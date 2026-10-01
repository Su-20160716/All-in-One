# -*- coding: utf-8 -*-
"""minitools · 文字游戏家族（8 个，F707–F714）。

去重：minitools/text 处理英文与通用文本、learning 的汉字字典属学习区；这里做中文「查字/拆字/平仄/字帖」小工具。
数据为内置精简字表（约 80 个常用字），未收录的字会明确提示，不猜测、不编造。
"""
from .common import endpoint, ok, opt_num, opt_str, req_list, req_str

# 常用字表：字 -> (笔画, 部首, 拼音, 声调 1~4；轻声记 0)
CHAR_DB = {
    "人": (2, "人", "rén", 2), "大": (3, "大", "dà", 4), "小": (3, "小", "xiǎo", 3),
    "山": (3, "山", "shān", 1), "水": (4, "水", "shuǐ", 3), "火": (4, "火", "huǒ", 3),
    "日": (4, "日", "rì", 4), "月": (4, "月", "yuè", 4), "木": (4, "木", "mù", 4),
    "土": (3, "土", "tǔ", 3), "天": (4, "大", "tiān", 1), "地": (6, "土", "dì", 4),
    "学": (8, "子", "xué", 2), "习": (3, "丿", "xí", 2), "好": (6, "女", "hǎo", 3),
    "书": (4, "乙", "shū", 1), "读": (10, "讠", "dú", 2), "写": (5, "冖", "xiě", 3),
    "字": (6, "子", "zì", 4), "词": (7, "讠", "cí", 2), "句": (5, "口", "jù", 4),
    "文": (4, "文", "wén", 2), "章": (11, "立", "zhāng", 1), "诗": (8, "讠", "shī", 1),
    "古": (5, "口", "gǔ", 3), "今": (4, "人", "jīn", 1), "中": (4, "丨", "zhōng", 1),
    "国": (8, "囗", "guó", 2), "家": (10, "宀", "jiā", 1), "心": (4, "心", "xīn", 1),
    "手": (4, "手", "shǒu", 3), "目": (5, "目", "mù", 4), "口": (3, "口", "kǒu", 3),
    "耳": (6, "耳", "ěr", 3), "足": (7, "足", "zú", 2), "见": (4, "见", "jiàn", 4),
    "知": (8, "矢", "zhī", 1), "道": (12, "辶", "dào", 4), "理": (11, "王", "lǐ", 3),
    "思": (9, "心", "sī", 1), "想": (13, "心", "xiǎng", 3), "明": (8, "日", "míng", 2),
    "白": (5, "白", "bái", 2), "红": (6, "纟", "hóng", 2), "春": (9, "日", "chūn", 1),
    "秋": (9, "禾", "qiū", 1), "风": (4, "风", "fēng", 1), "雨": (8, "雨", "yǔ", 3),
    "花": (7, "艹", "huā", 1), "草": (9, "艹", "cǎo", 3), "你": (7, "亻", "nǐ", 3),
    "我": (7, "戈", "wǒ", 3), "他": (5, "亻", "tā", 1), "上": (3, "一", "shàng", 4),
    "下": (3, "一", "xià", 4), "左": (5, "工", "zuǒ", 3), "右": (5, "口", "yòu", 4),
    "前": (9, "刂", "qián", 2), "后": (6, "口", "hòu", 4), "多": (6, "夕", "duō", 1),
    "少": (4, "小", "shǎo", 3), "长": (4, "长", "cháng", 2), "短": (12, "矢", "duǎn", 3),
    "高": (10, "高", "gāo", 1), "低": (7, "亻", "dī", 1), "年": (6, "干", "nián", 2),
    "时": (7, "日", "shí", 2), "东": (5, "一", "dōng", 1), "南": (9, "十", "nán", 2),
    "西": (6, "西", "xī", 1), "北": (5, "匕", "běi", 3), "金": (8, "金", "jīn", 1),
    "河": (8, "氵", "hé", 2), "湖": (12, "氵", "hú", 2), "海": (10, "氵", "hǎi", 3),
    "云": (4, "二", "yún", 2), "雪": (11, "雨", "xuě", 3), "雷": (13, "雨", "léi", 2),
    "星": (9, "日", "xīng", 1), "光": (6, "儿", "guāng", 1), "树": (9, "木", "shù", 4),
    "林": (8, "木", "lín", 2), "森": (12, "木", "sēn", 1), "叶": (5, "口", "yè", 4),
    "果": (8, "木", "guǒ", 3), "米": (6, "米", "mǐ", 3), "饭": (7, "饣", "fàn", 4),
}

# 多音字：字 -> [(拼音, 例词…)]
POLY_DB = {
    "长": [("cháng", ["长江", "长短", "长处"]), ("zhǎng", ["长大", "校长", "生长"])],
    "行": [("xíng", ["行走", "行为", "不行"]), ("háng", ["银行", "行业", "一行"])],
    "重": [("zhòng", ["重要", "体重", "重量"]), ("chóng", ["重复", "重逢", "重新"])],
    "好": [("hǎo", ["好人", "好看", "友好"]), ("hào", ["爱好", "好学", "好客"])],
    "少": [("shǎo", ["多少", "很少", "少数"]), ("shào", ["少年", "少爷", "老少"])],
    "乐": [("lè", ["快乐", "乐观", "乐趣"]), ("yuè", ["音乐", "乐器", "乐队"])],
    "数": [("shù", ["数学", "数量", "数字"]), ("shǔ", ["数一数", "数落", "数不清"])],
    "差": [("chà", ["差不多", "差别", "出差"]), ("chā", ["差别", "差异", "误差"])],
    "空": [("kōng", ["空气", "天空", "空闲"]), ("kòng", ["空白", "填空", "空隙"])],
    "为": [("wéi", ["认为", "成为", "作为"]), ("wèi", ["为了", "因为", "为何"])],
    "只": [("zhī", ["一只", "只身"]), ("zhǐ", ["只有", "只是", "只要"])],
    "中": [("zhōng", ["中国", "中间", "中心"]), ("zhòng", ["中奖", "中暑", "看中"])],
}

# 拆字谜：字 -> 谜面
RIDDLE_DB = {
    "人": "一撇一捺，互相支撑",
    "山": "三座山峰，一线相连",
    "日": "一个方框，中间一横，照亮大地",
    "月": "有它天就黑，弯弯挂天上",
    "水": "中间一竖钩，两边各两点，江河湖海都是它",
    "火": "中间一个人，两边各一点，越烧越旺",
    "木": "十上添撇捺，长在土里能成材",
    "林": "两个木，站成排",
    "森": "三个木，叠成塔",
    "明": "日月同辉，天就亮了",
    "好": "女子相伴，人人称赞",
    "休": "一个人靠在树上，歇一歇",
    "看": "手搭凉棚向远望",
    "男": "田里出力的人",
    "尘": "小小的土，就是灰",
}

# 近反义小词典：词 -> {syn: [...], ant: [...]}
WORD_DB = {
    "美丽": {"syn": ["漂亮", "好看", "俊俏"], "ant": ["丑陋", "难看"]},
    "高兴": {"syn": ["快乐", "愉快", "欢喜"], "ant": ["难过", "悲伤", "沮丧"]},
    "勇敢": {"syn": ["英勇", "无畏", "果敢"], "ant": ["怯懦", "胆小", "畏惧"]},
    "诚实": {"syn": ["老实", "真诚", "诚恳"], "ant": ["虚伪", "狡诈", "虚假"]},
    "勤奋": {"syn": ["刻苦", "努力", "勤勉"], "ant": ["懒惰", "懈怠", "懒散"]},
    "安静": {"syn": ["宁静", "寂静", "平静"], "ant": ["喧闹", "嘈杂", "吵闹"]},
    "宽广": {"syn": ["宽阔", "辽阔", "广大"], "ant": ["狭窄", "狭小", "逼仄"]},
    "明亮": {"syn": ["光亮", "敞亮", "通明"], "ant": ["昏暗", "阴暗", "漆黑"]},
    "珍贵": {"syn": ["宝贵", "名贵", "珍稀"], "ant": ["廉价", "低贱", "寻常"]},
    "团结": {"syn": ["齐心", "和睦", "协力"], "ant": ["分裂", "内讧", "涣散"]},
    "迅速": {"syn": ["快速", "飞快", "敏捷"], "ant": ["缓慢", "迟缓", "迟钝"]},
    "慷慨": {"syn": ["大方", "豪爽", "大度"], "ant": ["吝啬", "小气", "吝惜"]},
    "温柔": {"syn": ["温和", "柔和", "体贴"], "ant": ["粗暴", "凶悍", "严厉"]},
    "节约": {"syn": ["节省", "俭省", "节俭"], "ant": ["浪费", "挥霍", "奢侈"]},
    "热闹": {"syn": ["喧腾", "繁华", "喧闹"], "ant": ["冷清", "萧条", "寂静"]},
    "坚定": {"syn": ["坚决", "坚毅", "果断"], "ant": ["动摇", "犹豫", "彷徨"]},
    "谦虚": {"syn": ["谦逊", "虚心", "谦和"], "ant": ["骄傲", "自大", "傲慢"]},
    "熟悉": {"syn": ["熟识", "了解", "熟知"], "ant": ["陌生", "生疏", "生僻"]},
    "清澈": {"syn": ["清亮", "明净", "澄澈"], "ant": ["浑浊", "污浊", "混浊"]},
    "富饶": {"syn": ["富庶", "丰饶", "丰裕"], "ant": ["贫瘠", "贫穷", "荒芜"]},
}


@endpoint()
def stroke(request):
    """WP01. 笔画查表：给汉字返回笔画数与部首。"""
    chars = req_list(request, "chars", max_len=200)
    rows, miss = [], []
    for c in chars:
        c = str(c).strip()
        if not c:
            continue
        info = CHAR_DB.get(c)
        if info:
            rows.append({"char": c, "strokes": info[0], "radical": info[1], "pinyin": info[2]})
        else:
            miss.append(c)
    return ok({"found": len(rows), "list": rows, "missing": miss,
               "note": "内置字表约 80 个常用字；未收录的字见 missing，不猜测笔画。"})


@endpoint()
def radical(request):
    """WP02. 部首检字：按部首列出字表中同部首的字。"""
    target = req_str(request, "radical").strip()
    hits = [{"char": c, "strokes": v[0], "pinyin": v[2]}
            for c, v in CHAR_DB.items() if v[1] == target]
    hits.sort(key=lambda x: x["strokes"])
    radicals = sorted({v[1] for v in CHAR_DB.values()})
    return ok({"radical": target, "count": len(hits), "list": hits,
               "available_radicals": radicals})


@endpoint()
def pinyin_full(request):
    """WP03. 带调全拼：把中文转成带声调的拼音串。"""
    text = req_str(request, "text")
    out, miss = [], []
    for ch in text:
        if ch.isspace():
            out.append(" ")
            continue
        info = CHAR_DB.get(ch)
        if info:
            out.append(info[2])
        else:
            miss.append(ch)
            out.append(ch)
    return ok({"text": text, "pinyin": "".join(out),
               "annotated": [{"char": ch, "pinyin": CHAR_DB.get(ch, ("", "", "", 0))[2] or None}
                             for ch in text if not ch.isspace()],
               "missing": miss})


@endpoint()
def polyphone(request):
    """WP04. 多音字组词：返回该字的各种读音与例词。"""
    char = req_str(request, "char").strip()
    if len(char) != 1:
        raise ValueError("请只传一个汉字")
    rows = POLY_DB.get(char)
    if not rows:
        single = CHAR_DB.get(char)
        return ok({"char": char, "polyphonic": False,
                   "readings": [{"pinyin": single[2], "words": []}] if single else [],
                   "note": "该字未收录多音读法（或不是多音字）。"})
    return ok({"char": char, "polyphonic": True,
               "readings": [{"pinyin": p, "words": w} for p, w in rows]})


@endpoint()
def antonym(request):
    """WP05. 近反义查表：给词语返回近义词与反义词。"""
    word = req_str(request, "word").strip()
    hit = WORD_DB.get(word)
    if not hit:
        return ok({"word": word, "found": False, "synonyms": [], "antonyms": [],
                   "note": f"词表未收录「{word}」；已收录 {len(WORD_DB)} 个常用词。"})
    return ok({"word": word, "found": True,
               "synonyms": hit["syn"], "antonyms": hit["ant"]})


@endpoint()
def char_riddle(request):
    """WP06. 拆字谜：给谜面猜字，或给字查谜面。"""
    riddle = opt_str(request, "riddle", "").strip()
    char = opt_str(request, "char", "").strip()
    if riddle:
        hit = [c for c, r in RIDDLE_DB.items() if riddle in r]
        return ok({"riddle": riddle, "candidates": hit, "found": bool(hit)})
    if char:
        r = RIDDLE_DB.get(char)
        return ok({"char": char, "riddle": r, "found": r is not None})
    raise ValueError("请提供 riddle（谜面）或 char（字）之一")


@endpoint()
def couplet_tone(request):
    """WP07. 对联平仄：按字表声调给出平仄格式与对仗检查。"""
    line = req_str(request, "line").strip()
    if not line:
        raise ValueError("line 不能为空")
    pattern, unknown = [], []
    for ch in line:
        info = CHAR_DB.get(ch)
        if not info:
            pattern.append("?")
            unknown.append(ch)
        else:
            pattern.append("平" if info[3] in (1, 2) else "仄")
    other = opt_str(request, "other", "").strip()
    out = {"line": line, "pattern": "".join(pattern), "unknown": unknown,
           "rule": "一、二声为平，三、四声为仄；上联末字宜仄，下联末字宜平。"}
    if other:
        op = []
        for ch in other:
            info = CHAR_DB.get(ch)
            op.append("平" if info and info[3] in (1, 2) else ("仄" if info else "?"))
        opposite = all((a != b) for a, b in zip(pattern, op) if a != "?" and b != "?")
        out.update({"other": other, "other_pattern": "".join(op),
                    "length_match": len(pattern) == len(op),
                    "tone_opposite": opposite,
                    "ok": opposite and len(pattern) == len(op)})
    return ok(out)


@endpoint()
def copybook(request):
    """WP08. 字帖生成：把汉字排成田字格/米字格练字格（返回文本网格）。"""
    chars = [str(c).strip() for c in req_list(request, "chars", max_len=200) if str(c).strip()]
    if not chars:
        raise ValueError("chars 不能为空")
    per_row = int(opt_num(request, "per_row", default=8))
    per_row = max(1, min(per_row, 20))
    style = (opt_str(request, "style", "tian") or "tian").lower()
    if style not in ("tian", "mi", "blank"):
        raise ValueError("style 可选 tian（田字格）/ mi（米字格）/ blank（空白格）")
    cross = {"tian": "┼", "mi": "╳", "blank": "　"}[style]
    lines = []
    for i in range(0, len(chars), per_row):
        chunk = chars[i:i + per_row]
        lines.append("┌" + "┬".join("─" * 3 for _ in chunk) + "┐")
        lines.append("│" + "│".join(f" {c} " for c in chunk) + "│")
        lines.append("│" + "│".join(f" {cross} " for _ in chunk) + "│")
        lines.append("│" + "│".join("   " for _ in chunk) + "│")
        lines.append("└" + "┴".join("─" * 3 for _ in chunk) + "┘")
    return ok({"count": len(chars), "per_row": per_row, "style": style,
               "grid": "\n".join(lines),
               "note": "每个格子第 1 行为范字，第 2 行为格线标记，其余留白供临写。"})
