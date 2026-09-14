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
