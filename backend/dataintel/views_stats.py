# -*- coding: utf-8 -*-
"""dataintel · 统计面接口：stats(8) forecast(6) regress(5) cluster(4) outlier(4) = 27 个。"""
import math

from dataintel.statkit import (chi2_sf, euclid, mean, median, norm_cdf,
                               ols_fit, pearson, polyfit, quantile, stdev,
                               t_critical, t_sf_one_sided, t_sf_two_sided,
                               to_points, variance)

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p, req, req_list, req_num, req_str


def _num_list(request, key):
    values = req_list(request, key)
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是数字数组")
    if any(not math.isfinite(v) for v in nums):
        raise ValueError(f"{key} 含 NaN/Inf")
    return nums


# =====================================================================
# stats 统计检验（8）
# =====================================================================


@endpoint()
def stats_ttest_one(request):
    """单样本 t 检验：样本均值与 mu 是否有显著差异。"""
    vals = _num_list(request, "values")
    mu = float(opt_num(request, "mu", 0) or 0)
    if len(vals) < 2:
        raise ValueError("至少 2 个样本")
    n = len(vals)
    m, s = mean(vals), stdev(vals)
    if s == 0:
        raise ValueError("样本标准差为 0，无法检验")
    t = (m - mu) / (s / math.sqrt(n))
    df = n - 1
    p_two = t_sf_two_sided(abs(t), df)
    return ok({"t": round(t, 6), "df": df, "mean": round(m, 6), "mu": mu,
               "p_two_sided": round(p_two, 6), "p_one_sided": round(t_sf_one_sided(t, df), 6),
               "significant_0.05": p_two < 0.05, "n": n,
               "verdict": "拒绝原假设：均值与 mu 有显著差异" if p_two < 0.05 else "不能拒绝原假设：无显著差异"})


@endpoint()
def stats_ttest_two(request):
    """双样本 t 检验（Welch，支持配对）。"""
    a = _num_list(request, "a")
    b = _num_list(request, "b")
    if len(a) < 2 or len(b) < 2:
        raise ValueError("两组各至少 2 个样本")
    if opt_bool(request, "paired"):
        if len(a) != len(b):
            raise ValueError("配对检验要求两组等长")
        d = [x - y for x, y in zip(a, b)]
        return ok({"mode": "paired", **{k: v for k, v in stats_ttest_one_impl(d, 0).items()}})
    n1, n2 = len(a), len(b)
    m1, m2 = mean(a), mean(b)
    v1, v2 = variance(a), variance(b)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        raise ValueError("两组标准差均为 0")
    t = (m1 - m2) / se
    df = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    p_two = t_sf_two_sided(abs(t), df)
    pooled_sd = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    cohen_d = (m1 - m2) / pooled_sd if pooled_sd else 0
    return ok({"mode": "welch", "t": round(t, 6), "df": round(df, 2),
               "mean_a": round(m1, 6), "mean_b": round(m2, 6), "diff": round(m1 - m2, 6),
               "p_two_sided": round(p_two, 6), "significant_0.05": p_two < 0.05,
               "cohen_d": round(cohen_d, 4),
               "effect": ["微弱", "小", "中", "大"][min(int(abs(cohen_d) / 0.3), 3)] if abs(cohen_d) >= 0.2 else "可忽略"})


def stats_ttest_one_impl(vals, mu):
    n = len(vals)
    m, s = mean(vals), stdev(vals)
    t = (m - mu) / (s / math.sqrt(n)) if s else 0
    p_two = t_sf_two_sided(abs(t), n - 1)
    return {"t": round(t, 6), "df": n - 1, "mean": round(m, 6), "p_two_sided": round(p_two, 6),
            "significant_0.05": p_two < 0.05}


@endpoint()
def stats_chi2(request):
    """卡方检验：列联表独立性（观测矩阵 vs 期望）。"""
    observed = req_list(request, "observed")
    try:
        matrix = [[float(v) for v in row] for row in observed]
    except (TypeError, ValueError):
        raise ValueError("observed 必须是二维数字数组")
    rows_n, cols_n = len(matrix), len(matrix[0])
    if rows_n < 2 or cols_n < 2:
        raise ValueError("列联表至少 2×2")
    if any(len(r) != cols_n for r in matrix):
        raise ValueError("每一行长度必须一致")
    row_sums = [sum(r) for r in matrix]
    col_sums = [sum(matrix[i][j] for i in range(rows_n)) for j in range(cols_n)]
    total = sum(row_sums)
    if total <= 0:
        raise ValueError("观测频次总和必须 > 0")
    chi2 = 0.0
    expected = []
    for i in range(rows_n):
        er = []
        for j in range(cols_n):
            e = row_sums[i] * col_sums[j] / total
            er.append(round(e, 4))
            if e > 0:
                chi2 += (matrix[i][j] - e) ** 2 / e
    dof = (rows_n - 1) * (cols_n - 1)
    p_value = chi2_sf(chi2, dof)
    return ok({"chi2": round(chi2, 6), "dof": dof, "p_value": round(p_value, 6),
               "expected": expected, "total": total,
               "significant_0.05": p_value < 0.05,
               "note": "期望频次 <5 的单元格较多时建议合并类别" if any(e < 5 for er in expected for e in er) else "",
               "verdict": "变量间存在显著关联" if p_value < 0.05 else "未见显著关联"})


@endpoint()
def stats_zscore(request):
    """Z 分数：逐值标准化 + |z|>threshold 的异常点。"""
    vals = _num_list(request, "values")
    if len(vals) < 2:
        raise ValueError("至少 2 个样本")
    m, s = mean(vals), stdev(vals)
    threshold = float(opt_num(request, "threshold", 2.5) or 2.5)
    zs = [round((v - m) / s, 6) if s else 0 for v in vals]
    flags = [{"index": i, "value": v, "z": z} for i, (v, z) in enumerate(zip(vals, zs)) if abs(z) > threshold]
    return ok({"mean": round(m, 6), "std": round(s, 6), "z_scores": zs,
               "threshold": threshold, "outliers": flags, "outlier_count": len(flags)})


@endpoint()
def stats_ci_mean(request):
    """均值的 t 置信区间。"""
    vals = _num_list(request, "values")
    if len(vals) < 2:
        raise ValueError("至少 2 个样本")
    confidence = float(opt_num(request, "confidence", 0.95, minimum=0.5, maximum=0.999) or 0.95)
    n = len(vals)
    m, s = mean(vals), stdev(vals)
    tc = t_critical(n - 1, confidence)
    half = tc * s / math.sqrt(n)
    return ok({"mean": round(m, 6), "std": round(s, 6), "n": n, "confidence": confidence,
               "t_critical": round(tc, 4),
               "interval": [round(m - half, 6), round(m + half, 6)],
               "margin_of_error": round(half, 6),
               "interpretation": f"以 {confidence * 100:.0f}% 置信水平，总体均值落在 [{m - half:.4f}, {m + half:.4f}]"})


@endpoint()
def stats_proportion_ci(request):
    """比例的置信区间（Wald + Wilson）。"""
    successes = int(req_num(request, "successes", 0, minimum=0, integer=True))
    trials = int(req_num(request, "trials", 0, minimum=1, integer=True))
    confidence = float(opt_num(request, "confidence", 0.95, minimum=0.5, maximum=0.999) or 0.95)
    if successes > trials:
        raise ValueError("successes 不能大于 trials")
    phat = successes / trials
    z = norm_cdf(2.576) and {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}.get(round(confidence, 2), 1.96)
    wald = [phat - z * math.sqrt(phat * (1 - phat) / trials), phat + z * math.sqrt(phat * (1 - phat) / trials)]
    z2 = z * z
    denom = 1 + z2 / trials
    center = (phat + z2 / (2 * trials)) / denom
    half = z * math.sqrt(phat * (1 - phat) / trials + z2 / (4 * trials * trials)) / denom
    wilson = [center - half, center + half]
    return ok({"p_hat": round(phat, 6), "trials": trials, "successes": successes, "z": z,
               "wald_interval": [round(max(0, wald[0]), 6), round(min(1, wald[1]), 6)],
               "wilson_interval": [round(max(0, wilson[0]), 6), round(min(1, wilson[1]), 6)],
               "recommended": "wilson（小样本更稳健）"})


@endpoint()
def stats_binomial_test(request):
    """二项精确检验：成功率是否偏离 p0。"""
    successes = int(req_num(request, "successes", 0, minimum=0, integer=True))
    trials = int(req_num(request, "trials", 0, minimum=1, maximum=100000, integer=True))
    p0 = float(opt_num(request, "p0", 0.5, minimum=0, maximum=1) or 0.5)
    if successes > trials:
        raise ValueError("successes 不能大于 trials")
    phat = successes / trials
    if trials > 1000:
        se = math.sqrt(p0 * (1 - p0) / trials)
        if se <= 0:
            raise ValueError("p0 为 0 或 1 时无法做正态近似")
        z = (phat - p0) / se
        p_one = norm_cdf(-abs(z))
        p_two = min(1.0, 2 * p_one)
        return ok({"observed_rate": round(phat, 6), "p0": p0, "trials": trials, "successes": successes,
                   "p_one_sided": round(p_one, 6), "p_two_sided": round(p_two, 6),
                   "significant_0.05": p_two < 0.05, "approximate": True,
                   "verdict": "实际成功率显著偏离基准" if p_two < 0.05 else "与基准无显著差异"})

    # 精确二项：单侧与双侧
    pmf = [math.comb(trials, k) * p0 ** k * (1 - p0) ** (trials - k) for k in range(trials + 1)]
    if phat >= p0:
        p_one = sum(pmf[successes:])
    else:
        p_one = sum(pmf[:successes + 1])
    cutoff = pmf[successes] * 1.0000001
    p_two = min(1.0, sum(v for v in pmf if v <= cutoff))
    return ok({"observed_rate": round(phat, 6), "p0": p0, "trials": trials, "successes": successes,
               "p_one_sided": round(p_one, 6), "p_two_sided": round(p_two, 6),
               "significant_0.05": p_two < 0.05, "approximate": False,
               "verdict": "实际成功率显著偏离基准" if p_two < 0.05 else "与基准无显著差异"})


@endpoint()
def stats_corr_sig(request):
    """相关系数显著性检验（Pearson r + t 检验）。"""
    x = _num_list(request, "x")
    y = _num_list(request, "y")
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("x/y 等长且至少 3 个样本")
    r = pearson(x, y)
    n = len(x)
    t = r * math.sqrt((n - 2) / (1 - r * r)) if abs(r) < 1 else None
    p_value = 0.0 if abs(r) >= 1 else t_sf_two_sided(abs(t), n - 2)
    return ok({"r": round(r, 6), "t": round(t, 6) if t is not None else None, "df": n - 2, "n": n,
               "p_value": round(p_value, 6), "significant_0.05": p_value < 0.05,
               "strength": "强" if abs(r) >= 0.7 else "中等" if abs(r) >= 0.4 else "弱",
               "direction": "正相关" if r > 0 else "负相关" if r < 0 else "无"})


# =====================================================================
# forecast 时间序列（6）
# =====================================================================


@endpoint()
def forecast_moving_average(request):
    """移动平均：窗口平滑 + 末端延伸预测。"""
    vals = _num_list(request, "values")
    window = int(req_num(request, "window", 3, minimum=2, maximum=max(2, len(vals))) )
    if len(vals) < window:
        raise ValueError("数据长度必须 ≥ 窗口")
    ma = [round(mean(vals[i:i + window]), 6) for i in range(len(vals) - window + 1)]
    next_v = round(mean(vals[-window:]), 6)
    return ok({"moving_average": ma, "window": window, "next_value": next_v,
               "smoothed_loss": round(stdev(vals) - stdev(ma), 6)})


@endpoint()
def forecast_exp_smoothing(request):
    """指数平滑（一次）：alpha 加权 + 一步预测。"""
    vals = _num_list(request, "values")
    alpha = float(opt_num(request, "alpha", 0.3, minimum=0.01, maximum=0.99) or 0.3)
    if len(vals) < 3:
        raise ValueError("至少 3 个点")
    level = vals[0]
    smoothed = []
    for v in vals:
        level = alpha * v + (1 - alpha) * level
        smoothed.append(round(level, 6))
    fitted_err = math.sqrt(mean([(v - s) ** 2 for v, s in zip(vals[1:], smoothed[:-1])])) if len(vals) > 1 else 0
    return ok({"smoothed": smoothed, "alpha": alpha, "next_value": round(level, 6),
               "rmse_insample": round(fitted_err, 6)})


@endpoint()
def forecast_linear_trend(request):
    """线性趋势拟合 + 外推 N 期 + R²。"""
    vals = _num_list(request, "values")
    if len(vals) < 3:
        raise ValueError("至少 3 个点")
    x = list(range(len(vals)))
    fit = ols_fit(x, vals)
    steps = int(opt_num(request, "steps", 3, minimum=1, maximum=30) or 3)
    preds = [round(fit["slope"] * (len(vals) + i) + fit["intercept"], 6) for i in range(steps)]
    return ok({**fit, "forecast_next": preds,
               "direction": "上升" if fit["slope"] > 0 else "下降" if fit["slope"] < 0 else "持平",
               "trend_quality": "强" if fit["r2"] >= 0.8 else "中" if fit["r2"] >= 0.5 else "弱"})


@endpoint()
def forecast_season_naive(request):
    """季节朴素法：周期指数 + 季节朴素预测。"""
    vals = _num_list(request, "values")
    period = int(req_num(request, "period", 7, minimum=2, maximum=max(2, len(vals) // 2)))
    if len(vals) < period * 2:
        raise ValueError("数据需至少覆盖两个完整周期")
    overall = mean(vals)
    seasons = []
    for i in range(period):
        cycle_vals = vals[i::period]
        seasons.append(round(mean(cycle_vals) - overall, 6))
    steps = int(opt_num(request, "steps", period, minimum=1, maximum=period * 2) or period)
    preds = [round(overall + seasons[(len(vals) + i) % period], 6) for i in range(steps)]
    fitted = [round(overall + seasons[i % period], 6) for i in range(len(vals))]
    return ok({"seasonal_indices": seasons, "baseline": round(overall, 6),
               "forecast_next": preds, "period": period,
               "rmse_insample": round(math.sqrt(mean([(v - f) ** 2 for v, f in zip(vals, fitted)])), 6)})


@endpoint()
def forecast_eval(request):
    """预测评估：MAE / RMSE / MAPE / R²。"""
    actual = _num_list(request, "actual")
    predicted = _num_list(request, "predicted")
    if len(actual) != len(predicted) or not actual:
        raise ValueError("actual/predicted 等长且非空")
    n = len(actual)
    mae = mean([abs(a - p) for a, p in zip(actual, predicted)])
    rmse = math.sqrt(mean([(a - p) ** 2 for a, p in zip(actual, predicted)]))
    pairs = [(a, p) for a, p in zip(actual, predicted) if a != 0]
    mape = mean([abs((a - p) / a) * 100 for a, p in pairs]) if pairs else None
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    ss_tot = sum((a - mean(actual)) ** 2 for a in actual)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return ok({"n": n, "mae": round(mae, 6), "rmse": round(rmse, 6),
               "mape_pct": round(mape, 4) if mape is not None else None,
               "r2": round(r2, 6),
               "grade": "优秀" if r2 >= 0.9 else "良好" if r2 >= 0.7 else "一般" if r2 >= 0.4 else "较差"})


@endpoint()
def forecast_decompose(request):
    """时序分解：趋势（中心化移动平均）+ 季节 + 残差。"""
    vals = _num_list(request, "values")
    period = int(req_num(request, "period", 7, minimum=2, maximum=max(2, len(vals) // 2)))
    if len(vals) < period * 2:
        raise ValueError("数据需至少覆盖两个完整周期")
    trend = [round(mean(vals[max(0, i - period // 2):i + period // 2 + 1]), 6) for i in range(len(vals))]
    detrended = [v - t for v, t in zip(vals, trend)]
    overall = mean(vals)
    seasonal_idx = []
    for i in range(period):
        svals = [detrended[j] for j in range(i, len(detrended), period)]
        seasonal_idx.append(round(mean(svals) if svals else 0, 6))
    residual = [round(detrended[i] - seasonal_idx[i % period], 6) for i in range(len(vals))]
    return ok({"trend": trend, "seasonal_indices": seasonal_idx, "residual": residual,
               "period": period, "baseline": round(overall, 6),
               "residual_std": round(stdev(residual), 6)})


# =====================================================================
# regress 回归拟合（5）
# =====================================================================


@endpoint()
def regress_linear(request):
    """一元线性回归（OLS）：系数 + R² + 残差样例。"""
    x = _num_list(request, "x")
    y = _num_list(request, "y")
    if len(x) != len(y):
        raise ValueError("x/y 等长")
    fit = ols_fit(x, y)
    preds = [fit["slope"] * v + fit["intercept"] for v in x]
    residuals = [round(yi - pi, 6) for yi, pi in zip(y, preds)]
    return ok({**fit, "residuals_sample": residuals[:20],
               "residual_std": round(stdev(residuals), 6)})


@endpoint()
def regress_poly(request):
    """多项式回归（1-5 阶）。"""
    x = _num_list(request, "x")
    y = _num_list(request, "y")
    if len(x) != len(y):
        raise ValueError("x/y 等长")
    degree = int(req_num(request, "degree", 2, minimum=1, maximum=5, integer=True))
    result = polyfit(x, y, degree)
    if result is None:
        raise ValueError("矩阵奇异，无法求解（检查 x 是否重复）")
    return ok({**result, "degree": degree, "n": len(x),
               "expression": "y = " + " + ".join(
                   f"{c:g}·x^{i}" if i else f"{c:g}" for i, c in enumerate(result["coefficients"]))})


@endpoint()
def regress_logit(request):
    """逻辑回归（梯度下降，二分类）：系数 + 准确率。"""
    xs = req_list(request, "x")
    ys = req_list(request, "y")
    try:
        X = [[float(v) for v in row] if isinstance(row, (list, tuple)) else [float(row)] for row in xs]
        Y = [1 if (float(v) > 0.5 or str(v).lower() in ("true", "yes")) else 0 for v in ys]
    except (TypeError, ValueError):
        raise ValueError("x 为特征二维数组，y 为 0/1 标签")
    if len(X) != len(Y) or len(X) < 5:
        raise ValueError("x/y 等长且至少 5 个样本")
    dim = len(X[0])
    if any(len(r) != dim for r in X):
        raise ValueError("特征维度必须一致")
    lr = float(opt_num(request, "lr", 0.1, minimum=0.0001, maximum=1) or 0.1)
    epochs = int(opt_num(request, "epochs", 500, minimum=50, maximum=5000) or 500)
    w = [0.0] * dim
    b = 0.0
    n = len(X)
    for _ in range(epochs):
        gw = [0.0] * dim
        gb = 0.0
        for row, label in zip(X, Y):
            z = b + sum(wi * xi for wi, xi in zip(w, row))
            e = 1 / (1 + math.exp(-max(-30, min(30, z)))) - label
            for j in range(dim):
                gw[j] += e * row[j]
            gb += e
        w = [wi - lr * g / n for wi, g in zip(w, gw)]
        b -= lr * gb / n
    correct = 0
    probs = []
    for row, label in zip(X, Y):
        z = b + sum(wi * xi for wi, xi in zip(w, row))
        prob = 1 / (1 + math.exp(-max(-30, min(30, z))))
        probs.append(round(prob, 4))
        correct += int((prob > 0.5) == (label == 1))
    return ok({"weights": [round(v, 6) for v in w], "bias": round(b, 6),
               "accuracy": round(correct / n, 4), "n": n, "epochs": epochs, "lr": lr,
               "probabilities_sample": probs[:20]})


@endpoint()
def regress_eval(request):
    """拟合评估：自动识别回归/分类指标。"""
    actual = req_list(request, "actual")
    predicted = req_list(request, "predicted")
    if len(actual) != len(predicted) or not actual:
        raise ValueError("actual/predicted 等长且非空")
    try:
        a = [float(v) for v in actual]
        pr = [float(v) for v in predicted]
    except (TypeError, ValueError):
        acc = mean([1.0 if str(x).strip() == str(y).strip() else 0.0 for x, y in zip(actual, predicted)])
        return ok({"type": "classification", "accuracy": round(acc, 4), "n": len(actual)})
    mae = mean([abs(x - y) for x, y in zip(a, pr)])
    rmse = math.sqrt(mean([(x - y) ** 2 for x, y in zip(a, pr)]))
    ss_tot = sum((v - mean(a)) ** 2 for v in a)
    r2 = 1 - sum((x - y) ** 2 for x, y in zip(a, pr)) / ss_tot if ss_tot else 1.0
    return ok({"type": "regression", "mae": round(mae, 6), "rmse": round(rmse, 6), "r2": round(r2, 6), "n": len(a)})


@endpoint()
def regress_predict(request):
    """用系数做预测：线性（w·x+b）或多项式（coeffs 自低到高）。"""
    coefficients = req_list(request, "coefficients")
    try:
        coeffs = [float(c) for c in coefficients]
    except (TypeError, ValueError):
        raise ValueError("coefficients 必须是数字数组")
    intercept = float(opt_num(request, "intercept", 0) or 0)
    inputs = req_list(request, "x")
    try:
        xs = [float(v) for v in inputs]
    except (TypeError, ValueError):
        raise ValueError("x 必须是数字数组")
    mode = opt_str(request, "mode", "linear")
    preds = []
    for xi in xs:
        if mode == "poly":
            preds.append(round(sum(c * xi ** i for i, c in enumerate(coeffs)) + intercept, 6))
        else:
            preds.append(round(sum(coeffs) * xi + intercept, 6))
    return ok({"predictions": preds, "mode": mode, "n": len(xs)})


# =====================================================================
# cluster 聚类（4）
# =====================================================================


@endpoint()
def cluster_kmeans(request):
    """K-Means：质心 + 分配 + 惯性（可复现 seed）。"""
    import random as _r

    pts = to_points(req_list(request, "points"))
    if len(pts) > 2000:
        raise ValueError("聚类点数上限 2000")
    k = int(req_num(request, "k", 3, minimum=2, maximum=min(20, max(2, len(pts) - 1)), integer=True))
    if len(pts) < k:
        raise ValueError("点数必须多于 k")
    max_iter = int(opt_num(request, "iterations", 50, minimum=1, maximum=100) or 50)
    seed = p(request, "seed")
    rng = _r.Random(seed) if seed is not None else _r.Random(42)
    centroids = rng.sample(pts, k)
    assign = [0] * len(pts)
    for _ in range(max_iter):
        moved = False
        for i, pt in enumerate(pts):
            best, bd = 0, euclid(pt, centroids[0])
            for c in range(1, k):
                d = euclid(pt, centroids[c])
                if d < bd:
                    best, bd = c, d
            if assign[i] != best:
                moved = True
                assign[i] = best
        for c in range(k):
            members = [pts[i] for i in range(len(pts)) if assign[i] == c]
            if members:
                centroids[c] = [mean([m[d] for m in members]) for d in range(len(pts[0]))]
        if not moved:
            break
    inertia = sum(euclid(pt, centroids[assign[i]]) ** 2 for i, pt in enumerate(pts))
    clusters = [{"cluster": c, "size": assign.count(c), "centroid": [round(v, 4) for v in centroids[c]]} for c in range(k)]
    return ok({"assignments": assign, "clusters": clusters, "inertia": round(inertia, 6),
               "iterations": max_iter, "k": k, "dim": len(pts[0])})


@endpoint()
def cluster_hierarchical(request):
    """层次聚类（单连接凝聚法）：合并步骤 + 指定 k 时的划分快照。"""
    pts = to_points(req_list(request, "points"))
    n = len(pts)
    if n < 3:
        raise ValueError("至少 3 个点")
    if n > 500:
        raise ValueError("点数最多 500（单连接层次聚类为 O(n²) 规模）")
    k = int(opt_num(request, "k", 2, minimum=1, maximum=n - 1) or 2)

    # 单连接层次聚类等价于按距离升序做 Kruskal 合并（并查集）
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            edges.append((euclid(pts[i], pts[j]), i, j))
    edges.sort(key=lambda e: e[0])

    parent = list(range(n))
    members = {i: [i] for i in range(n)}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    steps = []
    snapshot_at_k = None
    count = n
    for d, i, j in edges:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        mi = members[ri]
        mj = members.pop(rj)
        steps.append({"merge": [sorted(mi), sorted(mj)], "distance": round(d, 6),
                      "size": len(mi) + len(mj)})
        parent[rj] = ri
        mi.extend(mj)
        count -= 1
        if count == k:
            snapshot_at_k = [sorted(c) for c in members.values()]
        if count == 1:
            break
    return ok({"steps": steps[:50], "merge_count": len(steps),
               "clusters_at_k": snapshot_at_k, "k_requested": k,
               "note": "单连接（最近邻）凝聚策略，n 较大时建议改用 kmeans"})


@endpoint()
def cluster_dbscan(request):
    """DBSCAN：密度聚类 + 噪声点标记。"""
    pts = to_points(req_list(request, "points"))
    if len(pts) > 2000:
        raise ValueError("聚类点数上限 2000")
    eps = float(req_num(request, "eps", 1.0, minimum=1e-6))
    min_pts = int(opt_num(request, "min_pts", 2, minimum=2, maximum=len(pts) or 2) or 2)
    n = len(pts)
    labels = [-1] * n
    visited = [False] * n
    cluster_id = 0

    def neighbors(i):
        return [j for j in range(n) if euclid(pts[i], pts[j]) <= eps]

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        nb = neighbors(i)
        if len(nb) < min_pts:
            continue
        labels[i] = cluster_id
        queue = list(nb)
        while queue:
            j = queue.pop(0)
            if not visited[j]:
                visited[j] = True
                nb2 = neighbors(j)
                if len(nb2) >= min_pts:
                    queue.extend(nb2)
            if labels[j] == -1:
                labels[j] = cluster_id
        cluster_id += 1
    noise = [i for i in range(n) if labels[i] == -1]
    return ok({"labels": labels, "cluster_count": cluster_id, "noise": noise,
               "noise_count": len(noise), "eps": eps, "min_pts": min_pts,
               "sizes": [labels.count(c) for c in range(cluster_id)]})


@endpoint()
def cluster_elbow(request):
    """肘部法则：k=1..k_max 的惯性曲线 + 建议拐点。"""
    import random as _r

    pts = to_points(req_list(request, "points"))
    k_max = int(opt_num(request, "k_max", 6, minimum=2, maximum=min(10, len(pts) - 1)) or 6)
    rng = _r.Random(42)
    curve = []
    for k in range(1, k_max + 1):
        centroids = rng.sample(pts, k)
        assign = [0] * len(pts)
        for _ in range(30):
            for i, pt in enumerate(pts):
                assign[i] = min(range(k), key=lambda c: euclid(pt, centroids[c]))
            for c in range(k):
                members = [pts[i] for i in range(len(pts)) if assign[i] == c]
                if members:
                    centroids[c] = [mean([m[d] for m in members]) for d in range(len(pts[0]))]
        inertia = sum(euclid(pt, centroids[assign[i]]) ** 2 for i, pt in enumerate(pts))
        curve.append(round(inertia, 6))
    drops = [curve[i - 1] - curve[i] for i in range(1, len(curve))]
    suggested = (drops.index(max(drops)) + 2) if drops else 2
    return ok({"inertia_curve": curve, "k_values": list(range(1, k_max + 1)),
               "suggested_k": suggested, "biggest_drop_at": suggested})


# =====================================================================
# outlier 异常检测（4）
# =====================================================================


@endpoint()
def outlier_zscore(request):
    """Z-Score 异常检测。"""
    vals = _num_list(request, "values")
    threshold = float(opt_num(request, "threshold", 3) or 3)
    m, s = mean(vals), stdev(vals)
    flags = [{"index": i, "value": v, "z": round((v - m) / s, 4) if s else 0}
             for i, v in enumerate(vals) if s and abs((v - m) / s) > threshold]
    return ok({"method": "zscore", "threshold": threshold, "mean": round(m, 6), "std": round(s, 6),
               "outliers": flags, "count": len(flags)})


@endpoint()
def outlier_iqr(request):
    """IQR 四分位法异常检测。"""
    vals = _num_list(request, "values")
    k = float(opt_num(request, "k", 1.5) or 1.5)
    q1, q3 = quantile(vals, 0.25), quantile(vals, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    flags = [{"index": i, "value": v, "side": "low" if v < lo else "high"}
             for i, v in enumerate(vals) if v < lo or v > hi]
    return ok({"method": "iqr", "q1": round(q1, 6), "q3": round(q3, 6), "iqr": round(iqr, 6),
               "fences": [round(lo, 6), round(hi, 6)], "outliers": flags, "count": len(flags)})


@endpoint()
def outlier_mad(request):
    """MAD 中位数绝对偏差法（对极端值更稳）。"""
    vals = _num_list(request, "values")
    threshold = float(opt_num(request, "threshold", 3.5) or 3.5)
    med = median(vals)
    mad = median([abs(v - med) for v in vals])
    modified_z = [0.6745 * (v - med) / mad if mad else 0 for v in vals]
    flags = [{"index": i, "value": v, "modified_z": round(z, 4)}
             for i, (v, z) in enumerate(zip(vals, modified_z)) if abs(z) > threshold]
    return ok({"method": "mad", "median": round(med, 6), "mad": round(mad, 6),
               "threshold": threshold, "outliers": flags, "count": len(flags)})


@endpoint()
def outlier_lof(request):
    """LOF 局部离群因子（简化实现，k 近邻密度比）。"""
    pts = to_points(req_list(request, "points"))
    n = len(pts)
    if n > 2000:
        raise ValueError("点数最多 2000（LOF 为 O(n²·k) 规模）")
    k = int(opt_num(request, "k", 3, minimum=1, maximum=max(1, n - 1)) or 3)
    if n < k + 1:
        raise ValueError("点数必须大于 k")
    knn = [None] * n
    kdist = [None] * n
    lrd = [None] * n

    def row_dists(i):
        r = [(euclid(pts[i], pts[j]), j) for j in range(n) if j != i]
        r.sort(key=lambda t: t[0])
        return r

    for i in range(n):
        di = row_dists(i)
        knn[i] = [j for _, j in di[:k]]
        kdist[i] = di[k - 1][0]
        reach = []
        for d, j in di[:k]:
            if kdist[j] is None:
                kdist[j] = row_dists(j)[k - 1][0]
            reach.append(max(kdist[j], d))
        lrd[i] = 1 / (mean(reach) or 1e-9)
    lof = [round(mean([lrd[j] for j in knn[i]]) / lrd[i] if lrd[i] else 1, 4) for i in range(n)]
    threshold = float(opt_num(request, "threshold", 1.5) or 1.5)
    flags = [{"index": i, "lof": lof[i]} for i in range(n) if lof[i] > threshold]
    return ok({"lof_scores": lof, "k": k, "threshold": threshold, "outliers": flags,
               "outlier_count": len(flags), "note": "LOF≈1 正常，>1.5 可疑，>2 大概率异常"})


STATS_FAMILY_COUNT = 8 + 6 + 5 + 4 + 4  # = 27
