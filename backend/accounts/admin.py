from django.contrib import admin

from accounts.models import Permission, Role, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["username", "nickname", "email", "is_active", "is_disabled", "is_superuser", "date_joined"]
    search_fields = ["username", "nickname", "email"]
    filter_horizontal = ["roles"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_builtin"]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "module"]
    filter_horizontal = ["roles"]
