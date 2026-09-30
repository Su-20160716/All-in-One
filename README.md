# 全能协作平台 All-in-One Platform

> Vue3 + TailwindCSS + Django DRF + Channels 全栈项目 · 10 大模块 · **主平台 177 项 + 学习中心 100 项 + 平台能力 11 项 + 办公三域 501 接口 + 代码工坊 100 项** · 含完整项目文档

一套登录，多个业务模块：**文件管理 / 笔记知识库 / 项目看板 / 站内消息 / 通知中心 / 操作日志 / 统计面板 / 小工具集 / RBAC 后台 / 代码工坊**。

> **模块记账口径**：主平台九个模块为 v2 基线；v3 学习中心、v4 平台横切能力、v5 办公三域、v6 代码工坊各自**独立记账**，不并入主平台总数，便于横向对比版本体量。

## 快速开始（开发环境，Windows 已验证）

### 1. 启动后端（Django + DRF + Channels）

```powershell
cd backend
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python manage.py migrate
.\venv\Scripts\python manage.py seed          # 初始化角色/权限/管理员
.\venv\Scripts\python manage.py runserver 8000
```

默认管理员：`admin / admin123`。

### 2. 启动前端（Vue3 + Vite + Tailwind）

```powershell
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 （Vite 已代理 `/api`、`/media`、`/ws` 到 8000）。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3（组合式 API）、Vite 5、TailwindCSS 3、Pinia、Vue Router 4、Axios、marked、ECharts、**CodeMirror 6**（代码工坊编辑器内核） |
| 后端 | Django 5、Django REST Framework、SimpleJWT、Django Channels 4 |
| 数据库 | SQLite（开发默认）/ PostgreSQL（环境变量切换） |
| 实时 | WebSocket（Channels，Redis 可选，默认内存层单机开发） |
| 代码执行 | 进程级沙箱（`code/runtime.py`）：`subprocess` 无 shell 调用 + 临时目录 + 环境变量白名单 + 超时强杀；POSIX 下 `resource.setrlimit` 限内存与 CPU，Windows 自动降级 |

## 目录结构

```
web/
├── backend/                  # Django 后端
│   ├── config/               # settings / urls / asgi / wsgi
│   ├── core/                 # 操作日志、通知中心、分页、异常、中间件、search、scoping（行级权限收口）
│   ├── accounts/             # 用户 / 角色 / RBAC 权限 / JWT / 部门 / 租户
│   ├── files/                # 文件：分片上传、断点续传、秒传、回收站、共享链接
│   ├── notes/                # 笔记：版本历史、标签、分享、全文搜索、双链
│   ├── projects/             # 项目看板：列、卡片拖拽、评论、统计
│   ├── im/                   # 站内消息：单聊 / 群聊 / 未读
│   ├── dashboard/            # 个人 / 全局统计、趋势
│   ├── tools/                # 12 个开发工具接口
│   ├── devtools/             # v5 开发者工具箱（27 子系统 · 154 接口）
│   ├── dataintel/            # v5 数据智能中心（20 子系统 · 114 接口）
│   ├── officesuite/          # v5 办公套件（29 子系统 · 233 接口，5 家族）
│   ├── learning/             # v3 学习中心
│   ├── assistant/            # v4 AI 助手（对话 / 摘要 / 出题 / 批改）
│   ├── code/                 # v6 代码工坊 ★ 本次新增
│   │   ├── models.py         # 15 个模型（工作区/文件/版本/片段/执行/协作/判题/评论/分享 + 每日一题/成就/错题/路径）
│   │   ├── runtime.py        # 代码执行沙箱 + 静态分析（指标/大纲/复杂度/流程图）
│   │   ├── views_core.py     # 工作区/文件/版本/执行/判题/片段/导出 + 判题核心 run_judge()
│   │   ├── views_ai.py       # 静态分析 8 + AI 辅助 15 + 评论/协作/分享
│   │   ├── views_eng.py      # L4 工程化：blame / TODO 聚合 / diff / 洞察 / 贡献者
│   │   ├── views_learn.py    # L5 竞技教学：每日一题 / 成就 / 错题本 / 学习路径 / 竞技场
│   │   └── urls.py           # SUBSYSTEMS + VIEWS 显式映射，结尾 `_EXPECTED = 104` 契约断言
│   ├── ws_app/               # WebSocket 统一消费者 + 推送封装
│   ├── smoke_test.py         # v2 基线冒烟测试
│   └── manage.py
├── frontend/                 # Vue3 前端
│   └── src/
│       ├── api/              # axios 封装 + 全模块 API
│       ├── stores/           # Pinia：user / app(通知+WS)
│       ├── router/           # 路由 + 登录守卫
│       ├── components/       # Sidebar / Topbar / Modal
│       ├── views/            # 登录、工作台、文件、笔记、看板、聊天、后台、工具、个人
│       │   └── code/         # v6 代码工坊：CodeForge / LearnCenter / SharedCode ★ 本次新增
│       └── utils/            # WebSocket 客户端、格式化
└── docs/                     # 项目文档（见下）
```

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/01-需求与功能清单.md](docs/01-需求与功能清单.md) | 功能逐条清单（编号可追溯） |
| [docs/02-系统架构.md](docs/02-系统架构.md) | 架构图、模块划分、关键设计（RBAC/分片上传/WS） |
| [docs/03-API接口文档.md](docs/03-API接口文档.md) | 全接口列表与方法（按模块） |
| [docs/04-数据库设计.md](docs/04-数据库设计.md) | 全部数据表、字段、关系 |
| [docs/05-部署与运行.md](docs/05-部署与运行.md) | 开发/生产部署、环境变量、Redis/PostgreSQL 切换 |
| [docs/06-UI设计说明.md](docs/06-UI设计说明.md) | 设计系统（色板/字阶/圆角/栅格）与控制台规范 |
| [docs/07-免费部署指南.md](docs/07-免费部署指南.md) | Cloudflare Pages + Render + Neon 零成本上线方案 |
| [docs/08-ClawCloud部署教程.md](docs/08-ClawCloud部署教程.md) | ClawCloud 容器化部署步骤 |
| [FEATURES.md](FEATURES.md) | **功能总账**（v2→v6 逐版本演进，含接口/表/页面全量清点） |

## 核心亮点

- **代码工坊（v6）**：15 张表 / **104 个登录接口 + 2 个公开接口** / 3 个前端页面。CodeMirror 6 编辑器（主题、缩进、字体、快捷键、自动换行、括号配对、行号、vim 键位**全部热切换**，语言包按需异步加载）；多语言安全执行沙箱 + REPL；版本快照/diff/回滚；多人协作行评论；只用例判题与排行榜；AI 生成/解释/找 Bug/重构/翻译/注释/优化/单测/摘要（**无密钥自动本地降级**）；TODO 聚合、代码归属（blame）、并排 diff、工程洞察；每日一题、成就徽章、错题本、学习路径、竞技场。
- **文件**：前端分片（5MB/块）→ 后端按块落盘 → 合并校验 SHA1；断点续传（重复分片幂等）；秒传（同 SHA1 复用存储）；回收站双态（恢复/彻底删除）；图片自动缩略图；文本在线预览；共享链接带权限与过期时间，匿名可访问可下载。
- **权限**：自定义 RBAC —— 权限点 → 角色 → 用户；内置管理员恒真；`/api/auth/me/permissions/` 供前端按钮级权限。**行级数据权限统一收口在 `core/scoping.py`**（`self` / `dept` / `dept_and_sub` / `all`），业务模型不加冗余字段。
- **实时**：Channels 统一消费者，JWT 登录后进入个人频道组；通知/聊天/文件/看板/协作事件统一消息协议；前端建连前用 `ensureFreshToken()` 保证 token 新鲜，**认证失败（4001）与网络断开区别处理**，避免重连死循环。
- **笔记**：每次内容变更自动存版本快照，可回滚任意历史版本；Markdown 双栏编辑/预览；标签、置顶、收藏、公开分享、`[[双链]]`。
- **看板**：原生 HTML5 拖拽跨列移动 + 列内排序；默认三列（待办/进行中/已完成）；成员、评论、活动流、逾期统计。
- **降级原则**：任何外部依赖（LibreOffice / LLM / 代码运行时）缺失都**不返回 500**，而是返回结构化错误码（`RUNTIME_NOT_FOUND` / `LIBREOFFICE_NOT_FOUND`）或走本地实现，前端置灰而非崩溃。

## 验证结果

- `manage.py check`：**System check identified no issues (0 silenced)**
- 后端模块 AST 解析：**10 个源文件全部 OK**
- 路由契约：`code` 模块 `urlpatterns` = **104**（断言 `_EXPECTED = 104` 通过）、`public_urlpatterns` = **2**
- 前端 `vite build`：**成功**（`CodeForge` 65.58 kB / gzip 19.78 kB，`LearnCenter` 26.60 kB / gzip 8.58 kB，CodeMirror 独立 chunk 426.87 kB / gzip 138.87 kB）
- 冒烟测试三套串行（v2 基线 160 项 / v3 学习中心 80 项 / v4 扩展 78 项）+ v5 套件（537 项）+ v6 code 套件 —— 改后端后必须**串行**跑，并行会撞 SQLite `database is locked`

