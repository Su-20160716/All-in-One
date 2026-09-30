# -*- coding: utf-8 -*-
"""清理回收站中超过保留天数的文件（到期自动清理策略）。

用法：
    python manage.py clean_expired_files            # 按 settings.TRASH_KEEP_DAYS
    python manage.py clean_expired_files --days 7    # 覆盖保留天数
    python manage.py clean_expired_files --dry-run  # 只统计不删除
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from files.models import FileMeta


class Command(BaseCommand):
    help = "物理删除回收站中超过保留天数的文件"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="覆盖保留天数（默认取 settings.TRASH_KEEP_DAYS）")
        parser.add_argument("--dry-run", action="store_true", help="只统计，不真正删除")

    def handle(self, *args, **options):
        days = options["days"] or getattr(settings, "TRASH_KEEP_DAYS", 30)
        if days < 1:
            self.stderr.write("--days 必须 >= 1")
            return
        threshold = timezone.now() - timedelta(days=days)
        qs = FileMeta.objects.filter(is_deleted=True, deleted_at__lt=threshold)
        total = qs.count()
        self.stdout.write(f"回收站中超期 {days} 天的文件数：{total}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry-run：未删除任何文件"))
            return
        removed = 0
        for fm in qs.iterator():
            fm.delete()
            removed += 1
        self.stdout.write(self.style.SUCCESS(f"已物理删除 {removed} 个过期回收文件"))
