# 全能协作平台 · 功能清单（v4.0.0）

技术栈：Django 5 + DRF + Channels(WebSocket) + SimpleJWT ｜ Vue3 + Vite + TailwindCSS + Pinia
- v2：共 **177 项后端能力（143 个业务接口 + 34 个在线工具）** 与 **20 个前端页面**。
- **v3 全新方向「学习中心」：新增 100 项功能 = 编程学习 30 项 + K12 学科 30 项 + 学习工具 40 个，另加 9 个前端页面与 6 张个人学习数据表（不改动既有业务模块，仅新增独立 app `learning` 并在 settings/根路由/前端菜单做必要装配）。**
- **v4 平台能力补全：新增 11 大横切能力 = 多类型在线预览 · Office→PDF · 全文搜索(中文分词+BM25) · Yjs 实时协同 · `[[双链]]` · 数据行级权限 · 组织架构/部门 · 多租户 · LLM 聊天助手 · 笔记 AI 问答/摘要 · AI 出题与批改；新增独立 app `assistant` 与 `core/scoping.py`，并新增 3 个前端页面（全文搜索 / AI 助手 / 组织架构）。**

## 一、后端接口计数（业务自有，共 143 个）

| 模块 | 接口数 | 主要能力 |
|---|---:|---|
| accounts 账号权限 | 24 | 注册/登录/登出(JWT 黑名单)/刷新/校验、资料、改用户名、改密码、头像上传/删除、注销、数据导出、登录历史、用户名查重、通讯录、我的权限、心跳；管理员：用户列表/新建/编辑/重置密码/批量启停·配额·角色、角色 CRUD、权限点、在线用户 |
| core 通用中心 | 18 | 通知列表/单读/全读/未读数/删除/偏好设置；公告列表/详情/已读 + 管理员公告 CRUD；操作日志列表/我的/统计/CSV 导出；跨模块全局搜索、健康检查、公开设置、站点设置读写 |
| files 文件中心 | 31 | 文件夹 CRUD/树、文件列表/搜索/收藏/复制/在线新建·保存文本/删除/下载/预览、批量操作/打包下载、分片上传 init·status·chunk·complete·abort（断点续传·秒传）、最近、收藏、存储分析、回收站列表/还原·彻底删除/自动清理、分享链接列表/创建/改密·限额/吊销 |
| notes 笔记中心 | 19 | 列表/目录树、标签 CRUD、最近、统计、模板列表/从模板创建、笔记 CRUD/复制/批量、回收站/清空、大纲、版本列表/差异对比/回滚、单篇导出/全量导出 |
| projects 项目看板 | 24 | 项目 CRUD/收藏/克隆/成员增删、看板 CRUD/排序、卡片 CRUD/复制/批量/移动/搜索、子任务 CRUD、工时记录增删、评论 CRUD、活动流、项目统计、日历、我的任务聚合 |
| im 即时消息 | 15 | 会话列表/建会话/详情/改群名/退群/转让/加人/踢人/会话设置(置顶·免打扰·草稿·已读)、消息历史/发送/撤回/删除/转发/搜索、未读总数/分组汇总 |
| dashboard 工作台 | 9 | 个人统计、14 天产出趋势、任务分布、文件类型分布、首页待办聚合、管理员全局统计、操作趋势、30 天用户增长、模块使用排行 |
| tools 工具箱 | 3 | 工具目录、统一运行入口（背后 34 个工具，见下） |
| **合计** | **143** | |

## 二、在线工具（34 个，统一 catalog + run 入口）

JSON 格式化、时间戳、UUID、随机密码、哈希(MD5/SHA 系列)、Base64、URL 编解码、颜色转换、配色生成、CSV↔JSON（2）、二维码、文本大小写、去重、排序、去空白、字数统计、文本对比、文本反转、slugify、Markdown 转纯文本、正则测试、摩斯密码、ROT13、HTML 实体、进制转换、文本↔Hex、文本↔Binary、JWT 解析、密码强度、Luhn 校验、身份证校验、随机数、日期差、单位换算。

## 三、前端页面（20 个）

- 登录/注册
- 工作台 Dashboard（待办聚合、14 天三色产出柱、存储进度、最近笔记/通知）
- 文件：文件库、回收站、分享管理、存储分析（4）
- 笔记：笔记工作台（标签/模板/版本/回收站/大纲/统计/导出）
- 项目：项目列表、看板（子任务·工时·评论·拖拽·筛选）、我的任务（3）
- 消息：Chat（单聊/群聊/置顶/免打扰/草稿/撤回/转发/实时推送）
- 工具箱（34 工具动态表单）
- 系统公告中心、个人中心 Profile
- 管理后台：用户、角色权限、操作日志、全局统计、公告管理、站点设置（6）

## 四、横切能力

- JWT 双 Token + 刷新拦截 + 登出黑名单；RBAC 角色-权限点细粒度鉴权
- 单条 WebSocket 全双工通道：通知 / 文件事件 / 看板事件 / 消息 / 群系统 / 撤回 / 输入中 / 心跳自动重连
- 统一响应 `{code,message,detail}`、统一分页、写操作自动落 OperationLog、统一 Toast
- 最近活跃中间件、回收站 30 天保留策略、存储配额校验、分片上传与秒传

## 五、验证结果

- 后端综合冒烟 `smoke_test.py`：**通过 160 项，失败 0 项**，无 Traceback / 500
- `manage.py check`：0 issues；迁移已应用
- 前端 `npm run build`：**成功**，119 模块，26 个构建产物，无报错
- 开发服务器 `/api/core/health/` 实测 200（db ok, v2.0.0）

## 六、启动方式（PowerShell）

```powershell
# 后端（HTTP）
cd C:\Users\banna\Desktop\web\backend
.\venv\Scripts\python.exe manage.py runserver
# WebSocket（可选，另开窗口）
.\venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application

# 前端
cd C:\Users\banna\Desktop\web\frontend
npm run dev
```

演示账号：**admin / admin123**（超级用户）；新注册用户自动绑定普通用户角色。

---

# 七、v3 新增：学习中心（全新方向，正好 100 项）

> 独立 Django app `learning`（挂载于 `/api/learning/`），**不扩展、不改动任何既有业务模块逻辑**，仅在 `INSTALLED_APPS`、根路由、前端 router/侧边栏/api 封装处做必要接线。面向「10 种编程语言」与「小学 / 初中 / 高中（K12）学习资料」两条主线。
>
> **计数口径：编程学习 30 项 + K12 学科 30 项 + 学习工具 40 个 = 100 项**；另含专注记录 / 学习计划等个人闭环与 9 个前端页面（100+）。

## 7.1 编程学习 30 项（10 种语言：Python/JavaScript/C/C++/Java/Go/Rust/C#/Swift/Kotlin）

1. 语言总览（10 语言卡片）2. 语言详情 3. 分阶段学习路线 4. 语法速查 5. 关键字表 6. 数据类型参考 7. 代码片段库（主题过滤）8. 片段详情 9. 多语言横向对比 10. 99 条编程术语词典（搜索/标签）11. 六大编程范式 12. 入门课程列表（每语言 5 课）13. 课程详情（要点+范例）14. 单选题 15. 读程序写结果 16. 代码填空 17. 找错题 18. 单题判分 19. 随机抽题 20. 按目标/基础推荐语言 21. 常见报错排查 22. 23 个入门算法目录 23. 18 种数据结构词典 24. 开发环境/IDE 指南 25. 编码规范 26. 整卷交卷计分 27. 每日一题 28. 学习进度列表 29. 进度新增/更新(upsert) 30. 代码片段收藏（增/查/删）。每种语言均内置元信息、Hello World、路线、12 条速查、关键字、8 类类型、6 段片段、5 节课程、报错、IDE、规范与覆盖 4 种题型共 82 道练习题。

## 7.2 K12 学科 30 项（小学/初中/高中）

1. 学段学科目录 2. 学科详情 3. 知识点树（457 个知识点，含初高中语文知识树）4. 知识点详情 5. 知识点全局搜索 6. 公式手册（60 条，安全 AST 求值）7. 公式详情 8. 公式代入计算（内置 π/e/g 常量）9. 古诗文目录（30 首）10. 古诗文详情（原文/译文/主旨）11. 古诗接句默写 12. 分级英语词表（139 词/多主题）13. 单词详情 14. 单词听写默写 15. 单词选择测验 16. 个人生词本（增/删/掌握切换）17. 题库列表（115 题，单选/判断/填空，覆盖三学段九学科）18. 题目详情（答案解析）19. 智能组卷（试卷+答案卷分离）20. 交卷自动判分 21. 错题本（增/删/订正）22. 知识点掌握度汇总 23. 成语词典（70 条，支持接龙）24. 成语接龙 25. 汉字字典（181 字/部首筛选，兼作拼音库）26. 元素周期表（118 种元素全量/分类）27. 元素详情 28. 化学方程式库（52 条/现象/条件，兼容 Unicode 下标）29. 英语语法目录（28 点）30. 语法点详情（规则+例句）。

## 7.3 学习工具 40 个（统一 catalog + run，并为每个工具生成直达路由）

- 数理计算（13）：arith-gen 口算出题、fraction-simplify 约分、gcd-lcm 最大公因数/最小公倍数、prime 质因数分解、roman 罗马数字、quadratic 一元二次方程、linear2 二元一次方程组、sequence 数列、plane-geo 平面图形、solid-geo 立体图形、percent 百分数、unit-convert 单位换算、temp 温度换算。
- 化学（2）：molar-mass 化学式摩尔质量（解析括号/Unicode 下标）、balance-check 方程式配平原子守恒检查。
- 英语/语文（6）：en-word-freq 词频统计、en-readability 易读性、en-inflect 词形变化、ipa-table 48 国际音标表、pinyin 汉字注音、composition-count 作文字数统计。
- 成绩与学习管理（10）：score-stats 成绩统计、rank 排名(多种并列规则)、gpa 绩点换算、ebbinghaus 艾宾浩斯复习点、pomodoro 番茄钟统计、roll-call 随机点名、group 随机分组、study-plan 学习计划排程、flashcard-sched 闪卡调度、points-to-flashcard 要点转闪卡。
- 思维与基础训练（9）：truth-table 真值表、study-time 学习时长、rmb 人民币大写、calendar-math 日期/星期/闰年、clock-drill 钟表练习、pattern 找规律、multiplication-table 乘法表、unit-rate-table 常用进率表、probability 概率模拟。

## 7.4 个人学习数据（6 张表，用户私有）

LearningProgress 学习进度、SnippetBookmark 代码收藏、WordbookItem 生词本、MistakeRecord 错题本、StudySession 专注记录、StudyPlan 学习计划；均已注册 Admin、生成并应用迁移 `learning/0001_initial`。

## 7.5 前端页面（9 个，复用全局 card/input/btn/tag 与 brand/ink 设计体系）

学习中心总览（每日一题+目标推荐）、编程语言广场（详情十页签+对比+术语+算法结构）、编程刷题训练、学科知识中心（知识点/公式计算/语法/化学）、语文园地（古诗/成语/汉字）、英语角（词表/听写/测验/音标/生词本）、题库与组卷（在线判分+错题本）、学习工具箱（40 工具）、我的学习（进度/收藏/专注/计划）。侧边栏新增「学习中心」分组 9 个入口，`api/index.js` 新增 `learnApi`。

## 7.6 v3 验证结果

- `learning_smoke_test.py`（APIClient 真实打接口）：**通过 80 项检查、失败 0**，覆盖编程 30 + 学科 30 端点全 200、40 工具 run 全部返回 result、组卷用标准答案判分得满分、生词本/错题本/进度/收藏/专注/计划数据库闭环。
- 40 个学习纯函数工具逐一样例运行 **40/40 通过**；60 条公式代入全部可计算；10 语言练习题四题型无缺失（共 82 题）。
- **知识库已全部充实（v3.1）**：元素 33→**118（完整周期表，摩尔质量工具同步支持全部元素）**、方程式 24→52、英语词 60→139（音标 48 完整保留）、古诗 15→30、成语 26→70、汉字 50→181、题库 41→115、知识点 377→457（补齐初高中语文树）、公式 34→60、语法 15→28、术语 50→99、算法 14→23、数据结构 12→18、每语言课程 3→5 课；已脚本校验：元素序号 1–118 连续、方程式逐条原子守恒、公式全部可求值、题目/练习 ID 无重复且答案合法。
- `manage.py makemigrations/migrate/check`：迁移已应用，**0 issues**（本次仅扩充静态数据，未改模型，无需迁移）。
- 前端 `npm run build`：**成功**，128 模块转换、无报错，新增 9 个学习页构建产物，首页统计默认值已同步为 457 知识点 / 60 公式。

---

# 八、v4 新增：平台能力补全（11 大横切能力）

> 原则同 v3：**不改动既有业务模块的对外契约**，新增能力以「独立 app + 统一收口函数 + 可降级适配器」的方式接入，默认关闭的新特性保持向后兼容。

## 8.1 文件在线预览增强（自适应类型 + HTTP Range）

- `File.preview_type` 自动分类：`image` / `video` / `audio` / `pdf` / `text` / `office` / `none`，前端按类型选择 `<img>` / `<video>` / `<audio>` / `<iframe>` / `<pre>` 渲染。
- 新增 `GET /api/files/<id>/raw/`：**支持 HTTP Range**（`Range: bytes=0-`），返回 206 Partial Content 或 416，用 `StreamingHttpResponse` 分块推送 —— 视频/音频可拖动进度条、大图不整包载入。
- `FileMetaSerializer` 新增 `preview_type` / `previewable` / `raw_url` / `pdf_url`，前端 `Files.vue` 行内「预览」按钮对所有可预览类型统一走 `openPreview()`。

## 8.2 Office 转 PDF（LibreOffice 可插拔适配器）

- `files/office.py`：`find_soffice()`（候选路径 + `SOFFICE_PATH` 环境变量）、`can_convert()`、`convert_to_pdf()`、`soffice_status()`。
- `POST /api/files/<id>/to-pdf/` 触发转换并落库（`pdf_path` / `pdf_status` / `pdf_error` / `pdf_updated_at`），`GET /api/files/<id>/pdf/` 回读，`GET /api/files/office-capability/` 查询能力。
- **优雅降级**：未安装 LibreOffice 时返回结构化 `LIBREOFFICE_NOT_FOUND` 与安装提示，**不会 500**；前端展示安装引导。

## 8.3 文档全文搜索（纯 Python 倒排索引，中文免分词）

- `core/search.py`：`tokenize()`（**中文 bigram 切分 + 拉丁词**，无需第三方分词器/词典）、`extract_text()`（txt/md/csv/json/pdf/docx/xlsx）、`index_document()` / `remove_document()` / `search()`（**BM25-lite 排序**）/ `suggest()` / `index_stats()`。
- 数据模型 `SearchDoc`（module/object_id/owner/title/summary/length）+ `SearchTerm`（doc/term/freq/in_title），`core/signals.py` 对笔记/文件/项目/任务卡片 `post_save`·`post_delete` **自动增量索引**。
- 接口：`/core/search/fulltext/`（分页 + 模块过滤 + 高亮片段 + 命中词）、`/core/search/suggest/`（补全）、`/core/search/stats/`、`/core/search/reindex/`（重建）；管理命令 `reindex_search`。
- **复用既有全文搜索**：`GlobalSearchView` 改为走 `core.scoping.scope_queryset`，与数据权限天然一致。

## 8.4 实时协同编辑（Yjs/CRDT over WebSocket）

- 复用既有 WebSocket 通道，新增 `ws/notes/<note_id>/` 路由与 `CollabConsumer`：服务端**只做中继与持久化**（快照 + 更新日志，`MAX_UPDATE_LOG=200`），**不做 CRDT 合并**，合并由客户端 Yjs 完成（真正的 CRDT 语义）。
- 新增 `ws_app/middleware.py::JWTAuthMiddleware`：支持 `?token=<JWT>` 查询参数与 `Authorization` 头，**解决原 WS 仅 Session 鉴权、前端 localStorage JWT 无法握手的问题**；未认证连接被拒绝。失败原因会打 WARNING（`ws_auth` 取值 `no-token` / `token-expired` / `token-invalid` / `user-not-found-or-inactive`），因为 Daphne 只输出笼统的 `WebSocket REJECT`，无法区分「没带 token」与「token 过期」。
- **长连接令牌生命周期**：客户端建连前先解析 JWT `exp`，临期/过期则用 `/api/auth/refresh/` 换新后再连；普通断线按指数退避重连（3s→30s 封顶），而认证失败（close code 4001）只刷新重试一次，仍失败即停止重连并回到登录页 —— 避免「过期 token + 3 秒无脑重连」导致的握手刷屏死循环。`App.vue` 监听登录态变化同步实时通道（登录即连、登出即停）。
- 模型 `NoteCollabState`（BinaryField 快照 / JSON 更新日志 / revision / text_mirror）；前端 `utils/collab.js` 封装 `NoteCollab` 类（本地文本前缀/后缀差分 → Yjs 增量、awareness 在线成员、`compact()` 落快照）。
- 前端 `Notes.vue` 顶部「👥 协同」开关，开启后自动同步并显示在线协作者。

## 8.5 笔记双链 `[[ ]]`（反向链接 / 出链 / 悬浮链接 / 图谱）

- `notes/links.py`：`parse_links()`（正则支持 `[[标题]]` 与 `[[标题|别名]]`）、`rebuild_links_for_note()`、`resolve_dangling_links()`、`backlinks()` / `outgoing_links()` / `link_graph()` / `suggest_titles()` / `dangling_notes()`。
- 模型 `NoteLink`（source/target/owner/target_title/alias），保存笔记时自动解析重建链接，指向不存在笔记的链接记为**悬浮链接（dangling）**，可一键 `from-title` 创建。
- 接口：`/notes/<pk>/backlinks/`、`/notes/graph/`、`/notes/link-suggest/`、`/notes/dangling/`、`/notes/from-title/`、`/notes/links/rebuild/`。
- 前端 `Notes.vue` 右侧「🔗 关联」面板（反链/出链/悬浮链接 + 关系图谱弹窗）；编辑器内输入 `[[` 弹出笔记选择浮层，选中即插入链接。

## 8.6 数据行级权限（20 权限点 → +Data Scope）

- 在既有 RBAC（角色-权限点）之上叠加**行级数据范围**：`self`（仅本人）/ `dept`（本部门）/ `dept_and_sub`（本部门及下级）/ `all`（全部数据），用户多角色时按 `DATA_SCOPE_WEIGHT` **取最高级别**。
- `core/scoping.py` 统一收口：`visible_user_ids(user)` / `scope_queryset(qs, user, owner_field, co_member_field)` / `is_visible()` / `describe_scope()`；业务模型无需新增字段，owner 类查询一律经此过滤。
- 已接入：全局搜索、全文搜索、笔记可见性（`notes/views._note_qs`）、文件列表（`files/views._file_qs`）等。
- 接口 `GET /auth/me/scope/` 返回当前用户生效的数据范围说明（可见人数 / 部门 / 租户）。

## 8.7 组织架构 / 部门（自引用树）

- 模型 `Department`：自引用 `parent`，含 `descendant_ids()`（含/不含自身）与 `path_name()`（"总部 / 研发中心 / 前端组"）。
- 接口：`/auth/admin/departments/`（树，支持 `?flat=1` 扁平化、按租户过滤）与 `/auth/admin/departments/<pk>/`（详情含 `descendant_ids` 与成员；编辑时**防止把上级设为自己或后代造成环**；删除前校验成员/子部门非空）。
- 初始化命令 `seed_org`（幂等）：创建默认租户与 6 个示例部门并把存量用户回填租户。
- 前端新增 **组织架构页 `/admin/org`**（部门树增删改 + 租户管理 + 我的数据范围卡片），`AdminUsers.vue` 增加「部门」列与部门/租户下拉，「AdminRoles.vue」增加数据范围单选。

## 8.8 多租户（Tenant，默认关闭向后兼容）

- 模型 `Tenant`（name/code/is_active/expire_at/remark）；`User`、`Role`、`Department` 可关联租户。
- `accounts/middleware.py::TenantMiddleware` 从 `X-Tenant-Code` 头或当前用户解析 `request.tenant`。
- 隔离策略：**租户 → 用户集合 → 数据范围**，沿用 `core.scoping` 收口，业务模型零改动。
- 开关 `TENANCY_ENABLED` **默认 False**：不开启时行为与 v3 完全一致，存量数据无需迁移语义。

## 8.9 LLM 聊天助手（OpenAI 兼容 + 本地降级）

- 独立 app `assistant`；`assistant/llm.py::chat()` 用标准库 `urllib` 直连 Chat Completions 协议（**不引入任何 SDK 依赖**），支持 `chat_json()` 结构化输出、`is_configured()` / `status()` / `log_usage()`。
- 配置 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`；**未配置时全部 AI 能力自动降级为本地实现**（抽取式摘要、要点提取、检索问答、启发式评分），保证功能可演示可测试。
- `assistant/retrieval.py` 提供 RAG-lite：`chunk_text()` → `rank_chunks()` → `build_context()`，聊天可勾选「检索我的笔记」作为回答依据并返回引用来源。
- 会话持久化 `AIConversation` / `AIMessage`（含引用），接口 `/assistant/chat/`、`/assistant/ask/`、`/assistant/conversations/*`。

## 8.10 笔记 AI 问答 / 摘要

- `POST /assistant/notes/<id>/summarize/`：生成并**缓存**摘要（写入 `Note.ai_summary` / `ai_summary_at`），`GET` 直接读缓存。
- `POST /assistant/notes/<id>/ask/`：基于该篇笔记内容（chunk + rank）回答问题，返回答案与引用片段。
- 前端 `Notes.vue` 右侧「AI 助手」页签：一键生成摘要 + 要点列表 + 就本篇提问。

## 8.11 AI 出题与批改

- `POST /assistant/questions/generate/`：按知识点 / 题型（单选·判断·填空·主观·编程）/ 题量 / 难度出题；**有 LLM 用 LLM，无则从内置题库智能抽题**（`source` 字段标注来源），可落库 `AIGeneratedQuestion`。
- `POST /assistant/grade/`：支持主观题与编程题批改，返回分数 / 反馈 / 待补充要点；**未通过时自动写入既有错题本 `MistakeRecord`**（与学习中心打通）。
- 前端新增 **AI 助手页 `/ai`**：对话助手 / AI 出题 / AI 批改 三个页签。

## 8.12 前端页面（新增 3 个，总 23→26 个业务页）

- **全文搜索 `/search`**：联想补全、模块过滤、命中高亮、相关度、耗时、索引概况、一键重建我的索引。
- **AI 助手 `/ai`**：对话（多会话/检索笔记/引用来源）、出题（参数化 + 我的题目管理）、批改（评分反馈 + 写入错题本）。
- **组织架构 `/admin/org`**：部门树（递归组件，增删改 + 负责人 + 租户）、租户列表（CRUD + 到期 + 启停）、我的数据范围。
- 侧边栏新增「全文搜索 / AI 助手 / 组织架构」三项（版本标识更新为 v3.0）；`api/index.js` 新增 `searchApi` / `orgApi` / `aiApi`，扩展 `fileApi`（raw/pdf/toPdf/officeCapability）与 `noteApi`（backlinks/linkGraph/linkSuggest/dangling/fromTitle/rebuildLinks）。

## 8.13 v4 新增数据表与接口

- 新增表：`assistant`（AIConversation / AIMessage / AIGeneratedQuestion / AIUsageLog）、`core.SearchDoc` / `core.SearchTerm`、`notes.NoteLink` / `notes.NoteCollabState`、`accounts.Tenant` / `accounts.Department`；`Note` 增加 `ai_summary` / `ai_summary_at`，`File` 增加 `pdf_*` 四字段，`Role` 增加 `data_scope`，`User` 增加 `tenant` / `department`。
- 新增接口约 **24 个**：搜索 4 + 文件预览/转 PDF 4 + 笔记双链 6 + 组织架构/租户 8 + AI 助手 8 中的合计（含 `/auth/me/scope/`）。

## 8.14 v4 验证结果

- **`extensions_smoke_test.py`（APIClient + WebsocketCommunicator 真实打接口）：78 项全通过、0 失败**，覆盖：
  - 数据范围（`self`/`dept`/`dept_and_sub`/`all` 可见人数与越权不可见）；
  - 组织架构（建部门 / 建子树 / 环检测 / 有成员时拒删）；
  - 全文搜索（中文词组命中 / 模块过滤 / 建议 / 统计 / 重建）；
  - 双链（解析 `[[ ]]` 与别名 / 反链 / 出链 / 悬浮链接 / 一键创建 / 图谱）；
  - 文件（`preview_type` 分类 / Range 206 与 416 / Office 能力探测优雅降级）；
  - 协同（WS JWT 握手成功、未认证被拒、update 中继回显）；
  - AI（状态 / 摘要缓存 / 笔记问答 / 聊天 / 出题 / 批改并写错题本，全部在**无 LLM 密钥的本地降级模式**下通过）。
- 回归：`smoke_test.py` **160/160**、`learning_smoke_test.py` **80/80**，均 0 失败 —— v4 未破坏既有 v2/v3 能力。
- `manage.py makemigrations accounts core notes files assistant` + `migrate` 已应用；`manage.py check` → **0 issues**；`seed_org`（6 部门 / 存量用户回填租户）与 `reindex_search`（88 篇文档入库）执行成功。
- 前端 `npm run build`：**成功**，168 模块转换、全部构建产物生成（含新增 `Search` / `AiAssistant` / `AdminOrg` 三个 chunk），无报错。

## 8.15 v4 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `SEARCH_ENABLED` | 是否启用全文搜索 | `True` |
| `TENANCY_ENABLED` | 是否启用多租户隔离 | `False` |
| `SOFFICE_PATH` | LibreOffice 可执行文件路径 | 自动探测 |
| `OFFICE_CONVERT_TIMEOUT` | Office 转 PDF 超时（秒） | 120 |
| `LLM_API_KEY` | 大模型密钥；未设置则 AI 全部本地降级 | 空 |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名 | `gpt-4o-mini` |

## 8.16 后端根路径与排障

- `GET /` 返回友好 JSON（服务名 / 版本 / `api_prefix` / WebSocket 路径 / 前端端口提示），不再返回 404 —— 避免「打开 8000 端口以为服务坏了」的误解；`GET /favicon.ico` 返回 204，消除浏览器 404 噪声。
- WebSocket 握手中若携带的 token 未通过校验，会打印 WARNING 并附带原因（`token-expired` / `token-invalid` 等），无需再靠猜；未携带 token 时打印 INFO 说明已回退 Session 认证。

## 8.17 .env 配置文件（LLM 密钥）

- `settings.py` 顶部通过 **python-dotenv** 自动加载 `backend/.env`（可选依赖：未安装时静默跳过、仅用系统环境变量，不影响启动）；同名变量以**系统环境变量优先**（`load_dotenv` 默认不覆盖已存在变量）。
- `requirements.txt` 新增 `python-dotenv>=1.0`；仓库提供 `backend/.env.example` 模板；根 `.gitignore` 已忽略 `.env` / venv / node_modules / db 等。
- LLM 默认指向 **NVIDIA NIM**（`LLM_BASE_URL=https://integrate.api.nvidia.com/v1`，注意 `/v1` 后缀必须带上；密钥在 build.nvidia.com 生成，`nvapi-` 开头），示例模型 `deepseek-ai/deepseek-v4-flash-0731`；未填 `LLM_API_KEY` 时 AI 仍自动走本地降级，行为不变。
- 修改 `.env` 后需**重启 Daphne** 生效；已验证：`.env` 加载、环境变量覆盖优先级、AI 状态切换（local ↔ llm）均正确。
- **排障实录（2026-09-13）**：前端 axios 全局超时 60s < 后端 `LLM_TIMEOUT` 90s，大模型响应慢时前端先报 `timeout of 60000ms exceeded`；已把 `aiApi` 中走大模型的 6 个 POST 放宽到 180s（`AI_TIMEOUT`），普通接口维持全局 60s。
- NIM 的 `deepseek-v4-flash-0731` / `deepseek-v4-pro-0813` 实测持续挂起（>100s 无响应，关 thinking 同样），默认模型改为 `nvidia/nemotron-3-super-120b-a12b`（关闭思考实测 ~1-4s）；新增 `LLM_EXTRA_BODY`（JSON 字符串，透传合并进 `/chat/completions` 请求体，用于厂商专属开关，解析失败自动忽略不影响启动）。

