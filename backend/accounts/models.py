"""用户、角色、权限（自定义 RBAC）+ 登录历史 + 租户/部门（组织架构）"""
from django.contrib.auth.models import AbstractUser
from django.db import models

# 数据范围（行级数据权限）：决定该角色能看到"谁的数据"
DATA_SCOPE_CHOICES = [
    ("self", "仅本人"),
    ("dept", "本部门"),
    ("dept_and_sub", "本部门及下级部门"),
    ("all", "全部数据"),
]
DATA_SCOPE_WEIGHT = {"self": 0, "dept": 1, "dept_and_sub": 2, "all": 3}


class Tenant(models.Model):
    """租户：一套部署服务多个组织时用于数据隔离

    隔离策略：租户 → 用户集合 → 数据范围。owner 类业务模型无需增加字段，
    由 core.scoping.scope_queryset / visible_user_ids 统一收口。
    """

    name = models.CharField(max_length=100, verbose_name="租户名")
    code = models.CharField(max_length=50, unique=True, verbose_name="租户编码")
    is_active = models.BooleanField(default=True, verbose_name="启用")
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name="到期时间")
    remark = models.CharField(max_length=255, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "租户"
        verbose_name_plural = "租户"
        ordering = ["id"]

    def __str__(self):
        return self.name


class Department(models.Model):
    """部门：支持任意层级树形组织架构"""

    name = models.CharField(max_length=100, verbose_name="部门名")
    code = models.CharField(max_length=50, blank=True, verbose_name="部门编码")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children", verbose_name="上级部门"
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name="departments", verbose_name="所属租户"
    )
    leader = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="leading_departments", verbose_name="部门负责人",
    )
    sort = models.IntegerField(default=0, verbose_name="排序")
    is_active = models.BooleanField(default=True, verbose_name="启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "部门"
        verbose_name_plural = "部门"
        ordering = ["sort", "id"]
        unique_together = [("tenant", "name", "parent")]

    def __str__(self):
        return self.name

    def descendant_ids(self, include_self=True):
        """返回自身及全部下级部门 id（用于 dept_and_sub 数据范围）"""
        ids = [self.id] if include_self else []
        stack = [self.id]
        seen = {self.id}
        while stack:
            cur = stack.pop()
            for child_id in Department.objects.filter(parent_id=cur).values_list("id", flat=True):
                if child_id in seen:
                    continue
                seen.add(child_id)
                ids.append(child_id)
                stack.append(child_id)
        return ids

    def path_name(self, sep=" / "):
        """部门全路径名，如 产品中心 / 研发部"""
        parts, node, guard = [], self, 0
        while node is not None and guard < 20:
            parts.append(node.name)
            node = node.parent
            guard += 1
        return sep.join(reversed(parts))


class Role(models.Model):
    """角色：管理员 / 普通用户 / 自定义

    data_scope 为行级数据权限：同一角色下不同角色的用户可见数据范围不同。
    """

    name = models.CharField(max_length=50, unique=True, verbose_name="角色名")
    code = models.CharField(max_length=50, unique=True, verbose_name="角色编码")
    description = models.CharField(max_length=255, blank=True, verbose_name="描述")
    is_builtin = models.BooleanField(default=False, verbose_name="内置角色")
    data_scope = models.CharField(
        max_length=16, choices=DATA_SCOPE_CHOICES, default="self", verbose_name="数据范围"
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name="roles", verbose_name="所属租户"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "角色"
        verbose_name_plural = "角色"

    def __str__(self):
        return self.name

    @property
    def data_scope_label(self):
        return dict(DATA_SCOPE_CHOICES).get(self.data_scope, self.data_scope)


class Permission(models.Model):
    """细粒度权限点：模块 + 动作，例如 files:upload"""

    MODULE_CHOICES = [
        ("files", "文件"),
        ("notes", "笔记"),
        ("projects", "项目"),
        ("im", "消息"),
        ("admin", "后台"),
        ("tools", "工具"),
    ]
    module = models.CharField(max_length=32, choices=MODULE_CHOICES, verbose_name="模块")
    code = models.CharField(max_length=64, unique=True, verbose_name="权限编码")
    name = models.CharField(max_length=100, verbose_name="权限名")
    roles = models.ManyToManyField(Role, related_name="permissions", blank=True, verbose_name="拥有角色")

    class Meta:
        verbose_name = "权限"
        verbose_name_plural = "权限"

    def __str__(self):
        return f"{self.name} ({self.code})"


class User(AbstractUser):
    """扩展用户：昵称、头像、邮箱验证、角色多对多、禁用标志"""

    nickname = models.CharField(max_length=50, blank=True, verbose_name="昵称")
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True, verbose_name="头像")
    phone = models.CharField(max_length=20, blank=True, verbose_name="手机号")
    bio = models.CharField(max_length=255, blank=True, verbose_name="个人简介")
    is_disabled = models.BooleanField(default=False, verbose_name="已禁用")
    storage_quota_mb = models.IntegerField(default=2048, verbose_name="存储配额(MB)")
    roles = models.ManyToManyField(Role, related_name="users", blank=True, verbose_name="角色")
    tenant = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="users", verbose_name="所属租户"
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="members", verbose_name="所属部门",
    )
    last_active_at = models.DateTimeField(null=True, blank=True, verbose_name="最后活跃时间")

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self):
        return self.username

    @property
    def display_name(self):
        return self.nickname or self.username

    def has_permission_code(self, code: str) -> bool:
        """检查用户是否拥有指定权限编码（内置管理员恒真）"""
        if self.is_superuser:
            return True
        return Permission.objects.filter(code=code, roles__users=self).exists()

    def is_admin_role(self) -> bool:
        return self.is_superuser or self.roles.filter(code__in=["admin", "ADMIN"]).exists()

    def data_scope(self) -> str:
        """取用户所有角色中最宽的数据范围（超级用户恒为 all）"""
        if self.is_superuser:
            return "all"
        scopes = list(self.roles.values_list("data_scope", flat=True))
        if not scopes:
            return "self"
        return max(scopes, key=lambda s: DATA_SCOPE_WEIGHT.get(s, 0))

    def dept_path(self) -> str:
        return self.department.path_name() if self.department_id else ""


class LoginLog(models.Model):
    """登录历史：每次成功登录记录 IP / 设备 / 时间"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="login_logs", null=True, blank=True, verbose_name="用户"
    )
    username = models.CharField(max_length=150, blank=True, verbose_name="登录账号")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    user_agent = models.CharField(max_length=300, blank=True, verbose_name="User-Agent")
    device = models.CharField(max_length=60, blank=True, verbose_name="设备")
    is_success = models.BooleanField(default=True, verbose_name="是否成功")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="登录时间")

    class Meta:
        verbose_name = "登录历史"
        verbose_name_plural = "登录历史"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.username} @ {self.created_at:%Y-%m-%d %H:%M}"
