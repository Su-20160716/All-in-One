# -*- coding: utf-8 -*-
"""证据接口：CRUD + 哈希校验 + 过期列表。

证据只登记「元数据 + 哈希」，不接收文件上传：
- 文件本体属于 files 应用，重复存储会让敏感证据在治理库里留下副本；
- 哈希校验的价值在于「证明调阅到的材料与登记时一致」，与文件存在哪里无关。

校验接口允许两种输入：`content`（原文，服务端现算哈希）或 `hash_value`
（外部给出的摘要）。都不传时只做格式合法性 + 过期检查，结论写回证据行，
因此重复调用不会产生任何新记录（幂等）。
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from devtools.common import endpoint, ok, p

from governance import services
from governance.models import EVIDENCE_KINDS, EVIDENCE_TARGETS, Evidence
from governance.views_common import (
    apply_search,
    filter_choice,
    filter_int,
    get_evidence,
    paginate,
    param_choice,
    param_datetime,
    param_date,
    param_int,
    param_str,
    param_text,
    scoped,
)

EVIDENCE_SEARCH_FIELDS = ("name", "reference", "hash_value", "collected_by_name")


def _validate_hash(value):
    """登记哈希时先做格式校验，避免把拼写错误存进库里直到校验才发现。"""
    if not value:
        return ""
    algorithm, digest = services.split_hash(value)
    if not digest:
        raise ValueError("哈希值不能为空")
    if not all(ch in "0123456789abcdef" for ch in digest):
        raise ValueError("哈希值需为十六进制摘要")
    return f"{algorithm}:{digest}"


@endpoint(("GET",))
def evidence_list(request):
    """证据列表：可按对象类型/对象 ID/是否过期筛选。"""
    qs = scoped(Evidence, request.user)
    qs = apply_search(qs, request, EVIDENCE_SEARCH_FIELDS, status_field=None)
    qs = filter_choice(qs, request, "target_kind", EVIDENCE_TARGETS)
    qs = filter_choice(qs, request, "kind", EVIDENCE_KINDS)
    qs = filter_int(qs, request, "target_id", "target_id")
    expired = param_str(request, "expired", max_len=8)
    if expired in ("1", "true", "yes", "on"):
        qs = qs.filter(expires_on__lt=services.today())
    elif expired in ("0", "false", "no", "off"):
        qs = qs.filter(Q(expires_on__gte=services.today()) | Q(expires_on__isnull=True))
    return paginate(qs.order_by("-created_at"), request)


@endpoint()
def evidence_create(request):
    """登记证据（哈希值做格式校验，采集时间缺省为当前）。"""
    target_kind = param_choice(request, "target_kind", EVIDENCE_TARGETS, default="control")
    target_id = param_int(request, "target_id", required=True, minimum=1)
    kind = param_choice(request, "kind", EVIDENCE_KINDS, default="link")
    hash_value = _validate_hash(param_str(request, "hash_value", max_len=160))
    if kind == "hash" and not hash_value:
        raise ValueError("证据类型为 hash 时必须提供 hash_value")
    evidence = Evidence.objects.create(
        owner=request.user,
        target_kind=target_kind,
        target_id=target_id,
        name=param_str(request, "name", required=True, max_len=200),
        kind=kind,
        reference=param_str(request, "reference", max_len=500),
        hash_value=hash_value,
        collected_by_name=param_str(request, "collected_by_name",
                                    default=getattr(request.user, "nickname", "")
                                    or getattr(request.user, "username", ""), max_len=80),
        collected_at=param_datetime(request, "collected_at", default=timezone.now()),
        expires_on=param_date(request, "expires_on"),
    )
    return ok(evidence.to_dict())


@endpoint(("GET",))
def evidence_detail(request, pk):
    """证据详情（含最近一次校验结论）。"""
    evidence = get_evidence(pk, request.user)
    data = evidence.to_dict()
    data["algorithm"] = services.split_hash(evidence.hash_value)[0] if evidence.hash_value else ""
    return ok(data)


@endpoint()
def evidence_update(request, pk):
    """更新证据元数据（哈希变更会清空上次校验结论，避免旧结论误导）。"""
    evidence = get_evidence(pk, request.user, write=True)
    new_hash = _validate_hash(param_str(request, "hash_value", max_len=160))
    if new_hash and new_hash != evidence.hash_value:
        evidence.last_check_ok = None
        evidence.last_check_note = ""
        evidence.last_checked_at = None
    evidence.hash_value = new_hash or evidence.hash_value
    evidence.name = param_str(request, "name", default=evidence.name, max_len=200)
    evidence.reference = param_str(request, "reference", default=evidence.reference, max_len=500)
    evidence.kind = param_choice(request, "kind", EVIDENCE_KINDS, default=evidence.kind)
    evidence.target_kind = param_choice(request, "target_kind", EVIDENCE_TARGETS,
                                        default=evidence.target_kind)
    target_id = param_int(request, "target_id", default=None, minimum=1)
    if target_id:
        evidence.target_id = target_id
    evidence.collected_by_name = param_str(request, "collected_by_name",
                                           default=evidence.collected_by_name, max_len=80)
    evidence.collected_at = param_datetime(request, "collected_at",
                                           default=evidence.collected_at)
    evidence.expires_on = param_date(request, "expires_on") or evidence.expires_on
    evidence.save()
    return ok(evidence.to_dict())


@endpoint()
def evidence_delete(request, pk):
    """删除证据（仅删除元数据登记，不影响外部文件）。"""
    evidence = get_evidence(pk, request.user, write=True)
    with transaction.atomic():
        evidence.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def evidence_verify(request, pk):
    """校验证据：哈希一致性 + 过期检查，结论写回证据行（幂等）。"""
    evidence = get_evidence(pk, request.user)
    content = p(request, "content")
    if content is not None and not isinstance(content, (str, bytes)):
        raise ValueError("参数 content 必须是字符串")
    provided = param_str(request, "hash_value", max_len=160)
    if provided:
        provided = _validate_hash(provided)
    result = services.verify_evidence(evidence, provided_hash=provided, content=content)
    return ok(result)


@endpoint(("GET",))
def evidence_expired(request):
    """过期 / 即将到期证据列表（days 默认 0 只含已过期）。"""
    days = param_int(request, "days", default=0, minimum=0, maximum=3650)
    only_expired = param_str(request, "only_expired", max_len=8) not in ("0", "false", "no", "off")
    data = services.expiring_evidences(request.user, days=days, only_expired=only_expired)
    return ok(data)
