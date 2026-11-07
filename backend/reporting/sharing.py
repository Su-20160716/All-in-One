# -*- coding: utf-8 -*-
"""分享链接：token 生成、校验与只读访问口径。

设计
----
- token 用 ``secrets.token_urlsafe(24)``（约 192 bit 熵），不可预测；
- 校验失败按「不存在 / 已停用 / 已过期」区分中文提示，便于前端引导；
- 分享访问**只读**：公开接口只允许读已发布报表的执行结果，不暴露配置写接口；
- 访问计数用 ``F()`` 自增，避免并发读改写互相覆盖。
"""
import secrets
from datetime import timedelta

from django.utils import timezone

from reporting.models import ReportShare

TOKEN_BYTES = 24
MAX_SHARE_DAYS = 365


def new_token():
    """生成分享令牌（base64url 字符集，可直接放 URL）。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def create_share(report, user, days=7, readonly=True, note="", token=None):
    """创建分享链接：days<=0 表示永不过期（仍可手动停用）。"""
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("有效天数必须是整数")
    if days > MAX_SHARE_DAYS:
        raise ValueError(f"有效期不能超过 {MAX_SHARE_DAYS} 天")
    if days < 0:
        raise ValueError("有效天数不能为负")
    expires = timezone.now() + timedelta(days=days) if days > 0 else None
    final_token = str(token or new_token()).strip()
    if len(final_token) < 8 or len(final_token) > 64:
        raise ValueError("自定义 token 长度需在 8~64 之间")
    if ReportShare.objects.filter(token=final_token).exists():
        raise ValueError("分享 token 已存在，请换一个")
    return ReportShare.objects.create(
        report=report,
        token=final_token,
        readonly=bool(readonly),
        expires_at=expires,
        note=str(note or "")[:200],
        owner=user,
    )


def validate_share(token):
    """按 token 取有效分享，非法抛 ValueError（中文原因）。"""
    text = str(token or "").strip()
    if not text:
        raise ValueError("分享 token 不能为空")
    share = ReportShare.objects.select_related("report").filter(token=text).first()
    if share is None:
        raise ValueError("分享链接不存在")
    if not share.enabled:
        raise ValueError("分享链接已停用")
    if share.expires_at and share.expires_at <= timezone.now():
        raise ValueError("分享链接已过期")
    return share


def share_brief(share):
    """分享链接的前端展示结构（不暴露 owner 之外的用户信息）。"""
    return {
        "id": share.pk,
        "token": share.token,
        "report_id": share.report_id,
        "readonly": share.readonly,
        "enabled": share.enabled,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "expired": bool(share.expires_at and share.expires_at <= timezone.now()),
        "note": share.note,
        "view_count": share.view_count,
        "last_viewed_at": share.last_viewed_at.isoformat() if share.last_viewed_at else None,
        "created_at": share.created_at.isoformat() if share.created_at else None,
        "url_hint": f"/api/reporting/share/{share.token}/",
    }


def disable_share(share):
    """停用分享（保留记录，便于审计与误操作恢复）。"""
    if not share.enabled:
        return share
    share.enabled = False
    share.save(update_fields=["enabled"])
    return share
