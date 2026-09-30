# -*- coding: utf-8 -*-
"""devtools 静态数据表（色名 / Emoji / HTTP / MIME / gitmoji / 黄历签文 / 历史上的今天 等）。"""

# ---------- CSS 命名色（用于“最近色名”匹配） ----------
CSS_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "lime": (0, 255, 0),
    "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "silver": (192, 192, 192), "gray": (128, 128, 128), "maroon": (128, 0, 0), "olive": (128, 128, 0),
    "green": (0, 128, 0), "purple": (128, 0, 128), "teal": (0, 128, 128), "navy": (0, 0, 128),
    "orange": (255, 165, 0), "pink": (255, 192, 203), "gold": (255, 215, 0), "brown": (165, 42, 42),
    "tomato": (255, 99, 71), "salmon": (250, 128, 114), "coral": (255, 127, 80), "crimson": (220, 20, 60),
    "indigo": (75, 0, 130), "violet": (238, 130, 238), "skyblue": (135, 206, 235), "steelblue": (70, 130, 180),
    "royalblue": (65, 105, 225), "midnightblue": (25, 25, 112), "darkgreen": (0, 100, 0),
    "lightgreen": (144, 238, 144), "khaki": (240, 230, 140), "beige": (245, 245, 220),
    "ivory": (255, 255, 240), "lavender": (230, 230, 250), "orchid": (218, 112, 214),
    "plum": (221, 160, 221), "tan": (210, 180, 140), "wheat": (245, 222, 179), "snow": (255, 250, 250),
    "honeydew": (240, 255, 240), "mintcream": (245, 255, 250), "azure": (240, 255, 255),
    "chocolate": (210, 105, 30), "peru": (205, 133, 63), "goldenrod": (218, 165, 32),
    "hotpink": (255, 105, 180), "deepskyblue": (0, 191, 255), "aquamarine": (127, 255, 212),
    "lawngreen": (124, 252, 0), "yellowgreen": (154, 205, 50), "springgreen": (0, 255, 127),
    "turquoise": (64, 224, 208), "firebrick": (178, 34, 34), "sienna": (160, 82, 45),
}

# ---------- Emoji 词典（keyword 搜索） ----------
EMOJI = [
    ("😀", ["grin", "笑", "开心", "笑脸"]), ("😂", ["joy", "笑哭", "哈哈"]), ("🤣", ["rofl", "笑死"]),
    ("😊", ["blush", "微笑", "害羞"]), ("😍", ["heart-eyes", "花痴"]), ("🤔", ["think", "思考", "想想"]),
    ("😎", ["cool", "墨镜", "装"]), ("😭", ["sob", "哭", "大哭"]), ("😡", ["angry", "愤怒", "生气"]),
    ("🥳", ["party", "庆祝", "派对"]), ("😴", ["sleep", "睡", "困"]), ("🤯", ["mind-blown", "爆炸头"]),
    ("🙃", ["upside", "倒脸", "无语"]), ("😇", ["angel", "天使"]), ("🤡", ["clown", "小丑"]),
    ("👻", ["ghost", "鬼"]), ("💀", ["skull", "骷髅", "寄"]), ("👽", ["alien", "外星人"]),
    ("🤖", ["robot", "机器人"]), ("🎃", ["pumpkin", "南瓜"]), ("🐱", ["cat", "猫", "猫咪"]),
    ("🐶", ["dog", "狗", "汪"]), ("🐭", ["mouse", "老鼠"]), ("🦊", ["fox", "狐狸"]),
    ("🐻", ["bear", "熊"]), ("🐼", ["panda", "熊猫"]), ("🐸", ["frog", "青蛙"]),
    ("🐔", ["chicken", "鸡"]), ("🦆", ["duck", "鸭", "鸭鸭"]), ("🦄", ["unicorn", "独角兽"]),
    ("🍕", ["pizza", "披萨"]), ("🍔", ["burger", "汉堡"]), ("🍜", ["noodle", "面", "拉面"]),
    ("🍚", ["rice", "米饭"]), ("🍣", ["sushi", "寿司"]), ("🎂", ["cake", "蛋糕", "生日"]),
    ("🍎", ["apple", "苹果"]), ("🍉", ["melon", "西瓜"]), ("🍺", ["beer", "啤酒"]),
    ("☕", ["coffee", "咖啡"]), ("🍵", ["tea", "茶"]), ("🧋", ["boba", "奶茶"]),
    ("⚽", ["soccer", "足球"]), ("🏀", ["basketball", "篮球"]), ("🎮", ["game", "游戏", "手柄"]),
    ("🎲", ["dice", "骰子"]), ("🎯", ["dart", "靶心", "目标"]), ("🎉", ["tada", "庆祝", "撒花"]),
    ("🚀", ["rocket", "火箭", "起飞"]), ("💡", ["bulb", "灯泡", "点子"]), ("🔥", ["fire", "火", "热"]),
    ("⭐", ["star", "星", "星星"]), ("🌈", ["rainbow", "彩虹"]), ("☀", ["sun", "太阳", "晴"]),
    ("🌙", ["moon", "月亮"]), ("☁", ["cloud", "云"]), ("⚡", ["zap", "闪电", "电力"]),
    ("❄", ["snow", "雪"]), ("🍀", ["clover", "幸运草"]), ("🌸", ["flower", "花", "樱花"]),
    ("❤", ["heart", "红心", "爱"]), ("💔", ["broken-heart", "心碎"]), ("💯", ["hundred", "满分", "一百"]),
    ("✅", ["check", "对勾", "完成"]), ("❌", ["x", "叉", "错误"]), ("⚠", ["warn", "警告"]),
    ("❓", ["question", "问号", "问题"]), ("❗", ["exclamation", "感叹", "注意"]),
    ("👀", ["eyes", "眼睛", "看看"]), ("👋", ["wave", "挥手", "你好"]), ("👍", ["thumbs-up", "赞"]),
    ("👎", ["thumbs-down", "踩"]), ("🙏", ["pray", "拜", "谢谢"]), ("🤝", ["handshake", "握手", "合作"]),
    ("💪", ["muscle", "加油", "肌肉"]), ("🧠", ["brain", "脑子"]), ("📌", ["pin", "图钉", "置顶"]),
    ("📎", ["clip", "回形针", "附件"]), ("📝", ["memo", "笔记", "记录"]), ("📚", ["books", "书", "学习"]),
    ("💻", ["laptop", "电脑", "代码"]), ("🖥", ["desktop", "台式机"]), ("⌨", ["keyboard", "键盘"]),
    ("🐛", ["bug", "虫子", "缺陷"]), ("🔧", ["wrench", "扳手", "修"]), ("🔨", ["hammer", "锤子"]),
    ("🔍", ["search", "搜索", "放大镜"]), ("🔒", ["lock", "锁", "安全"]), ("🔑", ["key", "钥匙"]),
    ("⏰", ["alarm", "闹钟", "提醒"]), ("📅", ["calendar", "日历", "日期"]), ("💰", ["money", "钱", "moneybag"]),
    ("💸", ["money-fly", "花钱"]), ("🎁", ["gift", "礼物"]), ("🏆", ["trophy", "奖杯", "冠军"]),
    ("🥇", ["gold-medal", "金牌"]), ("🚗", ["car", "汽车"]), ("✈", ["plane", "飞机"]),
    ("🏠", ["house", "房子", "家"]), ("🌍", ["earth", "地球", "世界"]), ("📞", ["phone", "电话"]),
    ("📧", ["mail", "邮件"]), ("💬", ["chat", "对话", "消息"]), ("🔊", ["sound", "音量", "响"]),
    ("🆗", ["ok", "OK"]), ("🆒", ["cool-box", "酷"]), ("🆕", ["new", "新"]),
    ("🔝", ["top", "顶"]), ("🌀", ["cyclone", "旋风"]), ("🕐", ["clock", "时钟"]),
]

# ---------- HTTP 状态码参考 ----------
HTTP_STATUS = {
    100: "Continue 继续，客户端应继续请求", 101: "Switching Protocols 切换协议",
    200: "OK 成功", 201: "Created 已创建", 202: "Accepted 已接受（异步处理）",
    204: "No Content 成功无返回体", 206: "Partial Content 断点续传/范围请求",
    301: "Moved Permanently 永久重定向", 302: "Found 临时重定向", 304: "Not Modified 缓存命中",
    307: "Temporary Redirect 临时重定向（保持方法）", 308: "Permanent Redirect 永久重定向（保持方法）",
    400: "Bad Request 请求参数错误", 401: "Unauthorized 未认证（登录）", 403: "Forbidden 无权限",
    404: "Not Found 资源不存在", 405: "Method Not Allowed 方法不允许", 409: "Conflict 冲突",
    410: "Gone 已删除", 413: "Payload Too Large 请求体过大", 415: "Unsupported Media Type 类型不支持",
    416: "Range Not Satisfiable 范围越界", 422: "Unprocessable Entity 校验失败",
    429: "Too Many Requests 限流", 451: "Unavailable For Legal Reasons 法律原因不可用",
    500: "Internal Server Error 服务端错误", 501: "Not Implemented 未实现",
    502: "Bad Gateway 网关错误", 503: "Service Unavailable 服务不可用",
    504: "Gateway Timeout 网关超时", 507: "Insufficient Storage 存储不足",
}

# ---------- 常用 HTTP 头参考 ----------
HTTP_HEADERS = {
    "authorization": "认证凭据，如 Bearer <token>",
    "content-type": "请求/响应体类型，如 application/json",
    "accept": "客户端可接受的响应类型",
    "user-agent": "客户端标识（浏览器/UA）",
    "cookie": "携带的 Cookie", "set-cookie": "服务端种 Cookie（HttpOnly/Secure/SameSite）",
    "cache-control": "缓存策略（no-cache/max-age/no-store）",
    "etag": "资源指纹，配合 If-None-Match 做 304",
    "if-none-match": "条件请求：ETag 未变则 304",
    "last-modified": "资源最后修改时间", "if-modified-since": "条件请求：按时间 304",
    "content-length": "响应体字节数", "content-encoding": "压缩编码（gzip/br）",
    "content-range": "范围响应的实际字节区间（206）", "accept-ranges": "是否支持 Range（bytes）",
    "location": "重定向目标 / 201 新资源地址",
    "access-control-allow-origin": "CORS 允许的来源", "access-control-allow-headers": "CORS 允许的请求头",
    "strict-transport-security": "HSTS 强制 HTTPS",
    "x-frame-options": "点击劫持防护（DENY/SAMEORIGIN）",
    "x-requested-with": "标记 Ajax 请求（传统约定）", "referer": "来源页",
    "retry-after": "限流/503 后建议重试秒数", "www-authenticate": "401 时的认证方式",
    "forwarded": "代理链路信息（X-Forwarded-For 的标准化版）",
}

# ---------- MIME 表（常见扩展名） ----------
MIME_TABLE = {
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv", "html": "text/html", "htm": "text/html",
    "css": "text/css", "js": "text/javascript", "mjs": "text/javascript", "json": "application/json",
    "xml": "application/xml", "pdf": "application/pdf", "zip": "application/zip",
    "gz": "application/gzip", "tar": "application/x-tar", "7z": "application/x-7z-compressed",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml", "ico": "image/x-icon", "bmp": "image/bmp",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac", "m4a": "audio/mp4",
    "mp4": "video/mp4", "webm": "video/webm", "avi": "video/x-msvideo", "mov": "video/quicktime", "mkv": "video/x-matroska",
    "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "woff": "font/woff", "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf",
    "wasm": "application/wasm", "yaml": "application/yaml", "yml": "application/yaml", "toml": "application/toml",
}

# ---------- 文件魔数签名 ----------
MAGIC_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "png", "PNG 图片"),
    (b"\xff\xd8\xff", "jpg", "JPEG 图片"),
    (b"GIF87a", "gif", "GIF 图片 (87a)"), (b"GIF89a", "gif", "GIF 图片 (89a)"),
    (b"PK\x03\x04", "zip-family", "ZIP 家族（zip/docx/xlsx/jar/apk…）"),
    (b"%PDF", "pdf", "PDF 文档"),
    (b"\x1f\x8b", "gzip", "GZIP 压缩"),
    (b"7z\xbc\xaf\x27\x1c", "7z", "7-Zip 压缩"),
    (b"Rar!\x1a\x07", "rar", "RAR 压缩"),
    (b"\x00\x00\x01\x00", "ico", "ICO 图标"),
    (b"BM", "bmp", "BMP 位图"),
    (b"RIFF", "riff-family", "RIFF 家族（wav/avi/webp）"),
    (b"ID3", "mp3", "MP3（ID3 头）"), (b"\xff\xfb", "mp3", "MP3（MPEG 帧）"),
    (b"OggS", "ogg", "OGG 容器"), (b"fLaC", "flac", "FLAC 音频"),
    (b"\x1a\x45\xdf\xa3", "mkv", "Matroska/WebM 容器"),
    (b"SQLite format 3\x00", "sqlite", "SQLite 数据库"),
    (b"\xca\xfe\xba\xbe", "class", "Java class / mach-o fat"),
    (b"MZ", "exe", "Windows PE（exe/dll）"),
    (b"<!DOCTYPE html", "html", "HTML 文本"), (b"<html", "html", "HTML 文本"),
]

# ---------- gitmoji ----------
GITMOJI = [
    ("✨", ":sparkles:", "新增功能"), ("🐛", ":bug:", "修 bug"), ("📚", ":book:", "文档"),
    ("🔥", ":fire:", "删除代码/文件"), ("🚑", ":ambulance:", "紧急热修"), ("💄", ":lipstick:", "样式/UI"),
    ("🎉", ":tada:", "初始化"), ("✅", ":white_check_mark:", "测试"), ("🔒", ":lock:", "安全修复"),
    ("⚡", ":zap:", "性能优化"), ("♻", ":recycle:", "重构"), ("🔧", ":wrench:", "配置文件"),
    ("🏗", ":building_construction:", "架构调整"), ("🧪", ":test_tube:", "实验性功能"),
    ("🩹", ":adhesive_bandage:", "简单修补（非致命）"), ("⬆", ":arrow_up:", "升依赖"),
    ("⬇", ":arrow_down:", "降依赖"), ("🚀", ":rocket:", "部署相关"), ("🎨", ":art:", "代码结构/格式"),
    ("🔀", ":twisted_rightwards_arrows:", "合并分支"), ("🚚", ":truck:", "移动/改名"),
    ("💡", ":bulb:", "注释/源码说明"), ("🔇", ":mute:", "移除日志"), ("🔊", ":loud_sound:", "加日志"),
    (" 👔", ":necktie:", "业务/管理层改动"), ("🥅", ":goal_net:", "捕获异常"),
]

# ---------- 签文（fortune） ----------
FORTUNES = [
    ("大吉", "你今天写下的代码，将一次通过。连 CI 都会为你鼓掌。"),
    ("大吉", "上游依赖今天不会更新。世界难得的温柔。"),
    ("中吉", "Bug 会来找你，但你比它快一步。"),
    ("中吉", "今天适合重构，不适合重写。手别痒。"),
    ("中吉", "你将发现一个别人埋了很久的坑，并优雅绕过。"),
    ("小吉", "会议会比预计早结束五分钟。这是今天的全部惊喜。"),
    ("小吉", "咖啡因充足时，diff 都是绿色的。"),
    ("小吉", "今天提的需求，明天才会变。抓紧。"),
    ("吉", "稳步推进即可，别开新坑。旧坑填完就是胜利。"),
    ("吉", "你的 PR 将被快速 review。评论只有一行：LGTM。"),
    ("凶", "今天别在生产环境直接改配置。听劝。"),
    ("凶", "周五下午上新，是当代行为艺术。三思。"),
    ("凶", "别相信「就改一行」。它从不只改一行。"),
    ("末吉", "凌晨三点的灵感，早上八点会变成 bug。先睡。"),
]

# ---------- 历史上的今天（月-日 → 事件，精选） ----------
TODAY_HISTORY = {
    "01-01": ["1912 年：中华民国成立", "1995 年：世界贸易组织正式运作"],
    "01-11": ["1922 年：胰岛素首次用于治疗糖尿病"],
    "02-14": ["1876 年：贝尔获得电话专利"],
    "03-12": ["1912 年：童子军创立"],
    "04-23": ["1616 年：塞万提斯与莎士比亚逝世（世界读书日由来）"],
    "05-01": ["1889 年：五一国际劳动节确立"],
    "05-04": ["1919 年：五四运动爆发"],
    "06-01": ["1925 年：国际儿童节设立（1927 定于 6.1）"],
    "07-01": ["1997 年：香港回归祖国"],
    "08-01": ["1927 年：南昌起义（中国人民解放军建军节）"],
    "09-03": ["1945 年：中国人民抗日战争胜利纪念日"],
    "09-10": ["1985 年：中国首个教师节"],
    "10-01": ["1949 年：中华人民共和国成立"],
    "11-11": ["1918 年：第一次世界大战停战"],
    "12-20": ["1999 年：澳门回归祖国"],
    "12-26": ["1893 年：毛泽东诞辰"],
}

# ---------- 中国大区划（模拟数据用，省市级采样） ----------
REGION = {
    "广东省": ["深圳市", "广州市", "珠海市", "东莞市", "佛山市"],
    "北京市": ["朝阳区", "海淀区", "东城区", "西城区"],
    "上海市": ["浦东新区", "徐汇区", "静安区", "杨浦区"],
    "浙江省": ["杭州市", "宁波市", "温州市", "绍兴市"],
    "江苏省": ["南京市", "苏州市", "无锡市", "常州市"],
    "四川省": ["成都市", "绵阳市", "乐山市"],
    "湖北省": ["武汉市", "宜昌市", "襄阳市"],
    "湖南省": ["长沙市", "株洲市", "湘潭市"],
    "山东省": ["济南市", "青岛市", "烟台市"],
    "福建省": ["福州市", "厦门市", "泉州市"],
    "陕西省": ["西安市", "咸阳市", "宝鸡市"],
    "河南省": ["郑州市", "洛阳市", "开封市"],
}

# 身份证 region code 采样（真实行政区划码前 6 位，用于生成可校验样例）
ID_REGION_CODES = {
    "440300": "广东省深圳市", "440100": "广东省广州市", "110100": "北京市市辖区",
    "310100": "上海市市辖区", "330100": "浙江省杭州市", "320500": "江苏省苏州市",
    "510100": "四川省成都市", "420100": "湖北省武汉市", "440600": "广东省佛山市",
    "350200": "福建省厦门市", "610100": "陕西省西安市", "370200": "山东省青岛市",
}

SURNAME = "王李张刘陈杨赵黄周吴徐孙马朱胡郭何林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
GIVEN_M = ["伟", "强", "磊", "军", "洋", "勇", "杰", "涛", "明", "刚", "平", "辉", "健", "俊", "鑫", "晨", "旭", "浩", "子轩", "浩然", "宇轩"]
GIVEN_F = ["芳", "娜", "敏", "静", "丽", "娟", "艳", "霞", "雪", "琳", "婷", "欣怡", "雨桐", "梦琪", "诗涵"]

LOREM_ZH = "在产品与工程之间总有一道看不见的墙而好的工程师会带着产品思维把它拆掉需求从不害怕变化害怕的是变化来时代码还没有准备好分布式系统的魅力在于它教会我们承认失败才是常态把每一次重试都变成一次优雅的舞蹈数据不会说谎但图表可以所以要对坐标轴保持敬畏代码是写给人看的只是顺便能在机器上运行这不是玩笑这是工程的事实好的接口设计像好的笑话不需要解释"

CITY_LATLNG = {  # 经纬度（geo 距离演示）
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737), "深圳": (22.5431, 114.0579),
    "广州": (23.1291, 113.2644), "杭州": (30.2741, 120.1551), "成都": (30.5728, 104.0668),
    "武汉": (30.5928, 114.3055), "西安": (34.3416, 108.9398), "重庆": (29.5630, 106.5516),
    "南京": (32.0603, 118.7969), "厦门": (24.4798, 118.0894), "长沙": (28.2282, 112.9388),
}

# 服装/鞋码对照
APPAREL_SIZE = {
    "男装上装": {"S": "165/84A", "M": "170/88A", "L": "175/92A", "XL": "180/96A", "XXL": "185/100A"},
    "女装上装": {"S": "155/80A", "M": "160/84A", "L": "165/88A", "XL": "170/92A"},
    "男鞋": {"39": "24.5cm", "40": "25.0cm", "41": "25.5cm", "42": "26.0cm", "43": "26.5cm", "44": "27.0cm"},
    "女鞋": {"35": "22.5cm", "36": "23.0cm", "37": "23.5cm", "38": "24.0cm", "39": "24.5cm"},
}

SQL_JOINS = {
    "inner": ("INNER JOIN", "只保留两表都能匹配上的行。就像只聊得来的人互相点赞。",
              "SELECT a.*, b.* FROM a INNER JOIN b ON a.id = b.a_id;"),
    "left": ("LEFT JOIN", "左表全保留，右表匹配不上补 NULL。领导说：一个都不能少。",
             "SELECT a.*, b.* FROM a LEFT JOIN b ON a.id = b.a_id;"),
    "right": ("RIGHT JOIN", "右表全保留，左表匹配不上补 NULL。left 的镜像。", 
              "SELECT a.*, b.* FROM a RIGHT JOIN b ON a.id = b.a_id;"),
    "full": ("FULL OUTER JOIN", "两边都保留，匹配不上互相补 NULL（MySQL 需用 UNION 模拟）。",
             "SELECT a.*, b.* FROM a LEFT JOIN b ON a.id = b.a_id UNION SELECT a.*, b.* FROM a RIGHT JOIN b ON a.id = b.a_id;"),
    "cross": ("CROSS JOIN", "笛卡尔积：m × n 全组合。慎用，行数会爆炸。",
              "SELECT a.*, b.* FROM a CROSS JOIN b;"),
    "self": ("SELF JOIN", "自己 join 自己，常用于层级（员工-经理）。",
             "SELECT e.name, m.name AS manager FROM emp e LEFT JOIN emp m ON e.manager_id = m.id;"),
}

CODE39_TABLE = {
    "0": "101001101101", "1": "110100101011", "2": "101100101011", "3": "110110010101",
    "4": "101001101011", "5": "110100110101", "6": "101100110101", "7": "101001011011",
    "8": "110100101101", "9": "101100101101", "A": "110101001011", "B": "101101001011",
    "C": "110110100101", "D": "101011001011", "E": "110101100101", "F": "101101100101",
    "G": "101010011011", "H": "110101001101", "I": "101101001101", "J": "101011001101",
    "K": "110101010011", "L": "101101010011", "M": "110110101001", "N": "101011010011",
    "O": "110101101001", "P": "101101101001", "Q": "101010110011", "R": "110101011001",
    "S": "101101011001", "T": "101011011001", "U": "110010101011", "V": "100110101011",
    "W": "110011010101", "X": "100101101011", "Y": "110010110101", "Z": "100110110101",
    "-": "100101011011", ".": "110010101101", " ": "100110101101", "$": "100100100101",
    "/": "100100101001", "+": "100101001001", "%": "101001001001", "*": "100101101101",
}

REGEX_TOKENS = [
    (r"^", "行首锚点"), (r"$", "行尾锚点"), (r".", "任意字符（除换行）"),
    (r"\d", "数字 [0-9]"), (r"\D", "非数字"), (r"\w", "单词字符 [A-Za-z0-9_]"),
    (r"\W", "非单词字符"), (r"\s", "空白字符"), (r"\S", "非空白字符"),
    (r"\b", "单词边界"), (r"*", "前一元素重复 0 次或多次（贪婪）"),
    (r"+", "前一元素重复 1 次或多次（贪婪）"), (r"?", "前一元素 0 或 1 次"),
    (r"{m,n}", "重复 m 到 n 次"), (r"[abc]", "字符集合：a、b 或 c"),
    (r"[^abc]", "不在集合中的字符"), (r"(abc)", "捕获组"), (r"(?:abc)", "非捕获组"),
    (r"a|b", "或：匹配 a 或 b"), (r"(?=…)", "正向先行断言"), (r"(?!…)", "负向先行断言"),
    (r"(?<=…)", "正向后行断言"), (r"*?", "+?", "懒惰量词（尽量少匹配）"),
]
