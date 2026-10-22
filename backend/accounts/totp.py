# -*- coding: utf-8 -*-
"""TOTP 双因素认证（RFC 6238 / RFC 4226）—— **纯标准库实现**。

只使用 Python 自带的 hmac / struct / base64 / hashlib / secrets / time /
urllib.parse，不引入任何第三方依赖，也不生成二维码（前端展示可复制的
Base32 密钥与 otpauth:// 链接，由用户手动录入验证器 App）。

约定：6 位数字、30 秒步长、SHA-1（与 Google Authenticator / Authy /
1Password 等主流验证器默认参数一致），校验时允许 ±1 个时间窗容差。
"""
import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

DIGITS = 6
PERIOD = 30          # 秒
ALGORITHM = "SHA1"
WINDOW = 1           # 校验容差窗口（前后各 N 个步长）
ISSUER = "全能协作平台"


def generate_secret() -> str:
    """生成 160 bit 随机密钥 → Base32（32 个字符，无填充，便于手动输入）"""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode(secret: str) -> bytes:
    """Base32 解码（自动补齐 = 填充，大小写不敏感）"""
    s = (secret or "").strip().replace(" ", "").replace("-", "")
    if not s:
        raise ValueError("密钥为空")
    s = s.upper()
    s += "=" * ((8 - len(s) % 8) % 8)
    return base64.b32decode(s, casefold=True)


def _hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    """HMAC-based 一次性密码（RFC 4226）"""
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f"{code:0{digits}d}"


def _counter(at: float = None) -> int:
    return int((time.time() if at is None else at) // PERIOD)


def totp(secret: str, at: float = None, offset: int = 0) -> str:
    """计算指定时刻（默认当前）的 6 位动态口令"""
    return _hotp(_decode(secret), _counter(at) + offset)


def verify(secret: str, code, window: int = WINDOW) -> bool:
    """校验动态口令：允许 ±window 个步长的时间漂移；比较使用常数时间算法"""
    if not secret or code is None:
        return False
    code = str(code).strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return False
    try:
        key = _decode(secret)
    except (binascii.Error, ValueError):
        return False
    now = _counter()
    # 容差窗口 ±window：历史上写成 range(-w, w+w+1)，前向多放一个步长，
    # 等于把验证码有效期延长到 90 秒，削弱防重放强度。
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(key, now + w), code):
            return True
    return False


def otpauth_url(secret: str, username: str, issuer: str = ISSUER) -> str:
    """生成验证器 App 可识别的 otpauth:// 链接（前端展示为可复制文本）"""
    label = urllib.parse.quote(f"{issuer}:{username}", safe=":")
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}&issuer={urllib.parse.quote(issuer)}"
        f"&digits={DIGITS}&period={PERIOD}&algorithm={ALGORITHM}"
    )
