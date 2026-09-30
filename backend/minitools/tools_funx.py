# -*- coding: utf-8 -*-
"""minitools · 趣味扩展家族（8 个）。

去重：fun 已有 dice/coin/lottery/fortune/zodiac/riddle/xiehouyu；date 已有 zodiac；
这里做藏头诗/数字谐音/生日密码/解梦/黄历等。
"""
import random
import time

from .common import endpoint, ok, opt_num, opt_str, req_list, req_str

_HOMOPHONE = {
    "0": "你", "520": "我爱你", "5201314": "我爱你一生一世",
    "1314": "一生一世", "7758": "亲亲我吧", "88": "拜拜",
    "666": "溜溜溜", "999": "长长久久", "555": "呜呜呜",
    "233": "哈哈哈", "456": "是我啦", "9494": "就是就是",
}

_DREAM = {
    "鱼": "年年有余，财运将至", "蛇": "贵人相助，注意人际", "火": "情绪旺盛，防口角",
    "水": "财运流动，宜理财", "飞": "事业上升，梦想将达", "老人": "长辈关怀，注意健康",
    "牙齿": "旧貌换新，宜决断", "迷路": "近期决策需谨慎", "考试": "压力较大，宜放松",
    "狗": "忠诚朋友，有贵人", "房子": "家宅安宁，有喜讯", "掉落牙": "注意家人健康",
}

_MBTI_QUESTIONS = [
    ("周末你更愿意：", ("出门社交见朋友", "E"), ("在家看书追剧", "I")),
    ("做决定时更依赖：", ("逻辑分析", "T"), ("人情感受", "F")),
    ("你的桌面通常：", ("整洁有序", "J"), ("随性自然", "P")),
    ("你更关注：", ("现实细节", "S"), ("未来想象", "N")),
]


@endpoint()
def acrostic(request):
    """FX01. 藏头诗：给定每行首字和主题，生成模板句。"""
    heads = req_list(request, "heads")
    topic = opt_str(request, "topic", "春风")
    lines = [f"{h}{topic}正好景，一心只向高处行。" for h in heads]
    return ok({"poem": "\n".join(lines), "heads": heads})


@endpoint()
def num_homophone(request):
    """FX02. 数字谐音翻译。"""
    num = req_str(request, "number")
    meaning = _HOMOPHONE.get(num)
    return ok({"number": num, "meaning": meaning or "暂无释义"})


@endpoint()
def birthday_numerology(request):
    """FX03. 生日密码：生日各位数相加缩放到 1-9。"""
    date = req_str(request, "date")  # YYYYMMDD
    digits = [int(c) for c in date if c.isdigit()]
    total = sum(digits)
    while total > 9:
        total = sum(int(c) for c in str(total))
    traits = {
        1: "领袖型：独立、有主见", 2: "协调型：温和、善合作",
        3: "创意型：表达力强", 4: "稳健型：踏实可靠",
        5: "自由型：爱冒险", 6: "责任型：顾家有爱",
        7: "智慧型：善思考", 8: "权力型：善理财",
        9: "博爱型：有理想",
    }
    return ok({"number": total, "trait": traits.get(total, "")})


@endpoint()
def wuge(request):
    """FX04. 姓名五格（简化版，按字符数近似笔画）。"""
    surname = req_str(request, "surname")
    given = req_str(request, "given")
    tian = len(surname) + 1
    ren = len(surname) + len(given[0]) if given else len(surname)
    di = len(given) + 1 if given else 1
    return ok({"天格": tian, "人格": ren, "地格": di,
               "note": "简化版：以字符数近似笔画"})


@endpoint()
def dream_dict(request):
    """FX05. 周公解梦（内置关键词表）。"""
    word = req_str(request, "keyword")
    for k, v in _DREAM.items():
        if k in word:
            return ok({"keyword": word, "interpretation": v, "matched": k})
    return ok({"keyword": word, "interpretation": "暂无记载，宜自悟", "matched": None})


@endpoint()
def lucky_number(request):
    """FX06. 幸运数字（按生日确定性生成 1-99）。"""
    date = req_str(request, "date")
    seed = sum(ord(c) for c in date)
    rnd = random.Random(seed)
    return ok({"numbers": sorted(rnd.sample(range(1, 100), 6))})


@endpoint()
def mbti(request):
    """FX07. 简化 MBTI：4 道题快速测试。"""
    answers = req_list(request, "answers")  # 4 个: 0/1
    letters = []
    for i, (_, opt_a, opt_b) in enumerate(_MBTI_QUESTIONS):
        choice = str(answers[i]).strip() if i < len(answers) else "0"
        letters.append(opt_a[1] if choice == "0" else opt_b[1])
    type_ = "".join(letters)
    return ok({"type": type_, "questions": [q[0] for q in _MBTI_QUESTIONS]})


_ALMANAC = ["宜出行 忌动土", "宜会友 忌争执", "宜读书 忌熬夜",
            "宜理财 忌冲动消费", "宜规划 忌拖延", "宜静养 忌操劳"]


@endpoint()
def almanac(request):
    """FX08. 简化黄历（按日序确定性）。"""
    day = int(time.strftime("%j"))
    pick = _ALMANAC[day % len(_ALMANAC)]
    return ok({"day_of_year": day, "advice": pick})
