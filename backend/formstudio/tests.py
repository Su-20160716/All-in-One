# -*- coding: utf-8 -*-
"""formstudio 测试：覆盖目录、设计态、版本、条件/校验/计分、提交、草稿、
分享链接、Webhook、统计导出、模板、审核与评论，以及关键服务层纯函数。

运行：venv/Scripts/python.exe manage.py test formstudio -v 1
（测试库为内存 sqlite，不触碰开发库）
"""
import copy
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from formstudio import services
from formstudio.models import (
    FormDefinition,
    FormShareLink,
    FormSubmission,
    FormSubmissionValue,
    FormWebhookDelivery,
)

User = get_user_model()

BASE = "/api/formstudio/"


def base_schema():
    """通用测试 schema：覆盖文本/数字/单选/多选/评分/邮箱/日期/开关/文件/条件逻辑。"""
    return {
        "sections": [
            {"key": "base", "title": "基本信息", "order": 0},
            {"key": "extra", "title": "补充信息", "order": 1, "collapsible": True},
        ],
        "fields": [
            {"key": "name", "label": "姓名", "type": "text", "required": True,
             "section": "base", "order": 0, "width": "half"},
            {"key": "age", "label": "年龄", "type": "number", "required": True,
             "section": "base", "order": 1, "width": "half",
             "validation": {"min": 18, "max": 120, "integer": True}},
            {"key": "plan", "label": "套餐", "type": "select", "required": True,
             "section": "base", "order": 2,
             "options": [
                 {"value": "basic", "label": "基础", "score": 1},
                 {"value": "pro", "label": "专业", "score": 5},
             ]},
            {"key": "tags", "label": "兴趣", "type": "multiselect", "required": False,
             "section": "extra", "order": 3,
             "options": [
                 {"value": "a", "label": "A"},
                 {"value": "b", "label": "B"},
                 {"value": "c", "label": "C"},
             ]},
            {"key": "score", "label": "评分", "type": "rating", "required": False,
             "section": "extra", "order": 4, "validation": {"max": 5}},
            {"key": "email", "label": "邮箱", "type": "email", "required": False,
             "section": "extra", "order": 5},
            {"key": "visit_date", "label": "到访日期", "type": "date", "required": False,
             "section": "extra", "order": 6},
            {"key": "agree", "label": "同意回访", "type": "boolean", "required": False,
             "section": "extra", "order": 7},
            {"key": "reason", "label": "原因", "type": "textarea", "required": False,
             "section": "extra", "order": 8,
             "condition": {"field": "agree", "op": "eq", "value": True}},
            {"key": "resume", "label": "简历", "type": "file", "required": False,
             "section": "extra", "order": 9, "validation": {"max_size_mb": 5}},
        ],
        "logic": [
            {"name": "同意回访必须填原因",
             "condition": {"field": "agree", "op": "eq", "value": True},
             "action": "require", "target_key": "reason", "priority": 10},
        ],
        "settings": {"scoring": {"pass_score": 3}},
    }


def base_answers():
    """一份合法答案。"""
    return {
        "name": "张三",
        "age": 30,
        "plan": "pro",
        "tags": ["a", "b"],
        "score": 4,
        "email": "zhangsan@example.com",
        "visit_date": "2026-01-15",
        "agree": False,
    }


class FormStudioTestBase(TestCase):
    """公共基类：三个用户 + 两个客户端 + 通用请求助手。"""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="fs_owner", password="test12345")
        cls.other = User.objects.create_user(username="fs_other", password="test12345")
        cls.third = User.objects.create_user(username="fs_third", password="test12345")

    def setUp(self):
        self.owner_c = APIClient()
        self.owner_c.force_authenticate(user=self.owner)
        self.other_c = APIClient()
        self.other_c.force_authenticate(user=self.other)
        self.third_c = APIClient()
        self.third_c.force_authenticate(user=self.third)

    # -- 请求助手 -----------------------------------------------------------
    def api(self, client, method, path, data=None):
        """统一发起请求；GET 用 query 参数，其余用 JSON body。"""
        if method == "get":
            return client.get(path, data or {})
        if method == "delete":
            return client.delete(path, data or {}, format="json")
        return getattr(client, method)(path, data or {}, format="json")

    def ok(self, resp):
        """断言 200 且 ok=True，返回 data。"""
        body = resp.json()
        self.assertEqual(resp.status_code, 200, body)
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def fail(self, resp, status=400):
        """断言业务失败并返回响应体（字符串入参交给 unittest 处理断言消息）。"""
        if isinstance(resp, str):
            super().fail(resp)
        body = resp.json()
        self.assertEqual(resp.status_code, status, body)
        self.assertFalse(body.get("ok"), body)
        return body

    # -- 常用构造 -----------------------------------------------------------
    def create_form(self, schema=None, **overrides):
        """创建表单（可选写入 schema），返回表单 dict。"""
        payload = {
            "name": "测试表单",
            "form_type": "survey",
            "allow_multiple": True,
        }
        payload.update(overrides)
        form = self.ok(self.api(self.owner_c, "post", BASE + "forms/", payload))
        if schema is not None:
            self.ok(
                self.api(
                    self.owner_c,
                    "post",
                    f"{BASE}forms/{form['id']}/schema/",
                    {"schema": schema},
                )
            )
        return form

    def publish(self, form_id):
        """发布表单并返回版本数据。"""
        data = self.ok(self.api(self.owner_c, "post", f"{BASE}forms/{form_id}/publish/", {}))
        return data

    def submit(self, code, answers, client=None, **extra):
        """按编码公开提交。"""
        payload = {"code": code, "answers": answers}
        payload.update(extra)
        return self.api(client or self.other_c, "post", BASE + "submissions/public/", payload)

    def ready_form(self, schema=None, **overrides):
        """创建 + 写 schema + 发布，返回 (form, version)。"""
        form = self.create_form(schema or base_schema(), **overrides)
        data = self.publish(form["id"])
        return form, data["version"]


class CatalogAndDesignTests(FormStudioTestBase):
    """目录、表单 CRUD、schema 校验、版本、分区字段等设计态能力。"""

    def test_catalog(self):
        data = self.ok(self.api(self.owner_c, "get", BASE))
        self.assertEqual(data["domain"], "formstudio")
        self.assertEqual(len(data["field_types"]), 16)
        self.assertEqual(data["endpoint_count"], 61)
        self.assertEqual(len(data["endpoints"]), 61)
        methods = {m for item in data["endpoints"] for m in item["methods"]}
        self.assertIn("GET", methods)
        self.assertIn("POST", methods)

    def test_form_crud_and_permissions(self):
        form = self.ok(
            self.api(
                self.owner_c,
                "post",
                BASE + "forms/",
                {"name": "报名表", "form_type": "registration", "code": "signup-2026"},
            )
        )
        self.assertEqual(form["code"], "signup-2026")
        self.assertEqual(form["status"], "draft")
        # 编码重复
        dup = self.submit(
            "x",
            {},
        )
        self.assertIsNotNone(dup)
        self.fail(
            self.api(
                self.owner_c,
                "post",
                BASE + "forms/",
                {"name": "重复编码", "code": "signup-2026"},
            )
        )
        listing = self.ok(self.api(self.owner_c, "get", BASE + "forms/"))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(set(listing.keys()), {"items", "count", "page", "page_size"})
        self.assertEqual(self.ok(self.api(self.other_c, "get", BASE + "forms/"))["count"], 0)
        # 非创建者不可读/写
        self.fail(self.api(self.other_c, "get", f"{BASE}forms/{form['id']}/"))
        self.fail(
            self.api(self.other_c, "patch", f"{BASE}forms/{form['id']}/", {"name": "改名"})
        )
        detail = self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/"))
        self.assertEqual(detail["sections"], [])
        updated = self.ok(
            self.api(
                self.owner_c,
                "patch",
                f"{BASE}forms/{form['id']}/",
                {"name": "报名表 2026", "allow_anonymous": True, "settings": {"x": 1}},
            )
        )
        self.assertEqual(updated["name"], "报名表 2026")
        self.assertTrue(updated["allow_anonymous"])
        deleted = self.ok(
            self.api(self.owner_c, "delete", f"{BASE}forms/{form['id']}/")
        )
        self.assertTrue(deleted["deleted"])

    def test_schema_save_and_validate(self):
        form = self.create_form()
        counts = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/",
                {"schema": base_schema()},
            )
        )["counts"]
        self.assertEqual(counts["fields"], 10)
        self.assertEqual(counts["sections"], 2)
        self.assertEqual(counts["logic"], 1)
        schema = self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/schema/"))
        self.assertEqual(schema["summary"]["fields"], 10)
        self.assertEqual(schema["issues"], [])
        # 重复 key + 选择题无选项
        bad = base_schema()
        bad["fields"].append({"key": "name", "label": "重复", "type": "text"})
        bad["fields"].append({"key": "empty_select", "label": "空单选", "type": "select"})
        result = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/validate/",
                {"schema": bad},
            )
        )
        self.assertFalse(result["valid"])
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("field_duplicate", codes)
        self.assertIn("options_required", codes)
        # 保存非法 schema 被拒
        self.fail(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/",
                {"schema": bad},
            )
        )

    def test_schema_condition_and_cycle_validation(self):
        form = self.create_form()
        schema = {
            "sections": [],
            "fields": [
                {"key": "a", "label": "A", "type": "text"},
                {"key": "b", "label": "B", "type": "text"},
            ],
            "logic": [
                {"condition": {"field": "b", "op": "not_empty"},
                 "action": "set_value", "target_key": "a", "value": "x"},
                {"condition": {"field": "a", "op": "not_empty"},
                 "action": "set_value", "target_key": "b", "value": "y"},
            ],
        }
        result = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/validate/",
                {"schema": schema},
            )
        )
        self.assertFalse(result["valid"])
        self.assertIn("logic_cycle", {i["code"] for i in result["issues"]})
        schema["fields"].append(
            {"key": "c", "label": "C", "type": "text",
             "condition": {"field": "missing", "op": "empty"}}
        )
        result = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/validate/",
                {"schema": schema},
            )
        )
        self.assertIn("condition_ref", {i["code"] for i in result["issues"]})

    def test_publish_versions_compare_rollback(self):
        form, version = self.ready_form()
        self.assertEqual(version["version_no"], 1)
        self.assertTrue(version["is_current"])
        detail = self.ok(self.api(self.owner_c, "get", f"{BASE}versions/{version['id']}/"))
        self.assertEqual(len(detail["schema"]["fields"]), 10)
        form_detail = self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/"))
        self.assertEqual(form_detail["status"], "published")
        self.assertEqual(form_detail["current_version"]["version_no"], 1)
        versions = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/versions/")
        )
        self.assertEqual(versions["count"], 1)
        # 修改字段标签后发布 v2
        changed = base_schema()
        changed["fields"][0]["label"] = "真实姓名"
        changed["fields"][0]["required"] = False
        self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/",
                {"schema": changed},
            )
        )
        v2 = self.publish(form["id"])["version"]
        self.assertEqual(v2["version_no"], 2)
        diff = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/versions/compare/",
                {"left_id": version["id"], "right_id": v2["id"]},
            )
        )
        self.assertEqual(diff["summary"]["fields_modified"], 1)
        self.assertEqual(diff["fields"]["modified"][0]["key"], "name")
        rolled = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}versions/{version['id']}/rollback/",
                {"note": "回滚测试"},
            )
        )
        self.assertEqual(rolled["version"]["version_no"], 3)
        fields = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/fields/")
        )["items"]
        name_field = [x for x in fields if x["key"] == "name"][0]
        self.assertEqual(name_field["label"], "姓名")
        self.assertTrue(name_field["required"])

    def test_sections_fields_crud_reorder_options_rules(self):
        form = self.create_form()
        section = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/sections/",
                {"key": "sec1", "title": "第一段", "collapsible": True},
            )
        )
        self.assertEqual(section["key"], "sec1")
        # 非 owner 不能建字段
        self.fail(
            self.api(
                self.other_c,
                "post",
                f"{BASE}forms/{form['id']}/fields/",
                {"key": "x", "label": "X", "field_type": "text"},
            )
        )
        select_field = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/fields/",
                {
                    "key": "nick",
                    "label": "昵称",
                    "field_type": "select",
                    "required": True,
                    "section_id": section["id"],
                    "options": [
                        {"value": "a", "label": "A", "score": 2},
                        {"value": "b", "label": "B"},
                    ],
                },
            )
        )
        self.assertEqual(len(select_field["options"]), 2)
        self.assertEqual(select_field["section_id"], section["id"])
        # 选择题必须有选项
        self.fail(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/fields/",
                {"key": "bad", "label": "坏单选", "field_type": "select"},
            )
        )
        text_field = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/fields/",
                {"key": "code", "label": "编号", "field_type": "text", "width": "half"},
            )
        )
        self.assertEqual(
            self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/fields/"))["count"],
            2,
        )
        # 替换选项
        replaced = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}fields/{select_field['id']}/options/",
                {"options": [{"value": "x", "label": "X", "score": 3}]},
            )
        )
        self.assertEqual(replaced["count"], 1)
        updated = self.ok(
            self.api(
                self.owner_c,
                "patch",
                f"{BASE}fields/{select_field['id']}/",
                {"label": "昵称（必填）", "default_value": "x"},
            )
        )
        self.assertEqual(updated["label"], "昵称（必填）")
        # 排序
        reordered = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/fields/reorder/",
                {"keys": ["code", "nick"]},
            )
        )
        self.assertEqual([f["key"] for f in reordered["items"]], ["code", "nick"])
        sections = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/sections/reorder/",
                {"ids": [section["id"]]},
            )
        )
        self.assertEqual(sections["count"], 1)
        # 校验规则
        rule = self.ok(
            self.api(
                self.owner_c,
                "post",
                BASE + "validations/",
                {
                    "form_id": form["id"],
                    "field_id": text_field["id"],
                    "rule_type": "regex",
                    "params": {"pattern": "^[A-Z]{2}\\d+$"},
                    "message": "编号格式错误",
                },
            )
        )
        self.assertEqual(rule["rule_type"], "regex")
        self.fail(
            self.api(
                self.owner_c,
                "post",
                BASE + "validations/",
                {
                    "form_id": form["id"],
                    "field_id": text_field["id"],
                    "rule_type": "regex",
                    "params": {"pattern": "(["},
                },
            )
        )
        rules = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/validations/")
        )
        self.assertEqual(rules["count"], 1)
        patched = self.ok(
            self.api(
                self.owner_c,
                "patch",
                f"{BASE}validations/{rule['id']}/",
                {"message": "请填正确编号"},
            )
        )
        self.assertEqual(patched["message"], "请填正确编号")
        self.ok(self.api(self.owner_c, "delete", f"{BASE}validations/{rule['id']}/"))
        # 逻辑规则 + 试跑
        logic = self.ok(
            self.api(
                self.owner_c,
                "post",
                BASE + "logic/",
                {
                    "form_id": form["id"],
                    "name": "选 X 必填编号",
                    "condition": {"field": "nick", "op": "eq", "value": "x"},
                    "action": "require",
                    "target_key": "code",
                },
            )
        )
        state = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/logic/test/",
                {"answers": {"nick": "x"}},
            )
        )
        self.assertIn("code", state["states"]["required"])
        self.assertIn("code", state["errors"][0]["field"])
        listed = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/logic/")
        )
        self.assertEqual(listed["count"], 1)
        self.ok(self.api(self.owner_c, "patch", f"{BASE}logic/{logic['id']}/", {"priority": 5}))
        self.ok(self.api(self.owner_c, "delete", f"{BASE}logic/{logic['id']}/"))
        self.ok(self.api(self.owner_c, "delete", f"{BASE}fields/{select_field['id']}/"))
        self.ok(self.api(self.owner_c, "delete", f"{BASE}sections/{section['id']}/"))


class SubmissionTests(FormStudioTestBase):
    """提交、草稿、匿名、多次限制、附件与版本固化。"""

    def test_public_submit_validation_and_values(self):
        form, _version = self.ready_form()
        # 缺少必填
        resp = self.submit(form["code"], {"plan": "pro"})
        body = self.fail(resp)
        self.assertTrue(body.get("errors"))
        self.assertIn("name", {e["field"] for e in body["errors"]})
        # 非法选项
        answers = base_answers()
        answers["plan"] = "not-exists"
        body = self.fail(self.submit(form["code"], answers))
        self.assertIn("plan", {e["field"] for e in body["errors"]})
        # 数字越界
        answers = base_answers()
        answers["age"] = 10
        body = self.fail(self.submit(form["code"], answers))
        self.assertIn("age", {e["field"] for e in body["errors"]})
        # 邮箱格式
        answers = base_answers()
        answers["email"] = "bad-email"
        body = self.fail(self.submit(form["code"], answers))
        self.assertIn("email", {e["field"] for e in body["errors"]})
        # 合法提交
        data = self.ok(self.submit(form["code"], base_answers()))
        submission = data["submission"]
        self.assertEqual(submission["status"], "submitted")
        self.assertEqual(submission["version_no"], 1)
        self.assertEqual(submission["score"], 9)
        self.assertEqual(submission["max_score"], 10)
        self.assertGreaterEqual(len(submission["values"]), 7)
        self.assertEqual(submission["submitted_by"]["id"], self.other.id)
        # 表单计数 + 我的提交
        detail = self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/"))
        self.assertEqual(detail["submission_count"], 1)
        mine = self.ok(self.api(self.other_c, "get", BASE + "submissions/mine/"))
        self.assertEqual(mine["count"], 1)
        # 填报人与创建者都能看详情
        self.ok(self.api(self.other_c, "get", f"{BASE}submissions/{submission['id']}/"))
        self.ok(self.api(self.owner_c, "get", f"{BASE}submissions/{submission['id']}/"))
        # 无关用户看不到
        self.fail(self.api(self.third_c, "get", f"{BASE}submissions/{submission['id']}/"))
        # 列表结构与筛选
        listing = self.ok(
            self.api(self.owner_c, "get", BASE + "submissions/", {"status": "submitted"})
        )
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["form_name"], form["name"])

    def test_condition_engine_required_and_hidden(self):
        form, _version = self.ready_form()
        answers = base_answers()
        answers["agree"] = True
        body = self.fail(self.submit(form["code"], answers))
        self.assertIn("reason", {e["field"] for e in body["errors"]})
        answers["reason"] = "希望电话回访"
        data = self.ok(self.submit(form["code"], answers))
        values = {v["field_key"]: v for v in data["submission"]["values"]}
        self.assertEqual(values["reason"]["raw"], "希望电话回访")
        # 不同意时 reason 被隐藏，即使传了也不落值
        answers = base_answers()
        answers["reason"] = "隐藏字段内容"
        data = self.ok(self.submit(form["code"], answers))
        values = {v["field_key"] for v in data["submission"]["values"]}
        self.assertNotIn("reason", values)

    def test_anonymous_submission(self):
        form, _version = self.ready_form(allow_anonymous=True)
        data = self.ok(self.submit(form["code"], base_answers(), anonymous=True))
        submission = data["submission"]
        self.assertIsNone(submission["submitted_by"])
        self.assertEqual(self.ok(self.api(self.other_c, "get", BASE + "submissions/mine/"))["count"], 0)
        owner_list = self.ok(self.api(self.owner_c, "get", BASE + "submissions/"))
        self.assertEqual(owner_list["count"], 1)
        self.assertIsNone(owner_list["items"][0]["submitted_by"])
        # 非匿名提交记录填报人
        data = self.ok(self.submit(form["code"], base_answers(), client=self.third_c))
        self.assertEqual(data["submission"]["submitted_by"]["id"], self.third.id)

    def test_multiple_submit_limit(self):
        form, _version = self.ready_form(allow_multiple=False)
        self.ok(self.submit(form["code"], base_answers()))
        body = self.fail(self.submit(form["code"], base_answers()))
        self.assertIn("重复提交", body["error"])

    def test_draft_flow_and_delete(self):
        form, _version = self.ready_form()
        draft = self.ok(
            self.api(
                self.other_c,
                "post",
                BASE + "submissions/draft/",
                {"code": form["code"], "answers": {"name": "草稿中"}},
            )
        )
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(len(draft["values"]), 1)
        # 草稿未通过必填校验也能保存
        updated = self.ok(
            self.api(
                self.other_c,
                "post",
                f"{BASE}submissions/{draft['id']}/draft/",
                {"answers": base_answers(), "submit": True, "duration_seconds": 45},
            )
        )
        self.assertEqual(updated["status"], "submitted")
        self.assertEqual(updated["duration_seconds"], 45)
        self.assertGreaterEqual(len(updated["values"]), 7)
        # 正式提交后不可再按草稿编辑
        self.fail(
            self.api(
                self.other_c,
                "post",
                f"{BASE}submissions/{draft['id']}/draft/",
                {"answers": {"name": "改"}},
            )
        )
        # 新建草稿并删除
        draft2 = self.ok(
            self.api(
                self.other_c,
                "post",
                BASE + "submissions/draft/",
                {"code": form["code"], "answers": {"name": "待删"}},
            )
        )
        self.ok(self.api(self.other_c, "delete", f"{BASE}submissions/{draft2['id']}/delete/"))
        mine = self.ok(self.api(self.other_c, "get", BASE + "submissions/mine/"))
        self.assertEqual(mine["count"], 1)

    def test_version_freeze_on_submit(self):
        form, _version = self.ready_form()
        self.ok(self.submit(form["code"], base_answers()))
        changed = base_schema()
        changed["fields"][0]["label"] = "姓名（新版）"
        self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/schema/",
                {"schema": changed},
            )
        )
        self.publish(form["id"])
        self.ok(self.submit(form["code"], base_answers()))
        subs = list(
            FormSubmission.objects.filter(form_id=form["id"]).order_by("id")
        )
        self.assertEqual([s.version_no for s in subs], [1, 2])
        stats = self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/stats/"))
        versions = {row["version_no"]: row["count"] for row in stats["by_version"]}
        self.assertEqual(versions, {1: 1, 2: 1})
        filtered = self.ok(
            self.api(self.owner_c, "get", BASE + "submissions/", {"version_no": 1})
        )
        self.assertEqual(filtered["count"], 1)

    def test_attachments_metadata_only(self):
        form, _version = self.ready_form()
        answers = base_answers()
        answers["resume"] = {
            "file_name": "cv.pdf",
            "file_size": 2048,
            "content_hash": "a" * 64,
            "mime_type": "application/pdf",
        }
        data = self.ok(self.submit(form["code"], answers))
        sub_id = data["submission"]["id"]
        att = self.ok(
            self.api(
                self.other_c,
                "post",
                f"{BASE}submissions/{sub_id}/attachments/",
                {
                    "field_key": "resume",
                    "file_name": "cv.pdf",
                    "file_size": 2048,
                    "content_hash": "b" * 64,
                    "mime_type": "application/pdf",
                },
            )
        )
        self.assertEqual(att["file_name"], "cv.pdf")
        self.fail(
            self.api(
                self.other_c,
                "post",
                f"{BASE}submissions/{sub_id}/attachments/",
                {
                    "field_key": "resume",
                    "file_name": "cv.pdf",
                    "file_size": 10,
                    "content": "真实文件内容",
                },
            )
        )
        listed = self.ok(
            self.api(self.other_c, "get", f"{BASE}submissions/{sub_id}/attachments/")
        )
        self.assertEqual(listed["count"], 1)
        detail = self.ok(
            self.api(self.owner_c, "get", f"{BASE}submissions/{sub_id}/")
        )
        self.assertEqual(len(detail["attachments"]), 1)


class SharingWebhookTemplateTests(FormStudioTestBase):
    """分享链接、Webhook、模板与测验计分。"""

    def test_share_links_password_limit_and_disable(self):
        form, _version = self.ready_form()
        self.fail(
            self.api(
                self.other_c,
                "post",
                f"{BASE}forms/{form['id']}/share-links/",
                {"label": "别人创建"},
            )
        )
        link = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/share-links/",
                {
                    "label": "客户群",
                    "password": "abcd",
                    "max_uses": 1,
                    "expires_at": (timezone.now() + timedelta(days=7)).isoformat(),
                },
            )
        )
        self.assertTrue(link["requires_password"])
        self.assertNotIn("password_hash", link)
        self.fail(
            self.api(
                self.other_c,
                "post",
                BASE + "share-links/verify/",
                {"token": link["token"], "password": "wrong"},
            )
        )
        verified = self.ok(
            self.api(
                self.other_c,
                "post",
                BASE + "share-links/verify/",
                {"token": link["token"], "password": "abcd"},
            )
        )
        self.assertEqual(verified["remaining_uses"], 1)
        self.assertEqual(verified["link"]["used_count"], 0)
        # 首次提交消费一次
        data = self.ok(
            self.submit(
                form["code"],
                base_answers(),
                token=link["token"],
                password="abcd",
            )
        )
        self.assertEqual(data["submission"]["source"], "share")
        # 次数用尽
        self.fail(
            self.submit(form["code"], base_answers(), token=link["token"], password="abcd")
        )
        listing = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/share-links/")
        )
        self.assertEqual(listing["count"], 1)
        self.ok(self.api(self.owner_c, "post", f"{BASE}share-links/{link['id']}/disable/", {}))
        self.fail(
            self.submit(form["code"], base_answers(), token=link["token"], password="abcd")
        )
        # 过期链接
        expired = FormShareLink.objects.create(
            owner=self.owner,
            form=FormDefinition.objects.get(pk=form["id"]),
            token="expired-token-123",
            expires_at=timezone.now() - timedelta(days=1),
        )
        body = self.fail(
            self.api(
                self.other_c,
                "post",
                BASE + "share-links/verify/",
                {"token": expired.token},
            )
        )
        self.assertIn("过期", body["error"])
        overall = self.ok(self.api(self.owner_c, "get", BASE + "share-links/"))
        self.assertEqual(overall["count"], 2)

    def test_webhooks_delivery_retry_and_event(self):
        form, _version = self.ready_form()
        good = self.ok(
            self.api(
                self.owner_c,
                "post",
                BASE + "webhooks/",
                {
                    "form_id": form["id"],
                    "url": "https://example.com/hook",
                    "event": "submission.created",
                    "secret": "s3cret",
                },
            )
        )
        self.assertEqual(good["secret_masked"][-4:], "cret")
        tested = self.ok(
            self.api(self.owner_c, "post", f"{BASE}webhooks/{good['id']}/test/", {})
        )
        self.assertEqual(tested["delivery"]["status"], "success")
        self.assertEqual(tested["delivery"]["response_code"], 200)
        self.assertEqual(len(tested["delivery"]["signature"]), 64)
        bad = self.ok(
            self.api(
                self.owner_c,
                "post",
                BASE + "webhooks/",
                {
                    "form_id": form["id"],
                    "url": "https://fail.example.com/hook",
                    "event": "all",
                },
            )
        )
        failed = self.ok(
            self.api(self.owner_c, "post", f"{BASE}webhooks/{bad['id']}/test/", {})
        )
        self.assertEqual(failed["delivery"]["status"], "failed")
        self.assertIn("失败", failed["delivery"]["error"])
        self.assertIsNotNone(failed["delivery"]["next_retry_at"])
        retried = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}deliveries/{failed['delivery']['id']}/retry/",
                {},
            )
        )
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(retried["status"], "failed")
        # 正式提交触发 submission.created 投递（good 钩子）
        self.ok(self.submit(form["code"], base_answers()))
        deliveries = self.ok(
            self.api(
                self.owner_c,
                "get",
                f"{BASE}webhooks/{good['id']}/deliveries/",
            )
        )
        self.assertEqual(deliveries["count"], 2)
        events = {d["event"] for d in deliveries["items"]}
        self.assertIn("webhook.test", events)
        self.assertIn("submission.created", events)
        all_deliveries = self.ok(self.api(self.owner_c, "get", BASE + "deliveries/"))
        self.assertGreaterEqual(all_deliveries["count"], 3)
        # 非法 URL 被拒绝
        self.fail(
            self.api(
                self.owner_c,
                "post",
                BASE + "webhooks/",
                {"form_id": form["id"], "url": "ftp://x/hook"},
            )
        )
        self.fail(
            self.api(self.other_c, "post", f"{BASE}webhooks/{good['id']}/test/", {})
        )
        self.ok(self.api(self.owner_c, "delete", f"{BASE}webhooks/{bad['id']}/"))

    def test_templates_and_quiz_scoring(self):
        listing = self.ok(self.api(self.owner_c, "get", BASE + "templates/"))
        self.assertGreaterEqual(listing["count"], 6)
        self.assertIn("调研", listing["categories"])
        quiz_tpl = [x for x in listing["items"] if x["name"] == "基础知识测验"][0]
        detail = self.ok(self.api(self.owner_c, "get", f"{BASE}templates/{quiz_tpl['id']}/"))
        self.assertIn("schema", detail)
        self.assertEqual(detail["form_type"], "quiz")
        created = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}templates/{quiz_tpl['id']}/instantiate/",
                {"name": "季度测验"},
            )
        )
        form = created["form"]
        self.assertEqual(form["status"], "draft")
        self.assertEqual(form["form_type"], "quiz")
        self.publish(form["id"])
        good = {
            "q1": "def",
            "q2": ["get", "put", "delete"],
            "q3": True,
            "q4": 48,
        }
        data = self.ok(self.submit(form["code"], good, client=self.other_c))
        self.assertEqual(data["submission"]["score"], 100)
        self.assertEqual(data["submission"]["max_score"], 100)
        bad = {"q1": "func", "q2": ["get"], "q3": False, "q4": 1}
        data = self.ok(self.submit(form["code"], bad, client=self.third_c))
        self.assertEqual(data["submission"]["score"], 10)
        self.assertLess(data["submission"]["score"], data["submission"]["max_score"])
        # 从模板创建接口
        created2 = self.ok(
            self.api(
                self.owner_c,
                "post",
                BASE + "forms/from-template/",
                {"template_id": quiz_tpl["id"], "name": "复制测验"},
            )
        )
        self.assertEqual(created2["form_type"], "quiz")
        self.assertGreater(created2["field_count"], 0)

    def test_template_clone_and_save(self):
        form, _version = self.ready_form()
        clone = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/clone/",
                {"name": "副本表单"},
            )
        )
        self.assertNotEqual(clone["id"], form["id"])
        self.assertEqual(clone["status"], "draft")
        fields = self.ok(self.api(self.owner_c, "get", f"{BASE}forms/{clone['id']}/fields/"))
        self.assertEqual(fields["count"], 10)
        tpl = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/save-as-template/",
                {"name": "我的模板"},
            )
        )
        self.assertFalse(tpl["builtin"])
        self.assertEqual(tpl["field_count"], 10)
        detail = self.ok(self.api(self.owner_c, "get", f"{BASE}templates/{tpl['id']}/"))
        self.assertIn("schema", detail)


class AnalyticsReviewCommentTests(FormStudioTestBase):
    """统计/导出、审核任务与评论。"""

    def test_stats_and_csv_export(self):
        form, _version = self.ready_form()
        answers = base_answers()
        answers["name"] = "=SUM(1,1)"
        self.ok(self.submit(form["code"], answers))
        answers2 = base_answers()
        answers2["plan"] = "basic"
        answers2["score"] = 2
        answers2["tags"] = ["c"]
        self.ok(self.submit(form["code"], answers2, client=self.third_c))
        overview = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/stats/")
        )
        self.assertEqual(overview["final"], 2)
        self.assertEqual(overview["by_status"]["submitted"], 2)
        self.assertAlmostEqual(overview["completion_rate"], 100.0)
        self.assertGreater(overview["avg_score"], 0)
        self.assertEqual(overview["webhooks"]["hooks"], 0)
        fields = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/stats/fields/")
        )
        plan = [f for f in fields["fields"] if f["field_key"] == "plan"][0]
        dist = {x["value"]: x["count"] for x in plan["distribution"]}
        self.assertEqual(dist.get("pro"), 1)
        self.assertEqual(dist.get("basic"), 1)
        age = [f for f in fields["fields"] if f["field_key"] == "age"][0]
        self.assertEqual(age["stats"]["count"], 2)
        self.assertEqual(age["stats"]["avg"], 30)
        one_field = self.ok(
            self.api(
                self.owner_c,
                "get",
                f"{BASE}forms/{form['id']}/stats/fields/",
                {"field_key": "plan"},
            )
        )
        self.assertEqual(len(one_field["fields"]), 1)
        trend = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/stats/trend/", {"days": 7})
        )
        self.assertEqual(len(trend["series"]), 7)
        self.assertEqual(trend["total"], 2)
        duration = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/stats/duration/")
        )
        self.assertIn("buckets", duration)
        snap = self.ok(
            self.api(self.owner_c, "post", f"{BASE}forms/{form['id']}/stats/snapshots/", {})
        )
        self.assertEqual(snap["submissions"], 2)
        snaps = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/stats/snapshots/")
        )
        self.assertEqual(snaps["count"], 1)
        # CSV 导出（仅 owner）+ 公式注入防护
        self.fail(self.api(self.other_c, "get", f"{BASE}forms/{form['id']}/export/"))
        csv_data = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/export/")
        )
        self.assertEqual(csv_data["row_count"], 2)
        self.assertTrue(csv_data["content"].startswith("\ufeff"))
        self.assertIn("姓名", csv_data["columns"])
        self.assertIn("'=SUM", csv_data["content"])
        self.assertIn("提交ID", csv_data["content"])

    def test_approval_review_tasks(self):
        listing = self.ok(self.api(self.owner_c, "get", BASE + "templates/"))
        tpl = [x for x in listing["items"] if x["name"] == "用印审批申请"][0]
        created = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}templates/{tpl['id']}/instantiate/",
                {"name": "用印审批"},
            )
        )
        form = created["form"]
        self.publish(form["id"])
        answers = {
            "applicant": "李四",
            "seal_type": "official",
            "copies": 2,
            "use_date": "2026-03-01",
            "purpose": "合同用印",
            "urgent": False,
        }
        data = self.ok(self.submit(form["code"], answers))
        sub_id = data["submission"]["id"]
        tasks = self.ok(
            self.api(self.owner_c, "get", BASE + "review-tasks/mine/", {"status": "pending"})
        )
        self.assertEqual(tasks["count"], 1)
        task_id = tasks["items"][0]["id"]
        self.assertFalse(tasks["items"][0]["overdue"])
        # 无关用户不能处理
        self.fail(
            self.api(
                self.third_c,
                "post",
                f"{BASE}review-tasks/{task_id}/decide/",
                {"approve": True},
            )
        )
        decided = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}review-tasks/{task_id}/decide/",
                {"approve": True, "conclusion": "同意"},
            )
        )
        self.assertEqual(decided["task"]["status"], "approved")
        self.assertEqual(decided["submission"]["status"], "reviewed")
        self.assertEqual(decided["submission"]["review_note"], "同意")
        # 再提交一单走驳回
        data2 = self.ok(self.submit(form["code"], answers, client=self.third_c))
        sub2 = data2["submission"]["id"]
        tasks = self.ok(
            self.api(self.owner_c, "get", BASE + "review-tasks/mine/", {"status": "pending"})
        )
        self.assertEqual(tasks["count"], 1)
        self.fail(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}submissions/{sub2}/reject/",
                {"conclusion": ""},
            )
        )
        rejected = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}submissions/{sub2}/reject/",
                {"conclusion": "材料不全"},
            )
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["review_note"], "材料不全")
        mine = self.ok(
            self.api(self.owner_c, "get", BASE + "review-tasks/mine/", {"status": "pending"})
        )
        self.assertEqual(mine["count"], 0)

    def test_comments_visibility_and_resolve(self):
        form, _version = self.ready_form()
        data = self.ok(self.submit(form["code"], base_answers()))
        sub_id = data["submission"]["id"]
        internal = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/comments/",
                {"body": "内部备注", "submission_id": sub_id, "visibility": "internal"},
            )
        )
        public = self.ok(
            self.api(
                self.other_c,
                "post",
                f"{BASE}forms/{form['id']}/comments/",
                {"body": "申请人补充", "submission_id": sub_id, "visibility": "internal"},
            )
        )
        # 非管理者发评论会被降级为 public
        self.assertEqual(public["visibility"], "public")
        owner_list = self.ok(
            self.api(self.owner_c, "get", f"{BASE}forms/{form['id']}/comments/")
        )
        self.assertEqual(owner_list["count"], 2)
        other_list = self.ok(
            self.api(self.other_c, "get", f"{BASE}forms/{form['id']}/comments/")
        )
        self.assertEqual(other_list["count"], 1)
        self.assertEqual(other_list["items"][0]["body"], "申请人补充")
        resolved = self.ok(
            self.api(
                self.owner_c,
                "patch",
                f"{BASE}comments/{internal['id']}/resolve/",
                {"resolved": True},
            )
        )
        self.assertTrue(resolved["resolved"])
        reply = self.ok(
            self.api(
                self.owner_c,
                "post",
                f"{BASE}forms/{form['id']}/comments/",
                {"body": "回复你", "parent_id": public["id"]},
            )
        )
        self.assertEqual(reply["parent_id"], public["id"])
        # 第三方无法评论未参与的表单
        self.fail(
            self.api(
                self.third_c,
                "post",
                f"{BASE}forms/{form['id']}/comments/",
                {"body": "路过"},
            )
        )

    def test_form_actions_close_archive_and_delete_guard(self):
        form, _version = self.ready_form()
        self.ok(self.submit(form["code"], base_answers()))
        self.fail(
            self.api(self.owner_c, "delete", f"{BASE}forms/{form['id']}/")
        )
        closed = self.ok(
            self.api(self.owner_c, "post", f"{BASE}forms/{form['id']}/close/", {})
        )
        self.assertEqual(closed["status"], "closed")
        body = self.fail(self.submit(form["code"], base_answers()))
        self.assertIn("关闭", body["error"])
        archived = self.ok(
            self.api(self.owner_c, "post", f"{BASE}forms/{form['id']}/archive/", {})
        )
        self.assertEqual(archived["status"], "archived")
        listing = self.ok(self.api(self.owner_c, "get", BASE + "forms/"))
        self.assertEqual(listing["count"], 0)
        with_archived = self.ok(
            self.api(self.owner_c, "get", BASE + "forms/", {"include_archived": 1})
        )
        self.assertEqual(with_archived["count"], 1)


class ServiceEngineTests(TestCase):
    """服务层纯函数：公式、条件、CSV 转义、schema 校验与分享 token。"""

    def test_formula_engine_is_safe(self):
        self.assertEqual(services.evaluate_formula("{a}+{b}*2", {"a": 1, "b": 3}), 7)
        self.assertEqual(services.evaluate_formula("max({a},{b})", {"a": 2, "b": 9}), 9)
        self.assertEqual(services.evaluate_formula("if({a}>1,10,20)", {"a": 2}), 10)
        self.assertAlmostEqual(services.evaluate_formula("avg(1,2,3)", {}), 2)
        self.assertTrue(services.evaluate_formula("{age} >= 18", {"age": 20}))
        for expr in ("__import__('os')", "eval(1)", "{a} +", "1/0", "a+"):
            with self.assertRaises(ValueError):
                services.evaluate_formula(expr, {"a": 1})

    def test_condition_engine_operators(self):
        answers = {"a": 5, "s": "hello", "tags": ["x", "y"], "empty": ""}
        self.assertTrue(services.evaluate_condition({"field": "a", "op": "gte", "value": 5}, answers))
        self.assertTrue(services.evaluate_condition({"field": "a", "op": "between", "value": [1, 9]}, answers))
        self.assertTrue(services.evaluate_condition({"field": "s", "op": "contains", "value": "ell"}, answers))
        self.assertTrue(services.evaluate_condition({"field": "tags", "op": "in", "value": ["y"]}, answers))
        self.assertTrue(services.evaluate_condition({"field": "empty", "op": "empty"}, answers))
        self.assertTrue(
            services.evaluate_condition(
                {"all": [{"field": "a", "op": "gt", "value": 1},
                         {"any": [{"field": "s", "op": "starts_with", "value": "he"}]}]},
                answers,
            )
        )
        self.assertFalse(services.evaluate_condition({"field": "a", "op": "lt", "value": 1}, answers))
        self.assertFalse(services.evaluate_condition({"field": "a", "op": "bad_op", "value": 1}, answers))

    def test_csv_injection_guard(self):
        self.assertEqual(services.csv_cell("=1+1"), "'=1+1")
        self.assertEqual(services.csv_cell("+86"), "'+86")
        self.assertEqual(services.csv_cell("-10"), "'-10")
        self.assertEqual(services.csv_cell("@cmd"), "'@cmd")
        self.assertEqual(services.csv_cell("normal"), "normal")
        self.assertEqual(services.csv_cell(["=a", "b"]), "'=a；b")
        self.assertEqual(services.csv_cell(True), "是")

    def test_schema_issues_cover_core_rules(self):
        schema = {
            "sections": [{"key": "s1", "title": "S"}],
            "fields": [
                {"key": "1bad", "label": "Bad", "type": "nope"},
                {"key": "sel", "label": "Sel", "type": "select"},
                {"key": "m", "label": "M", "type": "matrix"},
                {"key": "t", "label": "T", "type": "text",
                 "validations": [{"rule_type": "regex", "params": {"pattern": "(["},
                                  "message": "bad"}]},
            ],
            "logic": [],
        }
        codes = {i["code"] for i in services.collect_schema_issues(schema)}
        self.assertIn("field_key", codes)
        self.assertIn("field_type", codes)
        self.assertIn("options_required", codes)
        self.assertIn("matrix_rows", codes)
        self.assertIn("regex", codes)
        with self.assertRaises(ValueError):
            services.assert_schema_valid(schema)

    def test_share_link_token_and_webhook_signature(self):
        from django.contrib.auth import get_user_model
        from formstudio.models import FormDefinition

        User = get_user_model()
        owner = User.objects.create_user(username="fs_engine", password="x")
        form = FormDefinition.objects.create(owner=owner, code="engine-form", name="引擎表单")
        link = services.create_share_link(
            form, owner, password="pass1234", max_uses=2
        )
        self.assertEqual(len(link.token), 40)
        same = services.verify_share_link(link.token, "pass1234")
        self.assertEqual(same.pk, link.pk)
        with self.assertRaises(ValueError):
            services.verify_share_link(link.token, "wrong")
        consumed = services.consume_share_link(link)
        self.assertEqual(consumed.used_count, 1)
        signature = services.sign_webhook("secret", 1700000000, '{"a":1}')
        self.assertEqual(len(signature), 64)
        self.assertNotEqual(signature, services.sign_webhook("other", 1700000000, '{"a":1}'))
