# -*- coding: utf-8 -*-
"""第三轮升级 373–390：学习模块增强（错题批量导入导出 / 相似题 / 错因聚类 /
学习偏好与提醒 / 考试倒计时 / 学习小组 / 学习榜 / 题单分享 / 题库统计 /
计划排程 / 掌握度热力图 / 公式计算历史 / 生词本互通 / 错题转笔记待办 /
时长与工具报表 / 目标预测）。

约定：
- 只走 DRF APIView/Response，写库前先做 owner 可见性校验；
- 导出类接口返回附件流（CSV 带 UTF-8 BOM，Anki 用 #separator:tab 模板）；
- 所有查询带 limit / 数据库聚合，不在 Python 里遍历全表；
- 只读公开接口（题单分享）显式 permission_classes = [] 且不做任何写操作。
"""
import csv
import html
import io
import json
import math
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import Lower, TruncDate, TruncWeek
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Notification
from core.notify import dispatch
from core.search import tokenize
from core.validators import as_date, as_int, parse_bool, sanitize_filename
from learning.data import curriculum as cu
from learning.data import questions as qb
from learning.models import (
    DailyGoal, ExamCountdown, FormulaCalcLog, LearningPref, MistakeRecord, QuestionSet,
    StudyGroup, StudyGroupMember, StudyPlan, StudySession, ToolUsageLog, WordbookItem,
)

User = get_user_model()

# 单次导入/导出的行数上限（防止超大请求把内存与事务拖垮）
MAX_IMPORT_ROWS = 500
MAX_WORDS_IMPORT_ROWS = 1000
MAX_EXPORT_ROWS = 2000
MAX_WORDS_EXPORT_ROWS = 5000
MAX_ERRORS = 20


# ---------------------------------------------------------------------------
# 公共小工具
# ---------------------------------------------------------------------------

def _subject_cn():
    """学科 key → 中文名（口径与学科中心一致）。"""
    m = {}
    for st in getattr(cu, "STAGES", []):
        for sub in st.get("subjects", []):
            if sub.get("key"):
                m.setdefault(sub["key"], sub.get("name") or sub["key"])
    return m


def _type_cn():
    return dict(MistakeRecord.TYPES)


def _cause_cn():
    return dict(MistakeRecord.CAUSES)


def _csv_response(filename, header, rows):
    """附件流 CSV：text/csv + UTF-8 BOM（Excel 打开不乱码）。"""
    resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = content_disposition_header(
        True, sanitize_filename(filename, fallback="export.csv", max_length=80))
    resp.write("\ufeff")
    writer = csv.writer(resp)
    writer.writerow(header)
    writer.writerows(rows)
    return resp


def _text_response(filename, text, content_type="text/plain; charset=utf-8"):
    resp = HttpResponse(text, content_type=content_type)
    resp["Content-Disposition"] = content_disposition_header(
        True, sanitize_filename(filename, fallback="export.txt", max_length=80))
    return resp


def _norm_key(text):
    return str(text or "").strip().lower().replace(" ", "").replace("_", "")


def _build_row_getter(fields):
    """字段别名表：规范字段 → 可接受的行内列名（中英文）。"""
    aliases = {key: {_norm_key(a) for a in names} for key, names in fields.items()}

    def pick(row, key, default=""):
        normalized = {_norm_key(k): v for k, v in row.items()}
        for alias in aliases[key]:
            if alias in normalized and normalized[alias] not in (None, ""):
                return str(normalized[alias]).strip()
        return default

    return pick


def _load_rows(payload, fmt):
    """把请求体解析成 list[dict]；返回 (rows, error_message)。"""
    items = payload.get("items")
    text = payload.get("text")
    if fmt == "json":
        if isinstance(items, list):
            return items, ""
        if not text:
            return None, "json 格式需要 text（JSON 文本）或 items 数组"
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            return None, f"JSON 解析失败：{exc}"
        if isinstance(data, dict):
            data = data.get("items", data.get("list", []))
        if not isinstance(data, list):
            return None, "JSON 顶层需为数组，或 {items: [...]}"
        return data, ""
    if not text:
        return None, "csv 格式需要 text（CSV 文本）"
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        return None, "CSV 缺少表头"
    return [dict(r) for r in reader], ""


def _err(rows):
    """错误明细最多 20 条，剩余只报数量。"""
    return rows[:MAX_ERRORS]


# ---------------------------------------------------------------------------
# 373 错题批量导入
# ---------------------------------------------------------------------------
_MISTAKE_FIELDS = {
    "stage": ("stage", "学段"),
    "subject": ("subject", "学科"),
    "question_type": ("question_type", "type", "题型"),
    "difficulty": ("difficulty", "难度"),
    "stem": ("stem", "题干", "题目", "题目内容"),
    "answer": ("answer", "正确答案", "答案"),
    "user_answer": ("user_answer", "我的答案", "作答"),
    "analysis": ("analysis", "解析"),
    "cause": ("cause", "错因"),
}
_MISTAKE_PICK = _build_row_getter(_MISTAKE_FIELDS)
_QTYPE_INPUT = {
    "single": "single", "单选": "single", "单项选择": "single", "选择题": "single",
    "judge": "judge", "判断": "judge", "判断题": "judge",
    "fill": "fill", "填空": "fill", "填空题": "fill",
    "output": "output", "读程序": "output", "程序题": "output",
    "other": "other", "其它": "other", "其他": "other", "解答": "other",
}
_CAUSE_INPUT = {label: key for key, label in MistakeRecord.CAUSES}
_CAUSE_INPUT.update({key: key for key, _ in MistakeRecord.CAUSES})


def _clean_mistake_row(row):
    """校验并清洗一行；返回 (dict, error)。"""
    if not isinstance(row, dict):
        return None, "行数据必须是对象"
    stem = _MISTAKE_PICK(row, "stem")
    if not stem:
        return None, "缺少题干"
    if len(stem) > 2000:
        return None, "题干过长（上限 2000 字）"
    raw_type = _MISTAKE_PICK(row, "question_type") or "single"
    qtype = _QTYPE_INPUT.get(raw_type.lower()) or _QTYPE_INPUT.get(raw_type)
    if not qtype:
        return None, f"题型不合法：{raw_type}"
    raw_diff = _MISTAKE_PICK(row, "difficulty") or "1"
    try:
        difficulty = int(float(raw_diff))
    except (TypeError, ValueError):
        return None, f"难度不合法：{raw_diff}"
    if not 1 <= difficulty <= 5:
        return None, "难度需在 1–5 之间"
    raw_cause = _MISTAKE_PICK(row, "cause")
    cause = ""
    if raw_cause:
        cause = _CAUSE_INPUT.get(raw_cause) or _CAUSE_INPUT.get(raw_cause.lower())
        if not cause:
            return None, f"错因不合法：{raw_cause}"
    return {
        "stage": _MISTAKE_PICK(row, "stage")[:20],
        "subject": _MISTAKE_PICK(row, "subject")[:20],
        "question_type": qtype,
        "difficulty": difficulty,
        "stem": stem,
        "answer": _MISTAKE_PICK(row, "answer")[:255],
        "user_answer": _MISTAKE_PICK(row, "user_answer")[:255],
        "analysis": _MISTAKE_PICK(row, "analysis")[:5000],
        "cause": cause,
    }, ""


class MistakeImportView(APIView):
    """373 POST school/mistakes/import/ {format: csv|json, text} → created/skipped/errors。"""

    def post(self, request):
        fmt = str(request.data.get("format") or "csv").strip().lower()
        if fmt not in ("csv", "json"):
            return Response({"ok": False, "error": "format 只支持 csv / json"}, status=400)
        rows, error = _load_rows(request.data, fmt)
        if error:
            return Response({"ok": False, "error": error}, status=400)
        if not rows:
            return Response({"ok": False, "error": "没有可导入的数据"}, status=400)
        if len(rows) > MAX_IMPORT_ROWS:
            return Response({"ok": False, "error": f"单次最多导入 {MAX_IMPORT_ROWS} 行"}, status=400)

        cleaned, errors = [], []
        for idx, row in enumerate(rows, start=1):
            item, msg = _clean_mistake_row(row)
            if msg:
                errors.append({"row": idx, "error": msg})
            else:
                cleaned.append(item)

        # 去重：本次内部 + 与该用户已有错题（一次 IN 查询，限 500 个题干）
        stems = [x["stem"] for x in cleaned]
        existing = set(
            MistakeRecord.objects.filter(owner=request.user, stem__in=stems)
            .values_list("stem", flat=True)
        )
        seen, objs, skipped = set(), [], 0
        for item in cleaned:
            if item["stem"] in existing or item["stem"] in seen:
                skipped += 1
                continue
            seen.add(item["stem"])
            objs.append(MistakeRecord(owner=request.user, **item))
        if objs:
            MistakeRecord.objects.bulk_create(objs, batch_size=200)

        result = {
            "ok": True,
            "format": fmt,
            "total": len(rows),
            "created": len(objs),
            "skipped": skipped + len(errors),
            "invalid": len(errors),
            "duplicated": skipped,
            "errors": _err(errors),
            "errors_truncated": len(errors) > MAX_ERRORS,
        }
        return Response(result, status=201)


# ---------------------------------------------------------------------------
# 374 错题导出（csv / anki）
# ---------------------------------------------------------------------------

def _anki_cell(value):
    return html.escape(str(value or "")).replace("\t", " ").replace("\r", "").replace("\n", "<br>")


class MistakeExportView(APIView):
    """374 GET school/mistakes/export/?fmt=csv|anki → 附件流。"""

    def get(self, request):
        fmt = str(request.query_params.get("fmt") or "csv").strip().lower()
        if fmt not in ("csv", "anki"):
            return Response({"ok": False, "error": "fmt 只支持 csv / anki"}, status=400)
        qs = MistakeRecord.objects.filter(owner=request.user)
        subject = request.query_params.get("subject")
        if subject:
            qs = qs.filter(subject=subject)
        if request.query_params.get("mastered") in ("0", "1"):
            qs = qs.filter(mastered=request.query_params["mastered"] == "1")
        rows = list(qs.order_by("-created_at")[:MAX_EXPORT_ROWS])
        stamp = timezone.localdate().strftime("%Y%m%d")
        types, causes = _type_cn(), _cause_cn()
        subjects = _subject_cn()

        if fmt == "csv":
            header = ["学科", "题型", "难度", "题干", "正确答案", "我的答案", "解析", "错因", "已订正", "录入时间"]
            data = [[
                r.subject, types.get(r.question_type, r.question_type), r.difficulty,
                r.stem, r.answer, r.user_answer, r.analysis, causes.get(r.cause, r.cause),
                "是" if r.mastered else "否",
                timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
            ] for r in rows]
            return _csv_response(f"mistakes_{stamp}.csv", header, data)

        # Anki：制表符分隔模板（html:true 让换行以 <br> 呈现）
        lines = [
            "#separator:tab",
            "#html:true",
            "#columns:题干\t正确答案\t解析\t学科\t题型",
        ]
        for r in rows:
            lines.append("\t".join([
                _anki_cell(r.stem), _anki_cell(r.answer),
                _anki_cell(r.analysis or r.user_answer),
                _anki_cell(subjects.get(r.subject, r.subject or "未分类")),
                _anki_cell(types.get(r.question_type, r.question_type)),
            ]))
        return _text_response(f"mistakes_{stamp}.txt", "\n".join(lines) + "\n")


def subject_name(subject):
    return _subject_cn().get(subject, subject or "未分类")


# ---------------------------------------------------------------------------
# 375 相似错题（tokenize + TF 余弦）
# ---------------------------------------------------------------------------

def _tf(tokens):
    return Counter(tokens)


def _cosine(a, b):
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    num = sum(a[t] * b[t] for t in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


class MistakeSimilarView(APIView):
    """375 GET school/mistakes/similar/?id=&limit=10 → 同科相似错题（TF 重叠度排序）。"""

    MAX_POOL = 300

    def get(self, request):
        pk = as_int(request.query_params.get("id"), default=None, field="id")
        if pk is None:
            return Response({"ok": False, "error": "缺少 id"}, status=400)
        limit = as_int(request.query_params.get("limit"), default=10, field="limit", minimum=1, maximum=30)
        target = get_object_or_404(MistakeRecord, id=pk, owner=request.user)
        pool_qs = MistakeRecord.objects.filter(owner=request.user).exclude(id=target.id)
        if target.subject:
            pool_qs = pool_qs.filter(subject=target.subject)
        pool = list(pool_qs.order_by("-created_at")[:self.MAX_POOL])
        target_tf = _tf(tokenize(target.stem))
        scored = []
        for m in pool:
            tf = _tf(tokenize(m.stem))
            score = _cosine(target_tf, tf)
            if score <= 0:
                continue
            scored.append((score, m, sorted(set(target_tf) & set(tf))[:5]))
        scored.sort(key=lambda t: -t[0])
        types, causes = _type_cn(), _cause_cn()
        return Response({
            "id": target.id,
            "subject": target.subject,
            "subject_name": subject_name(target.subject),
            "total": len(scored),
            "list": [{
                "id": m.id, "stem": m.stem, "subject": m.subject,
                "question_type": m.question_type,
                "type_name": types.get(m.question_type, m.question_type),
                "cause": m.cause, "cause_name": causes.get(m.cause, m.cause),
                "mastered": m.mastered,
                "score": round(score, 4),
                "matched_terms": terms,
            } for score, m, terms in scored[:limit]],
        })


# ---------------------------------------------------------------------------
# 376 错因聚类（subject × cause）
# ---------------------------------------------------------------------------
class MistakeClustersView(APIView):
    """376 GET school/mistakes/clusters/ → 按学科与错因聚合计数与订正率。"""

    def get(self, request):
        rows = list(
            MistakeRecord.objects.filter(owner=request.user)
            .values("subject", "cause")
            .annotate(total=Count("id"), mastered=Count("id", filter=Q(mastered=True)))
            .order_by("-total")[:200]
        )
        types_subject = _subject_cn()
        causes = _cause_cn()
        clusters = []
        for r in rows:
            total, mastered = r["total"], r["mastered"]
            rate = round(mastered / total * 100, 1) if total else 0.0
            clusters.append({
                "subject": r["subject"] or "unclassified",
                "subject_name": types_subject.get(r["subject"], r["subject"] or "未分类"),
                "cause": r["cause"] or "unset",
                "cause_name": causes.get(r["cause"], "未归类"),
                "total": total,
                "mastered": mastered,
                "rate": rate,
                # 薄弱度：题量 × 未订正比例，越大越该先补
                "weakness": round(total * (100 - rate) / 100, 2),
            })
        clusters.sort(key=lambda x: (-x["weakness"], -x["total"]))
        return Response({
            "total": sum(c["total"] for c in clusters),
            "cluster_count": len(clusters),
            "top": clusters[:5],
            "clusters": clusters,
        })


# ---------------------------------------------------------------------------
# 377 学习偏好 + 每日提醒检查
# ---------------------------------------------------------------------------
def _pref_payload(pref):
    return {
        "daily_remind": pref.daily_remind,
        "leaderboard_public": pref.leaderboard_public,
        "updated_at": pref.updated_at.isoformat(timespec="seconds"),
    }


class StudyPrefView(APIView):
    """377 GET/POST study/pref/ → 每日提醒与学习榜公开开关。"""

    def get(self, request):
        pref, _ = LearningPref.objects.get_or_create(owner=request.user)
        return Response(_pref_payload(pref))

    def post(self, request):
        pref, _ = LearningPref.objects.get_or_create(owner=request.user)
        if "daily_remind" in request.data:
            pref.daily_remind = parse_bool(request.data.get("daily_remind"), default=pref.daily_remind,
                                          field="daily_remind")
        if "leaderboard_public" in request.data:
            pref.leaderboard_public = parse_bool(request.data.get("leaderboard_public"),
                                                 default=pref.leaderboard_public, field="leaderboard_public")
        pref.save(update_fields=["daily_remind", "leaderboard_public", "updated_at"])
        return Response(_pref_payload(pref))


class StudyRemindCheckView(APIView):
    """377 POST study/remind/check/ → 每日目标未达成时提醒一次（当日 Notification 去重）。"""

    LINK = "/learning/study"

    def post(self, request):
        today = timezone.localdate()
        pref, _ = LearningPref.objects.get_or_create(owner=request.user)
        goal, _ = DailyGoal.objects.get_or_create(owner=request.user)
        target = goal.target_minutes or 0
        minutes = StudySession.objects.filter(
            owner=request.user, study_date=today).aggregate(m=Sum("minutes"))["m"] or 0
        payload = {"minutes": minutes, "target_minutes": target, "daily_remind": pref.daily_remind}

        if not pref.daily_remind:
            return Response({**payload, "sent": False, "reason": "已关闭每日提醒"})
        if target <= 0:
            return Response({**payload, "sent": False, "reason": "未设置每日目标"})
        if minutes >= target:
            return Response({**payload, "sent": False, "reason": "今日目标已达成", "achieved": True})
        already = Notification.objects.filter(
            recipient=request.user, link=self.LINK,
            title__startswith="今日还差", created_at__date=today,
        ).exists()
        if already:
            return Response({**payload, "sent": False, "already": True, "reason": "今日已提醒过"})

        gap = target - minutes
        notif = dispatch(
            request.user, f"今日还差 {gap} 分钟达标",
            f"今日已专注 {minutes} 分钟，目标 {target} 分钟。去「我的学习 → 专注记录」再记一段就达标了。",
            category="system", level="info", link=self.LINK,
        )
        return Response({
            **payload, "gap": gap, "sent": bool(notif),
            "reason": "" if notif else "通知分类已关闭或未投递",
        })


# ---------------------------------------------------------------------------
# 378 考试倒计时
# ---------------------------------------------------------------------------
def _exam_payload(obj, today):
    days_left = (obj.exam_date - today).days
    daily = math.ceil(obj.target_count / max(days_left, 1)) if obj.target_count else 0
    return {
        "id": obj.id, "title": obj.title, "subject": obj.subject,
        "exam_date": obj.exam_date.isoformat(),
        "days_left": days_left,
        "passed": days_left < 0,
        "urgent": 0 <= days_left <= 7,
        "target_count": obj.target_count,
        "daily_questions": daily,
        "note": obj.note,
    }


class ExamCountdownView(APIView):
    """378 GET/POST/DELETE study/exam/ → 考试倒计时与按剩余天数摊分的每日题量。"""

    def get(self, request):
        today = timezone.localdate()
        eid = request.query_params.get("id")
        if eid:
            obj = get_object_or_404(ExamCountdown, id=as_int(eid, field="id"), owner=request.user)
            return Response(_exam_payload(obj, today))
        qs = ExamCountdown.objects.filter(owner=request.user).order_by("exam_date")[:50]
        rows = [_exam_payload(o, today) for o in qs]
        upcoming = [r for r in rows if not r["passed"]]
        return Response({
            "total": len(rows),
            "nearest": upcoming[0] if upcoming else None,
            "list": rows,
        })

    def post(self, request):
        today = timezone.localdate()
        eid = request.data.get("id")
        if eid:
            obj = get_object_or_404(ExamCountdown, id=as_int(eid, field="id"), owner=request.user)
        else:
            obj = ExamCountdown(owner=request.user)
        title = str(request.data.get("title") or obj.title or "").strip()
        if not title:
            return Response({"ok": False, "error": "请填写考试名称"}, status=400)
        if "exam_date" not in request.data and not obj.exam_date:
            return Response({"ok": False, "error": "exam_date 必填（YYYY-MM-DD）"}, status=400)
        obj.title = title[:128]
        if "exam_date" in request.data:
            obj.exam_date = as_date(request.data.get("exam_date"), field="exam_date")
        if "subject" in request.data:
            obj.subject = str(request.data.get("subject") or "")[:40]
        if "target_count" in request.data:
            obj.target_count = as_int(request.data.get("target_count"), default=0,
                                      field="target_count", minimum=0, maximum=100000)
        if "note" in request.data:
            obj.note = str(request.data.get("note") or "")[:255]
        obj.save()
        return Response(_exam_payload(obj, today), status=201 if not eid else 200)

    def delete(self, request):
        eid = request.query_params.get("id") or request.data.get("id")
        obj = get_object_or_404(ExamCountdown, id=as_int(eid, field="id"), owner=request.user)
        obj.delete()
        return Response({"deleted": True})


# ---------------------------------------------------------------------------
# 379 学习小组
# ---------------------------------------------------------------------------
def _mask_name(name):
    """用户名脱敏：保留首字符，其余打码（至少 3 个星）。"""
    name = str(name or "同学")
    return name[:1] + "*" * 3


class StudyGroupView(APIView):
    """379 GET/POST study/groups/ → 小组列表 / 建组。"""

    MAX_GROUPS = 50

    def get(self, request):
        today = timezone.localdate()
        scope = (request.query_params.get("scope") or "mine").lower()
        if scope == "all":
            groups = list(StudyGroup.objects.order_by("-created_at")[:self.MAX_GROUPS])
        else:
            ids = StudyGroupMember.objects.filter(user=request.user).values_list("group_id", flat=True)
            groups = list(StudyGroup.objects.filter(
                Q(id__in=ids) | Q(owner=request.user)).order_by("-created_at")[:self.MAX_GROUPS])
        gids = [g.id for g in groups]
        # 成员 + 今日分钟：3 条聚合查询，与小组数无关
        member_rows = list(StudyGroupMember.objects.filter(group_id__in=gids)
                           .values_list("group_id", "user_id", "last_checkin"))
        user_ids = {u for _, u, _ in member_rows}
        minutes_map = {
            row["owner_id"]: row["m"] or 0
            for row in StudySession.objects.filter(owner_id__in=user_ids, study_date=today)
            .values("owner_id").annotate(m=Sum("minutes"))
        } if user_ids else {}
        by_group = {}
        for gid, uid, last in member_rows:
            item = by_group.setdefault(gid, {"members": 0, "today_minutes": 0,
                                             "checked_in": 0, "my_checked_in": False})
            item["members"] += 1
            item["today_minutes"] += minutes_map.get(uid, 0)
            if last == today:
                item["checked_in"] += 1
            if uid == request.user.id and last == today:
                item["my_checked_in"] = True
        return Response({
            "scope": scope,
            "total": len(groups),
            "list": [{
                "id": g.id, "name": g.name, "subject": g.subject,
                "goal_minutes": g.goal_minutes, "note": g.note,
                "is_owner": g.owner_id == request.user.id,
                "created_at": timezone.localtime(g.created_at).strftime("%Y-%m-%d %H:%M"),
                **(by_group.get(g.id) or {"members": 0, "today_minutes": 0,
                                           "checked_in": 0, "my_checked_in": False}),
            } for g in groups],
        })

    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"ok": False, "error": "请填写小组名称"}, status=400)
        group = StudyGroup.objects.create(
            owner=request.user, name=name[:64],
            subject=str(request.data.get("subject") or "")[:40],
            goal_minutes=as_int(request.data.get("goal_minutes"), default=60,
                                field="goal_minutes", minimum=1, maximum=1440),
            note=str(request.data.get("note") or "")[:255],
        )
        StudyGroupMember.objects.get_or_create(group=group, user=request.user)
        return Response({"ok": True, "id": group.id, "name": group.name, "members": 1}, status=201)


class StudyGroupJoinView(APIView):
    """379 POST study/groups/<int:pk>/join/ → 加入小组。"""

    def post(self, request, pk):
        group = get_object_or_404(StudyGroup, id=pk)
        member, created = StudyGroupMember.objects.get_or_create(group=group, user=request.user)
        return Response({
            "ok": True, "group_id": group.id, "name": group.name,
            "joined": created, "members": group.members.count(),
        }, status=201 if created else 200)


class StudyGroupCheckinView(APIView):
    """379 POST study/groups/<int:pk>/checkin/ → 打卡（写一条 StudySession）。"""

    def post(self, request, pk):
        group = get_object_or_404(StudyGroup, id=pk)
        member = StudyGroupMember.objects.filter(group=group, user=request.user).first()
        if member is None:
            return Response({"ok": False, "error": "请先加入该小组"}, status=403)
        minutes = as_int(request.data.get("minutes"), default=25, field="minutes", minimum=1, maximum=600)
        today = timezone.localdate()
        note = f"小组打卡：{group.name}"[:255]
        session = StudySession.objects.create(
            owner=request.user, subject=(group.subject or group.name)[:40],
            minutes=minutes, study_date=today, note=note)
        member.last_checkin = today
        member.checkin_count += 1
        member.save(update_fields=["last_checkin", "checkin_count"])
        total = StudySession.objects.filter(
            owner=request.user, study_date=today).aggregate(m=Sum("minutes"))["m"] or 0
        return Response({
            "ok": True, "session_id": session.id, "minutes": minutes,
            "group_id": group.id, "today_minutes": total,
            "checkin_count": member.checkin_count,
        }, status=201)


# ---------------------------------------------------------------------------
# 380 学习榜（仅公开用户 + 用户名脱敏）
# ---------------------------------------------------------------------------
class StudyLeaderboardView(APIView):
    """380 GET study/leaderboard/?range=week&limit=10 → 按 StudySession 分钟聚合。"""

    RANGES = ("day", "week", "month")

    def get(self, request):
        rng = (request.query_params.get("range") or "week").lower()
        if rng not in self.RANGES:
            return Response({"ok": False, "error": "range 只支持 day / week / month"}, status=400)
        limit = as_int(request.query_params.get("limit"), default=10, field="limit", minimum=1, maximum=50)
        today = timezone.localdate()
        if rng == "day":
            start = today
        elif rng == "week":
            start = today - timedelta(days=today.weekday())
        else:
            start = today.replace(day=1)

        rows = list(
            StudySession.objects
            .filter(study_date__gte=start, study_date__lte=today,
                    owner__learning_pref__leaderboard_public=True)
            .values("owner_id")
            .annotate(minutes=Sum("minutes"), days=Count("study_date", distinct=True))
            .order_by("-minutes", "owner_id")[:limit]
        )
        names = {u.id: u.username for u in User.objects.filter(id__in=[r["owner_id"] for r in rows])}
        mine = StudySession.objects.filter(
            owner=request.user, study_date__gte=start, study_date__lte=today
        ).aggregate(m=Sum("minutes"), d=Count("study_date", distinct=True))
        pref = LearningPref.objects.filter(owner=request.user).first()
        return Response({
            "range": rng, "start": start.isoformat(), "end": today.isoformat(),
            "total": len(rows),
            "list": [{
                "rank": i + 1,
                "name": _mask_name(names.get(r["owner_id"])),
                "minutes": r["minutes"] or 0,
                "days": r["days"] or 0,
            } for i, r in enumerate(rows)],
            "me": {
                "minutes": mine["m"] or 0,
                "days": mine["d"] or 0,
                "public": bool(pref and pref.leaderboard_public),
            },
        })


# ---------------------------------------------------------------------------
# 381 题单分享（分享令牌 + 免登录只读）
# ---------------------------------------------------------------------------
class QuestionSetShareView(APIView):
    """381 POST study/question-sets/<int:pk>/share/ → 生成 share_token。"""

    def post(self, request, pk):
        obj = get_object_or_404(QuestionSet, id=pk, owner=request.user)
        token = obj.ensure_share_token()
        return Response({
            "ok": True, "id": obj.id, "share_token": token,
            "path": f"/api/learning/share/questionset/{token}/",
        })


class PublicQuestionSetView(APIView):
    """381 GET share/questionset/<token>/ → 免登录只读（不含答案与作者信息）。"""

    authentication_classes = []
    permission_classes = []

    def get(self, request, token):
        obj = QuestionSet.objects.filter(share_token=token).first()
        if obj is None:
            return Response({"ok": False, "error": "分享链接不存在或已失效"}, status=404)
        ids = [str(i) for i in (obj.question_ids or [])][:200]
        index = {q.get("id"): q for q in getattr(qb, "QUESTIONS", [])}
        items = [qb.public_question(index[i], with_answer=False) for i in ids if i in index]
        return Response({
            "ok": True, "name": obj.name, "note": obj.note,
            "count": len(items), "requested": len(ids), "list": items,
        })


# ---------------------------------------------------------------------------
# 382 题库统计
# ---------------------------------------------------------------------------
class QuestionStatsView(APIView):
    """382 GET school/questions/stats/ → 学科/题型/难度分布 + 知识点覆盖率。"""

    def get(self, request):
        questions = list(getattr(qb, "QUESTIONS", []))
        subjects = _subject_cn()
        by_subject, by_type, by_difficulty, by_stage = {}, {}, {}, {}
        kps = set()
        for q in questions:
            sub = q.get("subject") or "unknown"
            by_subject[sub] = by_subject.get(sub, 0) + 1
            by_type[q.get("type") or "other"] = by_type.get(q.get("type") or "other", 0) + 1
            diff = str(q.get("difficulty") or 0)
            by_difficulty[diff] = by_difficulty.get(diff, 0) + 1
            stage = q.get("stage") or "unknown"
            by_stage[stage] = by_stage.get(stage, 0) + 1
            if q.get("kp"):
                kps.add((stage, q.get("subject"), q["kp"]))
        all_kps = {(st.get("key"), sub.get("key"), point)
                   for st in getattr(cu, "STAGES", [])
                   for sub in st.get("subjects", [])
                   for chapter in (cu.KNOWLEDGE.get(f"{st.get('key')}.{sub.get('key')}") or [])
                   for point in chapter.get("points", [])}
        coverage = round(len(kps) / len(all_kps) * 100, 1) if all_kps else 0.0
        return Response({
            "total": len(questions),
            "by_subject": [{"key": k, "name": subjects.get(k, k), "count": v}
                           for k, v in sorted(by_subject.items(), key=lambda x: -x[1])],
            "by_type": [{"key": k, "name": _type_cn().get(k, k), "count": v}
                        for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
            "by_difficulty": [{"difficulty": int(k), "count": v}
                              for k, v in sorted(by_difficulty.items())],
            "by_stage": [{"stage": k, "count": v} for k, v in sorted(by_stage.items())],
            "kp": {
                "covered": len(kps),
                "total": len(all_kps),
                "coverage": coverage,
            },
        })


# ---------------------------------------------------------------------------
# 383 学习计划排程（按每日分钟拆分）
# ---------------------------------------------------------------------------
class StudyPlanScheduleView(APIView):
    """383 GET study/plans/<int:pk>/schedule/?daily_minutes=60 → 每日任务拆分。"""

    MAX_DAYS = 90

    def get(self, request, pk):
        plan = get_object_or_404(StudyPlan, id=pk, owner=request.user)
        daily_minutes = as_int(request.query_params.get("daily_minutes"), default=60,
                               field="daily_minutes", minimum=5, maximum=600)
        today = timezone.localdate()
        remaining = max(0, (plan.total or 0) - (plan.finished or 0))
        deadline = plan.start_date + timedelta(days=max(plan.days or 1, 1) - 1)
        start = max(today, plan.start_date)
        days_left = max((deadline - start).days + 1, 1)
        truncated = days_left > self.MAX_DAYS
        span = min(days_left, self.MAX_DAYS)

        schedule = []
        tasks_left = remaining
        for i in range(span):
            days_remaining = span - i
            per_day = math.ceil(tasks_left / days_remaining) if days_remaining else 0
            per_day = min(per_day, tasks_left)
            per_task = max(5, daily_minutes // max(per_day, 1))
            minutes = min(daily_minutes, per_day * per_task) if per_day else 0
            day = start + timedelta(days=i)
            schedule.append({
                "date": day.isoformat(),
                "weekday": "一二三四五六日"[day.weekday()],
                "tasks": per_day,
                "minutes": minutes,
                "is_today": day == today,
                "is_deadline": day == deadline,
            })
            tasks_left -= per_day
        return Response({
            "plan_id": plan.id, "title": plan.title, "subject": plan.subject,
            "total": plan.total, "finished": plan.finished, "remaining": remaining,
            "start_date": plan.start_date.isoformat(),
            "deadline": deadline.isoformat(),
            "days_left": days_left,
            "daily_minutes": daily_minutes,
            "schedule": schedule,
            "truncated": truncated,
            "note": "剩余任务按「剩余量 ÷ 剩余天数」每天摊分，单日不超过 daily_minutes 分钟。",
        })


# ---------------------------------------------------------------------------
# 384 掌握度热力图（学科 × 周）
# ---------------------------------------------------------------------------
class MasteryHeatmapView(APIView):
    """384 GET school/mastery/heatmap/?days=90 → 学科×周订正率矩阵。"""

    def get(self, request):
        days = as_int(request.query_params.get("days"), default=90, field="days", minimum=7, maximum=365)
        today = timezone.localdate()
        weeks = min(math.ceil(days / 7), 53)
        current_monday = today - timedelta(days=today.weekday())
        week_starts = [current_monday - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]
        start = week_starts[0]
        tz = timezone.get_current_timezone()
        rows = (
            MistakeRecord.objects.filter(owner=request.user, created_at__date__gte=start)
            .annotate(w=TruncWeek("created_at", tzinfo=tz))
            .values("subject", "w")
            .annotate(total=Count("id"), mastered=Count("id", filter=Q(mastered=True)))
        )
        cell_map = {}
        subject_totals = {}
        for r in rows:
            week = r["w"]
            if hasattr(week, "date"):
                week = timezone.localtime(week).date() if timezone.is_aware(week) else week.date()
            week = week - timedelta(days=week.weekday())
            key = (r["subject"] or "", week.isoformat())
            cell_map[key] = (r["total"], r["mastered"])
            agg = subject_totals.setdefault(r["subject"] or "", {"total": 0, "mastered": 0})
            agg["total"] += r["total"]
            agg["mastered"] += r["mastered"]

        names = _subject_cn()
        ordered = sorted(subject_totals.items(), key=lambda x: -x[1]["total"])[:12]
        matrix = []
        for subject, agg in ordered:
            cells = []
            for ws in week_starts:
                total, mastered = cell_map.get((subject, ws.isoformat()), (0, 0))
                cells.append({
                    "week": ws.isoformat(), "total": total, "mastered": mastered,
                    "rate": round(mastered / total * 100, 1) if total else None,
                })
            rate = round(agg["mastered"] / agg["total"] * 100, 1) if agg["total"] else 100.0
            matrix.append({
                "subject": subject or "unclassified",
                "subject_name": names.get(subject, subject or "未分类"),
                "total": agg["total"], "mastered": agg["mastered"], "rate": rate,
                "cells": cells,
            })
        return Response({
            "days": days,
            "weeks": [{"start": ws.isoformat(), "label": ws.strftime("%m-%d")} for ws in week_starts],
            "subjects": matrix,
            "legend": [{"min": 0, "max": 39}, {"min": 40, "max": 69},
                       {"min": 70, "max": 89}, {"min": 90, "max": 100}],
        })


# ---------------------------------------------------------------------------
# 385 公式计算历史（保留最近 100 条）
# ---------------------------------------------------------------------------
MAX_CALC_LOGS = 100


def record_formula_log(user, formula_key, values, result):
    """写一条计算历史并裁剪到 100 条；异常不影响主流程。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        log = FormulaCalcLog.objects.create(
            owner=user, formula_key=str(formula_key)[:64],
            values=values if isinstance(values, dict) else {},
            result=str(result)[:64],
        )
        keep = list(FormulaCalcLog.objects.filter(owner=user)
                    .order_by("-created_at").values_list("id", flat=True)[:MAX_CALC_LOGS])
        FormulaCalcLog.objects.filter(owner=user).exclude(id__in=keep).delete()
        return log
    except Exception:  # noqa: BLE001 —— 历史记录失败绝不影响计算本身
        return None


def _formula_by_key(key):
    return next((x for x in getattr(cu, "FORMULAS", []) if x.get("key") == key), None)


class FormulaCalcHistoryView(APIView):
    """385 GET/POST school/formulas/calc-history/ → 回填用的最近计算记录。"""

    def get(self, request):
        limit = as_int(request.query_params.get("limit"), default=10, field="limit", minimum=1, maximum=50)
        qs = FormulaCalcLog.objects.filter(owner=request.user)[:limit]
        names = {f["key"]: f.get("name", f["key"]) for f in getattr(cu, "FORMULAS", [])}
        return Response({
            "total": FormulaCalcLog.objects.filter(owner=request.user).count(),
            "list": [{
                "id": o.id, "key": o.formula_key,
                "name": names.get(o.formula_key, o.formula_key),
                "values": o.values or {}, "result": o.result,
                "created_at": timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"),
            } for o in qs],
        })

    def post(self, request):
        key = str(request.data.get("key") or "").strip()
        formula = _formula_by_key(key)
        if formula is None:
            return Response({"ok": False, "error": "公式不存在"}, status=404)
        raw = request.data.get("values") or {}
        if not isinstance(raw, dict):
            return Response({"ok": False, "error": "values 需为对象"}, status=400)
        values, result = {}, request.data.get("result")
        for vk, _label in formula["vars"]:
            try:
                values[vk] = float(raw.get(vk))
            except (TypeError, ValueError):
                values = {}
                break
        if values and result in (None, ""):
            try:
                result = round(cu.safe_eval_expr(formula["expr"], values), 6)
            except Exception:  # noqa: BLE001
                result = ""
        log = record_formula_log(request.user, key, values or raw, result if result is not None else "")
        return Response({
            "ok": True, "id": getattr(log, "id", None),
            "key": key, "values": values or raw, "result": "" if result is None else str(result),
        }, status=201)


# ---------------------------------------------------------------------------
# 386 生词本导入导出（按 word 去重）
# ---------------------------------------------------------------------------
_WORD_FIELDS = {
    "word": ("word", "单词"),
    "phonetic": ("phonetic", "音标"),
    "meaning": ("meaning", "释义"),
    "mastered": ("mastered", "已掌握"),
}
_WORD_PICK = _build_row_getter(_WORD_FIELDS)


class WordbookExportView(APIView):
    """386 GET school/words/wordbook/export/?fmt=csv → 生词本附件流。"""

    def get(self, request):
        fmt = str(request.query_params.get("fmt") or "csv").strip().lower()
        if fmt != "csv":
            return Response({"ok": False, "error": "暂仅支持 fmt=csv"}, status=400)
        qs = WordbookItem.objects.filter(owner=request.user).order_by("-created_at")
        rows = [[o.word, o.phonetic, o.meaning, "是" if o.mastered else "否",
                 timezone.localtime(o.created_at).strftime("%Y-%m-%d")]
                for o in qs[:MAX_WORDS_EXPORT_ROWS]]
        stamp = timezone.localdate().strftime("%Y%m%d")
        return _csv_response(f"wordbook_{stamp}.csv",
                             ["单词", "音标", "释义", "已掌握", "加入时间"], rows)


class WordbookImportView(APIView):
    """386 POST school/words/wordbook/import/ {format, text} → 按 word 去重导入。"""

    def post(self, request):
        fmt = str(request.data.get("format") or "csv").strip().lower()
        if fmt not in ("csv", "json"):
            return Response({"ok": False, "error": "format 只支持 csv / json"}, status=400)
        rows, error = _load_rows(request.data, fmt)
        if error:
            return Response({"ok": False, "error": error}, status=400)
        if not rows:
            return Response({"ok": False, "error": "没有可导入的数据"}, status=400)
        if len(rows) > MAX_WORDS_IMPORT_ROWS:
            return Response({"ok": False, "error": f"单次最多导入 {MAX_WORDS_IMPORT_ROWS} 行"}, status=400)

        errors, candidates = [], []
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                errors.append({"row": idx, "error": "行数据必须是对象"})
                continue
            word = _WORD_PICK(row, "word")
            if not word:
                errors.append({"row": idx, "error": "缺少 word"})
                continue
            if len(word) > 64:
                errors.append({"row": idx, "error": "单词过长（上限 64 字符）"})
                continue
            candidates.append({
                "word": word,
                "phonetic": _WORD_PICK(row, "phonetic")[:48],
                "meaning": _WORD_PICK(row, "meaning")[:255],
                "mastered": _WORD_PICK(row, "mastered").lower() in ("1", "true", "yes", "是", "已掌握"),
            })

        words = [c["word"] for c in candidates]
        # 按 word 小写去重（与既有记录也不区分大小写；限本次候选词，不扫全表）
        existing = {
            w.lower() for w in WordbookItem.objects.filter(owner=request.user)
            .annotate(lw=Lower("word")).filter(lw__in=[w.lower() for w in words])
            .values_list("lw", flat=True)
        }
        created, objs = 0, []
        for item in candidates:
            key = item["word"].lower()
            if key in existing:
                continue
            existing.add(key)
            objs.append(WordbookItem(owner=request.user, **item))
        if objs:
            WordbookItem.objects.bulk_create(objs, batch_size=200)
            created = len(objs)
        skipped = len(rows) - created
        return Response({
            "ok": True, "format": fmt, "total": len(rows), "created": created,
            "skipped": skipped, "duplicated": len(candidates) - created,
            "errors": _err(errors), "errors_truncated": len(errors) > MAX_ERRORS,
        }, status=201)


# ---------------------------------------------------------------------------
# 387 / 388 错题转笔记 / 错题转待办
# ---------------------------------------------------------------------------
class MistakeToNoteView(APIView):
    """387 POST school/mistakes/<int:pk>/to-note/ → 用题干/解析/错因建 Note。"""

    def post(self, request, pk):
        m = get_object_or_404(MistakeRecord, id=pk, owner=request.user)
        from notes.models import Note  # 局部导入：避免跨 app 模块级耦合

        types, causes = _type_cn(), _cause_cn()
        lines = [
            f"### 题干\n\n{m.stem}\n",
            f"- 学科：{subject_name(m.subject)}",
            f"- 题型：{types.get(m.question_type, m.question_type)}　难度：{'★' * min(m.difficulty, 5)}",
            f"- 我的答案：{m.user_answer or '（未记录）'}",
            f"- 正确答案：{m.answer or '（未记录）'}",
            f"- 错因：{causes.get(m.cause, '未归类')}\n",
            f"### 解析\n\n{m.analysis or '（待补充）'}\n",
            "### 复盘\n\n- [ ] 重做一遍并说出关键步骤\n- [ ] 归纳同类题的通用解法\n",
        ]
        title = f"错题复盘：{m.stem[:30]}" if m.stem else "错题复盘"
        note = Note.objects.create(owner=request.user, title=title[:200],
                                   content="\n".join(lines), source="import")
        return Response({"ok": True, "note_id": note.id, "title": note.title,
                         "path": f"/notes?id={note.id}"}, status=201)


class MistakeToTodoView(APIView):
    """388 POST school/mistakes/<int:pk>/to-todo/?due=YYYY-MM-DD → 建 TodoItem。"""

    def post(self, request, pk):
        m = get_object_or_404(MistakeRecord, id=pk, owner=request.user)
        from officesuite.models import TodoItem  # 局部导入

        raw_due = request.query_params.get("due") or request.data.get("due")
        due = as_date(raw_due, field="due") if raw_due else None
        title = (m.stem or "错题复习").strip()[:40]
        todo = TodoItem.objects.create(
            owner=request.user, title=title, priority="normal", due_date=due,
            status="open", data={"source": "learning_mistake", "mistake_id": m.id},
        )
        return Response({
            "ok": True, "id": todo.id, "title": todo.title,
            "due_date": due.isoformat() if due else None,
        }, status=201)


# ---------------------------------------------------------------------------
# 389 学习时长 × 工具使用 双序列报表
# ---------------------------------------------------------------------------
class UsageReportView(APIView):
    """389 GET study/usage-report/?days=30 → 按日双序列（分钟 / 工具次数）。"""

    def get(self, request):
        days = as_int(request.query_params.get("days"), default=30, field="days", minimum=1, maximum=180)
        today = timezone.localdate()
        start = today - timedelta(days=days - 1)
        minutes = {
            row["study_date"]: row["m"] or 0
            for row in StudySession.objects.filter(owner=request.user, study_date__gte=start)
            .values("study_date").annotate(m=Sum("minutes"))
        }
        calls = {
            row["d"]: row["c"] or 0
            for row in ToolUsageLog.objects.filter(owner=request.user, used_at__date__gte=start)
            .annotate(d=TruncDate("used_at")).values("d").annotate(c=Count("id"))
        }
        series, total_minutes, total_calls, active = [], 0, 0, 0
        for i in range(days):
            day = start + timedelta(days=i)
            m, c = minutes.get(day, 0), calls.get(day, 0)
            total_minutes += m
            total_calls += c
            active += 1 if (m or c) else 0
            series.append({"date": day.isoformat(), "minutes": m, "tool_calls": c})
        peak = max(series, key=lambda x: x["minutes"]) if series else None
        return Response({
            "days": days,
            "start": start.isoformat(),
            "end": today.isoformat(),
            "series": series,
            "totals": {
                "minutes": total_minutes,
                "tool_calls": total_calls,
                "active_days": active,
                "avg_minutes": round(total_minutes / days, 1) if days else 0,
                "avg_calls": round(total_calls / days, 1) if days else 0,
            },
            "peak": peak if peak and peak["minutes"] else None,
        })


# ---------------------------------------------------------------------------
# 390 每日目标达成预测（近 7 天线性外推）
# ---------------------------------------------------------------------------
class DailyGoalForecastView(APIView):
    """390 GET study/daily-goal/forecast/ → 本周达成概率与需补时长。"""

    def get(self, request):
        goal, _ = DailyGoal.objects.get_or_create(owner=request.user)
        target = goal.target_minutes or 0
        today = timezone.localdate()
        days = [today - timedelta(days=6 - i) for i in range(7)]
        raw = {
            row["study_date"]: row["m"] or 0
            for row in StudySession.objects.filter(owner=request.user, study_date__gte=days[0])
            .values("study_date").annotate(m=Sum("minutes"))
        }
        series = [raw.get(d, 0) for d in days]

        week_start = today - timedelta(days=today.weekday())
        done_this_week = StudySession.objects.filter(
            owner=request.user, study_date__gte=week_start, study_date__lte=today
        ).aggregate(m=Sum("minutes"))["m"] or 0
        days_left = 6 - today.weekday()

        payload = {
            "target_minutes": target,
            "history": [{"date": d.isoformat(), "minutes": m} for d, m in zip(days, series)],
            "avg_7d": round(sum(series) / 7, 1),
            "days_left_in_week": days_left,
            "done_this_week": done_this_week,
        }
        if target <= 0:
            return Response({**payload, "week_target": 0, "probability": 0,
                             "need_minutes": 0, "message": "先去设置每日目标，再来看达成预测。"})

        # 最小二乘线性拟合近 7 天分钟数（x=0..6）
        n = 7
        mean_x = (n - 1) / 2
        mean_y = sum(series) / n
        denom = sum((i - mean_x) ** 2 for i in range(n))
        slope = sum((i - mean_x) * (series[i] - mean_y) for i in range(n)) / denom if denom else 0.0
        intercept = mean_y - slope * mean_x
        predicted = [max(0.0, intercept + slope * (n + i)) for i in range(days_left)]
        projected = done_this_week + sum(predicted)
        week_target = target * 7
        probability = max(0.0, min(1.0, projected / week_target)) if week_target else 0.0
        need = max(0, round(week_target - projected))
        if probability >= 0.9:
            message = f"按当前节奏，本周目标基本稳了（预计 {round(projected)} 分钟）。"
        elif probability >= 0.6:
            message = f"本周达成概率 {round(probability * 100)}%，还需补 {need} 分钟，建议每天多学 {math.ceil(need / max(days_left, 1))} 分钟。"
        else:
            message = (f"本周达成概率仅 {round(probability * 100)}%，还需补 {need} 分钟，"
                       f"先保证每天 {target} 分钟不断档。")
        return Response({
            **payload,
            "week_target": week_target,
            "projected_week_minutes": round(projected, 1),
            "slope": round(slope, 2),
            "probability": round(probability, 3),
            "need_minutes": need,
            "message": message,
        })
