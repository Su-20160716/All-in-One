# 全能协作平台 · 功能清单（v8.0.0）

技术栈：Django 5.2 + DRF 3.18 + Channels 4.3 + SimpleJWT 5.5 + drf-spectacular ｜ Vue3.5 + Vite 7 + TailwindCSS 4 + Pinia 3 + CodeMirror 6

> **当前实测规模（以 `scripts/stats.py` 输出为准，2026-10-24）**：16 个 app · **1518 条路由叶子** · 145 个模型 · 41 个前端页面 · 49 条前端路由 · 代码约 9.1 万行（后端 71,591 / 前端 19,819）。
> 下文各版本条目里的数字是**当时**的交付快照，用于横向对比版本体量；要"现在到底多少"，跑 `python scripts/stats.py`。
- v2：共 **177 项后端能力（143 个业务接口 + 34 个在线工具）** 与 **20 个前端页面**。
- **v3 全新方向「学习中心」：新增 100 项功能 = 编程学习 30 项 + K12 学科 30 项 + 学习工具 40 个，另加 9 个前端页面与 6 张个人学习数据表（不改动既有业务模块，仅新增独立 app `learning` 并在 settings/根路由/前端菜单做必要装配）。**
- **v4 平台能力补全：新增 11 大横切能力 = 多类型在线预览 · Office→PDF · 全文搜索(中文分词+BM25) · Yjs 实时协同 · `[[双链]]` · 数据行级权限 · 组织架构/部门 · 多租户 · LLM 聊天助手 · 笔记 AI 问答/摘要 · AI 出题与批改；新增独立 app `assistant` 与 `core/scoping.py`，并新增 3 个前端页面（全文搜索 / AI 助手 / 组织架构）。**
- **v5 三大能力域（目录驱动）：新增 3 个独立 app（`devtools` / `dataintel` / `officesuite`），共 **76 个子系统 + 518 个接口**（devtools 27 子系统 154 接口 · dataintel 20 子系统 114 接口 · officesuite 29 子系统 250 接口），三域 catalog 全量返回接口明细（路径 + 方法）供前端动态渲染；前端一份 `DomainExplorer` 组件驱动三个域的浏览与调试，新增 3 个页面（总 26→29 个）。**
- **v6 代码工坊（2026-09-19）：新增独立 app `code`，落地 100 项能力 = 编辑内核 22 + 执行沙箱 20 + 智能化 22 + 协作工程化 22 + 竞技教学 14；新增 **15 张表 · 110 个登录接口 + 2 个公开接口 · 3 个前端页面**（代码工坊 / 代码学习中心 / 分享代码）。编辑器内核为 CodeMirror 6，执行走进程级沙箱 + 可降级适配器，AI 全程支持本地降级。**

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
# 后端（HTTP + WebSocket 由 Channels 的 runserver 一并承载）
cd C:\Users\banna\Desktop\banna\web\backend
.\venv\Scripts\python.exe manage.py runserver   # 项目自带 backend/venv 为 Python 3.13

# 前端
cd C:\Users\banna\Desktop\banna\web\frontend
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

# 九、v5 新增：三大能力域（目录驱动，76 子系统 + 518 接口）

> 设计原则（沿用 v4 约定并加强）：三域全部**只增不改**（不动任何既有接口契约）；所有计算类接口统一 `endpoint` 装饰器兜底——ValueError→400、其余异常→422（结构化 `{"ok":false,"error":...}`，**绝不 500**）；外部依赖缺失一律可降级（AI 走本地实现、导出走 CSV 兜底）；行级权限继续收口在 `core/scoping.py`。
> 三个域的 `/catalog/` 目录接口（GET）返回 `domain / domain_name / subsystems / subsystem_count / endpoint_count`，并在 v5 收尾时**新增 `endpoints` 明细字段**（`[{path, methods}]`，从 urlpatterns 反射还原每个路径的真实 GET/POST）——前端据此目录驱动渲染，后端加接口无需改前端。

## 9.1 devtools 开发者工具箱（27 子系统 · 154 接口）

| 子系统 | 接口 | 子系统 | 接口 |
|---|---:|---|---:|
| text 文本处理 | 6 | num 数字进制 | 6 |
| str 字符串进阶 | 6 | color 颜色实验室 | 6 |
| md Markdown 工具链 | 6 | date 日期数学 | 6 |
| json JSON 进阶 | 6 | cron CRON 表达式 | 4 |
| log 日志分析 | 5 | math 数学扩展 | 6 |
| encode 编码转换 | 5 | unit 单位换算 | 4 |
| regex 正则实验室 | 6 | net 网络工具 | 6 |
| hash 哈希扩展 | 5 | fake 模拟数据 | 7 |
| token 令牌与密钥 | 6 | fun 趣味盒子 | 8 |
| code 代码工具 | 6 | cheatsheet 速查手册 | 8 |
| diff 差异对比 | 5 | asciiart ASCII 艺术 | 6 |
| id 标识符 | 4 | qr 码制 | 3 |
| file 文件工具 | 6 | web 接口助手 | 6 |
| db SQL 助手 | 5 | catalog 目录 | 1 |

合计 154（含目录）。亮点：jwt-sign/jwt-verify、otp/nanoid/password-audit、sql-format/where-builder/join-explain、ieee754/bitwise/combinatorics、dijkstra/linear-solve、CRON 解析/校验/推演、zip-list/data-url/编码探测、ASCII banner/sparkline/progress、模拟身份/银行卡（Luhn 生成）/Lorem 等。

## 9.2 dataintel 数据智能中心（20 子系统 · 114 接口）

| 子系统 | 接口 | 子系统 | 接口 |
|---|---:|---|---:|
| dataset 数据集管理 | 6 | ai AI 增强 | 8 |
| profile 数据画像 | 5 | report 智能报表 | 5 |
| transform 数据变换 | 6 | chart 图表数据 | 8 |
| calc 数据计算器 | 5 | abtest A/B 实验 | 5 |
| stats 统计检验 | 8 | cohort 留存分析 | 4 |
| forecast 时间序列 | 6 | sampling 抽样 | 4 |
| regress 回归拟合 | 5 | geo 轻地理计算 | 6 |
| cluster 聚类 | 4 | insight 自动洞察 | 6 |
| outlier 异常检测 | 4 | nlp 中文 NLP | 8 |
| textmine 文本挖掘 | 5 | vector 向量运算 | 5 |
| catalog 目录 | 1 | | |

合计 114（含目录）。亮点：数据集 CRUD + 行级导入查询、pivot/groupby/filter-expr、t 检验/卡方/比例区间、移动平均/指数平滑/线性趋势/季节朴素/分解、线性/多项式/logit 回归、kmeans/层次/DBSCAN/肘部、zscore/IQR/MAD/LOF、分词/关键词/情感/摘要/实体/相似度/可读性、simhash、cosine/knn/质心、AI 对话/翻译/改写/分类/抽取（本地降级）、A/B 分流+显著性、留存矩阵、分层/系统/Bootstrap 抽样、haversine/geohash/多边形/ETA、自动洞察叙述。

## 9.3 officesuite 办公套件（29 子系统 · 250 接口，5 大家族）

- **流程域 flow（41）**：approval 通用审批 12（模板/提交/我的已发/待我处理/统计/详情/同意/驳回/撤回/评论/流转记录/催办，已批准单全员可见、其余仅 owner 与超管）；seal 用印 6；expense 报销 8（提交/台账/统计/CSV 导出/详情/批/驳/付款）；travel 差旅 7；contract 合同 8（台账/到期预警/回款）。
- **资源域 res（45）**：meeting 会议室 10（房间管理/预订/冲突检查 availability/我的预订/统计）；asset 固定资产 9；vehicle 车辆 7；supplies 办公用品 7；visitor 访客 7；mailroom 快递代收 5。
- **人员域 people（66）**：duty 值班排班 9；timesheet 工时 9（填报/周视图/汇总/导出/审批）；training 培训 10（报名/花名册/签到/反馈，报名全员开放、报名记录按 本人/负责人/超管 收口）；recognition 表彰墙 6；standup 每日站会 7；okr 目标 10（O/KR/进度/总览/历史沿 Objective 可见性）；decision 决策记录 7；todobox 轻待办 8。
- **知识域 know（71）**：faq 7；policy 制度 7（确认回执/确认名单）；template 模板 7（分类/渲染）；wiki 团队 Wiki 9（树/修订/移动带环检测）；minutes 会议纪要 7（行动项）；formcollect 收集表 8（填报/entries/导出）；announcement 部门公告 8（置顶/已读名单）；poll 投票 9（我的票/结果/开关）；helpdesk 工单 9（指派/回复/解决/重开/优先级）。
- **日历域 calendar（9）**：共享日程（事件 CRUD/今日与本周 agenda/RSVP/出席名单）+ 目录 1。

合计 250（v5 交付时为 233，后续版本在流程/人员/知识域继续加接口）。行级权限对无 owner 字段的模型（TrainingEnrollment/KeyResult）显式实现 `_get_enrollment` 等规则，不走 `scope_queryset`（避免 FieldError）。

## 9.4 前端接入（目录驱动，页面 26→29）

- **`views/toolbox/DomainExplorer.vue`（一份代码三域复用）**：三栏布局 = 子系统列表 → 接口列表（GET/POST 徽标，来自 catalog `endpoints` 明细）→ 执行器（方法/路径/JSON 请求体可编辑，GET 自动转 query string，含 `<int:pk>` 占位符提示）；常用接口预置参数模板（约 30 组启发式），响应 JSON 美化展示、一键复制；顶部关键字搜索（子系统名 + 接口路径）。
- **路由与导航**：`/toolbox/devtools`（开发工具箱）、`/toolbox/dataintel`（数据智能中心）、`/toolbox/office`（办公套件）三条路由共用同一组件（props 传域），侧边栏新增 3 个入口，版本号升级 v5.0。
- **`suiteApi`**（`src/api/index.js`）：`catalog(domain)` + `call(domain, path, method, data)`；`request.js` 错误链补 `response.data.error` 透传（v5 结构化错误体直达 Toast）。
- officesuite 的 URL 首段与子系统 key 存在三处不同（form→formcollect、ticket→helpdesk、todo→todobox），前端目录分组做别名归位。

## 9.5 v5 验证结果（2026-09-14 全绿）

- **v5 套件冒烟 `suite_smoke_test.py`**：12 轮迭代收敛，**通过 537 / 失败 0**（覆盖当时 501 接口，现三域合计 518 + 36 个深度断言：权限矩阵、wiki 环检测、留存矩阵、降级 4xx 结构化等）。
- **四套串行回归**（防 SQLite `database is locked`）：`smoke_test.py` v2 160✓/0✗、`learning_smoke_test.py` v3 81✓/0✗、`extensions_smoke_test.py` v4 EXIT:0、`suite_smoke_test.py` v5 537✓/0✗；`manage.py check` EXIT:0。
- **catalog 端到端（APIClient 全链路）**：devtools 27 子系统/153 明细、dataintel 20/113、officesuite 29/232，方法反射与真实行为一致（GET 抽测 200），合计 498 明细 + 3 目录 = 501。
- **前端 `vite build`**：170 模块构建成功（DomainExplorer 7.63 kB / gzip 3.79 kB），EXIT:0。

# 十、v6 新增：代码工坊（15 表 + 110 接口 + 2 公开接口 + 3 页面）

> **定位**：把「写代码 / 跑代码 / 学代码」这件事整个搬进平台，做成一个自包含的在线 IDE + 教学系统。
> **设计原则**（沿用 v4/v5 约定）：`code` 为**独立 app，只增不改**——不动任何既有接口契约，仅在 `settings.INSTALLED_APPS`、根路由、前端菜单做必要装配；全部计算类接口走 `devtools/common.py` 的 `endpoint` 装饰器兜底（ValueError→400、其余→422，**绝不 500**）；外部依赖缺失一律**可降级**（无 LLM 密钥走本地实现、无运行时返回结构化 `RUNTIME_NOT_FOUND`，前端置灰而非崩溃）；行级权限统一走 `core/scoping.py`。

## 10.1 能力分层（100 项）

| 层 | 名称 | 项数 | 覆盖范围 |
|---|---|---:|---|
| L1 | 编辑内核 | 22 | CodeMirror 6 编辑器、语法高亮、多语言、文件树、工作区、版本快照/diff/回滚、片段库、导入导出 |
| L2 | 执行沙箱 | 20 | 多语言执行、REPL、stdin/args/env、超时、标准输出/错误、执行历史与统计、清空、结果展示 |
| L3 | 智能化 | 22 | 静态分析 8（指标/大纲/复杂度/质量/流程图/相似度/密钥扫描/重构建议）+ AI 辅助 15（生成/转换/报错解释/正则/NL2SQL/学习路径/对话改码/行内补全/应用补丁/翻译/注释/优化/单测/摘要/状态） |
| L4 | 协作工程化 | 22 | 行评论与解决、协同状态与 WS、只读/可运行分享、zip 导出，以及 6 个工程化接口（blame / TODO 聚合 / diff / 洞察 / 贡献者 / 并排 diff） |
| L5 | 竞技教学 | 14 | 每日一题（今日/提交/历史）、成就徽章（列表/我的）、错题本（列表/收录/复习/删除）、学习路径（列表/生成/详情/勾选/删除）、竞技场（战力榜/随机挑战/提交）、学习总览 |

## 10.2 数据模型（15 张表，新增 app `code`）

**L1/L2 基础 9 张**：`CodeWorkspace`（代码工作区，含 owner/语言/星标/克隆源）、`CodeFile`（代码文件，含路径/语言/内容/收藏/排序/最后执行）、`CodeVersion`（文件版本快照，含序号/内容/摘要/创建者，`unique(file, version)`）、`CodeSnippet`（可复用代码片段 + 标签，支持从文件一键提取）、`CodeRun`（执行记录，含语言/代码/stdin/exit_code/stdout/stderr/duration/verdict）、`CodeCollabState`（协同状态，Yjs 文档快照 + 版本号）、`CodeJudgeTask`（判题任务，含多用例结果/通过数/耗时）、`CodeComment`（行级评论，含行号/内容/是否已解决）、`CodeShare`（分享链接，含 token/权限/过期/访问计数）。

**L5 教学 6 张**：`CodeDailyChallenge`（每日一题，`date` 唯一 + 标题/描述/语言/难度/模板/题解/测试用例/标签）、`CodeDailyRecord`（打卡记录，`unique(user, challenge)`，含通过用例数/耗时）、`CodeAchievement`（成就定义，`key` 唯一 + 规则 JSON + 层级 bronze/silver/gold）、`CodeUserAchievement`（用户成就进度，`unique(user, achievement)`）、`CodeWrongBook`（错题本，含来源/来源 ID/失败用例/掌握状态/复习次数）、`CodeLearningPath`（学习路径，含阶段 JSON/进度 JSON + `total_items` / `done_items` / `percent` 三个 property）。

> L3/L4 接口**零新模型**：静态分析、AI 辅助、blame、TODO、diff、洞察、贡献者全部复用既有 9 张表计算得出。

## 10.3 接口清单（104 登录接口 + 2 公开接口）

路由定义在 `code/urls.py`，采用 `SUBSYSTEMS`（供前端目录页渲染）+ `VIEWS`（路由串 → 视图函数显式映射，避免手写 path 出错）双表结构，结尾 `_EXPECTED = 110` **契约断言**防止无声破坏。

| 子系统 | 接口 | 说明 |
|---|---:|---|
| meta 元信息 | 4 | catalog / runtimes / languages / templates |
| workspace 工作区 | 5 | 列表 / 创建 / 详情 / 星标 / 克隆（+ update / delete 走 VIEWS） |
| file 代码文件 | 8 | 列表 / 创建 / 详情 / 收藏 / 读取入口 / 移动 / 批量 / 树 |
| version 版本历史 | 5 | 列表 / 创建快照 / 差异对比 / 回滚 / 删除 |
| run 安全执行 | 7 | 执行 / REPL / 历史 / 详情 / 删除 / 清空 / 统计 |
| judge 判题 | 4 | 判题 / 历史 / 详情 / 排行榜 |
| snippet 片段库 | 6 | 列表 / 创建 / 详情 / 复制 / 标签 / 从文件提取 |
| analyze 静态分析 | 8 | 指标 / 大纲 / 复杂度 / 质量 / 流程图 / 相似度 / 密钥扫描 / 重构建议 |
| ai 智能辅助 | 15 | 状态 / 生成 / 转换 / 报错解释 / 正则 / NL2SQL / 学习路径 / 对话改码 / 行内补全 / 应用补丁 · **翻译 / 注释 / 优化 / 单测 / 摘要** |
| collab 协作 | 6 | 评论列表 / 发评论 / 解决 / 删除 / 协同状态 / WS 信息 |
| share 分享 | 4 | 列表 / 创建 / 更新 / 吊销 |
| export 导出 | 2 | zip 打包 / 单文件下载 |
| daily 每日一题 | 3 | 今日题目 / 提交 / 打卡历史 |
| achievement 成就徽章 | 2 | 徽章列表 / 我的进度 |
| wrongbook 错题本 | 4 | 列表 / 收录 / 复习 / 删除 |
| learnpath 学习路径 | 5 | 列表 / 生成 / 详情 / 勾选进度 / 删除 |
| arena 竞技场 | 3 | 战力榜 / 随机挑战 / 提交 |
| learn 学习总览 | 1 | 个人学习看板聚合 |
| engineering 工程化 | 6 | blame / TODO 聚合 / diff / 洞察 / 贡献者 / 并排 diff |
| **合计** | **104** | |

**公开接口（无需登录，挂 `/api/share/code/<token>/`）**：
- `GET /share/code/<token>/`：只读查看分享的代码（含语言、内容、展示元信息）。
- `POST /share/code/<token>/run/`：**只跑分享内容本身**——不允许请求体覆盖代码绕过高危扫描，超时硬限 10s，不落 `CodeRun` 表，防匿名刷库。

## 10.4 编辑器内核（CodeMirror 6）

- **5 个 Compartment 动态重配**：语言 / 主题 / 缩进 / 字体 / 键位图各自独立 compartment，改任一设置只重配对应部分、不重建编辑器，光标与滚动位置不丢。
- **按需异步加载语言包**：语言包走动态 `import()`，切语言时才拉对应 chunk（构建产物中 code 相关 chunk 426.87 kB / gzip 138.87 kB，独立成块不拖累首屏）。
- **可热切换项**：主题、缩进（空格/Tab + 宽度）、字号/行高/字族、自动换行、括号配对、行号、活跃行高亮、vim 键位。
- **跳转与定位**：`editorRef.goToLine(n)` 供 TODO 面板点击直达源码行（配合 `nextTick` 等编辑器挂载完成）。

## 10.5 执行沙箱与静态分析（`code/runtime.py`）

- **进程级隔离**：`subprocess.Popen(shell=False)`（杜绝 shell 注入）+ 独立临时目录 + 环境变量**白名单**（不透传宿主环境）+ `communicate(timeout)` 到点强杀 + POSIX 下 `resource.setrlimit` 限内存与 CPU；Windows 无 `resource` 模块时**自动降级**为纯超时约束。
- **可降级适配器**：语言运行时未安装时返回结构化 `RUNTIME_NOT_FOUND`（附安装提示），而非抛异常；`allow_dangerous` 开关控制高危能力，默认关闭。
- **恒返回 dict**：`run_code(...)` 无论成功失败都返回统一结构，上游无需 try/except 分支。
- **静态分析纯 Python 实现**：`analyze_metrics()`（函数/类/行数/注释率）、`to_flow_nodes()`（返回 `{nodes, edges}` 用于流程图渲染）、复杂度估算、代码质量评分、`secret-scan`（密钥/凭据模式扫描）、`refactor-hints`（可读性/重复/长度提示），**不依赖任何第三方分析库**。

## 10.6 L4 工程化实现要点

- **blame（代码归属）**：沿版本链**正序**逐版跑 `difflib.SequenceMatcher` diff，把每行的归属累积到 `ownership[j] = {author, version_id, at}`——谁最后动这行就是谁。
- **todos（TODO 聚合）**：8 类标记（`TODO` / `FIXME` / `HACK` / `XXX` / `BUG` / `OPTIMIZE` / `REVIEW` / `NOTE`）按严重度分级（high: FIXME·BUG / medium: TODO·HACK·XXX / low: OPTIMIZE·REVIEW / info: NOTE），支持 `level` 排序 + `by_tag` / `by_file` 双维度分组，点击直达源码行。
- **diff**：三种模式自适应 —— `{file, v1, v2}`（版本间）/ `{file, version}`（版本对当前）/ `{file_a, file_b}`（跨文件），输出结构化 hunks + unified 文本。
- **insights（工程洞察）**：语言占比 + 目录分布 + 30 天活跃度 + 执行成功率 + **健康度评分**（4 条扣分规则：无版本快照、TODO 堆积、执行失败率高、长期未活动）。
- **contributors**：按版本创建者聚合贡献量。
- **side-by-side**：行号对齐的并排 diff，前端可直接双栏渲染。

## 10.7 L5 竞技教学实现要点

- **每日一题（确定性轮换）**：内置 7 道题（两数之和 / 斐波那契 / 回文串 / 数组最大值 / 括号匹配 / 去重排序 / 质数筛），`idx = day.toordinal() % len(_FALLBACK_PROBLEMS)` —— **不落定时任务，全员同日同题**，访问即 `_ensure_daily()` 补建当日题目。
- **打卡与连续天数**：`_daily_streak(user)` 按打卡记录回溯计算连续天数；提交未通过自动写入错题本（`get_or_create(user, source="daily", source_id=ch.id, ...)`，幂等不重复）。
- **成就徽章（惰性结算）**：14 个内置徽章，**不用 Celery / 定时任务**——用户访问时 `check_achievements(user)` 现算 9 项指标（文件数/执行数/通过数/连续打卡/片段数/工作区数/错题复习数/路径完成度/分享数），命中规则即解锁并写入 `unlocked_at`，返回本次新解锁列表供前端弹窗。
- **学习路径**：按语言给内置模板（python / js / java）+ 通用兜底，难度调节系数 `_LEVEL_ADJUST`（beginner 1.0 / intermediate 0.6 / advanced 0.3）控制阶段条目量；`_parse_stages(raw)` 兼容 LLM 返回的多种结构，解析失败自动回落本地模板。
- **竞技场**：`arena_board` 战力榜（按判题通过数 & 执行成功率综合排序）+ `arena_challenge` 随机抽题 + `arena_submit` 复用与判题**同一个核心**。
- **判题核心抽成纯函数**：`run_judge(language, code, cases, timeout=5, ignore_ws=True)` —— 只跑代码 + 比对，**不落库**，返回 `(verdict, passed, results, total_ms)`。普通判题 / 每日一题 / 竞技场三处共用，杜绝逻辑分叉。

## 10.8 前端接入（新增 3 个页面，总 29→32 个）

- **`views/code/CodeForge.vue`（代码工坊，~1700 行）**：三栏布局 = 工作区/文件树 → CodeMirror 编辑器（多标签页）→ 执行输出/AI 面板；顶栏含运行 / 判题 / 设置 / `📌 TODO` / `📈 洞察` / `🏅 学习` 入口；内含 TODO 聚合面板（760px）与工程洞察面板两个模态框；行评论、协同、分享、导出、片段库全部在此收口。
- **`views/code/LearnCenter.vue`（代码学习中心，新增）**：6 个标签页 = 总览 / 每日一题 / 成就 / 错题本 / 学习路径 / 竞技场；`switchTab(k)` **惰性加载** + `loaded` ref 防重复请求；含生成学习路径模态框。路由 `/code/learn`。
- **`views/code/SharedCode.vue`（分享代码，公开页）**：无需登录，`/share/code/:token`；只读展示 + 可直接试跑（请求只传 `stdin`，代码由服务端按 token 取，防止篡改）。
- **路由与导航**：`/code`（代码工坊）与 `/code/learn`（代码学习中心）挂登录内；`/share/code/:token` 为顶层公开路由（`meta: { public: true }`）；侧边栏新增「🧑‍💻 代码工坊」「🏅 代码学习中心」两个入口。
- **API 层**：`src/api/code.js` 新增 24 个方法（含 2 个公开接口），统一 `RUN_TIMEOUT = 60000`、`AI_TIMEOUT = 180000`（走大模型的接口单独放宽，避免前端先于后端超时）。

## 10.9 v6 验证结果（2026-09-19）

- `manage.py check` → **System check identified no issues (0 silenced)**；`code` 迁移 `0002_codeachievement_...` **Applying ... OK**。
- 后端 **10 个源文件 AST 解析全部 OK**；`code/urls.py` 路由断言 `104 == _EXPECTED` 通过，`public_urlpatterns` = 2。
- 前端 `vite build` → **✓ built in 5.93s**：`LearnCenter-VxkeE5-6.js` 26.60 kB（gzip 8.58）、`CodeForge-BMXZQVUr.js` 65.58 kB（gzip 19.78）、CodeMirror 相关 chunk 426.87 kB（gzip 138.87）。
- **未覆盖的验证**：`manage.py test code` / `code_smoke_test.py` / 启动 Daphne 做端到端，在当前开发机上被安全策略拦截，**运行时行为改由人工验收**。这是 v6 目前唯一的验证缺口。

## 10.10 v6 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `CODE_RUN_TIMEOUT` | 单次代码执行超时（秒） | 5 |
| `CODE_MAX_OUTPUT` | 标准输出截断上限（字符） | 20000 |
| `CODE_ALLOW_DANGEROUS` | 是否允许高危执行能力 | `False` |
| `LLM_API_KEY` 等 | 复用 v4 的 LLM 配置；未设置则 AI 全部本地降级 | 空 |



---

# 十一、v7 新增：100 项模块增强 + 374 个迷你工具（2026-09-25）

> v7.0：落地《可快速落地的100项功能清单》全部 100 项模块增强，覆盖 11 个模块。
> v7.1：新建独立 app minitools，目录驱动 catalog + 纯函数 run，批量落地 320 个纯函数工具（19 大家族），前端复用 DomainExplorer 动态渲染。
> **v8（2026-10-01）在此基础上再扩 7 个家族 54 个工具 → 26 家族 374 工具 / 375 条路由，见 docs/12。**

## 11.1 minitools 迷你工具箱（374 工具 · 26 家族 · 375 URL）

独立 Django app minitools，挂载 /api/minitools/，全部无状态纯函数，不落库不调外部 API。前端 DomainExplorer 一份组件驱动。

v7.0 首批 210 工具（9 家族）：text(30) / num(28) / encode(25) / date(22) / color(18) / gen(25) / validate(22) / convert(22) / fun(18)
v7.1 追加 110 工具（10 新家族，已与 devtools/dataintel/officesuite/tools 去重）：finance(16) / health(12) / geo(10) / security(10) / algo(13) / science(13) / tx(10) / biz(10) / fmt(8) / funx(8)

工程规约：复用 devtools/common.py endpoint 装饰器（ValueError→400、其余→422，绝不500）；urls.py 契约断言 == 321；零第三方依赖。

## 11.2 百项模块增强（100 项，11 模块）

| 模块 | 项数 | 关键交付 |
|---|---:|---|
| 文件中心 #1-12 | 12 | FileTag模型+M2M标签、分片进度、文件夹模板、EXIF、到期清理、收藏分组、批量重命名、类型图标、空格预览 |
| 笔记知识库 #13-24 | 12 | is_archived归档、AI大纲(本地降级)、批量导入MD、闪卡、阅读统计、双链补全、模板插入、版本差异高亮、标签云 |
| 项目看板 #25-36 | 12 | 卡片标签、逾期提醒、模板库、SVG燃尽图、只读分享、筛选/紧凑视图/逾期高亮/子任务进度条/主题/复制/分组 |
| 即时消息 #37-47 | 11 | 引用回复、消息置顶、会话归档、JSON导出、快捷回复、关键词提醒、代码高亮、搜索筛选、已读回执、emoji |
| 账号个人 #48-57 | 10 | Badge/InviteCode/ActiveSession三模型、在线状态、密码强度、安全日志、邀请注册、头像裁剪、设备管理、主题 |
| 智能搜索 #58-66 | 9 | 全局命令面板(Ctrl+K)、AI自动标签、每日摘要、写作润色、代码评审、搜索历史热词、条件记忆、CSV导出 |
| 管理后台 #67-74 | 8 | DRF限流、备份恢复命令、日志筛选、公告定时发布、在线用户、存储TOP、已读导出、权限搜索 |
| 代码工坊 #75-82 | 8 | 质量报告SVG、片段筛选、模板插入、主题字号切换、执行统计、判题耗时、导出命名规范、快捷键面板 |
| 学习中心 #83-88 | 6 | 学习日历、掌握度雷达/热力图、时长看板、错题复习、进度徽章、每日一题历史 |
| 办公套件 #89-93 | 5 | ICS导出、待办IM提醒、工单筛选、行动项转待办、值班周视图 |
| 平台体验 #94-100 | 7 | 性能监控P50/P95、统一时区、错误码目录、快捷入口、免打扰、骨架屏、品牌定制 |

## 11.3 新增数据表与接口

新增约 12 张表：FileTag、CardLabel、BoardShare、QuickReply、KeywordAlert、Badge、InviteCode、ActiveSession、SearchQueryLog；新增字段若干（Note.is_archived、Message.reply_to/is_pinned、Conversation.is_archived、User.tags/dnd、Announcement.scheduled_at/expires_at、FileMeta.tags/favorite_group）。

新增接口：minitools 375（含 catalog）+ files 7 + notes 5 + projects 6 + im 8 + accounts 10 + core 6 + assistant 3 + code 1 + officesuite 17（v5 的 233 → 250）。code 路由断言已到 110（`code/urls.py::_EXPECTED`），minitools 断言 375。

## 11.4 v7 验证结果（2026-09-25 全绿）

| 检查项 | 结果 |
|---|---|
| manage.py check | 0 issues |
| 迁移 | 全部已应用，无待执行 |
| v2 smoke_test.py | 160 通过 / 0 失败 |
| v3 learning_smoke | 80 通过 / 0 失败 |
| v4 extensions_smoke | 78 通过 / 0 失败 |
| v5 suite_smoke | 537 通过 / 0 失败 |
| minitools v7 smoke | catalog 19子系统/321接口，32/32工具通过 |
| minitools v7.1 smoke | 99/99新工具通过，无500 |
| npm run build | 成功（3.87s） |
| 后端总URL数 | 1518（`scripts/stats.py` 口径：路由叶子，不含 Django admin；v7 时手数为 1707，含重复计数） |

说明：冒烟全部串行执行；admin密码曾漂移已重置为admin123；ECharts未安装，图表改用SVG；#86/#91/#93为部分实现，核心接口就绪。

## 11.5 设计文档
- docs/10-可快速落地的100项功能清单.md
- docs/11-新增200+简单功能设计清单.md（含v7.1追加110项章节）
