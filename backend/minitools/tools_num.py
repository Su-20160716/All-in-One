# -*- coding: utf-8 -*-
"""minitools · 数字数学家族（28 个，编号 31-58）。"""
import math
import random
from collections import Counter
from decimal import Decimal, getcontext

from .common import (endpoint, ok, opt_bool, opt_num, opt_str, req_list,
                     req_num, req_str)

getcontext().prec = 50

_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ["", "拾", "佰", "仟"]
_CN_BIG = ["", "万", "亿", "万亿"]

_EN_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
            "seventeen", "eighteen", "nineteen"]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_EN_SCALES = ["", "thousand", "million", "billion", "trillion"]


def _three_digit_to_en(n):
    parts = []
    if n >= 100:
        parts.append(_EN_ONES[n // 100])
        parts.append("hundred")
        n %= 100
    if n >= 20:
        parts.append(_EN_TENS[n // 10])
        if n % 10:
            parts.append(_EN_ONES[n % 10])
    elif n > 0:
        parts.append(_EN_ONES[n])
    return " ".join(parts)


@endpoint()
def to_chinese_upper(request):
    """31. 数字转中文大写（金额）。"""
    number = req_num(request, "number")
    n = Decimal(str(number))
    if n < 0:
        return ok({"result": "负" + _to_cn_upper(-n)})
    return ok({"result": _to_cn_upper(n)})


def _to_cn_upper(n):
    if n == 0:
        return "零元整"
    int_part = int(n)
    frac = int(round((n - int_part) * 100))
    # 整数部分
    if int_part == 0:
        int_str = ""
    else:
        groups = []
        while int_part > 0:
            groups.append(int_part % 10000)
            int_part //= 10000
        parts = []
        for i, g in enumerate(groups):
            if g == 0:
                continue
            g_str = _four_digit_cn(g)
            parts.append(g_str + _CN_BIG[i])
        int_str = "".join(reversed(parts)) + "元"
    if frac == 0:
        return int_str + "整"
    jiao = frac // 10
    fen = frac % 10
    tail = ""
    if jiao:
        tail += _CN_DIGITS[jiao] + "角"
    if fen:
        tail += _CN_DIGITS[fen] + "分"
    return int_str + tail


def _four_digit_cn(n):
    s = str(n).zfill(4)
    out = []
    zero_pending = False
    for i, ch in enumerate(s):
        d = int(ch)
        unit = _CN_UNITS[3 - i]
        if d == 0:
            zero_pending = bool(out)
        else:
            if zero_pending:
                out.append("零")
                zero_pending = False
            out.append(_CN_DIGITS[d] + unit)
    return "".join(out)


@endpoint()
def to_english_words(request):
    """32. 数字转英文单词。"""
    number = req_num(request, "number")
    n = int(number)
    if n == 0:
        return ok({"result": "zero"})
    neg = n < 0
    n = abs(n)
    groups = []
    while n > 0:
        groups.append(n % 1000)
        n //= 1000
    parts = []
    for i, g in enumerate(groups):
        if g == 0:
            continue
        chunk = _three_digit_to_en(g)
        if _EN_SCALES[i]:
            chunk += " " + _EN_SCALES[i]
        parts.append(chunk)
    result = " ".join(reversed(parts))
    if neg:
        result = "negative " + result
    return ok({"result": result})


_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


@endpoint()
def roman_convert(request):
    """33. 罗马数字互转。direction: int2roman / roman2int。"""
    value = req_str(request, "value")
    direction = opt_str(request, "direction", "int2roman")
    if direction == "int2roman":
        n = int(req_num(request, "value", minimum=1, maximum=3999, integer=True))
        out = []
        for v, sym in _ROMAN:
            while n >= v:
                out.append(sym)
                n -= v
        return ok({"result": "".join(out)})
    if direction == "roman2int":
        s = value.strip().upper()
        roman_map = {sym: v for v, sym in _ROMAN}
        total = 0
        prev = 0
        for ch in reversed(s):
            v = roman_map.get(ch, 0)
            if v < prev:
                total -= v
            else:
                total += v
            prev = v
        return ok({"result": total})
    raise ValueError("direction 必须是 int2roman 或 roman2int")


@endpoint()
def prime_factorize(request):
    """34. 质因数分解。"""
    n = int(req_num(request, "number", minimum=2, maximum=10**12, integer=True))
    orig = n
    factors = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1
    if n > 1:
        factors.append(n)
    return ok({"number": orig, "factors": factors})


@endpoint()
def perfect_number(request):
    """35. 完全数判断。"""
    n = int(req_num(request, "number", minimum=1, maximum=10**7, integer=True))
    divisors = []
    s = 0
    for i in range(1, int(math.isqrt(n)) + 1):
        if n % i == 0:
            if i != n:
                divisors.append(i)
                s += i
            if i != n // i and n // i != n:
                divisors.append(n // i)
                s += n // i
    divisors.sort()
    return ok({"is_perfect": s == n, "divisors": divisors})


@endpoint()
def fibonacci(request):
    """36. 斐波那契数列。n: 个数；start: 起始值（默认0）。"""
    n = int(req_num(request, "n", minimum=1, maximum=100, integer=True))
    start = int(opt_num(request, "start", 0, integer=True))
    seq = [start, start + 1]
    for _ in range(n - 2):
        seq.append(seq[-1] + seq[-2])
    return ok({"sequence": seq[:n]})


@endpoint()
def factorial(request):
    """37. 阶乘。"""
    n = int(req_num(request, "n", minimum=0, maximum=1000, integer=True))
    return ok({"result": str(math.factorial(n))})


@endpoint()
def power_calc(request):
    """38. 幂运算（含大数）。"""
    base = req_num(request, "base")
    exponent = req_num(request, "exponent")
    result = Decimal(str(base)) ** Decimal(str(exponent))
    return ok({"result": format(result, "f")})


@endpoint()
def percentage_calc(request):
    """39. 百分比计算。part/ total。"""
    part = req_num(request, "part")
    total = req_num(request, "total")
    if total == 0:
        raise ValueError("total 不能为 0")
    pct = part / total * 100
    return ok({"percent": round(pct, 4), "part_of": f"{part}/{total}"})


@endpoint()
def discount_calc(request):
    """40. 折扣计算。discount 为折扣率（如 0.8 = 8折）。"""
    price = req_num(request, "price", minimum=0)
    discount = req_num(request, "discount", minimum=0, maximum=1)
    final = price * discount
    return ok({"final": round(final, 2), "saved": round(price - final, 2)})


@endpoint()
def compound_interest(request):
    """41. 复利计算。freq: 每年复利次数。"""
    principal = req_num(request, "principal", minimum=0)
    rate = req_num(request, "rate", minimum=0) / 100
    years = req_num(request, "years", minimum=0)
    freq = int(opt_num(request, "freq", 1, minimum=1, maximum=365, integer=True))
    final = principal * (1 + rate / freq) ** (freq * years)
    return ok({"final": round(final, 2), "interest": round(final - principal, 2)})


@endpoint()
def loan_payment(request):
    """42. 贷款月供（等额本息）。rate 为年利率%。"""
    principal = req_num(request, "principal", minimum=0)
    rate = req_num(request, "rate", minimum=0) / 100 / 12
    months = int(req_num(request, "months", minimum=1, maximum=600, integer=True))
    if rate == 0:
        monthly = principal / months
    else:
        monthly = principal * rate * (1 + rate) ** months / ((1 + rate) ** months - 1)
    return ok({"monthly": round(monthly, 2), "total": round(monthly * months, 2)})


@endpoint()
def bmi_calc(request):
    """43. BMI 计算。"""
    h = req_num(request, "height_cm", minimum=50, maximum=250) / 100
    w = req_num(request, "weight_kg", minimum=10, maximum=300)
    bmi = w / (h * h)
    if bmi < 18.5:
        cat = "偏瘦"
    elif bmi < 24:
        cat = "正常"
    elif bmi < 28:
        cat = "超重"
    else:
        cat = "肥胖"
    return ok({"bmi": round(bmi, 2), "category": cat})


@endpoint()
def triangle_area(request):
    """44. 三角形面积（海伦公式）。"""
    a = req_num(request, "a", minimum=0)
    b = req_num(request, "b", minimum=0)
    c = req_num(request, "c", minimum=0)
    valid = a + b > c and a + c > b and b + c > a
    if not valid:
        return ok({"area": 0, "valid": False})
    s = (a + b + c) / 2
    area = math.sqrt(max(0, s * (s - a) * (s - b) * (s - c)))
    return ok({"area": round(area, 4), "valid": True})


@endpoint()
def circle_calc(request):
    """45. 圆面积/周长。"""
    r = req_num(request, "radius", minimum=0)
    return ok({"area": round(math.pi * r * r, 4), "circumference": round(2 * math.pi * r, 4)})


@endpoint()
def sphere_calc(request):
    """46. 球体积/表面积。"""
    r = req_num(request, "radius", minimum=0)
    return ok({"volume": round(4 / 3 * math.pi * r ** 3, 4), "surface": round(4 * math.pi * r * r, 4)})


@endpoint()
def percent_change(request):
    """47. 百分比变化。"""
    old = req_num(request, "old")
    new = req_num(request, "new")
    if old == 0:
        raise ValueError("old 不能为 0")
    chg = (new - old) / abs(old) * 100
    direction = "上升" if chg > 0 else ("下降" if chg < 0 else "不变")
    return ok({"change": round(chg, 4), "direction": direction})


@endpoint()
def weighted_average(request):
    """48. 加权平均。"""
    values = req_list(request, "values")
    weights = req_list(request, "weights")
    if len(values) != len(weights):
        raise ValueError("values 与 weights 长度必须一致")
    num = sum(float(v) * float(w) for v, w in zip(values, weights))
    den = sum(float(w) for w in weights)
    if den == 0:
        raise ValueError("weights 之和不能为 0")
    return ok({"result": round(num / den, 4)})


@endpoint()
def std_variance(request):
    """49. 标准差/方差。"""
    values = [float(v) for v in req_list(request, "values")]
    if len(values) < 2:
        raise ValueError("至少需要 2 个数据点")
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return ok({"std": round(math.sqrt(var), 4), "variance": round(var, 4), "mean": round(mean, 4)})


@endpoint()
def median_mode(request):
    """50. 中位数/众数。"""
    values = sorted(float(v) for v in req_list(request, "values"))
    n = len(values)
    if n == 0:
        raise ValueError("values 不能为空")
    if n % 2:
        median = values[n // 2]
    else:
        median = (values[n // 2 - 1] + values[n // 2]) / 2
    cnt = Counter(values)
    max_c = max(cnt.values())
    mode = [k for k, v in cnt.items() if v == max_c]
    return ok({"median": median, "mode": mode})


@endpoint()
def linear_interpolate(request):
    """51. 线性插值。"""
    x0 = req_num(request, "x0")
    y0 = req_num(request, "y0")
    x1 = req_num(request, "x1")
    y1 = req_num(request, "y1")
    x = req_num(request, "x")
    if x1 == x0:
        raise ValueError("x1 不能等于 x0")
    y = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ok({"y": round(y, 4)})


@endpoint()
def format_thousands(request):
    """52. 数字千分位格式化。"""
    number = req_num(request, "number")
    decimals = int(opt_num(request, "decimals", 2, minimum=0, maximum=10, integer=True))
    return ok({"result": f"{number:,.{decimals}f}"})


@endpoint()
def random_range(request):
    """53. 随机数生成。unique: 是否去重。"""
    lo = req_num(request, "min", integer=True)
    hi = req_num(request, "max", integer=True)
    count = int(opt_num(request, "count", 1, minimum=1, maximum=10000, integer=True))
    unique = opt_bool(request, "unique", False)
    lo, hi = int(lo), int(hi)
    if lo > hi:
        raise ValueError("min 不能大于 max")
    if unique:
        if count > hi - lo + 1:
            raise ValueError("区间内唯一数不足")
        nums = random.sample(range(lo, hi + 1), count)
    else:
        nums = [random.randint(lo, hi) for _ in range(count)]
    return ok({"numbers": nums})


@endpoint()
def shuffle_list(request):
    """54. 随机洗牌。"""
    items = req_list(request, "items")
    shuffled = list(items)
    random.shuffle(shuffled)
    return ok({"shuffled": shuffled})


@endpoint()
def permutation_combination(request):
    """55. 排列组合计算。"""
    n = int(req_num(request, "n", minimum=0, integer=True))
    k = int(req_num(request, "k", minimum=0, integer=True))
    if k > n:
        raise ValueError("k 不能大于 n")
    perm = math.perm(n, k)
    comb = math.comb(n, k)
    return ok({"permutation": perm, "combination": comb})


@endpoint()
def log_calc(request):
    """56. 对数计算（任意底）。"""
    value = req_num(request, "value", minimum=0.000001)
    base = req_num(request, "base", minimum=0.000001)
    return ok({"result": round(math.log(value, base), 6)})


@endpoint()
def angle_radian(request):
    """57. 角度弧度互转。direction: deg2rad / rad2deg。"""
    value = req_num(request, "value")
    direction = opt_str(request, "direction", "deg2rad")
    if direction == "deg2rad":
        return ok({"result": round(math.radians(value), 6)})
    if direction == "rad2deg":
        return ok({"result": round(math.degrees(value), 6)})
    raise ValueError("direction 必须是 deg2rad 或 rad2deg")


@endpoint()
def trig_calc(request):
    """58. 三角函数。func: sin/cos/tan；unit: deg/rad。"""
    value = req_num(request, "value")
    func = opt_str(request, "func", "sin")
    unit = opt_str(request, "unit", "deg")
    rad = math.radians(value) if unit == "deg" else value
    funcs = {"sin": math.sin, "cos": math.cos, "tan": math.tan}
    if func not in funcs:
        raise ValueError("func 必须是 sin/cos/tan")
    return ok({"result": round(funcs[func](rad), 6)})
