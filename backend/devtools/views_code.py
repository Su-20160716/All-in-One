# -*- coding: utf-8 -*-
"""devtools · 工具家族接口：hash(5) token(6) code(6) diff(5) id(4) file(6) qr(3) webdev(6) db(5) = 46 个。

第三轮 S26（391–398）追加 +5：code/complexity、code/import-graph、diff/three-way、
id/snowflake-parse、db/sql-to-model（全部静态分析 / 纯计算，不执行用户代码、不连库）。
"""
import ast
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
    if len(a) > 20000 or len(b) > 20000:
        raise ValueError("两段文本各限 20000 字符（difflib 最坏为 O(n·m)）")
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


# =====================================================================
# 第三轮 S26（391–398）：静态分析 / 三方合并 / 雪花反解 / DDL 转模型
# =====================================================================

# 控制流节点：既用于圈复杂度，也用于嵌套深度
_CONTROL_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                  ast.With, ast.AsyncWith, ast.IfExp)
_MATCH_NODE = getattr(ast, "Match", None)


def _fn_body_nodes(fn):
    """函数自身（不含嵌套函数/类）的全部 AST 节点。"""
    out, stack = [], list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _fn_max_depth(fn):
    """控制结构最大嵌套深度（函数体顶层记为 0）。"""

    def walk(node, depth):
        inner = depth + 1 if isinstance(node, _CONTROL_NODES) else depth
        best = inner
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            best = max(best, walk(child, inner))
        return best

    return walk(fn, 0)


def _fn_branches(nodes):
    """圈复杂度近似：1 + 判定节点数（含 and/or、except、推导式 if）。"""
    cc = 1
    for n in nodes:
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Assert)):
            cc += 1
        elif isinstance(n, ast.Try):
            cc += max(1, len(n.handlers)) + (1 if n.orelse else 0) + (1 if n.finalbody else 0)
        elif isinstance(n, ast.BoolOp):
            cc += max(1, len(n.values) - 1)
        elif isinstance(n, ast.comprehension):
            cc += 1 + len(n.ifs)
        elif _MATCH_NODE is not None and isinstance(n, _MATCH_NODE):
            cc += max(1, len(n.cases))
    return cc


def _cc_grade(cc):
    if cc <= 5:
        return "低"
    if cc <= 10:
        return "中"
    if cc <= 20:
        return "高"
    return "极高"


def _collect_functions(tree):
    """按限定名收集函数（Class.method 形式，避免嵌套重复统计）。"""
    out = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((child, prefix + child.name, bool(prefix)))
                walk(child, prefix + child.name + ".")

    walk(tree, "")
    return out


@endpoint()
def code_complexity(request):
    """Python 圈复杂度与嵌套深度（ast 静态分析，绝不执行用户代码）。"""
    src = req_str(request, "code")
    language = opt_str(request, "language", "python").lower() or "python"
    if language not in ("python", "py", "python3"):
        raise ValueError("code/complexity 仅支持 Python 源码（language=python）")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise ValueError(f"Python 语法错误：第 {e.lineno} 行 {e.msg}")

    functions = []
    for node, qualname, _is_nested in _collect_functions(tree):
        own = _fn_body_nodes(node)
        cc = _fn_branches(own)
        depth = _fn_max_depth(node)
        args = list(getattr(node.args, "posonlyargs", [])) + list(node.args.args)
        first = args[0].arg if args else ""
        functions.append({
            "name": node.name,
            "qualified": qualname,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno) or node.lineno,
            "loc": max(1, (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1),
            "args": len(args),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "is_method": bool(first in ("self", "cls")),
            "branches": cc,
            "complexity": cc,
            "depth": depth,
            "grade": _cc_grade(cc),
        })
    functions.sort(key=lambda f: (-f["complexity"], -f["depth"], f["line"]))
    total = len(functions)
    avg = round(sum(f["complexity"] for f in functions) / total, 2) if total else 0
    hotspots = [f for f in functions if f["complexity"] > 10][:10]
    return ok({
        "language": "python",
        "functions": functions,
        "count": total,
        "classes": sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef)),
        "hotspots": hotspots,
        "summary": {
            "avg_complexity": avg,
            "max_complexity": max((f["complexity"] for f in functions), default=0),
            "max_depth": max((f["depth"] for f in functions), default=0),
            "high_risk": len(hotspots),
            "worst": functions[0]["name"] if functions else None,
        },
        "hint": "complexity = 1 + 判定节点数；depth 为控制结构最大嵌套层级",
    })


# ---------- 392 import 依赖图 ----------


def _module_imports(tree):
    """收集 import 目标（含相对导入的层级前缀）。"""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((a.name, node.lineno, a.asname or ""))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            prefix = "." * (node.level or 0)
            for a in node.names:
                if a.name == "*":
                    target = f"{prefix}{base}" if base else prefix
                else:
                    target = f"{prefix}{base}.{a.name}" if base else f"{prefix}{a.name}"
                found.append((target, node.lineno, a.asname or ""))
    return [f for f in found if f[0]]


@endpoint()
def code_import_graph(request):
    """import 依赖图：nodes/edges + 被引 Top10（供前端 DomainExplorer 渲染）。"""
    raw_files = p(request, "files")
    if raw_files is not None:
        if isinstance(raw_files, str):
            try:
                raw_files = json.loads(raw_files)
            except json.JSONDecodeError:
                raise ValueError("files 必须是 JSON 数组")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files 需为非空数组")
        if len(raw_files) > 50:
            raise ValueError("files 最多 50 个文件")
        items = []
        for i, f in enumerate(raw_files):
            if not isinstance(f, dict):
                raise ValueError("files 每项需为 {name, code}")
            name = str(f.get("name") or f"file{i}.py")
            items.append((name, str(f.get("code") or "")))
    else:
        code = req_str(request, "code")
        items = [(opt_str(request, "name", "", max_len=200) or "<code>.py", code)]

    def _module_of(filename):
        return filename.replace("\\", "/").lstrip("./").rsplit(".py", 1)[0].replace("/", ".")

    internal = {}
    parsed = []
    for name, code in items:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise ValueError(f"{name} 语法错误：第 {e.lineno} 行 {e.msg}")
        mod = _module_of(name)
        internal[mod] = name
        internal.setdefault(mod.split(".")[-1], name)
        parsed.append((name, mod, _module_imports(tree)))

    nodes, edges = {}, {}
    for name, mod, deps in parsed:
        nodes.setdefault(name, {"id": name, "type": "file", "in": 0, "out": 0})
        for target, lineno, alias in deps:
            nodes[name]["out"] += 1
            hit = internal.get(target) or internal.get(target.split(".")[0])
            if hit:
                tgt, kind = hit, "internal"
            else:
                tgt, kind = target, "external"
            nodes.setdefault(tgt, {"id": tgt, "type": "file" if kind == "internal" else "external",
                                   "in": 0, "out": 0})
            nodes[tgt]["in"] += 1
            key = (name, tgt)
            if key in edges:
                edges[key]["weight"] += 1
                edges[key]["lines"].append(lineno)
                if alias and alias not in edges[key]["names"]:
                    edges[key]["names"].append(alias)
            else:
                edges[key] = {"source": name, "target": tgt, "type": kind,
                              "weight": 1, "lines": [lineno], "names": [alias] if alias else []}

    ranked = sorted((n for n in nodes.values() if n["type"] != "file"),
                    key=lambda n: (-n["in"], n["id"]))
    return ok({
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "top10": [{"module": n["id"], "count": n["in"]} for n in ranked[:10]],
        "counts": {"files": len(parsed), "nodes": len(nodes), "edges": len(edges),
                   "external": sum(1 for n in nodes.values() if n["type"] == "external"),
                   "internal_edges": sum(1 for e in edges.values() if e["type"] == "internal")},
    })


# ---------- 394 三方合并 ----------


def _line_changes(base, other):
    """base→other 的非 equal 变更段（i1/i2 为 base 行区间）。"""
    import difflib

    sm = difflib.SequenceMatcher(None, base, other, autojunk=False)
    return [{"i1": i1, "i2": i2, "lines": other[j1:j2]}
            for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _touch(change, start, end):
    """变更段是否与当前合并簇相交（纯插入按点判断，避免误吞相邻变更）。"""
    if start == end:  # 当前簇是纯插入点：只和同点的插入合并
        return change["i1"] == change["i2"] == start
    if change["i1"] == change["i2"]:
        return start <= change["i1"] < end
    return change["i1"] < end and change["i2"] > start


def _side_segment(base, start, end, changes):
    """把单侧变更应用到 base[start:end] 上。"""
    out, pos = [], start
    for ch in changes:
        if ch["i1"] == ch["i2"]:
            if not (start <= ch["i1"] <= end):
                continue
            s = e = ch["i1"]
        else:
            s, e = max(ch["i1"], start), min(ch["i2"], end)
            if s >= e:
                continue
        if s > pos:
            out.extend(base[pos:s])
        out.extend(ch["lines"])
        pos = max(pos, e)
    if pos < end:
        out.extend(base[pos:end])
    return out


@endpoint()
def diff_three_way(request):
    """三方合并：base/ours/theirs → hunks（含冲突段）+ conflicts 计数。"""
    base = as_lines(req_str(request, "base"))
    ours = as_lines(req_str(request, "ours"))
    theirs = as_lines(req_str(request, "theirs"))
    oc = _line_changes(base, ours)
    tc = _line_changes(base, theirs)
    max_lines = max(len(base), len(ours), len(theirs))
    if max_lines > 5000:
        raise ValueError("单侧行数超过 5000 行上限")

    hunks, out, conflicts = [], [], 0
    pos = oi = ti = 0
    while oi < len(oc) or ti < len(tc):
        o = oc[oi] if oi < len(oc) else None
        t = tc[ti] if ti < len(tc) else None
        o_start, t_start = oi, ti
        if t is None or (o is not None and o["i1"] <= t["i1"]):
            start, end = o["i1"], o["i2"]
            oi += 1
        else:
            start, end = t["i1"], t["i2"]
            ti += 1
        grew = True
        while grew:
            grew = False
            while oi < len(oc) and _touch(oc[oi], start, end):
                end = max(end, oc[oi]["i2"])
                oi += 1
                grew = True
            while ti < len(tc) and _touch(tc[ti], start, end):
                end = max(end, tc[ti]["i2"])
                ti += 1
                grew = True
        ours_seg = _side_segment(base, start, end, oc[o_start:oi])
        theirs_seg = _side_segment(base, start, end, tc[t_start:ti])
        if oi == o_start:
            kind, seg = "theirs", theirs_seg
        elif ti == t_start:
            kind, seg = "ours", ours_seg
        elif ours_seg == theirs_seg:
            kind, seg = "both", ours_seg
        else:
            kind = "conflict"
            seg = ["<<<<<<< ours"] + ours_seg + ["======="] + theirs_seg + [">>>>>>> theirs"]
            conflicts += 1
        if start > pos:
            out.extend(base[pos:start])
        out.extend(seg)
        pos = end
        hunks.append({"type": kind, "base": [start, end],
                      "base_lines": base[start:end],
                      "ours": ours_seg, "theirs": theirs_seg, "result": seg})
    out.extend(base[pos:])

    return ok({"merged": "\n".join(out), "hunks": hunks, "conflicts": conflicts,
               "clean": conflicts == 0,
               "ours_changes": len(oc), "theirs_changes": len(tc),
               "base_lines": len(base)})


# ---------- 397 雪花 ID 反解 ----------


@endpoint()
def id_snowflake_parse(request):
    """雪花 ID 反解：时间戳 / worker / sequence（epoch、位数可配）。"""
    from datetime import datetime, timezone

    raw = req(request, "id")
    try:
        sid = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("id 必须是整数雪花 ID")
    if sid < 0:
        raise ValueError("雪花 ID 为无符号整数，不接受负数")
    if sid >= (1 << 64):
        raise ValueError("id 超出 64 位范围")
    epoch = int(req_num(request, "epoch", 1288834974657, minimum=0))
    worker_bits = int(req_num(request, "worker_bits", 5, minimum=1, maximum=20, integer=True))
    seq_bits = int(req_num(request, "sequence_bits", 12, minimum=1, maximum=22, integer=True))
    ts_bits = int(req_num(request, "timestamp_bits", 41, minimum=20, maximum=48, integer=True))
    dc_bits = 63 - ts_bits - worker_bits - seq_bits
    if dc_bits < 0:
        raise ValueError("timestamp_bits + worker_bits + sequence_bits 超过 63 位")

    seq = sid & ((1 << seq_bits) - 1)
    worker = (sid >> seq_bits) & ((1 << worker_bits) - 1)
    datacenter = (sid >> (seq_bits + worker_bits)) & ((1 << dc_bits) - 1) if dc_bits else 0
    delta = (sid >> (seq_bits + worker_bits + dc_bits)) & ((1 << ts_bits) - 1)
    ts_ms = epoch + delta

    zone = opt_str(request, "tz", "Asia/Shanghai")
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(zone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
        zone = "UTC"
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=tz)
        iso = dt.isoformat()
    except (OverflowError, OSError, ValueError):
        dt, iso = None, None

    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return ok({
        "id": str(sid),
        "epoch": epoch,
        "timestamp_ms": ts_ms,
        "delta_ms": delta,
        "datetime": iso,
        "utc": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat() if iso else None,
        "timezone": zone,
        "worker": worker,
        "datacenter": datacenter,
        "sequence": seq,
        "age_days": round((now_ms - ts_ms) / 86400000, 2) if iso else None,
        "in_future": ts_ms > now_ms,
        "bits": {"sign": 1, "timestamp": ts_bits, "datacenter": dc_bits,
                 "worker": worker_bits, "sequence": seq_bits},
    })


# ---------- 398 DDL → Django 模型 ----------

_SQL_SKIP = re.compile(r"^(PRIMARY\s+KEY|UNIQUE(\s+KEY|\s+INDEX)?|KEY|INDEX|CONSTRAINT|"
                       r"FOREIGN\s+KEY|CHECK|FULLTEXT|SPATIAL)\b", re.I)


def _split_columns(body):
    """按顶层逗号切分列定义（尊重括号与引号）。"""
    parts, cur, depth, quote = [], "", 0, ""
    for ch in body:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"`":
            quote = ch
            cur += ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur)
    return [x.strip() for x in parts if x.strip()]


def _django_field(sql_type, args, tail_upper=""):
    """SQL 类型 → (Django 字段表达式, 字段类型名)。"""
    t = re.sub(r"\s+", "", sql_type).upper()
    base = {"SERIAL": "AutoField", "BIGSERIAL": "BigAutoField", "SMALLSERIAL": "SmallAutoField"}
    if t in base:
        return f"models.{base[t]}()", base[t]
    if "AUTO_INCREMENT" in (tail_upper or ""):
        return "models.AutoField()", "AutoField"
    if t.startswith("BIGINT"):
        return "models.BigIntegerField()", "BigIntegerField"
    if t.startswith("SMALLINT") or t.startswith("TINYINT") or t.startswith("MEDIUMINT"):
        if args and str(args[0]) == "1":
            return "models.BooleanField()", "BooleanField"
        return "models.SmallIntegerField()", "SmallIntegerField"
    if t.startswith(("INT", "INTEGER")):
        return "models.IntegerField()", "IntegerField"
    if t.startswith(("DECIMAL", "NUMERIC", "MONEY")):
        md = args[0] if args else "10"
        dp = args[1] if len(args) > 1 else "2"
        return (f"models.DecimalField(max_digits={md}, decimal_places={dp})", "DecimalField")
    if t.startswith(("DOUBLE", "FLOAT", "REAL")):
        return "models.FloatField()", "FloatField"
    if t.startswith(("BOOL", "BIT")):
        return "models.BooleanField()", "BooleanField"
    if t.startswith(("DATETIME", "TIMESTAMP")):
        return "models.DateTimeField()", "DateTimeField"
    if t.startswith("DATE"):
        return "models.DateField()", "DateField"
    if t.startswith("TIME"):
        return "models.TimeField()", "TimeField"
    if t.startswith("YEAR"):
        return "models.SmallIntegerField()", "SmallIntegerField"
    if t.startswith(("JSON", "JSONB")):
        return "models.JSONField()", "JSONField"
    if t.startswith("UUID"):
        return "models.UUIDField()", "UUIDField"
    if t.startswith(("BLOB", "BINARY", "VARBINARY", "BYTEA")):
        return "models.BinaryField()", "BinaryField"
    if t.startswith(("TEXT", "CLOB", "LONGTEXT", "MEDIUMTEXT", "TINYTEXT")):
        return "models.TextField()", "TextField"
    if t.startswith(("VARCHAR", "CHAR", "NVARCHAR", "NCHAR", "ENUM", "SET", "STRING")):
        return f"models.CharField(max_length={args[0] if args else 255})", "CharField"
    return "models.CharField(max_length=255)", "CharField"


@endpoint()
def db_sql_to_model(request):
    """CREATE TABLE → Django models.py 字段片段（纯正则解析，不连库）。"""
    sql = req_str(request, "sql")
    m = re.search(r"CREATE\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                  r"([`\"\[\]\w.]+)\s*\(", sql, re.I)
    if not m:
        raise ValueError("未找到 CREATE TABLE 语句")
    table = m.group(1).strip('`"[]').split(".")[-1]
    override = opt_str(request, "table").strip()
    if override:
        table = override.strip('`"[]').split(".")[-1]
    open_at = m.end() - 1
    depth, body = 0, None
    for idx in range(open_at, len(sql)):
        if sql[idx] == "(":
            depth += 1
        elif sql[idx] == ")":
            depth -= 1
            if depth == 0:
                body = sql[open_at + 1:idx]
                break
    if body is None:
        raise ValueError("CREATE TABLE 括号未闭合")

    cls = "".join(w[:1].upper() + w[1:] for w in re.split(r"[_\W]+", table) if w) or "Model"
    if cls[0].isdigit():
        cls = "T" + cls
    fields, notes = [], []
    for raw in _split_columns(body):
        if _SQL_SKIP.match(raw):
            flat = re.sub(r"\s+", " ", raw)[:80]
            notes.append("跳过表级约束：" + flat)
            continue
        cm = re.match(r"^[`\"\[]?(\w+)[`\"\]]?\s+(.+)$", raw, re.S)
        if not cm:
            notes.append("无法解析：" + raw[:60])
            continue
        col, rest = cm.group(1), cm.group(2).strip()
        tm = re.match(r"^([A-Za-z]+(?:\s+(?:PRECISION|VARYING|UNSIGNED|ZEROFILL|"
                      r"WITH(?:OUT)?\s+TIME\s+ZONE))*)\s*(?:\(([^)]*)\))?(.*)$", rest, re.S | re.I)
        if not tm:
            notes.append("无法解析列 " + col + "：" + rest[:60])
            continue
        sql_type = re.sub(r"\s+", " ", tm.group(1)).strip()
        args = [a.strip() for a in (tm.group(2) or "").split(",") if a.strip()]
        tail = tm.group(3) or ""
        upper_tail = tail.upper()
        kw = ["verbose_name=" + json.dumps(c, ensure_ascii=False)
              for c in re.findall(r"COMMENT\s+'([^']*)'", tail, re.I)]
        expr, dtype = _django_field(sql_type, args, upper_tail)
        opts = []
        is_pk = "PRIMARY KEY" in upper_tail or dtype.endswith("AutoField")
        if is_pk:
            opts.append("primary_key=True")
        elif "NOT NULL" not in upper_tail:
            opts.append("null=True")
        if "UNIQUE" in upper_tail:
            opts.append("unique=True")
        dm = re.search(r"DEFAULT\s+('(?:[^']*)'|\"[^\"]*\"|[^\s,]+)", tail, re.I)
        if dm:
            dv = dm.group(1)
            if dv.upper() in ("CURRENT_TIMESTAMP", "NOW()", "GETDATE()"):
                opts.append("default=timezone.now")
            elif dv.startswith(("'", '"')):
                opts.append("default=" + json.dumps(dv[1:-1], ensure_ascii=False))
            elif re.fullmatch(r"-?\d+(\.\d+)?", dv):
                opts.append("default=" + dv)
            else:
                opts.append("default=" + json.dumps(dv))
        opts.extend(kw)
        if opts:
            inner = expr[:-1]
            sep = "" if inner.endswith("(") else ", "
            assign = inner + sep + ", ".join(opts) + ")"
        else:
            assign = expr
        fields.append({"name": col, "sql_type": sql_type, "django_type": dtype,
                       "assignment": assign, "args": args,
                       "primary_key": is_pk, "nullable": "null=True" in opts})
        if len(fields) >= 200:
            raise ValueError("列数超过 200，请拆分建表语句")

    if not fields:
        raise ValueError("未解析出任何列定义")
    lines = [f"class {cls}(models.Model):"]
    for f in fields:
        lines.append(f"    {f['name']} = {f['assignment']}")
    if table.lower() != cls.lower():
        lines += ["", "    class Meta:", f'        db_table = "{table}"']
    code = "\n".join(lines)
    return ok({"model": cls, "table": table, "code": code, "fields": fields,
               "field_count": len(fields), "notes": notes,
               "hint": "已自动生成 null/primary_key/unique/default/verbose_name，请人工复核枚举与索引"})


# 模块计数自检
CODE_FAMILY_COUNT = 5 + 6 + 6 + 5 + 4 + 6 + 3 + 6 + 5  # = 46（不含 S26 追加 5 个）
