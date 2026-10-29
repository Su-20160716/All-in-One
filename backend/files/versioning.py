"""F11 文件版本历史：在线编辑前生成物理副本，按 FILE_VERSION_KEEP 保留最近 N 个。"""
import hashlib
import os
import shutil
import uuid

from django.conf import settings
from django.utils import timezone

from .models import FileMeta, FileVersion


def keep_limit() -> int:
    try:
        return max(1, int(getattr(settings, "FILE_VERSION_KEEP", 5)))
    except (TypeError, ValueError):
        return 5


def _abs(rel: str) -> str:
    return os.path.join(settings.MEDIA_ROOT, rel)


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _trim(fm):
    stale = list(fm.versions.order_by("-version")[keep_limit():])
    for ver in stale:
        try:
            os.remove(_abs(ver.storage_path))
        except OSError:
            pass
        ver.delete()


def snapshot(fm, user=None):
    """把 fm 当前物理内容存成历史版本，返回 FileVersion 或 None。"""
    src = _abs(fm.storage_path)
    if not os.path.isfile(src):
        return None
    last = fm.versions.order_by("-version").first()
    next_version = (last.version if last else 0) + 1
    ext = os.path.splitext(fm.storage_path)[1]
    rel = f"files/versions/{fm.id}/v{next_version}{ext}"
    dst = _abs(rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    record = FileVersion.objects.create(
        file=fm,
        version=next_version,
        storage_path=rel,
        size=os.path.getsize(dst),
        sha1=fm.sha1 or _sha1(dst),
        created_by=user,
    )
    _trim(fm)
    return record


def restore(fm, version, user=None):
    """回滚到指定版本；回滚前先把当前内容存为新版本。"""
    snap = fm.versions.filter(version=version).first()
    if snap is None:
        raise LookupError("版本不存在")
    src = _abs(snap.storage_path)
    if not os.path.isfile(src):
        raise FileNotFoundError("版本文件已丢失")

    snapshot(fm, user)
    # 物理路径若与他人共享（秒传），另存新路径，避免覆盖别人文件
    shared = FileMeta.objects.filter(storage_path=fm.storage_path).exclude(pk=fm.pk).exists()
    if shared:
        ext = os.path.splitext(fm.storage_path)[1]
        rel = f"files/{fm.owner_id}/{timezone.now():%Y%m}/{uuid.uuid4().hex[:8]}{ext}"
    else:
        rel = fm.storage_path
    dst = _abs(rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    fm.storage_path = rel
    fm.size = os.path.getsize(dst)
    fm.sha1 = _sha1(dst)
    fm.save(update_fields=["storage_path", "size", "sha1", "updated_at"])
    return fm
