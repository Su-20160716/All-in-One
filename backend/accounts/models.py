"""用户、角色、权限（自定义 RBAC）+ 登录历史 + 租户/部门（组织架构）"""
import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

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
    tags = models.JSONField(default=list, blank=True, verbose_name="个人标签")
    dnd_start = models.TimeField(null=True, blank=True, verbose_name="免打扰开始")
    dnd_end = models.TimeField(null=True, blank=True, verbose_name="免打扰结束")
    # B12：JWT 令牌版本号。签发时写入 tv claim，认证时比对；
    # 改密 / 强制下线时 +1，令该用户此前签发的所有 token 立即失效
    # （黑名单只挡 refresh，access 在有效期内仍可用，这个字段补上这个洞）。
    token_version = models.PositiveIntegerField(default=0, verbose_name="令牌版本号")

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


# ---------------------------------------------------------------------------
# #49 用户徽章 / 成就
# ---------------------------------------------------------------------------

class Badge(models.Model):
    """徽章定义（内置 + 可扩展）"""

    LEVEL_CHOICES = [("bronze", "铜"), ("silver", "银"), ("gold", "金")]

    key = models.CharField(max_length=50, unique=True, verbose_name="徽章标识")
    name = models.CharField(max_length=100, verbose_name="徽章名称")
    icon = models.CharField(max_length=50, default="🏅", verbose_name="图标 emoji")
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="bronze", verbose_name="等级")
    rule = models.CharField(max_length=255, blank=True, verbose_name="获取规则描述")
    description = models.TextField(blank=True, verbose_name="详细说明")

    class Meta:
        verbose_name = "徽章"
        verbose_name_plural = "徽章"
        ordering = ["level", "id"]

    def __str__(self):
        return self.name


class UserBadge(models.Model):
    """用户已获得的徽章"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="badges", verbose_name="用户")
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name="awarded_users", verbose_name="徽章")
    awarded_at = models.DateTimeField(auto_now_add=True, verbose_name="获得时间")

    class Meta:
        verbose_name = "用户徽章"
        verbose_name_plural = "用户徽章"
        unique_together = [("user", "badge")]


# ---------------------------------------------------------------------------
# #52 邀请码
# ---------------------------------------------------------------------------

class InviteCode(models.Model):
    """邀请注册码"""

    code = models.CharField(max_length=32, unique=True, verbose_name="邀请码")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="invite_codes", verbose_name="邀请人")
    used_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="used_invites", verbose_name="被邀请人"
    )
    max_uses = models.IntegerField(default=1, verbose_name="最大使用次数")
    uses = models.IntegerField(default=0, verbose_name="已使用次数")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "邀请码"
        verbose_name_plural = "邀请码"
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def is_valid(self):
        if self.uses >= self.max_uses:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

    @classmethod
    def generate(cls, owner, max_uses=1, expires_days=30):
        """生成唯一邀请码"""
        for _ in range(10):
            code = secrets.token_urlsafe(8)[:8]
            if not cls.objects.filter(code=code).exists():
                break
        else:
            code = secrets.token_urlsafe(12)[:12]
        expires = timezone.now() + timezone.timedelta(days=expires_days) if expires_days else None
        return cls.objects.create(code=code, owner=owner, max_uses=max_uses, expires_at=expires)


# ---------------------------------------------------------------------------
# #56 登录设备 / 活跃会话
# ---------------------------------------------------------------------------

class ActiveSession(models.Model):
    """追踪 JWT 会话（用于设备管理 / 踢下线）"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions", verbose_name="用户")
    jti = models.CharField(max_length=64, unique=True, verbose_name="Token ID")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    device = models.CharField(max_length=60, blank=True, verbose_name="设备")
    user_agent = models.CharField(max_length=300, blank=True, verbose_name="User-Agent")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="登录时间")
    last_seen = models.DateTimeField(auto_now=True, verbose_name="最后活跃")
    is_revoked = models.BooleanField(default=False, verbose_name="已吊销")

    class Meta:
        verbose_name = "活跃会话"
        verbose_name_plural = "活跃会话"
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.user_id} {self.jti[:8]}"


# ===========================================================================
# v8 新增（F613–F626 账号与个人）—— 全部为纯新增模型/字段，向后兼容
# ===========================================================================

class DeactivateRequest(models.Model):
    """F614 注销申请：7 天冷静期，期间可撤销，到期后账号被停用"""

    STATUS_CHOICES = [("pending", "待执行"), ("cancelled", "已撤销"), ("done", "已执行")]
    COOLDOWN_DAYS = 7

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="deactivate_requests", verbose_name="用户"
    )
    reason = models.CharField(max_length=255, blank=True, verbose_name="注销原因")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending", verbose_name="状态")
    requested_at = models.DateTimeField(auto_now_add=True, verbose_name="申请时间")
    execute_at = models.DateTimeField(verbose_name="执行时间")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="撤销时间")
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")

    class Meta:
        verbose_name = "注销申请"
        verbose_name_plural = "注销申请"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.user} {self.status} @{self.requested_at:%Y-%m-%d}"

    @property
    def days_left(self):
        from datetime import datetime

        delta = self.execute_at - datetime.now(self.execute_at.tzinfo)
        return max(0, delta.days if delta.total_seconds() > 0 else 0)


class TwoFactorSecret(models.Model):
    """F615 TOTP 双因素：每用户一个共享密钥（RFC 6238，纯标准库校验）"""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="totp", verbose_name="用户"
    )
    secret = models.CharField(max_length=64, verbose_name="Base32 密钥")
    enabled = models.BooleanField(default=False, verbose_name="已启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="确认启用时间")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="最近校验时间")

    class Meta:
        verbose_name = "双因素密钥"
        verbose_name_plural = "双因素密钥"

    def __str__(self):
        return f"{self.user_id} {'on' if self.enabled else 'off'}"


class UserPreference(models.Model):
    """F620 时区与周起始日偏好（个人级，仅本人可见）"""

    WEEK_START_CHOICES = [("mon", "周一"), ("sun", "周日")]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="preference", verbose_name="用户"
    )
    timezone_name = models.CharField(max_length=64, default="Asia/Shanghai", verbose_name="时区")
    week_start = models.CharField(
        max_length=8, choices=WEEK_START_CHOICES, default="mon", verbose_name="周起始日"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "个人偏好"
        verbose_name_plural = "个人偏好"

    def __str__(self):
        return f"{self.user_id} {self.timezone_name}/{self.week_start}"


class PersonalAccessToken(models.Model):
    """F621 长期访问令牌 PAT：供脚本以 Authorization 头调用（只存哈希）"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="personal_tokens", verbose_name="用户"
    )
    name = models.CharField(max_length=80, verbose_name="令牌名称")
    token_hash = models.CharField(max_length=64, unique=True, verbose_name="令牌 SHA256")
    prefix = models.CharField(max_length=20, blank=True, verbose_name="令牌前缀(展示用)")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="最近使用")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="吊销时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "个人访问令牌"
        verbose_name_plural = "个人访问令牌"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_valid(self) -> bool:
        from django.utils import timezone as tz

        if self.revoked_at:
            return False
        if self.expires_at and tz.now() > self.expires_at:
            return False
        return True


class NicknameHistory(models.Model):
    """F622 昵称变更历史（仅本人可见）"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="nickname_history", verbose_name="用户"
    )
    old_value = models.CharField(max_length=50, blank=True, verbose_name="原昵称")
    new_value = models.CharField(max_length=50, blank=True, verbose_name="新昵称")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="变更时间")

    class Meta:
        verbose_name = "昵称变更历史"
        verbose_name_plural = "昵称变更历史"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.user_id}: {self.old_value} → {self.new_value}"


class AvatarHistory(models.Model):
    """F623 头像历史（存副本文件，可一键切换回旧头像）"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="avatar_history", verbose_name="用户"
    )
    image = models.ImageField(
        upload_to="avatars/history/", null=True, blank=True, verbose_name="历史头像"
    )
    note = models.CharField(max_length=80, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="保存时间")

    class Meta:
        verbose_name = "头像历史"
        verbose_name_plural = "头像历史"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} avatar@{self.created_at:%Y%m%d%H%M}"


class UserFollow(models.Model):
    """F618 关注 / 粉丝（轻量关系表）"""

    follower = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="following_set", verbose_name="关注者"
    )
    following = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="followers_set", verbose_name="被关注者"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="关注时间")

    class Meta:
        verbose_name = "关注关系"
        verbose_name_plural = "关注关系"
        unique_together = [("follower", "following")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.follower_id} → {self.following_id}"


class ContactAlias(models.Model):
    """F624 通讯录备注名（仅自己可见，不影响他人展示名）"""

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="contact_aliases", verbose_name="本人"
    )
    contact = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="aliased_by_set", verbose_name="联系人"
    )
    alias = models.CharField(max_length=80, verbose_name="备注名")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "通讯录备注"
        verbose_name_plural = "通讯录备注"
        unique_together = [("owner", "contact")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.owner_id}:{self.contact_id}={self.alias}"


class InviteUse(models.Model):
    """F625 邀请码使用明细（支撑邀请效果看板的按码聚合）"""

    invite = models.ForeignKey(
        InviteCode, on_delete=models.CASCADE, related_name="usages", verbose_name="邀请码"
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invite_usages", verbose_name="被邀请注册用户",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="注册时间")

    class Meta:
        verbose_name = "邀请使用记录"
        verbose_name_plural = "邀请使用记录"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invite_id} → {self.user_id}"


class RoleAuditLog(models.Model):
    """F636 角色变更历史（谁、何时、把谁的角色从 A 改成 B）"""

    ACTION_CHOICES = [
        ("assign", "分配角色"),
        ("remove", "移除角色"),
        ("set", "设置角色"),
        ("initial", "初始角色"),
    ]

    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="role_audit_acted", verbose_name="操作人",
    )
    target = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="role_audit_received", verbose_name="目标用户",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default="set", verbose_name="动作")
    roles_from = models.JSONField(default=list, blank=True, verbose_name="变更前角色")
    roles_to = models.JSONField(default=list, blank=True, verbose_name="变更后角色")
    detail = models.CharField(max_length=255, blank=True, verbose_name="备注")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "角色变更历史"
        verbose_name_plural = "角色变更历史"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.target_id}: {self.roles_from} → {self.roles_to}"
