# -*- coding: utf-8 -*-
"""审计、发现与整改接口。

闭环状态机：
    audit: planned → in_progress → completed / cancelled
    finding: open → in_progress → resolved → verified
    remediation: open → in_progress → done → verified

关键控制点：
1. finding 不允许直接置 verified，必须由整改任务「验证」接口推进；
2. 整改验证必须写验证人，且只能验证一次（重复调用返回既有结论）；
3. 一条发现下的全部整改任务都验证通过后，发现才自动进入 verified 并回填关闭日。
"""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from devtools.common import endpoint, ok, p

from governance import services
from governance.models import (
    AUDIT_KINDS,
    AUDIT_STATUS,
    FINDING_SEVERITIES,
    FINDING_STATUS,
    REMEDIATION_STATUS,
    Audit,
    Finding,
    RemediationTask,
)
from governance.views_common import (
    apply_search,
    filter_choice,
    filter_int,
    get_audit,
    get_finding,
    get_remediation,
    page_params,
    paginate,
    param_choice,
    param_date,
    param_int,
    param_str,
    param_text,
    scoped,
)

AUDIT_SEARCH_FIELDS = ("name", "scope", "auditor_name", "conclusion")
FINDING_SEARCH_FIELDS = ("title", "description", "remediation_owner")
REMEDIATION_SEARCH_FIELDS = ("measure", "owner_name", "verifier_name")


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def audit_list(request):
    """审计列表：按类型/状态筛选。"""
    qs = scoped(Audit, request.user)
    qs = apply_search(qs, request, AUDIT_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "kind", AUDIT_KINDS)
    return paginate(qs.annotate(finding_total=Count("findings")).order_by("-created_at"), request)


@endpoint()
def audit_create(request):
    """新建审计（类型与起止日期）。"""
    audit = Audit.objects.create(
        owner=request.user,
        name=param_str(request, "name", required=True, max_len=200),
        kind=param_choice(request, "kind", AUDIT_KINDS, default="internal"),
        scope=param_str(request, "scope", max_len=200),
        start_on=param_date(request, "start_on"),
        end_on=param_date(request, "end_on"),
        status=param_choice(request, "status", AUDIT_STATUS, default="planned"),
        auditor_name=param_str(request, "auditor_name", max_len=80),
        conclusion=param_text(request, "conclusion"),
    )
    return ok(audit.to_dict())


@endpoint(("GET",))
def audit_detail(request, pk):
    """审计详情：含发现按严重度分布与整改进度。"""
    audit = get_audit(pk, request.user)
    data = audit.to_dict()
    findings = list(audit.findings.all())
    by_severity = {severity: 0 for severity in FINDING_SEVERITIES}
    by_status = {status: 0 for status in FINDING_STATUS}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        by_status[finding.status] = by_status.get(finding.status, 0) + 1
    data["by_severity"] = by_severity
    data["by_status"] = by_status
    data["overdue_findings"] = sum(1 for finding in findings if finding.is_overdue())
    data["recent_findings"] = [f.to_dict() for f in audit.findings.order_by("-created_at")[:10]]
    return ok(data)


@endpoint()
def audit_update(request, pk):
    """更新审计（范围/起止/状态/审计人/结论）。"""
    audit = get_audit(pk, request.user, write=True)
    audit.name = param_str(request, "name", default=audit.name, max_len=200)
    audit.kind = param_choice(request, "kind", AUDIT_KINDS, default=audit.kind)
    audit.scope = param_str(request, "scope", default=audit.scope, max_len=200)
    audit.start_on = param_date(request, "start_on") or audit.start_on
    audit.end_on = param_date(request, "end_on") or audit.end_on
    audit.status = param_choice(request, "status", AUDIT_STATUS, default=audit.status)
    audit.auditor_name = param_str(request, "auditor_name", default=audit.auditor_name,
                                   max_len=80)
    audit.conclusion = param_text(request, "conclusion", default=audit.conclusion)
    audit.save()
    return ok(audit.to_dict())


@endpoint()
def audit_delete(request, pk):
    """删除审计（发现与整改任务级联删除；已完成审计需 force=1）。"""
    audit = get_audit(pk, request.user, write=True)
    force = str(p(request, "force", "")).lower() in ("1", "true", "yes", "on")
    if audit.findings.exists() and not force:
        raise ValueError("该审计已有发现记录，确认删除请传 force=1")
    with transaction.atomic():
        audit.delete()
    return ok({"id": pk, "deleted": True})


@endpoint(("GET",))
def audit_findings(request, pk):
    """某审计下的发现列表。"""
    audit = get_audit(pk, request.user)
    qs = apply_search(audit.findings.all(), request, FINDING_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "severity", FINDING_SEVERITIES)
    return paginate(qs.order_by("-created_at"), request)


@endpoint()
def audit_finding_create(request):
    """新增发现（严重度/整改负责人/截止日）。"""
    audit_id = param_int(request, "audit_id", required=True, minimum=1)
    audit = get_audit(audit_id, request.user, write=True)
    finding = Finding.objects.create(
        owner=request.user,
        audit=audit,
        title=param_str(request, "title", required=True, max_len=200),
        severity=param_choice(request, "severity", FINDING_SEVERITIES, default="medium"),
        description=param_text(request, "description"),
        remediation_owner=param_str(request, "remediation_owner", max_len=80),
        due_on=param_date(request, "due_on"),
        status=param_choice(request, "status", FINDING_STATUS, default="open"),
    )
    return ok(finding.to_dict())


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def finding_list(request):
    """发现列表：按严重度/状态/审计/是否逾期筛选。

    逾期是推导状态（未解决且截止日已过），过滤在 Python 侧完成；
    发现数量与审计同量级（几十到几百条），代价可接受。
    """
    qs = scoped(Finding, request.user)
    qs = apply_search(qs, request, FINDING_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "severity", FINDING_SEVERITIES)
    qs = filter_int(qs, request, "audit_id", "audit_id")
    overdue = param_str(request, "overdue", max_len=8)
    rows = list(qs.select_related("audit").order_by("-created_at"))
    if overdue in ("1", "true", "yes", "on"):
        rows = [row for row in rows if row.is_overdue()]
    elif overdue in ("0", "false", "no", "off"):
        rows = [row for row in rows if not row.is_overdue()]
    page, size = page_params(request)
    start = (page - 1) * size
    return ok({"items": [row.to_dict() for row in rows[start:start + size]],
               "count": len(rows), "page": page, "page_size": size})


@endpoint(("GET",))
def finding_detail(request, pk):
    """发现详情：含整改任务清单与逾期标记。"""
    finding = get_finding(pk, request.user)
    data = finding.to_dict()
    tasks = list(finding.remediations.all())
    data["remediations"] = [task.to_dict() for task in tasks]
    data["remediation_total"] = len(tasks)
    data["remediation_done"] = sum(1 for task in tasks
                                   if task.status in ("done", "verified"))
    return ok(data)


@endpoint()
def finding_update(request, pk):
    """更新发现（状态推进到 verified 需走整改验证接口）。"""
    finding = get_finding(pk, request.user, write=True)
    target_status = param_choice(request, "status", FINDING_STATUS, default=finding.status)
    if target_status == "verified" and finding.status != "verified":
        raise ValueError("发现需通过整改任务验证后才能置为已验证")
    finding.title = param_str(request, "title", default=finding.title, max_len=200)
    finding.severity = param_choice(request, "severity", FINDING_SEVERITIES,
                                    default=finding.severity)
    finding.description = param_text(request, "description", default=finding.description)
    finding.remediation_owner = param_str(request, "remediation_owner",
                                          default=finding.remediation_owner, max_len=80)
    finding.due_on = param_date(request, "due_on") or finding.due_on
    finding.status = target_status
    if target_status in ("resolved", "verified") and finding.closed_on is None:
        finding.closed_on = param_date(request, "closed_on") or services.today()
    finding.save()
    return ok(finding.to_dict())


@endpoint()
def finding_delete(request, pk):
    """删除发现（整改任务级联删除）。"""
    finding = get_finding(pk, request.user, write=True)
    with transaction.atomic():
        finding.delete()
    return ok({"id": pk, "deleted": True})


@endpoint(("GET",))
def finding_remediations(request, pk):
    """某发现下的整改任务列表。"""
    finding = get_finding(pk, request.user)
    qs = finding.remediations.all().order_by("-created_at")
    qs = filter_choice(qs, request, "status", REMEDIATION_STATUS)
    return paginate(qs, request)


@endpoint()
def finding_remediation_create(request):
    """新增整改任务（措施/负责人/截止日）。"""
    finding_id = param_int(request, "finding_id", required=True, minimum=1)
    finding = get_finding(finding_id, request.user, write=True)
    with transaction.atomic():
        task = RemediationTask.objects.create(
            owner=request.user,
            finding=finding,
            measure=param_text(request, "measure"),
            owner_name=param_str(request, "owner_name", max_len=80),
            due_on=param_date(request, "due_on"),
            status=param_choice(request, "status", REMEDIATION_STATUS, default="open"),
        )
        if finding.status == "open":
            # 有整改任务即进入处理中，避免看板上「已有人在做但状态仍待处理」。
            finding.status = "in_progress"
            finding.save(update_fields=["status", "updated_at"])
    return ok(task.to_dict())


@endpoint(("GET",))
def remediation_list(request):
    """整改任务列表（跨发现，支持逾期过滤）。"""
    qs = scoped(RemediationTask, request.user)
    qs = apply_search(qs, request, REMEDIATION_SEARCH_FIELDS, status_field=None)
    qs = filter_choice(qs, request, "status", REMEDIATION_STATUS)
    qs = filter_int(qs, request, "finding_id", "finding_id")
    overdue = param_str(request, "overdue", max_len=8)
    if overdue in ("1", "true", "yes", "on", "0", "false", "no", "off"):
        rows = list(qs.order_by("due_on", "id"))
        wanted = overdue in ("1", "true", "yes", "on")
        rows = [row for row in rows if row.is_overdue() == wanted]
        page, size = page_params(request)
        start = (page - 1) * size
        return ok({"items": [row.to_dict() for row in rows[start:start + size]],
                   "count": len(rows), "page": page, "page_size": size})
    return paginate(qs.order_by("due_on", "id"), request)


@endpoint(("GET",))
def remediation_detail(request, pk):
    """整改任务详情。"""
    task = get_remediation(pk, request.user)
    return ok(task.to_dict())


@endpoint()
def remediation_update(request, pk):
    """更新整改任务（措施/负责人/截止/状态；done 时回填完成日）。"""
    task = get_remediation(pk, request.user, write=True)
    if task.status == "verified":
        raise ValueError("已验证的整改任务不可修改")
    task.measure = param_text(request, "measure", default=task.measure)
    task.owner_name = param_str(request, "owner_name", default=task.owner_name, max_len=80)
    task.due_on = param_date(request, "due_on") or task.due_on
    status = param_choice(request, "status", REMEDIATION_STATUS, default=task.status)
    if status == "verified" and task.status != "verified":
        raise ValueError("请使用验证接口完成整改验证")
    task.status = status
    if status == "done" and task.completed_on is None:
        task.completed_on = param_date(request, "completed_on") or services.today()
    task.save()
    return ok(task.to_dict())


@endpoint()
def remediation_verify(request, pk):
    """验证整改：写入验证人与时间，全部任务验证后自动关闭发现（幂等）。"""
    task = get_remediation(pk, request.user, write=True)
    if task.status == "verified":
        return ok({"remediation": task.to_dict(), "already_verified": True,
                   "finding_status": task.finding.status})
    verifier = param_str(request, "verifier_name",
                         default=getattr(request.user, "display_name", "") or
                         getattr(request.user, "username", ""), max_len=80)
    if not verifier.strip():
        raise ValueError("验证人不能为空")
    now = timezone.now()
    with transaction.atomic():
        task.status = "verified"
        task.verifier_name = verifier
        task.verified_at = now
        if task.completed_on is None:
            task.completed_on = services.today()
        task.save(update_fields=["status", "verifier_name", "verified_at",
                                 "completed_on", "updated_at"])
        finding = task.finding
        remaining = finding.remediations.exclude(status="verified").count()
        if remaining == 0 and finding.status != "verified":
            # 发现级闭环：所有整改都验证通过才关闭发现，任何一条未验证
            # 都保持 resolved，避免「部分整改=已关闭」的审计漏洞。
            finding.status = "verified"
            if finding.closed_on is None:
                finding.closed_on = services.today()
            finding.save(update_fields=["status", "closed_on", "updated_at"])
    return ok({"remediation": task.to_dict(), "already_verified": False,
               "finding_status": task.finding.status})
