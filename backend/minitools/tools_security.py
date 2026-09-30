# -*- coding: utf-8 -*-
"""minitools · 安全工具家族（10 个）。

去重：gen/password、gen/hash/hmac/crc32、validate/password-strength 已有；
这里做 XOR 密码、一次性密码本、凯撒暴力破解、端口表、DN 解析、策略校验等。
"""
import base64
import binascii
import os
import re

from .common import endpoint, ok, opt_bool, opt_num, opt_str, req_num, req_str


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


@endpoint()
def xor_cipher(request):
    """S01. XOR 加解密（对称，同一 key 加解密）。"""
    text = req_str(request, "text")
    key = req_str(request, "key")
    data = text.encode("utf-8")
    out = _xor_bytes(data, key.encode("utf-8"))
    mode = opt_str(request, "mode", "encrypt")
    if mode == "encrypt":
        return ok({"result": base64.b64encode(out).decode()})
    # decrypt: text 视为 base64
    raw = base64.b64decode(text)
    back = _xor_bytes(raw, key.encode("utf-8"))
    try:
        return ok({"result": back.decode("utf-8")})
    except UnicodeDecodeError:
        return ok({"result_hex": back.hex()})


@endpoint()
def one_time_pad(request):
    """S02. 一次性密码本：encrypt 生成随机密钥并返回密文；decrypt 用密钥还原。"""
    text = req_str(request, "text")
    mode = opt_str(request, "mode", "encrypt")
    if mode == "encrypt":
        data = text.encode("utf-8")
        key = os.urandom(len(data))
        out = _xor_bytes(data, key)
        return ok({"ciphertext": base64.b64encode(out).decode(),
                   "key": base64.b64encode(key).decode()})
    cipher = base64.b64decode(req_str(request, "ciphertext"))
    key = base64.b64decode(req_str(request, "key"))
    back = _xor_bytes(cipher, key)
    return ok({"plaintext": back.decode("utf-8", errors="replace")})


_EN_FREQ = "ETAOINSHRDLCUMWFGYPBVKJXQZ"


@endpoint()
def caesar_brute(request):
    """S03. 凯撒密码暴力破解：列出 25 种移位及评分。"""
    text = req_str(request, "text")
    results = []
    for shift in range(1, 26):
        out = []
        for ch in text:
            if "a" <= ch <= "z":
                out.append(chr((ord(ch) - 97 - shift) % 26 + 97))
            elif "A" <= ch <= "Z":
                out.append(chr((ord(ch) - 65 - shift) % 26 + 65))
            else:
                out.append(ch)
        s = "".join(out)
        score = sum(s.upper().count(c) * (26 - i) for i, c in enumerate(_EN_FREQ))
        results.append({"shift": shift, "score": score, "plaintext": s})
    results.sort(key=lambda x: -x["score"])
    return ok({"top": results[:5]})


_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP",
    69: "TFTP", 80: "HTTP", 110: "POP3", 123: "NTP", 143: "IMAP",
    161: "SNMP", 389: "LDAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS",
    587: "SMTP Submission", 636: "LDAPS", 993: "IMAPS", 995: "POP3S",
    1433: "MSSQL", 1521: "Oracle", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt", 9200: "Elasticsearch",
    27017: "MongoDB",
}


@endpoint()
def port_lookup(request):
    """S04. 常用端口号查表。"""
    port = int(req_num(request, "port", minimum=1, maximum=65535))
    return ok({"port": port, "service": _PORTS.get(port),
               "common_ports": [{"port": p, "service": s} for p, s in _PORTS.items()]})


@endpoint()
def cert_dn_parse(request):
    """S05. X.500 Distinguished Name 解析（如 CN=example.com,O=Org,C=US）。"""
    dn = req_str(request, "dn")
    parts = [p.strip() for p in dn.split(",") if p.strip()]
    parsed = []
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            parsed.append({"key": k.strip(), "value": v.strip()})
    return ok({"components": parsed})


@endpoint()
def hash_identifier(request):
    """S06. 通过长度/字符集猜测哈希类型。"""
    s = req_str(request, "hash").strip()
    n = len(s)
    kinds = []
    if n == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", s):
        kinds.append("MD5")
    if n == 40 and re.fullmatch(r"[0-9a-fA-F]{40}", s):
        kinds.append("SHA-1")
    if n == 56 and re.fullmatch(r"[0-9a-fA-F]{56}", s):
        kinds.append("SHA-224")
    if n == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", s):
        kinds.append("SHA-256")
    if n == 128 and re.fullmatch(r"[0-9a-fA-F]{128}", s):
        kinds.append("SHA-512")
    if n == 60 and s.startswith("$2"):
        kinds.append("bcrypt")
    if s.startswith("$argon2"):
        kinds.append("Argon2")
    if not kinds:
        kinds.append("未知")
    return ok({"length": n, "candidates": kinds})


@endpoint()
def password_policy(request):
    """S07. 按指定策略校验密码（长度/大小写/数字/符号要求）。"""
    pwd = req_str(request, "password")
    min_len = int(opt_num(request, "min_length", default=8, minimum=1, maximum=128))
    need_upper = opt_bool(request, "need_upper", True)
    need_lower = opt_bool(request, "need_lower", True)
    need_digit = opt_bool(request, "need_digit", True)
    need_symbol = opt_bool(request, "need_symbol", default=False)
    checks = {
        "length_ok": len(pwd) >= min_len,
        "upper_ok": bool(re.search(r"[A-Z]", pwd)) if need_upper else True,
        "lower_ok": bool(re.search(r"[a-z]", pwd)) if need_lower else True,
        "digit_ok": bool(re.search(r"[0-9]", pwd)) if need_digit else True,
        "symbol_ok": bool(re.search(r"[^A-Za-z0-9]", pwd)) if need_symbol else True,
    }
    passed = all(checks.values())
    return ok({"passed": passed, "checks": checks})


@endpoint()
def salt_gen(request):
    """S08. 生成随机盐值（hex/base64）。"""
    length = int(opt_num(request, "length", default=16, minimum=4, maximum=128))
    enc = opt_str(request, "encoding", "hex")
    raw = os.urandom(length)
    if enc == "base64":
        return ok({"salt": base64.b64encode(raw).decode(), "bytes": length})
    return ok({"salt": raw.hex(), "bytes": length})


@endpoint()
def basic_auth(request):
    """S09. HTTP Basic Auth 头生成/解析。"""
    mode = opt_str(request, "mode", "make")
    if mode == "make":
        user = req_str(request, "username")
        pwd = req_str(request, "password")
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        return ok({"header": f"Authorization: Basic {token}", "token": token})
    header = req_str(request, "header")
    m = re.search(r"Basic\s+([A-Za-z0-9+/=]+)", header)
    if not m:
        raise ValueError("不是有效的 Basic Authorization 头")
    decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
    user, _, pwd = decoded.partition(":")
    return ok({"username": user, "password": pwd})


@endpoint()
def cookie_parse(request):
    """S10. Cookie 字符串解析为键值对。"""
    raw = req_str(request, "cookie")
    pairs = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        pairs[k.strip()] = v.strip()
    return ok({"pairs": pairs, "count": len(pairs)})
