from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "公共核心"

    def ready(self):
        # 注册「保存即索引 + 双链重建」信号
        from core import signals  # noqa: F401

        # S2-B1：触发外部依赖探测注册（import 副作用）。
        # files.office / assistant.llm 尾部各自 register_probe；
        # code.apps.ready 注册 sandbox。任何单个适配器 import 失败
        # 不影响其它探测与启动（可降级原则）。
        for mod in ("files.office", "assistant.llm"):
            try:
                __import__(mod)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "S2-B1：适配器探测注册失败 module=%s", mod
                )

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
                    # 排序/临时表放内存：默认走磁盘临时文件，一旦系统 Temp 不可写
                    # （安全软件管控、只读 rootfs、容器无 /tmp）就会报
                    # "unable to open database file"，典型受害者是日志/文件导出（带
                    # Meta.ordering 的万行切片）。本项目 SQLite 规模下内存排序代价可忽略。
                    cur.execute("PRAGMA temp_store=MEMORY")
            except Exception:
                # pragma 失败不影响启动（只读库等场景）；登记日志便于排查
                # WAL 未生效时的 database is locked 问题
                import logging
                logging.getLogger(__name__).exception("B23：SQLite PRAGMA 调优失败")

        connection_created.connect(_sqlite_tune)
