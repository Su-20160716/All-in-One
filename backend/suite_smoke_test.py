# -*- coding: utf-8 -*-
"""v5 套件冒烟测试：devtools + dataintel + officesuite 三 catalog 全链路。

接口总数由各源 SUBSYSTEMS 动态计算（见下方 *_EXPECTED），不写死。
运行：venv/Scripts/python suite_smoke_test.py
注意：必须与其它测试**串行**执行（SQLite database is locked），勿并行。
"""
import os
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from rest_framework.test import APIClient  # noqa: E402

# S3-B2/B17：三个 catalog 的期望数统一从源动态计算（SUBSYSTEMS 是唯一事实源），
# 以后加接口冒烟自动跟上，不再出现"脚本过期假装接口丢了"的假阳性。
from devtools.urls import SUBSYSTEMS as _DEV_SUBS  # noqa: E402
from dataintel.urls import SUBSYSTEMS as _DI_SUBS  # noqa: E402
from officesuite.views_cal import OFFICE_SUBSYSTEMS as _OS_SUBS  # noqa: E402

# endpoint_count 均含 catalog 自身接口（各 urls.py / views 里都是 sum(...)+1）
DEVT_EXPECTED = sum(len(eps) for _, _, eps in _DEV_SUBS) + 1
DI_EXPECTED = sum(c for _, _, c in _DI_SUBS) + 1
OS_EXPECTED = sum(c for _, _, c in _OS_SUBS) + 1

passed, failed = [], []


def check(name, cond, extra=""):
    if cond:
        passed.append(name)
        print(f"  ✓ {name}")
    else:
        failed.append(name)
        print(f"  ✗ {name} {extra}")


def call(c, method, path, payload=None):
    fn = getattr(c, method.lower())
    return fn(path, payload or {}, format="json")


def ok200(r):
    return r.status_code == 200 and r.data.get("ok") is True


# =====================================================================
# 第一部分：devtools（153 工具 + catalog GET = 154）
# =====================================================================

DEVT = [
    ("text/case/", {"text": "hello_world", "mode": "camel"}),
    ("text/wrap/", {"text": "hello world " * 10, "width": 20}),
    ("text/pad/", {"text": "x", "width": 10}),
    ("text/replace/", {"text": "a-b-c", "find": "-", "replace": "+"}),
    ("text/extract/", {"text": "mail a@b.com call 13800138000", "kind": "mobile"}),
    ("text/normalize/", {"text": "ｈｅｌｌｏ　world"}),
    ("str/dedent/", {"text": "  a\n  b"}),
    ("str/truncate/", {"text": "abcdef", "limit": 4}),
    ("str/char-stats/", {"text": "你好 world 123"}),
    ("str/initials/", {"text": "hello world foo"}),
    ("str/abbr/", {"text": "Hyper Text Markup Language"}),
    ("str/reverse-words/", {"text": "the quick brown fox"}),
    ("md/to-html/", {"text": "# 标题\n\n- a\n- b\n\n**粗体**"}),
    ("md/headings/", {"text": "# a\n## b\n### c"}),
    ("md/toc/", {"text": "# a\n## b\n# c"}),
    ("md/strip/", {"text": "# a\n**b**"}),
    ("md/table/", {"text": "| a | b |\n|---|---|\n| 1 | 2 |"}),
    ("md/frontmatter/", {"text": "---\ntitle: t\n---\n正文"}),
    ("json/flatten/", {"data": {"a": {"b": 1}, "c": [1, 2]}}),
    ("json/unflatten/", {"flat": {"a.b": 1, "a.c": 2}}),
    ("json/merge/", {"objects": [{"a": 1}, {"b": 2}, {"a": 3}]}),
    ("json/ndjson/", {"data": [{"a": 1}, {"a": 2}]}),
    ("json/stats/", {"data": {"a": 1, "b": [1, 2, 3], "c": None}}),
    ("json/pick/", {"data": {"a": 1, "b": 2}, "keys": ["a"]}),
    ("log/parse/", {"text": "2026-09-14 10:00:00 ERROR db timeout\n2026-09-14 10:01:00 INFO ok"}),
    ("log/level-stat/", {"text": "ERROR x\nINFO y\nINFO z\nWARN w"}),
    ("log/timeframe/", {"text": "2026-09-14 10:00:00 INFO a\n2026-09-14 12:30:00 INFO b"}),
    ("log/topn/", {"text": "GET /a\nGET /b\nGET /a\nPOST /c", "top": 2}),
    ("log/filter/", {"text": "ERROR a\nINFO b\nERROR c", "level": "ERROR"}),
    ("encode/base32/", {"text": "hello"}),
    ("encode/base85/", {"text": "hello"}),
    ("encode/qp/", {"text": "中文=quoted"}),
    ("encode/unicode-escape/", {"text": "中文"}),
    ("encode/punycode/", {"text": "中文.com"}),
    ("regex/replace/", {"text": "a1b2c3", "pattern": "\\d", "replace": "#"}),
    ("regex/extract/", {"text": "a1b22c333", "pattern": "\\d+"}),
    ("regex/split/", {"text": "a,b;;c", "pattern": "[,;]+"}),
    ("regex/explain/", {"pattern": "\\d+(?:\\.\\d+)?"}),
    ("regex/grep/", {"pattern": "error", "text": "ERROR 1\ninfo 2\nerror 3"}),
    ("regex/template/", {"text": "订单号 {{order.id}} 共 {{n}} 件", "context": {"order": {"id": "A001"}, "n": 3}}),
    ("hash/crc32/", {"text": "hello"}),
    ("hash/adler32/", {"text": "hello"}),
    ("hash/sha3/", {"text": "hello"}),
    ("hash/hmac/", {"text": "hello", "key": "s3cr3t"}),
    ("hash/blake2/", {"text": "hello"}),
    ("token/jwt-sign/", {"payload": {"sub": "u1", "role": "dev"}, "secret": "k1", "ttl_seconds": 3600}),
    ("token/jwt-verify/", {"text": "", "secret": "k1"}),  # text 在运行时填充
    ("token/apikey/", {"prefix": "sk"}),
    ("token/otp/", {"seed": "JBSWY3DPEHPK3PXP"}),
    ("token/nanoid/", {"size": 12, "count": 3}),
    ("token/password-audit/", {"password": "Tr0ub4dor&3"}),
    ("code/minify-css/", {"css": "body { color: red; }"}),
    ("code/beautify/", {"text": "function f(){return 1}", "indent": 2}),
    ("code/lang-detect/", {"text": "def f(x):\n    return x"}),
    ("code/loc/", {"text": "line1\n\n# comment\nline4"}),
    ("code/todo-scan/", {"text": "# TODO fix\nx = 1\n# FIXME later"}),
    ("code/gitmoji/", {"keyword": "bug"}),
    ("diff/text/", {"a": "hello\nworld", "b": "hello\nworld!"}),
    ("diff/word/", {"a": "the quick fox", "b": "the slow fox"}),
    ("diff/json/", {"a": {"x": 1, "y": 2}, "b": {"x": 1, "z": 3}}),
    ("diff/similarity/", {"a": "hello world", "b": "hello word"}),
    ("diff/patch/", {"patch": "", "a": "x\ny"}),  # patch 在运行时填充
    ("id/uuid-multi/", {"count": 3, "version": 4}),
    ("id/shortid/", {"count": 2}),
    ("id/checksum/", {"code": "1234567890128"}),  # 合法 EAN-13
    ("id/luhn-gen/", {"brand": "unionpay"}),
    ("file/data-url/", {"mode": "build", "content": "hello", "mime": "text/plain"}),
    ("file/csv-clean/", {"csv": "a,b\n1, 2\n 3,4\n,,\n5,6"}),
    ("file/magic/", {"data": "89504e470d0a1a0a"}),
    ("file/zip-list/", {"zip_b64": "UEsDBBQAAAAAAIcEL12FEUoNCwAAAAsAAAAJAAAAaGVsbG8udHh0aGVsbG8gd29ybGRQSwMEFAAAAAAAhwQvXYP5PQYGAAAABgAAAA4AAABkb2NzL3JlYWRtZS5tZCMgZGVtb1BLAQIUABQAAAAAAIcEL12FEUoNCwAAAAsAAAAJAAAAAAAAAAAAAACAAQAAAABoZWxsby50eHRQSwECFAAUAAAAAACHBC9dg/k9BgYAAAAGAAAADgAAAAAAAAAAAAAAgAEyAAAAZG9jcy9yZWFkbWUubWRQSwUGAAAAAAIAAgBzAAAAZAAAAAAA"}),
    ("file/encoding-detect/", {"data_b64": "5L2g5aW9"}),
    ("file/line-endings/", {"text": "a\r\nb\nc\r\n"}),
    ("qr/generate/", {"text": "https://example.com", "size": 15}),
    ("qr/info/", {"text": "hello"}),
    ("qr/barcode39/", {"content": "ABC123"}),
    ("web/curl-parse/", {"curl": "curl -X POST https://api.example.com/v1 -H 'Content-Type: application/json' -d '{\"a\":1}'"}),
    ("web/jsonpath/", {"data": {"a": {"b": [1, 2, 3]}}, "path": "a.b"}),
    ("web/dotpath/", {"data": {"a": {"b": 1}}, "path": "a.b"}),
    ("web/http-status/", {"code": 404}),
    ("web/headers/", {"name": "content-type"}),
    ("web/querystring/", {"query": "?a=1&b=%E4%B8%AD&c=x&c=y"}),
    ("db/sql-format/", {"sql": "select a,b from t where a=1 and b>2 order by a desc"}),
    ("db/sql-minify/", {"sql": "SELECT a, b\nFROM t -- comment\nWHERE a = 1"}),
    ("db/where-builder/", {"rules": [{"field": "age", "op": ">", "value": 18}, {"field": "name", "op": "=", "value": "bob"}], "glue": "AND"}),
    ("db/join-explain/", {"kind": "left"}),
    ("db/epoch/", {"value": 1789200000, "mode": "from"}),
    ("num/base/", {"value": "255", "from_base": 10, "to_base": 16}),
    ("num/ieee754/", {"value": 3.14}),
    ("num/bitwise/", {"a": 12, "b": 10, "op": "and"}),
    ("num/combinatorics/", {"items": ["a", "b", "c", "d"], "k": 2, "sample": 3}),
    ("num/format/", {"value": 1234567.891}),
    ("num/rounding/", {"value": 2.675, "places": 2}),
    ("color/contrast/", {"color1": "#1a73e8", "color2": "#ffffff"}),
    ("color/mix/", {"color1": "#ff0000", "color2": "#0000ff"}),
    ("color/scale/", {"color1": "#3498db", "color2": "#ffffff", "steps": 5}),
    ("color/nearest/", {"color": "#f0f0f0"}),
    ("color/shade/", {"color": "#ff6600", "percent": -20}),
    ("color/filter/", {"color": "#ff6600", "kind": "grayscale"}),
    ("date/add/", {"date": "2026-09-14", "amount": 7}),
    ("date/workdays/", {"start": "2026-09-14", "end": "2026-09-30"}),
    ("date/week-info/", {"date": "2026-09-14"}),
    ("date/quarter-info/", {"date": "2026-09-14"}),
    ("date/seq/", {"start": "2026-09-01", "count": 7}),
    ("date/countdown/", {"target": "2027-01-01"}),
    ("cron/parse/", {"cron": "0 9 * * 1-5"}),
    ("cron/validate/", {"cron": "*/5 * * * *"}),
    ("cron/from-interval/", {"every": 30}),
    ("cron/shift/", {"cron": "0 9 * * 1-5", "minutes": -30}),
    ("math/matrix/", {"a": [[1, 2], [3, 4]], "b": [[5, 6], [7, 8]], "op": "mul"}),
    ("math/linear-solve/", {"a": [[2, 1], [1, 3]], "b": [5, 10]}),
    ("math/primes/", {"n": 100}),
    ("math/expr/", {"expr": "1 + 2 * 3"}),
    ("math/dist/", {"kind": "normal", "x": 1.96}),
    ("math/dijkstra/", {"edges": [{"from": "A", "to": "B", "weight": 1}, {"from": "B", "to": "C", "weight": 2}, {"from": "A", "to": "C", "weight": 5}], "start": "A", "end": "C"}),
    ("unit/data-size/", {"value": 1024, "from": "KB", "to": "MB"}),
    ("unit/angle/", {"value": 180, "from": "deg"}),
    ("unit/speed/", {"value": 72, "from": "km/h"}),
    ("unit/apparel/", {"size": "M", "kind": "top", "gender": "men"}),
    ("net/ip-calc/", {"cidr": "192.168.1.0/24"}),
    ("net/ip-classify/", {"ip": "10.0.0.1"}),
    ("net/url-parse/", {"url": "https://user:pw@api.example.com:8443/v1/x?page=2#top"}),
    ("net/url-build/", {"host": "api.example.com", "path": "/v1/x", "params": {"page": 2}, "scheme": "https"}),
    ("net/ua-parse/", {"user_agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36"}),
    ("net/mime-lookup/", {"ext": "pdf"}),
    ("fake/person/", {"gender": "female"}),
    ("fake/company/", {}),
    ("fake/address/", {"region": "广东"}),
    ("fake/lorem/", {"count": 3}),
    ("fake/batch/", {"fields": [{"name": "name", "type": "name"}, {"name": "phone", "type": "phone"}, {"name": "mail", "type": "email"}], "count": 5}),
    ("fake/net/", {"kind": "ipv4"}),
    ("fake/bank-card/", {"scheme": "unionpay"}),
    ("fun/fortune/", {"name": "鸭鸭"}),
    ("fun/dice/", {"count": 2, "sides": 6}),
    ("fun/lottery/", {"pool": ["a", "b", "c", "d"], "count": 2}),
    ("fun/team-splitter/", {"names": ["甲", "乙", "丙", "丁", "戊", "己"], "teams": 2}),
    ("fun/coinflip/", {"count": 10}),
    ("fun/emoji/", {"keyword": "笑"}),
    ("fun/today/", {"date": "09-14"}),
    ("fun/zodiac/", {"birth": "2000-08-15"}),
    ("cheatsheet/md/", {}),
    ("cheatsheet/git/", {}),
    ("cheatsheet/vim/", {}),
    ("cheatsheet/shell/", {}),
    ("cheatsheet/regex/", {}),
    ("cheatsheet/http/", {}),
    ("cheatsheet/python/", {}),
    ("cheatsheet/sql/", {}),
    ("asciiart/banner/", {"text": "HI"}),
    ("asciiart/box/", {"text": "第一行\n第二行", "style": "round"}),
    ("asciiart/table/", {"rows": [["列1", "列2"], ["a", "b"], ["c", "d"]]}),
    ("asciiart/block/", {"matrix": [[1, 0], [0, 1]]}),
    ("asciiart/sparkline/", {"values": [3, 5, 4, 8, 9]}),
    ("asciiart/progress/", {"percent": 72, "width": 20, "style": "block"}),
]


def test_devtools(c):
    print("\n【devtools 开发者工具箱】%d 接口" % DEVT_EXPECTED)
    r = c.get("/api/devtools/catalog/")
    check("devtools/catalog 目录", ok200(r) and r.data["data"]["endpoint_count"] == DEVT_EXPECTED)

    jwt_token, luhn_code = "", ""
    # 先跑 jwt-sign / luhn-gen，拿值给 verify / checksum
    r = call(c, "POST", "/api/devtools/token/jwt-sign/", {"payload": {"sub": "u1"}, "secret": "k1", "ttl_seconds": 3600})
    check("token/jwt-sign", ok200(r))
    jwt_token = r.data["data"]["token"]
    r = call(c, "POST", "/api/devtools/id/luhn-gen/", {"brand": "unionpay"})
    check("id/luhn-gen", ok200(r))
    luhn_code = r.data["data"]["cards"][0]

    diff_patch_input = ""
    r = call(c, "POST", "/api/devtools/diff/text/", {"a": "x\ny", "b": "x\nz"})
    check("diff/text(取补丁源)", ok200(r))
    diff_patch_input = r.data["data"].get("patch") or r.data["data"].get("diff") or ""

    for path, payload in DEVT:
        name = path.rstrip("/").replace("/", "/")
        if path == "token/jwt-verify/":
            payload = {**payload, "text": jwt_token}
        elif path == "diff/patch/":
            payload = {**payload, "patch": diff_patch_input}
        r = call(c, "POST", f"/api/devtools/{path}", payload)
        check(f"devtools/{path}", ok200(r), f"status={r.status_code} body={str(r.data)[:120]}")

    # 深度断言
    r = call(c, "POST", "/api/devtools/text/case/", {"text": "hello_world", "mode": "camel"})
    check("devtools 深度：case camel", r.data["data"]["result"] == "helloWorld")
    r = call(c, "POST", "/api/devtools/num/base/", {"value": "255", "from_base": 10, "to_base": 16})
    check("devtools 深度：255→FF", str(r.data["data"]["value"]).upper().endswith("FF"))
    r = call(c, "POST", "/api/devtools/math/expr/", {"expr": "1 + 2 * 3"})
    check("devtools 深度：expr=7", r.data["data"]["value"] == 7)
    r = call(c, "POST", "/api/devtools/math/dijkstra/", {"edges": [{"from": "A", "to": "B", "weight": 1}, {"from": "B", "to": "C", "weight": 2}, {"from": "A", "to": "C", "weight": 5}], "start": "A", "end": "C"})
    check("devtools 深度：dijkstra 最短 3", r.data["data"]["distance"] == 3 and r.data["data"]["path"] == ["A", "B", "C"])
    r = call(c, "POST", "/api/devtools/net/ip-calc/", {"cidr": "192.168.1.0/24"})
    check("devtools 深度：/24 可用 254", r.data["data"]["usable_hosts"] == 254)
    r = call(c, "POST", "/api/devtools/date/add/", {"date": "2026-09-14", "amount": 7})
    check("devtools 深度：+7 天", "2026-09-21" in str(r.data["data"]))
    r = call(c, "POST", "/api/devtools/token/jwt-verify/", {"text": jwt_token, "secret": "k1"})
    check("devtools 深度：jwt 闭环验证", r.data["data"]["valid"] is True)
    r = call(c, "POST", "/api/devtools/token/jwt-verify/", {"text": jwt_token, "secret": "wrong"})
    check("devtools 深度：jwt 错钥拒绝", r.data["data"]["valid"] is False)
    r = call(c, "POST", "/api/devtools/fun/zodiac/", {"birth": "2000-08-15"})
    check("devtools 深度：生肖龙+狮子座", r.data["data"]["zodiac"] == "龙" and r.data["data"]["constellation"] == "狮子座")
    r = call(c, "POST", "/api/devtools/fake/bank-card/", {"scheme": "unionpay"})
    check("devtools 深度：卡号 luhn 合法", r.data["data"]["luhn_valid"] is True)
    r = call(c, "POST", "/api/devtools/asciiart/sparkline/", {"values": [3, 5, 9]})
    check("devtools 深度：sparkline 上行", r.data["data"]["trend"] == "up")
    r = call(c, "POST", "/api/devtools/cheatsheet/git/", {})
    check("devtools 深度：git 速查 ≥10 条", len(r.data["data"]["entries"]) >= 10)
    r = call(c, "POST", "/api/devtools/regex/extract/", {"text": "a1b22c333", "pattern": "\\d+"})
    check("devtools 深度：regex 3 组", len(r.data["data"]["matches"]) == 3)
    # 降级验证：非法参数必须 4xx + 结构化错误，绝不 500
    r = call(c, "POST", "/api/devtools/math/expr/", {"expr": "__import__('os')"})
    check("devtools 降级：表达式白名单拒绝", r.status_code in (400, 422) and r.data.get("ok") is False)
    r = call(c, "POST", "/api/devtools/net/ip-calc/", {"cidr": "not-an-ip"})
    check("devtools 降级：非法 CIDR", r.status_code in (400, 422))


# =====================================================================
# 第二部分：dataintel（113 + catalog = 114）
# =====================================================================

SAMPLE_ROWS = [
    {"city": "深圳", "month": "2026-01", "amount": 120, "qty": 10, "score": 4.2},
    {"city": "深圳", "month": "2026-02", "amount": 135, "qty": 12, "score": 4.5},
    {"city": "深圳", "month": "2026-03", "amount": 150, "qty": 15, "score": 4.8},
    {"city": "广州", "month": "2026-01", "amount": 90, "qty": 8, "score": 3.9},
    {"city": "广州", "month": "2026-02", "amount": 85, "qty": 7, "score": 3.6},
    {"city": "广州", "month": "2026-03", "amount": 95, "qty": 9, "score": 4.0},
    {"city": "上海", "month": "2026-01", "amount": 200, "qty": 20, "score": 4.9},
    {"city": "上海", "month": "2026-02", "amount": 210, "qty": 22, "score": 4.7},
    {"city": "上海", "month": "2026-03", "amount": 260, "qty": 28, "score": 5.0},
    {"city": "北京", "month": "2026-01", "amount": 170, "qty": 16, "score": 4.3},
    {"city": "北京", "month": "2026-02", "amount": None, "qty": 14, "score": 4.1},
    {"city": "北京", "month": "2026-03", "amount": 180, "qty": 17, "score": 4.4},
]

DATAI_ROWS = [
    ("dataset/list/", {}),
    ("profile/describe/", {"field": "amount"}),
    ("profile/freq/", {"field": "city"}),
    ("profile/corr/", {"x": "amount", "y": "qty"}),
    ("profile/missing/", {}),
    ("profile/dtype-infer/", {}),
    ("transform/pivot/", {"index": "city", "columns": "month", "value": "amount"}),
    ("transform/groupby/", {"by": "city", "field": "amount", "agg": "mean"}),
    ("transform/filter-expr/", {"expr": "amount > 100"}),
    ("transform/sort/", {"by": "amount", "order": "desc"}),
    ("transform/sample/", {"n": 5}),
    ("transform/normalize/", {"fields": ["amount"], "method": "minmax"}),
    ("calc/expr-row/", {"expr": "amount * 2"}),
    ("calc/pct-change/", {"values": [100, 110, 121]}),
    ("calc/weighted/", {"items": [{"value": 1, "weight": 1}, {"value": 2, "weight": 1}, {"value": 3, "weight": 2}]}),
    ("calc/running-total/", {"values": [10, 20, 30]}),
    ("calc/vlookup/", {"lookup_rows": [{"city": "深圳", "code": "0755"}, {"city": "广州", "code": "020"}], "key": "city", "fallback": "未知"}),
    ("stats/ttest-one/", {"values": [10, 12, 9, 11, 13, 12, 8], "mu": 10}),
    ("stats/ttest-two/", {"a": [10, 12, 9, 11], "b": [14, 15, 13, 16]}),
    ("stats/chi2/", {"observed": [[10, 20, 30], [6, 22, 32]]}),
    ("stats/zscore/", {"values": [10, 12, 9, 11, 13, 30]}),
    ("stats/ci-mean/", {"values": [10, 12, 9, 11, 13]}),
    ("stats/proportion-ci/", {"successes": 65, "trials": 100}),
    ("stats/binomial-test/", {"successes": 8, "trials": 10, "p": 0.5}),
    ("stats/corr-sig/", {"x": [1, 2, 3, 4, 5], "y": [2, 4, 5, 4, 5]}),
    ("forecast/moving-average/", {"values": [1, 2, 3, 4, 5, 6], "window": 3}),
    ("forecast/exp-smoothing/", {"values": [10, 12, 11, 13, 15], "alpha": 0.5}),
    ("forecast/linear-trend/", {"values": [10, 12, 14, 16], "steps": 3}),
    ("forecast/season-naive/", {"values": [1, 2, 3, 1, 2, 3, 1, 2, 3], "period": 3}),
    ("forecast/eval/", {"actual": [10, 12, 14], "predicted": [11, 11, 15]}),
    ("forecast/decompose/", {"values": [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4], "period": 4}),
    ("regress/linear/", {"x": [1, 2, 3, 4, 5], "y": [2.1, 3.9, 6.2, 8.1, 9.8]}),
    ("regress/poly/", {"x": [1, 2, 3, 4, 5], "y": [1, 4, 9, 16, 25], "degree": 2}),
    ("regress/logit/", {"x": [1, 2, 3, 4, 5, 6, 7, 8], "y": [0, 0, 0, 1, 0, 1, 1, 1]}),
    ("regress/eval/", {"actual": [1, 2, 3], "predicted": [1.1, 1.9, 3.2]}),
    ("regress/predict/", {"coefficients": [1, 2], "x": [3]}),
    ("cluster/kmeans/", {"points": [[1, 1], [1.2, 0.9], [5, 5], [5.2, 5.1]], "k": 2}),
    ("cluster/hierarchical/", {"points": [[1], [2], [9], [10]]}),
    ("cluster/dbscan/", {"points": [[1, 1], [1.1, 1], [5, 5]], "eps": 1.0}),
    ("cluster/elbow/", {"points": [[1], [2], [3], [8], [9], [10]]}),
    ("outlier/zscore/", {"values": [10, 11, 12, 100]}),
    ("outlier/iqr/", {"values": [1, 2, 3, 4, 100]}),
    ("outlier/mad/", {"values": [1, 2, 3, 4, 50]}),
    ("outlier/lof/", {"points": [[0, 0], [0.1, 0], [0, 0.1], [9, 9]]}),
    ("nlp/tokenize/", {"text": "这是一个中文分词测试"}),
    ("nlp/keywords/", {"text": "人工智能与机器学习改变世界，机器学习很重要", "top": 3}),
    ("nlp/sentiment/", {"text": "今天心情非常好，效率很高"}),
    ("nlp/summarize/", {"text": "第一句。第二句。第三句。", "ratio": 0.5}),
    ("nlp/entities/", {"text": "张三 2026-09-14 在深圳开会，电话 13800138000"}),
    ("nlp/similarity/", {"a": "机器学习很有趣", "b": "机器学习真好玩"}),
    ("nlp/readability/", {"text": "这是一段测试文本，用于计算可读性指标。"}),
    ("nlp/stopwords/", {"text": "这是一个 测试 文本 的 例子"}),
    ("textmine/wordfreq/", {"text": "苹果 香蕉 苹果 香蕉 橙子", "top": 3}),
    ("textmine/cooccurrence/", {"text": "a b c b c d", "window": 2}),
    ("textmine/bigram/", {"text": "今天 天气 不错 心情 好"}),
    ("textmine/classify/", {"text": "优惠 打折 促销", "categories": [{"name": "电商", "keywords": ["打折", "促销", "优惠"]}, {"name": "研发", "keywords": ["代码", "修复", "bug"]}]}),
    ("textmine/simhash/", {"docs": ["机器学习改变世界", "机器学习正在改变世界"]}),
    ("vector/cosine/", {"a": [1, 0, 1], "b": [1, 1, 0]}),
    ("vector/distance/", {"a": [0, 0], "b": [3, 4], "kind": "euclidean"}),
    ("vector/knn/", {"points": [[1, 1], [2, 2], [8, 8]], "query": [1, 2], "k": 2}),
    ("vector/centroid/", {"points": [[1, 1], [3, 3]]}),
    ("vector/normalize/", {"a": [3, 4]}),
    ("ai/status/", {}),
    ("ai/chat/", {"messages": [{"role": "user", "content": "用一句话介绍你自己"}]}),
    ("ai/translate/", {"text": "hello world", "to": "zh"}),
    ("ai/rewrite/", {"text": "这个功能很好用，真的非常好用", "style": "polish"}),
    ("ai/classify/", {"text": "服务器又挂了", "labels": ["技术故障", "售前咨询"]}),
    ("ai/extract/", {"text": "会议定在 2026-09-15 下午 3 点", "fields": ["日期", "时间"]}),
    ("ai/sentiment/", {"text": "非常满意这次服务"}),
    ("ai/summary/", {"text": "第一句话。第二句话。第三句话。"}),
    ("report/summary/", {"title": "销售月报", "sections": [{"name": "概况", "points": ["销售达标", "环比上升"]}]}),
    ("report/trend/", {"values": [10, 12, 9, 15, 18], "labels": ["一", "二", "三", "四", "五"]}),
    ("report/compare/", {"rows_b": [{"amount": 90, "qty": 8, "score": 3.9}, {"amount": 85, "qty": 7, "score": 3.6}, {"amount": 95, "qty": 9, "score": 4.0}]}),
    ("report/kpi/", {"kpis": [{"name": "GMV", "value": 120, "target": 100}, {"name": "新增用户", "value": 40, "target": 50}]}),
    ("report/export/", {"title": "导出测试", "rows": [["列1", "列2"], [1, 2]]}),
    ("chart/histogram/", {"values": [1, 2, 2, 3, 3, 3, 10], "bins": 4}),
    ("chart/boxplot/", {"values": [1, 2, 3, 4, 5, 100]}),
    ("chart/scatter/", {"points": [[1, 2], [2, 4], [3, 6]]}),
    ("chart/pie/", {"items": [{"name": "a", "value": 3}, {"name": "b", "value": 1}]}),
    ("chart/line/", {"series": [{"name": "s1", "values": [1, 2, 3]}, {"name": "s2", "values": [2, 2, 2]}]}),
    ("chart/heatmap/", {"matrix": [[1, 2], [3, 4]], "x_labels": ["a", "b"], "y_labels": ["1", "2"]}),
    ("chart/pareto/", {"items": [{"name": "a", "value": 50}, {"name": "b", "value": 30}, {"name": "c", "value": 20}]}),
    ("chart/funnel/", {"stages": [{"name": "访问", "value": 1000}, {"name": "下单", "value": 300}, {"name": "支付", "value": 100}]}),
    ("abtest/assign/", {"user_key": "u-42", "variants": ["A", "B"]}),
    ("abtest/hash-preview/", {"keys": ["u-1", "u-2", "u-3"], "variants": ["A", "B"]}),
    ("abtest/plan/", {"baseline_rate": 0.05, "mde": 0.02}),
    ("abtest/significance/", {"control": [20, 200], "variant": [30, 200]}),
    ("abtest/metrics/", {"groups": [{"name": "A", "successes": 20, "trials": 200}, {"name": "B", "successes": 30, "trials": 200}]}),
    ("cohort/build/", {"events": [{"user": "u1", "period": "2026-09"}, {"user": "u1", "period": "2026-10"}, {"user": "u2", "period": "2026-09"}]}),
    ("cohort/summary/", {"events": [{"user": "u1", "ts": "2026-09-01"}, {"user": "u1", "ts": "2026-09-08"}, {"user": "u2", "ts": "2026-09-01"}], "split_period": "week"}),
    ("cohort/retain/", {"events": [{"user": "u1", "ts": "2026-09-01"}, {"user": "u1", "ts": "2026-09-02"}], "periods": 3, "unit": "day"}),
    ("cohort/compare/", {"events": [{"user": "u1", "period": "2026-08"}, {"user": "u1", "period": "2026-09"}, {"user": "u2", "period": "2026-09"}], "split_period": "2026-09"}),
    ("sampling/random/", {"population": [1, 2, 3, 4, 5, 6, 7, 8], "n": 4}),
    ("sampling/systematic/", {"population": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "k": 3}),
    ("sampling/stratified/", {"population": [{"g": "a"}, {"g": "a"}, {"g": "b"}, {"g": "b"}], "stratum_key": "g", "n": 2}),
    ("sampling/bootstrap/", {"values": [1, 2, 3, 4, 5], "iterations": 200}),
    ("geo/distance/", {"from": "深圳", "to": "广州"}),
    ("geo/geohash/", {"lat": 22.54, "lng": 114.05, "precision": 6}),
    ("geo/polygon/", {"point": [22.54, 114.05], "polygon": [[22.0, 113.5], [23.0, 113.5], [23.0, 114.5], [22.0, 114.5]]}),
    ("geo/bbox/", {"points": [[22.5, 114.0], [22.6, 114.1]]}),
    ("geo/eta/", {"distance_km": 120, "mode": "car"}),
    ("geo/parse/", {"value": "22.54,114.05"}),
    ("insight/overview/", {}),
    ("insight/anomaly-brief/", {"column": "amount"}),
    ("insight/trend-brief/", {"column": "amount"}),
    ("insight/corr-top/", {"top": 3}),
    ("insight/segment-diff/", {"group_by": "city", "column": "amount"}),
    ("insight/narrate/", {}),
]


def test_dataintel(c):
    print("\n【dataintel 数据智能中心】%d 接口" % DI_EXPECTED)
    r = c.get("/api/dataintel/catalog/")
    check("dataintel/catalog 目录", ok200(r) and r.data["data"]["endpoint_count"] == DI_EXPECTED)

    # dataset CRUD（6）
    r = call(c, "POST", "/api/dataintel/dataset/create/", {"name": "销售样例", "rows": SAMPLE_ROWS})
    check("dataset/create", ok200(r))
    ds_id = r.data["data"]["id"]
    r = call(c, "POST", f"/api/dataintel/dataset/{ds_id}/", {})
    check("dataset/detail", ok200(r) and r.data["data"]["row_count"] == 12)
    r = call(c, "POST", f"/api/dataintel/dataset/{ds_id}/rows/import/", {"rows": [{"city": "杭州", "month": "2026-01", "amount": 60, "qty": 5, "score": 3.8}]})
    check("dataset/rows/import", ok200(r) and r.data["data"]["row_count"] == 13)
    r = call(c, "POST", f"/api/dataintel/dataset/{ds_id}/rows/query/", {"field": "city", "op": "eq", "value": "深圳", "limit": 10})
    check("dataset/rows/query 过滤", ok200(r) and r.data["data"]["total"] == 3)
    check("dataset/list", ok200(c.post("/api/dataintel/dataset/list/", {}, format="json")))

    # 其余 107 条表驱动（带 dataset_id）
    for path, payload in DATAI_ROWS:
        body = {**payload, "dataset_id": ds_id}
        if path in ("dataset/list/",):
            continue
        if path == "ai/status/":  # 仅支持 GET
            r = call(c, "GET", f"/api/dataintel/{path}", None)
        else:
            r = call(c, "POST", f"/api/dataintel/{path}", body)
        check(f"dataintel/{path}", ok200(r), f"status={r.status_code} body={str(r.data)[:120]}")

    # 深度断言
    r = call(c, "POST", "/api/dataintel/stats/ttest-one/", {"values": [10, 12, 9, 11, 13, 12, 8], "mu": 10})
    check("dataintel 深度：t 检验有 p 值", 0 <= r.data["data"].get("p_value", 1) <= 1)
    r = call(c, "POST", "/api/dataintel/abtest/assign/", {"user_key": "stable-user-1", "variants": ["A", "B"]})
    first = r.data["data"]["variant"]
    for _ in range(3):
        r2 = call(c, "POST", "/api/dataintel/abtest/assign/", {"user_key": "stable-user-1", "variants": ["A", "B"]})
        check("dataintel 深度：AB 分桶确定性", r2.data["data"]["variant"] == first)
        if r2.data["data"]["variant"] != first:
            break
    r = call(c, "POST", "/api/dataintel/geo/distance/", {"from": "深圳", "to": "广州"})
    check("dataintel 深度：深广距离合理", 80 < r.data["data"]["distance_km"] < 200)
    r = call(c, "POST", "/api/dataintel/insight/trend-brief/", {"dataset_id": ds_id, "column": "amount"})
    check("dataintel 深度：趋势简报有结论", len(r.data["data"].get("statement", "")) > 5)
    r = call(c, "POST", "/api/dataintel/insight/overview/", {"dataset_id": ds_id})
    check("dataintel 深度：洞察发现缺失列", any("缺失" in f for f in r.data["data"]["findings"]))
    # 降级验证
    r = call(c, "POST", "/api/dataintel/stats/ttest-one/", {"values": ["x", "y"], "mu": 10})
    check("dataintel 降级：脏数据 4xx", r.status_code in (400, 422) and r.data.get("ok") is False)
    r = call(c, "POST", "/api/dataintel/insight/overview/", {"dataset_id": 999999})
    check("dataintel 降级：不存在数据集 4xx", r.status_code in (400, 404, 422))
    # 收尾：删除数据集
    r = call(c, "POST", f"/api/dataintel/dataset/{ds_id}/delete/", {})
    check("dataset/delete", ok200(r))


# =====================================================================
# 第三部分：officesuite（catalog + 232 业务 = 233）
# =====================================================================


def test_officesuite(c, peer, boss):
    """c=提交人/操作者，peer=同租户普通同事，boss=超管审批人。

    自 S18 起审批链路禁止自批（#39/#41），且写权限按 owner 收口，
    因此审批类接口必须由跨可见范围的审批人（boss）发起。
    """
    print("\n【officesuite 办公套件】%d 接口" % OS_EXPECTED)
    r = c.get("/api/officesuite/catalog/")
    check("officesuite/catalog 目录", ok200(r) and r.data["data"]["endpoint_count"] == OS_EXPECTED)

    # ---- approval（12）----
    r = c.get("/api/officesuite/approval/templates/")
    check("approval/templates", ok200(r))
    r = call(c, "POST", "/api/officesuite/approval/submit/", {"title": "请假：回家看鸭", "type": "leave", "detail": {"days": 2}, "urgency": "high"})
    check("approval/submit", ok200(r))
    ap_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/approval/my-submitted/", {"status": "pending"})
    check("approval/my-submitted", ok200(r) and r.data["data"]["count"] >= 1)
    r = call(c, "POST", "/api/officesuite/approval/my-pending/", {})
    check("approval/my-pending", ok200(r))
    r = call(c, "POST", f"/api/officesuite/approval/{ap_id}/", {})
    check("approval/detail", ok200(r) and r.data["data"]["events"])
    r = call(c, "POST", f"/api/officesuite/approval/{ap_id}/comment/", {"text": "请安排好交接"})
    check("approval/comment", ok200(r))
    r = call(c, "POST", f"/api/officesuite/approval/{ap_id}/urge/", {"note": "加急"})
    check("approval/urge", ok200(r))
    r = call(c, "POST", f"/api/officesuite/approval/{ap_id}/events/", {})
    check("approval/events", ok200(r) and r.data["data"]["count"] >= 3)
    r = call(c, "POST", "/api/officesuite/approval/stats/", {})
    check("approval/stats", ok200(r))
    # 重复单测试 reject + cancel
    r = call(c, "POST", "/api/officesuite/approval/submit/", {"title": "采购显示器", "type": "purchase"})
    ap2 = r.data["data"]["id"]
    r = call(c, "POST", f"/api/officesuite/approval/{ap2}/reject/", {"reason": "预算不足"})
    check("approval 降级：自批被拒（驳回）", r.status_code in (400, 403, 422))
    r = call(boss, "POST", f"/api/officesuite/approval/{ap2}/reject/", {"reason": "预算不足"})
    check("approval/reject", ok200(r) and r.data["data"]["status"] == "rejected")
    r = call(c, "POST", "/api/officesuite/approval/submit/", {"title": "加班餐补"})
    ap3 = r.data["data"]["id"]
    r = call(c, "POST", f"/api/officesuite/approval/{ap3}/cancel/", {})
    check("approval/cancel", ok200(r))
    r = call(c, "POST", f"/api/officesuite/approval/{ap_id}/approve/", {"note": "同意"})
    check("approval 降级：自批被拒（通过）", r.status_code in (400, 403, 422))
    r = call(boss, "POST", f"/api/officesuite/approval/{ap_id}/approve/", {"note": "同意"})
    check("approval/approve", ok200(r) and r.data["data"]["status"] == "approved")
    r = call(boss, "POST", f"/api/officesuite/approval/{ap_id}/approve/", {"note": "再批一次"})
    check("approval 降级：重复审批被拒", r.status_code in (400, 422))

    # ---- seal（6）----
    r = call(c, "POST", "/api/officesuite/seal/apply/", {"title": "合同盖章", "seal_type": "公章", "copies": 2})
    check("seal/apply", ok200(r))
    seal_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/seal/mine/", {})
    check("seal/mine", ok200(r))
    r = call(c, "POST", "/api/officesuite/seal/log/", {})
    check("seal/log", ok200(r))
    r = call(c, "POST", "/api/officesuite/seal/stats/", {})
    check("seal/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/seal/{seal_id}/", {})
    check("seal/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/seal/{seal_id}/approve/", {"action": "approve"})
    check("seal/approve", ok200(r))

    # ---- expense（8）----
    r = call(c, "POST", "/api/officesuite/expense/submit/", {"title": "差旅报销", "items": [{"name": "机票", "amount": 800}], "invoice_count": 2})
    check("expense/submit", ok200(r))
    exp_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/expense/mine/", {})
    check("expense/mine", ok200(r))
    r = call(c, "POST", "/api/officesuite/expense/stats/", {})
    check("expense/stats", ok200(r))
    r = call(c, "POST", "/api/officesuite/expense/export/", {})
    check("expense/export", ok200(r))
    r = call(c, "POST", f"/api/officesuite/expense/{exp_id}/", {})
    check("expense/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/expense/{exp_id}/approve/", {"note": "ok"})
    check("expense/approve", ok200(r))
    r = call(c, "POST", f"/api/officesuite/expense/{exp_id}/pay/", {})
    check("expense/pay", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/expense/submit/", {"title": "测试驳回单"})
    r = call(c, "POST", f"/api/officesuite/expense/{r2.data['data']['id']}/reject/", {"reason": "发票抬头错误"})
    check("expense/reject", ok200(r))

    # ---- travel（7）----
    r = call(c, "POST", "/api/officesuite/travel/apply/", {"title": "深圳出差", "destination": "上海", "start_date": "2026-10-01", "end_date": "2026-10-03", "estimate": 2000})
    check("travel/apply", ok200(r))
    tv_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/travel/mine/", {})
    check("travel/mine", ok200(r))
    r = call(c, "POST", "/api/officesuite/travel/all/", {})
    check("travel/all", ok200(r))
    r = call(c, "POST", "/api/officesuite/travel/stats/", {})
    check("travel/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/travel/{tv_id}/", {})
    check("travel/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/travel/{tv_id}/approve/", {"action": "approve"})
    check("travel/approve", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/travel/apply/", {"title": "取消测试", "destination": "广州"})
    r = call(c, "POST", f"/api/officesuite/travel/{r2.data['data']['id']}/cancel/", {})
    check("travel/cancel", ok200(r))

    # ---- contract（8）----
    r = call(c, "POST", "/api/officesuite/contract/create/", {"title": "云服务采购合同", "party": "某云厂商", "amount": 50000, "sign_date": "2026-01-10", "expire_date": "2026-12-31"})
    check("contract/create", ok200(r))
    ct_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/contract/list/", {})
    check("contract/list", ok200(r))
    r = call(c, "POST", "/api/officesuite/contract/expiring/", {"days": 365})
    check("contract/expiring", ok200(r))
    r = call(c, "POST", "/api/officesuite/contract/stats/", {})
    check("contract/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/contract/{ct_id}/", {})
    check("contract/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/contract/{ct_id}/status/", {"status": "active"})
    check("contract/status", ok200(r))
    r = call(c, "POST", f"/api/officesuite/contract/{ct_id}/payments/", {"payments": [{"date": "2026-01-10", "amount": 25000}, {"date": "2026-07-01", "amount": 25000}]})
    check("contract/payments", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/contract/create/", {"title": "待删合同"})
    r = call(c, "POST", f"/api/officesuite/contract/{r2.data['data']['id']}/delete/", {})
    check("contract/delete", ok200(r))

    # ---- meeting（10）----
    r = call(c, "POST", "/api/officesuite/meeting/room/create/", {"name": "小会议室 A", "capacity": 8, "location": "3F", "facilities": ["投屏", "白板"]})
    check("meeting/room/create", ok200(r))
    room_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/meeting/room/list/", {})
    check("meeting/room/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/meeting/room/{room_id}/update/", {"capacity": 10})
    check("meeting/room/update", ok200(r))
    r = call(c, "GET", f"/api/officesuite/meeting/room/{room_id}/availability/", {"date": "2026-09-15"})
    check("meeting/room/availability", ok200(r))
    r = call(c, "POST", "/api/officesuite/meeting/book/", {"room_id": room_id, "title": "周会", "start_at": "2026-09-15 10:00", "end_at": "2026-09-15 11:00"})
    check("meeting/book", ok200(r))
    book_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/meeting/book/", {"room_id": room_id, "title": "冲突测试", "start_at": "2026-09-15 10:30", "end_at": "2026-09-15 11:30"})
    check("meeting 深度：时段冲突拒绝", r.status_code in (400, 422))
    r = call(c, "GET", "/api/officesuite/meeting/my-bookings/", {})
    check("meeting/my-bookings", ok200(r))
    r = call(c, "GET", "/api/officesuite/meeting/stats/", {})
    check("meeting/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/meeting/booking/{book_id}/detail/", {})
    check("meeting/booking/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/meeting/booking/{book_id}/cancel/", {})
    check("meeting/booking/cancel", ok200(r))

    # ---- asset（9）----
    r = call(c, "POST", "/api/officesuite/asset/create/", {"title": "MacBook Pro 14", "category": "电脑", "value": 18999})
    check("asset/create", ok200(r))
    as_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/asset/list/", {})
    check("asset/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/asset/{as_id}/update/", {"remark": "新机"})
    check("asset/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/asset/{as_id}/assign/", {"holder_name": PEER_NAME})
    check("asset/assign", ok200(r))
    r = call(c, "POST", f"/api/officesuite/asset/{as_id}/detail/", {})
    check("asset/detail", ok200(r) and r.data["data"]["events"])
    r = call(c, "GET", "/api/officesuite/asset/my-held/", {})
    check("asset/my-held", ok200(r))
    r = call(c, "GET", "/api/officesuite/asset/stats/", {})
    check("asset/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/asset/{as_id}/return/", {"note": "完好"})
    check("asset/return", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/asset/create/", {"title": "待删资产"})
    r = call(c, "POST", f"/api/officesuite/asset/{r2.data['data']['id']}/delete/", {})
    check("asset/delete", ok200(r))

    # ---- vehicle（7）----
    r = call(c, "POST", "/api/officesuite/vehicle/create/", {"plate": "粤B88888", "model_name": "别克 GL8", "seats": 7})
    check("vehicle/create", ok200(r))
    vh_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/vehicle/list/", {})
    check("vehicle/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/vehicle/{vh_id}/update/", {"seats": 6})
    check("vehicle/update", ok200(r))
    r = call(c, "POST", "/api/officesuite/vehicle/book/", {"vehicle_id": vh_id, "destination": "机场", "use_at": "2026-09-16 08:00"})
    check("vehicle/book", ok200(r))
    vb_id = r.data["data"]["id"]
    r = call(c, "POST", f"/api/officesuite/vehicle/booking/{vb_id}/approve/", {"action": "approve"})
    check("vehicle 降级：自批被拒", r.status_code in (400, 403, 422))
    r = call(boss, "POST", f"/api/officesuite/vehicle/booking/{vb_id}/approve/", {"action": "approve"})
    check("vehicle/booking/approve", ok200(r))
    r = call(c, "GET", "/api/officesuite/vehicle/my-bookings/", {})
    check("vehicle/my-bookings", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/vehicle/book/", {"vehicle_id": vh_id, "destination": "取消测试", "use_at": "2026-09-17 08:00"})
    r = call(c, "POST", f"/api/officesuite/vehicle/booking/{r2.data['data']['id']}/cancel/", {})
    check("vehicle/booking/cancel", ok200(r))

    # ---- supplies（7）----
    r = call(c, "POST", "/api/officesuite/supplies/item/create/", {"name": "A4 打印纸", "stock": 100, "unit": "包"})
    check("supplies/item/create", ok200(r))
    it_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/supplies/item/list/", {})
    check("supplies/item/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/supplies/item/{it_id}/restock/", {"delta": 50})
    check("supplies/item/restock", ok200(r) and r.data["data"]["stock"] == 150)
    r = call(c, "POST", "/api/officesuite/supplies/apply/", {"item_id": it_id, "qty": 10, "purpose": "打印周报"})
    check("supplies/apply", ok200(r) and r.data["data"]["stock_left"] == 140)
    aply_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/supplies/apply/", {"item_id": it_id, "qty": 99999})
    check("supplies 深度：库存不足拒绝", r.status_code in (400, 422))
    r = call(c, "GET", "/api/officesuite/supplies/my-applies/", {})
    check("supplies/my-applies", ok200(r))
    r = call(c, "GET", "/api/officesuite/supplies/stats/", {})
    check("supplies/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/supplies/apply/{aply_id}/cancel/", {})
    check("supplies/apply/cancel 回滚库存", ok200(r))

    # ---- visitor（7）----
    r = call(c, "POST", "/api/officesuite/visitor/create/", {"visitor_name": "王客户", "company": "某客户公司", "host_name": "小苏"})
    check("visitor/create", ok200(r))
    vs_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/visitor/list/", {})
    check("visitor/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/visitor/{vs_id}/update/", {"company": "更新后的单位"})
    check("visitor/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/visitor/{vs_id}/checkin/", {})
    check("visitor/checkin", ok200(r))
    r = call(c, "GET", "/api/officesuite/visitor/today/")
    check("visitor/today", ok200(r))
    r = call(c, "POST", f"/api/officesuite/visitor/{vs_id}/checkout/", {})
    check("visitor/checkout", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/visitor/create/", {"visitor_name": "待删访客"})
    r = call(c, "POST", f"/api/officesuite/visitor/{r2.data['data']['id']}/delete/", {})
    check("visitor/delete", ok200(r))

    # ---- mailroom（5）----
    r = call(c, "POST", "/api/officesuite/mailroom/create/", {"receiver_name": "小苏", "sender_info": "顺丰 SF123"})
    check("mailroom/create", ok200(r))
    ml_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/mailroom/list/", {})
    check("mailroom/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/mailroom/pending/")
    check("mailroom/pending", ok200(r))
    r = call(c, "GET", "/api/officesuite/mailroom/stats/")
    check("mailroom/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/mailroom/{ml_id}/pickup/", {})
    check("mailroom/pickup", ok200(r))

    # ---- duty（9）----
    r = call(c, "POST", "/api/officesuite/duty/schedule/create/", {"name": "九月值班表", "start_date": "2026-09-01"})
    check("duty/schedule/create", ok200(r))
    ds_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/duty/schedule/list/", {})
    check("duty/schedule/list", ok200(r))
    r = call(c, "POST", "/api/officesuite/duty/shift/add/", {"schedule_id": ds_id, "duty_date": "2026-09-20", "member_name": PEER_NAME, "shift_name": "白班"})
    check("duty/shift/add", ok200(r))
    sh_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/duty/shift/list/", {"schedule_id": ds_id})
    check("duty/shift/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/duty/shift/{sh_id}/swap/", {"swap_to": "test"})
    check("duty/shift/swap", ok200(r))
    r = call(c, "GET", "/api/officesuite/duty/week/", {"date": "2026-09-20"})
    check("duty/week", ok200(r))
    r = call(c, "GET", "/api/officesuite/duty/my-shifts/")
    check("duty/my-shifts", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/duty/shift/add/", {"schedule_id": ds_id, "duty_date": "2026-09-21", "member_name": PEER_NAME})
    r = call(c, "POST", f"/api/officesuite/duty/shift/{r2.data['data']['id']}/delete/", {})
    check("duty/shift/delete", ok200(r))
    r = call(c, "POST", f"/api/officesuite/duty/schedule/{ds_id}/delete/", {})
    check("duty/schedule/delete", ok200(r))

    # ---- timesheet（9）----
    r = call(c, "POST", "/api/officesuite/timesheet/create/", {"work_date": "2026-09-14", "hours": 7.5, "project_name": "v5 大版本"})
    check("timesheet/create", ok200(r))
    ts_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/timesheet/list/", {})
    check("timesheet/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/timesheet/week/", {"date": "2026-09-14"})
    check("timesheet/week", ok200(r))
    r = call(c, "GET", "/api/officesuite/timesheet/summary/", {})
    check("timesheet/summary", ok200(r))
    r = call(c, "GET", "/api/officesuite/timesheet/stats/")
    check("timesheet/stats", ok200(r))
    r = call(c, "GET", "/api/officesuite/timesheet/export/")
    check("timesheet/export", ok200(r))
    r = call(c, "POST", f"/api/officesuite/timesheet/{ts_id}/update/", {"hours": 8})
    check("timesheet/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/timesheet/{ts_id}/approve/", {"action": "approve"})
    check("timesheet 降级：自批被拒", r.status_code in (400, 403, 422))
    r = call(boss, "POST", f"/api/officesuite/timesheet/{ts_id}/approve/", {"action": "approve"})
    check("timesheet/approve", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/timesheet/create/", {"work_date": "2026-09-13", "hours": 2, "project_name": "删除测试"})
    r = call(c, "POST", f"/api/officesuite/timesheet/{r2.data['data']['id']}/delete/", {})
    check("timesheet/delete", ok200(r))

    # ---- training（10）----
    r = call(c, "POST", "/api/officesuite/training/create/", {"topic": "Django 5 实战", "trainer": "小苏", "start_at": "2026-09-20 14:00", "capacity": 2})
    check("training/create", ok200(r))
    tr_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/training/list/", {})
    check("training/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/training/{tr_id}/detail/", {})
    check("training/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/training/{tr_id}/update/", {"capacity": 3})
    check("training/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/training/{tr_id}/enroll/", {})
    check("training/enroll", ok200(r))
    en_id = r.data["data"]["id"]
    r = call(c, "POST", f"/api/officesuite/training/enroll/{en_id}/checkin/", {})
    check("training/checkin", ok200(r))
    r = call(c, "POST", f"/api/officesuite/training/enroll/{en_id}/feedback/", {"rating": 5, "feedback": "讲得不错"})
    check("training/feedback", ok200(r))
    r = call(c, "GET", f"/api/officesuite/training/{tr_id}/roster/", {})
    check("training/roster", ok200(r))
    r2 = call(peer, "POST", f"/api/officesuite/training/{tr_id}/enroll/", {})
    r = call(peer, "POST", f"/api/officesuite/training/enroll/{r2.data['data']['id']}/cancel/", {})
    check("training/enroll/cancel", ok200(r))
    r = call(c, "POST", f"/api/officesuite/training/{tr_id}/delete/", {})
    check("training/delete", ok200(r))

    # ---- recognition（6）----
    r = call(c, "POST", "/api/officesuite/recognition/create/", {"title": "本周之星", "to_name": "小苏", "level": "公司", "reason": "v5 上线功臣"})
    check("recognition/create", ok200(r))
    rc_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/recognition/list/", {})
    check("recognition/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/recognition/{rc_id}/like/", {})
    check("recognition/like", ok200(r) and r.data["data"]["likes"] == 1)
    r = call(c, "GET", "/api/officesuite/recognition/ranking/")
    check("recognition/ranking", ok200(r))
    r = call(c, "GET", "/api/officesuite/recognition/stats/")
    check("recognition/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/recognition/{rc_id}/delete/", {})
    check("recognition/delete", ok200(r))

    # ---- standup（7）----
    r = call(c, "POST", "/api/officesuite/standup/create/", {"yesterday": "修 bug", "today": "写 v5", "blockers": "无"})
    check("standup/create", ok200(r))
    sd_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/standup/list/", {})
    check("standup/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/standup/today/")
    check("standup/today", ok200(r) and r.data["data"]["submitted_count"] >= 1)
    r = call(c, "POST", "/api/officesuite/standup/create/", {"yesterday": "重复提交测试"})
    check("standup 深度：同日重复幂等", ok200(r) and r.data["data"].get("existing") is True)
    r = call(c, "GET", "/api/officesuite/standup/summary/")
    check("standup/summary", ok200(r))
    r = call(c, "GET", "/api/officesuite/standup/export/")
    check("standup/export", ok200(r))
    r = call(c, "POST", f"/api/officesuite/standup/{sd_id}/update/", {"today": "改：继续写 v5"})
    check("standup/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/standup/{sd_id}/delete/", {})
    check("standup/delete", ok200(r))

    # ---- okr（10）----
    r = call(c, "POST", "/api/officesuite/okr/objective/create/", {"title": "Q4 完成 v5 上线", "period": "2026-Q4", "description": "全量功能落地"})
    check("okr/objective/create", ok200(r))
    ob_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/okr/objective/list/", {"period": "2026-Q4"})
    check("okr/objective/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/okr/objective/{ob_id}/", {})
    check("okr/objective/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/okr/objective/{ob_id}/update/", {"description": "更新描述"})
    check("okr/objective/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/okr/objective/{ob_id}/kr/add/", {"content": "501 接口全绿", "weight": 3, "progress": 20})
    check("okr/kr/add", ok200(r))
    kr_id = r.data["data"]["id"]
    r = call(c, "POST", f"/api/officesuite/okr/kr/{kr_id}/progress/", {"progress": 80})
    check("okr 深度：KR 进度联动 O", ok200(r) and r.data["data"]["objective_progress"] == 80)
    r = call(c, "GET", "/api/officesuite/okr/overview/", {"period": "2026-Q4"})
    check("okr/overview", ok200(r))
    r = call(c, "GET", "/api/officesuite/okr/history/")
    check("okr/history", ok200(r))
    r2 = call(c, "POST", f"/api/officesuite/okr/objective/{ob_id}/kr/add/", {"content": "临时 KR", "weight": 1})
    r = call(c, "POST", f"/api/officesuite/okr/kr/{r2.data['data']['id']}/delete/", {})
    check("okr/kr/delete", ok200(r))
    r = call(c, "POST", f"/api/officesuite/okr/objective/{ob_id}/delete/", {})
    check("okr/objective/delete", ok200(r))

    # ---- decision（7）----
    r = call(c, "POST", "/api/officesuite/decision/create/", {"title": "前端框架选型", "context": "Vue3 vs React", "options": ["Vue3", "React"]})
    check("decision/create", ok200(r))
    dc_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/decision/list/", {"status": "open"})
    check("decision/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/decision/{dc_id}/", {})
    check("decision/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/decision/{dc_id}/update/", {"context": "补充：团队熟悉度"})
    check("decision/update", ok200(r))
    r = call(c, "POST", "/api/officesuite/decision/create/", {"title": "选项校验", "options": ["A", "B"]})
    r = call(c, "POST", f"/api/officesuite/decision/{r.data['data']['id']}/decide/", {"choice": "C"})
    check("decision 深度：候选外选择拒绝", r.status_code in (400, 422))
    r = call(c, "POST", f"/api/officesuite/decision/{dc_id}/decide/", {"choice": "Vue3", "rationale": "全家桶熟"})
    check("decision/decide", ok200(r))
    r = call(c, "GET", "/api/officesuite/decision/archive/")
    check("decision/archive", ok200(r))
    r = call(c, "POST", f"/api/officesuite/decision/{dc_id}/delete/", {})
    check("decision/delete", ok200(r))

    # ---- todobox（8）----
    r = call(c, "POST", "/api/officesuite/todo/create/", {"title": "回复邮件", "priority": "high", "due_date": "2026-09-15"})
    check("todo/create", ok200(r))
    td_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/todo/list/", {})
    check("todo/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/todo/{td_id}/update/", {"priority": "urgent"})
    check("todo/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/todo/{td_id}/complete/", {})
    check("todo/complete", ok200(r))
    r = call(c, "POST", f"/api/officesuite/todo/{td_id}/reopen/", {})
    check("todo/reopen", ok200(r))
    r2 = call(c, "POST", "/api/officesuite/todo/create/", {"title": "批量测试1"})
    r3 = call(c, "POST", "/api/officesuite/todo/create/", {"title": "批量测试2"})
    r = call(c, "POST", "/api/officesuite/todo/batch-complete/", {"ids": [r2.data["data"]["id"], r3.data["data"]["id"]]})
    check("todo/batch-complete", ok200(r) and r.data["data"]["updated"] == 2)
    r = call(c, "GET", "/api/officesuite/todo/stats/")
    check("todo/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/todo/{td_id}/delete/", {})
    check("todo/delete", ok200(r))

    # ---- faq（7）----
    r = call(c, "POST", "/api/officesuite/faq/create/", {"title": "如何申请休假？", "answer": "OA 审批流提交", "category": "行政", "tags": ["休假", "OA"]})
    check("faq/create", ok200(r))
    fq_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/faq/list/", {"category": "行政"})
    check("faq/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/faq/search/", {"keyword": "休假"})
    check("faq/search", ok200(r))
    r = call(c, "GET", "/api/officesuite/faq/stats/")
    check("faq/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/faq/{fq_id}/update/", {"answer": "OA 审批流提交（更新版）"})
    check("faq/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/faq/{fq_id}/vote/", {})
    check("faq/vote", ok200(r) and r.data["data"]["votes"] == 1)
    r = call(c, "POST", f"/api/officesuite/faq/{fq_id}/delete/", {})
    check("faq/delete", ok200(r))

    # ---- policy（7）----
    r = call(c, "POST", "/api/officesuite/policy/create/", {"title": "考勤制度", "content": "9 点打卡", "version": "v1.0", "effective_date": "2026-10-01"})
    check("policy/create", ok200(r))
    po_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/policy/list/", {})
    check("policy/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/policy/{po_id}/", {})
    check("policy/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/policy/{po_id}/update/", {"content": "9:30 打卡"})
    check("policy/update 自动升版本", ok200(r) and r.data["data"]["version"] == "v1.1")
    r = call(c, "POST", f"/api/officesuite/policy/{po_id}/ack/", {})
    check("policy/ack", ok200(r) and r.data["data"]["acked_by_me"] is True)
    r = call(c, "GET", f"/api/officesuite/policy/{po_id}/ack-list/")
    check("policy/ack-list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/policy/{po_id}/delete/", {})
    check("policy/delete", ok200(r))

    # ---- template（7）----
    r = call(c, "POST", "/api/officesuite/template/create/", {"title": "周报模板", "content": "本周完成：{{done}}\n下周计划：{{plan}}", "category": "周报"})
    check("template/create", ok200(r))
    tp_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/template/list/", {})
    check("template/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/template/categories/")
    check("template/categories", ok200(r))
    r = call(c, "POST", f"/api/officesuite/template/{tp_id}/", {})
    check("template/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/template/{tp_id}/render/", {"vars": {"done": "v5 接口", "plan": "前端页面"}})
    check("template/render", ok200(r) and r.data["data"]["complete"] is True and "v5 接口" in r.data["data"]["rendered"])
    r = call(c, "POST", f"/api/officesuite/template/{tp_id}/update/", {"category": "模板"})
    check("template/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/template/{tp_id}/delete/", {})
    check("template/delete", ok200(r))

    # ---- wiki（9）----
    r = call(c, "POST", "/api/officesuite/wiki/create/", {"title": "后端规范", "content": "接口统一 ok 格式"})
    check("wiki/create", ok200(r))
    wk_id = r.data["data"]["id"]
    r = call(c, "POST", "/api/officesuite/wiki/create/", {"title": "命名规范", "parent_id": wk_id, "content": "变量用小写下划线"})
    wk_child = r.data["data"]["id"]
    check("wiki/create 子页", ok200(r))
    r = call(c, "GET", "/api/officesuite/wiki/list/", {"parent_id": wk_id})
    check("wiki/list 子页过滤", ok200(r) and r.data["data"]["count"] == 1)
    r = call(c, "POST", f"/api/officesuite/wiki/{wk_id}/", {})
    check("wiki/detail", ok200(r) and r.data["data"]["version"] == 1)
    r = call(c, "POST", f"/api/officesuite/wiki/{wk_id}/update/", {"content": "接口统一 {ok, data} 格式", "note": "补充格式说明"})
    check("wiki/update 版本+1", ok200(r) and r.data["data"]["version"] == 2)
    r = call(c, "GET", f"/api/officesuite/wiki/{wk_id}/revisions/")
    check("wiki/revisions", ok200(r) and r.data["data"]["version"] == 2)
    r = call(c, "POST", f"/api/officesuite/wiki/{wk_id}/move/", {"parent_id": None, "order": 5})
    check("wiki/move", ok200(r))
    r = call(c, "POST", f"/api/officesuite/wiki/{wk_id}/move/", {"parent_id": wk_child})
    check("wiki 深度：移动到子树被拒", r.status_code in (400, 422))
    r = call(c, "GET", "/api/officesuite/wiki/search/", {"keyword": "规范"})
    check("wiki/search", ok200(r))
    r = call(c, "GET", "/api/officesuite/wiki/tree/")
    check("wiki/tree", ok200(r))

    # ---- minutes（7）----
    r = call(c, "POST", "/api/officesuite/minutes/create/", {"title": "v5 周会", "meeting_at": "2026-09-14 10:00", "attendees": ["小苏", "test"], "content": "1. 上线时间确定\n2. 行动：小苏负责压测"})
    check("minutes/create", ok200(r))
    mn_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/minutes/list/", {"keyword": "v5"})
    check("minutes/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/minutes/stats/")
    check("minutes/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/minutes/{mn_id}/", {})
    check("minutes/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/minutes/{mn_id}/update/", {"publish": True})
    check("minutes/update 发布", ok200(r) and r.data["data"]["status"] == "published")
    r = call(c, "GET", f"/api/officesuite/minutes/{mn_id}/action-items/")
    check("minutes/action-items", ok200(r) and r.data["data"]["count"] >= 1)
    r = call(c, "POST", f"/api/officesuite/minutes/{mn_id}/delete/", {})
    check("minutes/delete", ok200(r))

    # ---- formcollect（8）----
    r = call(c, "POST", "/api/officesuite/form/create/", {"title": "团建报名", "fields": [{"name": "name", "type": "text", "required": True}, {"name": "phone", "type": "text", "required": False}]})
    check("form/create", ok200(r))
    fm_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/form/list/", {})
    check("form/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/form/{fm_id}/", {})
    check("form/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/form/{fm_id}/submit/", {"values": {"name": "小苏", "phone": "13800138000"}})
    check("form/submit", ok200(r))
    r = call(c, "POST", f"/api/officesuite/form/{fm_id}/submit/", {"values": {"phone": "缺姓名"}})
    check("form 深度：必填校验拒绝", r.status_code in (400, 422))
    r = call(c, "GET", f"/api/officesuite/form/{fm_id}/entries/")
    check("form/entries", ok200(r) and r.data["data"]["count"] == 1)
    r = call(c, "GET", f"/api/officesuite/form/{fm_id}/export/")
    check("form/export", ok200(r) and "小苏" in r.data["data"]["csv"])
    r = call(c, "POST", f"/api/officesuite/form/{fm_id}/update/", {"closed": True})
    check("form/update 截止", ok200(r) and r.data["data"]["closed"] is True)
    r = call(c, "POST", f"/api/officesuite/form/{fm_id}/delete/", {})
    check("form/delete", ok200(r))

    # ---- announcement（8）----
    r = call(c, "POST", "/api/officesuite/announcement/create/", {"title": "v5 上线公告", "content": "501 接口正式上线", "audience": "全员", "pinned": True})
    check("announcement/create", ok200(r))
    an_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/announcement/list/", {})
    check("announcement/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/announcement/{an_id}/", {})
    check("announcement/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/announcement/{an_id}/update/", {"content": "501 接口 + 78 子系统"})
    check("announcement/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/announcement/{an_id}/pin/", {})
    check("announcement/pin 切换", ok200(r) and r.data["data"]["pinned"] is False)
    r = call(c, "POST", f"/api/officesuite/announcement/{an_id}/read/", {})
    check("announcement/read", ok200(r))
    r = call(c, "GET", f"/api/officesuite/announcement/{an_id}/readers/")
    check("announcement/readers", ok200(r))
    r = call(c, "POST", f"/api/officesuite/announcement/{an_id}/delete/", {})
    check("announcement/delete", ok200(r))

    # ---- poll（9）----
    r = call(c, "POST", "/api/officesuite/poll/create/", {"question": "团建吃什么？", "options": ["火锅", "烧烤", "日料"], "multiple": False})
    check("poll/create", ok200(r))
    pl_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/poll/list/", {})
    check("poll/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/poll/my-votes/", {})
    check("poll/my-votes", ok200(r))
    r = call(c, "POST", f"/api/officesuite/poll/{pl_id}/", {})
    check("poll/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/poll/{pl_id}/vote/", {"choices": ["火锅"]})
    check("poll/vote", ok200(r))
    r = call(c, "POST", f"/api/officesuite/poll/{pl_id}/vote/", {"choices": ["烧烤"]})
    check("poll 深度：重复投票拒绝", r.status_code in (400, 422))
    r = call(c, "GET", f"/api/officesuite/poll/{pl_id}/results/")
    check("poll/results", ok200(r) and r.data["data"]["results"][0]["option"] == "火锅")
    r = call(c, "POST", f"/api/officesuite/poll/{pl_id}/close/", {})
    check("poll/close", ok200(r))
    r = call(c, "POST", f"/api/officesuite/poll/{pl_id}/reopen/", {})
    check("poll/reopen", ok200(r))
    r = call(c, "POST", f"/api/officesuite/poll/{pl_id}/delete/", {})
    check("poll/delete", ok200(r))

    # ---- helpdesk（9）----
    r = call(c, "POST", "/api/officesuite/ticket/create/", {"title": "打印机故障", "description": "3 楼打印机卡纸", "priority": "high", "category": "行政"})
    check("ticket/create", ok200(r))
    tk_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/ticket/list/", {"status": "open"})
    check("ticket/list", ok200(r))
    r = call(c, "GET", "/api/officesuite/ticket/stats/")
    check("ticket/stats", ok200(r))
    r = call(c, "POST", f"/api/officesuite/ticket/{tk_id}/", {})
    check("ticket/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/ticket/{tk_id}/assign/", {"assignee": "test"})
    check("ticket/assign", ok200(r) and r.data["data"]["status"] == "in_progress")
    r = call(c, "POST", f"/api/officesuite/ticket/{tk_id}/priority/", {"priority": "urgent"})
    check("ticket/priority", ok200(r))
    r = call(c, "POST", f"/api/officesuite/ticket/{tk_id}/reply/", {"content": "已联系供应商"})
    check("ticket/reply", ok200(r))
    r = call(c, "POST", f"/api/officesuite/ticket/{tk_id}/resolve/", {"solution": "换硒鼓"})
    check("ticket/resolve", ok200(r))
    r = call(c, "POST", f"/api/officesuite/ticket/{tk_id}/reopen/", {"reason": "又卡纸了"})
    check("ticket/reopen", ok200(r))

    # ---- calendar（9）----
    r = call(c, "POST", "/api/officesuite/calendar/event/create/", {"title": "v5 发布会", "start_at": "2026-09-15 15:00", "end_at": "2026-09-15 16:00", "kind": "meeting", "attendees": ["小苏", "test"]})
    check("calendar/event/create", ok200(r))
    ev_id = r.data["data"]["id"]
    r = call(c, "GET", "/api/officesuite/calendar/event/list/", {"start": "2026-09-15 00:00", "end": "2026-09-16 00:00"})
    check("calendar/event/list", ok200(r))
    r = call(c, "POST", f"/api/officesuite/calendar/event/{ev_id}/", {})
    check("calendar/event/detail", ok200(r))
    r = call(c, "POST", f"/api/officesuite/calendar/event/{ev_id}/update/", {"title": "v5 发布会（改期）", "start_at": "2026-09-16 15:00"})
    check("calendar/event/update", ok200(r))
    r = call(c, "POST", f"/api/officesuite/calendar/event/{ev_id}/rsvp/", {"answer": "yes"})
    check("calendar/event/rsvp", ok200(r))
    r = call(c, "GET", f"/api/officesuite/calendar/event/{ev_id}/attendees/")
    check("calendar/event/attendees", ok200(r))
    r = call(c, "GET", "/api/officesuite/calendar/agenda/today/")
    check("calendar/agenda/today", ok200(r))
    r = call(c, "GET", "/api/officesuite/calendar/agenda/week/", {"date": "2026-09-16"})
    check("calendar/agenda/week", ok200(r))
    r = call(c, "POST", f"/api/officesuite/calendar/event/{ev_id}/delete/", {})
    check("calendar/event/delete", ok200(r))

    # ---- 权限收口验证（跨用户）----
    r = call(peer, "POST", f"/api/officesuite/approval/{ap_id}/", {})
    check("officesuite 深度：peer 不可见他人审批单", r.status_code in (400, 403, 404))
    r = call(peer, "POST", f"/api/officesuite/faq/999999/vote/", {})
    check("officesuite 降级：不存在对象 4xx", r.status_code in (400, 404, 422))


def main():
    ts = int(time.time())
    c = APIClient()
    r = c.post("/api/auth/register/", {"username": f"suite{ts}", "password": "test12345"}, format="json")
    if r.status_code not in (200, 201):
        print("注册失败", r.status_code, str(r.data)[:200])
        raise SystemExit(1)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    global PEER_NAME
    r2 = c.post("/api/auth/register/", {"username": f"peer{ts}", "password": "test12345"}, format="json")
    PEER_NAME = f"peer{ts}"
    peer = APIClient()
    peer.credentials(HTTP_AUTHORIZATION=f"Bearer {r2.data['access']}")

    # 审批人：注册后提权为超管，用 force_authenticate（避免复登/密码策略干扰）。
    # 审批链路要求「跨 owner 可见 + 写权限」，普通同事（self 范围）不再具备。
    r3 = c.post("/api/auth/register/", {"username": f"boss{ts}", "password": "test12345"}, format="json")
    if r3.status_code not in (200, 201):
        print("审批人注册失败", r3.status_code, str(r3.data)[:200])
        raise SystemExit(1)
    from django.contrib.auth import get_user_model  # noqa: E402

    boss_user = get_user_model().objects.get(username=f"boss{ts}")
    boss_user.is_staff = True
    boss_user.is_superuser = True
    boss_user.save(update_fields=["is_staff", "is_superuser"])
    boss = APIClient()
    boss.force_authenticate(user=boss_user)

    t0 = time.time()
    test_devtools(c)
    test_dataintel(c)
    test_officesuite(c, peer, boss)
    cost = time.time() - t0

    print(f"\n========== v5 套件冒烟：通过 {len(passed)} / 失败 {len(failed)} ==========")
    if failed:
        print("失败清单：")
        for f_ in failed:
            print(f"  - {f_}")
        raise SystemExit(1)
    print(f"全部通过，耗时 {cost:.1f}s")


PEER_NAME = ""


if __name__ == "__main__":
    main()
