# -*- coding: utf-8 -*-
"""学习中心视图：
- 编程学习（10 种语言：元信息/路线/速查/关键字/类型/片段/课程/对比/推荐/练习题库…）
- K12 学科（学段学科/知识点/公式/古诗文/英语词表/题库组卷判分/成语汉字/元素方程式/语法…）
- 个人数据（进度/收藏/生词本/错题本/专注/计划）
- 40 个学习工具统一目录与运行入口（见 learn_tools）
"""
import datetime as dt
import random
import re

from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core.validators import as_int, parse_bool
from learning.data import chinese as cn
from learning.data import chemistry as ch
from learning.data import curriculum as cu
from learning.data import english as en
from learning.data import questions as qb
from learning.data.enhanced import LANG_MODULES, keyword_detail, knowledge_detail
from learning.data.languages import LANGS, LANG_ORDER, lang_brief
from learning.data.programming import (
    ALGORITHMS, DATA_STRUCTURES, DRILLS, GLOSSARY, PARADIGMS, drills_by, public_drill,
)
from learning.learn_tools import LEARN_TOOL_REGISTRY
from learning.models import (
    DailyGoal, FormulaFavorite, IdiomChainRecord, LearningBadge, LearningProgress,
    MasteryRating, MistakeRecord, PaperArchive, QuestionFavorite, QuestionSet,
    SnippetBookmark, StudyPlan, StudySession, ToolUsageLog, WordbookItem,
)
from learning.serializers import (
    LearningProgressSerializer, MistakeRecordSerializer, SnippetBookmarkSerializer,
    StudyPlanSerializer, StudySessionSerializer, WordbookItemSerializer,
)


def _lang(key):
    d = LANGS.get(key)
    if not d:
        from rest_framework.exceptions import NotFound
        raise NotFound(f"未知编程语言：{key}")
    return d


def _params(request, *keys):
    return [request.query_params.get(k) for k in keys]


# ============================================================
# 一、编程学习（30 项）
# ============================================================
class LangCatalogView(APIView):
    """P01 语言总览：10 种编程语言卡片"""

    def get(self, request):
        briefs = [lang_brief(k) for k in LANG_ORDER]
        return Response({"total": len(briefs), "list": briefs})


class LangDetailView(APIView):
    """P02 语言详情（完整元信息）"""

    def get(self, request, key):
        d = _lang(key)
        return Response(lang_brief(key))


class LangRoadmapView(APIView):
    """P03 学习路线"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "name": d["name"], "roadmap": d["roadmap"]})


class LangCheatsheetView(APIView):
    """P04 语法速查"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "name": d["name"], "cheatsheet": [{"point": a, "code": b, "note": c} for a, b, c in d["cheatsheet"]]})


class LangKeywordsView(APIView):
    """P05 关键字表（支持 ?detail=true 返回每个关键字的详解）"""

    def get(self, request, key):
        d = _lang(key)
        keywords = d["keywords"]
        detail = request.query_params.get("detail", "").lower() in ("1", "true", "yes")
        if detail:
            items = [keyword_detail(key, w) for w in keywords]
            return Response({"key": key, "keywords": items, "count": len(items)})
        return Response({"key": key, "keywords": keywords, "count": len(keywords)})


class LangKeywordDetailView(APIView):
    """P05b 单个关键字详解"""

    def get(self, request, key, word):
        d = _lang(key)
        if word not in d["keywords"]:
            from rest_framework.exceptions import NotFound
            raise NotFound(f"关键字不存在：{word}")
        return Response(keyword_detail(key, word))


class LangModulesView(APIView):
    """P05c 标准库模块用法列表"""

    def get(self, request, key):
        d = _lang(key)
        modules = LANG_MODULES.get(key, [])
        return Response({
            "key": key,
            "name": d["name"],
            "modules": [{"index": i, "name": m["name"], "desc": m["desc"]} for i, m in enumerate(modules)],
            "count": len(modules),
        })


class LangModuleDetailView(APIView):
    """P05d 单个模块完整用法（含函数列表、示例代码、注意事项）"""

    def get(self, request, key, idx):
        modules = LANG_MODULES.get(key, [])
        if not (0 <= idx < len(modules)):
            from rest_framework.exceptions import NotFound
            raise NotFound("模块不存在")
        return Response({"index": idx, "key": key, **modules[idx]})


class LangTypesView(APIView):
    """P06 数据类型参考"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "types": d["types"]})


class LangSnippetListView(APIView):
    """P07 代码片段库（可按 topic 过滤）"""

    def get(self, request, key):
        d = _lang(key)
        topic = request.query_params.get("topic")
        items = d["snippets"]
        if topic:
            items = [s for s in items if s["topic"] == topic]
        topics = sorted({s["topic"] for s in d["snippets"]})
        return Response({"key": key, "topics": topics, "total": len(items),
                         "list": [{"index": i, **s} for i, s in enumerate(d["snippets"]) if not topic or s["topic"] == topic]})


class LangSnippetDetailView(APIView):
    """P08 片段详情"""

    def get(self, request, key, idx):
        d = _lang(key)
        if not (0 <= idx < len(d["snippets"])):
            from rest_framework.exceptions import NotFound
            raise NotFound("片段不存在")
        return Response({"index": idx, **d["snippets"][idx]})


class LangCompareView(APIView):
    """P09 多语言横向对比"""

    def get(self, request):
        keys = [k for k in re.split(r"[,，\s]+", request.query_params.get("keys", "")) if k in LANGS]
        if len(keys) < 2:
            keys = LANG_ORDER[:2]
        dims = ["typing", "year", "designer", "paradigms", "domains", "difficulty", "hello"]
        rows = []
        for dim in ["名称", "类型系统", "诞生年份", "设计者", "范式", "适用领域", "入门难度", "Hello World"]:
            row = {"dimension": dim}
            for k in keys:
                d = LANGS[k]
                row[k] = {"名称": d["name"], "类型系统": d["typing"], "诞生年份": d["year"], "设计者": d["designer"],
                          "范式": d["paradigms"], "适用领域": d["domains"], "入门难度": d["difficulty"],
                          "Hello World": d["hello"]}[dim]
            rows.append(row)
        return Response({"keys": keys, "names": {k: LANGS[k]["name"] for k in keys}, "rows": rows})


class GlossaryView(APIView):
    """P10 编程术语词典（可搜索 q / 按 tag）"""

    def get(self, request):
        q = request.query_params.get("q", "").strip().lower()
        tag = request.query_params.get("tag")
        items = GLOSSARY
        if tag:
            items = [g for g in items if tag in g["tags"]]
        if q:
            items = [g for g in items if q in g["term"].lower() or q in g["desc"].lower()]
        tags = sorted({t for g in GLOSSARY for t in g["tags"]})
        return Response({"total": len(items), "tags": tags, "list": items})


class ParadigmsView(APIView):
    """P11 编程范式总览"""

    def get(self, request):
        return Response({"list": PARADIGMS})


class LessonListView(APIView):
    """P12 入门课程列表"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "total": len(d["lessons"]),
                         "list": [{"index": i, "title": x["title"], "summary": x["summary"]} for i, x in enumerate(d["lessons"])]})


class LessonDetailView(APIView):
    """P13 课程详情"""

    def get(self, request, key, idx):
        d = _lang(key)
        if not (0 <= idx < len(d["lessons"])):
            from rest_framework.exceptions import NotFound
            raise NotFound("课程不存在")
        return Response({"index": idx, **d["lessons"][idx]})


def _sample(dtype, lang=None, level=None, n=5, with_answer=False):
    pool = drills_by(lang=lang, dtype=dtype, level=level)
    random.shuffle(pool)
    return [public_drill(x, with_answer) for x in pool[:n]]


class DrillQuizView(APIView):
    """P14 单选题练习"""

    def get(self, request):
        lang, level, n = _params(request, "lang", "level", "n")
        return Response({"list": _sample("quiz", lang, level, as_int(n, default=5, field="n", minimum=1))})


class DrillOutputView(APIView):
    """P15 读程序写结果"""

    def get(self, request):
        lang, level, n = _params(request, "lang", "level", "n")
        return Response({"list": _sample("output", lang, level, as_int(n, default=5, field="n", minimum=1))})


class DrillFillView(APIView):
    """P16 代码填空"""

    def get(self, request):
        lang, level, n = _params(request, "lang", "level", "n")
        return Response({"list": _sample("fill", lang, level, as_int(n, default=5, field="n", minimum=1))})


class DrillBugView(APIView):
    """P17 找错题"""

    def get(self, request):
        lang, level, n = _params(request, "lang", "level", "n")
        return Response({"list": _sample("bug", lang, level, as_int(n, default=5, field="n", minimum=1))})


def _normalize(s):
    return re.sub(r"\s+", "", str(s).strip().lower().replace("，", ",").replace("（", "(").replace("）", ")"))


class DrillGradeView(APIView):
    """P18 单题判分：{id, answer}"""

    def post(self, request):
        qid = request.data.get("id")
        ans = request.data.get("answer")
        target = next((d for d in DRILLS if d["id"] == qid), None)
        if not target:
            return Response({"message": "题目不存在"}, status=404)
        if target["type"] in ("quiz", "bug"):
            try:
                correct = int(ans) == target["answer"]
            except (TypeError, ValueError):
                correct = False
            right = target["answer"]
        else:
            correct = _normalize(ans) == _normalize(target["answer"])
            right = target["answer"]
        return Response({"id": qid, "correct": correct, "right_answer": right, "explain": target["explain"]})


class DrillRandomView(APIView):
    """P19 随机抽题（可指定 lang/type）"""

    def get(self, request):
        lang, dtype = _params(request, "lang", "type")
        pool = drills_by(lang=lang, dtype=dtype)
        if not pool:
            return Response({"message": "没有符合条件的题"}, status=404)
        return Response(public_drill(random.choice(pool)))


class RecommendView(APIView):
    """P20 语言推荐：按目标 goal 与基础 base"""

    def get(self, request):
        goal = request.query_params.get("goal", "")
        base = request.query_params.get("base", "zero")
        goal_map = {
            "ai": ["python"], "web": ["javascript", "go", "java"], "game": ["csharp", "cpp"],
            "job": ["java", "python", "javascript"], "system": ["c", "cpp", "rust"],
            "mobile": ["kotlin", "swift"], "embedded": ["c"], "cloud": ["go", "rust"],
        }
        rec_keys = goal_map.get(goal, ["python", "javascript"])
        if base == "zero":
            rec_keys = sorted(rec_keys, key=lambda k: LANGS[k]["difficulty"])
        reason = {
            "ai": "人工智能与数据科学首选 Python，生态成熟",
            "web": "前端必学 JavaScript，后端可选 Go/Java",
            "game": "Unity 用 C#，高性能引擎用 C++",
            "job": "岗位需求量大、生态稳定的主流语言",
            "system": "贴近硬件与底层性能，选 C/C++/Rust",
            "mobile": "安卓 Kotlin、iOS Swift",
        }.get(goal, "零基础建议从语法友好的语言入门")
        return Response({"goal": goal, "base": base, "reason": reason,
                         "list": [lang_brief(k) for k in rec_keys]})


class LangTroubleshootView(APIView):
    """P21 常见报错排查"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "errors": d["errors"]})


class AlgorithmsView(APIView):
    """P22 算法入门目录"""

    def get(self, request):
        level = request.query_params.get("level")
        items = [a for a in ALGORITHMS if not level or a["level"] == level]
        return Response({"total": len(items), "list": items})


class DataStructuresView(APIView):
    """P23 数据结构词典"""

    def get(self, request):
        return Response({"total": len(DATA_STRUCTURES), "list": DATA_STRUCTURES})


class LangIdeView(APIView):
    """P24 开发环境/IDE 指南"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "ide": d["ide"]})


class LangStyleView(APIView):
    """P25 编码规范"""

    def get(self, request, key):
        d = _lang(key)
        return Response({"key": key, "style": d["style"]})


class QuizSubmitView(APIView):
    """P26 整卷交卷计分：{answers:[{id,answer}]}"""

    def post(self, request):
        answers = request.data.get("answers", [])
        details, correct = [], 0
        for item in answers:
            target = next((d for d in DRILLS if d["id"] == item.get("id")), None)
            if not target:
                continue
            ua = item.get("answer")
            if target["type"] in ("quiz", "bug"):
                ok = str(ua) == str(target["answer"])
            else:
                ok = _normalize(ua) == _normalize(target["answer"])
            correct += ok
            details.append({"id": target["id"], "correct": ok, "right_answer": target["answer"], "explain": target["explain"]})
        total = len(details)
        return Response({"total": total, "correct": correct, "score": round(correct / total * 100, 1) if total else 0, "details": details})


class DailyChallengeView(APIView):
    """P27 每日一题（按日期稳定，可选 lang）"""

    def get(self, request):
        lang = request.query_params.get("lang")
        pool = drills_by(lang=lang)
        day = dt.date.today().timetuple().tm_yday
        pick = pool[day % len(pool)]
        return Response({"date": dt.date.today().isoformat(), **public_drill(pick)})


class ProgressView(APIView):
    """P28 学习进度列表 / P29 进度新增更新(upsert)"""

    def get(self, request):
        qs = LearningProgress.objects.filter(owner=request.user)
        domain = request.query_params.get("domain")
        if domain:
            qs = qs.filter(domain=domain)
        data = LearningProgressSerializer(qs, many=True).data
        finished = sum(1 for x in data if x["status"] == "finished")
        return Response({"total": len(data), "finished": finished, "list": data})

    def post(self, request):
        d = request.data
        obj, _ = LearningProgress.objects.update_or_create(
            owner=request.user, domain=d.get("domain", "programming"), target_key=d.get("target_key"),
            defaults={"target_name": d.get("target_name", ""), "status": d.get("status", "learning"),
                      "percent": as_int(d.get("percent"), default=0, field="percent", minimum=0, maximum=100), "note": d.get("note", "")})
        return Response(LearningProgressSerializer(obj).data)


class SnippetBookmarkView(APIView):
    """P30 代码片段收藏：列表/新增/删除"""

    def get(self, request):
        qs = SnippetBookmark.objects.filter(owner=request.user)
        lang = request.query_params.get("lang")
        if lang:
            qs = qs.filter(language=lang)
        return Response({"total": qs.count(), "list": SnippetBookmarkSerializer(qs, many=True).data})

    def post(self, request):
        ser = SnippetBookmarkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(owner=request.user)
        return Response(ser.data, status=201)

    def delete(self, request):
        obj = get_object_or_404(SnippetBookmark, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


# ============================================================
# 二、K12 学科（30 项）
# ============================================================
class StageListView(APIView):
    """S01 学段学科目录"""

    def get(self, request):
        return Response({"list": cu.STAGES})


class SubjectDetailView(APIView):
    """S02 学科详情"""

    def get(self, request, stage, subject):
        st = next((s for s in cu.STAGES if s["key"] == stage), None)
        if not st:
            from rest_framework.exceptions import NotFound
            raise NotFound("学段不存在")
        sub = next((x for x in st["subjects"] if x["key"] == subject), None)
        if not sub:
            from rest_framework.exceptions import NotFound
            raise NotFound("学科不存在")
        chapters = cu.KNOWLEDGE.get(f"{stage}.{subject}", [])
        return Response({"stage": stage, "stage_name": st["name"], **sub,
                         "chapter_count": len(chapters),
                         "point_count": sum(len(c["points"]) for c in chapters)})


class KnowledgeTreeView(APIView):
    """S03 知识点树"""

    def get(self, request):
        stage, subject = _params(request, "stage", "subject")
        if stage and subject:
            chapters = cu.KNOWLEDGE.get(f"{stage}.{subject}", [])
            points = [{"id": f"{stage}.{subject}.{ci}.{pi}", "chapter": c["chapter"], "name": pt}
                      for ci, c in enumerate(chapters) for pi, pt in enumerate(c["points"])]
            return Response({"stage": stage, "subject": subject, "chapters": chapters, "points": points})
        # 全量按 学段.学科 分组返回章节树
        tree = {}
        for sk, chapters in cu.KNOWLEDGE.items():
            tree[sk] = [{"chapter": c["chapter"], "points": c["points"]} for c in chapters]
        counts = {sk: sum(len(c["points"]) for c in cs) for sk, cs in cu.KNOWLEDGE.items()}
        return Response({"tree": tree, "counts": counts, "total_points": sum(counts.values())})


_ALL_POINTS = list(cu.iter_points())


class KnowledgeDetailView(APIView):
    """S04 知识点详情（含定义、要点、公式、例题、方法、易错点）"""

    def get(self, request, kid):
        pt = next((x for x in _ALL_POINTS if x["id"] == kid), None)
        if not pt:
            from rest_framework.exceptions import NotFound
            raise NotFound("知识点不存在")
        related = _related_formulas(pt)
        # 生成完整知识点详情（语数英支持完整教学内容）
        stage_subject = f"{pt['stage']}.{pt['subject']}"
        detail = knowledge_detail(stage_subject, pt["chapter"], pt["name"])
        return Response({
            **pt,
            "related_formulas": [f["name"] for f in related],
            "detail": detail,
        })


class KnowledgeSearchView(APIView):
    """S05 知识点全局搜索"""

    def get(self, request):
        kw = request.query_params.get("q", "").strip()
        if not kw:
            return Response({"list": [], "total": 0})
        items = [x for x in _ALL_POINTS if kw in x["name"] or kw in x["chapter"]]
        return Response({"q": kw, "total": len(items), "list": items[:50]})


class FormulaListView(APIView):
    """S06 公式手册列表"""

    def get(self, request):
        stage, subject = _params(request, "stage", "subject")
        items = cu.FORMULAS
        if stage:
            items = [f for f in items if f["stage"] == stage]
        if subject:
            items = [f for f in items if f["subject"] == subject]
        brief = [{"key": f["key"], "name": f["name"], "formula": f["formula"],
                  "stage": f["stage"], "subject": f["subject"], "vars": f["vars"]} for f in items]
        return Response({"total": len(brief), "list": brief})


class FormulaDetailView(APIView):
    """S07 公式详情"""

    def get(self, request, key):
        f = next((x for x in cu.FORMULAS if x["key"] == key), None)
        if not f:
            from rest_framework.exceptions import NotFound
            raise NotFound("公式不存在")
        return Response({k: v for k, v in f.items() if k != "expr"})


class FormulaCalcView(APIView):
    """S08 公式代入计算：{key, values:{变量:数值}}"""

    def post(self, request):
        key = request.data.get("key")
        f = next((x for x in cu.FORMULAS if x["key"] == key), None)
        if not f:
            return Response({"message": "公式不存在"}, status=404)
        raw = request.data.get("values", {})
        values = {}
        for vk, label in f["vars"]:
            try:
                values[vk] = float(raw.get(vk))
            except (TypeError, ValueError):
                return Response({"message": f"缺少或非法的变量：{label}({vk})"}, status=400)
        try:
            result = cu.safe_eval_expr(f["expr"], values)
        except Exception as e:  # noqa
            return Response({"message": f"计算失败：{e}"}, status=400)
        return Response({"key": key, "name": f["name"], "formula": f["formula"], "inputs": values,
                         "result": round(result, 6)})


class PoemListView(APIView):
    """S09 古诗文目录"""

    def get(self, request):
        stage = request.query_params.get("stage")
        items = cn.POEMS
        if stage:
            items = [p for p in items if p["stage"] == stage]
        return Response({"total": len(items),
                         "list": [{"key": p["key"], "title": p["title"], "author": p["author"],
                                   "dynasty": p["dynasty"], "stage": p["stage"]} for p in items]})


class PoemDetailView(APIView):
    """S10 古诗文详情"""

    def get(self, request, key):
        p = next((x for x in cn.POEMS if x["key"] == key), None)
        if not p:
            from rest_framework.exceptions import NotFound
            raise NotFound("古诗文不存在")
        return Response(p)


class PoemDrillView(APIView):
    """S11 古诗接句/默写练习：给上句接下句"""

    def get(self, request):
        stage = request.query_params.get("stage")
        n = as_int(request.query_params.get("n"), default=5, field="n", minimum=1)
        bank = []
        for p in cn.POEMS:
            if stage and p["stage"] != stage:
                continue
            for up, down in p["pairs"]:
                bank.append({"poem": p["title"], "author": p["author"], "prompt": up, "answer": down})
        random.shuffle(bank)
        return Response({"total": len(bank), "list": bank[:n]})


class WordListView(APIView):
    """S12 英语词表（按 stage/topic）"""

    def get(self, request):
        stage, topic = _params(request, "stage", "topic")
        items = en.WORDS
        if stage:
            items = [w for w in items if w["stage"] == stage]
        if topic:
            items = [w for w in items if w["topic"] == topic]
        topics = sorted({w["topic"] for w in en.WORDS if not stage or w["stage"] == stage})
        return Response({"total": len(items), "topics": topics, "list": items})


class WordDetailView(APIView):
    """S13 单词详情"""

    def get(self, request, word):
        w = next((x for x in en.WORDS if x["word"].lower() == word.lower()), None)
        if not w:
            from rest_framework.exceptions import NotFound
            raise NotFound("词库未收录该词")
        return Response(w)


class WordDictationView(APIView):
    """S14 单词听写/默写：给中文释义拼写英文"""

    def get(self, request):
        stage, topic, n = _params(request, "stage", "topic", "n")
        items = en.WORDS
        if stage:
            items = [w for w in items if w["stage"] == stage]
        if topic:
            items = [w for w in items if w["topic"] == topic]
        sample = random.sample(items, min(len(items), as_int(n, default=10, field="n", minimum=1)))
        return Response({"list": [{"prompt": w["meaning"], "phonetic": w["phonetic"], "answer": w["word"], "example": w["example"]} for w in sample]})


class WordQuizView(APIView):
    """S15 单词选择题：给英文选释义"""

    def get(self, request):
        stage = request.query_params.get("stage")
        n = as_int(request.query_params.get("n"), default=5, field="n", minimum=1)
        pool = [w for w in en.WORDS if not stage or w["stage"] == stage]
        quiz = []
        for w in random.sample(pool, min(len(pool), n)):
            distractors = random.sample([x["meaning"] for x in pool if x["word"] != w["word"]], 3)
            opts = distractors + [w["meaning"]]
            random.shuffle(opts)
            quiz.append({"word": w["word"], "phonetic": w["phonetic"], "options": opts, "answer": opts.index(w["meaning"])})
        return Response({"list": quiz})


class WordbookView(APIView):
    """S16 生词本（私有）：列表/新增/删除/标记掌握"""

    def get(self, request):
        qs = WordbookItem.objects.filter(owner=request.user)
        if request.query_params.get("mastered") == "0":
            qs = qs.filter(mastered=False)
        return Response({"total": qs.count(), "list": WordbookItemSerializer(qs, many=True).data})

    def post(self, request):
        word = str(request.data.get("word", "")).strip()
        if not word:
            return Response({"message": "单词不能为空"}, status=400)
        known = next((w for w in en.WORDS if w["word"].lower() == word.lower()), {})
        obj, created = WordbookItem.objects.get_or_create(
            owner=request.user, word=word,
            defaults={"phonetic": request.data.get("phonetic", known.get("phonetic", "")),
                      "meaning": request.data.get("meaning", known.get("meaning", ""))})
        return Response(WordbookItemSerializer(obj).data, status=201 if created else 200)

    def patch(self, request):
        obj = get_object_or_404(WordbookItem, id=as_int(request.data.get("id"), default=None, field="id"), owner=request.user)
        obj.mastered = not obj.mastered
        obj.save(update_fields=["mastered"])
        return Response(WordbookItemSerializer(obj).data)

    def delete(self, request):
        obj = get_object_or_404(WordbookItem, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


class QuestionListView(APIView):
    """S17 题库列表（默认不带答案，供练习）"""

    def get(self, request):
        stage, subject, qtype, difficulty, with_answer = _params(request, "stage", "subject", "type", "difficulty", "answer")
        items = qb.filter_questions(stage, subject, qtype, difficulty)
        show = with_answer == "1"
        return Response({"total": len(items), "list": [qb.public_question(x, show) for x in items]})


class QuestionDetailView(APIView):
    """S18 题目详情（含答案解析）"""

    def get(self, request, qid):
        q = next((x for x in qb.QUESTIONS if x["id"] == qid), None)
        if not q:
            from rest_framework.exceptions import NotFound
            raise NotFound("题目不存在")
        return Response(qb.public_question(q, True))


class PaperComposeView(APIView):
    """S19 智能组卷：按学段/学科/题型/数量抽题，返回试卷与答案卷"""

    def get(self, request):
        return self._compose(request.query_params)

    def post(self, request):
        return self._compose(request.data)

    def _compose(self, params):
        stage, subject = params.get("stage"), params.get("subject")
        count = as_int(params.get("count"), default=10, field="count", minimum=1)
        qtype = params.get("type")
        pool = qb.filter_questions(stage, subject, qtype)
        if not pool:
            return Response({"message": "该条件下暂无题目"}, status=404)
        picked = [random.choice(pool) for _ in range(min(count, len(pool)))] if count > len(pool) else random.sample(pool, count)
        return Response({"stage": stage, "subject": subject, "count": len(picked),
                         "paper": [qb.public_question(x) for x in picked],
                         "answer_sheet": [{"id": x["id"], "answer": x["answer"], "analysis": x["analysis"]} for x in picked]})


class PaperGradeView(APIView):
    """S20 交卷判分：{answers:[{id,answer}]}"""

    def post(self, request):
        answers = request.data.get("answers", [])
        details, correct = [], 0
        for item in answers:
            q = next((x for x in qb.QUESTIONS if x["id"] == item.get("id")), None)
            if not q:
                continue
            ua = item.get("answer")
            if q["type"] in ("single",):
                ok = str(ua) == str(q["answer"])
            elif q["type"] == "judge":
                ok = str(ua).lower() in ("true", "1", "yes", "对", "正确") and q["answer"] is True or \
                     str(ua).lower() in ("false", "0", "no", "错", "错误") and q["answer"] is False
            else:
                ok = _normalize(ua) == _normalize(q["answer"])
            correct += ok
            details.append({"id": q["id"], "correct": ok, "right_answer": q["answer"], "analysis": q["analysis"]})
        total = len(details)
        return Response({"total": total, "correct": correct, "wrong": total - correct,
                         "score": round(correct / total * 100, 1) if total else 0, "details": details})


class MistakeView(APIView):
    """S21 错题本：列表/新增/删除/标记订正"""

    def get(self, request):
        qs = MistakeRecord.objects.filter(owner=request.user)
        subject = request.query_params.get("subject")
        if subject:
            qs = qs.filter(subject=subject)
        if request.query_params.get("mastered") == "0":
            qs = qs.filter(mastered=False)
        return Response({"total": qs.count(), "list": MistakeRecordSerializer(qs, many=True).data})

    def post(self, request):
        ser = MistakeRecordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(owner=request.user)
        return Response(ser.data, status=201)

    def patch(self, request):
        obj = get_object_or_404(MistakeRecord, id=as_int(request.data.get("id"), default=None, field="id"), owner=request.user)
        obj.mastered = not obj.mastered
        obj.save(update_fields=["mastered"])
        return Response(MistakeRecordSerializer(obj).data)

    def delete(self, request):
        obj = get_object_or_404(MistakeRecord, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


class MasteryView(APIView):
    """S22 知识点掌握度：按学科汇总错题订正率与学习进度"""

    def get(self, request):
        agg = {}
        for m in MistakeRecord.objects.filter(owner=request.user):
            a = agg.setdefault(m.subject or "未分类", {"total": 0, "mastered": 0})
            a["total"] += 1
            a["mastered"] += int(m.mastered)
        for v in agg.values():
            v["mastery"] = round(v["mastered"] / v["total"] * 100, 1) if v["total"] else 100
        progress = LearningProgressSerializer(LearningProgress.objects.filter(owner=request.user), many=True).data
        return Response({"by_subject": agg, "progress": progress})


class IdiomListView(APIView):
    """S23 成语词典（搜索）"""

    def get(self, request):
        kw = request.query_params.get("q", "").strip()
        items = cn.IDIOMS
        if kw:
            items = [x for x in cn.IDIOMS if kw in x["word"] or kw in x["meaning"]]
        return Response({"total": len(items), "list": items})


class IdiomChainView(APIView):
    """S24 成语接龙：给定成语，找以末字开头的成语"""

    def get(self, request):
        word = request.query_params.get("word", "").strip()
        if not word:
            return Response({"message": "请输入成语"}, status=400)
        tail = word[-1]
        nxt = [x["word"] for x in cn.IDIOMS if x["word"].startswith(tail)]
        return Response({"word": word, "tail": tail, "next": nxt})


class HanziView(APIView):
    """S25 汉字字典：按字查询 拼音/部首/笔画/释义"""

    def get(self, request):
        key = request.query_params.get("char", "").strip()
        if key:
            hits = [h for h in cn.HANZI if key in h["char"]]
            return Response({"list": hits})
        radical = request.query_params.get("radical")
        items = [h for h in cn.HANZI if not radical or h["radical"] == radical]
        radicals = sorted({h["radical"] for h in cn.HANZI})
        return Response({"total": len(items), "radicals": radicals, "list": items})


class ElementListView(APIView):
    """S26 元素周期表（常用元素）"""

    def get(self, request):
        category = request.query_params.get("category")
        items = ch.ELEMENTS
        if category:
            items = [e for e in items if e["category"] == category]
        cats = sorted({e["category"] for e in ch.ELEMENTS})
        return Response({"total": len(items), "categories": cats, "list": items})


class ElementDetailView(APIView):
    """S27 元素详情：按原子序数或符号"""

    def get(self, request, key):
        e = next((x for x in ch.ELEMENTS if str(x["number"]) == str(key) or x["symbol"].lower() == str(key).lower()), None)
        if not e:
            from rest_framework.exceptions import NotFound
            raise NotFound("未收录该元素")
        return Response(e)


class EquationListView(APIView):
    """S28 化学方程式库"""

    def get(self, request):
        stage, etype = _params(request, "stage", "type")
        items = ch.EQUATIONS
        if stage:
            items = [x for x in items if x["stage"] == stage]
        if etype:
            items = [x for x in items if etype in x["type"]]
        return Response({"total": len(items), "list": items})


class GrammarListView(APIView):
    """S29 英语语法点目录"""

    def get(self, request):
        stage = request.query_params.get("stage")
        items = cu.GRAMMAR
        if stage:
            items = [g for g in items if g["stage"] == stage]
        return Response({"total": len(items), "list": [{"key": g["key"], "title": g["title"], "stage": g["stage"]} for g in items]})


class GrammarDetailView(APIView):
    """S30 语法点详情"""

    def get(self, request, key):
        g = next((x for x in cu.GRAMMAR if x["key"] == key), None)
        if not g:
            from rest_framework.exceptions import NotFound
            raise NotFound("语法点不存在")
        return Response(g)


# ============================================================
# 三、个人学习中心（附加：专注记录 / 学习计划）
# ============================================================
class StudySessionView(APIView):
    """专注记录：列表/新增/删除，含汇总"""

    def get(self, request):
        qs = StudySession.objects.filter(owner=request.user)
        total_minutes = sum(s.minutes for s in qs)
        by_subject = {}
        for s in qs:
            by_subject[s.subject] = by_subject.get(s.subject, 0) + s.minutes
        return Response({"total_minutes": total_minutes, "count": qs.count(),
                         "by_subject": by_subject, "list": StudySessionSerializer(qs, many=True).data})

    def post(self, request):
        d = request.data
        ser = StudySessionSerializer(data=d)
        ser.is_valid(raise_exception=True)
        ser.save(owner=request.user)
        return Response(ser.data, status=201)

    def delete(self, request):
        obj = get_object_or_404(StudySession, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


class StudyPlanView(APIView):
    """学习计划：列表/新增/删除/更新进度"""

    def get(self, request):
        qs = StudyPlan.objects.filter(owner=request.user)
        return Response({"total": qs.count(), "list": StudyPlanSerializer(qs, many=True).data})

    def post(self, request):
        ser = StudyPlanSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(owner=request.user)
        return Response(ser.data, status=201)

    def patch(self, request):
        obj = get_object_or_404(StudyPlan, id=as_int(request.data.get("id"), default=None, field="id"), owner=request.user)
        if "finished" in request.data:
            obj.finished = max(0, min(obj.total, as_int(request.data["finished"], field="finished", minimum=0)))
        if "title" in request.data:
            obj.title = request.data["title"]
        obj.save()
        return Response(StudyPlanSerializer(obj).data)

    def delete(self, request):
        obj = get_object_or_404(StudyPlan, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


# ============================================================
# 四、40 个学习工具：目录 + 统一运行
# ============================================================
class LearnToolCatalogView(APIView):
    """学习工具目录（按分类分组）"""

    def get(self, request):
        categories, total = {}, 0
        for key, (cat, name, desc, _) in LEARN_TOOL_REGISTRY.items():
            categories.setdefault(cat, []).append({"key": key, "name": name, "desc": desc})
            total += 1
        return Response({"total": total, "categories": categories})


class LearnToolRunView(APIView):
    """统一运行：POST /api/learning/tools/run/ {tool,...} 或 /api/learning/tools/<tool>/"""

    def _run(self, tool, params):
        entry = LEARN_TOOL_REGISTRY.get(tool)
        if not entry:
            return Response({"message": f"未知学习工具: {tool}"}, status=404)
        try:
            return Response({"tool": tool, "result": entry[3](params or {})})
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
            return Response({"message": f"输入有误：{e}"}, status=400)

    def post(self, request, tool=None):
        params = dict(request.data)
        tool = tool or params.pop("tool", None)

        def _unwrap(v):
            # 仅把“单元素且元素为标量”的列表解包，保留 [{...}] 这类嵌套结构
            return v[0] if isinstance(v, list) and len(v) == 1 and not isinstance(v[0], (dict, list)) else v

        params = {k: _unwrap(v) for k, v in params.items()}
        return self._run(tool, params)

    def get(self, request, tool=None):
        return self._run(tool, request.query_params)


# ============================================================
# 五、v8 学习闭环增强（dsh 2026-09-30）
#   F519 月度学习报告 / F520 错题重练 / F521 艾宾浩斯复习队列 / F522 连续打卡
#   F533 学习数据导出导入 / F541 弱项雷达 / F542 学习区全局搜索
# 只增不改：全部为新增接口，不动任何既有接口的请求与响应契约。
# ============================================================

# 艾宾浩斯复习间隔（天）：复习次数越多，间隔越长
_EBBINGHAUS = [1, 2, 4, 7, 15, 30, 60]


def _review_due(last_reviewed, review_count):
    """按艾宾浩斯间隔判断某条记录今天是否该复习。"""
    if last_reviewed is None:
        return True
    idx = min(int(review_count or 0), len(_EBBINGHAUS) - 1)
    return (dt.date.today() - last_reviewed).days >= _EBBINGHAUS[idx]


def _norm_answer(v):
    """规范化作答后比较：判断题统一成「对/错」，其余去空白并忽略大小写。"""
    s = str(v if v is not None else "").strip().lower()
    if s in {"true", "t", "1", "对", "正确", "是", "√", "yes", "y"}:
        return "对"
    if s in {"false", "f", "0", "错", "错误", "否", "×", "no", "n"}:
        return "错"
    return re.sub(r"\s+", "", s)


def _subject_cn_map():
    """学科 key → 中文名（取自 curriculum.STAGES，口径与学科中心一致）。"""
    m = {}
    for st in getattr(cu, "STAGES", []):
        for sub in st.get("subjects", []):
            key = sub.get("key")
            if key:
                m.setdefault(key, sub.get("name") or key)
    return m


def _related_formulas(pt):
    """F500（S2）：按名称相关性挑出与知识点**真正相关**的公式。

    原实现返回「该学段 + 该学科」的全部公式（60 条公式里随便挑），与所点知识点无关。
    这里改两级匹配打分：
      · 知识点名与公式名互为包含  +6（强相关，如「浮力」↔「阿基米德浮力」）
      · 章节名与公式名互为包含    +4（章节级相关，如「数列」↔「等差数列前 n 项和」）
      · 知识点二元组重合          +3 × 重合比例
      · 章节二元组重合            +1 × 重合比例
    阈值 4.0（即至少要有一处「包含」关系），按分数取前 5；确实没有相关公式就返回空列表，
    前端会自动隐藏该区块——比塞一堆无关公式更诚实。
    """
    point = (pt.get("name") or "").strip()
    chapter = (pt.get("chapter") or "").strip()
    pool = [f for f in cu.FORMULAS
            if f.get("stage") == pt.get("stage") and f.get("subject") == pt.get("subject")]
    if not pool or not point:
        return []

    def grams(s):
        s = re.sub(r"\s+", "", s or "")
        return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())

    pg, cg = grams(point), grams(chapter)
    scored = []
    for f in pool:
        name = f.get("name", "")
        ng = grams(name)
        score = 0.0
        if name and (point in name or name in point):
            score += 6.0
        if name and chapter and (chapter in name or name in chapter):
            score += 4.0
        score += 3.0 * len(pg & ng) / max(len(pg), 1)
        score += 1.0 * len(cg & ng) / max(len(cg), 1)
        if score >= 4.0:
            scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:5]]


class StudyStreakView(APIView):
    """F522 连续打卡：当前连续 / 历史最长 / 今日时长 / 全部有记录的日期。"""

    def get(self, request):
        qs = StudySession.objects.filter(owner=request.user)
        days = sorted({s.study_date for s in qs})
        today = dt.date.today()
        today_minutes = sum(s.minutes for s in qs if s.study_date == today)
        if not days:
            return Response({"current": 0, "longest": 0, "today_minutes": 0,
                             "total_minutes": 0, "last_date": None, "days": []})
        longest = run = 1
        for prev, cur in zip(days, days[1:]):
            run = run + 1 if (cur - prev).days == 1 else 1
            longest = max(longest, run)
        current, cursor = 0, (today if today in days else today - dt.timedelta(days=1))
        while cursor in days:
            current += 1
            cursor -= dt.timedelta(days=1)
        return Response({
            "current": current,
            "longest": max(longest, current),
            "today_minutes": today_minutes,
            "total_minutes": sum(s.minutes for s in qs),
            "last_date": days[-1].isoformat(),
            "days": [d.isoformat() for d in days],
        })


class StudyReportView(APIView):
    """F519 月度学习报告：时长 / 活跃天数 / 科目分布 / 错题 / 进度，附 Markdown 导出。"""

    def get(self, request):
        month = request.query_params.get("month") or dt.date.today().strftime("%Y-%m")
        try:
            year, mon = int(month.split("-")[0]), int(month.split("-")[1])
            first = dt.date(year, mon, 1)
        except (ValueError, IndexError):
            return Response({"ok": False, "error": "month 需为 YYYY-MM 格式"}, status=400)
        nxt = dt.date(year + 1, 1, 1) if mon == 12 else dt.date(year, mon + 1, 1)
        last = nxt - dt.timedelta(days=1)

        qs = StudySession.objects.filter(owner=request.user, study_date__gte=first, study_date__lte=last)
        total = sum(s.minutes for s in qs)
        active = {s.study_date for s in qs}
        by_subject = {}
        for s in qs:
            by_subject[s.subject] = by_subject.get(s.subject, 0) + s.minutes

        mis = MistakeRecord.objects.filter(owner=request.user,
                                           created_at__date__gte=first, created_at__date__lte=last)
        mis_total, mis_fixed = mis.count(), mis.filter(mastered=True).count()
        prog_updates = LearningProgress.objects.filter(
            owner=request.user, updated_at__date__gte=first, updated_at__date__lte=last).count()

        top = sorted(by_subject.items(), key=lambda kv: -kv[1])[:5]
        lines = [
            f"# {year} 年 {mon} 月学习报告",
            "",
            f"- 累计学习时长：**{total} 分钟**（约 {round(total / 60, 1)} 小时）",
            f"- 有记录的天数：**{len(active)} 天**（本月共 {last.day} 天）",
            f"- 日均时长：**{round(total / last.day, 1)} 分钟**",
            f"- 本月新增错题：**{mis_total} 道**，已订正 **{mis_fixed} 道**",
            f"- 进度更新条目：**{prog_updates} 条**",
            "",
            "## 科目分布（Top 5）",
        ]
        lines += [f"- {k}：{v} 分钟" for k, v in top] or ["- 本月还没有专注记录"]
        lines += [
            "",
            "## 建议",
            "- " + ("保持每天 25 分钟以上的专注记录" if total else "先从一个番茄钟开始，今天记满 25 分钟"),
            "- " + ("错题订正率偏低，建议用「错题重练」优先消化未掌握错题"
                    if mis_total and mis_fixed * 2 < mis_total else "错题订正情况良好，继续按复习队列走"),
        ]
        return Response({
            "month": f"{year}-{mon:02d}", "total_minutes": total, "active_days": len(active),
            "avg_minutes": round(total / last.day, 1), "by_subject": by_subject,
            "mistakes": {"total": mis_total, "fixed": mis_fixed},
            "progress_updates": prog_updates, "markdown": "\n".join(lines),
        })


class StudyReviewQueueView(APIView):
    """F521 艾宾浩斯复习队列：今日应复习的生词与错题；POST 标记「今天已复习」。"""

    def get(self, request):
        words = [w for w in WordbookItem.objects.filter(owner=request.user, mastered=False)
                 if _review_due(w.last_reviewed, w.review_count)]
        mistakes = [m for m in MistakeRecord.objects.filter(owner=request.user, mastered=False)
                    if _review_due(m.last_reviewed, m.redrill_attempts)]
        return Response({
            "date": dt.date.today().isoformat(),
            "total": len(words) + len(mistakes),
            "words": [{"id": w.id, "word": w.word, "phonetic": w.phonetic, "meaning": w.meaning,
                       "review_count": w.review_count,
                       "last_reviewed": w.last_reviewed.isoformat() if w.last_reviewed else None}
                      for w in words],
            "mistakes": [{"id": m.id, "subject": m.subject, "question_type": m.question_type,
                          "stem": m.stem, "attempts": m.redrill_attempts,
                          "last_reviewed": m.last_reviewed.isoformat() if m.last_reviewed else None}
                         for m in mistakes],
        })

    def post(self, request):
        kind, obj_id, today = request.data.get("kind"), as_int(request.data.get("id"), default=None, field="id"), dt.date.today()
        if kind == "word":
            obj = get_object_or_404(WordbookItem, id=obj_id, owner=request.user)
            obj.review_count += 1
        elif kind == "mistake":
            obj = get_object_or_404(MistakeRecord, id=obj_id, owner=request.user)
            obj.redrill_attempts += 1
        else:
            return Response({"ok": False, "error": "kind 需为 word 或 mistake"}, status=400)
        obj.last_reviewed = today
        obj.save()
        return Response({"ok": True, "kind": kind, "id": obj.id, "last_reviewed": today.isoformat()})


_Q_OPTIONS_INDEX = None


def _question_options_index():
    """题干 → 选项。错题本没存 options，重练单选题时按题干回题库取（取不到返回 None）。"""
    global _Q_OPTIONS_INDEX
    if _Q_OPTIONS_INDEX is None:
        idx = {}
        for q in getattr(qb, "QUESTIONS", []):
            stem = (q.get("stem") or "").strip()
            opts = q.get("options")
            if stem and opts:
                idx.setdefault(stem, opts)
        _Q_OPTIONS_INDEX = idx
    return _Q_OPTIONS_INDEX


class StudyReDrillView(APIView):
    """F520 错题重练：GET 抽未掌握错题成卷（不含答案）；POST 交卷记二次正确率。"""

    def get(self, request):
        try:
            n = max(1, min(int(request.query_params.get("n") or 5), 20))
        except (TypeError, ValueError):
            n = 5
        qs = MistakeRecord.objects.filter(owner=request.user, mastered=False)
        subject = request.query_params.get("subject")
        if subject:
            qs = qs.filter(subject=subject)
        items = list(qs[:n])
        idx = _question_options_index()
        rows = []
        for m in items:
            row = {
                "id": m.id, "stage": m.stage, "subject": m.subject,
                "question_type": m.question_type, "difficulty": m.difficulty,
                "stem": m.stem, "attempts": m.redrill_attempts,
                "redrill_correct": m.redrill_correct,
            }
            # 豆包 2026-10-01 反馈：单选题只回题干会让用户盲填序号，这里回填选项
            if m.question_type == "single":
                row["options"] = idx.get((m.stem or "").strip())
            rows.append(row)
        return Response({"total": len(rows), "list": rows})

    def post(self, request):
        m = get_object_or_404(MistakeRecord, id=request.data.get("id"), owner=request.user)
        got, right = _norm_answer(request.data.get("answer")), _norm_answer(m.answer)
        correct = bool(right) and got == right
        m.redrill_attempts += 1
        if correct:
            m.redrill_correct += 1
        m.last_reviewed = dt.date.today()
        m.save()
        rate = round(m.redrill_correct / m.redrill_attempts * 100) if m.redrill_attempts else 0
        return Response({"correct": correct, "right_answer": m.answer, "analysis": m.analysis,
                         "attempts": m.redrill_attempts, "redrill_correct": m.redrill_correct,
                         "redrill_rate": rate})


class StudyWeaknessView(APIView):
    """F541 弱项雷达：按学科 / 题型算订正率，给出补弱顺序。"""

    def get(self, request):
        recs = list(MistakeRecord.objects.filter(owner=request.user))
        sub_cn = _subject_cn_map()
        type_cn = dict(MistakeRecord.TYPES)

        def agg(key_fn, label_fn=None):
            buckets = {}
            for m in recs:
                k = key_fn(m) or ""
                b = buckets.setdefault(k, {"total": 0, "mastered": 0})
                b["total"] += 1
                if m.mastered:
                    b["mastered"] += 1
            rows = []
            for k, v in buckets.items():
                rate = round(v["mastered"] / v["total"] * 100) if v["total"] else 0
                rows.append({
                    "key": k or "unknown",
                    "name": (label_fn(k) if label_fn else k) or "未分类",
                    "total": v["total"], "mastered": v["mastered"],
                    "fixed_rate": rate, "weak": rate < 60,
                })
            rows.sort(key=lambda r: (r["fixed_rate"], -r["total"]))
            return rows

        # 口径统一：name 一律回中文名，另附 key 供前端做稳定映射（豆包 2026-09-30 反馈②）
        by_subject = agg(lambda m: m.subject, lambda k: sub_cn.get(k, k))
        by_type = agg(lambda m: m.question_type, lambda k: type_cn.get(k, k))
        # order = 学科维度（与 by_subject.name 同口径），按订正率升序取前 5（反馈①）
        order = [r["name"] for r in by_subject if r["weak"]] or [r["name"] for r in by_subject]
        return Response({"total": len(recs), "by_subject": by_subject, "by_type": by_type,
                         "order": order[:5]})


class StudyBackupView(APIView):
    """F533 学习数据导出 / 导入（JSON），只覆盖学习区个人数据。"""

    def get(self, request):
        def dump(qs, fields):
            out = []
            for o in qs:
                row = {}
                for f in fields:
                    v = getattr(o, f)
                    row[f] = v.isoformat() if hasattr(v, "isoformat") else v
                out.append(row)
            return out

        return Response({
            "version": 1,
            "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
            "progress": dump(LearningProgress.objects.filter(owner=request.user),
                             ["domain", "target_key", "target_name", "status", "percent", "note"]),
            "bookmarks": dump(SnippetBookmark.objects.filter(owner=request.user),
                              ["language", "title", "code", "note"]),
            "wordbook": dump(WordbookItem.objects.filter(owner=request.user),
                             ["word", "phonetic", "meaning", "mastered", "source", "review_count"]),
            "mistakes": dump(MistakeRecord.objects.filter(owner=request.user),
                             ["stage", "subject", "question_type", "difficulty", "stem", "answer",
                              "user_answer", "analysis", "mastered", "redrill_attempts", "redrill_correct"]),
            "sessions": dump(StudySession.objects.filter(owner=request.user),
                             ["subject", "minutes", "study_date", "note"]),
            "plans": dump(StudyPlan.objects.filter(owner=request.user),
                          ["title", "subject", "total", "days", "plan", "finished", "start_date"]),
        })

    def post(self, request):
        """导入：只新增、不覆盖既有数据（进度按 owner+domain+target_key 去重更新）。"""
        d = request.data or {}
        created = {"progress": 0, "bookmarks": 0, "wordbook": 0, "mistakes": 0, "sessions": 0, "plans": 0}
        for it in d.get("progress", []):
            LearningProgress.objects.update_or_create(
                owner=request.user, domain=it.get("domain", "programming"),
                target_key=it.get("target_key", ""),
                defaults={"target_name": it.get("target_name", ""),
                          "status": it.get("status", "learning"),
                          "percent": as_int(it.get("percent") or 0, field="percent"), "note": it.get("note", "")})
            created["progress"] += 1
        for it in d.get("bookmarks", []):
            SnippetBookmark.objects.create(owner=request.user, language=it.get("language", ""),
                                           title=it.get("title", ""), code=it.get("code", ""),
                                           note=it.get("note", ""))
            created["bookmarks"] += 1
        for it in d.get("wordbook", []):
            WordbookItem.objects.get_or_create(
                owner=request.user, word=it.get("word", ""),
                defaults={"phonetic": it.get("phonetic", ""), "meaning": it.get("meaning", ""),
                          "mastered": parse_bool(it.get("mastered"), field="mastered"), "source": it.get("source", "import")})
            created["wordbook"] += 1
        for it in d.get("mistakes", []):
            MistakeRecord.objects.create(
                owner=request.user, stage=it.get("stage", ""), subject=it.get("subject", ""),
                question_type=it.get("question_type", "single"), difficulty=as_int(it.get("difficulty") or 1, field="difficulty"),
                stem=it.get("stem", ""), answer=it.get("answer", ""), user_answer=it.get("user_answer", ""),
                analysis=it.get("analysis", ""), mastered=parse_bool(it.get("mastered"), field="mastered"))
            created["mistakes"] += 1
        for it in d.get("sessions", []):
            StudySession.objects.create(
                owner=request.user, subject=it.get("subject", "通用"),
                minutes=as_int(it.get("minutes") or 0, field="minutes"),
                study_date=it.get("study_date") or dt.date.today(), note=it.get("note", ""))
            created["sessions"] += 1
        for it in d.get("plans", []):
            StudyPlan.objects.create(
                owner=request.user, title=it.get("title", "导入计划"), subject=it.get("subject", ""),
                total=as_int(it.get("total") or 0, field="total"), days=as_int(it.get("days") or 7, field="days"),
                plan=it.get("plan") or [], finished=as_int(it.get("finished") or 0, field="finished"),
                start_date=it.get("start_date") or dt.date.today())
            created["plans"] += 1
        return Response({"ok": True, "created": created})


class ProgRadarView(APIView):
    """F535 多语言进度雷达的数据面：10 门语言各维度的完成度，供前端手写 SVG。

    维度：进度完成度（LearningProgress.percent）、收藏片段数、是否已开始。
    """

    def get(self, request):
        prog = {p.target_key: p for p in LearningProgress.objects.filter(
            owner=request.user, domain="programming")}
        marks = {}
        for b in SnippetBookmark.objects.filter(owner=request.user):
            marks[b.language] = marks.get(b.language, 0) + 1
        rows = []
        for key in LANG_ORDER:
            brief = lang_brief(key) or {}
            p = prog.get(key)
            rows.append({
                "key": key,
                "name": brief.get("name", key),
                "icon": brief.get("icon", ""),
                "percent": p.percent if p else 0,
                "status": p.status if p else "not_started",
                "bookmarks": marks.get(key, 0),
                "started": bool(p),
            })
        started = [r for r in rows if r["started"]]
        return Response({
            "langs": rows,
            "started_count": len(started),
            "avg_percent": round(sum(r["percent"] for r in started) / len(started)) if started else 0,
        })


class LearningGlobalSearchView(APIView):
    """F542 学习区全局搜索：诗词 / 单词 / 成语 / 汉字 / 公式 / 题目 / 知识点，一个框。"""

    LIMIT = 6

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"ok": False, "error": "请输入关键词 q"}, status=400)
        low = q.lower()

        def hit(*vals):
            return any(low in str(v or "").lower() for v in vals)

        poems = [{"key": p.get("key"), "title": p.get("title"),
                  "sub": f"{p.get('dynasty', '')} · {p.get('author', '')}"}
                 for p in cn.POEMS if hit(p.get("title"), p.get("text"), p.get("author"))][:self.LIMIT]
        words = [{"word": w.get("word"), "sub": w.get("meaning")}
                 for w in en.WORDS if hit(w.get("word"), w.get("meaning"))][:self.LIMIT]
        idioms = [{"word": i.get("word"), "sub": i.get("meaning")}
                  for i in cn.IDIOMS if hit(i.get("word"), i.get("meaning"))][:self.LIMIT]
        hanzi = [{"char": h.get("char"), "sub": f"{h.get('pinyin', '')} · {h.get('meaning', '')}"}
                 for h in cn.HANZI if hit(h.get("char"), h.get("meaning"), h.get("pinyin"))][:self.LIMIT]
        formulas = [{"key": f.get("key"), "name": f.get("name"), "sub": f.get("formula")}
                    for f in cu.FORMULAS if hit(f.get("name"), f.get("formula"))][:self.LIMIT]
        questions = [{"id": x.get("id"), "sub": x.get("stem"),
                      "meta": f"{x.get('stage')} · {x.get('subject')} · {x.get('type')}"}
                     for x in qb.QUESTIONS if hit(x.get("stem"), x.get("kp"))][:self.LIMIT]
        points = []
        for stage_subject, chapters in cu.KNOWLEDGE.items():
            for blk in chapters:
                ch_name = blk.get("chapter", "")
                for pt_name in blk.get("points", []):
                    if hit(pt_name, ch_name):
                        points.append({"stage_subject": stage_subject, "chapter": ch_name, "name": pt_name})
                    if len(points) >= self.LIMIT:
                        break
                if len(points) >= self.LIMIT:
                    break
            if len(points) >= self.LIMIT:
                break

        groups = {"poems": poems, "words": words, "idioms": idioms, "hanzi": hanzi,
                  "formulas": formulas, "questions": questions, "points": points}
        return Response({"q": q, "total": sum(len(v) for v in groups.values()), "groups": groups})


# ============================================================
# 六、v8 学习区新增能力（dsh 2026-10-01）
#   F523 每日目标 / F524 番茄钟 / F525 自定义题单 / F526 掌握度自评 / F528 古诗填空
#   F529 成语接龙战绩 / F530 方程式配平练习 / F531 听写错词入生词本 / F532 公式收藏
#   F536 题目收藏 / F537 试卷存档 / F538 工具使用历史 / F539 知识点关联推荐
#   F540 学习徽章 / F543 听写逐词反馈 / F544 进度详情 / F545 错因归类 / F546 计划排程解释
# 只增不改：全部为新增接口与新增模型，不动既有接口契约。
# ============================================================


def _questions_by_ids(ids):
    """按题目 ID 回题目（默认不带答案）。"""
    idx = {q.get("id"): q for q in getattr(qb, "QUESTIONS", [])}
    out = []
    for i in (ids or []):
        q = idx.get(i)
        if q:
            out.append(qb.public_question(q, with_answer=False))
    return out


class DailyGoalView(APIView):
    """F523 每日学习目标与达成率。"""

    def get(self, request):
        goal, _ = DailyGoal.objects.get_or_create(owner=request.user)
        today = dt.date.today()
        minutes = sum(s.minutes for s in StudySession.objects.filter(owner=request.user, study_date=today))
        target = goal.target_minutes or 0
        return Response({
            "target_minutes": target, "today_minutes": minutes,
            "rate": round(minutes / target * 100) if target else 0,
            "achieved": bool(target) and minutes >= target,
            "note": goal.note,
        })

    def post(self, request):
        goal, _ = DailyGoal.objects.get_or_create(owner=request.user)
        if "target_minutes" in request.data:
            goal.target_minutes = as_int(request.data["target_minutes"], field="target_minutes", minimum=0, maximum=1440)
        if "note" in request.data:
            goal.note = str(request.data["note"])[:255]
        goal.save()
        return self.get(request)


class PomodoroView(APIView):
    """F524 番茄钟专注闭环：25 分钟一轮，记录完成 / 打断。"""

    ROUND = 25

    def get(self, request):
        today = dt.date.today()
        qs = StudySession.objects.filter(owner=request.user, study_date=today, subject="番茄钟")
        rows = list(qs)
        broken = [s for s in rows if "打断" in (s.note or "")]
        return Response({
            "round_minutes": self.ROUND,
            "total_rounds": len(rows),
            "finished": len(rows) - len(broken),
            "interrupted": len(broken),
            "focus_minutes": sum(s.minutes for s in rows),
            "list": [{"id": s.id, "minutes": s.minutes, "note": s.note,
                      "at": s.created_at.isoformat(timespec="seconds")} for s in rows],
        })

    def post(self, request):
        minutes = as_int(request.data.get("minutes") or self.ROUND, field="minutes")
        interrupted = parse_bool(request.data.get("interrupted"), field="interrupted")
        s = StudySession.objects.create(
            owner=request.user, subject="番茄钟", minutes=max(1, min(240, minutes)),
            study_date=dt.date.today(), note="打断" if interrupted else "完成")
        return Response({"ok": True, "id": s.id, "interrupted": interrupted}, status=201)


class QuestionSetView(APIView):
    """F525 自定义题单：列表 / 详情取题 / 新建 / 改名 / 删除。"""

    def get(self, request):
        sid = request.query_params.get("id")
        if sid:
            obj = get_object_or_404(QuestionSet, id=as_int(sid, field="id"), owner=request.user)
            return Response({"id": obj.id, "name": obj.name, "note": obj.note,
                             "question_ids": obj.question_ids or [],
                             "list": _questions_by_ids(obj.question_ids)})
        qs = QuestionSet.objects.filter(owner=request.user)
        return Response({"total": qs.count(), "list": [
            {"id": o.id, "name": o.name, "note": o.note, "count": len(o.question_ids or []),
             "created_at": o.created_at.isoformat(timespec="seconds")} for o in qs]})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"ok": False, "error": "请填写题单名称"}, status=400)
        ids = request.data.get("question_ids") or []
        if not isinstance(ids, list):
            return Response({"ok": False, "error": "question_ids 需为数组"}, status=400)
        obj = QuestionSet.objects.create(owner=request.user, name=name[:128],
                                         question_ids=ids[:200],
                                         note=str(request.data.get("note", ""))[:255])
        return Response({"ok": True, "id": obj.id, "count": len(obj.question_ids)}, status=201)

    def patch(self, request):
        obj = get_object_or_404(QuestionSet, id=as_int(request.data.get("id"), default=None, field="id"), owner=request.user)
        if request.data.get("name"):
            obj.name = str(request.data["name"])[:128]
        if "note" in request.data:
            obj.note = str(request.data["note"])[:255]
        if isinstance(request.data.get("question_ids"), list):
            obj.question_ids = request.data["question_ids"][:200]
        obj.save()
        return Response({"ok": True, "id": obj.id, "count": len(obj.question_ids or [])})

    def delete(self, request):
        obj = get_object_or_404(QuestionSet, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


class MasteryRatingView(APIView):
    """F526 知识点掌握度自评（1–5 星）。"""

    def get(self, request):
        qs = MasteryRating.objects.filter(owner=request.user)
        sk = request.query_params.get("stage_subject")
        if sk:
            qs = qs.filter(stage_subject=sk)
        rows = [{"id": o.id, "stage_subject": o.stage_subject, "point": o.point, "stars": o.stars,
                 "updated_at": o.updated_at.isoformat(timespec="seconds")} for o in qs]
        return Response({"total": len(rows),
                         "avg_stars": round(sum(r["stars"] for r in rows) / len(rows), 2) if rows else 0,
                         "list": rows})

    def post(self, request):
        sk = (request.data.get("stage_subject") or "").strip()
        point = (request.data.get("point") or "").strip()
        if not sk or not point:
            return Response({"ok": False, "error": "stage_subject 与 point 必填"}, status=400)
        try:
            stars = max(1, min(5, int(request.data.get("stars") or 3)))
        except (TypeError, ValueError):
            stars = 3
        obj, _ = MasteryRating.objects.update_or_create(
            owner=request.user, stage_subject=sk[:64], point=point[:128],
            defaults={"stars": stars})
        return Response({"ok": True, "id": obj.id, "stars": obj.stars}, status=201)

    def delete(self, request):
        obj = get_object_or_404(MasteryRating, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


class PoemFillBlankView(APIView):
    """F528 古诗填空练习：自动挖空 + 按上句判分。"""

    @staticmethod
    def _lines(poem):
        return [x for x in re.split(r"[，。；！？\n]", poem.get("text", "")) if x.strip()]

    def get(self, request):
        key = request.query_params.get("key")
        pool = [p for p in cn.POEMS if not key or p.get("key") == key]
        if not pool:
            return Response({"ok": False, "error": "未收录该篇目"}, status=404)
        p = random.choice(pool)
        pairs = p.get("pairs") or []
        if pairs:
            shang, xia = random.choice(pairs)
        else:
            lines = self._lines(p)
            if len(lines) < 2:
                return Response({"ok": False, "error": "该篇目暂不支持挖空"}, status=400)
            i = random.randrange(len(lines) - 1)
            shang, xia = lines[i], lines[i + 1]
        return Response({"key": p["key"], "title": p["title"], "author": p.get("author", ""),
                         "dynasty": p.get("dynasty", ""), "shang": shang, "answer": xia})

    def post(self, request):
        key = request.data.get("key")
        shang = (request.data.get("shang") or "").strip()
        p = next((x for x in cn.POEMS if x.get("key") == key), None)
        if not p:
            return Response({"ok": False, "error": "未收录该篇目"}, status=404)
        expected = None
        for a, b in (p.get("pairs") or []):
            if a == shang:
                expected = b
                break
        if expected is None:
            lines = self._lines(p)
            for i, ln in enumerate(lines[:-1]):
                if ln == shang:
                    expected = lines[i + 1]
                    break
        if expected is None:
            return Response({"ok": False, "error": "找不到对应的上句"}, status=400)
        return Response({"correct": _norm_answer(request.data.get("answer")) == _norm_answer(expected),
                         "right_answer": expected})


class IdiomChainRecordView(APIView):
    """F529 成语接龙战绩：记录链长与难度，返回个人最佳。"""

    def get(self, request):
        qs = list(IdiomChainRecord.objects.filter(owner=request.user)[:20])
        return Response({
            "total": IdiomChainRecord.objects.filter(owner=request.user).count(),
            "best": qs[0].length if qs else 0,
            "by_difficulty": {lv: max([o.length for o in qs if o.difficulty == lv] or [0])
                              for lv, _ in IdiomChainRecord.LEVELS},
            "list": [{"id": o.id, "length": o.length, "difficulty": o.difficulty, "chain": o.chain,
                      "created_at": o.created_at.isoformat(timespec="seconds")} for o in qs],
        })

    def post(self, request):
        chain = request.data.get("chain") or []
        if not isinstance(chain, list):
            return Response({"ok": False, "error": "chain 需为数组"}, status=400)
        diff = request.data.get("difficulty") or "normal"
        if diff not in dict(IdiomChainRecord.LEVELS):
            diff = "normal"
        obj = IdiomChainRecord.objects.create(owner=request.user, length=len(chain),
                                              difficulty=diff, chain=chain[:100])
        return Response({"ok": True, "id": obj.id, "length": obj.length}, status=201)


class EquationPracticeView(APIView):
    """F530 化学方程式配平练习：出题（不含系数）+ 判分。"""

    def get(self, request):
        pool = [e for e in ch.EQUATIONS if e.get("reactants") and e.get("products")]
        if not pool:
            return Response({"ok": False, "error": "方程式库为空"}, status=400)
        e = random.choice(pool)
        return Response({"key": e["key"], "type": e.get("type"), "condition": e.get("condition"),
                         "left_forms": [f for f, _ in e["reactants"]],
                         "right_forms": [f for f, _ in e["products"]]})

    def post(self, request):
        e = next((x for x in ch.EQUATIONS if x.get("key") == request.data.get("key")), None)
        if not e:
            return Response({"ok": False, "error": "找不到该方程式"}, status=404)

        def to_ints(v):
            if not isinstance(v, list):
                return None
            try:
                return [int(x) for x in v]
            except (TypeError, ValueError):
                return None

        gl, gr = to_ints(request.data.get("left")), to_ints(request.data.get("right"))
        if gl is None or gr is None:
            return Response({"ok": False, "error": "left / right 需为整数数组"}, status=400)
        el = [n for _, n in e["reactants"]]
        er = [n for _, n in e["products"]]
        return Response({"correct": gl == el and gr == er,
                         "left_answer": el, "right_answer": er,
                         "equation": e.get("equation"), "balance_tip": e.get("balance_tip")})


class DictationCollectView(APIView):
    """F531 听写错词自动入生词本（带来源标记）。"""

    def post(self, request):
        words = request.data.get("words") or []
        if not isinstance(words, list):
            return Response({"ok": False, "error": "words 需为数组"}, status=400)
        idx = {w.get("word"): w for w in en.WORDS}
        added, skipped = [], []
        for raw in words[:100]:
            w = str(raw or "").strip().lower()
            if not w:
                continue
            src = idx.get(w, {})
            obj, created = WordbookItem.objects.get_or_create(
                owner=request.user, word=w,
                defaults={"phonetic": src.get("phonetic", ""), "meaning": src.get("meaning", ""),
                          "source": "dictation"})
            (added if created else skipped).append(w)
        return Response({"ok": True, "added": added, "skipped": skipped,
                         "added_count": len(added)})


class DictationGradeView(APIView):
    """F543 听写逐词反馈：对/错 + 正确拼写。"""

    def post(self, request):
        items = request.data.get("items")
        if not isinstance(items, list):
            return Response({"ok": False, "error": "items 需为数组，元素形如 {answer, expected}"}, status=400)
        idx = {w.get("word"): w for w in en.WORDS}
        rows = []
        for it in items[:200]:
            expected = str((it or {}).get("expected") or "").strip().lower()
            answer = str((it or {}).get("answer") or "").strip().lower()
            src = idx.get(expected, {})
            rows.append({
                "expected": expected, "answer": answer, "correct": answer == expected,
                "phonetic": src.get("phonetic", ""), "meaning": src.get("meaning", ""),
                "example": src.get("example", ""),
            })
        right = sum(1 for r in rows if r["correct"])
        return Response({"total": len(rows), "right": right,
                         "score": round(right / len(rows) * 100) if rows else 0, "list": rows})


class FormulaFavoriteView(APIView):
    """F532 公式收藏夹。"""

    def get(self, request):
        qs = FormulaFavorite.objects.filter(owner=request.user)
        keys = [o.formula_key for o in qs]
        idx = {f.get("key"): f for f in cu.FORMULAS}
        return Response({"total": len(keys), "keys": keys, "list": [
            {"key": k, "name": idx.get(k, {}).get("name", k), "formula": idx.get(k, {}).get("formula", ""),
             "stage": idx.get(k, {}).get("stage", ""), "subject": idx.get(k, {}).get("subject", "")}
            for k in keys if k in idx]})

    def post(self, request):
        key = (request.data.get("key") or "").strip()
        if not key:
            return Response({"ok": False, "error": "缺少 key"}, status=400)
        obj, created = FormulaFavorite.objects.get_or_create(owner=request.user, formula_key=key[:64])
        if not created and request.data.get("toggle", True):
            obj.delete()
            return Response({"ok": True, "favorited": False})
        return Response({"ok": True, "favorited": True})

    def delete(self, request):
        FormulaFavorite.objects.filter(owner=request.user,
                                       formula_key=request.query_params.get("key")).delete()
        return Response({"deleted": True})


class QuestionFavoriteView(APIView):
    """F536 题目收藏（加星筛选）。"""

    def get(self, request):
        qs = QuestionFavorite.objects.filter(owner=request.user)
        ids = [o.question_id for o in qs]
        return Response({"total": len(ids), "ids": ids, "list": _questions_by_ids(ids)})

    def post(self, request):
        qid = (request.data.get("id") or "").strip()
        if not qid:
            return Response({"ok": False, "error": "缺少 id"}, status=400)
        obj, created = QuestionFavorite.objects.get_or_create(owner=request.user, question_id=qid[:64])
        if not created and request.data.get("toggle", True):
            obj.delete()
            return Response({"ok": True, "favorited": False})
        return Response({"ok": True, "favorited": True})

    def delete(self, request):
        QuestionFavorite.objects.filter(owner=request.user,
                                        question_id=as_int(request.query_params.get("id"), default=None, field="id")).delete()
        return Response({"deleted": True})


class PaperArchiveView(APIView):
    """F537 组卷结果存档与重做。"""

    def get(self, request):
        aid = request.query_params.get("id")
        if aid:
            obj = get_object_or_404(PaperArchive, id=as_int(aid, field="id"), owner=request.user)
            return Response({"id": obj.id, "title": obj.title, "stage": obj.stage,
                             "subject": obj.subject, "total": obj.total,
                             "last_score": obj.last_score, "payload": obj.payload})
        qs = PaperArchive.objects.filter(owner=request.user)
        return Response({"total": qs.count(), "list": [
            {"id": o.id, "title": o.title, "stage": o.stage, "subject": o.subject,
             "total": o.total, "last_score": o.last_score,
             "created_at": o.created_at.isoformat(timespec="seconds")} for o in qs]})

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"ok": False, "error": "请填写试卷名称"}, status=400)
        payload = request.data.get("payload") or {}
        if not isinstance(payload, dict):
            return Response({"ok": False, "error": "payload 需为对象"}, status=400)
        obj = PaperArchive.objects.create(
            owner=request.user, title=title[:128],
            stage=str(request.data.get("stage", ""))[:20],
            subject=str(request.data.get("subject", ""))[:20],
            payload=payload, total=as_int(request.data.get("total") or 0, field="total"))
        return Response({"ok": True, "id": obj.id}, status=201)

    def patch(self, request):
        """交卷后回写得分。"""
        obj = get_object_or_404(PaperArchive, id=as_int(request.data.get("id"), default=None, field="id"), owner=request.user)
        if "last_score" in request.data:
            try:
                obj.last_score = max(0, min(100, int(request.data["last_score"])))
            except (TypeError, ValueError):
                pass
        obj.save()
        return Response({"ok": True, "id": obj.id, "last_score": obj.last_score})

    def delete(self, request):
        obj = get_object_or_404(PaperArchive, id=as_int(request.query_params.get("id"), default=None, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


class ToolUsageView(APIView):
    """F538 学习工具使用历史（最近用过可快速重开）。"""

    def get(self, request):
        qs = ToolUsageLog.objects.filter(owner=request.user)
        seen, rows = set(), []
        for o in qs:
            if o.tool_key in seen:
                continue
            seen.add(o.tool_key)
            entry = LEARN_TOOL_REGISTRY.get(o.tool_key)
            rows.append({"key": o.tool_key, "name": (entry[1] if entry else o.tool_key),
                         "used_at": o.used_at.isoformat(timespec="seconds")})
            if len(rows) >= 12:
                break
        return Response({"total": qs.count(), "list": rows})

    def post(self, request):
        key = (request.data.get("key") or "").strip()
        if not key:
            return Response({"ok": False, "error": "缺少 key"}, status=400)
        if key not in LEARN_TOOL_REGISTRY:
            return Response({"ok": False, "error": f"未知学习工具: {key}"}, status=404)
        ToolUsageLog.objects.create(owner=request.user, tool_key=key[:64])
        return Response({"ok": True}, status=201)


class KnowledgeRelatedView(APIView):
    """F539 知识点关联推荐：同章节兄弟点 + 同学科相似名。"""

    LIMIT = 6

    def get(self, request):
        kid = request.query_params.get("kid")
        pt = next((x for x in _ALL_POINTS if x["id"] == kid), None)
        if not pt:
            return Response({"ok": False, "error": "知识点不存在"}, status=404)
        name, chapter = pt["name"], pt["chapter"]
        pool = [x for x in _ALL_POINTS
                if x["stage"] == pt["stage"] and x["subject"] == pt["subject"] and x["id"] != pt["id"]]

        def grams(s):
            s = re.sub(r"\s+", "", s or "")
            return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())

        ng = grams(name)
        scored = []
        for x in pool:
            score = 0.0
            if x["chapter"] == chapter:
                score += 3.0
            xg = grams(x["name"])
            score += 3.0 * len(ng & xg) / max(len(ng), 1)
            if score > 0:
                scored.append((score, x))
        scored.sort(key=lambda t: -t[0])
        return Response({"kid": kid, "name": name, "chapter": chapter, "list": [
            {"id": x["id"], "name": x["name"], "chapter": x["chapter"],
             "stage": x["stage"], "subject": x["subject"]} for _, x in scored[:self.LIMIT]]})


# 学习徽章定义：code → (名称, 说明, 判定函数)
def _badge_defs():
    def _streak(user):
        days = sorted({s.study_date for s in StudySession.objects.filter(owner=user)})
        best = run = 0
        prev = None
        for d in days:
            run = run + 1 if prev and (d - prev).days == 1 else 1
            best = max(best, run)
            prev = d
        return best

    return [
        ("first_step", "启程", "完成第一次专注记录", lambda u: StudySession.objects.filter(owner=u).exists()),
        ("streak3", "三日不辍", "连续打卡 3 天", lambda u: _streak(u) >= 3),
        ("streak7", "七日成习", "连续打卡 7 天", lambda u: _streak(u) >= 7),
        ("fix10", "订正达人", "订正掌握 10 道错题", lambda u: MistakeRecord.objects.filter(owner=u, mastered=True).count() >= 10),
        ("word50", "词库初成", "生词本累计 50 词", lambda u: WordbookItem.objects.filter(owner=u).count() >= 50),
        ("focus600", "专注十时", "累计专注 600 分钟", lambda u: sum(s.minutes for s in StudySession.objects.filter(owner=u)) >= 600),
        ("polymath", "博闻", "自评过 5 个知识点", lambda u: MasteryRating.objects.filter(owner=u).count() >= 5),
    ]


class LearningBadgeView(APIView):
    """F540 学习中心徽章：惰性结算并返回全部徽章状态。"""

    def get(self, request):
        owned = {b.code: b for b in LearningBadge.objects.filter(owner=request.user)}
        new = []
        for code, title, desc, test in _badge_defs():
            if code in owned:
                continue
            try:
                hit = bool(test(request.user))
            except Exception:
                hit = False
            if hit:
                owned[code] = LearningBadge.objects.create(owner=request.user, code=code)
                new.append(code)
        return Response({
            "unlocked": len(owned),
            "total": len(_badge_defs()),
            "new": new,
            "list": [{"code": code, "title": title, "desc": desc,
                      "unlocked": code in owned,
                      "unlocked_at": owned[code].unlocked_at.isoformat(timespec="seconds") if code in owned else None}
                     for code, title, desc, _ in _badge_defs()],
        })


class ProgressDetailView(APIView):
    """F544 进度条目详情：该项信息 + 相关收藏/错题/专注历史。"""

    def get(self, request):
        pid = request.query_params.get("id")
        obj = get_object_or_404(LearningProgress, id=as_int(pid, default=None, field="id"), owner=request.user)
        target = obj.target_key
        related = []
        if obj.domain == "programming":
            related = [{"kind": "收藏片段", "title": b.title, "at": b.created_at.isoformat(timespec="seconds")}
                       for b in SnippetBookmark.objects.filter(owner=request.user, language=target)[:10]]
        elif obj.domain == "school":
            subj = target.split(".")[-1] if "." in target else target
            related = [{"kind": "错题", "title": m.stem[:40], "at": m.created_at.isoformat(timespec="seconds")}
                       for m in MistakeRecord.objects.filter(owner=request.user, subject=subj)[:10]]
        return Response({
            "id": obj.id, "domain": obj.domain, "target_key": target,
            "target_name": obj.target_name, "status": obj.status, "percent": obj.percent,
            "note": obj.note,
            "created_at": obj.created_at.isoformat(timespec="seconds"),
            "updated_at": obj.updated_at.isoformat(timespec="seconds"),
            "related": related,
        })


class MistakeCauseView(APIView):
    """F545 错题错因归类：设置错因 + 汇总分布。"""

    def get(self, request):
        recs = list(MistakeRecord.objects.filter(owner=request.user))
        buckets = {k: 0 for k, _ in MistakeRecord.CAUSES}
        unset = 0
        for m in recs:
            if m.cause and m.cause in buckets:
                buckets[m.cause] += 1
            else:
                unset += 1
        return Response({
            "total": len(recs), "unset": unset,
            "causes": [{"key": k, "name": v, "count": buckets[k]} for k, v in MistakeRecord.CAUSES],
            "by_subject": {},
        })

    def post(self, request):
        m = get_object_or_404(MistakeRecord, id=as_int(request.data.get("id"), default=None, field="id"), owner=request.user)
        cause = (request.data.get("cause") or "").strip()
        if cause and cause not in dict(MistakeRecord.CAUSES):
            return Response({"ok": False, "error": "cause 取值非法"}, status=400)
        m.cause = cause
        m.save(update_fields=["cause"])
        return Response({"ok": True, "id": m.id, "cause": m.cause})


class StudyPlanDetailView(APIView):
    """F546 学习计划详情：解释排程逻辑。"""

    def get(self, request):
        pid = request.query_params.get("id")
        obj = get_object_or_404(StudyPlan, id=as_int(pid, default=None, field="id"), owner=request.user)
        plan = obj.plan or []
        total = obj.total or 0
        per_day = round(total / obj.days, 1) if obj.days else 0
        return Response({
            "id": obj.id, "title": obj.title, "subject": obj.subject,
            "total": obj.total, "days": obj.days, "finished": obj.finished,
            "start_date": obj.start_date.isoformat(),
            "plan": plan,
            "explain": {
                "per_day_avg": per_day,
                "rule": f"总任务 {total} 项 ÷ {obj.days} 天 ≈ 每天 {per_day} 项，最后一天补足余数；"
                        "任务量按天数均分，避免前期过载。",
                "remain": max(0, total - obj.finished),
                "progress_rate": round(obj.finished / total * 100) if total else 0,
            },
        })
