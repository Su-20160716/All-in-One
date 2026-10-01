# -*- coding: utf-8 -*-
"""学习周报推送（F534）：汇总最近 7 天学习数据，向有记录的用户推送一条周报通知。

用法：python manage.py learning_weekly_report
说明：
- 统计口径为「最近 7 天」（含今天），包含时长、活跃天数、错题订正、进度更新；
- 本周无任何学习记录的用户跳过，不产生噪音；
- 同一周（按 ISO 周）内已推送则跳过（幂等，可重复运行）；
- 通知经 core.models.notify 创建，自动尊重用户通知偏好与免打扰时段。
"""
import datetime as dt

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.utils import timezone

from accounts.models import User
from core.models import Notification, notify
from learning.models import LearningProgress, MistakeRecord, StudySession


class Command(BaseCommand):
    help = "汇总最近 7 天学习数据并向用户推送学习周报"

    def handle(self, *args, **options):
        today = timezone.localdate()
        start = today - dt.timedelta(days=6)
        iso_year, iso_week, _ = today.isocalendar()
        title = f"第 {iso_week} 周学习周报"

        sent = skipped = 0
        rows = (StudySession.objects.filter(study_date__gte=start, study_date__lte=today)
                .values("owner_id").annotate(total=Sum("minutes")))
        for row in rows:
            user = User.objects.filter(id=row["owner_id"], is_active=True).first()
            if not user:
                continue
            minutes = row["total"] or 0
            days = (StudySession.objects.filter(owner=user, study_date__gte=start, study_date__lte=today)
                    .values("study_date").distinct().count())
            mistakes = MistakeRecord.objects.filter(owner=user, created_at__date__gte=start,
                                                    created_at__date__lte=today)
            fixed = mistakes.filter(mastered=True).count()
            prog = LearningProgress.objects.filter(owner=user, updated_at__date__gte=start,
                                                   updated_at__date__lte=today).count()

            # 幂等：最近 7 天内已推送过同名周报则跳过
            if Notification.objects.filter(
                recipient=user, title=title, created_at__date__gte=start, created_at__date__lte=today
            ).exists():
                skipped += 1
                continue

            content = (f"{start:%m-%d} ~ {today:%m-%d}：专注 {minutes} 分钟、活跃 {days} 天；"
                       f"新增错题 {mistakes.count()} 道、已订正 {fixed} 道；进度更新 {prog} 条。"
                       "去「我的学习 → 学习报告」可导出完整月报。")
            notify(user, title, content, category="system", level="success", link="/learning/study")
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            f"学习周报完成：第 {iso_week} 周，候选用户 {len(rows)} 人，本轮推送 {sent} 条，跳过(已推送) {skipped} 人"
        ))
