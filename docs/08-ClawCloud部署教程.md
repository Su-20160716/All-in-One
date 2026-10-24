# 08 · 国内友好免费部署（Cloudflare Pages + ClawCloud Run）

> 适合 Render 访问不了的网络环境。前端照旧 Cloudflare Pages（免费），
> 后端改用 **ClawCloud Run**：新加坡节点回国网络优化，GitHub 账号 ≥180 天每月白送 $5 额度，
> 免信用卡，**支持挂持久卷——SQLite 数据和上传文件都能活过重启**。
> 架构：CF Pages（前端）→ ClawCloud Run 容器（Django+Daphne）→ 持久卷（SQLite + media）

## 0. 前提条件

- **GitHub 账号注册 ≥ 180 天**（ClawCloud 免费额度硬性条件）
- 代码已推上 GitHub（本仓库）
- 管理员账号密码：容器启动时 `seed` 自动创建，**用环境变量覆盖默认的 admin/admin123**

改动清单（均已就位）：
- `backend/Dockerfile` —— 后端镜像（migrate + seed + daphne，构建期 collectstatic）
- `backend/.dockerignore` —— 排除 `.env`/数据库/上传文件，密钥不进镜像
- `.github/workflows/build-backend.yml` —— 推代码自动构建镜像 → GHCR
- `config/settings.py` —— `DATA_DIR` 环境变量：SQLite 和 media 整体搬进持久卷
- `accounts/management/commands/seed.py` —— 管理员账号密码支持 `SEED_ADMIN_*` 环境变量

## 1. 推代码，等 GitHub Actions 构建镜像（约 5 分钟）

```bash
git add -A && git commit -m "ClawCloud 容器部署配置" && git push
```

1. 打开 GitHub 仓库页 → **Actions** 标签 → 看到 `Build backend image` 在跑 → 等 3-5 分钟变绿勾
2. 构建成功后：仓库页右侧 **Packages**（或个人主页 Packages）→ 点开 `coop-backend` →
   **Package settings → Change visibility → Public**（不设 Public ClawCloud 拉不到镜像）

## 2. 注册 ClawCloud Run（2 分钟）

1. 打开 **run.claw.cloud** → `Get started for free` → **GitHub 登录**（≥180 天老号自动领每月 $5）
2. 首次进入会让你选区域：**选 Singapore（新加坡）**——回国网络优化最好；
   （日本节点有证书申请故障的黑历史，别选）

## 3. 创建后端应用（10 分钟）

控制台 → **App Launchpad** → **Create App**，按下表填：

### Basic
| 项 | 值 |
|---|---|
| Application Name | `coop-backend` |
| Image | Private（或 Public）→ Image Name 填 `ghcr.io/你的GitHub用户名/coop-backend:latest` |

### Usage（资源配置，控制在 $5/月 内）
| 项 | 值 |
|---|---|
| Replicas | Fixed 1 |
| CPU | 0.5 |
| Memory | 512M |

### Network（网络）
| 项 | 值 |
|---|---|
| Container Port | `8000` |
| Enable Internet Access | ✅ 打开 |

### Environment Variables（环境变量，逐条添加）
| 变量 | 值 | 说明 |
|---|---|---|
| `DJANGO_DEBUG` | `0` | 生产必须 |
| `DJANGO_SECRET_KEY` | 随便一长串乱码 | 自己编 50 位以上 |
| `DJANGO_ALLOWED_HOSTS` | `*` | ClawCloud 域名不定，用 * |
| `DATA_DIR` | `/app/data` | **关键**：SQLite 和 media 落进持久卷（也认别名 `DJANGO_DATA_DIR`，两者取其一） |
| `SERVE_MEDIA` | `1` | **关键**：`DEBUG=0` 时 Django 默认不挂 `/media/` 路由，这里没 Nginx，必须开这个开关，否则上传成功但打开图片 404 |
| `SEED_ADMIN_USERNAME` | 你的管理员名 | 不设则 admin |
| `SEED_ADMIN_PASSWORD` | **强密码** | 不设则 admin123，公网上等于裸奔 |
| `CORS_ALLOWED_ORIGINS` | `https://xxx.pages.dev` | 前端部署完回填 |
| `CSRF_TRUSTED_ORIGINS` | `https://xxx.pages.dev` | 同上 |
| `LLM_API_KEY` | 可选 | 不填则 AI 降级本地实现 |

### Local Storage（持久卷，数据不丢的关键）
| 项 | 值 |
|---|---|
| Capacity | `1` G |
| Mount Path | `/app/data` |

> **`DATA_DIR` 到底做了什么**（`config/settings.py`）：
> - 引擎是 SQLite 时：`DATABASES.default.NAME = $DATA_DIR/db.sqlite3`
> - 无论什么引擎：`MEDIA_ROOT = $DATA_DIR/media`（上传的文件、头像、缩略图都在这）
> - 目录不存在会自动 `mkdir`
> - 一旦填了 `DATABASE_URL` 接 Postgres，**只挪 MEDIA_ROOT，不会把 PG 的库名覆盖成 sqlite 路径**（这条有专门的判断，别删）
>
> 所以持久卷必须同时容纳 `db.sqlite3` 和 `media/`——挂 `1G` 起步，文件多了再扩。

### 媒体文件为什么需要 `SERVE_MEDIA=1`

`config/urls.py` 里的 `/media/` 路由被 `DEBUG` 门控：开发时 Django 自己吐文件，生产（`DEBUG=0`）默认不挂。
Render/docker-compose 场景前面有 Nginx 反代 `/media/`，所以没事；**ClawCloud 只跑后端一个容器，没有 Nginx**，
不开 `SERVE_MEDIA` 就会「上传成功、数据库有记录、点开图片 404」。

| 部署形态 | `/media/` 谁服务 | 需要 SERVE_MEDIA |
|---|---|---|
| 本地开发（DEBUG=1） | Django 自带 static 视图 | 不需要 |
| docker-compose（前端 Nginx 反代） | Nginx | 保持 0 |
| **ClawCloud Run 单容器** | Django（本文场景） | **必须 1** |

### Advanced（如有）
无额外 Command（Dockerfile 里已写好启动流程）。

最后点 **Deploy Application** → 等 Pod 状态变 `Active`（首次拉镜像 + 迁移约 2-3 分钟）。

## 4. 拿后端地址，部署前端

1. 应用详情 **Network** 里复制 **Public Address**（形如 `https://coop-backend-xxx.run.app`），浏览器访问 `它/api/core/health/` 验证
2. 前端照旧走 **Cloudflare Pages**（上一份教程第 3 步），唯一区别：
   `VITE_API_BASE` 填这里的后端 Public Address
3. 回 ClawCloud 更新环境变量：`CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` 填前端 pages.dev 地址 → 保存自动重启

## 5. 验收清单

- [ ] `xxx.pages.dev` 登录页正常
- [ ] 用 SEED_ADMIN_* 设的管理员登录
- [ ] 双浏览器互发 IM 消息实时到达（WS 通）
- [ ] **上传一个文件 → 在 ClawCloud 里 Restart 容器 → 文件还在**（持久卷生效，这是比 Render 强的地方）
- [ ] 深层页面刷新不 404

## 6. 日常更新

改完代码 `git push` → GitHub Actions 自动构建新镜像（约 3 分钟）→ ClawCloud 里对应用点 **Restart/Redeploy**（拉 latest）。
数据在持久卷里，重启不丢。

## 7. 已知限制

- 免费额度 $5/月：0.5C/512M 约合 $2-3/月 + 1G 卷 + 流量，个人使用够；**流量超 10G/月按 $0.05/G 计费**（上传下载大文件注意）
- 免费服务无 SLA，官方都建议做数据备份——定期在 ClawCloud 存储页下载 `db.sqlite3` 备份，或哪天升级 DATABASE_URL 接 Supabase
- Japan 区域证书申请有故障，选 Singapore
