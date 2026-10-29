# -*- coding: utf-8 -*-
"""minitools · 媒体与批量哈希（F42 图片压缩 / F44 哈希批量）。"""
import base64
import binascii
import hashlib
import io

from devtools.common import endpoint, ok, opt_num, opt_str, req_list

_ALGOS = {
    "md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512,
}


def _decode_data_url(raw):
    """接受 data URL 或裸 base64，返回 bytes。"""
    text = str(raw or "")
    if not text:
        raise ValueError("缺少图片/文件数据")
    if text.startswith("data:"):
        text = text.split(",", 1)[1] if "," in text else ""
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("base64 数据非法")


def _image_bytes(payload):
    from PIL import Image

    data = _decode_data_url(payload)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("输入图片超过 10MB 上限")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise ValueError("不是可识别的图片格式")
    if img.width * img.height > 40_000_000:
        raise ValueError("图片像素超过 4000 万上限")
    return img, data


@endpoint()
def image_compress(request):
    """F42 图片压缩 / 格式转换，返回 data URL（不落盘）"""
    img, original = _image_bytes(opt_str(request, "data") or opt_str(request, "data_url"))
    quality = int(opt_num(request, "quality", 80, minimum=1, maximum=95, integer=True))
    max_side = int(opt_num(request, "max_side", 1600, minimum=32, maximum=8000, integer=True))
    fmt = opt_str(request, "format", "webp").lower()
    fmt = {"jpg": "jpeg"}.get(fmt, fmt)
    if fmt not in ("jpeg", "png", "webp"):
        raise ValueError("format 只能是 jpeg/png/webp")
    before = [img.width, img.height]
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
    if fmt in ("jpeg", "webp") and img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if fmt == "jpeg" and img.mode == "RGBA":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format=fmt.upper(), quality=quality, optimize=True)
    out = buf.getvalue()
    mime = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[fmt]
    return ok({
        "data_url": f"data:{mime};base64,{base64.b64encode(out).decode()}",
        "format": fmt, "quality": quality,
        "original_bytes": len(original), "result_bytes": len(out),
        "ratio": round(len(out) / len(original), 4) if original else 0,
        "original_size": before, "result_size": [img.width, img.height],
    })


@endpoint()
def hash_batch(request):
    """F44 批量文本/文件哈希（data URL 输入分块计算）"""
    items = req_list(request, "items")
    if not isinstance(items, list) or not items:
        raise ValueError("items 必须是非空数组")
    if len(items) > 100:
        raise ValueError("单次最多 100 项")
    algos = request.data.get("algorithms") if hasattr(request, "data") else None
    if not algos:
        algos = ["md5", "sha1", "sha256"]
    if not isinstance(algos, list) or any(a not in _ALGOS for a in algos):
        raise ValueError("algorithms 只能包含 md5/sha1/sha256/sha512")
    rows = []
    for idx, item in enumerate(items):
        try:
            if isinstance(item, dict):
                raw = item.get("data") or item.get("data_url")
                if raw:
                    payload = _decode_data_url(raw)
                    if len(payload) > 10 * 1024 * 1024:
                        raise ValueError("单项超过 10MB 上限")
                    source = "file"
                else:
                    payload = str(item.get("text") or "").encode("utf-8")
                    source = "text"
            else:
                payload = str(item).encode("utf-8")
                source = "text"
            hashes = {a: _ALGOS[a](payload).hexdigest() for a in algos}
            rows.append({"index": idx, "ok": True, "source": source,
                         "bytes": len(payload), "hashes": hashes})
        except ValueError as e:
            rows.append({"index": idx, "ok": False, "error": str(e)})
    failed = sum(1 for r in rows if not r["ok"])
    return ok({"items": rows, "total": len(rows), "failed": failed, "algorithms": algos})
