# -*- coding: utf-8 -*-
"""minitools · 趣味家族（18 个，编号 193-210）。"""
import random
import secrets

from .common import endpoint, ok, opt_num, opt_str, req_list, req_str


@endpoint()
def dice(request):
    """193. 掷骰子。sides: 面数；count: 个数。"""
    sides = int(opt_num(request, "sides", 6, minimum=2, maximum=1000, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    rolls = [random.randint(1, sides) for _ in range(count)]
    return ok({"rolls": rolls, "total": sum(rolls)})


@endpoint()
def coin_flip(request):
    """194. 抛硬币。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=10000, integer=True))
    results = [random.choice(["正", "反"]) for _ in range(count)]
    return ok({"results": results, "heads": results.count("正"), "tails": results.count("反")})


@endpoint()
def lottery(request):
    """195. 随机抽奖。"""
    items = req_list(request, "items")
    count = int(opt_num(request, "count", 1, minimum=1, maximum=len(items), integer=True))
    return ok({"winners": random.sample(items, count)})


@endpoint()
def team_split(request):
    """196. 团队随机分组。"""
    members = req_list(request, "members")
    group_count = int(opt_num(request, "group_count", 2, minimum=2, maximum=len(members), integer=True))
    shuffled = list(members)
    random.shuffle(shuffled)
    groups = [[] for _ in range(group_count)]
    for i, m in enumerate(shuffled):
        groups[i % group_count].append(m)
    return ok({"groups": groups})


_FORTUNES = [
    ("大吉", "红色", "今天宜大胆行动，会有意外收获。"),
    ("中吉", "黄色", "平稳向好，保持节奏即可。"),
    ("小吉", "绿色", "小有收获，适合整理内务。"),
    ("吉", "蓝色", "诸事顺遂，适合沟通合作。"),
    ("末吉", "紫色", "耐心等待，转机在后半段。"),
]


@endpoint()
def fortune_today(request):
    """197. 今日运势。"""
    zodiac = opt_str(request, "zodiac", "")
    f = random.choice(_FORTUNES)
    return ok({"fortune": f[0], "lucky": f[1], "advice": f[2]})


_ZODIAC_MATCH = {
    ("鼠", "牛"): 90, ("鼠", "龙"): 85, ("鼠", "猴"): 85,
    ("牛", "鼠"): 90, ("牛", "蛇"): 85, ("牛", "鸡"): 85,
    ("虎", "马"): 85, ("虎", "狗"): 85,
    ("兔", "羊"): 85, ("兔", "猪"): 85, ("兔", "狗"): 85,
    ("龙", "鼠"): 85, ("龙", "猴"): 90, ("龙", "鸡"): 80,
    ("蛇", "牛"): 85, ("蛇", "鸡"): 85,
    ("马", "虎"): 85, ("马", "狗"): 85, ("马", "羊"): 80,
    ("羊", "兔"): 85, ("羊", "马"): 80, ("羊", "猪"): 85,
    ("猴", "鼠"): 85, ("猴", "龙"): 90,
    ("鸡", "牛"): 85, ("鸡", "蛇"): 85, ("鸡", "龙"): 80,
    ("狗", "虎"): 85, ("狗", "兔"): 85, ("狗", "马"): 85,
    ("猪", "兔"): 85, ("猪", "羊"): 85,
}


@endpoint()
def zodiac_match(request):
    """198. 生肖配对。"""
    a = req_str(request, "zodiac_a")
    b = req_str(request, "zodiac_b")
    score = _ZODIAC_MATCH.get((a, b), _ZODIAC_MATCH.get((b, a), 60))
    desc = "天作之合" if score >= 85 else ("相处融洽" if score >= 70 else "需要磨合")
    return ok({"match_score": score, "description": desc})


_BRAIN_TEASERS = [
    {"q": "什么东西越洗越脏？", "a": "水"},
    {"q": "什么门永远关不上？", "a": "球门"},
    {"q": "小明从不念书却得了模范生，为什么？", "a": "他是聋哑学生"},
    {"q": "什么车子寸步难行？", "a": "风车"},
    {"q": "什么花一年四季都开？", "a": "塑料花"},
    {"q": "铁放在屋外会生锈，那金子呢？", "a": "会被拿走"},
    {"q": "什么时候有人敲门你不会说请进？", "a": "上厕所的时候"},
    {"q": "什么布切不断？", "a": "瀑布"},
    {"q": "孔雀什么时候会东南飞？", "a": "五里一徘徊（乐府）"},
    {"q": "小明的妈妈有三个儿子，大儿子叫大毛，二儿子叫二毛，三儿子叫什么？", "a": "小明"},
]


@endpoint()
def brain_teaser(request):
    """199. 脑筋急转弯。"""
    count = int(opt_num(request, "count", 3, minimum=1, maximum=10, integer=True))
    return ok({"items": random.sample(_BRAIN_TEASERS, min(count, len(_BRAIN_TEASERS)))})


_TONGUE_TWISTERS = [
    "四是四，十是十，十四是十四，四十是四十。",
    "红凤凰，粉凤凰，红粉凤凰花凤凰。",
    "吃葡萄不吐葡萄皮，不吃葡萄倒吐葡萄皮。",
    "扁担长，板凳宽，扁担想绑在板凳上。",
    "黑化肥发灰，灰化肥发黑。",
    "刘奶奶找牛奶奶买牛奶，牛奶奶给刘奶奶拿牛奶。",
    "七巷一个漆匠，西巷一个锡匠。",
    "老龙恼怒闹老农，老农恼怒闹老龙。",
]


@endpoint()
def tongue_twister(request):
    """200. 绕口令。"""
    count = int(opt_num(request, "count", 3, minimum=1, maximum=8, integer=True))
    return ok({"items": random.sample(_TONGUE_TWISTERS, min(count, len(_TONGUE_TWISTERS)))})


_XIEHOUYU = [
    {"q": "外甥打灯笼", "a": "照旧（舅）"},
    {"q": "孔夫子搬家", "a": "净是输（书）"},
    {"q": "小葱拌豆腐", "a": "一清（青）二白"},
    {"q": "茶壶里煮饺子", "a": "有嘴倒（道）不出"},
    {"q": "黄鼠狼给鸡拜年", "a": "没安好心"},
    {"q": "十五个吊桶打水", "a": "七上八下"},
    {"q": "芝麻开花", "a": "节节高"},
    {"q": "老虎屁股", "a": "摸不得"},
    {"q": "王婆卖瓜", "a": "自卖自夸"},
    {"q": "八仙过海", "a": "各显神通"},
]


@endpoint()
def xiehouyu(request):
    """201. 歇后语。"""
    count = int(opt_num(request, "count", 3, minimum=1, maximum=10, integer=True))
    return ok({"items": random.sample(_XIEHOUYU, min(count, len(_XIEHOUYU)))})


_RIDDLES = [
    {"q": "千条线，万条线，落到水里看不见。（打一自然现象）", "a": "雨"},
    {"q": "身穿绿衣裳，肚里水汪汪，生的儿子多，个个黑脸膛。（打一水果）", "a": "西瓜"},
    {"q": "有头没有颈，身上冷冰冰，有翅不能飞，无脚也能行。（打一动物）", "a": "鱼"},
    {"q": "一个黑孩，从不开口，要是开口，掉出舌头。（打一食品）", "a": "瓜子"},
    {"q": "屋子方方，有门没窗，屋外热烘，屋里冰霜。（打一家电）", "a": "冰箱"},
    {"q": "弟兄七八个，围着柱子坐，只要一分开，衣服就扯破。（打一蔬菜）", "a": "蒜"},
    {"q": "身穿大皮袄，野草吃个饱，过了严冬天，献出一身毛。（打一动物）", "a": "绵羊"},
    {"q": "头戴红帽子，身披五彩衣，从来不唱戏，喜欢吊嗓子。（打一动物）", "a": "公鸡"},
]


@endpoint()
def riddle(request):
    """202. 谜语。"""
    count = int(opt_num(request, "count", 3, minimum=1, maximum=8, integer=True))
    return ok({"items": random.sample(_RIDDLES, min(count, len(_RIDDLES)))})


@endpoint()
def emoji_text(request):
    """203. 表情包文字生成。style: heart/star/sparkle。"""
    text = req_str(request, "text")
    style = opt_str(request, "style", "heart")
    wrappers = {"heart": ("💖", "💖"), "star": ("⭐", "⭐"), "sparkle": ("✨", "✨"),
                "boom": ("💥", "💥"), "none": ("", "")}
    if style not in wrappers:
        raise ValueError("style 必须是 heart/star/sparkle/boom/none")
    a, b = wrappers[style]
    return ok({"result": f"{a} {text} {b}"})


_FANCY = {
    "bold": "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳",
    "sans": "𝖺𝖻𝖼𝖽𝖾𝖿𝗀𝗁𝗂𝗃𝗄𝗅𝗆𝗇𝗈𝗉𝗊𝗋𝗌𝗍𝗎𝗏𝗐𝗑𝗒𝗓",
    "script": "𝒶𝒷𝒸𝒹ℯ𝒻𝑔𝒽𝒾𝒿𝓀𝓁𝓂𝓃ℴ𝓅𝓆𝓇𝓈𝓉𝓊𝓋𝔀𝔁𝔂𝓏",
    "mono": "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣",
}


@endpoint()
def fancy_text(request):
    """204. 花字生成。style: bold/sans/script/mono。"""
    text = req_str(request, "text")
    style = opt_str(request, "style", "bold")
    if style not in _FANCY:
        raise ValueError("style 必须是 bold/sans/script/mono")
    base = "abcdefghijklmnopqrstuvwxyz"
    table = str.maketrans(base, _FANCY[style])
    table.update(str.maketrans(base.upper(), _FANCY[style].upper()))
    return ok({"result": text.translate(table)})


@endpoint()
def vertical_text(request):
    """205. 文字竖排。"""
    text = req_str(request, "text")
    return ok({"result": "\n".join(text)})


@endpoint()
def ascii_banner(request):
    """206. ASCII banner（简化块字体）。"""
    text = req_str(request, "text")
    # 简化：用大字块
    lines = []
    for ch in text[:20]:
        lines.append(f" {ch} ")
    return ok({"ascii": " ".join(lines)})


@endpoint()
def ascii_box(request):
    """207. ASCII 框。style: single/double/round。"""
    text = req_str(request, "text")
    style = opt_str(request, "style", "single")
    boxes = {"single": ("+", "-", "|"), "double": ("=", "=", "║"), "round": ("·", "-", "¦")}
    if style not in boxes:
        raise ValueError("style 必须是 single/double/round")
    corner, h, v = boxes[style]
    w = len(text) + 2
    top = corner + h * w + corner
    mid = v + " " + text + " " + v
    return ok({"ascii": f"{top}\n{mid}\n{top}"})


@endpoint()
def rock_paper_scissors(request):
    """208. 石头剪刀布。"""
    player = req_str(request, "player_choice")
    if player not in ("石头", "剪刀", "布"):
        raise ValueError("player_choice 必须是 石头/剪刀/布")
    computer = random.choice(["石头", "剪刀", "布"])
    beats = {"石头": "剪刀", "剪刀": "布", "布": "石头"}
    if player == computer:
        result = "平局"
    elif beats[player] == computer:
        result = "你赢了"
    else:
        result = "你输了"
    return ok({"result": result, "computer": computer, "winner": result})


_EIGHT_BALL = [
    "肯定是", "毫无疑问", "我看行", "大概率", "先等等",
    "不太确定", "估计不行", "别想了", "不可能", "问我也没用",
]


@endpoint()
def magic_8_ball(request):
    """209. 魔法8球。"""
    req_str(request, "question")
    return ok({"answer": random.choice(_EIGHT_BALL)})


_NAME_PUNS = [
    "你的名字自带 Buff，听着就很有故事。",
    "这名字读三遍会发现神奇的节奏感。",
    "名字很有辨识度，适合上热搜。",
    "这个名字让人想多看一眼名片。",
    "名字里藏着一幅画。",
    "这名字读起来像一句诗。",
    "名字很有画面感，像某个电影主角。",
    "这名字听着就让人想认识一下。",
]


@endpoint()
def name_pun(request):
    """210. 姓名谐音梗。"""
    name = req_str(request, "name")
    return ok({"puns": [f"「{name}」" + p for p in random.sample(_NAME_PUNS, 3)]})
