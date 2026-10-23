from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "公共核心"

    def ready(self):
        # 注册「保存即索引 + 双链重建」信号
        from core import signals  # noqa: F401

        # B10：SQLite 开启 WAL + busy_timeout（仅 sqlite 分支）。
        # WAL 让读写不再互斥（冒烟三连跑、开发时前后端并行请求不再撞
        # database is locked）；busy_timeout 与 settings 的 timeout=20 双保险。
        from django.conf import settings
        from django.db.backends.signals import connection_created

        def _sqlite_tune(sender, connection, **kwargs):
            if connection.vendor != "sqlite":
                return
            try:
                with connection.cursor() as cur:
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute("PRAGMA busy_timeout=20000")
                    cur.execute("PRAGMA synchronous=NORMAL")
            except Exception:
                pass  # pragma 失败不影响启动（只读库等场景）

        connection_created.connect(_sqlite_tune)
