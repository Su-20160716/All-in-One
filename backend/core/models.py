"""公共模型：操作日志、通知中心、通知偏好、系统公告、已读公告、站点设置"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class OperationLog(models.Model):
    """全平台统一操作日志（由中间件 + 业务代码写入）"""

    ACTION_CHOICES = [
        ("create", "创建"),
        ("update", "更新"),
        ("delete", "删除"),
        ("read", "读取"),
        ("login", "登录"),
        ("logout", "退出"),
        ("upload", "上传"),
        ("download", "下载"),
        ("share", "分享"),
        ("move", "移动"),
        ("restore", "恢复"),
        ("export", "导出"),
        ("other", "其他"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="操作用户"
    )
    module = models.CharField(max_length=32, verbose_name="模块")
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default="other", verbose_name="动作")
    target = models.CharField(max_length=255, blank=True, verbose_name="操作对象")
    detail = models.TextField(blank=True, verbose_name="详情")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "操作日志"
        verbose_name_plural = "操作日志"

    def __str__(self):
        return f"{self.user} {self.action} {self.target}"


class Notification(models.Model):
    """统一通知中心：笔记评论、任务分配、新消息、文件共享等全部汇聚于此"""

    LEVEL_CHOICES = [("info", "普通"), ("success", "成功"), ("warning", "警告"), ("danger", "危险")]
    CATEGORY_CHOICES = [
        ("system", "系统"),
        ("file", "文件"),
        ("note", "笔记"),
        ("project", "项目"),
        ("message", "消息"),
        ("share", "分享"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications", verbose_name="接收人"
    )
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="system", verbose_name="分类")
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="info", verbose_name="级别")
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(blank=True, verbose_name="内容")
    link = models.CharField(max_length=500, blank=True, verbose_name="跳转链接")
    is_read = models.BooleanField(default=False, verbose_name="已读")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "通知"
        verbose_name_plural = "通知"

    def __str__(self):
        return f"[{self.recipient}] {self.title}"


class NotificationSetting(models.Model):
    """用户通知偏好：按分类开关（免打扰）"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_settings", verbose_name="用户"
    )
    category = models.CharField(max_length=16, default="system", verbose_name="分类")
    enabled = models.BooleanField(default=True, verbose_name="是否接收")

    class Meta:
        verbose_name = "通知偏好"
        verbose_name_plural = "通知偏好"
        unique_together = [("user", "category")]

    def __str__(self):
        return f"{self.user_id}:{self.category}={self.enabled}"


class Announcement(models.Model):
    """系统公告（管理员发布，全员可见）"""

    LEVEL_CHOICES = [("info", "普通"), ("important", "重要"), ("urgent", "紧急")]

    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(verbose_name="正文")
    level = models.CharField(max_length=12, choices=LEVEL_CHOICES, default="info", verbose_name="级别")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="announcements", verbose_name="发布人"
    )
    is_pinned = models.BooleanField(default=False, verbose_name="置顶")
    is_published = models.BooleanField(default=True, verbose_name="已发布")
    scheduled_at = models.DateTimeField(null=True, blank=True, verbose_name="定时发布时间")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="到期时间")
    readers = models.ManyToManyField(settings.AUTH_USER_MODEL, through="AnnouncementRead", related_name="read_announcements")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="发布时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["-is_pinned", "-created_at"]
        verbose_name = "系统公告"
        verbose_name_plural = "系统公告"

    def __str__(self):
        return self.title


class AnnouncementRead(models.Model):
    """公告已读记录"""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="read_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_reads")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("announcement", "user")]


class SiteSetting(models.Model):
    """站点键值设置（管理员维护，前端读取）"""

    key = models.CharField(max_length=64, unique=True, verbose_name="键")
    value = models.TextField(blank=True, verbose_name="值")
    label = models.CharField(max_length=120, blank=True, verbose_name="说明")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "站点设置"
        verbose_name_plural = "站点设置"

    def __str__(self):
        return self.key


def notify(recipient, title, content="", category="system", level="info", link=""):
    """快捷创建通知（尊重用户通知偏好和免打扰时段，被关闭的分类/免打扰时段不产生推送通知）

    免打扰时段内：通知仍写入数据库（用户稍后可见），但不做即时推送。
    """
    if recipient is None:
        return None
    # 检查分类开关
    if NotificationSetting.objects.filter(
        user=recipient, category=category, enabled=False
    ).exists():
        return None
    # 检查免打扰时段（dnd_start/dnd_end 同在 User 上）
    dnd = False
    dnd_start = getattr(recipient, "dnd_start", None)
    dnd_end = getattr(recipient, "dnd_end", None)
    if dnd_start and dnd_end:
        now_time = timezone.localtime(timezone.now()).time()
        if dnd_start <= dnd_end:
            dnd = dnd_start <= now_time <= dnd_end
        else:
            # 跨午夜（如 22:00 ~ 08:00）
            dnd = now_time >= dnd_start or now_time <= dnd_end
    notif = Notification.objects.create(
        recipient=recipient, title=title, content=content, category=category, level=level, link=link
    )
    # 免打扰时段不做即时推送（前端 WebSocket 层可根据 dnd 标记跳过 toast）
    notif.dnd_suppressed = dnd
    return notif


# ---------------------------------------------------------------------------
# 全文搜索倒排索引
# ---------------------------------------------------------------------------

class SearchDoc(models.Model):
    """被索引的文档（笔记 / 文件内容 / 项目 / 任务）

    与业务表解耦：只保存 module + object_id，检索时再回查业务表，
    这样任何模块都能接入搜索而无需改动业务模型。
    """

    MODULE_CHOICES = [
        ("note", "笔记"),
        ("file", "文件"),
        ("project", "项目"),
        ("task", "任务"),
        # B27：代码工坊（v6）接入全文索引——与 core/signals.py 的
        # 保存即索引、core/reindex.py 的重建 handler 使用同一组 module 名
        ("code", "代码文件"),
        ("snippet", "代码片段"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="search_docs", verbose_name="所属用户"
    )
    module = models.CharField(max_length=16, choices=MODULE_CHOICES, verbose_name="模块")
    object_id = models.BigIntegerField(verbose_name="业务对象ID")
    title = models.CharField(max_length=500, verbose_name="标题")
    summary = models.TextField(blank=True, verbose_name="摘要片段")
    length = models.IntegerField(default=1, verbose_name="词项总数(用于BM25归一化)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "搜索文档"
        verbose_name_plural = "搜索文档"
        unique_together = [("module", "object_id")]
        indexes = [models.Index(fields=["owner", "module"]), models.Index(fields=["module", "object_id"])]

    def __str__(self):
        return f"{self.module}:{self.object_id} {self.title[:20]}"


class SearchTerm(models.Model):
    """倒排词项：一个词在某个文档中的出现频次"""

    doc = models.ForeignKey(SearchDoc, on_delete=models.CASCADE, related_name="terms")
    term = models.CharField(max_length=64, db_index=True, verbose_name="词项")
    freq = models.IntegerField(default=1, verbose_name="频次(标题加权)")
    in_title = models.BooleanField(default=False, verbose_name="是否命中标题")

    class Meta:
        verbose_name = "搜索词项"
        verbose_name_plural = "搜索词项"
        indexes = [models.Index(fields=["term", "doc"])]

    def __str__(self):
        return f"{self.term}x{self.freq}"


class SearchQueryLog(models.Model):
    """用户搜索词记录：用于搜索历史与热词统计（#63）"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="search_queries", verbose_name="用户",
    )
    term = models.CharField(max_length=200, db_index=True, verbose_name="搜索词")
    result_count = models.IntegerField(default=0, verbose_name="结果数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "搜索词记录"
        verbose_name_plural = "搜索词记录"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]

    def __str__(self):
        return f"{self.owner}:{self.term}"


# ===========================================================================
# v8 新增（F627–F642 管理与平台）—— 纯新增模型，向后兼容
# ===========================================================================

class AdminCommandRun(models.Model):
    """F629 管理命令面板：白名单命令的执行记录与上次结果"""

    command = models.CharField(max_length=64, db_index=True, verbose_name="命令名")
    args = models.CharField(max_length=200, blank=True, verbose_name="参数")
    ok = models.BooleanField(default=True, verbose_name="是否成功")
    output = models.TextField(blank=True, verbose_name="输出(截断)")
    error = models.TextField(blank=True, verbose_name="错误(截断)")
    duration_ms = models.IntegerField(default=0, verbose_name="耗时(ms)")
    ran_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="command_runs", verbose_name="触发人",
    )
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="开始时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")

    class Meta:
        verbose_name = "管理命令执行记录"
        verbose_name_plural = "管理命令执行记录"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.command} {'ok' if self.ok else 'fail'} @{self.started_at:%Y-%m-%d %H:%M:%S}"


class ExceptionRecord(models.Model):
    """F633 异常聚合：按「类型 + 规范化消息 + 出错位置」签名去重计数"""

    signature = models.CharField(max_length=40, unique=True, verbose_name="异常签名")
    etype = models.CharField(max_length=100, db_index=True, verbose_name="异常类型")
    message = models.CharField(max_length=500, blank=True, verbose_name="消息(已规范化)")
    location = models.CharField(max_length=200, blank=True, verbose_name="出错位置")
    path = models.CharField(max_length=200, blank=True, verbose_name="最近请求路径")
    count = models.IntegerField(default=1, verbose_name="累计次数")
    sample = models.TextField(blank=True, verbose_name="样本堆栈(截断)")
    first_at = models.DateTimeField(auto_now_add=True, verbose_name="首次出现")
    last_at = models.DateTimeField(auto_now=True, verbose_name="最近出现")

    class Meta:
        verbose_name = "异常记录"
        verbose_name_plural = "异常记录"
        ordering = ["-last_at"]

    def __str__(self):
        return f"{self.etype} x{self.count}"


class SlowEndpoint(models.Model):
    """F632 慢接口采样聚合（前端上报的接口耗时样本，按路径归并）"""

    path = models.CharField(max_length=200, unique=True, verbose_name="接口路径")
    samples = models.IntegerField(default=0, verbose_name="样本数")
    total_ms = models.BigIntegerField(default=0, verbose_name="耗时总和(ms)")
    slow_samples = models.IntegerField(default=0, verbose_name="慢样本数(≥1000ms)")
    max_ms = models.IntegerField(default=0, verbose_name="最大耗时(ms)")
    first_at = models.DateTimeField(auto_now_add=True, verbose_name="首个样本")
    last_at = models.DateTimeField(auto_now=True, verbose_name="最近样本")

    class Meta:
        verbose_name = "慢接口采样"
        verbose_name_plural = "慢接口采样"
        ordering = ["-max_ms"]

    def __str__(self):
        return f"{self.path} avg={self.avg_ms}ms"

    @property
    def avg_ms(self) -> int:
        return int(self.total_ms / self.samples) if self.samples else 0
