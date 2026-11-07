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
    wip_limit = models.IntegerField(default=0, verbose_name="在制品上限(0=不限)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "看板列"
        verbose_name_plural = "看板列"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.project.name} / {self.name}"


class Sprint(models.Model):
    """F23 迭代：卡片可归入迭代，结束后未完成卡片自动回到待办池"""

    STATUS_CHOICES = [("planned", "规划中"), ("active", "进行中"), ("closed", "已结束")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints", verbose_name="项目")
    name = models.CharField(max_length=120, verbose_name="迭代名称")
    start_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    end_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="planned", verbose_name="状态")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "迭代"
        verbose_name_plural = "迭代"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project_id}:{self.name}"


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
    estimated_minutes = models.IntegerField(default=0, verbose_name="预估工时(分钟)")
    number = models.IntegerField(null=True, blank=True, db_index=True, verbose_name="项目内编号")
    sprint = models.ForeignKey(
        "Sprint", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cards", verbose_name="所属迭代",
    )
    is_archived = models.BooleanField(default=False, verbose_name="已归档")
    sort_order = models.IntegerField(default=0, verbose_name="列内排序")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    # 300：标记解决的问题卡片，保留解决原因供时间线展示
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="解决时间")
    resolve_reason = models.CharField(max_length=200, blank=True, verbose_name="解决说明")
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
        # S2-B1：看板视图按 board 批量取卡片并按 sort_order 排序
        # （BoardListView 每列一查、拖拽换序按 board 过滤）。owner 维度被
        # board__project 间接覆盖，不单独入索引。标注待实测。
        indexes = [
            models.Index(fields=["board", "sort_order"],
                         name="taskcard_board_sort_idx"),
            # #142：MyTasks / 日历 / 逾期统计按 board 取到期日、或按 due_date + status 过滤，
            # 原表无任何 due_date 索引，只能全表扫描后排序。待迁移：makemigrations projects。
            models.Index(fields=["board", "due_date"],
                         name="taskcard_board_due_idx"),
            models.Index(fields=["due_date", "status"],
                         name="taskcard_due_status_idx"),
        ]

    def __str__(self):
        return self.title

    @property
    def code(self):
        """F592 卡片编号展示：C-1 / C-2"""
        return f"C-{self.number}" if self.number else ""

    def _normalize_due_date(self):
        # 接口传入的是 YYYY-MM-DD 字符串，Django 不会在保存时转成 date，
        # 直接留在实例上会让后续比较/序列化报错，这里统一转换。
        if isinstance(self.due_date, str):
            from datetime import datetime as _dt

            try:
                self.due_date = _dt.strptime(self.due_date[:10], "%Y-%m-%d").date()
            except ValueError:
                self.due_date = None

    def save(self, *args, **kwargs):
        # F592 首次保存时按项目分配自增编号（仅当为空，避免额外查询）。
        # 编号在「查 Max + 写入」之间有竞态，并发创建会拿到同一个号；
        # 锁住项目行（Postgres 生效，SQLite 为 no-op）把这段收进同一事务。
        project_id = None
        if self.number is None and self.board_id:
            project_id = getattr(self.board, "project_id", None)
        if project_id:
            from django.db import transaction
            from django.db.models import Max

            with transaction.atomic():
                Project.objects.select_for_update().filter(pk=project_id).first()
                m = TaskCard.objects.filter(board__project_id=project_id).aggregate(x=Max("number"))["x"] or 0
                self.number = m + 1
                self._normalize_due_date()
                super().save(*args, **kwargs)
            return
        self._normalize_due_date()
        super().save(*args, **kwargs)


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
    # 282：访问口令（make_password 哈希，空串表示无口令）
    password_hash = models.CharField(max_length=128, blank=True, default="", verbose_name="访问口令哈希")
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


# ===========================================================================
# 看板增强（F583–F598）：依赖、里程碑、卡片模板、验收清单(DoD)
# ===========================================================================

class CardDependency(models.Model):
    """F588 卡片依赖：card 被 blocked_by 阻塞"""

    card = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="dependencies", verbose_name="卡片")
    blocked_by = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="blocks", verbose_name="被依赖卡片")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "卡片依赖"
        verbose_name_plural = "卡片依赖"
        unique_together = [("card", "blocked_by")]

    def __str__(self):
        return f"{self.card_id} <- {self.blocked_by_id}"


class Milestone(models.Model):
    """F589 里程碑"""

    STATUS_CHOICES = [("planned", "计划中"), ("doing", "进行中"), ("done", "已完成")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones", verbose_name="项目")
    name = models.CharField(max_length=120, verbose_name="名称")
    description = models.TextField(blank=True, verbose_name="描述")
    due_date = models.DateField(null=True, blank=True, verbose_name="目标日期")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="planned", verbose_name="状态")
    # 287：临期里程碑每日提醒去重（距上次提醒 <20 小时不重复发）
    last_notified_at = models.DateTimeField(null=True, blank=True, verbose_name="上次提醒时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "里程碑"
        verbose_name_plural = "里程碑"
        ordering = ["due_date", "id"]

    def __str__(self):
        return self.name


class CardTemplate(models.Model):
    """F594 卡片模板（保存卡片为可复用模板）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_templates", verbose_name="所有者")
    name = models.CharField(max_length=200, verbose_name="模板名")
    title = models.CharField(max_length=200, verbose_name="卡片标题")
    description = models.TextField(blank=True, verbose_name="描述")
    priority = models.CharField(max_length=10, default="medium", verbose_name="优先级")
    labels = models.JSONField(default=list, blank=True, verbose_name="标签")
    story_points = models.IntegerField(default=0, verbose_name="故事点")
    estimated_minutes = models.IntegerField(default=0, verbose_name="预估工时(分钟)")
    # 288：模板携带验收清单文本，套用时一并回填
    dod_items = models.JSONField(default=list, blank=True, verbose_name="验收清单")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "卡片模板"
        verbose_name_plural = "卡片模板"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class AcceptanceItem(models.Model):
    """F595 验收清单（Definition of Done）条目"""

    card = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="acceptance_items", verbose_name="卡片")
    content = models.CharField(max_length=300, verbose_name="验收项")
    is_done = models.BooleanField(default=False, verbose_name="已满足")
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "验收清单项"
        verbose_name_plural = "验收清单项"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.content


class CardWatcher(models.Model):
    """295 卡片关注者：卡片变更只推送给关注者，避免全项目噪音"""

    card = models.ForeignKey(TaskCard, on_delete=models.CASCADE, related_name="watchers", verbose_name="卡片")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watched_cards", verbose_name="关注人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="关注时间")

    class Meta:
        verbose_name = "卡片关注"
        verbose_name_plural = "卡片关注"
        unique_together = [("card", "user")]

    def __str__(self):
        return f"{self.user_id} watch {self.card_id}"

