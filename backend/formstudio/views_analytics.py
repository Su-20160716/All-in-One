# -*- coding: utf-8 -*-
"""formstudio 运营接口：统计聚合、CSV 导出、分享链接、Webhook 与模板目录。

- 统计接口只读，默认以「有效提交」为口径（submitted/reviewed），草稿不计入；
- CSV 导出仅表单创建者可用，导出前统一做公式注入转义；
- Webhook 测试投递同样走入库模拟，返回真实的状态/签名/重试时间；
- 模板目录首次访问时懒创建内置模板，避免引入数据迁移。
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core.scoping import can_write

from devtools.common import (endpoint, ok, opt_bool, opt_str, p, req_str)

from formstudio import services
from formstudio.common import (
    delivery_dict,
    form_dict,
    get_form,
    get_share_link,
    get_template,
    get_webhook,
    int_param,
    json_obj,
    opt_date,
    opt_dt,
    opt_int,
    paginate,
    share_link_dict,
    snapshot_dict,
    template_dict,
    visible_forms,
    webhook_dict,
)
from formstudio.models import (
    WEBHOOK_EVENT_CHOICES,
    FormShareLink,
    FormTemplate,
    FormWebhook,
    FormWebhookDelivery,
)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def form_stats(request, pk):
    """表单统计概览：状态/来源/版本分布、均分、均耗时、完成率与待审数。"""
    form = get_form(request.user, pk)
    data = services.aggregate_overview(form)
    data["webhooks"] = services.webhook_stats(form)
    latest = form.snapshots.order_by("-date").first()
    data["latest_snapshot"] = snapshot_dict(latest) if latest else None
    return ok(data)


@endpoint(("GET",))
def form_stats_fields(request, pk):
    """字段分布：选项占比、数值统计、文本 Top、矩阵交叉与附件计数。"""
    form = get_form(request.user, pk)
    field_key = opt_str(request, "field_key", "", max_len=64).strip() or None
    return ok(services.field_distribution(form, field_key=field_key))


@endpoint(("GET",))
def form_stats_trend(request, pk):
    """按日趋势（默认 30 天，自动补齐空缺日期）。"""
    form = get_form(request.user, pk)
    days = opt_int(request, "days", default=30, minimum=1, maximum=365)
    return ok(services.daily_trend(form, days=days))


@endpoint(("GET",))
def form_stats_duration(request, pk):
    """填写耗时统计：均值/中位数/分位与耗时分布桶。"""
    form = get_form(request.user, pk)
    return ok(services.duration_stats(form))


@endpoint(("GET", "POST"))
def form_stats_snapshots(request, pk):
    """分析快照列表（GET）/ 生成指定日期快照（POST）。"""
    if request.method == "POST":
        form = get_form(request.user, pk, write=True)
        day = opt_date(request, "date") or timezone.localdate()
        snapshot = services.build_daily_snapshot(form, day)
        return ok(snapshot_dict(snapshot))
    form = get_form(request.user, pk)
    days = opt_int(request, "days", default=30, minimum=1, maximum=365)
    start = timezone.localdate() - timedelta(days=days - 1)
    qs = form.snapshots.filter(date__gte=start).order_by("-date")
    return ok(paginate(qs, request, snapshot_dict, default_size=30))


@endpoint(("GET",))
def form_export(request, pk):
    """导出 CSV：仅创建者可用，默认导出有效提交并做公式注入防护。"""
    form = get_form(request.user, pk, write=True)
    qs = form.submissions.all().select_related("submitted_by").prefetch_related("values")
    status = opt_str(request, "status", "", max_len=20)
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.filter(status__in=("submitted", "reviewed")).exclude(status="draft")
    source = opt_str(request, "source", "")
    if source:
        qs = qs.filter(source=source)
    version_no = opt_int(request, "version_no")
    if version_no:
        qs = qs.filter(version_no=version_no)
    limit = opt_int(request, "limit", default=5000, minimum=1, maximum=20000)
    rows = list(qs.order_by("id")[:limit])
    result = services.export_submissions_csv(form, rows, include_meta=True)
    result["truncated"] = qs.count() > len(rows)
    result["total"] = qs.count()
    result["form_id"] = form.pk
    return ok(result)


# ---------------------------------------------------------------------------
# 分享链接
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def form_share_links(request, pk):
    """表单分享链接列表（GET）/ 创建（POST，可设密码/过期/次数上限）。"""
    form = get_form(request.user, pk)
    if request.method == "GET":
        qs = form.share_links.all().order_by("-created_at")
        if not opt_bool(request, "include_inactive", True):
            qs = qs.filter(active=True)
        return ok(paginate(qs, request, share_link_dict))
    if not can_write(request.user, form):
        raise ValueError("无权创建分享链接")
    expires_at = opt_dt(request, "expires_at")
    if expires_at and expires_at <= timezone.now():
        raise ValueError("过期时间必须晚于当前时间")
    link = services.create_share_link(
        form,
        request.user,
        label=opt_str(request, "label", "", max_len=120),
        password=opt_str(request, "password", "", max_len=128),
        expires_at=expires_at,
        max_uses=opt_int(request, "max_uses", default=0, minimum=0, maximum=1000000),
    )
    return ok(share_link_dict(link))


@endpoint(("GET",))
def share_link_list(request):
    """分享链接总览：按表单/状态过滤，仅可见表单下的链接。"""
    qs = FormShareLink.objects.filter(form__in=visible_forms(request.user)).select_related(
        "form"
    )
    form_id = opt_int(request, "form_id")
    if form_id:
        qs = qs.filter(form_id=form_id)
    token = opt_str(request, "token", "", max_len=64).strip()
    if token:
        qs = qs.filter(token=token)
    if opt_bool(request, "active_only", False):
        qs = qs.filter(active=True)
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, share_link_dict))


@endpoint(("GET", "POST"))
def share_link_verify(request):
    """核验分享链接（不消费次数），返回表单结构与剩余次数。"""
    token = req_str(request, "token", max_len=128).strip()
    link = services.verify_share_link(token, p(request, "password"))
    form = link.form
    version = services.current_version(form)
    schema = (version.schema if version else None) or services.schema_from_form(form)
    return ok(
        {
            "link": share_link_dict(link),
            "form": form_dict(form),
            "schema": schema,
            "can_submit": form.is_open(),
            "block_reason": form.submit_block_reason(),
            "remaining_uses": link.remaining_uses(),
        }
    )


@endpoint(("POST",))
def share_link_disable(request, pk):
    """停用分享链接（保留历史提交的关联）。"""
    link = get_share_link(request.user, pk, write=True)
    link.active = False
    link.save(update_fields=["active", "updated_at"])
    return ok(share_link_dict(link))


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def _webhook_payload_from_request(request):
    """从请求中解析 Webhook 配置并做边界校验。"""
    url = req_str(request, "url", max_len=500).strip()
    services.validate_webhook_url(url)
    event = opt_str(request, "event", "submission.created", max_len=40)
    if event not in dict(WEBHOOK_EVENT_CHOICES):
        raise ValueError(f"事件类型不合法: {event}")
    return {
        "url": url,
        "event": event,
        "secret": opt_str(request, "secret", "", max_len=128),
        "headers": json_obj(request, "headers"),
        "enabled": opt_bool(request, "enabled", True),
        "max_retries": opt_int(request, "max_retries", default=3, minimum=0, maximum=10),
        "timeout_seconds": opt_int(request, "timeout_seconds", default=5, minimum=1, maximum=60),
    }


@endpoint(("GET", "POST"))
def webhook_collection(request):
    """Webhook 列表（GET）/ 创建（POST）。"""
    if request.method == "GET":
        qs = FormWebhook.objects.filter(form__in=visible_forms(request.user)).select_related(
            "form"
        )
        form_id = opt_int(request, "form_id")
        if form_id:
            qs = qs.filter(form_id=form_id)
        if opt_bool(request, "enabled_only", False):
            qs = qs.filter(enabled=True)
        event = opt_str(request, "event", "")
        if event:
            qs = qs.filter(event=event)
        qs = qs.order_by("-created_at", "-id")
        return ok(paginate(qs, request, webhook_dict))
    form = get_form(request.user, int_param(request, "form_id"), write=True)
    hook = FormWebhook.objects.create(
        owner=form.owner, form=form, **_webhook_payload_from_request(request)
    )
    return ok(webhook_dict(hook))


@endpoint(("GET", "PATCH", "DELETE"))
def webhook_item(request, pk):
    """Webhook 详情（GET）/ 更新（PATCH）/ 删除（DELETE）。"""
    hook = get_webhook(request.user, pk, write=request.method != "GET")
    if request.method == "GET":
        data = webhook_dict(hook)
        data["recent_deliveries"] = [
            delivery_dict(d) for d in hook.deliveries.all().order_by("-id")[:10]
        ]
        return ok(data)
    if request.method == "DELETE":
        hook.delete()
        return ok({"id": pk, "deleted": True})
    if request.data.get("url") is not None:
        hook.url = req_str(request, "url", max_len=500).strip()
        services.validate_webhook_url(hook.url)
    if request.data.get("event") is not None:
        event = opt_str(request, "event", hook.event, max_len=40)
        if event not in dict(WEBHOOK_EVENT_CHOICES):
            raise ValueError(f"事件类型不合法: {event}")
        hook.event = event
    if request.data.get("secret") is not None:
        hook.secret = opt_str(request, "secret", "", max_len=128)
    if request.data.get("headers") is not None:
        hook.headers = json_obj(request, "headers")
    if request.data.get("enabled") is not None:
        hook.enabled = opt_bool(request, "enabled")
    if request.data.get("max_retries") is not None:
        hook.max_retries = opt_int(request, "max_retries", minimum=0, maximum=10)
    if request.data.get("timeout_seconds") is not None:
        hook.timeout_seconds = opt_int(
            request, "timeout_seconds", minimum=1, maximum=60
        )
    hook.save()
    return ok(webhook_dict(hook))


@endpoint(("POST",))
def webhook_test(request, pk):
    """测试投递：构造合成事件并走完整模拟投递（状态/签名/重试时间都会落库）。"""
    hook = get_webhook(request.user, pk, write=True)
    payload = services.build_webhook_payload(
        "webhook.test",
        hook.form,
        extra={"webhook_id": hook.pk, "manual": True},
    )
    delivery = FormWebhookDelivery.objects.create(
        owner=hook.owner,
        webhook=hook,
        event="webhook.test",
        payload=payload,
        status="pending",
        attempt=1,
    )
    services.simulate_delivery(hook, delivery)
    return ok(
        {
            "webhook": webhook_dict(hook),
            "delivery": delivery_dict(delivery),
        }
    )


@endpoint(("GET",))
def webhook_deliveries(request, pk):
    """某个 Webhook 的投递记录（可按状态过滤）。"""
    hook = get_webhook(request.user, pk)
    qs = hook.deliveries.all().order_by("-created_at", "-id")
    status = opt_str(request, "status", "")
    if status:
        qs = qs.filter(status=status)
    event = opt_str(request, "event", "")
    if event:
        qs = qs.filter(event=event)
    return ok(paginate(qs, request, delivery_dict))


@endpoint(("POST",))
def delivery_retry(request, pk):
    """手动重试一次失败投递。"""
    delivery = (
        FormWebhookDelivery.objects.select_related("webhook__form")
        .filter(pk=pk)
        .first()
    )
    if delivery is None:
        raise ValueError("投递记录不存在")
    if not can_write(request.user, delivery.webhook.form):
        raise ValueError("无权重试该投递")
    delivery = services.retry_delivery(delivery)
    return ok(delivery_dict(delivery))


@endpoint(("GET",))
def delivery_list(request):
    """投递记录总览：按表单/Webhook/状态过滤（只含可见表单）。"""
    qs = FormWebhookDelivery.objects.filter(
        webhook__form__in=visible_forms(request.user)
    ).select_related("webhook")
    form_id = opt_int(request, "form_id")
    if form_id:
        qs = qs.filter(webhook__form_id=form_id)
    webhook_id = opt_int(request, "webhook_id")
    if webhook_id:
        qs = qs.filter(webhook_id=webhook_id)
    status = opt_str(request, "status", "")
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, delivery_dict))


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def template_list(request):
    """模板目录：内置模板懒创建 + 个人模板，支持分类/类型/关键字过滤。"""
    services.ensure_builtin_templates(request.user)
    qs = FormTemplate.objects.filter(Q(owner_id=request.user.id) | Q(builtin=True))
    qs = qs.filter(
        Q(name__icontains=opt_str(request, "q", ""))
        | Q(description__icontains=opt_str(request, "q", ""))
    ) if opt_str(request, "q", "").strip() else qs
    category = opt_str(request, "category", "")
    if category:
        qs = qs.filter(category=category)
    form_type = opt_str(request, "form_type", "")
    if form_type:
        qs = qs.filter(form_type=form_type)
    if opt_bool(request, "builtin_only", False):
        qs = qs.filter(builtin=True)
    qs = qs.order_by("-builtin", "-usage_count", "id")
    data = paginate(qs, request, template_dict)
    data["categories"] = sorted(
        set(
            FormTemplate.objects.filter(
                Q(owner_id=request.user.id) | Q(builtin=True)
            ).values_list("category", flat=True)
        )
    )
    return ok(data)


@endpoint(("GET",))
def template_detail(request, pk):
    """模板详情（含完整 schema，可直接渲染预览）。"""
    template = get_template(request.user, pk)
    return ok(template_dict(template, with_schema=True))


@endpoint(("POST",))
def template_instantiate(request, pk):
    """从模板实例化表单（草稿态，可继续编辑后发布）。"""
    template = get_template(request.user, pk)
    form = services.instantiate_template(
        template,
        request.user,
        code=opt_str(request, "code", "", max_len=64).strip(),
        name=opt_str(request, "name", "", max_len=200).strip(),
        settings=json_obj(request, "settings"),
    )
    return ok(
        {
            "form": form_dict(form),
            "template": template_dict(template),
            "schema": services.schema_from_form(form),
        }
    )
