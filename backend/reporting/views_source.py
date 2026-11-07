# -*- coding: utf-8 -*-
"""数据源与数据集接口：CRUD、字段/关联/参数维护、预览与取值枚举。

写操作全部走 ``transaction.atomic()``（批量保存字段时先删后建，必须原子），
配置校验一律调用编译器/白名单，配置写错在保存时就报 400，而不是执行期才炸。
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_str, p, req_str

from reporting import probe as probe_mod
from reporting import services as svc
from reporting.models import (
    AGGREGATES, BUCKETS, FIELD_TYPES, JOIN_TYPES, PARAM_TYPES, SOURCE_KINDS,
    DataSource, Dataset, DatasetField,
)
from reporting.payloads import (
    apply_q, apply_status, dataset_dict, field_dict, join_dict, paginate,
    param_dict, source_dict,
)
from reporting.views_common import (
    get_dataset, get_source, read_bool, read_choice, read_int_list, read_json,
    read_json_obj, read_limit, read_str_list, require_model, require_model_fields,
)

FIELD_FORMATS = {"", "number", "percent", "currency", "date", "datetime", "compact"}
PARAM_NAME_MAX = 60


# =====================================================================
# 数据源（7）
# =====================================================================


@endpoint(("GET",))
def sources_list(request):
    """数据源列表（q/kind/status 过滤 + 分页）。"""
    qs = scope_queryset(DataSource.objects.all(), request.user, "owner")
    qs = apply_q(qs, request, ["name", "description", "last_message"])
    kind = read_choice(request, "kind", SOURCE_KINDS)
    if kind:
        qs = qs.filter(kind=kind)
    qs = apply_status(qs, request)
    qs = qs.order_by("-updated_at", "-id")
    return ok(paginate(qs, request, source_dict))


@endpoint()
def source_create(request):
    """新建数据源（保存前先做一次配置校验，坏配置进不了库）。"""
    name = req_str(request, "name")[:120]
    kind = read_choice(request, "kind", SOURCE_KINDS, required=True)
    config = read_json_obj(request, "config", {})
    description = opt_str(request, "description")[:255]
    probe = probe_mod.probe_source(kind, config)
    if not probe["ok"]:
        raise ValueError(f"数据源配置校验失败：{probe['message']}")
    now = timezone.now()
    obj = DataSource.objects.create(
        name=name, kind=kind, description=description, config=config,
        status="active", owner=request.user,
        last_checked_at=now, last_message=probe_mod.probe_message_success(probe),
        check_count=1, ok_count=1, last_ok_at=now,
    )
    return ok({"source": source_dict(obj, detail=True), "probe": probe})


@endpoint(("GET",))
def source_detail(request, pk):
    """数据源详情（含配置与关联数据集数量）。"""
    obj = get_source(pk, request.user)
    data = source_dict(obj, detail=True)
    data["datasets"] = [
        {"id": d.pk, "name": d.name, "primary_model": d.primary_model, "status": d.status}
        for d in obj.rep_datasets.all().order_by("-updated_at")[:50]
    ]
    return ok(data)


@endpoint()
def source_update(request, pk):
    """更新数据源（改名/改配置/改描述；配置变更会立即重新校验）。"""
    obj = get_source(pk, request.user, write=True)
    name = opt_str(request, "name").strip()
    config = None
    if p(request, "config") is not None:
        config = read_json_obj(request, "config", {})
        probe = probe_mod.probe_source(obj.kind, config)
        if not probe["ok"]:
            raise ValueError(f"数据源配置校验失败：{probe['message']}")
    with transaction.atomic():
        if name:
            obj.name = name[:120]
        if p(request, "description") is not None:
            obj.description = opt_str(request, "description")[:255]
        if config is not None:
            obj.config = config
            obj.last_checked_at = timezone.now()
            obj.last_message = probe_mod.probe_message_success(probe)
        obj.save()
    return ok(source_dict(obj, detail=True))


@endpoint()
def source_delete(request, pk):
    """删除数据源（关联数据集自动解除引用，不级联删数据）。"""
    obj = get_source(pk, request.user, write=True)
    detached = list(obj.rep_datasets.values_list("id", flat=True))
    sid, name = obj.pk, obj.name
    obj.delete()
    return ok({"deleted": True, "id": sid, "name": name,
               "detached_datasets": len(detached), "dataset_ids": detached[:50]})


@endpoint()
def source_test(request, pk):
    """测试数据源连通性（orm 真计数；http/file 为配置校验 + 模拟探测）。"""
    obj = get_source(pk, request.user, write=True)
    result = probe_mod.probe_source(obj.kind, obj.config or {})
    now = timezone.now()
    with transaction.atomic():
        obj.check_count = (obj.check_count or 0) + 1
        obj.last_checked_at = now
        if result["ok"]:
            obj.ok_count = (obj.ok_count or 0) + 1
            obj.last_ok_at = now
            obj.status = "active"
        else:
            obj.status = "error"
        obj.last_message = probe_mod.probe_message_success(result)
        obj.save(update_fields=["check_count", "ok_count", "last_checked_at",
                                "last_ok_at", "status", "last_message", "updated_at"])
    return ok({**result, "source_id": obj.pk, "status": obj.status,
               "checked_at": now.isoformat(), "summary": obj.summarize()})


@endpoint()
def source_toggle(request, pk):
    """启用/停用数据源（停用后其数据集执行前置校验会提示）。"""
    obj = get_source(pk, request.user, write=True)
    enabled = read_bool(request, "enabled", default=obj.status != "active")
    with transaction.atomic():
        obj.status = "active" if enabled else "inactive"
        obj.last_message = "手动启停"[:255]
        obj.save(update_fields=["status", "last_message", "updated_at"])
    return ok({"id": obj.pk, "status": obj.status, "enabled": obj.status == "active"})


# =====================================================================
# 数据集（5）
# =====================================================================


@endpoint(("GET",))
def datasets_list(request):
    """数据集列表（q/status/model 过滤 + 分页）。"""
    qs = scope_queryset(Dataset.objects.all(), request.user, "owner")
    qs = apply_q(qs, request, ["name", "description", "primary_model"])
    model = opt_str(request, "primary_model").strip()
    if model:
        qs = qs.filter(primary_model=model)
    qs = apply_status(qs, request)
    qs = qs.select_related("source").order_by("-updated_at", "-id")
    return ok(paginate(qs, request, lambda o: dataset_dict(o)))


@endpoint()
def dataset_create(request):
    """新建数据集（模型白名单 + 过滤条件即刻校验，可顺带创建字段）。"""
    name = req_str(request, "name")[:120]
    primary_model = req_str(request, "primary_model")[:120]
    model = require_model(primary_model)
    primary_model = f"{model._meta.app_label}.{model._meta.object_name}"
    filter_spec = read_json_obj(request, "filter", {})
    svc.validate_filter(model, filter_spec)
    distinct_fields = read_str_list(request, "distinct_fields", max_items=10, max_len=160)
    require_model_fields(primary_model, distinct_fields, "去重字段")
    source_id = p(request, "source_id")
    source = None
    if source_id:
        source = get_source(source_id, request.user, write=True)
    default_limit = int(p(request, "default_limit") or 200)
    if default_limit < 1 or default_limit > 2000:
        raise ValueError("default_limit 需在 1~2000 之间")
    cache_ttl = int(p(request, "cache_ttl") or 300)
    if cache_ttl < 0 or cache_ttl > 86400:
        raise ValueError("cache_ttl 需在 0~86400 秒之间")
    with transaction.atomic():
        dataset = Dataset.objects.create(
            name=name, description=opt_str(request, "description"),
            primary_model=primary_model, source=source, filter=filter_spec,
            distinct_fields=distinct_fields, default_limit=default_limit,
            cache_ttl=cache_ttl, owner=request.user,
        )
        raw_fields = p(request, "fields")
        if raw_fields:
            if not isinstance(raw_fields, list):
                raise ValueError("fields 必须是数组")
            _save_fields(dataset, raw_fields)
    return ok({"dataset": dataset_dict(dataset, detail=True)})


@endpoint(("GET",))
def dataset_detail(request, pk):
    """数据集详情（字段 + 关联 + 参数 + 引用它的组件）。"""
    dataset = get_dataset(pk, request.user)
    data = dataset_dict(dataset, detail=True)
    data["widgets"] = [
        {"id": w.pk, "title": w.title, "type": w.rtype,
         "report_id": w.page.report_id if w.page_id else None}
        for w in dataset.rep_widgets.select_related("page").all()[:50]
    ]
    return ok(data)


@endpoint()
def dataset_update(request, pk):
    """更新数据集（改模型时旧字段会失效，因此要求显式传 reset_fields）。"""
    dataset = get_dataset(pk, request.user, write=True)
    new_model = opt_str(request, "primary_model").strip()
    reset_fields = read_bool(request, "reset_fields", False)
    with transaction.atomic():
        if new_model and new_model != dataset.primary_model:
            model = require_model(new_model)
            dataset.primary_model = f"{model._meta.app_label}.{model._meta.object_name}"
            # 换模型后旧字段路径基本都不成立：没有 reset_fields 就不许换
            if dataset.rep_dataset_fields.exists() and not reset_fields:
                raise ValueError("更换主模型会失效现有字段，请传 reset_fields=true 确认")
            dataset.rep_dataset_fields.all().delete()
            dataset.rep_dataset_joins.all().delete()
        model = svc.get_whitelisted_model(dataset.primary_model)
        if p(request, "filter") is not None:
            filter_spec = read_json_obj(request, "filter", {})
            svc.validate_filter(model, filter_spec)
            dataset.filter = filter_spec
        if p(request, "distinct_fields") is not None:
            distinct_fields = read_str_list(request, "distinct_fields", max_items=10, max_len=160)
            require_model_fields(dataset.primary_model, distinct_fields, "去重字段")
            dataset.distinct_fields = distinct_fields
        name = opt_str(request, "name").strip()
        if name:
            dataset.name = name[:120]
        if p(request, "description") is not None:
            dataset.description = opt_str(request, "description")
        if p(request, "default_limit") is not None:
            limit = int(p(request, "default_limit") or 200)
            if limit < 1 or limit > 2000:
                raise ValueError("default_limit 需在 1~2000 之间")
            dataset.default_limit = limit
        if p(request, "cache_ttl") is not None:
            ttl = int(p(request, "cache_ttl") or 0)
            if ttl < 0 or ttl > 86400:
                raise ValueError("cache_ttl 需在 0~86400 秒之间")
            dataset.cache_ttl = ttl
        if p(request, "source_id") is not None:
            source_id = p(request, "source_id")
            dataset.source = get_source(source_id, request.user, write=True) if source_id else None
        status = read_choice(request, "status", [("active", "启用"), ("inactive", "停用")])
        if status:
            dataset.status = status
        dataset.save()
    return ok({"dataset": dataset_dict(dataset, detail=True)})


@endpoint()
def dataset_delete(request, pk):
    """删除数据集（被组件引用时需 force=true，避免报表静默变空）。"""
    dataset = get_dataset(pk, request.user, write=True)
    force = read_bool(request, "force", False)
    widget_count = dataset.rep_widgets.count()
    if widget_count and not force:
        raise ValueError(f"该数据集被 {widget_count} 个组件引用，请先解绑或传 force=true")
    did, name = dataset.pk, dataset.name
    dataset.delete()
    return ok({"deleted": True, "id": did, "name": name, "detached_widgets": widget_count})


# =====================================================================
# 数据集字段（6）
# =====================================================================


def _field_payload(primary_model, row, dataset, order_default=0):
    """字段入参校验：路径真实存在 + 聚合与类型匹配。"""
    if not isinstance(row, dict):
        raise ValueError("字段配置必须是对象")
    path = str(row.get("path") or "").strip()
    if not path:
        raise ValueError("字段缺少 path")
    model = svc.get_whitelisted_model(primary_model)
    resolved = svc.resolve_path(model, path)
    agg = str(row.get("aggregate") or "none")
    if agg not in dict(AGGREGATES):
        raise ValueError(f"不支持的聚合函数：{agg}")
    ftype = str(row.get("ftype") or resolved["type"] or "string")
    if ftype not in dict(FIELD_TYPES):
        raise ValueError(f"不支持的字段类型：{ftype}")
    bucket = str(row.get("bucket") or "")
    if bucket and bucket not in dict(BUCKETS):
        raise ValueError(f"不支持的时间分桶：{bucket}")
    if bucket and resolved["type"] not in ("date", "datetime"):
        raise ValueError(f"字段 {path} 不是日期类型，不能设置时间分桶")
    if agg in ("sum", "avg", "median") and not (
        resolved["type"] in ("integer", "number", "decimal") or resolved.get("is_json")
    ):
        raise ValueError(f"字段 {path} 不是数值类型，不能做 {agg} 聚合")
    fmt = str(row.get("fmt") or "")
    if fmt not in FIELD_FORMATS:
        raise ValueError(f"不支持的格式化：{fmt}（可选 {'/'.join(sorted(FIELD_FORMATS - {''}))}）")
    alias = str(row.get("alias") or "").strip()
    if len(alias) > 60:
        raise ValueError("字段别名不能超过 60 字符")
    order = row.get("order", order_default)
    try:
        order = int(order)
    except (TypeError, ValueError):
        raise ValueError("字段排序必须是整数")
    return {
        "dataset": dataset,
        "path": path,
        "alias": alias,
        "ftype": ftype,
        "aggregate": agg,
        "is_group": bool(row.get("is_group", agg == "none")),
        "bucket": bucket,
        "order": order,
        "fmt": fmt,
        "visible": bool(row.get("visible", True)),
    }


def _save_fields(dataset, rows):
    """批量保存字段（调用方保证在事务内）：先清空再重建，别名重复提前报错。"""
    if len(rows) > 80:
        raise ValueError("字段数量不能超过 80")
    prepared = []
    seen = set()
    for idx, row in enumerate(rows):
        payload = _field_payload(dataset.primary_model, row, dataset, idx)
        if payload["alias"]:
            if payload["alias"] in seen:
                raise ValueError(f"字段别名重复：{payload['alias']}")
            seen.add(payload["alias"])
        prepared.append(payload)
    dataset.rep_dataset_fields.all().delete()
    created = [DatasetField.objects.create(**item) for item in prepared]
    return created


@endpoint(("GET",))
def dataset_fields(request, pk):
    """字段列表（含推导出的输出列名 key）。"""
    dataset = get_dataset(pk, request.user)
    fields = [field_dict(f) for f in dataset.rep_dataset_fields.all().order_by("order", "id")]
    return ok({"items": fields, "count": len(fields)})


@endpoint()
def dataset_fields_save(request, pk):
    """批量保存字段（整体替换；一次事务，失败全回滚）。"""
    dataset = get_dataset(pk, request.user, write=True)
    rows = p(request, "fields")
    if not isinstance(rows, list):
        raise ValueError("fields 必须是数组")
    with transaction.atomic():
        created = _save_fields(dataset, rows)
    return ok({"dataset_id": dataset.pk, "items": [field_dict(f) for f in created],
               "count": len(created)})


@endpoint()
def dataset_field_create(request, pk):
    """新增单个字段（追加到末尾）。"""
    dataset = get_dataset(pk, request.user, write=True)
    payload = _field_payload(dataset.primary_model, request.data if isinstance(request.data, dict) else {},
                             dataset, dataset.rep_dataset_fields.count())
    if payload["alias"] and dataset.rep_dataset_fields.filter(alias=payload["alias"]).exists():
        raise ValueError(f"字段别名重复：{payload['alias']}")
    field = DatasetField.objects.create(**payload)
    return ok(field_dict(field))


@endpoint()
def dataset_field_update(request, pk):
    """更新字段（字段归属的 dataset 通过 field_id 反查，避免路径冲突）。"""
    field = _get_field(pk, request.user, write=True)
    dataset = field.dataset
    merged = {
        "path": p(request, "path") or field.path,
        "alias": p(request, "alias") if p(request, "alias") is not None else field.alias,
        "ftype": p(request, "ftype") or field.ftype,
        "aggregate": p(request, "aggregate") or field.aggregate,
        "is_group": p(request, "is_group") if p(request, "is_group") is not None else field.is_group,
        "bucket": p(request, "bucket") if p(request, "bucket") is not None else field.bucket,
        "order": p(request, "order") if p(request, "order") is not None else field.order,
        "fmt": p(request, "fmt") if p(request, "fmt") is not None else field.fmt,
        "visible": p(request, "visible") if p(request, "visible") is not None else field.visible,
    }
    payload = _field_payload(dataset.primary_model, merged, dataset, field.order)
    if payload["alias"] and dataset.rep_dataset_fields.exclude(pk=field.pk).filter(
            alias=payload["alias"]).exists():
        raise ValueError(f"字段别名重复：{payload['alias']}")
    with transaction.atomic():
        for key, value in payload.items():
            if key != "dataset":
                setattr(field, key, value)
        field.save()
    return ok(field_dict(field))


@endpoint()
def dataset_field_delete(request, pk):
    """删除字段。"""
    field = _get_field(pk, request.user, write=True)
    fid, dataset_id = field.pk, field.dataset_id
    field.delete()
    return ok({"deleted": True, "id": fid, "dataset_id": dataset_id})


@endpoint()
def dataset_fields_reorder(request, pk):
    """字段排序：按传入的 id 顺序重排（缺省的排在后面）。"""
    dataset = get_dataset(pk, request.user, write=True)
    ids = read_int_list(request, "ids", max_items=80)
    if not ids:
        raise ValueError("缺少必填参数: ids")
    existing = {f.pk: f for f in dataset.rep_dataset_fields.all()}
    with transaction.atomic():
        for idx, fid in enumerate(ids):
            field = existing.get(fid)
            if field is None:
                raise ValueError(f"字段 {fid} 不属于该数据集")
            if field.order != idx:
                field.order = idx
                field.save(update_fields=["order"])
        tail = idx + 1 if ids else 0
        for field in existing.values():
            if field.pk in ids:
                continue
            if field.order != tail:
                field.order = tail
                field.save(update_fields=["order"])
            tail += 1
    return ok({"dataset_id": dataset.pk, "count": len(ids)})


def _get_field(pk, user, write=False):
    """字段是数据集的子对象：先取数据集权限，再定位字段。"""
    from reporting.models import DatasetField as _Model

    field = _Model.objects.select_related("dataset").filter(pk=pk).first()
    if field is None:
        raise ValueError("字段不存在")
    dataset = field.dataset
    from core.scoping import can_write, is_visible

    if write and not can_write(user, dataset):
        raise ValueError("无权修改该字段")
    if not write and not is_visible(dataset, user):
        raise ValueError("字段不存在或无权访问")
    return field


# =====================================================================
# 数据集关联 / 参数（4）
# =====================================================================


@endpoint()
def dataset_join_create(request, pk):
    """新增关联（校验 via 真实指向 target_model，防止“声东击西”）。"""
    dataset = get_dataset(pk, request.user, write=True)
    target_model = req_str(request, "target_model")[:120]
    svc.model_info(target_model)
    via = req_str(request, "via")[:80]
    model = svc.get_whitelisted_model(dataset.primary_model)
    from reporting.whitelist import same_relation_target

    same_relation_target(model, via, target_model)
    if dataset.rep_dataset_joins.filter(via=via).exists():
        raise ValueError(f"关联路径 {via} 已存在")
    join_type = read_choice(request, "join_type", JOIN_TYPES, default="left")
    left_field = opt_str(request, "left_field")[:80]
    right_field = opt_str(request, "right_field")[:80]
    target = svc.get_whitelisted_model(target_model)
    if left_field:
        svc.resolve_path(model, left_field)
    if right_field:
        svc.resolve_path(target, right_field)
    try:
        with transaction.atomic():
            join = dataset.rep_dataset_joins.create(
                target_model=target_model, via=via, left_field=left_field,
                right_field=right_field, join_type=join_type,
                order=dataset.rep_dataset_joins.count(),
            )
    except IntegrityError:
        raise ValueError("该关联路径已存在")
    return ok(join_dict(join))


@endpoint()
def dataset_join_delete(request, pk):
    """删除关联。"""
    from reporting.models import DatasetJoin

    join = DatasetJoin.objects.select_related("dataset").filter(pk=pk).first()
    if join is None:
        raise ValueError("关联不存在")
    dataset = join.dataset
    from core.scoping import can_write

    if not can_write(request.user, dataset):
        raise ValueError("无权修改该关联")
    jid = join.pk
    join.delete()
    return ok({"deleted": True, "id": jid, "dataset_id": dataset.pk})


@endpoint()
def dataset_param_create(request, pk):
    """新增数据集参数（报表执行时按名绑定，供过滤条件 $占位）。"""
    dataset = get_dataset(pk, request.user, write=True)
    name = req_str(request, "name")[:PARAM_NAME_MAX].strip()
    if not name.replace("_", "").isalnum() or name[0].isdigit():
        raise ValueError("参数名只能含字母数字下划线，且不能以数字开头")
    if dataset.rep_dataset_params.filter(name=name).exists():
        raise ValueError(f"参数 {name} 已存在")
    ptype = read_choice(request, "ptype", PARAM_TYPES, default="string")
    try:
        default = read_json(request, "default")
    except ValueError:
        # 文本/日期参数允许直接传纯字符串（前端表单最常见），不必先包成 JSON
        raw = p(request, "default")
        if ptype in ("string", "date") and isinstance(raw, (str, int, float)):
            default = str(raw) if raw != "" else None
        else:
            raise
    required = read_bool(request, "required", False)
    if required and default not in (None, ""):
        raise ValueError("必填参数的默认值会掩盖缺参，请留空默认值")
    param = dataset.rep_dataset_params.create(
        name=name, ptype=ptype, default=default, required=required,
        description=opt_str(request, "description")[:200],
    )
    return ok(param_dict(param))


@endpoint()
def dataset_param_delete(request, pk):
    """删除数据集参数。"""
    from reporting.models import DatasetParam

    param = DatasetParam.objects.select_related("dataset").filter(pk=pk).first()
    if param is None:
        raise ValueError("参数不存在")
    from core.scoping import can_write

    if not can_write(request.user, param.dataset):
        raise ValueError("无权修改该参数")
    pid, dataset_id = param.pk, param.dataset_id
    param.delete()
    return ok({"deleted": True, "id": pid, "dataset_id": dataset_id})


# =====================================================================
# 预览 / 取值 / 结构（4）
# =====================================================================


@endpoint()
def dataset_preview(request, pk):
    """预览数据集：支持临时覆盖 filter/fields/order/limit（不落库）。"""
    dataset = get_dataset(pk, request.user)
    overrides = svc.overrides_from_request(request)
    if not overrides.get("limit"):
        overrides["limit"] = read_limit(request, "limit", dataset.default_limit, maximum=500)
    params = read_json_obj(request, "params", {})
    result = svc.run_dataset(dataset, params, overrides)
    dataset.touch_preview()
    return ok({**result, "params": params, "dataset": {
        "id": dataset.pk, "name": dataset.name, "model": dataset.primary_model,
    }})


@endpoint()
def dataset_quick_preview(request):
    """不建数据集的即时预览：选模型 → 试过滤 → 看结果（给「试一试」用）。"""
    primary_model = req_str(request, "primary_model")[:120]
    require_model(primary_model)
    filter_spec = read_json_obj(request, "filter", {})
    params = read_json_obj(request, "params", {})
    limit = read_limit(request, "limit", 20, maximum=500)
    fields = p(request, "fields")
    if fields is not None and not isinstance(fields, list):
        raise ValueError("fields 必须是数组")
    result = svc.quick_preview(
        primary_model, filter_spec=filter_spec, fields=fields, limit=limit,
        params=params, order=p(request, "order"),
    )
    return ok(result)


@endpoint(("GET",))
def dataset_values(request, pk):
    """字段取值枚举（筛选器下拉）：带命中次数，按次数倒序。"""
    dataset = get_dataset(pk, request.user)
    field = opt_str(request, "field").strip()
    if not field:
        raise ValueError("缺少必填参数: field")
    svc.resolve_path(svc.get_whitelisted_model(dataset.primary_model), field)
    limit = read_limit(request, "limit", 100, maximum=500)
    filter_spec = svc.combine_filters(dataset.filter or {}, read_json(request, "filter", {}))
    result = svc.distinct_values(dataset.primary_model, field, filter_spec, limit)
    return ok({**result, "dataset_id": dataset.pk})


@endpoint(("GET",))
def dataset_schema(request, pk):
    """数据集结构：可用字段 + 关系 + 已选字段 + 聚合建议。"""
    dataset = get_dataset(pk, request.user)
    info = svc.model_detail(dataset.primary_model)
    suggestions = []
    for field in info["fields"][:12]:
        if field["name"] == "id":
            continue
        suggestion = {"path": field["name"], "type": field["type"]}
        if field["type"] in ("integer", "number", "decimal"):
            suggestion["aggregate"] = "sum"
        elif field["type"] in ("date", "datetime"):
            suggestion["bucket"] = "month"
            suggestion["aggregate"] = "none"
        else:
            suggestion["is_group"] = True
            suggestion["aggregate"] = "count"
        suggestions.append(suggestion)
    return ok({
        "dataset": {"id": dataset.pk, "name": dataset.name, "model": dataset.primary_model},
        "model": info,
        "fields": [field_dict(f) for f in dataset.rep_dataset_fields.all().order_by("order", "id")],
        "joins": [join_dict(j) for j in dataset.rep_dataset_joins.all().order_by("order", "id")],
        "params": [param_dict(x) for x in dataset.rep_dataset_params.all()],
        "suggestions": suggestions,
    })
