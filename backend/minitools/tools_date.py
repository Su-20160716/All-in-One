# -*- coding: utf-8 -*-
"""minitools · 日期时间家族（22 个，编号 84-105）。"""
import math
from datetime import date, datetime, timedelta, timezone

from .common import endpoint, ok, opt_num, opt_str, req_num, req_str


def _parse(s):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {s}")


@endpoint()
def date_diff(request):
    """84. 日期差。"""
    a = _parse(req_str(request, "date_a"))
    b = _parse(req_str(request, "date_b"))
    days = abs((b.date() - a.date()).days)
    return ok({"days": days, "weeks": days // 7, "months": days // 30, "years": days // 365})


@endpoint()
def date_add(request):
    """85. 日期加减。"""
    d = _parse(req_str(request, "date"))
    years = int(opt_num(request, "years", 0, integer=True))
    months = int(opt_num(request, "months", 0, integer=True))
    days = int(opt_num(request, "days", 0, integer=True))
    y = d.year + years
    m = d.month + months
    y += (m - 1) // 12
    m = ((m - 1) % 12) + 1
    day = min(d.day, 28)
    try:
        result = d.replace(year=y, month=m, day=day) + timedelta(days=days)
    except ValueError:
        result = d.replace(year=y, month=m, day=28) + timedelta(days=days)
    return ok({"result": result.strftime("%Y-%m-%d")})


@endpoint()
def weekday(request):
    """86. 星期几计算。"""
    d = _parse(req_str(request, "date"))
    names_cn = ["一", "二", "三", "四", "五", "六", "日"]
    return ok({"weekday": d.weekday() + 1, "weekday_cn": "星期" + names_cn[d.weekday()]})


@endpoint()
def leap_year(request):
    """87. 闰年判断。"""
    y = int(req_num(request, "year", minimum=1, maximum=9999, integer=True))
    return ok({"is_leap": (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)})


@endpoint()
def days_in_month(request):
    """88. 当月天数。"""
    y = int(req_num(request, "year", minimum=1, maximum=9999, integer=True))
    m = int(req_num(request, "month", minimum=1, maximum=12, integer=True))
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return ok({"days": (nxt - date(y, m, 1)).days})


@endpoint()
def quarter(request):
    """89. 季度计算。"""
    d = _parse(req_str(request, "date"))
    q = (d.month - 1) // 3 + 1
    start = date(d.year, (q - 1) * 3 + 1, 1)
    end_month = q * 3
    if end_month == 12:
        end = date(d.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(d.year, end_month + 1, 1) - timedelta(days=1)
    return ok({"quarter": q, "start": start.isoformat(), "end": end.isoformat()})


@endpoint()
def timestamp_convert(request):
    """90. 时间戳转换。unit: s/ms。"""
    value = req_num(request, "value")
    unit = opt_str(request, "unit", "s")
    ts = value / 1000 if unit == "ms" else value
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ValueError("时间戳超出可表示范围")
    return ok({"datetime": dt.strftime("%Y-%m-%d %H:%M:%S UTC"), "timestamp": ts})


@endpoint()
def countdown(request):
    """91. 倒计时计算（到目标日期的剩余时间）。"""
    target = _parse(req_str(request, "target_date"))
    now = datetime.now()
    delta = target - now
    secs = max(0, int(delta.total_seconds()))
    return ok({
        "days": secs // 86400,
        "hours": (secs % 86400) // 3600,
        "minutes": (secs % 3600) // 60,
        "seconds": secs % 60,
    })


@endpoint()
def age_calc(request):
    """92. 年龄计算。"""
    birth = _parse(req_str(request, "birth_date"))
    today = date.today()
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    months = today.month - birth.month - (today.day < birth.day)
    if months < 0:
        months += 12
    days = (today - date(today.year, today.month, birth.day)).days if today.day >= birth.day else (today - date(today.year, today.month - 1, birth.day)).days
    return ok({"years": years, "months": months, "days": max(0, days)})


_ZODIAC = [(1, 20, "摩羯座", "土象"), (2, 19, "水瓶座", "风象"), (3, 21, "双鱼座", "水象"),
           (4, 20, "白羊座", "火象"), (5, 21, "金牛座", "土象"), (6, 21, "双子座", "风象"),
           (7, 23, "巨蟹座", "水象"), (8, 23, "狮子座", "火象"), (9, 23, "处女座", "土象"),
           (10, 24, "天秤座", "风象"), (11, 23, "天蝎座", "水象"), (12, 22, "射手座", "火象"),
           (12, 32, "摩羯座", "土象")]


@endpoint()
def zodiac(request):
    """93. 星座计算。"""
    m = int(req_num(request, "month", minimum=1, maximum=12, integer=True))
    d = int(req_num(request, "day", minimum=1, maximum=31, integer=True))
    for mm, dd, name, element in _ZODIAC:
        if m == mm and d <= dd:
            return ok({"zodiac": name, "element": element})
        if m == mm - 1:
            pass
    # fallback: 找第一个 (month,day) >= (m,d) 的
    for mm, dd, name, element in _ZODIAC:
        if (m, d) <= (mm, dd):
            return ok({"zodiac": name, "element": element})
    return ok({"zodiac": "摩羯座", "element": "土象"})


_ANIMALS = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
_BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]


@endpoint()
def chinese_zodiac(request):
    """94. 生肖计算。"""
    y = int(req_num(request, "year", minimum=1, maximum=9999, integer=True))
    idx = (y - 4) % 12
    return ok({"zodiac": _ANIMALS[idx], "earthly_branch": _BRANCHES[idx]})


_STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]


@endpoint()
def tiangan_dizhi(request):
    """95. 天干地支。"""
    y = int(req_num(request, "year", minimum=4, maximum=9999, integer=True))
    stem = _STEMS[(y - 4) % 10]
    branch = _BRANCHES[(y - 4) % 12]
    return ok({"ganzhi": stem + branch, "gan": stem, "zhi": branch})


@endpoint()
def holiday_check(request):
    """96. 中国节假日判断（基于周末+固定节日估算）。"""
    d = _parse(req_str(request, "date")).date()
    if d.weekday() >= 5:
        return ok({"is_holiday": True, "name": "周末"})
    festivals = {(1, 1): "元旦", (5, 1): "劳动节", (10, 1): "国庆节",
                 (1, 1): "元旦", (4, 5): "清明节", (6, 1): "儿童节"}
    name = festivals.get((d.month, d.day), "")
    if name:
        return ok({"is_holiday": True, "name": name})
    return ok({"is_holiday": False, "name": ""})


@endpoint()
def workdays(request):
    """97. 工作日计算（排除周末）。"""
    start = _parse(req_str(request, "start")).date()
    end = _parse(req_str(request, "end")).date()
    if start > end:
        raise ValueError("start 不能晚于 end")
    work = 0
    weekend = 0
    cur = start
    while cur <= end:
        if cur.weekday() >= 5:
            weekend += 1
        else:
            work += 1
        cur += timedelta(days=1)
    return ok({"workdays": work, "weekends": weekend})


@endpoint()
def date_range(request):
    """98. 日期范围生成。step: 步长（天）。"""
    start = _parse(req_str(request, "start")).date()
    end = _parse(req_str(request, "end")).date()
    step = int(opt_num(request, "step", 1, minimum=1, maximum=365, integer=True))
    if start > end:
        raise ValueError("start 不能晚于 end")
    out = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=step)
    return ok({"dates": out})


@endpoint()
def relative_time(request):
    """99. 相对时间描述。"""
    dt = _parse(req_str(request, "datetime"))
    now = datetime.now()
    delta = (now - dt).total_seconds()
    future = delta < 0
    delta = abs(delta)
    if delta < 60:
        desc = "刚刚"
    elif delta < 3600:
        desc = f"{int(delta // 60)} 分钟"
    elif delta < 86400:
        desc = f"{int(delta // 3600)} 小时"
    elif delta < 86400 * 30:
        desc = f"{int(delta // 86400)} 天"
    elif delta < 86400 * 365:
        desc = f"{int(delta // (86400 * 30))} 个月"
    else:
        desc = f"{int(delta // (86400 * 365))} 年"
    if future:
        desc = desc + "后"
    elif desc != "刚刚":
        desc = desc + "前"
    return ok({"description": desc})


_TZ_OFFSETS = {"UTC": 0, "伦敦": 0, "北京": 8, "上海": 8, "东京": 9,
               "纽约": -5, "洛杉矶": -8, "巴黎": 1, "莫斯科": 3, "悉尼": 10, "迪拜": 4}


@endpoint()
def timezone_convert(request):
    """100. 时区转换（主要城市）。"""
    dt = _parse(req_str(request, "datetime"))
    from_tz = opt_str(request, "from_tz", "北京")
    to_tz = opt_str(request, "to_tz", "UTC")
    if from_tz not in _TZ_OFFSETS or to_tz not in _TZ_OFFSETS:
        raise ValueError(f"支持的时区: {list(_TZ_OFFSETS.keys())}")
    diff = _TZ_OFFSETS[to_tz] - _TZ_OFFSETS[from_tz]
    result = dt + timedelta(hours=diff)
    return ok({"result": result.strftime("%Y-%m-%d %H:%M:%S"), "from_tz": from_tz, "to_tz": to_tz})


@endpoint()
def format(request):
    """101. 日期格式化。"""
    d = _parse(req_str(request, "date"))
    fmt = opt_str(request, "format", "%Y-%m-%d")
    try:
        return ok({"result": d.strftime(fmt)})
    except Exception as e:
        raise ValueError(f"格式错误: {e}")


@endpoint()
def iso_week(request):
    """102. ISO 周数计算。"""
    d = _parse(req_str(request, "date")).date()
    iso = d.isocalendar()
    return ok({"week": iso[1], "year": iso[0]})


@endpoint()
def sunrise_sunset(request):
    """103. 日出日落估算（简化模型）。"""
    lat = req_num(request, "lat", minimum=-90, maximum=90)
    lng = req_num(request, "lng", minimum=-180, maximum=180)
    d = _parse(req_str(request, "date")).date()
    # 简化：基于日期的日长模型
    day_of_year = d.timetuple().tm_yday
    decl = 23.45 * math.sin(math.radians(360 / 365 * (284 + day_of_year)))
    lat_r = math.radians(lat)
    decl_r = math.radians(decl)
    cos_h = -math.tan(lat_r) * math.tan(decl_r)
    cos_h = max(-1, min(1, cos_h))
    h = math.degrees(math.acos(cos_h)) / 15.0
    day_length = h * 2
    noon = 12 - lng / 15.0
    sunrise = noon - h
    sunset = noon + h
    def _fmt(t):
        t = t % 24
        return f"{int(t):02d}:{int((t % 1) * 60):02d}"
    return ok({"sunrise": _fmt(sunrise), "sunset": _fmt(sunset), "day_length": round(day_length, 2)})


@endpoint()
def easter_calc(request):
    """104. 复活节计算（Meeus 算法）。"""
    y = int(req_num(request, "year", minimum=1583, maximum=4000, integer=True))
    a = y % 19
    b = y // 100
    c = y % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return ok({"date": date(y, month, day).isoformat()})


@endpoint()
def week_of_month(request):
    """105. 当月第几周。"""
    d = _parse(req_str(request, "date")).date()
    first = date(d.year, d.month, 1)
    return ok({"week_of_month": (d.day - 1 + first.weekday()) // 7 + 1})
