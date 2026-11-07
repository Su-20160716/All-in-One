# -*- coding: utf-8 -*-
"""#68 数据保留策略：按保留天数分批清理日志与审计类大表。

默认保留期（集中在 config/settings.py，可用环境变量覆盖）：
- OperationLog      180 天（审计追溯底线，OPLOG_KEEP_DAYS）
- ShareVisit        90 天（分享访问明细，SHARE_VISIT_KEEP_DAYS）
- OutstandingToken  7 天（refresh 生命周期；只删已过期且签发超期的，不会误删有效令牌）
- Notification      90 天（只清「已读」，未读通知永不自动删除）
- SearchQueryLog    30 天（#17 搜索词默认保留期）

用法：
    python manage.py purge_retention                 # 按默认保留期清理
    python manage.py purge_retention --dry-run       # 只统计，不删除
    python manage.py purge_retention --batch 5000    # 每批删除条数（默认 2000）
    python manage.py purge_retention --only oplog,notification

定时入口：已加入 core/views.py 的 SAFE_COMMANDS 白名单，
管理员可在「管理命令面板」手动触发，也可由外部 cron 每日调用。
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 2000


def _purge(qs, batch: int, dry_run: bool) -> int:
    """分批删除，返回删除（或 dry-run 下统计到）的行数。

    一次 DELETE 全表会长时间持锁并把日志撑爆，因此按主键区间循环；
    ``delete()`` 返回 0 说明这批已不存在（并发清理），立即跳出避免死循环。
    """
    qs = qs.order_by("pk")
    if dry_run:
        return qs.count()
    total = 0
    while True:
        ids = list(qs.values_list("pk", flat=True)[:batch])
        if not ids:
            return total
        deleted, _ = qs.model.objects.filter(pk__in=ids).delete()
        total += len(ids)
        if deleted == 0:
            logger.warning("purge_retention：%s 批次未删除任何行，提前结束", qs.model.__name__)
            return total


class Command(BaseCommand):
    help = "按保留天数分批清理操作日志 / 分享访问 / 过期令牌 / 旧通知 / 搜索词（#68）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只统计，不真正删除")
        parser.add_argument("--batch", type=int, default=DEFAULT_BATCH, help=f"每批删除条数（默认 {DEFAULT_BATCH}）")
        parser.add_argument(
            "--only", default="",
            help="只清理指定项，逗号分隔：oplog,share_visit,token,notification,search_log",
        )

    def handle(self, *args, **options):
        batch = max(1, int(options["batch"] or DEFAULT_BATCH))
        dry_run = bool(options["dry_run"])
        only = {x.strip() for x in (options["only"] or "").replace("，", ",").split(",") if x.strip()}
        now = timezone.now()

        def days(name, default):
            try:
                return int(getattr(settings, name, default))
            except (TypeError, ValueError):
                return default

        def cutoff(keep_days):
            return now - timedelta(days=max(1, keep_days))

        targets = []  # (key, 说明, queryset 或无参构造器, 保留天数)

        oplog_days = days("OPLOG_KEEP_DAYS", 180)
        if oplog_days > 0:
            from core.models import OperationLog

            targets.append((
                "oplog", "操作日志",
                lambda: OperationLog.objects.filter(created_at__lt=cutoff(oplog_days)), oplog_days,
            ))

        visit_days = days("SHARE_VISIT_KEEP_DAYS", 90)
        if visit_days > 0:
            from files.models import ShareVisit

            targets.append((
                "share_visit", "分享访问明细",
                lambda: ShareVisit.objects.filter(created_at__lt=cutoff(visit_days)), visit_days,
            ))

        token_days = days("REFRESH_TOKEN_KEEP_DAYS", 7)
        if token_days > 0:
            try:
                from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

                # 双重条件：既已过期、又签发超过保留期，绝不误删还能用的 refresh 令牌
                targets.append((
                    "token", "过期刷新令牌",
                    lambda: OutstandingToken.objects.filter(
                        expires_at__lt=now, created_at__lt=cutoff(token_days)
                    ), token_days,
                ))
            except Exception:  # noqa: BLE001 —— 未启用 token_blacklist 时跳过
                logger.info("purge_retention：token_blacklist 未启用，跳过令牌清理")

        notif_days = days("NOTIFICATION_KEEP_DAYS", 90)
        if notif_days > 0:
            from core.models import Notification

            targets.append((
                "notification", "已读通知",
                lambda: Notification.objects.filter(is_read=True, created_at__lt=cutoff(notif_days)), notif_days,
            ))

        search_days = days("SEARCH_LOG_KEEP_DAYS", 30)
        if search_days > 0:
            from core.models import SearchQueryLog

            targets.append((
                "search_log", "搜索词记录",
                lambda: SearchQueryLog.objects.filter(created_at__lt=cutoff(search_days)), search_days,
            ))

        if only:
            unknown = only - {t[0] for t in targets}
            if unknown:
                self.stderr.write(f"未知的清理项：{','.join(sorted(unknown))}")
                return
            targets = [t for t in targets if t[0] in only]

        total = 0
        for key, label, build_qs, keep_days in targets:
            try:
                n = _purge(build_qs(), batch, dry_run)
            except Exception as exc:  # noqa: BLE001 —— 单类失败不拖垮整体清理
                logger.exception("purge_retention：清理 %s 失败", key)
                self.stderr.write(f"{label}（{key}）清理失败：{type(exc).__name__}")
                continue
            total += n
            prefix = "将删除" if dry_run else "已删除"
            self.stdout.write(f"{prefix} {label}（{key}，保留 {keep_days} 天）：{n} 行")

        suffix = "（dry-run：未真正删除）" if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"数据保留清理完成，共处理 {total} 行{suffix}"))
