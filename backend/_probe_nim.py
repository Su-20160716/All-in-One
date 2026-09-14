"""临时探针 v7：nemotron-3-super 开关思考模式的输出对比（跑完即删）"""
import time
import json
import os
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

key = os.environ.get("LLM_API_KEY", "")
base = os.environ.get("LLM_BASE_URL", "").rstrip("/")

for tag, extra in [
    ("默认（不传 thinking）", None),
    ("thinking=False       ", {"chat_template_kwargs": {"thinking": False}}),
]:
    payload = {
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "messages": [{"role": "user", "content": "只回复两个字：你好"}],
        "max_tokens": 512,
        "temperature": 0,
    }
    if extra:
        payload.update(extra)
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8", errors="ignore"))
        msg = body["choices"][0]["message"]
        c = (msg.get("content") or "").strip()[:60]
        reason = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()[:40]
        print(f"[{tag}] 200，耗时 {time.time() - t:.1f}s")
        print(f"    content={c!r}")
        if reason:
            print(f"    reasoning_content={reason!r}...")
    except urllib.error.HTTPError as e:
        print(f"[{tag}] HTTP {e.code}，耗时 {time.time() - t:.1f}s，"
              f"{e.read().decode('utf-8', errors='ignore')[:150]}")
    except Exception as e:
        print(f"[{tag}] 失败，耗时 {time.time() - t:.1f}s —— {type(e).__name__}: {e}")
