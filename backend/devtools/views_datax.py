# -*- coding: utf-8 -*-
"""devtools 扩展：结构化数据互转（F39） / 正则调试（F40） / 时间戳批量（F41）。"""
import datetime as _dt
import json
import re
import xml.etree.ElementTree as ET

from core.regex_safety import RegexSafetyError, compile_safe, guard_subject

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, req_str


# ---------------------------------------------------------------- F39


def _parse_yaml(text):
    import yaml

    return yaml.safe_load(text)


def _dump_yaml(obj):
    import yaml

    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False)


def _parse_toml(text):
    import tomllib

    return tomllib.loads(text)


def _dump_toml(obj, prefix=""):
    """极简 TOML 序列化：标量/数组走 key = value，嵌套 dict 走 [section]"""
    if not isinstance(obj, dict):
        raise ValueError("TOML 顶层必须是对象")
    lines, tables = [], []
    for k, v in obj.items():
        key = str(k)
        if isinstance(v, dict):
            tables.append((key, v))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v:
                tables.append((key, item))
        else:
            lines.append(f"{key} = {json.dumps(v, ensure_ascii=False)}")
    out = list(lines)
    for name, table in tables:
        out.append("")
        out.append(f"[{prefix}{name}]")
        for k, v in table.items():
            out.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(out).strip() + "\n"


def _xml_to_obj(elem):
    children = list(elem)
    if not children and not elem.attrib:
        return elem.text or ""
    obj = {}
    for k, v in elem.attrib.items():
        obj[f"@{k}"] = v
    text = (elem.text or "").strip()
    if text:
        obj["#text"] = text
    for child in children:
        val = _xml_to_obj(child)
        if child.tag in obj:
            if not isinstance(obj[child.tag], list):
                obj[child.tag] = [obj[child.tag]]
            obj[child.tag].append(val)
        else:
            obj[child.tag] = val
    return obj


def _obj_to_xml(obj, tag="root"):
    def build(name, value):
        el = ET.Element(str(name))
        if isinstance(value, dict):
            for k, v in value.items():
                if k.startswith("@"):
                    el.set(k[1:], str(v))
                elif k == "#text":
                    el.text = str(v)
                elif isinstance(v, list):
                    for item in v:
                        el.append(build(k, item))
                else:
                    el.append(build(k, v))
        elif isinstance(value, list):
            for item in value:
                el.append(build("item", item))
        else:
            el.text = "" if value is None else str(value)
        return el

    return ET.tostring(build(tag, obj), encoding="unicode")


def _parse_data(text, fmt):
    fmt = (fmt or "json").lower()
    if fmt == "json":
        return json.loads(text)
    if fmt in ("yaml", "yml"):
        return _parse_yaml(text)
    if fmt == "toml":
        return _parse_toml(text)
    if fmt == "xml":
        return _xml_to_obj(ET.fromstring(text))
    raise ValueError("format 只能是 json/yaml/toml/xml")


def _dump_data(obj, fmt):
    fmt = (fmt or "json").lower()
    if fmt == "json":
        return json.dumps(obj, ensure_ascii=False, indent=2)
    if fmt in ("yaml", "yml"):
        return _dump_yaml(obj)
    if fmt == "toml":
        return _dump_toml(obj)
    if fmt == "xml":
        return _obj_to_xml(obj)
    raise ValueError("format 只能是 json/yaml/toml/xml")


@endpoint()
def data_yaml(request):
    """YAML ↔ JSON"""
    text = req_str(request, "text")
    mode = opt_str(request, "mode", "yaml_to_json")
    if mode == "json_to_yaml":
        return ok({"text": _dump_yaml(json.loads(text))})
    if mode != "yaml_to_json":
        raise ValueError("mode 只能是 yaml_to_json / json_to_yaml")
    return ok({"text": json.dumps(_parse_yaml(text), ensure_ascii=False, indent=2)})


@endpoint()
def data_toml(request):
    """TOML ↔ JSON（写端为极简序列化）"""
    text = req_str(request, "text")
    mode = opt_str(request, "mode", "toml_to_json")
    if mode == "json_to_toml":
        return ok({"text": _dump_toml(json.loads(text))})
    if mode != "toml_to_json":
        raise ValueError("mode 只能是 toml_to_json / json_to_toml")
    return ok({"text": json.dumps(_parse_toml(text), ensure_ascii=False, indent=2)})


@endpoint()
def data_xml(request):
    """XML ↔ JSON（属性用 @key，文本用 #text）"""
    text = req_str(request, "text")
    mode = opt_str(request, "mode", "xml_to_json")
    if mode == "json_to_xml":
        return ok({"text": _obj_to_xml(json.loads(text))})
    if mode != "xml_to_json":
        raise ValueError("mode 只能是 xml_to_json / json_to_xml")
    return ok({"text": json.dumps(_xml_to_obj(ET.fromstring(text)), ensure_ascii=False, indent=2)})


@endpoint()
def data_convert(request):
    """通用互转：source/target ∈ json|yaml|toml|xml"""
    text = req_str(request, "text")
    source = opt_str(request, "source", "json")
    target = opt_str(request, "target", "yaml")
    out = _dump_data(_parse_data(text, source), target)
    return ok({"text": out, "source": source, "target": target, "length": len(out)})


# ---------------------------------------------------------------- F40

_RISK_PATTERNS = [
    (r"\((?:[^()]|\\.){0,200}[+*}](?:[^()]|\\.){0,200}\)\s*[+*{]", "nested_quantifier",
     "括号内已含量词，外层再量化，易触发灾难性回溯"),
    (r"\\[1-9][+*{]", "quantified_backref", "对反向引用再加量词，回溯成本极高"),
    (r"\([^()]{0,100}\|[^()]{0,100}\)\s*[+*]", "alternation_quantifier", "分组内多选再量化，可能指数级回溯"),
    (r"\.\*.*\.\*", "double_dotstar", "多个 .* 叠加，长文本下匹配成本高"),
]


@endpoint()
def regex_debug(request):
    """正则调试：命中 + 分组 + 复杂度预警（危险模式直接拒绝执行）"""
    pattern = req_str(request, "pattern")
    text = guard_subject(opt_str(request, "text", ""))
    findings = [{"code": code, "message": msg}
                for rx, code, msg in _RISK_PATTERNS if re.search(rx, pattern)]
    flags = 0
    if opt_bool(request, "ignore_case"):
        flags |= re.I
    if opt_bool(request, "multiline"):
        flags |= re.M
    if opt_bool(request, "dotall"):
        flags |= re.S
    try:
        compiled = compile_safe(pattern, flags)
    except RegexSafetyError as e:
        return ok({"valid": False, "error": str(e), "risk": {"level": "high", "findings": findings},
                   "matches": [], "groups": []})
    matches = []
    for m in compiled.finditer(text):
        matches.append({"text": m.group(0), "start": m.start(), "end": m.end(),
                        "groups": [{"index": i + 1, "value": g} for i, g in enumerate(m.groups())]})
        if len(matches) >= 200:
            break
    groups = [{"index": i + 1, "name": ""} for i in range(compiled.groups)]
    for name, idx in (compiled.groupindex or {}).items():
        if 1 <= idx <= len(groups):
            groups[idx - 1]["name"] = name
    level = "high" if any(f["code"] in ("nested_quantifier", "quantified_backref") for f in findings) \
        else ("medium" if findings else "low")
    return ok({
        "valid": True, "pattern": pattern, "match_count": len(matches), "matches": matches,
        "groups": groups, "named_groups": dict(compiled.groupindex or {}),
        "risk": {"level": level, "findings": findings},
    })


# ---------------------------------------------------------------- F41


@endpoint()
def timestamp_batch(request):
    """时间戳/日期批量转换：逐行返回结果，单行失败不影响其它行"""
    text = req_str(request, "text")
    target = opt_str(request, "target", "iso")
    unit = opt_str(request, "unit", "auto")
    try:
        offset = float(opt_num(request, "tz_offset", 8, minimum=-12, maximum=14))
    except (TypeError, ValueError):
        raise ValueError("tz_offset 必须是 -12~14 的数字")
    if target not in ("iso", "timestamp", "millis"):
        raise ValueError("target 只能是 iso / timestamp / millis")
    tz = _dt.timezone(_dt.timedelta(hours=offset))
    rows = []
    for idx, line in enumerate(text.splitlines()):
        raw = line.strip()
        if not raw:
            continue
        try:
            if raw.replace(".", "", 1).lstrip("-").isdigit():
                val = float(raw)
                if unit == "ms" or (unit == "auto" and abs(val) > 10**11):
                    val /= 1000
                dt = _dt.datetime.fromtimestamp(val, tz)
            else:
                parsed = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                dt = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
            if target == "iso":
                result = dt.isoformat(timespec="seconds")
            elif target == "timestamp":
                result = int(dt.timestamp())
            else:
                result = int(dt.timestamp() * 1000)
            rows.append({"index": idx, "input": raw, "ok": True, "result": result})
        except (ValueError, OverflowError, OSError) as e:
            rows.append({"index": idx, "input": raw, "ok": False, "error": str(e)})
    failed = sum(1 for r in rows if not r["ok"])
    return ok({"rows": rows, "total": len(rows), "failed": failed,
               "target": target, "tz_offset": offset})
