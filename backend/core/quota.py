# -*- coding: utf-8 -*-
"""存储配额校验（B8）

约定：
- `User.storage_quota_mb <= 0` 表示不限容量
- 已用容量 = 该用户未删除文件（is_deleted=False）的 size 合计
- 上传**初始化**与**完成**双校验：初始化挡住「明知超限还传满」的流量；
  完成时再挡一次，兜住绕过初始化直接调 complete 的路径

返回约定：不抛异常，超限返回 `(code, message)` 元组，通过返回 None，
由调用方决定响应格式（视图直接 400 + 业务错误码 1010）。
"""
from django.db.models import Sum

from core.errors import ERR_STORAGE_QUOTA


def used_bytes(user) -> int:
    """用户当前已用容量（字节）"""
    from files.models import FileMeta

    return (
        FileMeta.objects.filter(owner=user, is_deleted=False).aggregate(s=Sum("size"))["s"] or 0
    )


def check_quota(user, additional_bytes):
    """校验追加 additional_bytes 后是否超出用户配额。

    返回 None 表示通过；超限返回 (ERR_STORAGE_QUOTA, 可读文案)。
    """
    quota_mb = getattr(user, "storage_quota_mb", 0) or 0
    if quota_mb <= 0:
        return None
    limit = quota_mb * 1024 * 1024
    used = used_bytes(user)
    extra = max(0, additional_bytes or 0)
    if used + extra > limit:
        from core.utils import format_size

        return (
            ERR_STORAGE_QUOTA,
            f"存储配额不足：已用 {format_size(used)}，本次需 {format_size(extra)}，"
            f"上限 {format_size(limit)}",
        )
    return None
