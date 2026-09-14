# 03 API 接口文档

> 统一前缀 `/api`；认证：`Authorization: Bearer <access>`；错误结构 `{code, message, detail}`；分页参数 `?page=1&page_size=20`（上限 100）。

## 认证与账号 `/api/auth`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | /auth/register/ | 公开 | 注册，返回 access/refresh/user |
| POST | /auth/login/ | 公开 | 登录（SimpleJWT TokenObtainPair） |
| POST | /auth/refresh/ | 公开 | 刷新 token |
| POST | /auth/verify/ | 公开 | 校验 token |
| GET | /auth/profile/ | 登录 | 我的资料 |
| PATCH | /auth/profile/ | 登录 | 改昵称/邮箱/手机/简介 |
| POST | /auth/profile/change-password/ | 登录 | 修改密码 |
| POST | /auth/profile/avatar/ | 登录 | 上传头像（multipart: avatar） |
| GET | /auth/me/permissions/ | 登录 | 我的角色/权限编码/是否管理员 |
| GET | /auth/admin/users/ | 管理员 | 用户列表（keyword/status/page_size） |
| POST | /auth/admin/users/create/ | 管理员 | 创建用户 |
| PATCH | /auth/admin/users/{id}/ | 管理员 | 编辑用户（含禁用/配额/角色） |
| POST | /auth/admin/users/assign-roles/ | 管理员 | 批量分配角色 {user_ids, role_ids} |
| GET | /auth/admin/roles/ | 管理员 | 角色列表 |
| POST | /auth/admin/roles/ | 管理员 | 创建角色 |
| PATCH | /auth/admin/roles/{id}/ | 管理员 | 编辑角色（permission_ids 授权） |
| DELETE | /auth/admin/roles/{id}/ | 管理员 | 删除角色（内置不可删） |
| GET | /auth/admin/permissions/ | 管理员 | 权限点列表 |
| GET | /auth/admin/online/ | 管理员 | 15 分钟内活跃用户 |

## 文件 `/api/files`（公开 `/share/...`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /files/folders/?parent= | 登录 | 文件夹列表 |
| POST | /files/folders/ | 登录 | 创建文件夹 {name, parent} |
| PATCH | /files/folders/{id}/ | 登录(owner) | 重命名/移动 |
| DELETE | /files/folders/{id}/ | 登录(owner) | 删除（级联） |
| GET | /files/?folder=&keyword=&sort= | 登录 | 文件列表 |
| GET | /files/search/?q= | 登录 | 全盘搜索 |
| POST | /files/upload/init/ | 登录 | 分片初始化（秒传检测） |
| POST | /files/upload/chunk/ | 登录 | 上传分片（multipart: upload_id/index/chunk） |
| POST | /files/upload/complete/ | 登录 | 合并完成 {upload_id} |
| PATCH | /files/{id}/ | 登录(owner) | 重命名/移动 |
| DELETE | /files/{id}/ | 登录(owner) | 移入回收站 |
| GET | /files/{id}/download/ | 登录(owner/共享) | 下载 |
| GET | /files/{id}/preview/ | 登录(owner) | 文本预览 |
| GET | /files/trash/ | 登录 | 回收站列表 |
| POST | /files/trash/action/ | 登录 | {action: restore/delete/empty, file_ids} |
| GET | /files/shares/ | 登录 | 我的共享链接 |
| POST | /files/shares/create/ | 登录 | {file_id/folder_id, permission, expire_hours} |
| DELETE | /files/shares/{token}/ | 登录(owner) | 撤销链接 |
| GET | /share/{token}/ | 公开 | 匿名访问（文件信息/预览/文件夹列表） |
| GET | /share/{token}/download/{file_id}/ | 公开 | 共享下载（计数） |

## 笔记 `/api/notes`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /notes/?parent=&tag=&search=&favorite= | 登录 | 列表 |
| POST | /notes/ | 登录 | 创建 {title, content, parent, tags} |
| GET | /notes/tree/ | 登录 | 目录树 |
| GET | /notes/tags/ | 登录 | 我的标签 |
| GET | /notes/recent/ | 登录 | 最近 10 篇 |
| GET | /notes/public/{token}/ | 公开 | 公开笔记访问 |
| GET | /notes/{id}/ | 登录(owner) | 详情 |
| PATCH | /notes/{id}/ | 登录(owner) | 更新（自动存版本） |
| DELETE | /notes/{id}/ | 登录(owner) | 删除 |
| GET | /notes/{id}/versions/ | 登录(owner) | 版本历史 |
| POST | /notes/{id}/rollback/{version}/ | 登录(owner) | 回滚 |

## 项目看板 `/api/projects`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /projects/?archived=&search= | 登录 | 项目列表 |
| POST | /projects/ | 登录 | 创建（自动三列） |
| GET | /projects/{id}/ | 成员 | 详情 |
| PATCH | /projects/{id}/ | 创建者 | 编辑/归档 |
| DELETE | /projects/{id}/ | 创建者 | 删除 |
| POST | /projects/{id}/members/ | 创建者 | 添加成员 {usernames} |
| DELETE | /projects/{id}/members/?user_id= | 创建者 | 移除成员 |
| GET | /projects/{id}/boards/ | 成员 | 看板（列+卡片） |
| POST | /projects/{id}/boards/ | 成员 | 新建列 {name} |
| PATCH | /projects/boards/{board_id}/ | 成员 | 列重命名 |
| DELETE | /projects/boards/{board_id}/ | 成员 | 删列（级联卡片） |
| POST | /projects/boards/{board_id}/cards/ | 成员 | 创建卡片 |
| GET | /projects/cards/{id}/ | 成员 | 卡片详情 |
| PATCH | /projects/cards/{id}/ | 成员 | 编辑（含 board 换列） |
| DELETE | /projects/cards/{id}/ | 成员 | 删除卡片 |
| POST | /projects/cards/{id}/move/ | 成员 | 拖拽移动 {board_id, index} |
| GET | /projects/cards/{id}/comments/ | 成员 | 评论列表 |
| POST | /projects/cards/{id}/comments/ | 成员 | 发评论 |
| GET | /projects/{id}/stats/ | 成员 | 项目统计 |

## 消息 `/api/im`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /im/sessions/?search= | 登录 | 会话列表（未读数） |
| POST | /im/sessions/create/ | 登录 | {type, member_ids, name} |
| GET | /im/sessions/{id}/ | 成员 | 会话详情 |
| PATCH | /im/sessions/{id}/ | 成员 | 群名/群成员 |
| GET | /im/sessions/{id}/messages/?page= | 成员 | 消息历史（30/页） |
| POST | /im/sessions/{id}/send/ | 成员 | 发消息 |
| POST | /im/sessions/{id}/read/ | 成员 | 标记已读 |
| GET | /im/unread-total/ | 登录 | 全局未读数 |
| GET | /im/candidates/?q= | 登录 | 用户候选 |

## 通知与日志 `/api/core`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /core/notifications/?unread=1 | 登录 | 通知列表 |
| POST | /core/notifications/read/ | 登录 | {ids: []} 空=全部已读 |
| GET | /core/notifications/unread-count/ | 登录 | 未读数 |
| GET | /core/logs/?username=&module=&action= | 管理员 | 操作日志 |

## 统计 `/api/dashboard`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /dashboard/stats/ | 登录 | 个人统计 |
| GET | /dashboard/admin/global/ | 管理员 | 全局统计 |
| GET | /dashboard/admin/trend/ | 管理员 | 近 14 天趋势 |

## 工具 `/api/tools`（均公开 POST，返回 `{tool, ok, result}`）

| 路径 | 入参 | 出参(result) |
|---|---|---|
| /tools/json/format/ | text, mode(format/minify/sort) | output |
| /tools/json/csv/ | text | output(CSV) |
| /tools/base64/ | text, mode(encode/decode) | output |
| /tools/timestamp/ | value, mode(to_date/to_ts) | date/weekday 或 timestamp |
| /tools/url/ | text, mode(encode/decode) | output |
| /tools/hash/ | text, algos[] | {md5, sha1, ...} |
| /tools/password/ | length, symbols | password, strength |
| /tools/uuid/ | count, version | list |
| /tools/color/ | value | hex/rgb/hsl |
| /tools/word-count/ | text | chars/chinese/lines/words/bytes |
| /tools/regex/ | pattern, text, flags[] | matches, count |
| /tools/markdown/ | text | html |

## WebSocket `/ws/notify/`

- 认证：Cookie 或 URL 携带 token（AuthMiddlewareStack）
- 协议见 docs/02 第 3.3 节
