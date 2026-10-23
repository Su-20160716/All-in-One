# -*- coding: utf-8 -*-
"""外部依赖适配器的统一降级语义（S2-B1）。

项目铁律「可降级适配器」的收口模块：LibreOffice / LLM / 执行沙箱等外部依赖
缺失或失败时，**永远返回结构化结果，绝不向调用方抛异常、绝不 500**。

统一约定
--------
1. 失败返回 `{"ok": False, "code": <错误码>, "message": <中文说明>, ...}`；
   成功返回 `{"ok": True, "code": "OK", ...}`。
2. 错误码集中在 `CODES`（含中文说明），新增依赖在此登记，不要散着造字符串。
3. `guard()` 兜底包装：把「忘了 try 的适配器函数」的异常也转成结构化失败。
4. `register_probe()` 登记探测函数，`/api/core/health/` 一处看全外部依赖状态。

兼容性：本模块只提供构造器与语义，不改变 files.office / assistant.llm /
code.runtime 既有返回结构的字段名（code/message/error/path...），纯新增。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "CODES", "degraded", "succeeded", "guard",
    "register_probe", "probe", "probe_all", "unregister_probe",
]

# 错误码登记表：code -> 默认中文说明（degraded 未显式传 message 时使用）
CODES = {
    "OK": "正常",
    # —— LibreOffice 文档转换 ——
    "LIBREOFFICE_NOT_FOUND": "未检测到 LibreOffice，按平台提示安装后重试",
    "SOURCE_MISSING": "源文件不存在",
    "UNSUPPORTED_FORMAT": "不支持的格式",
    "CONVERT_FAILED": "转换失败",
    "TIMEOUT": "执行超时",
    # —— LLM 远程调用 ——
    "NOT_CONFIGURED": "未配置 LLM_API_KEY，已降级为本地实现",
    "HTTP_ERROR": "远程服务返回错误",
    "NETWORK_ERROR": "网络请求失败",
    "BAD_RESPONSE": "远程响应格式异常",
    # —— 执行沙箱 ——
    "RUNTIME_NOT_FOUND": "本机未安装该语言运行时",
    "RUNTIME_UNSUPPORTED": "当前平台不支持该语言",
    # —— 通用 ——
    "ADAPTER_ERROR": "适配器内部错误",
    "PROBE_FAILED": "探测失败",
}


def degraded(code: str, message: str = "", **extra) -> dict:
    """构造结构化失败结果（永不为 None、永不抛异常）。"""
    return {
        "ok": False,
        "code": code,
        "message": message or CODES.get(code, code),
        **extra,
    }


def succeeded(**extra) -> dict:
    """构造结构化成功结果。"""
    return {"ok": True, "code": "OK", **extra}


def guard(fn, code: str = "ADAPTER_ERROR", **extra) -> dict:
    """兜底包装：fn() 的任何异常都转成 degraded()。

    用于「理论不该炸但怕炸」的适配器路径（第三方库边界、平台差异），
    与调用方自己的业务 try 分工：guard 保底不 500，调用方处理语义。
    """
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 —— 兜底保命，日志必须留
        logger.exception("适配器执行失败 code=%s", code)
        return degraded(code, f"{type(exc).__name__}: {exc}", **extra)
    if isinstance(result, dict) and result.get("ok") is False and "code" not in result:
        result["code"] = code
    return result


# ---------------------------------------------------------------------------
# 探测注册表：外部依赖健康状态一处汇总
# ---------------------------------------------------------------------------

_PROBES: dict[str, callable] = {}


def register_probe(name: str, fn) -> None:
    """登记探测函数：fn() -> {"available": bool, ...}"""
    _PROBES[name] = fn


def unregister_probe(name: str) -> None:
    _PROBES.pop(name, None)


def probe(name: str) -> dict:
    """探测单个依赖；探测函数自身炸掉也返回结构化结果。"""
    fn = _PROBES.get(name)
    if fn is None:
        return degraded("PROBE_FAILED", f"未登记的探测项: {name}")
    return guard(fn, code="PROBE_FAILED", name=name)


def probe_all() -> dict:
    """全部依赖探测（供 /api/core/health/ 与管理端诊断页）。"""
    return {name: probe(name) for name in sorted(_PROBES)}
