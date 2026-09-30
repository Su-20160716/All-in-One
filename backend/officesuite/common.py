# -*- coding: utf-8 -*-
"""officesuite 通用助手：对象渲染、可见性校验、状态机事件。"""
from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.scoping import is_visible

from devtools.common import fail, ok


def obj_dict(o, extra=(), owner_name=None):
    """统一渲染为 dict：id/title/status/remark/时间 + 指定字段。"""
    d = {
        "id": o.pk,
        "title": o.title,
        "status": o.status,
        "remark": o.remark,
        "data": o.data,
        "created_at": o.created_at.isoformat() if getattr(o, "created_at", None) else None,
        "updated_at": o.updated_at.isoformat() if getattr(o, "updated_at", None) else None,
    }
    if owner_name or getattr(o, "owner", None) is not None:
        u = getattr(o, "owner", None)
        d["owner"] = owner_name or (u.username if u and u.pk else "")
        d["owner_id"] = u.pk if u and u.pk else None
    for f in extra:
        v = getattr(o, f, None)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        elif hasattr(v, "pk"):
            v = v.pk
        d[f] = v
    return d


def get_obj(model, pk, user, allow_owner=True):
    """取对象 + 行级可见性校验（core.scoping 收口）。"""
    try:
        o = model.objects.get(pk=pk)
    except model.DoesNotExist:
        raise ValueError("对象不存在")
    if not is_visible(o, user):
        raise ValueError("无权访问该对象")
    return o


def flow_event(obj, action, user, note=""):
    """把流转动作写进 data.events（轻量审计，不额外建表）。"""
    events = list((obj.data or {}).get("events", []))
    events.append({"action": action, "by": getattr(user, "username", "system"),
                   "note": note, "at": timezone.now().isoformat()})
    obj.data = {**(obj.data or {}), "events": events[-100:]}


def parse_dt(s, field="时间", allow_empty=False, default=None):
    """字符串 → aware datetime；支持 YYYY-MM-DD[ HH:MM[:SS]]。"""
    if not s:
        if allow_empty:
            return default
        raise ValueError(f"{field} 不能为空")
    dt = parse_datetime(str(s))
    if dt is None:
        d = parse_date(str(s))
        if d is None:
            raise ValueError(f"{field} 需为 YYYY-MM-DD[ HH:MM[:SS]]")
        dt = datetime.combine(d, time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def parse_day(s, field="日期", allow_empty=True, default=None):
    """字符串 → date（缺省可空）。"""
    if not s:
        if allow_empty:
            return default
        raise ValueError(f"{field} 不能为空")
    d = parse_date(str(s))
    if d is None:
        raise ValueError(f"{field} 需为 YYYY-MM-DD")
    return d
