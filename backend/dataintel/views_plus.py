# -*- coding: utf-8 -*-
"""dataintel · 增强面（F48–F50）：数据集版本 / 图表落盘 / 数据质量报告。

F48 版本快照的 rows 只落 MEDIA 下的 JSON 文件（DB 只存行数 / 哈希 / storage_path），
MEDIA 不可写时回退为内联存储；读取时两者皆兼容（#86）；
F49 只接受 png/jpeg/webp/svg 的 data URL，SVG 做脚本/事件属性清洗；
F50 复刻 Excel「数据质量」口径：缺失、类型不一致、IQR 异常、重复行。
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from core.scoping import is_visible
from dataintel.models import Dataset, DatasetVersion
from dataintel.statkit import quantile
from dataintel.views_data import load_rows
from devtools.common import endpoint, ok, opt_str, p, req_str

MAX_VERSIONS = 30


# =====================================================================
# F48 数据集版本
# =====================================================================


def _rows_hash(rows):
    payload = json.dumps(rows or [], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_dataset(user, pk):
    try:
        ds = Dataset.objects.get(pk=int(pk))
    except (Dataset.DoesNotExist, TypeError, ValueError):
        raise ValueError("数据集不存在")
    if not is_visible(ds, user):
        raise ValueError("无权访问该数据集")
    return ds


def snapshot_version(ds, user=None, note=""):
    """按当前内容建版本；内容与上一版相同则不重复建。失败只记日志，不影响主流程。

    #86：rows 只落 JSON 文件，DB 行仅保留 row_count / rows_hash / storage_path；
    文件写失败时才回退为「内联 rows」，保证 MEDIA 不可写时回滚仍然可用。
    """
    rows = ds.rows or []
    h = _rows_hash(rows)
    last = ds.versions.order_by("-version").first()
    if last is not None and last.rows_hash == h:
        return last
    version = (last.version if last else 0) + 1
    path = ""
    try:
        payload = json.dumps({"columns": ds.columns or [], "rows": rows},
                             ensure_ascii=False).encode("utf-8")
        path = default_storage.save(
            f"dataset_versions/{ds.id}/v{version}-{h[:8]}.json", ContentFile(payload))
    except Exception:  # noqa: BLE001 —— 磁盘不可写时仍以内联快照为准
        path = ""
    obj = DatasetVersion.objects.create(
        dataset=ds, version=version, rows_hash=h, row_count=len(rows),
        columns=ds.columns or [], rows=[] if path else rows, storage_path=path,
        note=note[:200], created_by=user if getattr(user, "pk", None) else None,
    )
    stale = list(ds.versions.order_by("-version").values_list("pk", "storage_path")[MAX_VERSIONS:])
    if stale:
        for _, sp in stale:
            if sp:
                try:
                    default_storage.delete(sp)
                except Exception:  # noqa: BLE001
                    pass
        DatasetVersion.objects.filter(pk__in=[pk for pk, _ in stale]).delete()
    return obj


def _version_rows(v):
    """#86：读取版本行数据。

    新版本 rows 落文件、DB 只留 storage_path；老版本（或文件不可写时的降级版）
    仍然内联在 ``rows`` 里，读取顺序为「内联 → 文件 → 空」。
    """
    rows = v.rows or []
    if rows:
        return rows
    path = (v.storage_path or "").strip()
    if not path:
        return []
    try:
        with default_storage.open(path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
        data = payload.get("rows") if isinstance(payload, dict) else None
        return data or []
    except Exception:  # noqa: BLE001 —— 文件损坏/被清理时降级为空，不 500
        return []


def _version_dict(v, current_version=None):
    return {
        "id": v.pk,
        "version": v.version,
        "row_count": v.row_count,
        "rows_hash": (v.rows_hash or "")[:12],
        "columns": v.columns or [],
        "note": v.note,
        "storage_path": v.storage_path,
        "created_by": v.created_by.username if v.created_by else "",
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "virtual": False,
        "current": current_version is not None and v.version == current_version,
    }


@endpoint(("GET",))
def dataset_versions(request, pk):
    """版本列表；从未导入过的老数据集按 v1 虚拟条目返回，不影响既有接口。"""
    ds = _get_dataset(request.user, pk)
    items = list(ds.versions.all()[:100])
    if not items:
        return ok({"dataset_id": ds.id, "items": [{
            "id": None, "version": 1, "row_count": len(ds.rows or []), "rows_hash": "",
            "columns": ds.columns or [], "note": "当前内容（历史版本未记录）", "storage_path": "",
            "created_by": "", "created_at": None, "virtual": True, "current": True,
        }], "count": 1, "current": 1, "virtual": True})
    current = max(v.version for v in items)
    return ok({"dataset_id": ds.id,
               "items": [_version_dict(v, current) for v in items],
               "count": len(items), "current": current, "virtual": False,
               "max_versions": MAX_VERSIONS})


def _load_version_side(ds, raw):
    """把 a/b 参数解析成 (label, columns, rows)。

    raw 支持版本号、"current"/"latest"；版本号不存在且没有历史时回落到当前内容。
    """
    if raw in (None, "", "current", "latest", "0"):
        return ("current", ds.columns or [], ds.rows or [])
    try:
        vno = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"版本号非法：{raw}")
    v = ds.versions.filter(version=vno).first()
    if v is not None:
        return (f"v{v.version}", v.columns or [], _version_rows(v))
    has_versions = ds.versions.exists()
    if not has_versions and vno == 1:
        return ("v1", ds.columns or [], ds.rows or [])
    raise ValueError(f"版本 v{vno} 不存在")


@endpoint(("GET",))
def dataset_version_diff(request, pk):
    """按行位序对比两个版本：新增/删除/变更行 + 列增减。"""
    ds = _get_dataset(request.user, pk)
    a_raw, b_raw = p(request, "a"), p(request, "b")
    a_label, a_cols, a_rows = _load_version_side(ds, a_raw)
    b_label, b_cols, b_rows = _load_version_side(ds, b_raw)

    n = min(len(a_rows), len(b_rows))
    changed = []
    unchanged = 0
    field_hits = {}
    for i in range(n):
        ra, rb = a_rows[i], b_rows[i]
        if ra == rb:
            unchanged += 1
            continue
        keys = sorted({k for k in ra if ra.get(k) != rb.get(k)} |
                      {k for k in rb if ra.get(k) != rb.get(k)})
        for k in keys:
            field_hits[k] = field_hits.get(k, 0) + 1
        if len(changed) < 50:
            changed.append({"index": i, "fields": keys,
                            "before": {k: ra.get(k) for k in keys},
                            "after": {k: rb.get(k) for k in keys}})

    a_only = len(a_rows) - n
    b_only = len(b_rows) - n
    return ok({
        "a": {"label": a_label, "row_count": len(a_rows), "columns": a_cols},
        "b": {"label": b_label, "row_count": len(b_rows), "columns": b_cols},
        "summary": {
            "unchanged": unchanged,
            "changed": sum(1 for i in range(n) if a_rows[i] != b_rows[i]),
            "added": b_only,
            "removed": a_only,
            "same_content": _rows_hash(a_rows) == _rows_hash(b_rows),
        },
        "columns": {
            "added": [c for c in b_cols if c not in a_cols],
            "removed": [c for c in a_cols if c not in b_cols],
        },
        "field_changes": [{"field": k, "rows": v}
                          for k, v in sorted(field_hits.items(), key=lambda kv: -kv[1])[:30]],
        "changes": changed,
        "changes_truncated": len(changed) >= 50,
    })


@endpoint(("POST",))
def dataset_version_rollback(request, pk, vid):
    """回滚到指定版本：恢复 rows/columns，并记一版「回滚」快照（历史不丢）。"""
    ds = _get_dataset(request.user, pk)
    if not getattr(request.user, "is_staff", False) and not getattr(request.user, "is_superuser", False):
        if ds.owner_id != request.user.id:
            raise ValueError("仅数据集所有者可回滚")
    try:
        v = ds.versions.get(pk=int(vid))
    except (DatasetVersion.DoesNotExist, TypeError, ValueError):
        raise ValueError("版本不存在")
    ds.rows = list(_version_rows(v))
    ds.columns = list(v.columns or [])
    ds.save()
    new = snapshot_version(ds, request.user, note=f"回滚到 v{v.version}")
    return ok({"id": ds.id, "row_count": ds.row_count, "restored_from": v.version,
               "version": new.version, "rolled_back_at": timezone.now().isoformat()})


# =====================================================================
# F49 图表导出落盘
# =====================================================================

_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|svg\+xml);base64,(.+)$", re.S | re.I)
MAX_IMAGE_BYTES = 2 * 1024 * 1024
_SVG_BAD_RE = re.compile(r"<script|javascript:|on[a-z]+\s*=", re.I)


def _safe_name(title, ext):
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5_-]+", "-", (title or "").strip())[:40].strip("-")
    return f"{base or 'chart'}-{uuid.uuid4().hex[:8]}.{ext}"


@endpoint()
def chart_save(request):
    """把前端 canvas/SVG 导出的 data URL 存到 media/charts/，返回可分享链接。"""
    import base64

    raw = req_str(request, "data_url").strip()
    m = _DATA_URL_RE.match(raw)
    if not m:
        raise ValueError("data_url 必须是 image/png|jpeg|webp|svg+xml 的 base64 data URL")
    kind = m.group(1).lower()
    ext = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp", "svg+xml": "svg"}[kind]
    try:
        blob = base64.b64decode(m.group(2), validate=True)
    except Exception:
        raise ValueError("data_url 的 base64 内容非法")
    if not blob:
        raise ValueError("图片内容为空")
    if len(blob) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 2MB，请降低分辨率后重试")
    if ext == "png" and not blob.startswith(b"\x89PNG"):
        raise ValueError("PNG 文件头校验失败")
    if ext == "jpg" and not blob.startswith(b"\xff\xd8"):
        raise ValueError("JPEG 文件头校验失败")
    if ext == "svg":
        text = blob.decode("utf-8", errors="ignore")
        if _SVG_BAD_RE.search(text):
            raise ValueError("SVG 含脚本或事件属性，已拒绝保存")
    title = opt_str(request, "title", "chart")[:80]
    name = _safe_name(title, ext)
    path = default_storage.save(f"charts/{name}", ContentFile(blob))
    url = default_storage.url(path)
    return ok({"path": path, "url": url, "name": name, "size": len(blob),
               "format": ext, "title": title,
               "note": "图片存于 media/charts/，可直接嵌入报告或分享链接"})


# =====================================================================
# F50 数据质量报告
# =====================================================================

_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")
_NUM_STR_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _kind(v):
    if v is None:
        return "missing"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return "blank"
        if _NUM_STR_RE.match(s):
            return "number"
        if _DATE_RE.match(s):
            return "date"
        return "string"
    return "other"


def _to_float(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


@endpoint()
def data_quality(request):
    """逐列质量体检：缺失/空白、类型不一致、IQR 异常值、重复行，并给 0–100 分。"""
    rows, ds = load_rows(request)
    if not rows:
        raise ValueError("rows 为空，无法体检")
    total = len(rows)
    fields = sorted({k for r in rows for k in r})
    if len(fields) > 200:
        raise ValueError("字段数超过 200，请先用 transform 裁剪")
    key_fields = p(request, "key_fields")
    if isinstance(key_fields, str):
        key_fields = [k.strip() for k in key_fields.split(",") if k.strip()]

    issues = []
    col_reports = []
    outlier_cells = 0
    for f in fields:
        vals = [r.get(f) for r in rows]
        kinds = [_kind(v) for v in vals]
        missing = sum(1 for k in kinds if k == "missing")
        blank = sum(1 for k in kinds if k == "blank")
        non_null = total - missing - blank
        present = [k for k in kinds if k not in ("missing", "blank")]
        type_counts = {}
        for k in present:
            type_counts[k] = type_counts.get(k, 0) + 1
        dominant = max(type_counts, key=type_counts.get) if type_counts else "missing"
        dominant_share = round(type_counts.get(dominant, 0) / len(present), 4) if present else 0.0
        inconsistent = bool(present) and len(type_counts) > 1 and dominant_share < 0.9

        nums = [x for x in (_to_float(v) for v in vals) if x is not None]
        outlier_info = None
        outliers = []
        if len(nums) >= 8:
            q1, q3 = quantile(nums, 0.25), quantile(nums, 0.75)
            iqr = q3 - q1
            if iqr > 0:
                lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                outliers = [x for x in nums if x < lo or x > hi]
                outlier_info = {"low": round(lo, 4), "high": round(hi, 4),
                                "count": len(outliers),
                                "pct": round(len(outliers) / len(nums) * 100, 2),
                                "samples": [round(x, 6) for x in outliers[:5]]}
                outlier_cells += len(outliers)

        distinct = len({json.dumps(v, ensure_ascii=False, sort_keys=True) for v in vals if v not in (None, "")})
        item = {
            "field": f,
            "non_null": non_null,
            "missing": missing,
            "blank": blank,
            "missing_pct": round((missing + blank) / total * 100, 2),
            "types": type_counts,
            "dominant_type": dominant,
            "dominant_share": dominant_share,
            "type_inconsistent": inconsistent,
            "distinct": distinct,
            "unique_ratio": round(distinct / total, 4),
            "outliers": outlier_info,
        }
        col_reports.append(item)

        if item["missing_pct"] >= 50:
            issues.append({"level": "high", "field": f, "kind": "missing",
                           "message": f"缺失/空白 {item['missing_pct']}%（{missing + blank}/{total}）"})
        elif item["missing_pct"] >= 10:
            issues.append({"level": "medium", "field": f, "kind": "missing",
                           "message": f"缺失/空白 {item['missing_pct']}%"})
        if inconsistent:
            minority = sorted(type_counts.items(), key=lambda kv: kv[1])[0]
            issues.append({"level": "medium", "field": f, "kind": "type",
                           "message": f"类型不一致：{minority[0]} 占 {minority[1]}/{len(present)}"})
        if outlier_info and outlier_info["pct"] >= 5:
            issues.append({"level": "low", "field": f, "kind": "outlier",
                           "message": f"IQR 异常值 {outlier_info['count']} 个（{outlier_info['pct']}%）"})

    hashes = [_rows_hash([r]) for r in rows]
    dup_rows = len(hashes) - len(set(hashes))
    if dup_rows:
        issues.append({"level": "high" if dup_rows / total > 0.1 else "medium",
                       "field": None, "kind": "duplicate_row",
                       "message": f"完全重复行 {dup_rows} 条（{round(dup_rows / total * 100, 2)}%）"})

    key_dup = None
    if key_fields:
        missing_keys = [k for k in key_fields if k not in fields]
        if missing_keys:
            raise ValueError(f"key_fields 不存在：{', '.join(missing_keys)}")
        seen = {}
        for r in rows:
            key = json.dumps([r.get(k) for k in key_fields], ensure_ascii=False, sort_keys=True)
            seen[key] = seen.get(key, 0) + 1
        dup_keys = sum(c - 1 for c in seen.values() if c > 1)
        key_dup = {"fields": key_fields, "groups": sum(1 for c in seen.values() if c > 1),
                   "extra_rows": dup_keys}
        if dup_keys:
            issues.append({"level": "high", "field": ",".join(key_fields), "kind": "duplicate_key",
                           "message": f"主键重复 {dup_keys} 行（{key_dup['groups']} 组）"})

    avg_missing = sum(c["missing_pct"] for c in col_reports) / len(col_reports)
    inconsistent_n = sum(1 for c in col_reports if c["type_inconsistent"])
    dup_pct = dup_rows / total * 100
    outlier_pct = outlier_cells / (total * max(1, len(fields))) * 100
    score = 100.0 - min(30.0, avg_missing * 0.6) - min(15.0, inconsistent_n * 3.0) \
        - min(20.0, dup_pct * 0.4) - min(10.0, outlier_pct * 6)
    score = round(max(0.0, min(100.0, score)), 1)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"

    return ok({
        "dataset": {"id": ds.id if ds else None, "name": ds.name if ds else "临时数据"},
        "total_rows": total,
        "total_fields": len(fields),
        "total_cells": total * len(fields),
        "duplicate_rows": dup_rows,
        "duplicate_pct": round(dup_pct, 2),
        "key_duplicates": key_dup,
        "fields": col_reports,
        "issues": issues[:100],
        "issue_count": len(issues),
        "score": score,
        "grade": grade,
        "generated_at": timezone.now().isoformat(),
    })
