# -*- coding: utf-8 -*-
"""minitools · 统计进阶家族（8 个，F733–F740）。

去重：dataintel/stats 做假设检验、minitools/num 做基础统计量（均值/方差/中位数）；
这里只补「相关/回归/分位/移动平均/频数/抽样/效应量」这类进阶描述统计与推断辅助。
"""
import math
import random
import statistics

from .common import endpoint, ok, opt_num, opt_str, req_list, req_num


def _nums(request, key="values"):
    raw = req_list(request, key, max_len=20000)
    out = []
    for x in raw:
        if x is None or (isinstance(x, str) and not x.strip()):
            continue
        try:
            val = float(x)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 含非数字项: {x}")
        if not math.isfinite(val):
            raise ValueError(f"参数 {key} 含 NaN/Inf")
        out.append(val)
    if len(out) < 2:
        raise ValueError(f"参数 {key} 至少需要 2 个数字")
    return out


@endpoint()
def correlation(request):
    """SX01. 相关系数：Pearson 与 Spearman。"""
    xs = _nums(request, "x")
    ys = _nums(request, "y")
    n = min(len(xs), len(ys))
    if n < 2:
        raise ValueError("x 与 y 至少各有 2 个数字")
    xs, ys = xs[:n], ys[:n]
    try:
        pearson = statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        pearson = None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    try:
        spearman = statistics.correlation(ranks(xs), ranks(ys))
    except statistics.StatisticsError:
        spearman = None
    return ok({"n": n,
               "pearson": round(pearson, 6) if pearson is not None else None,
               "spearman": round(spearman, 6) if spearman is not None else None,
               "strength": ("强" if pearson is not None and abs(pearson) >= 0.7
                            else "中" if pearson is not None and abs(pearson) >= 0.4 else "弱"),
               "note": "Pearson 衡量线性相关；数据有异常值或非线性时看 Spearman。"})


@endpoint()
def linreg(request):
    """SX02. 一元线性回归：y = a + b·x，含 R² 与预测。"""
    xs = _nums(request, "x")
    ys = _nums(request, "y")
    n = min(len(xs), len(ys))
    if n < 2:
        raise ValueError("x 与 y 至少各有 2 个数字")
    xs, ys = xs[:n], ys[:n]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((v - mx) ** 2 for v in xs)
    if sxx == 0:
        raise ValueError("x 全相同，无法拟合直线")
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((v - my) ** 2 for v in ys)
    ss_res = sum((ys[i] - (a + b * xs[i])) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    predict = opt_num(request, "predict")
    out = {"n": n, "slope": round(b, 6), "intercept": round(a, 6),
           "equation": f"y = {round(a, 4)} + {round(b, 4)}·x",
           "r2": round(r2, 6) if r2 is not None else None}
    if predict is not None:
        out["predict_at"] = predict
        out["predicted_y"] = round(a + b * predict, 6)
    return ok(out)


@endpoint()
def percentile(request):
    """SX03. 百分位：线性插值法求任意分位。"""
    vals = sorted(_nums(request, "values"))
    q = req_num(request, "q", minimum=0, maximum=100)
    if q <= 0:
        p = vals[0]
    elif q >= 100:
        p = vals[-1]
    else:
        pos = (len(vals) - 1) * q / 100.0
        lo = math.floor(pos)
        hi = math.ceil(pos)
        p = vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)
    return ok({"q": q, "percentile": round(p, 6), "n": len(vals),
               "min": vals[0], "max": vals[-1],
               "median": round(statistics.median(vals), 6)})


@endpoint()
def iqr(request):
    """SX04. 四分位与 IQR：Q1/Q2/Q3、IQR、上下界与异常值。"""
    vals = sorted(_nums(request, "values"))
    n = len(vals)

    def q(p):
        pos = (n - 1) * p
        lo, hi = math.floor(pos), math.ceil(pos)
        return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)

    q1, q2, q3 = q(0.25), q(0.5), q(0.75)
    iqr_val = q3 - q1
    low, high = q1 - 1.5 * iqr_val, q3 + 1.5 * iqr_val
    outliers = [v for v in vals if v < low or v > high]
    return ok({"n": n, "q1": round(q1, 6), "q2_median": round(q2, 6), "q3": round(q3, 6),
               "iqr": round(iqr_val, 6), "lower_fence": round(low, 6), "upper_fence": round(high, 6),
               "outliers": outliers, "outlier_count": len(outliers)})


@endpoint()
def moving_average(request):
    """SX05. 移动平均：支持简单/加权，可指定窗口。"""
    vals = _nums(request, "values")
    window = req_num(request, "window", integer=True, minimum=1, maximum=min(len(vals), 1000))
    kind = (opt_str(request, "kind", "simple") or "simple").lower()
    w = int(window)
    # 前缀和：原本每窗口重算一次是 O(n·w)，大窗口下约 10⁸ 次乘加
    prefix = [0.0]
    weighted_prefix = [0.0]
    for i, v in enumerate(vals):
        prefix.append(prefix[-1] + v)
        weighted_prefix.append(weighted_prefix[-1] + v * (i + 1))
    out = []
    total_w = w * (w + 1) / 2.0
    for i in range(len(vals) - w + 1):
        if kind == "weighted":
            # Σ v[j]*(j-i+1) = Σ v[j]*(j+1) - i*Σ v[j]
            seg_sum = weighted_prefix[i + w] - weighted_prefix[i] - i * (prefix[i + w] - prefix[i])
            out.append(seg_sum / total_w)
        else:
            out.append((prefix[i + w] - prefix[i]) / w)
    return ok({"window": w, "kind": kind, "count": len(out),
               "values": [round(v, 6) for v in out],
               "note": "输出长度 = 原长度 − 窗口 + 1（不补边）。"})


@endpoint()
def frequency_bins(request):
    """SX06. 组距频数：自动分箱并给出频数/频率/累计频率。"""
    vals = _nums(request, "values")
    bins = opt_num(request, "bins", default=0)
    lo, hi = min(vals), max(vals)
    if bins:
        k = int(bins)
        if k < 1:
            raise ValueError("bins 至少为 1")
        if k > 1000:
            raise ValueError("bins 上限为 1000")
        if k > len(vals):
            raise ValueError("bins 不能超过样本数")
    else:
        k = max(1, int(math.ceil(math.sqrt(len(vals)))))
    width = (hi - lo) / k if hi > lo else 1.0
    rows = []
    total = len(vals)
    cum = 0
    for i in range(k):
        a = lo + i * width
        b = lo + (i + 1) * width
        cnt = sum(1 for v in vals if (a <= v < b) or (i == k - 1 and v == b))
        cum += cnt
        rows.append({"from": round(a, 6), "to": round(b, 6), "count": cnt,
                     "frequency": round(cnt / total, 6), "cumulative": round(cum / total, 6)})
    return ok({"n": total, "bins": k, "width": round(width, 6),
               "min": lo, "max": hi, "rows": rows})


@endpoint()
def normal_sample(request):
    """SX07. 正态抽样：按均值/标准差生成样本，含描述统计。"""
    n = req_num(request, "n", integer=True, minimum=1, maximum=10000)
    mu = opt_num(request, "mu", default=0.0)
    sigma = opt_num(request, "sigma", default=1.0)
    if sigma <= 0:
        raise ValueError("sigma 必须大于 0")
    seed = opt_num(request, "seed")
    rnd = random.Random(int(seed)) if seed is not None else random.Random()
    sample = [rnd.gauss(mu, sigma) for _ in range(int(n))]
    return ok({
        "n": int(n), "mu": mu, "sigma": sigma,
        "sample_mean": round(statistics.fmean(sample), 6),
        "sample_std": round(statistics.pstdev(sample), 6),
        "min": round(min(sample), 6), "max": round(max(sample), 6),
        "preview": [round(v, 4) for v in sample[:20]],
        "note": "给 seed 可复现；preview 只回前 20 个，避免响应过大。",
    })


@endpoint()
def effect_size(request):
    """SX08. 效应量：Cohen's d 与 Cohen's h（比例差）。"""
    d = opt_num(request, "cohens_d")
    if d is not None:
        return ok({"type": "cohens_d", "value": round(d, 6),
                   "magnitude": ("大" if abs(d) >= 0.8 else "中" if abs(d) >= 0.5 else
                                 "小" if abs(d) >= 0.2 else "可忽略"),
                   "note": "|d|≥0.8 大、≥0.5 中、≥0.2 小（Cohen 惯例）。"})
    p1 = opt_num(request, "p1")
    p2 = opt_num(request, "p2")
    if p1 is None or p2 is None:
        raise ValueError("请提供 cohens_d，或同时提供 p1 与 p2（两个比例）")
    if not (0 <= p1 <= 1 and 0 <= p2 <= 1):
        raise ValueError("p1 / p2 需在 0~1 之间")
    h = 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))
    return ok({"type": "cohens_h", "p1": p1, "p2": p2, "value": round(h, 6),
               "magnitude": ("大" if abs(h) >= 0.8 else "中" if abs(h) >= 0.5 else
                             "小" if abs(h) >= 0.2 else "可忽略")})
