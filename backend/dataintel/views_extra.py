# -*- coding: utf-8 -*-
"""dataintel · 图表与实验面接口：chart(8) abtest(5) cohort(4) sampling(4) geo(5) = 26 个。"""
import hashlib
import math

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p, req, req_list, req_num, req_str

from .statkit import euclid, mean, stdev

# =====================================================================
# chart 图表数据（8）—— 输出「可直接渲染」的数据结构 + ASCII 预览
# =====================================================================


def _ascii_bar(values, width=40, labels=None):
    if not values:
        return []
    mx = max(values) or 1
    chars = "▁▂▃▄▅▆▇█"
    return ["".join(chars[min(7, int(v / mx * 8))] for v in row) for row in ([values] if not labels else [values])]


@endpoint()
def chart_histogram(request):
    """直方图数据：分箱 + 频次 + ASCII 预览。"""
    values = req_list(request, "values")
    try:
        vals = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values 必须是数字数组")
    if len(vals) < 3:
        raise ValueError("至少 3 个数值")
    bins = int(opt_num(request, "bins", 8, minimum=2, maximum=50) or 8)
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    width = rng / bins
    counts = [0] * bins
    for v in vals:
        idx = min(bins - 1, int((v - lo) / width))
        counts[idx] += 1
    mx = max(counts) or 1
    ascii_bar = "".join("▇" * int(c / mx * 30) or "·" for c in counts)
    return ok({"bins": [{"from": round(lo + i * width, 4), "to": round(lo + (i + 1) * width, 4), "count": c}
                        for i, c in enumerate(counts)],
               "min": lo, "max": hi, "bin_width": round(width, 4),
               "ascii": ascii_bar, "n": len(vals)})


@endpoint()
def chart_boxplot(request):
    """箱线图五数 + 内围栏 + ASCII 示意。"""
    from dataintel.statkit import median, quantile

    values = req_list(request, "values")
    try:
        vals = sorted(float(v) for v in values)
    except (TypeError, ValueError):
        raise ValueError("values 必须是数字数组")
    if len(vals) < 4:
        raise ValueError("至少 4 个数值")
    q1, q2, q3 = quantile(vals, 0.25), quantile(vals, 0.5), quantile(vals, 0.75)
    iqr = q3 - q1
    lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    whiskers = [v for v in vals if lo_f <= v <= hi_f]
    outliers = [v for v in vals if v < lo_f or v > hi_f]
    lo_w, hi_w = min(whiskers), max(whiskers)
    lo_all, hi_all = min(vals), max(vals)
    rng = (hi_all - lo_all) or 1
    pos = lambda v: int((v - lo_all) / rng * 40)
    ascii_box = (" " * pos(lo_w) + "├" + "─" * max(1, pos(q1) - pos(lo_w)) +
                 "[" + "─" * max(1, pos(q3) - pos(q1)) + "]" +
                 "─" * max(1, pos(hi_w) - pos(q3)) + "┤")
    return ok({"min": lo_all, "q1": round(q1, 4), "median": round(q2, 4), "q3": round(q3, 4),
               "max": hi_all, "iqr": round(iqr, 4), "whiskers": [round(lo_w, 4), round(hi_w, 4)],
               "outliers": outliers, "ascii": ascii_box})


@endpoint()
def chart_scatter(request):
    """散点数据：趋势线参数 + 象限统计 + 采样输出。"""
    points = req_list(request, "points")
    x_field, y_field = opt_str(request, "x_field", "x"), opt_str(request, "y_field", "y")
    pts = []
    for pt in points:
        if isinstance(pt, dict):
            try:
                pts.append((float(pt[x_field]), float(pt[y_field])))
            except (KeyError, TypeError, ValueError):
                continue
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            try:
                pts.append((float(pt[0]), float(pt[1])))
            except (TypeError, ValueError):
                continue
    if len(pts) < 3:
        raise ValueError("有效散点不足 3 个")
    from dataintel.statkit import ols_fit, pearson

    xs, ys = [a for a, _ in pts], [b for _, b in pts]
    fit = ols_fit(xs, ys)
    r = pearson(xs, ys)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    quadrants = {"Q1_右右上": sum(1 for a, b in pts if a >= mx and b >= my),
                 "Q2_左上": sum(1 for a, b in pts if a < mx and b >= my),
                 "Q3_左下": sum(1 for a, b in pts if a < mx and b < my),
                 "Q4_右下": sum(1 for a, b in pts if a >= mx and b < my)}
    limit = int(opt_num(request, "limit", 200, minimum=10, maximum=2000) or 200)
    step = max(1, len(pts) // limit)
    return ok({"points": pts[::step], "total": len(pts), "trend": fit, "pearson_r": round(r, 4),
               "quadrants": quadrants, "center": [round(mx, 4), round(my, 4)]})


@endpoint()
def chart_pie(request):
    """饼图数据：占比 + 颜色分配 + ASCII。"""
    items = req_list(request, "items")
    try:
        pairs = [(str(i["name"]), float(i["value"])) for i in items]
    except (KeyError, TypeError, ValueError):
        raise ValueError('items 每项需为 {name, value}')
    if not pairs or sum(v for _, v in pairs) <= 0:
        raise ValueError("items 不能为空且总值 > 0")
    total = sum(v for _, v in pairs)
    palette = ["#5b8ff9", "#5ad8a6", "#5d7092", "#f6bd16", "#e8684a", "#6dc8ec", "#9270ca", "#ff9d4d"]
    out = []
    for i, (name, v) in enumerate(pairs):
        pct = v / total * 100
        out.append({"name": name, "value": v, "pct": round(pct, 2), "color": palette[i % len(palette)]})
    out.sort(key=lambda x: -x["pct"])
    ascii_pie = "".join("█" * max(1, int(o["pct"] / 3)) for o in out)
    return ok({"items": out, "total": round(total, 6),
               "top1_pct": out[0]["pct"], "ascii": ascii_pie,
               "note": "前二占比超 75% 时建议聚焦头部" if out[0]["pct"] + (out[1]["pct"] if len(out) > 1 else 0) > 75 else ""})


@endpoint()
def chart_line(request):
    """折线序列：多系列 + 极值 + ASCII 走势。"""
    series = req_list(request, "series")
    parsed = []
    for s in series:
        if not isinstance(s, dict) or "values" not in s:
            raise ValueError('series 每项需为 {name, values}')
        try:
            parsed.append({"name": str(s.get("name", "series")), "values": [float(v) for v in s["values"]]})
        except (TypeError, ValueError):
            raise ValueError(f"系列 {s.get('name')} 含非数值")
    if not parsed:
        raise ValueError("series 为空")
    chars = "▁▂▃▄▅▆▇█"
    for s in parsed:
        vs = s["values"]
        mx, mn = max(vs), min(vs)
        rng = (mx - mn) or 1
        s["ascii"] = "".join(chars[min(7, int((v - mn) / rng * 8))] for v in vs[:80])
        s["min"], s["max"], s["mean"] = round(mn, 4), round(mx, 4), round(mean(vs), 4)
    all_max = max(s["max"] for s in parsed)
    return ok({"series": parsed, "series_count": len(parsed), "global_max": all_max,
               "lengths": [len(s["values"]) for s in parsed]})


@endpoint()
def chart_heatmap(request):
    """热力矩阵：归一化 + TOP 单元格。"""
    matrix = req_list(request, "matrix")
    try:
        m = [[float(v) for v in row] for row in matrix]
    except (TypeError, ValueError):
        raise ValueError("matrix 必须是二维数字数组")
    if not m or any(len(r) != len(m[0]) for r in m):
        raise ValueError("matrix 行列必须规整")
    flat = [v for row in m for v in row]
    lo, hi = min(flat), max(flat)
    rng = (hi - lo) or 1
    norm = [[round((v - lo) / rng, 3) for v in row] for row in m]
    cells = sorted(((i, j, m[i][j]) for i in range(len(m)) for j in range(len(m[0]))), key=lambda t: -t[2])
    labels_y = p(request, "row_labels") or [f"R{i}" for i in range(len(m))]
    labels_x = p(request, "col_labels") or [f"C{j}" for j in range(len(m[0]))]
    return ok({"normalized": norm, "range": [lo, hi],
               "top_cells": [{"row": labels_y[i], "col": labels_x[j], "value": v} for i, j, v in cells[:10]],
               "dims": [len(m), len(m[0])]})


@endpoint()
def chart_pareto(request):
    """帕累托分析：排序 + 累计占比 + 80/20 切点。"""
    items = req_list(request, "items")
    try:
        pairs = [(str(i["name"]), float(i["value"])) for i in items]
    except (KeyError, TypeError, ValueError):
        raise ValueError('items 每项需为 {name, value}')
    pairs.sort(key=lambda kv: -kv[1])
    total = sum(v for _, v in pairs) or 1
    out, cum = [], 0.0
    cut = None
    for i, (name, v) in enumerate(pairs, 1):
        cum += v
        pct = cum / total * 100
        if cut is None and pct >= 80:
            cut = i
        out.append({"rank": i, "name": name, "value": v, "share_pct": round(v / total * 100, 2),
                    "cumulative_pct": round(pct, 2)})
    return ok({"items": out, "vital_few_count": cut or len(pairs),
               "vital_few_share_pct": round(out[cut - 1]["cumulative_pct"], 2) if cut else 100,
               "insight": f"前 {cut or len(pairs)} 项贡献约 {out[cut - 1]['cumulative_pct'] if cut else 100}% —— 集中火力打它们" if cut else ""})


@endpoint()
def chart_funnel(request):
    """漏斗：逐级转化率 + 整体转化 + 最大流失点。"""
    stages = req_list(request, "stages")
    try:
        pairs = [(str(s["name"]), float(s["value"])) for s in stages]
    except (KeyError, TypeError, ValueError):
        raise ValueError('stages 每项需为 {name, value}')
    if len(pairs) < 2:
        raise ValueError("漏斗至少两级")
    out = []
    for i, (name, v) in enumerate(pairs):
        rate = v / pairs[i - 1][1] * 100 if i and pairs[i - 1][1] else None
        out.append({"stage": name, "value": v, "from_prev_pct": round(rate, 2) if rate else 100.0})
    overall = pairs[-1][1] / pairs[0][1] * 100 if pairs[0][1] else 0
    biggest_leak = min(range(1, len(out)), key=lambda i: out[i]["from_prev_pct"])
    return ok({"stages": out, "overall_conversion_pct": round(overall, 2),
               "biggest_leak": {"from": out[biggest_leak - 1]["stage"], "to": out[biggest_leak]["stage"],
                                "rate_pct": out[biggest_leak]["from_prev_pct"]},
               "ascii": "".join("█" * max(1, int(v / pairs[0][1] * 30)) + f" {n}\n" for n, v in pairs)})


# =====================================================================
# abtest A/B 实验（5）—— 无状态，确定性哈希分桶
# =====================================================================


def _bucket(user_key: str, salt: str, variants: int) -> int:
    h = hashlib.md5(f"{salt}:{user_key}".encode()).hexdigest()
    return int(h[:8], 16) % variants


@endpoint()
def abtest_assign(request):
    """确定性分桶：同一 user_key + salt 永远得到同一变体。"""
    user_key = req_str(request, "user_key")
    variants = req_list(request, "variants")
    if len(variants) < 2:
        raise ValueError("variants 至少 2 个")
    salt = opt_str(request, "salt", "exp1")
    idx = _bucket(user_key, salt, len(variants))
    return ok({"user_key": user_key, "variant": str(variants[idx]), "variant_index": idx,
               "salt": salt, "deterministic": True})


@endpoint()
def abtest_hash_preview(request):
    """分桶分布预览：批量 key 的分流均匀度检查。"""
    keys = req_list(request, "keys")
    variants = req_list(request, "variants")
    salt = opt_str(request, "salt", "exp1")
    counts = [0] * len(variants)
    for k in keys:
        counts[_bucket(str(k), salt, len(variants))] += 1
    total = len(keys) or 1
    expect = 100 / len(variants)
    return ok({"distribution": [{"variant": str(v), "count": c, "pct": round(c / total * 100, 2)}
                                for v, c in zip(variants, counts)],
               "expected_pct": round(expect, 2),
               "max_deviation_pct": round(max(abs(c / total * 100 - expect) for c in counts), 2),
               "keys": len(keys)})


@endpoint()
def abtest_plan(request):
    """实验样本量计算：baseline/mde/alpha/power → 每组所需 n。"""
    baseline = float(req_num(request, "baseline_rate", 0.05, minimum=0.0001, maximum=0.99))
    mde = float(req_num(request, "mde", 0.01, minimum=0.0001, maximum=0.9))
    alpha = float(opt_num(request, "alpha", 0.05, minimum=0.001, maximum=0.2) or 0.05)
    power = float(opt_num(request, "power", 0.8, minimum=0.5, maximum=0.99) or 0.8)
    z_a = 1.959964 if abs(alpha - 0.05) < 1e-6 else 2.575829 if abs(alpha - 0.01) < 1e-6 else 1.644854
    z_b = 0.841621 if abs(power - 0.8) < 1e-6 else 1.281552 if abs(power - 0.9) < 1e-6 else 0.674490
    p2 = baseline + mde
    pbar = (baseline + p2) / 2
    n = ((z_a * math.sqrt(2 * pbar * (1 - pbar)) + z_b * math.sqrt(baseline * (1 - baseline) + p2 * (1 - p2))) ** 2) / mde ** 2
    return ok({"baseline_rate": baseline, "mde": mde, "alpha": alpha, "power": power,
               "n_per_variant": math.ceil(n),
               "total": math.ceil(n) * 2,
               "expected_uplift_pct": round(mde / baseline * 100, 2),
               "note": "按双侧检验、两变体（1 对照 1 实验）计算"})


@endpoint()
def abtest_significance(request):
    """双比例 z 检验：实验组相对对照组是否显著。"""
    control = req_list(request, "control")
    variant = req_list(request, "variant")
    if len(control) != 2 or len(variant) != 2:
        raise ValueError("control/variant 均需 [成功数, 总数]")
    x1, n1 = float(control[0]), float(control[1])
    x2, n2 = float(variant[0]), float(variant[1])
    if n1 <= 0 or n2 <= 0 or x1 > n1 or x2 > n2:
        raise ValueError("数据不合法：成功数不得超过总数，总数 > 0")
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) or 1e-12
    z = (p2 - p1) / se
    from dataintel.statkit import norm_cdf

    p_value = 2 * (1 - norm_cdf(abs(z)))
    uplift = (p2 - p1) / p1 * 100 if p1 else None
    se_diff = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2) or 1e-12
    ci = [(p2 - p1) - 1.96 * se_diff, (p2 - p1) + 1.96 * se_diff]
    return ok({"control_rate": round(p1, 6), "variant_rate": round(p2, 6),
               "uplift_pct": round(uplift, 2) if uplift is not None else None,
               "z": round(z, 4), "p_value": round(p_value, 6),
               "significant_0.05": p_value < 0.05,
               "diff_ci_95": [round(c, 6) for c in ci],
               "verdict": "实验组显著" + ("更优" if p2 > p1 else "更差") if p_value < 0.05 else "差异不显著，继续积累样本"})


@endpoint()
def abtest_metrics(request):
    """实验指标汇总：多组 [成功,总数] 的率与置信区间。"""
    groups = req_list(request, "groups")
    out = []
    for g in groups:
        if not isinstance(g, dict) or "name" not in g or "successes" not in g or "trials" not in g:
            raise ValueError('groups 每项需为 {name, successes, trials}')
        s, t = float(g["successes"]), float(g["trials"])
        if t <= 0 or s > t:
            raise ValueError(f"组 {g['name']} 数据不合法")
        p = s / t
        se = math.sqrt(p * (1 - p) / t) or 1e-12
        out.append({"name": str(g["name"]), "rate": round(p, 6),
                    "ci_95": [round(p - 1.96 * se, 6), round(p + 1.96 * se, 6)],
                    "trials": int(t), "successes": int(s)})
    return ok({"groups": out, "count": len(out),
               "best": max(out, key=lambda x: x["rate"])["name"] if out else None})


# =====================================================================
# cohort 留存分析（4）
# =====================================================================


@endpoint()
def cohort_build(request):
    """留存矩阵：events=[{user, period}] → 首触周期 × 后续周期留存。"""
    events = req_list(request, "events")
    users = {}
    for e in events:
        if not isinstance(e, dict) or "user" not in e or "period" not in e:
            raise ValueError('events 每项需为 {user, period}')
        users.setdefault(str(e["user"]), set()).add(str(e["period"]))
    periods = sorted({p_ for ps in users.values() for p_ in ps})
    pidx = {p_: i for i, p_ in enumerate(periods)}
    cohorts = {}
    for u, ps in users.items():
        first = min(ps, key=lambda p_: pidx[p_])
        cohorts.setdefault(first, {"size": 0, "retained": [0] * len(periods)})
        c = cohorts[first]
        c["size"] += 1
        for p_ in ps:
            offset = pidx[p_] - pidx[first]
            c["retained"][offset] += 1
    matrix = []
    for first in periods:
        c = cohorts.get(first) or {"size": 0, "retained": [0] * len(periods)}
        size = c["size"]
        if size:
            retention = [round(r / size * 100, 1) if r else (100.0 if i == 0 else 0.0)
                         for i, r in enumerate(c["retained"])]
        else:
            retention = [0.0] * len(periods)
        matrix.append({"cohort": first, "size": size,
                       "retention_pct": retention,
                       "retained_counts": c["retained"]})
    return ok({"periods": periods, "matrix": matrix, "cohort_count": len(matrix),
               "users": len(users)})


@endpoint()
def cohort_summary(request):
    """留存概览：各周期活跃数 / 新老用户拆分。"""
    events = req_list(request, "events")
    users = {}
    for e in events:
        if isinstance(e, dict) and "user" in e and "period" in e:
            users.setdefault(str(e["user"]), set()).add(str(e["period"]))
    periods = sorted({p_ for ps in users.values() for p_ in ps})
    pidx = {p_: i for i, p_ in enumerate(periods)}
    first_seen = {u: min(ps, key=lambda p_: pidx[p_]) for u in users}
    rows = []
    for p_ in periods:
        active = sum(1 for ps in users.values() if p_ in ps)
        new = sum(1 for f in first_seen.values() if f == p_)
        rows.append({"period": p_, "active_users": active, "new_users": new,
                     "returning_users": active - new,
                     "new_ratio_pct": round(new / active * 100, 1) if active else 0})
    total_active = sum(r["active_users"] for r in rows)
    return ok({"periods": rows, "period_count": len(periods), "total_users": len(users),
               "avg_active_per_period": round(total_active / len(periods), 1) if periods else 0,
               "sticky_factor_pct": round(total_active / max(len(users) * max(len(periods), 1), 1) * 100, 1)})


@endpoint()
def cohort_retain(request):
    """留存曲线对比：相邻周期衰减率。"""
    events = req_list(request, "events")
    users = {}
    for e in events:
        if isinstance(e, dict) and "user" in e and "period" in e:
            users.setdefault(str(e["user"]), set()).add(str(e["period"]))
    periods = sorted({p_ for ps in users.values() for p_ in ps})
    pidx = {p_: i for i, p_ in enumerate(periods)}
    offsets = {}
    for u, ps in users.items():
        first = pidx[min(ps, key=lambda p_: pidx[p_])]
        for p_ in ps:
            offsets.setdefault(pidx[p_] - first, set()).add(u)
    base = len(users) or 1
    curve = [{"offset": k, "active_users": len(v), "retention_pct": round(len(v) / base * 100, 1)}
             for k, v in sorted(offsets.items())]
    decays = []
    for i in range(2, len(curve)):
        prev, cur = curve[i - 1]["retention_pct"], curve[i]["retention_pct"]
        decays.append(round(prev - cur, 2))
    return ok({"curve": curve, "avg_decay_per_period_pct": round(mean(decays), 2) if decays else 0,
               "d30_style_retention": curve[3]["retention_pct"] if len(curve) > 3 else None})


@endpoint()
def cohort_compare(request):
    """两期留存对比：新 cohort 相对旧 cohort 的留存差。"""
    events = req_list(request, "events")
    split_period = req_str(request, "split_period")
    users = {}
    for e in events:
        if isinstance(e, dict) and "user" in e and "period" in e:
            users.setdefault(str(e["user"]), set()).add(str(e["period"]))
    old_users = {u for u, ps in users.items() if min(ps) < split_period}
    new_users = {u for u, ps in users.items() if min(ps) >= split_period}

    def retention(user_set):
        if not user_set:
            return None
        firsts = {u: min(users[u]) for u in user_set}
        same = sum(1 for u in user_set if len(users[u]) >= 2)
        return round(same / len(user_set) * 100, 1)
    r_old, r_new = retention(old_users), retention(new_users)
    delta = None if (r_old is None or r_new is None) else round(r_new - r_old, 1)
    return ok({"old_cohort": {"users": len(old_users), "repeat_retention_pct": r_old},
               "new_cohort": {"users": len(new_users), "repeat_retention_pct": r_new},
               "delta_pct": delta,
               "verdict": "新用户留存改善" if (delta or 0) > 0 else "新用户留存下滑" if delta is not None else "样本不足",
               "split_period": split_period})


# =====================================================================
# sampling 抽样（4）
# =====================================================================


@endpoint()
def sampling_random(request):
    """简单随机抽样（seed 可复现）。"""
    population = req_list(request, "population")
    n = int(req_num(request, "n", 10, minimum=1, maximum=len(population) or 1) or 10)
    seed = p(request, "seed")
    import random as _r

    rng = _r.Random(seed)
    picked = rng.sample([str(x) for x in population], min(n, len(population)))
    return ok({"sample": picked, "n": len(picked), "population": len(population), "seed": seed})


@endpoint()
def sampling_systematic(request):
    """系统（等距）抽样。"""
    population = req_list(request, "population")
    k = int(req_num(request, "k", 5, minimum=1, maximum=len(population) or 1) or 5)
    start = int(opt_num(request, "start", 0, minimum=0, maximum=max(0, k - 1)) or 0)
    picked = [str(population[i]) for i in range(start, len(population), k)]
    return ok({"sample": picked, "n": len(picked), "k": k, "start": start,
               "population": len(population)})


@endpoint()
def sampling_stratified(request):
    """分层抽样：按 group 字段等比例抽取。"""
    rows = req_list(request, "population")
    n = int(req_num(request, "n", 10, minimum=1) or 10)
    group_field = opt_str(request, "group_field", "group")
    groups = {}
    for r in rows:
        key = str(r.get(group_field, "_all")) if isinstance(r, dict) else "_all"
        groups.setdefault(key, []).append(r)
    total = len(rows) or 1
    import random as _r

    rng = _r.Random(p(request, "seed"))
    out = []
    for g, members in sorted(groups.items()):
        take = max(1, round(n * len(members) / total))
        out.extend({"group": g, "item": it} for it in rng.sample(members, min(take, len(members))))
    return ok({"sample": out, "picked": len(out), "strata": {g: len(m) for g, m in groups.items()},
               "target_n": n})


@endpoint()
def sampling_bootstrap(request):
    """Bootstrap 置信区间（均值/中位数，seed 可复现）。"""
    values = req_list(request, "values")
    try:
        vals = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values 必须是数字数组")
    if len(vals) < 5:
        raise ValueError("至少 5 个样本")
    n_iter = int(opt_num(request, "iterations", 1000, minimum=100, maximum=10000) or 1000)
    stat = opt_str(request, "stat", "mean")
    seed = p(request, "seed")
    import random as _r

    rng = _r.Random(seed)
    fn = mean if stat == "mean" else (lambda xs: sorted(xs)[len(xs) // 2])
    stats = []
    for _ in range(n_iter):
        sample = [vals[rng.randrange(len(vals))] for _ in range(len(vals))]
        stats.append(fn(sample))
    stats.sort()
    lo, hi = stats[int(n_iter * 0.025)], stats[int(n_iter * 0.975) - 1]
    return ok({"stat": stat, "point_estimate": round(fn(vals), 6),
               "ci_95": [round(lo, 6), round(hi, 6)], "iterations": n_iter,
               "bootstrap_std": round(stdev(stats), 6), "seed": seed})


# =====================================================================
# geo 轻地理（5）
# =====================================================================


def _haversine(lat1, lng1, lat2, lng2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _resolve_point(value):
    """坐标 [lat,lng] 或内置城市名 → (lat, lng)。"""
    from devtools.data import CITY_LATLNG

    if isinstance(value, str):
        key = value.strip().rstrip("市")
        if key not in CITY_LATLNG:
            raise ValueError(f"未知城市 {value}，或直接传 [lat,lng]")
        return CITY_LATLNG[key], key
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (float(value[0]), float(value[1])), None
        except (TypeError, ValueError):
            raise ValueError("坐标需为数字 [lat, lng]")
    raise ValueError("point 需为城市名或 [lat,lng]")


@endpoint()
def geo_distance(request):
    """球面距离（haversine）：坐标对或内置城市名。"""
    p_from, name_a = _resolve_point(req(request, "from"))
    p_to, name_b = _resolve_point(req(request, "to"))
    km = _haversine(p_from[0], p_from[1], p_to[0], p_to[1])
    return ok({"distance_km": round(km, 2), "distance_miles": round(km * 0.621371, 2),
               "from": name_a or list(p_from), "to": name_b or list(p_to),
               "flight_hint": f"民航约 {km / 800:.1f} 小时（不含起降）",
               "drive_hint": f"高速约 {km / 90:.1f} 小时"})


_GEO_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


@endpoint()
def geo_geohash(request):
    """Geohash 编码/解码（纯 Python 实现）。"""
    action = opt_str(request, "action", "encode")
    if action == "encode":
        lat = float(req_num(request, "lat", minimum=-90, maximum=90))
        lng = float(req_num(request, "lng", minimum=-180, maximum=180))
        precision = int(opt_num(request, "precision", 8, minimum=1, maximum=12) or 8)
        lat_lo, lat_hi, lng_lo, lng_hi = -90.0, 90.0, -180.0, 180.0
        bits = [16, 8, 4, 2, 1]
        bit, ch, even, out = 0, 0, True, []
        while len(out) < precision:
            if even:
                mid = (lng_lo + lng_hi) / 2
                if lng >= mid:
                    ch |= bits[bit]
                    lng_lo = mid
                else:
                    lng_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if lat >= mid:
                    ch |= bits[bit]
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
            if bit < 4:
                bit += 1
            else:
                out.append(_GEO_BASE32[ch])
                bit, ch = 0, 0
        return ok({"geohash": "".join(out), "lat": lat, "lng": lng, "precision": precision})
    hs = req_str(request, "geohash").strip().lower()
    lat_lo, lat_hi, lng_lo, lng_hi = -90.0, 90.0, -180.0, 180.0
    even = True
    for ch in hs:
        idx = _GEO_BASE32.find(ch)
        if idx < 0:
            raise ValueError(f"非法 geohash 字符: {ch}")
        for bit in [16, 8, 4, 2, 1]:
            if even:
                mid = (lng_lo + lng_hi) / 2
                if idx & bit:
                    lng_lo = mid
                else:
                    lng_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if idx & bit:
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
    return ok({"lat": round((lat_lo + lat_hi) / 2, 8), "lng": round((lng_lo + lng_hi) / 2, 8),
               "bbox": {"lat": [lat_lo, lat_hi], "lng": [lng_lo, lng_hi]}})


@endpoint()
def geo_polygon(request):
    """点在多边形内判定（射线法）。"""
    point = req_list(request, "point")
    polygon = req_list(request, "polygon")
    try:
        px, py = float(point[0]), float(point[1])
        poly = [(float(pt[0]), float(pt[1])) for pt in polygon]
    except (IndexError, TypeError, ValueError):
        raise ValueError("point=[x,y]，polygon=[[x,y],...]")
    if len(poly) < 3:
        raise ValueError("多边形至少 3 个顶点")
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    area = abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2
    return ok({"inside": inside, "point": [px, py], "vertices": len(poly),
               "polygon_area": round(area, 6), "method": "ray-casting"})


@endpoint()
def geo_bbox(request):
    """点集包围盒：min/max/中心/对角线长度。"""
    points = req_list(request, "points")
    try:
        pts = [(float(pt[0]), float(pt[1])) for pt in points]
    except (IndexError, TypeError, ValueError):
        raise ValueError("points 需为 [[lat,lng], ...]")
    if len(pts) < 2:
        raise ValueError("至少 2 个点")
    lats, lngs = [a for a, _ in pts], [b for _, b in pts]
    bbox = [min(lats), min(lngs), max(lats), max(lngs)]
    return ok({"bbox": bbox, "center": [round(sum(lats) / len(lats), 6), round(sum(lngs) / len(lngs), 6)],
               "width_deg": round(bbox[3] - bbox[1], 6), "height_deg": round(bbox[2] - bbox[0], 6),
               "diagonal_km": round(_haversine(bbox[0], bbox[1], bbox[2], bbox[3]), 2)})


@endpoint()
def geo_eta(request):
    """行程时间估算：距离 + 交通模式 → 时间与速度区间。"""
    distance_km = float(req_num(request, "distance_km", minimum=0.01, maximum=50000))
    mode = opt_str(request, "mode", "car")
    speeds = {"walk": (4.0, 5.5), "bike": (12.0, 22.0), "car": (30.0, 80.0),
              "highway": (80.0, 120.0), "highspeed_rail": (250.0, 350.0), "flight": (700.0, 900.0)}
    if mode not in speeds:
        raise ValueError(f"mode 支持 {list(speeds)}")
    lo, hi = speeds[mode]
    def fmt(hours):
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h}小时{m:02d}分" if h else f"{m} 分钟"
    return ok({"distance_km": distance_km, "mode": mode,
               "eta_range": [fmt(distance_km / hi), fmt(distance_km / lo)],
               "speed_range_kmh": [lo, hi],
               "minutes_avg": round(distance_km / ((lo + hi) / 2) * 60, 1)})


# =====================================================================
# insight 自动洞察（6）—— 对行数据一键产出「人话」结论
# =====================================================================


def _load_table(request):
    """复用 rows 数组或 dataset_id 两种来源。"""
    from .views_data import load_rows
    return load_rows(request)[0]


def _num_cols(rows):
    cols = []
    for key in (rows[0] or {}):
        vals = [r.get(key) for r in rows if r.get(key) not in (None, "")]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            cols.append(key)
    return cols


def _stats_1d(xs):
    from .statkit import mean, median, quantile
    s = sorted(xs)
    n = len(s)
    return {"n": n, "mean": round(mean(xs), 4), "median": round(median(s), 4),
            "min": s[0], "max": s[-1],
            "p25": round(quantile(s, 0.25), 4), "p75": round(quantile(s, 0.75), 4)}


@endpoint()
def insight_overview(request):
    """全自动概览：字段类型分布、数值列统计、缺失率 TOP、行数规模。"""
    rows = _load_table(request)
    if not rows:
        raise ValueError("数据为空")
    num_cols = _num_cols(rows)
    missing = {}
    for key in rows[0]:
        cnt = sum(1 for r in rows if r.get(key) in (None, ""))
        if cnt:
            missing[key] = round(cnt / len(rows) * 100, 1)
    missing_top = sorted(missing.items(), key=lambda kv: -kv[1])[:5]
    findings = []
    if len(rows) < 30:
        findings.append(f"样本量偏小（{len(rows)} 行），结论仅供参考")
    for k, v in missing_top:
        if v > 20:
            findings.append(f"字段 {k} 缺失率 {v}%，建议清洗")
        else:
            findings.append(f"字段 {k} 存在少量缺失（{v}%），可留意")
    if not missing_top:
        findings.append("无缺失值，数据完整度良好")
    return ok({"row_count": len(rows), "col_count": len(rows[0]),
               "numeric_columns": num_cols,
               "numeric_profiles": {k: _stats_1d([r[k] for r in rows
                                                  if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)])
                                    for k in num_cols[:8]},
               "missing_top": [{"column": k, "missing_pct": v} for k, v in missing_top],
               "findings": findings})


@endpoint()
def insight_anomaly_brief(request):
    """异常简报：IQR 与 Z-Score 双法交叉，只报双法命中的稳健异常。"""
    column = req_str(request, "column")
    rows = _load_table(request)
    xs = [float(r[column]) for r in rows
          if isinstance(r.get(column), (int, float)) and not isinstance(r.get(column), bool)]
    if len(xs) < 8:
        raise ValueError("该列有效数值不足 8 个，无法判定异常")
    s = sorted(xs)
    from .statkit import mean, quantile
    q1, q3 = quantile(s, 0.25), quantile(s, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mu, sigma = mean(xs), (sum((x - mean(xs)) ** 2 for x in xs) / len(xs)) ** 0.5 or 1e-9
    by_iqr = {x for x in xs if x < lo or x > hi}
    by_z = {x for x in xs if abs((x - mu) / sigma) > 3}
    robust = sorted(by_iqr & by_z)
    return ok({"column": column, "bounds_iqr": [round(lo, 4), round(hi, 4)],
               "n_iqr_hits": len(by_iqr), "n_z_hits": len(by_z),
               "robust_outliers": robust[:50],
               "conclusion": f"双法共同命中 {len(robust)} 个异常值" + ("，可信度较高" if robust else "，整体干净")} if True else {})


@endpoint()
def insight_trend_brief(request):
    """趋势简报：线性斜率 + 头尾环比，输出上/下行判断。"""
    column = req_str(request, "column")
    rows = _load_table(request)
    xs = [float(r[column]) for r in rows
          if isinstance(r.get(column), (int, float)) and not isinstance(r.get(column), bool)]
    if len(xs) < 3:
        raise ValueError("至少需要 3 个有效数值")
    n = len(xs)
    mean_x, mean_y = (n - 1) / 2, sum(xs) / n
    slope = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(xs)) / \
        (sum((i - mean_x) ** 2 for i in range(n)) or 1e-9)
    change_pct = (xs[-1] - xs[0]) / (abs(xs[0]) or 1e-9) * 100
    direction = "上行" if slope > 0 else ("下行" if slope < 0 else "持平")
    return ok({"column": column, "slope_per_step": round(slope, 6),
               "first": xs[0], "last": xs[-1], "change_pct": round(change_pct, 2),
               "direction": direction,
               "statement": f"{column} 呈{direction}趋势，全程变化 {change_pct:+.1f}%（{n} 个点）"})


@endpoint()
def insight_corr_top(request):
    """相关性发现：数值列两两 Pearson，返回 |r| 最高的前 N 组。"""
    from .statkit import pearson
    top_n = int(opt_num(request, "top", 5, minimum=1, maximum=20) or 5)
    rows = _load_table(request)
    cols = _num_cols(rows)
    if len(cols) < 2:
        raise ValueError("数值列不足 2 个，无法计算相关性")
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a = [float(r[cols[i]]) for r in rows if isinstance(r.get(cols[i]), (int, float))]
            b = [float(r[cols[j]]) for r in rows if isinstance(r.get(cols[j]), (int, float))]
            m = min(len(a), len(b))
            if m >= 5:
                pairs.append({"a": cols[i], "b": cols[j], "r": round(pearson(a[:m], b[:m]), 4), "n": m})
    pairs.sort(key=lambda pr: -abs(pr["r"]))
    return ok({"columns": cols, "pairs": pairs[:top_n],
               "note": "r>0.7 强相关；|r|>0.4 中等；正负号代表方向"} if pairs else {"pairs": []})


@endpoint()
def insight_segment_diff(request):
    """分组差异：按类别列拆分，比较各组的数值列均值与组间极差。"""
    group_by = req_str(request, "group_by")
    column = req_str(request, "column")
    rows = _load_table(request)
    groups = {}
    for r in rows:
        g = str(r.get(group_by, ""))
        if isinstance(r.get(column), (int, float)) and not isinstance(r.get(column), bool):
            groups.setdefault(g, []).append(float(r[column]))
    groups = {g: v for g, v in groups.items() if len(v) >= 2}
    if len(groups) < 2:
        raise ValueError("至少需要 2 个含 2 条记录的分组")
    from .statkit import mean
    stats = [{"group": g, "n": len(v), "mean": round(mean(v), 4),
              "min": min(v), "max": max(v)} for g, v in groups.items()]
    stats.sort(key=lambda x: -x["mean"])
    gap = round(stats[0]["mean"] - stats[-1]["mean"], 4)
    return ok({"group_by": group_by, "column": column, "segments": stats,
               "highest": stats[0]["group"], "lowest": stats[-1]["group"], "gap": gap,
               "statement": f"{stats[0]['group']} 均值最高（{stats[0]['mean']}），"
                            f"比最低的 {stats[-1]['group']} 高 {gap}"})


@endpoint()
def insight_narrate(request):
    """自动叙述：把概览+趋势+异常揉成一段中文洞察（配置 LLM 时由大模型润色）。"""
    rows = _load_table(request)
    if not rows:
        raise ValueError("数据为空")
    num_cols = _num_cols(rows)
    sentences = [f"共 {len(rows)} 行、{len(rows[0])} 列，其中数值列 {len(num_cols)} 个。"]
    for k in num_cols[:3]:
        xs = [float(r[k]) for r in rows if isinstance(r.get(k), (int, float))]
        if len(xs) >= 3:
            st = _stats_1d(xs)
            sentences.append(f"{k} 均值 {st['mean']}，区间 [{st['min']}, {st['max']}]，中位数 {st['median']}。")
    from assistant.llm import chat, is_configured
    provider = "local-template"
    if is_configured():
        try:
            text = chat("\n".join(sentences) + "\n请用 3 句话以内总结这份业务数据，面向运营同学。")
            sentences = [text]
            provider = "llm"
        except Exception:
            pass
    return ok({"narrative": " ".join(sentences), "provider": provider,
               "numeric_columns": num_cols})


# =====================================================================
# geo 补充：坐标解析（1）
# =====================================================================


@endpoint()
def geo_parse(request):
    """坐标解析：'lat,lng' 字符串 / [lat,lng] 数组 / 城市名 → 标准化坐标。"""
    raw = req(request, "value")
    if isinstance(raw, str):
        parts = raw.strip().replace("，", ",").split(",")
        try:
            point, name = (float(parts[0]), float(parts[1])), None
            source = "coordinates"
        except (TypeError, ValueError):
            point, name = _resolve_point(raw)
            source = "builtin-city-table"
    elif isinstance(raw, (list, tuple)):
        point, name = _resolve_point(list(raw))
        source = "coordinates"
    else:
        raise ValueError("value 需为 'lat,lng' / [lat,lng] / 城市名")
    return ok({"input": raw, "lat": point[0], "lng": point[1],
               "latlng": [point[0], point[1]], "city": name, "source": source})


EXTRA_FAMILY_COUNT = 8 + 5 + 4 + 4 + 5 + 6 + 1  # = 33
