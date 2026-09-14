"""重建全文索引

用法：
    python manage.py reindex_search                 # 全量重建（笔记/文件/项目/任务）
    python manage.py reindex_search --module note
    python manage.py reindex_search --user admin    # 只重建某用户的数据
    python manage.py reindex_search --purge         # 先清空索引再重建

依赖说明：pdf/docx/xlsx 正文抽取需要 pypdf / python-docx / openpyxl，
缺失时对应文件会被跳过（计入 skipped），不影响其他格式。
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.reindex import reindex_all, reindex_user

User = get_user_model()


class Command(BaseCommand):
    help = "重建全文搜索倒排索引"

    def add_arguments(self, parser):
        parser.add_argument("--module", action="append", help="只重建指定模块（可重复）")
        parser.add_argument("--user", help="只重建指定用户名自己的数据")
        parser.add_argument("--purge", action="store_true", help="重建前清空全部索引")

    def handle(self, *args, **options):
        if options["purge"]:
            from core.models import SearchDoc

            removed = SearchDoc.objects.all().delete()[0]
            self.stdout.write(f"已清空索引（{removed} 行）")

        modules = options.get("module") or None
        if options.get("user"):
            user = User.objects.filter(username=options["user"]).first()
            if not user:
                self.stderr.write(f"用户不存在：{options['user']}")
                return
            result = reindex_user(user, modules)
        else:
            result = reindex_all(modules)

        for name, info in result["detail"].items():
            skipped = info.get("skipped")
            text = f"{name}: 索引 {info.get('indexed', 0)} 篇"
            if skipped:
                text += f"，跳过 {skipped} 篇（格式不支持/体积超限/抽取为空）"
            self.stdout.write(text)
        self.stdout.write(self.style.SUCCESS(f"索引重建完成，共 {result['indexed']} 篇"))
