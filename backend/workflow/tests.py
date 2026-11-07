# -*- coding: utf-8 -*-
"""流程引擎回归测试。

覆盖四层：
1. 纯算法层：表达式解释执行、图算法、结构校验（不碰数据库）；
2. 接口层：定义/版本/设计器/运行态/任务/监控/协作全部走 APIClient；
3. 引擎层：串行审批、拒绝、退回、加签、转办、委派、并行分支/汇聚、
   条件分支、批量办理、取消/终止、变量/评论/附件/快照/回放；
4. 一致性与权限：重复办理 400、非办理人 400、SLA 扫描幂等、分页上限、
   数据范围隔离。

测试库由 Django 测试运行器按模型结构自动创建（workflow/migrations 为空），
因此不会触碰本地 SQLite 数据文件。
"""
from datetime import timedelta
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department, Role, User
from workflow import services
from workflow.models import (
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNode,
    WorkflowNotification,
    WorkflowSlaPolicy,
    WorkflowTask,
    WorkflowTransition,
    WorkflowWebhook,
)

BASE = "/api/workflow"


def iso_after(minutes=0, days=0):
    """构造未来的 ISO 时间串（委托窗口用）。"""
    return (timezone.now() + timedelta(minutes=minutes, days=days)).isoformat()


class WorkflowBase(TestCase):
    """公共夹具：四个用户 + 部门 + 角色 + 统一的请求/建图助手。"""

    def setUp(self):
        self.dept = Department.objects.create(name="研发部")
        self.sub_dept = Department.objects.create(name="平台组", parent=self.dept)
        self.role = Role.objects.create(name="审批人", code="approver", data_scope="self")
        self.alice = User.objects.create_user(
            username="alice", password="pw-alice", nickname="爱丽丝", department=self.dept
        )
        self.bob = User.objects.create_user(
            username="bob", password="pw-bob", nickname="鲍勃", department=self.sub_dept
        )
        self.carol = User.objects.create_user(
            username="carol", password="pw-carol", nickname="卡罗尔", department=self.dept
        )
        self.dave = User.objects.create_user(
            username="dave", password="pw-dave", nickname="戴夫", department=self.dept
        )
        self.admin = User.objects.create_user(
            username="admin", password="pw-admin", nickname="管理员",
            is_staff=True, is_superuser=True,
        )
        self.dept.leader = self.carol
        self.dept.save(update_fields=["leader"])
        self.client = APIClient()

    # ---- 请求助手 ---------------------------------------------------------

    def auth(self, user):
        """切换当前登录用户（force_authenticate 直接注入，不走 JWT）。"""
        self.client.force_authenticate(user=user)
        return self

    def request(self, method, path, data=None, user=None):
        """发请求：path 只写业务路径，自动补 /api/workflow 前缀。"""
        if user is not None:
            self.auth(user)
        url = f"{BASE}{path}"
        if method == "get":
            return self.client.get(url, data or {})
        return self.client.post(url, data or {}, format="json")

    def get(self, path, data=None, user=None):
        return self.request("get", path, data, user)

    def post(self, path, data=None, user=None):
        return self.request("post", path, data, user)

    def assert_ok(self, response):
        """断言统一成功响应并返回 data。"""
        self.assertEqual(response.status_code, 200, response.content.decode("utf-8", "ignore"))
        body = response.json()
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def assert_fail(self, response, contains=None):
        """断言 400 且错误信息包含指定片段（ValueError → 400）。"""
        self.assertEqual(response.status_code, 400, response.content.decode("utf-8", "ignore"))
        body = response.json()
        self.assertFalse(body.get("ok"), body)
        if contains:
            self.assertIn(contains, body.get("error", ""))
        return body.get("error", "")

    # ---- 建图助手 ---------------------------------------------------------

    def simple_nodes(self, approver=None, sla_minutes=60):
        """开始 → 单人审批 → 结束。"""
        approver = approver or self.bob
        return [
            {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
            {"key": "approve", "name": "审批", "assignee_type": "user",
             "assignee_rule": {"user_ids": [approver.id]}, "sla_minutes": sla_minutes},
            {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
        ]

    def simple_edges(self):
        """开始 → 审批 → 结束的连线。"""
        return [{"from": "start", "to": "approve"}, {"from": "approve", "to": "end"}]

    def make_definition(self, owner=None, code=None, nodes=None, edges=None, publish=False):
        """直接用 ORM 建流程定义与图结构（可指定是否发布）。"""
        owner = owner or self.alice
        code = code or f"flow_{uuid4().hex[:8]}"
        definition = WorkflowDefinition.objects.create(
            owner=owner, code=code, name="测试流程", category="通用",
            status="draft", version_no=1, start_permission={"allow_all": True},
        )
        nodes = nodes if nodes is not None else self.simple_nodes()
        edges = edges if edges is not None else self.simple_edges()
        created = {}
        for index, spec in enumerate(nodes):
            node = WorkflowNode.objects.create(
                definition=definition, owner=owner, key=spec["key"],
                name=spec.get("name") or spec["key"],
                node_type=spec.get("node_type", "task"),
                assignee_type=spec.get("assignee_type", "user"),
                assignee_rule=spec.get("assignee_rule") or {},
                sla_minutes=int(spec.get("sla_minutes") or 0),
                form_fields=spec.get("form_fields") or [],
                config=spec.get("config") or {},
                order=index,
                allow_reject=spec.get("allow_reject", True),
                allow_return=spec.get("allow_return", True),
                allow_add_sign=spec.get("allow_add_sign", True),
                allow_transfer=spec.get("allow_transfer", True),
                require_comment=spec.get("require_comment", False),
            )
            created[node.key] = node
        for spec in edges:
            WorkflowTransition.objects.create(
                definition=definition, owner=owner,
                from_node=created[spec["from"]], to_node=created[spec["to"]],
                condition=spec.get("condition", ""),
                priority=spec.get("priority", 100),
                is_default=spec.get("is_default", False),
                label=spec.get("label", ""),
            )
        if publish:
            services.publish_definition(definition, owner, note="测试初始化")
        return definition

    def start_instance(self, definition, user=None, context=None, **extra):
        """通过 API 发起流程，返回数据库实例。"""
        payload = {"definition_id": definition.id, "context": context or {}}
        payload.update(extra)
        data = self.assert_ok(self.post("/instances/start/", payload, user=user or self.alice))
        return WorkflowInstance.objects.get(pk=data["id"])

    def open_task(self, instance, node_key="approve"):
        """取实例在指定节点上的未结任务。"""
        return WorkflowTask.objects.filter(
            instance=instance, node__key=node_key,
            status__in=("pending", "claimed"),
        ).order_by("id").first()

    def complete(self, task, user, action="approve", **extra):
        """通过 API 办理任务并返回响应。"""
        payload = {"action": action, "comment": extra.pop("comment", "同意")}
        payload.update(extra)
        return self.post(f"/tasks/{task.id}/complete/", payload, user=user)


class ExpressionEngineTests(WorkflowBase):
    """表达式引擎：语法、类型转换、安全边界。"""

    def test_boolean_and_arithmetic(self):
        ctx = {"amount": 8000, "category": "采购", "priority": "high", "days": 3}
        self.assertTrue(services.evaluate_condition(
            'amount >= 5000 and category == "采购"', ctx))
        self.assertFalse(services.evaluate_condition(
            'amount < 5000 or priority == "low"', ctx))
        self.assertTrue(services.evaluate_condition("amount / 2 == 4000", ctx))
        self.assertTrue(services.evaluate_condition("amount % 2 == 0", ctx))
        self.assertTrue(services.evaluate_condition('priority in ["high", "urgent"]', ctx))
        self.assertTrue(services.evaluate_condition('category not in ["人事", "财务"]', ctx))

    def test_nested_paths_and_lists(self):
        ctx = {"form": {"days": "5"}, "items": [{"qty": 2}, {"qty": 9}], "ok": None}
        self.assertTrue(services.evaluate_condition("form.days > 3", ctx))
        self.assertTrue(services.evaluate_condition("items[0].qty + items[1].qty == 11", ctx))
        self.assertTrue(services.evaluate_condition("ok == null", ctx))
        self.assertTrue(services.evaluate_condition("not false", ctx))

    def test_raw_expression_result(self):
        value = services.evaluate_expression(
            'category == "采购" and amount > 100', {"category": "采购", "amount": 200})
        self.assertTrue(value)
        self.assertEqual(services.evaluate_expression("1 + 2 * 3", {}), 7)
        self.assertIsNone(services.evaluate_expression("", {}))

    def test_invalid_expression_rejected(self):
        for expression in ("amount >", "amount + ", "(a or b", '"unterminated'):
            with self.assertRaises(ValueError):
                services.compile_condition(expression)

    def test_no_exec_or_attribute_escape(self):
        # 不允许调用函数、访问属性或下标注入；这些都会被词法器拒绝
        for expression in ('__import__("os")', "user.__class__()", "a.b.c()",
                           "open('x')", "[1,2][9]"):
            with self.assertRaises(ValueError):
                services.compile_condition(expression)

    def test_expression_length_limit(self):
        too_long = "a" + " + a" * 1500
        with self.assertRaises(ValueError):
            services.compile_condition(too_long)

    def test_api_expression_eval(self):
        data = self.assert_ok(self.post("/expressions/eval/", {
            "expression": 'amount >= 100 and level in ["vip", "svip"]',
            "context": {"amount": 300, "level": "vip"},
        }, user=self.alice))
        self.assertTrue(data["valid"])
        self.assertTrue(data["result"])
        bad = self.assert_ok(self.post("/expressions/eval/", {
            "expression": "amount >", "context": {},
        }, user=self.alice))
        self.assertFalse(bad["valid"])
        self.assertTrue(bad["error"])


class GraphAlgorithmTests(WorkflowBase):
    """图算法：环检测、拓扑排序、可达性、最长 SLA 路径。"""

    def _adjacency(self):
        nodes = [{"key": k} for k in ("s", "a", "b", "c", "e")]
        edges = [
            {"from": "s", "to": "a", "priority": 10},
            {"from": "s", "to": "b", "priority": 20},
            {"from": "a", "to": "c", "priority": 10},
            {"from": "b", "to": "c", "priority": 10},
            {"from": "c", "to": "e", "priority": 10},
        ]
        return services.build_adjacency(nodes, edges)

    def test_reachability_and_topology(self):
        adjacency = self._adjacency()
        self.assertEqual(services.reachable_from(adjacency, "s"), {"s", "a", "b", "c", "e"})
        self.assertEqual(services.reachable_ends(adjacency, "s", ["e"]), {"e"})
        order, has_cycle = services.topological_order(adjacency)
        self.assertFalse(has_cycle)
        self.assertLess(order.index("s"), order.index("a"))
        self.assertLess(order.index("c"), order.index("e"))

    def test_cycle_detection(self):
        nodes = [{"key": k} for k in ("s", "a", "b")]
        edges = [{"from": "s", "to": "a"}, {"from": "a", "to": "b"},
                 {"from": "b", "to": "a"}]
        cycles = services.detect_cycles(services.build_adjacency(nodes, edges))
        self.assertTrue(cycles)
        self.assertIn("a", cycles[0])

    def test_longest_sla_path(self):
        adjacency = self._adjacency()
        minutes, path = services.longest_sla_path(
            adjacency, {"s": 0, "a": 30, "b": 10, "c": 60, "e": 0})
        self.assertEqual(minutes, 90)
        self.assertEqual(path, ["s", "a", "c"])

    def test_validate_payload_reports_errors(self):
        report = services.validate_payload({
            "nodes": [
                {"key": "start", "node_type": "start"},
                {"key": "end", "node_type": "end"},
                {"key": "start", "node_type": "task"},
            ],
            "transitions": [{"from": "start", "to": "missing"}],
        })
        self.assertFalse(report["valid"])
        messages = " ".join(item["message"] for item in report["errors"])
        self.assertIn("重复", messages)
        self.assertIn("不存在", messages)
        self.assertIn("开始节点", messages)


class DefinitionApiTests(WorkflowBase):
    """定义与版本：创建、整图保存、校验、发布、回滚、克隆、导入导出。"""

    def test_create_save_validate_publish(self):
        created = self.assert_ok(self.post("/definitions/create/", {
            "code": "leave_a", "name": "请假流程", "category": "人事",
            "description": "年假与事假",
        }, user=self.alice))
        pk = created["id"]
        self.assertEqual(created["status"], "draft")

        nodes = [
            {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
            {"key": "approve", "name": "主管审批", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.bob.id]}, "sla_minutes": 120},
            {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
        ]
        edges = [
            {"from": "start", "to": "approve", "label": "提交"},
            {"from": "approve", "to": "end", "label": "通过"},
        ]
        saved = self.assert_ok(self.post(f"/definitions/{pk}/graph/save/", {
            "nodes": nodes, "transitions": edges,
        }, user=self.alice))
        self.assertTrue(saved["saved"])
        self.assertTrue(saved["validation"]["valid"])

        checked = self.assert_ok(self.get(f"/definitions/{pk}/validate/", user=self.alice))
        self.assertTrue(checked["valid"])
        self.assertEqual(checked["stats"]["node_count"], 3)

        published = self.assert_ok(self.post(f"/definitions/{pk}/publish/",
                                             {"note": "首次发布"}, user=self.alice))
        self.assertEqual(published["version"]["version_no"], 1)
        self.assertEqual(published["definition"]["status"], "published")

        detail = self.assert_ok(self.get(f"/definitions/{pk}/", user=self.alice))
        self.assertEqual(len(detail["nodes"]), 3)
        self.assertEqual(len(detail["transitions"]), 2)
        self.assertTrue(detail["validation"]["valid"])

        stats = self.assert_ok(self.get(f"/definitions/{pk}/stats/", user=self.alice))
        self.assertEqual(stats["total"], 0)
        self.assertIn("validation", stats)

    def test_invalid_graph_cannot_be_saved_strict(self):
        definition = self.make_definition()
        response = self.post(f"/definitions/{definition.id}/graph/save/", {
            "nodes": [{"key": "start", "node_type": "start"}],
            "transitions": [],
        }, user=self.alice)
        self.assert_fail(response, "校验未通过")

        # strict=false 允许存草稿，但必须把问题带回来
        loose = self.assert_ok(self.post(f"/definitions/{definition.id}/graph/save/", {
            "nodes": [{"key": "start", "node_type": "start"}],
            "transitions": [], "strict": False,
        }, user=self.alice))
        self.assertFalse(loose["validation"]["valid"])

    def test_design_node_and_transition_crud(self):
        definition = self.make_definition(
            nodes=[{"key": "start", "node_type": "start", "assignee_type": "none"}],
            edges=[],
        )
        start = definition.nodes.get(key="start")
        node = self.assert_ok(self.post(f"/definitions/{definition.id}/nodes/create/", {
            "key": "approve", "name": "审批", "assignee_type": "user",
            "assignee_rule": {"user_ids": [self.bob.id]},
        }, user=self.alice))
        end = self.assert_ok(self.post(f"/definitions/{definition.id}/nodes/create/", {
            "key": "end", "name": "结束", "node_type": "end", "assignee_type": "none",
        }, user=self.alice))
        self.assert_ok(self.post(f"/definitions/{definition.id}/transitions/create/", {
            "from_key": "start", "to_key": "approve",
        }, user=self.alice))
        edge = self.assert_ok(self.post(f"/definitions/{definition.id}/transitions/create/", {
            "from_key": "approve", "to_key": "end", "label": "通过",
        }, user=self.alice))

        listing = self.assert_ok(self.get(f"/definitions/{definition.id}/nodes/", user=self.alice))
        self.assertEqual(listing["count"], 3)
        self.assert_ok(self.post(f"/nodes/{node['id']}/update/", {
            "name": "部门审批", "sla_minutes": 30,
        }, user=self.alice))
        options = self.assert_ok(self.get(f"/definitions/{definition.id}/node-options/",
                                          user=self.alice))
        self.assertTrue(options["users"])
        self.assertTrue(options["roles"])

        graph = self.assert_ok(self.get(f"/definitions/{definition.id}/graph/", user=self.alice))
        self.assertTrue(graph["validation"]["valid"])
        self.assertEqual(graph["definition"]["status"], "draft")

        self.assert_ok(self.post(f"/transitions/{edge['id']}/delete/", user=self.alice))
        self.assert_ok(self.post(f"/nodes/{end['id']}/delete/", user=self.alice))
        self.assertEqual(definition.nodes.count(), 2)

    def test_version_publish_diff_rollback(self):
        definition = self.make_definition(publish=True)
        self.assert_ok(self.post(f"/definitions/{definition.id}/publish/",
                                 {"note": "二次发布"}, user=self.alice))
        versions = self.assert_ok(self.get(f"/definitions/{definition.id}/versions/",
                                           user=self.alice))
        self.assertEqual(versions["count"], 2)
        first = versions["items"][-1]
        second = versions["items"][0]

        diff = self.assert_ok(self.get("/versions/diff/", {
            "from_id": first["id"], "to_id": second["id"],
        }, user=self.alice))
        self.assertEqual(diff["summary"]["changed"], 0)
        self.assertEqual(diff["nodes"]["added"], [])

        detail = self.assert_ok(self.get(f"/versions/{second['id']}/", user=self.alice))
        self.assertTrue(detail["snapshot"]["nodes"])

        rolled = self.assert_ok(self.post(f"/versions/{first['id']}/rollback/",
                                          {"note": "回到首版"}, user=self.alice))
        self.assertEqual(rolled["rolled_back_from"], first["version_no"])
        definition.refresh_from_db()
        self.assertEqual(definition.status, "published")
        self.assertEqual(definition.nodes.count(), 3)

    def test_clone_export_import(self):
        definition = self.make_definition(code="contract", publish=True)
        clone = self.assert_ok(self.post(f"/definitions/{definition.id}/clone/", {
            "code": "contract_copy", "name": "合同副本",
        }, user=self.alice))
        self.assertEqual(clone["status"], "draft")
        self.assertEqual(clone["node_count"], 3)

        exported = self.assert_ok(self.get(f"/definitions/{definition.id}/export/",
                                           user=self.alice))
        self.assertEqual(exported["source"]["code"], "contract")
        self.assertTrue(exported["validation"]["valid"])

        dry = self.assert_ok(self.post("/definitions/import/", {
            "payload": exported, "dry_run": True, "code": "contract_import",
        }, user=self.alice))
        self.assertTrue(dry["dry_run"])
        self.assertTrue(dry["valid"])
        self.assertFalse(WorkflowDefinition.objects.filter(code="contract_import").exists())

        imported = self.assert_ok(self.post("/definitions/import/", {
            "payload": exported, "code": "contract_import", "name": "导入流程",
        }, user=self.alice))
        self.assertTrue(imported["imported"])
        self.assertEqual(WorkflowDefinition.objects.get(
            pk=imported["definition_id"]).nodes.count(), 3)

    def test_definition_permission_isolation(self):
        definition = self.make_definition(publish=True)
        self.assert_fail(self.get(f"/definitions/{definition.id}/", user=self.carol), "无权")
        self.assert_fail(self.post(f"/definitions/{definition.id}/update/",
                                   {"name": "越权改名"}, user=self.carol), "无权")
        self.assert_fail(self.post(f"/definitions/{definition.id}/clone/", {}, user=self.carol),
                         "无权")

    def test_missing_definition_returns_400(self):
        self.assert_fail(self.get("/definitions/999999/", user=self.alice), "不存在")


class RuntimeFlowTests(WorkflowBase):
    """运行态：串行审批、拒绝、取消、终止、变量、评论、附件、快照。"""

    def test_start_approve_and_complete(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition, title="张三请假", context={"days": 3})
        self.assertEqual(instance.status, "running")
        task = self.open_task(instance)
        self.assertIsNotNone(task)
        self.assertEqual(task.assignee_id, self.bob.id)

        pending = self.assert_ok(self.get("/tasks/my-pending/", user=self.bob))
        self.assertEqual(pending["count"], 1)
        self.assertEqual(pending["items"][0]["id"], task.id)
        self.assertTrue(pending["items"][0]["can_operate"])

        result = self.assert_ok(self.complete(task, self.bob, comment="同意"))
        self.assertEqual(result["instance"]["status"], "completed")
        self.assertEqual(result["task"]["status"], "completed")

        done = self.assert_ok(self.get("/tasks/my-done/", user=self.bob))
        self.assertEqual(done["count"], 1)
        self.assertEqual(done["items"][0]["action"], "approve")

        # 重复办理必须 400（实例已结束 / 任务已完成）
        self.assert_fail(self.complete(task, self.bob), "已结束")
        self.assertEqual(WorkflowTask.objects.filter(instance=instance, status="completed").count(), 1)

        detail = self.assert_ok(self.get(f"/instances/{instance.id}/", user=self.alice))
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["open_task_count"], 0)
        self.assertEqual(detail["stats"]["task_total"], 1)

    def test_reject_ends_instance(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        result = self.assert_ok(self.complete(task, self.bob, action="reject", comment="不符合要求"))
        self.assertEqual(result["instance"]["status"], "rejected")
        self.assertEqual(WorkflowTask.objects.filter(
            instance=instance, status__in=("pending", "claimed")).count(), 0)

    def test_cancel_and_terminate(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        self.assert_fail(self.post(f"/instances/{instance.id}/cancel/", {},
                                   user=self.carol), "无权")
        cancelled = self.assert_ok(self.post(f"/instances/{instance.id}/cancel/",
                                             {"reason": "不需要了"}, user=self.alice))
        self.assertEqual(cancelled["status"], "cancelled")
        self.assert_fail(self.post(f"/instances/{instance.id}/cancel/", {}, user=self.alice),
                         "运行中")

        second = self.start_instance(definition)
        self.assert_fail(self.post(f"/instances/{second.id}/terminate/", {}, user=self.alice),
                         "原因")
        terminated = self.assert_ok(self.post(f"/instances/{second.id}/terminate/",
                                              {"reason": "流程配置错误"}, user=self.alice))
        self.assertEqual(terminated["status"], "terminated")

    def test_variables_comments_attachments(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        saved = self.assert_ok(self.post(f"/instances/{instance.id}/variables/set/", {
            "variables": {"days": 3, "urgent": True, "note": "住院"},
        }, user=self.alice))
        self.assertEqual(saved["count"], 3)
        variables = self.assert_ok(self.get(f"/instances/{instance.id}/variables/",
                                            user=self.alice))
        self.assertEqual(variables["count"], 3)
        single = self.assert_ok(self.post(f"/instances/{instance.id}/variables/set/", {
            "key": "amount", "value": 128.5,
        }, user=self.alice))
        self.assertEqual(single["saved"][0]["var_type"], "number")

        comment = self.assert_ok(self.post(f"/instances/{instance.id}/comments/create/", {
            "content": "请尽快处理",
        }, user=self.alice))
        self.assertEqual(comment["content"], "请尽快处理")
        listed = self.assert_ok(self.get(f"/instances/{instance.id}/comments/", user=self.bob))
        self.assertEqual(listed["count"], 1)

        self.assert_fail(self.post(f"/instances/{instance.id}/comments/create/", {
            "content": "内部备注", "is_internal": True,
        }, user=self.dave), "无权")
        internal = self.assert_ok(self.post(f"/instances/{instance.id}/comments/create/", {
            "content": "仅内部可见", "is_internal": True,
        }, user=self.bob))
        self.assertTrue(internal["is_internal"])
        # 未参与人连实例都看不到，评论列表沿用同一可见性边界直接拒绝
        self.assert_fail(self.get(f"/instances/{instance.id}/comments/", user=self.dave), "无权")
        participant_view = self.assert_ok(self.get(f"/instances/{instance.id}/comments/",
                                                   user=self.bob))
        self.assertEqual(participant_view["count"], 2)
        self.assertTrue(any(item["is_internal"] for item in participant_view["items"]))

        attachment = self.assert_ok(self.post(f"/instances/{instance.id}/attachments/create/", {
            "name": "病历.pdf", "url": "/files/1", "size": 2048, "mime": "application/pdf",
        }, user=self.alice))
        self.assertEqual(attachment["name"], "病历.pdf")
        attachments = self.assert_ok(self.get(f"/instances/{instance.id}/attachments/",
                                              user=self.alice))
        self.assertEqual(attachments["count"], 1)

    def test_timeline_snapshot_replay(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        timeline = self.assert_ok(self.get(f"/instances/{instance.id}/timeline/",
                                           user=self.alice))
        actions = [item["action"] for item in timeline["items"]]
        self.assertIn("instance.started", actions)
        self.assertIn("task.created", actions)

        snapshot = self.assert_ok(self.post(f"/instances/{instance.id}/snapshots/create/",
                                            {}, user=self.alice))
        self.assertEqual(snapshot["reason"], "manual")
        snapshots = self.assert_ok(self.get(f"/instances/{instance.id}/snapshots/",
                                            user=self.alice))
        self.assertGreaterEqual(snapshots["count"], 2)

        replay = self.assert_ok(self.get(f"/instances/{instance.id}/replay/", user=self.alice))
        self.assertGreaterEqual(replay["count"], 2)
        self.assertEqual(replay["frames"][0]["seq"], 1)
        self.assertIn("state", replay["frames"][0])

    def test_start_validations(self):
        draft = self.make_definition(publish=False)
        self.assert_fail(self.post("/instances/start/", {"definition_id": draft.id},
                                   user=self.alice), "未发布")
        published = self.make_definition(publish=True)
        first = self.start_instance(published, business_no="BIZ-0001")
        self.assertEqual(first.business_no, "BIZ-0001")
        self.assert_fail(self.post("/instances/start/", {
            "definition_id": published.id, "business_no": "BIZ-0001",
        }, user=self.alice), "已存在")
        self.assert_fail(self.post("/instances/start/", {}, user=self.alice), "definition_id")

    def test_instance_list_filters_and_pagination(self):
        definition = self.make_definition(publish=True)
        for _ in range(3):
            self.start_instance(definition)
        listing = self.assert_ok(self.get("/instances/", {
            "status": "running", "page": 1, "page_size": 2,
        }, user=self.alice))
        self.assertEqual(listing["count"], 3)
        self.assertEqual(len(listing["items"]), 2)
        self.assertEqual(listing["page_size"], 2)
        capped = self.assert_ok(self.get("/instances/", {"page_size": 999},
                                         user=self.alice))
        self.assertEqual(capped["page_size"], 200)
        no_match = self.assert_ok(self.get("/instances/", {"status": "completed"},
                                           user=self.alice))
        self.assertEqual(no_match["count"], 0)


class TaskOperationTests(WorkflowBase):
    """任务办理：退回、加签、转办、委派、批量与权限。"""

    def _two_step_definition(self):
        nodes = [
            {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
            {"key": "review", "name": "初审", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.bob.id]}, "sla_minutes": 60},
            {"key": "approve", "name": "终审", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.carol.id]}, "sla_minutes": 60},
            {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
        ]
        edges = [
            {"from": "start", "to": "review"},
            {"from": "review", "to": "approve"},
            {"from": "approve", "to": "end"},
        ]
        return self.make_definition(nodes=nodes, edges=edges, publish=True)

    def test_return_to_previous_node(self):
        definition = self._two_step_definition()
        instance = self.start_instance(definition)
        review = self.open_task(instance, "review")
        self.assert_ok(self.complete(review, self.bob))
        final = self.open_task(instance, "approve")
        self.assertIsNotNone(final)

        self.assert_ok(self.complete(final, self.carol, action="return",
                                     target_node_key="review", comment="材料不全"))
        back = self.open_task(instance, "review")
        self.assertIsNotNone(back)
        self.assertEqual(back.assignee_id, self.bob.id)
        self.assertEqual(back.id != review.id, True)

        self.assert_ok(self.complete(back, self.bob))
        final_again = self.open_task(instance, "approve")
        self.assert_ok(self.complete(final_again, self.carol))
        instance.refresh_from_db()
        self.assertEqual(instance.status, "completed")

    def test_add_sign(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        result = self.assert_ok(self.complete(task, self.bob, action="add_sign",
                                              add_sign_user_ids=[self.carol.id],
                                              comment="请财务会签"))
        self.assertEqual(result["instance"]["status"], "running")
        sign_task = WorkflowTask.objects.filter(
            instance=instance, node__key="approve", assignee=self.carol,
            status__in=("pending", "claimed")).first()
        self.assertIsNotNone(sign_task)
        self.assertEqual(sign_task.parent_task_id, task.id)

        self.assert_ok(self.complete(sign_task, self.carol))
        instance.refresh_from_db()
        self.assertEqual(instance.status, "completed")

    def test_transfer_task(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        transferred = self.assert_ok(self.post(f"/tasks/{task.id}/transfer/", {
            "target_user_id": self.carol.id, "comment": "我不在",
        }, user=self.bob))
        self.assertEqual(transferred["assignee"]["id"], self.carol.id)
        self.assertEqual(transferred["status"], "claimed")

        bob_pending = self.assert_ok(self.get("/tasks/my-pending/", user=self.bob))
        self.assertEqual(bob_pending["count"], 0)
        carol_pending = self.assert_ok(self.get("/tasks/my-pending/", user=self.carol))
        self.assertEqual([x["id"] for x in carol_pending["items"]], [task.id])
        self.assert_ok(self.complete(task, self.carol))

    def test_delegate_task_keeps_candidates(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        delegated = self.assert_ok(self.post(f"/tasks/{task.id}/delegate/", {
            "target_user_id": self.carol.id, "comment": "帮忙处理",
        }, user=self.bob))
        self.assertEqual(delegated["assignee"]["id"], self.carol.id)
        self.assertIn(self.bob.id, delegated["candidate_users"])

        # 原办理人仍可接管（候选集保留）
        self.assert_ok(self.complete(task, self.bob, comment="我自己来"))

    def test_batch_complete(self):
        definition = self.make_definition(publish=True)
        first = self.start_instance(definition)
        second = self.start_instance(definition)
        ids = [self.open_task(first).id, self.open_task(second).id]
        data = self.assert_ok(self.post("/tasks/batch-complete/", {
            "task_ids": ids, "action": "approve", "comment": "批量同意",
        }, user=self.bob))
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failed_count"], 0)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")

        mixed = self.assert_ok(self.post("/tasks/batch-complete/", {
            "task_ids": [ids[0], 999999], "action": "approve",
        }, user=self.bob))
        self.assertEqual(mixed["success_count"], 0)
        self.assertEqual(mixed["failed_count"], 2)

    def test_only_assignee_can_operate(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        # 外部用户看不到实例；即便可见也会被办理人校验拦下
        response = self.complete(task, self.dave)
        self.assertEqual(response.status_code, 400)
        task.refresh_from_db()
        self.assertIn(task.status, ("pending", "claimed"))
        instance.refresh_from_db()
        self.assertEqual(instance.status, "running")

    def test_task_detail_and_overdue_list(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        detail = self.assert_ok(self.get(f"/tasks/{task.id}/", user=self.bob))
        self.assertEqual(detail["id"], task.id)
        self.assertTrue(detail["can_operate"])
        self.assertIn("instance", detail)

        task.due_at = timezone.now() - timedelta(hours=2)
        task.is_overdue = True
        task.save(update_fields=["due_at", "is_overdue", "updated_at"])
        overdue = self.assert_ok(self.get("/tasks/overdue/", user=self.bob))
        self.assertEqual(overdue["count"], 1)
        self.assertEqual(overdue["items"][0]["overdue_minutes"] >= 0, True)
        self.assertEqual(overdue["summary"]["overdue_total"], 1)

    def test_my_pending_includes_candidate_pool(self):
        nodes = self.simple_nodes()
        nodes[1]["assignee_rule"] = {"user_ids": [self.bob.id, self.carol.id]}
        definition = self.make_definition(nodes=nodes, publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        self.assertIsNone(task.assignee_id)
        self.assertEqual(task.status, "pending")
        for user in (self.bob, self.carol):
            pending = self.assert_ok(self.get("/tasks/my-pending/", user=user))
            self.assertEqual(pending["count"], 1)
        claimed = self.assert_ok(self.post(f"/tasks/{task.id}/claim/", {}, user=self.carol))
        self.assertEqual(claimed["assignee"]["id"], self.carol.id)
        self.assert_ok(self.complete(task, self.carol))


class GatewayFlowTests(WorkflowBase):
    """网关：条件分支与并行拆分/汇聚。"""

    def test_decision_branch_by_context(self):
        nodes = [
            {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
            {"key": "decide", "name": "金额判断", "node_type": "decision",
             "assignee_type": "none"},
            {"key": "high", "name": "大额审批", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.bob.id]}},
            {"key": "low", "name": "普通审批", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.carol.id]}},
            {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
        ]
        edges = [
            {"from": "start", "to": "decide"},
            {"from": "decide", "to": "high", "condition": "amount >= 5000", "priority": 10},
            {"from": "decide", "to": "low", "is_default": True, "priority": 20},
            {"from": "high", "to": "end"},
            {"from": "low", "to": "end"},
        ]
        definition = self.make_definition(nodes=nodes, edges=edges, publish=True)

        big = self.start_instance(definition, context={"amount": 8000})
        self.assertIsNotNone(self.open_task(big, "high"))
        self.assertIsNone(self.open_task(big, "low"))
        self.assert_ok(self.complete(self.open_task(big, "high"), self.bob))
        big.refresh_from_db()
        self.assertEqual(big.status, "completed")

        small = self.start_instance(definition, context={"amount": 100})
        self.assertIsNotNone(self.open_task(small, "low"))
        self.assertIsNone(self.open_task(small, "high"))

    def test_parallel_split_and_join_completes_once(self):
        nodes = [
            {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
            {"key": "split", "name": "并行", "node_type": "parallel_split",
             "assignee_type": "none"},
            {"key": "a", "name": "技术评审", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.bob.id]}},
            {"key": "b", "name": "财务评审", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.carol.id]}},
            {"key": "join", "name": "汇聚", "node_type": "parallel_join",
             "assignee_type": "none"},
            {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
        ]
        edges = [
            {"from": "start", "to": "split"},
            {"from": "split", "to": "a", "label": "技术"},
            {"from": "split", "to": "b", "label": "财务"},
            {"from": "a", "to": "join"},
            {"from": "b", "to": "join"},
            {"from": "join", "to": "end"},
        ]
        definition = self.make_definition(nodes=nodes, edges=edges, publish=True)
        instance = self.start_instance(definition)
        self.assertEqual(WorkflowTask.objects.filter(
            instance=instance, status__in=("pending", "claimed")).count(), 2)

        self.assert_ok(self.complete(self.open_task(instance, "a"), self.bob))
        instance.refresh_from_db()
        self.assertEqual(instance.status, "running")
        # 已到汇聚点的分支令牌仍在等待另一条入边，所以活跃令牌是 2（汇聚点 1 + b 分支 1）
        self.assertEqual(instance.active_token_count(), 2)

        self.assert_ok(self.complete(self.open_task(instance, "b"), self.carol))
        instance.refresh_from_db()
        self.assertEqual(instance.status, "completed")
        self.assertEqual(instance.active_token_count(), 0)
        self.assertEqual(instance.tokens.filter(status="active").count(), 0)

    def test_parallel_branch_reject_does_not_complete(self):
        nodes = [
            {"key": "start", "name": "开始", "node_type": "start", "assignee_type": "none"},
            {"key": "split", "name": "并行", "node_type": "parallel_split",
             "assignee_type": "none"},
            {"key": "a", "name": "技术评审", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.bob.id]}},
            {"key": "b", "name": "财务评审", "assignee_type": "user",
             "assignee_rule": {"user_ids": [self.carol.id]}},
            {"key": "join", "name": "汇聚", "node_type": "parallel_join",
             "assignee_type": "none"},
            {"key": "end", "name": "结束", "node_type": "end", "assignee_type": "none"},
        ]
        edges = [
            {"from": "start", "to": "split"},
            {"from": "split", "to": "a"}, {"from": "split", "to": "b"},
            {"from": "a", "to": "join"}, {"from": "b", "to": "join"},
            {"from": "join", "to": "end"},
        ]
        definition = self.make_definition(nodes=nodes, edges=edges, publish=True)
        instance = self.start_instance(definition)
        self.assert_ok(self.complete(self.open_task(instance, "a"), self.bob,
                                     action="reject", comment="技术不通过"))
        instance.refresh_from_db()
        self.assertEqual(instance.status, "rejected")
        self.assertEqual(WorkflowTask.objects.filter(
            instance=instance, status__in=("pending", "claimed")).count(), 0)


class CollaborationTests(WorkflowBase):
    """协作：委托、通知、Webhook、SLA 策略、审计。"""

    def test_delegation_crud_and_effect_on_assignment(self):
        created = self.assert_ok(self.post("/delegations/create/", {
            "to_user_id": self.carol.id, "scope": "all",
            "start_at": iso_after(minutes=-1), "end_at": iso_after(days=2),
            "reason": "休假",
        }, user=self.bob))
        self.assertEqual(created["status"], "active")
        self.assertEqual(created["to_user"]["id"], self.carol.id)

        self.assert_fail(self.post("/delegations/create/", {
            "to_user_id": self.carol.id, "scope": "all", "end_at": iso_after(days=3),
        }, user=self.bob), "已存在")

        out_list = self.assert_ok(self.get("/delegations/", {"direction": "out"},
                                           user=self.bob))
        self.assertEqual(out_list["count"], 1)
        in_list = self.assert_ok(self.get("/delegations/", {"direction": "in"},
                                          user=self.carol))
        self.assertEqual(in_list["count"], 1)

        # 委托生效后，新任务的候选池会自动加入受托人
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        self.assertIn(self.carol.id, task.candidate_users)
        self.assertIn(self.bob.id, task.candidate_users)

        self.assert_fail(self.post(f"/delegations/{created['id']}/revoke/", {},
                                   user=self.dave), "委托人")
        revoked = self.assert_ok(self.post(f"/delegations/{created['id']}/revoke/", {},
                                           user=self.bob))
        self.assertEqual(revoked["status"], "revoked")

    def test_notifications_and_read(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        listing = self.assert_ok(self.get("/notifications/", {"status": "unread"},
                                          user=self.bob))
        self.assertGreaterEqual(listing["count"], 1)
        self.assertGreaterEqual(listing["unread"], 1)
        notification = listing["items"][0]

        summary = self.assert_ok(self.get("/notifications/summary/", user=self.bob))
        self.assertGreaterEqual(summary["unread"], 1)

        read = self.assert_ok(self.post(f"/notifications/{notification['id']}/read/",
                                        {}, user=self.bob))
        self.assertEqual(read["status"], "read")
        self.assert_fail(self.post(f"/notifications/{notification['id']}/read/", {},
                                   user=self.carol), "自己的通知")

        marked = self.assert_ok(self.post("/notifications/read/", {}, user=self.bob))
        self.assertGreaterEqual(marked["marked"], 0)
        self.assertEqual(marked["unread"], 0)

    def test_webhook_simulated_delivery(self):
        webhook = self.assert_ok(self.post("/webhooks/create/", {
            "name": "事件订阅", "url": "https://example.com/hook",
            "events": ["task.created", "instance.*"],
        }, user=self.alice))
        self.assertTrue(webhook["active"])
        self.assert_fail(self.post("/webhooks/create/", {
            "name": "坏地址", "url": "ftp://example.com",
        }, user=self.alice), "http")

        definition = self.make_definition(publish=True)
        self.start_instance(definition)
        webhook_obj = WorkflowWebhook.objects.get(pk=webhook["id"])
        self.assertEqual(webhook_obj.last_status, "simulated_success")
        self.assertIsNotNone(webhook_obj.last_delivery_at)
        deliveries = WorkflowNotification.objects.filter(
            recipient=self.alice, channel="webhook")
        self.assertGreaterEqual(deliveries.count(), 1)
        payload = deliveries.first().payload
        self.assertIn("event", payload)

        updated = self.assert_ok(self.post(f"/webhooks/{webhook['id']}/update/", {
            "active": False,
        }, user=self.alice))
        self.assertFalse(updated["active"])
        listing = self.assert_ok(self.get("/webhooks/", user=self.alice))
        self.assertEqual(listing["count"], 1)
        self.assert_ok(self.post(f"/webhooks/{webhook['id']}/delete/", {}, user=self.alice))
        self.assertFalse(WorkflowWebhook.objects.filter(pk=webhook["id"]).exists())

    def test_sla_policy_create_and_validation(self):
        policy = self.assert_ok(self.post("/sla-policies/create/", {
            "code": "urgent_4h", "name": "紧急四小时",
            "priority": "urgent", "response_minutes": 60, "resolve_minutes": 240,
        }, user=self.alice))
        self.assertEqual(policy["resolve_minutes"], 240)
        self.assert_fail(self.post("/sla-policies/create/", {
            "code": "urgent_4h", "name": "重复编码",
        }, user=self.alice), "已存在")
        self.assert_fail(self.post("/sla-policies/create/", {
            "code": "bad_window", "name": "倒挂", "response_minutes": 600,
            "resolve_minutes": 60,
        }, user=self.alice), "解决时限")
        listing = self.assert_ok(self.get("/sla-policies/", user=self.alice))
        self.assertEqual(listing["count"], 1)
        self.assertTrue(WorkflowSlaPolicy.objects.filter(code="urgent_4h").exists())

    def test_audit_instance_and_global(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        audit = self.assert_ok(self.get(f"/instances/{instance.id}/audit/", user=self.alice))
        self.assertGreaterEqual(audit["count"], 2)
        actions = [row["action"] for row in audit["items"]]
        self.assertIn("instance.started", actions)

        global_audit = self.assert_ok(self.get("/audit/", {"instance_id": instance.id},
                                               user=self.alice))
        self.assertGreaterEqual(global_audit["count"], 2)
        outsider = self.assert_ok(self.get("/audit/", {"instance_id": instance.id},
                                           user=self.dave))
        self.assertEqual(outsider["count"], 0)


class MonitoringAndSlaTests(WorkflowBase):
    """监控与 SLA：扫描幂等、指标、分布、趋势、瓶颈、大盘。"""

    def test_sla_scan_is_idempotent(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        task = self.open_task(instance)
        past = timezone.now() - timedelta(hours=3)
        WorkflowTask.objects.filter(pk=task.pk).update(due_at=past, is_overdue=False)
        WorkflowInstance.objects.filter(pk=instance.pk).update(due_at=past)

        first = self.assert_ok(self.post("/monitor/sla-scan/", {}, user=self.admin))
        counts = first["counts"]
        self.assertEqual(counts["newly_overdue"], 1)
        self.assertEqual(counts["instances_flagged"], 1)
        self.assertGreaterEqual(counts["notified"], 1)
        task.refresh_from_db()
        self.assertTrue(task.is_overdue)

        second = self.assert_ok(self.post("/monitor/sla-scan/", {}, user=self.admin))
        self.assertEqual(second["counts"]["newly_overdue"], 0)
        self.assertEqual(second["counts"]["instances_flagged"], 0)
        self.assertEqual(WorkflowNotification.objects.filter(
            recipient=self.bob, dedup_key=f"overdue:task:{task.id}").count(), 1)

        overdue = self.assert_ok(self.get("/tasks/overdue/", user=self.bob))
        self.assertEqual(overdue["count"], 1)

    def test_metrics_dashboard_and_distributions(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        self.assert_ok(self.complete(self.open_task(instance), self.bob))

        metrics = self.assert_ok(self.get("/monitor/metrics/", {"days": 30}, user=self.alice))
        self.assertGreaterEqual(metrics["instances"]["total"], 1)
        self.assertGreaterEqual(metrics["instances"]["completed"], 1)
        self.assertGreater(metrics["instances"]["completion_rate_pct"], 0)
        self.assertGreaterEqual(metrics["tasks"]["total"], 1)

        statuses = self.assert_ok(self.get("/monitor/status-distribution/", user=self.alice))
        self.assertGreaterEqual(statuses["total"], 1)
        self.assertTrue(statuses["items"])

        categories = self.assert_ok(self.get("/monitor/category-distribution/", user=self.alice))
        self.assertGreaterEqual(categories["count"], 1)

        trend = self.assert_ok(self.get("/monitor/trend/", {"days": 14}, user=self.alice))
        self.assertEqual(len(trend["items"]), 14)
        self.assertGreaterEqual(sum(x["started"] for x in trend["items"]), 1)

        bottlenecks = self.assert_ok(self.get("/monitor/bottlenecks/", user=self.alice))
        self.assertTrue(bottlenecks["items"])
        self.assertEqual(bottlenecks["items"][0]["node_key"], "approve")

        dashboard = self.assert_ok(self.get("/monitor/dashboard/", user=self.alice))
        self.assertIn("metrics", dashboard)
        self.assertIn("my", dashboard)
        self.assertEqual(dashboard["metrics"]["instances"]["completed"], 1)

    def test_running_instances_endpoint(self):
        definition = self.make_definition(publish=True)
        self.start_instance(definition)
        running = self.assert_ok(self.get("/monitor/running/", user=self.alice))
        self.assertEqual(running["count"], 1)
        self.assertEqual(running["items"][0]["active_token_count"], 1)
        self.assertEqual(running["summary"]["running_total"], 1)


class CatalogAndPermissionTests(WorkflowBase):
    """目录、分页契约与数据范围。"""

    def test_catalog_contains_endpoint_index(self):
        data = self.assert_ok(self.get("/catalog/", user=self.alice))
        self.assertEqual(data["endpoint_count"], len(data["endpoints"]))
        self.assertGreaterEqual(data["endpoint_count"], 76)
        paths = [item["path"] for item in data["endpoints"]]
        self.assertNotIn("catalog/", paths)
        self.assertIn("instances/start/", paths)
        self.assertIn("tasks/my-pending/", paths)
        self.assertIn("monitor/metrics/", paths)
        self.assertEqual(data["pagination"]["page_size_max"], 200)
        self.assertTrue(data["expression"]["operators"])
        self.assertIn("definitions", data["counts"])

    def test_definition_list_scope_and_filters(self):
        self.make_definition(owner=self.alice, code="alice_flow", publish=True)
        self.make_definition(owner=self.bob, code="bob_flow")
        alice_list = self.assert_ok(self.get("/definitions/", user=self.alice))
        self.assertEqual(alice_list["count"], 1)
        self.assertEqual(alice_list["items"][0]["code"], "alice_flow")

        searched = self.assert_ok(self.get("/definitions/", {"q": "alice_flow"},
                                           user=self.alice))
        self.assertEqual(searched["count"], 1)
        missing = self.assert_ok(self.get("/definitions/", {"q": "nothing"},
                                          user=self.alice))
        self.assertEqual(missing["count"], 0)

        admin_list = self.assert_ok(self.get("/definitions/", user=self.admin))
        self.assertEqual(admin_list["count"], 2)

    def test_instance_visibility_for_participant(self):
        definition = self.make_definition(publish=True)
        instance = self.start_instance(definition)
        self.assert_fail(self.get(f"/instances/{instance.id}/", user=self.dave), "无权")
        bob_detail = self.assert_ok(self.get(f"/instances/{instance.id}/", user=self.bob))
        self.assertEqual(bob_detail["id"], instance.id)
        self.assert_fail(self.post(f"/instances/{instance.id}/variables/set/", {
            "variables": {"x": 1},
        }, user=self.dave), "无权")

    def test_pagination_shape_is_stable(self):
        definition = self.make_definition(publish=True)
        self.start_instance(definition)
        tasks = self.assert_ok(self.get("/tasks/", user=self.bob))
        self.assertEqual(set(tasks.keys()) >= {"items", "count", "page", "page_size"}, True)
        self.assertEqual(tasks["page"], 1)
        self.assertEqual(tasks["page_size"], 20)
        audit = self.assert_ok(self.get("/audit/", user=self.alice))
        self.assertTrue({"items", "count", "page", "page_size"} <= set(audit.keys()))

    def test_unknown_route_and_unauthenticated(self):
        anonymous = APIClient()
        response = anonymous.get(f"{BASE}/instances/")
        self.assertIn(response.status_code, (401, 403))
        missing = self.get("/instances/999999/", user=self.alice)
        self.assert_fail(missing, "不存在")
