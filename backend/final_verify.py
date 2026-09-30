# -*- coding: utf-8 -*-
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
User = get_user_model()
u, _ = User.objects.get_or_create(username="final_verify", defaults={"is_active": True})
c = APIClient()
c.force_authenticate(user=u)

r = c.get("/api/minitools/catalog/")
d = r.json()["data"]
print("minitools: %d subsystems, %d endpoints, %d details" % (d["subsystem_count"], d["endpoint_count"], len(d["endpoints"])))

tests = [
    ("finance/npv/", {"cashflows": "-1000,300,400,500", "rate": 0.1}),
    ("health/bmr/", {"gender": "male", "weight_kg": 70, "height_cm": 175, "age": 30}),
    ("algo/hanoi/", {"n": 3}),
    ("science/ph/", {"h_plus": 0.001}),
    ("biz/ean13/", {"code": "4006381333931"}),
]
for path, body in tests:
    r = c.post("/api/minitools/" + path, body, format="json")
    print("  %s: status=%d ok=%s" % (path, r.status_code, r.json().get("ok")))

r = c.get("/api/code/catalog/")
if r.status_code == 200:
    print("code catalog: %d endpoints" % r.json()["data"]["endpoint_count"])
else:
    print("code catalog status: %d" % r.status_code)

print("ALL VERIFICATION DONE")
