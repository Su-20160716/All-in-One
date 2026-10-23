# -*- coding: utf-8 -*-
"""代码工坊 —— 序列化助手与公共查询收口。

读与写分开：
- `ws_qs` / `file_qs` 按数据范围过滤，用于列表与详情（能看见就能读）
- `ws_write_qs` / `file_write_qs` 只含本人对象，用于所有写操作
历史上把读范围直接用于写，导致部门/全平台角色可以改删他人代码文件。
"""
from core.scoping import owner_qs, scope_queryset

from .models import CodeFile, CodeWorkspace


def ws_qs(user):
    """当前用户可见的工作区（读）。"""
    return scope_queryset(CodeWorkspace.objects.all(), user, "owner")


def ws_write_qs(user):
    """当前用户可写的工作区（仅本人）。"""
    return owner_qs(CodeWorkspace.objects.all(), user, "owner")


def get_ws(user, pk, write=False):
    qs = ws_write_qs(user) if write else ws_qs(user)
    obj = qs.filter(pk=pk).first()
    if not obj:
        raise ValueError(f"工作区不存在或无权访问: {pk}")
    return obj


def file_qs(user):
    """当前用户可见的代码文件（读）。"""
    return scope_queryset(CodeFile.objects.all(), user, "owner").select_related("workspace")


def file_write_qs(user):
    """当前用户可写的代码文件（仅本人）。"""
    return owner_qs(CodeFile.objects.all(), user, "owner").select_related("workspace")


def get_file(user, pk, write=False):
    qs = file_write_qs(user) if write else file_qs(user)
    obj = qs.filter(pk=pk).first()
    if not obj:
        raise ValueError(f"代码文件不存在或无权访问: {pk}")
    return obj


def ws_brief(obj):
    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "language": obj.language,
        "icon": obj.icon,
        "color": obj.color,
        "is_starred": obj.is_starred,
        "is_archived": obj.is_archived,
        "file_count": obj.file_count or 0,
        "total_bytes": obj.total_bytes or 0,
        "run_config": obj.run_config or {},
        "env_keys": obj.env_keys or [],
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def ws_detail(obj, include_files=False):
    data = ws_brief(obj)
    if include_files:
        data["files"] = [file_brief(f, with_content=False) for f in obj.files.all()]
    return data


def file_brief(obj, with_content=True):
    data = {
        "id": obj.id,
        "workspace": obj.workspace_id,
        "workspace_name": obj.workspace.name if obj.workspace_id else "",
        "path": obj.path,
        "name": obj.name,
        "language": obj.language,
        "size": obj.size,
        "lines": obj.lines,
        "is_entry": obj.is_entry,
        "is_favorite": obj.is_favorite,
        "order": obj.order,
        "editor_state": obj.editor_state or {},
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }
    if with_content:
        data["content"] = obj.content
    return data


def build_tree(files):
    """把扁平文件列表组装成目录树（第 77 条）。

    返回 [{type:"dir"|"file", name, path, children?, id?}]
    """
    root = {}
    for f in files:
        parts = f.path.split("/")
        cur = root
        for i, part in enumerate(parts):
            is_leaf = i == len(parts) - 1
            node = cur.setdefault(part, {"__children__": {}, "__file__": None})
            if is_leaf:
                node["__file__"] = f
            cur = node["__children__"]

    def walk(container, prefix=""):
        out = []
        for name in sorted(container.keys(), key=lambda x: (container[x]["__file__"] is not None, x.lower())):
            node = container[name]
            path = f"{prefix}{name}"
            if node["__file__"] is not None and not node["__children__"]:
                f = node["__file__"]
                out.append({
                    "type": "file",
                    "name": name,
                    "path": path,
                    "id": f.id,
                    "language": f.language,
                    "size": f.size,
                    "lines": f.lines,
                    "is_entry": f.is_entry,
                    "is_favorite": f.is_favorite,
                })
            else:
                children = walk(node["__children__"], f"{path}/")
                if node["__file__"] is not None:
                    f = node["__file__"]
                    children.insert(0, {
                        "type": "file",
                        "name": name,
                        "path": path,
                        "id": f.id,
                        "language": f.language,
                        "size": f.size,
                        "lines": f.lines,
                        "is_entry": f.is_entry,
                        "is_favorite": f.is_favorite,
                    })
                out.append({
                    "type": "dir",
                    "name": name,
                    "path": path,
                    "children": children,
                })
        return out

    return walk(root)
