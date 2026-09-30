# -*- coding: utf-8 -*-
"""minitools 冒烟测试：catalog + 抽测 20+ 工具 + 错误输入兜底。"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient

c = APIClient()
# 绕过认证：创建/复用一个测试用户并 force_authenticate
from django.contrib.auth import get_user_model
User = get_user_model()
u, _ = User.objects.get_or_create(username="smoke_test_user", defaults={"is_active": True})
c.force_authenticate(user=u)

# 1. catalog
r = c.get("/api/minitools/catalog/")
assert r.status_code == 200, f"catalog status {r.status_code}: {r.content[:200]}"
data = r.json()["data"]
print(f"[catalog] domain={data['domain']} subsystems={data['subsystem_count']} endpoints={data['endpoint_count']}")
assert data["subsystem_count"] == 19, data["subsystem_count"]
assert data["endpoint_count"] == 321, data["endpoint_count"]
assert len(data["endpoints"]) == 320, len(data["endpoints"])

# 2. 抽测工具（覆盖每个家族至少2个）
cases = [
    # text
    ("text/case-title/", {"text": "hello world"}),
    ("text/dedup-lines/", {"text": "a\nb\na\nc"}),
    ("text/palindrome-check/", {"text": "A man a plan Panama"}),
    ("text/zero-width-remove/", {"text": "abc\u200bdef"}),
    # num
    ("num/to-chinese-upper/", {"number": 123.45}),
    ("num/prime-factorize/", {"number": 360}),
    ("num/bmi-calc/", {"height_cm": 175, "weight_kg": 70}),
    ("num/factorial/", {"n": 10}),
    # encode
    ("encode/base64/", {"text": "hello", "direction": "encode"}),
    ("encode/rot-n/", {"text": "Hello", "n": 13}),
    ("encode/morse/", {"text": "SOS", "direction": "encode"}),
    ("encode/url-codec/", {"text": "hello world", "direction": "encode"}),
    # date
    ("date/leap-year/", {"year": 2024}),
    ("date/weekday/", {"date": "2026-09-25"}),
    ("date/easter-calc/", {"year": 2026}),
    # color
    ("color/convert/", {"value": "#ff0000", "from": "hex", "to": "rgb"}),
    ("color/invert/", {"color": "#000000"}),
    ("color/gradient/", {"color_a": "#000000", "color_b": "#ffffff", "steps": 4}),
    # gen
    ("gen/uuid/", {"version": 4, "count": 2}),
    ("gen/password/", {"length": 12, "count": 2}),
    ("gen/hash/", {"text": "hello", "algorithm": "md5"}),
    ("gen/qrcode/", {"text": "hello", "size": 100}),
    # validate
    ("validate/email/", {"email": "test@example.com"}),
    ("validate/phone-cn/", {"phone": "13800138000"}),
    ("validate/json/", {"json_text": '{"a":1}'}),
    ("validate/ip/", {"ip": "8.8.8.8"}),
    # convert
    ("convert/temperature/", {"value": 100, "from": "C", "to": "F"}),
    ("convert/base-arbitrary/", {"value": "ff", "from": 16, "to": 2}),
    ("convert/length/", {"value": 1, "from": "km", "to": "m"}),
    # fun
    ("fun/dice/", {"sides": 6, "count": 3}),
    ("fun/rock-paper-scissors/", {"player_choice": "石头"}),
    ("fun/fortune-today/", {"zodiac": "鼠"}),
]

passed = 0
for path, body in cases:
    r = c.post(f"/api/minitools/{path}", body, format="json")
    ok_flag = r.json().get("ok")
    if r.status_code == 200 and ok_flag:
        passed += 1
        print(f"  OK  {path} -> {str(r.json().get('data'))[:80]}")
    else:
        print(f"  FAIL {path} status={r.status_code} body={r.content[:200]}")

print(f"\n[tools] passed {passed}/{len(cases)}")

# 3. 错误输入应返回 400/422 而非 500
err_cases = [
    ("text/case-title/", {}),  # 缺 text -> 400
    ("num/bmi-calc/", {"height_cm": 175}),  # 缺 weight_kg -> 400
    ("encode/base64/", {"text": "!!!invalid!!!", "direction": "decode"}),  # 400
    ("validate/email/", {"email": "not-an-email"}),  # 200 ok=false
]
err_ok = 0
for path, body in err_cases:
    r = c.post(f"/api/minitools/{path}", body, format="json")
    if r.status_code in (200, 400, 422):
        err_ok += 1
        print(f"  ERR-OK {path} status={r.status_code} ok={r.json().get('ok')}")
    else:
        print(f"  ERR-BAD {path} status={r.status_code} body={r.content[:200]}")

print(f"\n[errors] handled {err_ok}/{len(err_cases)} (no 500)")
print("\n=== SMOKE TEST DONE ===")
