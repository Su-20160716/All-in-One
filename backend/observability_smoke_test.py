# -*- coding: utf-8 -*-
"""observability 应用独立冒烟脚本：进程内跑一遍「服务→指标→SLO→告警→事故→值班」。

用法（必须显式执行，不参与 CI，也不会被单元测试收集）：

    venv/Scripts/python.exe observability_smoke_test.py

与 flags_smoke_test.py 等脚本的差别：本脚本不要求后端已经启动，而是直接
``django.setup()`` + DRF ``APIClient`` 在进程内调用视图，因此会写入
**当前 settings 指向的数据库**（开发库）。正式回归请让主流程统一执行，
不要把它挂到单元测试发现规则里。

覆盖主链路：
1. 目录契约（能力清单/接口数）
2. 服务 → 指标定义 → 指标上报（批量 + 单点）→ 查询/分位/最新值/标签
3. SLO：可用性计算、窗口幂等、错误预算、多窗口燃烧率、预算预测、延迟 SLO
4. 告警：规则 → 求值触发 → 事件确认 → 静默
5. 事故：登记 → 时间线 → 确认/缓解/解决/复盘 → 终态保护 → 更新记录
6. 值班：排班推导、当前/未来班次、换班、升级检查
7. 健康检查：执行 → 健康分 → 趋势
8. 统计总览与行级权限隔离

所有账号/服务/团队名都带时间戳后缀，重复执行不会互相干扰。
任何一项不符合预期都会累计失败并以非零码退出。
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

BASE = "/api/observability/"
AUTH = "/api/auth/"

STAMP = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
# 与用户名刻意不同，避免撞上「口令与账号过于相似」的密码校验器
PASSWORD = "LimeFalcon#42!Q"

_failures: list[str] = []
_passed = 0


# ---------------------------------------------------------------------------
# 断言与请求 helper
# ---------------------------------------------------------------------------


def check(condition, message):
    """记录一项断言；失败只累计，不中断后续步骤。"""
    global _passed
    if condition:
        _passed += 1
        print(f"  [ok] {message}")
    else:
        _failures.append(message)
        print(f"  [FAIL] {message}")


def api(client, method, path, payload=None, params=None, expect=200):
    """发一次请求：200 返回 data，非 200 返回完整响应体（用于断言错误提示）。"""
    if method.upper() == "GET":
        response = client.get(BASE + path, params or {})
    else:
        response = client.post(BASE + path, payload if payload is not None else {},
                               format="json")
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 —— 非 JSON 响应也要给出可读信息
        body = {"raw": response.content[:300].decode("utf-8", "replace")}
    if response.status_code != expect:
        raise RuntimeError(
            f"{method.upper()} {path} -> {response.status_code}（期望 {expect}）：{body}")
    if expect == 200:
        if not body.get("ok"):
            raise RuntimeError(f"{method.upper()} {path} 返回 ok=false：{body}")
        return body.get("data")
    return body


def error_of(client, method, path, payload=None, params=None, status=400):
    """发一次预期失败的请求，返回错误文案。"""
    body = api(client, method, path, payload=payload, params=params, expect=status)
    return str(body.get("error") or body.get("message") or "")


def register_and_login(username, nickname):
    """注册并登录，返回已带 Bearer 令牌的 APIClient。"""
    client = APIClient()
    register = client.post(AUTH + "register/", {
        "username": username, "password": PASSWORD, "nickname": nickname,
    }, format="json")
    if register.status_code not in (200, 201):
        # 站点开启邀请码时注册接口会 400：退回 ORM 建号，登录仍走真实接口
        from django.contrib.auth import get_user_model

        User = get_user_model()
        if not User.objects.filter(username=username).exists():
            User.objects.create_user(username=username, password=PASSWORD,
                                     nickname=nickname)
    login = client.post(AUTH + "login/", {
        "username": username, "password": PASSWORD,
    }, format="json")
    if login.status_code != 200:
        raise RuntimeError(f"登录失败 {username}：{login.status_code} "
                           f"{login.content[:300]!r}")
    token = (login.json() or {}).get("access")
    if not token:
        raise RuntimeError(f"登录响应缺少 access 令牌：{login.json()}")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ---------------------------------------------------------------------------
# 主链路
# ---------------------------------------------------------------------------


def run():
    now = timezone.now()
    suffix = STAMP[-6:]
    user_a = f"obs_smoke_{STAMP}"
    user_b = f"obs_smoke_b_{STAMP}"
    nick_a = f"冒烟爱丽丝{suffix}"
    nick_b = f"冒烟鲍勃{suffix}"
    team = f"冒烟团队-{suffix}"

    print("\n== 0. 账号注册/登录 ==")
    client = register_and_login(user_a, nick_a)
    other = register_and_login(user_b, nick_b)
    check(True, "账号注册并登录成功（两个独立令牌）")

    print("\n== 1. 目录契约 ==")
    catalog = api(client, "GET", "")
    check(catalog.get("app") == "observability", "目录返回 app=observability")
    check(int(catalog.get("endpoint_count") or 0) >= 100,
          f"目录接口数 >= 100（实际 {catalog.get('endpoint_count')}）")
    check(bool(catalog.get("compute", {}).get("burn_windows")),
          "目录暴露燃烧率窗口口径")

    print("\n== 2. 服务 ==")
    service = api(client, "POST", "services/create/", {
        "name": f"冒烟服务-{suffix}", "team": team, "level": "P0",
        "description": "observability 冒烟脚本创建",
    })
    service_id = service["id"]
    check(bool(service_id), "服务创建返回 id")
    check(bool(service.get("slug")), "服务自动生成 slug")
    check(service.get("status") == "healthy", "服务默认状态 healthy")
    check(service.get("owner_name") == nick_a, "服务负责人=当前用户昵称")
    detail = api(client, "GET", f"services/{service_id}/")
    check(detail.get("counts", {}).get("metrics") == 0, "新服务指标计数为 0")
    listing = api(client, "GET", "services/", params={"team": team})
    check(listing.get("count") == 1, "服务列表按团队过滤命中 1 条")

    dup_slug = error_of(client, "POST", "services/create/",
                        {"name": "另一个服务", "slug": service["slug"]})
    check("服务标识已存在" in dup_slug, "重复 slug 被拒绝并给出可操作提示")

    blank_name = error_of(client, "POST", "services/create/", {"name": "   "})
    check("服务名称不能为空" in blank_name, "空白服务名被拒绝并给出明确提示")

    print("\n== 3. 指标定义与上报 ==")
    for name, metric_type, unit in (
            ("requests_total", "counter", ""),
            ("errors_total", "counter", ""),
            ("request_latency_ms", "histogram", "ms"),
            ("qps", "gauge", "")):
        metric = api(client, "POST", "metrics/defs/create/", {
            "service_id": service_id, "name": name, "metric_type": metric_type,
            "unit": unit,
        })
        check(metric.get("name") == name, f"指标定义创建成功：{name}")
    metric_list = api(client, "GET", "metrics/defs/", params={"service_id": service_id})
    check(metric_list.get("count") == 4, "指标定义列表计数为 4")
    dup_metric = error_of(client, "POST", "metrics/defs/create/", {
        "service_id": service_id, "name": "requests_total"})
    check("同名指标" in dup_metric, "同名指标被拒绝")

    points = [
        # 可用性 SLO 的计数器（一次窗口内的总量）
        {"service_id": service_id, "metric": "requests_total", "value": 1000,
         "timestamp": (now - timedelta(minutes=10)).isoformat()},
        {"service_id": service_id, "metric": "errors_total", "value": 5,
         "timestamp": (now - timedelta(minutes=10)).isoformat()},
    ]
    # 延迟 SLO 的样本：2 条达标 + 2 条超标（阈值 250ms）
    for offset, value in enumerate((100, 150, 300, 400)):
        points.append({
            "service_id": service_id, "metric": "request_latency_ms", "value": value,
            "timestamp": (now - timedelta(minutes=30 - offset)).isoformat(),
        })
    # 告警规则的持续样本：最近 30 秒内 6 个点，值均 > 5
    for index in range(6):
        points.append({
            "service_id": service_id, "metric": "requests_total", "value": 10,
            "timestamp": (now - timedelta(seconds=5 * (index + 1))).isoformat(),
        })
    batch = api(client, "POST", "metrics/points/batch/", {"points": points})
    check(batch.get("created") == 12, "批量上报 12 个指标点")

    single = api(client, "POST", "metrics/points/report/", {
        "service_id": service_id, "metric": "qps", "value": 42,
        "labels": {"instance": "smoke-a"},
    })
    check(single.get("value") == 42.0, "单点上报返回写入值")

    bad_value = error_of(client, "POST", "metrics/points/report/", {
        "service_id": service_id, "metric": "qps", "value": "abc"})
    check("数值" in bad_value, "非法数值上报被拒绝（提示数值）")
    bad_time = error_of(client, "POST", "metrics/points/report/", {
        "service_id": service_id, "metric": "qps", "value": 1,
        "timestamp": "not-a-time"})
    check("时间" in bad_time, "非法时间戳上报被拒绝（提示时间）")

    print("\n== 4. 指标查询 ==")
    query = api(client, "GET", "metrics/points/query/", params={
        "service_id": service_id, "metric": "requests_total",
        "hours": 1, "aggregation": "sum"})
    check(query.get("count") == 7, "查询窗口命中 7 个请求计数点")
    check(query.get("value") == 1060.0, "聚合 sum = 1060")
    percentiles = api(client, "GET", "metrics/points/percentiles/", params={
        "service_id": service_id, "metric": "qps", "hours": 1})
    check(percentiles.get("summary", {}).get("p50") == 42.0, "qps 分位 P50 = 42")
    check(percentiles.get("method") == "nearest_rank", "分位口径为最近秩法")
    latest = api(client, "GET", "metrics/points/latest/", params={
        "service_id": service_id, "metric": "qps"})
    check(latest.get("point", {}).get("value") == 42.0, "最新值查询返回 42")
    labels = api(client, "GET", "metrics/points/labels/", params={
        "service_id": service_id, "metric": "qps"})
    check("instance" in (labels.get("keys") or []), "标签枚举包含 instance")

    print("\n== 5. SLO / 错误预算 / 燃烧率 ==")
    slo = api(client, "POST", "slos/create/", {
        "service_id": service_id, "name": f"冒烟可用性{suffix}",
        "slo_type": "availability", "target_pct": 99.0, "window_days": 30,
    })
    slo_id = slo["id"]
    check(bool(slo_id), "可用性 SLO 创建成功")
    computed = api(client, "POST", f"slos/{slo_id}/compute/", {"id": slo_id})
    check(computed.get("total_requests") == 1060, "SLO 总请求 = 1060")
    check(computed.get("bad_requests") == 5, "SLO 坏请求 = 5")
    check(computed.get("met") is True, "SLO 达标（达成率 > 99%）")
    check(float(computed.get("attainment_pct") or 0) > 99.0, "SLO 达成率 > 99%")
    check(bool(computed.get("budget")), "计算接口同时返回错误预算")
    api(client, "POST", f"slos/{slo_id}/compute/", {"id": slo_id})
    windows = api(client, "GET", f"slos/{slo_id}/windows/")
    check(windows.get("count") == 1, "重复计算只保留一个窗口快照（幂等）")
    budget = api(client, "GET", f"slos/{slo_id}/budget/")
    check(budget.get("status") == "healthy", "错误预算状态 healthy")
    check(float(budget.get("total_allowed") or 0) > 0, "错误预算总额度 > 0")
    burn = api(client, "GET", f"slos/{slo_id}/burn-rate/")
    check([row.get("window") for row in burn.get("windows", [])]
          == ["1h", "6h", "3d"], "燃烧率窗口为 1h/6h/3d")
    check(burn.get("state") == "ok", "当前燃烧率状态 ok")
    forecast = api(client, "GET", f"slos/{slo_id}/forecast/", params={"days": 10})
    check(forecast.get("available") is True, "预算预测可用")
    check(len(forecast.get("points") or []) == 11, "预测曲线为 11 个点（10 天）")

    latency_slo = api(client, "POST", "slos/create/", {
        "service_id": service_id, "name": f"冒烟延迟{suffix}", "slo_type": "latency",
        "target_pct": 90, "latency_threshold_ms": 250, "window_days": 30,
    })
    latency_id = latency_slo["id"]
    check(latency_slo.get("slo_type") == "latency", "延迟 SLO 创建成功")
    latency_result = api(client, "POST", f"slos/{latency_id}/compute/",
                         {"id": latency_id})
    check(latency_result.get("total_requests") == 4, "延迟 SLO 样本数 = 4")
    check(latency_result.get("good_requests") == 2, "延迟 SLO 达标样本 = 2")
    check(latency_result.get("attainment_pct") == 50.0, "延迟 SLO 达成率 = 50%")
    check(latency_result.get("source") == "latency_samples",
          "延迟 SLO 数据来源为 latency_samples")

    print("\n== 6. 告警链路 ==")
    rule = api(client, "POST", "alerts/rules/create/", {
        "service_id": service_id, "name": f"冒烟错误率高{suffix}",
        "expression": "requests_total > 5", "duration_seconds": 60,
        "severity": "critical", "cooldown_seconds": 600,
    })
    rule_id = rule["id"]
    check(bool(rule_id), "告警规则创建成功")
    evaluated = api(client, "POST", "alerts/evaluate/", {})
    check(evaluated.get("firing") == 1, "巡检触发 1 条告警")
    event_id = (evaluated.get("items") or [{}])[0].get("event_id")
    check(bool(event_id), "触发结果携带事件 id")
    events = api(client, "GET", "alerts/events/", params={"status": "firing"})
    check(events.get("count") >= 1, "告警事件列表可见 firing 事件")
    acked = api(client, "POST", f"alerts/events/{event_id}/ack/",
                {"note": "冒烟确认"})
    # 告警确认只记录确认人/时间，不改变触发状态（仍需恢复）；
    # acknowledged 是事故（incidents）的状态，不适用于告警事件。
    check(bool(acked.get("acknowledged_at")) and bool(acked.get("acknowledged_by"))
          and acked.get("status") == "firing", "告警事件确认成功")
    silence = api(client, "POST", "alerts/silences/create/", {
        "rule_id": rule_id, "minutes": 30, "reason": "冒烟静默窗口"})
    check(silence.get("status") == "active", "静默窗口创建成功")
    silences = api(client, "GET", "alerts/silences/", params={"rule_id": rule_id})
    check(silences.get("count") >= 1, "静默列表可见新建窗口")

    print("\n== 7. 事故 ==")
    incident = api(client, "POST", "incidents/create/", {
        "title": f"冒烟事故-{suffix}", "severity": "sev2",
        "services": [service_id], "impact": "冒烟影响面",
    })
    incident_id = incident["id"]
    check(incident.get("status") == "open", "事故登记后状态 open")
    check(incident.get("owner_name") == nick_a, "事故负责人=当前用户昵称")
    timeline = api(client, "GET", f"incidents/{incident_id}/timeline/")
    check(timeline.get("count") == 1, "时间线首条为登记事件（无重复）")
    check((timeline.get("items") or [{}])[0].get("status_change") == "->open",
          "时间线首条状态变更 ->open")
    acked_incident = api(client, "POST", f"incidents/{incident_id}/acknowledge/",
                         {"note": "开始排查"})
    check(acked_incident.get("status") == "acknowledged", "事故确认（acknowledged）")
    check(acked_incident.get("mtta_seconds") is not None, "事故记录 MTTA")
    mitigated = api(client, "POST", f"incidents/{incident_id}/mitigate/", {})
    check(mitigated.get("status") == "mitigated", "事故缓解（mitigated）")
    resolved = api(client, "POST", f"incidents/{incident_id}/resolve/",
                   {"root_cause": "冒烟根因：连接池打满"})
    check(resolved.get("status") == "resolved", "事故解决（resolved）")
    check(resolved.get("root_cause") == "冒烟根因：连接池打满", "解决时写入根因")
    check(resolved.get("mttr_seconds") is not None, "事故记录 MTTR")
    postmortem = api(client, "POST", f"incidents/{incident_id}/postmortem/",
                     {"action_items": ["扩容连接池"]})
    check(postmortem.get("status") == "postmortem", "事故复盘（postmortem）")
    check(postmortem.get("action_items") == ["扩容连接池"], "复盘写入行动项")
    full_timeline = api(client, "GET", f"incidents/{incident_id}/timeline/")
    check(full_timeline.get("count") >= 5, "全生命周期时间线 >= 5 条")
    update = api(client, "POST", f"incidents/{incident_id}/updates/create/",
                 {"content": "冒烟补记：连接池扩容完成"})
    check(update.get("content") == "冒烟补记：连接池扩容完成", "事故更新记录创建成功")
    updates = api(client, "GET", f"incidents/{incident_id}/updates/")
    check(updates.get("count") >= 6, "事故更新记录列表包含补记")
    terminal = error_of(client, "POST", f"incidents/{incident_id}/resolve/", {})
    check("已处于" in terminal, "终态事故不能再次流转")

    print("\n== 8. 值班与升级 ==")
    schedule = api(client, "POST", "oncall/schedules/create/", {
        "team": team, "name": f"冒烟主值班{suffix}", "rotation": "daily",
        "start_at": (now - timedelta(days=2)).isoformat(),
        "members": [user_a, user_b],
    })
    schedule_id = schedule["id"]
    check(bool(schedule_id), "值班表创建成功")
    current = api(client, "GET", "oncall/current/", params={"team": team})
    check(current.get("count") == 1, "当前值班按团队命中 1 条")
    check((current.get("items") or [{}])[0].get("member") == user_a,
          "当前值班人为轮换首位成员")
    upcoming = api(client, "GET", "oncall/upcoming/",
                   params={"schedule_id": schedule_id, "count": 3})
    check(upcoming.get("count") == 3, "未来排班返回 3 个班次")
    swapped = api(client, "POST", "oncall/swap/", {
        "schedule_id": schedule_id, "to_member": "carol-smoke"})
    check(swapped.get("from") == user_a, "换班前值班人为 alice")
    check(swapped.get("to") == "carol-smoke", "换班后值班人为 carol")

    policy1 = api(client, "POST", "escalations/create/", {
        "team": team, "level": 1, "delay_minutes": 5, "target_name": "值班A"})
    policy2 = api(client, "POST", "escalations/create/", {
        "team": team, "level": 2, "delay_minutes": 10, "target_name": "值班B"})
    check(policy1.get("level") == 1, "一级升级策略创建成功")
    escalation = api(client, "GET", "escalations/check/",
                     params={"team": team, "elapsed_minutes": 7})
    check(escalation.get("current_level") == 1, "7 分钟时升级到第 1 级")
    check(len(escalation.get("targets") or []) == 1, "7 分钟时只通知 1 个目标")
    unknown = api(client, "GET", "escalations/check/",
                  params={"team": f"未知团队-{suffix}"})
    check(unknown.get("levels") == [], "未配置团队返回空层级且不升级")

    print("\n== 9. 健康检查 ==")
    health_check = api(client, "POST", "health-checks/create/", {
        "service_id": service_id, "check_type": "http",
        "interval_seconds": 60, "timeout_seconds": 5,
    })
    check_id = health_check["id"]
    check(bool(check_id), "健康检查创建成功")
    run_result = api(client, "POST", f"health-checks/{check_id}/run/",
                     {"succeed": True, "latency_ms": 42})
    check(run_result.get("run", {}).get("status") == "up", "健康检查执行成功（up）")
    check(run_result.get("health", {}).get("score") == 100.0, "服务健康分 = 100")
    trend = api(client, "GET", "health-checks/trend/",
                params={"check_id": check_id, "bucket_hours": 1})
    check(trend.get("available") is True, "健康趋势可用")
    check(trend.get("total_runs") == 1, "健康趋势统计到 1 次执行")

    print("\n== 10. 统计与权限 ==")
    overview = api(client, "GET", "stats/overview/")
    check(overview.get("services", {}).get("total") == 1, "总览服务数 = 1")
    check(overview.get("slos", {}).get("total") == 2, "总览 SLO 数 = 2")
    check(overview.get("incidents", {}).get("total") == 1, "总览事故数 = 1")

    other_services = api(other, "GET", "services/")
    check(other_services.get("count") == 0, "他人看不到当前用户的服务")
    denied_read = error_of(other, "GET", f"services/{service_id}/")
    check("无权查看" in denied_read, "他人读取服务被拒绝")
    denied_write = error_of(other, "POST", "metrics/points/report/", {
        "service_id": service_id, "metric": "qps", "value": 1})
    check("无权修改" in denied_write, "他人上报指标被拒绝（提示无权修改）")

    print("\n== 11. 清理（尽力而为，不计入断言） ==")
    for path in (f"incidents/{incident_id}/delete/",
                 f"oncall/schedules/{schedule_id}/delete/",
                 f"escalations/{policy1['id']}/delete/",
                 f"escalations/{policy2['id']}/delete/",
                 f"slos/{latency_id}/delete/",
                 f"slos/{slo_id}/delete/",
                 f"services/{service_id}/delete/"):
        try:
            api(client, "POST", path)
        except Exception as exc:  # noqa: BLE001 —— 清理失败不影响冒烟结论
            print(f"  [warn] 清理 {path} 失败：{exc}")

    return 0


def main():
    print(f"observability 冒烟测试（进程内 APIClient，stamp={STAMP}）")
    try:
        run()
    except Exception:  # noqa: BLE001 —— 顶层兜底：打印完整栈并返回非零码
        traceback.print_exc()
        _failures.append("执行过程中出现未捕获异常（详见上方栈）")
    total = _passed + len(_failures)
    print(f"\n断言 {total} 项：通过 {_passed}，失败 {len(_failures)}")
    if _failures:
        print("失败项：")
        for item in _failures:
            print(f" - {item}")
        return 1
    print("observability 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())