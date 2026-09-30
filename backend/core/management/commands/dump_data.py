# -*- coding: utf-8 -*-
"""#68 备份数据到 JSON 文件"""
import os
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "备份所有业务数据到 JSON 文件（backup_YYYYMMDD_HHMMSS.json）"

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", type=str, default="", help="输出文件路径")

    def handle(self, *args, **options):
        out = options["output"]
        if not out:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = str(settings.BASE_DIR / f"backup_{ts}.json")
        # 排除 contenttypes / sessions / admin log，只备份业务数据
        excludes = ["contenttypes", "auth.Permission", "sessions", "admin.LogEntry"]
        call_command("dumpdata", "--indent", "2", "--output", out, "--natural-foreign", "--natural-primary", *[f"--exclude={e}" for e in excludes])
        size = os.path.getsize(out)
        self.stdout.write(self.style.SUCCESS(f"备份完成: {out} ({size/1024:.1f} KB)"))
