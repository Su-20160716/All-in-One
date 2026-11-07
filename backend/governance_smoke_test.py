# -*- coding: utf-8 -*-
"""governance 合规治理冒烟测试：进程内用 DRF APIClient 走一遍真实路由栈。

覆盖链路（与真实业务顺序一致）：
    目录/接口清单 → 内置条款库 → 按模板建框架 → 条款/映射/覆盖率/差距
    → 制度策略（评审/批准/发布/版本/回滚）→ 控制与测试执行
    → 评估（建项/批量/得分/完成）→ 证据（哈希校验）
    → 风险矩阵与处置 → 数据资产/处理活动 DPIA
    → 保留期扫描（幂等）与执行 → 同意有效性/撤回
    → 审计发现/整改验证闭环 → 合规日历/ICS/测试计划/责任分布
    → CSV 导出 → 看板。

与其他应用的 *_smoke_test.py 保持一致：
- 直接 django.setup() + rest_framework.test.APIClient，不需要先起 8000 端口；
- 优先注册带时间戳后缀的新账号并拿 JWT，注册被站点策略挡住时回退 admin；
- 所有编码/名称都带时间戳后缀，可反复执行不撞唯一约束；
- 不自动建表：governance 迁移由独立任务生成，缺表时提示并以退出码 2 结束。

运行（必须显式执行，不参与 CI，也不会被单元测试收集）：

    venv/Scripts/python.exe governance_smoke_test.py

任何一项不符合预期都会打印 [FAIL] 并以非零码退出。
"""
import hashlib
import os
import sys
import time
from datetime import timedelta

import django

# Windows 控制台默认 GBK，输出中文/符号会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# 本轮冒烟约 90 次请求：只放宽本进程内存里的限流，不影响服务器配置。
from django.conf import settings as dj_settings  # noqa: E402
from rest_framework.settings import api_settings  # noqa: E402

dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
    {"user": "1000000/min", "anon": "1000000/min"})
api_settings.DEFAULT_THROTTLE_RATES.update(
    dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

BASE = "/api/governance/"
LIST_KEYS = {"items", "count", "page", "page_size"}
EXPECTED_ENDPOINTS = 147  # 路由共 148 条，目录自身不列入 endpoints

SUFFIX = f"{int(time.time())}{os.getpid() % 1000:03d}"
TODAY = timezone.localdate()

passed, failed = [], []


# ===========================================================================
# 通用断言 / 取值助手
# ===========================================================================


def check(name, cond, extra=""):
    """记录一项检查；失败不中断，最后统一汇总，便于一次跑出全部问题。"""
    if cond:
        passed.append(name)
    else:
        failed.append(name)
        print(f"  [FAIL] {name} {extra}".strip())


def brief(resp, limit=220):
    """失败时打印状态码与响应片段。"""
    try:
        body = resp.data
    except Exception:  # noqa: BLE001
        body = ""
    return f"[{resp.status_code}] {str(body)[:limit]}"


def ok_data(resp):
    """取出统一响应 {ok, data} 里的 data；失败或空体返回 {}。"""
    try:
        if resp.data.get("ok"):
            data = resp.data.get("data")
            if isinstance(data, (dict, list)):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def is_page(payload):
    """列表契约必须恰好四个键，多一个少一个都算破坏前端分页。"""
    return isinstance(payload, dict) and set(payload.keys()) == LIST_KEYS


def section(title):
    print(f"\n--- {title} ---")


def schema_ready():
    """governance 表是否已由迁移创建（本脚本不建表，避免绕过迁移策略）。"""
    from django.apps import apps
    from django.db import connection

    existing = set(connection.introspection.table_names())
    missing = [model._meta.db_table
               for model in apps.get_app_config("governance").get_models()
               if model._meta.db_table not in existing]
    if not missing:
        return True
    print("governance 表尚未创建，无法跑冒烟（本脚本不会自动建表）。")
    print("请先完成 governance 迁移任务并执行 migrate，再重跑本脚本。")
    print("缺少表：" + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    return False


def make_client():
    """注册带时间戳的新账号并返回已带 JWT 的客户端；失败回退 admin。"""
    client = APIClient()
    username = f"gov{SUFFIX}"
    resp = client.post("/api/auth/register/", {
        "username": username,
        "password": "Gv7-tR4ce-92",
        "nickname": "治理冒烟",
        "email": f"{username}@governance.test",
    }, format="json")
    token = (resp.data or {}).get("access") if resp.status_code == 201 else ""
    check("注册冒烟账号并获取 JWT", bool(token), brief(resp))

    if not token:
        client = APIClient()
        resp = client.post("/api/auth/login/",
                           {"username": "admin", "password": "admin123"},
                           format="json")
        token = (resp.data or {}).get("access") or ""
        check("管理员 admin 登录获取 JWT", bool(token), brief(resp))

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ===========================================================================
# 主链路
# ===========================================================================


def main():
    if not schema_ready():
        return 2

    client = make_client()

    # ---------- 1. 目录 ----------
    section("目录")
    resp = client.get(BASE)
    catalog = ok_data(resp)
    check("目录接口可用", resp.status_code == 200 and catalog.get("app") == "governance",
          brief(resp))
    check("目录版本 1.0", catalog.get("version") == "1.0", str(catalog.get("version")))
    check("能力域 9 个", len(catalog.get("domains") or []) == 9,
          str(len(catalog.get("domains") or [])))
    endpoints = catalog.get("endpoints") or []
    check(f"接口清单 {EXPECTED_ENDPOINTS} 个（目录自身除外）",
          catalog.get("endpoint_count") == EXPECTED_ENDPOINTS
          and len(endpoints) == EXPECTED_ENDPOINTS,
          str(catalog.get("endpoint_count")))
    paths = {row.get("path"): row.get("methods") for row in endpoints}
    check("接口清单含 frameworks/", "frameworks/" in paths)
    check("接口清单含 exports/risks/", "exports/risks/" in paths)
    check("frameworks/ 方法契约", paths.get("frameworks/") == ["GET"],
          str(paths.get("frameworks/")))

    # ---------- 2. 内置条款库 ----------
    section("条款库模板")
    templates = ok_data(client.get(BASE + "templates/"))
    check("模板目录 3 套", templates.get("count") == 3, str(templates)[:200])
    iso = ok_data(client.get(BASE + "templates/iso27001/"))
    check("ISO 模板条款 >= 20 条",
          len(iso.get("items") or []) >= 20, str(len(iso.get("items") or [])))
    check("ISO 首条为 A.5.1",
          (iso.get("items") or [{}])[0].get("code") == "A.5.1",
          str((iso.get("items") or [{}])[0]))

    # ---------- 3. 按模板建框架 ----------
    section("框架与条款")
    resp = client.post(BASE + "frameworks/from-template/", {
        "kind": "soc2", "name": f"SOC2-{SUFFIX}",
    }, format="json")
    framework = ok_data(resp)
    framework_id = framework.get("id")
    apply_info = framework.get("apply") or {}
    check("按模板建框架并写入条款",
          resp.status_code == 200 and apply_info.get("created", 0) > 0
          and framework.get("control_count", 0) > 0, brief(resp))
    resp = client.post(BASE + f"frameworks/{framework_id}/apply-template/", {},
                       format="json")
    again = (ok_data(resp).get("apply") or {})
    check("重复应用模板幂等（created=0）", again.get("created") == 0, brief(resp))

    controls = ok_data(client.get(BASE + f"frameworks/{framework_id}/controls/"))
    check("框架条款列表契约", is_page(controls) and controls.get("count", 0) > 0,
          str(controls)[:200])
    first_control = (controls.get("items") or [{}])[0]

    resp = client.post(BASE + "frameworks/" + f"{framework_id}/publish/", {},
                       format="json")
    check("发布框架", ok_data(resp).get("status") == "active", brief(resp))

    # ---------- 4. 控制与映射 ----------
    section("控制与映射")
    resp = client.post(BASE + "controls/create/", {
        "code": f"AC-{SUFFIX}", "name": "统一身份认证",
        "category": "访问控制", "frequency": "quarterly", "automated": True,
    }, format="json")
    control = ok_data(resp)
    control_id = control.get("id")
    check("新建内部控制", resp.status_code == 200 and control.get("code"),
          brief(resp))

    resp = client.post(BASE + "control-mappings/link/", {
        "framework_control_id": first_control.get("id"),
        "control_id": control_id, "strength": 100,
    }, format="json")
    check("条款映射控制", resp.status_code == 200, brief(resp))

    coverage = ok_data(client.get(BASE + f"frameworks/{framework_id}/coverage/"))
    check("覆盖率含 gap 字段",
          "gap_total" in coverage and coverage.get("control_total", 0) > 0,
          str(coverage)[:200])
    gaps = ok_data(client.get(BASE + f"frameworks/{framework_id}/gaps/"))
    check("差距分析契约", isinstance(gaps.get("gaps"), list)
          and "no_mapping" in (gaps.get("summary") or {}), str(gaps)[:200])

    # ---------- 5. 策略生命周期 ----------
    section("策略生命周期")
    resp = client.post(BASE + "policies/create/", {
        "code": f"PRV-{SUFFIX}", "name": f"隐私政策-{SUFFIX}",
        "kind": "privacy", "content": "第一条 总则\n第二条 适用范围",
    }, format="json")
    policy = ok_data(resp)
    policy_id = policy.get("id")
    check("新建策略为草稿", policy.get("status") == "draft", brief(resp))
    client.post(BASE + f"policies/{policy_id}/submit-review/", {}, format="json")
    check("提交评审",
          ok_data(client.get(BASE + f"policies/{policy_id}/"))
          .get("status") == "reviewing", brief(resp))
    resp = client.post(BASE + f"policies/{policy_id}/approve/", {
        "approver_name": "合规负责人",
        "next_review_on": (TODAY + timedelta(days=5)).isoformat(),
    }, format="json")
    check("批准策略并返回版本",
          (ok_data(resp).get("policy") or {}).get("status") == "approved",
          brief(resp))
    resp = client.post(BASE + f"policies/{policy_id}/publish/", {}, format="json")
    published = ok_data(resp)
    check("发布策略生成版本快照",
          published.get("already_published") is not True
          and (published.get("version") or {}).get("id"), brief(resp))
    resp = client.post(BASE + f"policies/{policy_id}/publish/", {}, format="json")
    check("重复发布幂等（already_published）",
          ok_data(resp).get("already_published") is True, brief(resp))
    detail = ok_data(client.get(BASE + f"policies/{policy_id}/"))
    current_version = detail.get("current_version")
    versions = ok_data(client.get(BASE + f"policies/{policy_id}/versions/"))
    check("版本列表含已发布版本",
          (versions.get("count") or 0) >= 1, str(versions)[:200])
    resp = client.post(BASE + f"policies/{policy_id}/rollback/",
                       {"version": current_version}, format="json")
    check("回滚到当前版本不改动",
          ok_data(resp).get("changed") is False, brief(resp))

    # ---------- 6. 控制测试 ----------
    section("控制测试")
    resp = client.post(BASE + "control-tests/create/", {
        "control_id": control_id, "name": "抽样核对权限",
        "method": "manual", "steps": ["导出权限清单", "比对岗位矩阵"],
        "pass_criteria": "无多余权限",
    }, format="json")
    test = ok_data(resp)
    check("新建控制测试（2 步）", test.get("step_count") == 2, brief(resp))
    resp = client.post(BASE + f"control-tests/{test.get('id')}/run/",
                       {"result": "pass", "duration_ms": 120}, format="json")
    check("执行测试通过并回写有效性",
          ok_data(resp).get("control_effectiveness") == 100, brief(resp))
    history = ok_data(client.get(BASE + f"control-tests/{test.get('id')}/history/"))
    check("测试历史分页契约", is_page(history) and history.get("count") == 1,
          str(history)[:200])

    # ---------- 7. 评估 ----------
    section("合规评估")
    resp = client.post(BASE + "assessments/create/", {
        "name": f"2026 年度评估-{SUFFIX}", "framework_id": framework_id,
        "lead_name": "王五",
        "end_on": (TODAY + timedelta(days=30)).isoformat(),
    }, format="json")
    assessment = ok_data(resp)
    assessment_id = assessment.get("id")
    check("按框架自动生成评估项", assessment.get("seeded_items", 0) > 0, brief(resp))
    client.post(BASE + f"assessments/{assessment_id}/start/", {}, format="json")
    items = ok_data(client.get(BASE + f"assessments/{assessment_id}/items/"))
    rows = (items.get("items") or [])[:3]
    payload_rows = []
    for index, row in enumerate(rows):
        status = "passed" if index == 0 else ("in_progress" if index == 1 else "not_applicable")
        payload_rows.append({"id": row.get("id"), "status": status})
    resp = client.post(BASE + "assessments/items/bulk/", {
        "assessment_id": assessment_id, "items": payload_rows,
    }, format="json")
    bulk = ok_data(resp)
    check("批量更新评估项并算分",
          bulk.get("updated") == len(payload_rows) and bulk.get("score") is not None,
          brief(resp))
    resp = client.post(BASE + f"assessments/{assessment_id}/complete/", {},
                       format="json")
    check("完成评估并固化得分",
          ok_data(resp).get("status") == "completed", brief(resp))
    report = ok_data(client.get(BASE + f"assessments/{assessment_id}/report/"))
    check("评估报告含状态分布",
          isinstance(report.get("by_status"), dict), str(report)[:200])

    # ---------- 8. 证据 ----------
    section("证据")
    content = f"权限清单-{SUFFIX}"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    resp = client.post(BASE + "evidences/create/", {
        "target_kind": "control", "target_id": control_id,
        "name": f"权限清单-{SUFFIX}", "kind": "hash",
        "hash_value": f"sha256:{digest}",
        "expires_on": (TODAY + timedelta(days=3)).isoformat(),
    }, format="json")
    evidence = ok_data(resp)
    check("登记证据（哈希指纹）", evidence.get("hash_value") == f"sha256:{digest}",
          brief(resp))
    resp = client.post(BASE + f"evidences/{evidence.get('id')}/verify/",
                       {"content": content}, format="json")
    verified = ok_data(resp)
    check("证据哈希校验一致", verified.get("ok") is True, brief(resp))
    resp = client.post(BASE + f"evidences/{evidence.get('id')}/verify/",
                       {"content": "被篡改的内容"}, format="json")
    check("篡改内容校验失败", ok_data(resp).get("ok") is False, brief(resp))
    # 接口默认 only_expired=true 只列已过期；要查「即将到期」需显式关闭该过滤
    expiring = ok_data(client.get(BASE + "evidences/expired/",
                                  {"days": 30, "only_expired": 0}))
    check("即将到期证据可查询", (expiring.get("count") or 0) >= 1,
          str(expiring)[:200])

    # ---------- 9. 风险 ----------
    section("风险矩阵与处置")
    resp = client.post(BASE + "risks/create/", {
        "name": f"供应商数据泄露-{SUFFIX}", "likelihood": 5, "impact": 5,
        "category": "第三方",
    }, format="json")
    risk = ok_data(resp)
    risk_id = risk.get("id")
    check("新建风险（固有分 25、严重）",
          risk.get("inherent_score") == 25 and risk.get("level") == "critical",
          brief(resp))
    matrix = ok_data(client.get(BASE + "risks/matrix/"))
    check("风险矩阵 25 格 + 4 分档",
          len(matrix.get("grid") or []) == 25 and len(matrix.get("bands") or []) == 4,
          str(matrix)[:200])
    resp = client.post(BASE + "risks/treatments/create/", {
        "risk_id": risk_id, "strategy": "mitigate", "action": "上线数据脱敏",
        "owner_name": "赵六", "due_on": TODAY.isoformat(),
    }, format="json")
    treatment = ok_data(resp)
    check("新建处置且风险转处置中",
          ok_data(client.get(BASE + f"risks/{risk_id}/")).get("status") == "treating",
          brief(resp))
    resp = client.post(BASE + f"risk-treatments/{treatment.get('id')}/complete/", {},
                       format="json")
    check("完成处置（风险转监控中）",
          ok_data(resp).get("risk_status") == "monitored", brief(resp))
    resp = client.post(BASE + f"risk-treatments/{treatment.get('id')}/complete/", {},
                       format="json")
    check("重复完成处置幂等", ok_data(resp).get("changed") is False, brief(resp))
    rescored = ok_data(client.post(BASE + f"risks/{risk_id}/rescore/",
                                   {"effectiveness": 50}, format="json"))
    check("重算后剩余分 13（25*0.5 四舍五入）",
          (rescored.get("scoring") or {}).get("residual_score") == 13,
          brief(resp))

    # ---------- 10. 隐私 ----------
    section("数据资产与处理活动")
    resp = client.post(BASE + "data-assets/create/", {
        "name": f"客户主数据-{SUFFIX}", "kind": "personal",
        "classification": "confidential", "retention_days": 1,
        "contains_pii": True, "storage_location": "cn-north-1",
    }, format="json")
    asset = ok_data(resp)
    check("新建数据资产（含 PII、有到期日）",
          asset.get("contains_pii") is True and asset.get("retention_due_on"),
          brief(resp))
    resp = client.post(BASE + "processing-activities/create/", {
        "name": f"营销画像-{SUFFIX}", "purpose": "个性化推荐",
        "legal_basis": "同意", "data_categories": ["浏览记录"],
        "subject_categories": ["用户"], "cross_border": True,
    }, format="json")
    activity = ok_data(resp)
    activity_id = activity.get("id")
    check("新建处理活动（跨境）", activity.get("cross_border") is True, brief(resp))
    first = ok_data(client.post(BASE + f"processing-activities/{activity_id}/dpia/",
                                {}, format="json"))
    check("完成 DPIA", first.get("already_done") is False, brief(resp))
    second = ok_data(client.post(BASE + f"processing-activities/{activity_id}/dpia/",
                                 {}, format="json"))
    check("重复 DPIA 幂等（already_done）", second.get("already_done") is True,
          str(second)[:200])

    # ---------- 11. 保留期 ----------
    section("保留期扫描与执行")
    resp = client.post(BASE + "retention-rules/create/", {
        "resource_kind": "data_asset", "retention_days": 1, "due_action": "archive",
    }, format="json")
    check("新建保留规则", resp.status_code == 200, brief(resp))
    as_of = (TODAY + timedelta(days=2)).isoformat()
    first_scan = ok_data(client.post(BASE + "retention/scan/", {"as_of": as_of},
                                     format="json"))
    check("保留扫描生成台账", first_scan.get("created", 0) >= 1, brief(resp))
    second_scan = ok_data(client.post(BASE + "retention/scan/", {"as_of": as_of},
                                      format="json"))
    check("重复扫描幂等（created=0）", second_scan.get("created") == 0,
          str(second_scan)[:200])
    due = ok_data(client.get(BASE + "retention/due/", {"as_of": as_of}))
    check("到期台账可查询", (due.get("count") or 0) >= 1, str(due)[:200])
    action_id = ((due.get("items") or [{}])[0]).get("id")
    executed = ok_data(client.post(BASE + "retention/execute/",
                                   {"action_id": action_id}, format="json"))
    check("执行保留期动作", executed.get("changed") is True, brief(resp))
    repeated = ok_data(client.post(BASE + "retention/execute/",
                                   {"action_id": action_id}, format="json"))
    check("重复执行不二次迁移状态",
          repeated.get("changed") is False
          and repeated.get("reason") == "already_executed", str(repeated)[:200])

    # ---------- 12. 同意 ----------
    section("同意记录")
    resp = client.post(BASE + "consents/create/", {
        "data_subject": f"user{SUFFIX}@example.com", "purpose": "营销短信",
        "expires_on": (TODAY + timedelta(days=10)).isoformat(),
    }, format="json")
    consent = ok_data(resp)
    consent_id = consent.get("id")
    check("登记同意（授予中）", consent.get("status") == "granted", brief(resp))
    valid = ok_data(client.get(BASE + f"consents/{consent_id}/validity/",
                               {"purpose": "营销短信"}))
    check("同意有效", valid.get("valid") is True, str(valid)[:200])
    mismatch = ok_data(client.get(BASE + f"consents/{consent_id}/validity/",
                                  {"purpose": "征信查询"}))
    check("目的不一致判无效", mismatch.get("valid") is False, str(mismatch)[:200])
    client.post(BASE + f"consents/{consent_id}/withdraw/", {}, format="json")
    after = ok_data(client.get(BASE + f"consents/{consent_id}/validity/"))
    check("撤回后无效", after.get("valid") is False, str(after)[:200])
    summary = ok_data(client.get(BASE + "consents/summary/"))
    check("同意汇总可查询", (summary.get("by_status") or {}).get("withdrawn", 0) >= 1,
          str(summary)[:200])

    # ---------- 13. 审计闭环 ----------
    section("审计发现与整改")
    resp = client.post(BASE + "audits/create/", {
        "name": f"2026 年内部审计-{SUFFIX}", "kind": "internal",
    }, format="json")
    audit = ok_data(resp)
    audit_id = audit.get("id")
    resp = client.post(BASE + "audits/findings/create/", {
        "audit_id": audit_id, "title": f"离职账号未及时回收-{SUFFIX}",
        "severity": "high", "remediation_owner": "运维",
        "due_on": TODAY.isoformat(),
    }, format="json")
    finding = ok_data(resp)
    finding_id = finding.get("id")
    check("登记审计发现（高风险）",
          finding.get("severity") == "high", brief(resp))
    resp = client.post(BASE + "findings/remediations/create/", {
        "finding_id": finding_id, "measure": "接入离职自动回收脚本",
        "owner_name": "运维", "due_on": TODAY.isoformat(),
    }, format="json")
    task = ok_data(resp)
    task_id = task.get("id")
    check("新建整改任务", resp.status_code == 200, brief(resp))
    client.post(BASE + f"remediations/{task_id}/update/", {"status": "done"},
                format="json")
    resp = client.post(BASE + f"remediations/{task_id}/verify/",
                       {"verifier_name": "合规负责人"}, format="json")
    verified_task = ok_data(resp)
    check("整改验证通过并关闭发现",
          verified_task.get("finding_status") == "verified", brief(resp))
    resp = client.post(BASE + f"remediations/{task_id}/verify/", {}, format="json")
    check("重复验证幂等（already_verified）",
          ok_data(resp).get("already_verified") is True, brief(resp))

    # ---------- 14. 合规日历 ----------
    section("合规日历")
    calendar = ok_data(client.get(BASE + "stats/calendar/", {"days": 30}))
    check("日历聚合到期事项", calendar.get("count", 0) >= 1,
          str(calendar)[:200])
    sources = ok_data(client.get(BASE + "stats/calendar/sources/"))
    check("日历来源字典 9 类", sources.get("count") == 9, str(sources)[:200])
    ics = ok_data(client.get(BASE + "stats/calendar/ics/", {"days": 30}))
    check("导出 iCalendar 文本",
          ics.get("format") == "ics"
          and str(ics.get("content", "")).startswith("BEGIN:VCALENDAR"),
          str(ics)[:200])
    plan = ok_data(client.get(BASE + "stats/control-plan/", {"days": 120}))
    check("控制测试计划可查询", isinstance(plan.get("items"), list),
          str(plan)[:200])
    workload = ok_data(client.get(BASE + "stats/workload/"))
    check("责任分布可查询", isinstance(workload.get("items"), list),
          str(workload)[:200])

    # ---------- 15. 导出 ----------
    section("CSV 导出")
    exports = ok_data(client.get(BASE + "exports/"))
    check("导出目录 5 个数据集", exports.get("count") == 5, str(exports)[:200])
    risks_csv = ok_data(client.get(BASE + "exports/risks/"))
    check("风险 CSV 契约与内容",
          risks_csv.get("format") == "csv"
          and "编号" in (risks_csv.get("headers") or [])
          and (risks_csv.get("count") or 0) >= 1, str(risks_csv)[:200])
    controls_csv = ok_data(client.get(BASE + "exports/controls/"))
    check("控制 CSV 可导出", (controls_csv.get("count") or 0) >= 1,
          str(controls_csv)[:200])
    findings_csv = ok_data(client.get(BASE + "exports/findings/"))
    check("发现 CSV 可导出", (findings_csv.get("count") or 0) >= 1,
          str(findings_csv)[:200])

    # ---------- 16. 看板 ----------
    section("看板")
    dashboard = ok_data(client.get(BASE + "stats/dashboard/"))
    check("看板含框架/风险/整改/DPIA",
          all(key in dashboard for key in ("frameworks", "risks", "remediations", "dpia")),
          str(dashboard)[:200])
    check("看板统计到本轮风险",
          (dashboard.get("risks") or {}).get("total", 0) >= 1,
          str(dashboard.get("risks"))[:200])
    trend = ok_data(client.get(BASE + "stats/finding-trend/", {"months": 3}))
    check("发现趋势可查询", isinstance(trend.get("series"), list), str(trend)[:200])

    # ---------- 汇总 ----------
    total = len(passed) + len(failed)
    print(f"\ngovernance 冒烟：通过 {len(passed)} / 失败 {len(failed)}（共 {total} 项）")
    if failed:
        print("失败项：")
        for name in failed:
            print("  -", name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
