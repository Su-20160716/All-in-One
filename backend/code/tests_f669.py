# -*- coding: utf-8 -*-
"""F669–F680 代码工坊新增能力回归测试。

运行：python manage.py test code.tests_f669
"""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

User = get_user_model()


class CodeF669F680Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="f6tester", password="F6test#2026")
        cls.other = User.objects.create_user(username="f6other", password="F6test#2026")

    def setUp(self):
        # 直接签发 JWT（accounts 的 TwoFactorSecret 缺迁移，走 /api/auth/login/ 会在测试库 500）
        from rest_framework_simplejwt.tokens import RefreshToken
        self.c = Client()
        self.token = str(RefreshToken.for_user(self.user).access_token)

    def api(self, method, path, data=None):
        h = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        if method == "get":
            return self.c.get(path, data or None, **h)
        if method == "post":
            return self.c.post(path, data=json.dumps(data or {}),
                               content_type="application/json", **h)
        if method == "delete":
            return self.c.delete(path, **h)
        raise AssertionError(method)

    def js(self, resp):
        return json.loads(resp.content.decode("utf-8"))

    # ---------- F669 片段收藏夹分组 ----------
    def test_snippet_folders(self):
        r = self.api("post", "/api/code/snippets/create/",
                     {"title": "工具函数", "code": "print(1)", "folder": "工具箱",
                      "is_favorite": True})
        self.assertEqual(r.status_code, 200, r.content[:300])
        sid = self.js(r)["data"]["id"]

        r = self.api("post", "/api/code/snippets/create/",
                     {"title": "未分组", "code": "print(2)"})
        self.assertEqual(r.status_code, 200, r.content[:300])

        r = self.api("get", "/api/code/snippets/folders/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        data = self.js(r)["data"]
        names = {f["key"]: f["count"] for f in data["folders"]}
        self.assertEqual(names.get("工具箱"), 1)
        self.assertEqual(names.get("__none__"), 1)
        self.assertEqual(data["favorite_count"], 1)

        # 按组筛选
        r = self.api("get", "/api/code/snippets/", {"folder": "工具箱"})
        items = self.js(r)["data"]["items"]
        self.assertEqual([i["title"] for i in items], ["工具函数"])
        self.assertTrue(items[0]["is_favorite"])

        # 改组
        r = self.api("post", f"/api/code/snippets/{sid}/update/", {"folder": "常用"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(self.js(r)["data"]["folder"], "常用")

    # ---------- F672 测试用例批量启停 ----------
    def test_judge_skips_disabled(self):
        r = self.api("post", "/api/code/judge/", {
            "language": "python", "code": "print(input())",
            "title": "启停用例",
            "testcases": [
                {"stdin": "1", "expected": "1", "enabled": True},
                {"stdin": "2", "expected": "2", "enabled": False},
            ],
        })
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["skipped"], 1)
        # 原始序号保留（启用的是第 1 条）
        self.assertEqual(d["results"][0]["index"], 1)

    def test_judge_all_disabled_400(self):
        r = self.api("post", "/api/code/judge/", {
            "language": "python", "code": "print(1)",
            "testcases": [{"stdin": "", "expected": "1", "enabled": False}],
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("停用", self.js(r)["error"])

    # ---------- F676 运行参数预设 ----------
    def test_run_presets(self):
        r = self.api("post", "/api/code/run/presets/",
                     {"language": "python", "name": "样例输入", "stdin": "3 4\n",
                      "args": ["-O"], "timeout": 8})
        self.assertEqual(r.status_code, 200, r.content[:300])
        pid = self.js(r)["data"]["id"]

        r = self.api("get", "/api/code/run/presets/", {"language": "python"})
        items = self.js(r)["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["stdin"], "3 4\n")
        self.assertEqual(items[0]["args"], ["-O"])

        r = self.api("post", f"/api/code/run/presets/{pid}/", {"stdin": "5 6\n"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(self.js(r)["data"]["stdin"], "5 6\n")

        r = self.api("delete", f"/api/code/run/presets/{pid}/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        r = self.api("get", "/api/code/run/presets/")
        self.assertEqual(self.js(r)["data"]["items"], [])

    # ---------- F677 代码统计卡 ----------
    def test_code_stats_card(self):
        code = "\n".join(["# 注释一行", "def a():", "    return 1", "",
                          "def b():", "    return 2"])
        r = self.api("post", "/api/code/code-stats/", {"language": "python", "code": code})
        self.assertEqual(r.status_code, 200, r.content[:300])
        card = self.js(r)["data"]["card"]
        self.assertEqual(card["total_lines"], 6)
        self.assertEqual(card["function_count"], 2)
        self.assertEqual(card["comment_lines"], 1)
        self.assertGreater(card["comment_ratio_pct"], 0)
        self.assertGreater(card["bytes"], 0)

    # ---------- F680 每日一题站内提醒 ----------
    def test_daily_reminder(self):
        r = self.api("get", "/api/code/daily/reminder/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertFalse(d["solved"])
        self.assertFalse(d["notified"])

        r = self.api("post", "/api/code/daily/reminder/")
        d = self.js(r)["data"]
        self.assertTrue(d["sent"])
        self.assertTrue(d["notified"])

        # 幂等：再发一次不重复
        r = self.api("post", "/api/code/daily/reminder/")
        self.assertFalse(self.js(r)["data"]["sent"])

        from core.models import Notification
        self.assertEqual(
            Notification.objects.filter(recipient=self.user, title__startswith="每日一题提醒").count(),
            1,
        )
