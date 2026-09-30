# -*- coding: utf-8 -*-
"""F689 待办重复规则：按 daily / weekly / workday 给所有用户生成今日实例。

用法：
    python manage.py scan_todo_repeat            # 扫描全体用户的重复待办
    python manage.py scan_todo_repeat --user banna   # 只扫一个用户
    python manage.py scan_todo_repeat --dry-run  # 只统计不生成

说明：
- 复用 officesuite.views_people.repeat_scan_for_user（与 todo/repeat-scan/ 接口同一实现）；
- 幂等：data.repeat_parent + data.repeat_date 去重，每天每条重复待办最多生成一次；
- 建议挂到每日定时任务（工作日规则会自动跳过周六日）。
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from officesuite.views_people import repeat_scan_for_user


class Command(BaseCommand):
    help = "扫描重复待办（daily/weekly/workday）并生成今日实例"

    def add_arguments(self, parser):
        parser.add_argument("--user", help="只扫描指定用户名")
        parser.add_argument("--dry-run", action="store_true", help="只统计，不生成")

    def handle(self, *args, **options):
        today = timezone.localdate()
        users = User.objects.filter(is_active=True)
        if options.get("user"):
            users = users.filter(username=options["user"])
            if not users.exists():
                raise SystemExit(f"用户不存在: {options['user']}")

        scanned = created = 0
        details = []
        for u in users:
            if options.get("dry_run"):
                from officesuite.models import TodoItem
                n = (TodoItem.objects.filter(owner=u)
                     .exclude(repeat_rule="none").filter(done=False).count())
                scanned += n
                continue
            out = repeat_scan_for_user(u, today)
            scanned += out["scanned"]
            created += out["created"]
            if out["created"]:
                details.append(f"{u.username}+{out['created']}")

        suffix = "（dry-run 未生成）" if options.get("dry_run") else ""
        self.stdout.write(self.style.SUCCESS(
            f"重复待办扫描{suffix}：{today} · 用户 {users.count()} 人 · "
            f"规则待办 {scanned} 条 · 新建实例 {created} 条"
            + (f" · {', '.join(details)}" if details else "")
        ))
