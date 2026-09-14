from django.apps import AppConfig


class ImConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "im"
    verbose_name = "站内消息"
