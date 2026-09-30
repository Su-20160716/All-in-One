# -*- coding: utf-8 -*-
"""minitools · 商业工具家族（10 个）。

去重：validate 已有 tax-number-cn/uscc-cn/bank-card/credit-card-type/phone-cn；
这里做 EAN-13 校验位、价税分离、毛利率、BIN/号段查表、快递识别等。
"""
import re

from .common import endpoint, ok, opt_num, opt_str, req_num, req_str

# 简化 BIN 表：卡号前 6 位 -> (银行, 卡类型)
BIN_TABLE = {
    "622202": ("工商银行", "借记卡"), "622208": ("工商银行", "借记卡"),
    "621226": ("工商银行", "借记卡"), "622848": ("农业银行", "借记卡"),
    "622262": ("交通银行", "借记卡"), "622700": ("建设银行", "借记卡"),
    "622600": ("中信银行", "借记卡"), "622588": ("招商银行", "借记卡"),
    "622690": ("中信银行", "信用卡"), "439225": ("招商银行", "Visa"),
    "622588": ("招商银行", "借记卡"), "621700": ("建设银行", "借记卡"),
    "622845": ("农业银行", "借记卡"), "521899": ("中国银行", "Mastercard"),
}

# 手机号段前 3 位 -> 运营商（简化表）
MOBILE_SEGMENTS = {
    "134": "移动", "135": "移动", "136": "移动", "137": "移动", "138": "移动",
    "139": "移动", "150": "移动", "151": "移动", "152": "移动", "157": "移动",
    "158": "移动", "159": "移动", "182": "移动", "183": "移动", "184": "移动",
    "187": "移动", "188": "移动", "198": "移动",
    "130": "联通", "131": "联通", "132": "联通", "145": "联通", "155": "联通",
    "156": "联通", "175": "联通", "176": "联通", "185": "联通", "186": "联通",
    "166": "联通",
    "133": "电信", "149": "电信", "153": "电信", "173": "电信", "177": "电信",
    "180": "电信", "181": "电信", "189": "电信", "199": "电信",
}


@endpoint()
def ean13(request):
    """B01. EAN-13 条码校验位计算/校验。"""
    code = re.sub(r"\D", "", req_str(request, "code"))
    if len(code) == 12:
        odd = sum(int(code[i]) for i in range(0, 12, 2))
        even = sum(int(code[i]) for i in range(1, 12, 2))
        check = (10 - (odd + even * 3) % 10) % 10
        return ok({"code": code + str(check), "check_digit": check, "complete": True})
    if len(code) == 13:
        body = code[:12]
        given = int(code[12])
        odd = sum(int(body[i]) for i in range(0, 12, 2))
        even = sum(int(body[i]) for i in range(1, 12, 2))
        expected = (10 - (odd + even * 3) % 10) % 10
        return ok({"valid": given == expected, "expected": expected, "given": given})
    raise ValueError("EAN-13 需 12 位（算校验位）或 13 位（校验）")


@endpoint()
def vat_split(request):
    """B02. 增值税价税分离。price 为含税价，rate 默认 13%。"""
    price = req_num(request, "price", minimum=0)
    rate = opt_num(request, "rate", default=13)
    net = price / (1 + rate / 100.0)
    tax = price - net
    return ok({"net": round(net, 2), "tax": round(tax, 2), "gross": price})


@endpoint()
def margin(request):
    """B03. 毛利率 / 加价率。cost 成本，price 售价。"""
    cost = req_num(request, "cost", minimum=0.0001)
    price = req_num(request, "price", minimum=0)
    profit = price - cost
    return ok({
        "profit": round(profit, 2),
        "gross_margin_pct": round(profit / price * 100, 2) if price else 0,
        "markup_pct": round(profit / cost * 100, 2),
    })


@endpoint()
def bank_bin(request):
    """B04. 银行卡 BIN 查表（前 6 位）。"""
    card = re.sub(r"\D", "", req_str(request, "card"))
    head = card[:6]
    info = BIN_TABLE.get(head)
    return ok({"bin": head, "info": info, "found": info is not None})


@endpoint()
def mobile_segment(request):
    """B05. 中国手机号段运营商归属（前 3 位）。"""
    phone = re.sub(r"\D", "", req_str(request, "phone"))
    seg = phone[:3]
    carrier = MOBILE_SEGMENTS.get(seg)
    return ok({"segment": seg, "carrier": carrier,
               "is_cn_mobile": len(phone) == 11 and phone.startswith("1")})


@endpoint()
def express_recognize(request):
    """B06. 快递单号规则识别（长度+前缀）。"""
    no = req_str(request, "no").strip().upper()
    n = len(no)
    if re.fullmatch(r"1\d{12}", no) or re.fullmatch(r"SF\d{10,12}", no):
        carrier = "顺丰"
    elif re.fullmatch(r"\d{12,15}", no) and no.startswith(("1", "3", "4")):
        carrier = "圆通/中通"
    elif re.fullmatch(r"YT\d{10,15}", no):
        carrier = "圆通"
    elif re.fullmatch(r"ZTO\d{10,15}", no):
        carrier = "中通"
    elif re.fullmatch(r"YD\d{10,15}", no):
        carrier = "韵达"
    elif re.fullmatch(r"EMS\d{9,11}", no) or n == 13:
        carrier = "EMS/邮政"
    else:
        carrier = "未知"
    return ok({"number": no, "length": n, "carrier": carrier})


@endpoint()
def commission(request):
    """B07. 销售佣金：base + rate% × amount。"""
    amount = req_num(request, "amount", minimum=0)
    rate = opt_num(request, "rate", default=5)
    base = opt_num(request, "base", default=0)
    comm = base + amount * rate / 100.0
    return ok({"commission": round(comm, 2)})


@endpoint()
def gross_up(request):
    """B08. 税后反推税前：net = gross × (1 - tax_rate)。"""
    net = req_num(request, "net", minimum=0)
    rate = opt_num(request, "rate", default=13)
    gross = net / (1 - rate / 100.0)
    return ok({"gross": round(gross, 2), "tax": round(gross - net, 2), "net": net})


@endpoint()
def unit_price(request):
    """B09. 单位价格：总价 / 数量（或按重量）。"""
    total = req_num(request, "total", minimum=0)
    qty = req_num(request, "quantity", minimum=0.0001)
    unit = opt_str(request, "unit", "件")
    return ok({"unit_price": round(total / qty, 4), "per": unit})


@endpoint()
def profit_calc(request):
    """B10. 净利润：售价 - 成本 - 费用。"""
    price = req_num(request, "price", minimum=0)
    cost = req_num(request, "cost", minimum=0)
    expense = opt_num(request, "expense", default=0, minimum=0)
    profit = price - cost - expense
    return ok({"revenue": price, "cost": cost, "expense": expense,
               "net_profit": round(profit, 2),
               "margin_pct": round(profit / price * 100, 2) if price else 0})
