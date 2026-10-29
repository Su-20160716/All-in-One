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
3. 密码正确（如设置了密码）
4. 下载场景还要看权限与次数上限
5. 计数用 F() 原子自增，并发下不会突破 max_downloads
"""
from django.contrib.auth.hashers import check_password
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.response import Response

from .models import ShareLink


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
    if link.password and not check_password(str(password or ""), link.password):
        # 401 + need_password 让前端弹密码框
        raise ShareAccessError("请输入访问密码", status=401, extra={"need_password": True})
    if for_download:
        if link.permission not in ("download", "edit"):
            raise ShareAccessError("当前链接不允许下载", status=403)
        if link.max_downloads is not None and link.download_count >= link.max_downloads:
            raise ShareAccessError("下载次数已达上限", status=403)
    if request is not None:
        record_visit(link, request)
    return link


def record_visit(link, request):
    """F14 访问明细：只落 IP/UA 的 sha256 前缀，失败不影响分享访问"""
    try:
        import hashlib

        from core.utils import get_client_ip

        from .models import ShareVisit

        ip = get_client_ip(request) or ""
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:300]
        ShareVisit.objects.create(
            link=link,
            ip_hash=hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32] if ip else "",
            ua_hash=hashlib.sha256(ua.encode("utf-8")).hexdigest()[:32] if ua else "",
        )
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
