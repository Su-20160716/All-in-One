# -*- coding: utf-8 -*-
"""可观测性中心 · 分析层（异常检测 / 容量预测 / 告警噪音 / 预算策略 / 关键度 / 相似事故）。

为什么需要这一层
----------------
基础指标（聚合、SLO、燃烧率）回答「现在怎么样」；分析层回答「哪里不对劲、
什么时候会出事、这条告警值不值得留、这个服务挂了影响多大、以前是不是
遇到过」。这些问题的答案全部由已有数据推导，不引入任何外部依赖或模型。

算法选择
--------
- 异常检测用「滑动中位数 + MAD」而不是均值 + 标准差：监控数据天然长尾，
  一个故障尖峰会把均值和方差一起抬高，反而让后续尖峰检测不出来；
  MAD 对离群点不敏感，是流式异常检测的常用稳健估计。
- 容量预测用最小二乘线性回归：可解释、可复算，复盘时能直接给出公式。
- 告警噪音分按「重复率 / 未处置率 / 静默率」加权：这三个指标分别对应急需
  合并、急需值班培训、急需调阈值三类完全不同的治理动作。
- 服务关键度 = 直接依赖方的等级权重 + 传递影响面：只看直接被依赖数会
  低估「底层存储」这类服务。
"""
import math
from datetime import datetime as py_datetime
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone

from observability import services

# 异常检测默认阈值：|稳健 z 分数| >= 3.5 视为异常（约 0.05% 的双侧概率）
DEFAULT_Z_THRESHOLD = 3.5

# 滑动窗口最少样本数：样本太少时中位数没有统计意义
MIN_BASELINE = 5

# 服务等级 → 关键度权重
LEVEL_WEIGHTS = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}

# 告警噪音分阈值 → 治理建议
NOISE_BANDS = (
    (80, "严重噪音", "立即合并/删除规则，或延长持续时间并提高阈值"),
    (60, "噪音偏高", "建议合并同类规则、增加抑制与分组"),
    (40, "可接受", "观察一两周，若持续偏高再调整"),
    (0, "健康", "规则质量良好，保持现状"),
)


def _median(values):
    """中位数（偶数个取中间两数均值）。"""
    data = sorted(values)
    if not data:
        return 0.0
    mid = len(data) // 2
    if len(data) % 2:
        return float(data[mid])
    return (data[mid - 1] + data[mid]) / 2.0


def mad(values):
    """中位数绝对偏差（MAD）：稳健离散度，对离群点不敏感。"""
    data = [float(v) for v in values]
    if not data:
        return 0.0
    center = _median(data)
    return _median([abs(v - center) for v in data])


def robust_z(value, baseline):
    """稳健 z 分数：0.6745 是把 MAD 折算成正态标准差的常数。"""
    center = _median(baseline)
    scale = mad(baseline)
    if scale <= 0:
        # MAD 为 0（基线几乎恒定）时退回平均绝对偏差，避免除零
        scale = sum(abs(v - center) for v in baseline) / max(len(baseline), 1)
    if scale <= 0:
        return 0.0
    return 0.6745 * (float(value) - center) / scale


def detect_anomalies(rows, window=20, threshold=DEFAULT_Z_THRESHOLD, max_items=100):
    """滑动窗口异常检测：返回每个异常点的分数、方向与严重度。

    rows 为 [(timestamp, value)]（按时间升序）。每个点只用它之前的 window
    个点做基线，避免用未来数据解释现在（在线检测必须可实时复现）。
    """
    data = [(ts, float(value)) for ts, value in rows]
    if len(data) < MIN_BASELINE + 1:
        return {
            "available": False,
            "reason": f"样本不足（至少需要 {MIN_BASELINE + 1} 个点）",
            "items": [],
            "count": 0,
        }
    window = max(int(window or 20), MIN_BASELINE)
    items = []
    for index in range(MIN_BASELINE, len(data)):
        start = max(index - window, 0)
        baseline = [value for _, value in data[start:index]]
        if len(baseline) < MIN_BASELINE:
            continue
        ts, value = data[index]
        scale = mad(baseline)
        if scale <= 0:
            same = all(abs(v - baseline[0]) < 1e-12 for v in baseline)
            if same and abs(value - baseline[0]) < 1e-12:
                continue
            if same:
                score = 999.0 if value != baseline[0] else 0.0
            else:
                score = robust_z(value, baseline)
        else:
            score = robust_z(value, baseline)
        if abs(score) < threshold:
            continue
        severity = "critical" if abs(score) >= threshold * 2 else "warning"
        items.append({
            "index": index,
            "timestamp": services.iso(ts),
            "value": services.round4(value),
            "baseline_median": services.round4(_median(baseline)),
            "baseline_mad": services.round4(scale),
            "score": services.round4(score),
            "direction": "spike" if score > 0 else "drop",
            "severity": severity,
        })
        if len(items) >= max_items:
            break
    return {
        "available": True,
        "window": window,
        "threshold": threshold,
        "samples": len(data),
        "count": len(items),
        "items": items,
        "spikes": sum(1 for i in items if i["direction"] == "spike"),
        "drops": sum(1 for i in items if i["direction"] == "drop"),
    }


def linear_regression(points):
    """最小二乘拟合 y = a + b*x；返回斜率、截距与 R²。

    points 为 [(x, y)]。R² 用来判断这条趋势线是否值得相信：R² 很低的
    「趋势」多半是噪声，预测接口会据此给出低置信度标记。
    """
    data = [(float(x), float(y)) for x, y in points]
    n = len(data)
    if n < 2:
        return {"slope": 0.0, "intercept": data[0][1] if data else 0.0,
                "r2": 0.0, "samples": n}
    sum_x = sum(x for x, _ in data)
    sum_y = sum(y for _, y in data)
    sum_xy = sum(x * y for x, y in data)
    sum_xx = sum(x * x for x, _ in data)
    denominator = n * sum_xx - sum_x * sum_x
    if abs(denominator) < 1e-12:
        return {"slope": 0.0, "intercept": sum_y / n, "r2": 0.0, "samples": n}
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    mean_y = sum_y / n
    ss_total = sum((y - mean_y) ** 2 for _, y in data)
    ss_residual = sum((y - (intercept + slope * x)) ** 2 for x, y in data)
    r2 = 1.0 - ss_residual / ss_total if ss_total > 0 else 0.0
    return {
        "slope": slope,
        "intercept": intercept,
        "r2": services.round4(max(0.0, min(r2, 1.0))),
        "samples": n,
    }


def capacity_forecast(rows, threshold, horizon_days=30, now=None):
    """容量预测：按线性趋势外推指标首次触及阈值的时间。

    只对「上升趋势」预测（下降趋势意味着短期内不会触顶）；返回的
    ``confidence`` 直接来自 R²，前端可以据此决定是否展示预测日期。
    """
    now = now or timezone.now()
    data = [(ts, float(value)) for ts, value in rows]
    if len(data) < 3:
        return {"available": False, "reason": "样本不足（至少 3 个点）",
                "threshold": threshold}
    origin = data[0][0]
    points = [((ts - origin).total_seconds() / 86400.0, value) for ts, value in data]
    fit = linear_regression(points)
    slope = fit["slope"]
    last_day = points[-1][0]
    last_value = data[-1][1]
    if slope <= 0:
        return {
            "available": True,
            "threshold": services.round4(threshold),
            "current": services.round4(last_value),
            "slope_per_day": services.round4(slope),
            "trend": "flat_or_down",
            "breach_in_days": None,
            "projected_breach_date": None,
            "confidence": fit["r2"],
            "message": "当前趋势不会触及阈值",
        }
    days_to_threshold = (float(threshold) - fit["intercept"]) / slope - last_day
    breach_date = (now + timedelta(days=max(days_to_threshold, 0))).date() \
        if days_to_threshold <= horizon_days else None
    return {
        "available": True,
        "threshold": services.round4(threshold),
        "current": services.round4(last_value),
        "slope_per_day": services.round4(slope),
        "intercept": services.round4(fit["intercept"]),
        "trend": "rising",
        "breach_in_days": services.round4(days_to_threshold) if days_to_threshold >= 0 else 0.0,
        "projected_breach_date": breach_date.isoformat() if breach_date else None,
        "within_horizon": days_to_threshold <= horizon_days,
        "confidence": fit["r2"],
        "horizon_days": horizon_days,
        "message": ("预计 %s 触及阈值" % breach_date.isoformat()) if breach_date
        else "预测触顶时间超出观察窗口",
    }


def alert_noise_score(total, resolved, suppressed, firing, distinct_days=1):
    """告警噪音分（0-100）：越高越该治理。

    三个因子与三类治理动作一一对应，避免给出一个「玄学分数」：
    - 重复率：同一规则反复触发 → 合并/延长持续时间；
    - 未处置率：一直 firing 没人管 → 值班流程问题；
    - 静默率：大量靠静默压住 → 阈值本身不合理。
    """
    total = max(int(total or 0), 0)
    if total == 0:
        return {"score": 0.0, "band": "健康", "advice": NOISE_BANDS[-1][2],
                "factors": {"redundancy": 0.0, "unhandled": 0.0, "silenced": 0.0}}
    distinct = max(int(distinct_days or 1), 1)
    redundancy = services.clamp(1.0 - distinct / float(total), 0.0, 1.0)
    unhandled = services.clamp(float(firing or 0) / total, 0.0, 1.0)
    silenced = services.clamp(float(suppressed or 0) / total, 0.0, 1.0)
    resolved_ratio = services.clamp(float(resolved or 0) / total, 0.0, 1.0)
    score = 100.0 * (0.45 * redundancy + 0.35 * unhandled + 0.20 * silenced)
    # 自动恢复率高说明规则本身是「抖一下就恢复」，适当加分体现噪音
    score += 10.0 * resolved_ratio if redundancy > 0.5 else 0.0
    score = services.clamp(score, 0.0, 100.0)
    band, advice = NOISE_BANDS[-1][0], NOISE_BANDS[-1][2]
    for bound, label, text in NOISE_BANDS:
        if score >= bound:
            band, advice = label, text
            break
    return {
        "score": services.round4(score),
        "band": band,
        "advice": advice,
        "factors": {
            "redundancy": services.round4(redundancy),
            "unhandled": services.round4(unhandled),
            "silenced": services.round4(silenced),
            "resolved_ratio": services.round4(resolved_ratio),
        },
    }


def noise_ranking(rule_rows, limit=10):
    """对规则的事件统计做噪音打分并排序（最吵的排前面）。"""
    rows = []
    for row in rule_rows:
        score = alert_noise_score(
            total=row.get("total", 0),
            resolved=row.get("resolved", 0),
            suppressed=row.get("suppressed", 0),
            firing=row.get("firing", 0),
            distinct_days=row.get("distinct_days", 1),
        )
        item = dict(row)
        item.update(score)
        rows.append(item)
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def error_budget_policy(burn_report, budget=None):
    """错误预算策略：把燃烧率与预算状态翻译成「能不能发布」。

    Google SRE 的错误预算策略核心是「预算烧完就冻结变更」，这里给出
    三档：normal / watch / slow_down / freeze，并附上可执行的理由。
    """
    state = (burn_report or {}).get("state") or "insufficient_data"
    budget_status = (budget or {}).get("status") or "unknown"
    budget_remaining_pct = None
    if budget and budget.get("total_allowed"):
        budget_remaining_pct = services.round4(
            float(budget.get("remaining") or 0) / float(budget["total_allowed"]) * 100.0)
    if state == "critical_burn" and budget_status == "exhausted":
        decision = "freeze"
        label = "冻结发布"
        actions = [
            "停止所有非修复类变更",
            "拉事故复盘会议，确认错误来源",
            "把预算恢复情况纳入每日站会",
        ]
    elif state == "critical_burn":
        decision = "slow_down"
        label = "变更降速"
        actions = [
            "仅允许修复类与回滚类变更",
            "对核心链路开启更短的燃烧率窗口（1h）盯盘",
            "准备回滚预案并指定值守人",
        ]
    elif state == "elevated_burn":
        decision = "watch"
        label = "加强观察"
        actions = ["关注 6h 窗口燃烧率是否继续恶化", "确认是否为已知的容量问题"]
    else:
        decision = "normal"
        label = "正常发布"
        actions = ["按常规发布节奏进行"]
    return {
        "decision": decision,
        "label": label,
        "burn_state": state,
        "budget_status": budget_status,
        "budget_remaining_pct": budget_remaining_pct,
        "actions": actions,
        "worst_window": (burn_report or {}).get("worst_window"),
        "generated_at": services.iso(timezone.now()),
    }


def service_criticality(service, services_list, edges, max_depth=10):
    """服务关键度：被依赖的等级权重 + 传递影响面，归一到 0-100。

    只看直接扇入会低估底层组件（数据库/网关），因此把「故障向上传播的
    全部上游」按等级加权计入；归一化用当前可见服务里的最大值，保证不同
    规模的组织都能得到有区分度的分数。
    """
    service_map = {s.id: s for s in services_list}
    dependents = {}
    for edge in edges:
        dependents.setdefault(edge.downstream_id, []).append(edge.upstream_id)
    direct_weight = 0
    for upstream_id in dependents.get(service.id, []):
        upstream = service_map.get(upstream_id)
        direct_weight += LEVEL_WEIGHTS.get(getattr(upstream, "level", "P2"), 2)
    try:
        impact = services.impact_analysis(service.id, edges=edges,
                                          services=services_list, max_depth=max_depth)
        indirect = sum(LEVEL_WEIGHTS.get(item["level"], 2)
                       for item in impact["impacted"])
    except ValueError:
        indirect = 0
    raw = direct_weight * 2 + indirect
    # 同批服务里的最大值做归一化基准（至少 1 避免除零）
    baseline = max(raw, 1)
    for other in services_list:
        if other.id == service.id:
            continue
        weight = sum(LEVEL_WEIGHTS.get(getattr(service_map.get(up), "level", "P2"), 2)
                     for up in dependents.get(other.id, []))
        try:
            other_impact = services.impact_analysis(other.id, edges=edges,
                                                    services=services_list, max_depth=3)
            weight += sum(LEVEL_WEIGHTS.get(item["level"], 2)
                          for item in other_impact["impacted"])
        except ValueError:
            pass
        baseline = max(baseline, weight * 2)
    score = services.round4(services.clamp(100.0 * raw / baseline, 0.0, 100.0))
    rank_label = ("核心依赖" if score >= 70 else "重要依赖" if score >= 40
                  else "一般依赖" if score >= 15 else "边缘依赖")
    return {
        "service_id": service.id,
        "name": service.name,
        "level": service.level,
        "direct_dependents": len(dependents.get(service.id, [])),
        "direct_weight": direct_weight,
        "indirect_impact_weight": indirect,
        "criticality_score": score,
        "label": rank_label,
    }


def criticality_ranking(services_list, edges, limit=20):
    """关键度排行：一次算完所有服务并排序（总览页的「核心依赖」卡片）。"""
    rows = [service_criticality(s, services_list, edges) for s in services_list]
    rows.sort(key=lambda r: -r["criticality_score"])
    return rows[:limit]


def _tokens(text):
    """中英混合分词：英文按词、中文按二元组，用于相似度计算。

    不引入分词库（约束：不新增依赖）。中文二元组对「数据库连接池耗尽」
    这类短语的召回已经足够，且完全确定、可复现。
    """
    text = str(text or "").lower()
    words = set()
    buffer = []
    cjk = []
    for char in text:
        if char.isascii() and (char.isalnum() or char in "-_"):
            buffer.append(char)
            if cjk:
                cjk.append(None)
        else:
            if buffer:
                words.add("".join(buffer))
                buffer = []
            if "\u4e00" <= char <= "\u9fff":
                cjk.append(char)
            else:
                if len(cjk) >= 2:
                    words.update("".join(cjk[i:i + 2]) for i in range(len(cjk) - 1))
                cjk = []
    if buffer:
        words.add("".join(buffer))
    if len(cjk) >= 2:
        words.update("".join(cjk[i:i + 2]) for i in range(len(cjk) - 1))
    return words


def incident_similarity(incident, candidates, limit=5):
    """相似事故：服务重合度 + 文本相似度（Jaccard），用于「以前见过吗」。"""
    base_services = {int(i) for i in (incident.services or []) if str(i).isdigit()}
    base_tokens = _tokens(" ".join([incident.title or "", incident.impact or "",
                                    incident.root_cause or ""]))
    rows = []
    for other in candidates:
        if other.id == incident.id:
            continue
        other_services = {int(i) for i in (other.services or []) if str(i).isdigit()}
        other_tokens = _tokens(" ".join([other.title or "", other.impact or "",
                                         other.root_cause or ""]))
        service_union = base_services | other_services
        service_overlap = (len(base_services & other_services) / len(service_union)
                           if service_union else 0.0)
        token_union = base_tokens | other_tokens
        token_overlap = (len(base_tokens & other_tokens) / len(token_union)
                         if token_union else 0.0)
        score = 0.6 * service_overlap + 0.4 * token_overlap
        if score <= 0:
            continue
        rows.append({
            "incident_id": other.id,
            "title": other.title,
            "severity": other.severity,
            "status": other.status,
            "started_at": services.iso(other.started_at),
            "score": services.round4(score * 100.0),
            "service_overlap": services.round4(service_overlap),
            "text_overlap": services.round4(token_overlap),
            "shared_services": sorted(base_services & other_services),
        })
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def health_trend(runs, bucket_hours=1):
    """健康趋势：按桶统计可用率与平均延迟，并给出连续失败段。

    连续失败段是排障时最需要的信号：单点 down 往往是抖动，连续 down
    才是真故障，需要直接对应到告警与事故。
    """
    rows = sorted(runs, key=lambda r: r.checked_at)
    if not rows:
        return {"available": False, "points": [], "incidents": []}
    bucket_seconds = max(int(float(bucket_hours) * 3600), 60)
    buckets = {}
    for run in rows:
        epoch = int(run.checked_at.timestamp())
        key = epoch // bucket_seconds * bucket_seconds
        buckets.setdefault(key, []).append(run)
    points = []
    for key in sorted(buckets):
        group = buckets[key]
        up = sum(1 for r in group if r.status == "up")
        points.append({
            "start": services.iso(py_datetime.fromtimestamp(key, dt_timezone.utc)),
            "total": len(group),
            "up": up,
            "down": sum(1 for r in group if r.status == "down"),
            "availability_pct": services.round4(up / len(group) * 100.0),
            "avg_latency_ms": services.round4(
                sum(r.latency_ms for r in group) / len(group)),
        })
    outages = []
    current = None
    for run in rows:
        if run.status == "down":
            if current is None:
                current = {"start": run.checked_at, "end": run.checked_at,
                           "failures": 0}
            current["end"] = run.checked_at
            current["failures"] += 1
            current["error"] = run.error
        elif current is not None:
            outages.append({
                "start": services.iso(current["start"]),
                "end": services.iso(current["end"]),
                "failures": current["failures"],
                "duration_seconds": services.seconds_between(current["start"],
                                                            current["end"]),
                "error": current.get("error", ""),
            })
            current = None
    if current is not None:
        outages.append({
            "start": services.iso(current["start"]),
            "end": None,
            "failures": current["failures"],
            "duration_seconds": None,
            "error": current.get("error", ""),
            "ongoing": True,
        })
    return {
        "available": True,
        "bucket_hours": bucket_hours,
        "points": points,
        "outages": outages,
        "total_runs": len(rows),
        "availability_pct": services.round4(
            sum(1 for r in rows if r.status == "up") / len(rows) * 100.0),
    }


def capacity_burn_forecast(series_rows, threshold, horizon_days=30, now=None):
    """指标容量预测的入口：把 (时间, 值) 序列直接交给线性外推。

    与 budget_forecast 的区别：预算预测针对「错误预算剩余额度」，此刻的
    预测针对「任意指标的容量水位」（磁盘、连接数、QPS），两者共用回归
    实现但对外语义不同，因此保留两个入口避免调用方传错参数。
    """
    return capacity_forecast(series_rows, threshold, horizon_days=horizon_days, now=now)


def anomaly_summary(detection):
    """把异常检测结果压成一句话摘要（告警摘要/页面标题用）。"""
    if not detection.get("available"):
        return detection.get("reason", "样本不足")
    if detection["count"] == 0:
        return "窗口内未发现异常点"
    return (f"发现 {detection['count']} 个异常点（尖峰 {detection['spikes']}、"
            f"骤降 {detection['drops']}）")


def _exp_mean(values):
    """指数平滑均值：给近期样本更高权重，用于趋势摘要。"""
    data = [float(v) for v in values]
    if not data:
        return 0.0
    alpha = 0.3
    result = data[0]
    for value in data[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def trend_digest(rows):
    """趋势摘要：方向、斜率（每小时）、波动率与指数平滑均值。

    「波动率」用标准差 / 均值（变异系数）表达：同样的标准差，均值小的
    指标波动更严重，单看标准差会误判。
    """
    data = [(ts, float(value)) for ts, value in rows]
    if len(data) < 2:
        return {"available": False, "reason": "样本不足"}
    origin = data[0][0]
    points = [((ts - origin).total_seconds() / 3600.0, value) for ts, value in data]
    fit = linear_regression(points)
    values = [value for _, value in data]
    mean = sum(values) / len(values)
    stddev = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    cv = stddev / mean if mean else 0.0
    direction = "up" if fit["slope"] > 0 else "down" if fit["slope"] < 0 else "flat"
    return {
        "available": True,
        "samples": len(values),
        "mean": services.round4(mean),
        "stddev": services.round4(stddev),
        "cv": services.round4(cv),
        "min": services.round4(min(values)),
        "max": services.round4(max(values)),
        "slope_per_hour": services.round4(fit["slope"]),
        "r2": fit["r2"],
        "direction": direction,
        "smoothed": services.round4(_exp_mean(values)),
        "volatility_label": ("剧烈" if cv >= 1.0 else "偏高" if cv >= 0.5
                             else "平稳"),
    }
