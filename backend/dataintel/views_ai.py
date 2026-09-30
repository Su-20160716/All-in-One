# -*- coding: utf-8 -*-
"""dataintel · AI 面与报表面接口：ai(8) + report(5) = 13 个。

AI 接口全部走 assistant.llm 适配器：配置了 LLM_API_KEY 用大模型，
没配置走本地降级实现（响应里始终带 provider 标注）。
"""
import json
import re

from assistant import llm as llm_mod
from assistant.llm import (chat, chat_json, extractive_summary,
                           is_configured, keywords as llm_keywords,
                           split_sentences, status as llm_status)

from devtools.common import endpoint, fail, ok, opt_bool, opt_num, opt_str, p, req, req_list, req_num, req_str

from .views_data import load_rows
from .views_nlp import _NER_PATTERNS, _ZH_SENTIMENT_NEG, _ZH_SENTIMENT_POS

# =====================================================================
# ai LLM 增强（8）
# =====================================================================


@endpoint(("GET",))
def ai_status(request):
    """AI 能力状态（提供方 / 模型 / 配置指引）。"""
    st = llm_status()
    st["features"] = {"chat": True, "translate": True, "rewrite": True, "classify": True,
                      "extract": True, "sentiment": True, "summary": True}
    return ok(st)


def _llm_or_local(system, user_prompt, local_fn):
    """统一封装：LLM 可用则用 LLM，否则本地降级；响应带 provider。"""
    if is_configured():
        res = chat([{"role": "system", "content": system}, {"role": "user", "content": user_prompt}])
        if res["ok"]:
            return {"provider": "llm", "model": res["model"], "result": res["content"],
                    "duration_ms": res["duration_ms"]}
    data = local_fn()
    data["provider"] = "local"
    data["degraded"] = True
    return data


@endpoint()
def ai_chat(request):
    """通用对话（messages 数组或单条 text；无 Key 走本地规则应答）。"""
    messages = p(request, "messages")
    if messages:
        if not isinstance(messages, list) or any(not isinstance(m, dict) or "role" not in m or "content" not in m for m in messages):
            raise ValueError("messages 需为 [{role, content}] 数组")
    else:
        text = req_str(request)
        messages = [{"role": "user", "content": text}]

    def local():
        q = messages[-1]["content"]
        kws = llm_keywords(q, 5)
        reply = ("（本地模式，未配置 LLM_API_KEY）我理解你在聊" +
                 ("「" + "、".join(kws[:3]) + "」" if kws else "这个话题") + "。"
                 "本地模式只能做关键词应答：配置 backend/.env 的 LLM_API_KEY 后，我会调用真实大模型完整回答。")
        return {"result": reply}

    return ok(_llm_or_local("你是全能协作平台内置的数据智能助手，回答简洁专业。", messages[-1]["content"], local))


_MINI_DICT = {"hello": "你好", "world": "世界", "thanks": "谢谢", "cat": "猫", "dog": "狗", "code": "代码",
              "data": "数据", "meeting": "会议", "report": "报告", "hello world": "你好，世界"}


@endpoint()
def ai_translate(request):
    """翻译（LLM）；无 Key 时提供迷你词典降级 + 明确提示。"""
    text = req_str(request)
    target = opt_str(request, "target", "en")
    if is_configured():
        res = chat([{"role": "system", "content": f"你是翻译引擎，把用户文本翻译成 {target}，只输出译文。"},
                    {"role": "user", "content": text}])
        if res["ok"]:
            return ok({"provider": "llm", "translation": res["content"], "target": target})
    hits = {w: _MINI_DICT[w] for w in _MINI_DICT if w in text.lower()}
    return ok({"provider": "local", "degraded": True, "target": target,
               "translation": None, "dictionary_hits": hits,
               "message": "未配置 LLM_API_KEY，机翻不可用；本地仅提供常用词词典命中。"})


@endpoint()
def ai_rewrite(request):
    """文本改写：polish 润色 / shorten 缩写 / expand 扩写。"""
    text = req_str(request)
    style = opt_str(request, "style", "polish")
    if style == "polish" and not is_configured():
        # 润色本地也能干得不错：标点规范 + 去冗余空白 + 重复词收敛
        out = re.sub(r"\s+", " ", text).strip()
        out = re.sub(r"([，。！？；：,.!?;:])\1+", r"\1", out)
        out = re.sub(r"[,;]", "，", out)
        out = re.sub(r"\.", "。", out) if "。" in out or "，" in out else out
        return ok({"provider": "local", "style": "polish", "result": out, "changed": out != text.strip()})
    prompts = {"polish": "润色下面的文字，保持原意，更通顺专业",
               "shorten": "把下面的文字压缩到一半篇幅，保留要点",
               "expand": "扩写下面的文字，补充论据与细节，篇幅翻倍"}
    if style not in prompts:
        raise ValueError("style 支持 polish/shorten/expand")

    def local():
        if style == "shorten":
            return {"result": extractive_summary(text, max_sentences=max(1, len(split_sentences(text)) // 2))}
        return {"result": text,
                "message": "本地模式无法扩写/深度润色，已原文返回；配置 LLM_API_KEY 后可用。"}
    return ok(_llm_or_local("你是文案编辑助手。", f"{prompts[style]}：\n{text}", local))


@endpoint()
def ai_classify(request):
    """文本分类：LLM 零样本；无 Key 时走关键词规则。"""
    text = req_str(request)
    labels = req_list(request, "labels")

    def local():
        low = text.lower()
        scored = []
        for lb in labels:
            kw = str(lb).lower()
            hit = kw in low or any(part and part in low for part in kw.split())
            scored.append({"label": str(lb), "score": 2 if kw in low else (1 if hit else 0)})
        best = max(scored, key=lambda x: x["score"])
        return {"predicted": best["label"] if best["score"] else None,
                "scores": scored, "method": "keyword-match"}
    data = _llm_or_local(
        "你是文本分类器。只输出 JSON：{\"label\": \"...\"}，label 必须从候选中选。",
        f"候选标签：{json.dumps(labels, ensure_ascii=False)}\n文本：{text}",
        local)
    if data.get("provider") == "llm":
        parsed = None
        try:
            parsed = json.loads(re.search(r"\{[\s\S]*\}", data["result"]).group(0))
        except (AttributeError, ValueError):
            pass
        data["parsed"] = parsed
    return ok(data)


@endpoint()
def ai_extract(request):
    """结构化信息抽取：LLM JSON 模式；无 Key 时正则规则抽取。"""
    text = req_str(request)
    fields = req_list(request, "fields")

    def local():
        found = {}
        for _, name, pat in _NER_PATTERNS:
            hits = sorted(set(re.findall(pat, text)))
            for f in fields:
                fname = str(f)
                if fname and (fname in name or name in fname):
                    found[fname] = hits
        return {"extracted": {str(f): found.get(str(f), []) for f in fields}, "method": "regex"}
    data = _llm_or_local(
        "你是信息抽取引擎。只输出 JSON 对象，key 为给定字段名，value 为字符串或数组；抽不到给 null。",
        f"字段：{json.dumps([str(f) for f in fields], ensure_ascii=False)}\n文本：{text}",
        local)
    if data.get("provider") == "llm":
        try:
            data["parsed"] = json.loads(re.search(r"\{[\s\S]*\}", data["result"]).group(0))
        except (AttributeError, ValueError):
            data["parsed"] = None
    return ok(data)


@endpoint()
def ai_sentiment(request):
    """情感分析（LLM 优先，本地词典兜底）。"""
    text = req_str(request)

    def local():
        low = text.lower()
        pos = [w for w in _ZH_SENTIMENT_POS if w in low]
        neg = [w for w in _ZH_SENTIMENT_NEG if w in low]
        score = (len(pos) - len(neg)) / max(len(pos) + len(neg), 1)
        return {"label": "正面" if score > 0.2 else "负面" if score < -0.2 else "中性",
                "score": round(score, 4), "method": "lexicon"}
    return ok(_llm_or_local("判断文本情感，只输出 JSON：{\"label\": \"正面|负面|中性\", \"score\": -1到1}。",
                            text, local))


@endpoint()
def ai_summary(request):
    """智能摘要（LLM 优先，抽取式兜底）。"""
    text = req_str(request)
    max_sentences = int(opt_num(request, "max_sentences", 3, minimum=1, maximum=10) or 3)

    def local():
        return {"result": extractive_summary(text, max_sentences=max_sentences),
                "method": "extractive"}
    data = _llm_or_local("你是摘要助手，输出不超过指定句数的中文摘要。", f"摘要以下内容（最多 {max_sentences} 句）：\n{text}", local)
    return ok(data)


# =====================================================================
# report 报表生成（5）
# =====================================================================


def _md_table(headers, rows):
    lines = ["| " + " | ".join(map(str, headers)) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


@endpoint()
def report_summary(request):
    """数据集体检报告（Markdown）：形状/字段/缺失/数值概览。"""
    rows, ds = load_rows(request)
    if not rows:
        raise ValueError("数据为空，无法生成报告")
    fields = sorted({k for r in rows for k in r})
    table_rows = []
    for f in fields:
        vals = [r.get(f) for r in rows]
        nums = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        missing = sum(1 for v in vals if v is None)
        stat = (f"均值 {sum(nums) / len(nums):.2f} / 最小 {min(nums):.2f} / 最大 {max(nums):.2f}"
                if len(nums) >= 2 else f"{len(nums)} 个数值")
        table_rows.append([f, missing, f"{missing / len(rows) * 100:.1f}%", stat])
    md = (f"# 数据体检报告\n\n- 行数：**{len(rows)}**，字段数：**{len(fields)}**\n\n"
          + _md_table(["字段", "缺失", "缺失率", "数值概况"], table_rows))
    if ds:
        md += f"\n\n> 来源数据集：{ds.name}（#{ds.id}）"
    return ok({"report_md": md, "rows": len(rows), "fields": len(fields), "format": "markdown"})


@endpoint()
def report_trend(request):
    """趋势报告：方向 / 环比 / 异常点 / Markdown 叙述。"""
    values = req_list(request, "values")
    labels = p(request, "labels") or [f"T{i + 1}" for i in range(len(values))]
    try:
        vals = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values 必须是数字数组")
    if len(vals) < 3:
        raise ValueError("至少 3 个数据点")
    from dataintel.statkit import ols_fit, stdev

    fit = ols_fit(list(range(len(vals))), vals)
    changes = [round((vals[i] - vals[i - 1]) / abs(vals[i - 1]) * 100, 2) if vals[i - 1] else None
               for i in range(1, len(vals))]
    mu, sd = sum(vals) / len(vals), stdev(vals)
    anomalies = [{"point": labels[i], "value": vals[i]} for i, v in enumerate(vals)
                 if sd and abs((v - mu) / sd) > 2]
    md = (f"# 趋势报告\n\n- 整体方向：**{'上升' if fit['slope'] > 0 else '下降' if fit['slope'] < 0 else '持平'}**"
          f"（斜率 {fit['slope']:.4f}，R² {fit['r2']:.3f}）\n"
          f"- 区间：{labels[0]} → {labels[-1]}，累计变化 **{(vals[-1] - vals[0]) / (abs(vals[0]) or 1) * 100:.1f}%**\n"
          f"- 最大单期涨幅 {max((c for c in changes if c is not None), default=0)}%，"
          f"最大跌幅 {min((c for c in changes if c is not None), default=0)}%\n"
          f"- 异常点（|z|>2）：{anomalies if anomalies else '无'}\n")
    return ok({"report_md": md, "slope": fit["slope"], "r2": fit["r2"],
               "changes": changes, "anomalies": anomalies})


@endpoint()
def report_compare(request):
    """对比报告：两组数值字段逐项对比（A/B 或同期）。"""
    rows_a, _ = load_rows(request)
    rows_b = p(request, "rows_b")
    if isinstance(rows_b, str):
        rows_b = json.loads(rows_b)
    if not isinstance(rows_b, list):
        raise ValueError("rows_b 必须是数组（对比组）")
    fields = p(request, "fields") or sorted({k for r in rows_a for k in r if isinstance(r.get(k), (int, float))}
                                            & {k for r in rows_b for k in r if isinstance(r.get(k), (int, float))})
    table = []
    for f in fields:
        va = [float(r[f]) for r in rows_a if isinstance(r.get(f), (int, float))]
        vb = [float(r[f]) for r in rows_b if isinstance(r.get(f), (int, float))]
        if not va or not vb:
            continue
        ma, mb = sum(va) / len(va), sum(vb) / len(vb)
        delta = (ma - mb) / (abs(mb) or 1) * 100
        table.append([f, round(ma, 4), round(mb, 4), f"{delta:+.1f}%", "↑" if delta > 0 else "↓" if delta < 0 else "→"])
    md = (f"# 对比报告（A 组 {len(rows_a)} 行 vs B 组 {len(rows_b)} 行）\n\n"
          + _md_table(["字段", "A 均值", "B 均值", "差异", "方向"], table))
    return ok({"report_md": md, "compared_fields": len(table), "format": "markdown"})


@endpoint()
def report_kpi(request):
    """KPI 计分卡：达成率 / 状态灯 / Markdown 看板。"""
    kpis = req_list(request, "kpis")
    rows = []
    for k in kpis:
        if not isinstance(k, dict) or "name" not in k or "value" not in k:
            raise ValueError('kpis 每项需为 {name, value, target?, unit?}')
        name, value = str(k["name"]), float(k["value"])
        target = float(k["target"]) if k.get("target") is not None else None
        unit = str(k.get("unit", ""))
        if target:
            rate = value / target * 100
            status = "🟢 达标" if rate >= 100 else "🟡 接近" if rate >= 80 else "🔴 滞后"
            rows.append([name, f"{value:g}{unit}", f"{target:g}{unit}", f"{rate:.1f}%", status])
        else:
            rows.append([name, f"{value:g}{unit}", "-", "-", "➖ 无目标"])
    md = "# KPI 计分卡\n\n" + _md_table(["指标", "实际", "目标", "达成率", "状态"], rows)
    on_track = sum(1 for r in rows if "🟢" in r[4])
    md += f"\n\n**{on_track}/{len(rows)}** 项达标。"
    return ok({"report_md": md, "kpis": len(rows), "on_track": on_track, "format": "markdown"})


@endpoint()
def report_export(request):
    """行数据导出 CSV 字符串（内存导出，不落盘）。"""
    rows, ds = load_rows(request)
    fields = p(request, "fields") or (sorted({k for r in rows for k in r}) if rows else [])
    delim = opt_str(request, "delimiter", ",")
    lines = [delim.join(fields)]
    for r in rows:
        vals = []
        for f in fields:
            v = r.get(f)
            s = "" if v is None else str(v)
            if delim in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            vals.append(s)
        lines.append(delim.join(vals))
    return ok({"csv": "\n".join(lines), "rows": len(rows), "fields": fields,
               "bytes": len("\n".join(lines).encode("utf-8")),
               "dataset": ds.name if ds else None})


AI_FAMILY_COUNT = 8 + 5  # = 13
