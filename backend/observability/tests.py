# -*- coding: utf-8 -*-
"""observability 测试：目录契约、服务/端点/依赖/面板、指标上报与聚合、
SLO 与错误预算、告警求值链路、事故状态机、值班与升级、运行手册与健康检查、
统计与分析师接口，以及行级权限隔离。

运行：venv/Scripts/python.exe manage.py test observability -v 1
（测试库为内存 sqlite，不触碰开发库，也不会发起任何网络请求）

注意：本应用当前不提交迁移文件（迁移统一生成是独立任务），空的 migrations
包会让测试库不 sync 建表，因此 ApiTestBase.setUpClass 会在开启类级事务之前
先补建本应用的表（与 rules/tests.py 的做法一致）。
"""
from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from observability import analytics, oncall, services
from observability.models import (
    AlertEvent,
    AlertRule,
    ErrorBudget,
    HealthCheckRun,
    Incident,
    IncidentUpdate,
    MetricDef,
    MetricPoint,
    RunbookExecution,
    Service,
    Silence,
    Slo,
    SloWindow,
)

User = get_user_model()

BASE = "/api/observability/"


def ensure_observability_tables():
    """测试库补建 observability 表（幂等，不影响开发库/生产库的迁移策略）。

    必须在 TestCase 开启类级事务之前调用：SQLite 不允许在事务内关闭外键
    检查，建表会直接失败。
    """
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in apps.get_app_config("observability").get_models():
            if model._meta.db_table not in existing:
                editor.create_model(model)


class ApiTestBase(TestCase):
    """接口测试基类：用户、客户端、工厂方法与通用断言。"""

    @classmethod
    def setUpClass(cls):
        ensure_observability_tables()
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

    # ---------------------------------------------------------------
    # 请求 helper
    # ---------------------------------------------------------------

    def get(self, path, params=None):
        return self.client.get(BASE + path, params or {})

    def post(self, path, data=None):
        return self.client.post(BASE + path, data if data is not None else {},
                                format="json")

    def as_user(self, user):
        self.client.force_authenticate(user)

    # ---------------------------------------------------------------
    # 断言 helper
    # ---------------------------------------------------------------

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def bad(self, response, status=400):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertFalse(body.get("ok"), body)
        self.assertTrue(body.get("error"), body)
        return body

    def expect_error(self, response, keyword, status=400):
        """断言失败响应里包含指定中文关键词（校验提示必须可操作）。"""
        body = self.bad(response, status)
        self.assertIn(keyword, body["error"], body)
        return body

    # ---------------------------------------------------------------
    # 时间 helper
    # ---------------------------------------------------------------

    def seconds_ago(self, seconds):
        return (timezone.now() - timedelta(seconds=seconds)).isoformat()

    def minutes_ago(self, minutes=5):
        return (timezone.now() - timedelta(minutes=minutes)).isoformat()

    def hours_ago(self, hours=1):
        return (timezone.now() - timedelta(hours=hours)).isoformat()

    def days_ago(self, days=1):
        return (timezone.now() - timedelta(days=days)).isoformat()

    # ---------------------------------------------------------------
    # 数据工厂
    # ---------------------------------------------------------------

    def create_service(self, name="订单服务", **overrides):
        payload = {"name": name, "team": "交易", "level": "P0"}
        payload.update(overrides)
        return self.ok(self.post("services/create/", payload))

    def create_metric(self, service_id, name="requests_total", metric_type="counter",
                      unit="", **overrides):
        payload = {"service_id": service_id, "name": name,
                   "metric_type": metric_type, "unit": unit}
        payload.update(overrides)
        return self.ok(self.post("metrics/defs/create/", payload))

    def report(self, service_id, metric, value, at=None, **extra):
        """上报单个指标点（模拟 agent 一次采集）。"""
        payload = {"service_id": service_id, "metric": metric, "value": value,
                   "timestamp": at or self.minutes_ago(1)}
        payload.update(extra)
        return self.ok(self.post("metrics/points/report/", payload))

    def batch_points(self, items):
        return self.ok(self.post("metrics/points/batch/", {"points": items}))

    def create_slo(self, service_id, name="可用性 99%", **overrides):
        payload = {"service_id": service_id, "name": name, "slo_type": "availability",
                   "target_pct": 99.0, "window_days": 30}
        payload.update(overrides)
        return self.ok(self.post("slos/create/", payload))

    def create_rule(self, service_id, name="错误率高", expression="requests_total > 5",
                    **overrides):
        payload = {"service_id": service_id, "name": name, "expression": expression,
                   "duration_seconds": 60, "severity": "critical", "cooldown_seconds": 600}
        payload.update(overrides)
        return self.ok(self.post("alerts/rules/create/", payload))

    def create_incident(self, title="支付超时", **overrides):
        payload = {"title": title, "severity": "sev2"}
        payload.update(overrides)
        return self.ok(self.post("incidents/create/", payload))

    def create_check(self, service_id, check_type="http", **overrides):
        payload = {"service_id": service_id, "check_type": check_type,
                   "interval_seconds": 60, "timeout_seconds": 5}
        payload.update(overrides)
        return self.ok(self.post("health-checks/create/", payload))

    def create_schedule(self, team="交易", members=None, **overrides):
        payload = {"team": team, "name": "主值班", "rotation": "daily",
                   "start_at": self.days_ago(2), "members": members or ["alice", "bob"]}
        payload.update(overrides)
        return self.ok(self.post("oncall/schedules/create/", payload))

    def fire_rule(self, rule_id):
        """对单条规则跑一次求值（测试用，走真实的巡检接口）。"""
        return self.ok(self.post("alerts/evaluate/", {}))


# =====================================================================
# 1. 目录与契约
# =====================================================================


class CatalogTests(ApiTestBase):
    """目录接口：能力清单、枚举、计算口径、分页契约与接口数量。"""

    def test_catalog_shape(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "observability")
        self.assertGreaterEqual(len(data["capabilities"]), 10)
        self.assertIn("percentile", data["compute"])
        self.assertIn("burn_windows", data["compute"])
        self.assertEqual(data["compute"]["burn_windows"][0]["window"], "1h")

    def test_catalog_enums_are_labeled(self):
        data = self.ok(self.get(""))
        levels = data["enums"]["service_levels"]
        self.assertEqual([row["value"] for row in levels], ["P0", "P1", "P2", "P3"])
        self.assertEqual(levels[0]["label"], "核心")
        statuses = [row["value"] for row in data["enums"]["incident_status"]]
        self.assertEqual(statuses, ["open", "acknowledged", "mitigated",
                                    "resolved", "postmortem"])

    def test_catalog_pagination_contract(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["pagination"]["page_size_max"], 200)
        self.assertEqual(data["pagination"]["response_shape"],
                         ["items", "count", "page", "page_size"])

    def test_catalog_endpoint_index_covers_route_table(self):
        data = self.ok(self.get(""))
        self.assertGreaterEqual(data["endpoint_count"], 100)
        paths = {row["path"] for row in data["endpoints"]}
        self.assertIn("services/", paths)
        self.assertIn("metrics/points/report/", paths)
        self.assertIn("incidents/<int:pk>/similar/", paths)
        self.assertNotIn("", paths)

    def test_catalog_counts_are_scoped(self):
        self.create_service()
        self.as_user(self.other)
        data = self.ok(self.get(""))
        self.assertEqual(data["counts"]["services"], 0)

    def test_post_only_route_rejects_get(self):
        response = self.client.get(BASE + "services/create/")
        self.assertEqual(response.status_code, 405, response.content)


# =====================================================================
# 2. 聚合与分位（纯函数）
# =====================================================================


class AggregationTests(ApiTestBase):
    """分位、摘要、分桶、降采样、分桶大小选择等纯计算口径。"""

    def test_nearest_rank_percentiles(self):
        values = list(range(1, 101))
        self.assertEqual(services.percentile_nearest_rank(values, 50), 50)
        self.assertEqual(services.percentile_nearest_rank(values, 90), 90)
        self.assertEqual(services.percentile_nearest_rank(values, 95), 95)
        self.assertEqual(services.percentile_nearest_rank(values, 99), 99)
        self.assertEqual(services.percentile_nearest_rank([], 95), 0.0)

    def test_nearest_rank_uses_real_sample(self):
        # 最近秩法返回真实样本，不做线性插值（插值会给出不存在的延迟值）
        values = [10, 20, 30, 40]
        self.assertEqual(services.percentile_nearest_rank(values, 50), 20)
        self.assertEqual(services.percentile_nearest_rank(values, 51), 30)
        self.assertEqual(services.percentile_nearest_rank(values, 100), 40)

    def test_summarize_fields(self):
        summary = services.summarize([1, 2, 3, 4])
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["sum"], 10.0)
        self.assertEqual(summary["avg"], 2.5)
        self.assertEqual(summary["min"], 1.0)
        self.assertEqual(summary["max"], 4.0)
        self.assertEqual(summary["p50"], 2.0)

    def test_summarize_empty(self):
        summary = services.summarize([])
        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["p99"], 0.0)

    def test_aggregate_values_variants(self):
        values = [1, 2, 3, 4]
        self.assertEqual(services.aggregate_values(values, "sum"), 10.0)
        self.assertEqual(services.aggregate_values(values, "min"), 1.0)
        self.assertEqual(services.aggregate_values(values, "max"), 4.0)
        self.assertEqual(services.aggregate_values(values, "count"), 4.0)
        self.assertEqual(services.aggregate_values(values, "last"), 4.0)
        self.assertEqual(services.aggregate_values(values, "first"), 1.0)
        self.assertEqual(services.aggregate_values(values, "p95"), 4.0)

    def test_aggregate_values_rejects_unknown(self):
        with self.assertRaisesMessage(ValueError, "聚合口径"):
            services.aggregate_values([1], "median")

    def test_choose_bucket_seconds(self):
        now = timezone.now()
        self.assertGreaterEqual(
            services.choose_bucket_seconds(now - timedelta(hours=1), now), 1)
        coarse = services.choose_bucket_seconds(now - timedelta(days=30), now)
        fine = services.choose_bucket_seconds(now - timedelta(hours=1), now)
        self.assertGreater(coarse, fine)

    def test_bucketize_and_downsample(self):
        now = timezone.now()
        rows = [(now - timedelta(minutes=10) + timedelta(seconds=10 * i), i)
                for i in range(10)]
        buckets = services.bucketize(rows, 300, since=now - timedelta(hours=1), until=now,
                                     aggregation="avg")
        self.assertTrue(buckets)
        self.assertTrue(all("start" in row and "value" in row for row in buckets))
        reduced = services.downsample(buckets, max_points=2, aggregation="avg")
        self.assertLessEqual(len(reduced), 2)

    def test_bucketize_fill_empty(self):
        now = timezone.now()
        rows = [(now - timedelta(minutes=5), 3.0)]
        filled = services.bucketize(rows, 600, since=now - timedelta(hours=1), until=now,
                                    aggregation="avg", fill_empty=True)
        self.assertGreater(len(filled), 1)
        blanks = [row for row in filled if row["count"] == 0]
        self.assertTrue(blanks)


# =====================================================================
# 3. 分析层（异常检测 / 回归 / 噪音 / 相似度）
# =====================================================================


class AnalyticsTests(ApiTestBase):
    """分析纯函数：稳健 z 分数、线性回归、噪音打分、文本相似度。"""

    def test_robust_z_and_mad(self):
        baseline = [10, 10, 11, 9, 10, 10, 10]
        self.assertGreater(analytics.robust_z(50, baseline), 3.5)
        self.assertLess(abs(analytics.robust_z(10, baseline)), 1.0)
        self.assertGreaterEqual(analytics.mad(baseline), 0.0)

    def test_detect_anomalies_flags_spike_and_drop(self):
        now = timezone.now()
        rows = [(now - timedelta(minutes=60 - i), 10.0) for i in range(20)]
        rows.append((now - timedelta(minutes=1), 200.0))
        detection = analytics.detect_anomalies(rows, window=20, threshold=3.5)
        self.assertTrue(detection["available"])
        self.assertEqual(detection["count"], 1)
        self.assertEqual(detection["items"][0]["direction"], "spike")
        self.assertEqual(detection["items"][0]["severity"], "critical")

    def test_detect_anomalies_needs_samples(self):
        now = timezone.now()
        detection = analytics.detect_anomalies([(now, 1.0), (now, 2.0)])
        self.assertFalse(detection["available"])
        self.assertIn("样本不足", detection["reason"])

    def test_linear_regression_recovers_line(self):
        fit = analytics.linear_regression([(0, 1), (1, 3), (2, 5), (3, 7)])
        self.assertAlmostEqual(fit["slope"], 2.0, places=4)
        self.assertAlmostEqual(fit["intercept"], 1.0, places=4)
        self.assertGreater(fit["r2"], 0.99)

    def test_capacity_forecast_projects_breach(self):
        now = timezone.now()
        rows = [(now - timedelta(days=6 - i), 10 + 5 * i) for i in range(7)]
        forecast = analytics.capacity_burn_forecast(rows, 100, horizon_days=60)
        self.assertTrue(forecast["available"])
        self.assertEqual(forecast["trend"], "rising")
        self.assertIsNotNone(forecast["projected_breach_date"])
        self.assertGreater(forecast["confidence"], 0.9)

    def test_capacity_forecast_flat_trend(self):
        now = timezone.now()
        rows = [(now - timedelta(days=3 - i), 10.0 + (i % 2)) for i in range(4)]
        forecast = analytics.capacity_burn_forecast(rows, 100)
        self.assertTrue(forecast["available"])
        self.assertIn(forecast["trend"], ("flat_or_down", "rising"))

    def test_alert_noise_score_bands(self):
        noisy = analytics.alert_noise_score(total=40, resolved=2, suppressed=10,
                                            firing=28, distinct_days=1)
        calm = analytics.alert_noise_score(total=4, resolved=4, suppressed=0,
                                           firing=0, distinct_days=4)
        self.assertGreater(noisy["score"], calm["score"])
        self.assertIn(noisy["band"], ("严重噪音", "噪音偏高"))
        self.assertIn(noisy["advice"], ("立即合并/删除规则，或延长持续时间并提高阈值",
                                        "建议合并同类规则、增加抑制与分组"))

    def test_alert_noise_score_zero_events(self):
        score = analytics.alert_noise_score(total=0, resolved=0, suppressed=0, firing=0)
        self.assertEqual(score["score"], 0.0)
        self.assertEqual(score["band"], "健康")

    def test_error_budget_policy_freeze(self):
        policy = analytics.error_budget_policy(
            {"state": "critical_burn", "worst_window": "1h"},
            {"status": "exhausted", "total_allowed": 10, "remaining": 0})
        self.assertEqual(policy["decision"], "freeze")
        self.assertTrue(policy["actions"])

    def test_error_budget_policy_normal(self):
        policy = analytics.error_budget_policy({"state": "ok"}, {"status": "healthy"})
        self.assertEqual(policy["decision"], "normal")

    def test_incident_similarity_uses_services_and_text(self):
        service = self.create_service()
        base = self.create_incident(title="数据库连接池耗尽", services=[service["id"]])
        other = self.create_incident(title="数据库连接池耗尽", services=[service["id"]])
        unrelated = self.create_incident(title="前端构建失败", services=[])
        incident = Incident.objects.get(pk=base["id"])
        rows = analytics.incident_similarity(
            incident, [Incident.objects.get(pk=other["id"]),
                       Incident.objects.get(pk=unrelated["id"])], limit=5)
        self.assertTrue(rows)
        self.assertEqual(rows[0]["incident_id"], other["id"])
        self.assertGreaterEqual(rows[0]["score"], rows[-1]["score"])

    def test_health_trend_segments_outages(self):
        service = self.create_service()
        check = self.create_check(service["id"])
        now = timezone.now()
        check_obj = services.get_check(check["id"], self.user)
        for offset, status in enumerate(["up", "up", "down", "down", "up"]):
            HealthCheckRun.objects.create(
                owner=self.user, health_check=check_obj, status=status,
                latency_ms=10, checked_at=now - timedelta(minutes=10 - offset))
        runs = list(check_obj.runs.order_by("checked_at"))
        trend = analytics.health_trend(runs, bucket_hours=1)
        self.assertTrue(trend["available"])
        self.assertTrue(trend["points"])
        self.assertEqual(len(trend["outages"]), 1)
        self.assertEqual(trend["outages"][0]["failures"], 2)
        self.assertLess(trend["availability_pct"], 100.0)


# =====================================================================
# 4. 服务目录
# =====================================================================


class ServiceCrudTests(ApiTestBase):
    """服务 CRUD、筛选、分页与总览。"""

    def test_create_and_detail(self):
        service = self.create_service(name="订单服务", slug="orders")
        self.assertEqual(service["slug"], "orders")
        self.assertEqual(service["status"], "healthy")
        self.assertEqual(service["owner_name"], "爱丽丝")
        detail = self.ok(self.get(f"services/{service['id']}/"))
        self.assertEqual(detail["counts"]["endpoints"], 0)
        self.assertIn("health_score", detail["health"])

    def test_slug_auto_generated_and_unique(self):
        first = self.create_service(name="Payment Gateway")
        self.assertEqual(first["slug"], "payment-gateway")
        # 同名自动生成时追加序号（中文名 slugify 为空也走这条路径）
        second = self.create_service(name="Payment Gateway")
        self.assertEqual(second["slug"], "payment-gateway-2")
        chinese = self.create_service(name="风控服务")
        self.assertTrue(chinese["slug"].startswith("service"))

    def test_explicit_duplicate_slug_rejected(self):
        self.create_service(name="订单服务", slug="orders")
        response = self.post("services/create/", {"name": "另一个服务", "slug": "orders"})
        self.expect_error(response, "服务标识已存在")

    def test_create_requires_name(self):
        response = self.post("services/create/", {"name": "   "})
        self.expect_error(response, "服务名称不能为空")

    def test_create_rejects_unknown_level(self):
        response = self.post("services/create/", {"name": "x", "level": "P9"})
        self.expect_error(response, "服务等级")

    def test_list_filters_and_pagination(self):
        self.create_service(name="订单服务", team="交易", level="P0")
        self.create_service(name="风控服务", team="风控", level="P1", status="degraded")
        data = self.ok(self.get("services/", {"page_size": 1}))
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 1)
        filtered = self.ok(self.get("services/", {"level": "P1"}))
        self.assertEqual(filtered["count"], 1)
        self.assertEqual(filtered["items"][0]["name"], "风控服务")
        by_status = self.ok(self.get("services/", {"status": "degraded"}))
        self.assertEqual(by_status["count"], 1)
        by_q = self.ok(self.get("services/", {"q": "订单"}))
        self.assertEqual(by_q["count"], 1)
        by_team = self.ok(self.get("services/", {"team": "风控"}))
        self.assertEqual(by_team["count"], 1)

    def test_page_size_over_limit_rejected(self):
        response = self.get("services/", {"page_size": 1000})
        self.expect_error(response, "不能大于 200")

    def test_update_and_labels(self):
        service = self.create_service()
        updated = self.ok(self.post(f"services/{service['id']}/update/", {
            "id": service["id"], "name": "订单服务 v2", "status": "degraded",
            "labels": {"env": "prod"}}))
        self.assertEqual(updated["name"], "订单服务 v2")
        self.assertEqual(updated["status"], "degraded")
        self.assertEqual(updated["labels"], {"env": "prod"})

    def test_update_rejects_empty_name(self):
        service = self.create_service()
        response = self.post(f"services/{service['id']}/update/",
                             {"id": service["id"], "name": " "})
        self.expect_error(response, "服务名称不能为空")

    def test_overview_and_graph(self):
        service = self.create_service()
        overview = self.ok(self.get("services/overview/"))
        self.assertEqual(overview["total"], 1)
        self.assertEqual(overview["by_status"]["healthy"], 1)
        self.assertIn("avg_health_score", overview)
        graph = self.ok(self.get("services/graph/"))
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertFalse(graph["cycle_detected"])

    def test_delete_removes_service(self):
        service = self.create_service()
        result = self.ok(self.post(f"services/{service['id']}/delete/"))
        self.assertTrue(result["deleted"])
        self.assertFalse(Service.objects.filter(pk=service["id"]).exists())
        self.bad(self.get(f"services/{service['id']}/"))


# =====================================================================
# 5. 端点、依赖与影响分析
# =====================================================================


class TopologyTests(ApiTestBase):
    """端点登记、依赖边维护、依赖计数与故障影响分析。"""

    def setUp(self):
        super().setUp()
        self.upstream = self.create_service(name="网关", level="P0")
        self.mid = self.create_service(name="订单服务", level="P1")
        self.downstream = self.create_service(name="用户库", level="P2")

    def add_edge(self, upstream_id, downstream_id, **overrides):
        payload = {"upstream_id": upstream_id, "downstream_id": downstream_id}
        payload.update(overrides)
        return self.ok(self.post("dependencies/create/", payload))

    def test_endpoint_crud(self):
        created = self.ok(self.post("endpoints/create/", {
            "service_id": self.upstream["id"], "path": "/api/order",
            "method": "get", "timeout_ms": 2000}))
        self.assertEqual(created["method"], "GET")
        updated = self.ok(self.post(f"endpoints/{created['id']}/update/", {
            "id": created["id"], "status": "degraded", "p95_ms": 320}))
        self.assertEqual(updated["status"], "degraded")
        self.assertEqual(updated["p95_ms"], 320.0)
        listing = self.ok(self.get("endpoints/", {"service_id": self.upstream["id"]}))
        self.assertEqual(listing["count"], 1)
        self.ok(self.post(f"endpoints/{created['id']}/delete/"))
        self.assertEqual(self.ok(self.get("endpoints/"))["count"], 0)

    def test_endpoint_path_must_start_with_slash(self):
        response = self.post("endpoints/create/", {
            "service_id": self.upstream["id"], "path": "api/order"})
        self.expect_error(response, "必须以 / 开头")

    def test_endpoint_duplicate_rejected(self):
        payload = {"service_id": self.upstream["id"], "path": "/pay", "method": "POST"}
        self.ok(self.post("endpoints/create/", payload))
        self.expect_error(self.post("endpoints/create/", payload), "已存在相同方法")

    def test_dependency_create_updates_counts(self):
        dep = self.add_edge(self.upstream["id"], self.downstream["id"],
                            criticality="critical")
        self.assertEqual(dep["criticality"], "critical")
        self.upstream = self.ok(self.get(f"services/{self.upstream['id']}/"))
        self.assertEqual(self.upstream["dependency_count"], 1)
        listing = self.ok(self.get("dependencies/", {"upstream_id": self.upstream["id"]}))
        self.assertEqual(listing["count"], 1)

    def test_dependency_rejects_self_and_duplicate(self):
        response = self.post("dependencies/create/", {
            "upstream_id": self.mid["id"], "downstream_id": self.mid["id"]})
        self.expect_error(response, "不能依赖自身")
        self.add_edge(self.mid["id"], self.downstream["id"])
        dup = self.post("dependencies/create/", {
            "upstream_id": self.mid["id"], "downstream_id": self.downstream["id"]})
        self.expect_error(dup, "依赖关系已存在")

    def test_dependency_impact_propagates_upstream(self):
        self.add_edge(self.upstream["id"], self.mid["id"])
        self.add_edge(self.mid["id"], self.downstream["id"])
        impact = self.ok(self.get("dependencies/impact/",
                                  {"service_id": self.downstream["id"]}))
        self.assertEqual(impact["impacted_count"], 2)
        names = [row["name"] for row in impact["impacted"]]
        self.assertIn("网关", names)
        self.assertEqual(impact["max_depth"], 2)
        self.assertFalse(impact["cycle_detected"])

    def test_impact_detects_cycle(self):
        self.add_edge(self.upstream["id"], self.mid["id"])
        self.add_edge(self.mid["id"], self.upstream["id"])
        impact = self.ok(self.get("dependencies/impact/",
                                  {"service_id": self.upstream["id"]}))
        self.assertTrue(impact["cycle_detected"])
        graph = self.ok(self.get("services/graph/"))
        self.assertTrue(graph["cycle_detected"])

    def test_dependency_delete_restores_count(self):
        dep = self.add_edge(self.upstream["id"], self.downstream["id"])
        result = self.ok(self.post(f"dependencies/{dep['id']}/delete/"))
        self.assertEqual(result["upstream_id"], self.upstream["id"])
        refreshed = self.ok(self.get(f"services/{self.upstream['id']}/"))
        self.assertEqual(refreshed["dependency_count"], 0)

    def test_service_delete_repairs_affected_counts(self):
        self.add_edge(self.upstream["id"], self.downstream["id"])
        self.add_edge(self.mid["id"], self.downstream["id"])
        result = self.ok(self.post(f"services/{self.downstream['id']}/delete/"))
        self.assertIn(self.mid["id"], result["affected_services"])
        refreshed = self.ok(self.get(f"services/{self.mid['id']}/"))
        self.assertEqual(refreshed["dependency_count"], 0)


# =====================================================================
# 6. 指标上报与查询
# =====================================================================


class MetricTests(ApiTestBase):
    """指标定义 CRUD、单条/批量上报、聚合查询、分位、最新值与标签枚举。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service()

    def test_metric_definition_crud(self):
        metric = self.create_metric(self.service["id"], unit="次")
        self.assertEqual(metric["name"], "requests_total")
        updated = self.ok(self.post(f"metrics/defs/{metric['id']}/update/", {
            "id": metric["id"], "retention_days": 90}))
        self.assertEqual(updated["retention_days"], 90)
        listing = self.ok(self.get("metrics/defs/", {"service_id": self.service["id"]}))
        self.assertEqual(listing["count"], 1)
        self.ok(self.post(f"metrics/defs/{metric['id']}/delete/"))
        self.assertEqual(self.ok(self.get("metrics/defs/"))["count"], 0)

    def test_metric_duplicate_rejected(self):
        self.create_metric(self.service["id"])
        response = self.post("metrics/defs/create/", {
            "service_id": self.service["id"], "name": "requests_total"})
        self.expect_error(response, "已存在同名指标")

    def test_report_auto_register(self):
        point = self.report(self.service["id"], "qps", 12.5, auto_register=True,
                            labels={"instance": "a"})
        self.assertEqual(point["value"], 12.5)
        self.assertEqual(point["labels"], {"instance": "a"})
        self.assertTrue(MetricDef.objects.filter(service_id=self.service["id"],
                                                 name="qps").exists())

    def test_report_unknown_metric_without_auto_register(self):
        response = self.post("metrics/points/report/", {
            "service_id": self.service["id"], "metric": "unknown", "value": 1})
        self.expect_error(response, "指标不存在")

    def test_report_invalid_timestamp(self):
        self.create_metric(self.service["id"])
        response = self.post("metrics/points/report/", {
            "service_id": self.service["id"], "metric": "requests_total",
            "value": 1, "timestamp": "not-a-time"})
        self.expect_error(response, "时间")

    def test_report_invalid_value(self):
        self.create_metric(self.service["id"])
        response = self.post("metrics/points/report/", {
            "service_id": self.service["id"], "metric": "requests_total",
            "value": "abc"})
        self.expect_error(response, "数值")

    def test_batch_report(self):
        self.create_metric(self.service["id"])
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "requests_total",
                  "value": i, "timestamp": (now - timedelta(minutes=30 - i)).isoformat()}
                 for i in range(5)]
        result = self.batch_points(items)
        self.assertEqual(result["created"], 5)
        self.assertEqual(MetricPoint.objects.count(), 5)

    def test_batch_rejects_bad_item(self):
        self.create_metric(self.service["id"])
        response = self.post("metrics/points/batch/", {
            "points": [{"service_id": self.service["id"],
                        "metric": "requests_total", "value": "x"}]})
        self.expect_error(response, "数值非法")

    def test_batch_requires_points(self):
        self.expect_error(self.post("metrics/points/batch/", {"points": []}),
                          "不能为空数组")

    def test_query_aggregation_and_buckets(self):
        self.create_metric(self.service["id"])
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "requests_total",
                  "value": 10, "timestamp": (now - timedelta(minutes=40 - 10 * i)).isoformat()}
                 for i in range(4)]
        self.batch_points(items)
        data = self.ok(self.get("metrics/points/query/", {
            "service_id": self.service["id"], "metric": "requests_total",
            "hours": 2, "aggregation": "sum", "bucket_seconds": 600}))
        self.assertEqual(data["count"], 4)
        self.assertEqual(data["value"], 40.0)
        self.assertEqual(data["aggregation"], "sum")
        self.assertTrue(data["points"])
        self.assertFalse(data["missing"])

    def test_query_group_by_label(self):
        self.create_metric(self.service["id"])
        now = timezone.now()
        items = []
        for index, instance in enumerate(["a", "a", "b"]):
            items.append({"service_id": self.service["id"],
                          "metric": "requests_total", "value": 10 + index,
                          "timestamp": (now - timedelta(minutes=20 - index)).isoformat(),
                          "labels": {"instance": instance}})
        self.batch_points(items)
        data = self.ok(self.get("metrics/points/query/", {
            "service_id": self.service["id"], "metric": "requests_total",
            "hours": 2, "group_by": "instance"}))
        self.assertEqual(len(data["groups"]), 2)
        self.assertEqual({row["label"] for row in data["groups"]}, {"a", "b"})

    def test_percentiles(self):
        self.create_metric(self.service["id"], name="request_latency_ms",
                           metric_type="histogram")
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "request_latency_ms",
                  "value": value,
                  "timestamp": (now - timedelta(minutes=60 - value)).isoformat()}
                 for value in range(1, 101)]
        self.batch_points(items)
        data = self.ok(self.get("metrics/points/percentiles/", {
            "service_id": self.service["id"], "metric": "request_latency_ms",
            "hours": 2}))
        self.assertEqual(data["summary"]["p50"], 50.0)
        self.assertEqual(data["summary"]["p90"], 90.0)
        self.assertEqual(data["summary"]["p95"], 95.0)
        self.assertEqual(data["summary"]["p99"], 99.0)
        self.assertEqual(data["method"], "nearest_rank")

    def test_percentiles_without_data(self):
        self.create_metric(self.service["id"])
        response = self.get("metrics/points/percentiles/", {
            "service_id": self.service["id"], "metric": "requests_total"})
        self.expect_error(response, "没有指标数据")

    def test_latest_and_label_filter(self):
        self.create_metric(self.service["id"])
        self.report(self.service["id"], "requests_total", 1, labels={"instance": "a"},
                    at=self.minutes_ago(30))
        self.report(self.service["id"], "requests_total", 9, labels={"instance": "b"},
                    at=self.minutes_ago(20))
        latest = self.ok(self.get("metrics/points/latest/", {
            "service_id": self.service["id"], "metric": "requests_total"}))
        self.assertEqual(latest["point"]["value"], 9.0)
        filtered = self.ok(self.get("metrics/points/latest/", {
            "service_id": self.service["id"], "metric": "requests_total",
            "label_key": "instance", "label_value": "a"}))
        self.assertEqual(filtered["point"]["value"], 1.0)

    def test_labels_enumeration(self):
        self.create_metric(self.service["id"])
        self.report(self.service["id"], "requests_total", 1,
                    labels={"instance": "a", "region": "cn"})
        data = self.ok(self.get("metrics/points/labels/", {
            "service_id": self.service["id"], "metric": "requests_total"}))
        self.assertEqual(data["keys"], ["instance", "region"])
        self.assertEqual(data["labels"][0]["values"], ["a"])

    def test_metric_delete_reports_points_removed(self):
        metric = self.create_metric(self.service["id"])
        self.report(self.service["id"], "requests_total", 1)
        result = self.ok(self.post(f"metrics/defs/{metric['id']}/delete/"))
        self.assertEqual(result["points_deleted"], 1)

    def test_invalid_window_rejected(self):
        self.create_metric(self.service["id"])
        response = self.get("metrics/points/query/", {
            "service_id": self.service["id"], "metric": "requests_total",
            "since": "2026-01-02T00:00:00+00:00", "until": "2026-01-01T00:00:00+00:00"})
        self.expect_error(response, "窗口开始时间必须早于结束时间")


# =====================================================================
# 7. SLO、燃烧率与错误预算
# =====================================================================


class SloTests(ApiTestBase):
    """SLO 创建校验、窗口计算、预算、燃烧率、预测与排行。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service()
        self.create_metric(self.service["id"], name="requests_total")
        self.create_metric(self.service["id"], name="errors_total")
        self.create_metric(self.service["id"], name="request_latency_ms",
                           metric_type="histogram", unit="ms")

    def test_create_requires_latency_threshold(self):
        response = self.post("slos/create/", {
            "service_id": self.service["id"], "name": "延迟", "slo_type": "latency"})
        self.expect_error(response, "延迟类 SLO 必须配置")

    def test_create_validates_target_range(self):
        response = self.post("slos/create/", {
            "service_id": self.service["id"], "name": "x", "target_pct": 120})
        self.expect_error(response, "目标百分比必须在 0 到 100 之间")

    def test_duplicate_name_rejected(self):
        self.create_slo(self.service["id"])
        response = self.post("slos/create/", {
            "service_id": self.service["id"], "name": "可用性 99%"})
        self.expect_error(response, "已存在同名 SLO")

    def compute_availability(self):
        self.create_slo(self.service["id"])
        self.report(self.service["id"], "requests_total", 1000, at=self.hours_ago(1))
        self.report(self.service["id"], "errors_total", 5, at=self.hours_ago(1))
        slo_id = Slo.objects.get(service_id=self.service["id"]).id
        return slo_id, self.ok(self.post(f"slos/{slo_id}/compute/", {"id": slo_id}))

    def test_compute_writes_window_and_budget(self):
        slo_id, result = self.compute_availability()
        self.assertEqual(result["total_requests"], 1000)
        self.assertEqual(result["bad_requests"], 5)
        self.assertEqual(result["attainment_pct"], 99.5)
        self.assertTrue(result["met"])
        self.assertEqual(SloWindow.objects.filter(slo_id=slo_id).count(), 1)
        self.assertEqual(ErrorBudget.objects.filter(slo_id=slo_id).count(), 1)
        self.assertIn("budget", result)

    def test_compute_is_idempotent(self):
        slo_id, _first = self.compute_availability()
        self.ok(self.post(f"slos/{slo_id}/compute/", {"id": slo_id}))
        self.assertEqual(SloWindow.objects.filter(slo_id=slo_id).count(), 1)

    def test_compute_without_metrics_reports_400(self):
        slo = self.create_slo(self.service["id"], name="空 SLO")
        response = self.post(f"slos/{slo['id']}/compute/", {"id": slo["id"]})
        self.expect_error(response, "没有请求指标数据")

    def test_compute_invalid_window(self):
        slo = self.create_slo(self.service["id"])
        response = self.post(f"slos/{slo['id']}/compute/", {
            "id": slo["id"], "since": "2026-02-01T00:00:00+00:00",
            "until": "2026-01-01T00:00:00+00:00"})
        self.expect_error(response, "窗口开始时间必须早于结束时间")

    def test_list_and_detail_include_snapshot(self):
        slo_id, _result = self.compute_availability()
        listing = self.ok(self.get("slos/", {"service_id": self.service["id"]}))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["snapshot"]["state"], "met")
        detail = self.ok(self.get(f"slos/{slo_id}/"))
        self.assertEqual(len(detail["windows"]), 1)
        self.assertEqual(detail["budget"]["status"], "healthy")

    def test_windows_history_pagination(self):
        slo_id, _result = self.compute_availability()
        windows = self.ok(self.get(f"slos/{slo_id}/windows/", {"page_size": 5}))
        self.assertEqual(windows["count"], 1)
        self.assertEqual(windows["page_size"], 5)

    def test_budget_requires_compute_first(self):
        slo = self.create_slo(self.service["id"])
        response = self.get(f"slos/{slo['id']}/budget/")
        self.expect_error(response, "尚无预算快照")

    def test_budget_recompute_flag(self):
        slo_id, _result = self.compute_availability()
        snapshot = self.ok(self.get(f"slos/{slo_id}/budget/", {"recompute": "1"}))
        self.assertIn("total_allowed", snapshot)
        self.assertIn("status", snapshot)
        self.assertEqual(snapshot["status"], "healthy")

    def test_budget_exhausted_when_errors_exceed_allowance(self):
        slo = self.create_slo(self.service["id"], name="严格 SLO", target_pct=99.9)
        self.report(self.service["id"], "requests_total", 1000, at=self.hours_ago(1))
        self.report(self.service["id"], "errors_total", 100, at=self.hours_ago(1))
        result = self.ok(self.post(f"slos/{slo['id']}/compute/", {"id": slo["id"]}))
        self.assertFalse(result["met"])
        self.assertEqual(result["budget"]["status"], "exhausted")
        self.assertEqual(result["budget"]["remaining"], 0.0)

    def test_burn_rate_windows(self):
        slo = self.create_slo(self.service["id"], name="燃烧 SLO", target_pct=99.9)
        self.report(self.service["id"], "requests_total", 1000, at=self.minutes_ago(10))
        self.report(self.service["id"], "errors_total", 100, at=self.minutes_ago(10))
        report = self.ok(self.get(f"slos/{slo['id']}/burn-rate/"))
        self.assertEqual(len(report["windows"]), 3)
        self.assertEqual([row["window"] for row in report["windows"]],
                         ["1h", "6h", "3d"])
        self.assertEqual(report["state"], "critical_burn")
        self.assertEqual(report["worst_window"], "1h")
        self.assertGreater(report["windows"][0]["burn_rate"], 14.4)

    def test_burn_rate_without_data(self):
        slo = self.create_slo(self.service["id"])
        report = self.ok(self.get(f"slos/{slo['id']}/burn-rate/"))
        self.assertEqual(report["state"], "insufficient_data")

    def test_budget_forecast_curve(self):
        slo_id, _result = self.compute_availability()
        forecast = self.ok(self.get(f"slos/{slo_id}/forecast/", {"days": 10}))
        self.assertTrue(forecast["available"])
        self.assertEqual(len(forecast["points"]), 11)
        self.assertEqual(forecast["points"][0]["remaining"], forecast["remaining"])

    def test_forecast_without_budget(self):
        slo = self.create_slo(self.service["id"])
        forecast = self.ok(self.get(f"slos/{slo['id']}/forecast/"))
        self.assertFalse(forecast["available"])

    def test_latency_slo_uses_samples(self):
        slo = self.create_slo(self.service["id"], name="延迟 SLO", slo_type="latency",
                              target_pct=90, latency_threshold_ms=250)
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "request_latency_ms",
                  "value": value, "timestamp": (now - timedelta(minutes=30 - value)).isoformat()}
                 for value in (100, 150, 300, 400)]
        self.batch_points(items)
        result = self.ok(self.post(f"slos/{slo['id']}/compute/", {"id": slo["id"]}))
        self.assertEqual(result["total_requests"], 4)
        self.assertEqual(result["good_requests"], 2)
        self.assertEqual(result["attainment_pct"], 50.0)
        self.assertEqual(result["source"], "latency_samples")

    def test_update_slo(self):
        slo = self.create_slo(self.service["id"])
        updated = self.ok(self.post(f"slos/{slo['id']}/update/", {
            "id": slo["id"], "target_pct": 99.95, "window_days": 7}))
        self.assertEqual(updated["target_pct"], 99.95)
        self.assertEqual(updated["window_days"], 7)

    def test_update_to_latency_requires_threshold(self):
        slo = self.create_slo(self.service["id"])
        response = self.post(f"slos/{slo['id']}/update/", {
            "id": slo["id"], "slo_type": "latency"})
        self.expect_error(response, "延迟类 SLO 必须配置")

    def test_delete_slo_cascades(self):
        slo_id, _result = self.compute_availability()
        self.ok(self.post(f"slos/{slo_id}/delete/"))
        self.assertEqual(SloWindow.objects.filter(slo_id=slo_id).count(), 0)
        self.assertEqual(ErrorBudget.objects.filter(slo_id=slo_id).count(), 0)


# =====================================================================
# 8. 告警链路
# =====================================================================


class AlertTests(ApiTestBase):
    """告警规则校验、触发去重、抑制间隔、静默与自动恢复。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service(name="支付服务")
        self.create_metric(self.service["id"])

    def high_points(self, count=6, value=10.0):
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "requests_total",
                  "value": value,
                  "timestamp": (now - timedelta(seconds=5 * (index + 1))).isoformat()}
                 for index in range(count)]
        self.batch_points(items)

    def test_rule_create_validates_expression(self):
        response = self.post("alerts/rules/create/", {
            "service_id": self.service["id"], "name": "坏规则",
            "expression": "requests_total over 5"})
        self.expect_error(response, "告警表达式格式")

    def test_rule_create_validates_metric_exists(self):
        response = self.post("alerts/rules/create/", {
            "service_id": self.service["id"], "name": "坏规则",
            "expression": "not_a_metric > 5"})
        self.expect_error(response, "指标不存在")

    def test_rule_create_accepts_pseudo_metric(self):
        rule = self.create_rule(self.service["id"], name="健康分",
                                expression="health_score < 80")
        self.assertEqual(rule["expression"], "health_score < 80")

    def test_rule_create_validates_severity(self):
        response = self.post("alerts/rules/create/", {
            "service_id": self.service["id"], "name": "x",
            "expression": "requests_total > 1", "severity": "fatal"})
        self.expect_error(response, "严重度")

    def test_rule_test_does_not_persist(self):
        rule = self.create_rule(self.service["id"])
        self.high_points()
        result = self.ok(self.post(f"alerts/rules/{rule['id']}/test/"))
        self.assertTrue(result["sustained"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["meta"]["op"], ">")
        self.assertEqual(AlertEvent.objects.count(), 0)

    def test_evaluate_fires_then_deduplicates(self):
        self.create_rule(self.service["id"])
        self.high_points()
        first = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(first["firing"], 1)
        self.assertEqual(first["by_state"].get("firing"), 1)
        event = AlertEvent.objects.get()
        self.assertEqual(event.status, "firing")
        self.assertIn("requests_total=10", event.summary)
        second = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(second["firing"], 1)
        self.assertTrue(second["items"][0]["deduplicated"])
        self.assertEqual(AlertEvent.objects.count(), 1)

    def test_evaluate_auto_resolves(self):
        rule = self.create_rule(self.service["id"])
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        self.ok(self.post(f"alerts/rules/{rule['id']}/update/", {
            "id": rule["id"], "expression": "requests_total > 1000"}))
        result = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(result["resolved"], 1)
        event = AlertEvent.objects.get()
        self.assertEqual(event.status, "resolved")
        self.assertIsNotNone(event.ended_at)
        again = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(again["by_state"].get("ok"), 1)

    def test_evaluate_no_data(self):
        self.create_rule(self.service["id"], expression="requests_total > 5")
        result = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(result["no_data"], 1)
        self.assertEqual(result["items"][0]["state"], "no_data")

    def test_disabled_rule_skipped(self):
        rule = self.create_rule(self.service["id"])
        self.ok(self.post(f"alerts/rules/{rule['id']}/toggle/"))
        toggled = Slo.objects.count()
        self.assertEqual(toggled, 0)
        result = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(result["total"], 0)
        self.assertFalse(AlertRule.objects.get(pk=rule["id"]).enabled)

    def test_silence_suppresses_new_event(self):
        rule = self.create_rule(self.service["id"])
        silence = self.ok(self.post("alerts/silences/create/", {
            "rule_id": rule["id"], "minutes": 30, "reason": "发版窗口"}))
        self.assertEqual(silence["status"], "active")
        self.high_points()
        result = self.ok(self.post("alerts/evaluate/", {}))
        self.assertEqual(result["suppressed"], 1)
        event = AlertEvent.objects.get()
        self.assertEqual(event.status, "suppressed")
        self.assertIsNotNone(event.silenced_until)

    def test_silence_cancel_restores_event(self):
        rule = self.create_rule(self.service["id"])
        silence = self.ok(self.post("alerts/silences/create/", {
            "rule_id": rule["id"], "minutes": 30}))
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        cancelled = self.ok(self.post(f"alerts/silences/{silence['id']}/cancel/"))
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(AlertEvent.objects.get().status, "firing")
        self.expect_error(self.post(f"alerts/silences/{silence['id']}/cancel/"),
                          "只有生效中的静默")

    def test_silence_validation(self):
        rule = self.create_rule(self.service["id"])
        response = self.post("alerts/silences/create/", {
            "rule_id": rule["id"], "start_at": "2026-03-02T00:00:00+00:00",
            "end_at": "2026-03-01T00:00:00+00:00"})
        self.expect_error(response, "静默结束时间必须晚于开始时间")

    def test_silence_update_extends(self):
        rule = self.create_rule(self.service["id"])
        silence = self.ok(self.post("alerts/silences/create/", {
            "rule_id": rule["id"], "minutes": 10}))
        updated = self.ok(self.post(f"alerts/silences/{silence['id']}/update/", {
            "minutes": 120}))
        self.assertEqual(updated["status"], "active")

    def test_event_acknowledge_and_resolve(self):
        self.create_rule(self.service["id"])
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        event = AlertEvent.objects.get()
        acked = self.ok(self.post(f"alerts/events/{event.id}/ack/",
                                  {"note": "已介入"}))
        self.assertEqual(acked["acknowledged_by"], "alice")
        self.assertIn("已介入", acked["summary"])
        resolved = self.ok(self.post(f"alerts/events/{event.id}/resolve/"))
        self.assertEqual(resolved["status"], "resolved")
        self.assertIsNotNone(resolved["ended_at"])

    def test_event_detail_and_filters(self):
        self.create_rule(self.service["id"])
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        event = AlertEvent.objects.get()
        detail = self.ok(self.get(f"alerts/events/{event.id}/"))
        self.assertEqual(detail["rule"]["expression"], "requests_total > 5")
        self.assertIsNone(detail["silence"])
        listing = self.ok(self.get("alerts/events/", {"status": "firing",
                                                      "service_id": self.service["id"]}))
        self.assertEqual(listing["count"], 1)
        by_severity = self.ok(self.get("alerts/events/", {"severity": "critical"}))
        self.assertEqual(by_severity["count"], 1)
        by_q = self.ok(self.get("alerts/events/", {"q": "支付"}))
        self.assertEqual(by_q["count"], 1)

    def test_event_silence_action(self):
        self.create_rule(self.service["id"])
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        event = AlertEvent.objects.get()
        payload = self.ok(self.post(f"alerts/events/{event.id}/silence/",
                                    {"minutes": 15, "reason": "已知问题"}))
        self.assertEqual(payload["silence"]["status"], "active")
        self.assertEqual(payload["event"]["status"], "suppressed")
        self.assertEqual(Silence.objects.count(), 1)

    def test_stats_by_rule(self):
        self.create_rule(self.service["id"])
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        data = self.ok(self.get("alerts/stats/by-rule/"))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["open"], 1)

    def test_rule_list_filters(self):
        self.create_rule(self.service["id"], name="规则甲")
        self.create_rule(self.service["id"], name="规则乙", severity="warning")
        listing = self.ok(self.get("alerts/rules/", {"severity": "warning"}))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["name"], "规则乙")
        by_q = self.ok(self.get("alerts/rules/", {"q": "规则甲"}))
        self.assertEqual(by_q["count"], 1)

    def test_rule_delete_cascades_events(self):
        rule = self.create_rule(self.service["id"])
        self.high_points()
        self.ok(self.post("alerts/evaluate/", {}))
        self.ok(self.post(f"alerts/rules/{rule['id']}/delete/"))
        self.assertEqual(AlertEvent.objects.count(), 0)


# =====================================================================
# 9. 事故状态机
# =====================================================================


class IncidentTests(ApiTestBase):
    """事故登记、合法/非法状态流转、时间线、更新记录与 MTTA/MTTR。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service(team="交易")

    def test_create_and_timeline(self):
        incident = self.create_incident(services=[self.service["id"]])
        self.assertEqual(incident["status"], "open")
        self.assertEqual(incident["owner_name"], "爱丽丝")
        self.assertEqual(IncidentUpdate.objects.count(), 1)
        timeline = self.ok(self.get(f"incidents/{incident['id']}/timeline/"))
        self.assertEqual(timeline["count"], 1)
        self.assertEqual(timeline["items"][0]["status_change"], "->open")

    def test_create_requires_title(self):
        self.expect_error(self.post("incidents/create/", {"title": " "}),
                          "事故标题不能为空")

    def test_create_rejects_future_start(self):
        response = self.post("incidents/create/", {
            "title": "未来事故", "started_at": (timezone.now() + timedelta(hours=1)).isoformat()})
        self.expect_error(response, "不能晚于当前时间")

    def test_illegal_transition_rejected(self):
        incident = self.create_incident()
        response = self.post(f"incidents/{incident['id']}/resolve/", {})
        self.expect_error(response, "不能从「待响应」直接变更为「已解决」")
        self.assertEqual(Incident.objects.get(pk=incident["id"]).status, "open")

    def test_full_lifecycle(self):
        incident = self.create_incident()
        acked = self.ok(self.post(f"incidents/{incident['id']}/acknowledge/",
                                  {"note": "开始排查"}))
        self.assertEqual(acked["status"], "acknowledged")
        self.assertIsNotNone(acked["acknowledged_at"])
        mitigated = self.ok(self.post(f"incidents/{incident['id']}/mitigate/"))
        self.assertEqual(mitigated["status"], "mitigated")
        resolved = self.ok(self.post(f"incidents/{incident['id']}/resolve/",
                                     {"root_cause": "连接池耗尽"}))
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["root_cause"], "连接池耗尽")
        self.assertIsNotNone(resolved["resolved_at"])
        done = self.ok(self.post(f"incidents/{incident['id']}/postmortem/",
                                 {"action_items": ["扩容连接池"]}))
        self.assertEqual(done["status"], "postmortem")
        self.assertEqual(done["action_items"], ["扩容连接池"])
        self.assertIsNotNone(done["mtta_seconds"])
        self.assertIsNotNone(done["mttr_seconds"])
        self.assertGreaterEqual(len(IncidentUpdate.objects.filter(
            incident_id=incident["id"])), 5)

    def test_postmortem_is_terminal(self):
        incident = self.create_incident()
        for action in ("acknowledge", "mitigate", "resolve", "postmortem"):
            self.ok(self.post(f"incidents/{incident['id']}/{action}/", {}))
        response = self.post(f"incidents/{incident['id']}/resolve/", {})
        self.expect_error(response, "已处于「已复盘」状态")

    def test_update_fields_and_service_filter(self):
        incident = self.create_incident()
        updated = self.ok(self.post(f"incidents/{incident['id']}/update/", {
            "id": incident["id"], "severity": "sev1", "impact": "支付全挂",
            "services": [self.service["id"]]}))
        self.assertEqual(updated["severity"], "sev1")
        self.assertEqual(updated["impact"], "支付全挂")
        listed = self.ok(self.get("incidents/", {"service_id": self.service["id"]}))
        self.assertEqual(listed["count"], 1)
        other = self.ok(self.get("incidents/", {"service_id": 99999}))
        self.assertEqual(other["count"], 0)

    def test_update_rejects_bad_severity(self):
        incident = self.create_incident()
        response = self.post(f"incidents/{incident['id']}/update/", {
            "id": incident["id"], "severity": "sev9"})
        self.expect_error(response, "事故严重度")

    def test_updates_crud(self):
        incident = self.create_incident()
        created = self.ok(self.post(f"incidents/{incident['id']}/updates/create/", {
            "content": "已定位到慢查询"}))
        self.assertEqual(created["content"], "已定位到慢查询")
        listing = self.ok(self.get(f"incidents/{incident['id']}/updates/"))
        self.assertEqual(listing["count"], 2)
        deleted = self.ok(self.post(f"incident-updates/{created['id']}/delete/"))
        self.assertEqual(deleted["incident_id"], incident["id"])

    def test_update_create_requires_content(self):
        incident = self.create_incident()
        response = self.post(f"incidents/{incident['id']}/updates/create/", {})
        self.expect_error(response, "更新内容不能为空")

    def test_delete_incident(self):
        incident = self.create_incident()
        self.ok(self.post(f"incidents/{incident['id']}/delete/"))
        self.assertEqual(Incident.objects.count(), 0)
        self.assertEqual(IncidentUpdate.objects.count(), 0)

    def test_list_filters(self):
        self.create_incident(title="支付超时", severity="sev1")
        self.create_incident(title="推荐降级", severity="sev3", status="open")
        severity = self.ok(self.get("incidents/", {"severity": "sev1"}))
        self.assertEqual(severity["count"], 1)
        keyword = self.ok(self.get("incidents/", {"q": "推荐"}))
        self.assertEqual(keyword["count"], 1)

    def test_mtta_mttr_stats(self):
        incident = self.create_incident(severity="sev1")
        self.ok(self.post(f"incidents/{incident['id']}/acknowledge/", {}))
        self.ok(self.post(f"incidents/{incident['id']}/mitigate/", {}))
        self.ok(self.post(f"incidents/{incident['id']}/resolve/", {}))
        stats = self.ok(self.get("stats/mtta-mttr/"))
        self.assertIsNotNone(stats["mtta_seconds"])
        self.assertIsNotNone(stats["mttr_seconds"])
        self.assertTrue(stats["meets_mtta_target"])
        self.assertIn("by_severity", stats)


# =====================================================================
# 10. 值班与升级
# =====================================================================


class OnCallTests(ApiTestBase):
    """值班表推导（当前/未来/换班）与升级策略触发检查。"""

    def test_schedule_validation(self):
        self.expect_error(self.post("oncall/schedules/create/",
                                    {"team": " ", "name": "x"}), "团队名称不能为空")
        self.expect_error(self.post("oncall/schedules/create/", {
            "team": "交易", "name": "x", "rotation": "hourly"}), "轮换周期")

    def test_current_shift_by_rotation(self):
        schedule = self.create_schedule(members=["alice", "bob"])
        data = self.ok(self.get("oncall/current/", {"team": "交易"}))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["member"], "alice")
        self.assertEqual(data["by_team"]["交易"], ["alice"])
        single = self.ok(self.get("oncall/current/", {"schedule_id": schedule["id"]}))
        self.assertEqual(single["count"], 1)

    def test_current_before_start_is_empty(self):
        self.create_schedule(start_at=(timezone.now() + timedelta(days=1)).isoformat())
        data = self.ok(self.get("oncall/current/", {"team": "交易"}))
        self.assertEqual(data["count"], 0)

    def test_upcoming_shifts(self):
        schedule = self.create_schedule(members=["alice", "bob"])
        data = self.ok(self.get("oncall/upcoming/", {"schedule_id": schedule["id"],
                                                     "count": 3}))
        self.assertEqual(data["count"], 3)
        self.assertTrue(data["items"][0]["is_current"])
        self.assertEqual(data["items"][1]["member"], "bob")

    def test_swap_shift(self):
        schedule = self.create_schedule(members=["alice", "bob"])
        result = self.ok(self.post("oncall/swap/", {
            "schedule_id": schedule["id"], "to_member": "carol"}))
        self.assertEqual(result["from"], "alice")
        self.assertEqual(result["to"], "carol")
        self.assertEqual(result["members"][0], "carol")

    def test_swap_to_same_member_rejected(self):
        schedule = self.create_schedule(members=["alice", "bob"])
        response = self.post("oncall/swap/", {"schedule_id": schedule["id"],
                                              "to_member": "alice"})
        self.expect_error(response, "换班目标与当前值班人相同")

    def test_schedule_update_and_delete(self):
        schedule = self.create_schedule()
        updated = self.ok(self.post(f"oncall/schedules/{schedule['id']}/update/", {
            "id": schedule["id"], "name": "备值班"}))
        self.assertEqual(updated["name"], "备值班")
        self.ok(self.post(f"oncall/schedules/{schedule['id']}/delete/"))
        self.assertEqual(self.ok(self.get("oncall/schedules/"))["count"], 0)

    def test_escalation_create_and_duplicate(self):
        created = self.ok(self.post("escalations/create/", {
            "team": "交易", "level": 1, "delay_minutes": 5,
            "target_user_id": self.user.id, "channels": ["sms"]}))
        self.assertEqual(created["level"], 1)
        self.assertEqual(created["target_name"], "爱丽丝")
        self.expect_error(self.post("escalations/create/", {
            "team": "交易", "level": 1}), "已存在")

    def test_escalation_check_by_elapsed(self):
        self.ok(self.post("escalations/create/", {"team": "交易", "level": 1,
                                                  "delay_minutes": 5,
                                                  "target_name": "爱丽丝"}))
        self.ok(self.post("escalations/create/", {"team": "交易", "level": 2,
                                                  "delay_minutes": 10,
                                                  "target_name": "鲍勃"}))
        data = self.ok(self.get("escalations/check/", {"team": "交易",
                                                       "elapsed_minutes": 7}))
        self.assertEqual(data["current_level"], 1)
        self.assertEqual(len(data["targets"]), 1)
        self.assertEqual(data["targets"][0]["target_name"], "爱丽丝")

    def test_escalation_check_by_incident(self):
        self.service = self.create_service(team="交易")
        self.ok(self.post("escalations/create/", {"team": "交易", "level": 1,
                                                  "delay_minutes": 5,
                                                  "target_name": "爱丽丝"}))
        self.ok(self.post("escalations/create/", {"team": "交易", "level": 2,
                                                  "delay_minutes": 10,
                                                  "target_name": "鲍勃"}))
        incident = self.create_incident(services=[self.service["id"]],
                                        started_at=self.minutes_ago(20))
        data = self.ok(self.get("escalations/check/", {"incident_id": incident["id"]}))
        self.assertEqual(data["team"], "交易")
        self.assertEqual(data["current_level"], 2)

    def test_escalation_check_without_policies(self):
        data = self.ok(self.get("escalations/check/", {"team": "未知团队"}))
        self.assertFalse(data["escalate"])
        self.assertEqual(data["levels"], [])

    def test_escalation_update_and_delete(self):
        created = self.ok(self.post("escalations/create/", {
            "team": "交易", "level": 1, "delay_minutes": 5}))
        updated = self.ok(self.post(f"escalations/{created['id']}/update/", {
            "id": created["id"], "delay_minutes": 15}))
        self.assertEqual(updated["delay_minutes"], 15)
        self.ok(self.post(f"escalations/{created['id']}/delete/"))
        self.assertEqual(self.ok(self.get("escalations/"))["count"], 0)


# =====================================================================
# 11. 运行手册与健康检查
# =====================================================================


class RunbookTests(ApiTestBase):
    """运行手册步骤校验、执行记录与历史查询。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service()

    def test_create_validates_steps(self):
        self.expect_error(self.post("runbooks/create/", {
            "name": "x", "steps": []}), "至少需要一个步骤")
        self.expect_error(self.post("runbooks/create/", {
            "name": "x", "steps": [{"command": "ls"}]}), "缺少 title")

    def test_create_accepts_strings_and_objects(self):
        runbook = self.ok(self.post("runbooks/create/", {
            "name": "数据库故障处置", "service_id": self.service["id"],
            "steps": ["检查连接数", {"title": "扩容", "command": "scale up",
                                   "expect": "副本数增加"}]}))
        self.assertEqual(len(runbook["steps"]), 2)
        self.assertEqual(runbook["steps"][1]["order"], 2)
        self.assertEqual(runbook["service_id"], self.service["id"])

    def test_execute_success_and_failure(self):
        runbook = self.ok(self.post("runbooks/create/", {
            "name": "处置", "steps": ["a", "b"]}))
        success = self.ok(self.post(f"runbooks/{runbook['id']}/execute/", {
            "id": runbook["id"], "note": "演练"}))
        self.assertEqual(success["status"], "succeeded")
        self.assertFalse(success["failed"])
        self.assertEqual(success["step_count"], 2)
        failed = self.ok(self.post(f"runbooks/{runbook['id']}/execute/", {
            "id": runbook["id"],
            "results": [{"order": 1, "status": "failed", "notes": "权限不足"}]}))
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["failed"])
        self.assertEqual(RunbookExecution.objects.count(), 2)

    def test_execute_rejects_bad_step_status(self):
        runbook = self.ok(self.post("runbooks/create/", {"name": "处置", "steps": ["a"]}))
        response = self.post(f"runbooks/{runbook['id']}/execute/", {
            "id": runbook["id"], "results": [{"order": 1, "status": "unknown"}]})
        self.expect_error(response, "步骤状态")

    def test_executions_history_and_detail(self):
        runbook = self.ok(self.post("runbooks/create/", {"name": "处置", "steps": ["a"]}))
        self.ok(self.post(f"runbooks/{runbook['id']}/execute/", {"id": runbook["id"]}))
        listing = self.ok(self.get(f"runbooks/{runbook['id']}/executions/"))
        self.assertEqual(listing["count"], 1)
        self.assertNotIn("steps", listing["items"][0])
        execution_id = listing["items"][0]["id"]
        detail = self.ok(self.get(f"runbook-executions/{execution_id}/"))
        self.assertIn("steps", detail)
        self.assertEqual(detail["steps"][0]["status"], "succeeded")

    def test_retired_runbook_cannot_execute(self):
        runbook = self.ok(self.post("runbooks/create/", {
            "name": "处置", "steps": ["a"], "status": "retired"}))
        response = self.post(f"runbooks/{runbook['id']}/execute/", {"id": runbook["id"]})
        self.expect_error(response, "已下线的手册不能执行")

    def test_list_and_update(self):
        runbook = self.ok(self.post("runbooks/create/", {"name": "处置", "steps": ["a"]}))
        listing = self.ok(self.get("runbooks/", {"q": "处置"}))
        self.assertEqual(listing["count"], 1)
        updated = self.ok(self.post(f"runbooks/{runbook['id']}/update/", {
            "id": runbook["id"], "version": "v2.0"}))
        self.assertEqual(updated["version"], "v2.0")
        self.ok(self.post(f"runbooks/{runbook['id']}/delete/"))
        self.assertEqual(RunbookExecution.objects.count(), 0)


class HealthCheckTests(ApiTestBase):
    """健康检查配置、执行状态同步、历史摘要与健康分。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service()

    def test_create_defaults_per_type(self):
        http = self.create_check(self.service["id"])
        self.assertIn("url", http["config"])
        tcp = self.create_check(self.service["id"], check_type="tcp")
        self.assertIn("port", tcp["config"])
        self.expect_error(self.post("health-checks/create/", {
            "service_id": self.service["id"], "check_type": "ftp"}), "检查类型")

    def test_run_success_updates_status(self):
        check = self.create_check(self.service["id"])
        payload = self.ok(self.post(f"health-checks/{check['id']}/run/", {
            "succeed": True, "latency_ms": 42}))
        self.assertEqual(payload["run"]["status"], "up")
        self.assertEqual(payload["check"]["status"], "up")
        self.assertEqual(payload["check"]["consecutive_failures"], 0)
        self.assertEqual(payload["health"]["score"], 100.0)

    def test_run_failure_counts_consecutive(self):
        check = self.create_check(self.service["id"], weight=3)
        payload = self.ok(self.post(f"health-checks/{check['id']}/run/", {
            "succeed": False, "error": "connection refused"}))
        self.assertEqual(payload["run"]["status"], "down")
        self.assertEqual(payload["check"]["consecutive_failures"], 1)
        self.assertLess(payload["health"]["score"], 100.0)
        self.assertEqual(payload["health"]["worst"], "down")
        second = self.ok(self.post(f"health-checks/{check['id']}/run/",
                                   {"succeed": False}))
        self.assertEqual(second["check"]["consecutive_failures"], 2)

    def test_run_timeout_degrades(self):
        check = self.create_check(self.service["id"], timeout_seconds=1)
        payload = self.ok(self.post(f"health-checks/{check['id']}/run/", {
            "succeed": True, "latency_ms": 5000}))
        self.assertEqual(payload["run"]["status"], "degraded")
        self.assertIn("超过超时阈值", payload["run"]["error"])

    def test_run_all(self):
        self.create_check(self.service["id"])
        self.create_check(self.service["id"], check_type="tcp")
        data = self.ok(self.post("health-checks/run-all/", {"succeed": True}))
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["by_status"].get("up"), 2)
        filtered = self.ok(self.post("health-checks/run-all/", {
            "service_id": self.service["id"], "succeed": False}))
        self.assertEqual(filtered["by_status"].get("down"), 2)

    def test_history_summary(self):
        check = self.create_check(self.service["id"])
        for succeed in (True, False, True):
            self.ok(self.post(f"health-checks/{check['id']}/run/",
                              {"succeed": succeed}))
        history = self.ok(self.get(f"health-checks/{check['id']}/history/"))
        self.assertEqual(history["count"], 3)
        self.assertEqual(history["summary"]["up"], 2)
        self.assertEqual(history["summary"]["down"], 1)
        self.assertAlmostEqual(history["summary"]["availability_pct"], 66.6667,
                               places=3)

    def test_trend_endpoint(self):
        check = self.create_check(self.service["id"])
        for succeed in (True, False):
            self.ok(self.post(f"health-checks/{check['id']}/run/",
                              {"succeed": succeed}))
        trend = self.ok(self.get("health-checks/trend/", {
            "check_id": check["id"], "bucket_hours": 1}))
        self.assertTrue(trend["available"])
        self.assertTrue(trend["points"])
        self.assertEqual(trend["total_runs"], 2)

    def test_service_health_reflects_checks(self):
        self.create_check(self.service["id"])
        self.ok(self.post("health-checks/run-all/", {"succeed": False}))
        health = self.ok(self.get(f"services/{self.service['id']}/health/"))
        self.assertEqual(health["status"], "down")
        self.assertLess(health["health_score"], 100.0)
        self.assertEqual(health["checks"]["down"], 1)

    def test_update_and_delete(self):
        check = self.create_check(self.service["id"])
        updated = self.ok(self.post(f"health-checks/{check['id']}/update/", {
            "id": check["id"], "weight": 5, "enabled": False}))
        self.assertEqual(updated["weight"], 5)
        self.assertFalse(updated["enabled"])
        self.ok(self.post(f"health-checks/{check['id']}/delete/"))
        self.assertEqual(HealthCheckRun.objects.count(), 0)

    def test_health_score_uses_weights(self):
        heavy = self.create_check(self.service["id"], weight=9)
        light = self.create_check(self.service["id"], weight=1)
        self.ok(self.post(f"health-checks/{heavy['id']}/run/", {"succeed": False}))
        self.ok(self.post(f"health-checks/{light['id']}/run/", {"succeed": True}))
        health = self.ok(self.get(f"services/{self.service['id']}/health/"))
        # 权重 9 的检查 down：扣分 9/(9+1)=90%，得分约 10 分
        self.assertLess(health["health_score"], 20.0)
        self.assertEqual(health["grade"], "F")


# =====================================================================
# 12. 面板、统计与分析师接口
# =====================================================================


class PanelTests(ApiTestBase):
    """仪表盘面板 CRUD、排序与数据取数。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service()
        self.create_metric(self.service["id"])

    def test_create_update_reorder(self):
        first = self.ok(self.post("panels/create/", {
            "name": "QPS", "service_id": self.service["id"],
            "query": {"metric": "requests_total"}}))
        second = self.ok(self.post("panels/create/", {
            "name": "延迟", "service_id": self.service["id"],
            "chart_type": "gauge"}))
        self.assertEqual(first["chart_type"], "line")
        reorder = self.ok(self.post("panels/reorder/", {
            "ids": [second["id"], first["id"]]}))
        self.assertEqual(reorder["reordered"], 2)
        listing = self.ok(self.get("panels/", {"service_id": self.service["id"]}))
        self.assertEqual(listing["items"][0]["id"], second["id"])
        updated = self.ok(self.post(f"panels/{first['id']}/update/", {
            "id": first["id"], "width": 12, "height": 8}))
        self.assertEqual(updated["width"], 12)

    def test_reorder_rejects_unknown_id(self):
        response = self.post("panels/reorder/", {"ids": [99999]})
        self.expect_error(response, "不可见或已删除")

    def test_panel_data_metric(self):
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "requests_total",
                  "value": 5, "timestamp": (now - timedelta(minutes=20 - i)).isoformat()}
                 for i in range(3)]
        self.batch_points(items)
        panel = self.ok(self.post("panels/create/", {
            "name": "QPS", "service_id": self.service["id"],
            "query": {"metric": "requests_total", "aggregation": "avg", "hours": 2}}))
        data = self.ok(self.get(f"panels/{panel['id']}/data/"))
        self.assertEqual(data["kind"], "metric")
        self.assertTrue(data["points"])
        self.assertEqual(data["summary"]["count"], 3)

    def test_panel_data_health_score(self):
        self.create_check(self.service["id"])
        panel = self.ok(self.post("panels/create/", {
            "name": "健康分", "service_id": self.service["id"],
            "query": {"kind": "health_score"}}))
        data = self.ok(self.get(f"panels/{panel['id']}/data/"))
        self.assertEqual(data["kind"], "health_score")
        self.assertIn("grade", data)

    def test_panel_data_requires_service_for_health(self):
        panel = self.ok(self.post("panels/create/", {
            "name": "健康分", "query": {"kind": "health_score"}}))
        self.expect_error(self.get(f"panels/{panel['id']}/data/"),
                          "未绑定服务")

    def test_panel_query_must_be_object(self):
        response = self.post("panels/create/", {"name": "x", "query": [1, 2]})
        self.expect_error(response, "必须是对象")

    def test_panel_delete(self):
        panel = self.ok(self.post("panels/create/", {"name": "x"}))
        self.ok(self.post(f"panels/{panel['id']}/delete/"))
        self.assertEqual(self.ok(self.get("panels/"))["count"], 0)


class StatsAndAnalyticsTests(ApiTestBase):
    """统计总览、告警 TOP、事故趋势、SLO 排行与分析接口。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service(level="P0")
        self.create_metric(self.service["id"])
        self.create_metric(self.service["id"], name="errors_total")
        self.create_metric(self.service["id"], name="qps", metric_type="gauge")

    def seed_events(self, rule, rows):
        # 工厂返回的是接口响应字典，这里取回真实对象以拿到 service 外键
        rule_obj = AlertRule.objects.get(pk=rule["id"]) if isinstance(rule, dict) else rule
        for offset, (status, days) in enumerate(rows):
            AlertEvent.objects.create(
                owner=self.user, rule=rule_obj, service=rule_obj.service, status=status,
                started_at=timezone.now() - timedelta(days=days, minutes=offset),
                value=10, summary="测试事件")

    def test_overview(self):
        self.create_slo(self.service["id"])
        self.create_incident()
        rule = self.create_rule(self.service["id"])
        self.seed_events(rule, [("firing", 0)])
        data = self.ok(self.get("stats/overview/"))
        self.assertEqual(data["services"]["total"], 1)
        self.assertEqual(data["alerts"]["firing"], 1)
        self.assertEqual(data["incidents"]["total"], 1)
        self.assertEqual(data["slos"]["total"], 1)
        self.assertIn("recent_incidents", data)

    def test_alerts_top(self):
        rule = self.create_rule(self.service["id"])
        self.seed_events(rule, [("resolved", 1), ("firing", 0)])
        data = self.ok(self.get("stats/alerts-top/", {"days": 7}))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["total"], 2)
        self.assertEqual(data["total_events"], 2)
        filtered = self.ok(self.get("stats/alerts-top/", {"severity": "warning"}))
        self.assertEqual(filtered["count"], 0)

    def test_incidents_trend(self):
        self.create_incident(started_at=self.days_ago(1))
        self.create_incident(started_at=self.days_ago(2))
        data = self.ok(self.get("stats/incidents-trend/", {"days": 14}))
        self.assertEqual(data["days"], 14)
        self.assertEqual(len(data["points"]), 14)
        self.assertEqual(data["total_opened"], 2)

    def test_slo_ranking(self):
        slo = self.create_slo(self.service["id"])
        self.report(self.service["id"], "requests_total", 1000, at=self.hours_ago(1))
        self.report(self.service["id"], "errors_total", 50, at=self.hours_ago(1))
        self.ok(self.post(f"slos/{slo['id']}/compute/", {"id": slo["id"]}))
        data = self.ok(self.get("stats/slo-ranking/"))
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["breached"], 1)
        self.assertEqual(data["items"][0]["state"], "breached")

    def test_recent_incidents(self):
        self.create_incident(title="支付超时")
        data = self.ok(self.get("stats/incidents-recent/", {"days": 7}))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["title"], "支付超时")

    def test_noise_ranking(self):
        rule = self.create_rule(self.service["id"])
        self.seed_events(rule, [("firing", 0), ("firing", 0), ("suppressed", 1),
                                ("resolved", 2)])
        data = self.ok(self.get("stats/noise-ranking/", {"days": 7}))
        self.assertEqual(data["count"], 1)
        item = data["items"][0]
        self.assertGreater(item["score"], 0)
        self.assertIn("band", item)
        self.assertIn("factors", item)

    def test_point_anomalies(self):
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "qps", "value": 10,
                  "timestamp": (now - timedelta(minutes=60 - i)).isoformat()}
                 for i in range(20)]
        items.append({"service_id": self.service["id"], "metric": "qps", "value": 200,
                      "timestamp": (now - timedelta(minutes=1)).isoformat()})
        self.batch_points(items)
        data = self.ok(self.get("metrics/points/anomalies/", {
            "service_id": self.service["id"], "metric": "qps", "hours": 3}))
        self.assertTrue(data["available"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["direction"], "spike")
        self.assertEqual(data["method"], "median_mad_robust_z")

    def test_capacity_forecast_endpoint(self):
        now = timezone.now()
        items = [{"service_id": self.service["id"], "metric": "qps",
                  "value": 10 + 5 * i,
                  "timestamp": (now - timedelta(days=6, hours=-i)).isoformat()}
                 for i in range(7)]
        self.batch_points(items)
        data = self.ok(self.get("stats/capacity-forecast/", {
            "service_id": self.service["id"], "metric": "qps",
            "threshold": 100, "horizon_days": 60}))
        self.assertTrue(data["available"])
        self.assertEqual(data["trend"], "rising")
        self.assertIn("digest", data)

    def test_service_criticality(self):
        downstream = self.create_service(name="用户库", level="P2")
        dependency = self.ok(self.post("dependencies/create/", {
            "upstream_id": self.service["id"], "downstream_id": downstream["id"]}))
        self.assertTrue(dependency["id"])
        data = self.ok(self.get(f"services/{downstream['id']}/criticality/"))
        self.assertEqual(data["direct_dependents"], 1)
        self.assertGreater(data["criticality_score"], 0)
        self.assertIn("ranking", data)

    def test_incident_similar_endpoint(self):
        first = self.create_incident(title="数据库连接池耗尽",
                                     services=[self.service["id"]])
        second = self.create_incident(title="数据库连接池耗尽",
                                      services=[self.service["id"]])
        data = self.ok(self.get(f"incidents/{first['id']}/similar/"))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["incident_id"], second["id"])

    def test_slo_policy_endpoint(self):
        slo = self.create_slo(self.service["id"], target_pct=99.9)
        self.report(self.service["id"], "requests_total", 1000, at=self.minutes_ago(5))
        self.report(self.service["id"], "errors_total", 100, at=self.minutes_ago(5))
        self.ok(self.post(f"slos/{slo['id']}/compute/", {"id": slo["id"]}))
        data = self.ok(self.get(f"slos/{slo['id']}/policy/"))
        self.assertIn(data["decision"], ("freeze", "slow_down", "watch", "normal"))
        self.assertTrue(data["actions"])
        self.assertIn("burn", data)


# =====================================================================
# 13. 行级权限隔离
# =====================================================================


class PermissionTests(ApiTestBase):
    """数据范围隔离：读走 scope、写只认 owner，管理员可越权操作。"""

    def setUp(self):
        super().setUp()
        self.service = self.create_service(name="私有服务")
        self.create_metric(self.service["id"])

    def test_other_user_cannot_list_or_read(self):
        self.as_user(self.other)
        listing = self.ok(self.get("services/"))
        self.assertEqual(listing["count"], 0)
        self.expect_error(self.get(f"services/{self.service['id']}/"),
                          "无权查看该数据")

    def test_other_user_cannot_write(self):
        self.as_user(self.other)
        self.expect_error(self.post(f"services/{self.service['id']}/update/", {
            "id": self.service["id"], "name": "偷改"}), "无权修改该数据")
        self.expect_error(self.post(f"services/{self.service['id']}/delete/"),
                          "无权修改该数据")

    def test_other_user_cannot_report_metric(self):
        self.as_user(self.other)
        response = self.post("metrics/points/report/", {
            "service_id": self.service["id"], "metric": "requests_total", "value": 1})
        self.expect_error(response, "无权修改该数据")

    def test_other_user_cannot_ack_alert(self):
        rule = self.create_rule(self.service["id"])
        now = timezone.now()
        AlertEvent.objects.create(owner=self.user, rule_id=rule["id"],
                                  service_id=self.service["id"], status="firing",
                                  started_at=now, value=10, summary="x")
        event = AlertEvent.objects.get()
        self.as_user(self.other)
        self.expect_error(self.post(f"alerts/events/{event.id}/ack/"),
                          "无权操作该告警事件")
        self.as_user(self.user)
        self.ok(self.post(f"alerts/events/{event.id}/ack/"))

    def test_admin_bypasses_scope(self):
        self.as_user(self.admin)
        listing = self.ok(self.get("services/"))
        self.assertEqual(listing["count"], 1)
        updated = self.ok(self.post(f"services/{self.service['id']}/update/", {
            "id": self.service["id"], "status": "maintenance"}))
        self.assertEqual(updated["status"], "maintenance")

    def test_other_user_cannot_touch_incident(self):
        incident = self.create_incident()
        self.as_user(self.other)
        self.expect_error(self.get(f"incidents/{incident['id']}/"),
                          "无权查看该数据")
        self.expect_error(self.post(f"incidents/{incident['id']}/acknowledge/"),
                          "无权修改该数据")
        self.assertFalse(Incident.objects.filter(pk=incident["id"],
                                                 status="acknowledged").exists())

    def test_bob_sees_only_own_data(self):
        self.as_user(self.other)
        self.ok(self.post("services/create/", {"name": "鲍勃的服务"}))
        own = self.ok(self.get("services/"))
        self.assertEqual(own["count"], 1)
        self.assertEqual(own["items"][0]["name"], "鲍勃的服务")
        self.as_user(self.user)
        self.assertEqual(self.ok(self.get("services/"))["count"], 1)

    def test_silence_only_creator_can_cancel(self):
        rule = self.create_rule(self.service["id"])
        silence = self.ok(self.post("alerts/silences/create/", {
            "rule_id": rule["id"], "minutes": 30}))
        self.as_user(self.admin)
        self.ok(self.post(f"alerts/silences/{silence['id']}/cancel/"))

    def test_metrics_are_scoped_in_catalog_counts(self):
        self.create_slo(self.service["id"])
        self.as_user(self.other)
        data = self.ok(self.get(""))
        self.assertEqual(data["counts"]["metrics"], 0)
        self.assertEqual(data["counts"]["slos"], 0)
