# -*- coding: utf-8 -*-
"""contracts 测试：模板渲染、合同状态机、版本、履约、变更、财务、风险、提醒、统计与权限。

运行方式（项目内 `backend/code` 包会遮蔽标准库 code，导致 manage.py test 的 pdb
导入失败，因此用 --pdb 之外的常规入口即可；若命令行直接跑 manage.py test 报
`module 'code' has no attribute 'InteractiveConsole'`，用下面的等价方式）：

    venv/Scripts/python.exe manage.py test contracts --settings=config.settings

本文件也刻意不依赖迁移：contracts 的 migrations 包为空，测试库不会自动建表，
所以每个 TestCase 在 setUpClass 里按依赖顺序补建本应用的表（只作用于测试库）。
"""
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from contracts import services, state
from contracts.models import Contract, ContractAudit, ContractTemplate

User = get_user_model()

BASE = "/api/contracts/"


def ensure_contracts_tables():
    """测试库补建 contracts 表（幂等，只影响测试库）。

    本应用当前不提交迁移文件（迁移统一生成是独立任务），但空的 migrations 包
    会让 Django 认为应用「已迁移但没有迁移」，测试库不会 sync 建表。这里按
    依赖顺序补建：先建没有本应用外键的表，再建引用它们的表，避免 SQLite 在
    DDL 阶段对缺失目标表报错。
    """
    existing = set(connection.introspection.table_names())
    pending = [model for model in apps.get_app_config("contracts").get_models()
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
                if related._meta.app_label != "contracts":
                    continue
                if related._meta.db_table not in existing:
                    deps.add(related)
            if not deps:
                ordered.append(model)
                pending.remove(model)
                progressed = True
        if not progressed:
            # Contract ↔ ContractVersion 互相引用，无法拓扑排序；SQLite 允许
            # 建表时引用尚不存在的表，剩余模型按声明顺序补齐即可。
            ordered.extend(pending)
            break
    with connection.schema_editor() as editor:
        for model in ordered:
            if model._meta.db_table not in existing:
                editor.create_model(model)
                existing.add(model._meta.db_table)


class ApiTestBase(TestCase):
    """接口测试基类：三个用户、客户端、通用断言与数据工厂。"""

    @classmethod
    def setUpClass(cls):
        ensure_contracts_tables()
        super().setUpClass()

    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", password="pass1234", nickname="爱丽丝")
        self.other = User.objects.create_user(
            username="bob", password="pass1234", nickname="鲍勃")
        self.admin = User.objects.create_user(
            username="root", password="pass1234", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    # ---- 请求 helper ----

    def get(self, path, params=None):
        return self.client.get(BASE + path, params or {})

    def post(self, path, data=None):
        return self.client.post(BASE + path, data if data is not None else {},
                                format="json")

    def as_user(self, user):
        self.client.force_authenticate(user)

    # ---- 断言 helper ----

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def bad(self, response, status=400):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertFalse(body.get("ok"), body)
        return body

    # ---- 数据工厂 ----

    def create_contract(self, **overrides):
        payload = {
            "name": "年度技术服务合同",
            "contract_type": "service",
            "amount": "200000.00",
            "currency": "CNY",
            "effective_date": timezone.localdate().isoformat(),
            "expire_date": (timezone.localdate() + timedelta(days=90)).isoformat(),
            "counterparty_name": "乙方科技有限公司",
            "parties": [{"name": "甲方科技有限公司", "role": "party_a",
                         "credit_code": "91310000MA1FL0000X"},
                        {"name": "乙方科技有限公司", "role": "party_b"}],
            "body": "第一条 合作范围\n双方就年度技术服务达成一致。\n"
                    "第二条 付款\n甲方按期付款。",
        }
        payload.update(overrides)
        return self.ok(self.post("contracts/create/", payload))

    def create_template(self, code="TPL-001", **overrides):
        payload = {
            "code": code,
            "name": "技术服务模板",
            "template_type": "service",
            "scene": "年度服务",
            "body": "甲方：{{party_a}}\n金额：{{amount|0}} 元\n{{clause}}",
            "variables": [
                {"name": "party_a", "label": "甲方", "required": True},
                {"name": "amount", "label": "金额", "required": False,
                 "default": "0"},
                {"name": "clause", "label": "补充条款", "required": False,
                 "default": ""},
            ],
        }
        payload.update(overrides)
        return self.ok(self.post("templates/create/", payload))

    def approve_all(self, contract_id):
        data = self.ok(self.post(f"contracts/{contract_id}/approve/", {}))
        guard = 0
        while data["status"] == "reviewing" and guard < 10:
            data = self.ok(self.post(f"contracts/{contract_id}/approve/", {}))
            guard += 1
        return data

    def activate_contract(self, contract_id, sign_now=True):
        self.ok(self.post(f"contracts/{contract_id}/submit/", {}))
        self.approve_all(contract_id)
        self.ok(self.post(f"contracts/{contract_id}/sign/",
                          {"sign_now": sign_now}))
        return self.ok(self.post(f"contracts/{contract_id}/activate/", {}))


class CatalogTests(ApiTestBase):
    """目录 / 元信息 / 规模。"""

    def test_catalog_and_meta(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "contracts")
        self.assertGreaterEqual(len(data["endpoints"]), 80)
        self.assertEqual(data["endpoints"].__class__, list)
        paths = {row["path"] for row in data["endpoints"]}
        self.assertIn("contracts/", paths)
        self.assertIn("templates/", paths)

        meta = self.ok(self.get("meta/"))
        self.assertEqual(meta["expiry_stages"], [30, 15, 7, 1])
        self.assertIn("draft", meta["enums"]["contract_status"])
        self.assertIn("purchase", meta["contract_type_keys"])
        self.assertEqual(len(meta["approval_thresholds"]), 4)

    def test_counts(self):
        self.create_contract()
        data = self.ok(self.get("counts/"))
        self.assertEqual(data["contracts"], 1)
        self.assertEqual(data["templates"], 0)


class TemplateTests(ApiTestBase):
    """模板 CRUD / 发布 / 渲染 / 克隆 / 条款与条款库。"""

    def test_template_lifecycle(self):
        created = self.create_template()
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["variable_names"], ["amount", "clause", "party_a"])

        # 编码重复必须被拦住（唯一约束在应用层先给出中文提示）
        self.bad(self.post("templates/create/", {"code": "TPL-001", "name": "重复"}))

        detail = self.ok(self.get(f"templates/{created['id']}/"))
        self.assertIn("{{party_a}}", detail["body"])
        self.assertEqual(detail["clauses"], [])

        listed = self.ok(self.get("templates/", {"q": "技术", "page_size": 10}))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["page"], 1)

        published = self.ok(self.post(f"templates/{created['id']}/publish/", {}))
        self.assertEqual(published["status"], "published")
        self.bad(self.post(f"templates/{created['id']}/publish/", {}))

        rendered = self.ok(self.post(f"templates/{created['id']}/render/",
                                     {"variables": {"party_a": "甲公司"}}))
        self.assertIn("甲公司", rendered["body"])
        self.assertEqual(rendered["unresolved"], [])
        # 必填变量缺失必须报错，而不是渲染成空串
        self.bad(self.post(f"templates/{created['id']}/render/", {"variables": {}}))
        # 未声明占位符同样要报错（白名单）
        self.bad(self.post(f"templates/{created['id']}/render/",
                           {"variables": {"party_a": "甲", "other": "x"}}))

        # 正文占位符未声明变量时禁止发布
        second = self.create_template(code="TPL-002", body="甲方：{{ghost}}",
                                      variables=[{"name": "party_a"}])
        self.bad(self.post(f"templates/{second['id']}/publish/", {}))

    def test_template_update_clone_disable(self):
        created = self.create_template()
        updated = self.ok(self.post(f"templates/{created['id']}/update/",
                                    {"name": "新版模板", "body": "甲方：{{party_a}}"}))
        self.assertEqual(updated["name"], "新版模板")
        self.assertEqual(updated["version"], "v1.1")

        clone = self.ok(self.post(f"templates/{created['id']}/clone/", {}))
        self.assertNotEqual(clone["code"], created["code"])
        self.assertEqual(clone["source_id"], created["id"])

        self.ok(self.post(f"templates/{created['id']}/publish/", {}))
        # 已发布模板不能直接删除
        self.bad(self.post(f"templates/{created['id']}/delete/", {}))
        self.ok(self.post(f"templates/{created['id']}/disable/", {}))
        self.bad(self.post(f"templates/{created['id']}/disable/", {}))
        self.ok(self.post(f"templates/{created['id']}/delete/", {}))

    def test_clauses_and_library(self):
        template = self.create_template()
        first = self.ok(self.post(f"templates/{template['id']}/clauses/add/",
                                  {"title": "保密条款", "body": "双方保密。",
                                   "risk_level": "medium"}))
        second = self.ok(self.post(f"templates/{template['id']}/clauses/add/",
                                   {"title": "违约条款", "body": "违约方赔偿。",
                                    "risk_level": "high", "alt_group": "责任"}))
        self.assertEqual(first["order"], 1)
        self.assertEqual(second["order"], 2)

        listed = self.ok(self.get(f"templates/{template['id']}/clauses/"))
        self.assertEqual(listed["count"], 2)

        reordered = self.ok(self.post(f"templates/{template['id']}/clauses/reorder/",
                                      {"ids": [second["id"], first["id"]]}))
        self.assertEqual(reordered["count"], 2)
        detail = self.ok(self.get(f"templates/{template['id']}/clauses/"))
        self.assertEqual(detail["items"][0]["title"], "违约条款")

        library = self.ok(self.post("clauses/library/create/", {
            "category": "争议解决", "title": "仲裁条款",
            "body": "提交上海仲裁委员会仲裁。", "risk_level": "low",
            "tags": ["仲裁", "争议"],
        }))
        stats = self.ok(self.get("clauses/library/stats/"))
        self.assertEqual(stats["by_category"]["争议解决"], 1)

        from_library = self.ok(self.post(
            f"templates/{template['id']}/clauses/from-library/",
            {"library_id": library["id"]}))
        self.assertEqual(from_library["library_id"], library["id"])

        # 库条目删除为停用，不影响已实例化条款
        disabled = self.ok(self.post(f"clauses/library/{library['id']}/delete/", {}))
        self.assertEqual(disabled["status"], "disabled")
        self.bad(self.post(f"templates/{template['id']}/clauses/from-library/",
                           {"library_id": library["id"]}))

        self.ok(self.post(f"clauses/{first['id']}/update/",
                          {"optional": True, "risk_level": "low"}))
        self.ok(self.post(f"clauses/{first['id']}/delete/", {}))

        self.as_user(self.other)
        self.bad(self.get(f"templates/{template['id']}/"))


class ContractFlowTests(ApiTestBase):
    """合同全链路：起草 → 审批 → 签署 → 生效 → 履约 → 完成 → 归档。"""

    def test_lifecycle(self):
        created = self.create_contract()
        self.assertTrue(created["number"].startswith("HT"))
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["amount"], "200000.00")
        self.assertEqual(created["party_count"], 2)
        # 风险分在创建时就算了一次，金额 20 万至少落在第二档
        self.assertGreater(created["risk_score"], 0)

        submitted = self.ok(self.post(f"contracts/{created['id']}/submit/", {}))
        self.assertEqual(submitted["status"], "reviewing")
        self.assertEqual(len(submitted["nodes"]), 2)

        detail = self.ok(self.get(f"contracts/{created['id']}/"))
        self.assertEqual(detail["approval_summary"]["total"], 2)
        self.assertEqual(detail["approval_summary"]["pending"], 2)

        approved = self.approve_all(created["id"])
        self.assertEqual(approved["status"], "approved")

        signed = self.ok(self.post(f"contracts/{created['id']}/sign/",
                                   {"sign_now": False}))
        self.assertEqual(signed["status"], "signing")
        self.assertEqual(signed["pending"], 2)

        # 未完成签署不能生效
        self.bad(self.post(f"contracts/{created['id']}/activate/", {}))

        signatures = self.ok(self.get(f"contracts/{created['id']}/signatures/"))
        self.assertEqual(signatures["count"], 2)
        for row in signatures["items"]:
            result = self.ok(self.post(f"signatures/{row['id']}/status/",
                                       {"status": "signed"}))
            self.assertTrue(result["verified"])
            # 指纹是 64 位 sha256
            self.assertEqual(len(result["hash_fingerprint"]), 64)

        activated = self.ok(self.post(f"contracts/{created['id']}/activate/", {}))
        self.assertEqual(activated["status"], "active")

        obligation = self.ok(self.post(f"contracts/{created['id']}/obligations/create/",
                                       {"content": "提交季度服务报告",
                                        "due_date": (timezone.localdate()
                                                     + timedelta(days=10)).isoformat()}))
        # 有未完成义务时不允许标记完成
        self.bad(self.post(f"contracts/{created['id']}/complete/", {}))
        self.ok(self.post(f"obligations/{obligation['id']}/complete/",
                          {"note": "已交付"}))
        completed = self.ok(self.post(f"contracts/{created['id']}/complete/", {}))
        self.assertEqual(completed["status"], "completed")

        archived = self.ok(self.post(f"contracts/{created['id']}/archive/", {}))
        self.assertEqual(archived["status"], "archived")
        self.bad(self.post(f"contracts/{created['id']}/update/", {"name": "x"}))

        timeline = self.ok(self.get(f"contracts/{created['id']}/timeline/"))
        self.assertGreater(timeline["count"], 3)
        self.assertIn("audit", {row["type"] for row in timeline["items"]})

        clone = self.ok(self.post(f"contracts/{created['id']}/clone/", {}))
        self.assertEqual(clone["status"], "draft")
        self.assertNotEqual(clone["number"], created["number"])
        cloned = self.ok(self.get(f"contracts/{clone['id']}/"))
        self.assertEqual(cloned["party_count"], 2)

    def test_terminate_waives_obligations(self):
        created = self.create_contract()
        self.activate_contract(created["id"])
        obligation = self.ok(self.post(f"contracts/{created['id']}/obligations/create/",
                                       {"content": "现场巡检",
                                        "due_date": (timezone.localdate()
                                                     + timedelta(days=5)).isoformat()}))
        result = self.ok(self.post(f"contracts/{created['id']}/terminate/",
                                   {"reason": "对方违约"}))
        self.assertEqual(result["status"], "terminated")
        self.assertEqual(result["waived_obligations"], 1)
        row = self.ok(self.get(f"obligations/{obligation['id']}/events/"))
        self.assertEqual(row["items"][0]["action"], "waive")
        # 终止后不能再次终止
        self.bad(self.post(f"contracts/{created['id']}/terminate/", {"reason": "x"}))


class StateMachineTests(ApiTestBase):
    """状态机拦截：非法流转、驳回回退、金额路由。"""

    def test_illegal_transitions(self):
        created = self.create_contract()
        # 草稿不能直接审批通过 / 生效 / 完成
        self.bad(self.post(f"contracts/{created['id']}/approve/", {}))
        self.bad(self.post(f"contracts/{created['id']}/activate/", {}))
        self.bad(self.post(f"contracts/{created['id']}/complete/", {}))
        # 终止必须给原因
        self.bad(self.post(f"contracts/{created['id']}/terminate/", {}))
        # 归档草稿是允许的，归档后一切写动作都拒绝
        self.ok(self.post(f"contracts/{created['id']}/archive/", {}))
        self.bad(self.post(f"contracts/{created['id']}/submit/", {}))

    def test_zero_amount_and_reject_flow(self):
        self.bad(self.post("contracts/create/", {"name": "空金额", "amount": "0",
                                          "body": "第一条 空"}))
        created = self.create_contract(amount="6000000")
        submitted = self.ok(self.post(f"contracts/{created['id']}/submit/", {}))
        # 600 万触发四级审批
        self.assertEqual(len(submitted["nodes"]), 4)

        # 驳回必须给理由
        self.bad(self.post(f"contracts/{created['id']}/reject/", {}))
        rejected = self.ok(self.post(f"contracts/{created['id']}/reject/",
                                     {"reason": "条款风险过高"}))
        self.assertEqual(rejected["status"], "draft")
        # 驳回后可重新提交，节点重置为待审
        again = self.ok(self.post(f"contracts/{created['id']}/submit/", {}))
        self.assertEqual(again["status"], "reviewing")
        self.assertEqual(
            self.ok(self.get(f"contracts/{created['id']}/approvals/"))["summary"]["pending"],
            4)
        # 审批中的合同不能重复提交
        self.bad(self.post(f"contracts/{created['id']}/submit/", {}))

    def test_service_and_lease_route(self):
        # 租赁/劳务即使金额很小也要走法务
        created = self.create_contract(contract_type="lease", amount="50000")
        submitted = self.ok(self.post(f"contracts/{created['id']}/submit/", {}))
        self.assertEqual([name for name in submitted["nodes"]],
                         ["部门主管", "法务审核"])


class VersionTests(ApiTestBase):
    """版本快照、条款级对比与回滚。"""

    BODY_V1 = ("第一条 服务范围\n提供年度运维。\n"
               "第二条 付款方式\n按季度付款。\n"
               "第三条 违约责任\n违约方赔偿损失。")
    BODY_V2 = ("第一条 服务范围\n提供年度运维与巡检。\n"
               "第二条 付款方式\n按季度付款。\n"
               "第四条 保密\n双方互负保密义务。")

    def test_versions_diff_rollback(self):
        created = self.create_contract(body=self.BODY_V1)
        versions = self.ok(self.get(f"contracts/{created['id']}/versions/"))
        self.assertEqual(versions["count"], 1)
        self.assertTrue(versions["items"][0]["is_current"])

        second = self.ok(self.post(f"contracts/{created['id']}/versions/create/",
                                   {"body": self.BODY_V2,
                                    "change_summary": "调整服务范围"}))
        self.assertEqual(second["version_no"], 2)
        versions = self.ok(self.get(f"contracts/{created['id']}/versions/"))
        current = [row for row in versions["items"] if row["is_current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["version_no"], 2)

        first_id = [row for row in versions["items"]
                    if row["version_no"] == 1][0]["id"]
        compare = self.ok(self.get("versions/compare/",
                                   {"left_id": first_id, "right_id": second["id"]}))
        self.assertEqual(compare["summary"]["added"], 1)
        self.assertEqual(compare["summary"]["modified"], 1)
        self.assertFalse(compare["summary"]["identical"])

        rollback = self.ok(self.post(f"versions/{first_id}/rollback/", {}))
        self.assertEqual(rollback["restored_from"], 1)
        self.assertEqual(rollback["new_version"], 3)
        detail = self.ok(self.get(f"versions/{rollback['id']}/"))
        self.assertEqual(detail["body_snapshot"], self.BODY_V1)

        # 跨合同对比必须拒绝
        other = self.create_contract(name="另一个合同", body=self.BODY_V1)
        other_version = self.ok(self.get(f"contracts/{other['id']}/versions/"))
        self.bad(self.get("versions/compare/",
                          {"left_id": first_id,
                           "right_id": other_version["items"][0]["id"]}))

    def test_diff_service(self):
        diff = services.diff_versions(self.BODY_V1, self.BODY_V2)
        self.assertEqual(diff["summary"]["modified"], 1)
        self.assertEqual(diff["summary"]["added"], 1)
        self.assertEqual(diff["summary"]["removed"], 1)
        same = services.diff_versions(self.BODY_V1, self.BODY_V1)
        self.assertTrue(same["summary"]["identical"])


class ObligationTests(ApiTestBase):
    """履约义务：状态动作、事件留痕、逾期扫描与幂等排期。"""

    def test_obligation_actions(self):
        created = self.create_contract()
        today = timezone.localdate()
        row = self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "提交月度报告", "cycle": "monthly",
            "due_date": today.isoformat(), "priority": "high",
        }))
        self.assertEqual(row["cycle"], "monthly")
        self.assertTrue(row["series_uid"])

        # 新截止日必须晚于原截止日
        self.bad(self.post(f"obligations/{row['id']}/postpone/",
                           {"due_date": (today - timedelta(days=1)).isoformat()}))
        postponed = self.ok(self.post(f"obligations/{row['id']}/postpone/",
                                      {"due_date": (today + timedelta(days=3)).isoformat(),
                                       "note": "客户延期"}))
        self.assertEqual(postponed["due_date"], (today + timedelta(days=3)).isoformat())

        done = self.ok(self.post(f"obligations/{row['id']}/complete/",
                                 {"note": "已提交", "evidence": "邮件回执"}))
        self.assertEqual(done["status"], "done")
        self.bad(self.post(f"obligations/{row['id']}/delete/", {}))
        self.bad(self.post(f"obligations/{row['id']}/postpone/",
                           {"due_date": (today + timedelta(days=5)).isoformat()}))

        events = self.ok(self.get(f"obligations/{row['id']}/events/"))
        self.assertEqual(events["count"], 2)
        self.assertEqual(events["items"][0]["action"], "complete")

        waived_row = self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "旧系统迁移", "due_date": today.isoformat()}))
        self.bad(self.post(f"obligations/{waived_row['id']}/waive/", {}))
        waived = self.ok(self.post(f"obligations/{waived_row['id']}/waive/",
                                   {"reason": "范围取消"}))
        self.assertEqual(waived["status"], "waived")

    def test_schedule_idempotent_and_overdue(self):
        created = self.create_contract()
        self.activate_contract(created["id"])
        today = timezone.localdate()
        row = self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "按期付款", "cycle": "monthly", "due_date": today.isoformat()}))
        first = self.ok(self.post(f"obligations/{row['id']}/schedule/",
                                  {"periods": 3}))
        self.assertEqual(first["created"], 3)
        second = self.ok(self.post(f"obligations/{row['id']}/schedule/",
                                   {"periods": 3}))
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 3)

        list_data = self.ok(self.get(f"contracts/{created['id']}/obligations/"))
        self.assertEqual(list_data["count"], 4)
        self.assertEqual(list_data["summary"]["total"], 4)

        # 一条过去的义务 → 逾期扫描把它置为 overdue
        overdue_row = self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "过期的验收", "due_date": (today - timedelta(days=5)).isoformat()}))
        overdue = self.ok(self.get("obligations/overdue/"))
        self.assertGreaterEqual(overdue["count"], 1)
        ids = {item["id"] for item in overdue["items"]}
        self.assertIn(overdue_row["id"], ids)
        self.assertEqual(overdue["items"][0]["overdue_days"], 5)

    def test_obligations_all_filters(self):
        created = self.create_contract()
        today = timezone.localdate()
        self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "培训交付", "due_date": (today + timedelta(days=20)).isoformat()}))
        self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "材料归档", "due_date": (today + timedelta(days=40)).isoformat()}))
        all_rows = self.ok(self.get("obligations/", {"page_size": 50}))
        self.assertEqual(all_rows["count"], 2)
        self.assertEqual(all_rows["items"][0]["contract_number"], created["number"])
        filtered = self.ok(self.get("obligations/", {"q": "培训"}))
        self.assertEqual(filtered["count"], 1)
        ranged = self.ok(self.get("obligations/", {
            "due_before": (today + timedelta(days=30)).isoformat()}))
        self.assertEqual(ranged["count"], 1)


class MilestoneAmendmentTests(ApiTestBase):
    """里程碑与变更单：达成率、延期标记、变更审批与生效。"""

    def test_milestone(self):
        today = timezone.localdate()
        created = self.create_contract(
            effective_date=(today - timedelta(days=10)).isoformat(),
            expire_date=(today + timedelta(days=80)).isoformat())
        row = self.ok(self.post(f"contracts/{created['id']}/milestones/create/", {
            "name": "一期验收", "plan_date": (today - timedelta(days=3)).isoformat(),
            "amount": "50000"}))
        done = self.ok(self.post(f"milestones/{row['id']}/complete/",
                                 {"actual_date": today.isoformat()}))
        self.assertTrue(done["is_late"])
        self.assertEqual(done["delay_days"], 3)
        self.assertFalse(done["on_time"])
        self.bad(self.post(f"milestones/{row['id']}/update/",
                           {"plan_date": (today + timedelta(days=1)).isoformat()}))
        listed = self.ok(self.get(f"contracts/{created['id']}/milestones/"))
        self.assertEqual(listed["achieved"], 1)
        self.assertEqual(listed["achievement_rate"], 100.0)

    def test_amendment_amount_and_date(self):
        created = self.create_contract()
        amendment = self.ok(self.post(f"contracts/{created['id']}/amendments/create/", {
            "change_type": "amount", "after_text": "250000.00",
            "reason": "增加服务范围"}))
        self.assertEqual(amendment["approval_status"], "draft")
        # 草稿不能直接审批
        self.bad(self.post(f"amendments/{amendment['id']}/approve/", {}))
        self.ok(self.post(f"amendments/{amendment['id']}/submit/", {}))
        approved = self.ok(self.post(f"amendments/{amendment['id']}/approve/",
                                     {"action": "approve"}))
        self.assertEqual(approved["approval_status"], "effective")
        self.assertTrue(approved["applied"])
        detail = self.ok(self.get(f"contracts/{created['id']}/"))
        self.assertEqual(detail["amount"], "250000.00")
        versions = self.ok(self.get(f"contracts/{created['id']}/versions/"))
        self.assertEqual(versions["count"], 2)

        date_amendment = self.ok(self.post(f"contracts/{created['id']}/amendments/create/", {
            "change_type": "date", "reason": "延长服务期"}))
        self.ok(self.post(f"amendments/{date_amendment['id']}/submit/", {}))
        new_expire = (timezone.localdate() + timedelta(days=400)).isoformat()
        applied = self.ok(self.post(f"amendments/{date_amendment['id']}/approve/",
                                    {"action": "approve",
                                     "new_expire_date": new_expire}))
        self.assertTrue(applied["applied"])
        detail = self.ok(self.get(f"contracts/{created['id']}/"))
        self.assertEqual(detail["expire_date"], new_expire)

    def test_amendment_reject(self):
        created = self.create_contract()
        amendment = self.ok(self.post(f"contracts/{created['id']}/amendments/create/", {
            "change_type": "clause", "after_text": "第一条 变更后\n新条款。"}))
        self.ok(self.post(f"amendments/{amendment['id']}/submit/", {}))
        rejected = self.ok(self.post(f"amendments/{amendment['id']}/approve/",
                                     {"action": "reject", "reason": "无需变更"}))
        self.assertEqual(rejected["approval_status"], "rejected")
        # 驳回后可以改稿回到草稿
        updated = self.ok(self.post(f"amendments/{amendment['id']}/update/",
                                    {"reason": "修改后重提"}))
        self.assertEqual(updated["approval_status"], "draft")


class FinanceTests(ApiTestBase):
    """付款计划、逾期、续约与财务汇总。"""

    def test_payment_flow(self):
        created = self.create_contract(amount="100000")
        today = timezone.localdate()
        first = self.ok(self.post(f"contracts/{created['id']}/payments/create/", {
            "plan_amount": "60000", "plan_date": (today + timedelta(days=10)).isoformat()}))
        second = self.ok(self.post(f"contracts/{created['id']}/payments/create/", {
            "plan_amount": "40000", "plan_date": (today + timedelta(days=40)).isoformat()}))
        self.assertEqual([first["period_no"], second["period_no"]], [1, 2])

        partial = self.ok(self.post(f"payments/{first['id']}/pay/",
                                    {"amount": "20000"}))
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["remaining"], "40000.00")
        # 超付必须拒绝
        self.bad(self.post(f"payments/{first['id']}/pay/", {"amount": "99999"}))
        paid = self.ok(self.post(f"payments/{first['id']}/pay/",
                                 {"amount": "40000"}))
        self.assertEqual(paid["status"], "paid")
        self.bad(self.post(f"payments/{first['id']}/update/",
                           {"plan_amount": "1"}))
        self.bad(self.post(f"payments/{first['id']}/cancel/", {}))

        payout = self.ok(self.get(f"contracts/{created['id']}/payments/"))
        self.assertEqual(payout["planned_total"], "100000.00")
        self.assertEqual(payout["paid_total"], "60000.00")
        self.assertEqual(payout["unpaid_total"], "40000.00")

        summary = self.ok(self.get("finance/summary/",
                                   {"contract_id": created["id"]}))
        self.assertEqual(summary["overall"]["paid_amount"], "60000.00")
        self.assertEqual(summary["overall"]["unpaid_amount"], "40000.00")
        self.assertEqual(summary["by_currency"][0]["currency"], "CNY")
        self.assertEqual(summary["by_currency"][0]["collection_rate"], 60.0)

    def test_payment_overdue(self):
        created = self.create_contract(amount="50000")
        today = timezone.localdate()
        self.ok(self.post(f"contracts/{created['id']}/payments/create/", {
            "plan_amount": "50000",
            "plan_date": (today - timedelta(days=7)).isoformat()}))
        stats = self.ok(self.get("payments/overdue/"))
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["max_overdue_days"], 7)
        self.assertEqual(stats["overdue_total"], "50000.00")
        self.assertEqual(stats["items"][0]["contract_number"], created["number"])

    def test_cancel_payment(self):
        created = self.create_contract(amount="80000")
        row = self.ok(self.post(f"contracts/{created['id']}/payments/create/", {
            "plan_amount": "80000",
            "plan_date": (timezone.localdate() + timedelta(days=5)).isoformat()}))
        cancelled = self.ok(self.post(f"payments/{row['id']}/cancel/", {}))
        self.assertEqual(cancelled["status"], "cancelled")
        self.bad(self.post(f"payments/{row['id']}/pay/", {"amount": "1"}))

    def test_renewals(self):
        created = self.create_contract(
            expire_date=(timezone.localdate() + timedelta(days=10)).isoformat())
        # 新到期日必须晚于当前到期日
        self.bad(self.post(f"contracts/{created['id']}/renewals/create/", {
            "renewal_type": "manual",
            "new_expire_date": (timezone.localdate() + timedelta(days=1)).isoformat()}))
        renewal = self.ok(self.post(f"contracts/{created['id']}/renewals/create/", {
            "renewal_type": "manual", "remind_days": 30,
            "new_expire_date": (timezone.localdate() + timedelta(days=400)).isoformat()}))
        upcoming = self.ok(self.get("renewals/upcoming/"))
        self.assertEqual(upcoming["count"], 1)
        self.assertEqual(upcoming["items"][0]["days_to_expiry"], 10)

        confirmed = self.ok(self.post(f"renewals/{renewal['id']}/confirm/",
                                      {"action": "confirm"}))
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["expire_date"],
                         (timezone.localdate() + timedelta(days=400)).isoformat())
        self.bad(self.post(f"renewals/{renewal['id']}/confirm/", {}))


class RiskReminderTests(ApiTestBase):
    """风险评分明细、关键词扫描与到期提醒幂等。"""

    def test_risk_score(self):
        created = self.create_contract(amount="30000",
                                       contract_type="purchase",
                                       body="第一条 责任\n乙方承担无限责任。")
        score = self.ok(self.post(f"contracts/{created['id']}/risk/score/", {}))
        self.assertIn("breakdown", score)
        self.assertEqual(set(score["breakdown"]),
                         {"amount", "type", "clause", "performance", "counterparty"})
        self.assertGreaterEqual(score["total"], 1)
        self.assertTrue(any(hit["keyword"] == "无限责任"
                            for hit in score["breakdown"]["clause"]["keyword_hits"]))

        risk = self.ok(self.post(f"contracts/{created['id']}/risks/create/", {
            "title": "付款周期过长", "level": "high",
            "description": "账期 120 天", "mitigation": "要求预付款"}))
        self.assertGreaterEqual(risk["contract_risk_score"], score["total"])
        closed = self.ok(self.post(f"risks/{risk['id']}/update/",
                                   {"status": "closed"}))
        self.assertEqual(closed["status"], "closed")
        listed = self.ok(self.get(f"contracts/{created['id']}/risks/"))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["open_count"], 0)

    def test_reminder_scan_idempotent(self):
        soon = self.create_contract(
            name="即将到期合同",
            expire_date=(timezone.localdate() + timedelta(days=3)).isoformat())
        self.activate_contract(soon["id"])
        result = self.ok(self.post("reminders/scan/", {"days": 90}))
        self.assertEqual(result["marked_expiring"], 1)
        self.assertGreaterEqual(result["reminders_created"], 1)
        second = self.ok(self.post("reminders/scan/", {"days": 90}))
        self.assertEqual(second["reminders_created"], 0)
        detail = self.ok(self.get(f"contracts/{soon['id']}/"))
        self.assertEqual(detail["status"], "expiring")
        self.assertEqual(detail["days_to_expiry"], 3)

        expired = self.create_contract(
            name="已过期合同",
            effective_date=(timezone.localdate() - timedelta(days=60)).isoformat(),
            expire_date=(timezone.localdate() - timedelta(days=2)).isoformat())
        self.activate_contract(expired["id"])
        third = self.ok(self.post("reminders/scan/", {"days": 90}))
        self.assertEqual(third["marked_expired"], 1)
        detail = self.ok(self.get(f"contracts/{expired['id']}/"))
        self.assertEqual(detail["status"], "expired")

        listed = self.ok(self.get("reminders/", {"kind": "expiry"}))
        self.assertGreaterEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["kind"], "expiry")

        # dry_run 只预演，不写库
        fresh = self.create_contract(
            name="预演合同",
            expire_date=(timezone.localdate() + timedelta(days=20)).isoformat())
        preview = self.ok(self.post("reminders/scan/", {"dry_run": True}))
        self.assertTrue(preview["dry_run"])
        detail = self.ok(self.get(f"contracts/{fresh['id']}/"))
        self.assertEqual(detail["status"], "draft")

    def test_reminder_channel_validation(self):
        self.bad(self.post("reminders/scan/", {"channel": "carrier-pigeon"}))


class StatsTests(ApiTestBase):
    """组合统计与履约健康度。"""

    def test_stats_endpoints(self):
        created = self.create_contract(amount="120000")
        self.activate_contract(created["id"])
        today = timezone.localdate()
        obligation = self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "按期交付", "due_date": (today + timedelta(days=5)).isoformat()}))
        self.ok(self.post(f"obligations/{obligation['id']}/complete/", {}))
        payment = self.ok(self.post(f"contracts/{created['id']}/payments/create/", {
            "plan_amount": "120000", "plan_date": today.isoformat()}))
        self.ok(self.post(f"payments/{payment['id']}/pay/",
                          {"amount": "120000", "paid_date": today.isoformat()}))

        overview = self.ok(self.get("stats/overview/"))
        self.assertEqual(overview["total"], 1)
        self.assertEqual(overview["by_status"]["active"], 1)
        self.assertIn("obligations", overview)

        expiry = self.ok(self.get("stats/expiry/"))
        self.assertEqual(expiry["total"], 1)
        self.assertEqual(sum(expiry["buckets"].values()), 1)

        amount = self.ok(self.get("stats/amount/"))
        self.assertEqual(amount["overall"]["paid_amount"], "120000.00")
        self.assertEqual(amount["by_currency"][0]["currency"], "CNY")
        self.assertEqual(amount["top_contracts"][0]["id"], created["id"])

        risk = self.ok(self.get("stats/risk/"))
        self.assertEqual(risk["total"], 1)
        self.assertIn("bands", risk)

        health = self.ok(self.get("stats/health/"))
        self.assertEqual(health["scored"], 1)
        self.assertGreaterEqual(health["average_score"], 90.0)

        load = self.ok(self.get("stats/owner-load/"))
        self.assertEqual(load["count"], 1)
        self.assertEqual(load["items"][0]["contracts"], 1)

    def test_expiring_list(self):
        created = self.create_contract(
            name="30 天内到期",
            expire_date=(timezone.localdate() + timedelta(days=12)).isoformat())
        self.activate_contract(created["id"])
        listed = self.ok(self.get("contracts/expiring/", {"days": 30}))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["days_to_expiry"], 12)
        self.assertEqual(listed["items"][0]["stage"], 15)


class PermissionAndValidationTests(ApiTestBase):
    """行级权限、分页上限与入参校验。"""

    def test_row_level_isolation(self):
        created = self.create_contract()
        self.as_user(self.other)
        self.assertEqual(self.ok(self.get("contracts/"))["count"], 0)
        self.bad(self.get(f"contracts/{created['id']}/"))
        self.bad(self.post(f"contracts/{created['id']}/update/", {"name": "x"}))
        self.bad(self.post(f"contracts/{created['id']}/obligations/create/",
                           {"content": "x"}))
        # 其他用户不能登记到自己名下
        mine = self.create_contract(name="鲍勃的合同")
        self.assertEqual(self.ok(self.get("contracts/"))["count"], 1)
        self.as_user(self.user)
        self.assertEqual(self.ok(self.get("contracts/"))["count"], 1)
        self.bad(self.get(f"contracts/{mine['id']}/"))

    def test_pagination_and_validation(self):
        for index in range(5):
            self.create_contract(name=f"批量合同 {index}",
                                 number=f"HT-BULK-{index}")
        page = self.ok(self.get("contracts/", {"page_size": 2, "page": 2}))
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["page_size"], 2)
        self.assertEqual(len(page["items"]), 2)
        self.assertEqual(page["count"], 5)
        self.bad(self.get("contracts/", {"page_size": 500}))
        self.bad(self.get("contracts/", {"page": 0}))
        self.bad(self.get("contracts/", {"page": "abc"}))
        self.bad(self.post("contracts/create/", {"name": "金额非法", "amount": "abc"}))
        self.bad(self.post("contracts/create/", {"name": "类型非法",
                                          "contract_type": "unknown"}))
        self.bad(self.post("contracts/create/", {"name": "币种非法",
                                          "currency": "XYZ"}))
        # 编号重复（同一用户）必须报错
        self.bad(self.post("contracts/create/", {"name": "重复编号",
                                          "number": "HT-BULK-0"}))
        # 日期区间必须自洽
        self.bad(self.post("contracts/create/", {
            "name": "日期倒挂",
            "effective_date": (timezone.localdate() + timedelta(days=30)).isoformat(),
            "expire_date": timezone.localdate().isoformat()}))

    def test_tags(self):
        created = self.create_contract()
        tag = self.ok(self.post("tags/create/", {"name": "重点", "color": "#F56C6C"}))
        again = self.ok(self.post("tags/create/", {"name": "重点"}))
        self.assertFalse(again["created"])
        result = self.ok(self.post(f"contracts/{created['id']}/tags/",
                                   {"tag_ids": [tag["id"]]}))
        self.assertEqual(len(result["tags"]), 1)
        listed = self.ok(self.get("contracts/", {"tag_id": tag["id"]}))
        self.assertEqual(listed["count"], 1)
        self.as_user(self.other)
        self.bad(self.post(f"contracts/{created['id']}/tags/",
                           {"tag_ids": [tag["id"]]}))
        self.as_user(self.user)
        self.ok(self.post(f"tags/{tag['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get("tags/"))["count"], 0)


class ServiceUnitTests(ApiTestBase):
    """服务层纯函数：渲染白名单、金额分档、审批路由、指纹、健康度与组合统计。"""

    def test_render_and_fingerprint(self):
        template = ContractTemplate.objects.create(
            owner=self.user, code="UNIT-1", name="单测模板",
            body="甲方：{{party_a}}；金额：{{amount|0}}",
            variables=[{"name": "party_a", "required": True},
                       {"name": "amount", "required": False, "default": "0"}],
            status="published")
        result = services.render_template(template, {"party_a": "甲公司"})
        self.assertEqual(result["body"], "甲方：甲公司；金额：0")
        with self.assertRaises(ValueError):
            services.render_template(template, {})
        with self.assertRaises(ValueError):
            services.render_body("{{unknown}}", [], {}, strict=True)

        contract = Contract.objects.create(
            owner=self.user, number="HT-UNIT-1", name="指纹合同",
            contract_type="service", amount=Decimal("1000.00"))
        services.create_version(contract, self.user, "第一条 正文")
        contract.refresh_from_db()
        stamp = timezone.now()
        digest = services.sign_fingerprint(contract, "张三", stamp)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, services.sign_fingerprint(contract, "张三", stamp))
        self.assertNotEqual(digest, services.sign_fingerprint(contract, "李四", stamp))

    def test_amount_bands_and_route(self):
        levels = [services.amount_band_label(Decimal(value))[0]
                  for value in ("1000", "500000", "2000000", "9000000")]
        self.assertEqual(levels, [1, 2, 3, 4])
        route = services.build_approval_route(Decimal("2000000"), "service")
        self.assertEqual([node["name"] for node in route["nodes"]],
                         ["部门主管", "法务审核", "财务总监"])
        lease = services.build_approval_route(Decimal("1000"), "lease")
        self.assertEqual([node["name"] for node in lease["nodes"]],
                         ["部门主管", "法务审核"])

    def test_clause_diff_and_health(self):
        old = "第一条 范围\nA\n第二条 付款\nB"
        new = "第一条 范围\nA+\n第二条 付款\nB\n第三条 保密\nC"
        diff = services.diff_versions(old, new)
        self.assertEqual(diff["summary"]["modified"], 1)
        self.assertEqual(diff["summary"]["added"], 1)
        self.assertEqual(diff["summary"]["unchanged"], 1)

        contract = Contract.objects.create(
            owner=self.user, number="HT-UNIT-2", name="健康度合同",
            contract_type="service", amount=Decimal("1000.00"),
            status="active")
        health = services.health_score(contract)
        self.assertEqual(health["score"], 100.0)
        self.assertEqual(health["level"], "excellent")

    def test_month_add_and_expiry_stage(self):
        self.assertEqual(services.month_add(timezone.localdate().replace(
            day=31, month=1), 1).day, 28)
        self.assertEqual(services.expiry_stage_for(3), 7)
        self.assertEqual(services.expiry_stage_for(1), 1)
        self.assertEqual(services.expiry_stage_for(0), 1)
        self.assertEqual(services.expiry_stage_for(12), 15)
        self.assertEqual(services.expiry_stage_for(25), 30)
        self.assertIsNone(services.expiry_stage_for(60))
        self.assertIsNone(services.expiry_stage_for(-3))

    def test_state_machine_helpers(self):
        contract = Contract.objects.create(
            owner=self.user, number="HT-UNIT-3", name="状态合同",
            contract_type="service", amount=Decimal("1000.00"))
        self.assertEqual(state.assert_action_allowed(contract, "submit"), "reviewing")
        with self.assertRaises(ValueError):
            state.assert_action_allowed(contract, "activate")
        state.transition(contract, "submit", self.user, "提交")
        self.assertEqual(contract.status, "reviewing")
        self.assertEqual(ContractAudit.objects.filter(contract=contract).count(), 1)


class AnalyticsExtrasTests(ApiTestBase):
    """审计 / 归档导出 / 付款计划 / 条款推荐 / 续约窗口 / 履约日历 / 提醒确认。"""

    def test_audit_and_export(self):
        created = self.create_contract()
        audit = self.ok(self.get(f"contracts/{created['id']}/audit/",
                                 {"page_size": 20}))
        self.assertGreaterEqual(audit["count"], 1)
        self.assertEqual(audit["items"][0]["action"], "create")

        exported = self.ok(self.get(f"contracts/{created['id']}/export/"))
        self.assertEqual(exported["contract"]["id"], created["id"])
        self.assertEqual(len(exported["parties"]), 2)
        self.assertEqual(exported["versions"][0]["version_no"], 1)
        self.assertIn("obligations", exported)
        self.assertIn("exported_at", exported)

        tags = self.ok(self.get(f"contracts/{created['id']}/tags/detail/"))
        self.assertEqual(tags["count"], 0)

    def test_payment_plan_idempotent(self):
        created = self.create_contract(amount="100000")
        today = timezone.localdate()
        plan = self.ok(self.post(f"contracts/{created['id']}/payments/plan/", {
            "periods": 3, "ratios": ["50", "30", "20"],
            "first_date": today.isoformat(), "interval_days": 30}))
        self.assertEqual(plan["created"], 3)
        self.assertEqual(plan["amount"], "100000.00")
        amounts = [Decimal(item["plan_amount"]) for item in plan["items"]]
        self.assertEqual(sum(amounts), Decimal("100000.00"))
        self.assertEqual(plan["items"][0]["plan_amount"], "50000.00")

        again = self.ok(self.post(f"contracts/{created['id']}/payments/plan/", {
            "periods": 3, "ratios": ["50", "30", "20"],
            "first_date": today.isoformat()}))
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["skipped"], 3)

        listed = self.ok(self.get(f"contracts/{created['id']}/payments/"))
        self.assertEqual(listed["count"], 3)

        self.bad(self.post(f"contracts/{created['id']}/payments/plan/", {
            "periods": 3, "ratios": ["50", "30"]}))
        self.bad(self.post(f"contracts/{created['id']}/payments/plan/", {
            "periods": 0}))

    def test_library_suggest_and_renewal_window(self):
        self.ok(self.post("clauses/library/create/", {
            "title": "保密义务", "category": "通用", "risk_level": "high",
            "body": "双方对合作中知悉的商业秘密承担保密义务。",
            "tags": ["保密", "通用"]}))
        suggested = self.ok(self.get("clauses/library/suggest/",
                                     {"q": "保密", "risk_level": "high"}))
        self.assertEqual(suggested["count"], 1)
        self.assertGreaterEqual(suggested["items"][0]["score"], 7)
        self.assertIn("标题命中", suggested["items"][0]["reason"])
        self.bad(self.get("clauses/library/suggest/", {"risk_level": "unknown"}))

        today = timezone.localdate()
        created = self.create_contract(
            contract_type="lease", renewal_mode="auto",
            expire_date=(today + timedelta(days=20)).isoformat())
        self.activate_contract(created["id"])
        window = self.ok(self.get("stats/renewal-window/", {"days": 90}))
        self.assertEqual(window["buckets"]["d30"], 1)
        self.assertEqual(window["auto_renew"], 1)
        self.assertEqual(window["items"][0]["contract_id"], created["id"])
        self.assertEqual(window["items"][0]["action"], "确认续约")

    def test_obligation_calendar_and_reminder_ack(self):
        created = self.create_contract()
        today = timezone.localdate()
        self.ok(self.post(f"contracts/{created['id']}/obligations/create/", {
            "content": "本月验收", "due_date": today.isoformat()}))
        calendar = self.ok(self.get("obligations/calendar/", {"months": 3}))
        self.assertGreaterEqual(calendar["total"], 1)
        self.assertEqual(calendar["months"][0]["month"], today.strftime("%Y-%m"))
        self.assertIn("due_date", calendar["months"][0]["items"][0])

        expiring = self.create_contract(
            name="临期提醒合同",
            expire_date=(today + timedelta(days=10)).isoformat())
        self.activate_contract(expiring["id"])
        self.ok(self.post("reminders/scan/", {"days": 30}))
        reminders = self.ok(self.get("reminders/", {"kind": "expiry"}))
        self.assertGreaterEqual(reminders["count"], 1)
        reminder_id = reminders["items"][0]["id"]
        acked = self.ok(self.post(f"reminders/{reminder_id}/ack/", {}))
        self.assertTrue(acked["changed"])
        self.assertEqual(acked["status"], "read")
        again = self.ok(self.post(f"reminders/{reminder_id}/ack/", {}))
        self.assertFalse(again["changed"])
