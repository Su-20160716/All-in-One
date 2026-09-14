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
    description = models.CharField(max_length=500, blank=True, verbose_name="备注")
    is_deleted = models.BooleanField(default=False, verbose_name="已删除(回收站)")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    origin_folder_id = models.BigIntegerField(null=True, blank=True, verbose_name="删除前所在文件夹")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "文件元数据"
        verbose_name_plural = "文件元数据"
        ordering = ["-created_at"]

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
    password = models.CharField(max_length=64, blank=True, verbose_name="访问密码(明文仅演示)")
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    max_downloads = models.IntegerField(null=True, blank=True, verbose_name="下载次数上限")
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
