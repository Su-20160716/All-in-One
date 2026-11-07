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
ERR_LOGIN_LOCKED = 1016        # 登录连续失败，账号临时锁定
ERR_TWOFA_REQUIRED = 1017      # 账号已开启两步验证，需要 TOTP 验证码
ERR_TWOFA_INVALID = 1018       # 两步验证码错误或已过期

# ---------------------------------------------------------------------------
# #419 错误码目录：GET /api/core/errors/catalog/ 反射本模块全部 ERR_* 常量，
# 用下面的表补出「文案 + 处置建议（hint）」。新增常量忘了登记也能被反射出来
# （文案按常量名兜底），前端启动时拉取合并进 toast 映射即可。
# 格式：code -> (message, hint)
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    ERR_UNAUTHORIZED: ("未登录或登录态已失效", "请重新登录后再试"),
    ERR_FORBIDDEN: ("没有访问权限", "确认账号角色与数据范围，或联系管理员授权"),
    ERR_NOT_FOUND: ("资源不存在", "刷新列表确认对象是否已被删除"),
    ERR_METHOD_NOT_ALLOWED: ("请求方法不被支持", "检查请求方法（GET/POST/PATCH/DELETE）"),
    ERR_CONFLICT: ("资源状态冲突", "刷新后重试，避免并发覆盖"),
    ERR_TOO_MANY: ("请求过于频繁", "稍后再试，或脚本中加入退避重试"),
    ERR_VALIDATION: ("参数校验失败", "按 error 字段提示修正入参后重试"),
    ERR_USERNAME_TAKEN: ("用户名已被占用", "换一个用户名"),
    ERR_EMAIL_EXISTS: ("邮箱已注册", "直接登录或使用「忘记密码」找回"),
    ERR_PASSWORD_WEAK: ("密码强度不足", "至少 8 位，且不要使用常见弱口令或纯数字"),
    ERR_PASSWORD_INCORRECT: ("原密码不正确", "确认当前密码后重试"),
    ERR_ACCOUNT_DISABLED: ("账号已被禁用", "联系管理员恢复账号"),
    ERR_INVITE_INVALID: ("邀请码无效或已过期", "向邀请人索取新的邀请码"),
    ERR_INVITE_REQUIRED: ("该站点需要邀请码才能注册", "填写有效的邀请码"),
    ERR_FILE_TOO_LARGE: ("文件超出大小限制", "压缩或分片上传，或联系管理员调整上限"),
    ERR_STORAGE_QUOTA: ("存储配额已满", "清理回收站或申请扩容"),
    ERR_PERMISSION_DENIED: ("无操作权限", "确认自己是资源所有者，或申请相应角色"),
    ERR_RESOURCE_LOCKED: ("资源被锁定", "等待锁定解除后再编辑"),
    ERR_NETWORK: ("网络异常", "检查网络连接后重试"),
    ERR_SERVER: ("服务器内部错误", "稍后重试；持续失败请携带 request_id 反馈"),
    ERR_TOKEN_EXPIRED: ("登录已过期", "刷新令牌或重新登录"),
    ERR_LOGIN_LOCKED: ("登录失败次数过多，账号临时锁定", "等待锁定期结束或联系管理员解锁"),
    ERR_TWOFA_REQUIRED: ("需要两步验证码", "输入验证器中的 6 位动态码"),
    ERR_TWOFA_INVALID: ("两步验证码错误或已过期", "校准手机时间后重新输入当前验证码"),
}


def _humanize_error_name(name: str) -> str:
    """未登记文案时的兜底：ERR_FILE_TOO_LARGE → FILE TOO LARGE"""
    return name[4:].replace("_", " ") if name.startswith("ERR_") else name


def error_catalog() -> list:
    """反射本模块 ERR_* 常量 → [{code, name, message, hint}]（按 code 排序）"""
    rows = {}
    for name in list(globals()):
        if not name.startswith("ERR_"):
            continue
        code = globals().get(name)
        if not isinstance(code, int) or isinstance(code, bool):
            continue
        message, hint = ERROR_CATALOG.get(code, ("", ""))
        row = rows.setdefault(code, {
            "code": code,
            "names": [],
            "message": message or _humanize_error_name(name),
            "hint": hint or "见接口文档或联系管理员",
        })
        row["names"].append(name)
    out = []
    for code in sorted(rows):
        row = rows[code]
        row["name"] = row["names"][0]
        out.append(row)
    return out
