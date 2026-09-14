"""accounts 路由"""
from django.urls import path

from accounts import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("username-check/", views.UsernameCheckView.as_view(), name="username-check"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("profile/change-username/", views.ChangeUsernameView.as_view(), name="change-username"),
    path("profile/avatar/", views.AvatarView.as_view(), name="avatar"),
    path("profile/deactivate/", views.DeactivateSelfView.as_view(), name="deactivate-self"),
    path("profile/export/", views.DataExportView.as_view(), name="data-export"),
    path("profile/login-history/", views.LoginHistoryView.as_view(), name="login-history"),
    path("heartbeat/", views.HeartbeatView.as_view(), name="heartbeat"),
    path("directory/", views.UserDirectoryView.as_view(), name="user-directory"),
    path("me/permissions/", views.MyPermissionView.as_view(), name="my-permissions"),
    path("me/scope/", views.MyScopeView.as_view(), name="my-scope"),
    # 组织架构 / 租户（管理员）
    path("admin/departments/", views.DepartmentListView.as_view(), name="department-list"),
    path("admin/departments/<int:pk>/", views.DepartmentDetailView.as_view(), name="department-detail"),
    path("admin/tenants/", views.TenantListView.as_view(), name="tenant-list"),
    path("admin/tenants/<int:pk>/", views.TenantDetailView.as_view(), name="tenant-detail"),
    # 管理员
    path("admin/users/", views.UserListView.as_view(), name="user-list"),
    path("admin/users/create/", views.UserCreateView.as_view(), name="user-create"),
    path("admin/users/batch/", views.AdminBatchActionView.as_view(), name="user-batch"),
    path("admin/users/<int:pk>/", views.UserDetailView.as_view(), name="user-detail"),
    path("admin/users/<int:pk>/reset-password/", views.AdminResetPasswordView.as_view(), name="admin-reset-password"),
    path("admin/users/assign-roles/", views.AssignRoleView.as_view(), name="assign-roles"),
    path("admin/roles/", views.RoleListView.as_view(), name="role-list"),
    path("admin/roles/<int:pk>/", views.RoleDetailView.as_view(), name="role-detail"),
    path("admin/permissions/", views.PermissionListView.as_view(), name="permission-list"),
    path("admin/online/", views.OnlineUsersView.as_view(), name="online-users"),
]
