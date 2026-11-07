# -*- coding: utf-8 -*-
"""minitools · 职场计算家族 work（第三轮 S26：399–402）。

gpa-calc / annual-leave / overtime-pay / severance-pay 全部为纯计算，
不读写数据库、不调用外部服务；口径写在各自 docstring 与返回的 basis/breakdown 里。
"""
from datetime import date

from .common import endpoint, ok, opt_bool, opt_num, opt_str, req_list, req_num, req_str

# 法定口径常量
MONTHLY_WORK_DAYS = 21.75          # 人社部月计薪天数
DAILY_HOURS = 8
OVERTIME_RATES = {
    "weekday": (1.5, "工作日加班"),
    "workday": (1.5, "工作日加班"),
    "weekend": (2.0, "休息日加班（未安排补休）"),
    "rest": (2.0, "休息日加班（未安排补休）"),
    "holiday": (3.0, "法定节假日加班"),
    "statutory": (3.0, "法定节假日加班"),
}


# =====================================================================
# 399 GPA 换算
# =====================================================================

# 常见 4.0 分制（北大/多数高校）百分制 → 绩点
_GPA_4_TABLE = [
    (90, 4.0), (85, 3.7), (82, 3.3), (78, 3.0), (75, 2.7),
    (72, 2.3), (68, 2.0), (64, 1.5), (60, 1.0),
]


def _point_standard(score, scale):
    for lo, pt in _GPA_4_TABLE:
        if score >= lo:
            return round(pt * scale / 4.0, 3)
    return 0.0


def _point_linear(score, scale):
    return round(min(scale, max(0.0, score / 100.0 * scale)), 3)


@endpoint()
def gpa_calc(request):
    """GPA 换算：courses[{credit, score}] → 加权 GPA + 加权均分（scale 默认 4.0）。

    method=standard（分段表，默认）| linear（score/100*scale）；
    也可给单门课直接传 point/gpa 覆盖换算结果。
    """
    courses = req_list(request, "courses", max_len=200)
    if not courses:
        raise ValueError("courses 不能为空")
    scale = float(opt_num(request, "scale", 4.0, minimum=1.0, maximum=5.0))
    method = opt_str(request, "method", "standard").lower()
    if method not in ("standard", "linear"):
        raise ValueError("method 支持 standard/linear")

    rows, credits, point_sum, score_sum = [], 0.0, 0.0, 0.0
    bands = {"90+": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
    for idx, item in enumerate(courses):
        if not isinstance(item, dict):
            raise ValueError("courses 每项需为 {credit, score, name?}")
        try:
            credit = float(item.get("credit", item.get("credits", 1)))
            score = float(item.get("score", item.get("points")))
        except (TypeError, ValueError):
            raise ValueError(f"第 {idx + 1} 门课 credit/score 必须是数字")
        if credit <= 0:
            raise ValueError(f"第 {idx + 1} 门课学分必须大于 0")
        if not 0 <= score <= 100:
            raise ValueError(f"第 {idx + 1} 门课分数需在 0–100（当前 {score}）")
        override = item.get("point", item.get("gpa"))
        if override is not None:
            try:
                point = float(override)
            except (TypeError, ValueError):
                raise ValueError(f"第 {idx + 1} 门课 point 必须是数字")
            point = round(min(scale, max(0.0, point)), 3)
            source = "override"
        else:
            point = _point_standard(score, scale) if method == "standard" else _point_linear(score, scale)
            source = method
        band = ("90+" if score >= 90 else "80-89" if score >= 80 else
                "70-79" if score >= 70 else "60-69" if score >= 60 else "<60")
        bands[band] += 1
        credits += credit
        point_sum += credit * point
        score_sum += credit * score
        rows.append({"name": str(item.get("name") or f"课程{idx + 1}")[:60],
                     "credit": round(credit, 2), "score": round(score, 2),
                     "point": point, "source": source, "band": band})
    if credits <= 0:
        raise ValueError("学分合计必须大于 0")
    return ok({
        "scale": scale,
        "method": method,
        "gpa": round(point_sum / credits, 3),
        "average": round(score_sum / credits, 2),
        "total_credits": round(credits, 2),
        "count": len(rows),
        "bands": bands,
        "courses": rows,
        "summary": f"{len(rows)} 门课 / {round(credits, 2)} 学分 → 加权 GPA {round(point_sum / credits, 3)}（{scale} 分制）",
    })


# =====================================================================
# 400 年假折算
# =====================================================================


def _parse_date(raw, key):
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"缺少必填参数: {key}")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise ValueError(f"{key} 需为 YYYY-MM-DD 格式")


def _entitled_days(years):
    """工龄 → 法定年假天数（<1 年 0 天 / 1–10 年 5 天 / 10–20 年 10 天 / ≥20 年 15 天）。"""
    if years < 1:
        return 0, "累计工龄不满 1 年，当年不享受带薪年休假"
    if years < 10:
        return 5, "累计工龄满 1 年不满 10 年，年休假 5 天"
    if years < 20:
        return 10, "累计工龄满 10 年不满 20 年，年休假 10 天"
    return 15, "累计工龄满 20 年以上，年休假 15 天"


@endpoint()
def annual_leave(request):
    """年假折算：hire_date/as_of → 工龄、应享天数、当年可休（入职当年按剩余日历天折算）。"""
    hire = _parse_date(req_str(request, "hire_date"), "hire_date")
    as_of = _parse_date(opt_str(request, "as_of") or date.today().isoformat(), "as_of")
    if hire > as_of:
        raise ValueError("hire_date 不能晚于 as_of")

    years = as_of.year - hire.year - ((as_of.month, as_of.day) < (hire.month, hire.day))
    months = (as_of.year - hire.year) * 12 + (as_of.month - hire.month) - (1 if as_of.day < hire.day else 0)
    entitled, basis = _entitled_days(years)

    year_end = date(as_of.year, 12, 31)
    remaining = (year_end - max(hire, date(as_of.year, 1, 1))).days + 1
    prorated = hire.year == as_of.year
    days = round(entitled * remaining / 365, 2) if prorated else float(entitled)

    basis_list = [basis]
    if prorated:
        basis_list.append(f"本年度入职，按剩余 {remaining} 天折算：{entitled} × {remaining}/365 = {days} 天")

    # 下一档提示
    next_tier = None
    for threshold, next_days in ((1, 5), (10, 10), (20, 15)):
        if years < threshold:
            next_tier = {"years": threshold, "days": next_days,
                         "in_years": round(threshold - years - 1, 2)}
            break
    anniversary = date(as_of.year if (as_of.month, as_of.day) < (hire.month, hire.day) else as_of.year + 1,
                       hire.month, hire.day)
    return ok({
        "hire_date": hire.isoformat(),
        "as_of": as_of.isoformat(),
        "service_years": years,
        "service_months": max(0, months),
        "tier": ("<1 年" if years < 1 else "1–10 年" if years < 10 else "10–20 年" if years < 20 else "≥20 年"),
        "entitled_days": entitled,
        "days": days,
        "prorated": prorated,
        "remaining_days_in_year": remaining,
        "basis": "；".join(basis_list),
        "basis_list": basis_list,
        "next_tier": next_tier,
        "next_anniversary": anniversary.isoformat(),
        "days_to_anniversary": (anniversary - as_of).days,
    })


# =====================================================================
# 401 加班费
# =====================================================================


@endpoint()
def overtime_pay(request):
    """加班费：monthly_salary/hours/kind → 时薪（月薪÷21.75÷8）× 1.5/2/3 倍。"""
    monthly = float(req_num(request, "monthly_salary", minimum=0, maximum=10_000_000))
    hours = float(req_num(request, "hours", minimum=0.01, maximum=1000))
    kind = opt_str(request, "kind", "weekday").strip().lower()
    if kind not in OVERTIME_RATES:
        raise ValueError("kind 支持 weekday/weekend/holiday")
    multiplier, kind_name = OVERTIME_RATES[kind]

    day_rate = monthly / MONTHLY_WORK_DAYS
    hourly = day_rate / DAILY_HOURS
    pay = hourly * hours * multiplier
    return ok({
        "monthly_salary": round(monthly, 2),
        "kind": kind,
        "kind_name": kind_name,
        "multiplier": multiplier,
        "hours": round(hours, 2),
        "monthly_work_days": MONTHLY_WORK_DAYS,
        "daily_hours": DAILY_HOURS,
        "day_rate": round(day_rate, 2),
        "hourly_rate": round(hourly, 4),
        "pay": round(pay, 2),
        "breakdown": (f"时薪 = {round(monthly, 2)} ÷ {MONTHLY_WORK_DAYS} ÷ {DAILY_HOURS} = {round(hourly, 2)} 元；"
                      f"{round(hours, 2)} 小时 × {multiplier} 倍 = {round(pay, 2)} 元"),
        "summary": f"{kind_name} {round(hours, 2)} 小时应发加班费 {round(pay, 2)} 元",
    })


# =====================================================================
# 402 经济补偿金
# =====================================================================


def _severance_months(years):
    """工作年限 → 补偿月数：满 1 年 1 个月，6 个月以上不满 1 年按 1 年，不满 6 个月按半个月。"""
    full = int(years)
    rest = years - full
    if rest >= 0.5:
        return full + 1, "剩余满 6 个月以上按 1 年计"
    if rest > 0:
        return full + 0.5, "剩余不满 6 个月按半个月计"
    return full, "整年计"


@endpoint()
def severance_pay(request):
    """经济补偿金：salary/years/cap（三倍社平月薪）→ N / N+1 金额与封顶说明。"""
    salary = float(req_num(request, "salary", minimum=0, maximum=10_000_000))
    years = float(req_num(request, "years", minimum=0, maximum=60))
    cap_raw = opt_num(request, "cap", None, minimum=0, maximum=10_000_000)
    cap = float(cap_raw) if cap_raw is not None else None
    plus_one = opt_bool(request, "plus_one", True)
    if salary <= 0:
        raise ValueError("salary 必须大于 0")

    months, months_basis = _severance_months(years)
    base = salary
    capped = False
    note = []
    if cap and salary > cap:
        base = cap
        capped = True
        if months > 12:
            months = 12.0
            note.append("月工资高于社平三倍，补偿年限最多按 12 年计")
        note.append(f"月工资高于社平三倍（{round(cap, 2)}），补偿基数按 {round(cap, 2)} 元封顶")
    amount = base * months
    notice = base if plus_one else 0.0
    return ok({
        "salary": round(salary, 2),
        "years": round(years, 2),
        "cap": round(cap, 2) if cap else None,
        "base_salary": round(base, 2),
        "capped": capped,
        "months": months,
        "months_basis": months_basis,
        "amount": round(amount, 2),
        "notice_pay": round(notice, 2),
        "amount_n_plus_1": round(amount + notice, 2),
        "formula": f"N = {months} 个月 × {round(base, 2)} 元 = {round(amount, 2)} 元"
                   + (f"；N+1 含代通知金 {round(notice, 2)} 元 = {round(amount + notice, 2)} 元" if plus_one else ""),
        "notes": note,
        "summary": f"经济补偿金 N = {round(amount, 2)} 元" + (f"，N+1 = {round(amount + notice, 2)} 元" if plus_one else ""),
    })
