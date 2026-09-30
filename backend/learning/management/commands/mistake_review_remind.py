# -*- coding: utf-8 -*-
"""错题复习提醒：汇总每位用户仍未掌握的错题，每日推送一条复习通知。

用法：python manage.py mistake_review_remind
说明：
- 只统计 mastered=False 的错题，按用户聚合；
- 当日已推送过相同提醒的用户自动跳过（幂等，可重复运行）；
- 通知经 core.models.notify 创建，自动尊重用户通知偏好与免打扰时段。
"""
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from accounts.models import User
from core.models import Notification, notify
from learning.models import MistakeRecord


class Command(BaseCommand):
    help = "汇总未掌握错题并向用户推送每日复习提醒"

    def handle(self, *args, **options):
        today = timezone.localdate()
        rows = (MistakeRecord.objects.filter(mastered=False)
                .values("owner_id").annotate(n=Count("id")))
        sent = skipped = 0
        for row in rows:
            user = User.objects.filter(id=row["owner_id"], is_active=True).first()
            if not user:
                continue
            n = row["n"]
            title = f"今日有 {n} 道错题待复习"
            if Notification.objects.filter(
                recipient=user, title=title, created_at__date=today
            ).exists():
                skipped += 1
                continue
            notify(
                user, title,
                "打开「题库与组卷 → 错题本」，优先复习仍未掌握的题目，完成后可标记订正。",
                category="system", level="info", link="/learning/questions",
            )
            sent += 1
        self.stdout.write(self.style.SUCCESS(
            f"错题复习提醒完成：待复习用户 {len(rows)} 人，本轮推送 {sent} 条，跳过(已提醒) {skipped} 人"
        ))
