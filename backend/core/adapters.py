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
    # —— 汇率 ——
    "RATES_FALLBACK": "未配置实时汇率源，已降级为静态参考值",
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


# ---------------------------------------------------------------------------
# 汇率：静态参考值 + 可选环境覆盖（F51 单位换算）
# ---------------------------------------------------------------------------

# 「1 单位外币 = 多少 CNY」；仅用于离线演示，不构成交易依据。
STATIC_RATES_CNY = {
    "CNY": 1.0, "USD": 7.10, "EUR": 7.75, "JPY": 0.0475, "HKD": 0.912,
    "GBP": 9.10, "AUD": 4.68, "CAD": 5.15, "KRW": 0.00515, "SGD": 5.28,
    "TWD": 0.221, "THB": 0.205, "RUB": 0.078, "INR": 0.084, "CHF": 8.05,
}
STATIC_RATES_AS_OF = "2026-01-01"


def currency_rates() -> dict:
    """返回 {code: 每单位兑 CNY} 与来源标注。

    优先读 settings.CURRENCY_RATES（运维可注入实时汇率），未配置则用静态参考值。
    任何异常都退回静态表，调用方永远不会因为汇率拿不到而 500。
    """
    from django.conf import settings

    override = getattr(settings, "CURRENCY_RATES", None)
    if isinstance(override, dict) and override:
        rates = {}
        for k, v in override.items():
            try:
                rates[str(k).upper()] = float(v)
            except (TypeError, ValueError):
                continue
        if rates:
            rates.setdefault("CNY", 1.0)
            return {
                "ok": True, "code": "OK", "rates": rates,
                "source": "settings", "as_of": getattr(settings, "CURRENCY_RATES_AS_OF", ""),
                "message": "汇率来自系统配置",
            }
    return {
        "ok": False, "code": "RATES_FALLBACK", "rates": dict(STATIC_RATES_CNY),
        "source": "static-reference", "as_of": STATIC_RATES_AS_OF,
        "message": "未配置实时汇率源，使用静态参考值（仅供演示）",
    }


def _probe_currency():
    info = currency_rates()
    return {"available": bool(info["rates"]), "source": info["source"],
            "as_of": info["as_of"], "currencies": len(info["rates"])}


register_probe("currency", _probe_currency)
