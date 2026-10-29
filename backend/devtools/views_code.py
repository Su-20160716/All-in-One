# -*- coding: utf-8 -*-
"""devtools · 工具家族接口：hash(5) token(6) code(6) diff(5) id(4) file(6) qr(3) webdev(6) db(5) = 46 个。"""
import base64
import binascii
import hashlib
import hmac as hmac_mod
import io
import json
import math
import re
import secrets
import struct
import time
import zipfile
import zlib
from urllib.parse import parse_qsl, urlencode, urlparse

from .common import (as_lines, endpoint, fail, ok, opt_bool, opt_num, opt_str, p,
                     req, req_list, req_num, req_str)
from .data import (CODE39_TABLE, HTTP_HEADERS, HTTP_STATUS, MAGIC_SIGNATURES,
                   MIME_TABLE)

# =====================================================================
# hash 哈希扩展（5）
# =====================================================================


@endpoint()
def hash_crc32(request):
    """CRC32 校验（返回十进制与十六进制）。"""
    text = req_str(request)
    v = zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF
    return ok({"crc32": v, "hex": f"{v:08x}"})


@endpoint()
def hash_adler32(request):
    """Adler-32 校验。"""
    text = req_str(request)
    v = zlib.adler32(text.encode("utf-8")) & 0xFFFFFFFF
    return ok({"adler32": v, "hex": f"{v:08x}"})


@endpoint()
def hash_sha3(request):
    """SHA3 家族（224/256/384/512）与 shake 摘要。"""
    text = req_str(request)
    data = text.encode("utf-8")
    return ok({
        "sha3_224": hashlib.sha3_224(data).hexdigest(),
        "sha3_256": hashlib.sha3_256(data).hexdigest(),
        "sha3_384": hashlib.sha3_384(data).hexdigest(),
        "sha3_512": hashlib.sha3_512(data).hexdigest(),
        "shake_128_32": hashlib.shake_128(data).hexdigest(32),
    })


@endpoint()
def hash_hmac(request):
    """HMAC-SHA256/1/512 签名。"""
    text = req_str(request)
    key = req(request, "key")
    algo = opt_str(request, "algo", "sha256")
    fn = {"sha256": hashlib.sha256, "sha1": hashlib.sha1, "sha512": hashlib.sha512, "md5": hashlib.md5}.get(algo)
    if not fn:
        raise ValueError("algo 支持 sha256/sha1/sha512/md5")
    key_b = key.encode("utf-8")
    if re.fullmatch(r"[0-9a-fA-F]+", str(key)) and len(str(key)) % 2 == 0:
        key_b = binascii.unhexlify(str(key))
    return ok({"algo": algo, "hex": hmac_mod.new(key_b, text.encode("utf-8"), fn).hexdigest(),
               "base64": base64.b64encode(hmac_mod.new(key_b, text.encode("utf-8"), fn).digest()).decode()})


@endpoint()
def hash_blake2(request):
    """BLAKE2b/BLAKE2s 摘要（可带 key，支持可变长度）。"""
    text = req_str(request)
    key = opt_str(request, "key", "")
    digest_size = int(opt_num(request, "size", 32, minimum=1, maximum=64) or 32)
    kb = key.encode("utf-8") if key else b""
    return ok({
        "blake2b": hashlib.blake2b(text.encode("utf-8"), key=kb, digest_size=digest_size).hexdigest(),
        "blake2s": hashlib.blake2s(text.encode("utf-8"), key=kb, digest_size=min(digest_size, 32)).hexdigest(),
        "digest_size": digest_size,
    })


# =====================================================================
# token 令牌与密钥（6）
# =====================================================================


@endpoint()
def token_jwt_sign(request):
    """JWT 签发（HS256，PyJWT；payload 直接内嵌）。"""
    import jwt as pyjwt

    payload = p(request, "payload") or {}
    secret = req(request, "secret")
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象")
    exp_seconds = int(opt_num(request, "exp_seconds", 3600, minimum=1, maximum=30 * 86400) or 3600)
    body = dict(payload)
    body["iat"] = int(time.time())
    body["exp"] = int(time.time()) + exp_seconds
    token = pyjwt.encode(body, secret, algorithm="HS256")
    return ok({"token": token, "exp": body["exp"], "alg": "HS256"})


@endpoint()
def token_jwt_verify(request):
    """JWT 校验（HS256，验证签名与有效期，返回 payload）。"""
    import jwt as pyjwt

    token = req_str(request)
    secret = req(request, "secret")
    try:
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return ok({"valid": True, "payload": payload})
    except pyjwt.ExpiredSignatureError:
        return ok({"valid": False, "reason": "token 已过期"})
    except pyjwt.InvalidSignatureError:
        return ok({"valid": False, "reason": "签名不匹配"})
    except pyjwt.PyJWTError as e:
        return ok({"valid": False, "reason": f"{type(e).__name__}: {e}"})


@endpoint()
def token_apikey(request):
    """API Key 生成（前缀 + 高熵随机段，附校验位）。"""
    prefix = opt_str(request, "prefix", "sk").strip().rstrip("_") or "sk"
    count = int(opt_num(request, "count", 1, minimum=1, maximum=50) or 1)
    keys = []
    for _ in range(count):
        body = secrets.token_urlsafe(24)
        chk = sum(ord(c) for c in body) % 97
        keys.append(f"{prefix}_{body}{chk:02d}")
    return ok({"keys": keys})


_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def _totp_at(secret_b32: str, t: int, digits=6, period=30) -> str:
    pad = "=" * ((8 - len(secret_b32.replace("=", "")) % 8) % 8)
    key = base64.b32decode(secret_b32.replace(" ", "").upper() + pad)
    counter = struct.pack(">Q", t // period)
    digest = hmac_mod.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


@endpoint()
def token_otp(request):
    """TOTP 动态口令（RFC 6238）：生成当前码 / 校验（±1 窗口容错）。"""
    action = opt_str(request, "action", "now")
    if action == "seed":
        raw = secrets.token_bytes(20)
        seed = base64.b32encode(raw).decode().rstrip("=")
        return ok({"seed": seed, "digits": 6, "period": 30,
                   "otpauth": f"otpauth://totp/Platform:{int(time.time())}?secret={seed}&digits=6&period=30"})
    seed = req(request, "seed")
    code = _totp_at(str(seed), int(time.time()))
    result = {"action": action, "now_code": code, "period": 30}
    if action == "verify":
        given = str(req(request, "code")).strip()
        t = int(time.time())
        ok_windows = [w for w in (-1, 0, 1) if _totp_at(str(seed), t + w * 30) == given]
        result["valid"] = bool(ok_windows)
        result["window_offset"] = ok_windows[0] if ok_windows else None
    return ok(result)


@endpoint()
def token_nanoid(request):
    """NanoID 风格短 ID（可指定字母表与长度）。"""
    alphabet = opt_str(request, "alphabet", "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-")
    size = int(opt_num(request, "size", 21, minimum=4, maximum=128) or 21)
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100) or 1)
    ids = ["".join(secrets.choice(alphabet) for _ in range(size)) for _ in range(count)]
    return ok({"ids": ids, "alphabet_size": len(set(alphabet))})


@endpoint()
def token_password_audit(request):
    """密码强度审计：熵值、组成、社工词检查、离线爆破时长估算。"""
    pwd = req_str(request, "password")
    pool = 0
    if re.search(r"[a-z]", pwd):
        pool += 26
    if re.search(r"[A-Z]", pwd):
        pool += 26
    if re.search(r"\d", pwd):
        pool += 10
    if re.search(r"[^a-zA-Z0-9]", pwd):
        pool += 33
    entropy = len(pwd) * (pool.bit_length() if pool else 0)
    # 每秒 1e10 次尝试的离线破解估算；用对数算，避免超长密码把
    # `pool ** len(pwd)` 变成天文数字后在转 float 时抛 OverflowError
    if pool and pwd:
        log_seconds = len(pwd) * math.log10(pool) - math.log10(2) - 10
        seconds = 10 ** log_seconds if log_seconds < 18 else float("inf")
    else:
        seconds = 0.0
    units = [("年", 31536000), ("天", 86400), ("小时", 3600), ("分钟", 60), ("秒", 1)]
    if math.isinf(seconds):
        human = "超过已知宇宙年龄"
    else:
        human = "瞬间"
        for name, sec in units:
            if seconds >= sec:
                human = f"{seconds / sec:.1f} {name}"
                break
    weak_words = ["password", "123456", "qwerty", "admin", "abc123", "iloveyou", "111111", "000000"]
    flagged = [w for w in weak_words if w in pwd.lower()]
    score = max(0, min(100, int(entropy * 1.8) - 30 * len(flagged)))
    return ok({
        "length": len(pwd), "pool": pool, "entropy_bits": entropy, "score": score,
        "crack_time": human, "flagged_common": flagged,
        "levels": ["极弱", "弱", "一般", "强", "极强"][min(score // 25, 4)],
        "suggestions": (["增加长度到 12 位以上"] if len(pwd) < 12 else []) +
                       (["混入大小写/数字/符号"] if pool < 80 else []) +
                       ([f"避开常见词: {flagged}"] if flagged else []) or ["看起来不错"],
    })


# =====================================================================
# code 代码工具（6）
# =====================================================================


@endpoint()
def code_minify_css(request):
    """CSS 压缩（去注释/空白/末尾分号）。"""
    css = req_str(request, "css")
    out = re.sub(r"/\*[\s\S]*?\*/", "", css)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s*([{}:;,>])\s*", r"\1", out)
    out = re.sub(r";}", "}", out)
    return ok({"result": out.strip(), "saved": len(css) - len(out), "orig": len(css), "min": len(out)})


@endpoint()
def code_beautify(request):
    """通用缩进美化（{}[] 括号驱动，适用于 JS/JSON/CSS/Java 风格）。"""
    src = req_str(request)
    indent_size = int(opt_num(request, "indent", 2, minimum=1, maximum=8) or 2)
    out, depth = [], 0
    cur = ""
    in_str, quote = False, ""
    i = 0
    while i < len(src):
        ch = src[i]
        if in_str:
            cur += ch
            if ch == quote and src[i - 1] != "\\":
                in_str = False
        elif ch in "\"'":
            in_str, quote, cur = True, ch, cur + ch
        elif ch in "{[":
            cur += ch
            out.append(" " * (depth * indent_size) + cur.strip())
            depth += 1
            cur = ""
        elif ch in "}]":
            if cur.strip():
                out.append(" " * (depth * indent_size) + cur.strip())
            depth = max(0, depth - 1)
            close = ch
            if i + 1 < len(src) and src[i + 1] == ";":
                close += ";"
                i += 1
            out.append(" " * (depth * indent_size) + close)
            cur = ""
        elif ch in ";":
            cur += ch
            if cur.strip():
                out.append(" " * (depth * indent_size) + cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(" " * (depth * indent_size) + cur.strip())
    return ok({"result": "\n".join(out)})


_LANG_HINTS = [
    ("python", (r"def \w+\(", r"import \w+$", r"print\(", r"__name__", r"elif ")),
    ("javascript", (r"function \w+\(", r"=>", r"console\.log", r"const \w+ =", r"let \w+")),
    ("java", (r"public class", r"System\.out", r"void main", r"private \w+")),
    ("go", (r"func \w+\(", r"fmt\.", r"package main", r":= ")),
    ("sql", (r"SELECT .+ FROM", r"\bJOIN\b", r"\bWHERE\b", r"INSERT INTO")),
    ("html", (r"<html", r"<div", r"</\w+>")),
    ("css", (r"\{[\s\S]*:[^;]+;", r"@media", r"px")),
    ("json", (r'^\s*[\{\[]', r'"\w+"\s*:')),
]


@endpoint()
def code_lang_detect(request):
    """代码语言猜测（启发式打分）。"""
    src = req_str(request)
    scores = {}
    for lang, patterns in _LANG_HINTS:
        s = sum(2 if re.search(pat, src, re.M | re.I) else 0 for pat in patterns)
        if s:
            scores[lang] = s
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return ok({"language": ranked[0][0] if ranked else "unknown",
               "confidence_scores": dict(ranked), "total_chars": len(src)})


@endpoint()
def code_loc(request):
    """代码行统计：总行/代码/注释/空行（识别 # // /* */ <!-- -->）。"""
    text = req_str(request)
    total = code = blank = comment = 0
    in_block = False
    block_style = ""
    for ln in as_lines(text):
        total += 1
        s = ln.strip()
        if not s:
            blank += 1
            continue
        if in_block:
            comment += 1
            if block_style in ("*/", "-->") and ((block_style == "*/" and "*/" in s) or (block_style == "-->" and "-->" in s)):
                in_block = False
            continue
        if s.startswith(("//", "#")) and not s.startswith("#!"):
            comment += 1
        elif s.startswith("/*"):
            comment += 1
            in_block, block_style = "*/" not in s, "*/"
        elif s.startswith("<!--"):
            comment += 1
            in_block, block_style = "-->" not in s, "-->"
        else:
            code += 1
    return ok({"total": total, "code": code, "comment": comment, "blank": blank,
               "comment_ratio": round(comment / total, 3) if total else 0})


@endpoint()
def code_todo_scan(request):
    """TODO/FIXME/XXX/HACK 扫描（带行号与标签）。"""
    text = req_str(request)
    tags = ("TODO", "FIXME", "XXX", "HACK", "NOTE")
    found = []
    for i, ln in enumerate(as_lines(text), 1):
        for tag in tags:
            m = re.search(rf"\b{tag}\b[:：]?\s*(.*)", ln)
            if m:
                found.append({"line": i, "tag": tag, "note": m.group(1).strip()[:120], "context": ln.strip()[:160]})
                break
    by = {}
    for f in found:
        by[f["tag"]] = by.get(f["tag"], 0) + 1
    return ok({"items": found, "total": len(found), "by_tag": by})


@endpoint()
def code_gitmoji(request):
    """gitmoji 速查（全部或按关键词搜索）。"""
    from .data import GITMOJI
    kw = opt_str(request, "keyword").lower()
    items = [{"emoji": e.strip(), "code": c, "meaning": m} for e, c, m in GITMOJI
             if not kw or kw in m or kw in c or kw in e.strip()]
    return ok({"items": items, "count": len(items)})


# =====================================================================
# diff 差异对比（5）
# =====================================================================


@endpoint()
def diff_text(request):
    """文本 unified diff（可选带行号上下文）。"""
    import difflib

    a = req_str(request, "a")
    b = req_str(request, "b")
    n = int(opt_num(request, "context", 3, minimum=0, maximum=20) or 3)
    a_lines, b_lines = as_lines(a), as_lines(b)
    diff = list(difflib.unified_diff(a_lines, b_lines, fromfile=opt_str(request, "from", "a"),
                                     tofile=opt_str(request, "to", "b"), lineterm="", n=n))
    adds = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    dels = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return ok({"diff": "\n".join(diff), "added": adds, "removed": dels, "changed": adds + dels > 0})


@endpoint()
def diff_word(request):
    """词级差异（中文按字、英文按词）。"""
    import difflib

    a, b = req_str(request, "a"), req_str(request, "b")
    at = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+|\S", a)
    bt = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+|\S", b)
    sm = difflib.SequenceMatcher(None, at, bt)
    ops = [{"op": tag, "a_text": "".join(at[i1:i2]), "b_text": "".join(bt[j1:j2])}
           for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
    return ok({"changes": ops, "ratio": round(sm.ratio(), 4), "changed": len(ops) > 0})


@endpoint()
def diff_json(request):
    """JSON 深度差异：报告新增/删除/变更的路径。"""
    a = req(request, "a")
    b = req(request, "b")
    if isinstance(a, str):
        a = json.loads(a)
    if isinstance(b, str):
        b = json.loads(b)
    changes = []

    def walk(x, y, path):
        if type(x) is not type(y) and not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            changes.append({"path": path, "type": "changed", "old": x, "new": y})
        elif isinstance(x, dict) and isinstance(y, dict):
            for k in x.keys() | y.keys():
                if k not in y:
                    changes.append({"path": f"{path}.{k}", "type": "removed", "old": x[k], "new": None})
                elif k not in x:
                    changes.append({"path": f"{path}.{k}", "type": "added", "old": None, "new": y[k]})
                else:
                    walk(x[k], y[k], f"{path}.{k}")
        elif isinstance(x, list) and isinstance(y, list):
            for i in range(max(len(x), len(y))):
                if i >= len(x):
                    changes.append({"path": f"{path}[{i}]", "type": "added", "old": None, "new": y[i]})
                elif i >= len(y):
                    changes.append({"path": f"{path}[{i}]", "type": "removed", "old": x[i], "new": None})
                else:
                    walk(x[i], y[i], f"{path}[{i}]")
        elif x != y:
            changes.append({"path": path, "type": "changed", "old": x, "new": y})

    walk(a, b, "$")
    return ok({"changes": changes, "identical": not changes, "count": len(changes)})


@endpoint()
def diff_similarity(request):
    """相似度（SequenceMatcher 比率 + 行级 Jaccard）。"""
    a, b = req_str(request, "a"), req_str(request, "b")
    import difflib

    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    sa, sb = set(a.split()), set(b.split())
    jac = len(sa & sb) / len(sa | sb) if sa | sb else 1.0
    return ok({"similarity": round(ratio, 4), "word_jaccard": round(jac, 4),
               "len_a": len(a), "len_b": len(b)})


@endpoint()
def diff_patch(request):
    """将 unified diff 应用回原文（difflib.restore 语义）。"""
    import difflib

    patch = req_str(request, "patch")
    lines = as_lines(patch)
    try:
        target = [ln for ln in lines if ln.startswith(("---", "+++", "@@")) or True]
        side_a = [ln[1:] for ln in lines if ln.startswith("-") and not ln.startswith("---")]
        side_b = [ln[1:] for ln in lines if ln.startswith("+") and not ln.startswith("+++")]
        # 使用 ndiff 的还原逻辑：把 +/-/空 行合并为序列
        merged = []
        i = 0
        diff_body = [ln for ln in lines if not ln.startswith(("---", "+++", "@@"))]
        for ln in diff_body:
            if ln.startswith("? "):
                continue
            merged.append(ln)
        restored = difflib.restore(merged, 2)
        return ok({"result": "\n".join(restored), "hint": "从 diff 的 + 侧（新文本）还原"})
    except Exception as e:  # noqa: BLE001
        return ok({"error": f"patch 解析失败: {e}", "hint": "需要标准的 unified diff 输入"})


# =====================================================================
# id 标识符（4）
# =====================================================================


@endpoint()
def id_uuid_multi(request):
    """批量 UUID v4 + 短格式（去横线/前 8 位/base64）。"""
    import uuid

    n = int(opt_num(request, "count", 5, minimum=1, maximum=100) or 5)
    items = []
    for _ in range(n):
        u = str(uuid.uuid4())
        items.append({"uuid": u, "compact": u.replace("-", ""), "short": u[:8],
                      "b64": base64.urlsafe_b64encode(uuid.UUID(u).bytes).decode().rstrip("=")})
    return ok({"items": items, "count": n})


_ALPHABET_SHORT = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@endpoint()
def id_shortid(request):
    """短 ID 生成（时间前缀 + 随机段，近似有序）。"""
    n = int(opt_num(request, "count", 5, minimum=1, maximum=100) or 5)
    ts = int(time.time() * 1000)
    ids = []
    for i in range(n):
        tail = "".join(secrets.choice(_ALPHABET_SHORT) for _ in range(8))
        ids.append(f"{ts + i:x}{tail}")
    return ok({"ids": ids})


def _isbn10_check(digits9):
    s = sum((10 - i) * int(d) for i, d in enumerate(digits9))
    check = (11 - s % 11) % 11
    return "X" if check == 10 else str(check)


def _ean13_check(digits12):
    s = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits12))
    return str((10 - s % 10) % 10)


@endpoint()
def id_checksum(request):
    """校验码：ISBN-10 / ISBN-13 / EAN-13 校验与补位。"""
    code = re.sub(r"[^0-9Xx]", "", req_str(request, "code")).upper()
    out = {"code": code}
    if len(code) == 10:
        out["kind"] = "ISBN-10"
        if code[:9].isdigit():
            expect = _isbn10_check(code[:9])
            out["valid"] = expect == code[9]
            out["expected_check"] = expect
        else:
            out["valid"] = False
            out["error"] = "前 9 位必须为数字"
    elif len(code) == 13 and code.isdigit():
        out["kind"] = "ISBN-13/EAN-13"
        expect = _ean13_check(code[:12])
        out["valid"] = expect == code[12]
        out["expected_check"] = expect
    elif len(code) in (9, 12):
        out["kind"] = "ISBN-10" if len(code) == 9 else "ISBN-13/EAN-13"
        out["valid"] = None
        out["completed"] = code + (_isbn10_check(code) if len(code) == 9 else _ean13_check(code))
    else:
        raise ValueError("请提供 9/10/12/13 位数字（ISBN-10 或 EAN-13）")
    return ok(out)


_CARD_PREFIX = {"visa": "4", "mastercard": "55", "amex": "37", "unionpay": "62", "jcb": "35"}


def _luhn_sum(digits):
    s, alt = 0, False
    for d in reversed(digits):
        v = int(d)
        if alt:
            v *= 2
            if v > 9:
                v -= 9
        s += v
        alt = not alt
    return s


@endpoint()
def id_luhn_gen(request):
    """生成 Luhn 合法的测试卡号（visa/mastercard/amex/unionpay/jcb，仅供测试）。"""
    brand = opt_str(request, "brand", "visa").lower()
    if brand not in _CARD_PREFIX:
        raise ValueError(f"brand 支持 {list(_CARD_PREFIX)}")
    n = int(opt_num(request, "count", 1, minimum=1, maximum=20) or 1)
    length = 15 if brand == "amex" else 16
    cards = []
    for _ in range(n):
        body = _CARD_PREFIX[brand] + "".join(secrets.choice("0123456789") for _ in range(length - 1 - len(_CARD_PREFIX[brand])))
        for chk in range(10):
            if _luhn_sum(body + str(chk)) % 10 == 0:
                cards.append(body + str(chk))
                break
    return ok({"cards": cards, "brand": brand, "disclaimer": "仅供联调测试使用，不对应任何真实账户"})


# =====================================================================
# file 文件工具（6）
# =====================================================================


@endpoint()
def file_data_url(request):
    """Data URL ↔ base64 互转 + 元信息提取。"""
    mode = opt_str(request, "mode", "parse")
    if mode == "build":
        mime = opt_str(request, "mime", "text/plain")
        raw = req_str(request, "content")
        b64 = base64.b64encode(raw.encode("utf-8")).decode()
        return ok({"data_url": f"data:{mime};base64,{b64}", "mime": mime, "bytes": len(raw.encode("utf-8"))})
    du = req_str(request, "data_url")
    m = re.match(r"^data:([^;,]+)?(;base64)?,([\s\S]+)$", du.strip())
    if not m:
        raise ValueError("不是合法的 data URL")
    mime, is_b64, payload = m.group(1) or "text/plain", bool(m.group(2)), m.group(3)
    if is_b64:
        raw = base64.b64decode(payload)
        try:
            preview = raw[:200].decode("utf-8")
        except UnicodeDecodeError:
            preview = f"<二进制 {len(raw)} 字节>"
        return ok({"mime": mime, "encoding": "base64", "bytes": len(raw), "text_preview": preview})
    from urllib.parse import unquote

    return ok({"mime": mime, "encoding": "url", "text": unquote(payload)})


@endpoint()
def file_csv_clean(request):
    """CSV 清洗：去空行/去重/裁剪空白/转置/列删除。"""
    text = req_str(request, "csv")
    rows = [ln.split(opt_str(request, "delimiter", ",")) for ln in as_lines(text) if ln.strip()]
    rows = [[c.strip() for c in r] for r in rows]
    if opt_bool(request, "dedupe"):
        seen, uniq = set(), []
        for r in rows:
            k = tuple(r)
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        rows = uniq
    if opt_bool(request, "drop_empty_rows"):
        rows = [r for r in rows if any(c for c in r)]
    drop_cols = p(request, "drop_columns") or []
    if drop_cols:
        keep = [i for i in range(max(len(r) for r in rows)) if i not in drop_cols]
        rows = [[r[i] if i < len(r) else "" for i in keep] for r in rows]
    if opt_bool(request, "transpose"):
        rows = [list(col) for col in zip(*rows)] if rows else []
    return ok({"rows": rows, "count": len(rows), "cols": max((len(r) for r in rows), default=0)})


@endpoint()
def file_magic(request):
    """魔数识别文件类型（base64 或 hex 输入）。"""
    raw_in = req_str(request, "data").strip()
    try:
        raw = base64.b64decode(raw_in, validate=True)
    except Exception:
        try:
            raw = binascii.unhexlify(re.sub(r"[\s,]", "", raw_in))
        except Exception:
            raise ValueError("data 需为 base64 或 hex 编码的文件头")
    head = raw[:64]
    sig, ext, name = "", "unknown", "未知类型"
    for pattern, e, n in MAGIC_SIGNATURES:
        if head.startswith(pattern):
            sig, ext, name = pattern.decode("latin1", errors="replace"), e, n
            break
    if ext == "riff-family" and len(raw) > 12:
        sub = raw[8:12].decode("latin1", errors="replace")
        ext = {"WAVE": "wav", "AVI ": "avi", "WEBP": "webp"}.get(sub, "riff")
        name = f"RIFF/{sub.strip()} 文件"
    return ok({"ext": ext, "name": name, "signature_hex": raw[:16].hex(), "size_hint_bytes": None})


@endpoint()
def file_zip_list(request):
    """列出 base64 编码 zip 包内条目（大小/压缩率/CRC）。"""
    b64 = req_str(request, "zip_b64").strip()
    try:
        raw = base64.b64decode(re.sub(r"\s", "", b64), validate=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"zip_b64 不是合法 base64: {e}")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError("不是合法的 zip 文件")
    items = []
    for info in zf.infolist():
        ratio = round(1 - info.compress_size / info.file_size, 3) if info.file_size else 0
        items.append({"name": info.filename, "size": info.file_size, "compressed": info.compress_size,
                      "ratio": ratio, "crc32": f"{info.CRC:08x}", "is_dir": info.is_dir()})
    return ok({"entries": items, "count": len(items), "total_size": sum(i["size"] for i in items)})


@endpoint()
def file_encoding_detect(request):
    """文本编码探测：BOM → UTF-8 校验 → GBK 试解码启发式。"""
    text_b64 = req_str(request, "data_b64").strip()
    raw = base64.b64decode(re.sub(r"\s", "", text_b64), validate=True)
    if raw.startswith(b"\xef\xbb\xbf"):
        return ok({"encoding": "utf-8-sig", "confidence": 1.0, "bom": True})
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ok({"encoding": "utf-16", "confidence": 1.0, "bom": True})
    try:
        raw.decode("utf-8")
        return ok({"encoding": "utf-8", "confidence": 0.95, "bom": False})
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gbk")
        return ok({"encoding": "gbk", "confidence": 0.7, "bom": False, "hint": "中文环境常见"})
    except UnicodeDecodeError:
        return ok({"encoding": "binary/unknown", "confidence": 0.3, "bom": False})


@endpoint()
def file_line_endings(request):
    """换行符统计与规范化（CRLF/LF/CR）。"""
    text = req_str(request)
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    target = opt_str(request, "to", "")
    result = text
    if target == "lf":
        result = text.replace("\r\n", "\n").replace("\r", "\n")
    elif target == "crlf":
        result = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    elif target == "cr":
        result = text.replace("\r\n", "\n").replace("\n", "\r")
    return ok({"stats": {"crlf": crlf, "lf": lf, "cr": cr},
               "dominant": max([("crlf", crlf), ("lf", lf), ("cr", cr)], key=lambda x: x[1])[0] if text else "none",
               "result": result if target else None})


# =====================================================================
# qr / barcode（3）
# =====================================================================


@endpoint()
def qr_generate(request):
    """二维码生成（依赖 qrcode 库；未安装时返回结构化降级提示）。"""
    text = req_str(request)
    try:
        import qrcode  # noqa
    except ImportError:
        return ok({"available": False, "provider": "none",
                   "degraded": True,
                   "message": "服务器未安装 qrcode 库（pip install qrcode[pil]），此接口为可降级适配器，未生成图片。",
                   "hint": "可使用平台既有工具 /api/tools/qr-code/ 的能力，或安装依赖后重试。"})
    try:
        from qrcode.image.svg import SvgPathImage

        img = qrcode.make(str(text), image_factory=SvgPathImage, box_size=12, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return ok({"available": True, "provider": "qrcode", "svg": buf.getvalue().decode()})
    except Exception as e:  # noqa: BLE001
        return fail(f"二维码生成失败: {e}", status=422)


@endpoint()
def qr_info(request):
    """二维码能力探测与参数说明（可降级适配器元信息）。"""
    try:
        import qrcode  # noqa

        installed = True
    except ImportError:
        installed = False
    return ok({"library_installed": installed, "provider": "qrcode" if installed else "none",
               "params": {"text": "要编码的内容", "box_size": "模块像素大小", "border": "留白边框"},
               "endpoints": ["/api/devtools/qr/generate/", "/api/devtools/qr/barcode39/"]})


@endpoint()
def barcode_code39(request):
    """Code39 条形码 → SVG（纯 Python 实现，无外部依赖）。"""
    content = req_str(request, "content").upper()
    if not re.fullmatch(r"[0-9A-Z\-. $/+%]+", content):
        raise ValueError("Code39 仅支持 0-9 A-Z 空格 与 - . $ / + %")
    from .data import CODE39_TABLE

    bits = "".join(CODE39_TABLE[ch] for ch in "*" + content + "*")
    bars, x = [], 0.0
    narrow = 2
    for i, b in enumerate(bits):
        width = narrow * (2.6 if (i % 6 >= 3) else 1) if False else narrow  # 宽窄条简化：按表内 1/0 已编码
        if b == "1":
            bars.append((x, narrow))
        x += narrow
    rects = "".join(f'<rect x="{px}" y="0" width="{w}" height="60"/>' for px, w in bars)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x + 4} 84" width="{x + 4}" height="84">'
           f'<rect width="100%" height="100%" fill="white"/>{rects}'
           f'<text x="{x / 2 + 2}" y="78" text-anchor="middle" font-size="12" font-family="monospace">{content}</text></svg>')
    return ok({"svg": svg, "chars": len(content) + 2, "modules": len(bits)})


# =====================================================================
# webdev 前端/接口助手（6）
# =====================================================================


@endpoint()
def web_curl_parse(request):
    """curl 命令解析 → 结构化请求 + python requests 代码。"""
    cmd = req_str(request, "curl").strip().replace("\\\n", " ")
    method, url, headers, data = "GET", "", {}, None
    tokens = re.findall(r'"([^"]*)"|\'([^\']*)\'|(\S+)', cmd)
    toks = [t[0] or t[1] or t[2] for t in tokens]
    i = 0
    while i < len(toks):
        t = toks[i]
        low = t.lower()
        if low in ("-x", "--request") and i + 1 < len(toks):
            method = toks[i + 1].upper()
            i += 2
        elif low in ("-h", "--header") and i + 1 < len(toks):
            k, _, v = toks[i + 1].partition(":")
            headers[k.strip()] = v.strip()
            i += 2
        elif low in ("-d", "--data", "--data-raw", "--data-binary") and i + 1 < len(toks):
            data = toks[i + 1]
            if method == "GET":
                method = "POST"
            i += 2
        elif low in ("-f", "--form") and i + 1 < len(toks):
            data = toks[i + 1]
            method = "POST"
            i += 2
        elif not t.startswith("-") and not url:
            url = t
            i += 1
        else:
            i += 1
    parsed = urlparse(url) if url else None
    code = f'import requests\n\nresp = requests.request(\n    "{method}",\n    "{url}",\n    headers={headers!r},\n'
    if data:
        code += f"    data={data!r},\n"
    code += ")\nprint(resp.status_code, resp.text)"
    return ok({"method": method, "url": url, "headers": headers, "data": data,
               "host": parsed.netloc if parsed else "", "scheme": parsed.scheme if parsed else "",
               "python_code": code})


def _jsonpath(obj, path):
    """$.a.b[0].c[*] 查询。"""
    tokens = re.findall(r"\.([A-Za-z_]\w*)|\[(\*|-?\d+)\]", path.replace("$", "", 1))
    cur = [obj]
    for name, idx in tokens:
        nxt = []
        for item in cur:
            if name:
                if isinstance(item, dict) and name in item:
                    nxt.append(item[name])
            else:
                if isinstance(item, list):
                    if idx == "*":
                        nxt.extend(item)
                    else:
                        j = int(idx)
                        if -len(item) <= j < len(item):
                            nxt.append(item[j])
        cur = nxt
    return cur


@endpoint()
def web_jsonpath(request):
    """JSONPath 迷你实现：$.store.book[*].title 风格查询。"""
    data = req(request, "data")
    if isinstance(data, str):
        data = json.loads(data)
    path = req_str(request, "path")
    hits = _jsonpath(data, path)
    return ok({"found": hits, "count": len(hits), "path": path})


@endpoint()
def web_dotpath(request):
    """嵌套取值/设值：a.b.0.c 点路径操作。"""
    mode = opt_str(request, "mode", "get")
    path = req_str(request, "path")
    data = req(request, "data")
    if isinstance(data, str):
        data = json.loads(data)
    if mode == "get":
        cur = data
        for part in path.split("."):
            if isinstance(cur, list):
                cur = cur[int(part)]
            elif isinstance(cur, dict):
                cur = cur[part]
            else:
                raise ValueError(f"路径 {path} 在 {type(cur).__name__} 上不可继续下钻")
        return ok({"value": cur})
    value = p(request, "value")
    cur = data
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur[int(part)] if isinstance(cur, list) else cur.setdefault(part, {})
        cur = nxt
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value
    return ok({"result": data})


@endpoint()
def web_http_status(request):
    """HTTP 状态码速查（全部或按码查询）。"""
    code = p(request, "code")
    if code is not None:
        c = int(code)
        if c not in HTTP_STATUS:
            raise ValueError(f"未收录状态码 {c}")
        return ok({"code": c, "meaning": HTTP_STATUS[c]})
    cls = opt_str(request, "class", "")
    items = [{"code": c, "meaning": m} for c, m in sorted(HTTP_STATUS.items())
             if not cls or str(c).startswith(cls)]
    return ok({"items": items, "count": len(items)})


@endpoint()
def web_headers(request):
    """常见 HTTP 头速查与解析（粘贴原始头即可结构化）。"""
    raw = opt_str(request, "raw")
    if raw:
        parsed = {}
        for ln in as_lines(raw):
            if ":" in ln:
                k, v = ln.split(":", 1)
                parsed[k.strip()] = v.strip()
        annotated = {k: {"value": v, "reference": HTTP_HEADERS.get(k.lower(), "")} for k, v in parsed.items()}
        return ok({"parsed": parsed, "annotated": annotated, "count": len(parsed)})
    kw = opt_str(request, "keyword").lower()
    items = [{"header": k, "reference": v} for k, v in sorted(HTTP_HEADERS.items()) if not kw or kw in k or kw in v]
    return ok({"items": items, "count": len(items)})


@endpoint()
def web_querystring(request):
    """Query String 解析/构建（保留数组键）。"""
    mode = opt_str(request, "mode", "parse")
    if mode == "build":
        params = p(request, "params") or {}
        if not isinstance(params, dict):
            raise ValueError("params 必须是对象")
        pairs = []
        for k, v in params.items():
            if isinstance(v, list):
                pairs.extend((k, str(x)) for x in v)
            else:
                pairs.append((k, str(v)))
        return ok({"query": urlencode(pairs)})
    qs = req_str(request, "query").lstrip("?")
    out = {}
    for k, v in parse_qsl(qs, keep_blank_values=True):
        out.setdefault(k, []).append(v)
    return ok({"parsed": {k: (v[0] if len(v) == 1 else v) for k, v in out.items()},
               "raw_pairs": out, "count": sum(len(v) for v in out.values())})


# =====================================================================
# db SQL 助手（5）
# =====================================================================

_SQL_KEYWORDS = ["SELECT", "FROM", "WHERE", "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM",
                 "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "OUTER JOIN", "ON", "GROUP BY",
                 "ORDER BY", "HAVING", "LIMIT", "OFFSET", "UNION", "UNION ALL", "AS", "AND", "OR",
                 "NOT", "IN", "IS NULL", "LIKE", "BETWEEN", "DISTINCT", "COUNT", "SUM", "AVG",
                 "MIN", "MAX", "CREATE TABLE", "ALTER TABLE", "DROP TABLE", "WITH", "CASE", "WHEN",
                 "THEN", "ELSE", "END", "ASC", "DESC"]


@endpoint()
def db_sql_format(request):
    """SQL 美化：关键字大写 + 主子句换行缩进。"""
    sql = req_str(request, "sql").strip().rstrip(";")
    major = ["SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT", "UNION", "UNION ALL", "INSERT INTO", "UPDATE", "DELETE FROM", "SET", "VALUES"]
    upper = sql
    for kw in sorted(_SQL_KEYWORDS, key=len, reverse=True):
        upper = re.sub(rf"\b{re.escape(kw)}\b", kw, upper, flags=re.I)
    out, indent = [], 0
    tokens = re.split(r"(\b(?:%s)\b)" % "|".join(major), upper, flags=re.I)
    cur = ""
    for tok in tokens:
        if tok.upper() in major:
            if cur.strip():
                out.append(("  " * indent) + cur.strip())
            indent = 1 if tok.upper() in ("SELECT",) else indent
            if tok.upper() in ("FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "VALUES", "SET"):
                indent = 1
            cur = tok + " "
        else:
            cur += tok
    if cur.strip():
        out.append(("  " * indent) + cur.strip())
    return ok({"sql": "\n".join(out).replace(" ,", ","), "lines": len(out)})


@endpoint()
def db_sql_minify(request):
    """SQL 压缩：去注释/折叠空白/去尾分号。"""
    sql = req_str(request, "sql")
    out = re.sub(r"--[^\n]*", "", sql)
    out = re.sub(r"/\*[\s\S]*?\*/", "", out)
    out = re.sub(r"\s+", " ", out).strip().rstrip(";")
    return ok({"sql": out, "saved": len(sql) - len(out)})


@endpoint()
def db_where_builder(request):
    """结构化条件 → 参数化 WHERE 子句。"""
    rules = req_list(request, "rules")
    glue = opt_str(request, "glue", "AND").upper()
    if glue not in ("AND", "OR"):
        raise ValueError("glue 只支持 AND/OR")
    clauses, params = [], []
    for r in rules:
        if not isinstance(r, dict):
            raise ValueError("rules 每项需为 {field, op, value}")
        field, op = str(r.get("field", "")), str(r.get("op", "=")).lower()
        value = r.get("value")
        ops = {"=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<=",
               "like": "LIKE", "in": "IN", "not in": "NOT IN", "is": "IS", "between": "BETWEEN"}
        if op not in ops:
            raise ValueError(f"不支持的操作符: {op}")
        if op in ("in", "not in"):
            vals = value if isinstance(value, list) else [value]
            clauses.append(f"{field} {ops[op]} ({', '.join(['%s'] * len(vals))})")
            params.extend(vals)
        elif op == "is":
            clauses.append(f"{field} IS {str(value).upper()}")
        elif op == "between":
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("between 需要 [low, high]")
            clauses.append(f"{field} BETWEEN %s AND %s")
            params.extend(list(value))
        elif op == "like":
            clauses.append(f"{field} LIKE %s")
            params.append(f"%{value}%")
        else:
            clauses.append(f"{field} {ops[op]} %s")
            params.append(value)
    where = f" {glue} ".join(clauses) if clauses else "1=1"
    return ok({"where": where, "params": params, "full": f"SELECT * FROM t WHERE {where};"})


@endpoint()
def db_join_explain(request):
    """JOIN 类型解释 + 示例 SQL + 行为示意。"""
    from .data import SQL_JOINS
    kind = opt_str(request, "kind", "all")
    if kind in SQL_JOINS:
        name, desc, example = SQL_JOINS[kind]
        return ok({"kind": kind, "name": name, "description": desc, "example": example})
    return ok({"items": [{"kind": k, "name": v[0], "description": v[1], "example": v[2]} for k, v in SQL_JOINS.items()]})


@endpoint()
def db_epoch(request):
    """时间戳多格式转换：epoch ↔ ISO/本地/UTC/相对时间。"""
    from datetime import datetime, timezone

    raw = req(request, "value")
    zone = opt_str(request, "tz", "Asia/Shanghai")
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(zone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    if isinstance(raw, str) and not re.fullmatch(r"-?\d+(\.\d+)?", raw.strip()):
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        epoch = int(dt.timestamp())
    else:
        num = float(raw)
        epoch = int(num if num < 1e12 else num / 1000)  # 毫秒自动降级为秒
    dt_utc = datetime.fromtimestamp(epoch, tz=timezone.utc)
    dt_local = datetime.fromtimestamp(epoch, tz=tz)
    now = time.time()
    delta = now - epoch
    relative = ("未来 " if delta < 0 else "") + (
        f"{abs(delta) / 86400:.1f} 天" if abs(delta) >= 86400 else
        f"{abs(delta) / 3600:.1f} 小时" if abs(delta) >= 3600 else
        f"{abs(delta) / 60:.1f} 分钟" if abs(delta) >= 60 else f"{abs(delta):.0f} 秒")
    relative += ("后" if delta < 0 else "前")
    return ok({"epoch_seconds": epoch, "epoch_ms": epoch * 1000,
               "iso_utc": dt_utc.isoformat(), "iso_local": dt_local.isoformat(),
               "timezone": zone, "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt_local.weekday()],
               "relative": relative, "now_epoch": int(now)})


# 模块计数自检
CODE_FAMILY_COUNT = 5 + 6 + 6 + 5 + 4 + 6 + 3 + 6 + 5  # = 46
