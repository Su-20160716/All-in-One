# -*- coding: utf-8 -*-
"""pipeline 测试：连接器 / 连接、DAG 校验、节点执行、调度、质量、血缘、
画像、Webhook、统计与行级权限隔离。

运行：venv/Scripts/python.exe manage.py test pipeline -v 1
（测试库为内存 sqlite，不触碰开发库，也不发起任何网络 / SQL 请求）
"""
from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from pipeline.models import (Connector, DataQualityRule, Pipeline, PipelineRun,
                             RunStep, Schedule, WebhookTrigger)

User = get_user_model()

BASE = "/api/pipeline/"


def ensure_pipeline_tables():
    """测试库补建 pipeline 表。

    本应用暂不提交迁移文件，但空的 migrations 包会让 Django 认为该应用
    「已迁移但没有迁移」，测试库不会 sync 建表。这里只对测试库做一次幂等补建。
    """
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in apps.get_app_config("pipeline").get_models():
            if model._meta.db_table not in existing:
                editor.create_model(model)


class PipelineApiBase(TestCase):
    """接口测试基类：用户、客户端、请求与断言 helper。"""

    @classmethod
    def setUpClass(cls):
        # 必须在 TestCase 开启类级事务之前建表：SQLite 不允许事务内关闭外键检查
        ensure_pipeline_tables()
        super().setUpClass()

    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", password="pass1234", nickname="爱丽丝")
        self.other = User.objects.create_user(
            username="bob", password="pass1234", nickname="鲍勃")
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

    # ---- 数据 helper ----

    def create_pipeline(self, code="pipe_main", name="每日订单汇总", **overrides):
        data = {"code": code, "name": name, **overrides}
        return self.ok(self.post("pipelines/", data))

    def builtin_connector(self, kind="generator"):
        items = self.ok(self.get("connectors/", {"kind": kind}))["items"]
        self.assertTrue(items)
        return items[0]

    def add_flow(self, pipeline_id, count=12, sink_dataset="orders_summary"):
        """建一条 source → filter → map → aggregate → sink 的合法链路。"""
        nodes = [
            {"node_key": "src", "name": "订单源", "node_type": "source", "order": 0,
             "config": {"connector_kind": "generator", "dataset": "orders",
                        "count": count, "seed": 7}},
            {"node_key": "flt", "name": "金额过滤", "node_type": "filter", "order": 1,
             "config": {"condition": "amount >= 100"}},
            {"node_key": "mp", "name": "字段映射", "node_type": "map", "order": 2,
             "config": {"mappings": [
                 {"source": "order_id", "target": "id"},
                 {"source": "amount", "target": "amount"},
                 {"expression": "amount * 2", "target": "amount2"},
                 {"source": "status", "target": "status"},
             ]}},
            {"node_key": "agg", "name": "按状态聚合", "node_type": "aggregate", "order": 3,
             "config": {"group_by": ["status"], "metrics": [
                 {"func": "count", "as": "cnt"},
                 {"func": "sum", "field": "amount", "as": "total"},
             ]}},
            {"node_key": "sink", "name": "落地汇总", "node_type": "sink", "order": 4,
             "config": {"dataset": sink_dataset, "mode": "append"}},
        ]
        edges = [
            {"source": "src", "source_port": "out", "target": "flt", "target_port": "in"},
            {"source": "flt", "source_port": "pass", "target": "mp", "target_port": "in"},
            {"source": "mp", "source_port": "out", "target": "agg", "target_port": "in"},
            {"source": "agg", "source_port": "out", "target": "sink", "target_port": "in"},
        ]
        self.ok(self.post(f"pipelines/{pipeline_id}/nodes/bulk/",
                          {"items": nodes, "replace": True}))
        self.ok(self.post(f"pipelines/{pipeline_id}/edges/bulk/",
                          {"items": edges, "replace": True}))

    def create_flow_pipeline(self, code="pipe_main", count=12, **overrides):
        pipeline = self.create_pipeline(code=code, **overrides)
        self.add_flow(pipeline["id"], count=count)
        return pipeline


class CatalogConnectionTests(PipelineApiBase):
    """目录、连接器、凭据与连接：脱敏、模拟测试与权限边界。"""

    def test_catalog_endpoint_contract(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["endpoint_count"], 82)
        self.assertEqual(len(data["endpoints"]), 82)
        self.assertIn("source", data["node_types"])
        paths = {item["path"] for item in data["endpoints"]}
        self.assertIn("pipelines/<int:pk>/run/", paths)
        self.assertIn("stats/overview/", paths)

    def test_builtin_connectors_and_templates(self):
        templates = self.ok(self.get("connectors/templates/"))
        self.assertGreaterEqual(templates["count"], 5)
        kinds = {item["kind"] for item in templates["items"]}
        self.assertEqual(kinds, {"http", "database", "file", "webhook", "generator"})
        items = self.ok(self.get("connectors/"))["items"]
        self.assertGreaterEqual(len(items), 5)
        self.assertTrue(all(item["builtin"] for item in items))

    def test_custom_connector_crud(self):
        created = self.ok(self.post("connectors/", {
            "name": "自定义 HTTP 源", "kind": "http",
            "capabilities": ["read", "sample"],
            "config_template": {"url": {"type": "string", "required": True}},
            "description": "联调用",
        }))
        self.assertFalse(created["builtin"])
        self.bad(self.post("connectors/", {
            "name": "自定义 HTTP 源", "kind": "http"}))
        updated = self.ok(self.post(f"connectors/{created['id']}/update/", {
            "capabilities": ["read"], "description": "改过", "kind": "file"}))
        self.assertEqual(updated["capabilities"], ["read"])
        builtin = self.builtin_connector("http")
        self.bad(self.post(f"connectors/{builtin['id']}/update/", {"kind": "file"}))
        self.ok(self.post(f"connectors/{created['id']}/delete/", {}))

    def test_credential_ref_never_stores_secret(self):
        created = self.ok(self.post("credentials/", {
            "name": "prod_api_key", "kind": "api_key", "provider": "vault",
            "secret": "plain-text-never-store",
        }))
        self.assertEqual(created["name"], "prod_api_key")
        self.assertNotIn("plain-text-never-store", str(created))
        self.assertIn("secret_notice", created)
        rotated = self.ok(self.post(f"credentials/{created['id']}/rotate/", {}))
        self.assertTrue(rotated["last_rotated_at"])
        self.bad(self.post("credentials/", {"name": "prod_api_key"}))
        self.ok(self.post(f"credentials/{created['id']}/update/",
                          {"description": "生产密钥"}))
        self.ok(self.post(f"credentials/{created['id']}/delete/", {}))

    def test_connection_crud_test_and_masking(self):
        connector = self.ok(self.post("connectors/", {
            "name": "测试 HTTP 连接器", "kind": "http",
            "capabilities": ["read", "sample"]}))["id"]
        self.ok(self.post("credentials/", {"name": "http_key", "kind": "api_key"}))
        created = self.ok(self.post("connections/", {
            "connector_id": connector, "name": "订单接口",
            "config": {"url": "https://api.example.com/v1/orders",
                       "method": "GET", "sample_size": 4,
                       "api_key": "top-secret-value"},
            "secret_ref": "http_key",
        }))
        self.assertNotIn("top-secret-value", str(created))
        self.assertIn("api_key", created["masked_keys"][0])
        detail = self.ok(self.get(f"connections/{created['id']}/"))
        self.assertEqual(detail["config"]["api_key"], "******")
        self.assertEqual(detail["secret_ref"], "http_key")
        tested = self.ok(self.post(f"connections/{created['id']}/test/", {}))
        self.assertEqual(tested["status"], "success")
        self.assertGreater(tested["row_count"], 0)
        toggled = self.ok(self.post(f"connections/{created['id']}/toggle/", {}))
        self.assertEqual(toggled["status"], "disabled")
        self.assertEqual(
            self.ok(self.post(f"connections/{created['id']}/toggle/", {}))["status"],
            "active")
        self.bad(self.post(f"connections/{created['id']}/update/", {
            "config": {"url": "ftp://bad"}}))
        self.bad(self.post("connections/", {
            "connector_id": connector, "name": "坏引用",
            "config": {"url": "https://api.example.com"}, "secret_ref": "missing"}))
        # 被连接引用的凭据不能删
        credential = self.ok(self.get("credentials/", {"q": "http_key"}))["items"][0]
        self.bad(self.post(f"credentials/{credential['id']}/delete/", {}))
        self.ok(self.post(f"connections/{created['id']}/delete/", {}))
        self.ok(self.post(f"credentials/{credential['id']}/delete/", {}))

    def test_connection_permission_isolation(self):
        connector = self.ok(self.post("connectors/", {
            "name": "私有连接器", "kind": "generator"}))["id"]
        connection = self.ok(self.post("connections/", {
            "connector_id": connector, "name": "私有连接",
            "config": {"dataset": "orders", "count": 5}}))
        self.as_user(self.other)
        self.bad(self.get(f"connections/{connection['id']}/"))
        self.bad(self.post(f"connections/{connection['id']}/update/", {"name": "改名"}))
        self.assertEqual(self.ok(self.get("connections/"))["count"], 0)


class PipelineCrudTests(PipelineApiBase):
    """管道 CRUD、画布批量保存、版本 / 导入导出与生命周期。"""

    def test_pipeline_create_update_and_list(self):
        created = self.create_pipeline(tags=["daily", "orders"], row_limit=100)
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["tags"], ["daily", "orders"])
        self.bad(self.post("pipelines/", {"code": "pipe_main", "name": "重复编码"}))
        self.bad(self.post("pipelines/", {"code": "bad code", "name": "非法编码"}))
        listed = self.ok(self.get("pipelines/", {"q": "订单", "status": "draft"}))
        self.assertEqual(listed["count"], 1)
        updated = self.ok(self.post(f"pipelines/{created['id']}/update/", {
            "name": "改名后的管道", "timeout_seconds": 60}))
        self.assertEqual(updated["name"], "改名后的管道")
        self.bad(self.post(f"pipelines/{created['id']}/update/", {"status": "active"}))
        empty = self.ok(self.post(f"pipelines/{created['id']}/validate/", {}))
        self.assertFalse(empty["valid"])
        self.bad(self.post(f"pipelines/{created['id']}/publish/", {}))

    def test_pipeline_permission_isolation(self):
        pipeline = self.create_pipeline()
        self.as_user(self.other)
        self.bad(self.get(f"pipelines/{pipeline['id']}/"))
        self.bad(self.post(f"pipelines/{pipeline['id']}/update/", {"name": "越权"}))
        self.assertEqual(self.ok(self.get("pipelines/"))["count"], 0)
        self.as_user(self.user)
        self.ok(self.get(f"pipelines/{pipeline['id']}/"))

    def test_nodes_edges_mappings_variables(self):
        pipeline = self.create_pipeline()
        pid = pipeline["id"]
        source = self.ok(self.post(f"pipelines/{pid}/nodes/", {
            "node_key": "src", "name": "源", "node_type": "source",
            "config": {"connector_kind": "generator", "dataset": "orders", "count": 5}}))
        self.bad(self.post(f"pipelines/{pid}/nodes/", {
            "node_key": "src", "name": "重复", "node_type": "source",
            "config": {"dataset": "orders"}}))
        self.bad(self.post(f"pipelines/{pid}/nodes/", {
            "node_key": "flt", "name": "坏过滤", "node_type": "filter",
            "config": {}}))
        target = self.ok(self.post(f"pipelines/{pid}/nodes/", {
            "node_key": "sink", "name": "落地", "node_type": "sink",
            "config": {"dataset": "orders_out"}}))
        self.ok(self.post(f"pipelines/{pid}/nodes/reorder/", {
            "items": [{"node_key": "src", "order": 2},
                      {"node_key": "sink", "order": 1}]}))
        self.bad(self.post(f"nodes/{target['id']}/update/", {"node_key": "src"}))
        self.ok(self.post(f"nodes/{target['id']}/update/", {"name": "改名落地"}))
        edge = self.ok(self.post(f"pipelines/{pid}/edges/", {
            "source": "src", "target": "sink"}))["edge"]
        self.bad(self.post(f"pipelines/{pid}/edges/", {
            "source": "src", "target": "sink"}))
        self.bad(self.post(f"pipelines/{pid}/edges/", {
            "source": "src", "target": "src"}))
        self.ok(self.post(f"edges/{edge['id']}/delete/", {}))
        mapping = self.ok(self.post(f"pipelines/{pid}/mappings/", {
            "node_key": "src", "source_field": "order_id", "target_field": "id",
            "cast": "string"}))
        self.bad(self.post(f"pipelines/{pid}/mappings/", {
            "target_field": "x", "expression": "1 +"}))
        self.ok(self.post(f"mappings/{mapping['id']}/update/", {
            "target_field": "order_no"}))
        variable = self.ok(self.post(f"pipelines/{pid}/variables/", {
            "name": "batch_size", "value": 100, "kind": "number"}))
        self.bad(self.post(f"pipelines/{pid}/variables/", {
            "name": "1bad", "value": 1}))
        self.ok(self.post(f"variables/{variable['id']}/update/", {"value": 200}))
        self.ok(self.post(f"variables/{variable['id']}/delete/", {}))
        detail = self.ok(self.get(f"pipelines/{pid}/"))
        self.assertEqual(len(detail["nodes"]), 2)
        self.assertEqual(len(detail["mappings"]), 1)
        self.assertEqual(len(detail["variables"]), 0)
        self.ok(self.post(f"mappings/{mapping['id']}/delete/", {}))

    def test_publish_export_import_clone_and_rollback(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        report = self.ok(self.post(f"pipelines/{pid}/validate/", {}))
        self.assertTrue(report["valid"], report)
        topology = self.ok(self.get(f"pipelines/{pid}/topology/"))
        self.assertEqual(topology["order"][0], "src")
        published = self.ok(self.post(f"pipelines/{pid}/publish/", {"note": "首发"}))
        self.assertEqual(published["version"], 1)
        versions = self.ok(self.get(f"pipelines/{pid}/versions/"))
        self.assertEqual(versions["count"], 1)
        document = self.ok(self.get(f"pipelines/{pid}/export/"))
        self.assertEqual(len(document["nodes"]), 5)

        imported = self.ok(self.post("pipelines/import/", {
            "document": document, "code": "pipe_imported"}))
        self.assertEqual(imported["pipeline"]["code"], "pipe_imported")
        self.assertEqual(imported["node_count"], 5)
        cloned = self.ok(self.post(f"pipelines/{pid}/clone/", {"code": "pipe_clone"}))
        self.assertEqual(cloned["code"], "pipe_clone")

        # 删掉两个节点后回滚，结构应恢复
        nodes = self.ok(self.get(f"pipelines/{pid}/nodes/"))["items"]
        for node in nodes[:2]:
            self.ok(self.post(f"nodes/{node['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get(f"pipelines/{pid}/nodes/"))["count"], 3)
        version_id = versions["items"][0]["id"]
        rolled = self.ok(self.post(
            f"pipelines/{pid}/versions/{version_id}/rollback/", {}))
        self.assertEqual(rolled["version"], 1)
        self.assertEqual(self.ok(self.get(f"pipelines/{pid}/nodes/"))["count"], 5)

    def test_pause_archive_and_schedule_stop(self):
        pipeline = self.create_flow_pipeline(code="pipe_life")
        pid = pipeline["id"]
        schedule = self.ok(self.post("schedules/", {
            "pipeline_id": pid, "name": "每小时", "cron": "0 * * * *"}))
        self.assertIsNotNone(schedule["next_run_at"])
        self.ok(self.post(f"pipelines/{pid}/pause/", {}))
        self.bad(self.post(f"pipelines/{pid}/run/", {}))
        archived = self.ok(self.post(f"pipelines/{pid}/archive/", {}))
        self.assertEqual(archived["pipeline"]["status"], "archived")
        self.assertEqual(archived["stopped_schedules"], 1)
        self.bad(self.post(f"pipelines/{pid}/run/", {}))
        self.assertFalse(Schedule.objects.get(pk=schedule["id"]).enabled)


class PipelineRunTests(PipelineApiBase):
    """运行链路、质量检查、血缘、画像、统计与失败重跑。"""

    def run_pipeline(self, pipeline_id, **payload):
        return self.ok(self.post(f"pipelines/{pipeline_id}/run/", payload))

    def test_full_pipeline_run_and_outputs(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        result = self.run_pipeline(pid)
        run = result["run"]
        self.assertEqual(run["status"], "success", run.get("error"))
        self.assertGreater(run["input_rows"], 0)
        self.assertGreater(run["output_rows"], 0)
        statuses = {step["node_key"]: step["status"] for step in result["steps"]}
        self.assertEqual(statuses["src"], "success")
        self.assertEqual(statuses["sink"], "success")
        self.assertEqual(len(result["steps"]), 5)

        detail = self.ok(self.get(f"runs/{run['id']}/"))
        self.assertEqual(detail["status"], "success")
        self.assertGreaterEqual(detail["step_count"], 5)
        steps = self.ok(self.get(f"runs/{run['id']}/steps/"))
        self.assertEqual(steps["count"], 5)
        logs = self.ok(self.get(f"runs/{run['id']}/logs/", {"level": "info"}))
        self.assertGreaterEqual(logs["count"], 1)

        outputs = self.ok(self.get("outputs/", {"run_id": run["id"]}))
        self.assertGreater(outputs["count"], 0)
        row = outputs["items"][0]["data"]
        self.assertIn("status", row)
        self.assertIn("cnt", row)

    def test_join_pipeline_left_join(self):
        pipeline = self.create_pipeline(code="pipe_join", name="关联管道")
        pid = pipeline["id"]
        nodes = [
            {"node_key": "src", "name": "源", "node_type": "source", "order": 0,
             "config": {"connector_kind": "generator", "dataset": "orders",
                        "count": 20, "seed": 11}},
            {"node_key": "flt", "name": "分流", "node_type": "filter", "order": 1,
             "config": {"condition": "amount >= 250"}},
            {"node_key": "join", "name": "左关联", "node_type": "join", "order": 2,
             "config": {"how": "left", "left_on": "order_id",
                        "right_on": "order_id"}},
            {"node_key": "sink", "name": "落地", "node_type": "sink", "order": 3,
             "config": {"dataset": "joined_orders"}},
        ]
        edges = [
            {"source": "src", "source_port": "out", "target": "flt", "target_port": "in"},
            {"source": "flt", "source_port": "pass", "target": "join", "target_port": "left"},
            {"source": "flt", "source_port": "fail", "target": "join", "target_port": "right"},
            {"source": "join", "source_port": "out", "target": "sink", "target_port": "in"},
        ]
        self.ok(self.post(f"pipelines/{pid}/nodes/bulk/", {"items": nodes,
                                                          "replace": True}))
        self.ok(self.post(f"pipelines/{pid}/edges/bulk/", {"items": edges,
                                                          "replace": True}))
        result = self.run_pipeline(pid)
        run = result["run"]
        self.assertEqual(run["status"], "success", run.get("error"))
        self.assertGreater(run["output_rows"], 0)
        self.assertLessEqual(run["output_rows"], run["input_rows"])
        outputs = self.ok(self.get("outputs/", {"run_id": run["id"]}))
        self.assertIn("order_id", outputs["items"][0]["data"])

    def test_incremental_watermark_advances(self):
        pipeline = self.create_flow_pipeline(code="pipe_watermark",
                                            watermark_field="amount")
        pid = pipeline["id"]
        first = self.run_pipeline(pid)["run"]
        self.assertEqual(first["status"], "success")
        detail = self.ok(self.get(f"pipelines/{pid}/"))
        self.assertTrue(detail["pipeline"]["watermark_value"])
        second = self.run_pipeline(pid)["run"]
        self.assertEqual(second["watermark_before"],
                         detail["pipeline"]["watermark_value"])
        # 第二次运行所有行都不大于水位，应被增量过滤掉
        self.assertEqual(second["input_rows"], 0)
        self.assertEqual(second["output_rows"], 0)

    def test_injected_rows_and_run_guard(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        result = self.run_pipeline(pid, rows=[
            {"amount": 50, "status": "paid"},
            {"amount": 500, "status": "paid"},
        ])
        self.assertEqual(result["run"]["status"], "success")
        self.assertEqual(result["run"]["input_rows"], 2)
        # 注入超过 5000 行直接 400，且不产生新的运行记录
        before = PipelineRun.objects.filter(pipeline_id=pid).count()
        overflow = self.bad(self.post(f"pipelines/{pid}/run/", {
            "rows": [{"amount": 1, "status": "paid"}] * 5001}))
        self.assertIn("5000", overflow["error"])
        self.assertEqual(PipelineRun.objects.filter(pipeline_id=pid).count(), before)

    def test_quality_rules_results_and_rule_test(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        not_null = self.ok(self.post("quality/rules/", {
            "pipeline_id": pid, "name": "状态非空", "rule_type": "not_null",
            "field": "status", "severity": "error"}))
        self.ok(self.post("quality/rules/", {
            "pipeline_id": pid, "name": "行数区间", "rule_type": "row_count",
            "params": {"min": 1, "max": 100}}))
        self.bad(self.post("quality/rules/", {
            "pipeline_id": pid, "name": "坏正则", "rule_type": "regex",
            "field": "status", "params": {"pattern": "("}}))
        run = self.run_pipeline(pid)["run"]
        results = self.ok(self.get("quality/results/", {"run_id": run["id"]}))
        self.assertEqual(results["count"], 2)
        self.assertTrue(all(item["passed"] for item in results["items"]))
        tested = self.ok(self.post(f"quality/rules/{not_null['id']}/test/", {
            "rows": [{"status": ""}, {"status": "paid"}]}))
        self.assertFalse(tested["passed"])
        self.assertGreaterEqual(tested["failed_rows"], 1)
        listed = self.ok(self.get("quality/rules/", {"pipeline_id": pid}))
        self.assertEqual(listed["count"], 2)
        self.ok(self.post(f"quality/rules/{not_null['id']}/update/", {
            "severity": "warning"}))
        self.ok(self.post(f"quality/rules/{not_null['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get("quality/rules/", {"pipeline_id": pid}))["count"], 1)

    def test_lineage_impact_and_graph(self):
        pipeline = self.create_flow_pipeline(code="pipe_lineage")
        run = self.run_pipeline(pipeline["id"])["run"]
        upstream = self.ok(self.get("lineage/upstream/", {
            "entity_type": "dataset", "key": "orders_summary"}))
        keys = {item["key"] for item in upstream["nodes"]}
        self.assertIn("pipe_lineage", keys)
        self.assertIn("orders", keys)
        impact = self.ok(self.get("lineage/impact/", {
            "entity_type": "dataset", "key": "orders"}))
        self.assertEqual(impact["affected_pipelines"], 1)
        self.assertGreaterEqual(impact["affected_datasets"], 1)
        graph = self.ok(self.get("lineage/graph/", {"pipeline_id": pipeline["id"]}))
        self.assertGreaterEqual(graph["node_count"], 3)
        self.assertGreaterEqual(graph["edge_count"], 2)
        detail = self.ok(self.get(f"runs/{run['id']}/"))
        self.assertEqual(detail["status"], "success")

    def test_profiles_generate_detail_compare(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        self.run_pipeline(pid)
        profile = self.ok(self.post("profiles/generate/", {
            "pipeline_id": pid, "sample_size": 50}))
        self.assertGreater(profile["column_count"], 0)
        self.assertGreater(profile["row_count"], 0)
        second = self.ok(self.post("profiles/generate/", {
            "pipeline_id": pid,
            "rows": [{"status": "paid", "cnt": 1, "total": 100.0},
                     {"status": "pending", "cnt": 2, "total": 300.0}]}))
        listed = self.ok(self.get("profiles/", {"pipeline_id": pid}))
        self.assertEqual(listed["count"], 2)
        detail = self.ok(self.get(f"profiles/{profile['id']}/"))
        self.assertTrue(detail["columns"])
        compared = self.ok(self.get("profiles/compare/", {
            "left": profile["id"], "right": second["id"]}))
        self.assertIn("columns", compared)
        self.assertIsInstance(compared["row_delta"], int)

    def test_stats_endpoints(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        self.run_pipeline(pid)
        self.run_pipeline(pid)
        overview = self.ok(self.get("stats/overview/", {"days": 7}))
        self.assertGreaterEqual(overview["runs"]["total"], 2)
        self.assertEqual(overview["pipelines"]["total"], 1)
        trend = self.ok(self.get("stats/row-trend/", {"days": 7, "pipeline_id": pid}))
        self.assertTrue(trend["series"])
        rate = self.ok(self.get("stats/success-rate/", {"days": 7}))
        self.assertEqual(rate["success"], 2)
        latency = self.ok(self.get("stats/latency/", {"days": 7}))
        self.assertIn("p95", str(latency))
        failed = self.ok(self.get("stats/failed-nodes/", {"days": 7}))
        self.assertEqual(failed["total_failures"], 0)
        detail = self.ok(self.get(f"pipelines/{pid}/stats/", {"days": 7}))
        self.assertIn("runs", detail)

    def test_compare_cancel_and_retry_failed(self):
        pipeline = self.create_flow_pipeline()
        pid = pipeline["id"]
        first = self.run_pipeline(pid)["run"]
        second = self.run_pipeline(pid)["run"]
        compared = self.ok(self.get("runs/compare/", {
            "run_a": first["id"], "run_b": second["id"]}))
        self.assertEqual(len(compared["steps"]), 5)
        self.assertIn("output_delta", compared)

        queued = PipelineRun.objects.create(
            owner=self.user, pipeline_id=pid, trigger="manual", status="queued")
        cancelled = self.ok(self.post(f"runs/{queued.id}/cancel/", {}))
        self.assertEqual(cancelled["status"], "cancelled")
        self.bad(self.post(f"runs/{queued.id}/cancel/", {}))

        failed = PipelineRun.objects.create(
            owner=self.user, pipeline_id=pid, trigger="manual", status="failed",
            started_at=timezone.now(), finished_at=timezone.now(),
            error="模拟失败")
        source = Pipeline.objects.get(pk=pid).nodes.get(node_key="src")
        RunStep.objects.create(
            owner=self.user, run=failed, node=source, node_key="src",
            node_type="source", seq=1, attempt=1, status="failed",
            error="模拟节点失败")
        retried = self.ok(self.post(f"runs/{failed.id}/retry-failed/", {}))
        self.assertEqual(retried["run"]["status"], "success")
        self.assertEqual(retried["run"]["resumed_from"], "src")
        self.bad(self.post(f"runs/{second['id']}/retry-failed/", {}))


class ScheduleWebhookTests(PipelineApiBase):
    """调度 cron / 到期扫描与 Webhook 密钥校验。"""

    def test_schedule_crud_and_next_runs(self):
        pipeline = self.create_flow_pipeline(code="pipe_cron")
        created = self.ok(self.post("schedules/", {
            "pipeline_id": pipeline["id"], "name": "每五分钟",
            "cron": "*/5 * * * *", "timezone": "Asia/Shanghai"}))
        self.assertEqual(created["cron"], "*/5 * * * *")
        self.assertIsNotNone(created["next_run_at"])
        self.bad(self.post("schedules/", {
            "pipeline_id": pipeline["id"], "name": "坏 cron", "cron": "99 99 * * *"}))
        self.bad(self.post("schedules/", {
            "pipeline_id": pipeline["id"], "name": "每五分钟", "cron": "0 * * * *"}))
        preview = self.ok(self.get(f"schedules/{created['id']}/next-run/", {"count": 3}))
        self.assertEqual(len(preview["next_runs"]), 3)
        updated = self.ok(self.post(f"schedules/{created['id']}/update/", {
            "cron": "0 9 * * *", "enabled": True}))
        self.assertEqual(updated["cron"], "0 9 * * *")
        toggled = self.ok(self.post(f"schedules/{created['id']}/toggle/", {}))
        self.assertFalse(toggled["enabled"])
        self.assertIsNone(toggled["next_run_at"])
        listed = self.ok(self.get("schedules/", {"pipeline_id": pipeline["id"]}))
        self.assertEqual(listed["count"], 1)
        self.ok(self.post(f"schedules/{created['id']}/delete/", {}))

    def test_schedule_scan_runs_due_schedule(self):
        pipeline = self.create_flow_pipeline(code="pipe_scan")
        schedule = self.ok(self.post("schedules/", {
            "pipeline_id": pipeline["id"], "name": "扫描触发",
            "cron": "*/5 * * * *"}))
        Schedule.objects.filter(pk=schedule["id"]).update(
            next_run_at=timezone.now() - timedelta(minutes=1))
        scanned = self.ok(self.post("schedules/scan/", {"limit": 5}))
        self.assertEqual(scanned["count"], 1)
        self.assertEqual(scanned["items"][0]["status"], "success")
        refreshed = Schedule.objects.get(pk=schedule["id"])
        self.assertIsNotNone(refreshed.last_run_at)
        self.assertGreater(refreshed.next_run_at, timezone.now())

    def test_webhook_secret_lifecycle(self):
        pipeline = self.create_flow_pipeline(code="pipe_hook")
        created = self.ok(self.post("webhooks/", {
            "pipeline_id": pipeline["id"], "name": "外部触发",
            "secret": "hook-secret-1"}))
        self.assertEqual(created["secret"], "hook-secret-1")
        self.assertTrue(created["secret_hint"].startswith("***"))
        listed = self.ok(self.get("webhooks/", {"pipeline_id": pipeline["id"]}))
        self.assertNotIn("secret", listed["items"][0])
        self.bad(self.post(f"webhooks/{created['id']}/trigger/", {
            "secret": "wrong-secret"}))
        triggered = self.ok(self.post(f"webhooks/{created['id']}/trigger/", {
            "secret": "hook-secret-1"}))
        self.assertEqual(triggered["run"]["status"], "success")
        self.assertEqual(triggered["webhook"]["trigger_count"], 1)
        rotated = self.ok(self.post(f"webhooks/{created['id']}/rotate/", {
            "secret": "hook-secret-2"}))
        self.assertEqual(rotated["secret"], "hook-secret-2")
        self.bad(self.post(f"webhooks/{created['id']}/trigger/", {
            "secret": "hook-secret-1"}))
        self.ok(self.post(f"webhooks/{created['id']}/trigger/", {
            "secret": "hook-secret-2"}))
        self.assertFalse(self.ok(self.post(f"webhooks/{created['id']}/toggle/", {}))["enabled"])
        self.bad(self.post(f"webhooks/{created['id']}/trigger/", {
            "secret": "hook-secret-2"}))
        self.ok(self.post(f"webhooks/{created['id']}/delete/", {}))
        self.assertEqual(WebhookTrigger.objects.count(), 0)

    def test_webhook_requires_owner(self):
        pipeline = self.create_flow_pipeline(code="pipe_hook_perm")
        webhook = self.ok(self.post("webhooks/", {
            "pipeline_id": pipeline["id"], "name": "私有触发",
            "secret": "hook-secret-1"}))
        self.as_user(self.other)
        self.bad(self.post(f"webhooks/{webhook['id']}/trigger/", {
            "secret": "hook-secret-1"}))
        self.assertEqual(self.ok(self.get("webhooks/"))["count"], 0)


class QualityRuleModelTests(PipelineApiBase):
    """质量规则模型层的静态校验：坏参数在落库前就被拒绝。"""

    def test_rule_validation_blocks_bad_params(self):
        pipeline = self.create_pipeline(code="pipe_rule")
        rule = DataQualityRule(
            owner=self.user, pipeline_id=pipeline["id"], name="坏区间",
            rule_type="range", field="amount", params={})
        from pipeline.quality import validate_rule

        with self.assertRaisesMessage(ValueError, "min 或 max"):
            validate_rule(rule)
        rule.params = {"min": 0, "max": 100}
        validate_rule(rule)
        self.assertEqual(Connector.objects.count(), 0)
        self.assertEqual(Pipeline.objects.count(), 1)
