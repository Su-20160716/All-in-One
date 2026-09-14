"""初始化组织架构与数据范围（幂等）

用法：
    python manage.py seed_org                 # 建默认租户 + 部门树 + 回填内置角色数据范围
    python manage.py seed_org --no-departments # 只处理租户与角色

说明：
- 默认租户仅用于让多租户字段有值，不改变既有可见性
  （TENANCY_ENABLED 默认关闭，隔离策略不会因此变严）。
- 内置角色数据范围：管理员=全部（all），普通用户=仅本人（self），
  与改造前行为一致，不会让普通用户看到别人的数据。
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Department, Role, Tenant

User = get_user_model()

DEFAULT_TREE = [
    ("总部", ["研发中心", "产品中心", "市场中心"]),
    ("研发中心", ["后端组", "前端组", "测试组"]),
]

ROLE_SCOPE = {
    "admin": "all",
    "ADMIN": "all",
    "user": "self",
    "USER": "self",
}


class Command(BaseCommand):
    help = "初始化租户、部门树与角色数据范围"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-name", default="默认租户")
        parser.add_argument("--tenant-code", default="default")
        parser.add_argument("--no-departments", action="store_true", help="跳过部门树初始化")

    @transaction.atomic
    def handle(self, *args, **options):
        tenant, created = Tenant.objects.get_or_create(
            code=options["tenant_code"],
            defaults={"name": options["tenant_name"], "remark": "由 seed_org 自动创建"},
        )
        self.stdout.write(f"租户：{tenant.name}({tenant.code}) {'新建' if created else '已存在'}")

        # 回填用户租户（仅对尚无租户的用户）
        filled = User.objects.filter(tenant__isnull=True).update(tenant=tenant)
        if filled:
            self.stdout.write(f"已为 {filled} 个用户回填租户")

        if not options["no_departments"]:
            made = 0
            for parent_name, children in DEFAULT_TREE:
                parent, _ = Department.objects.get_or_create(
                    tenant=tenant, name=parent_name, parent=None,
                    defaults={"code": parent_name, "sort": 10},
                )
                for idx, child in enumerate(children, start=1):
                    _, c = Department.objects.get_or_create(
                        tenant=tenant, name=child, parent=parent,
                        defaults={"code": f"{parent.code or parent_name}-{idx}", "sort": idx * 10},
                    )
                    made += 1 if c else 0
            self.stdout.write(
                f"部门：{Department.objects.filter(tenant=tenant).count()} 个（本次新建 {made} 个）"
            )

        changed = []
        for code, scope in ROLE_SCOPE.items():
            for role in Role.objects.filter(code=code):
                if role.data_scope != scope:
                    role.data_scope = scope
                    role.tenant = role.tenant or tenant
                    role.save(update_fields=["data_scope", "tenant"])
                    changed.append(f"{role.code}={scope}")
        self.stdout.write(
            "角色数据范围：" + ("、".join(changed) if changed else "无需调整（已符合默认策略）")
        )
        self.stdout.write(self.style.SUCCESS("组织架构初始化完成"))
