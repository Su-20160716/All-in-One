"""出站地址安全校验：阻断指向内网/环回/元数据地址的 Webhook。"""
import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse

from django.conf import settings


def host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def is_safe_outbound_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    # 本地开发允许回环地址，生产环境必须解析到公网地址
    if settings.DEBUG and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    return host_is_public(parsed.hostname)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Webhook 不跟随重定向，避免跳到内网地址绕过首次校验。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)
