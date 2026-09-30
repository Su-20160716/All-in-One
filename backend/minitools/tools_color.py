# -*- coding: utf-8 -*-
"""minitools · 颜色家族（18 个，编号 106-123）。"""
import colorsys
import random
import re

from .common import endpoint, ok, opt_num, opt_str, req_str


def _parse_color(value):
    """支持 #RGB, #RRGGBB, rgb(r,g,b) -> (r,g,b) 0-255。"""
    v = value.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise ValueError(f"无法解析颜色: {value}")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v)
    if m:
        return tuple(int(x) for x in m.groups())
    raise ValueError(f"无法解析颜色: {value}")


def _to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def _rgb_to_hsl(rgb):
    r, g, b = [c / 255 for c in rgb]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return (h * 360, s * 100, l * 100)


def _hsl_to_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return (r * 255, g * 255, b * 255)


@endpoint()
def convert(request):
    """106. HEX/RGB/HSL 互转。from/to: hex/rgb/hsl。"""
    value = req_str(request, "value")
    frm = opt_str(request, "from", "hex")
    to = opt_str(request, "to", "rgb")
    if frm == "hex":
        rgb = _parse_color(value)
    elif frm == "rgb":
        parts = [int(x) for x in re.findall(r"\d+", value)]
        if len(parts) != 3:
            raise ValueError("rgb 需要 3 个分量")
        rgb = tuple(parts)
    elif frm == "hsl":
        parts = [float(x) for x in re.findall(r"[\d.]+", value)]
        if len(parts) != 3:
            raise ValueError("hsl 需要 3 个分量")
        rgb = _hsl_to_rgb(*parts)
    else:
        raise ValueError("from 必须是 hex/rgb/hsl")
    if to == "hex":
        return ok({"result": _to_hex(rgb)})
    if to == "rgb":
        return ok({"result": f"rgb({int(rgb[0])},{int(rgb[1])},{int(rgb[2])})"})
    if to == "hsl":
        h, s, l = _rgb_to_hsl(rgb)
        return ok({"result": f"hsl({h:.0f},{s:.0f}%,{l:.0f}%)"})
    raise ValueError("to 必须是 hex/rgb/hsl")


@endpoint()
def contrast(request):
    """107. 对比度计算（WCAG）。"""
    a = _parse_color(req_str(request, "color_a"))
    b = _parse_color(req_str(request, "color_b"))

    def _lum(rgb):
        def f(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, bl = [f(c) for c in rgb]
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    l1, l2 = _lum(a), _lum(b)
    ratio = (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
    if ratio >= 7:
        level = "AAA"
    elif ratio >= 4.5:
        level = "AA"
    elif ratio >= 3:
        level = "AA Large"
    else:
        level = "Fail"
    return ok({"ratio": round(ratio, 2), "level": level})


@endpoint()
def mix(request):
    """108. 颜色混合。ratio: color_b 占比 0-1。"""
    a = _parse_color(req_str(request, "color_a"))
    b = _parse_color(req_str(request, "color_b"))
    ratio = opt_num(request, "ratio", 0.5, minimum=0, maximum=1)
    rgb = tuple(a[i] * (1 - ratio) + b[i] * ratio for i in range(3))
    return ok({"result": _to_hex(rgb)})


@endpoint()
def gradient(request):
    """109. 颜色渐变生成。"""
    a = _parse_color(req_str(request, "color_a"))
    b = _parse_color(req_str(request, "color_b"))
    steps = int(opt_num(request, "steps", 5, minimum=2, maximum=50, integer=True))
    out = []
    for i in range(steps):
        t = i / (steps - 1)
        rgb = tuple(a[j] * (1 - t) + b[j] * t for j in range(3))
        out.append(_to_hex(rgb))
    return ok({"colors": out})


@endpoint()
def complementary(request):
    """110. 互补色/类似色/三角色。scheme: complementary/analogous/triadic。"""
    rgb = _parse_color(req_str(request, "color"))
    h, s, l = _rgb_to_hsl(rgb)
    scheme = opt_str(request, "scheme", "complementary")
    if scheme == "complementary":
        hs = [(h + 180) % 360]
    elif scheme == "analogous":
        hs = [(h - 30) % 360, h, (h + 30) % 360]
    elif scheme == "triadic":
        hs = [h, (h + 120) % 360, (h + 240) % 360]
    else:
        raise ValueError("scheme 必须是 complementary/analogous/triadic")
    return ok({"colors": [_to_hex(_hsl_to_rgb(x, s, l)) for x in hs]})


@endpoint()
def lighten(request):
    """111. 颜色变亮。percent: 0-100。"""
    rgb = _parse_color(req_str(request, "color"))
    p = opt_num(request, "percent", 10, minimum=0, maximum=100) / 100
    h, s, l = _rgb_to_hsl(rgb)
    return ok({"result": _to_hex(_hsl_to_rgb(h, s, l + p * (100 - l)))})


@endpoint()
def darken(request):
    """112. 颜色变暗。"""
    rgb = _parse_color(req_str(request, "color"))
    p = opt_num(request, "percent", 10, minimum=0, maximum=100) / 100
    h, s, l = _rgb_to_hsl(rgb)
    return ok({"result": _to_hex(_hsl_to_rgb(h, s, l * (1 - p)))})


@endpoint()
def saturate(request):
    """113. 饱和度调整。"""
    rgb = _parse_color(req_str(request, "color"))
    p = opt_num(request, "percent", 10, minimum=-100, maximum=100) / 100
    h, s, l = _rgb_to_hsl(rgb)
    s = max(0, min(100, s * (1 + p)))
    return ok({"result": _to_hex(_hsl_to_rgb(h, s, l))})


@endpoint()
def color_temp(request):
    """114. 色温转换（K→RGB，简化 Tanner 算法）。"""
    kelvin = opt_num(request, "kelvin", 6500, minimum=1000, maximum=40000)
    temp = kelvin / 100
    if temp <= 66:
        r = 255
        g = 99.47 * math.log(temp) - 161.12 if temp > 0 else 0
        b = 0 if temp <= 19 else 138.52 * math.log(temp - 10) - 305.04
    else:
        r = 329.69 * (temp - 60) ** -0.1332
        g = 288.12 * (temp - 60) ** -0.0755
        b = 255
    import math
    rgb = tuple(max(0, min(255, int(round(c)))) for c in (r, g, b))
    return ok({"rgb": list(rgb), "hex": _to_hex(rgb)})


import math  # noqa: E402


_CSS_COLORS = {
    "red": "#ff0000", "green": "#008000", "blue": "#0000ff", "white": "#ffffff",
    "black": "#000000", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff",
    "gray": "#808080", "orange": "#ffa500", "purple": "#800080", "pink": "#ffc0cb",
}


@endpoint()
def name_lookup(request):
    """115. 颜色名称查找。"""
    rgb = _parse_color(req_str(request, "color"))
    # 简单最近邻
    best = None
    best_d = 1e9
    for name, hexv in _CSS_COLORS.items():
        nrgb = _parse_color(hexv)
        d = sum((rgb[i] - nrgb[i]) ** 2 for i in range(3))
        if d < best_d:
            best_d = d
            best = name
    return ok({"name": best, "nearest": _CSS_COLORS[best]})


@endpoint()
def random_palette(request):
    """116. 随机配色生成。scheme: monochrome/analogous/complementary。"""
    count = int(opt_num(request, "count", 5, minimum=1, maximum=20, integer=True))
    scheme = opt_str(request, "scheme", "analogous")
    base_h = random.uniform(0, 360)
    out = []
    for i in range(count):
        if scheme == "monochrome":
            h, s, l = base_h, random.uniform(40, 80), 20 + i * 60 / count
        elif scheme == "complementary":
            h = (base_h + (i % 2) * 180) % 360
            s, l = 60, 50
        else:
            h = (base_h + i * 30) % 360
            s, l = 60, 50
        out.append(_to_hex(_hsl_to_rgb(h, s, l)))
    return ok({"colors": out})


@endpoint()
def grayscale(request):
    """117. 灰度转换。"""
    r, g, b = _parse_color(req_str(request, "color"))
    gray = int(round(0.299 * r + 0.587 * g + 0.114 * b))
    return ok({"result": _to_hex((gray, gray, gray))})


@endpoint()
def invert(request):
    """118. 颜色反转。"""
    rgb = _parse_color(req_str(request, "color"))
    return ok({"result": _to_hex(tuple(255 - c for c in rgb))})


@endpoint()
def cmyk_convert(request):
    """119. CMYK 转换。direction: rgb2cmyk / cmyk2rgb。"""
    direction = opt_str(request, "direction", "rgb2cmyk")
    if direction == "rgb2cmyk":
        r, g, b = [c / 255 for c in _parse_color(req_str(request, "value"))]
        k = 1 - max(r, g, b)
        if k == 1:
            return ok({"result": "cmyk(0%,0%,0%,100%)"})
        c = (1 - r - k) / (1 - k)
        m = (1 - g - k) / (1 - k)
        y = (1 - b - k) / (1 - k)
        return ok({"result": f"cmyk({c*100:.0f}%,{m*100:.0f}%,{y*100:.0f}%,{k*100:.0f}%)"})
    if direction == "cmyk2rgb":
        parts = [float(x) / 100 for x in re.findall(r"[\d.]+", req_str(request, "value"))]
        if len(parts) != 4:
            raise ValueError("cmyk 需要 4 个分量")
        c, m, y, k = parts
        r = 255 * (1 - c) * (1 - k)
        g = 255 * (1 - m) * (1 - k)
        b = 255 * (1 - y) * (1 - k)
        return ok({"result": _to_hex((r, g, b))})
    raise ValueError("direction 必须是 rgb2cmyk 或 cmyk2rgb")


@endpoint()
def hex_expand(request):
    """120. 十六进制缩写展开。"""
    h = req_str(request, "hex").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError("hex 必须是 3 或 6 位")
    return ok({"expanded": "#" + h})


@endpoint()
def alpha_blend(request):
    """121. 透明度混合。fg: 前景色；bg: 背景色；alpha: 前景透明度。"""
    fg = _parse_color(req_str(request, "fg"))
    bg = _parse_color(req_str(request, "bg"))
    alpha = opt_num(request, "alpha", 0.5, minimum=0, maximum=1)
    rgb = tuple(fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3))
    return ok({"result": _to_hex(rgb)})


@endpoint()
def harmony(request):
    """122. 色彩和谐方案。type: analogous/triadic/tetradic/split。"""
    rgb = _parse_color(req_str(request, "color"))
    h, s, l = _rgb_to_hsl(rgb)
    t = opt_str(request, "type", "analogous")
    shifts = {"analogous": [-30, 0, 30], "triadic": [0, 120, 240],
              "tetradic": [0, 60, 180, 240], "split": [0, 150, 210]}
    if t not in shifts:
        raise ValueError("type 必须是 analogous/triadic/tetradic/split")
    return ok({"colors": [_to_hex(_hsl_to_rgb((h + x) % 360, s, l)) for x in shifts[t]]})


@endpoint()
def wcag_text(request):
    """123. WCAG 文字颜色建议（根据背景选黑/白文字）。"""
    bg = _parse_color(req_str(request, "bg_color"))
    def _lum(rgb):
        def f(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
    lum = _lum(bg)
    white_ratio = (1.05) / (lum + 0.05)
    black_ratio = (lum + 0.05) / 0.05
    if white_ratio > black_ratio:
        return ok({"recommended": "#ffffff", "ratio": round(white_ratio, 2)})
    return ok({"recommended": "#000000", "ratio": round(black_ratio, 2)})
