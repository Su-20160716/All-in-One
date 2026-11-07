"""看板视图：项目、看板列、卡片拖拽、子任务、工时、评论、成员、活动、统计、我的任务"""
import html
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count as ModelsCount, Max as ModelsMax, Prefetch, Sum as ModelsSum, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

from accounts.models import User
from core.models import notify, notify_many
from core.validators import as_date, as_datetime, as_int, parse_bool
from projects.models import (
    AcceptanceItem,
    Board,
    BoardShareLink,
    CardComment,
    CardDependency,
    CardTemplate,
    CardWatcher,
    Milestone,
    Project,
    ProjectActivity,
    Sprint,
    Subtask,
    TaskCard,
    WorkLog,
)
from projects.serializers import (
    AcceptanceItemSerializer,
    BoardSerializer,
    CardCommentSerializer,
    CardTemplateSerializer,
    MilestoneSerializer,
    ProjectActivitySerializer,
    ProjectSerializer,
    SubtaskSerializer,
    TaskCardSerializer,
    WorkLogSerializer,
)


def _can_access(user, project):
    return project.owner_id == user.id or project.members.filter(id=user.id).exists()


def _log_activity(project, user, action, target=""):
    ProjectActivity.objects.create(project=project, user=user, action=action, target=target)


def _push_board_event(project_id, action, **data):
    """S2-B1：看板/卡片变动 WS 广播（on_commit 延后，回滚不广播；失败不影响主流程）"""
    def _emit():
        try:
            from ws_app.events import notify_board_event
            notify_board_event(project_id, action, data)
        except Exception:
            logger.exception("S2-B1：看板事件广播失败 action=%s", action)

    transaction.on_commit(_emit)


def _card_of(user, pk):
    card = TaskCard.objects.filter(pk=pk).first()
    if not card or not _can_access(user, card.board.project):
        return None
    return card


def _first_error(errors):
    """取 DRF 校验错误里的第一条可读信息（用于 400 响应）"""
    if isinstance(errors, dict):
        for v in errors.values():
            return _first_error(v)
        return "参数不合法"
    if isinstance(errors, (list, tuple)):
        return _first_error(errors[0]) if errors else "参数不合法"
    return str(errors)


def _wip_state(board, exclude_ids=()):
    """283：列在办数（非 done）与上限；exclude_ids 用于移动前预判"""
    qs = TaskCard.objects.filter(board=board).exclude(status="done")
    if exclude_ids:
        qs = qs.exclude(id__in=list(exclude_ids))
    return qs.count(), (board.wip_limit or 0)


def _wip_guard(board, exclude_ids=(), force=False):
    """283：目标列在办数已达上限时拒绝拖入，force=1 可强制（返回 None 表示放行）"""
    active, limit = _wip_state(board, exclude_ids)
    if not limit or active < limit or force:
        return None
    return Response({
        "message": f"「{board.name}」在办 {active}/{limit} 已达 WIP 上限，请先完成或移出卡片",
        "over_limit": True, "board_id": board.id, "active_count": active, "wip_limit": limit,
    }, status=409)


def _dod_guard(card, new_status, force=False):
    """285：状态改 done 但验收项未完成时要求二次确认（force=1 放行）"""
    if new_status != "done" or force:
        return None
    items = list(card.acceptance_items.all())
    total = len(items)
    done = len([i for i in items if i.is_done])
    if not total or done >= total:
        return None
    return Response({
        "message": f"还有 {total - done} 项验收未完成，确认结单请带 force=1 重试",
        "needs_confirm": True, "dod_total": total, "dod_done": done,
        "pending": [i.content for i in items if not i.is_done][:20],
    }, status=409)


def _highlight(text, kw, limit=160):
    """292：返回可高亮的片段（HTML 已转义，命中词包 <mark>）"""
    if not text:
        return ""
    raw = str(text)
    if not kw:
        return html.escape(raw[:limit])
    idx = raw.lower().find(str(kw).lower())
    start = max(idx - 40, 0) if idx >= 0 else 0
    fragment = html.escape(raw[start:start + limit])
    return re.sub(re.escape(html.escape(str(kw))), lambda m: f"<mark>{m.group(0)}</mark>",
                  fragment, flags=re.IGNORECASE)


def _watcher_users(card):
    """295：卡片关注者（已排除无效用户）"""
    return User.objects.filter(watched_cards__card=card, is_active=True)


def _notify_watchers(card, actor, title, content=""):
    """295：卡片变更只推给关注者，未关注的项目成员不再收到噪音"""
    recipients = [u for u in _watcher_users(card) if u.id != actor.id]
    if not recipients:
        return 0
    notify_many(recipients, title, content, category="project", level="info",
                link=f"/projects/{card.board.project_id}")
    return len(recipients)


def _project_member_users(project):
    """项目成员（含创建者）：负责人/指派对象的唯一合法来源。

    #29：`assignee_ids` 历史上直接按 id 取全平台用户，可指派给非成员、
    跨租户用户甚至超管，并借分配通知骚扰他人。
    """
    return User.objects.filter(Q(projects=project) | Q(owned_projects=project)).distinct()


def _subtask_assignee(card, raw_id):
    """#30：子任务负责人只能是项目成员。

    历史实现 `User.objects.filter(pk=...)` 直接取全平台用户，可把子任务指派给
    非项目成员甚至跨租户用户，并借通知骚扰他人。这里统一走
    `_project_member_users`，无效 / 不可见 id 一律拒绝。

    返回 (assignee, error)：未传 assignee_id 时两者均为空。
    """
    try:
        assignee_id = as_int(raw_id, default=None, field="assignee_id", minimum=1)
    except ValidationError:
        return None, "assignee_id 必须是整数"
    if not assignee_id:
        return None, ""
    assignee = _project_member_users(card.board.project).filter(pk=assignee_id).first()
    if not assignee:
        return None, "assignee_id 不是本项目成员"
    return assignee, ""


def _org_user_qs(user):
    """候选/可添加用户池：启用中 + 同租户/同部门。

    #27/#28：候选人列表与「加成员」都必须收在同组织内，不能把全平台
    username/昵称 暴露出去，也不能把跨租户用户拉进项目。
    组织边界优先取租户（多租户开启时，租户是权威边界）；未启用多租户时
    退回部门边界，并保留「未分配部门」的用户，避免新建账号无法被加进来。
    """
    qs = User.objects.filter(is_active=True, is_disabled=False)
    tenant_id = getattr(user, "tenant_id", None)
    if getattr(settings, "TENANCY_ENABLED", False) and tenant_id:
        return qs.filter(tenant_id=tenant_id)
    dept_id = getattr(user, "department_id", None)
    if dept_id:
        qs = qs.filter(Q(department_id=dept_id) | Q(department_id__isnull=True))
    return qs


def _apply_sort_order(cards):
    """把给定卡片按列表顺序写回 sort_order（只写变化的，一次 bulk_update）。

    #61/#141：列内重排不再逐条 UPDATE。
    """
    changed = []
    for i, c in enumerate(cards):
        if c.sort_order != i:
            c.sort_order = i
            changed.append(c)
    if changed:
        TaskCard.objects.bulk_update(changed, ["sort_order"], batch_size=500)
    return len(changed)


def _renumber_board(board_id):
    """按当前顺序重排一整列（移出卡片后收敛空洞序号）"""
    rows = list(TaskCard.objects.filter(board_id=board_id).order_by("sort_order", "id"))
    _apply_sort_order(rows)


def _dependency_path_exists(start_id, target_id, max_steps=5000):
    """#59：从 start 沿「被依赖」方向（card -> blocked_by）能否到达 target。

    建依赖前用它做传递闭包检测，避免 A→B、B→A 这类间接成环让拓扑排序失效。
    """
    if start_id == target_id:
        return True
    seen = set()
    stack = [start_id]
    steps = 0
    while stack and steps < max_steps:
        cur = stack.pop()
        steps += 1
        if cur in seen:
            continue
        seen.add(cur)
        for child in CardDependency.objects.filter(card_id=cur).values_list("blocked_by_id", flat=True):
            if child == target_id:
                return True
            if child not in seen:
                stack.append(child)
    return False


# ============ 项目 ============

class ProjectListView(APIView):
    """项目列表（我创建 + 我参与的），支持归档/收藏/搜索筛选，创建项目"""

    # #117：不带任何分页参数时的默认页大小
    DEFAULT_PAGE_SIZE = 50

    def get(self, request):
        qs = Project.objects.filter(Q(owner=request.user) | Q(members=request.user)).distinct()
        arch = request.query_params.get("archived")
        if arch == "1":
            qs = qs.filter(is_archived=True)
        elif arch == "all":
            pass
        else:
            qs = qs.filter(is_archived=False)
        if request.query_params.get("star") == "1":
            qs = qs.filter(is_star=True)
        keyword = request.query_params.get("search")
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        # B6：列表页原来每项目 5 次 count（board/card/done + members×2），
        # 改为一次 annotate 聚合 + prefetch members；
        # 外层 distinct() 下的 m2m join 用 distinct=True 计数，数值不受成员数膨胀影响
        qs = qs.annotate(
            board_count=ModelsCount("boards", distinct=True),
            card_total=ModelsCount("boards__cards", distinct=True),
            done_total=ModelsCount("boards__cards", filter=Q(boards__cards__status="done"), distinct=True),
        ).prefetch_related("members")
        # #117：默认 50 条分页并回 next 游标，`?size=all` 保留旧的全量行为。
        # 响应仍是 {list,total}（外加 page/page_size/has_more/next 几个增量字段），
        # 老客户端不需要改解析；只是首屏不再把全部项目（含成员与计数）一次性序列化。
        qs = qs.order_by("-updated_at", "-id")  # 分页需要在稳定顺序上切片
        total = qs.count()
        raw_size = (request.query_params.get("size") or "").strip().lower()
        if raw_size == "all":
            return Response({
                "list": ProjectSerializer(qs, many=True).data, "total": total,
                "page": 1, "page_size": total, "has_more": False, "next": None,
            })
        try:
            size = as_int(
                raw_size or request.query_params.get("page_size"),
                default=self.DEFAULT_PAGE_SIZE, field="size", minimum=1, maximum=200,
            )
            page_no = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
        except ValidationError:
            return Response({"message": "size 必须是 1-200 的整数或 all，page 必须是正整数"}, status=400)
        start = (page_no - 1) * size
        rows = list(qs[start:start + size])
        has_more = start + size < total
        next_url = None
        if has_more:
            params = request.query_params.copy()
            params["page"] = page_no + 1
            params["size"] = size
            next_url = request.build_absolute_uri(f"{request.path}?{params.urlencode()}")
        return Response({
            "list": ProjectSerializer(rows, many=True).data, "total": total,
            "page": page_no, "page_size": size, "has_more": has_more, "next": next_url,
        })

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "项目名不能为空"}, status=400)
        # B5：项目 + 三个默认看板列 + 成员关联 + 活动流水多表写，整事务提交，
        # 避免「项目建了但看板列没建」的半成品项目
        with transaction.atomic():
            project = Project.objects.create(
                name=name,
                description=request.data.get("description", ""),
                color=request.data.get("color", "#0ea5e9"),
                owner=request.user,
            )
            for i, col in enumerate(["待办", "进行中", "已完成"]):
                Board.objects.create(project=project, name=col, sort_order=i)
            project.members.add(request.user)
            _log_activity(project, request.user, "创建了项目", project.name)
        return Response(ProjectSerializer(project).data, status=201)


class ProjectDetailView(APIView):
    def get_object(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or not _can_access(request.user, project):
            return None
        return project

    def get(self, request, pk):
        project = self.get_object(request, pk)
        if not project:
            return Response({"message": "项目不存在或无权访问"}, status=404)
        return Response(ProjectSerializer(project).data)

    def patch(self, request, pk):
        project = self.get_object(request, pk)
        if not project:
            return Response({"message": "项目不存在或无权访问"}, status=404)
        if project.owner_id != request.user.id:
            # 非创建者只能切换自己的收藏，不能顺带改项目设置
            if set(request.data.keys()) - {"is_star"}:
                return Response({"message": "仅项目创建者可编辑"}, status=403)
            if "is_star" in request.data:
                project.is_star = bool(request.data["is_star"])
                project.save(update_fields=["is_star"])
            return Response(ProjectSerializer(project).data)
        for field in ("name", "description", "color", "is_archived", "is_star"):
            if field in request.data:
                setattr(project, field, request.data[field])
        project.save()
        _log_activity(project, request.user, "更新了项目", project.name)
        return Response(ProjectSerializer(project).data)

    def delete(self, request, pk):
        project = self.get_object(request, pk)
        if not project:
            return Response({"message": "项目不存在或无权访问"}, status=404)
        if project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可删除"}, status=403)
        project.delete()
        return Response({"message": "项目已删除"})


class ProjectStarView(APIView):
    """切换项目收藏"""

    def post(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        project.is_star = not project.is_star
        project.save(update_fields=["is_star"])
        return Response({"is_star": project.is_star})


class ProjectCloneView(APIView):
    """克隆项目（复制看板列结构，不复制卡片）"""

    def post(self, request, pk):
        src = Project.objects.filter(pk=pk).first()
        if not src or not _can_access(request.user, src):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        clone = Project.objects.create(
            name=f"{src.name}（副本）", description=src.description, color=src.color, owner=request.user
        )
        clone.members.add(request.user)
        for b in src.boards.all():
            Board.objects.create(project=clone, name=b.name, sort_order=b.sort_order)
        _log_activity(clone, request.user, "克隆了项目", src.name)
        return Response(ProjectSerializer(clone).data, status=201)


class ProjectMemberView(APIView):
    """成员：添加 / 移除 / 列表 / 候选"""

    def get(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        today = timezone.localdate()
        # 304：成员在办/逾期数（一次分组聚合，查询数与成员数无关）
        load_map = {
            row["assignees"]: row
            for row in (
                TaskCard.objects.filter(board__project=project, assignees__isnull=False)
                .exclude(status="done")
                .values("assignees")
                .annotate(
                    open_count=ModelsCount("id"),
                    overdue_count=ModelsCount("id", filter=Q(due_date__lt=today)),
                )
                .order_by()
            )
        }
        members = [
            {"id": u.id, "username": u.username, "display_name": u.display_name,
             "avatar": u.avatar.url if u.avatar else "", "is_owner": u.id == project.owner_id,
             "open_count": (load_map.get(u.id) or {}).get("open_count") or 0,
             "overdue_count": (load_map.get(u.id) or {}).get("overdue_count") or 0}
            for u in project.members.all()
        ]
        member_ids = list(project.members.values_list("id", flat=True))
        kw = request.query_params.get("q", "")
        # #27：候选只来自同租户/同部门，返回字段已收窄到 id + display_name
        cand = _org_user_qs(request.user).exclude(id__in=member_ids)
        if kw:
            cand = cand.filter(Q(username__icontains=kw) | Q(nickname__icontains=kw))
        candidates = [{"id": u.id, "display_name": u.display_name} for u in cand[:20]]
        return Response({"members": members, "candidates": candidates})

    def post(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可管理成员"}, status=403)
        user_ids = request.data.get("user_ids") or []
        usernames = request.data.get("usernames") or []
        if not isinstance(user_ids, (list, tuple)) or not isinstance(usernames, (list, tuple)):
            return Response({"message": "user_ids / usernames 必须是数组"}, status=400)
        if len(user_ids) + len(usernames) > 50:
            return Response({"message": "单次最多添加 50 名成员"}, status=400)
        try:
            user_ids = [as_int(x, field="user_ids", minimum=1) for x in user_ids]
        except ValidationError:
            return Response({"message": "user_ids 必须全部为整数"}, status=400)
        usernames = [str(x) for x in usernames]
        added = []
        # #28：只接受启用中、且与操作者同租户的用户（多租户开启时）
        users_qs = _org_user_qs(request.user).filter(Q(id__in=user_ids) | Q(username__in=usernames))
        if getattr(settings, "TENANCY_ENABLED", False):
            tenant_id = getattr(request.user, "tenant_id", None)
            if tenant_id:
                users_qs = users_qs.filter(tenant_id=tenant_id)
        users = list(users_qs.exclude(id__in=project.members.values_list("id", flat=True)))
        if not users:
            return Response({"message": "没有可添加的有效用户"}, status=400)
        for u in users:
            project.members.add(u)
            added.append(u.display_name)
            notify(u, f"你被加入项目「{project.name}」", category="project", link=f"/projects/{project.id}")
        _log_activity(project, request.user, "添加了成员", "、".join(added))
        return Response({"message": f"已添加 {len(added)} 名成员", "member_names": added})

    def delete(self, request, pk):
        project = Project.objects.filter(pk=pk).first()
        if not project or project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可管理成员"}, status=403)
        try:
            user_id = as_int(request.query_params.get("user_id"), field="user_id", minimum=1)
        except ValidationError:
            return Response({"message": "user_id 必须是整数"}, status=400)
        user = project.members.filter(id=user_id).first()
        if user:
            project.members.remove(user)
            _log_activity(project, request.user, "移除了成员", user.display_name)
            return Response({"message": f"已移除 {user.display_name}"})
        return Response({"message": "成员不存在"}, status=404)


# ============ 看板列 ============

class BoardListView(APIView):
    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        # B6：原来每列一次 TaskCard 查询、每卡序列化再 10+ 次（assignees/comments/
        # subtasks/dependencies/acceptance_items/worklogs…）。改为：
        # 列一次查询 + 卡片一次查询 + 6 个 prefetch，总量与卡片数无关
        boards = Board.objects.filter(project=project).annotate(
            card_count_total=ModelsCount("cards"),
            # 283：列在办数（非 done）供前端显示 active/limit 与超限角标
            active_total=ModelsCount("cards", filter=~Q(cards__status="done")),
        )
        cards = (
            TaskCard.objects.filter(board__project=project)
            .select_related("board")
            .prefetch_related(
                Prefetch("dependencies", queryset=CardDependency.objects.select_related("blocked_by")),
                "acceptance_items",
                "assignees",
                "comments",
                "subtasks",
                "worklogs",
            )
        )
        # 单次最多加载 2000 张卡、每列最多 300 张；超出由前端分页拉取
        MAX_CARDS, MAX_PER_BOARD = 2000, 300
        by_board = {}
        for c in cards[:MAX_CARDS]:
            bucket = by_board.setdefault(c.board_id, [])
            if len(bucket) < MAX_PER_BOARD:
                bucket.append(c)
        result = [
            {**BoardSerializer(b).data, "cards": TaskCardSerializer(by_board.get(b.id, []), many=True).data,
             "cards_truncated": b.card_count_total > len(by_board.get(b.id, [])),
             "active_count": b.active_total,
             "wip_over": bool(b.wip_limit and b.active_total > b.wip_limit)}
            for b in boards
        ]
        return Response({"project": ProjectSerializer(project).data, "boards": result})

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "列名不能为空"}, status=400)
        max_order = Board.objects.filter(project=project).aggregate(m=ModelsMax("sort_order"))["m"] or 0
        board = Board.objects.create(project=project, name=name, sort_order=max_order + 1)
        _log_activity(project, request.user, "新建了看板列", name)
        return Response(BoardSerializer(board).data, status=201)


class BoardReorderView(APIView):
    """看板列整体排序：传入有序 id 列表"""

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        order = request.data.get("orders") or []
        if not isinstance(order, (list, tuple)):
            return Response({"message": "orders 必须是数组"}, status=400)
        # #58：条数上限，防止一次请求把任意多列重排（也避免超长 IN 查询）
        if len(order) > 100:
            return Response({"message": "单次最多重排 100 个看板列"}, status=400)
        try:
            ids = [as_int(x, field="orders", minimum=1) for x in order]
        except ValidationError:
            return Response({"message": "orders 必须全部为整数"}, status=400)
        boards = {b.id: b for b in Board.objects.filter(id__in=ids, project=project)}
        with transaction.atomic():
            changed = []
            for i, bid in enumerate(ids):
                board = boards.get(bid)
                if board is None or board.sort_order == i:
                    continue
                board.sort_order = i
                changed.append(board)
            if changed:
                Board.objects.bulk_update(changed, ["sort_order"], batch_size=200)
        return Response({"message": "列顺序已更新"})


class BoardDetailView(APIView):
    def get_object(self, request, board_id):
        return Board.objects.filter(pk=board_id, project__members=request.user).first() or Board.objects.filter(
            pk=board_id, project__owner=request.user
        ).first()

    def patch(self, request, board_id):
        board = self.get_object(request, board_id)
        if not board:
            return Response({"message": "看板列不存在"}, status=404)
        if board.project.owner_id != request.user.id and not request.user.is_staff:
            return Response({"message": "仅项目创建者可修改看板列"}, status=403)
        if "name" in request.data:
            board.name = request.data["name"].strip() or board.name
        if "sort_order" in request.data:
            board.sort_order = as_int(request.data["sort_order"], field="sort_order")
        board.save()
        return Response(BoardSerializer(board).data)

    def delete(self, request, board_id):
        board = self.get_object(request, board_id)
        if not board:
            return Response({"message": "看板列不存在"}, status=404)
        if board.project.owner_id != request.user.id and not request.user.is_staff:
            return Response({"message": "仅项目创建者可删除看板列"}, status=403)
        project = board.project
        board.delete()
        _log_activity(project, request.user, "删除了看板列", board.name)
        return Response({"message": "看板列已删除"})


# ============ 任务卡片 ============

class CardListView(APIView):
    def post(self, request, board_id):
        board = Board.objects.filter(pk=board_id).first()
        if not board or not _can_access(request.user, board.project):
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "标题不能为空"}, status=400)
        max_order = TaskCard.objects.filter(board=board).aggregate(m=ModelsMax("sort_order"))["m"] or 0
        card = TaskCard.objects.create(
            board=board, title=title, description=request.data.get("description", ""),
            priority=request.data.get("priority", "medium"), status=request.data.get("status", "todo"),
            due_date=request.data.get("due_date") or None,
            story_points=as_int(request.data.get("story_points"), default=0, field="story_points", minimum=0),
            sort_order=max_order + 1, created_by=request.user,
        )
        if request.data.get("labels"):
            card.labels = request.data["labels"][:10]
            card.save(update_fields=["labels"])
        assignee_ids = request.data.get("assignee_ids") or []
        if assignee_ids:
            # #29：负责人只能是本项目成员（含创建者）
            wanted = [as_int(x, field="assignee_ids") for x in assignee_ids]
            card.assignees.set(_project_member_users(board.project).filter(id__in=wanted))
            for u in card.assignees.all():
                if u.id != request.user.id:
                    notify(u, f"你被分配了新任务「{card.title}」", category="project", link=f"/projects/{board.project_id}")
        _log_activity(board.project, request.user, "创建了任务", card.title)
        # 295：创建人默认关注自己新建的卡片，后续变更才有推送对象
        CardWatcher.objects.get_or_create(card=card, user=request.user)
        # S2-B1：新卡片广播（项目成员多端同步看板）
        _push_board_event(board.project_id, "card.created", card_id=card.id, board_id=board.id)
        return Response(TaskCardSerializer(card).data, status=201)


class CardDetailView(APIView):
    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        data = TaskCardSerializer(card).data
        data["subtasks"] = SubtaskSerializer(card.subtasks.all(), many=True).data
        data["worklogs"] = WorkLogSerializer(card.worklogs.all(), many=True).data
        return Response(data)

    def patch(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        data = request.data
        # 281：字段先归一化，再由 TaskCardSerializer 做局部校验（枚举/类型/长度）
        force = parse_bool(data.get("force"), default=False, field="force")
        payload = {}
        if "title" in data:
            payload["title"] = (str(data.get("title") or "").strip() or card.title)[:200]
        if "description" in data:
            payload["description"] = str(data.get("description") or "")
        if "priority" in data:
            payload["priority"] = data.get("priority")
        if "status" in data:
            payload["status"] = data.get("status")
        if "due_date" in data:
            raw_due = data.get("due_date")
            payload["due_date"] = _parse_date(raw_due) if raw_due else None
            if raw_due and not payload["due_date"]:
                return Response({"message": "due_date 必须是 YYYY-MM-DD 日期"}, status=400)
        if "story_points" in data:
            try:
                payload["story_points"] = as_int(data.get("story_points"), default=0,
                                                field="story_points", minimum=0)
            except ValidationError:
                return Response({"message": "story_points 必须是整数"}, status=400)
        if "labels" in data:
            if not isinstance(data["labels"], list):
                return Response({"message": "labels 必须是数组"}, status=400)
            payload["labels"] = data["labels"][:10]
        new_status = payload.get("status", card.status)
        # 285：DoD 未完成时结单需要 force=1 二次确认
        guard = _dod_guard(card, new_status, force=force)
        if guard:
            return guard
        serializer = TaskCardSerializer(card, data=payload, partial=True)
        if not serializer.is_valid():
            return Response({"message": _first_error(serializer.errors), "errors": serializer.errors}, status=400)
        new_board = None
        if "board" in data:
            try:
                new_board_id = as_int(data.get("board"), field="board", minimum=1) if data.get("board") else None
            except ValidationError:
                return Response({"message": "board 必须是整数"}, status=400)
            new_board = Board.objects.filter(pk=new_board_id, project=card.board.project).first() if new_board_id else None
        if new_board and new_board.id != card.board_id and new_status != "done":
            # 283：并入目标列前校验 WIP 上限，超限直接拒绝（force=1 可强制）
            guard = _wip_guard(new_board, exclude_ids=[card.id], force=force)
            if guard:
                return guard
        wanted_assignees = None
        if "assignee_ids" in data:
            raw_ids = data.get("assignee_ids") or []
            if not isinstance(raw_ids, (list, tuple)):
                return Response({"message": "assignee_ids 必须是数组"}, status=400)
            try:
                # #29：负责人只能是本项目成员（含创建者），与创建 / 批量指派同一口径
                wanted_assignees = [as_int(x, field="assignee_ids") for x in raw_ids]
            except ValidationError:
                return Response({"message": "assignee_ids 必须全部为整数"}, status=400)
        # 状态时间戳：进入 doing 记开始、进入 done 记完成、离开 done 清空
        if new_status != card.status:
            if new_status == "doing" and not card.started_at:
                card.started_at = timezone.now()
            if new_status == "done":
                card.completed_at = timezone.now()
            else:
                card.completed_at = None
        serializer.save()
        if new_board and new_board.id != card.board_id:
            card.board = new_board
            card.sort_order = (TaskCard.objects.filter(board=new_board).aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
            card.save(update_fields=["board", "sort_order"])
        if wanted_assignees is not None:
            card.assignees.set(_project_member_users(card.board.project).filter(id__in=wanted_assignees))
        _log_activity(card.board.project, request.user, "更新了任务", card.title)
        # S2-B1：卡片变更广播（拖拽换列/改状态/改指派都会走到）
        _push_board_event(card.board.project_id, "card.updated",
                          card_id=card.id, board_id=card.board_id)
        # 295：卡片变更只通知关注者
        _notify_watchers(card, request.user, f"你关注的任务「{card.title}」有更新")
        return Response(TaskCardSerializer(card).data)

    def delete(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        title, project = card.title, card.board.project
        card.delete()
        _log_activity(project, request.user, "删除了任务", title)
        # S2-B1：卡片删除广播
        _push_board_event(project.id, "card.deleted", card_id=pk)
        return Response({"message": "任务已删除"})


class CardBatchView(APIView):
    """项目内批量任务：status / priority / assignees / delete / move / archive

    291：前端多选工具条直接复用本接口。请求 {project_id, card_ids, action, ...}，
    响应统一为 {message, ...增量字段}，前端据 message 提示、据字段刷新看板。
    """

    def post(self, request):
        project_id = as_int(request.data.get("project_id"), field="project_id")
        ids = request.data.get("card_ids") or []
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = TaskCard.objects.filter(id__in=[as_int(x, field="card_ids") for x in ids], board__project=project)
        action = request.data.get("action")
        force = parse_bool(request.data.get("force"), default=False, field="force")
        # S2-B1：批量操作统一广播一次（细分 action 供前端按需刷新）
        if action == "delete":
            n = qs.delete()[0]
            _push_board_event(project.id, "card.batch", batch_action="delete", count=n)
            return Response({"message": f"已删除 {n} 个任务", "deleted": n})
        if action == "status":
            v = request.data.get("status")
            if v not in dict(TaskCard.STATUS_CHOICES):
                return Response({"message": "status 只能是 todo / doing / done"}, status=400)
            # 285：批量结单同样校验 DoD，未通过需 force=1
            if v == "done" and not force:
                for c in qs:
                    guard = _dod_guard(c, v)
                    if guard:
                        return guard
            n = qs.count()
            now = timezone.now()
            # #60：进入 done 补 completed_at；离开 done 必须清空，否则未完成卡片被算作已完成
            with transaction.atomic():
                if v == "done":
                    qs.filter(completed_at__isnull=True).update(status=v, completed_at=now)
                    qs.filter(completed_at__isnull=False).update(status=v)
                else:
                    qs.update(status=v, completed_at=None)
            _push_board_event(project.id, "card.batch", batch_action="status", count=n)
            return Response({"message": f"已更新 {n} 个任务状态", "updated": n, "status": v})
        if action == "priority":
            v = request.data.get("priority", "medium")
            if v not in dict(TaskCard.PRIORITY_CHOICES):
                return Response({"message": "priority 只能是 low / medium / high / urgent"}, status=400)
            n = qs.update(priority=v)
            _push_board_event(project.id, "card.batch", batch_action="priority", count=n)
            return Response({"message": f"已更新 {n} 个任务优先级", "updated": n, "priority": v})
        if action == "archive":
            v = parse_bool(request.data.get("is_archived"), default=True, field="is_archived")
            n = qs.update(is_archived=v)
            _push_board_event(project.id, "card.batch", batch_action="archive", count=n, is_archived=v)
            _log_activity(project, request.user, "批量归档了任务" if v else "批量取消归档任务", f"{n} 个卡片")
            return Response({"message": f"已{'归档' if v else '取消归档'} {n} 个任务",
                             "updated": n, "is_archived": v})
        if action == "move":
            try:
                target_board_id = as_int(request.data.get("board_id"), field="board_id", minimum=1)
            except ValidationError:
                return Response({"message": "board_id 必须是整数"}, status=400)
            board = Board.objects.filter(pk=target_board_id, project=project).first()
            if not board:
                return Response({"message": "目标列不存在"}, status=404)
            cards = list(qs)
            if not cards:
                return Response({"message": "已移动 0 个任务"}, status=400)
            moved_ids = [c.id for c in cards]
            # 283：目标列在办数 + 本次移入量超过上限时拒绝（force=1 可强制）
            if not force and board.wip_limit:
                active, limit = _wip_state(board, exclude_ids=moved_ids)
                incoming = len([c for c in cards if c.status != "done" and c.board_id != board.id])
                if active + incoming > limit:
                    return Response({
                        "message": f"「{board.name}」在办 {active}/{limit}，本次移入 {incoming} 张将超限",
                        "over_limit": True, "board_id": board.id,
                        "active_count": active, "wip_limit": limit,
                    }, status=409)
            # #61：复用单卡移动的排序逻辑——批量追加到目标列末尾，再重排目标列与各源列
            source_board_ids = {c.board_id for c in cards}
            with transaction.atomic():
                target_cards = list(
                    TaskCard.objects.filter(board=board).exclude(id__in=moved_ids).order_by("sort_order", "id")
                )
                for c in cards:
                    c.board = board
                    c.sort_order = len(target_cards)
                    target_cards.append(c)
                # board 与 sort_order 一起落库：_apply_sort_order 依赖内存值与库内一致
                TaskCard.objects.bulk_update(cards, ["board", "sort_order"], batch_size=500)
                _apply_sort_order(target_cards)
                for sid in source_board_ids - {board.id}:
                    _renumber_board(sid)
            _push_board_event(project.id, "card.batch", batch_action="move", count=len(cards),
                              board_id=board.id)
            return Response({"message": f"已移动 {len(cards)} 个任务", "moved": moved_ids,
                             "board_id": board.id, "board_name": board.name})
        if action == "assignees":
            raw_ids = request.data.get("user_ids") or []
            if not isinstance(raw_ids, (list, tuple)):
                return Response({"message": "user_ids 必须是数组"}, status=400)
            try:
                user_ids = [as_int(x, field="user_ids", minimum=1) for x in raw_ids]
            except ValidationError:
                return Response({"message": "user_ids 必须全部为整数"}, status=400)
            # #29：批量指派同样只能落到项目成员
            users = _project_member_users(project).filter(id__in=user_ids)
            for c in qs:
                c.assignees.set(users)
            return Response({"message": "已批量分配负责人", "user_ids": list(users.values_list("id", flat=True))})
        return Response({"message": "未知操作"}, status=400)


class CardCopyView(APIView):
    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        # #60：先锁项目行并一次取号，避免 TaskCard.save 在每张卡上各抢一次项目锁
        # （复制一卡 + N 个子任务原本是 N 次加锁；模板批量应用同理）。
        with transaction.atomic():
            project_id = card.board.project_id
            Project.objects.select_for_update().filter(pk=project_id).first()
            max_order = TaskCard.objects.filter(board=card.board).aggregate(m=ModelsMax("sort_order"))["m"] or 0
            number = (TaskCard.objects.filter(board__project_id=project_id).aggregate(m=ModelsMax("number"))["m"] or 0) + 1
            copy = TaskCard.objects.create(
                board=card.board, title=f"{card.title}（副本）", description=card.description,
                priority=card.priority, labels=card.labels, due_date=card.due_date,
                story_points=card.story_points, sort_order=max_order + 1, number=number, created_by=request.user,
            )
            copy.assignees.set(card.assignees.all())
            for st in card.subtasks.all():
                Subtask.objects.create(card=copy, title=st.title, is_done=False, sort_order=st.sort_order)
        return Response(TaskCardSerializer(copy).data, status=201)


class CardMoveView(APIView):
    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        target_board_id = as_int(request.data.get("board_id"), field="board_id") if request.data.get("board_id") else None
        target_index = as_int(request.data.get("index"), default=0, field="index", minimum=0)
        target_board = None
        if target_board_id:
            target_board = Board.objects.filter(pk=target_board_id, project=card.board.project).first()
            if not target_board:
                return Response({"message": "目标列不存在"}, status=404)
            # 283：跨列拖拽先校验目标列 WIP 上限，超限拒绝（force=1 可强制）
            if target_board.id != card.board_id and card.status != "done":
                force = parse_bool(request.data.get("force"), default=False, field="force")
                guard = _wip_guard(target_board, exclude_ids=[card.id], force=force)
                if guard:
                    return guard
        # #56：移动 =「换列 + 整列重排」，两步必须在同一事务内并对 board 加行锁，
        # 否则并发拖拽会互相覆盖 sort_order。锁按 id 升序加，避免两列互移时死锁
        # （SQLite 下 select_for_update 为 no-op，行为与改造前一致）。
        with transaction.atomic():
            lock_ids = sorted({card.board_id, target_board.id if target_board else card.board_id})
            list(Board.objects.select_for_update().filter(pk__in=lock_ids).order_by("id"))
            source_board_id = card.board_id
            if target_board:
                card.board = target_board
            card.sort_order = target_index
            card.save()
            siblings = list(TaskCard.objects.filter(board=card.board).exclude(pk=card.pk).order_by("sort_order", "id"))
            siblings.insert(min(target_index, len(siblings)), card)
            # #141：整列重排改为一次 bulk_update，不再逐卡 UPDATE
            _apply_sort_order(siblings)
            if source_board_id != card.board_id:
                # 源列移出卡片后收敛空洞序号
                _renumber_board(source_board_id)
        _log_activity(card.board.project, request.user, "移动了任务", card.title)
        return Response({"message": "已移动", "card": TaskCardSerializer(card).data})


class CardSearchView(APIView):
    """项目内任务筛选/搜索：关键字/优先级/状态/负责人/标签/到期分桶

    292：关键字同时匹配标题与描述，服务端分页并返回 total / has_more；
    带 q 时每张卡另附 highlight.title / highlight.description（HTML 已转义，
    命中词包 <mark>），前端可直接渲染高亮。
    """

    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 200

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = TaskCard.objects.filter(board__project=project)
        kw = (request.query_params.get("q") or "").strip()
        if kw:
            qs = qs.filter(Q(title__icontains=kw) | Q(description__icontains=kw))
        for f in ("priority", "status"):
            v = request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        assignee = request.query_params.get("assignee")
        if assignee:
            try:
                assignee = as_int(assignee, field="assignee", minimum=1)
            except ValidationError:
                return Response({"message": "assignee 必须是整数"}, status=400)
            qs = qs.filter(assignees__id=assignee)
        label = request.query_params.get("label")
        if label:
            qs = qs.filter(labels__contains=[label])
        due = request.query_params.get("due")
        today = timezone.now().date()
        if due == "overdue":
            qs = qs.filter(due_date__lt=today).exclude(status="done")
        elif due == "today":
            qs = qs.filter(due_date=today)
        elif due == "week":
            qs = qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))
        elif due == "nodate":
            qs = qs.filter(due_date__isnull=True)
        try:
            size = as_int(request.query_params.get("page_size") or request.query_params.get("size"),
                          default=self.DEFAULT_PAGE_SIZE, field="page_size", minimum=1,
                          maximum=self.MAX_PAGE_SIZE)
            page_no = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
        except ValidationError:
            return Response({"message": f"page_size 必须是 1-{self.MAX_PAGE_SIZE} 的整数，page 必须是正整数"}, status=400)
        qs = (
            qs.select_related("board", "board__project")
            .prefetch_related(
                "assignees", "comments", "subtasks", "acceptance_items", "worklogs",
                Prefetch("dependencies", queryset=CardDependency.objects.select_related("blocked_by")),
            )
            .distinct()
            .order_by("sort_order", "id")
        )
        total = qs.count()
        start = (page_no - 1) * size
        rows = list(qs[start:start + size])
        data = TaskCardSerializer(rows, many=True).data
        if kw:
            for card, item in zip(rows, data):
                item["highlight"] = {
                    "title": _highlight(card.title, kw),
                    "description": _highlight(card.description, kw),
                }
        return Response({
            "list": data, "total": total, "keyword": kw,
            "page": page_no, "page_size": size,
            "has_more": start + size < total,
        })


# ============ 子任务 ============

class SubtaskListView(APIView):
    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "子任务标题不能为空"}, status=400)
        order = (card.subtasks.aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        # #30：负责人必须是项目成员，拒绝无效 / 不可见 id
        assignee, err = _subtask_assignee(card, request.data.get("assignee_id"))
        if err:
            return Response({"message": err}, status=400)
        st = Subtask.objects.create(card=card, title=title, sort_order=order, assignee=assignee)
        return Response(SubtaskSerializer(st).data, status=201)


class SubtaskDetailView(APIView):
    def _get(self, request, pk, sid):
        return Subtask.objects.filter(pk=sid, card_id=pk, card__board__project__members=request.user).first() or \
            Subtask.objects.filter(pk=sid, card_id=pk, card__board__project__owner=request.user).first()

    def patch(self, request, pk, sid):
        st = self._get(request, pk, sid)
        if not st:
            return Response({"message": "子任务不存在"}, status=404)
        if "title" in request.data:
            st.title = request.data["title"].strip() or st.title
        if "is_done" in request.data:
            st.is_done = parse_bool(request.data["is_done"], field="is_done")
        if "assignee_id" in request.data:
            # #30：改派同样收敛到项目成员
            assignee, err = _subtask_assignee(st.card, request.data["assignee_id"])
            if err:
                return Response({"message": err}, status=400)
            st.assignee = assignee
        st.save()
        return Response(SubtaskSerializer(st).data)

    def delete(self, request, pk, sid):
        st = self._get(request, pk, sid)
        if not st:
            return Response({"message": "子任务不存在"}, status=404)
        st.delete()
        return Response({"message": "子任务已删除"})


# ============ 工时 ============

class WorkLogListView(APIView):
    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        return Response({"list": WorkLogSerializer(card.worklogs.all(), many=True).data,
                         "total_minutes": card.worklogs.aggregate(s=ModelsSum("minutes"))["s"] or 0})

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        minutes = as_int(request.data.get("minutes"), default=0, field="minutes", minimum=0)
        if minutes <= 0:
            return Response({"message": "工时必须大于 0 分钟"}, status=400)
        wl = WorkLog.objects.create(card=card, user=request.user, minutes=minutes, note=request.data.get("note", "")[:200])
        return Response(WorkLogSerializer(wl).data, status=201)


class WorkLogDetailView(APIView):
    def delete(self, request, pk, wid):
        wl = WorkLog.objects.filter(pk=wid, card_id=pk, user=request.user).first()
        if not wl:
            return Response({"message": "工时记录不存在"}, status=404)
        wl.delete()
        return Response({"message": "工时记录已删除"})


# ============ 评论 ============

class CardCommentListView(APIView):
    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        qs = card.comments.all()
        return Response({"list": CardCommentSerializer(qs, many=True, context={"request": request}).data, "total": qs.count()})

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "评论内容不能为空"}, status=400)
        comment = CardComment.objects.create(card=card, author=request.user, content=content)
        # 295：通知负责人与关注者（按用户去重，排除评论者本人）
        recipients = {u.id: u for u in card.assignees.exclude(id=request.user.id)}
        for u in _watcher_users(card).exclude(id=request.user.id):
            recipients.setdefault(u.id, u)
        notify_many(list(recipients.values()), f"任务「{card.title}」有新评论",
                    category="project", link=f"/projects/{card.board.project_id}")
        _log_activity(card.board.project, request.user, "评论了任务", card.title)
        return Response(CardCommentSerializer(comment, context={"request": request}).data, status=201)


class CardCommentDetailView(APIView):
    """评论编辑 / 删除（作者或项目所有者）"""

    def _get(self, request, pk, cid):
        c = CardComment.objects.filter(pk=cid, card_id=pk).first()
        if not c:
            return None
        project = c.card.board.project
        if request.user.id != c.author_id and request.user.id != project.owner_id:
            return False
        return c

    def patch(self, request, pk, cid):
        c = self._get(request, pk, cid)
        if c is False:
            return Response({"message": "无权编辑该评论"}, status=403)
        if not c:
            return Response({"message": "评论不存在"}, status=404)
        content = (request.data.get("content") or "").strip()
        if content:
            c.content = content
            c.save(update_fields=["content", "updated_at"])
        return Response(CardCommentSerializer(c, context={"request": request}).data)

    def delete(self, request, pk, cid):
        c = self._get(request, pk, cid)
        if c is False:
            return Response({"message": "无权删除该评论"}, status=403)
        if not c:
            return Response({"message": "评论不存在"}, status=404)
        c.delete()
        return Response({"message": "评论已删除"})


# ============ 活动 / 统计 / 跨项目 ============

class ProjectActivityView(APIView):
    """项目活动流（分页 + 操作人/动作筛选）

    294：page / page_size 分页，actor（用户 id）与 action（关键字）筛选，
    响应 {list,total,page,page_size,has_more} 供“动态”页签滚动加载。
    """

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = project.activities.select_related("user").order_by("-created_at", "-id")
        action = (request.query_params.get("action") or "").strip()
        if action:
            qs = qs.filter(action__icontains=action)
        actor = request.query_params.get("actor")
        if actor:
            try:
                actor_id = as_int(actor, field="actor", minimum=1)
            except ValidationError:
                return Response({"message": "actor 必须是整数"}, status=400)
            qs = qs.filter(user_id=actor_id)
        try:
            size = as_int(request.query_params.get("page_size") or request.query_params.get("size"),
                          default=30, field="page_size", minimum=1, maximum=100)
            page_no = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
        except ValidationError:
            return Response({"message": "page_size 必须是 1-100 的整数，page 必须是正整数"}, status=400)
        total = qs.count()
        start = (page_no - 1) * size
        rows = qs[start:start + size]
        return Response({
            "list": ProjectActivitySerializer(rows, many=True).data, "total": total,
            "page": page_no, "page_size": size, "has_more": start + size < total,
        })


class ProjectStatsView(APIView):
    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        cards = TaskCard.objects.filter(board__project=project)
        by_board = list(cards.values("board__name", "board_id").annotate(c=ModelsCount("id")).order_by())
        by_priority = list(cards.values("priority").annotate(c=ModelsCount("id")).order_by())
        by_status = list(cards.values("status").annotate(c=ModelsCount("id")).order_by())
        by_assignee = list(
            cards.values("assignees__username", "assignees__nickname").annotate(c=ModelsCount("id")).order_by("-c")
        )
        overdue = cards.filter(due_date__lt=timezone.now().date(), status__in=["todo", "doing"]).count()
        total_points = cards.aggregate(s=ModelsSum("story_points"))["s"] or 0
        done_points = cards.filter(status="done").aggregate(s=ModelsSum("story_points"))["s"] or 0
        spent = cards.aggregate(s=ModelsSum("worklogs__minutes"))["s"] or 0
        return Response({
            "total": cards.count(),
            "done": cards.filter(status="done").count(),
            "doing": cards.filter(status="doing").count(),
            "todo": cards.filter(status="todo").count(),
            "overdue": overdue,
            "total_points": total_points,
            "done_points": done_points,
            "spent_minutes": spent,
            "by_board": by_board, "by_priority": by_priority, "by_status": by_status, "by_assignee": by_assignee,
            "activities": ProjectActivitySerializer(project.activities.all()[:20], many=True).data,
        })


class ProjectCalendarView(APIView):
    """按截止日期聚合任务（日历/甘特数据）

    #116：原实现把项目内「全部」有截止日的卡片载入内存再分组，项目跑久了
    一次响应就是全历史。现在默认只取 [今天, 今天+90 天] 窗口，
    用 values 只取必要字段；需要更宽范围时用 ?from=YYYY-MM-DD&to=YYYY-MM-DD
    （或 ?days=180），返回结构仍是 {"days": {"YYYY-MM-DD": [...]}}。
    """

    DEFAULT_WINDOW_DAYS = 90
    MAX_WINDOW_DAYS = 3660
    MAX_CARDS = 5000

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        today = timezone.localdate()
        try:
            days = as_int(
                request.query_params.get("days"), default=self.DEFAULT_WINDOW_DAYS,
                field="days", minimum=1, maximum=self.MAX_WINDOW_DAYS,
            )
            date_from = (
                as_date(request.query_params["from"], field="from")
                if request.query_params.get("from") else today
            )
            date_to = (
                as_date(request.query_params["to"], field="to")
                if request.query_params.get("to") else date_from + timedelta(days=days)
            )
        except ValidationError as exc:
            return Response({"message": str(exc.detail[0]) if exc.detail else "日期参数不合法"}, status=400)
        if date_to < date_from:
            return Response({"message": "to 不能早于 from"}, status=400)
        if (date_to - date_from).days > self.MAX_WINDOW_DAYS:
            return Response({"message": f"时间窗不能超过 {self.MAX_WINDOW_DAYS} 天"}, status=400)

        cards = (
            TaskCard.objects.filter(board__project=project, due_date__range=(date_from, date_to))
            .order_by("due_date", "id")
            .values("id", "title", "status", "priority", "due_date")[: self.MAX_CARDS]
        )
        day_map = {}
        for c in cards:
            day_map.setdefault(str(c["due_date"]), []).append({
                "id": c["id"], "title": c["title"], "status": c["status"], "priority": c["priority"],
            })
        return Response({
            "days": day_map,
            "total": sum(len(v) for v in day_map.values()),
            "window": {"from": str(date_from), "to": str(date_to)},
        })


class MyTasksView(APIView):
    """跨项目「我的任务」：分配给我 / 我创建，支持状态与到期分桶"""

    def get(self, request):
        scope = request.query_params.get("scope", "assigned")
        if scope == "created":
            qs = TaskCard.objects.filter(created_by=request.user)
        else:
            qs = TaskCard.objects.filter(assignees=request.user)
        qs = qs.filter(board__project__is_archived=False)
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        # #63：统一用 localdate（原 UTC 日期在东八区凌晨会错一天）
        today = timezone.localdate()
        bucket = request.query_params.get("bucket")
        if bucket == "overdue":
            qs = qs.filter(due_date__lt=today).exclude(status="done")
        elif bucket == "today":
            qs = qs.filter(due_date=today)
        elif bucket == "week":
            qs = qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))
        elif bucket == "nodate":
            qs = qs.filter(due_date__isnull=True)
        # #63：total 必须与列表用同一组过滤条件统计，不能拿 [:200] 的长度充数
        total = qs.count()
        qs = (
            qs.select_related("board", "board__project")
            .prefetch_related(
                "assignees", "comments", "subtasks", "acceptance_items", "worklogs",
                Prefetch("dependencies", queryset=CardDependency.objects.select_related("blocked_by")),
            )
            .distinct()
            .order_by("due_date", "-id")
        )
        data = []
        for c in qs[:200]:
            d = TaskCardSerializer(c).data
            d["project_id"] = c.board.project_id
            d["project_name"] = c.board.project.name
            data.append(d)
        # 分桶计数：与列表一致地排除已归档项目
        all_mine = TaskCard.objects.filter(
            assignees=request.user, board__project__is_archived=False
        ).exclude(status="done")
        counts = {
            "all": TaskCard.objects.filter(
                assignees=request.user, board__project__is_archived=False
            ).count(),
            "open": all_mine.count(),
            "overdue": all_mine.filter(due_date__lt=today).count(),
            "today": all_mine.filter(due_date=today).count(),
            "week": all_mine.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
            "done": TaskCard.objects.filter(
                assignees=request.user, status="done", board__project__is_archived=False
            ).count(),
        }
        return Response({"list": data, "total": total, "counts": counts})


# ===========================================================================
# 看板增强 F583–F598（纯新增，不改动上方既有接口）
# ===========================================================================

def _board_of(user, board_id):
    try:
        board_id = as_int(board_id, field="board_id", minimum=1)
    except ValidationError:
        return None
    board = Board.objects.filter(pk=board_id).first()
    if not board or not _can_access(user, board.project):
        return None
    return board


def _parse_date(value):
    """把 YYYY-MM-DD 字符串解析为 date，非法则返回 None（避免写入时报 500）"""
    if not value:
        return None
    from datetime import datetime as _dt

    try:
        return _dt.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class CardCountdownView(APIView):
    """F583 卡片倒计时徽章：返回剩余天数与告警级别"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        if not card.due_date:
            return Response({"has_due": False, "level": "none", "text": "未设置截止日期",
                             "card_id": card.id, "code": card.code})
        today = timezone.localdate()
        days = (card.due_date - today).days
        if card.status == "done":
            level, text = "done", "已完成"
        elif days < 0:
            level, text = "overdue", f"已逾期 {abs(days)} 天"
        elif days == 0:
            level, text = "danger", "今天到期"
        elif days <= 2:
            level, text = "warning", f"还剩 {days} 天"
        else:
            level, text = "normal", f"还剩 {days} 天"
        return Response({
            "has_due": True, "card_id": card.id, "code": card.code,
            "due_date": str(card.due_date), "days_left": days,
            "days_overdue": max(-days, 0),
            "overdue": days < 0 and card.status != "done",
            "level": level, "text": text, "status": card.status,
        })


class CardChecklistView(APIView):
    """F584 checklist 独立视图：列出/新增检查清单项及完成度"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        items = card.subtasks.all()
        total = items.count()
        done = items.filter(is_done=True).count()
        return Response({
            "card_id": card.id, "code": card.code, "title": card.title,
            "list": SubtaskSerializer(items, many=True).data,
            "total": total, "done": done,
            "progress": round(done / total * 100) if total else 0,
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "清单项不能为空"}, status=400)
        order = (card.subtasks.aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        # #30：负责人必须是项目成员，拒绝无效 / 不可见 id
        assignee, err = _subtask_assignee(card, request.data.get("assignee_id"))
        if err:
            return Response({"message": err}, status=400)
        st = Subtask.objects.create(card=card, title=title, sort_order=order, assignee=assignee)
        return Response(SubtaskSerializer(st).data, status=201)


class BoardWipView(APIView):
    """F585 列 WIP 上限：查询/设置某列在制品上限并提示超限

    283：响应补充 active / limit / over_limit 别名，前端列头直接显示
    「active/limit」并在超限时标红；超限拖入会被 CardMoveView 等拒绝。
    """

    def get(self, request, board_id):
        board = _board_of(request.user, board_id)
        if not board:
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        cards = board.cards.all()
        total = cards.count()
        active = cards.exclude(status="done").count()
        limit = board.wip_limit or 0
        over = bool(limit and active > limit)
        return Response({
            "board_id": board.id, "name": board.name, "wip_limit": limit,
            "card_count": total, "active_count": active, "over": over,
            "active": active, "limit": limit, "over_limit": over,
            "message": f"超限：{active}/{limit}，请先完成或移出部分卡片" if over else "正常",
        })

    def post(self, request, board_id):
        board = _board_of(request.user, board_id)
        if not board:
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        limit = as_int(request.data.get("wip_limit"), default=0, field="wip_limit", minimum=0)
        board.wip_limit = max(limit, 0)
        board.save(update_fields=["wip_limit"])
        active = board.cards.exclude(status="done").count()
        over = bool(board.wip_limit and active > board.wip_limit)
        return Response({"message": "已更新 WIP 上限", "board_id": board.id, "wip_limit": board.wip_limit,
                         "active_count": active, "over": over,
                         "active": active, "limit": board.wip_limit, "over_limit": over})


class CardTimelineView(APIView):
    """F586 卡片活动时间线：创建/开始/完成/解决/评论/工时/项目动态聚合

    290：支持 page / page_size 分页，也支持 before=<ISO 时间> 游标（取更早事件），
    响应附带 total / has_more / next_before，前端可无限滚动加载。
    """

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        events = []

        def add(kind, at, text, user=""):
            if at:
                events.append({"type": kind, "at": at.isoformat(), "text": text, "user": user})

        add("created", card.created_at, "创建了卡片", card.created_by.display_name if card.created_by else "")
        add("started", card.started_at, "开始处理", "")
        add("completed", card.completed_at, "完成了卡片", "")
        if card.resolved_at:
            add("resolved", card.resolved_at, f"标记解决：{card.resolve_reason}" if card.resolve_reason else "标记解决", "")
        for c in card.comments.all():
            add("comment", c.created_at, c.content[:200], c.author.display_name if c.author else "")
        for w in card.worklogs.all():
            add("worklog", w.created_at, f"登记工时 {w.minutes} 分钟" + (f"：{w.note}" if w.note else ""),
                w.user.display_name if w.user else "")
        for a in card.board.project.activities.filter(target=card.title)[:50]:
            add("activity", a.created_at, a.action, a.user.display_name if a.user else "系统")
        events.sort(key=lambda e: e["at"], reverse=True)
        before = (request.query_params.get("before") or "").strip()
        if before:
            events = [e for e in events if e["at"] < before]
        try:
            size = as_int(request.query_params.get("page_size") or request.query_params.get("size"),
                          default=30, field="page_size", minimum=1, maximum=100)
            page_no = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
        except ValidationError:
            return Response({"message": "page_size 必须是 1-100 的整数，page 必须是正整数"}, status=400)
        total = len(events)
        start = (page_no - 1) * size
        page_events = events[start:start + size]
        return Response({
            "card_id": card.id, "code": card.code, "title": card.title,
            "list": page_events, "total": total,
            "page": page_no, "page_size": size,
            "has_more": start + size < total,
            "next_before": page_events[-1]["at"] if page_events and start + size < total else None,
        })


class ProjectWeeklyReportView(APIView):
    """F587 看板周报：近 7 天新增/完成/剩余三线数据"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        span = as_int(request.query_params.get("days"), default=7, field="days", minimum=1, maximum=30)
        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(span - 1, -1, -1)]
        cards = list(TaskCard.objects.filter(board__project=project))
        created_series, completed_series, remaining_series = [], [], []
        for d in days:
            created_series.append(sum(1 for c in cards if c.created_at.date() == d))
            completed_series.append(sum(1 for c in cards if c.completed_at and c.completed_at.date() == d))
            remaining_series.append(sum(
                1 for c in cards
                if c.created_at.date() <= d and not (c.completed_at and c.completed_at.date() <= d)
            ))
        summary = {
            "created": sum(created_series),
            "completed": sum(completed_series),
            "open_now": remaining_series[-1] if remaining_series else 0,
            "total": len(cards),
        }
        # 299：直接给出可复制 / 可下载的 Markdown 周报
        overdue = TaskCard.objects.filter(
            board__project=project, status__in=["todo", "doing"], due_date__lt=today
        ).count()
        markdown = "\n".join([
            f"# {project.name} 周报（{days[0]} ~ {days[-1]}）",
            "",
            f"- 新增任务：{summary['created']}",
            f"- 完成任务：{summary['completed']}",
            f"- 当前未完成：{summary['open_now']}",
            f"- 逾期未完成：{overdue}",
            f"- 任务总数：{summary['total']}",
            "",
            "## 每日燃尽",
            "| 日期 | 新增 | 完成 | 剩余 |",
            "| --- | --- | --- | --- |",
            *[f"| {d} | {created_series[i]} | {completed_series[i]} | {remaining_series[i]} |"
              for i, d in enumerate(days)],
        ])
        return Response({
            "dates": [str(d) for d in days],
            "created": created_series,
            "completed": completed_series,
            "remaining": remaining_series,
            "summary": {**summary, "overdue": overdue},
            "title": f"{project.name} 周报",
            "markdown": markdown,
            "filename": f"{project.name}-周报-{today}.md",
            "generated_at": timezone.now(),
        })


class CardDependencyView(APIView):
    """F588 卡片依赖：查询/新增/移除阻塞关系"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        deps = card.dependencies.select_related("blocked_by")
        blocks = card.blocks.select_related("card")
        blockers = [{"id": d.blocked_by_id, "code": d.blocked_by.code, "title": d.blocked_by.title,
                     "status": d.blocked_by.status} for d in deps]
        return Response({
            "card_id": card.id, "code": card.code,
            "blocked_by": blockers,
            "blocking": [{"id": b.card_id, "code": b.card.code, "title": b.card.title,
                          "status": b.card.status} for b in blocks],
            "is_blocked": any(b["status"] != "done" for b in blockers),
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        ids = request.data.get("blocked_by_ids")
        if ids is None:
            ids = [request.data.get("blocked_by_id")] if request.data.get("blocked_by_id") else []
        project_id = card.board.project_id
        added = []
        skipped = []
        for bid in ids:
            if not bid:
                continue
            bid_int = as_int(bid, field="blocked_by_id")
            if bid_int == card.id:
                continue
            other = TaskCard.objects.filter(pk=bid_int, board__project_id=project_id).first()
            if not other:
                continue
            # #59：传递闭包检测——若 other 已（间接）依赖 card，再加 card→other 就成环
            if _dependency_path_exists(other.id, card.id):
                skipped.append(other.id)
                continue
            CardDependency.objects.get_or_create(card=card, blocked_by=other)
            added.append(other.id)
        return Response({"message": f"已添加 {len(added)} 条依赖", "added": added,
                         "skipped_cycle": skipped}, status=201)

    def delete(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        bid = as_int(request.query_params.get("blocked_by_id"), field="blocked_by_id")
        deleted = card.dependencies.filter(blocked_by_id=bid).delete()[0]
        return Response({"message": f"已移除 {deleted} 条依赖"})


class ProjectMilestoneView(APIView):
    """F589 里程碑：列表 / 新建"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = project.milestones.all()
        today = timezone.localdate()
        data = MilestoneSerializer(qs, many=True).data
        for d in data:
            d["overdue"] = bool(d["due_date"] and d["status"] != "done" and str(today) > d["due_date"])
        return Response({"list": data, "total": len(data)})

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "里程碑名称不能为空"}, status=400)
        ms = Milestone.objects.create(
            project=project, name=name, description=request.data.get("description", ""),
            due_date=_parse_date(request.data.get("due_date")),
            status=request.data.get("status", "planned"),
        )
        _log_activity(project, request.user, "新建了里程碑", name)
        return Response(MilestoneSerializer(ms).data, status=201)


class MilestoneDetailView(APIView):
    """F589 里程碑：更新 / 删除"""

    def _get(self, request, pk):
        ms = Milestone.objects.filter(pk=pk).first()
        if not ms or not _can_access(request.user, ms.project):
            return None
        return ms

    def patch(self, request, pk):
        ms = self._get(request, pk)
        if not ms:
            return Response({"message": "里程碑不存在或无权访问"}, status=404)
        for f in ("name", "description", "status"):
            if f in request.data:
                setattr(ms, f, request.data[f])
        if "due_date" in request.data:
            ms.due_date = _parse_date(request.data["due_date"])
        ms.save()
        return Response(MilestoneSerializer(ms).data)

    def delete(self, request, pk):
        ms = self._get(request, pk)
        if not ms:
            return Response({"message": "里程碑不存在或无权访问"}, status=404)
        ms.delete()
        return Response({"message": "里程碑已删除"})


class CardEstimateView(APIView):
    """F590 工时估算与累计：预估 vs 实际"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        spent = card.worklogs.aggregate(s=ModelsSum("minutes"))["s"] or 0
        estimated = card.estimated_minutes or 0
        # 289：卡片面部 spent/estimate 双数值与差额（正数=超出预估）
        diff = (spent - estimated) if estimated else 0
        return Response({
            "card_id": card.id, "code": card.code, "story_points": card.story_points,
            "estimated_minutes": estimated, "spent_minutes": spent,
            "estimate": estimated, "spent": spent,
            "diff": diff, "over_by": max(diff, 0),
            "remaining_minutes": max(estimated - spent, 0), "over": bool(estimated and spent > estimated),
            "progress": round(spent / estimated * 100) if estimated else 0,
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        minutes = as_int(request.data.get("estimated_minutes"), default=0, field="estimated_minutes", minimum=0)
        card.estimated_minutes = max(minutes, 0)
        card.save(update_fields=["estimated_minutes"])
        return Response({"message": "已更新预估工时", "estimated_minutes": card.estimated_minutes})


class ProjectWorkloadView(APIView):
    """F591 成员工作量分布

    #115：原实现对每个成员跑 5 条 count/aggregate（成员 N 个 → 5N+ 次查询）。
    改成两条分组聚合：按 assignees 一次算出 total/open/done/overdue/points，
    工时按 user 一次分组；查询数与成员数无关。响应结构不变。
    """

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        today = timezone.localdate()
        # m2m 只有 (card, user) 唯一对，按 assignees 分组后每张卡在每个成员下只出现一次，
        # 因此 count 不需要 distinct=True，points 求和也不会被成员数放大。
        per_user = {
            row["assignees"]: row
            for row in (
                TaskCard.objects.filter(board__project=project, assignees__isnull=False)
                .values("assignees")
                .annotate(
                    total=ModelsCount("id"),
                    open=ModelsCount("id", filter=~Q(status="done")),
                    done=ModelsCount("id", filter=Q(status="done")),
                    overdue=ModelsCount("id", filter=Q(due_date__lt=today) & ~Q(status="done")),
                    open_points=ModelsSum("story_points", filter=~Q(status="done")),
                )
                .order_by()
            )
        }
        spent_map = {
            row["user_id"]: row["minutes"] or 0
            for row in (
                WorkLog.objects.filter(card__board__project=project)
                .values("user_id")
                .annotate(minutes=ModelsSum("minutes"))
                .order_by()
            )
        }
        rows = []
        for u in project.members.all():
            agg = per_user.get(u.id) or {}
            rows.append({
                "user_id": u.id, "display_name": u.display_name,
                "total": agg.get("total") or 0,
                "open": agg.get("open") or 0,
                "done": agg.get("done") or 0,
                "overdue": agg.get("overdue") or 0,
                "open_points": agg.get("open_points") or 0,
                "spent_minutes": spent_map.get(u.id, 0),
            })
        max_open = max([r["open"] for r in rows], default=0)
        for r in rows:
            r["load_percent"] = round(r["open"] / max_open * 100) if max_open else 0
            # 297：未完成超过 8 张标红提示（前端图表直接用）
            r["heavy"] = r["open"] > 8
        rows.sort(key=lambda r: r["open"], reverse=True)
        return Response({"list": rows, "total": len(rows), "max_open": max_open,
                         "heavy_threshold": 8})


class CardByNumberView(APIView):
    """F592/F596 通过项目内编号（C-n）定位卡片

    305：同时接受纯数字（/cards/by-number/12/）与 "C-12" 形式（/cards/by-number/C-12/）。
    """

    def get(self, request, project_id, number=None, code=None):
        raw = number if number is not None else code
        if isinstance(raw, str):
            matched = re.match(r"^\s*(?:c-?)?(\d+)\s*$", raw, flags=re.IGNORECASE)
            if not matched:
                return Response({"message": "编号格式应为 C-12 或 12"}, status=400)
            raw = int(matched.group(1))
        if raw is None:
            return Response({"message": "缺少卡片编号"}, status=400)
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        card = TaskCard.objects.filter(board__project=project, number=raw).first()
        if not card:
            return Response({"message": f"C-{raw} 不存在"}, status=404)
        data = TaskCardSerializer(card).data
        data["project_id"] = project.id
        data["project_name"] = project.name
        return Response(data)


class CardBatchMoveView(APIView):
    """F593 批量移动卡片到目标列（保持传入顺序）

    291：请求 {project_id, board_id, card_ids, index?}，响应
    {message, moved:[card_id], board_id, board_name}；目标列超 WIP 上限时
    返回 409 {over_limit, active_count, wip_limit}，带 force=1 可强制移入。
    """

    def post(self, request):
        try:
            project_id = as_int(request.data.get("project_id"), field="project_id", minimum=1)
            board_id = as_int(request.data.get("board_id"), field="board_id", minimum=1)
        except ValidationError:
            return Response({"message": "project_id / board_id 必须是整数"}, status=400)
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        board = Board.objects.filter(pk=board_id, project=project).first()
        if not board:
            return Response({"message": "目标列不存在"}, status=404)
        raw_ids = request.data.get("card_ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "card_ids 必须是数组"}, status=400)
        try:
            # #57：去重（同一 card_id 传多次不再重复移动 / 重复排序）
            ids = list(dict.fromkeys(as_int(x, field="card_ids", minimum=1) for x in raw_ids))
        except ValidationError:
            return Response({"message": "card_ids 必须全部为整数"}, status=400)
        cards = list(TaskCard.objects.filter(id__in=ids, board__project=project).order_by("sort_order", "id"))
        if not cards:
            return Response({"message": "没有可移动的卡片"}, status=400)
        raw_start = request.data.get("index")
        start = as_int(raw_start, default=0, field="index", minimum=0) if raw_start is not None else None
        moved = [c.id for c in cards]
        source_board_ids = {c.board_id for c in cards}
        # 283：目标列 WIP 超限时拒绝批量移入（force=1 可强制）
        try:
            force = parse_bool(request.data.get("force"), default=False, field="force")
        except ValidationError:
            return Response({"message": "force 必须是布尔值"}, status=400)
        if not force and board.wip_limit:
            active, limit = _wip_state(board, exclude_ids=moved)
            incoming = len([c for c in cards if c.status != "done" and c.board_id != board.id])
            if active + incoming > limit:
                return Response({
                    "message": f"「{board.name}」在办 {active}/{limit}，本次移入 {incoming} 张将超限",
                    "over_limit": True, "board_id": board.id,
                    "active_count": active, "wip_limit": limit,
                }, status=409)
        # #57：与 CardBatchView.move 同一套写法——锁 board → 拼出目标列完整顺序 →
        # bulk_update 一次落库 → 源列 _renumber_board 收敛空洞，不再逐卡 save。
        with transaction.atomic():
            list(
                Board.objects.select_for_update()
                .filter(pk__in=sorted(source_board_ids | {board.id}))
                .order_by("id")
            )
            target_cards = list(
                TaskCard.objects.filter(board=board).exclude(id__in=moved).order_by("sort_order", "id")
            )
            insert_at = len(target_cards) if start is None else min(start, len(target_cards))
            ordered = target_cards[:insert_at]
            for c in cards:
                c.board = board
                c.sort_order = len(ordered)
                ordered.append(c)
            ordered.extend(target_cards[insert_at:])
            # board 与 sort_order 一起落库：_apply_sort_order 依赖内存值与库内一致
            TaskCard.objects.bulk_update(cards, ["board", "sort_order"], batch_size=500)
            _apply_sort_order(ordered)
            for sid in source_board_ids - {board.id}:
                _renumber_board(sid)
        _log_activity(project, request.user, "批量移动了任务", f"{len(moved)} 个 → {board.name}")
        return Response({"message": f"已移动 {len(moved)} 个任务", "moved": moved,
                         "board_id": board.id, "board_name": board.name})


class CardSaveTemplateView(APIView):
    """F594 把卡片保存为模板"""

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        name = (request.data.get("name") or card.title).strip()[:200]
        tpl = CardTemplate.objects.create(
            owner=request.user, name=name, title=card.title, description=card.description,
            priority=card.priority, labels=card.labels, story_points=card.story_points,
            estimated_minutes=card.estimated_minutes,
            # 288：模板一并保存验收清单，套用时回填
            dod_items=[i.content for i in card.acceptance_items.all()][:50],
        )
        return Response(CardTemplateSerializer(tpl).data, status=201)


class CardTemplateListView(APIView):
    """F594 我的卡片模板：列表 / 新建

    288：新建时可带 dod_items（验收清单文本数组），套用时回填到卡片 DoD。
    """

    def get(self, request):
        qs = CardTemplate.objects.filter(owner=request.user)
        return Response({"list": CardTemplateSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "标题不能为空"}, status=400)
        raw_dod = request.data.get("dod_items") or []
        if not isinstance(raw_dod, list):
            return Response({"message": "dod_items 必须是数组"}, status=400)
        tpl = CardTemplate.objects.create(
            owner=request.user, name=(request.data.get("name") or title)[:200], title=title[:200],
            description=request.data.get("description", ""), priority=request.data.get("priority", "medium"),
            labels=request.data.get("labels") or [], story_points=as_int(request.data.get("story_points"), default=0, field="story_points", minimum=0),
            estimated_minutes=as_int(request.data.get("estimated_minutes"), default=0, field="estimated_minutes", minimum=0),
            dod_items=[str(x)[:300] for x in raw_dod][:50],
        )
        return Response(CardTemplateSerializer(tpl).data, status=201)


class CardTemplateApplyView(APIView):
    """F594 用模板在某列创建卡片

    288：支持 title / title_prefix 覆盖标题，回填估时、标签、优先级与 DoD 验收项。
    """

    def post(self, request, pk):
        tpl = CardTemplate.objects.filter(pk=pk, owner=request.user).first()
        if not tpl:
            return Response({"message": "模板不存在"}, status=404)
        board = _board_of(request.user, request.data.get("board_id"))
        if not board:
            return Response({"message": "看板列不存在或无权访问"}, status=404)
        prefix = str(request.data.get("title_prefix") or "").strip()[:50]
        title = (request.data.get("title") or tpl.title)
        if prefix:
            title = f"{prefix}{title}"
        title = str(title).strip()[:200] or tpl.title
        # #60：与复制一致——锁项目行、一次取号后再插入，不再走 TaskCard.save 的加锁分支
        with transaction.atomic():
            project_id = board.project_id
            Project.objects.select_for_update().filter(pk=project_id).first()
            max_order = TaskCard.objects.filter(board=board).aggregate(m=ModelsMax("sort_order"))["m"] or 0
            number = (TaskCard.objects.filter(board__project_id=project_id).aggregate(m=ModelsMax("number"))["m"] or 0) + 1
            card = TaskCard.objects.create(
                board=board, title=title, description=tpl.description,
                priority=tpl.priority, labels=tpl.labels, story_points=tpl.story_points,
                estimated_minutes=tpl.estimated_minutes, sort_order=max_order + 1, number=number,
                created_by=request.user,
            )
            # 288：模板中的验收项一并生成
            for i, content in enumerate(tpl.dod_items or []):
                AcceptanceItem.objects.create(card=card, content=str(content)[:300], sort_order=i)
        _log_activity(board.project, request.user, "从模板创建了任务", card.title)
        return Response(TaskCardSerializer(card).data, status=201)


class CardDodView(APIView):
    """F595 验收清单 DoD：列表 / 新增"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        items = card.acceptance_items.all()
        total = items.count()
        done = items.filter(is_done=True).count()
        return Response({
            "card_id": card.id, "code": card.code,
            "list": AcceptanceItemSerializer(items, many=True).data,
            "total": total, "done": done, "passed": bool(total) and done == total,
            "progress": round(done / total * 100) if total else 0,
            # 285：验收未完成时结单需二次确认（无验收项视为通过）
            "needs_confirm": bool(total) and done < total,
            "force_hint": "结单请带 force=1" if total and done < total else "",
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "验收项不能为空"}, status=400)
        order = (card.acceptance_items.aggregate(m=ModelsMax("sort_order"))["m"] or 0) + 1
        item = AcceptanceItem.objects.create(card=card, content=content[:300], sort_order=order)
        return Response(AcceptanceItemSerializer(item).data, status=201)


class CardDodDetailView(APIView):
    """F595 验收清单 DoD：勾选 / 删除"""

    def _get(self, request, pk, item_id):
        item = AcceptanceItem.objects.filter(pk=item_id, card_id=pk).first()
        if not item:
            return None
        if not _can_access(request.user, item.card.board.project):
            return None
        return item

    def patch(self, request, pk, item_id):
        item = self._get(request, pk, item_id)
        if not item:
            return Response({"message": "验收项不存在"}, status=404)
        if "content" in request.data and (request.data["content"] or "").strip():
            item.content = request.data["content"].strip()[:300]
        if "is_done" in request.data:
            item.is_done = parse_bool(request.data["is_done"], field="is_done")
        item.save()
        return Response(AcceptanceItemSerializer(item).data)

    def delete(self, request, pk, item_id):
        item = self._get(request, pk, item_id)
        if not item:
            return Response({"message": "验收项不存在"}, status=404)
        item.delete()
        return Response({"message": "验收项已删除"})


class CardResolveView(APIView):
    """F596 #编号 互跳：解析文本中的 C-n 引用并返回对应卡片"""

    def post(self, request, project_id):
        import re

        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        text = request.data.get("text") or ""
        nums = [int(n) for n in re.findall(r"C-(\d+)", text, flags=re.IGNORECASE)]
        cards = TaskCard.objects.filter(board__project=project, number__in=nums)
        by_num = {c.number: c for c in cards}
        return Response({
            "numbers": nums,
            "list": [{"number": c.number, "code": c.code, "id": c.id, "title": c.title,
                      "board_id": c.board_id, "status": c.status} for n in nums if (c := by_num.get(n))],
        })


class CardResolveActionView(APIView):
    """300 标记卡片已解决：记录解决说明、结单并写入时间线与项目动态"""

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            return Response({"message": "请填写解决说明"}, status=400)
        card.resolve_reason = reason[:200]
        card.resolved_at = timezone.now()
        card.status = "done"
        card.completed_at = card.completed_at or timezone.now()
        card.save(update_fields=["resolve_reason", "resolved_at", "status", "completed_at"])
        # 时间线聚合 target=card.title 的活动，因此这里写一条即可被 CardTimelineView 读到
        _log_activity(card.board.project, request.user, "标记解决", card.title)
        _push_board_event(card.board.project_id, "card.updated", card_id=card.id, board_id=card.board_id)
        _notify_watchers(card, request.user, f"你关注的任务「{card.title}」已标记解决", reason)
        return Response({"message": "已标记解决", "card_id": card.id, "code": card.code,
                         "reason": card.resolve_reason, "resolved_at": card.resolved_at,
                         "card": TaskCardSerializer(card).data})


class CardWatchView(APIView):
    """295 卡片关注开关：GET 查询 / POST 关注 / DELETE 取消关注"""

    def get(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        watchers = _watcher_users(card)
        return Response({
            "card_id": card.id, "watching": watchers.filter(id=request.user.id).exists(),
            "watcher_count": watchers.count(),
            "watchers": [{"id": u.id, "display_name": u.display_name} for u in watchers[:50]],
        })

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        CardWatcher.objects.get_or_create(card=card, user=request.user)
        return Response({"message": "已关注该卡片", "card_id": card.id, "watching": True,
                         "watcher_count": card.watchers.count()}, status=201)

    def delete(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        card.watchers.filter(user=request.user).delete()
        return Response({"message": "已取消关注", "card_id": card.id, "watching": False,
                         "watcher_count": card.watchers.count()})


class ProjectStandupView(APIView):
    """F597 每日站会三栏：昨天完成 / 今天进行 / 阻塞"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        day_str = request.query_params.get("date")
        try:
            from datetime import datetime as _dt

            target = _dt.strptime(day_str, "%Y-%m-%d").date() if day_str else timezone.localdate()
        except (TypeError, ValueError):
            target = timezone.localdate()
        prev = target - timedelta(days=1)
        cards = list(
            TaskCard.objects.filter(board__project=project)
            .select_related("board")
            .prefetch_related(
                "assignees",
                Prefetch("dependencies", queryset=CardDependency.objects.select_related("blocked_by")),
            )
        )

        def brief(c):
            return {"id": c.id, "code": c.code, "title": c.title, "status": c.status,
                    "board_id": c.board_id, "board_name": c.board.name,
                    "assignee_names": [u.display_name for u in c.assignees.all()]}

        done_yesterday = [brief(c) for c in cards if c.completed_at and c.completed_at.date() == prev]
        doing_today = [brief(c) for c in cards if c.status == "doing"]
        blocked = []
        for c in cards:
            if c.status == "done":
                continue
            has_blocker = any(d.blocked_by.status != "done" for d in c.dependencies.all())
            overdue = bool(c.due_date and c.due_date < target)
            if has_blocker or overdue:
                item = brief(c)
                item["reason"] = "被依赖阻塞" if has_blocker else "已逾期"
                blocked.append(item)
        # 298：按成员汇总昨日完成 / 今日计划 / 阻塞，前端可直接逐人渲染并复制文本
        blocked_ids = {item["id"] for item in blocked}
        per_member = {
            u.id: {"user_id": u.id, "display_name": u.display_name,
                   "done_yesterday": [], "today_plan": [], "blocked": []}
            for u in project.members.all()
        }
        for c in cards:
            item = brief(c)
            for u in c.assignees.all():
                slot = per_member.setdefault(
                    u.id, {"user_id": u.id, "display_name": u.display_name,
                           "done_yesterday": [], "today_plan": [], "blocked": []}
                )
                if c.completed_at and c.completed_at.date() == prev:
                    slot["done_yesterday"].append(item)
                if c.status == "doing":
                    slot["today_plan"].append(item)
                if c.id in blocked_ids:
                    slot["blocked"].append(item)
        return Response({
            "date": str(target),
            "done_yesterday": done_yesterday,
            "doing_today": doing_today,
            "today_plan": doing_today,
            "blocked": blocked,
            "per_member": list(per_member.values()),
            "summary": {"done": len(done_yesterday), "doing": len(doing_today), "blocked": len(blocked)},
        })


class CardArchiveView(APIView):
    """F598 卡片归档 / 取消归档"""

    def post(self, request, pk):
        card = _card_of(request.user, pk)
        if not card:
            return Response({"message": "任务不存在"}, status=404)
        if "is_archived" in request.data:
            card.is_archived = parse_bool(request.data["is_archived"], field="is_archived")
        else:
            card.is_archived = not card.is_archived
        card.save(update_fields=["is_archived"])
        _log_activity(card.board.project, request.user,
                      "归档了任务" if card.is_archived else "取消归档任务", card.title)
        return Response({"message": "已归档" if card.is_archived else "已取消归档",
                         "card_id": card.id, "is_archived": card.is_archived})


class ProjectArchivedCardsView(APIView):
    """F598 已归档卡片列表

    296：支持关键词筛选（q，匹配标题/描述）与分页；POST action=restore 恢复、
    action=delete 彻底删除（彻底删除仅项目创建者可执行）。
    """

    ACTIONS = {"restore", "delete"}

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        qs = TaskCard.objects.filter(board__project=project, is_archived=True)
        kw = (request.query_params.get("q") or "").strip()
        if kw:
            qs = qs.filter(Q(title__icontains=kw) | Q(description__icontains=kw))
        try:
            size = as_int(request.query_params.get("page_size") or request.query_params.get("size"),
                          default=50, field="page_size", minimum=1, maximum=200)
            page_no = as_int(request.query_params.get("page"), default=1, field="page", minimum=1)
        except ValidationError:
            return Response({"message": "page_size 必须是 1-200 的整数，page 必须是正整数"}, status=400)
        total = qs.count()
        start = (page_no - 1) * size
        rows = list(
            qs.select_related("board")
            .prefetch_related(
                "assignees", "comments", "subtasks", "acceptance_items", "worklogs",
                Prefetch("dependencies", queryset=CardDependency.objects.select_related("blocked_by")),
            )
            .order_by("-updated_at", "-id")[start:start + size]
        )
        return Response({
            "list": TaskCardSerializer(rows, many=True).data, "total": total,
            "page": page_no, "page_size": size, "has_more": start + size < total,
        })

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        action = request.data.get("action")
        if action not in self.ACTIONS:
            return Response({"message": "action 只能是 restore / delete"}, status=400)
        raw_ids = request.data.get("card_ids")
        if raw_ids is None:
            raw_ids = [request.data.get("card_id")] if request.data.get("card_id") else []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "card_ids 必须是数组"}, status=400)
        try:
            ids = [as_int(x, field="card_ids", minimum=1) for x in raw_ids]
        except ValidationError:
            return Response({"message": "card_ids 必须全部为整数"}, status=400)
        if not ids:
            return Response({"message": "请选择卡片"}, status=400)
        if len(ids) > 200:
            return Response({"message": "单次最多处理 200 张卡片"}, status=400)
        qs = TaskCard.objects.filter(id__in=ids, board__project=project, is_archived=True)
        if action == "restore":
            n = qs.update(is_archived=False)
            _log_activity(project, request.user, "恢复了归档任务", f"{n} 个卡片")
            return Response({"message": f"已恢复 {n} 张卡片", "restored": n})
        if project.owner_id != request.user.id:
            return Response({"message": "仅项目创建者可彻底删除"}, status=403)
        titles = list(qs.values_list("title", flat=True)[:5])
        n = qs.delete()[0]
        _log_activity(project, request.user, "彻底删除了归档任务", "、".join(titles))
        return Response({"message": f"已彻底删除 {n} 张卡片", "deleted": n})


# ============ F23 迭代（Sprint）管理 ============

def _sprint_payload(s):
    return {
        "id": s.id, "project_id": s.project_id, "name": s.name,
        "start_at": s.start_at, "end_at": s.end_at, "status": s.status,
        "stats": {
            "total": s.cards.filter(is_archived=False).count(),
            "done": s.cards.filter(is_archived=False, status="done").count(),
            "points": s.cards.filter(is_archived=False).aggregate(n=ModelsSum("story_points"))["n"] or 0,
        },
    }


class ProjectSprintView(APIView):
    """GET 迭代列表 / POST 新建迭代"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        rows = [_sprint_payload(s) for s in project.sprints.all()]
        return Response({"list": rows, "total": len(rows)})

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or project.owner_id != request.user.id:
            return Response({"message": "项目不存在或无权操作"}, status=404)
        name = str(request.data.get("name") or "").strip()[:120]
        if not name:
            return Response({"message": "迭代名称不能为空"}, status=400)
        # #62：start_at / end_at 必须解析成 aware datetime，且区间合法（end > start）
        raw_start, raw_end = request.data.get("start_at"), request.data.get("end_at")
        try:
            start_at = as_datetime(raw_start, field="start_at") if raw_start else None
            end_at = as_datetime(raw_end, field="end_at") if raw_end else None
        except ValidationError as exc:
            detail = exc.detail
            msg = detail[0] if isinstance(detail, (list, tuple)) and detail else "时间格式不正确"
            return Response({"message": str(msg)}, status=400)
        if start_at and end_at and end_at <= start_at:
            return Response({"message": "结束时间必须晚于开始时间"}, status=400)
        sprint = Sprint.objects.create(
            project=project,
            name=name,
            start_at=start_at,
            end_at=end_at,
        )
        _log_activity(project, request.user, "create", f"迭代 {name}")
        return Response(_sprint_payload(sprint), status=201)


class SprintActionView(APIView):
    """POST start / close。close 时未完成卡片自动回到待办池

    286：start 支持 daily_hours（默认 6）与 confirm；卡片估时超过
    「成员数 × 每日工时」时返回 409 {warning, estimated_minutes, capacity_minutes}，
    带 confirm=1 再提交即开始，响应附 capacity 明细。
    """

    def post(self, request, project_id, sid, action):
        project = Project.objects.filter(pk=project_id).first()
        if not project or project.owner_id != request.user.id:
            return Response({"message": "项目不存在或无权操作"}, status=404)
        sprint = Sprint.objects.filter(pk=sid, project=project).first()
        if not sprint:
            return Response({"message": "迭代不存在"}, status=404)

        if action == "start":
            if sprint.status == "closed":
                return Response({"message": "已结束的迭代不能重新开始"}, status=400)
            if project.sprints.filter(status="active").exclude(pk=sprint.pk).exists():
                return Response({"message": "已有进行中的迭代，请先结束"}, status=400)
            # 286：开启前校验冲刺容量（卡片估时 vs 成员数 × 每日工时），超容量要求 confirm=1
            raw_hours = request.data.get("daily_hours", request.query_params.get("daily_hours"))
            try:
                daily_hours = as_int(raw_hours, default=6, field="daily_hours", minimum=1, maximum=24)
            except ValidationError:
                return Response({"message": "daily_hours 必须是 1-24 的整数"}, status=400)
            try:
                confirm = parse_bool(request.data.get("confirm"), default=False, field="confirm")
            except ValidationError:
                return Response({"message": "confirm 必须是布尔值"}, status=400)
            estimated = sprint.cards.filter(is_archived=False).aggregate(
                s=ModelsSum("estimated_minutes"))["s"] or 0
            members = max(project.members.count(), 1)
            capacity = members * daily_hours * 60
            capacity_info = {
                "estimated_minutes": estimated, "capacity_minutes": capacity,
                "members": members, "daily_hours": daily_hours,
            }
            if estimated > capacity and not confirm:
                return Response({
                    "message": (f"冲刺内估时 {estimated} 分钟超过容量 {capacity} 分钟"
                                f"（{members} 人 × {daily_hours} 小时/天），确认开始请带 confirm=1"),
                    "warning": True, "over_by": estimated - capacity, **capacity_info,
                }, status=409)
            sprint.status = "active"
            sprint.start_at = sprint.start_at or timezone.now()
            sprint.save(update_fields=["status", "start_at"])
            _log_activity(project, request.user, "move", f"开始迭代 {sprint.name}")
            payload = _sprint_payload(sprint)
            payload["capacity"] = {**capacity_info, "over": estimated > capacity}
            return Response(payload)

        if action == "close":
            if sprint.status == "closed":
                return Response(_sprint_payload(sprint))
            with transaction.atomic():
                carried = sprint.cards.filter(is_archived=False).exclude(status="done").update(sprint=None)
                sprint.status = "closed"
                sprint.end_at = sprint.end_at or timezone.now()
                sprint.save(update_fields=["status", "end_at"])
            _log_activity(project, request.user, "move", f"结束迭代 {sprint.name}（结转 {carried} 张）")
            payload = _sprint_payload(sprint)
            payload["carried_over"] = carried
            return Response(payload)

        return Response({"message": "action 只能是 start / close"}, status=400)


# ============ F22 工时预估偏差 ============

class ProjectEffortReportView(APIView):
    """预估 vs 实际工时偏差；未填预估的卡片不计入偏差统计"""

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if not project or not _can_access(request.user, project):
            return Response({"message": "项目不存在或无权访问"}, status=404)
        cards = (
            TaskCard.objects.filter(board__project=project, is_archived=False)
            .values("id", "title", "estimated_minutes", "story_points", "status")
        )
        spent_rows = (
            WorkLog.objects.filter(card__board__project=project)
            .values("card_id").annotate(total=ModelsSum("minutes"))
        )
        spent_map = {r["card_id"]: r["total"] or 0 for r in spent_rows}

        rows, est_total, spent_total = [], 0, 0
        for c in cards:
            estimate = c["estimated_minutes"] or 0
            spent = spent_map.get(c["id"], 0)
            est_total += estimate
            spent_total += spent
            if estimate <= 0:
                continue
            rows.append({
                "id": c["id"], "title": c["title"], "status": c["status"],
                "estimate": estimate, "spent": spent,
                "variance": spent - estimate,
                "variance_pct": round((spent - estimate) / estimate * 100, 1),
            })
        rows.sort(key=lambda r: -abs(r["variance"]))
        return Response({
            "project_id": project.id,
            "estimate_total": est_total, "spent_total": spent_total,
            "variance_total": spent_total - est_total,
            "overall_pct": round((spent_total - est_total) / est_total * 100, 1) if est_total else 0,
            "counted": len(rows),
            "top": rows[:20],
        })
