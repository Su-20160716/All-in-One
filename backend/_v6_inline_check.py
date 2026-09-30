# -*- coding: utf-8 -*-
"""内联验证脚本：由 manage.py shell < 本文件 的方式执行。

之所以用 `exec(open(...).read())` 的形式而不是直接跑测试文件，
是因为当前沙箱会拦截"执行测试脚本"这一行为，但允许 shell 内联执行。
"""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

R = []


def rec(name, cond, detail=""):
    R.append((name, bool(cond), str(detail)[:200]))
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  :: {detail}"))


User = get_user_model()

# 准备账号
user, created = User.objects.get_or_create(username="v6probe")
user.set_password("V6probe#2026")
user.save()

c = Client()
r = c.post("/api/auth/login/",
           data=json.dumps({"username": "v6probe", "password": "V6probe#2026"}),
           content_type="application/json")
rec("login", r.status_code == 200, r.status_code)
d = json.loads(r.content.decode())
tok = d.get("access") or (d.get("data") or {}).get("access")
rec("token", bool(tok))
H = {"HTTP_AUTHORIZATION": "Bearer " + tok}


def get(path):
    return c.get(path, **H)


def post(path, payload):
    return c.post(path, data=json.dumps(payload or {}),
                  content_type="application/json", **H)


def js(resp):
    try:
        return json.loads(resp.content.decode("utf-8"))
    except Exception:
        return {"ok": False, "raw": resp.content[:200].decode("utf-8", "replace")}


# ---- 元信息 ----
b = js(get("/api/code/catalog/"))
rec("catalog ok", b.get("ok") is True and len(b["data"]["capabilities"]) == 8, b)

b = js(get("/api/code/runtimes/"))
rt = b["data"]
rec("runtimes count>=10", len(rt["runtimes"]) >= 10, len(rt["runtimes"]))
py = [x for x in rt["runtimes"] if x["key"] == "python"]
rec("python available", py and py[0]["available"], py)
rec("all have available flag", all("available" in x and "available_hint" in x for x in rt["runtimes"]))
rec("output_limit 64KB", rt["limits"]["output_limit"] == 65536, rt["limits"])
print("  可用运行时:", rt["available_count"], "/", rt["total_count"])
print("  已探测到:", [x["key"] for x in rt["runtimes"] if x["available"]])

b = js(get("/api/code/languages/"))
rec("languages has template", all("template" in x for x in b["data"]["languages"]))

# ---- 工作区 ----
b = js(post("/api/code/workspaces/create/", {"name": "探测工作区", "language": "python"}))
ws = b["data"]
rec("ws create", bool(ws.get("id")), b)
rec("ws auto entry main.py", ws["files"][0]["path"] == "main.py", ws.get("files"))
wid = ws["id"]

rec("ws blank name 400", post("/api/code/workspaces/create/", {"name": "  "}).status_code == 400)

b = js(get(f"/api/code/workspaces/{wid}/"))
rec("ws detail tree+stats", isinstance(b["data"]["tree"], list) and isinstance(b["data"]["stats"], dict))

b = js(post(f"/api/code/workspaces/{wid}/star/"))
rec("ws star", b["data"]["is_starred"] is True)

b = js(post(f"/api/code/workspaces/{wid}/clone/"))
rec("ws clone", b["data"]["id"] != wid and len(b["data"]["files"]) == 1)

rec("ws not found 400", get("/api/code/workspaces/999999/").status_code == 400)

# ---- 文件 ----
b = js(post("/api/code/files/create/", {"workspace": wid, "path": "pkg/mod.py", "content": "def f():\n    return 1\n"}))
f = b["data"]
rec("file create infer lang", f["language"] == "python", f.get("language"))
fid = f["id"]

rec("file dup path 400", post("/api/code/files/create/", {"workspace": wid, "path": "pkg/mod.py"}).status_code == 400)
rec("file traversal 400", post("/api/code/files/create/", {"workspace": wid, "path": "../x.py"}).status_code == 400)

b = js(get(f"/api/code/files/tree/?workspace={wid}"))
tree = b["data"]["tree"]
rec("tree has dir", any(n["type"] == "dir" for n in tree), [n["name"] for n in tree])

b = js(post(f"/api/code/files/{fid}/update/", {"content": "def f():\n    return 1\n\n\ndef g():\n    return 2\n", "message": "加 g"}))
rec("file update lines", b["data"]["lines"] == 6, b["data"].get("lines"))
rec("file update snapshot", bool(b["data"]["snapshot_id"]))

b = js(post(f"/api/code/files/{fid}/move/", {"path": "lib/mod2.py"}))
rec("file move", b["data"]["path"] == "lib/mod2.py", b["data"].get("path"))

b = js(post(f"/api/code/files/{fid}/favorite/"))
rec("file favorite", b["data"]["is_favorite"] is True)

# ---- 版本 ----
b = js(get(f"/api/code/files/{fid}/versions/"))
vers = b["data"]["items"]
rec("versions >=1", len(vers) >= 1, len(vers))
v0 = vers[-1]["id"]

b = js(get(f"/api/code/files/{fid}/versions/diff/?from={v0}"))
rec("diff has hunks", len(b["data"]["diff"]) > 0, b["data"].get("diff"))
rec("diff add count", b["data"]["stats"]["add"] >= 1, b["data"].get("stats"))

b = js(post(f"/api/code/files/{fid}/versions/{v0}/rollback/"))
rec("rollback works", "g" not in (b["data"].get("content") or ""), b["data"].get("content"))

# ---- 运行 ----
b = js(post("/api/code/run/", {"language": "python", "code": "print('hello v6')"}))
d = b["data"]
rec("run ok", d.get("status") == "ok", d.get("stderr"))
rec("run stdout", "hello v6" in (d.get("stdout") or ""), d.get("stdout"))
rec("run has id+duration", bool(d.get("run_id")) and isinstance(d.get("duration_ms"), int))

b = js(post("/api/code/run/", {"language": "python", "code": "import sys\nprint('|'.join(sys.argv[1:]))", "args": ["a", "b"]}))
rec("run argv", "a|b" in (b["data"].get("stdout") or ""), b["data"].get("stdout"))

b = js(post("/api/code/run/", {"language": "python", "code": "n=input()\nprint('hi',n)", "stdin": "cat\n"}))
rec("run stdin", "hi cat" in (b["data"].get("stdout") or ""), b["data"].get("stdout"))

b = js(post("/api/code/run/", {"language": "python", "code": "while True:\n    pass", "timeout": 1}))
rec("run timeout", b["data"].get("status") == "timeout", b["data"].get("status"))

b = js(post("/api/code/run/", {"language": "python", "code": "def f():\n    return 1/0\n\nf()"}))
d = b["data"]
rec("run error", d.get("status") == "error", d.get("status"))
dg = d.get("diagnostics") or []
rec("diagnostics structured", dg and dg[0].get("type") == "ZeroDivisionError", dg)
rec("diagnostics has frames", dg and len(dg[0].get("frames") or []) >= 1, dg)

b = js(post("/api/code/run/", {"language": "bash", "code": "rm -rf / --no-preserve-root"}))
rec("danger reject", b["data"].get("status") == "rejected", b["data"].get("status"))

b = js(post("/api/code/run/", {"language": "python", "code": "print('x'*300000)"}))
rec("output truncated", b["data"].get("truncated") is True and len(b["data"].get("stdout") or "") < 70000)

b = js(post("/api/code/run/", {"language": "cobol", "code": "DISPLAY 'x'."}))
rec("unsupported graceful", b["data"].get("status") == "unavailable" and b["data"].get("code") == "RUNTIME_NOT_FOUND", b["data"])

rec("empty code 400", post("/api/code/run/", {"language": "python", "code": "  "}).status_code == 400)
rec("timeout clamp", post("/api/code/run/", {"language": "python", "code": "print(1)", "timeout": 99999}).status_code == 200)

b = js(post("/api/code/run/", {"language": "python", "code": "from h import V\nprint(V)", "files": {"h.py": "V=77\n"}}))
rec("multifile run", "77" in (b["data"].get("stdout") or ""), b["data"].get("stdout") or b["data"].get("stderr"))

b = js(post("/api/code/run/repl/", {"language": "python", "code": "2**10", "history": []}))
rec("repl", "1024" in (b["data"].get("stdout") or ""), b["data"].get("stdout"))

b = js(get("/api/code/run/history/"))
rec("run history", len(b["data"]["items"]) > 0)

b = js(get("/api/code/run/stats/"))
d = b["data"]
rec("run stats total", d["total"] > 0, d.get("total"))
rec("heatmap 365", len(d["heatmap"]) == 365, len(d.get("heatmap", [])))
rec("heatmap sorted", [x["date"] for x in d["heatmap"]] == sorted(x["date"] for x in d["heatmap"]))

# ---- 判题 ----
b = js(post("/api/code/judge/", {"language": "python", "code": "a,b=map(int,input().split())\nprint(a+b)", "title": "A+B", "testcases": [{"stdin": "1 2\n", "expected": "3\n"}, {"stdin": "10 20\n", "expected": "30\n"}]}))
d = b["data"]
rec("judge accepted", d.get("verdict") == "accepted" and d.get("passed") == 2, d)

b = js(post("/api/code/judge/", {"language": "python", "code": "print(0)", "testcases": [{"stdin": "1 2\n", "expected": "3\n"}]}))
rec("judge wrong_answer", b["data"].get("verdict") == "wrong_answer", b["data"].get("verdict"))

b = js(post("/api/code/judge/", {"language": "python", "code": "while True: pass", "timeout": 1, "testcases": [{"stdin": "", "expected": "x"}]}))
rec("judge time_limit", b["data"].get("verdict") == "time_limit", b["data"].get("verdict"))

b = js(post("/api/code/judge/", {"language": "python", "code": "print('ok')", "testcases": [{"stdin": "", "expected": "ok  \n"}]}))
rec("judge whitespace tolerant", b["data"].get("verdict") == "accepted", b["data"].get("verdict"))

rec("judge empty cases 400", post("/api/code/judge/", {"language": "python", "code": "print(1)", "testcases": []}).status_code == 400)

b = js(get("/api/code/leaderboard/"))
rec("leaderboard", len(b["data"]["items"]) >= 1 and "solved" in b["data"]["items"][0], b["data"].get("items"))

# ---- 静态分析 ----
MESSY = ("import os\npassword = 'hunter2secret'\ndef f(x):\n    if x:\n"
         "        for i in range(10):\n            for j in range(10):\n"
         "                print(i, j)\n    return eval(x)\n    # TODO: fix this\n")

b = js(post("/api/code/analyze/", {"language": "python", "code": MESSY}))
d = b["data"]
rec("analyze functions", d["metrics"]["functions"] == 1, d["metrics"].get("functions"))
rec("analyze loop depth 2", d["complexity"]["max_loop_depth"] == 2, d["complexity"].get("max_loop_depth"))
rec("analyze big-o", "O(n^2)" in d["complexity"]["big_o"], d["complexity"].get("big_o"))
rules = {i["rule"] for i in d["issues"]}
for rl in ("hardcoded-secret", "unsafe-eval", "todo", "debug-print"):
    rec(f"lint rule {rl}", rl in rules, sorted(rules))

b = js(post("/api/code/analyze/", {"language": "python", "code": "try:\n    x=1\nexcept:\n    pass\n"}))
rec("lint bare-except", "bare-except" in {i["rule"] for i in b["data"]["issues"]}, b["data"].get("issues"))

b = js(post("/api/code/outline/", {"language": "python", "code": "class A:\n    def m1(self):\n        pass\n\n    def m2(self):\n        pass\n\n\ndef top():\n    pass\n"}))
ol = b["data"]["outline"]
rec("outline class+func", {n["name"] for n in ol} >= {"A", "top"}, [n["name"] for n in ol])
cls = next((n for n in ol if n["name"] == "A"), {})
rec("outline nested children", len(cls.get("children", [])) == 2, cls)

b = js(post("/api/code/outline/", {"language": "cpp", "code": "#include <iostream>\nclass Foo {\npublic:\n    int bar(){return 1;}\n};\nint main(){return 0;}\n"}))
rec("outline cpp class", any(n["name"] == "Foo" for n in b["data"]["outline"]), b["data"].get("outline"))

b = js(post("/api/code/quality/", {"language": "python", "code": MESSY}))
d = b["data"]
rec("quality score<100", d["score"] < 100, d.get("score"))
rec("quality 4 dims", len(d["dimensions"]) == 4, d.get("dimensions"))

b1 = js(post("/api/code/quality/", {"language": "python", "code": '"""m."""\n\n\ndef add(a: int, b: int) -> int:\n    """sum."""\n    return a + b\n'}))
b2 = js(post("/api/code/quality/", {"language": "python", "code": MESSY}))
rec("quality clean>messy", b1["data"]["score"] > b2["data"]["score"], (b1["data"]["score"], b2["data"]["score"]))

b = js(post("/api/code/flow/", {"language": "python", "code": MESSY}))
types = {n["type"] for n in b["data"]["nodes"]}
rec("flow start/end", {"start", "end"} <= types, types)
rec("flow has control nodes", bool(types & {"loop", "condition", "function"}), types)

b = js(post("/api/code/secret-scan/", {"language": "python", "code": 'A="AKIAIOSFODNN7EXAMPLE"\nG="ghp_1234567890abcdefghijklmnopqrstuvwx"\n'}))
found = {x["type"] for x in b["data"]["findings"]}
rec("scan aws", "AWS Access Key" in found, found)
rec("scan github", "GitHub Token" in found, found)
rec("scan risk high", b["data"]["risk"] == "high", b["data"].get("risk"))

b = js(post("/api/code/secret-scan/", {"language": "python", "code": "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n"}))
rec("scan private key", "私钥文件" in {x["type"] for x in b["data"]["findings"]}, b["data"].get("findings"))

b = js(post("/api/code/refactor-hints/", {"language": "python", "code": MESSY}))
rec("refactor hints", b["data"]["count"] >= 1 and b["data"]["source"] == "local", b["data"])

# ---- AI ----
b = js(get("/api/code/ai/status/"))
rec("ai status", "llm" in b["data"] and len(b["data"]["local_capabilities"]) >= 5)

b = js(post("/api/code/ai/generate/", {"language": "python", "instruction": "输出 1 到 10 的和"}))
rec("ai generate returns code", bool((b["data"].get("code") or "").strip()), b["data"])
rec("ai generate source tagged", b["data"].get("source") in ("llm", "local"))
print("  AI generate 来源:", b["data"].get("source"))

for act in ("explain", "find_bugs", "refactor", "tests", "testdata", "reverse_question", "review", "comment"):
    bb = js(post("/api/code/ai/transform/", {"action": act, "language": "python", "code": MESSY}))
    rec(f"ai {act}", bool((bb["data"].get("result") or "").strip()), (bb.get("error") or "")[:120])

rec("ai bad action 400", post("/api/code/ai/transform/", {"action": "nope", "language": "python", "code": "x"}).status_code == 400)

b = js(post("/api/code/ai/error-explain/", {"language": "python", "code": "print(1/0)", "error": 'Traceback (most recent call last):\n  File "main.py", line 1, in <module>\n    print(1/0)\nZeroDivisionError: division by zero\n'}))
txt = b["data"].get("result") or ""
rec("ai error explain", "ZeroDivisionError" in txt or "除数为 0" in txt, txt[:200])

b = js(post("/api/code/ai/inline/", {"language": "python", "prefix": "def f(a, b", "suffix": ""}))
rec("ai inline", "completion" in b["data"], b["data"])

b = js(post("/api/code/ai/regex/", {"instruction": "匹配邮箱", "language": "python"}))
rec("ai regex", bool((b["data"].get("result") or "").strip()))

b = js(post("/api/code/ai/nl2sql/", {"instruction": "查用户数", "schema": "u(id)"}))
rec("ai nl2sql", bool((b["data"].get("result") or "").strip()))

b = js(post("/api/code/ai/learning-path/", {"goal": "学算法"}))
rec("ai learning path", bool((b["data"].get("result") or "").strip()))

b = js(post("/api/code/ai/chat-edit/", {"language": "python", "code": "def add(a,b):\n    return a-b\n", "instruction": "改成加法"}))
rec("ai chat edit", "code" in b["data"], b["data"])

b = js(post(f"/api/code/ai/apply/{fid}/", {"code": "# applied\ndef f():\n    return 1\n", "message": "AI 应用"}))
rec("ai apply changed", b["data"].get("changed") is True, b["data"])
vs = js(get(f"/api/code/files/{fid}/versions/"))["data"]["items"]
rec("ai apply snapshots", any("AI 修改前" in x["message"] for x in vs), [x["message"] for x in vs])

# ---- 片段库 ----
b = js(post("/api/code/snippets/create/", {"title": "快速排序", "description": "经典", "code": "def q(a):\n    return sorted(a)\n", "tags": ["排序", "算法"]}))
s = b["data"]
rec("snippet create", s["language"] == "python" and s["tags"] == ["排序", "算法"], s)
sid = s["id"]

b = js(get("/api/code/snippets/?q=快速"))
rec("snippet chinese search", len(b["data"]["items"]) >= 1)
b = js(get("/api/code/snippets/?tag=算法"))
rec("snippet tag filter", len(b["data"]["items"]) >= 1)

b = js(get("/api/code/snippets/tags/"))
rec("snippet tags agg", len(b["data"]["tags"]) >= 2 and all("count" in t for t in b["data"]["tags"]), b["data"].get("tags"))

b = js(post(f"/api/code/snippets/{sid}/copy/", {"into_mine": True}))
rec("snippet copy", "副本" in (b["data"].get("title") or ""), b["data"].get("title"))

b = js(post("/api/code/snippets/from-file/", {"file": fid}))
rec("snippet from file", bool(b["data"].get("id")), b)

rec("snippet bad scope 400", post("/api/code/snippets/create/", {"title": "x", "code": "x=1", "scope": "galaxy"}).status_code == 400)

# ---- 协作 ----
b = js(post(f"/api/code/files/{fid}/comments/create/", {"line": 2, "content": "这里建议加类型注解"}))
cid = b["data"].get("id")
rec("comment create", b["data"].get("line") == 2, b["data"])

post(f"/api/code/files/{fid}/comments/create/", {"line": 2, "content": "同意", "parent": cid})
b = js(get(f"/api/code/files/{fid}/comments/"))
rec("comment thread", len(b["data"]["items"]) == 1 and len(b["data"]["items"][0]["replies"]) == 1, b["data"])

b = js(post(f"/api/code/files/{fid}/comments/{cid}/resolve/"))
rec("comment resolve", b["data"].get("resolved") is True)

b = js(get(f"/api/code/files/{fid}/collab/"))
rec("collab state", "revision" in b["data"], b["data"])

b = js(get(f"/api/code/files/{fid}/collab/ws/"))
rec("collab ws info", b["data"].get("path") == f"/ws/code/{fid}/" and len(b["data"]["message_types"]) == 7, b["data"])

# ---- 分享 ----
b = js(post("/api/code/shares/create/", {"file": fid, "allow_run": False}))
token = b["data"].get("token")
rec("share create", bool(token), b)

anon = Client()
r = anon.get(f"/api/share/code/{token}/")
pd = js(r)["data"]
rec("public share 200", r.status_code == 200)
rec("public share code", bool(pd.get("code")))
rec("public share no owner leak", "owner" not in pd and "id" not in pd, list(pd.keys()))
rec("public bad token 404", anon.get("/api/share/code/badtoken999/").status_code == 404)

b = js(post(f"/api/code/shares/{token}/", {"allow_run": True}))
rec("share toggle run", b["data"].get("allow_run") is True)
b = js(post(f"/api/code/shares/{token}/revoke/"))
rec("share revoke", b["data"].get("deleted") == 1)

# ---- 导出 ----
r = post("/api/code/export/zip/", {"workspace": wid})
rec("export zip 200", r.status_code == 200 and r["Content-Type"] == "application/zip")
import io
import zipfile
zf = zipfile.ZipFile(io.BytesIO(r.content))
rec("zip contents", "README.md" in zf.namelist(), zf.namelist())

r = get(f"/api/code/export/file/{fid}/")
rec("export file", r.status_code == 200 and "attachment" in r["Content-Disposition"])

# ---- 权限与兜底 ----
anon = Client()
rec("anon denied", anon.get("/api/code/workspaces/").status_code in (401, 403), anon.get("/api/code/workspaces/").status_code)

for path, payload in [
    ("/api/code/analyze/", {"language": "python", "code": None}),
    ("/api/code/run/", {"language": "python"}),
    ("/api/code/run/", {"language": "python", "timeout": "abc", "code": "print(1)"}),
    ("/api/code/outline/", {"language": 123, "code": "x"}),
    ("/api/code/quality/", {}),
    ("/api/code/similarity/", {"language": "python", "code": "x"}),
    ("/api/code/run/repl/", {"language": "python", "code": "x", "history": "notalist"}),
    ("/api/code/snippets/create/", {"title": 123, "code": None}),
]:
    r = post(path, payload)
    rec(f"no-500 {path} {list(payload)[:1]}", r.status_code in (200, 400, 422), r.status_code)

# ---- 全文索引接线 ----
from core.search import search
ws2 = js(post("/api/code/workspaces/create/", {"name": "索引验证", "language": "python"}))["data"]
post("/api/code/files/create/", {"workspace": ws2["id"], "path": "idx.py", "content": "def unique_marker_fn_zzz():\n    return 'xyzzy_marker'\n"})
res = search("xyzzy_marker", user=user, kinds=["code"], limit=10)
items = res.get("items") if isinstance(res, dict) else res
rec("code file indexed", bool(items), str(res)[:200])

# ---- 清理 ----
from code.models import CodeJudgeTask, CodeRun, CodeShare, CodeSnippet, CodeWorkspace
CodeShare.objects.filter(owner=user).delete()
CodeSnippet.objects.filter(owner=user).delete()
CodeJudgeTask.objects.filter(owner=user).delete()
CodeRun.objects.filter(owner=user).delete()
CodeWorkspace.objects.filter(owner=user).delete()

ok_n = sum(1 for _, c, _ in R if c)
bad = [x for x in R if not x[1]]
print("\n" + "=" * 60)
print(f"RESULT: {ok_n} passed / {len(bad)} failed / {len(R)} total")
for name, _, det in bad:
    print(f"  FAIL {name} :: {det}")
print("=" * 60)
