"""F18 到期笔记自动归档（可由 cron / 管理命令面板触发）。"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from notes.models import Note


class Command(BaseCommand):
    help = "把 expire_at 已到且未归档的笔记置为归档（默认 dry-run）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="真正写库")

    def handle(self, *args, **options):
        now = timezone.now()
        qs = Note.objects.filter(is_archived=False, is_deleted=False, expire_at__lte=now)
        count = qs.count()
        if options["apply"]:
            updated = qs.update(is_archived=True, updated_at=now)
            self.stdout.write(f"已归档 {updated} 篇到期笔记")
        else:
            self.stdout.write(f"将归档 {count} 篇到期笔记（dry-run，加 --apply 执行）")
