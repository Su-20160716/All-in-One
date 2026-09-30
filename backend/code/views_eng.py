# -*- coding: utf-8 -*-
"""代码工坊视图（四）：工程化收口（L4 第 65~86 条的补齐部分）。

包含：代码归属统计（blame） / TODO 聚合 / diff 视图 / 工程洞察。

设计要点：
- 全部基于既有 CodeFile / CodeVersion / CodeRun / CodeJudgeTask 做聚合，
  **不新增模型**——这层是"把已有数据读出价值"，不是再造数据。
- blame 用「版本链回溯」实现：从当前内容出发，逐个版本比对，
  某行的最后修改版本即其归属；未变过的行归到文件创建者。
"""
import difflib
import re

from django.db.models import Count, Sum, Q

from devtools.common import (
    endpoint, ok, fail, p, req, req_str, opt_str, req_num, opt_num, opt_bool, as_lines,
)

from . import runtime as rt
from .models import (
    CodeFile,
    CodeJudgeTask,
    CodeRun,
    CodeVersion,
    CodeWorkspace,
)
from .serializers import file_qs, get_file, get_ws, ws_qs


# ============================================================
# 一、代码归属统计 blame（第 80 条）
# ============================================================


@endpoint(("GET",))
def blame(request, pk):
    """逐行归属：给出每行「最后由谁改的 / 在哪个版本改的」。

    算法：把版本链按时间正序排列，从**最早的版本**开始逐版 diff，
    记录每一行的"最后一次变更"归属。当前内容中未在历史里出现过的行，
    归到文件最后修改者（通常是自动保存产生的新行）。

    参数：`max_lines` 限制返回行数（默认 2000），避免大文件拖垮响应。
    """
    f = get_file(request.user, pk)
    max_lines = opt_num(request, "max_lines", 2000, integer=True, minimum=1, maximum=20000)

    current = as_lines(f.content or "")
    versions = list(f.versions.order_by("created_at"))

    if not versions:
        # 没有任何版本记录 → 全部归给文件 owner
        owner_name = _display_name(f.owner)
        return ok({
            "lines": [
                {"line": i, "author": owner_name, "version_id": None,
                 "at": f.updated_at, "changed": False}
                for i, _ in enumerate(current[:max_lines], start=1)
            ],
            "authors": [{"author": owner_name, "lines": len(current), "percent": 100}],
            "total_lines": len(current),
            "version_count": 0,
            "note": "该文件暂无版本快照，全部行归属到文件所有者。",
        })

    # 逐版本累积「每行的归属」
    # ownership[line_index] = {"author": name, "version_id": id, "at": dt}
    ownership = {}

    prev_lines = []
    for v in versions:
        cur_lines = as_lines(v.content or "")
        author = _display_name(v.created_by or f.owner)
        sm = difflib.SequenceMatcher(None, prev_lines, cur_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("replace", "insert"):
                for j in range(j1, j2):
                    ownership[j] = {
                        "author": author, "version_id": v.id, "at": v.created_at,
                    }
            # delete 不需要处理——那些行已不在当前内容里
        prev_lines = cur_lines

    # 当前内容可能比最后一个版本更长（编辑后自动保存过但没打快照）
    fallback_author = _display_name(f.owner)
    rows = []
    for i, _ in enumerate(current[:max_lines]):
        own = ownership.get(i)
        if own:
            rows.append({
                "line": i + 1, "author": own["author"],
                "version_id": own["version_id"], "at": own["at"], "changed": True,
            })
        else:
            rows.append({
                "line": i + 1, "author": fallback_author,
                "version_id": None, "at": f.updated_at, "changed": False,
            })

    # 按作者汇总
    counter = {}
    for r in rows:
        counter[r["author"]] = counter.get(r["author"], 0) + 1
    total = max(1, len(rows))
    authors = [
        {"author": a, "lines": c, "percent": round(c * 100 / total)}
        for a, c in sorted(counter.items(), key=lambda x: -x[1])
    ]

    return ok({
        "lines": rows,
        "authors": authors,
        "total_lines": len(current),
        "returned_lines": len(rows),
        "version_count": len(versions),
        "truncated": len(current) > max_lines,
    })


def _display_name(user):
    if not user:
        return "未知"
    return getattr(user, "username", None) or getattr(user, "email", None) or f"用户{user.id}"


# ============================================================
# 二、TODO 聚合（第 81 条）
# ============================================================

_TODO_RX = re.compile(
    r"(?P<tag>TODO|FIXME|HACK|XXX|BUG|NOTE|OPTIMIZE|REVIEW)\b[\s:：\-]*(?P<text>.*)",
    re.IGNORECASE,
)

_TAG_LEVEL = {
    "FIXME": "high", "BUG": "high",
    "TODO": "medium", "HACK": "medium", "XXX": "medium",
    "OPTIMIZE": "low", "REVIEW": "low", "NOTE": "info",
}


@endpoint(("GET",))
def todos(request):
    """扫描工作区（或全部）代码，聚合 TODO/FIXME 等标记。

    参数：
    - `workspace`: 限定工作区 id
    - `tag`: 只看某类标记（TODO/FIXME/...）
    - `include_done`: 是否包含已标记完成（含 DONE 关键字）的项
    """
    ws_id = opt_num(request, "workspace", None, integer=True)
    only_tag = (opt_str(request, "tag", "") or "").upper()
    limit = opt_num(request, "limit", 500, integer=True, minimum=1, maximum=5000)

    if ws_id:
        ws = get_ws(request.user, ws_id)
        qs = CodeFile.objects.filter(workspace=ws)
    else:
        qs = file_qs(request.user)

    items = []
    by_tag = {}
    by_file = {}

    for f in qs.only("id", "path", "name", "language", "content", "workspace_id")[:800]:
        content = f.content or ""
        if not any(t in content.upper() for t in ("TODO", "FIXME", "HACK", "XXX", "BUG", "NOTE")):
            continue
        for lineno, line in enumerate(as_lines(content), start=1):
            m = _TODO_RX.search(line)
            if not m:
                continue
            tag = (m.group("tag") or "").upper()
            if only_tag and tag != only_tag:
                continue
            text = (m.group("text") or "").strip()
            # 去掉常见的注释尾巴
            text = re.sub(r"[\s*/#>-]+$", "", text)[:200]
            # 已完成的标记（如 "TODO(done)" 或行尾 ✓）
            done = bool(re.search(r"\b(done|已完成|✓)\b", text, re.I))
            item = {
                "file_id": f.id, "path": f.path, "language": f.language,
                "line": lineno, "tag": tag, "text": text,
                "level": _TAG_LEVEL.get(tag, "info"), "done": done,
            }
            items.append(item)
            by_tag[tag] = by_tag.get(tag, 0) + 1
            by_file[f.path] = by_file.get(f.path, 0) + 1

    # 按严重度排序（high → medium → low → info），同级别按文件+行号
    level_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    items.sort(key=lambda x: (level_order.get(x["level"], 9), x["path"], x["line"]))

    top_files = [
        {"path": p_, "count": c}
        for p_, c in sorted(by_file.items(), key=lambda x: -x[1])[:20]
    ]

    return ok({
        "items": items[:limit],
        "total": len(items),
        "by_tag": [{"tag": t, "count": c}
                   for t, c in sorted(by_tag.items(), key=lambda x: -x[1])],
        "by_file": top_files,
        "scanned_files": qs.count(),
    })


# ============================================================
# 三、Diff 视图（第 78 条）
# ============================================================


@endpoint(("POST",))
def diff_view(request):
    """结构化 diff：两个版本 / 版本对当前 / 两个文件 之间的差异。

    入参三种模式：
    - {file, v1, v2}            同一文件的两个版本
    - {file, version}           某版本 vs 当前内容
    - {file_a, file_b}          两个文件对比
    返回逐段 opcodes，前端可按行号对齐渲染。
    """
    file_id = opt_num(request, "file", None, integer=True)
    v1_id = opt_num(request, "v1", None, integer=True)
    v2_id = opt_num(request, "v2", None, integer=True)
    single_v = opt_num(request, "version", None, integer=True)
    file_a = opt_num(request, "file_a", None, integer=True)
    file_b = opt_num(request, "file_b", None, integer=True)
    context = opt_num(request, "context", 3, integer=True, minimum=0, maximum=50)

    left_label = right_label = ""
    left_text = right_text = ""

    if file_a and file_b:
        fa = get_file(request.user, file_a)
        fb = get_file(request.user, file_b)
        left_text, right_text = fa.content or "", fb.content or ""
        left_label, right_label = fa.path, fb.path

    elif file_id and single_v:
        f = get_file(request.user, file_id)
        v = CodeVersion.objects.filter(file=f, id=single_v).first()
        if not v:
            raise ValueError(f"版本不存在: {single_v}")
        left_text, right_text = v.content or "", f.content or ""
        left_label = f"{f.path} @v{v.id}"
        right_label = f"{f.path} (当前)"

    elif file_id and v1_id and v2_id:
        f = get_file(request.user, file_id)
        va = CodeVersion.objects.filter(file=f, id=v1_id).first()
        vb = CodeVersion.objects.filter(file=f, id=v2_id).first()
        if not va or not vb:
            raise ValueError("指定的版本不存在")
        left_text, right_text = va.content or "", vb.content or ""
        left_label, right_label = f"{f.path} @v{v1_id}", f"{f.path} @v{v2_id}"

    else:
        raise ValueError("请提供 (file, v1, v2) 或 (file, version) 或 (file_a, file_b)")

    lines_a = as_lines(left_text)
    lines_b = as_lines(right_text)

    sm = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)
    hunks = []
    added = removed = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            # 只保留 context 行数的上下文
            seg = lines_a[i1:i2]
            if len(seg) > context * 2:
                head = seg[:context]
                tail = seg[-context:]
                hunks.append({
                    "type": "context", "a_start": i1 + 1, "b_start": j1 + 1,
                    "lines": [{"a": i1 + k + 1, "b": j1 + k + 1, "text": t}
                              for k, t in enumerate(head)],
                })
                hunks.append({
                    "type": "skip", "count": len(seg) - context * 2,
                    "a_start": i1 + context + 1, "b_start": j1 + context + 1,
                })
                hunks.append({
                    "type": "context", "a_start": i1 + len(seg) - context + 1,
                    "b_start": j1 + len(seg) - context + 1,
                    "lines": [{"a": i1 + len(seg) - context + k + 1,
                               "b": j1 + len(seg) - context + k + 1, "text": t}
                              for k, t in enumerate(tail)],
                })
            else:
                hunks.append({
                    "type": "context", "a_start": i1 + 1, "b_start": j1 + 1,
                    "lines": [{"a": i1 + k + 1, "b": j1 + k + 1, "text": t}
                              for k, t in enumerate(seg)],
                })
        elif tag == "replace":
            removed += i2 - i1
            added += j2 - j1
            hunks.append({
                "type": "change", "a_start": i1 + 1, "b_start": j1 + 1,
                "lines": (
                    [{"a": i1 + k + 1, "b": None, "text": t, "kind": "del"}
                     for k, t in enumerate(lines_a[i1:i2])]
                    + [{"a": None, "b": j1 + k + 1, "text": t, "kind": "add"}
                       for k, t in enumerate(lines_b[j1:j2])]
                ),
            })
        elif tag == "delete":
            removed += i2 - i1
            hunks.append({
                "type": "delete", "a_start": i1 + 1, "b_start": j1 + 1,
                "lines": [{"a": i1 + k + 1, "b": None, "text": t, "kind": "del"}
                          for k, t in enumerate(lines_a[i1:i2])],
            })
        elif tag == "insert":
            added += j2 - j1
            hunks.append({
                "type": "insert", "a_start": i1 + 1, "b_start": j1 + 1,
                "lines": [{"a": None, "b": j1 + k + 1, "text": t, "kind": "add"}
                          for k, t in enumerate(lines_b[j1:j2])],
            })

    # 文本形式的 unified diff，方便复制
    unified = "\n".join(difflib.unified_diff(
        lines_a, lines_b, fromfile=left_label or "left",
        tofile=right_label or "right", lineterm="", n=context,
    ))

    return ok({
        "left": {"label": left_label, "lines": len(lines_a)},
        "right": {"label": right_label, "lines": len(lines_b)},
        "hunks": hunks,
        "stats": {
            "added": added, "removed": removed,
            "same": sum(1 for t, *_ in sm.get_opcodes() if t == "equal"),
            "changed": bool(added or removed),
        },
        "unified": unified[:200000],
    })


# ============================================================
# 四、工程洞察（第 76/82 条）
# ============================================================


@endpoint(("GET",))
def insights(request):
    """工作区工程洞察：语言占比 / 文件分布 / 活跃度 / 健康度。

    参数：`workspace` 可选，不传则统计当前用户全部代码资产。
    """
    ws_id = opt_num(request, "workspace", None, integer=True)
    if ws_id:
        ws = get_ws(request.user, ws_id)
        files = CodeFile.objects.filter(workspace=ws)
        run_qs = CodeRun.objects.filter(owner=request.user, workspace=ws)
        label = ws.name
    else:
        files = file_qs(request.user)
        run_qs = CodeRun.objects.filter(owner=request.user)
        label = "全部代码资产"

    total_files = files.count()
    total_bytes = files.aggregate(s=Sum("size"))["s"] or 0
    total_lines = files.aggregate(s=Sum("lines"))["s"] or 0

    # 语言分布
    by_lang = list(
        files.values("language")
        .annotate(count=Count("id"), bytes=Sum("size"), lines=Sum("lines"))
        .order_by("-count")
    )
    lang_total = max(1, total_files)
    languages = [{
        "language": r["language"] or "unknown",
        "count": r["count"],
        "bytes": r["bytes"] or 0,
        "lines": r["lines"] or 0,
        "percent": round(r["count"] * 100 / lang_total),
    } for r in by_lang]

    # 目录分布（按路径前缀，取一级目录）
    dirs = {}
    for f in files.only("id", "path"):
        top = f.path.split("/")[0] if "/" in f.path else "(根目录)"
        dirs[top] = dirs.get(top, 0) + 1
    top_dirs = [
        {"dir": d, "count": c,
         "percent": round(c * 100 / lang_total)}
        for d, c in sorted(dirs.items(), key=lambda x: -x[1])[:15]
    ]

    # 运行活跃度（近 30 天）
    from django.utils import timezone
    import datetime
    today = timezone.localdate()
    start = today - datetime.timedelta(days=29)
    recent_runs = run_qs.filter(created_at__date__gte=start)
    run_days = {}
    for r in recent_runs.only("created_at"):
        d = timezone.localtime(r.created_at).date()
        run_days[d] = run_days.get(d, 0) + 1

    activity = []
    for i in range(29, -1, -1):
        d = today - datetime.timedelta(days=i)
        activity.append({"date": d, "count": run_days.get(d, 0)})

    # 执行成功率
    run_stats = run_qs.aggregate(
        total=Count("id"),
        ok=Count("id", filter=Q(status="ok")),
        err=Count("id", filter=Q(status="error")),
        timeout=Count("id", filter=Q(status="timeout")),
    )
    total_runs = run_stats["total"] or 0
    success_rate = round((run_stats["ok"] or 0) * 100 / total_runs) if total_runs else 0

    # 健康度评分：规模合理性 + 成功率 + 文件粒度
    health = 100
    alerts = []
    if total_files and total_bytes / total_files > 30000:
        health -= 15
        alerts.append("平均文件体积偏大，建议拆分")
    if total_runs and success_rate < 60:
        health -= 25
        alerts.append(f"执行成功率仅 {success_rate}%，建议优先排查报错")
    if (run_stats["timeout"] or 0) > max(3, total_runs * 0.15):
        health -= 10
        alerts.append("超时比例偏高，检查是否有死循环或重计算")
    big = list(files.filter(size__gt=100000).values("id", "path", "size")[:10])
    if big:
        health -= min(15, len(big) * 3)
        alerts.append(f"存在 {len(big)} 个超过 100KB 的文件")
    health = max(0, min(100, health))

    return ok({
        "label": label,
        "summary": {
            "files": total_files, "bytes": total_bytes, "lines": total_lines,
            "workspaces": ws_qs(request.user).count() if not ws_id else 1,
            "runs_30d": recent_runs.count(),
            "success_rate": success_rate,
            "health": health,
        },
        "languages": languages,
        "directories": top_dirs,
        "activity": activity,
        "alerts": alerts,
        "biggest": [{"id": b["id"], "path": b["path"], "size": b["size"]} for b in big],
    })


@endpoint(("GET",))
def contributors(request):
    """工作区贡献者统计（第 80 条的汇总视图）。

    按版本快照的创建者聚合：每人贡献了多少次快照、涉及多少文件。
    这是"谁在这个工程里干活"的直观答案。
    """
    ws_id = opt_num(request, "workspace", None, integer=True)
    if ws_id:
        ws = get_ws(request.user, ws_id)
        files = CodeFile.objects.filter(workspace=ws)
        label = ws.name
    else:
        files = file_qs(request.user)
        label = "全部代码资产"

    versions = (
        CodeVersion.objects
        .filter(file__in=files)
        .values("created_by_id", "created_by__username")
        .annotate(
            snapshots=Count("id"),
            bytes=Sum("size"),
        )
        .order_by("-snapshots")
    )

    total = sum(v["snapshots"] for v in versions) or 1
    items = [{
        "user_id": v["created_by_id"],
        "username": v["created_by__username"] or "未知",
        "snapshots": v["snapshots"],
        "bytes": v["bytes"] or 0,
        "percent": round(v["snapshots"] * 100 / total),
        "is_me": v["created_by_id"] == request.user.id,
    } for v in versions]

    # 每个贡献者涉及的文件数
    for it in items:
        it["files"] = (
            CodeVersion.objects
            .filter(file__in=files, created_by_id=it["user_id"])
            .values("file_id").distinct().count()
        )

    return ok({
        "label": label,
        "items": items,
        "total_snapshots": sum(v["snapshots"] for v in versions),
        "contributor_count": len(items),
    })


# ============================================================
# 五、文件粒度 diff（第 79 条：单文件两个版本并排）
# ============================================================


@endpoint(("GET",))
def version_side_by_side(request, pk, vid):
    """把某个版本与当前内容做并排对比（行号对齐的简化结构）。"""
    f = get_file(request.user, pk)
    v = CodeVersion.objects.filter(file=f, id=vid).first()
    if not v:
        raise ValueError(f"版本不存在: {vid}")

    a = as_lines(v.content or "")
    b = as_lines(f.content or "")
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)

    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({
                    "a": i1 + k + 1, "b": j1 + k + 1,
                    "left": a[i1 + k], "right": b[j1 + k], "kind": "same",
                })
        elif tag == "replace":
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                li = i1 + k
                ri = j1 + k
                rows.append({
                    "a": li + 1 if li < i2 else None,
                    "b": ri + 1 if ri < j2 else None,
                    "left": a[li] if li < i2 else "",
                    "right": b[ri] if ri < j2 else "",
                    "kind": "change",
                })
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"a": k + 1, "b": None, "left": a[k], "right": "", "kind": "del"})
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"a": None, "b": k + 1, "left": "", "right": b[k], "kind": "add"})

    return ok({
        "file": {"id": f.id, "path": f.path, "language": f.language},
        "version": {"id": v.id, "message": v.message, "created_at": v.created_at},
        "rows": rows,
        "stats": {
            "left_lines": len(a), "right_lines": len(b),
            "added": sum(1 for r in rows if r["kind"] == "add"),
            "removed": sum(1 for r in rows if r["kind"] == "del"),
            "changed": sum(1 for r in rows if r["kind"] == "change"),
        },
    })
