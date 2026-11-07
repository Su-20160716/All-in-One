# -*- coding: utf-8 -*-
"""#68 备份数据到 JSON 文件；#132 备份保留策略（最近 N 份 + 每周一份）"""
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

# 排除 contenttypes / sessions / admin log，只备份业务数据
EXCLUDES = ("contenttypes", "auth.Permission", "sessions", "admin.LogEntry")
# #132：默认保留最近 7 份「逐次备份」+ 每周 1 份（跨周的历史锚点），可用环境变量覆盖
DEFAULT_KEEP = int(os.environ.get("BACKUP_KEEP", "7"))
BACKUP_GLOB = "backup_*.json"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _week_key(path: Path) -> tuple:
    """按文件修改时间取 ISO 周（年, 周），用于「每周保留一份」的判定"""
    return datetime.fromtimestamp(_mtime(path)).isocalendar()[:2]


def prune_backups(directory: Path, keep: int = DEFAULT_KEEP) -> list:
    """#132：删除超出保留策略的备份文件，返回被删除的路径列表。

    规则：按修改时间倒序，前 `keep` 份无条件保留；更老的每 ISO 周只保留最新一份。
    keep <= 0 表示不清理（保留全部），便于临时排障。
    """
    if keep <= 0 or not directory.is_dir():
        return []
    files = sorted(directory.glob(BACKUP_GLOB), key=_mtime, reverse=True)
    if len(files) <= keep:
        return []
    keep_set = set(files[:keep])
    seen_weeks = set()
    for path in files[keep:]:
        week = _week_key(path)
        if week in seen_weeks:
            continue  # 同一周已有更新的备份保留
        seen_weeks.add(week)
        keep_set.add(path)
    removed = []
    for path in files:
        if path in keep_set:
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            # 删除失败（权限/被占用）不影响本次备份结果，留日志提示即可
            pass
    return removed


class Command(BaseCommand):
    help = "备份所有业务数据到 JSON 文件（backup_YYYYMMDD_HHMMSS.json），并按保留策略清理旧备份"

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", type=str, default="", help="输出文件路径")
        parser.add_argument(
            "--keep",
            type=int,
            default=DEFAULT_KEEP,
            help=f"保留最近 N 份备份，另外每周保留 1 份；<=0 表示不清理（默认 {DEFAULT_KEEP}）",
        )
        parser.add_argument(
            "--no-prune",
            action="store_true",
            help="只备份，不执行保留策略清理",
        )

    def handle(self, *args, **options):
        out = options["output"]
        if not out:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = str(settings.BASE_DIR / f"backup_{ts}.json")
        out_path = Path(out).resolve()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CommandError(f"备份目录不可写: {out_path.parent} ({exc})") from exc

        call_command(
            "dumpdata",
            "--indent",
            "2",
            "--output",
            str(out_path),
            "--natural-foreign",
            "--natural-primary",
            *[f"--exclude={e}" for e in EXCLUDES],
        )
        if not out_path.exists():
            raise CommandError(f"备份文件未生成: {out_path}")
        size = out_path.stat().st_size
        self.stdout.write(self.style.SUCCESS(f"备份完成: {out_path} ({size / 1024:.1f} KB)"))

        if options["no_prune"]:
            return
        removed = prune_backups(out_path.parent, keep=options["keep"])
        if removed:
            self.stdout.write(f"按保留策略清理 {len(removed)} 个旧备份（保留最近 {options['keep']} 份 + 每周 1 份）")
            for path in removed:
                self.stdout.write(f"  - {path.name}")
