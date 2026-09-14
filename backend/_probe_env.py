"""临时探针：验证 backend/.env 是否被 settings 正确加载（跑完即删）"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings
from assistant import llm

print("LLM_BASE_URL   =", settings.LLM_BASE_URL)
print("LLM_MODEL      =", settings.LLM_MODEL)
print("LLM_TIMEOUT    =", settings.LLM_TIMEOUT)
print("LLM_MAX_TOKENS =", settings.LLM_MAX_TOKENS)
print("LLM_API_KEY    =", repr(settings.LLM_API_KEY))
print("is_configured  =", llm.is_configured())
st = llm.status()
print("status         =", st["provider"], "|", st["mode_label"], "|", st["model"])
