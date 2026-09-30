# -*- coding: utf-8 -*-
"""F680 每日一题站内提醒：到点给尚未完成今日题目的用户推送站内通知。

用法：
    python manage.py daily_challenge_notify            # 每日一次（可挂 cron / 定时任务）
    python manage.py daily_challenge_notify --force    # 忽略「今日已完成」过滤，全员重发（仍幂等去重）
    python manage.py daily_challenge_notify --dry-run  # 只统计不发送

说明：
- 通知经 core.models.notify 创建，自动尊重用户通知偏好与免打扰时段；
- 幂等：同一天同一用户已存在同名通知则跳过，可重复运行；
- 「到点」由外部调度器决定（cron 09:00 等），本命令本身不睡眠。
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from core.models import Notification, notify
from code.models import CodeDailyChallenge, CodeDailyRecord
from code.views_learn import _ensure_daily, _daily_notify_title


class Command(BaseCommand):
    help = "给未完成今日题目的用户推送「每日一题」站内提醒（幂等）"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="不跳过已完成用户（仍按通知去重）")
        parser.add_argument("--dry-run", action="store_true",
                            help="只统计，不真正发送")

    def handle(self, *args, **options):
        force = options["force"]
        dry = options["dry_run"]
        day = timezone.localdate()
        ch = _ensure_daily(day)
        title = _daily_notify_title(day)

        users = list(User.objects.filter(is_active=True).only("id", "username"))
        done_ids = set(
            CodeDailyRecord.objects.filter(challenge=ch, passed=True)
            .values_list("user_id", flat=True)
        )
        already = set(
            Notification.objects.filter(title=title, created_at__date=day)
            .values_list("recipient_id", flat=True)
        )

        sent = skipped_done = skipped_dup = 0
        for u in users:
            if not force and u.id in done_ids:
                skipped_done += 1
                continue
            if u.id in already:
                skipped_dup += 1
                continue
            if dry:
                sent += 1
                continue
            notify(
                u, title,
                f"今日一题《{ch.title}》（难度：{ch.difficulty}）还没完成，"
                f"打开「代码学习中心」练一练，保持连续打卡。",
                category="system", level="info", link="/code/learn",
            )
            sent += 1

        suffix = "（dry-run 未发送）" if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"每日一题提醒{suffix}：题目《{ch.title}》 · 用户 {len(users)} 人 · "
            f"本次发送 {sent} 条 · 已完成跳过 {skipped_done} · 已提醒跳过 {skipped_dup}"
        ))
