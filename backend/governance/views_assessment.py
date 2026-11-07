# -*- coding: utf-8 -*-
"""合规评估接口：评估 CRUD + 启动/完成 + 评估项 CRUD + 批量更新 + 得分 + 报告。

评估的生命周期与分值计算分两处：
- 视图负责状态机（planned → in_progress → completed）与权限；
- services.assessment_score 负责加权口径（通过=1、进行中=0.5、失败=0、
  不适用剔除），评估完成、批量更新与得分查询都调用同一函数。

批量更新必须整体成功或整体失败：部分更新会让得分基于「一半新一半旧」的
评估项计算，看起来正常却无法复现。
"""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from devtools.common import endpoint, ok, p

from governance import services
from governance.models import (
    ASSESSMENT_ITEM_STATUS,
    ASSESSMENT_STATUS,
    Assessment,
    AssessmentItem,
    Evidence,
    RemediationTask,
)
from governance.views_common import (
    apply_search,
    filter_choice,
    filter_int,
    get_assessment,
    get_assessment_item,
    get_control,
    get_framework,
    get_framework_control,
    page_params,
    paginate,
    param_choice,
    param_date,
    param_int,
    param_str,
    param_text,
    scoped,
)

ASSESSMENT_SEARCH_FIELDS = ("name", "scope", "lead_name")
ITEM_SEARCH_FIELDS = ("note", "evidence_note")


def _item_defaults(request, assessment, framework_control, control):
    """计算评估项的权重与初始状态。

    权重优先取框架条款权重（快照），其次取 1：评估项一旦创建，权重就固定，
    后续框架条款调权不会追溯改变历史得分。
    """
    weight = param_int(request, "weight", default=0, minimum=0, maximum=100)
    if not weight:
        weight = getattr(framework_control, "weight", 1) or 1
    status = param_choice(request, "status", ASSESSMENT_ITEM_STATUS, default="not_started")
    return {
        "owner": request.user,
        "assessment": assessment,
        "framework_control": framework_control,
        "control": control,
        "status": status,
        "weight": weight,
        "evidence_note": param_text(request, "evidence_note"),
        "note": param_text(request, "note"),
    }


@endpoint(("GET",))
def assessment_list(request):
    """评估列表：可按框架与有效状态筛选。"""
    qs = scoped(Assessment, request.user)
    qs = apply_search(qs, request, ASSESSMENT_SEARCH_FIELDS)
    qs = filter_int(qs, request, "framework_id", "framework_id")
    rows = list(qs.select_related("framework").order_by("-created_at"))
    # overdue 是时间推导出来的状态，数据库里没有这一列，只能读时过滤再分页；
    # 评估数量本身有限（通常几十条），这里不做额外索引权衡。
    wanted = param_str(request, "effective_status", max_len=20)
    if wanted:
        if wanted not in ASSESSMENT_STATUS:
            raise ValueError("参数 effective_status 必须是 "
                             + "/".join(ASSESSMENT_STATUS) + " 之一")
        rows = [row for row in rows if row.effective_status() == wanted]
    page, size = services.parse_int(p(request, "page"), "page", default=1, minimum=1), \
        services.parse_int(p(request, "page_size"), "page_size", default=20, minimum=1, maximum=200)
    start = (page - 1) * size
    return ok({"items": [row.to_dict() for row in rows[start:start + size]],
               "count": len(rows), "page": page, "page_size": size})


@endpoint()
def assessment_create(request):
    """创建评估；指定框架时可按框架条款自动生成评估项（幂等）。"""
    name = param_str(request, "name", required=True, max_len=200)
    framework_id = param_int(request, "framework_id", default=None, minimum=1)
    framework = get_framework(framework_id, request.user) if framework_id else None
    seed = str(p(request, "seed_items", "1")).lower() not in ("0", "false", "no", "off")
    with transaction.atomic():
        assessment = Assessment.objects.create(
            owner=request.user,
            name=name,
            framework=framework,
            scope=param_str(request, "scope", max_len=200),
            status="planned",
            start_on=param_date(request, "start_on"),
            end_on=param_date(request, "end_on"),
            lead_name=param_str(request, "lead_name", max_len=80),
        )
        created = 0
        if framework is not None and seed:
            existing = set(assessment.items.values_list("framework_control_id", flat=True))
            for control in framework.controls.all():
                if control.pk in existing:
                    continue
                AssessmentItem.objects.create(
                    owner=request.user,
                    assessment=assessment,
                    framework_control=control,
                    status="not_started",
                    weight=control.weight,
                )
                created += 1
    data = assessment.to_dict()
    data["seeded_items"] = created
    return ok(data)


@endpoint(("GET",))
def assessment_detail(request, pk):
    """评估详情：含状态分布与得分摘要。"""
    assessment = get_assessment(pk, request.user)
    data = assessment.to_dict()
    counts = {row["status"]: row["count"] for row in
              assessment.items.values("status").annotate(count=Count("id"))}
    data["item_counts"] = {status: counts.get(status, 0)
                           for status in ASSESSMENT_ITEM_STATUS}
    data["item_total"] = sum(counts.values())
    data["score_detail"] = services.assessment_score(assessment, persist=False)
    return ok(data)


@endpoint()
def assessment_update(request, pk):
    """更新评估元信息（状态只能通过启动/完成接口推进）。"""
    assessment = get_assessment(pk, request.user, write=True)
    if assessment.status == "completed":
        raise ValueError("已完成的评估不可修改")
    framework_id = param_int(request, "framework_id", default=None, minimum=1)
    if framework_id:
        assessment.framework = get_framework(framework_id, request.user)
    assessment.name = param_str(request, "name", default=assessment.name, max_len=200)
    assessment.scope = param_str(request, "scope", default=assessment.scope, max_len=200)
    assessment.lead_name = param_str(request, "lead_name", default=assessment.lead_name, max_len=80)
    assessment.start_on = param_date(request, "start_on") or assessment.start_on
    assessment.end_on = param_date(request, "end_on") or assessment.end_on
    assessment.save()
    return ok(assessment.to_dict())


@endpoint()
def assessment_delete(request, pk):
    """删除评估（评估项级联删除；已完成评估需 force=1）。"""
    assessment = get_assessment(pk, request.user, write=True)
    force = str(p(request, "force", "")).lower() in ("1", "true", "yes", "on")
    if assessment.status == "completed" and not force:
        raise ValueError("已完成评估确认删除请传 force=1")
    with transaction.atomic():
        assessment.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def assessment_start(request, pk):
    """启动评估：planned/overdue → in_progress（已在进行中则幂等返回）。"""
    assessment = get_assessment(pk, request.user, write=True)
    if assessment.status == "in_progress":
        return ok({"assessment": assessment.to_dict(), "already_started": True})
    services.require_status(assessment, ("planned", "overdue"), "启动")
    assessment.status = "in_progress"
    if assessment.start_on is None:
        assessment.start_on = services.today()
    assessment.save(update_fields=["status", "start_on", "updated_at"])
    return ok({"assessment": assessment.to_dict(), "already_started": False})


@endpoint()
def assessment_complete(request, pk):
    """完成评估：重算并固化得分，同时把未决评估项置为进行中。"""
    assessment = get_assessment(pk, request.user, write=True)
    if assessment.status == "completed":
        return ok({"assessment": assessment.to_dict(),
                   "score": float(assessment.score),
                   "already_completed": True})
    services.require_status(assessment, ("planned", "in_progress", "overdue"), "完成")
    with transaction.atomic():
        # 未开始项在完成时统一置为「进行中」：直接置 passed 会伪造结论，
        # 置 failed 又会在没有证据的情况下给出负面评价。
        assessment.items.filter(status="not_started").update(status="in_progress")
        score = services.assessment_score(assessment)
        assessment.status = "completed"
        if assessment.end_on is None:
            assessment.end_on = services.today()
        assessment.save(update_fields=["status", "end_on", "updated_at"])
    data = assessment.to_dict()
    data["score_detail"] = score
    return ok(data)


@endpoint(("GET",))
def assessment_items(request, pk):
    """评估项列表（按状态/条款筛选）。"""
    assessment = get_assessment(pk, request.user)
    qs = assessment.items.select_related("framework_control", "control").order_by("id")
    qs = apply_search(qs, request, ITEM_SEARCH_FIELDS)
    qs = filter_int(qs, request, "framework_control_id", "framework_control_id")
    qs = filter_int(qs, request, "control_id", "control_id")
    return paginate(qs, request)


@endpoint()
def assessment_item_create(request):
    """新增评估项（框架条款或内部控制至少给一个）。"""
    assessment_id = param_int(request, "assessment_id", required=True, minimum=1)
    assessment = get_assessment(assessment_id, request.user, write=True)
    if assessment.status == "completed":
        raise ValueError("已完成的评估不能再新增评估项")
    framework_control_id = param_int(request, "framework_control_id", default=None, minimum=1)
    control_id = param_int(request, "control_id", default=None, minimum=1)
    if not framework_control_id and not control_id:
        raise ValueError("必须提供 framework_control_id 或 control_id")
    framework_control = get_framework_control(framework_control_id, request.user) \
        if framework_control_id else None
    control = get_control(control_id, request.user) if control_id else None
    if (framework_control is not None and assessment.framework_id
            and framework_control.framework_id != assessment.framework_id):
        raise ValueError("框架条款不属于该评估的框架")
    item = AssessmentItem.objects.create(**_item_defaults(request, assessment,
                                                          framework_control, control))
    return ok(item.to_dict())


@endpoint(("GET",))
def assessment_item_detail(request, pk):
    """评估项详情（含关联整改任务）。"""
    item = get_assessment_item(pk, request.user)
    data = item.to_dict()
    task = item.remediation_task
    data["remediation_task"] = task.to_dict() if task else None
    return ok(data)


@endpoint()
def assessment_item_update(request, pk):
    """更新评估项（状态/备注/证据说明/权重/整改任务）。"""
    item = get_assessment_item(pk, request.user, write=True)
    if item.assessment.status == "completed":
        raise ValueError("已完成的评估不可修改评估项")
    item.status = param_choice(request, "status", ASSESSMENT_ITEM_STATUS, default=item.status)
    item.note = param_text(request, "note", default=item.note)
    item.evidence_note = param_text(request, "evidence_note", default=item.evidence_note)
    weight = param_int(request, "weight", default=None, minimum=1, maximum=100)
    if weight is not None:
        item.weight = weight
    task_id = param_int(request, "remediation_task_id", default=None, minimum=1)
    if task_id:
        task = RemediationTask.objects.filter(pk=task_id).first()
        if task is None:
            raise ValueError("整改任务不存在")
        services.ensure_visible(task, request.user)
        item.remediation_task = task
    item.save()
    return ok(item.to_dict())


@endpoint()
def assessment_item_delete(request, pk):
    """删除评估项（不影响已关联的整改任务本身）。"""
    item = get_assessment_item(pk, request.user, write=True)
    if item.assessment.status == "completed":
        raise ValueError("已完成的评估不可删除评估项")
    assessment_id = item.assessment_id
    item.delete()
    return ok({"id": pk, "assessment_id": assessment_id, "deleted": True})


@endpoint()
def assessment_items_bulk(request):
    """批量更新评估项状态（整体事务，任一行非法则全部回滚）。"""
    pk = param_int(request, "assessment_id", required=True, minimum=1)
    assessment = get_assessment(pk, request.user, write=True)
    # 先校验入参再校验状态：空 items 属于参数错误，无论评估是否已完成都应
    # 返回同一个中文提示，前端据此定位是「传错了」而不是「状态锁了」。
    rows = p(request, "items")
    if not isinstance(rows, list) or not rows:
        raise ValueError("参数 items 必须是非空数组")
    if len(rows) > 200:
        raise ValueError("参数 items 最多 200 项")
    if assessment.status == "completed":
        raise ValueError("已完成的评估不可批量更新")
    ids = set(assessment.items.values_list("id", flat=True))
    updated = 0
    with transaction.atomic():
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("items 每一项必须是对象")
            item_id = services.parse_int(row.get("id"), "id", required=True, minimum=1)
            if item_id not in ids:
                raise ValueError(f"评估项 {item_id} 不属于该评估")
            item = AssessmentItem.objects.get(pk=item_id)
            if row.get("status") not in (None, ""):
                item.status = services.choice(row.get("status"), "status",
                                              ASSESSMENT_ITEM_STATUS, required=True)
            if "note" in row:
                item.note = str(row.get("note") or "")[:20000]
            if "evidence_note" in row:
                item.evidence_note = str(row.get("evidence_note") or "")[:20000]
            if row.get("weight") not in (None, ""):
                item.weight = services.parse_int(row.get("weight"), "weight",
                                                 minimum=1, maximum=100)
            item.save()
            updated += 1
        score = services.assessment_score(assessment)
    return ok({"assessment_id": assessment.pk, "updated": updated, "score": score["score"]})


@endpoint(("GET",))
def assessment_score_view(request, pk):
    """评估得分：加权明细（不落库，供预览）。"""
    assessment = get_assessment(pk, request.user)
    return ok(services.assessment_score(assessment, persist=False))


@endpoint(("GET",))
def assessment_report(request, pk):
    """评估报告：得分、状态分布、分类达成、未通过清单与证据统计。"""
    assessment = get_assessment(pk, request.user)
    score = services.assessment_score(assessment, persist=False)
    items = list(assessment.items.select_related("framework_control", "control"))
    by_status = {status: 0 for status in ASSESSMENT_ITEM_STATUS}
    by_category = {}
    failed = []
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        category = getattr(item.framework_control, "category", "") or \
            getattr(item.control, "category", "") or "未分类"
        bucket = by_category.setdefault(category, {"category": category, "total": 0,
                                                   "passed": 0, "failed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if item.status == "passed" else 0
        bucket["failed"] += 1 if item.status == "failed" else 0
        if item.status == "failed":
            failed.append(item.to_dict())
    for bucket in by_category.values():
        bucket["pass_ratio"] = services.pct(bucket["passed"], bucket["total"])
    evidence_qs = Evidence.objects.filter(owner=assessment.owner, target_kind="assessment",
                                          target_id=assessment.pk)
    return ok({
        "assessment": assessment.to_dict(),
        "score": score,
        "by_status": by_status,
        "by_category": sorted(by_category.values(), key=lambda row: row["pass_ratio"]),
        "failed_items": failed,
        "evidence_total": evidence_qs.count(),
        "generated_at": services.as_iso(timezone.now()),
    })
