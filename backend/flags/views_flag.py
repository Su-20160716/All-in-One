# -*- coding: utf-8 -*-
"""功能开关 · 开关与评估接口（17 个）。

开关生命周期：创建 → 配置变体/定向/灰度 → 发布版本 → 评估 → 归档/回滚。
评估接口是本应用的高频路径，所有写日志、缓存、截断逻辑都在 services 里，
视图只负责定位开关与整理上下文。
"""
from django.db import IntegrityError, transaction
from django.db.models import Q

from devtools.common import endpoint, ok, opt_str, p, req_str

from flags import services
from flags.models import (
    FLAG_STATUS,
    FLAG_TYPES,
    LOGIC_OPS,
    ROLLOUT_STATUS,
    Environment,
    Flag,
    FlagVersion,
    Project,
    Rollout,
    TargetingRule,
    Variant,
)
from flags.views_common import (
    after_write,
    bool_param,
    context_param,
    get_environment,
    get_flag,
    int_param,
    json_param,
    list_param,
    paginate,
    percent_param,
    resolve_flag,
    visible_flags,
)


def _user_key(request):
    """评估用户键：user_key 为主，兼容 user/user_id 别名。"""
    value = p(request, "user_key")
    if value in (None, ""):
        value = p(request, "user") or p(request, "user_id")
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少必填参数: user_key")
    if len(text) > 200:
        raise ValueError("user_key 最长为 200 字符")
    return text


def _apply_flag_filters(qs, request):
    """开关列表过滤：项目/环境/负责人/标签/类型。"""
    project_id = p(request, "project_id")
    if project_id not in (None, ""):
        qs = qs.filter(project_id=services.parse_int(project_id, "project_id", minimum=1))
    env_id = p(request, "environment_id")
    if env_id not in (None, ""):
        qs = qs.filter(environment_id=services.parse_int(env_id, "environment_id", minimum=1))
    flag_type = opt_str(request, "flag_type").strip()
    if flag_type:
        if flag_type not in FLAG_TYPES:
            raise ValueError(f"开关类型必须是 {'/'.join(FLAG_TYPES)} 之一")
        qs = qs.filter(flag_type=flag_type)
    assignee = opt_str(request, "assignee").strip()
    if assignee:
        qs = qs.filter(assignee__icontains=assignee)
    return qs


def _validate_lifecycle(temporary, permanent):
    if temporary and permanent:
        raise ValueError("临时开关与永久开关不能同时选中")


def _create_variant(flag, row, order=0):
    """按行创建变体；供创建/克隆复用。"""
    if not isinstance(row, dict):
        raise ValueError("变体必须是对象")
    key = services.parse_key(row.get("key"), "变体键")
    name = str(row.get("name") or key)[:120]
    weight = services.parse_int(row.get("weight"), "权重", 0, minimum=0, maximum=100)
    payload = services.parse_json(row.get("payload"), "负载", {}) or {}
    if not isinstance(payload, dict):
        raise ValueError("变体负载必须是对象")
    return Variant.objects.create(
        owner=flag.owner,
        flag=flag,
        key=key,
        name=name,
        weight=weight,
        payload=payload,
    )


def _create_targeting(flag, row):
    """按行创建定向规则；条件在入库前校验，避免脏正则进入评估。"""
    if not isinstance(row, dict):
        raise ValueError("定向规则必须是对象")
    conditions = row.get("conditions") or []
    logic, normalized = services.normalize_conditions(
        conditions, row.get("condition_logic") or "and"
    )
    for condition in normalized:
        services.validate_condition(condition)
    priority = services.parse_int(row.get("priority"), "优先级", 100)
    if flag.targeting_rules.filter(priority=priority).exists():
        # 唯一约束会报 IntegrityError，这里提前给出可读错误
        max_priority = flag.targeting_rules.order_by("-priority").values_list(
            "priority", flat=True).first() or 0
        priority = max_priority + 10
    return TargetingRule.objects.create(
        owner=flag.owner,
        flag=flag,
        priority=priority,
        conditions=normalized,
        condition_logic=logic,
        variant_key=str(row.get("variant_key") or "")[:80],
        percentage=services.parse_percent(row.get("percentage"), "百分比", 100),
        enabled=bool(row.get("enabled", True)),
        note=str(row.get("note") or "")[:200],
    )


# =====================================================================
# 开关 CRUD
# =====================================================================


@endpoint(("GET", "POST"))
def flags(request):
    """开关列表（GET）或创建开关（POST）。"""
    if request.method == "POST":
        project_id = int_param(request, "project_id", None, minimum=1)
        env_id = int_param(request, "environment_id", None, minimum=1)
        if not project_id:
            raise ValueError("缺少必填参数: project_id")
        if not env_id:
            raise ValueError("缺少必填参数: environment_id")
        from flags.views_common import get_project

        project = get_project(project_id, request.user, write=True)
        environment = get_environment(env_id, request.user, write=True)
        if environment.project_id != project.id:
            raise ValueError("环境不属于该项目")
        key = services.parse_key(req_str(request, "key"), "开关键名")
        name = req_str(request, "name")[:200]
        flag_type = services.parse_choice(p(request, "flag_type"), FLAG_TYPES, "开关类型", "boolean")
        status = services.parse_choice(p(request, "status"), FLAG_STATUS, "开关状态", "active")
        temporary = bool_param(request, "temporary", False)
        permanent = bool_param(request, "permanent", False)
        _validate_lifecycle(temporary, permanent)
        labels = services.normalize_labels(p(request, "labels") or [])
        default_variant = opt_str(request, "default_variant").strip()[:80]
        if default_variant:
            services.parse_key(default_variant, "默认变体键")
        try:
            with transaction.atomic():
                flag = Flag.objects.create(
                    owner=request.user,
                    project=project,
                    environment=environment,
                    key=key,
                    name=name,
                    description=opt_str(request, "description"),
                    flag_type=flag_type,
                    status=status,
                    temporary=temporary,
                    permanent=permanent,
                    labels=labels,
                    assignee=opt_str(request, "assignee")[:120],
                    default_variant=default_variant,
                )
                for row in list_param(request, "variants", [], max_len=20):
                    _create_variant(flag, row)
                for row in list_param(request, "targeting_rules", [], max_len=50):
                    _create_targeting(flag, row)
                if p(request, "rollout_percentage") not in (None, ""):
                    Rollout.objects.create(
                        owner=request.user,
                        flag=flag,
                        percentage=percent_param(request, "rollout_percentage", 0),
                        salt=opt_str(request, "salt")[:120],
                        status="running",
                        start_at=services.now(),
                    )
        except IntegrityError:
            raise ValueError("同一环境下开关键名已存在")
        after_write(
            request.user,
            flag,
            "flag.create",
            after={"key": key, "environment_id": env_id, "flag_type": flag_type},
            project=project,
        )
        return ok(flag.as_dict())

    qs = _apply_flag_filters(visible_flags(request.user), request)
    from flags.views_common import apply_search

    qs = apply_search(qs, request, ["key", "name", "description", "assignee"])
    return paginate(qs.order_by("-created_at", "-id"), request, lambda obj: obj.as_dict())


@endpoint(("GET",))
def flag_detail(request, pk):
    """开关详情（含变体、定向、灰度、依赖与实验数量）。"""
    flag = get_flag(pk, request.user)
    data = flag.as_dict()
    data["variants"] = [item.as_dict() for item in flag.variants.all().order_by("id")]
    data["targeting_rules"] = [
        item.as_dict() for item in flag.targeting_rules.all().order_by("priority", "id")
    ]
    data["rollouts"] = [item.as_dict() for item in flag.rollouts.all().order_by("id")]
    data["dependencies"] = [
        item.as_dict() for item in flag.dependencies.select_related("depends_on").order_by("id")
    ]
    data["dependents"] = [
        item.as_dict() for item in flag.dependents.select_related("flag").order_by("id")
    ]
    data["experiments"] = [
        item.as_dict() for item in flag.experiments.all().order_by("-id")[:20]
    ]
    data["version_count"] = flag.versions.count()
    data["stats"] = services.flag_stats(flag)
    return ok(data)


@endpoint()
def flag_update(request):
    """更新开关基础属性（键名/环境变更会校验唯一性与归属）。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        flag_id = int_param(request, "id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    before = flag.as_dict()
    if p(request, "name") not in (None, ""):
        flag.name = req_str(request, "name")[:200]
    if p(request, "description") not in (None, ""):
        flag.description = opt_str(request, "description")
    if p(request, "flag_type") not in (None, ""):
        flag.flag_type = services.parse_choice(
            p(request, "flag_type"), FLAG_TYPES, "开关类型", flag.flag_type
        )
    if p(request, "status") not in (None, ""):
        flag.status = services.parse_choice(
            p(request, "status"), FLAG_STATUS, "开关状态", flag.status
        )
    if p(request, "temporary") not in (None, ""):
        flag.temporary = bool_param(request, "temporary", flag.temporary)
    if p(request, "permanent") not in (None, ""):
        flag.permanent = bool_param(request, "permanent", flag.permanent)
    _validate_lifecycle(flag.temporary, flag.permanent)
    if p(request, "labels") not in (None, ""):
        flag.labels = services.normalize_labels(p(request, "labels"))
    if p(request, "assignee") not in (None, ""):
        flag.assignee = opt_str(request, "assignee")[:120]
    if p(request, "default_variant") not in (None, ""):
        value = opt_str(request, "default_variant").strip()[:80]
        if value:
            services.parse_key(value, "默认变体键")
        flag.default_variant = value
    if p(request, "key") not in (None, ""):
        flag.key = services.parse_key(p(request, "key"), "开关键名")
    if p(request, "environment_id") not in (None, ""):
        environment = get_environment(
            services.parse_int(p(request, "environment_id"), "environment_id", minimum=1),
            request.user,
            write=True,
        )
        if environment.project_id != flag.project_id:
            raise ValueError("环境不属于该开关所在项目")
        flag.environment = environment
    try:
        # 唯一约束冲突会污染外层事务（ATOMIC_REQUESTS / TestCase），
        # 用内层原子块做保存点回滚，后续查询才能继续。
        with transaction.atomic():
            flag.save()
    except IntegrityError:
        raise ValueError("同一环境下开关键名已存在")
    after_write(
        request.user,
        flag,
        "flag.update",
        before=before,
        after=flag.as_dict(),
        project=flag.project,
        note="生产环境修改" if flag.environment.is_production else "",
    )
    return ok(flag.as_dict())


@endpoint()
def flag_toggle(request):
    """启用/停用开关（归档状态需先 restore 或直接 update 状态）。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    if flag.status == "archived":
        raise ValueError("开关已归档，不能直接启停")
    before = {"status": flag.status}
    if p(request, "status") not in (None, ""):
        flag.status = services.parse_choice(
            p(request, "status"), ("active", "inactive"), "开关状态", flag.status
        )
    else:
        if p(request, "enabled") not in (None, ""):
            flag.status = "active" if bool_param(request, "enabled", True) else "inactive"
        else:
            flag.status = "inactive" if flag.status == "active" else "active"
    flag.save(update_fields=["status", "updated_at"])
    after_write(request.user, flag, "flag.toggle", before=before,
                after={"status": flag.status}, project=flag.project)
    return ok({"id": flag.id, "status": flag.status})


@endpoint()
def flag_clone(request):
    """克隆开关到同项目或指定环境（复制变体、定向规则与灰度）。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    new_key = services.parse_key(
        opt_str(request, "key").strip() or f"{flag.key}-copy", "新开关键名"
    )
    env_id = int_param(request, "environment_id", flag.environment_id, minimum=1)
    environment = get_environment(env_id, request.user, write=True)
    if environment.project_id != flag.project_id:
        raise ValueError("目标环境不属于该开关所在项目")
    try:
        with transaction.atomic():
            clone = Flag.objects.create(
                owner=request.user,
                project=flag.project,
                environment=environment,
                key=new_key,
                name=(opt_str(request, "name", f"{flag.name} 副本") or flag.name)[:200],
                description=flag.description,
                flag_type=flag.flag_type,
                status="inactive",
                temporary=flag.temporary,
                permanent=flag.permanent,
                labels=list(flag.labels or []),
                assignee=flag.assignee,
                default_variant=flag.default_variant,
            )
            for row in flag.variants.all().order_by("id"):
                Variant.objects.create(
                    owner=request.user,
                    flag=clone,
                    key=row.key,
                    name=row.name,
                    weight=row.weight,
                    payload=row.payload or {},
                )
            for row in flag.targeting_rules.all().order_by("priority", "id"):
                TargetingRule.objects.create(
                    owner=request.user,
                    flag=clone,
                    priority=row.priority,
                    conditions=row.conditions or [],
                    condition_logic=row.condition_logic,
                    variant_key=row.variant_key,
                    percentage=row.percentage,
                    enabled=row.enabled,
                    note=row.note,
                )
            for row in flag.rollouts.all().order_by("id"):
                Rollout.objects.create(
                    owner=request.user,
                    flag=clone,
                    percentage=row.percentage,
                    segment=row.segment if row.segment and row.segment.project_id == flag.project_id else None,
                    salt=row.salt,
                    start_at=row.start_at,
                    end_at=row.end_at,
                    status="paused",
                )
    except IntegrityError:
        raise ValueError("目标环境下开关键名已存在")
    after_write(request.user, clone, "flag.clone", before={"source_id": flag.id},
                after={"key": new_key}, project=flag.project)
    return ok(clone.as_dict())


@endpoint()
def flag_archive(request):
    """归档开关（保留历史与版本，评估返回 flag-archived）。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    if flag.status == "archived":
        raise ValueError("开关已归档")
    before = {"status": flag.status}
    flag.status = "archived"
    flag.save(update_fields=["status", "updated_at"])
    after_write(request.user, flag, "flag.archive", before=before,
                after={"status": "archived"}, project=flag.project)
    return ok(flag.as_dict())


@endpoint()
def flag_publish(request):
    """发布开关版本（固化变体/定向/灰度快照）。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    note = opt_str(request, "change_note") or opt_str(request, "note")
    record = services.publish_version(flag, request.user, note)
    return ok(record.as_dict())


@endpoint(("GET",))
def flag_versions(request, pk):
    """开关版本列表（可选 with_snapshot=1 返回快照）。"""
    flag = get_flag(pk, request.user)
    qs = flag.versions.select_related("publisher").order_by("-version", "-id")
    with_snapshot = bool_param(request, "with_snapshot", False)
    return paginate(qs, request, lambda obj: obj.as_dict(with_snapshot=with_snapshot))


@endpoint()
def flag_rollback(request):
    """回滚到指定版本并自动发布回滚版本。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    version_id = int_param(request, "version_id", None, minimum=1)
    if version_id:
        record = FlagVersion.objects.filter(flag=flag, pk=version_id).first()
    else:
        number = int_param(request, "version", None, minimum=1)
        if not number:
            raise ValueError("缺少必填参数: version_id 或 version")
        record = FlagVersion.objects.filter(flag=flag, version=number).first()
    if record is None:
        raise ValueError("版本不存在")
    new_record = services.restore_version(flag, record, request.user)
    flag.refresh_from_db()
    return ok({
        "flag": flag.as_dict(),
        "rolled_back_to": record.version,
        "new_version": new_record.as_dict(with_snapshot=False),
    })


@endpoint()
def flag_delete(request):
    """删除开关（级联删除变体/规则/灰度/日志，删除前写审计）。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        flag_id = int_param(request, "id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    snapshot = flag.as_dict()
    project = flag.project
    with transaction.atomic():
        services.record_audit(
            request.user, flag, "flag.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        flag.delete()
    services.invalidate_flag(flag_id)
    return ok({"deleted": True, "id": flag_id})


@endpoint(("GET",))
def flag_stats(request, pk):
    """单开关统计：评估量、命中率、原因与变体分布。"""
    flag = get_flag(pk, request.user)
    return ok(services.flag_stats(flag))


# =====================================================================
# 评估
# =====================================================================


@endpoint()
def evaluate(request):
    """单用户评估：返回 enabled/value/variant/reason 并写评估日志。"""
    flag = resolve_flag(request, request.user)
    user_key = _user_key(request)
    context = context_param(request)
    result = services.evaluate_flag(
        flag,
        user_key,
        context,
        write_log=bool_param(request, "write_log", True),
        use_cache=bool_param(request, "use_cache", True),
    )
    return ok(result)


@endpoint()
def evaluate_batch(request):
    """批量评估：一次请求最多 500 个用户，返回命中数与逐用户明细。"""
    flag = resolve_flag(request, request.user)
    raw_users = p(request, "user_keys")
    if raw_users in (None, ""):
        raw_users = p(request, "users")
    user_keys = list_param(request, "user_keys", [], max_len=500)
    if not user_keys and raw_users not in (None, ""):
        user_keys = raw_users if isinstance(raw_users, list) else [raw_users]
    if not user_keys:
        raise ValueError("缺少必填参数: user_keys")
    context = context_param(request)
    context_by_user = json_param(request, "context_by_user", {}) or {}
    if not isinstance(context_by_user, dict):
        raise ValueError("context_by_user 必须是对象")
    result = services.evaluate_batch(
        flag, [str(item) for item in user_keys], context, context_by_user
    )
    return ok(result)


@endpoint()
def evaluate_bool(request):
    """仅返回布尔值：指定开关或项目/环境下全部启用开关。"""
    user_key = _user_key(request)
    context = context_param(request)
    flag_ids = list_param(request, "flag_ids", [], max_len=200)
    flags = []
    if flag_ids:
        for raw in flag_ids:
            if isinstance(raw, dict):
                raw = raw.get("id")
            if not str(raw).isdigit():
                raise ValueError("flag_ids 必须是开关 id 数组")
            flags.append(get_flag(int(raw), request.user))
    else:
        qs = visible_flags(request.user).filter(status="active")
        project_id = p(request, "project_id")
        if project_id not in (None, ""):
            qs = qs.filter(project_id=services.parse_int(project_id, "project_id", minimum=1))
        env_id = p(request, "environment_id")
        if env_id not in (None, ""):
            qs = qs.filter(environment_id=services.parse_int(env_id, "environment_id", minimum=1))
        flags = list(qs.order_by("key")[:200])
    if not flags:
        raise ValueError("没有可评估的开关")
    return ok(services.evaluate_boolean_map(flags, user_key, context))


@endpoint()
def evaluate_explain(request):
    """解释评估：逐段展示依赖、定向、实验与灰度为什么命中/未命中。"""
    flag = resolve_flag(request, request.user)
    user_key = _user_key(request)
    context = context_param(request)
    return ok(services.explain_flag(flag, user_key, context))


@endpoint(("GET",))
def flag_evaluations(request, pk):
    """评估历史：按用户键/命中原因搜索，支持分页。"""
    flag = get_flag(pk, request.user)
    qs = flag.evaluation_logs.select_related("environment").order_by("-evaluated_at", "-id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(
            Q(user_key__icontains=keyword) | Q(matched_rule__icontains=keyword)
        )
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(matched_rule__startswith=status)
    return paginate(qs, request, lambda obj: obj.as_dict())
