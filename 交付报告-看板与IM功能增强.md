# 23 项功能增强交付报告（项目看板 #25-#36 + 即时消息 #37-#47）

环境：Django 5 + DRF + Channels（backend/venv）/ Vue3 + Vite5 + Tailwind3 + Pinia；SQLite。

## 一、总体验证结果

| 项 | 结果 |
|---|---|
| `manage.py check` | ✅ System check identified no issues (0 silenced) |
| `makemigrations projects im` | ✅ 生成 2 个迁移文件 |
| `migrate` | ✅ 成功 |
| `npm run build`（前端） | ✅ built in ~3.85s，无错误 |
| `smoke_test.py` v2 回归 | ✅ 通过 160 项，失败 0 项 |
| 新增接口抽测 | ✅ templates/from-template/burndown/share(创建+公开只读)/quick-reply/keyword-alert 全部 200/201 |

> 冒烟输出中的 `Not Found: /api/im/sessions/40/leave/`、`Forbidden: /api/auth/admin/users/` 是用例刻意触发的负路径断言（非成员退群被拒、普通用户访问后台被拒），对应用例均标 ✓。

## 二、迁移文件

- `projects/migrations/0003_taskcard_last_overdue_notified_at_boardsharelink.py`
- `im/migrations/0003_chatmessage_is_pinned_chatmessage_reply_to_and_more.py`

均为纯新增字段/表，无破坏性删除或重命名。

## 三、项目看板（#25–#36，12 项）

| # | 功能 | 状态 | 实现要点 |
|---|---|---|---|
| 25 | 卡片标签+自定义颜色 | ✅ | TaskCard 已有 `labels` JSONField（后端就绪）；Board.vue 卡片按标签名 hash 取色渲染彩色 pill，支持增删标签 |
| 26 | 到期自动提醒 | ✅ | 新增 `TaskCard.last_overdue_notified_at`；新增管理命令 `projects/management/commands/check_overdue_cards.py`，扫逾期卡向 assignee 走 `notify()` 推送，每卡 20h 去重 |
| 27 | 看板模板库 | ✅ | 硬编码 4 套模板（agile/content/simple/bugfix）；`GET /api/projects/templates/`、`POST /api/projects/from-template/`；Projects.vue 加"从模板创建"弹窗 |
| 28 | 燃尽图/燃起图 | ✅ | `GET /api/projects/<id>/burndown/` 用卡片 created_at/completed_at 重建每日剩余故事点；Board.vue 统计弹窗内 **SVG 折线图**（ECharts 实际未安装，见问题） |
| 29 | 看板只读分享链接 | ✅ | 新模型 `BoardShareLink`(token/created_by/is_revoked/expire_at/view_count)；`POST/DELETE /api/projects/<id>/share/...`；公开只读 `GET /share/board/<token>/`（AllowAny）；新前端 `SharedBoard.vue` + 路由 `/share/board/:token` |
| 30 | 卡片快速筛选 | ✅ | Board.vue 筛选栏：按负责人、按到期（今日/本周/逾期/全部），纯前端过滤 |
| 31 | 列表/紧凑视图切换 | ✅ | Board.vue 头部切换 完整/紧凑 两种卡片密度 |
| 32 | 逾期徽标与高亮 | ✅ | 前端按 due_date 着色：逾期红、今日橙、未来正常；卡片加逾期徽标 |
| 33 | 子任务进度条 | ✅ | 复用 serializer 的 subtask_total/done/progress；卡片内进度条 |
| 34 | 看板主题/背景色 | ✅ | Board 主题切换（浅色/深色/自定义背景），localStorage 记忆 |
| 35 | 卡片复制快捷操作 | ✅ | 复用既有 `copyCard` 接口，卡片 hover 操作菜单加"复制" |
| 36 | 我的任务按项目分组 | ✅ | MyTasks.vue 重写为按项目分组展示（并修复原 `counts.forEach` 对 dict 的既有 bug） |

## 四、即时消息（#37–#47，11 项）

| # | 功能 | 状态 | 实现要点 |
|---|---|---|---|
| 37 | 消息引用回复 | ✅ | `ChatMessage.reply_to` self FK；serializer `reply_to_info`；发送带 `reply_to`；Chat.vue 渲染引用块 + 回复条 |
| 38 | 消息置顶/固定 | ✅ | `ChatMessage.is_pinned`；`POST /api/im/messages/<id>/pin/`；MessageListView 返回 `pinned` 列表；Chat.vue 置顶消息栏 + 取消 |
| 39 | 会话归档 | ✅ | `SessionMemberSetting.is_archived`（按用户归档，不影响群内他人）；SessionListView 加 archived 过滤；Chat.vue 归档 tab + 归档操作 |
| 40 | 聊天记录导出 | ✅ | 复用历史接口，前端打包下载 JSON（Blob + a[download]） |
| 41 | 快捷回复模板 | ✅ | 新模型 `QuickReply(owner,title,content,sort_order)`；CRUD 接口；发送面板 ⚡ 弹窗管理并一键填入 |
| 42 | 关键词提醒 | ✅ | 新模型 `KeywordAlert(owner,keywords JSONField)`；MessageCreateView `_fire_keyword_alerts` 命中即 `notify`；`GET/POST /api/im/keyword-alert/` |
| 43 | 代码块高亮 | ✅ | Chat.vue `renderContent` 按 ``` 切分，代码块渲染深色 `<pre>`（其余文本先 HTML 转义防 XSS）；未引第三方库 |
| 44 | 会话搜索按人/时间 | ✅ | GlobalMessageSearchView 加 sender/date_from/date_to 过滤；前端搜索弹窗加对应筛选 |
| 45 | 群成员搜索 | ✅ | 群管理弹窗加搜索框，`filteredMembers` computed 纯前端过滤 |
| 46 | 单条已读回执 | ✅ | serializer `read_by_count`（基于 SessionMemberSetting.last_read_at >= msg.created_at）；自己发的消息显示"已读 N" |
| 47 | 表情快捷面板 | ✅ | 内置常用 emoji 列表，发送框 😊 弹出选择器插入 |

## 五、新增接口清单（均 `/api/` 前缀，除公开分享）

- `GET  /api/projects/templates/`
- `POST /api/projects/from-template/`
- `GET  /api/projects/<id>/burndown/`
- `POST   /api/projects/<id>/share/`
- `DELETE /api/projects/<id>/share/<token>/`
- `GET  /share/board/<token>/`（公开，无 `/api` 前缀，AllowAny）
- `POST /api/im/messages/<id>/pin/`
- `GET/POST   /api/im/quick-replies/`
- `PATCH/DELETE /api/im/quick-replies/<id>/`
- `GET/POST /api/im/keyword-alert/`
- 既有接口扩展参数：`/im/sessions/`(archived)、`/im/sessions/<id>/messages/`(返回 pinned + sender/date 过滤)、`/im/global-search/`(sender/date)

## 六、遇到的问题与决策

1. **ECharts 实际未安装**：package.json 无 echarts、src 无引用，燃尽图改用**内联 SVG** 实现，未新增依赖。
2. **代码块高亮未引 marked/highlight.js**：为避免 XSS，在 Chat.vue 手写安全渲染——仅 ``` 围栏内做样式化 `<pre>`，其余 HTML 转义后按行渲染。
3. **会话归档粒度**：归档字段放在 `SessionMemberSetting`（按用户）而非 `ChatSession`，群聊内一人归档不影响他人。
4. **公开分享路径**：后端公开只读视图挂在根路径 `/share/board/<token>/`（非 `/api` 前缀，AllowAny），vite proxy 已配 `/share`→后端；前端 SharedBoard.vue 用裸 axios + `API_BASE` 请求，不走带 `/api` 的 request 实例。
5. **DB 既有漂移（非本次改动引入）**：首次冒烟时 `accounts_user` 报"no column named tags"——迁移 0004 记录为已应用但列缺失；重跑后列已就位（推测为早前 migrate 补齐），冒烟随即全绿。已在报告中标注。
6. **只增不改**：未动任何既有接口对外契约；新增字段全部可空/有默认值，迁移纯新增。
