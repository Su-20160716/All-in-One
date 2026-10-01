# -*- coding: utf-8 -*-
"""minitools · 生活计算家族（8 个，F715–F722）。

去重：minitools/finance 做贷款利息、convert 做单位换算；这里只做生活场景的实用估算。
"""
import math
import random

from .common import endpoint, ok, opt_bool, opt_num, opt_str, req_list, req_num


@endpoint()
def paint_usage(request):
    """LF01. 装修用量：按面积与涂布率估算涂料/腻子用量。"""
    area = req_num(request, "area_m2", minimum=0)
    coats = req_num(request, "coats", integer=True, default=2, minimum=1, maximum=6)
    coverage = req_num(request, "coverage_m2_per_l", default=10, minimum=0.1)
    waste = opt_num(request, "waste_rate", default=0.1)
    liters = area * int(coats) / coverage * (1 + waste)
    buckets = math.ceil(liters / 5)  # 常见 5L 装
    return ok({
        "area_m2": area, "coats": int(coats), "coverage_m2_per_l": coverage,
        "waste_rate": waste,
        "liters": round(liters, 2),
        "buckets_5l": buckets,
        "note": "含损耗系数；门窗可另按面积扣除，乳胶漆通常刷 2 遍。",
    })


@endpoint()
def taxi_fare(request):
    """LF02. 打车费：起步价 + 里程费 + 时长费 + 夜间加价。"""
    distance = req_num(request, "distance_km", minimum=0)
    duration = opt_num(request, "duration_min", default=0)
    base = opt_num(request, "base_fare", default=13.0)
    base_km = opt_num(request, "base_km", default=3.0)
    per_km = opt_num(request, "per_km", default=2.5)
    per_min = opt_num(request, "per_min", default=0.0)
    night = opt_bool(request, "night", False)
    night_rate = opt_num(request, "night_rate", default=0.2)
    extra_km = max(0.0, distance - base_km)
    fare = base + extra_km * per_km + duration * per_min
    if night:
        fare *= (1 + night_rate)
    return ok({
        "distance_km": distance, "duration_min": duration,
        "base_fare": base, "extra_km": round(extra_km, 3),
        "fare_before_night": round(base + extra_km * per_km + duration * per_min, 2),
        "night": night, "fare": round(fare, 2),
        "note": "各城市计价规则不同，这里按常用参数估算；夜间加价默认 20%。",
    })


@endpoint()
def carpool_split(request):
    """LF03. 拼车分摊：按各自乘车里程分摊车费。"""
    total_fare = req_num(request, "total_fare", minimum=0)
    legs = req_list(request, "legs", max_len=20)
    if not legs:
        raise ValueError("legs 不能为空，每项为该乘客的乘车里程(km)")
    try:
        dists = [float(x) for x in legs]
    except (TypeError, ValueError):
        raise ValueError("legs 每项必须是数字")
    if any(d < 0 for d in dists):
        raise ValueError("里程不能为负")
    total = sum(dists)
    if total <= 0:
        raise ValueError("里程合计必须大于 0")
    rows = []
    for i, d in enumerate(dists):
        rows.append({"index": i + 1, "km": round(d, 3),
                     "ratio": round(d / total, 4),
                     "share": round(total_fare * d / total, 2)})
    return ok({"total_fare": total_fare, "total_km": round(total, 3),
               "list": rows,
               "note": "按里程比例分摊；如需按人头平摊，把 legs 全部填相同里程即可。"})


@endpoint()
def red_packet(request):
    """LF04. 红包分配：把总金额随机拆成 N 份（二倍均值法）。"""
    total = req_num(request, "amount", minimum=0.01)
    count = req_num(request, "count", integer=True, minimum=1, maximum=1000)
    min_amount = opt_num(request, "min_amount", default=0.01)
    n = int(count)
    if min_amount <= 0:
        raise ValueError("min_amount 必须大于 0")
    if total < min_amount * n:
        raise ValueError(f"总金额不足以让每份至少 {min_amount} 元")
    seed = opt_num(request, "seed")
    rnd = random.Random(int(seed)) if seed is not None else random.Random()
    remain = total
    rows = []
    for i in range(n):
        left = n - i
        if left == 1:
            amt = remain
        else:
            avg = remain / left
            hi = min(avg * 2, remain - min_amount * (left - 1))
            amt = rnd.uniform(min_amount, hi) if hi > min_amount else min_amount
        amt = round(amt, 2)
        remain = round(remain - amt, 2)
        rows.append(amt)
    return ok({"amount": total, "count": n, "min_amount": min_amount,
               "list": rows, "sum": round(sum(rows), 2),
               "max": max(rows), "min": min(rows),
               "note": "二倍均值法；给 seed 可复现。金额单位与入参一致（元）。"})


@endpoint()
def table_seating(request):
    """LF05. 配桌：按人数与每桌容量算出桌数与余位。"""
    guests = req_num(request, "guests", integer=True, minimum=1)
    per_table = req_num(request, "per_table", integer=True, minimum=1, maximum=20)
    reserve = opt_num(request, "reserve_tables", default=0)
    g, p = int(guests), int(per_table)
    tables = math.ceil(g / p)
    total_tables = tables + int(reserve)
    seats = total_tables * p
    return ok({
        "guests": g, "per_table": p,
        "tables_needed": tables, "reserve_tables": int(reserve),
        "total_tables": total_tables, "total_seats": seats,
        "empty_seats": seats - g,
        "note": "建议每桌留 1~2 个机动位，可把 reserve_tables 设为 1。",
    })


@endpoint()
def wedding_budget(request):
    """LF06. 婚礼预算：按项目比例估算各项花费。"""
    total = req_num(request, "total_budget", minimum=0)
    preset = (opt_str(request, "preset", "standard") or "standard").lower()
    RATIOS = {
        "simple": {"婚宴": 0.45, "婚庆布置": 0.12, "婚纱摄影": 0.12, "三金首饰": 0.10,
                   "婚车礼服": 0.06, "喜糖请柬": 0.05, "蜜月": 0.10},
        "standard": {"婚宴": 0.42, "婚庆布置": 0.15, "婚纱摄影": 0.13, "三金首饰": 0.12,
                     "婚车礼服": 0.07, "喜糖请柬": 0.05, "蜜月": 0.06},
        "luxury": {"婚宴": 0.40, "婚庆布置": 0.18, "婚纱摄影": 0.12, "三金首饰": 0.15,
                   "婚车礼服": 0.08, "喜糖请柬": 0.03, "蜜月": 0.04},
    }
    if preset not in RATIOS:
        raise ValueError("preset 可选 simple / standard / luxury")
    rows = [{"item": k, "ratio": v, "amount": round(total * v, 2)}
            for k, v in RATIOS[preset].items()]
    return ok({"total_budget": total, "preset": preset, "list": rows,
               "note": "比例参考常见婚礼支出结构，可按当地行情自行调整。"})


@endpoint()
def fuel_cost(request):
    """LF07. 油耗成本：按百公里油耗、里程与油价算油费。"""
    distance = req_num(request, "distance_km", minimum=0)
    per_100km = req_num(request, "consumption_l_per_100km", minimum=0)
    price = req_num(request, "price_per_l", minimum=0)
    liters = distance / 100.0 * per_100km
    return ok({
        "distance_km": distance,
        "consumption_l_per_100km": per_100km,
        "price_per_l": price,
        "liters": round(liters, 3),
        "cost": round(liters * price, 2),
        "cost_per_km": round(liters * price / distance, 4) if distance else None,
    })


@endpoint()
def tile_layout(request):
    """LF08. 地砖铺贴：按房间与砖规格算用砖量与损耗。"""
    length = req_num(request, "room_length_m", minimum=0)
    width = req_num(request, "room_width_m", minimum=0)
    tile_l = req_num(request, "tile_length_m", minimum=0.001)
    tile_w = req_num(request, "tile_width_m", minimum=0.001)
    waste = opt_num(request, "waste_rate", default=0.08)
    room_area = length * width
    tile_area = tile_l * tile_w
    exact = room_area / tile_area
    with_waste = exact * (1 + waste)
    return ok({
        "room_area_m2": round(room_area, 4),
        "tile_area_m2": round(tile_area, 6),
        "tiles_exact": round(exact, 2),
        "tiles_with_waste": math.ceil(with_waste),
        "waste_rate": waste,
        "note": "斜铺或异形房间损耗更高，可把 waste_rate 调到 0.1~0.15。",
    })
