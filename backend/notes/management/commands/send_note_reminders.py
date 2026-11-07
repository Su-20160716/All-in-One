"""F240 笔记回看提醒：扫描 remind_at 已到且未提醒的笔记并发送通知。"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.notify import dispatch
from notes.models import Note


class Command(BaseCommand):
    help = "扫描 remind_at 已到且未提醒的笔记，发送站内提醒并写 reminded_at（默认 dry-run）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="真正发送并标记已提醒")
        parser.add_argument("--limit", type=int, default=500, help="单次最多处理篇数（默认 500）")

    def handle(self, *args, **options):
        now = timezone.now()
        limit = max(1, int(options.get("limit") or 500))
        qs = (
            Note.objects.filter(reminded_at__isnull=True, is_deleted=False, remind_at__isnull=False,
                                remind_at__lte=now)
            .select_related("owner")
            .order_by("remind_at")[:limit]
        )
        rows = list(qs)
        if not options["apply"]:
            self.stdout.write(f"将提醒 {len(rows)} 篇笔记（dry-run，加 --apply 执行）")
            return
        sent = 0
        for note in rows:
            title = f"笔记提醒：{note.title}"
            excerpt = " ".join((note.content or "").split())[:120]
            try:
                dispatch(note.owner, title, excerpt, category="system", level="info",
                         link=f"/notes?id={note.id}")
            except Exception as exc:  # 单篇失败不影响其余提醒
                self.stderr.write(f"笔记 {note.id} 提醒发送失败：{exc}")
                continue
            note.reminded_at = now
            note.save(update_fields=["reminded_at"])
            sent += 1
        self.stdout.write(f"已发送 {sent} 条笔记提醒")
