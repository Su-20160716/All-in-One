# -*- coding: utf-8 -*-
"""officesuite · 知识内容面接口：faq(7) policy(8) template(7) wiki(12) minutes(12)
formcollect(9) announcement(8) poll(9) helpdesk(11) = 83 个（含 minutes_to_todo / 行动项落库与转日程）。

FAQ/制度/模板/wiki 围绕知识沉淀；表单/公告/投票/工单围绕信息流转。
"""
from datetime import datetime, timedelta
import html
import re
from urllib.parse import quote

from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.http import HttpResponse
from django.utils import timezone

from core.scoping import is_visible, scope_queryset, visible_user_ids
from core.validators import parse_bool

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req, req_num, req_str)
from officesuite.common import (can_write_obj, flow_event, get_obj, obj_dict,
                                parse_day, parse_dt)
from officesuite.models import (CollectForm, DeptAnnouncement, FaqEntry,
                                FormEntry, HelpTicket, MeetingMinutes,
                                PolicyDoc, DocTemplate, Poll, PollVote,
                                SuiteEvent, WikiPage)

# =====================================================================
# faq FAQ（7）
# =====================================================================


@endpoint()
def faq_create(request):
    """新建 FAQ。"""
    f = FaqEntry.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        answer=opt_str(request, "answer"),
        category=opt_str(request, "category", "通用"),
        status="published",
        data={"tags": p(request, "tags") or [], "events": []})
    return ok({"id": f.id, "title": f.title, "category": f.category})


@endpoint(("GET",))
def faq_list(request):
    """FAQ 列表（分类过滤 + 按票数排序）。"""
    qs = scope_queryset(FaqEntry.objects.all(), request.user).order_by("-votes", "-created_at")
    category = opt_str(request, "category")
    if category:
        qs = qs.filter(category=category)
    kw = opt_str(request, "keyword")
    if kw:
        qs = qs.filter(Q(title__icontains=kw) | Q(answer__icontains=kw))
    return ok({"items": [obj_dict(o, extra=("answer", "category", "votes")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def faq_update(request, pk):
    """编辑 FAQ。"""
    f = get_obj(FaqEntry, pk, request.user, write=True)
    if p(request, "title") is not None:
        f.title = req_str(request, "title")[:200]
    if p(request, "answer") is not None:
        f.answer = opt_str(request, "answer")
    if p(request, "category") is not None:
        f.category = opt_str(request, "category", f.category)
    f.save()
    return ok({"id": f.id, "title": f.title})


@endpoint()
def faq_delete(request, pk):
    """删除 FAQ。"""
    f = get_obj(FaqEntry, pk, request.user, write=True)
    f.delete()
    return ok({"deleted": pk})


@endpoint()
def faq_vote(request, pk):
    """标记「有用」（F 原子自增）。"""
    f = get_obj(FaqEntry, pk, request.user)
    FaqEntry.objects.filter(pk=f.pk).update(votes=F("votes") + 1)
    f.refresh_from_db()
    return ok({"id": f.id, "votes": f.votes})


@endpoint(("GET",))
def faq_search(request):
    """FAQ 搜索：标题/答案/标签全文（icontains）。"""
    kw = req_str(request, "keyword")
    if len(kw) < 1:
        raise ValueError("keyword 不能为空")
    qs = scope_queryset(FaqEntry.objects.all(), request.user).filter(
        Q(title__icontains=kw) | Q(answer__icontains=kw) | Q(data__tags__icontains=kw))
    return ok({"keyword": kw,
               "items": [{"id": o.id, "title": o.title, "category": o.category,
                          "votes": o.votes} for o in qs[:50]],
               "count": qs.count()})


@endpoint(("GET",))
def faq_stats(request):
    """FAQ 统计：分类分布与高票 TOP5（#43：所有聚合前置 scope_queryset）。"""
    qs = scope_queryset(FaqEntry.objects.all(), request.user)
    by_cat = qs.values("category").annotate(c=Count("id")).order_by("-c")
    top = qs.order_by("-votes").values("title", "votes")[:5]
    return ok({"by_category": [{"category": b["category"], "count": b["c"]} for b in by_cat],
               "top_voted": list(top), "total": qs.count()})


# =====================================================================
# policy 制度文档（7）
# =====================================================================


@endpoint()
def policy_create(request):
    """发布制度文档。"""
    d = PolicyDoc.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        content=opt_str(request, "content"),
        version=opt_str(request, "version", "v1.0"),
        effective_date=parse_day(opt_str(request, "effective_date"), "effective_date"),
        status="effective", data={"events": []})
    flow_event(d, "publish", request.user)
    d.save()
    return ok({"id": d.id, "title": d.title, "version": d.version})


@endpoint(("GET",))
def policy_list(request):
    """制度列表（关键词搜索）。"""
    qs = scope_queryset(PolicyDoc.objects.all(), request.user).order_by("-created_at")
    kw = opt_str(request, "keyword")
    if kw:
        qs = qs.filter(Q(title__icontains=kw) | Q(content__icontains=kw))
    return ok({"items": [{"id": d.id, "title": d.title, "version": d.version,
                          "effective_date": str(d.effective_date or ""),
                          "acked_count": len(d.acked_by or []),
                          "owner": d.owner.username} for d in qs[:100]],
               "count": qs.count()})


@endpoint()
def policy_detail(request, pk):
    """制度详情（正文 + 已阅数）。"""
    d = get_obj(PolicyDoc, pk, request.user)
    out = obj_dict(d)
    out["content"] = d.content
    out["version"] = d.version
    out["effective_date"] = str(d.effective_date or "")
    out["acked_count"] = len(d.acked_by or [])
    out["acked_by_me"] = request.user.username in (d.acked_by or [])
    return ok(out)


@endpoint()
def policy_update(request, pk):
    """修订制度（版本自动 +0.1 可覆盖）。"""
    d = get_obj(PolicyDoc, pk, request.user, write=True)
    if p(request, "title") is not None:
        d.title = req_str(request, "title")[:200]
    if p(request, "content") is not None:
        d.content = opt_str(request, "content")
        if opt_bool(request, "auto_bump", True):
            try:
                major, minor = d.version.lstrip("vV").split(".")
                d.version = f"v{major}.{int(minor) + 1}"
            except ValueError:
                d.version = "v1.1"
    if p(request, "effective_date") is not None:
        d.effective_date = parse_day(opt_str(request, "effective_date"), "effective_date")
    flow_event(d, "revise", request.user, d.version)
    d.save()
    return ok({"id": d.id, "version": d.version})


@endpoint()
def policy_ack(request, pk):
    """确认已阅（幂等）。"""
    d = get_obj(PolicyDoc, pk, request.user)
    acked = list(d.acked_by or [])
    if request.user.username not in acked:
        acked.append(request.user.username)
        d.acked_by = acked
        d.save(update_fields=["acked_by", "updated_at"])
    return ok({"id": d.id, "acked_count": len(acked), "acked_by_me": True})


@endpoint(("GET",))
def policy_ack_list(request, pk):
    """制度已阅名单与未阅提醒（可见范围）。"""
    d = get_obj(PolicyDoc, pk, request.user)
    from accounts.models import User
    acked = d.acked_by or []
    visible_names = list(User.objects.filter(
        id__in=visible_user_ids(request.user) or {request.user.id}
    ).values_list("username", flat=True)) if request.user.is_authenticated else []
    unread = [n for n in visible_names if n not in acked]
    return ok({"title": d.title, "acked": acked, "unread": unread[:50],
               "ack_rate": round(len([n for n in visible_names if n in acked]) / len(visible_names) * 100, 1)
               if visible_names else 0})


@endpoint()
def policy_remind(request, pk):
    """S26-370 制度催办：给可见且未确认的用户发站内提醒，返回待催人数。"""
    d = get_obj(PolicyDoc, pk, request.user, write=True)
    from accounts.models import User
    from core.notify import dispatch

    acked = set(d.acked_by or [])
    ids = visible_user_ids(request.user)
    users = User.objects.filter(is_active=True)
    if ids is not None:
        users = users.filter(id__in=ids)
    targets = [u for u in users.order_by("id")[:500] if u.username not in acked]
    sent = 0
    for u in targets:
        n = dispatch(u, f"制度待阅读：{d.title}",
                     f"请阅读并确认《{d.title}》（{d.version}）。",
                     category="system", level="info", link="/officesuite/policy")
        if n is not None:
            sent += 1
    flow_event(d, "remind", request.user, f"催办 {len(targets)} 人")
    d.save(update_fields=["data", "updated_at"])
    return ok({"id": d.id, "title": d.title, "version": d.version,
               "pending": len(targets), "sent": sent,
               "unread": [u.username for u in targets[:50]]})


@endpoint()
def policy_delete(request, pk):
    """删除制度文档。"""
    d = get_obj(PolicyDoc, pk, request.user, write=True)
    d.delete()
    return ok({"deleted": pk})


# =====================================================================
# template 文档模板（7）
# =====================================================================


@endpoint()
def template_create(request):
    """新建文档模板（正文可含 {{变量}} 占位）。"""
    t = DocTemplate.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        content=opt_str(request, "content"),
        category=opt_str(request, "category", "通用"),
        status="ready", data={"events": []})
    return ok({"id": t.id, "title": t.title, "category": t.category})


@endpoint(("GET",))
def template_list(request):
    """模板列表（分类过滤）。"""
    qs = scope_queryset(DocTemplate.objects.all(), request.user).order_by("-created_at")
    category = opt_str(request, "category")
    if category:
        qs = qs.filter(category=category)
    return ok({"items": [obj_dict(o, extra=("category",)) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def template_detail(request, pk):
    """模板详情（正文）。"""
    t = get_obj(DocTemplate, pk, request.user)
    out = obj_dict(t, extra=("category",))
    out["content"] = t.content
    return ok(out)


@endpoint()
def template_update(request, pk):
    """编辑模板。"""
    t = get_obj(DocTemplate, pk, request.user, write=True)
    if p(request, "title") is not None:
        t.title = req_str(request, "title")[:200]
    if p(request, "content") is not None:
        t.content = opt_str(request, "content")
    if p(request, "category") is not None:
        t.category = opt_str(request, "category", t.category)
    t.save()
    return ok({"id": t.id, "title": t.title})


@endpoint()
def template_delete(request, pk):
    """删除模板。"""
    t = get_obj(DocTemplate, pk, request.user, write=True)
    t.delete()
    return ok({"deleted": pk})


@endpoint()
def template_render(request, pk):
    """渲染模板：vars 键值对替换 {{var}}，缺失占位保留并提示。"""
    t = get_obj(DocTemplate, pk, request.user)
    vars_ = p(request, "vars") or {}
    if not isinstance(vars_, dict):
        raise ValueError("vars 需为键值对象")
    import re

    content = t.content or ""
    missing = sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", content)) - set(vars_))
    for k, v in vars_.items():
        content = re.sub(r"\{\{\s*" + re.escape(str(k)) + r"\s*\}\}", str(v), content)
    return ok({"title": t.title, "rendered": content,
               "missing_placeholders": missing,
               "complete": not missing})


@endpoint(("GET",))
def template_categories(request):
    """模板分类汇总。"""
    rows = DocTemplate.objects.values("category").annotate(c=Count("id")).order_by("-c")
    return ok({"categories": [{"category": r["category"], "count": r["c"]} for r in rows]})


# =====================================================================
# wiki 知识库（9）
# =====================================================================


@endpoint()
def wiki_create(request):
    """新建 wiki 页面（可指定父页）。"""
    parent = None
    if p(request, "parent_id") is not None:
        parent = get_obj(WikiPage, int(req_num(request, "parent_id", minimum=1)), request.user)
    w = WikiPage.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        parent=parent,
        content=opt_str(request, "content"),
        order=int(req_num(request, "order", minimum=0, default=0)),
        revisions=[{"v": 1, "by": request.user.username, "at": timezone.now().isoformat(),
                    "note": "初稿"}])
    return ok({"id": w.id, "title": w.title, "parent": parent.id if parent else None})


@endpoint(("GET",))
def wiki_list(request):
    """wiki 列表（顶层页或某父页的子页）。"""
    qs = scope_queryset(WikiPage.objects.all(), request.user)
    parent_id = opt_num(request, "parent_id")
    if parent_id is None and not opt_bool(request, "include_children"):
        qs = qs.filter(parent__isnull=True)
    elif parent_id is not None:
        qs = qs.filter(parent_id=parent_id)
    qs = qs.order_by("order", "-updated_at")
    return ok({"items": [{"id": w.id, "title": w.title, "parent": w.parent_id,
                          "order": w.order, "updated_at": w.updated_at.isoformat(),
                          "like_count": len(w.likes or []),
                          "star_count": len(w.stars or []),
                          "children": w.children.count()} for w in qs[:200]],
               "count": qs.count()})


@endpoint()
def wiki_detail(request, pk):
    """wiki 详情（正文 + 版本号）。"""
    w = get_obj(WikiPage, pk, request.user)
    out = obj_dict(o=w, owner_name=w.owner.username) if False else {
        "id": w.id, "title": w.title, "parent": w.parent_id, "content": w.content,
        "order": w.order, "revisions": (w.revisions or [])[-20:],
        "version": len(w.revisions or []),
        "owner": w.owner.username,
        "created_at": w.created_at.isoformat(), "updated_at": w.updated_at.isoformat(),
    }
    out["children"] = [{"id": c.id, "title": c.title} for c in w.children.all()]
    likes = list(w.likes or [])
    stars = list(w.stars or [])
    out["like_count"] = len(likes)
    out["star_count"] = len(stars)
    out["liked"] = request.user.username in likes
    out["starred"] = request.user.username in stars
    return ok(out)


@endpoint()
def wiki_update(request, pk):
    """编辑 wiki（自动记修订版本；#67 事务内行锁，版本号在锁内生成）。"""
    with transaction.atomic():
        try:
            w = WikiPage.objects.select_for_update().get(pk=pk)
        except WikiPage.DoesNotExist:
            raise ValueError("对象不存在")
        if not is_visible(w, request.user):
            raise ValueError("无权访问该对象")
        if not can_write_obj(request.user, w):
            raise ValueError("无权修改该对象")
        changed = False
        if p(request, "title") is not None:
            w.title = req_str(request, "title")[:200]
            changed = True
        if p(request, "content") is not None:
            w.content = opt_str(request, "content")
            changed = True
        if p(request, "order") is not None:
            w.order = int(req_num(request, "order", minimum=0))
            changed = True
        if changed:
            revs = list(w.revisions or [])
            revs.append({"v": len(revs) + 1, "by": request.user.username,
                         "at": timezone.now().isoformat(),
                         "note": opt_str(request, "note", "更新")})
            w.revisions = revs
        w.save()
    return ok({"id": w.id, "version": len(w.revisions or [])})


@endpoint()
def wiki_delete(request, pk):
    """删除 wiki 页（连带子页）。"""
    w = get_obj(WikiPage, pk, request.user, write=True)
    w.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def wiki_revisions(request, pk):
    """wiki 修订历史。"""
    w = get_obj(WikiPage, pk, request.user)
    return ok({"title": w.title, "revisions": (w.revisions or [])[-50:],
               "version": len(w.revisions or [])})


@endpoint()
def wiki_move(request, pk):
    """移动页面：换父页或调排序（不允许把自己挂到自己的后代）。

    #42：目标父页改用 get_obj(write=True)，避免挂到他人/他租户页面下。
    """
    w = get_obj(WikiPage, pk, request.user, write=True)
    new_parent = None
    if p(request, "parent_id") is not None:
        new_parent_id = int(req_num(request, "parent_id", minimum=1))
        if new_parent_id == w.pk:
            raise ValueError("不能把自己设为父页")
        target = get_obj(WikiPage, new_parent_id, request.user, write=True)
        ancestor = target
        while ancestor is not None:
            if ancestor.pk == w.pk:
                raise ValueError("不能把页面移动到自己的子树下")
            ancestor = ancestor.parent
        new_parent = target
    if p(request, "order") is not None:
        w.order = int(req_num(request, "order", minimum=0))
    w.parent = new_parent
    w.save()
    return ok({"id": w.id, "parent": w.parent_id, "order": w.order})


@endpoint(("GET",))
def wiki_search(request):
    """wiki 全文搜索（标题 + 内容）。"""
    kw = req_str(request, "keyword")
    qs = scope_queryset(WikiPage.objects.filter(
        Q(title__icontains=kw) | Q(content__icontains=kw)), request.user)[:50]
    return ok({"keyword": kw,
               "items": [{"id": w.id, "title": w.title,
                          "snippet": (w.content or "")[:80]} for w in qs]})


@endpoint(("GET",))
def wiki_tree(request):
    """F688 知识库目录树浏览：整棵可见范围内的树（全深度）+ 面包屑 + 计数。

    兼容旧响应（仍返回 `tree`），新增 depth / path / child_count /
    like_count / star_count / page_count / max_depth 等浏览信息。
    """
    all_pages = list(
        scope_queryset(WikiPage.objects.all(), request.user).order_by("order", "id")[:1000]
    )
    children = {}
    for w in all_pages:
        children.setdefault(w.parent_id, []).append(w)

    max_depth = [0]

    def walk(nodes, path, depth, seen):
        out = []
        for w in nodes:
            if w.pk in seen:
                continue
            seen.add(w.pk)
            kids = children.get(w.pk, [])
            max_depth[0] = max(max_depth[0], depth)
            out.append({
                "id": w.id, "title": w.title, "order": w.order,
                "depth": depth, "path": path + [w.title],
                "has_children": bool(kids), "child_count": len(kids),
                "like_count": len(w.likes or []), "star_count": len(w.stars or []),
                "updated_at": w.updated_at.isoformat(),
                "children": walk(kids, path + [w.title], depth + 1, seen),
            })
        return out

    seen = set()
    tree = walk(children.get(None, []), [], 0, seen)
    # parent 不可见/成环的孤儿页挂到根，保证树里不丢页
    orphans = [w for w in all_pages if w.pk not in seen]
    if orphans:
        tree = tree + walk(orphans, [], 0, seen)

    def count_nodes(nodes):
        return sum(1 + count_nodes(n["children"]) for n in nodes)

    return ok({
        "tree": tree,
        "page_count": len(all_pages),
        "root_count": len(tree),
        "max_depth": max_depth[0] + 1,
        "node_count": count_nodes(tree),
    })


# =====================================================================
# F687 知识库文章点赞 / 收藏
# =====================================================================


def _toggle_name(names, username):
    """返回 (新列表, 本次是否点亮)。"""
    names = list(names or [])
    if username in names:
        names.remove(username)
        return names, False
    names.append(username)
    return names, True


@endpoint()
def wiki_like(request, pk):
    """F687 点赞（再点一次取消）。"""
    w = get_obj(WikiPage, pk, request.user)
    likes, on = _toggle_name(w.likes, request.user.username)
    w.likes = likes
    w.save(update_fields=["likes", "updated_at"])
    return ok({"id": w.id, "liked": on, "like_count": len(likes),
               "likes": likes[:50]})


@endpoint()
def wiki_star(request, pk):
    """F687 收藏到我的知识库（再点一次取消）。"""
    w = get_obj(WikiPage, pk, request.user)
    stars, on = _toggle_name(w.stars, request.user.username)
    w.stars = stars
    w.save(update_fields=["stars", "updated_at"])
    return ok({"id": w.id, "starred": on, "star_count": len(stars),
               "stars": stars[:50]})


def _wiki_subtree(root, limit=200):
    """S26-369：按 BFS 取子页（成环/超深也安全），返回 [root, ...]。"""
    pages, seen = [root], {root.pk}
    queue = [root]
    while queue and len(pages) < limit:
        node = queue.pop(0)
        for child in node.children.order_by("order", "id")[:50]:
            if child.pk in seen or len(pages) >= limit:
                continue
            seen.add(child.pk)
            pages.append(child)
            queue.append(child)
    return pages


@endpoint(("GET",))
def wiki_export(request, pk):
    """S26-369 Wiki 导出：fmt=md/html，children=1 时拼接子页，返回附件流。"""
    w = get_obj(WikiPage, pk, request.user)
    fmt = (opt_str(request, "fmt", "md") or "md").strip().lower()
    if fmt not in ("md", "html"):
        raise ValueError("fmt 仅支持 md / html")
    pages = _wiki_subtree(w) if opt_bool(request, "children") else [w]
    filename = re.sub(r'[\\/:*?"<>|\r\n]+', "_", w.title or "").strip("_ ")[:80] or f"wiki-{w.id}"

    if fmt == "md":
        parts = []
        for idx, pg in enumerate(pages):
            body = (pg.content or "").rstrip()
            if idx > 0:
                body = f"# {pg.title}\n\n{body}"
            parts.append(body)
        body_text = "\n\n---\n\n".join(parts)
        content_type = "text/markdown; charset=utf-8"
        ext = "md"
    else:
        sections = []
        for idx, pg in enumerate(pages):
            heading = "h1" if idx == 0 else "h2"
            sections.append(
                f"<section><{heading}>{html.escape(pg.title or '')}</{heading}>"
                f"<pre>{html.escape(pg.content or '')}</pre></section>"
            )
        body_text = (
            "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(w.title or 'Wiki')}</title></head><body>"
            + "\n".join(sections)
            + "</body></html>"
        )
        content_type = "text/html; charset=utf-8"
        ext = "html"

    resp = HttpResponse(body_text.encode("utf-8"), content_type=content_type)
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}.{ext}"
    return resp


# =====================================================================
# minutes 会议纪要（7）
# =====================================================================


@endpoint()
def minutes_create(request):
    """新建会议纪要。"""
    m = MeetingMinutes.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        meeting_at=parse_dt(opt_str(request, "meeting_at"), "meeting_at", allow_empty=True),
        attendees=p(request, "attendees") or [],
        content=opt_str(request, "content"),
        status="draft", data={"events": []})
    flow_event(m, "create", request.user)
    m.save()
    return ok({"id": m.id, "title": m.title, "status": m.status})


@endpoint(("GET",))
def minutes_list(request):
    """纪要列表（日期区间 + 关键词）。"""
    qs = scope_queryset(MeetingMinutes.objects.all(), request.user).order_by("-meeting_at")
    start = parse_day(opt_str(request, "start"), "start")
    end = parse_day(opt_str(request, "end"), "end")
    if start:
        qs = qs.filter(meeting_at__gte=start)
    if end:
        qs = qs.filter(meeting_at__lt=end + timezone.timedelta(days=1))
    kw = opt_str(request, "keyword")
    if kw:
        qs = qs.filter(Q(title__icontains=kw) | Q(content__icontains=kw))
    return ok({"items": [obj_dict(o, extra=("meeting_at", "attendees")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def minutes_detail(request, pk):
    """纪要详情。"""
    m = get_obj(MeetingMinutes, pk, request.user)
    out = obj_dict(o=m, extra=("meeting_at",))
    out["attendees"] = m.attendees
    out["content"] = m.content
    return ok(out)


@endpoint()
def minutes_update(request, pk):
    """更新纪要（可发布）。"""
    m = get_obj(MeetingMinutes, pk, request.user, write=True)
    if p(request, "title") is not None:
        m.title = req_str(request, "title")[:200]
    if p(request, "content") is not None:
        m.content = opt_str(request, "content")
    if p(request, "attendees") is not None:
        m.attendees = p(request, "attendees") or []
    if p(request, "meeting_at") is not None:
        m.meeting_at = parse_dt(opt_str(request, "meeting_at"), "meeting_at", allow_empty=True)
    if p(request, "publish") is not None and p(request, "publish"):
        m.status = "published"
        flow_event(m, "publish", request.user)
    m.save()
    return ok({"id": m.id, "status": m.status})


@endpoint()
def minutes_delete(request, pk):
    """删除纪要。"""
    m = get_obj(MeetingMinutes, pk, request.user, write=True)
    m.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def minutes_action_items(request, pk):
    """提取行动项：按「行动/TODO/待办/负责人/@」简单规则扫描正文。

    F692：提取结果连同完成状态一起持久化到 data.action_items，
    支撑「标记完成 → 完成率周统计」；响应新增 done / rate（向后兼容）。
    S26-352：GET 改为纯计算不落库（读接口不再产生写副作用），
    需要持久化请调用 POST minutes/<pk>/action-items/sync/。
    """
    m = get_obj(MeetingMinutes, pk, request.user)
    old = (m.data or {}).get("action_items") or {}
    if isinstance(old, list):
        old = {str(it.get("line_no")): it for it in old if isinstance(it, dict)}
    items = []
    for i, line in enumerate((m.content or "").splitlines()):
        s = line.strip()
        if not s:
            continue
        hit = any(k in s for k in ("行动", "TODO", "待办", "跟进", "负责", "@"))
        if not hit:
            continue
        prev = old.get(str(i + 1)) or {}
        items.append({
            "line_no": i + 1, "text": s[:200],
            "done": bool(prev.get("done")),
            "done_by": prev.get("done_by", ""),
            "done_at": prev.get("done_at", ""),
        })
    done = sum(1 for it in items if it["done"])
    return ok({
        "title": m.title, "action_items": items, "count": len(items),
        "done": done,
        "rate": round(done * 100 / len(items), 1) if items else 0.0,
    })


@endpoint()
def minutes_action_items_sync(request, pk):
    """S26-352 行动项落库：POST action_items（数组或 {line_no: item}）。

    写接口显式走 get_obj(write=True)，与 GET 的纯读语义分离。
    """
    m = get_obj(MeetingMinutes, pk, request.user, write=True)
    raw = p(request, "action_items")
    if raw is None:
        raw = p(request, "items")
    if isinstance(raw, dict):
        seq = list(raw.values())
    elif isinstance(raw, list):
        seq = raw
    else:
        raise ValueError("action_items 需为数组或 {line_no: item} 对象")
    items = {}
    for idx, it in enumerate(seq):
        if not isinstance(it, dict):
            raise ValueError("每个行动项需为对象")
        try:
            line_no = int(it.get("line_no") or idx + 1)
        except (TypeError, ValueError):
            raise ValueError("line_no 需为整数")
        if line_no < 1:
            raise ValueError("line_no 需为正整数")
        text = str(it.get("text") or "").strip()[:200]
        if not text:
            continue
        done = bool(it.get("done"))
        items[str(line_no)] = {
            "line_no": line_no, "text": text, "done": done,
            "done_by": str(it.get("done_by") or (request.user.username if done else ""))[:60],
            "done_at": str(it.get("done_at") or (timezone.now().isoformat() if done else "")),
        }
    m.data = {**(m.data or {}), "action_items": items}
    flow_event(m, "action_item_sync", request.user, f"同步 {len(items)} 条行动项")
    m.save()
    all_items = list(items.values())
    done_n = sum(1 for x in all_items if x.get("done"))
    return ok({
        "id": m.id, "action_items": all_items, "count": len(all_items),
        "done": done_n,
        "rate": round(done_n * 100 / len(all_items), 1) if all_items else 0.0,
    })


@endpoint()
def minutes_action_items_toggle(request, pk):
    """F692 标记行动项完成/未完成（按 line_no），返回最新完成率。"""
    m = get_obj(MeetingMinutes, pk, request.user, write=True)
    line_no = int(req_num(request, "line_no", minimum=1))
    items = (m.data or {}).get("action_items") or {}
    if isinstance(items, list):
        items = {str(it.get("line_no")): it for it in items if isinstance(it, dict)}
    key = str(line_no)
    if key not in items:
        raise ValueError(f"第 {line_no} 行不是行动项（先调 action-items 提取）")
    it = dict(items[key])
    it["done"] = not it.get("done")
    it["done_by"] = request.user.username if it["done"] else ""
    it["done_at"] = timezone.now().isoformat() if it["done"] else ""
    items[key] = it
    m.data = {**(m.data or {}), "action_items": items}
    flow_event(m, "action_item", request.user,
               f"{'完成' if it['done'] else '重开'} 行动项 L{line_no}")
    m.save()
    all_items = list(items.values())
    done_n = sum(1 for x in all_items if x.get("done"))
    return ok({
        "id": m.id, "line_no": line_no, "item": it,
        "done_count": done_n, "total": len(all_items),
        "rate": round(done_n * 100 / len(all_items), 1) if all_items else 0.0,
    })


@endpoint(("GET",))
def minutes_action_items_stats(request):
    """F692 行动项完成率周统计：最近 N 周（默认 8）按周聚合完成率。"""
    weeks = int(opt_num(request, "weeks", 8, integer=True, minimum=1, maximum=26))
    today = timezone.localdate()
    this_monday = today - timedelta(days=today.weekday())
    qs = scope_queryset(MeetingMinutes.objects.all(), request.user).order_by("-meeting_at")[:300]

    buckets = {}
    per_user = {}
    total = done = 0
    for m in qs:
        raw = (m.data or {}).get("action_items")
        if isinstance(raw, dict):
            its = list(raw.values())
        elif isinstance(raw, list):
            its = raw
        else:
            its = []
        if not its:
            continue
        base_date = (timezone.localtime(m.meeting_at).date() if m.meeting_at
                     else m.created_at.date())
        monday = base_date - timedelta(days=base_date.weekday())
        b = buckets.setdefault(str(monday), {"total": 0, "done": 0})
        for it in its:
            b["total"] += 1
            total += 1
            if it.get("done"):
                b["done"] += 1
                done += 1
                who = it.get("done_by") or "未知"
                per_user[who] = per_user.get(who, 0) + 1

    series = []
    for i in range(weeks - 1, -1, -1):
        monday = this_monday - timedelta(days=7 * i)
        b = buckets.get(str(monday), {"total": 0, "done": 0})
        series.append({
            "week": str(monday), "total": b["total"], "done": b["done"],
            "rate": round(b["done"] * 100 / b["total"], 1) if b["total"] else 0.0,
        })
    return ok({
        "weeks": weeks, "series": series,
        "total": total, "done": done,
        "rate": round(done * 100 / total, 1) if total else 0.0,
        "by_user": [{"user": k, "done": v}
                    for k, v in sorted(per_user.items(), key=lambda kv: -kv[1])[:10]],
    })


@endpoint(("GET",))
def minutes_stats(request):
    """纪要统计：近 30 天场次、最活跃参会人。"""
    month_ago = timezone.now() - timedelta(days=30)
    recent = MeetingMinutes.objects.filter(created_at__gte=month_ago)
    attendee_count = {}
    for m in recent[:200]:
        for a in (m.attendees or [])[:20]:
            attendee_count[str(a)] = attendee_count.get(str(a), 0) + 1
    top = sorted(attendee_count.items(), key=lambda kv: -kv[1])[:5]
    return ok({"last_30d": recent.count(), "total": MeetingMinutes.objects.count(),
               "top_attendees": [{"name": n, "meetings": c} for n, c in top]})


# =====================================================================
# formcollect 收集表单（8）
# =====================================================================


@endpoint()
def form_create(request):
    """创建收集表单（fields: [{name,type,required}]）。"""
    fields = p(request, "fields") or []
    if not isinstance(fields, list) or not fields:
        raise ValueError("fields 需为非空数组 [{name,type,required}]")
    for f in fields:
        if not isinstance(f, dict) or not f.get("name"):
            raise ValueError("每个字段需含 name")
    form = CollectForm.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        fields=fields,
        closed=False)
    return ok({"id": form.id, "title": form.title, "field_count": len(fields)})


@endpoint(("GET",))
def form_list(request):
    """表单列表（含填写数）。"""
    qs = scope_queryset(CollectForm.objects.all(), request.user).order_by("-created_at")
    items = [{"id": f.id, "title": f.title, "closed": f.closed,
              "field_count": len(f.fields or []),
              "entries": f.entries.count(),
              "owner": f.owner.username} for f in qs[:100]]
    return ok({"items": items, "count": qs.count()})


@endpoint()
def form_detail(request, pk):
    """表单详情（字段定义）。"""
    f = get_obj(CollectForm, pk, request.user)
    return ok({"id": f.id, "title": f.title, "fields": f.fields,
               "closed": f.closed, "entries": f.entries.count(),
               "owner": f.owner.username})


@endpoint()
def form_update(request, pk):
    """编辑表单（截止/标题/字段）。"""
    f = get_obj(CollectForm, pk, request.user, write=True)
    if p(request, "title") is not None:
        f.title = req_str(request, "title")[:200]
    if p(request, "fields") is not None:
        flds = p(request, "fields") or []
        if not isinstance(flds, list) or not flds:
            raise ValueError("fields 需为非空数组")
        f.fields = flds
    if p(request, "closed") is not None:
        f.closed = parse_bool(p(request, "closed"), field="closed")
    f.save()
    return ok({"id": f.id, "title": f.title, "closed": f.closed})


@endpoint()
def form_delete(request, pk):
    """删除表单（连带填写记录）。"""
    f = get_obj(CollectForm, pk, request.user, write=True)
    f.delete()
    return ok({"deleted": pk})


@endpoint()
def form_submit(request, pk):
    """提交一份填写（截止后拒绝；required 校验）。"""
    f = get_obj(CollectForm, pk, request.user)
    if f.closed:
        raise ValueError("表单已截止")
    values = p(request, "values") or {}
    if not isinstance(values, dict):
        raise ValueError("values 需为键值对象")
    for fld in f.fields or []:
        if fld.get("required") and values.get(fld.get("name")) in (None, ""):
            raise ValueError(f"必填字段缺失：{fld.get('name')}")
    e = FormEntry.objects.create(form=f, values=values)
    return ok({"id": e.id, "form": f.title, "values": values})


def _require_form_owner(f, user, action="查看"):
    """#37：答卷含隐私字段，只允许表单创建者或管理员读取/导出。"""
    if f.owner_id != getattr(user, "id", None) and not (
            getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)):
        raise ValueError(f"仅表单创建者可{action}答卷")


@endpoint(("GET",))
def form_entries(request, pk):
    """查看收集结果（#37：仅创建人或管理员）。"""
    try:
        f = CollectForm.objects.get(pk=pk)
    except CollectForm.DoesNotExist:
        raise ValueError("表单不存在")
    _require_form_owner(f, request.user)
    rows = f.entries.order_by("-created_at")[:500]
    return ok({"form": f.title, "fields": f.fields,
               "items": [{"id": e.id, "values": e.values,
                          "created_at": e.created_at.isoformat()} for e in rows],
               "count": f.entries.count()})


@endpoint(("GET",))
def form_export(request, pk):
    """导出填写结果 CSV 文本（#37：仅创建人或管理员）。"""
    try:
        f = CollectForm.objects.get(pk=pk)
    except CollectForm.DoesNotExist:
        raise ValueError("表单不存在")
    _require_form_owner(f, request.user, "导出")
    names = [str(fl.get("name", "")) for fl in (f.fields or [])]

    def esc(v):
        s = str(v if v is not None else "")
        return '"' + s.replace('"', "'") + '"'
    lines = [",".join(esc(n) for n in names)]
    for e in f.entries.order_by("created_at")[:2000]:
        lines.append(",".join(esc((e.values or {}).get(n, "")) for n in names))
    return ok({"csv": "\n".join(lines), "rows": len(lines) - 1})


def _is_number(val):
    """S26-371：可参与均值统计的数值（bool 不算）。"""
    if isinstance(val, bool) or val is None or val == "":
        return False
    try:
        float(val)
        return True
    except (TypeError, ValueError):
        return False


@endpoint(("GET",))
def form_stats(request, pk):
    """S26-371 表单字段级统计：选项计数 / 数值均值 / 填空 TOP10。

    仅表单创建人或管理员可看（与 entries/export 的隐私口径一致）。
    """
    try:
        f = CollectForm.objects.get(pk=pk)
    except CollectForm.DoesNotExist:
        raise ValueError("表单不存在")
    _require_form_owner(f, request.user, "查看统计")
    rows = list(f.entries.order_by("id").values_list("values", flat=True)[:5000])
    total = len(rows)
    out = []
    for fld in f.fields or []:
        name = str(fld.get("name", ""))
        ftype = str(fld.get("type", "text")).lower()
        values = []
        for vals in rows:
            v = (vals or {}).get(name)
            if isinstance(v, list):
                values.extend([str(x) for x in v if str(x).strip()])
            elif v not in (None, ""):
                values.append(v)
        filled = len([1 for vals in rows if (vals or {}).get(name) not in (None, "", [])])
        numeric = bool(values) and all(_is_number(v) for v in values)
        nums = [float(v) for v in values] if numeric else []
        counts = {}
        for v in values:
            key = str(v)[:80]
            counts[key] = counts.get(key, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        out.append({
            "name": name, "type": ftype, "required": bool(fld.get("required")),
            "filled": filled, "empty": total - filled,
            "fill_rate": round(filled * 100 / total, 1) if total else 0.0,
            "unique": len(counts),
            "numeric": numeric,
            "mean": round(sum(nums) / len(nums), 2) if nums else None,
            "min": min(nums) if nums else None,
            "max": max(nums) if nums else None,
            "options": [{"value": k, "count": c,
                         "pct": round(c * 100 / max(filled, 1), 1)} for k, c in top],
            "top10": [{"value": k, "count": c} for k, c in top],
        })
    return ok({"form": f.title, "entries": total, "fields": out,
               "field_count": len(out)})


# =====================================================================
# announcement 部门公告（8）
# =====================================================================


@endpoint()
def announcement_create(request):
    """发布公告。"""
    a = DeptAnnouncement.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        remark=opt_str(request, "content"),
        audience=opt_str(request, "audience", "全员"),
        pinned=opt_bool(request, "pinned"),
        status="published", data={"events": []})
    flow_event(a, "publish", request.user)
    a.save()
    return ok({"id": a.id, "title": a.title, "audience": a.audience})


@endpoint(("GET",))
def announcement_list(request):
    """公告列表（置顶优先 + 已读状态）。"""
    qs = scope_queryset(DeptAnnouncement.objects.all(), request.user).order_by("-pinned", "-created_at")
    audience = opt_str(request, "audience")
    if audience:
        qs = qs.filter(audience=audience)
    items = []
    for o in qs[:100]:
        d = obj_dict(o, extra=("audience", "pinned"))
        d["read_by_me"] = request.user.username in (o.read_by or [])
        items.append(d)
    return ok({"items": items, "count": qs.count()})


@endpoint()
def announcement_detail(request, pk):
    """公告详情（正文 + 已读数）。"""
    a = get_obj(DeptAnnouncement, pk, request.user)
    out = obj_dict(o=a, extra=("audience", "pinned"))
    out["content"] = a.remark
    out["read_count"] = len(a.read_by or [])
    return ok(out)


@endpoint()
def announcement_update(request, pk):
    """编辑公告。"""
    a = get_obj(DeptAnnouncement, pk, request.user, write=True)
    if p(request, "title") is not None:
        a.title = req_str(request, "title")[:200]
    if p(request, "content") is not None:
        a.remark = opt_str(request, "content")
    if p(request, "audience") is not None:
        a.audience = opt_str(request, "audience", a.audience)
    a.save()
    return ok({"id": a.id, "title": a.title})


@endpoint()
def announcement_pin(request, pk):
    """置顶/取消置顶切换（#36：仅发布者/管理员可写）。"""
    a = get_obj(DeptAnnouncement, pk, request.user, write=True)
    a.pinned = not a.pinned
    a.save(update_fields=["pinned", "updated_at"])
    return ok({"id": a.id, "pinned": a.pinned})


@endpoint()
def announcement_read(request, pk):
    """标记已读（幂等）。"""
    a = get_obj(DeptAnnouncement, pk, request.user)
    read = list(a.read_by or [])
    if request.user.username not in read:
        read.append(request.user.username)
        a.read_by = read
        a.save(update_fields=["read_by", "updated_at"])
    return ok({"id": a.id, "read_by_me": True, "read_count": len(read)})


@endpoint(("GET",))
def announcement_readers(request, pk):
    """公告已读/未读名单（可见范围）。"""
    a = get_obj(DeptAnnouncement, pk, request.user)
    from accounts.models import User
    read = a.read_by or []
    visible = list(User.objects.filter(
        id__in=visible_user_ids(request.user) or {request.user.id}
    ).values_list("username", flat=True)) if request.user.is_authenticated else []
    return ok({"title": a.title, "read": [n for n in visible if n in read][:50],
               "unread": [n for n in visible if n not in read][:50]})


@endpoint()
def announcement_delete(request, pk):
    """删除公告。"""
    a = get_obj(DeptAnnouncement, pk, request.user, write=True)
    a.delete()
    return ok({"deleted": pk})


# =====================================================================
# poll 投票（9）
# =====================================================================

# #82：选项数量夹在 2–20，避免一次投票塞进上万选项把 JSONField 与结果面板撑爆
POLL_OPTION_MIN = 2
POLL_OPTION_MAX = 20
# #83：单投票选票上限；超过后拒绝继续投票，聚合也只扫前 N 张（防全量载入内存）
POLL_BALLOT_MAX = 5000


def _poll_tally(poll):
    """#83：聚合各选项票数。

    只取 ``choices`` 一列并按选票上限截断，不再把整场投票的 PollVote 实例
    全部实例化到内存；返回 (tally, counted_ballots)。
    """
    tally = {opt: 0 for opt in poll.options or []}
    counted = 0
    qs = poll.votes.values_list("choices", flat=True).order_by("id")[:POLL_BALLOT_MAX]
    for choices in qs:
        counted += 1
        for c in choices or []:
            if c in tally:
                tally[c] += 1
    return tally, counted


@endpoint()
def poll_create(request):
    """发起投票（options 2–20 项）。"""
    options = p(request, "options") or []
    if not isinstance(options, list) or len(options) < POLL_OPTION_MIN:
        raise ValueError(f"options 需为至少 {POLL_OPTION_MIN} 项的数组")
    if len(options) > POLL_OPTION_MAX:
        raise ValueError(f"options 最多 {POLL_OPTION_MAX} 项")
    options = [str(o)[:60] for o in options if str(o).strip()]
    if len(options) < POLL_OPTION_MIN:
        raise ValueError(f"有效选项不足 {POLL_OPTION_MIN} 项（空选项已忽略）")
    poll = Poll.objects.create(
        owner=request.user,
        question=req_str(request, "question")[:300],
        options=options,
        multiple=opt_bool(request, "multiple"),
        deadline=parse_day(opt_str(request, "deadline"), "deadline"))
    return ok({"id": poll.id, "question": poll.question, "options": poll.options})


@endpoint(("GET",))
def poll_list(request):
    """投票列表（含票数与状态）。"""
    # #123：一次 annotate 聚合票数，替代循环内逐条 votes.count()
    qs = (scope_queryset(Poll.objects.all(), request.user)
          .select_related("owner").annotate(vc=Count("votes")).order_by("-created_at"))
    items = []
    for o in qs[:100]:
        items.append({"id": o.id, "question": o.question, "multiple": o.multiple,
                      "closed": o.closed, "deadline": str(o.deadline or ""),
                      "votes": o.vc,
                      "owner": o.owner.username})
    return ok({"items": items, "count": qs.count()})


@endpoint()
def poll_detail(request, pk):
    """投票详情（含各选项票数）。"""
    poll = get_obj(Poll, pk, request.user)
    tally, counted = _poll_tally(poll)
    total_ballots = poll.votes.count()
    return ok({"id": poll.id, "question": poll.question, "options": poll.options,
               "multiple": poll.multiple, "closed": poll.closed,
               "deadline": str(poll.deadline or ""),
               "tally": tally, "total_ballots": total_ballots,
               "counted_ballots": counted,
               "truncated": total_ballots > counted})


@endpoint()
def poll_vote(request, pk):
    """投票（一人一票；多选校验选项；截止校验）。"""
    poll = get_obj(Poll, pk, request.user)
    if poll.closed:
        raise ValueError("投票已截止")
    if poll.deadline and timezone.localdate() > poll.deadline:
        raise ValueError("已过投票截止日")
    if PollVote.objects.filter(poll=poll, voter_name=request.user.username).exists():
        raise ValueError("你已投过票")
    # #83：单投票票数上限（超出后结果聚合会失真，直接拒绝新票）
    if PollVote.objects.filter(poll=poll).count() >= POLL_BALLOT_MAX:
        raise ValueError(f"该投票票数已达上限 {POLL_BALLOT_MAX}")
    choices = p(request, "choices") or []
    if not isinstance(choices, list) or not choices:
        raise ValueError("choices 需为非空数组")
    if not poll.multiple and len(choices) > 1:
        raise ValueError("该投票为单选")
    for c in choices:
        if c not in poll.options:
            raise ValueError(f"无效选项：{c}")
    v = PollVote.objects.create(poll=poll, voter_name=request.user.username,
                                choices=[str(c)[:60] for c in choices])
    return ok({"id": v.id, "choices": v.choices})


@endpoint(("GET",))
def poll_results(request, pk):
    """投票结果（票数 + 占比，排序）。"""
    poll = get_obj(Poll, pk, request.user)
    tally, counted = _poll_tally(poll)
    total = sum(tally.values())
    total_ballots = poll.votes.count()
    ranked = sorted([{"option": k, "votes": v,
                      "pct": round(v / total * 100, 1) if total else 0}
                     for k, v in tally.items()], key=lambda x: -x["votes"])
    return ok({"question": poll.question, "results": ranked,
               "total_ballots": total_ballots, "total_choices": total,
               "counted_ballots": counted,
               "truncated": total_ballots > counted})


@endpoint()
def poll_close(request, pk):
    """截止投票。"""
    poll = get_obj(Poll, pk, request.user)
    if poll.closed:
        raise ValueError("已经截止")
    poll.closed = True
    poll.save(update_fields=["closed"])
    return ok({"id": poll.id, "closed": True})


@endpoint()
def poll_reopen(request, pk):
    """重开投票。"""
    poll = get_obj(Poll, pk, request.user)
    if not poll.closed:
        raise ValueError("该投票未截止")
    poll.closed = False
    poll.save(update_fields=["closed"])
    return ok({"id": poll.id, "closed": False})


@endpoint()
def poll_delete(request, pk):
    """删除投票（连带选票）。"""
    poll = get_obj(Poll, pk, request.user, write=True)
    poll.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def poll_my_votes(request):
    """我的投票历史。"""
    votes = PollVote.objects.filter(voter_name=request.user.username).select_related("poll").order_by("-created_at")[:100]
    return ok({"items": [{"id": v.id, "poll_id": v.poll_id, "question": v.poll.question,
                          "choices": v.choices, "poll_closed": v.poll.closed} for v in votes],
               "count": votes.count()})


# =====================================================================
# helpdesk 工单（9）
# =====================================================================


@endpoint()
def ticket_create(request):
    """提工单。"""
    t = HelpTicket.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        priority=opt_str(request, "priority", "normal"),
        status="open",
        data={"description": opt_str(request, "description"),
              "category": opt_str(request, "category", "其他"), "events": []})
    flow_event(t, "create", request.user)
    t.save()
    return ok({"id": t.id, "title": t.title, "status": t.status})


@endpoint(("GET",))
def ticket_list(request):
    """工单列表（状态/优先级/分类过滤）。"""
    qs = scope_queryset(HelpTicket.objects.all(), request.user).order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    priority = opt_str(request, "priority")
    if priority:
        qs = qs.filter(priority=priority)
    category = opt_str(request, "category")
    if category:
        qs = qs.filter(data__category=category)
    return ok({"items": [obj_dict(o, extra=("priority", "assignee_name")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def ticket_detail(request, pk):
    """工单详情（含回复与事件）。"""
    t = get_obj(HelpTicket, pk, request.user)
    out = obj_dict(o=t, extra=("priority", "assignee_name"))
    out["description"] = (t.data or {}).get("description", "")
    out["category"] = (t.data or {}).get("category", "")
    out["replies"] = (t.data or {}).get("replies", [])
    out["events"] = (t.data or {}).get("events", [])
    return ok(out)


@endpoint()
def ticket_assign(request, pk):
    """指派处理人。"""
    t = get_obj(HelpTicket, pk, request.user, write=True)
    if t.status == "resolved":
        raise ValueError("已解决的工单无需指派")
    t.assignee_name = req_str(request, "assignee")[:60]
    assignee_id = opt_num(request, "assignee_id")
    if not assignee_id and t.assignee_name:
        from accounts.models import User

        u = User.objects.filter(Q(username=t.assignee_name) | Q(nickname=t.assignee_name)).first()
        assignee_id = u.id if u else None
    t.data = {**(t.data or {}), "assignee_id": int(assignee_id) if assignee_id else None}
    if t.status == "open":
        t.status = "in_progress"
    flow_event(t, "assign", request.user, f"指派给 {t.assignee_name}")
    t.save()
    return ok({"id": t.id, "assignee": t.assignee_name, "status": t.status})


@endpoint()
def ticket_reply(request, pk):
    """回复工单。"""
    t = get_obj(HelpTicket, pk, request.user, write=True)
    content = req_str(request, "content")
    replies = list((t.data or {}).get("replies", []))
    replies.append({"by": request.user.username,
                    "content": content[:2000],
                    "at": timezone.now().isoformat()})
    t.data = {**(t.data or {}), "replies": replies[-100:]}
    if t.status == "open":
        t.status = "in_progress"
    flow_event(t, "reply", request.user)
    t.save()
    return ok({"id": t.id, "reply_count": len(replies), "status": t.status})


@endpoint()
def ticket_resolve(request, pk):
    """解决工单（记录解决方案）。"""
    t = get_obj(HelpTicket, pk, request.user, write=True)
    if t.status == "resolved":
        raise ValueError("工单已是解决状态")
    t.status = "resolved"
    t.data = {**(t.data or {}), "solution": opt_str(request, "solution")}
    flow_event(t, "resolve", request.user)
    t.save()
    return ok({"id": t.id, "status": t.status})


@endpoint()
def ticket_reopen(request, pk):
    """重开工单（解决后仍可重开）。"""
    t = get_obj(HelpTicket, pk, request.user, write=True)
    if t.status != "resolved":
        raise ValueError("仅已解决的工单可重开")
    t.status = "in_progress"
    flow_event(t, "reopen", request.user, opt_str(request, "reason"))
    t.save()
    return ok({"id": t.id, "status": t.status})


@endpoint()
def ticket_priority(request, pk):
    """调整优先级。"""
    t = get_obj(HelpTicket, pk, request.user, write=True)
    if t.status == "resolved":
        raise ValueError("已解决的工单不再调整优先级")
    prio = req_str(request, "priority")
    if prio not in ("low", "normal", "high", "urgent"):
        raise ValueError("priority 支持 low/normal/high/urgent")
    old = t.priority
    t.priority = prio
    flow_event(t, "priority", request.user, f"{old} → {prio}")
    t.save()
    return ok({"id": t.id, "priority": prio})


@endpoint(("GET",))
def ticket_stats(request):
    """工单统计：状态分布、优先级分布、解决率（F684 附满意度均分）。"""
    by_status = HelpTicket.objects.values("status").annotate(c=Count("id")).order_by("-c")
    by_prio = HelpTicket.objects.values("priority").annotate(c=Count("id")).order_by("-c")
    total = HelpTicket.objects.count()
    resolved = HelpTicket.objects.filter(status="resolved").count()
    ratings = [
        (row["data"] or {}).get("rating")
        for row in HelpTicket.objects.filter(status="resolved").values("data")[:500]
    ]
    ratings = [int(r) for r in ratings if isinstance(r, (int, float))]
    return ok({"by_status": [{"status": b["status"], "count": b["c"]} for b in by_status],
               "by_priority": [{"priority": b["priority"], "count": b["c"]} for b in by_prio],
               "total": total,
               "rating_count": len(ratings),
               "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
               "resolve_rate": round(resolved / total * 100, 1) if total else 0})


# =====================================================================
# F684 工单满意度评分 / F685 轮询自动分配
# =====================================================================


@endpoint()
def ticket_rate(request, pk):
    """F684 满意度评分：工单关闭（resolved）后 1–5 星 + 留言，可重复改评。"""
    t = get_obj(HelpTicket, pk, request.user, write=True)
    if t.status != "resolved":
        raise ValueError("工单关闭（已解决）后才能评分")
    raw = req_num(request, "rating", minimum=1, maximum=5)
    if raw != int(raw):
        raise ValueError("rating 需为 1–5 的整数星级")
    rating = int(raw)
    comment = opt_str(request, "comment", "")[:500]
    prev = (t.data or {}).get("rating")
    history = list((t.data or {}).get("rating_history") or [])
    if prev is not None:
        history.append({"rating": prev, "comment": (t.data or {}).get("rating_comment", ""),
                        "by": (t.data or {}).get("rated_by", ""),
                        "at": (t.data or {}).get("rated_at", "")})
    t.data = {**(t.data or {}),
              "rating": rating, "rating_comment": comment,
              "rated_by": request.user.username,
              "rated_at": timezone.now().isoformat(),
              "rating_history": history[-10:]}
    flow_event(t, "rate", request.user, f"满意度 {rating} 星")
    t.save()
    return ok({"id": t.id, "rating": rating, "comment": comment,
               "previous": prev, "changed": prev is not None, "status": t.status})


@endpoint()
def ticket_auto_assign(request):
    """F685 轮询自动分配：把未指派工单派给「当前负载最小」的成员。

    负载 = 该成员名下未完成（open/in_progress）工单数；
    候选成员可用 members 参数显式指定，否则取历史处理过工单的人，
    再兜底到全体活跃用户。可传 ticket_id 只分配单条。
    """
    base = scope_queryset(
        HelpTicket.objects.filter(status__in=("open", "in_progress")), request.user
    ).order_by("created_at")
    # 批量改派是管理动作：可见范围不等于处置权
    if not (request.user.is_superuser or request.user.is_staff):
        raise ValueError("仅管理员可批量改派工单")

    # 各成员当前负载
    load = {}
    for row in base.exclude(assignee_name="").values("assignee_name").annotate(c=Count("id")):
        if row["assignee_name"]:
            load[row["assignee_name"]] = row["c"]

    members = p(request, "members")
    if isinstance(members, list) and members:
        members = [str(m).strip()[:60] for m in members if str(m).strip()]
    else:
        members = list(
            HelpTicket.objects.exclude(assignee_name="")
            .values_list("assignee_name", flat=True).distinct()[:50]
        )
        if not members:
            from django.contrib.auth import get_user_model
            members = list(
                get_user_model().objects.filter(is_active=True)
                .values_list("username", flat=True)[:50]
            )
    if not members:
        raise ValueError("没有可分配的成员")
    for m in members:
        load.setdefault(m, 0)

    ticket_id = opt_num(request, "ticket_id", None, integer=True)
    if ticket_id:
        qs = base.filter(pk=ticket_id)
    else:
        limit = int(opt_num(request, "limit", 50, integer=True, minimum=1, maximum=200))
        qs = base.filter(assignee_name="")[:limit]

    assignments = []
    for t in qs:
        member = min(members, key=lambda m: (load[m], m))
        t.assignee_name = member
        if t.status == "open":
            t.status = "in_progress"
        flow_event(t, "auto-assign", request.user, f"轮询分配给 {member}（接手前负载 {load[member]}）")
        t.save()
        load[member] += 1
        assignments.append({"ticket": t.id, "title": t.title,
                            "assignee": member, "load_after": load[member]})

    if not assignments:
        raise ValueError("没有待分配的工单（可能都已指派）")
    return ok({
        "assigned": len(assignments), "items": assignments,
        "candidates": members,
        "loads": [{"member": m, "load": load[m]}
                  for m in sorted(members, key=lambda x: (load[x], x))],
    })


KNOW_FAMILY_COUNT = 7 + 8 + 7 + 12 + 12 + 9 + 8 + 9 + 11  # = 83（S26：minutes +2 含 to-todo、wiki/policy/form 各 +1）


@endpoint()
def minutes_to_todo(request, pk):
    """会议纪要行动项一键转待办（#92）。

    扫描纪要正文中的行动项，批量创建 TodoItem。
    POST {"items": [{"text": "..."}]} 不传则自动扫描正文。
    """
    from officesuite.models import TodoItem
    m = get_obj(MeetingMinutes, pk, request.user)
    raw = request.data.get("items")
    if isinstance(raw, list) and raw:
        texts = [str(it.get("text") or it)[:200] for it in raw if str(it.get("text") or it).strip()]
    else:
        texts = []
        for line in (m.content or "").splitlines():
            s = line.strip()
            if s and any(k in s for k in ("行动", "TODO", "待办", "跟进", "负责", "@")):
                texts.append(s[:200])
    if not texts:
        raise ValueError("未提取到行动项")
    created = []
    for t in texts:
        obj = TodoItem.objects.create(
            owner=request.user, title=t, priority="normal",
            status="open", data={"source": "minutes", "minutes_id": m.id, "events": []})
        created.append({"id": obj.id, "title": obj.title})
    return ok({"created": len(created), "items": created})


# 行动项里的日期：2026-05-12 / 2026/5/12 / 5月12日（默认当年）
_DATE_FULL_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
_DATE_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[月/.]\s*(\d{1,2})(?!\d)")


def _action_item_date(text, today):
    """S26-372：从行动项文本里抽出日期（无日期返回 None）。"""
    hit = _DATE_FULL_RE.search(text or "")
    if hit:
        y, m, d = (int(x) for x in hit.groups())
    else:
        hit = _DATE_MD_RE.search(text or "")
        if not hit:
            return None
        y, (m, d) = today.year, (int(hit.group(1)), int(hit.group(2)))
    try:
        return datetime(y, m, d).date()
    except ValueError:
        return None


@endpoint()
def minutes_action_items_to_calendar(request, pk):
    """S26-372 行动项转日程：把带日期的行动项批量建 SuiteEvent（source=minutes）。

    data.calendar_items 记录 line_no→event_id，重复调用只补新建项（幂等）。
    """
    m = get_obj(MeetingMinutes, pk, request.user, write=True)
    converted = dict((m.data or {}).get("calendar_items") or {})
    raw = p(request, "items")
    if isinstance(raw, list) and raw:
        seq = []
        for idx, it in enumerate(raw):
            text = str(it.get("text") if isinstance(it, dict) else it or "").strip()
            line_no = int(it.get("line_no") or idx + 1) if isinstance(it, dict) else idx + 1
            if text:
                seq.append({"line_no": line_no, "text": text})
    else:
        stored = (m.data or {}).get("action_items") or {}
        if isinstance(stored, dict):
            seq = [{"line_no": int(it.get("line_no") or k), "text": str(it.get("text") or "")}
                   for k, it in stored.items() if isinstance(it, dict)]
        else:
            seq = [{"line_no": i + 1, "text": s.strip()}
                   for i, s in enumerate((m.content or "").splitlines()) if s.strip()]
        seq = [it for it in seq if any(k in it["text"] for k in
                                       ("行动", "TODO", "待办", "跟进", "负责", "@"))]
    today = timezone.localdate()
    created, skipped = [], 0
    for it in seq:
        text = str(it.get("text") or "").strip()[:200]
        if not text:
            continue
        key = str(it.get("line_no"))
        if key in converted:
            skipped += 1
            continue
        day = _action_item_date(text, today)
        if day is None:
            skipped += 1
            continue
        start = timezone.make_aware(datetime(day.year, day.month, day.day, 9, 0))
        e = SuiteEvent.objects.create(
            owner=request.user, title=text, status="planned",
            start_at=start, end_at=start + timedelta(hours=1), kind="event",
            data={"source": "minutes", "minutes_id": m.id, "line_no": it.get("line_no")},
        )
        converted[key] = e.id
        created.append({"id": e.id, "line_no": it.get("line_no"), "title": text,
                        "date": str(day)})
    if not created and skipped:
        raise ValueError("没有可转换的带日期行动项（已转换或缺少日期）")
    m.data = {**(m.data or {}), "calendar_items": converted}
    flow_event(m, "to_calendar", request.user, f"转日程 {len(created)} 条")
    m.save()
    return ok({"minutes_id": m.id, "created": len(created), "skipped": skipped,
               "event_ids": [c["id"] for c in created], "items": created})
