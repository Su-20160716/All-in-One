"""临时探针 v3：网络体检 —— 基线连通 / DeepSeek 对比 / NIM 直连 / 本地代理端口（跑完即删）"""
import os
import time
import socket
import urllib.request
import urllib.error


def try_url(name, url, timeout=8):
    req = urllib.request.Request(url, method="GET")
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            print(f"[{name}] HTTP {r.status}，耗时 {time.time() - t:.1f}s —— 通")
    except urllib.error.HTTPError as e:
        print(f"[{name}] HTTP {e.code}（有响应就说明通），耗时 {time.time() - t:.1f}s")
    except Exception as e:
        print(f"[{name}] 失败，耗时 {time.time() - t:.1f}s —— {type(e).__name__}: {e}")


proxies = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
print("系统代理环境变量:", proxies if proxies else "无")

try_url("百度（基线）        ", "https://www.baidu.com", 6)
try_url("DeepSeek 官方（对比）", "https://api.deepseek.com/v1/models", 8)
try_url("NVIDIA NIM（直连）  ", "https://integrate.api.nvidia.com/v1/models", 10)

print()
for port in (7890, 10809, 1080, 8888, 33210):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect(("127.0.0.1", port))
        print(f"本地端口 {port}: 有服务在监听（可能是代理）")
    except Exception:
        print(f"本地端口 {port}: 无")
    finally:
        s.close()
