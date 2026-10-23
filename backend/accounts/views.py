"""用户认证 / 个人中心 / 角色权限管理 视图"""
import logging

logger = logging.getLogger(__name__)

import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts import totp as totp_lib
from accounts.models import (
    ActiveSession,
    AvatarHistory,
    Badge,
    ContactAlias,
    DeactivateRequest,
    Department,
    InviteCode,
    InviteUse,
    LoginLog,
    NicknameHistory,
    Permission,
    PersonalAccessToken,
    Role,
    RoleAuditLog,
    Tenant,
    TwoFactorSecret,
    UserBadge,
    UserFollow,
    UserPreference,
)
from accounts.serializers import (
    ActiveSessionSerializer,
    AdminResetPasswordSerializer,
    AssignRoleSerializer,
    BadgeSerializer,
    ChangePasswordSerializer,
    ChangeUsernameSerializer,
    DepartmentSerializer,
    InviteCodeSerializer,
    LoginLogSerializer,
    MyTokenObtainPairSerializer,
    MyTokenRefreshSerializer,
    PermissionSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    RoleSerializer,
    TenantSerializer,
    UserAdminCreateSerializer,
    UserDirectorySerializer,
    UserSerializer,
)
from core.models import OperationLog
from core.pagination import StandardPagination
from core.scoping import describe_scope
from core.utils import get_client_ip
from core.validators import as_int, parse_bool

User = get_user_model()

# ---------------------------------------------------------------------------
# F626 登录失败保护：同账号连续 N 次失败 → 锁定 M 分钟（并写入登录历史）
# ---------------------------------------------------------------------------
LOGIN_LOCK_THRESHOLD = 5
LOGIN_LOCK_MINUTES = 10
# F614 注销冷静期（天）
DEACTIVATE_COOLDOWN_DAYS = DeactivateRequest.COOLDOWN_DAYS


def parse_device(ua: str) -> str:
    ua = ua or ""
    # 浏览器
    browser = "未知浏览器"
    for b, pat in [("Chrome", "Chrome"), ("Firefox", "Firefox"), ("Safari", "Safari"),
                   ("Edge", "Edg"), ("Opera", "OPR")]:
        if pat in ua:
            browser = b
            break
    # 操作系统
    if "Mobile" in ua or "Android" in ua or "iPhone" in ua:
        os_name = "移动端"
    elif "Windows" in ua:
        os_name = "Windows"
    elif "Macintosh" in ua or "Mac OS" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "未知设备"
    return f"{os_name} / {browser}"


def record_login(request, user, success=True, username=""):
    LoginLog.objects.create(
        user=user if success else None,
        username=username or (user.username if user else ""),
        ip=get_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:300],
        device=parse_device(request.META.get("HTTP_USER_AGENT", "")),
        is_success=success,
    )


# ---------------- F626 登录失败锁定 ----------------

def login_lock_state(username: str):
    """同账号自最近一次成功登录起连续失败 ≥5 次 → 锁定 10 分钟。

    返回剩余锁定秒数（int）表示仍在锁定期，返回 None 表示未锁定。
    锁定期内的拦截请求不再写失败记录，避免「越锁越久」。
    """
    if not username:
        return None
    now = timezone.now()
    try:
        last_ok = (
            LoginLog.objects.filter(username=username, is_success=True, created_at__lte=now)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        qs = LoginLog.objects.filter(username=username, is_success=False, created_at__lte=now)
        if last_ok:
            qs = qs.filter(created_at__gt=last_ok)
        if qs.count() < LOGIN_LOCK_THRESHOLD:
            return None
        latest = qs.order_by("-created_at").values_list("created_at", flat=True).first()
        if latest is None:
            return None
        until = latest + timezone.timedelta(minutes=LOGIN_LOCK_MINUTES)
        if now < until:
            return max(1, int((until - now).total_seconds()))
    except Exception:
        return None
    return None


# ---------------- F614 注销冷静期：执行到期申请 ----------------

def process_due_deactivations() -> int:
    """执行已到冷静期的注销申请（幂等；任何异常都不影响主流程）"""
    done = 0
    try:
        now = timezone.now()
        due = DeactivateRequest.objects.filter(status="pending", execute_at__lte=now).select_related("user")
        for req in list(due):
            user = req.user
            user.is_active = False
            user.is_disabled = True
            user.save(update_fields=["is_active", "is_disabled"])
            req.status = "done"
            req.processed_at = now
            req.save(update_fields=["status", "processed_at"])
            OperationLog.objects.create(
                user=user, module="accounts", action="delete",
                target="注销申请到期执行", detail=f"冷静期 {DEACTIVATE_COOLDOWN_DAYS} 天已过",
            )
            done += 1
    except Exception:
        return done
    return done


# ---------------- F615 TOTP ----------------

def _totp_state(user):
    """返回 (是否启用, 密钥, otpauth 链接)；未设置时按需生成"""
    obj = TwoFactorSecret.objects.filter(user=user).first()
    if obj is None:
        return False, "", ""
    return obj.enabled, obj.secret, totp_lib.otpauth_url(obj.secret, user.username)


class LoginView(TokenObtainPairView):
    """登录：连续失败锁定（F626）+ TOTP 双因素（F615）+ 到期注销执行（F614）"""

    # B12：签发时写入 tv claim（token_version），认证端据此判定失效
    serializer_class = MyTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        username = (request.data.get("username", "") or "").strip()
        # F614：登录入口顺带执行到期的注销冷静期
        process_due_deactivations()

        # F626：连续 5 次失败锁定 10 分钟
        locked_seconds = login_lock_state(username)
        if locked_seconds:
            minutes = max(1, (locked_seconds + 59) // 60)
            return Response(
                {
                    "code": 1016,
                    "message": f"连续 {LOGIN_LOCK_THRESHOLD} 次登录失败，账号已锁定，请 {minutes} 分钟后再试",
                    "locked_seconds": locked_seconds,
                    "detail": {},
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # F615：已开启两步验证的账号必须携带有效的 TOTP 验证码
        code = str(request.data.get("totp_code") or request.data.get("code") or "").strip()
        user = User.objects.filter(username=username).first()
        if user is not None:
            totp_row = TwoFactorSecret.objects.filter(user=user).first()
            if (
                totp_row is not None
                and totp_row.enabled
                and user.check_password(str(request.data.get("password", "") or ""))
            ):
                if not code:
                    return Response(
                        {"twofa_required": True, "code": 1017,
                         "message": "该账号已开启两步验证，请输入 6 位验证码", "detail": {}},
                        status=status.HTTP_200_OK,
                    )
                if not totp_lib.verify(totp_row.secret, code):
                    record_login(request, None, False, username)
                    return Response(
                        {"code": 1018, "message": "两步验证码错误或已过期", "detail": {}},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
                TwoFactorSecret.objects.filter(pk=totp_row.pk).update(last_used_at=timezone.now())

        try:
            resp = super().post(request, *args, **kwargs)
        except APIException as exc:
            # 密码错误 / 账号禁用 / 限流……统一记录一次失败（F626「并记录」）
            record_login(request, None, False, username)
            return self.handle_exception(exc)
        except ValueError as exc:
            return Response({"code": 400, "message": str(exc), "detail": {}}, status=400)
        except Exception as exc:  # noqa: BLE001 —— 结构化降级，绝不 500
            record_login(request, None, False, username)
            try:
                from core.platform import record_exception

                record_exception(exc, request.path)
            except Exception:
                logger.exception("B23：静默兜底已登记（accounts/views.py:246 原为 pass）——review 是否应收窄异常类型")
            return Response(
                {"code": 422, "message": f"{type(exc).__name__}: {exc}", "detail": {}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if resp.status_code == 200:
            user = User.objects.filter(username=username).first()
            if user:
                record_login(request, user, True, username)
                # #56 记录活跃会话
                try:
                    jti = resp.data.get("access", "").split(".")
                    # 从 access token 解 jti
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = AccessToken(resp.data["access"])
                    ActiveSession.objects.create(
                        user=user,
                        jti=str(token["jti"]),
                        ip=get_client_ip(request),
                        device=parse_device(request.META.get("HTTP_USER_AGENT", "")),
                        user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:300],
                    )
                except Exception:
                    logger.exception("B23：静默兜底已登记（accounts/views.py:270 原为 pass）——review 是否应收窄异常类型")
                resp.data["user"] = UserSerializer(user).data
        return resp


class RefreshView(TokenRefreshView):
    """B12：refresh 时校验 tv claim，改密前的旧 refresh 一律拒绝（401），
    前端按 401 流程引导重新登录"""

    serializer_class = MyTokenRefreshSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        invite_code = (request.data.get("invite_code") or "").strip()
        invite = None
        # 如果站点设置了 register_invite_required，则必须提供有效邀请码
        from core.models import SiteSetting
        require_invite = SiteSetting.objects.filter(key="register_invite_required", value="1").exists()
        if invite_code:
            invite = InviteCode.objects.filter(code=invite_code).first()
            if not invite or not invite.is_valid:
                return Response({"message": "邀请码无效或已过期", "code": 1007}, status=status.HTTP_400_BAD_REQUEST)
        elif require_invite:
            return Response({"message": "本站点需要邀请码才能注册", "code": 1008}, status=status.HTTP_400_BAD_REQUEST)

        # B5：用户 + 邀请码绑定 + 邀请记录 + 操作日志 + 登录日志多表写，
        # 任一步失败整体回滚，避免「用户建了但邀请码没用上」的中间态
        with transaction.atomic():
            ser = RegisterSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            user = ser.save()
            # 绑定邀请码
            if invite:
                invite.used_by = user
                invite.uses += 1
                invite.save(update_fields=["used_by", "uses"])
                # F625 邀请效果看板：记录本次注册，用于按码聚合「带来注册数」
                try:
                    InviteUse.objects.create(invite=invite, user=user)
                except Exception:
                    logger.exception("B23：静默兜底已登记（accounts/views.py:313 原为 pass）——review 是否应收窄异常类型")
            token = RefreshToken.for_user(user)
            # B12：与登录保持一致，写入 tv claim（认证端校验 token_version）
            token["tv"] = user.token_version
            OperationLog.objects.create(
                user=user, module="accounts", action="create", target="用户注册", detail=user.username,
                ip=get_client_ip(request),
            )
            record_login(request, user, True, user.username)
        return Response(
            {
                "access": str(token.access_token),
                "refresh": str(token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LogoutView(APIView):
    """登出：把 refresh token 加入黑名单"""

    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass
        OperationLog.objects.create(
            user=request.user, module="accounts", action="logout", target="退出登录", ip=get_client_ip(request)
        )
        return Response({"message": "已退出登录"})


class ProfileView(APIView):
    """查看 / 修改个人资料"""

    def get(self, request):
        # F614：个人资料是高频入口，顺带执行到期的注销申请
        process_due_deactivations()
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        old_nickname = request.user.nickname
        ser = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        # F622 昵称变更历史（仅记录真实变化）
        new_nickname = request.user.nickname
        if old_nickname != new_nickname:
            try:
                NicknameHistory.objects.create(
                    user=request.user, old_value=old_nickname or "", new_value=new_nickname or ""
                )
            except Exception:
                logger.exception("B23：静默兜底已登记（accounts/views.py:369 原为 pass）——review 是否应收窄异常类型")
        return Response({"message": "资料已更新", "user": UserSerializer(request.user).data})


class ChangeUsernameView(APIView):
    """修改登录用户名"""

    def post(self, request):
        ser = ChangeUsernameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        old = request.user.username
        request.user.username = ser.validated_data["username"]
        request.user.save(update_fields=["username"])
        OperationLog.objects.create(
            user=request.user, module="accounts", action="update", target="修改用户名", detail=f"{old} → {request.user.username}",
            ip=get_client_ip(request),
        )
        return Response({"message": "用户名已修改", "user": UserSerializer(request.user).data})


class ChangePasswordView(APIView):
    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        # B12：改密后吊销该用户所有已签发 token（tv claim 对不上即失效）
        request.user.token_version += 1
        request.user.save(update_fields=["password", "token_version"])
        return Response({"message": "密码修改成功，请重新登录"})


def snapshot_avatar(user, note: str = ""):
    """F623 把当前头像复制一份存入历史（复制文件副本，避免后续替换/删除破坏历史）"""
    try:
        import os as _os

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        av = user.avatar
        if not av:
            return None
        with av.open("rb") as fh:
            data = fh.read()
        name = _os.path.basename(av.name) or "avatar.png"
        ts = timezone.now().strftime("%Y%m%d%H%M%S%f")
        path = default_storage.save(f"avatars/history/{ts}_{name}", ContentFile(data))
        row = AvatarHistory.objects.create(user=user, image=path, note=(note or "")[:80])
        # 只保留最近 10 张，超出的连同文件一起清理
        keep_ids = list(
            AvatarHistory.objects.filter(user=user).order_by("-created_at")
            .values_list("id", flat=True)[:10]
        )
        stale = AvatarHistory.objects.filter(user=user).exclude(id__in=keep_ids)
        for old in stale:
            try:
                old.image.delete(save=False)
            except Exception:
                logger.exception("B23：静默兜底已登记（accounts/views.py:427 原为 pass）——review 是否应收窄异常类型")
        stale.delete()
        return row
    except Exception:
        return None


class AvatarView(APIView):
    """头像：POST 上传 / DELETE 移除（F623 自动留存历史，可随时切换回旧头像）"""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.FILES.get("avatar")
        if not file:
            return Response({"message": "请选择头像文件"}, status=status.HTTP_400_BAD_REQUEST)
        snapshot_avatar(request.user, note="上传新头像前自动保存")
        request.user.avatar = file
        request.user.save(update_fields=["avatar"])
        return Response({
            "message": "头像已更新",
            "url": request.user.avatar.url if request.user.avatar else "",
            "history_count": AvatarHistory.objects.filter(user=request.user).count(),
        })

    def delete(self, request):
        if request.user.avatar:
            snapshot_avatar(request.user, note="移除头像前自动保存")
            request.user.avatar.delete(save=False)
            request.user.avatar = None
            request.user.save(update_fields=["avatar"])
        return Response({"message": "头像已移除"})


class DeactivateSelfView(APIView):
    """注销当前账号（停用，保留数据）"""

    def post(self, request):
        password = request.data.get("password", "")
        if not request.user.check_password(password):
            return Response({"message": "密码不正确，无法注销"}, status=status.HTTP_400_BAD_REQUEST)
        request.user.is_active = False
        request.user.is_disabled = True
        request.user.save(update_fields=["is_active", "is_disabled"])
        OperationLog.objects.create(user=request.user, module="accounts", action="other", target="注销账号", ip=get_client_ip(request))
        return Response({"message": "账号已注销"})


def _notif_qs(user):
    from core.models import Notification

    return Notification.objects.filter(recipient=user)


def _pref_dict(user) -> dict:
    """F620 时区 / 周起始日偏好（无记录时返回默认值）"""
    row = UserPreference.objects.filter(user=user).first()
    if row is None:
        return {"timezone": "Asia/Shanghai", "week_start": "mon", "updated_at": None}
    return {
        "timezone": row.timezone_name,
        "week_start": row.week_start,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _deactivate_state(user) -> dict:
    """F614 当前注销申请状态（无申请时 status=none）"""
    row = DeactivateRequest.objects.filter(user=user).order_by("-requested_at").first()
    if row is None:
        return {"status": "none", "cooldown_days": DEACTIVATE_COOLDOWN_DAYS}
    from datetime import datetime

    now = datetime.now(row.execute_at.tzinfo)
    left = (row.execute_at - now).total_seconds()
    return {
        "status": row.status,
        "requested_at": row.requested_at.isoformat(),
        "execute_at": row.execute_at.isoformat(),
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "cooldown_days": DEACTIVATE_COOLDOWN_DAYS,
        "seconds_left": int(left) if row.status == "pending" else 0,
        "days_left": int(max(0, left // 86400)) if row.status == "pending" else 0,
    }


class DataExportView(APIView):
    """导出我的全部个人数据（F613 数据 JSON 导出：覆盖账号/内容/社交/安全全量模块）"""

    def get(self, request):
        from files.models import FileMeta
        from notes.models import Note
        from projects.models import TaskCard
        from im.models import ChatSession

        u = request.user

        def _safe(fn, default=None):
            try:
                return fn()
            except Exception:
                return default if default is not None else []

        data = {
            "profile": UserSerializer(u).data,
            "files": list(FileMeta.objects.filter(owner=u).values("id", "name", "size", "kind", "created_at")),
            "notes": list(Note.objects.filter(owner=u).values("id", "title", "content", "created_at", "updated_at")),
            "tasks": list(
                TaskCard.objects.filter(assignees=u).values("id", "title", "status", "priority", "due_date")
            ),
            "sessions": list(ChatSession.objects.filter(members=u).values("id", "name", "type", "created_at")),
            # ---- 以下为 F613 新增的导出模块（只增不改，老字段保持不变） ----
            "login_history": _safe(lambda: list(
                LoginLog.objects.filter(user=u).values(
                    "id", "username", "ip", "device", "is_success", "created_at"
                )[:1000]
            )),
            "notifications": _safe(lambda: list(
                _notif_qs(u).values("id", "category", "level", "title", "content", "is_read", "created_at")[:500]
            )),
            "badges": _safe(lambda: list(
                UserBadge.objects.filter(user=u).values("badge__key", "badge__name", "awarded_at")
            )),
            "invite_codes": _safe(lambda: list(
                InviteCode.objects.filter(owner=u).values("code", "max_uses", "uses", "expires_at", "created_at")
            )),
            "invite_registrations": _safe(lambda: list(
                InviteUse.objects.filter(invite__owner=u).values(
                    "invite__code", "user__username", "created_at"
                )[:500]
            )),
            "follows": _safe(lambda: {
                "following": list(UserFollow.objects.filter(follower=u).values_list("following__username", flat=True)),
                "followers": list(UserFollow.objects.filter(following=u).values_list("follower__username", flat=True)),
            }),
            "contact_aliases": _safe(lambda: list(
                ContactAlias.objects.filter(owner=u).values("contact__username", "alias", "updated_at")
            )),
            "nickname_history": _safe(lambda: list(
                NicknameHistory.objects.filter(user=u).values("old_value", "new_value", "changed_at")[:200]
            )),
            "avatar_history": _safe(lambda: [
                {"image": (h.image.url if h.image else ""), "note": h.note, "created_at": h.created_at}
                for h in AvatarHistory.objects.filter(user=u)[:50]
            ]),
            "preferences": _safe(lambda: _pref_dict(u)),
            "deactivate_request": _safe(lambda: _deactivate_state(u)),
            "personal_tokens": _safe(lambda: [
                {"name": t.name, "prefix": t.prefix, "created_at": t.created_at,
                 "expires_at": t.expires_at, "revoked_at": t.revoked_at, "last_used_at": t.last_used_at}
                for t in PersonalAccessToken.objects.filter(user=u)
            ]),
            "exported_at": timezone.now().isoformat(),
            "export_version": 2,
        }
        data["summary"] = {
            "files": len(data["files"]), "notes": len(data["notes"]), "tasks": len(data["tasks"]),
            "sessions": len(data["sessions"]), "login_history": len(data["login_history"]),
            "notifications": len(data["notifications"]), "follows": len(data["follows"]["following"]),
        }
        return Response(data)


class HeartbeatView(APIView):
    """前端定时心跳，刷新在线状态"""

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(last_active_at=timezone.now())
        return Response({"ok": True, "server_time": timezone.now().isoformat()})


class UsernameCheckView(APIView):
    """用户名可用性校验（注册/改名实时提示）"""

    permission_classes = [AllowAny]

    def get(self, request):
        username = (request.query_params.get("username") or "").strip()
        if len(username) < 3:
            return Response({"valid": False, "available": False, "message": "至少 3 个字符"})
        exists = User.objects.filter(username=username).exists()
        return Response({"valid": True, "available": not exists, "message": "可用" if not exists else "已被占用"})


class LoginHistoryView(APIView):
    """我的登录历史"""

    def get(self, request):
        qs = LoginLog.objects.filter(user=request.user)
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        # B20：复用 DRF 分页器已算好的 count（paginate_queryset 内部本来就
        # count 过一次），不再单独执行第二条 COUNT SQL
        total = pg.page.paginator.count if pg.page else 0
        return Response({
            "list": LoginLogSerializer(page, many=True).data,
            "total": total,
            "page": pg.page.number if pg.page else 1,
        })


class UserDirectoryView(APIView):
    """全员用户名录（登录可见，用于 @、拉人、发起聊天）"""

    def get(self, request):
        qs = User.objects.filter(is_active=True, is_disabled=False)
        keyword = request.query_params.get("q")
        if keyword:
            qs = qs.filter(Q(username__icontains=keyword) | Q(nickname__icontains=keyword) | Q(email__icontains=keyword))
        qs = qs.order_by("username")[:50]
        return Response({"list": UserDirectorySerializer(qs, many=True).data, "total": qs.count()})


class UserListView(APIView):
    """用户列表（管理员）：支持关键词、状态、角色筛选"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = User.objects.all().distinct()
        keyword = request.query_params.get("keyword")
        status_f = request.query_params.get("status")
        role = request.query_params.get("role")
        if keyword:
            qs = qs.filter(Q(username__icontains=keyword) | Q(nickname__icontains=keyword) | Q(email__icontains=keyword))
        if status_f == "disabled":
            qs = qs.filter(is_disabled=True)
        elif status_f == "active":
            qs = qs.filter(is_disabled=False)
        elif status_f == "admin":
            qs = qs.filter(Q(is_superuser=True) | Q(roles__code="admin"))
        if role:
            qs = qs.filter(roles__code=role)
        # B6：roles m2m（role_names/role_ids 共用）+ department/tenant FK 预取，
        # 避免每用户 5+ 次附加查询
        qs = qs.prefetch_related("roles").select_related("department", "tenant")
        pg = StandardPagination()
        page = pg.paginate_queryset(qs.order_by("-date_joined"), request)
        data = UserSerializer(page, many=True).data
        return Response({"list": data, "total": qs.count(), "page": pg.page.number if pg.page else 1})


class UserDetailView(APIView):
    """用户详情 / 编辑 / 禁用启用（管理员）"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return User.objects.filter(pk=pk).first()

    def get(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response({"message": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response({"message": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        for field in ("nickname", "email", "phone", "bio"):
            if field in request.data:
                setattr(user, field, request.data[field])
        if "storage_quota_mb" in request.data:
            user.storage_quota_mb = as_int(request.data["storage_quota_mb"], field="storage_quota_mb", minimum=0)
        if "is_disabled" in request.data:
            user.is_disabled = parse_bool(request.data["is_disabled"], field="is_disabled")
            user.is_active = not user.is_disabled
        if "department" in request.data:
            dept_id = as_int(request.data["department"], field="department") if request.data["department"] else None
            user.department = Department.objects.filter(pk=dept_id).first() if dept_id else None
        if "tenant" in request.data:
            tenant_id = as_int(request.data["tenant"], field="tenant") if request.data["tenant"] else None
            user.tenant = Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
        user.save()
        role_ids = request.data.get("role_ids")
        if isinstance(role_ids, list):
            before = list(user.roles.values_list("code", flat=True))
            user.roles.set(Role.objects.filter(id__in=role_ids))
            after = list(user.roles.values_list("code", flat=True))
            if before != after:
                record_role_change(
                    request.user, user, "set", before, after, get_client_ip(request), "编辑用户角色"
                )
        return Response({"message": "已更新", "user": UserSerializer(user).data})


class UserCreateView(APIView):
    """管理员创建用户"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        ser = UserAdminCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        # F636 初始角色也进变更历史
        record_role_change(
            request.user, user, "initial", [],
            list(user.roles.values_list("code", flat=True)),
            get_client_ip(request), "创建用户",
        )
        return Response({"message": "用户已创建", "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class AdminResetPasswordView(APIView):
    """管理员重置指定用户密码"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if not user:
            return Response({"message": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        ser = AdminResetPasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user.set_password(ser.validated_data["new_password"])
        # B12：管理员重置密码同样吊销该用户所有旧 token
        user.token_version += 1
        user.save(update_fields=["password", "token_version"])
        return Response({"message": "密码已重置"})


def record_role_change(actor, target, action, roles_from, roles_to, ip=None, detail=""):
    """F636 角色变更历史（任何角色写操作都留痕；失败不影响主流程）"""
    try:
        RoleAuditLog.objects.create(
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            target=target,
            action=action,
            roles_from=list(roles_from or []),
            roles_to=list(roles_to or []),
            detail=(detail or "")[:255],
            ip=ip,
        )
    except Exception:
        logger.exception("B23：静默兜底已登记（accounts/views.py:763 原为 pass）——review 是否应收窄异常类型")


class AdminBatchActionView(APIView):
    """管理员批量操作用户：启用/禁用/删除/分配角色/设置配额
    + F637 扩展：强制下线 / 重置两步验证 / 调整部门 / 重置注销申请
    """

    permission_classes = [IsAdminUser]

    def post(self, request):
        action = request.data.get("action")
        ids = request.data.get("user_ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"message": "未选择用户"}, status=status.HTTP_400_BAD_REQUEST)
        qs = User.objects.filter(id__in=ids)
        if action == "enable":
            qs.update(is_disabled=False, is_active=True)
            msg = f"已启用 {len(ids)} 个用户"
        elif action == "disable":
            qs.update(is_disabled=True, is_active=False)
            msg = f"已禁用 {len(ids)} 个用户"
        elif action == "delete":
            n = qs.exclude(is_superuser=True).delete()[0]
            msg = f"已删除 {n} 个用户"
        elif action == "quota":
            quota = as_int(request.data.get("storage_quota_mb"), default=2048, field="storage_quota_mb", minimum=0)
            n = qs.update(storage_quota_mb=quota)
            msg = f"已为 {n} 个用户设置配额 {quota}MB"
        elif action == "roles":
            role_ids = request.data.get("role_ids") or []
            roles = Role.objects.filter(id__in=role_ids)
            n = 0
            for u in qs:
                before = list(u.roles.values_list("code", flat=True))
                u.roles.set(roles)
                after = list(u.roles.values_list("code", flat=True))
                if before != after:
                    record_role_change(
                        request.user, u, "set", before, after, get_client_ip(request), "批量分配角色"
                    )
                n += 1
            msg = f"已为 {n} 个用户分配角色"
        # ---------- F637 批量操作扩展 ----------
        elif action == "force_logout":
            n_sess = ActiveSession.objects.filter(user__in=qs, is_revoked=False).update(is_revoked=True)
            n_tok = 0
            try:
                from rest_framework_simplejwt.token_blacklist.models import (
                    BlacklistedToken,
                    OutstandingToken,
                )

                for tok in OutstandingToken.objects.filter(user__in=qs):
                    BlacklistedToken.objects.get_or_create(token=tok)
                    n_tok += 1
            except Exception:
                n_tok = 0
            # B12：黑名单只挡 refresh，access 在有效期内仍可用；
            # token_version +1 让所有已签发 access 立即失效（认证端校验 tv claim）
            n_tv = qs.update(token_version=F("token_version") + 1)
            msg = f"已强制 {qs.count()} 个用户下线（会话 {n_sess} 个 / 吊销令牌 {n_tok} 个 / 令牌版本 {n_tv} 个）"
        elif action == "reset_2fa":
            n = TwoFactorSecret.objects.filter(user__in=qs).update(
                enabled=False, confirmed_at=None, last_used_at=None
            )
            msg = f"已重置 {n} 个用户的两步验证（需重新绑定）"
        elif action == "assign_dept":
            dept_id = request.data.get("department")
            dept = Department.objects.filter(pk=dept_id).first() if dept_id else None
            n = qs.update(department=dept)
            msg = f"已将 {n} 个用户调整到「{dept.path_name() if dept else '未分配部门'}」"
        elif action == "clear_deactivate":
            n = DeactivateRequest.objects.filter(
                user__in=qs, status="pending"
            ).update(status="cancelled", cancelled_at=timezone.now())
            qs.update(is_disabled=False, is_active=True)
            msg = f"已撤销 {n} 条注销申请并恢复账号"
        else:
            return Response({"message": "未知操作"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": msg})


class AssignRoleView(APIView):
    """批量分配角色"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        ser = AssignRoleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        users = User.objects.filter(id__in=ser.validated_data["user_ids"])
        roles = Role.objects.filter(id__in=ser.validated_data["role_ids"])
        ip = get_client_ip(request)
        for u in users:
            before = list(u.roles.values_list("code", flat=True))
            u.roles.set(roles)
            after = list(u.roles.values_list("code", flat=True))
            if before != after:
                record_role_change(request.user, u, "assign", before, after, ip, "批量分配角色")
        return Response({"message": f"已为 {users.count()} 个用户分配角色"})


class RoleListView(APIView):
    """角色列表 / 创建"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Role.objects.all()
        return Response({"list": RoleSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not name or not code:
            return Response({"message": "角色名与编码不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        if Role.objects.filter(code=code).exists():
            return Response({"message": "角色编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.create(
            name=name, code=code, description=request.data.get("description", ""),
            data_scope=request.data.get("data_scope") or "self",
        )
        tenant_id = request.data.get("tenant")
        if tenant_id:
            role.tenant = Tenant.objects.filter(pk=tenant_id).first()
            role.save(update_fields=["tenant"])
        perm_ids = request.data.get("permission_ids") or []
        if perm_ids:
            role.permissions.set(Permission.objects.filter(id__in=perm_ids))
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    """角色详情 / 更新 / 删除"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return Role.objects.filter(pk=pk).first()

    def get(self, request, pk):
        role = self.get_object(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RoleSerializer(role).data)

    def patch(self, request, pk):
        role = self.get_object(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data:
            role.name = request.data["name"]
        if "description" in request.data:
            role.description = request.data["description"]
        if "data_scope" in request.data:
            role.data_scope = request.data["data_scope"] or "self"
        if "tenant" in request.data:
            tenant_id = request.data.get("tenant")
            role.tenant = Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
        role.save()
        permission_ids = request.data.get("permission_ids")
        if isinstance(permission_ids, list):
            role.permissions.set(Permission.objects.filter(id__in=permission_ids))
        return Response(RoleSerializer(role).data)

    def delete(self, request, pk):
        role = self.get_object(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if role.is_builtin:
            return Response({"message": "内置角色不可删除"}, status=status.HTTP_400_BAD_REQUEST)
        role.delete()
        return Response({"message": "角色已删除"})


class PermissionListView(APIView):
    """权限点列表：支持按模块分组返回"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Permission.objects.all().order_by("module", "id")
        if request.query_params.get("grouped") == "1":
            grouped = {}
            for p in PermissionSerializer(qs, many=True).data:
                grouped.setdefault(p["module"], []).append(p)
            return Response({"list": PermissionSerializer(qs, many=True).data, "grouped": grouped, "total": qs.count()})
        return Response({"list": PermissionSerializer(qs, many=True).data, "total": qs.count()})


class MyPermissionView(APIView):
    """当前用户拥有的权限编码 + 角色（前端做按钮级权限）"""

    def get(self, request):
        user = request.user
        codes = list(user.roles.values_list("permissions__code", flat=True))
        if user.is_superuser:
            codes = list(Permission.objects.values_list("code", flat=True))
        return Response(
            {
                "is_admin": user.is_admin_role(),
                "roles": list(user.roles.values_list("code", flat=True)),
                "permissions": sorted(set(c for c in codes if c)),
            }
        )


class OnlineUsersView(APIView):
    """最近活跃用户（模拟在线状态）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        minutes = as_int(request.query_params.get("minutes"), default=15, field="minutes", minimum=1, maximum=43200)
        qs = User.objects.filter(last_active_at__gte=timezone.now() - timezone.timedelta(minutes=minutes))
        return Response({"list": UserSerializer(qs, many=True).data, "count": qs.count()})


# ---------------- #49 用户徽章 ----------------

def _compute_badges(user):
    """基于用户行为数据惰性计算应获得的徽章"""
    from files.models import FileMeta
    from notes.models import Note
    from projects.models import TaskCard

    rules = {
        "newcomer": lambda u: True,  # 注册即得
        "active_7d": lambda u: u.login_logs.filter(is_success=True, created_at__gte=timezone.now() - timezone.timedelta(days=7)).count() >= 5,
        "creator": lambda u: Note.objects.filter(owner=u).count() >= 10,
        "collector": lambda u: FileMeta.objects.filter(owner=u, is_star=True).count() >= 5,
        "social": lambda u: u.roles.count() >= 2 or u.leading_departments.exists(),
        "publisher": lambda u: FileMeta.objects.filter(owner=u, is_deleted=False).count() >= 20,
        "writer": lambda u: Note.objects.filter(owner=u).count() >= 50,
        "team_player": lambda u: TaskCard.objects.filter(assignees=u).count() >= 10,
    }
    defaults = {
        "newcomer": ("初来乍到", "🌱", "bronze", "完成注册"),
        "active_7d": ("一周活跃", "🔥", "bronze", "7天内登录5次以上"),
        "creator": ("笔记创作者", "📝", "silver", "创建10篇笔记"),
        "collector": ("收藏达人", "⭐", "bronze", "收藏5个文件"),
        "social": ("社交达人", "🤝", "silver", "加入多个角色或管理部门"),
        "publisher": ("文件达人", "📁", "silver", "上传20个文件"),
        "writer": ("笔耕不辍", "✍️", "gold", "创建50篇笔记"),
        "team_player": ("团队核心", "👥", "gold", "参与10个任务"),
    }
    awarded = set(UserBadge.objects.filter(user=user).values_list("badge__key", flat=True))
    for key, rule_fn in rules.items():
        if key in awarded:
            continue
        try:
            if rule_fn(user):
                name, icon, level, desc = defaults[key]
                badge, _ = Badge.objects.get_or_create(
                    key=key, defaults={"name": name, "icon": icon, "level": level, "rule": desc}
                )
                UserBadge.objects.get_or_create(user=user, badge=badge)
        except Exception:
            logger.exception("B23：静默兜底已登记（accounts/views.py:1022 原为 pass）——review 是否应收窄异常类型")


class MyBadgesView(APIView):
    """我的徽章列表（自动计算并返回）"""

    def get(self, request):
        _compute_badges(request.user)
        awarded = UserBadge.objects.filter(user=request.user).select_related("badge")
        all_badges = Badge.objects.all()
        awarded_keys = set(awarded.values_list("badge__key", flat=True))
        list_data = []
        for b in all_badges:
            ub = awarded.filter(badge=b).first()
            list_data.append({
                "id": b.id, "key": b.key, "name": b.name, "icon": b.icon,
                "level": b.level, "rule": b.rule, "description": b.description,
                "earned": b.key in awarded_keys,
                "earned_at": ub.awarded_at if ub else None,
            })
        return Response({"list": list_data, "earned_count": len(awarded_keys)})


# ---------------- #52 邀请码 ----------------

class MyInviteCodesView(APIView):
    """我的邀请码列表 / 生成新邀请码"""

    def get(self, request):
        qs = InviteCode.objects.filter(owner=request.user)
        return Response({"list": InviteCodeSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        max_uses = as_int(request.data.get("max_uses"), default=1, field="max_uses", minimum=0)
        expires_days = as_int(request.data.get("expires_days"), default=30, field="expires_days", minimum=0)
        code = InviteCode.generate(request.user, max_uses=max_uses, expires_days=expires_days)
        return Response(InviteCodeSerializer(code).data, status=status.HTTP_201_CREATED)


# ---------------- #56 登录设备 / 会话管理 ----------------

class MySessionsView(APIView):
    """我的活跃会话列表"""

    def get(self, request):
        qs = ActiveSession.objects.filter(user=request.user, is_revoked=False).order_by("-last_seen")
        return Response({"list": ActiveSessionSerializer(qs, many=True).data, "total": qs.count()})


class SessionRevokeView(APIView):
    """吊销指定会话（踢下线）"""

    def post(self, request, pk):
        sess = ActiveSession.objects.filter(pk=pk, user=request.user).first()
        if not sess:
            return Response({"message": "会话不存在"}, status=404)
        sess.is_revoked = True
        sess.save(update_fields=["is_revoked"])
        # 将 jti 加入 simplejwt 黑名单
        try:
            from rest_framework_simplejwt.tokens import BlacklistMixin
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            OutstandingToken.objects.get_or_create(jti=sess.jti)
        except Exception:
            logger.exception("B23：静默兜底已登记（accounts/views.py:1086 原为 pass）——review 是否应收窄异常类型")
        return Response({"message": "已踢出该设备"})


# ---------------- 数据范围（行级数据权限） ----------------

class MyScopeView(APIView):
    """当前用户生效的数据范围说明（前端提示可见范围）"""

    def get(self, request):
        return Response(describe_scope(request.user))


# ---------------- 组织架构：部门 ----------------

def _dept_tree(parent=None, tenant_id=None):
    """递归构建部门树"""
    qs = Department.objects.filter(parent=parent)
    if tenant_id:
        qs = qs.filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True))
    out = []
    for d in qs.order_by("sort", "id"):
        node = DepartmentSerializer(d).data
        node["children"] = _dept_tree(d, tenant_id)
        out.append(node)
    return out


class DepartmentListView(APIView):
    """部门列表（树）/ 新建部门"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        tenant = request.query_params.get("tenant")
        tenant_id = as_int(tenant, field="tenant") if tenant else None
        flat = request.query_params.get("flat") == "1"
        if flat:
            qs = Department.objects.all().order_by("sort", "id")
            if tenant_id:
                qs = qs.filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True))
            return Response({"list": DepartmentSerializer(qs, many=True).data, "total": qs.count()})
        tree = _dept_tree(None, tenant_id)
        return Response({"tree": tree, "total": Department.objects.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "部门名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        parent_id = as_int(request.data.get("parent"), field="parent") if request.data.get("parent") else None
        tenant_fk = as_int(request.data.get("tenant"), field="tenant") if request.data.get("tenant") else None
        leader_id = as_int(request.data.get("leader"), field="leader") if request.data.get("leader") else None
        dept = Department.objects.create(
            name=name[:100],
            code=(request.data.get("code") or "")[:50],
            parent=Department.objects.filter(pk=parent_id).first() if parent_id else None,
            tenant=Tenant.objects.filter(pk=tenant_fk).first() if tenant_fk else None,
            leader=User.objects.filter(pk=leader_id).first() if leader_id else None,
            sort=as_int(request.data.get("sort"), default=0, field="sort"),
        )
        return Response(DepartmentSerializer(dept).data, status=status.HTTP_201_CREATED)


class DepartmentDetailView(APIView):
    """部门详情 / 编辑 / 删除"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return Department.objects.filter(pk=pk).first()

    def get(self, request, pk):
        dept = self.get_object(pk)
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        data = DepartmentSerializer(dept).data
        data["descendant_ids"] = dept.descendant_ids()
        data["members"] = UserSerializer(dept.members.all()[:50], many=True).data
        return Response(data)

    def patch(self, request, pk):
        dept = self.get_object(pk)
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data and request.data["name"].strip():
            dept.name = request.data["name"].strip()[:100]
        if "code" in request.data:
            dept.code = (request.data["code"] or "")[:50]
        if "sort" in request.data:
            dept.sort = as_int(request.data["sort"], default=0, field="sort")
        if "is_active" in request.data:
            dept.is_active = parse_bool(request.data["is_active"], field="is_active")
        if "leader" in request.data:
            lid = as_int(request.data.get("leader"), field="leader") if request.data.get("leader") else None
            dept.leader = User.objects.filter(pk=lid).first() if lid else None
        if "parent" in request.data:
            pid = as_int(request.data.get("parent"), field="parent") if request.data.get("parent") else None
            # 防止把上级设为自己或自己的后代，造成环
            if pid and pid in (dept.descendant_ids(include_self=True)):
                return Response({"message": "不能将部门移动到自身或其下级"}, status=400)
            dept.parent = Department.objects.filter(pk=pid).first() if pid else None
        dept.save()
        return Response(DepartmentSerializer(dept).data)

    def delete(self, request, pk):
        dept = self.get_object(pk)
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        if dept.members.exists():
            return Response({"message": "该部门下仍有成员，请先转移成员"}, status=status.HTTP_400_BAD_REQUEST)
        if dept.children.exists():
            return Response({"message": "该部门下仍有子部门，请先处理子部门"}, status=status.HTTP_400_BAD_REQUEST)
        dept.delete()
        return Response({"message": "部门已删除"})


# ---------------- 多租户 ----------------

class TenantListView(APIView):
    """租户列表 / 新建租户"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Tenant.objects.all().order_by("id")
        return Response({"list": TenantSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not name or not code:
            return Response({"message": "租户名与编码不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        if Tenant.objects.filter(code=code).exists():
            return Response({"message": "租户编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        tenant = Tenant.objects.create(
            name=name[:100], code=code[:50], remark=(request.data.get("remark") or "")[:255]
        )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


class TenantDetailView(APIView):
    """租户详情 / 编辑 / 删除"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return Tenant.objects.filter(pk=pk).first()

    def get(self, request, pk):
        tenant = self.get_object(pk)
        if not tenant:
            return Response({"message": "租户不存在"}, status=status.HTTP_404_NOT_FOUND)
        data = TenantSerializer(tenant).data
        data["departments"] = DepartmentSerializer(tenant.departments.all(), many=True).data
        data["user_count"] = tenant.users.count()
        return Response(data)

    def patch(self, request, pk):
        tenant = self.get_object(pk)
        if not tenant:
            return Response({"message": "租户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data:
            tenant.name = request.data["name"]
        if "remark" in request.data:
            tenant.remark = request.data["remark"]
        if "expire_at" in request.data:
            tenant.expire_at = request.data["expire_at"] or None
        if "is_active" in request.data:
            tenant.is_active = parse_bool(request.data["is_active"], field="is_active")
        tenant.save()
        return Response(TenantSerializer(tenant).data)

    def delete(self, request, pk):
        tenant = self.get_object(pk)
        if not tenant:
            return Response({"message": "租户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if tenant.users.exists():
            return Response({"message": "该租户下仍有用户，无法删除"}, status=status.HTTP_400_BAD_REQUEST)
        tenant.delete()
        return Response({"message": "租户已删除"})


# ===========================================================================
# v8 新增视图（F613–F626 账号与个人）
# ===========================================================================

def _guard(fn):
    """新视图统一异常兜底：ValueError → 400，其余 → 422（结构化，绝不 500）"""

    from functools import wraps

    @wraps(fn)
    def inner(self, request, *args, **kwargs):
        try:
            return fn(self, request, *args, **kwargs)
        except ValidationError as exc:
            # core/validators 的 as_int/parse_bool 走 DRF ValidationError，
            # 与 ValueError 一样按 400 处理，避免变成 422
            return Response({"ok": False, "error": str(exc.detail[0]) if exc.detail else "参数有误", "code": 400}, status=400)
        except ValueError as exc:
            return Response({"ok": False, "error": str(exc), "code": 400}, status=400)
        except Exception as exc:  # noqa: BLE001 —— 结构化降级
            try:
                from core.platform import record_exception

                record_exception(exc, getattr(request, "path", ""))
            except Exception:
                logger.exception("B23：静默兜底已登记（accounts/views.py:1293 原为 pass）——review 是否应收窄异常类型")
            return Response(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}", "code": 422},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    return inner


# ---------------- F614 注销申请（7 天冷静期，可撤销） ----------------

class DeactivateRequestView(APIView):
    """GET 查看注销申请状态 / POST 提交注销申请（冷静期内可继续使用并可撤销）"""

    @_guard
    def get(self, request):
        return Response(_deactivate_state(request.user))

    @_guard
    def post(self, request):
        password = str(request.data.get("password", "") or "")
        if not request.user.check_password(password):
            return Response({"ok": False, "error": "密码不正确，无法提交注销申请", "code": 1005},
                            status=400)
        if DeactivateRequest.objects.filter(user=request.user, status="pending").exists():
            return Response({"ok": False, "error": "已存在待执行的注销申请", "code": 1012}, status=400)
        row = DeactivateRequest.objects.create(
            user=request.user,
            reason=str(request.data.get("reason", "") or "")[:255],
            execute_at=timezone.now() + timezone.timedelta(days=DEACTIVATE_COOLDOWN_DAYS),
        )
        OperationLog.objects.create(
            user=request.user, module="accounts", action="create", target="提交注销申请",
            detail=f"冷静期 {DEACTIVATE_COOLDOWN_DAYS} 天，{row.execute_at:%Y-%m-%d %H:%M} 执行",
            ip=get_client_ip(request),
        )
        return Response({**_deactivate_state(request.user), "message": "注销申请已提交，7 天内可随时撤销"},
                        status=201)

    @_guard
    def delete(self, request):
        """DELETE 等价于撤销（同一语义的另一种入口）"""
        return _cancel_deactivate(request)


class DeactivateCancelView(APIView):
    """撤销注销申请（冷静期内）"""

    @_guard
    def post(self, request):
        return _cancel_deactivate(request)


def _cancel_deactivate(request):
    row = DeactivateRequest.objects.filter(user=request.user, status="pending").first()
    if row is None:
        return Response({"ok": False, "error": "没有待执行的注销申请", "code": 404}, status=400)
    row.status = "cancelled"
    row.cancelled_at = timezone.now()
    row.save(update_fields=["status", "cancelled_at"])
    OperationLog.objects.create(
        user=request.user, module="accounts", action="update", target="撤销注销申请",
        ip=get_client_ip(request),
    )
    return Response({**_deactivate_state(request.user), "message": "注销申请已撤销"})


# ---------------- F615 TOTP 双因素 ----------------

class TwoFactorView(APIView):
    """GET 双因素状态（含可复制的 Base32 密钥与 otpauth 链接）"""

    @_guard
    def get(self, request):
        row = TwoFactorSecret.objects.filter(user=request.user).first()
        if row is None:
            # 按需生成，但保持未启用状态（用户点「绑定」时会写入）
            return Response({
                "enabled": False, "configured": False, "secret": "", "otpauth_url": "",
                "digits": totp_lib.DIGITS, "period": totp_lib.PERIOD,
                "algorithm": totp_lib.ALGORITHM, "last_used_at": None,
            })
        return Response({
            "enabled": row.enabled,
            "configured": True,
            "secret": row.secret,
            "otpauth_url": totp_lib.otpauth_url(row.secret, request.user.username),
            "digits": totp_lib.DIGITS,
            "period": totp_lib.PERIOD,
            "algorithm": totp_lib.ALGORITHM,
            "created_at": row.created_at.isoformat(),
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        })


class TwoFactorSetupView(APIView):
    """POST 生成 / 重新生成密钥（尚未启用，需用验证码确认）"""

    @_guard
    def post(self, request):
        secret = totp_lib.generate_secret()
        row, created = TwoFactorSecret.objects.update_or_create(
            user=request.user,
            defaults={"secret": secret, "enabled": False, "confirmed_at": None},
        )
        return Response({
            "message": "密钥已生成，请在验证器 App 中录入后提交验证码" if created else "密钥已重新生成，请重新录入验证器",
            "enabled": row.enabled,
            "secret": row.secret,
            "otpauth_url": totp_lib.otpauth_url(row.secret, request.user.username),
            "digits": totp_lib.DIGITS, "period": totp_lib.PERIOD,
        }, status=201 if created else 200)


class TwoFactorVerifyView(APIView):
    """POST {code} 校验并启用（enable）/ 校验并停用（disable）双因素"""

    @_guard
    def post(self, request):
        mode = str(request.data.get("mode") or "enable")
        code = str(request.data.get("code") or "").strip()
        row = TwoFactorSecret.objects.filter(user=request.user).first()
        if row is None:
            return Response({"ok": False, "error": "请先生成密钥", "code": 400}, status=400)
        if not totp_lib.verify(row.secret, code):
            return Response({"ok": False, "error": "验证码错误或已过期", "code": 1018}, status=400)
        now = timezone.now()
        if mode == "disable":
            row.enabled = False
            row.confirmed_at = None
            row.last_used_at = now
            row.save(update_fields=["enabled", "confirmed_at", "last_used_at"])
            OperationLog.objects.create(user=request.user, module="accounts", action="update",
                                        target="关闭两步验证", ip=get_client_ip(request))
            return Response({"message": "两步验证已关闭", "enabled": False})
        row.enabled = True
        row.confirmed_at = now
        row.last_used_at = now
        row.save(update_fields=["enabled", "confirmed_at", "last_used_at"])
        OperationLog.objects.create(user=request.user, module="accounts", action="update",
                                    target="开启两步验证", ip=get_client_ip(request))
        return Response({"message": "两步验证已开启，下次登录需输入验证码", "enabled": True})


# ---------------- F616 安全评分卡 ----------------

class SecurityScoreView(APIView):
    """GET 安全评分卡（0–100，逐项给出得分与改进建议）"""

    @_guard
    def get(self, request):
        u = request.user
        try:
            totp_on = TwoFactorSecret.objects.filter(user=u, enabled=True).exists()
        except Exception:
            totp_on = False
        since = timezone.now() - timezone.timedelta(days=30)
        fails_30d = LoginLog.objects.filter(
            username=u.username, is_success=False, created_at__gte=since
        ).count()
        active_sessions = ActiveSession.objects.filter(user=u, is_revoked=False).count()
        items = [
            {"key": "totp", "label": "开启两步验证（TOTP）", "weight": 25, "passed": totp_on,
             "suggestion": "在「两步验证」中绑定验证器 App，登录时需额外输入 6 位验证码"},
            {"key": "email", "label": "绑定邮箱", "weight": 15, "passed": bool(u.email),
             "suggestion": "填写邮箱，便于找回账号与接收安全提醒"},
            {"key": "phone", "label": "绑定手机号", "weight": 10, "passed": bool(u.phone),
             "suggestion": "填写手机号，作为备用验证方式"},
            {"key": "profile", "label": "资料完整（昵称/简介/头像）", "weight": 15,
             "passed": bool(u.nickname and u.bio and u.avatar),
             "suggestion": "补齐昵称、个人简介并上传头像"},
            {"key": "recent_fail", "label": "近 30 天无登录失败", "weight": 15,
             "passed": fails_30d == 0,
             "suggestion": f"近 30 天有 {fails_30d} 次登录失败，建议修改密码并检查登录历史"},
            {"key": "sessions", "label": "活跃设备不超过 3 台", "weight": 10,
             "passed": active_sessions <= 3,
             "suggestion": f"当前有 {active_sessions} 台活跃设备，可在「登录设备管理」中踢出多余设备"},
            {"key": "dept", "label": "已归属部门/组织", "weight": 10, "passed": bool(u.department_id),
             "suggestion": "联系管理员把自己加入部门，便于协作与数据范围生效"},
        ]
        score = sum(i["weight"] for i in items if i["passed"])
        grade = "优秀" if score >= 90 else "良好" if score >= 75 else "一般" if score >= 60 else "需加强"
        return Response({
            "score": score, "grade": grade, "max": 100, "items": items,
            "passed_count": sum(1 for i in items if i["passed"]),
            "total_count": len(items),
            "tips": [i["suggestion"] for i in items if not i["passed"]],
            "computed_at": timezone.now().isoformat(),
        })


# ---------------- F617 个人公开主页 ----------------

class PublicProfileView(APIView):
    """GET /api/auth/profile/public/<username>/ 公开主页（免登录可读）"""

    permission_classes = [AllowAny]

    @_guard
    def get(self, request, username):
        target = User.objects.filter(username=username).first()
        if target is None or not target.is_active or getattr(target, "is_disabled", False):
            return Response({"ok": False, "error": "用户不存在", "code": 404}, status=404)
        me = request.user if getattr(request.user, "is_authenticated", False) else None
        from files.models import FileMeta
        from notes.models import Note

        badges = [
            {"name": b.badge.name, "icon": b.badge.icon, "level": b.badge.level}
            for b in UserBadge.objects.filter(user=target).select_related("badge")[:20]
        ]
        is_following = None
        if me is not None and me.pk != target.pk:
            is_following = UserFollow.objects.filter(follower=me, following=target).exists()
        payload = {
            "username": target.username,
            "nickname": target.nickname,
            "display_name": target.display_name,
            "avatar": target.avatar.url if target.avatar else "",
            "bio": target.bio,
            "tags": target.tags or [],
            "department": target.department.path_name() if target.department_id else "",
            "role_names": list(target.roles.values_list("name", flat=True)),
            "date_joined": target.date_joined.isoformat() if target.date_joined else None,
            "is_online": bool(
                target.last_active_at
                and (timezone.now() - target.last_active_at).total_seconds() < 300
            ),
            "badges": badges,
            "stats": {
                "notes": Note.objects.filter(owner=target).count(),
                "files": FileMeta.objects.filter(owner=target, is_deleted=False).count(),
                "followers": UserFollow.objects.filter(following=target).count(),
                "following": UserFollow.objects.filter(follower=target).count(),
                "invite_codes": InviteCode.objects.filter(owner=target).count(),
            },
            "is_following": is_following,
            "is_self": bool(me is not None and me.pk == target.pk),
            "profile_url": f"/u/{target.username}",
        }
        if me is not None:  # 登录用户可见最近活跃时间（与用户名录口径一致）
            payload["last_active_at"] = (
                target.last_active_at.isoformat() if target.last_active_at else None
            )
        return Response(payload)


# ---------------- F618 关注 / 粉丝 ----------------

def _follow_item(u, me=None):
    return {
        "id": u.id, "username": u.username, "nickname": u.nickname,
        "display_name": u.display_name, "avatar": u.avatar.url if u.avatar else "",
        "bio": u.bio, "is_following": (
            UserFollow.objects.filter(follower=me, following=u).exists() if me else None
        ),
    }


class FollowToggleView(APIView):
    """POST 切换关注状态（不能关注自己 → ValueError → 400）"""

    @_guard
    def post(self, request, username):
        target = User.objects.filter(username=username, is_active=True).first()
        if target is None:
            raise ValueError("用户不存在")
        if target.pk == request.user.pk:
            raise ValueError("不能关注自己")
        row = UserFollow.objects.filter(follower=request.user, following=target).first()
        if row:
            row.delete()
            following = False
        else:
            UserFollow.objects.create(follower=request.user, following=target)
            following = True
            if target.pk != request.user.pk:
                from core.models import notify

                notify(target, title=f"{request.user.display_name} 关注了你",
                       content="快去他的个人主页看看吧", category="system")
        return Response({
            "following": following,
            "followers_count": UserFollow.objects.filter(following=target).count(),
            "following_count": UserFollow.objects.filter(follower=request.user).count(),
        })


class FollowListView(APIView):
    """GET 我的关注 / 我的粉丝（?type=following|followers）"""

    @_guard
    def get(self, request):
        kind = request.query_params.get("type") or "following"
        limit = as_int(request.query_params.get("limit"), default=50, field="limit", minimum=1, maximum=200)
        if kind == "followers":
            qs = [f.follower for f in
                  UserFollow.objects.filter(following=request.user).select_related("follower")[:limit]]
            total = UserFollow.objects.filter(following=request.user).count()
        else:
            qs = [f.following for f in
                  UserFollow.objects.filter(follower=request.user).select_related("following")[:limit]]
            total = UserFollow.objects.filter(follower=request.user).count()
        return Response({
            "type": kind, "total": total,
            "list": [_follow_item(u, request.user) for u in qs],
            "following_count": UserFollow.objects.filter(follower=request.user).count(),
            "followers_count": UserFollow.objects.filter(following=request.user).count(),
        })


# ---------------- F619 新手任务清单（注册 6 步引导） ----------------

ONBOARDING_STEPS = [
    {"key": "profile", "title": "完善个人资料", "desc": "填写昵称、简介与邮箱", "link": "/profile"},
    {"key": "avatar", "title": "上传头像", "desc": "让同事更容易认出你", "link": "/profile"},
    {"key": "note", "title": "创建第一篇笔记", "desc": "在笔记知识库写下第一条内容", "link": "/notes"},
    {"key": "file", "title": "上传第一个文件", "desc": "把本地文件传到文件中心", "link": "/files"},
    {"key": "project", "title": "创建或加入一个项目", "desc": "在项目看板里协作", "link": "/projects"},
    {"key": "invite", "title": "生成一个邀请码", "desc": "邀请同事加入平台", "link": "/profile"},
]


class OnboardingView(APIView):
    """GET 新手任务清单（6 步引导，进度由真实数据实时推导，天然持久）"""

    @_guard
    def get(self, request):
        u = request.user
        done = {}
        try:
            done["profile"] = bool(u.nickname and u.bio and u.email)
        except Exception:
            done["profile"] = False
        done["avatar"] = bool(u.avatar)
        try:
            from notes.models import Note

            done["note"] = Note.objects.filter(owner=u).exists()
        except Exception:
            done["note"] = False
        try:
            from files.models import FileMeta

            done["file"] = FileMeta.objects.filter(owner=u, is_deleted=False).exists()
        except Exception:
            done["file"] = False
        try:
            from projects.models import Project

            done["project"] = Project.objects.filter(owner=u).exists() or Project.objects.filter(
                members=u
            ).exists()
        except Exception:
            done["project"] = False
        done["invite"] = InviteCode.objects.filter(owner=u).exists()
        steps = [{**s, "done": bool(done.get(s["key"]))} for s in ONBOARDING_STEPS]
        finished = sum(1 for s in steps if s["done"])
        return Response({
            "steps": steps,
            "done_count": finished,
            "total_count": len(steps),
            "progress": round(finished * 100 / len(steps)),
            "all_done": finished == len(steps),
        })


# ---------------- F620 时区与周起始日偏好 ----------------

COMMON_TIMEZONES = [
    "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Taipei", "Asia/Tokyo", "Asia/Seoul",
    "Asia/Singapore", "Asia/Bangkok", "Asia/Kolkata", "Asia/Dubai", "Europe/London",
    "Europe/Paris", "Europe/Berlin", "Europe/Moscow", "America/New_York",
    "America/Chicago", "America/Los_Angeles", "America/Sao_Paulo", "Australia/Sydney",
    "Pacific/Auckland", "UTC",
]


class PreferenceView(APIView):
    """GET / PUT 时区与周起始日偏好（纯标准库 zoneinfo 校验，非法时区 → 400）"""

    @_guard
    def get(self, request):
        return Response({
            **_pref_dict(request.user),
            "common_timezones": COMMON_TIMEZONES,
            "week_start_choices": [{"value": "mon", "label": "周一"}, {"value": "sun", "label": "周日"}],
        })

    @_guard
    def put(self, request):
        return self._save(request)

    @_guard
    def patch(self, request):
        return self._save(request)

    def _save(self, request):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        tz = str(request.data.get("timezone") or request.data.get("timezone_name") or "").strip()
        week_start = str(request.data.get("week_start") or "").strip().lower()
        if tz:
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError, KeyError):
                raise ValueError(f"不支持的时区：{tz}")
        if week_start and week_start not in ("mon", "sun"):
            raise ValueError("week_start 只能是 mon 或 sun")
        row, _ = UserPreference.objects.get_or_create(user=request.user)
        if tz:
            row.timezone_name = tz[:64]
        if week_start:
            row.week_start = week_start
        row.save()
        return Response({"message": "偏好已保存", **_pref_dict(request.user)})


# ---------------- F621 长期访问令牌 PAT ----------------

def _pat_item(t):
    return {
        "id": t.id, "name": t.name, "prefix": t.prefix,
        "created_at": t.created_at.isoformat(),
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
        "is_valid": t.is_valid,
    }


class PersonalTokenView(APIView):
    """GET 我的令牌列表 / POST 创建令牌（明文只在创建时返回一次）"""

    @_guard
    def get(self, request):
        qs = PersonalAccessToken.objects.filter(user=request.user)
        return Response({
            "list": [_pat_item(t) for t in qs],
            "total": qs.count(),
            "usage": "curl -H 'Authorization: Bearer <token>' "
                     f"{request.scheme}://{request.get_host()}/api/core/health/",
        })

    @_guard
    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValueError("请填写令牌名称")
        try:
            days = int(request.data.get("expires_days", 90) or 0)
        except (TypeError, ValueError):
            raise ValueError("expires_days 必须是整数")
        if days < 0 or days > 3650:
            raise ValueError("有效期需在 0（长期）~3650 天之间")
        import hashlib
        import secrets as _secrets

        raw = "pat_" + _secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        obj = PersonalAccessToken.objects.create(
            user=request.user,
            name=name[:80],
            token_hash=token_hash,
            prefix=raw[:12] + "…",
            expires_at=(timezone.now() + timezone.timedelta(days=days)) if days else None,
        )
        OperationLog.objects.create(
            user=request.user, module="accounts", action="create", target="创建访问令牌",
            detail=name[:80], ip=get_client_ip(request),
        )
        return Response({
            "message": "令牌创建成功，请立即复制保存（仅此一次可见）",
            "token": raw,
            "header": f"Authorization: Bearer {raw}",
            "x_header": f"X-Api-Token: {raw}",
            "token_info": _pat_item(obj),
        }, status=201)


class PersonalTokenRevokeView(APIView):
    """DELETE 吊销指定令牌"""

    @_guard
    def delete(self, request, pk):
        obj = PersonalAccessToken.objects.filter(pk=pk, user=request.user).first()
        if obj is None:
            raise ValueError("令牌不存在")
        if obj.revoked_at is None:
            obj.revoked_at = timezone.now()
            obj.save(update_fields=["revoked_at"])
        OperationLog.objects.create(
            user=request.user, module="accounts", action="delete", target="吊销访问令牌",
            detail=obj.name, ip=get_client_ip(request),
        )
        return Response({"message": "令牌已吊销", "token_info": _pat_item(obj)})


# ---------------- F622 昵称变更历史 ----------------

class NicknameHistoryView(APIView):
    """GET 我的昵称变更历史"""

    @_guard
    def get(self, request):
        rows = NicknameHistory.objects.filter(user=request.user)[:100]
        return Response({
            "list": [
                {"id": r.id, "old_value": r.old_value, "new_value": r.new_value,
                 "changed_at": r.changed_at.isoformat()}
                for r in rows
            ],
            "total": NicknameHistory.objects.filter(user=request.user).count(),
        })


# ---------------- F623 头像历史切换 ----------------

class AvatarHistoryView(APIView):
    """GET 头像历史 / POST <pk>/restore 切回指定历史头像"""

    @_guard
    def get(self, request):
        rows = AvatarHistory.objects.filter(user=request.user)[:20]
        current = request.user.avatar.url if request.user.avatar else ""
        return Response({
            "list": [
                {"id": r.id, "image": r.image.url if r.image else "", "note": r.note,
                 "created_at": r.created_at.isoformat(),
                 "is_current": bool(r.image) and bool(current) and current.endswith(r.image.name)}
                for r in rows
            ],
            "total": AvatarHistory.objects.filter(user=request.user).count(),
            "current": current,
        })

    @_guard
    def post(self, request, pk):
        row = AvatarHistory.objects.filter(pk=pk, user=request.user).first()
        if row is None or not row.image:
            raise ValueError("历史头像不存在")
        snapshot_avatar(request.user, note="切换头像前自动保存")
        request.user.avatar = row.image.name
        request.user.save(update_fields=["avatar"])
        return Response({
            "message": "已切换为历史头像",
            "url": request.user.avatar.url if request.user.avatar else "",
        })


# ---------------- F624 通讯录备注名（仅自己可见） ----------------

class ContactAliasView(APIView):
    """GET 我的通讯录备注 / POST 保存（新增或更新）"""

    @_guard
    def get(self, request):
        rows = ContactAlias.objects.filter(owner=request.user).select_related("contact")[:500]
        return Response({
            "list": [
                {
                    "id": r.id,
                    "contact_id": r.contact_id,
                    "username": r.contact.username,
                    "display_name": r.contact.display_name,
                    "avatar": r.contact.avatar.url if r.contact.avatar else "",
                    "alias": r.alias,
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in rows
            ],
            "total": ContactAlias.objects.filter(owner=request.user).count(),
            "note": "备注名仅你自己可见，不会影响对方的展示名",
        })

    @_guard
    def post(self, request):
        alias = str(request.data.get("alias") or "").strip()
        if not alias:
            raise ValueError("请填写备注名")
        username = str(request.data.get("username") or "").strip()
        contact_id = request.data.get("contact_id")
        contact = None
        if contact_id:
            contact = User.objects.filter(pk=contact_id).first()
        elif username:
            contact = User.objects.filter(username=username).first()
        if contact is None:
            raise ValueError("联系人不存在")
        if contact.pk == request.user.pk:
            raise ValueError("不能给自己设置备注名")
        row, _created = ContactAlias.objects.update_or_create(
            owner=request.user, contact=contact, defaults={"alias": alias[:80]}
        )
        return Response({
            "message": "备注已保存",
            "item": {
                "id": row.id, "contact_id": contact.pk, "username": contact.username,
                "display_name": contact.display_name,
                "avatar": contact.avatar.url if contact.avatar else "",
                "alias": row.alias, "updated_at": row.updated_at.isoformat(),
            },
        })


class ContactAliasDeleteView(APIView):
    """DELETE 删除备注"""

    @_guard
    def delete(self, request, pk):
        row = ContactAlias.objects.filter(pk=pk, owner=request.user).first()
        if row is None:
            raise ValueError("备注不存在")
        row.delete()
        return Response({"message": "备注已删除"})


# ---------------- F625 邀请效果看板 ----------------

class InviteDashboardView(APIView):
    """GET 邀请效果看板：每个码的使用次数 / 带来注册数 / 仍活跃数 + 30 天趋势"""

    @_guard
    def get(self, request):
        codes = list(InviteCode.objects.filter(owner=request.user).order_by("-created_at"))
        since = timezone.now() - timezone.timedelta(days=30)
        items = []
        for c in codes:
            uses = InviteUse.objects.filter(invite=c)
            registrations = uses.count()
            active = uses.filter(user__is_active=True, user__is_disabled=False).count()
            items.append({
                "id": c.id, "code": c.code, "max_uses": c.max_uses, "uses": c.uses,
                "registrations": registrations, "active_users": active,
                "is_valid": c.is_valid,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "created_at": c.created_at.isoformat(),
                "conversion": round(registrations * 100 / c.uses, 1) if c.uses else 0.0,
            })
        trend = []
        for i in range(29, -1, -1):
            day = (timezone.now() - timezone.timedelta(days=i)).date()
            n = InviteUse.objects.filter(
                invite__owner=request.user, created_at__date=day
            ).count()
            trend.append({"date": day.isoformat(), "count": n})
        totals = {
            "codes": len(items),
            "uses": sum(i["uses"] for i in items),
            "registrations": sum(i["registrations"] for i in items),
            "active_users": sum(i["active_users"] for i in items),
        }
        return Response({"codes": items, "totals": totals, "trend": trend})


# ---------------- F636 角色变更历史（管理员查询） ----------------

class RoleAuditLogView(APIView):
    """GET 角色变更历史（管理员）：支持按目标用户 / 操作人 / 动作筛选"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        qs = RoleAuditLog.objects.select_related("actor", "target")
        username = request.query_params.get("username")
        action = request.query_params.get("action")
        if username:
            qs = qs.filter(
                Q(target__username__icontains=username) | Q(actor__username__icontains=username)
            )
        if action:
            qs = qs.filter(action=action)
        total = qs.count()
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        return Response({
            "list": [
                {
                    "id": r.id,
                    "time": r.created_at.isoformat(),
                    "actor": r.actor.username if r.actor else "系统",
                    "target": r.target.username if r.target else "（已删除用户）",
                    "target_id": r.target_id,
                    "action": r.action,
                    "action_label": dict(RoleAuditLog.ACTION_CHOICES).get(r.action, r.action),
                    "roles_from": r.roles_from,
                    "roles_to": r.roles_to,
                    "detail": r.detail,
                    "ip": r.ip or "",
                }
                for r in page
            ],
            "total": total,
            "page": pg.page.number if pg.page else 1,
        })
