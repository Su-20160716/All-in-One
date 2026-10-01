# -*- coding: utf-8 -*-
"""minitools · 百科家族（10 个，F723–F732）。

去重：validate 已做身份证/车牌/ISBN/邮编的**校验**；这里做**内容查询与解析**（知识小百科），不重复校验。
数据为内置精选小表（可继续扩充），查不到时明确返回 found=false，不编造。
"""
import datetime as dt

from .common import endpoint, ok, opt_num, opt_str, req_str

# —— 百科小表 ——
TODAY_IN_HISTORY = {
    "01-01": ["1912 年中华民国临时政府成立", "1999 年欧元正式启用"],
    "05-04": ["1919 年五四运动爆发", "1989 年五四运动七十周年"],
    "07-01": ["1921 年中国共产党成立纪念日", "1997 年香港回归祖国"],
    "08-01": ["1927 年南昌起义，中国人民解放军建军"],
    "09-03": ["1945 年中国人民抗日战争胜利纪念日"],
    "10-01": ["1949 年中华人民共和国成立"],
    "12-13": ["1937 年南京大屠杀死难者国家公祭日"],
    "03-12": ["1925 年孙中山逝世", "1979 年首个植树节"],
    "06-05": ["1972 年联合国人类环境会议召开，世界环境日"],
    "04-22": ["1970 年首个世界地球日"],
    "09-10": ["1985 年首个教师节"],
    "12-20": ["1999 年澳门回归祖国"],
}

QUOTES = [
    {"text": "学而不思则罔，思而不学则殆。", "author": "孔子", "tag": "学习"},
    {"text": "纸上得来终觉浅，绝知此事要躬行。", "author": "陆游", "tag": "学习"},
    {"text": "不积跬步，无以至千里。", "author": "荀子", "tag": "坚持"},
    {"text": "锲而不舍，金石可镂。", "author": "荀子", "tag": "坚持"},
    {"text": "天生我材必有用。", "author": "李白", "tag": "自信"},
    {"text": "会当凌绝顶，一览众山小。", "author": "杜甫", "tag": "志向"},
    {"text": "先天下之忧而忧，后天下之乐而乐。", "author": "范仲淹", "tag": "担当"},
    {"text": "为中华之崛起而读书。", "author": "周恩来", "tag": "志向"},
    {"text": "业精于勤，荒于嬉。", "author": "韩愈", "tag": "勤奋"},
    {"text": "路漫漫其修远兮，吾将上下而求索。", "author": "屈原", "tag": "求索"},
    {"text": "千磨万击还坚劲，任尔东西南北风。", "author": "郑燮", "tag": "坚韧"},
    {"text": "问渠那得清如许？为有源头活水来。", "author": "朱熹", "tag": "学习"},
]

PROVERBS = [
    {"text": "一年之计在于春，一日之计在于晨。", "cat": "惜时"},
    {"text": "种瓜得瓜，种豆得豆。", "cat": "因果"},
    {"text": "路遥知马力，日久见人心。", "cat": "识人"},
    {"text": "三个臭皮匠，顶个诸葛亮。", "cat": "合作"},
    {"text": "冰冻三尺，非一日之寒。", "cat": "积累"},
    {"text": "近水楼台先得月。", "cat": "条件"},
    {"text": "尺有所短，寸有所长。", "cat": "辩证"},
    {"text": "不入虎穴，焉得虎子。", "cat": "勇气"},
    {"text": "磨刀不误砍柴工。", "cat": "方法"},
    {"text": "虚心使人进步，骄傲使人落后。", "cat": "态度"},
]

ACRONYMS = {
    "yyds": "永远的神（赞美）", "xswl": "笑死我了", "zqsg": "真情实感",
    "nsdd": "你说得对", "u1s1": "有一说一", "bdjw": "不懂就问",
    "yygq": "阴阳怪气", "emo": "情绪低落", "jio": "脚（方言谐音）",
    "kdl": "磕到了（嗑到了）", "awsl": "啊我死了（极度喜爱）", "bhys": "不好意思",
    "dbq": "对不起", "pyq": "朋友圈", "zbc": "真不错", "gkd": "搞快点",
}

HOLIDAYS = [
    ("元旦", 1, 1), ("春节", None, None), ("清明", 4, 4), ("劳动节", 5, 1),
    ("端午", None, None), ("中秋", None, None), ("国庆节", 10, 1), ("教师节", 9, 10),
    ("儿童节", 6, 1), ("妇女节", 3, 8), ("植树节", 3, 12), ("建军节", 8, 1),
]

DYNASTIES = [
    ("夏", "约前 2070—前 1600"), ("商", "约前 1600—前 1046"), ("西周", "前 1046—前 771"),
    ("东周（春秋战国）", "前 770—前 221"), ("秦", "前 221—前 206"), ("汉（西汉/东汉）", "前 202—220"),
    ("三国", "220—280"), ("晋（西晋/东晋）", "265—420"), ("南北朝", "420—589"),
    ("隋", "581—618"), ("唐", "618—907"), ("五代十国", "907—960"),
    ("宋（北宋/南宋）", "960—1279"), ("元", "1271—1368"), ("明", "1368—1644"),
    ("清", "1636—1912"),
]

AREA_CODES = {
    "北京": ("010", "100000"), "上海": ("021", "200000"), "广州": ("020", "510000"),
    "深圳": ("0755", "518000"), "天津": ("022", "300000"), "重庆": ("023", "400000"),
    "成都": ("028", "610000"), "武汉": ("027", "430000"), "西安": ("029", "710000"),
    "南京": ("025", "210000"), "杭州": ("0571", "310000"), "沈阳": ("024", "110000"),
    "长沙": ("0731", "410000"), "郑州": ("0371", "450000"), "济南": ("0531", "250000"),
    "青岛": ("0532", "266000"), "哈尔滨": ("0451", "150000"), "长春": ("0431", "130000"),
    "福州": ("0591", "350000"), "厦门": ("0592", "361000"), "合肥": ("0551", "230000"),
    "昆明": ("0871", "650000"), "贵阳": ("0851", "550000"), "兰州": ("0931", "730000"),
    "乌鲁木齐": ("0991", "830000"), "拉萨": ("0891", "850000"), "海口": ("0898", "570000"),
}

BIRTHDAYS = {
    "01-01": ["吴阶平（医学家）"], "02-11": ["爱迪生（发明家）"],
    "03-14": ["爱因斯坦（物理学家）"], "04-23": ["莎士比亚（剧作家）"],
    "05-05": ["马克思（思想家）"], "06-13": ["图灵（计算机科学家）"],
    "07-21": ["海明威（作家）"], "08-26": ["居里夫人（物理学家、化学家）"],
    "09-28": ["孔子（思想家、教育家）"], "10-31": ["莫言（作家）"],
    "11-07": ["居里（物理学家）"], "12-10": ["诺贝尔（发明家）"],
}

TERMS = {
    "光合作用": "绿色植物利用光能，把二氧化碳和水合成有机物并释放氧气的过程。",
    "牛顿第一定律": "一切物体在没有受到外力作用时，总保持静止或匀速直线运动状态。",
    "勾股定理": "直角三角形两直角边平方和等于斜边平方：a² + b² = c²。",
    "元素周期律": "元素的性质随原子序数递增呈周期性变化的规律。",
    "边际效用": "每增加一单位消费所带来的额外满足感，通常递减。",
    "通货膨胀": "一般物价水平持续上涨、货币购买力下降的经济现象。",
    "通货膨胀率": "衡量物价水平变动幅度的指标，常用 CPI 同比涨幅表示。",
    "语义化标签": "HTML 中表达内容含义的标签（如 header/article），利于可访问性与 SEO。",
    "时间复杂度": "用大 O 描述算法运行时间随输入规模增长的变化趋势。",
    "摩尔": "物质的量的单位，1 mol 含 6.022×10²³ 个粒子（阿伏加德罗常数）。",
}

PROVINCE_CODES = {
    "11": "北京市", "12": "天津市", "13": "河北省", "14": "山西省", "15": "内蒙古自治区",
    "21": "辽宁省", "22": "吉林省", "23": "黑龙江省", "31": "上海市", "32": "江苏省",
    "33": "浙江省", "34": "安徽省", "35": "福建省", "36": "江西省", "37": "山东省",
    "41": "河南省", "42": "湖北省", "43": "湖南省", "44": "广东省", "45": "广西壮族自治区",
    "46": "海南省", "50": "重庆市", "51": "四川省", "52": "贵州省", "53": "云南省",
    "54": "西藏自治区", "61": "陕西省", "62": "甘肃省", "63": "青海省", "64": "宁夏回族自治区",
    "65": "新疆维吾尔自治区", "71": "台湾省", "81": "香港特别行政区", "82": "澳门特别行政区",
}


@endpoint()
def today_in_history(request):
    """TR01. 历史上的今天：按日期查大事记。"""
    raw = opt_str(request, "date", "").strip()
    if raw:
        try:
            d = dt.date.fromisoformat(raw)
        except ValueError:
            raise ValueError("date 需为 YYYY-MM-DD")
    else:
        d = dt.date.today()
    key = f"{d.month:02d}-{d.day:02d}"
    events = TODAY_IN_HISTORY.get(key, [])
    return ok({"date": d.isoformat(), "month_day": key, "found": bool(events),
               "events": events,
               "note": "内置为精选条目；未收录的日期返回 found=false。"})


@endpoint()
def quote(request):
    """TR02. 名言：按标签随机/检索名言。"""
    tag = opt_str(request, "tag", "").strip()
    kw = opt_str(request, "keyword", "").strip()
    pool = QUOTES
    if tag:
        pool = [q for q in pool if q["tag"] == tag]
    if kw:
        pool = [q for q in pool if kw in q["text"] or kw in q["author"]]
    if not pool:
        return ok({"found": False, "list": [], "tags": sorted({q["tag"] for q in QUOTES})})
    n = int(opt_num(request, "n", default=1))
    n = max(1, min(n, len(pool)))
    return ok({"found": True, "count": len(pool), "list": pool[:n],
               "tags": sorted({q["tag"] for q in QUOTES})})


@endpoint()
def proverb(request):
    """TR03. 谚语：按分类查谚语。"""
    cat = opt_str(request, "cat", "").strip()
    kw = opt_str(request, "keyword", "").strip()
    pool = PROVERBS
    if cat:
        pool = [p for p in pool if p["cat"] == cat]
    if kw:
        pool = [p for p in pool if kw in p["text"]]
    return ok({"count": len(pool), "list": pool,
               "cats": sorted({p["cat"] for p in PROVERBS})})


@endpoint()
def acronym(request):
    """TR04. 网络缩写：查常见网络用语含义。"""
    kw = opt_str(request, "word", "").strip().lower()
    if kw:
        hit = ACRONYMS.get(kw)
        return ok({"word": kw, "found": hit is not None, "meaning": hit})
    return ok({"count": len(ACRONYMS),
               "list": [{"word": k, "meaning": v} for k, v in sorted(ACRONYMS.items())]})


@endpoint()
def holiday_countdown(request):
    """TR05. 节日倒计时：算距离下一个公历固定节日还有几天。"""
    today = dt.date.today()
    rows = []
    for name, m, d in HOLIDAYS:
        if m is None:
            continue
        this_year = dt.date(today.year, m, d)
        nxt = this_year if this_year >= today else dt.date(today.year + 1, m, d)
        rows.append({"name": name, "date": nxt.isoformat(),
                     "days_left": (nxt - today).days})
    rows.sort(key=lambda x: x["days_left"])
    return ok({"today": today.isoformat(), "list": rows,
               "nearest": rows[0] if rows else None,
               "note": "只含公历固定日期节日；春节/端午/中秋等农历节日未纳入。"})


@endpoint()
def dynasty_era(request):
    """TR06. 朝代年号：查中国历史朝代起止年表。"""
    kw = opt_str(request, "name", "").strip()
    pool = DYNASTIES
    if kw:
        pool = [d for d in DYNASTIES if kw in d[0]]
    return ok({"count": len(pool),
               "list": [{"dynasty": d, "period": p} for d, p in pool]})


@endpoint()
def postcode_area(request):
    """TR07. 邮编区号：查城市的长途区号与邮编。"""
    city = opt_str(request, "city", "").strip()
    if city:
        hit = AREA_CODES.get(city)
        if not hit:
            near = [c for c in AREA_CODES if city in c or c in city]
            return ok({"city": city, "found": False, "candidates": near})
        return ok({"city": city, "found": True, "area_code": hit[0], "postcode": hit[1]})
    return ok({"count": len(AREA_CODES),
               "list": [{"city": c, "area_code": v[0], "postcode": v[1]}
                        for c, v in sorted(AREA_CODES.items())]})


@endpoint()
def birthday_celeb(request):
    """TR08. 名人诞辰：按日期查同日诞生的名人。"""
    raw = opt_str(request, "date", "").strip()
    if raw:
        try:
            d = dt.date.fromisoformat(raw)
        except ValueError:
            raise ValueError("date 需为 YYYY-MM-DD")
    else:
        d = dt.date.today()
    key = f"{d.month:02d}-{d.day:02d}"
    people = BIRTHDAYS.get(key, [])
    return ok({"date": d.isoformat(), "month_day": key, "found": bool(people),
               "people": people})


@endpoint()
def term_glossary(request):
    """TR09. 学科术语：按关键词查术语释义。"""
    kw = opt_str(request, "keyword", "").strip()
    if kw:
        hits = [{"term": k, "definition": v} for k, v in TERMS.items() if kw in k or kw in v]
        return ok({"keyword": kw, "count": len(hits), "list": hits})
    return ok({"count": len(TERMS),
               "list": [{"term": k, "definition": v} for k, v in TERMS.items()]})


@endpoint()
def serial_parse(request):
    """TR10. 番号解析：解析行政区划代码 / 股票代码的构成含义（只解析，不校验）。"""
    code = req_str(request, "code").strip().upper()
    digits = "".join(ch for ch in code if ch.isdigit())

    # 6 位行政区划代码
    if len(digits) == 6 and code == digits:
        prov = PROVINCE_CODES.get(digits[:2])
        return ok({
            "code": code, "type": "行政区划代码",
            "province": prov, "province_code": digits[:2],
            "city_code": digits[2:4], "county_code": digits[4:6],
            "note": "前 2 位为省级；市/县级需更完整的代码表，这里只解析到省级。",
        })

    # 股票代码（6 位数字，或带 .SH/.SZ/.BJ 后缀）
    if len(digits) == 6:
        suffix = code[6:].lstrip(".")
        if digits.startswith(("60", "68")):
            market, board = "上海证券交易所", "沪市主板/科创板"
        elif digits.startswith(("00", "30")):
            market, board = "深圳证券交易所", "深市主板/创业板"
        elif digits.startswith(("83", "87", "43", "92")):
            market, board = "北京证券交易所", "北交所/新三板"
        else:
            market, board = "未知", "无法判断"
        if suffix:
            market = {"SH": "上海证券交易所", "SZ": "深圳证券交易所",
                      "BJ": "北京证券交易所"}.get(suffix, market)
        return ok({"code": code, "type": "证券代码", "digits": digits,
                   "market": market, "board": board, "suffix": suffix or None,
                   "note": "按代码前缀判断市场归属，不构成投资建议。"})

    return ok({
        "code": code, "type": "通用编号",
        "length": len(code), "digit_count": len(digits),
        "letter_count": sum(1 for ch in code if ch.isalpha()),
        "segments": [len(seg) for seg in code.split("-")] if "-" in code else [len(code)],
        "note": "未匹配到内置的行政区划/证券代码格式，仅返回结构统计。",
    })
