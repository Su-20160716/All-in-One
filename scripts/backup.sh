#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 数据备份（清单 #138）
# 调用 core 的 dump_data 管理命令：dumpdata 全量业务数据 → JSON，
# 并按保留策略（默认最近 7 份 + 每周 1 份）清理旧文件。
#
# 用法：
#   scripts/backup.sh                              # 备份到 backend/backup_<时间戳>.json
#   scripts/backup.sh -o /data/backups/manual.json # 指定输出文件
#   scripts/backup.sh --keep 14                    # 保留 14 份 + 每周 1 份
#   scripts/backup.sh --no-prune                   # 只备份不清理
#   PYTHON=/usr/bin/python3 scripts/backup.sh      # 指定解释器（默认自动探测 venv）
#
# 说明：脚本在 Git Bash / WSL / Linux 下均可运行；退出码透传给 CI/运维调用方。
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"

trap 'echo "[backup] 备份失败（退出码 $?）" >&2' ERR

pick_python() {
  if [ -n "${PYTHON:-}" ]; then
    printf '%s' "$PYTHON"
    return 0
  fi
  local candidate
  for candidate in "$BACKEND/venv/Scripts/python.exe" "$BACKEND/venv/bin/python"; do
    if [ -x "$candidate" ]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  command -v python3 2>/dev/null || command -v python 2>/dev/null || true
}

PY="$(pick_python)"
if [ -z "$PY" ]; then
  echo "[backup] 未找到 python，请用 PYTHON=/path/to/python 指定解释器" >&2
  exit 2
fi

echo "[backup] python: $PY"
echo "[backup] 工作目录: $BACKEND"
cd "$BACKEND"

# dump_data 负责任务本身与保留策略；额外参数（-o/--keep/--no-prune）原样透传
"$PY" manage.py dump_data "$@"

echo "[backup] 完成"
