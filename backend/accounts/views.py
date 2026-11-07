"""用户认证 / 个人中心 / 角色权限管理 视图"""
import logging

logger = logging.getLogger(__name__)

import json
import os

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
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
    ApiTokenUsage,
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
from core.validators import as_datetime, as_int, parse_bool

User = get_user_model()

# ---------------------------------------------------------------------------
# F626 登录失败保护：同账号连续 N 次失败 → 锁定 M 分钟（并写入登录历史）
# #4：锁定维度从「仅账号」升级为「账号 / 账号+IP / 单 IP 失败总量」三重，
#     避免匿名者连错 5 次就锁死指定账号（也顺手削弱账号枚举预言机）。
# ---------------------------------------------------------------------------
LOGIN_LOCK_THRESHOLD = 5
LOGIN_LOCK_MINUTES = 10
# 账号维度（跨 IP）阈值：高于「账号+IP」一档，既保留定向爆破防护，
# 又不再让任意匿名者 5 次就把别人的账号锁死
LOGIN_ACCOUNT_LOCK_THRESHOLD = 15
# 同一 IP 在窗口内失败总量上限：跨账号撞库（spraying）单独限流
LOGIN_IP_LOCK_THRESHOLD = 20
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


# ---------------- F626 登录失败锁定（#4 双维度计数） ----------------

def _failures_since_last_success(username=None, ip=None):
    """返回该维度下「自最近一次成功之后」的失败记录查询集

    账号维度：username；账号+IP 维度：username & ip；IP 维度：ip。
    """
    now = timezone.now()
    fails = LoginLog.objects.filter(is_success=False, created_at__lte=now)
    oks = LoginLog.objects.filter(is_success=True, created_at__lte=now)
    if username is not None:
        fails = fails.filter(username=username)
        oks = oks.filter(username=username)
    if ip is not None:
        fails = fails.filter(ip=ip)
        oks = oks.filter(ip=ip)
    last_ok = oks.order_by("-created_at").values_list("created_at", flat=True).first()
    if last_ok:
        fails = fails.filter(created_at__gt=last_ok)
    return fails


def _remaining_lock(fails_qs, threshold, now) -> int:
    """失败数达到阈值时返回剩余锁定秒数，否则返回 0"""
    if fails_qs.count() < threshold:
        return 0
    latest = fails_qs.order_by("-created_at").values_list("created_at", flat=True).first()
    if latest is None:
        return 0
    until = latest + timezone.timedelta(minutes=LOGIN_LOCK_MINUTES)
    if now < until:
        return max(1, int((until - now).total_seconds()))
    return 0


def login_lock_state(username: str, ip: str = None):
    """登录失败锁定状态：三重维度取最大剩余锁定时间。

    - 账号 + IP：同设备连续 5 次失败（主判定，不牵连其他设备/其他用户）
    - 账号（跨 IP）：连续 15 次失败（防多 IP 轮换的定向爆破）
    - 单 IP 失败总量：20 次（防撞库 spraying，覆盖大量不同账号名）

    返回剩余锁定秒数（int）表示仍在锁定期，返回 None 表示未锁定。
    锁定期内的拦截请求不再写失败记录，避免「越锁越久」。
    """
    if not username and not ip:
        return None
    now = timezone.now()
    try:
        checks = []
        if username:
            if ip:
                checks.append(
                    (_failures_since_last_success(username=username, ip=ip), LOGIN_LOCK_THRESHOLD)
                )
            checks.append(
                (_failures_since_last_success(username=username), LOGIN_ACCOUNT_LOCK_THRESHOLD)
            )
        if ip:
            checks.append((_failures_since_last_success(ip=ip), LOGIN_IP_LOCK_THRESHOLD))
        locked = 0
        for qs, threshold in checks:
            locked = max(locked, _remaining_lock(qs, threshold, now))
        return locked or None
    except Exception:
        return None


# ---------------- F614 注销冷静期：执行到期申请 ----------------

def process_due_deactivations() -> int:
    """执行已到冷静期的注销申请（幂等；任何异常都不影响主流程）

    #69：先用条件 update 把 pending 抢占成 running，只有真正抢到的 worker
    才执行——多 worker/多进程并发时不会对同一申请重复停用与重复写日志。
    处理失败会把状态放回 pending，等下一轮重试；running 悬挂超过 1 天
    （worker 崩溃）也会被回收。
    """
    done = 0
    now = timezone.now()
    try:
        DeactivateRequest.objects.filter(
            status="running", execute_at__lt=now - timezone.timedelta(days=1)
        ).update(status="pending")
        due_ids = list(
            DeactivateRequest.objects.filter(status="pending", execute_at__lte=now)
            .values_list("id", flat=True)
        )
    except Exception:
        return 0
    for rid in due_ids:
        try:
            claimed = DeactivateRequest.objects.filter(pk=rid, status="pending").update(status="running")
        except Exception:
            continue
        if not claimed:
            # 已被其他 worker 抢走 / 已被撤销
            continue
        try:
            with transaction.atomic():
                req = DeactivateRequest.objects.select_for_update().filter(pk=rid).first()
                if req is None or req.status != "running":
                    continue
                user = req.user
                user.is_active = False
                user.is_disabled = True
                user.save(update_fields=["is_active", "is_disabled"])
                req.status = "done"
                req.processed_at = timezone.now()
                req.save(update_fields=["status", "processed_at"])
                OperationLog.objects.create(
                    user=user, module="accounts", action="delete",
                    target="注销申请到期执行", detail=f"冷静期 {DEACTIVATE_COOLDOWN_DAYS} 天已过",
                )
            done += 1
        except Exception:
            logger.exception("注销申请执行失败，回退为 pending 待重试（id=%s）", rid)
            try:
                DeactivateRequest.objects.filter(pk=rid, status="running").update(status="pending")
            except Exception:
                pass
    return done


# ---------------- F615 TOTP ----------------

def _totp_state(user):
    """返回 (是否启用, 密钥, otpauth 链接)；未设置时按需生成"""
    obj = TwoFactorSecret.objects.filter(user=user).first()
    if obj is None:
        return False, "", ""
    return obj.enabled, obj.secret, totp_lib.otpauth_url(obj.secret, user.username)


def _consume_totp(row, code) -> bool:
    """#5 校验并「消费」验证码：命中即把时间步长写回 last_used_counter。

    同一验证码再次提交时命中步长 ≤ last_used_counter 会被拒绝，
    因此 ±1 容差窗口内不可重放（登录、关闭 2FA、重置密钥统一走这里）。
    """
    if row is None:
        return False
    counter = totp_lib.match_counter(row.secret, code, last_counter=row.last_used_counter)
    if counter is None:
        return False
    now = timezone.now()
    try:
        TwoFactorSecret.objects.filter(pk=row.pk).update(
            last_used_counter=counter, last_used_at=now
        )
    except Exception:
        logger.exception("TOTP 计数器写入失败（user_id=%s）", row.user_id)
        return False
    row.last_used_counter = counter
    row.last_used_at = now
    return True


class LoginView(TokenObtainPairView):
    """登录：连续失败锁定（F626）+ TOTP 双因素（F615）+ 到期注销执行（F614）"""

    # B12：签发时写入 tv claim（token_version），认证端据此判定失效
    serializer_class = MyTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        username = (request.data.get("username", "") or "").strip()
        # F614：登录入口顺带执行到期的注销冷静期
        process_due_deactivations()

        # F626 / #4：连续失败锁定（账号+IP、账号、单 IP 三维度取最长剩余时间）
        locked_seconds = login_lock_state(username, get_client_ip(request))
        if locked_seconds:
            minutes = max(1, (locked_seconds + 59) // 60)
            return Response(
                {
                    "code": 1016,
                    # 文案不区分命中哪一维度（账号 / 账号+IP / IP），避免泄露账号是否存在
                    "message": f"登录失败次数过多，请 {minutes} 分钟后再试",
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
            if totp_row is not None and totp_row.enabled:
                # #32：缺验证码时不能暴露「密码是否正确」——无论密码对错都返回
                # 同一条 twofa_required 挑战（保持前端 Login.vue 契约），并计入
                # 一次失败，使未认证请求无法据此判定密码正确性。
                if not code:
                    record_login(request, None, False, username)
                    return Response(
                        {"twofa_required": True, "code": 1017,
                         "message": "该账号已开启两步验证，请输入 6 位验证码", "detail": {}},
                        status=status.HTTP_200_OK,
                    )
                # 先验码：码错直接 401（不泄露密码正确性）；码对再由下方
                # super().post 校验密码，只有全部通过才签发令牌。
                # #5：验码成功后立即消费该时间步长，同一码不可二次使用。
                if not _consume_totp(totp_row, code):
                    record_login(request, None, False, username)
                    return Response(
                        {"code": 1018, "message": "两步验证码错误或已过期", "detail": {}},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )

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
                # #32：密码 + TOTP 全部通过后才记录验证器最近使用时间
                TwoFactorSecret.objects.filter(user=user, enabled=True).update(last_used_at=timezone.now())
                # #56 记录活跃会话
                try:
                    jti = resp.data.get("access", "").split(".")
                    # 从 access token 解 jti
                    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
                    token = AccessToken(resp.data["access"])
                    refresh_raw = resp.data.get("refresh") or ""
                    refresh_jti = str(RefreshToken(refresh_raw)["jti"]) if refresh_raw else ""
                    ActiveSession.objects.create(
                        user=user,
                        jti=str(token["jti"]),
                        refresh_jti=refresh_jti,
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


def _validate_password_policy(password, user=None):
    """#6：把 AUTH_PASSWORD_VALIDATORS 真正落到所有设置口令的入口。

    序列化层只有硬编码的 min_length，settings 里的校验器此前没有任何调用方
    （等于死配置）。这里统一调用 validate_password：长度 / 相似度 / 常见弱口令 /
    纯数字都在同一处生效，失败转成 DRF ValidationError（→ 400）。
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError(list(exc.messages))


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        invite_code = (request.data.get("invite_code") or "").strip()
        # 如果站点设置了 register_invite_required，则必须提供有效邀请码
        from core.models import SiteSetting
        require_invite = SiteSetting.objects.filter(key="register_invite_required", value="1").exists()

        # B5：用户 + 邀请码绑定 + 邀请记录 + 操作日志 + 登录日志多表写，
        # 任一步失败整体回滚，避免「用户建了但邀请码没用上」的中间态。
        # #31：邀请码行加 select_for_update，校验与占用在同一事务内完成，
        # 并发注册无法突破 max_uses。
        with transaction.atomic():
            invite = None
            if invite_code:
                invite = (
                    InviteCode.objects.select_for_update()
                    .filter(code=invite_code)
                    .first()
                )
                if not invite or not invite.is_valid:
                    return Response({"message": "邀请码无效或已过期", "code": 1007}, status=status.HTTP_400_BAD_REQUEST)
                if invite.uses >= invite.max_uses:
                    return Response({"message": "邀请码使用次数已达上限", "code": 1007}, status=status.HTTP_400_BAD_REQUEST)
            elif require_invite:
                return Response({"message": "本站点需要邀请码才能注册", "code": 1008}, status=status.HTTP_400_BAD_REQUEST)

            ser = RegisterSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            # #6：注册口令同样受站点口令策略约束（弱口令 / 纯数字直接 400）
            _validate_password_policy(ser.validated_data["password"])
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
        new_username = ser.validated_data["username"]
        try:
            # #80：唯一性最终以数据库约束为准（serializer 的 exists() 检查
            # 存在并发窗口），同一事务内改名 + 留痕，冲突返回 400 而非 500。
            with transaction.atomic():
                request.user.username = new_username
                request.user.save(update_fields=["username"])
                OperationLog.objects.create(
                    user=request.user, module="accounts", action="update", target="修改用户名",
                    detail=f"{old} → {new_username}", ip=get_client_ip(request),
                )
        except IntegrityError:
            return Response({"message": "该用户名已被占用", "code": 1002}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "用户名已修改", "user": UserSerializer(request.user).data})


class ChangePasswordView(APIView):
    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        new_password = ser.validated_data["new_password"]
        # #6：改密同样走站点口令策略（长度 / 常见弱口令 / 纯数字）
        _validate_password_policy(new_password, user=request.user)
        # #47：改密与「吊销全部会话」放在同一事务里，设备管理页不会再显示
        # 一批实际已失效的旧设备在线；同时 bump token_version 让旧 access 立刻失效。
        with transaction.atomic():
            request.user.set_password(new_password)
            request.user.token_version += 1
            request.user.save(update_fields=["password", "token_version"])
            revoked = ActiveSession.objects.filter(
                user=request.user, is_revoked=False
            ).update(is_revoked=True, revoked_at=timezone.now())
        logger.info("用户 %s 改密成功，已吊销 %s 个活跃会话", request.user.pk, revoked)
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
        # 头像会以静态资源被浏览器直接渲染：必须限定真实图片类型。
        # 历史上直接把上传文件塞给 ImageField，SVG/HTML 可当头像存成 XSS 载荷。
        ext = os.path.splitext(file.name)[1].lower().lstrip(".")
        if ext not in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}:
            return Response({"message": "头像仅支持 jpg/png/gif/webp/bmp"},
                            status=status.HTTP_400_BAD_REQUEST)
        if file.size > 5 * 1024 * 1024:
            return Response({"message": "头像不能超过 5MB"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from PIL import Image

            img = Image.open(file)
            img.verify()
            file.seek(0)
        except Exception:
            return Response({"message": "文件不是有效图片"}, status=status.HTTP_400_BAD_REQUEST)
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


# ---------------- #10 导出前的二次认证 ----------------

# 5 分钟内通过过 TOTP 校验即视为已完成二次认证（与清单口径一致）
EXPORT_REAUTH_TTL_SECONDS = 300
# #85：笔记正文是导出里唯一可能无界的字段（单篇可达数十万字、篇数无上限），
# 一次性拼进内存 JSON 会打爆 worker。只导前 200 篇、单篇截断 200k 字。
EXPORT_NOTE_LIMIT = 200
EXPORT_NOTE_MAX_CHARS = 200_000


def _export_reauth_ok(request) -> bool:
    """导出个人全量数据前的二次认证：当前密码，或 5 分钟内刚校验过 TOTP。"""
    user = request.user
    row = TwoFactorSecret.objects.filter(user=user, enabled=True).first()
    if row is not None and row.last_used_at is not None:
        if (timezone.now() - row.last_used_at).total_seconds() <= EXPORT_REAUTH_TTL_SECONDS:
            return True
    password = str(
        request.query_params.get("password")
        or request.headers.get("X-Reauth-Password", "")
        or ""
    )
    return bool(password) and user.check_password(password)


def _export_notes_payload(user):
    """#85：按上限取笔记，返回 (行列表, 是否发生截断)。

    只取前 EXPORT_NOTE_LIMIT 篇（多取 1 条用于判断是否还有更多），
    单篇正文超过 EXPORT_NOTE_MAX_CHARS 时截断；行结构与原来一致。
    """
    from notes.models import Note

    rows = list(
        Note.objects.filter(owner=user)
        .values("id", "title", "content", "created_at", "updated_at")
        .order_by("id")[: EXPORT_NOTE_LIMIT + 1]
    )
    truncated = len(rows) > EXPORT_NOTE_LIMIT
    rows = rows[:EXPORT_NOTE_LIMIT]
    for row in rows:
        content = row.get("content")
        if isinstance(content, str) and len(content) > EXPORT_NOTE_MAX_CHARS:
            row["content"] = content[:EXPORT_NOTE_MAX_CHARS]
            truncated = True
    return rows, truncated


class DataExportView(APIView):
    """导出我的全部个人数据（F613 数据 JSON 导出：覆盖账号/内容/社交/安全全量模块）

    #10：导出属于高敏感操作——必须二次认证（当前密码或 5 分钟内 TOTP），
    成功后写一条 OperationLog 审计。
    """

    def get(self, request):
        from files.models import FileMeta
        from projects.models import TaskCard
        from im.models import ChatSession

        if not _export_reauth_ok(request):
            return Response(
                {
                    "ok": False,
                    "code": 1031,
                    "message": "导出个人数据需二次认证：请提供当前密码，或在 5 分钟内完成一次两步验证",
                    "detail": {},
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        u = request.user

        def _safe(fn, default=None):
            try:
                return fn()
            except Exception:
                return default if default is not None else []

        # #85：笔记分页导出——前 200 篇、单篇正文截断 200k 字，
        # 超出部分不再拼进内存（全量导出应走后台任务生成文件）。
        notes, notes_truncated = _export_notes_payload(u)

        data = {
            "profile": UserSerializer(u).data,
            "files": list(FileMeta.objects.filter(owner=u).values("id", "name", "size", "kind", "created_at")),
            "notes": notes,
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
            # #85：为 True 表示笔记仅导出前 200 篇 / 单篇截断 200k 字
            "notes_truncated": notes_truncated,
        }
        # #10：留痕（谁、何时、从哪个 IP 导出了全量个人数据）
        try:
            OperationLog.objects.create(
                user=u, module="accounts", action="export", target="导出个人全部数据",
                detail=f"export_version={data['export_version']} 模块数={len(data) - 1}",
                ip=get_client_ip(request),
            )
        except Exception:
            logger.exception("数据导出审计写入失败（user_id=%s）", u.pk)
        return Response(data)


class DataExportCountView(APIView):
    """导出模块计数（#196）：只做 exists 探测，不把全部数据装配一遍。"""

    def get(self, request):
        from files.models import FileMeta
        from im.models import ChatSession
        from notes.models import Note
        from projects.models import TaskCard

        u = request.user

        def _has(qs):
            try:
                return qs.exists()
            except Exception:
                return False

        count = 1  # profile 始终存在
        probes = [
            FileMeta.objects.filter(owner=u),
            Note.objects.filter(owner=u),
            TaskCard.objects.filter(assignees=u),
            ChatSession.objects.filter(members=u),
            LoginLog.objects.filter(user=u),
            _notif_qs(u),
            UserBadge.objects.filter(user=u),
            InviteCode.objects.filter(owner=u),
            InviteUse.objects.filter(invite__owner=u),
            UserFollow.objects.filter(follower=u),
            UserFollow.objects.filter(following=u),
            ContactAlias.objects.filter(owner=u),
            NicknameHistory.objects.filter(user=u),
            AvatarHistory.objects.filter(user=u),
            PersonalAccessToken.objects.filter(user=u),
        ]
        count += sum(1 for qs in probes if _has(qs))
        return Response({"count": count})


class HeartbeatView(APIView):
    """前端定时心跳，刷新在线状态"""

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(last_active_at=timezone.now())
        return Response({"ok": True, "server_time": timezone.now().isoformat()})


# ---------------- #9 用户名探测防护 ----------------

# 按 IP 限流：60 秒内最多 10 次（缓存计数，缓存不可用时降级放行）
USERNAME_CHECK_LIMIT = 10
USERNAME_CHECK_WINDOW = 60


def _username_check_blocked(ip: str) -> bool:
    """同 IP 高频查询判定（滑动窗口用 60 秒固定窗口近似）"""
    from django.core.cache import cache

    key = f"accounts:username_check:{ip or 'unknown'}"
    try:
        if cache.add(key, 1, USERNAME_CHECK_WINDOW):
            return False
        return int(cache.incr(key)) > USERNAME_CHECK_LIMIT
    except ValueError:
        # 计数键刚好过期（add 与 incr 之间被淘汰）：重置后放行本次
        cache.add(key, 1, USERNAME_CHECK_WINDOW)
        return False
    except Exception:
        # 缓存不可用时不阻断正常注册流程
        return False


class UsernameCheckView(APIView):
    """用户名可用性校验（注册/改名实时提示）

    #9：匿名请求统一返回模糊结果（不区分「已占用 / 未占用」），并按 IP 限流，
    消除匿名枚举预言机；登录用户（改名场景）仍返回真实可用性。
    """

    permission_classes = [AllowAny]

    def get(self, request):
        ip = get_client_ip(request)
        if _username_check_blocked(ip):
            return Response(
                {"valid": False, "available": None, "code": 1029,
                 "message": "查询过于频繁，请稍后再试"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        username = (request.query_params.get("username") or "").strip()
        if len(username) < 3:
            # 长度不合法与是否被占用无关，可以直接告知
            return Response({"valid": False, "available": False, "message": "至少 3 个字符"})
        if not getattr(request.user, "is_authenticated", False):
            # 模糊响应：格式校验通过即可提交，占用与否以注册结果为准
            return Response(
                {"valid": True, "available": None,
                 "message": "用户名格式可用，最终以提交注册的结果为准"}
            )
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
    """全员用户名录（登录可见，用于 @、拉人、发起聊天）

    #30：按租户/部门收敛可见范围；邮箱检索仅 staff 可用；只返回最简字段。
    """

    def get(self, request):
        actor = request.user
        qs = User.objects.filter(is_active=True, is_disabled=False)
        # 同租户收敛（模型支持 tenant 字段；超管无租户时不限制）
        if actor.tenant_id:
            qs = qs.filter(tenant_id=actor.tenant_id)
        # 非 staff 只能看到本部门同事（无部门时退化为仅同租户）
        if not actor.is_staff and actor.department_id:
            qs = qs.filter(department_id=actor.department_id)
        keyword = request.query_params.get("q")
        if keyword:
            cond = Q(username__icontains=keyword) | Q(nickname__icontains=keyword)
            # 邮箱属于个人敏感信息，仅 staff 可按邮箱检索
            if actor.is_staff:
                cond |= Q(email__icontains=keyword)
            qs = qs.filter(cond)
        # 先取总数再切片 —— 对切片后的 QuerySet 调 count() 会带上 LIMIT，
        # total 会永远等于 50
        total = qs.count()
        rows = (
            qs.select_related("department")
            .prefetch_related("roles")
            .order_by("username")[:50]
        )
        return Response({"list": UserDirectorySerializer(rows, many=True).data, "total": total})


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
        if user.is_superuser and not request.user.is_superuser:
            return Response({"message": "仅超级管理员可操作超级管理员账号"}, status=status.HTTP_403_FORBIDDEN)

        role_ids = request.data.get("role_ids")
        roles = None
        if isinstance(role_ids, list):
            roles = list(Role.objects.filter(id__in=role_ids).prefetch_related("permissions"))
            if roles and not request.user.is_superuser:
                if any(_is_admin_level_role(r) for r in roles):
                    return Response(
                        {"message": "仅超级管理员可分配管理员级角色"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                if user.id == request.user.id:
                    actor_codes = _actor_permission_codes(request.user)
                    new_codes = {c for r in roles for c in r.permissions.values_list("code", flat=True) if c}
                    if actor_codes is not None and (new_codes - actor_codes):
                        return Response(
                            {"message": "不能为自己分配超出自身权限的角色"},
                            status=status.HTTP_403_FORBIDDEN,
                        )

        with transaction.atomic():
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
            if roles is not None:
                before = list(user.roles.values_list("code", flat=True))
                user.roles.set(roles)
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
        role_ids = request.data.get("role_ids") or []
        if role_ids and not request.user.is_superuser:
            roles = list(Role.objects.filter(id__in=role_ids).prefetch_related("permissions"))
            if any(_is_admin_level_role(r) for r in roles):
                return Response({"message": "仅超级管理员可分配管理员级角色"}, status=status.HTTP_403_FORBIDDEN)
            if any(r.tenant_id and r.tenant_id != request.user.tenant_id for r in roles):
                return Response({"message": "不能分配其他组织的角色"}, status=status.HTTP_403_FORBIDDEN)
        # #6：管理员代建账号的初始口令同样受站点口令策略约束
        _validate_password_policy(ser.validated_data["password"])
        with transaction.atomic():
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
        # 只有超管能重置超管密码，避免 is_staff 直接接管站点
        if user.is_superuser and not request.user.is_superuser:
            return Response({"message": "无权重置超级管理员密码"}, status=status.HTTP_403_FORBIDDEN)
        ser = AdminResetPasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        # #6：管理员重置口令同样受站点口令策略约束
        _validate_password_policy(ser.validated_data["new_password"], user=user)
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


# 管理员级角色编码（内置 admin / superadmin），另加 data_scope=all 与含 admin 权限点
_ADMIN_ROLE_CODES = {"admin", "superadmin", "super_admin"}
_BATCH_ACTION_MAX_IDS = 500


def _is_admin_level_role(role) -> bool:
    """角色是否含管理员级能力：管理员编码 / 全局数据范围 / admin 模块权限点"""
    if role.code in _ADMIN_ROLE_CODES or role.data_scope == "all":
        return True
    # 优先用 prefetch_related("permissions") 的缓存，避免逐角色查询
    return any(p.module == "admin" for p in role.permissions.all())


def _actor_permission_codes(user):
    """非超管操作者当前拥有的权限编码集合（超管返回 None 表示不受限）"""
    if user.is_superuser:
        return None
    return {c for c in user.roles.values_list("permissions__code", flat=True) if c}


def _validate_batch_ids(raw):
    """#81：批量 ids 必须是非空整型列表，去重并限制单次数量"""
    if not isinstance(raw, list) or not raw:
        raise ValidationError("未选择用户")
    ids = {as_int(v, field="user_ids", minimum=1) for v in raw}
    if len(ids) > _BATCH_ACTION_MAX_IDS:
        raise ValidationError(f"单次最多操作 {_BATCH_ACTION_MAX_IDS} 个用户")
    return sorted(ids)


class AdminBatchActionView(APIView):
    """管理员批量操作用户：启用/禁用/删除/分配角色/设置配额
    + F637 扩展：强制下线 / 重置两步验证 / 调整部门 / 重置注销申请
    """

    permission_classes = [IsAdminUser]

    def post(self, request):
        action = request.data.get("action")
        ids = _validate_batch_ids(request.data.get("user_ids") or [])
        # #81：禁止把任何批量操作落到超管与操作者本人身上
        qs = User.objects.filter(id__in=ids).exclude(id=request.user.id).exclude(is_superuser=True)
        if not qs.exists():
            return Response(
                {"message": "没有可操作的用户（不能操作超级管理员或本人）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action == "enable":
            n = qs.update(is_disabled=False, is_active=True)
            msg = f"已启用 {n} 个用户"
        elif action == "disable":
            n = qs.update(is_disabled=True, is_active=False)
            msg = f"已禁用 {n} 个用户"
        elif action == "delete":
            # 只统计主对象，delete() 的返回值包含级联删除的关联对象
            n = qs.count()
            qs.delete()
            msg = f"已删除 {n} 个用户"
        elif action == "quota":
            quota = as_int(request.data.get("storage_quota_mb"), default=2048, field="storage_quota_mb", minimum=0)
            n = qs.update(storage_quota_mb=quota)
            msg = f"已为 {n} 个用户设置配额 {quota}MB"
        elif action == "roles":
            role_ids = request.data.get("role_ids") or []
            roles = list(Role.objects.filter(id__in=role_ids).prefetch_related("permissions"))
            # 与 AssignRoleView 对齐：管理员级角色仅超管可分配
            if not request.user.is_superuser and any(_is_admin_level_role(r) for r in roles):
                return Response({"message": "仅超级管理员可分配管理员级角色"}, status=status.HTTP_403_FORBIDDEN)
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
            n_users = qs.count()
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
            qs.update(token_version=F("token_version") + 1)
            msg = f"已强制 {n_users} 个用户下线（会话 {n_sess} 个 / 吊销令牌 {n_tok} 个）"
        elif action == "reset_2fa":
            n = TwoFactorSecret.objects.filter(user__in=qs).update(
                enabled=False, confirmed_at=None, last_used_at=None
            )
            msg = f"已重置 {n} 个用户的两步验证（需重新绑定）"
        elif action == "assign_dept":
            dept_id = as_int(request.data.get("department"), default=None, field="department") if request.data.get("department") else None
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
        users = list(
            User.objects.filter(id__in=ser.validated_data["user_ids"]).prefetch_related("roles")
        )
        roles = list(
            Role.objects.filter(id__in=ser.validated_data["role_ids"]).prefetch_related("permissions")
        )
        # #22：管理员级角色（admin 编码 / data_scope=all / admin 模块权限点）仅超管可分配
        if roles and not request.user.is_superuser and any(_is_admin_level_role(r) for r in roles):
            return Response(
                {"message": "仅超级管理员可分配管理员级角色"},
                status=status.HTTP_403_FORBIDDEN,
            )
        # #22：禁止自我提权——非超管给自己分配的角色权限不得超出自己已有权限
        actor_codes = _actor_permission_codes(request.user)
        if actor_codes is not None:
            new_codes = {
                code
                for r in roles
                for code in r.permissions.values_list("code", flat=True)
                if code
            }
            if any(u.id == request.user.id for u in users) and (new_codes - actor_codes):
                return Response(
                    {"message": "不能为自己分配超出自身权限的角色"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        after = [r.code for r in roles]
        ip = get_client_ip(request)
        for u in users:
            before = [r.code for r in u.roles.all()]
            u.roles.set(roles)
            if before != after:
                record_role_change(request.user, u, "assign", before, after, ip, "批量分配角色")
        return Response({"message": f"已为 {len(users)} 个用户分配角色"})


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
        scope = request.data.get("data_scope") or "self"
        if scope == "all" and not request.user.is_superuser:
            return Response({"message": "仅超级管理员可设置全局数据范围"}, status=status.HTTP_403_FORBIDDEN)
        role = Role.objects.create(
            name=name, code=code, description=request.data.get("description", ""),
            data_scope=scope,
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
        if _is_admin_level_role(role) and not request.user.is_superuser:
            return Response({"message": "仅超级管理员可修改管理员级角色"}, status=status.HTTP_403_FORBIDDEN)
        permission_ids = request.data.get("permission_ids")
        if isinstance(permission_ids, list) and not request.user.is_superuser:
            if Permission.objects.filter(id__in=permission_ids, module="admin").exists():
                return Response({"message": "仅超级管理员可分配管理模块权限点"}, status=status.HTTP_403_FORBIDDEN)
        if "name" in request.data:
            role.name = request.data["name"]
        if "description" in request.data:
            role.description = request.data["description"]
        if "data_scope" in request.data:
            scope = request.data["data_scope"] or "self"
            if scope == "all" and not request.user.is_superuser:
                return Response({"message": "仅超级管理员可设置全局数据范围"}, status=status.HTTP_403_FORBIDDEN)
            role.data_scope = scope
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
        # #31：普通用户按角色配额限制（次数 ≤10、有效期 ≤30 天）；staff/超管不限
        unlimited = request.user.is_staff or request.user.is_superuser
        max_uses = as_int(
            request.data.get("max_uses"), default=1, field="max_uses",
            minimum=1, maximum=None if unlimited else 10,
        )
        expires_days = as_int(
            request.data.get("expires_days"), default=30, field="expires_days",
            minimum=0 if unlimited else 1, maximum=None if unlimited else 30,
        )
        code = InviteCode.generate(request.user, max_uses=max_uses, expires_days=expires_days)
        return Response(InviteCodeSerializer(code).data, status=status.HTTP_201_CREATED)


# ---------------- #56 登录设备 / 会话管理 ----------------

class MySessionsView(APIView):
    """我的活跃会话列表"""

    def get(self, request):
        qs = ActiveSession.objects.filter(user=request.user, is_revoked=False).order_by("-last_seen")
        return Response({"list": ActiveSessionSerializer(qs, many=True).data, "total": qs.count()})


class SessionRevokeView(APIView):
    """吊销指定会话（踢下线）

    #11：黑名单只挡 refresh，access 在有效期内仍可用、WS 长连接也不会断。
    因此吊销时同步 bump token_version——accounts.auth 的 tv 校验与
    ws_app.middleware 的握手校验都以该字段为准，HTTP 与 WebSocket
    两侧立即失效。
    """

    def post(self, request, pk):
        sess = ActiveSession.objects.filter(pk=pk, user=request.user).first()
        if not sess:
            return Response({"message": "会话不存在"}, status=404)
        sess.is_revoked = True
        sess.revoked_at = timezone.now()
        sess.save(update_fields=["is_revoked", "revoked_at"])
        # 将 refresh token 加入 simplejwt 黑名单（否则攻击者可用 refresh 续出新 access）
        try:
            from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

            refresh_jti = getattr(sess, "refresh_jti", "") or ""
            if refresh_jti:
                ot = OutstandingToken.objects.filter(jti=refresh_jti).first()
                if ot is not None:
                    BlacklistedToken.objects.get_or_create(token=ot)
            else:
                # 老会话没有记录 refresh_jti：退化为吊销该用户全部 refresh
                for ot in OutstandingToken.objects.filter(user_id=sess.user_id):
                    BlacklistedToken.objects.get_or_create(token=ot)
        except Exception:
            logger.exception("B23：静默兜底已登记（accounts/views.py:1086 原为 pass）——review 是否应收窄异常类型")
        # #11：token_version 单调递增，已签发的 access/PAT 立即失效（WS 握手同样被拒）。
        # 注意：该字段是用户级而非会话级，踢任一台设备都会让全端重新登录。
        try:
            User.objects.filter(pk=request.user.pk).update(token_version=F("token_version") + 1)
            request.user.token_version += 1
        except Exception:
            logger.exception("踢下线时 token_version 递增失败（user_id=%s）", request.user.pk)
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
            # #48：直接把原始字符串塞给 DateTimeField 会在 save() 才抛 500；
            # 统一用 as_datetime 解析（非法值 → 400），且不允许设置为过去时间。
            raw_expire = request.data["expire_at"]
            if raw_expire in (None, ""):
                tenant.expire_at = None
            else:
                expire_at = as_datetime(raw_expire, field="expire_at")
                if expire_at <= timezone.now():
                    return Response({"message": "到期时间必须晚于当前时间"}, status=400)
                tenant.expire_at = expire_at
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
            # #7：非参数类异常一律不回显 str(exc)——它可能带出 ORM 字段名、
            # 磁盘路径、SQL 片段等内部信息。调用方只拿到固定文案与错误码，
            # 细节仅写日志 / 异常平台。
            logger.exception("accounts 视图未预期异常（path=%s）", getattr(request, "path", ""))
            try:
                from core.platform import record_exception

                record_exception(exc, getattr(request, "path", ""))
            except Exception:
                logger.exception("B23：静默兜底已登记（accounts/views.py:1293 原为 pass）——review 是否应收窄异常类型")
            return Response(
                {"ok": False, "error": "服务器处理异常，请稍后重试或联系管理员", "code": 422},
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
    """GET 双因素状态。已启用后不再返回明文 secret / otpauth 链接（#21）。"""

    @_guard
    def get(self, request):
        row = TwoFactorSecret.objects.filter(user=request.user).first()
        if row is None:
            # 按需生成，但保持未启用状态（用户点「绑定」时会写入）
            return Response({
                "enabled": False, "configured": False, "secret": "", "otpauth_url": "",
                "secret_available": False,
                "digits": totp_lib.DIGITS, "period": totp_lib.PERIOD,
                "algorithm": totp_lib.ALGORITHM, "last_used_at": None,
            })
        # 启用后 secret 只允许在 setup 响应中返回一次；此后 GET 一律脱敏
        secret_visible = not row.enabled
        return Response({
            "enabled": row.enabled,
            "configured": True,
            "secret": row.secret if secret_visible else "",
            "otpauth_url": totp_lib.otpauth_url(row.secret, request.user.username) if secret_visible else "",
            "secret_available": secret_visible,
            "digits": totp_lib.DIGITS,
            "period": totp_lib.PERIOD,
            "algorithm": totp_lib.ALGORITHM,
            "created_at": row.created_at.isoformat(),
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        })


class TwoFactorSetupView(APIView):
    """POST 生成 / 重新生成密钥（尚未启用，需用验证码确认）

    #21：已有密钥（重置）时必须提供账号密码；已启用的密钥重置还需有效 TOTP。
    首次绑定（尚无密钥）不需要密码，保持现有前端「生成密钥并绑定」流程可用。
    """

    @_guard
    def post(self, request):
        row = TwoFactorSecret.objects.filter(user=request.user).first()
        if row is not None:
            password = str(request.data.get("password") or "")
            if not password or not request.user.check_password(password):
                return Response({"ok": False, "error": "重置两步验证需要输入正确的账号密码", "code": 1005}, status=400)
            if row.enabled:
                code = str(request.data.get("totp_code") or request.data.get("code") or "").strip()
                if not _consume_totp(row, code):
                    return Response(
                        {"ok": False, "error": "重置已开启的两步验证需要当前验证码", "code": 1018},
                        status=400,
                    )
        secret = totp_lib.generate_secret()
        row, created = TwoFactorSecret.objects.update_or_create(
            user=request.user,
            defaults={"secret": secret, "enabled": False, "confirmed_at": None},
        )
        return Response({
            "message": "密钥已生成，请在验证器 App 中录入后提交验证码" if created else "密钥已重新生成，请重新录入验证器",
            "enabled": row.enabled,
            "configured": True,
            "secret": row.secret,
            "otpauth_url": totp_lib.otpauth_url(row.secret, request.user.username),
            "secret_available": True,
            "digits": totp_lib.DIGITS, "period": totp_lib.PERIOD,
        }, status=201 if created else 200)


class TwoFactorVerifyView(APIView):
    """POST {code} 校验并启用（enable）/ 校验并停用（disable）双因素

    #21：关闭已启用的两步验证必须同时提供账号密码 + 当前 TOTP。
    """

    @_guard
    def post(self, request):
        mode = str(request.data.get("mode") or "enable")
        code = str(request.data.get("code") or "").strip()
        row = TwoFactorSecret.objects.filter(user=request.user).first()
        if row is None:
            return Response({"ok": False, "error": "请先生成密钥", "code": 400}, status=400)
        if mode == "disable":
            password = str(request.data.get("password") or "")
            if not row.enabled:
                return Response({"ok": False, "error": "两步验证未开启", "code": 400}, status=400)
            if not password or not request.user.check_password(password):
                return Response({"ok": False, "error": "关闭两步验证需要输入正确的账号密码", "code": 1005}, status=400)
        if not _consume_totp(row, code):
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
    """GET /api/auth/profile/public/<username>/ 公开主页

    #8 隐私分级（免登录不再能做人员画像）：
    - 匿名：仅昵称 / 头像 / 简介等名片字段；
    - 登录：追加关注关系、在线状态等社交字段；
    - 登录且同组织（或本人 / staff）：才返回部门路径、角色名、注册时间、
      徽章与内容/粉丝计数。
    """

    permission_classes = [AllowAny]

    @_guard
    def get(self, request, username):
        target = User.objects.filter(username=username).first()
        if target is None or not target.is_active or getattr(target, "is_disabled", False):
            return Response({"ok": False, "error": "用户不存在", "code": 404}, status=404)
        me = request.user if getattr(request.user, "is_authenticated", False) else None
        payload = {
            "username": target.username,
            "nickname": target.nickname,
            "display_name": target.display_name,
            "avatar": target.avatar.url if target.avatar else "",
            "bio": target.bio,
            "profile_url": f"/u/{target.username}",
        }
        if me is None:
            # 未登录：到此为止，不返回任何可用于画像的字段
            return Response(payload)

        is_following = None
        if me.pk != target.pk:
            is_following = UserFollow.objects.filter(follower=me, following=target).exists()
        payload.update({
            "tags": target.tags or [],
            "is_following": is_following,
            "is_self": bool(me.pk == target.pk),
            "is_online": bool(
                target.last_active_at
                and (timezone.now() - target.last_active_at).total_seconds() < 300
            ),
            # 登录用户可见最近活跃时间（与用户名录口径一致）
            "last_active_at": (
                target.last_active_at.isoformat() if target.last_active_at else None
            ),
        })

        # 同组织判定：本人 / staff / 双方租户一致（都为 None 视为单租户部署，
        # 也算同一组织；只要一方有租户则必须完全一致）
        same_org = (
            me.pk == target.pk
            or getattr(me, "is_staff", False)
            or me.tenant_id == target.tenant_id
        )
        if not same_org:
            payload["detail_hidden"] = True
            return Response(payload)

        from files.models import FileMeta
        from notes.models import Note

        badges = [
            {"name": b.badge.name, "icon": b.badge.icon, "level": b.badge.level}
            for b in UserBadge.objects.filter(user=target).select_related("badge")[:20]
        ]
        payload.update({
            "department": target.department.path_name() if target.department_id else "",
            "role_names": list(target.roles.values_list("name", flat=True)),
            "date_joined": target.date_joined.isoformat() if target.date_joined else None,
            "badges": badges,
            "stats": {
                "notes": Note.objects.filter(owner=target).count(),
                "files": FileMeta.objects.filter(owner=target, is_deleted=False).count(),
                "followers": UserFollow.objects.filter(following=target).count(),
                "following": UserFollow.objects.filter(follower=target).count(),
                "invite_codes": InviteCode.objects.filter(owner=target).count(),
            },
            "detail_hidden": False,
        })
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
        # #414 作用域：空列表 = 全权（兼容升级前的旧令牌）
        "scopes": [s.strip() for s in (getattr(t, "scopes", "") or "").split(",") if s.strip()],
        "scopes_raw": getattr(t, "scopes", "") or "",
    }


# #414 允许的作用域：read / write / * 与 <资源>:<read|write|*>
def _normalize_pat_scopes(value) -> str:
    """scopes 入参（字符串或数组）→ 规范化逗号串；空串表示全权"""
    from core.middleware import SCOPE_RESOURCES

    if value is None:
        return ""
    if isinstance(value, str):
        items = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValidationError("scopes 必须是字符串或数组")
    resources = set(SCOPE_RESOURCES.values()) | {"api"}
    out = []
    for raw in items:
        token = str(raw or "").strip().lower()
        if not token:
            continue
        if token in ("*", "read", "write"):
            if token not in out:
                out.append(token)
            continue
        resource, _, action = token.partition(":")
        if not action or resource not in resources or action not in ("read", "write", "*"):
            raise ValidationError(
                f"scope 不合法：{token[:32]}（可用 read/write/* 或 <资源>:<read|write|*>）"
            )
        if token not in out:
            out.append(token)
    if len(out) > 20:
        raise ValidationError("scopes 最多 20 个")
    joined = ",".join(out)
    if len(joined) > 200:
        raise ValidationError("scopes 总长度不能超过 200")
    return joined


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
        scopes = _normalize_pat_scopes(request.data.get("scopes"))
        import hashlib
        import secrets as _secrets

        raw = "pat_" + _secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        obj = PersonalAccessToken.objects.create(
            user=request.user,
            name=name[:80],
            token_hash=token_hash,
            token_version=request.user.token_version,
            prefix=raw[:12] + "…",
            scopes=scopes,
            expires_at=(timezone.now() + timezone.timedelta(days=days)) if days else None,
        )
        OperationLog.objects.create(
            user=request.user, module="accounts", action="create", target="创建访问令牌",
            detail=f"{name[:60]} scopes={scopes or '*'}", ip=get_client_ip(request),
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


class PersonalTokenUsageView(APIView):
    """#415 GET 单个令牌的按日调用量（?days=30，最多 365 天）"""

    @_guard
    def get(self, request, pk):
        token = PersonalAccessToken.objects.filter(pk=pk, user=request.user).first()
        if token is None:
            return Response({"ok": False, "code": 404, "error": "令牌不存在"}, status=404)
        try:
            days = int(request.query_params.get("days") or 30)
        except (TypeError, ValueError):
            raise ValueError("days 必须是整数")
        if days < 1 or days > 365:
            raise ValueError("days 需在 1~365 之间")
        today = timezone.localdate()
        start_day = today - timezone.timedelta(days=days - 1)
        rows = {
            r.date: r
            for r in ApiTokenUsage.objects.filter(token=token, date__gte=start_day)
        }
        series = []
        for offset in range(days):
            day = start_day + timezone.timedelta(days=offset)
            row = rows.get(day)
            series.append({
                "date": day.isoformat(),
                "count": row.count if row else 0,
                "last_path": (row.last_path if row else "") or "",
            })
        total = sum(item["count"] for item in series)
        peak = max(series, key=lambda x: x["count"]) if series else {"date": "", "count": 0}
        return Response({
            "token": _pat_item(token),
            "days": days,
            "start": start_day.isoformat(),
            "end": today.isoformat(),
            "total": total,
            "avg": round(total / days, 1),
            "peak": {"date": peak.get("date", ""), "count": peak.get("count", 0)},
            "series": series,
        })


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
        # 先把目标记录提到最新，避免 snapshot 的「只留 10 张」把它清理掉
        row.created_at = timezone.now()
        row.save(update_fields=["created_at"])
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


# ===========================================================================
# F08/F09/F10 组织与权限增强（纯新增）
# ===========================================================================

class DepartmentMoveView(APIView):
    """F08 部门移动：改上级并校验不成环，返回新的路径与下级清单"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        dept = Department.objects.filter(pk=pk).first()
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        raw = request.data.get("parent", request.data.get("parent_id"))
        parent = None
        if raw not in (None, "", 0, "0"):
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                return Response({"message": "parent 必须是整数"}, status=400)
            if pid in dept.descendant_ids(include_self=True):
                return Response({"message": "不能将部门移动到自身或其下级"}, status=400)
            parent = Department.objects.filter(pk=pid).first()
            if not parent:
                return Response({"message": "目标部门不存在"}, status=404)
        dept.parent = parent
        if "sort" in request.data:
            try:
                dept.sort = int(request.data.get("sort") or 0)
            except (TypeError, ValueError):
                return Response({"message": "sort 必须是整数"}, status=400)
        dept.save(update_fields=["parent", "sort"])
        return Response({
            "id": dept.id, "name": dept.name, "parent": parent.id if parent else None,
            "path": dept.path_name(), "descendant_ids": dept.descendant_ids(),
            "member_count": dept.members.count(),
        })


class ActivityHeatmapView(APIView):
    """F09 用户活跃热力图：按周×小时聚合登录/操作日志

    #106：原来把 90 天的 created_at 全量拉进 Python 再逐条 localtime 分桶，
    数据量随日志线性增长（百万级日志 = 百万次 Python 循环 + 巨量内存）。
    改为在 DB 内用 TruncDay + ExtractWeekDay/ExtractHour 聚合，只回 7×24 个桶。
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count
        from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDay

        from core.models import OperationLog

        try:
            days = int(request.query_params.get("days") or 90)
        except (TypeError, ValueError):
            return Response({"message": "days 必须是整数"}, status=400)
        days = max(7, min(180, days))
        user_id = request.query_params.get("user")
        since = timezone.now() - timedelta(days=days)
        login = LoginLog.objects.filter(is_success=True, created_at__gte=since)
        oper = OperationLog.objects.filter(created_at__gte=since)
        if user_id:
            try:
                uid = int(user_id)
            except (TypeError, ValueError):
                return Response({"message": "user 必须是整数"}, status=400)
            login, oper = login.filter(user_id=uid), oper.filter(user_id=uid)

        # 分桶口径：一天（本地时区的自然日）× 星期 × 小时，聚合出 ≤ 天数×24 行
        tz = timezone.get_current_timezone()
        weekday = [0] * 7
        hour = [0] * 24
        by_day = {}
        cells = {}
        for qs in (login, oper):
            rows = (
                qs.annotate(
                    _day=TruncDay("created_at"),
                    _weekday=ExtractWeekDay("created_at", tzinfo=tz),
                    _hour=ExtractHour("created_at", tzinfo=tz),
                )
                .values("_day", "_weekday", "_hour")
                .annotate(_count=Count("id"))
            )
            for row in rows:
                count = row["_count"] or 0
                if not count:
                    continue
                day = row["_day"]
                if day is not None:
                    key = (day.date() if hasattr(day, "date") else day).isoformat()
                    by_day[key] = by_day.get(key, 0) + count
                wd, hr = row["_weekday"], row["_hour"]
                if wd is None or hr is None:
                    continue
                # ExtractWeekDay 的返回口径是 Sunday=1 … Saturday=7，换算成「周一=0」
                idx = (int(wd) + 5) % 7
                hr = int(hr)
                weekday[idx] += count
                hour[hr] += count
                cells[(idx, hr)] = cells.get((idx, hr), 0) + count
        return Response({
            "days": days,
            "total": sum(weekday),
            "weekday_labels": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
            "by_weekday": weekday,
            "by_hour": hour,
            "by_day": [{"date": k, "count": v} for k, v in sorted(by_day.items())],
            "cells": [
                {"weekday": w, "hour": h, "count": c}
                for (w, h), c in sorted(cells.items())
            ],
            "peak": {"weekday": weekday.index(max(weekday)) if weekday else 0,
                     "hour": hour.index(max(hour)) if hour else 0},
        })


class RoleMatrixView(APIView):
    """F10 角色×权限矩阵：GET 读取，PUT 整体保存（事务内）"""

    permission_classes = [IsAdminUser]

    def _role(self, pk):
        return Role.objects.filter(pk=pk).first()

    def get(self, request, pk):
        role = self._role(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        perms = list(Permission.objects.all().order_by("module", "id"))
        modules = {}
        for p in perms:
            modules.setdefault(p.module, []).append({
                "id": p.id, "code": p.code, "name": p.name,
            })
        return Response({
            "role": {"id": role.id, "name": role.name, "code": role.code,
                     "data_scope": role.data_scope, "is_builtin": role.is_builtin},
            "modules": [{"module": m, "permissions": rows} for m, rows in modules.items()],
            "permission_ids": list(role.permissions.values_list("id", flat=True)),
            "total_permissions": len(perms),
        })

    def put(self, request, pk):
        role = self._role(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        ids = request.data.get("permission_ids")
        codes = request.data.get("permission_codes")
        if ids is None and codes is None:
            return Response({"message": "需要 permission_ids 或 permission_codes"}, status=400)
        if ids is not None and not isinstance(ids, list):
            return Response({"message": "permission_ids 必须是数组"}, status=400)
        if codes is not None and not isinstance(codes, list):
            return Response({"message": "permission_codes 必须是数组"}, status=400)
        with transaction.atomic():
            if ids is not None:
                qs = Permission.objects.filter(id__in=[int(i) for i in ids if str(i).isdigit()])
            else:
                qs = Permission.objects.filter(code__in=[str(c) for c in codes])
            role.permissions.set(qs)
            applied = qs.count()
        return Response({"message": "权限矩阵已保存", "role_id": role.id,
                         "applied": applied,
                         "permission_ids": list(role.permissions.values_list("id", flat=True))})
