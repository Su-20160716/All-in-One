"""每日提醒任务：逾期卡片 / 被阻塞卡片 / 临期里程碑。

用法：python manage.py check_overdue_cards

- 逾期未完成卡片 → 提醒负责人
- 284：被依赖阻塞（is_blocked）且未完成卡片 → 提醒负责人并附阻塞卡片编号
- 287：3 天内到期且未完成的里程碑 → 提醒项目成员并写入 ProjectActivity
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import notify, notify_many
from projects.models import CardDependency, Milestone, ProjectActivity, TaskCard


class Command(BaseCommand):
    help = "检查逾期卡片、被阻塞卡片与临期里程碑并推送提醒"

    def handle(self, *args, **options):
        today = timezone.localdate()
        sent = self._notify_overdue(today)
        blocked = self._notify_blocked(today)
        milestones = self._notify_milestones(today)
        self.stdout.write(self.style.SUCCESS(
            f"提醒完成：逾期 {sent} 张，阻塞 {blocked} 张，临期里程碑 {milestones} 个"
        ))

    def _notify_overdue(self, today):
        """逾期且未完成的卡片，每张每天最多提醒一次（距上次提醒 >= 20 小时）"""
        overdue = TaskCard.objects.filter(
            due_date__lt=today, status__in=["todo", "doing"]
        ).select_related("board__project")
        sent = 0
        for card in overdue:
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
        return sent

    def _notify_blocked(self, today):
        """284：被阻塞且未完成的卡片，提醒负责人并附阻塞卡片编号（同日不重复）"""
        # 有待处理依赖的卡片：blocked_by 状态仍为 todo/doing
        blocked_pairs = (
            CardDependency.objects.filter(blocked_by__status__in=["todo", "doing"])
            .exclude(card__status="done")
            .select_related("card__board__project", "blocked_by")
        )
        grouped = {}
        for dep in blocked_pairs:
            card = dep.card
            grouped.setdefault(card.id, {"card": card, "blockers": []})["blockers"].append(dep.blocked_by)
        sent = 0
        for item in grouped.values():
            card = item["card"]
            project = card.board.project
            assignees = list(card.assignees.all())
            if not assignees:
                continue
            # 同一项目同一卡片的阻塞提醒每天只发一次（借活动流水去重）
            if ProjectActivity.objects.filter(
                project=project, action="阻塞提醒", target=card.title, created_at__date=today
            ).exists():
                continue
            codes = "、".join([b.code or f"#{b.id}" for b in item["blockers"]])[:200]
            notify_many(
                assignees,
                f"任务被阻塞：{card.title}",
                f"依赖卡片 {codes} 尚未完成，请协调推进。",
                category="project", level="warning", link=f"/projects/{project.id}/board",
            )
            ProjectActivity.objects.create(project=project, user=None, action="阻塞提醒",
                                           target=card.title)
            sent += 1
        return sent

    def _notify_milestones(self, today):
        """287：3 天内到期且未完成的里程碑提醒项目成员，并写项目动态"""
        window_end = today + timedelta(days=3)
        due = Milestone.objects.filter(
            status__in=["planned", "doing"], due_date__isnull=False, due_date__lte=window_end,
        ).select_related("project")
        sent = 0
        for ms in due:
            if ms.last_notified_at and timezone.now() - ms.last_notified_at < timedelta(hours=20):
                continue
            project = ms.project
            users = list(project.members.filter(is_active=True))
            days = (ms.due_date - today).days
            when = "已逾期" if days < 0 else ("今天到期" if days == 0 else f"还剩 {days} 天")
            notify_many(
                users,
                f"里程碑临期：{ms.name}",
                f"项目「{project.name}」的里程碑将于 {ms.due_date} 到期（{when}）。",
                category="project", level="warning", link=f"/projects/{project.id}",
            )
            ProjectActivity.objects.create(project=project, user=None, action="里程碑临期提醒",
                                           target=ms.name)
            ms.last_notified_at = timezone.now()
            ms.save(update_fields=["last_notified_at"])
            sent += 1
        return sent
