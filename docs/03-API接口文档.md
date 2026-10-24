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

# 学习中心 `/api/learning`（v3 · 5 个一级入口 · 132 条可访问路由）

> `learning/urls.py` 里有 92 条 `path()` 声明，`school/` 与 `prog/` 下还有二级 include，展开后共 **132 条路由**（`scripts/stats.py` 口径）。一级入口：`school`（K12 学科与知识树）、`prog`（编程语言广场 / 刷题 / 竞技）、`study`（我的学习：番茄钟、计划、成就）、`tools`（学习工具目录 + 运行）、`search`（学习域内搜索）。

| 接口 | 说明 |
|---|---|
| `/api/learning/school/knowledge/` | 知识树；返回 `total_points` 等统计（学习首页统计卡片的数据源，前端不再写死 1500） |
| `/api/learning/prog/lang-catalog/` | 编程语言目录，返回 `{total, list}` |
| `/api/learning/tools/catalog/` · `/tools/run/` | 学习工具目录与统一运行入口 |
| `/api/learning/search/` | 学习域内搜索 |

# AI 助手 `/api/assistant`（v4 · 26 接口）

> 全部接口**优先走 `_call_llm()`，未配置 `LLM_API_KEY` 时本地降级**——降级是真正可用的实现，不是占位符（见 `assistant/llm.py`）。

| 分组 | 接口 |
|---|---|
| 状态 | `/status/` |
| 笔记智能 | `/notes/<pk>/summarize/`、`/notes/<pk>/ask/`、`/auto-tag/`、`/polish/` |
| 对话 | `/chat/`、`/ask/`、`/conversations/`（列表 / 详情 / 分支 / 导出）、`/prompts/`（列表 / 详情） |
| 写作 | `/translate/`、`/names/`、`/weekly-report/`、`/agenda/`、`/email-draft/`、`/social-copy/`、`/math-explain/`、`/daily-digest/` |
| 教学 | `/questions/generate/`、`/questions/grade/` |
| 其它 | `/commands/`、`/input-feedback/` |

# 迷你工具箱 `/api/minitools`（v7/v8 · 26 家族 · 375 接口）

> 目录驱动：`/api/minitools/catalog/` 返回 26 家族 × 374 个纯函数工具，`/api/minitools/run/` 统一执行（`{tool, ok, result}`）。
> **`minitools/urls.py` 末尾有 `assert len(urlpatterns) == 375`**——加工具必须同步改这个断言，否则启动即失败。

# v5 三大能力域 `/api/devtools` `/api/dataintel` `/api/officesuite`（76 子系统 · 518 接口）

> v5 全部接口走统一约定：JWT 鉴权（`IsAuthenticated`）；响应 `{"ok":true,"data":...}` / `{"ok":false,"error":"..."}`；`endpoint` 装饰器兜底 ValueError→400、其余→422，**绝不 500**；除目录外默认 POST（`@endpoint()`），GET-only 接口在目录明细中标为 GET。完整子系统 × 接口清单见根 `FEATURES.md` 第 9 章。

## 目录接口（GET，三域同构）

| 接口 | 返回 data |
|---|---|
| /api/devtools/catalog/ | `{domain, domain_name, subsystems:[{key,name,endpoints,url_prefix}], subsystem_count:27, endpoint_count:154, endpoints:[{path,methods}]}` |
| /api/dataintel/catalog/ | 同构，subsystem_count:20，endpoint_count:114 |
| /api/officesuite/catalog/ | 同构，subsystem_count:29，endpoint_count:250 |

`endpoints` 为接口明细（路径 pattern + 真实方法，从 urlpatterns 反射导出，不含目录自身），前端 `DomainExplorer.vue` 据此目录驱动渲染与调试。

## devtools（27 子系统 · 154 接口）

URL 形如 `/api/devtools/{子系统}/{动作}/`：text/str/md/json/log/encode/regex（文本族 34）、hash/token/code/diff/id/file/qr/web/db（代码与安全族 48）、num/color/date/cron/math/unit（数学族 32）、net/fake/fun/cheatsheet/asciiart（趣味族 39）。典型入参：`text`（文本类）、`pattern+text`（正则）、`a/b`（diff）、`value/from_base`（进制）、`expr`（CRON/表达式）。

## dataintel（20 子系统 · 114 接口）

URL 形如 `/api/dataintel/{子系统}/{动作}/`：dataset（create/list/detail/delete/rows-import/rows-query，数据落库 SQLite）；profile/transform/calc 吃 `rows`（对象数组）+ 参数；stats/forecast/regress/cluster/outlier 吃数值数组（`a`/`b`/`y`）；nlp/textmine/vector 吃 `text` 或数值向量；ai 8 个接口未配 `LLM_API_KEY` 时本地降级；chart 输出直喂 ECharts 的 series 结构；abtest/cohort/sampling/geo/insight 各成体系。

## officesuite（29 子系统 · 250 接口，5 家族）

URL 形如 `/api/officesuite/{子系统}/{动作}/`：flow 41（approval/seal/expense/travel/contract）、res 45（meeting/asset/vehicle/supplies/visitor/mailroom）、people 66（duty/timesheet/training/recognition/standup/okr/decision/todobox）、know 71（faq/policy/template/wiki/minutes/formcollect/announcement/poll/helpdesk）、calendar 9 + 目录 1。行级权限：owner 类查询走 `core/scoping.py` 数据范围；无 owner 字段的模型（报名记录/KR）用显式规则收口；已批准审批单全员可见（审批透明）。

# 代码工坊 `/api/code`（19 子系统 · 110 接口 + 2 公开接口）

> v6 新增独立 app `code`。全部登录接口走 `IsAuthenticated`，响应约定与 v5 三域一致：`{"ok":true,"data":...}` / `{"ok":false,"error":"..."}`，`endpoint` 装饰器兜底 ValueError→400、其余→422，**绝不 500**。
> 路由定义在 `code/urls.py`，`SUBSYSTEMS`（前端目录渲染）+ `VIEWS`（路由串 → 视图函数显式映射）双表结构，结尾 `_EXPECTED = 110` 契约断言。
> 目录接口 `GET /api/code/catalog/` 返回 `{domain, subsystems:[{key,name,endpoints,url_prefix}], subsystem_count, endpoint_count, endpoints:[{path,methods}]}`。

## meta 元信息（4）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/catalog/ | 目录：子系统 × 接口明细（路径 + 真实方法） |
| GET | /code/runtimes/ | 运行时探测（各语言可用性，未装返回 `RUNTIME_NOT_FOUND` 结构） |
| GET | /code/languages/ | 支持的语言清单（含高亮/执行能力标记） |
| GET | /code/templates/ | 新建文件的语言模板 |

## workspace 工作区（7）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/workspaces/ | 工作区列表 |
| POST | /code/workspaces/create/ | 创建工作区 |
| GET | /code/workspaces/{id}/ | 详情 |
| PATCH | /code/workspaces/{id}/update/ | 编辑 |
| DELETE | /code/workspaces/{id}/delete/ | 删除 |
| POST | /code/workspaces/{id}/star/ | 星标/取消 |
| POST | /code/workspaces/{id}/clone/ | 克隆（含全部文件） |

## file 代码文件（10）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/files/ | 文件列表（?workspace=&keyword=） |
| POST | /code/files/create/ | 新建文件 |
| GET | /code/files/tree/ | 工作区文件树 |
| GET | /code/files/{id}/ | 详情（含内容） |
| PATCH | /code/files/{id}/update/ | 保存内容（自动存版本快照） |
| DELETE | /code/files/{id}/delete/ | 删除 |
| POST | /code/files/{id}/favorite/ | 收藏/取消 |
| GET | /code/files/{id}/entry/ | 读取执行入口信息 |
| POST | /code/files/{id}/move/ | 移动/重命名 |
| POST | /code/files/batch/ | 批量操作（删除/移动/收藏） |

## version 版本历史（5）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/files/{id}/versions/ | 版本列表 |
| POST | /code/files/{id}/versions/create/ | 手动创建快照 |
| POST | /code/files/{id}/versions/diff/ | 版本差异对比 |
| POST | /code/files/{id}/versions/{vid}/rollback/ | 回滚到指定版本 |
| DELETE | /code/files/{id}/versions/{vid}/delete/ | 删除版本 |

## run 安全执行（7）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /code/run/ | 执行代码（语言/代码/stdin/args/env/timeout/allow_dangerous） |
| POST | /code/run/repl/ | REPL 逐次执行（保持会话上下文语义） |
| GET | /code/run/history/ | 执行历史 |
| GET | /code/run/{id}/ | 单次执行详情（stdout/stderr/exit_code/duration） |
| DELETE | /code/run/{id}/delete/ | 删除记录 |
| POST | /code/run/clear/ | 清空我的执行历史 |
| GET | /code/run/stats/ | 执行统计（次数/成功率/平均耗时） |

## judge 判题（4）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /code/judge/ | 多测试用例判定（核心 `run_judge()` 纯函数） |
| GET | /code/judge/history/ | 判题历史 |
| GET | /code/judge/{id}/ | 判题详情（逐用例结果） |
| GET | /code/leaderboard/ | 排行榜 |

## snippet 代码片段库（8）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/snippets/ | 片段列表（?tag=&keyword=） |
| POST | /code/snippets/create/ | 创建片段 |
| GET | /code/snippets/tags/ | 标签聚合 |
| POST | /code/snippets/from-file/ | 从代码文件一键提取为片段 |
| GET | /code/snippets/{id}/ | 详情 |
| PATCH | /code/snippets/{id}/update/ | 编辑 |
| DELETE | /code/snippets/{id}/delete/ | 删除 |
| POST | /code/snippets/{id}/copy/ | 复制一份 |

## analyze 静态分析（8，纯 Python 实现）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /code/analyze/ | 综合指标（函数/类/行数/注释率）；键为 `functions` / `classes` |
| POST | /code/outline/ | 结构大纲（函数/类/方法定义） |
| POST | /code/complexity/ | 圈复杂度估算 |
| POST | /code/quality/ | 代码质量评分 |
| POST | /code/flow/ | 控制流图，返回 `{nodes, edges}`（节点用 `type` 字段） |
| POST | /code/similarity/ | 两段代码相似度 |
| POST | /code/secret-scan/ | 密钥/凭据模式扫描 |
| POST | /code/refactor-hints/ | 重构与可读性建议 |

## ai 智能辅助（15，无 `LLM_API_KEY` 时全部本地降级）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/ai/status/ | AI 状态（local / llm） |
| POST | /code/ai/generate/ | 生成代码 |
| POST | /code/ai/transform/ | 代码转换（语言/风格/范式） |
| POST | /code/ai/error-explain/ | 报错解释与修复建议 |
| POST | /code/ai/regex/ | 自然语言生成正则 |
| POST | /code/ai/nl2sql/ | 自然语言转 SQL |
| POST | /code/ai/learning-path/ | 生成学习路径建议 |
| POST | /code/ai/chat-edit/ | 对话式改代码 |
| POST | /code/ai/inline/ | 行内补全 |
| POST | /code/ai/apply/{id}/ | 应用 AI 产出的补丁 |
| POST | /code/ai/translate/ | 代码跨语言翻译 |
| POST | /code/ai/comment/ | 自动补注释（15 种语言风格提示） |
| POST | /code/ai/optimize/ | 性能/结构优化建议 |
| POST | /code/ai/testgen/ | 生成单元测试骨架（含框架选择） |
| POST | /code/ai/summary/ | 代码摘要 |

## collab 协作（6）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/files/{id}/comments/ | 行级评论列表 |
| POST | /code/files/{id}/comments/create/ | 发评论（含行号） |
| POST | /code/files/{id}/comments/{cid}/resolve/ | 标记已解决 |
| DELETE | /code/files/{id}/comments/{cid}/delete/ | 删除评论 |
| GET | /code/files/{id}/collab/ | 协同状态（Yjs 快照 + 版本号） |
| GET | /code/files/{id}/collab/ws/ | 协作 WebSocket 接入信息 |

## share 分享（4）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/shares/ | 我的分享链接 |
| POST | /code/shares/create/ | 创建（权限 / 是否可运行 / 过期） |
| PATCH | /code/shares/{token}/ | 更新分享设置 |
| POST | /code/shares/{token}/revoke/ | 吊销 |

## export 导出（2）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /code/export/zip/ | 工作区打包为 zip |
| GET | /code/export/file/{id}/ | 单文件下载 |

## daily 每日一题（3）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/daily/today/ | 今日题目（`date.toordinal() % N` 确定性轮换，全员同日同题） |
| POST | /code/daily/submit/ | 提交作答 → 复用 `run_judge()`，未通过自动进错题本 |
| GET | /code/daily/history/ | 打卡历史与连续天数 |

## achievement 成就徽章（2）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/achievements/ | 全部 14 个徽章定义 |
| GET | /code/achievements/mine/ | 我的解锁进度（访问时**惰性结算** `check_achievements()`） |

## wrongbook 错题本（4）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/wrongbook/ | 错题列表 |
| POST | /code/wrongbook/add/ | 手动收录 |
| POST | /code/wrongbook/{id}/review/ | 标记复习（计数 + 时间） |
| DELETE | /code/wrongbook/{id}/delete/ | 移除 |

## learnpath 学习路径（5）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/paths/ | 我的学习路径列表 |
| POST | /code/paths/generate/ | 生成路径（LLM 优先，解析失败回落内置模板） |
| GET | /code/paths/{id}/ | 详情（阶段 + 进度 + percent） |
| POST | /code/paths/{id}/tick/ | 勾选/取消某条目完成 |
| DELETE | /code/paths/{id}/delete/ | 删除路径 |

## arena 竞技场（3）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/arena/board/ | 战力榜 |
| POST | /code/arena/challenge/ | 随机抽题 |
| POST | /code/arena/submit/ | 提交（复用 `run_judge()`） |

## learn 学习总览（1）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/learn/overview/ | 个人学习看板聚合（打卡/成就/错题/路径/战力） |

## engineering 工程化（6，零新模型）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /code/blame/{id}/ | 代码归属（沿版本链正序 SequenceMatcher diff 累积每行 author） |
| GET | /code/todos/ | TODO 聚合（8 类标记 × 4 级严重度，支持 by_tag / by_file） |
| POST | /code/diff/ | diff（三模式：`{file,v1,v2}` / `{file,version}` / `{file_a,file_b}`） |
| GET | /code/insights/ | 工程洞察（语言占比/目录分布/30 天活跃/成功率/健康度评分） |
| GET | /code/contributors/ | 贡献者聚合 |
| GET | /code/files/{id}/versions/{vid}/side-by-side/ | 行号对齐并排 diff |

## 公开接口 `/api/share/code/<token>/`（2，无需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /share/code/{token}/ | 只读查看分享的代码 |
| POST | /share/code/{token}/run/ | 试跑分享代码。**只跑服务端按 token 取的代码**，不接受请求体覆盖（防绕过高危扫描）；超时硬限 10s；不落 `CodeRun` 表 |

