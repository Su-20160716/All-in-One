# -*- coding: utf-8 -*-
"""minitools · 数据格式家族（8 个）。

去重：encode 有 json-minify/json-to-yaml/xml-to-json/csv-to-json；
devtools/json 有 flatten/unflatten/merge；dataintel/transform 有 pivot/sample；
这里做 INI/TOML、脱敏、HTML->文本、XML 美化、JSON Schema 推断等。
"""
import io
import json
import re
import tomllib
from xml.dom import minidom
from xml.etree import ElementTree as ET

from .common import endpoint, ok, opt_bool, opt_str, req_str


@endpoint()
def ini_codec(request):
    """FMT01. INI 解析/生成。"""
    mode = opt_str(request, "mode", "parse")
    if mode == "parse":
        text = req_str(request, "text")
        data = {}
        section = "_default"
        for line in text.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            m = re.match(r"^\[(.+)\]$", line)
            if m:
                section = m.group(1).strip()
                data.setdefault(section, {})
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                data.setdefault(section, {})[k.strip()] = v.strip()
        return ok({"data": data})
    obj = json.loads(req_str(request, "obj"))
    lines = []
    for section, kv in obj.items():
        lines.append(f"[{section}]")
        for k, v in kv.items():
            lines.append(f"{k} = {v}")
        lines.append("")
    return ok({"ini": "\n".join(lines)})


@endpoint()
def toml_codec(request):
    """FMT02. TOML 解析（tomllib）/ 生成（dict -> toml 文本）。"""
    mode = opt_str(request, "mode", "parse")
    if mode == "parse":
        text = req_str(request, "text")
        data = tomllib.loads(text)
        return ok({"data": data})
    obj = json.loads(req_str(request, "obj"))
    lines = []
    for k, v in obj.items():
        if isinstance(v, dict):
            lines.append(f"[{k}]")
            for k2, v2 in v.items():
                lines.append(f"{k2} = {json.dumps(v2)}")
        else:
            lines.append(f"{k} = {json.dumps(v)}")
    return ok({"toml": "\n".join(lines)})


@endpoint()
def data_mask(request):
    """FMT03. 数据脱敏：手机号/身份证/银行卡/邮箱打码。"""
    text = req_str(request, "text")

    def _mask_mobile(m):
        s = m.group(0)
        return s[:3] + "****" + s[-4:]

    def _mask_id(m):
        s = m.group(0)
        return s[:4] + "**********" + s[-4:]

    def _mask_bank(m):
        s = re.sub(r"\s", "", m.group(0))
        return s[:4] + " **** **** " + s[-4:]

    def _mask_email(m):
        s = m.group(0)
        name, _, dom = s.partition("@")
        return name[:1] + "***@" + dom

    out = re.sub(r"\b1[3-9]\d{9}\b", _mask_mobile, text)
    out = re.sub(r"\b\d{17}[\dXx]\b", _mask_id, out)
    out = re.sub(r"\b\d{16,19}\b", _mask_bank, out)
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", _mask_email, out)
    return ok({"masked": out})


_END_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# 只匹配开始/结束标签本身（不含 .*?），逐段用 find 定位，避免跨行正则在超长 HTML 上回溯
_BLOCK_OPEN_RE = re.compile(r"(?is)<(script|style)\b[^>]*>")
_BLOCK_CLOSE_RE = re.compile(r"(?is)</(?:script|style)\s*>")
_FMT_TEXT_MAX = 1000000  # 1MB


def _drop_block(html, open_re, close_re):
    """线性删除 <script>/<style> 整块：正则只匹配标签，块内文本用 str.find 跳过。"""
    out, pos = [], 0
    for m in open_re.finditer(html):
        if m.start() < pos:
            continue
        close = close_re.search(html, m.end())
        if not close:
            break
        out.append(html[pos:m.start()])
        pos = close.end()
    out.append(html[pos:])
    return "".join(out)


def _drop_between(text, open_tok, close_tok):
    """删除 open_tok…close_tok 之间的内容（用于 HTML 注释），纯 str.find 线性扫描。"""
    out, pos = [], 0
    while True:
        i = text.find(open_tok, pos)
        if i < 0:
            break
        j = text.find(close_tok, i + len(open_tok))
        if j < 0:
            break
        out.append(text[pos:i])
        pos = j + len(close_tok)
    out.append(text[pos:])
    return "".join(out)


@endpoint()
def html_text(request):
    """FMT04. HTML 转纯文本（去标签/去脚本）。"""
    html = req_str(request, "html", max_len=_FMT_TEXT_MAX)
    html = _drop_block(html, _BLOCK_OPEN_RE, _BLOCK_CLOSE_RE)
    if "<!--" in html:
        html = _drop_between(html, "<!--", "-->")
    text = _END_TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return ok({"text": text})


@endpoint()
def xml_format(request):
    """FMT05. XML 美化/压缩。"""
    xml = req_str(request, "xml")
    compact = opt_bool(request, "compact", False)
    try:
        dom = minidom.parseString(xml)
    except Exception as e:
        raise ValueError(f"XML 解析失败: {e}")
    if compact:
        return ok({"xml": re.sub(r">\s+<", "><", dom.toxml())})
    return ok({"xml": dom.toprettyxml(indent="  ").replace("\n\n", "\n")})


@endpoint()
def csv_escape(request):
    """FMT06. CSV 字段转义/反转义。"""
    mode = opt_str(request, "mode", "escape")
    if mode == "escape":
        field = req_str(request, "field")
        if any(c in field for c in [",", "\"", "\n"]):
            return ok({"escaped": '"' + field.replace('"', '""') + '"'})
        return ok({"escaped": field})
    s = req_str(request, "field")
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1].replace('""', '"')
    return ok({"unescaped": s})


@endpoint()
def json_schema_infer(request):
    """FMT07. 从示例 JSON 推断极简 JSON Schema。"""
    raw = req_str(request, "obj")
    if len(raw) > 1024 * 1024:
        raise ValueError("obj 过大（上限 1MB）")
    obj = json.loads(raw)

    def infer(v, depth=0):
        if depth > 64:
            raise ValueError("JSON 嵌套过深（上限 64 层）")
        if isinstance(v, bool):
            return {"type": "boolean"}
        if isinstance(v, int):
            return {"type": "integer"}
        if isinstance(v, float):
            return {"type": "number"}
        if isinstance(v, str):
            return {"type": "string"}
        if v is None:
            return {"type": "null"}
        if isinstance(v, list):
            return {"type": "array", "items": infer(v[0], depth + 1) if v else {}}
        if isinstance(v, dict):
            return {"type": "object",
                    "properties": {k: infer(val, depth + 1) for k, val in v.items()}}
        return {}

    return ok({"schema": infer(obj)})


@endpoint()
def csv_tsv(request):
    """FMT08. CSV ↔ TSV 互转（文本上限 1MB，逐行生成后再拼接，避免整表双份副本）。"""
    mode = opt_str(request, "mode", "csv_to_tsv")
    text = req_str(request, "text", max_len=_FMT_TEXT_MAX)
    src, dst = (",", "\t") if mode == "csv_to_tsv" else ("\t", ",")

    def _rows():
        for row in text.replace("\r\n", "\n").split("\n"):
            if row:
                yield row.replace(src, dst)

    return ok({"result": "\n".join(_rows())})
