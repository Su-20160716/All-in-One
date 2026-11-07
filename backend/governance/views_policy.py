# -*- coding: utf-8 -*-
"""制度策略接口：CRUD + 评审流转 + 版本快照 / 对比 / 回滚。

状态机（服务层校验，不允许跳级）：

    draft ──提交评审──▶ reviewing ──批准──▶ approved ──发布──▶ published
      ▲                    │                  │                 │
      └─────────驳回(回草稿)┘                  └─────停用─────────▶ retired

审批与发布允许 owner 与管理员（合规负责人常常不是录入人），其余写操作
严格按 owner 收口。每次批准/发布都会固化一个 PolicyVersion 快照，
回滚则是「把历史快照重新发布为新版本」，而不是修改历史记录。
"""
from django.db import transaction
from django.utils import timezone

from devtools.common import endpoint, ok, p

from governance import services
from governance.models import POLICY_KINDS, POLICY_STATUS, Policy, PolicyVersion
from governance.views_common import (
    apply_search,
    filter_choice,
    get_policy,
    paginate,
    param_choice,
    param_date,
    param_int,
    param_str,
    param_text,
    scoped,
)

POLICY_SEARCH_FIELDS = ("code", "name", "description", "owner_name", "scope")


@endpoint(("GET",))
def policy_list(request):
    """策略列表：q/status/kind + 评审日区间过滤。"""
    qs = scoped(Policy, request.user)
    qs = apply_search(qs, request, POLICY_SEARCH_FIELDS)
    qs = filter_choice(qs, request, "kind", POLICY_KINDS)
    due_before = param_date(request, "due_before")
    if due_before:
        qs = qs.filter(next_review_on__isnull=False, next_review_on__lte=due_before)
    return paginate(qs.order_by("-created_at"), request)


@endpoint()
def policy_create(request):
    """新建策略（编码在当前用户下唯一）。"""
    code = param_str(request, "code", required=True, max_len=60)
    name = param_str(request, "name", required=True, max_len=200)
    if Policy.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("该策略编码已存在")
    policy = Policy.objects.create(
        owner=request.user,
        code=code,
        name=name,
        kind=param_choice(request, "kind", POLICY_KINDS, default="security"),
        description=param_text(request, "description"),
        content=param_text(request, "content"),
        owner_name=param_str(request, "owner_name", default=getattr(request.user, "username", ""),
                             max_len=80),
        scope=param_str(request, "scope", max_len=200),
        next_review_on=param_date(request, "next_review_on"),
    )
    return ok(policy.to_dict())


@endpoint(("GET",))
def policy_detail(request, pk):
    """策略详情（含正文与最近版本号）。"""
    policy = get_policy(pk, request.user)
    data = policy.to_dict()
    data["content"] = policy.content
    latest = policy.versions.order_by("-created_at").first()
    data["latest_version"] = latest.to_dict() if latest else None
    data["version_count"] = policy.versions.count()
    return ok(data)


@endpoint()
def policy_update(request, pk):
    """更新策略内容（仅草稿/评审中的正文可改；已发布必须走版本回滚或重新发布）。"""
    policy = get_policy(pk, request.user, write=True)
    if policy.status == "published" and p(request, "content") not in (None, ""):
        raise ValueError("已发布策略的正文不可直接修改，请用版本回滚或新建版本")
    policy.code = param_str(request, "code", default=policy.code, max_len=60)
    policy.name = param_str(request, "name", default=policy.name, max_len=200)
    policy.kind = param_choice(request, "kind", POLICY_KINDS, default=policy.kind)
    policy.description = param_text(request, "description", default=policy.description)
    policy.content = param_text(request, "content", default=policy.content)
    policy.owner_name = param_str(request, "owner_name", default=policy.owner_name, max_len=80)
    policy.scope = param_str(request, "scope", default=policy.scope, max_len=200)
    policy.next_review_on = param_date(request, "next_review_on") or policy.next_review_on
    policy.save()
    return ok(policy.to_dict())


@endpoint()
def policy_delete(request, pk):
    """删除策略；已发布策略需 force=1（避免误删已生效制度的审计链路）。"""
    policy = get_policy(pk, request.user, write=True)
    force = str(p(request, "force", "")).lower() in ("1", "true", "yes", "on")
    if policy.status == "published" and not force:
        raise ValueError("已发布策略确认删除请传 force=1")
    with transaction.atomic():
        policy.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def policy_submit_review(request, pk):
    """提交评审：draft → reviewing。"""
    policy = get_policy(pk, request.user, write=True)
    services.require_status(policy, ("draft",), "提交评审")
    policy.status = "reviewing"
    policy.save(update_fields=["status", "updated_at"])
    return ok(policy.to_dict())


@endpoint()
def policy_approve(request, pk):
    """批准策略：reviewing → approved，并固化版本快照。"""
    policy = get_policy(pk, request.user, write=True)
    services.require_status(policy, ("reviewing",), "批准")
    approver = param_str(request, "approver_name",
                         default=getattr(request.user, "display_name", "") or
                         getattr(request.user, "username", ""), max_len=80)
    next_review = param_date(request, "next_review_on")
    with transaction.atomic():
        policy.status = "approved"
        policy.approved_by_name = approver
        if next_review:
            policy.next_review_on = next_review
        policy.save(update_fields=["status", "approved_by_name", "next_review_on", "updated_at"])
        version = services.policy_publish_version(
            policy, request.user, change_note=param_text(request, "change_note"))
        policy.current_version = version.version
        policy.save(update_fields=["current_version", "updated_at"])
    return ok({"policy": policy.to_dict(), "version": version.to_dict()})


@endpoint()
def policy_publish(request, pk):
    """发布策略：approved → published；已发布时幂等返回当前版本。"""
    policy = get_policy(pk, request.user, write=True)
    if policy.status == "published":
        latest = policy.versions.filter(version=policy.current_version).first() \
            or policy.versions.order_by("-created_at").first()
        return ok({"policy": policy.to_dict(),
                   "version": latest.to_dict() if latest else None,
                   "already_published": True})
    services.require_status(policy, ("approved",), "发布")
    with transaction.atomic():
        policy.status = "published"
        policy.published_at = timezone.now()
        policy.save(update_fields=["status", "published_at", "updated_at"])
        version = policy.versions.filter(version=policy.current_version).first()
        if version is None:
            version = services.policy_publish_version(
                policy, request.user, change_note=param_text(request, "change_note"))
            policy.current_version = version.version
            policy.save(update_fields=["current_version", "updated_at"])
        if version.published_at is None:
            version.published_at = policy.published_at
            version.save(update_fields=["published_at", "updated_at"])
    return ok({"policy": policy.to_dict(), "version": version.to_dict()})


@endpoint()
def policy_retire(request, pk):
    """停用策略：published/approved → retired；已停用时幂等。"""
    policy = get_policy(pk, request.user, write=True)
    if policy.status == "retired":
        return ok({"policy": policy.to_dict(), "already_retired": True})
    services.require_status(policy, ("approved", "published"), "停用")
    policy.status = "retired"
    policy.save(update_fields=["status", "updated_at"])
    return ok(policy.to_dict())


@endpoint(("GET",))
def policy_versions(request, pk):
    """策略版本列表（按创建时间倒序）。"""
    policy = get_policy(pk, request.user)
    qs = policy.versions.all().order_by("-created_at")
    return paginate(qs, request)


@endpoint(("GET",))
def policy_version_compare(request, pk):
    """版本对比：left/right 传版本号（缺省对比最近两个版本）。"""
    policy = get_policy(pk, request.user)
    versions = list(policy.versions.order_by("-created_at")[:2])
    left_version = param_str(request, "left", max_len=40)
    right_version = param_str(request, "right", max_len=40)
    if left_version or right_version:
        if not (left_version and right_version):
            raise ValueError("版本对比需同时提供 left 与 right")
        left = policy.versions.filter(version=left_version).first()
        right = policy.versions.filter(version=right_version).first()
        if left is None or right is None:
            raise ValueError("指定版本不存在")
    else:
        if len(versions) < 2:
            raise ValueError("至少需要两个版本才能对比")
        left, right = versions[1], versions[0]
    return ok(services.compare_versions(policy, left, right))


@endpoint()
def policy_rollback(request, pk):
    """回滚：以历史版本内容生成新版本并重新发布（历史记录不可变）。"""
    policy = get_policy(pk, request.user, write=True)
    version_no = param_str(request, "version", required=True, max_len=40)
    target = policy.versions.filter(version=version_no).first()
    if target is None:
        raise ValueError("指定版本不存在")
    if target.version == policy.current_version and policy.status == "published":
        return ok({"policy": policy.to_dict(), "version": target.to_dict(),
                   "changed": False, "reason": "已是当前版本"})
    with transaction.atomic():
        new_no = f"{target.version}-rb{policy.versions.count() + 1}"
        snapshot = PolicyVersion.objects.create(
            owner=request.user,
            policy=policy,
            version=new_no,
            content_snapshot=target.content_snapshot,
            change_note=param_text(request, "change_note",
                                   default=f"回滚至 {target.version}"),
            approver_name=getattr(request.user, "display_name", "")
            or getattr(request.user, "username", ""),
            published_at=timezone.now(),
        )
        policy.content = target.content_snapshot
        policy.current_version = new_no
        if policy.status in ("draft", "reviewing", "approved"):
            # 只有已经生效过的策略回滚后才保持 published；草稿回滚仍留在草稿态，
            # 否则一次误回滚就会让未批准的文本直接对外生效。
            policy.status = "published" if policy.published_at else "draft"
        policy.save(update_fields=["content", "current_version", "status", "updated_at"])
    return ok({"policy": policy.to_dict(), "version": snapshot.to_dict(), "changed": True})
