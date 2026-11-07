# -*- coding: utf-8 -*-
"""学习时长提醒（F527）：把今日专注时长与「每日学习目标」对比，未达标 / 超标各推一条通知。

用法：python manage.py learning_goal_remind
说明：
- 只处理设置了 DailyGoal 的用户（未设置目标不打扰）；
- 未达标 → 提示还差多少分钟；已超标 → 提示注意休息；
- 当日同标题已推送则跳过（幂等，可重复运行）；
- 通知经 core.models.notify 创建，自动尊重用户通知偏好与免打扰时段。
"""
import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from core.models import Notification, notify
from learning.models import DailyGoal, LearningPref, StudySession


class Command(BaseCommand):
    help = "对比今日专注时长与每日目标，向未达标/超标的用户推送提醒"

    def handle(self, *args, **options):
        today = timezone.localdate()
        sent = skipped = 0
        # 377：尊重 study/pref/ 的每日提醒开关（关闭的用户一律不打扰）
        disabled = set(
            LearningPref.objects.filter(daily_remind=False).values_list("owner_id", flat=True)
        )
        goals = DailyGoal.objects.select_related("owner").all()
        for goal in goals:
            if goal.owner_id in disabled:
                continue
            user = User.objects.filter(id=goal.owner_id, is_active=True).first()
            target = goal.target_minutes or 0
            if not user or target <= 0:
                continue
            minutes = sum(s.minutes for s in StudySession.objects.filter(owner=user, study_date=today))
            if minutes >= target:
                if minutes >= target * 2:
                    title = f"今日已学 {minutes} 分钟，注意休息"
                    content = f"目标 {target} 分钟，今天已经超出 {minutes - target} 分钟。长时间连续学习效率会下降，建议起身活动一下。"
                    level = "warning"
                else:
                    continue  # 刚好达标不打扰
            else:
                title = f"今日还差 {target - minutes} 分钟达标"
                content = f"今日已专注 {minutes} 分钟，目标 {target} 分钟。去「我的学习 → 专注记录」再记一段就达标了。"
                level = "info"

            if Notification.objects.filter(recipient=user, title=title, created_at__date=today).exists():
                skipped += 1
                continue
            notify(user, title, content, category="system", level=level, link="/learning/study")
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            f"学习时长提醒完成：扫描 {goals.count()} 个目标，本轮推送 {sent} 条，跳过(已提醒) {skipped} 条"
        ))
