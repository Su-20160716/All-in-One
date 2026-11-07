# -*- coding: utf-8 -*-
"""风险接口：风险 CRUD + 矩阵 + 重新评分 + 处置 CRUD + 完成处置。

评分规则（见 governance.services）：
    固有风险 = 可能性 × 影响（各 1..5）
    剩余风险 = 固有风险 × 控制有效性系数（有效性 0% → 不消减，100% → 完全消减）
    等级     = 按用户可配置的分档（默认 1-4 低 / 5-9 中 / 10-14 高 / 15-25 严重）

任何改变可能性、影响或有效性的写操作都会在同一事务内重新评分，
避免出现「列表里显示低风险、详情页算出高风险」的口径错位。
"""
from django.db import transaction

from devtools.common import endpoint, ok, p

from governance import services
from governance.models import (
    RISK_LEVELS,
    RISK_STATUS,
    TREATMENT_STATUS,
    TREATMENT_STRATEGIES,
    Risk,
    RiskTreatment,
)
from governance.views_common import (
    apply_search,
    filter_choice,
    filter_int,
    get_risk,
    get_treatment,
    paginate,
    param_choice,
    param_date,
    param_int,
    param_str,
    param_text,
    scoped,
)

RISK_SEARCH_FIELDS = ("code", "name", "category", "description", "owner_name")


@endpoint(("GET",))
def risk_list(request):
    """风险列表：按等级/状态/类别筛选，默认剩余风险分倒序。"""
    qs = scoped(Risk, request.user)
    qs = apply_search(qs, request, RISK_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "level", RISK_LEVELS)
    category = param_str(request, "category", max_len=60)
    if category:
        qs = qs.filter(category=category)
    min_score = param_int(request, "min_residual", default=None, minimum=1, maximum=25)
    if min_score is not None:
        qs = qs.filter(residual_score__gte=min_score)
    return paginate(qs.order_by("-residual_score", "-created_at"), request)


@endpoint()
def risk_create(request):
    """新建风险：自动编号并在事务内完成首次评分。"""
    name = param_str(request, "name", required=True, max_len=200)
    code = param_str(request, "code", max_len=40) or services.next_code(
        Risk, request.user, "RSK")
    if Risk.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("该风险编号已存在")
    likelihood = param_int(request, "likelihood", default=3, minimum=1, maximum=5)
    impact = param_int(request, "impact", default=3, minimum=1, maximum=5)
    effectiveness = param_int(request, "effectiveness", default=0, minimum=0, maximum=100)
    with transaction.atomic():
        risk = Risk.objects.create(
            owner=request.user,
            code=code,
            name=name,
            category=param_str(request, "category", default="通用", max_len=60),
            description=param_text(request, "description"),
            likelihood=likelihood,
            impact=impact,
            effectiveness=effectiveness,
            status=param_choice(request, "status", RISK_STATUS, default="identified"),
            owner_name=param_str(request, "owner_name", max_len=80),
            review_on=param_date(request, "review_on"),
            treatment_plan=param_text(request, "treatment_plan"),
        )
        services.rescore(risk)
    return ok(risk.to_dict())


@endpoint(("GET",))
def risk_detail(request, pk):
    """风险详情：含处置清单与评分明细。"""
    risk = get_risk(pk, request.user)
    data = risk.to_dict()
    treatments = list(risk.treatments.all())
    data["treatments"] = [t.to_dict() for t in treatments]
    band = services.band_for_score(risk.residual_score, owner=risk.owner)
    data["score_detail"] = {
        "likelihood": risk.likelihood,
        "impact": risk.impact,
        "inherent_score": risk.inherent_score,
        "residual_score": risk.residual_score,
        "coefficient": services.effectiveness_coefficient(risk.effectiveness),
        "band": band,
        "open_treatments": sum(1 for t in treatments
                               if t.status in ("planned", "in_progress")),
    }
    return ok(data)


@endpoint()
def risk_update(request, pk):
    """更新风险；可能性/影响/有效性变化时同事务重算分值。"""
    risk = get_risk(pk, request.user, write=True)
    code = param_str(request, "code", default=risk.code, max_len=40)
    if code != risk.code and Risk.objects.filter(owner=risk.owner, code=code).exists():
        raise ValueError("该风险编号已存在")
    likelihood = param_int(request, "likelihood", default=risk.likelihood, minimum=1, maximum=5)
    impact = param_int(request, "impact", default=risk.impact, minimum=1, maximum=5)
    effectiveness = param_int(request, "effectiveness", default=risk.effectiveness,
                              minimum=0, maximum=100)
    with transaction.atomic():
        risk.code = code
        risk.name = param_str(request, "name", default=risk.name, max_len=200)
        risk.category = param_str(request, "category", default=risk.category, max_len=60)
        risk.description = param_text(request, "description", default=risk.description)
        risk.status = param_choice(request, "status", RISK_STATUS, default=risk.status)
        risk.owner_name = param_str(request, "owner_name", default=risk.owner_name, max_len=80)
        risk.review_on = param_date(request, "review_on") or risk.review_on
        risk.treatment_plan = param_text(request, "treatment_plan",
                                         default=risk.treatment_plan)
        services.rescore(risk, effectiveness=effectiveness)
    return ok(risk.to_dict())


@endpoint()
def risk_delete(request, pk):
    """删除风险（处置记录级联删除；处理活动关联自动解除）。"""
    risk = get_risk(pk, request.user, write=True)
    with transaction.atomic():
        risk.delete()
    return ok({"id": pk, "deleted": True})


@endpoint(("GET",))
def risk_matrix(request):
    """风险矩阵：5×5 分档、格子落位与当前风险分布。"""
    return ok(services.risk_matrix(request.user))


@endpoint()
def risk_rescore(request, pk):
    """重新评分：可传入新的控制有效性（0..100），其余沿用现值。"""
    risk = get_risk(pk, request.user, write=True)
    effectiveness = param_int(request, "effectiveness", default=None, minimum=0, maximum=100)
    with transaction.atomic():
        result = services.rescore(risk, effectiveness=effectiveness)
    return ok({"risk": risk.to_dict(), "scoring": result})


@endpoint(("GET",))
def risk_treatments(request, pk):
    """风险处置列表（按风险聚合）。"""
    risk = get_risk(pk, request.user)
    return paginate(risk.treatments.all().order_by("-created_at"), request)


@endpoint()
def risk_treatment_create(request):
    """新增处置：策略为接受（accept）时必须写明理由。"""
    risk_id = param_int(request, "risk_id", required=True, minimum=1)
    risk = get_risk(risk_id, request.user, write=True)
    strategy = param_choice(request, "strategy", TREATMENT_STRATEGIES, default="mitigate")
    action = param_text(request, "action")
    if strategy == "accept" and not action.strip():
        raise ValueError("策略为接受时必须写明接受理由")
    with transaction.atomic():
        treatment = RiskTreatment.objects.create(
            owner=request.user,
            risk=risk,
            strategy=strategy,
            action=action,
            owner_name=param_str(request, "owner_name", max_len=80),
            due_on=param_date(request, "due_on"),
            status=param_choice(request, "status", TREATMENT_STATUS, default="planned"),
        )
        if risk.status == "identified":
            risk.status = "treating"
            risk.save(update_fields=["status", "updated_at"])
    return ok(treatment.to_dict())


@endpoint(("GET",))
def risk_treatment_detail(request, pk):
    """处置详情。"""
    treatment = get_treatment(pk, request.user)
    return ok(treatment.to_dict())


@endpoint()
def risk_treatment_update(request, pk):
    """更新处置（策略/行动/负责人/截止/状态）。"""
    treatment = get_treatment(pk, request.user, write=True)
    strategy = param_choice(request, "strategy", TREATMENT_STRATEGIES,
                            default=treatment.strategy)
    action = param_text(request, "action", default=treatment.action)
    if strategy == "accept" and not action.strip():
        raise ValueError("策略为接受时必须写明接受理由")
    treatment.strategy = strategy
    treatment.action = action
    treatment.owner_name = param_str(request, "owner_name", default=treatment.owner_name, max_len=80)
    treatment.due_on = param_date(request, "due_on") or treatment.due_on
    treatment.status = param_choice(request, "status", TREATMENT_STATUS, default=treatment.status)
    if treatment.status == "done" and treatment.completed_on is None:
        treatment.completed_on = services.today()
    treatment.save()
    return ok(treatment.to_dict())


@endpoint()
def risk_treatment_complete(request, pk):
    """完成处置：置 done 并回填完成日；全部完成后风险转为监控中。"""
    treatment = get_treatment(pk, request.user, write=True)
    if treatment.status == "done":
        return ok({"treatment": treatment.to_dict(), "changed": False,
                   "reason": "已完成"})
    with transaction.atomic():
        treatment.status = "done"
        treatment.completed_on = param_date(request, "completed_on") or services.today()
        treatment.save(update_fields=["status", "completed_on", "updated_at"])
        risk = treatment.risk
        open_left = risk.treatments.exclude(status__in=("done", "cancelled")).count()
        if open_left == 0 and risk.status in ("identified", "treating"):
            # 处置全部完成后进入监控态：风险并未消失，只是进入持续观察，
            # 直接关闭会丢失复核节奏。
            risk.status = "monitored"
            risk.save(update_fields=["status", "updated_at"])
    return ok({"treatment": treatment.to_dict(), "changed": True,
               "risk_status": treatment.risk.status})
