"""F03 通用导入导出框架。

导出：GET  /api/core/io/<app>/export/?fmt=csv|json
导入：POST /api/core/io/<app>/import/   （file 字段上传 .csv/.json，可选 mapping）
各模块只需在 EXPORTERS / IMPORTERS 中声明字段映射，不触碰既有导入实现。
"""
import csv
import io
import json

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header

MAX_EXPORT_ROWS = 5000
MAX_IMPORT_ROWS = 2000
MAX_IMPORT_BYTES = 5 * 1024 * 1024


def _export_files(request):
    from files.models import FileMeta

    fields = ["id", "name", "size", "kind", "ext", "folder", "is_star", "description", "created_at"]
    qs = (
        FileMeta.objects.filter(owner=request.user, is_deleted=False)
        .select_related("folder")
        .order_by("-created_at")[:MAX_EXPORT_ROWS]
    )
    rows = [
        {
            "id": f.id,
            "name": f.name,
            "size": f.size,
            "kind": f.kind,
            "ext": f.ext,
            "folder": f.folder.name if f.folder else "",
            "is_star": int(f.is_star),
            "description": f.description,
            "created_at": f.created_at.isoformat(timespec="seconds"),
        }
        for f in qs
    ]
    return "files", fields, rows


def _export_notes(request):
    from notes.models import Note

    fields = ["id", "title", "content", "is_public", "is_archived", "folder", "words", "created_at", "updated_at"]
    qs = (
        Note.objects.filter(owner=request.user, is_deleted=False)
        .select_related("folder")
        .order_by("-updated_at")[:MAX_EXPORT_ROWS]
    )
    rows = [
        {
            "id": n.id,
            "title": n.title,
            "content": n.content,
            "is_public": int(n.is_public),
            "is_archived": int(n.is_archived),
            "folder": n.folder.name if n.folder_id else "",
            "words": n.words,
            "created_at": n.created_at.isoformat(timespec="seconds"),
            "updated_at": n.updated_at.isoformat(timespec="seconds"),
        }
        for n in qs
    ]
    return "notes", fields, rows


def _export_projects(request):
    from projects.models import Project

    fields = ["id", "name", "description", "is_archived", "created_at"]
    qs = Project.objects.filter(owner=request.user).order_by("-created_at")[:MAX_EXPORT_ROWS]
    rows = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "is_archived": int(p.is_archived),
            "created_at": p.created_at.isoformat(timespec="seconds"),
        }
        for p in qs
    ]
    return "projects", fields, rows


def _export_tasks(request):
    from projects.models import TaskCard

    fields = ["id", "number", "title", "description", "status", "priority", "due_date", "board", "project"]
    qs = (
        TaskCard.objects.filter(board__project__owner=request.user)
        .select_related("board", "board__project")
        .order_by("-id")[:MAX_EXPORT_ROWS]
    )
    rows = [
        {
            "id": c.id,
            "number": c.number,
            "title": c.title,
            "description": c.description,
            "status": c.status,
            "priority": c.priority,
            "due_date": c.due_date.isoformat() if c.due_date else "",
            "board": c.board.name,
            "project": c.board.project.name,
        }
        for c in qs
    ]
    return "tasks", fields, rows


EXPORTERS = {
    "files": _export_files,
    "notes": _export_notes,
    "projects": _export_projects,
    "tasks": _export_tasks,
}


def _import_notes(request, rows, mapping):
    from notes.models import Note, NoteTag

    created, errors = 0, []
    for idx, raw in enumerate(rows, start=1):
        data = {mapping.get(k, k): v for k, v in raw.items()} if mapping else dict(raw)
        title = str(data.get("title") or "").strip()[:200]
        if not title:
            errors.append({"row": idx, "message": "标题不能为空"})
            continue
        try:
            with transaction.atomic():
                note = Note.objects.create(
                    owner=request.user,
                    title=title,
                    content=str(data.get("content") or ""),
                    is_public=str(data.get("is_public") or "").lower() in ("1", "true", "yes"),
                    source="import",
                )
                tag_text = str(data.get("tags") or "").strip()
                if tag_text:
                    for name in [t.strip() for t in tag_text.replace("，", ",").split(",") if t.strip()][:10]:
                        tag, _ = NoteTag.objects.get_or_create(owner=request.user, name=name[:50])
                        note.tags.add(tag)
            created += 1
        except Exception as exc:
            errors.append({"row": idx, "message": f"{type(exc).__name__}: {exc}"[:160]})
        if len(errors) >= 200:
            errors.append({"row": idx, "message": "错误过多，已中止"})
            break
    return created, errors


IMPORTERS = {"notes": _import_notes}


def _parse_upload(upload):
    name = (getattr(upload, "name", "") or "").lower()
    if upload.size > MAX_IMPORT_BYTES:
        raise ValueError("导入文件不能超过 5MB")
    raw = upload.read()
    # 浏览器上传必带文件名；无扩展名时按内容嗅探，避免代理改名导致误拒
    if not name.endswith((".json", ".csv")):
        head = raw.lstrip()[:1]
        name = "upload.json" if head in (b"{", b"[") else "upload.csv"
    if name.endswith(".json"):
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("JSON 格式非法")
        if isinstance(data, dict):
            data = data.get("rows") or data.get("list") or []
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError("JSON 需为对象数组")
        return data
    text = raw.decode("utf-8-sig", "ignore")
    return [r for r in csv.DictReader(io.StringIO(text)) if any((v or "").strip() for v in r.values())]


def export_response(app, request):
    exporter = EXPORTERS.get(app)
    if exporter is None:
        raise ValueError(f"不支持的模块：{app}（可选 {'/'.join(EXPORTERS)}）")
    fmt = (request.query_params.get("fmt") or "csv").lower()
    if fmt not in ("csv", "json"):
        raise ValueError("fmt 只能是 csv 或 json")
    _app, fields, rows = exporter(request)
    stamp = timezone.localdate().isoformat()
    if fmt == "json":
        body = json.dumps({"fields": fields, "rows": rows}, ensure_ascii=False).encode("utf-8")
        resp = HttpResponse(body, content_type="application/json; charset=utf-8")
        filename = f"{app}-{stamp}.json"
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        resp = HttpResponse(("\ufeff" + buf.getvalue()).encode("utf-8"), content_type="text/csv; charset=utf-8")
        filename = f"{app}-{stamp}.csv"
    resp["Content-Disposition"] = content_disposition_header(True, filename)
    resp["X-Total-Rows"] = str(len(rows))
    return resp


def import_response(app, request):
    importer = IMPORTERS.get(app)
    if importer is None:
        raise ValueError(f"该模块暂不支持导入：{app}（可选 {'/'.join(IMPORTERS)}）")
    upload = request.FILES.get("file")
    if upload is None:
        raise ValueError("请上传文件（file 字段）")
    rows = _parse_upload(upload)
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"单次最多导入 {MAX_IMPORT_ROWS} 行")
    mapping = request.data.get("mapping") or {}
    if isinstance(mapping, str):
        try:
            mapping = json.loads(mapping)
        except json.JSONDecodeError:
            raise ValueError("mapping 必须是 JSON 对象")
    if not isinstance(mapping, dict):
        raise ValueError("mapping 必须是 JSON 对象")
    created, errors = importer(request, rows, mapping)
    return {
        "created": created,
        "failed": len(errors),
        "total": len(rows),
        "errors": errors[:200],
        "preview": rows[:3],
    }
