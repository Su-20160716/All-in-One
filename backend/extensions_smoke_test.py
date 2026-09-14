# -*- coding: utf-8 -*-
"""扩展功能冒烟测试：全文搜索 / 双链 / 组织架构与数据权限 / 多租户 /
文件预览与 Range 流式 / Office 转 PDF 适配器 / AI 摘要问答出题批改 / Yjs 协同

用法（在 backend 目录）：
    python extensions_smoke_test.py

特点：全部通过真实 HTTP 接口（APIClient）打，WebSocket 部分用 Channels 的
WebsocketCommunicator 真连 ASGI 应用，不做任何 mock。
"""
import asyncio
import os
import sys
import time
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, extra=""):
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {extra}" if extra and not ok else ""))


def section(title):
    print(f"\n=== {title} ===")


def login(username, password):
    c = APIClient()
    r = c.post("/api/auth/login/", {"username": username, "password": password}, format="json")
    assert r.status_code == 200, f"登录失败 {r.status_code} {r.data}"
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    return c, r.data["user"]


def main():
    ts = int(time.time())
    admin, admin_user = login("admin", "admin123")

    # ------------------------------------------------------------------
    section("1. 双链 [[wiki link]]")
    # ------------------------------------------------------------------
    target = admin.post("/api/notes/", {"title": f"目标笔记{ts}", "content": "被引用的内容"}, format="json")
    check("创建目标笔记", target.status_code == 201)
    tid = target.data["id"]

    ghost_title = f"还不存在的笔记{ts}"
    src = admin.post("/api/notes/", {
        "title": f"来源笔记{ts}",
        "content": f"参考 [[目标笔记{ts}]] 以及 [[{ghost_title}|另一个名字]] 的内容",
    }, format="json")
    check("创建含双链的来源笔记", src.status_code == 201)
    sid = src.data["id"]

    r = admin.get(f"/api/notes/{tid}/backlinks/")
    backlinks = r.data.get("backlinks", []) if r.status_code == 200 else []
    check("反向链接命中来源笔记", r.status_code == 200 and any(b["note_id"] == sid for b in backlinks),
          str(r.data)[:200])

    r = admin.get(f"/api/notes/{sid}/backlinks/")
    check("来源笔记的出链计数正确（2 条 [[ ]]）", r.data.get("outgoing_count", 0) >= 2, str(r.data)[:200])
    check("目标笔记无出链", admin.get(f"/api/notes/{tid}/backlinks/").data.get("outgoing_count", -1) == 0)

    r = admin.get(f"/api/notes/{sid}/")
    out = r.data.get("outgoing_links", []) if r.status_code == 200 else []
    resolved = [o for o in out if o.get("resolved")]
    unresolved = [o for o in out if not o.get("resolved")]
    check("出链区分已解析/悬浮链接", len(resolved) >= 1 and len(unresolved) >= 1, str(out)[:200])

    r = admin.get("/api/notes/dangling/")
    dangling = [d["title"] for d in r.data.get("list", [])] if r.status_code == 200 else []
    check("悬浮链接汇总包含未创建标题", ghost_title in dangling, str(dangling)[:200])

    r = admin.post("/api/notes/from-title/", {"title": ghost_title}, format="json")
    check("按标题补建笔记", r.status_code in (200, 201), str(r.data)[:150])

    r = admin.get("/api/notes/dangling/")
    dangling2 = [d["title"] for d in r.data.get("list", [])] if r.status_code == 200 else []
    check("补建后悬浮链接自动接上", ghost_title not in dangling2, str(dangling2)[:200])

    r = admin.get("/api/notes/graph/")
    check("双链图谱返回节点与边",
          r.status_code == 200 and r.data.get("node_count", 0) >= 2 and r.data.get("edge_count", 0) >= 1,
          str(r.data)[:200])

    r = admin.get("/api/notes/link-suggest/", {"q": "目标笔记"})
    check("[[ 标题联想可用", r.status_code == 200 and len(r.data.get("list", [])) >= 1, str(r.data)[:150])

    r = admin.post("/api/notes/links/rebuild/", {}, format="json")
    check("双链重建接口可用", r.status_code == 200, str(r.data)[:150])

    # ------------------------------------------------------------------
    section("2. 全文搜索（中文分词 + BM25）")
    # ------------------------------------------------------------------
    marker = f"独特关键词{uuid.uuid4().hex[:6]}"
    r = admin.post("/api/notes/", {
        "title": f"搜索测试笔记{ts}",
        "content": f"这是一篇用于验证全文检索的笔记，包含{marker}以及协同编辑相关内容。"
                   f"{marker}重复出现以便观察词频加权效果。",
    }, format="json")
    search_note_id = r.data["id"]

    r = admin.get("/api/core/search/fulltext/", {"q": marker})
    hits = r.data.get("results", []) if r.status_code == 200 else []
    check("中文关键词全文检索命中", r.status_code == 200 and any(h["id"] == search_note_id for h in hits),
          str(r.data)[:250])
    check("检索结果带高亮摘要", any("<em>" in (h.get("snippet") or "") or marker in (h.get("snippet") or "")
                                    for h in hits), str(hits)[:200])
    check("检索返回耗时统计", isinstance(r.data.get("took_ms"), int))

    r = admin.get("/api/core/search/fulltext/", {"q": "协同编辑"})
    check("多字中文词（bigram）可检索", r.status_code == 200 and r.data.get("total", 0) >= 1, str(r.data)[:200])

    r = admin.get("/api/core/search/fulltext/", {"q": marker, "module": "note"})
    check("按模块过滤检索", r.status_code == 200 and all(h["module"] == "note" for h in r.data["results"]))

    r = admin.get("/api/core/search/suggest/", {"q": marker[:4]})
    check("检索词联想可用", r.status_code == 200 and isinstance(r.data.get("list"), list), str(r.data)[:150])

    r = admin.get("/api/core/search/stats/")
    check("索引概况可用（含各模块分布）",
          r.status_code == 200 and r.data.get("documents", 0) > 0 and len(r.data.get("by_module", [])) >= 1,
          str(r.data)[:200])

    r = admin.post("/api/core/search/reindex/", {"scope": "own", "modules": ["note"]}, format="json")
    check("重建索引接口可用", r.status_code == 200 and r.data.get("indexed", 0) >= 1, str(r.data)[:200])

    # 索引命中：文件内容
    r = admin.post("/api/files/create-text/", {
        "name": f"检索测试文本{ts}.txt",
        "content": f"文件正文里也藏着关键词 {marker} 用于验证文件内容索引。",
    }, format="json")
    check("创建文本文件", r.status_code in (200, 201), str(r.data)[:150])
    file_id = r.data.get("file", {}).get("id") or r.data.get("id")
    r = admin.get("/api/core/search/fulltext/", {"q": marker, "module": "file"})
    check("文件正文进入索引并可检索",
          r.status_code == 200 and any(h["id"] == file_id for h in r.data.get("results", [])),
          str(r.data)[:250])

    # ------------------------------------------------------------------
    section("3. 组织架构 / 数据范围 / 多租户")
    # ------------------------------------------------------------------
    r = admin.post("/api/auth/admin/tenants/", {"name": f"测试租户{ts}", "code": f"t{ts}"}, format="json")
    check("创建租户", r.status_code == 201, str(r.data)[:150])
    tenant_id = r.data.get("id")

    r = admin.get("/api/auth/admin/tenants/")
    check("租户列表", r.status_code == 200 and r.data.get("total", 0) >= 1)

    r = admin.post("/api/auth/admin/departments/", {"name": f"测试部门{ts}", "tenant": tenant_id,
                                                   "code": f"d{ts}"}, format="json")
    check("创建部门", r.status_code == 201, str(r.data)[:150])
    dept_id = r.data.get("id")

    r = admin.post("/api/auth/admin/departments/", {"name": f"子部门{ts}", "parent": dept_id}, format="json")
    check("创建子部门", r.status_code == 201, str(r.data)[:150])
    child_id = r.data.get("id")

    r = admin.get("/api/auth/admin/departments/")
    tree = r.data.get("tree", []) if r.status_code == 200 else []
    check("部门树返回嵌套 children", r.status_code == 200 and len(tree) >= 1)

    r = admin.get(f"/api/auth/admin/departments/{dept_id}/")
    check("部门详情含下级 id 列表", r.status_code == 200 and child_id in r.data.get("descendant_ids", []),
          str(r.data)[:200])

    r = admin.patch(f"/api/auth/admin/departments/{dept_id}/", {"parent": child_id}, format="json")
    check("阻止把部门移动到自己的下级（防环）", r.status_code == 400, str(r.data)[:150])

    r = admin.patch(f"/api/auth/admin/departments/{child_id}/", {"name": f"子部门改名{ts}", "sort": 5},
                    format="json")
    check("编辑部门", r.status_code == 200 and r.data.get("name") == f"子部门改名{ts}", str(r.data)[:150])

    r = admin.post("/api/auth/admin/roles/", {
        "name": f"部门主管{ts}", "code": f"lead{ts}", "data_scope": "dept_and_sub",
        "description": "能看到本部门及下级数据",
    }, format="json")
    check("创建角色并设置数据范围", r.status_code == 201 and r.data.get("data_scope") == "dept_and_sub",
          str(r.data)[:200])
    role_id = r.data.get("id")

    r = admin.patch(f"/api/auth/admin/roles/{role_id}/", {"data_scope": "all"}, format="json")
    check("修改角色数据范围", r.status_code == 200 and r.data.get("data_scope") == "all", str(r.data)[:150])

    r = admin.get("/api/auth/admin/roles/")
    scopes = {role["code"]: role["data_scope"] for role in r.data.get("list", [])}
    check("内置管理员角色数据范围为 all", scopes.get("admin") == "all", str(scopes)[:200])
    check("普通用户角色仍为 self（不改变既有可见性）", scopes.get("user", "self") == "self", str(scopes)[:200])

    r = admin.get("/api/auth/me/scope/")
    check("我的数据范围说明", r.status_code == 200 and r.data.get("scope") == "all", str(r.data)[:200])

    # 新建用户并归属部门
    uname = f"orguser{ts}"
    r = admin.post("/api/auth/admin/users/create/", {
        "username": uname, "password": "orgpass123", "nickname": "部门成员",
        "department": dept_id,
    }, format="json")
    check("创建用户并指定部门", r.status_code == 201, str(r.data)[:200])
    new_uid = r.data.get("user", {}).get("id")
    r = admin.get(f"/api/auth/admin/users/{new_uid}/")
    check("用户详情带部门与数据范围", r.status_code == 200 and r.data.get("data_scope") in
          ("self", "dept", "dept_and_sub", "all"), str(r.data)[:200])

    # 数据范围隔离验证：新用户（self）看不到 admin 的笔记
    member, _ = login(uname, "orgpass123")
    r = member.get("/api/notes/", {"all": "1"})
    own_ids = [n["id"] for n in r.data.get("list", [])] if r.status_code == 200 else []
    check("普通用户（self）看不到他人笔记", search_note_id not in own_ids, str(own_ids)[:200])
    r = member.get(f"/api/notes/{search_note_id}/")
    check("普通用户访问他人笔记详情被拒", r.status_code == 404, f"status={r.status_code}")

    # admin（all）能看到成员的笔记 → 反向验证数据范围确实放宽
    r = member.post("/api/notes/", {"title": f"成员笔记{ts}", "content": "成员自己的内容"}, format="json")
    member_note_id = r.data["id"]
    r = admin.get("/api/notes/", {"all": "1"})
    admin_ids = [n["id"] for n in r.data.get("list", [])] if r.status_code == 200 else []
    check("管理员（all）可见成员笔记", member_note_id in admin_ids, str(admin_ids)[-10:])

    # ------------------------------------------------------------------
    section("4. 文件预览 / Range 流式 / Office 转 PDF")
    # ------------------------------------------------------------------
    r = admin.get(f"/api/files/{file_id}/preview/")
    check("文本文件预览返回正文与类型",
          r.status_code == 200 and r.data.get("preview_type") == "text" and marker in r.data.get("content", ""),
          str(r.data)[:200])

    r = admin.get(f"/api/files/{file_id}/raw/", HTTP_RANGE="bytes=0-9")
    body = b"".join(r.streaming_content) if getattr(r, "streaming_content", None) is not None else b""
    check("Range 请求返回 206 Partial Content", r.status_code == 206, f"status={r.status_code}")
    check("Range 响应带 Content-Range", "Content-Range" in r.headers, str(dict(r.headers))[:200])
    check("Range 响应带 Accept-Ranges", r.headers.get("Accept-Ranges") == "bytes")
    check("Range 分片长度正确", len(body) == 10, f"len={len(body)}")

    r = admin.get(f"/api/files/{file_id}/raw/")
    full = b"".join(r.streaming_content) if getattr(r, "streaming_content", None) is not None else b""
    check("非 Range 请求返回完整内容", r.status_code == 200 and len(full) > 10, f"len={len(full)}")

    r = admin.get(f"/api/files/{file_id}/raw/", HTTP_RANGE="bytes=99999999-")
    check("越界 Range 返回 416", r.status_code == 416, f"status={r.status_code}")

    r = admin.get("/api/files/office-capability/")
    check("Office 能力探测返回安装状态与指引",
          r.status_code == 200 and "installed" in r.data and ("hint" in r.data),
          str(r.data)[:200])
    office_installed = bool(r.data.get("installed"))

    # 用 .docx 文件名模拟 Office 文档（内容仍是文本，只为验证分支与降级路径）
    r = admin.post("/api/files/create-text/", {"name": f"假Office文档{ts}.docx", "content": "office"}, format="json")
    office_file_id = r.data.get("file", {}).get("id") or r.data.get("id")
    r = admin.get(f"/api/files/{office_file_id}/preview/")
    check("Office 文件预览走 office 分支",
          r.status_code == 200 and r.data.get("preview_type") == "office", str(r.data)[:200])
    r = admin.post(f"/api/files/{office_file_id}/to-pdf/", {}, format="json")
    if office_installed:
        check("Office 转 PDF 成功", r.status_code == 200 and r.data.get("ok"), str(r.data)[:200])
    else:
        check("未装 LibreOffice 时返回结构化降级提示（不报 500）",
              r.status_code == 200 and r.data.get("code") == "LIBREOFFICE_NOT_FOUND",
              str(r.data)[:250])

    # ------------------------------------------------------------------
    section("5. AI 摘要 / 问答 / 聊天 / 出题 / 批改")
    # ------------------------------------------------------------------
    r = admin.get("/api/assistant/status/")
    check("AI 状态接口", r.status_code == 200 and "configured" in r.data, str(r.data)[:200])
    ai_provider = r.data.get("provider")
    print(f"    · 当前 AI 提供方：{ai_provider}（{'大模型' if ai_provider == 'llm' else '本地降级'}）")

    long_note = admin.post("/api/notes/", {
        "title": f"AI 摘要测试{ts}",
        "content": ("协同编辑系统需要解决冲突合并问题。CRDT 是一种无中心的数据结构，"
                    "它保证不同副本在任意顺序收到更新后都能收敛到一致状态。"
                    "Yjs 是 JavaScript 生态中最流行的 CRDT 实现之一，支持文本、数组与映射类型。"
                    "在服务端只需要做更新中继与快照持久化，真正的合并发生在客户端。"
                    "这样可以避免在服务端引入复杂的 CRDT 依赖，同时保持最终一致性。"
                    "全文搜索需要中文分词，bigram 是一种无需词典的简单方案。") * 2,
    }, format="json")
    ai_note_id = long_note.data["id"]

    r = admin.post(f"/api/assistant/notes/{ai_note_id}/summarize/", {"force": True}, format="json")
    check("笔记 AI 摘要生成", r.status_code == 200 and len(r.data.get("summary", "")) > 20, str(r.data)[:250])
    check("摘要返回关键要点", isinstance(r.data.get("key_points"), list), str(r.data.get("key_points"))[:150])
    check("摘要标注提供方", r.data.get("provider") in ("llm", "local"), str(r.data.get("provider")))

    r = admin.get(f"/api/assistant/notes/{ai_note_id}/summarize/")
    check("摘要结果被缓存", r.status_code == 200 and r.data.get("cached") is True, str(r.data)[:150])

    r = admin.post(f"/api/assistant/notes/{ai_note_id}/ask/", {"question": "服务端需要做 CRDT 合并吗？"},
                   format="json")
    check("笔记 AI 问答返回答案", r.status_code == 200 and len(r.data.get("answer", "")) > 5, str(r.data)[:250])
    check("问答返回引用来源", isinstance(r.data.get("references"), list), str(r.data.get("references"))[:150])

    r = admin.post("/api/assistant/ask/", {"question": "全文搜索怎么做中文分词？"}, format="json")
    check("跨笔记问答可用", r.status_code in (200, 404), str(r.data)[:200])

    r = admin.post("/api/assistant/chat/", {"message": "帮我总结一下 CRDT 的核心思想"}, format="json")
    check("聊天助手返回回复", r.status_code == 200 and len(r.data.get("reply", "")) > 5, str(r.data)[:250])
    conv_id = r.data.get("conversation_id")
    r = admin.get(f"/api/assistant/conversations/{conv_id}/")
    check("会话历史已持久化", r.status_code == 200 and len(r.data.get("messages", [])) >= 2,
          str(r.data)[:200])

    r = admin.post("/api/assistant/questions/generate/", {
        "topic": "一元二次方程", "count": 3, "type": "single", "difficulty": 2, "subject": "math",
    }, format="json")
    check("AI 出题返回题目列表",
          r.status_code == 200 and r.data.get("count", 0) >= 1 and len(r.data.get("items", [])) >= 1,
          str(r.data)[:250])
    check("出题带来源标注（llm/bank）", r.data.get("source") in ("llm", "bank"),
          str(r.data.get("source")))
    first_q = (r.data.get("items") or [{}])[0]
    check("单选题含选项与答案", bool(first_q.get("options")) and first_q.get("answer") != "",
          str(first_q)[:200])

    r = admin.post("/api/assistant/questions/generate/", {
        "topic": "Python 列表推导式", "count": 2, "type": "code", "save": False,
    }, format="json")
    check("编程题出题可用", r.status_code == 200 and r.data.get("count", 0) >= 1, str(r.data)[:200])

    r = admin.get("/api/assistant/questions/")
    check("已生成题目可查询", r.status_code == 200 and r.data.get("total", 0) >= 1, str(r.data)[:150])

    r = admin.post("/api/assistant/grade/", {
        "items": [
            {"question": "简述 CRDT 为什么能做到最终一致",
             "reference_answer": "CRDT 通过可交换、可结合、幂等的操作设计，使不同副本以任意顺序应用更新后都能收敛到同一状态，因此无需中心协调即可最终一致。",
             "user_answer": "因为它把操作设计成可交换、幂等，副本按任意顺序应用更新都能收敛到同一状态。",
             "type": "subjective", "topic": "分布式"},
            {"question": "计算 25 × 4 ÷ 25 × 4", "reference_answer": "16", "user_answer": "16",
             "type": "fill"},
        ],
        "record_mistakes": False,
    }, format="json")
    check("AI 批改返回评分与评语",
          r.status_code == 200 and r.data.get("total") == 2 and r.data.get("average_score") is not None,
          str(r.data)[:250])
    items = r.data.get("items", [])
    check("客观题判分正确", items and items[1].get("score") == 100, str(items[1] if items else {})[:150])
    check("主观题给出分值区间", items and 0 <= items[0].get("score", -1) <= 100, str(items[0] if items else {})[:150])
    check("主观题列出缺失要点字段", "missing_points" in (items[0] if items else {}), str(items[0] if items else {})[:150])
    check("批改标注提供方", r.data.get("provider") in ("llm", "local"), str(r.data.get("provider")))

    r = admin.post("/api/assistant/grade/", {
        "items": [{"question": "解释一致性哈希", "reference_answer": "环形空间、虚拟节点、最小重映射",
                   "user_answer": "没学过", "type": "subjective", "topic": "分布式"}],
        "record_mistakes": True,
    }, format="json")
    check("错题写入错题本闭环", r.status_code == 200 and r.data.get("recorded_mistakes", 0) >= 1,
          str(r.data)[:200])

    return {"note_id": ai_note_id, "admin_user": admin_user, "search_note": search_note_id}


def ws_collab_test(note_id, username="admin"):
    """Yjs 协同 WebSocket 真连测试"""
    from channels.testing import WebsocketCommunicator
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import RefreshToken

    from config.asgi import application

    User = get_user_model()
    user = User.objects.get(username=username)
    token = str(RefreshToken.for_user(user).access_token)

    async def run():
        results = {}
        comm = WebsocketCommunicator(application, f"/ws/notes/{note_id}/?token={token}")
        connected, _ = await comm.connect()
        results["connected"] = connected
        if not connected:
            return results
        init = await comm.receive_json_from(timeout=10)
        results["init_type"] = init.get("type")
        results["init_data"] = init.get("data", {})

        await comm.send_json_to({"type": "ping"})
        pong = await comm.receive_json_from(timeout=10)
        results["pong"] = pong.get("type")

        await comm.send_json_to({"type": "yjs.update", "update": "AAECAwQ="})
        await comm.send_json_to({"type": "yjs.snapshot", "snapshot": "AAECAwQFBgc=",
                                 "text": "协同写入的正文内容，用于验证快照回写与索引联动。"})
        results["sent"] = True

        # 未带 token 的连接应被拒绝
        bad = WebsocketCommunicator(application, f"/ws/notes/{note_id}/")
        ok, _ = await bad.connect()
        results["unauthorized_rejected"] = not ok
        await bad.disconnect()
        await comm.disconnect()
        return results

    return asyncio.run(run())


def main_ws(info):
    section("6. 笔记实时协同（Yjs over WebSocket）")
    try:
        res = ws_collab_test(info["note_id"], info["admin_user"]["username"])
    except Exception as exc:
        check("协同 WebSocket 连接", False, f"{type(exc).__name__}: {exc}")
        return
    check("携带 JWT 的 WebSocket 连接成功（修复了原 Session-only 认证）", res.get("connected") is True)
    check("连接后下发初始状态 collab.init", res.get("init_type") == "collab.init", str(res)[:200])
    check("初始状态含快照/增量/修订号字段",
          all(k in (res.get("init_data") or {}) for k in ("snapshot", "updates", "revision")),
          str(res.get("init_data"))[:200])
    check("心跳 ping/pong 正常", res.get("pong") == "pong", str(res.get("pong")))
    check("未认证连接被拒绝", res.get("unauthorized_rejected") is True, str(res.get("unauthorized_rejected")))

    # 验证快照回写笔记正文
    admin, _ = login("admin", "admin123")
    r = admin.get(f"/api/notes/{info['note_id']}/")
    check("协同快照已回写笔记正文", r.status_code == 200 and "协同写入的正文" in r.data.get("content", ""),
          str(r.data.get("content"))[:150])
    r = admin.get("/api/core/search/fulltext/", {"q": "协同写入"})
    check("协同写入内容已进入全文索引",
          r.status_code == 200 and any(h["id"] == info["note_id"] for h in r.data.get("results", [])),
          str(r.data)[:200])


if __name__ == "__main__":
    info = main()
    main_ws(info)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：")
        for name in FAILED:
            print("  -", name)
    sys.exit(1 if FAILED else 0)
