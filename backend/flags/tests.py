# -*- coding: utf-8 -*-
"""flags 测试：项目/环境、开关生命周期、确定性评估、细分/灰度/定向/变体、
实验入组与曝光幂等、实验统计、依赖与护栏、受众、统计与行级权限。

运行：venv/Scripts/python.exe manage.py test flags -v 1
（测试库为内存 sqlite，不触碰开发库，也不发起任何网络请求。）

注意：项目内 ``backend/code`` 包会遮蔽标准库 ``code``，直接执行 manage.py test
会在导入 django.test.runner 的 pdb 时报错。本文件与 billing 保持一致，在
TestClass 里按依赖顺序为测试库补建本应用的表（flags 的 migrations 包为空，
Django 不会自动建表）。等价运行方式：

    python -c "import sys,os; p=list(sys.path); sys.path=[x for x in p if not x.replace(chr(92),'/').endswith('/backend') and x not in ('','.')]; import code; sys.modules['code']=code; import pdb, django.test.runner; sys.path=p; del sys.modules['code']; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); from django.core.management import execute_from_command_line as ex; ex(['manage.py','test','flags','-v','1'])"

这些测试只使用 APIClient.force_authenticate，不依赖 JWT 签发，也不依赖迁移。
"""
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from flags import services

User = get_user_model()

BASE = "/api/flags/"


def ensure_flags_tables():
    """测试库补建 flags 表（只作用于测试库，不影响开发/生产迁移策略）。"""
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in apps.get_app_config("flags").get_models():
            if model._meta.db_table not in existing:
                editor.create_model(model)


class FlagsApiBase(TestCase):
    """接口测试基类：三个账号 + 通用断言 + 数据工厂。"""

    @classmethod
    def setUpClass(cls):
        # 必须在 TestCase 开启类级事务之前建表：SQLite 不允许在事务中改 schema
        ensure_flags_tables()
        super().setUpClass()

    def setUp(self):
        services.clear_cache()
        self.user = User.objects.create_user(
            username="alice", password="pass1234", nickname="爱丽丝")
        self.other = User.objects.create_user(
            username="bob", password="pass1234", nickname="鲍勃")
        self.admin = User.objects.create_user(
            username="root", password="pass1234", is_staff=True, is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    # ---- 请求 helper ----

    def get(self, path, params=None):
        return self.client.get(BASE + path, params or {})

    def post(self, path, data=None):
        return self.client.post(BASE + path, data if data is not None else {}, format="json")

    def as_user(self, user):
        self.client.force_authenticate(user)

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

    def assert_page(self, data):
        self.assertEqual(set(data.keys()), {"items", "count", "page", "page_size"})
        self.assertIsInstance(data["items"], list)

    # ---- 数据工厂 ----

    def make_project(self, key="alpha", name="Alpha", **extra):
        payload = {"key": key, "name": name}
        payload.update(extra)
        return self.ok(self.post("projects/", payload))

    def make_env(self, project_id, key="staging", name="预发", env_type="staging"):
        return self.ok(self.post("environments/", {
            "project_id": project_id, "key": key, "name": name, "env_type": env_type}))

    def default_env(self, project_id):
        detail = self.ok(self.get(f"projects/{project_id}/"))
        return detail["environments"][0]

    def make_flag(self, project_id, environment_id, key="new_checkout", **extra):
        payload = {
            "project_id": project_id,
            "environment_id": environment_id,
            "key": key,
            "name": f"开关-{key}",
        }
        payload.update(extra)
        return self.ok(self.post("flags/", payload))

    def make_segment(self, project_id, name="beta", rules=None, **extra):
        # rules=None 表示用默认国家规则；显式传 [] 时保持为空（只测结构化规则）
        if rules is None:
            rules = [{"field": "user.country", "operator": "in",
                      "value": ["US", "CA"]}]
        payload = {"project_id": project_id, "name": name, "rules": rules}
        payload.update(extra)
        return self.ok(self.post("segments/", payload))

    def evaluate(self, flag_id, user_key="u1", context=None, **extra):
        payload = {"flag_id": flag_id, "user_key": user_key, "context": context or {}}
        payload.update(extra)
        return self.ok(self.post("evaluate/", payload))


class CatalogTests(FlagsApiBase):
    def test_auth_required(self):
        client = APIClient()
        response = client.get(BASE)
        self.assertIn(response.status_code, (401, 403))

    def test_catalog_contract(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "flags")
        self.assertEqual(data["pagination"]["page_size_max"], 200)
        self.assertEqual(len(data["operators"]), 14)
        self.assertGreaterEqual(len(data["endpoints"]), 52)
        self.assertIn("flag_types", data["enums"])
        self.assertEqual(data["counts"]["flags"], 0)

    def test_catalog_counts_after_create(self):
        project = self.make_project()
        env = self.default_env(project["id"])
        self.make_flag(project["id"], env["id"])
        data = self.ok(self.get(""))
        self.assertEqual(data["counts"]["flags"], 1)
        paths = {row["path"] for row in data["endpoints"]}
        self.assertIn("evaluate/", paths)

    def test_model_count(self):
        models = list(apps.get_app_config("flags").get_models())
        self.assertGreaterEqual(len(models), 17)


class ProjectEnvironmentTests(FlagsApiBase):
    def test_create_project_with_default_env(self):
        project = self.make_project()
        self.assertEqual(project["key"], "alpha")
        self.assertEqual(project["environment_count"], 1)
        detail = self.ok(self.get(f"projects/{project['id']}/"))
        self.assertEqual(len(detail["environments"]), 1)
        self.assertEqual(detail["environments"][0]["key"], "dev")

    def test_duplicate_project_key(self):
        self.make_project()
        self.bad(self.post("projects/", {"key": "alpha", "name": "另一个"}))

    def test_project_list_pagination_contract(self):
        self.make_project(key="p1")
        self.make_project(key="p2")
        data = self.ok(self.get("projects/", {"page": 1, "page_size": 1}))
        self.assert_page(data)
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["items"]), 1)
        capped = self.bad(self.get("projects/", {"page_size": 500}))
        self.assertIn("page_size", capped["error"])
        self.bad(self.get("projects/", {"page": 0}))

    def test_project_members(self):
        project = self.make_project()
        data = self.ok(self.post("projects/members/", {
            "project_id": project["id"], "action": "add",
            "members": [self.other.id]}))
        self.assertEqual(data["members"], [self.other.id])
        self.assertEqual(data["count"], 1)
        removed = self.ok(self.post("projects/members/", {
            "project_id": project["id"], "action": "remove",
            "members": [self.other.id]}))
        self.assertEqual(removed["members"], [])
        self.bad(self.post("projects/members/", {
            "project_id": project["id"], "members": [999999]}))

    def test_project_update_and_archive(self):
        project = self.make_project()
        updated = self.ok(self.post("projects/update/", {
            "project_id": project["id"], "name": "Alpha 2", "description": "说明"}))
        self.assertEqual(updated["name"], "Alpha 2")
        archived = self.ok(self.post("projects/archive/", {"project_id": project["id"]}))
        self.assertEqual(archived["status"], "archived")
        self.bad(self.post("projects/archive/", {"project_id": project["id"]}))

    def test_environment_crud_and_toggle(self):
        project = self.make_project()
        env = self.make_env(project["id"])
        self.assertEqual(env["env_type"], "staging")
        self.bad(self.post("environments/", {
            "project_id": project["id"], "key": "staging", "name": "重复"}))
        toggled = self.ok(self.post("environments/toggle/", {"environment_id": env["id"]}))
        self.assertFalse(toggled["enabled"])
        updated = self.ok(self.post("environments/update/", {
            "environment_id": env["id"], "name": "预发-2", "enabled": True}))
        self.assertTrue(updated["enabled"])
        flag = self.make_flag(project["id"], env["id"])
        deleted = self.ok(self.post("environments/delete/", {"environment_id": env["id"]}))
        self.assertTrue(deleted["deleted"])
        self.assertFalse(services.Flag.objects.filter(pk=flag["id"]).exists())
        detail = self.ok(self.get(f"projects/{project['id']}/"))
        self.assertEqual(detail["environment_count"], 1)

    def test_project_stats(self):
        project = self.make_project()
        env = self.default_env(project["id"])
        self.make_flag(project["id"], env["id"])
        data = self.ok(self.get(f"projects/{project['id']}/stats/"))
        self.assertEqual(data["flags"], 1)
        self.assertEqual(data["environments"], 1)


class FlagCrudTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])

    def test_create_flag_with_variants(self):
        flag = self.make_flag(
            self.project["id"], self.env["id"], flag_type="multivariate",
            variants=[{"key": "blue", "name": "蓝", "weight": 50,
                       "payload": {"color": "blue"}},
                      {"key": "green", "name": "绿", "weight": 50,
                       "payload": {"color": "green"}}],
            labels=["checkout", "q4"])
        self.assertEqual(flag["flag_type"], "multivariate")
        detail = self.ok(self.get(f"flags/{flag['id']}/"))
        self.assertEqual(len(detail["variants"]), 2)
        self.assertEqual(detail["labels"], ["checkout", "q4"])

    def test_duplicate_flag_key(self):
        self.make_flag(self.project["id"], self.env["id"])
        self.bad(self.post("flags/", {
            "project_id": self.project["id"], "environment_id": self.env["id"],
            "key": "new_checkout", "name": "重复"}))

    def test_flag_env_project_mismatch(self):
        other = self.make_project(key="other")
        other_env = self.default_env(other["id"])
        self.bad(self.post("flags/", {
            "project_id": self.project["id"], "environment_id": other_env["id"],
            "key": "bad", "name": "错配"}))

    def test_flag_validation(self):
        self.bad(self.post("flags/", {
            "project_id": self.project["id"], "environment_id": self.env["id"],
            "key": "Bad Key!", "name": "非法"}))
        self.bad(self.post("flags/", {
            "project_id": self.project["id"], "environment_id": self.env["id"],
            "key": "temp", "name": "临时", "temporary": True, "permanent": True}))

    def test_flag_list_and_filters(self):
        self.make_flag(self.project["id"], self.env["id"], key="one")
        self.make_flag(self.project["id"], self.env["id"], key="two", flag_type="multivariate")
        page = self.ok(self.get("flags/", {"project_id": self.project["id"]}))
        self.assert_page(page)
        self.assertEqual(page["count"], 2)
        filtered = self.ok(self.get("flags/", {"flag_type": "multivariate"}))
        self.assertEqual(filtered["count"], 1)
        searched = self.ok(self.get("flags/", {"q": "one"}))
        self.assertEqual(searched["count"], 1)

    def test_flag_update_toggle_archive(self):
        flag = self.make_flag(self.project["id"], self.env["id"])
        updated = self.ok(self.post("flags/update/", {
            "flag_id": flag["id"], "name": "新名字", "assignee": "爱丽丝",
            "labels": ["a", "b"]}))
        self.assertEqual(updated["name"], "新名字")
        self.assertEqual(updated["labels"], ["a", "b"])
        toggled = self.ok(self.post("flags/toggle/", {"flag_id": flag["id"]}))
        self.assertEqual(toggled["status"], "inactive")
        self.assertEqual(self.evaluate(flag["id"])["reason"], "flag-inactive")
        archived = self.ok(self.post("flags/archive/", {"flag_id": flag["id"]}))
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self.evaluate(flag["id"])["reason"], "flag-archived")
        self.bad(self.post("flags/toggle/", {"flag_id": flag["id"]}))

    def test_flag_clone(self):
        flag = self.make_flag(
            self.project["id"], self.env["id"], flag_type="multivariate",
            variants=[{"key": "a", "name": "A", "weight": 100}],
            targeting_rules=[{"conditions": [{"field": "user.country",
                                              "operator": "eq", "value": "CN"}],
                              "variant_key": "a"}])
        clone = self.ok(self.post("flags/clone/", {
            "flag_id": flag["id"], "key": "clone_key"}))
        self.assertEqual(clone["key"], "clone_key")
        self.assertEqual(clone["status"], "inactive")
        detail = self.ok(self.get(f"flags/{clone['id']}/"))
        self.assertEqual(len(detail["variants"]), 1)
        self.assertEqual(len(detail["targeting_rules"]), 1)
        self.bad(self.post("flags/clone/", {
            "flag_id": flag["id"], "key": "new_checkout"}))

    def test_publish_versions_and_rollback(self):
        flag = self.make_flag(
            self.project["id"], self.env["id"], flag_type="multivariate",
            variants=[{"key": "a", "name": "A", "weight": 100,
                       "payload": {"v": 1}}])
        version = self.ok(self.post("flags/publish/", {
            "flag_id": flag["id"], "change_note": "初始"}))
        self.assertEqual(version["version"], 1)
        self.ok(self.post("variants/weight/", {
            "flag_id": flag["id"], "weights": {"a": 100},
            "variant_id": None}))
        variant = self.ok(self.get("variants/", {"flag_id": flag["id"]}))["items"][0]
        self.ok(self.post("variants/update/", {
            "variant_id": variant["id"], "payload": {"v": 2}}))
        self.ok(self.post("flags/publish/", {"flag_id": flag["id"], "change_note": "改负载"}))
        versions = self.ok(self.get(f"flags/{flag['id']}/versions/"))
        self.assertEqual(versions["count"], 2)
        result = self.ok(self.post("flags/rollback/", {
            "flag_id": flag["id"], "version": 1}))
        self.assertEqual(result["rolled_back_to"], 1)
        self.assertEqual(result["new_version"]["version"], 3)
        detail = self.ok(self.get(f"flags/{flag['id']}/"))
        self.assertEqual(detail["variants"][0]["payload"], {"v": 1})

    def test_delete_flag_and_audit(self):
        flag = self.make_flag(self.project["id"], self.env["id"])
        self.ok(self.post("flags/delete/", {"flag_id": flag["id"]}))
        self.bad(self.get(f"flags/{flag['id']}/"))
        events = self.ok(self.get("audit-events/", {"object_type": "flag"}))
        actions = {row["action"] for row in events["items"]}
        self.assertIn("flag.delete", actions)
        self.assertIn("flag.create", actions)


class EvaluationTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])

    def test_default_and_deterministic(self):
        first = self.evaluate(self.flag["id"], "u1")
        second = self.evaluate(self.flag["id"], "u1")
        self.assertFalse(first["enabled"])
        self.assertEqual(first["reason"], "default")
        self.assertEqual(first["variant"], "false")
        self.assertEqual(first["enabled"], second["enabled"])
        self.assertEqual(first["variant"], second["variant"])
        self.assertTrue(second["cached"])

    def test_rollout_full_and_partial(self):
        self.ok(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": 100}))
        result = self.evaluate(self.flag["id"], "u1")
        self.assertTrue(result["enabled"])
        self.assertEqual(result["reason"], "rollout:100%")
        # 0% 永远不会命中，即使桶值为 0
        rollout = self.ok(self.get("rollouts/", {"flag_id": self.flag["id"]}))["items"][0]
        self.ok(self.post("rollouts/update/", {"rollout_id": rollout["id"], "percentage": 0}))
        self.assertFalse(self.evaluate(self.flag["id"], "u1")["enabled"])

    def test_partial_rollout_stable(self):
        self.ok(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": 37}))
        first = self.evaluate(self.flag["id"], "stable-user")
        for _ in range(3):
            again = self.evaluate(self.flag["id"], "stable-user")
            self.assertEqual(first["enabled"], again["enabled"])
            self.assertEqual(first["variant"], again["variant"])
        hits = 0
        for index in range(40):
            if self.evaluate(self.flag["id"], f"bulk-{index}")["enabled"]:
                hits += 1
        self.assertGreater(hits, 0)
        self.assertLess(hits, 40)

    def test_targeting_rule(self):
        rule = self.ok(self.post("targeting-rules/", {
            "flag_id": self.flag["id"],
            "conditions": [{"field": "user.country", "operator": "eq", "value": "CN"}],
            "variant_key": "true", "percentage": 100}))
        cn = self.evaluate(self.flag["id"], "u-cn", {"user": {"country": "CN"}})
        us = self.evaluate(self.flag["id"], "u-us", {"user": {"country": "US"}})
        self.assertTrue(cn["enabled"])
        self.assertEqual(cn["reason"], f"targeting:{rule['id']}")
        self.assertFalse(us["enabled"])
        self.assertEqual(us["reason"], "default")

    def test_targeting_percentage_skip(self):
        self.ok(self.post("targeting-rules/", {
            "flag_id": self.flag["id"],
            "conditions": [{"field": "user.plan", "operator": "in", "value": ["pro"]}],
            "variant_key": "true", "percentage": 0}))
        result = self.evaluate(self.flag["id"], "u1", {"user": {"plan": "pro"}})
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reason"], "default")

    def test_multivariate_weighted_variant(self):
        flag = self.make_flag(
            self.project["id"], self.env["id"], key="color_flag",
            flag_type="multivariate",
            variants=[{"key": "blue", "name": "蓝", "weight": 50,
                       "payload": {"color": "blue"}},
                      {"key": "green", "name": "绿", "weight": 50,
                       "payload": {"color": "green"}}])
        self.ok(self.post("rollouts/", {"flag_id": flag["id"], "percentage": 100}))
        seen = set()
        for index in range(10):
            result = self.evaluate(flag["id"], f"m-{index}")
            seen.add(result["variant"])
            self.assertIn(result["variant"], ("blue", "green"))
            self.assertEqual(result["value"]["color"], result["variant"])
        self.assertGreaterEqual(len(seen), 1)

    def test_batch_and_bool(self):
        self.ok(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": 100}))
        batch = self.ok(self.post("evaluate/batch/", {
            "flag_id": self.flag["id"], "user_keys": ["a", "b", "c"]}))
        self.assertEqual(batch["count"], 3)
        self.assertEqual(batch["hits"], 3)
        self.assertEqual(len(batch["items"]), 3)
        booleans = self.ok(self.post("evaluate/bool/", {
            "user_key": "a", "project_id": self.project["id"]}))
        self.assertTrue(booleans["flags"][self.flag["key"]])
        self.assertEqual(booleans["count"], 1)

    def test_explain(self):
        rule = self.ok(self.post("targeting-rules/", {
            "flag_id": self.flag["id"],
            "conditions": [{"field": "custom.device", "operator": "eq", "value": "ios"}],
            "variant_key": "true"}))
        data = self.ok(self.post("evaluate/explain/", {
            "flag_id": self.flag["id"], "user_key": "u1",
            "context": {"custom": {"device": "ios"}}}))
        self.assertTrue(data["result"]["enabled"])
        steps = {row["step"] for row in data["steps"]}
        self.assertIn("targeting", steps)
        self.assertIn("rollouts", steps)
        targeting_step = [row for row in data["steps"] if row["step"] == "targeting"][0]
        self.assertEqual(targeting_step["rules"][0]["rule_id"], rule["id"])

    def test_evaluation_log_and_history(self):
        self.evaluate(self.flag["id"], "log-user")
        history = self.ok(self.get(f"flags/{self.flag['id']}/evaluations/"))
        self.assert_page(history)
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["items"][0]["matched_rule"], "default")
        searched = self.ok(self.get(f"flags/{self.flag['id']}/evaluations/",
                                    {"q": "log-user"}))
        self.assertEqual(searched["count"], 1)

    def test_environment_disabled(self):
        self.ok(self.post("environments/toggle/", {"environment_id": self.env["id"]}))
        self.assertEqual(self.evaluate(self.flag["id"])["reason"], "environment-disabled")

    def test_boolean_alias_by_key(self):
        self.ok(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": 100}))
        result = self.ok(self.post("evaluate/", {
            "flag": self.flag["key"],
            "project_id": self.project["id"],
            "environment_id": self.env["id"],
            "user_key": "alias-user"}))
        self.assertTrue(result["enabled"])

    def test_evaluation_validation(self):
        self.bad(self.post("evaluate/", {"flag_id": self.flag["id"]}))
        self.bad(self.post("evaluate/batch/", {
            "flag_id": self.flag["id"], "user_keys": []}))
        # 缺少 user_key 必须报错，而不是默认成匿名用户
        self.bad(self.post("evaluate/", {"flag_id": self.flag["id"]}))
        self.bad(self.post("evaluate/", {"user_key": "u1"}))


class SegmentRolloutTargetingTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])

    def test_segment_crud_and_preview(self):
        segment = self.make_segment(self.project["id"])
        preview = self.ok(self.post("segments/preview/", {
            "segment_id": segment["id"],
            "contexts": [
                {"user_key": "a", "user": {"country": "US"}},
                {"user_key": "b", "user": {"country": "CN"}},
                {"user_key": "c", "user": {"country": "CA"}},
            ]}))
        self.assertEqual(preview["hits"], 2)
        self.assertEqual(preview["total"], 3)
        updated = self.ok(self.post("segments/update/", {
            "segment_id": segment["id"], "description": "北美"}))
        self.assertEqual(updated["description"], "北美")
        detail = self.ok(self.get(f"segments/{segment['id']}/"))
        self.assertEqual(detail["name"], "beta")
        self.ok(self.post("segments/delete/", {"segment_id": segment["id"]}))
        self.bad(self.get(f"segments/{segment['id']}/"))

    def test_segment_rules(self):
        segment = self.make_segment(self.project["id"], rules=[])
        rule = self.ok(self.post("segments/rules/", {
            "segment_id": segment["id"], "field": "user.email",
            "operator": "ends_with", "value": "@example.com"}))
        preview = self.ok(self.post("segments/preview/", {
            "segment_id": segment["id"],
            "contexts": [{"user_key": "a", "user": {"email": "a@example.com"}},
                         {"user_key": "b", "user": {"email": "b@other.com"}}]}))
        self.assertEqual(preview["hits"], 1)
        updated = self.ok(self.post("segments/rules/update/", {
            "rule_id": rule["id"], "value": "@other.com"}))
        self.assertEqual(updated["value"], "@other.com")
        self.ok(self.post("segments/rules/delete/", {"rule_id": rule["id"]}))
        self.bad(self.post("segments/rules/", {
            "segment_id": segment["id"], "field": "x", "operator": "bad"}))

    def test_segment_rollout_reason(self):
        segment = self.make_segment(self.project["id"])
        self.ok(self.post("rollouts/", {
            "flag_id": self.flag["id"], "percentage": 100,
            "segment_id": segment["id"]}))
        us = self.evaluate(self.flag["id"], "u-us", {"user": {"country": "US"}})
        cn = self.evaluate(self.flag["id"], "u-cn", {"user": {"country": "CN"}})
        self.assertTrue(us["enabled"])
        self.assertEqual(us["reason"], "segment:beta")
        self.assertFalse(cn["enabled"])
        self.assertEqual(cn["reason"], "rollout:100%")

    def test_rollout_advance_and_toggle(self):
        rollout = self.ok(self.post("rollouts/", {
            "flag_id": self.flag["id"], "percentage": 10}))
        advanced = self.ok(self.post("rollouts/advance/", {
            "rollout_id": rollout["id"], "delta": 10}))
        self.assertEqual(advanced["percentage"], 20)
        target = self.ok(self.post("rollouts/advance/", {
            "rollout_id": rollout["id"], "target": 60}))
        self.assertEqual(target["percentage"], 60)
        # 推进只增不减：target 小于当前值不生效
        same = self.ok(self.post("rollouts/advance/", {
            "rollout_id": rollout["id"], "target": 30}))
        self.assertEqual(same["percentage"], 60)
        paused = self.ok(self.post("rollouts/toggle/", {
            "rollout_id": rollout["id"], "status": "paused"}))
        self.assertEqual(paused["status"], "paused")
        result = self.evaluate(self.flag["id"], "u1")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reason"], "rollout:paused")
        completed = self.ok(self.post("rollouts/advance/", {
            "rollout_id": rollout["id"], "target": 100}))
        self.assertEqual(completed["status"], "completed")

    def test_targeting_reorder_and_toggle(self):
        first = self.ok(self.post("targeting-rules/", {
            "flag_id": self.flag["id"], "priority": 10,
            "conditions": [{"field": "user.country", "operator": "eq", "value": "CN"}],
            "variant_key": "true"}))
        second = self.ok(self.post("targeting-rules/", {
            "flag_id": self.flag["id"], "priority": 20,
            "conditions": [{"field": "user.country", "operator": "eq", "value": "US"}],
            "variant_key": "false"}))
        self.bad(self.post("targeting-rules/", {
            "flag_id": self.flag["id"], "priority": 10,
            "conditions": [], "variant_key": "true"}))
        reordered = self.ok(self.post("targeting-rules/reorder/", {
            "flag_id": self.flag["id"], "ids": [second["id"], first["id"]]}))
        self.assertEqual([row["id"] for row in reordered["rules"]],
                         [second["id"], first["id"]])
        toggled = self.ok(self.post("targeting-rules/toggle/", {
            "rule_id": first["id"], "enabled": False}))
        self.assertFalse(toggled["enabled"])
        self.ok(self.post("targeting-rules/delete/", {"rule_id": first["id"]}))
        remaining = self.ok(self.get("targeting-rules/", {"flag_id": self.flag["id"]}))
        self.assertEqual(remaining["count"], 1)

    def test_variants_crud_and_weight(self):
        flag = self.make_flag(
            self.project["id"], self.env["id"], key="multi",
            flag_type="multivariate",
            variants=[{"key": "a", "name": "A", "weight": 50},
                      {"key": "b", "name": "B", "weight": 50}])
        variants = self.ok(self.get("variants/", {"flag_id": flag["id"]}))["items"]
        self.assertEqual(len(variants), 2)
        result = self.ok(self.post("variants/weight/", {
            "flag_id": flag["id"],
            "weights": {"a": 20, "b": 80}}))
        weights = {row["key"]: row["weight"] for row in result["variants"]}
        self.assertEqual(weights, {"a": 20, "b": 80})
        extra = self.ok(self.post("variants/", {
            "flag_id": flag["id"], "key": "c", "name": "C", "weight": 0,
            "payload": {"x": 1}}))
        updated = self.ok(self.post("variants/update/", {
            "variant_id": extra["id"], "name": "C2"}))
        self.assertEqual(updated["name"], "C2")
        self.ok(self.post("variants/delete/", {"variant_id": extra["id"]}))
        self.bad(self.post("variants/", {
            "flag_id": flag["id"], "key": "a", "name": "重复"}))

    def test_rollout_validation(self):
        segment = self.make_segment(self.project["id"])
        other = self.make_project(key="other")
        other_env = self.default_env(other["id"])
        other_flag = self.make_flag(other["id"], other_env["id"], key="other_flag")
        self.bad(self.post("rollouts/", {
            "flag_id": other_flag["id"], "percentage": 10,
            "segment_id": segment["id"]}))
        self.bad(self.post("rollouts/", {
            "flag_id": self.flag["id"], "percentage": 101}))


class DependencyEvaluationTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.upstream = self.make_flag(self.project["id"], self.env["id"], key="upstream")
        self.downstream = self.make_flag(self.project["id"], self.env["id"], key="downstream")
        self.dep = self.ok(self.post("dependencies/", {
            "flag_id": self.downstream["id"], "depends_on_id": self.upstream["id"],
            "relation": "requires"}))

    def test_dependency_blocks_when_upstream_off(self):
        result = self.evaluate(self.downstream["id"], "u1")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reason"], "dependency:upstream")

    def test_dependency_allows_when_upstream_on(self):
        self.ok(self.post("rollouts/", {
            "flag_id": self.upstream["id"], "percentage": 100}))
        result = self.evaluate(self.downstream["id"], "u1")
        self.assertEqual(result["reason"], "default")
        self.assertFalse(result["enabled"])

    def test_dependency_graph_and_cycle(self):
        graph = self.ok(self.get("dependencies/graph/", {"project_id": self.project["id"]}))
        self.assertEqual(graph["node_count"], 2)
        self.assertEqual(graph["edge_count"], 1)
        self.assertFalse(graph["cycles"])
        self.bad(self.post("dependencies/", {
            "flag_id": self.upstream["id"], "depends_on_id": self.downstream["id"],
            "relation": "requires"}))
        self.bad(self.post("dependencies/", {
            "flag_id": self.upstream["id"], "depends_on_id": self.upstream["id"]}))
        cycles = self.ok(self.get("dependencies/check-cycles/",
                                   {"project_id": self.project["id"]}))
        self.assertFalse(cycles["has_cycle"])

    def test_dependency_forbids(self):
        other = self.make_flag(self.project["id"], self.env["id"], key="forbid_flag")
        self.ok(self.post("dependencies/", {
            "flag_id": other["id"], "depends_on_id": self.upstream["id"],
            "relation": "forbids"}))
        self.assertEqual(self.evaluate(other["id"])["reason"], "default")
        self.ok(self.post("rollouts/", {
            "flag_id": self.upstream["id"], "percentage": 100}))
        blocked = self.evaluate(other["id"], "another-user")
        self.assertEqual(blocked["reason"], "dependency:upstream")

    def test_dependency_cross_project(self):
        other = self.make_project(key="other")
        other_env = self.default_env(other["id"])
        other_flag = self.make_flag(other["id"], other_env["id"], key="cross")
        self.bad(self.post("dependencies/", {
            "flag_id": other_flag["id"], "depends_on_id": self.upstream["id"]}))
        # 非所有者删除他人依赖必须被行级权限拦下，所有者本人可以删除
        self.as_user(self.other)
        self.bad(self.post("dependencies/delete/", {"dependency_id": self.dep["id"]}))
        self.as_user(self.user)
        self.ok(self.post("dependencies/delete/", {"dependency_id": self.dep["id"]}))


class ExperimentTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])
        self.experiment = self.ok(self.post("experiments/", {
            "flag_id": self.flag["id"], "name": "按钮实验",
            "hypothesis": "新按钮提高转化", "min_sample_size": 2,
            "primary_metric": "conversion"}))

    def test_create_auto_metric(self):
        detail = self.ok(self.get(f"experiments/{self.experiment['id']}/"))
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(len(detail["metrics"]), 1)
        self.assertEqual(detail["metrics"][0]["name"], "conversion")
        self.bad(self.post("experiments/", {
            "flag_id": self.flag["id"], "name": "按钮实验"}))

    def test_lifecycle_and_evaluation(self):
        started = self.ok(self.post("experiments/start/", {
            "experiment_id": self.experiment["id"]}))
        self.assertEqual(started["status"], "running")
        resumed = self.evaluate(self.flag["id"], "exp-user")
        self.assertTrue(resumed["reason"].startswith("experiment:"))
        # 布尔开关上的实验：control 映射 false，treatment 映射 true
        self.assertIn(resumed["variant"], ("true", "false"))
        self.assertEqual(resumed["enabled"], resumed["variant"] == "true")
        again = self.evaluate(self.flag["id"], "exp-user")
        self.assertEqual(resumed["variant"], again["variant"])
        paused = self.ok(self.post("experiments/pause/", {
            "experiment_id": self.experiment["id"]}))
        self.assertEqual(paused["status"], "paused")
        after = self.evaluate(self.flag["id"], "exp-user")
        self.assertFalse(after["reason"].startswith("experiment:"))
        concluded = self.ok(self.post("experiments/conclude/", {
            "experiment_id": self.experiment["id"]}))
        self.assertEqual(concluded["status"], "concluded")
        self.bad(self.post("experiments/start/", {
            "experiment_id": self.experiment["id"]}))

    def test_exposure_idempotent(self):
        self.ok(self.post("experiments/start/", {"experiment_id": self.experiment["id"]}))
        first = self.ok(self.post("experiments/exposures/", {
            "experiment_id": self.experiment["id"], "user_key": "u-exposure",
            "context": {"converted": True, "value": 9}}))
        self.assertTrue(first["created"])
        second = self.ok(self.post("experiments/exposures/", {
            "experiment_id": self.experiment["id"], "user_key": "u-exposure",
            "context": {"converted": True}}))
        self.assertTrue(second["idempotent"])
        self.assertFalse(second["created"])
        stats = self.ok(self.get(f"experiments/{self.experiment['id']}/exposures/"))
        self.assertEqual(stats["total"], 1)

    def test_results_progress_and_winner(self):
        self.ok(self.post("experiments/start/", {"experiment_id": self.experiment["id"]}))
        rows = [
            ("c1", "control", True), ("c2", "control", False),
            ("t1", "treatment", True), ("t2", "treatment", True),
        ]
        for user_key, variant, converted in rows:
            self.ok(self.post("experiments/exposures/", {
                "experiment_id": self.experiment["id"], "user_key": user_key,
                "variant_key": variant,
                "context": {"converted": converted, "value": 10 if converted else 0}}))
        results = self.ok(self.get(f"experiments/{self.experiment['id']}/results/"))
        self.assertEqual(results["total_exposures"], 4)
        self.assertEqual(results["control_variant"], "control")
        variants = {row["variant_key"]: row for row in results["variants"]}
        self.assertAlmostEqual(variants["control"]["conversion_rate"], 0.5)
        self.assertAlmostEqual(variants["treatment"]["conversion_rate"], 1.0)
        self.assertAlmostEqual(variants["treatment"]["lift"], 0.5)
        self.assertGreaterEqual(results["variants"][0]["p_value"], 0)
        self.assertLessEqual(results["variants"][0]["p_value"], 1)
        self.assertTrue(results["sample_ready"])
        self.assertEqual(results["winner"], "treatment")
        progress = self.ok(self.get(f"experiments/{self.experiment['id']}/progress/"))
        self.assertEqual(progress["total_exposures"], 4)
        self.assertGreater(progress["percent"], 0)

    def test_metric_crud(self):
        created = self.ok(self.post("experiment-metrics/", {
            "experiment_id": self.experiment["id"], "name": "revenue",
            "metric_type": "revenue", "unit": "CNY", "set_primary": True}))
        self.assertEqual(created["metric_type"], "revenue")
        updated = self.ok(self.post("experiment-metrics/update/", {
            "metric_id": created["id"], "direction": "increase", "unit": "元"}))
        self.assertEqual(updated["unit"], "元")
        self.bad(self.post("experiment-metrics/", {
            "experiment_id": self.experiment["id"], "name": "revenue"}))
        deleted = self.ok(self.post("experiment-metrics/delete/", {
            "metric_id": created["id"]}))
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["primary_metric"], "conversion")

    def test_experiment_validation(self):
        self.bad(self.post("experiments/pause/", {
            "experiment_id": self.experiment["id"]}))
        self.bad(self.post("experiments/conclude/", {
            "experiment_id": self.experiment["id"]}))
        self.bad(self.post("experiments/exposures/", {
            "experiment_id": self.experiment["id"], "user_key": "u1",
            "variant_key": "nope"}))


class GuardrailAudienceTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])

    def test_audience_crud_and_preview(self):
        audience = self.ok(self.post("audiences/", {
            "project_id": self.project["id"], "name": "付费用户",
            "rules": [{"field": "user.plan", "operator": "in",
                       "value": ["pro", "team"]}]}))
        preview = self.ok(self.post("audiences/preview/", {
            "audience_id": audience["id"],
            "contexts": [{"user_key": "a", "user": {"plan": "pro"}},
                         {"user_key": "b", "user": {"plan": "free"}}]}))
        self.assertEqual(preview["hits"], 1)
        updated = self.ok(self.post("audiences/update/", {
            "audience_id": audience["id"], "description": "付费"}))
        self.assertEqual(updated["description"], "付费")
        detail = self.ok(self.get(f"audiences/{audience['id']}/"))
        self.assertIn("user.plan", detail["fields"])
        self.ok(self.post("audiences/delete/", {"audience_id": audience["id"]}))
        self.bad(self.get(f"audiences/{audience['id']}/"))

    def test_guardrail_triggers_pause_and_audit(self):
        rollout = self.ok(self.post("rollouts/", {
            "flag_id": self.flag["id"], "percentage": 100}))
        guardrail = self.ok(self.post("guardrails/", {
            "flag_id": self.flag["id"], "metric": "error_rate",
            "threshold": 0.5, "action": "pause", "comparator": "gte"}))
        below = self.ok(self.post("guardrails/check/", {
            "flag_id": self.flag["id"], "metric": "error_rate", "value": 0.1}))
        self.assertEqual(below["count"], 0)
        triggered = self.ok(self.post("guardrails/check/", {
            "flag_id": self.flag["id"], "readings": {"error_rate": 0.9}}))
        self.assertEqual(triggered["count"], 1)
        self.assertEqual(triggered["triggered"][0]["guardrail_id"], guardrail["id"])
        self.assertEqual(triggered["triggered"][0]["action"], "pause")
        rollout_after = self.ok(self.get("rollouts/", {"flag_id": self.flag["id"]}))
        self.assertEqual(rollout_after["items"][0]["status"], "paused")
        self.assertEqual(self.evaluate(self.flag["id"], "u1")["reason"], "rollout:paused")
        events = self.ok(self.get("audit-events/", {"action": "guardrail"}))
        self.assertGreaterEqual(events["count"], 1)
        self.assertEqual(rollout["percentage"], 100)

    def test_guardrail_rollback(self):
        self.ok(self.post("guardrails/", {
            "flag_id": self.flag["id"], "metric": "latency", "threshold": 500,
            "action": "rollback", "comparator": "gt"}))
        result = self.ok(self.post("guardrails/check/", {
            "flag_id": self.flag["id"], "readings": [{"metric": "latency", "value": 900}]}))
        self.assertEqual(result["flag_status"], "inactive")
        self.assertEqual(self.evaluate(self.flag["id"])["reason"], "flag-inactive")

    def test_guardrail_crud(self):
        created = self.ok(self.post("guardrails/", {
            "flag_id": self.flag["id"], "metric": "crash", "threshold": 1}))
        updated = self.ok(self.post("guardrails/update/", {
            "guardrail_id": created["id"], "threshold": 2, "window_minutes": 30}))
        self.assertEqual(updated["threshold"], 2)
        self.bad(self.post("guardrails/", {
            "flag_id": self.flag["id"], "metric": "crash"}))
        self.ok(self.post("guardrails/delete/", {"guardrail_id": created["id"]}))
        self.bad(self.post("guardrails/check/", {
            "flag_id": self.flag["id"], "readings": {}}))
        self.bad(self.post("guardrails/", {
            "flag_id": self.flag["id"], "metric": "x", "comparator": "bad"}))


class StatsTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])
        self.ok(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": 100}))
        for index in range(5):
            self.evaluate(self.flag["id"], f"stat-{index}")

    def test_overview(self):
        data = self.ok(self.get("stats/overview/"))
        self.assertEqual(data["flags"], 1)
        self.assertGreaterEqual(data["evaluations"], 5)
        self.assertEqual(data["hits"], 5)
        self.assertEqual(data["hit_rate"], 1.0)

    def test_top_flags(self):
        data = self.ok(self.get("stats/top-flags/"))
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["flag_key"], self.flag["key"])
        self.assertGreaterEqual(data["items"][0]["hit_rate"], 0)

    def test_variant_distribution_and_trend(self):
        distribution = self.ok(self.get("stats/variant-distribution/"))
        self.assertGreaterEqual(distribution["count"], 1)
        variants = {row["variant"] for row in distribution["items"]}
        self.assertIn("true", variants)
        trend = self.ok(self.get("stats/evaluation-trend/", {"days": 7}))
        self.assertEqual(len(trend["items"]), 7)
        self.assertGreaterEqual(trend["total"], 5)

    def test_experiment_board(self):
        experiment = self.ok(self.post("experiments/", {
            "flag_id": self.flag["id"], "name": "看板实验"}))
        self.ok(self.post("experiments/start/", {"experiment_id": experiment["id"]}))
        board = self.ok(self.get("stats/experiment-board/"))
        self.assertEqual(board["experiments"], 1)
        self.assertEqual(board["status"]["running"], 1)
        self.assertEqual(board["items"][0]["experiment_id"], experiment["id"])

    def test_flag_stats(self):
        data = self.ok(self.get(f"flags/{self.flag['id']}/stats/"))
        self.assertGreaterEqual(data["evaluations"], 5)
        self.assertEqual(data["hit_rate"], 1.0)


class ScopingTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])
        self.segment = self.make_segment(self.project["id"])
        self.experiment = self.ok(self.post("experiments/", {
            "flag_id": self.flag["id"], "name": "隔离实验"}))

    def test_other_user_cannot_read_or_write(self):
        self.as_user(self.other)
        projects = self.ok(self.get("projects/"))
        self.assertEqual(projects["count"], 0)
        self.bad(self.get(f"projects/{self.project['id']}/"))
        self.bad(self.get(f"flags/{self.flag['id']}/"))
        self.bad(self.post("flags/update/", {"flag_id": self.flag["id"], "name": "越权"}))
        self.bad(self.post("evaluate/", {"flag_id": self.flag["id"], "user_key": "x"}))
        self.bad(self.get(f"segments/{self.segment['id']}/"))
        self.bad(self.get(f"experiments/{self.experiment['id']}/"))

    def test_admin_can_read(self):
        self.as_user(self.admin)
        detail = self.ok(self.get(f"flags/{self.flag['id']}/"))
        self.assertEqual(detail["id"], self.flag["id"])
        projects = self.ok(self.get("projects/"))
        self.assertEqual(projects["count"], 1)

    def test_project_member_does_not_gain_write(self):
        self.ok(self.post("projects/members/", {
            "project_id": self.project["id"], "members": [self.other.id]}))
        self.as_user(self.other)
        self.bad(self.post("flags/update/", {"flag_id": self.flag["id"], "name": "成员"}))


class ValidationTests(FlagsApiBase):
    def setUp(self):
        super().setUp()
        self.project = self.make_project()
        self.env = self.default_env(self.project["id"])
        self.flag = self.make_flag(self.project["id"], self.env["id"])

    def test_percent_and_key_validation(self):
        self.bad(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": -1}))
        self.bad(self.post("rollouts/", {"flag_id": self.flag["id"], "percentage": "abc"}))
        self.bad(self.post("flags/", {
            "project_id": self.project["id"], "environment_id": self.env["id"],
            "key": "bad key!", "name": "非法键"}))

    def test_condition_validation(self):
        self.bad(self.post("targeting-rules/", {
            "flag_id": self.flag["id"],
            "conditions": [{"field": "user.country", "operator": "regex",
                            "value": "["}], "variant_key": "true"}))
        self.bad(self.post("targeting-rules/", {
            "flag_id": self.flag["id"],
            "conditions": [{"field": "user.country", "operator": "in",
                            "value": "CN"}], "variant_key": "true"}))
        self.bad(self.post("targeting-rules/", {
            "flag_id": self.flag["id"],
            "conditions": [], "variant_key": "missing"}))

    def test_unknown_operator_in_segment(self):
        self.bad(self.post("segments/", {
            "project_id": self.project["id"], "name": "bad",
            "rules": [{"field": "user.country", "operator": "unknown", "value": "CN"}]}))

    def test_bad_json_and_ids(self):
        self.bad(self.post("evaluate/", {
            "flag_id": self.flag["id"], "user_key": "u1", "context": "not-json"}))
        self.bad(self.post("evaluate/", {
            "flag_id": self.flag["id"], "user_key": "u1",
            "context": "{bad json"}))
        self.bad(self.post("segments/preview/", {"segment_id": 999999}))

    def test_operators_semver(self):
        from flags import services as svc

        self.assertTrue(svc.evaluate_condition(
            {"field": "user.version", "operator": "semver_gte", "value": "1.2.0"},
            {"user": {"version": "1.10.3"}}))
        self.assertFalse(svc.evaluate_condition(
            {"field": "user.version", "operator": "semver_lt", "value": "2.0.0"},
            {"user": {"version": "2.1.0"}}))
        self.assertTrue(svc.evaluate_condition(
            {"field": "custom.tags", "operator": "contains", "value": "beta"},
            {"custom": {"tags": ["beta", "ios"]}}))

    def test_deterministic_bucket(self):
        from flags import services as svc

        first = svc.bucket_for_flag("flag", "user", "salt")
        second = svc.bucket_for_flag("flag", "user", "salt")
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 10000)
        self.assertTrue(svc.percentage_hit("f", "u", "s", 100))
        self.assertFalse(svc.percentage_hit("f", "u", "s", 0))
