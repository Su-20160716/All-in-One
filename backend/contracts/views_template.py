# -*- coding: utf-8 -*-
"""contracts · 模板与条款接口（20 个）：模板 CRUD/发布/停用/克隆/渲染预览，条款库与模板条款。

约定：
- 模板是「可写资产」，只对 owner 开放写操作（core.scoping.can_write）；
- 条款库删除只停用不物理删除（库里条款被历史模板引用，删了会丢审计线索）；
- 渲染预览永远走 services.render_template，白名单与缺失校验只有一份实现。
"""
import re

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from core.scoping import can_write, scope_queryset
from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)
from contracts import services
from contracts.common import (clause_dict, has, iso, library_clause_dict,
                              list_queryset, page_payload, req_list_arg,
                              template_dict)
from contracts.models import (CONTRACT_TYPES, RISK_LEVELS, Clause,
                              ClauseLibrary, Contract, ContractTemplate)

VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _template(user, pk, write=False):
    """取模板并校验可见性/写权限；写操作额外要求 owner。"""
    from core.scoping import is_visible

    template = ContractTemplate.objects.filter(pk=pk).first()
    if template is None:
        raise ValueError("模板不存在")
    if not is_visible(template, user):
        raise ValueError("无权访问该模板")
    if write and not can_write(user, template):
        raise ValueError("无权修改该模板")
    return template


def _normalize_variables(raw):
    """变量定义规范化：统一成 [{name,label,required,default}]。

    历史数据里可能直接存 ["party_a"]，这里一并转成字典形态，
    后续渲染逻辑只需处理一种结构，避免每个调用点都做类型判断。
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError("variables 必须是数组")
    if len(raw) > 100:
        raise ValueError("variables 最多 100 项")
    out, seen = [], set()
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            label = str(item.get("label") or name)
            required = bool(item.get("required", True))
            default = item.get("default", "")
        else:
            name = str(item or "").strip()
            label, required, default = name, True, ""
        if not VARIABLE_NAME_RE.match(name):
            raise ValueError(f"变量名不合法: {name}（仅允许字母、数字、下划线）")
        if name in seen:
            raise ValueError(f"变量名重复: {name}")
        seen.add(name)
        out.append({"name": name, "label": label, "required": required,
                    "default": default})
    return out


def _bump_version(version):
    """小版本自增：v1.0 → v1.1；无法解析的数字段保持原样但追加 .1 后缀。"""
    match = re.match(r"^(v?)(\d+)\.(\d+)$", (version or "").strip())
    if not match:
        return f"{version or 'v1.0'}.1"[:20]
    return f"{match.group(1)}{match.group(2)}.{int(match.group(3)) + 1}"


def _visible_templates(user):
    return scope_queryset(ContractTemplate.objects.all(), user)


@endpoint(("GET",))
def templates(request):
    """模板列表（数据范围内，支持 q / status / 类型筛选）。"""
    qs = _visible_templates(request.user).select_related("owner")
    rows, total, page, size = list_queryset(
        request, qs, ("code", "name", "scene"),
        extra_filters={"template_type": ("template_type", str)},
    )
    return ok(page_payload([template_dict(row) for row in rows], total, page, size))


@endpoint()
def template_create(request):
    """新建模板（编码在同一用户下唯一，变量定义做格式校验）。"""
    code = req_str(request, "code", max_len=60).strip()
    if ContractTemplate.objects.filter(owner=request.user, code=code).exists():
        raise ValueError(f"模板编码已存在: {code}")
    template_type = opt_str(request, "template_type", "service")
    if template_type not in CONTRACT_TYPES:
        raise ValueError(f"合同类型不支持: {template_type}")
    row = ContractTemplate.objects.create(
        owner=request.user,
        code=code,
        name=req_str(request, "name", max_len=200),
        template_type=template_type,
        scene=opt_str(request, "scene", max_len=120),
        body=opt_str(request, "body", max_len=0),
        variables=_normalize_variables(p(request, "variables") or []),
        version=opt_str(request, "version", "v1.0", max_len=20),
        status="draft",
        remark=opt_str(request, "remark", max_len=0),
    )
    return ok(template_dict(row))


@endpoint(("GET",))
def template_detail(request, pk):
    """模板详情（含正文与条款明细）。"""
    row = _template(request.user, pk)
    data = template_dict(row, with_body=True)
    data["clauses"] = [clause_dict(item) for item in
                       row.clauses.all().order_by("order", "id")]
    return ok(data)


@endpoint()
def template_update(request, pk):
    """更新模板（局部字段；正文变更自动升小版本号并留变更摘要）。"""
    row = _template(request.user, pk, write=True)
    body_changed = has(request, "body") and p(request, "body") != row.body
    if has(request, "code"):
        code = opt_str(request, "code", max_len=60).strip()
        if code and code != row.code:
            if ContractTemplate.objects.filter(owner=request.user, code=code).exists():
                raise ValueError(f"模板编码已存在: {code}")
            row.code = code
    if has(request, "name"):
        row.name = req_str(request, "name", max_len=200)
    if has(request, "template_type"):
        value = opt_str(request, "template_type", row.template_type)
        if value not in CONTRACT_TYPES:
            raise ValueError(f"合同类型不支持: {value}")
        row.template_type = value
    if has(request, "scene"):
        row.scene = opt_str(request, "scene", max_len=120)
    if has(request, "body"):
        row.body = opt_str(request, "body", max_len=0)
    if has(request, "variables"):
        row.variables = _normalize_variables(p(request, "variables") or [])
    if has(request, "version"):
        row.version = opt_str(request, "version", row.version, max_len=20)
    if has(request, "remark"):
        row.remark = opt_str(request, "remark", max_len=0)
    if body_changed and not has(request, "version"):
        # 正文变了但调用方没给版本号：自动升小版本（v1.0 → v1.1），
        # 避免「正文改了版本没变」导致审计回放时无法区分两份不同正文。
        row.version = _bump_version(row.version)
    row.touch()
    row.save()
    return ok(template_dict(row, with_body=True))


@endpoint()
def template_delete(request, pk):
    """删除模板（仅草稿/停用可删；已发布先停用，防止在途合同引用悬空）。"""
    row = _template(request.user, pk, write=True)
    if row.status == "published":
        raise ValueError("已发布模板不能删除，请先停用")
    if row.contracts.exists():
        raise ValueError("模板已被合同引用，不能删除，请改为停用")
    template_id = row.id
    with transaction.atomic():
        row.delete()
    return ok({"deleted": True, "id": template_id})


@endpoint()
def template_publish(request, pk):
    """发布模板（草稿/停用 → 已发布；正文与变量必须自洽）。"""
    row = _template(request.user, pk, write=True)
    if row.status == "published":
        raise ValueError("模板已是发布状态")
    if not (row.body or "").strip():
        raise ValueError("模板正文不能为空")
    # 正文里的占位符必须都在变量定义中声明，否则发布后渲染必然报错
    placeholders = {match.group(1) for match in
                    services.PLACEHOLDER_RE.finditer(row.body or "")}
    undeclared = sorted(placeholders - row.variable_names())
    if undeclared:
        raise ValueError(f"正文占位符未声明变量: {'、'.join(undeclared)}")
    row.publish()
    return ok({"id": row.id, "status": row.status, "version": row.version})


@endpoint()
def template_disable(request, pk):
    """停用模板（已发布的模板不再出现在起草入口，历史合同不受影响）。"""
    row = _template(request.user, pk, write=True)
    if row.status == "disabled":
        raise ValueError("模板已停用")
    row.status = "disabled"
    row.touch()
    row.save(update_fields=["status", "updated_at"])
    return ok({"id": row.id, "status": row.status})


@endpoint()
def template_clone(request, pk):
    """克隆模板（连同条款一起复制，编码自动加后缀，副本从草稿开始）。"""
    source = _template(request.user, pk)
    base_code = opt_str(request, "code", f"{source.code}-copy", max_len=60).strip()
    code, index = base_code, 1
    while ContractTemplate.objects.filter(owner=request.user, code=code).exists():
        index += 1
        code = f"{base_code}-{index}"[:60]
    with transaction.atomic():
        copy = ContractTemplate.objects.create(
            owner=request.user,
            code=code,
            name=opt_str(request, "name", f"{source.name}（副本）", max_len=200),
            template_type=source.template_type,
            scene=source.scene,
            body=source.body,
            variables=source.variables or [],
            version="v1.0",
            status="draft",
            remark=f"克隆自模板 #{source.id}",
        )
        for clause in source.clauses.all().order_by("order", "id"):
            Clause.objects.create(
                owner=request.user,
                template=copy,
                library=clause.library,
                title=clause.title,
                body=clause.body,
                order=clause.order,
                optional=clause.optional,
                alt_group=clause.alt_group,
                risk_level=clause.risk_level,
                variables=clause.variables or [],
                note=clause.note,
            )
    return ok({"id": copy.id, "code": copy.code,
               "clauses": copy.clauses.count(), "source_id": source.id})


@endpoint()
def template_render(request, pk):
    """渲染预览：传 variables 取值，返回正文与未解析占位符（白名单 + 缺失报错）。"""
    row = _template(request.user, pk)
    values = p(request, "variables") or p(request, "values") or {}
    if not isinstance(values, dict):
        raise ValueError("variables 必须是对象")
    strict = opt_bool(request, "strict", True)
    result = services.render_template(row, values, strict=strict)
    return ok(result)


@endpoint(("GET",))
def template_clauses(request, pk):
    """模板条款列表（按排序返回，含风险等级）。"""
    row = _template(request.user, pk)
    items = [clause_dict(item) for item in row.clauses.all().order_by("order", "id")]
    return ok({"items": items, "count": len(items)})


@endpoint()
def clause_add(request, pk):
    """新增模板条款（可引用条款库；顺序缺省追加到末尾）。"""
    row = _template(request.user, pk, write=True)
    library_id = opt_num(request, "library_id", None, integer=True, minimum=1)
    library = None
    if library_id:
        library = ClauseLibrary.objects.filter(pk=int(library_id)).first()
        if library is None:
            raise ValueError("来源条款不存在")
    order = opt_num(request, "order", None, integer=True, minimum=0)
    if order is None:
        order = (row.clauses.order_by("-order").values_list("order", flat=True).first()
                 or 0) + 1
    risk_level = opt_str(request, "risk_level",
                         library.risk_level if library else "low")
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"风险等级不支持: {risk_level}")
    title = opt_str(request, "title", library.title if library else "")
    if not title.strip():
        raise ValueError("缺少必填参数: title")
    clause = Clause.objects.create(
        owner=request.user,
        template=row,
        library=library,
        title=title[:200],
        body=opt_str(request, "body", library.body if library else "", max_len=0),
        order=int(order),
        optional=opt_bool(request, "optional", False),
        alt_group=opt_str(request, "alt_group", max_len=40),
        risk_level=risk_level,
        variables=[],
        note=opt_str(request, "note", max_len=0),
    )
    if library:
        library.mark_used()
    return ok(clause_dict(clause))


@endpoint()
def clause_from_library(request, pk):
    """把条款库条目实例化到模板（保持库条目不被改写，只复制正文）。"""
    row = _template(request.user, pk, write=True)
    library_id = int(req_num(request, "library_id", None, integer=True, minimum=1))
    library = ClauseLibrary.objects.filter(pk=library_id).first()
    if library is None:
        raise ValueError("条款库条目不存在")
    if library.status != "active":
        raise ValueError("该条款已停用，不能引用")
    order = (row.clauses.order_by("-order").values_list("order", flat=True).first()
             or 0) + 1
    clause = Clause.objects.create(
        owner=request.user,
        template=row,
        library=library,
        title=library.title,
        body=library.body,
        order=order,
        risk_level=library.risk_level,
        variables=[],
        note=f"引用条款库 #{library.id}（{library.category}）",
    )
    library.mark_used()
    return ok(clause_dict(clause))


@endpoint()
def clause_update(request, pk):
    """更新模板条款（排序、可选、替代组、正文均可改）。"""
    clause = Clause.objects.select_related("template").filter(pk=pk).first()
    if clause is None:
        raise ValueError("条款不存在")
    if not can_write(request.user, clause):
        raise ValueError("无权修改该条款")
    if has(request, "title"):
        clause.title = req_str(request, "title", max_len=200)
    if has(request, "body"):
        clause.body = opt_str(request, "body", max_len=0)
    if has(request, "order"):
        clause.order = int(req_num(request, "order", clause.order, minimum=0,
                                   maximum=100000, integer=True))
    if has(request, "optional"):
        clause.optional = opt_bool(request, "optional", clause.optional)
    if has(request, "alt_group"):
        clause.alt_group = opt_str(request, "alt_group", max_len=40)
    if has(request, "risk_level"):
        level = opt_str(request, "risk_level", clause.risk_level)
        if level not in RISK_LEVELS:
            raise ValueError(f"风险等级不支持: {level}")
        clause.risk_level = level
    if has(request, "note"):
        clause.note = opt_str(request, "note", max_len=0)
    clause.touch()
    clause.save()
    return ok(clause_dict(clause))


@endpoint()
def clause_delete(request, pk):
    """删除模板条款（仅模板 owner 可删）。"""
    clause = Clause.objects.select_related("template").filter(pk=pk).first()
    if clause is None:
        raise ValueError("条款不存在")
    if not can_write(request.user, clause):
        raise ValueError("无权删除该条款")
    clause_id = clause.id
    clause.delete()
    return ok({"deleted": True, "id": clause_id})


@endpoint()
def clause_reorder(request, pk):
    """批量调整条款顺序（传完整 id 顺序，缺省的条款保持原有相对次序）。"""
    row = _template(request.user, pk, write=True)
    ids = req_list_arg(request, "ids")
    if not ids:
        raise ValueError("缺少必填参数: ids")
    existing = {item.id: item for item in row.clauses.all()}
    order = 0
    with transaction.atomic():
        for raw in ids:
            try:
                clause_id = int(raw)
            except (TypeError, ValueError):
                raise ValueError("ids 必须是整数数组")
            clause = existing.pop(clause_id, None)
            if clause is None:
                raise ValueError(f"条款 #{clause_id} 不属于该模板")
            order += 1
            clause.order = order
            clause.touch()
            clause.save(update_fields=["order", "updated_at"])
        for clause in existing.values():
            order += 1
            clause.order = order
            clause.touch()
            clause.save(update_fields=["order", "updated_at"])
    return ok({"template_id": row.id, "count": order})


# ---------------------------------------------------------------------------
# 条款库
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def library_list(request):
    """条款库检索（支持 q / category / risk_level / jurisdiction）。"""
    qs = scope_queryset(ClauseLibrary.objects.all(), request.user)
    rows, total, page, size = list_queryset(
        request, qs, ("title", "body", "category", "tags"),
        status_field="status",
        extra_filters={
            "category": ("category", str),
            "risk_level": ("risk_level", str),
            "jurisdiction": ("jurisdiction", str),
        },
    )
    return ok(page_payload([library_clause_dict(row) for row in rows],
                           total, page, size))


@endpoint()
def library_create(request):
    """新增条款库条目（分类/等级/法域校验，标签去重）。"""
    risk_level = opt_str(request, "risk_level", "low")
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"风险等级不支持: {risk_level}")
    tags = req_list_arg(request, "tags", [], max_items=30)
    cleaned = []
    for item in tags:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text[:30])
    row = ClauseLibrary.objects.create(
        owner=request.user,
        category=opt_str(request, "category", "通用", max_len=40) or "通用",
        title=req_str(request, "title", max_len=200),
        body=opt_str(request, "body", max_len=0),
        risk_level=risk_level,
        jurisdiction=opt_str(request, "jurisdiction", "CN", max_len=40),
        tags=cleaned,
        status="active",
        remark=opt_str(request, "remark", max_len=0),
    )
    return ok(library_clause_dict(row))


@endpoint()
def library_update(request, pk):
    """更新条款库条目（只改传入字段）。"""
    row = ClauseLibrary.objects.filter(pk=pk).first()
    if row is None:
        raise ValueError("条款不存在")
    if not can_write(request.user, row):
        raise ValueError("无权修改该条款")
    if has(request, "category"):
        row.category = (opt_str(request, "category", row.category, max_len=40)
                        or "通用")
    if has(request, "title"):
        row.title = req_str(request, "title", max_len=200)
    if has(request, "body"):
        row.body = opt_str(request, "body", max_len=0)
    if has(request, "risk_level"):
        level = opt_str(request, "risk_level", row.risk_level)
        if level not in RISK_LEVELS:
            raise ValueError(f"风险等级不支持: {level}")
        row.risk_level = level
    if has(request, "jurisdiction"):
        row.jurisdiction = opt_str(request, "jurisdiction", row.jurisdiction,
                                   max_len=40)
    if has(request, "tags"):
        row.tags = [str(item).strip()[:30] for item in req_list_arg(request, "tags")
                    if str(item).strip()]
    if has(request, "status"):
        status = opt_str(request, "status", row.status)
        if status not in ("active", "disabled"):
            raise ValueError("条款状态仅支持 active / disabled")
        row.status = status
    if has(request, "remark"):
        row.remark = opt_str(request, "remark", max_len=0)
    row.touch()
    row.save()
    return ok(library_clause_dict(row))


@endpoint()
def library_delete(request, pk):
    """停用条款库条目（不物理删除：历史模板条款仍指向它做溯源）。"""
    row = ClauseLibrary.objects.filter(pk=pk).first()
    if row is None:
        raise ValueError("条款不存在")
    if not can_write(request.user, row):
        raise ValueError("无权删除该条款")
    row.status = "disabled"
    row.touch()
    row.save(update_fields=["status", "updated_at"])
    return ok({"id": row.id, "status": row.status,
               "referenced": row.clause_instances.count()})


@endpoint(("GET",))
def library_stats(request):
    """条款库统计：按分类 / 风险等级 / 法域聚合，附带最常用条款。"""
    qs = scope_queryset(ClauseLibrary.objects.all(), request.user)
    by_category = {row["category"]: row["count"] for row in
                   qs.values("category").annotate(count=Count("id")).order_by()}
    by_risk = {row["risk_level"]: row["count"] for row in
               qs.values("risk_level").annotate(count=Count("id")).order_by()}
    by_jurisdiction = {row["jurisdiction"]: row["count"] for row in
                       qs.values("jurisdiction").annotate(count=Count("id")).order_by()}
    top = list(qs.order_by("-usage_count", "title")[:10])
    return ok({
        "total": qs.count(),
        "active": qs.filter(status="active").count(),
        "by_category": by_category,
        "by_risk_level": by_risk,
        "by_jurisdiction": by_jurisdiction,
        "top_used": [{"id": row.id, "title": row.title,
                      "usage_count": row.usage_count} for row in top],
    })


@endpoint(("GET",))
def template_stats(request):
    """模板统计：状态分布与合同引用量 TOP（评估模板是否真的在用）。"""
    qs = _visible_templates(request.user)
    by_status = {row["status"]: row["count"] for row in
                 qs.values("status").annotate(count=Count("id")).order_by()}
    usage = []
    for row in qs.order_by("id")[:200]:
        usage.append({"id": row.id, "code": row.code, "name": row.name,
                      "status": row.status,
                      "contracts": Contract.objects.filter(template=row).count(),
                      "clauses": row.clauses.count()})
    usage.sort(key=lambda item: (-item["contracts"], item["code"]))
    return ok({"total": qs.count(), "by_status": by_status,
               "usage": usage[:20], "generated_at": iso(timezone.now())})


# ---------------------------------------------------------------------------
# 条款推荐
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def library_suggest(request):
    """条款推荐：按关键字/风险等级/合同类型给条款库打分排序，返回推荐理由。"""
    qs = (scope_queryset(ClauseLibrary.objects.all(), request.user)
          .filter(status="active"))
    keyword = opt_str(request, "q", "", max_len=60)
    risk_level = opt_str(request, "risk_level", "")
    if risk_level and risk_level not in RISK_LEVELS:
        raise ValueError(f"风险等级不支持: {risk_level}")
    limit = int(opt_num(request, "limit", 20, minimum=1, maximum=50,
                        integer=True))
    rows = list(qs[:500])
    items = services.suggest_clauses(rows, keyword,
                                     risk_level,
                                     opt_str(request, "contract_type", ""),
                                     limit)
    return ok(page_payload(items, len(items), 1, limit, q=keyword,
                           risk_level=risk_level))
