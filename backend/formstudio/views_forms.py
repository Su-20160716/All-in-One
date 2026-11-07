# -*- coding: utf-8 -*-
"""formstudio 设计态接口：目录、表单 CRUD、发布/关闭/归档/克隆、版本、
分区、字段、校验规则与逻辑规则。

设计约定
--------
- 读接口走 core.scoping 的可见范围，写接口只认 owner（core.scoping.can_write）；
- 批量 schema 保存是唯一会「重建字段」的入口，单字段 CRUD 用于小步编辑；
- 发布即快照，之后的历史提交一律按快照版本统计。
"""
from django.db import transaction
from django.db.models import Count, Max

from devtools.common import (endpoint, endpoint_index, fail, ok, opt_bool, opt_num,
                             opt_str, p, req_str)

from formstudio import services
from formstudio.common import (
    apply_keyword,
    apply_status,
    field_dict,
    form_dict,
    get_field,
    get_form,
    get_logic,
    get_section,
    get_template,
    get_validation,
    get_version,
    int_param,
    iso,
    json_list,
    json_obj,
    logic_dict,
    opt_dt,
    opt_int,
    paginate,
    section_dict,
    template_dict,
    user_brief,
    validation_dict,
    version_dict,
    visible_forms,
)
from formstudio.models import (
    FIELD_TYPE_CHOICES,
    FORM_STATUS_CHOICES,
    FORM_TYPE_CHOICES,
    LOGIC_ACTION_CHOICES,
    VALIDATION_RULE_CHOICES,
    FormField,
    FormFieldOption,
    FormLogicRule,
    FormSection,
    FormValidation,
    FormVersion,
)
from formstudio.services import (
    FIELD_TYPE_REGISTRY,
    _normalize_option,
    assert_schema_valid,
    collect_schema_issues,
    schema_from_form,
)


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def catalog(request):
    """表单设计器目录：能力清单、字段类型注册表与全部接口明细。"""
    fields = [
        {
            "type": key,
            "label": spec["label"],
            "choice": spec["choice"],
        }
        for key, spec in FIELD_TYPE_REGISTRY.items()
    ]
    # 延迟导入避免 urls -> views 的循环依赖；catalog 需要路由表生成接口索引。
    from formstudio.urls import urlpatterns

    return ok(
        {
            "domain": "formstudio",
            "name": "表单设计器",
            "description": "可视化表单/问卷/测验/报名/审批，支持逻辑规则、计分、统计与 Webhook。",
            "form_types": [{"value": k, "label": v} for k, v in FORM_TYPE_CHOICES],
            "statuses": [{"value": k, "label": v} for k, v in FORM_STATUS_CHOICES],
            "field_types": fields,
            "validation_rules": [{"value": k, "label": v} for k, v in VALIDATION_RULE_CHOICES],
            "logic_actions": [{"value": k, "label": v} for k, v in LOGIC_ACTION_CHOICES],
            "capabilities": [
                "schema_design",
                "publish_versioning",
                "conditional_logic",
                "validation_engine",
                "quiz_scoring",
                "submission_review",
                "analytics",
                "csv_export",
                "share_links",
                "webhooks",
                "templates",
                "comments",
            ],
            "endpoints": endpoint_index(urlpatterns, exclude=("", "catalog/")),
            "endpoint_count": len(urlpatterns) - 2,
        }
    )


# ---------------------------------------------------------------------------
# 表单定义
# ---------------------------------------------------------------------------


def _has(request, key):
    """判断请求是否显式传了某字段（PATCH 语义：没传就不改）。"""
    if request.method == "GET":
        return key in request.query_params
    return isinstance(request.data, dict) and key in request.data


def _form_counts(form):
    """字段/分区数量，供 form_dict 渲染。"""
    return {
        "fields": form.fields.count(),
        "sections": form.sections.count(),
    }


def _form_type(value, default="survey"):
    """校验表单类型。"""
    value = str(value or default)
    if value not in dict(FORM_TYPE_CHOICES):
        raise ValueError(f"表单类型不合法: {value}")
    return value


def _form_status(value, default="draft"):
    """校验表单状态。"""
    value = str(value or default)
    if value not in dict(FORM_STATUS_CHOICES):
        raise ValueError(f"表单状态不合法: {value}")
    return value


def _validate_code(request, owner, exclude_pk=None):
    """表单编码：字母开头、用户内唯一。"""
    from formstudio.models import FormDefinition

    code = req_str(request, "code", max_len=64).strip()
    if not services.FIELD_KEY_RE.match(code.replace("-", "_")):
        raise ValueError("表单编码需字母开头，只能包含字母、数字、下划线或短横线")
    qs = FormDefinition.objects.filter(owner=owner, code=code)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValueError(f"表单编码已存在: {code}")
    return code


@endpoint(("GET", "POST"))
def form_collection(request):
    """表单列表（GET）/ 新建表单（POST）。"""
    if request.method == "POST":
        name = req_str(request, "name", max_len=200).strip()
        owner = request.user
        code = opt_str(request, "code", "", max_len=64).strip()
        if code:
            code = _validate_code(request, owner)
            # 未显式传 code 时上面不会走到，这里保持唯一性检查
        else:
            code = services.unique_form_code(owner, name)
        form_type = _form_type(opt_str(request, "form_type", "survey"))
        deadline = opt_dt(request, "deadline")
        form = FormDefinitionCreate(owner, code, name, form_type, request, deadline)
        return ok(form_dict(form))
    qs = visible_forms(request.user)
    qs = qs.select_related("owner")
    qs = apply_keyword(qs, request, ("name", "code", "description"))
    qs = apply_status(qs, request)
    if not p(request, "status") and not opt_bool(request, "include_archived", False):
        qs = qs.exclude(status="archived")
    form_type = opt_str(request, "form_type", "")
    if form_type:
        qs = qs.filter(form_type=form_type)
    return ok(paginate(qs, request, lambda f: form_dict(f, _form_counts(f))))


def FormDefinitionCreate(owner, code, name, form_type, request, deadline):
    """创建表单定义（独立函数便于单测替换，且集中处理可选字段）。"""
    from formstudio.models import FormDefinition

    return FormDefinition.objects.create(
        owner=owner,
        code=code,
        name=name,
        description=opt_str(request, "description"),
        form_type=form_type,
        status="draft",
        allow_anonymous=opt_bool(request, "allow_anonymous", False),
        allow_multiple=opt_bool(request, "allow_multiple", True),
        deadline=deadline,
        theme=json_obj(request, "theme"),
        settings=json_obj(request, "settings"),
        submit_message=opt_str(request, "submit_message", "提交成功，感谢参与。", max_len=300),
        redirect_url=opt_str(request, "redirect_url", "", max_len=500),
    )


@endpoint(("GET", "PATCH", "DELETE"))
def form_item(request, pk):
    """表单详情（GET）/ 更新元信息（PATCH）/ 删除（DELETE，仅无提交）。"""
    if request.method == "GET":
        form = get_form(request.user, pk)
        data = form_dict(form, _form_counts(form))
        data["sections"] = [
            section_dict(s) for s in form.sections.all().order_by("order", "id")
        ]
        data["fields"] = [
            field_dict(f)
            for f in form.fields.select_related("section").order_by("order", "id")
        ]
        data["logic"] = [
            logic_dict(r) for r in form.logic_rules.all().order_by("priority", "id")
        ]
        current = services.current_version(form)
        data["current_version"] = version_dict(current) if current else None
        return ok(data)
    form = get_form(request.user, pk, write=True)
    if request.method == "DELETE":
        if form.submissions.exclude(status="draft").exists():
            raise ValueError("表单已有提交，请先归档而不是删除")
        form.delete()
        return ok({"id": pk, "deleted": True})
    if _has(request, "name"):
        form.name = req_str(request, "name", max_len=200).strip()
    if _has(request, "description"):
        form.description = opt_str(request, "description")
    if _has(request, "form_type"):
        form.form_type = _form_type(opt_str(request, "form_type"))
    if _has(request, "deadline"):
        form.deadline = opt_dt(request, "deadline")
    if _has(request, "allow_anonymous"):
        form.allow_anonymous = opt_bool(request, "allow_anonymous")
    if _has(request, "allow_multiple"):
        form.allow_multiple = opt_bool(request, "allow_multiple")
    if _has(request, "theme"):
        form.theme = json_obj(request, "theme")
    if _has(request, "settings"):
        form.settings = json_obj(request, "settings")
    if _has(request, "submit_message"):
        form.submit_message = opt_str(request, "submit_message", "", max_len=300)
    if _has(request, "redirect_url"):
        form.redirect_url = opt_str(request, "redirect_url", "", max_len=500)
    if _has(request, "code"):
        form.code = _validate_code(request, form.owner, exclude_pk=form.pk)
    form.save()
    return ok(form_dict(form, _form_counts(form)))


@endpoint()
def form_publish(request, pk):
    """发布表单：校验 schema 并生成新版本快照。"""
    form = get_form(request.user, pk, write=True)
    version = services.publish_form(
        form,
        request.user,
        note=opt_str(request, "note", "", max_len=500),
        changelog=opt_str(request, "changelog"),
    )
    return ok(
        {
            "form": form_dict(form, _form_counts(form)),
            "version": version_dict(version),
        }
    )


@endpoint()
def form_close(request, pk):
    """关闭表单：停止接收新提交，历史数据保留。"""
    form = get_form(request.user, pk, write=True)
    if form.status != "published":
        raise ValueError("只有已发布表单可以关闭")
    from django.utils import timezone

    form.status = "closed"
    form.closed_at = timezone.now()
    form.save(update_fields=["status", "closed_at", "updated_at"])
    return ok(form_dict(form, _form_counts(form)))


@endpoint()
def form_archive(request, pk):
    """归档表单：从默认列表隐藏，数据与版本全部保留。"""
    form = get_form(request.user, pk, write=True)
    if form.status == "archived":
        raise ValueError("表单已归档")
    from django.utils import timezone

    form.status = "archived"
    form.archived_at = timezone.now()
    form.save(update_fields=["status", "archived_at", "updated_at"])
    return ok(form_dict(form, _form_counts(form)))


@endpoint()
def form_clone(request, pk):
    """克隆表单设计态（不复制提交、分享链接与 Webhook）。"""
    form = get_form(request.user, pk)
    clone = services.clone_form(
        form,
        request.user,
        code=opt_str(request, "code", "", max_len=64).strip(),
        name=opt_str(request, "name", "", max_len=200).strip(),
    )
    return ok(form_dict(clone, _form_counts(clone)))


@endpoint()
def form_save_as_template(request, pk):
    """把表单另存为个人模板。"""
    form = get_form(request.user, pk)
    template = services.save_form_as_template(
        form,
        request.user,
        name=opt_str(request, "name", "", max_len=180).strip(),
        category=opt_str(request, "category", "自建", max_len=40),
        description=opt_str(request, "description"),
    )
    return ok(template_dict(template))


@endpoint()
def form_from_template(request):
    """从模板创建表单（可覆盖编码/名称）。"""
    template_id = int_param(request, "template_id")
    template = get_template(request.user, template_id)
    form = services.instantiate_template(
        template,
        request.user,
        code=opt_str(request, "code", "", max_len=64).strip(),
        name=opt_str(request, "name", "", max_len=200).strip(),
        settings=json_obj(request, "settings"),
    )
    return ok(form_dict(form, _form_counts(form)))


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def form_version_list(request, pk):
    """表单版本列表（按版本号倒序）。"""
    form = get_form(request.user, pk)
    qs = form.versions.select_related("published_by").order_by("-version_no")
    return ok(paginate(qs, request, version_dict))


@endpoint(("GET",))
def version_detail(request, pk):
    """版本详情，可选携带完整 schema 快照。"""
    version = get_version(request.user, pk)
    with_schema = opt_bool(request, "with_schema", True)
    return ok(version_dict(version, with_schema=with_schema))


@endpoint(("GET", "POST"))
def version_compare(request, pk):
    """版本对比：字段增删改、分区变化与逻辑规则差异。"""
    form = get_form(request.user, pk)
    left_id = int_param(request, "left_id", default=opt_int(request, "from_id"))
    right_id = int_param(request, "right_id", default=opt_int(request, "to_id"))
    left = form.versions.filter(pk=left_id).first()
    right = form.versions.filter(pk=right_id).first()
    if left is None or right is None:
        raise ValueError("对比版本不存在或不属于该表单")
    return ok(services.diff_versions(left, right))


@endpoint()
def version_rollback(request, pk):
    """回滚到指定版本（写回设计态并发布为新版本）。"""
    version = get_version(request.user, pk)
    form = get_form(request.user, version.form_id, write=True)
    new_version = services.rollback_to_version(
        form, version, request.user, note=opt_str(request, "note", "", max_len=500)
    )
    return ok(
        {
            "form": form_dict(form, _form_counts(form)),
            "version": version_dict(new_version),
            "rolled_back_from": version.version_no,
        }
    )


# ---------------------------------------------------------------------------
# 分区
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def form_section_collection(request, pk):
    """分区列表（GET）/ 新建分区（POST）。"""
    if request.method == "GET":
        form = get_form(request.user, pk)
        return ok(
            {
                "items": [
                    section_dict(s) for s in form.sections.all().order_by("order", "id")
                ],
                "count": form.sections.count(),
            }
        )
    form = get_form(request.user, pk, write=True)
    key = req_str(request, "key", max_len=64).strip()
    if not services.FIELD_KEY_RE.match(key):
        raise ValueError("分区 key 需字母开头，只能包含字母、数字与下划线")
    if form.sections.filter(key=key).exists():
        raise ValueError(f"分区 key 已存在: {key}")
    max_order = form.sections.aggregate(value=Max("order"))["value"]
    section = FormSection.objects.create(
        owner=form.owner,
        form=form,
        key=key,
        title=opt_str(request, "title", key, max_len=200),
        description=opt_str(request, "description"),
        order=opt_int(request, "order", default=(max_order or 0) + 1),
        collapsible=opt_bool(request, "collapsible", False),
        condition=json_obj(request, "condition"),
    )
    return ok(section_dict(section))


@endpoint(("PATCH", "DELETE"))
def section_item(request, pk):
    """更新分区（PATCH）/ 删除分区（DELETE，字段移入未分组）。"""
    section = get_section(request.user, pk, write=True)
    if request.method == "DELETE":
        section.delete()
        return ok({"id": pk, "deleted": True})
    if _has(request, "key"):
        key = req_str(request, "key", max_len=64).strip()
        if not services.FIELD_KEY_RE.match(key):
            raise ValueError("分区 key 需字母开头，只能包含字母、数字与下划线")
        if section.form.sections.exclude(pk=section.pk).filter(key=key).exists():
            raise ValueError(f"分区 key 已存在: {key}")
        section.key = key
    if _has(request, "title"):
        section.title = req_str(request, "title", max_len=200)
    if _has(request, "description"):
        section.description = opt_str(request, "description")
    if _has(request, "order"):
        section.order = int_param(request, "order")
    if _has(request, "collapsible"):
        section.collapsible = opt_bool(request, "collapsible")
    if _has(request, "condition"):
        section.condition = json_obj(request, "condition")
    section.save()
    return ok(section_dict(section))


@endpoint()
def form_section_reorder(request, pk):
    """按 ids 或 keys 重排分区（事务内批量更新）。"""
    form = get_form(request.user, pk, write=True)
    ids = json_list(request, "ids")
    keys = json_list(request, "keys")
    if not ids and not keys:
        raise ValueError("缺少 ids 或 keys")
    with transaction.atomic():
        if ids:
            sections = list(form.sections.filter(pk__in=[int(i) for i in ids]))
        else:
            sections = list(form.sections.filter(key__in=[str(k) for k in keys]))
        if len(sections) != len(ids or keys):
            raise ValueError("存在不属于该表单的分区")
        order_map = {str(value): index for index, value in enumerate(ids or keys)}
        for section in sections:
            section.order = order_map[str(section.pk if ids else section.key)]
            section.save(update_fields=["order", "updated_at"])
    return ok(
        {
            "items": [
                section_dict(s) for s in form.sections.all().order_by("order", "id")
            ],
            "count": form.sections.count(),
        }
    )


# ---------------------------------------------------------------------------
# 字段
# ---------------------------------------------------------------------------


def _resolve_section(form, request):
    """字段分区：支持 section_id 或 section key，二者都不传为未分组。"""
    section_id = opt_int(request, "section_id")
    section_key = opt_str(request, "section", "", max_len=64).strip()
    if section_id:
        section = form.sections.filter(pk=section_id).first()
        if section is None:
            raise ValueError("分区不存在")
        return section
    if section_key:
        section = form.sections.filter(key=section_key).first()
        if section is None:
            raise ValueError(f"分区不存在: {section_key}")
        return section
    return None


def _normalize_options(payload):
    """选项数组规范化（value/label 必填、score 整数、值唯一）。"""
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("options 必须是数组")
    out = []
    seen = set()
    for option in payload:
        norm = _normalize_option(option)
        if norm["value"] in seen:
            raise ValueError(f"选项值重复: {norm['value']}")
        seen.add(norm["value"])
        out.append(norm)
    return out


def _field_type(value):
    """校验字段类型是否在注册表内。"""
    value = str(value or "text")
    if value not in FIELD_TYPE_REGISTRY:
        raise ValueError(f"字段类型不合法: {value}")
    return value


def _assert_field_options(field_type, options, validation):
    """选择题必须有选项；矩阵必须有行定义。"""
    if field_type in ("select", "multiselect") and not options:
        raise ValueError("选择题至少需要一个选项")
    if field_type == "matrix":
        if not options:
            raise ValueError("矩阵字段至少需要一列")
        rows = (validation or {}).get("rows") or []
        if not rows:
            raise ValueError("矩阵字段至少需要一行")


def _write_field_options(field, options):
    """同步选项子表与 JSON 快照。"""
    field.option_rows.all().delete()
    for index, option in enumerate(options):
        FormFieldOption.objects.create(
            owner=field.owner,
            field=field,
            value=option["value"],
            label=option["label"],
            order=index,
            score=option.get("score", 0),
            disabled=option.get("disabled", False),
        )
    field.options = options


@endpoint(("GET", "POST"))
def form_field_collection(request, pk):
    """字段列表（GET）/ 新建字段（POST）。"""
    if request.method == "GET":
        form = get_form(request.user, pk)
        qs = form.fields.select_related("section").order_by("order", "id")
        section_key = opt_str(request, "section", "")
        if section_key:
            qs = qs.filter(section__key=section_key)
        items = [field_dict(f, with_rules=True) for f in qs]
        return ok({"items": items, "count": len(items)})
    form = get_form(request.user, pk, write=True)
    key = req_str(request, "key", max_len=64).strip()
    if not services.FIELD_KEY_RE.match(key):
        raise ValueError("字段 key 需字母开头，只能包含字母、数字与下划线")
    if form.fields.filter(key=key).exists():
        raise ValueError(f"字段 key 已存在: {key}")
    field_type = _field_type(opt_str(request, "field_type", opt_str(request, "type", "text")))
    options = _normalize_options(json_list(request, "options"))
    validation = json_obj(request, "validation")
    _assert_field_options(field_type, options, validation)
    max_order = form.fields.aggregate(value=Max("order"))["value"]
    field = FormField(
        owner=form.owner,
        form=form,
        section=_resolve_section(form, request),
        key=key,
        label=opt_str(request, "label", key, max_len=200),
        field_type=field_type,
        required=opt_bool(request, "required", False),
        default_value=p(request, "default_value", p(request, "default")),
        placeholder=opt_str(request, "placeholder", "", max_len=200),
        help_text=opt_str(request, "help_text"),
        order=opt_int(request, "order", default=(max_order or 0) + 1),
        width=opt_str(request, "width", "full", max_len=10),
        validation=validation,
        condition=json_obj(request, "condition"),
    )
    if field.width not in ("full", "half", "third"):
        raise ValueError("字段宽度必须是 full/half/third")
    field.save()
    _write_field_options(field, options)
    field.save(update_fields=["options", "updated_at"])
    return ok(field_dict(field, with_rules=True))


@endpoint(("GET", "PATCH", "DELETE"))
def field_item(request, pk):
    """字段详情（GET）/ 更新（PATCH）/ 删除（DELETE）。"""
    field = get_field(request.user, pk, write=request.method != "GET")
    if request.method == "GET":
        return ok(field_dict(field, with_rules=True))
    if request.method == "DELETE":
        field.delete()
        return ok({"id": pk, "deleted": True})
    if _has(request, "key"):
        key = req_str(request, "key", max_len=64).strip()
        if not services.FIELD_KEY_RE.match(key):
            raise ValueError("字段 key 需字母开头，只能包含字母、数字与下划线")
        if field.form.fields.exclude(pk=field.pk).filter(key=key).exists():
            raise ValueError(f"字段 key 已存在: {key}")
        field.key = key
    if _has(request, "label"):
        field.label = req_str(request, "label", max_len=200)
    if _has(request, "field_type") or _has(request, "type"):
        field.field_type = _field_type(
            opt_str(request, "field_type", opt_str(request, "type", field.field_type))
        )
    if _has(request, "required"):
        field.required = opt_bool(request, "required")
    if _has(request, "default_value") or _has(request, "default"):
        field.default_value = p(request, "default_value", p(request, "default"))
    if _has(request, "placeholder"):
        field.placeholder = opt_str(request, "placeholder", "", max_len=200)
    if _has(request, "help_text"):
        field.help_text = opt_str(request, "help_text")
    if _has(request, "order"):
        field.order = int_param(request, "order")
    if _has(request, "width"):
        field.width = opt_str(request, "width", field.width, max_len=10)
        if field.width not in ("full", "half", "third"):
            raise ValueError("字段宽度必须是 full/half/third")
    if _has(request, "validation"):
        field.validation = json_obj(request, "validation")
    if _has(request, "condition"):
        field.condition = json_obj(request, "condition")
    if _has(request, "section_id") or _has(request, "section"):
        field.section = _resolve_section(field.form, request)
    options = None
    if _has(request, "options"):
        options = _normalize_options(json_list(request, "options"))
    _assert_field_options(
        field.field_type,
        options if options is not None else field.option_items(),
        field.validation,
    )
    field.save()
    if options is not None:
        _write_field_options(field, options)
        field.save(update_fields=["options", "updated_at"])
    return ok(field_dict(field, with_rules=True))


@endpoint()
def form_field_reorder(request, pk):
    """按 ids 或 keys 重排字段。"""
    form = get_form(request.user, pk, write=True)
    ids = json_list(request, "ids")
    keys = json_list(request, "keys")
    if not ids and not keys:
        raise ValueError("缺少 ids 或 keys")
    with transaction.atomic():
        if ids:
            fields = list(form.fields.filter(pk__in=[int(i) for i in ids]))
        else:
            fields = list(form.fields.filter(key__in=[str(k) for k in keys]))
        if len(fields) != len(ids or keys):
            raise ValueError("存在不属于该表单的字段")
        order_map = {str(value): index for index, value in enumerate(ids or keys)}
        for field in fields:
            field.order = order_map[str(field.pk if ids else field.key)]
            field.save(update_fields=["order", "updated_at"])
    return ok(
        {
            "items": [field_dict(f) for f in form.fields.all().order_by("order", "id")],
            "count": form.fields.count(),
        }
    )


@endpoint(("GET", "POST", "PUT"))
def form_schema(request, pk):
    """获取完整 schema（GET）/ 批量保存 schema（POST/PUT）。"""
    form = get_form(request.user, pk, write=request.method != "GET")
    if request.method == "GET":
        schema = schema_from_form(form)
        return ok(
            {
                "schema": schema,
                "issues": collect_schema_issues(schema),
                "summary": _schema_summary(form),
            }
        )
    payload = p(request, "schema")
    schema = payload if isinstance(payload, dict) else (
        request.data if isinstance(request.data, dict) else {}
    )
    counts = services.persist_schema(form, schema, owner=form.owner)
    form.refresh_from_db()
    return ok(
        {
            "counts": counts,
            "schema": schema_from_form(form),
            "summary": _schema_summary(form),
        }
    )


def _schema_summary(form):
    """schema 摘要：字段/分区/逻辑数 + 当前版本。"""
    version = services.current_version(form)
    return {
        "fields": form.fields.count(),
        "sections": form.sections.count(),
        "logic": form.logic_rules.count(),
        "validations": FormValidation.objects.filter(field__form=form).count(),
        "current_version": version.version_no if version else 0,
    }


@endpoint()
def form_schema_validate(request, pk):
    """只校验不改写：优先校验请求内的 schema，否则校验当前设计。"""
    form = get_form(request.user, pk)
    payload = p(request, "schema")
    schema = payload if isinstance(payload, dict) else schema_from_form(form)
    issues = collect_schema_issues(schema)
    return ok(
        {
            "valid": not issues,
            "issue_count": len(issues),
            "issues": issues,
            "summary": _schema_summary(form),
        }
    )


@endpoint(("GET", "POST"))
def field_options(request, pk):
    """字段选项列表（GET）/ 整体替换（POST）。"""
    field = get_field(request.user, pk, write=request.method != "GET")
    if request.method == "GET":
        return ok({"items": field.option_items(), "count": len(field.option_items())})
    options = _normalize_options(json_list(request, "options", required=True))
    _assert_field_options(field.field_type, options, field.validation)
    with transaction.atomic():
        _write_field_options(field, options)
        field.save(update_fields=["options", "updated_at"])
    return ok({"items": field.option_items(), "count": len(options)})


# ---------------------------------------------------------------------------
# 校验规则
# ---------------------------------------------------------------------------


def _rule_type(value):
    """校验规则类型合法化。"""
    value = str(value or "required")
    if value not in dict(VALIDATION_RULE_CHOICES):
        raise ValueError(f"校验规则类型不合法: {value}")
    return value


def _rule_params(rule_type, params):
    """按规则类型校验参数：min/max 要有 value，regex 要能编译，formula 要有 expr。"""
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    if rule_type in ("min", "max"):
        if "value" not in params and rule_type not in params:
            raise ValueError(f"{rule_type} 规则需要 params.value")
    if rule_type == "length" and "min" not in params and "max" not in params:
        raise ValueError("length 规则需要 params.min 或 params.max")
    if rule_type == "regex":
        pattern = params.get("pattern")
        if not pattern:
            raise ValueError("regex 规则需要 params.pattern")
        if len(str(pattern)) > 500:
            raise ValueError("正则表达式过长")
        import re

        try:
            re.compile(str(pattern))
        except re.error:
            raise ValueError("正则表达式不合法")
    if rule_type == "formula":
        expr = params.get("expr")
        if not expr:
            raise ValueError("formula 规则需要 params.expr")
        try:
            services.formula_field_refs(expr)
        except ValueError as exc:
            raise ValueError(str(exc))
    return params


def _resolve_validation_field(form, request):
    """校验规则的目标字段：支持 field_id 或 field_key。"""
    field_id = opt_int(request, "field_id")
    if field_id:
        field = form.fields.filter(pk=field_id).first()
        if field is None:
            raise ValueError("字段不存在")
        return field
    key = opt_str(request, "field_key", opt_str(request, "key", ""), max_len=64).strip()
    if not key:
        raise ValueError("缺少 field_id 或 field_key")
    field = form.fields.filter(key=key).first()
    if field is None:
        raise ValueError(f"字段不存在: {key}")
    return field


@endpoint(("GET",))
def form_validation_list(request, pk):
    """表单校验规则列表（可按字段过滤）。"""
    form = get_form(request.user, pk)
    qs = FormValidation.objects.filter(field__form=form).select_related("field")
    field_key = opt_str(request, "field_key", "")
    if field_key:
        qs = qs.filter(field__key=field_key)
    rule_type = opt_str(request, "rule_type", "")
    if rule_type:
        qs = qs.filter(rule_type=rule_type)
    qs = qs.order_by("field__order", "order", "id")
    return ok(paginate(qs, request, validation_dict))


@endpoint(("POST",))
def validation_create(request):
    """为字段新增独立校验规则。"""
    form = get_form(request.user, int_param(request, "form_id"), write=True)
    field = _resolve_validation_field(form, request)
    rule_type = _rule_type(opt_str(request, "rule_type", "required"))
    params = json_obj(request, "params")
    _rule_params(rule_type, params)
    max_order = field.validation_rules.aggregate(value=Max("order"))["value"]
    rule = FormValidation.objects.create(
        owner=form.owner,
        field=field,
        rule_type=rule_type,
        params=params,
        message=opt_str(request, "message", "", max_len=300),
        target_key=opt_str(request, "target_key", "", max_len=64),
        order=opt_int(request, "order", default=(max_order or 0) + 1),
        enabled=opt_bool(request, "enabled", True),
    )
    return ok(validation_dict(rule))


@endpoint(("PATCH", "DELETE"))
def validation_item(request, pk):
    """更新（PATCH）/ 删除（DELETE）校验规则。"""
    rule = get_validation(request.user, pk, write=True)
    if request.method == "DELETE":
        rule.delete()
        return ok({"id": pk, "deleted": True})
    if _has(request, "rule_type"):
        rule.rule_type = _rule_type(opt_str(request, "rule_type"))
    if _has(request, "params"):
        rule.params = json_obj(request, "params")
        _rule_params(rule.rule_type, rule.params)
    if _has(request, "message"):
        rule.message = opt_str(request, "message", "", max_len=300)
    if _has(request, "target_key"):
        rule.target_key = opt_str(request, "target_key", "", max_len=64)
    if _has(request, "order"):
        rule.order = int_param(request, "order")
    if _has(request, "enabled"):
        rule.enabled = opt_bool(request, "enabled")
    rule.save()
    return ok(validation_dict(rule))


# ---------------------------------------------------------------------------
# 逻辑规则
# ---------------------------------------------------------------------------


def _logic_cycle(form, exclude_id=None, extra=None):
    """在现有规则基础上判定是否形成环（只报 logic_cycle 问题）。"""
    schema = schema_from_form(form)
    qs = form.logic_rules.all()
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    rules = [
        {
            "name": rule.name,
            "condition": rule.condition or {},
            "action": rule.action,
            "target_key": rule.target_key,
            "value": rule.value,
            "priority": rule.priority,
            "enabled": rule.enabled,
        }
        for rule in qs
    ]
    if extra:
        rules.append(extra)
    schema["logic"] = rules
    issues = collect_schema_issues(schema)
    return [i for i in issues if i["code"] == "logic_cycle"]


def _validate_logic_rule(form, action, target, condition, exclude_id=None, name=""):
    """逻辑规则单条校验：动作/目标/条件引用/循环依赖。"""
    action = str(action or "show")
    if action not in dict(LOGIC_ACTION_CHOICES):
        raise ValueError(f"逻辑动作不合法: {action}")
    keys = set(form.fields.values_list("key", flat=True))
    if target not in keys:
        raise ValueError(f"目标字段不存在: {target}")
    for ref in services.collect_condition_fields(condition):
        if ref not in keys:
            raise ValueError(f"条件引用了不存在的字段: {ref}")
    cycle = _logic_cycle(
        form,
        exclude_id=exclude_id,
        extra={
            "name": name,
            "action": action,
            "target_key": target,
            "condition": condition,
            "enabled": True,
        },
    )
    if cycle:
        raise ValueError(cycle[0]["message"])
    return action


@endpoint(("GET",))
def form_logic_list(request, pk):
    """表单逻辑规则列表（按优先级排序）。"""
    form = get_form(request.user, pk)
    qs = form.logic_rules.all().order_by("priority", "id")
    if opt_str(request, "action", ""):
        qs = qs.filter(action=opt_str(request, "action"))
    return ok(paginate(qs, request, logic_dict))


@endpoint(("POST",))
def logic_create(request):
    """新增逻辑规则（show/hide/require/skip/set_value）。"""
    form = get_form(request.user, int_param(request, "form_id"), write=True)
    target = req_str(request, "target_key", max_len=64)
    condition = json_obj(request, "condition")
    action = _validate_logic_rule(
        form,
        opt_str(request, "action", "show"),
        target,
        condition,
        name=opt_str(request, "name", "", max_len=200),
    )
    rule = FormLogicRule.objects.create(
        owner=form.owner,
        form=form,
        name=opt_str(request, "name", "", max_len=200),
        condition=condition,
        action=action,
        target_key=target,
        value=p(request, "value"),
        priority=opt_int(request, "priority", default=100),
        enabled=opt_bool(request, "enabled", True),
    )
    return ok(logic_dict(rule))


@endpoint(("PATCH", "DELETE"))
def logic_item(request, pk):
    """更新（PATCH）/ 删除（DELETE）逻辑规则。"""
    rule = get_logic(request.user, pk, write=True)
    if request.method == "DELETE":
        rule.delete()
        return ok({"id": pk, "deleted": True})
    target = (
        req_str(request, "target_key", max_len=64)
        if _has(request, "target_key")
        else rule.target_key
    )
    condition = json_obj(request, "condition") if _has(request, "condition") else rule.condition
    action = _validate_logic_rule(
        rule.form,
        opt_str(request, "action", rule.action),
        target,
        condition,
        exclude_id=rule.pk,
        name=opt_str(request, "name", rule.name, max_len=200),
    )
    if _has(request, "name"):
        rule.name = opt_str(request, "name", "", max_len=200)
    rule.target_key = target
    rule.condition = condition
    rule.action = action
    if _has(request, "value"):
        rule.value = p(request, "value")
    if _has(request, "priority"):
        rule.priority = int_param(request, "priority")
    if _has(request, "enabled"):
        rule.enabled = opt_bool(request, "enabled")
    rule.save()
    return ok(logic_dict(rule))


@endpoint(("POST",))
def logic_test(request, pk):
    """按给定答案试跑逻辑规则，预览显隐/必填/赋值与校验结果。"""
    form = get_form(request.user, pk)
    schema = schema_from_form(form)
    answers = json_obj(request, "answers")
    states = services.apply_logic(
        schema.get("fields") or [],
        schema.get("logic") or [],
        answers,
        schema.get("sections") or [],
    )
    result = services.validate_answers(
        form, schema, answers, check_unique=False, collect_all=True
    )
    score = services.compute_score(form, schema, answers)
    return ok(
        {
            "states": states,
            "errors": result["errors"],
            "cleaned": result["cleaned"],
            "score": score,
            "visible_count": len(states["visible"]),
            "hidden_count": len(states["hidden"]),
        }
    )
