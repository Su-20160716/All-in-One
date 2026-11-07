"""笔记知识库模型：笔记、版本快照、标签"""
import uuid

from django.conf import settings
from django.db import models


class NoteTag(models.Model):
    name = models.CharField(max_length=50, verbose_name="标签名")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="note_tags", verbose_name="所有者")
    color = models.CharField(max_length=16, default="default", verbose_name="颜色")

    class Meta:
        verbose_name = "笔记标签"
        verbose_name_plural = "笔记标签"
        unique_together = [("name", "owner")]

    def __str__(self):
        return self.name

    @property
    def use_count(self):
        return self.notes.count()


class Note(models.Model):
    """笔记页面：支持父级嵌套、Markdown 正文、标签、置顶收藏、公开分享、回收站"""

    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(blank=True, verbose_name="Markdown 正文")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes", verbose_name="所有者")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children", verbose_name="父笔记")
    tags = models.ManyToManyField(NoteTag, related_name="notes", blank=True, verbose_name="标签")
    is_pinned = models.BooleanField(default=False, verbose_name="置顶")
    is_favorite = models.BooleanField(default=False, verbose_name="收藏")
    is_public = models.BooleanField(default=False, verbose_name="公开分享")
    share_token = models.CharField(max_length=32, blank=True, db_index=True, verbose_name="分享令牌")
    version = models.IntegerField(default=1, verbose_name="版本号")
    is_deleted = models.BooleanField(default=False, verbose_name="已删除(回收站)")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    is_archived = models.BooleanField(default=False, verbose_name="已归档")
    words = models.IntegerField(default=0, verbose_name="字数缓存")
    # F572 颜色标记（6 色，空=无标记）
    color = models.CharField(max_length=16, blank=True, default="", verbose_name="颜色标记")
    # F573 笔记来源（manual/template/import/copy/link/split/merge）
    source = models.CharField(max_length=16, default="manual", verbose_name="来源")
    # F582 分组文件夹
    folder = models.ForeignKey(
        "NoteFolder", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes", verbose_name="所属文件夹"
    )
    # AI 摘要（assistant 模块写入，避免重复调用大模型）
    ai_summary = models.TextField(blank=True, verbose_name="AI 摘要")
    ai_summary_at = models.DateTimeField(null=True, blank=True, verbose_name="摘要生成时间")
    # F18 定时发布 / 到期归档（均为空时行为与旧版完全一致）
    publish_at = models.DateTimeField(null=True, blank=True, verbose_name="定时发布时间")
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name="到期时间")
    # F238 自定义图标（emoji，最多 8 字符）
    icon = models.CharField(max_length=8, blank=True, default="", verbose_name="图标")
    # F239 封面图（引用文件中心已有图片）
    cover_file = models.ForeignKey(
        "files.FileMeta", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="note_covers", verbose_name="封面图",
    )
    # F240 回看提醒（remind_at 到点后由 send_note_reminders 发送并写 reminded_at）
    remind_at = models.DateTimeField(null=True, blank=True, verbose_name="提醒时间")
    reminded_at = models.DateTimeField(null=True, blank=True, verbose_name="已提醒时间")
    # F260 置顶区手动排序（越小越靠前，默认 0）
    pin_order = models.IntegerField(default=0, verbose_name="置顶排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "笔记"
        verbose_name_plural = "笔记"
        # F260：置顶笔记之间按 pin_order 升序，其余仍按更新时间
        ordering = ["-is_pinned", "pin_order", "-updated_at"]
        # S2-B1：笔记列表恒为 owner + is_deleted=False 过滤 + updated_at 倒序
        # （NoteListView / 回收站 / 搜索三处同模式；is_pinned 在前但为布尔低基数，
        # 不进索引，由排序阶段处理）。标注待实测，理由同 FileMeta 索引注释。
        indexes = [
            models.Index(fields=["owner", "is_deleted", "-updated_at"],
                         name="notes_owner_del_updated_idx"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.share_token:
            self.share_token = uuid.uuid4().hex[:16]
        super().save(*args, **kwargs)


class NoteVersion(models.Model):
    """笔记版本快照（自动保存 + 手动回滚）"""

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="versions", verbose_name="笔记")
    version = models.IntegerField(verbose_name="版本号")
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(blank=True, verbose_name="正文快照")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="操作人"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "笔记版本"
        verbose_name_plural = "笔记版本"
        ordering = ["-version"]
        unique_together = [("note", "version")]

    def __str__(self):
        return f"{self.note.title} v{self.version}"


class NoteLink(models.Model):
    """[[双链]]：笔记正文中出现的 [[标题]] 引用关系

    双向可查：
    - 出链（outgoing）：source 笔记里引用了谁
    - 反链（backlinks）：谁引用了 target 笔记
    target 为空表示「尚未创建的同名笔记」（悬浮链接）。
    """

    source = models.ForeignKey(
        Note, on_delete=models.CASCADE, related_name="outgoing_links", verbose_name="来源笔记"
    )
    target = models.ForeignKey(
        Note, on_delete=models.CASCADE, null=True, blank=True,
        related_name="incoming_links", verbose_name="目标笔记",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="note_links", verbose_name="所有者"
    )
    target_title = models.CharField(max_length=200, verbose_name="引用标题")
    alias = models.CharField(max_length=200, blank=True, verbose_name="显示别名")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立时间")

    class Meta:
        verbose_name = "笔记双链"
        verbose_name_plural = "笔记双链"
        unique_together = [("source", "target_title")]
        indexes = [models.Index(fields=["owner", "target"]), models.Index(fields=["owner", "target_title"])]

    def __str__(self):
        return f"[[{self.target_title}]]"

    @property
    def resolved(self):
        return self.target_id is not None


class NoteCollabState(models.Model):
    """实时协同编辑状态（Yjs CRDT）

    服务端不做 CRDT 合并，只做「快照 + 增量日志」的中继与持久化：
    - snapshot：最近一次客户端压缩后的完整状态（Y.encodeStateAsUpdate）
    - update_log：快照之后的增量更新列表（base64）
    新加入的客户端依次应用 snapshot + update_log 即可还原（Yjs 更新可交换、幂等）。
    """

    note = models.OneToOneField(Note, on_delete=models.CASCADE, related_name="collab", verbose_name="笔记")
    snapshot = models.BinaryField(null=True, blank=True, verbose_name="CRDT 快照")
    update_log = models.JSONField(default=list, blank=True, verbose_name="增量更新日志")
    revision = models.IntegerField(default=0, verbose_name="修订号")
    text_mirror = models.TextField(blank=True, verbose_name="纯文本镜像(供检索/回写)")
    contributors = models.JSONField(default=list, blank=True, verbose_name="最近协作者")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "协同编辑状态"
        verbose_name_plural = "协同编辑状态"

    def __str__(self):
        return f"collab#{self.note_id} rev{self.revision}"


class NoteCollabUpdate(models.Model):
    """协同增量更新（append-only）。

    每次 Yjs 增量只 INSERT 一行，避免「读整个 JSON → append → 整列写回」
    造成的写放大；快照压缩时整体清空。
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="collab_updates", verbose_name="笔记")
    revision = models.IntegerField(verbose_name="修订号")
    payload = models.TextField(verbose_name="Yjs 增量(base64)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        ordering = ["revision"]
        verbose_name = "协同增量更新"
        verbose_name_plural = "协同增量更新"
        indexes = [models.Index(fields=["note", "revision"], name="note_collab_upd_idx")]

    def __str__(self):
        return f"collab#{self.note_id}@{self.revision}"


class NoteFolder(models.Model):
    """F582 笔记分组文件夹（按用户隔离，支持一层嵌套）"""

    name = models.CharField(max_length=100, verbose_name="名称")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children", verbose_name="父文件夹")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="note_folders", verbose_name="所有者")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "笔记文件夹"
        verbose_name_plural = "笔记文件夹"
        ordering = ["name"]
        unique_together = [("name", "owner")]

    def __str__(self):
        return self.name


class NoteSnippet(models.Model):
    """F574 个人片段库：可反复插入笔记的常用文本片段"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="note_snippets", verbose_name="所有者")
    title = models.CharField(max_length=100, verbose_name="标题")
    content = models.TextField(blank=True, verbose_name="片段内容")
    tag = models.CharField(max_length=50, blank=True, default="", verbose_name="分类")
    use_count = models.IntegerField(default=0, verbose_name="插入次数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "笔记片段"
        verbose_name_plural = "笔记片段"
        ordering = ["-use_count", "-updated_at"]

    def __str__(self):
        return self.title


class WritingGoal(models.Model):
    """F565 写作字数目标（按天/周/月 或 指定笔记）"""

    PERIOD_CHOICES = [("day", "每天"), ("week", "每周"), ("month", "每月"), ("note", "单篇笔记")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writing_goals", verbose_name="所有者")
    target = models.PositiveIntegerField(default=500, verbose_name="目标字数")
    period = models.CharField(max_length=8, choices=PERIOD_CHOICES, default="day", verbose_name="周期")
    note = models.ForeignKey(Note, on_delete=models.CASCADE, null=True, blank=True, related_name="goals", verbose_name="关联笔记")
    active = models.BooleanField(default=True, verbose_name="进行中")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "写作目标"
        verbose_name_plural = "写作目标"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.period}:{self.target}"


class WordActivity(models.Model):
    """F565 每日写作增量（笔记正文变化时累计，供目标完成度/周回顾使用）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="word_activity", verbose_name="用户")
    date = models.DateField(verbose_name="日期")
    delta = models.IntegerField(default=0, verbose_name="当日新增字数")

    class Meta:
        verbose_name = "写作活跃"
        verbose_name_plural = "写作活跃"
        unique_together = [("owner", "date")]

    def __str__(self):
        return f"{self.owner_id}:{self.date}:{self.delta}"


class NoteComment(models.Model):
    """F236 段落讨论：引用选中文本的评论 / 回复（parent 为空即顶层评论）"""

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="comments", verbose_name="笔记")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="note_comments", verbose_name="作者")
    quote = models.CharField(max_length=500, blank=True, default="", verbose_name="引用文本")
    content = models.TextField(verbose_name="评论内容")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies", verbose_name="父评论"
    )
    resolved = models.BooleanField(default=False, verbose_name="已解决")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "笔记评论"
        verbose_name_plural = "笔记评论"
        ordering = ["created_at"]

    def __str__(self):
        return f"#{self.note_id}:{self.content[:20]}"


class NoteAttachment(models.Model):
    """F237 笔记附件：引用文件中心已有文件（不复制物理文件）"""

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="attachments", verbose_name="笔记")
    file = models.ForeignKey(
        "files.FileMeta", on_delete=models.CASCADE, related_name="note_attachments", verbose_name="文件"
    )
    name = models.CharField(max_length=255, blank=True, default="", verbose_name="展示名称")
    size = models.BigIntegerField(default=0, verbose_name="大小(字节)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="绑定时间")

    class Meta:
        verbose_name = "笔记附件"
        verbose_name_plural = "笔记附件"
        ordering = ["id"]
        unique_together = [("note", "file")]

    def __str__(self):
        return self.name or f"att#{self.file_id}"


class NoteTemplate(models.Model):
    """F243 用户自建笔记模板（tags 以逗号分隔保存标签名）"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="note_templates", verbose_name="所有者")
    title = models.CharField(max_length=200, verbose_name="模板标题")
    content = models.TextField(blank=True, default="", verbose_name="正文")
    icon = models.CharField(max_length=8, blank=True, default="", verbose_name="图标")
    tags = models.CharField(max_length=200, blank=True, default="", verbose_name="标签(逗号分隔)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "笔记模板"
        verbose_name_plural = "笔记模板"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]
