# -*- coding: utf-8 -*-
"""workflow 冒烟测试：串行跑通流程引擎的完整业务链路。

覆盖：目录 → 定义创建/整图保存/校验/发布 → 发起实例 → 待办认领与审批 →
决策分支 → 评论/变量/附件/快照/时间线/回放 → 监控指标/SLA 扫描 →
委托/通知/审计 → Webhook/SLA 策略/表达式 → 版本二次发布/对比/回滚 →
克隆/导出/导入 → 越权边界。

运行：venv/Scripts/python.exe workflow_smoke_test.py
说明：真实写入 db.sqlite3，结束时不清库，便于复现失败现场。
"""
import os
import sys
import time
from datetime import timedelta

import django

# Windows 控制台默认 GBK，输出 ✓/✗ 会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# 冒烟一轮几百次请求会撞线上限流，这里仅在测试进程内放宽，
# 避免 429 掩盖真实业务失败（不影响线上配置）。
from django.conf import settings as dj_settings  # noqa: E402
from rest_framework.settings import api_settings  # noqa: E402

dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
    {"user": "1000000/min", "anon": "1000000/min"}
)
api_settings.DEFAULT_THROTTLE_RATES.update(
    dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
)

from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

BASE = "/api/workflow/"
passed, failed = [], []


def check(name, cond, extra=""):
    """记录一项断言结果，失败时打印响应摘要方便定位。"""
    if cond:
        passed.append(name)
    else:
        failed.append(name)
        print(f"  ✗ {name} {extra}")


def brief(resp, limit=200):
    """响应摘要（统一响应体里的 error 优先展示）。"""
    try:
        body = resp.data
    except Exception:  # noqa: BLE001
        body = ""
    return f"[{resp.status_code}] {str(body)[:limit]}"


def register(client, username, password="test12345"):
    """注册并直接返回带 Bearer 令牌的客户端。"""
    resp = client.post(
        "/api/auth/register/", {"username": username, "password": password}, format="json"
    )
    if resp.status_code not in (200, 201) or not getattr(resp, "data", {}).get("access"):
        return None, resp
    token = resp.data["access"]
    authed = APIClient()
    authed.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return authed, resp


def ok_data(resp):
    """取统一响应里的 data（失败或非对象返回 {}）。"""
    try:
        if resp.data.get("ok"):
            data = resp.data.get("data")
            if isinstance(data, (dict, list)):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def list_items(data):
    """列表接口统一为 items，这里做一次兜底避免 KeyError。"""
    return data.get("items") or []


def find_task(client, instance_id, name_prefix=""):
    """从我的待办里挑出指定实例的任务（冒烟里每人同时只跑一个流程）。"""
    data = ok_data(client.get(BASE + "tasks/my-pending/", {"page_size": 100}))
    for item in list_items(data):
        if item.get("instance_id") == instance_id:
            if not name_prefix or str(item.get("name", "")).startswith(name_prefix):
                return item
    return None


def main():
    ts = int(time.time())
    user_a = f"wf{ts}a"
    user_b = f"wf{ts}b"

    ca, resp = register(APIClient(), user_a)
    check("注册发起人", ca is not None, brief(resp))
    if ca is None:
        raise SystemExit(1)
    cb, resp = register(APIClient(), user_b)
    check("注册审批人", cb is not None, brief(resp))
    if cb is None:
        raise SystemExit(1)
    # 审批人 id 直接取注册响应：node-options 候选人按 id 截取前 200，
    # 开发库用户超 200 时新注册用户不在下拉里，不能依赖它取 id。
    approver_id = (resp.data.get("user") or {}).get("id")
    check("审批人 ID 可取", bool(approver_id), brief(resp))
    if not approver_id:
        raise SystemExit(1)

    # ---------- 1. 目录 ----------
    resp = ca.get(BASE + "catalog/")
    catalog = ok_data(resp)
    check("流程目录", resp.status_code == 200 and catalog.get("endpoint_count", 0) >= 70,
          brief(resp))
    check("目录能力域", len(catalog.get("domains") or []) >= 5,
          str(catalog.keys())[:120])
    check("表达式语法说明", bool(catalog.get("expression")), str(catalog.keys())[:120])

    # ---------- 2. 定义 / 设计器 ----------
    code = f"wf_smoke_{ts}"
    resp = ca.post(BASE + "definitions/create/", {
        "code": code, "name": f"冒烟审批流程{ts}", "category": "冒烟",
        "description": "workflow_smoke_test 自动创建",
    }, format="json")
    definition = ok_data(resp)
    definition_id = definition.get("id")
    check("创建定义", resp.status_code == 200 and bool(definition_id), brief(resp))
    if not definition_id:
        raise SystemExit(1)

    options = ok_data(ca.get(f"{BASE}definitions/{definition_id}/node-options/"))
    # node-options 候选人按 id 截取前 200（下拉规模上限），不保证含最新注册用户；
    # 这里只校验选项契约：返回候选用户、节点类型与办理人类型。审批人 id 取自注册响应。
    check("设计器选项含审批人", bool(options.get("users")) and
          bool(options.get("node_types")) and bool(options.get("assignee_types")),
          str(options.keys())[:120])

    nodes = [
        {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
        {"key": "apply", "name": "主管审批", "node_type": "task", "assignee_type": "user",
         "assignee_rule": {"user_ids": [approver_id]}, "sla_minutes": 120},
        {"key": "decide", "name": "金额判断", "node_type": "decision", "assignee_type": "none"},
        {"key": "high", "name": "大额复核", "node_type": "task", "assignee_type": "user",
         "assignee_rule": {"user_ids": [approver_id]}},
        {"key": "low", "name": "普通归档", "node_type": "task", "assignee_type": "user",
         "assignee_rule": {"user_ids": [approver_id]}},
        {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
    ]
    transitions = [
        {"from": "start", "to": "apply"},
        {"from": "apply", "to": "decide"},
        {"from": "decide", "to": "high", "condition": "amount >= 5000", "priority": 10},
        {"from": "decide", "to": "low", "is_default": True, "priority": 20},
        {"from": "high", "to": "end"},
        {"from": "low", "to": "end"},
    ]
    resp = ca.post(f"{BASE}definitions/{definition_id}/graph/save/", {
        "nodes": nodes, "transitions": transitions,
    }, format="json")
    saved = ok_data(resp)
    check("整图保存", resp.status_code == 200 and saved.get("saved"), brief(resp))
    check("保存即校验", bool((saved.get("validation") or {}).get("valid")), brief(resp))

    checked = ok_data(ca.get(f"{BASE}definitions/{definition_id}/validate/"))
    check("显式校验", checked.get("valid") is True, str(checked.get("errors"))[:160])
    check("节点统计", (checked.get("stats") or {}).get("node_count") == 6, brief(resp))

    graph = ok_data(ca.get(f"{BASE}definitions/{definition_id}/graph/"))
    check("读回整图", len(graph.get("nodes") or []) == 6 and
          len(graph.get("transitions") or []) == 6, str(graph.keys())[:120])

    # 非法图必须被拒绝：悬空连线
    resp = ca.post(f"{BASE}definitions/{definition_id}/graph/save/", {
        "nodes": nodes, "transitions": transitions + [{"from": "end", "to": "ghost"}],
    }, format="json")
    check("非法连线被拒绝", resp.status_code == 400, brief(resp))

    resp = ca.post(f"{BASE}definitions/{definition_id}/publish/", {"note": "首次发布"},
                   format="json")
    published = ok_data(resp)
    check("发布 v1", resp.status_code == 200 and
          (published.get("version") or {}).get("version_no") == 1, brief(resp))
    check("发布后状态", (published.get("definition") or {}).get("status") == "published",
          brief(resp))

    # ---------- 3. 发起与审批 ----------
    resp = ca.post(BASE + "instances/start/", {
        "definition_id": definition_id, "title": f"冒烟报销{ts}",
        "business_no": f"SMOKE-{ts}", "context": {"amount": 8000, "days": 3},
        "variables": {"amount": 8000}, "priority": "high",
    }, format="json")
    instance = ok_data(resp)
    instance_id = instance.get("id")
    check("发起实例", resp.status_code == 200 and instance_id and
          instance.get("status") == "running", brief(resp))
    if not instance_id:
        raise SystemExit(1)

    pending = ok_data(cb.get(BASE + "tasks/my-pending/", {"page_size": 50}))
    check("审批人待办", pending.get("count", 0) >= 1, brief(resp))
    task = find_task(cb, instance_id, "主管审批")
    check("首节点任务", task is not None and task.get("status") == "claimed",
          str(pending)[:160])

    if task:
        detail = ok_data(cb.get(f"{BASE}tasks/{task['id']}/"))
        check("任务详情", detail.get("id") == task["id"] and detail.get("instance_id") == instance_id,
              brief(resp))
        check("任务可办理", detail.get("can_operate") is True, str(detail.keys())[:160])
        resp = cb.post(f"{BASE}tasks/{task['id']}/complete/", {
            "action": "approve", "comment": "主管同意", "payload": {"score": 90},
        }, format="json")
        first_done = ok_data(resp)
        check("主管审批通过", resp.status_code == 200 and
              (first_done.get("instance") or {}).get("status") == "running", brief(resp))

    high_task = find_task(cb, instance_id, "大额复核")
    check("条件分支命中大额", high_task is not None,
          str(ok_data(cb.get(BASE + "tasks/my-pending/")))[:160])

    # ---------- 4. 评论 / 变量 / 附件 / 快照 / 时间线 ----------
    resp = ca.post(f"{BASE}instances/{instance_id}/comments/create/", {
        "content": "请尽快处理", "kind": "comment",
    }, format="json")
    check("新增评论", resp.status_code == 200, brief(resp))

    resp = ca.post(f"{BASE}instances/{instance_id}/variables/set/", {
        "variables": {"amount": 8000, "urgent": True, "note": "冒烟测试"},
    }, format="json")
    variables_saved = ok_data(resp)
    check("写入变量", resp.status_code == 200 and variables_saved.get("count") == 3, brief(resp))

    resp = ca.get(f"{BASE}instances/{instance_id}/variables/")
    check("读取变量", ok_data(resp).get("count") == 3, brief(resp))

    resp = ca.post(f"{BASE}instances/{instance_id}/attachments/create/", {
        "name": "发票.pdf", "url": "/files/smoke-invoice.pdf", "size": 2048,
        "mime": "application/pdf",
    }, format="json")
    check("登记附件", resp.status_code == 200 and ok_data(resp).get("name") == "发票.pdf",
          brief(resp))

    resp = ca.post(f"{BASE}instances/{instance_id}/snapshots/create/", {}, format="json")
    check("创建快照", resp.status_code == 200 and bool(ok_data(resp).get("id")), brief(resp))

    resp = ca.get(f"{BASE}instances/{instance_id}/timeline/")
    timeline = ok_data(resp)
    check("实例时间线", resp.status_code == 200 and len(timeline.get("items") or []) >= 3,
          brief(resp))

    resp = ca.get(f"{BASE}instances/{instance_id}/replay/")
    replay = ok_data(resp)
    check("实例回放", resp.status_code == 200 and len(replay.get("frames") or []) >= 1,
          brief(resp))

    resp = ca.get(f"{BASE}instances/{instance_id}/snapshots/")
    check("快照列表", ok_data(resp).get("count", 0) >= 1, brief(resp))

    # ---------- 5. 完成剩余任务 ----------
    if high_task:
        resp = cb.post(f"{BASE}tasks/{high_task['id']}/complete/", {
            "action": "approve", "comment": "大额复核通过",
        }, format="json")
        check("完成大额复核", resp.status_code == 200 and
              (ok_data(resp).get("instance") or {}).get("status") == "completed", brief(resp))

    resp = ca.get(f"{BASE}instances/{instance_id}/")
    detail = ok_data(resp)
    check("实例已完成", detail.get("status") == "completed", brief(resp))
    check("实例耗时", "duration_minutes" in detail, str(detail.keys())[:160])

    resp = cb.get(BASE + "tasks/my-done/")
    check("我的已办", ok_data(resp).get("count", 0) >= 2, brief(resp))

    # ---------- 6. 监控 ----------
    resp = ca.get(BASE + "monitor/running/")
    check("运行中看板", resp.status_code == 200 and "summary" in ok_data(resp), brief(resp))
    resp = ca.post(BASE + "monitor/sla-scan/", {}, format="json")
    scanned = ok_data(resp)
    check("SLA 扫描", resp.status_code == 200 and "counts" in scanned, brief(resp))
    resp = ca.get(BASE + "monitor/metrics/", {"definition_id": definition_id})
    metrics = ok_data(resp)
    check("指标总览", resp.status_code == 200 and
          "completion_rate_pct" in (metrics.get("instances") or {}), brief(resp))
    resp = ca.get(BASE + "monitor/status-distribution/")
    check("状态分布", resp.status_code == 200 and "items" in ok_data(resp), brief(resp))
    resp = ca.get(BASE + "monitor/category-distribution/")
    check("分类分布", resp.status_code == 200, brief(resp))
    resp = ca.get(BASE + "monitor/bottlenecks/", {"definition_id": definition_id})
    check("节点瓶颈", resp.status_code == 200 and "items" in ok_data(resp), brief(resp))
    resp = ca.get(BASE + "monitor/trend/", {"days": 7})
    check("趋势", resp.status_code == 200 and "items" in ok_data(resp), brief(resp))
    resp = ca.get(BASE + "monitor/dashboard/")
    check("监控大屏", resp.status_code == 200 and bool(ok_data(resp)), brief(resp))

    # ---------- 7. 协作 ----------
    resp = ca.post(BASE + "delegations/create/", {
        "to_user_id": approver_id, "scope": "all", "reason": "冒烟委托",
        "start_at": timezone.now().isoformat(),
        "end_at": (timezone.now() + timedelta(days=1)).isoformat(),
    }, format="json")
    delegation = ok_data(resp)
    check("创建委托", resp.status_code == 200 and bool(delegation.get("id")), brief(resp))
    if delegation.get("id"):
        resp = ca.post(f"{BASE}delegations/{delegation['id']}/revoke/", {}, format="json")
        check("撤销委托", resp.status_code == 200 and
              ok_data(resp).get("status") == "revoked", brief(resp))

    resp = cb.get(BASE + "notifications/")
    notices = ok_data(resp)
    check("通知列表", resp.status_code == 200 and notices.get("count", 0) >= 1, brief(resp))
    resp = cb.get(BASE + "notifications/summary/")
    summary = ok_data(resp)
    check("通知汇总", resp.status_code == 200 and "unread" in summary, brief(resp))
    resp = cb.post(BASE + "notifications/read/", {}, format="json")
    check("全部已读", resp.status_code == 200, brief(resp))

    resp = ca.get(f"{BASE}instances/{instance_id}/audit/")
    check("实例审计", resp.status_code == 200 and ok_data(resp).get("count", 0) >= 5, brief(resp))
    resp = ca.get(BASE + "audit/", {"page_size": 50})
    check("全局审计", resp.status_code == 200 and ok_data(resp).get("count", 0) >= 1, brief(resp))

    resp = ca.post(BASE + "webhooks/create/", {
        "name": "冒烟 Webhook", "url": "https://example.com/wf-smoke",
        "events": ["task.*", "instance.completed"], "definition_id": definition_id,
    }, format="json")
    webhook = ok_data(resp)
    check("创建 Webhook", resp.status_code == 200 and bool(webhook.get("id")), brief(resp))
    if webhook.get("id"):
        resp = ca.post(f"{BASE}webhooks/{webhook['id']}/update/", {"active": False},
                       format="json")
        check("更新 Webhook", resp.status_code == 200 and
              ok_data(resp).get("active") is False, brief(resp))
        resp = ca.post(f"{BASE}webhooks/{webhook['id']}/delete/", {}, format="json")
        check("删除 Webhook", resp.status_code == 200 and
              ok_data(resp).get("deleted") is True, brief(resp))

    resp = ca.post(BASE + "sla-policies/create/", {
        "code": f"sla_{ts}", "name": "冒烟 SLA", "priority": "high",
        "response_minutes": 30, "resolve_minutes": 240,
    }, format="json")
    check("创建 SLA 策略", resp.status_code == 200 and bool(ok_data(resp).get("id")), brief(resp))

    resp = ca.post(BASE + "expressions/eval/", {
        "expression": "amount >= 5000 and items[0].qty > 0",
        "context": {"amount": 8000, "items": [{"qty": 2}]},
    }, format="json")
    evaluated = ok_data(resp)
    check("表达式求值", resp.status_code == 200 and evaluated.get("valid") is True
          and evaluated.get("raw") is True, brief(resp))
    resp = ca.post(BASE + "expressions/eval/", {
        "expression": "__import__('os').system('echo hacked')", "context": {},
    }, format="json")
    check("危险表达式被拒", resp.status_code == 400 or
          ok_data(resp).get("valid") is False, brief(resp))

    # ---------- 8. 版本 / 克隆 / 导出导入 ----------
    resp = ca.post(f"{BASE}definitions/{definition_id}/publish/", {"note": "二次发布"},
                   format="json")
    check("二次发布", resp.status_code == 200 and
          (ok_data(resp).get("version") or {}).get("version_no") == 2, brief(resp))

    versions = ok_data(ca.get(f"{BASE}definitions/{definition_id}/versions/"))
    items = list_items(versions)
    check("版本列表", versions.get("count") == 2, brief(resp))
    if len(items) >= 2:
        first, second = items[-1], items[0]
        resp = ca.get(BASE + "versions/diff/", {"from_id": first["id"], "to_id": second["id"]})
        diff = ok_data(resp)
        check("版本对比", resp.status_code == 200 and "summary" in diff, brief(resp))
        resp = ca.post(f"{BASE}versions/{first['id']}/rollback/", {"note": "回到首版"},
                       format="json")
        check("版本回滚", resp.status_code == 200, brief(resp))

    stats = ok_data(ca.get(f"{BASE}definitions/{definition_id}/stats/"))
    check("定义统计", stats.get("total", 0) >= 1 and "validation" in stats, brief(resp))

    resp = ca.post(f"{BASE}definitions/{definition_id}/clone/", {
        "code": f"{code}_copy", "name": f"冒烟副本{ts}",
    }, format="json")
    clone = ok_data(resp)
    check("克隆定义", resp.status_code == 200 and clone.get("status") == "draft"
          and clone.get("node_count") == 6, brief(resp))

    exported = ok_data(ca.get(f"{BASE}definitions/{definition_id}/export/"))
    check("导出定义", bool(exported.get("source")) and bool(exported.get("nodes")), brief(resp))

    resp = ca.post(BASE + "definitions/import/", {
        "payload": exported, "code": f"{code}_imp", "name": f"冒烟导入{ts}",
    }, format="json")
    imported = ok_data(resp)
    check("导入定义", resp.status_code == 200 and imported.get("imported") is True, brief(resp))
    if imported.get("definition_id"):
        resp = ca.post(f"{BASE}definitions/{imported['definition_id']}/delete/", {},
                       format="json")
        check("删除导入副本", resp.status_code == 200, brief(resp))

    resp = ca.post(f"{BASE}definitions/{definition_id}/disable/", {}, format="json")
    check("停用定义", resp.status_code == 200 and
          ok_data(resp).get("status") == "disabled", brief(resp))
    resp = ca.post(BASE + "instances/start/", {"definition_id": definition_id}, format="json")
    check("停用后不可发起", resp.status_code == 400, brief(resp))

    # ---------- 9. 越权边界 ----------
    resp = cb.get(f"{BASE}definitions/{definition_id}/")
    check("非所有者不可读定义详情", resp.status_code == 400, brief(resp))
    resp = cb.post(f"{BASE}definitions/{definition_id}/update/", {"name": "越权改名"},
                   format="json")
    check("非所有者不可改定义", resp.status_code == 400, brief(resp))
    resp = cb.get(BASE + "definitions/", {"page_size": 5})
    codes = [x.get("code") for x in list_items(ok_data(resp))]
    check("列表不泄漏他人定义", code not in codes, str(codes)[:160])

    # ---------- 汇总 ----------
    total = len(passed) + len(failed)
    print(f"\nworkflow 冒烟：通过 {len(passed)} / 失败 {len(failed)}（共 {total} 项）")
    if failed:
        print("失败项：")
        for name in failed:
            print("  -", name)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
