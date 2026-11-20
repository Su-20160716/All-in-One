# -*- coding: utf-8 -*-
"""代码工坊（v6）—— 在线编辑 + 安全执行 + 智能辅助。

设计原则（与项目既有约定一致）：
1. **独立 app，只增不改**：不动任何既有 app 的模型/接口契约；
2. **可降级适配器**：运行时（python/node/gcc/...）缺失不报 500，
   统一返回结构化 `RUNTIME_NOT_FOUND`，前端据此禁用按钮而不崩；
3. **统一异常兜底**：所有接口走 `devtools.common.endpoint`（ValueError→400，其余→422）；
4. **行级权限收口**：owner 类查询走 `core.scoping`。
"""
default_app_config = "code.apps.CodeConfig"


def _install_stdlib_code_compat():
    """本包与标准库 ``code`` 模块同名，会遮蔽后者。

    ``pdb`` 在**导入期**就引用 ``code.InteractiveConsole``，因此
    ``manage.py test``（尤其是 ``--parallel`` 的子进程）与 ``breakpoint()``
    会直接崩在 ``module 'code' has no attribute 'InteractiveConsole'``。
    这里把标准库同名模块的公开属性补齐（只新增、不覆盖本包已有名字）。
    """
    import importlib.util
    import os
    import sys
    import sysconfig

    stdlib = sysconfig.get_paths().get("stdlib")
    if not stdlib:
        return
    target = os.path.join(stdlib, "code.py")
    if not os.path.exists(target):
        return
    spec = importlib.util.spec_from_file_location("_stdlib_code_compat", target)
    if spec is None or spec.loader is None:
        return
    mod = sys.modules.get("_stdlib_code_compat")
    if mod is None:
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_stdlib_code_compat"] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001 —— 兼容失败不应阻断应用启动
            return
    pkg = sys.modules[__name__]
    for name in dir(mod):
        if name.startswith("_"):
            continue
        if not hasattr(pkg, name):
            setattr(pkg, name, getattr(mod, name))


_install_stdlib_code_compat()
