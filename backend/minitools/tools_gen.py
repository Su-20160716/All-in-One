# -*- coding: utf-8 -*-
"""minitools · 生成器家族（25 个，编号 124-148）。"""
import hashlib
import hmac
import html
import random
import secrets
import string
import time
import uuid as _uuid

from .common import endpoint, ok, opt_bool, opt_num, opt_str, req_num, req_str


_LAST_NAMES = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "林", "罗", "郑"]
_MALE_NAMES = ["伟", "强", "磊", "军", "洋", "勇", "杰", "涛", "明", "超", "刚", "平", "辉", "鹏", "华"]
_FEMALE_NAMES = ["芳", "娜", "敏", "静", "丽", "艳", "娟", "英", "红", "燕", "玲", "霞", "萍", "雪", "婷"]
_EN_FIRST_M = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles"]
_EN_FIRST_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
_EN_LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
_STREETS = ["长安街", "中山路", "人民路", "解放大道", "建设街", "和平路", "建国路", "文化路", "五四路", "滨江大道"]
_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆"]
_L_COMPANIES = ["华", "中", "大", "天", "金", "新", "博", "创", "智", "云"]
_M_COMPANIES = ["瑞", "泰", "恒", "昌", "盛", "通", "达", "安", "和", "润"]
_T_COMPANIES = ["科技", "实业", "集团", "网络", "电子", "贸易", "咨询", "文化", "能源", "制造"]
_LOREM = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua".split()


@endpoint()
def uuid_gen(request):
    """124. UUID 生成。version: 1/4/5；count: 个数。"""
    version = int(opt_num(request, "version", 4, minimum=1, maximum=5, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    namespace = _uuid.NAMESPACE_DNS
    name = opt_str(request, "name", "minitools")
    out = []
    for _ in range(count):
        if version == 1:
            out.append(str(_uuid.uuid1()))
        elif version == 3:
            out.append(str(_uuid.uuid3(namespace, name)))
        elif version == 5:
            out.append(str(_uuid.uuid5(namespace, name)))
        else:
            out.append(str(_uuid.uuid4()))
    return ok({"uuids": out})


@endpoint()
def shortid(request):
    """125. 短 ID 生成。"""
    length = int(opt_num(request, "length", 8, minimum=4, maximum=64, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    alphabet = string.ascii_letters + string.digits
    return ok({"ids": ["".join(secrets.choice(alphabet) for _ in range(length)) for _ in range(count)]})


@endpoint()
def nanoid(request):
    """126. NanoID 生成。"""
    length = int(opt_num(request, "length", 21, minimum=4, maximum=128, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-"
    return ok({"ids": ["".join(secrets.choice(alphabet) for _ in range(length)) for _ in range(count)]})


@endpoint()
def password(request):
    """127. 随机密码（可配置复杂度）。"""
    length = int(opt_num(request, "length", 16, minimum=4, maximum=128, integer=True))
    upper = opt_bool(request, "upper", True)
    lower = opt_bool(request, "lower", True)
    digit = opt_bool(request, "digit", True)
    symbol = opt_bool(request, "symbol", False)
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    pools = []
    if upper:
        pools.append(string.ascii_uppercase)
    if lower:
        pools.append(string.ascii_lowercase)
    if digit:
        pools.append(string.digits)
    if symbol:
        pools.append("!@#$%^&*()_+-=[]{}|;:,.<>?")
    if not pools:
        pools.append(string.ascii_letters)
    all_chars = "".join(pools)
    out = []
    for _ in range(count):
        chars = [secrets.choice(p) for p in pools]
        chars += [secrets.choice(all_chars) for _ in range(length - len(chars))]
        secrets.SystemRandom().shuffle(chars)
        out.append("".join(chars))
    return ok({"passwords": out})


@endpoint()
def chinese_name(request):
    """128. 随机中文姓名。gender: male/female。"""
    gender = opt_str(request, "gender", "male")
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    pool = _MALE_NAMES if gender == "male" else _FEMALE_NAMES
    return ok({"names": [random.choice(_LAST_NAMES) + "".join(random.choice(pool) for _ in range(random.randint(1, 2))) for _ in range(count)]})


@endpoint()
def english_name(request):
    """129. 随机英文姓名。"""
    gender = opt_str(request, "gender", "male")
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    pool = _EN_FIRST_M if gender == "male" else _EN_FIRST_F
    return ok({"names": [random.choice(pool) + " " + random.choice(_EN_LAST) for _ in range(count)]})


@endpoint()
def phone(request):
    """130. 随机手机号。prefix: 号段前缀。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    prefix = opt_str(request, "prefix", "138")
    if not prefix.isdigit() or len(prefix) not in (3,):
        raise ValueError("prefix 应为 3 位号段")
    return ok({"phones": [prefix + "".join(secrets.choice(string.digits) for _ in range(8)) for _ in range(count)]})


@endpoint()
def email(request):
    """131. 随机邮箱。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    domain = opt_str(request, "domain", "example.com")
    return ok({"emails": [f"user{secrets.randbelow(10**8):08d}@{domain}" for _ in range(count)]})


@endpoint()
def address(request):
    """132. 随机地址。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    return ok({"addresses": [f"{random.choice(_CITIES)}市{random.choice(_STREETS)}{random.randint(1,200)}号" for _ in range(count)]})


@endpoint()
def company(request):
    """133. 随机公司名。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    return ok({"companies": [random.choice(_L_COMPANIES) + random.choice(_M_COMPANIES) + random.choice(_T_COMPANIES) + "有限公司" for _ in range(count)]})


@endpoint()
def lorem(request):
    """134. Lorem Ipsum。type: word/sentence/paragraph；count: 数量。"""
    typ = opt_str(request, "type", "paragraph")
    count = int(opt_num(request, "count", 3, minimum=1, maximum=50, integer=True))
    if typ == "word":
        return ok({"text": " ".join(random.choice(_LOREM) for _ in range(count))})
    if typ == "sentence":
        out = []
        for _ in range(count):
            words = [random.choice(_LOREM) for _ in range(random.randint(5, 12))]
            out.append(words[0].capitalize() + " " + " ".join(words[1:]) + ".")
        return ok({"text": " ".join(out)})
    if typ == "paragraph":
        paras = []
        for _ in range(count):
            sents = []
            for _ in range(random.randint(3, 6)):
                words = [random.choice(_LOREM) for _ in range(random.randint(8, 15))]
                sents.append(words[0].capitalize() + " " + " ".join(words[1:]) + ".")
            paras.append(" ".join(sents))
        return ok({"text": "\n\n".join(paras)})
    raise ValueError("type 必须是 word/sentence/paragraph")


@endpoint()
def random_color(request):
    """135. 随机颜色。format: hex/rgb。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    fmt = opt_str(request, "format", "hex")
    out = []
    for _ in range(count):
        r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        if fmt == "rgb":
            out.append(f"rgb({r},{g},{b})")
        else:
            out.append(f"#{r:02x}{g:02x}{b:02x}")
    return ok({"colors": out})


@endpoint()
def random_date(request):
    """136. 随机日期。"""
    from datetime import date, timedelta
    start_s = opt_str(request, "start", "2020-01-01")
    end_s = opt_str(request, "end", "2030-12-31")
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(end_s)
    if start > end:
        raise ValueError("start 不能晚于 end")
    delta = (end - start).days
    return ok({"dates": [(start + timedelta(days=random.randint(0, delta))).isoformat() for _ in range(count)]})


def _qr_svg(text, size=200):
    """生成 QR 风格的 SVG（视觉形似，非真实可扫描）。"""
    # 基于文本 hash 生成确定性 25x25 矩阵
    h = hashlib.md5(text.encode("utf-8")).digest()
    n = 25
    cells = []
    for i in range(n * n):
        b = h[i % len(h)]
        cells.append((b >> (i % 8)) & 1)
    unit = size / n
    rects = []
    for y in range(n):
        for x in range(n):
            if cells[y * n + x]:
                rects.append(f'<rect x="{x*unit:.1f}" y="{y*unit:.1f}" width="{unit+0.5:.1f}" height="{unit+0.5:.1f}" fill="#000"/>')
    # 三个定位角
    def finder(cx, cy):
        u = unit
        return (f'<rect x="{cx*u:.1f}" y="{cy*u:.1f}" width="{7*u:.1f}" height="{7*u:.1f}" fill="#000"/>'
                f'<rect x="{(cx+1)*u:.1f}" y="{(cy+1)*u:.1f}" width="{5*u:.1f}" height="{5*u:.1f}" fill="#fff"/>'
                f'<rect x="{(cx+2)*u:.1f}" y="{(cy+2)*u:.1f}" width="{3*u:.1f}" height="{3*u:.1f}" fill="#000"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
           f'<rect width="{size}" height="{size}" fill="#fff"/>' + "".join(rects)
           + finder(0, 0) + finder(n - 7, 0) + finder(0, n - 7) + "</svg>")
    return svg


@endpoint()
def qrcode(request):
    """137. 二维码生成（SVG）。"""
    text = req_str(request, "text")
    size = int(opt_num(request, "size", 200, minimum=50, maximum=1000, integer=True))
    return ok({"svg_data": _qr_svg(text, size)})


def _barcode_svg(text, size=200):
    """Code128 风格条形码 SVG（视觉形似）。"""
    # 把文本映射为宽窄交替条
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    bars = []
    pos = 0
    bw = 2
    for i, ch in enumerate(h):
        w = bw * (1 + int(ch, 16) % 3)
        if i % 2 == 0:
            bars.append(f'<rect x="{pos}" y="10" width="{w}" height="80" fill="#000"/>')
        pos += w
    width = max(pos, size)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="100" viewBox="0 0 {width} 100">'
           + "".join(bars) + f'<text x="{width/2}" y="100" text-anchor="middle" font-size="10">{html.escape(text)}</text></svg>')
    return svg


@endpoint()
def barcode(request):
    """138. 条形码（Code128/Code39 风格 SVG）。"""
    text = req_str(request, "text")
    return ok({"svg_data": _barcode_svg(text)})


@endpoint()
def avatar(request):
    """139. 头像生成（首字母 SVG）。"""
    text = req_str(request, "text")
    size = int(opt_num(request, "size", 100, minimum=32, maximum=512, integer=True))
    letter = text.strip()[:1].upper() or "?"
    palette = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#34495e"]
    color = palette[hash(text) % len(palette)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
           f'<rect width="{size}" height="{size}" rx="{size/6}" fill="{color}"/>'
           f'<text x="50%" y="50%" dy="0.35em" text-anchor="middle" font-family="sans-serif" '
           f'font-size="{size*0.5}" fill="#fff">{letter}</text></svg>')
    return ok({"svg_data": svg})


@endpoint()
def placeholder_image(request):
    """140. 占位图片 URL 生成。"""
    width = int(req_num(request, "width", minimum=1, maximum=2000, integer=True))
    height = int(req_num(request, "height", minimum=1, maximum=2000, integer=True))
    text = opt_str(request, "text", f"{width} x {height}")
    bg = opt_str(request, "bg", "#cccccc")
    fg = opt_str(request, "fg", "#999999")
    return ok({"url": f"https://placehold.co/{width}x{height}{bg}/{fg}?text={text.replace(' ', '+')}"})


@endpoint()
def hash_gen(request):
    """141. 哈希值（MD5/SHA 系列）。"""
    text = req_str(request, "text")
    algo = opt_str(request, "algorithm", "md5").lower()
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}
    if algo not in algos:
        raise ValueError("algorithm 必须是 md5/sha1/sha256/sha512")
    return ok({"hash": algos[algo](text.encode("utf-8")).hexdigest()})


@endpoint()
def hmac_gen(request):
    """142. HMAC 生成。"""
    text = req_str(request, "text")
    key = req_str(request, "key")
    algo = opt_str(request, "algorithm", "sha256").lower()
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}
    if algo not in algos:
        raise ValueError("algorithm 必须是 md5/sha1/sha256/sha512")
    return ok({"hash": hmac.new(key.encode("utf-8"), text.encode("utf-8"), algos[algo]).hexdigest()})


@endpoint()
def crc32(request):
    """143. CRC32 校验。"""
    import zlib
    text = req_str(request, "text")
    return ok({"crc32": format(zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF, "08x")})


@endpoint()
def mac_address(request):
    """144. 随机 MAC 地址。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    sep = opt_str(request, "separator", ":")
    return ok({"addresses": [sep.join(f"{secrets.randbelow(256):02x}" for _ in range(6)) for _ in range(count)]})


@endpoint()
def ip_address(request):
    """145. 随机 IP 地址。version: 4/6。"""
    version = int(opt_num(request, "version", 4, minimum=4, maximum=6, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    if version == 4:
        return ok({"ips": [".".join(str(secrets.randbelow(256)) for _ in range(4)) for _ in range(count)]})
    out = []
    for _ in range(count):
        parts = [f"{secrets.randbelow(65536):04x}" for _ in range(8)]
        out.append(":".join(parts))
    return ok({"ips": out})


_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


@endpoint()
def user_agent(request):
    """146. 随机 User-Agent。"""
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    return ok({"uas": [random.choice(_UA_POOL) for _ in range(count)]})


@endpoint()
def snowflake_id(request):
    """147. 雪花 ID 生成（模拟）。"""
    worker_id = int(opt_num(request, "worker_id", 1, minimum=0, maximum=1023, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=1000, integer=True))
    epoch = 1577836800000  # 2020-01-01
    out = []
    seq = 0
    for _ in range(count):
        ts = int(time.time() * 1000) - epoch
        sid = (ts << 22) | (worker_id << 12) | (seq & 0xFFF)
        seq += 1
        out.append(sid)
    return ok({"ids": out})


@endpoint()
def invite_code(request):
    """148. 邀请码生成。"""
    length = int(opt_num(request, "length", 8, minimum=4, maximum=32, integer=True))
    count = int(opt_num(request, "count", 1, minimum=1, maximum=100, integer=True))
    charset = opt_str(request, "charset", string.ascii_uppercase + string.digits)
    if not charset:
        raise ValueError("charset 不能为空")
    return ok({"codes": ["".join(secrets.choice(charset) for _ in range(length)) for _ in range(count)]})
