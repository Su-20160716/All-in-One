"""用户/角色/权限/租户/部门 序列化"""
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer

from accounts.models import (
    DATA_SCOPE_CHOICES,
    ActiveSession,
    Badge,
    Department,
    InviteCode,
    LoginLog,
    Permission,
    Role,
    Tenant,
    UserBadge,
)

User = get_user_model()


class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """B12：登录签发时把 token_version 写进 tv claim，
    认证端（accounts.auth.TokenVersionJWTAuthentication）据此判断 token 是否已失效"""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["tv"] = user.token_version
        return token


class MyTokenRefreshSerializer(TokenRefreshSerializer):
    """B12：refresh 时同样校验 tv claim —— 改密后旧 refresh 一律拒绝，
    避免「旧 access 失效但旧 refresh 还能续出新 access」的半失效状态"""

    def validate(self, attrs):
        refresh = attrs["refresh"]
        try:
            user = User.objects.filter(id=refresh.get("user_id")).first()
        except Exception:
            user = None
        if user is None or refresh.get("tv") != user.token_version:
            raise InvalidToken("登录态已失效，请重新登录")
        return super().validate(attrs)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["username", "password", "nickname", "email", "phone"]

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            nickname=validated_data.get("nickname", ""),
            email=validated_data.get("email", ""),
            phone=validated_data.get("phone", ""),
        )
        # 新用户默认赋予"普通用户"角色
        default_role = Role.objects.filter(code="user").first()
        if default_role:
            user.roles.add(default_role)
        return user


class UserSerializer(serializers.ModelSerializer):
    role_names = serializers.SerializerMethodField()
    role_ids = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    department_path = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()
    data_scope = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "nickname", "email", "phone", "bio", "avatar", "tags",
            "is_superuser", "is_active", "is_disabled", "storage_quota_mb",
            "date_joined", "last_login", "last_active_at", "is_online",
            "dnd_start", "dnd_end", "role_names", "role_ids",
            "department", "department_name", "department_path", "tenant", "tenant_name", "data_scope",
        ]
        read_only_fields = ["is_superuser", "date_joined", "last_login", "last_active_at", "is_online"]
        extra_kwargs = {"department": {"required": False, "allow_null": True},
                        "tenant": {"required": False, "allow_null": True}}

    def get_role_names(self, obj):
        return list(obj.roles.values_list("name", flat=True))

    def get_role_ids(self, obj):
        return list(obj.roles.values_list("id", flat=True))

    def get_department_name(self, obj):
        return obj.department.name if obj.department_id else ""

    def get_department_path(self, obj):
        return obj.department.path_name() if obj.department_id else ""

    def get_tenant_name(self, obj):
        return obj.tenant.name if obj.tenant_id else ""

    def get_data_scope(self, obj):
        return obj.data_scope()

    def get_is_online(self, obj):
        """5 分钟内有活跃记录视为在线"""
        from django.utils import timezone
        if not obj.last_active_at:
            return False
        return (timezone.now() - obj.last_active_at).total_seconds() < 300


class TenantSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()
    dept_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ["id", "name", "code", "is_active", "expire_at", "remark",
                  "created_at", "user_count", "dept_count"]

    def get_user_count(self, obj):
        return obj.users.count()

    def get_dept_count(self, obj):
        return obj.departments.count()


class DepartmentSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    parent_name = serializers.SerializerMethodField()
    leader_name = serializers.SerializerMethodField()
    path_name = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "name", "code", "parent", "parent_name", "tenant", "leader", "leader_name",
                  "sort", "is_active", "created_at", "member_count", "path_name"]

    def get_member_count(self, obj):
        return obj.members.count()

    def get_parent_name(self, obj):
        return obj.parent.name if obj.parent_id else ""

    def get_leader_name(self, obj):
        return obj.leader.display_name if obj.leader_id else ""

    def get_path_name(self, obj):
        return obj.path_name()


class UserDirectorySerializer(serializers.ModelSerializer):
    """用户名录（精简，全员可见）"""

    display_name = serializers.CharField(read_only=True)
    role_names = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "nickname", "display_name", "avatar", "bio", "tags", "role_names",
                  "department_name", "last_active_at", "is_online"]

    def get_role_names(self, obj):
        return list(obj.roles.values_list("name", flat=True))

    def get_department_name(self, obj):
        return obj.department.path_name() if obj.department_id else ""

    def get_is_online(self, obj):
        from django.utils import timezone
        if not obj.last_active_at:
            return False
        return (timezone.now() - obj.last_active_at).total_seconds() < 300


class LoginLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginLog
        fields = ["id", "username", "ip", "user_agent", "device", "is_success", "created_at"]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["nickname", "email", "phone", "bio", "tags", "dnd_start", "dnd_end"]

    def validate_email(self, value):
        User = get_user_model()
        if value and User.objects.exclude(pk=self.instance.pk).filter(email=value).exists():
            raise serializers.ValidationError("该邮箱已被使用")
        return value


class ChangeUsernameSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=30)

    def validate_username(self, value):
        User = get_user_model()
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError("用户名只能包含字母、数字、下划线")
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被占用")
        return value


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=6)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("原密码不正确")
        return value


class AdminResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(min_length=6)


class RoleSerializer(serializers.ModelSerializer):
    permission_ids = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()
    data_scope_label = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "name", "code", "description", "is_builtin", "data_scope", "data_scope_label",
                  "tenant", "created_at", "permission_ids", "user_count"]

    def get_permission_ids(self, obj):
        return list(obj.permissions.values_list("id", flat=True))

    def get_user_count(self, obj):
        return obj.users.count()

    def get_data_scope_label(self, obj):
        return dict(DATA_SCOPE_CHOICES).get(obj.data_scope, obj.data_scope)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "module", "code", "name"]


class AssignRoleSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.IntegerField())
    role_ids = serializers.ListField(child=serializers.IntegerField())


class UserAdminCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["username", "password", "nickname", "email", "phone", "role_ids",
                  "department", "tenant"]

    role_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    department = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    tenant = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    def create(self, validated_data):
        role_ids = validated_data.pop("role_ids", [])
        department_id = validated_data.pop("department", None)
        tenant_id = validated_data.pop("tenant", None)
        user = User.objects.create_user(**validated_data)
        if role_ids:
            user.roles.set(Role.objects.filter(id__in=role_ids))
        if department_id:
            user.department = Department.objects.filter(pk=department_id).first()
        if tenant_id:
            user.tenant = Tenant.objects.filter(pk=tenant_id).first()
        if department_id or tenant_id:
            user.save(update_fields=["department", "tenant"])
        return user


# ---------------------------------------------------------------------------
# #49 徽章
# ---------------------------------------------------------------------------

class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = ["id", "key", "name", "icon", "level", "rule", "description"]


class UserBadgeSerializer(serializers.ModelSerializer):
    badge = BadgeSerializer(read_only=True)

    class Meta:
        model = UserBadge
        fields = ["id", "badge", "awarded_at"]


# ---------------------------------------------------------------------------
# #52 邀请码
# ---------------------------------------------------------------------------

class InviteCodeSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.display_name", read_only=True)
    used_by_name = serializers.CharField(source="used_by.display_name", read_only=True, default="")
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = InviteCode
        fields = ["id", "code", "owner", "owner_name", "used_by", "used_by_name",
                  "max_uses", "uses", "expires_at", "is_valid", "created_at"]
        read_only_fields = ["code", "owner", "used_by", "uses", "created_at"]


# ---------------------------------------------------------------------------
# #56 活跃会话 / 设备管理
# ---------------------------------------------------------------------------

class ActiveSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActiveSession
        fields = ["id", "ip", "device", "user_agent", "created_at", "last_seen", "is_revoked"]
        read_only_fields = fields
