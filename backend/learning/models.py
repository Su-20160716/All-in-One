"""学习中心模型：学习进度、代码片段收藏、生词本、错题本、专注记录、学习计划。
均为用户私有数据，与既有业务模块解耦。
"""
from django.conf import settings
from django.db import models


class LearningProgress(models.Model):
    """学习进度：domain=programming 时 target_key 为语言 key；为 school 时为 学段.学科"""

    DOMAINS = [("programming", "编程"), ("school", "学科"), ("tool", "工具")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_progress", verbose_name="用户")
    domain = models.CharField(max_length=20, choices=DOMAINS, default="programming", verbose_name="领域")
    target_key = models.CharField(max_length=64, verbose_name="目标标识")
    target_name = models.CharField(max_length=128, blank=True, verbose_name="目标名称")
    status = models.CharField(max_length=20, default="learning", verbose_name="状态")  # learning/finished
    percent = models.PositiveSmallIntegerField(default=0, verbose_name="完成度%")
    note = models.CharField(max_length=255, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "学习进度"
        verbose_name_plural = "学习进度"
        unique_together = [("owner", "domain", "target_key")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.owner_id}-{self.domain}:{self.target_key} {self.percent}%"


class SnippetBookmark(models.Model):
    """收藏的编程代码片段"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="snippet_bookmarks", verbose_name="用户")
    language = models.CharField(max_length=20, verbose_name="语言key")
    title = models.CharField(max_length=128, verbose_name="标题")
    code = models.TextField(blank=True, verbose_name="代码")
    note = models.CharField(max_length=255, blank=True, verbose_name="笔记")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="收藏时间")

    class Meta:
        verbose_name = "代码收藏"
        verbose_name_plural = "代码收藏"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class WordbookItem(models.Model):
    """英语生词本"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wordbook", verbose_name="用户")
    word = models.CharField(max_length=64, verbose_name="单词")
    phonetic = models.CharField(max_length=48, blank=True, verbose_name="音标")
    meaning = models.CharField(max_length=255, blank=True, verbose_name="释义")
    mastered = models.BooleanField(default=False, verbose_name="已掌握")
    source = models.CharField(max_length=20, default="manual", verbose_name="来源")  # manual/dictation（F531）
    last_reviewed = models.DateField(null=True, blank=True, verbose_name="最近复习日")  # F521 艾宾浩斯
    review_count = models.PositiveIntegerField(default=0, verbose_name="复习次数")  # F521
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="加入时间")

    class Meta:
        verbose_name = "生词本"
        verbose_name_plural = "生词本"
        unique_together = [("owner", "word")]
        ordering = ["-created_at"]

    def __str__(self):
        return self.word


class MistakeRecord(models.Model):
    """错题本"""

    TYPES = [("single", "单选"), ("judge", "判断"), ("fill", "填空"), ("output", "读程序"), ("other", "其它")]
    # F545 错因归类（豆包/dsh 2026-10-01）
    CAUSES = [("reading", "审题不清"), ("concept", "概念不清"), ("calc", "计算失误"), ("careless", "粗心笔误"), ("other", "其它")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mistakes", verbose_name="用户")
    stage = models.CharField(max_length=20, blank=True, verbose_name="学段")
    subject = models.CharField(max_length=20, blank=True, verbose_name="学科")
    question_type = models.CharField(max_length=20, choices=TYPES, default="single", verbose_name="题型")
    difficulty = models.PositiveSmallIntegerField(default=1, verbose_name="难度")
    stem = models.TextField(verbose_name="题干")
    answer = models.CharField(max_length=255, blank=True, verbose_name="正确答案")
    user_answer = models.CharField(max_length=255, blank=True, verbose_name="我的答案")
    analysis = models.TextField(blank=True, verbose_name="解析")
    mastered = models.BooleanField(default=False, verbose_name="已订正掌握")
    last_reviewed = models.DateField(null=True, blank=True, verbose_name="最近复习日")  # F520/F521
    redrill_attempts = models.PositiveIntegerField(default=0, verbose_name="二刷次数")  # F520
    redrill_correct = models.PositiveIntegerField(default=0, verbose_name="二刷答对次数")  # F520
    cause = models.CharField(max_length=20, blank=True, default="", verbose_name="错因")  # F545
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="加入时间")

    class Meta:
        verbose_name = "错题本"
        verbose_name_plural = "错题本"
        ordering = ["-created_at"]

    def __str__(self):
        return self.stem[:20]


class StudySession(models.Model):
    """专注/学习记录（番茄钟打卡）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_sessions", verbose_name="用户")
    subject = models.CharField(max_length=40, default="通用", verbose_name="科目/主题")
    minutes = models.PositiveIntegerField(default=25, verbose_name="时长(分钟)")
    study_date = models.DateField(verbose_name="日期")
    note = models.CharField(max_length=255, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        verbose_name = "专注记录"
        verbose_name_plural = "专注记录"
        ordering = ["-study_date", "-created_at"]

    def __str__(self):
        return f"{self.subject} {self.minutes}分钟"


class StudyPlan(models.Model):
    """学习计划"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_plans", verbose_name="用户")
    title = models.CharField(max_length=128, verbose_name="计划名称")
    subject = models.CharField(max_length=40, blank=True, verbose_name="科目")
    total = models.PositiveIntegerField(default=0, verbose_name="总任务量")
    days = models.PositiveIntegerField(default=7, verbose_name="天数")
    plan = models.JSONField(default=list, blank=True, verbose_name="每日安排")
    finished = models.PositiveIntegerField(default=0, verbose_name="已完成")
    start_date = models.DateField(verbose_name="开始日期")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "学习计划"
        verbose_name_plural = "学习计划"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


# ============================================================
# v8 学习区新增能力（dsh 2026-10-01，F523–F540/F545）
# 均为用户私有数据、与既有模块解耦；只增不改。
# ============================================================


class DailyGoal(models.Model):
    """F523 每日学习目标与达成率（每人一条）"""

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="daily_goal", verbose_name="用户")
    target_minutes = models.PositiveIntegerField(default=30, verbose_name="每日目标(分钟)")
    note = models.CharField(max_length=255, blank=True, verbose_name="备注")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "每日学习目标"
        verbose_name_plural = "每日学习目标"

    def __str__(self):
        return f"{self.owner_id}: {self.target_minutes}min"


class QuestionSet(models.Model):
    """F525 自定义题单（收藏题目成组练习）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="question_sets", verbose_name="用户")
    name = models.CharField(max_length=128, verbose_name="题单名称")
    question_ids = models.JSONField(default=list, blank=True, verbose_name="题目 ID 列表")
    note = models.CharField(max_length=255, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "自定义题单"
        verbose_name_plural = "自定义题单"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class MasteryRating(models.Model):
    """F526 知识点掌握度自评（1–5 星）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mastery_ratings", verbose_name="用户")
    stage_subject = models.CharField(max_length=64, verbose_name="学段.学科")
    point = models.CharField(max_length=128, verbose_name="知识点")
    stars = models.PositiveSmallIntegerField(default=3, verbose_name="自评星级")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "知识点自评"
        verbose_name_plural = "知识点自评"
        unique_together = [("owner", "stage_subject", "point")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.point} {self.stars}★"


class FormulaFavorite(models.Model):
    """F532 公式收藏夹"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="formula_favorites", verbose_name="用户")
    formula_key = models.CharField(max_length=64, verbose_name="公式 key")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="收藏时间")

    class Meta:
        verbose_name = "公式收藏"
        verbose_name_plural = "公式收藏"
        unique_together = [("owner", "formula_key")]
        ordering = ["-created_at"]

    def __str__(self):
        return self.formula_key


class QuestionFavorite(models.Model):
    """F536 题目收藏（加星筛选）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="question_favorites", verbose_name="用户")
    question_id = models.CharField(max_length=64, verbose_name="题目 ID")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="收藏时间")

    class Meta:
        verbose_name = "题目收藏"
        verbose_name_plural = "题目收藏"
        unique_together = [("owner", "question_id")]
        ordering = ["-created_at"]

    def __str__(self):
        return self.question_id


class PaperArchive(models.Model):
    """F537 组卷结果存档（保存后可重做）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="paper_archives", verbose_name="用户")
    title = models.CharField(max_length=128, verbose_name="试卷名称")
    stage = models.CharField(max_length=20, blank=True, verbose_name="学段")
    subject = models.CharField(max_length=20, blank=True, verbose_name="学科")
    payload = models.JSONField(default=dict, blank=True, verbose_name="试卷内容")
    total = models.PositiveIntegerField(default=0, verbose_name="题量")
    last_score = models.PositiveIntegerField(default=0, verbose_name="最近得分")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "试卷存档"
        verbose_name_plural = "试卷存档"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ToolUsageLog(models.Model):
    """F538 学习工具使用历史（最近用过可快速重开）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="tool_usage", verbose_name="用户")
    tool_key = models.CharField(max_length=64, verbose_name="工具 key")
    used_at = models.DateTimeField(auto_now_add=True, verbose_name="使用时间")

    class Meta:
        verbose_name = "工具使用记录"
        verbose_name_plural = "工具使用记录"
        ordering = ["-used_at"]

    def __str__(self):
        return self.tool_key


class LearningBadge(models.Model):
    """F540 学习中心徽章（区别于代码工坊成就）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="learning_badges", verbose_name="用户")
    code = models.CharField(max_length=40, verbose_name="徽章代码")
    unlocked_at = models.DateTimeField(auto_now_add=True, verbose_name="解锁时间")

    class Meta:
        verbose_name = "学习徽章"
        verbose_name_plural = "学习徽章"
        unique_together = [("owner", "code")]
        ordering = ["-unlocked_at"]

    def __str__(self):
        return self.code


class IdiomChainRecord(models.Model):
    """F529 成语接龙战绩（难度分级）"""

    LEVELS = [("easy", "简单"), ("normal", "普通"), ("hard", "困难")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="idiom_chains", verbose_name="用户")
    length = models.PositiveIntegerField(default=0, verbose_name="连成链长")
    difficulty = models.CharField(max_length=10, choices=LEVELS, default="normal", verbose_name="难度")
    chain = models.JSONField(default=list, blank=True, verbose_name="成语链")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        verbose_name = "成语接龙战绩"
        verbose_name_plural = "成语接龙战绩"
        ordering = ["-length", "-created_at"]

    def __str__(self):
        return f"{self.length} 连"
