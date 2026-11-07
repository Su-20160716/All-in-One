# -*- coding: utf-8 -*-
"""knowledgegraph · 关系接口：创建 / 列表 / 详情 / 更新 / 软删除 / 批量 = 6。

关系写入比实体严格一档：
- 两端实体必须属于同一本体且都是 active，且调用方对两端都有写权限
  （否则等于可以往别人的实体上挂边）；
- 关系类型若声明了源 / 目标类型，必须匹配，避免「人 位于 部门」这种
  语义上不成立的边污染图；
- 同类型同两端同方向的生效边唯一；无向关系类型的反向重复也会被判重；
- 删除是软删除，历史合并日志与快照对比都依赖这些行的存在。
"""
from django.db import transaction
from django.db.models import Q

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_str, p, req_num, req_str
from knowledgegraph import services
from knowledgegraph.common import (bool_arg, clamp, clamp_weight, float_arg,
                                   ids_arg, int_arg, json_arg, list_queryset,
                                   page_args, page_payload, read_obj,
                                   record_audit, relation_dict, write_obj)
from knowledgegraph.models import (Entity, Relation, RelationType)


def _relation_endpoints(source_id, target_id, user):
    """取两端实体并校验写权限 / 同本体 / 非自环。"""
    source_id, target_id = int(source_id), int(target_id)
    source = write_obj(Entity, source_id, user, "源实体")
    target = write_obj(Entity, target_id, user, "目标实体")
    if source.id == target.id:
        raise ValueError("关系的源实体与目标实体不能相同")
    if source.ontology_id != target.ontology_id:
        raise ValueError("关系两端必须属于同一本体")
    if source.status != "active" or target.status != "active":
        raise ValueError("关系两端必须都是生效实体")
    return source, target


def _relation_type(rtype_id, ontology_id, user, code=""):
    """取关系类型并校验本体归属与启用状态。"""
    if rtype_id:
        rtype = write_obj(RelationType, int(rtype_id), user, "关系类型")
    elif code:
        rtype = RelationType.objects.filter(ontology_id=ontology_id,
                                            code=code).first()
        if rtype is None:
            raise ValueError("关系类型不存在")
        if not getattr(rtype, "enabled", False):
            raise ValueError("关系类型已停用")
    else:
        raise ValueError("必须指定关系类型")
    if rtype.ontology_id != int(ontology_id):
        raise ValueError("关系类型不属于该本体")
    if not rtype.enabled:
        raise ValueError("关系类型已停用")
    return rtype


def _check_type_endpoints(rtype, source, target):
    """关系类型声明的端点约束：源 / 目标类型必须匹配。"""
    if rtype.source_type_id and rtype.source_type_id != source.entity_type_id:
        raise ValueError(f"源实体类型不符合关系类型约束（要求 {rtype.source_type.name}）")
    if rtype.target_type_id and rtype.target_type_id != target.entity_type_id:
        raise ValueError(f"目标实体类型不符合关系类型约束（要求 {rtype.target_type.name}）")


def _duplicate_relation(rtype, source, target, exclude_pk=None):
    """重复边判定：有向看同方向；无向额外看反方向。"""
    qs = Relation.objects.filter(relation_type=rtype, status="active")
    if rtype.directed:
        qs = qs.filter(source_entity=source, target_entity=target)
    else:
        qs = qs.filter(
            Q(source_entity=source, target_entity=target)
            | Q(source_entity=target, target_entity=source))
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


@endpoint()
def relation_create(request):
    """创建关系（校验端点类型、方向与重复边）。"""
    ontology_id = req_num(request, "ontology_id")
    rtype_id = int_arg(request, "relation_type_id")
    rtype = _relation_type(rtype_id, int(ontology_id), request.user,
                           opt_str(request, "relation_type_code", "").strip())
    source, target = _relation_endpoints(req_num(request, "source_entity_id"),
                                         req_num(request, "target_entity_id"),
                                         request.user)
    _check_type_endpoints(rtype, source, target)
    if _duplicate_relation(rtype, source, target):
        raise ValueError("相同关系已存在")
    relation = Relation.objects.create(
        owner=request.user, ontology_id=rtype.ontology_id, relation_type=rtype,
        source_entity=source, target_entity=target,
        attrs=json_arg(request, "attrs", {}),
        weight=clamp_weight(req_num(request, "weight", rtype.weight,
                                   minimum=0.01, maximum=100), rtype.weight),
        confidence=clamp(req_num(request, "confidence", 0.8, minimum=0,
                                  maximum=1), 0.8),
        source=opt_str(request, "source", "manual")[:40] or "manual",
        status="active",
    )
    services.invalidate_path_cache(relation.ontology_id,
                                   [source.id, target.id])
    record_audit(request.user, "relation.create", relation.ontology_id,
                 "relation", relation.id,
                 f"创建关系 {source.name} -{rtype.name}-> {target.name}")
    return ok(relation_dict(relation))


@endpoint(("GET",))
def relation_list(request):
    """关系列表（支持本体 / 类型 / 实体 / 状态 / 权重与置信度下限）。"""
    qs = scope_queryset(Relation.objects.all(), request.user).order_by("-created_at")
    entity_id = int_arg(request, "entity_id")
    if entity_id:
        qs = qs.filter(Q(source_entity_id=entity_id) | Q(target_entity_id=entity_id))
    relation_type_id = int_arg(request, "relation_type_id")
    rows, total, page, size = list_queryset(
        request, qs, [], "status",
        extra_filters={
            "ontology_id": ("ontology_id", int),
            "relation_type_id": ("relation_type_id", int),
            "min_weight": ("weight__gte", float),
            "min_confidence": ("confidence__gte", float),
        },
    )
    return ok(page_payload([relation_dict(r) for r in rows], total, page, size,
                           relation_type_id=relation_type_id))


@endpoint()
def relation_batch(request):
    """批量创建关系（重复跳过，单事务；最多 1000 条）。"""
    ontology_id = int(req_num(request, "ontology_id"))
    rows = p(request, "rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows 必须是非空数组")
    if len(rows) > 1000:
        raise ValueError("单次最多创建 1000 条关系")
    created = 0
    skipped = 0
    errors = []
    created_ids = []
    with transaction.atomic():
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append({"row": index, "error": "行必须是对象"})
                continue
            try:
                rtype = _relation_type(
                    int(row.get("relation_type_id") or 0) or None, ontology_id,
                    request.user, str(row.get("relation_type_code") or ""))
                source, target = _relation_endpoints(
                    row.get("source_entity_id"), row.get("target_entity_id"),
                    request.user)
                _check_type_endpoints(rtype, source, target)
                if _duplicate_relation(rtype, source, target):
                    skipped += 1
                    continue
                relation = Relation.objects.create(
                    owner=request.user, ontology_id=rtype.ontology_id,
                    relation_type=rtype, source_entity=source,
                    target_entity=target,
                    attrs=row.get("attrs") if isinstance(row.get("attrs"), dict) else {},
                    weight=clamp_weight(row.get("weight", rtype.weight), rtype.weight),
                    confidence=clamp(row.get("confidence", 0.8), 0.8),
                    source=str(row.get("source") or "batch")[:40],
                    status="active",
                )
                created += 1
                created_ids.append(relation.id)
            except ValueError as exc:
                errors.append({"row": index, "error": str(exc)})
    services.invalidate_path_cache(ontology_id)
    record_audit(request.user, "relation.batch", ontology_id, "relation", None,
                 f"批量创建关系 {created} 条",
                 {"created": created, "skipped": skipped, "errors": len(errors)})
    return ok({"created": created, "skipped": skipped, "errors": errors[:100],
               "error_count": len(errors), "relation_ids": created_ids[:1000]})


@endpoint(("GET",))
def relation_detail(request, pk):
    """关系详情。"""
    relation = read_obj(Relation, pk, request.user, "关系")
    data = relation_dict(relation)
    data["relation_type"] = relation.relation_type.name
    data["source_entity_name"] = relation.source_entity.name
    data["target_entity_name"] = relation.target_entity.name
    return ok(data)


@endpoint()
def relation_update(request, pk):
    """更新关系（属性 / 权重 / 置信度 / 类型；端点变更同样做全量校验）。"""
    relation = write_obj(Relation, pk, request.user, "关系")
    if relation.status != "active":
        raise ValueError("已删除的关系不能修改")
    source = relation.source_entity
    target = relation.target_entity
    if p(request, "source_entity_id") is not None or \
            p(request, "target_entity_id") is not None:
        source, target = _relation_endpoints(
            int_arg(request, "source_entity_id", source.id),
            int_arg(request, "target_entity_id", target.id),
            request.user)
    rtype = relation.relation_type
    if p(request, "relation_type_id") not in (None, ""):
        rtype = _relation_type(int_arg(request, "relation_type_id"),
                               relation.ontology_id, request.user)
    _check_type_endpoints(rtype, source, target)
    if _duplicate_relation(rtype, source, target, exclude_pk=relation.pk):
        raise ValueError("相同关系已存在")
    relation.relation_type = rtype
    relation.source_entity = source
    relation.target_entity = target
    if p(request, "attrs") is not None:
        relation.attrs = json_arg(request, "attrs", {})
    if p(request, "weight") is not None:
        relation.weight = clamp_weight(req_num(request, "weight", minimum=0.01,
                                             maximum=100), relation.weight)
    if p(request, "confidence") is not None:
        relation.confidence = clamp(req_num(request, "confidence", minimum=0,
                                            maximum=1), relation.confidence)
    if p(request, "source") is not None:
        relation.source = opt_str(request, "source", "manual")[:40] or "manual"
    relation.save()
    services.invalidate_path_cache(relation.ontology_id,
                                   [relation.source_entity_id,
                                    relation.target_entity_id])
    record_audit(request.user, "relation.update", relation.ontology_id,
                 "relation", relation.id, "更新关系")
    return ok(relation_dict(relation))


@endpoint()
def relation_delete(request, pk):
    """软删除关系（保留行以便合并日志与快照对账）。"""
    relation = write_obj(Relation, pk, request.user, "关系")
    if relation.status == "deleted":
        return ok({"id": relation.id, "status": relation.status,
                   "already": True})
    relation.status = "deleted"
    relation.save(update_fields=["status", "updated_at"])
    services.invalidate_path_cache(relation.ontology_id,
                                   [relation.source_entity_id,
                                    relation.target_entity_id])
    record_audit(request.user, "relation.delete", relation.ontology_id,
                 "relation", relation.id, "删除关系")
    return ok({"id": relation.id, "status": relation.status})


RELATION_FAMILY_COUNT = 6
