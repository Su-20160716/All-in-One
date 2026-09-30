"""任务看板模型：项目、看板列、任务卡片、子任务、工时、评论、成员、活动"""
import uuid

from django.conf import settings
from django.db import models


class Project(models.Model):
    """项目（顶级容器）"""

    name = models.CharField(max_length=120, verbose_name="项目名")
    description = models.TextField(blank=True, verbose_name="描述")
    color = models.CharField(max_length=16, default="#0ea5e9", verbose_name="主题色")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_projects", verbose_name="创建者")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="projects", blank=True, verbose_name="成员")
    is_archived = models.BooleanField(default=False, verbose_name="已归档")
    is_star = models.BooleanField(default=False, verbose_name="收藏")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "项目"
        verbose_name_plural = "项目"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class Board(models.Model):
    """看板列（待办/进行中/完成…）"""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boards", verbose_name="项目")
    name = models.CharField(max_length=60, verbose_name="列名")
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "看板列"
        verbose_name_plural = "看板列"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.project.name} / {self.name}"


class TaskCard(models.Model):
    """任务卡片"""

    PRIORITY_CHOICES = [("low", "低"), ("medium", "中"), ("high", "高"), ("urgent", "紧急")]
    STATUS_CHOICES = [("todo", "待办"), ("doing", "进行中"), ("done", "已完成")]

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="cards", verbose_name="所在列")
    title = models.CharField(max_length=200, verbose_name="标题")
    description = models.TextField(blank=True, verbose_name="描述")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium", verbose_name="优先级")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="todo", verbose_name="状态")
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="task_cards", blank=True, verbose_name="负责人")
    labels = models.JSONField(default=list, blank=True, verbose_name="标签")
    due_date = models.DateField(null=True, blank=True, verbose_name="截止日期")
    story_points = models.IntegerField(default=0, verbose_name="故事点/工作量")
    sort_order = models.IntegerField(default=0, verbose_name="列内排序")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    last_overdue_notified_at = models.DateTimeField(null=True, blank=True, verbose_name="上次逾期提醒时间")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_cards", verbose_name="创建者"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "任务卡片"
        verbose_name_plural = "任务卡片"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class Subtask(models.Model):
    """子任务 / 检查清单项"""

    card = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="subtasks", verbose_name="所属任务")
    title = models.CharField(max_length=200, verbose_name="标题")
    is_done = models.BooleanField(default=False, verbose_name="已完成")
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="subtasks", verbose_name="负责人"
    )
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "子任务"
        verbose_name_plural = "子任务"
        ordering = ["sort_order", "id"]


class WorkLog(models.Model):
    """任务工时记录"""

    card = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="worklogs", verbose_name="任务")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="worklogs", verbose_name="记录人")
    minutes = models.IntegerField(default=0, verbose_name="工时(分钟)")
    note = models.CharField(max_length=200, blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        verbose_name = "工时记录"
        verbose_name_plural = "工时记录"
        ordering = ["-created_at"]


class CardComment(models.Model):
    """任务评论"""

    card = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="comments", verbose_name="任务")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_comments", verbose_name="作者")
    content = models.TextField(verbose_name="内容")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "任务评论"
        verbose_name_plural = "任务评论"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} 评论 {self.card.title}"


class ProjectActivity(models.Model):
    """项目活动记录（动态流）"""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="activities", verbose_name="项目")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    action = models.CharField(max_length=100, verbose_name="动作")
    target = models.CharField(max_length=200, blank=True, verbose_name="对象")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "项目活动"
        verbose_name_plural = "项目活动"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.target}"


class BoardShareLink(models.Model):
    """看板只读分享链接（免登录查看）"""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="share_links", verbose_name="项目")
    token = models.CharField(max_length=32, unique=True, db_index=True, verbose_name="令牌")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="board_share_links", verbose_name="创建者")
    is_revoked = models.BooleanField(default=False, verbose_name="已失效")
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    view_count = models.IntegerField(default=0, verbose_name="浏览次数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "看板分享链接"
        verbose_name_plural = "看板分享链接"

    def __str__(self):
        return self.token

    @staticmethod
    def make_token():
        return uuid.uuid4().hex[:16]

    @property
    def is_expired(self):
        from django.utils import timezone

        if self.is_revoked:
            return True
        if self.expire_at and self.expire_at < timezone.now():
            return True
        return False
