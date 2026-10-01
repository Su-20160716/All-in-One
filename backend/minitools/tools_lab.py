# -*- coding: utf-8 -*-
"""minitools · 实验室家族（6 个，F741–F746）。

去重：minitools/science 做物理化学公式；这里只做「配制/滴定/浓度换算/有效数字/温度表」这类实验台计算。
"""
import math

from .common import endpoint, ok, opt_num, opt_str, req_num

# 常见物质的摩尔质量（g/mol），仅作默认值，可被入参覆盖
MOLAR_MASS = {
    "nacl": 58.44, "naoh": 40.00, "hcl": 36.46, "h2so4": 98.08, "hno3": 63.01,
    "koh": 56.11, "k2cr2o7": 294.18, "kmno4": 158.03, "na2co3": 105.99,
    "cuso4": 159.61, "cuso4·5h2o": 249.69, "glucose": 180.16, "edta": 372.24,
    "na2s2o3": 158.11, "agno3": 169.87, "ch3cooh": 60.05, "nh4cl": 53.49,
}


def _round_sig(x, digits):
    """按有效数字位数四舍五入。"""
    if x == 0:
        return 0.0
    d = math.ceil(math.log10(abs(x)))
    power = digits - d
    factor = 10 ** power
    return round(x * factor) / factor


def _count_sig(raw):
    """数一个数字字符串的有效数字位数。"""
    s = str(raw).strip().lstrip("+-")
    if not s or not any(c.isdigit() for c in s):
        return 0
    if "e" in s.lower():
        s = s.lower().split("e")[0]
    if "." in s:
        return len(s.replace(".", "").lstrip("0")) or 1
    return len(s.rstrip("0")) or 1


@endpoint()
def dilution(request):
    """LB01. 稀释配制：C1V1 = C2V2，给任意三个求第四个。"""
    c1 = opt_num(request, "c1")
    v1 = opt_num(request, "v1")
    c2 = opt_num(request, "c2")
    v2 = opt_num(request, "v2")
    known = [x is not None for x in (c1, v1, c2, v2)]
    if sum(known) != 3:
        raise ValueError("请给出 C1/V1/C2/V2 中的任意三个")
    if c1 is None:
        c1 = c2 * v2 / v1
    elif v1 is None:
        v1 = c2 * v2 / c1
    elif c2 is None:
        c2 = c1 * v1 / v2
    else:
        v2 = c1 * v1 / c2
    if v2 is not None and v2 <= 0:
        raise ValueError("V2 计算结果非正，请检查入参")
    return ok({
        "c1": round(c1, 8), "v1": round(v1, 6),
        "c2": round(c2, 8), "v2": round(v2, 6),
        "solvent_to_add": round(v2 - v1, 6) if (v2 is not None and v1 is not None) else None,
        "note": "单位只需左右一致（如 C 用 mol/L、V 用 mL）。",
    })


@endpoint()
def titration(request):
    """LB02. 滴定体积：按 c1V1/n1 = c2V2/n2 求未知量。"""
    c1 = req_num(request, "c1", minimum=0)
    v1 = req_num(request, "v1", minimum=0)
    n1 = opt_num(request, "n1", default=1)
    n2 = opt_num(request, "n2", default=1)
    if n1 <= 0 or n2 <= 0:
        raise ValueError("n1 / n2 必须大于 0")
    c2 = opt_num(request, "c2")
    v2 = opt_num(request, "v2")
    if c2 is None and v2 is None:
        raise ValueError("请提供 c2（求体积）或 v2（求浓度）之一")
    out = {"c1": c1, "v1": v1, "n1": n1, "n2": n2}
    if v2 is None:
        v2 = c1 * v1 * n2 / (c2 * n1)
        out.update({"c2": c2, "v2": round(v2, 6), "solved": "v2"})
    else:
        c2 = c1 * v1 * n2 / (v2 * n1)
        out.update({"c2": round(c2, 8), "v2": v2, "solved": "c2"})
    return ok(out)


@endpoint()
def concentration_convert(request):
    """LB03. 浓度单位互换：mol/L、g/L、质量分数%、ppm 之间换算。"""
    value = req_num(request, "value")
    frm = (opt_str(request, "from", "mol_l") or "mol_l").lower()
    to = (opt_str(request, "to", "g_l") or "g_l").lower()
    m = opt_num(request, "molar_mass")
    if m is None:
        name = (opt_str(request, "substance", "") or "").strip().lower()
        m = MOLAR_MASS.get(name)
    if m is None or m <= 0:
        raise ValueError("请提供 molar_mass（g/mol），或用 substance 指定常见物质（nacl/naoh/h2so4…）")

    # 先统一到 g/L（ppm 与 % 需要密度，用 density 折算，默认 1 g/mL 即稀水溶液）
    density = opt_num(request, "density_g_ml", default=1.0)
    if density <= 0:
        raise ValueError("density_g_ml 必须大于 0")
    if frm == "mol_l":
        g_l = value * m
    elif frm == "g_l":
        g_l = value
    elif frm in ("percent", "%", "mass_percent"):
        g_l = value / 100.0 * density * 1000.0
    elif frm == "ppm":
        g_l = value / 1e6 * density * 1000.0
    else:
        raise ValueError("from 可选 mol_l / g_l / percent / ppm")

    if to == "mol_l":
        out = g_l / m
    elif to == "g_l":
        out = g_l
    elif to in ("percent", "%", "mass_percent"):
        out = g_l / (density * 1000.0) * 100.0
    elif to == "ppm":
        out = g_l / (density * 1000.0) * 1e6
    else:
        raise ValueError("to 可选 mol_l / g_l / percent / ppm")
    return ok({"from": frm, "to": to, "value": value, "result": round(out, 8),
               "molar_mass": m, "density_g_ml": density,
               "g_per_l": round(g_l, 8),
               "note": "percent/ppm 换算按 density_g_ml（默认 1）折算，浓溶液请填真实密度。"})


@endpoint()
def standard_solution(request):
    """LB04. 标准液配制：算需称取的固体质量或需量取的母液体积。"""
    c = req_num(request, "c", minimum=0)
    v_ml = req_num(request, "v_ml", minimum=0)
    m = opt_num(request, "molar_mass")
    if m is None:
        name = (opt_str(request, "substance", "") or "").strip().lower()
        m = MOLAR_MASS.get(name)
    if m is None or m <= 0:
        raise ValueError("请提供 molar_mass（g/mol），或用 substance 指定常见物质")
    purity = opt_num(request, "purity", default=1.0)
    if not (0 < purity <= 1):
        raise ValueError("purity 需在 (0, 1] 之间，如 0.999 表示 99.9%")
    moles = c * (v_ml / 1000.0)
    mass = moles * m
    actual = mass / purity
    return ok({
        "c": c, "v_ml": v_ml, "molar_mass": m, "purity": purity,
        "moles": round(moles, 8),
        "mass_g": round(mass, 6),
        "mass_with_purity_g": round(actual, 6),
        "note": "先用少量溶剂溶解、转移入容量瓶、定容到刻度并摇匀；固体需先干燥恒重。",
    })


@endpoint()
def sig_figs(request):
    """LB05. 有效数字复算：数位数 + 按指定位数取整。"""
    raw = opt_str(request, "value", "")
    if not raw:
        raise ValueError("请提供 value（数字或数字字符串）")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"value 不是数字: {raw}")
    digits = opt_num(request, "digits")
    out = {"input": raw, "value": val, "sig_figs": _count_sig(raw)}
    if digits is not None:
        d = int(digits)
        if d < 1 or d > 15:
            raise ValueError("digits 需在 1~15 之间")
        out["rounded"] = _round_sig(val, d)
        out["rounded_str"] = f"{_round_sig(val, d):.{max(0, d - 1)}e}" if abs(val) >= 1e6 or (val != 0 and abs(val) < 1e-4) else repr(_round_sig(val, d))
    return ok(out)


@endpoint()
def temp_table(request):
    """LB06. 温度换算表：给定区间生成摄氏/华氏/开尔文对照表。"""
    start = req_num(request, "start", default=0)
    end = req_num(request, "end", default=100)
    step = req_num(request, "step", default=10)
    if step <= 0:
        raise ValueError("step 必须大于 0")
    if end < start:
        raise ValueError("end 不能小于 start")
    n = int((end - start) / step) + 1
    if n > 500:
        raise ValueError("步长过小导致行数超过 500，请增大 step")
    rows = []
    for i in range(n):
        c = start + i * step
        rows.append({"c": round(c, 4), "f": round(c * 9 / 5 + 32, 4), "k": round(c + 273.15, 4)})
    return ok({"start": start, "end": end, "step": step, "rows": rows, "count": len(rows)})
