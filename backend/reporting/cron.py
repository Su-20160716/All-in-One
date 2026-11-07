# -*- coding: utf-8 -*-
"""cron 简化解析与下一次运行时间计算（不依赖任何调度库）。

支持 5 段标准 cron：``分 时 日 月 周``
------------------------------------
- ``*``        任意
- ``*/n``      步长
- ``a-b``      范围
- ``a-b/n``    范围内步长
- ``a,b,c``    枚举（可与上面任意组合）
- 月份/星期支持英文缩写（JAN / MON），星期 0 与 7 都表示周日

**不支持** ``@daily`` / 秒级 / L / W / # 等扩展语法 —— 报表场景够用，
且解析结果可完全解释，避免「配了不生效还查不出原因」。

下一次运行时间的算法：从 after 起逐分钟推进（按 时/分 的匹配集合跳着走，
不是暴力遍历 1440 分钟），最多向前找 400 天，找不到就报错。
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

MAX_LOOKAHEAD_DAYS = 400

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

WEEKDAY_LABELS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]

FIELD_SPECS = (
    ("minute", 0, 59, "分钟"),
    ("hour", 0, 23, "小时"),
    ("dom", 1, 31, "日"),
    ("month", 1, 12, "月"),
    ("dow", 0, 6, "星期"),
)


class CronSpec:
    """解析后的 cron：五个集合 + 原始表达式，便于复用与展示。"""

    def __init__(self, expr, minute, hour, dom, month, dow):
        self.expr = expr
        self.minute = minute
        self.hour = hour
        self.dom = dom
        self.month = month
        self.dow = dow

    def as_dict(self):
        return {
            "expr": self.expr,
            "minute": sorted(self.minute),
            "hour": sorted(self.hour),
            "dom": sorted(self.dom),
            "month": sorted(self.month),
            "dow": sorted(self.dow),
            "dom_restricted": self.dom != set(range(1, 32)),
            "dow_restricted": self.dow != set(range(0, 7)),
            "description": describe(self.expr),
        }


def _parse_atom(text, lo, hi, label, names=None):
    atom = text.strip().lower()
    if not atom:
        raise ValueError(f"cron 的{label}段含空项")
    if names and atom in names:
        return names[atom]
    try:
        value = int(atom)
    except ValueError:
        raise ValueError(f"cron 的{label}段取值非法：{text}")
    if value < lo or value > hi:
        raise ValueError(f"cron 的{label}段取值越界（{lo}-{hi}）：{text}")
    return value


def parse_field(text, lo, hi, label, names=None):
    """解析单个字段（支持 * / 步长 / 范围 / 枚举）。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError(f"cron 的{label}段不能为空")
    values = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"cron 的{label}段含空项")
        step = 1
        body = part
        if "/" in part:
            body, step_text = part.split("/", 1)
            try:
                step = int(step_text)
            except ValueError:
                raise ValueError(f"cron 的{label}段步长非法：{part}")
            if step <= 0 or step > (hi - lo + 1):
                raise ValueError(f"cron 的{label}段步长越界：{part}")
        if body in ("*", "?"):
            start, end = lo, hi
        elif "-" in body:
            left, right = body.split("-", 1)
            start = _parse_atom(left, lo, hi, label, names)
            end = _parse_atom(right, lo, hi, label, names)
            if end < start:
                raise ValueError(f"cron 的{label}段范围倒置：{part}")
        else:
            start = _parse_atom(body, lo, hi, label, names)
            end = hi if step > 1 else start
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"cron 的{label}段解析为空：{text}")
    return values


def parse_cron(expr):
    """解析 5 段 cron；段数不对 / 取值越界 / 步长非法都抛 ValueError。"""
    text = str(expr or "").strip()
    if not text:
        raise ValueError("cron 表达式不能为空")
    parts = text.split()
    if len(parts) != 5:
        raise ValueError(f"cron 必须为 5 段（分 时 日 月 周），实际 {len(parts)} 段")
    parsed = {}
    for idx, (key, lo, hi, label) in enumerate(FIELD_SPECS):
        names = MONTH_NAMES if key == "month" else (DOW_NAMES if key == "dow" else None)
        parsed[key] = parse_field(parts[idx], lo, hi, label, names)
    # 7 也是周日（与 Unix cron 兼容）
    if 7 in parsed["dow"]:
        parsed["dow"].discard(7)
        parsed["dow"].add(0)
    return CronSpec(text, parsed["minute"], parsed["hour"], parsed["dom"],
                    parsed["month"], parsed["dow"])


def validate_cron(expr):
    """只校验不计算（保存计划任务时用），返回解析后的 spec。"""
    return parse_cron(expr)


def get_zone(tz_name):
    """时区解析：优先 zoneinfo，取不到回退项目默认时区。"""
    name = str(tz_name or "").strip() or getattr(settings, "TIME_ZONE", "UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        try:
            return ZoneInfo(getattr(settings, "TIME_ZONE", "UTC"))
        except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover
            return ZoneInfo("UTC")


def _day_matches(spec, day):
    """日与星期的组合规则（与标准 cron 一致）：两者都限定时取「或」。"""
    dom_ok = day.day in spec.dom
    dow_ok = (day.weekday() + 1) % 7 in spec.dow  # Python 周一=0，cron 周日=0
    dom_restricted = spec.dom != set(range(1, 32))
    dow_restricted = spec.dow != set(range(0, 7))
    if dom_restricted and dow_restricted:
        return dom_ok or dow_ok
    if dom_restricted:
        return dom_ok
    if dow_restricted:
        return dow_ok
    return True


def compute_next_run(expr, tz_name=None, after=None):
    """计算下一次运行时间（aware datetime，带目标时区）。

    after 默认为「现在」；返回严格晚于 after 的最近匹配分钟。
    """
    spec = parse_cron(expr)
    zone = get_zone(tz_name)
    base = after or timezone.now()
    if timezone.is_naive(base):
        base = timezone.make_aware(base, zone)
    local = base.astimezone(zone)
    # 从下一分钟开始找（cron 的分钟粒度）
    cursor = (local + timedelta(minutes=1)).replace(second=0, microsecond=0)
    hours = sorted(spec.hour)
    minutes = sorted(spec.minute)

    for day_offset in range(MAX_LOOKAHEAD_DAYS):
        day = (cursor + timedelta(days=day_offset)).date()
        if day.month not in spec.month:
            continue
        if not _day_matches(spec, day):
            continue
        for hour in hours:
            for minute in minutes:
                candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
                if candidate >= cursor:
                    return candidate
        # 当天没有更晚的匹配，继续下一天
    raise ValueError(f"cron 表达式 {expr} 在未来 {MAX_LOOKAHEAD_DAYS} 天内没有匹配时间")


def next_runs(expr, tz_name=None, count=5, after=None):
    """连续计算 N 次运行时间（前端「未来 5 次」预览）。"""
    count = max(1, min(int(count or 5), 20))
    out = []
    cursor = after or timezone.now()
    for _ in range(count):
        nxt = compute_next_run(expr, tz_name, after=cursor)
        out.append(nxt)
        cursor = nxt
    return out


def is_due(expr, tz_name=None, now=None):
    """当前分钟是否命中表达式（到期扫描用：分钟级幂等）。"""
    spec = parse_cron(expr)
    zone = get_zone(tz_name)
    moment = (now or timezone.now()).astimezone(zone)
    if moment.minute not in spec.minute or moment.hour not in spec.hour:
        return False
    if moment.month not in spec.month:
        return False
    return _day_matches(spec, moment.date())


def describe(expr):
    """把 cron 翻成一句中文，便于列表页直接展示。"""
    spec = parse_cron(expr)
    minute_text = _describe_values(sorted(spec.minute), "分")
    hour_text = _describe_values(sorted(spec.hour), "点")
    day_text = _describe_dom(spec.dom)
    month_text = _describe_month(spec.month)
    dow_text = _describe_dow(spec.dow)
    pieces = [f"{month_text}", f"{day_text}", f"{dow_text}", f"{hour_text}{minute_text}"]
    return "".join(piece for piece in pieces if piece)


def _describe_values(values, unit):
    if values == list(range(0, 60)) or values == list(range(0, 24)):
        return "每分钟" if unit == "分" else "每小时"
    if len(values) == 1:
        return f"第{values[0]}{unit}"
    if len(values) <= 6:
        return f"{unit}：{','.join(str(v) for v in values)}"
    # 等差数列显示成步长
    gap = values[1] - values[0] if len(values) > 1 else 1
    if gap > 1 and all(values[i] - values[i - 1] == gap for i in range(1, len(values))):
        return f"每 {gap} {unit}"
    return f"{unit}：{len(values)} 个取值"


def _describe_dom(dom):
    if dom == set(range(1, 32)):
        return "每天"
    values = sorted(dom)
    if len(values) == 1:
        return f"每月{values[0]}号"
    return f"每月 {len(values)} 天"


def _describe_month(month):
    if month == set(range(1, 13)):
        return ""
    return "、".join(f"{m}月" for m in sorted(month))


def _describe_dow(dow):
    if dow == set(range(0, 7)):
        return ""
    if dow == {1, 2, 3, 4, 5}:
        return "工作日"
    if dow == {0, 6}:
        return "周末"
    return "、".join(WEEKDAY_LABELS[d] for d in sorted(dow))


def schedule_summary(schedule, count=3):
    """计划任务摘要：下次运行 + 未来 N 次 + 是否合法（非法不抛异常）。"""
    data = {
        "id": schedule.pk,
        "cron": schedule.cron_expr,
        "timezone": schedule.timezone,
        "enabled": schedule.enabled,
        "valid": True,
        "error": "",
        "upcoming": [],
    }
    try:
        runs = next_runs(schedule.cron_expr, schedule.timezone, count)
        data["upcoming"] = [r.isoformat() for r in runs]
        data["next_run_at"] = runs[0].isoformat() if runs else None
        data["description"] = describe(schedule.cron_expr)
    except ValueError as e:
        data["valid"] = False
        data["error"] = str(e)
        data["next_run_at"] = None
        data["description"] = ""
    return data
