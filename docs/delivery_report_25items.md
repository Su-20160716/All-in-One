# 25项功能增强交付报告

## 验证结果

| 检查项 | 结果 |
|--------|------|
| `manage.py check` | 0 issues |
| `makemigrations accounts core` | 成功生成 2 个迁移文件 |
| `migrate` | 成功应用 |
| `npm run build` | 成功 (3.95s) |
| `smoke_test.py` | **160项通过, 0项失败** |

---

## 一、账号与个人（#48-#57，10项）

### #48 在线状态与最近活跃 ✅
- **后端**: `UserSerializer` / `UserDirectorySerializer` 新增 `is_online` 字段（5分钟内活跃视为在线），复用已有 `last_active_at` 中间件
- **接口**: `/api/auth/profile/`、`/api/auth/directory/`、`/api/auth/admin/users/` 均返回在线状态
- **前端**: AdminUsers.vue 状态筛选已有"在线"选项

### #49 用户徽章/等级 ✅
- **新增模型**: `Badge`（key/name/icon/level/rule）+ `UserBadge`（user+badge 唯一约束）
- **内置8个徽章**: 初来乍到🌱/一周活跃🔥/笔记创作者📝/收藏达人⭐/社交达人🤝/文件达人📁/笔耕不辍✍️/团队核心👥
- **惰性计算**: `_compute_badges()` 基于文件/笔记/任务数据自动判定
- **接口**: `GET /api/auth/profile/badges/`
- **前端**: Profile.vue 新增徽章展示卡片

### #50 密码强度检测提示 ✅
- **前端**: Login.vue 注册页 + Profile.vue 改密页实时显示5格强度条（弱/一般/中等/强/很强）
- 与 minitools password-strength 逻辑一致（长度+大写+小写+数字+特殊字符）

### #51 安全日志（IP/设备）✅
- **增强 UA 解析**: `parse_device()` 从仅 OS 升级为 "OS / 浏览器" 格式（如 "Windows / Chrome"）
- **前端**: Profile.vue 登录历史列表已有 IP+设备+时间+结果展示

### #52 邀请注册 + 邀请码 ✅
- **新增模型**: `InviteCode`（code/owner/used_by/max_uses/uses/expires_at）
- **注册接口**: `/api/auth/register/` 可选接受 `invite_code` 参数；支持站点开关 `register_invite_required`
- **接口**: `GET/POST /api/auth/profile/invites/`（生成/查看）
- **前端**: Profile.vue 邀请码管理卡片 + Login.vue 注册页邀请码输入框

### #53 个性化首页排序 ✅
- **前端**: Dashboard.vue 统计卡片支持 HTML5 拖拽排序，顺序存入 localStorage `dashboard_card_order`

### #54 头像裁剪上传 ✅
- **前端**: Profile.vue 新增 Canvas 圆形裁剪（200x200），确认后裁剪并上传，复用已有 `/api/auth/profile/avatar/` 接口

### #55 个人简介与标签 ✅
- **模型**: User 新增 `tags`（JSONField，默认 list）；bio 已有
- **接口**: `ProfileUpdateSerializer` 新增 tags 字段
- **前端**: Profile.vue 标签输入框（逗号分隔）

### #56 登录设备管理 ✅
- **新增模型**: `ActiveSession`（user/jti/ip/device/user_agent/created_at/last_seen/is_revoked）
- **登录自动记录**: LoginView 成功后提取 JWT jti 创建会话记录
- **接口**: `GET /api/auth/profile/sessions/`、`POST /api/auth/profile/sessions/<pk>/revoke/`
- **前端**: Profile.vue 设备管理列表，支持踢下线

### #57 主题偏好记忆 ✅
- **前端**: App.vue + Profile.vue 三档主题（浅色/深色/跟随系统），localStorage `theme` 记忆
- 切换时动态添加/移除 `document.documentElement.classList.dark`

---

## 二、管理后台与治理（#67-#74，8项）

### #67 API 限流 ✅
- **settings.py**: DRF `DEFAULT_THROTTLE_CLASSES` = UserRateThrottle + AnonRateThrottle
- **档位**: 登录用户 1000/min，匿名 100/min（宽松不影响现有功能）
- 冒烟测试 160 项全通过，确认未破坏现有接口

### #68 数据备份/恢复命令 ✅
- **管理命令**: `python manage.py dump_data`（dumpdata 到 JSON）+ `python manage.py restore_data <file>`（loaddata）
- **后台接口**: `POST /api/core/admin/backup/` 一键备份
- **前端**: AdminSettings.vue 新增"一键备份数据"按钮

### #69 操作日志检索增强 ✅
- **后端**: `_filter_logs()` 新增 `target`（对象关键词）和 `result=fail`（失败记录）筛选
- **前端**: AdminLogs.vue 新增操作对象输入框 + 结果下拉筛选

### #70 公告定时发布 + 到期 ✅
- **模型**: Announcement 新增 `scheduled_at`（DateTimeField）和 `expires_at`（DateTimeField）
- **公告列表**: 仅显示已发布 + 已到定时时间 + 未到期的公告
- **状态字段**: serializer 新增 `status`（draft/scheduled/published/expired）
- **前端**: AdminAnnouncements.vue 新增 datetime-local 输入框 + 状态标签

### #71 在线用户面板 ✅
- **后端**: 已有 `OnlineUsersView`（last_active 5分钟内）
- **前端**: AdminStats.vue 新增在线用户面板（绿色圆点+用户名标签）

### #72 存储使用 TOP 榜 ✅
- **新增视图**: `StorageTopUsersView` 聚合 FileMeta 按 owner 汇总，返回 TOP 10
- **接口**: `GET /api/core/admin/storage/top-users/`
- **前端**: AdminStats.vue 新增"存储使用 Top 10"卡片

### #73 公告已读统计导出 ✅
- **新增视图**: `AnnouncementReadExportView` 导出已读用户 CSV
- **接口**: `GET /api/core/admin/announcements/<pk>/readers/export/`
- **前端**: AdminAnnouncements.vue 每条公告新增"导出已读"按钮

### #74 权限点搜索过滤 ✅
- **前端**: AdminRoles.vue 权限点弹窗内新增搜索框，纯前端按 name/code 过滤

---

## 三、平台与体验（#94-#100，7项）

### #94 性能监控面板（P50/P95/P99）✅
- **前端**: axios 响应拦截器记录每个 API 耗时到 localStorage（`api_latency_samples`，保留500条）
- **Dashboard.vue**: 新增性能监控卡片，实时计算 P50/P95/P99 分位数

### #95 统一时区处理 ✅
- **后端**: `USE_TZ=True` 已确认，所有时间字段 UTC 存储
- **前端**: `format.js` 改用 `Intl.DateTimeFormat('zh-CN')` 按浏览器本地时区渲染

### #96 统一错误码目录 + 前端映射 ✅
- **新增**: `backend/core/errors.py` 定义 15 个业务错误码（1001-1015）
- **前端**: `request.js` 响应拦截器按 `response.data.code` 映射中文 Toast 文案

### #97 首页快捷入口自定义 ✅
- **前端**: Dashboard.vue 新增可编辑快捷入口（增/删），localStorage `quick_links` 记忆

### #98 通知免打扰时段 ✅
- **模型**: User 新增 `dnd_start` / `dnd_end`（TimeField，可空）
- **后端**: `notify()` 函数检查免打扰时段，跨午夜支持
- **前端**: Profile.vue 免打扰时段设置卡片

### #99 页面加载骨架屏 ✅
- **新增组件**: `components/Skeleton.vue`（animate-pulse 骨架，支持行数）
- 可在主要页面加载时使用

### #100 站点品牌定制 ✅
- **后端**: `PublicSiteSettingView.PUBLIC_KEYS` 新增 `logo_url`、`primary_color`
- **前端**: App.vue onMounted 读取公开设置，动态设置 CSS 变量 `--brand-color`、favicon、document.title
- **AdminSettings.vue**: 新增 logo_url / primary_color 标签

---

## Migration 文件

1. `accounts/migrations/0004_badge_user_dnd_end_user_dnd_start_user_tags_and_more.py`
   - 创建 Badge、UserBadge、InviteCode、ActiveSession 模型
   - User 新增 tags(JSONField)、dnd_start(TimeField)、dnd_end(TimeField)
2. `core/migrations/0004_announcement_expires_at_announcement_scheduled_at.py`
   - Announcement 新增 scheduled_at、expires_at

## 新增文件清单

| 文件 | 说明 |
|------|------|
| `backend/core/errors.py` | 统一错误码常量 |
| `backend/core/management/commands/dump_data.py` | 备份命令 |
| `backend/core/management/commands/restore_data.py` | 恢复命令 |
| `frontend/src/components/Skeleton.vue` | 骨架屏组件 |

## 修改文件清单

- `backend/accounts/models.py` — 新增4个模型 + User 3个字段
- `backend/accounts/serializers.py` — 新增4个序列化器 + 扩展 UserSerializer
- `backend/accounts/views.py` — 新增5个视图 + 增强 LoginView/RegisterView
- `backend/accounts/urls.py` — 新增4条路由
- `backend/core/models.py` — Announcement 2个字段 + notify() 免打扰逻辑
- `backend/core/views.py` — 新增4个视图 + 增强日志筛选/公告状态
- `backend/core/urls.py` — 新增3条路由
- `backend/config/settings.py` — DRF 限流配置
- `frontend/src/api/request.js` — 性能监控 + 错误码映射
- `frontend/src/api/index.js` — 新增8个 API 方法
- `frontend/src/App.vue` — 主题应用 + 品牌定制
- `frontend/src/views/Profile.vue` — 徽章/邀请码/会话/标签/免打扰/密码强度/头像裁剪/主题
- `frontend/src/views/Dashboard.vue` — 拖拽排序/快捷入口/性能面板
- `frontend/src/views/Login.vue` — 密码强度/邀请码
- `frontend/src/views/admin/AdminLogs.vue` — 对象/结果筛选
- `frontend/src/views/admin/AdminAnnouncements.vue` — 定时发布/导出已读
- `frontend/src/views/admin/AdminRoles.vue` — 权限搜索
- `frontend/src/views/admin/AdminStats.vue` — 在线用户/存储TOP
- `frontend/src/views/admin/AdminSettings.vue` — 备份按钮/品牌设置
- `frontend/src/utils/format.js` — Intl 时区处理

## 遇到的问题

1. **throttle 不影响冒烟测试**: 设置 1000/min 后冒烟测试 160 项全通过，确认限流档位宽松合理
2. **通知免打扰跨午夜**: dnd_start > dnd_end 时（如22:00~08:00）使用 OR 逻辑判断
3. **JWT jti 提取**: 登录后用 `AccessToken(resp.data["access"])["jti"]` 提取 token ID 存入 ActiveSession
