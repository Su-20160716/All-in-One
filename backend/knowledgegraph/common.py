# -*- coding: utf-8 -*-
"""knowledgegraph 视图公共层：分页四件套、入参解析、对象读取与序列化。

为什么单独一层：
- 分页协议、权限判定、JSON 入参校验在 80+ 个接口里重复出现，写一次
  才能保证「列表永远是 items/count/page/page_size」不被某个接口破坏；
- 读权限（scope_queryset）与写权限（can_write）是两套语义，必须在取对象
  时就分开，否则很容易出现「部门可见 = 谁都能改」的越权；
- 序列化统一在这里做，视图只负责组装业务参数，减少字段拼写漂移。
"""
import json

from django.db.models import Q

from core.scoping import can_write, scope_queryset
from devtools.common import opt_num, opt_str, p
from knowledgegraph.models import (DEFAULT_PAGE_SIZE, ENTITY_STATUS_LABELS,
                                   ENTITY_STATUSES, JOB_STATUS_LABELS,
                                   JOB_STATUSES, MAX_PAGE_SIZE,
                                   MERGE_STATUS_LABELS, MERGE_STATUSES,
                                   ONTOLOGY_STATUS_LABELS, ONTOLOGY_STATUSES,
                                   RELATION_STATUS_LABELS, RELATION_STATUSES,
                                   SOURCE_TYPE_LABELS, SOURCE_TYPES, Entity,
                                   EntityAlias, EntityTag, EntityType,
                                   ExtractionCandidate, ExtractionJob, GraphAudit,
                                   GraphQuery, GraphSnapshot, MergeLog,
                                   MergeRequest, Ontology, OntologyVersion,
                                   PathCache, QueryRun, Relation, RelationType,
                                   Source, clamp_confidence)


# ---------------------------------------------------------------------------
# 分页
# ---------------------------------------------------------------------------


def page_args(request):
    """统一解析 page / page_size（page_size 上限 200，防止一次拉爆内存）。"""
    page = int(opt_num(request, "page", 1, minimum=1, maximum=100000, integer=True))
    size = int(opt_num(request, "page_size", DEFAULT_PAGE_SIZE, minimum=1,
                       maximum=MAX_PAGE_SIZE, integer=True))
    return page, size


def slice_page(qs, page, size):
    """按页切片并返回总数；count 用 queryset 自身计数，与切片无关。"""
    total = qs.count()
    start = (page - 1) * size
    return list(qs[start:start + size]), total


def page_payload(items, count, page, size, **extra):
    """统一列表响应体：四件套固定，额外汇总字段平行放置。"""
    payload = {"items": items, "count": count, "page": page, "page_size": size}
    payload.update(extra)
    return payload


def list_queryset(request, qs, search_fields, status_field="status",
                  extra_filters=None):
    """列表通用流程：关键字 → 状态 → 附加过滤 → 分页。

    extra_filters 形如 {参数名: (orm 字段, 转换函数)}；转换失败抛 ValueError
    给出中文提示，避免 "invalid literal for int()" 直接暴露给前端。
    """
    page, size = page_args(request)
    q = opt_str(request, "q").strip()
    if q:
        cond = Q()
        for name in search_fields:
            cond |= Q(**{f"{name}__icontains": q})
        qs = qs.filter(cond)
    status = opt_str(request, "status").strip()
    if status and status_field:
        qs = qs.filter(**{status_field: status})
    for arg, (orm_field, caster) in (extra_filters or {}).items():
        raw = p(request, arg)
        if raw in (None, ""):
            continue
        try:
            value = caster(raw)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {arg} 非法")
        qs = qs.filter(**{orm_field: value})
    rows, total = slice_page(qs, page, size)
    return rows, total, page, size


# ---------------------------------------------------------------------------
# 入参解析
# ---------------------------------------------------------------------------


def json_arg(request, key, default=None, expect=(dict, list), required=False):
    """解析 JSON 形态入参：accepts dict/list 原生值或 JSON 字符串。

    前端两种传法都存在（axios 序列化 vs 表单 textarea 手写 JSON），
    统一在这里兼容；字符串解析失败给中文提示，而不是抛 JSONDecodeError。
    """
    raw = p(request, key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return {} if default is None and dict in expect else ([] if default is None else default)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数 {key} 不是合法 JSON: {exc.msg}")
    if expect and not isinstance(raw, expect):
        names = "/".join(t.__name__ for t in expect)
        raise ValueError(f"参数 {key} 必须是 {names}")
    return raw


def int_arg(request, key, default=None, minimum=None, maximum=None):
    """整数入参（四舍五入到整数），上下界失败给中文提示。"""
    value = opt_num(request, key, default, minimum=minimum, maximum=maximum,
                    integer=True)
    # opt_num 在「参数缺失且 default 为 None」时返回 None；直接 int(None)
    # 会变成 500/422，这里统一回落默认值，让调用方自己用 None 判断必填。
    if value is None:
        return default
    return int(value)


def float_arg(request, key, default=None, minimum=None, maximum=None):
    """浮点入参（带 finite 校验，NaN/Inf 会被 devtools 拦截）。"""
    value = opt_num(request, key, default, minimum=minimum, maximum=maximum)
    if value is None:
        return default
    return float(value)


def choice_arg(request, key, choices, default=None, required=False):
    """枚举入参：不在白名单里直接 400，避免脏状态写库。"""
    value = opt_str(request, key, "").strip()
    if not value:
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default if default is not None else ""
    if value not in choices:
        raise ValueError(f"参数 {key} 仅支持: {'/'.join(choices)}")
    return value


def bool_arg(request, key, default=False):
    """布尔入参：兼容 true/false 与 1/0（与 devtools.opt_bool 同口径）。"""
    from devtools.common import opt_bool

    return opt_bool(request, key, default)


def ids_arg(request, key, required=False, max_len=500):
    """id 数组入参：去重、保持顺序、限制长度。"""
    raw = p(request, key)
    if raw in (None, "", []):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return []
    if isinstance(raw, str):
        raw = [x for x in raw.replace("，", ",").split(",") if x.strip()]
    if not isinstance(raw, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(raw) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    out = []
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 含非整数项")
        if value not in out:
            out.append(value)
    return out


# ---------------------------------------------------------------------------
# 对象读取（读 / 写分离）
# ---------------------------------------------------------------------------


def read_obj(model, pk, user, label="对象"):
    """按数据范围读取对象；不存在与无权访问统一提示，避免探测 id。"""
    obj = scope_queryset(model.objects.all(), user).filter(pk=pk).first()
    if obj is None:
        raise ValueError(f"{label}不存在或无权访问")
    return obj


def write_obj(model, pk, user, label="对象"):
    """按写权限读取对象：先判存在，再判 owner，报错更精确。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(f"{label}不存在")
    if not can_write(user, obj):
        raise ValueError(f"无权修改该{label}")
    return obj


def owned_child(model, pk, user, label="对象"):
    """子对象（别名 / 标签 / 关系）的读取：同样走数据范围。"""
    return read_obj(model, pk, user, label)


def entity_for_write(entity_id, user):
    """实体写权限入口：合并、拆分、归档都不会允许跨用户操作。"""
    try:
        pk = int(entity_id)
    except (TypeError, ValueError):
        raise ValueError("实体ID必须是整数")
    return write_obj(Entity, pk, user, "实体")


def ontology_for_write(ontology_id, user):
    """本体写权限入口。"""
    try:
        pk = int(ontology_id)
    except (TypeError, ValueError):
        raise ValueError("本体ID必须是整数")
    return write_obj(Ontology, pk, user, "本体")


def ensure_ontology_mutable(ontology):
    """已归档本体禁止写入：归档语义是「只读留存」。

    如果不拦截，用户可以在归档本体里继续加实体，归档就失去意义了。
    """
    if ontology.status == "archived":
        raise ValueError("本体已归档，不能继续修改")
    return ontology


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _dt(value):
    """时间字段统一 ISO 字符串，跨时区可排序；空值返回空串。"""
    if not value:
        return ""
    return value.isoformat()


def ontology_dict(o, with_counts=False):
    data = {
        "id": o.id,
        "name": o.name,
        "namespace": o.namespace,
        "description": o.description,
        "version": o.version,
        "status": o.status,
        "owner_id": o.owner_id,
        "created_at": _dt(o.created_at),
        "updated_at": _dt(o.updated_at),
    }
    if with_counts:
        data["entity_count"] = getattr(o, "entity_count", None)
        data["relation_count"] = getattr(o, "relation_count", None)
    return data


def ontology_version_dict(v):
    return {
        "id": v.id,
        "ontology_id": v.ontology_id,
        "version": v.version,
        "note": v.note,
        "stats": v.stats or {},
        "published_by_id": v.published_by_id,
        "created_at": _dt(v.created_at),
    }


def entity_type_dict(t):
    return {
        "id": t.id,
        "ontology_id": t.ontology_id,
        "name": t.name,
        "code": t.code,
        "color": t.color,
        "icon": t.icon,
        "attr_schema": t.attr_schema or {},
        "parent_id": t.parent_id,
        "enabled": t.enabled,
        "created_at": _dt(t.created_at),
        "updated_at": _dt(t.updated_at),
    }


def relation_type_dict(t):
    return {
        "id": t.id,
        "ontology_id": t.ontology_id,
        "name": t.name,
        "code": t.code,
        "source_type_id": t.source_type_id,
        "target_type_id": t.target_type_id,
        "directed": t.directed,
        "attr_schema": t.attr_schema or {},
        "weight": t.weight,
        "enabled": t.enabled,
        "created_at": _dt(t.created_at),
        "updated_at": _dt(t.updated_at),
    }


def entity_dict(e, with_type=True):
    data = {
        "id": e.id,
        "ontology_id": e.ontology_id,
        "entity_type_id": e.entity_type_id,
        "name": e.name,
        "canonical_name": e.canonical_name,
        "description": e.description,
        "attrs": e.attrs or {},
        "source_id": e.source_id,
        "confidence": e.confidence,
        "status": e.status,
        "created_by_id": e.created_by_id,
        "created_at": _dt(e.created_at),
        "updated_at": _dt(e.updated_at),
    }
    if with_type:
        # select_related 后直接取，未预取时退化为 None，不触发额外查询也可以接受
        etype = getattr(e, "entity_type", None)
        data["entity_type"] = etype.name if etype else ""
        data["entity_type_code"] = etype.code if etype else ""
        data["entity_type_color"] = etype.color if etype else ""
    return data


def alias_dict(a):
    return {
        "id": a.id,
        "entity_id": a.entity_id,
        "alias": a.alias,
        "lang": a.lang,
        "source": a.source,
        "confidence": a.confidence,
        "created_at": _dt(a.created_at),
    }


def relation_dict(r):
    return {
        "id": r.id,
        "ontology_id": r.ontology_id,
        "relation_type_id": r.relation_type_id,
        "source_entity_id": r.source_entity_id,
        "target_entity_id": r.target_entity_id,
        "attrs": r.attrs or {},
        "weight": r.weight,
        "confidence": r.confidence,
        "source": r.source,
        "status": r.status,
        "created_at": _dt(r.created_at),
    }


def query_dict(q):
    return {
        "id": q.id,
        "ontology_id": q.ontology_id,
        "name": q.name,
        "kind": q.kind,
        "dsl": q.dsl,
        "params": q.params or {},
        "description": q.description,
        "created_at": _dt(q.created_at),
        "updated_at": _dt(q.updated_at),
    }


def run_dict(r):
    return {
        "id": r.id,
        "query_id": r.query_id,
        "kind": r.kind,
        "params": r.params or {},
        "elapsed_ms": r.elapsed_ms,
        "node_count": r.node_count,
        "edge_count": r.edge_count,
        "status": r.status,
        "error": r.error,
        "created_at": _dt(r.created_at),
    }


def tag_dict(t):
    return {
        "id": t.id,
        "entity_id": t.entity_id,
        "tag": t.tag,
        "weight": t.weight,
        "created_at": _dt(t.created_at),
    }


def source_dict(s):
    return {
        "id": s.id,
        "name": s.name,
        "type": s.type,
        "description": s.description,
        "config": s.config or {},
        "created_at": _dt(s.created_at),
        "updated_at": _dt(s.updated_at),
    }


def job_dict(j):
    return {
        "id": j.id,
        "source_id": j.source_id,
        "ontology_id": j.ontology_id,
        "status": j.status,
        "rules": j.rules or {},
        "entity_count": j.entity_count,
        "relation_count": j.relation_count,
        "error": j.error,
        "text_length": len(j.text or ""),
        "created_at": _dt(j.created_at),
        "updated_at": _dt(j.updated_at),
    }


def candidate_dict(c):
    return {
        "id": c.id,
        "job_id": c.job_id,
        "kind": c.kind,
        "name": c.name,
        "payload": c.payload or {},
        "confidence": c.confidence,
        "status": c.status,
        "created_at": _dt(c.created_at),
    }


def merge_request_dict(m):
    return {
        "id": m.id,
        "ontology_id": m.ontology_id,
        "source_entity_id": m.source_entity_id,
        "target_entity_id": m.target_entity_id,
        "source_name": getattr(m.source_entity, "name", ""),
        "target_name": getattr(m.target_entity, "name", ""),
        "reason": m.reason,
        "status": m.status,
        "approver_id": m.approver_id,
        "decided_at": _dt(m.decided_at),
        "created_at": _dt(m.created_at),
    }


def merge_log_dict(log):
    return {
        "id": log.id,
        "ontology_id": log.ontology_id,
        "request_id": log.request_id,
        "source_entity_id": log.source_entity_id,
        "target_entity_id": log.target_entity_id,
        "moved_relations": log.moved_relations,
        "merged_aliases": log.merged_aliases,
        "detail": log.detail or {},
        "operator_id": log.operator_id,
        "created_at": _dt(log.created_at),
    }


def snapshot_dict(s):
    return {
        "id": s.id,
        "ontology_id": s.ontology_id,
        "name": s.name,
        "node_count": s.node_count,
        "edge_count": s.edge_count,
        "stats": s.stats or {},
        "note": s.note,
        "created_at": _dt(s.created_at),
    }


def path_cache_dict(c):
    return {
        "id": c.id,
        "ontology_id": c.ontology_id,
        "start_entity_id": c.start_entity_id,
        "end_entity_id": c.end_entity_id,
        "max_depth": c.max_depth,
        "weighted": c.weighted,
        "path": c.path or [],
        "cost": c.cost,
        "generated_at": _dt(c.generated_at),
    }


def audit_dict(a):
    return {
        "id": a.id,
        "ontology_id": a.ontology_id,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "summary": a.summary,
        "detail": a.detail or {},
        "actor_id": a.actor_id,
        "created_at": _dt(a.created_at),
    }


def clamp(value, default=0.8):
    """视图层夹取置信度 / 权重的快捷入口（与服务层同口径）。"""
    return clamp_confidence(value, default)


def clamp_weight(value, default=1.0):
    """把关系 / 标签权重夹取到 [0.01, 100]。

    权重不是置信度：1.0 只是默认值而不是上限，用 clamp_confidence 会把
    「权重 2/3」直接压成 1，导致加权最短路与标签热度全部失真。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return float(default)
    if num != num:  # NaN
        return float(default)
    return round(min(100.0, max(0.01, num)), 4)


def record_audit(user, action, ontology_id=None, target_type="", target_id=None,
                 summary="", detail=None):
    """写一条图谱审计：所有会改变结构的写操作都应留痕。

    审计失败不阻断主流程（主流程已经写过业务数据），但会把异常吞掉并
    返回 None——「日志不重要到可以回滚业务」是明确的取舍。
    """
    try:
        return GraphAudit.objects.create(
            owner=user, ontology_id=ontology_id, action=action,
            target_type=target_type, target_id=target_id,
            summary=(summary or "")[:300], detail=detail or {}, actor=user,
        )
    except Exception:  # noqa: BLE001 —— 审计失败不影响业务写入
        return None


def slugify_code(text, fallback="type"):
    """把名称转成标识：小写、非字母数字转下划线、压缩连续下划线。

    标识用于 RelationType/EntityType.code 的稳定引用（抽取规则、DSL 都按
    code 匹配），因此不能包含空格与中文标点；空结果回落到 fallback。
    """
    import re

    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", str(text or "").strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:80] or fallback


def search_entities_for_user(user, q, ontology_id=None, type_ids=None, limit=20):
    """按数据范围做加权实体搜索，供实体搜索与图搜索两个接口共用。

    先由数据库用 icontains / 别名字查询把候选压到 3000 条以内，再交给
    服务层做加权评分：纯 Python 打分无法处理上万实体，纯 SQL 又做不出
    「名称命中权重高于描述」的排序，两段式是必要的折中。
    """
    from knowledgegraph import services

    qs = scope_queryset(Entity.objects.select_related("entity_type"), user).filter(
        status="active")
    if ontology_id:
        qs = qs.filter(ontology_id=ontology_id)
    alias_entity_ids = EntityAlias.objects.filter(
        owner=user, alias__icontains=q).values_list("entity_id", flat=True)
    qs = qs.filter(
        Q(name__icontains=q) | Q(canonical_name__icontains=q)
        | Q(description__icontains=q) | Q(id__in=alias_entity_ids)
    )[:3000]
    entities = [services.entity_lite(e) for e in qs]
    alias_map = {}
    ids = [e["id"] for e in entities]
    for alias in EntityAlias.objects.filter(entity_id__in=ids)[:10000]:
        alias_map.setdefault(alias.entity_id, []).append(alias.alias)
    return services.search_entities(entities, alias_map, q, limit=limit,
                                    type_ids=type_ids)


# 目录枚举：前端一次性拉取，避免各页面硬编码中文名
CATALOG_ENUMS = {
    "ontology_status": [{"value": v, "label": ONTOLOGY_STATUS_LABELS.get(v, v)}
                        for v in ONTOLOGY_STATUSES],
    "entity_status": [{"value": v, "label": ENTITY_STATUS_LABELS.get(v, v)}
                      for v in ENTITY_STATUSES],
    "relation_status": [{"value": v, "label": RELATION_STATUS_LABELS.get(v, v)}
                        for v in RELATION_STATUSES],
    "job_status": [{"value": v, "label": JOB_STATUS_LABELS.get(v, v)}
                   for v in JOB_STATUSES],
    "merge_status": [{"value": v, "label": MERGE_STATUS_LABELS.get(v, v)}
                     for v in MERGE_STATUSES],
    "source_type": [{"value": v, "label": SOURCE_TYPE_LABELS.get(v, v)}
                    for v in SOURCE_TYPES],
}


# 显式导出：目录视图与测试会按名字断言，避免 __all__ 漏项
_MODELS = (
    Ontology, OntologyVersion, EntityType, RelationType, Entity, EntityAlias,
    Relation, GraphQuery, QueryRun, EntityTag, Source, ExtractionJob,
    ExtractionCandidate, MergeRequest, MergeLog, GraphSnapshot, PathCache,
    GraphAudit,
)


def model_labels():
    """模型清单（目录接口展示规模用）。"""
    return [m._meta.verbose_name for m in _MODELS]
