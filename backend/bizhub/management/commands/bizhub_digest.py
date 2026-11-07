# -*- coding: utf-8 -*-
"""bizhub 到期订阅摘要推送。

用法：
    python manage.py bizhub_digest              # 按订阅频率给到期/临期记录发汇总通知
    python manage.py bizhub_digest --dry-run    # 只打印不发送（不更新 last_sent_at）

规则：
- 只处理 enabled 的 BizSubscription；
- daily 每天发，weekly 仅在周一发；同一天已发过的不重复发；
- 统计该用户在该模块**可见范围内**「已逾期 + 3 天内到期」且未完成的记录；
- 通知走 core.models.notify（尊重用户通知偏好与免打扰），发完更新 last_sent_at。
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from bizhub.models import BizRecord, BizSubscription
from bizhub.modules import MODULE_INDEX
from core.models import notify
from core.scoping import scope_queryset


class Command(BaseCommand):
    help = "推送 bizhub 模块的逾期/临期订阅摘要"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只打印不发送")

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        today = timezone.localdate()
        horizon = today + timedelta(days=3)
        now = timezone.now()
        is_monday = today.weekday() == 0

        subscriptions = (
            BizSubscription.objects.filter(enabled=True)
            .select_related("user")
            .order_by("user_id", "module")
        )

        processed = sent = 0
        for sub in subscriptions:
            if sub.frequency == "weekly" and not is_monday:
                continue
            if sub.last_sent_at and timezone.localdate(sub.last_sent_at) == today:
                continue
            mod = MODULE_INDEX.get(sub.module)
            if mod is None:
                continue

            processed += 1
            qs = BizRecord.objects.filter(
                module=sub.module, is_deleted=False, archived=False,
                due_date__isnull=False, due_date__lte=horizon,
            )
            qs = scope_queryset(qs, sub.user, "owner")
            done_keys = [s["key"] for s in mod["statuses"] if s.get("done")]
            if done_keys:
                qs = qs.exclude(status__in=done_keys)
            overdue = qs.filter(due_date__lt=today).count()
            upcoming = qs.filter(due_date__gte=today).count()
            total = overdue + upcoming

            title = f"{mod['name']} · 到期提醒"
            content = f"逾期 {overdue} 条，3 天内到期 {upcoming} 条，共 {total} 条待跟进。"
            link = f"/bizhub/{mod['slug']}"

            if dry_run:
                self.stdout.write(
                    f"[dry-run] {sub.user.username} {mod['slug']} "
                    f"overdue={overdue} upcoming={upcoming} freq={sub.frequency}"
                )
                continue

            notify(
                sub.user,
                title=title,
                content=content,
                category="system",
                level="warning" if overdue else "info",
                link=link,
            )
            sub.last_sent_at = now
            sub.save(update_fields=["last_sent_at"])
            sent += 1

        suffix = "（dry-run，未发送）" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"bizhub_digest：处理订阅 {processed} 条，发送 {sent} 条{suffix}"
            )
        )
        return f"processed={processed} sent={sent}"
