# -*- coding: utf-8 -*-
"""devtools · 杂项家族接口：net(6) fake(6) fun(7) = 19 个。"""
import hashlib
import ipaddress
import re
import secrets
import time
from datetime import date, datetime
from urllib.parse import urlencode, urlparse

from .common import (as_lines, endpoint, ok, opt_bool, opt_num, opt_str, p,
                     req, req_list, req_num, req_str)
from .data import (CITY_LATLNG, EMOJI, GIVEN_F, GIVEN_M, ID_REGION_CODES,
                   MIME_TABLE, REGION, SURNAME, TODAY_HISTORY)

# =====================================================================
# net 网络（6）
# =====================================================================


@endpoint()
def net_ip_calc(request):
    """IPv4 CIDR 计算：掩码/反掩码/网络号/广播/可用主机范围与数量。"""
    cidr = req_str(request, "cidr").strip()
    net = ipaddress.ip_network(cidr, strict=False)
    if net.version != 4:
        raise ValueError("本接口仅处理 IPv4（v6 请用 ip-classify）")
    # 不要 list(net.hosts())：/8 有 1600 万地址，会直接把进程内存打满。
    # 首末可用地址用整数运算即可。
    if net.prefixlen <= 30:
        usable = net.num_addresses - 2
        first_host = str(net.network_address + 1)
        last_host = str(net.broadcast_address - 1)
    else:
        usable = net.num_addresses
        first_host = str(net.network_address)
        last_host = str(net.broadcast_address)
    return ok({
        "network": str(net.network_address), "netmask": str(net.netmask),
        "wildcard": str(net.hostmask), "broadcast": str(net.broadcast_address),
        "prefix": net.prefixlen, "total_addresses": net.num_addresses,
        "usable_hosts": usable,
        "first_host": first_host,
        "last_host": last_host,
        "is_private": net.is_private,
    })


@endpoint()
def net_ip_classify(request):
    """IP 分类：公网/内网/回环/链路本地/组播 + 类型提示。"""
    raw = req_str(request, "ip").strip()
    ip = ipaddress.ip_address(raw)
    tags = []
    if ip.is_loopback:
        tags.append("loopback 回环")
    if ip.is_private:
        tags.append("private 内网(RFC1918/ULA)")
    if ip.is_link_local:
        tags.append("link-local 链路本地")
    if ip.is_multicast:
        tags.append("multicast 组播")
    if ip.is_reserved:
        tags.append("reserved 保留")
    if ip.version == 6 and str(ip).lower().startswith("::ffff:"):
        tags.append("IPv4-mapped")
    scope = "内网" if ip.is_private or ip.is_loopback else "公网"
    return ok({"ip": str(ip), "version": ip.version, "scope": scope,
               "tags": tags or ["public 公网"],
               "binary": f"{int(ip):0{32 if ip.version == 4 else 128}b}",
               "exploded": ip.exploded})


@endpoint()
def net_url_parse(request):
    """URL 拆解：scheme/host/port/path/params/fragment/凭据。"""
    url = req_str(request, "url").strip()
    parsed = urlparse(url if "://" in url else "https://" + url)
    return ok({
        "scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port or (443 if parsed.scheme == "https" else 80),
        "path": parsed.path, "query": parsed.query, "fragment": parsed.fragment,
        "userinfo": parsed.username or "", "domain": ".".join((parsed.hostname or "").split(".")[-2:]),
        "params": dict(pair.split("=", 1) if "=" in pair else (pair, "") for pair in parsed.query.split("&") if pair),
    })


@endpoint()
def net_url_build(request):
    """URL 组装：scheme+host(+port)+path+params(+fragment) → 完整 URL。"""
    scheme = opt_str(request, "scheme", "https")
    host = str(req(request, "host")).strip()
    port = p(request, "port")
    path = opt_str(request, "path", "/")
    if not path.startswith("/"):
        path = "/" + path
    params = p(request, "params") or {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    qs = urlencode({k: v for k, v in params.items() if v is not None})
    fragment = opt_str(request, "fragment")
    url = f"{scheme}://{host}{':' + str(port) if port else ''}{path}"
    if qs:
        url += "?" + qs
    if fragment:
        url += "#" + str(fragment)
    return ok({"url": url})


@endpoint()
def net_ua_parse(request):
    """User-Agent 解析：浏览器/内核/操作系统/设备类型。"""
    ua = req_str(request, "user_agent")
    browsers = [("Edg", "Edge"), ("OPR", "Opera"), ("Chrome", "Chrome"), ("Firefox", "Firefox"),
                ("Version/.*Safari", "Safari"), ("MSIE", "IE"), ("Trident", "IE")]
    browser, engine = "未知", "未知"
    for pat, name in browsers:
        if re.search(pat, ua):
            browser = name
            break
    if "Gecko/" in ua and "Firefox" in ua:
        engine = "Gecko"
    elif "AppleWebKit" in ua:
        engine = "Blink" if "Chrome" in ua or "Edg" in ua else "WebKit"
    elif "Trident" in ua:
        engine = "Trident"
    os_name = ("Windows" if "Windows NT" in ua else
               "macOS" if "Mac OS X" in ua else
               "Android" if "Android" in ua else
               "iOS" if ("iPhone" in ua or "iPad" in ua) else
               "Linux" if "Linux" in ua else "未知")
    device = ("手机" if ("Mobile" in ua or "iPhone" in ua) else
              "平板" if ("iPad" in ua or "Tablet" in ua) else
              "桌面/其他")
    bot = bool(re.search(r"bot|spider|crawl|slurp|bingpreview", ua, re.I))
    m = re.search(r"(?:Chrome|Edg|Firefox|Version)[/ ](\d+)", ua)
    return ok({"browser": browser, "browser_version": m.group(1) if m else "", "engine": engine,
               "os": os_name, "device": device, "is_bot": bot, "length": len(ua)})


@endpoint()
def net_mime_lookup(request):
    """扩展名 → MIME（全表或查询；含反向查询）。"""
    q = opt_str(request, "ext", "").lower().lstrip(".")
    if q:
        if q in MIME_TABLE:
            return ok({"ext": q, "mime": MIME_TABLE[q]})
        raise ValueError(f"未收录扩展名 {q}")
    mime = opt_str(request, "mime", "").lower()
    if mime:
        hits = [e for e, m in MIME_TABLE.items() if m == mime]
        return ok({"mime": mime, "extensions": hits, "count": len(hits)})
    return ok({"table": MIME_TABLE, "count": len(MIME_TABLE)})


# =====================================================================
# fake 模拟数据（6）
# =====================================================================


def _cn_id_card(rng=None):
    rng = rng or secrets.SystemRandom()
    region = rng.choice(list(ID_REGION_CODES))
    birth = date(1960 + secrets.randbelow(45), 1 + secrets.randbelow(12), 1 + secrets.randbelow(28))
    seq = f"{secrets.randbelow(1000):03d}"
    body = f"{region}{birth.strftime('%Y%m%d')}{seq}"
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_map = "10X98765432"
    s = sum(int(d) * w for d, w in zip(body, weights))
    return body + check_map[s % 11]


@endpoint()
def fake_person(request):
    """模拟中国人：姓名/性别/手机号/身份证（校验位合法）/邮箱。"""
    n = int(opt_num(request, "count", 1, minimum=1, maximum=50) or 1)
    items = []
    for _ in range(n):
        gender = secrets.choice(["男", "女"])
        surname = secrets.choice(SURNAME)
        given = secrets.choice(GIVEN_M if gender == "男" else GIVEN_F)
        phone = "1" + secrets.choice("3456789") + "".join(secrets.choice("0123456789") for _ in range(9))
        email_user = f"{surname.lower()}{given.lower()}{secrets.randbelow(900) + 100}"
        items.append({"name": surname + given, "gender": gender, "phone": phone,
                      "id_card": _cn_id_card(None), "email": email_user + "@example.com"})
    return ok({"items": items, "count": n, "disclaimer": "均为随机生成，如有雷同纯属巧合"})


@endpoint()
def fake_company(request):
    """模拟公司：名称/行业/规模/统一社会信用代码风格编号。"""
    n = int(opt_num(request, "count", 1, minimum=1, maximum=50) or 1)
    prefixes = ["深圳", "广州", "北京", "上海", "杭州", "成都"]
    cores = ["云图", "星链", "智造", "飞鸟", "磐石", "青柠", "北极星", "万象"]
    suffixes = ["科技有限公司", "信息技术有限公司", "网络有限公司", "数据服务有限公司"]
    industries = ["互联网", "制造业", "金融", "教育", "医疗", "物流", "零售", "新能源"]
    items = []
    for _ in range(n):
        code = "".join(secrets.choice("0123456789ABCDEFGHJKLMNPQRTUWXY") for _ in range(18))
        items.append({"name": secrets.choice(prefixes) + secrets.choice(cores) + secrets.choice(suffixes),
                      "industry": secrets.choice(industries),
                      "staff": [10, 50, 100, 200, 500, 1000, 5000][secrets.randbelow(7)],
                      "credit_code_style": code})
    return ok({"items": items, "count": n})


@endpoint()
def fake_address(request):
    """模拟地址：省/市/区+街道门牌（采样自内置区划表）。"""
    n = int(opt_num(request, "count", 1, minimum=1, maximum=50) or 1)
    streets = ["科技路", "南山大道", "创业路", "金融街", "望江路", "长江西路", "中山路"]
    items = []
    for _ in range(n):
        prov = secrets.choice(list(REGION))
        city = secrets.choice(REGION[prov])
        items.append({"province": prov, "city": city,
                      "address": f"{prov}{city}{secrets.choice(streets)}{secrets.randbelow(999) + 1}号"})
    return ok({"items": items, "count": n})


@endpoint()
def fake_lorem(request):
    """中文假文生成（若干段，每段若干句）。"""
    from .data import LOREM_ZH
    paragraphs = int(opt_num(request, "paragraphs", 2, minimum=1, maximum=10) or 2)
    sentences = int(opt_num(request, "sentences", 3, minimum=1, maximum=20) or 3)
    out = []
    for _ in range(paragraphs):
        text = "".join(LOREM_ZH[(secrets.randbelow(len(LOREM_ZH)))] for _ in range(sentences * 18))
        parts = re.findall(r".{8,22}?", text)
        body = "。".join(p for p in parts[:sentences]) + "。"
        out.append(body)
    return ok({"paragraphs": out, "chars": sum(len(x) for x in out)})


@endpoint()
def fake_batch(request):
    """批量组合生成：fields=[{name, type}]，type∈name/phone/id/email/company/address/int/float/date。"""

    def gen_one(t):
        if t == "name":
            return secrets.choice(SURNAME) + secrets.choice(GIVEN_M + GIVEN_F)
        if t == "phone":
            return "1" + secrets.choice("3456789") + "".join(secrets.choice("0123456789") for _ in range(9))
        if t == "id":
            return _cn_id_card(None)
        if t == "email":
            return f"user{secrets.randbelow(100000)}@example.com"
        if t == "company":
            return secrets.choice(REGION and list(REGION)) + secrets.choice(["星辰", "远见", "逐浪"]) + "科技有限公司"
        if t == "address":
            prov = secrets.choice(list(REGION))
            return prov + secrets.choice(REGION[prov]) + "示例路" + str(secrets.randbelow(999) + 1) + "号"
        if t == "int":
            return secrets.randbelow(10000)
        if t == "float":
            return round(secrets.randbelow(1000000) / 100, 2)
        if t == "date":
            ts = datetime(2020, 1, 1).timestamp() + secrets.randbelow(int((datetime.now() - datetime(2020, 1, 1)).total_seconds()))
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        raise ValueError(f"未知类型: {t}（支持 name/phone/id/email/company/address/int/float/date）")

    fields_spec = req_list(request, "fields")
    n = int(opt_num(request, "count", 5, minimum=1, maximum=200) or 5)
    fields = []
    for f in fields_spec:
        if isinstance(f, str):
            fields.append((f, f))
        elif isinstance(f, dict) and "type" in f:
            fields.append((str(f.get("name", f["type"])), str(f["type"])))
        else:
            raise ValueError("fields 每项需为字符串或 {name, type}")
    rows = [{name: gen_one(t) for name, t in fields} for _ in range(n)]
    return ok({"rows": rows, "count": n, "fields": [f[0] for f in fields]})


@endpoint()
def fake_net(request):
    """模拟网络资源：内网 IPv4 / MAC / 域名 / 端口组合。"""
    n = int(opt_num(request, "count", 1, minimum=1, maximum=50) or 1)
    tlds = ["example.com", "test.org", "demo.dev", "sample.cn"]
    items = []
    for _ in range(n):
        ip = f"192.168.{secrets.randbelow(255)}.{1 + secrets.randbelow(253)}"
        mac = ":".join(f"{secrets.randbelow(256):02x}" for _ in range(6)).upper()
        domain = f"svc-{secrets.randbelow(10000)}.{secrets.choice(tlds)}"
        items.append({"ip": ip, "mac": mac, "domain": domain,
                      "port": secrets.choice([80, 443, 3000, 5173, 8000, 8080, 5432, 6379, 27017])})
    return ok({"items": items, "count": n})


# =====================================================================
# fun 趣味（7）
# =====================================================================


@endpoint()
def fun_fortune(request):
    """每日一签：同一天同一人签文固定（按日期+用户名做种子）。"""
    from .data import FORTUNES
    who = opt_str(request, "who", request.user.username if getattr(request, "user", None) and request.user.is_authenticated else "guest")
    today = date.today().isoformat()
    seed = int(hashlib.sha256(f"{today}:{who}".encode()).hexdigest()[:8], 16)
    level, text = FORTUNES[seed % len(FORTUNES)]
    lucky = seed % 100 + 1
    return ok({"date": today, "who": who, "level": level, "text": text,
               "lucky_number": lucky, "lucky_color": ["红", "橙", "黄", "绿", "青", "蓝", "紫"][seed % 7]})


@endpoint()
def fun_dice(request):
    """掷骰子：count 个 d sides 骰子，附点数总和与分布。"""
    count = int(req_num(request, "count", 1, minimum=1, maximum=20, integer=True))
    sides = int(opt_num(request, "sides", 6, minimum=2, maximum=100) or 6)
    rolls = [secrets.randbelow(sides) + 1 for _ in range(count)]
    return ok({"rolls": rolls, "total": sum(rolls), "sides": sides, "average": round(sum(rolls) / count, 2)})


@endpoint()
def fun_lottery(request):
    """从名单里不放回抽取 n 个（附抽取顺序）。"""
    pool = req_list(request, "pool")
    n = int(opt_num(request, "n", 1, minimum=1, maximum=len(pool) or 1) or 1)
    items = [str(x) for x in pool]
    picked, bag = [], items[:]
    for _ in range(min(n, len(items))):
        i = secrets.randbelow(len(bag))
        picked.append(bag.pop(i))
    return ok({"picked": picked, "pool_size": len(items), "remaining": len(bag)})


@endpoint()
def fun_team_splitter(request):
    """随机分组：names 按 n 组尽量均匀。"""
    names = req_list(request, "names")
    teams = int(opt_num(request, "teams", 2, minimum=2, maximum=20) or 2)
    bag = [str(x) for x in names]
    for i in range(len(bag) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        bag[i], bag[j] = bag[j], bag[i]
    groups = [[] for _ in range(teams)]
    for i, name in enumerate(bag):
        groups[i % teams].append(name)
    return ok({"teams": [{"team": f"第{i + 1}组", "members": g, "size": len(g)} for i, g in enumerate(groups)],
               "people": len(bag)})


@endpoint()
def fun_coinflip(request):
    """抛硬币：n 次，正反面统计与最长连击。"""
    n = int(opt_num(request, "count", 1, minimum=1, maximum=10000) or 1)
    flips = ["正面" if secrets.randbelow(2) else "反面" for _ in range(n)]
    streak, best = 1, 1
    for i in range(1, n):
        streak = streak + 1 if flips[i] == flips[i - 1] else 1
        best = max(best, streak)
    return ok({"count": n, "heads": flips.count("正面"), "tails": flips.count("反面"),
               "heads_pct": round(flips.count("正面") / n * 100, 1) if n else 0,
               "longest_streak": best, "results": flips if n <= 50 else None})


@endpoint()
def fun_emoji(request):
    """Emoji 搜索：中英关键词匹配（全表或搜索）。"""
    kw = opt_str(request, "keyword", "").lower()
    hits = [{"emoji": e, "keywords": ks} for e, ks in EMOJI if not kw or any(kw in k for k in ks)]
    return ok({"items": hits, "count": len(hits), "total": len(EMOJI)})


@endpoint()
def fun_today(request):
    """历史上的今天（内置精选事件表）。"""
    now = datetime.now()
    key = now.strftime("%m-%d")
    if opt_str(request, "date"):
        d = str(opt_str(request, "date"))
        m = re.match(r"(\d{1,2})-(\d{1,2})", d)
        if not m or not (1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31):
            raise ValueError("date 需为 MM-DD")
        key = f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ok({"date": key, "events": TODAY_HISTORY.get(key, []),
               "count": len(TODAY_HISTORY.get(key, [])),
               "note": "内置精选数据，欢迎在 docs 里补充" if not TODAY_HISTORY.get(key) else ""})


# =====================================================================
# cheatsheet 速查手册（8）
# =====================================================================

_CHEATSHEETS = {
    "md": ("Markdown 语法", [
        ("# 标题", "1-6 级标题，# 数量决定层级"),
        ("**粗体** / *斜体*", "强调：**b** *i* ***bi***"),
        ("`行内代码`", "反引号包裹；三反引号围栏代码块，语言名标注高亮"),
        ("> 引用", "嵌套用 >>；引用内可用全部语法"),
        ("- 列表", "无序列表 -/+/*；有序 1. 2.；嵌套缩进两空格"),
        ("| a | b |", "表格：第二行 ---: 右对齐 :--- 左对齐 :---: 居中"),
        ("[文字](url)", "链接；图片加 !；参考式 [文字][id] + [id]: url"),
        ("---", "水平分割线（*** 或 ___ 同效）"),
        ("~~删除线~~", "GFM 扩展；任务列表 - [ ] / - [x]"),
        ("脚注[^1]", "GFM 扩展，文末 [^1]: 说明文字"),
    ]),
    "git": ("Git 命令", [
        ("git init / clone", "初始化仓库 / 克隆远端（-b 指定分支）"),
        ("git status -sb", "简短状态 + 分支跟踪信息"),
        ("git add -p", "交互式暂存补丁块，精细控制提交内容"),
        ("git commit --amend", "修正上一次提交（push 过则需 force）"),
        ("git log --oneline --graph", "单行图形化历史；-S 关键字找提交"),
        ("git restore --staged", "取消暂存；git restore 丢弃工作区改动"),
        ("git reset --soft HEAD~1", "撤销提交保留改动；--hard 彻底丢弃（慎用）"),
        ("git rebase -i HEAD~3", "交互变基：squash/fixup/reorder"),
        ("git stash push/pop", "临时收起与恢复工作区；list 查看"),
        ("git bisect start", "二分定位引入 bug 的提交"),
        ("git cherry-pick <sha>", "摘取单个提交到当前分支"),
        ("git reflog", "找回「丢失」的提交（后悔药）"),
    ]),
    "vim": ("Vim 操作", [
        ("h j k l", "左下上右移动；0/^ 行首 $ 行尾 gg G 文件首尾"),
        ("w b e", "词间跳转；f{char} 行内查找 ; , 重复"),
        ("i a o", "插入模式变体：前插/后插/下行开新行"),
        ("dd yy p", "剪切行/复制行/粘贴；3dd 操作计数"),
        ("ciw ci\"", "改内词/改引号内；di( 删括号内，textobj 万能公式"),
        ("u Ctrl-r", "撤销 / 重做"),
        ("/ ? n N", "向下/向上搜索，下一个/上一个"),
        (":%s/old/new/g", "全文替换；加 c 逐个确认；'<,'> 仅选区"),
        ("v V Ctrl-v", "可视/行选/块选，块选后 I A 批量插入"),
        (":w !sudo tee %", "忘开 sudo 的补救保存"),
        ("zz zt zb", "当前行居中/顶部/底部"),
        (":e! / :q!", "放弃改动重读 / 不保存退出"),
    ]),
    "shell": ("Shell 命令", [
        ("grep -rn 'kw' dir", "递归搜文本；-i 忽略大小写 -E 扩展正则"),
        ("find . -name '*.py' -mtime -7", "按名/时间找文件；-exec cmd {} \\;"),
        ("awk -F, '{print $2}'", "按列处理文本；NR 行号 NF 列数"),
        ("sed -i 's/a/b/g' file", "流编辑替换；-n + p 只输出匹配行"),
        ("xargs -P4 -I{} cmd {}", "并行消费管道输入；-I 占位符"),
        ("ps aux | grep xxx", "查进程；kill -9 pid 强杀"),
        ("df -h / du -sh *", "磁盘余量 / 目录体积"),
        ("tar -czvf x.tgz dir", "打包压缩；-xzvf 解包"),
        ("curl -X POST -d @data.json", "发请求；-H 头 -o 落盘 -L 跟随跳转"),
        ("chmod 755 / chown", "权限位 rwx=421；属主变更"),
        ("history | tail", "历史命令；Ctrl-r 反向搜索"),
        ("nohup cmd & / jobs fg bg", "后台任务三件套"),
    ]),
    "regex": ("正则表达式", [
        (". \\d \\w \\s", "任意字符/数字/字母数字下划线/空白；大写取反"),
        ("^ $ \\b", "行首/行尾/单词边界"),
        ("* + ? {n,m}", "量词：任意/至少一/零或一/次数区间；后接 ? 变惰性"),
        ("[abc] [^abc] [a-z]", "字符组与否定；组内元字符不需转义"),
        ("(exp) (?:exp)", "捕获组 / 非捕获组；\\1 反向引用"),
        ("(?<name>exp)", "命名组；Python 里 (?P<name>exp)"),
        ("(?=exp) (?!exp)", "正向/负向先行断言（不消耗字符）"),
        ("(?<=exp) (?<!exp)", "正向/负向后行断言"),
        ("a|b", "或；注意优先级，常配合分组用"),
        ("\\p{Han}", "Unicode 属性（PCRE/部分引擎）——匹配汉字"),
        ("Flags: i g m s x", "忽略大小写/全局/多行/点匹配换行/宽松书写"),
    ]),
    "http": ("HTTP 要点", [
        ("GET / POST", "GET 幂等可缓存；POST 非幂等；PUT 全量替换 DELETE 删除"),
        ("200 201 204", "成功/已创建/无内容"),
        ("301 302 304", "永久跳转/临时跳转/缓存有效"),
        ("400 401 403 404", "参数错/未认证/已认证无权限/资源不存在"),
        ("409 422 429", "冲突/校验失败/请求过于频繁"),
        ("500 502 503 504", "服务端错/网关上游错/过载维护/网关超时"),
        ("Content-Type", "application/json;charset=utf-8 最常用；multipart/form-data 传文件"),
        ("Authorization: Bearer", "JWT 携带方式；Cookie: 会话；Set-Cookie 属性"),
        ("Cache-Control / ETag", "缓存策略头；ETag + If-None-Match 协商缓存"),
        ("CORS", "Access-Control-Allow-Origin 等头；预检 OPTIONS"),
    ]),
    "python": ("Python 常用", [
        ("f\"{x:.2f}\"", "格式化字符串；:,.2f 千分位，:>10 右对齐"),
        ("列表推导 [x*2 for x in xs if x]", "同理字典/集合推导"),
        ("enumerate / zip", "带下标迭代 / 平行迭代（zip(*matrix) 转置）"),
        ("with open(...) as f", "上下文管理；pathlib.Path 读写更顺手"),
        ("dataclass / TypedDict", "轻量结构体；pydantic 做校验"),
        ("{**a, **b} | a|b", "字典合并（3.9+ 用 |）"),
        ("sorted(xs, key=lambda x: -x)", "稳定排序；itemgetter 更快"),
        ("setdefault / defaultdict / Counter", "计数与分组利器"),
        ("try/except/else/finally", "else 无异常才走；raise X from e 保留因果"),
        ("__name__ == '__main__'", "入口守卫；if TYPE_CHECKING: 类型提示专用导入"),
    ]),
    "sql": ("SQL 速查", [
        ("SELECT ... WHERE ... GROUP BY ... HAVING", "标准四段；HAVING 过滤聚合后结果"),
        ("JOIN / LEFT JOIN", "内连接取交集；左连接保左表；NULL 判定用 IS NULL"),
        ("ORDER BY x DESC NULLS LAST", "排序；LIMIT/OFFSET 分页（大偏移要游标）"),
        ("CASE WHEN ... THEN ... END", "行内条件；聚合内做条件计数"),
        ("INSERT ... ON CONFLICT DO UPDATE", "Upsert；MySQL 是 ON DUPLICATE KEY UPDATE"),
        ("UPDATE t SET x=? WHERE id=?", "永远带 WHERE；先用 SELECT 预演"),
        ("EXISTS / IN", "大表用 EXISTS 常更快；NOT IN 遇 NULL 会全空"),
        ("窗口函数 ROW_NUMBER() OVER(PARTITION BY ...)", "组内排名/去重神器"),
        ("索引覆盖", "最左前缀；避免对索引列套函数"),
        ("EXPLAIN", "看执行计划再优化，不要靠猜"),
    ]),
}


@endpoint(("GET", "POST"))
def cheatsheet_md(request):
    """Markdown 语法速查表。"""
    name, entries = _CHEATSHEETS["md"]
    return ok({"key": "md", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_git(request):
    """Git 高频命令速查表。"""
    name, entries = _CHEATSHEETS["git"]
    return ok({"key": "git", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_vim(request):
    """Vim 操作速查表。"""
    name, entries = _CHEATSHEETS["vim"]
    return ok({"key": "vim", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_shell(request):
    """Shell 命令速查表。"""
    name, entries = _CHEATSHEETS["shell"]
    return ok({"key": "shell", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_regex(request):
    """正则表达式速查表。"""
    name, entries = _CHEATSHEETS["regex"]
    return ok({"key": "regex", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_http(request):
    """HTTP 状态码与头部速查表。"""
    name, entries = _CHEATSHEETS["http"]
    return ok({"key": "http", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_python(request):
    """Python 常用语法速查表。"""
    name, entries = _CHEATSHEETS["python"]
    return ok({"key": "python", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


@endpoint(("GET", "POST"))
def cheatsheet_sql(request):
    """SQL 速查表。"""
    name, entries = _CHEATSHEETS["sql"]
    return ok({"key": "sql", "name": name, "entries": [{"term": t, "desc": d} for t, d in entries]})


# =====================================================================
# asciiart ASCII 艺术（6）
# =====================================================================

_BANNER_FONT = {
    "A": [".###.", "#...#", "#####", "#...#", "#...#"],
    "B": ["####.", "#...#", "####.", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "####.", "#....", "#####"],
    "F": ["#####", "#....", "####.", "#....", "#...."],
    "G": [".####", "#....", "#..##", "#...#", ".####"],
    "H": ["#...#", "#...#", "#####", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "#####"],
    "J": ["....#", "....#", "....#", "#...#", ".###."],
    "K": ["#...#", "#..#.", "###..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "####.", "#....", "#...."],
    "Q": [".###.", "#...#", "#.#.#", "#..##", ".##.#"],
    "R": ["####.", "#...#", "####.", "#..#.", "#...#"],
    "S": [".####", "#....", ".###.", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
    "Y": ["#...#", ".#.#.", "..#..", "..#..", "..#.."],
    "Z": ["#####", "...#.", "..#..", ".#...", "#####"],
    "0": [".###.", "#..##", "#.#.#", "##..#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "#####"],
    "2": [".###.", "#...#", "...#.", "..#..", "#####"],
    "3": ["####.", "....#", ".###.", "....#", "####."],
    "4": ["#..#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "####."],
    "6": [".###.", "#....", "####.", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", "..#.."],
    "8": [".###.", "#...#", ".###.", "#...#", ".###."],
    "9": [".###.", "#...#", ".####", "....#", ".###."],
    " ": [".....", ".....", ".....", ".....", "....."],
}


def _banner_rows(text):
    rows = ["", "", "", "", ""]
    unknown = []
    for ch in text.upper():
        glyph = _BANNER_FONT.get(ch)
        if glyph is None:
            if ch not in unknown:
                unknown.append(ch)
            glyph = _BANNER_FONT[" "]
        for i in range(5):
            rows[i] += glyph[i] + " "
    return [r.rstrip() for r in rows], unknown


@endpoint()
def asciiart_banner(request):
    """大字横幅：5x5 字模渲染（支持 A-Z 0-9 空格）。"""
    text = req_str(request, "text").strip()
    if not text or len(text) > 24:
        raise ValueError("text 需为 1-24 个字符（A-Z 0-9 空格）")
    rows, unknown = _banner_rows(text)
    return ok({"text": text, "art": "\n".join(rows), "rows": rows,
               "unknown_chars": unknown, "width": len(rows[0])})


@endpoint()
def asciiart_box(request):
    """把文本装进 Unicode/ASCII 边框盒。"""
    lines = as_lines(req_str(request, "text"))
    if not lines or len(lines) > 40:
        raise ValueError("text 需为 1-40 行文本")
    style = opt_str(request, "style", "unicode")
    box = {"unicode": ("┌", "┐", "└", "┘", "─", "│"),
           "ascii": ("+", "+", "+", "+", "-", "|"),
           "double": ("╔", "╗", "╚", "╝", "═", "║"),
           "round": ("╭", "╮", "╰", "╯", "─", "│")}
    if style not in box:
        raise ValueError(f"style 支持 {list(box)}")
    tl, tr, bl, br, hz, vt = box[style]
    width = max(len(s) for s in lines) + 2
    out = [tl + hz * width + tr]
    out += [vt + " " + s.ljust(width - 2) + " " + vt for s in lines]
    out.append(bl + hz * width + br)
    return ok({"style": style, "art": "\n".join(out), "width": width, "lines": len(lines)})


@endpoint()
def asciiart_table(request):
    """把二维数组渲染成对齐的 ASCII 表格。"""
    rows = req_list(request, "rows", max_len=200)
    if len(rows) < 1 or any(not isinstance(r, list) for r in rows):
        raise ValueError("rows 需为二维数组")
    cols = max(len(r) for r in rows)
    grid = [[("" if v is None else str(v)) for v in (list(r) + [""] * (cols - len(r)))] for r in rows]
    widths = [max(len(g[j]) for g in grid) for j in range(cols)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    for i, g in enumerate(grid):
        out.append("|" + "|".join(f" {c.ljust(widths[j])} " for j, c in enumerate(g)) + "|")
        if i == 0 and len(grid) > 1:
            out.append(sep)
    if len(grid) > 1:
        out.append(sep)
    return ok({"art": "\n".join(out), "rows": len(grid), "cols": cols})


@endpoint()
def asciiart_block(request):
    """像素矩阵 → 方块画：1→█ 0→空，可选密度字符。"""
    matrix = req_list(request, "matrix", max_len=100)
    if not matrix or any(not isinstance(r, list) for r in matrix):
        raise ValueError("matrix 需为二维 0/1 数组")
    w = len(matrix[0])
    if any(len(r) != w for r in matrix) or len(matrix) > 60 or w > 80:
        raise ValueError("矩阵需为矩形且不超过 60x80")
    on, off = opt_str(request, "on", "██") or "██", opt_str(request, "off", "  ") or "  "
    art = "\n".join("".join(on if c else off for c in row) for row in matrix)
    filled = sum(1 for row in matrix for c in row if c)
    return ok({"art": art, "size": [len(matrix), w],
               "fill_ratio": round(filled / (len(matrix) * w) * 100, 1)})


_SPARK = "▁▂▃▄▅▆▇█"


@endpoint()
def asciiart_sparkline(request):
    """数值序列 → 火花线 ▁▂▃▅▇（Tufte 风格）。"""
    values = req_list(request, "values", max_len=500)
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values 需为数字数组")
    if not nums:
        raise ValueError("values 不能为空")
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1
    bars = "".join(_SPARK[min(int((v - lo) / span * (len(_SPARK) - 1)), len(_SPARK) - 1)] for v in nums)
    return ok({"sparkline": bars, "min": lo, "max": hi,
               "trend": "up" if len(nums) > 1 and nums[-1] > nums[0] else ("down" if len(nums) > 1 else "flat")})


@endpoint()
def asciiart_progress(request):
    """ASCII 进度条：多种字符风格，支持多段。"""
    percent = float(req_num(request, "percent", minimum=0, maximum=100))
    width = int(opt_num(request, "width", 30, minimum=5, maximum=120) or 30)
    style = opt_str(request, "style", "block")
    styles = {"block": ("█", "░"), "ascii": ("#", "-"), "equal": ("=", "."),
              "square": ("■", "□"), "sha": ("▮", "▯")}
    if style not in styles:
        raise ValueError(f"style 支持 {list(styles)}")
    on, off = styles[style]
    filled = on * round(percent / 100 * width)
    empty = off * (width - len(filled))
    return ok({"bar": f"[{filled}{empty}] {percent:.0f}%", "percent": percent,
               "width": width, "style": style})


# =====================================================================
# fun/zodiac + fake/bank-card（2）
# =====================================================================

_CONSTELLATION = [(1, 20, 2, 18, "水瓶座"), (2, 19, 3, 20, "双鱼座"), (3, 21, 4, 19, "白羊座"),
                  (4, 20, 5, 20, "金牛座"), (5, 21, 6, 21, "双子座"), (6, 22, 7, 22, "巨蟹座"),
                  (7, 23, 8, 22, "狮子座"), (8, 23, 9, 22, "处女座"), (9, 23, 10, 23, "天秤座"),
                  (10, 24, 11, 22, "天蝎座"), (11, 23, 12, 21, "射手座")]
_ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"


@endpoint()
def fun_zodiac(request):
    """生肖与星座：按公历生日推算（生肖以立春 2/4 近似分界）。"""
    birth = req_str(request, "birth").strip()
    try:
        d = datetime.strptime(birth, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("birth 需为 YYYY-MM-DD")
    y, m, day = d.year, d.month, d.day
    zy = y if (m, day) >= (2, 4) else y - 1
    zodiac = _ZODIAC[(zy - 4) % 12]
    const_ = None
    for s_m, s_d, e_m, e_d, name in _CONSTELLATION:
        if (m, day) >= (s_m, s_d) and (m, day) <= (e_m, e_d):
            const_ = name
            break
    if const_ is None:
        const_ = "摩羯座"  # 12/22-1/19 跨年段
    age = datetime.now().year - y
    return ok({"birth": birth, "zodiac": zodiac, "zodiac_year": f"{zy}年",
               "constellation": const_, "age": age})


_CARD_BINS = {"visa": "4", "mastercard": "5", "unionpay": "62"}


@endpoint()
def fake_bank_card(request):
    """模拟银行卡号：Luhn 校验位合法 + 有效期 + CVV（仅供测试，非真实卡）。"""
    scheme = opt_str(request, "scheme", "unionpay")
    if scheme not in _CARD_BINS:
        raise ValueError(f"scheme 支持 {list(_CARD_BINS)}")
    rng = secrets.SystemRandom()
    prefix = _CARD_BINS[scheme] + "".join(str(rng.randrange(10)) for _ in range(10 if scheme != "mastercard" else 13))
    digits = prefix + "0"
    check = (10 - sum(int(d) * (2 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits))) % 10) % 10
    card_no = prefix + str(check)
    year = datetime.now().year + rng.randrange(1, 6)
    month = rng.randrange(1, 13)
    cvv = f"{rng.randrange(1000):03d}"
    return ok({"scheme": scheme, "card_number": card_no,
               "valid_thru": f"{month:02d}/{str(year)[2:]}",
               "cvv": cvv, "luhn_valid": True,
               "masked": card_no[:4] + " **** **** " + card_no[-4:],
               "note": "仅供联调/演示使用，不对应任何真实账户"})


FAMILY_COUNT = 6 + 7 + 8 + 8 + 6 + 2  # = 37（net/fake/fun/cheatsheet/asciiart/补充）
