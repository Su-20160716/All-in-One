"""开发者工具箱：统一注册表 + 目录 + 运行入口。
所有工具为无副作用纯函数，POST /api/tools/run/ {tool, ...params} 或 /api/tools/<tool>/。
"""
import base64
import codecs
import colorsys
import csv
import hashlib
import html
import io
import json
import random
import re
import string
import time
import urllib.parse
import uuid
from datetime import datetime

from rest_framework.response import Response
from rest_framework.views import APIView


# ============================ 工具处理函数 ============================

def t_json_format(params):
    data = json.loads(params.get("text", ""))
    indent = int(params.get("indent", 2))
    if params.get("mode") == "minify":
        return {"result": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}
    return {"result": json.dumps(data, ensure_ascii=False, indent=indent)}


def t_timestamp(params):
    mode = params.get("mode", "now")
    if mode == "now":
        return {"timestamp": int(time.time()), "iso": datetime.now().isoformat()}
    if mode == "to_date":
        ts = int(params.get("timestamp", 0))
        return {"date": datetime.fromtimestamp(ts).isoformat()}
    date_str = params.get("date", "")
    dt = datetime.fromisoformat(date_str)
    return {"timestamp": int(dt.timestamp())}


def t_uuid(params):
    n = max(1, min(int(params.get("count", 1)), 100))
    upper = bool(params.get("upper"))
    out = [(str(uuid.uuid4()).upper() if upper else str(uuid.uuid4())) for _ in range(n)]
    return {"list": out, "result": "\n".join(out)}


def t_password(params):
    length = max(4, min(int(params.get("length", 12)), 64))
    n = max(1, min(int(params.get("count", 1)), 50))
    pools = string.ascii_lowercase + string.ascii_uppercase + string.digits
    if params.get("symbol", True):
        pools += "!@#$%^&*()-_=+"
    out = ["".join(random.choice(pools) for _ in range(length)) for _ in range(n)]
    return {"list": out, "result": "\n".join(out)}


def t_hash(params):
    text = params.get("text", "")
    alg = params.get("alg", "sha256")
    data = text.encode("utf-8")
    return {a: getattr(hashlib, a)(data).hexdigest() for a in ("md5", "sha1", "sha256", "sha512") if alg == "all" or a == alg}


def t_base64(params):
    text = params.get("text", "")
    if params.get("mode", "encode") == "encode":
        return {"result": base64.b64encode(text.encode("utf-8")).decode()}
    return {"result": base64.b64decode(text).decode("utf-8", errors="ignore")}


def t_url(params):
    text = params.get("text", "")
    if params.get("mode", "encode") == "encode":
        return {"result": urllib.parse.quote(text, safe="")}
    return {"result": urllib.parse.unquote(text)}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, round(c))) for c in rgb])


def t_color(params):
    base = params.get("hex", "#0ea5e9").lstrip("#")
    r, g, b = _hex_to_rgb(base)
    return {
        "hex": f"#{base.lower()}",
        "rgb": f"rgb({r},{g},{b})",
        "hsl": _rgb_to_hsl(r, g, b),
    }


def _rgb_to_hsl(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return f"hsl({round(h*360)},{round(s*100)}%,{round(l*100)}%)"


def t_csv_json(params):
    text = params.get("text", "")
    reader = csv.DictReader(io.StringIO(text))
    return {"result": json.dumps(list(reader), ensure_ascii=False, indent=2)}


def t_json_csv(params):
    data = params.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, list) or not data:
        raise ValueError("需要非空对象数组")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
    writer.writeheader()
    writer.writerows(data)
    return {"result": buf.getvalue()}


def t_qrcode(params):
    text = params.get("text", "")
    if not text:
        raise ValueError("请输入内容")
    try:
        import qrcode
    except ImportError:
        raise ValueError("服务器未安装 qrcode 库，无法生成二维码")
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


# ---------- 新增文本类 ----------

def t_text_case(params):
    text, mode = params.get("text", ""), params.get("mode", "upper")
    fn = {
        "upper": str.upper, "lower": str.lower, "title": str.title,
        "capitalize": str.capitalize, "swapcase": str.swapcase,
    }.get(mode, str.upper)
    return {"result": fn(text)}


def t_text_dedupe(params):
    lines = params.get("text", "").splitlines()
    seen, out = set(), []
    for ln in lines:
        key = ln if params.get("keep_space", True) else ln.strip()
        if key not in seen:
            seen.add(key)
            out.append(ln)
    removed = len(lines) - len(out)
    return {"result": "\n".join(out), "removed": removed}


def t_text_sort(params):
    lines = [l for l in params.get("text", "").splitlines()]
    reverse = params.get("order", "asc") == "desc"
    numeric = params.get("numeric", False)
    key = (lambda x: float(x.strip() or 0)) if numeric else None
    return {"result": "\n".join(sorted(lines, key=key, reverse=reverse))}


def t_text_trim(params):
    text = params.get("text", "")
    lines = text.splitlines()
    if params.get("remove_blank", True):
        lines = [l for l in lines if l.strip()]
    if params.get("strip_line", True):
        lines = [l.strip() for l in lines]
    return {"result": "\n".join(lines)}


def t_text_count(params):
    text = params.get("text", "")
    return {
        "chars": len(text), "chars_no_space": len(text.replace(" ", "").replace("\n", "")),
        "words": len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)),
        "lines": len(text.splitlines()) if text else 0,
        "cjk": len(re.findall(r"[\u4e00-\u9fff]", text)),
    }


def t_text_diff(params):
    import difflib
    a = params.get("a", "").splitlines()
    b = params.get("b", "").splitlines()
    diff = list(difflib.unified_diff(a, b, fromfile="A", tofile="B", lineterm=""))
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return {"diff": diff, "similarity": round(ratio * 100, 1)}


def t_text_reverse(params):
    text = params.get("text", "")
    mode = params.get("mode", "chars")
    if mode == "words":
        return {"result": " ".join(text.split()[::-1])}
    if mode == "lines":
        return {"result": "\n".join(text.splitlines()[::-1])}
    return {"result": text[::-1]}


def t_slugify(params):
    text = params.get("text", "").lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return {"result": text}


def t_markdown_plain(params):
    text = params.get("text", "")
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"[#>*`_~\-]{1,3}\s?", "", text)
    return {"result": text.strip()}


def t_regex_test(params):
    pattern, text = params.get("pattern", ""), params.get("text", "")
    flags = re.M | (re.I if params.get("ignorecase") else 0)
    matches = [{"match": m.group(0), "index": m.start()} for m in re.finditer(pattern, text, flags)]
    return {"matches": matches[:200], "count": len(matches)}


# ---------- 编码 / 转换 ----------

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--",
    "?": "..--..", "!": "-.-.--", "/": "-..-.", " ": "/",
}
MORSE_REV = {v: k for k, v in MORSE.items()}


def t_morse(params):
    text, mode = params.get("text", ""), params.get("mode", "encode")
    if mode == "encode":
        return {"result": " ".join(MORSE.get(ch.upper(), "") for ch in text)}
    return {"result": "".join(MORSE_REV.get(code, "") for code in text.split(" "))}


def t_rot13(params):
    return {"result": codecs.encode(params.get("text", ""), "rot_13")}


def t_html_entity(params):
    text = params.get("text", "")
    if params.get("mode", "encode") == "encode":
        return {"result": html.escape(text, quote=True)}
    return {"result": html.unescape(text)}


def t_number_base(params):
    value = params.get("value", "0")
    from_base = int(params.get("from_base", 10))
    num = int(str(value), from_base)
    return {"2": bin(num)[2:], "8": oct(num)[2:], "10": str(num), "16": hex(num)[2:].upper()}


def t_text_hex(params):
    text = params.get("text", "")
    if params.get("mode", "encode") == "encode":
        return {"result": text.encode("utf-8").hex()}
    return {"result": bytes.fromhex(text).decode("utf-8", errors="ignore")}


def t_text_binary(params):
    text = params.get("text", "")
    if params.get("mode", "encode") == "encode":
        return {"result": " ".join(format(b, "08b") for b in text.encode("utf-8"))}
    raw = text.replace(" ", "")
    return {"result": bytes(int(raw[i:i + 8], 2) for i in range(0, len(raw), 8)).decode("utf-8", errors="ignore")}


def t_jwt_decode(params):
    token = params.get("token", "").strip()
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("JWT 格式不正确")
    def dec(seg):
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    return {"header": dec(parts[0]), "payload": dec(parts[1])}


# ---------- 校验 / 生成 ----------

def t_password_strength(params):
    pwd = params.get("password", "")
    score = 0
    checks = {
        "长度≥8": len(pwd) >= 8, "含小写字母": bool(re.search(r"[a-z]", pwd)),
        "含大写字母": bool(re.search(r"[A-Z]", pwd)), "含数字": bool(re.search(r"\d", pwd)),
        "含特殊字符": bool(re.search(r"[^A-Za-z0-9]", pwd)), "长度≥12": len(pwd) >= 12,
    }
    score = sum(checks.values())
    level = ["极弱", "弱", "中", "强", "很强", "极强"][min(score, 5)]
    return {"score": score, "level": level, "checks": checks}


def t_luhn(params):
    number = re.sub(r"\D", "", params.get("number", ""))
    if not number:
        raise ValueError("请输入卡号")
    digits = [int(c) for c in number]
    checksum, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return {"valid": checksum % 10 == 0, "number": number}


WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CHECK = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]


def t_idcard(params):
    idc = params.get("idcard", "").strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", idc):
        return {"valid": False, "message": "格式不正确"}
    s = sum(int(idc[i]) * WEIGHTS[i] for i in range(17))
    valid = ID_CHECK[s % 11] == idc[-1]
    birth = idc[6:14]
    gender = "男" if int(idc[16]) % 2 else "女"
    return {"valid": valid, "birthday": f"{birth[:4]}-{birth[4:6]}-{birth[6:]}", "gender": gender if valid else ""}


def t_random_number(params):
    lo = int(params.get("min", 0))
    hi = int(params.get("max", 100))
    n = max(1, min(int(params.get("count", 1)), 500))
    out = [random.randint(min(lo, hi), max(lo, hi)) for _ in range(n)]
    return {"list": out, "result": ", ".join(map(str, out))}


def t_date_diff(params):
    d1 = datetime.fromisoformat(params.get("start", ""))
    d2 = datetime.fromisoformat(params.get("end", ""))
    delta = d2 - d1
    return {"days": delta.days, "seconds": int(delta.total_seconds()), "weeks": round(delta.days / 7, 2)}


LENGTH = {"mm": 1, "cm": 0.1, "m": 0.001, "km": 0.000001, "inch": 0.0393701, "ft": 0.00328084, "mile": 6.2137e-7}
WEIGHT = {"mg": 1000, "g": 1, "kg": 0.001, "t": 0.000001, "lb": 0.00220462, "oz": 0.035274}


def t_unit_convert(params):
    value = float(params.get("value", 0))
    table_name = params.get("table", "length")
    table = WEIGHT if table_name == "weight" else LENGTH
    frm, to = params.get("from", "m"), params.get("to", "cm")
    if table_name == "temperature":
        c = value if frm == "c" else (value - 32) * 5 / 9 if frm == "f" else value - 273.15
        out = c if to == "c" else c * 9 / 5 + 32 if to == "f" else c + 273.15
        return {"result": round(out, 4)}
    base = value / table[frm]
    return {"result": round(base * table[to], 6)}


def t_color_palette(params):
    base = params.get("hex", "#0ea5e9").lstrip("#")
    r, g, b = [int(base[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    palette = []
    for dl in (-0.3, -0.15, 0, 0.15, 0.3):
        rr, gg, bb = colorsys.hls_to_rgb(h, max(0, min(1, l + dl)), s)
        palette.append(_rgb_to_hex((rr * 255, gg * 255, bb * 255)))
    comp_h = (h + 0.5) % 1
    cr, cg, cb = colorsys.hls_to_rgb(comp_h, l, s)
    return {"palette": palette, "complement": _rgb_to_hex((cr * 255, cg * 255, cb * 255))}


# ============================ 工具目录 ============================
# key: (分类, 名称, 说明, 处理函数)
TOOL_REGISTRY = {
    "json-format": ("JSON", "JSON 格式化", "美化/压缩 JSON", t_json_format),
    "timestamp": ("时间", "时间戳转换", "时间戳与日期互转", t_timestamp),
    "uuid": ("生成", "UUID 生成", "批量生成 UUID", t_uuid),
    "password": ("生成", "随机密码", "生成强随机密码", t_password),
    "hash": ("加密", "哈希计算", "MD5/SHA 系列摘要", t_hash),
    "base64": ("编码", "Base64", "Base64 编解码", t_base64),
    "url": ("编码", "URL 编解码", "URL 百分号编解码", t_url),
    "color": ("颜色", "颜色转换", "HEX/RGB/HSL 互转", t_color),
    "color-palette": ("颜色", "配色生成", "由基色生成同色系与互补色", t_color_palette),
    "csv-json": ("转换", "CSV 转 JSON", "CSV 文本转 JSON 数组", t_csv_json),
    "json-csv": ("转换", "JSON 转 CSV", "JSON 数组转 CSV", t_json_csv),
    "qrcode": ("图像", "二维码生成", "文本生成二维码", t_qrcode),
    "text-case": ("文本", "大小写转换", "大写/小写/首字母大写等", t_text_case),
    "text-dedupe": ("文本", "行去重", "按行去除重复", t_text_dedupe),
    "text-sort": ("文本", "行排序", "按字典序/数值排序", t_text_sort),
    "text-trim": ("文本", "文本清理", "去空行与首尾空白", t_text_trim),
    "text-count": ("文本", "文本统计", "字符/单词/行数统计", t_text_count),
    "text-diff": ("文本", "文本对比", "两段文本差异与相似度", t_text_diff),
    "text-reverse": ("文本", "文本反转", "字符/单词/行反转", t_text_reverse),
    "slugify": ("文本", "Slug 生成", "生成 URL 友好标识", t_slugify),
    "markdown-plain": ("文本", "Markdown 转纯文本", "去除 Markdown 标记", t_markdown_plain),
    "regex-test": ("文本", "正则测试", "正则匹配并列出命中", t_regex_test),
    "morse": ("编码", "摩斯电码", "摩斯电码编解码", t_morse),
    "rot13": ("编码", "ROT13", "凯撒位移编解码", t_rot13),
    "html-entity": ("编码", "HTML 实体", "HTML 实体编解码", t_html_entity),
    "number-base": ("编码", "进制转换", "二/八/十/十六进制互转", t_number_base),
    "text-hex": ("编码", "文本↔十六进制", "文本与 HEX 互转", t_text_hex),
    "text-binary": ("编码", "文本↔二进制", "文本与二进制互转", t_text_binary),
    "jwt-decode": ("编码", "JWT 解析", "解析 JWT 头部与载荷", t_jwt_decode),
    "password-strength": ("校验", "密码强度", "评估密码强度", t_password_strength),
    "luhn": ("校验", "银行卡校验", "Luhn 算法校验卡号", t_luhn),
    "idcard": ("校验", "身份证校验", "身份证校验位与信息", t_idcard),
    "random-number": ("生成", "随机数", "区间随机数批量生成", t_random_number),
    "date-diff": ("时间", "日期相差", "计算两个日期差值", t_date_diff),
    "unit-convert": ("换算", "单位换算", "长度/重量/温度换算", t_unit_convert),
}


class ToolCatalogView(APIView):
    """工具目录（按分类分组）"""

    def get(self, request):
        categories = {}
        for key, (cat, name, desc, _) in TOOL_REGISTRY.items():
            categories.setdefault(cat, []).append({"key": key, "name": name, "desc": desc})
        return Response({"total": len(TOOL_REGISTRY), "categories": categories})


class ToolRunView(APIView):
    """统一运行入口：POST /api/tools/run/ 带 tool，或 /api/tools/<tool>/"""

    def _run(self, tool, params):
        entry = TOOL_REGISTRY.get(tool)
        if not entry:
            return Response({"message": f"未知工具: {tool}"}, status=404)
        try:
            result = entry[3](params or {})
            return Response({"tool": tool, "result": result})
        except json.JSONDecodeError as e:
            return Response({"message": f"JSON 解析失败：{e}"}, status=400)
        except (ValueError, KeyError, TypeError) as e:
            return Response({"message": f"输入有误：{e}"}, status=400)

    def post(self, request, tool=None):
        params = dict(request.data)
        tool = tool or params.pop("tool", None)
        # MultiValueDict 兼容
        params = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in params.items()}
        return self._run(tool, params)
