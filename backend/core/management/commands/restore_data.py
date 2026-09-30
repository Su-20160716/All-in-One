# -*- coding: utf-8 -*-
"""#68 从 JSON 文件恢复数据"""
import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "从备份 JSON 文件恢复数据"

    def add_arguments(self, parser):
        parser.add_argument("input", type=str, help="备份文件路径（dump_data 生成的 JSON）")

    def handle(self, *args, **options):
        path = options["input"]
        if not os.path.exists(path):
            raise CommandError(f"文件不存在: {path}")
        call_command("loaddata", path)
        self.stdout.write(self.style.SUCCESS(f"数据已从 {path} 恢复"))
