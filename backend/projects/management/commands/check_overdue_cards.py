"""到期自动提醒：检查逾期未完成卡片，向负责人推送通知（每日一次）。

用法：python manage.py check_overdue_cards
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import notify
from projects.models import TaskCard


class Command(BaseCommand):
    help = "检查逾期未完成卡片并向负责人推送提醒通知"

    def handle(self, *args, **options):
        today = timezone.now().date()
        # 逾期且未完成的卡片
        overdue = TaskCard.objects.filter(
            due_date__lt=today, status__in=["todo", "doing"]
        ).select_related("board__project")
        sent = 0
        for card in overdue:
            # 每张卡片每天最多提醒一次（距上次提醒 >= 20 小时）
            if card.last_overdue_notified_at and timezone.now() - card.last_overdue_notified_at < timedelta(hours=20):
                continue
            project = card.board.project
            for u in card.assignees.all():
                notify(
                    u,
                    f"任务已逾期：{card.title}",
                    f"项目「{project.name}」中的任务截止日期为 {card.due_date}，请尽快处理。",
                    category="project",
                    level="warning",
                    link=f"/projects/{project.id}/board",
                )
            card.last_overdue_notified_at = timezone.now()
            card.save(update_fields=["last_overdue_notified_at"])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"逾期提醒完成，共检查 {overdue.count()} 张逾期卡，本轮提醒 {sent} 张"))
