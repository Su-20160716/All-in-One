# -*- coding: utf-8 -*-
"""代码工坊视图（三）：竞技教学（L5 第 87~100 条）。

包含：每日一题 / 成就徽章 / 错题本 / 学习路径 / 代码挑战赛。

设计要点：
- 成就解锁走 `check_achievements()`，基于实时统计数据惰性计算并落库，
  不用定时任务——用户访问「我的成就」时才结算，简单可靠。
- 每日一题复用 `views_core.run_judge()`，不重复实现判题。
- 学习路径优先用 LLM 生成，无 Key 时用 `_local_path()` 模板降级。
"""
import datetime
import random

from django.db.models import Count, Q
from django.utils import timezone

from assistant import llm

from devtools.common import (
    endpoint, ok, fail, p, req, req_str, opt_str, req_num, opt_num, opt_bool, req_list,
)

from . import runtime as rt
from .models import (
    CodeAchievement,
    CodeDailyChallenge,
    CodeDailyRecord,
    CodeFile,
    CodeJudgeTask,
    CodeLearningPath,
    CodeRun,
    CodeUserAchievement,
    CodeWorkspace,
    CodeWrongBook,
)
from .views_core import run_judge

# ============================================================
# 一、每日一题（第 90 条）
# ============================================================

# 内置题库：没有数据库题目时按日期确定性轮换，保证「每天都有题」且全员一致
_FALLBACK_PROBLEMS = [
    {
        "title": "两数之和",
        "description": "读入一行两个整数，输出它们的和。\n\n输入示例：3 5\n输出示例：8",
        "language": "python",
        "difficulty": "easy",
        "template": "# 读取一行两个整数并输出和\n",
        "testcases": [
            {"stdin": "3 5", "expected": "8"},
            {"stdin": "-2 7", "expected": "5"},
            {"stdin": "0 0", "expected": "0"},
        ],
        "tags": ["基础", "输入输出"],
    },
    {
        "title": "斐波那契第 N 项",
        "description": "读入整数 n（1<=n<=30），输出斐波那契数列第 n 项（F(1)=1, F(2)=1）。",
        "language": "python",
        "difficulty": "easy",
        "template": "def fib(n):\n    pass\n\nprint(fib(int(input())))\n",
        "testcases": [
            {"stdin": "1", "expected": "1"},
            {"stdin": "7", "expected": "13"},
            {"stdin": "20", "expected": "6765"},
        ],
        "tags": ["递归", "动态规划"],
    },
    {
        "title": "判断回文串",
        "description": "读入一个字符串，忽略大小写，判断是否回文。是输出 YES，否输出 NO。",
        "language": "python",
        "difficulty": "easy",
        "template": "s = input().strip()\n",
        "testcases": [
            {"stdin": "AbBa", "expected": "YES"},
            {"stdin": "hello", "expected": "NO"},
            {"stdin": "A", "expected": "YES"},
        ],
        "tags": ["字符串", "双指针"],
    },
    {
        "title": "数组最大值与下标",
        "description": "第一行读入 n，第二行读入 n 个整数，输出最大值和它第一次出现的下标（从 0 开始），空格分隔。",
        "language": "python",
        "difficulty": "medium",
        "template": "n = int(input())\nnums = list(map(int, input().split()))\n",
        "testcases": [
            {"stdin": "5\n3 9 2 9 1", "expected": "9 1"},
            {"stdin": "3\n-1 -5 -2", "expected": "-1 0"},
        ],
        "tags": ["数组", "遍历"],
    },
    {
        "title": "括号匹配",
        "description": "读入只含 ()[]{} 的字符串，判断括号是否合法配对。合法输出 YES，否则 NO。",
        "language": "python",
        "difficulty": "medium",
        "template": "s = input().strip()\n",
        "testcases": [
            {"stdin": "()[]{}", "expected": "YES"},
            {"stdin": "(]", "expected": "NO"},
            {"stdin": "([{}])", "expected": "YES"},
        ],
        "tags": ["栈", "字符串"],
    },
    {
        "title": "去重并排序",
        "description": "读入一行整数（空格分隔），输出去重后升序排列的结果，空格分隔。",
        "language": "python",
        "difficulty": "easy",
        "template": "nums = list(map(int, input().split()))\n",
        "testcases": [
            {"stdin": "3 1 3 2 1", "expected": "1 2 3"},
            {"stdin": "5", "expected": "5"},
        ],
        "tags": ["集合", "排序"],
    },
    {
        "title": "质数筛",
        "description": "读入整数 n（2<=n<=1000），升序输出不超过 n 的所有质数，空格分隔。",
        "language": "python",
        "difficulty": "medium",
        "template": "n = int(input())\n",
        "testcases": [
            {"stdin": "10", "expected": "2 3 5 7"},
            {"stdin": "2", "expected": "2"},
            {"stdin": "20", "expected": "2 3 5 7 11 13 17 19"},
        ],
        "tags": ["数学", "筛法"],
    },
]


def _problem_for_date(day):
    """按日期确定性选一道内置题（同一天全员一致）。"""
    idx = day.toordinal() % len(_FALLBACK_PROBLEMS)
    return _FALLBACK_PROBLEMS[idx]


def _ensure_daily(day):
    """确保某天有题：优先查库，没有就按日期从内置题库生成并落库。"""
    ch = CodeDailyChallenge.objects.filter(date=day).first()
    if ch:
        return ch
    tpl = _problem_for_date(day)
    return CodeDailyChallenge.objects.create(
        date=day,
        title=tpl["title"],
        description=tpl["description"],
        language=tpl["language"],
        difficulty=tpl["difficulty"],
        template=tpl["template"],
        testcases=tpl["testcases"],
        tags=tpl["tags"],
    )


def _daily_brief(ch, record=None):
    return {
        "id": ch.id, "date": ch.date, "title": ch.title,
        "description": ch.description, "language": ch.language,
        "difficulty": ch.difficulty, "template": ch.template,
        "tags": ch.tags, "case_count": len(ch.testcases or []),
        "solved": bool(record and record.passed),
        "passed_count": record.passed_count if record else 0,
        "total_count": record.total_count if record else 0,
    }


@endpoint(("GET",))
def daily_today(request):
    """今日题目 + 我的完成状态。"""
    day = timezone.localdate()
    ch = _ensure_daily(day)
    rec = CodeDailyRecord.objects.filter(user=request.user, challenge=ch).first()
    # 附带连续打卡天数
    streak = _daily_streak(request.user)
    return ok({"challenge": _daily_brief(ch, rec), "streak": streak})


@endpoint(("POST",))
def daily_submit(request):
    """提交今日题目代码 → 判题 → 落记录 → 若未通过自动进错题本。"""
    day = timezone.localdate()
    ch = _ensure_daily(day)
    code = req_str(request, "code", "")
    if not code.strip():
        raise ValueError("代码不能为空")

    cases = ch.testcases or []
    if not cases:
        raise ValueError("该题目暂无测试用例，无法判题")

    verdict, passed, results, total_ms = run_judge(
        ch.language, code, cases, timeout=5, ignore_ws=True
    )
    all_pass = verdict == "accepted"

    rec, _ = CodeDailyRecord.objects.update_or_create(
        user=request.user, challenge=ch,
        defaults={
            "code": code[:20000],
            "passed": all_pass,
            "passed_count": passed,
            "total_count": len(results),
            "duration_ms": total_ms,
        },
    )

    # 未通过 → 自动进错题本（按来源+来源ID 去重）
    wrong_id = None
    if not all_pass:
        failed = [r for r in results if r.get("verdict") != "accepted"][:5]
        wb, created = CodeWrongBook.objects.get_or_create(
            user=request.user, source="daily", source_id=ch.id,
            defaults={
                "title": f"[每日一题] {ch.title}",
                "language": ch.language,
                "source_code": code[:20000],
                "reason": _verdict_text(verdict),
                "failed_cases": failed,
            },
        )
        if not created:
            wb.source_code = code[:20000]
            wb.reason = _verdict_text(verdict)
            wb.failed_cases = failed
            wb.mastered = False
            wb.save()
        wrong_id = wb.id

    # 提交后结算成就
    unlocked = check_achievements(request.user)

    return ok({
        "verdict": verdict, "accepted": all_pass,
        "passed": passed, "total": len(results),
        "results": results, "duration_ms": total_ms,
        "record_id": rec.id, "streak": _daily_streak(request.user),
        "wrong_book_id": wrong_id,
        "unlocked": unlocked,
    })


@endpoint(("GET",))
def daily_history(request):
    """我的每日一题历史 + 通过率。"""
    limit = opt_num(request, "limit", 30, integer=True, minimum=1, maximum=200)
    recs = CodeDailyRecord.objects.filter(user=request.user).select_related("challenge")[:limit]
    items = [{
        "id": r.id, "date": r.challenge.date, "title": r.challenge.title,
        "language": r.challenge.language, "difficulty": r.challenge.difficulty,
        "passed": r.passed, "passed_count": r.passed_count,
        "total_count": r.total_count, "duration_ms": r.duration_ms,
        "updated_at": r.updated_at,
    } for r in recs]

    total = CodeDailyRecord.objects.filter(user=request.user).count()
    solved = CodeDailyRecord.objects.filter(user=request.user, passed=True).count()
    return ok({
        "items": items, "total": total, "solved": solved,
        "rate": round(solved * 100 / total) if total else 0,
        "streak": _daily_streak(request.user),
    })


def _daily_notify_title(day):
    return f"每日一题提醒 · {day}"


@endpoint(("GET", "POST"))
def daily_reminder(request):
    """F680 每日一题站内提醒。

    - GET  → 今日题目 + 是否完成 + 今天是否已发过站内提醒
    - POST → 立即给我发一条站内通知（幂等：同一天只发一次；已完成则不发）

    定时批量提醒由管理命令 `daily_challenge_notify` 负责（到点 notify）。
    """
    from core.models import Notification, notify

    day = timezone.localdate()
    ch = _ensure_daily(day)
    rec = CodeDailyRecord.objects.filter(user=request.user, challenge=ch).first()
    solved = bool(rec and rec.passed)
    title = _daily_notify_title(day)
    notified = Notification.objects.filter(
        recipient=request.user, title=title, created_at__date=day
    ).exists()

    sent = False
    if request.method == "POST":
        if solved:
            return ok({
                "date": str(day), "title": ch.title, "difficulty": ch.difficulty,
                "solved": True, "notified": notified, "sent": False,
                "streak": _daily_streak(request.user),
                "message": "今日一题已完成，暂不需要提醒",
            })
        if not notified:
            notify(
                request.user, title,
                f"今日一题《{ch.title}》（难度：{ch.difficulty}）还没完成，"
                f"打开「代码学习中心」练一练，保持连续打卡。",
                category="system", level="info", link="/code/learn",
            )
            notified = True
            sent = True

    return ok({
        "date": str(day), "title": ch.title, "difficulty": ch.difficulty,
        "solved": solved, "notified": notified, "sent": sent,
        "streak": _daily_streak(request.user),
        "link": "/code/learn",
    })


def _daily_streak(user):
    """连续打卡天数：从今天（或昨天）往前数连续有提交记录的天数。"""
    days = set(
        CodeDailyRecord.objects.filter(user=user)
        .values_list("challenge__date", flat=True)
    )
    if not days:
        return 0
    today = timezone.localdate()
    # 今天没做但从昨天开始也算连续（还没到做今天题的时候）
    cursor = today if today in days else today - datetime.timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak


def _verdict_text(verdict):
    return {
        "wrong_answer": "答案错误",
        "time_limit": "超时",
        "runtime_error": "运行时错误",
        "compile_error": "编译错误",
        "unavailable": "运行时不可用",
        "accepted": "通过",
    }.get(verdict, verdict or "未通过")


# ============================================================
# 二、成就徽章（第 92 条）
# ============================================================

# 内置徽章定义（首次访问时种子化）
_BUILTIN_ACHIEVEMENTS = [
    {"key": "first_run", "name": "初见代码", "icon": "🌱", "tier": "bronze",
     "description": "完成第一次代码运行", "rule": {"metric": "run_count", "value": 1}, "order": 1},
    {"key": "run_100", "name": "跑题百遍", "icon": "🔥", "tier": "silver",
     "description": "累计执行代码 100 次", "rule": {"metric": "run_count", "value": 100}, "order": 2},
    {"key": "run_500", "name": "键盘磨损者", "icon": "⚡", "tier": "gold",
     "description": "累计执行代码 500 次", "rule": {"metric": "run_count", "value": 500}, "order": 3},
    {"key": "file_10", "name": "多产写手", "icon": "📝", "tier": "bronze",
     "description": "创建 10 个代码文件", "rule": {"metric": "file_count", "value": 10}, "order": 4},
    {"key": "file_50", "name": "工程癖", "icon": "📦", "tier": "silver",
     "description": "创建 50 个代码文件", "rule": {"metric": "file_count", "value": 50}, "order": 5},
    {"key": "judge_first", "name": "首战告捷", "icon": "✅", "tier": "bronze",
     "description": "首次判题全部通过", "rule": {"metric": "judge_accepted", "value": 1}, "order": 6},
    {"key": "judge_30", "name": "刷题达人", "icon": "🎯", "tier": "gold",
     "description": "累计通过 30 次判题", "rule": {"metric": "judge_accepted", "value": 30}, "order": 7},
    {"key": "daily_first", "name": "今日启程", "icon": "📅", "tier": "bronze",
     "description": "完成第一道每日一题", "rule": {"metric": "daily_solved", "value": 1}, "order": 8},
    {"key": "streak_7", "name": "一周不断", "icon": "🎖", "tier": "silver",
     "description": "连续打卡 7 天", "rule": {"metric": "daily_streak", "value": 7}, "order": 9},
    {"key": "streak_30", "name": "月度铁人", "icon": "👑", "tier": "gold",
     "description": "连续打卡 30 天", "rule": {"metric": "daily_streak", "value": 30}, "order": 10},
    {"key": "snippet_5", "name": "收藏家", "icon": "💎", "tier": "bronze",
     "description": "沉淀 5 个代码片段", "rule": {"metric": "snippet_count", "value": 5}, "order": 11},
    {"key": "workspace_5", "name": "多线程人生", "icon": "🗂", "tier": "bronze",
     "description": "创建 5 个代码工作区", "rule": {"metric": "workspace_count", "value": 5}, "order": 12},
    {"key": "polyglot", "name": "多语言者", "icon": "🌍", "tier": "silver",
     "description": "在 3 种以上语言中执行过代码", "rule": {"metric": "language_count", "value": 3}, "order": 13},
    {"key": "deployer", "name": "分享精神", "icon": "🔗", "tier": "bronze",
     "description": "创建第一条分享链接", "rule": {"metric": "share_count", "value": 1}, "order": 14},
]


def ensure_achievements():
    """种子化内置徽章（幂等）。"""
    existing = set(CodeAchievement.objects.values_list("key", flat=True))
    to_create = [
        CodeAchievement(**a) for a in _BUILTIN_ACHIEVEMENTS if a["key"] not in existing
    ]
    if to_create:
        CodeAchievement.objects.bulk_create(to_create, ignore_conflicts=True)


def _user_metrics(user):
    """统计用户各项指标，供成就结算与个人中心展示。"""
    from .models import CodeSnippet, CodeShare

    run_count = CodeRun.objects.filter(owner=user).count()
    file_count = CodeFile.objects.filter(owner=user).count()
    judge_accepted = CodeJudgeTask.objects.filter(owner=user, verdict="accepted").count()
    daily_solved = CodeDailyRecord.objects.filter(user=user, passed=True).count()
    snippet_count = CodeSnippet.objects.filter(owner=user).count()
    workspace_count = CodeWorkspace.objects.filter(owner=user).count()
    share_count = CodeShare.objects.filter(owner=user).count()
    language_count = (
        CodeRun.objects.filter(owner=user)
        .values("language").distinct().count()
    )
    return {
        "run_count": run_count,
        "file_count": file_count,
        "judge_accepted": judge_accepted,
        "daily_solved": daily_solved,
        "daily_streak": _daily_streak(user),
        "snippet_count": snippet_count,
        "workspace_count": workspace_count,
        "share_count": share_count,
        "language_count": language_count,
    }


def check_achievements(user):
    """结算成就：把已达标的徽章写入/更新 CodeUserAchievement。

    返回本次**新解锁**的徽章列表。惰性调用，不依赖定时任务。
    """
    ensure_achievements()
    metrics = _user_metrics(user)
    unlocked_now = []

    existing = {
        ua.achievement_id: ua
        for ua in CodeUserAchievement.objects.filter(user=user)
    }

    for ach in CodeAchievement.objects.all():
        rule = ach.rule or {}
        metric = rule.get("metric")
        target = int(rule.get("value") or 0)
        if not metric or target <= 0:
            continue
        current = int(metrics.get(metric, 0))
        ua = existing.get(ach.id)

        if current >= target:
            if ua is None:
                ua = CodeUserAchievement.objects.create(
                    user=user, achievement=ach,
                    progress=current, target=target,
                    unlocked_at=timezone.now(),
                )
                unlocked_now.append({
                    "key": ach.key, "name": ach.name,
                    "icon": ach.icon, "tier": ach.tier,
                    "description": ach.description,
                })
            elif ua.unlocked_at is None:
                ua.unlocked_at = timezone.now()
                ua.progress = current
                ua.save(update_fields=["unlocked_at", "progress"])
                unlocked_now.append({
                    "key": ach.key, "name": ach.name,
                    "icon": ach.icon, "tier": ach.tier,
                    "description": ach.description,
                })
        else:
            # 未达标也记录进度，前端可展示进度条
            if ua is None:
                CodeUserAchievement.objects.create(
                    user=user, achievement=ach, progress=current, target=target
                )
            elif ua.progress != current or ua.target != target:
                ua.progress = current
                ua.target = target
                ua.save(update_fields=["progress", "target"])

    return unlocked_now


@endpoint(("GET",))
def achievement_list(request):
    """全部徽章 + 我的进度/解锁状态。"""
    ensure_achievements()
    metrics = _user_metrics(request.user)

    ua_map = {
        ua.achievement_id: ua
        for ua in CodeUserAchievement.objects.filter(user=request.user)
    }
    items = []
    for ach in CodeAchievement.objects.all():
        ua = ua_map.get(ach.id)
        rule = ach.rule or {}
        target = int(rule.get("value") or 1)
        progress = ua.progress if ua else int(metrics.get(rule.get("metric"), 0))
        items.append({
            "id": ach.id, "key": ach.key, "name": ach.name,
            "description": ach.description, "icon": ach.icon,
            "tier": ach.tier, "metric": rule.get("metric"),
            "target": target, "progress": min(progress, target),
            "unlocked": bool(ua and ua.unlocked_at),
            "unlocked_at": ua.unlocked_at if ua else None,
            "percent": min(100, round(progress * 100 / target)) if target else 0,
        })

    unlocked = [i for i in items if i["unlocked"]]
    return ok({
        "items": items,
        "unlocked_count": len(unlocked),
        "total_count": len(items),
        "metrics": metrics,
    })


@endpoint(("GET",))
def achievement_mine(request):
    """我的已解锁徽章（含新解锁结算）。"""
    unlocked_now = check_achievements(request.user)
    qs = (
        CodeUserAchievement.objects
        .filter(user=request.user, unlocked_at__isnull=False)
        .select_related("achievement")
    )
    items = [{
        "key": ua.achievement.key, "name": ua.achievement.name,
        "icon": ua.achievement.icon, "tier": ua.achievement.tier,
        "description": ua.achievement.description,
        "unlocked_at": ua.unlocked_at,
    } for ua in qs]
    total = CodeAchievement.objects.count()
    return ok({
        "items": items, "count": len(items), "total": total,
        "newly_unlocked": unlocked_now,
        "metrics": _user_metrics(request.user),
    })


# ============================================================
# 三、错题本（第 94 条）
# ============================================================


def _wrong_brief(w):
    return {
        "id": w.id, "title": w.title, "language": w.language,
        "source": w.source, "reason": w.reason,
        "mastered": w.mastered, "review_count": w.review_count,
        "failed_cases": w.failed_cases,
        "created_at": w.created_at, "updated_at": w.updated_at,
        "last_reviewed_at": w.last_reviewed_at,
    }


@endpoint(("GET",))
def wrong_list(request):
    """错题列表，支持按掌握状态/语言筛选。"""
    qs = CodeWrongBook.objects.filter(user=request.user)
    only = opt_str(request, "filter", "")
    if only == "unmastered":
        qs = qs.filter(mastered=False)
    elif only == "mastered":
        qs = qs.filter(mastered=True)
    lang = opt_str(request, "language", "")
    if lang:
        qs = qs.filter(language=lang)
    limit = opt_num(request, "limit", 50, integer=True, minimum=1, maximum=500)
    items = [_wrong_brief(w) for w in qs[:limit]]
    return ok({
        "items": items,
        "total": CodeWrongBook.objects.filter(user=request.user).count(),
        "unmastered": CodeWrongBook.objects.filter(user=request.user, mastered=False).count(),
        "mastered": CodeWrongBook.objects.filter(user=request.user, mastered=True).count(),
    })


@endpoint(("POST",))
def wrong_add(request):
    """手动加入错题本。"""
    title = req_str(request, "title", "")
    if not title.strip():
        raise ValueError("title 不能为空")
    w = CodeWrongBook.objects.create(
        user=request.user,
        title=title[:200],
        language=rt.normalize_language(opt_str(request, "language", "python")),
        source_code=opt_str(request, "code", "")[:20000],
        source=opt_str(request, "source", "manual")[:16],
        source_id=opt_num(request, "source_id", None, integer=True),
        reason=opt_str(request, "reason", "")[:200],
    )
    return ok({"id": w.id})


@endpoint(("POST",))
def wrong_review(request, pk):
    """复习一次：计数 +1，可同时标记已掌握。"""
    w = CodeWrongBook.objects.filter(user=request.user, id=pk).first()
    if not w:
        raise ValueError(f"错题不存在: {pk}")
    w.review_count += 1
    w.last_reviewed_at = timezone.now()
    if opt_bool(request, "mastered", False):
        w.mastered = True
    elif opt_bool(request, "unmaster", False):
        w.mastered = False
    w.save(update_fields=["review_count", "last_reviewed_at", "mastered", "updated_at"])
    return ok(_wrong_brief(w))


@endpoint(("POST", "DELETE"))
def wrong_delete(request, pk):
    n, _ = CodeWrongBook.objects.filter(user=request.user, id=pk).delete()
    if not n:
        raise ValueError(f"错题不存在: {pk}")
    return ok({"deleted": n})


# ============================================================
# 四、学习路径（第 87/88 条）
# ============================================================

# 本地降级模板：按语言+水平给出阶段化计划
_LOCAL_PATH_TEMPLATES = {
    "python": [
        {"stage": "语言基础", "items": ["变量与数据类型", "运算符与表达式", "条件与循环", "函数定义与参数"], "hours": 8},
        {"stage": "数据结构", "items": ["列表与元组", "字典与集合", "字符串处理", "推导式"], "hours": 8},
        {"stage": "面向对象", "items": ["类与实例", "继承与多态", "魔术方法", "异常处理"], "hours": 10},
        {"stage": "标准库与工程", "items": ["文件与路径", "JSON/CSV 处理", "虚拟环境与依赖", "单元测试"], "hours": 10},
        {"stage": "实战进阶", "items": ["并发与异步", "装饰器与上下文管理器", "常用三方库", "完整项目练习"], "hours": 14},
    ],
    "javascript": [
        {"stage": "语言基础", "items": ["变量与作用域", "函数与箭头函数", "数组与对象", "解构与展开"], "hours": 8},
        {"stage": "异步编程", "items": ["回调与事件循环", "Promise", "async/await", "错误处理"], "hours": 10},
        {"stage": "DOM 与浏览器", "items": ["DOM 操作", "事件模型", "fetch 与请求", "本地存储"], "hours": 10},
        {"stage": "工程化", "items": ["模块系统", "包管理与构建", "调试技巧", "测试入门"], "hours": 12},
    ],
    "java": [
        {"stage": "语言基础", "items": ["基本类型与包装类", "流程控制", "方法与重载", "数组"], "hours": 10},
        {"stage": "面向对象", "items": ["类与对象", "继承与接口", "泛型", "集合框架"], "hours": 14},
        {"stage": "核心进阶", "items": ["异常体系", "IO 流", "多线程与并发", "JVM 基础"], "hours": 16},
        {"stage": "工程实践", "items": ["Maven/Gradle", "单元测试", "常用设计模式", "Spring 入门"], "hours": 16},
    ],
}

# 通用兜底（未收录语言）
_GENERIC_PATH = [
    {"stage": "语法入门", "items": ["基本类型与变量", "运算符", "条件与循环", "函数"], "hours": 8},
    {"stage": "数据结构", "items": ["数组与切片", "映射与集合", "字符串处理", "自定义结构"], "hours": 10},
    {"stage": "进阶特性", "items": ["错误处理", "模块与包", "并发模型", "标准库精讲"], "hours": 12},
    {"stage": "工程实践", "items": ["依赖管理", "测试与调试", "性能剖析", "项目实战"], "hours": 14},
]

_LEVEL_ADJUST = {
    "beginner": 1.0,
    "intermediate": 0.6,
    "advanced": 0.3,
}


def _local_path(language, level, goal):
    """本地降级：按语言选模板，按水平裁剪阶段数量。"""
    stages = _LOCAL_PATH_TEMPLATES.get(language) or _GENERIC_PATH
    factor = _LEVEL_ADJUST.get(level, 1.0)
    keep = max(2, round(len(stages) * factor))
    picked = stages[:keep]
    if goal:
        picked = [dict(s) for s in picked]
        picked[-1]["items"] = list(picked[-1]["items"]) + [f"围绕目标：{goal}"]
    return picked


@endpoint(("GET",))
def path_list(request):
    qs = CodeLearningPath.objects.filter(user=request.user)
    limit = opt_num(request, "limit", 20, integer=True, minimum=1, maximum=100)
    items = [{
        "id": p.id, "title": p.title, "language": p.language,
        "level": p.level, "goal": p.goal,
        "stage_count": len(p.stages or []),
        "total_items": p.total_items, "done_items": p.done_items,
        "percent": p.percent, "is_active": p.is_active,
        "source": p.source, "updated_at": p.updated_at,
    } for p in qs[:limit]]
    return ok({"items": items})


@endpoint(("POST",))
def path_generate(request):
    """生成学习路径：LLM 优先，无 Key 时本地模板降级。"""
    language = rt.normalize_language(opt_str(request, "language", "python"))
    level = opt_str(request, "level", "beginner")
    goal = opt_str(request, "goal", "").strip()[:200]

    source = "local"
    stages = None

    if llm.is_configured():
        prompt = (
            f"请为「{language}」设计一份学习路径，学习者水平：{level}，目标：{goal or '系统掌握'}。\n"
            "严格只输出 JSON 数组，不要任何解释、不要 markdown 代码块。格式：\n"
            '[{"stage": "阶段名", "items": ["知识点1", "知识点2"], "hours": 8}, ...]\n'
            "建议 3-5 个阶段，每阶段 3-5 个知识点，hours 为预估小时数（整数）。"
        )
        raw = llm.chat(
            [{"role": "user", "content": prompt}],
            system="你是编程教学课程设计师，只输出合法 JSON。",
            max_tokens=1200,
        )
        parsed = _parse_stages(raw)
        if parsed:
            stages = parsed
            source = "llm"

    if not stages:
        stages = _local_path(language, level, goal)

    title = opt_str(request, "title", "").strip() or f"{language} 学习路径"
    path = CodeLearningPath.objects.create(
        user=request.user, title=title[:200], language=language,
        level=level, goal=goal, stages=stages, source=source,
    )
    return ok({
        "id": path.id, "title": path.title, "language": path.language,
        "level": path.level, "goal": path.goal, "stages": path.stages,
        "total_items": path.total_items, "source": source,
        "llm_available": llm.is_configured(),
    })


def _parse_stages(raw):
    """从 LLM 输出里抠出 JSON 数组，失败返回 None。"""
    import json as _json
    import re as _re

    if not raw:
        return None
    text = str(raw).strip()
    # 去掉 ```json ... ``` 包裹
    m = _re.search(r"```(?:json)?\s*(.+?)\s*```", text, _re.S)
    if m:
        text = m.group(1)
    # 截取第一个 [ 到最后一个 ]
    s, e = text.find("["), text.rfind("]")
    if s < 0 or e <= s:
        return None
    try:
        arr = _json.loads(text[s:e + 1])
    except Exception:
        return None
    if not isinstance(arr, list):
        return None
    out = []
    for st in arr:
        if not isinstance(st, dict):
            continue
        items = st.get("items")
        if not isinstance(items, list):
            continue
        out.append({
            "stage": str(st.get("stage") or "阶段")[:60],
            "items": [str(i)[:80] for i in items][:10],
            "hours": int(st.get("hours") or 6),
        })
    return out or None


@endpoint(("GET",))
def path_detail(request, pk):
    path = CodeLearningPath.objects.filter(user=request.user, id=pk).first()
    if not path:
        raise ValueError(f"学习路径不存在: {pk}")
    return ok({
        "id": path.id, "title": path.title, "language": path.language,
        "level": path.level, "goal": path.goal, "stages": path.stages,
        "progress": path.progress, "total_items": path.total_items,
        "done_items": path.done_items, "percent": path.percent,
        "is_active": path.is_active, "source": path.source,
        "created_at": path.created_at, "updated_at": path.updated_at,
    })


@endpoint(("POST",))
def path_tick(request, pk):
    """勾选/取消某个学习项。`item` 形如 "0-1"（阶段下标-项下标）。"""
    path = CodeLearningPath.objects.filter(user=request.user, id=pk).first()
    if not path:
        raise ValueError(f"学习路径不存在: {pk}")
    item = req_str(request, "item", "").strip()
    if not _valid_item_key(path, item):
        raise ValueError(f"无效的学习项标识: {item}")

    done = list(path.progress or [])
    if opt_bool(request, "done", True):
        if item not in done:
            done.append(item)
    else:
        done = [d for d in done if d != item]
    path.progress = done
    path.save(update_fields=["progress", "updated_at"])
    return ok({
        "id": path.id, "progress": path.progress,
        "done_items": path.done_items, "percent": path.percent,
    })


def _valid_item_key(path, key):
    try:
        si, ii = key.split("-")
        si, ii = int(si), int(ii)
    except Exception:
        return False
    stages = path.stages or []
    if si < 0 or si >= len(stages):
        return False
    items = stages[si].get("items") or []
    return 0 <= ii < len(items)


@endpoint(("POST", "DELETE"))
def path_delete(request, pk):
    n, _ = CodeLearningPath.objects.filter(user=request.user, id=pk).delete()
    if not n:
        raise ValueError(f"学习路径不存在: {pk}")
    return ok({"deleted": n})


# ============================================================
# 五、代码挑战赛（第 96 条，简化版）
# ============================================================


@endpoint(("GET",))
def arena_board(request):
    """竞技场面板：个人战力统计 + 各榜单摘要。

    不引入实时对战（复杂度高、收益低），做「静态竞技场」：
    聚合已有数据给出可比较的排名。
    """
    me = request.user
    my_runs = CodeRun.objects.filter(owner=me).count()
    my_accepted = CodeJudgeTask.objects.filter(owner=me, verdict="accepted").count()
    my_daily = CodeDailyRecord.objects.filter(user=me, passed=True).count()
    my_streak = _daily_streak(me)

    # 战力评分：简单的加权聚合，便于横向比较
    power = my_runs * 1 + my_accepted * 20 + my_daily * 15 + my_streak * 10

    # 榜单（基于 CodeRun / CodeJudgeTask 聚合，限 10 人）
    top_runners = list(
        CodeRun.objects.values("owner_id", "owner__username")
        .annotate(cnt=Count("id")).order_by("-cnt")[:10]
    )
    top_solvers = list(
        CodeJudgeTask.objects.filter(verdict="accepted")
        .values("owner_id", "owner__username")
        .annotate(cnt=Count("id")).order_by("-cnt")[:10]
    )
    top_daily = list(
        CodeDailyRecord.objects.filter(passed=True)
        .values("user_id", "user__username")
        .annotate(cnt=Count("id")).order_by("-cnt")[:10]
    )

    def _rank(rows, id_key, name_key):
        out = []
        for i, r in enumerate(rows, start=1):
            is_me = r.get(id_key) == me.id
            out.append({
                "rank": i, "username": r.get(name_key) or "匿名",
                "value": r.get("cnt") or 0, "is_me": is_me,
            })
        return out

    return ok({
        "me": {
            "username": me.username,
            "run_count": my_runs, "accepted_count": my_accepted,
            "daily_solved": my_daily, "streak": my_streak,
            "power": power,
        },
        "boards": {
            "runners": _rank(top_runners, "owner_id", "owner__username"),
            "solvers": _rank(top_solvers, "owner_id", "owner__username"),
            "daily": _rank(top_daily, "user_id", "user__username"),
        },
    })


@endpoint(("GET",))
def arena_challenge(request):
    """随机抽一道挑战题（从每日题库里抽，供临时练习）。"""
    difficulty = opt_str(request, "difficulty", "")
    pool = _FALLBACK_PROBLEMS
    if difficulty:
        pool = [q for q in pool if q["difficulty"] == difficulty] or _FALLBACK_PROBLEMS
    q = random.choice(pool)
    return ok({
        "title": q["title"], "description": q["description"],
        "language": q["language"], "difficulty": q["difficulty"],
        "template": q["template"], "tags": q["tags"],
        "case_count": len(q["testcases"]),
    })


@endpoint(("POST",))
def arena_submit(request):
    """挑战赛提交：直接对内置题判题（不落 CodeJudgeTask 以外的额外表）。

    与 daily_submit 的区别：题目由客户端指定 title，允许重复挑同一题。
    """
    title = opt_str(request, "title", "").strip()
    if not title:
        raise ValueError("title 不能为空")
    q = next((x for x in _FALLBACK_PROBLEMS if x["title"] == title), None)
    if not q:
        raise ValueError(f"未找到挑战题: {title}")

    code = req_str(request, "code", "")
    if not code.strip():
        raise ValueError("代码不能为空")

    verdict, passed, results, total_ms = run_judge(
        q["language"], code, q["testcases"], timeout=5, ignore_ws=True
    )
    all_pass = verdict == "accepted"

    from .models import CodeJudgeTask
    task = CodeJudgeTask.objects.create(
        owner=request.user, title=f"[挑战] {title}"[:200],
        language=q["language"], source_code=code[:20000],
        testcases=q["testcases"], results=results,
        verdict=verdict, passed=passed, total=len(results),
        duration_ms=total_ms,
    )

    unlocked = check_achievements(request.user)

    wrong_id = None
    if not all_pass:
        wb, _c = CodeWrongBook.objects.get_or_create(
            user=request.user, source="arena", source_id=task.id,
            defaults={
                "title": f"[挑战] {title}", "language": q["language"],
                "source_code": code[:20000],
                "reason": _verdict_text(verdict),
                "failed_cases": [r for r in results if r.get("verdict") != "accepted"][:5],
            },
        )
        wrong_id = wb.id

    return ok({
        "task_id": task.id, "verdict": verdict, "accepted": all_pass,
        "passed": passed, "total": len(results), "results": results,
        "duration_ms": total_ms, "unlocked": unlocked, "wrong_book_id": wrong_id,
    })


# ============================================================
# 六、学习总览（第 89 条：个人学习看板）
# ============================================================


@endpoint(("GET",))
def learn_overview(request):
    """个人学习总览：聚合每日一题 / 判题 / 成就 / 错题 / 路径进度。"""
    metrics = _user_metrics(request.user)
    ensure_achievements()
    check_achievements(request.user)

    unlocked = CodeUserAchievement.objects.filter(
        user=request.user, unlocked_at__isnull=False
    ).count()
    total_ach = CodeAchievement.objects.count()

    wrong_unmastered = CodeWrongBook.objects.filter(
        user=request.user, mastered=False
    ).count()

    active_path = CodeLearningPath.objects.filter(
        user=request.user, is_active=True
    ).order_by("-updated_at").first()

    # 近 7 天每日一题完成情况
    today = timezone.localdate()
    week = []
    for i in range(6, -1, -1):
        d = today - datetime.timedelta(days=i)
        rec = CodeDailyRecord.objects.filter(
            user=request.user, challenge__date=d
        ).first()
        week.append({
            "date": d,
            "done": bool(rec),
            "passed": bool(rec and rec.passed),
        })

    return ok({
        "metrics": metrics,
        "achievements": {"unlocked": unlocked, "total": total_ach},
        "wrong": {"unmastered": wrong_unmastered},
        "active_path": {
            "id": active_path.id, "title": active_path.title,
            "percent": active_path.percent,
            "done_items": active_path.done_items,
            "total_items": active_path.total_items,
        } if active_path else None,
        "daily_streak": _daily_streak(request.user),
        "week": week,
    })
