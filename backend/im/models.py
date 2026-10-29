"""IM 模型：会话、消息、会话成员偏好（免打扰/置顶/草稿/归档）"""
from django.conf import settings
from django.db import models


class QuickReply(models.Model):
    """个人快捷回复模板"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quick_replies", verbose_name="所有者")
    title = models.CharField(max_length=120, blank=True, verbose_name="标题")
    content = models.TextField(verbose_name="内容")
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "快捷回复"
        verbose_name_plural = "快捷回复"
        ordering = ["sort_order", "id"]


class KeywordAlert(models.Model):
    """关键词提醒：消息内容命中关键词时推送通知"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="keyword_alerts", verbose_name="所有者")
    keywords = models.JSONField(default=list, verbose_name="关键词列表")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "关键词提醒"
        verbose_name_plural = "关键词提醒"


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
    is_archived = models.BooleanField(default=False, verbose_name="已归档")
    # F25 自定义标签（列表页可按标签过滤）
    tags = models.JSONField(default=list, blank=True, verbose_name="标签")
    draft = models.TextField(blank=True, verbose_name="草稿")
    draft_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="草稿更新时间")
    typing_at = models.DateTimeField(null=True, blank=True, verbose_name="最近正在输入时间")
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
    reply_to = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies", verbose_name="回复")
    is_pinned = models.BooleanField(default=False, verbose_name="会话内置顶")
    is_recalled = models.BooleanField(default=False, verbose_name="已撤回")
    is_deleted = models.BooleanField(default=False, verbose_name="双方删除")
    edited = models.BooleanField(default=False, verbose_name="已编辑")
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name="编辑时间")
    deleted_for = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="deleted_messages", blank=True, verbose_name="对谁删除")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "消息"
        verbose_name_plural = "消息"
        ordering = ["created_at"]
        # S2-B1：消息列表恒为 session 过滤 + id 倒序取最近 N 条
        # （MessageListView order_by("-id")[:50]，WS 重连补拉同模式）。
        # created_at 与 id 单调性一致但索引选 id：查询条件就是 id，且
        # created_at 允许并发同值。标注待实测。
        indexes = [
            models.Index(fields=["session", "-id"],
                         name="chatmsg_session_id_idx"),
        ]

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


# ===========================================================================
# IM 增强（F599–F612）：稍后处理清单、消息收藏夹
# ===========================================================================

class TodoItem(models.Model):
    """F602 稍后处理清单：把某条消息标记为稍后处理"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="im_todos", verbose_name="所有者")
    session = models.ForeignKey(ChatSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="todos", verbose_name="来源会话")
    message = models.ForeignKey(ChatMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="todos", verbose_name="来源消息")
    content = models.TextField(blank=True, verbose_name="内容摘要")
    is_done = models.BooleanField(default=False, verbose_name="已处理")
    remind_at = models.DateTimeField(null=True, blank=True, verbose_name="提醒时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "稍后处理"
        verbose_name_plural = "稍后处理"
        ordering = ["is_done", "-created_at"]

    def __str__(self):
        return self.content[:30]


class MessageFavorite(models.Model):
    """F608 消息收藏夹"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_favorites", verbose_name="所有者")
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="favorited_by", verbose_name="消息")
    note = models.CharField(max_length=200, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="收藏时间")

    class Meta:
        verbose_name = "消息收藏"
        verbose_name_plural = "消息收藏"
        ordering = ["-created_at"]
        unique_together = [("owner", "message")]

    def __str__(self):
        return f"{self.owner_id} 收藏 {self.message_id}"
