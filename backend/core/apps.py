from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "公共核心"

    def ready(self):
        # 注册「保存即索引 + 双链重建」信号
        from core import signals  # noqa: F401
