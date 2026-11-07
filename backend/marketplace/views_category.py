# -*- coding: utf-8 -*-
"""应用市场 · 分类接口（4 个）。

分类维护属于平台治理动作，创建/修改/删除仅管理员；读取对所有登录用户开放。
删除前必须为空（无子分类、无应用），避免出现孤儿应用指向不存在的分类。
"""
from django.db import transaction

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p, req_str

from .common import (get_category, is_staff_user, page_params,
                     paginate_queryset, require_staff, valid_slug)
from .models import Category, Listing
from .serializers import category_dict, category_tree


def _parent_for(request, exclude=None):
    """解析上级分类并阻止形成环（父级不能是自身或自己的后代）。"""
    parent_id = opt_num(request, "parent_id", integer=True)
    if not parent_id:
        return None
    parent = Category.objects.filter(pk=int(parent_id)).first()
    if parent is None:
        raise ValueError("上级分类不存在")
    if exclude is not None:
        if parent.id == exclude.id:
            raise ValueError("上级分类不能是自己")
        node = parent
        depth = 0
        while node is not None and depth < 20:
            if node.id == exclude.id:
                raise ValueError("上级分类不能是自己的子分类")
            node = node.parent
            depth += 1
    return parent


@endpoint(("GET", "POST"))
def categories(request):
    """分类列表（q/status 分页）或创建分类（仅管理员）。"""
    if request.method == "GET":
        queryset = Category.objects.select_related("parent").order_by("order", "id")
        status = opt_str(request, "status").strip()
        if status:
            if status not in ("active", "inactive"):
                raise ValueError("status 支持 active/inactive")
            queryset = queryset.filter(active=(status == "active"))
        data = paginate_queryset(
            request, queryset, category_dict,
            search_fields=("name", "code", "description"), status_field=None,
        )
        # 附带每个分类的应用数，列表页无需再逐个请求
        for item in data["items"]:
            item["listing_count"] = Listing.objects.filter(
                category_id=item["id"], status="published").count()
        return ok(data)

    require_staff(request.user, "仅管理员可管理分类")
    code = valid_slug(opt_str(request, "code").strip()
                      or f"cat-{Category.objects.count() + 1}")
    if Category.objects.filter(code=code).exists():
        raise ValueError(f"分类编码 {code} 已存在")
    name = req_str(request, "name", max_len=80).strip()
    if not name:
        raise ValueError("分类名称不能为空")
    category = Category.objects.create(
        owner=request.user,
        code=code,
        name=name[:80],
        parent=_parent_for(request),
        order=int(opt_num(request, "order", 0, minimum=0, maximum=100000, integer=True)),
        icon=opt_str(request, "icon", max_len=120),
        active=opt_bool(request, "active", True),
        description=opt_str(request, "description", max_len=300),
    )
    return ok(category_dict(category, with_counts=True))


@endpoint(("GET",))
def categories_tree(request):
    """分类树（默认只含启用分类；管理员 all=1 可含停用分类）。"""
    include_inactive = is_staff_user(request.user) and opt_bool(request, "all", False)
    roots = category_tree()
    if not include_inactive:
        def prune(nodes):
            result = []
            for node in nodes:
                if not node.get("active", True):
                    continue
                node["children"] = prune(node.get("children") or [])
                result.append(node)
            return result
        roots = prune(roots)
    return ok({"items": roots, "count": len(roots)})


@endpoint()
def category_update(request, pk):
    """更新分类（仅管理员；编码可改但需唯一，父级不能成环）。"""
    require_staff(request.user, "仅管理员可管理分类")
    category = get_category(pk)
    if p(request, "code") is not None:
        code = valid_slug(p(request, "code"), "分类编码")
        if Category.objects.filter(code=code).exclude(pk=category.pk).exists():
            raise ValueError(f"分类编码 {code} 已存在")
        category.code = code
    if p(request, "name") is not None:
        name = str(p(request, "name")).strip()
        if not name:
            raise ValueError("分类名称不能为空")
        category.name = name[:80]
    if p(request, "parent_id") is not None:
        category.parent = None if p(request, "parent_id") in ("", None) else _parent_for(
            request, exclude=category)
    if p(request, "order") not in (None, ""):
        category.order = int(opt_num(request, "order", category.order,
                                     minimum=0, maximum=100000, integer=True))
    if p(request, "icon") is not None:
        category.icon = str(p(request, "icon"))[:120]
    if p(request, "active") is not None:
        category.active = opt_bool(request, "active", category.active)
    if p(request, "description") is not None:
        category.description = str(p(request, "description"))[:300]
    category.save()
    return ok(category_dict(category, with_counts=True))


@endpoint()
def category_delete(request, pk):
    """删除分类（仅管理员；有子分类或应用时拒绝）。"""
    require_staff(request.user, "仅管理员可管理分类")
    category = get_category(pk)
    if category.mp_children.exists():
        raise ValueError("该分类下还有子分类，请先删除或转移子分类")
    if Listing.objects.filter(category=category).exists():
        count = Listing.objects.filter(category=category).count()
        raise ValueError(f"该分类下还有 {count} 个应用，请先转移应用")
    cid, code = category.id, category.code
    category.delete()
    return ok({"deleted": True, "id": cid, "code": code})


CATEGORY_ENDPOINT_COUNT = 4
