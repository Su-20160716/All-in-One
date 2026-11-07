.PHONY: help dev build check smoke lint fmt smoke-all clean backup restore openapi

# 全能协作平台 —— 常用命令封装（S3-B1/D8）
# make help 查看全部；CI 只跑 check + smoke-all + fe-build（见 .github/workflows/ci.yml）

help: ## 显示本帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ---------- 开发 ----------
dev: ## 前后端同时起（两个后台进程，Ctrl-C 全停）
	$(MAKE) -j2 be-dev fe-dev

be-dev: ## 后端开发服务器（8000）
	cd backend && PYTHONPATH=backend/venv/Lib/site-packages \
		python manage.py runserver 8000

fe-dev: ## 前端开发服务器（5173）
	cd frontend && npm run dev

# ---------- 质量门禁 ----------
check: ## Django system check
	cd backend && python manage.py check

lint: ## ruff 静态检查（后端）
	ruff check backend/

fmt: ## ruff 自动修复 + 格式化（后端）
	ruff check --fix backend/
	ruff format backend/

smoke: ## 冒烟全集（必须串行——并行撞 SQLite 锁）
	cd backend && \
	python smoke_test.py && \
	python extensions_smoke_test.py && \
	python learning_smoke_test.py && \
	python suite_smoke_test.py && \
	python minitools_smoke.py

smoke-all: smoke ## smoke 别名

# ---------- 构建 ----------
fe-build: ## 前端生产构建
	cd frontend && npm run build

build: fe-build ## 全量构建（当前仅前端需要构建步骤）

# ---------- 数据备份 / 恢复 / 契约 ----------
backup: ## 备份业务数据到 backend/backup_*.json（保留 7 份 + 每周 1 份）
	bash scripts/backup.sh

restore: ## 从备份恢复：make restore F=backend/backup_xxx.json（自动校验 + 恢复前快照）
	@if [ -z "$(F)" ]; then echo "用法: make restore F=backend/backup_YYYYMMDD_HHMMSS.json"; exit 2; fi
	bash scripts/restore.sh "$(abspath $(F))"

openapi: ## 导出 OpenAPI schema 到 docs/openapi.yaml（并做规范校验）
	cd backend && python manage.py spectacular --file ../docs/openapi.yaml --validate

docker-up: ## 本地容器一键起（compose）
	docker compose up -d --build

docker-down: ## 停掉并删容器
	docker compose down

# ---------- 清理 ----------
clean: ## 清理构建产物（不动 venv/node_modules）
	rm -rf frontend/dist backend/staticfiles
	find . -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
