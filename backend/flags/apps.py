from django.apps import AppConfig


class FlagsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "flags"
    verbose_name = "功能开关与实验"
