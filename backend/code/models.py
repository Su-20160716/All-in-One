# -*- coding: utf-8 -*-
"""代码工坊模型。

对外键与字段命名均沿用项目既有风格（owner / created_at / updated_at），
以便直接接入 `core.scoping.scope_queryset` 的行级权限体系。
"""
import uuid

from django.conf import settings
from django.db import models


class CodeWorkspace(models.Model):
    """代码工作区：一组代码文件的容器（相当于一个轻量工程/项目）"""

    name = models.CharField(max_length=120, verbose_name="工作区名")
    description = models.TextField(blank=True, verbose_name="描述")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_workspaces",
        verbose_name="所有者",
    )
    language = models.CharField(max_length=32, default="python", verbose_name="主语言")
    icon = models.CharField(max_length=16, default="📁", verbose_name="图标")
    color = models.CharField(max_length=16, default="brand", verbose_name="配色")
    is_starred = models.BooleanField(default=False, verbose_name="星标")
    is_archived = models.BooleanField(default=False, verbose_name="已归档")
    # 运行配置预设：{"language": "python", "entry": "main.py", "args": [], "stdin": "", "timeout": 5}
    run_config = models.JSONField(default=dict, blank=True, verbose_name="运行配置预设")
    # 环境变量注入（第 84 条：密钥注入）—— 仅存键名与脱敏值，明文不落库
    env_keys = models.JSONField(default=list, blank=True, verbose_name="环境变量键名")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "代码工作区"
        verbose_name_plural = "代码工作区"
        ordering = ["-is_starred", "-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.name

    @property
    def file_count(self):
        return self.files.count()

    @property
    def total_bytes(self):
        agg = self.files.aggregate(total=models.Sum("size"))
        return agg["total"] or 0


class CodeFile(models.Model):
    """代码文件：一个可编辑、可运行、可版本化的源码文件。"""

    workspace = models.ForeignKey(
        CodeWorkspace,
        on_delete=models.CASCADE,
        related_name="files",
        verbose_name="所属工作区",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_files",
        verbose_name="所有者",
    )
    # 相对路径，支持 a/b/c.py 形式的多级目录（第 77 条：多文件树）
    path = models.CharField(max_length=400, verbose_name="相对路径")
    name = models.CharField(max_length=200, verbose_name="文件名")
    language = models.CharField(max_length=32, default="python", verbose_name="语言")
    content = models.TextField(blank=True, verbose_name="源码")
    size = models.IntegerField(default=0, verbose_name="字节数")
    lines = models.IntegerField(default=0, verbose_name="行数")
    is_entry = models.BooleanField(default=False, verbose_name="是否为入口文件")
    is_favorite = models.BooleanField(default=False, verbose_name="收藏")
    order = models.IntegerField(default=0, verbose_name="排序")
    # 编辑器本地状态（光标、折叠、滚动位置等），多端同步用
    editor_state = models.JSONField(default=dict, blank=True, verbose_name="编辑器状态")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "代码文件"
        verbose_name_plural = "代码文件"
        ordering = ["order", "path"]
        unique_together = [("workspace", "path")]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.path

    def save(self, *args, **kwargs):
        """保存时自动统计字节数/行数，避免各处重复计算。"""
        if self.content is None:
            self.content = ""
        self.size = len(self.content.encode("utf-8"))
        self.lines = self.content.count("\n") + 1 if self.content else 0
        if not self.name:
            self.name = self.path.rsplit("/", 1)[-1]
        super().save(*args, **kwargs)


class CodeVersion(models.Model):
    """代码版本快照：支持 diff 与回滚（照抄 NoteVersion 模式）。"""

    file = models.ForeignKey(
        CodeFile,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="所属文件",
    )
    content = models.TextField(verbose_name="快照内容")
    message = models.CharField(max_length=200, blank=True, verbose_name="版本说明")
    size = models.IntegerField(default=0, verbose_name="字节数")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="code_versions",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "代码版本"
        verbose_name_plural = "代码版本"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file.path} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class CodeSnippet(models.Model):
    """代码片段知识库：可复用、可检索、可打标签的小段代码。"""

    title = models.CharField(max_length=200, verbose_name="标题")
    description = models.TextField(blank=True, verbose_name="描述")
    language = models.CharField(max_length=32, default="python", verbose_name="语言")
    code = models.TextField(verbose_name="代码")
    tags = models.JSONField(default=list, blank=True, verbose_name="标签")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_snippets",
        verbose_name="所有者",
    )
    scope = models.CharField(
        max_length=16,
        default="private",
        choices=[("private", "私有"), ("team", "团队可见"), ("public", "公开")],
        verbose_name="可见范围",
    )
    # F669 片段收藏夹分组：收藏后可归入分组，按组筛选（纯新增，可为空）
    folder = models.CharField(max_length=60, blank=True, default="", verbose_name="收藏夹分组")
    is_favorite = models.BooleanField(default=False, verbose_name="收藏")
    copy_count = models.IntegerField(default=0, verbose_name="被复制次数")
    use_count = models.IntegerField(default=0, verbose_name="被引用次数")
    source_url = models.CharField(max_length=500, blank=True, verbose_name="来源")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "代码片段"
        verbose_name_plural = "代码片段"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.title


class CodeRunPreset(models.Model):
    """F676 运行参数预设：按语言保存 stdin / 命令行参数 / 超时。

    每个用户每语言可存多条命名预设，运行时前端选中后随 /run/ 一起提交。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_run_presets",
        verbose_name="所有者",
    )
    language = models.CharField(max_length=32, default="python", verbose_name="语言")
    name = models.CharField(max_length=120, default="默认预设", verbose_name="预设名")
    stdin = models.TextField(blank=True, verbose_name="标准输入")
    args = models.JSONField(default=list, blank=True, verbose_name="命令行参数")
    timeout = models.FloatField(default=5.0, verbose_name="超时秒数")
    is_default = models.BooleanField(default=False, verbose_name="该语言默认预设")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "运行参数预设"
        verbose_name_plural = "运行参数预设"
        ordering = ["-is_default", "-updated_at"]
        indexes = [models.Index(fields=["owner", "language"])]

    def __str__(self):
        return f"{self.language}:{self.name}"


class CodeRun(models.Model):
    """运行记录：每次执行落库，支撑运行历史、热力图、统计（第 25/33/34/100 条）。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_runs",
        verbose_name="执行者",
    )
    file = models.ForeignKey(
        CodeFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
        verbose_name="来源文件",
    )
    workspace = models.ForeignKey(
        CodeWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
        verbose_name="来源工作区",
    )
    language = models.CharField(max_length=32, verbose_name="语言")
    source_code = models.TextField(blank=True, verbose_name="提交的源码")
    stdin = models.TextField(blank=True, verbose_name="标准输入")
    stdout = models.TextField(blank=True, verbose_name="标准输出")
    stderr = models.TextField(blank=True, verbose_name="标准错误")
    exit_code = models.IntegerField(default=0, verbose_name="退出码")
    signal_name = models.CharField(max_length=32, blank=True, verbose_name="终止信号")
    status = models.CharField(
        max_length=16,
        default="ok",
        choices=[
            ("ok", "成功"),
            ("error", "运行错误"),
            ("timeout", "超时"),
            ("memory", "内存超限"),
            ("rejected", "被拦截"),
            ("unavailable", "环境不可用"),
        ],
        verbose_name="状态",
    )
    duration_ms = models.IntegerField(default=0, verbose_name="耗时(ms)")
    memory_kb = models.IntegerField(default=0, verbose_name="峰值内存(KB)")
    truncated = models.BooleanField(default=False, verbose_name="输出被截断")
    # 结构化诊断（第 36/37 条）：编译错误、traceback 帧
    diagnostics = models.JSONField(default=list, blank=True, verbose_name="结构化诊断")
    artifacts = models.JSONField(default=list, blank=True, verbose_name="产物文件")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "运行记录"
        verbose_name_plural = "运行记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["owner", "language"]),
        ]

    def __str__(self):
        return f"{self.language} · {self.status} · {self.duration_ms}ms"


class CodeCollabState(models.Model):
    """代码文件协同状态（照抄 NoteCollabState，第 68/69 条）。

    服务端不做 CRDT 合并，只做「快照 + 增量日志」的持久化中继。
    """

    file = models.OneToOneField(
        CodeFile,
        on_delete=models.CASCADE,
        related_name="collab",
        verbose_name="代码文件",
    )
    snapshot = models.BinaryField(null=True, blank=True, verbose_name="Yjs 快照")
    update_log = models.JSONField(default=list, blank=True, verbose_name="增量日志")
    revision = models.IntegerField(default=0, verbose_name="修订号")
    text_mirror = models.TextField(blank=True, verbose_name="文本镜像")
    contributors = models.JSONField(default=list, blank=True, verbose_name="贡献者")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "代码协同状态"
        verbose_name_plural = "代码协同状态"

    def __str__(self):
        return f"collab:{self.file.path}"


class CodeJudgeTask(models.Model):
    """判题任务（第 87–90 条 OJ 简化版）。

    不依赖外部判题集群：用本机可用的运行时逐个用例跑，逐条判定。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_judge_tasks",
        verbose_name="提交者",
    )
    title = models.CharField(max_length=200, default="未命名题目", verbose_name="题目名")
    language = models.CharField(max_length=32, default="python", verbose_name="语言")
    source_code = models.TextField(verbose_name="提交代码")
    testcases = models.JSONField(default=list, verbose_name="测试用例 [{stdin, expected}]")
    results = models.JSONField(default=list, blank=True, verbose_name="逐用例结果")
    verdict = models.CharField(
        max_length=16,
        default="pending",
        choices=[
            ("pending", "等待中"),
            ("accepted", "通过"),
            ("wrong_answer", "答案错误"),
            ("time_limit", "超时"),
            ("runtime_error", "运行错误"),
            ("compile_error", "编译错误"),
            ("unavailable", "环境不可用"),
        ],
        verbose_name="判定结果",
    )
    passed = models.IntegerField(default=0, verbose_name="通过用例数")
    total = models.IntegerField(default=0, verbose_name="用例总数")
    duration_ms = models.IntegerField(default=0, verbose_name="总耗时(ms)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "判题任务"
        verbose_name_plural = "判题任务"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]

    def __str__(self):
        return f"{self.title} · {self.verdict} ({self.passed}/{self.total})"


class CodeComment(models.Model):
    """行级评论（第 71/72 条）：钉在某文件某一行上的讨论串。"""

    file = models.ForeignKey(
        CodeFile,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="代码文件",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_comments",
        verbose_name="作者",
    )
    line = models.IntegerField(default=1, verbose_name="行号")
    content = models.TextField(verbose_name="评论内容")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        verbose_name="父评论",
    )
    resolved = models.BooleanField(default=False, verbose_name="已解决")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "代码行评论"
        verbose_name_plural = "代码行评论"
        ordering = ["line", "created_at"]

    def __str__(self):
        return f"{self.file.path}:{self.line}"


class CodeShare(models.Model):
    """代码分享链接（第 73/74 条）：可设置只读/可运行、是否公开。"""

    token = models.CharField(max_length=48, unique=True, verbose_name="分享令牌")
    file = models.ForeignKey(
        CodeFile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shares",
        verbose_name="代码文件",
    )
    snippet = models.ForeignKey(
        CodeSnippet,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shares",
        verbose_name="代码片段",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_shares",
        verbose_name="创建者",
    )
    title = models.CharField(max_length=200, blank=True, verbose_name="展示标题")
    allow_run = models.BooleanField(default=False, verbose_name="允许访客运行")
    allow_download = models.BooleanField(default=True, verbose_name="允许下载")
    view_count = models.IntegerField(default=0, verbose_name="访问次数")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "代码分享"
        verbose_name_plural = "代码分享"
        ordering = ["-created_at"]

    def __str__(self):
        return self.token

    @staticmethod
    def new_token():
        return uuid.uuid4().hex[:24]


# ============================================================
# 五、竞技教学（L5 第 87~100 条）
# ============================================================


class CodeDailyChallenge(models.Model):
    """每日一题（第 90 条）。

    按日期唯一，题目内容由管理端或 AI 生成后落库；
    同一天的题对所有用户是同一道，保证可比性。
    """

    DIFFICULTY_CHOICES = [
        ("easy", "简单"),
        ("medium", "中等"),
        ("hard", "困难"),
    ]

    date = models.DateField(unique=True, verbose_name="日期")
    title = models.CharField(max_length=200, verbose_name="题目标题")
    description = models.TextField(blank=True, verbose_name="题目描述")
    language = models.CharField(max_length=32, default="python", verbose_name="语言")
    difficulty = models.CharField(
        max_length=16, default="easy", choices=DIFFICULTY_CHOICES, verbose_name="难度"
    )
    template = models.TextField(blank=True, verbose_name="初始代码模板")
    solution = models.TextField(blank=True, verbose_name="参考解法")
    # 测试用例：[{"input": "...", "output": "...", "hidden": false}]
    testcases = models.JSONField(default=list, blank=True, verbose_name="测试用例")
    tags = models.JSONField(default=list, blank=True, verbose_name="标签")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "每日一题"
        verbose_name_plural = "每日一题"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} {self.title}"


class CodeDailyRecord(models.Model):
    """每日一题答题记录（第 90 条配套）。

    每人每天每题一条，重复提交取最后一次结果（update_or_create）。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_daily_records",
        verbose_name="用户",
    )
    challenge = models.ForeignKey(
        CodeDailyChallenge,
        on_delete=models.CASCADE,
        related_name="records",
        verbose_name="题目",
    )
    code = models.TextField(blank=True, verbose_name="提交代码")
    passed = models.BooleanField(default=False, verbose_name="是否通过")
    passed_count = models.IntegerField(default=0, verbose_name="通过用例数")
    total_count = models.IntegerField(default=0, verbose_name="总用例数")
    duration_ms = models.IntegerField(default=0, verbose_name="耗时毫秒")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "每日一题记录"
        verbose_name_plural = "每日一题记录"
        unique_together = [("user", "challenge")]
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return f"{self.user_id}@{self.challenge_id}"


class CodeAchievement(models.Model):
    """成就徽章定义（第 92 条）。

    内置徽章在数据迁移时种子化；`key` 唯一，解锁逻辑按 key 分支。
    """

    key = models.CharField(max_length=64, unique=True, verbose_name="徽章标识")
    name = models.CharField(max_length=64, verbose_name="徽章名")
    description = models.CharField(max_length=200, blank=True, verbose_name="描述")
    icon = models.CharField(max_length=16, default="🏅", verbose_name="图标")
    # 解锁阈值：{"metric": "run_count", "value": 100}
    rule = models.JSONField(default=dict, blank=True, verbose_name="解锁规则")
    tier = models.CharField(max_length=16, default="bronze", verbose_name="等级")
    order = models.IntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "成就徽章"
        verbose_name_plural = "成就徽章"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.icon} {self.name}"


class CodeUserAchievement(models.Model):
    """用户已解锁的成就（第 92 条配套）。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_achievements",
        verbose_name="用户",
    )
    achievement = models.ForeignKey(
        CodeAchievement,
        on_delete=models.CASCADE,
        related_name="unlocks",
        verbose_name="徽章",
    )
    progress = models.IntegerField(default=0, verbose_name="当前进度")
    target = models.IntegerField(default=1, verbose_name="目标值")
    unlocked_at = models.DateTimeField(null=True, blank=True, verbose_name="解锁时间")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "用户成就"
        verbose_name_plural = "用户成就"
        unique_together = [("user", "achievement")]
        ordering = ["-unlocked_at", "-id"]

    def __str__(self):
        return f"{self.user_id}:{self.achievement.key}"


class CodeWrongBook(models.Model):
    """错题本（第 94 条）。

    判题/每日一题未通过时自动收入；支持手动标记已掌握。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_wrong_items",
        verbose_name="用户",
    )
    title = models.CharField(max_length=200, verbose_name="题目标题")
    language = models.CharField(max_length=32, default="python", verbose_name="语言")
    source_code = models.TextField(blank=True, verbose_name="当时提交的代码")
    # 关联来源：judge / daily / manual
    source = models.CharField(max_length=16, default="manual", verbose_name="来源")
    source_id = models.IntegerField(null=True, blank=True, verbose_name="来源记录 ID")
    reason = models.CharField(max_length=200, blank=True, verbose_name="错误原因")
    # 失败用例快照，便于复盘
    failed_cases = models.JSONField(default=list, blank=True, verbose_name="失败用例")
    mastered = models.BooleanField(default=False, verbose_name="已掌握")
    review_count = models.IntegerField(default=0, verbose_name="复习次数")
    last_reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="上次复习")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "代码错题本"
        verbose_name_plural = "代码错题本"
        ordering = ["mastered", "-updated_at"]
        indexes = [models.Index(fields=["user", "mastered", "-updated_at"])]

    def __str__(self):
        return self.title


class CodeLearningPath(models.Model):
    """学习路径（第 87/88 条）。

    由 AI 或本地模板生成的阶段化学习计划；每个阶段含若干任务，
    进度存 `progress`（已完成任务的索引列表）。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_learning_paths",
        verbose_name="用户",
    )
    title = models.CharField(max_length=200, verbose_name="路径标题")
    language = models.CharField(max_length=32, default="python", verbose_name="目标语言")
    level = models.CharField(max_length=16, default="beginner", verbose_name="起点水平")
    goal = models.CharField(max_length=200, blank=True, verbose_name="学习目标")
    # [{"stage": "基础语法", "items": ["变量与类型", "流程控制"], "hours": 6}]
    stages = models.JSONField(default=list, blank=True, verbose_name="阶段计划")
    # 已完成任务的稳定标识："0-1" = 第 0 阶段第 1 项
    progress = models.JSONField(default=list, blank=True, verbose_name="已完成项")
    is_active = models.BooleanField(default=True, verbose_name="进行中")
    source = models.CharField(max_length=16, default="local", verbose_name="生成来源")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "代码学习路径"
        verbose_name_plural = "代码学习路径"
        ordering = ["-is_active", "-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return self.title

    @property
    def total_items(self):
        return sum(len(s.get("items") or []) for s in (self.stages or []))

    @property
    def done_items(self):
        return len(self.progress or [])

    @property
    def percent(self):
        t = self.total_items
        return round(self.done_items * 100 / t) if t else 0
