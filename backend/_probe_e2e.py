"""临时探针 v8：端到端验证 —— Django settings → assistant.llm.chat() → NIM（跑完即删）"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

import time
from django.conf import settings
from assistant import llm

print("LLM_MODEL       =", settings.LLM_MODEL)
print("LLM_EXTRA_BODY  =", settings.LLM_EXTRA_BODY)
print("is_configured   =", llm.is_configured())

t = time.time()
res = llm.chat([{"role": "user", "content": "只回复两个字：你好"}])
dt = time.time() - t
print(f"chat() 耗时 {dt:.1f}s | ok={res['ok']} | code={res['code']} | provider={res['provider']}")
print("content:", (res["content"] or "(空)")[:60])
if not res["ok"]:
    print("error:", res["error"])
