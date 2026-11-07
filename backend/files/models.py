"""文件管理模型：文件夹、文件元数据、共享链接、分片上传记录、回收站、最近访问"""
import uuid

from django.conf import settings
from django.db import models


class Folder(models.Model):
    """虚拟文件夹树（与磁盘解耦）"""

    COLOR_CHOICES = [
        ("default", "默认"), ("red", "红"), ("orange", "橙"), ("green", "绿"),
        ("blue", "蓝"), ("purple", "紫"), ("gray", "灰"),
    ]

    name = models.CharField(max_length=200, verbose_name="名称")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children", verbose_name="父文件夹")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="folders", verbose_name="所有者")
    color = models.CharField(max_length=12, default="default", choices=COLOR_CHOICES, verbose_name="颜色标记")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "文件夹"
        verbose_name_plural = "文件夹"
        ordering = ["name"]

    def __str__(self):
        return self.name


class FileMeta(models.Model):
    """文件元数据：名称、存储路径、大小、哈希、类型、回收站、收藏、备注"""

    name = models.CharField(max_length=255, verbose_name="文件名")
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, null=True, blank=True, related_name="files", verbose_name="所属文件夹")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="files", verbose_name="所有者")
    storage_path = models.CharField(max_length=500, verbose_name="存储相对路径")
    size = models.BigIntegerField(default=0, verbose_name="大小(字节)")
    sha1 = models.CharField(max_length=40, blank=True, db_index=True, verbose_name="SHA1")
    kind = models.CharField(max_length=16, default="other", verbose_name="类型")
    ext = models.CharField(max_length=16, blank=True, verbose_name="扩展名")
    thumbnail_path = models.CharField(max_length=500, blank=True, verbose_name="缩略图路径")
    # Office → PDF 转换产物（由 files.office 适配器生成，未安装 LibreOffice 时保持空）
    pdf_path = models.CharField(max_length=500, blank=True, verbose_name="转换后PDF路径")
    pdf_status = models.CharField(max_length=12, default="", verbose_name="PDF转换状态")
    pdf_error = models.CharField(max_length=255, blank=True, verbose_name="PDF转换失败原因")
    pdf_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="PDF生成时间")
    is_star = models.BooleanField(default=False, verbose_name="收藏")
    favorite_group = models.CharField(max_length=50, blank=True, default="", verbose_name="收藏分组")
    # F555 收藏夹自定义排序（默认 0，按创建时间兜底）
    favorite_order = models.IntegerField(default=0, verbose_name="收藏排序")
    # F553 图片分辨率（首次查询时按需计算并缓存）
    width = models.IntegerField(null=True, blank=True, verbose_name="图片宽度(px)")
    height = models.IntegerField(null=True, blank=True, verbose_name="图片高度(px)")
    description = models.CharField(max_length=500, blank=True, verbose_name="备注")
    is_deleted = models.BooleanField(default=False, verbose_name="已删除(回收站)")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    origin_folder_id = models.BigIntegerField(null=True, blank=True, verbose_name="删除前所在文件夹")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    tags = models.ManyToManyField("FileTag", related_name="files", blank=True, verbose_name="标签")

    class Meta:
        verbose_name = "文件元数据"
        verbose_name_plural = "文件元数据"
        ordering = ["-created_at"]
        # S2-B1：文件列表恒为 owner + is_deleted=False 过滤 + created_at 倒序
        # （FileListView / 回收站 / 全局搜索三处同模式）。单例用户场景收益有限，
        # 标注待实测：数据量过万后用 EXPLAIN QUERY PLAN 验证命中后再决定去留。
        indexes = [
            models.Index(fields=["owner", "is_deleted", "-created_at"],
                         name="files_owner_del_created_idx"),
        ]

    def __str__(self):
        return self.name

    @property
    def url(self):
        if not self.storage_path:
            return ""
        return f"/media/{self.storage_path}"

    @property
    def thumbnail_url(self):
        return f"/media/{self.thumbnail_path}" if self.thumbnail_path else ""

    @property
    def pdf_url(self):
        return f"/media/{self.pdf_path}" if self.pdf_path else ""

    # ---- 在线预览能力判定 ----
    IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "ico", "avif"}
    VIDEO_EXTS = {"mp4", "webm", "ogv", "mov", "m4v", "mkv"}
    AUDIO_EXTS = {"mp3", "wav", "ogg", "flac", "m4a", "aac"}
    TEXT_EXTS = {"txt", "md", "markdown", "json", "csv", "xml", "yml", "yaml", "log", "ini",
                 "py", "js", "ts", "vue", "java", "c", "cpp", "h", "go", "rs", "rb", "php",
                 "sql", "sh", "html", "htm", "css", "scss"}
    OFFICE_EXTS = {"doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "odt", "ods", "odp", "rtf", "wps"}

    @property
    def preview_type(self):
        """返回预览类型，前端据此选择渲染器：
        image / video / audio / pdf / text / office / none
        """
        ext = (self.ext or "").lower().lstrip(".")
        if ext in self.IMAGE_EXTS or self.kind == "image":
            return "image"
        if ext in self.VIDEO_EXTS or self.kind == "video":
            return "video"
        if ext in self.AUDIO_EXTS or self.kind == "audio":
            return "audio"
        if ext == "pdf":
            return "pdf"
        if ext in self.OFFICE_EXTS:
            return "office"
        if ext in self.TEXT_EXTS or self.kind == "text":
            return "text"
        return "none"

    @property
    def previewable(self):
        return self.preview_type != "none"


class RecentFile(models.Model):
    """最近访问/下载的文件记录"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recent_files", verbose_name="用户")
    file = models.ForeignKey(FileMeta, on_delete=models.CASCADE, related_name="recent_records", verbose_name="文件")
    accessed_at = models.DateTimeField(auto_now=True, verbose_name="访问时间")

    class Meta:
        verbose_name = "最近访问"
        verbose_name_plural = "最近访问"
        unique_together = [("owner", "file")]
        ordering = ["-accessed_at"]


class ChunkUpload(models.Model):
    """分片上传任务（断点续传依据）"""

    STATUS_CHOICES = [("uploading", "上传中"), ("completed", "已完成"), ("aborted", "已取消")]

    upload_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, verbose_name="上传ID")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chunk_uploads", verbose_name="上传者")
    filename = models.CharField(max_length=255, verbose_name="文件名")
    folder_id = models.IntegerField(null=True, blank=True, verbose_name="目标文件夹ID")
    file_size = models.BigIntegerField(default=0, verbose_name="总大小")
    chunk_size = models.IntegerField(default=5 * 1024 * 1024, verbose_name="分块大小")
    total_chunks = models.IntegerField(default=0, verbose_name="总分块数")
    uploaded_chunks = models.JSONField(default=list, verbose_name="已上传分块索引")
    sha1 = models.CharField(max_length=40, blank=True, verbose_name="文件SHA1")
    temp_dir = models.CharField(max_length=500, blank=True, verbose_name="临时目录")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="uploading", verbose_name="状态")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "分片上传"
        verbose_name_plural = "分片上传"

    def __str__(self):
        return f"{self.filename} ({len(self.uploaded_chunks)}/{self.total_chunks})"


class ShareLink(models.Model):
    """文件/文件夹共享链接"""

    PERMISSION_CHOICES = [("view", "仅预览"), ("download", "可下载"), ("edit", "可编辑")]

    token = models.CharField(max_length=32, unique=True, db_index=True, verbose_name="令牌")
    file = models.ForeignKey(FileMeta, on_delete=models.CASCADE, null=True, blank=True, related_name="share_links", verbose_name="文件")
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, null=True, blank=True, related_name="share_links", verbose_name="文件夹")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="share_links", verbose_name="创建者")
    permission = models.CharField(max_length=16, choices=PERMISSION_CHOICES, default="view", verbose_name="权限")
    # S2-B1：访问密码改为 Django password hash 存储（原为明文）。
    # max_length 128 容纳 PBKDF2 格式（pbkdf2_sha256$600000$<salt>$<hash> ≈ 78 字符）；
    # 存量明文由数据迁移 files/migrations/00XX_hash_share_passwords 批量转换。
    password = models.CharField(max_length=128, blank=True, verbose_name="访问密码(hash)")
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    max_downloads = models.IntegerField(null=True, blank=True, verbose_name="下载次数上限")
    # S24-223：文件夹分享允许访客把文件投递进来（收集链接）
    allow_upload = models.BooleanField(default=False, verbose_name="允许访客上传")
    download_count = models.IntegerField(default=0, verbose_name="下载次数")
    view_count = models.IntegerField(default=0, verbose_name="浏览次数")
    is_revoked = models.BooleanField(default=False, verbose_name="已失效")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "共享链接"
        verbose_name_plural = "共享链接"

    def __str__(self):
        return self.token

    @property
    def is_expired(self):
        from django.utils import timezone
        if self.is_revoked:
            return True
        if self.expire_at and self.expire_at < timezone.now():
            return True
        if self.max_downloads is not None and self.download_count >= self.max_downloads:
            return True
        return False


class FileTag(models.Model):
    """文件标签（多标签体系，按用户隔离）"""

    name = models.CharField(max_length=50, verbose_name="标签名")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="file_tags", verbose_name="所有者")
    color = models.CharField(max_length=16, default="default", verbose_name="颜色")

    class Meta:
        verbose_name = "文件标签"
        verbose_name_plural = "文件标签"
        unique_together = [("name", "owner")]
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def use_count(self):
        return self.files.filter(is_deleted=False).count()


class FileOperationLog(models.Model):
    """F559 移动/复制等文件操作流水（只增不改，便于追溯）"""

    ACTION_CHOICES = [
        ("move", "移动"), ("copy", "复制"), ("rename", "重命名"),
        ("upload", "上传"), ("trash", "移入回收站"), ("restore", "还原"),
        ("download", "下载"), ("share", "分享"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="file_ops", verbose_name="操作者")
    file = models.ForeignKey(FileMeta, on_delete=models.SET_NULL, null=True, blank=True, related_name="ops", verbose_name="文件")
    file_name = models.CharField(max_length=255, blank=True, verbose_name="文件名(冗余)")
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default="move", verbose_name="操作类型")
    detail = models.CharField(max_length=500, blank=True, verbose_name="详情")
    from_folder = models.CharField(max_length=200, blank=True, verbose_name="来源目录")
    to_folder = models.CharField(max_length=200, blank=True, verbose_name="目标目录")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "文件操作记录"
        verbose_name_plural = "文件操作记录"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "created_at"])]

    def __str__(self):
        return f"{self.action}:{self.file_name}"


class FileVisibilitySnapshot(models.Model):
    """F561 文件可见性快照：记录文件在某时刻的可见范围（私有/共享链接/权限）"""

    VISIBILITY_CHOICES = [
        ("private", "仅自己"), ("shared", "共享链接"), ("expired", "链接已过期"), ("revoked", "链接已撤销"),
    ]

    file = models.ForeignKey(FileMeta, on_delete=models.CASCADE, related_name="visibility_snapshots", verbose_name="文件")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="file_visibility_snapshots", verbose_name="记录人"
    )
    visibility = models.CharField(max_length=16, choices=VISIBILITY_CHOICES, default="private", verbose_name="可见性")
    data_scope = models.CharField(max_length=16, default="self", verbose_name="数据范围")
    share_token = models.CharField(max_length=32, blank=True, verbose_name="关联分享令牌")
    permission = models.CharField(max_length=16, blank=True, verbose_name="分享权限")
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name="分享过期时间")
    snapshot = models.JSONField(default=dict, blank=True, verbose_name="快照明细")
    note = models.CharField(max_length=255, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        verbose_name = "文件可见性快照"
        verbose_name_plural = "文件可见性快照"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_id}:{self.visibility}"


class FileVersion(models.Model):
    """F11 文件历史版本：在线编辑/覆盖保存前的物理副本（仅保留最近 N 个）"""

    file = models.ForeignKey(FileMeta, on_delete=models.CASCADE, related_name="versions", verbose_name="文件")
    version = models.PositiveIntegerField(verbose_name="版本号")
    storage_path = models.CharField(max_length=500, verbose_name="版本存储路径")
    size = models.BigIntegerField(default=0, verbose_name="大小(字节)")
    sha1 = models.CharField(max_length=40, blank=True, verbose_name="SHA1")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="file_versions", verbose_name="保存人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="保存时间")

    class Meta:
        verbose_name = "文件版本"
        verbose_name_plural = "文件版本"
        ordering = ["-version"]
        unique_together = [("file", "version")]

    def __str__(self):
        return f"{self.file_id} v{self.version}"


class ShareVisit(models.Model):
    """F14 分享访问明细：按 IP/UA 哈希去重统计独立访客（不落原始 IP）"""

    link = models.ForeignKey(ShareLink, on_delete=models.CASCADE, related_name="visits", verbose_name="分享链接")
    ip_hash = models.CharField(max_length=64, blank=True, default="", db_index=True, verbose_name="IP哈希")
    ua_hash = models.CharField(max_length=64, blank=True, default="", verbose_name="UA哈希")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="访问时间")

    class Meta:
        verbose_name = "分享访问"
        verbose_name_plural = "分享访问"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["link", "-created_at"])]

    def __str__(self):
        return f"{self.link_id} @{self.created_at:%Y-%m-%d %H:%M}"
