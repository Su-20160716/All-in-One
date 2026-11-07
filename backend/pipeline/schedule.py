# -*- coding: utf-8 -*-
"""Cron 解析与下次运行时间计算。

只支持标准 5 段（分 时 日 月 周），够用且不会被 6 段 / Quartz 方言搞混。
支持 ``*``、``*/n``、``a-b``、``a-b/n``、逗号列表、月份与星期英文缩写。

计算策略：先按天筛（月 / 日 / 周），命中后在当天按小时、分钟顺序找第一个
晚于基准时间的点。相比逐分钟推进 366 天（约 52 万次），这里最坏也只是
「366 天 × 当天分钟集合」，而且绝大多数管道每天都在跑。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
WEEKDAY_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_FIELD_RANGES = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 6),
)

MAX_LOOKAHEAD_DAYS = 366


def _parse_value(text: str, low: int, high: int, field: str, names: dict) -> int:
    raw = text.strip().lower()
    if raw in names:
        return names[raw]
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"cron 的 {field} 字段包含非法值：{text}")
    if value < low or value > high:
        raise ValueError(f"cron 的 {field} 字段超出范围 {low}-{high}：{value}")
    return value


def _parse_field(text: str, low: int, high: int, field: str,
                 names: dict | None = None) -> set[int]:
    """解析单个 cron 字段，返回允许值集合。"""
    names = names or {}
    text = str(text).strip()
    if not text:
        raise ValueError(f"cron 的 {field} 字段不能为空")
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"cron 的 {field} 字段存在空项")
        step = 1
        if "/" in part:
            base, step_text = part.split("/", 1)
            try:
                step = int(step_text)
            except ValueError:
                raise ValueError(f"cron 的 {field} 步长必须是整数：{step_text}")
            if step <= 0:
                raise ValueError(f"cron 的 {field} 步长必须大于 0")
        else:
            base = part

        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, right = base.split("-", 1)
            start = _parse_value(left, low, high, field, names)
            end = _parse_value(right, low, high, field, names)
            if start > end:
                raise ValueError(f"cron 的 {field} 区间起始值不能大于结束值：{base}")
        else:
            start = _parse_value(base, low, high, field, names)
            end = start
        values.update(range(start, end + 1, step))

    if field == "weekday" and 7 in values:
        # 兼容 Unix 习惯：0 与 7 都是周日
        values.discard(7)
        values.add(0)
    return values


@lru_cache(maxsize=256)
def parse_cron(expr: str) -> dict:
    """把 cron 解析成各字段的允许值集合（带缓存，调度扫描高频复用）。"""
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("cron 表达式不能为空")
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron 表达式必须包含 5 段：分 时 日 月 周")
    parsed = {}
    for index, (field, low, high) in enumerate(_FIELD_RANGES):
        names = {}
        if field == "month":
            names = MONTH_NAMES
        elif field == "weekday":
            names = WEEKDAY_NAMES
        parsed[field] = _parse_field(parts[index], low, high, field, names)
    return parsed


def normalize_cron(expr: str) -> str:
    """校验并归一化空白；非法时抛中文 ValueError。"""
    parse_cron(expr)
    return " ".join(expr.split())


def get_timezone(name: str):
    """解析时区；空值回退项目默认时区。"""
    name = (name or getattr(settings, "TIME_ZONE", "Asia/Shanghai")).strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f"无效的时区：{name}")


def _day_matches(parsed: dict, current: datetime) -> bool:
    if current.month not in parsed["month"]:
        return False
    dom_match = current.day in parsed["day"]
    # Python: 周一=0 … 周日=6；cron: 周日=0 … 周六=6
    cron_weekday = (current.weekday() + 1) % 7
    dow_match = cron_weekday in parsed["weekday"]
    dom_any = len(parsed["day"]) == 31
    dow_any = len(parsed["weekday"]) == 7
    if dom_any and dow_any:
        return True
    if dom_any:
        return dow_match
    if dow_any:
        return dom_match
    # 标准 cron：日与周都限定时取「或」
    return dom_match or dow_match


def next_run_time(expr: str, after: datetime | None = None,
                  tzname: str | None = None) -> datetime:
    """计算下一次运行时间（带时区），找不到抛 ValueError。"""
    parsed = parse_cron(expr)
    tz = get_timezone(tzname or "")
    if after is None:
        after = timezone.now()
    if timezone.is_naive(after):
        after = after.replace(tzinfo=tz)
    else:
        after = after.astimezone(tz)
    start = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)

    hours = sorted(parsed["hour"])
    minutes = sorted(parsed["minute"])
    for offset in range(MAX_LOOKAHEAD_DAYS + 1):
        day = start.date() + timedelta(days=offset)
        probe = datetime(day.year, day.month, day.day, tzinfo=tz)
        if not _day_matches(parsed, probe):
            continue
        day_start = start if offset == 0 else probe
        for hour in hours:
            if offset == 0 and hour < day_start.hour:
                continue
            for minute in minutes:
                if offset == 0:
                    if hour == day_start.hour and minute < day_start.minute:
                        continue
                candidate = datetime(day.year, day.month, day.day, hour, minute,
                                     tzinfo=tz)
                if candidate > after:
                    return candidate
    raise ValueError(f"cron 表达式在 {MAX_LOOKAHEAD_DAYS} 天内没有可执行时间：{expr}")


def next_run_times(expr: str, count: int = 3, after: datetime | None = None,
                   tzname: str | None = None) -> list[datetime]:
    """连续计算 N 次运行时间，供调度预览。"""
    count = max(1, min(int(count or 1), 20))
    tz = get_timezone(tzname or "")
    cursor = after
    out = []
    for _ in range(count):
        cursor = next_run_time(expr, cursor, tzname)
        out.append(cursor.astimezone(tz))
    return out


def cron_matches(expr: str, moment: datetime | None = None,
                 tzname: str | None = None) -> bool:
    """判断某个时刻是否命中 cron（精确到分钟）。"""
    parsed = parse_cron(expr)
    tz = get_timezone(tzname or "")
    moment = moment or timezone.now()
    moment = moment.astimezone(tz) if not timezone.is_naive(moment) else moment.replace(tzinfo=tz)
    return (_day_matches(parsed, moment)
            and moment.hour in parsed["hour"]
            and moment.minute in parsed["minute"])


def describe_cron(expr: str) -> str:
    """把 cron 翻译成中文描述，降低配置门槛。"""
    parts = expr.split()
    if len(parts) != 5:
        return "无法解析的 cron 表达式"
    minute, hour, day, month, weekday = parts
    if expr.strip() == "* * * * *":
        return "每分钟"
    if minute.startswith("*/") and hour == "*" and day == "*" and month == "*" and weekday == "*":
        return f"每 {minute[2:]} 分钟"
    if minute.isdigit() and hour == "*" and day == "*" and month == "*" and weekday == "*":
        return f"每小时第 {int(minute)} 分钟"
    if minute.isdigit() and hour.isdigit() and day == "*" and month == "*" and weekday == "*":
        return f"每天 {int(hour):02d}:{int(minute):02d}"
    if (minute.isdigit() and hour.isdigit() and weekday != "*"
            and day == "*" and month == "*"):
        return f"每周 {weekday} 的 {int(hour):02d}:{int(minute):02d}"
    return f"按 {expr} 执行"


def schedule_next_run(schedule, base: datetime | None = None):
    """计算并写入调度的下次运行时间；禁用时清空。"""
    if not schedule.enabled:
        schedule.next_run_at = None
        return None
    schedule.next_run_at = next_run_time(schedule.cron, base, schedule.timezone)
    return schedule.next_run_at


def preview_next_runs(pipeline, limit: int = 3) -> list[dict]:
    """管道调度预览：取第一个启用调度，返回未来 N 次运行时间。"""
    schedule = pipeline.schedules.filter(enabled=True).order_by("id").first()
    if schedule is None:
        return []
    times = next_run_times(schedule.cron, limit, None, schedule.timezone)
    return [
        {
            "schedule_id": schedule.id,
            "name": schedule.name,
            "cron": schedule.cron,
            "timezone": schedule.timezone,
            "next_run_at": moment.isoformat(),
            "description": describe_cron(schedule.cron),
        }
        for moment in times
    ]


def due_schedules(now: datetime | None = None):
    """到期待执行的调度查询集（调用方负责按用户范围过滤）。"""
    from pipeline.models import Schedule

    now = now or timezone.now()
    return Schedule.objects.filter(enabled=True, next_run_at__lte=now)


def mark_schedule_run(schedule, run=None, status: str = "", base: datetime | None = None):
    """运行结束后回写调度：上次时间、上次状态、下次运行时间。"""
    now = base or timezone.now()
    schedule.last_run_at = now
    schedule.last_status = status or (run.status if run is not None else "")
    try:
        schedule.next_run_at = next_run_time(schedule.cron, now, schedule.timezone)
    except ValueError:
        # cron 在上次保存后仍可能因时区数据缺失失效：保留原值并禁用，避免死循环
        schedule.enabled = False
        schedule.next_run_at = None
    schedule.save(update_fields=["last_run_at", "last_status", "next_run_at",
                                 "enabled", "updated_at"])
    return schedule
