# -*- coding: utf-8 -*-
"""minitools · 科学计算家族（13 个）。

去重：minitools/num 有 trig/log/power；convert 有 pressure/energy；
dataintel/stats 有假设检验；这里做物理化学公式与概率分布 pmf/pdf。
"""
import math

from .common import endpoint, ok, opt_num, req_num, opt_str


@endpoint()
def kinematics(request):
    """SC01. 匀加速运动：v = u + at, s = ut + 0.5 a t², v² = u² + 2as。"""
    u = req_num(request, "u", minimum=0)
    a = req_num(request, "a")
    t = req_num(request, "t", minimum=0)
    v = u + a * t
    s = u * t + 0.5 * a * t * t
    return ok({"v": round(v, 3), "s": round(s, 3)})


@endpoint()
def newton(request):
    """SC02. 牛顿第二定律 F = ma。"""
    m = req_num(request, "mass_kg", minimum=0)
    a = req_num(request, "accel_m_s2")
    return ok({"force_n": round(m * a, 3)})


@endpoint()
def ohm(request):
    """SC03. 欧姆定律 V = IR。"""
    v = opt_num(request, "voltage")
    i = opt_num(request, "current")
    r = opt_num(request, "resistance")
    if v is not None and i is not None:
        return ok({"voltage": v, "current": i, "resistance": round(v / i, 3)})
    if v is not None and r is not None:
        return ok({"voltage": v, "current": round(v / r, 4), "resistance": r})
    if i is not None and r is not None:
        return ok({"voltage": round(i * r, 3), "current": i, "resistance": r})
    raise ValueError("需提供 V/I/R 中任意两个")


@endpoint()
def normal_dist(request):
    """SC04. 正态分布 PDF/CDF。"""
    x = req_num(request, "x")
    mu = opt_num(request, "mu", default=0)
    sigma = opt_num(request, "sigma", default=1, minimum=1e-9)
    pdf = math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
    cdf = 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))
    return ok({"pdf": round(pdf, 6), "cdf": round(cdf, 6)})


@endpoint()
def poisson(request):
    """SC05. 泊松分布 P(X=k) = λ^k e^-λ / k!。"""
    lam = req_num(request, "lambda", minimum=0)
    k = int(req_num(request, "k", minimum=0))
    p = lam ** k * math.exp(-lam) / math.factorial(k)
    return ok({"prob": round(p, 6), "mean": lam, "variance": lam})


@endpoint()
def molarity(request):
    """SC06. 摩尔浓度 c = n / V = m / (M·V_L)。"""
    mass_g = req_num(request, "mass_g", minimum=0)
    mw = req_num(request, "molar_mass", minimum=0.0001)
    volume_ml = req_num(request, "volume_ml", minimum=0.0001)
    c = (mass_g / mw) / (volume_ml / 1000.0)
    return ok({"molarity_mol_L": round(c, 4)})


@endpoint()
def ph(request):
    """SC07. pH 与 [H+] 互算。"""
    mode = opt_str(request, "mode", "h_to_ph")
    if mode == "h_to_ph":
        h = req_num(request, "h_concentration", minimum=1e-14)
        return ok({"ph": round(-math.log10(h), 3), "h_concentration": h})
    ph = req_num(request, "ph", minimum=0, maximum=14)
    return ok({"ph": ph, "h_concentration": 10 ** (-ph)})


@endpoint()
def gas_law(request):
    """SC08. 理想气体定律 PV = nRT，R=8.314。"""
    p = opt_num(request, "pressure_pa")
    v = opt_num(request, "volume_m3")
    n = opt_num(request, "moles")
    t = opt_num(request, "temperature_k", minimum=0)
    R = 8.314
    if p is not None and v is not None and t is not None:
        return ok({"moles": round(p * v / (R * t), 4)})
    if n is not None and v is not None and t is not None:
        return ok({"pressure_pa": round(n * R * t / v, 2)})
    if p is not None and n is not None and t is not None:
        return ok({"volume_m3": round(n * R * t / p, 5)})
    raise ValueError("需提供 PV=nRT 中任意三个量")


@endpoint()
def wave(request):
    """SC09. 波长↔频率 c = λf（光速 3e8 m/s）。"""
    c = 3e8
    mode = opt_str(request, "mode", "freq_to_wave")
    if mode == "freq_to_wave":
        f = req_num(request, "freq_hz", minimum=0)
        return ok({"freq_hz": f, "wavelength_m": round(c / f, 6) if f else None})
    lam = req_num(request, "wavelength_m", minimum=0.000001)
    return ok({"freq_hz": round(c / lam, 2), "wavelength_m": lam})


@endpoint()
def half_life(request):
    """SC10. 半衰期剩余量 N = N0 · (1/2)^(t/T)。"""
    n0 = req_num(request, "initial", minimum=0)
    half = req_num(request, "half_life", minimum=0.0001)
    t = req_num(request, "time", minimum=0)
    n = n0 * (0.5 ** (t / half))
    return ok({"remaining": round(n, 4), "ratio": round(n / n0, 4) if n0 else 0})


@endpoint()
def sigfigs(request):
    """SC11. 有效数字位数。"""
    raw = str(req_num(request, "number"))
    s = raw.lstrip("+").lstrip("-")
    if "e" in s or "E" in s:
        s = s.split("e")[0].split("E")[0]
    if "." in s:
        int_part, frac = s.split(".", 1)
        if int_part == "0":
            digits = frac.lstrip("0")
        else:
            digits = int_part + frac
    else:
        # 无小数点：末尾零不计
        digits = s.rstrip("0") or "0"
    count = sum(1 for ch in digits if ch.isdigit())
    return ok({"number": raw, "sigfigs": count})


@endpoint()
def error_propagation(request):
    """SC12. 误差传播：和/差绝对误差相加；积/商相对误差相加。

    values: [x, y]; errors: [dx, dy]; op: add/sub/mul/div。
    """
    values = req_num_v(request)
    errors = req_num_e(request)
    op = opt_str(request, "op", "add")
    x, y = values
    dx, dy = errors
    if op in ("add", "sub"):
        result = x + y if op == "add" else x - y
        derr = math.sqrt(dx ** 2 + dy ** 2)
    else:
        result = x * y if op == "mul" else x / y
        rel = math.sqrt((dx / x) ** 2 + (dy / y) ** 2)
        derr = abs(result) * rel
    return ok({"result": round(result, 4), "abs_error": round(derr, 4),
               "rel_error_pct": round(derr / abs(result) * 100, 3) if result else 0})


def req_num_v(request):
    from .common import req_list
    v = req_list(request, "values")
    if len(v) != 2:
        raise ValueError("values 需要 2 个数字")
    return float(v[0]), float(v[1])


def req_num_e(request):
    from .common import req_list
    v = req_list(request, "errors")
    if len(v) != 2:
        raise ValueError("errors 需要 2 个非负数字")
    return float(v[0]), float(v[1])


@endpoint()
def reaction_yield(request):
    """SC13. 化学反应产率 = 实际 / 理论 × 100%。"""
    actual = req_num(request, "actual", minimum=0)
    theoretical = req_num(request, "theoretical", minimum=0.0001)
    pct = actual / theoretical * 100.0
    return ok({"yield_pct": round(pct, 2)})
