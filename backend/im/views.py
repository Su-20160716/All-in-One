"""IM 视图：会话管理、成员、成员设置、消息收发、撤回、删除、转发、搜索、未读汇总"""
import csv
import io
import logging
from datetime import datetime, time as dtime, timedelta
from functools import reduce
from operator import or_
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, DateTimeField, F, Max, Min, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, ExtractHour
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from core.scoping import visible_user_ids
from core.validators import as_date, as_datetime, as_int, parse_bool
from im.models import ChatMessage, ChatSession, KeywordAlert, MessageFavorite, QuickReply, SessionMemberSetting, TodoItem
from im.serializers import (
    ChatMessageSerializer,
    MessageFavoriteSerializer,
    QuickReplySerializer,
    SessionSerializer,
    TodoItemSerializer,
)
from ws_app.events import broadcast_session, send_to_session

logger = logging.getLogger(__name__)


def _member_sessions(user):
    return ChatSession.objects.filter(members=user).distinct()


_EPOCH = timezone.make_aware(datetime(1970, 1, 1))


def _with_unread(qs, user):
    """给会话 queryset 标注 unread_count（单条 SQL，替代每个会话一次 COUNT）。

    阈值取该用户在该会话的 last_read_at；没有设置记录时回落到 1970 年，
    等价于「全部未读」。#82：已删除 / 已撤回 / 自己 deleted_for 的消息不计入，
    否则这些消息永远无法通过「已读」清零。
    """
    last_read = Subquery(
        SessionMemberSetting.objects.filter(session=OuterRef("pk"), user=user)
        .values("last_read_at")[:1]
    )
    threshold = Coalesce(last_read, Value(_EPOCH), output_field=DateTimeField())
    unread = Subquery(
        ChatMessage.objects.filter(session=OuterRef("pk"))
        .exclude(sender=user)
        .exclude(is_deleted=True)
        .exclude(is_recalled=True)
        .exclude(deleted_for=user)
        .filter(created_at__gt=threshold)
        .values("session").annotate(c=Count("id")).values("c")[:1]
    )
    return qs.annotate(unread_count=Coalesce(unread, 0))


def _visible_user_qs(user, ids):
    """#43：把候选成员收敛到当前用户可见范围。

    口径 = UserDirectory（在职且未禁用）∩ core.scoping 数据范围：
    - 默认 data_scope=self 只是「业务数据」范围，不应把通讯录缩成只有自己，
      此时沿用 UserDirectory 口径；
    - dept / dept_and_sub / all 返回了更大集合时按该集合收敛（含多租户收口）。
    """
    ids = {i for i in ids if i is not None}
    if not ids:
        return User.objects.none()
    qs = User.objects.filter(id__in=ids, is_active=True, is_disabled=False)
    # 多租户开启时，无论角色 data_scope 多宽都不得跨租户拉人
    if getattr(settings, "TENANCY_ENABLED", False):
        tenant_id = getattr(user, "tenant_id", None)
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
    allowed = visible_user_ids(user)
    if allowed is not None and allowed != {user.id}:
        qs = qs.filter(id__in=allowed)
    return qs


_ATTACHMENT_KEYS = {"name", "url", "size", "type"}
_ATTACHMENT_MAX_COUNT = 20
_ATTACHMENT_MAX_SIZE = 5 * 1024 * 1024 * 1024


def _clean_attachments(raw):
    """#44：附件白名单校验，返回 (cleaned, error)。

    最多 20 条；每项必须是对象且只含 name/url/size/type；url 仅 http(s)；
    name ≤255、url ≤2000、type ≤64、size 为非负数字。
    """
    if raw in (None, ""):
        return [], ""
    if not isinstance(raw, (list, tuple)):
        return None, "attachments 必须是数组"
    if len(raw) > _ATTACHMENT_MAX_COUNT:
        return None, f"附件最多 {_ATTACHMENT_MAX_COUNT} 个"
    cleaned = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, f"attachments[{idx}] 必须是对象"
        extra = set(item) - _ATTACHMENT_KEYS
        if extra:
            return None, f"attachments[{idx}] 含非法字段：{', '.join(sorted(extra))}"
        name = item.get("name", "")
        url = item.get("url", "")
        ftype = item.get("type", "")
        size = item.get("size", 0)
        if not isinstance(name, str) or not isinstance(url, str) or not isinstance(ftype, str):
            return None, f"attachments[{idx}] 的 name/url/type 必须是字符串"
        name, url, ftype = name.strip(), url.strip(), ftype.strip()
        if len(name) > 255 or len(url) > 2000 or len(ftype) > 64:
            return None, f"attachments[{idx}] 字段超长"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None, f"attachments[{idx}] 的 url 仅支持 http/https"
        if isinstance(size, bool) or not isinstance(size, (int, float)) \
                or size < 0 or size > _ATTACHMENT_MAX_SIZE:
            return None, f"attachments[{idx}] 的 size 非法"
        cleaned.append({"name": name, "url": url, "size": int(size), "type": ftype})
    return cleaned, ""


def _get_setting(session, user):
    obj, _ = SessionMemberSetting.objects.get_or_create(session=session, user=user)
    return obj


# #326 临时免打扰：mute_until 到期后按未静音处理，无需定时任务清理
MUTE_DURATION_CHOICES = ("1h", "8h", "tomorrow")


def _mute_active_q(now=None):
    """免打扰生效的查询条件：永久静音（mute_until 为空）或尚未到期。"""
    now = now or timezone.now()
    return Q(is_muted=True) & (Q(mute_until__isnull=True) | Q(mute_until__gt=now))


def _is_mute_active(setting, now=None):
    if not setting or not setting.is_muted:
        return False
    now = now or timezone.now()
    return not setting.mute_until or setting.mute_until > now


def _mute_until_for(duration):
    """#326：1h / 8h / tomorrow → 到期时间；返回 (datetime, 错误文案)。"""
    now = timezone.now()
    if duration == "1h":
        return now + timedelta(hours=1), ""
    if duration == "8h":
        return now + timedelta(hours=8), ""
    if duration == "tomorrow":
        # 「明天」= 本地时区次日 00:00 自动恢复
        local = timezone.localtime(now)
        next_day = local.date() + timedelta(days=1)
        return timezone.make_aware(datetime.combine(next_day, dtime.min)), ""
    return None, f"duration 仅支持 {'/'.join(MUTE_DURATION_CHOICES)}"


# #84：草稿是随「会话列表 / 草稿接口」一起返回的字段，无上限可被写入任意
# 大文本（几十万字），每次拉列表都要把它读出来并序列化。与消息正文同口径限制。
DRAFT_MAX_CHARS = 20000


def _clean_draft(raw):
    """#84：草稿统一校验，返回 (截断后的文本, 错误文案)。

    非字符串直接 400；超过 20000 字同样 400（避免把服务端当大文本存储），
    未超限时原样保存。写入方同时刷新 draft_updated_at。
    """
    if raw is None:
        return "", ""
    if not isinstance(raw, str):
        return None, "draft 必须是字符串"
    if len(raw) > DRAFT_MAX_CHARS:
        return None, f"草稿不能超过 {DRAFT_MAX_CHARS} 字"
    return raw, ""


def _kick_ws_from_session(session_id, user_id):
    """#33：成员被移出会话后，通知 WS 层把该用户的连接解绑会话组。

    NotifyConsumer 连接时一次性加入全部会话组，只删 m2m 不会解绑，
    被移出者仍能实时收到消息。这里向会话组广播一次 kick，目标连接自行
    group_discard 并断开重连（重连后按新成员关系重建组）。
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if not layer:
            return
        async_to_sync(layer.group_send)(
            f"session_{session_id}",
            {"type": "session_kick", "data": {"session_id": session_id, "user_id": user_id}},
        )
    except Exception:  # 广播失败不影响移除操作本身
        logger.exception("#33 WS kick 广播失败 session=%s user=%s", session_id, user_id)


class SessionListView(APIView):
    """会话列表（置顶优先）/ 创建单聊或群聊"""

    def get(self, request):
        archived = request.query_params.get("archived")
        # B6：prefetch members（members_info/member_count 共用）+ 最后一条消息
        # （to_attr 预取，避免每会话一次 order by 查询）
        # 每条会话只取「最后一条消息」：旧实现把每个会话的全部消息都预取进内存。
        # 先用相关子查询拿 last_message_id，再批量取这些消息（共 2 条 SQL）。
        last_msg_id = (
            ChatMessage.objects.filter(session=OuterRef("pk"))
            .exclude(is_recalled=True)
            .order_by("-created_at")
            .values("id")[:1]
        )
        sessions = list(
            _with_unread(_member_sessions(request.user), request.user)
            .annotate(last_message_id=Subquery(last_msg_id))
            .prefetch_related("members")
        )
        msg_ids = [s.last_message_id for s in sessions if s.last_message_id]
        last_msgs = {
            m.id: m
            for m in ChatMessage.objects.filter(id__in=msg_ids).select_related("sender")
        } if msg_ids else {}
        for s in sessions:
            msg = last_msgs.get(s.last_message_id)
            s._last_messages = [msg] if msg else []
        data = SessionSerializer(sessions, many=True, context={"request": request}).data
        # #83：排序必须用模型 datetime（序列化后的 created_at 是字符串，
        # 旧实现 hasattr(last, "timestamp") 恒 False，所有会话排序值都是 0）。
        pairs = list(zip(sessions, data))
        # 归档过滤：archived=1 仅归档；默认仅未归档
        if archived == "1":
            pairs = [p for p in pairs if p[1]["is_archived"]]
        elif archived == "all":
            pass
        else:
            pairs = [p for p in pairs if not p[1]["is_archived"]]
        # 标签过滤（会话设置里的自定义分组标签）
        # #315：tag 单选保持兼容，新增 tags 多选并集（支持逗号分隔或重复传参）
        raw_tags = []
        try:
            raw_tags = request.query_params.getlist("tags")
        except AttributeError:  # 非 QueryDict（测试里直接传 dict）时退化为单值
            single_raw = request.query_params.get("tags")
            raw_tags = [single_raw] if single_raw else []
        tag_values = []
        for chunk in raw_tags:
            tag_values.extend(str(chunk).split(","))
        single_tag = (request.query_params.get("tag") or "").strip()
        if single_tag:
            tag_values.append(single_tag)
        active_tags = list(dict.fromkeys(t.strip() for t in tag_values if t and t.strip()))
        if active_tags:
            pairs = [p for p in pairs if set(active_tags) & set(p[1].get("tags") or [])]
        # #315：随列表下发可用标签集合（一次查询，供前端渲染 chips）
        available_tags = []
        for tags in (
            SessionMemberSetting.objects.filter(user=request.user)
            .exclude(tags=[]).values_list("tags", flat=True)
        ):
            for t in tags or []:
                if t and t not in available_tags:
                    available_tags.append(t)
        available_tags = available_tags[:100]
        # 关键字过滤（会话名 / 对方名）
        kw = (request.query_params.get("search") or "").strip()
        if kw:
            pairs = [
                p for p in pairs
                if kw in p[1].get("name", "")
                or kw in (p[1].get("last_message", {}) or {}).get("content", "")
            ]

        def _last_dt(session):
            cached = getattr(session, "_last_messages", None)
            if cached:
                return cached[0].created_at
            return session.created_at

        # 置顶在前（#327 按 pin_order 自定义排序），再按最后消息时间
        pairs.sort(key=lambda p: (
            0 if p[1]["is_pinned"] else 1,
            (p[1].get("pin_order") or 0) if p[1]["is_pinned"] else 0,
            -_last_dt(p[0]).timestamp(),
        ))
        data = [d for _, d in pairs]
        # #37：随会话列表下发短时一次性 WS ticket，前端用 /ws/notify/?ticket= 握手，
        # 避免 access token 长期出现在查询串（Daphne/Nginx 访问日志、浏览器历史）。
        from ws_app.middleware import mint_ws_ticket

        return Response({
            "list": data, "total": len(data),
            "tags": available_tags, "active_tags": active_tags,
            "ws_ticket": mint_ws_ticket(request.user),
        })

    def post(self, request):
        stype = request.data.get("type", "single")
        if stype == "direct":
            stype = "single"
        raw_ids = request.data.get("member_ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "member_ids 必须是数组"}, status=400)
        if len(raw_ids) > 200:
            return Response({"message": "单次最多选择 200 人"}, status=400)
        try:
            member_ids = [as_int(x, field="member_ids", minimum=1) for x in raw_ids]
        except ValidationError:
            return Response({"message": "member_ids 必须全部为整数"}, status=400)
        if stype == "single":
            other_id = member_ids[0] if member_ids else None
            # #84：禁止与自己建单聊
            if other_id == request.user.id:
                return Response({"message": "不能和自己创建单聊"}, status=400)
            other = _visible_user_qs(request.user, [other_id]).first() if other_id else None
            if not other:
                return Response({"message": "对方不存在或不可见"}, status=400)
            # #61：单聊去重键 = "min_id:max_id"，DB 唯一约束兜底并发重复建会话
            pair_key = f"{min(request.user.id, other.id)}:{max(request.user.id, other.id)}"
            with transaction.atomic():
                # 先锁住双方用户行（配合 pair_key 唯一约束双重去重）
                list(
                    User.objects.select_for_update()
                    .filter(id__in=sorted({request.user.id, other.id}))
                    .order_by("id")
                )
                exist = (
                    ChatSession.objects.filter(type="single", members=request.user)
                    .filter(members=other)
                    .first()
                )
                if not exist:
                    # pair_key 可能已被并发请求写入，优先按 key 回查
                    exist = ChatSession.objects.filter(pair_key=pair_key).first()
                if exist:
                    # 历史单聊没有 pair_key，回填后后续并发才真正被唯一约束拦住
                    if not exist.pair_key:
                        try:
                            with transaction.atomic():
                                exist.pair_key = pair_key
                                exist.save(update_fields=["pair_key"])
                        except IntegrityError:
                            pass
                    # 对方可能「退出」过单聊（= 归档），重新发起时恢复显示
                    setting = _get_setting(exist, request.user)
                    if setting.is_archived:
                        setting.is_archived = False
                        setting.save(update_fields=["is_archived"])
                    return Response(SessionSerializer(exist, context={"request": request}).data)
                try:
                    with transaction.atomic():
                        session = ChatSession.objects.create(type="single", owner=request.user, pair_key=pair_key)
                except IntegrityError:
                    # 并发下另一个请求已建成：回查并复用，不产生重复单聊
                    session = ChatSession.objects.filter(pair_key=pair_key).first()
                    if session is None:
                        raise
                session.members.add(request.user, other)
        else:
            # #43：成员必须落在当前用户的可见范围（同部门/同租户），且拒绝不存在/不可见 id
            requested = set(member_ids) - {request.user.id}
            users = list(_visible_user_qs(request.user, requested).order_by("id"))
            invalid = requested - {u.id for u in users}
            if invalid:
                return Response({"message": "包含无效或不可见的成员"}, status=400)
            name = str(request.data.get("name") or "未命名群聊").strip()
            session = ChatSession.objects.create(type="group", name=name, owner=request.user,
                                                 announcement=request.data.get("announcement", ""))
            session.members.add(request.user)
            session.members.add(*users)
            send_to_session(session.id, {
                "type": "group.system",
                "data": {"content": f"{request.user.display_name} 创建了群聊「{name}」", "session_id": session.id},
            })
        return Response(SessionSerializer(session, context={"request": request}).data, status=201)


class SessionDetailView(APIView):
    """会话详情 / 更新群信息"""

    def _get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        return s

    def get(self, request, pk):
        s = self._get(request, pk)
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        return Response(SessionSerializer(s, context={"request": request}).data)

    def patch(self, request, pk):
        s = self._get(request, pk)
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type == "group" and s.owner_id != request.user.id:
            return Response({"message": "仅群主可修改群信息"}, status=403)
        for f in ("name", "announcement", "avatar"):
            if f in request.data:
                setattr(s, f, request.data[f])
        s.save()
        broadcast_session(s.id, {"type": "session.updated", "data": {"session_id": s.id}})
        return Response(SessionSerializer(s, context={"request": request}).data)


class SessionMemberView(APIView):
    """添加 / 移除群成员"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type != "group":
            return Response({"message": "单聊不能添加成员"}, status=400)
        # 群主校验：仅群主可邀请成员（原来任意成员都能拉人）
        if s.owner_id != request.user.id:
            return Response({"message": "仅群主可邀请成员"}, status=403)
        raw_ids = request.data.get("member_ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "member_ids 必须是数组"}, status=400)
        if len(raw_ids) > 50:
            return Response({"message": "单次最多邀请 50 人"}, status=400)
        try:
            ids = {as_int(x, field="member_ids") for x in raw_ids}
        except ValidationError as exc:
            return Response({"message": "member_ids 必须全部为整数"}, status=400)
        # #32：邀请对象必须落在当前用户可见范围（启用中、同租户/同部门），
        # 拒绝不存在的 id，避免把禁用或跨租户用户拉进群读历史。
        users = list(_visible_user_qs(request.user, ids).order_by("id"))
        invalid = ids - {u.id for u in users}
        if invalid:
            return Response({"message": "包含无效或不可见的成员"}, status=400)
        # 去重：已在群内的不再重复添加（系统消息数量也才准确）
        existing = set(s.members.values_list("id", flat=True))
        fresh = [u for u in users if u.id not in existing]
        if not fresh:
            return Response({"message": "没有新成员可添加"})
        with transaction.atomic():
            s.members.add(*fresh)
            for u in fresh:
                _get_setting(s, u)
        # #119：成员变化后失效「成员名集合」缓存，保证新成员立刻可被 @ 到
        _invalidate_mention_names(s.id)
        send_to_session(s.id, {"type": "group.system",
                               "data": {"content": f"{request.user.display_name} 邀请 {len(fresh)} 人入群"}})
        return Response({"message": f"已添加 {len(fresh)} 名成员"})

    def delete(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        try:
            target_id = as_int(request.query_params.get("user_id"), field="user_id")
        except ValidationError:
            return Response({"message": "user_id 必须是整数"}, status=400)
        if s.owner_id != request.user.id and target_id != request.user.id:
            return Response({"message": "仅群主可移除成员"}, status=403)
        # #85：群主永远不能被移出成员表，否则 owner 指向一个不在群里的用户
        if target_id == s.owner_id:
            return Response({"message": "不能移除群主，请先转让群主"}, status=400)
        user = User.objects.filter(id=target_id).first()
        if user:
            s.members.remove(user)
            # #119：成员变化后失效「成员名集合」缓存
            _invalidate_mention_names(s.id)
            # #33：被移出者的长连接立即解绑会话组，不再收到该会话消息
            _kick_ws_from_session(s.id, user.id)
            send_to_session(s.id, {"type": "group.system", "data": {"content": f"{user.display_name} 被移出群聊"}})
        return Response({"message": "成员已移除"})


class SessionLeaveView(APIView):
    """退出群聊；群主退出则解散群（或先转让）"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type == "single":
            # 单聊「删除」只对当前用户归档：直接删会话会级联删掉对方的历史消息
            setting = _get_setting(s, request.user)
            setting.is_archived = True
            setting.is_pinned = False
            setting.save(update_fields=["is_archived", "is_pinned"])
            return Response({"message": "会话已从列表移除"})
        if s.owner_id == request.user.id:
            # 群主退出 → 解散群
            send_to_session(s.id, {"type": "group.system", "data": {"content": "群主已解散该群聊"}})
            s.delete()
            return Response({"message": "群聊已解散"})
        s.members.remove(request.user)
        # #33：主动退群同样要解绑本人长连接的会话组
        _kick_ws_from_session(s.id, request.user.id)
        send_to_session(s.id, {"type": "group.system", "data": {"content": f"{request.user.display_name} 退出了群聊"}})
        return Response({"message": "已退出群聊"})


class SessionTransferView(APIView):
    """转让群主"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk).first()
        if not s or s.owner_id != request.user.id:
            return Response({"message": "仅群主可转让"}, status=403)
        try:
            new_owner_id = as_int(request.data.get("user_id"), field="user_id", minimum=1)
        except ValidationError:
            return Response({"message": "user_id 必须是整数"}, status=400)
        new_owner = s.members.filter(id=new_owner_id).first()
        if not new_owner:
            return Response({"message": "新群主必须是群成员"}, status=400)
        s.owner = new_owner
        s.save(update_fields=["owner"])
        send_to_session(s.id, {"type": "group.system", "data": {"content": f"群主已转让给 {new_owner.display_name}"}})
        return Response({"message": "转让成功"})


class SessionSettingView(APIView):
    """成员会话设置：免打扰 / 置顶 / 草稿 / 标记已读"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        changed = []
        for f in ("is_muted", "is_pinned", "is_archived"):
            if f in request.data:
                setattr(setting, f, parse_bool(request.data[f], field=f))
                changed.append(f)
        if "is_muted" in changed:
            if not setting.is_muted:
                # #326：关闭免打扰同时清掉临时到期时间
                setting.mute_until = None
                changed.append("mute_until")
            elif setting.mute_until and setting.mute_until <= timezone.now():
                # 已过期的临时静音再被置为 is_muted=true 时转为永久，避免状态自相矛盾
                setting.mute_until = None
                changed.append("mute_until")
        if "draft" in request.data:
            # #84：20000 字上限，超长直接 400；保存时同步刷新 draft_updated_at
            draft, err = _clean_draft(request.data.get("draft"))
            if err:
                return Response({"message": err}, status=400)
            setting.draft = draft
            setting.draft_updated_at = timezone.now()
            changed.extend(["draft", "draft_updated_at"])
        if "tags" in request.data:
            raw = request.data["tags"]
            if not isinstance(raw, (list, tuple)):
                return Response({"message": "tags 必须是数组"}, status=400)
            tags = []
            for t in raw:
                val = str(t or "").strip()[:20]
                if val and val not in tags:
                    tags.append(val)
            setting.tags = tags[:10]
            changed.append("tags")
        # #327：置顶排序权重，仅在 is_pinned 时参与列表排序
        if "pin_order" in request.data:
            try:
                setting.pin_order = as_int(request.data["pin_order"], field="pin_order",
                                           minimum=-100000, maximum=100000)
            except ValidationError:
                return Response({"message": "pin_order 必须是整数"}, status=400)
            changed.append("pin_order")
        if request.data.get("mark_read"):
            setting.last_read_at = timezone.now()
            changed.append("last_read_at")
        setting.save()
        return Response({"message": "设置已更新", "is_muted": _is_mute_active(setting),
                         "is_pinned": setting.is_pinned, "is_archived": setting.is_archived,
                         "draft": setting.draft, "tags": list(setting.tags or []),
                         "pin_order": setting.pin_order, "mute_until": setting.mute_until})


class SessionPinOrderView(APIView):
    """#327 置顶会话拖拽排序：按提交顺序重写 pin_order"""

    MAX_ITEMS = 200

    def post(self, request):
        items = request.data.get("items")
        if items is None:
            # 兼容 {order: [session_id, ...]}：数组下标即新的 pin_order
            order = request.data.get("order")
            if not isinstance(order, (list, tuple)):
                return Response({"message": "items 必须是数组"}, status=400)
            items = [{"session_id": sid, "pin_order": idx} for idx, sid in enumerate(order)]
        if not isinstance(items, (list, tuple)):
            return Response({"message": "items 必须是数组"}, status=400)
        if len(items) > self.MAX_ITEMS:
            return Response({"message": f"单次最多调整 {self.MAX_ITEMS} 个会话"}, status=400)
        parsed = []
        for row in items:
            if not isinstance(row, dict):
                return Response({"message": "items 每项必须是对象"}, status=400)
            try:
                sid = as_int(row.get("session_id"), field="session_id", minimum=1)
                porder = as_int(row.get("pin_order"), field="pin_order",
                                minimum=-100000, maximum=100000)
            except ValidationError:
                return Response({"message": "session_id / pin_order 必须是整数"}, status=400)
            parsed.append((sid, porder))
        if not parsed:
            return Response({"message": "没有需要排序的会话", "updated": 0})
        # 只允许调整本人所在会话的设置，且一次查询取回
        settings_map = {
            s.session_id: s
            for s in SessionMemberSetting.objects.filter(
                user=request.user, session_id__in=[sid for sid, _ in parsed]
            )
        }
        to_update = []
        for sid, porder in parsed:
            setting = settings_map.get(sid)
            if not setting:
                continue
            setting.pin_order = porder
            # 参与拖拽排序即视为置顶
            setting.is_pinned = True
            to_update.append(setting)
        if to_update:
            SessionMemberSetting.objects.bulk_update(
                to_update, ["pin_order", "is_pinned"], batch_size=200
            )
        return Response({"message": f"已更新 {len(to_update)} 个会话排序", "updated": len(to_update)})


class MessageListView(APIView):
    """消息历史（对自己删除的不返回），支持会话内搜索 / 按发送者 / 时间范围过滤"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        # 置顶消息区（与历史分开返回）
        pinned = list(
            s.messages.filter(is_pinned=True).exclude(deleted_for=request.user)
            .exclude(is_recalled=True).exclude(is_deleted=True).order_by("-created_at")
            .select_related("sender", "reply_to", "reply_to__sender")
        )
        qs = s.messages.exclude(deleted_for=request.user).exclude(is_deleted=True).exclude(is_recalled=True)
        kw = request.query_params.get("q")
        if kw:
            qs = qs.filter(content__icontains=kw)
        msg_type = request.query_params.get("msg_type")
        if msg_type:
            qs = qs.filter(msg_type=msg_type)
        sender = request.query_params.get("sender")
        if sender:
            qs = qs.filter(sender_id=as_int(sender, field="sender"))
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=as_date(date_from, field="date_from"))
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=as_date(date_to, field="date_to"))
        before = request.query_params.get("before")
        if before:
            qs = qs.filter(id__lt=as_int(before, field="before"))
        # B6：sender / reply_to / reply_to.sender 全部 select_related，
        # 避免每条消息 2-3 次 sender 查询
        # B19：total 取过滤后总量（切片前 count）——原来是 len(本页数据)，
        # 命中 50 条上限时恒等于 50，名不副实；前端未消费该字段，改语义零影响
        total = qs.count()
        qs = qs.select_related("sender", "reply_to", "reply_to__sender").order_by("-id")[:50]
        data = ChatMessageSerializer(list(qs)[::-1], many=True, context={"request": request}).data
        pinned_data = ChatMessageSerializer(pinned, many=True, context={"request": request}).data
        return Response({"list": data, "total": total, "pinned": pinned_data})


class SessionFilesView(APIView):
    """#329 会话文件聚合：把消息里的附件摊平成文件列表，支持类型 / 发送者筛选"""

    MAX_SCAN = 2000          # 最多扫描的带附件消息条数（防止超大群一次拉爆）
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        qs = (
            s.messages.exclude(deleted_for=request.user)
            .exclude(is_deleted=True).exclude(is_recalled=True)
            .exclude(attachments=[])
        )
        sender = request.query_params.get("sender")
        if sender:
            try:
                qs = qs.filter(sender_id=as_int(sender, field="sender"))
            except ValidationError:
                return Response({"message": "sender 必须是整数"}, status=400)
        ftype = (request.query_params.get("type") or "").strip().lower()
        msgs = list(
            qs.select_related("sender").order_by("-id")[: self.MAX_SCAN]
        )
        truncated = len(msgs) >= self.MAX_SCAN
        rows = []
        for m in msgs:
            sender_name = m.sender.display_name if m.sender else "系统"
            for att in (m.attachments or []):
                if not isinstance(att, dict):
                    continue
                mime = str(att.get("type") or "").lower()
                name = str(att.get("name") or "")
                if ftype:
                    if ftype == "image":
                        if not mime.startswith("image/"):
                            continue
                    elif ftype == "file":
                        if mime.startswith("image/"):
                            continue
                    elif ftype not in mime and ftype not in name.lower():
                        continue
                rows.append({
                    "message_id": m.id, "session_id": s.id,
                    "sender_id": m.sender_id, "sender_name": sender_name,
                    "name": name, "url": att.get("url") or "",
                    "size": att.get("size") or 0, "type": mime,
                    "category": "image" if mime.startswith("image/") else "file",
                    "created_at": m.created_at,
                })
        total = len(rows)
        try:
            page = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
            page_size = as_int(request.query_params.get("page_size"), default=self.DEFAULT_PAGE_SIZE,
                               field="page_size", minimum=1, maximum=self.MAX_PAGE_SIZE)
        except ValidationError:
            return Response({"message": "page / page_size 必须是整数"}, status=400)
        start = (page - 1) * page_size
        return Response({
            "session_id": s.id, "list": rows[start:start + page_size], "total": total,
            "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
            "truncated": truncated,
        })


_MESSAGE_MAX_CHARS = 20000
_MESSAGE_TYPES = {t[0] for t in ChatMessage.TYPE_CHOICES}


def _validate_message_payload(content, msg_type):
    """#34：消息正文 / 类型的统一校验（创建与编辑共用）。

    返回错误文案；空串表示通过。系统消息只能由服务端产生，客户端伪造会冒充官方通知。
    """
    if not isinstance(content, str):
        return "content 必须是字符串"
    if msg_type == "system":
        return "不允许发送系统消息"
    if msg_type not in _MESSAGE_TYPES:
        return "msg_type 非法"
    if len(content) > _MESSAGE_MAX_CHARS:
        return f"消息内容不能超过 {_MESSAGE_MAX_CHARS} 字"
    return ""


class MessageCreateView(APIView):
    """发送消息（文本/图片/文件/系统），支持转发"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在或你不在会话中"}, status=404)
        content = request.data.get("content", "")
        msg_type = request.data.get("msg_type", "text")
        # #34：与编辑路径共用同一校验（字符串 / 类型白名单 / 20000 字上限）
        err = _validate_message_payload(content, msg_type)
        if err:
            # 伪造系统消息保持原 403 语义，其余非法入参 400
            return Response({"message": err}, status=403 if msg_type == "system" else 400)
        forward_id = as_int(request.data.get("forward_from"), default=None, field="forward_from") if request.data.get("forward_from") else None
        forward = ChatMessage.objects.filter(id=forward_id, session__members=request.user).first() if forward_id else None
        reply_id = as_int(request.data.get("reply_to"), default=None, field="reply_to") if request.data.get("reply_to") else None
        reply = ChatMessage.objects.filter(id=reply_id, session=s).first() if reply_id else None
        if not content and msg_type == "text" and not forward:
            return Response({"message": "消息内容不能为空"}, status=400)
        # #44：附件白名单校验（条数 / 字段 / 协议 / 长度），脏数据直接 400
        attachments, att_err = _clean_attachments(request.data.get("attachments"))
        if att_err:
            return Response({"message": att_err}, status=400)
        msg = ChatMessage.objects.create(
            session=s, sender=request.user, content=content, msg_type=msg_type,
            attachments=attachments, forward_from=forward, reply_to=reply,
        )
        # 给已归档会话发消息 = 主动恢复显示
        setting = _get_setting(s, request.user)
        if setting.is_archived:
            setting.is_archived = False
            setting.save(update_fields=["is_archived"])
        send_to_session(s.id, {"type": "chat.message", "data": ChatMessageSerializer(msg, context={"request": request}).data})
        # 非免打扰成员推送通知（一次查偏好 + 一次 bulk_create，避免群发 N 次 SQL）
        # #326：mute_until 已过期的设置视为未静音
        muted_ids = set(
            SessionMemberSetting.objects.filter(session=s).filter(_mute_active_q())
            .values_list("user_id", flat=True)
        )
        from core.models import notify_many
        notify_many(
            [u for u in s.members.exclude(id=request.user.id) if u.id not in muted_ids],
            f"新消息：{request.user.display_name}", content[:80], category="message", link=f"/im/{s.id}",
        )
        # 关键词提醒：对命中关键词的成员额外推送一条醒目通知
        if msg_type == "text" and content:
            _fire_keyword_alerts(s, msg)
            _fire_mentions(s, msg)
        return Response(ChatMessageSerializer(msg, context={"request": request}).data, status=201)


def _fire_keyword_alerts(session, msg):
    """对会话内配置了关键词提醒的成员，若消息内容命中其关键词则推送通知中心

    #118：原来每条命中都单独调一次 notify（每次 exists + INSERT），一条消息
    命中 N 人就 N 次 SQL。改为先收集命中，再按「命中词组合」分组批量
    notify_many（一次查偏好 + 一次 bulk_create），通常只有 1 次写入。
    """
    from core.models import notify_many

    content = msg.content or ""
    if not content:
        return
    content_lower = content.lower()
    groups = {}
    settings = (
        KeywordAlert.objects.filter(owner__in=session.members.all())
        .exclude(owner_id=msg.sender_id)
        .select_related("owner")
    )
    for setting in settings:
        hits = [kw for kw in (setting.keywords or []) if kw and kw.lower() in content_lower]
        if not hits:
            continue
        # 通知标题带命中词，所以按命中词组合分组；同一用户多条规则只提醒一次
        key = tuple(dict.fromkeys(hits[:3]))
        groups.setdefault(key, {})[setting.owner_id] = setting.owner
    if not groups:
        return
    sender_name = msg.sender.display_name if msg.sender else "某人"
    for hits, owners in groups.items():
        notify_many(
            list(owners.values()),
            f"关键词提醒：{', '.join(hits)}",
            f"来自 {sender_name}：{content[:100]}",
            category="message",
            level="warning",
            link=f"/im/{session.id}",
        )


# #119：成员名集合缓存 TTL（成员增删时主动失效，这里只是兜底）
MENTION_NAMES_TTL_SECONDS = 60


def _mention_names(session):
    """#119：会话成员「id → 展示名」短时缓存。

    原来每条含 @ 的消息都要遍历全部成员并对每个成员取 display_name，
    群越大越慢。这里一次取回 (id, nickname, username) 并缓存 60 秒，
    成员增删时由 SessionMemberView 主动删除缓存键。
    """
    key = f"im:mention_names:{session.pk}"
    try:
        cached = cache.get(key)
    except Exception:  # cache 后端不可用时退化为直接查库
        cached = None
    if cached is not None:
        return cached
    names = [
        (uid, nickname or username)
        for uid, nickname, username in session.members.values_list("id", "nickname", "username")
    ]
    try:
        cache.set(key, names, MENTION_NAMES_TTL_SECONDS)
    except Exception:
        logger.exception("#119 成员名缓存写入失败 session=%s", session.pk)
    return names


def _invalidate_mention_names(session_id):
    """#119：成员增删后立即失效，避免 60 秒内 @ 不到新成员"""
    try:
        cache.delete(f"im:mention_names:{session_id}")
    except Exception:
        logger.exception("#119 成员名缓存失效失败 session=%s", session_id)


def _mentioned_users(session, content):
    """F607 解析消息中的 @提及：返回被提及的会话成员列表

    #119：只在正文含 @ 时才解析（否则直接返回），成员名取自缓存，
    命中后再按 id 一次性取回用户对象，不再遍历全群成员。
    """
    if not content or "@" not in content:
        return []
    hit_ids = [uid for uid, name in _mention_names(session) if name and f"@{name}" in content]
    if not hit_ids:
        return []
    return list(User.objects.filter(id__in=hit_ids))


def _can_mention_all(session, user) -> bool:
    """#36：@所有人 仅群主 / 管理员可用；普通成员走频控。"""
    return (
        session.owner_id == getattr(user, "id", None)
        or getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
    )


MENTION_ALL_WINDOW_SECONDS = 5 * 60


def _fire_mentions(session, msg):
    """F607 对被 @提及的成员推送通知中心消息"""
    from core.models import notify_many

    content = msg.content or ""
    if "@所有人" in content or "@all" in content.lower():
        sender = msg.sender
        if sender is None:
            return
        # #36：普通成员每群 5 分钟最多 @所有人 1 次，防止通知轰炸
        if not _can_mention_all(session, sender):
            key = f"im:atall:{session.id}:{sender.id}"
            try:
                if cache.get(key):
                    return  # 窗口内已用过：不再向全群推送
                cache.set(key, 1, MENTION_ALL_WINDOW_SECONDS)
            except Exception:  # cache 不可用时放行（不阻断正常消息）
                pass
        notify_many(
            list(session.members.exclude(id=msg.sender_id)),
            f"{msg.sender.display_name if msg.sender else '某人'} 在「{session.name or '会话'}」提到了所有人",
            content[:100], category="message", level="warning", link=f"/im/{session.id}",
        )
        return
    # #119：@ 提醒同样批量落库（一次查偏好 + 一次 bulk_create），不再逐人 notify
    mentioned = [u for u in _mentioned_users(session, content) if u.id != msg.sender_id]
    if not mentioned:
        return
    notify_many(
        mentioned,
        f"{msg.sender.display_name if msg.sender else '某人'} 在「{session.name or '会话'}」提到了你",
        content[:100], category="message", level="warning", link=f"/im/{session.id}",
    )


class MessageRecallView(APIView):
    """撤回消息（发送者，2 分钟内）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        if msg.sender_id != request.user.id:
            return Response({"message": "只能撤回自己的消息"}, status=403)
        if timezone.now() - msg.created_at > timezone.timedelta(minutes=2):
            return Response({"message": "超过 2 分钟不可撤回"}, status=400)
        msg.is_recalled = True
        msg.save(update_fields=["is_recalled"])
        send_to_session(msg.session_id, {"type": "message.recalled", "data": {"id": msg.id, "session_id": msg.session_id}})
        return Response({"message": "消息已撤回"})


class MessageDeleteView(APIView):
    """删除消息（仅对自己隐藏）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        msg.deleted_for.add(request.user)
        return Response({"message": "已删除"})


class MessageForwardView(APIView):
    """转发消息到其它会话（#324 支持 session_ids 批量，返回逐会话成功/失败明细）"""

    MAX_TARGETS = 20

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        target_ids = request.data.get("session_ids") or []
        if not isinstance(target_ids, (list, tuple)):
            return Response({"message": "session_ids 必须是数组"}, status=400)
        try:
            # #35：去重后再限流，避免同一会话重复转发 / 一次请求无限建消息
            ids = list(dict.fromkeys(as_int(x, field="session_ids", minimum=1) for x in target_ids))
        except ValidationError:
            return Response({"message": "session_ids 必须全部为整数"}, status=400)
        if len(ids) > self.MAX_TARGETS:
            return Response({"message": f"单次最多转发到 {self.MAX_TARGETS} 个会话"}, status=400)
        # 一次查出可转发的目标会话，避免逐个会话一次查询
        targets = {
            t.id: t for t in ChatSession.objects.filter(id__in=ids, members=request.user)
        }
        results, created = [], []
        for sid in ids:
            target = targets.get(sid)
            if not target:
                results.append({"session_id": sid, "success": False,
                                "error": "会话不存在或无权访问"})
                continue
            new_msg = ChatMessage.objects.create(
                session=target, sender=request.user, content=msg.content, msg_type=msg.msg_type,
                attachments=msg.attachments, forward_from=msg,
            )
            send_to_session(target.id, {"type": "chat.message", "data": ChatMessageSerializer(new_msg).data})
            created.append(new_msg.id)
            results.append({"session_id": sid, "success": True, "message_id": new_msg.id,
                            "session_name": target.name or "单聊"})
        failed = [r for r in results if not r["success"]]
        return Response({
            "message": f"已转发到 {len(created)} 个会话" + (f"，{len(failed)} 个失败" if failed else ""),
            "message_ids": created,
            "results": results,
            "success_count": len(created),
            "failed_count": len(failed),
            "failed": failed,
        })


class GlobalMessageSearchView(APIView):
    """跨全部会话搜索消息，支持按发送者 / 类型 / 日期区间 / 含附件过滤

    #320：新增 page / page_size 分页，total 改为过滤后真实总数（切片前计数），
    并返回 pages / has_more 供前端翻页。
    """

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = settings.PAGE_SIZE_MAX

    def get(self, request):
        kw = (request.query_params.get("q") or "").strip()
        qs = (
            ChatMessage.objects.filter(session__members=request.user)
            .exclude(deleted_for=request.user)
            .exclude(is_deleted=True)
            .exclude(is_recalled=True)
        )
        if kw:
            qs = qs.filter(content__icontains=kw)
        sender = request.query_params.get("sender")
        if sender:
            qs = qs.filter(sender_id=as_int(sender, field="sender"))
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=as_date(date_from, field="date_from"))
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=as_date(date_to, field="date_to"))
        msg_type = (request.query_params.get("msg_type") or "").strip()
        if msg_type:
            qs = qs.filter(msg_type=msg_type)
        has_attachment = request.query_params.get("has_attachment")
        if has_attachment not in (None, ""):
            if parse_bool(has_attachment, field="has_attachment"):
                qs = qs.exclude(attachments=[])
            else:
                qs = qs.filter(attachments=[])
        if not kw and not sender and not date_from and not date_to and not msg_type \
                and has_attachment in (None, ""):
            return Response({"list": [], "total": 0, "page": 1,
                             "page_size": self.DEFAULT_PAGE_SIZE, "pages": 0, "has_more": False})
        try:
            page = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
            page_size = as_int(request.query_params.get("page_size"),
                               default=self.DEFAULT_PAGE_SIZE, field="page_size",
                               minimum=1, maximum=self.MAX_PAGE_SIZE)
        except ValidationError:
            return Response({"message": "page / page_size 必须是整数"}, status=400)
        # #114：session / sender / 引用消息及其发送者一次查出，整批序列化避免逐条查询
        # 注：SearchDoc 目前只有 note/file/project/task/code/snippet 六个 module，
        # 消息未入倒排索引（需改 core 的索引与信号），故这里仍用 icontains。
        total = qs.count()
        start = (page - 1) * page_size
        messages = list(
            qs.select_related("session", "sender", "reply_to", "reply_to__sender")
            .order_by("-id")[start:start + page_size]
        )
        data = ChatMessageSerializer(messages, context={"request": request}, many=True).data
        for row, m in zip(data, messages):
            row["session_name"] = m.session.name or "单聊"
        pages = (total + page_size - 1) // page_size if total else 0
        return Response({
            "list": data, "total": total, "page": page, "page_size": page_size,
            "pages": pages, "has_more": start + len(messages) < total,
        })


class UnreadSummaryView(APIView):
    """未读消息汇总（免打扰会话单独计数）"""

    def get(self, request):
        # B6：原来每个会话 2 次查询（setting + COUNT）；现在未读数由一条
        # 带相关子查询的注解算出，设置一次批量取出
        sessions = _with_unread(_member_sessions(request.user), request.user)
        settings = {
            s.session_id: s for s in SessionMemberSetting.objects.filter(user=request.user)
        }
        total, muted_total, per_session = 0, 0, {}
        for s in sessions:
            n = s.unread_count or 0
            per_session[s.id] = n
            setting = settings.get(s.id)
            # #326：mute_until 已过期的设置按未静音计入
            if _is_mute_active(setting):
                muted_total += n
            else:
                total += n
        return Response({"unread": total, "muted_unread": muted_total, "per_session": per_session})


# ============ 消息置顶 ============

class MessagePinView(APIView):
    """置顶 / 取消置顶一条消息（会话成员均可操作）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        msg.is_pinned = not msg.is_pinned
        msg.save(update_fields=["is_pinned"])
        send_to_session(msg.session_id, {
            "type": "message.pinned",
            "data": {"id": msg.id, "session_id": msg.session_id, "is_pinned": msg.is_pinned},
        })
        return Response({"message": "已置顶" if msg.is_pinned else "已取消置顶", "is_pinned": msg.is_pinned})


# ============ 快捷回复模板 ============

QUICK_REPLY_MAX = 500


def _clean_qr_group(raw):
    """#319：分组名统一收敛（去空白、最长 60 字）"""
    return str(raw or "").strip()[:60]


def _clean_qr_sort(raw):
    return as_int(raw, default=0, field="sort_order", minimum=-100000, maximum=100000)


class QuickReplyListView(APIView):
    """快捷回复列表 / 新增（#319 支持分组与排序）"""

    def get(self, request):
        qs = QuickReply.objects.filter(owner=request.user)
        group = (request.query_params.get("group") or "").strip()
        if group:
            qs = qs.filter(group=group)
        # 一次查询取回分组列表，供前端渲染分组标题
        groups = [
            g for g in QuickReply.objects.filter(owner=request.user)
            .order_by("group").values_list("group", flat=True).distinct() if g
        ]
        return Response({
            "list": QuickReplySerializer(qs, many=True).data,
            "total": qs.count(), "groups": groups,
        })

    def post(self, request):
        content = str(request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "内容不能为空"}, status=400)
        if QuickReply.objects.filter(owner=request.user).count() >= QUICK_REPLY_MAX:
            return Response({"message": f"快捷回复最多 {QUICK_REPLY_MAX} 条"}, status=400)
        try:
            sort_order = _clean_qr_sort(request.data.get("sort_order", 0))
        except ValidationError:
            return Response({"message": "sort_order 必须是整数"}, status=400)
        qr = QuickReply.objects.create(
            owner=request.user, title=str(request.data.get("title") or "")[:120], content=content,
            sort_order=sort_order, group=_clean_qr_group(request.data.get("group")),
        )
        return Response(QuickReplySerializer(qr).data, status=201)


class QuickReplyDetailView(APIView):
    def _get(self, request, pk):
        return QuickReply.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        qr = self._get(request, pk)
        if not qr:
            return Response({"message": "模板不存在"}, status=404)
        for f in ("title", "content"):
            if f in request.data:
                setattr(qr, f, str(request.data[f] or ""))
        if "group" in request.data:
            qr.group = _clean_qr_group(request.data.get("group"))
        if "sort_order" in request.data:
            try:
                qr.sort_order = _clean_qr_sort(request.data.get("sort_order"))
            except ValidationError:
                return Response({"message": "sort_order 必须是整数"}, status=400)
        qr.save()
        return Response(QuickReplySerializer(qr).data)

    def delete(self, request, pk):
        qr = self._get(request, pk)
        if not qr:
            return Response({"message": "模板不存在"}, status=404)
        qr.delete()
        return Response({"message": "已删除"})


class QuickReplyReorderView(APIView):
    """#319 批量排序 / 分组：items=[{id, sort_order, group?}]"""

    MAX_ITEMS = 500

    def post(self, request):
        items = request.data.get("items")
        if not isinstance(items, (list, tuple)):
            return Response({"message": "items 必须是数组"}, status=400)
        if len(items) > self.MAX_ITEMS:
            return Response({"message": f"单次最多调整 {self.MAX_ITEMS} 条"}, status=400)
        parsed = []
        for row in items:
            if not isinstance(row, dict):
                return Response({"message": "items 每项必须是对象"}, status=400)
            try:
                qr_id = as_int(row.get("id"), field="id", minimum=1)
                sort_order = _clean_qr_sort(row.get("sort_order", 0))
            except ValidationError:
                return Response({"message": "id / sort_order 必须是整数"}, status=400)
            parsed.append((qr_id, sort_order, row.get("group")))
        if not parsed:
            return Response({"message": "没有需要调整的模板", "updated": 0})
        qrs = {
            q.id: q for q in QuickReply.objects.filter(
                owner=request.user, id__in=[p[0] for p in parsed]
            )
        }
        changed = []
        for qr_id, sort_order, group in parsed:
            qr = qrs.get(qr_id)
            if not qr:
                continue
            qr.sort_order = sort_order
            if group is not None:
                qr.group = _clean_qr_group(group)
            changed.append(qr)
        if changed:
            QuickReply.objects.bulk_update(changed, ["sort_order", "group"], batch_size=200)
        return Response({"message": f"已更新 {len(changed)} 条模板", "updated": len(changed)})


# ============ 关键词提醒 ============

class KeywordAlertView(APIView):
    """读取 / 保存我的关键词提醒列表（整体覆盖）"""

    def get(self, request):
        obj = KeywordAlert.objects.filter(owner=request.user).first()
        return Response({"keywords": obj.keywords if obj else []})

    def post(self, request):
        keywords = request.data.get("keywords")
        if not isinstance(keywords, list):
            return Response({"message": "keywords 必须是数组"}, status=400)
        cleaned = [str(k).strip()[:32] for k in keywords if str(k).strip()][:50]
        obj, _ = KeywordAlert.objects.update_or_create(owner=request.user, defaults={"keywords": cleaned})
        return Response({"keywords": obj.keywords})


class KeywordAlertHitsView(APIView):
    """#318 关键词最近命中：用消息搜索按关键词取最近 20 条，供回看 / 调参"""

    LIMIT = 20

    def get(self, request):
        obj = KeywordAlert.objects.filter(owner=request.user).first()
        keywords = [str(k).strip() for k in (obj.keywords if obj else []) if str(k).strip()]
        if not keywords:
            return Response({"keywords": [], "list": [], "total": 0, "limit": self.LIMIT})
        # 与命中通知同口径：只看他人发的文本消息，排除已删 / 已撤回
        qs = (
            ChatMessage.objects.filter(session__members=request.user, msg_type="text")
            .exclude(sender=request.user)
            .exclude(deleted_for=request.user)
            .exclude(is_deleted=True).exclude(is_recalled=True)
            .filter(reduce(or_, (Q(content__icontains=k) for k in keywords)))
        )
        total = qs.count()
        messages = list(
            qs.select_related("session", "sender", "reply_to", "reply_to__sender")
            .order_by("-id")[: self.LIMIT]
        )
        data = ChatMessageSerializer(messages, context={"request": request}, many=True).data
        for row, m in zip(data, messages):
            content_lower = (m.content or "").lower()
            row["session_name"] = m.session.name or "单聊"
            row["session_type"] = m.session.type
            row["matched_keywords"] = [k for k in keywords if k.lower() in content_lower]
        return Response({
            "keywords": keywords, "list": data, "total": total, "limit": self.LIMIT,
        })


# ===========================================================================
# IM 增强 F599–F612（纯新增，不改动上方既有接口）
# ===========================================================================

class MessageEditView(APIView):
    """F599 消息编辑：发送者 10 分钟内可编辑，标记 edited"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        if msg.sender_id != request.user.id:
            return Response({"message": "只能编辑自己的消息"}, status=403)
        if msg.is_recalled or msg.is_deleted:
            return Response({"message": "该消息不可编辑"}, status=400)
        if timezone.now() - msg.created_at > timezone.timedelta(minutes=10):
            return Response({"message": "超过 10 分钟不可编辑"}, status=400)
        content = request.data.get("content", "")
        # #34：编辑与创建共用校验（字符串 / 类型白名单 / 20000 字上限）
        msg_type = request.data.get("msg_type", msg.msg_type)
        err = _validate_message_payload(content, msg_type)
        if err:
            return Response({"message": err}, status=403 if msg_type == "system" else 400)
        content = content.strip()
        if not content:
            return Response({"message": "消息内容不能为空"}, status=400)
        msg.content = content
        msg.edited = True
        msg.edited_at = timezone.now()
        msg.save(update_fields=["content", "edited", "edited_at"])
        data = ChatMessageSerializer(msg, context={"request": request}).data
        send_to_session(msg.session_id, {"type": "message.edited", "data": data})
        return Response(data)


class MessageDeleteForAllView(APIView):
    """F600 消息删除并双端同步（发送者 / 群主 / 管理员）

    #307：权限收敛为发送者、群主或管理员；广播带 deleted_by / sender_id，
    前端可据此把气泡替换为「该消息已被删除」。
    """

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        is_owner = msg.session.type == "group" and msg.session.owner_id == request.user.id
        is_admin = bool(getattr(request.user, "is_staff", False)
                        or getattr(request.user, "is_superuser", False))
        if msg.sender_id != request.user.id and not is_owner and not is_admin:
            return Response({"message": "仅发送者、群主或管理员可删除"}, status=403)
        if msg.is_deleted:
            return Response({"message": "消息已删除", "id": msg.id, "session_id": msg.session_id,
                             "is_deleted": True, "deleted_for_all": True})
        msg.is_deleted = True
        msg.save(update_fields=["is_deleted"])
        send_to_session(msg.session_id, {
            "type": "message.deleted",
            "data": {"id": msg.id, "session_id": msg.session_id, "deleted_for_all": True,
                     "deleted_by": request.user.id, "sender_id": msg.sender_id},
        })
        return Response({"message": "消息已删除", "id": msg.id, "session_id": msg.session_id,
                         "is_deleted": True, "deleted_for_all": True})


class SessionDraftView(APIView):
    """F601 按会话保存草稿"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        return Response({"session_id": s.id, "draft": setting.draft or "",
                         "updated_at": setting.draft_updated_at})

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        # #84：与 SessionSettingView 同一校验（字符串 / 20000 字上限）
        draft, err = _clean_draft(request.data.get("draft"))
        if err:
            return Response({"message": err}, status=400)
        setting = _get_setting(s, request.user)
        setting.draft = draft
        setting.draft_updated_at = timezone.now()
        setting.save(update_fields=["draft", "draft_updated_at"])
        return Response({"message": "草稿已保存", "session_id": s.id, "draft": setting.draft,
                         "updated_at": setting.draft_updated_at})

    def delete(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        setting.draft = ""
        setting.draft_updated_at = None
        setting.save(update_fields=["draft", "draft_updated_at"])
        return Response({"message": "草稿已清空", "session_id": s.id, "draft": ""})


class TodoListView(APIView):
    """F602 稍后处理清单：列表 / 新增

    #310：列表支持 status=open|done、按会话过滤、sort=remind（按到期排序，无到期排后）。
    """

    def get(self, request):
        qs = TodoItem.objects.filter(owner=request.user).select_related("session")
        status_filter = request.query_params.get("status")
        if status_filter == "open":
            qs = qs.filter(is_done=False)
        elif status_filter == "done":
            qs = qs.filter(is_done=True)
        session_id = request.query_params.get("session_id")
        if session_id:
            try:
                qs = qs.filter(session_id=as_int(session_id, field="session_id", minimum=1))
            except ValidationError:
                return Response({"message": "session_id 必须是整数"}, status=400)
        if request.query_params.get("sort") in ("remind", "due", "remind_at"):
            # 未完成在前，按到期时间升序，无到期时间的排最后
            qs = qs.order_by("is_done", F("remind_at").asc(nulls_last=True), "-created_at")
        return Response({
            "list": TodoItemSerializer(qs, many=True).data,
            "total": qs.count(),
            "open": TodoItem.objects.filter(owner=request.user, is_done=False).count(),
        })

    def post(self, request):
        try:
            message_id = as_int(request.data.get("message_id"), default=None, field="message_id", minimum=1)
        except ValidationError:
            return Response({"message": "message_id 必须是整数"}, status=400)
        msg = ChatMessage.objects.filter(id=message_id, session__members=request.user).first() if message_id else None
        content = str(request.data.get("content") or (msg.content if msg else "") or "").strip()
        if not content:
            return Response({"message": "内容不能为空"}, status=400)
        try:
            remind_at = as_datetime(request.data.get("remind_at"), field="remind_at") if request.data.get("remind_at") else None
        except ValidationError:
            return Response({"message": "remind_at 必须是合法日期时间"}, status=400)
        item = TodoItem.objects.create(
            owner=request.user,
            session=msg.session if msg else None,
            message=msg,
            content=content[:500],
            remind_at=remind_at,
        )
        return Response(TodoItemSerializer(item).data, status=201)


class TodoDetailView(APIView):
    """F602 稍后处理清单：完成 / 删除"""

    def _get(self, request, pk):
        return TodoItem.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        item = self._get(request, pk)
        if not item:
            return Response({"message": "条目不存在"}, status=404)
        if "is_done" in request.data:
            item.is_done = parse_bool(request.data["is_done"], field="is_done")
        if "content" in request.data and str(request.data["content"] or "").strip():
            item.content = str(request.data["content"]).strip()[:500]
        if "remind_at" in request.data:
            raw = request.data["remind_at"]
            if not raw:
                item.remind_at = None
            else:
                try:
                    item.remind_at = as_datetime(raw, field="remind_at")
                except ValidationError:
                    return Response({"message": "remind_at 必须是合法日期时间"}, status=400)
        item.save()
        return Response(TodoItemSerializer(item).data)

    def delete(self, request, pk):
        item = self._get(request, pk)
        if not item:
            return Response({"message": "条目不存在"}, status=404)
        item.delete()
        return Response({"message": "已删除"})


class SessionMuteView(APIView):
    """F603 单会话免打扰开关

    #326：支持 duration=1h / 8h / tomorrow 临时静音（写入 mute_until），
    duration=off 或 is_muted=false 立即恢复；到期由查询侧按未静音处理。
    """

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        duration = request.data.get("duration")
        if duration is not None and str(duration).strip():
            duration = str(duration).strip().lower()
            if duration in ("0", "off", "none", "false"):
                setting.is_muted = False
                setting.mute_until = None
            elif duration in MUTE_DURATION_CHOICES:
                until, err = _mute_until_for(duration)
                if err:
                    return Response({"message": err}, status=400)
                setting.is_muted = True
                setting.mute_until = until
            else:
                return Response({
                    "message": f"duration 仅支持 {'/'.join(MUTE_DURATION_CHOICES)} 或 off",
                }, status=400)
        elif request.data.get("mute_until") not in (None, ""):
            try:
                until = as_datetime(request.data.get("mute_until"), field="mute_until")
            except ValidationError:
                return Response({"message": "mute_until 必须是合法日期时间"}, status=400)
            if until <= timezone.now():
                return Response({"message": "mute_until 必须晚于当前时间"}, status=400)
            setting.is_muted = True
            setting.mute_until = until
        elif "is_muted" in request.data:
            setting.is_muted = parse_bool(request.data["is_muted"], field="is_muted")
            if not setting.is_muted:
                setting.mute_until = None
        else:
            # 无参数 = 切换当前生效状态；永久静音/临时静音都按「正在免打扰」翻转
            active = _is_mute_active(setting)
            setting.is_muted = not active
            setting.mute_until = None
        setting.save(update_fields=["is_muted", "mute_until"])
        active = _is_mute_active(setting)
        return Response({
            "message": "已开启免打扰" if active else "已关闭免打扰",
            "session_id": s.id, "is_muted": active, "mute_until": setting.mute_until,
            "duration": duration if isinstance(duration, str) else None,
        })


class SessionTypingView(APIView):
    """F604 正在输入状态：上报 / 查询（8 秒内有效）

    #314：POST 支持 typing=false 主动结束（发送或清空输入框时），
    防抖仍由前端负责，后端只做广播。
    """

    WINDOW_SECONDS = 8

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        is_typing = parse_bool(request.data.get("typing"), default=True, field="typing")
        setting = _get_setting(s, request.user)
        setting.typing_at = timezone.now() if is_typing else None
        setting.save(update_fields=["typing_at"])
        broadcast_session(s.id, {"type": "session.typing", "data": {
            "session_id": s.id, "user_id": request.user.id,
            "display_name": request.user.display_name, "is_typing": is_typing,
        }})
        return Response({"message": "ok", "session_id": s.id, "is_typing": is_typing})

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        since = timezone.now() - timezone.timedelta(seconds=self.WINDOW_SECONDS)
        typing = SessionMemberSetting.objects.filter(
            session=s, typing_at__gte=since
        ).exclude(user=request.user).select_related("user")
        return Response({"session_id": s.id, "typing": [
            {"user_id": t.user_id, "display_name": t.user.display_name} for t in typing
        ]})


class SessionPinnedView(APIView):
    """F605 置顶消息管理：列表 / 取消置顶"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        qs = s.messages.filter(is_pinned=True).exclude(is_deleted=True)
        return Response({"session_id": s.id,
                         "list": ChatMessageSerializer(qs, many=True, context={"request": request}).data,
                         "total": qs.count()})


class SessionPinnedDetailView(APIView):
    """F605 取消某条消息置顶"""

    def delete(self, request, pk, msg_id):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        msg = s.messages.filter(id=msg_id, is_pinned=True).first()
        if not msg:
            return Response({"message": "置顶消息不存在"}, status=404)
        msg.is_pinned = False
        msg.save(update_fields=["is_pinned"])
        send_to_session(s.id, {"type": "message.pinned",
                               "data": {"id": msg.id, "session_id": s.id, "is_pinned": False}})
        return Response({"message": "已取消置顶", "id": msg.id, "is_pinned": False})


class SessionAnnouncementView(APIView):
    """F606 群公告：读取 / 设置（仅群主可设置）

    #317：保存公告时刷新 announcement_updated_at，落一条 system 消息并给
    其他成员发 message 类通知；GET 返回本人公告未读状态（mark_read=1 顺手已读）。
    """

    def _payload(self, s, setting, user):
        unread = bool(
            s.announcement_updated_at
            and (not setting or not setting.announcement_read_at
                 or setting.announcement_read_at < s.announcement_updated_at)
        )
        return {
            "session_id": s.id, "announcement": s.announcement or "",
            "announcement_updated_at": s.announcement_updated_at,
            "is_read": not unread, "unread": unread,
            "can_edit": s.type == "group" and s.owner_id == getattr(user, "id", None),
        }

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = SessionMemberSetting.objects.filter(session=s, user=request.user).first()
        mark = parse_bool(request.query_params.get("mark_read"), default=False, field="mark_read")
        if mark and s.type == "group":
            setting = _get_setting(s, request.user)
            setting.announcement_read_at = timezone.now()
            setting.save(update_fields=["announcement_read_at"])
        return Response(self._payload(s, setting, request.user))

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type != "group":
            return Response({"message": "单聊没有群公告"}, status=400)
        if s.owner_id != request.user.id:
            return Response({"message": "仅群主可发布公告"}, status=403)
        setting = _get_setting(s, request.user)
        # 仅标记已读（成员点开公告入口时调用）
        if "announcement" not in request.data and parse_bool(
                request.data.get("mark_read"), default=False, field="mark_read"):
            setting.announcement_read_at = timezone.now()
            setting.save(update_fields=["announcement_read_at"])
            return Response({"message": "公告已读", **self._payload(s, setting, request.user)})
        new_text = str(request.data.get("announcement") or "")[:500]
        changed = new_text != (s.announcement or "")
        if changed:
            s.announcement = new_text
            s.announcement_updated_at = timezone.now()
            s.save(update_fields=["announcement", "announcement_updated_at"])
        # 发布者视为已读
        setting.announcement_read_at = s.announcement_updated_at or timezone.now()
        setting.save(update_fields=["announcement_read_at"])
        if changed:
            # 系统消息落库：离线成员重连拉历史也能看到公告变更
            sys_msg = ChatMessage.objects.create(
                session=s, sender=request.user, msg_type="system",
                content=f"群公告已更新：{(new_text or '（已清空）')[:300]}",
            )
            send_to_session(s.id, {
                "type": "chat.message",
                "data": ChatMessageSerializer(sys_msg, context={"request": request}).data,
            })
            from core.models import notify_many
            notify_many(
                list(s.members.exclude(id=request.user.id)),
                f"「{s.name or '群聊'}」公告已更新",
                new_text[:100] or "群公告已清空",
                category="message", link=f"/im/{s.id}",
            )
            broadcast_session(s.id, {"type": "session.updated", "data": {"session_id": s.id}})
        return Response({"message": "公告已更新" if changed else "公告未变化",
                         **self._payload(s, setting, request.user)})


class MentionsView(APIView):
    """F607 我收到的 @提及消息列表

    #311：返回会话 / 消息 id 供前端跳转定位；@所有人 同样计入；
    整批 select_related，避免逐条查会话与发送者。
    """

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 100

    def get(self, request):
        name = request.user.display_name
        try:
            limit = as_int(request.query_params.get("limit"), default=self.DEFAULT_LIMIT,
                           field="limit", minimum=1, maximum=self.MAX_LIMIT)
        except ValidationError:
            return Response({"message": "limit 必须是整数"}, status=400)
        if not name:
            return Response({"list": [], "total": 0, "has_more": False})
        cond = Q(content__icontains=f"@{name}") | Q(content__icontains="@所有人") \
            | Q(content__icontains="@all")
        qs = (
            ChatMessage.objects.filter(session__members=request.user)
            .filter(cond)
            .exclude(sender=request.user)
            .exclude(deleted_for=request.user)
            .exclude(is_deleted=True).exclude(is_recalled=True)
        )
        session_id = request.query_params.get("session_id")
        if session_id:
            try:
                qs = qs.filter(session_id=as_int(session_id, field="session_id", minimum=1))
            except ValidationError:
                return Response({"message": "session_id 必须是整数"}, status=400)
        total = qs.count()
        messages = list(
            qs.select_related("session", "sender", "reply_to", "reply_to__sender")
            .order_by("-id")[:limit]
        )
        data = ChatMessageSerializer(messages, context={"request": request}, many=True).data
        for row, m in zip(data, messages):
            row["session_name"] = m.session.name or "单聊"
            row["session_type"] = m.session.type
        return Response({"list": data, "total": total, "has_more": total > len(messages)})


class FavoriteListView(APIView):
    """F608 消息收藏夹：列表 / 收藏或取消收藏"""

    def get(self, request):
        qs = MessageFavorite.objects.filter(owner=request.user).select_related("message")
        return Response({"list": MessageFavoriteSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        try:
            message_id = as_int(request.data.get("message_id"), field="message_id", minimum=1)
        except ValidationError:
            return Response({"message": "message_id 必须是整数"}, status=400)
        msg = ChatMessage.objects.filter(id=message_id, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        fav = MessageFavorite.objects.filter(owner=request.user, message=msg).first()
        if fav:
            fav.delete()
            return Response({"message": "已取消收藏", "favorited": False})
        fav = MessageFavorite.objects.create(owner=request.user, message=msg,
                                             note=str(request.data.get("note") or "")[:200])
        return Response({"message": "已收藏", "favorited": True,
                         "item": MessageFavoriteSerializer(fav).data}, status=201)


class FavoriteDetailView(APIView):
    """F608 删除收藏"""

    def delete(self, request, pk):
        fav = MessageFavorite.objects.filter(pk=pk, owner=request.user).first()
        if not fav:
            return Response({"message": "收藏不存在"}, status=404)
        fav.delete()
        return Response({"message": "已删除收藏"})


# F609 本地词典（无外部密钥即可降级运行）
_TRANS_DICT_ZH_EN = {
    "你好": "hello", "谢谢": "thank you", "再见": "goodbye", "好的": "ok", "收到": "received",
    "项目": "project", "任务": "task", "看板": "board", "卡片": "card", "会议": "meeting",
    "今天": "today", "明天": "tomorrow", "昨天": "yesterday", "完成": "done", "进行中": "in progress",
    "待办": "todo", "负责人": "assignee", "截止日期": "due date", "优先级": "priority",
    "问题": "issue", "需求": "requirement", "文档": "document", "测试": "test", "上线": "release",
    "请": "please", "尽快": "as soon as possible", "确认": "confirm", "安排": "schedule",
}
_TRANS_DICT_EN_ZH = {v: k for k, v in _TRANS_DICT_ZH_EN.items()}
_TRANS_SUPPORTED = ("zh", "en")


def _norm_lang(raw):
    """#308：目标语言归一化（zh-CN / en_US → zh / en），不支持返回空串"""
    base = str(raw or "").strip().lower().replace("_", "-").split("-")[0]
    return base if base in _TRANS_SUPPORTED else ""


def _local_translate(text, target_lang):
    """本地词典降级翻译：按词/短语替换，未命中保留原文"""
    text = text or ""
    if target_lang == "en":
        table = _TRANS_DICT_ZH_EN
    else:
        table = _TRANS_DICT_EN_ZH
    matched = 0
    out = text
    for src in sorted(table.keys(), key=len, reverse=True):
        if src in out:
            out = out.replace(src, table[src])
            matched += 1
    return out, matched


class MessageTranslateView(APIView):
    """F609 消息翻译（本地词典降级，无密钥也能出结果）

    #308：target_lang 支持 zh / en（含 zh-CN、en-US 等带地区写法），
    响应固定回带 original / translated / source_lang / target_lang。
    """

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        raw_target = request.data.get("target_lang") or request.query_params.get("target_lang") or "en"
        target = _norm_lang(raw_target)
        if not target:
            return Response({"message": "target_lang 仅支持 zh / en",
                             "supported_languages": list(_TRANS_SUPPORTED)}, status=400)
        original = msg.content or ""
        source = "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in original) else "en"
        if source == target or not original:
            translated, matched = original, 0
        else:
            translated, matched = _local_translate(original, target)
        return Response({
            "message_id": msg.id, "source_lang": source, "target_lang": target,
            "requested_lang": str(raw_target),
            "original": original, "translated": translated,
            "changed": translated != original,
            "engine": "local-dict", "matched": matched, "fallback": matched == 0,
            "supported_languages": list(_TRANS_SUPPORTED),
        })


class SessionStatsView(APIView):
    """F610 会话统计：发言数 / 时段分布 / 类型分布

    #312：全部改成数据库聚合（group by），不再把整段消息读进内存逐条统计。
    """

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        qs = s.messages.exclude(is_deleted=True)
        total = qs.count()
        member_rows = (
            qs.values("sender_id", "sender__nickname", "sender__username")
            .annotate(count=Count("id")).order_by("-count")
        )
        by_member = [
            {"id": r["sender_id"],
             "name": r["sender__nickname"] or r["sender__username"] or "系统",
             "count": r["count"]}
            for r in member_rows
        ]
        by_type = {
            r["msg_type"]: r["count"]
            for r in qs.values("msg_type").annotate(count=Count("id"))
        }
        # 按本地时区折算小时，与前端展示口径一致
        hour_rows = (
            qs.annotate(h=ExtractHour("created_at", tzinfo=timezone.get_current_timezone()))
            .values("h").annotate(count=Count("id"))
        )
        hour_dist = [0] * 24
        for r in hour_rows:
            if r["h"] is not None and 0 <= r["h"] < 24:
                hour_dist[r["h"]] = r["count"]
        active_days = qs.values("created_at__date").distinct().count()
        span = qs.aggregate(first=Min("created_at"), last=Max("created_at"))
        return Response({
            "session_id": s.id, "total": total,
            "member_count": s.members.count(),
            "by_member": by_member,
            "by_type": by_type, "hour_distribution": hour_dist,
            "active_days": active_days,
            "first_message_at": span["first"], "last_message_at": span["last"],
        })


class SessionExportView(APIView):
    """F611 会话导出

    #325：支持 start / end 时间范围与 format=md|csv，返回导出条数与截断标记。
    """

    MAX_MESSAGES = 5000
    FORMATS = ("md", "csv")

    @staticmethod
    def _body(m):
        if m.is_recalled:
            return "[已撤回]"
        if m.msg_type == "image":
            return "[图片]"
        if m.msg_type == "file":
            return "[文件]"
        return m.content or ""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        # DRF 会把 ?format= 当渲染器后缀拦截（未知值直接 404），导出参数改用 fmt
        fmt = (request.query_params.get("fmt") or request.query_params.get("format") or "md").strip().lower()
        if fmt not in self.FORMATS:
            return Response({"message": "fmt 仅支持 md / csv"}, status=400)
        raw_start = request.query_params.get("start")
        raw_end = request.query_params.get("end")
        qs = (
            s.messages.exclude(is_deleted=True)
            .exclude(deleted_for=request.user)
        )
        try:
            if raw_start:
                qs = qs.filter(created_at__date__gte=as_date(raw_start, field="start"))
            if raw_end:
                qs = qs.filter(created_at__date__lte=as_date(raw_end, field="end"))
        except ValidationError:
            return Response({"message": "start / end 必须是 YYYY-MM-DD"}, status=400)
        total = qs.count()
        # #109：最多导出 5000 条；sender 一次性 select_related，避免逐行懒加载
        msgs = list(qs.select_related("sender").order_by("created_at")[: self.MAX_MESSAGES])
        count = len(msgs)
        members = "、".join(
            nick or uname for nick, uname in s.members.values_list("nickname", "username")
        )
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["时间", "发送者", "类型", "内容", "附件数", "已编辑", "已撤回"])
            for m in msgs:
                writer.writerow([
                    timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M"),
                    m.sender.display_name if m.sender else "系统",
                    m.msg_type, self._body(m), len(m.attachments or []),
                    "是" if m.edited else "否", "是" if m.is_recalled else "否",
                ])
            # BOM 让 Excel 正确识别 UTF-8 中文
            content = "\ufeff" + buf.getvalue()
            filename = f"chat-{s.id}.csv"
        else:
            lines = [f"# {s.name or '单聊会话'}", ""]
            lines.append(f"> 导出时间：{timezone.localtime(timezone.now()):%Y-%m-%d %H:%M}")
            if raw_start or raw_end:
                lines.append(f"> 时间范围：{raw_start or '最早'} ~ {raw_end or '最新'}")
            lines.append(f"> 成员：{members}")
            if s.announcement:
                lines.append(f"> 群公告：{s.announcement}")
            lines.append("")
            lines.append("---")
            lines.append("")
            for m in msgs:
                ts = timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M")
                who = m.sender.display_name if m.sender else "系统"
                suffix = "（已编辑）" if m.edited else ""
                lines.append(f"**{who}** · {ts}{suffix}")
                lines.append("")
                lines.append(self._body(m))
                lines.append("")
            content = "\n".join(lines)
            filename = f"chat-{s.id}.md"
        return Response({
            "session_id": s.id, "name": s.name or "单聊",
            "filename": filename, "format": fmt, "count": count,
            "total": total, "truncated": total > count,
            "start": raw_start or None, "end": raw_end or None,
            "content": content, "markdown": content if fmt == "md" else None,
            "length": len(content),
        })


class SessionUnreadLineView(APIView):
    """F612 未读分隔线与跳转：返回首条未读消息及上下文"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = SessionMemberSetting.objects.filter(session=s, user=request.user).first()
        qs = s.messages.exclude(deleted_for=request.user).exclude(is_deleted=True).exclude(sender=request.user)
        if setting and setting.last_read_at:
            unread = qs.filter(created_at__gt=setting.last_read_at)
        else:
            unread = qs
        first_unread = unread.order_by("id").first()
        if not first_unread:
            return Response({"session_id": s.id, "has_unread": False, "unread_count": 0,
                             "first_unread_id": None, "first_unread_at": None, "context": []})
        context = list(s.messages.filter(id__gte=first_unread.id).exclude(deleted_for=request.user)
                       .exclude(is_deleted=True).order_by("id")[:20])
        return Response({
            "session_id": s.id, "has_unread": True, "unread_count": unread.count(),
            "first_unread_id": first_unread.id,
            "first_unread_at": first_unread.created_at,
            "context": ChatMessageSerializer(context, many=True, context={"request": request}).data,
        })


class MessageReadersView(APIView):
    """F26 已读回执详情：发送者 / 群主可查看谁已读、谁未读"""

    def get(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        session = msg.session
        can_view = (
            msg.sender_id == request.user.id
            or (session.type == "group" and session.owner_id == request.user.id)
        )
        if not can_view:
            return Response({"message": "仅发送者或群主可查看已读详情"}, status=403)
        settings = {
            s.user_id: s.last_read_at
            for s in SessionMemberSetting.objects.filter(session=session)
        }
        readers, unreaders = [], []
        for u in session.members.exclude(id=msg.sender_id):
            last_read = settings.get(u.id)
            row = {"id": u.id, "display_name": u.display_name,
                   "avatar": u.avatar.url if u.avatar else ""}
            if last_read and last_read >= msg.created_at:
                readers.append(row)
            else:
                unreaders.append(row)
        return Response({
            "message_id": msg.id, "session_id": session.id,
            "sender_id": msg.sender_id,
            "sender_name": msg.sender.display_name if msg.sender else "系统",
            "read": len(readers), "unread": len(unreaders),
            "total": len(readers) + len(unreaders),
            "readers": readers, "unreaders": unreaders,
            # #309：直接给出 id 列表，方便前端「一键 @ 未读者」
            "read_user_ids": [u["id"] for u in readers],
            "unread_user_ids": [u["id"] for u in unreaders],
        })
