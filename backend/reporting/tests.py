# -*- coding: utf-8 -*-
"""reporting 应用测试：接口主链路 + 服务层单元测试。

为什么用 ``APIClient.force_authenticate``
-----------------------------------------
接口全部走 ``devtools.common.endpoint``（DRF api_view + 统一信封），
测试只关心「入参 → 数据 → 权限」，不重复造 JWT；force_authenticate
能精确模拟某一个用户，越权用例（bob 改 alice 的数据集）才有意义。
"""
import json
from datetime import timedelta

from django.conf import settings as django_settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from bizhub.models import BizRecord

from reporting import services as svc
from reporting.models import (
    Dashboard, DashboardWidget, Dataset, ReportDefinition,
    ReportFavorite, ReportRun, ReportSchedule, ReportSubscription,
)
from reporting.whitelist import clear_model_cache

# reporting 骨架不生成迁移文件；空的 migrations 包会被 Django 视为「已迁移」，
# 测试库建库时不会 syncdb，导致表不存在。测试进程里声明本应用无迁移，
# 让测试库走 syncdb 建表（只影响测试进程，不改 settings.py）。
django_settings.MIGRATION_MODULES = {
    **getattr(django_settings, "MIGRATION_MODULES", {}),
    "reporting": None,
}


class ReportingTestBase(TestCase):
    """公共夹具：两个用户 + 5 条业务记录 + 一次数据集/报表建链。"""

    @classmethod
    def setUpTestData(cls):
        clear_model_cache()
        cls.alice = User.objects.create_user(username="alice", password="pass-123456")
        cls.bob = User.objects.create_user(username="bob", password="pass-123456")
        now = timezone.now()
        cls.records = []
        for idx in range(5):
            record = BizRecord.objects.create(
                module="sales" if idx < 3 else "hr",
                title=f"记录 {idx}",
                status="done" if idx % 2 == 0 else "open",
                category="c1",
                priority="high" if idx == 0 else "normal",
                due_date=(now + timedelta(days=idx)).date(),
                data={"amount": idx * 10},
            )
            # created_at 是 auto_now_add，测试里补写成确定的月份，分桶断言才稳定
            BizRecord.objects.filter(pk=record.pk).update(
                created_at=now - timedelta(days=idx * 30),
            )
            cls.records.append(record)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.alice)

    # ------------------------------------------------------------------
    # 调用助手：统一断言 ok 信封，失败时把错误信息带出来便于定位
    # ------------------------------------------------------------------
    def call(self, method, path, data=None, expect_ok=True, status=None):
        func = getattr(self.client, method.lower())
        if method.upper() == "GET":
            resp = func(path, data or {}, format="json")
        else:
            resp = func(path, data or {}, format="json")
        if status is not None:
            self.assertEqual(resp.status_code, status, resp.content)
        if expect_ok:
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertTrue(resp.data.get("ok"), resp.data)
            return resp.data.get("data")
        self.assertFalse(resp.data.get("ok"), resp.data)
        return resp.data

    def get(self, path, data=None, **kw):
        return self.call("GET", path, data, **kw)

    def post(self, path, data=None, **kw):
        return self.call("POST", path, data, **kw)

    # ------------------------------------------------------------------
    # 业务夹具（按需创建，避免 setUp 里把所有用例都拖慢）
    # ------------------------------------------------------------------
    def make_dataset(self, **overrides):
        payload = {
            "name": "销售记录集",
            "primary_model": "bizhub.BizRecord",
            "filter": {
                "logic": "and",
                "filters": [
                    {"field": "is_deleted", "op": "eq", "value": False},
                ],
            },
            "default_limit": 100,
            "fields": [
                {"path": "module", "alias": "模块", "ftype": "string",
                 "aggregate": "none", "is_group": True, "order": 0},
                {"path": "id", "alias": "数量", "ftype": "integer",
                 "aggregate": "count", "order": 1},
            ],
        }
        payload.update(overrides)
        data = self.post("/api/reporting/datasets/create/", payload)
        return data["dataset"]

    def make_report(self, with_widget=True):
        data = self.post("/api/reporting/reports/create/", {
            "code": "sales-report", "name": "销售报表", "category": "销售",
        })
        report = data["report"]
        pages = self.get(f"/api/reporting/reports/{report['id']}/pages/")
        page_id = pages["items"][0]["id"]
        if with_widget:
            dataset = self.make_dataset()
            self.post(f"/api/reporting/pages/{page_id}/widgets/create/", {
                "type": "table", "title": "模块计数", "dataset_id": dataset["id"],
                "config": {},
            })
        return report


class CatalogAndUnitTests(ReportingTestBase):
    """目录、白名单、公式、cron、导出的服务层单元测试。"""

    def test_catalog_lists_endpoints_and_models(self):
        data = self.get("/api/reporting/")
        self.assertGreaterEqual(data["endpoint_count"], 50)
        self.assertGreaterEqual(data["model_count"], 10)
        self.assertIn("models", data)
        self.assertIn("operators", data["enums"])
        self.assertIn("prefix", data)

    def test_models_and_fields(self):
        data = self.get("/api/reporting/models/", {"q": "biz"})
        self.assertGreaterEqual(data["count"], 1)
        labels = [item["label"] for item in data["items"]]
        self.assertTrue(any("BizRecord" in label for label in labels))

        detail = self.get("/api/reporting/models/bizhub.BizRecord/")
        self.assertEqual(detail["label"], "bizhub.BizRecord")
        self.assertEqual(detail["model"], "BizRecord")
        self.assertTrue(detail["fields"])

        fields = self.get("/api/reporting/models/bizhub.BizRecord/fields/")
        self.assertEqual(fields["count"], len(fields["items"]))

    def test_model_whitelist_rejects_unknown(self):
        body = self.get("/api/reporting/models/os.system/", expect_ok=False)
        self.assertIn("error", body)

    def test_meta_and_registry_and_resolver(self):
        meta = self.get("/api/reporting/meta/")
        self.assertIn("widget_types", meta)
        self.assertIn("sub_frequencies", meta)
        registry = self.get("/api/reporting/registry/")
        self.assertEqual(registry["count"], 19)
        resolver = self.get("/api/reporting/resolver/")
        self.assertTrue(resolver["api_prefix_present"])
        self.assertGreaterEqual(resolver["endpoint_count"], 50)

    def test_formula_eval_and_validate(self):
        data = self.post("/api/reporting/formula/eval/", {
            "formula": "(a + b) * 2 / max(c, 1)",
            "variables": {"a": 3, "b": 5, "c": 4},
        })
        self.assertEqual(data["value"], 4.0)

        validated = self.post("/api/reporting/formula/validate/", {
            "formula": "value * 1.1", "sample_keys": ["value"],
        })
        self.assertTrue(validated["valid"])
        self.assertGreaterEqual(validated["token_count"], 3)

    def test_formula_rejects_code_execution(self):
        with self.assertRaises(ValueError):
            svc.evaluate_formula("__import__('os').system('echo hi')", {})
        with self.assertRaises(ValueError):
            svc.validate_formula("eval('1+1')")
        # 未知变量按 0 处理，但不允许调用非白名单函数
        with self.assertRaises(ValueError):
            svc.evaluate_formula("unknown_fn(1)", {})

    def test_cron_preview_and_next_runs(self):
        data = self.post("/api/reporting/cron/preview/", {
            "cron": "*/15 9-18 * * 1-5", "timezone": "Asia/Shanghai", "count": 3,
        })
        self.assertEqual(len(data["upcoming"]), 3)
        self.assertTrue(data["description"])
        runs = svc.next_runs("0 9 * * 1-5", "Asia/Shanghai", 3)
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(run > timezone.now() for run in runs))
        with self.assertRaises(ValueError):
            svc.parse_cron("61 * * * *")

    def test_csv_formula_injection_guard(self):
        self.assertEqual(svc.sanitize_cell("=cmd|'/c calc'!A1"), "'=cmd|'/c calc'!A1")
        self.assertEqual(svc.sanitize_cell("@SUM(A1)"), "'@SUM(A1)")
        content = svc.render_csv(
            [{"key": "a", "label": "列A"}],
            [{"a": "=1+1"}, {"a": "普通文本"}],
            bom=True,
        )
        self.assertTrue(content.startswith("\ufeff"))
        self.assertIn("'=1+1", content)

    def test_whitelist_path_rejections(self):
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        with self.assertRaises(ValueError):
            svc.resolve_path(user_model, "roles")  # 多对多不允许
        with self.assertRaises(ValueError):
            svc.resolve_path(user_model, "not_a_field")
        self.assertEqual(svc.model_info("bizhub.BizRecord")["model_name"], "BizRecord")

    def test_quality_check_service(self):
        result = svc.quality_check(
            "bizhub.BizRecord",
            distinct_keys=["module"],
            numeric_field="id",
            fields=["module", "title"],
        )
        self.assertEqual(result["row_count"], 5)
        self.assertEqual(len(result["fields"]), 2)
        self.assertIn("score", result)
        self.assertEqual(result["duplicates"]["keys"], ["module"])

    def test_params_key_and_metric_percentile(self):
        self.assertEqual(svc.params_key({"a": 1, "b": 2}),
                         svc.params_key({"b": 2, "a": 1}))
        self.assertEqual(svc.percentile([1, 2, 3, 4], 50), 2.5)


class SourceAndDatasetTests(ReportingTestBase):
    """数据源、数据集、字段、关联、参数、预览、取值。"""

    def test_source_crud_and_test(self):
        data = self.post("/api/reporting/sources/create/", {
            "name": "业务库", "kind": "orm",
            "config": {"model": "bizhub.BizRecord"},
        })
        source = data["source"]
        self.assertEqual(source["kind"], "orm")
        self.assertEqual(source["summary"]["check_count"], 1)

        listed = self.get("/api/reporting/sources/", {"q": "业务"})
        self.assertEqual(listed["count"], 1)
        self.assertEqual(set(listed.keys()), {"items", "count", "page", "page_size"})

        tested = self.post(f"/api/reporting/sources/{source['id']}/test/")
        self.assertTrue(tested["ok"])
        self.assertEqual(tested["summary"]["check_count"], 2)

        toggled = self.post(f"/api/reporting/sources/{source['id']}/toggle/",
                            {"status": "inactive"})
        self.assertEqual(toggled["status"], "inactive")

        detail = self.get(f"/api/reporting/sources/{source['id']}/")
        self.assertEqual(detail["dataset_count"], 0)

        updated = self.post(f"/api/reporting/sources/{source['id']}/update/",
                            {"description": "主业务库"})
        self.assertEqual(updated["description"], "主业务库")

        self.post(f"/api/reporting/sources/{source['id']}/delete/")

    def test_dataset_crud_and_preview(self):
        dataset = self.make_dataset()
        self.assertEqual(dataset["primary_model"], "bizhub.BizRecord")
        self.assertEqual(dataset["field_count"], 2)

        detail = self.get(f"/api/reporting/datasets/{dataset['id']}/")
        self.assertEqual(len(detail["fields"]), 2)

        preview = self.post(f"/api/reporting/datasets/{dataset['id']}/preview/",
                            {"limit": 10})
        self.assertIn("columns", preview)
        self.assertEqual(len(preview["rows"]), 2)  # sales / hr 两组
        self.assertIn("meta", preview)
        self.assertGreaterEqual(preview["meta"]["total"], 2)

        values = self.get(f"/api/reporting/datasets/{dataset['id']}/values/",
                          {"field": "module"})
        self.assertGreaterEqual(values["count"], 2)

        schema = self.get(f"/api/reporting/datasets/{dataset['id']}/schema/")
        self.assertTrue(schema["suggestions"])

        updated = self.post(f"/api/reporting/datasets/{dataset['id']}/update/",
                            {"name": "销售记录集 v2"})
        self.assertEqual(updated["dataset"]["name"], "销售记录集 v2")

        listed = self.get("/api/reporting/datasets/")
        self.assertEqual(listed["count"], 1)

        self.post(f"/api/reporting/datasets/{dataset['id']}/delete/",
                  {"force": True})

    def test_dataset_fields_save_and_reorder(self):
        dataset = self.make_dataset(fields=[])
        saved = self.post(f"/api/reporting/datasets/{dataset['id']}/fields/save/", {
            "fields": [
                {"path": "module", "alias": "模块", "aggregate": "none", "is_group": True},
                {"path": "status", "alias": "状态", "aggregate": "none", "is_group": True},
                {"path": "id", "alias": "数量", "aggregate": "count"},
            ],
        })
        self.assertEqual(len(saved["items"]), 3)
        ids = [f["id"] for f in saved["items"]]
        reordered = self.post(f"/api/reporting/datasets/{dataset['id']}/fields/reorder/",
                              {"ids": list(reversed(ids))})
        self.assertEqual(reordered["count"], 3)

        created = self.post(f"/api/reporting/datasets/{dataset['id']}/fields/create/", {
            "path": "title", "alias": "标题", "aggregate": "count_distinct",
        })
        self.assertEqual(created["aggregate"], "count_distinct")

        updated = self.post(f"/api/reporting/datasets/fields/{created['id']}/update/",
                            {"alias": "去重标题"})
        self.assertEqual(updated["alias"], "去重标题")

        self.post(f"/api/reporting/datasets/fields/{created['id']}/delete/")
        fields = self.get(f"/api/reporting/datasets/{dataset['id']}/fields/")
        self.assertEqual(fields["count"], 3)

    def test_dataset_invalid_model_and_field(self):
        body = self.post("/api/reporting/datasets/create/", {
            "name": "越权集", "primary_model": "os.system",
        }, expect_ok=False)
        self.assertIn("白名单", body["error"])

        body = self.post("/api/reporting/datasets/create/", {
            "name": "坏字段集", "primary_model": "bizhub.BizRecord",
            "fields": [{"path": "no_such_field"}],
        }, expect_ok=False)
        self.assertIn("no_such_field", body["error"])

    def test_dataset_params_and_quick_preview(self):
        dataset = self.make_dataset()
        created = self.post(f"/api/reporting/datasets/{dataset['id']}/params/create/", {
            "name": "module", "ptype": "string", "default": "sales", "required": False,
        })
        self.assertEqual(created["name"], "module")

        preview = self.post(f"/api/reporting/datasets/{dataset['id']}/preview/", {
            "params": {"module": "sales"},
            "filter": {"field": "module", "op": "eq", "value": {"$param": "module"}},
        })
        self.assertEqual(len(preview["rows"]), 1)

        quick = self.post("/api/reporting/datasets/quick-preview/", {
            "primary_model": "bizhub.BizRecord", "limit": 3,
        })
        self.assertLessEqual(len(quick["rows"]), 3)

        self.post(f"/api/reporting/datasets/params/{created['id']}/delete/")

    def test_dataset_join_requires_valid_relation(self):
        dataset = self.make_dataset()
        # 关系目标写错时必须拦下（owner 指向 accounts.User，不能硬连到别的模型）
        body = self.post(f"/api/reporting/datasets/{dataset['id']}/joins/create/", {
            "target_model": "bizhub.BizComment", "via": "owner",
        }, expect_ok=False)
        self.assertTrue(body["error"])

        join = self.post(f"/api/reporting/datasets/{dataset['id']}/joins/create/", {
            "target_model": "accounts.User", "via": "owner", "join_type": "left",
        })
        self.assertEqual(join["via"], "owner")
        self.post(f"/api/reporting/datasets/joins/{join['id']}/delete/")

    def test_dataset_write_permission(self):
        dataset = self.make_dataset()
        self.client.force_authenticate(user=self.bob)
        body = self.post(f"/api/reporting/datasets/{dataset['id']}/update/",
                         {"name": "改名"}, expect_ok=False)
        self.assertIn("无权", body["error"])
        body = self.get(f"/api/reporting/datasets/{dataset['id']}/", expect_ok=False)
        self.assertIn("不存在或无权访问", body["error"])


class ReportFlowTests(ReportingTestBase):
    """报表 → 页面 → 组件 → 执行/结果/导出/收藏/分享 的主链路。"""

    def test_report_crud_publish_and_run(self):
        report = self.make_report()
        detail = self.get(f"/api/reporting/reports/{report['id']}/")
        self.assertEqual(len(detail["pages"]), 1)
        self.assertEqual(len(detail["pages"][0]["widgets"]), 1)

        published = self.post(f"/api/reporting/reports/{report['id']}/publish/")
        self.assertEqual(published["status"], "published")

        run = self.post(f"/api/reporting/reports/{report['id']}/run/", {"params": {}})
        self.assertTrue(run["meta"]["run_id"])
        widget = run["pages"][0]["widgets"][0]
        self.assertIn("columns", widget["result"])
        self.assertIn("rows", widget["result"])
        self.assertIn("meta", widget["result"])
        self.assertGreaterEqual(len(widget["result"]["rows"]), 2)

        result = self.get(f"/api/reporting/reports/{report['id']}/result/")
        self.assertTrue(result["available"])

        snapshots = self.get(f"/api/reporting/reports/{report['id']}/snapshots/")
        self.assertGreaterEqual(snapshots["count"], 1)

        runs = self.get(f"/api/reporting/reports/{report['id']}/runs/")
        self.assertGreaterEqual(runs["count"], 1)

        preview = self.post(f"/api/reporting/reports/{report['id']}/preview/",
                            {"limit": 5})
        self.assertTrue(preview["meta"]["preview"])

        updated = self.post(f"/api/reporting/reports/{report['id']}/update/",
                            {"name": "销售报表 2026", "cache_ttl": 60})
        self.assertEqual(updated["report"]["name"], "销售报表 2026")

        cloned = self.post(f"/api/reporting/reports/{report['id']}/clone/",
                           {"code": "sales-report-copy"})
        self.assertEqual(cloned["report"]["code"], "sales-report-copy")

        archived = self.post(f"/api/reporting/reports/{report['id']}/archive/")
        self.assertEqual(archived["status"], "archived")

        listed = self.get("/api/reporting/reports/")
        self.assertEqual(listed["count"], 2)

        self.post(f"/api/reporting/reports/{cloned['report']['id']}/delete/")

    def test_report_publish_requires_widget(self):
        report = self.make_report(with_widget=False)
        body = self.post(f"/api/reporting/reports/{report['id']}/publish/",
                         expect_ok=False)
        self.assertIn("组件", body["error"])

    def test_report_export_and_export_jobs(self):
        report = self.make_report()
        self.post(f"/api/reporting/reports/{report['id']}/publish/")
        data = self.post(f"/api/reporting/reports/{report['id']}/export/",
                         {"fmt": "csv"})
        self.assertEqual(data["format"], "csv")
        self.assertTrue(data["filename"].endswith(".csv"))
        self.assertGreater(data["rows"], 0)
        self.assertTrue(data["job"]["id"])

        jobs = self.get("/api/reporting/export-jobs/")
        self.assertEqual(jobs["count"], 1)
        self.assertEqual(jobs["items"][0]["status"], "done")

        as_json = self.post(f"/api/reporting/reports/{report['id']}/export/",
                            {"fmt": "json"})
        self.assertEqual(as_json["format"], "json")
        json.loads(as_json["content"])

    def test_report_favorite(self):
        report = self.make_report(with_widget=False)
        data = self.post(f"/api/reporting/reports/{report['id']}/favorite/")
        self.assertTrue(data["favorited"])
        self.assertEqual(ReportFavorite.objects.filter(report_id=report["id"]).count(), 1)

        listing = self.get("/api/reporting/reports/favorites/")
        self.assertEqual(listing["count"], 1)

        data = self.post(f"/api/reporting/reports/{report['id']}/favorite/")
        self.assertFalse(data["favorited"])

        filtered = self.get("/api/reporting/reports/", {"favorite": True})
        self.assertEqual(filtered["count"], 0)

    def test_share_crud_and_public_read(self):
        report = self.make_report()
        self.post(f"/api/reporting/reports/{report['id']}/publish/")
        share = self.post(f"/api/reporting/reports/{report['id']}/share/",
                          {"days": 3, "note": "给销售看"})
        self.assertTrue(share["token"])
        self.assertTrue(share["readonly"])

        listing = self.get("/api/reporting/shares/", {"report_id": report["id"]})
        self.assertEqual(listing["count"], 1)

        public = self.get(f"/api/reporting/share/{share['token']}/")
        self.assertTrue(public["readonly"])
        self.assertEqual(public["share"]["report_id"], report["id"])
        self.assertIn("payload", public)

        updated = self.post(f"/api/reporting/shares/{share['id']}/update/",
                            {"note": "长期有效", "days": 0})
        self.assertEqual(updated["note"], "长期有效")

        disabled = self.post(f"/api/reporting/shares/{share['id']}/disable/")
        self.assertFalse(disabled["enabled"])
        body = self.get(f"/api/reporting/share/{share['token']}/", expect_ok=False)
        self.assertIn("停用", body["error"])

    def test_public_share_unknown_token(self):
        body = self.get("/api/reporting/share/not-a-real-token/", expect_ok=False)
        self.assertIn("不存在", body["error"])

    def test_pages_and_widgets(self):
        report = self.make_report(with_widget=False)
        page = self.post(f"/api/reporting/reports/{report['id']}/pages/create/", {
            "title": "明细", "layout": {"columns": 12},
        })
        other = self.post(f"/api/reporting/reports/{report['id']}/pages/create/", {
            "title": "趋势",
        })
        reordered = self.post(f"/api/reporting/reports/{report['id']}/pages/reorder/",
                              {"ids": [other["id"], page["id"]]})
        self.assertEqual(reordered["count"], 2)

        dataset = self.make_dataset()
        widget = self.post(f"/api/reporting/pages/{page['id']}/widgets/create/", {
            "type": "bar", "title": "模块分布", "dataset_id": dataset["id"],
            "config": {"x": "模块", "y": "数量"},
        })
        self.assertEqual(widget["type"], "bar")

        second = self.post(f"/api/reporting/pages/{page['id']}/widgets/create/", {
            "type": "kpi", "title": "总量", "dataset_id": dataset["id"],
            "config": {"formula": "数量"},
        })
        self.post(f"/api/reporting/pages/{page['id']}/widgets/reorder/",
                  {"ids": [second["id"], widget["id"]]})

        widget_run = self.post(f"/api/reporting/widgets/{widget['id']}/run/",
                               {"limit": 20})
        self.assertIn("rows", widget_run)

        updated = self.post(f"/api/reporting/widgets/{widget['id']}/update/",
                            {"title": "模块分布图", "w": 8})
        self.assertEqual(updated["position"]["w"], 8)

        listed = self.get(f"/api/reporting/pages/{page['id']}/widgets/")
        self.assertEqual(listed["count"], 2)

        self.post(f"/api/reporting/pages/{page['id']}/delete/")
        pages = self.get(f"/api/reporting/reports/{report['id']}/pages/")
        self.assertEqual(pages["count"], 2)  # 首页 + 趋势页

    def test_widget_filters(self):
        report = self.make_report()
        page_id = self.get(f"/api/reporting/reports/{report['id']}/pages/")["items"][0]["id"]
        widget = self.get(f"/api/reporting/pages/{page_id}/widgets/")["items"][0]

        created = self.post(f"/api/reporting/widgets/{widget['id']}/filters/create/", {
            "field": "status", "operator": "eq", "default_value": "done",
            "label": "状态",
        })
        self.assertEqual(created["field"], "status")

        updated = self.post(f"/api/reporting/filters/{created['id']}/update/", {
            "operator": "neq",
        })
        self.assertEqual(updated["operator"], "neq")

        listed = self.get(f"/api/reporting/widgets/{widget['id']}/filters/")
        self.assertEqual(listed["count"], 1)

        self.post(f"/api/reporting/filters/{created['id']}/delete/")

    def test_annotations(self):
        report = self.make_report()
        page_id = self.get(f"/api/reporting/reports/{report['id']}/pages/")["items"][0]["id"]
        widget = self.get(f"/api/reporting/pages/{page_id}/widgets/")["items"][0]

        created = self.post("/api/reporting/annotations/create/", {
            "report_id": report["id"], "widget_id": widget["id"],
            "body": "这个月销售额异常", "data_point": {"key": "数量", "index": 0},
        })
        self.assertEqual(created["report_id"], report["id"])

        listed = self.get("/api/reporting/annotations/", {"report_id": report["id"]})
        self.assertEqual(listed["count"], 1)

        updated = self.post(f"/api/reporting/annotations/{created['id']}/update/",
                            {"resolved": True})
        self.assertTrue(updated["resolved"])

        self.post(f"/api/reporting/annotations/{created['id']}/delete/")


class DashboardTests(ReportingTestBase):
    """仪表盘 CRUD、组件拼装、详情与导出。"""

    def test_dashboard_flow(self):
        report = self.make_report()
        self.post(f"/api/reporting/reports/{report['id']}/publish/")
        page_id = self.get(f"/api/reporting/reports/{report['id']}/pages/")["items"][0]["id"]
        widget = self.get(f"/api/reporting/pages/{page_id}/widgets/")["items"][0]

        cands = self.get("/api/reporting/dashboards/available-widgets/")
        self.assertGreaterEqual(cands["count"], 1)

        created = self.post("/api/reporting/dashboards/create/", {
            "name": "销售看板", "default_filters": {"region": "all"},
        })
        dashboard = created["dashboard"]

        link = self.post(f"/api/reporting/dashboards/{dashboard['id']}/widgets/add/", {
            "widget_id": widget["id"], "override": {"title": "本月"},
        })
        self.assertEqual(link["widget_id"], widget["id"])

        detail = self.get(f"/api/reporting/dashboards/{dashboard['id']}/")
        self.assertEqual(detail["meta"]["widget_count"], 1)
        self.assertEqual(detail["widgets"][0]["title"], "本月")
        self.assertIn("rows", detail["widgets"][0]["result"])

        moved = self.post(f"/api/reporting/dashboard-widgets/{link['id']}/update/",
                          {"x": 2, "w": 10, "override": {"title": "本月销售额"}})
        self.assertEqual(moved["position"]["w"], 10)

        self.post(f"/api/reporting/dashboards/{dashboard['id']}/widgets/reorder/",
                  {"ids": [link["id"]]})

        exported = self.post(f"/api/reporting/dashboards/{dashboard['id']}/export/",
                             {"fmt": "csv"})
        self.assertGreaterEqual(exported["widget_count"], 1)
        self.assertTrue(exported["filename"].endswith(".csv"))

        updated = self.post(f"/api/reporting/dashboards/{dashboard['id']}/update/",
                            {"name": "销售看板 2.0", "status": "archived"})
        self.assertEqual(updated["dashboard"]["status"], "archived")

        listed = self.get("/api/reporting/dashboards/", {"status": "archived"})
        self.assertEqual(listed["count"], 1)

        self.post(f"/api/reporting/dashboard-widgets/{link['id']}/remove/")
        self.assertEqual(DashboardWidget.objects.count(), 0)

        self.post(f"/api/reporting/dashboards/{dashboard['id']}/delete/")
        self.assertEqual(Dashboard.objects.count(), 0)


class OpsTests(ReportingTestBase):
    """计划任务、订阅、指标、质量、流水、导出任务。"""

    def make_published_report(self):
        report = self.make_report()
        self.post(f"/api/reporting/reports/{report['id']}/publish/")
        return report

    def test_schedule_flow(self):
        report = self.make_published_report()
        created = self.post("/api/reporting/schedules/create/", {
            "report_id": report["id"], "name": "每日九点",
            "cron_expr": "0 9 * * 1-5", "timezone": "Asia/Shanghai",
            "enabled": True, "recipients": ["ops@example.com"],
        })
        self.assertTrue(created["enabled"])
        self.assertTrue(created["next_run_at"])
        self.assertTrue(created["upcoming"])

        listed = self.get("/api/reporting/schedules/", {"report_id": report["id"]})
        self.assertEqual(listed["count"], 1)

        detail = self.get(f"/api/reporting/schedules/{created['id']}/")
        self.assertTrue(detail["description"])

        upcoming = self.post(f"/api/reporting/schedules/{created['id']}/next/",
                             {"count": 3})
        self.assertEqual(len(upcoming["upcoming"]), 3)

        toggled = self.post(f"/api/reporting/schedules/{created['id']}/toggle/")
        self.assertFalse(toggled["enabled"])
        self.assertIsNone(toggled["next_run_at"])

        toggled = self.post(f"/api/reporting/schedules/{created['id']}/toggle/")
        self.assertTrue(toggled["enabled"])

        ran = self.post(f"/api/reporting/schedules/{created['id']}/run-now/")
        self.assertEqual(ran["status"], "success")
        self.assertTrue(ran["run_id"])

        updated = self.post(f"/api/reporting/schedules/{created['id']}/update/", {
            "cron_expr": "30 8 * * *",
        })
        self.assertEqual(updated["cron_expr"], "30 8 * * *")

        due = self.get("/api/reporting/schedules/due/")
        self.assertEqual(due["count"], 0)

        body = self.post("/api/reporting/schedules/create/", {
            "report_id": report["id"], "cron_expr": "99 * * * *",
        }, expect_ok=False)
        self.assertIn("cron", body["error"].lower())

        self.post(f"/api/reporting/schedules/{created['id']}/delete/")
        self.assertEqual(ReportSchedule.objects.count(), 0)

    def test_subscriptions(self):
        report = self.make_published_report()
        created = self.post("/api/reporting/subscriptions/create/", {
            "report_id": report["id"], "channel": "email", "frequency": "weekly",
        })
        self.assertEqual(created["user_id"], self.alice.id)

        body = self.post("/api/reporting/subscriptions/create/", {
            "report_id": report["id"],
        }, expect_ok=False)
        self.assertIn("已订阅", body["error"])

        listed = self.get("/api/reporting/subscriptions/")
        self.assertEqual(listed["count"], 1)

        updated = self.post(f"/api/reporting/subscriptions/{created['id']}/update/", {
            "frequency": "daily", "enabled": False,
        })
        self.assertFalse(updated["enabled"])

        # 订阅自己可以取消；bob 既不是创建人也不是订阅人
        self.client.force_authenticate(user=self.bob)
        protected = self.post(f"/api/reporting/subscriptions/{created['id']}/cancel/",
                              expect_ok=False)
        self.assertTrue(protected["error"])

        self.client.force_authenticate(user=self.alice)
        canceled = self.post(f"/api/reporting/subscriptions/{created['id']}/cancel/")
        self.assertTrue(canceled["canceled"])
        self.assertEqual(ReportSubscription.objects.count(), 0)

    def test_subscribe_others_requires_ownership(self):
        report = self.make_published_report()
        self.client.force_authenticate(user=self.bob)
        body = self.post("/api/reporting/subscriptions/create/", {
            "report_id": report["id"], "user_id": self.alice.id,
        }, expect_ok=False)
        self.assertTrue(body["error"])

    def test_metrics_and_runs(self):
        report = self.make_published_report()
        run = self.post(f"/api/reporting/reports/{report['id']}/run/", {"params": {}})
        run_id = run["meta"]["run_id"]

        overview = self.get("/api/reporting/metrics/overview/", {"days": 7})
        self.assertGreaterEqual(overview["total"], 1)
        self.assertIn("duration_p95_ms", overview)
        self.assertIn("top_reports", overview)

        per_report = self.get(f"/api/reporting/metrics/reports/{report['id']}/")
        self.assertEqual(per_report["report_id"], report["id"])

        runs = self.get("/api/reporting/runs/", {"report_id": report["id"]})
        self.assertGreaterEqual(runs["count"], 1)
        self.assertEqual(set(runs.keys()), {"items", "count", "page", "page_size"})

        detail = self.get(f"/api/reporting/runs/{run_id}/")
        self.assertEqual(detail["id"], run_id)
        self.assertIn("result", detail)

    def test_quality_endpoint_with_dataset_and_model(self):
        dataset = self.make_dataset()
        by_dataset = self.post("/api/reporting/quality/check/", {
            "dataset_id": dataset["id"], "fields": ["module", "title"],
            "distinct_keys": ["module"], "numeric_field": "id",
        })
        self.assertEqual(by_dataset["row_count"], 5)
        self.assertIn("score", by_dataset)

        by_model = self.post("/api/reporting/quality/check/", {
            "model": "bizhub.BizRecord", "filter": {
                "field": "module", "op": "eq", "value": "sales",
            },
        })
        self.assertEqual(by_model["row_count"], 3)

        body = self.post("/api/reporting/quality/check/", {}, expect_ok=False)
        self.assertTrue(body["error"])


class SnapshotAndExecutorTests(ReportingTestBase):
    """缓存 TTL、组件执行失败结构化、KPI / 透视后处理。"""

    def test_snapshot_cache_hit(self):
        report = self.make_report()
        self.post(f"/api/reporting/reports/{report['id']}/publish/")
        first = self.post(f"/api/reporting/reports/{report['id']}/run/", {"params": {}})
        self.assertFalse(first["meta"]["cached"])
        second = self.post(f"/api/reporting/reports/{report['id']}/run/", {"params": {}})
        self.assertTrue(second["meta"]["cached"])
        cached_runs = ReportRun.objects.filter(report_id=report["id"], trigger="cache")
        self.assertEqual(cached_runs.count(), 1)

        bypass = self.post(f"/api/reporting/reports/{report['id']}/run/",
                           {"params": {}, "bypass_cache": True})
        self.assertFalse(bypass["meta"]["cached"])

    def test_kpi_and_pivot_widget_results(self):
        # KPI 使用不分组的数据集，聚合结果只有一行，公式变量才能取到总数
        kpi_dataset = self.make_dataset(fields=[
            {"path": "id", "alias": "数量", "ftype": "integer",
             "aggregate": "count", "order": 0},
        ])
        dataset = self.make_dataset()
        report = self.make_report(with_widget=False)
        page_id = self.get(f"/api/reporting/reports/{report['id']}/pages/")["items"][0]["id"]
        kpi = self.post(f"/api/reporting/pages/{page_id}/widgets/create/", {
            "type": "kpi", "title": "总数量", "dataset_id": kpi_dataset["id"],
            "config": {"formula": "数量", "unit": "条"},
        })
        result = self.post(f"/api/reporting/widgets/{kpi['id']}/run/")
        self.assertIn("rows", result)
        self.assertEqual(result["rows"][0]["value"], 5.0)
        self.assertEqual(result["widget_id"], kpi["id"])

        pivot = self.post(f"/api/reporting/pages/{page_id}/widgets/create/", {
            "type": "pivot", "title": "透视", "dataset_id": dataset["id"],
        })
        pivot_result = self.post(f"/api/reporting/widgets/{pivot['id']}/run/")
        self.assertIn("rows", pivot_result)

    def test_widget_error_is_structured(self):
        dataset = self.make_dataset(fields=[
            {"path": "module", "alias": "模块", "aggregate": "none", "is_group": True},
        ])
        report = self.make_report(with_widget=False)
        page_id = self.get(f"/api/reporting/reports/{report['id']}/pages/")["items"][0]["id"]
        widget = self.post(f"/api/reporting/pages/{page_id}/widgets/create/", {
            "type": "table", "title": "会失败", "dataset_id": dataset["id"],
            "config": {},
        })
        # 删除数据集后执行：组件返回结构化错误而不是 500
        self.post(f"/api/reporting/datasets/{dataset['id']}/delete/",
                  {"force": True})
        result = self.post(f"/api/reporting/widgets/{widget['id']}/run/")
        self.assertTrue(result["meta"].get("error"))

    def test_dashboard_source_snapshot_reuse(self):
        report = self.make_report()
        self.post(f"/api/reporting/reports/{report['id']}/publish/")
        self.post(f"/api/reporting/reports/{report['id']}/run/", {"params": {}})
        page_id = self.get(f"/api/reporting/reports/{report['id']}/pages/")["items"][0]["id"]
        widget = self.get(f"/api/reporting/pages/{page_id}/widgets/")["items"][0]
        dashboard = self.post("/api/reporting/dashboards/create/",
                              {"name": "快照看板"})["dashboard"]
        self.post(f"/api/reporting/dashboards/{dashboard['id']}/widgets/add/",
                  {"widget_id": widget["id"]})
        detail = self.get(f"/api/reporting/dashboards/{dashboard['id']}/")
        self.assertTrue(detail["widgets"][0]["result"]["meta"].get("from_snapshot"))
        refreshed = self.get(f"/api/reporting/dashboards/{dashboard['id']}/",
                             {"refresh": True})
        self.assertFalse(refreshed["widgets"][0]["result"]["meta"].get("from_snapshot"))


class PermissionTests(ReportingTestBase):
    """行级权限：同部门可读、非 owner 不可写。"""

    def test_foreign_report_not_visible(self):
        report = self.make_report(with_widget=False)
        self.client.force_authenticate(user=self.bob)
        body = self.get(f"/api/reporting/reports/{report['id']}/", expect_ok=False)
        self.assertIn("不存在或无权访问", body["error"])

        body = self.post(f"/api/reporting/reports/{report['id']}/run/",
                         expect_ok=False)
        self.assertIn("不存在或无权访问", body["error"])

    def test_dashboard_widget_requires_visible_report(self):
        self.make_report(with_widget=False)
        self.client.force_authenticate(user=self.bob)
        dashboard = self.post("/api/reporting/dashboards/create/",
                              {"name": "bob 的看板"})["dashboard"]
        alice_dataset = Dataset.objects.create(
            name="alice 数据集", primary_model="bizhub.BizRecord", owner=self.alice,
        )
        self.client.force_authenticate(user=self.alice)
        report = ReportDefinition.objects.filter(owner=self.alice).first()
        page = report.rep_pages.first()
        widget = page.rep_widgets.create(
            rtype="table", title="隐藏组件", dataset=alice_dataset,
        )
        self.client.force_authenticate(user=self.bob)
        body = self.post(f"/api/reporting/dashboards/{dashboard['id']}/widgets/add/",
                         {"widget_id": widget.pk}, expect_ok=False)
        self.assertIn("无权", body["error"])
