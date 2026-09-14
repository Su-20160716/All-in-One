"""行级数据权限（数据范围）+ 多租户隔离的统一收口。

设计要点
--------
1. 数据范围由「角色」承载（Role.data_scope），用户取所有角色中**最宽**的一档。
2. 多租户通过「租户 → 用户集合」实现：业务模型（owner 类）**无需新增字段**，
   由本模块统一把可见范围收敛到同租户用户集合之内。
3. 默认（TENANCY_ENABLED=False 且角色 data_scope=self）行为与改造前完全一致：
   只有 `owner=request.user`，不会越权。
"""
from django.conf import settings
from django.db.models import Q

__all__ = [
    "visible_user_ids",
    "scope_queryset",
    "is_visible",
    "data_scope_of",
    "describe_scope",
]


def data_scope_of(user) -> str:
    """取用户生效的数据范围（兼容未登录/匿名）"""
    if user is None or not getattr(user, "is_authenticated", False):
        return "self"
    getter = getattr(user, "data_scope", None)
    if callable(getter):
        return getter()
    return "self"


def _tenant_user_ids(user):
    """返回本租户用户 id 集合；未启用多租户或用户无租户时返回 None（表示不限）"""
    if not getattr(settings, "TENANCY_ENABLED", False):
        return None
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        return None
    from accounts.models import User

    return set(User.objects.filter(tenant_id=tenant_id).values_list("id", flat=True))


def visible_user_ids(user):
    """返回该用户可见数据的 owner 用户 id 集合。**返回 None 表示不限制。**

    - self          仅本人
    - dept          本人 + 本部门成员
    - dept_and_sub  本人 + 本部门及全部下级部门成员
    - all           全部（受多租户开关约束）
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return set()

    scope = data_scope_of(user)
    tenant_ids = _tenant_user_ids(user)

    if scope == "all":
        return tenant_ids  # 可能是 None（不限）

    ids = {user.id}
    if scope in ("dept", "dept_and_sub"):
        dept_id = getattr(user, "department_id", None)
        if dept_id:
            from accounts.models import Department, User

            if scope == "dept":
                dept_ids = [dept_id]
            else:
                dept = Department.objects.filter(pk=dept_id).first()
                dept_ids = dept.descendant_ids() if dept else [dept_id]
            ids |= set(User.objects.filter(department_id__in=dept_ids).values_list("id", flat=True))

    if tenant_ids is not None:
        ids &= tenant_ids | {user.id}
    return ids


def scope_queryset(qs, user, owner_field="owner", co_member_field=None):
    """按用户数据范围过滤 queryset。

    :param owner_field: 归属字段名（默认 owner），比较 owner_id
    :param co_member_field: 可选的「协作成员」多对多字段名，
           即便不是数据所有者，只要是协作成员也可见（如项目成员）
    """
    ids = visible_user_ids(user)
    if ids is None:
        return qs
    if not ids:
        return qs.none()
    cond = Q(**{f"{owner_field}_id__in": ids})
    if co_member_field:
        cond |= Q(**{f"{co_member_field}__id": getattr(user, "id", None)})
    return qs.filter(cond).distinct()


def is_visible(obj, user, owner_field="owner") -> bool:
    """单对象可见性判定（详情/下载等场景）"""
    if obj is None:
        return False
    ids = visible_user_ids(user)
    if ids is None:
        return True
    owner_id = getattr(obj, f"{owner_field}_id", None)
    return owner_id in ids


def describe_scope(user) -> dict:
    """给前端展示当前用户的数据范围说明"""
    from accounts.models import DATA_SCOPE_CHOICES

    scope = data_scope_of(user)
    ids = visible_user_ids(user)
    dept = getattr(user, "department", None)
    return {
        "scope": scope,
        "scope_label": dict(DATA_SCOPE_CHOICES).get(scope, scope),
        "unlimited": ids is None,
        "visible_user_count": None if ids is None else len(ids),
        "tenant": getattr(getattr(user, "tenant", None), "name", "") if getattr(user, "tenant_id", None) else "",
        "department": dept.path_name() if dept else "",
        "tenancy_enabled": bool(getattr(settings, "TENANCY_ENABLED", False)),
    }
