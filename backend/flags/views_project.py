# -*- coding: utf-8 -*-
"""功能开关 · 项目与环境接口（11 个）。

项目是权限与组织根：环境、细分、受众都挂在项目下；开关再挂到环境上。
项目成员 JSON 只用于前端展示与通知，真正的写权限仍由 owner 收口
（core.scoping.can_write），避免「成员」被误当成协作者权限。
"""
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from devtools.common import endpoint, ok, opt_str, p, req_str

from flags import services
from flags.models import (
    ENV_TYPES,
    FLAG_STATUS,
    PROJECT_STATUS,
    Environment,
    Flag,
    Project,
)
from flags.views_common import (
    after_write,
    apply_search,
    bool_param,
    can_read_project,
    can_write_project,
    get_environment,
    get_project,
    int_param,
    list_param,
    paginate,
    str_param,
)

User = get_user_model()


def _visible_projects(user):
    return services.visible(Project.objects.all(), user)


def _visible_environments(user):
    """环境可见范围：所属项目可见，或环境本身在数据范围内。"""
    if services.is_admin(user):
        return Environment.objects.all()
    project_ids = _visible_projects(user).values_list("id", flat=True)
    return Environment.objects.filter(Q(project_id__in=project_ids) | Q(owner=user)).distinct()


def _derive_key(name):
    """从名称推导项目标识；中文名无法推导时用短随机串，保证不阻塞建项目。"""
    lowered = "".join(ch for ch in str(name).lower() if ch.isalnum() or ch in "._-")
    lowered = lowered.strip("._-")
    if lowered and lowered[0].isalnum():
        return lowered[:56]
    return f"proj-{uuid.uuid4().hex[:8]}"


def _member_rows(ids):
    """成员 id 转展示行；已删除用户保持 id 展示，不丢历史配置。"""
    users = User.objects.in_bulk(ids)
    rows = []
    for user_id in ids:
        user = users.get(user_id)
        rows.append({
            "id": user_id,
            "username": getattr(user, "username", ""),
            "nickname": getattr(user, "nickname", ""),
            "exists": user is not None,
        })
    return rows


def _parse_members(request, key="members"):
    """成员参数归一：接受 [1,2] / ["1"] / [{id:1}]，最多 100 人。"""
    raw = list_param(request, key, [], max_len=100)
    ids = []
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            value = item
        elif isinstance(item, str) and item.strip().isdigit():
            value = int(item.strip())
        elif isinstance(item, dict):
            candidate = item.get("id")
            if isinstance(candidate, int):
                value = candidate
            elif isinstance(candidate, str) and candidate.isdigit():
                value = int(candidate)
            else:
                continue
        else:
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    if ids:
        existing = set(User.objects.filter(id__in=ids).values_list("id", flat=True))
        missing = [item for item in ids if item not in existing]
        if missing:
            raise ValueError(f"成员不存在: {missing[:5]}")
    return ids


# =====================================================================
# 项目
# =====================================================================


@endpoint(("GET", "POST"))
def projects(request):
    """项目列表（GET）或创建项目（POST）。"""
    if request.method == "POST":
        name = req_str(request, "name")[:120]
        raw_key = opt_str(request, "key").strip()
        key = services.parse_key(raw_key or _derive_key(name), "项目标识")
        status = services.parse_choice(
            p(request, "status"), PROJECT_STATUS, "项目状态", "active"
        )
        members = _parse_members(request)
        try:
            with transaction.atomic():
                project = Project.objects.create(
                    owner=request.user,
                    name=name,
                    key=key,
                    description=opt_str(request, "description"),
                    members=members,
                    status=status,
                    environment_count=0,
                )
                # 新项目默认建一个开发环境：没有环境的项目无法建开关，
                # 默认环境能减少一次「建项目没反应」的困惑。
                Environment.objects.create(
                    owner=request.user,
                    project=project,
                    name=opt_str(request, "default_environment", "开发")[:80] or "开发",
                    key="dev",
                    env_type="dev",
                    sort_order=10,
                    enabled=True,
                )
                project.environment_count = 1
                project.save(update_fields=["environment_count", "updated_at"])
        except IntegrityError:
            raise ValueError("项目标识已存在")
        after_write(request.user, project, "project.create", after={"key": key, "name": name})
        return ok(project.as_dict())

    qs = apply_search(_visible_projects(request.user), request, ["name", "key", "description"])
    qs = qs.order_by("-created_at", "-id")
    return paginate(qs, request, lambda obj: obj.as_dict())


@endpoint(("GET",))
def project_detail(request, pk):
    """项目详情（含环境列表与规模统计）。"""
    project = get_project(pk, request.user)
    data = project.as_dict(stats=services.project_stats(project))
    data["members_detail"] = _member_rows(sorted(project.member_ids()))
    data["environments"] = [
        env.as_dict() for env in project.environments.all().order_by("sort_order", "id")
    ]
    return ok(data)


@endpoint()
def project_update(request):
    """更新项目名称/描述/状态/成员。"""
    project_id = int_param(request, "project_id", None, minimum=1)
    if not project_id:
        project_id = int_param(request, "id", None, minimum=1)
    if not project_id:
        raise ValueError("缺少必填参数: project_id")
    project = get_project(project_id, request.user, write=True)
    before = project.as_dict()
    name = opt_str(request, "name", project.name)[:120]
    if not name.strip():
        raise ValueError("项目名称不能为空")
    project.name = name
    project.description = opt_str(request, "description", project.description)
    if p(request, "status") not in (None, ""):
        project.status = services.parse_choice(
            p(request, "status"), PROJECT_STATUS, "项目状态", project.status
        )
    if p(request, "members") not in (None, ""):
        project.members = _parse_members(request)
    if p(request, "key") not in (None, ""):
        project.key = services.parse_key(p(request, "key"), "项目标识")
    try:
        with transaction.atomic():
            project.save()
    except IntegrityError:
        raise ValueError("项目标识已存在")
    after_write(
        request.user,
        project,
        "project.update",
        before=before,
        after=project.as_dict(),
        note="成员变更" if p(request, "members") not in (None, "") else "",
    )
    return ok(project.as_dict())


@endpoint()
def project_members(request):
    """项目成员管理：action=add/remove/set。"""
    project_id = int_param(request, "project_id", None, minimum=1)
    if not project_id:
        raise ValueError("缺少必填参数: project_id")
    project = get_project(project_id, request.user, write=True)
    action = str(p(request, "action") or "set").strip().lower()
    if action not in ("add", "remove", "set"):
        raise ValueError("action 必须是 add/remove/set 之一")
    ids = _parse_members(request)
    before = list(project.members or [])
    current = sorted(project.member_ids())
    if action == "set":
        current = ids
    elif action == "add":
        current = sorted(set(current) | set(ids))
    else:
        current = [item for item in current if item not in set(ids)]
    if len(current) > 100:
        raise ValueError("项目成员最多 100 人")
    project.members = current
    project.save(update_fields=["members", "updated_at"])
    after_write(
        request.user,
        project,
        f"project.members.{action}",
        before={"members": before},
        after={"members": project.members},
    )
    return ok({
        "project_id": project.id,
        "action": action,
        "members": project.members,
        "members_detail": _member_rows(current),
        "count": len(current),
    })


@endpoint()
def project_archive(request):
    """归档项目（开关保留，但前端默认不再展示）。"""
    project_id = int_param(request, "project_id", None, minimum=1)
    if not project_id:
        raise ValueError("缺少必填参数: project_id")
    project = get_project(project_id, request.user, write=True)
    if project.status == "archived":
        raise ValueError("项目已归档")
    before = {"status": project.status}
    project.status = "archived"
    project.save(update_fields=["status", "updated_at"])
    after_write(request.user, project, "project.archive", before=before,
                after={"status": "archived"})
    return ok(project.as_dict())


@endpoint(("GET",))
def project_stats(request, pk):
    """项目统计：环境/开关/实验/灰度与近 7 天评估。"""
    project = get_project(pk, request.user)
    data = services.project_stats(project)
    data["flags_by_status"] = {
        row["status"]: row["count"]
        for row in Flag.objects.filter(project=project)
        .values("status").annotate(count=Count("id")).order_by()
    }
    return ok(data)


# =====================================================================
# 环境
# =====================================================================


@endpoint(("GET", "POST"))
def environments(request):
    """环境列表（GET）或创建环境（POST）。"""
    if request.method == "POST":
        project_id = int_param(request, "project_id", None, minimum=1)
        if not project_id:
            raise ValueError("缺少必填参数: project_id")
        project = get_project(project_id, request.user, write=True)
        name = req_str(request, "name")[:80]
        key = services.parse_key(opt_str(request, "key") or _derive_key(name), "环境标识")
        env_type = services.parse_choice(p(request, "env_type"), ENV_TYPES, "环境类型", "dev")
        try:
            with transaction.atomic():
                env = Environment.objects.create(
                    owner=request.user,
                    project=project,
                    name=name,
                    key=key,
                    env_type=env_type,
                    sort_order=int_param(request, "sort_order", 0),
                    enabled=bool_param(request, "enabled", True),
                )
                project.environment_count = project.environments.count()
                project.save(update_fields=["environment_count", "updated_at"])
        except IntegrityError:
            raise ValueError("环境标识已存在")
        after_write(request.user, env, "environment.create",
                    after={"project_id": project.id, "key": key, "env_type": env_type},
                    project=project)
        return ok(env.as_dict())

    qs = apply_search(
        _visible_environments(request.user), request, ["name", "key"], status_field=None
    )
    qs = filter_env_params(qs, request)
    qs = qs.order_by("sort_order", "id")
    return paginate(qs, request, lambda obj: obj.as_dict())


def filter_env_params(qs, request):
    """环境额外过滤：project_id / env_type / enabled。"""
    project_id = p(request, "project_id")
    if project_id not in (None, ""):
        qs = qs.filter(project_id=services.parse_int(project_id, "project_id", minimum=1))
    env_type = opt_str(request, "env_type").strip()
    if env_type:
        if env_type not in ENV_TYPES:
            raise ValueError(f"环境类型必须是 {'/'.join(ENV_TYPES)} 之一")
        qs = qs.filter(env_type=env_type)
    enabled = p(request, "enabled")
    if enabled not in (None, ""):
        qs = qs.filter(enabled=bool_param(request, "enabled", True))
    return qs


@endpoint(("GET",))
def environment_detail(request, pk):
    """环境详情（含开关数量）。"""
    env = get_environment(pk, request.user)
    data = env.as_dict()
    data["flag_count"] = env.flags.count()
    data["active_flag_count"] = env.flags.filter(status="active").count()
    return ok(data)


@endpoint()
def environment_update(request):
    """更新环境名称/类型/排序/启用状态。"""
    env_id = int_param(request, "environment_id", None, minimum=1)
    if not env_id:
        env_id = int_param(request, "id", None, minimum=1)
    if not env_id:
        raise ValueError("缺少必填参数: environment_id")
    env = get_environment(env_id, request.user, write=True)
    before = env.as_dict()
    env.name = opt_str(request, "name", env.name)[:80]
    if not env.name.strip():
        raise ValueError("环境名称不能为空")
    if p(request, "env_type") not in (None, ""):
        env.env_type = services.parse_choice(
            p(request, "env_type"), ENV_TYPES, "环境类型", env.env_type
        )
    if p(request, "key") not in (None, ""):
        env.key = services.parse_key(p(request, "key"), "环境标识")
    env.sort_order = int_param(request, "sort_order", env.sort_order)
    if p(request, "enabled") not in (None, ""):
        env.enabled = bool_param(request, "enabled", env.enabled)
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            env.save()
    except IntegrityError:
        raise ValueError("环境标识已存在")
    after_write(request.user, env, "environment.update", before=before, after=env.as_dict())
    return ok(env.as_dict())


@endpoint()
def environment_toggle(request):
    """启用/停用环境；停用后该环境所有开关评估返回 environment-disabled。"""
    env_id = int_param(request, "environment_id", None, minimum=1)
    if not env_id:
        raise ValueError("缺少必填参数: environment_id")
    env = get_environment(env_id, request.user, write=True)
    before = {"enabled": env.enabled}
    if p(request, "enabled") in (None, ""):
        env.enabled = not env.enabled
    else:
        env.enabled = bool_param(request, "enabled", env.enabled)
    env.save(update_fields=["enabled", "updated_at"])
    # 环境状态变化不写回 Flag.updated_at，必须显式清缓存
    for flag_id in env.flags.values_list("id", flat=True):
        services.invalidate_flag(flag_id)
    after_write(request.user, env, "environment.toggle", before=before,
                after={"enabled": env.enabled})
    return ok(env.as_dict())


@endpoint()
def environment_delete(request):
    """删除环境（级联删除其下开关，操作前写审计）。"""
    env_id = int_param(request, "environment_id", None, minimum=1)
    if not env_id:
        env_id = int_param(request, "id", None, minimum=1)
    if not env_id:
        raise ValueError("缺少必填参数: environment_id")
    env = get_environment(env_id, request.user, write=True)
    project = env.project
    snapshot = env.as_dict()
    flag_count = env.flags.count()
    with transaction.atomic():
        # 审计必须写在删除之前：对象没了之后 object_id 仍然可以保留，
        # 但 project 外键与快照需要先取出来。
        services.record_audit(
            request.user,
            env,
            "environment.delete",
            before=snapshot,
            after={"deleted": True, "flags": flag_count},
            project=project,
        )
        env.delete()
        project.environment_count = project.environments.count()
        project.save(update_fields=["environment_count", "updated_at"])
    return ok({"deleted": True, "id": env_id, "flags_deleted": flag_count})


# 明确引用，避免静态检查误报未使用（这些状态常量在过滤/文档中使用）
__all__ = [
    "projects",
    "project_detail",
    "project_update",
    "project_members",
    "project_archive",
    "project_stats",
    "environments",
    "environment_detail",
    "environment_update",
    "environment_toggle",
    "environment_delete",
    "FLAG_STATUS",
]

_ = FLAG_STATUS
