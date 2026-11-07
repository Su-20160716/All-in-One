# -*- coding: utf-8 -*-
"""导出：CSV / JSON 渲染，含公式注入防护与单元格长度收敛。

公式注入（CSV Injection）
-------------------------
Excel / WPS 会把以 ``= + - @`` 开头的单元格当公式执行，``=cmd|'/c calc'!A1``
这类内容一旦被打开就是本机命令执行。报表的单元格内容来自业务数据，
属于不可信输入，因此导出时统一加前缀 ``'``（Excel 的文本转义约定），
并把制表符/回车开头的单元格一并处理。
"""
import csv
import io
import json
import re

from django.utils import timezone

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MAX_CELL_CHARS = 32000  # Excel 单元格上限 32767，留点余量
MAX_EXPORT_ROWS = 50000


def sanitize_cell(value):
    """单值 → 适合 CSV 的文本：公式前缀转义 + 控制字符处理 + 长度截断。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    # 去掉除 \n \t 之外的 C0 控制字符（Excel 会因此报「文件损坏」）
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    if text.startswith(FORMULA_PREFIXES):
        text = "'" + text
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + "…"
    return text


def render_csv(columns, rows, include_header=True, delimiter=",", bom=False):
    """渲染 CSV 文本。

    columns: [{"key","label"}]；rows: [dict]。
    使用 csv 模块而不是手工拼串 —— 引号/换行/分隔符全部交给标准库。
    """
    if not isinstance(columns, list) or not columns:
        raise ValueError("导出缺少列定义")
    if len(rows) > MAX_EXPORT_ROWS:
        raise ValueError(f"单次导出不能超过 {MAX_EXPORT_ROWS} 行")
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n",
                        quoting=csv.QUOTE_MINIMAL)
    if include_header:
        writer.writerow([sanitize_cell(c.get("label") or c.get("key")) for c in columns])
    for row in rows:
        writer.writerow([sanitize_cell((row or {}).get(c.get("key"))) for c in columns])
    text = buffer.getvalue()
    if bom:
        # BOM 让 Excel 正确识别 UTF-8（否则中文变乱码）
        text = "\ufeff" + text
    return text


def render_json(payload):
    """JSON 导出：保留中文与结构，供下游系统消费。"""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _safe_json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, (dict, list)):
        return value
    return str(value)


def widget_columns(result):
    """从组件结果提取列定义（无列时按首行键推导，保证导出永不空表头）。"""
    columns = []
    for col in (result or {}).get("columns") or []:
        if isinstance(col, dict) and col.get("key"):
            columns.append({
                "key": col["key"],
                "label": col.get("label") or col["key"],
                "type": col.get("type") or "string",
            })
    if columns:
        return columns
    rows = (result or {}).get("rows") or []
    if rows and isinstance(rows[0], dict):
        return [{"key": key, "label": key, "type": "string"} for key in rows[0].keys()]
    return []


def find_widget(payload, widget_id=None):
    """在报表执行结果里定位组件（不传 id 时优先返回第一个有数据的表格类组件）。"""
    pages = (payload or {}).get("pages") or []
    candidates = []
    for page in pages:
        for widget in page.get("widgets") or []:
            candidates.append(widget)
    if widget_id:
        for widget in candidates:
            if int(widget.get("id") or 0) == int(widget_id):
                return widget
        raise ValueError(f"报表中不存在组件 {widget_id}")
    for widget in candidates:
        if widget.get("type") in ("table", "pivot", "bar", "line", "pie", "heatmap"):
            if (widget.get("result") or {}).get("rows"):
                return widget
    if candidates:
        return candidates[0]
    raise ValueError("报表没有任何组件，无法导出")


def export_widget(result, fmt="csv", filename="report"):
    """导出单个组件：返回 (filename, content, row_count)。"""
    columns = widget_columns(result)
    rows = (result or {}).get("rows") or []
    fmt = str(fmt or "csv").lower()
    if fmt not in ("csv", "json"):
        raise ValueError("导出格式只支持 csv / json")
    stem = safe_filename(filename)
    if fmt == "csv":
        content = render_csv(columns, rows, bom=True)
        name = f"{stem}-{timezone.localdate():%Y%m%d}.csv"
    else:
        payload = {
            "columns": columns,
            "rows": [{k: _safe_json_value(v) for k, v in (row or {}).items()} for row in rows],
            "meta": (result or {}).get("meta") or {},
            "exported_at": timezone.now().isoformat(),
        }
        content = render_json(payload)
        name = f"{stem}-{timezone.localdate():%Y%m%d}.json"
    return name, content, len(rows)


def export_report(payload, fmt="csv", filename="report", widget_id=None):
    """导出整份报表（默认取第一个有数据的组件，指定 widget_id 则只导它）。"""
    widget = find_widget(payload, widget_id)
    result = widget.get("result") or {}
    stem = filename or payload.get("report", {}).get("name") or "report"
    name, content, rows = export_widget(result, fmt, stem)
    return {
        "filename": name,
        "content": content,
        "rows": rows,
        "widget_id": widget.get("id"),
        "widget_title": widget.get("title", ""),
        "format": str(fmt).lower(),
        "bytes": len(content.encode("utf-8")),
    }


def export_dashboard(payload, fmt="csv"):
    """仪表盘导出：多组件纵向拼接，用「组件名」做分节标题。"""
    items = (payload or {}).get("widgets") or []
    if not items:
        raise ValueError("仪表盘没有组件，无法导出")
    fmt = str(fmt or "csv").lower()
    if fmt == "json":
        content = render_json(payload)
        return {"filename": f"dashboard-{timezone.localdate():%Y%m%d}.json",
                "content": content, "rows": sum(len((i.get("result") or {}).get("rows") or []) for i in items),
                "format": "json", "bytes": len(content.encode("utf-8"))}
    blocks = []
    total_rows = 0
    for item in items:
        result = item.get("result") or {}
        columns = widget_columns(result)
        if not columns:
            continue
        rows = result.get("rows") or []
        total_rows += len(rows)
        blocks.append(f"# {item.get('title') or item.get('id')}")
        blocks.append(render_csv(columns, rows))
    content = "\ufeff" + "\n".join(blocks)
    return {
        "filename": f"dashboard-{timezone.localdate():%Y%m%d}.csv",
        "content": content,
        "rows": total_rows,
        "format": "csv",
        "bytes": len(content.encode("utf-8")),
    }


_NAME_RE = re.compile(r"[^\w\u4e00-\u9fff.\-]+")


def safe_filename(name):
    """文件名收敛：去路径分隔符与特殊字符，禁止 ../ 之类穿越。"""
    text = str(name or "report").strip()
    text = text.replace("\\", "-").replace("/", "-")
    text = _NAME_RE.sub("-", text)
    text = text.strip(".-") or "report"
    return text[:80]
