# -*- coding: utf-8 -*-
"""minitools · 编码解码家族（25 个，编号 59-83）。"""
import base64
import binascii
import binascii as _b
import html
import json
import quopri
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter

from .common import endpoint, ok, opt_num, opt_str, req_str


# Base58 字母表（Bitcoin/Ripple 风格，去除 0OIl）
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58_encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    # 前导零字节映射为 '1'
    pad = 0
    for byte in b:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def _b58_decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + b


@endpoint()
def base64_codec(request):
    """59. Base64 编解码。direction: encode/decode。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": base64.b64encode(text.encode("utf-8")).decode("ascii")})
    if direction == "decode":
        try:
            return ok({"result": base64.b64decode(text).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"Base64 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def base64url_codec(request):
    """60. Base64URL 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")})
    if direction == "decode":
        padded = text + "=" * (-len(text) % 4)
        try:
            return ok({"result": base64.urlsafe_b64decode(padded).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"Base64URL 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def base58_codec(request):
    """61. Base58 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": _b58_encode(text.encode("utf-8"))})
    if direction == "decode":
        try:
            return ok({"result": _b58_decode(text).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"Base58 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def url_codec(request):
    """62. URL 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": urllib.parse.quote(text, safe="")})
    if direction == "decode":
        return ok({"result": urllib.parse.unquote(text)})
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def html_entity_codec(request):
    """63. HTML 实体编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": html.escape(text)})
    if direction == "decode":
        return ok({"result": html.unescape(text)})
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def unicode_codepoint(request):
    """64. Unicode 码点转换。"""
    text = req_str(request)
    codepoints = [f"U+{ord(ch):04X}" for ch in text]
    return ok({"codepoints": codepoints, "chars": list(text)})


@endpoint()
def utf8_bytes(request):
    """65. UTF-8 字节查看。"""
    text = req_str(request)
    b = text.encode("utf-8")
    return ok({"bytes_hex": b.hex(" "), "byte_count": len(b)})


@endpoint()
def hex_codec(request):
    """66. Hex 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": text.encode("utf-8").hex()})
    if direction == "decode":
        try:
            return ok({"result": bytes.fromhex(text.replace(" ", "")).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"Hex 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def binary_codec(request):
    """67. Binary 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": " ".join(format(b, "08b") for b in text.encode("utf-8"))})
    if direction == "decode":
        try:
            bits = text.replace(" ", "")
            chunks = [bits[i:i + 8] for i in range(0, len(bits), 8)]
            return ok({"result": bytes(int(c, 2) for c in chunks if len(c) == 8).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"Binary 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def octal_codec(request):
    """68. Octal 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": " ".join(format(b, "o") for b in text.encode("utf-8"))})
    if direction == "decode":
        try:
            parts = text.split()
            return ok({"result": bytes(int(p, 8) for p in parts).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"Octal 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")


_MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---",
    "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..",
}
_MORSE_REV = {v: k for k, v in _MORSE.items()}


@endpoint()
def morse(request):
    """69. 摩斯电码编解码。direction: encode/decode。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        out = []
        for word in text.upper().split():
            out.append(" ".join(_MORSE.get(ch, "") for ch in word))
        return ok({"result": " / ".join(out)})
    if direction == "decode":
        words = text.split(" / ")
        out = []
        for w in words:
            out.append("".join(_MORSE_REV.get(code, "") for code in w.split()))
        return ok({"result": " ".join(out)})
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def rot_n(request):
    """70. ROT-N 偏移（N 可配）。"""
    text = req_str(request)
    n = int(opt_num(request, "n", 13, minimum=0, maximum=25, integer=True))
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - ord("a") + n) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - ord("A") + n) % 26 + ord("A")))
        else:
            out.append(ch)
    return ok({"result": "".join(out)})


@endpoint()
def caesar(request):
    """71. 凯撒密码。direction: encode/decode。"""
    text = req_str(request)
    shift = int(opt_num(request, "shift", 3, integer=True))
    direction = opt_str(request, "direction", "encode")
    if direction == "decode":
        shift = -shift
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - ord("a") + shift) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - ord("A") + shift) % 26 + ord("A")))
        else:
            out.append(ch)
    return ok({"result": "".join(out)})


@endpoint()
def rail_fence(request):
    """72. 栅栏密码。direction: encode/decode。"""
    text = req_str(request)
    rails = int(opt_num(request, "rails", 3, minimum=2, maximum=20, integer=True))
    direction = opt_str(request, "direction", "encode")
    clean = re.sub(r"\s+", "", text)
    if direction == "encode":
        fence = [[] for _ in range(rails)]
        r, d = 0, 1
        for ch in clean:
            fence[r].append(ch)
            if r == 0:
                d = 1
            elif r == rails - 1:
                d = -1
            r += d
        return ok({"result": "".join("".join(row) for row in fence)})
    if direction == "decode":
        pattern = []
        r, d = 0, 1
        for _ in clean:
            pattern.append(r)
            if r == 0:
                d = 1
            elif r == rails - 1:
                d = -1
            r += d
        counts = Counter(pattern)
        idx = 0
        rows = {}
        for rail in range(rails):
            rows[rail] = list(clean[idx:idx + counts[rail]])
            idx += counts[rail]
        out = []
        pos = {0: 0}
        for p in pattern:
            out.append(rows[p][pos[p]])
            pos[p] += 1
        return ok({"result": "".join(out)})
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def vigenere(request):
    """73. Vigenere 密码。direction: encode/decode。"""
    text = req_str(request)
    key = req_str(request, "key")
    direction = opt_str(request, "direction", "encode")
    key = re.sub(r"[^A-Za-z]", "", key).lower()
    if not key:
        raise ValueError("key 必须包含字母")
    out = []
    ki = 0
    for ch in text:
        if ch.isalpha():
            shift = ord(key[ki % len(key)]) - ord("a")
            if direction == "decode":
                shift = -shift
            base = ord("a") if ch.islower() else ord("A")
            out.append(chr((ord(ch) - base + shift) % 26 + base))
            ki += 1
        else:
            out.append(ch)
    return ok({"result": "".join(out)})


@endpoint()
def atbash(request):
    """74. Atbash 密码。"""
    text = req_str(request)
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr(ord("z") - (ord(ch) - ord("a"))))
        elif "A" <= ch <= "Z":
            out.append(chr(ord("Z") - (ord(ch) - ord("A"))))
        else:
            out.append(ch)
    return ok({"result": "".join(out)})


_BACON = {"a": "aaaaa", "b": "aaaab", "c": "aaaba", "d": "aaabb", "e": "aabaa",
          "f": "aabab", "g": "aabba", "h": "aabbb", "i": "abaaa", "j": "abaab",
          "k": "ababa", "l": "ababb", "m": "abbaa", "n": "abbab", "o": "abbba",
          "p": "abbba", "q": "abbab", "r": "abaaa", "s": "aabaa", "t": "aaaba",
          "u": "abbaa", "v": "abab", "w": "abbab", "x": "aabab", "y": "aabba", "z": "aaabb"}


@endpoint()
def baconian(request):
    """75. Baconian 密码编解码。"""
    text = req_str(request).lower()
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        out = []
        for ch in text:
            if ch.isalpha():
                out.append(_BACON.get(ch, "aaaaa"))
        return ok({"result": " ".join(out)})
    if direction == "decode":
        blocks = text.split()
        rev = {v: k for k, v in _BACON.items()}
        return ok({"result": "".join(rev.get(b, "?") for b in blocks)})
    raise ValueError("direction 必须是 encode 或 decode")


# 常用汉字拼音首字母映射表（覆盖最常用 500 字左右）
_PINYIN_INITIAL = {
    "的": "d", "一": "y", "是": "s", "不": "b", "了": "l", "人": "r", "我": "w",
    "在": "z", "有": "y", "他": "t", "这": "z", "个": "g", "们": "m", "中": "z",
    "来": "l", "上": "s", "大": "d", "为": "w", "和": "h", "国": "g", "地": "d",
    "到": "d", "说": "s", "时": "s", "要": "y", "就": "j", "出": "c", "会": "h",
    "可": "k", "也": "y", "你": "n", "对": "d", "生": "s", "能": "n", "而": "e",
    "子": "z", "那": "n", "得": "d", "于": "y", "着": "z", "下": "x", "自": "z",
    "之": "z", "年": "n", "过": "g", "发": "f", "后": "h", "作": "z", "里": "l",
    "用": "y", "道": "d", "行": "x", "所": "s", "然": "r", "家": "j", "种": "z",
    "事": "s", "成": "c", "方": "f", "多": "d", "经": "j", "么": "m", "去": "q",
    "如": "r", "都": "d", "同": "t", "现": "x", "当": "d", "没": "m", "动": "d",
    "面": "m", "起": "q", "看": "k", "定": "d", "天": "t", "分": "f", "还": "h",
    "进": "j", "小": "x", "部": "b", "其": "q", "主": "z", "样": "y", "理": "l",
    "心": "x", "她": "t", "本": "b", "前": "q", "开": "k", "但": "d", "因": "y",
    "只": "z", "从": "c", "想": "x", "实": "s", "日": "r", "军": "j", "者": "z",
    "意": "y", "无": "w", "力": "l", "它": "t", "与": "y", "长": "c", "把": "b",
    "机": "j", "十": "s", "民": "m", "第": "d", "公": "g", "此": "c", "已": "y",
    "工": "g", "使": "s", "情": "q", "明": "m", "性": "x", "知": "z", "全": "q",
    "三": "s", "又": "y", "关": "g", "点": "d", "正": "z", "业": "y", "外": "w",
    "将": "j", "两": "l", "感": "g", "间": "j", "内": "n", "因": "y", "斯": "s",
    "文": "w", "序": "x", "她": "t", "树": "s", "听": "t", "业": "y", "但": "d",
    "爱": "a", "丰": "f", "坐": "z", "坚": "j", "写": "x", "软": "r", "找": "z",
    "读": "d", "站": "z", "完": "w", "展": "z", "包": "b", "王": "w", "长": "c",
    "车": "c", "记": "j", "口": "k", "水": "s", "手": "s", "气": "q", "门": "m",
    "光": "g", "电": "d", "高": "g", "打": "d", "最": "z", "问": "w", "身": "s",
    "命": "m", "写": "x", "红": "h", "节": "j", "真": "z", "花": "h", "表": "b",
    "更": "g", "水": "s", "路": "l", "打": "d", "呢": "n", "系": "x", "谁": "s",
    "克": "k", "基": "j", "麦": "m", "代": "d", "展": "z", "确": "q", "亲": "q",
    "室": "s", "照": "z", "审": "s", "革": "g", "众": "z", "总": "z", "举": "j",
    "布": "b", "单": "d", "血": "x", "压": "y", "据": "j", "色": "s", "身": "s",
    "头": "t", "月": "y", "花": "h", "多": "d", "尾": "w", "调": "t", "写": "x",
    "客": "k", "群": "q", "宽": "k", "输": "s", "风": "f", "紧": "j", "板": "b",
    "华": "h", "该": "g", "画": "h", "备": "b", "底": "d", "激": "j", "距": "j",
    "封": "f", "镜": "j", "增": "z", "弱": "r", "离": "l", "星": "x", "号": "h",
    "存": "c", "良": "l", "须": "x", "落": "l", "越": "y", "尽": "j", "级": "j",
    "级": "j", "轨": "g", "总": "z", "流": "l", "烟": "y", "毫": "h", "情": "q",
    "尝": "c", "诉": "s", "盖": "g", "豫": "y", "久": "j", "六": "l", "探": "t",
    "右": "y", "共": "g", "宽": "k", "触": "c", "诊": "z", "菲": "f", "露": "l",
    "抽": "c", "辉": "h", "货": "h", "乐": "l", "识": "s", "逐": "z", "疲": "p",
    "柴": "c", "灌": "g", "频": "p", "铺": "p", "疏": "s", "透": "t", "疑": "y",
    "避": "b", "翻": "f", "浮": "f", "甲": "j", "繁": "f", "秃": "t", "拖": "t",
}


@endpoint()
def pinyin_initials(request):
    """76. 拼音首字母（中文）。"""
    text = req_str(request)
    initials = []
    full = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            ini = _PINYIN_INITIAL.get(ch, "?")
            initials.append(ini)
            full.append(ini)
        elif ch.isalpha():
            initials.append(ch.lower())
            full.append(ch.lower())
    return ok({"initials": "".join(initials), "full_pinyin": " ".join(full)})


@endpoint()
def jwt_decode(request):
    """77. JWT 解码（不验证签名）。"""
    token = req_str(request, "token").strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT 格式应为 header.payload.signature")
    try:
        def _seg(s):
            padded = s + "=" * (-len(s) % 4)
            return json.loads(base64.urlsafe_b64decode(padded))
        return ok({"header": _seg(parts[0]), "payload": _seg(parts[1])})
    except Exception as e:
        raise ValueError(f"JWT 解码失败: {e}")


@endpoint()
def json_minify(request):
    """78. JSON 压缩/美化。mode: minify/beautify。"""
    text = req_str(request, "text")
    mode = opt_str(request, "mode", "beautify")
    try:
        data = json.loads(text)
    except Exception as e:
        raise ValueError(f"JSON 解析失败: {e}")
    if mode == "minify":
        return ok({"result": json.dumps(data, ensure_ascii=False, separators=(",", ":"))})
    if mode == "beautify":
        return ok({"result": json.dumps(data, ensure_ascii=False, indent=2)})
    raise ValueError("mode 必须是 minify 或 beautify")


@endpoint()
def json_to_yaml(request):
    """79. JSON 转 YAML（基础）。"""
    text = req_str(request, "json_text")
    try:
        data = json.loads(text)
    except Exception as e:
        raise ValueError(f"JSON 解析失败: {e}")
    lines = []

    def _dump(obj, indent=0):
        pad = "  " * indent
        if isinstance(obj, dict):
            if not obj:
                lines.append(pad + "{}")
                return
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}{k}:")
                    _dump(v, indent + 1)
                else:
                    lines.append(f"{pad}{k}: {_scalar(v)}")
        elif isinstance(obj, list):
            if not obj:
                lines.append(pad + "[]")
                return
            for item in obj:
                if isinstance(item, (dict, list)):
                    lines.append(f"{pad}-")
                    _dump(item, indent + 1)
                else:
                    lines.append(f"{pad}- {_scalar(item)}")
        else:
            lines.append(f"{pad}{_scalar(obj)}")

    def _scalar(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return v
        return str(v)

    _dump(data)
    return ok({"yaml": "\n".join(lines)})


@endpoint()
def xml_to_json(request):
    """80. XML 转 JSON（基础）。"""
    text = req_str(request, "xml_text")
    try:
        root = ET.fromstring(text)
    except Exception as e:
        raise ValueError(f"XML 解析失败: {e}")

    def _node(el):
        children = list(el)
        if not children:
            return el.text.strip() if el.text else ""
        d = {}
        for child in children:
            d.setdefault(child.tag, _node(child))
        return d

    return ok({"json": {root.tag: _node(root)}})


@endpoint()
def csv_to_json(request):
    """81. CSV 转 JSON。"""
    import csv
    import io
    text = req_str(request, "csv_text")
    delim = opt_str(request, "delimiter", ",")[:1]
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    return ok({"json": rows, "row_count": len(rows)})


@endpoint()
def data_url(request):
    """82. 数据 URL 编解码。direction: encode/decode。"""
    text = req_str(request, "text")
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        mime = opt_str(request, "mime", "text/plain")
        b = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return ok({"result": f"data:{mime};base64,{b}"})
    if direction == "decode":
        m = re.match(r"data:([^;]+);base64,(.+)", text)
        if not m:
            raise ValueError("不是合法的 data URL")
        return ok({"result": base64.b64decode(m.group(2)).decode("utf-8"), "mime": m.group(1)})
    raise ValueError("direction 必须是 encode 或 decode")


@endpoint()
def quoted_printable(request):
    """83. Quoted-Printable 编解码。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "encode")
    if direction == "encode":
        return ok({"result": quopri.encodestring(text.encode("utf-8")).decode("ascii")})
    if direction == "decode":
        try:
            return ok({"result": quopri.decodestring(text.encode("ascii")).decode("utf-8")})
        except Exception as e:
            raise ValueError(f"QP 解码失败: {e}")
    raise ValueError("direction 必须是 encode 或 decode")
