# -*- coding: utf-8 -*-
"""统一错误码目录：前端据此映射 Toast 文案。

约定：后端返回 {"code": <int>, "message": "...", "detail": ...}。
这里集中管理业务错误码，避免前后端散落 magic string。
"""

# HTTP 标准码（DRF 默认）
ERR_UNAUTHORIZED = 401          # 未登录 / Token 失效
ERR_FORBIDDEN = 403             # 无权限
ERR_NOT_FOUND = 404             # 资源不存在
ERR_METHOD_NOT_ALLOWED = 405
ERR_CONFLICT = 409              # 资源冲突
ERR_TOO_MANY = 429              # 限流

# 业务错误码（1000 段）
ERR_VALIDATION = 1001           # 参数校验失败
ERR_USERNAME_TAKEN = 1002       # 用户名已被占用
ERR_EMAIL_EXISTS = 1003         # 邮箱已注册
ERR_PASSWORD_WEAK = 1004        # 密码强度不足
ERR_PASSWORD_INCORRECT = 1005   # 原密码不正确
ERR_ACCOUNT_DISABLED = 1006     # 账号已禁用
ERR_INVITE_INVALID = 1007       # 邀请码无效/过期
ERR_INVITE_REQUIRED = 1008      # 需要邀请码才能注册
ERR_FILE_TOO_LARGE = 1009       # 文件超出大小限制
ERR_STORAGE_QUOTA = 1010        # 存储配额已满
ERR_PERMISSION_DENIED = 1011    # 无操作权限
ERR_RESOURCE_LOCKED = 1012     # 资源被锁定
ERR_NETWORK = 1013              # 网络异常
ERR_SERVER = 1014               # 服务器内部错误
ERR_TOKEN_EXPIRED = 1015       # Token 已过期
