"""AI 助手模型：会话、消息、AI 生成题目、调用日志

设计原则：AI 能力是**可选增强**。未配置 LLM_API_KEY 时系统自动降级为
本地抽取式实现（摘要/关键词/检索问答/启发式批改），记录里会标明 provider=local，
用户可随时补上 Key 切换到真实大模型，历史数据结构不变。
"""
from django.conf import settings
from django.db import models


class AIConversation(models.Model):
    """AI 对话（LLM 聊天助手）

    分支（F645）：一条回复可以「从这条分支新对话」——新会话记录父会话与父消息，
    两个字段都可空，老数据不受影响。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations", verbose_name="用户"
    )
    title = models.CharField(max_length=120, blank=True, verbose_name="标题")
    scene = models.CharField(max_length=32, default="chat", verbose_name="场景")
    parent_conversation = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="branches", verbose_name="父会话",
    )
    parent_message = models.ForeignKey(
        "AIMessage", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="branches", verbose_name="父消息",
    )
    model = models.CharField(max_length=64, blank=True, verbose_name="使用的模型")
    message_count = models.IntegerField(default=0, verbose_name="消息数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "AI 会话"
        verbose_name_plural = "AI 会话"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"会话#{self.id}"


class AIMessage(models.Model):
    ROLE_CHOICES = [("system", "系统"), ("user", "用户"), ("assistant", "助手")]

    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages", verbose_name="会话"
    )
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default="user", verbose_name="角色")
    content = models.TextField(verbose_name="内容")
    provider = models.CharField(max_length=20, blank=True, verbose_name="提供方")
    references = models.JSONField(default=list, blank=True, verbose_name="引用的笔记/文件")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "AI 消息"
        verbose_name_plural = "AI 消息"
        ordering = ["id"]

    def __str__(self):
        return f"{self.role}: {self.content[:30]}"


class AIGeneratedQuestion(models.Model):
    """AI 生成的练习题（可保存到个人题库，用于复习）"""

    TYPE_CHOICES = [("single", "单选"), ("judge", "判断"), ("fill", "填空"), ("subjective", "主观"), ("code", "编程")]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_questions", verbose_name="用户"
    )
    topic = models.CharField(max_length=120, verbose_name="知识点/主题")
    question_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="single", verbose_name="题型")
    difficulty = models.PositiveSmallIntegerField(default=2, verbose_name="难度1-5")
    stem = models.TextField(verbose_name="题干")
    options = models.JSONField(default=list, blank=True, verbose_name="选项")
    answer = models.TextField(blank=True, verbose_name="参考答案")
    analysis = models.TextField(blank=True, verbose_name="解析")
    source = models.CharField(max_length=16, default="local", verbose_name="来源(llm/bank/local)")
    provider = models.CharField(max_length=20, blank=True, verbose_name="提供方")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="生成时间")

    class Meta:
        verbose_name = "AI 生成题目"
        verbose_name_plural = "AI 生成题目"
        ordering = ["-created_at"]

    def __str__(self):
        return self.stem[:30]


class AIUsageLog(models.Model):
    """AI 调用日志（可观测性：成功/失败、耗时、降级情况）"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_usage", verbose_name="用户",
    )
    feature = models.CharField(max_length=32, verbose_name="功能")
    provider = models.CharField(max_length=20, blank=True, verbose_name="提供方")
    model = models.CharField(max_length=64, blank=True, verbose_name="模型")
    success = models.BooleanField(default=True, verbose_name="是否成功")
    prompt_chars = models.IntegerField(default=0, verbose_name="输入字符数")
    output_chars = models.IntegerField(default=0, verbose_name="输出字符数")
    duration_ms = models.IntegerField(default=0, verbose_name="耗时(ms)")
    error = models.CharField(max_length=255, blank=True, verbose_name="错误信息")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "AI 调用日志"
        verbose_name_plural = "AI 调用日志"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.feature} {self.provider} {'ok' if self.success else 'fail'}"


class AIPrompt(models.Model):
    """提示词库（F644）：收藏常用提示词，一键插入输入框

    内置提示词（is_builtin=True）在用户首次打开提示词库时按 owner 幂等补种，
    用户可自由修改/收藏/删除自己的副本。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_prompts", verbose_name="用户"
    )
    title = models.CharField(max_length=120, verbose_name="标题")
    content = models.TextField(verbose_name="提示词内容")
    category = models.CharField(max_length=32, default="自定义", verbose_name="分类")
    is_favorite = models.BooleanField(default=False, verbose_name="是否收藏")
    is_builtin = models.BooleanField(default=False, verbose_name="是否内置")
    usage_count = models.PositiveIntegerField(default=0, verbose_name="使用次数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "AI 提示词"
        verbose_name_plural = "AI 提示词"
        ordering = ["-is_favorite", "-updated_at"]

    def __str__(self):
        return f"{self.title} ({self.category})"
