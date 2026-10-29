"""AI 助手接口：状态 / 笔记摘要 / 笔记问答 / 聊天助手 / 出题 / 批改 / 创作工具

约定
----
- 所有能力在「未配置 LLM_API_KEY」时自动降级为本地实现，接口结构与返回字段完全一致，
  仅 `provider` 从 `llm` 变为 `local`，因此前端无需分叉。
- 每次调用都会写 AIUsageLog，便于观察降级比例与失败原因。
- 计算类接口统一兜底：ValueError → 400，其余异常 → 422，绝不 500。
"""
from __future__ import annotations

import random
from functools import wraps
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant import generators, llm, retrieval
from assistant.models import AIConversation, AIGeneratedQuestion, AIMessage, AIPrompt
from core.scoping import scope_queryset
from core.validators import as_int, parse_bool

SYSTEM_TUTOR = (
    "你是「全能协作平台」内置的知识助手。回答要准确、简洁、结构清晰，"
    "优先依据用户提供的资料作答；资料不足时明确说明，不要编造。"
    "使用简体中文回答，必要时用列表或步骤组织内容。"
)

MAX_INPUT_CHARS = 12000


def endpoint(methods=("POST",)):
    """视图方法兜底装饰器：ValueError → 400，其余异常 → 422（结构化 {ok:false,error}）"""

    def deco(fn):
        @wraps(fn)
        def impl(self, request, *args, **kwargs):
            try:
                return fn(self, request, *args, **kwargs)
            except ValueError as exc:
                return Response({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:  # noqa: BLE001 —— 结构化降级，绝不 500
                return Response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status=422)

        return impl

    return deco


def _note_or_404(user, pk):
    from notes.models import Note

    return scope_queryset(Note.objects.filter(is_deleted=False), user).filter(pk=pk).first()


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------

class AIStatusView(APIView):
    """当前 AI 能力状态：是否接入大模型、支持哪些功能、如何配置"""

    def get(self, request):
        from assistant.models import AIUsageLog

        info = llm.status()
        recent = AIUsageLog.objects.filter(owner=request.user)[:20]
        info["recent_calls"] = [
            {"feature": r.feature, "provider": r.provider, "success": r.success,
             "duration_ms": r.duration_ms, "created_at": r.created_at}
            for r in recent
        ]
        info["recent_success_rate"] = (
            round(sum(1 for r in recent if r.success) / len(recent) * 100, 1) if recent else None
        )
        return Response(info)


# ---------------------------------------------------------------------------
# 笔记摘要
# ---------------------------------------------------------------------------

class NoteSummarizeView(APIView):
    """笔记 AI 摘要。

    POST /api/assistant/notes/<pk>/summarize/
        {"force": false, "length": "short|medium|detail", "mode": "one_line|bullets|paragraph"}
    结果会缓存到 Note.ai_summary，除非 force=true 否则不重复调用大模型。

    F652 摘要三档切换：`mode` 参数化既有 summarize 接口，返回体同时给出
    `modes`（一句话 / 要点列表 / 段落 三种口径）与按 mode 选出的 `result`。
    """

    MODES = ("one_line", "bullets", "paragraph")

    def post(self, request, pk):
        note = _note_or_404(request.user, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=status.HTTP_404_NOT_FOUND)

        content = note.content or ""
        if not content.strip():
            return Response({"message": "笔记内容为空，无法生成摘要"}, status=400)

        mode = (request.data.get("mode") or "").strip()
        if mode and mode not in self.MODES:
            return Response({"message": f"mode 只能是 {' / '.join(self.MODES)}"}, status=400)

        force = parse_bool(request.data.get("force"), field="force")
        if note.ai_summary and not force:
            points = llm.bullet_points(content, 5)
            modes = _summary_modes(note.ai_summary, points, content)
            return Response({
                "summary": note.ai_summary, "note_id": note.id, "title": note.title,
                "provider": "cache", "model": "", "cached": True,
                "key_points": points,
                "generated_at": note.ai_summary_at,
                "mode": mode or "paragraph", "modes": modes,
                "result": modes.get(mode, note.ai_summary) if mode else note.ai_summary,
            })

        length = request.data.get("length") or "medium"
        detail_hint = {
            "short": "用 2-3 句话概括。",
            "medium": "用一段话（120-200 字）概括。",
            "detail": "分「核心结论 / 关键要点 / 待办或风险」三部分详细总结。",
        }.get(length, "用一段话概括。")

        prompt = (
            f"请为下面这篇笔记生成摘要。{detail_hint}\n"
            "输出格式：第一行是摘要正文；随后以「要点：」开头，用 - 列出 3-5 个关键要点。\n\n"
            f"笔记标题：{note.title}\n笔记正文：\n{content[:MAX_INPUT_CHARS]}"
        )
        result = llm.chat(
            [{"role": "system", "content": SYSTEM_TUTOR}, {"role": "user", "content": prompt}],
            temperature=0.2,
        )
        llm.log_usage(request.user.id, "note_summarize", result, len(prompt), len(result.get("content") or ""))

        if result["ok"]:
            summary = result["content"]
            points = _extract_points(summary)
            if points:
                summary = summary.split("要点")[0].strip()
        else:
            summary = llm.extractive_summary(content, 5)
            points = llm.bullet_points(content, 5)

        note.ai_summary = summary[:4000]
        from django.utils import timezone

        note.ai_summary_at = timezone.now()
        note.save(update_fields=["ai_summary", "ai_summary_at"])

        modes = _summary_modes(summary, points, content)
        return Response({
            "summary": summary, "key_points": points, "note_id": note.id, "title": note.title,
            "provider": result["provider"], "model": result.get("model", ""), "cached": False,
            "fallback_reason": "" if result["ok"] else result.get("error", ""),
            "generated_at": note.ai_summary_at,
            "mode": mode or "paragraph", "modes": modes,
            "result": modes.get(mode, summary) if mode else summary,
        })

    def get(self, request, pk):
        note = _note_or_404(request.user, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        points = llm.bullet_points(note.content, 5) if note.content else []
        modes = _summary_modes(note.ai_summary or "", points, note.content or "")
        return Response({
            "summary": note.ai_summary, "note_id": note.id, "title": note.title,
            "cached": bool(note.ai_summary), "generated_at": note.ai_summary_at,
            "key_points": points, "modes": modes,
        })


def _summary_modes(summary: str, points, content: str) -> dict:
    """F652：把一份摘要切成三档口径（一句话 / 要点列表 / 段落），纯本地可算"""
    para = (summary or "").strip()
    sents = llm.split_sentences(para, min_len=4)
    one = sents[0] if sents else ""
    if not one:
        one = llm.extractive_summary(content or "", 1)
    bullets = [str(p).strip() for p in (points or []) if str(p).strip()]
    if not bullets:
        bullets = llm.bullet_points(content or "", 5)
    if not bullets:
        bullets = [s for s in sents if s.strip()][:5]
    return {
        "one_line": one[:300],
        "bullets": bullets[:6],
        "paragraph": para or ("".join(sents[:3])),
    }


def _extract_points(text: str):
    """从大模型输出里抽出「要点」列表"""
    if not text:
        return []
    marker = "要点"
    idx = text.find(marker)
    if idx < 0:
        return []
    tail = text[idx:]
    points = []
    for line in tail.splitlines()[1:]:
        line = line.strip().lstrip("-•*·").strip()
        if len(line) >= 4:
            points.append(line[:200])
    return points[:8]


# ---------------------------------------------------------------------------
# 笔记问答（RAG-lite）
# ---------------------------------------------------------------------------

class NoteAskView(APIView):
    """针对单篇笔记提问。

    POST /api/assistant/notes/<pk>/ask/  {"question": "..."}
    回答附带引用片段，便于核对来源。
    """

    def post(self, request, pk):
        note = _note_or_404(request.user, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=status.HTTP_404_NOT_FOUND)
        question = (request.data.get("question") or "").strip()
        if not question:
            return Response({"message": "请输入问题"}, status=400)
        if not (note.content or "").strip():
            return Response({"message": "笔记内容为空"}, status=400)
        return Response(_answer_question(request.user, question, [note]))


class AssistantAskView(APIView):
    """跨笔记问答：自动检索个人知识库里最相关的片段再回答。

    POST /api/assistant/ask/  {"question": "...", "note_ids": [1,2], "keyword": "架构"}
    """

    def post(self, request):
        question = str(request.data.get("question") or "").strip()
        if not question:
            return Response({"message": "请输入问题"}, status=400)

        raw_ids = request.data.get("note_ids") or None
        if raw_ids is not None and not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "note_ids 必须是数组"}, status=400)
        try:
            note_ids = {as_int(i, field="note_ids", minimum=1) for i in raw_ids} if raw_ids else None
        except ValidationError:
            return Response({"message": "note_ids 必须全部为整数"}, status=400)
        keyword = str(request.data.get("keyword") or "").strip()
        notes = list(retrieval.search_notes(request.user, keyword or question, limit=30))
        if note_ids:
            allowed = note_ids
            notes = [n for n in notes if n.id in allowed] or list(
                scope_queryset(_note_model().objects.filter(id__in=allowed, is_deleted=False), request.user)
            )
        if not notes:
            return Response({"message": "没有可检索的笔记，请先创建一些内容"}, status=404)
        return Response(_answer_question(request.user, question, notes))


def _note_model():
    from notes.models import Note

    return Note


def _answer_question(user, question, notes):
    """检索 + 生成（大模型或本地降级）"""
    chunks = []
    for note in notes:
        for chunk in retrieval.chunk_text(note.content):
            chunks.append({
                "title": note.title,
                "text": f"# {note.title}\n{chunk}",
                "ref": {"note_id": note.id, "title": note.title},
            })

    picked = retrieval.rank_chunks(question, chunks, top_k=4)
    references = [
        {"note_id": c["ref"]["note_id"], "title": c["ref"]["title"], "excerpt": c["text"][:160]}
        for c in picked
    ]

    if not picked:
        local = llm.answer_from_context(question, chunks)
        return {"answer": local["answer"], "references": local["references"],
                "provider": "local", "model": "local-extractive", "confidence": local["confidence"],
                "fallback_reason": "未检索到相关片段"}

    context = retrieval.build_context(picked)
    prompt = (
        "根据下面的资料回答用户问题。只使用资料中的信息；"
        "如果资料不足以回答，请明确说明「资料中未提及」。"
        "回答末尾不要重复资料原文，直接给结论。\n\n"
        f"=== 资料开始 ===\n{context}\n=== 资料结束 ===\n\n问题：{question}"
    )
    result = llm.chat(
        [{"role": "system", "content": SYSTEM_TUTOR}, {"role": "user", "content": prompt}],
        temperature=0.2,
    )
    llm.log_usage(user.id, "note_ask", result, len(prompt), len(result.get("content") or ""))

    if result["ok"]:
        return {"answer": result["content"], "references": references, "provider": "llm",
                "model": result["model"], "confidence": 1.0, "fallback_reason": ""}

    local = llm.answer_from_context(question, picked)
    return {"answer": local["answer"], "references": references, "provider": "local",
            "model": "local-extractive", "confidence": local["confidence"],
            "fallback_reason": result.get("error", "")}


# ---------------------------------------------------------------------------
# 聊天助手
# ---------------------------------------------------------------------------

class ConversationListView(APIView):
    """我的 AI 会话列表 / 新建会话

    F643 对话按日分组：列表返回 created_at / updated_at / date（YYYY-MM-DD），
    前端据此把会话按日分组并在左侧日期轴上跳转。
    """

    @endpoint(("GET",))
    def get(self, request):
        qs = AIConversation.objects.filter(owner=request.user)
        items = []
        for c in qs[:80]:
            items.append({
                "id": c.id, "title": c.title, "model": c.model, "message_count": c.message_count,
                "scene": c.scene, "created_at": c.created_at, "updated_at": c.updated_at,
                "date": c.updated_at.date().isoformat(),
                "created_date": c.created_at.date().isoformat(),
                "parent_conversation_id": c.parent_conversation_id,
                "parent_message_id": c.parent_message_id,
            })
        return Response({"list": items, "total": qs.count()})

    @endpoint(("POST",))
    def post(self, request):
        c = AIConversation.objects.create(
            owner=request.user,
            title=(request.data.get("title") or "新对话")[:120],
            scene=request.data.get("scene") or "chat",
            model=llm.status()["model"],
        )
        return Response({"id": c.id, "title": c.title}, status=201)


class ConversationDetailView(APIView):
    """会话消息 / 重命名 / 删除"""

    def _get(self, request, pk):
        return AIConversation.objects.filter(pk=pk, owner=request.user).first()

    @endpoint(("GET",))
    def get(self, request, pk):
        c = self._get(request, pk)
        if not c:
            return Response({"message": "会话不存在"}, status=404)
        return Response({
            "id": c.id, "title": c.title, "model": c.model, "updated_at": c.updated_at,
            "created_at": c.created_at, "date": c.updated_at.date().isoformat(),
            "parent_conversation_id": c.parent_conversation_id,
            "parent_message_id": c.parent_message_id,
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content,
                 "provider": m.provider, "references": m.references, "created_at": m.created_at}
                for m in c.messages.all()
            ],
        })

    def patch(self, request, pk):
        c = self._get(request, pk)
        if not c:
            return Response({"message": "会话不存在"}, status=404)
        if request.data.get("title"):
            c.title = request.data["title"][:120]
            c.save(update_fields=["title", "updated_at"])
        return Response({"id": c.id, "title": c.title})

    def delete(self, request, pk):
        c = self._get(request, pk)
        if not c:
            return Response({"message": "会话不存在"}, status=404)
        c.delete()
        return Response({"message": "会话已删除"})


class ChatView(APIView):
    """LLM 聊天助手（带历史上下文 + 可选知识库检索增强）

    POST /api/assistant/chat/  {"message": "...", "conversation_id": 1, "use_knowledge": true}
    """

    HISTORY_LIMIT = 12

    @endpoint(("POST",))
    def post(self, request):
        message = (request.data.get("message") or "").strip()
        if not message:
            return Response({"message": "请输入内容"}, status=400)

        conv = None
        cid = request.data.get("conversation_id")
        if cid:
            conv = AIConversation.objects.filter(pk=cid, owner=request.user).first()
        if conv is None:
            conv = AIConversation.objects.create(
                owner=request.user, title=message[:40], model=llm.status()["model"]
            )

        AIMessage.objects.create(conversation=conv, role="user", content=message[:MAX_INPUT_CHARS])

        use_knowledge = request.data.get("use_knowledge", True)
        references = []
        context = ""
        if use_knowledge:
            notes = list(retrieval.search_notes(request.user, message, limit=15))
            chunks = []
            for note in notes:
                for chunk in retrieval.chunk_text(note.content):
                    chunks.append({"title": note.title, "text": f"# {note.title}\n{chunk}",
                                   "ref": {"note_id": note.id, "title": note.title}})
            picked = retrieval.rank_chunks(message, chunks, top_k=3)
            if picked:
                context = retrieval.build_context(picked, max_chars=3000)
                references = [
                    {"note_id": c["ref"]["note_id"], "title": c["ref"]["title"]}
                    for c in picked
                ]

        history = [
            {"role": m.role, "content": m.content}
            for m in conv.messages.order_by("-id")[: self.HISTORY_LIMIT][::-1]
            if m.role in ("user", "assistant")
        ]
        if context:
            history.insert(0, {
                "role": "system",
                "content": f"以下是用户知识库中与问题相关的资料，回答时优先参考：\n{context}",
            })
        messages = [{"role": "system", "content": SYSTEM_TUTOR}] + history

        result = llm.chat(messages, temperature=0.4)
        llm.log_usage(request.user.id, "chat", result,
                      sum(len(m["content"]) for m in messages), len(result.get("content") or ""))

        if result["ok"]:
            reply = result["content"]
        else:
            reply = _local_chat_reply(message, references)
            if not reply:
                reply = ("当前未配置大模型（环境变量 LLM_API_KEY），已降级为本地应答。\n\n"
                         f"{result.get('error', '')}\n\n"
                         "本地模式下我可以：检索你的笔记并返回相关片段、提炼要点、"
                         "生成练习题、批改答案。配好 Key 后我会用大模型完整作答。")

        AIMessage.objects.create(
            conversation=conv, role="assistant", content=reply[:MAX_INPUT_CHARS],
            provider=result["provider"], references=references,
        )
        conv.message_count = conv.messages.count()
        conv.model = result.get("model", conv.model)
        conv.save(update_fields=["message_count", "model", "updated_at"])

        return Response({
            "conversation_id": conv.id,
            "reply": reply,
            "provider": result["provider"],
            "model": result.get("model", ""),
            "references": references,
            "fallback_reason": "" if result["ok"] else result.get("error", ""),
        })


def _local_chat_reply(message: str, references):
    """本地降级时的聊天回复：给出检索到的相关笔记片段"""
    if not references:
        return ""
    titles = "、".join(f"《{r['title']}》" for r in references[:3])
    return (f"（本地检索模式，未调用大模型）你在 {titles} 中有相关内容，"
            "下面是可以参考的片段：\n\n"
            + "\n\n".join(f"- 《{r['title']}》" for r in references[:3]))


# ---------------------------------------------------------------------------
# AI 出题
# ---------------------------------------------------------------------------

class QuestionGenerateView(APIView):
    """AI 出题：有 Key 时由大模型生成新题，无 Key 时从内置题库智能抽题（打乱选项）。

    POST /api/assistant/questions/generate/
        {"topic": "一元二次方程", "count": 5, "type": "single|judge|fill|subjective|code",
         "difficulty": 2, "subject": "math", "stage": "junior", "save": true}
    """

    TYPE_ALIAS = {
        "single": "single", "judge": "judge", "fill": "fill",
        "subjective": "subjective", "code": "code",
        "choice": "single", "编程": "code", "主观": "subjective",
    }

    def post(self, request):
        topic = (request.data.get("topic") or "").strip()
        count = as_int(request.data.get("count"), default=5, field="count", minimum=1, maximum=10)
        qtype = self.TYPE_ALIAS.get(str(request.data.get("type") or "single"), "single")
        difficulty = as_int(request.data.get("difficulty"), default=2, field="difficulty", minimum=1, maximum=5)
        save = parse_bool(request.data.get("save"), default=True, field="save")

        if not topic:
            return Response({"message": "请提供知识点或主题"}, status=400)

        items, result = self._generate(topic, count, qtype, difficulty, request.data)
        llm.log_usage(request.user.id, "generate_questions", result,
                      len(topic), sum(len(i.get("stem", "")) for i in items))

        source = "llm" if result["ok"] else "bank"
        if not items:
            return Response({"message": "生成失败，且题库中没有匹配的题目",
                             "code": result.get("code", ""), "detail": result.get("error", "")}, status=404)

        saved_ids = []
        if save:
            for item in items:
                obj = AIGeneratedQuestion.objects.create(
                    owner=request.user, topic=topic[:120], question_type=qtype,
                    difficulty=difficulty, stem=item.get("stem", ""),
                    options=item.get("options") or [], answer=str(item.get("answer", "")),
                    analysis=item.get("analysis", ""), source=source,
                    provider=result.get("provider", ""),
                )
                saved_ids.append(obj.id)
                item["id"] = obj.id

        return Response({
            "topic": topic, "type": qtype, "difficulty": difficulty, "count": len(items),
            "items": items, "source": source, "provider": result.get("provider", "local"),
            "model": result.get("model", ""),
            "saved_ids": saved_ids,
            "fallback_reason": "" if result["ok"] else result.get("error", ""),
        })

    def _generate(self, topic, count, qtype, difficulty, data):
        if llm.is_configured():
            items, result = self._generate_by_llm(topic, count, qtype, difficulty, data)
            if items:
                return items, result
        else:
            result = {"ok": False, "provider": "local", "model": "local-extractive",
                      "error": "未配置 LLM_API_KEY", "code": "NOT_CONFIGURED", "duration_ms": 0}
        # 降级：从内置题库抽题
        return self._draw_from_bank(topic, count, qtype, difficulty, data), result

    def _generate_by_llm(self, topic, count, qtype, difficulty, data):
        type_hint = {
            "single": '每题为单选题，options 是 4 个选项字符串，answer 是正确选项的下标（0-3 的整数）',
            "judge": "每题为判断题，answer 只能是 true 或 false",
            "fill": "每题为填空题，题干用 ____ 表示空，answer 是参考答案字符串",
            "subjective": "每题为主观题，answer 是参考答案要点（分点写）",
            "code": "每题为编程题，题干包含需求描述与输入输出示例，answer 是参考代码",
        }[qtype]
        subject = data.get("subject") or ""
        prompt = (
            f"请围绕知识点「{topic}」生成 {count} 道难度为 {difficulty}/5 的练习题。"
            f"{type_hint}。{'学科：' + subject if subject else ''}\n"
            '严格输出 JSON：{"items":[{"stem":"题干","options":["A","B","C","D"],'
            '"answer":"参考答案","analysis":"解析"}]}\n'
            "题干与解析使用简体中文；不要输出 JSON 以外的任何内容。"
        )
        parsed, result = llm.chat_json(
            [{"role": "system", "content": "你是资深教研老师，擅长命题。"},
             {"role": "user", "content": prompt}],
            fallback=None,
        )
        if parsed and isinstance(parsed.get("items"), list):
            cleaned = []
            for item in parsed["items"][:count]:
                if not isinstance(item, dict) or not item.get("stem"):
                    continue
                cleaned.append({
                    "stem": str(item.get("stem"))[:1000],
                    "options": [str(o)[:200] for o in (item.get("options") or [])][:6],
                    "answer": item.get("answer", ""),
                    "analysis": str(item.get("analysis") or "")[:1000],
                })
            if cleaned:
                return cleaned, result
        return [], result

    def _draw_from_bank(self, topic, count, qtype, difficulty, data):
        """降级策略：从 K12 题库按主题匹配抽题，并打乱单选题选项顺序"""
        from learning.data import questions as qb

        pool = [q for q in qb.QUESTIONS if q["type"] == qtype]
        if not pool:
            pool = list(qb.QUESTIONS)

        terms = [t for t in (topic or "") if "\u4e00" <= t <= "\u9fff"] or [topic]
        def relevance(q):
            hay = f"{q.get('stem','')}{q.get('kp','')}{q.get('analysis','')}"
            return sum(1 for t in terms if t and t in hay)

        scored = sorted(pool, key=lambda q: (relevance(q), -abs(q.get("difficulty", 2) - difficulty)), reverse=True)
        picked = scored[: max(count * 2, count)]
        random.shuffle(picked)
        picked = picked[:count]

        items = []
        for q in picked:
            item = {"stem": q["stem"], "answer": "", "analysis": q.get("analysis", ""),
                    "options": list(q.get("options") or []), "source_id": q["id"],
                    "kp": q.get("kp", "")}
            if qtype == "single" and item["options"]:
                correct = q["answer"]
                opts = list(item["options"])
                order = list(range(len(opts)))
                random.shuffle(order)
                item["options"] = [opts[i] for i in order]
                item["answer"] = order.index(correct)
            else:
                item["answer"] = q["answer"]
            items.append(item)
        return items


class GeneratedQuestionListView(APIView):
    """我生成的题目：列表 / 删除"""

    def get(self, request):
        qs = AIGeneratedQuestion.objects.filter(owner=request.user)
        topic = request.query_params.get("topic")
        if topic:
            qs = qs.filter(topic__icontains=topic)
        try:
            limit = as_int(request.query_params.get("limit"), default=50, field="limit", minimum=1, maximum=200)
        except ValidationError:
            return Response({"message": "limit 必须是 1-200 的整数"}, status=400)
        return Response({"list": [
            {"id": q.id, "topic": q.topic, "question_type": q.question_type, "difficulty": q.difficulty,
             "stem": q.stem, "options": q.options, "answer": q.answer, "analysis": q.analysis,
             "source": q.source, "created_at": q.created_at}
            for q in qs[:limit]
        ], "total": qs.count()})

    def delete(self, request):
        raw_ids = request.data.get("ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "ids 必须是数组"}, status=400)
        try:
            ids = [as_int(i, field="ids", minimum=1) for i in raw_ids]
        except ValidationError:
            return Response({"message": "ids 必须全部为整数"}, status=400)
        if not ids:
            return Response({"message": "未选择题目"}, status=400)
        n = AIGeneratedQuestion.objects.filter(owner=request.user, id__in=ids).delete()[0]
        return Response({"message": f"已删除 {n} 道题"})


# ---------------------------------------------------------------------------
# AI 批改
# ---------------------------------------------------------------------------

class GradeView(APIView):
    """AI 批改：主观题 / 编程题 / 客观题都能改。

    POST /api/assistant/grade/
        {"items": [{"question": "...", "reference_answer": "...", "user_answer": "...",
                    "type": "subjective|code|single|judge|fill", "language": "python",
                    "topic": "..."}],
         "record_mistakes": true}

    主观/编程题有 Key 时由大模型评分并给出改进建议；无 Key 时用
    「参考答案关键词覆盖率 + 篇幅」启发式打分，同样返回评分与缺失要点。
    """

    def post(self, request):
        items = request.data.get("items")
        if not items and request.data.get("question"):
            items = [request.data]
        if not isinstance(items, list) or not items:
            return Response({"message": "请提供待批改的题目"}, status=400)
        items = items[:20]

        record = parse_bool(request.data.get("record_mistakes"), default=True, field="record_mistakes")
        results, provider, model, fallback = [], "local", "local-heuristic", ""

        for idx, item in enumerate(items):
            qtype = str(item.get("type") or "subjective")
            question = item.get("question") or item.get("stem") or ""
            reference = str(item.get("reference_answer") or item.get("answer") or "")
            user_answer = str(item.get("user_answer") or "")

            graded = None
            if llm.is_configured() and qtype in ("subjective", "code"):
                graded, result = self._grade_by_llm(question, reference, user_answer, qtype,
                                                    item.get("language"), item.get("topic"))
                provider, model = result.get("provider", "llm"), result.get("model", "")
                if graded is None:
                    fallback = result.get("error", "")
                    llm.log_usage(request.user.id, "grade", result, len(question), 0)
            if graded is None:
                graded = llm.heuristic_grade(question, reference, user_answer, qtype)

            graded["index"] = idx
            graded["question"] = question[:200]
            results.append(graded)

        scored = [r["score"] for r in results]
        total = round(sum(scored) / len(scored), 1) if scored else 0

        recorded = 0
        if record:
            recorded = self._record_mistakes(request.user, items, results)

        return Response({
            "total": len(results), "average_score": total,
            "passed": sum(1 for r in results if r.get("correct")),
            "items": results, "provider": provider, "model": model,
            "fallback_reason": fallback,
            "recorded_mistakes": recorded,
        })

    def _grade_by_llm(self, question, reference, user_answer, qtype, language, topic):
        if qtype == "code":
            role = "你是资深程序员与技术面试官。"
            extra = f"编程语言：{language or '不限'}。请评估正确性、边界处理、复杂度与代码风格。"
        else:
            role = "你是严谨的阅卷老师。"
            extra = "请对照参考答案要点给分，指出遗漏或错误之处。"
        prompt = (
            f"请批改下面这道题。{extra}\n\n"
            f"题目：{question}\n参考答案：{reference}\n学生作答：{user_answer}\n\n"
            '严格输出 JSON：{"score": 0-100 的分数, "correct": true/false, '
            '"feedback":"评语（简体中文，指出优缺点与改进方向）", '
            '"missing_points":["遗漏要点1","遗漏要点2"]}\n'
            "不要输出 JSON 以外的内容。"
        )
        parsed, result = llm.chat_json(
            [{"role": "system", "content": role}, {"role": "user", "content": prompt}],
            fallback=None, temperature=0.1,
        )
        if not parsed:
            return None, result
        try:
            score = float(parsed.get("score", 0))
        except Exception:
            return None, result
        return {
            "score": max(0.0, min(score, 100.0)),
            "correct": bool(parsed.get("correct", score >= 60)),
            "feedback": str(parsed.get("feedback", ""))[:2000],
            "missing_points": [str(p)[:200] for p in (parsed.get("missing_points") or [])][:8],
        }, result

    def _record_mistakes(self, user, items, results):
        """把未通过的题目写入学习中心的错题本，形成「练—错—复习」闭环"""
        try:
            from learning.models import MistakeRecord
        except Exception:
            return 0
        created = 0
        for item, graded in zip(items, results):
            if graded.get("score", 0) >= 60:
                continue
            MistakeRecord.objects.create(
                owner=user,
                stage=str(item.get("stage") or "")[:20],
                subject=str(item.get("subject") or item.get("topic") or "")[:20],
                question_type={"single": "single", "judge": "judge", "fill": "fill",
                               "code": "output"}.get(str(item.get("type")), "other"),
                difficulty=int(item.get("difficulty") or 1),
                stem=str(item.get("question") or item.get("stem") or "")[:2000],
                answer=str(item.get("reference_answer") or item.get("answer") or "")[:255],
                user_answer=str(item.get("user_answer") or "")[:255],
                analysis=str(graded.get("feedback") or "")[:2000],
            )
            created += 1
        return created


# ---------------------------------------------------------------------------
# AI 自动标签（#59 / #66）
# ---------------------------------------------------------------------------

class AutoTagView(APIView):
    """根据文本内容推荐标签。

    POST /api/assistant/auto-tag/  {"text": "...", "title": "...", "count": 6}
    有 Key 时由大模型给出结构化标签；无 Key 时用本地关键词提取降级。
    前端拿到 tags 后由用户勾选确认再应用（配合 #66 标签建议浮层）。
    """

    def post(self, request):
        text = (request.data.get("text") or "")[:8000]
        title = (request.data.get("title") or "")[:200]
        try:
            count = max(2, min(int(request.data.get("count") or 6), 12))
        except (TypeError, ValueError):
            count = 6
        combined = f"{title}\n{text}".strip()
        if not combined.strip():
            return Response({"message": "文本为空，无法打标签"}, status=400)

        tags, provider, model, fallback = [], "local", "local-keywords", ""

        if llm.is_configured():
            prompt = (
                f"为下面这段内容生成 {count} 个简短标签（每个 2~6 个字，中文优先），"
                "用于笔记/文件分类。只输出 JSON 数组，例如 [\"标签1\",\"标签2\"]，不要解释。\n\n"
                f"标题：{title}\n内容：\n{combined[:3000]}"
            )
            parsed, result = llm.chat_json(
                [{"role": "system", "content": "你是内容标签助手。"},
                 {"role": "user", "content": prompt}],
                fallback=None,
            )
            llm.log_usage(request.user.id, "auto_tag", result, len(combined), 0)
            if isinstance(parsed, list):
                tags = [str(t)[:20] for t in parsed if str(t).strip()][:count]
                provider, model = result.get("provider", "llm"), result.get("model", "")
            else:
                fallback = result.get("error", "")

        if not tags:
            tags = llm.keywords(combined, top=count)
            for w in llm.keywords(title, top=max(0, count - len(tags))):
                if w not in tags:
                    tags.append(w)
            provider = "local"

        return Response({
            "tags": tags, "provider": provider, "model": model,
            "fallback_reason": fallback, "confirmed": False,
        })


# ---------------------------------------------------------------------------
# 写作助手内嵌（#61）：润色 / 扩写 / 缩写 / 纠错
# ---------------------------------------------------------------------------

class PolishView(APIView):
    """写作润色：复用 assistant chat，无 Key 时本地降级。

    POST /api/assistant/polish/  {"text": "...", "mode": "polish|expand|shorten|fix"}
    """

    MODES = {
        "polish": "润色：让表达更流畅、专业、得体，保持原意。",
        "expand": "扩写：在原意基础上补充细节与例子，使内容更充实。",
        "shorten": "缩写：精简冗余，保留核心意思，缩短篇幅。",
        "fix": "纠错：修正错别字、语病与标点，不通顺处改写。",
    }

    def post(self, request):
        text = (request.data.get("text") or "").strip()
        if not text:
            return Response({"message": "请输入要润色的文本"}, status=400)
        mode = request.data.get("mode") or "polish"
        if mode not in self.MODES:
            mode = "polish"

        prompt = (f"{self.MODES[mode]}\n\n原文：\n{text[:MAX_INPUT_CHARS]}"
                   "\n\n直接输出处理后的文本，不要解释。")
        result = llm.chat(
            [{"role": "system", "content": "你是中文写作助手。"},
             {"role": "user", "content": prompt}],
            temperature=0.5,
        )
        llm.log_usage(request.user.id, "polish", result, len(text), len(result.get("content") or ""))

        if result["ok"]:
            out = result["content"]
        else:
            out = _local_polish(text, mode)

        return Response({
            "original": text, "result": out, "mode": mode,
            "provider": result["provider"] if result["ok"] else "local",
            "model": result.get("model", "") if result["ok"] else "local-heuristic",
            "fallback_reason": "" if result["ok"] else result.get("error", ""),
        })


_POLISH_REPL = [
    ("非常非常", "非常"),
    ("十分非常", "十分"),
    ("然后然后", "然后"),
    ("的的", "的"),
    ("了了", "了"),
    ("我觉得我认为", "我认为"),
    ("这个东西", "该对象"),
    ("那个东西", "该对象"),
]


def _local_polish(text: str, mode: str) -> str:
    """无 Key 时的本地降级：冗余清理 + 句式微调，不改变原意"""
    out = text
    for a, b in _POLISH_REPL:
        out = out.replace(a, b)
    lines = [ln.rstrip() for ln in out.replace("\r\n", "\n").split("\n")]
    cleaned, blank = [], 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 1:
                cleaned.append("")
        else:
            blank = 0
            cleaned.append(ln)
    out = "\n".join(cleaned).strip()
    if mode == "shorten":
        sents = llm.split_sentences(out, min_len=6)
        out = "".join(sents[: max(1, len(sents) // 2)])
    elif mode == "expand":
        out = out + "\n\n（本地降级模式：未配置大模型，扩写请配置 LLM_API_KEY 后使用。）"
    elif mode == "fix":
        out = _auto_punct(out)
    return out


def _auto_punct(text: str) -> str:
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if s and not s.endswith(("。", "！", "？", "；", ".", "!", "?", ";", ":", "：")):
            if any("\u4e00" <= ch <= "\u9fff" for ch in s):
                s += "。"
        lines.append(s)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AI 每日摘要日报（#60）
# ---------------------------------------------------------------------------

class DailyDigestView(APIView):
    """汇总当日新增笔记/文件，生成摘要并写入通知中心。

    POST /api/assistant/daily-digest/  {"date": "2026-09-25"}  (date 缺省=今天)
    """

    def post(self, request):
        from django.utils import timezone
        from notes.models import Note
        from files.models import FileMeta

        day_str = request.data.get("date") or ""
        if day_str:
            try:
                target = timezone.datetime.strptime(day_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"message": "date 需为 YYYY-MM-DD"}, status=400)
        else:
            target = timezone.localdate()

        notes = scope_queryset(
            Note.objects.filter(is_deleted=False, created_at__date=target), request.user
        ).order_by("-created_at")
        files = scope_queryset(
            FileMeta.objects.filter(is_deleted=False, created_at__date=target), request.user
        ).order_by("-created_at")

        note_items = [n.title for n in notes[:20]]
        file_items = [f.name for f in files[:20]]
        note_bodies = "\n".join((n.content or "")[:500] for n in notes[:5])
        summary = llm.extractive_summary(note_bodies, max_sentences=5) if note_bodies else ""

        digest = {
            "date": target.isoformat(),
            "note_count": notes.count(),
            "file_count": files.count(),
            "notes": note_items,
            "files": file_items,
            "summary": summary or "今日暂无新增笔记正文可摘要。",
        }

        from core.models import notify
        notify(
            request.user,
            title=f"每日摘要 · {target.isoformat()}",
            content=f"新增笔记 {digest['note_count']} 篇，文件 {digest['file_count']} 个。"
                    + (("\n要点：" + summary[:120]) if summary else ""),
            category="note", level="info",
        )
        return Response({"digest": digest, "provider": "local", "notified": True})


# ---------------------------------------------------------------------------
# F644 提示词库（收藏常用提示词 CRUD + 一键插入输入框）
# ---------------------------------------------------------------------------

BUILTIN_PROMPTS = [
    ("总结要点", "请把下面的内容总结成 5 条要点，每条不超过 30 字：\n\n", "总结"),
    ("写作润色", "请润色下面的文字，使其更流畅、专业，保持原意，只输出润色结果：\n\n", "写作"),
    ("翻译成英文", "请把下面的内容翻译成英文，只输出译文：\n\n", "翻译"),
    ("解释概念", "请用通俗易懂的方式解释这个概念，并举一个生活中的例子：", "学习"),
    ("代码评审", "请评审下面的代码，指出问题并给出 3 条改进建议：\n\n", "编程"),
    ("会议纪要", "请把下面的会议记录整理成纪要，包含议题、结论与行动项：\n\n", "办公"),
    ("写周报", "请根据下面的要点生成一份工作周报，包含本周进展、风险与下周计划：\n\n", "办公"),
    ("起名建议", "请为我起 8 个候选名，说明寓意与风格：", "创作"),
]


def _seed_builtin_prompts(user):
    """首次进入提示词库时补内置提示词（幂等，不覆盖用户改动）"""
    for title, content, category in BUILTIN_PROMPTS:
        AIPrompt.objects.get_or_create(
            owner=user, title=title,
            defaults={"content": content, "category": category, "is_builtin": True},
        )


def _prompt_json(p: AIPrompt) -> dict:
    return {
        "id": p.id, "title": p.title, "content": p.content, "category": p.category,
        "is_favorite": p.is_favorite, "is_builtin": p.is_builtin,
        "usage_count": p.usage_count, "created_at": p.created_at, "updated_at": p.updated_at,
    }


class PromptLibraryView(APIView):
    """提示词库：GET 列表（收藏/分类/关键词过滤）· POST 新建"""

    @endpoint(("GET",))
    def get(self, request):
        from django.db.models import Q

        _seed_builtin_prompts(request.user)
        base = AIPrompt.objects.filter(owner=request.user)
        qs = base
        if request.query_params.get("favorite") == "1":
            qs = qs.filter(is_favorite=True)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q))
        return Response({
            "list": [_prompt_json(p) for p in qs.order_by("-is_favorite", "-updated_at")[:200]],
            "total": qs.count(),
            "favorite_count": base.filter(is_favorite=True).count(),
            "categories": sorted({c for c in base.values_list("category", flat=True) if c}),
        })

    @endpoint(("POST",))
    def post(self, request):
        title = (request.data.get("title") or "").strip()
        content = (request.data.get("content") or "").strip()
        if not title:
            raise ValueError("请填写提示词标题")
        if not content:
            raise ValueError("请填写提示词内容")
        p = AIPrompt.objects.create(
            owner=request.user, title=title[:120], content=content[:4000],
            category=(request.data.get("category") or "自定义")[:32],
            is_favorite=parse_bool(request.data.get("is_favorite"), field="is_favorite"),
        )
        return Response(_prompt_json(p), status=201)


class PromptDetailView(APIView):
    """单条提示词：PATCH 更新（含收藏切换）· DELETE 删除 · POST 记一次使用"""

    def _get(self, request, pk):
        return AIPrompt.objects.filter(pk=pk, owner=request.user).first()

    @endpoint(("PATCH",))
    def patch(self, request, pk):
        p = self._get(request, pk)
        if not p:
            return Response({"message": "提示词不存在"}, status=404)
        for field, cap in (("title", 120), ("content", 4000), ("category", 32)):
            if field in request.data and request.data[field]:
                setattr(p, field, str(request.data[field])[:cap])
        if "is_favorite" in request.data:
            p.is_favorite = parse_bool(request.data["is_favorite"], field="is_favorite")
        p.save()
        return Response(_prompt_json(p))

    @endpoint(("POST",))
    def post(self, request, pk):
        """一键插入输入框：记一次使用次数（前端插入后调用）"""
        p = self._get(request, pk)
        if not p:
            return Response({"message": "提示词不存在"}, status=404)
        AIPrompt.objects.filter(pk=p.pk).update(usage_count=p.usage_count + 1)
        p.refresh_from_db()
        return Response(_prompt_json(p))

    @endpoint(("DELETE",))
    def delete(self, request, pk):
        p = self._get(request, pk)
        if not p:
            return Response({"message": "提示词不存在"}, status=404)
        p.delete()
        return Response({"message": "已删除"})


# ---------------------------------------------------------------------------
# F645 复制/重试/分支 —— 分支：以该条消息为父创建新会话
# ---------------------------------------------------------------------------

class ConversationBranchView(APIView):
    """POST /api/assistant/conversations/<pk>/branch/  {"message_id": 12}

    以指定消息为父，创建新会话，并把该消息（含）之前的上下文复制过去。
    """

    @endpoint(("POST",))
    def post(self, request, pk):
        parent = AIConversation.objects.filter(pk=pk, owner=request.user).first()
        if not parent:
            return Response({"message": "会话不存在"}, status=404)
        mid = request.data.get("message_id")
        msg = None
        if mid:
            try:
                msg = parent.messages.filter(pk=int(mid)).first()
            except (TypeError, ValueError):
                msg = None
        if msg is None:
            msg = parent.messages.order_by("-id").first()
        if msg is None:
            raise ValueError("该会话还没有可分支的消息")

        conv = AIConversation.objects.create(
            owner=request.user,
            title=f"{parent.title or '新对话'} · 分支",
            scene=parent.scene,
            model=parent.model,
            parent_conversation=parent,
            parent_message=msg,
        )
        copied = 0
        for m in parent.messages.filter(id__lte=msg.id).order_by("id"):
            AIMessage.objects.create(
                conversation=conv, role=m.role, content=m.content,
                provider=m.provider, references=m.references,
            )
            copied += 1
        conv.message_count = copied
        conv.save(update_fields=["message_count", "updated_at"])
        return Response({
            "id": conv.id, "title": conv.title, "copied_messages": copied,
            "parent_conversation_id": parent.id, "parent_message_id": msg.id,
        }, status=201)


class ConversationExportView(APIView):
    """F655 对话导出 Markdown：GET /api/assistant/conversations/<pk>/export/"""

    @endpoint(("GET",))
    def get(self, request, pk):
        conv = AIConversation.objects.filter(pk=pk, owner=request.user).first()
        if not conv:
            return Response({"message": "会话不存在"}, status=404)
        from django.utils import timezone

        lines = [
            f"# {conv.title or 'AI 对话'}", "",
            f"> 导出时间：{timezone.localtime().strftime('%Y-%m-%d %H:%M')} ｜ "
            f"消息数：{conv.message_count} ｜ 模型：{conv.model or '-'}", "",
        ]
        if conv.parent_conversation_id:
            lines += [f"> 分支自会话 #{conv.parent_conversation_id}"
                      + (f"（消息 #{conv.parent_message_id}）" if conv.parent_message_id else ""), ""]
        for m in conv.messages.order_by("id"):
            who = "我" if m.role == "user" else "助手"
            lines.append(f"### {who} · {m.created_at.strftime('%Y-%m-%d %H:%M')}")
            lines.append("")
            lines.append(m.content or "")
            lines.append("")
            if m.references:
                titles = "、".join(str(r.get("title", "")) for r in m.references if isinstance(r, dict))
                if titles:
                    lines += [f"> 引用：{titles}", ""]
        md = "\n".join(lines)
        resp = HttpResponse(md, content_type="text/markdown; charset=utf-8")
        fname = f"conversation_{conv.id}.md"
        resp["Content-Disposition"] = (
            f"attachment; filename=\"{fname}\"; filename*=UTF-8''{quote(conv.title or '对话')}.md"
        )
        return resp


class ConversationSummarizeView(APIView):
    """F56 长对话自动摘要：GET/POST /api/assistant/conversations/<pk>/summarize/

    有 LLM 走模型；无 Key 用本地抽取式摘要。按消息数缓存，新增消息后自动失效，
    传 force=1 可强制重算。
    """

    MAX_TRANSCRIPT = 12000

    def _transcript(self, conv):
        msgs = list(conv.messages.order_by("id"))
        lines = []
        for m in msgs[-80:]:
            who = "用户" if m.role == "user" else ("助手" if m.role == "assistant" else "系统")
            body = (m.content or "").strip()
            if not body:
                continue
            lines.append(f"{who}：{body[:600]}")
        text = "\n".join(lines)
        if len(text) > self.MAX_TRANSCRIPT:
            text = text[-self.MAX_TRANSCRIPT:]
        return text, len(msgs)

    def _local(self, conv, transcript):
        head = [m for m in list(conv.messages.order_by("id"))[:3] if (m.content or "").strip()]
        tail = [m for m in list(conv.messages.order_by("-id"))[:5] if (m.content or "").strip()][::-1]
        parts = []
        for m in head:
            parts.append(("用户" if m.role == "user" else "助手") + "：" + (m.content or "").strip()[:120])
        picked = llm.extractive_summary(transcript, max_sentences=5)
        if picked:
            parts.append(picked[:600])
        if tail:
            last = tail[-1]
            parts.append("最近：" + (last.content or "").strip()[:120])
        return "；".join(p for p in parts if p)[:800]

    def _handle(self, request, pk):
        conv = AIConversation.objects.filter(pk=pk, owner=request.user).first()
        if not conv:
            return Response({"message": "会话不存在"}, status=404)
        transcript, total = self._transcript(conv)
        if not transcript:
            raise ValueError("会话还没有可摘要的消息")
        force = parse_bool(request.query_params.get("force") if request.method == "GET" else request.data.get("force"),
                           field="force")
        cached = (conv.summary and conv.summary_message_count == total and not force)
        if cached:
            return Response({"conversation_id": conv.id, "summary": conv.summary,
                             "summary_at": conv.summary_at, "message_count": total,
                             "covered": conv.summary_message_count, "cached": True,
                             "provider": "cache"})

        mode = "local"
        summary = ""
        try:
            res = llm.chat([
                {"role": "system", "content": "你是对话摘要助手。只输出摘要正文，不要客套话。"},
                {"role": "user", "content": (
                    "把下面这段 AI 对话压缩成 5 条以内要点，保留结论、决定与待办：\n\n" + transcript
                )},
            ], temperature=0.3, max_tokens=600)
            if res.get("ok") and (res.get("content") or "").strip():
                summary = res["content"].strip()[:2000]
                mode = "llm"
        except Exception:  # noqa: BLE001 —— 摘要属增强能力，失败降级
            mode = "local"
        if not summary:
            summary = self._local(conv, transcript)

        conv.summary = summary
        conv.summary_at = timezone.now()
        conv.summary_message_count = total
        conv.save(update_fields=["summary", "summary_at", "summary_message_count"])
        llm.log_usage(request.user.id, "conversation_summary", {"ok": True}, prompt_chars=len(transcript),
                      output_chars=len(summary))
        return Response({"conversation_id": conv.id, "summary": summary,
                         "summary_at": conv.summary_at, "message_count": total,
                         "covered": total, "cached": False, "provider": mode})

    @endpoint(("GET",))
    def get(self, request, pk):
        return self._handle(request, pk)

    @endpoint(("POST",))
    def post(self, request, pk):
        return self._handle(request, pk)


# ---------------------------------------------------------------------------
# F647–F651、F653、F656 创作工具（有 Key 走模型，无 Key 本地降级）
# ---------------------------------------------------------------------------

class TranslateView(APIView):
    """F647 多语翻译：POST /api/assistant/translate/ {"text": "...", "target": "en|zh|ja|ko"}"""

    @endpoint(("POST",))
    def post(self, request):
        out = generators.translate(
            request.data.get("text") or "",
            request.data.get("target") or "en",
            user_id=request.user.id,
        )
        out["languages"] = generators.SUPPORTED_LANGS
        return Response(out)


class NameGeneratorView(APIView):
    """F648 起名器：POST /api/assistant/names/ {"kind": "person|project|brand", "seed": ...}"""

    @endpoint(("POST",))
    def post(self, request):
        seed = request.data.get("seed")
        if seed in (None, ""):
            seed = random.randint(1, 10 ** 9)
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = random.randint(1, 10 ** 9)
        out = generators.gen_names(
            kind=request.data.get("kind") or "project",
            count=request.data.get("count") or 8,
            seed=seed,
            hint=(request.data.get("hint") or "").strip()[:60],
            user_id=request.user.id,
        )
        out["kinds"] = generators.KIND_LABEL
        return Response(out)


class WeeklyReportView(APIView):
    """F649 周报生成器：POST /api/assistant/weekly-report/ {"points": ["...", ...]}"""

    @endpoint(("POST",))
    def post(self, request):
        points = request.data.get("points")
        if isinstance(points, str):
            points = [p for p in points.replace("\r", "\n").split("\n")]
        if not isinstance(points, list):
            raise ValueError("points 需为字符串数组")
        return Response(generators.weekly_report(
            points,
            author=(request.data.get("author") or "").strip()[:40],
            week_label=(request.data.get("week_label") or "").strip()[:40],
            user_id=request.user.id,
        ))


class AgendaView(APIView):
    """F656 会议议程生成：POST /api/assistant/agenda/ {"topic": "...", "minutes": 60}"""

    @endpoint(("POST",))
    def post(self, request):
        return Response(generators.agenda(
            request.data.get("topic") or "",
            request.data.get("minutes") or 60,
            user_id=request.user.id,
        ))


class EmailDraftView(APIView):
    """F650 邮件草稿生成：POST /api/assistant/email-draft/ {"scene": "...", "tone": "formal"}"""

    @endpoint(("POST",))
    def post(self, request):
        points = request.data.get("key_points") or []
        if isinstance(points, str):
            points = [points]
        return Response(generators.email_draft(
            scene=request.data.get("scene") or "",
            tone=request.data.get("tone") or "neutral",
            to=(request.data.get("to") or "").strip()[:80],
            key_points=points if isinstance(points, list) else [],
            extra=(request.data.get("extra") or "").strip()[:500],
            user_id=request.user.id,
        ))


class SocialCopyView(APIView):
    """F651 社交文案生成：POST /api/assistant/social-copy/ {"topic": "...", "style": "fresh"}"""

    @endpoint(("POST",))
    def post(self, request):
        return Response(generators.social_copy(
            topic=request.data.get("topic") or "",
            style=request.data.get("style") or "fresh",
            platform=(request.data.get("platform") or "朋友圈")[:20],
            count=request.data.get("count") or 3,
            user_id=request.user.id,
        ))


class MathExplainView(APIView):
    """F653 算式分步讲解：POST /api/assistant/math-explain/ {"expression": "(1+2)*3"}

    使用 ast 白名单求值，不使用 eval；非法表达式 → 400。
    """

    @endpoint(("POST", "GET"))
    def post(self, request):
        return Response(generators.explain_math(
            request.data.get("expression") or request.query_params.get("expression") or ""
        ))

    def get(self, request):
        return self.post(request)


# ---------------------------------------------------------------------------
# F654 快捷指令 `/` 菜单（后端给出工具与路由建议，前端合并渲染）
# ---------------------------------------------------------------------------

COMMAND_ITEMS = [
    {"id": "translate", "kind": "tool", "label": "翻译", "usage": "/translate 你好",
     "desc": "中英日韩互译（本地词典降级）", "icon": "🌐"},
    {"id": "names", "kind": "tool", "label": "起名器", "usage": "/names 项目",
     "desc": "人名 / 项目名 / 品牌名", "icon": "✨"},
    {"id": "weekly", "kind": "tool", "label": "周报", "usage": "/weekly",
     "desc": "三条要点生成工作周报", "icon": "📊"},
    {"id": "agenda", "kind": "tool", "label": "会议议程", "usage": "/agenda",
     "desc": "主题 + 时长 → 分钟级议程", "icon": "🗓️"},
    {"id": "email", "kind": "tool", "label": "邮件草稿", "usage": "/email",
     "desc": "场景 + 语气生成邮件", "icon": "✉️"},
    {"id": "social", "kind": "tool", "label": "社交文案", "usage": "/social",
     "desc": "朋友圈 / 短文案多风格", "icon": "💬"},
    {"id": "summary", "kind": "tool", "label": "摘要三档", "usage": "/summary",
     "desc": "一句话 / 要点 / 段落切换", "icon": "📝"},
    {"id": "math", "kind": "tool", "label": "算式讲解", "usage": "/math (1+2)*3",
     "desc": "四则运算分步解释", "icon": "🧮"},
    {"id": "clear", "kind": "action", "label": "清空当前对话", "usage": "/clear",
     "desc": "开始一个新对话", "icon": "🧹"},
    {"id": "route-notes", "kind": "route", "label": "打开笔记", "usage": "/notes",
     "path": "/notes", "desc": "跳转到笔记知识库", "icon": "📝"},
    {"id": "route-files", "kind": "route", "label": "打开文件", "usage": "/files",
     "path": "/files", "desc": "跳转到文件管理", "icon": "📁"},
    {"id": "route-search", "kind": "route", "label": "全文搜索", "usage": "/search",
     "path": "/search", "desc": "跳转到搜索页", "icon": "🔍"},
    {"id": "route-learning", "kind": "route", "label": "学习中心", "usage": "/learning",
     "path": "/learning", "desc": "跳转到学习中心", "icon": "📚"},
    {"id": "route-dashboard", "kind": "route", "label": "回到工作台", "usage": "/dashboard",
     "path": "/dashboard", "desc": "跳转到工作台", "icon": "🏠"},
]


class CommandMenuView(APIView):
    """F654：GET /api/assistant/commands/ —— 输入 `/` 时的工具与路由建议"""

    def get(self, request):
        return Response({"list": COMMAND_ITEMS, "total": len(COMMAND_ITEMS)})


# ---------------------------------------------------------------------------
# F646 输入即时反馈（输入框边打边给提示，纯本地规则，无 LLM 依赖）
# ---------------------------------------------------------------------------

def _input_feedback(text: str) -> dict:
    """对正在输入的内容做即时本地分析（纯规则，无 Key 也能用）"""
    text = text or ""
    stripped = text.strip()
    char_count = len(text)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if cjk and latin:
        lang = "mixed"
    elif cjk:
        lang = "zh"
    elif latin:
        lang = "en"
    else:
        lang = "unknown"
    words = cjk if lang == "zh" else len([w for w in stripped.split() if w])
    if char_count == 0:
        level = "empty"
    elif char_count <= 200:
        level = "short"
    elif char_count <= 2000:
        level = "medium"
    else:
        level = "long"

    has_command = stripped.startswith("/")
    command = ""
    if has_command:
        token = stripped[1:].split()[0].lower() if len(stripped) > 1 else ""
        if token in {c["id"] for c in COMMAND_ITEMS}:
            command = token

    tips = []
    if not stripped:
        tips.append("输入 / 可打开快捷指令菜单")
    else:
        if has_command and not command:
            tips.append("未识别的指令，输入 / 可查看全部快捷指令")
        if char_count > MAX_INPUT_CHARS:
            tips.append(f"超过单次上限 {MAX_INPUT_CHARS} 字，发送时会自动截断")
        elif lang in ("zh", "mixed") and char_count > 800:
            tips.append("内容较长，可先用「摘要三档」压缩后再发送")
        if "？" in text or text.endswith("?") or "吗" in text:
            tips.append("看起来是一个问题，可直接发送给助手")

    return {
        "char_count": char_count,
        "word_count": words,
        "cjk_count": cjk,
        "language": lang,
        "length_level": level,
        "is_empty": not bool(stripped),
        "has_command": has_command,
        "command": command,
        "over_limit": char_count > MAX_INPUT_CHARS,
        "max_chars": MAX_INPUT_CHARS,
        "tips": tips,
        "suggestions": [
            {"id": "polish", "label": "润色", "hint": "让表达更流畅"},
            {"id": "translate", "label": "翻译", "hint": "中英日韩互译"},
            {"id": "summary", "label": "摘要", "hint": "一句话 / 要点 / 段落"},
        ],
    }


class InputFeedbackView(APIView):
    """F646：POST /api/assistant/input-feedback/ {"text": "..."}

    输入框即时反馈：字数统计 / 语言判定 / `/` 指令识别 / 即时建议，全部本地规则计算。
    """

    @endpoint(("POST", "GET"))
    def post(self, request):
        return Response(_input_feedback(
            request.data.get("text") or request.query_params.get("text") or ""
        ))

    def get(self, request):
        return self.post(request)
