# -*- coding: utf-8 -*-
"""devtools · 数学与日期家族接口：num(6) color(6) date(6) cron(4) math(6) unit(4) = 32 个。"""
import ast
import colorsys
import heapq
import math
import re
import secrets
import struct
from datetime import datetime, timedelta, timezone
from itertools import combinations, permutations, product

from .common import (as_lines, endpoint, ok, opt_bool, opt_num, opt_str, p,
                     req, req_list, req_num, req_str)
from .data import APPAREL_SIZE

# =====================================================================
# num 数字（6）
# =====================================================================

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


@endpoint()
def num_base(request):
    """2-36 进制互转（整数 + 6 位小数精度）。"""
    value = req_str(request, "value").strip().lower()
    from_base = int(req_num(request, "from_base", 10, minimum=2, maximum=36, integer=True))
    to_base = int(req_num(request, "to_base", 2, minimum=2, maximum=36, integer=True))
    neg = value.startswith("-")
    if neg:
        value = value[1:]
    if "." in value:
        int_part, frac_part = value.split(".", 1)
    else:
        int_part, frac_part = value, ""
    try:
        dec = 0
        for ch in int_part:
            d = _B36.index(ch)
            if d >= from_base:
                raise ValueError
            dec = dec * from_base + d
        frac = 0.0
        for i, ch in enumerate(frac_part, 1):
            d = _B36.index(ch)
            if d >= from_base:
                raise ValueError
            frac += d / (from_base ** i)
    except ValueError:
        raise ValueError(f"数值包含超出 {from_base} 进制范围的字符")

    def to_base_str(x, base, places=6):
        if x == 0:
            return "0"
        digs = []
        n = int(x)
        while n:
            digs.append(_B36[n % base])
            n //= base
        s = "".join(reversed(digs))
        f = x - int(x)
        if f > 0 and places:
            s += "."
            for _ in range(places):
                f *= base
                d = int(f)
                s += _B36[d]
                f -= d
                if f <= 0:
                    break
        return s

    result = to_base_str(dec + frac, to_base)
    return ok({"value": ("-" if neg else "") + result, "decimal": dec + frac,
               "from_base": from_base, "to_base": to_base})


@endpoint()
def num_ieee754(request):
    """IEEE754 双精度解析：hex / 二进制位拆解（符号·指数·尾数）。"""
    value = req_num(request, "value")
    bits = struct.unpack(">Q", struct.pack(">d", value))[0]
    sign = bits >> 63
    exponent = (bits >> 52) & 0x7FF
    mantissa = bits & ((1 << 52) - 1)
    return ok({
        "value": value, "hex": struct.pack(">d", value).hex(),
        "binary": f"{bits:064b}", "sign": sign, "exponent_raw": exponent,
        "exponent_real": exponent - 1023 if exponent else 0,
        "mantissa_bits": f"{mantissa:052b}",
        "special": "NaN" if exponent == 0x7FF and mantissa else ("Infinity" if exponent == 0x7FF else ("Denormal/0" if exponent == 0 else "Normal")),
    })


@endpoint()
def num_bitwise(request):
    """位运算面板：and/or/xor/not/左右移 + 双进制视图。"""
    a = int(req_num(request, "a", integer=True))
    b = int(opt_num(request, "b", 0) or 0)
    shift = int(opt_num(request, "shift", 1, minimum=0, maximum=64) or 1)
    return ok({
        "a": {"dec": a, "bin": f"{a & 0xFFFFFFFFFFFFFFFF:064b}", "hex": f"{a & 0xFFFFFFFFFFFFFFFF:x}"},
        "b": {"dec": b, "bin": f"{b & 0xFFFFFFFFFFFFFFFF:064b}"},
        "and": a & b, "or": a | b, "xor": a ^ b, "not_a": ~a,
        "left_shift": a << shift, "right_shift": a >> shift, "shift": shift,
        "popcount": bin(a).count("1"),
    })


@endpoint()
def num_combinatorics(request):
    """排列/组合/笛卡尔积：计数与抽样。"""
    items = req_list(request, "items")
    k = int(opt_num(request, "k", 2, minimum=1, maximum=len(items) or 1) or 2)
    sample_n = int(opt_num(request, "sample", 5, minimum=0, maximum=50) or 5)
    rng = secrets.SystemRandom()

    perms = list(permutations(items, k))
    combs = list(combinations(items, k))
    prod = list(product(items, repeat=k))
    return ok({
        "n": len(items), "k": k,
        "P_count": len(perms), "P_sample": [list(x) for x in rng.sample(perms, min(sample_n, len(perms)))],
        "C_count": len(combs), "C_sample": [list(x) for x in rng.sample(combs, min(sample_n, len(combs)))],
        "cartesian_count": len(prod),
    })


@endpoint()
def num_format(request):
    """数字格式化：千分位 / 科学计数 / 百分比 / 指定位数。"""
    value = req_num(request, "value")
    places = int(opt_num(request, "places", 2, minimum=0, maximum=10) or 2)
    return ok({
        "thousands": f"{value:,.{places}f}",
        "scientific": f"{value:.{places}e}",
        "percent": f"{value * 100:.{places}f}%",
        "fixed": f"{value:.{places}f}",
        "compact": f"{value / (1e4 if abs(value) >= 1e4 else 1):.1f} 万" if abs(value) >= 1e4 else f"{value:.{places}f}",
    })


@endpoint()
def num_rounding(request):
    """多种取整：向上/向下/四舍五入/银行家/截断。"""
    value = req_num(request, "value")
    places = int(opt_num(request, "places", 2, minimum=0, maximum=10) or 2)
    factor = 10 ** places
    scaled = value * factor
    return ok({
        "ceil": math.ceil(scaled) / factor,
        "floor": math.floor(scaled) / factor,
        "round": round(scaled) / factor,
        "bankers": round(scaled / 1) / factor if places == 0 else round(value, places),
        "truncate": (int(scaled) / factor) if value >= 0 else (math.ceil(scaled) / factor),
        "places": places,
    })


# =====================================================================
# color 颜色（6）
# =====================================================================


def _parse_color(s):
    s = str(s).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", s):
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise ValueError("颜色需为 #RGB 或 #RRGGBB")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def _rel_lum(rgb):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@endpoint()
def color_contrast(request):
    """WCAG 对比度计算（AA/AAA 判定，正文与大字号）。"""
    c1, c2 = _parse_color(req_str(request, "color1")), _parse_color(req_str(request, "color2"))
    l1, l2 = sorted((_rel_lum(c1), _rel_lum(c2)), reverse=True)
    ratio = (l1 + 0.05) / (l2 + 0.05)
    return ok({"ratio": round(ratio, 2), "color1": _hex(c1), "color2": _hex(c2),
               "AA_normal": ratio >= 4.5, "AA_large": ratio >= 3.0,
               "AAA_normal": ratio >= 7.0, "AAA_large": ratio >= 4.5,
               "verdict": "通过" if ratio >= 4.5 else "正文对比度不足" if ratio >= 3 else "仅适合装饰用途"})


@endpoint()
def color_mix(request):
    """两色按比例混合（线性 RGB 插值）。"""
    c1, c2 = _parse_color(req_str(request, "color1")), _parse_color(req_str(request, "color2"))
    t = float(opt_num(request, "ratio", 0.5, minimum=0, maximum=1) or 0.5)
    mixed = tuple(a * (1 - t) + b * t for a, b in zip(c1, c2))
    return ok({"result": _hex(mixed), "ratio": t, "from": _hex(c1), "to": _hex(c2)})


@endpoint()
def color_scale(request):
    """生成 N 步色阶（c1 → c2 渐变）。"""
    c1, c2 = _parse_color(req_str(request, "color1")), _parse_color(req_str(request, "color2"))
    steps = int(req_num(request, "steps", 5, minimum=2, maximum=24, integer=True))
    colors = [_hex(tuple(a + (b - a) * i / (steps - 1) for a, b in zip(c1, c2))) for i in range(steps)]
    return ok({"colors": colors, "steps": steps})


@endpoint()
def color_nearest(request):
    """最近的 CSS 命名色（欧氏距离）。"""
    rgb = _parse_color(req_str(request, "color"))
    from .data import CSS_COLORS

    best = min(CSS_COLORS.items(), key=lambda kv: sum((a - b) ** 2 for a, b in zip(rgb, kv[1])))
    dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(rgb, best[1])))
    h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in rgb])
    return ok({"nearest": best[0], "hex": _hex(best[1]), "distance": round(dist, 1),
               "your_color": _hex(rgb), "hsl": {"h": round(h * 360), "s": round(s * 100), "l": round(l * 100)}})


@endpoint()
def color_shade(request):
    """明暗调整：lighten/darken/saturate/desaturate（HSL 空间）。"""
    rgb = _parse_color(req_str(request, "color"))
    amount = float(opt_num(request, "amount", 10, minimum=0, maximum=100) or 10) / 100
    mode = opt_str(request, "mode", "lighten")
    h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in rgb])
    if mode == "lighten":
        l = min(1, l + amount)
    elif mode == "darken":
        l = max(0, l - amount)
    elif mode == "saturate":
        s = min(1, s + amount)
    elif mode == "desaturate":
        s = max(0, s - amount)
    else:
        raise ValueError("mode 支持 lighten/darken/saturate/desaturate")
    out = [round(v * 255) for v in colorsys.hls_to_rgb(h, l, s)]
    return ok({"result": _hex(out), "mode": mode, "amount_pct": amount * 100})


@endpoint()
def color_filter(request):
    """滤镜矩阵：grayscale / sepia / invert。"""
    rgb = _parse_color(req_str(request, "color"))
    mode = opt_str(request, "mode", "grayscale")
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    if mode == "grayscale":
        out = (lum, lum, lum)
    elif mode == "invert":
        out = tuple(255 - v for v in rgb)
    elif mode == "sepia":
        r, g, b = [v / 255 for v in rgb]
        out = (min(255, (0.393 * r + 0.769 * g + 0.189 * b) * 255),
               min(255, (0.349 * r + 0.686 * g + 0.168 * b) * 255),
               min(255, (0.272 * r + 0.534 * g + 0.131 * b) * 255))
    else:
        raise ValueError("mode 支持 grayscale/invert/sepia")
    return ok({"result": _hex(out), "mode": mode, "input": _hex(rgb)})


# =====================================================================
# date 日期（6）
# =====================================================================


def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {s}（支持 YYYY-MM-DD 等）")


@endpoint()
def date_add(request):
    """日期加减：y/m/d/w/h 单位，支持跨月自动收敛。"""
    base = _parse_date(req(request, "date"))
    amount = int(req_num(request, "amount", 0, integer=True))
    unit = opt_str(request, "unit", "day").lower()
    result = base
    if unit == "day":
        result = base + timedelta(days=amount)
    elif unit == "week":
        result = base + timedelta(weeks=amount)
    elif unit == "hour":
        result = base + timedelta(hours=amount)
    elif unit == "month":
        month_index = base.year * 12 + base.month - 1 + amount
        y, m = divmod(month_index, 12)
        m += 1
        last_day = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        result = base.replace(year=y, month=m, day=min(base.day, last_day))
    elif unit == "year":
        try:
            result = base.replace(year=base.year + amount)
        except ValueError:  # 2月29
            result = base.replace(year=base.year + amount, day=28)
    else:
        raise ValueError("unit 支持 day/week/month/year/hour")
    return ok({"result": result.strftime("%Y-%m-%d %H:%M"), "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][result.weekday()]})


@endpoint()
def date_workdays(request):
    """工作日计算：区间内工作日数 / 加 N 个工作日后的日期。"""
    start = _parse_date(req(request, "start")).date()
    holidays = set(p(request, "holidays") or [])
    mode = opt_str(request, "mode", "count")
    if mode == "count":
        end = _parse_date(req(request, "end")).date()
        days, d = 0, start
        while d <= end:
            if d.weekday() < 5 and d.isoformat() not in holidays:
                days += 1
            d += timedelta(days=1)
        total = (end - start).days + 1
        return ok({"workdays": days, "calendar_days": total, "weekend_days": total - days})
    n = int(req_num(request, "n", 1, minimum=0, maximum=10000, integer=True))
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in holidays:
            added += 1
    return ok({"result": d.isoformat(), "added": added})


@endpoint()
def date_week_info(request):
    """ISO 周信息：第几周 / 周几 / 本周一与周日。"""
    d = _parse_date(req(request, "date")).date()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return ok({"iso_year": d.isocalendar()[0], "iso_week": d.isocalendar()[1],
               "weekday": d.weekday() + 1, "weekday_cn": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()],
               "monday": monday.isoformat(), "sunday": sunday.isoformat(),
               "quarter": (d.month - 1) // 3 + 1, "day_of_year": d.timetuple().tm_yday})


@endpoint()
def date_quarter_info(request):
    """季度信息：起止日期 / 月列表 / 进度。"""
    d = _parse_date(req(request, "date")).date()
    q = (d.month - 1) // 3 + 1
    start_month = 3 * (q - 1) + 1
    end_month = start_month + 2
    end_day = [31, 30, 30, 31][q - 1]
    start = d.replace(month=start_month, day=1)
    end = d.replace(month=end_month, day=end_day)
    total = (end - start).days + 1
    elapsed = (d - start).days + 1
    return ok({"year": d.year, "quarter": q, "months": [start_month, start_month + 1, end_month],
               "start": start.isoformat(), "end": end.isoformat(),
               "progress_pct": round(elapsed / total * 100, 1)})


@endpoint()
def date_seq(request):
    """日期序列：start 起 n 个，步长 step 天（可选只保留工作日）。"""
    start = _parse_date(req(request, "start")).date()
    n = int(req_num(request, "count", 7, minimum=1, maximum=1000, integer=True))
    step = int(opt_num(request, "step", 1, minimum=1, maximum=366) or 1)
    workday_only = opt_bool(request, "workdays_only")
    out = []
    d = start
    while len(out) < n:
        if not workday_only or d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=step)
    return ok({"dates": out, "count": len(out)})


@endpoint()
def date_countdown(request):
    """倒计时：距离目标时间的 天/时/分/秒 与进度（可选起始时间）。"""
    target = _parse_date(req(request, "target"))
    start_s = p(request, "start")
    base = _parse_date(start_s) if start_s else datetime.now()
    delta = target - base
    total = int(delta.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    past = delta.total_seconds() < 0
    return ok({"target": target.strftime("%Y-%m-%d %H:%M:%S"),
               "days": total // 86400, "hours": total % 86400 // 3600,
               "minutes": total % 3600 // 60, "seconds": total % 60,
               "text": f"{sign}{total // 86400}天 {total % 86400 // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}",
               "passed": past})


# =====================================================================
# cron 调度表达式（4）—— 自研解析器
# =====================================================================

_CRON_FIELD_RANGES = {"minute": (0, 59), "hour": (0, 23), "day": (1, 31), "month": (1, 12), "week": (0, 6)}
_CRON_DOW = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]


def _parse_cron_field(expr, lo, hi, names=None):
    values = set()
    for part in str(expr).split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("步长必须 >= 1")
        if part == "*" or part == "":
            start, end = lo, hi
        elif "-" in part and not part.lstrip("-").isdigit():
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            if names and part.lower() in names:
                start = end = names[part.lower()]
            else:
                start = end = int(part)
        if start < lo or end > hi or start > end:
            raise ValueError(f"取值 {part} 超出范围 [{lo},{hi}]")
        values.update(range(start, end + 1, step))
    return values


def _cron_next(expr_fields, after, n=5):
    minute_v, hour_v, day_v, month_v, week_v = expr_fields
    out = []
    t = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    for _ in range(500000):
        if t.minute in minute_v and t.hour in hour_v and t.month in month_v and t.day in day_v and (t.weekday() + 1) % 7 in week_v:
            out.append(t)
            if len(out) >= n:
                break
        t += timedelta(minutes=1)
    return out


@endpoint()
def cron_parse(request):
    """CRON 解析：合法性 + 未来 N 次触发时间 + 中文描述。"""
    expr = req_str(request, "cron").strip()
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("标准 5 位 CRON：分 时 日 月 周")
    names = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    try:
        parsed = tuple(_parse_cron_field(f, *_CRON_FIELD_RANGES[k], names if k == "week" else None)
                       for f, k in zip(fields, ["minute", "hour", "day", "month", "week"]))
    except ValueError as e:
        raise ValueError(f"CRON 不合法: {e}")
    n = int(opt_num(request, "next", 5, minimum=1, maximum=20) or 5)
    nexts = _cron_next(parsed, datetime.now(), n)
    desc = f"每{'分钟' if len(parsed[0]) == 60 and len(parsed[1]) == 24 else '小时的 ' + ','.join(str(h) for h in sorted(parsed[1])) + ' 分的 ' + ','.join(str(m) for m in sorted(parsed[0]))}"
    if len(parsed[4]) < 7:
        desc += f"，仅在 {'、'.join(_CRON_DOW[d] for d in sorted(parsed[4]))}"
    return ok({"valid": True, "expression": expr,
               "next_runs": [t.strftime("%Y-%m-%d %H:%M") for t in nexts],
               "next_runs_epoch": [int(t.timestamp()) for t in nexts],
               "description": desc,
               "minute_values": sorted(parsed[0]), "hour_values": sorted(parsed[1]),
               "weekday_values": sorted(parsed[4])})


@endpoint()
def cron_validate(request):
    """CRON 校验（只验不跑，给出错误定位）。"""
    expr = req_str(request, "cron").strip()
    fields = expr.split()
    if len(fields) != 5:
        return ok({"valid": False, "error": f"需要 5 个字段，收到 {len(fields)} 个", "expression": expr})
    try:
        vals = tuple(len(_parse_cron_field(f, *_CRON_FIELD_RANGES[k])) for f, k in zip(fields, _CRON_FIELD_RANGES))
        return ok({"valid": True, "values_count": vals, "expression": expr,
                   "complexity": "sparse" if min(vals) < 15 else "dense"})
    except ValueError as e:
        return ok({"valid": False, "error": str(e), "expression": expr})


@endpoint()
def cron_from_interval(request):
    """间隔 → CRON：每 N 分钟/小时 的等价表达式（带说明）。"""
    every = int(req_num(request, "every", 5, minimum=1, maximum=1440, integer=True))
    unit = opt_str(request, "unit", "minute").lower()
    if unit == "minute":
        if every >= 60:
            h, m = divmod(every, 60)
            expr = f"{m or 0} */{h} * * *" if m else f"0 */{h} * * *"
        else:
            expr = f"*/{every} * * * *"
        desc = f"每 {every} 分钟"
    elif unit == "hour":
        expr = f"0 */{every} * * *"
        desc = f"每 {every} 小时的第 0 分"
    elif unit == "day":
        hour = int(opt_num(request, "at_hour", 9, minimum=0, maximum=23) or 9)
        expr = f"0 {hour} */{every} * *"
        desc = f"每 {every} 天的 {hour}:00"
    elif unit == "week":
        dow = int(opt_num(request, "weekday", 1, minimum=0, maximum=6) or 1)
        hour = int(opt_num(request, "at_hour", 9, minimum=0, maximum=23) or 9)
        expr = f"0 {hour} * * {dow}"
        desc = f"每周{_CRON_DOW[dow]} {hour}:00"
    else:
        raise ValueError("unit 支持 minute/hour/day/week")
    return ok({"cron": expr, "description": desc, "every": every, "unit": unit})


@endpoint()
def cron_shift(request):
    """时区换算：把下一次触发时间换算到目标时区。"""
    expr = req_str(request, "cron").strip()
    tz_name = opt_str(request, "tz", "UTC")
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("标准 5 位 CRON")
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        raise ValueError(f"未知时区: {tz_name}")
    names = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    parsed = tuple(_parse_cron_field(f, *_CRON_FIELD_RANGES[k], names if k == "week" else None)
                   for f, k in zip(fields, ["minute", "hour", "day", "month", "week"]))
    now_local = datetime.now(tz).replace(tzinfo=None)
    nexts = _cron_next(parsed, now_local, 3)
    return ok({"timezone": tz_name,
               "next_local": [t.strftime("%Y-%m-%d %H:%M") for t in nexts],
               "utc_offset": (datetime.now(tz).utcoffset() or timezone.utc.utcoffset(datetime.now())).total_seconds() / 3600})


# =====================================================================
# math 数学扩展（6）
# =====================================================================


@endpoint()
def math_matrix(request):
    """矩阵运算：行列式 / 逆 / 转置 / 乘法 / 迹。"""
    a = req_list(request, "a")
    n = len(a)
    if not n or any(len(r) != n for r in a):
        raise ValueError("仅支持 n×n 方阵做 det/inv")
    try:
        m = [[float(x) for x in row] for row in a]
    except (TypeError, ValueError):
        raise ValueError("a 必须是数字二维数组")

    def det(mat):
        if len(mat) == 1:
            return mat[0][0]
        total = 0
        for j in range(len(mat)):
            minor = [row[:j] + row[j + 1:] for row in mat[1:]]
            total += ((-1) ** j) * mat[0][j] * det(minor)
        return total

    d = det(m)
    result = {"det": round(d, 8), "trace": round(sum(m[i][i] for i in range(n)), 8), "size": n}
    if abs(d) < 1e-12:
        result["inverse"] = None
        result["singular"] = True
    else:
        aug = [m[i] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        for col in range(n):
            piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
            aug[col], aug[piv] = aug[piv], aug[col]
            pv = aug[col][col]
            aug[col] = [v / pv for v in aug[col]]
            for r in range(n):
                if r != col and aug[r][col]:
                    f = aug[r][col]
                    aug[r] = [v - f * w for v, w in zip(aug[r], aug[col])]
        result["inverse"] = [[round(v, 8) for v in row[n:]] for row in aug]
    b = p(request, "b")
    if b is not None:
        try:
            bm = [[float(x) for x in row] for row in b]
        except (TypeError, ValueError):
            raise ValueError("b 必须是数字二维数组")
        if len(bm[0]) != len(m):
            raise ValueError("b 的列数必须等于 a 的行数")
        result["multiply"] = [[round(sum(m[i][k] * bm[k][j] for k in range(len(bm))), 8)
                               for j in range(len(bm[0]))] for i in range(len(m))]
    result["transpose"] = [[m[j][i] for j in range(n)] for i in range(n)]
    return ok(result)


@endpoint()
def math_linear_solve(request):
    """线性方程组求解（高斯消元，支持长方阵最小二乘提示）。"""
    a = req_list(request, "a")
    b = req_list(request, "b")
    n = len(a)
    aug = [[float(a[i][j]) for j in range(n)] + [float(b[i])] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-12:
            return ok({"solvable": False, "reason": "矩阵奇异（无唯一解）"})
        aug[col], aug[piv] = aug[piv], aug[col]
        for r in range(n):
            if r != col and aug[r][col]:
                f = aug[r][col] / aug[col][col]
                aug[r] = [v - f * w for v, w in zip(aug[r], aug[col])]
    x = [aug[i][n] / aug[i][i] for i in range(n)]
    return ok({"solvable": True, "solution": [round(v, 8) for v in x],
               "verify": [round(sum(a[i][j] * x[j] for j in range(n)), 6) for i in range(n)]})


def _is_prime(n):
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0:
            return False
    return True


@endpoint()
def math_primes(request):
    """质数工具：因子分解 / 是否质数 / N 以内计数与抽样。"""
    n = int(req_num(request, "n", 2, minimum=1, maximum=10 ** 12, integer=True))
    factors, x = [], n
    d = 2
    while d * d <= x:
        while x % d == 0:
            factors.append(d)
            x //= d
        d += 1
    if x > 1:
        factors.append(x)
    count_n = min(n, 100000)
    sieve = [True] * (count_n + 1) if count_n >= 2 else []
    primes_count = 0
    if count_n >= 2:
        sieve[0] = sieve[1] = False
        for i in range(2, int(count_n ** 0.5) + 1):
            if sieve[i]:
                sieve[i * i::i] = [False] * len(sieve[i * i::i])
        primes_count = sum(sieve)
    return ok({"n": n, "factors": factors, "factorization": " × ".join(map(str, sorted(factors))),
               "is_prime": _is_prime(n) and n >= 2, "primes_below_100k_style": primes_count if count_n == n else None,
               "largest_prime_factor": max(factors) if factors else None})


_FUNC_WHITELIST = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "abs": abs, "floor": math.floor, "ceil": math.ceil, "round": round,
    "pow": pow, "min": min, "max": max, "hypot": math.hypot,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


@endpoint()
def math_expr(request):
    """安全表达式求值（AST 白名单，支持变量与函数，如 x**2 + sin(x)）。"""
    expr = req_str(request, "expr")
    variables = p(request, "variables") or {}
    if not isinstance(variables, dict):
        raise ValueError("variables 必须是对象")

    allowed_names = set(_FUNC_WHITELIST) | set(_CONSTS) | set(variables)

    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in _CONSTS:
                return _CONSTS[node.id]
            if node.id in variables:
                return float(variables[node.id])
            raise ValueError(f"未知变量: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv):
            l, r = eval_node(node.left), eval_node(node.right)
            return {ast.Add: l + r, ast.Sub: l - r, ast.Mult: l * r, ast.Div: l / r,
                    ast.Pow: l ** r, ast.Mod: l % r, ast.FloorDiv: l // r}[type(node.op)]
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.USub, ast.UAdd):
            v = eval_node(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNC_WHITELIST:
            args = [eval_node(a) for a in node.args]
            return _FUNC_WHITELIST[node.func.id](*args)
        raise ValueError(f"不允许的表达式元素: {type(node).__name__}")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"表达式语法错误: {e}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(f"未知标识符: {node.id}")
    value = eval_node(tree.body)
    return ok({"expr": expr, "value": round(value, 10) if isinstance(value, float) else value,
               "variables": variables, "engine": "ast-whitelist"})


@endpoint()
def math_dist(request):
    """分布求值：正态 PDF/CDF、二项 PMF、泊松 PMF。"""
    kind = opt_str(request, "kind", "normal")
    if kind == "normal":
        x = float(req_num(request, "x"))
        mu = float(opt_num(request, "mean", 0) or 0)
        sigma = float(opt_num(request, "sigma", 1) or 1)
        if sigma <= 0:
            raise ValueError("sigma 必须 > 0")
        pdf = math.exp(-((x - mu) ** 2) / (2 * sigma ** 2)) / (sigma * math.sqrt(2 * math.pi))
        cdf = 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))
        z = (x - mu) / sigma
        return ok({"kind": "normal", "pdf": round(pdf, 8), "cdf": round(cdf, 6), "z": round(z, 4)})
    if kind == "binomial":
        n = int(req_num(request, "n", 10, minimum=1, maximum=10000, integer=True))
        p_ = float(req_num(request, "p", 0.5, minimum=0, maximum=1))
        k = int(req_num(request, "k", 5, minimum=0, maximum=n, integer=True))
        pmf = math.comb(n, k) * p_ ** k * (1 - p_) ** (n - k)
        return ok({"kind": "binomial", "pmf": round(pmf, 8), "mean": n * p_, "variance": n * p_ * (1 - p_)})
    if kind == "poisson":
        lam = float(req_num(request, "lambda", 1, minimum=0))
        k = int(req_num(request, "k", 0, minimum=0, maximum=10000, integer=True))
        pmf = lam ** k * math.exp(-lam) / math.factorial(k)
        return ok({"kind": "poisson", "pmf": round(pmf, 8), "mean": lam, "variance": lam})
    raise ValueError("kind 支持 normal/binomial/poisson")


@endpoint()
def math_dijkstra(request):
    """Dijkstra 最短路径：edges=[{from,to,weight}]，返回路径与距离。"""
    edges = req_list(request, "edges")
    start = str(req(request, "start"))
    end = str(req(request, "end"))
    graph = {}
    for e in edges:
        if not isinstance(e, dict):
            raise ValueError("edges 每项需为 {from, to, weight}")
        f, t, w = str(e.get("from")), str(e.get("to")), float(e.get("weight", 1))
        if w < 0:
            raise ValueError("Dijkstra 不支持负权重")
        graph.setdefault(f, []).append((t, w))
        graph.setdefault(t, []).append((f, w))  # 无向
    dist, prev, pq = {start: 0.0}, {}, [(0.0, start)]
    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w in graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if end not in dist:
        return ok({"reachable": False, "nodes_explored": len(visited)})
    path, cur = [end], end
    while cur != start:
        cur = prev[cur]
        path.append(cur)
    return ok({"reachable": True, "distance": round(dist[end], 6), "path": list(reversed(path)),
               "steps": len(path) - 1, "all_distances": {k: round(v, 4) for k, v in dist.items()}})


# =====================================================================
# unit 单位扩展（4）
# =====================================================================

_UNIT_TABLES = {
    "data": {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4, "PB": 1024 ** 5,
             "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "bit": 1 / 8, "Kb": 128, "Mb": 1024 ** 2 / 8},
    "angle": {"deg": 1, "rad": 180 / math.pi, "grad": 0.9, "turn": 360, "arcmin": 1 / 60, "arcsec": 1 / 3600},
    "speed": {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444, "ft/s": 0.3048, "mach": 340.29},
}


@endpoint()
def unit_data_size(request):
    """数据容量换算（KB/KiB/Mb 通通分清）。"""
    value = float(req_num(request, "value"))
    from_u = str(req(request, "from")).strip()
    table = _UNIT_TABLES["data"]
    if from_u not in table:
        raise ValueError(f"未知单位 {from_u}，支持 {list(table)}")
    base = value * table[from_u]
    return ok({"input": {"value": value, "unit": from_u},
               "converted": {u: round(base / f, 6) for u, f in table.items() if f >= 1}})


@endpoint()
def unit_angle(request):
    """角度换算：deg/rad/grad/turn/角分/角秒。"""
    value = float(req_num(request, "value"))
    from_u = str(req(request, "from")).strip()
    table = _UNIT_TABLES["angle"]
    if from_u not in table:
        raise ValueError(f"未知单位 {from_u}")
    base = value * table[from_u]
    return ok({"input": {"value": value, "unit": from_u},
               "converted": {u: round(base / f, 8) for u, f in table.items()}})


@endpoint()
def unit_speed(request):
    """速度换算：m/s、km/h、mph、节、马赫。"""
    value = float(req_num(request, "value"))
    from_u = str(req(request, "from")).strip()
    table = _UNIT_TABLES["speed"]
    if from_u not in table:
        raise ValueError(f"未知单位 {from_u}")
    base = value * table[from_u]
    return ok({"input": {"value": value, "unit": from_u},
               "converted": {u: round(base / f, 6) for u, f in table.items()}})


@endpoint()
def unit_apparel(request):
    """服装/鞋码对照表（全量或按码查询）。"""
    table = opt_str(request, "table", "")
    size = opt_str(request, "size", "")
    if table:
        if table not in APPAREL_SIZE:
            raise ValueError(f"table 支持 {list(APPAREL_SIZE)}")
        data = APPAREL_SIZE[table]
        if size and size in data:
            return ok({"table": table, "size": size, "matches": data[size]})
        return ok({"table": table, "sizes": data})
    return ok({"tables": APPAREL_SIZE, "hint": "传 table 与可选 size 精查"})


MATH_FAMILY_COUNT = 6 + 6 + 6 + 4 + 6 + 4  # = 32
