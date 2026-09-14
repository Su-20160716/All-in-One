"""IM 模型：会话、消息、会话成员偏好（免打扰/置顶/草稿）"""
from django.conf import settings
from django.db import models


class ChatSession(models.Model):
    """聊天会话：单聊或群聊"""

    TYPE_CHOICES = [("single", "单聊"), ("group", "群聊")]

    name = models.CharField(max_length=120, blank=True, verbose_name="群名")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="single", verbose_name="类型")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="chat_sessions", verbose_name="成员")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_sessions", verbose_name="群主"
    )
    announcement = models.CharField(max_length=500, blank=True, verbose_name="群公告")
    avatar = models.CharField(max_length=500, blank=True, verbose_name="群头像")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "会话"
        verbose_name_plural = "会话"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"会话 {self.id}"


class SessionMemberSetting(models.Model):
    """成员对会话的个性化设置：免打扰 / 置顶 / 草稿"""

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="member_settings", verbose_name="会话")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_settings", verbose_name="成员")
    is_muted = models.BooleanField(default=False, verbose_name="免打扰")
    is_pinned = models.BooleanField(default=False, verbose_name="置顶")
    draft = models.TextField(blank=True, verbose_name="草稿")
    last_read_at = models.DateTimeField(null=True, blank=True, verbose_name="最后已读时间")

    class Meta:
        verbose_name = "会话设置"
        verbose_name_plural = "会话设置"
        unique_together = [("session", "user")]


class ChatMessage(models.Model):
    """聊天消息（支持文本/图片/文件/系统消息、撤回、转发）"""

    TYPE_CHOICES = [("text", "文本"), ("image", "图片"), ("file", "文件"), ("system", "系统")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages", verbose_name="会话")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="sent_messages", verbose_name="发送者"
    )
    msg_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="text", verbose_name="消息类型")
    content = models.TextField(verbose_name="内容")
    attachments = models.JSONField(default=list, blank=True, verbose_name="附件")
    forward_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="forwards", verbose_name="转发自")
    is_recalled = models.BooleanField(default=False, verbose_name="已撤回")
    deleted_for = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="deleted_messages", blank=True, verbose_name="对谁删除")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "消息"
        verbose_name_plural = "消息"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender} @ {self.created_at:%H:%M}"


class UnreadCounter(models.Model):
    """（保留兼容）旧版未读计数，新逻辑使用 SessionMemberSetting.last_read_at"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="unread_counters", verbose_name="用户")
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="unread_counters", verbose_name="会话")
    count = models.IntegerField(default=0, verbose_name="未读数")

    class Meta:
        verbose_name = "未读计数"
        verbose_name_plural = "未读计数"
        unique_together = [("user", "session")]
