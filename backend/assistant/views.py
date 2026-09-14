"""AI 助手接口：状态 / 笔记摘要 / 笔记问答 / 聊天助手 / 出题 / 批改

约定
----
- 所有能力在「未配置 LLM_API_KEY」时自动降级为本地实现，接口结构与返回字段完全一致，
  仅 `provider` 从 `llm` 变为 `local`，因此前端无需分叉。
- 每次调用都会写 AIUsageLog，便于观察降级比例与失败原因。
"""
from __future__ import annotations

import random

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant import llm, retrieval
from assistant.models import AIConversation, AIGeneratedQuestion, AIMessage
from core.scoping import scope_queryset

SYSTEM_TUTOR = (
    "你是「全能协作平台」内置的知识助手。回答要准确、简洁、结构清晰，"
    "优先依据用户提供的资料作答；资料不足时明确说明，不要编造。"
    "使用简体中文回答，必要时用列表或步骤组织内容。"
)

MAX_INPUT_CHARS = 12000


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

    POST /api/assistant/notes/<pk>/summarize/   {"force": false, "length": "short|medium|detail"}
    结果会缓存到 Note.ai_summary，除非 force=true 否则不重复调用大模型。
    """

    def post(self, request, pk):
        note = _note_or_404(request.user, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=status.HTTP_404_NOT_FOUND)

        content = note.content or ""
        if not content.strip():
            return Response({"message": "笔记内容为空，无法生成摘要"}, status=400)

        force = bool(request.data.get("force"))
        if note.ai_summary and not force:
            return Response({
                "summary": note.ai_summary, "note_id": note.id, "title": note.title,
                "provider": "cache", "model": "", "cached": True,
                "key_points": llm.bullet_points(content, 5),
                "generated_at": note.ai_summary_at,
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

        return Response({
            "summary": summary, "key_points": points, "note_id": note.id, "title": note.title,
            "provider": result["provider"], "model": result.get("model", ""), "cached": False,
            "fallback_reason": "" if result["ok"] else result.get("error", ""),
            "generated_at": note.ai_summary_at,
        })

    def get(self, request, pk):
        note = _note_or_404(request.user, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        return Response({
            "summary": note.ai_summary, "note_id": note.id, "title": note.title,
            "cached": bool(note.ai_summary), "generated_at": note.ai_summary_at,
            "key_points": llm.bullet_points(note.content, 5) if note.content else [],
        })


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
        question = (request.data.get("question") or "").strip()
        if not question:
            return Response({"message": "请输入问题"}, status=400)

        note_ids = request.data.get("note_ids") or None
        keyword = (request.data.get("keyword") or "").strip()
        notes = list(retrieval.search_notes(request.user, keyword or question, limit=30))
        if note_ids:
            allowed = set(int(i) for i in note_ids)
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
    """我的 AI 会话列表 / 新建会话"""

    def get(self, request):
        qs = AIConversation.objects.filter(owner=request.user)
        return Response({"list": [
            {"id": c.id, "title": c.title, "model": c.model, "message_count": c.message_count,
             "updated_at": c.updated_at}
            for c in qs[:50]
        ], "total": qs.count()})

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

    def get(self, request, pk):
        c = self._get(request, pk)
        if not c:
            return Response({"message": "会话不存在"}, status=404)
        return Response({
            "id": c.id, "title": c.title, "model": c.model, "updated_at": c.updated_at,
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
        count = max(1, min(int(request.data.get("count") or 5), 10))
        qtype = self.TYPE_ALIAS.get(str(request.data.get("type") or "single"), "single")
        difficulty = max(1, min(int(request.data.get("difficulty") or 2), 5))
        save = bool(request.data.get("save", True))

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
        limit = min(int(request.query_params.get("limit", 50)), 200)
        return Response({"list": [
            {"id": q.id, "topic": q.topic, "question_type": q.question_type, "difficulty": q.difficulty,
             "stem": q.stem, "options": q.options, "answer": q.answer, "analysis": q.analysis,
             "source": q.source, "created_at": q.created_at}
            for q in qs[:limit]
        ], "total": qs.count()})

    def delete(self, request):
        ids = request.data.get("ids") or []
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

        record = bool(request.data.get("record_mistakes", True))
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
