# -*- coding: utf-8 -*-
"""officesuite 通用助手：对象渲染、可见性校验、状态机事件。"""
from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.scoping import can_write, is_visible

from devtools.common import fail, ok


def _is_admin(user) -> bool:
    """管理员通行：超管或 staff（数据范围再宽也不是写权限，见 scoping.py 注释）。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def _name_hit(user, name) -> bool:
    """展示名匹配：审批人/处理人字段存的是展示名，兼容 username/display_name。"""
    if not name:
        return False
    uid = getattr(user, "id", None)
    names = {getattr(user, "username", ""), getattr(user, "display_name", "")}
    names.discard("")
    return name in names


def _approver_policy(user, obj) -> bool:
    """审批流：owner + data.approver 指名 + 管理员。状态维度（pending 才可流转）
    由各视图自己校验，这里只做身份维度。"""
    if _is_admin(user):
        return True
    if obj.owner_id == getattr(user, "id", None):
        return True
    return _name_hit(user, (obj.data or {}).get("approver", ""))


def _assignee_policy(user, obj) -> bool:
    """工单：owner + 被指派人（assignee_name 展示名）+ 管理员。"""
    if _is_admin(user):
        return True
    if obj.owner_id == getattr(user, "id", None):
        return True
    return _name_hit(user, getattr(obj, "assignee_name", ""))


# S2-B1：按模型细化写策略（模型名 -> callable(user, obj) -> bool）。
# 未登记的模型仍走 core.scoping.can_write（owner-only，管理员在
# can_write_obj 里统一放行），行为与 S1 的严格写权限一致；
# 审批/工单这类「审批人、被指派人也要写」的对象在此登记。
WRITE_POLICIES = {
    "ApprovalRequest": _approver_policy,
    "SealApply": _approver_policy,
    "ExpenseReport": _approver_policy,
    "TravelApply": _approver_policy,
    "Contract": _approver_policy,
    "HelpTicket": _assignee_policy,
}


def can_write_obj(user, obj):
    """对象级写权限：管理员通行 → WRITE_POLICIES 定制 → owner 判定。"""
    if _is_admin(user):
        return True
    policy = WRITE_POLICIES.get(obj.__class__.__name__)
    if policy is not None:
        return bool(policy(user, obj))
    return can_write(user, obj)


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


def get_obj(model, pk, user, write=False):
    """取对象 + 行级可见性校验（core.scoping 收口）。

    :param write: True 表示该接口会修改对象，此时额外要求写权限。
        默认 False 保持既有读行为不变；写接口请显式传 write=True。
    """
    try:
        o = model.objects.get(pk=pk)
    except model.DoesNotExist:
        raise ValueError("对象不存在")
    if not is_visible(o, user):
        raise ValueError("无权访问该对象")
    if write and not can_write_obj(user, o):
        raise ValueError("无权修改该对象")
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
