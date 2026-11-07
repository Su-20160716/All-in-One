# -*- coding: utf-8 -*-
"""contracts 状态机：合同主状态、变更单、审批节点、付款期次的合法流转。

为什么要单独一个模块：
- 状态机是合同域唯一「不能靠调用方自律」的规则，散落在视图里必然出现
  「某个接口忘了校验」的越权流转；集中定义 + 断言函数是唯一可靠做法。
- 状态流转同时要落审计（from/to + 动作 + 操作人），把「校验」和「记录」
  放在一处，视图只需调用 transition()。
"""
from django.utils import timezone

from contracts.models import (AMENDMENT_STATUS, CONTRACT_STATUS,
                              CONTRACT_STATUS_LABELS, ContractAudit)

# 允许的流转：键是当前状态，值是可去往的状态集合。
# 几处刻意的取舍：
# 1) reviewing 允许退回 draft（驳回后需要改稿再提交），但不允许直接 active；
# 2) signing 只能去 active 或 terminated：签署中的合同不能跳过生效去履约；
# 3) expired 允许回到 active：续约确认后由服务层走 reactivate，历史数据也可修正；
# 4) archived 是终态，任何回流都要显式走「恢复」而非顺手改字段。
CONTRACT_TRANSITIONS = {
    "draft": {"reviewing", "archived"},
    "reviewing": {"approved", "draft", "archived"},
    "approved": {"signing", "archived"},
    "signing": {"active", "terminated"},
    "active": {"expiring", "terminated", "completed", "expired"},
    "expiring": {"active", "terminated", "completed", "expired"},
    "expired": {"completed", "archived", "active"},
    "terminated": {"archived"},
    "completed": {"archived"},
    "archived": set(),
}

# 每个动作隐含的目标状态与允许的来源状态（比裸状态对更贴近接口语义）
ACTION_TARGETS = {
    "submit": ("reviewing", {"draft"}),
    "approve": ("approved", {"reviewing"}),
    "reject": ("draft", {"reviewing"}),
    "sign": ("signing", {"approved"}),
    "activate": ("active", {"signing"}),
    "terminate": ("terminated", {"signing", "active", "expiring"}),
    "complete": ("completed", {"active", "expiring", "expired"}),
    "archive": ("archived", {"draft", "reviewing", "approved", "expired",
                             "terminated", "completed"}),
    "expire": ("expired", {"active", "expiring"}),
    "mark_expiring": ("expiring", {"active", "expiring"}),
    "reactivate": ("active", {"expired"}),
}

ACTION_LABELS = {
    "submit": "提交审批",
    "approve": "审批通过",
    "reject": "审批驳回",
    "sign": "发起签署",
    "activate": "合同生效",
    "terminate": "终止合同",
    "complete": "完成合同",
    "archive": "归档合同",
    "expire": "标记到期",
    "mark_expiring": "标记临期",
    "reactivate": "恢复履行",
}

# 变更单流转：草稿 → 待审 → 批准/驳回 → 生效
AMENDMENT_TRANSITIONS = {
    "draft": {"submitted", "rejected"},
    "submitted": {"approved", "rejected"},
    "approved": {"effective"},
    "rejected": {"draft"},
    "effective": set(),
}

# 审批节点结论只允许单次落定（pending → approved/rejected/skipped）
APPROVAL_DECISIONS_FLOW = {
    "pending": {"approved", "rejected", "skipped"},
    "approved": set(),
    "rejected": set(),
    "skipped": set(),
}


class TransitionError(ValueError):
    """非法流转：继承 ValueError，让 @endpoint 统一转成 400 中文提示。"""


def status_label(status):
    """状态中文名：错误提示里直接给中文，避免前端把英文码透给业务方。"""
    return CONTRACT_STATUS_LABELS.get(status, status)


def assert_action_allowed(contract, action):
    """校验动作在当前状态下是否合法，返回目标状态。

    错误提示包含「当前状态」与「允许的下一步」，让调用方一次就能改对。
    """
    if action not in ACTION_TARGETS:
        raise TransitionError(f"不支持的动作: {action}")
    target, sources = ACTION_TARGETS[action]
    if contract.status not in sources:
        label = ACTION_LABELS.get(action, action)
        allowed = "、".join(status_label(s) for s in sorted(sources)) or "无"
        raise TransitionError(
            f"当前状态「{status_label(contract.status)}」不能{label}（仅允许：{allowed}）")
    return target


def assert_transition(contract, target):
    """按状态对校验流转（给需要直接置状态的场景用，如扫描标记到期）。"""
    if target not in CONTRACT_STATUS:
        raise TransitionError(f"未知状态: {target}")
    allowed = CONTRACT_TRANSITIONS.get(contract.status, set())
    if target not in allowed and target != contract.status:
        raise TransitionError(
            f"合同状态不能从「{status_label(contract.status)}」变为「{status_label(target)}」")
    return target


def transition(contract, action, user=None, note="", payload=None, extra_fields=()):
    """执行一次合法流转：改状态 + 落审计 + 保存。

    调用方必须已确认写权限（视图层 can_write/get_owned），这里只负责状态与审计。
    事务由调用方保证（多表写入统一 transaction.atomic()）。
    """
    target = assert_action_allowed(contract, action)
    before = contract.status
    contract.status = target
    contract.touch()
    fields = ["status", "updated_at", *extra_fields]
    contract.save(update_fields=fields)
    log_transition(contract, action, user, note, before, target, payload)
    return contract


def force_status(contract, target, user=None, note="", payload=None,
                 extra_fields=(), action="update"):
    """带状态对校验的强制置位（到期/临期扫描用，语义与 transition 区分开）。"""
    assert_transition(contract, target)
    before = contract.status
    contract.status = target
    contract.touch()
    contract.save(update_fields=["status", "updated_at", *extra_fields])
    log_transition(contract, action, user, note, before, target, payload)
    return contract


def log_transition(contract, action, user, note, before, after, payload=None):
    """追加审计：追加型日志，不提供修改/删除入口。"""
    return ContractAudit.objects.create(
        owner=user if getattr(user, "pk", None) else contract.owner,
        contract=contract,
        action=action,
        from_status=before or "",
        to_status=after or "",
        note=note or "",
        actor=user if getattr(user, "pk", None) else None,
        payload=payload or {},
    )


def assert_amendment_transition(amendment, target):
    """变更单流转校验：approved 之后才能生效，跳步直接报错。"""
    if target not in AMENDMENT_STATUS:
        raise TransitionError(f"未知变更状态: {target}")
    allowed = AMENDMENT_TRANSITIONS.get(amendment.approval_status, set())
    if target not in allowed:
        raise TransitionError(
            f"变更单不能从「{amendment.approval_status}」变为「{target}」")
    return target


def assert_approval_decision(approval, decision):
    """审批节点结论校验：同一个节点不能既通过又驳回。"""
    if decision not in APPROVAL_DECISIONS_FLOW:
        raise TransitionError(f"未知审批结论: {decision}")
    allowed = APPROVAL_DECISIONS_FLOW.get(approval.decision, set())
    if decision not in allowed:
        raise TransitionError(
            f"审批节点「{approval.node_name}」当前为 {approval.decision}，不可重复裁决")
    return decision


def next_pending_approval(contract):
    """取下一个待办节点（按 node 升序）；全部落定时返回 None。"""
    return (contract.approvals.filter(decision="pending")
            .order_by("node").first())


def approvals_summary(contract):
    """审批进度摘要：前端进度条直接用，避免每次都拉全量节点自己算。"""
    rows = list(contract.approvals.all().order_by("node"))
    total = len(rows)
    done = sum(1 for row in rows if row.decision in ("approved", "skipped"))
    rejected = sum(1 for row in rows if row.decision == "rejected")
    pending = sum(1 for row in rows if row.decision == "pending")
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "rejected": rejected,
        "progress_pct": round(done * 100.0 / total, 1) if total else 0.0,
        "next_node": next_pending_approval(contract).node_name
        if pending and not rejected else "",
    }


def touch_contract(contract, user=None, note="", action="update", payload=None):
    """无状态变化但要留痕的动作（付款、续约、风险重算）。"""
    contract.touch()
    contract.save(update_fields=["updated_at"])
    log_transition(contract, action, user, note, contract.status, contract.status,
                   payload)
    return contract


def now():
    """统一时间源，测试里可 monkeypatch contracts.state.now 固定时钟。"""
    return timezone.now()
