# -*- coding: utf-8 -*-
"""knowledgegraph · 实体与别名接口：实体 11 + 别名 5 = 16。

实体生命周期：
- 新建时做「同本体 + 同类型 + 同规范名」的重复拦截，避免手工录入把
  同一实体录成两条；批量导入对重复行跳过而不是报错（导入是幂等诉求）；
- 归档是软删除（status=archived），已合并实体不再允许编辑；
- 合并 / 拆分是结构性写操作，全部在服务层事务内完成并留审计。
"""
from django.db import transaction
from django.db.models import Q

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_bool, opt_str, p, req_num, req_str
from knowledgegraph import services
from knowledgegraph.common import (alias_dict, bool_arg, clamp, entity_dict,
                                   entity_for_write, entity_type_dict,
                                   float_arg, ids_arg, int_arg, json_arg,
                                   list_queryset, ontology_for_write,
                                   page_args, page_payload, read_obj,
                                   record_audit, slice_page, tag_dict,
                                   write_obj)
from knowledgegraph.models import (Entity, EntityAlias, EntityTag, EntityType,
                                   Ontology, Relation, Source)


def _entity_queryset(user):
    """实体读取范围 + 预取类型与本体（列表 / 详情共用，避免 N+1）。"""
    return scope_queryset(
        Entity.objects.select_related("entity_type", "ontology", "source"),
        user,
    )


def _resolve_ontology_and_type(ontology_id, type_id, user, type_code=""):
    """解析本体与实体类型，并校验「类型属于本体且已启用」。"""
    ontology = ontology_for_write(ontology_id, user)
    if ontology.status == "archived":
        raise ValueError("本体已归档，不能新增实体")
    if type_id:
        etype = EntityType.objects.filter(pk=int(type_id)).first()
    elif type_code:
        etype = EntityType.objects.filter(ontology=ontology, code=type_code).first()
    else:
        raise ValueError("必须指定实体类型")
    if etype is None:
        raise ValueError("实体类型不存在")
    if etype.ontology_id != ontology.id:
        raise ValueError("实体类型不属于该本体")
    if not etype.enabled:
        raise ValueError("实体类型已停用")
    return ontology, etype


def _duplicate_entity(ontology, etype, canonical_name, exclude_pk=None):
    """同本体 + 同类型 + 同规范名的生效实体视为重复。"""
    qs = Entity.objects.filter(ontology=ontology, entity_type=etype,
                               canonical_name=canonical_name, status="active")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


@endpoint()
def entity_create(request):
    """创建实体（同本体同类型同规范名拦截重复）。"""
    ontology_id = req_num(request, "ontology_id")
    type_id = int_arg(request, "entity_type_id")
    type_code = opt_str(request, "entity_type_code", "").strip()
    ontology, etype = _resolve_ontology_and_type(
        ontology_id, type_id, request.user, type_code)
    name = req_str(request, "name", max_len=200).strip()
    if not name:
        raise ValueError("实体名称不能为空")
    canonical = opt_str(request, "canonical_name", "").strip()
    canonical = (canonical or services.normalize_name(name) or name)[:200]
    duplicate = _duplicate_entity(ontology, etype, canonical)
    if duplicate:
        raise ValueError(f"实体已存在：{duplicate.name}（如确认重复请走合并流程）")
    source = None
    source_id = int_arg(request, "source_id")
    if source_id:
        source = scope_queryset(Source.objects.all(), request.user).filter(
            pk=source_id).first()
        if source is None:
            raise ValueError("来源不存在或无权访问")
    entity = Entity.objects.create(
        owner=request.user,
        ontology=ontology,
        entity_type=etype,
        name=name[:200],
        canonical_name=canonical,
        description=opt_str(request, "description")[:4000],
        attrs=json_arg(request, "attrs", {}),
        source=source,
        confidence=clamp(req_num(request, "confidence", 0.8, minimum=0,
                                  maximum=1), 0.8),
        status="active",
        created_by=request.user,
    )
    record_audit(request.user, "entity.create", ontology.id, "entity", entity.id,
                 f"创建实体 {entity.name}")
    return ok(entity_dict(entity))


@endpoint(("GET",))
def entity_list(request):
    """实体列表（支持关键字 / 状态 / 本体 / 类型 / 置信度下限）。"""
    qs = _entity_queryset(request.user).order_by("-updated_at")
    rows, total, page, size = list_queryset(
        request, qs, ["name", "canonical_name", "description"], "status",
        extra_filters={
            "ontology_id": ("ontology_id", int),
            "entity_type_id": ("entity_type_id", int),
            "min_confidence": ("confidence__gte", float),
        },
    )
    return ok(page_payload([entity_dict(e) for e in rows], total, page, size))


@endpoint(("GET",))
def entity_detail(request, pk):
    """实体详情：基础信息 + 出/入关系 + 别名 + 标签。"""
    entity = read_obj(Entity, pk, request.user, "实体")
    data = entity_dict(entity)
    out_relations = Relation.objects.filter(source_entity=entity, status="active"
                                            ).select_related("relation_type",
                                                             "target_entity")[:200]
    in_relations = Relation.objects.filter(target_entity=entity, status="active"
                                           ).select_related("relation_type",
                                                            "source_entity")[:200]
    data["out_relations"] = [
        {**{k: getattr(r, k) for k in ("id", "weight", "confidence", "attrs",
                                       "created_at")},
         "relation_type": r.relation_type.name,
         "relation_type_code": r.relation_type.code,
         "direction": "out",
         "other_entity_id": r.target_entity_id,
         "other_entity_name": r.target_entity.name}
        for r in out_relations
    ]
    data["in_relations"] = [
        {**{k: getattr(r, k) for k in ("id", "weight", "confidence", "attrs",
                                       "created_at")},
         "relation_type": r.relation_type.name,
         "relation_type_code": r.relation_type.code,
         "direction": "in",
         "other_entity_id": r.source_entity_id,
         "other_entity_name": r.source_entity.name}
        for r in in_relations
    ]
    data["aliases"] = [alias_dict(a) for a in entity.aliases.all()[:100]]
    data["tags"] = [tag_dict(t) for t in entity.tags.all()[:100]]
    data["relation_count"] = len(data["out_relations"]) + len(data["in_relations"])
    data["ontology_name"] = entity.ontology.name
    return ok(data)


@endpoint()
def entity_update(request, pk):
    """更新实体（名称变化时同步规范名；已合并 / 归档实体不可编辑）。"""
    entity = entity_for_write(pk, request.user)
    if entity.status != "active":
        raise ValueError("只有生效状态的实体可以编辑")
    if p(request, "entity_type_id") is not None:
        type_id = int_arg(request, "entity_type_id")
        etype = EntityType.objects.filter(pk=type_id).first()
        if etype is None:
            raise ValueError("实体类型不存在")
        if etype.ontology_id != entity.ontology_id:
            raise ValueError("实体类型不属于该本体")
        if not etype.enabled:
            raise ValueError("实体类型已停用")
        entity.entity_type = etype
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("实体名称不能为空")
        entity.name = name[:200]
        if p(request, "canonical_name") in (None, ""):
            entity.canonical_name = (services.normalize_name(name) or name)[:200]
    if p(request, "canonical_name") is not None:
        canonical = opt_str(request, "canonical_name").strip()
        if canonical:
            entity.canonical_name = canonical[:200]
    if p(request, "description") is not None:
        entity.description = opt_str(request, "description")[:4000]
    if p(request, "attrs") is not None:
        entity.attrs = json_arg(request, "attrs", {})
    if p(request, "confidence") is not None:
        entity.confidence = clamp(req_num(request, "confidence", minimum=0,
                                          maximum=1), entity.confidence)
    if p(request, "source_id") is not None:
        source_id = int_arg(request, "source_id")
        if source_id:
            source = scope_queryset(Source.objects.all(), request.user).filter(
                pk=source_id).first()
            if source is None:
                raise ValueError("来源不存在或无权访问")
            entity.source = source
        else:
            entity.source = None
    duplicate = _duplicate_entity(entity.ontology, entity.entity_type,
                                  entity.canonical_name, exclude_pk=entity.pk)
    if duplicate:
        raise ValueError(f"同类型下已存在规范名相同的实体：{duplicate.name}")
    entity.save()
    record_audit(request.user, "entity.update", entity.ontology_id, "entity",
                 entity.id, f"更新实体 {entity.name}")
    return ok(entity_dict(entity))


def _archive_entity(entity):
    """归档核心逻辑：删除与归档共用，避免重复包裹 DRF 视图。"""
    if entity.status == "archived":
        return {"id": entity.id, "status": entity.status, "already": True}
    entity.status = "archived"
    entity.save(update_fields=["status", "updated_at"])
    services.invalidate_path_cache(entity.ontology_id, [entity.id])
    record_audit(entity.owner, "entity.archive", entity.ontology_id, "entity",
                 entity.id, f"归档实体 {entity.name}")
    return {"id": entity.id, "status": entity.status}


@endpoint()
def entity_delete(request, pk):
    """删除实体（软删除：状态置为 archived，保留关系可追溯）。"""
    return ok(_archive_entity(entity_for_write(pk, request.user)))


@endpoint()
def entity_archive(request, pk):
    """归档实体（与删除同义，独立入口便于前端语义区分）。"""
    return ok(_archive_entity(entity_for_write(pk, request.user)))


@endpoint()
def entity_bulk_import(request):
    """批量导入实体（重复跳过，逐行返回错误；单事务保证部分失败不落库）。"""
    ontology_id = req_num(request, "ontology_id")
    ontology = ontology_for_write(ontology_id, request.user)
    if ontology.status == "archived":
        raise ValueError("本体已归档，不能导入实体")
    rows = p(request, "rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows 必须是非空数组")
    if len(rows) > 500:
        raise ValueError("单次最多导入 500 行")
    type_map = {t.code: t for t in EntityType.objects.filter(ontology=ontology)}
    type_id_map = {t.id: t for t in type_map.values()}
    created = 0
    skipped = 0
    errors = []
    created_ids = []
    with transaction.atomic():
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append({"row": index, "error": "行必须是对象"})
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                errors.append({"row": index, "error": "缺少 name"})
                continue
            etype = None
            if row.get("entity_type_id") not in (None, ""):
                try:
                    etype = type_id_map.get(int(row["entity_type_id"]))
                except (TypeError, ValueError):
                    etype = None
            elif row.get("entity_type_code"):
                etype = type_map.get(str(row["entity_type_code"]))
            elif row.get("entity_type"):
                etype = type_map.get(str(row["entity_type"]))
            if etype is None:
                errors.append({"row": index, "error": "实体类型不存在或未提供"})
                continue
            canonical = str(row.get("canonical_name") or "").strip()
            canonical = (canonical or services.normalize_name(name) or name)[:200]
            if _duplicate_entity(ontology, etype, canonical):
                skipped += 1
                continue
            attrs = row.get("attrs") if isinstance(row.get("attrs"), dict) else {}
            entity = Entity.objects.create(
                owner=request.user, ontology=ontology, entity_type=etype,
                name=name[:200], canonical_name=canonical,
                description=str(row.get("description") or "")[:4000],
                attrs=attrs,
                confidence=clamp(row.get("confidence", 0.8), 0.8),
                status="active", created_by=request.user,
            )
            created += 1
            created_ids.append(entity.id)
    record_audit(request.user, "entity.bulk_import", ontology.id, "entity", None,
                 f"批量导入 {created} 个实体",
                 {"created": created, "skipped": skipped, "errors": len(errors)})
    return ok({"created": created, "skipped": skipped, "errors": errors[:100],
               "error_count": len(errors), "entity_ids": created_ids[:500]})


@endpoint()
def entity_merge(request):
    """合并实体（事务内迁移关系 / 别名 / 标签，自动去重自环与重复边）。"""
    source_id = req_num(request, "source_id")
    target_id = req_num(request, "target_id")
    source = entity_for_write(source_id, request.user)
    target = entity_for_write(target_id, request.user)
    reason = opt_str(request, "reason", "")[:2000]
    result = services.merge_entities(source, target, request.user, reason=reason)
    return ok(result)


@endpoint()
def entity_split(request, pk):
    """拆分实体：把选中的关系 / 别名迁入新实体。"""
    entity = entity_for_write(pk, request.user)
    name = req_str(request, "name", max_len=200).strip()
    relation_ids = ids_arg(request, "relation_ids")
    alias_ids = ids_arg(request, "alias_ids")
    etype = None
    type_id = int_arg(request, "entity_type_id")
    if type_id:
        etype = EntityType.objects.filter(pk=type_id).first()
        if etype is None:
            raise ValueError("实体类型不存在")
        if etype.ontology_id != entity.ontology_id:
            raise ValueError("实体类型不属于该本体")
    result = services.split_entity(
        entity, request.user, name, relation_ids=relation_ids,
        alias_ids=alias_ids, entity_type=etype,
        description=opt_str(request, "description", ""))
    return ok(result)


@endpoint(("GET",))
def entity_search(request):
    """实体加权搜索（名称 / 规范名 / 别名 / 描述 / 属性）。"""
    q = req_str(request, "q", max_len=200).strip()
    if not q:
        raise ValueError("搜索关键字不能为空")
    ontology_id = int_arg(request, "ontology_id")
    type_ids = ids_arg(request, "type_ids")
    limit = int_arg(request, "limit", 20, minimum=1, maximum=200)
    qs = _entity_queryset(request.user).filter(status="active")
    if ontology_id:
        qs = qs.filter(ontology_id=ontology_id)
    alias_entity_ids = EntityAlias.objects.filter(
        owner=request.user, alias__icontains=q).values_list("entity_id", flat=True)
    qs = qs.filter(
        Q(name__icontains=q) | Q(canonical_name__icontains=q)
        | Q(description__icontains=q) | Q(id__in=alias_entity_ids)
    )[:3000]
    entities = [services.entity_lite(e) for e in qs]
    alias_map = {}
    for alias in EntityAlias.objects.filter(
            entity_id__in=[e["id"] for e in entities])[:10000]:
        alias_map.setdefault(alias.entity_id, []).append(alias.alias)
    result = services.search_entities(
        entities, alias_map, q, limit=limit, type_ids=type_ids)
    record_audit(request.user, "entity.search", ontology_id, "entity", None,
                 f"搜索 {q}", {"result_count": result["count"]})
    return ok(result)


@endpoint(("GET",))
def entity_duplicates(request):
    """实体重复候选（名称规范化 + 编辑距离 + token Jaccard 的合并建议）。"""
    ontology_id = int_arg(request, "ontology_id")
    threshold = float_arg(request, "threshold", 0.82, minimum=0.5, maximum=1.0)
    limit = int_arg(request, "limit", 50, minimum=1, maximum=200)
    same_type_only = not bool_arg(request, "cross_type", False)
    qs = _entity_queryset(request.user).filter(status="active")
    if ontology_id:
        qs = qs.filter(ontology_id=ontology_id)
    entities = [services.entity_lite(e) for e in qs[:2001]]
    result = services.duplicate_suggestions(
        entities[:2000], threshold=threshold, same_type_only=same_type_only,
        limit=limit)
    return ok(result)


# ---------------------------------------------------------------------------
# 别名
# ---------------------------------------------------------------------------


@endpoint()
def alias_create(request):
    """新增实体别名（同一实体下别名唯一）。"""
    entity_id = req_num(request, "entity_id")
    entity = entity_for_write(entity_id, request.user)
    alias = req_str(request, "alias", max_len=200).strip()
    if not alias:
        raise ValueError("别名不能为空")
    if EntityAlias.objects.filter(entity=entity, alias=alias).exists():
        raise ValueError("该别名已存在")
    row = EntityAlias.objects.create(
        owner=request.user, entity=entity, alias=alias[:200],
        lang=opt_str(request, "lang", "zh")[:20] or "zh",
        source=opt_str(request, "source", "manual")[:40] or "manual",
        confidence=clamp(req_num(request, "confidence", 1.0, minimum=0,
                                  maximum=1), 1.0),
    )
    record_audit(request.user, "alias.create", entity.ontology_id, "entity",
                 entity.id, f"新增别名 {row.alias}")
    return ok(alias_dict(row))


@endpoint(("GET",))
def alias_list(request):
    """别名列表（支持实体 / 关键字）。"""
    qs = scope_queryset(EntityAlias.objects.all(), request.user).order_by("id")
    entity_id = int_arg(request, "entity_id")
    if entity_id:
        qs = qs.filter(entity_id=entity_id)
    rows, total, page, size = list_queryset(
        request, qs, ["alias"], status_field=None)
    return ok(page_payload([alias_dict(a) for a in rows], total, page, size))


@endpoint()
def alias_batch(request):
    """批量新增别名（支持字符串或对象数组，重复跳过）。"""
    entity_id = req_num(request, "entity_id")
    entity = entity_for_write(entity_id, request.user)
    raw = p(request, "aliases")
    if not isinstance(raw, list) or not raw:
        raise ValueError("aliases 必须是非空数组")
    if len(raw) > 200:
        raise ValueError("单次最多新增 200 个别名")
    existing = {a.alias.casefold() for a in EntityAlias.objects.filter(entity=entity)}
    created = 0
    skipped = 0
    items = []
    with transaction.atomic():
        for item in raw:
            if isinstance(item, dict):
                alias = str(item.get("alias") or item.get("name") or "").strip()
                lang = str(item.get("lang") or "zh")[:20]
                confidence = clamp(item.get("confidence", 1.0), 1.0)
            else:
                alias = str(item or "").strip()
                lang = "zh"
                confidence = 1.0
            if not alias:
                skipped += 1
                continue
            if alias.casefold() in existing:
                skipped += 1
                continue
            row = EntityAlias.objects.create(
                owner=request.user, entity=entity, alias=alias[:200],
                lang=lang, source="batch", confidence=confidence)
            existing.add(alias.casefold())
            created += 1
            items.append(alias_dict(row))
    record_audit(request.user, "alias.batch", entity.ontology_id, "entity",
                 entity.id, f"批量新增别名 {created} 个")
    return ok({"created": created, "skipped": skipped, "items": items})


@endpoint()
def alias_update(request, pk):
    """更新别名（别名文本重复会被拒绝）。"""
    row = write_obj(EntityAlias, pk, request.user, "别名")
    if p(request, "alias") is not None:
        alias = opt_str(request, "alias").strip()
        if not alias:
            raise ValueError("别名不能为空")
        conflict = EntityAlias.objects.filter(
            entity_id=row.entity_id, alias=alias).exclude(pk=row.pk).exists()
        if conflict:
            raise ValueError("该别名已存在")
        row.alias = alias[:200]
    if p(request, "lang") is not None:
        row.lang = opt_str(request, "lang", "zh")[:20] or "zh"
    if p(request, "confidence") is not None:
        row.confidence = clamp(req_num(request, "confidence", minimum=0,
                                       maximum=1), row.confidence)
    row.save()
    return ok(alias_dict(row))


@endpoint()
def alias_delete(request, pk):
    """删除别名。"""
    row = write_obj(EntityAlias, pk, request.user, "别名")
    row_id = row.id
    row.delete()
    return ok({"id": row_id, "deleted": True})


ENTITY_FAMILY_COUNT = 11 + 5
