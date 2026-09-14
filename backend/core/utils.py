"""核心工具函数：文件哈希、大小格式化、客户端 IP 等"""
import hashlib
import os


def sha1_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """分块计算文件 SHA1"""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def format_size(num: float) -> str:
    """字节数 → 人类可读"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def get_client_ip(request) -> str:
    ip = request.META.get("HTTP_X_FORWARDED_FOR")
    if ip:
        return ip.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def ext_of(name: str) -> str:
    return os.path.splitext(name)[1].lower().lstrip(".")


IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"}
TEXT_EXTS = {
    "txt", "md", "markdown", "log", "json", "py", "js", "ts", "vue", "html", "css",
    "java", "c", "cpp", "h", "go", "rs", "sql", "yml", "yaml", "toml", "ini", "conf",
    "xml", "sh", "bat", "ps1", "csv", "tsx", "jsx", "rb", "php", "kt", "swift",
}
VIDEO_EXTS = {"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"}
AUDIO_EXTS = {"mp3", "wav", "flac", "aac", "ogg", "m4a"}
ARCHIVE_EXTS = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"}


def file_kind(name: str) -> str:
    """按扩展名分类文件类型：image/text/video/audio/archive/other"""
    e = ext_of(name)
    if e in IMAGE_EXTS:
        return "image"
    if e in TEXT_EXTS:
        return "text"
    if e in VIDEO_EXTS:
        return "video"
    if e in AUDIO_EXTS:
        return "audio"
    if e in ARCHIVE_EXTS:
        return "archive"
    return "other"
