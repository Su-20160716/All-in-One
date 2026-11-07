# -*- coding: utf-8 -*-
"""#68 从 JSON 文件恢复数据；#133 恢复前校验 + 自动生成恢复前快照"""
import json
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def inspect_backup(path: Path) -> dict:
    """#133：解析并校验 dumpdata 生成的 JSON，返回统计信息。

    校验项：
    - 顶层必须是对象数组（dumpdata 格式），且不能为空（空文件多为写入中断）
    - 每条记录必须含 model（`app_label.ModelName`）与 fields
    - app_label 必须是本项目已注册的 app（模型漂移/跨项目文件直接拒绝）
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise CommandError(f"备份文件无法解析为 JSON: {path} ({exc})") from exc
    if not isinstance(data, list):
        raise CommandError("备份文件不是 dumpdata 生成的 JSON 数组，拒绝恢复")
    if not data:
        raise CommandError("备份文件为空（可能写入中断），拒绝恢复")

    known_apps = {cfg.label for cfg in apps.get_app_configs()}
    model_counts: dict = {}
    for index, obj in enumerate(data):
        if not isinstance(obj, dict) or not obj.get("model") or "fields" not in obj:
            raise CommandError(f"第 {index + 1} 条记录结构非法（缺少 model/fields），拒绝恢复")
        label = str(obj["model"])
        if "." not in label:
            raise CommandError(f"第 {index + 1} 条记录的 model={label!r} 不是 app.Model 形式，拒绝恢复")
        model_counts[label] = model_counts.get(label, 0) + 1

    model_apps = sorted({label.split(".", 1)[0] for label in model_counts})
    unknown = [label for label in model_apps if label not in known_apps]
    if unknown:
        raise CommandError(
            "备份文件包含当前项目不存在的 app："
            f"{', '.join(unknown)}（模型漂移，请先部署对应版本或手工剔除）"
        )
    return {
        "objects": len(data),
        "models": len(model_counts),
        "apps": model_apps,
        "top_models": sorted(model_counts.items(), key=lambda kv: kv[1], reverse=True)[:10],
    }


class Command(BaseCommand):
    help = "从备份 JSON 文件恢复数据（恢复前自动校验结构并生成恢复前快照）"

    def add_arguments(self, parser):
        parser.add_argument("input", type=str, help="备份文件路径（dump_data 生成的 JSON）")
        parser.add_argument(
            "--no-snapshot",
            action="store_true",
            help="跳过恢复前的自动快照（仅在确认无需回退时使用）",
        )
        parser.add_argument(
            "--validate-only",
            action="store_true",
            help="只校验备份文件结构与统计信息，不写库",
        )

    def handle(self, *args, **options):
        path = Path(options["input"]).resolve()
        if not path.exists():
            raise CommandError(f"文件不存在: {path}")

        info = inspect_backup(path)
        self.stdout.write(
            f"校验通过: {info['objects']} 条对象 / {info['models']} 个模型 / app: {', '.join(info['apps'])}"
        )
        for label, count in info["top_models"]:
            self.stdout.write(f"  - {label}: {count}")
        if options["validate_only"]:
            self.stdout.write(self.style.SUCCESS("仅校验模式，未写库"))
            return

        # #133：恢复前快照——坏数据也能一键回到恢复前状态
        snapshot = None
        if not options["no_snapshot"]:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot = Path(settings.BASE_DIR) / f"backup_pre_restore_{ts}.json"
            try:
                call_command("dump_data", output=str(snapshot), no_prune=True)
            except Exception as exc:  # 快照失败必须中止，避免不可回退的恢复
                raise CommandError(f"恢复前快照生成失败，已中止恢复: {exc}") from exc
            self.stdout.write(f"恢复前快照: {snapshot}")

        try:
            with transaction.atomic():
                call_command("loaddata", str(path))
        except Exception as exc:
            rollback_hint = f"，可用快照回退: {snapshot}" if snapshot else ""
            raise CommandError(f"恢复失败，事务已回滚{rollback_hint}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"数据已从 {path} 恢复（{info['objects']} 条对象）"))
