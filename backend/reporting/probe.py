# -*- coding: utf-8 -*-
"""数据源探测：orm 真实计数，http / file 只做配置校验 + 模拟结果。

为什么 http/file 不真连
-----------------------
项目运行环境（含测试与演示环境）不允许外联：真发请求既可能超时拖垮
接口，也可能把内网地址暴露成 SSRF 面。所以这两类数据源只校验配置结构，
返回「模拟探测」结果，把真实连通性留给部署方在外部任务里做。
"""
import time
from urllib.parse import urlparse

from reporting.compiler import preview_count
from reporting.whitelist import get_whitelisted_model, model_label

HTTP_METHODS = ("GET", "POST")
FILE_FORMATS = ("csv", "json", "xlsx")
FILE_ENCODINGS = ("utf-8", "utf-8-sig", "gbk")


def probe_source(kind, config):
    """按类型探测数据源，返回 {ok, message, latency_ms, detail}（不抛异常）。"""
    started = time.perf_counter()
    config = config if isinstance(config, dict) else {}
    try:
        if kind == "orm":
            detail = _probe_orm(config)
        elif kind == "http":
            detail = _probe_http(config)
        elif kind == "file":
            detail = _probe_file(config)
        else:
            return _result(False, f"不支持的数据源类型：{kind}", started, {})
        return _result(True, detail.pop("message"), started, detail)
    except ValueError as e:
        return _result(False, str(e), started, {})
    except Exception as e:  # noqa: BLE001 —— 探测失败也要结构化返回
        return _result(False, f"{type(e).__name__}: {e}", started, {})


def _result(ok, message, started, detail):
    return {
        "ok": ok,
        "message": message[:255],
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "detail": detail,
        "network": False,
    }


def _probe_orm(config):
    """orm 源：模型必须白名单内，顺手数一下行数（真查询，但只是 COUNT）。"""
    label = str(config.get("model") or config.get("model_label") or "").strip()
    if not label:
        raise ValueError("orm 数据源需要配置 model（app_label.ModelName）")
    model = get_whitelisted_model(label)
    rows = preview_count(label, config.get("filter") or {})
    return {
        "message": f"模型 {model_label(model)} 可访问，命中 {rows} 行",
        "model": model_label(model),
        "rows": rows,
        "field_count": len(model._meta.concrete_fields),
    }


def _probe_http(config):
    """http 源：只校验 URL / 方法 / 头 / 超时；不发起任何请求。"""
    url = str(config.get("url") or "").strip()
    if not url:
        raise ValueError("http 数据源需要配置 url")
    if len(url) > 500:
        raise ValueError("url 过长（上限 500 字符）")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url 只支持 http / https 协议")
    if not parsed.hostname:
        raise ValueError("url 缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError("url 不允许内嵌账号密码，请把凭据放到部署环境变量")
    method = str(config.get("method") or "GET").upper()
    if method not in HTTP_METHODS:
        raise ValueError("method 只支持 GET / POST")
    headers = config.get("headers") or {}
    if not isinstance(headers, dict) or len(headers) > 20:
        raise ValueError("headers 必须是不超过 20 项的 JSON 对象")
    for key in headers:
        if not isinstance(key, str) or len(key) > 80:
            raise ValueError("headers 的键必须是长度 ≤80 的字符串")
    timeout = config.get("timeout", 5)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        raise ValueError("timeout 必须是数字")
    if timeout <= 0 or timeout > 60:
        raise ValueError("timeout 需在 0~60 秒之间")
    return {
        "message": "HTTP 配置校验通过（未联网，模拟探测成功）",
        "host": parsed.hostname,
        "method": method,
        "timeout": timeout,
        "simulated_status": 200,
    }


def _probe_file(config):
    """file 源：只校验文件名 / 格式 / 编码，不读磁盘。"""
    filename = str(config.get("filename") or config.get("path") or "").strip()
    if not filename:
        raise ValueError("file 数据源需要配置 filename")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("filename 只能是文件名，不允许路径穿越")
    if len(filename) > 120:
        raise ValueError("filename 过长（上限 120 字符）")
    fmt = str(config.get("format") or "").lower()
    if fmt not in FILE_FORMATS:
        raise ValueError(f"format 只支持：{'/'.join(FILE_FORMATS)}")
    encoding = str(config.get("encoding") or "utf-8").lower()
    if encoding not in FILE_ENCODINGS:
        raise ValueError(f"encoding 只支持：{'/'.join(FILE_ENCODINGS)}")
    declared_rows = config.get("rows")
    row_hint = None
    if declared_rows is not None:
        try:
            row_hint = int(declared_rows)
        except (TypeError, ValueError):
            raise ValueError("rows 必须是整数")
        if row_hint < 0:
            raise ValueError("rows 不能为负")
    return {
        "message": "文件配置校验通过（未读取文件，模拟探测成功）",
        "filename": filename,
        "format": fmt,
        "encoding": encoding,
        "simulated_rows": row_hint,
    }


def probe_message_success(probe):
    """把探测结果压成一句可入库的说明（数据源列表直接展示）。"""
    if probe.get("ok"):
        return str(probe.get("message") or "探测通过")[:255]
    return f"探测失败：{probe.get('message') or '未知原因'}"[:255]
