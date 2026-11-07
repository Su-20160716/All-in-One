#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 数据恢复（清单 #138 / #133）
# 流程：结构校验（restore_data --validate-only）→ 交互确认 → 恢复。
# restore_data 会在写库前自动 dump_data 生成恢复前快照，坏数据可回退。
#
# 用法：
#   scripts/restore.sh backend/backup_20261105_120000.json
#   scripts/restore.sh backup.json -y               # 无人值守（跳过确认）
#   scripts/restore.sh backup.json --no-snapshot    # 不要恢复前快照（危险）
#   PYTHON=/usr/bin/python3 scripts/restore.sh ...
#
# 退出码：0 成功；1 用户取消/恢复失败；2 参数或环境问题。
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"

usage() {
  cat <<'USAGE'
用法: scripts/restore.sh <backup.json> [--no-snapshot] [-y|--yes]

  -y, --yes        跳过交互确认（CI / 无人值守）
      --no-snapshot 跳过恢复前自动快照（确认无需回退时才用）
  -h, --help       显示本帮助
USAGE
}

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

FILE=""
CONFIRMED=0
EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -y|--yes)
      CONFIRMED=1
      shift
      ;;
    --no-snapshot)
      EXTRA+=("--no-snapshot")
      shift
      ;;
    -*)
      echo "[restore] 未知参数: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      FILE="$1"
      shift
      ;;
  esac
done

if [ -z "$FILE" ]; then
  usage >&2
  exit 2
fi
if [ ! -f "$FILE" ]; then
  echo "[restore] 备份文件不存在: $FILE" >&2
  exit 2
fi
# 统一成绝对路径（restore_data 会在 backend 目录下执行）
FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"

PY="$(pick_python)"
if [ -z "$PY" ]; then
  echo "[restore] 未找到 python，请用 PYTHON=/path/to/python 指定解释器" >&2
  exit 2
fi

echo "[restore] python: $PY"
echo "[restore] 备份文件: $FILE"
cd "$BACKEND"

# ① 恢复前校验：解析 JSON、统计对象数、确认 app 都在当前代码里
"$PY" manage.py restore_data "$FILE" --validate-only

# ② 二次确认：恢复会覆盖现有业务数据
if [ "$CONFIRMED" -ne 1 ]; then
  if [ -t 0 ]; then
    printf '[restore] 即将覆盖当前数据，输入 yes 继续: '
    read -r answer
    if [ "$answer" != "yes" ]; then
      echo "[restore] 已取消"
      exit 1
    fi
  else
    echo "[restore] 非交互环境，请加 -y/--yes 明确确认" >&2
    exit 2
  fi
fi

# ③ 恢复（restore_data 内部先做恢复前快照，再在事务里 loaddata）
if [ ${#EXTRA[@]} -gt 0 ]; then
  "$PY" manage.py restore_data "$FILE" "${EXTRA[@]}"
else
  "$PY" manage.py restore_data "$FILE"
fi

echo "[restore] 完成"
