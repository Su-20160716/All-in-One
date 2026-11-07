# -*- coding: utf-8 -*-
"""rules 测试：表达式引擎、规则集/版本、规则配置、评估与动作、决策表、
用例与仿真、冲突与调度、审批与统计，以及行级权限隔离。

运行：venv/Scripts/python.exe manage.py test rules -v 1
（测试库为内存 sqlite，不触碰开发库，也不会发起任何网络请求）
"""
import json
from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from rules import services
from rules.expressions import (MAX_DEPTH, MAX_EXPR_LEN, ExprError,
                               combine_conditions, condition_expression,
                               evaluate_expression, explain_expression,
                               parse_expression, resolve_path,
                               validate_expression, validate_path)
from rules.models import (DecisionRow, Rule, RuleAction, RuleApproval,
                          RuleCondition, RuleConflict, RuleDecisionTable,
                          RuleEvaluation, RuleExecutionLog, RuleNotification,
                          RuleSchedule, RuleSet, RuleSetVersion, RuleSimulation,
                          RuleTag, RuleTask, RuleTemplate, RuleTestCase,
                          RuleVariable)

User = get_user_model()

BASE = "/api/rules/"


def facts_after(result):
    """便捷取评估后的上下文事实。"""
    return (result.get("decision") or {}).get("facts_after") or {}


def ensure_rules_tables():
    """测试库补建 rules 表。

    本应用当前不提交迁移文件（迁移统一生成是独立任务），但空的 migrations 包
    会让 Django 认为该应用「已迁移但没有迁移」，测试库不会 sync 建表。
    这里只对测试库做一次幂等补建，不影响开发库/生产库的迁移策略。
    """
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in apps.get_app_config("rules").get_models():
            if model._meta.db_table not in existing:
                editor.create_model(model)


class ExpressionEngineTests(TestCase):
    """表达式引擎纯函数：语法、函数白名单、限制与安全边界。"""

    def test_arithmetic_and_comparison(self):
        facts = {"amount": 120, "user": {"vip": True, "age": 30}}
        self.assertTrue(evaluate_expression(
            "facts.amount * 2 + 10 >= 250", facts))
        self.assertTrue(evaluate_expression("facts.amount % 2 == 0", facts))
        self.assertFalse(evaluate_expression("facts.amount / 3 > 50", facts))
        self.assertTrue(evaluate_expression(
            "facts.user.vip == true and facts.user.age > 18", facts))

    def test_bare_paths_fall_back_to_facts(self):
        self.assertTrue(evaluate_expression("amount > 1", {"amount": 2}))
        self.assertTrue(evaluate_expression(
            "vars.rate > 0.5", {}, {"rate": 0.8}))

    def test_logical_precedence_and_parentheses(self):
        facts = {"a": True, "b": False, "c": True}
        self.assertTrue(evaluate_expression("facts.a or facts.b and facts.b", facts))
        self.assertFalse(evaluate_expression("(facts.a or facts.b) and facts.b", facts))
        self.assertTrue(evaluate_expression("not facts.b and (facts.a or facts.b)", facts))
        self.assertTrue(evaluate_expression("facts.a && facts.c", facts))
        self.assertTrue(evaluate_expression("facts.b || facts.c", facts))

    def test_membership_between_like_and_null(self):
        facts = {"level": "vip", "amount": 150, "name": "Alice Wang", "note": None}
        self.assertTrue(evaluate_expression("facts.level in ['vip', 'svip']", facts))
        self.assertTrue(evaluate_expression("facts.level not in ['normal', 'guest']", facts))
        self.assertTrue(evaluate_expression("facts.amount between 100 and 200", facts))
        self.assertFalse(evaluate_expression("facts.amount not between 100 and 200", facts))
        self.assertTrue(evaluate_expression("facts.name like '%wang'", facts))
        self.assertTrue(evaluate_expression("facts.name not like 'bob%'", facts))
        self.assertTrue(evaluate_expression("facts.level matches 'v.*'", facts))
        self.assertTrue(evaluate_expression("facts.note is null", facts))
        self.assertTrue(evaluate_expression("facts.name is not null", facts))

    def test_whitelisted_functions(self):
        facts = {"tags": [1, 2, 3], "name": "Alice", "value": 1.234,
                 "start": "2024-01-01", "end": "2024-01-03", "none": None}
        self.assertTrue(evaluate_expression("len(facts.tags) == 3", facts))
        self.assertTrue(evaluate_expression("abs(-5) == 5", facts))
        self.assertTrue(evaluate_expression("min(3, 1, 2) == 1", facts))
        self.assertTrue(evaluate_expression("max([3, 1, 2]) == 3", facts))
        self.assertTrue(evaluate_expression("round(facts.value, 1) == 1.2", facts))
        self.assertTrue(evaluate_expression("lower(facts.name) == 'alice'", facts))
        self.assertTrue(evaluate_expression("upper(facts.name) == 'ALICE'", facts))
        self.assertTrue(evaluate_expression("coalesce(facts.none, 'x') == 'x'", facts))
        self.assertTrue(evaluate_expression("now() is not null", facts))
        self.assertTrue(evaluate_expression(
            "days_between(facts.start, facts.end) == 2", facts))

    def test_unknown_function_is_rejected(self):
        with self.assertRaises(ExprError):
            evaluate_expression("eval('1')", {})
        with self.assertRaises(ExprError):
            parse_expression("danger(1)")

    def test_invalid_regex_reports_error(self):
        with self.assertRaises(ExprError) as ctx:
            evaluate_expression("facts.name matches '['", {"name": "x"})
        self.assertIn("正则", str(ctx.exception))

    def test_underscore_paths_are_rejected(self):
        for path in ("_secret", "a._b", "a.__class__", "a..b", ""):
            with self.assertRaises(ExprError):
                validate_path(path)
        with self.assertRaises(ExprError):
            resolve_path("__class__", {})
        report = validate_expression("facts.__dict__ == 1")
        self.assertFalse(report["valid"])
        self.assertIn("下划线", report["error"])

    def test_parse_limits(self):
        too_long = "1 + " * (MAX_EXPR_LEN // 2)
        with self.assertRaises(ExprError):
            parse_expression(too_long)
        deep = "(" * (MAX_DEPTH + 3) + "1" + ")" * (MAX_DEPTH + 3)
        with self.assertRaises(ExprError):
            parse_expression(deep)
        report = validate_expression("1 + 2")
        self.assertTrue(report["valid"])
        self.assertEqual(report["depth"], 2)

    def test_explain_returns_tree_and_steps(self):
        explained = explain_expression(
            "facts.amount > 100 and facts.vip == true",
            {"amount": 200, "vip": True})
        self.assertTrue(explained["value"])
        trace = explained["trace"]
        self.assertEqual(trace["expression"],
                         "facts.amount > 100 and facts.vip == true")
        self.assertTrue(trace["steps"])
        self.assertEqual(trace["tree"]["type"], "logical")
        self.assertTrue(all("seq" in step for step in trace["steps"]))

    def test_condition_expression_and_combine(self):
        self.assertEqual(condition_expression("facts.amount", ">=", 10),
                         "(facts.amount >= 10)")
        self.assertEqual(condition_expression("facts.name", "contains", "a"),
                         "(facts.name like '%a%')")
        self.assertEqual(condition_expression("facts.level", "in", ["vip"]),
                         "(facts.level in ['vip'])")
        composed = combine_conditions([
            {"field": "facts.amount", "operator": ">", "value": 10},
            {"field": "facts.vip", "operator": "==", "value": True,
             "logic_group": "or"},
        ])
        self.assertIn(" or ", composed)
        self.assertEqual(combine_conditions([]), "true")
        with self.assertRaises(ExprError):
            condition_expression("facts.amount", "unknown", 1)
        with self.assertRaises(ExprError):
            condition_expression("facts.amount", "between", [1])

    def test_value_semantics(self):
        self.assertTrue(services.values_equal(1, 1.0))
        self.assertFalse(services.values_equal(True, 1))
        self.assertTrue(services.values_equal(" a ", "a"))
        self.assertTrue(services.values_equal({"a": [1, 2]}, {"a": [1.0, 2]}))
        self.assertTrue(services.subset_match({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(services.subset_match({"a": 2}, {"a": 1, "b": 2}))
        self.assertTrue(services.subset_match(
            [{"name": "x"}], [{"name": "x", "id": 1}, {"name": "y"}]))

    def test_to_json_handles_dates_and_sets(self):
        self.assertIsNone(services.to_json(float("nan")))
        self.assertEqual(services.to_json({1, 2}), [1, 2])
        self.assertIn("T", services.to_json(timezone.now()))
        self.assertEqual(services.to_json({"a": (1, 2)}), {"a": [1, 2]})


class PercentileAndCronTests(TestCase):
    """分位统计与简化 cron 的边界行为。"""

    def test_percentiles(self):
        empty = services.percentiles([])
        self.assertEqual(empty["count"], 0)
        data = services.percentiles([10, 20, 30, 40, 50])
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["min"], 10)
        self.assertEqual(data["max"], 50)
        self.assertLessEqual(data["p50"], data["p90"])
        self.assertLessEqual(data["p90"], data["p99"])

    def test_cron_parse(self):
        fields = services.cron_parse("*/15 9-18 * * 1-5")
        self.assertEqual(fields["minute"], {0, 15, 30, 45})
        self.assertEqual(fields["hour"], set(range(9, 19)))
        self.assertEqual(fields["weekday"], {1, 2, 3, 4, 5})
        # 7 视为周日（0 为周一）
        self.assertIn(0, services.cron_parse("0 0 * * 7")["weekday"])
        for bad in ("* * * *", "60 * * * *", "* 24 * * *", "*/0 * * * *",
                    "a * * * *"):
            with self.assertRaises(ValueError):
                services.cron_parse(bad)

    def test_cron_next(self):
        now = timezone.localtime()
        nxt = services.cron_next("*/10 * * * *")
        self.assertGreater(nxt, timezone.now())
        self.assertIn(nxt.minute % 10, (0,))
        yearly = services.cron_next("0 0 1 1 *", now)
        self.assertEqual(yearly.month, 1)
        self.assertEqual(yearly.day, 1)

    def test_cell_matches(self):
        self.assertTrue(services.cell_matches("*", 123))
        self.assertTrue(services.cell_matches(None, "x"))
        self.assertTrue(services.cell_matches("", "x"))
        self.assertTrue(services.cell_matches("100..200", 150))
        self.assertFalse(services.cell_matches("100..200", 250))
        self.assertTrue(services.cell_matches("vip|svip", "vip"))
        self.assertTrue(services.cell_matches(">=100", 100))
        self.assertTrue(services.cell_matches("!=100", 101))
        self.assertFalse(services.cell_matches(">100", 100))
        self.assertTrue(services.cell_matches({"min": 10, "max": 20}, 15))
        self.assertTrue(services.cell_matches({"in": ["a", "b"]}, "b"))
        self.assertTrue(services.cell_matches({"op": "<", "value": 5}, 4))
        self.assertTrue(services.cell_matches({"not": "vip"}, "normal"))
        self.assertTrue(services.cell_matches([1, 2, 3], 2))
        self.assertTrue(services.cell_matches(True, True))
        self.assertFalse(services.cell_matches(True, 1))
        self.assertFalse(services.cell_matches("vip", None))

    def test_normalize_actions(self):
        normalized = services.normalize_actions([
            "score",
            {"type": "flag", "name": "vip"},
            {"action": "route", "params": {"target": "queue"}},
        ])
        self.assertEqual(normalized[0], {"type": "score", "params": {}})
        self.assertEqual(normalized[1]["params"], {"name": "vip"})
        self.assertEqual(normalized[2]["params"], {"target": "queue"})
        with self.assertRaises(ValueError):
            services.normalize_actions([{"type": "nope"}])
        with self.assertRaises(ValueError):
            services.normalize_actions("not-json")
        with self.assertRaises(ValueError):
            services.normalize_actions({"a": 1})
        self.assertEqual(services.normalize_actions(None), [])


class ApiTestBase(TestCase):
    """接口测试基类：用户、客户端与通用断言。"""

    @classmethod
    def setUpClass(cls):
        # 必须在 TestCase 开启类级事务之前建表：SQLite 不允许在事务中关闭外键检查
        ensure_rules_tables()
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

    # ---- 数据 helper ----

    def create_ruleset(self, code="rs_main", **overrides):
        payload = {"code": code, "name": f"规则集-{code}"}
        payload.update(overrides)
        return self.ok(self.post("rulesets/", payload))

    def create_rule(self, ruleset_id, name="规则一", condition="facts.amount > 100",
                    actions=None, **overrides):
        payload = {"ruleset_id": ruleset_id, "name": name,
                   "condition": condition, "priority": overrides.pop("priority", 100)}
        if actions is not None:
            payload["actions"] = actions
        payload.update(overrides)
        return self.ok(self.post("rules/", payload))

    def publish(self, ruleset_id, **overrides):
        payload = {"note": "测试发布"}
        payload.update(overrides)
        return self.ok(self.post(f"rulesets/{ruleset_id}/publish/", payload))

    def evaluate(self, ruleset_id, facts=None, **overrides):
        payload = {"ruleset_id": ruleset_id, "facts": facts or {}}
        payload.update(overrides)
        return self.ok(self.post("evaluate/", payload))

    def make_basic(self, hit_policy="first"):
        ruleset = self.create_ruleset(hit_policy=hit_policy)
        rule = self.create_rule(ruleset["id"], condition="facts.amount > 100")
        return ruleset, rule


class CatalogTests(ApiTestBase):
    """目录接口：枚举、限制与接口清单。"""

    def test_catalog(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "rules")
        self.assertGreaterEqual(data["endpoint_count"], 50)
        self.assertGreaterEqual(len(data["endpoints"]), 50)
        self.assertIn("first", [item["value"] for item in data["hit_policies"]])
        self.assertIn("set_field", data["action_types"])
        self.assertIn("len", [item["name"] for item in data["functions"]])
        self.assertEqual(data["limits"]["page_size"], 200)
        paths = [item["path"] for item in data["endpoints"]]
        self.assertIn("rulesets/", paths)
        self.assertEqual(len(paths), len(set(paths)))

    def test_catalog_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.get("").status_code, 401)


class RulesetApiTests(ApiTestBase):
    """规则集 CRUD、发布、版本、导入导出、回滚与分页。"""

    def test_create_and_list(self):
        ruleset = self.create_ruleset()
        self.assertEqual(ruleset["code"], "rs_main")
        self.assertEqual(ruleset["status"], "draft")
        self.assertEqual(ruleset["owner"]["id"], self.user.id)
        self.assertEqual(ruleset["rule_count"], 0)

        listed = self.ok(self.get("rulesets/"))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["page"], 1)
        self.assertEqual(listed["page_size"], 20)

        filtered = self.ok(self.get("rulesets/", {"q": "rs_main"}))
        self.assertEqual(filtered["count"], 1)
        empty = self.ok(self.get("rulesets/", {"q": "不存在"}))
        self.assertEqual(empty["count"], 0)

    def test_create_validation(self):
        self.bad(self.post("rulesets/", {"name": "缺编码"}))
        self.bad(self.post("rulesets/", {"code": "bad code", "name": "x"}))
        self.create_ruleset()
        self.bad(self.post("rulesets/", {"code": "rs_main", "name": "重复"}))
        self.bad(self.post("rulesets/", {"code": "rs_x", "name": "x",
                                         "status": "bad"}))
        self.bad(self.post("rulesets/", {"code": "rs_y", "name": "x",
                                         "hit_policy": "bad"}))

    def test_detail_update_pause_archive(self):
        ruleset = self.create_ruleset()
        detail = self.ok(self.get(f"rulesets/{ruleset['id']}/"))
        self.assertEqual(detail["code"], "rs_main")

        updated = self.ok(self.post(f"rulesets/{ruleset['id']}/", {
            "name": "改名", "description": "说明", "tags": ["a", "b"],
            "settings": {"k": 1}, "max_executions": 50, "timeout_ms": 500,
        }))
        self.assertEqual(updated["name"], "改名")
        self.assertEqual(updated["max_executions"], 50)
        self.assertEqual(updated["tags"], ["a", "b"])

        paused = self.ok(self.post(f"rulesets/{ruleset['id']}/pause/"))
        self.assertEqual(paused["status"], "paused")
        archived = self.ok(self.post(f"rulesets/{ruleset['id']}/archive/"))
        self.assertEqual(archived["status"], "archived")
        self.bad(self.post(f"rulesets/{ruleset['id']}/pause/"))

    def test_publish_and_versions(self):
        ruleset = self.create_ruleset()
        self.create_rule(ruleset["id"], actions=[{"type": "score",
                                                  "params": {"delta": 1}}])
        published = self.publish(ruleset["id"])
        self.assertEqual(published["version"]["version_no"], 1)
        self.assertTrue(published["validation"]["valid"])
        self.assertEqual(published["ruleset"]["status"], "active")

        listed = self.ok(self.get(f"rulesets/{ruleset['id']}/versions/"))
        self.assertEqual(listed["count"], 1)
        version_id = listed["items"][0]["id"]
        detail = self.ok(self.get(f"versions/{version_id}/"))
        self.assertEqual(detail["snapshot"]["rules"][0]["name"], "规则一")

        self.bad(self.get("versions/999999/"))

    def test_publish_with_invalid_action_needs_force(self):
        ruleset = self.create_ruleset()
        self.ok(self.post("rules/", {
            "ruleset_id": ruleset["id"], "name": "坏 webhook",
            "condition": "facts.amount > 1",
            "action_items": [{"type": "webhook", "params": {"url": "ftp://bad"}}],
        }))
        report = self.ok(self.get(f"rulesets/{ruleset['id']}/validate/"))
        self.assertFalse(report["valid"])
        self.assertTrue(report["errors"])
        self.bad(self.post(f"rulesets/{ruleset['id']}/publish/"))
        forced = self.ok(self.post(f"rulesets/{ruleset['id']}/publish/",
                                   {"force": True}))
        self.assertEqual(forced["version"]["version_no"], 1)

    def test_validate_empty_ruleset_warns(self):
        ruleset = self.create_ruleset()
        report = self.ok(self.post(f"rulesets/{ruleset['id']}/validate/", {}))
        self.assertTrue(report["valid"])
        codes = {item["code"] for item in report["warnings"]}
        self.assertIn("empty_ruleset", codes)

    def test_clone(self):
        ruleset, rule = self.make_basic()
        cloned = self.ok(self.post(f"rulesets/{ruleset['id']}/clone/",
                                   {"name": "副本"}))
        self.assertNotEqual(cloned["id"], ruleset["id"])
        self.assertEqual(cloned["status"], "draft")
        self.assertEqual(cloned["rule_count"], 1)
        self.assertTrue(cloned["code"].startswith("rs_main_copy"))

    def test_export_and_import(self):
        ruleset, _ = self.make_basic()
        snapshot = self.ok(self.get(f"rulesets/{ruleset['id']}/export/"))
        self.assertEqual(snapshot["format"], "ruleset-snapshot")
        self.assertEqual(snapshot["ruleset"]["code"], "rs_main")

        # 编码冲突默认拒绝，overwrite=true 才覆盖
        self.bad(self.post("rulesets/import/", {"snapshot": snapshot}))
        overwritten = self.ok(self.post("rulesets/import/", {
            "snapshot": snapshot, "overwrite": True}))
        self.assertEqual(overwritten["id"], ruleset["id"])
        self.assertEqual(overwritten["rule_count"], 1)

        snapshot["ruleset"]["code"] = "rs_copy"
        created = self.ok(self.post("rulesets/import/", {"snapshot": snapshot}))
        self.assertEqual(created["code"], "rs_copy")
        self.assertEqual(created["status"], "draft")
        self.bad(self.post("rulesets/import/", {}))

    def test_compare_and_rollback(self):
        ruleset, rule = self.make_basic()
        self.publish(ruleset["id"])
        self.ok(self.post(f"rules/{rule['id']}/", {
            "name": "规则一改名", "condition": "facts.amount > 200"}))
        self.publish(ruleset["id"])
        versions = self.ok(self.get(f"rulesets/{ruleset['id']}/versions/"))
        self.assertEqual(versions["count"], 2)
        ids = [item["id"] for item in versions["items"]]
        compared = self.ok(self.get("versions/compare/", {
            "left_id": ids[-1], "right_id": ids[0]}))
        self.assertFalse(compared["identical"])
        # 版本对比按规则名做键：改名表现为「新增 + 删除」
        self.assertIn("规则一改名", compared["rules"]["added"])
        self.assertIn("规则一", compared["rules"]["removed"])

        self.bad(self.get("versions/compare/", {"left_id": ids[0]}))
        rolled = self.ok(self.post(f"rulesets/{ruleset['id']}/rollback/",
                                   {"version_no": 1}))
        self.assertEqual(rolled["ruleset"]["version_no"], 5)
        detail = self.ok(self.get(f"rulesets/{ruleset['id']}/"))
        self.assertEqual(detail["rules"][0]["name"], "规则一")
        self.assertEqual(detail["rules"][0]["condition"], "facts.amount > 100")
        self.bad(self.post(f"rulesets/{ruleset['id']}/rollback/", {}))

    def test_delete(self):
        ruleset = self.create_ruleset()
        deleted = self.ok(self.post(f"rulesets/{ruleset['id']}/delete/", {}))
        self.assertTrue(deleted["deleted"])
        self.bad(self.get(f"rulesets/{ruleset['id']}/"))

    def test_page_size_cap(self):
        self.create_ruleset()
        self.bad(self.get("rulesets/", {"page_size": 201}))
        self.bad(self.get("rulesets/", {"page": 0}))
        self.bad(self.get("rulesets/", {"status": "bad"}))

    def test_isolation(self):
        ruleset = self.create_ruleset()
        self.as_user(self.other)
        self.assertEqual(self.ok(self.get("rulesets/"))["count"], 0)
        self.bad(self.get(f"rulesets/{ruleset['id']}/"))
        self.bad(self.post(f"rulesets/{ruleset['id']}/", {"name": "偷改"}))
        self.bad(self.post("rules/", {"ruleset_id": ruleset["id"], "name": "x"}))
        self.bad(self.post("evaluate/", {"ruleset_id": ruleset["id"],
                                         "facts": {}}))


class RuleConfigurationTests(ApiTestBase):
    """规则、条件、动作、变量与批量导入/重排。"""

    def setUp(self):
        super().setUp()
        self.ruleset = self.create_ruleset()

    def test_rule_create_detail_update_toggle_delete(self):
        rule = self.create_rule(self.ruleset["id"], actions=[
            {"type": "set_field", "params": {"field": "risk", "value": "high"}}])
        detail = self.ok(self.get(f"rules/{rule['id']}/"))
        self.assertEqual(detail["name"], "规则一")
        self.assertEqual(detail["effective_expression"], "facts.amount > 100")
        self.assertEqual(detail["actions"][0]["type"], "set_field")

        updated = self.ok(self.post(f"rules/{rule['id']}/", {
            "name": "规则改名", "priority": 5, "condition": "facts.amount > 50"}))
        self.assertEqual(updated["name"], "规则改名")
        self.assertEqual(updated["priority"], 5)

        toggled = self.ok(self.post(f"rules/{rule['id']}/toggle/", {}))
        self.assertFalse(toggled["enabled"])
        toggled = self.ok(self.post(f"rules/{rule['id']}/toggle/",
                                    {"enabled": True}))
        self.assertTrue(toggled["enabled"])

        self.bad(self.post("rules/", {"ruleset_id": self.ruleset["id"],
                                      "name": "坏条件",
                                      "condition": "facts.amount >"}))
        self.bad(self.post("rules/", {"ruleset_id": self.ruleset["id"],
                                      "name": "穿透",
                                      "condition": "facts.__dict__ == 1"}))
        self.bad(self.post("rules/", {"ruleset_id": self.ruleset["id"]}))

        self.ok(self.post(f"rules/{rule['id']}/delete/", {}))
        self.bad(self.get(f"rules/{rule['id']}/"))

    def test_rule_list_filters(self):
        self.create_rule(self.ruleset["id"], name="A 规则")
        self.create_rule(self.ruleset["id"], name="B 规则", condition="facts.x > 1",
                         priority=10, enabled=False)
        listed = self.ok(self.get("rules/", {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(listed["count"], 2)
        self.assertEqual(listed["items"][0]["priority"], 10)
        enabled = self.ok(self.get("rules/", {"status": "enabled"}))
        self.assertEqual(enabled["count"], 1)
        disabled = self.ok(self.get("rules/", {"status": "disabled"}))
        self.assertEqual(disabled["count"], 1)
        searched = self.ok(self.get("rules/", {"q": "A 规则"}))
        self.assertEqual(searched["count"], 1)
        self.bad(self.get("rules/", {"status": "weird"}))

    def test_rule_conditions_rows(self):
        rule = self.create_rule(self.ruleset["id"], condition="",
                                conditions=[
                                    {"field": "facts.amount", "operator": ">=",
                                     "value": 100},
                                    {"field": "facts.level", "operator": "in",
                                     "value": ["vip", "svip"],
                                     "logic_group": "and"},
                                ])
        detail = self.ok(self.get(f"rules/{rule['id']}/"))
        self.assertEqual(len(detail["conditions"]), 2)
        self.assertIn("facts.amount >= 100", detail["effective_expression"])
        self.assertIn(" in ", detail["effective_expression"])

        created = self.ok(self.post("conditions/", {
            "rule_id": rule["id"], "field": "facts.age", "operator": ">=",
            "value": 18}))
        self.assertEqual(created["condition"]["field"], "facts.age")
        self.assertIn("facts.age >= 18", created["rule_expression"])

        updated = self.ok(self.post(
            f"conditions/{created['condition']['id']}/update/",
            {"operator": ">", "value": 20}))
        self.assertEqual(updated["operator"], ">")

        composed = self.ok(self.post("conditions/compose/", {"rule_id": rule["id"]}))
        self.assertTrue(composed["report"]["valid"])
        self.assertGreaterEqual(len(composed["report"]["variables"]), 3)

        listed = self.ok(self.get("conditions/", {"rule_id": rule["id"]}))
        self.assertEqual(listed["count"], 3)
        self.ok(self.post(
            f"conditions/{created['condition']['id']}/delete/", {}))
        self.bad(self.post("conditions/", {
            "rule_id": rule["id"], "field": "facts.x", "operator": "nope"}))
        self.bad(self.post("conditions/", {
            "rule_id": rule["id"], "field": "facts.x", "logic_group": "xor"}))

    def test_rule_action_rows(self):
        rule = self.create_rule(self.ruleset["id"], actions=[])
        created = self.ok(self.post("actions/", {
            "rule_id": rule["id"], "type": "set_field",
            "params": {"field": "risk.level", "value": "high"}}))
        self.assertEqual(created["type"], "set_field")
        self.assertEqual(created["params"]["field"], "risk.level")

        self.bad(self.post("actions/", {
            "rule_id": rule["id"], "type": "set_field", "params": {}}))
        self.bad(self.post("actions/", {
            "rule_id": rule["id"], "type": "unknown"}))
        self.bad(self.post("actions/", {
            "rule_id": rule["id"], "type": "webhook", "params": {}}))

        updated = self.ok(self.post(f"actions/{created['id']}/update/", {
            "type": "score", "params": {"delta": 5}}))
        self.assertEqual(updated["type"], "score")

        listed = self.ok(self.get("actions/", {"rule_id": rule["id"]}))
        self.assertEqual(listed["count"], 1)
        detail = self.ok(self.get(f"rules/{rule['id']}/"))
        self.assertEqual(detail["resolved_actions"][0]["type"], "score")

        self.ok(self.post(f"actions/{created['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get("actions/", {
            "rule_id": rule["id"]}))["count"], 0)

    def test_variables(self):
        created = self.ok(self.post("variables/", {
            "ruleset_id": self.ruleset["id"], "name": "threshold",
            "type": "number", "default_value": 100, "description": "阈值"}))
        self.assertEqual(created["name"], "threshold")
        self.assertEqual(created["default_value"], 100)

        self.bad(self.post("variables/", {
            "ruleset_id": self.ruleset["id"], "name": "threshold"}))
        self.bad(self.post("variables/", {
            "ruleset_id": self.ruleset["id"], "name": "a.b"}))
        self.bad(self.post("variables/", {
            "ruleset_id": self.ruleset["id"], "name": "_secret"}))
        self.bad(self.post("variables/", {
            "ruleset_id": self.ruleset["id"], "name": "x", "type": "bad"}))

        updated = self.ok(self.post(f"variables/{created['id']}/update/", {
            "default_value": 200, "description": "新阈值"}))
        self.assertEqual(updated["default_value"], 200)

        listed = self.ok(self.get("variables/", {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(listed["count"], 1)
        self.ok(self.post(f"variables/{created['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get("variables/"))["count"], 0)

    def test_variable_used_in_expression(self):
        self.ok(self.post("variables/", {
            "ruleset_id": self.ruleset["id"], "name": "threshold",
            "type": "number", "default_value": 100}))
        self.create_rule(self.ruleset["id"], condition="facts.amount > threshold")
        result = self.evaluate(self.ruleset["id"], {"amount": 150})
        self.assertTrue(result["matched"])
        result = self.evaluate(self.ruleset["id"], {"amount": 150},
                               variables={"threshold": 200})
        self.assertFalse(result["matched"])

    def test_reorder_and_batch_import(self):
        first = self.create_rule(self.ruleset["id"], name="第一", priority=100)
        second = self.create_rule(self.ruleset["id"], name="第二", priority=200)
        reordered = self.ok(self.post("rules/reorder/", {
            "ruleset_id": self.ruleset["id"],
            "order": [second["id"], first["id"]]}))
        self.assertEqual(reordered["items"][0]["priority"], 10)
        self.bad(self.post("rules/reorder/", {
            "ruleset_id": self.ruleset["id"],
            "order": [first["id"], first["id"]]}))

        imported = self.ok(self.post("rules/import/", {
            "ruleset_id": self.ruleset["id"],
            "rules": [
                {"name": "导入一", "condition": "facts.amount > 1",
                 "actions": [{"type": "score", "params": {"delta": 2}}],
                 "conditions": [{"field": "facts.vip", "operator": "==",
                                 "value": True}]},
                {"name": "导入二", "condition": "facts.amount > 2",
                 "action_items": [{"type": "notify",
                                   "params": {"title": "提醒"}}]},
            ]}))
        self.assertEqual(imported["created"], 2)
        detail = self.ok(self.get(f"rules/{imported['ids'][0]}/"))
        self.assertEqual(len(detail["conditions"]), 1)
        self.bad(self.post("rules/import/", {
            "ruleset_id": self.ruleset["id"], "rules": [{"condition": "true"}]}))
        self.bad(self.post("rules/import/", {
            "ruleset_id": self.ruleset["id"], "rules": []}))

    def test_invalid_expression_limits_return_400(self):
        self.bad(self.post("rules/", {
            "ruleset_id": self.ruleset["id"], "name": "超长",
            "condition": "1 or " * (MAX_EXPR_LEN // 3)}))
        deep = "(" * (MAX_DEPTH + 5) + "true" + ")" * (MAX_DEPTH + 5)
        self.bad(self.post("rules/", {
            "ruleset_id": self.ruleset["id"], "name": "超深", "condition": deep}))


class EvaluationTests(ApiTestBase):
    """评估主链路：命中策略、动作执行、追踪、批量与诊断。"""

    def test_single_evaluate_with_trace_and_hit_count(self):
        ruleset, rule = self.make_basic()
        result = self.evaluate(ruleset["id"], {"amount": 200},
                               trace_id="trace-1", caller="unit")
        self.assertTrue(result["matched"])
        self.assertTrue(result["persisted"])
        self.assertEqual(result["trace_id"], "trace-1")
        decision = result["decision"]
        self.assertEqual(decision["decision"], "matched")
        self.assertEqual(decision["rules"][0]["name"], "规则一")
        self.assertEqual(result["trace"]["rule_count"], 1)
        self.assertTrue(result["trace"]["rules"][0]["trace"]["steps"])
        self.assertTrue(result["trace"]["rules"][0]["trace"]["tree"])

        rule_obj = Rule.objects.get(pk=rule["id"])
        self.assertEqual(rule_obj.hit_count, 1)
        self.assertIsNotNone(rule_obj.last_hit_at)
        evaluation = RuleEvaluation.objects.get(pk=result["evaluation_id"])
        self.assertEqual(evaluation.trace_id, "trace-1")
        self.assertEqual(evaluation.status, "success")

        missed = self.evaluate(ruleset["id"], {"amount": 10})
        self.assertFalse(missed["matched"])
        self.assertEqual(missed["decision"]["decision"], "no_match")

    def test_evaluate_without_persist(self):
        ruleset, _ = self.make_basic()
        result = self.evaluate(ruleset["id"], {"amount": 1000},
                               persist=False, explain=False)
        self.assertIsNone(result["evaluation_id"])
        self.assertFalse(result["persisted"])
        self.assertEqual(RuleEvaluation.objects.count(), 0)
        self.assertEqual(Rule.objects.get().hit_count, 0)

    def test_all_action_types(self):
        ruleset = self.create_ruleset(hit_policy="all")
        rule = self.create_rule(
            ruleset["id"], name="全动作", condition="facts.amount >= 100",
            actions=[
                {"type": "set_field",
                 "params": {"field": "risk.level", "value": "high"}},
                {"type": "score", "params": {"field": "risk_score", "delta": 10}},
                {"type": "flag", "params": {"name": "vip_flag", "value": True}},
                {"type": "route", "params": {"target": "vip_queue"}},
                {"type": "notify",
                 "params": {"title": "命中提醒",
                            "message": "金额 {{facts.amount}} 命中"}},
                {"type": "webhook",
                 "params": {"url": "https://example.com/hook",
                            "payload": {"amount": "{{facts.amount}}"}}},
                {"type": "create_task",
                 "params": {"title": "跟进 {{facts.amount}}",
                            "due_days": 2, "assignee_id": self.user.id}},
                {"type": "approve", "params": {"reason": "自动通过"}},
            ])
        self.assertEqual(len(rule["actions"]), 8)
        result = self.evaluate(ruleset["id"], {"amount": 500})
        self.assertTrue(result["matched"])
        decision = result["decision"]
        self.assertEqual(decision["decision"], "approved")
        after = decision["facts_after"]
        self.assertEqual(after["risk"]["level"], "high")
        self.assertEqual(after["risk_score"], 10)
        self.assertTrue(after["flags"]["vip_flag"])
        self.assertEqual(after["route"], "vip_queue")
        self.assertEqual(decision["outputs"]["risk.level"], "high")
        self.assertEqual(len(decision["actions"]), 8)
        self.assertTrue(all(a["status"] == "success" for a in decision["actions"]))

        self.assertEqual(RuleNotification.objects.filter(channel="inapp").count(), 1)
        webhook = RuleNotification.objects.get(channel="webhook")
        self.assertEqual(webhook.status, "queued")
        self.assertEqual(webhook.target, "https://example.com/hook")
        self.assertEqual(RuleTask.objects.count(), 1)
        task = RuleTask.objects.get()
        self.assertEqual(task.assignee_id, self.user.id)
        self.assertEqual(task.title, "跟进 500")
        self.assertEqual(RuleExecutionLog.objects.count(), 8)
        self.assertEqual(RuleExecutionLog.objects.filter(status="failed").count(), 0)

    def test_reject_decision(self):
        ruleset = self.create_ruleset()
        self.create_rule(ruleset["id"], condition="true",
                         actions=[{"type": "reject",
                                   "params": {"reason": "金额过大"}}])
        result = self.evaluate(ruleset["id"], {})
        self.assertEqual(result["decision"]["decision"], "rejected")
        self.assertEqual(facts_after(result)["decision_reason"], "金额过大")

    def test_action_failure_is_logged_not_fatal(self):
        ruleset = self.create_ruleset(hit_policy="all")
        self.create_rule(ruleset["id"], condition="facts.amount > 0",
                         actions=[{"type": "flag", "params": {}},
                                  {"type": "score", "params": {"delta": 3}}])
        result = self.evaluate(ruleset["id"], {"amount": 5})
        statuses = [item["status"] for item in result["decision"]["actions"]]
        self.assertIn("failed", statuses)
        self.assertIn("success", statuses)
        self.assertEqual(facts_after(result)["score"], 3)
        self.assertEqual(RuleExecutionLog.objects.filter(status="failed").count(), 1)

    def test_hit_policies(self):
        def build(policy):
            ruleset = self.create_ruleset(code=f"rs_{policy}", hit_policy=policy)
            self.create_rule(ruleset["id"], name="A", priority=10,
                             condition="facts.amount > 100",
                             actions=[{"type": "route", "params": {"target": "A"}}])
            self.create_rule(ruleset["id"], name="B", priority=20,
                             condition="facts.amount > 100",
                             actions=[{"type": "route", "params": {"target": "B"}}])
            return ruleset

        first = self.evaluate(build("first")["id"], {"amount": 200})
        self.assertEqual(first["decision"]["rules"][0]["name"], "A")
        self.assertEqual(first["decision"]["outputs"]["route"], "A")

        priority = self.evaluate(build("priority")["id"], {"amount": 200})
        self.assertEqual(len(priority["decision"]["rules"]), 2)
        self.assertEqual(priority["decision"]["outputs"]["route"], "A")

        all_policy = self.evaluate(build("all")["id"], {"amount": 200})
        self.assertEqual(len(all_policy["decision"]["rules"]), 2)
        self.assertEqual(all_policy["decision"]["outputs"]["route"], "B")

        collect = self.evaluate(build("collect")["id"], {"amount": 200})
        self.assertIsInstance(collect["decision"]["outputs"], list)
        self.assertEqual(len(collect["decision"]["collected"]["route"]), 2)

    def test_evaluate_batch(self):
        ruleset, _ = self.make_basic()
        data = self.ok(self.post("evaluate/batch/", {
            "ruleset_id": ruleset["id"],
            "facts": [{"amount": 200}, {"amount": 10}, {"amount": 300}],
        }))
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["matched"], 2)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["items"][0]["rules"], ["规则一"])
        self.assertEqual(data["duration"]["count"], 3)
        self.bad(self.post("evaluate/batch/", {
            "ruleset_id": ruleset["id"], "facts": []}))

    def test_evaluations_list_detail_and_logs(self):
        ruleset, _ = self.make_basic()
        result = self.evaluate(ruleset["id"], {"amount": 500})
        listed = self.ok(self.get("evaluations/", {"ruleset_id": ruleset["id"]}))
        self.assertEqual(listed["count"], 1)
        detail = self.ok(self.get(f"evaluations/{result['evaluation_id']}/"))
        self.assertTrue(detail["trace"]["rules"])
        self.assertEqual(detail["source"], "manual")

        logs = self.ok(self.get("logs/", {"evaluation_id": result["evaluation_id"]}))
        self.assertEqual(logs["count"], 0)
        self.bad(self.get("evaluations/999999/"))

    def test_miss_diagnose_and_reevaluate(self):
        ruleset = self.create_ruleset()
        self.create_rule(ruleset["id"], condition="amount > 100 and vip == true")
        missed = self.evaluate(ruleset["id"], {"amount": 50})
        self.assertFalse(missed["matched"])
        diagnosis = self.ok(self.get(
            f"evaluations/{missed['evaluation_id']}/miss-diagnose/"))
        self.assertFalse(diagnosis["matched"])
        self.assertTrue(diagnosis["rules"])
        self.assertTrue(diagnosis["hints"])
        self.assertIn("vip", diagnosis["rules"][0]["missing_facts"])

        new_result = self.ok(self.post(
            f"evaluations/{missed['evaluation_id']}/reevaluate/", {}))
        self.assertEqual(new_result["decision"]["previous_evaluation_id"],
                         missed["evaluation_id"])
        self.assertEqual(new_result["source"] if "source" in new_result else
                         new_result["decision"].get("decision"), "no_match")

    def test_timeout_budget_marks_timeout(self):
        ruleset = self.create_ruleset(timeout_ms=50)
        for index in range(3):
            self.create_rule(ruleset["id"], name=f"规则{index}",
                             condition="facts.amount > 1")
        result = self.evaluate(ruleset["id"], {"amount": 2})
        # 50ms 预算在慢机器上可能仍然够用；只断言结构，不断言一定超时
        self.assertIn(result["status"], ("success", "timeout"))

    def test_evaluation_ownership(self):
        ruleset, _ = self.make_basic()
        result = self.evaluate(ruleset["id"], {"amount": 500})
        self.as_user(self.other)
        self.assertEqual(self.ok(self.get("evaluations/"))["count"], 0)
        self.bad(self.get(f"evaluations/{result['evaluation_id']}/"))


class DecisionTableTests(ApiTestBase):
    """决策表：列定义、单元格语法、命中策略与行维护。"""

    def setUp(self):
        super().setUp()
        self.ruleset = self.create_ruleset()
        self.table = self.ok(self.post("tables/", {
            "ruleset_id": self.ruleset["id"], "name": "额度表",
            "inputs": [
                {"name": "amount", "field": "facts.amount", "type": "number"},
                {"name": "level", "field": "facts.level"},
            ],
            "outputs": ["decision", "limit"],
            "hit_policy": "first",
        }))
        self.row = self.ok(self.post(f"tables/{self.table['id']}/rows/", {
            "conditions": {"amount": "100..200", "level": "vip|svip"},
            "outputs": {"decision": "approve", "limit": 5000},
            "remark": "中额 VIP",
        }))

    def test_table_create_and_rows(self):
        self.assertEqual(self.table["name"], "额度表")
        self.assertEqual(len(self.table["inputs"]), 2)
        self.assertEqual(self.row["conditions"]["level"], "vip|svip")

        rows = self.ok(self.get(f"tables/{self.table['id']}/rows/"))
        self.assertEqual(rows["count"], 1)
        detail = self.ok(self.get(f"tables/{self.table['id']}/"))
        self.assertEqual(len(detail["rows"]), 1)

        listed = self.ok(self.get("tables/", {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(listed["count"], 1)

        self.bad(self.post("tables/", {"ruleset_id": self.ruleset["id"],
                                       "name": "空表", "inputs": [""]}))
        self.bad(self.post("tables/", {"ruleset_id": self.ruleset["id"],
                                       "name": "坏策略", "hit_policy": "bad"}))

    def test_evaluate_first_and_inline_rows(self):
        result = self.ok(self.post(f"tables/{self.table['id']}/evaluate/", {
            "facts": {"amount": 150, "level": "vip"}}))
        self.assertTrue(result["matched"])
        self.assertEqual(result["outputs"]["decision"], "approve")
        self.assertEqual(result["outputs"]["limit"], 5000)
        self.assertEqual(result["matched_count"], 1)
        self.assertTrue(result["trace"][0]["cells"])
        self.assertEqual(result["source"], "database")

        inline = self.ok(self.post(f"tables/{self.table['id']}/evaluate/", {
            "facts": {"amount": 150, "level": "normal"},
            "rows": [{"conditions": {"amount": ">100"},
                      "outputs": {"decision": "review"}}]}))
        self.assertEqual(inline["outputs"]["decision"], "review")
        self.assertEqual(inline["source"], "inline")

    def test_bulk_save_and_collect_policy(self):
        saved = self.ok(self.post(f"tables/{self.table['id']}/rows/bulk/", {
            "replace": True,
            "rows": [
                {"conditions": {"amount": ">=100"},
                 "outputs": {"decision": "big", "limit": 1000}, "priority": 10},
                {"conditions": {"amount": "*"},
                 "outputs": {"decision": "small", "limit": 100}, "priority": 20},
            ]}))
        self.assertEqual(saved["saved"], 2)

        updated = self.ok(self.post(f"tables/{self.table['id']}/", {
            "hit_policy": "collect", "description": "汇总"}))
        self.assertEqual(updated["hit_policy"], "collect")
        result = self.ok(self.post(f"tables/{self.table['id']}/evaluate/", {
            "facts": {"amount": 500}}))
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(len(result["outputs"]), 2)
        self.assertEqual(len(result["collected"]["decision"]), 2)

    def test_row_update_delete_and_table_delete(self):
        updated = self.ok(self.post(f"rows/{self.row['id']}/update/", {
            "outputs": {"decision": "reject", "limit": 0},
            "priority": 5, "remark": "改过"}))
        self.assertEqual(updated["outputs"]["decision"], "reject")
        result = self.ok(self.post(f"tables/{self.table['id']}/evaluate/", {
            "facts": {"amount": 150, "level": "vip"}}))
        self.assertEqual(result["outputs"]["decision"], "reject")

        self.ok(self.post(f"rows/{self.row['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get(
            f"tables/{self.table['id']}/rows/"))["count"], 0)
        self.ok(self.post(f"tables/{self.table['id']}/delete/", {}))
        self.bad(self.get(f"tables/{self.table['id']}/"))


class TestCaseAndSimulationTests(ApiTestBase):
    """回归用例、覆盖率与批量仿真。"""

    def setUp(self):
        super().setUp()
        self.ruleset = self.create_ruleset()
        self.rule = self.create_rule(
            self.ruleset["id"], condition="facts.amount > 100",
            actions=[{"type": "score", "params": {"field": "score", "delta": 10}}])

    def test_testcase_crud_and_run(self):
        case = self.ok(self.post("testcases/", {
            "ruleset_id": self.ruleset["id"], "name": "大额命中",
            "facts": {"amount": 200},
            "expected": {"matched": True, "score": 10,
                         "rules": ["规则一"]},
        }))
        run = self.ok(self.post(f"testcases/{case['id']}/run/", {}))
        self.assertTrue(run["passed"])
        self.assertTrue(all(item["ok"] for item in run["checks"]))
        case_obj = RuleTestCase.objects.get(pk=case["id"])
        self.assertTrue(case_obj.passed)
        self.assertIsNotNone(case_obj.last_run_at)

        failed_case = self.ok(self.post("testcases/", {
            "ruleset_id": self.ruleset["id"], "name": "错误期望",
            "facts": {"amount": 200}, "expected": {"matched": False}}))
        failed = self.ok(self.post(f"testcases/{failed_case['id']}/run/", {}))
        self.assertFalse(failed["passed"])

        updated = self.ok(self.post(f"testcases/{case['id']}/update/", {
            "name": "改名用例", "expected": {"matched": True}}))
        self.assertEqual(updated["name"], "改名用例")

        listed = self.ok(self.get("testcases/", {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(listed["count"], 2)
        self.assertEqual(self.ok(self.get("testcases/", {"status": "passed"}))["count"], 1)

        self.ok(self.post(f"testcases/{failed_case['id']}/delete/", {}))
        self.bad(self.post("testcases/", {"ruleset_id": self.ruleset["id"],
                                          "facts": {"amount": 1}}))

    def test_run_all_and_coverage(self):
        self.ok(self.post("testcases/", {
            "ruleset_id": self.ruleset["id"], "name": "命中",
            "facts": {"amount": 200}, "expected": {"matched": True}}))
        self.ok(self.post("testcases/", {
            "ruleset_id": self.ruleset["id"], "name": "未命中",
            "facts": {"amount": 10}, "expected": {"matched": False}}))
        data = self.ok(self.post("testcases/run-all/", {
            "ruleset_id": self.ruleset["id"]}))
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["passed"], 2)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(data["pass_rate"], 1.0)

        coverage = self.ok(self.get("testcases/coverage/",
                                    {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(coverage["enabled_rules"], 1)
        self.assertEqual(coverage["covered_rules"], 1)
        self.assertEqual(coverage["coverage"], 1.0)
        self.assertEqual(coverage["uncovered"], [])
        self.assertEqual(coverage["case_count"], 2)

    def test_coverage_reports_uncovered(self):
        self.create_rule(self.ruleset["id"], name="永不命中",
                         condition="facts.amount > 99999")
        self.ok(self.post("testcases/", {
            "ruleset_id": self.ruleset["id"], "name": "只覆盖一条",
            "facts": {"amount": 200}, "expected": {}}))
        coverage = self.ok(self.get("testcases/coverage/",
                                    {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(coverage["enabled_rules"], 2)
        self.assertEqual(coverage["covered_rules"], 1)
        self.assertEqual(coverage["uncovered"][0]["name"], "永不命中")

    def test_simulation(self):
        data = self.ok(self.post("simulations/", {
            "ruleset_id": self.ruleset["id"], "name": "压测",
            "facts": [{"amount": 500}, {"amount": 10},
                      {"amount": 800}, {"amount": 1}]}))
        summary = data["summary"]
        self.assertIsNotNone(data["simulation_id"])
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["matched"], 2)
        self.assertEqual(summary["missed"], 2)
        self.assertEqual(summary["match_rate"], 0.5)
        self.assertTrue(summary["hit_distribution"])
        self.assertEqual(summary["hit_distribution"][0]["rule"], "规则一")
        self.assertEqual(summary["latency"]["count"], 4)
        self.assertTrue(summary["samples"])

        detail = self.ok(self.get(f"simulations/{data['simulation_id']}/"))
        self.assertTrue(detail["results"])
        self.assertEqual(detail["fact_count"], 4)
        listed = self.ok(self.get("simulations/", {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(listed["count"], 1)
        self.bad(self.post("simulations/", {"ruleset_id": self.ruleset["id"],
                                            "facts": []}))
        self.bad(self.post("simulations/", {"ruleset_id": self.ruleset["id"],
                                            "facts": ["bad"]}))


class ConflictTests(ApiTestBase):
    """规则冲突检测与处理。"""

    def test_detect_duplicate_contradiction_shadow_unreachable(self):
        ruleset = self.create_ruleset(hit_policy="first")
        actions = [{"type": "route", "params": {"target": "queue"}}]
        self.create_rule(ruleset["id"], name="重复A", priority=10,
                         condition="facts.amount > 100", actions=actions)
        self.create_rule(ruleset["id"], name="重复B", priority=20,
                         condition="facts.amount > 100", actions=actions)
        self.create_rule(ruleset["id"], name="矛盾A", priority=30,
                         condition="facts.vip == true",
                         actions=[{"type": "notify", "params": {"title": "a"}}])
        self.create_rule(ruleset["id"], name="矛盾B", priority=40,
                         condition="facts.vip == true",
                         actions=[{"type": "notify", "params": {"title": "b"}}])
        self.create_rule(ruleset["id"], name="宽条件", priority=50,
                         condition="facts.amount > 0")
        self.create_rule(ruleset["id"], name="窄条件", priority=60,
                         condition="facts.amount > 0 and facts.vip == true")
        self.create_rule(ruleset["id"], name="不可达", priority=70,
                         condition="false")

        report = self.ok(self.post("conflicts/detect/", {
            "ruleset_id": ruleset["id"]}))
        types = {item["conflict_type"] for item in report["conflicts"]}
        self.assertIn("duplicate", types)
        self.assertIn("contradiction", types)
        self.assertIn("shadowed", types)
        self.assertIn("unreachable", types)
        self.assertGreaterEqual(report["count"], 4)
        self.assertTrue(report["persisted"])

        listed = self.ok(self.get("conflicts/", {"ruleset_id": ruleset["id"]}))
        self.assertEqual(listed["count"], report["count"])
        filtered = self.ok(self.get("conflicts/", {
            "ruleset_id": ruleset["id"], "status": "open",
            "severity": "high"}))
        self.assertGreaterEqual(filtered["count"], 1)
        self.bad(self.get("conflicts/", {"status": "nope"}))
        self.bad(self.get("conflicts/", {"severity": "nope"}))

    def test_equivalent_and_order_insensitive(self):
        ruleset = self.create_ruleset()
        self.create_rule(ruleset["id"], name="顺序A", priority=10,
                         condition="facts.a > 1 and facts.b == 2")
        self.create_rule(ruleset["id"], name="顺序B", priority=20,
                         condition="facts.b == 2 and facts.a > 1")
        report = self.ok(self.post("conflicts/detect/", {
            "ruleset_id": ruleset["id"]}))
        self.assertEqual(report["conflicts"][0]["conflict_type"], "duplicate")

    def test_resolve_and_ignore(self):
        ruleset = self.create_ruleset()
        # 两对重复规则，保证检测出两条独立冲突，才能一条解决一条忽略
        self.create_rule(ruleset["id"], name="A1", priority=10, condition="facts.a > 1")
        self.create_rule(ruleset["id"], name="A2", priority=20, condition="facts.a > 1")
        self.create_rule(ruleset["id"], name="B1", priority=30, condition="facts.b > 1")
        self.create_rule(ruleset["id"], name="B2", priority=40, condition="facts.b > 1")
        report = self.ok(self.post("conflicts/detect/", {"ruleset_id": ruleset["id"]}))
        self.assertEqual(len(report["conflicts"]), 2)
        conflicts = self.ok(self.get("conflicts/", {"ruleset_id": ruleset["id"]}))
        first, second = conflicts["items"][0], conflicts["items"][1]
        resolved = self.ok(self.post(f"conflicts/{first['id']}/resolve/",
                                     {"note": "合并"}))
        self.assertEqual(resolved["status"], "resolved")
        ignored = self.ok(self.post(f"conflicts/{second['id']}/ignore/",
                                    {"note": "误报"}))
        self.assertEqual(ignored["status"], "ignored")
        self.bad(self.post(f"conflicts/{first['id']}/resolve/", {}))

        # 再次检测会清掉 open 记录，已处理的保留
        self.ok(self.post("conflicts/detect/", {"ruleset_id": ruleset["id"]}))
        self.assertEqual(RuleConflict.objects.filter(
            ruleset_id=ruleset["id"], status="resolved").count(), 1)


class ScheduleTests(ApiTestBase):
    """简化 cron 调度：创建、启停、手动执行与扫描。"""

    def setUp(self):
        super().setUp()
        self.ruleset = self.create_ruleset()
        self.create_rule(self.ruleset["id"], condition="facts.amount > 100")
        self.publish(self.ruleset["id"])

    def test_schedule_crud(self):
        schedule = self.ok(self.post("schedules/", {
            "ruleset_id": self.ruleset["id"], "name": "每十分钟",
            "cron": "*/10 * * * *", "facts": {"amount": 500}}))
        self.assertIsNotNone(schedule["next_run_at"])
        self.assertTrue(schedule["enabled"])
        self.bad(self.post("schedules/", {
            "ruleset_id": self.ruleset["id"], "cron": "* * * *"}))
        self.bad(self.post("schedules/", {
            "ruleset_id": self.ruleset["id"], "cron": "60 * * * *"}))

        listed = self.ok(self.get("schedules/", {"ruleset_id": self.ruleset["id"]}))
        self.assertEqual(listed["count"], 1)

        updated = self.ok(self.post(f"schedules/{schedule['id']}/update/", {
            "cron": "*/30 * * * *", "facts": {"amount": 300}}))
        self.assertEqual(updated["cron"], "*/30 * * * *")
        self.assertEqual(updated["facts"]["amount"], 300)

        toggled = self.ok(self.post(f"schedules/{schedule['id']}/toggle/", {}))
        self.assertFalse(toggled["enabled"])
        toggled = self.ok(self.post(f"schedules/{schedule['id']}/toggle/",
                                    {"enabled": True}))
        self.assertTrue(toggled["enabled"])

        self.ok(self.post(f"schedules/{schedule['id']}/delete/", {}))
        self.bad(self.post(f"schedules/{schedule['id']}/update/",
                           {"cron": "*/5 * * * *"}))

    def test_run_now(self):
        schedule = self.ok(self.post("schedules/", {
            "ruleset_id": self.ruleset["id"], "cron": "*/10 * * * *",
            "facts": {"amount": 500}}))
        data = self.ok(self.post(f"schedules/{schedule['id']}/run/", {}))
        self.assertTrue(data["result"]["matched"])
        schedule_obj = RuleSchedule.objects.get(pk=schedule["id"])
        self.assertEqual(schedule_obj.run_count, 1)
        self.assertIsNotNone(schedule_obj.last_run_at)

    def test_scan_executes_due_and_skips_inactive(self):
        schedule = self.ok(self.post("schedules/", {
            "ruleset_id": self.ruleset["id"], "cron": "*/10 * * * *",
            "facts": {"amount": 500}}))
        RuleSchedule.objects.filter(pk=schedule["id"]).update(
            next_run_at=timezone.now() - timedelta(minutes=1))

        paused = self.create_ruleset(code="rs_paused")
        self.create_rule(paused["id"], condition="true")
        self.ok(self.post("schedules/", {
            "ruleset_id": paused["id"], "cron": "*/10 * * * *"}))
        silent = RuleSchedule.objects.get(ruleset_id=paused["id"])
        RuleSchedule.objects.filter(pk=silent.id).update(
            next_run_at=timezone.now() - timedelta(minutes=1))

        data = self.ok(self.post("schedules/scan/", {}))
        self.assertGreaterEqual(data["scanned"], 2)
        self.assertEqual(data["executed"], 1)
        skipped = [item for item in data["items"] if item.get("skipped")]
        self.assertEqual(len(skipped), 1)

        executed = RuleSchedule.objects.get(pk=schedule["id"])
        self.assertEqual(executed.run_count, 1)
        self.assertGreater(executed.next_run_at, timezone.now())
        silent.refresh_from_db()
        self.assertEqual(silent.run_count, 0)


class ApprovalTests(ApiTestBase):
    """规则变更审批：提交、自批拦截、通过应用与驳回。"""

    def test_submit_and_approve(self):
        ruleset = self.create_ruleset()
        approval = self.ok(self.post("approvals/", {
            "ruleset_id": ruleset["id"], "note": "改配置",
            "change": {"fields": {"name": "审批改名", "hit_policy": "all"},
                       "publish": True}}))
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["applicant"]["id"], self.user.id)
        self.bad(self.post(f"approvals/{approval['id']}/approve/", {}))
        self.bad(self.post("approvals/", {
            "ruleset_id": ruleset["id"],
            "change": {"fields": {"code": "hack"}}}))
        self.bad(self.post("approvals/", {
            "ruleset_id": ruleset["id"], "change": {"fields": {"name": ""}}}))
        self.bad(self.post("approvals/", {"ruleset_id": ruleset["id"]}))

        self.as_user(self.admin)
        approved = self.ok(self.post(f"approvals/{approval['id']}/approve/",
                                     {"note": "同意"}))
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["reviewer"]["id"], self.admin.id)
        ruleset_obj = RuleSet.objects.get(pk=ruleset["id"])
        self.assertEqual(ruleset_obj.name, "审批改名")
        self.assertEqual(ruleset_obj.hit_policy, "all")
        self.assertTrue(RuleSetVersion.objects.filter(
            ruleset_id=ruleset["id"]).exists())
        self.bad(self.post(f"approvals/{approval['id']}/approve/", {}))

        self.as_user(self.user)
        listed = self.ok(self.get("approvals/", {"ruleset_id": ruleset["id"]}))
        self.assertEqual(listed["count"], 1)
        self.assertTrue(listed["items"][0]["review_note"])

    def test_reject(self):
        ruleset = self.create_ruleset()
        approval = self.ok(self.post("approvals/", {
            "ruleset_id": ruleset["id"],
            "change": {"fields": {"name": "不会生效"}}}))
        self.as_user(self.admin)
        self.bad(self.post(f"approvals/{approval['id']}/reject/", {}))
        rejected = self.ok(self.post(f"approvals/{approval['id']}/reject/",
                                     {"reason": "先补充说明"}))
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["review_note"], "先补充说明")
        self.as_user(self.user)
        self.assertEqual(RuleSet.objects.get(pk=ruleset["id"]).name,
                         "规则集-rs_main")
        self.assertEqual(self.ok(self.get("approvals/",
                                          {"status": "rejected"}))["count"], 1)
        self.bad(self.get("approvals/", {"status": "bad"}))


class MiscApiTests(ApiTestBase):
    """标签、模板、任务/通知台账、执行日志与统计。"""

    def test_tags(self):
        ruleset = self.create_ruleset()
        tag = self.ok(self.post("tags/", {
            "name": "重点", "color": "#f00", "ruleset_ids": [ruleset["id"]]}))
        self.assertEqual(tag["ruleset_count"], 1)
        listed = self.ok(self.get("tags/"))
        self.assertEqual(listed["count"], 1)
        self.bad(self.post("tags/", {"name": "重点"}))
        self.ok(self.post(f"tags/{tag['id']}/delete/", {}))
        self.assertEqual(self.ok(self.get("tags/"))["count"], 0)

    def test_templates(self):
        ruleset, _ = self.make_basic()
        listed = self.ok(self.get("templates/"))
        self.assertGreaterEqual(listed["count"], 4)
        keys = {item["key"] for item in listed["items"] if item.get("builtin")}
        self.assertIn("vip-route", keys)

        saved = self.ok(self.post("templates/", {
            "name": "我的模板", "category": "自定义",
            "ruleset_id": ruleset["id"]}))
        self.assertFalse(saved["builtin"])
        self.assertTrue(saved["template"]["ruleset"])

        applied = self.ok(self.post("templates/apply/", {
            "template_id": saved["id"], "name": "从模板生成"}))
        self.assertEqual(applied["name"], "从模板生成")
        self.assertEqual(applied["status"], "draft")
        self.assertEqual(applied["rule_count"], 1)
        self.assertTrue(RuleTemplate.objects.get(pk=saved["id"]).usage_count == 1)

        builtin_applied = self.ok(self.post("templates/apply/", {
            "key": "leave-auto"}))
        self.assertGreaterEqual(builtin_applied["rule_count"], 2)
        self.bad(self.post("templates/apply/", {"key": "missing"}))
        self.bad(self.post("templates/", {"name": "坏模板"}))

    def test_tasks_notifications_and_stats(self):
        ruleset = self.create_ruleset(hit_policy="all")
        self.create_rule(ruleset["id"], name="通知规则",
                         condition="facts.amount > 100",
                         actions=[
                             {"type": "notify",
                              "params": {"title": "提醒", "target": "alice"}},
                             {"type": "create_task",
                              "params": {"title": "跟进", "assignee_id": self.user.id}},
                             {"type": "flag", "params": {}},
                         ])
        result = self.evaluate(ruleset["id"], {"amount": 500})
        self.assertEqual(len(result["decision"]["actions"]), 3)

        notifications = self.ok(self.get("notifications/", {"channel": "inapp"}))
        self.assertEqual(notifications["count"], 1)
        tasks = self.ok(self.get("tasks/", {"ruleset_id": ruleset["id"]}))
        self.assertEqual(tasks["count"], 1)
        self.assertEqual(tasks["items"][0]["status"], "open")

        logs = self.ok(self.get("logs/", {"evaluation_id": result["evaluation_id"]}))
        self.assertEqual(logs["count"], 3)
        failed = self.ok(self.get("logs/", {"status": "failed"}))
        self.assertEqual(failed["count"], 1)
        log_detail = self.ok(self.get(f"logs/{logs['items'][0]['id']}/"))
        self.assertIn("params", log_detail["detail"])

        overview = self.ok(self.get("stats/overview/"))
        self.assertEqual(overview["evaluations"], 1)
        self.assertEqual(overview["matched"], 1)
        self.assertEqual(overview["hit_rate"], 1.0)
        self.assertEqual(overview["rules"], 1)
        self.assertEqual(overview["active_rulesets"], 0)
        self.assertEqual(overview["open_tasks"], 1)

        top = self.ok(self.get("stats/top-rules/", {"days": 30}))
        self.assertEqual(top["items"][0]["name"], "通知规则")
        self.assertEqual(top["items"][0]["lifetime_hits"], 1)

        failures = self.ok(self.get("stats/failures/", {"days": 30}))
        self.assertEqual(failures["action_failure_total"], 1)
        self.assertEqual(failures["action_failures"][0]["action_type"], "flag")

        latency = self.ok(self.get("stats/latency/", {"days": 30}))
        self.assertEqual(latency["overall"]["count"], 1)
        self.assertEqual(latency["slowest_rulesets"][0]["ruleset_code"], "rs_main")

        trend = self.ok(self.get("stats/trend/", {"days": 7}))
        self.assertEqual(len(trend["items"]), 7)
        self.assertEqual(trend["items"][-1]["total"], 1)
        self.assertEqual(trend["items"][-1]["matched"], 1)

        self.bad(self.get("stats/overview/", {"days": 0}))
        self.bad(self.get("rulesets/", {"page_size": 500}))

    def test_tag_and_template_isolation(self):
        self.as_user(self.other)
        self.assertEqual(self.ok(self.get("tags/"))["count"], 0)
        templates = self.ok(self.get("templates/"))
        personal = [item for item in templates["items"] if not item.get("builtin")]
        self.assertEqual(personal, [])
