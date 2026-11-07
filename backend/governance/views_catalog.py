# -*- coding: utf-8 -*-
"""目录、合规框架、框架控制项与控制映射接口。

框架是整套治理数据的入口：条款（FrameworkControl）承载评估与差距分析的
最小粒度；ControlMapping 把条款与内部实施串起来，是「条款有没有人负责」
的唯一判据。因此这三类接口放在一起维护。
"""
from django.db import transaction
from django.db.models import Count

from devtools.common import endpoint, ok, opt_str, p

from governance import services
from governance.models import (
    FRAMEWORK_KINDS,
    FRAMEWORK_STATUS,
    ControlMapping,
    Framework,
    FrameworkControl,
)
from governance.views_common import (
    apply_search,
    filter_choice,
    filter_int,
    get_control,
    get_framework,
    get_framework_control,
    paginate,
    param_choice,
    param_int,
    param_str,
    param_text,
    scoped,
)

FRAMEWORK_SEARCH_FIELDS = ("name", "version", "description")
FRAMEWORK_CONTROL_SEARCH_FIELDS = ("code", "title", "description", "category")

CATALOG_META = {
    "app": "governance",
    "label": "合规治理",
    "version": "1.0",
    "domains": [
        {"key": "framework", "label": "框架与条款"},
        {"key": "policy", "label": "制度策略"},
        {"key": "control", "label": "控制与测试"},
        {"key": "assessment", "label": "合规评估"},
        {"key": "evidence", "label": "证据"},
        {"key": "risk", "label": "风险"},
        {"key": "privacy", "label": "隐私与数据"},
        {"key": "audit", "label": "审计与整改"},
        {"key": "stats", "label": "统计看板"},
    ],
    "enums": {
        "framework_kind": list(FRAMEWORK_KINDS),
        "framework_status": list(FRAMEWORK_STATUS),
        "risk_level": ["low", "medium", "high", "critical"],
        "risk_status": ["identified", "assessing", "treating", "monitored", "closed"],
        "assessment_item_status": ["not_started", "in_progress", "passed", "failed",
                                   "not_applicable"],
    },
}


@endpoint(("GET",))
def catalog(request):
    """治理目录：能力域与枚举字典（接口明细由路由层补充）。"""
    return ok(dict(CATALOG_META))


# ---------------------------------------------------------------------------
# 框架
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def framework_list(request):
    """框架列表：支持 q/status/kind 过滤与分页。"""
    qs = scoped(Framework, request.user)
    qs = apply_search(qs, request, FRAMEWORK_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "kind", FRAMEWORK_KINDS)
    qs = qs.annotate(control_total=Count("controls")).order_by("-created_at")
    return paginate(qs, request, lambda obj: obj.to_dict())


@endpoint()
def framework_create(request):
    """创建框架（同用户下 name+version 唯一）。"""
    name = param_str(request, "name", required=True, max_len=120)
    version = param_str(request, "version", default="2022", max_len=40)
    kind = param_choice(request, "kind", FRAMEWORK_KINDS, default="custom")
    if Framework.objects.filter(owner=request.user, name=name, version=version).exists():
        raise ValueError("同名同版本的框架已存在")
    framework = Framework.objects.create(
        owner=request.user,
        name=name,
        version=version,
        kind=kind,
        description=param_text(request, "description"),
        status=param_choice(request, "status", FRAMEWORK_STATUS, default="draft"),
    )
    return ok(framework.to_dict())


@endpoint(("GET",))
def framework_detail(request, pk):
    """框架详情：含条款数量、达成率与差距摘要。"""
    framework = get_framework(pk, request.user)
    data = framework.to_dict()
    coverage = services.framework_coverage(framework)
    data["coverage"] = {
        "control_total": coverage["control_total"],
        "coverage_ratio": coverage["coverage_ratio"],
        "pass_ratio": coverage["pass_ratio"],
        "gap_total": coverage["gap_total"],
    }
    return ok(data)


@endpoint()
def framework_update(request, pk):
    """更新框架基础信息（名称/版本冲突直接拒绝）。"""
    framework = get_framework(pk, request.user, write=True)
    name = param_str(request, "name", default=framework.name, max_len=120)
    version = param_str(request, "version", default=framework.version, max_len=40)
    kind = param_choice(request, "kind", FRAMEWORK_KINDS, default=framework.kind)
    status = param_choice(request, "status", FRAMEWORK_STATUS, default=framework.status)
    clash = Framework.objects.filter(owner=framework.owner, name=name, version=version) \
        .exclude(pk=framework.pk)
    if name != framework.name or version != framework.version:
        if clash.exists():
            raise ValueError("同名同版本的框架已存在")
    framework.name = name
    framework.version = version
    framework.kind = kind
    framework.status = status
    framework.description = param_text(request, "description", default=framework.description)
    framework.save()
    return ok(framework.to_dict())


@endpoint()
def framework_delete(request, pk):
    """删除框架；已有评估时要求显式 force=1（防止误删历史评估归属）。"""
    framework = get_framework(pk, request.user, write=True)
    force = str(p(request, "force", "")).lower() in ("1", "true", "yes", "on")
    with transaction.atomic():
        if framework.assessments.exists() and not force:
            raise ValueError("该框架已有评估记录，确认后请传 force=1 再删除")
        if framework.assessments.exists():
            # 评估是历史事实，不随框架删除：先解绑再删框架。
            framework.assessments.update(framework=None)
        framework.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def framework_publish(request, pk):
    """框架发布（置为生效，幂等）。"""
    framework = get_framework(pk, request.user, write=True)
    framework.publish()
    return ok(framework.to_dict())


@endpoint(("GET",))
def framework_controls(request, pk):
    """某框架下的条款列表（按编号排序）。"""
    framework = get_framework(pk, request.user)
    qs = apply_search(framework.controls.all(), request, FRAMEWORK_CONTROL_SEARCH_FIELDS)
    category = opt_str(request, "category").strip()
    if category:
        qs = qs.filter(category=category)
    return paginate(qs.order_by("code"), request)


@endpoint(("GET",))
def framework_control_list(request):
    """条款列表：可跨框架（framework_id 过滤）。"""
    qs = scoped(FrameworkControl, request.user)
    qs = apply_search(qs, request, FRAMEWORK_CONTROL_SEARCH_FIELDS)
    qs = filter_int(qs, request, "framework_id", "framework_id")
    category = opt_str(request, "category").strip()
    if category:
        qs = qs.filter(category=category)
    return paginate(qs.select_related("framework").order_by("framework_id", "code"), request)


@endpoint()
def framework_control_create(request):
    """新增框架条款（框架内编号唯一，权重 1..10）。"""
    framework_id = param_int(request, "framework_id", required=True, minimum=1)
    framework = get_framework(framework_id, request.user, write=True)
    code = param_str(request, "code", required=True, max_len=60)
    title = param_str(request, "title", required=True, max_len=200)
    if framework.controls.filter(code=code).exists():
        raise ValueError("该框架下已存在相同编号的条款")
    control = FrameworkControl.objects.create(
        owner=request.user,
        framework=framework,
        code=code,
        title=title,
        description=param_text(request, "description"),
        category=param_str(request, "category", default="通用", max_len=60),
        weight=param_int(request, "weight", default=1, minimum=1, maximum=10),
    )
    return ok(control.to_dict())


@endpoint(("GET",))
def framework_control_detail(request, pk):
    """条款详情：附带映射的控制与评估结论。"""
    control = get_framework_control(pk, request.user)
    data = control.to_dict()
    mappings = control.mappings.select_related("control").all()
    data["mappings"] = [m.to_dict() for m in mappings]
    data["mapped_controls"] = [
        {"id": m.control_id, "code": m.control.code, "name": m.control.name,
         "effectiveness": m.control.effectiveness}
        for m in mappings
    ]
    items = control.assessment_items.order_by("-updated_at")[:10]
    data["assessment_items"] = [item.to_dict() for item in items]
    return ok(data)


@endpoint()
def framework_control_update(request, pk):
    """更新条款（编号/权重/类别）。"""
    control = get_framework_control(pk, request.user, write=True)
    code = param_str(request, "code", default=control.code, max_len=60)
    if code != control.code and control.framework.controls.filter(code=code).exists():
        raise ValueError("该框架下已存在相同编号的条款")
    control.code = code
    control.title = param_str(request, "title", default=control.title, max_len=200)
    control.description = param_text(request, "description", default=control.description)
    control.category = param_str(request, "category", default=control.category, max_len=60)
    control.weight = param_int(request, "weight", default=control.weight, minimum=1, maximum=10)
    control.save()
    return ok(control.to_dict())


@endpoint()
def framework_control_delete(request, pk):
    """删除条款（评估项会随之解绑，框架控制映射级联删除）。"""
    control = get_framework_control(pk, request.user, write=True)
    with transaction.atomic():
        control.assessment_items.update(framework_control=None)
        control.delete()
    return ok({"id": pk, "deleted": True})


@endpoint(("GET",))
def framework_coverage(request, pk):
    """框架达成率：整体比例 + 按类别明细。"""
    framework = get_framework(pk, request.user)
    return ok(services.framework_coverage(framework))


@endpoint(("GET",))
def framework_gaps(request, pk):
    """框架差距分析：缺口清单 + 原因分类统计。"""
    framework = get_framework(pk, request.user)
    return ok(services.framework_gaps(framework))


# ---------------------------------------------------------------------------
# 控制映射（条款 ↔ 内部实施）
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def mapping_list(request):
    """控制映射列表（可按 framework_control_id / control_id 过滤）。"""
    qs = scoped(ControlMapping, request.user)
    qs = filter_int(qs, request, "framework_control_id", "framework_control_id")
    qs = filter_int(qs, request, "control_id", "control_id")
    qs = qs.select_related("framework_control", "control").order_by("framework_control_id")
    return paginate(qs, request)


@endpoint()
def mapping_link(request):
    """建立条款与控制的映射（重复映射视为已是同一关系，幂等返回）。"""
    framework_control_id = param_int(request, "framework_control_id", required=True, minimum=1)
    control_id = param_int(request, "control_id", required=True, minimum=1)
    fw_control = get_framework_control(framework_control_id, request.user, write=True)
    control = get_control(control_id, request.user, write=True)
    strength = param_int(request, "strength", default=100, minimum=0, maximum=100)
    mapping, created = ControlMapping.objects.get_or_create(
        framework_control=fw_control,
        control=control,
        defaults={"owner": request.user, "strength": strength,
                  "note": param_str(request, "note", max_len=200)},
    )
    if not created and mapping.strength != strength:
        mapping.strength = strength
        mapping.save(update_fields=["strength", "updated_at"])
    return ok({"mapping": mapping.to_dict(), "created": created})


@endpoint()
def mapping_unlink(request):
    """解除映射（不存在时按已解除处理，保证重试安全）。"""
    mapping_id = param_int(request, "id", required=True, minimum=1)
    mapping = scoped(ControlMapping, request.user).filter(pk=mapping_id).first()
    if mapping is None:
        return ok({"id": mapping_id, "deleted": False, "reason": "not_found"})
    services.ensure_writable(mapping, request.user)
    mapping.delete()
    return ok({"id": mapping_id, "deleted": True})
