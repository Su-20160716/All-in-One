# -*- coding: utf-8 -*-
"""formstudio 通用助手：入参解析、分页、对象渲染与行级权限收口。

为什么单独一层
--------------
- 视图里大量重复的「取 JSON 参数 / 取对象 / 判可见性 / 统一列表结构」集中到这里，
  避免每个接口各写一套口径导致分页上限、错误文案不一致；
- 对象渲染统一在这里定义，服务层的统计结构可以复用同一份字段命名；
- 写权限与读权限严格区分：列表/详情走 core.scoping 的可见范围，
  写操作只认 owner（表单创建者），与平台其他模块保持一致。
"""
from datetime import datetime

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.scoping import can_write, is_visible, scope_queryset, visible_user_ids

from devtools.common import p

from formstudio.models import (
    FormAttachment,
    FormComment,
    FormDefinition,
    FormField,
    FormFieldOption,
    FormLogicRule,
    FormReviewTask,
    FormSection,
    FormShareLink,
    FormSubmission,
    FormSubmissionValue,
    FormTemplate,
    FormValidation,
    FormVersion,
    FormWebhook,
    FormWebhookDelivery,
)


# ---------------------------------------------------------------------------
# 入参解析
# ---------------------------------------------------------------------------


def json_param(request, key, default=None):
    """取任意 JSON 参数（dict/list/标量均可），GET 下走 query_params。"""
    data = p(request, key, default)
    return data


def json_obj(request, key, default=None, required=False):
    """取对象型参数；required=True 时缺失或类型不符抛中文错误。"""
    val = p(request, key)
    if val is None or val == "":
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return {} if default is None else default
    if not isinstance(val, dict):
        if isinstance(val, str):
            # 表单提交可能把 JSON 作为字符串传入（multipart/表单场景）
            import json

            try:
                val = json.loads(val)
            except (TypeError, ValueError):
                raise ValueError(f"参数 {key} 必须是对象")
        else:
            raise ValueError(f"参数 {key} 必须是对象")
    return val


def json_list(request, key, default=None, required=False, max_len=5000):
    """取数组型参数，兼容 JSON 字符串，并限制元素数量防止超大 payload。"""
    val = p(request, key)
    if val is None or val == "":
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return [] if default is None else default
    if isinstance(val, str):
        import json

        try:
            val = json.loads(val)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 必须是数组")
    if not isinstance(val, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(val) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    return val


def int_param(request, key, default=None, minimum=None, maximum=None):
    """整数参数解析：拒绝布尔与浮点字符串，避免 True 被当成 1。"""
    val = p(request, key)
    if val is None or val == "":
        if default is None:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    if isinstance(val, bool):
        raise ValueError(f"参数 {key} 必须是整数")
    try:
        out = int(str(val).strip())
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是整数")
    if minimum is not None and out < minimum:
        raise ValueError(f"参数 {key} 不能小于 {minimum}")
    if maximum is not None and out > maximum:
        raise ValueError(f"参数 {key} 不能大于 {maximum}")
    return out


def opt_int(request, key, default=None, minimum=None, maximum=None):
    """可选整数。"""
    val = p(request, key)
    if val is None or val == "":
        return default
    return int_param(request, key, default=default, minimum=minimum, maximum=maximum)


def parse_dt(value):
    """宽松解析 ISO 日期/日期时间；非法值抛中文错误。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    text = str(value).strip().replace("Z", "+00:00")
    dt = parse_datetime(text)
    if dt is None:
        d = parse_date(text[:10])
        if d is not None:
            dt = datetime(d.year, d.month, d.day)
    if dt is None:
        raise ValueError(f"时间格式不合法: {value}")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def opt_dt(request, key):
    """可选时间参数。"""
    return parse_dt(p(request, key))


def opt_date(request, key):
    """可选日期参数（返回 date）。"""
    val = p(request, key)
    if not val:
        return None
    d = parse_date(str(val)[:10])
    if d is None:
        raise ValueError(f"日期格式不合法: {val}")
    return d


def iso(dt):
    """时间统一以 ISO 字符串下发，空值返回空串。"""
    return dt.isoformat() if dt else ""


def iso_date(d):
    """日期统一以 YYYY-MM-DD 下发。"""
    return d.isoformat() if d else ""


def clamp_page_size(value, default=20, maximum=200):
    """分页大小：服务端强制 1..200，前端再大也不放大查询。"""
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = default
    return max(1, min(maximum, size))


def paginate(qs, request, serializer, default_size=20):
    """统一列表结构：{"items", "count", "page", "page_size"}。"""
    page = max(1, int_param(request, "page", default=1))
    size = clamp_page_size(p(request, "page_size"), default=default_size)
    count = qs.count()
    start = (page - 1) * size
    rows = list(qs[start:start + size])
    return {
        "items": [serializer(o) for o in rows],
        "count": count,
        "page": page,
        "page_size": size,
    }


def apply_keyword(qs, request, fields):
    """按 q 做多字段 icontains 模糊搜索；空 q 原样返回。"""
    from django.db.models import Q

    q = (p(request, "q") or "").strip()
    if not q:
        return qs
    cond = Q()
    for field in fields:
        cond |= Q(**{f"{field}__icontains": q})
    return qs.filter(cond)


def apply_status(qs, request, field="status"):
    """按 status 精确过滤；空值表示不限。"""
    status = (p(request, "status") or "").strip()
    if status:
        qs = qs.filter(**{field: status})
    return qs


# ---------------------------------------------------------------------------
# 行级权限
# ---------------------------------------------------------------------------


def visible_forms(user):
    """当前用户可读的表单（数据范围）。"""
    return scope_queryset(FormDefinition.objects.all(), user)


def owned_forms(user):
    """当前用户可写的表单（严格 owner）。"""
    return FormDefinition.objects.filter(owner_id=getattr(user, "id", None))


def get_form(user, pk, write=False):
    """取表单：write=True 只允许创建者，否则按可见范围。"""
    if write:
        obj = owned_forms(user).filter(pk=pk).first()
        if obj is None:
            raise ValueError("表单不存在或无权修改")
        return obj
    obj = visible_forms(user).filter(pk=pk).first()
    if obj is None:
        raise ValueError("表单不存在或无权查看")
    return obj


def get_form_by_code(code, user=None):
    """按编码取表单（提交入口）；同一编码可能属于多个用户，优先取可见的。"""
    qs = FormDefinition.objects.filter(code=code)
    if user is not None and getattr(user, "is_authenticated", False):
        scoped = scope_queryset(qs, user)
        hit = scoped.order_by("-updated_at").first()
        if hit is not None:
            return hit
    return qs.order_by("-updated_at").first()


def visible_submissions(user):
    """可读提交：数据范围覆盖表单创建者，叠加本人作为填报人的记录。

    匿名提交 submitted_by 为空，只有表单创建者/数据范围可见者能看到，
    与「不记录填报人」的语义一致。
    """
    uid = getattr(user, "id", None)
    if uid is None:
        return FormSubmission.objects.none()
    ids = visible_user_ids(user)
    if ids is None:
        return FormSubmission.objects.all()
    # 用 Q 组合而非 queryset | queryset：scope_queryset 自带 distinct，
    # 直接 union 会触发「unique/non-unique query 不能合并」的报错。
    cond = Q(owner_id__in=ids) | Q(submitted_by_id=uid)
    return FormSubmission.objects.filter(cond).distinct()


def get_submission(user, pk, mode="view"):
    """取提交并按模式校验：

    - view   ：可见范围或本人填报；
    - edit   ：仅填报人，且必须是草稿；
    - manage ：仅表单创建者（审核/删除/附件）。
    """
    sub = FormSubmission.objects.select_related("form").filter(pk=pk).first()
    if sub is None:
        raise ValueError("提交记录不存在")
    if mode == "manage":
        if not can_write(user, sub.form):
            raise ValueError("无权管理该提交")
        return sub
    if mode == "edit":
        if sub.submitted_by_id != getattr(user, "id", None):
            raise ValueError("只能修改自己填写的草稿")
        if sub.status != "draft":
            raise ValueError("只有草稿可以修改")
        return sub
    ids = visible_user_ids(user)
    owner_ok = ids is None or sub.owner_id in ids
    if not (owner_ok or sub.submitted_by_id == getattr(user, "id", None)):
        raise ValueError("无权查看该提交")
    return sub


def get_section(user, pk, write=False):
    """取分区。"""
    obj = FormSection.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("分区不存在")
    _ensure_form_access(user, obj.form, write)
    return obj


def get_field(user, pk, write=False):
    """取字段。"""
    obj = FormField.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("字段不存在")
    _ensure_form_access(user, obj.form, write)
    return obj


def get_validation(user, pk, write=False):
    """取校验规则。"""
    obj = (
        FormValidation.objects.select_related("field__form")
        .filter(pk=pk)
        .first()
    )
    if obj is None:
        raise ValueError("校验规则不存在")
    _ensure_form_access(user, obj.field.form, write)
    return obj


def get_logic(user, pk, write=False):
    """取逻辑规则。"""
    obj = FormLogicRule.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("逻辑规则不存在")
    _ensure_form_access(user, obj.form, write)
    return obj


def get_version(user, pk):
    """取版本并校验表单可见性。"""
    obj = FormVersion.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("版本不存在")
    _ensure_form_access(user, obj.form, False)
    return obj


def get_share_link(user, pk, write=False):
    """取分享链接。"""
    obj = FormShareLink.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("分享链接不存在")
    _ensure_form_access(user, obj.form, write)
    return obj


def get_webhook(user, pk, write=False):
    """取 Webhook。"""
    obj = FormWebhook.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("Webhook 不存在")
    _ensure_form_access(user, obj.form, write)
    return obj


def get_template(user, pk):
    """取模板：内置模板对所有登录用户可用，自建模板仅本人可用。"""
    obj = FormTemplate.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("模板不存在")
    if obj.owner_id != getattr(user, "id", None) and not obj.builtin:
        raise ValueError("无权使用该模板")
    return obj


def get_comment(user, pk, write=False):
    """取评论：写权限按表单 owner 或评论作者收口。"""
    obj = FormComment.objects.select_related("form").filter(pk=pk).first()
    if obj is None:
        raise ValueError("评论不存在")
    if write:
        if obj.owner_id != getattr(user, "id", None) and not can_write(user, obj.form):
            raise ValueError("无权修改该评论")
        return obj
    _ensure_form_access(user, obj.form, False)
    return obj


def _ensure_form_access(user, form, write):
    """表单访问判定：写只认 owner，读走可见范围。"""
    if write:
        if not can_write(user, form):
            raise ValueError("无权修改该表单")
        return
    if not is_visible(form, user) and form.owner_id != getattr(user, "id", None):
        # 表单创建者天然可见，其余按数据范围
        raise ValueError("无权查看该表单")


# ---------------------------------------------------------------------------
# 对象渲染
# ---------------------------------------------------------------------------


def user_brief(user):
    """用户简要信息，匿名/已删用户返回 None。"""
    if user is None or not getattr(user, "pk", None):
        return None
    return {
        "id": user.pk,
        "username": getattr(user, "username", ""),
        "name": getattr(user, "display_name", None) or getattr(user, "username", ""),
    }


def form_dict(form, counts=None):
    """表单定义渲染；counts 可传入已聚合的字段/分区数量避免 N+1。"""
    counts = counts or {}
    return {
        "id": form.pk,
        "code": form.code,
        "name": form.name,
        "description": form.description,
        "form_type": form.form_type,
        "status": form.status,
        "allow_anonymous": form.allow_anonymous,
        "allow_multiple": form.allow_multiple,
        "deadline": iso(form.deadline),
        "theme": form.theme or {},
        "settings": form.settings or {},
        "submit_message": form.submit_message,
        "redirect_url": form.redirect_url,
        "submission_count": form.submission_count,
        "view_count": form.view_count,
        "field_count": counts.get("fields", getattr(form, "field_count", None)),
        "section_count": counts.get("sections", getattr(form, "section_count", None)),
        "is_open": form.is_open(),
        "is_expired": form.is_expired(),
        "block_reason": form.submit_block_reason(),
        "owner": user_brief(form.owner),
        "published_at": iso(form.published_at),
        "closed_at": iso(form.closed_at),
        "archived_at": iso(form.archived_at),
        "created_at": iso(form.created_at),
        "updated_at": iso(form.updated_at),
    }


def section_dict(section, with_fields=False, fields=None):
    """分区渲染；with_fields 时附带其字段。"""
    data = {
        "id": section.pk,
        "form_id": section.form_id,
        "key": section.key,
        "title": section.title,
        "description": section.description,
        "order": section.order,
        "collapsible": section.collapsible,
        "condition": section.condition or {},
        "field_count": len(fields) if fields is not None else None,
        "created_at": iso(section.created_at),
        "updated_at": iso(section.updated_at),
    }
    if with_fields:
        data["fields"] = [field_dict(f) for f in (fields or [])]
    return data


def option_dict(option):
    """选项渲染。"""
    if isinstance(option, dict):
        return {
            "value": option.get("value", ""),
            "label": option.get("label", ""),
            "score": option.get("score", 0),
            "disabled": bool(option.get("disabled", False)),
        }
    return {
        "id": option.pk,
        "value": option.value,
        "label": option.label,
        "order": option.order,
        "score": option.score,
        "disabled": option.disabled,
    }


def field_dict(field, with_rules=False):
    """字段渲染；with_rules 时附带独立校验规则。"""
    data = {
        "id": field.pk,
        "form_id": field.form_id,
        "section_id": field.section_id,
        "key": field.key,
        "label": field.label,
        "field_type": field.field_type,
        "required": field.required,
        "default_value": field.default_value,
        "placeholder": field.placeholder,
        "help_text": field.help_text,
        "order": field.order,
        "width": field.width,
        "options": [option_dict(o) for o in field.option_items()],
        "validation": field.validation or {},
        "condition": field.condition or {},
        "created_at": iso(field.created_at),
        "updated_at": iso(field.updated_at),
    }
    if with_rules:
        data["validations"] = [
            validation_dict(v) for v in field.validation_rules.all().order_by("order", "id")
        ]
    return data


def validation_dict(rule):
    """校验规则渲染。"""
    return {
        "id": rule.pk,
        "field_id": rule.field_id,
        "field_key": getattr(rule.field, "key", ""),
        "rule_type": rule.rule_type,
        "params": rule.params or {},
        "message": rule.message,
        "target_key": rule.target_key,
        "order": rule.order,
        "enabled": rule.enabled,
    }


def logic_dict(rule):
    """逻辑规则渲染。"""
    return {
        "id": rule.pk,
        "form_id": rule.form_id,
        "name": rule.name,
        "condition": rule.condition or {},
        "action": rule.action,
        "target_key": rule.target_key,
        "value": rule.value,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "created_at": iso(rule.created_at),
    }


def version_dict(version, with_schema=False):
    """版本渲染；列表默认不带完整 schema。"""
    data = {
        "id": version.pk,
        "form_id": version.form_id,
        "version_no": version.version_no,
        "status": version.status,
        "note": version.note,
        "changelog": version.changelog,
        "is_current": version.is_current,
        "field_count": version.field_count(),
        "section_count": version.section_count(),
        "published_by": user_brief(version.published_by),
        "published_at": iso(version.published_at),
        "created_at": iso(version.created_at),
    }
    if with_schema:
        data["schema"] = version.schema or {}
    return data


def submission_dict(sub, with_values=False, with_attachments=False):
    """提交渲染；详情接口才展开 values/attachments。"""
    data = {
        "id": sub.pk,
        "form_id": sub.form_id,
        "form_name": getattr(sub.form, "name", ""),
        "status": sub.status,
        "score": sub.score,
        "max_score": sub.max_score,
        "duration_seconds": sub.duration_seconds,
        "version_no": sub.version_no,
        "version_id": sub.version_id,
        "submitted_by": user_brief(sub.submitted_by),
        "owner": user_brief(sub.owner),
        "source": sub.source,
        "ip": sub.ip,
        "user_agent": sub.user_agent,
        "answers_count": sub.answers_count,
        "data": sub.data or {},
        "submitted_at": iso(sub.submitted_at),
        "reviewed_at": iso(sub.reviewed_at),
        "review_note": sub.review_note,
        "created_at": iso(sub.created_at),
        "updated_at": iso(sub.updated_at),
    }
    if with_values:
        data["values"] = [value_dict(v) for v in sub.values.all().order_by("field_key")]
    if with_attachments:
        data["attachments"] = [
            attachment_dict(a) for a in sub.attachments.all().order_by("id")
        ]
    return data


def value_dict(value):
    """填报值渲染：同时给出原始值与强类型值，前端可自行取用。"""
    return {
        "id": value.pk,
        "field_key": value.field_key,
        "field_type": value.field_type,
        "raw": value.raw,
        "text": value.text_value,
        "number": value.number_value,
        "date": iso(value.date_value),
        "score": value.score,
    }


def attachment_dict(att):
    """附件元数据渲染（不提供下载地址，因为文件不落地）。"""
    return {
        "id": att.pk,
        "submission_id": att.submission_id,
        "field_key": att.field_key,
        "file_name": att.file_name,
        "file_size": att.file_size,
        "content_hash": att.content_hash,
        "mime_type": att.mime_type,
        "remark": att.remark,
        "uploaded_by": user_brief(att.uploaded_by),
        "created_at": iso(att.created_at),
    }


def share_link_dict(link):
    """分享链接渲染：不回传密码哈希。"""
    return {
        "id": link.pk,
        "form_id": link.form_id,
        "token": link.token,
        "label": link.label,
        "requires_password": link.requires_password(),
        "expires_at": iso(link.expires_at),
        "max_uses": link.max_uses,
        "used_count": link.used_count,
        "remaining_uses": link.remaining_uses(),
        "active": link.active,
        "is_expired": link.is_expired(),
        "last_used_at": iso(link.last_used_at),
        "created_at": iso(link.created_at),
    }


def webhook_dict(hook):
    """Webhook 渲染：密钥脱敏。"""
    return {
        "id": hook.pk,
        "form_id": hook.form_id,
        "url": hook.url,
        "event": hook.event,
        "secret_masked": hook.masked_secret(),
        "headers": hook.headers or {},
        "enabled": hook.enabled,
        "max_retries": hook.max_retries,
        "timeout_seconds": hook.timeout_seconds,
        "failure_count": hook.failure_count,
        "last_status": hook.last_status,
        "last_error": hook.last_error,
        "last_delivery_at": iso(hook.last_delivery_at),
        "created_at": iso(hook.created_at),
    }


def delivery_dict(delivery):
    """投递记录渲染。"""
    return {
        "id": delivery.pk,
        "webhook_id": delivery.webhook_id,
        "event": delivery.event,
        "status": delivery.status,
        "attempt": delivery.attempt,
        "response_code": delivery.response_code,
        "signature": delivery.signature,
        "error": delivery.error,
        "duration_ms": delivery.duration_ms,
        "next_retry_at": iso(delivery.next_retry_at),
        "payload": delivery.payload or {},
        "created_at": iso(delivery.created_at),
    }


def template_dict(template, with_schema=False):
    """模板渲染。"""
    data = {
        "id": template.pk,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "form_type": template.form_type,
        "builtin": template.builtin,
        "usage_count": template.usage_count,
        "tags": template.tags or [],
        "field_count": len((template.schema or {}).get("fields") or []),
        "created_at": iso(template.created_at),
    }
    if with_schema:
        data["schema"] = template.schema or {}
    return data


def review_task_dict(task):
    """审核任务渲染。"""
    return {
        "id": task.pk,
        "submission_id": task.submission_id,
        "form_id": getattr(task.submission, "form_id", None),
        "form_name": getattr(getattr(task.submission, "form", None), "name", ""),
        "reviewer": user_brief(task.reviewer),
        "status": task.status,
        "conclusion": task.conclusion,
        "priority": task.priority,
        "due_at": iso(task.due_at),
        "decided_at": iso(task.decided_at),
        "created_at": iso(task.created_at),
    }


def comment_dict(comment, with_replies=True):
    """评论渲染；replies 一层展开即可，深层回复由前端按 parent 归并。"""
    data = {
        "id": comment.pk,
        "form_id": comment.form_id,
        "submission_id": comment.submission_id,
        "parent_id": comment.parent_id,
        "body": comment.body,
        "visibility": comment.visibility,
        "resolved": comment.resolved,
        "author": user_brief(comment.owner),
        "created_at": iso(comment.created_at),
    }
    if with_replies:
        data["replies"] = [comment_dict(r, with_replies=False) for r in comment.replies.all()]
    return data


def snapshot_dict(snapshot):
    """分析快照渲染。"""
    return {
        "date": iso_date(snapshot.date),
        "submissions": snapshot.submissions,
        "drafts": snapshot.drafts,
        "reviews": snapshot.reviews,
        "avg_score": snapshot.avg_score,
        "avg_duration": snapshot.avg_duration,
        "completion_rate": snapshot.completion_rate,
        "viewed": snapshot.viewed,
        "started": snapshot.started,
        "detail": snapshot.detail or {},
    }
