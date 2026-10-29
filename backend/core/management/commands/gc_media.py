"""F05 孤儿物理文件清理。

默认 dry-run；只有显式 --apply 才真正删除。
跳过仍被其他未删除文件共享同一 storage_path 的物理文件（秒传场景）。
"""
import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import AttachmentRef
from files.models import FileMeta


class Command(BaseCommand):
    help = "清理回收站超期且无引用的物理文件（默认 dry-run，需 --apply 才删除）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="真正删除物理文件")
        parser.add_argument("--days", type=int, default=30, help="回收站保留天数，默认 30")

    def handle(self, *args, **options):
        apply_ = options["apply"]
        days = max(1, options["days"])
        cutoff = timezone.now() - timedelta(days=days)

        qs = FileMeta.objects.filter(is_deleted=True).filter(
            Q(deleted_at__lt=cutoff) | Q(deleted_at__isnull=True, created_at__lt=cutoff)
        )
        referenced = set(AttachmentRef.objects.values_list("file_id", flat=True))
        shared_paths = set(FileMeta.objects.filter(is_deleted=False).values_list("storage_path", flat=True))

        removed, skipped_ref, skipped_shared, missing = 0, 0, 0, 0
        for meta in qs.iterator(chunk_size=200):
            if meta.id in referenced:
                skipped_ref += 1
                continue
            if meta.storage_path in shared_paths:
                skipped_shared += 1
                continue
            paths = [meta.storage_path, meta.thumbnail_path, meta.pdf_path]
            existed = False
            for rel in paths:
                if not rel:
                    continue
                abs_path = os.path.join(settings.MEDIA_ROOT, rel)
                if os.path.isfile(abs_path):
                    existed = True
                    if apply_:
                        try:
                            os.remove(abs_path)
                        except OSError as exc:
                            self.stderr.write(f"删除失败 {abs_path}: {exc}")
                            continue
                elif rel == meta.storage_path:
                    missing += 1
            if existed:
                removed += 1

        mode = "已删除" if apply_ else "将删除（dry-run）"
        self.stdout.write(
            f"{mode} {removed} 个文件的物理副本；跳过 有引用={skipped_ref} 共享路径={skipped_shared}；"
            f"源文件缺失={missing}。"
            + ("" if apply_ else " 加 --apply 执行删除。")
        )
