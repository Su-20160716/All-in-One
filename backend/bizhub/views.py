# -*- coding: utf-8 -*-
"""bizhub 引擎视图：34 个业务模块共用同一套 CRUD / 权限 / 批量 / 分析 / 导入导出。

约定（与全仓一致）：
- 统一 ``ok(data)`` / ``fail(msg, status)``，异常抛 ValueError 由
  ``devtools.common.endpoint`` 兜底为 400，绝不 500；
- 读写权限全部走 ``core.scoping``：管理员（superuser/staff）不受数据范围限制，
  普通用户读按数据范围可见、写按「管理员 / 负责人本人 / 部门及以上范围的可见者」；
- 模块元数据与字段 schema 来自 ``bizhub/modules.py``，本文件不含任何业务分支。
"""
import csv
import io
import json
import math
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, TextField, When
from django.db.models.functions import Cast
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import notify
from core.scoping import data_scope_of, is_visible, scope_queryset, visible_user_ids

from devtools.common import endpoint, fail, ok, opt_bool, opt_str, p

from . import modules
from .models import (
    BizActivity,
    BizComment,
    BizRecord,
    BizSavedView,
    BizSubscription,
)

_missing = object()

PRIORITIES = ("low", "normal", "high", "urgent")
PRIORITY_LABELS = {"low": "低", "normal": "普通", "high": "高", "urgent": "紧急"}
ACTION_LABELS = {
    "create": "创建",
    "update": "更新",
    "delete": "删除",
    "restore": "恢复",
    "archive": "归档",
    "unarchive": "取消归档",
    "duplicate": "复制",
    "merge": "合并",
    "favorite": "收藏",
    "import": "导入",
}
_ORDERINGS = {
    "created_at": ["created_at", "id"],
    "-created_at": ["-created_at", "-id"],
    "updated_at": ["updated_at", "id"],
    "-updated_at": ["-updated_at", "-id"],
    "due_date": [F("due_date").asc(nulls_last=True), "id"],
    "-due_date": [F("due_date").desc(nulls_last=True), "-id"],
    "priority": [
        Case(
            When(priority="urgent", then=0),
            When(priority="high", then=1),
            When(priority="normal", then=2),
            When(priority="low", then=3),
            default=4,
            output_field=IntegerField(),
        ),
        "id",
    ],
    "-priority": [
        Case(
            When(priority="urgent", then=0),
            When(priority="high", then=1),
            When(priority="normal", then=2),
            When(priority="low", then=3),
            default=4,
            output_field=IntegerField(),
        ).desc(),
        "-id",
    ],
    "title": ["title", "id"],
    "-title": ["-title", "-id"],
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _is_admin(user) -> bool:
    """管理员通行：超管或 staff（与 officesuite.common._is_admin 同口径）。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def _module(slug):
    """只允许 modules.MODULE_INDEX 中的 slug，其余返回 None。"""
    if not isinstance(slug, str):
        return None
    return modules.MODULE_INDEX.get(slug)


def _done_keys(mod):
    return [s["key"] for s in mod["statuses"] if s.get("done")]


def _status_label(mod, key):
    for s in mod["statuses"]:
        if s["key"] == key:
            return s["label"]
    return key or ""


def _body(request):
    data = request.data
    if isinstance(data, dict):
        return data
    if hasattr(data, "dict") and callable(data.dict):
        return data.dict()
    return {}


def _can_edit(user, rec) -> bool:
    """写权限：管理员 / 负责人本人 / 部门及以上数据范围且记录可见。"""
    if rec is None:
        return False
    if _is_admin(user):
        return True
    if rec.owner_id is not None and rec.owner_id == getattr(user, "id", None):
        return True
    return data_scope_of(user) in ("dept", "dept_and_sub", "all") and is_visible(rec, user)


def _can_read(user, rec) -> bool:
    if rec is None:
        return False
    return _is_admin(user) or is_visible(rec, user)


def _readable_qs(user, qs):
    if _is_admin(user):
        return qs
    return scope_queryset(qs, user, "owner")


def _base_qs(request, user, mod):
    """列表基础 queryset：删除 / 归档 / 数据范围三件事集中在这里。

    deleted=1 → 只看回收站；archived=1 → 只看归档；include_archived=1 → 归档+活跃；
    默认只看活跃（未删除且未归档）。
    """
    qs = BizRecord.objects.filter(module=mod["slug"])
    if opt_bool(request, "deleted"):
        qs = qs.filter(is_deleted=True)
    else:
        qs = qs.filter(is_deleted=False)
        if opt_bool(request, "archived"):
            qs = qs.filter(archived=True)
        elif not opt_bool(request, "include_archived"):
            qs = qs.filter(archived=False)
    return _readable_qs(user, qs)


def _int_param(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _int_ids(value, limit=200, minimum=1):
    if isinstance(value, str):
        value = [x for x in value.replace("，", ",").split(",") if x.strip()]
    if not isinstance(value, (list, tuple)):
        raise ValueError("ids 必须是数组")
    out = []
    for v in value:
        if isinstance(v, bool):
            raise ValueError("ids 必须是整数数组")
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError("ids 必须是整数数组")
        if n not in out:
            out.append(n)
    if len(out) < minimum:
        raise ValueError(f"ids 至少需要 {minimum} 项")
    if len(out) > limit:
        raise ValueError(f"ids 最多 {limit} 项")
    return out


def _page(qs, request):
    """手动分页：page>=1，page_size 1..100（默认 20）。"""
    page = max(1, _int_param(p(request, "page"), 1))
    page_size = _int_param(p(request, "page_size"), 20)
    page_size = min(100, max(1, page_size))
    count = qs.count()
    start = (page - 1) * page_size
    items = list(qs[start: start + page_size])
    return items, count, page, page_size


def _favorite_ids(user, ids):
    if not ids:
        return set()
    return set(user.biz_favorites.filter(id__in=ids).values_list("id", flat=True))


def _user_brief(user):
    if user is None or not getattr(user, "pk", None):
        return None
    return {
        "id": user.pk,
        "name": getattr(user, "display_name", None) or getattr(user, "username", ""),
        "username": getattr(user, "username", ""),
    }


def _rec_dict(rec, user, favorite_ids=None):
    mod = modules.MODULE_INDEX.get(rec.module)
    if favorite_ids is not None:
        favorite = rec.pk in favorite_ids
    else:
        favorite = rec.favorited_by.filter(pk=getattr(user, "pk", None)).exists()
    return {
        "id": rec.pk,
        "module": rec.module,
        "title": rec.title,
        "status": rec.status,
        "status_label": _status_label(mod, rec.status) if mod else rec.status,
        "category": rec.category,
        "priority": rec.priority,
        "owner": _user_brief(rec.owner),
        "department": rec.department.name if rec.department_id and rec.department else "",
        "department_id": rec.department_id,
        "due_date": rec.due_date.isoformat() if rec.due_date else None,
        "tags": list(rec.tags or []),
        "data": rec.data or {},
        "archived": bool(rec.archived),
        "is_deleted": bool(rec.is_deleted),
        "favorite": favorite,
        "created_by": _user_brief(rec.created_by),
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def _log(rec, user, action, detail=None):
    try:
        return BizActivity.objects.create(
            record=rec,
            actor=user if getattr(user, "pk", None) else None,
            action=(action or "update")[:32],
            detail=detail or {},
        )
    except Exception:  # noqa: BLE001 —— 留痕失败不能影响主业务
        return None


def _notify_owner(rec, title, content, link="", actor=None):
    """通知记录负责人；负责人缺失或就是操作人时不发。"""
    owner = rec.owner
    if owner is None:
        return None
    if actor is not None and owner.pk == getattr(actor, "pk", None):
        return None
    return notify(owner, title=title, content=content, category="system", level="info", link=link)


def _parse_day(value, label="日期"):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = parse_date(text)
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValueError(f"{label} 必须是日期（YYYY-MM-DD）")
    return parsed


def _resolve_owner(raw, actor):
    """owner_id / 用户名 → User，并校验「必须是可见用户或管理员」。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    from accounts.models import User

    if isinstance(raw, str) and not raw.strip().lstrip("-").isdigit():
        user = (
            User.objects.filter(username=raw.strip()).first()
            or User.objects.filter(nickname=raw.strip()).first()
        )
    else:
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            raise ValueError("负责人必须是用户 id 或用户名")
        user = User.objects.filter(pk=pk).first()
    if user is None:
        raise ValueError("负责人不存在")
    if not _is_admin(actor):
        ids = visible_user_ids(actor)
        if ids is not None and user.pk not in ids:
            raise ValueError("无权指派给该负责人")
    return user


def _clean_tags(value):
    if value is None:
        return []
    if isinstance(value, str):
        parts = [x.strip() for x in value.replace("，", ",").split(",")]
    elif isinstance(value, (list, tuple)):
        parts = [str(x).strip() for x in value]
    else:
        raise ValueError("tags 必须是数组或逗号分隔字符串")
    out = []
    for t in parts:
        if not t:
            continue
        if len(t) > 30:
            raise ValueError("单个标签不能超过 30 字符")
        if t not in out:
            out.append(t)
    if len(out) > 20:
        raise ValueError("标签最多 20 个")
    return out


def _clean_field_value(field, value):
    """按字段 type 校验单个自定义字段值；空值统一落 None。"""
    label = field.get("label") or field.get("key") or "字段"
    ftype = field.get("type") or "text"
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if ftype == "number":
        if isinstance(value, bool):
            raise ValueError(f"{label} 必须是数字")
        try:
            num = float(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{label} 必须是数字")
        if not math.isfinite(num):
            raise ValueError(f"{label} 必须是有限数字")
        return int(num) if num.is_integer() else num
    if ftype == "date":
        day = _parse_day(value, label)
        return day.isoformat() if day else None
    if ftype == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{label} 必须是布尔值")
    if ftype == "select":
        text = str(value).strip()
        if field.get("options") and text not in field["options"]:
            raise ValueError(f"{label} 必须是：{'/'.join(field['options'])}")
        return text
    if ftype == "textarea":
        text = str(value)
        if len(text) > 2000:
            raise ValueError(f"{label} 不能超过 2000 字符")
        return text
    text = str(value)
    if len(text) > 500:
        raise ValueError(f"{label} 不能超过 500 字符")
    return text


def _clean_payload(mod, payload, partial=False, actor=None):
    """按模块 schema 规范化入参；任何非法值抛 ValueError（→400）。

    :param partial: True 时只处理显式传入的字段（PATCH 语义）
    :param actor: 用于负责人可见性校验的当前用户
    """
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    out = {}
    fields = {f["key"]: f for f in mod["fields"]}
    statuses = [s["key"] for s in mod["statuses"]]
    given = payload.__contains__

    # title
    if given("title") or not partial:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        if len(title) > 200:
            raise ValueError("标题不能超过 200 字符")
        out["title"] = title

    # status
    if given("status") or not partial:
        status = str(payload.get("status") or "").strip()
        if not status:
            status = statuses[0] if statuses else ""
        if statuses and status not in statuses:
            raise ValueError(f"状态必须是：{', '.join(statuses)}")
        out["status"] = status

    # category
    if given("category") or not partial:
        category = str(payload.get("category") or "").strip()
        if category and mod["categories"] and category not in mod["categories"]:
            raise ValueError(f"分类必须是：{', '.join(mod['categories'])}")
        out["category"] = category

    # priority
    if given("priority") or not partial:
        priority = str(payload.get("priority") or "normal").strip().lower()
        if priority not in PRIORITIES:
            raise ValueError(f"优先级必须是：{', '.join(PRIORITIES)}")
        out["priority"] = priority

    # due_date
    if given("due_date") or not partial:
        raw = payload.get("due_date")
        out["due_date"] = _parse_day(raw, "到期日") if raw not in (None, "") else None

    # tags
    if given("tags") or not partial:
        out["tags"] = _clean_tags(payload.get("tags"))

    # data（只接受 schema 中定义的 key；缺省不写入）
    if given("data"):
        raw_data = payload.get("data")
        if raw_data in (None, ""):
            raw_data = {}
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except ValueError:
                raise ValueError("data 必须是 JSON 对象")
        if not isinstance(raw_data, dict):
            raise ValueError("data 必须是 JSON 对象")
        cleaned = {}
        for key, value in raw_data.items():
            field = fields.get(key)
            if field is None:
                continue
            cleaned[key] = _clean_field_value(field, value)
        out["data"] = cleaned

    # owner（可选；创建时缺省为创建人）
    if given("owner_id"):
        out["owner_id"] = payload.get("owner_id")
    elif given("owner"):
        out["owner_id"] = payload.get("owner")

    return out


def _json_like_terms(text):
    """JSON 字段文本搜索的候选串：原文 + ensure_ascii 转义形式。

    SQLite 下 JSONField 落库是 ``json.dumps(..., ensure_ascii=True)``，
    中文会存成 ``\\u8fb9\\u754c``；PostgreSQL jsonb 转 text 则是原文。
    两种都尝试，跨库行为一致。
    """
    terms = [text]
    escaped = json.dumps(text, ensure_ascii=True)[1:-1]
    if escaped != text:
        terms.append(escaped)
    return terms


def _filtered_qs(request, user, mod):
    """列表 / 导出共用的筛选链（排序由调用方决定，分页除外）。"""
    qs = _base_qs(request, user, mod)
    q = opt_str(request, "q", "").strip()
    tag = opt_str(request, "tag", "").strip()
    if q or tag:
        qs = qs.annotate(
            tag_text=Cast("tags", TextField()),
            data_text=Cast("data", TextField()),
        )
    if q:
        cond = Q(title__icontains=q)
        for term in _json_like_terms(q):
            cond |= Q(tag_text__icontains=term) | Q(data_text__icontains=term)
        qs = qs.filter(cond)
    if tag:
        cond = Q()
        for term in _json_like_terms(tag):
            cond |= Q(tag_text__icontains=f'"{term}"')
        qs = qs.filter(cond)

    status = opt_str(request, "status", "").strip()
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        known = {s["key"] for s in mod["statuses"]}
        bad = [s for s in wanted if s not in known]
        if bad:
            raise ValueError(f"状态必须是：{', '.join(sorted(known))}")
        qs = qs.filter(status__in=wanted)

    category = opt_str(request, "category", "").strip()
    if category:
        qs = qs.filter(category=category)

    priority = opt_str(request, "priority", "").strip()
    if priority:
        if priority not in PRIORITIES:
            raise ValueError(f"优先级必须是：{', '.join(PRIORITIES)}")
        qs = qs.filter(priority=priority)

    owner = opt_str(request, "owner", "").strip()
    if owner:
        if not owner.lstrip("-").isdigit():
            raise ValueError("owner 必须是用户 id")
        qs = qs.filter(owner_id=int(owner))

    due_before = opt_str(request, "due_before", "").strip()
    if due_before:
        qs = qs.filter(due_date__lte=_parse_day(due_before, "due_before"))
    due_after = opt_str(request, "due_after", "").strip()
    if due_after:
        qs = qs.filter(due_date__gte=_parse_day(due_after, "due_after"))

    if opt_bool(request, "favorite"):
        qs = qs.filter(favorited_by=user)

    ordering = opt_str(request, "ordering", "").strip()
    if ordering:
        if ordering not in _ORDERINGS:
            raise ValueError(f"ordering 只支持：{', '.join(_ORDERINGS)}")
    else:
        ordering = "-updated_at"
    return qs.order_by(*_ORDERINGS[ordering])


def _get_record(mod, pk, user, write=False):
    """取记录并做行级校验；无权限 / 不存在返回 (None, 响应)。"""
    rec = (
        BizRecord.objects.select_related("owner", "department", "created_by")
        .filter(module=mod["slug"], pk=pk)
        .first()
    )
    if rec is None or not _can_read(user, rec):
        return None, fail("记录不存在", status=404)
    if write and not _can_edit(user, rec):
        return None, fail("无权修改该记录", status=403)
    return rec, None


# ---------------------------------------------------------------------------
# 1–4 模块目录 / 概览 / 成员
# ---------------------------------------------------------------------------


@endpoint(methods=("GET",))
def modules_list(request):
    return ok(modules.catalog())


@endpoint(methods=("GET",))
def module_detail(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    return ok(modules.module_public(mod))


@endpoint(methods=("GET",))
def overview(request):
    qs = _readable_qs(request.user, BizRecord.objects.filter(is_deleted=False, archived=False))
    today = timezone.localdate()
    rows = list(qs.values("module").annotate(c=Count("id")))
    by_group = []
    counts = {}
    for row in rows:
        mod = modules.MODULE_INDEX.get(row["module"])
        if mod is None:
            continue
        counts[mod["group"]] = counts.get(mod["group"], 0) + row["c"]
    for name in modules.GROUP_ORDER:
        by_group.append({"name": name, "count": counts.get(name, 0)})

    overdue = 0
    done_by_module = {mod["slug"]: set(_done_keys(mod)) for mod in modules.MODULES}
    for row in (
        qs.filter(due_date__lt=today)
        .values("module", "status")
        .annotate(c=Count("id"))
    ):
        if row["status"] in done_by_module.get(row["module"], ()):
            continue
        overdue += row["c"]
    return ok(
        {
            "module_count": len(modules.MODULES),
            "feature_count": modules.FEATURE_TOTAL,
            "record_count": qs.count(),
            "overdue_count": overdue,
            "by_group": by_group,
        }
    )


@endpoint(methods=("GET",))
def members(request):
    from accounts.models import User

    qs = User.objects.filter(is_active=True, is_disabled=False).select_related("department")
    if not _is_admin(request.user):
        ids = visible_user_ids(request.user)
        if ids is not None:
            qs = qs.filter(id__in=ids)
    items = [
        {
            "id": u.pk,
            "name": u.display_name,
            "username": u.username,
            "department": u.department.name if u.department_id and u.department else "",
        }
        for u in qs.order_by("username")[:500]
    ]
    return ok(items)


# ---------------------------------------------------------------------------
# 5 记录列表 / 新建
# ---------------------------------------------------------------------------


@endpoint(methods=("GET", "POST"))
def record_collection(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    if request.method == "POST":
        payload = _body(request)
        cleaned = _clean_payload(mod, payload, actor=request.user)
        owner_raw = cleaned.pop("owner_id", None)
        owner = _resolve_owner(owner_raw, request.user) if owner_raw not in (None, "") else None
        if owner is None:
            owner = request.user
        rec = BizRecord(
            module=mod["slug"],
            owner=owner,
            department=owner.department if owner.department_id else request.user.department,
            created_by=request.user,
            **cleaned,
        )
        rec.save()
        _log(rec, request.user, "create", {"title": rec.title})
        return ok(_rec_dict(rec, request.user, set()))

    qs = _filtered_qs(request, request.user, mod)
    items, count, page, page_size = _page(qs, request)
    favs = _favorite_ids(request.user, [r.pk for r in items])
    today = timezone.localdate()
    summary = {
        "total": count,
        "overdue": qs.filter(due_date__lt=today).exclude(status__in=_done_keys(mod)).count(),
    }
    return ok(
        {
            "module": mod["slug"],
            "count": count,
            "page": page,
            "page_size": page_size,
            "results": [_rec_dict(r, request.user, favs) for r in items],
            "summary": summary,
        }
    )


# ---------------------------------------------------------------------------
# 6 记录详情 / 更新 / 软删除
# ---------------------------------------------------------------------------


@endpoint(methods=("GET", "PATCH", "DELETE"))
def record_item(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    write = request.method in ("PATCH", "DELETE")
    rec, denied = _get_record(mod, pk, request.user, write=write)
    if denied is not None:
        return denied

    if request.method == "GET":
        return ok(_rec_dict(rec, request.user))

    if request.method == "DELETE":
        if not rec.is_deleted:
            rec.is_deleted = True
            rec.save(update_fields=["is_deleted", "updated_at"])
            _log(rec, request.user, "delete", {"title": rec.title})
        return ok(_rec_dict(rec, request.user))

    payload = _body(request)
    cleaned = _clean_payload(mod, payload, partial=True, actor=request.user)
    changed = []
    owner_raw = cleaned.pop("owner_id", None) if "owner_id" in cleaned else _missing
    if "data" in cleaned:
        merged = dict(rec.data or {})
        merged.update(cleaned.pop("data"))
        cleaned["data"] = merged
    for key, value in cleaned.items():
        if getattr(rec, key) != value:
            setattr(rec, key, value)
            changed.append(key)
    if owner_raw is not _missing:
        owner = _resolve_owner(owner_raw, request.user) or request.user
        if rec.owner_id != owner.pk:
            rec.owner = owner
            changed.append("owner")
        if owner.department_id and rec.department_id != owner.department_id:
            rec.department = owner.department
            changed.append("department")
    if changed:
        rec.save()
        _log(rec, request.user, "update", {"fields": changed})
    return ok(_rec_dict(rec, request.user))


_missing = object()


# ---------------------------------------------------------------------------
# 7 恢复 / 归档 / 取消归档 / 复制
# ---------------------------------------------------------------------------


@endpoint(methods=("POST",))
def record_restore(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user, write=True)
    if denied is not None:
        return denied
    if rec.is_deleted:
        rec.is_deleted = False
        rec.save(update_fields=["is_deleted", "updated_at"])
        _log(rec, request.user, "restore", {"title": rec.title})
    return ok(_rec_dict(rec, request.user))


@endpoint(methods=("POST",))
def record_archive(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user, write=True)
    if denied is not None:
        return denied
    if not rec.archived:
        rec.archived = True
        rec.save(update_fields=["archived", "updated_at"])
        _log(rec, request.user, "archive", {"title": rec.title})
    return ok(_rec_dict(rec, request.user))


@endpoint(methods=("POST",))
def record_unarchive(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user, write=True)
    if denied is not None:
        return denied
    if rec.archived:
        rec.archived = False
        rec.save(update_fields=["archived", "updated_at"])
        _log(rec, request.user, "unarchive", {"title": rec.title})
    return ok(_rec_dict(rec, request.user))


@endpoint(methods=("POST",))
def record_duplicate(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user)
    if denied is not None:
        return denied
    suffix = "（副本）"
    title = (rec.title or "")[: 200 - len(suffix)] + suffix
    copy = BizRecord.objects.create(
        module=rec.module,
        title=title,
        status=(mod["statuses"][0]["key"] if mod["statuses"] else rec.status),
        category=rec.category,
        priority=rec.priority,
        owner=request.user,
        department=request.user.department if request.user.department_id else rec.department,
        due_date=rec.due_date,
        tags=list(rec.tags or []),
        data=dict(rec.data or {}),
        created_by=request.user,
    )
    _log(copy, request.user, "duplicate", {"source_id": rec.pk})
    return ok(_rec_dict(copy, request.user, set()))


# ---------------------------------------------------------------------------
# 8–10 评论 / 时间线 / 收藏
# ---------------------------------------------------------------------------


@endpoint(methods=("GET", "POST"))
def record_comments(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user)
    if denied is not None:
        return denied

    if request.method == "GET":
        rows = rec.comments.select_related("user").all()[:200]
        items = [
            {
                "id": c.pk,
                "content": c.content,
                "user": _user_brief(c.user),
                "created_at": c.created_at.isoformat(),
            }
            for c in rows
        ]
        return ok({"total": len(items), "items": items})

    payload = _body(request)
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("评论内容不能为空")
    if len(content) > 1000:
        raise ValueError("评论不能超过 1000 字符")
    comment = BizComment.objects.create(record=rec, user=request.user, content=content)
    _notify_owner(
        rec,
        title=f"新评论：{rec.title[:40]}",
        content=content[:200],
        link=f"/bizhub/{rec.module}/{rec.pk}",
        actor=request.user,
    )
    return ok(
        {
            "id": comment.pk,
            "content": comment.content,
            "user": _user_brief(comment.user),
            "created_at": comment.created_at.isoformat(),
        }
    )


@endpoint(methods=("GET",))
def record_timeline(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user)
    if denied is not None:
        return denied

    rows = []
    for act in rec.activities.select_related("actor").all()[:200]:
        rows.append(
            (
                act.created_at,
                {
                    "kind": "activity",
                    "id": act.pk,
                    "actor": _user_brief(act.actor),
                    "action": act.action,
                    "label": ACTION_LABELS.get(act.action, act.action),
                    "detail": act.detail or {},
                    "content": "",
                    "at": act.created_at.isoformat(),
                },
            )
        )
    for cm in rec.comments.select_related("user").all()[:200]:
        rows.append(
            (
                cm.created_at,
                {
                    "kind": "comment",
                    "id": cm.pk,
                    "actor": _user_brief(cm.user),
                    "action": "comment",
                    "label": "评论",
                    "detail": {},
                    "content": cm.content,
                    "at": cm.created_at.isoformat(),
                },
            )
        )
    rows.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
    return ok({"items": [r[1] for r in rows]})


@endpoint(methods=("POST",))
def record_favorite(request, slug, pk):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    rec, denied = _get_record(mod, pk, request.user)
    if denied is not None:
        return denied

    payload = _body(request)
    raw = payload.get("favorite")
    if raw is None:
        want = not rec.favorited_by.filter(pk=request.user.pk).exists()
    else:
        want = _truthy(raw)
    if want:
        rec.favorited_by.add(request.user)
        _log(rec, request.user, "favorite", {"favorite": True})
    else:
        rec.favorited_by.remove(request.user)
    return ok({"favorite": want, "count": rec.favorited_by.count()})


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# 11 批量操作
# ---------------------------------------------------------------------------


@endpoint(methods=("POST",))
def record_bulk(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    payload = _body(request)
    action = str(payload.get("action") or "").strip()
    if action not in ("status", "owner", "tag", "archive", "delete"):
        raise ValueError("action 只支持 status/owner/tag/archive/delete")
    ids = _int_ids(payload.get("ids"), limit=200)

    status = str(payload.get("status") or "").strip()
    if action == "status":
        if status not in [s["key"] for s in mod["statuses"]]:
            raise ValueError(f"状态必须是：{', '.join(s['key'] for s in mod['statuses'])}")
    owner = None
    if action == "owner":
        owner = _resolve_owner(payload.get("owner_id"), request.user) or request.user
    tags = []
    if action == "tag":
        tags = _clean_tags(payload.get("tags"))
        if not tags:
            raise ValueError("tags 不能为空")

    recs = list(BizRecord.objects.filter(module=mod["slug"], pk__in=ids))
    skipped = len(ids) - len(recs)
    updated_ids = []
    for rec in recs:
        if not _can_edit(request.user, rec):
            skipped += 1
            continue
        if action == "status":
            rec.status = status
            detail = {"bulk": True, "status": status}
            log_action = "update"
        elif action == "owner":
            rec.owner = owner
            rec.department = owner.department if owner.department_id else None
            detail = {"bulk": True, "owner_id": owner.pk}
            log_action = "update"
        elif action == "tag":
            merged = list(rec.tags or [])
            for t in tags:
                if t not in merged:
                    merged.append(t)
            rec.tags = merged[:20]
            detail = {"bulk": True, "tags": tags}
            log_action = "update"
        elif action == "archive":
            rec.archived = True
            detail = {"bulk": True}
            log_action = "archive"
        else:
            rec.is_deleted = True
            detail = {"bulk": True}
            log_action = "delete"
        rec.save()
        _log(rec, request.user, log_action, detail)
        updated_ids.append(rec.pk)
    return ok({"updated": len(updated_ids), "skipped": skipped, "ids": updated_ids})


# ---------------------------------------------------------------------------
# 12 导出 CSV
# ---------------------------------------------------------------------------


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    # 防 CSV 公式注入：Excel 会把 = + - @ 开头的单元格当公式执行
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@endpoint(methods=("GET",))
def record_export(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    fmt = opt_str(request, "fmt", "csv").strip().lower() or "csv"
    if fmt != "csv":
        raise ValueError("目前只支持 fmt=csv")

    qs = _filtered_qs(request, request.user, mod).select_related("owner").iterator(chunk_size=500)
    header = [
        "id", "title", "status", "status_label", "category", "priority", "owner",
        "due_date", "tags", "created_at", "updated_at",
    ] + [f["label"] for f in mod["fields"]]

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    for rec in qs:
        row = [
            rec.pk,
            rec.title,
            rec.status,
            _status_label(mod, rec.status),
            rec.category,
            rec.priority,
            rec.owner.display_name if rec.owner_id and rec.owner else "",
            rec.due_date.isoformat() if rec.due_date else "",
            "|".join(rec.tags or []),
            rec.created_at.isoformat() if rec.created_at else "",
            rec.updated_at.isoformat() if rec.updated_at else "",
        ]
        data = rec.data or {}
        row.extend(data.get(f["key"]) for f in mod["fields"])
        writer.writerow([_csv_cell(c) for c in row])

    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{mod["slug"]}.csv"'
    return resp


# ---------------------------------------------------------------------------
# 13 导入
# ---------------------------------------------------------------------------


def _import_rows(payload):
    """把 {rows:[...]} 或 {csv:"..."} 统一成 [(行号, dict)]。"""
    rows = payload.get("rows")
    text = payload.get("csv")
    if rows is not None:
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("rows 必须是对象数组")
        return list(enumerate(rows, start=1))
    if text is not None:
        if not isinstance(text, str):
            raise ValueError("csv 必须是字符串")
        text = text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        out = []
        for idx, row in enumerate(reader, start=2):  # 第 1 行是表头
            out.append((idx, row))
        return out
    raise ValueError("请传 rows 数组或 csv 字符串")


def _row_payload(row, mod):
    by_key = {f["key"]: f for f in mod["fields"]}
    by_label = {f["label"]: f for f in mod["fields"]}
    payload = {}
    custom = {}
    owner_value = None
    for raw_key, raw_val in row.items():
        if raw_key is None:
            continue
        key = str(raw_key).strip()
        low = key.lower()
        val = raw_val.strip() if isinstance(raw_val, str) else raw_val
        if low in ("title", "status", "category", "priority", "due_date", "tags"):
            payload[low] = val
            continue
        if low in ("owner", "owner_id"):
            owner_value = val
            continue
        field = by_key.get(key) or by_label.get(key) or by_key.get(low)
        if field is not None and val not in (None, ""):
            custom[field["key"]] = val
    if owner_value not in (None, ""):
        payload["owner_id"] = owner_value
    if custom:
        payload["data"] = custom
    return payload


@endpoint(methods=("POST",))
def record_import(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    pairs = _import_rows(_body(request))
    if len(pairs) > 500:
        raise ValueError("单次最多导入 500 行")

    created = 0
    errors = []
    for row_no, row in pairs:
        try:
            payload = _row_payload(row, mod)
            cleaned = _clean_payload(mod, payload, actor=request.user)
            owner_raw = cleaned.pop("owner_id", None)
            owner = _resolve_owner(owner_raw, request.user) if owner_raw not in (None, "") else None
            if owner is None:
                owner = request.user
            rec = BizRecord(
                module=mod["slug"],
                owner=owner,
                department=owner.department if owner.department_id else request.user.department,
                created_by=request.user,
                **cleaned,
            )
            rec.save()
            _log(rec, request.user, "import", {"row": row_no})
            created += 1
        except ValueError as e:
            errors.append({"row": row_no, "message": str(e)})
    return ok({"total": len(pairs), "created": created, "errors": errors})


# ---------------------------------------------------------------------------
# 14–18 统计 / 趋势 / 分布 / 逾期 / 质量
# ---------------------------------------------------------------------------


def _module_qs(user, mod, include_archived=True):
    qs = BizRecord.objects.filter(module=mod["slug"], is_deleted=False)
    if not include_archived:
        qs = qs.filter(archived=False)
    return _readable_qs(user, qs)


@endpoint(methods=("GET",))
def record_stats(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    today = timezone.localdate()
    now = timezone.now()
    base = _module_qs(request.user, mod)
    done = _done_keys(mod)
    total = base.count()
    archived = base.filter(archived=True).count()
    done_count = base.filter(status__in=done).count()
    active = base.filter(archived=False).exclude(status__in=done).count()
    overdue = (
        base.filter(archived=False, due_date__lt=today)
        .exclude(status__in=done)
        .count()
    )
    new_7d = base.filter(created_at__gte=now - timedelta(days=7)).count()
    new_30d = base.filter(created_at__gte=now - timedelta(days=30)).count()
    ages = [
        (now - c).days
        for c in base.values_list("created_at", flat=True)
        if c is not None
    ]
    avg_age = round(sum(ages) / len(ages), 1) if ages else 0
    by_status_counts = dict(
        base.values_list("status").annotate(c=Count("id")).values_list("status", "c")
    )
    by_priority_counts = dict(
        base.values_list("priority").annotate(c=Count("id")).values_list("priority", "c")
    )
    return ok(
        {
            "total": total,
            "active": active,
            "done": done_count,
            "overdue": overdue,
            "archived": archived,
            "completion_rate": round(done_count * 100.0 / total, 1) if total else 0,
            "new_7d": new_7d,
            "new_30d": new_30d,
            "avg_age_days": avg_age,
            "by_status": [
                {"key": s["key"], "label": s["label"], "count": by_status_counts.get(s["key"], 0)}
                for s in mod["statuses"]
            ],
            "by_priority": [
                {"key": k, "label": PRIORITY_LABELS[k], "count": by_priority_counts.get(k, 0)}
                for k in PRIORITIES
            ],
        }
    )


@endpoint(methods=("GET",))
def record_trend(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    days = _int_param(p(request, "days"), 30)
    days = min(90, max(1, days))

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    done = _done_keys(mod)
    base = _module_qs(request.user, mod).filter(created_at__date__gte=start)
    created_map = {}
    for c in base.values_list("created_at", flat=True):
        if c is None:
            continue
        d = timezone.localtime(c).date()
        created_map[d] = created_map.get(d, 0) + 1

    closed_map = {}
    if done:
        closed_rows = (
            _module_qs(request.user, mod)
            .filter(status__in=done, updated_at__date__gte=start)
            .values_list("updated_at", flat=True)
        )
        for u in closed_rows:
            if u is None:
                continue
            d = timezone.localtime(u).date()
            closed_map[d] = closed_map.get(d, 0) + 1

    items = []
    for i in range(days):
        d = start + timedelta(days=i)
        items.append(
            {
                "date": d.isoformat(),
                "created": created_map.get(d, 0),
                "closed": closed_map.get(d, 0),
            }
        )
    return ok({"days": days, "items": items})


@endpoint(methods=("GET",))
def record_distribution(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    field = opt_str(request, "field", "status").strip() or "status"
    if field not in ("status", "category", "priority", "owner"):
        raise ValueError("field 只支持 status/category/priority/owner")

    base = _module_qs(request.user, mod)
    total = base.count()
    items = []
    if field == "status":
        counts = dict(base.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        for s in mod["statuses"]:
            items.append({"key": s["key"], "label": s["label"], "count": counts.get(s["key"], 0)})
    elif field == "category":
        counts = dict(base.values_list("category").annotate(c=Count("id")).values_list("category", "c"))
        for key, count in sorted(counts.items(), key=lambda x: -x[1]):
            label = key or "未分类"
            items.append({"key": key or "", "label": label, "count": count})
    elif field == "priority":
        counts = dict(base.values_list("priority").annotate(c=Count("id")).values_list("priority", "c"))
        for key in PRIORITIES:
            items.append({"key": key, "label": PRIORITY_LABELS[key], "count": counts.get(key, 0)})
    else:
        from accounts.models import User

        counts = dict(
            base.values("owner_id").annotate(c=Count("id")).values_list("owner_id", "c")
        )
        owners = {
            u.pk: _user_brief(u)
            for u in User.objects.filter(pk__in=[k for k in counts if k is not None])
        }
        for uid, count in sorted(counts.items(), key=lambda x: -x[1]):
            brief = owners.get(uid)
            if brief is None:
                items.append({"key": "", "label": "未指派", "count": count})
            else:
                items.append(
                    {"key": str(uid), "label": brief["name"], "count": count}
                )
    for item in items:
        item["percent"] = round(item["count"] * 100.0 / total, 1) if total else 0
    return ok({"field": field, "items": items})


@endpoint(methods=("GET",))
def record_overdue(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    today = timezone.localdate()
    qs = (
        _module_qs(request.user, mod, include_archived=False)
        .filter(due_date__lt=today)
        .exclude(status__in=_done_keys(mod))
        .select_related("owner", "department", "created_by")
        .order_by("due_date", "id")
    )
    total = qs.count()
    items = list(qs[:200])
    favs = _favorite_ids(request.user, [r.pk for r in items])
    return ok(
        {
            "count": total,
            "results": [_rec_dict(r, request.user, favs) for r in items],
        }
    )


@endpoint(methods=("GET",))
def record_quality(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    base = _module_qs(request.user, mod, include_archived=False)
    checked = base.count()
    now = timezone.now()

    dup_titles = list(
        base.values("title")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
        .values_list("title", flat=True)[:200]
    )
    dup_qs = base.filter(title__in=dup_titles)

    specs = [
        ("missing_owner", "缺少负责人", base.filter(owner__isnull=True)),
        ("missing_due", "缺少到期日", base.filter(due_date__isnull=True)),
        ("missing_category", "缺少分类", base.filter(category="")),
        ("duplicate_title", "标题重复", dup_qs),
        ("stale_90d", "超过 90 天未更新", base.filter(updated_at__lt=now - timedelta(days=90))),
    ]
    issues = []
    for key, label, qs in specs:
        ids = list(qs.values_list("id", flat=True)[:50])
        issues.append(
            {"key": key, "label": label, "count": qs.count(), "sample_ids": ids[:5]}
        )
    # 样本只取了前 50 条，缺陷比例按全量计数估算（更稳定）
    issue_total = sum(i["count"] for i in issues)
    score = round(100.0, 1) if not checked else round(
        max(0.0, 100.0 - issue_total * 100.0 / checked), 1
    )
    return ok({"score": score, "issues": issues, "checked": checked})


# ---------------------------------------------------------------------------
# 19 合并
# ---------------------------------------------------------------------------


@endpoint(methods=("POST",))
def record_merge(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    payload = _body(request)
    ids = _int_ids(payload.get("ids"), limit=200, minimum=2)
    recs = list(
        BizRecord.objects.select_related("owner", "department", "created_by").filter(
            module=mod["slug"], pk__in=ids
        )
    )
    if len(recs) != len(ids):
        return fail("部分记录不存在或不属于该模块", status=404)
    for rec in recs:
        if not _can_edit(request.user, rec):
            return fail(f"无权合并记录 {rec.pk}", status=403)

    primary_id = payload.get("primary_id")
    primary = None
    if primary_id not in (None, ""):
        pid = _int_param(primary_id, -1)
        primary = next((r for r in recs if r.pk == pid), None)
        if primary is None:
            raise ValueError("primary_id 必须是待合并记录之一")
    if primary is None:
        primary = recs[0]

    others = [r for r in recs if r.pk != primary.pk]
    merged_ids = list((primary.data or {}).get("merged_ids") or [])
    with transaction.atomic():
        for other in others:
            BizComment.objects.filter(record=other).update(record=primary)
            BizActivity.objects.filter(record=other).update(record=primary)
            other.data = {**(other.data or {}), "merged_into": primary.pk}
            other.is_deleted = True
            other.archived = True
            other.save(update_fields=["data", "is_deleted", "archived", "updated_at"])
            if other.pk not in merged_ids:
                merged_ids.append(other.pk)
        primary.data = {**(primary.data or {}), "merged_ids": merged_ids}
        primary.save(update_fields=["data", "updated_at"])
        _log(
            primary,
            request.user,
            "merge",
            {"primary_id": primary.pk, "merged_ids": [r.pk for r in others]},
        )
    return ok(_rec_dict(primary, request.user))


# ---------------------------------------------------------------------------
# 20 保存视图
# ---------------------------------------------------------------------------


def _view_dict(view, user):
    return {
        "id": view.pk,
        "module": view.module,
        "name": view.name,
        "params": view.params or {},
        "shared": bool(view.shared),
        "mine": view.user_id == getattr(user, "pk", None),
        "created_at": view.created_at.isoformat() if view.created_at else None,
    }


@endpoint(methods=("GET", "POST", "DELETE"))
def saved_views(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)

    if request.method == "GET":
        qs = (
            BizSavedView.objects.filter(module=mod["slug"])
            .filter(Q(user=request.user) | Q(shared=True))
            .order_by("-shared", "-created_at", "-id")[:200]
        )
        return ok({"total": len(qs), "items": [_view_dict(v, request.user) for v in qs]})

    if request.method == "DELETE":
        vid = request.query_params.get("id")
        if vid in (None, ""):
            vid = _body(request).get("id")
        if vid in (None, ""):
            raise ValueError("缺少必填参数: id")
        view = BizSavedView.objects.filter(
            pk=_int_param(vid, -1), module=mod["slug"], user=request.user
        ).first()
        if view is None:
            return fail("视图不存在", status=404)
        view.delete()
        return ok({"deleted": int(vid)})

    payload = _body(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("视图名不能为空")
    if len(name) > 80:
        raise ValueError("视图名不能超过 80 字符")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是 JSON 对象")
    shared = _truthy(payload.get("shared", False))
    view, _ = BizSavedView.objects.update_or_create(
        user=request.user,
        module=mod["slug"],
        name=name,
        defaults={"params": params, "shared": shared},
    )
    return ok(_view_dict(view, request.user))


# ---------------------------------------------------------------------------
# 21 订阅
# ---------------------------------------------------------------------------


def _sub_dict(sub):
    return {
        "enabled": bool(sub.enabled),
        "frequency": sub.frequency,
        "last_sent_at": sub.last_sent_at.isoformat() if sub.last_sent_at else None,
    }


@endpoint(methods=("GET", "POST"))
def subscription(request, slug):
    mod = _module(slug)
    if mod is None:
        return fail("模块不存在", status=404)
    if "subscription" not in mod["feature_keys"]:
        return fail("该模块不支持订阅", status=400)

    sub, _ = BizSubscription.objects.get_or_create(
        user=request.user,
        module=mod["slug"],
        defaults={"enabled": False, "frequency": "daily"},
    )
    if request.method == "POST":
        payload = _body(request)
        if "enabled" in payload:
            sub.enabled = _truthy(payload.get("enabled"))
        if "frequency" in payload:
            freq = str(payload.get("frequency") or "").strip().lower()
            if freq not in ("daily", "weekly"):
                raise ValueError("frequency 只支持 daily/weekly")
            sub.frequency = freq
        sub.save(update_fields=["enabled", "frequency"])
    return ok(_sub_dict(sub))
