"""contracts 应用独立冒烟脚本：进程内走 DRF 路由栈跑一遍合同全生命周期主链路。

用法（必须显式执行，不参与 CI，也不会被单元测试收集）：

    venv/Scripts/python.exe contracts_smoke_test.py

可选环境变量：

    CONTRACTS_SMOKE_TOKEN   Bearer 令牌（与 SESSION 二选一）
    CONTRACTS_SMOKE_SESSION 会话 Cookie，形如 sessionid=xxx
    CONTRACTS_SMOKE_KEEP    1 表示保留创建出来的合同，默认归档收尾

传输层用 smoke_inproc（django.setup + APIClient），不需要先起 8000 端口；
未给令牌时自动登录 admin/admin123，失败再回退注册新账号。
任何一步不符合预期都会抛 AssertionError 并以非零码退出，
方便在发布前手工确认「模型 / 服务 / 路由」三件事都通。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

from smoke_inproc import init, request_json

KEEP = os.environ.get("CONTRACTS_SMOKE_KEEP", "") == "1"

PREFIX = "/api/contracts/"

CLIENT, TOKEN = init("contracts", token_env="CONTRACTS_SMOKE_TOKEN",
                     session_env="CONTRACTS_SMOKE_SESSION")

_failures: list[str] = []
_created: dict[str, int] = {}


def call(method: str, path: str, payload=None, expect=(200,), params=None):
    """发一次进程内请求，返回 (状态码, 解析后的 JSON)，断言状态码在 expect 内。"""
    url = f"{PREFIX}{path.lstrip('/')}"
    status, data = request_json(CLIENT, method, url, payload=payload, params=params)
    if status not in expect:
        raise AssertionError(f"{method} {path} -> {status}（期望 {expect}）：{data}")
    return status, data


def check(name: str, condition: bool, detail: str = "") -> None:
    """记录一步结果；失败不中断，便于一次跑出全部问题。"""
    if condition:
        print(f"[ok]   {name}")
        return
    _failures.append(f"{name} {detail}".strip())
    print(f"[FAIL] {name} {detail}".strip())


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    today = date.today()
    section("目录与鉴权")
    _, catalog = call("GET", "")
    endpoints = catalog.get("endpoints", [])
    paths = {item["path"] for item in endpoints}
    check("目录返回接口清单", len(paths) >= 100, f"实际 {len(paths)} 条")
    check("目录包含合同创建", "contracts/create/" in paths)
    check("目录声明分页上限", catalog.get("limits", {}).get("page_size") == 200)
    status, _ = request_json(CLIENT, "GET", PREFIX, auth=False)
    check("匿名访问被拒绝", status in (401, 403), f"实际 {status}")

    _, meta = call("GET", "meta/")
    check("元信息含状态枚举", "contract_status" in (meta.get("enums") or {}))
    _, counts = call("GET", "counts/")
    check("规模统计可用", "contracts" in counts)

    section("模板与条款库")
    _, template = call("POST", "templates/create/", {
        "code": f"SMOKE-TPL-{today:%Y%m%d}",
        "name": "冒烟技术服务模板",
        "template_type": "service",
        "scene": "冒烟",
        "body": "甲方：{{party_a}}\n金额：{{amount|0}} 元\n{{clause}}",
        "variables": [
            {"name": "party_a", "label": "甲方", "required": True},
            {"name": "amount", "label": "金额", "required": False, "default": "0"},
            {"name": "clause", "label": "补充条款", "required": False,
             "default": ""},
        ],
    })
    template_id = template["id"]
    _created["template"] = template_id
    check("创建模板为草稿", template.get("status") == "draft")
    check("模板变量名去重排序", template.get("variable_names")
          == ["amount", "clause", "party_a"])

    _, published = call("POST", f"templates/{template_id}/publish/", {})
    check("发布模板", published.get("status") == "published")
    _, rendered = call("POST", f"templates/{template_id}/render/", {
        "variables": {"party_a": "冒烟甲方"}})
    check("渲染替换变量", "冒烟甲方" in rendered.get("body", ""))
    check("渲染无剩余占位符", rendered.get("unresolved") == [])
    call("POST", f"templates/{template_id}/render/", {"variables": {}},
         expect=(400,))

    _, library = call("POST", "clauses/library/create/", {
        "title": "保密义务", "category": "通用", "risk_level": "high",
        "body": "双方对合作中知悉的商业秘密承担保密义务。",
        "tags": ["保密", "通用"]})
    check("新增条款库条目", library.get("risk_level") == "high")
    _, suggested = call("GET", "clauses/library/suggest/",
                        params={"q": "保密", "risk_level": "high"})
    check("条款推荐命中", suggested.get("count") == 1,
          json.dumps(suggested)[:200])

    section("合同起草与审批")
    _, contract = call("POST", "contracts/create/", {
        "name": f"冒烟技术服务合同 {today:%Y%m%d}",
        "contract_type": "service",
        "amount": "120000.00",
        "currency": "CNY",
        "effective_date": today.isoformat(),
        "expire_date": (today + timedelta(days=60)).isoformat(),
        "renewal_mode": "manual",
        "counterparty_name": "冒烟乙方有限公司",
        "template_id": template_id,
        "variables": {"party_a": "冒烟甲方", "amount": "120000"},
        "parties": [
            {"name": "冒烟甲方", "role": "party_a", "credit_code": "91310000SMOKE0001X"},
            {"name": "冒烟乙方有限公司", "role": "party_b"},
        ],
        "body": "第一条 合作范围\n双方就冒烟测试服务达成一致。\n第二条 付款\n甲方按期付款。",
    })
    contract_id = contract["id"]
    _created["contract"] = contract_id
    check("创建合同为草稿", contract.get("status") == "draft")
    check("生成首个版本", contract.get("current_version_id") is not None)
    check("金额两位小数", contract.get("amount") == "120000.00")

    _, submitted = call("POST", f"contracts/{contract_id}/submit/", {})
    check("提交进入审批中", submitted.get("status") == "reviewing")
    check("按金额生成审批节点", len(submitted.get("nodes") or []) >= 1)

    approved = submitted
    for _ in range(6):
        if approved.get("status") != "reviewing":
            break
        _, approved = call("POST", f"contracts/{contract_id}/approve/", {})
    check("审批全部通过", approved.get("status") == "approved")

    _, signed = call("POST", f"contracts/{contract_id}/sign/",
                     {"method": "electronic", "sign_now": True})
    check("签署生成指纹", signed.get("signed", 0) >= 1)
    _, activated = call("POST", f"contracts/{contract_id}/activate/", {})
    check("合同生效", activated.get("status") == "active")

    section("版本与状态机")
    _, detail = call("GET", f"contracts/{contract_id}/")
    check("详情含参与方数量", detail.get("party_count") == 2)
    _, versions = call("GET", f"contracts/{contract_id}/versions/")
    first_version = versions["items"][0]["id"]
    _, second = call("POST", f"contracts/{contract_id}/versions/create/", {
        "body": "第一条 合作范围\n双方就冒烟测试服务达成一致（修订）。\n"
                "第二条 付款\n甲方按期付款。",
        "change_summary": "冒烟改稿"})
    check("新增版本号自增", second.get("version_no", 0) >= 2)
    _, compare = call("GET", "versions/compare/", params={
        "left_id": first_version, "right_id": second["id"]})
    check("版本对比给出差异", compare.get("changed", 0) >= 1,
          json.dumps(compare)[:200])
    status, _ = call("POST", f"contracts/{contract_id}/archive/", {}, expect=(400,))
    check("生效合同不能直接归档", status == 400)

    section("履约与里程碑")
    _, obligation = call("POST", f"contracts/{contract_id}/obligations/create/", {
        "content": "按季提交服务报告", "cycle": "quarterly",
        "due_date": today.isoformat()})
    obligation_id = obligation["id"]
    _, schedule = call("POST", f"obligations/{obligation_id}/schedule/",
                       {"periods": 4})
    check("排期幂等生成", schedule.get("created") == 4)
    _, schedule_again = call("POST", f"obligations/{obligation_id}/schedule/",
                             {"periods": 4})
    check("重复排期不新增", schedule_again.get("created") == 0)
    _, done = call("POST", f"obligations/{obligation_id}/complete/",
                   {"note": "冒烟完成"})
    check("完成义务写事件", done.get("status") == "done")

    _, milestone = call("POST", f"contracts/{contract_id}/milestones/create/", {
        "name": "一期验收", "plan_date": (today + timedelta(days=5)).isoformat(),
        "amount": "30000"})
    _, milestone_done = call("POST", f"milestones/{milestone['id']}/complete/",
                             {"actual_date": (today + timedelta(days=6)).isoformat()})
    check("里程碑延期换算", milestone_done.get("delay_days") == 1)

    _, amendment = call("POST", f"contracts/{contract_id}/amendments/create/", {
        "change_type": "amount", "after_text": "150000.00",
        "reason": "冒烟增加服务范围"})
    call("POST", f"amendments/{amendment['id']}/submit/", {})
    _, effective = call("POST", f"amendments/{amendment['id']}/approve/",
                        {"action": "approve"})
    check("变更单生效", effective.get("approval_status") == "effective")
    _, detail = call("GET", f"contracts/{contract_id}/")
    check("变更回写合同金额", detail.get("amount") == "150000.00")

    section("付款计划")
    _, plan = call("POST", f"contracts/{contract_id}/payments/plan/", {
        "periods": 3, "ratios": ["50", "30", "20"],
        "first_date": today.isoformat(), "interval_days": 30})
    check("付款计划生成三期", plan.get("created") == 3)
    check("计划总额等于合同金额", plan.get("amount") == "150000.00")
    _, plan_again = call("POST", f"contracts/{contract_id}/payments/plan/", {
        "periods": 3, "ratios": ["50", "30", "20"],
        "first_date": today.isoformat()})
    check("重复生成幂等", plan_again.get("created") == 0)
    first_payment = plan["items"][0]
    _, paid = call("POST", f"payments/{first_payment['id']}/pay/",
                   {"amount": first_payment["plan_amount"],
                    "paid_date": today.isoformat()})
    check("首期结清", paid.get("status") == "paid")

    section("提醒与风险")
    _, scan = call("POST", "reminders/scan/", {"days": 90})
    check("到期扫描有结果结构", set(scan) >= {"scanned", "items"})
    _, scan_again = call("POST", "reminders/scan/", {"days": 90})
    check("提醒扫描幂等", scan_again.get("reminders_created", 0) <= 1,
          json.dumps(scan_again)[:200])
    _, reminders = call("GET", "reminders/", {"page_size": 10})
    check("提醒列表分页结构", set(reminders) >= {"items", "count", "page", "page_size"})
    if reminders.get("items"):
        _, acked = call("POST", f"reminders/{reminders['items'][0]['id']}/ack/", {})
        check("提醒可确认已读", acked.get("status") == "read")

    _, scored = call("POST", f"contracts/{contract_id}/risk/score/", {})
    check("风险评分返回明细", "breakdown" in scored or "level" in scored,
          json.dumps(scored)[:200])
    _, risks = call("POST", f"contracts/{contract_id}/risks/create/", {
        "title": "付款逾期风险", "level": "medium", "category": "payment",
        "description": "首期付款存在延迟可能。"})
    check("风险项默认未关闭", risks.get("status") in ("open", "monitoring"))

    section("审计、导出与统计")
    _, audit = call("GET", f"contracts/{contract_id}/audit/", {"page_size": 20})
    check("审计流水含状态流转", audit.get("count", 0) >= 3)
    _, exported = call("GET", f"contracts/{contract_id}/export/")
    check("归档包含主档", exported.get("contract", {}).get("id") == contract_id)
    check("归档包含付款", len(exported.get("payments") or []) == 3)
    _, calendar = call("GET", "obligations/calendar/", {"months": 6})
    check("履约日历按月聚合", calendar.get("total", 0) >= 1)
    _, window = call("GET", "stats/renewal-window/", {"days": 90})
    check("续约窗口分档", "buckets" in window)
    _, finance = call("GET", "finance/summary/", {"contract_id": contract_id})
    check("财务汇总金额一致", finance.get("paid_amount") == first_payment["plan_amount"],
          json.dumps(finance)[:200])
    _, overview = call("GET", "stats/overview/")
    check("组合统计可用", overview.get("total", 0) >= 1)
    _, health = call("GET", "stats/health/")
    check("健康度有评分", health.get("scored", 0) >= 1)

    section("分页与校验")
    _, listed = call("GET", "contracts/", {"page_size": 200})
    check("列表分页结构", set(listed) >= {"items", "count", "page", "page_size"})
    status, _ = call("GET", "contracts/", {"page_size": 500}, expect=(400,))
    check("分页超限返回 400", status == 400)
    status, _ = call("POST", "contracts/create/", {"name": "空金额", "amount": "0"},
                     expect=(400,))
    check("零金额被拒绝", status == 400)
    status, _ = call("POST", "contracts/create/", {"name": "坏金额", "amount": "abc"},
                     expect=(400,))
    check("非法金额返回 400", status == 400)

    section("清理")
    if KEEP:
        print("保留合同:", contract_id)
    else:
        call("POST", f"contracts/{contract_id}/terminate/", {"reason": "冒烟收尾"})
        call("POST", f"contracts/{contract_id}/archive/", {})
        print("已终止并归档合同:", contract_id)
        print("模板/条款库保留（条款库删除仅停用，避免丢审计线索）")

    if _failures:
        print(f"\n共 {len(_failures)} 项失败：")
        for item in _failures:
            print(" -", item)
        return 1
    print("\n全部冒烟步骤通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
