# -*- coding: utf-8 -*-
"""dataintel 统计工具函数：正态/卡方/t 分布 P 值、相关系数、回归求解等纯函数。"""
import math


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def variance(xs, ddof=1):
    if len(xs) <= ddof:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - ddof)


def stdev(xs, ddof=1):
    return math.sqrt(variance(xs, ddof))


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def quantile(xs, q):
    s = sorted(xs)
    if not s:
        return 0.0
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def pearson(x, y):
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x, y = x[:n], y[:n]
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


# ---------- 分布函数 ----------


def norm_cdf(x, mu=0.0, sigma=1.0):
    return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))


def _betacf(a, b, x, itmax=200, eps=3e-9):
    """不完全 Beta 的连分式（Numerical Recipes 标准实现）。"""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a, b, x):
    """正则化不完全 Beta I_x(a, b)。"""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_sf_two_sided(t, df):
    """t 分布双侧 P 值。"""
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return betainc(df / 2.0, 0.5, x)


def t_sf_one_sided(t, df):
    return t_sf_two_sided(abs(t), df) / 2


def chi2_sf(x, k):
    """卡方分布上侧 P 值（正则化上不完全 Gamma Q(k/2, x/2)）。"""
    if x <= 0:
        return 1.0
    a, xx = k / 2.0, x / 2.0
    if xx < a + 1:  # 级数求 P，Q = 1 - P
        s = 1.0 / a
        term = s
        for n in range(1, 300):
            term *= xx / (a + n)
            s += term
            if abs(term) < abs(s) * 1e-10:
                break
        return max(0.0, min(1.0, 1.0 - s * math.exp(-xx + a * math.log(xx) - math.lgamma(a))))
    # 连分式求 Q
    b = xx + 1 - a
    c = 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 300):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    q = math.exp(-xx + a * math.log(xx) - math.lgamma(a)) * h
    return max(0.0, min(1.0, q))


# t 分布临界值表（双侧 90/95/99%），df<=30 精确，其余近似
_T_TABLE = {
    1: (6.314, 12.706, 63.657), 2: (2.920, 4.303, 9.925), 3: (2.353, 3.182, 5.841),
    4: (2.132, 2.776, 4.604), 5: (2.015, 2.571, 4.032), 6: (1.943, 2.447, 3.707),
    7: (1.895, 2.365, 3.499), 8: (1.860, 2.306, 3.355), 9: (1.833, 2.262, 3.250),
    10: (1.812, 2.228, 3.169), 11: (1.796, 2.201, 3.106), 12: (1.782, 2.179, 3.055),
    13: (1.771, 2.160, 3.012), 14: (1.761, 2.145, 2.977), 15: (1.753, 2.131, 2.947),
    16: (1.746, 2.120, 2.921), 17: (1.740, 2.110, 2.898), 18: (1.734, 2.101, 2.878),
    19: (1.729, 2.093, 2.861), 20: (1.725, 2.086, 2.845), 25: (1.708, 2.060, 2.787),
    30: (1.697, 2.042, 2.750), 40: (1.684, 2.021, 2.704), 60: (1.671, 2.000, 2.660),
    120: (1.658, 1.980, 2.617),
}


def t_critical(df, confidence=0.95):
    """t 临界值（双侧置信水平）。"""
    idx = {0.90: 0, 0.95: 1, 0.99: 2}.get(round(confidence, 2), 1)
    if df in _T_TABLE:
        return _T_TABLE[df][idx]
    if df > 120:
        z = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}
        return z.get(round(confidence, 2), 1.960)
    keys = sorted(_T_TABLE)
    for i in range(len(keys) - 1):
        if keys[i] < df < keys[i + 1]:
            lo, hi = keys[i], keys[i + 1]
            f = (df - lo) / (hi - lo)
            return _T_TABLE[lo][idx] * (1 - f) + _T_TABLE[hi][idx] * f
    return _T_TABLE[keys[0]][idx] if df < keys[0] else 1.96


def ols_fit(x, y):
    """一元线性回归：slope/intercept/r2/rmse。"""
    n = len(x)
    if n < 2:
        raise ValueError("至少需要 2 个点")
    mx, my = mean(x), mean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    preds = [slope * v + intercept for v in x]
    ss_res = sum((b - p) ** 2 for b, p in zip(y, preds))
    ss_tot = sum((b - my) ** 2 for b in y)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    rmse = math.sqrt(ss_res / n)
    return {"slope": round(slope, 8), "intercept": round(intercept, 8),
            "r2": round(r2, 6), "rmse": round(rmse, 6), "n": n}


def polyfit(x, y, degree):
    """多项式最小二乘（Vandermonde + 高斯消元），degree ≤ 5。"""
    if degree < 1 or degree > 5:
        raise ValueError("degree 支持 1-5")
    n = len(x)
    if n <= degree:
        raise ValueError("样本数必须大于阶数")
    m = degree + 1
    a = [[sum(xi ** (i + j) for xi in x) for j in range(m)] + [sum(yi * xi ** i for xi, yi in zip(x, y))] for i in range(m)]
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        a[col], a[piv] = a[piv], a[col]
        for r in range(m):
            if r != col and a[r][col]:
                f = a[r][col] / a[col][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col])]
    coeffs = [a[i][m] / a[i][i] for i in range(m)]
    preds = [sum(c * xi ** i for i, c in enumerate(coeffs)) for xi in x]
    ss_res = sum((yi - pi) ** 2 for yi, pi in zip(y, preds))
    ss_tot = sum((yi - mean(y)) ** 2 for yi in y)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return {"coefficients": [round(c, 8) for c in coeffs], "r2": round(r2, 6), "rmse": round(math.sqrt(ss_res / n), 6)}


def euclid(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def to_points(raw):
    """把 [[x,y,...], {x:..,y:..}] 统一成数值向量列表。"""
    pts = []
    for item in raw:
        if isinstance(item, dict):
            vals = [float(v) for v in item.values() if isinstance(v, (int, float))]
        elif isinstance(item, (list, tuple)):
            vals = [float(v) for v in item]
        else:
            raise ValueError("points 需为数组或对象")
        if vals:
            pts.append(vals)
    dim = len(pts[0]) if pts else 0
    if any(len(p) != dim for p in pts):
        raise ValueError("所有点维度必须一致")
    return pts
