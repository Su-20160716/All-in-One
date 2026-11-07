# -*- coding: utf-8 -*-
"""minitools · 媒体与批量哈希（F42 图片压缩 / F44 哈希批量）。"""
import base64
import binascii
import hashlib
import io

from devtools.common import endpoint, ok, opt_num, opt_str, req_list, req_str

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


# =====================================================================
# 第三轮 S26（403/404）：图片元信息 / 文字水印
# =====================================================================

MAX_INPUT_BYTES = 5 * 1024 * 1024   # 5MB 上限，压制解压炸弹
MAX_SIDE_PX = 6000                  # 单边 6000px 上限


def _open_image_limited(payload):
    """按 5MB / 6000px 双闸门打开图片，返回 (img, 原始字节数)。"""
    from PIL import Image

    data = _decode_data_url(payload)
    if not data:
        raise ValueError("图片数据为空")
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"输入图片超过 {MAX_INPUT_BYTES // (1024 * 1024)}MB 上限")
    try:
        probe = Image.open(io.BytesIO(data))
        width, height = probe.size
        # 先看头部尺寸，避免 6 万 × 6 万的「解压炸弹」在 decode 时吃满内存
        if width > MAX_SIDE_PX or height > MAX_SIDE_PX:
            raise ValueError(f"图片单边超过 {MAX_SIDE_PX}px 上限（{width}×{height}）")
        probe.verify()
        img = Image.open(io.BytesIO(data))
    except ValueError:
        raise
    except Exception:
        raise ValueError("不是可识别的图片格式")
    return img, len(data)


def _json_safe(value):
    """EXIF 值转 JSON 友好类型（bytes/IFDRational 等一律降级为字符串）。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)[:120]


_KEY_EXIF = {
    271: "Make", 272: "Model", 274: "Orientation", 305: "Software",
    306: "DateTime", 36867: "DateTimeOriginal", 36868: "DateTimeDigitized",
    33434: "ExposureTime", 33437: "FNumber", 34855: "ISO",
    37386: "FocalLength", 42036: "LensModel", 40962: "ExifImageWidth",
    40963: "ExifImageHeight",
}


@endpoint()
def image_info(request):
    """403 图片元信息：格式 / 宽高 / 色彩模式 / 字节数 / EXIF 关键字段（不落盘）。"""
    img, size = _open_image_limited(opt_str(request, "data") or opt_str(request, "data_url"))
    exif, exif_count = {}, 0
    try:
        raw = img.getexif()
        exif_count = len(raw)
        for tag, name in _KEY_EXIF.items():
            if tag in raw:
                exif[name] = _json_safe(raw.get(tag))
    except Exception:  # noqa: BLE001 —— EXIF 损坏不影响主信息
        exif = {}

    info = {
        "format": (img.format or "unknown").upper(),
        "mime": img.get_format_mimetype() if hasattr(img, "get_format_mimetype") else "",
        "width": img.width,
        "height": img.height,
        "mode": img.mode,
        "bytes": size,
        "kb": round(size / 1024, 2),
        "megapixels": round(img.width * img.height / 1_000_000, 2),
        "has_alpha": img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info,
        "frames": getattr(img, "n_frames", 1),
        "is_animated": bool(getattr(img, "is_animated", False)),
        "dpi": list(img.info.get("dpi", [])) or None,
        "exif": exif,
        "exif_tags": exif_count,
    }
    if info["frames"] > 1:
        info["note"] = f"动图共 {info['frames']} 帧，仅读取首帧元信息"
    return ok(info)


_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def _load_font(px):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, px)
        except Exception:  # noqa: BLE001 —— 字体缺失继续降级
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # Pillow < 10.1 不支持 size
        return ImageFont.load_default()


def _watermark_xy(position, img_w, img_h, box_w, box_h, margin):
    pos = position.strip().lower()
    table = {
        "top-left": (margin, margin),
        "top-right": (img_w - box_w - margin, margin),
        "bottom-left": (margin, img_h - box_h - margin),
        "bottom-right": (img_w - box_w - margin, img_h - box_h - margin),
        "center": ((img_w - box_w) // 2, (img_h - box_h) // 2),
    }
    if pos not in table and pos not in ("tile", "repeat"):
        raise ValueError("position 支持 center/top-left/top-right/bottom-left/bottom-right/tile")
    return table.get(pos, (margin, margin))


@endpoint()
def image_watermark(request):
    """404 文字水印：data/text/opacity/position → 半透明叠加后返回 data URL。"""
    from PIL import ImageDraw

    img, size = _open_image_limited(opt_str(request, "data") or opt_str(request, "data_url"))
    text = req_str(request, "text", max_len=200)
    opacity_raw = float(opt_num(request, "opacity", 0.35, minimum=0, maximum=100))
    opacity = opacity_raw / 100 if opacity_raw > 1 else opacity_raw
    position = opt_str(request, "position", "bottom-right")
    font_size = int(opt_num(request, "size", 0, minimum=0, maximum=400, integer=True) or 0)
    margin = int(opt_num(request, "margin", 24, minimum=0, maximum=500, integer=True))
    out_fmt = opt_str(request, "format", "png").lower()
    if out_fmt == "jpg":
        out_fmt = "jpeg"
    if out_fmt not in ("png", "jpeg", "webp"):
        raise ValueError("format 支持 png/jpeg/webp")

    base = img.convert("RGBA")
    draw = ImageDraw.Draw(base)
    font = _load_font(font_size or max(16, int(min(base.size) / 18)))
    try:
        box = draw.textbbox((0, 0), text, font=font)
        box_w, box_h = box[2] - box[0], box[3] - box[1]
    except Exception:  # noqa: BLE001
        box_w, box_h = len(text) * (font_size or 16), (font_size or 16)
    alpha = int(max(0, min(1, opacity)) * 255)
    fill = (255, 255, 255, alpha)
    stroke = (0, 0, 0, max(0, int(alpha * 0.75)))
    drawn = 0

    if position.strip().lower() in ("tile", "repeat"):
        step_x, step_y = box_w + max(40, box_w // 4), box_h + max(40, box_h // 2)
        for y in range(margin, base.height, step_y):
            for x in range(margin, base.width, step_x):
                draw.text((x, y), text, font=font, fill=fill, stroke_width=1, stroke_fill=stroke)
                drawn += 1
                if drawn >= 400:  # 防止大图上画出几十万个水印
                    break
            if drawn >= 400:
                break
    else:
        x, y = _watermark_xy(position, base.width, base.height, box_w, box_h, margin)
        draw.text((x, y), text, font=font, fill=fill, stroke_width=1, stroke_fill=stroke)
        drawn = 1

    out_img = base.convert("RGB") if out_fmt == "jpeg" else base
    buf = io.BytesIO()
    if out_fmt == "jpeg":
        out_img.save(buf, format="JPEG", quality=90, optimize=True)
    elif out_fmt == "webp":
        out_img.save(buf, format="WEBP", quality=90, method=4)
    else:
        out_img.save(buf, format="PNG", optimize=True)
    out = buf.getvalue()
    mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[out_fmt]
    return ok({
        "data_url": f"data:{mime};base64,{base64.b64encode(out).decode()}",
        "format": out_fmt,
        "width": out_img.width,
        "height": out_img.height,
        "text": text,
        "opacity": round(opacity, 3),
        "position": position,
        "drawn": drawn,
        "bytes": len(out),
        "input_bytes": size,
        "ratio": round(len(out) / size, 3) if size else 0,
    })
