# -*- coding: utf-8 -*-
"""学习工具集：40 个面向小学/初中/高中与编程学习的纯函数工具。
统一通过 LEARN_TOOL_REGISTRY 注册，POST /api/learning/tools/run/ {tool,...} 调用。
"""
import datetime as dt
import math
import random
import re
from fractions import Fraction

from learning.data import chinese as cn_data
from learning.data import chemistry as chem_data
from learning.data import english as en_data

ELEMENT_MASS = {e["symbol"]: e["mass"] for e in chem_data.ELEMENTS}


# ============================================================
# 数学类
# ============================================================
def lt_arith_gen(p):
    """T01 口算题生成器：op=add/sub/mul/div/mix，n 题，max 上限，grade 影响范围"""
    n = max(1, min(int(p.get("n", 10)), 100))
    op = p.get("op", "mix")
    upper = int(p.get("max", 20))
    ops = ["add", "sub", "mul", "div"] if op == "mix" else [op]
    items = []
    for _ in range(n):
        o = random.choice(ops)
        if o == "add":
            a, b = random.randint(1, upper), random.randint(1, upper)
            items.append({"q": f"{a} + {b} =", "a": a + b})
        elif o == "sub":
            a, b = random.randint(1, upper), random.randint(1, upper)
            if b > a:
                a, b = b, a
            items.append({"q": f"{a} - {b} =", "a": a - b})
        elif o == "mul":
            hi = min(upper, 9)
            a, b = random.randint(1, max(2, hi)), random.randint(1, max(2, hi))
            items.append({"q": f"{a} × {b} =", "a": a * b})
        else:
            b = random.randint(1, 9)
            quotient = random.randint(1, max(2, min(upper, 9)))
            a = b * quotient
            items.append({"q": f"{a} ÷ {b} =", "a": quotient})
    return {"count": len(items), "list": items}


def lt_fraction_simplify(p):
    """T02 分数化简"""
    a, b = int(p["a"]), int(p["b"])
    if b == 0:
        raise ValueError("分母不能为 0")
    f = Fraction(a, b)
    sign = "-" if f < 0 else ""
    return {"input": f"{a}/{b}", "numerator": abs(f.numerator), "denominator": f.denominator,
            "sign": sign, "result": (f"{sign}{abs(f.numerator)}" if f.denominator == 1 else f"{sign}{abs(f.numerator)}/{f.denominator}"),
            "decimal": round(float(f), 6)}


def lt_gcd_lcm(p):
    """T03 最大公约数 / 最小公倍数，支持多个数"""
    nums = [int(x) for x in re.split(r"[,，\s]+", str(p.get("nums", "")).strip()) if str(x).strip()]
    if len(nums) < 2:
        raise ValueError("至少输入两个整数，用逗号分隔")
    g = nums[0]
    for x in nums[1:]:
        g = math.gcd(g, x)
    lcm = nums[0]
    for x in nums[1:]:
        lcm = lcm * x // math.gcd(lcm, x)
    return {"nums": nums, "gcd": g, "lcm": lcm}


def lt_prime(p):
    """T04 质数判断 + 质因数分解"""
    n = int(p["n"])
    if n < 2:
        return {"n": n, "is_prime": False, "factors": [], "note": "小于 2 不是质数"}
    is_p = all(n % i for i in range(2, int(math.isqrt(n)) + 1))
    factors, x, t = [], 2, n
    while x * x <= t:
        while t % x == 0:
            factors.append(x)
            t //= x
        x += 1
    if t > 1:
        factors.append(t)
    expr = "×".join(str(x) for x in factors)
    return {"n": n, "is_prime": is_p, "factors": factors, "factor_expr": expr + f"={n}"}


_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def lt_roman(p):
    """T05 罗马数字互转"""
    mode = p.get("mode", "to_roman")
    if mode == "to_roman":
        n = int(p["n"])
        if not 0 < n < 4000:
            raise ValueError("罗马数字范围 1-3999")
        out, x = "", n
        for v, s in _ROMAN:
            while x >= v:
                out += s
                x -= v
        return {"number": n, "roman": out}
    roman = str(p["roman"]).upper().strip()
    if not re.fullmatch(r"[IVXLCDM]+", roman):
        raise ValueError("不是合法罗马数字")
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, ch in enumerate(roman):
        v = vals[ch]
        if i + 1 < len(roman) and vals[roman[i + 1]] > v:
            total -= v
        else:
            total += v
    return {"roman": roman, "number": total}


def lt_quadratic(p):
    """T06 一元二次方程 ax²+bx+c=0"""
    a, b, c = float(p["a"]), float(p["b"]), float(p["c"])
    if a == 0:
        raise ValueError("a 不能为 0（否则不是二次方程）")
    d = b * b - 4 * a * c
    base = {"a": a, "b": b, "c": c, "delta": round(d, 6)}
    if d > 0:
        x1 = (-b + math.sqrt(d)) / (2 * a)
        x2 = (-b - math.sqrt(d)) / (2 * a)
        base.update({"kind": "两个不相等实根", "roots": [round(x1, 6), round(x2, 6)]})
    elif abs(d) < 1e-9:
        base.update({"kind": "两个相等实根", "roots": [round(-b / (2 * a), 6)]})
    else:
        real, imag = -b / (2 * a), math.sqrt(-d) / (2 * a)
        base.update({"kind": "一对共轭复根", "roots": [f"{round(real,4)}±{round(imag,4)}i"]})
    return base


def lt_linear2(p):
    """T07 二元一次方程组：a1 x+b1 y=c1; a2 x+b2 y=c2"""
    a1, b1, c1 = float(p["a1"]), float(p["b1"]), float(p["c1"])
    a2, b2, c2 = float(p["a2"]), float(p["b2"]), float(p["c2"])
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-12:
        return {"kind": "无唯一解（行列式为0，无解或无穷多解）", "det": 0}
    dx, dy = c1 * b2 - c2 * b1, a1 * c2 - a2 * c1
    return {"det": round(det, 6), "x": round(dx / det, 6), "y": round(dy / det, 6), "kind": "唯一解"}


def lt_sequence(p):
    """T08 等差/等比数列：求第 n 项与前 n 项和"""
    kind = p.get("kind", "arithmetic")
    a1, n = float(p["a1"]), int(p["n"])
    if kind == "arithmetic":
        d = float(p["d"])
        an = a1 + (n - 1) * d
        sn = n * (a1 + an) / 2
        return {"kind": "等差数列", "a_n": round(an, 6), "sum_n": round(sn, 6), "formula": f"aₙ=a₁+(n-1)d，Sₙ=n(a₁+aₙ)/2"}
    q = float(p["q"])
    if q == 1:
        an, sn = a1, a1 * n
    else:
        an = a1 * q ** (n - 1)
        sn = a1 * (1 - q ** n) / (1 - q)
    return {"kind": "等比数列", "a_n": round(an, 6), "sum_n": round(sn, 6), "formula": "aₙ=a₁qⁿ⁻¹，Sₙ=a₁(1-qⁿ)/(1-q)"}


_PLANE = {
    "rectangle": ("长方形", lambda a, b: {"area": a * b, "perimeter": 2 * (a + b)}),
    "square": ("正方形", lambda a, b=0: {"area": a * a, "perimeter": 4 * a}),
    "triangle": ("三角形", lambda a, h: {"area": a * h / 2}),
    "parallelogram": ("平行四边形", lambda a, h: {"area": a * h}),
    "trapezoid": ("梯形", lambda a, b, h: {"area": (a + b) * h / 2}),
    "circle": ("圆形", lambda r, b=0: {"area": round(math.pi * r * r, 6), "perimeter": round(2 * math.pi * r, 6)}),
}


def lt_plane_geo(p):
    """T09 平面图形面积/周长"""
    shape = p.get("shape", "rectangle")
    if shape not in _PLANE:
        raise ValueError("未知图形：" + shape)
    nums = [float(x) for x in re.split(r"[,，\s]+", str(p.get("dims", "")).strip()) if str(x).strip()]
    name, fn = _PLANE[shape]
    return {"shape": name, **fn(*nums)}


_SOLID = {
    "cuboid": ("长方体", lambda a, b, h: {"volume": a * b * h, "surface": 2 * (a * b + a * h + b * h)}),
    "cube": ("正方体", lambda a, b=0, h=0: {"volume": a ** 3, "surface": 6 * a * a}),
    "cylinder": ("圆柱", lambda r, h, b=0: {"volume": round(math.pi * r * r * h, 6), "surface": round(2 * math.pi * r * (r + h), 6)}),
    "sphere": ("球体", lambda r, b=0, h=0: {"volume": round(4 / 3 * math.pi * r ** 3, 6), "surface": round(4 * math.pi * r * r, 6)}),
    "cone": ("圆锥", lambda r, h, b=0: {"volume": round(1 / 3 * math.pi * r * r * h, 6)}),
}


def lt_solid_geo(p):
    """T10 立体体积/表面积"""
    shape = p.get("shape", "cuboid")
    if shape not in _SOLID:
        raise ValueError("未知立体：" + shape)
    nums = [float(x) for x in re.split(r"[,，\s]+", str(p.get("dims", "")).strip()) if str(x).strip()]
    name, fn = _SOLID[shape]
    return {"shape": name, **fn(*nums)}


def lt_percent(p):
    """T11 百分数/比例：mode=percent 求部分占比; part 已知百分比求部分; ratio 化简比"""
    mode = p.get("mode", "percent")
    if mode == "ratio":
        a, b = int(p["a"]), int(p["b"])
        g = math.gcd(a, b)
        return {"ratio": f"{a}:{b}", "simplified": f"{a // g}:{b // g}"}
    if mode == "part":
        whole, percent = float(p["whole"]), float(p["percent"])
        return {"part": round(whole * percent / 100, 6)}
    part, whole = float(p["part"]), float(p["whole"])
    if whole == 0:
        raise ValueError("总量不能为 0")
    return {"percent": round(part / whole * 100, 4)}


# 学习单位换算（相邻单位给出进率，统一换算到基准单位）
_UNIT = {
    "length": {"name": "长度", "base": "m", "rates": {"mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1, "km": 1000, "里": 500, "inch": 0.0254, "ft": 0.3048}},
    "mass": {"name": "质量", "base": "g", "rates": {"mg": 0.001, "g": 1, "kg": 1000, "t": 1_000_000, "斤": 500, "lb": 453.592, "oz": 28.3495}},
    "area": {"name": "面积", "base": "m²", "rates": {"cm²": 1e-4, "dm²": 0.01, "m²": 1, "公顷": 10000, "km²": 1e6, "亩": 1e4 / 15}},
    "volume": {"name": "体积/容积", "base": "L", "rates": {"mL": 0.001, "L": 1, "m³": 1000}},
    "time": {"name": "时间", "base": "s", "rates": {"秒": 1, "分": 60, "时": 3600, "天": 86400}},
    "speed": {"name": "速度", "base": "m/s", "rates": {"m/s": 1, "km/h": 1 / 3.6}},
}


def lt_unit_convert(p):
    """T12 学习单位换算"""
    table = _UNIT.get(p.get("table", "length"))
    if not table:
        raise ValueError("未知量纲")
    value = float(p["value"])
    frm, to = p["from"], p["to"]
    base = value * table["rates"][frm]
    return {"result": round(base / table["rates"][to], 8), "in_base": round(base, 6)}


def lt_temp(p):
    """T13 温度换算 C/F/K"""
    value = float(p["value"])
    frm = p.get("from", "c")
    c = {"c": value, "f": (value - 32) * 5 / 9, "k": value - 273.15}[frm]
    return {"C": round(c, 4), "F": round(c * 9 / 5 + 32, 4), "K": round(c + 273.15, 4)}


# ============================================================
# 化学类
# ============================================================
_SUBSCRIPT = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
              "₆": "6", "₇": "7", "₈": "8", "₉": "9",
              "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
              "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}


def normalize_formula(formula: str) -> str:
    """归一化化学式：Unicode 上下标转普通数字，去除状态符号/电荷/空白。"""
    s = str(formula).strip()
    for k, v in _SUBSCRIPT.items():
        s = s.replace(k, v)
    for mark in ("↑", "↓", "(g)", "(s)", "(l)", "(aq)", "（g）", "（s）", "（l）"):
        s = s.replace(mark, "")
    s = re.sub(r"[\s]+", "", s)
    s = s.rstrip("+-")  # 去掉简单离子电荷
    return s


def parse_formula(formula):
    """解析化学式为 {元素: 原子数}，支持括号与下标，兼容 Unicode 下标，如 Ca(OH)₂、H2SO4"""
    formula = normalize_formula(formula)
    stack = [{}]
    i, n = 0, len(formula)
    while i < n:
        ch = formula[i]
        if ch == "(":
            stack.append({})
            i += 1
        elif ch == ")":
            i += 1
            num = ""
            while i < n and formula[i].isdigit():
                num += formula[i]
                i += 1
            mul = int(num) if num else 1
            top = stack.pop()
            for el, cnt in top.items():
                stack[-1][el] = stack[-1].get(el, 0) + cnt * mul
        elif ch.isupper():
            el = ch
            i += 1
            if i < n and formula[i].islower():
                el += formula[i]
                i += 1
            num = ""
            while i < n and formula[i].isdigit():
                num += formula[i]
                i += 1
            cnt = int(num) if num else 1
            stack[-1][el] = stack[-1].get(el, 0) + cnt
        else:
            i += 1
    return stack[0]


def lt_molar_mass(p):
    """T14 摩尔质量：输入化学式如 H2SO4 / Ca(OH)2"""
    formula = str(p.get("formula", "")).replace(" ", "")
    if not formula:
        raise ValueError("请输入化学式")
    atoms = parse_formula(formula)
    detail, total = [], 0.0
    for el, cnt in atoms.items():
        m = ELEMENT_MASS.get(el)
        if m is None:
            raise ValueError(f"未知元素 {el}")
        subtotal = m * cnt
        total += subtotal
        detail.append({"element": el, "count": cnt, "atomic_mass": m, "subtotal": round(subtotal, 3)})
    return {"formula": formula, "atoms": atoms, "detail": detail, "molar_mass": round(total, 3), "unit": "g/mol"}


def _species_sum(items):
    total = {}
    for it in items:
        f, mul = it["f"], int(it.get("n", 1))
        for el, cnt in parse_formula(f).items():
            total[el] = total.get(el, 0) + cnt * mul
    return total


def lt_balance_check(p):
    """T15 化学方程式配平检查：left/right 为 [{f,n}]，比较两边各元素原子数"""
    import json
    def _load(v):
        if isinstance(v, list):
            return v
        return json.loads(v)
    left, right = _load(p["left"]), _load(p["right"])
    ls, rs = _species_sum(left), _species_sum(right)
    elems = sorted(set(ls) | set(rs))
    rows = [{"element": e, "left": ls.get(e, 0), "right": rs.get(e, 0), "balanced": ls.get(e, 0) == rs.get(e, 0)} for e in elems]
    balanced = all(r["balanced"] for r in rows)
    return {"balanced": balanced, "rows": rows, "message": "配平正确，两边原子守恒" if balanced else "未配平，存在元素原子数不等"}


# ============================================================
# 英语类
# ====================================================
def lt_en_word_freq(p):
    """T16 英语词频统计"""
    text = str(p.get("text", "")).lower()
    words = re.findall(r"[a-z']+", text)
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:20]
    lengths = [len(w) for w in words]
    return {"total_words": len(words), "unique_words": len(freq),
            "avg_length": round(sum(lengths) / len(lengths), 3) if lengths else 0,
            "sentences": max(1, len(re.findall(r"[.!?]+", text))), "top": [{"word": w, "count": c} for w, c in top]}


def lt_en_readability(p):
    """T17 英文阅读难度（Flesch 简易度 + 句均词长，给参考年级）"""
    text = str(p.get("text", ""))
    words = re.findall(r"[a-zA-Z']+", text)
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    syll = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in words)
    if not words:
        raise ValueError("请输入英文文本")
    asl = len(words) / sentences
    phw = syll / len(words) * 100
    flesch = 206.835 - 1.015 * asl - 84.6 * (syll / len(words))
    grade = 0.39 * asl + 11.8 * (syll / len(words)) - 15.59
    level = "很容易(小学)" if flesch >= 80 else "较容易(初中)" if flesch >= 60 else "中等(高中)" if flesch >= 50 else "较难(高中以上)"
    return {"words": len(words), "sentences": sentences, "avg_sentence_words": round(asl, 2),
            "flesch": round(flesch, 2), "grade_index": round(grade, 2), "level": level}


def lt_en_inflect(p):
    """T18 规则英语词形变化：复数/过去式/ing/比较级（规则词，附规则说明）"""
    w = str(p.get("word", "")).strip().lower()
    if not w:
        raise ValueError("请输入单词")
    vowels = "aeiou"

    def plural(word):
        if word.endswith(("s", "x", "z", "ch", "sh")):
            return word + "es", "以 s/x/z/ch/sh 结尾加 es"
        if word.endswith("y") and word[-2] not in vowels:
            return word[:-1] + "ies", "辅音字母+y，改 y 为 i 加 es"
        if word.endswith(("f", "fe")):
            base = word[:-1] if word.endswith("f") else word[:-2]
            return base + "ves", "以 f/fe 结尾常改 v 加 es(有特例)"
        return word + "s", "一般情况直接加 s"

    def past(word):
        if word.endswith("e"):
            return word + "d", "以 e 结尾直接加 d"
        if word.endswith("y") and word[-2] not in vowels:
            return word[:-1] + "ied", "辅音+y 改 y 为 i 加 ed"
        if len(word) >= 3 and word[-1] not in vowels and word[-2] in vowels and word[-3] not in vowels:
            return word + word[-1] + "ed", "重读闭音节双写末尾辅音加 ed"
        return word + "ed", "一般直接加 ed"

    def ing(word):
        if word.endswith("ie"):
            return word[:-2] + "ying", "ie 结尾改 y 加 ing"
        if word.endswith("e") and not word.endswith("ee"):
            return word[:-1] + "ing", "去不发音 e 加 ing"
        if len(word) >= 3 and word[-1] not in vowels and word[-2] in vowels and word[-3] not in vowels:
            return word + word[-1] + "ing", "重读闭音节双写加 ing"
        return word + "ing", "一般直接加 ing"

    def compare(word):
        if word.endswith("e"):
            return word + "r", word + "st", "以 e 结尾加 r/st"
        if word.endswith("y") and word[-2] not in vowels:
            return word[:-1] + "ier", word[:-1] + "iest", "辅音+y 改 y 为 i 加 er/est"
        return word + "er", word + "est", "一般加 er/est(长词用 more/most)"

    pl, pl_r = plural(w)
    pa, pa_r = past(w)
    ig, ig_r = ing(w)
    cmp_, sup, cmp_r = compare(w)
    return {"word": w, "plural": {"form": pl, "rule": pl_r}, "past": {"form": pa, "rule": pa_r},
            "ing": {"form": ig, "rule": ig_r}, "comparative": {"form": cmp_, "superlative": sup, "rule": cmp_r},
            "note": "仅适用规则变化，不规则动词/名词需单独记忆"}


def lt_pinyin(p):
    """T19 汉字拼音注音（基于常用字库，未收录字原样标出）"""
    text = str(p.get("text", ""))
    out, unknown = [], []
    for ch in text:
        if "一" <= ch <= "鿿":
            py = cn_data.PINYIN_MAP.get(ch)
            if py:
                out.append(f"{ch}({py})")
            else:
                out.append(ch)
                unknown.append(ch)
        else:
            out.append(ch)
    return {"original": text, "annotated": " ".join(out), "unknown": sorted(set(unknown)),
            "covered": len(text) - len(unknown)}


def lt_composition_count(p):
    """T20 作文字数统计：中文字/中文标点/英文词/段落/总字符"""
    text = str(p.get("text", ""))
    cjk = re.findall(r"[一-鿿]", text)
    cjk_punc = re.findall(r"[，。！？；：、“”‘’（）《》—…·]", text)
    en_words = re.findall(r"[A-Za-z]+", text)
    paragraphs = [x for x in re.split(r"\n\s*\n|[\r\n]+", text) if x.strip()]
    return {"chinese_chars": len(cjk), "chinese_punct": len(cjk_punc), "english_words": len(en_words),
            "paragraphs": len(paragraphs), "total_chars": len(text.replace("\n", "")),
            "writing_count": len(cjk) + len(en_words)}


# ============================================================
# 测评 / 记忆 / 课堂工具
# ============================================================
def lt_score_stats(p):
    """T21 成绩描述统计"""
    scores = [float(x) for x in re.split(r"[,，\s]+", str(p.get("scores", "")).strip()) if str(x).strip()]
    if not scores:
        raise ValueError("请输入成绩")
    n = len(scores)
    mean = sum(scores) / n
    var = sum((x - mean) ** 2 for x in scores) / n
    srt = sorted(scores)
    mid = n // 2
    median = srt[mid] if n % 2 else (srt[mid - 1] + srt[mid]) / 2
    freq = {}
    for x in scores:
        freq[x] = freq.get(x, 0) + 1
    mode = max(freq.items(), key=lambda kv: kv[1])[0]
    pass_line, excellent = float(p.get("pass", 60)), float(p.get("excellent", 90))
    return {"count": n, "mean": round(mean, 2), "median": median, "mode": mode,
            "max": max(scores), "min": min(scores), "range": round(max(scores) - min(scores), 2),
            "variance": round(var, 3), "std": round(math.sqrt(var), 3),
            "pass_rate": round(sum(x >= pass_line for x in scores) / n * 100, 1),
            "excellent_rate": round(sum(x >= excellent for x in scores) / n * 100, 1)}


def lt_rank(p):
    """T22 排名（含并列）：method=competition 同名次跳号 / dense 不跳号"""
    scores = [float(x) for x in re.split(r"[,，\s]+", str(p.get("scores", "")).strip()) if str(x).strip()]
    method = p.get("method", "competition")
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ranks = [0] * len(scores)
    prev, comp_rank, dense_rank = None, 0, 0
    for pos, idx in enumerate(order, start=1):
        if scores[idx] != prev:
            comp_rank, dense_rank = pos, dense_rank + 1
            prev = scores[idx]
        ranks[idx] = comp_rank if method == "competition" else dense_rank
    return {"list": [{"score": scores[i], "rank": ranks[i]} for i in range(len(scores))]}


def lt_gpa(p):
    """T23 百分制↔等第↔4.0 GPA"""
    mode = p.get("mode", "from_score")
    bands = [(90, "A", 4.0), (85, "A-", 3.7), (82, "B+", 3.3), (78, "B", 3.0), (75, "B-", 2.7),
             (72, "C+", 2.3), (68, "C", 2.0), (64, "C-", 1.7), (60, "D", 1.0), (0, "F", 0.0)]
    if mode == "avg_gpa":
        ss = [float(x) for x in re.split(r"[,，\s]+", str(p.get("scores", "")).strip()) if str(x).strip()]
        if not ss:
            raise ValueError("请输入成绩")
        def g(s):
            return next(gp for low, _, gp in bands if s >= low)
        return {"gpa": round(sum(g(s) for s in ss) / len(ss), 3), "count": len(ss)}
    score = float(p["score"])
    for low, letter, gp in bands:
        if score >= low:
            return {"score": score, "grade": letter, "gpa": gp}


_EBBINGHAUS_DAYS = [0, 1, 2, 4, 7, 15, 30]


def lt_ebbinghaus(p):
    """T24 艾宾浩斯复习时间表"""
    start = dt.date.fromisoformat(p.get("start", dt.date.today().isoformat()))
    rows = [{"round": i, "after_days": d, "date": (start + dt.timedelta(days=d)).isoformat(),
             "stage": ["初次学习", "第1次复习", "第2次复习", "第3次复习", "第4次复习", "第5次复习", "第6次复习"][i]}
            for i, d in enumerate(_EBBINGHAUS_DAYS)]
    return {"start": start.isoformat(), "list": rows}


def lt_pomodoro(p):
    """T25 番茄钟/专注时长汇总：sessions 为分钟数列表或 HH:MM"""
    raw = re.split(r"[,，\s]+", str(p.get("sessions", "")).strip())
    minutes = []
    for x in raw:
        if not x:
            continue
        if ":" in x:
            h, m = x.split(":")
            minutes.append(int(h) * 60 + int(m))
        else:
            minutes.append(int(float(x)))
    total = sum(minutes)
    return {"count": len(minutes), "total_minutes": total, "total_hours": round(total / 60, 2),
            "avg_minutes": round(total / len(minutes), 1) if minutes else 0,
            "pomodoros_25": round(total / 25, 1)}


def _names(p):
    return [x.strip() for x in re.split(r"[,，、\n\s]+", str(p.get("names", "")).strip()) if x.strip()]


def lt_roll_call(p):
    """T26 随机点名"""
    names = _names(p)
    if not names:
        raise ValueError("请输入名单")
    k = max(1, min(int(p.get("n", 1)), len(names)))
    unique = str(p.get("unique", "1")) != "0"
    if unique:
        picked = random.sample(names, k)
    else:
        picked = [random.choice(names) for _ in range(k)]
    return {"picked": picked, "total": len(names)}


def lt_group(p):
    """T27 随机分组：by=count 指定组数 / size 指定每组人数"""
    names = _names(p)
    random.shuffle(names)
    by = p.get("by", "count")
    if by == "size":
        size = max(1, int(p.get("size", 4)))
        groups = [names[i:i + size] for i in range(0, len(names), size)]
    else:
        count = max(1, int(p.get("count", 4)))
        groups = [[] for _ in range(count)]
        for i, name in enumerate(names):
            groups[i % count].append(name)
    return {"group_count": len(groups), "groups": [{"no": i + 1, "members": g} for i, g in enumerate(groups)]}


def lt_study_plan(p):
    """T28 学习计划生成：total 总任务量、days 天数、rest_every 每几天休一天"""
    total, days = int(p["total"]), int(p["days"])
    rest_every = int(p.get("rest_every", 0))
    if days <= 0:
        raise ValueError("天数需大于 0")
    base, rem = divmod(total, days)
    start = dt.date.fromisoformat(p.get("start", dt.date.today().isoformat()))
    plan, done = [], 0
    for i in range(days):
        day = start + dt.timedelta(days=i)
        is_rest = rest_every and (i + 1) % rest_every == 0
        task = 0 if is_rest else base + (1 if rem > 0 else 0)
        if not is_rest and rem > 0:
            rem -= 1
        done += task
        plan.append({"day": i + 1, "date": day.isoformat(), "task": task,
                     "rest": is_rest, "cumulative": done})
    return {"total": total, "days": days, "plan": plan, "per_day_avg": round(total / days, 2)}


def lt_flashcard_sched(p):
    """T29 闪卡间隔调度（Leitner 盒子法）：level 当前盒子1-5，rating=again/hard/good/easy"""
    level = max(1, min(int(p.get("level", 1)), 5))
    rating = p.get("rating", "good")
    intervals = {1: 1, 2: 2, 3: 4, 4: 7, 5: 15}
    if rating == "again":
        new_level = 1
    elif rating == "hard":
        new_level = max(1, level)
    elif rating == "easy":
        new_level = min(5, level + 2)
    else:
        new_level = min(5, level + 1)
    today = dt.date.today()
    return {"old_level": level, "rating": rating, "new_level": new_level,
            "next_interval_days": intervals[new_level],
            "next_date": (today + dt.timedelta(days=intervals[new_level])).isoformat()}


def _bool_eval(node, env):
    import ast
    if isinstance(node, ast.Expression):
        return _bool_eval(node.body, env)
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _bool_eval(node.operand, env)
    if isinstance(node, ast.BoolOp):
        vals = [_bool_eval(v, env) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.BinOp):
        l, r = _bool_eval(node.left, env), _bool_eval(node.right, env)
        if isinstance(node.op, ast.BitAnd):
            return l and r
        if isinstance(node.op, ast.BitOr):
            return l or r
        if isinstance(node.op, ast.BitXor):
            return l != r
    raise ValueError("仅支持 and/or/not/异或 与变量 A/B/C")


def lt_truth_table(p):
    """T30 逻辑真值表：expr 用 A/B/C 与 and/or/not（也兼容 & | ^）"""
    expr = str(p.get("expr", "A and B")).replace("∧", "&").replace("∨", "|").replace("¬", "not ").replace("→",">>")
    import ast
    vars_ = sorted(set(re.findall(r"[A-C]", expr))) or ["A", "B"]
    if ">>" in expr:  # 蕴含 A→B 等价 (not A) or B
        left, right = expr.split(">>", 1)
        expr = f"(not ({left.strip()})) or ({right.strip()})"
    tree = ast.parse(expr, mode="eval")
    rows = []
    for mask in range(2 ** len(vars_)):
        env = {v: bool((mask >> (len(vars_) - 1 - i)) & 1) for i, v in enumerate(vars_)}
        rows.append({"inputs": env, "output": _bool_eval(tree, env)})
    true_count = sum(1 for r in rows if r["output"])
    return {"variables": vars_, "expression": expr, "rows": rows,
            "tautology": true_count == len(rows), "contradiction": true_count == 0}


def lt_study_time(p):
    """T31 学习时长：求和多段时长；或 start/end 计算时长"""
    if p.get("start") and p.get("end"):
        fmt = "%H:%M"
        s = dt.datetime.strptime(p["start"], fmt)
        e = dt.datetime.strptime(p["end"], fmt)
        if e < s:
            e += dt.timedelta(days=1)
        mins = int((e - s).total_seconds() // 60)
    else:
        mins = 0
        for x in re.split(r"[,，\s]+", str(p.get("sessions", "")).strip()):
            if not x:
                continue
            h, m = (x.split(":") + ["0"])[:2] if ":" in x else (x, 0)
            mins += int(h) * 60 + int(m)
    return {"total_minutes": mins, "text": f"{mins // 60}小时{mins % 60}分钟", "decimal_hours": round(mins / 60, 2)}


def lt_rmb(p):
    """T32 人民币金额大写"""
    num = round(float(p["number"]), 2)
    if num >= 1e12:
        raise ValueError("金额过大")
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["分", "角", "元", "拾", "佰", "仟", "万", "拾", "佰", "仟", "亿", "拾", "佰", "仟"]
    cents = int(round(num * 100))
    if cents == 0:
        return {"number": num, "upper": "零元整"}
    s, idx = "", 0
    while cents:
        s = digits[cents % 10] + units[idx] + s
        cents //= 10
        idx += 1
    s = s.replace("零拾", "零").replace("零佰", "零").replace("零仟", "零")
    s = re.sub("零+", "零", s)
    if num == int(num):
        s += "整"
    return {"number": num, "upper": s}


def lt_calendar_math(p):
    """T33 闰年判断 / 星期 / 日期间隔"""
    year = int(p.get("year", 2024))
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    out = {"year": year, "is_leap": leap, "feb_days": 29 if leap else 28, "year_days": 366 if leap else 365}
    if p.get("date"):
        d = dt.date.fromisoformat(p["date"])
        out["date"] = d.isoformat()
        out["weekday"] = "周一 周二 周三 周四 周五 周六 周日".split()[d.weekday()]
    if p.get("start") and p.get("end"):
        d1, d2 = dt.date.fromisoformat(p["start"]), dt.date.fromisoformat(p["end"])
        out["days_between"] = abs((d2 - d1).days)
    return out


def lt_clock_drill(p):
    """T34 钟表认读题生成"""
    n = max(1, min(int(p.get("n", 5)), 30))
    items = []
    for _ in range(n):
        h = random.randint(1, 12)
        m = random.randint(0, 11) * 5
        angle_h = (h % 12) * 30 + m * 0.5
        angle_m = m * 6
        items.append({"time": f"{h:02d}:{m:02d}", "hour": h, "minute": m,
                      "hour_hand_deg": round(angle_h, 1), "minute_hand_deg": angle_m,
                      "q": f"时针指向 {h} 附近、分针指向 {m // 5 if m else 12}，是几时几分？"})
    return {"count": len(items), "list": items}


def lt_pattern(p):
    """T35 找规律数列题生成"""
    n = max(1, min(int(p.get("n", 5)), 20))
    kind = p.get("kind", random.choice(["arithmetic", "geometric", "square"]))
    items = []
    for _ in range(n):
        if kind == "arithmetic":
            a1, d = random.randint(1, 9), random.randint(2, 9)
            seq = [a1 + i * d for i in range(5)]
            answer = seq[-1] + d
            shown = seq[:4] + ["?"]
        elif kind == "geometric":
            a1, q = random.randint(1, 4), random.randint(2, 3)
            seq = [a1 * q ** i for i in range(5)]
            answer = seq[-1] * q
            shown = seq[:4] + ["?"]
        else:
            seq = [i * i for i in range(1, 6)]
            answer = 36
            shown = seq[:4] + ["?"]
        items.append({"kind": {"arithmetic": "等差数列", "geometric": "等比数列", "square": "平方数列"}[kind],
                       "sequence": shown, "answer": answer})
    return {"count": len(items), "list": items}


def lt_ipa_table(p):
    """T36 国际音标表（可按类型过滤）"""
    group = p.get("group")
    if group:
        return {"groups": {k: v for k, v in en_data.PHONETICS.items() if group in k}}
    counts = {k: len(v) for k, v in en_data.PHONETICS.items()}
    return {"groups": en_data.PHONETICS, "counts": counts, "total": sum(counts.values())}


def lt_multiplication_table(p):
    """T37 乘法口诀：mode=table 输出口诀表，drill 随机抽查"""
    if p.get("mode", "table") == "drill":
        n = max(1, min(int(p.get("n", 10)), 81))
        items = []
        for _ in range(n):
            a, b = random.randint(1, 9), random.randint(1, 9)
            items.append({"q": f"{a}×{b}=", "a": a * b})
        return {"count": n, "list": items}
    rows = []
    for i in range(1, 10):
        rows.append([f"{j}×{i}={j * i}" for j in range(1, i + 1)])
    return {"rows": rows}


def lt_unit_rate_table(p):
    """T38 单位进率表"""
    tables = {
        "长度": [["千米(km)", "米(m)", 1000], ["米", "分米(dm)", 10], ["分米", "厘米(cm)", 10], ["厘米", "毫米(mm)", 10]],
        "面积": [["平方千米", "公顷", 100], ["公顷", "平方米", 10000], ["平方米", "平方分米", 100], ["平方分米", "平方厘米", 100]],
        "体积容积": [["立方米", "立方分米(升)", 1000], ["升(L)", "毫升(mL)", 1000]],
        "质量": [["吨(t)", "千克(kg)", 1000], ["千克", "克(g)", 1000]],
        "人民币": [["元", "角", 10], ["角", "分", 10], ["元", "分", 100]],
        "时间": [["时", "分", 60], ["分", "秒", 60], ["时", "秒", 3600]],
    }
    return {"tables": tables}


def lt_probability(p):
    """T39 概率模拟：coin 抛硬币 / dice 掷骰子 / roulette 转盘，模拟 n 次并对比理论概率"""
    kind = p.get("kind", "coin")
    n = max(1, min(int(p.get("n", 100)), 100000))
    if kind == "coin":
        outcomes = ["正面", "反面"]
        theory = {k: 0.5 for k in outcomes}
        seq = [random.choice(outcomes) for _ in range(n)]
    elif kind == "dice":
        outcomes = [str(i) for i in range(1, 7)]
        theory = {k: 1 / 6 for k in outcomes}
        seq = [str(random.randint(1, 6)) for _ in range(n)]
    else:
        sectors = max(2, min(int(p.get("sectors", 4)), 12))
        outcomes = [f"区域{i}" for i in range(1, sectors + 1)]
        theory = {k: 1 / sectors for k in outcomes}
        seq = [random.choice(outcomes) for _ in range(n)]
    freq = {k: seq.count(k) for k in outcomes}
    return {"kind": kind, "times": n, "frequency": freq,
            "relative": {k: round(freq[k] / n, 4) for k in outcomes},
            "theory": {k: round(v, 4) for k, v in theory.items()}}


def lt_points_to_flashcard(p):
    """T40 要点转闪卡：按行拆分，支持“问题：答案 / Q? A / 术语-解释”三种切分"""
    text = str(p.get("text", ""))
    cards = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip().lstrip("-•*0123456789.、 ")
        if not line:
            continue
        parts = re.split(r"[：:?？]\s*|——|\s-\s", line, maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            cards.append({"front": parts[0].strip() + ("？" if "?" in line or "？" in line else ""), "back": parts[1].strip()})
        else:
            cards.append({"front": line, "back": ""})
    return {"count": len(cards), "cards": cards}


# ============================================================
# 注册：key -> (分类, 名称, 说明, 处理函数)
# ============================================================
LEARN_TOOL_REGISTRY = {
    "arith-gen": ("数学", "口算题生成器", "按运算类型与范围批量出题含答案", lt_arith_gen),
    "fraction-simplify": ("数学", "分数化简", "约分并化为带分数/小数", lt_fraction_simplify),
    "gcd-lcm": ("数学", "最大公约数与最小公倍数", "多个整数求 GCD/LCM", lt_gcd_lcm),
    "prime": ("数学", "质数与分解质因数", "判断质数并做质因数分解", lt_prime),
    "roman": ("数学", "罗马数字互转", "阿拉伯数字与罗马数字互转", lt_roman),
    "quadratic": ("数学", "一元二次方程求解", "判别式与实根/复根", lt_quadratic),
    "linear2": ("数学", "二元一次方程组", "行列式法求解", lt_linear2),
    "sequence": ("数学", "等差等比数列", "第 n 项与前 n 项和", lt_sequence),
    "plane-geo": ("数学", "平面图形计算", "面积与周长", lt_plane_geo),
    "solid-geo": ("数学", "立体图形计算", "体积与表面积", lt_solid_geo),
    "percent": ("数学", "百分数与比", "占比/求部分/化简比", lt_percent),
    "unit-convert": ("换算", "学习单位换算", "长度/面积/体积/质量/时间/速度", lt_unit_convert),
    "temp": ("换算", "温度换算", "摄氏度/华氏度/开尔文", lt_temp),
    "molar-mass": ("化学", "摩尔质量计算", "由化学式算摩尔质量", lt_molar_mass),
    "balance-check": ("化学", "方程式配平检查", "比较两边原子是否守恒", lt_balance_check),
    "en-word-freq": ("英语", "英语词频统计", "词数/词频/平均词长", lt_en_word_freq),
    "en-readability": ("英语", "英文阅读难度", "Flesch 指数与参考年级", lt_en_readability),
    "en-inflect": ("英语", "英语规则词形变化", "复数/过去式/ing/比较级", lt_en_inflect),
    "pinyin": ("语文", "汉字拼音注音", "给中文逐字标注拼音", lt_pinyin),
    "composition-count": ("语文", "作文字数统计", "中文字/标点/英文词/段落", lt_composition_count),
    "score-stats": ("测评", "成绩描述统计", "均值中位数方差及格率", lt_score_stats),
    "rank": ("测评", "成绩排名(含并列)", "竞赛排名/密集排名", lt_rank),
    "gpa": ("测评", "等第与GPA换算", "百分制转等级与4.0绩点", lt_gpa),
    "ebbinghaus": ("记忆方法", "艾宾浩斯复习表", "生成7轮复习日期", lt_ebbinghaus),
    "pomodoro": ("记忆方法", "专注时长汇总", "番茄钟/学习时长统计", lt_pomodoro),
    "roll-call": ("课堂", "随机点名", "从名单随机抽取", lt_roll_call),
    "group": ("课堂", "随机分组", "按组数或每组人数分组", lt_group),
    "study-plan": ("记忆方法", "学习计划生成", "任务量按天分配含休息日", lt_study_plan),
    "flashcard-sched": ("记忆方法", "闪卡间隔调度", "Leitner 盒子法排期", lt_flashcard_sched),
    "truth-table": ("数学", "逻辑真值表", "命题公式列真值判断重言", lt_truth_table),
    "study-time": ("记忆方法", "学习时长计算", "多段时长求和/区间时长", lt_study_time),
    "rmb": ("数学", "人民币大写", "金额转中文大写", lt_rmb),
    "calendar-math": ("数学", "闰年星期日期", "闰年判断/星期/日期间隔", lt_calendar_math),
    "clock-drill": ("小学数学", "钟表认读练习", "随机生成认钟表题目", lt_clock_drill),
    "pattern": ("数学", "找规律数列题", "等差/等比/平方数列", lt_pattern),
    "ipa-table": ("英语", "国际音标表", "48 个国际音标与口型", lt_ipa_table),
    "multiplication-table": ("小学数学", "乘法口诀表", "九九表与随机抽查", lt_multiplication_table),
    "unit-rate-table": ("小学数学", "单位进率表", "长度面积质量等进率", lt_unit_rate_table),
    "probability": ("数学", "概率模拟实验", "抛硬币/骰子/转盘频率", lt_probability),
    "points-to-flashcard": ("记忆方法", "要点转闪卡", "把要点文本拆成问答卡", lt_points_to_flashcard),
}
