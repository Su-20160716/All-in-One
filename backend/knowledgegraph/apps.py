# -*- coding: utf-8 -*-
"""knowledgegraph 应用配置。

除了常规 AppConfig，这里只处理一个仓库级历史问题：项目根目录存在
``backend/code`` 包，会在 ``sys.path[0]`` 上遮蔽标准库 ``code`` 模块；
Django 的 test 命令在 import 阶段就会 ``import pdb``，而 pdb 需要
``code.InteractiveConsole``，于是 ``manage.py test`` 直接失败。

修复位置只能在「django.setup() 之后、test 命令被 import 之前」——
AppConfig.ready() 正好是这段时间里唯一由本应用掌控的入口。这里给项目
``code`` 包补一个最小占位类，只在 test 进程中生效，不改变 code 包本身，
也不影响任何业务代码；非测试进程完全不做任何事。
"""
import sys

from django.apps import AppConfig


class KnowledgegraphConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "knowledgegraph"
    verbose_name = "知识图谱"

    def ready(self):
        _patch_test_pdb_compat()


def _patch_test_pdb_compat():
    """给被遮蔽的项目 code 包补 InteractiveConsole，保证 test 命令可导入。

    只在 ``manage.py test`` / ``pytest`` 这类测试入口下执行；占位类不实现
    任何交互能力，仅在 pdb 模块导入（类继承）时被引用，实际断点调试不可用，
    这是可以接受的取舍：仓库里没有修改 manage.py 的权限。
    """
    argv = " ".join(sys.argv[1:3]).lower()
    if "test" not in argv:
        return
    module = sys.modules.get("code")
    if module is None:
        try:
            import code as module  # noqa: F401 —— 命中项目 code 包
        except ImportError:  # pragma: no cover —— 极端裁剪环境
            return
    if hasattr(module, "InteractiveConsole"):
        return

    class _PdbConsolePlaceholder:
        """pdb 导入期所需的最小占位类（不提供实际交互）。"""

        def __init__(self, *args, **kwargs):
            self.locals = (args[0] if args else kwargs.get("locals")) or {}

        def interact(self, *args, **kwargs):  # pragma: no cover —— 不使用
            return None

    module.InteractiveConsole = _PdbConsolePlaceholder
