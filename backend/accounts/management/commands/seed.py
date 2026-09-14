"""平台初始化命令：
python manage.py seed
- 创建内置角色（admin/user）与权限点
- 创建默认管理员（用户名/密码可用环境变量 SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD 覆盖，
  公网部署务必设置强密码，避免 admin/admin123 裸奔）
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Permission, Role

User = get_user_model()

PERMISSIONS = [
    # 文件模块
    ("files", "files:upload", "文件上传"),
    ("files", "files:download", "文件下载"),
    ("files", "files:manage", "文件管理"),
    ("files", "files:share", "文件分享"),
    # 笔记模块
    ("notes", "notes:create", "创建笔记"),
    ("notes", "notes:edit", "编辑笔记"),
    ("notes", "notes:delete", "删除笔记"),
    ("notes", "notes:share", "分享笔记"),
    # 项目模块
    ("projects", "projects:create", "创建项目"),
    ("projects", "projects:edit", "编辑项目"),
    ("projects", "projects:delete", "删除项目"),
    ("projects", "projects:manage", "项目成员管理"),
    # 消息模块
    ("im", "im:send", "发送消息"),
    ("im", "im:group", "群组管理"),
    # 后台模块
    ("admin", "admin:users", "用户管理"),
    ("admin", "admin:roles", "角色权限管理"),
    ("admin", "admin:logs", "日志查看"),
    ("admin", "admin:settings", "系统设置"),
    ("admin", "admin:stats", "统计面板"),
    # 工具模块
    ("tools", "tools:use", "工具使用"),
]

ADMIN_ROLE_PERMS = [p[1] for p in PERMISSIONS]
USER_ROLE_PERMS = [
    "files:upload", "files:download", "files:manage", "files:share",
    "notes:create", "notes:edit", "notes:delete", "notes:share",
    "projects:create", "projects:edit", "projects:delete",
    "im:send", "im:group", "tools:use",
]


class Command(BaseCommand):
    help = "初始化角色、权限与默认管理员"

    def handle(self, *args, **options):
        created_perms = {}
        for module, code, name in PERMISSIONS:
            perm, _ = Permission.objects.get_or_create(code=code, defaults={"module": module, "name": name})
            created_perms[code] = perm

        admin_role, _ = Role.objects.get_or_create(
            code="admin", defaults={"name": "管理员", "description": "拥有全部权限", "is_builtin": True}
        )
        user_role, _ = Role.objects.get_or_create(
            code="user", defaults={"name": "普通用户", "description": "默认角色", "is_builtin": True}
        )
        admin_role.permissions.set([created_perms[c] for c in ADMIN_ROLE_PERMS if c in created_perms])
        user_role.permissions.set([created_perms[c] for c in USER_ROLE_PERMS if c in created_perms])

        username = os.environ.get("SEED_ADMIN_USERNAME", "admin")
        password = os.environ.get("SEED_ADMIN_PASSWORD", "admin123")
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, nickname="系统管理员")
            self.stdout.write(self.style.SUCCESS(f"已创建管理员 {username}（密码见环境变量）"))
        else:
            self.stdout.write(f"管理员 {username} 已存在")

        self.stdout.write(self.style.SUCCESS(f"初始化完成：{len(PERMISSIONS)} 个权限点，2 个内置角色"))
