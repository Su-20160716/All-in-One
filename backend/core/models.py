"""公共模型：操作日志、通知中心、通知偏好、系统公告、已读公告、站点设置"""
from django.conf import settings
from django.db import models


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
    """快捷创建通知（尊重用户通知偏好，被关闭的分类不产生通知）"""
    if recipient is not None and not NotificationSetting.objects.filter(
        user=recipient, category=category, enabled=False
    ).exists():
        return Notification.objects.create(
            recipient=recipient, title=title, content=content, category=category, level=level, link=link
        )
    return None


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
