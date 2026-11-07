# -*- coding: utf-8 -*-
"""formstudio 填报与协作接口：公开提交、草稿、我的提交、提交列表/详情、
审核通过/驳回、附件元数据、审核任务与评论。

权限口径
--------
- 表单创建者（owner）可查看/管理该表单下全部提交；
- 填报人凭 submitted_by 查看自己的提交，匿名提交不记录填报人；
- 审核只允许表单创建者（或具备写权限的管理员）执行；
- 附件只登记元数据，随时可回看是谁在什么字段上登记的。
"""
from django.db import transaction
from django.db.models import Q

from core.scoping import can_write, is_visible

from devtools.common import (endpoint, fail, ok, opt_bool, opt_str, p, req_str)

from formstudio import services
from formstudio.common import (
    apply_keyword,
    apply_status,
    attachment_dict,
    comment_dict,
    get_comment,
    get_form,
    get_submission,
    int_param,
    json_obj,
    opt_dt,
    opt_int,
    paginate,
    review_task_dict,
    submission_dict,
    user_brief,
    visible_submissions,
)
from formstudio.models import (
    FormComment,
    FormDefinition,
    FormReviewTask,
    FormSubmission,
)
from formstudio.services import SubmissionValidationError


def _client_ip(request):
    """取客户端 IP：优先反代头，其次 REMOTE_ADDR。"""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


def _resolve_submit_form(request):
    """提交入口解析：分享 token 优先，其次表单编码（slug 同义）。

    公开提交不要求表单对填报人可见，否则匿名收集无法使用；但必须已发布，
    由 create_submission 统一校验状态与截止时间。
    """
    token = opt_str(request, "token", "", max_len=128).strip()
    if token:
        link = services.verify_share_link(token, p(request, "password"))
        return link.form, link
    code = opt_str(request, "code", opt_str(request, "slug", ""), max_len=64).strip()
    if not code:
        raise ValueError("缺少表单编码或分享令牌")
    form = (
        FormDefinition.objects.select_related("owner")
        .filter(code=code)
        .order_by("-updated_at")
        .first()
    )
    if form is None:
        raise ValueError("表单不存在")
    return form, None


def _submission_or_raise_form(request):
    """草稿接口的表单定位：form_id 或 code。"""
    form_id = opt_int(request, "form_id")
    if form_id:
        form = FormDefinition.objects.select_related("owner").filter(pk=form_id).first()
        if form is None:
            raise ValueError("表单不存在")
        return form
    code = opt_str(request, "code", opt_str(request, "slug", ""), max_len=64).strip()
    if not code:
        raise ValueError("缺少 form_id 或 code")
    form = FormDefinition.objects.filter(code=code).order_by("-updated_at").first()
    if form is None:
        raise ValueError("表单不存在")
    return form


def _answers(request):
    """取答案对象；兼容 values 别名。"""
    if p(request, "answers") is not None:
        return json_obj(request, "answers", required=True)
    return json_obj(request, "values", required=True)


@endpoint(("POST",))
def submission_public(request):
    """公开提交（需登录）：按分享 token 或表单编码提交，支持匿名。"""
    form, share_link = _resolve_submit_form(request)
    answers = _answers(request)
    anonymous = opt_bool(request, "anonymous", False)
    try:
        submission = services.create_submission(
            form,
            request.user,
            answers,
            source=opt_str(request, "source", "web", max_len=20),
            share_link=share_link,
            anonymous=anonymous,
            duration_seconds=opt_int(request, "duration_seconds", default=0),
            ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            data=json_obj(request, "data"),
        )
    except SubmissionValidationError as exc:
        return fail(str(exc), errors=exc.errors)
    form.touch_view()
    return ok(
        {
            "submission": submission_dict(submission, with_values=True),
            "message": form.submit_message,
            "redirect_url": form.redirect_url,
            "score": submission.score,
            "max_score": submission.max_score,
        }
    )


@endpoint(("GET",))
def submission_mine(request):
    """我的提交列表（按填报人，含草稿）。"""
    qs = (
        FormSubmission.objects.filter(submitted_by_id=request.user.id)
        .select_related("form", "owner", "submitted_by")
        .order_by("-created_at", "-id")
    )
    qs = apply_keyword(qs, request, ("form__name", "form__code"))
    qs = apply_status(qs, request)
    form_id = opt_int(request, "form_id")
    if form_id:
        qs = qs.filter(form_id=form_id)
    return ok(paginate(qs, request, submission_dict))


@endpoint(("GET",))
def submission_collection(request):
    """提交列表（表单创建者按数据范围可见，回报填报人自己的记录）。"""
    qs = visible_submissions(request.user).select_related(
        "form", "owner", "submitted_by"
    )
    qs = apply_keyword(qs, request, ("form__name", "form__code"))
    qs = apply_status(qs, request)
    form_id = opt_int(request, "form_id")
    if form_id:
        qs = qs.filter(form_id=form_id)
    if opt_str(request, "source", ""):
        qs = qs.filter(source=opt_str(request, "source"))
    submitted_by = opt_int(request, "submitted_by")
    if submitted_by:
        qs = qs.filter(submitted_by_id=submitted_by)
    version_no = opt_int(request, "version_no")
    if version_no:
        qs = qs.filter(version_no=version_no)
    if opt_dt(request, "date_from"):
        qs = qs.filter(submitted_at__gte=opt_dt(request, "date_from"))
    if opt_dt(request, "date_to"):
        qs = qs.filter(submitted_at__lte=opt_dt(request, "date_to"))
    if not opt_str(request, "status", "") and not opt_bool(request, "include_drafts", False):
        qs = qs.exclude(status="draft")
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, submission_dict))


@endpoint(("GET",))
def submission_detail(request, pk):
    """提交详情：填报值、附件、审核任务与评论数。"""
    submission = get_submission(request.user, pk, mode="view")
    data = submission_dict(submission, with_values=True, with_attachments=True)
    data["review_tasks"] = [
        review_task_dict(t) for t in submission.review_tasks.all().order_by("-id")
    ]
    data["comments"] = submission.comments.count()
    data["can_review"] = can_write(request.user, submission.form)
    data["can_edit"] = (
        submission.status == "draft" and submission.submitted_by_id == request.user.id
    )
    return ok(data)


@endpoint(("POST",))
def submission_draft_create(request):
    """保存草稿：校验类型宽松，可稍后继续填写。"""
    form = _submission_or_raise_form(request)
    submission = services.create_submission(
        form,
        request.user,
        _answers(request),
        source=opt_str(request, "source", "web", max_len=20),
        duration_seconds=opt_int(request, "duration_seconds", default=0),
        ip=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        data=json_obj(request, "data"),
        draft=True,
    )
    return ok(submission_dict(submission, with_values=True))


@endpoint(("POST",))
def submission_draft_update(request, pk):
    """更新草稿；submit=true 时直接按正式提交校验并转正。"""
    submission = get_submission(request.user, pk, mode="edit")
    submit_now = opt_bool(request, "submit", False)
    answers = _answers(request)
    try:
        updated = services.create_submission(
            submission.form,
            request.user,
            answers,
            source=opt_str(request, "source", "web", max_len=20),
            duration_seconds=opt_int(request, "duration_seconds", default=submission.duration_seconds),
            ip=_client_ip(request) or submission.ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300] or submission.user_agent,
            data=json_obj(request, "data"),
            draft=not submit_now,
            existing=submission,
            share_link=submission.share_link,
        )
    except SubmissionValidationError as exc:
        return fail(str(exc), errors=exc.errors)
    return ok(submission_dict(updated, with_values=True))


@endpoint(("DELETE",))
def submission_delete(request, pk):
    """删除提交：草稿仅本人可删，正式提交仅表单创建者可删。"""
    submission = get_submission(request.user, pk, mode="view")
    if submission.status == "draft":
        if submission.submitted_by_id != request.user.id:
            raise ValueError("只能删除自己的草稿")
    elif not can_write(request.user, submission.form):
        raise ValueError("只有表单创建者可以删除正式提交")
    form = submission.form
    was_final = submission.status != "draft"
    submission.delete()
    if was_final:
        services.sync_form_counters(form)
    return ok({"id": pk, "deleted": True})


@endpoint(("POST",))
def submission_approve(request, pk):
    """审核通过：回写提交状态、审核结论与 Webhook 事件。"""
    submission = get_submission(request.user, pk, mode="manage")
    reviewed = services.review_submission(
        submission,
        request.user,
        approve=True,
        conclusion=opt_str(request, "conclusion", opt_str(request, "note", "")),
    )
    return ok(submission_dict(reviewed))


@endpoint(("POST",))
def submission_reject(request, pk):
    """审核驳回：必须填写驳回理由。"""
    submission = get_submission(request.user, pk, mode="manage")
    conclusion = req_str(request, "conclusion", default=opt_str(request, "reason", ""))
    reviewed = services.review_submission(
        submission, request.user, approve=False, conclusion=conclusion
    )
    return ok(submission_dict(reviewed))


@endpoint(("GET", "POST"))
def submission_attachments(request, pk):
    """附件元数据列表（GET）/ 登记附件（POST，只存文件名/大小/hash）。"""
    submission = get_submission(request.user, pk, mode="view")
    can_manage = can_write(request.user, submission.form)
    can_upload = can_manage or submission.submitted_by_id == request.user.id
    if request.method == "GET":
        items = [
            attachment_dict(a) for a in submission.attachments.all().order_by("id")
        ]
        return ok({"items": items, "count": len(items)})
    if not can_upload:
        raise ValueError("无权为该提交登记附件")
    attachment = services.add_attachment(submission, request.user, request.data or {})
    return ok(attachment_dict(attachment))


# ---------------------------------------------------------------------------
# 审核任务
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def review_task_mine(request):
    """我的待审核任务（含过期标记）。"""
    from django.utils import timezone

    qs = (
        FormReviewTask.objects.filter(reviewer_id=request.user.id)
        .select_related("submission__form", "reviewer", "submission__owner")
        .order_by("status", "due_at", "-created_at")
    )
    status = opt_str(request, "status", "pending")
    if status:
        qs = qs.filter(status=status)
    if opt_bool(request, "overdue_only", False):
        qs = qs.filter(due_at__lt=timezone.now(), status="pending")
    items = []
    now = timezone.now()
    page = paginate(qs, request, review_task_dict)
    for item in page["items"]:
        task = qs.filter(pk=item["id"]).first()
        item["overdue"] = bool(task and task.due_at and task.due_at < now and task.status == "pending")
        items.append(item)
    page["items"] = items
    return ok(page)


@endpoint(("POST",))
def review_task_decide(request, pk):
    """处理审核任务：通过/驳回并同步提交状态。"""
    task = (
        FormReviewTask.objects.select_related("submission__form", "reviewer")
        .filter(pk=pk)
        .first()
    )
    if task is None:
        raise ValueError("审核任务不存在")
    form = task.submission.form
    if task.reviewer_id != request.user.id and not can_write(request.user, form):
        raise ValueError("无权处理该审核任务")
    if task.status != "pending":
        raise ValueError("该任务已处理")
    approve = opt_bool(request, "approve", True)
    conclusion = opt_str(request, "conclusion", opt_str(request, "note", ""))
    if not approve and not conclusion:
        raise ValueError("驳回必须填写理由")
    reviewed = services.review_submission(
        task.submission, request.user, approve=approve, conclusion=conclusion
    )
    task.refresh_from_db()
    return ok(
        {
            "task": review_task_dict(task),
            "submission": submission_dict(reviewed),
        }
    )


# ---------------------------------------------------------------------------
# 评论
# ---------------------------------------------------------------------------


def _commentable_form(request, pk):
    """评论入口的表单访问：管理者/可见者之外，允许该表单的填报人参与评论。"""
    form = FormDefinition.objects.filter(pk=pk).first()
    if form is None:
        raise ValueError("表单不存在")
    if can_write(request.user, form) or is_visible(form, request.user):
        return form
    if form.submissions.filter(submitted_by_id=request.user.id).exists():
        return form
    raise ValueError("无权查看该表单")


@endpoint(("GET", "POST"))
def form_comments(request, pk):
    """表单/提交评论列表（GET）/ 发表评论（POST）。"""
    form = _commentable_form(request, pk)
    if request.method == "GET":
        qs = FormComment.objects.filter(form=form, parent__isnull=True).select_related(
            "owner", "submission"
        )
        submission_id = opt_int(request, "submission_id")
        if submission_id:
            qs = qs.filter(submission_id=submission_id)
        if not can_write(request.user, form):
            qs = qs.filter(Q(visibility="public") | Q(owner_id=request.user.id))
        qs = qs.prefetch_related("replies__owner").order_by("-created_at", "-id")
        return ok(paginate(qs, request, comment_dict))
    body = req_str(request, "body", max_len=5000).strip()
    if not body:
        raise ValueError("评论内容不能为空")
    submission_id = opt_int(request, "submission_id")
    submission = None
    if submission_id:
        submission = FormSubmission.objects.filter(pk=submission_id, form=form).first()
        if submission is None:
            raise ValueError("提交不存在或不属于该表单")
    parent_id = opt_int(request, "parent_id")
    parent = None
    if parent_id:
        parent = FormComment.objects.filter(pk=parent_id, form=form).first()
        if parent is None:
            raise ValueError("父评论不存在")
    visibility = opt_str(request, "visibility", "internal", max_len=10)
    if visibility not in ("internal", "public"):
        raise ValueError("评论可见范围不合法")
    if not can_write(request.user, form):
        # 非表单管理者只能发公开评论，避免内部备注被外部用户写入
        visibility = "public"
    comment = FormComment.objects.create(
        owner=request.user,
        form=form,
        submission=submission,
        parent=parent,
        body=body,
        visibility=visibility,
    )
    return ok(comment_dict(comment))


@endpoint(("PATCH",))
def comment_resolve(request, pk):
    """标记评论已解决/未解决。"""
    comment = get_comment(request.user, pk, write=True)
    comment.resolved = opt_bool(request, "resolved", True)
    comment.save(update_fields=["resolved", "updated_at"])
    return ok(comment_dict(comment))
