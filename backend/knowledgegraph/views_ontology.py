# -*- coding: utf-8 -*-
"""knowledgegraph · 本体与类型接口：本体 8 + 实体类型 5 + 关系类型 5 + 审计 1 = 19。

状态机：
- 本体 draft → published → archived；归档后只读，发布时自动递增版本并留痕；
- 类型没有状态机，用 enabled 控制「是否允许新建实体 / 关系」；
- 删除本体是级联操作，本体下还有实体时必须显式 force=true 才允许，
  避免一次误点把几个月积累的图谱清空。
"""
import re

from django.db import transaction
from django.db.models import Count, Q

from devtools.common import endpoint, ok, opt_bool, opt_str, p, req_num, req_str
from knowledgegraph.common import (choice_arg, entity_type_dict, int_arg,
                                   json_arg, list_queryset, ontology_dict,
                                   ontology_for_write, ontology_version_dict,
                                   page_args, page_payload, read_obj,
                                   record_audit, relation_type_dict,
                                   slice_page, slugify_code, write_obj)
from knowledgegraph.models import (ENTITY_STATUS_LABELS, Entity, EntityType,
                                   GraphAudit, Ontology, OntologyVersion,
                                   Relation, RelationType)


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------


def _unique_namespace(user, base, exclude_pk=None):
    """生成用户范围内唯一的命名空间：显式冲突时自动追加序号。

    不直接报错是因为前端「新建本体」默认命名空间常常留空，
    自动派生后撞名属于正常操作，不应该让用户手动改一个内部标识。
    """
    base = slugify_code(base, "kg")
    candidate = base
    index = 2
    while True:
        qs = Ontology.objects.filter(owner=user, namespace=candidate)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        candidate = f"{base}-{index}"
        index += 1


def _next_version(version):
    """版本号递增：v1 → v2；非标准写法（如 2024.1）统一转 v2。"""
    match = re.fullmatch(r"v(\d+)", str(version or "").strip())
    if match:
        return f"v{int(match.group(1)) + 1}"
    return "v2"


def _ontology_stats(ontology):
    """本体规模统计（发布留痕与详情共用）。"""
    entities = Entity.objects.filter(ontology=ontology)
    return {
        "entity_count": entities.filter(status="active").count(),
        "archived_entities": entities.filter(status="archived").count(),
        "merged_entities": entities.filter(status="merged").count(),
        "relation_count": Relation.objects.filter(ontology=ontology,
                                                  status="active").count(),
        "entity_type_count": EntityType.objects.filter(ontology=ontology).count(),
        "relation_type_count": RelationType.objects.filter(ontology=ontology).count(),
    }


@endpoint()
def ontology_create(request):
    """创建本体（命名空间在本人范围内自动去重）。"""
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("本体名称不能为空")
    namespace = opt_str(request, "namespace", "").strip()
    if namespace:
        exists = Ontology.objects.filter(owner=request.user,
                                         namespace=namespace).exists()
        if exists:
            raise ValueError("命名空间已存在，请换一个")
        final_namespace = namespace
    else:
        final_namespace = _unique_namespace(request.user, name)
    ontology = Ontology.objects.create(
        owner=request.user,
        name=name[:120],
        namespace=final_namespace[:80],
        description=opt_str(request, "description")[:2000],
        version=opt_str(request, "version", "v1")[:20] or "v1",
        status="draft",
    )
    record_audit(request.user, "ontology.create", ontology.id, "ontology",
                 ontology.id, f"创建本体 {ontology.name}")
    return ok(ontology_dict(ontology))


@endpoint(("GET",))
def ontology_list(request):
    """本体列表（数据范围内，支持关键字 / 状态，附实体与关系计数）。"""
    qs = scope_ontologies(request.user)
    qs = qs.annotate(
        entity_count=Count("entities", filter=Q(entities__status="active"),
                           distinct=True),
        relation_count=Count("relations", filter=Q(relations__status="active"),
                             distinct=True),
    ).order_by("-updated_at")
    rows, total, page, size = list_queryset(
        request, qs, ["name", "namespace", "description"], "status")
    return ok(page_payload([ontology_dict(o, with_counts=True) for o in rows],
                           total, page, size))


def scope_ontologies(user):
    """本体读取范围：统一走 scope_queryset，避免在列表里另写一套过滤。"""
    from core.scoping import scope_queryset

    return scope_queryset(Ontology.objects.all(), user)


@endpoint(("GET",))
def ontology_detail(request, pk):
    """本体详情：规模统计 + 类型清单 + 最近版本。"""
    ontology = read_obj(Ontology, pk, request.user, "本体")
    data = ontology_dict(ontology, with_counts=True)
    stats = _ontology_stats(ontology)
    data.update(stats)
    data["entity_type_count"] = stats["entity_type_count"]
    data["relation_type_count"] = stats["relation_type_count"]
    data["entity_types"] = [entity_type_dict(t) for t in
                            EntityType.objects.filter(ontology=ontology)[:50]]
    data["relation_types"] = [relation_type_dict(t) for t in
                              RelationType.objects.filter(ontology=ontology)[:50]]
    data["versions"] = [ontology_version_dict(v) for v in
                        ontology.versions.all()[:10]]
    return ok(data)


@endpoint()
def ontology_update(request, pk):
    """更新本体基本信息（归档本体只读）。"""
    ontology = ontology_for_write(int(pk), request.user)
    if ontology.status == "archived":
        raise ValueError("本体已归档，不能继续修改")
    name = opt_str(request, "name", "").strip()
    if name:
        ontology.name = name[:120]
    if p(request, "description") is not None:
        ontology.description = opt_str(request, "description")[:2000]
    if p(request, "namespace") is not None:
        namespace = opt_str(request, "namespace").strip()
        if not namespace:
            raise ValueError("命名空间不能为空")
        conflict = Ontology.objects.filter(
            owner=request.user, namespace=namespace).exclude(pk=ontology.pk).exists()
        if conflict:
            raise ValueError("命名空间已存在，请换一个")
        ontology.namespace = namespace[:80]
    if p(request, "version") is not None:
        version = opt_str(request, "version").strip()
        if not version:
            raise ValueError("版本号不能为空")
        ontology.version = version[:20]
    ontology.save()
    record_audit(request.user, "ontology.update", ontology.id, "ontology",
                 ontology.id, f"更新本体 {ontology.name}")
    return ok(ontology_dict(ontology))


@endpoint()
def ontology_delete(request, pk):
    """删除本体（级联；本体下仍有实体时必须 force=true）。"""
    ontology = ontology_for_write(int(pk), request.user)
    entity_count = Entity.objects.filter(ontology=ontology).count()
    force = opt_bool(request, "force", False)
    if entity_count and not force:
        raise ValueError("本体下仍有实体，确认删除请传 force=true")
    data = {"id": ontology.id, "name": ontology.name,
            "entity_count": entity_count}
    with transaction.atomic():
        # EntityType 被 Entity 以 PROTECT 引用，直接删本体会被保护性外键挡住；
        # 因此先按本体级联删实体（关系 / 别名 / 标签随实体级联），再删本体，
        # 让「force 确认后清空本体」在单个事务里完成，失败全量回滚。
        Entity.objects.filter(ontology=ontology).delete()
        ontology.delete()
    record_audit(request.user, "ontology.delete", None, "ontology",
                 data["id"], f"删除本体 {data['name']}")
    return ok({**data, "deleted": True})


@endpoint()
def ontology_publish(request, pk):
    """发布本体：递增版本、写入版本快照与发布说明。"""
    ontology = ontology_for_write(int(pk), request.user)
    if ontology.status == "archived":
        raise ValueError("已归档本体不能发布")
    stats = _ontology_stats(ontology)
    if stats["entity_count"] == 0 and not opt_bool(request, "allow_empty", False):
        raise ValueError("本体下没有实体，确认发布请传 allow_empty=true")
    note = opt_str(request, "note", "")[:2000]
    ontology.version = _next_version(ontology.version)
    ontology.status = "published"
    ontology.save(update_fields=["version", "status", "updated_at"])
    version = OntologyVersion.objects.create(
        owner=request.user, ontology=ontology, version=ontology.version,
        note=note, stats=stats, published_by=request.user,
    )
    record_audit(request.user, "ontology.publish", ontology.id, "ontology",
                 ontology.id, f"发布 {ontology.name} {ontology.version}",
                 {"version_id": version.id, "stats": stats})
    return ok({"id": ontology.id, "version": ontology.version,
               "status": ontology.status, "version_id": version.id,
               "stats": stats})


@endpoint()
def ontology_archive(request, pk):
    """归档本体（只读留存，幂等）。"""
    ontology = ontology_for_write(int(pk), request.user)
    if ontology.status == "archived":
        return ok({"id": ontology.id, "status": ontology.status,
                   "already": True})
    ontology.status = "archived"
    ontology.save(update_fields=["status", "updated_at"])
    record_audit(request.user, "ontology.archive", ontology.id, "ontology",
                 ontology.id, f"归档本体 {ontology.name}")
    return ok({"id": ontology.id, "status": ontology.status})


@endpoint(("GET",))
def ontology_versions(request, pk):
    """本体版本历史（按发布时间倒序）。"""
    ontology = read_obj(Ontology, pk, request.user, "本体")
    page, size = page_args(request)
    qs = ontology.versions.all().order_by("-created_at")
    rows, total = slice_page(qs, page, size)
    return ok(page_payload([ontology_version_dict(v) for v in rows],
                           total, page, size,
                           current_version=ontology.version))


# ---------------------------------------------------------------------------
# 实体类型
# ---------------------------------------------------------------------------


def _unique_type_code(ontology, base, model, exclude_pk=None):
    """类型标识去重：同本体内 code 唯一，冲突自动追加 -2 / -3。"""
    candidate = slugify_code(base, "type")
    index = 2
    while True:
        qs = model.objects.filter(ontology=ontology, code=candidate)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        candidate = f"{slugify_code(base, 'type')}-{index}"
        index += 1


def _parent_type(parent_id, ontology):
    """校验父类型：必须存在、同本体、不能形成环（由 update 侧继续校验）。"""
    if not parent_id:
        return None
    parent = EntityType.objects.filter(pk=parent_id).first()
    if parent is None:
        raise ValueError("父类型不存在")
    if parent.ontology_id != ontology.id:
        raise ValueError("父类型必须属于同一本体")
    return parent


@endpoint()
def entity_type_create(request):
    """创建实体类型（同本体 code 唯一，可指定继承类型）。"""
    ontology = ontology_for_write(req_num(request, "ontology_id"), request.user)
    name = req_str(request, "name", max_len=80).strip()
    if not name:
        raise ValueError("类型名称不能为空")
    code = opt_str(request, "code", "").strip()
    if code:
        if EntityType.objects.filter(ontology=ontology, code=code).exists():
            raise ValueError("类型标识已存在")
        final_code = code[:80]
    else:
        final_code = _unique_type_code(ontology, name, EntityType)
    parent = _parent_type(int_arg(request, "parent_id"), ontology)
    etype = EntityType.objects.create(
        owner=request.user, ontology=ontology, name=name[:80],
        code=final_code, color=opt_str(request, "color", "#409eff")[:20] or "#409eff",
        icon=opt_str(request, "icon", "")[:40],
        attr_schema=json_arg(request, "attr_schema", {}),
        parent=parent, enabled=not opt_bool(request, "disabled", False),
    )
    record_audit(request.user, "entity_type.create", ontology.id, "entity_type",
                 etype.id, f"创建实体类型 {etype.name}")
    return ok(entity_type_dict(etype))


@endpoint(("GET",))
def entity_type_list(request):
    """实体类型列表（支持本体 / 启用状态 / 关键字）。"""
    from core.scoping import scope_queryset

    qs = scope_queryset(EntityType.objects.all(), request.user).order_by("name")
    ontology_id = int_arg(request, "ontology_id")
    if ontology_id:
        qs = qs.filter(ontology_id=ontology_id)
    if p(request, "enabled") not in (None, ""):
        qs = qs.filter(enabled=not opt_bool(request, "disabled", False))
    rows, total, page, size = list_queryset(
        request, qs, ["name", "code"], status_field=None)
    return ok(page_payload([entity_type_dict(t) for t in rows], total, page, size))


@endpoint(("GET",))
def entity_type_detail(request, pk):
    """实体类型详情（附实体数量与子类型）。"""
    etype = read_obj(EntityType, pk, request.user, "实体类型")
    data = entity_type_dict(etype)
    data["entity_count"] = Entity.objects.filter(entity_type=etype).count()
    data["children"] = [entity_type_dict(t) for t in etype.children.all()[:50]]
    return ok(data)


@endpoint()
def entity_type_update(request, pk):
    """更新实体类型（父类型禁止指向自身或后代，避免继承环）。"""
    etype = write_obj(EntityType, pk, request.user, "实体类型")
    name = opt_str(request, "name", "").strip()
    if name:
        etype.name = name[:80]
    if p(request, "code") is not None:
        code = opt_str(request, "code").strip()
        if not code:
            raise ValueError("类型标识不能为空")
        conflict = EntityType.objects.filter(
            ontology_id=etype.ontology_id, code=code).exclude(pk=etype.pk).exists()
        if conflict:
            raise ValueError("类型标识已存在")
        etype.code = code[:80]
    if p(request, "color") is not None:
        etype.color = opt_str(request, "color", "#409eff")[:20] or "#409eff"
    if p(request, "icon") is not None:
        etype.icon = opt_str(request, "icon")[:40]
    if p(request, "attr_schema") is not None:
        etype.attr_schema = json_arg(request, "attr_schema", {})
    if p(request, "parent_id") is not None:
        parent_id = int_arg(request, "parent_id")
        if parent_id == etype.id:
            raise ValueError("父类型不能是自身")
        parent = _parent_type(parent_id, etype.ontology)
        # 沿父链向上检查，防止把父类型设成自己的后代形成环
        cursor = parent
        while cursor is not None:
            if cursor.id == etype.id:
                raise ValueError("父类型不能是自身的后代")
            cursor = cursor.parent
        etype.parent = parent
    if p(request, "enabled") is not None:
        etype.enabled = opt_bool(request, "enabled", True)
    etype.save()
    record_audit(request.user, "entity_type.update", etype.ontology_id,
                 "entity_type", etype.id, f"更新实体类型 {etype.name}")
    return ok(entity_type_dict(etype))


@endpoint()
def entity_type_delete(request, pk):
    """删除实体类型（类型下仍有实体时禁止删除）。"""
    etype = write_obj(EntityType, pk, request.user, "实体类型")
    entity_count = Entity.objects.filter(entity_type=etype).count()
    if entity_count:
        raise ValueError(f"该类型下仍有 {entity_count} 个实体，请先迁移或删除实体")
    if etype.children.exists():
        raise ValueError("该类型仍有子类型，请先处理子类型")
    if RelationType.objects.filter(Q(source_type=etype) | Q(target_type=etype)).exists():
        raise ValueError("该类型仍被关系类型引用，请先调整关系类型")
    etype_id, name = etype.id, etype.name
    etype.delete()
    record_audit(request.user, "entity_type.delete", None, "entity_type",
                 etype_id, f"删除实体类型 {name}")
    return ok({"id": etype_id, "deleted": True})


# ---------------------------------------------------------------------------
# 关系类型
# ---------------------------------------------------------------------------


def _relation_endpoint_type(type_id, ontology, label):
    """关系类型两端的实体类型校验：必须同本体。"""
    if not type_id:
        return None
    etype = EntityType.objects.filter(pk=type_id).first()
    if etype is None:
        raise ValueError(f"{label}不存在")
    if etype.ontology_id != ontology.id:
        raise ValueError(f"{label}必须属于同一本体")
    return etype


@endpoint()
def relation_type_create(request):
    """创建关系类型（可约束源 / 目标实体类型与方向）。"""
    ontology = ontology_for_write(req_num(request, "ontology_id"), request.user)
    name = req_str(request, "name", max_len=80).strip()
    if not name:
        raise ValueError("关系名称不能为空")
    code = opt_str(request, "code", "").strip()
    if code:
        if RelationType.objects.filter(ontology=ontology, code=code).exists():
            raise ValueError("关系标识已存在")
        final_code = code[:80]
    else:
        final_code = _unique_type_code(ontology, name, RelationType)
    source_type = _relation_endpoint_type(int_arg(request, "source_type_id"),
                                          ontology, "源类型")
    target_type = _relation_endpoint_type(int_arg(request, "target_type_id"),
                                          ontology, "目标类型")
    rtype = RelationType.objects.create(
        owner=request.user, ontology=ontology, name=name[:80], code=final_code,
        source_type=source_type, target_type=target_type,
        directed=not opt_bool(request, "undirected", False),
        attr_schema=json_arg(request, "attr_schema", {}),
        weight=round(float(req_num(request, "weight", 1.0, minimum=0.01,
                                   maximum=100)), 4),
        enabled=not opt_bool(request, "disabled", False),
    )
    record_audit(request.user, "relation_type.create", ontology.id,
                 "relation_type", rtype.id, f"创建关系类型 {rtype.name}")
    return ok(relation_type_dict(rtype))


@endpoint(("GET",))
def relation_type_list(request):
    """关系类型列表（支持本体 / 启用状态 / 关键字）。"""
    from core.scoping import scope_queryset

    qs = scope_queryset(RelationType.objects.all(), request.user).order_by("name")
    ontology_id = int_arg(request, "ontology_id")
    if ontology_id:
        qs = qs.filter(ontology_id=ontology_id)
    if p(request, "enabled") not in (None, ""):
        qs = qs.filter(enabled=not opt_bool(request, "disabled", False))
    rows, total, page, size = list_queryset(
        request, qs, ["name", "code"], status_field=None)
    return ok(page_payload([relation_type_dict(t) for t in rows], total, page, size))


@endpoint(("GET",))
def relation_type_detail(request, pk):
    """关系类型详情（附使用数量）。"""
    rtype = read_obj(RelationType, pk, request.user, "关系类型")
    data = relation_type_dict(rtype)
    data["relation_count"] = Relation.objects.filter(relation_type=rtype,
                                                     status="active").count()
    return ok(data)


@endpoint()
def relation_type_update(request, pk):
    """更新关系类型（两端类型必须与本体一致）。"""
    rtype = write_obj(RelationType, pk, request.user, "关系类型")
    name = opt_str(request, "name", "").strip()
    if name:
        rtype.name = name[:80]
    if p(request, "code") is not None:
        code = opt_str(request, "code").strip()
        if not code:
            raise ValueError("关系标识不能为空")
        conflict = RelationType.objects.filter(
            ontology_id=rtype.ontology_id, code=code).exclude(pk=rtype.pk).exists()
        if conflict:
            raise ValueError("关系标识已存在")
        rtype.code = code[:80]
    if p(request, "source_type_id") is not None:
        rtype.source_type = _relation_endpoint_type(
            int_arg(request, "source_type_id"), rtype.ontology, "源类型")
    if p(request, "target_type_id") is not None:
        rtype.target_type = _relation_endpoint_type(
            int_arg(request, "target_type_id"), rtype.ontology, "目标类型")
    if p(request, "directed") is not None:
        rtype.directed = opt_bool(request, "directed", True)
    if p(request, "attr_schema") is not None:
        rtype.attr_schema = json_arg(request, "attr_schema", {})
    if p(request, "weight") is not None:
        rtype.weight = round(float(req_num(request, "weight", minimum=0.01,
                                           maximum=100)), 4)
    if p(request, "enabled") is not None:
        rtype.enabled = opt_bool(request, "enabled", True)
    rtype.save()
    record_audit(request.user, "relation_type.update", rtype.ontology_id,
                 "relation_type", rtype.id, f"更新关系类型 {rtype.name}")
    return ok(relation_type_dict(rtype))


@endpoint()
def relation_type_delete(request, pk):
    """删除关系类型（仍有生效关系时禁止删除）。"""
    rtype = write_obj(RelationType, pk, request.user, "关系类型")
    relation_count = Relation.objects.filter(relation_type=rtype,
                                             status="active").count()
    if relation_count:
        raise ValueError(f"该关系类型下仍有 {relation_count} 条关系，请先删除关系")
    rtype_id, name = rtype.id, rtype.name
    rtype.delete()
    record_audit(request.user, "relation_type.delete", None, "relation_type",
                 rtype_id, f"删除关系类型 {name}")
    return ok({"id": rtype_id, "deleted": True})


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def audit_list(request):
    """图谱审计列表（数据范围内，支持本体 / 动作 / 关键字）。"""
    from core.scoping import scope_queryset

    qs = scope_queryset(GraphAudit.objects.all(), request.user).order_by("-created_at")
    ontology_id = int_arg(request, "ontology_id")
    if ontology_id:
        qs = qs.filter(ontology_id=ontology_id)
    action = opt_str(request, "action").strip()
    if action:
        qs = qs.filter(action=action)
    rows, total, page, size = list_queryset(
        request, qs, ["action", "summary", "target_type"], status_field=None)
    from knowledgegraph.common import audit_dict

    return ok(page_payload([audit_dict(a) for a in rows], total, page, size))


ONTOLOGY_FAMILY_COUNT = 8 + 5 + 5 + 1
