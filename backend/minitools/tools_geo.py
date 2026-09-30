# -*- coding: utf-8 -*-
"""minitools · 地理工具家族（10 个）。

去重：dataintel/geo 做距离/geohash/polygon/bbox/eta/parse；这里做坐标格式转换与
静态查表（邮编/区号/时区/国家码等），不重叠。
"""
import math

from .common import endpoint, ok, opt_num, opt_str, req_num, req_str

# ---------- 内置数据表 ----------

CN_POSTCODE = {
    "100000": "北京", "200000": "上海", "300000": "天津", "400000": "重庆",
    "510000": "广州", "518000": "深圳", "310000": "杭州", "210000": "南京",
    "200120": "上海外滩", "100101": "北京朝阳区", "610000": "成都",
    "430000": "武汉", "410000": "长沙", "350000": "福州", "361000": "厦门",
    "230000": "合肥", "330000": "南昌", "450000": "郑州", "530000": "南宁",
    "730000": "银川", "830000": "乌鲁木齐", "850000": "拉萨", "750000": "西宁",
    "710000": "西安", "730000": "银川", "550000": "贵阳", "650000": "昆明",
    "150000": "哈尔滨", "130000": "长春", "110000": "沈阳", "050000": "石家庄",
    "030000": "太原", "010000": "呼和浩特", "250000": "济南", "271000": "泰安",
}

CN_AREA_CODE = {
    "010": "北京", "021": "上海", "022": "天津", "023": "重庆",
    "020": "广州", "0755": "深圳", "0571": "杭州", "025": "南京",
    "028": "成都", "027": "武汉", "0731": "长沙", "0591": "福州",
    "0592": "厦门", "0551": "合肥", "0791": "南昌", "0371": "郑州",
    "0771": "南宁", "0951": "银川", "0991": "乌鲁木齐", "0891": "拉萨",
    "0971": "西宁", "029": "西安", "0851": "贵阳", "0871": "昆明",
    "0451": "哈尔滨", "0431": "长春", "024": "沈阳", "0311": "石家庄",
    "0351": "太原", "0471": "呼和浩特", "0531": "济南",
}

COUNTRY_ISO = {
    "CN": "中国", "US": "美国", "JP": "日本", "KR": "韩国", "GB": "英国",
    "FR": "法国", "DE": "德国", "IT": "意大利", "ES": "西班牙", "RU": "俄罗斯",
    "CA": "加拿大", "AU": "澳大利亚", "NZ": "新西兰", "SG": "新加坡",
    "TH": "泰国", "MY": "马来西亚", "VN": "越南", "IN": "印度", "BR": "巴西",
    "AR": "阿根廷", "EG": "埃及", "ZA": "南非", "AE": "阿联酋", "HK": "中国香港",
    "TW": "中国台湾", "MO": "中国澳门",
}

COUNTRY_PHONE_CODE = {
    "86": "中国", "1": "美国/加拿大", "81": "日本", "82": "韩国", "44": "英国",
    "33": "法国", "49": "德国", "39": "意大利", "7": "俄罗斯", "65": "新加坡",
    "66": "泰国", "60": "马来西亚", "84": "越南", "91": "印度", "852": "中国香港",
    "853": "中国澳门", "886": "中国台湾", "61": "澳大利亚",
}

CN_PROVINCES = ["北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
                "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
                "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
                "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
                "香港", "澳门"]

CONTINENTS = {
    "亚洲": ["中国", "日本", "韩国", "印度", "新加坡", "泰国", "马来西亚", "越南", "阿联酋"],
    "欧洲": ["英国", "法国", "德国", "意大利", "西班牙", "俄罗斯"],
    "北美洲": ["美国", "加拿大"],
    "南美洲": ["巴西", "阿根廷"],
    "非洲": ["埃及", "南非"],
    "大洋洲": ["澳大利亚", "新西兰"],
}

_COMPASS = ["北", "北东北", "东北", "东北东", "东", "东南东", "东南", "东南南",
            "南", "南西南", "西南", "西南西", "西", "西北西", "西北", "西北北"]


@endpoint()
def dms_convert(request):
    """G01. 坐标格式转换：十进制度 ↔ 度分秒。"""
    mode = opt_str(request, "mode", "dms_to_decimal")
    if mode == "dms_to_decimal":
        deg = req_num(request, "degrees")
        minutes = req_num(request, "minutes")
        seconds = opt_num(request, "seconds", default=0)
        sign = -1 if opt_str(request, "ref", "N") in ("S", "W") else 1
        decimal = sign * (abs(deg) + minutes / 60.0 + seconds / 3600.0)
        return ok({"decimal": round(decimal, 6)})
    decimal = req_num(request, "decimal")
    sign = "-" if decimal < 0 else ""
    ad = abs(decimal)
    deg = int(ad)
    minutes = int((ad - deg) * 60)
    seconds = round(((ad - deg) * 60 - minutes) * 60, 2)
    return ok({"dms": f"{sign}{deg}°{minutes}'{seconds}\""})


@endpoint()
def cn_postcode(request):
    """G02. 中国邮编查表（内置主要城市）。"""
    code = req_str(request, "code").strip()
    city = CN_POSTCODE.get(code)
    return ok({"code": code, "city": city, "found": city is not None,
               "sample": list(CN_POSTCODE.items())[:5]})


@endpoint()
def cn_area_code(request):
    """G03. 中国区号查表。"""
    code = req_str(request, "code").strip().lstrip("0")
    code = "0" + code if code else code
    city = CN_AREA_CODE.get(code)
    return ok({"code": code, "city": city, "found": city is not None})


@endpoint()
def timezone_offset(request):
    """G04. 时区偏移查表（UTC±）。"""
    tz = req_str(request, "tz").strip().upper()
    table = {"UTC": 0, "GMT": 0, "CST": 8, "EST": -5, "PST": -8,
             "JST": 9, "CET": 1, "EET": 2, "AEST": 10, "IST": 5.5, "BST": 1}
    offset = table.get(tz)
    return ok({"tz": tz, "offset_hours": offset, "known": offset is not None})


@endpoint()
def country_iso(request):
    """G05. ISO 3166 国家代码查表。"""
    code = req_str(request, "code").strip().upper()
    name = COUNTRY_ISO.get(code)
    return ok({"iso2": code, "name": name, "found": name is not None})


@endpoint()
def cn_province_list(request):
    """G06. 中国省份/直辖市列表。"""
    return ok({"provinces": CN_PROVINCES, "count": len(CN_PROVINCES)})


@endpoint()
def altitude_pressure(request):
    """G07. 海拔-大气压换算（国际压高公式）。"""
    altitude = req_num(request, "altitude_m")
    p = 101325 * (1 - 2.25577e-5 * altitude) ** 5.2559
    return ok({"altitude_m": altitude,
               "pressure_pa": round(p, 1),
               "pressure_hpa": round(p / 100.0, 1)})


@endpoint()
def compass(request):
    """G08. 罗盘方位：角度 -> 16 方位。"""
    deg = req_num(request, "degree") % 360
    idx = int((deg + 11.25) // 22.5) % 16
    return ok({"degree": round(deg, 1), "direction": _COMPASS[idx]})


@endpoint()
def country_phone_code(request):
    """G09. 国家电话代码查表。"""
    code = req_str(request, "code").strip().lstrip("+")
    name = COUNTRY_PHONE_CODE.get(code)
    return ok({"phone_code": "+" + code, "country": name, "found": name is not None})


@endpoint()
def continent_countries(request):
    """G10. 大洲国家列表。"""
    cont = opt_str(request, "continent", "")
    if cont:
        return ok({"continent": cont, "countries": CONTINENTS.get(cont, [])})
    return ok({"continents": list(CONTINENTS.keys()),
               "detail": CONTINENTS})
