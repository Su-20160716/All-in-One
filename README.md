# 全能协作平台 All-in-One Platform

> Vue3 + TailwindCSS + Django DRF + Channels 全栈项目 · 9 大模块 · **105 项功能** · 含完整项目文档

一套登录，多个业务模块：**文件管理 / 笔记知识库 / 项目看板 / 站内消息 / 通知中心 / 操作日志 / 统计面板 / 小工具集 / RBAC 后台**。

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
| 前端 | Vue 3（组合式 API）、Vite 5、TailwindCSS 3、Pinia、Vue Router 4、Axios、marked |
| 后端 | Django 5、Django REST Framework、SimpleJWT、Django Channels 4 |
| 数据库 | SQLite（开发默认）/ PostgreSQL（环境变量切换） |
| 实时 | WebSocket（Channels，Redis 可选，默认内存层单机开发） |

## 目录结构

```
web/
├── backend/                  # Django 后端
│   ├── config/               # settings / urls / asgi / wsgi
│   ├── core/                 # 操作日志、通知中心、分页、异常、中间件
│   ├── accounts/             # 用户 / 角色 / RBAC 权限 / JWT
│   ├── files/                # 文件：分片上传、断点续传、秒传、回收站、共享链接
│   ├── notes/                # 笔记：版本历史、标签、分享、全文搜索
│   ├── projects/             # 项目看板：列、卡片拖拽、评论、统计
│   ├── im/                   # 站内消息：单聊 / 群聊 / 未读
│   ├── tools/                # 12 个开发工具接口
│   ├── dashboard/            # 个人 / 全局统计、趋势
│   ├── ws_app/               # WebSocket 统一消费者 + 推送封装
│   ├── smoke_test.py         # 54 项接口冒烟测试（全通过）
│   └── manage.py
├── frontend/                 # Vue3 前端
│   └── src/
│       ├── api/              # axios 封装 + 全模块 API
│       ├── stores/           # Pinia：user / app(通知+WS)
│       ├── router/           # 路由 + 登录守卫
│       ├── components/       # Sidebar / Topbar / Modal
│       ├── views/            # 登录、工作台、文件、笔记、看板、聊天、后台、工具、个人
│       └── utils/            # WebSocket 客户端、格式化
└── docs/                     # 项目文档（见下）
```

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/01-需求与功能清单.md](docs/01-需求与功能清单.md) | 105 项功能逐条清单（编号可追溯） |
| [docs/02-系统架构.md](docs/02-系统架构.md) | 架构图、模块划分、关键设计（RBAC/分片上传/WS） |
| [docs/03-API接口文档.md](docs/03-API接口文档.md) | 全接口列表与方法（按模块） |
| [docs/04-数据库设计.md](docs/04-数据库设计.md) | 全部数据表、字段、关系 |
| [docs/05-部署与运行.md](docs/05-部署与运行.md) | 开发/生产部署、环境变量、Redis/PostgreSQL 切换 |
| [docs/06-UI设计说明.md](docs/06-UI设计说明.md) | 设计系统（色板/字阶/圆角/栅格）与控制台规范 |

## 核心亮点

- **文件**：前端分片（5MB/块）→ 后端按块落盘 → 合并校验 SHA1；断点续传（重复分片幂等）；秒传（同 SHA1 复用存储）；回收站双态（恢复/彻底删除）；图片自动缩略图；文本在线预览；共享链接带权限与过期时间，匿名可访问可下载。
- **权限**：自定义 RBAC —— 权限点(20) → 角色(2 内置) → 用户；内置管理员恒真；`/api/auth/me/permissions/` 供前端按钮级权限。
- **实时**：Channels 统一消费者，JWT 登录后进入个人频道组；通知/聊天/文件/看板事件统一消息协议；前端自动重连 + 30s 心跳。
- **笔记**：每次内容变更自动存版本快照，可回滚任意历史版本；Markdown 双栏编辑/预览；标签、置顶、收藏、公开分享。
- **看板**：原生 HTML5 拖拽跨列移动 + 列内排序；默认三列（待办/进行中/已完成）；成员、评论、活动流、逾期统计。

## 验证结果

- `manage.py check`：无问题
- 迁移 + seed：成功（20 权限点、2 内置角色、admin/admin123）
- 冒烟测试 `smoke_test.py`：**54 项全通过**（覆盖注册登录→文件全链路→笔记→看板→消息→工具→统计→管理→权限拒绝）
- 前端 `npm run build`：通过（见构建输出）
