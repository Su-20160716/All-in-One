# -*- coding: utf-8 -*-
"""共享链接访问校验的统一收口。

背景
----
历史上 `FileDownloadView` 判断非 owner 能否下载时，只检查「该文件存在任意一条
download/edit 分享链接」，既不校验请求带来的 token，也不校验密码、过期与下载上限。
结果是任何登录用户遍历文件 id 就能拿走别人设了密码的分享文件。

现在所有共享访问（浏览、下载）都必须经过本模块，规则只写一处：

1. 链接存在且未撤销
2. 未过期
3. 密码正确（如设置了密码）；密码按 token+IP 计失败次数，5 次退避 15 分钟
4. 下载场景还要看权限与次数上限
5. 计数用 F() 原子自增，并发下不会突破 max_downloads
"""
import time
from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.response import Response

from .models import ShareLink

# #19 密码爆破退避：同「链接 + IP」连续失败 N 次锁定 M 秒。
# 全局匿名 100/min 只能限制单 IP 速率，分布式换 IP 仍可慢慢试；这里按 token+IP
# 单独计数，5 次即锁 15 分钟。
PASSWORD_FAIL_LIMIT = 5
PASSWORD_LOCK_SECONDS = 15 * 60
# #20 访问明细：同 link+IP 10 分钟内合并，历史保留 90 天
VISIT_MERGE_MINUTES = 10
VISIT_RETENTION_DAYS = 90


class ShareAccessError(Exception):
    """共享链接校验失败，携带 HTTP 状态码与结构化提示。"""

    def __init__(self, message, status=403, code=None, extra=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra or {}

    def as_response(self):
        body = {"message": self.message}
        if self.code is not None:
            body["code"] = self.code
        body.update(self.extra)
        return Response(body, status=self.status)


def request_password(request):
    """分享密码只认请求头，避免拼进 URL 后泄露到访问日志/代理日志/Referer。"""
    try:
        return (request.headers.get("X-Share-Password", "") or "").strip()
    except AttributeError:
        return ""


# ---------------- #19 密码失败计数与退避 ----------------

def _guard_key(kind, link, request):
    """按「链接 + 客户端 IP」隔离计数，换 IP 无法共享同一份失败额度。"""
    from core.utils import get_client_ip

    ip = get_client_ip(request) or ""
    return f"share:{kind}:{link.token}:{ip}"


def password_lock_remaining(link, request):
    """剩余锁定秒数；0 表示未锁定。cache 不可用时按未锁定放行，不阻断正常访问。"""
    try:
        deadline = cache.get(_guard_key("pw_lock", link, request))
        if not deadline:
            return 0
        return max(int(float(deadline) - time.time()), 1)
    except Exception:
        return 0


def register_password_failure(link, request):
    """记一次密码失败；累计达阈值即锁定 15 分钟。返回剩余锁定秒数。"""
    try:
        fail_key = _guard_key("pw_fail", link, request)
        try:
            fails = cache.incr(fail_key)
        except ValueError:  # 键不存在或后端不支持 incr
            cache.set(fail_key, 1, PASSWORD_LOCK_SECONDS)
            fails = 1
        if fails >= PASSWORD_FAIL_LIMIT:
            cache.delete(fail_key)  # 锁定期间不再累加，锁满后重新计数
            cache.set(
                _guard_key("pw_lock", link, request),
                time.time() + PASSWORD_LOCK_SECONDS,
                PASSWORD_LOCK_SECONDS,
            )
            return PASSWORD_LOCK_SECONDS
    except Exception:
        pass
    return 0


def clear_password_failures(link, request):
    """密码校验通过后清零失败计数。"""
    try:
        cache.delete(_guard_key("pw_fail", link, request))
    except Exception:
        pass


def find_link(token, file_id=None, folder_id=None):
    """按 token 查链接；可限定文件/文件夹，避免拿 A 文件的 token 去下 B 文件。"""
    if not token:
        return None
    qs = ShareLink.objects.filter(token=token)
    if file_id is not None:
        qs = qs.filter(file_id=file_id)
    if folder_id is not None:
        qs = qs.filter(folder_id=folder_id)
    return qs.first()


def validate_link(link, password="", for_download=False, request=None):
    """校验链接有效性；不通过抛 ShareAccessError。

    :param for_download: True 时额外校验下载权限与次数上限
    :param request: 传入时记录一条访问明细（F14，只存 IP/UA 哈希）
    """
    if not link or link.is_revoked:
        raise ShareAccessError("链接不存在或已失效", status=404)
    if link.expire_at and link.expire_at < timezone.now():
        raise ShareAccessError("链接已过期", status=410)
    if link.password:
        # #19：锁定期内不再校验密码（连正确密码也拒），避免继续猜
        if request is not None:
            remaining = password_lock_remaining(link, request)
            if remaining:
                raise ShareAccessError(
                    "密码错误次数过多，请稍后再试", status=429, code="PASSWORD_LOCKED",
                    extra={"need_password": True, "retry_after": remaining},
                )
        if not check_password(str(password or ""), link.password):
            if request is not None and register_password_failure(link, request):
                raise ShareAccessError(
                    "密码错误次数过多，请稍后再试", status=429, code="PASSWORD_LOCKED",
                    extra={"need_password": True, "retry_after": PASSWORD_LOCK_SECONDS},
                )
            # 401 + need_password 让前端弹密码框
            raise ShareAccessError("请输入访问密码", status=401, extra={"need_password": True})
        if request is not None:
            clear_password_failures(link, request)
    if for_download:
        if link.permission not in ("download", "edit"):
            raise ShareAccessError("当前链接不允许下载", status=403)
        if link.max_downloads is not None and link.download_count >= link.max_downloads:
            raise ShareAccessError("下载次数已达上限", status=403)
    if request is not None:
        record_visit(link, request)
    return link


def record_visit(link, request):
    """F14 访问明细：只落 IP/UA 的 sha256 前缀，失败不影响分享访问

    #20：视频 Range 分段请求会逐段触发，同 link+IP 在 10 分钟内合并为一条；
    历史数据按 90 天保留期清理（借 cache 每天最多清一次，避免每次访问扫全表）。
    """
    try:
        import hashlib

        from core.utils import get_client_ip

        from .models import ShareVisit

        ip = get_client_ip(request) or ""
        ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32] if ip else ""
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:300]
        now = timezone.now()
        merged = ShareVisit.objects.filter(
            link=link, ip_hash=ip_hash,
            created_at__gte=now - timedelta(minutes=VISIT_MERGE_MINUTES),
        ).exists()
        if not merged:
            ShareVisit.objects.create(
                link=link,
                ip_hash=ip_hash,
                ua_hash=hashlib.sha256(ua.encode("utf-8")).hexdigest()[:32] if ua else "",
            )
        _purge_old_visits(now)
    except Exception:
        pass


def _purge_old_visits(now):
    """#20 保留 90 天；cache.add 保证同一进程/实例每天最多清理一次。"""
    try:
        from .models import ShareVisit

        if not cache.add("share:visit_purge", 1, 24 * 3600):
            return
        ShareVisit.objects.filter(
            created_at__lt=now - timedelta(days=VISIT_RETENTION_DAYS)
        ).delete()
    except Exception:
        pass


def bump_view(link):
    """浏览计数原子自增（并发下不丢计数）。"""
    ShareLink.objects.filter(pk=link.pk).update(view_count=F("view_count") + 1)


def bump_download(link):
    """下载计数原子自增，并保证不超过 max_downloads。

    :returns: True 表示本次占用成功；False 表示并发下已达上限
    """
    return bool(
        ShareLink.objects.filter(pk=link.pk)
        .filter(Q(max_downloads__isnull=True) | Q(download_count__lt=F("max_downloads")))
        .update(download_count=F("download_count") + 1)
    )
