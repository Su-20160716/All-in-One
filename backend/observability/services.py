# -*- coding: utf-8 -*-
"""可观测性中心 · 服务层（指标 / SLO / 告警 / 事故 / 值班的真实算法）。

为什么把这些算法单独成层
------------------------
聚合、分位、SLO 达成率、燃烧率、预算预测、告警求值、事故状态机、MTTA/
MTTR、健康评分、依赖影响分析，这些能力会被「列表接口、详情接口、统计
接口、目录接口」同时复用。如果留在视图里，同一个数字会出现两套算法
（例如 SLO 排行按窗口快照算、SLO 详情按指标点现算），复盘时无法解释
「为什么两个页面不一致」。这里是唯一真相。

章节
----
1. 时间与数值工具
2. 指标聚合与分位（最近秩法）
3. 时间序列分桶与降采样
4. SLO 计算（可用性 / 延迟 / 错误率）
5. 燃烧率（多窗口）与错误预算预测
6. 告警表达式解析与规则求值（含持续、抑制、静默）
7. 事故状态机与 MTTA/MTTR
8. 健康评分（多检查加权）
9. 依赖图与故障影响分析（反向 BFS，防环）
10. 统计聚合（总览 / 排行 / TOP / 趋势）

约定：所有「当前时间」都走 timezone.now()，不写死日期，测试可以构造过去
的数据来验证状态机与窗口统计。
"""
import math
import operator
import re
from collections import OrderedDict, defaultdict, deque
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date as dj_parse_date
from django.utils.dateparse import parse_datetime as dj_parse_datetime

from core.scoping import can_write, scope_queryset, visible_user_ids

from observability.models import (
    ALERT_EVENT_STATUS,
    ALERT_SEVERITIES,
    BUDGET_STATUS,
    HEALTH_STATUS,
    INCIDENT_SEVERITIES,
    INCIDENT_STATUS,
    AlertEvent,
    AlertRule,
    Dependency,
    ErrorBudget,
    HealthCheck,
    HealthCheckRun,
    Incident,
    IncidentUpdate,
    MetricDef,
    MetricPoint,
    Service,
    Silence,
    Slo,
    SloWindow,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 平台约定的标准指标名：SLO / 告警可以直接引用，不必每个服务重新定义
DEFAULT_TOTAL_METRIC = "requests_total"
DEFAULT_ERROR_METRIC = "errors_total"
DEFAULT_LATENCY_METRIC = "request_latency_ms"

# 多窗口燃烧率：窗口(小时) → 触发阈值（Google SRE Workbook 的多窗口口径）
BURN_WINDOWS = (
    ("1h", 1.0, 14.4),
    ("6h", 6.0, 6.0),
    ("3d", 72.0, 1.0),
)

# 一次聚合最多扫描的点数：防止一个超大时间范围把进程内存打满
MAX_POINTS_SCAN = 20000

# 分桶最少/最多桶数：太少没图形，太多前端画不动
MIN_BUCKETS = 1
MAX_BUCKETS = 500

# 健康检查状态 → 扣分比例（down 权重最高）
HEALTH_PENALTY = {"up": 0.0, "degraded": 0.35, "down": 1.0, "unknown": 0.2}

# 健康评分等级阈值（含下界）
HEALTH_GRADES = ((90, "A"), (75, "B"), (60, "C"), (40, "D"), (0, "F"))

# 事故合法流转：只允许沿链路前进一级，非法流转必须报错而不是静默改写
INCIDENT_TRANSITIONS = {
    "open": ("acknowledged",),
    "acknowledged": ("mitigated",),
    "mitigated": ("resolved",),
    "resolved": ("postmortem",),
    "postmortem": (),
}

# 事故流转 → 需要打点的时间字段
INCIDENT_TIMESTAMP_FIELDS = {
    "acknowledged": "acknowledged_at",
    "mitigated": "mitigated_at",
    "resolved": "resolved_at",
}

# 时间线里展示的中文动作名
INCIDENT_ACTION_LABELS = {
    "acknowledged": "确认事故",
    "mitigated": "缓解事故",
    "resolved": "解决事故",
    "postmortem": "完成复盘",
}

# 告警表达式允许的比较符（!= 也支持，用于「指标不等于基线」这类规则）
COMPARE_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

# 表达式：指标名 比较符 数值。指标名允许点号（如 http.server.duration）
EXPRESSION_RE = re.compile(
    r"^\s*([A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$"
)

# 伪指标：不来自 MetricPoint，而由平台实时推导
PSEUDO_METRICS = ("health_score", "error_rate", "slo_attainment", "check_failures")

# 聚合口径白名单：非法口径直接中文报错，避免把拼写错误当默认值静默放过
AGGREGATIONS = ("avg", "sum", "min", "max", "count", "last", "first",
                "p50", "p90", "p95", "p99")

# 标签枚举最多返回的取值个数
MAX_LABEL_VALUES = 200


# ---------------------------------------------------------------------------
# 1. 时间与数值工具
# ---------------------------------------------------------------------------


def parse_datetime(value, field="时间"):
    """解析 ISO 8601 时间；非法格式抛中文 ValueError（视图层统一转 400）。

    同时接受「纯日期」（YYYY-MM-DD），因为前端日期选择器只给日期；纯日期
    按当天 00:00 处理，符合「按日筛选」的直觉。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        dt = dj_parse_datetime(text)
        if dt is None:
            d = dj_parse_date(text)
            if d is None:
                raise ValueError(f"{field}格式非法，应为 ISO 8601 字符串（如 2026-01-02T03:04:05）")
            dt = datetime.combine(d, time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def parse_date(value, field="日期"):
    """解析 YYYY-MM-DD 日期。"""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    d = dj_parse_date(str(value).strip())
    if d is None:
        raise ValueError(f"{field}格式非法，应为 YYYY-MM-DD")
    return d


def to_float(value, field="数值"):
    """把入参安全转成有限浮点数（NaN/Inf 会污染 JSON，必须拒绝）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {field} 必须是数字")
    if not math.isfinite(number):
        raise ValueError(f"参数 {field} 必须是有限数字")
    return number


def to_int(value, field="数值"):
    """把入参安全转成整数（四舍五入，NaN 拒绝）。"""
    return int(round(to_float(value, field)))


def round4(value):
    """统一保留 4 位小数：达成率/燃烧率这类统计量不需要更多精度。"""
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def clamp(value, low, high):
    """区间夹取，用于把比率类结果限制在合理范围。"""
    return max(low, min(high, value))


def iso(dt):
    """序列化时间：None 安全，统一 ISO 8601 字符串。"""
    return dt.isoformat() if dt else None


def seconds_between(start, end):
    """两个时间点的秒数差；任一为空返回 None（用于未确认/未解决的时长）。"""
    if not start or not end:
        return None
    return (end - start).total_seconds()


def days_between(start, end):
    """天数差，最小按 1 小时计，避免除零把速率算成无穷大。"""
    seconds = seconds_between(start, end) or 0
    return max(seconds / 86400.0, 1.0 / 24.0)


def window_from(request, default_hours=24.0):
    """从 query 里取 since/until，缺省时回退到「最近 default_hours 小时」。

    返回 (since, until)；since >= until 时抛中文错误，避免出现空窗口把
    「没有数据」误判成「100% 达成」。
    """
    from devtools.common import opt_num, opt_str  # 延迟导入，避免 services 依赖 DRF

    now = timezone.now()
    since = parse_datetime(opt_str(request, "since"), "since") or None
    until = parse_datetime(opt_str(request, "until"), "until") or None
    if since is None and until is None:
        hours = float(opt_num(request, "hours", default_hours, minimum=0.01, maximum=24 * 365))
        until = now
        since = until - timedelta(hours=hours)
    elif since is None:
        hours = float(opt_num(request, "hours", default_hours, minimum=0.01, maximum=24 * 365))
        since = until - timedelta(hours=hours)
    elif until is None:
        until = now
    if since >= until:
        raise ValueError("窗口开始时间必须早于结束时间")
    return since, until


# ---------------------------------------------------------------------------
# 2. 指标聚合与分位
# ---------------------------------------------------------------------------


def percentile_nearest_rank(values, pct):
    """最近秩法计算分位：rank = ceil(pct/100 * n)，取第 rank 个（1-based）。

    选择最近秩而不是线性插值，是因为延迟分位的业界口径（Prometheus
    histogram_quantile 之外的主流实现）以「真实的第 k 个样本」为准，
    插值会给出不存在的延迟值，排障时容易误导。
    """
    data = sorted(float(v) for v in values)
    if not data:
        return 0.0
    pct = clamp(float(pct), 0.0, 100.0)
    rank = int(math.ceil(pct / 100.0 * len(data)))
    index = min(max(rank - 1, 0), len(data) - 1)
    return data[index]


def summarize(values):
    """一次性给出 count/sum/avg/min/max/stddev + P50/P90/P95/P99。"""
    data = [float(v) for v in values]
    if not data:
        return {
            "count": 0, "sum": 0.0, "avg": 0.0, "min": 0.0, "max": 0.0,
            "stddev": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0,
        }
    total = sum(data)
    avg = total / len(data)
    variance = sum((v - avg) ** 2 for v in data) / len(data)
    return {
        "count": len(data),
        "sum": round4(total),
        "avg": round4(avg),
        "min": round4(min(data)),
        "max": round4(max(data)),
        "stddev": round4(math.sqrt(variance)),
        "p50": round4(percentile_nearest_rank(data, 50)),
        "p90": round4(percentile_nearest_rank(data, 90)),
        "p95": round4(percentile_nearest_rank(data, 95)),
        "p99": round4(percentile_nearest_rank(data, 99)),
    }


def aggregate_values(values, aggregation="avg"):
    """把一个窗口内的样本压成一个数（列表卡片/告警求值共用）。"""
    aggregation = aggregation or "avg"
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"聚合口径必须是 {'/'.join(AGGREGATIONS)} 之一")
    data = [float(v) for v in values]
    if not data:
        return 0.0
    if aggregation == "sum":
        return round4(sum(data))
    if aggregation == "min":
        return round4(min(data))
    if aggregation == "max":
        return round4(max(data))
    if aggregation == "count":
        return len(data)
    if aggregation == "first":
        return round4(data[0])
    if aggregation == "last":
        return round4(data[-1])
    if aggregation.startswith("p"):
        return round4(percentile_nearest_rank(data, float(aggregation[1:])))
    return round4(sum(data) / len(data))


def metric_queryset(service, metric_name, since, until):
    """按 (服务, 指标名, 时间范围) 取指标点，统一按时间升序。

    先按服务+名字定位 MetricDef 再取点，比 ``metric__name`` 直接 join
    更快命中 (metric, timestamp) 联合索引；同名指标在多个服务下存在时
    也不会串数据。
    """
    from observability.models import MetricDef as _MetricDef  # 局部别名，避免名字歧义

    metric = _MetricDef.objects.filter(service=service, name=metric_name).first()
    if metric is None:
        return _MetricDef.objects.none(), None
    qs = MetricPoint.objects.filter(metric=metric, timestamp__gte=since,
                                    timestamp__lt=until).order_by("timestamp")
    return qs, metric


def metric_values(service, metric_name, since, until, limit=MAX_POINTS_SCAN):
    """取窗口内的指标值序列（按时间升序，超出上限时截断并保持顺序）。"""
    qs, metric = metric_queryset(service, metric_name, since, until)
    if metric is None:
        return [], None
    rows = list(qs.values_list("value", flat=True)[:limit])
    return rows, metric


def metric_series(service, metric_name, since, until, limit=MAX_POINTS_SCAN):
    """取窗口内的 (时间, 值) 序列，供分桶/降采样使用。"""
    qs, metric = metric_queryset(service, metric_name, since, until)
    if metric is None:
        return [], None
    rows = list(qs.values_list("timestamp", "value")[:limit])
    return rows, metric


def metric_point_filter(points, labels):
    """按标签子集过滤点：只要求传入的键值全部匹配（AND），便于多维下钻。"""
    if not labels:
        return list(points)
    wanted = {str(k): str(v) for k, v in labels.items()}
    out = []
    for point in points:
        actual = {str(k): str(v) for k, v in (point.labels or {}).items()}
        if all(actual.get(k) == v for k, v in wanted.items()):
            out.append(point)
    return out


# ---------------------------------------------------------------------------
# 3. 时间序列分桶与降采样
# ---------------------------------------------------------------------------


def _as_point(row):
    """兼容 (timestamp, value) 元组与带属性的对象（MetricPoint）。"""
    if isinstance(row, tuple):
        return row[0], float(row[1])
    return row.timestamp, float(row.value)


def choose_bucket_seconds(since, until, target_buckets=60):
    """按窗口长度与目标桶数选一个「整齐」的桶宽（秒）。

    取 1/5/10/30 秒、分钟、小时的阶梯，保证返回的桶边界在人类可读的
    时间点上，前端横轴不会出现 37 秒这种诡异刻度。
    """
    span = max((until - since).total_seconds(), 1.0)
    target = max(target_buckets, MIN_BUCKETS)
    raw = span / target
    steps = [1, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600,
             7200, 10800, 21600, 43200, 86400, 172800, 604800]
    for step in steps:
        if step >= raw:
            return step
    return steps[-1]


def bucketize(rows, bucket_seconds, since=None, until=None, aggregation="avg",
              fill_empty=False):
    """把 (时间, 值) 序列按固定宽度分桶并聚合。

    - 桶边界按 since（缺省取第一条数据）对齐，保证多次请求的桶边界一致；
    - ``fill_empty=True`` 时补空桶（value=None），前端画图不会把断点连成
      一条假的直线；
    - 聚合口径支持 avg/sum/min/max/count/first/last/pXX。
    """
    bucket_seconds = max(int(bucket_seconds or 60), 1)
    data = [_as_point(r) for r in rows]
    if not data:
        return []
    anchor = since or min(ts for ts, _ in data)
    anchor_epoch = int(anchor.timestamp())
    buckets = OrderedDict()
    for ts, value in data:
        index = (int(ts.timestamp()) - anchor_epoch) // bucket_seconds
        buckets.setdefault(index, []).append(value)

    if fill_empty and until is not None:
        total_buckets = int((until - anchor).total_seconds() // bucket_seconds) + 1
        total_buckets = clamp(total_buckets, MIN_BUCKETS, MAX_BUCKETS * 4)
        for index in range(total_buckets):
            buckets.setdefault(index, [])

    out = []
    for index in sorted(buckets):
        start = anchor + timedelta(seconds=index * bucket_seconds)
        values = buckets[index]
        if not values:
            out.append({
                "start": iso(start),
                "end": iso(start + timedelta(seconds=bucket_seconds)),
                "value": None,
                "count": 0,
            })
            continue
        out.append({
            "start": iso(start),
            "end": iso(start + timedelta(seconds=bucket_seconds)),
            "value": aggregate_values(values, aggregation),
            "count": len(values),
        })
    return out


def downsample(points, max_points=120, aggregation="avg"):
    """降采样：把相邻的若干点合成一个点，保留趋势但控制点数。

    合并而不是「隔 N 个取一个」，是因为后者会丢掉尖峰；观测图上最不能
    接受的就是「把故障尖峰抽没了」。
    """
    max_points = max(int(max_points or 120), 2)
    data = list(points)
    if len(data) <= max_points:
        return data
    group_size = int(math.ceil(len(data) / float(max_points)))
    out = []
    for start in range(0, len(data), group_size):
        chunk = data[start:start + group_size]
        if isinstance(chunk[0], dict):
            values = [c.get("value") for c in chunk if c.get("value") is not None]
            merged = dict(chunk[0])
            merged["value"] = aggregate_values(values, aggregation) if values else None
            merged["count"] = sum(int(c.get("count") or 0) for c in chunk)
            out.append(merged)
        else:
            values = [_as_point(c)[1] for c in chunk]
            out.append(aggregate_values(values, aggregation))
    return out


def timeseries(service, metric_name, since, until, bucket_seconds=None,
               aggregation="avg", fill_empty=False, max_points=240):
    """时间序列快捷入口：取数 → 分桶 →（可选）降采样。"""
    rows, metric = metric_series(service, metric_name, since, until)
    if metric is None:
        return {"metric": metric_name, "unit": "", "points": [], "bucket_seconds": 0,
                "count": 0, "summary": summarize([]), "missing": True}
    bucket_seconds = int(bucket_seconds or choose_bucket_seconds(since, until))
    buckets = bucketize(rows, bucket_seconds, since=since, until=until,
                        aggregation=aggregation, fill_empty=fill_empty)
    buckets = downsample(buckets, max_points=max_points, aggregation=aggregation)
    return {
        "metric": metric.name,
        "unit": metric.unit,
        "metric_type": metric.metric_type,
        "bucket_seconds": bucket_seconds,
        "aggregation": aggregation,
        "points": buckets,
        "count": sum(int(b.get("count") or 0) for b in buckets),
        "summary": summarize([v for _, v in rows]),
        "missing": False,
    }


# ---------------------------------------------------------------------------
# 4. SLO 计算
# ---------------------------------------------------------------------------


def slo_metric_names(slo):
    """SLO 的计算口径：允许每个 SLO 绑定自己的指标名，缺省走平台约定。"""
    cfg = slo.metrics or {}
    return {
        "total": cfg.get("total") or DEFAULT_TOTAL_METRIC,
        "error": cfg.get("error") or DEFAULT_ERROR_METRIC,
        "latency": cfg.get("latency") or DEFAULT_LATENCY_METRIC,
    }


def slo_allowed_error_pct(slo):
    """允许的错误率（百分数）。

    下限 0.001% 而不是 0：目标 100% 的 SLO 在真实系统里必然 0 预算，
    燃烧率会变成除零。用极小的下限表达「预算趋近于 0」。
    """
    return max(100.0 - float(slo.target_pct or 0), 0.001)


def compute_slo_counts(slo, since, until):
    """按 SLO 类型统计总请求/好请求/坏请求。

    - availability / error_rate：从 requests_total 与 errors_total 两个计数器
      求和；若服务只上报了延迟指标，则退化为「延迟样本数 = 总请求」，
      bad 由超出阈值的样本数决定（对没有独立错误计数器的服务更实用）。
    - latency：延迟样本中低于阈值的比例。
    """
    names = slo_metric_names(slo)
    total_values, _ = metric_values(slo.service, names["total"], since, until)
    error_values, _ = metric_values(slo.service, names["error"], since, until)
    latency_values, _ = metric_values(slo.service, names["latency"], since, until)

    if slo.slo_type == "latency":
        threshold = float(slo.latency_threshold_ms or 0)
        if threshold <= 0:
            raise ValueError("延迟类 SLO 必须配置大于 0 的延迟阈值")
        samples = latency_values or total_values
        if not samples:
            raise ValueError("窗口内没有延迟指标数据，无法计算 SLO")
        total = len(samples)
        good = sum(1 for v in samples if float(v) <= threshold)
        return {"total": total, "good": good, "bad": total - good,
                "threshold_ms": threshold, "source": "latency_samples"}

    total = int(round(sum(float(v) for v in total_values))) if total_values else 0
    bad = int(round(sum(float(v) for v in error_values))) if error_values else 0
    if total <= 0 and latency_values:
        # 退化路径：没有请求计数器，用延迟样本数当总请求
        total = len(latency_values)
        bad = bad or 0
    if total <= 0:
        raise ValueError("窗口内没有请求指标数据，无法计算 SLO")
    bad = max(0, min(bad, total))
    return {"total": total, "good": total - bad, "bad": bad,
            "threshold_ms": 0, "source": "counters"}


def compute_slo(slo, since, until):
    """计算一个 SLO 在 [since, until) 的达成率与燃烧率。"""
    if since >= until:
        raise ValueError("窗口开始时间必须早于结束时间")
    counts = compute_slo_counts(slo, since, until)
    total, good, bad = counts["total"], counts["good"], counts["bad"]
    attainment = good / float(total) * 100.0
    error_rate = bad / float(total) * 100.0
    allowed = slo_allowed_error_pct(slo)
    burn = error_rate / allowed if allowed > 0 else 0.0
    return {
        "slo_id": slo.id,
        "name": slo.name,
        "slo_type": slo.slo_type,
        "service_id": slo.service_id,
        "target_pct": round4(slo.target_pct),
        "window_days": slo.window_days,
        "since": iso(since),
        "until": iso(until),
        "window_hours": round4((until - since).total_seconds() / 3600.0),
        "total_requests": total,
        "good_requests": good,
        "bad_requests": bad,
        "attainment_pct": round4(attainment),
        "error_rate_pct": round4(error_rate),
        "allowed_error_pct": round4(allowed),
        "burn_rate": round4(burn),
        "met": attainment >= float(slo.target_pct),
        "latency_threshold_ms": counts["threshold_ms"],
        "source": counts["source"],
    }


def default_slo_window(slo, now=None):
    """SLO 的默认计算窗口：按自然日对齐、长度为 window_days。

    为什么按自然日对齐而不是「截止到当前时刻」：计算接口要可重复调用
    （同一窗口重复计算只能更新同一条 SloWindow，而不是每次多出一条快照），
    误差在秒级的 now 会让 (slo, start_at, end_at) 唯一约束永远命中不了。
    对齐到「今天结束」也让预算周期与日历一致，复盘时口径可解释。
    """
    now = now or timezone.now()
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return end - timedelta(days=max(int(slo.window_days or 1), 1)), end


def record_slo_window(slo, actor, since=None, until=None):
    """计算并落库窗口快照（同一窗口重复计算走更新，不产生重复行）。"""
    if since is None or until is None:
        since, until = default_slo_window(slo)
    result = compute_slo(slo, since, until)
    with transaction.atomic():
        window, _created = SloWindow.objects.update_or_create(
            slo=slo, start_at=since, end_at=until,
            defaults={
                "owner": actor,
                "attainment_pct": result["attainment_pct"],
                "total_requests": result["total_requests"],
                "good_requests": result["good_requests"],
                "bad_requests": result["bad_requests"],
                "burn_rate": result["burn_rate"],
                "met": result["met"],
            },
        )
        budget = record_error_budget(slo, actor, since, until, result)
    result["window_id"] = window.id
    result["budget_id"] = budget.id
    return result


def recent_window(slo):
    """取最近一次已落库的窗口快照；没有则返回 None（列表页避免现算）。"""
    return slo.windows.order_by("-start_at").first()


def slo_status_snapshot(slo):
    """列表/总览用的轻量快照：优先用落库窗口，缺数据时标记 unknown。"""
    window = recent_window(slo)
    if window is None:
        return {
            "slo_id": slo.id, "name": slo.name, "service_id": slo.service_id,
            "slo_type": slo.slo_type, "target_pct": round4(slo.target_pct),
            "attainment_pct": None, "burn_rate": None, "met": None,
            "total_requests": 0, "bad_requests": 0, "updated_at": None,
            "state": "unknown",
        }
    state = "met" if window.met else "breached"
    return {
        "slo_id": slo.id, "name": slo.name, "service_id": slo.service_id,
        "slo_type": slo.slo_type, "target_pct": round4(slo.target_pct),
        "attainment_pct": round4(window.attainment_pct),
        "burn_rate": round4(window.burn_rate),
        "met": window.met, "total_requests": window.total_requests,
        "bad_requests": window.bad_requests,
        "updated_at": iso(window.updated_at), "state": state,
    }


# ---------------------------------------------------------------------------
# 5. 燃烧率与错误预算预测
# ---------------------------------------------------------------------------


def compute_burn_rate(slo, window_hours=1.0, now=None):
    """单窗口燃烧率 = 当前错误率 / 允许错误率。

    燃烧率 1 表示「按当前速度刚好把预算烧完」，14.4 表示「1 小时烧掉
    30 天预算的 2%」（即 30 天内会烧掉 14.4 倍预算）。
    """
    now = now or timezone.now()
    hours = max(float(window_hours), 1.0 / 60.0)
    since = now - timedelta(hours=hours)
    try:
        result = compute_slo(slo, since, now)
    except ValueError:
        return {"window": f"{hours:g}h", "window_hours": round4(hours),
                "burn_rate": None, "error_rate_pct": None, "insufficient_data": True}
    return {
        "window": f"{hours:g}h",
        "window_hours": round4(hours),
        "burn_rate": result["burn_rate"],
        "error_rate_pct": result["error_rate_pct"],
        "attainment_pct": result["attainment_pct"],
        "total_requests": result["total_requests"],
        "insufficient_data": False,
    }


def burn_rate_report(slo, now=None, windows=BURN_WINDOWS):
    """多窗口燃烧率：任一窗口超过阈值即判定为快烧/慢烧。

    单窗口容易被瞬时抖动误导，双窗口（短窗 + 长窗）同时超标才告警是
    业界成熟做法；这里把 1h/6h/3d 三个窗口都算出来，让前端展示趋势，
    并由 ``state`` 给出综合结论。
    """
    now = now or timezone.now()
    entries = []
    worst = None
    for label, hours, threshold in windows:
        entry = compute_burn_rate(slo, hours, now=now)
        # 对外统一用 BURN_WINDOWS 的短标签（1h/6h/3d）：72 小时写成 "72h"
        # 会与配置里的 "3d" 对不上，前端按 window 取值时找不到同一个窗口。
        entry["window"] = label
        entry["label"] = label
        entry["threshold"] = threshold
        if entry["insufficient_data"]:
            entry["state"] = "insufficient_data"
            entries.append(entry)
            continue
        burn = entry["burn_rate"] or 0.0
        if burn >= threshold:
            entry["state"] = "critical_burn"
        elif burn >= threshold / 2.0:
            entry["state"] = "elevated_burn"
        else:
            entry["state"] = "ok"
        entries.append(entry)
        if worst is None or burn > (worst["burn_rate"] or 0):
            worst = entry
    state = "insufficient_data"
    if worst is not None:
        state = worst["state"]
    elif entries:
        state = "insufficient_data"
    return {
        "slo_id": slo.id,
        "slo_name": slo.name,
        "target_pct": round4(slo.target_pct),
        "allowed_error_pct": round4(slo_allowed_error_pct(slo)),
        "state": state,
        "worst_window": worst["label"] if worst else None,
        "windows": entries,
        "generated_at": iso(now),
    }


def budget_period_code(since, until):
    """预算周期编码：用窗口日期区间，便于唯一约束与前端展示。"""
    return f"{since.date().isoformat()}~{until.date().isoformat()}"


def forecast_exhaustion(remaining, consumed_rate_per_day, now=None):
    """按当前消耗速率外推耗尽日。

    速率为 0 或预算已耗尽时返回 None / 当天，语义区分开：
    - 速率为 0 → 永不耗尽（None）
    - 剩余 <= 0 → already exhausted（返回今天，由 status 标 exhausted）
    """
    now = now or timezone.now()
    if remaining <= 0:
        return now.date()
    if not consumed_rate_per_day or consumed_rate_per_day <= 0:
        return None
    days = remaining / float(consumed_rate_per_day)
    if days > 3650:  # 十年以上视为「不会耗尽」，避免存入 9999 年这种脏日期
        return None
    return (now + timedelta(days=days)).date()


def build_error_budget(slo, since, until, result=None, now=None):
    """根据窗口结果生成预算结构（纯计算，不落库）。"""
    now = now or timezone.now()
    result = result or compute_slo(slo, since, until)
    total = float(result["total_requests"])
    allowed_ratio = slo_allowed_error_pct(slo) / 100.0
    total_allowed = total * allowed_ratio
    consumed = float(result["bad_requests"])
    remaining = max(total_allowed - consumed, 0.0)
    elapsed_days = days_between(since, min(until, now) if now < until else until)
    rate = consumed / elapsed_days
    projected = forecast_exhaustion(remaining, rate, now=now)
    used_ratio = consumed / total_allowed if total_allowed > 0 else (1.0 if consumed else 0.0)
    if remaining <= 0:
        status = "exhausted"
    elif used_ratio >= 0.8:
        status = "warning"
    else:
        status = "healthy"
    return {
        "slo_id": slo.id,
        "slo_name": slo.name,
        "period": budget_period_code(since, until),
        "window_start": iso(since),
        "window_end": iso(until),
        "total_allowed": round4(total_allowed),
        "consumed": round4(consumed),
        "remaining": round4(remaining),
        "used_pct": round4(clamp(used_ratio * 100.0, 0.0, 100.0)),
        "consumed_rate_per_day": round4(rate),
        "projected_exhaustion": projected.isoformat() if projected else None,
        "days_until_exhaustion": (round4(remaining / rate) if rate > 0 and remaining > 0 else None),
        "status": status,
        "status_label": {"healthy": "健康", "warning": "预警", "exhausted": "已耗尽"}[status],
        "attainment_pct": result["attainment_pct"],
        "target_pct": round4(slo.target_pct),
    }


def record_error_budget(slo, actor, since, until, result=None):
    """把预算快照写入 ErrorBudget（同一 SLO+周期只保留一条）。"""
    payload = build_error_budget(slo, since, until, result=result)
    projected = parse_date(payload["projected_exhaustion"]) if payload["projected_exhaustion"] else None
    with transaction.atomic():
        budget, _created = ErrorBudget.objects.update_or_create(
            slo=slo, period=payload["period"],
            defaults={
                "owner": actor,
                "total_allowed": payload["total_allowed"],
                "consumed": payload["consumed"],
                "remaining": payload["remaining"],
                "consumed_rate_per_day": payload["consumed_rate_per_day"],
                "projected_exhaustion": projected,
                "status": payload["status"],
            },
        )
    payload["budget_id"] = budget.id
    return budget


def budget_snapshot(slo, actor=None, now=None):
    """取（或在缺失时计算）当前 SLO 的预算快照。

    已有预算行但指标已经更新时，允许视图显式重算；列表/总览用存量行，
    避免每次打开页面都扫全量指标点。
    """
    since, until = default_slo_window(slo, now=now)
    budget = ErrorBudget.objects.filter(slo=slo, period=budget_period_code(since, until)).first()
    if budget is None and actor is not None:
        budget = record_error_budget(slo, actor, since, until)
    if budget is None:
        return None
    result = compute_slo(slo, since, until) if actor is None else None
    remaining_days = None
    if budget.consumed_rate_per_day and budget.consumed_rate_per_day > 0 and budget.remaining > 0:
        remaining_days = round4(budget.remaining / budget.consumed_rate_per_day)
    return {
        "budget_id": budget.id,
        "slo_id": slo.id,
        "slo_name": slo.name,
        "period": budget.period,
        "total_allowed": round4(budget.total_allowed),
        "consumed": round4(budget.consumed),
        "remaining": round4(budget.remaining),
        "consumed_rate_per_day": round4(budget.consumed_rate_per_day),
        "projected_exhaustion": budget.projected_exhaustion.isoformat()
        if budget.projected_exhaustion else None,
        "days_until_exhaustion": remaining_days,
        "status": budget.status,
        "attainment_pct": result["attainment_pct"] if result else None,
        "updated_at": iso(budget.updated_at),
    }


def budget_forecast(slo, days=30, now=None):
    """预算预测曲线：按当前速率线性外推未来 N 天的剩余额度。

    线性外推是最容易解释、也最少被误读的口径；指数平滑会给出「更准」
    但没人能复算的数字，复盘会议上反而不可信。
    """
    now = now or timezone.now()
    snapshot = budget_snapshot(slo, actor=None, now=now)
    if snapshot is None:
        return {"slo_id": slo.id, "slo_name": slo.name, "available": False,
                "reason": "尚无预算快照，请先计算 SLO 窗口", "points": []}
    rate = float(snapshot["consumed_rate_per_day"] or 0)
    remaining = float(snapshot["remaining"] or 0)
    total_allowed = float(snapshot["total_allowed"] or 0)
    points = []
    days = int(clamp(days, 1, 365))
    for offset in range(days + 1):
        value = max(remaining - rate * offset, 0.0)
        points.append({
            "day": (now + timedelta(days=offset)).date().isoformat(),
            "remaining": round4(value),
            "remaining_pct": round4(value / total_allowed * 100.0) if total_allowed else 0.0,
        })
    exhaustion_index = next((i for i, p in enumerate(points) if p["remaining"] <= 0), None)
    return {
        "slo_id": slo.id,
        "slo_name": slo.name,
        "available": True,
        "rate_per_day": round4(rate),
        "remaining": round4(remaining),
        "projected_exhaustion": snapshot["projected_exhaustion"],
        "days_until_exhaustion": snapshot["days_until_exhaustion"],
        "exhausted_in_days": exhaustion_index,
        "points": points,
    }


# ---------------------------------------------------------------------------
# 6. 告警表达式解析与规则求值
# ---------------------------------------------------------------------------


def parse_expression(text):
    """解析「指标名 比较符 数值」表达式，非法格式给出可操作的中文提示。"""
    match = EXPRESSION_RE.match(str(text or ""))
    if not match:
        raise ValueError("告警表达式格式应为「指标名 比较符 数值」，如 error_rate > 5")
    name, op, threshold = match.groups()
    return {"metric": name, "op": op, "threshold": float(threshold)}


def compare_value(value, op, threshold):
    """按比较符判定；未知比较符抛错（防止拼写错误静默为 False）。"""
    fn = COMPARE_OPS.get(op)
    if fn is None:
        raise ValueError(f"不支持的比较符: {op}")
    return fn(float(value), float(threshold))


def _slice_averages(rows, slices):
    """把窗口切成 slices 段，返回每段的平均值（空段返回 None）。"""
    data = [_as_point(r) for r in rows]
    if not data:
        return []
    start = min(ts for ts, _ in data)
    end = max(ts for ts, _ in data)
    span = max((end - start).total_seconds(), 1.0)
    buckets = defaultdict(list)
    for ts, value in data:
        offset = (ts - start).total_seconds() / span
        index = min(int(offset * slices), slices - 1)
        buckets[index].append(value)
    out = []
    for index in range(slices):
        values = buckets.get(index) or []
        out.append(round4(sum(values) / len(values)) if values else None)
    return out


def indicator_value(rule, since, until):
    """计算规则引用的指标在窗口内的值。

    返回 (value, samples, meta)；无数据时 value 为 None。伪指标（健康分、
    错误率、SLO 达成率、失败检查数）由平台实时推导，让告警不必依赖服务
    自己上报每一个派生指标。
    """
    meta = parse_expression(rule.expression)
    name = meta["metric"]
    if name == "health_score":
        checks = list(rule.service.health_checks.filter(enabled=True))
        score = health_score(checks)
        return score["score"], len(checks), {"type": "health_score",
                                             "detail": score["counts"]}
    if name == "check_failures":
        checks = rule.service.health_checks.filter(enabled=True)
        failed = checks.filter(status__in=("down", "degraded")).count()
        return failed, checks.count(), {"type": "check_failures"}
    if name == "error_rate":
        names = {"total": DEFAULT_TOTAL_METRIC, "error": DEFAULT_ERROR_METRIC}
        total_values, _ = metric_values(rule.service, names["total"], since, until)
        error_values, _ = metric_values(rule.service, names["error"], since, until)
        total = sum(float(v) for v in total_values)
        errors = sum(float(v) for v in error_values)
        if total <= 0:
            return None, 0, {"type": "error_rate"}
        return round4(errors / total * 100.0), len(total_values), {"type": "error_rate"}
    if name == "slo_attainment":
        slo = rule.service.slos.filter(status="active").first()
        if slo is None:
            return None, 0, {"type": "slo_attainment"}
        try:
            result = compute_slo(slo, since, until)
        except ValueError:
            return None, 0, {"type": "slo_attainment"}
        return result["attainment_pct"], result["total_requests"], {"type": "slo_attainment",
                                                                   "slo_id": slo.id}
    metric = MetricDef.objects.filter(service=rule.service, name=name).first()
    if metric is None:
        raise ValueError(f"告警表达式引用的指标不存在: {name}")
    rows = list(MetricPoint.objects.filter(metric=metric, timestamp__gte=since,
                                          timestamp__lt=until)
                .order_by("timestamp").values_list("timestamp", "value")[:MAX_POINTS_SCAN])
    if not rows:
        return None, 0, {"type": "metric", "metric_id": metric.id, "unit": metric.unit}
    values = [float(v) for _, v in rows]
    return round4(sum(values) / len(values)), len(values), {
        "type": "metric", "metric_id": metric.id, "unit": metric.unit,
    }


def evaluate_condition(rule, since, until):
    """判断「表达式在窗口内是否持续成立」。

    持续时间语义：把窗口切成最多 8 段，每段平均都满足比较符才算持续
    成立；样本少于段数时退化为整体平均，避免低频指标永远不触发。
    """
    meta = parse_expression(rule.expression)
    rows = []
    name = meta["metric"]
    if name not in PSEUDO_METRICS:
        metric = MetricDef.objects.filter(service=rule.service, name=name).first()
        if metric is None:
            raise ValueError(f"告警表达式引用的指标不存在: {name}")
        rows = list(MetricPoint.objects.filter(metric=metric, timestamp__gte=since,
                                              timestamp__lt=until)
                    .order_by("timestamp").values_list("timestamp", "value")
                    [:MAX_POINTS_SCAN])
    value, samples, info = indicator_value(rule, since, until)
    if value is None:
        return {"available": False, "sustained": False, "value": None,
                "samples": 0, "slices": [], "meta": meta, "info": info}

    duration = max(int(rule.duration_seconds or 0), 0)
    slices_wanted = 0 if duration <= 0 else int(clamp(duration // 60, 2, 8))
    slices = []
    sustained = compare_value(value, meta["op"], meta["threshold"])
    if rows and slices_wanted >= 2 and len(rows) >= slices_wanted:
        slices = _slice_averages(rows, slices_wanted)
        filled = [s for s in slices if s is not None]
        if len(filled) >= 2:
            sustained = all(compare_value(s, meta["op"], meta["threshold"]) for s in filled)
    return {
        "available": True,
        "sustained": bool(sustained),
        "value": value,
        "samples": samples,
        "slices": slices,
        "meta": meta,
        "info": info,
    }


def active_silence(rule, now=None):
    """取当前生效的静默窗口（顺带把过期静默标成 expired）。"""
    now = now or timezone.now()
    Silence.objects.filter(rule=rule, status="active", end_at__lt=now).update(status="expired")
    return Silence.objects.filter(rule=rule, status="active",
                                  start_at__lte=now, end_at__gte=now).first()


def summarize_event_value(rule, value):
    """生成事件摘要：把「表达式 + 实际值 + 服务」说清楚，值班时不用再点开。"""
    meta = parse_expression(rule.expression)
    unit = ""
    metric = MetricDef.objects.filter(service=rule.service, name=meta["metric"]).first()
    if metric is not None:
        unit = metric.unit or ""
    return (f"{rule.service.name} {meta['metric']}={value}{unit} "
            f"{meta['op']} {meta['threshold']}{unit}")


def evaluate_rule(rule, actor=None, now=None, persist=True):
    """求值单条告警规则：触发 / 抑制重复 / 静默 / 恢复。

    返回结构里的 ``state`` 是唯一结论（firing/resolved/suppressed/
    cooldown/disabled/no_data），视图直接透传给前端，不再二次判断。
    """
    now = now or timezone.now()
    if not rule.enabled or rule.status == "disabled":
        return {"rule_id": rule.id, "rule_name": rule.name, "evaluated": False,
                "state": "disabled", "reason": "告警规则已停用"}
    duration = max(int(rule.duration_seconds or 0), 60)
    since = now - timedelta(seconds=duration)
    try:
        condition = evaluate_condition(rule, since, now)
    except ValueError as exc:
        return {"rule_id": rule.id, "rule_name": rule.name, "evaluated": False,
                "state": "error", "reason": str(exc)}

    base = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "service_id": rule.service_id,
        "severity": rule.severity,
        "expression": rule.expression,
        "value": condition["value"],
        "samples": condition["samples"],
        "sustained": condition["sustained"],
        "window_start": iso(since),
        "window_end": iso(now),
        "evaluated": True,
    }
    if not condition["available"]:
        base.update({"state": "no_data", "reason": "窗口内没有指标数据"})
        return base

    open_event = rule.events.filter(status__in=("firing", "suppressed")).order_by("-started_at").first()
    silence = active_silence(rule, now=now)

    if condition["sustained"]:
        if open_event is not None:
            if persist:
                open_event.value = condition["value"]
                open_event.status = "suppressed" if silence else "firing"
                open_event.silenced_until = silence.end_at if silence else None
                open_event.summary = summarize_event_value(rule, condition["value"])
                open_event.save(update_fields=["value", "status", "silenced_until",
                                               "summary", "updated_at"])
            base.update({"state": "suppressed" if silence else "firing",
                         "event_id": open_event.id, "deduplicated": True,
                         "suppressed_by": "silence" if silence else None})
            return base

        cooldown = int(rule.cooldown_seconds or 0)
        if cooldown > 0 and rule.last_fired_at and (now - rule.last_fired_at).total_seconds() < cooldown:
            base.update({"state": "cooldown", "event_id": None,
                         "reason": f"处于抑制间隔内（{cooldown} 秒），不重复触发"})
            return base

        if persist:
            with transaction.atomic():
                event = AlertEvent.objects.create(
                    owner=actor or rule.owner,
                    rule=rule,
                    service=rule.service,
                    status="suppressed" if silence else "firing",
                    started_at=now,
                    value=condition["value"],
                    summary=summarize_event_value(rule, condition["value"]),
                    owner_name=rule.service.owner_name,
                    silenced_until=silence.end_at if silence else None,
                )
                rule.last_fired_at = now
                rule.save(update_fields=["last_fired_at", "updated_at"])
            base["event_id"] = event.id
        else:
            base["event_id"] = None
        base.update({"state": "suppressed" if silence else "firing",
                     "deduplicated": False,
                     "suppressed_by": "silence" if silence else None})
        return base

    # 条件不成立：如有未恢复事件则关闭（恢复是告警生命周期的一部分）
    if open_event is not None:
        if persist:
            with transaction.atomic():
                open_event.status = "resolved"
                open_event.ended_at = now
                open_event.value = condition["value"]
                open_event.save(update_fields=["status", "ended_at", "value", "updated_at"])
        base.update({"state": "resolved", "event_id": open_event.id, "deduplicated": False})
        return base

    base.update({"state": "ok", "event_id": None})
    return base


def evaluate_rules(user=None, service=None, now=None, limit=500):
    """批量求值：返回每条规则的结论与汇总（供「测试求值」与巡检接口用）。"""
    now = now or timezone.now()
    qs = AlertRule.objects.select_related("service", "owner").filter(enabled=True)
    if service is not None:
        qs = qs.filter(service=service)
    if user is not None:
        qs = scope_queryset(qs, user)
    rules = list(qs.order_by("id")[:limit])
    items = [evaluate_rule(rule, actor=user, now=now) for rule in rules]
    counter = defaultdict(int)
    for item in items:
        counter[item["state"]] += 1
    return {
        "evaluated_at": iso(now),
        "total": len(items),
        "by_state": dict(counter),
        "firing": counter.get("firing", 0),
        "suppressed": counter.get("suppressed", 0),
        "resolved": counter.get("resolved", 0),
        "no_data": counter.get("no_data", 0),
        "items": items,
    }


def acknowledge_alert_event(event, actor=None, note=""):
    """确认告警事件：记录确认人与时间，不改变触发状态（告警仍需恢复）。"""
    now = timezone.now()
    event.acknowledged_at = event.acknowledged_at or now
    event.acknowledged_by = getattr(actor, "username", "") or event.acknowledged_by
    if note:
        event.summary = (event.summary + f" | 确认备注: {note}")[:300]
    event.save(update_fields=["acknowledged_at", "acknowledged_by", "summary", "updated_at"])
    return event


def resolve_alert_event(event, note=""):
    """手动解决告警事件（例如人工确认指标已恢复但规则还没到下一个求值周期）。"""
    if event.status == "resolved":
        raise ValueError("该告警事件已恢复，无需重复解决")
    event.status = "resolved"
    event.ended_at = event.ended_at or timezone.now()
    if note:
        event.summary = (event.summary + f" | 解决备注: {note}")[:300]
    event.save(update_fields=["status", "ended_at", "summary", "updated_at"])
    return event


def silence_rule(rule, actor, minutes=60, reason="", now=None):
    """给规则创建静默窗口，并把当前未恢复事件一并标记为 suppressed。"""
    now = now or timezone.now()
    minutes = int(clamp(int(minutes or 0), 1, 60 * 24 * 30))
    with transaction.atomic():
        silence = Silence.objects.create(
            owner=actor,
            rule=rule,
            start_at=now,
            end_at=now + timedelta(minutes=minutes),
            reason=reason[:300],
            created_by=actor,
            status="active",
        )
        rule.events.filter(status="firing").update(status="suppressed", silenced_until=silence.end_at)
    return silence


# ---------------------------------------------------------------------------
# 7. 事故状态机与 MTTA/MTTR
# ---------------------------------------------------------------------------


def incident_status_label(status):
    from observability.models import INCIDENT_STATUS_LABELS

    return INCIDENT_STATUS_LABELS.get(status, status)


def ensure_transition_allowed(current, target):
    """校验事故状态流转是否合法；非法流转抛中文错误（视图层转 400）。"""
    if target not in INCIDENT_STATUS:
        raise ValueError(f"未知的事故状态: {target}")
    if current == target:
        raise ValueError(f"事故已处于「{incident_status_label(current)}」状态")
    allowed = INCIDENT_TRANSITIONS.get(current, ())
    if not allowed:
        # 终态（已复盘）没有下一步：报「已处于终态」比报「不能直接变更为 X」更
        # 贴近用户意图，也避免前端把终态事故当成流程配置错误。
        raise ValueError(
            f"事故已处于「{incident_status_label(current)}」状态，不能再变更")
    if target not in allowed:
        allowed_text = " / ".join(incident_status_label(s) for s in allowed) or "无（终态）"
        raise ValueError(
            f"事故状态不能从「{incident_status_label(current)}」直接变更为"
            f"「{incident_status_label(target)}」，合法的下一步是：{allowed_text}"
        )
    return True


def transition_incident(incident, target, actor, note="", now=None):
    """执行一次合法的状态流转：改状态 + 打时间点 + 写时间线，全部原子完成。

    时间点与时间线必须与状态同事务：否则会出现「状态已解决但时间线缺失」，
    复盘时无法解释 MTTR 的起止。
    """
    now = now or timezone.now()
    current = incident.status
    ensure_transition_allowed(current, target)
    timestamp_field = INCIDENT_TIMESTAMP_FIELDS.get(target)
    with transaction.atomic():
        incident.status = target
        fields = ["status", "updated_at"]
        if timestamp_field:
            setattr(incident, timestamp_field, now)
            fields.append(timestamp_field)
        if target == "resolved":
            incident.ended_at = now
            fields.append("ended_at")
        incident.save(update_fields=fields)
        IncidentUpdate.objects.create(
            owner=actor,
            incident=incident,
            author=actor,
            content=note or INCIDENT_ACTION_LABELS.get(target, target),
            status_change=f"{current}->{target}",
            at=now,
        )
    return incident


def add_incident_update(incident, actor, content, at=None):
    """追加一条纯文本时间线记录（不改变状态）。"""
    at = at or timezone.now()
    return IncidentUpdate.objects.create(
        owner=actor,
        incident=incident,
        author=actor,
        content=content,
        status_change="",
        at=at,
    )


def incident_mtta_seconds(incident):
    """MTTA：从事故发生到被确认的秒数；未确认返回 None。"""
    return seconds_between(incident.started_at, incident.acknowledged_at)


def incident_mttr_seconds(incident):
    """MTTR：从事故发生到解决的秒数；未解决返回 None。"""
    end = incident.resolved_at or incident.ended_at
    return seconds_between(incident.started_at, end)


def _average(values):
    values = [v for v in values if v is not None]
    return round4(sum(values) / len(values)) if values else None


def _median(values):
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    mid = len(data) // 2
    if len(data) % 2:
        return round4(data[mid])
    return round4((data[mid - 1] + data[mid]) / 2.0)


def mtta_mttr_stats(incidents):
    """MTTA/MTTR 汇总：均值/中位数/最大值 + 按严重度分组。"""
    incidents = list(incidents)
    mtta = [incident_mtta_seconds(i) for i in incidents]
    mttr = [incident_mttr_seconds(i) for i in incidents]
    resolved = [i for i in incidents if incident_mttr_seconds(i) is not None]
    by_severity = {}
    for severity in INCIDENT_SEVERITIES:
        group = [i for i in incidents if i.severity == severity]
        if not group:
            continue
        by_severity[severity] = {
            "total": len(group),
            "mtta_seconds": _average([incident_mtta_seconds(i) for i in group]),
            "mttr_seconds": _average([incident_mttr_seconds(i) for i in group]),
        }
    return {
        "total_incidents": len(incidents),
        "acknowledged": sum(1 for i in incidents if i.acknowledged_at),
        "resolved": len(resolved),
        "mtta_seconds": _average(mtta),
        "mtta_median_seconds": _median(mtta),
        "mtta_max_seconds": round4(max([v for v in mtta if v is not None])) if any(
            v is not None for v in mtta) else None,
        "mttr_seconds": _average(mttr),
        "mttr_median_seconds": _median(mttr),
        "mttr_max_seconds": round4(max([v for v in mttr if v is not None])) if any(
            v is not None for v in mttr) else None,
        "by_severity": by_severity,
    }


def incident_timeline(incident, limit=200):
    """事故时间线：事故创建 + 所有更新记录，按时间升序。

    创建记录在登记时已经写成一条 ``->open`` 的更新，这里只在缺失时补一条
    虚拟创建事件（老数据/直接落库的事故），避免同一次登记出现两条重复节点。
    """
    updates = list(incident.updates.select_related("author")
                   .order_by("at", "id")[:limit])
    events = []
    if not any(u.status_change == "->open" for u in updates):
        events.append({
            "kind": "created",
            "at": iso(incident.started_at),
            "author": incident.owner_name or "",
            "content": f"事故登记：{incident.title}",
            "status_change": f"->{incident.status}" if incident.status == "open" else "",
        })
    for update in updates:
        events.append({
            "id": update.id,
            "kind": "update",
            "at": iso(update.at),
            "author": getattr(update.author, "nickname", "") or getattr(
                update.author, "username", ""),
            "content": update.content,
            "status_change": update.status_change,
        })
    events.sort(key=lambda e: e["at"] or "")
    return events


# ---------------------------------------------------------------------------
# 8. 健康评分与健康总览
# ---------------------------------------------------------------------------


def health_score(checks):
    """多检查加权健康分：down 扣满、degraded 扣 35%、unknown 扣 20%。

    权重取检查自身的 ``weight``，让「核心链路探活」比「边缘探活」更有
    话语权；没有任何启用检查时返回 100 分并标记 no_checks，避免把一个
    还没接监控的服务误判为故障。
    """
    checks = [c for c in checks if getattr(c, "enabled", True)]
    counts = {status: 0 for status in HEALTH_STATUS}
    if not checks:
        return {
            "score": 100.0, "grade": "A", "counts": counts,
            "total_weight": 0, "penalty": 0.0, "no_checks": True,
            "worst": "unknown", "checks": [],
        }
    total_weight = 0.0
    penalty = 0.0
    worst = "up"
    details = []
    for check in checks:
        status = check.status if check.status in HEALTH_PENALTY else "unknown"
        weight = max(int(check.weight or 1), 1)
        counts[status] = counts.get(status, 0) + 1
        total_weight += weight
        penalty += weight * HEALTH_PENALTY[status]
        if HEALTH_PENALTY[status] > HEALTH_PENALTY.get(worst, 0):
            worst = status
        details.append({
            "check_id": check.id,
            "check_type": check.check_type,
            "status": status,
            "weight": weight,
            "last_checked_at": iso(check.last_checked_at),
            "last_error": check.last_error,
        })
    ratio = penalty / total_weight if total_weight else 0.0
    score = clamp(100.0 * (1.0 - ratio), 0.0, 100.0)
    grade = next(label for bound, label in HEALTH_GRADES if score >= bound)
    return {
        "score": round4(score),
        "grade": grade,
        "counts": counts,
        "total_weight": round4(total_weight),
        "penalty": round4(penalty),
        "no_checks": False,
        "worst": worst,
        "checks": details,
    }


def service_status_from(score, open_critical, has_down_check):
    """把健康分与告警/检查结论归并成服务状态。

    优先级：有 down 检查 → down；健康分 < 75 或存在未恢复 critical 告警
    → degraded；否则 healthy。评审时这条规则可以直接对着页面解释。
    """
    if has_down_check:
        return "down"
    if open_critical:
        return "degraded"
    if score is not None and score < 75:
        return "degraded"
    if score is not None and score < 90:
        return "degraded"
    return "healthy"


def service_health(service, include_checks=True):
    """单个服务的健康总览：评分 + 检查分布 + 未恢复告警 + SLO 概要。"""
    checks = list(service.health_checks.filter(enabled=True))
    score = health_score(checks)
    open_events = service.alert_events.filter(status__in=("firing", "suppressed"))
    # AlertEvent 没有 severity 列：严重度是规则的属性，按规则反查统计
    open_critical = AlertEvent.objects.filter(
        service=service, status__in=("firing", "suppressed"),
        rule__severity="critical").count()
    has_down = score["counts"].get("down", 0) > 0
    status = service_status_from(score["score"], open_critical, has_down)
    slos = list(service.slos.filter(status="active"))
    slo_rows = [slo_status_snapshot(slo) for slo in slos]
    attained = [row for row in slo_rows if row["attainment_pct"] is not None]
    return {
        "service_id": service.id,
        "name": service.name,
        "slug": service.slug,
        "level": service.level,
        "team": service.team,
        "owner_name": service.owner_name,
        "status": status,
        "declared_status": service.status,
        "health_score": score["score"],
        "grade": score["grade"],
        "checks": score["counts"] if include_checks else None,
        "total_checks": len(checks),
        "open_alerts": open_events.count(),
        "critical_alerts": open_critical,
        "slo_total": len(slos),
        "slo_attainment_avg": _average([row["attainment_pct"] for row in attained]),
        "slos": slo_rows,
        "worst_check": score["worst"],
    }


def services_health_overview(services):
    """批量健康总览：一次取齐检查/告警/SLO，避免 N+1。"""
    from observability.models import Slo  # 局部导入避免顶层循环

    services = list(services)
    ids = [s.id for s in services]
    checks_by_service = defaultdict(list)
    for check in HealthCheck.objects.filter(service_id__in=ids, enabled=True):
        checks_by_service[check.service_id].append(check)
    alerts_by_service = defaultdict(int)
    critical_by_service = defaultdict(int)
    for row in (AlertEvent.objects.filter(service_id__in=ids,
                                         status__in=("firing", "suppressed"))
                .values("service_id", "rule__severity").annotate(total=Count("id"))):
        alerts_by_service[row["service_id"]] += row["total"]
        if row["rule__severity"] == "critical":
            critical_by_service[row["service_id"]] += row["total"]
    slos_by_service = defaultdict(list)
    for slo in Slo.objects.filter(service_id__in=ids, status="active"):
        slos_by_service[slo.service_id].append(slo)

    rows = []
    for service in services:
        score = health_score(checks_by_service.get(service.id, []))
        has_down = score["counts"].get("down", 0) > 0
        status = service_status_from(score["score"], critical_by_service.get(service.id, 0), has_down)
        snapshots = [slo_status_snapshot(slo) for slo in slos_by_service.get(service.id, [])]
        attained = [s["attainment_pct"] for s in snapshots if s["attainment_pct"] is not None]
        rows.append({
            "service_id": service.id,
            "name": service.name,
            "slug": service.slug,
            "level": service.level,
            "team": service.team,
            "owner_name": service.owner_name,
            "status": status,
            "declared_status": service.status,
            "health_score": score["score"],
            "grade": score["grade"],
            "checks": score["counts"],
            "total_checks": len(checks_by_service.get(service.id, [])),
            "open_alerts": alerts_by_service.get(service.id, 0),
            "critical_alerts": critical_by_service.get(service.id, 0),
            "slo_total": len(snapshots),
            "slo_met": sum(1 for s in snapshots if s["met"]),
            "slo_attainment_avg": _average(attained),
        })
    distribution = defaultdict(int)
    for row in rows:
        distribution[row["status"]] += 1
    return {
        "total": len(rows),
        "by_status": dict(distribution),
        "avg_health_score": _average([r["health_score"] for r in rows]),
        "critical_services": [r for r in rows if r["level"] == "P0" and r["status"] != "healthy"],
        "items": rows,
    }


def health_check_runs_summary(check, since=None, until=None):
    """单检查的执行历史摘要：可用率、平均延迟、最近状态。"""
    now = timezone.now()
    until = until or now
    since = since or (until - timedelta(days=1))
    runs = list(check.runs.filter(checked_at__gte=since, checked_at__lt=until)
                .order_by("checked_at"))
    total = len(runs)
    up = sum(1 for r in runs if r.status == "up")
    return {
        "check_id": check.id,
        "since": iso(since),
        "until": iso(until),
        "total": total,
        "up": up,
        "down": sum(1 for r in runs if r.status == "down"),
        "degraded": sum(1 for r in runs if r.status == "degraded"),
        "availability_pct": round4(up / total * 100.0) if total else None,
        "avg_latency_ms": _average([r.latency_ms for r in runs]),
        "max_latency_ms": round4(max([r.latency_ms for r in runs])) if runs else None,
        "last_status": runs[-1].status if runs else None,
        "last_checked_at": iso(runs[-1].checked_at) if runs else None,
    }


def execute_health_check(check, actor, succeed=None, latency_ms=None, error="", detail=None):
    """执行一次健康检查并落库。

    本应用不联网、不真的发 HTTP 请求（约束 7：模拟真实 agent）。这里的
    「执行」是把 agent 上报/推断的结果规整成一次探活记录：
    - 显式传入 succeed 时按传入结果记录（agent 上报场景）；
    - 未传入时按配置里的 ``expect_status`` 与当前时间推断（本地演示场景）。
    """
    now = timezone.now()
    if succeed is None:
        # 未显式给出结果：按配置的 expect 判定，默认视为正常
        expected = (check.config or {}).get("expect_status", "up")
        succeed = expected in ("up", "ok", True, 200, "200")
    status = "up" if succeed else "down"
    latency = round4(latency_ms if latency_ms is not None else 0.0)
    timeout_ms = float(check.timeout_seconds or 5) * 1000.0
    if latency > timeout_ms:
        status = "degraded"
        error = error or f"耗时 {latency}ms 超过超时阈值 {timeout_ms}ms"
    with transaction.atomic():
        run = HealthCheckRun.objects.create(
            owner=actor,
            health_check=check,
            status=status,
            latency_ms=latency,
            error=error[:300],
            detail=detail or {},
            checked_at=now,
        )
        check.status = status
        check.last_checked_at = now
        check.last_error = error[:300]
        if status == "down":
            check.consecutive_failures = int(check.consecutive_failures or 0) + 1
        else:
            check.consecutive_failures = 0
        check.save(update_fields=["status", "last_checked_at", "last_error",
                                  "consecutive_failures", "updated_at"])
    return run


# ---------------------------------------------------------------------------
# 9. 依赖图与故障影响分析
# ---------------------------------------------------------------------------


def dependency_graph(services=None, edges=None):
    """构造依赖图：节点 + 边 + 根（无上游）/叶（无下游）。

    节点里带 ``dependency_count``（出边数），前端画图可以不查第二遍。
    """
    services = list(services if services is not None else Service.objects.all())
    service_map = {s.id: s for s in services}
    if edges is None:
        edges = Dependency.objects.filter(upstream_id__in=service_map.keys(),
                                          downstream_id__in=service_map.keys())
    edges = list(edges)
    out_degree = defaultdict(int)
    in_degree = defaultdict(int)
    edge_rows = []
    for edge in edges:
        out_degree[edge.upstream_id] += 1
        in_degree[edge.downstream_id] += 1
        edge_rows.append({
            "id": edge.id,
            "upstream_id": edge.upstream_id,
            "downstream_id": edge.downstream_id,
            "upstream": service_map.get(edge.upstream_id).name if edge.upstream_id in service_map else "",
            "downstream": service_map.get(edge.downstream_id).name if edge.downstream_id in service_map else "",
            "dep_type": edge.dep_type,
            "criticality": edge.criticality,
            "timeout_ms": edge.timeout_ms,
        })
    nodes = [{
        "id": s.id,
        "name": s.name,
        "slug": s.slug,
        "level": s.level,
        "status": s.status,
        "out_degree": out_degree.get(s.id, 0),
        "in_degree": in_degree.get(s.id, 0),
    } for s in services]
    return {
        "nodes": nodes,
        "edges": edge_rows,
        "node_count": len(nodes),
        "edge_count": len(edge_rows),
        "roots": [n for n in nodes if n["in_degree"] == 0],
        "leaves": [n for n in nodes if n["out_degree"] == 0],
    }


def impact_analysis(target_id, edges=None, services=None, max_depth=10):
    """下游故障向上传播分析：返回所有会被拖垮的上游服务。

    边是 upstream→downstream，故障沿反向传播；用 BFS + visited 防环，
    发现回边时置 ``cycle_detected``，而不是无限递归或静默截断。
    """
    services = list(services if services is not None else Service.objects.all())
    service_map = {s.id: s for s in services}
    if target_id not in service_map:
        raise ValueError("目标服务不存在")
    if edges is None:
        edges = Dependency.objects.filter(upstream_id__in=service_map.keys(),
                                          downstream_id__in=service_map.keys())
    reverse = defaultdict(list)
    for edge in edges:
        reverse[edge.downstream_id].append(edge)

    queue = deque([(target_id, 0, [target_id])])
    visited = {target_id}
    impacted = []
    cycle = False
    while queue:
        current, depth, path = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in reverse.get(current, []):
            upstream = edge.upstream_id
            if upstream in path:
                cycle = True
                continue
            if upstream in visited:
                continue
            visited.add(upstream)
            node = service_map.get(upstream)
            impacted.append({
                "service_id": upstream,
                "name": node.name if node else "",
                "level": node.level if node else "",
                "status": node.status if node else "",
                "depth": depth + 1,
                "via": current,
                "criticality": edge.criticality,
                "dep_type": edge.dep_type,
                "path": [service_map.get(p).name if p in service_map else str(p)
                         for p in path + [upstream]],
            })
            queue.append((upstream, depth + 1, path + [upstream]))

    impacted.sort(key=lambda row: (row["depth"], row["name"]))
    max_depth_found = max([row["depth"] for row in impacted], default=0)
    critical = [row for row in impacted if row["level"] in ("P0", "P1")]
    return {
        "target": {
            "service_id": target_id,
            "name": service_map[target_id].name,
            "level": service_map[target_id].level,
            "status": service_map[target_id].status,
        },
        "impacted_count": len(impacted),
        "max_depth": max_depth_found,
        "cycle_detected": cycle,
        "critical_impacted": critical,
        "impacted": impacted,
    }


# ---------------------------------------------------------------------------
# 10. 统计聚合
# ---------------------------------------------------------------------------


def alert_top(rules_events, limit=10):
    """告警 TOP：按规则聚合触发次数与最近触发时间。"""
    grouped = {}
    for event in rules_events:
        key = event.rule_id
        row = grouped.setdefault(key, {
            "rule_id": key,
            "rule_name": event.rule.name if event.rule_id else "",
            "service_id": event.service_id,
            "service_name": event.service.name if event.service_id else "",
            "severity": event.rule.severity if event.rule_id else "",
            "total": 0,
            "firing": 0,
            "resolved": 0,
            "last_started_at": None,
        })
        row["total"] += 1
        row["firing"] += 1 if event.status == "firing" else 0
        row["resolved"] += 1 if event.status == "resolved" else 0
        if row["last_started_at"] is None or iso(event.started_at) > row["last_started_at"]:
            row["last_started_at"] = iso(event.started_at)
    rows = sorted(grouped.values(), key=lambda r: (-r["total"], r["rule_name"]))
    return rows[:limit]


def incident_trend(incidents, days=14, now=None):
    """事故趋势：按天统计新增/解决数量，返回连续日期（无数据补 0）。"""
    now = now or timezone.now()
    days = int(clamp(days, 1, 180))
    start = (now - timedelta(days=days - 1)).date()
    opened = defaultdict(int)
    resolved = defaultdict(int)
    for incident in incidents:
        day = incident.started_at.date()
        if day >= start:
            opened[day.isoformat()] += 1
        end = incident.resolved_at or incident.ended_at
        if end and end.date() >= start:
            resolved[end.date().isoformat()] += 1
    points = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        points.append({"date": day, "opened": opened.get(day, 0),
                       "resolved": resolved.get(day, 0)})
    return {
        "days": days,
        "since": start.isoformat(),
        "total_opened": sum(opened.values()),
        "total_resolved": sum(resolved.values()),
        "points": points,
    }


def slo_ranking(slos, snapshot=True):
    """SLO 达成排行：已达成按达成率降序，未达成优先置顶（风险优先）。"""
    rows = []
    for slo in slos:
        row = slo_status_snapshot(slo) if snapshot else None
        if row is None:
            continue
        row["service_name"] = slo.service.name if slo.service_id else ""
        rows.append(row)
    ranked = sorted(rows, key=lambda r: (
        1 if r["met"] else 0,
        -(r["attainment_pct"] if r["attainment_pct"] is not None else -1),
    ))
    breached = [r for r in ranked if r["met"] is False]
    return {
        "total": len(ranked),
        "breached": len(breached),
        "items": ranked,
    }


def platform_overview(user=None, now=None):
    """总览：服务健康 / SLO 达成 / 告警数 / 事故数（一次算齐）。"""
    from observability.models import MetricDef as _MetricDef

    now = now or timezone.now()
    services_qs = Service.objects.all()
    slos_qs = Slo.objects.select_related("service").all()
    incidents_qs = Incident.objects.all()
    rules_qs = AlertRule.objects.all()
    events_qs = AlertEvent.objects.select_related("rule", "service").all()
    if user is not None:
        services_qs = scope_queryset(services_qs, user)
        incidents_qs = scope_queryset(incidents_qs, user)
        rules_qs = scope_queryset(rules_qs, user)
        events_qs = scope_queryset(events_qs, user)
        slos_qs = slos_qs.filter(service_id__in=services_qs.values("id"))

    overview = services_health_overview(services_qs)
    slo_rows = [slo_status_snapshot(slo) for slo in slos_qs]
    attained = [r["attainment_pct"] for r in slo_rows if r["attainment_pct"] is not None]
    firing = events_qs.filter(status="firing")
    suppressed = events_qs.filter(status="suppressed")
    open_incidents = incidents_qs.filter(status__in=("open", "acknowledged", "mitigated"))
    recent_incidents = incidents_qs.filter(started_at__gte=now - timedelta(days=7))
    return {
        "generated_at": iso(now),
        "services": {
            "total": overview["total"],
            "by_status": overview["by_status"],
            "avg_health_score": overview["avg_health_score"],
            "critical_unhealthy": len(overview["critical_services"]),
        },
        "slos": {
            "total": len(slo_rows),
            "met": sum(1 for r in slo_rows if r["met"]),
            "breached": sum(1 for r in slo_rows if r["met"] is False),
            "unknown": sum(1 for r in slo_rows if r["met"] is None),
            "attainment_avg": _average(attained),
            "attainment_min": round4(min(attained)) if attained else None,
        },
        "alerts": {
            "rules_total": rules_qs.count(),
            "rules_enabled": rules_qs.filter(enabled=True).count(),
            "firing": firing.count(),
            "suppressed": suppressed.count(),
            "critical_firing": firing.filter(rule__severity="critical").count(),
            "events_24h": events_qs.filter(started_at__gte=now - timedelta(days=1)).count(),
        },
        "incidents": {
            "open": open_incidents.count(),
            "last_7d": recent_incidents.count(),
            "total": incidents_qs.count(),
            "unresolved_critical": open_incidents.filter(severity__in=("sev1", "sev2")).count(),
        },
        "metrics": {
            "definitions": _MetricDef.objects.filter(
                service_id__in=services_qs.values("id")).count(),
        },
        "worst_services": overview["items"][:5],
    }


def recent_incidents_summary(user=None, days=30, limit=10):
    """最近事故摘要：解决时长、是否已确认，便于首页列表直接渲染。"""
    since = timezone.now() - timedelta(days=days)
    qs = Incident.objects.filter(started_at__gte=since)
    if user is not None:
        qs = scope_queryset(qs, user)
    rows = []
    for incident in qs.order_by("-started_at")[:limit]:
        rows.append({
            "id": incident.id,
            "title": incident.title,
            "severity": incident.severity,
            "status": incident.status,
            "started_at": iso(incident.started_at),
            "mtta_seconds": incident_mtta_seconds(incident),
            "mttr_seconds": incident_mttr_seconds(incident),
        })
    return rows


# ---------------------------------------------------------------------------
# 权限收口（与 core.scoping 对齐：读走数据范围，写只认 owner/管理员）
# ---------------------------------------------------------------------------


def is_admin(user):
    """管理员通行判定；数据范围再宽也不等于写权限。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def ensure_visible(obj, user):
    """读权限：管理员放行，其余按数据范围判定。"""
    if obj is None:
        raise ValueError("对象不存在")
    if is_admin(user):
        return obj
    ids = visible_user_ids(user)
    if ids is not None and getattr(obj, "owner_id", None) not in ids:
        raise ValueError("无权查看该数据")
    return obj


def ensure_writable(obj, user):
    """写权限：管理员或 owner 本人（can_write 的口径）。"""
    if obj is None:
        raise ValueError("对象不存在")
    if is_admin(user):
        return obj
    if not can_write(user, obj):
        raise ValueError("无权修改该数据")
    return obj


def visible(qs, user):
    """按数据范围过滤 queryset（管理员看全量）。"""
    if is_admin(user):
        return qs
    return scope_queryset(qs, user)


def get_visible(model, pk, user, message="对象不存在"):
    """按主键取可见对象。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    return ensure_visible(obj, user)


def get_writable(model, pk, user, message="对象不存在"):
    """按主键取可写对象。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    return ensure_writable(obj, user)


def get_check(pk, user, write=False):
    """取健康检查（服务层入口，鉴权实现仍集中在 common，避免两份判定）。

    common 依赖 services，因此这里延迟导入，防止循环导入。
    """
    from observability.common import get_check as _get_check

    return _get_check(pk, user, write=write)
