"""flags 应用独立冒烟脚本：进程内走 DRF 路由栈跑一遍功能开关全生命周期。

用法（必须显式执行，不参与 CI，也不会被单元测试收集）：

    venv/Scripts/python.exe flags_smoke_test.py

可选环境变量：

    FLAGS_SMOKE_TOKEN    Bearer 令牌（与 SESSION 二选一）
    FLAGS_SMOKE_SESSION  会话 Cookie，形如 sessionid=xxx
    FLAGS_SMOKE_KEEP     1 表示保留创建出来的开关，默认归档收尾

传输层用 smoke_inproc（django.setup + APIClient），不需要先起 8000 端口；
未给令牌时自动登录 admin/admin123，失败再回退注册新账号。
覆盖主链路：项目/环境 → 开关 → 定向/变体/细分/灰度 → 确定性评估 →
实验入组与曝光 → 结果统计 → 依赖/护栏 → 统计与审计。

任何一步不符合预期都会记录失败并以非零码退出，便于发布前手工确认
「模型 / 服务 / 路由」三件事都通了。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from smoke_inproc import init, request_json

KEEP = os.environ.get("FLAGS_SMOKE_KEEP", "") == "1"

PREFIX = "/api/flags/"

CLIENT, TOKEN = init("flags", token_env="FLAGS_SMOKE_TOKEN",
                     session_env="FLAGS_SMOKE_SESSION")

_failures: list[str] = []
_created: dict[str, int] = {}


def call(method: str, path: str, payload=None, expect=(200,), params=None):
    """发一次进程内请求，返回 (状态码, 完整响应体)；data 在 body["data"] 里。"""
    url = f"{PREFIX}{path.lstrip('/')}"
    status, parsed = request_json(CLIENT, method, url, payload=payload, params=params)
    if status not in expect:
        raise AssertionError(f"{method} {path} -> {status}（期望 {expect}）：{parsed}")
    return status, parsed


def data_of(request_result):
    """取接口成功响应里的 data；失败响应没有 data 时返回空字典。"""
    _status, body = request_result
    if not isinstance(body, dict):
        return {}
    if body.get("ok") is False:
        return {}
    return body.get("data") or {}


def expect_error(method: str, path: str, payload=None, status=400) -> None:
    """断言一次请求被拒绝（参数校验/权限），用于负路径覆盖。"""
    _status, body = call(method, path, payload, expect=(status,))
    check(f"负路径 {method} {path} -> {status}", body.get("ok") is False,
          json.dumps(body, ensure_ascii=False)[:200])


def check(name: str, condition: bool, detail: str = "") -> None:
    """记录一步结果；失败不中断，便于一次跑出全部问题。"""
    if condition:
        print(f"[ok]   {name}")
        return
    _failures.append(f"{name} {detail}".strip())
    print(f"[FAIL] {name} {detail}".strip())


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def page_contract(name: str, rows) -> None:
    """所有列表必须统一 items/count/page/page_size 四个键。"""
    keys = set(rows.keys()) if isinstance(rows, dict) else set()
    check(f"{name} 分页契约", keys == {"items", "count", "page", "page_size"},
          f"实际 {sorted(keys)}")
    check(f"{name} items 是数组", isinstance(rows.get("items"), list))


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    section("目录与鉴权")
    catalog = data_of(call("GET", ""))
    check("目录含接口清单", len(catalog.get("endpoints") or []) >= 52)
    check("目录声明 14 个操作符", len(catalog.get("operators") or []) == 14)
    check("目录分页上限 200",
          (catalog.get("pagination") or {}).get("page_size_max") == 200)
    check("目录含开关类型枚举", "flag_types" in (catalog.get("enums") or {}))
    anon_status, _anon = request_json(CLIENT, "GET", PREFIX, auth=False)
    check("匿名访问被拒绝", anon_status in (401, 403), f"实际 {anon_status}")

    section("项目与环境")
    project = data_of(call("POST", "projects/", {
        "key": f"smoke{stamp}",
        "name": f"冒烟项目 {stamp}",
        "description": "flags smoke test",
        "members": [],
    }))
    project_id = project["id"]
    _created["project"] = project_id
    check("项目默认带开发环境", project.get("environment_count") == 1)
    project_detail = data_of(call("GET", f"projects/{project_id}/"))
    environments = project_detail.get("environments") or []
    check("项目详情返回环境列表", len(environments) == 1)
    dev_env = environments[0]
    check("默认环境是 dev", dev_env.get("key") == "dev")

    prod_env = data_of(call("POST", "environments/", {
        "project_id": project_id,
        "key": "prod",
        "name": "生产",
        "env_type": "production",
    }))
    prod_env_id = prod_env["id"]
    check("生产环境标记正确", prod_env.get("is_production") is True)
    toggled = data_of(call("POST", "environments/toggle/", {
        "environment_id": prod_env_id, "enabled": False}))
    check("环境可停用", toggled.get("enabled") is False)
    data_of(call("POST", "environments/toggle/", {
        "environment_id": prod_env_id, "enabled": True}))

    section("开关创建与版本")
    flag = data_of(call("POST", "flags/", {
        "project_id": project_id,
        "environment_id": dev_env["id"],
        "key": "smoke_checkout",
        "name": "冒烟结账开关",
        "flag_type": "boolean",
        "labels": ["smoke", "checkout"],
        "assignee": "冒烟负责人",
    }))
    flag_id = flag["id"]
    _created["flag"] = flag_id
    check("开关默认 active", flag.get("status") == "active")
    check("开关标签规范化", flag.get("labels") == ["smoke", "checkout"])

    published = data_of(call("POST", "flags/publish/", {
        "flag_id": flag_id, "change_note": "冒烟发布"}))
    check("发布生成版本", published.get("version") == 1)
    doc = data_of(call("POST", "flags/update/", {
        "flag_id": flag_id, "description": "冒烟修改"}))
    check("更新描述", doc.get("description") == "冒烟修改")
    data_of(call("POST", "flags/publish/", {
        "flag_id": flag_id, "change_note": "冒烟发布 2"}))
    versions = data_of(call("GET", f"flags/{flag_id}/versions/"))
    check("版本列表可查", versions.get("count") == 2)
    rolled = data_of(call("POST", "flags/rollback/", {
        "flag_id": flag_id, "version": 2}))
    check("回滚到版本 2", rolled.get("rolled_back_to") == 2)
    check("回滚恢复描述", (rolled.get("flag") or {}).get("description") == "冒烟修改")

    section("确定性评估")
    first = data_of(call("POST", "evaluate/", {
        "flag_id": flag_id,
        "user_key": "smoke-user",
        "context": {"user": {"country": "US", "plan": "pro"}},
    }))
    second = data_of(call("POST", "evaluate/", {
        "flag_id": flag_id,
        "user_key": "smoke-user",
        "context": {"user": {"country": "US", "plan": "pro"}},
    }))
    check("未配置策略返回 default", first.get("reason") == "default")
    check("布尔开关默认关闭", first.get("enabled") is False)
    check("同用户同上下文结果稳定", first == second)
    check("评估包含分桶", isinstance(first.get("bucket"), int))

    batch = data_of(call("POST", "evaluate/batch/", {
        "flag_id": flag_id, "user_keys": ["u1", "u2", "u3"]}))
    check("批量评估返回 3 条", len(batch.get("items") or []) == 3)
    boolean = data_of(call("POST", "evaluate/bool/", {
        "flag_ids": [flag_id], "user_key": "u1"}))
    check("布尔评估按开关键返回",
          (boolean.get("flags") or {}).get("smoke_checkout") is False)
    explained = data_of(call("POST", "evaluate/explain/", {
        "flag_id": flag_id, "user_key": "u1",
        "context": {"user": {"country": "US"}}}))
    check("解释接口含步骤", isinstance(explained.get("steps"), list))
    history = data_of(call("GET", f"flags/{flag_id}/evaluations/"))
    page_contract("评估历史", history)
    check("评估历史已落库", history.get("count", 0) >= 3)

    section("变体与定向")
    variant = data_of(call("POST", "variants/", {
        "flag_id": flag_id, "key": "beta", "name": "Beta", "weight": 100,
        "payload": {"color": "green"}}))
    check("变体创建成功", variant.get("key") == "beta")
    weighted = data_of(call("POST", "variants/weight/", {
        "flag_id": flag_id, "weights": [{"key": "beta", "weight": 100}]}))
    check("权重设置成功", len(weighted.get("updated") or []) == 1)

    rule = data_of(call("POST", "targeting-rules/", {
        "flag_id": flag_id,
        "conditions": [{"field": "user.country", "operator": "in",
                        "value": ["US", "CA"]}],
        "variant_key": "true",
        "priority": 10,
    }))
    targeted = data_of(call("POST", "evaluate/", {
        "flag_id": flag_id, "user_key": "smoke-us",
        "context": {"user": {"country": "US"}}}))
    check("定向命中原因", str(targeted.get("reason", "")).startswith("targeting:"))
    check("定向命中开启", targeted.get("enabled") is True)
    other = data_of(call("POST", "evaluate/", {
        "flag_id": flag_id, "user_key": "smoke-jp",
        "context": {"user": {"country": "JP"}}}))
    check("非目标用户不命中定向", other.get("reason") == "default")
    disabled = data_of(call("POST", "targeting-rules/toggle/", {
        "rule_id": rule["id"], "enabled": False}))
    check("定向规则可停用", disabled.get("enabled") is False)
    data_of(call("POST", "targeting-rules/toggle/", {
        "rule_id": rule["id"], "enabled": True}))
    reordered = data_of(call("POST", "targeting-rules/reorder/", {
        "flag_id": flag_id, "ids": [rule["id"]]}))
    check("定向规则可重排", reordered.get("ids") == [rule["id"]])
    expect_error("POST", "targeting-rules/", {
        "flag_id": flag_id,
        "conditions": [{"field": "user.country", "operator": "in", "value": "US"}],
        "variant_key": "true",
    })

    section("细分")
    segment = data_of(call("POST", "segments/", {
        "project_id": project_id,
        "name": "冒烟北美用户",
        "rules": [{"field": "user.country", "operator": "in", "value": ["US", "CA"]}],
        "rule_match": "and",
    }))
    segment_id = segment["id"]
    check("细分创建成功", segment.get("rule_match") == "and")
    segment_rule = data_of(call("POST", "segments/rules/", {
        "segment_id": segment_id, "field": "user.email",
        "operator": "ends_with", "value": "@example.com"}))
    check("细分结构化规则写入", segment_rule.get("operator") == "ends_with")
    preview = data_of(call("POST", "segments/preview/", {
        "segment_id": segment_id,
        "contexts": [
            {"user_key": "a", "user": {"country": "US", "email": "a@example.com"}},
            {"user_key": "b", "user": {"country": "CN", "email": "b@example.com"}},
            {"user_key": "c", "user": {"country": "CA", "email": "c@other.com"}},
        ],
    }))
    check("细分预览命中 1 人", preview.get("hits") == 1, json.dumps(preview)[:200])

    section("灰度放量")
    rollout = data_of(call("POST", "rollouts/", {
        "flag_id": flag_id, "percentage": 100, "segment_id": segment_id}))
    rollout_id = rollout["id"]
    check("灰度创建 running", rollout.get("status") == "running")
    hit = data_of(call("POST", "evaluate/", {
        "flag_id": flag_id, "user_key": "smoke-rollout",
        "context": {"user": {"country": "US", "email": "smoke@example.com"}}}))
    check("灰度命中细分原因", str(hit.get("reason", "")).startswith("segment:"))
    check("灰度放量开关打开", hit.get("enabled") is True)
    advanced = data_of(call("POST", "rollouts/advance/", {
        "rollout_id": rollout_id, "target": 100}))
    check("灰度推进到 100%", advanced.get("percentage") == 100)
    check("灰度满分自动完成", advanced.get("status") == "completed")
    paused = data_of(call("POST", "rollouts/toggle/", {
        "rollout_id": rollout_id, "status": "paused"}))
    check("灰度可暂停", paused.get("status") == "paused")
    paused_eval = data_of(call("POST", "evaluate/", {
        "flag_id": flag_id, "user_key": "smoke-rollout",
        "context": {"user": {"country": "US", "email": "smoke@example.com"}}}))
    check("暂停后回落到 rollout:paused", paused_eval.get("reason") == "rollout:paused")
    data_of(call("POST", "rollouts/toggle/", {
        "rollout_id": rollout_id, "status": "running"}))

    section("实验")
    # 实验分组复用开关自身变体；主开关已挂 beta 变体，这里另建一个
    # 无变体的布尔开关，让实验走默认 control/treatment 均分分组。
    exp_flag = data_of(call("POST", "flags/", {
        "project_id": project_id, "environment_id": dev_env["id"],
        "key": "smoke_experiment", "name": "冒烟实验开关",
        "flag_type": "boolean"}))
    exp_flag_id = exp_flag["id"]
    experiment = data_of(call("POST", "experiments/", {
        "flag_id": exp_flag_id,
        "name": f"冒烟实验 {stamp}",
        "hypothesis": "新按钮提高转化",
        "min_sample_size": 2,
        "primary_metric": "conversion",
    }))
    experiment_id = experiment["id"]
    check("实验默认草稿", experiment.get("status") == "draft")
    started = data_of(call("POST", "experiments/start/", {
        "experiment_id": experiment_id}))
    check("实验启动", started.get("status") == "running")
    exp_first = data_of(call("POST", "evaluate/", {
        "flag_id": exp_flag_id, "user_key": "smoke-exp"}))
    exp_second = data_of(call("POST", "evaluate/", {
        "flag_id": exp_flag_id, "user_key": "smoke-exp"}))
    check("实验命中原因", str(exp_first.get("reason", "")).startswith("experiment:"))
    check("实验入组稳定", exp_first.get("variant") == exp_second.get("variant"))

    for user_key, variant_key, converted in (
        ("c1", "control", True), ("c2", "control", False),
        ("t1", "treatment", True), ("t2", "treatment", True),
    ):
        exposure = data_of(call("POST", "experiments/exposures/", {
            "experiment_id": experiment_id,
            "user_key": user_key,
            "variant_key": variant_key,
            "context": {"converted": converted,
                        "value": 10 if converted else 0},
        }))
        check(f"曝光写入 {user_key}", (exposure.get("exposure") or {}).get("id") is not None)
    again = data_of(call("POST", "experiments/exposures/", {
        "experiment_id": experiment_id, "user_key": "c1",
        "variant_key": "control", "context": {"converted": True}}))
    check("曝光幂等", again.get("idempotent") is True)

    results = data_of(call("GET", f"experiments/{experiment_id}/results/"))
    check("实验结果含 4 次曝光", results.get("total_exposures") == 4)
    check("实验结果样本就绪", results.get("sample_ready") is True)
    check("实验结果给出胜出变体", results.get("winner") == "treatment")
    progress = data_of(call("GET", f"experiments/{experiment_id}/progress/"))
    check("实验进度可查", progress.get("total_exposures") == 4)
    exposure_stats = data_of(call("GET", f"experiments/{experiment_id}/exposures/"))
    check("曝光统计可查", exposure_stats.get("total") == 4)

    metric = data_of(call("POST", "experiment-metrics/", {
        "experiment_id": experiment_id, "name": "revenue",
        "metric_type": "revenue", "unit": "CNY"}))
    check("新增实验指标", metric.get("metric_type") == "revenue")
    metric = data_of(call("POST", "experiment-metrics/update/", {
        "metric_id": metric["id"], "unit": "元"}))
    check("更新实验指标", metric.get("unit") == "元")
    expect_error("POST", "experiment-metrics/", {
        "experiment_id": experiment_id, "name": "revenue"})
    data_of(call("POST", "experiment-metrics/delete/", {"metric_id": metric["id"]}))
    concluded = data_of(call("POST", "experiments/conclude/", {
        "experiment_id": experiment_id}))
    check("实验结束", concluded.get("status") == "concluded")

    section("受众与依赖")
    audience = data_of(call("POST", "audiences/", {
        "project_id": project_id,
        "name": "冒烟高价值受众",
        "rules": [{"field": "custom.level", "operator": "gte", "value": 3}],
        "rule_logic": "and",
    }))
    check("受众创建成功", audience.get("name") == "冒烟高价值受众")
    audience_preview = data_of(call("POST", "audiences/preview/", {
        "audience_id": audience["id"],
        "contexts": [{"user_key": "a", "custom": {"level": 5}},
                     {"user_key": "b", "custom": {"level": 1}}],
    }))
    check("受众预览命中 1 人", audience_preview.get("hits") == 1)

    upstream = data_of(call("POST", "flags/", {
        "project_id": project_id, "environment_id": dev_env["id"],
        "key": "smoke_upstream", "name": "上游开关"}))
    downstream = data_of(call("POST", "flags/", {
        "project_id": project_id, "environment_id": dev_env["id"],
        "key": "smoke_downstream", "name": "下游开关"}))
    dep = data_of(call("POST", "dependencies/", {
        "flag_id": downstream["id"], "depends_on_id": upstream["id"],
        "relation": "requires"}))
    check("依赖创建成功", dep.get("relation") == "requires")
    blocked = data_of(call("POST", "evaluate/", {
        "flag_id": downstream["id"], "user_key": "dep-user"}))
    check("上游未开时下游被依赖拦截",
          blocked.get("reason") == "dependency:smoke_upstream")
    graph = data_of(call("GET", "dependencies/graph/", params={"project_id": project_id}))
    check("依赖图含全部项目开关", graph.get("node_count", 0) >= 3)
    check("依赖图含 1 条边", graph.get("edge_count") == 1)
    cycles = data_of(call("GET", "dependencies/check-cycles/",
                          params={"project_id": project_id}))
    check("依赖无环", cycles.get("has_cycle") is False)
    expect_error("POST", "dependencies/", {
        "flag_id": upstream["id"], "depends_on_id": downstream["id"]})

    section("护栏")
    guardrail = data_of(call("POST", "guardrails/", {
        "flag_id": flag_id, "metric": "error_rate", "threshold": 0.5,
        "comparator": "gte", "action": "notify"}))
    below = data_of(call("POST", "guardrails/check/", {
        "flag_id": flag_id, "readings": {"error_rate": 0.1}}))
    check("读数低于阈值不触发", below.get("count") == 0)
    triggered = data_of(call("POST", "guardrails/check/", {
        "flag_id": flag_id,
        "readings": [{"metric": "error_rate", "value": 0.9}]}))
    check("读数超阈值触发", triggered.get("count") == 1,
          json.dumps(triggered, ensure_ascii=False)[:200])
    check("护栏记录触发次数", triggered.get("triggered")[0].get("guardrail_id")
          == guardrail["id"])

    section("统计与审计")
    overview = data_of(call("GET", "stats/overview/", params={"project_id": project_id}))
    check("总览含开关数", overview.get("flags", 0) >= 3)
    top = data_of(call("GET", "stats/top-flags/", params={"project_id": project_id}))
    check("Top 开关返回列表", isinstance(top.get("items"), list))
    distribution = data_of(call("GET", "stats/variant-distribution/",
                                params={"flag_id": flag_id}))
    variants = {row.get("variant") for row in (distribution.get("items") or [])}
    check("变体分布含布尔变体", bool(variants & {"true", "false"}),
          json.dumps(sorted(variants), ensure_ascii=False))
    trend = data_of(call("GET", "stats/evaluation-trend/",
                         params={"project_id": project_id, "days": 7}))
    check("趋势返回序列", isinstance(trend.get("items"), list))
    board = data_of(call("GET", "stats/experiment-board/",
                         params={"project_id": project_id}))
    check("实验看板可查", "concluded" in (board.get("status") or {}))
    audit = data_of(call("GET", "audit-events/", params={"project_id": project_id}))
    page_contract("审计事件", audit)
    check("审计事件已记录", audit.get("count", 0) >= 5)
    flag_stats = data_of(call("GET", f"flags/{flag_id}/stats/"))
    check("开关统计可查", "evaluations" in flag_stats)
    project_stats = data_of(call("GET", f"projects/{project_id}/stats/"))
    check("项目统计可查", project_stats.get("flags", 0) >= 3)

    section("收尾")
    if KEEP:
        print(f"保留数据：project={project_id} flag={flag_id}")
    else:
        archived = data_of(call("POST", "flags/archive/", {"flag_id": flag_id}))
        check("开关归档", archived.get("status") == "archived")
        archived_eval = data_of(call("POST", "evaluate/", {
            "flag_id": flag_id, "user_key": "smoke-after-archive"}))
        check("归档后评估返回 flag-archived",
              archived_eval.get("reason") == "flag-archived")
        data_of(call("POST", "projects/archive/", {"project_id": project_id}))
        check("项目归档成功", True)

    print()
    if _failures:
        print(f"失败 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("全部冒烟检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
