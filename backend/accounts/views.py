"""用户认证 / 个人中心 / 角色权限管理 视图"""
import json

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import Department, LoginLog, Permission, Role, Tenant
from accounts.serializers import (
    AdminResetPasswordSerializer,
    AssignRoleSerializer,
    ChangePasswordSerializer,
    ChangeUsernameSerializer,
    DepartmentSerializer,
    LoginLogSerializer,
    PermissionSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    RoleSerializer,
    TenantSerializer,
    UserAdminCreateSerializer,
    UserDirectorySerializer,
    UserSerializer,
)
from core.models import OperationLog
from core.pagination import StandardPagination
from core.scoping import describe_scope
from core.utils import get_client_ip

User = get_user_model()


def parse_device(ua: str) -> str:
    ua = ua or ""
    if "Mobile" in ua or "Android" in ua or "iPhone" in ua:
        return "移动端"
    if "Windows" in ua:
        return "Windows"
    if "Macintosh" in ua or "Mac OS" in ua:
        return "macOS"
    if "Linux" in ua:
        return "Linux"
    return "未知设备"


def record_login(request, user, success=True, username=""):
    LoginLog.objects.create(
        user=user if success else None,
        username=username or (user.username if user else ""),
        ip=get_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:300],
        device=parse_device(request.META.get("HTTP_USER_AGENT", "")),
        is_success=success,
    )


class LoginView(TokenObtainPairView):
    """登录：成功后记录登录历史并附带用户信息"""

    def post(self, request, *args, **kwargs):
        username = request.data.get("username", "")
        resp = super().post(request, *args, **kwargs)
        if resp.status_code == 200:
            user = User.objects.filter(username=username).first()
            if user:
                record_login(request, user, True, username)
                resp.data["user"] = UserSerializer(user).data
        return resp


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = RegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        token = RefreshToken.for_user(user)
        OperationLog.objects.create(
            user=user, module="accounts", action="create", target="用户注册", detail=user.username,
            ip=get_client_ip(request),
        )
        record_login(request, user, True, user.username)
        return Response(
            {
                "access": str(token.access_token),
                "refresh": str(token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LogoutView(APIView):
    """登出：把 refresh token 加入黑名单"""

    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass
        OperationLog.objects.create(
            user=request.user, module="accounts", action="logout", target="退出登录", ip=get_client_ip(request)
        )
        return Response({"message": "已退出登录"})


class ProfileView(APIView):
    """查看 / 修改个人资料"""

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        ser = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"message": "资料已更新", "user": UserSerializer(request.user).data})


class ChangeUsernameView(APIView):
    """修改登录用户名"""

    def post(self, request):
        ser = ChangeUsernameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        old = request.user.username
        request.user.username = ser.validated_data["username"]
        request.user.save(update_fields=["username"])
        OperationLog.objects.create(
            user=request.user, module="accounts", action="update", target="修改用户名", detail=f"{old} → {request.user.username}",
            ip=get_client_ip(request),
        )
        return Response({"message": "用户名已修改", "user": UserSerializer(request.user).data})


class ChangePasswordView(APIView):
    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"message": "密码修改成功，请重新登录"})


class AvatarView(APIView):
    """头像：POST 上传 / DELETE 移除"""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.FILES.get("avatar")
        if not file:
            return Response({"message": "请选择头像文件"}, status=status.HTTP_400_BAD_REQUEST)
        request.user.avatar = file
        request.user.save(update_fields=["avatar"])
        return Response({"message": "头像已更新", "url": request.user.avatar.url if request.user.avatar else ""})

    def delete(self, request):
        if request.user.avatar:
            request.user.avatar.delete(save=False)
            request.user.avatar = None
            request.user.save(update_fields=["avatar"])
        return Response({"message": "头像已移除"})


class DeactivateSelfView(APIView):
    """注销当前账号（停用，保留数据）"""

    def post(self, request):
        password = request.data.get("password", "")
        if not request.user.check_password(password):
            return Response({"message": "密码不正确，无法注销"}, status=status.HTTP_400_BAD_REQUEST)
        request.user.is_active = False
        request.user.is_disabled = True
        request.user.save(update_fields=["is_active", "is_disabled"])
        OperationLog.objects.create(user=request.user, module="accounts", action="other", target="注销账号", ip=get_client_ip(request))
        return Response({"message": "账号已注销"})


class DataExportView(APIView):
    """导出我的全部个人数据（GDPR 数据包）"""

    def get(self, request):
        from files.models import FileMeta
        from notes.models import Note
        from projects.models import TaskCard
        from im.models import ChatSession

        u = request.user
        data = {
            "profile": UserSerializer(u).data,
            "files": list(FileMeta.objects.filter(owner=u).values("id", "name", "size", "kind", "created_at")),
            "notes": list(Note.objects.filter(owner=u).values("id", "title", "content", "created_at", "updated_at")),
            "tasks": list(
                TaskCard.objects.filter(assignees=u).values("id", "title", "status", "priority", "due_date")
            ),
            "sessions": list(ChatSession.objects.filter(members=u).values("id", "name", "type", "created_at")),
            "exported_at": timezone.now().isoformat(),
        }
        return Response(data)


class HeartbeatView(APIView):
    """前端定时心跳，刷新在线状态"""

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(last_active_at=timezone.now())
        return Response({"ok": True, "server_time": timezone.now().isoformat()})


class UsernameCheckView(APIView):
    """用户名可用性校验（注册/改名实时提示）"""

    permission_classes = [AllowAny]

    def get(self, request):
        username = (request.query_params.get("username") or "").strip()
        if len(username) < 3:
            return Response({"valid": False, "available": False, "message": "至少 3 个字符"})
        exists = User.objects.filter(username=username).exists()
        return Response({"valid": True, "available": not exists, "message": "可用" if not exists else "已被占用"})


class LoginHistoryView(APIView):
    """我的登录历史"""

    def get(self, request):
        qs = LoginLog.objects.filter(user=request.user)
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        return Response({
            "list": LoginLogSerializer(page, many=True).data,
            "total": qs.count(),
            "page": pg.page.number if pg.page else 1,
        })


class UserDirectoryView(APIView):
    """全员用户名录（登录可见，用于 @、拉人、发起聊天）"""

    def get(self, request):
        qs = User.objects.filter(is_active=True, is_disabled=False)
        keyword = request.query_params.get("q")
        if keyword:
            qs = qs.filter(Q(username__icontains=keyword) | Q(nickname__icontains=keyword) | Q(email__icontains=keyword))
        qs = qs.order_by("username")[:50]
        return Response({"list": UserDirectorySerializer(qs, many=True).data, "total": qs.count()})


class UserListView(APIView):
    """用户列表（管理员）：支持关键词、状态、角色筛选"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = User.objects.all().distinct()
        keyword = request.query_params.get("keyword")
        status_f = request.query_params.get("status")
        role = request.query_params.get("role")
        if keyword:
            qs = qs.filter(Q(username__icontains=keyword) | Q(nickname__icontains=keyword) | Q(email__icontains=keyword))
        if status_f == "disabled":
            qs = qs.filter(is_disabled=True)
        elif status_f == "active":
            qs = qs.filter(is_disabled=False)
        elif status_f == "admin":
            qs = qs.filter(Q(is_superuser=True) | Q(roles__code="admin"))
        if role:
            qs = qs.filter(roles__code=role)
        pg = StandardPagination()
        page = pg.paginate_queryset(qs.order_by("-date_joined"), request)
        data = UserSerializer(page, many=True).data
        return Response({"list": data, "total": qs.count(), "page": pg.page.number if pg.page else 1})


class UserDetailView(APIView):
    """用户详情 / 编辑 / 禁用启用（管理员）"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return User.objects.filter(pk=pk).first()

    def get(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response({"message": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        user = self.get_object(pk)
        if not user:
            return Response({"message": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        for field in ("nickname", "email", "phone", "bio"):
            if field in request.data:
                setattr(user, field, request.data[field])
        if "storage_quota_mb" in request.data:
            user.storage_quota_mb = int(request.data["storage_quota_mb"])
        if "is_disabled" in request.data:
            user.is_disabled = bool(request.data["is_disabled"])
            user.is_active = not user.is_disabled
        if "department" in request.data:
            dept_id = request.data.get("department")
            user.department = Department.objects.filter(pk=dept_id).first() if dept_id else None
        if "tenant" in request.data:
            tenant_id = request.data.get("tenant")
            user.tenant = Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
        user.save()
        role_ids = request.data.get("role_ids")
        if isinstance(role_ids, list):
            user.roles.set(Role.objects.filter(id__in=role_ids))
        return Response({"message": "已更新", "user": UserSerializer(user).data})


class UserCreateView(APIView):
    """管理员创建用户"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        ser = UserAdminCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        return Response({"message": "用户已创建", "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class AdminResetPasswordView(APIView):
    """管理员重置指定用户密码"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if not user:
            return Response({"message": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        ser = AdminResetPasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user.set_password(ser.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"message": "密码已重置"})


class AdminBatchActionView(APIView):
    """管理员批量操作用户：启用/禁用/删除/分配角色/设置配额"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        action = request.data.get("action")
        ids = request.data.get("user_ids") or []
        if not ids:
            return Response({"message": "未选择用户"}, status=status.HTTP_400_BAD_REQUEST)
        qs = User.objects.filter(id__in=ids)
        if action == "enable":
            qs.update(is_disabled=False, is_active=True)
            msg = f"已启用 {len(ids)} 个用户"
        elif action == "disable":
            qs.update(is_disabled=True, is_active=False)
            msg = f"已禁用 {len(ids)} 个用户"
        elif action == "delete":
            n = qs.exclude(is_superuser=True).delete()[0]
            msg = f"已删除 {n} 个用户"
        elif action == "quota":
            quota = int(request.data.get("storage_quota_mb", 2048))
            n = qs.update(storage_quota_mb=quota)
            msg = f"已为 {n} 个用户设置配额 {quota}MB"
        elif action == "roles":
            role_ids = request.data.get("role_ids") or []
            roles = Role.objects.filter(id__in=role_ids)
            n = 0
            for u in qs:
                u.roles.set(roles)
                n += 1
            msg = f"已为 {n} 个用户分配角色"
        else:
            return Response({"message": "未知操作"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": msg})


class AssignRoleView(APIView):
    """批量分配角色"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        ser = AssignRoleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        users = User.objects.filter(id__in=ser.validated_data["user_ids"])
        roles = Role.objects.filter(id__in=ser.validated_data["role_ids"])
        for u in users:
            u.roles.set(roles)
        return Response({"message": f"已为 {users.count()} 个用户分配角色"})


class RoleListView(APIView):
    """角色列表 / 创建"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Role.objects.all()
        return Response({"list": RoleSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not name or not code:
            return Response({"message": "角色名与编码不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        if Role.objects.filter(code=code).exists():
            return Response({"message": "角色编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.create(
            name=name, code=code, description=request.data.get("description", ""),
            data_scope=request.data.get("data_scope") or "self",
        )
        tenant_id = request.data.get("tenant")
        if tenant_id:
            role.tenant = Tenant.objects.filter(pk=tenant_id).first()
            role.save(update_fields=["tenant"])
        perm_ids = request.data.get("permission_ids") or []
        if perm_ids:
            role.permissions.set(Permission.objects.filter(id__in=perm_ids))
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    """角色详情 / 更新 / 删除"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return Role.objects.filter(pk=pk).first()

    def get(self, request, pk):
        role = self.get_object(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RoleSerializer(role).data)

    def patch(self, request, pk):
        role = self.get_object(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data:
            role.name = request.data["name"]
        if "description" in request.data:
            role.description = request.data["description"]
        if "data_scope" in request.data:
            role.data_scope = request.data["data_scope"] or "self"
        if "tenant" in request.data:
            tenant_id = request.data.get("tenant")
            role.tenant = Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
        role.save()
        permission_ids = request.data.get("permission_ids")
        if isinstance(permission_ids, list):
            role.permissions.set(Permission.objects.filter(id__in=permission_ids))
        return Response(RoleSerializer(role).data)

    def delete(self, request, pk):
        role = self.get_object(pk)
        if not role:
            return Response({"message": "角色不存在"}, status=status.HTTP_404_NOT_FOUND)
        if role.is_builtin:
            return Response({"message": "内置角色不可删除"}, status=status.HTTP_400_BAD_REQUEST)
        role.delete()
        return Response({"message": "角色已删除"})


class PermissionListView(APIView):
    """权限点列表：支持按模块分组返回"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Permission.objects.all().order_by("module", "id")
        if request.query_params.get("grouped") == "1":
            grouped = {}
            for p in PermissionSerializer(qs, many=True).data:
                grouped.setdefault(p["module"], []).append(p)
            return Response({"list": PermissionSerializer(qs, many=True).data, "grouped": grouped, "total": qs.count()})
        return Response({"list": PermissionSerializer(qs, many=True).data, "total": qs.count()})


class MyPermissionView(APIView):
    """当前用户拥有的权限编码 + 角色（前端做按钮级权限）"""

    def get(self, request):
        user = request.user
        codes = list(user.roles.values_list("permissions__code", flat=True))
        if user.is_superuser:
            codes = list(Permission.objects.values_list("code", flat=True))
        return Response(
            {
                "is_admin": user.is_admin_role(),
                "roles": list(user.roles.values_list("code", flat=True)),
                "permissions": sorted(set(c for c in codes if c)),
            }
        )


class OnlineUsersView(APIView):
    """最近活跃用户（模拟在线状态）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        minutes = int(request.query_params.get("minutes", 15))
        qs = User.objects.filter(last_active_at__gte=timezone.now() - timezone.timedelta(minutes=minutes))
        return Response({"list": UserSerializer(qs, many=True).data, "count": qs.count()})


# ---------------- 数据范围（行级数据权限） ----------------

class MyScopeView(APIView):
    """当前用户生效的数据范围说明（前端提示可见范围）"""

    def get(self, request):
        return Response(describe_scope(request.user))


# ---------------- 组织架构：部门 ----------------

def _dept_tree(parent=None, tenant_id=None):
    """递归构建部门树"""
    qs = Department.objects.filter(parent=parent)
    if tenant_id:
        qs = qs.filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True))
    out = []
    for d in qs.order_by("sort", "id"):
        node = DepartmentSerializer(d).data
        node["children"] = _dept_tree(d, tenant_id)
        out.append(node)
    return out


class DepartmentListView(APIView):
    """部门列表（树）/ 新建部门"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        tenant = request.query_params.get("tenant")
        tenant_id = int(tenant) if tenant else None
        flat = request.query_params.get("flat") == "1"
        if flat:
            qs = Department.objects.all().order_by("sort", "id")
            if tenant_id:
                qs = qs.filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True))
            return Response({"list": DepartmentSerializer(qs, many=True).data, "total": qs.count()})
        tree = _dept_tree(None, tenant_id)
        return Response({"tree": tree, "total": Department.objects.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "部门名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        parent_id = request.data.get("parent")
        dept = Department.objects.create(
            name=name[:100],
            code=(request.data.get("code") or "")[:50],
            parent=Department.objects.filter(pk=parent_id).first() if parent_id else None,
            tenant=Tenant.objects.filter(pk=request.data.get("tenant")).first() if request.data.get("tenant") else None,
            leader=User.objects.filter(pk=request.data.get("leader")).first() if request.data.get("leader") else None,
            sort=int(request.data.get("sort") or 0),
        )
        return Response(DepartmentSerializer(dept).data, status=status.HTTP_201_CREATED)


class DepartmentDetailView(APIView):
    """部门详情 / 编辑 / 删除"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return Department.objects.filter(pk=pk).first()

    def get(self, request, pk):
        dept = self.get_object(pk)
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        data = DepartmentSerializer(dept).data
        data["descendant_ids"] = dept.descendant_ids()
        data["members"] = UserSerializer(dept.members.all()[:50], many=True).data
        return Response(data)

    def patch(self, request, pk):
        dept = self.get_object(pk)
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data and request.data["name"].strip():
            dept.name = request.data["name"].strip()[:100]
        if "code" in request.data:
            dept.code = (request.data["code"] or "")[:50]
        if "sort" in request.data:
            dept.sort = int(request.data["sort"] or 0)
        if "is_active" in request.data:
            dept.is_active = bool(request.data["is_active"])
        if "leader" in request.data:
            lid = request.data.get("leader")
            dept.leader = User.objects.filter(pk=lid).first() if lid else None
        if "parent" in request.data:
            pid = request.data.get("parent")
            # 防止把上级设为自己或自己的后代，造成环
            if pid and int(pid) in (dept.descendant_ids(include_self=True)):
                return Response({"message": "不能将部门移动到自身或其下级"}, status=400)
            dept.parent = Department.objects.filter(pk=pid).first() if pid else None
        dept.save()
        return Response(DepartmentSerializer(dept).data)

    def delete(self, request, pk):
        dept = self.get_object(pk)
        if not dept:
            return Response({"message": "部门不存在"}, status=status.HTTP_404_NOT_FOUND)
        if dept.members.exists():
            return Response({"message": "该部门下仍有成员，请先转移成员"}, status=status.HTTP_400_BAD_REQUEST)
        if dept.children.exists():
            return Response({"message": "该部门下仍有子部门，请先处理子部门"}, status=status.HTTP_400_BAD_REQUEST)
        dept.delete()
        return Response({"message": "部门已删除"})


# ---------------- 多租户 ----------------

class TenantListView(APIView):
    """租户列表 / 新建租户"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Tenant.objects.all().order_by("id")
        return Response({"list": TenantSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not name or not code:
            return Response({"message": "租户名与编码不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        if Tenant.objects.filter(code=code).exists():
            return Response({"message": "租户编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        tenant = Tenant.objects.create(
            name=name[:100], code=code[:50], remark=(request.data.get("remark") or "")[:255]
        )
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


class TenantDetailView(APIView):
    """租户详情 / 编辑 / 删除"""

    permission_classes = [IsAdminUser]

    def get_object(self, pk):
        return Tenant.objects.filter(pk=pk).first()

    def get(self, request, pk):
        tenant = self.get_object(pk)
        if not tenant:
            return Response({"message": "租户不存在"}, status=status.HTTP_404_NOT_FOUND)
        data = TenantSerializer(tenant).data
        data["departments"] = DepartmentSerializer(tenant.departments.all(), many=True).data
        data["user_count"] = tenant.users.count()
        return Response(data)

    def patch(self, request, pk):
        tenant = self.get_object(pk)
        if not tenant:
            return Response({"message": "租户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data:
            tenant.name = request.data["name"]
        if "remark" in request.data:
            tenant.remark = request.data["remark"]
        if "expire_at" in request.data:
            tenant.expire_at = request.data["expire_at"] or None
        if "is_active" in request.data:
            tenant.is_active = bool(request.data["is_active"])
        tenant.save()
        return Response(TenantSerializer(tenant).data)

    def delete(self, request, pk):
        tenant = self.get_object(pk)
        if not tenant:
            return Response({"message": "租户不存在"}, status=status.HTTP_404_NOT_FOUND)
        if tenant.users.exists():
            return Response({"message": "该租户下仍有用户，无法删除"}, status=status.HTTP_400_BAD_REQUEST)
        tenant.delete()
        return Response({"message": "租户已删除"})
