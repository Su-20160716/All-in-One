# -*- coding: utf-8 -*-
"""v7.1 新增 110 工具冒烟：catalog 断言 + 抽测每家族 + 错误输入兜底。"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

User = get_user_model()
u, _ = User.objects.get_or_create(username="smoke_test_user", defaults={"is_active": True})
c = APIClient()
c.force_authenticate(user=u)

# 1. catalog
r = c.get("/api/minitools/catalog/")
assert r.status_code == 200, r.content[:300]
data = r.json()["data"]
print(f"[catalog] subsystems={data['subsystem_count']} endpoints={data['endpoint_count']}")
assert data["subsystem_count"] == 19, data["subsystem_count"]
assert data["endpoint_count"] == 321, data["endpoint_count"]
assert len(data["endpoints"]) == 320, len(data["endpoints"])

# 2. 抽测：每个新家族至少 1-2 个
cases = [
    # finance
    ("finance/loan-equal-principal/", {"principal": 1000000, "annual_rate": 4.9, "months": 12}),
    ("finance/roi/", {"cost": 10000, "gain": 15000}),
    ("finance/annuity-fv/", {"pmt": 10000, "annual_rate": 5, "years": 10}),
    ("finance/depreciation-straight/", {"cost": 100000, "salvage": 10000, "life_years": 5}),
    ("finance/income-tax-cn/", {"income": 200000, "deduction": 36000}),
    ("finance/npv/", {"rate": 10, "cashflows": [-1000, 300, 400, 500, 600]}),
    ("finance/irr/", {"cashflows": [-1000, 300, 400, 500, 600]}),
    ("finance/credit-card-interest/", {"balance": 10000, "days": 30}),
    ("finance/rule-of-72/", {"annual_rate": 8}),
    ("finance/max-loan/", {"monthly_payment": 5000, "annual_rate": 4.9, "months": 360}),
    # health
    ("health/bmr/", {"weight_kg": 70, "height_cm": 175, "age": 30, "sex": "male"}),
    ("health/tdee/", {"weight_kg": 70, "height_cm": 175, "age": 30, "sex": "male", "activity": "light"}),
    ("health/body-fat/", {"sex": "male", "height_cm": 175, "waist_cm": 85, "neck_cm": 38}),
    ("health/ideal-weight/", {"height_cm": 175, "sex": "male"}),
    ("health/sleep-cycle/", {"wake_hour": 7, "wake_minute": 30}),
    ("health/heart-zone/", {"age": 30, "resting_hr": 70}),
    ("health/macro/", {"calories": 2000, "goal": "lose"}),
    ("health/bp-category/", {"systolic": 135, "diastolic": 90}),
    ("health/glucose-unit/", {"value": 100, "direction": "mgdl_to_mmol"}),
    ("health/whr/", {"waist_cm": 90, "hip_cm": 95, "sex": "male"}),
    # geo
    ("geo/dms-convert/", {"mode": "dms_to_decimal", "degrees": 39, "minutes": 54, "seconds": 30, "ref": "N"}),
    ("geo/cn-postcode/", {"code": "100000"}),
    ("geo/cn-area-code/", {"code": "010"}),
    ("geo/country-iso/", {"code": "CN"}),
    ("geo/cn-province/", {}),
    ("geo/altitude-pressure/", {"altitude_m": 1000}),
    ("geo/compass/", {"degree": 45}),
    ("geo/continent-countries/", {"continent": "亚洲"}),
    # security
    ("security/xor/", {"text": "hello", "key": "k", "mode": "encrypt"}),
    ("security/caesar-brute/", {"text": "Khoor Zruog"}),
    ("security/port-lookup/", {"port": 443}),
    ("security/cert-dn-parse/", {"dn": "CN=example.com,O=MyOrg,C=US"}),
    ("security/hash-identifier/", {"hash": "5d41402abc4b2a76b9719d911017c592"}),
    ("security/password-policy/", {"password": "Abc12345", "min_length": 8}),
    ("security/salt-gen/", {"length": 16, "encoding": "hex"}),
    ("security/basic-auth/", {"mode": "make", "username": "admin", "password": "pw"}),
    ("security/cookie-parse/", {"cookie": "session=abc; token=xyz"}),
    # algo
    ("algo/bubble-steps/", {"array": [3, 1, 2]}),
    ("algo/quick-steps/", {"array": [5, 2, 4, 1, 3]}),
    ("algo/binary-search-steps/", {"array": [1, 3, 5, 7, 9], "target": 5}),
    ("algo/euclid-steps/", {"a": 48, "b": 18}),
    ("algo/knapsack-dp/", {"weights": [2, 3, 4, 5], "values": [3, 4, 5, 6], "capacity": 8}),
    ("algo/coin-greedy/", {"amount": 63, "coins": [25, 10, 5, 1]}),
    ("algo/bfs/", {"start": "A"}),
    ("algo/dfs/", {"start": "A"}),
    ("algo/prim-mst/", {}),
    ("algo/topo-sort/", {}),
    ("algo/kmp/", {"text": "ababcabcab", "pattern": "abcab"}),
    ("algo/hanoi/", {"n": 3}),
    ("algo/josephus/", {"n": 10, "k": 3}),
    # science
    ("science/kinematics/", {"u": 0, "a": 9.8, "t": 2}),
    ("science/newton/", {"mass_kg": 10, "accel_m_s2": 5}),
    ("science/ohm/", {"voltage": 10, "current": 2}),
    ("science/normal-dist/", {"x": 0, "mu": 0, "sigma": 1}),
    ("science/poisson/", {"lambda": 4, "k": 2}),
    ("science/molarity/", {"mass_g": 5.85, "molar_mass": 58.5, "volume_ml": 500}),
    ("science/ph/", {"mode": "h_to_ph", "h_concentration": 0.0001}),
    ("science/gas-law/", {"pressure_pa": 101325, "volume_m3": 0.0224, "temperature_k": 273.15}),
    ("science/wave/", {"mode": "freq_to_wave", "freq_hz": 1e9}),
    ("science/half-life/", {"initial": 100, "half_life": 5, "time": 10}),
    ("science/sigfigs/", {"number": "0.001230"}),
    ("science/error-propagation/", {"values": [10, 5], "errors": [0.5, 0.2], "op": "add"}),
    ("science/reaction-yield/", {"actual": 8, "theoretical": 10}),
    # tx
    ("tx/lang-detect/", {"text": "你好世界"}),
    ("tx/syllable-en/", {"word": "beautiful"}),
    ("tx/acronym/", {"text": "As Soon As Possible"}),
    ("tx/palindrome-make/", {"word": "abc"}),
    ("tx/leetspeak/", {"text": "Hello World"}),
    ("tx/word-goal/", {"text": "hello world foo", "target": 10}),
    ("tx/hashtag-extract/", {"text": "这是 #测试 标签"}),
    ("tx/mention-extract/", {"text": "hi @bob and bob@example.com"}),
    ("tx/ordinal/", {"number": 21}),
    ("tx/sentence-split/", {"text": "Hello world. How are you? I'm fine."}),
    # biz
    ("biz/ean13/", {"code": "690123456789"}),
    ("biz/vat-split/", {"price": 1130, "rate": 13}),
    ("biz/margin/", {"cost": 80, "price": 100}),
    ("biz/bank-bin/", {"card": "6222021234567890"}),
    ("biz/mobile-segment/", {"phone": "13800138000"}),
    ("biz/express/", {"no": "SF1234567890"}),
    ("biz/commission/", {"amount": 10000, "rate": 5}),
    ("biz/gross-up/", {"net": 870, "rate": 13}),
    ("biz/unit-price/", {"total": 29.9, "quantity": 3}),
    ("biz/profit/", {"price": 100, "cost": 60, "expense": 10}),
    # fmt
    ("fmt/ini/", {"mode": "parse", "text": "[a]\nb=1\nc=2"}),
    ("fmt/toml/", {"mode": "parse", "text": "[server]\nhost = \"0.0.0.0\"\nport = 8080"}),
    ("fmt/mask/", {"text": "手机 13800138000，卡 6222021234567890"}),
    ("fmt/html-text/", {"html": "<h1>Hello</h1><p>World</p>"}),
    ("fmt/xml-format/", {"xml": "<root><a>1</a></root>"}),
    ("fmt/csv-escape/", {"mode": "escape", "field": "a,b,c"}),
    ("fmt/json-schema-infer/", {"obj": '{"name":"x","age":1}'}),
    ("fmt/csv-tsv/", {"mode": "csv_to_tsv", "text": "a,b,c\n1,2,3"}),
    # funx
    ("funx/acrostic/", {"heads": ["春", "风", "得", "意"]}),
    ("funx/num-homophone/", {"number": "5201314"}),
    ("funx/birthday-numerology/", {"date": "19900101"}),
    ("funx/wuge/", {"surname": "张", "given": "三"}),
    ("funx/dream/", {"keyword": "我梦见鱼在飞"}),
    ("funx/lucky-number/", {"date": "19900101"}),
    ("funx/mbti/", {"answers": [0, 1, 0, 1]}),
    ("funx/almanac/", {}),
]

passed = 0
failures = []
for path, body in cases:
    r = c.post(f"/api/minitools/{path}", body, format="json")
    j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
    if r.status_code == 200 and j.get("ok"):
        passed += 1
    else:
        failures.append((path, r.status_code, str(j)[:200]))

print(f"[tools] passed {passed}/{len(cases)}")
for f in failures:
    print("  FAIL", f)

# 3. 错误输入
err_cases = [
    ("finance/npv/", {"rate": 10}),  # 缺 cashflows
    ("health/bmr/", {"weight_kg": 70, "height_cm": 175}),  # 缺 age
    ("geo/compass/", {}),
    ("algo/binary-search-steps/", {"array": [1, 2]}),  # 缺 target
    ("science/ohm/", {"voltage": 10}),  # 只给一个量
    ("biz/ean13/", {"code": "123"}),  # 长度不对
]
err_ok = 0
for path, body in err_cases:
    r = c.post(f"/api/minitools/{path}", body, format="json")
    if r.status_code in (200, 400, 422):
        err_ok += 1
        print(f"  ERR-OK {path} status={r.status_code}")
    else:
        print(f"  ERR-BAD {path} status={r.status_code} body={r.content[:200]}")
print(f"[errors] handled {err_ok}/{len(err_cases)} (no 500)")
print("=== DONE ===")
