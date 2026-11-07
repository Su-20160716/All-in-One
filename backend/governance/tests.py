# -*- coding: utf-8 -*-
"""governance 回归测试：框架/条款、策略流转与版本、控制测试、评估评分、
证据校验、风险矩阵、隐私数据、保留期扫描、同意有效性、审计闭环与统计。

运行：venv/Scripts/python.exe manage.py test governance -v 1

说明
----
1. governance/migrations 目前只有空包（迁移统一生成是独立任务），Django 会
   认为应用「已迁移但没有迁移」，测试库不会 sync 建表，所以每个 TestCase
   在 setUpClass 里按依赖顺序补建本应用的表（只作用于测试库）。
2. 本工程 `backend/code` 包会遮蔽标准库 code，导致 Django 测试运行器导入
   pdb 失败。governance.apps.GovernanceConfig.ready() 在 django.setup()
   阶段已把标准库 code 的交互控制台类补到被遮蔽的包上，因此常规
   `manage.py test governance` 即可运行；本文件不做任何 sys.modules 改造。
3. 测试库为内存 sqlite，不触碰开发库，也不发起任何网络请求。
"""
from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from governance import services
from governance.models import (
    Assessment,
    AssessmentItem,
    Audit,
    ConsentRecord,
    Control,
    ControlMapping,
    ControlTest,
    ControlTestRun,
    DataAsset,
    Evidence,
    Finding,
    Framework,
    FrameworkControl,
    Policy,
    PolicyVersion,
    ProcessingActivity,
    RemediationTask,
    RetentionAction,
    RetentionRule,
    Risk,
    RiskMatrixBand,
    RiskTreatment,
)

User = get_user_model()
BASE = "/api/governance/"


def ensure_governance_tables():
    """测试库补建 governance 表（幂等，只影响测试库）。

    按本应用内部外键依赖做拓扑排序：先建没有本应用外键的表，再建引用它们的表。
    遇到互相引用（理论上不存在）时按声明顺序补齐，SQLite 允许先引用后建表。
    """
    if connection.in_atomic_block:
        # 已经在事务里说明调用顺序有误；静默跳过，让测试用真实报错暴露问题。
        return
    existing = set(connection.introspection.table_names())
    pending = [model for model in apps.get_app_config("governance").get_models()
               if model._meta.db_table not in existing]
    ordered = []
    while pending:
        progressed = False
        for model in list(pending):
            deps = set()
            for field in model._meta.get_fields():
                related = getattr(field, "related_model", None)
                if related is None or related is model:
                    continue
                if related._meta.app_label != "governance":
                    continue
                if related._meta.db_table not in existing:
                    deps.add(related)
            if not deps:
                ordered.append(model)
                pending.remove(model)
                progressed = True
        if not progressed:
            ordered.extend(pending)
            break
    with connection.schema_editor() as editor:
        for model in ordered:
            if model._meta.db_table not in existing:
                editor.create_model(model)
                existing.add(model._meta.db_table)


class GovBase(TestCase):
    """公共夹具：三个用户（owner / other / staff admin）、客户端与断言助手。"""

    @classmethod
    def setUpClass(cls):
        # 建表必须发生在 TestCase 的类级事务开启之前：SQLite 的 schema_editor
        # 不允许在事务内关闭外键约束检查（NotSupportedError）。
        ensure_governance_tables()
        super().setUpClass()

    def setUp(self):
        self.user = User.objects.create_user(username="gov_owner", password="x")
        self.other = User.objects.create_user(username="gov_other", password="x")
        self.admin = User.objects.create_user(username="gov_admin", password="x",
                                              is_staff=True)
        self.client = APIClient()
        self.as_user(self.user)

    # ---- 请求助手 ----

    def as_user(self, user):
        """切换当前认证用户（force_authenticate，不依赖 JWT 流程）。"""
        self.client.force_authenticate(user=user)
        self.current_user = user

    def get(self, path, params=None):
        return self.client.get(BASE + path, params or {})

    def post(self, path, payload=None):
        return self.client.post(BASE + path, payload or {}, format="json")

    def ok(self, response):
        """断言 200 + ok=True，返回 data。"""
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
        body = response.data
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def bad(self, response, fragment=None):
        """断言 400 + ok=False，返回错误文案。"""
        self.assertEqual(response.status_code, 400, getattr(response, "data", None))
        body = response.data
        self.assertFalse(body.get("ok"), body)
        if fragment:
            self.assertIn(fragment, body.get("error", ""))
        return body.get("error", "")

    # ---- 数据工厂 ----

    def make_framework(self, name="ISO 27001", version="2022"):
        return Framework.objects.create(owner=self.user, name=name, version=version,
                                        kind="iso27001", status="active")

    def make_fw_control(self, framework, code, title=None, category="访问控制", weight=1):
        return FrameworkControl.objects.create(
            owner=self.user, framework=framework, code=code,
            title=title or f"条款 {code}", category=category, weight=weight,
        )

    def make_control(self, code="AC-01", name="访问控制", category="访问控制"):
        return Control.objects.create(owner=self.user, code=code, name=name,
                                      category=category, frequency="quarterly")

    def make_risk(self, code="RSK-0001", likelihood=4, impact=4):
        risk = Risk.objects.create(owner=self.user, code=code, name=f"风险 {code}",
                                   likelihood=likelihood, impact=impact,
                                   effectiveness=0)
        services.rescore(risk)
        return risk

    def make_assessment(self, framework=None, name="2026 Q1 评估"):
        return Assessment.objects.create(owner=self.user, name=name, framework=framework,
                                         status="in_progress", end_on=services.today())

    def make_audit(self, name="2026 年内部审计"):
        return Audit.objects.create(owner=self.user, name=name, kind="internal",
                                    status="in_progress")

    def make_asset(self, name="客户主数据", days=0):
        return DataAsset.objects.create(owner=self.user, name=name, kind="personal",
                                        classification="confidential",
                                        retention_days=days, contains_pii=True)


class CatalogAndFrameworkTests(GovBase):
    """目录、框架、条款、映射、覆盖率与差距。"""

    def test_catalog_exposes_endpoints(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "governance")
        self.assertGreaterEqual(len(data["endpoints"]), 52)
        self.assertEqual(data["endpoint_count"], len(data["endpoints"]))
        paths = {row["path"] for row in data["endpoints"]}
        self.assertIn("risks/matrix/", paths)
        self.assertIn("stats/dashboard/", paths)

    def test_framework_crud_and_publish(self):
        data = self.ok(self.post("frameworks/create/", {
            "name": "SOC 2", "version": "2024", "kind": "soc2", "description": "信任服务",
        }))
        self.assertEqual(data["status"], "draft")
        self.bad(self.post("frameworks/create/", {"name": "SOC 2", "version": "2024"}),
                 "已存在")
        published = self.ok(self.post(f"frameworks/{data['id']}/publish/"))
        self.assertEqual(published["status"], "active")
        detail = self.ok(self.get(f"frameworks/{data['id']}/"))
        self.assertEqual(detail["coverage"]["control_total"], 0)
        updated = self.ok(self.post(f"frameworks/{data['id']}/update/",
                                    {"name": "SOC 2 (2024)"}))
        self.assertEqual(updated["name"], "SOC 2 (2024)")
        self.ok(self.post(f"frameworks/{data['id']}/delete/"))
        self.assertEqual(Framework.objects.filter(pk=data["id"]).count(), 0)

    def test_framework_controls_and_mapping(self):
        framework = self.make_framework()
        data = self.ok(self.post("framework-controls/create/", {
            "framework_id": framework.pk, "code": "A.5.1", "title": "信息安全方针",
            "category": "方针", "weight": 3,
        }))
        self.bad(self.post("framework-controls/create/", {
            "framework_id": framework.pk, "code": "A.5.1", "title": "重复",
        }), "相同编号")
        self.bad(self.post("framework-controls/create/", {
            "framework_id": framework.pk, "code": "A.9.9", "title": "权重越界", "weight": 99,
        }), "不能大于 10")
        control = self.make_control(code="AC-01")
        linked = self.ok(self.post("control-mappings/link/", {
            "framework_control_id": data["id"], "control_id": control.pk, "strength": 90,
        }))
        self.assertTrue(linked["created"])
        again = self.ok(self.post("control-mappings/link/", {
            "framework_control_id": data["id"], "control_id": control.pk, "strength": 90,
        }))
        self.assertFalse(again["created"])
        listing = self.ok(self.get("control-mappings/"))
        self.assertEqual(listing["count"], 1)
        detail = self.ok(self.get(f"framework-controls/{data['id']}/"))
        self.assertEqual(len(detail["mappings"]), 1)
        self.ok(self.post("control-mappings/unlink/", {"id": linked["mapping"]["id"]}))
        self.assertEqual(ControlMapping.objects.count(), 0)

    def test_coverage_and_gap_analysis(self):
        framework = self.make_framework()
        covered = self.make_fw_control(framework, "A.5.1", category="方针", weight=2)
        failed = self.make_fw_control(framework, "A.8.1", category="资产", weight=1)
        missing = self.make_fw_control(framework, "A.9.1", category="访问", weight=1)
        control = self.make_control()
        # 映射挂在评估未通过的条款上：覆盖（有实施）与达成（评估通过）是两个
        # 口径，失败项计入 gaps 但仍属于「有控制覆盖」。
        ControlMapping.objects.create(owner=self.user, framework_control=failed,
                                      control=control, strength=100)
        assessment = self.make_assessment(framework)
        AssessmentItem.objects.create(owner=self.user, assessment=assessment,
                                      framework_control=covered, status="passed", weight=2)
        AssessmentItem.objects.create(owner=self.user, assessment=assessment,
                                      framework_control=failed, status="failed", weight=1)
        coverage = self.ok(self.get(f"frameworks/{framework.pk}/coverage/"))
        self.assertEqual(coverage["control_total"], 3)
        self.assertEqual(coverage["passed"], 1)
        self.assertEqual(coverage["failed"], 1)
        # covered 条款 2 条（pass + 映射），未覆盖 1 条
        self.assertEqual(coverage["covered"], 2)
        self.assertEqual(coverage["coverage_ratio"], round(2 * 100 / 3, 2))
        gaps = self.ok(self.get(f"frameworks/{framework.pk}/gaps/"))
        reasons = {gap["code"]: gap["reason"] for gap in gaps["gaps"]}
        self.assertEqual(reasons["A.9.1"], "no_mapping")
        self.assertEqual(reasons["A.8.1"], "failed")
        self.assertEqual(gaps["summary"]["no_mapping"], 1)
        self.assertEqual(len(gaps["gaps"]), 2)

    def test_framework_delete_requires_force_with_assessments(self):
        framework = self.make_framework()
        self.make_assessment(framework)
        self.bad(self.post(f"frameworks/{framework.pk}/delete/"), "force=1")
        self.ok(self.post(f"frameworks/{framework.pk}/delete/", {"force": 1}))
        self.assertEqual(Framework.objects.count(), 0)
        self.assertEqual(Assessment.objects.count(), 1)
        self.assertIsNone(Assessment.objects.first().framework_id)


class PolicyTests(GovBase):
    """策略状态机、版本快照、对比与回滚。"""

    def _policy(self):
        return self.ok(self.post("policies/create/", {
            "code": "SEC-001", "name": "信息安全方针", "kind": "security",
            "content": "第一条 总则\n第二条 适用范围", "owner_name": "张三",
        }))

    def test_policy_lifecycle_and_versions(self):
        policy = self._policy()
        self.bad(self.post(f"policies/{policy['id']}/approve/"), "不能批准")
        self.ok(self.post(f"policies/{policy['id']}/submit-review/"))
        approved = self.ok(self.post(f"policies/{policy['id']}/approve/",
                                     {"approver_name": "李四", "change_note": "首版"}))
        self.assertEqual(approved["policy"]["status"], "approved")
        self.assertEqual(approved["version"]["version"], "v1.0")
        published = self.ok(self.post(f"policies/{policy['id']}/publish/"))
        self.assertEqual(published["policy"]["status"], "published")
        self.assertIsNotNone(published["version"]["published_at"])
        again = self.ok(self.post(f"policies/{policy['id']}/publish/"))
        self.assertTrue(again["already_published"])
        versions = self.ok(self.get(f"policies/{policy['id']}/versions/"))
        self.assertEqual(versions["count"], 1)
        retired = self.ok(self.post(f"policies/{policy['id']}/retire/"))
        self.assertEqual(retired["status"], "retired")
        self.assertTrue(self.ok(self.post(f"policies/{policy['id']}/retire/"))["already_retired"])

    def test_published_content_is_immutable(self):
        policy = self._policy()
        self.ok(self.post(f"policies/{policy['id']}/submit-review/"))
        self.ok(self.post(f"policies/{policy['id']}/approve/"))
        self.ok(self.post(f"policies/{policy['id']}/publish/"))
        self.bad(self.post(f"policies/{policy['id']}/update/",
                           {"content": "未经审批的新正文"}), "不可直接修改")

    def test_version_compare_and_rollback(self):
        policy = self._policy()
        self.ok(self.post(f"policies/{policy['id']}/submit-review/"))
        first = self.ok(self.post(f"policies/{policy['id']}/approve/",
                                  {"change_note": "首版"}))
        self.ok(self.post(f"policies/{policy['id']}/publish/"))
        # 回滚前先造出第二个版本：手工写入快照（模拟后续改版）
        PolicyVersion.objects.create(
            owner=self.user, policy_id=policy["id"], version="v2.0",
            content_snapshot="第一条 总则\n第二条 适用范围\n第三条 新增条款",
            change_note="年度改版",
        )
        Policy.objects.filter(pk=policy["id"]).update(current_version="v2.0")
        compare = self.ok(self.get(f"policies/{policy['id']}/versions/compare/",
                                   {"left": "v1.0", "right": "v2.0"}))
        self.assertFalse(compare["identical"])
        self.assertEqual(compare["added"], 1)
        rollback = self.ok(self.post(f"policies/{policy['id']}/rollback/",
                                     {"version": first["version"]["version"]}))
        self.assertTrue(rollback["changed"])
        self.assertIn("-rb", rollback["policy"]["current_version"])
        target = Policy.objects.get(pk=policy["id"])
        self.assertEqual(target.content, "第一条 总则\n第二条 适用范围")
        self.assertEqual(target.status, "published")

    def test_review_reminders_and_list_filters(self):
        policy = self.ok(self.post("policies/create/", {
            "code": "PRV-001", "name": "隐私政策", "kind": "privacy",
            "next_review_on": (services.today() + timedelta(days=5)).isoformat(),
        }))
        Policy.objects.filter(pk=policy["id"]).update(status="published")
        reminders = self.ok(self.get("stats/review-reminders/", {"days": 30}))
        self.assertEqual(reminders["count"], 1)
        self.assertEqual(reminders["items"][0]["days_remaining"], 5)
        listing = self.ok(self.get("policies/", {"kind": "privacy"}))
        self.assertEqual(listing["count"], 1)
        listing = self.ok(self.get("policies/", {"q": "隐私"}))
        self.assertEqual(listing["count"], 1)


class ControlTests(GovBase):
    """控制启停、测试执行、结果历史与差距。"""

    def test_control_crud_and_toggle(self):
        data = self.ok(self.post("controls/create/", {
            "code": "AC-01", "name": "统一身份认证", "frequency": "monthly",
            "automated": True,
        }))
        self.assertTrue(data["automated"])
        self.bad(self.post("controls/create/", {"code": "AC-01", "name": "重复"}),
                 "已存在")
        toggled = self.ok(self.post(f"controls/{data['id']}/toggle/"))
        self.assertEqual(toggled["status"], "inactive")
        toggled = self.ok(self.post(f"controls/{data['id']}/toggle/"))
        self.assertEqual(toggled["status"], "active")
        updated = self.ok(self.post(f"controls/{data['id']}/update/",
                                    {"name": "统一身份认证 v2", "automated": False}))
        self.assertFalse(updated["automated"])
        self.ok(self.post(f"controls/{data['id']}/delete/"))
        self.assertEqual(Control.objects.count(), 0)

    def test_control_test_run_and_history(self):
        control = self.make_control()
        test = self.ok(self.post("control-tests/create/", {
            "control_id": control.pk, "name": "抽样核对权限", "method": "manual",
            "steps": ["导出权限清单", "比对岗位矩阵"], "pass_criteria": "无多余权限",
        }))
        self.assertEqual(test["step_count"], 2)
        first = self.ok(self.post(f"control-tests/{test['id']}/run/",
                                  {"result": "pass", "duration_ms": 120}))
        self.assertEqual(first["control_effectiveness"], 100)
        second = self.ok(self.post(f"control-tests/{test['id']}/run/",
                                   {"result": "fail", "note": "发现 3 个越权账号"}))
        self.assertEqual(second["control_effectiveness"], 0)
        history = self.ok(self.get(f"control-tests/{test['id']}/history/"))
        self.assertEqual(history["count"], 2)
        self.assertEqual(history["items"][0]["result"], "fail")
        control.refresh_from_db()
        self.assertIsNotNone(control.last_tested_at)
        self.assertEqual(ControlTestRun.objects.count(), 2)
        detail = self.ok(self.get(f"controls/{control.pk}/"))
        self.assertEqual(detail["effectiveness_detail"]["total"], 1)
        self.bad(self.post(f"control-tests/{test['id']}/run/", {"result": "maybe"}),
                 "必须是")

    def test_control_gaps(self):
        control = self.make_control()
        control.status = "inactive"
        control.save(update_fields=["status"])
        framework = self.make_framework()
        fw_control = self.make_fw_control(framework, "A.9.1")
        ControlMapping.objects.create(owner=self.user, framework_control=fw_control,
                                      control=control)
        gaps = self.ok(self.get("controls/gaps/"))
        self.assertEqual(gaps["gap_total"], 1)
        self.assertIn("inactive_mapped", gaps["controls"][0]["reasons"])


class AssessmentTests(GovBase):
    """评估创建、批量更新、加权得分与报告。"""

    def test_assessment_flow_and_weighted_score(self):
        framework = self.make_framework()
        c1 = self.make_fw_control(framework, "A.5.1", weight=3)
        c2 = self.make_fw_control(framework, "A.8.1", weight=1)
        c3 = self.make_fw_control(framework, "A.9.1", weight=1)
        created = self.ok(self.post("assessments/create/", {
            "name": "2026 年度评估", "framework_id": framework.pk,
            "scope": "全公司", "lead_name": "王五",
            "end_on": (services.today() + timedelta(days=30)).isoformat(),
        }))
        self.assertEqual(created["seeded_items"], 3)
        items = self.ok(self.get(f"assessments/{created['id']}/items/"))
        by_code = {item["framework_control_code"]: item for item in items["items"]}
        self.assertEqual(by_code["A.5.1"]["weight"], 3)
        started = self.ok(self.post(f"assessments/{created['id']}/start/"))
        self.assertEqual(started["assessment"]["status"], "in_progress")
        bulk = self.ok(self.post("assessments/items/bulk/", {
            "assessment_id": created["id"],
            "items": [
                {"id": by_code["A.5.1"]["id"], "status": "passed"},
                {"id": by_code["A.8.1"]["id"], "status": "in_progress"},
                {"id": by_code["A.9.1"]["id"], "status": "not_applicable"},
            ],
        }))
        # (3*1 + 1*0.5) / (3+1) = 0.875 → 87.5；不适用项剔除分母
        self.assertEqual(bulk["score"], 87.5)
        score = self.ok(self.get(f"assessments/{created['id']}/score/"))
        self.assertEqual(score["excluded"], 1)
        completed = self.ok(self.post(f"assessments/{created['id']}/complete/"))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["score"], 87.5)
        self.bad(self.post("assessments/items/bulk/",
                           {"assessment_id": created["id"], "items": []}), "非空数组")
        report = self.ok(self.get(f"assessments/{created['id']}/report/"))
        self.assertEqual(report["by_status"]["passed"], 1)
        self.assertEqual(report["by_status"]["failed"], 0)
        self.assertEqual(report["by_category"][0]["category"], "访问控制")
        self.assertEqual(c1.code, "A.5.1")
        self.assertEqual(c2.code, "A.8.1")
        self.assertEqual(c3.code, "A.9.1")

    def test_assessment_item_crud_and_foreign_guard(self):
        framework = self.make_framework()
        assessment = self.make_assessment(framework)
        other_framework = self.make_framework(name="自定义框架", version="1")
        foreign = self.make_fw_control(other_framework, "C.1")
        self.bad(self.post("assessments/items/create/", {
            "assessment_id": assessment.pk, "framework_control_id": foreign.pk,
        }), "不属于该评估的框架")
        control = self.make_control()
        item = self.ok(self.post("assessments/items/create/", {
            "assessment_id": assessment.pk, "control_id": control.pk,
            "status": "passed", "weight": 2, "note": "已核对",
        }))
        updated = self.ok(self.post(f"assessment-items/{item['id']}/update/",
                                    {"status": "failed", "note": "证据不足"}))
        self.assertEqual(updated["status"], "failed")
        self.ok(self.post(f"assessment-items/{item['id']}/delete/"))
        self.assertEqual(AssessmentItem.objects.count(), 0)

    def test_overdue_assessment_effective_status(self):
        assessment = self.make_assessment()
        Assessment.objects.filter(pk=assessment.pk).update(
            status="in_progress", end_on=services.today() - timedelta(days=1))
        listing = self.ok(self.get("assessments/", {"effective_status": "overdue"}))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["effective_status"], "overdue")


class EvidenceTests(GovBase):
    """证据登记、哈希校验与过期列表。"""

    def test_evidence_hash_verification(self):
        digest = services.compute_hash("审计报告正文", "sha256")
        data = self.ok(self.post("evidences/create/", {
            "target_kind": "control", "target_id": 1, "name": "权限清单快照",
            "kind": "hash", "hash_value": digest,
            "expires_on": (services.today() + timedelta(days=10)).isoformat(),
        }))
        good = self.ok(self.post(f"evidences/{data['id']}/verify/",
                                 {"content": "审计报告正文"}))
        self.assertTrue(good["ok"])
        bad = self.ok(self.post(f"evidences/{data['id']}/verify/",
                                {"content": "被篡改的内容"}))
        self.assertFalse(bad["ok"])
        self.assertIn("哈希与登记值不一致", bad["notes"])
        self.bad(self.post("evidences/create/", {
            "target_kind": "control", "target_id": 2, "name": "非法算法",
            "hash_value": "crc32:abcd",
        }), "不支持的哈希算法")
        self.bad(self.post("evidences/create/", {
            "target_kind": "control", "target_id": 2, "name": "类型不符", "kind": "hash",
        }), "必须提供 hash_value")

    def test_expired_evidence_listing(self):
        Evidence.objects.create(owner=self.user, target_kind="policy", target_id=1,
                                name="过期证据", kind="link",
                                expires_on=services.today() - timedelta(days=1),
                                hash_value=services.compute_hash("x"))
        Evidence.objects.create(owner=self.user, target_kind="policy", target_id=2,
                                name="即将到期", kind="link",
                                expires_on=services.today() + timedelta(days=3),
                                hash_value=services.compute_hash("y"))
        expired = self.ok(self.get("evidences/expired/"))
        self.assertEqual(expired["count"], 1)
        soon = self.ok(self.get("evidences/expired/", {"days": 7, "only_expired": 0}))
        self.assertEqual(soon["count"], 2)


class RiskTests(GovBase):
    """风险评分矩阵、重新评分、处置闭环。"""

    def test_matrix_scoring_and_rescore(self):
        risk = self.make_risk(likelihood=5, impact=5)
        self.assertEqual(risk.inherent_score, 25)
        self.assertEqual(risk.level, "critical")
        rescored = self.ok(self.post(f"risks/{risk.pk}/rescore/", {"effectiveness": 80}))
        # 25 × (1 - 0.8) = 5 → 中风险
        self.assertEqual(rescored["scoring"]["residual_score"], 5)
        self.assertEqual(rescored["scoring"]["level"], "medium")
        matrix = self.ok(self.get("risks/matrix/"))
        self.assertEqual(len(matrix["grid"]), 25)
        self.assertEqual(len(matrix["bands"]), 4)
        self.assertEqual(matrix["risks"][0]["id"], risk.pk)
        distribution = self.ok(self.get("stats/risk-distribution/"))
        self.assertEqual(distribution["by_level"]["medium"], 1)
        self.assertEqual(distribution["total"], 1)

    def test_risk_create_autocode_and_validation(self):
        data = self.ok(self.post("risks/create/", {
            "name": "供应商数据泄露", "likelihood": 3, "impact": 4,
            "category": "第三方",
        }))
        self.assertTrue(data["code"].startswith("RSK-"))
        self.assertEqual(data["inherent_score"], 12)
        self.bad(self.post("risks/create/", {"name": "越界", "likelihood": 9}),
                 "不能大于 5")
        self.bad(self.post("risks/create/", {"likelihood": 2, "impact": 3}),
                 "缺少必填参数")
        second = self.ok(self.post("risks/create/", {"name": "第二个风险"}))
        self.assertNotEqual(second["code"], data["code"])

    def test_treatment_lifecycle(self):
        risk = self.make_risk()
        self.bad(self.post("risks/treatments/create/", {
            "risk_id": risk.pk, "strategy": "accept", "action": "  ",
        }), "接受理由")
        treatment = self.ok(self.post("risks/treatments/create/", {
            "risk_id": risk.pk, "strategy": "mitigate", "action": "上线数据脱敏",
            "owner_name": "赵六", "due_on": services.today().isoformat(),
        }))
        risk.refresh_from_db()
        self.assertEqual(risk.status, "treating")
        # type: RiskTreatment 存在
        self.assertEqual(RiskTreatment.objects.count(), 1)
        done = self.ok(self.post(f"risk-treatments/{treatment['id']}/complete/"))
        self.assertTrue(done["changed"])
        self.assertEqual(done["risk_status"], "monitored")
        again = self.ok(self.post(f"risk-treatments/{treatment['id']}/complete/"))
        self.assertFalse(again["changed"])

    def test_risk_matrix_bands_are_seeded_once(self):
        self.ok(self.get("risks/matrix/"))
        self.ok(self.get("risks/matrix/"))
        self.assertEqual(RiskMatrixBand.objects.filter(owner=self.user).count(), 4)


class PrivacyTests(GovBase):
    """数据资产分类统计、处理活动 DPIA 与风险关联。"""

    def test_data_asset_crud_and_classification(self):
        asset = self.ok(self.post("data-assets/create/", {
            "name": "客户主数据", "kind": "personal", "classification": "confidential",
            "retention_days": 180, "contains_pii": True, "storage_location": "cn-north-1",
        }))
        self.assertTrue(asset["contains_pii"])
        self.assertIsNotNone(asset["retention_due_on"])
        DataAsset.objects.create(owner=self.user, name="日志", kind="operational",
                                 classification="internal")
        stats = self.ok(self.get("data-assets/classification/"))
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_classification"]["confidential"], 1)
        self.assertEqual(stats["contains_pii"], 1)
        self.assertEqual(stats["without_retention_policy"], 1)
        updated = self.ok(self.post(f"data-assets/{asset['id']}/update/",
                                    {"classification": "restricted"}))
        self.assertEqual(updated["classification"], "restricted")

    def test_processing_dpia_and_risk_link(self):
        activity = self.ok(self.post("processing-activities/create/", {
            "name": "营销画像", "purpose": "个性化推荐",
            "legal_basis": "同意", "data_categories": ["浏览记录"],
            "subject_categories": ["用户"], "cross_border": True,
        }))
        self.assertTrue(activity["cross_border"])
        first = self.ok(self.post(f"processing-activities/{activity['id']}/dpia/"))
        self.assertFalse(first["already_done"])
        self.assertEqual(first["activity"]["status"], "active")
        second = self.ok(self.post(f"processing-activities/{activity['id']}/dpia/"))
        self.assertTrue(second["already_done"])
        risk = self.make_risk()
        self.ok(self.post(f"processing-activities/{activity['id']}/risks/link/",
                          {"risk_id": risk.pk}))
        self.ok(self.post(f"processing-activities/{activity['id']}/risks/link/",
                          {"risk_id": risk.pk}))
        linked = self.ok(self.get(f"processing-activities/{activity['id']}/risks/"))
        self.assertEqual(linked["count"], 1)
        detail = self.ok(self.get(f"processing-activities/{activity['id']}/"))
        self.assertEqual(len(detail["risks"]), 1)
        self.ok(self.post(f"processing-activities/{activity['id']}/risks/unlink/",
                          {"risk_id": risk.pk}))
        self.assertEqual(ProcessingActivity.objects.get(pk=activity["id"]).risks.count(), 0)


class RetentionTests(GovBase):
    """保留规则、扫描幂等与执行。"""

    def test_scan_is_idempotent_and_execute_marks_asset(self):
        rule = self.ok(self.post("retention-rules/create/", {
            "resource_kind": "data_asset", "retention_days": 30, "due_action": "archive",
        }))
        self.bad(self.post("retention-rules/create/", {
            "resource_kind": "data_asset", "retention_days": 10,
        }), "已存在")
        asset = self.make_asset(days=1)
        DataAsset.objects.filter(pk=asset.pk).update(
            created_at=timezone.now() - timedelta(days=5))
        first = self.ok(self.post("retention/scan/"))
        self.assertEqual(first["due_total"], 1)
        self.assertEqual(first["created"], 1)
        second = self.ok(self.post("retention/scan/"))
        self.assertEqual(second["created"], 0)
        self.assertEqual(RetentionAction.objects.count(), 1)
        due = self.ok(self.get("retention/due/"))
        self.assertEqual(due["count"], 1)
        action_id = due["items"][0]["id"]
        executed = self.ok(self.post("retention/execute/", {"action_id": action_id}))
        self.assertTrue(executed["changed"])
        self.assertEqual(executed["applied"]["status"], "archived")
        replay = self.ok(self.post("retention/execute/", {"action_id": action_id}))
        self.assertFalse(replay["changed"])
        self.assertEqual(replay["reason"], "already_executed")
        asset.refresh_from_db()
        self.assertEqual(asset.status, "archived")
        self.assertEqual(rule["due_action"], "archive")

    def test_consent_validity_and_withdraw(self):
        consent = self.ok(self.post("consents/create/", {
            "data_subject": "user@example.com", "purpose": "营销邮件",
            "source": "官网表单", "evidence_ref": "form-2026-01",
            "expires_on": (services.today() + timedelta(days=30)).isoformat(),
        }))
        valid = self.ok(self.get(f"consents/{consent['id']}/validity/"))
        self.assertTrue(valid["valid"])
        mismatch = self.ok(self.get(f"consents/{consent['id']}/validity/",
                                    {"purpose": "征信查询"}))
        self.assertFalse(mismatch["valid"])
        self.assertIn("目的与请求不一致", mismatch["reasons"])
        withdrawn = self.ok(self.post(f"consents/{consent['id']}/withdraw/"))
        self.assertFalse(withdrawn["already_withdrawn"])
        self.assertTrue(self.ok(self.post(f"consents/{consent['id']}/withdraw/"))["already_withdrawn"])
        after = self.ok(self.get(f"consents/{consent['id']}/validity/"))
        self.assertFalse(after["valid"])
        self.assertIn("同意已撤回", after["reasons"])
        summary = self.ok(self.get("consents/summary/"))
        self.assertEqual(summary["by_status"]["withdrawn"], 1)

    def test_expired_consent_detected_by_date(self):
        ConsentRecord.objects.create(owner=self.user, data_subject="a@b.com",
                                     purpose="分析", status="granted",
                                     expires_on=services.today() - timedelta(days=1))
        consent = ConsentRecord.objects.first()
        result = services.consent_validity(consent)
        self.assertFalse(result["valid"])
        self.assertIn("同意已超过有效期", result["reasons"])


class AuditTests(GovBase):
    """审计发现、整改验证闭环与趋势统计。"""

    def test_finding_remediation_closure(self):
        audit = self.make_audit()
        finding = self.ok(self.post("audits/findings/create/", {
            "audit_id": audit.pk,
            "title": "离职账号未及时回收", "severity": "high",
            "remediation_owner": "运维", "due_on": services.today().isoformat(),
        }))
        self.bad(self.post(f"findings/{finding['id']}/update/", {"status": "verified"}),
                 "整改任务验证")
        task = self.ok(self.post("findings/remediations/create/", {
            "finding_id": finding["id"],
            "measure": "接入离职自动回收脚本", "owner_name": "运维",
            "due_on": services.today().isoformat(),
        }))
        Finding.objects.filter(pk=finding["id"]).update(status="in_progress")
        self.ok(self.post(f"remediations/{task['id']}/update/", {"status": "done"}))
        verified = self.ok(self.post(f"remediations/{task['id']}/verify/",
                                     {"verifier_name": "合规负责人"}))
        self.assertFalse(verified["already_verified"])
        self.assertEqual(verified["finding_status"], "verified")
        again = self.ok(self.post(f"remediations/{task['id']}/verify/"))
        self.assertTrue(again["already_verified"])
        detail = self.ok(self.get(f"findings/{finding['id']}/"))
        self.assertEqual(detail["status"], "verified")
        self.assertIsNotNone(detail["closed_on"])

    def test_overdue_findings_and_trend(self):
        audit = self.make_audit()
        overdue_finding = Finding.objects.create(
            owner=self.user, audit=audit, title="逾期项", severity="critical",
            status="open", due_on=services.today() - timedelta(days=3))
        RemediationTask.objects.create(owner=self.user, finding=overdue_finding,
                                       measure="限期整改", owner_name="运维",
                                       status="open",
                                       due_on=services.today() - timedelta(days=2))
        Finding.objects.create(owner=self.user, audit=audit, title="已关闭项",
                               severity="low", status="verified",
                               due_on=services.today() - timedelta(days=3),
                               closed_on=services.today())
        overdue = self.ok(self.get("findings/", {"overdue": 1}))
        self.assertEqual(overdue["count"], 1)
        trend = self.ok(self.get("stats/finding-trend/", {"months": 3}))
        self.assertEqual(len(trend["series"]), 3)
        self.assertEqual(trend["totals"]["opened"], 2)
        timeliness = self.ok(self.get("stats/overdue-remediations/"))
        self.assertEqual(timeliness["overdue"], 1)
        detail = self.ok(self.get(f"audits/{audit.pk}/"))
        self.assertEqual(detail["by_severity"]["critical"], 1)
        self.assertEqual(detail["overdue_findings"], 1)


class StatsAndPermissionTests(GovBase):
    """看板汇总、分页上限、权限隔离与管理员放行。"""

    def test_dashboard_aggregates(self):
        framework = self.make_framework()
        self.make_fw_control(framework, "A.5.1")
        self.make_risk(likelihood=2, impact=2)
        self.make_asset(days=30)
        self.ok(self.post("retention-rules/create/", {
            "resource_kind": "data_asset", "retention_days": 30, "due_action": "delete",
        }))
        data = self.ok(self.get("stats/dashboard/"))
        self.assertEqual(data["frameworks"]["count"], 1)
        self.assertEqual(data["risks"]["total"], 1)
        self.assertEqual(data["controls"]["total"], 0)
        self.assertEqual(data["dpia"]["activity_total"], 0)
        coverage = self.ok(self.get("stats/framework-coverage/"))
        self.assertEqual(coverage["count"], 1)
        self.assertEqual(coverage["average_coverage"], 0.0)

    def test_pagination_and_search(self):
        for index in range(3):
            Control.objects.create(owner=self.user, code=f"C-{index:03d}",
                                   name=f"控制 {index}", category="通用")
        page = self.ok(self.get("controls/", {"page_size": 2, "page": 2}))
        self.assertEqual(page["page_size"], 2)
        self.assertEqual(page["page"], 2)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["count"], 3)
        self.bad(self.get("controls/", {"page_size": 500}), "不能大于 200")
        found = self.ok(self.get("controls/", {"q": "控制 2"}))
        self.assertEqual(found["count"], 1)

    def test_row_level_isolation(self):
        framework = self.make_framework()
        self.as_user(self.other)
        self.assertEqual(self.ok(self.get("frameworks/"))["count"], 0)
        self.bad(self.post(f"frameworks/{framework.pk}/update/", {"name": "越权"}),
                 "无权")
        self.bad(self.get(f"frameworks/{framework.pk}/"), "无权访问")
        # 读范围之外的对象直接不可见，哪怕数据范围最宽也不越权写
        self.assertEqual(self.ok(self.get("stats/dashboard/"))["risks"]["total"], 0)

    def test_admin_can_publish_others_policy(self):
        policy = Policy.objects.create(owner=self.user, code="SEC-9", name="待发布",
                                       status="approved", content="正文")
        self.as_user(self.admin)
        published = self.ok(self.post(f"policies/{policy.pk}/publish/"))
        self.assertEqual(published["policy"]["status"], "published")
        self.assertEqual(PolicyVersion.objects.filter(policy=policy).count(), 1)

    def test_validation_errors_are_chinese(self):
        error = self.bad(self.post("frameworks/create/", {"name": ""}), "缺少必填参数")
        self.assertIn("name", error)
        self.bad(self.post("frameworks/create/", {"name": "x", "kind": "nist"}),
                 "必须是")
        self.bad(self.post("risks/create/", {"name": "r", "likelihood": "abc"}),
                 "必须是整数")


class ServiceUnitTests(GovBase):
    """服务层纯函数口径（不依赖接口）。"""

    def test_score_helpers(self):
        self.assertEqual(services.risk_score(3, 4), 12)
        self.assertEqual(services.band_for_score(4)["level"], "low")
        self.assertEqual(services.band_for_score(9)["level"], "medium")
        self.assertEqual(services.band_for_score(14)["level"], "high")
        self.assertEqual(services.band_for_score(25)["level"], "critical")
        self.assertEqual(services.effectiveness_coefficient(0), 1.0)
        self.assertEqual(services.effectiveness_coefficient(100), 0.0)
        self.assertEqual(services.residual_score_of(25, 0.5), 13)  # 四舍五入，非银行家舍入
        self.assertEqual(services.residual_score_of(1, 0.0), 1)

    def test_percentage_guard(self):
        self.assertEqual(services.pct(0, 0), 0.0)
        self.assertEqual(services.pct(1, 3), 33.33)

    def test_hash_helpers(self):
        digest = services.compute_hash("abc", "sha256")
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest.split(":")[1]), 64)
        algorithm, value = services.split_hash(digest)
        self.assertEqual(algorithm, "sha256")
        self.assertEqual(value, digest.split(":")[1])
        self.assertEqual(services.split_hash("deadbeef")[0], "sha256")
        with self.assertRaises(ValueError):
            services.split_hash("sha3:abc")

    def test_month_range_fills_gaps(self):
        keys = services.month_range(services.today(), 3)
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[-1], services.today().strftime("%Y-%m"))


class TemplateTests(GovBase):
    """内置条款库：预览、按模板建框架、重复应用幂等。"""

    def test_template_catalog_and_detail(self):
        catalog = self.ok(self.get("templates/"))
        self.assertEqual(catalog["count"], 3)
        by_kind = {row["kind"]: row for row in catalog["items"]}
        self.assertGreaterEqual(by_kind["iso27001"]["control_total"], 20)
        self.assertGreaterEqual(by_kind["gdpr"]["control_total"], 16)
        self.assertGreaterEqual(by_kind["soc2"]["control_total"], 16)
        detail = self.ok(self.get("templates/iso27001/"))
        self.assertEqual(len(detail["items"]), detail["control_total"])
        self.assertEqual(detail["items"][0]["code"], "A.5.1")
        self.assertTrue(detail["categories"])
        self.bad(self.get("templates/nist/"), "未知模板")

    def test_framework_from_template_and_idempotent_apply(self):
        created = self.ok(self.post("frameworks/from-template/", {"kind": "gdpr"}))
        self.assertEqual(created["kind"], "gdpr")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["apply"]["created"], created["apply"]["total"])
        self.assertEqual(
            FrameworkControl.objects.filter(framework_id=created["id"]).count(),
            created["apply"]["total"])
        # 重复应用同一模板：只补缺，不重复写入
        again = self.ok(self.post(f"frameworks/{created['id']}/apply-template/"))
        self.assertEqual(again["apply"]["created"], 0)
        self.assertEqual(again["apply"]["skipped"], again["apply"]["total"])
        refreshed = self.ok(self.post(f"frameworks/{created['id']}/apply-template/",
                                      {"update_existing": True}))
        self.assertEqual(refreshed["apply"]["created"], 0)
        self.assertEqual(refreshed["apply"]["updated"], 0)
        # custom 框架没有内置条款：不指定 kind 时给出可操作提示
        custom = Framework.objects.create(owner=self.user, name="自建框架",
                                          version="1", kind="custom")
        self.bad(self.post(f"frameworks/{custom.pk}/apply-template/"), "没有可用的内置条款库")
        applied = self.ok(self.post(f"frameworks/{custom.pk}/apply-template/",
                                    {"kind": "soc2"}))
        self.assertGreater(applied["apply"]["created"], 0)
        # 同名同版本重复建框架被拒绝
        self.bad(self.post("frameworks/from-template/", {
            "kind": "gdpr", "name": created["name"], "version": created["version"],
        }), "已存在")

    def test_template_requires_kind(self):
        self.bad(self.post("frameworks/from-template/"), "缺少必填参数")


class CalendarTests(GovBase):
    """合规日历：多来源聚合、逾期置顶、iCalendar 导出与测试计划。"""

    def _seed_due_items(self):
        Policy.objects.create(owner=self.user, code="PRV-100", name="隐私政策",
                              status="published",
                              next_review_on=services.today() + timedelta(days=3))
        risk = self.make_risk()
        Risk.objects.filter(pk=risk.pk).update(review_on=services.today() - timedelta(days=1))
        ConsentRecord.objects.create(owner=self.user, data_subject="a@b.com",
                                     purpose="营销", status="granted",
                                     expires_on=services.today() + timedelta(days=2))

    def test_calendar_aggregates_and_prioritises_overdue(self):
        self._seed_due_items()
        data = self.ok(self.get("stats/calendar/", {"days": 7}))
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["overdue"], 1)
        self.assertEqual(data["by_kind"]["policy_review"], 1)
        self.assertEqual(data["by_kind"]["consent_expiry"], 1)
        self.assertEqual(data["items"][0]["kind"], "risk_review")
        self.assertTrue(data["items"][0]["overdue"])
        self.assertEqual(data["items"][0]["days_remaining"], -1)
        filtered = self.ok(self.get("stats/calendar/",
                                    {"days": 7, "sources": "consent_expiry,policy_review"}))
        self.assertEqual(filtered["count"], 2)
        self.assertNotIn("risk_review", filtered["by_kind"])
        summary = self.ok(self.get("stats/calendar/summary/", {"days": 7}))
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["due_soon"], 2)
        sources = self.ok(self.get("stats/calendar/sources/"))
        self.assertEqual(sources["count"], 9)

    def test_calendar_ics_export(self):
        self._seed_due_items()
        data = self.ok(self.get("stats/calendar/ics/", {"days": 7}))
        self.assertTrue(data["filename"].endswith(".ics"))
        self.assertEqual(data["event_total"], 3)
        self.assertTrue(data["content"].startswith("BEGIN:VCALENDAR"))
        self.assertIn("BEGIN:VEVENT", data["content"])
        self.assertIn("DTSTART;VALUE=DATE:", data["content"])
        self.assertTrue(data["content"].rstrip().endswith("END:VCALENDAR"))

    def test_control_test_plan(self):
        control = self.make_control()
        # 季度控制窗口 100 天：95 天前测过 → 5 天后到期（计划内、未逾期）
        Control.objects.filter(pk=control.pk).update(
            last_tested_at=timezone.now() - timedelta(days=95))
        plan = self.ok(self.get("stats/control-plan/", {"days": 30}))
        self.assertEqual(plan["count"], 1)
        self.assertEqual(plan["items"][0]["days_remaining"], 5)
        self.assertFalse(plan["items"][0]["overdue"])
        narrowing = self.ok(self.get("stats/control-plan/", {"days": 3}))
        self.assertEqual(narrowing["count"], 0)

    def test_workload_summary(self):
        audit = self.make_audit()
        finding = Finding.objects.create(
            owner=self.user, audit=audit, title="账号回收", severity="high",
            status="open", remediation_owner="张三",
            due_on=services.today() - timedelta(days=2))
        Finding.objects.create(owner=self.user, audit=audit, title="日志留存",
                               severity="low", status="open", remediation_owner="张三")
        RemediationTask.objects.create(owner=self.user, finding=finding, measure="脚本回收",
                                       owner_name="张三", status="open",
                                       due_on=services.today() - timedelta(days=1))
        RemediationTask.objects.create(owner=self.user, finding=finding, measure="培训",
                                       owner_name="李四", status="done")
        data = self.ok(self.get("stats/workload/"))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["owner_name"], "张三")
        self.assertEqual(data["items"][0]["total"], 3)
        self.assertEqual(data["items"][0]["overdue"], 2)
        self.assertEqual(data["items"][0]["load_score"], 7)


class ExportTests(GovBase):
    """CSV 导出：结构、公式注入防护、行数上限与可见性。"""

    def test_export_catalog_and_risk_csv(self):
        self.make_risk(code="RSK-1001")
        catalog = self.ok(self.get("exports/"))
        self.assertEqual(catalog["count"], 5)
        data = self.ok(self.get("exports/risks/"))
        self.assertEqual(data["format"], "csv")
        self.assertEqual(data["count"], 1)
        self.assertFalse(data["truncated"])
        self.assertIn("编号", data["content"])
        self.assertIn("RSK-1001", data["content"])
        self.assertTrue(data["filename"].startswith("governance-risks-"))
        controls = self.ok(self.get("exports/controls/"))
        self.assertEqual(controls["headers"][0], "编号")
        self.assertEqual(controls["count"], 0)
        findings = self.ok(self.get("exports/findings/"))
        self.assertEqual(findings["count"], 0)
        actions = self.ok(self.get("exports/retention-actions/"))
        self.assertEqual(actions["count"], 0)

    def test_export_neutralises_formula_injection(self):
        self.make_risk(code="RSK-1002")
        Risk.objects.filter(code="RSK-1002").update(name='=HYPERLINK("http://evil")')
        data = self.ok(self.get("exports/risks/"))
        self.assertIn("'=HYPERLINK", data["content"])

    def test_export_limit_and_visibility(self):
        self.make_risk(code="RSK-1003")
        self.make_risk(code="RSK-1004")
        limited = self.ok(self.get("exports/risks/", {"limit": 1}))
        self.assertEqual(limited["count"], 1)
        self.assertTrue(limited["truncated"])
        self.bad(self.get("exports/risks/", {"limit": 0}), "不能小于")
        foreign = Assessment.objects.create(owner=self.other, name="外部评估",
                                           status="planned")
        self.bad(self.get("exports/assessment-items/", {"assessment_id": foreign.pk}),
                 "无权访问该评估")

    def test_csv_cell_helpers(self):
        self.assertEqual(services.csv_cell(None), "")
        self.assertEqual(services.csv_cell(True), "是")
        self.assertEqual(services.csv_cell("-5"), "'-5")
        self.assertEqual(services.csv_cell(services.today()), services.today().isoformat())
