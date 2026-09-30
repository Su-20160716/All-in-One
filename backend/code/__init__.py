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
