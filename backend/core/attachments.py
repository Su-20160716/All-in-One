"""F05 跨模块附件引用：任意业务对象都能以 file_id 引用文件。

用法：
    from core.attachments import link, unlink, referenced_ids
    link(note, [12, 13])
    unlink(card, [12])
    referenced_ids([12, 13])  # -> {12}
"""

from core.models import AttachmentRef

MAX_REFS = 500


def _target(obj):
    meta = obj._meta
    return f"{meta.app_label}.{meta.model_name}", int(obj.pk)


def _clean_ids(file_ids):
    out = []
    for raw in file_ids or []:
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid > 0:
            out.append(fid)
    return out[:MAX_REFS]


def link(owner_obj, file_ids):
    """建立引用（幂等），返回实际新增条数。"""
    module, oid = _target(owner_obj)
    ids = _clean_ids(file_ids)
    if not ids:
        return 0
    existing = set(
        AttachmentRef.objects.filter(file_id__in=ids, module=module, object_id=oid)
        .values_list("file_id", flat=True)
    )
    rows = [AttachmentRef(file_id=fid, module=module, object_id=oid) for fid in ids if fid not in existing]
    if rows:
        AttachmentRef.objects.bulk_create(rows, ignore_conflicts=True, batch_size=200)
    return len(rows)


def unlink(owner_obj, file_ids=None):
    """解除引用；file_ids 为空时解除该对象全部引用。返回删除条数。"""
    module, oid = _target(owner_obj)
    qs = AttachmentRef.objects.filter(module=module, object_id=oid)
    ids = _clean_ids(file_ids)
    if ids:
        qs = qs.filter(file_id__in=ids)
    return qs.delete()[0]


def referenced_ids(file_ids):
    """返回其中仍被任何对象引用的文件 id 集合。"""
    ids = _clean_ids(file_ids)
    if not ids:
        return set()
    return set(AttachmentRef.objects.filter(file_id__in=ids).values_list("file_id", flat=True))
