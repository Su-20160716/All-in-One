# -*- coding: utf-8 -*-
"""minitools · 转换器家族（22 个，编号 171-192）。"""
import math
import re

from .common import endpoint, ok, opt_num, opt_str, req_num, req_str


def _convert(value, frm, to, units):
    """通用单位换算：先归一到基准单位，再转目标。"""
    if frm not in units or to not in units:
        raise ValueError(f"支持的单位: {list(units.keys())}")
    return value * units[frm] / units[to]


@endpoint()
def temperature(request):
    """171. 温度转换（C/F/K）。"""
    value = req_num(request, "value")
    frm = opt_str(request, "from", "C")
    to = opt_str(request, "to", "F")
    # 先转 C
    if frm == "C":
        c = value
    elif frm == "F":
        c = (value - 32) * 5 / 9
    elif frm == "K":
        c = value - 273.15
    else:
        raise ValueError("from 必须是 C/F/K")
    if to == "C":
        result = c
    elif to == "F":
        result = c * 9 / 5 + 32
    elif to == "K":
        result = c + 273.15
    else:
        raise ValueError("to 必须是 C/F/K")
    return ok({"result": round(result, 4)})


@endpoint()
def length(request):
    """172. 长度转换。"""
    units = {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "inch": 0.0254, "ft": 0.3048, "yd": 0.9144, "mile": 1609.344}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "m"), opt_str(request, "to", "ft"), units), 4)})


@endpoint()
def weight(request):
    """173. 重量转换。"""
    units = {"g": 1, "kg": 1000, "t": 1000000, "oz": 28.3495, "lb": 453.5924}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "kg"), opt_str(request, "to", "lb"), units), 4)})


@endpoint()
def area(request):
    """174. 面积转换。"""
    units = {"m2": 1, "km2": 1e6, "cm2": 0.0001, "ha": 10000, "acre": 4046.86, "ft2": 0.0929, "sqmi": 2.59e6}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "m2"), opt_str(request, "to", "ft2"), units), 4)})


@endpoint()
def volume(request):
    """175. 体积转换。"""
    units = {"ml": 0.001, "l": 1, "m3": 1000, "gal": 3.7854, "qt": 0.9464, "cup": 0.2366, "floz": 0.0296}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "l"), opt_str(request, "to", "gal"), units), 4)})


@endpoint()
def speed(request):
    """176. 速度转换。"""
    units = {"mps": 1, "kmh": 0.2778, "mph": 0.4470, "knot": 0.5144, "fps": 0.3048}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "kmh"), opt_str(request, "to", "mph"), units), 4)})


@endpoint()
def data_size(request):
    """177. 数据大小转换。"""
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4, "PB": 1024**5}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "MB"), opt_str(request, "to", "GB"), units), 4)})


@endpoint()
def time_unit(request):
    """178. 时间单位转换。"""
    units = {"ms": 0.001, "s": 1, "min": 60, "h": 3600, "day": 86400, "week": 604800, "year": 31536000}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "h"), opt_str(request, "to", "min"), units), 4)})


@endpoint()
def angle(request):
    """179. 角度转换。"""
    units = {"deg": 1, "rad": 57.2958, "grad": 0.9, "turn": 360}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "deg"), opt_str(request, "to", "rad"), units), 4)})


@endpoint()
def pressure(request):
    """180. 压力转换。"""
    units = {"pa": 1, "kpa": 1000, "bar": 100000, "psi": 6894.76, "atm": 101325, "mmhg": 133.322}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "bar"), opt_str(request, "to", "psi"), units), 4)})


@endpoint()
def energy(request):
    """181. 能量转换。"""
    units = {"j": 1, "kj": 1000, "cal": 4.184, "kcal": 4184, "wh": 3600, "kwh": 3.6e6, "btu": 1055.06}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "kcal"), opt_str(request, "to", "kj"), units), 4)})


@endpoint()
def power(request):
    """182. 功率转换。"""
    units = {"w": 1, "kw": 1000, "mw": 1e6, "hp": 745.7, "btu_h": 0.2931}
    value = req_num(request, "value")
    return ok({"result": round(_convert(value, opt_str(request, "from", "hp"), opt_str(request, "to", "kw"), units), 4)})


@endpoint()
def fuel_efficiency(request):
    """183. 燃油效率转换（L/100km <-> MPG）。"""
    value = req_num(request, "value", minimum=0.001)
    frm = opt_str(request, "from", "l100km")
    to = opt_str(request, "to", "mpg")
    if frm == to:
        return ok({"result": value})
    if frm == "l100km" and to == "mpg":
        return ok({"result": round(235.214 / value, 2)})
    if frm == "mpg" and to == "l100km":
        return ok({"result": round(235.214 / value, 2)})
    raise ValueError("from/to 必须是 l100km 或 mpg")


_SHOE_CN_MEN = {38: 240, 39: 245, 40: 250, 41: 255, 42: 260, 43: 265, 44: 270, 45: 275}
_SHOE_CN_WOMEN = {35: 225, 36: 230, 37: 235, 38: 240, 39: 245, 40: 250}


@endpoint()
def shoe_size(request):
    """184. 鞋码转换（EU/US/UK/CN）。"""
    value = req_num(request, "value", minimum=1)
    frm = opt_str(request, "from", "EU")
    to = opt_str(request, "to", "CN")
    gender = opt_str(request, "gender", "men")
    # 简化：EU <-> CN 毫米
    if frm == "EU" and to == "CN":
        cn = int(value * 1.5 + (value * 1.5 % 5 > 0)) if False else int((value + 18) * 10)
        return ok({"result": round(cn, 0)})
    if frm == "CN" and to == "EU":
        return ok({"result": round(value / 10 - 18, 1)})
    if frm == "US" and to == "EU":
        return ok({"result": round(value + (39 if gender == "men" else 37), 1)})
    if frm == "UK" and to == "EU":
        return ok({"result": round(value + (40 if gender == "men" else 38), 1)})
    raise ValueError(f"暂不支持 {frm}->{to}，常用组合：EU<->CN, US->EU, UK->EU")


@endpoint()
def apparel_size(request):
    """185. 服装尺码转换。"""
    value = req_str(request, "value").upper()
    to = opt_str(request, "to", "CN").upper()
    mapping = {"XS": {"CN": "160/84A", "US": "XS", "EU": "XS"},
               "S": {"CN": "165/88A", "US": "S", "EU": "S"},
               "M": {"CN": "170/92A", "US": "M", "EU": "M"},
               "L": {"CN": "175/96A", "US": "L", "EU": "L"},
               "XL": {"CN": "180/100A", "US": "XL", "EU": "XL"},
               "XXL": {"CN": "185/104A", "US": "XXL", "EU": "XXL"}}
    if value not in mapping:
        raise ValueError("value 必须是 XS/S/M/L/XL/XXL")
    return ok({"result": mapping[value].get(to, value)})


@endpoint()
def number_system(request):
    """186. 数字系统转换（中/阿/罗）。"""
    value = req_str(request, "value")
    frm = opt_str(request, "from", "arabic")
    to = opt_str(request, "to", "roman")
    if frm == "arabic" and to == "roman":
        n = int(value)
        # 经典罗马数字只到 3999；更大的值会让循环退化成长串 M
        if not 1 <= n <= 3999:
            raise ValueError("罗马数字仅支持 1-3999")
        roman = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                 (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                 (5, "V"), (4, "IV"), (1, "I")]
        out = []
        for v, s in roman:
            while n >= v:
                out.append(s)
                n -= v
        return ok({"result": "".join(out)})
    if frm == "roman" and to == "arabic":
        roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total, prev = 0, 0
        for ch in reversed(value.upper()):
            v = roman_map.get(ch, 0)
            total += -v if v < prev else v
            prev = v
        return ok({"result": total})
    raise ValueError("from/to 组合支持 arabic<->roman")


_NOTE_FREQ = {"C": 261.63, "C#": 277.18, "D": 293.66, "D#": 311.13, "E": 329.63,
              "F": 349.23, "F#": 369.99, "G": 392.00, "G#": 415.30, "A": 440.00,
              "A#": 466.16, "B": 493.88}


@endpoint()
def note_frequency(request):
    """187. 音符频率转换。"""
    note = req_str(request, "note").upper()
    octave = int(opt_num(request, "octave", 4, minimum=0, maximum=8, integer=True))
    if note not in _NOTE_FREQ:
        raise ValueError(f"音符必须是 {list(_NOTE_FREQ.keys())}")
    freq = _NOTE_FREQ[note] * (2 ** (octave - 4))
    wavelength = 343 / freq * 100  # cm
    return ok({"frequency": round(freq, 2), "wavelength": round(wavelength, 2)})


@endpoint()
def base_arbitrary(request):
    """188. 任意进制转换（2-36）。"""
    value = req_str(request, "value").strip()
    frm = int(req_num(request, "from", minimum=2, maximum=36, integer=True))
    to = int(req_num(request, "to", minimum=2, maximum=36, integer=True))
    B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
    neg = value.startswith("-")
    if neg:
        value = value[1:]
    try:
        dec = int(value, frm)
    except ValueError:
        raise ValueError(f"数值不是合法的 {frm} 进制数")
    if dec == 0:
        result = "0"
    else:
        digs = []
        n = dec
        while n:
            digs.append(B36[n % to])
            n //= to
        result = "".join(reversed(digs))
    return ok({"result": ("-" if neg else "") + result})


@endpoint()
def currency_format(request):
    """189. 货币格式化。"""
    amount = req_num(request, "amount")
    currency = opt_str(request, "currency", "CNY")
    symbols = {"CNY": "¥", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
    sym = symbols.get(currency, currency + " ")
    return ok({"formatted": f"{sym}{amount:,.2f}"})


@endpoint()
def percent_decimal(request):
    """190. 百分比小数互转。direction: pct2dec / dec2pct。"""
    value = req_num(request, "value")
    direction = opt_str(request, "direction", "pct2dec")
    if direction == "pct2dec":
        return ok({"result": value / 100})
    if direction == "dec2pct":
        return ok({"result": value * 100})
    raise ValueError("direction 必须是 pct2dec 或 dec2pct")


@endpoint()
def fraction_decimal(request):
    """191. 分数小数互转。direction: frac2dec / dec2frac。"""
    value = req_str(request, "value")
    direction = opt_str(request, "direction", "frac2dec")
    if direction == "frac2dec":
        if "/" not in value:
            raise ValueError("分数格式应为 a/b")
        num, den = value.split("/")
        return ok({"result": round(float(num) / float(den), 6)})
    if direction == "dec2frac":
        from fractions import Fraction
        f = Fraction(float(value)).limit_denominator(1000)
        return ok({"result": f"{f.numerator}/{f.denominator}"})
    raise ValueError("direction 必须是 frac2dec 或 dec2frac")


@endpoint()
def bmi_metric_imperial(request):
    """192. BMI 公制英制转换。unit: metric/imperial。"""
    height = req_num(request, "height")
    weight = req_num(request, "weight")
    unit = opt_str(request, "unit", "metric")
    if unit == "metric":
        h = height / 100
        bmi = weight / (h * h)
    else:  # imperial: height inches, weight lbs
        bmi = 703 * weight / (height * height)
    if bmi < 18.5:
        cat = "偏瘦"
    elif bmi < 24:
        cat = "正常"
    elif bmi < 28:
        cat = "超重"
    else:
        cat = "肥胖"
    return ok({"bmi": round(bmi, 2), "category": cat})
