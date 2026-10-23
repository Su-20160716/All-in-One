# -*- coding: utf-8 -*-
from django.apps import AppConfig


class CodeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "code"
    verbose_name = "代码工坊"

    def ready(self):
        # S2-B1：向统一适配器注册表登记执行沙箱探测。
        # 放在这里而不是 code/runtime.py——runtime 是零依赖纯标准库模块
        # （可被脚本单独引用），不能反向依赖 Django/core。
        from core import adapters

        def _sandbox_probe():
            from code import runtime as rt

            table = rt.detect_all()
            available = [v for v in table.values() if v.get("available")]
            return {
                "available": bool(available),
                "code": "OK" if available else "RUNTIME_NOT_FOUND",
                "available_count": len(available),
                "total_count": len(table),
                "platform": rt.platform.platform(),
                "is_windows": rt.IS_WINDOWS,
            }

        adapters.register_probe("sandbox", _sandbox_probe)
