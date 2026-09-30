# -*- coding: utf-8 -*-
"""代码工坊 v6 验证测试（Django TestCase）。

用 `python manage.py test code --settings=config.settings` 运行。
"""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

User = get_user_model()


class CodeV6Tests(TestCase):
    """覆盖 code app 的全部核心链路。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="v6tester", password="V6test#2026",
            email="v6@example.com",
        )
        cls.other = User.objects.create_user(
            username="v6other", password="V6test#2026",
        )

    def setUp(self):
        self.c = Client()
        r = self.c.post("/api/auth/login/",
                        data=json.dumps({"username": "v6tester", "password": "V6test#2026"}),
                        content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = json.loads(r.content.decode())
        self.token = d.get("access") or (d.get("data") or {}).get("access")
        self.assertTrue(self.token)

    # ---------- helpers ----------
    def api(self, method, path, data=None, token=None):
        h = {"HTTP_AUTHORIZATION": f"Bearer {token or self.token}"}
        if method == "get":
            return self.c.get(path, data or None, **h)
        if method == "post":
            return self.c.post(path, data=json.dumps(data or {}),
                               content_type="application/json", **h)
        if method == "patch":
            return self.c.patch(path, data=json.dumps(data or {}),
                                content_type="application/json", **h)
        return self.c.delete(path, **h)

    def js(self, resp):
        return json.loads(resp.content.decode("utf-8"))

    def mkws(self, name="测试工作区", language="python"):
        r = self.api("post", "/api/code/workspaces/create/",
                     {"name": name, "language": language, "with_entry": True})
        self.assertEqual(r.status_code, 200, r.content[:300])
        return self.js(r)["data"]

    def mkfile(self, ws_id, path, content="", language=None):
        payload = {"workspace": ws_id, "path": path, "content": content}
        if language:
            payload["language"] = language
        r = self.api("post", "/api/code/files/create/", payload)
        self.assertEqual(r.status_code, 200, r.content[:300])
        return self.js(r)["data"]

    # ==========================================================
    # 1. 元信息
    # ==========================================================

    def test_01_catalog(self):
        r = self.api("get", "/api/code/catalog/")
        self.assertEqual(r.status_code, 200)
        d = self.js(r)
        self.assertTrue(d["ok"])
        self.assertEqual(d["data"]["domain"], "code")
        self.assertEqual(len(d["data"]["capabilities"]), 8)

    def test_02_runtimes_probe(self):
        """运行时探测：python 必须可用，且降级结构完整。"""
        r = self.api("get", "/api/code/runtimes/")
        self.assertEqual(r.status_code, 200)
        d = self.js(r)["data"]
        self.assertGreaterEqual(len(d["runtimes"]), 10)
        py = [x for x in d["runtimes"] if x["key"] == "python"]
        self.assertEqual(len(py), 1)
        self.assertTrue(py[0]["available"], f"python 应可用: {py[0]}")
        # 每一个条目都必须带 available 字段（降级契约）
        for item in d["runtimes"]:
            self.assertIn("available", item)
            self.assertIn("available_hint", item)
        # 限制常量
        self.assertEqual(d["limits"]["output_limit"], 65536)
        self.assertEqual(d["limits"]["default_timeout"], 5)
        self.assertEqual(d["limits"]["max_timeout"], 30)

    def test_03_runtimes_unavailable_has_reason(self):
        """探测不到的语言必须给出可读原因，而不是消失。"""
        r = self.api("get", "/api/code/runtimes/")
        d = self.js(r)["data"]
        for item in d["runtimes"]:
            if not item["available"]:
                self.assertTrue(item["available_hint"], f"{item['key']} 缺少不可用原因")

    def test_04_languages_and_templates(self):
        r = self.api("get", "/api/code/languages/")
        d = self.js(r)["data"]
        self.assertGreaterEqual(len(d["languages"]), 10)
        for lang in d["languages"]:
            self.assertIn("template", lang)
            self.assertIn("available", lang)

        r = self.api("get", "/api/code/templates/")
        t = self.js(r)["data"]["templates"]
        self.assertGreaterEqual(len(t), 10)
        self.assertTrue(any(x["key"] == "python" for x in t))

    # ==========================================================
    # 2. 工作区
    # ==========================================================

    def test_10_workspace_create_with_entry(self):
        ws = self.mkws("新建工作区")
        self.assertTrue(ws["id"])
        self.assertEqual(len(ws["files"]), 1)
        self.assertEqual(ws["files"][0]["path"], "main.py")
        self.assertTrue(ws["files"][0]["is_entry"])

    def test_11_workspace_create_blank_name(self):
        r = self.api("post", "/api/code/workspaces/create/", {"name": "   "})
        self.assertEqual(r.status_code, 400)

    def test_12_workspace_list_detail(self):
        ws = self.mkws("列表用工作区", "javascript")
        r = self.api("get", "/api/code/workspaces/")
        items = self.js(r)["data"]["items"]
        self.assertTrue(any(x["id"] == ws["id"] for x in items))

        r = self.api("get", f"/api/code/workspaces/{ws['id']}/")
        d = self.js(r)["data"]
        self.assertIsInstance(d["tree"], list)
        self.assertIsInstance(d["stats"], dict)
        self.assertEqual(d["stats"]["file_count"], 1)

    def test_13_workspace_star_and_clone(self):
        ws = self.mkws("星标工作区")
        r = self.api("post", f"/api/code/workspaces/{ws['id']}/star/")
        self.assertTrue(self.js(r)["data"]["is_starred"])

        r = self.api("post", f"/api/code/workspaces/{ws['id']}/clone/")
        clone = self.js(r)["data"]
        self.assertNotEqual(clone["id"], ws["id"])
        self.assertEqual(len(clone["files"]), 1)
        self.assertIn("副本", clone["name"])

    def test_14_workspace_update_and_delete(self):
        ws = self.mkws("待改工作区")
        r = self.api("post", f"/api/code/workspaces/{ws['id']}/update/",
                     {"name": "改名了", "description": "新描述", "is_archived": True})
        d = self.js(r)["data"]
        self.assertEqual(d["name"], "改名了")
        self.assertTrue(d["is_archived"])

        r = self.api("post", f"/api/code/workspaces/{ws['id']}/delete/")
        self.assertEqual(self.js(r)["data"]["deleted"], ws["id"])

    def test_15_workspace_not_found(self):
        r = self.api("get", "/api/code/workspaces/999999/")
        self.assertEqual(r.status_code, 400)

    # ==========================================================
    # 3. 代码文件
    # ==========================================================

    def test_20_file_create_infers_language(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "a/b/solver.cpp", "int main(){return 0;}")
        self.assertEqual(f["language"], "cpp")
        self.assertEqual(f["name"], "solver.cpp")

    def test_21_file_duplicate_path_rejected(self):
        ws = self.mkws()
        self.mkfile(ws["id"], "dup.py", "x=1")
        r = self.api("post", "/api/code/files/create/",
                     {"workspace": ws["id"], "path": "dup.py"})
        self.assertEqual(r.status_code, 400)

    def test_22_file_path_traversal_rejected(self):
        ws = self.mkws()
        for bad in ("../evil.py", "a/../../evil.py"):
            r = self.api("post", "/api/code/files/create/",
                         {"workspace": ws["id"], "path": bad})
            self.assertEqual(r.status_code, 400, f"{bad} 应被拒绝")

    def test_23_file_tree_structure(self):
        ws = self.mkws()
        self.mkfile(ws["id"], "pkg/core.py", "x=1")
        self.mkfile(ws["id"], "pkg/sub/deep.py", "y=2")
        r = self.api("get", f"/api/code/files/tree/?workspace={ws['id']}")
        tree = self.js(r)["data"]["tree"]
        dirs = [n for n in tree if n["type"] == "dir"]
        self.assertTrue(dirs)


        pkg = next((n for n in dirs if n["name"] == "pkg"), None)
        self.assertIsNotNone(pkg, f"未找到 pkg 目录: {tree}")
        sub = next((n for n in pkg["children"] if n["name"] == "sub"), None)
        self.assertIsNotNone(sub, f"未找到 sub 子目录: {pkg['children']}")

    def test_24_file_update_recomputes_stats(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "calc.py", "a=1\n")
        self.assertEqual(f["lines"], 1)

        r = self.api("post", f"/api/code/files/{f['id']}/update/",
                     {"content": "a=1\nb=2\nc=3\n", "message": "加了 b c"})
        d = self.js(r)["data"]
        self.assertEqual(d["lines"], 3)
        self.assertTrue(d["snapshot_id"])
        self.assertGreater(d["size"], 0)

    def test_25_file_move_and_rename(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "old.py", "x=1")
        r = self.api("post", f"/api/code/files/{f['id']}/move/", {"path": "new/dir/renamed.py"})
        d = self.js(r)["data"]
        self.assertEqual(d["path"], "new/dir/renamed.py")
        self.assertEqual(d["name"], "renamed.py")

    def test_26_file_favorite_and_entry(self):
        ws = self.mkws()
        f1 = self.mkfile(ws["id"], "one.py", "x=1")
        f2 = self.mkfile(ws["id"], "two.py", "y=2")

        r = self.api("post", f"/api/code/files/{f1['id']}/favorite/")
        self.assertTrue(self.js(r)["data"]["is_favorite"])

        r = self.api("post", f"/api/code/files/{f2['id']}/entry/")
        self.assertEqual(self.js(r)["data"]["path"], "two.py")

        r = self.api("get", f"/api/code/files/{f1['id']}/")
        self.assertFalse(self.js(r)["data"]["is_entry"], "设为入口时应清掉旧的")

    def test_27_file_batch_ops(self):
        ws = self.mkws()
        a = self.mkfile(ws["id"], "ba.py", "1")
        b = self.mkfile(ws["id"], "bb.py", "2")
        r = self.api("post", "/api/code/files/batch/",
                     {"ids": [a["id"], b["id"]], "action": "favorite"})
        self.assertEqual(self.js(r)["data"]["affected"], 2)

        r = self.api("post", "/api/code/files/batch/",
                     {"ids": [a["id"]], "action": "delete"})
        self.assertEqual(self.js(r)["data"]["affected"], 1)

        r = self.api("post", "/api/code/files/batch/",
                     {"ids": [b["id"]], "action": "bogus"})
        self.assertEqual(r.status_code, 400)

    def test_28_file_filter_by_language(self):
        ws = self.mkws()
        self.mkfile(ws["id"], "f1.py", "x=1")
        self.mkfile(ws["id"], "f2.js", "let x=1")
        r = self.api("get", f"/api/code/files/?workspace={ws['id']}&language=javascript")
        items = self.js(r)["data"]["items"]
        self.assertTrue(all(x["language"] == "javascript" for x in items))
        self.assertTrue(any(x["path"] == "f2.js" for x in items))

    # ==========================================================
    # 4. 版本
    # ==========================================================

    def test_30_version_snapshot_on_update(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "v.py", "v1\n")
        self.api("post", f"/api/code/files/{f['id']}/update/", {"content": "v2\n"})
        self.api("post", f"/api/code/files/{f['id']}/update/", {"content": "v3\n"})

        r = self.api("get", f"/api/code/files/{f['id']}/versions/")
        d = self.js(r)["data"]
        self.assertGreaterEqual(len(d["items"]), 2)
        self.assertEqual(d["current"], "v3\n")
        # 最新快照应是 v2（每次保存前的内容）
        self.assertIn("v2", d["items"][0]["preview"])

    def test_31_version_diff(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "d.py", "line1\nline2\n")
        self.api("post", f"/api/code/files/{f['id']}/update/",
                 {"content": "line1\nline2\nline3\n"})
        vers = self.js(self.api("get", f"/api/code/files/{f['id']}/versions/"))["data"]["items"]
        v0 = vers[0]["id"]

        r = self.api("get", f"/api/code/files/{f['id']}/versions/diff/?from={v0}")
        d = self.js(r)["data"]
        self.assertIsInstance(d["diff"], list)
        added = [x for x in d["diff"] if x["type"] == "add"]
        self.assertTrue(any("line3" in x["text"] for x in added),
                        f"diff 应包含新增的 line3: {d['diff']}")
        self.assertGreaterEqual(d["stats"]["add"], 1)

    def test_32_version_rollback_snapshots_first(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "r.py", "original\n")
        r = self.api("post", f"/api/code/files/{f['id']}/versions/create/", {"message": "存档"})
        v = self.js(r)["data"]["id"]
        self.api("post", f"/api/code/files/{f['id']}/update/", {"content": "changed\n"})

        r = self.api("post", f"/api/code/files/{f['id']}/versions/{v}/rollback/")
        self.assertEqual(self.js(r)["data"]["content"], "original\n")

        # 回滚前的内容应被另存为快照（可逆）
        vers = self.js(self.api("get", f"/api/code/files/{f['id']}/versions/"))["data"]["items"]
        self.assertTrue(any("回滚前" in x["message"] for x in vers),
                        f"应有回滚前快照: {[x['message'] for x in vers]}")

    # ==========================================================
    # 5. 运行
    # ==========================================================

    def test_40_run_python_basic(self):
        r = self.api("post", "/api/code/run/",
                     {"language": "python", "code": "print('hello 工坊')"})
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = self.js(r)["data"]
        self.assertEqual(d["status"], "ok")
        self.assertIn("hello 工坊", d["stdout"])
        self.assertTrue(d["run_id"])
        self.assertIsInstance(d["duration_ms"], int)

    def test_41_run_with_stdin_and_args(self):
        r = self.api("post", "/api/code/run/", {
            "language": "python",
            "code": "import sys\nn = input()\nprint(n.upper(), sys.argv[1])\n",
            "stdin": "abc\n",
            "args": ["xyz"],
        })
        d = self.js(r)["data"]
        self.assertIn("ABC xyz", d["stdout"])

    def test_42_run_timeout(self):
        r = self.api("post", "/api/code/run/", {
            "language": "python",
            "code": "while True:\n    pass\n",
            "timeout": 1,
        })
        d = self.js(r)["data"]
        self.assertEqual(d["status"], "timeout")
        self.assertIn("超时", d["stdout"])

    def test_43_run_timeout_clamped(self):
        """timeout 超过上限必须被夹紧，而不是直接报错或无限等。"""
        r = self.api("post", "/api/code/run/", {
            "language": "python", "code": "print(1)", "timeout": 99999,
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.js(r)["data"]["status"], "ok")

    def test_44_run_error_structured_diagnostics(self):
        r = self.api("post", "/api/code/run/", {
            "language": "python",
            "code": "def f():\n    return 1 / 0\n\n\nf()\n",
        })
        d = self.js(r)["data"]
        self.assertEqual(d["status"], "error")
        self.assertIn("ZeroDivisionError", d["stderr"])
        diags = d["diagnostics"]
        self.assertGreaterEqual(len(diags), 1)
        self.assertEqual(diags[0]["type"], "ZeroDivisionError")
        self.assertIsInstance(diags[0]["line"], int)
        self.assertGreaterEqual(len(diags[0]["frames"]), 1)

    def test_45_run_syntax_error_diagnostics(self):
        r = self.api("post", "/api/code/run/", {
            "language": "python", "code": "def f(:\n    pass\n",
        })
        d = self.js(r)["data"]
        self.assertEqual(d["status"], "error")
        diags = d["diagnostics"]
        self.assertTrue(any(x["type"] == "SyntaxError" for x in diags),
                        f"应识别 SyntaxError: {diags}")

    def test_46_run_dangerous_rejected(self):
        for code in ("rm -rf / --no-preserve-root", "import os\nos.system('mkfs.ext4 /dev/sda1')"):
            r = self.api("post", "/api/code/run/", {"language": "bash", "code": code})
            d = self.js(r)["data"]
            self.assertEqual(d["status"], "rejected", f"应拦截: {code}")
            self.assertGreaterEqual(len(d["dangerous"]), 1)

    def test_47_run_output_truncated(self):
        r = self.api("post", "/api/code/run/", {
            "language": "python", "code": "print('x' * 300000)",
        })
        d = self.js(r)["data"]
        self.assertTrue(d["truncated"])
        self.assertLess(len(d["stdout"]), 70000)
        self.assertIn("已截断", d["stdout"])

    def test_48_run_unsupported_language_graceful(self):
        """未支持的语言必须优雅降级，绝不 500。"""
        r = self.api("post", "/api/code/run/", {"language": "cobol", "code": "DISPLAY 'x'."})
        self.assertEqual(r.status_code, 200)
        d = self.js(r)["data"]
        self.assertEqual(d["status"], "unavailable")
        self.assertEqual(d["code"], "RUNTIME_NOT_FOUND")

    def test_49_run_empty_code_400(self):
        r = self.api("post", "/api/code/run/", {"language": "python", "code": "   "})
        self.assertEqual(r.status_code, 400)

    def test_50_run_multifile(self):
        r = self.api("post", "/api/code/run/", {
            "language": "python",
            "code": "from helper import VALUE\nprint('got', VALUE)\n",
            "files": {"helper.py": "VALUE = 99\n"},
        })
        d = self.js(r)["data"]
        self.assertIn("got 99", d["stdout"], d["stderr"])

    def test_51_run_workspace_file_with_siblings(self):
        """跑工作区文件时，同工作区其它文件应作为模块可导入。"""
        ws = self.mkws()
        self.mkfile(ws["id"], "shared.py", "SHARED = 'from-sibling'\n")
        entry = self.mkfile(ws["id"], "entry.py", "")
        r = self.api("post", "/api/code/run/", {
            "file": entry["id"],
            "code": "from shared import SHARED\nprint(SHARED)\n",
        })
        d = self.js(r)["data"]
        self.assertIn("from-sibling", d["stdout"], d["stderr"])

    def test_52_run_repl(self):
        r = self.api("post", "/api/code/run/repl/", {
            "language": "python", "code": "2 ** 10", "history": [],
        })
        d = self.js(r)["data"]
        self.assertIn("1024", d["stdout"], d["stderr"])

    def test_53_run_history_and_stats(self):
        self.api("post", "/api/code/run/", {"language": "python", "code": "print(1)"})
        r = self.api("get", "/api/code/run/history/")
        self.assertGreaterEqual(len(self.js(r)["data"]["items"]), 1)

        r = self.api("get", "/api/code/run/stats/")
        d = self.js(r)["data"]
        self.assertGreaterEqual(d["total"], 1)
        self.assertEqual(len(d["heatmap"]), 365)
        self.assertGreaterEqual(len(d["by_language"]), 1)
        # 热力图日期必须连续升序
        dates = [c["date"] for c in d["heatmap"]]
        self.assertEqual(dates, sorted(dates))

    def test_54_run_detail_and_delete(self):
        r = self.api("post", "/api/code/run/", {"language": "python", "code": "print('detail')"})
        rid = self.js(r)["data"]["run_id"]
        r = self.api("get", f"/api/code/run/{rid}/")
        self.assertIn("detail", self.js(r)["data"]["stdout"])
        r = self.api("post", f"/api/code/run/{rid}/delete/")
        self.assertEqual(self.js(r)["data"]["deleted"], 1)

    # ==========================================================
    # 6. 判题
    # ==========================================================

    def test_60_judge_all_accepted(self):
        r = self.api("post", "/api/code/judge/", {
            "language": "python",
            "code": "a, b = map(int, input().split())\nprint(a + b)\n",
            "title": "A+B",
            "testcases": [
                {"stdin": "1 2\n", "expected": "3\n"},
                {"stdin": "10 20\n", "expected": "30\n"},
                {"stdin": "0 0\n", "expected": "0\n"},
            ],
        })
        d = self.js(r)["data"]
        self.assertEqual(d["verdict"], "accepted")
        self.assertEqual(d["passed"], 3)
        self.assertEqual(d["total"], 3)
        self.assertTrue(d["accepted"])

    def test_61_judge_wrong_answer(self):
        r = self.api("post", "/api/code/judge/", {
            "language": "python", "code": "print(0)\n",
            "testcases": [{"stdin": "1 2\n", "expected": "3\n"}],
        })
        d = self.js(r)["data"]
        self.assertEqual(d["verdict"], "wrong_answer")
        self.assertEqual(d["passed"], 0)
        self.assertIn("expected", d["results"][0])
        self.assertIn("actual", d["results"][0])

    def test_62_judge_time_limit(self):
        r = self.api("post", "/api/code/judge/", {
            "language": "python", "code": "while True: pass",
            "timeout": 1,
            "testcases": [{"stdin": "", "expected": "never"}],
        })
        d = self.js(r)["data"]
        self.assertEqual(d["verdict"], "time_limit")

    def test_63_judge_whitespace_tolerant(self):
        """默认忽略行尾空白，避免因格式细节误判。"""
        r = self.api("post", "/api/code/judge/", {
            "language": "python", "code": "print('ok')\n",
            "testcases": [{"stdin": "", "expected": "ok  \n\n"}],
        })
        self.assertEqual(self.js(r)["data"]["verdict"], "accepted")

    def test_64_judge_empty_cases_400(self):
        r = self.api("post", "/api/code/judge/",
                     {"language": "python", "code": "print(1)", "testcases": []})
        self.assertEqual(r.status_code, 400)

    def test_65_judge_history_and_leaderboard(self):
        self.api("post", "/api/code/judge/", {
            "language": "python", "code": "print(1)",
            "title": "榜单项", "testcases": [{"stdin": "", "expected": "1"}],
        })
        r = self.api("get", "/api/code/judge/history/")
        self.assertGreaterEqual(len(self.js(r)["data"]["items"]), 1)

        r = self.api("get", "/api/code/leaderboard/")
        items = self.js(r)["data"]["items"]
        self.assertGreaterEqual(len(items), 1)
        self.assertIn("solved", items[0])
        self.assertIn("rank", items[0])

    # ==========================================================
    # 7. 静态分析
    # ==========================================================

    MESSY = (
        "import os\n"
        "password = 'hunter2secret'\n"
        "def f(x):\n"
        "    if x:\n"
        "        for i in range(10):\n"
        "            for j in range(10):\n"
        "                print(i, j)\n"
        "    return eval(x)\n"
        "    # TODO: fix this\n"
    )

    def test_70_analyze_metrics_and_complexity(self):
        r = self.api("post", "/api/code/analyze/", {"language": "python", "code": self.MESSY})
        d = self.js(r)["data"]
        self.assertEqual(d["metrics"]["functions"], 1)
        self.assertEqual(d["complexity"]["max_loop_depth"], 2)
        self.assertIn("O(n^2)", d["complexity"]["big_o"])

    def test_71_analyze_lint_rules(self):
        r = self.api("post", "/api/code/analyze/", {"language": "python", "code": self.MESSY})
        rules = {i["rule"] for i in self.js(r)["data"]["issues"]}
        for expected in ("hardcoded-secret", "unsafe-eval", "todo", "debug-print"):
            self.assertIn(expected, rules, f"缺少规则 {expected}: {rules}")

    def test_72_analyze_bare_except(self):
        code = "try:\n    x = 1\nexcept:\n    pass\n"
        r = self.api("post", "/api/code/analyze/", {"language": "python", "code": code})
        rules = {i["rule"] for i in self.js(r)["data"]["issues"]}
        self.assertIn("bare-except", rules)

    def test_73_outline(self):
        code = "class A:\n    def m1(self):\n        pass\n\n    def m2(self):\n        pass\n\n\ndef top():\n    pass\n"
        r = self.api("post", "/api/code/outline/", {"language": "python", "code": code})
        ol = self.js(r)["data"]["outline"]
        names = {n["name"] for n in ol}
        self.assertIn("A", names)
        self.assertIn("top", names)
        cls = next(n for n in ol if n["name"] == "A")
        self.assertEqual(len(cls.get("children", [])), 2, cls)

    def test_74_outline_cpp(self):
        code = "#include <iostream>\nclass Foo {\npublic:\n    int bar() { return 1; }\n};\n\nint main() { return 0; }\n"
        r = self.api("post", "/api/code/outline/", {"language": "cpp", "code": code})
        ol = self.js(r)["data"]["outline"]
        self.assertTrue(any(n["name"] == "Foo" for n in ol), ol)

    def test_75_quality_score(self):
        r = self.api("post", "/api/code/quality/", {"language": "python", "code": self.MESSY})
        d = self.js(r)["data"]
        self.assertLess(d["score"], 100)
        self.assertIn(d["grade"], ("A", "B", "C", "D", "F"))
        self.assertEqual(len(d["dimensions"]), 4)
        self.assertIn("severity", d)

    def test_76_quality_clean_code_scores_higher(self):
        clean = (
            '"""工具模块。"""\n\n\n'
            "def add(a: int, b: int) -> int:\n"
            '    """返回两数之和。"""\n'
            "    return a + b\n"
        )
        r1 = self.api("post", "/api/code/quality/", {"language": "python", "code": clean})
        r2 = self.api("post", "/api/code/quality/", {"language": "python", "code": self.MESSY})
        self.assertGreater(self.js(r1)["data"]["score"], self.js(r2)["data"]["score"])

    def test_77_flow_nodes(self):
        r = self.api("post", "/api/code/flow/", {"language": "python", "code": self.MESSY})
        d = self.js(r)["data"]
        types = {n["type"] for n in d["nodes"]}
        self.assertIn("start", types)
        self.assertIn("end", types)
        self.assertTrue(types & {"loop", "condition", "function"}, types)
        self.assertGreaterEqual(len(d["edges"]), 1)

    def test_78_similarity(self):
        ws = self.mkws()
        base = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
        self.mkfile(ws["id"], "orig.py", base)
        near = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n# note\n"
        r = self.api("post", "/api/code/similarity/",
                     {"workspace": ws["id"], "language": "python", "code": near})
        d = self.js(r)["data"]
        self.assertGreaterEqual(len(d["matches"]), 1)
        self.assertGreater(d["matches"][0]["similarity"], 0.4, d["matches"])

    def test_79_secret_scan(self):
        code = ('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
                'GH = "ghp_1234567890abcdefghijklmnopqrstuvwx"\n'
                'db = "postgres://user:pass123@10.0.0.5:5432/db"\n')
        r = self.api("post", "/api/code/secret-scan/", {"language": "python", "code": code})
        d = self.js(r)["data"]
        types = {f["type"] for f in d["findings"]}
        self.assertIn("AWS Access Key", types)
        self.assertIn("GitHub Token", types)
        self.assertEqual(d["risk"], "high")
        # 敏感值必须脱敏
        for f in d["findings"]:
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", f["masked"])

    def test_80_secret_scan_private_key(self):
        code = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----\n"
        r = self.api("post", "/api/code/secret-scan/", {"language": "python", "code": code})
        types = {f["type"] for f in self.js(r)["data"]["findings"]}
        self.assertIn("私钥文件", types)

    def test_81_refactor_hints(self):
        r = self.api("post", "/api/code/refactor-hints/",
                     {"language": "python", "code": self.MESSY})
        d = self.js(r)["data"]
        self.assertGreaterEqual(d["count"], 1)
        self.assertEqual(d["source"], "local")
        titles = " ".join(h["title"] for h in d["hints"])
        self.assertTrue("嵌套" in titles or "复杂度" in titles, titles)

    # ==========================================================
    # 8. AI
    # ==========================================================

    def test_90_ai_status(self):
        r = self.api("get", "/api/code/ai/status/")
        d = self.js(r)["data"]
        self.assertIn("llm", d)
        self.assertGreaterEqual(len(d["local_capabilities"]), 5)

    def test_91_ai_generate_always_returns_code(self):
        """无论 LLM 是否可用，都必须返回可用的代码（降级契约）。"""
        r = self.api("post", "/api/code/ai/generate/",
                     {"language": "python", "instruction": "读入整数并输出平方"})
        d = self.js(r)["data"]
        self.assertTrue(d["code"].strip())
        self.assertIn(d["source"], ("llm", "local"))
        if d["source"] == "local":
            self.assertIn("note", d)

    def test_92_ai_generate_empty_instruction_400(self):
        r = self.api("post", "/api/code/ai/generate/",
                     {"language": "python", "instruction": ""})
        self.assertEqual(r.status_code, 400)

    def test_93_ai_transform_all_actions(self):
        actions = ["explain", "find_bugs", "refactor", "tests",
                   "testdata", "reverse_question", "review", "comment"]
        for act in actions:
            r = self.api("post", "/api/code/ai/transform/",
                         {"action": act, "language": "python", "code": self.MESSY})
            self.assertEqual(r.status_code, 200, f"{act}: {r.content[:200]}")
            d = self.js(r)["data"]
            self.assertTrue(d["result"].strip(), f"{act} 结果为空")
            self.assertIn(d["source"], ("llm", "local"))

    def test_94_ai_transform_translate(self):
        r = self.api("post", "/api/code/ai/transform/",
                     {"action": "translate", "language": "python",
                      "code": "print(1)", "target": "javascript"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.js(r)["data"]["result"].strip())

    def test_95_ai_transform_bad_action_400(self):
        r = self.api("post", "/api/code/ai/transform/",
                     {"action": "explode", "language": "python", "code": "x=1"})
        self.assertEqual(r.status_code, 400)

    def test_96_ai_transform_empty_code_400(self):
        r = self.api("post", "/api/code/ai/transform/",
                     {"action": "explain", "language": "python", "code": ""})
        self.assertEqual(r.status_code, 400)

    def test_97_ai_error_explain(self):
        r = self.api("post", "/api/code/ai/error-explain/", {
            "language": "python", "code": "print(1/0)\n",
            "error": 'Traceback (most recent call last):\n  File "main.py", line 1, in <module>\n    print(1/0)\nZeroDivisionError: division by zero\n',
        })
        d = self.js(r)["data"]
        text = d["result"]
        self.assertTrue("ZeroDivisionError" in text or "除数为 0" in text, text[:300])

    def test_98_ai_error_explain_falls_back_to_last_run(self):
        """不传 error 时应从最近一次运行记录里取。"""
        self.api("post", "/api/code/run/", {"language": "python", "code": "print(1/0)\n"})
        r = self.api("post", "/api/code/ai/error-explain/",
                     {"language": "python", "code": "print(1/0)\n"})
        d = self.js(r)["data"]
        self.assertTrue(d["result"].strip())

    def test_99_ai_error_explain_no_error_400(self):
        r = self.api("post", "/api/code/ai/error-explain/",
                     {"language": "python", "code": "print(1)"})
        self.assertEqual(r.status_code, 400)

    def test_a0_ai_inline(self):
        r = self.api("post", "/api/code/ai/inline/",
                     {"language": "python", "prefix": "def calc(a, b", "suffix": ""})
        self.assertEqual(r.status_code, 200)
        self.assertIn("completion", self.js(r)["data"])

    def test_a1_ai_inline_empty_prefix(self):
        r = self.api("post", "/api/code/ai/inline/",
                     {"language": "python", "prefix": "", "suffix": ""})
        self.assertEqual(self.js(r)["data"]["completion"], "")

    def test_a2_ai_inline_local_python_colon(self):
        """本地补全：if 语句缺冒号应补上。"""
        r = self.api("post", "/api/code/ai/inline/",
                     {"language": "python", "prefix": "    if x > 0", "suffix": ""})
        d = self.js(r)["data"]
        self.assertIn(d["source"], ("llm", "local"))
        if d["source"] == "local":
            self.assertEqual(d["completion"], ":")

    def test_a3_ai_regex_and_nl2sql_and_path(self):
        for path, payload in (
            ("/api/code/ai/regex/", {"instruction": "匹配邮箱", "language": "python"}),
            ("/api/code/ai/nl2sql/", {"instruction": "查询用户数", "schema": "u(id, name)"}),
            ("/api/code/ai/learning-path/", {"goal": "学算法"}),
        ):
            r = self.api("post", path, payload)
            self.assertEqual(r.status_code, 200, f"{path}: {r.content[:200]}")
            self.assertTrue(self.js(r)["data"]["result"].strip(), path)

    def test_a4_ai_chat_edit(self):
        r = self.api("post", "/api/code/ai/chat-edit/", {
            "language": "python", "code": "def add(a,b):\n    return a-b\n",
            "instruction": "改成加法",
        })
        d = self.js(r)["data"]
        self.assertIn("code", d)
        self.assertIn(d["source"], ("llm", "local"))

    def test_a5_ai_apply_to_file(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "apply.py", "old\n")
        r = self.api("post", f"/api/code/ai/apply/{f['id']}/",
                     {"code": "new content\n", "message": "AI 应用"})
        d = self.js(r)["data"]
        self.assertTrue(d["changed"])
        self.assertEqual(d["file"]["content"], "new content\n")

        # 应留下"AI 修改前快照"
        vers = self.js(self.api("get", f"/api/code/files/{f['id']}/versions/"))["data"]["items"]
        self.assertTrue(any("AI 修改前" in x["message"] for x in vers))

    def test_a6_ai_apply_same_content_no_change(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "same.py", "same\n")
        r = self.api("post", f"/api/code/ai/apply/{f['id']}/", {"code": "same\n"})
        self.assertFalse(self.js(r)["data"]["changed"])

    # ==========================================================
    # 9. 片段库
    # ==========================================================

    def test_b0_snippet_crud(self):
        r = self.api("post", "/api/code/snippets/create/", {
            "title": "快速排序", "description": "经典实现",
            "code": "def qsort(a):\n    return a if len(a) <= 1 else qsort([x for x in a[1:] if x < a[0]]) + [a[0]] + qsort([x for x in a[1:] if x >= a[0]])\n",
            "tags": ["排序", "算法"],
        })
        d = self.js(r)["data"]
        sid = d["id"]
        self.assertEqual(d["language"], "python", "应从代码猜出语言")
        self.assertEqual(d["tags"], ["排序", "算法"])

        r = self.api("get", f"/api/code/snippets/{sid}/")
        self.assertEqual(self.js(r)["data"]["title"], "快速排序")

        r = self.api("post", f"/api/code/snippets/{sid}/update/",
                     {"title": "快排 v2", "tags": ["排序"]})
        self.assertEqual(self.js(r)["data"]["title"], "快排 v2")

        r = self.api("post", f"/api/code/snippets/{sid}/delete/")
        self.assertEqual(self.js(r)["data"]["deleted"], sid)

    def test_b1_snippet_search_and_tags(self):
        self.api("post", "/api/code/snippets/create/",
                 {"title": "二分查找", "code": "def bs(a,x):\n    pass\n", "tags": ["搜索"]})
        r = self.api("get", "/api/code/snippets/?q=二分")
        self.assertGreaterEqual(len(self.js(r)["data"]["items"]), 1)

        r = self.api("get", "/api/code/snippets/?tag=搜索")
        self.assertGreaterEqual(len(self.js(r)["data"]["items"]), 1)

        r = self.api("get", "/api/code/snippets/tags/")
        tags = self.js(r)["data"]["tags"]
        self.assertTrue(any(t["name"] == "搜索" for t in tags), tags)
        self.assertTrue(all("count" in t for t in tags))

    def test_b2_snippet_copy_and_from_file(self):
        r = self.api("post", "/api/code/snippets/create/",
                     {"title": "源片段", "code": "x = 1\n"})
        sid = self.js(r)["data"]["id"]

        r = self.api("post", f"/api/code/snippets/{sid}/copy/", {"into_mine": True})
        self.assertIn("副本", self.js(r)["data"]["title"])

        ws = self.mkws()
        f = self.mkfile(ws["id"], "src.py", "print('from file')\n")
        r = self.api("post", "/api/code/snippets/from-file/", {"file": f["id"]})
        self.assertTrue(self.js(r)["data"]["id"])

    def test_b3_snippet_bad_scope(self):
        r = self.api("post", "/api/code/snippets/create/",
                     {"title": "x", "code": "x=1", "scope": "galaxy"})
        self.assertEqual(r.status_code, 400)

    def test_b4_snippet_empty_title_400(self):
        r = self.api("post", "/api/code/snippets/create/", {"title": "", "code": "x=1"})
        self.assertEqual(r.status_code, 400)

    # ==========================================================
    # 10. 协作
    # ==========================================================

    def test_c0_comment_thread(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "c.py", "line1\nline2\n")
        r = self.api("post", f"/api/code/files/{f['id']}/comments/create/",
                     {"line": 2, "content": "这里有问题"})
        cid = self.js(r)["data"]["id"]
        self.assertEqual(self.js(r)["data"]["line"], 2)

        self.api("post", f"/api/code/files/{f['id']}/comments/create/",
                 {"line": 2, "content": "同意", "parent": cid})

        r = self.api("get", f"/api/code/files/{f['id']}/comments/")
        d = self.js(r)["data"]
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(len(d["items"][0]["replies"]), 1)
        self.assertEqual(d["unresolved"], 1)

        r = self.api("post", f"/api/code/files/{f['id']}/comments/{cid}/resolve/")
        self.assertTrue(self.js(r)["data"]["resolved"])

        r = self.api("get", f"/api/code/files/{f['id']}/comments/")
        self.assertEqual(self.js(r)["data"]["unresolved"], 0)

    def test_c1_comment_delete_permission(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "perm.py", "x\n")
        r = self.api("post", f"/api/code/files/{f['id']}/comments/create/",
                     {"line": 1, "content": "mine"})
        cid = self.js(r)["data"]["id"]
        r = self.api("post", f"/api/code/files/{f['id']}/comments/{cid}/delete/")
        self.assertEqual(self.js(r)["data"]["deleted"], cid)

    def test_c2_comment_empty_content_400(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "e.py", "x\n")
        r = self.api("post", f"/api/code/files/{f['id']}/comments/create/",
                     {"line": 1, "content": "  "})
        self.assertEqual(r.status_code, 400)

    def test_c3_collab_state_and_ws_info(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "collab.py", "code\n")
        r = self.api("get", f"/api/code/files/{f['id']}/collab/")
        d = self.js(r)["data"]
        self.assertEqual(d["file"], f["id"])
        self.assertEqual(d["revision"], 0)

        r = self.api("get", f"/api/code/files/{f['id']}/collab/ws/")
        d = self.js(r)["data"]
        self.assertEqual(d["path"], f"/ws/code/{f['id']}/")
        self.assertEqual(len(d["message_types"]), 7)
        self.assertEqual(d["max_update_log"], 200)

    # ==========================================================
    # 11. 分享
    # ==========================================================

    def test_d0_share_lifecycle(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "share.py", "print('shared')\n")
        r = self.api("post", "/api/code/shares/create/",
                     {"file": f["id"], "allow_run": False})
        token = self.js(r)["data"]["token"]
        self.assertTrue(token)

        r = self.api("get", "/api/code/shares/")
        self.assertGreaterEqual(len(self.js(r)["data"]["items"]), 1)

        r = self.api("post", f"/api/code/shares/{token}/", {"allow_run": True})
        self.assertTrue(self.js(r)["data"]["allow_run"])

        r = self.api("post", f"/api/code/shares/{token}/revoke/")
        self.assertEqual(self.js(r)["data"]["deleted"], 1)

    def test_d1_public_share_no_auth(self):
        """公开分享必须免登录可读，且不泄露任何用户信息。"""
        ws = self.mkws()
        f = self.mkfile(ws["id"], "pub.py", "print('public')\n")
        r = self.api("post", "/api/code/shares/create/", {"file": f["id"]})
        token = self.js(r)["data"]["token"]

        anon = Client()
        r = anon.get(f"/api/share/code/{token}/")
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.content.decode())["data"]
        self.assertIn("public", d["code"])
        self.assertNotIn("owner", d)
        self.assertNotIn("owner_id", d)
        self.assertNotIn("id", d)

    def test_d2_public_share_bad_token(self):
        anon = Client()
        r = anon.get("/api/share/code/totallyinvalidtoken999/")
        self.assertEqual(r.status_code, 404)

    def test_d3_share_requires_target(self):
        r = self.api("post", "/api/code/shares/create/", {})
        self.assertEqual(r.status_code, 400)

    def test_d4_share_view_count(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "cnt.py", "x\n")
        r = self.api("post", "/api/code/shares/create/", {"file": f["id"]})
        token = self.js(r)["data"]["token"]
        anon = Client()
        anon.get(f"/api/share/code/{token}/")
        anon.get(f"/api/share/code/{token}/")
        items = self.js(self.api("get", "/api/code/shares/"))["data"]["items"]
        hit = next(x for x in items if x["token"] == token)
        self.assertEqual(hit["view_count"], 2)

    # ==========================================================
    # 12. 导出
    # ==========================================================

    def test_e0_export_zip(self):
        ws = self.mkws("导出工作区")
        self.mkfile(ws["id"], "a.py", "x=1\n")
        self.mkfile(ws["id"], "sub/b.py", "y=2\n")
        r = self.api("post", "/api/code/export/zip/", {"workspace": ws["id"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/zip")
        self.assertIn("attachment", r["Content-Disposition"])

        import io
        import zipfile
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        self.assertIn("a.py", names)
        self.assertIn("sub/b.py", names)
        self.assertIn("README.md", names)
        self.assertIn("导出工作区", zf.read("README.md").decode("utf-8"))

    def test_e1_export_zip_missing_workspace_400(self):
        r = self.api("post", "/api/code/export/zip/", {})
        self.assertEqual(r.status_code, 400)

    def test_e2_export_single_file(self):
        ws = self.mkws()
        f = self.mkfile(ws["id"], "single.py", "print('single')\n")
        r = self.api("get", f"/api/code/export/file/{f['id']}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("single", r.content.decode("utf-8"))

    # ==========================================================
    # 13. 权限与兜底
    # ==========================================================

    def test_f0_anonymous_denied(self):
        anon = Client()
        for path in ("/api/code/workspaces/", "/api/code/files/",
                     "/api/code/run/history/", "/api/code/snippets/"):
            r = anon.get(path)
            self.assertIn(r.status_code, (401, 403), f"{path} 应拒绝匿名")

    def test_f1_cross_user_isolation(self):
        """用户 A 的工作区，用户 B 不能读。"""
        ws = self.mkws("A 的私有工作区")
        c2 = Client()
        c2.post("/api/auth/login/",
                data=json.dumps({"username": "v6other", "password": "V6test#2026"}),
                content_type="application/json")
        d = json.loads(c2.post("/api/auth/login/",
                               data=json.dumps({"username": "v6other", "password": "V6test#2026"}),
                               content_type="application/json").content.decode())
        tok2 = d.get("access") or (d.get("data") or {}).get("access")
        r = self.api("get", f"/api/code/workspaces/{ws['id']}/", token=tok2)
        self.assertEqual(r.status_code, 400, "不应能访问其他用户的工作区")

    def test_f2_never_500_on_bad_input(self):
        """契约：任何异常入参只能返回 400/422，绝不 500。"""
        cases = [
            ("/api/code/analyze/", {"language": "python", "code": None}),
            ("/api/code/run/", {"language": "python"}),
            ("/api/code/run/", {"language": "python", "timeout": "abc", "code": "print(1)"}),
            ("/api/code/outline/", {"language": 123, "code": "x"}),
            ("/api/code/quality/", {}),
            ("/api/code/similarity/", {"language": "python", "code": "x"}),
            ("/api/code/run/repl/", {"language": "python", "code": "x", "history": "notalist"}),
            ("/api/code/snippets/create/", {"title": 123, "code": None}),
        ]
        for path, payload in cases:
            r = self.api("post", path, payload)
            self.assertNotEqual(r.status_code, 500,
                                f"{path} 返回了 500: {r.content[:300]}")
            self.assertIn(r.status_code, (200, 400, 422), f"{path} 状态码异常")

    def test_f3_full_text_index_hooked(self):
        """代码文件保存后应自动进入全文索引。"""
        from core.search import search
        ws = self.mkws()
        self.mkfile(ws["id"], "indexme.py", "def unique_marker_fn_zzz():\n    return 'xyzzy_marker'\n")
        res = search("xyzzy_marker", user=self.user, kinds=["code"], limit=10)
        items = res.get("items") if isinstance(res, dict) else res
        self.assertTrue(items, f"代码文件未进入全文索引: {res}")

    def test_f4_limits_probe_cached(self):
        """运行时探测应带缓存，重复调用结果一致。"""
        r1 = self.js(self.api("get", "/api/code/runtimes/"))["data"]
        r2 = self.js(self.api("get", "/api/code/runtimes/"))["data"]
        self.assertEqual(r1["available_count"], r2["available_count"])

    def test_f5_force_refresh_probe(self):
        r = self.js(self.api("get", "/api/code/runtimes/?force=true"))["data"]
        self.assertGreaterEqual(r["total_count"], 10)
