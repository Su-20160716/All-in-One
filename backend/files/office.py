"""Office 文档 → PDF 转换适配器（LibreOffice headless）

设计原则
--------
**可插拔 + 优雅降级**：LibreOffice 不是必需依赖。
- 装了：自动探测 soffice 并真正转换，结果落到 MEDIA_ROOT/converted/
- 没装：返回结构化的 `LIBREOFFICE_NOT_FOUND`，附带各平台安装方式，
  接口不会 500，前端可以给出明确提示而不是"服务异常"

探测顺序：settings.SOFFICE_PATH → 环境变量 → PATH → 各平台常见安装目录
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from django.conf import settings

# 需要经 LibreOffice 转换的格式（转 PDF 后可预览 / 可抽取文本）
CONVERTIBLE_EXTS = {
    "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "odt", "ods", "odp", "rtf", "wps", "et", "dps",
}

# 各平台常见安装位置
_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    r"C:\Program Files\LibreOffice 7\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/snap/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]

INSTALL_HINT = (
    "未检测到 LibreOffice。安装后即可启用 Office 转 PDF："
    "Windows 执行 `winget install TheDocumentFoundation.LibreOffice` 或到 libreoffice.org 下载；"
    "Ubuntu/Debian 执行 `sudo apt install libreoffice`；macOS 执行 `brew install --cask libreoffice`。"
    "也可通过环境变量 SOFFICE_PATH 指定 soffice 可执行文件的完整路径。"
)


def find_soffice() -> str | None:
    """返回可用的 soffice 可执行文件路径，找不到返回 None"""
    configured = (getattr(settings, "SOFFICE_PATH", "") or os.environ.get("SOFFICE_PATH", "")).strip()
    if configured:
        if os.path.isfile(configured):
            return configured
        found = shutil.which(configured)
        if found:
            return found

    for name in ("soffice", "libreoffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found

    for path in _CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def soffice_status() -> dict:
    """给接口/健康检查用的状态描述"""
    path = find_soffice()
    return {
        "available": bool(path),
        "path": path or "",
        "hint": "" if path else INSTALL_HINT,
    }


def can_convert(ext: str) -> bool:
    return (ext or "").lower().lstrip(".") in CONVERTIBLE_EXTS


def convert_to_pdf(abs_path: str, ext: str = "", out_dir: str | None = None) -> dict:
    """把 Office 文档转成 PDF。

    :return: {"ok": bool, "path": str|None, "code": str, "message": str}
             code 取值：OK / LIBREOFFICE_NOT_FOUND / SOURCE_MISSING /
                        UNSUPPORTED_FORMAT / CONVERT_FAILED / TIMEOUT
    """
    ext = (ext or os.path.splitext(abs_path)[1].lstrip(".")).lower()
    if not abs_path or not os.path.exists(abs_path):
        return {"ok": False, "path": None, "code": "SOURCE_MISSING", "message": "源文件不存在"}
    if not can_convert(ext):
        return {"ok": False, "path": None, "code": "UNSUPPORTED_FORMAT",
                "message": f"不支持转换 .{ext} 格式（仅支持 {', '.join(sorted(CONVERTIBLE_EXTS))}）"}

    soffice = find_soffice()
    if not soffice:
        return {"ok": False, "path": None, "code": "LIBREOFFICE_NOT_FOUND", "message": INSTALL_HINT}

    target_dir = Path(out_dir or (Path(settings.MEDIA_ROOT) / "converted"))
    target_dir.mkdir(parents=True, exist_ok=True)
    # 每次转换用独立 profile，避免并发调用时 LibreOffice 抢占用户配置
    profile = target_dir / f".profile-{uuid.uuid4().hex[:8]}"
    profile_uri = "file:///" + str(profile).replace("\\", "/").lstrip("/")

    cmd = [
        soffice,
        f"-env:UserInstallation={profile_uri}",
        "--headless", "--norestore", "--invisible", "--nolockcheck",
        "--convert-to", "pdf", "--outdir", str(target_dir), str(abs_path),
    ]

    timeout = int(getattr(settings, "OFFICE_CONVERT_TIMEOUT", 120))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, cwd=str(target_dir),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        _cleanup(profile)
        return {"ok": False, "path": None, "code": "TIMEOUT",
                "message": f"转换超时（>{timeout}s），文档可能过大或格式复杂"}
    except Exception as exc:  # pragma: no cover
        _cleanup(profile)
        return {"ok": False, "path": None, "code": "CONVERT_FAILED", "message": f"调用 LibreOffice 失败：{exc}"}
    finally:
        _cleanup(profile)

    produced = target_dir / (Path(abs_path).stem + ".pdf")
    if produced.exists():
        return {"ok": True, "path": str(produced), "code": "OK", "message": "转换成功"}

    # 极端情况下 LibreOffice 输出到别处或名字不同，做一次兜底扫描
    newest = None
    for f in target_dir.glob("*.pdf"):
        if newest is None or f.stat().st_mtime > newest.stat().st_mtime:
            newest = f
    if newest and newest.stat().st_mtime >= (os.path.getmtime(abs_path) - 5):
        return {"ok": True, "path": str(newest), "code": "OK", "message": "转换成功（文件名已归一）"}

    detail = ""
    if proc.stderr:
        detail = proc.stderr.decode("utf-8", errors="ignore")[:300]
    return {"ok": False, "path": None, "code": "CONVERT_FAILED",
            "message": ("LibreOffice 未能生成 PDF" + (f"：{detail}" if detail else ""))}


def _cleanup(path: Path):
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.exception("B23：静默兜底已登记（files/office.py:152 原为 pass）——review 是否应收窄异常类型")


def relative_media_path(abs_path: str) -> str:
    """把绝对路径转成相对 MEDIA_ROOT 的存储路径"""
    try:
        return str(Path(abs_path).relative_to(Path(settings.MEDIA_ROOT))).replace(os.sep, "/")
    except Exception:
        return ""
