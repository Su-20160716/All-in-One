# -*- coding: utf-8 -*-
"""minitools · 健康计算家族（12 个）。

去重：num/bmi-calc 已存在，这里做 BMR/TDEE/体脂/心率/血糖单位等更细分工具。
"""
import math

from .common import endpoint, ok, opt_num, req_num, opt_str

_ACTIVITY = {
    "sedentary": 1.2, "light": 1.375, "moderate": 1.55,
    "active": 1.725, "very_active": 1.9,
}


@endpoint()
def bmr(request):
    """H01. 基础代谢率（Mifflin-St Jeor）。"""
    weight = req_num(request, "weight_kg", minimum=0)
    height = req_num(request, "height_cm", minimum=0)
    age = req_num(request, "age", minimum=0)
    sex = opt_str(request, "sex", "male")
    base = 10 * weight + 6.25 * height - 5 * age
    bmr = base + 5 if sex == "male" else base - 161
    return ok({"bmr_kcal": round(bmr, 1)})


@endpoint()
def tdee(request):
    """H02. 每日总消耗 TDEE = BMR × 活动系数。"""
    weight = req_num(request, "weight_kg", minimum=0)
    height = req_num(request, "height_cm", minimum=0)
    age = req_num(request, "age", minimum=0)
    sex = opt_str(request, "sex", "male")
    activity = opt_str(request, "activity", "light")
    base = 10 * weight + 6.25 * height - 5 * age
    bmr = base + 5 if sex == "male" else base - 161
    factor = _ACTIVITY.get(activity, 1.375)
    return ok({"bmr_kcal": round(bmr, 1), "activity_factor": factor,
               "tdee_kcal": round(bmr * factor, 1)})


@endpoint()
def body_fat(request):
    """H03. US Navy 体脂率估算。"""
    sex = opt_str(request, "sex", "male")
    height = req_num(request, "height_cm", minimum=0)
    waist = req_num(request, "waist_cm", minimum=0)
    neck = req_num(request, "neck_cm", minimum=0)
    hip = opt_num(request, "hip_cm", default=0)
    if sex == "male":
        bf = 495 / (1.0324 - 0.19077 * math.log10(waist - neck)
                    + 0.15456 * math.log10(height)) - 450
    else:
        if hip <= 0:
            raise ValueError("女性需要提供 hip_cm")
        bf = 495 / (1.29579 - 0.35004 * math.log10(waist + hip - neck)
                    + 0.22100 * math.log10(height)) - 450
    return ok({"body_fat_pct": round(max(0, bf), 1)})


@endpoint()
def ideal_weight(request):
    """H04. 理想体重（Devine / Broca /  BMI=22 三种公式）。"""
    height = req_num(request, "height_cm", minimum=0)
    sex = opt_str(request, "sex", "male")
    if sex == "male":
        devine = 50 + 0.91 * (height - 152.4)
    else:
        devine = 45.5 + 0.91 * (height - 152.4)
    broca = (height - 100) * (0.9 if sex == "male" else 0.85)
    bmi22 = 22 * (height / 100.0) ** 2
    return ok({"devine_kg": round(devine, 1), "broca_kg": round(broca, 1),
               "bmi22_kg": round(bmi22, 1)})


@endpoint()
def water_intake(request):
    """H05. 每日饮水量估算（35ml/kg，运动出汗额外 +500ml）。"""
    weight = req_num(request, "weight_kg", minimum=0)
    active = opt_num(request, "exercise_hours", default=0)
    base = weight * 35
    extra = active * 500
    return ok({"water_ml": round(base + extra, 0),
               "base_ml": round(base, 0),
               "exercise_extra_ml": round(extra, 0)})


@endpoint()
def sleep_cycle(request):
    """H06. 睡眠周期：目标起床时间，推荐入睡时间（每周期 90 分钟）。"""
    wake_hour = req_num(request, "wake_hour", minimum=0, maximum=24)
    wake_minute = opt_num(request, "wake_minute", default=0, minimum=0, maximum=59)
    wake_total = wake_hour * 60 + wake_minute
    suggestions = []
    for cycles in (4, 5, 6, 7):
        bed = wake_total - cycles * 90 - 15  # 15 分钟入睡缓冲
        bed %= 24 * 60
        suggestions.append({
            "cycles": cycles,
            "sleep_hours": round(cycles * 1.5, 1),
            "bedtime": f"{int(bed // 60):02d}:{int(bed % 60):02d}",
        })
    return ok({"wake_time": f"{int(wake_hour):02d}:{int(wake_minute):02d}",
               "suggestions": suggestions})


@endpoint()
def calories_burn(request):
    """H07. 运动消耗：MET × 体重 × 小时。"""
    met = req_num(request, "met", minimum=0)
    weight = req_num(request, "weight_kg", minimum=0)
    hours = req_num(request, "hours", minimum=0)
    kcal = met * weight * hours
    return ok({"kcal": round(kcal, 1)})


@endpoint()
def heart_zone(request):
    """H08. 目标心率区间（220-年龄法 + Karvonen）。"""
    age = req_num(request, "age", minimum=0)
    resting = opt_num(request, "resting_hr", default=0)
    max_hr = 220 - age
    zones = []
    names = ["热身 50-60%", "减脂 60-70%", "有氧 70-80%", "无氧 80-90%", "极限 90-100%"]
    lo_hi = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
    for name, (lo, hi) in zip(names, lo_hi):
        if resting:
            lo_v = (max_hr - resting) * lo + resting
            hi_v = (max_hr - resting) * hi + resting
        else:
            lo_v = max_hr * lo
            hi_v = max_hr * hi
        zones.append({"zone": name, "bpm": f"{int(round(lo_v))}-{int(round(hi_v))}"})
    return ok({"max_hr": max_hr, "zones": zones})


@endpoint()
def macro(request):
    """H09. 宏量营养素分配：按目标给碳水/蛋白/脂肪克数。"""
    calories = req_num(request, "calories", minimum=0)
    goal = opt_str(request, "goal", "maintain")  # lose/maintain/gain
    ratios = {"lose": (0.40, 0.35, 0.25),
              "maintain": (0.50, 0.25, 0.25),
              "gain": (0.50, 0.25, 0.25)}
    c, p_, f = ratios.get(goal, ratios["maintain"])
    return ok({
        "carbs_g": round(calories * c / 4, 1),
        "protein_g": round(calories * p_ / 4, 1),
        "fat_g": round(calories * f / 9, 1),
    })


@endpoint()
def bp_category(request):
    """H10. 血压分类（中国标准）。"""
    systolic = req_num(request, "systolic", minimum=0)
    diastolic = req_num(request, "diastolic", minimum=0)
    if systolic < 120 and diastolic < 80:
        cat = "理想血压"
    elif systolic < 130 and diastolic < 85:
        cat = "正常血压"
    elif systolic < 140 or diastolic < 90:
        cat = "正常高值"
    elif systolic < 160 or diastolic < 100:
        cat = "高血压 1 级"
    elif systolic < 180 or diastolic < 110:
        cat = "高血压 2 级"
    else:
        cat = "高血压 3 级"
    return ok({"category": cat, "systolic": systolic, "diastolic": diastolic})


@endpoint()
def glucose_unit(request):
    """H11. 血糖单位换算 mg/dL ↔ mmol/L（÷18）。"""
    value = req_num(request, "value", minimum=0)
    direction = opt_str(request, "direction", "mgdl_to_mmol")
    if direction == "mgdl_to_mmol":
        return ok({"mg_dL": round(value, 1), "mmol_L": round(value / 18.0, 2)})
    return ok({"mg_dL": round(value * 18.0, 1), "mmol_L": round(value, 2)})


@endpoint()
def whr(request):
    """H12. 腰臀比 WHR 与健康风险。"""
    waist = req_num(request, "waist_cm", minimum=0)
    hip = req_num(request, "hip_cm", minimum=0.0001)
    sex = opt_str(request, "sex", "male")
    ratio = waist / hip
    if sex == "male":
        risk = "中心性肥胖" if ratio >= 0.9 else "正常"
    else:
        risk = "中心性肥胖" if ratio >= 0.85 else "正常"
    return ok({"whr": round(ratio, 2), "risk": risk})
