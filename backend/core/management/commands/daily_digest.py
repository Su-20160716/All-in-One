"""每日摘要日报（#60）

用法：
    python manage.py daily_digest                # 给所有用户生成今日摘要
    python manage.py daily_digest --date 2026-09-25
    python manage.py daily_digest --user admin   # 只给指定用户生成

汇总每位用户当日新增的笔记/文件，生成摘要并写入通知中心。
无 LLM 密钥时自动使用本地抽取式摘要（与接口降级一致）。
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = "生成每日摘要日报并推送到通知中心"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="指定日期 YYYY-MM-DD，缺省=今天")
        parser.add_argument("--user", help="只处理指定用户名")

    def handle(self, *args, **options):
        from assistant import llm
        from core.models import notify
        from notes.models import Note
        from files.models import FileMeta

        if options["date"]:
            target = timezone.datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            target = timezone.localdate()

        users = User.objects.all()
        if options["user"]:
            users = users.filter(username=options["user"])

        done = 0
        for user in users:
            notes = Note.objects.filter(
                is_deleted=False, created_at__date=target, owner=user)
            files = FileMeta.objects.filter(
                is_deleted=False, created_at__date=target, owner=user)
            note_bodies = "\n".join((n.content or "")[:500] for n in notes[:5])
            summary = llm.extractive_summary(note_bodies, max_sentences=5) if note_bodies else ""
            notify(
                user,
                title=f"每日摘要 · {target.isoformat()}",
                content=f"新增笔记 {notes.count()} 篇，文件 {files.count()} 个。"
                        + (("\n要点：" + summary[:120]) if summary else ""),
                category="note", level="info",
            )
            done += 1
        self.stdout.write(self.style.SUCCESS(f"已为 {done} 位用户生成 {target} 摘要"))
