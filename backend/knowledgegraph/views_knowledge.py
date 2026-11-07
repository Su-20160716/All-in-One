# -*- coding: utf-8 -*-
"""knowledgegraph · 来源 / 抽取 / 合并申请 / 快照接口。

四个家族共 23 个接口：
- 来源 5：抽取任务的输入载体（文档 / 笔记 / 上传 / 手工）；
- 抽取 7：规则任务 → 候选 → 人工接受（接受才写入图谱）/ 拒绝；
- 合并申请 5：申请 → 审批（通过时真正执行合并并写 MergeLog）；
- 快照 6：生成 / 列表 / 详情 / 删除 / 对比。

共同约束：
- 所有写操作先取 owner 校验（write_obj），不能借「能看见」来改；
- 接受候选、审批合并、生成快照都在事务内完成；
- 任何失败都把可读原因写回记录（job.error / candidate 状态不变），
  避免「操作黑箱」。
"""
import time

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.scoping import can_write, scope_queryset
from devtools.common import (endpoint, ok, opt_bool, opt_str, p, req_num,
                             req_str)
from knowledgegraph import services
from knowledgegraph.common import (bool_arg, candidate_dict, clamp,
                                   choice_arg, float_arg, int_arg, job_dict,
                                   json_arg, list_queryset, merge_log_dict,
                                   merge_request_dict, ontology_for_write,
                                   page_args, page_payload, read_obj,
                                   record_audit, slice_page, source_dict,
                                   snapshot_dict, write_obj)
from knowledgegraph.models import (CANDIDATE_KINDS, CANDIDATE_STATUSES,
                                   JOB_STATUSES, MERGE_STATUSES, SOURCE_TYPES,
                                   Entity, EntityAlias, EntityType,
                                   ExtractionCandidate, ExtractionJob,
                                   GraphSnapshot, MergeLog, MergeRequest,
                                   Ontology, Relation, RelationType, Source)
from knowledgegraph.views_graph import _load_graph


# ---------------------------------------------------------------------------
# 来源
# ---------------------------------------------------------------------------


@endpoint()
def source_create(request):
    """创建知识来源。"""
    name = req_str(request, "name", max_len=200).strip()
    if not name:
        raise ValueError("来源名称不能为空")
    source = Source.objects.create(
        owner=request.user, name=name[:200],
        type=choice_arg(request, "type", SOURCE_TYPES, "manual"),
        description=opt_str(request, "description")[:4000],
        config=json_arg(request, "config", {}),
    )
    record_audit(request.user, "source.create", None, "source", source.id,
                 f"创建来源 {source.name}")
    return ok(source_dict(source))


@endpoint(("GET",))
def source_list(request):
    """来源列表（支持类型 / 关键字）。"""
    qs = scope_queryset(Source.objects.all(), request.user).order_by("-created_at")
    rows, total, page, size = list_queryset(
        request, qs, ["name", "description"], status_field=None,
        extra_filters={"type": ("type", str)},
    )
    return ok(page_payload([source_dict(s) for s in rows], total, page, size))


@endpoint(("GET",))
def source_detail(request, pk):
    """来源详情（附任务数量与最近任务）。"""
    source = read_obj(Source, pk, request.user, "来源")
    data = source_dict(source)
    data["job_count"] = source.extraction_jobs.count()
    data["recent_jobs"] = [job_dict(j) for j in source.extraction_jobs.all()[:10]]
    return ok(data)


@endpoint()
def source_update(request, pk):
    """更新来源（名称 / 类型 / 描述 / 配置）。"""
    source = write_obj(Source, pk, request.user, "来源")
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("来源名称不能为空")
        source.name = name[:200]
    if p(request, "type") not in (None, ""):
        source.type = choice_arg(request, "type", SOURCE_TYPES, source.type)
    if p(request, "description") is not None:
        source.description = opt_str(request, "description")[:4000]
    if p(request, "config") is not None:
        source.config = json_arg(request, "config", {})
    source.save()
    return ok(source_dict(source))


@endpoint()
def source_delete(request, pk):
    """删除来源（存在抽取任务时需 force=true，级联删除任务与候选）。"""
    source = write_obj(Source, pk, request.user, "来源")
    job_count = source.extraction_jobs.count()
    if job_count and not opt_bool(request, "force", False):
        raise ValueError(f"该来源下有 {job_count} 个抽取任务，确认删除请传 force=true")
    source_id, name = source.id, source.name
    source.delete()
    record_audit(request.user, "source.delete", None, "source", source_id,
                 f"删除来源 {name}")
    return ok({"id": source_id, "deleted": True, "job_count": job_count})


# ---------------------------------------------------------------------------
# 抽取任务
# ---------------------------------------------------------------------------


def _job_rules(request):
    """抽取规则：{dictionary: [...], patterns: [...]}，非法结构直接 400。"""
    rules = json_arg(request, "rules", {})
    if not isinstance(rules, dict):
        raise ValueError("rules 必须是对象")
    dictionary = rules.get("dictionary")
    if dictionary is not None and not isinstance(dictionary, (dict, list)):
        raise ValueError("rules.dictionary 必须是对象或数组")
    patterns = rules.get("patterns")
    if patterns is not None:
        if not isinstance(patterns, list):
            raise ValueError("rules.patterns 必须是数组")
        for index, item in enumerate(patterns):
            if not isinstance(item, dict) or not item.get("regex") or not item.get("code"):
                raise ValueError(f"rules.patterns[{index}] 需要 code 与 regex")
    return rules


def _source_text(source, explicit):
    """抽取文本：请求显式文本优先，其次来源配置里的 text，最后为空。"""
    text = explicit or (source.config or {}).get("text") or ""
    text = str(text)
    if len(text) > 200000:
        raise ValueError("待抽取文本超过 200000 字符，请拆分为多个来源")
    return text


@endpoint()
def extraction_job_create(request):
    """创建抽取任务（queued，规则与文本可后置补充）。"""
    source = write_obj(Source, int(req_num(request, "source_id")),
                       request.user, "来源")
    ontology = ontology_for_write(req_num(request, "ontology_id"), request.user)
    job = ExtractionJob.objects.create(
        owner=request.user, source=source, ontology=ontology, status="queued",
        rules=_job_rules(request),
        text=_source_text(source, opt_str(request, "text", ""))[:200000],
    )
    record_audit(request.user, "extraction.create", ontology.id, "job", job.id,
                 f"创建抽取任务 #{job.id}")
    return ok(job_dict(job))


@endpoint(("GET",))
def extraction_job_list(request):
    """抽取任务列表（支持来源 / 本体 / 状态）。"""
    qs = scope_queryset(ExtractionJob.objects.all(), request.user
                        ).order_by("-created_at")
    rows, total, page, size = list_queryset(
        request, qs, ["error"], "status",
        extra_filters={"source_id": ("source_id", int),
                       "ontology_id": ("ontology_id", int)},
    )
    return ok(page_payload([job_dict(j) for j in rows], total, page, size))


@endpoint(("GET",))
def extraction_job_detail(request, pk):
    """抽取任务详情（候选统计 + 候选预览）。"""
    job = read_obj(ExtractionJob, pk, request.user, "抽取任务")
    data = job_dict(job)
    pending = job.candidates.filter(status="pending")
    data["pending_count"] = pending.count()
    data["accepted_count"] = job.candidates.filter(status="accepted").count()
    data["rejected_count"] = job.candidates.filter(status="rejected").count()
    data["candidates"] = [candidate_dict(c) for c in pending[:30]]
    data["source_name"] = job.source.name
    return ok(data)


@endpoint()
def extraction_job_update(request, pk):
    """更新抽取任务（文本 / 规则；执行中的任务不可改）。"""
    job = write_obj(ExtractionJob, pk, request.user, "抽取任务")
    if job.status == "running":
        raise ValueError("任务正在执行中，不能修改")
    if p(request, "text") is not None:
        job.text = _source_text(job.source, opt_str(request, "text", ""))[:200000]
    if p(request, "rules") is not None:
        job.rules = _job_rules(request)
    if p(request, "source_id") is not None:
        job.source = write_obj(Source, int(req_num(request, "source_id")),
                               request.user, "来源")
    if p(request, "ontology_id") is not None:
        job.ontology = ontology_for_write(req_num(request, "ontology_id"),
                                          request.user)
    # 改了规则或文本，旧候选已不代表当前任务，回到 queued 等重新执行
    if job.status == "done":
        job.status = "queued"
    job.save()
    return ok(job_dict(job))


@endpoint()
def extraction_job_delete(request, pk):
    """删除抽取任务（级联删除候选）。"""
    job = write_obj(ExtractionJob, pk, request.user, "抽取任务")
    if job.status == "running":
        raise ValueError("任务正在执行中，不能删除")
    job_id = job.id
    job.delete()
    return ok({"id": job_id, "deleted": True})


@endpoint(("GET",))
def extraction_job_candidates(request, pk):
    """某个抽取任务的候选列表（等价于 extraction/candidates?job_id=）。"""
    job = read_obj(ExtractionJob, pk, request.user, "抽取任务")
    status = opt_str(request, "status", "").strip()
    qs = job.candidates.all()
    if status:
        if status not in CANDIDATE_STATUSES:
            raise ValueError("候选状态仅支持: " + "/".join(CANDIDATE_STATUSES))
        qs = qs.filter(status=status)
    page, size = page_args(request)
    rows, total = slice_page(qs.order_by("-confidence", "id"), page, size)
    return ok(page_payload([candidate_dict(c) for c in rows], total, page, size,
                           job_id=job.id))


@endpoint()
def extraction_job_run(request, pk):
    """执行抽取任务：规则生成候选（重复执行会清掉上一轮待处理候选）。"""
    job = write_obj(ExtractionJob, pk, request.user, "抽取任务")
    if job.status == "running":
        raise ValueError("任务正在执行中，请稍后再试")
    if p(request, "text") is not None:
        job.text = _source_text(job.source, opt_str(request, "text", ""))[:200000]
    if not job.text.strip():
        raise ValueError("待抽取文本为空，请先在来源配置或任务里提供文本")
    if p(request, "rules") is not None:
        job.rules = _job_rules(request)
    job.status = "running"
    job.error = ""
    job.save(update_fields=["status", "error", "text", "rules", "updated_at"])
    started = time.perf_counter()
    try:
        rules = job.rules or {}
        candidates = services.extract_candidates(
            job.text, rules.get("dictionary"), rules.get("patterns"))
        summary = services.summarize_candidates(candidates)
        with transaction.atomic():
            job.candidates.filter(status="pending").delete()
            rows = [
                ExtractionCandidate(
                    owner=request.user, job=job, kind=item["kind"],
                    name=item["name"][:200], payload=item["payload"],
                    confidence=clamp(item["confidence"], 0.6), status="pending")
                for item in candidates
            ]
            ExtractionCandidate.objects.bulk_create(rows, batch_size=200)
            job.entity_count = summary["entity_count"]
            job.relation_count = summary["relation_count"]
            job.status = "done"
            job.error = ""
            job.save(update_fields=["entity_count", "relation_count", "status",
                                    "error", "updated_at"])
    except ValueError as exc:
        job.status = "failed"
        job.error = str(exc)[:2000]
        job.save(update_fields=["status", "error", "updated_at"])
        raise
    record_audit(request.user, "extraction.run", job.ontology_id, "job", job.id,
                 f"执行抽取任务 #{job.id}",
                 {"entity_count": job.entity_count,
                  "relation_count": job.relation_count,
                  "elapsed_ms": int((time.perf_counter() - started) * 1000)})
    return ok({**job_dict(job),
               "elapsed_ms": int((time.perf_counter() - started) * 1000)})


@endpoint(("GET",))
def extraction_candidates(request):
    """抽取候选列表（支持任务 / 状态 / 类型 / 关键字）。"""
    qs = scope_queryset(ExtractionCandidate.objects.all(), request.user
                        ).order_by("-confidence", "id")
    rows, total, page, size = list_queryset(
        request, qs, ["name"], "status",
        extra_filters={"job_id": ("job_id", int), "kind": ("kind", str)},
    )
    return ok(page_payload([candidate_dict(c) for c in rows], total, page, size))


def _candidate_type(ontology, payload):
    """候选自带的类型信息 → EntityType；无法识别时回落到本体默认类型。"""
    type_id = payload.get("entity_type_id")
    if type_id:
        etype = EntityType.objects.filter(pk=int(type_id)).first()
        if etype and etype.ontology_id == ontology.id:
            return etype
    code = (payload.get("entity_type_code") or payload.get("entity_type")
            or payload.get("type") or "")
    if code:
        etype = EntityType.objects.filter(ontology=ontology, code=str(code)).first()
        if etype:
            return etype
    etype = EntityType.objects.filter(ontology=ontology, enabled=True).order_by("id").first()
    if etype is None:
        raise ValueError("本体下没有启用的实体类型，无法写入实体")
    return etype


def _ensure_entity(ontology, name, payload, user):
    """按规范名复用已有实体，没有才新建（接受候选必须幂等）。"""
    etype = _candidate_type(ontology, payload)
    canonical = (services.normalize_name(name) or name)[:200]
    existing = Entity.objects.filter(
        ontology=ontology, status="active", canonical_name=canonical).first()
    if existing:
        return existing, False
    entity = Entity.objects.create(
        owner=user, ontology=ontology, entity_type=etype, name=name[:200],
        canonical_name=canonical,
        description=str(payload.get("evidence") or "")[:4000],
        attrs={"extracted": True}, confidence=clamp(payload.get("confidence", 0.6), 0.6),
        status="active", created_by=user,
    )
    return entity, True


def _ensure_relation_type(ontology, payload, user):
    """按 code 复用关系类型；不存在则用抽取模式名自动创建。"""
    code = str(payload.get("relation_code") or "related_to")[:80]
    rtype = RelationType.objects.filter(ontology=ontology, code=code).first()
    if rtype:
        return rtype
    name = str(payload.get("relation_name") or code)[:80]
    return RelationType.objects.create(
        owner=user, ontology=ontology, name=name, code=code,
        directed=True, weight=1.0, enabled=True,
    )


@endpoint()
def extraction_candidate_accept(request, pk):
    """接受候选：实体直接落库，关系落边（两端实体不存在时自动创建）。"""
    candidate = write_obj(ExtractionCandidate, pk, request.user, "抽取候选")
    if candidate.status != "pending":
        raise ValueError(f"候选已是 {candidate.status} 状态，不能重复处理")
    job = candidate.job
    ontology = job.ontology
    payload = candidate.payload or {}
    created_entities = 0
    created_relation = None
    with transaction.atomic():
        if candidate.kind == "entity":
            entity, created = _ensure_entity(ontology, candidate.name, payload,
                                             request.user)
            created_entities += 1 if created else 0
            candidate.payload = {**payload, "entity_id": entity.id,
                                 "created": created}
        elif candidate.kind == "relation":
            source_name = str(payload.get("source") or "").strip()
            target_name = str(payload.get("target") or "").strip()
            if not source_name or not target_name:
                raise ValueError("关系候选缺少 source / target")
            source, created_src = _ensure_entity(ontology, source_name, payload,
                                                 request.user)
            target, created_dst = _ensure_entity(ontology, target_name, payload,
                                                 request.user)
            created_entities += int(created_src) + int(created_dst)
            if source.id == target.id:
                raise ValueError("关系候选的两端解析为同一实体，已拒绝写入")
            rtype = _ensure_relation_type(ontology, payload, request.user)
            existing = Relation.objects.filter(
                relation_type=rtype, source_entity=source, target_entity=target,
                status="active").first()
            if existing:
                created_relation = existing
            else:
                created_relation = Relation.objects.create(
                    owner=request.user, ontology=ontology, relation_type=rtype,
                    source_entity=source, target_entity=target,
                    attrs={"evidence": str(payload.get("evidence") or "")[:2000]},
                    weight=1.0, confidence=clamp(candidate.confidence, 0.6),
                    source="extraction", status="active",
                )
            candidate.payload = {
                **payload,
                "source_entity_id": source.id,
                "target_entity_id": target.id,
                "relation_type_id": rtype.id,
                "relation_id": created_relation.id,
            }
        else:
            raise ValueError("未知的候选类型")
        candidate.status = "accepted"
        candidate.save(update_fields=["status", "payload", "updated_at"])
    services.invalidate_path_cache(ontology.id)
    record_audit(request.user, "extraction.accept", ontology.id, "candidate",
                 candidate.id, f"接受候选 {candidate.name}",
                 {"kind": candidate.kind, "created_entities": created_entities,
                  "relation_id": created_relation.id if created_relation else None})
    return ok({
        "id": candidate.id,
        "status": candidate.status,
        "kind": candidate.kind,
        "created_entities": created_entities,
        "relation_id": created_relation.id if created_relation else None,
        "payload": candidate.payload,
    })


@endpoint()
def extraction_candidate_reject(request, pk):
    """拒绝候选（只改状态，不落图谱）。"""
    candidate = write_obj(ExtractionCandidate, pk, request.user, "抽取候选")
    if candidate.status != "pending":
        raise ValueError(f"候选已是 {candidate.status} 状态，不能重复处理")
    candidate.status = "rejected"
    candidate.payload = {**(candidate.payload or {}),
                         "reject_reason": opt_str(request, "reason", "")[:500]}
    candidate.save(update_fields=["status", "payload", "updated_at"])
    record_audit(request.user, "extraction.reject", candidate.job.ontology_id,
                 "candidate", candidate.id, f"拒绝候选 {candidate.name}")
    return ok({"id": candidate.id, "status": candidate.status})


# ---------------------------------------------------------------------------
# 合并申请
# ---------------------------------------------------------------------------


@endpoint()
def merge_request_create(request):
    """创建合并申请（两端必须同本体、允许同一实体不同状态）。"""
    source = write_obj(Entity, int(req_num(request, "source_entity_id")),
                       request.user, "源实体")
    target = write_obj(Entity, int(req_num(request, "target_entity_id")),
                       request.user, "目标实体")
    if source.id == target.id:
        raise ValueError("不能把实体合并到自身")
    if source.ontology_id != target.ontology_id:
        raise ValueError("只能申请合并同一本体下的实体")
    if MergeRequest.objects.filter(source_entity=source, target_entity=target,
                                   status="pending").exists():
        raise ValueError("该合并申请已存在，请等待审批")
    merge_request = MergeRequest.objects.create(
        owner=request.user, ontology_id=source.ontology_id,
        source_entity=source, target_entity=target,
        reason=opt_str(request, "reason", "")[:2000], status="pending",
    )
    record_audit(request.user, "merge_request.create", source.ontology_id,
                 "merge_request", merge_request.id,
                 f"申请合并 {source.name} → {target.name}")
    merge_request = MergeRequest.objects.select_related(
        "source_entity", "target_entity").get(pk=merge_request.id)
    return ok(merge_request_dict(merge_request))


@endpoint(("GET",))
def merge_request_list(request):
    """合并申请列表（支持状态 / 本体 / 关键字）。"""
    qs = scope_queryset(
        MergeRequest.objects.select_related("source_entity", "target_entity"),
        request.user).order_by("-created_at")
    rows, total, page, size = list_queryset(
        request, qs, ["reason"], "status",
        extra_filters={"ontology_id": ("ontology_id", int)},
    )
    return ok(page_payload([merge_request_dict(m) for m in rows], total, page, size))


@endpoint(("GET",))
def merge_request_detail(request, pk):
    """合并申请详情（附合并预览与合并日志）。"""
    merge_request = read_obj(MergeRequest, pk, request.user, "合并申请")
    data = merge_request_dict(merge_request)
    try:
        data["preview"] = services.merge_preview(merge_request.source_entity,
                                                 merge_request.target_entity)
    except ValueError as exc:
        data["preview"] = {"error": str(exc)}
    data["logs"] = [merge_log_dict(log) for log in merge_request.logs.all()[:10]]
    return ok(data)


@endpoint()
def merge_request_approve(request, pk):
    """通过合并申请：事务内执行合并并写 MergeLog / 审计。"""
    with transaction.atomic():
        try:
            merge_request = MergeRequest.objects.select_for_update().get(pk=pk)
        except MergeRequest.DoesNotExist:
            raise ValueError("合并申请不存在")
        if not can_write(request.user, merge_request):
            raise ValueError("无权审批该合并申请")
        if merge_request.status != "pending":
            raise ValueError(f"当前状态 {merge_request.status} 不可审批")
        source = Entity.objects.select_for_update().filter(
            pk=merge_request.source_entity_id).first()
        target = Entity.objects.select_for_update().filter(
            pk=merge_request.target_entity_id).first()
        if source is None or target is None:
            raise ValueError("实体不存在或已删除")
        if not can_write(request.user, source) or not can_write(request.user, target):
            raise ValueError("无权操作合并涉及的实体")
        result = services.merge_entities(
            source, target, request.user, reason=merge_request.reason,
            request_obj=merge_request)
        merge_request.status = "approved"
        merge_request.approver = request.user
        merge_request.decided_at = timezone.now()
        merge_request.save(update_fields=["status", "approver", "decided_at",
                                          "updated_at"])
    return ok({**result, "request_id": merge_request.id,
               "status": merge_request.status})


@endpoint()
def merge_request_reject(request, pk):
    """拒绝合并申请（必须给理由，便于申请人修正）。"""
    with transaction.atomic():
        try:
            merge_request = MergeRequest.objects.select_for_update().get(pk=pk)
        except MergeRequest.DoesNotExist:
            raise ValueError("合并申请不存在")
        if not can_write(request.user, merge_request):
            raise ValueError("无权审批该合并申请")
        if merge_request.status != "pending":
            raise ValueError(f"当前状态 {merge_request.status} 不可审批")
        reason = req_str(request, "reason", max_len=1000).strip()
        merge_request.status = "rejected"
        merge_request.approver = request.user
        merge_request.decided_at = timezone.now()
        merge_request.reason = (merge_request.reason + "\n[驳回] " + reason)[:2000]
        merge_request.save(update_fields=["status", "approver", "decided_at",
                                          "reason", "updated_at"])
    record_audit(request.user, "merge_request.reject", merge_request.ontology_id,
                 "merge_request", merge_request.id,
                 f"驳回合并申请 #{merge_request.id}", {"reason": reason})
    return ok({"id": merge_request.id, "status": merge_request.status,
               "reason": reason})


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------


def _snapshot_stats(ontology, user):
    """按数据范围构建快照统计（实体 / 关系 / 类型名）。"""
    graph = _load_graph(user, ontology.id)
    type_names = {t.id: t.name for t in EntityType.objects.filter(ontology=ontology)}
    return services.snapshot_stats(list(graph["entity_map"].values()),
                                   graph["relations"], type_names)


def _create_snapshot(ontology, user, name):
    """生成并落库一份快照（名称与备注由调用方决定）。"""
    stats = _snapshot_stats(ontology, user)
    snapshot = GraphSnapshot.objects.create(
        owner=user, ontology=ontology, name=name[:120],
        node_count=stats["node_count"], edge_count=stats["edge_count"],
        stats=stats, note=opt_str_from_stats(stats, name),
    )
    record_audit(user, "snapshot.create", ontology.id, "snapshot", snapshot.id,
                 f"生成快照 {snapshot.name}",
                 {"node_count": snapshot.node_count,
                  "edge_count": snapshot.edge_count})
    return snapshot


def opt_str_from_stats(stats, name):
    """快照备注：记录生成时使用的口径，便于日后对比时解释差异。"""
    return f"节点 {stats.get('node_count', 0)} / 边 {stats.get('edge_count', 0)} / {name}"


@endpoint()
def snapshot_create(request):
    """创建图谱快照（名称必填，统计按当前数据范围计算）。"""
    ontology = read_obj(Ontology, int(req_num(request, "ontology_id")),
                        request.user, "本体")
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("快照名称不能为空")
    snapshot = _create_snapshot(ontology, request.user, name)
    return ok(snapshot_dict(snapshot))


@endpoint()
def snapshot_generate(request):
    """自动生成当日快照（名称按时间生成，可指定本体）。"""
    ontology = read_obj(Ontology, int(req_num(request, "ontology_id")),
                        request.user, "本体")
    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    name = opt_str(request, "name", "").strip() or f"{ontology.name} {stamp}"
    snapshot = _create_snapshot(ontology, request.user, name)
    return ok(snapshot_dict(snapshot))


@endpoint(("GET",))
def snapshot_list(request):
    """快照列表（支持本体 / 关键字，按生成时间倒序）。"""
    qs = scope_queryset(GraphSnapshot.objects.all(), request.user
                        ).order_by("-created_at")
    rows, total, page, size = list_queryset(
        request, qs, ["name", "note"], status_field=None,
        extra_filters={"ontology_id": ("ontology_id", int)},
    )
    return ok(page_payload([snapshot_dict(s) for s in rows], total, page, size))


@endpoint(("GET",))
def snapshot_detail(request, pk):
    """快照详情（完整统计 JSON）。"""
    snapshot = read_obj(GraphSnapshot, pk, request.user, "快照")
    data = snapshot_dict(snapshot)
    data["ontology_name"] = snapshot.ontology.name
    return ok(data)


@endpoint()
def snapshot_delete(request, pk):
    """删除快照。"""
    snapshot = write_obj(GraphSnapshot, pk, request.user, "快照")
    snapshot_id = snapshot.id
    snapshot.delete()
    return ok({"id": snapshot_id, "deleted": True})


@endpoint(("GET",))
def snapshot_diff(request):
    """对比两份快照（规模增量 / 类型增减 / 结构变化）。"""
    a_id = int_arg(request, "a") or int_arg(request, "base_id")
    b_id = int_arg(request, "b") or int_arg(request, "target_id")
    if not a_id or not b_id:
        raise ValueError("缺少必填参数: a / b")
    if a_id == b_id:
        raise ValueError("对比的两份快照不能相同")
    base = read_obj(GraphSnapshot, a_id, request.user, "基准快照")
    target = read_obj(GraphSnapshot, b_id, request.user, "目标快照")
    result = services.diff_stats(base.stats, target.stats)
    result.update({
        "base": {"id": base.id, "name": base.name,
                 "created_at": base.created_at.isoformat()},
        "target": {"id": target.id, "name": target.name,
                   "created_at": target.created_at.isoformat()},
        "same_ontology": base.ontology_id == target.ontology_id,
    })
    return ok(result)


KNOWLEDGE_FAMILY_COUNT = 5 + 7 + 5 + 6
