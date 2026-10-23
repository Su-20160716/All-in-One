# -*- coding: utf-8 -*-
"""清理回收站中超过保留天数的文件（到期自动清理策略）。

B9：原来只删数据库记录，磁盘上的物理文件与缩略图全部残留成孤儿文件；
现在连物理文件一起清（有记录共享同一 storage_path 时只删库，不删物理）。

用法：
    python manage.py clean_expired_files            # 按 settings.TRASH_KEEP_DAYS
    python manage.py clean_expired_files --days 7    # 覆盖保留天数
    python manage.py clean_expired_files --dry-run   # 只统计不删除
"""
import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from core.utils import format_size
from files.models import FileMeta


def _safe_media_join(rel):
    """把相对路径拼到 MEDIA_ROOT 下；逃逸出媒体目录的返回 None"""
    if not rel:
        return None
    base = os.path.abspath(settings.MEDIA_ROOT)
    target = os.path.abspath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target


def _remove_physical(fm) -> int:
    """删除物理文件与缩略图，返回释放的字节数。

    - 有其他 FileMeta 记录共享同一 storage_path / thumbnail_path 时只删库不删物理
      （秒传、复制等场景会复用同一份磁盘文件）
    - 任何 IO 失败只跳过，不中断整体清理
    """
    freed = 0
    if fm.storage_path and not FileMeta.objects.filter(
        storage_path=fm.storage_path
    ).exclude(pk=fm.pk).exists():
        path = _safe_media_join(fm.storage_path)
        if path and os.path.isfile(path):
            try:
                freed += os.path.getsize(path)
                os.remove(path)
            except OSError:
                pass
    if fm.thumbnail_path and not FileMeta.objects.filter(
        thumbnail_path=fm.thumbnail_path
    ).exclude(pk=fm.pk).exists():
        path = _safe_media_join(fm.thumbnail_path)
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    return freed


class Command(BaseCommand):
    help = "物理删除回收站中超过保留天数的文件（含磁盘文件与缩略图）"

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
        will_bytes = qs.aggregate(s=Sum("size"))["s"] or 0
        self.stdout.write(
            f"回收站中超期 {days} 天的文件数：{total}（数据库记录占用 {format_size(will_bytes)}）"
        )
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry-run：未删除任何文件"))
            return
        removed = 0
        freed = 0
        for fm in qs.iterator():
            freed += _remove_physical(fm)
            fm.delete()
            removed += 1
        self.stdout.write(
            self.style.SUCCESS(f"已物理删除 {removed} 个过期回收文件，释放磁盘 {format_size(freed)}")
        )
