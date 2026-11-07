"""rules 应用独立冒烟脚本：进程内走 DRF 路由栈跑一遍主链路。

用法（必须显式执行，不参与 CI，也不会被单元测试收集）：

    venv/Scripts/python.exe rules_smoke_test.py

可选环境变量：

    RULES_SMOKE_TOKEN  Bearer 令牌（与 RULES_SMOKE_SESSION 二选一）
    RULES_SMOKE_SESSION 会话 Cookie，形如 sessionid=xxx
    RULES_SMOKE_KEEP   1 表示保留创建出来的规则集，默认清理

传输层用 smoke_inproc（django.setup + APIClient），不需要先起 8000 端口；
未给令牌时自动登录 admin/admin123，失败再回退注册新账号。
任何一步不符合预期都会抛 AssertionError 并以非零码退出，
方便在发布前手工确认「模型 / 引擎 / 路由」三件事都通。
"""

from __future__ import annotations

import json
import os
import sys

from smoke_inproc import init, request_json

KEEP = os.environ.get("RULES_SMOKE_KEEP", "") == "1"

PREFIX = "/api/rules/"

CLIENT, TOKEN = init("rules", token_env="RULES_SMOKE_TOKEN",
                     session_env="RULES_SMOKE_SESSION")

_failures: list[str] = []
_created: dict[str, int] = {}


def call(method: str, path: str, payload=None, expect=(200,), params=None):
    """发一次进程内请求，返回 (状态码, 解析后的 JSON)，断言状态码在 expect 内。"""
    url = f"{PREFIX}{path.lstrip('/')}"
    status, data = request_json(CLIENT, method, url, payload=payload, params=params)
    if status not in expect:
        raise AssertionError(f"{method} {path} -> {status}（期望 {expect}）：{data}")
    return status, data


def check(name: str, condition: bool, detail: str = "") -> None:
    """记录一步结果；失败不中断，便于一次跑出全部问题。"""
    if condition:
        print(f"[ok]   {name}")
        return
    _failures.append(f"{name} {detail}".strip())
    print(f"[FAIL] {name} {detail}".strip())


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    section("目录与鉴权")
    _, catalog = call("GET", "")
    paths = {item["path"] for item in catalog.get("endpoints", [])}
    check("目录返回接口清单", len(paths) >= 50, f"实际 {len(paths)} 条")
    check("目录包含 rulesets/", "rulesets/" in paths)
    check("限制声明一致", catalog.get("limits", {}).get("page_size") == 200)
    status, _ = request_json(CLIENT, "GET", PREFIX, auth=False)
    check("匿名访问被拒绝", status in (401, 403), f"实际 {status}")

    section("规则集与规则")
    _, created = call("POST", "rulesets/", {
        "code": "smoke_ruleset",
        "name": "冒烟规则集",
        "description": "rules_smoke_test.py 生成，可安全删除",
    })
    ruleset_id = created["id"]
    _created["ruleset"] = ruleset_id
    check("创建规则集", created.get("status") == "draft")

    _, rule = call("POST", "rules/", {
        "ruleset_id": ruleset_id,
        "name": "大额通过",
        "priority": 10,
        "condition": "facts.amount >= 100 and facts.channel != 'blocked'",
        "actions": [{"type": "score", "params": {"field": "score", "delta": 20}}],
    })
    check("创建规则", rule["condition"].startswith("facts.amount"))

    status, _ = call("POST", "rules/", {
        "ruleset_id": ruleset_id, "name": "坏条件",
        "condition": "facts.amount >= ",
    }, expect=(400,))
    check("非法表达式返回 400", status == 400)

    status, _ = call("POST", "rules/", {
        "ruleset_id": ruleset_id, "name": "下划线字段",
        "condition": "facts.__proto__ == 1",
    }, expect=(400,))
    check("下划线路径被拦截", status == 400)

    section("发布与评估")
    _, published = call("POST", f"rulesets/{ruleset_id}/publish/", {"note": "冒烟"})
    check("发布生成版本", published.get("version_no", 0) >= 1)

    _, result = call("POST", "evaluate/", {
        "ruleset_id": ruleset_id,
        "facts": {"amount": 200, "channel": "web"},
    })
    check("命中规则", result.get("matched") is True, json.dumps(result)[:200])
    check("返回执行轨迹", bool(result.get("trace")))
    facts_after = (result.get("decision") or {}).get("facts_after") or {}
    check("动作分数生效", facts_after.get("score") == 20, json.dumps(facts_after)[:200])

    _, missed = call("POST", "evaluate/", {
        "ruleset_id": ruleset_id,
        "facts": {"amount": 10, "channel": "web"},
    })
    check("小额不命中", missed.get("matched") is False)
    check("未命中也有轨迹", bool(missed.get("trace")))

    section("决策表")
    _, table = call("POST", "tables/", {
        "ruleset_id": ruleset_id,
        "name": "金额分档",
        "inputs": [{"name": "amount", "field": "facts.amount"}],
        "outputs": [{"name": "level", "field": "level"}],
    })
    _, row = call("POST", f"tables/{table['id']}/rows/", {
        "conditions": {"amount": {"min": 100}},
        "outputs": {"level": "high"},
        "priority": 1,
    })
    check("新增决策行", row["id"] > 0)
    _, decided = call("POST", f"tables/{table['id']}/evaluate/", {
        "facts": {"amount": 150},
    })
    check("决策表命中最优行", (decided.get("outputs") or {}).get("level") == "high")

    section("测试用例与模拟")
    _, case = call("POST", "testcases/", {
        "ruleset_id": ruleset_id,
        "name": "大额命中",
        "facts": {"amount": 300, "channel": "web"},
        "expected": {"matched": True},
    })
    _, run = call("POST", f"testcases/{case['id']}/run/", {})
    check("用例执行通过", run.get("passed") is True)
    _, all_run = call("POST", "testcases/run-all/", {"ruleset_id": ruleset_id})
    check("批量执行汇总", all_run.get("total", 0) >= 1)

    _, simulated = call("POST", "simulations/", {
        "ruleset_id": ruleset_id,
        "name": "调参模拟",
        "facts": [{"amount": 50, "channel": "web"},
                  {"amount": 500, "channel": "web"}],
    })
    check("模拟返回样本汇总",
          (simulated.get("summary") or {}).get("total") == 2,
          json.dumps(simulated.get("summary") or {})[:200])

    section("冲突检测")
    call("POST", "rules/", {
        "ruleset_id": ruleset_id, "name": "重复规则", "priority": 20,
        "condition": "facts.amount >= 100 and facts.channel != 'blocked'",
    })
    _, conflicts = call("POST", "conflicts/detect/", {"ruleset_id": ruleset_id})
    check("检测出重复冲突", len(conflicts.get("conflicts", [])) >= 1)

    section("调度")
    _, schedule = call("POST", "schedules/", {
        "ruleset_id": ruleset_id,
        "name": "每十分钟",
        "cron": "*/10 * * * *",
        "facts": {"amount": 500, "channel": "web"},
    })
    check("创建调度并算出下次执行", bool(schedule.get("next_run_at")))
    _, run_now = call("POST", f"schedules/{schedule['id']}/run/", {})
    check("手动执行调度", (run_now.get("result") or {}).get("matched") is True)
    status, _ = call("POST", "schedules/", {
        "ruleset_id": ruleset_id, "cron": "60 * * * *",
    }, expect=(400,))
    check("非法 cron 返回 400", status == 400)

    section("统计与日志")
    _, overview = call("GET", "stats/overview/", params={"ruleset_id": ruleset_id})
    check("统计有评估次数", overview.get("evaluations", 0) >= 2)
    _, logs = call("GET", "logs/", params={"ruleset_id": ruleset_id, "page_size": 5})
    check("日志分页结构", set(logs) >= {"items", "count", "page", "page_size"})
    _, evaluations = call("GET", "evaluations/", params={"page_size": 500})
    check("分页大小封顶", evaluations.get("page_size") == 200)

    section("清理")
    if KEEP:
        print("保留规则集:", ruleset_id)
    else:
        call("POST", f"rulesets/{ruleset_id}/archive/", {}, expect=(200,))
        print("已归档规则集:", ruleset_id)

    if _failures:
        print(f"\n冒烟失败 {len(_failures)} 项：")
        for item in _failures:
            print(" -", item)
        return 1
    print("\n全部冒烟检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
