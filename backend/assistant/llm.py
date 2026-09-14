"""LLM 适配器 + 无 Key 降级实现

对外只暴露一个 `chat()`，调用方无需关心背后是 OpenAI、DeepSeek、通义还是本地 vLLM ——
只要兼容 OpenAI 的 `/chat/completions` 协议即可。

未配置 LLM_API_KEY 时 `chat()` 返回 ok=False + code=NOT_CONFIGURED，
各业务视图随即走本地降级（抽取式摘要 / 关键词 / 检索问答 / 启发式批改），
所以「AI 功能」在没有 Key 的环境里同样可用、可演示、可测试。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from django.conf import settings

from core.search import term_freq, tokenize


# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    return bool(getattr(settings, "LLM_API_KEY", "").strip())


def status() -> dict:
    configured = is_configured()
    return {
        "configured": configured,
        "provider": "llm" if configured else "local",
        "model": settings.LLM_MODEL if configured else "local-extractive",
        "base_url": settings.LLM_BASE_URL if configured else "",
        "mode_label": "大模型" if configured else "本地降级（未配置 LLM_API_KEY）",
        "features": {
            "summarize": True,
            "note_qa": True,
            "chat": True,
            "generate_questions": True,
            "grade": True,
        },
        "setup_hint": "" if configured else (
            "在 backend/.env（或系统环境变量）设置 LLM_API_KEY（可选 LLM_BASE_URL / LLM_MODEL）"
            "即可启用真实大模型；兼容 OpenAI Chat Completions 协议的服务均可。"
        ),
    }


# ---------------------------------------------------------------------------
# 远程调用
# ---------------------------------------------------------------------------

class LLMError(Exception):
    pass


def chat(messages, temperature=None, max_tokens=None, json_mode=False, timeout=None) -> dict:
    """调用兼容 OpenAI 协议的对话补全接口。

    :return: {"ok": bool, "content": str, "provider": str, "model": str,
              "error": str, "code": str, "duration_ms": int}
    """
    started = time.time()
    if not is_configured():
        return {"ok": False, "content": "", "provider": "local", "model": "local-extractive",
                "error": "未配置 LLM_API_KEY，已降级为本地实现", "code": "NOT_CONFIGURED",
                "duration_ms": 0}

    url = f"{settings.LLM_BASE_URL}/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    # 合并厂商专属参数（settings.LLM_EXTRA_BODY，如 NIM 的 thinking 开关）
    payload.update(getattr(settings, "LLM_EXTRA_BODY", {}) or {})

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or settings.LLM_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        return {"ok": False, "content": "", "provider": "llm", "model": settings.LLM_MODEL,
                "error": f"HTTP {exc.code} {detail}", "code": "HTTP_ERROR",
                "duration_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "content": "", "provider": "llm", "model": settings.LLM_MODEL,
                "error": f"请求失败：{exc}", "code": "NETWORK_ERROR",
                "duration_ms": int((time.time() - started) * 1000)}

    try:
        content = body["choices"][0]["message"]["content"] or ""
    except Exception:
        return {"ok": False, "content": "", "provider": "llm", "model": settings.LLM_MODEL,
                "error": f"响应格式异常：{str(body)[:200]}", "code": "BAD_RESPONSE",
                "duration_ms": int((time.time() - started) * 1000)}

    return {"ok": True, "content": content.strip(), "provider": "llm", "model": settings.LLM_MODEL,
            "error": "", "code": "OK", "duration_ms": int((time.time() - started) * 1000)}


def chat_json(messages, fallback=None, **kwargs):
    """要求模型输出 JSON，解析失败时返回 fallback"""
    res = chat(messages, json_mode=True, **kwargs)
    if not res["ok"]:
        return None, res
    raw = res["content"].strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    try:
        return json.loads(raw), res
    except Exception:
        # 尝试截取第一个 JSON 对象
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1]), res
            except Exception:
                pass
    return fallback, res


def log_usage(owner_id, feature, result, prompt_chars=0, output_chars=0):
    """写入调用日志（失败不影响主流程）"""
    try:
        from assistant.models import AIUsageLog

        AIUsageLog.objects.create(
            owner_id=owner_id, feature=feature, provider=result.get("provider", ""),
            model=result.get("model", ""), success=bool(result.get("ok")),
            prompt_chars=prompt_chars, output_chars=output_chars,
            duration_ms=int(result.get("duration_ms", 0) or 0),
            error=(result.get("error") or "")[:255],
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 本地降级实现
# ---------------------------------------------------------------------------

_SENT_SPLIT = "。！？!?；;\n\r"


def split_sentences(text: str, min_len: int = 4):
    """中英文句子切分（不引入分词库）"""
    if not text:
        return []
    sentences, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch in _SENT_SPLIT:
            s = "".join(buf).strip()
            buf = []
            if len(s) >= min_len:
                sentences.append(s)
            elif s:
                sentences.append(s)
    tail = "".join(buf).strip()
    if tail:
        sentences.append(tail)
    return sentences


def keywords(text: str, top: int = 8):
    """基于词频的关键词提取（复用全文搜索的分词器）"""
    freq = term_freq(text or "")
    if not freq:
        return []
    # 双字词优先（信息量高于单字），并按长度加权
    ranked = sorted(
        freq.items(),
        key=lambda kv: (kv[1] * (2 if len(kv[0]) >= 2 else 1)),
        reverse=True,
    )
    out, seen = [], set()
    for term, _ in ranked:
        if len(term) < 2:
            continue
        if any(term in s or s in term for s in seen):
            continue
        seen.add(term)
        out.append(term)
        if len(out) >= top:
            break
    return out


def extractive_summary(text: str, max_sentences: int = 5) -> str:
    """抽取式摘要：按关键词权重给句子打分，取前 N 句并按原文顺序输出"""
    sentences = split_sentences(text or "")
    if not sentences:
        return ""
    if len(sentences) <= max_sentences:
        return "".join(sentences).strip()

    freq = term_freq(text)
    if not freq:
        return "".join(sentences[:max_sentences]).strip()
    max_freq = max(freq.values()) or 1

    scored = []
    for idx, sent in enumerate(sentences):
        tokens = tokenize(sent)
        if not tokens:
            continue
        score = sum(freq.get(t, 0) / max_freq for t in tokens) / (len(tokens) ** 0.5)
        # 开头句通常是结论，给一点加成；过长的句子轻微惩罚
        if idx < 2:
            score *= 1.15
        if len(sent) > 160:
            score *= 0.9
        scored.append((score, idx, sent))

    if not scored:
        return "".join(sentences[:max_sentences]).strip()
    picked = sorted(sorted(scored, key=lambda x: x[0], reverse=True)[:max_sentences], key=lambda x: x[1])
    return "".join(s for _, _, s in picked).strip()


def bullet_points(text: str, count: int = 5):
    """把摘要结果整理成要点列表（本地降级时用于「要点提炼」）"""
    sentences = split_sentences(text or "")
    if not sentences:
        return []
    freq = term_freq(text)
    max_freq = max(freq.values()) if freq else 1
    scored = []
    for idx, sent in enumerate(sentences):
        tokens = tokenize(sent)
        if not tokens:
            continue
        score = sum(freq.get(t, 0) / max_freq for t in tokens) / (len(tokens) ** 0.5)
        scored.append((score, idx, sent.strip()))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = sorted(scored[:count], key=lambda x: x[1])
    out = []
    for _, _, sent in picked:
        item = sent.strip(" -•\t")
        if item and item not in out:
            out.append(item[:200])
    return out


def answer_from_context(question: str, chunks, max_chars: int = 1200) -> dict:
    """无大模型时的检索问答：返回最相关的原文片段 + 关键词提示

    :param chunks: [{"title": str, "text": str, "ref": {...}}]
    :return: {"answer": str, "references": [...], "confidence": float}
    """
    q_terms = set(tokenize(question))
    scored = []
    for chunk in chunks:
        text = chunk.get("text") or ""
        if not text:
            continue
        tokens = tokenize(text)
        if not tokens:
            continue
        hits = sum(1 for t in tokens if t in q_terms)
        if not hits:
            continue
        density = hits / (len(tokens) ** 0.5)
        scored.append((density, chunk, hits))

    if not scored:
        return {"answer": "未在文档中找到与该问题相关的内容。可以换一个说法，或先补充相关笔记。",
                "references": [], "confidence": 0.0}

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[0]
    picked = scored[:3]
    body = top[1].get("text", "")[:max_chars]
    excerpt = extractive_summary(body, max_sentences=4) or body[:400]
    kw = "、".join(keywords(question, 6)) or question

    answer = (
        f"（本地检索模式，未调用大模型）与「{kw}」最相关的内容如下：\n\n{excerpt}"
    )
    return {
        "answer": answer,
        "references": [
            {"title": c[1].get("title", ""), "score": round(c[0], 3), **(c[1].get("ref") or {})}
            for c in picked
        ],
        "confidence": round(min(top[0] / 3, 1.0), 2),
    }


def heuristic_grade(question: str, reference: str, user_answer: str, qtype: str = "subjective") -> dict:
    """启发式批改（无大模型时使用）

    客观题：标准化比较
    主观题：参考答案关键词覆盖率 + 篇幅合理性
    """
    ua = (user_answer or "").strip()
    ref = (reference or "").strip()

    if qtype in ("single", "judge", "fill"):
        norm = lambda s: "".join(ch for ch in (s or "").lower() if not ch.isspace())
        ok = norm(ua) == norm(ref)
        if qtype == "judge":
            truthy = {"true", "1", "yes", "对", "正确", "是", "t"}
            falsy = {"false", "0", "no", "错", "错误", "否", "f"}
            low = ua.lower()
            if low in truthy or low in falsy:
                ok = (low in truthy) == (ref.lower() in truthy | {"true", "1", "对", "正确", "是"})
        return {
            "score": 100 if ok else 0,
            "correct": ok,
            "feedback": "回答正确。" if ok else f"回答不正确，正确答案是：{ref}",
            "missing_points": [] if ok else [ref],
        }

    if not ua:
        return {"score": 0, "correct": False, "feedback": "未作答。", "missing_points": keywords(ref, 5)}

    ref_terms = set(keywords(ref, 12)) or set(tokenize(ref))
    hit = [t for t in ref_terms if t in ua]
    miss = [t for t in ref_terms if t not in ua]
    coverage = len(hit) / len(ref_terms) if ref_terms else 0.5

    # 篇幅合理性：过短扣分，充分展开加分（上限 1.0）
    length_factor = min(len(ua) / max(len(ref) * 0.6, 40), 1.0)
    score = round(coverage * 70 + length_factor * 30, 1)

    if score >= 85:
        comment = "要点覆盖充分，表述完整。"
    elif score >= 60:
        comment = "抓住了主要方向，但部分要点缺失。"
    else:
        comment = "与参考答案差距较大，建议对照要点重做。"
    if miss:
        comment += " 建议补充：" + "、".join(miss[:6]) + "。"

    return {
        "score": min(score, 100.0),
        "correct": score >= 60,
        "feedback": comment,
        "missing_points": miss[:8],
        "coverage": round(coverage, 2),
    }
