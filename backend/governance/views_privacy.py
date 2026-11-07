# -*- coding: utf-8 -*-
"""隐私域接口：数据资产（分类分级）与数据处理活动（ROPA / DPIA）。

数据资产与处理活动是隐私合规的两条主线：
- 资产台账回答「数据在哪里、属于什么级别、保留多久」；
- 处理活动回答「为什么处理、依据什么法律基础、是否跨境、是否做过 DPIA」。

两者都不存明细数据本身，只存治理元数据；资产保留期由 DataAsset.retention_days
与 RetentionRule 共同决定，扫描逻辑在 governance.services 中统一实现。
"""
from django.db import transaction
from django.db.models import Count

from devtools.common import endpoint, ok

from governance import services
from governance.models import (
    DATA_ASSET_KINDS,
    DATA_CLASSIFICATIONS,
    PROCESSING_STATUS,
    DataAsset,
    ProcessingActivity,
)
from governance.views_common import (
    apply_search,
    filter_bool,
    filter_choice,
    get_data_asset,
    get_processing,
    get_risk,
    paginate,
    param_bool,
    param_choice,
    param_date,
    param_int,
    param_list,
    param_str,
    param_text,
    scoped,
)

ASSET_SEARCH_FIELDS = ("name", "owner_name", "storage_location", "description")
PROCESSING_SEARCH_FIELDS = ("name", "purpose", "legal_basis", "recipients")


@endpoint(("GET",))
def data_asset_list(request):
    """数据资产列表：按类型/分级/是否含个人信息筛选。"""
    qs = scoped(DataAsset, request.user)
    qs = apply_search(qs, request, ASSET_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "kind", DATA_ASSET_KINDS)
    qs = filter_choice(qs, request, "classification", DATA_CLASSIFICATIONS)
    qs = filter_bool(qs, request, "contains_pii")
    return paginate(qs.order_by("-created_at"), request)


@endpoint()
def data_asset_create(request):
    """登记数据资产（保留天数 0 表示不自动到期）。"""
    asset = DataAsset.objects.create(
        owner=request.user,
        name=param_str(request, "name", required=True, max_len=200),
        kind=param_choice(request, "kind", DATA_ASSET_KINDS, default="operational"),
        classification=param_choice(request, "classification", DATA_CLASSIFICATIONS,
                                    default="internal"),
        owner_name=param_str(request, "owner_name", max_len=80),
        storage_location=param_str(request, "storage_location", max_len=200),
        retention_days=param_int(request, "retention_days", default=0, minimum=0,
                                 maximum=36500),
        contains_pii=bool(param_bool(request, "contains_pii", False)),
        status=param_choice(request, "status", ("active", "archived", "anonymized", "deleted"),
                            default="active"),
        description=param_text(request, "description"),
    )
    return ok(asset.to_dict())


@endpoint(("GET",))
def data_asset_detail(request, pk):
    """资产详情：保留到期日、关联保留动作与处理活动提示。"""
    asset = get_data_asset(pk, request.user)
    data = asset.to_dict()
    data["retention_actions"] = [a.to_dict() for a in
                                 asset.owner.gov_retention_actions.filter(
                                     resource_kind="data_asset", resource_id=asset.pk)]
    data["retention_due_on"] = services.as_iso(asset.retention_due_on())
    return ok(data)


@endpoint()
def data_asset_update(request, pk):
    """更新数据资产（分级/保留天数/存储位置等）。"""
    asset = get_data_asset(pk, request.user, write=True)
    asset.name = param_str(request, "name", default=asset.name, max_len=200)
    asset.kind = param_choice(request, "kind", DATA_ASSET_KINDS, default=asset.kind)
    asset.classification = param_choice(request, "classification", DATA_CLASSIFICATIONS,
                                        default=asset.classification)
    asset.owner_name = param_str(request, "owner_name", default=asset.owner_name, max_len=80)
    asset.storage_location = param_str(request, "storage_location",
                                       default=asset.storage_location, max_len=200)
    asset.retention_days = param_int(request, "retention_days", default=asset.retention_days,
                                     minimum=0, maximum=36500)
    pii = param_bool(request, "contains_pii", None)
    if pii is not None:
        asset.contains_pii = pii
    asset.status = param_choice(request, "status",
                                ("active", "archived", "anonymized", "deleted"),
                                default=asset.status)
    asset.description = param_text(request, "description", default=asset.description)
    asset.save()
    return ok(asset.to_dict())


@endpoint()
def data_asset_delete(request, pk):
    """删除数据资产（保留动作台账保留，作为历史记录）。"""
    asset = get_data_asset(pk, request.user, write=True)
    with transaction.atomic():
        asset.delete()
    return ok({"id": pk, "deleted": True})


@endpoint(("GET",))
def data_asset_classification(request):
    """分类分级统计：按分级/类型计数、PII 占比与最敏感的资产清单。"""
    qs = DataAsset.objects.filter(owner=request.user)
    total = qs.count()
    by_classification = {row["classification"]: row["count"] for row in
                         qs.values("classification").annotate(count=Count("id"))}
    by_kind = {row["kind"]: row["count"] for row in
               qs.values("kind").annotate(count=Count("id"))}
    pii = qs.filter(contains_pii=True).count()
    restricted = list(qs.filter(classification="restricted").order_by("-created_at")[:20])
    no_retention = qs.filter(retention_days=0).count()
    return ok({
        "total": total,
        "by_classification": {level: by_classification.get(level, 0)
                              for level in DATA_CLASSIFICATIONS},
        "by_kind": {kind: by_kind.get(kind, 0) for kind in DATA_ASSET_KINDS},
        "contains_pii": pii,
        "pii_ratio": services.pct(pii, total),
        "restricted_items": [asset.to_dict() for asset in restricted],
        "without_retention_policy": no_retention,
    })


# ---------------------------------------------------------------------------
# 处理活动
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def processing_list(request):
    """处理活动列表：按状态/跨境/DPIA 完成情况筛选。"""
    qs = scoped(ProcessingActivity, request.user)
    qs = apply_search(qs, request, PROCESSING_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "status", PROCESSING_STATUS)
    qs = filter_bool(qs, request, "cross_border")
    qs = filter_bool(qs, request, "dpia_done")
    return paginate(qs.annotate(risk_total=Count("risks")).order_by("-created_at"), request)


@endpoint()
def processing_create(request):
    """新建处理活动（数据类别/主体类别为字符串数组）。"""
    activity = ProcessingActivity.objects.create(
        owner=request.user,
        name=param_str(request, "name", required=True, max_len=200),
        purpose=param_text(request, "purpose"),
        legal_basis=param_str(request, "legal_basis", max_len=120),
        data_categories=param_list(request, "data_categories"),
        subject_categories=param_list(request, "subject_categories"),
        recipients=param_text(request, "recipients"),
        cross_border=bool(param_bool(request, "cross_border", False)),
        retention_period=param_str(request, "retention_period", max_len=80),
        status=param_choice(request, "status", PROCESSING_STATUS, default="draft"),
    )
    return ok(activity.to_dict())


@endpoint(("GET",))
def processing_detail(request, pk):
    """处理活动详情：含关联风险与 DPIA 状态。"""
    activity = get_processing(pk, request.user)
    data = activity.to_dict()
    data["risks"] = [risk.to_dict() for risk in activity.risks.all()]
    data["dpia_required"] = bool(activity.cross_border)
    return ok(data)


@endpoint()
def processing_update(request, pk):
    """更新处理活动（目的/依据/类别/跨境/保留期）。"""
    activity = get_processing(pk, request.user, write=True)
    activity.name = param_str(request, "name", default=activity.name, max_len=200)
    activity.purpose = param_text(request, "purpose", default=activity.purpose)
    activity.legal_basis = param_str(request, "legal_basis", default=activity.legal_basis,
                                     max_len=120)
    categories = param_list(request, "data_categories")
    if categories:
        activity.data_categories = categories
    subjects = param_list(request, "subject_categories")
    if subjects:
        activity.subject_categories = subjects
    activity.recipients = param_text(request, "recipients", default=activity.recipients)
    cross = param_bool(request, "cross_border", None)
    if cross is not None:
        activity.cross_border = cross
    activity.retention_period = param_str(request, "retention_period",
                                          default=activity.retention_period, max_len=80)
    activity.status = param_choice(request, "status", PROCESSING_STATUS, default=activity.status)
    activity.save()
    return ok(activity.to_dict())


@endpoint()
def processing_delete(request, pk):
    """删除处理活动（风险关联自动解除，风险本身不受影响）。"""
    activity = get_processing(pk, request.user, write=True)
    with transaction.atomic():
        activity.risks.clear()
        activity.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def processing_dpia(request, pk):
    """标记 DPIA 完成（重复标记幂等，日期以首次为准）。"""
    activity = get_processing(pk, request.user, write=True)
    if activity.dpia_done:
        return ok({"activity": activity.to_dict(), "already_done": True})
    activity.dpia_done = True
    activity.dpia_on = param_date(request, "dpia_on") or services.today()
    if activity.status == "draft":
        # 做过 DPIA 意味着活动已进入实质运行，草稿态继续留着会让
        # 「DPIA 覆盖率」与「在运行活动」两张表对不上。
        activity.status = "active"
    activity.save(update_fields=["dpia_done", "dpia_on", "status", "updated_at"])
    return ok({"activity": activity.to_dict(), "already_done": False})



@endpoint(("GET",))
def processing_risks(request, pk):
    """处理活动关联的风险列表。"""
    activity = get_processing(pk, request.user)
    return paginate(activity.risks.all().order_by("-residual_score"), request)


@endpoint()
def processing_risk_link(request, pk):
    """关联风险（重复关联视为已关联，幂等）。"""
    activity = get_processing(pk, request.user, write=True)
    risk = get_risk(param_int(request, "risk_id", required=True, minimum=1), request.user)
    with transaction.atomic():
        activity.risks.add(risk)
    return ok({"activity_id": activity.pk, "risk_id": risk.pk, "linked": True})


@endpoint()
def processing_risk_unlink(request, pk):
    """解除风险关联（未关联时返回 linked=False，不报错）。"""
    activity = get_processing(pk, request.user, write=True)
    risk_id = param_int(request, "risk_id", required=True, minimum=1)
    with transaction.atomic():
        activity.risks.remove(risk_id)
    return ok({"activity_id": activity.pk, "risk_id": risk_id, "linked": False})
