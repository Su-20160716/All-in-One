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
    path("profile/badges/", views.MyBadgesView.as_view(), name="my-badges"),
    path("profile/invites/", views.MyInviteCodesView.as_view(), name="my-invites"),
    path("profile/sessions/", views.MySessionsView.as_view(), name="my-sessions"),
    path("profile/sessions/<int:pk>/revoke/", views.SessionRevokeView.as_view(), name="session-revoke"),
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
    # F636 角色变更历史（管理员）
    # F08/F09/F10 组织与权限增强
    path("admin/departments/<int:pk>/move/", views.DepartmentMoveView.as_view(), name="department-move"),
    path("admin/activity-heatmap/", views.ActivityHeatmapView.as_view(), name="activity-heatmap"),
    path("admin/roles/<int:pk>/matrix/", views.RoleMatrixView.as_view(), name="role-matrix"),
    path("admin/role-audit/", views.RoleAuditLogView.as_view(), name="role-audit"),
    # ---------------- v8 新增（F613–F626 账号与个人） ----------------
    # F614 注销申请 7 天冷静期（可撤销）
    path("profile/deactivate-request/", views.DeactivateRequestView.as_view(), name="deactivate-request"),
    path("profile/deactivate-request/cancel/", views.DeactivateCancelView.as_view(), name="deactivate-cancel"),
    # F615 TOTP 双因素
    path("profile/2fa/", views.TwoFactorView.as_view(), name="totp-status"),
    path("profile/2fa/setup/", views.TwoFactorSetupView.as_view(), name="totp-setup"),
    path("profile/2fa/verify/", views.TwoFactorVerifyView.as_view(), name="totp-verify"),
    # F616 安全评分卡
    path("profile/security-score/", views.SecurityScoreView.as_view(), name="security-score"),
    # F617 个人公开主页（免登录）
    path("profile/public/<str:username>/", views.PublicProfileView.as_view(), name="public-profile"),
    # F618 关注 / 粉丝
    path("profile/follow/", views.FollowListView.as_view(), name="follow-list"),
    path("profile/follow/<str:username>/", views.FollowToggleView.as_view(), name="follow-toggle"),
    # F619 新手任务清单（注册 6 步引导）
    path("profile/onboarding/", views.OnboardingView.as_view(), name="onboarding"),
    # F620 时区与周起始日偏好
    path("profile/preferences/", views.PreferenceView.as_view(), name="preferences"),
    # F621 长期访问令牌 PAT
    path("profile/tokens/", views.PersonalTokenView.as_view(), name="pat-list"),
    path("profile/tokens/<int:pk>/", views.PersonalTokenRevokeView.as_view(), name="pat-revoke"),
    # F622 昵称变更历史
    path("profile/nickname-history/", views.NicknameHistoryView.as_view(), name="nickname-history"),
    # F623 头像历史切换
    path("profile/avatar/history/", views.AvatarHistoryView.as_view(), name="avatar-history"),
    path("profile/avatar/history/<int:pk>/restore/", views.AvatarHistoryView.as_view(), name="avatar-restore"),
    # F624 通讯录备注名（仅自己可见）
    path("profile/contacts/", views.ContactAliasView.as_view(), name="contact-aliases"),
    path("profile/contacts/<int:pk>/", views.ContactAliasDeleteView.as_view(), name="contact-alias-delete"),
    # F625 邀请效果看板
    path("profile/invite-dashboard/", views.InviteDashboardView.as_view(), name="invite-dashboard"),
]
