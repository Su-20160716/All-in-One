# -*- coding: utf-8 -*-
"""governance 应用配置（含一处针对工程内模块遮蔽的兼容补丁）。"""
import importlib.util
import os
import sys
import sysconfig

from django.apps import AppConfig


class GovernanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "governance"
    verbose_name = "合规治理"

    def ready(self):
        """应用就绪：安装标准库 code 的兼容补丁。

        背景：本项目自带 `backend/code` 包，在 `manage.py` 场景下会遮蔽
        标准库 `code`。Django 的测试运行器在**模块导入期**无条件 `import pdb`，
        而 pdb 继承 `code.InteractiveConsole`，于是 `manage.py test` 还没
        加载任何用例就会崩在 `module 'code' has no attribute 'InteractiveConsole'`。

        Django 在 fetch_command 之前已经执行 django.setup()，因此这里的 ready()
        一定早于测试运行器导入；把缺失的类从标准库 code.py 补到被遮蔽的包上，
        就能让测试命令正常启动，且不改变 `code` 应用自身的任何业务行为
        （只新增属性，从不覆盖已有名字）。
        """
        if not any("test" in arg for arg in sys.argv[:2]):
            # 只有测试命令需要 pdb；其余命令保持零副作用。
            return
        try:
            _patch_shadowed_code()
        except Exception:  # noqa: BLE001 —— 补丁失败不应阻断任何命令
            pass


def _patch_shadowed_code():
    """把标准库 code.py 的交互控制台类补到被遮蔽的 `code` 包上（幂等）。"""
    shadow = sys.modules.get("code")
    if shadow is None or hasattr(shadow, "InteractiveConsole"):
        return
    stdlib = sysconfig.get_paths().get("stdlib")
    if not stdlib:
        return
    target = os.path.join(stdlib, "code.py")
    if not os.path.exists(target):
        return
    spec = importlib.util.spec_from_file_location("_governance_stdlib_code", target)
    if spec is None or spec.loader is None:
        return
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    for name in ("InteractiveConsole", "InteractiveInterpreter",
                 "CommandCompiler", "compile_command"):
        if not hasattr(shadow, name) and hasattr(real, name):
            setattr(shadow, name, getattr(real, name))
