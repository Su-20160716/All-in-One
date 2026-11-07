# -*- coding: utf-8 -*-
"""contracts · 统计接口（6 个）：概览 / 到期分布 / 金额汇总 / 风险分布 / 健康度 / 负责人负载。

统计口径：
- 全部基于「可见范围」的合同集合，不额外做权限判断（scope_queryset 已收口）；
- 合同数量小（单企业级通常 < 10 万），聚合在 Python 里做可读性更好；
  但涉及简单计数的都用 ORM aggregate，避免为了「一次遍历」把全表拉进内存；
- 所有金额输出字符串两位小数，与明细接口保持一致，前端不用区分类型。
"""
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_num, opt_str
from contracts import services
from contracts.common import iso, money_str
from contracts.models import (CONTRACT_STATUS_LABELS, CONTRACT_TYPE_LABELS,
                              RENEWAL_MODE_LABELS, RISK_LEVEL_LABELS,
                              Contract, ContractApproval,
                              ContractObligation, ContractReminder,
                              ContractRisk, ContractSignature,
                              ContractTemplate, to_decimal)

# 风险分档：与 services.score_risk 的等级边界保持一致（35/55/75）
RISK_BANDS = (
    ("low", 0, 34),
    ("medium", 35, 54),
    ("high", 55, 74),
    ("critical", 75, 100),
)


def _contracts(request):
    return scope_queryset(Contract.objects.all(), request.user).select_related(
        "owner", "responsible")


def _optional_status(request):
    """可选状态筛选：统计接口统一支持 status，但不强制。"""
    return opt_str(request, "status")


def _filtered(request):
    qs = _contracts(request)
    status = _optional_status(request)
    if status:
        qs = qs.filter(status=status)
    contract_type = opt_str(request, "contract_type")
    if contract_type:
        qs = qs.filter(contract_type=contract_type)
    return qs


@endpoint(("GET",))
def stats_overview(request):
    """合同概览：状态/类型/到期月份/负责人组合统计 + 待办类指标。"""
    qs = _filtered(request)
    today = timezone.localdate()
    portfolio = services.portfolio_stats(qs, today)
    contract_ids = list(qs.values_list("id", flat=True))
    obligations = ContractObligation.objects.filter(contract_id__in=contract_ids)
    overdue_obligations = obligations.filter(status="overdue").count()
    pending_obligations = obligations.filter(status__in=("pending", "doing")).count()
    due_7 = obligations.filter(status__in=("pending", "doing"),
                               due_date__gte=today,
                               due_date__lte=today + timedelta(days=7)).count()
    approvals_pending = ContractApproval.objects.filter(
        contract_id__in=contract_ids, decision="pending").count()
    signatures_pending = ContractSignature.objects.filter(
        contract_id__in=contract_ids, status="pending").count()
    risks_open = ContractRisk.objects.filter(
        contract_id__in=contract_ids).exclude(status__in=("closed", "accepted"))
    reminders_7 = ContractReminder.objects.filter(
        contract_id__in=contract_ids,
        created_at__gte=timezone.now() - timedelta(days=7)).count()
    return ok({
        **portfolio,
        "status_labels": {key: CONTRACT_STATUS_LABELS.get(key, key)
                          for key in portfolio["by_status"]},
        "type_labels": {key: CONTRACT_TYPE_LABELS.get(key, key)
                        for key in portfolio["by_type"]},
        "obligations": {"overdue": overdue_obligations,
                        "pending": pending_obligations,
                        "due_in_7_days": due_7},
        "approvals_pending": approvals_pending,
        "signatures_pending": signatures_pending,
        "risks": {"open": risks_open.count(),
                  "critical": risks_open.filter(level="critical").count(),
                  "high": risks_open.filter(level="high").count()},
        "reminders_last_7_days": reminders_7,
        "templates": ContractTemplate.objects.filter(owner=request.user).count(),
        "generated_at": iso(timezone.now()),
    })


@endpoint(("GET",))
def stats_expiry(request):
    """到期分布：区间桶（已到期/7/30/90 天内/更晚）+ 未来 12 个月 + 临期明细。"""
    qs = _filtered(request).exclude(status__in=("archived", "completed"))
    today = timezone.localdate()
    buckets = {"expired": 0, "d7": 0, "d30": 0, "d90": 0, "later": 0, "none": 0}
    months = {}
    near = []
    no_expire = 0
    for contract in qs[:5000]:
        bucket = contract.expiry_bucket(today)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        if not contract.expire_date:
            no_expire += 1
            continue
        days = contract.days_to_expiry(today)
        months[contract.expire_date.strftime("%Y-%m")] = (
            months.get(contract.expire_date.strftime("%Y-%m"), 0) + 1)
        if 0 <= days <= 30:
            near.append({
                "id": contract.id,
                "number": contract.number,
                "name": contract.name,
                "status": contract.status,
                "currency": contract.currency,
                "amount": money_str(contract.amount),
                "expire_date": iso(contract.expire_date),
                "days_to_expiry": days,
                "renewal_mode": contract.renewal_mode,
            })
    near.sort(key=lambda item: item["days_to_expiry"])
    return ok({
        "total": qs.count(),
        "buckets": buckets,
        "buckets_label": {"expired": "已到期", "d7": "7 天内", "d30": "30 天内",
                          "d90": "90 天内", "later": "90 天以上", "none": "未设到期日"},
        "by_month": dict(sorted(months.items())),
        "no_expire_date": no_expire,
        "near_expiry": near[:100],
        "near_expiry_count": len(near),
        "generated_at": iso(timezone.now()),
    })


@endpoint(("GET",))
def stats_amount(request):
    """金额汇总：合同总额/已付/未付/逾期（按币种），并按类型与状态拆分。"""
    qs = _filtered(request)
    summary = services.finance_summary(qs.prefetch_related("payments"))
    by_type = {}
    by_status = {}
    top = []
    for contract in qs[:2000]:
        type_key = contract.contract_type
        status_key = contract.status
        by_type.setdefault(type_key, {"count": 0, "amount": to_decimal(0)})
        by_status.setdefault(status_key, {"count": 0, "amount": to_decimal(0)})
        by_type[type_key]["count"] += 1
        by_type[type_key]["amount"] += to_decimal(contract.amount)
        by_status[status_key]["count"] += 1
        by_status[status_key]["amount"] += to_decimal(contract.amount)
        if to_decimal(contract.amount) > 0:
            top.append({"id": contract.id, "number": contract.number,
                        "name": contract.name,
                        "amount": money_str(contract.amount),
                        "currency": contract.currency,
                        "status": contract.status})
    top.sort(key=lambda item: -float(item["amount"]))
    return ok({
        **summary,
        "by_type": [{"contract_type": key,
                     "label": CONTRACT_TYPE_LABELS.get(key, key),
                     "count": value["count"],
                     "amount": f"{value['amount']:.2f}"}
                    for key, value in by_type.items()],
        "by_status": [{"status": key,
                       "label": CONTRACT_STATUS_LABELS.get(key, key),
                       "count": value["count"],
                       "amount": f"{value['amount']:.2f}"}
                      for key, value in by_status.items()],
        "top_contracts": top[:10],
        "generated_at": iso(timezone.now()),
    })


@endpoint(("GET",))
def stats_risk(request):
    """风险分布：合同风险分档 + 风险项等级分布 + 高风险合同清单。"""
    qs = _filtered(request)
    bands = {key: {"count": 0, "label": RISK_LEVEL_LABELS.get(key, key)}
             for key, _, _ in RISK_BANDS}
    risky = []
    for contract in qs.order_by("-risk_score")[:2000]:
        score = int(contract.risk_score or 0)
        for key, low, high in RISK_BANDS:
            if low <= score <= high:
                bands[key]["count"] += 1
                break
        if score >= 35:
            risky.append({"id": contract.id, "number": contract.number,
                          "name": contract.name,
                          "risk_score": score,
                          "status": contract.status,
                          "amount": money_str(contract.amount),
                          "currency": contract.currency})
    risky.sort(key=lambda item: -item["risk_score"])
    risk_ids = list(qs.values_list("id", flat=True))
    items = ContractRisk.objects.filter(contract_id__in=risk_ids)
    by_level = {row["level"]: row["count"] for row in
                items.values("level").annotate(count=Count("id")).order_by()}
    by_status = {row["status"]: row["count"] for row in
                 items.values("status").annotate(count=Count("id")).order_by()}
    keywords = []
    keyword_counter = {}
    for contract in qs.exclude(current_version__isnull=True)[:500]:
        for hit in services.scan_clause_keywords(
                contract.current_version.body_snapshot or ""):
            keyword_counter[hit["keyword"]] = (keyword_counter.get(hit["keyword"], 0)
                                               + hit["count"])
    for word, count in sorted(keyword_counter.items(), key=lambda kv: -kv[1]):
        keywords.append({"keyword": word, "count": count})
    average = (round(sum(int(row.risk_score or 0) for row in qs) / qs.count(), 1)
               if qs.count() else 0.0)
    return ok({
        "total": qs.count(),
        "avg_score": average,
        "bands": bands,
        "risk_items": {"total": items.count(),
                       "open": items.exclude(status__in=("closed", "accepted")).count(),
                       "by_level": by_level,
                       "by_status": by_status},
        "high_risk_contracts": risky[:20],
        "clause_keywords": keywords[:20],
        "generated_at": iso(timezone.now()),
    })


@endpoint(("GET",))
def stats_health(request):
    """履约健康度：逐合同打分（义务准时/里程碑达成/付款及时）并给出整体均值。"""
    qs = _filtered(request).filter(status__in=("active", "expiring", "expired"))
    limit = int(opt_num(request, "limit", 50, minimum=1, maximum=200, integer=True))
    today = timezone.localdate()
    rows = []
    for contract in qs.prefetch_related("obligations__events", "milestones",
                                        "payments").order_by("expire_date")[:limit]:
        result = services.health_score(contract, today)
        rows.append({
            "contract_id": contract.id,
            "number": contract.number,
            "name": contract.name,
            "status": contract.status,
            "expire_date": iso(contract.expire_date),
            "score": result["score"],
            "level": result["level"],
            "obligations": result["components"]["obligations"],
            "milestones": result["components"]["milestones"],
            "payments": result["components"]["payments"],
        })
    rows.sort(key=lambda item: item["score"])
    average = round(sum(row["score"] for row in rows) / len(rows), 1) if rows else 0.0
    distribution = {"excellent": 0, "good": 0, "warning": 0, "critical": 0}
    for row in rows:
        distribution[row["level"]] = distribution.get(row["level"], 0) + 1
    return ok({
        "scored": len(rows),
        "average_score": average,
        "distribution": distribution,
        "worst": rows[:10],
        "items": rows,
        "generated_at": iso(timezone.now()),
    })


@endpoint(("GET",))
def stats_owner_load(request):
    """负责人负载：合同数/金额/逾期义务/待审批节点，按负载分排序。

    负载分 = 履行中合同数 × 2 + 逾期义务 × 3 + 待审批 × 1，
    只用于排序提示，不作为考核口径（写进文档避免被误用）。
    """
    qs = _filtered(request)
    today = timezone.localdate()
    owners = {}
    for contract in qs[:5000]:
        user = contract.responsible or contract.owner
        key = getattr(user, "id", 0)
        row = owners.setdefault(key, {
            "owner_id": key,
            "owner": getattr(user, "username", ""),
            "nickname": getattr(user, "nickname", "") or getattr(user, "username", ""),
            "contracts": 0,
            "active_contracts": 0,
            "amount": to_decimal(0),
            "overdue_obligations": 0,
            "pending_approvals": 0,
            "expiring_30d": 0,
        })
        row["contracts"] += 1
        row["amount"] += to_decimal(contract.amount)
        if contract.status in ("active", "expiring"):
            row["active_contracts"] += 1
        days = contract.days_to_expiry(today)
        if days is not None and 0 <= days <= 30:
            row["expiring_30d"] += 1
    owner_ids = list(owners.keys())
    overdue = (ContractObligation.objects
               .filter(contract__in=qs, status="overdue")
               .values("responsible_id")
               .annotate(count=Count("id")).order_by())
    for row in overdue:
        key = row["responsible_id"] or 0
        if key in owners:
            owners[key]["overdue_obligations"] = row["count"]
    pending = (ContractApproval.objects
               .filter(contract__in=qs, decision="pending")
               .values("contract__responsible_id")
               .annotate(count=Count("id")).order_by())
    for row in pending:
        key = row["contract__responsible_id"] or 0
        if key in owners:
            owners[key]["pending_approvals"] = row["count"]
    result = []
    for row in owners.values():
        load = row["active_contracts"] * 2 + row["overdue_obligations"] * 3 \
            + row["pending_approvals"]
        result.append({**row, "amount": f"{row['amount']:.2f}", "load_score": load})
    result.sort(key=lambda item: -item["load_score"])
    return ok({"items": result, "count": len(result),
               "owner_filter": owner_ids[:1], "generated_at": iso(timezone.now()),
               "formula": "履行中合同×2 + 逾期义务×3 + 待审批×1"})


# ---------------------------------------------------------------------------
# 续约窗口
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def stats_renewal_window(request):
    """续约窗口：未来 N 天按 7/30/60/90 天分档，输出处置建议与自动续约数量。"""
    days = int(opt_num(request, "days", 90, minimum=1, maximum=365,
                       integer=True))
    qs = _filtered(request).select_related("owner")
    result = services.renewal_window(qs, timezone.localdate(), days)
    for item in result["items"]:
        item["expire_date"] = iso(item["expire_date"])
        item["renewal_mode_label"] = RENEWAL_MODE_LABELS.get(
            item["renewal_mode"], item["renewal_mode"])
    return ok(result)
