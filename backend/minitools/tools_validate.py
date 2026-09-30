# -*- coding: utf-8 -*-
"""minitools · 校验器家族（22 个，编号 149-170）。"""
import ipaddress
import json
import re
from datetime import datetime

from .common import endpoint, ok, opt_num, opt_str, req_str


@endpoint()
def email(request):
    """149. 邮箱格式校验。"""
    email = req_str(request, "email").strip()
    m = re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email)
    valid = bool(m)
    return ok({"valid": valid, "normalized": email.lower(), "reason": "" if valid else "格式不正确"})


@endpoint()
def phone_cn(request):
    """150. 中国手机号校验。"""
    phone = req_str(request, "phone").strip()
    m = re.match(r"^1[3-9]\d{9}$", phone)
    carrier = ""
    if m:
        prefix = phone[:3]
        if prefix in ("134", "135", "136", "137", "138", "139", "150", "151", "152", "157", "158", "159", "187", "188"):
            carrier = "中国移动"
        elif prefix in ("130", "131", "132", "155", "156", "185", "186", "176"):
            carrier = "中国联通"
        else:
            carrier = "中国电信"
    return ok({"valid": bool(m), "carrier": carrier, "region": "中国大陆"})


@endpoint()
def id_card_cn(request):
    """151. 中国身份证校验（18位）。"""
    idc = req_str(request, "id_card").strip().upper()
    if not re.match(r"^\d{17}[\dX]$", idc):
        return ok({"valid": False, "gender": "", "birth": "", "region": ""})
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    codes = "10X98765432"
    s = sum(int(idc[i]) * weights[i] for i in range(17))
    valid = codes[s % 11] == idc[17]
    birth = f"{idc[6:10]}-{idc[10:12]}-{idc[12:14]}"
    gender = "男" if int(idc[16]) % 2 else "女"
    return ok({"valid": valid, "gender": gender, "birth": birth, "region": idc[:2] + "0000"})


@endpoint()
def bank_card(request):
    """152. 银行卡 Luhn 校验。"""
    card = re.sub(r"\s+", "", req_str(request, "card_number"))
    if not card.isdigit() or len(card) < 12:
        return ok({"valid": False, "bank_hint": ""})
    digits = [int(d) for d in card]
    check = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        check += d
    return ok({"valid": check % 10 == 0, "bank_hint": ""})


@endpoint()
def url(request):
    """153. URL 格式校验。"""
    url = req_str(request, "url").strip()
    m = re.match(r"^(https?://)?([\w.-]+)(:\d+)?(/[\w./?&=%-]*)?$", url)
    valid = bool(m)
    return ok({"valid": valid, "parts": {"host": m.group(2) if m else ""}, "reason": "" if valid else "URL 格式不正确"})


@endpoint()
def isbn(request):
    """154. ISBN 校验（10/13）。"""
    isbn = re.sub(r"[-\s]", "", req_str(request, "isbn"))
    valid = False
    fmt = ""
    if len(isbn) == 10 and isbn[:9].isdigit():
        s = sum((i + 1) * int(isbn[i]) for i in range(9))
        last = 10 if isbn[9] == "X" else int(isbn[9])
        valid = (s + last) % 11 == 0
        fmt = "ISBN-10"
    elif len(isbn) == 13 and isbn.isdigit():
        s = sum(int(isbn[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
        valid = (10 - s % 10) % 10 == int(isbn[12])
        fmt = "ISBN-13"
    return ok({"valid": valid, "format": fmt, "check_digit": isbn[-1] if isbn else ""})


@endpoint()
def postal_code_cn(request):
    """155. 中国邮政编码校验。"""
    code = req_str(request, "code").strip()
    valid = bool(re.match(r"^\d{6}$", code))
    return ok({"valid": valid, "region": ""})


@endpoint()
def password_strength(request):
    """156. 密码强度评估。"""
    pwd = req_str(request, "password")
    score = 0
    feedback = []
    if len(pwd) >= 8:
        score += 1
    else:
        feedback.append("至少 8 位")
    if re.search(r"[A-Z]", pwd):
        score += 1
    else:
        feedback.append("需要大写字母")
    if re.search(r"[a-z]", pwd):
        score += 1
    else:
        feedback.append("需要小写字母")
    if re.search(r"\d", pwd):
        score += 1
    else:
        feedback.append("需要数字")
    if re.search(r"[^A-Za-z0-9]", pwd):
        score += 1
    else:
        feedback.append("需要特殊字符")
    level = ["弱", "一般", "中等", "强", "很强"][score]
    return ok({"score": score, "level": level, "feedback": feedback})


@endpoint()
def ip(request):
    """157. IPv4/IPv6 校验。"""
    ip_s = req_str(request, "ip").strip()
    try:
        addr = ipaddress.ip_address(ip_s)
        return ok({"valid": True, "version": addr.version, "parts": str(addr)})
    except ValueError:
        return ok({"valid": False, "version": 0, "parts": ""})


@endpoint()
def mac(request):
    """158. MAC 地址校验。"""
    mac = req_str(request, "mac").strip()
    m = re.match(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$", mac)
    return ok({"valid": bool(m), "normalized": mac.upper().replace("-", ":") if m else ""})


@endpoint()
def date_valid(request):
    """159. 日期合法性校验。"""
    ds = req_str(request, "date_str")
    fmt = opt_str(request, "format", "%Y-%m-%d")
    try:
        d = datetime.strptime(ds, fmt)
        return ok({"valid": True, "parsed": d.strftime("%Y-%m-%d")})
    except ValueError:
        return ok({"valid": False, "parsed": ""})


@endpoint()
def credit_card_type(request):
    """160. 信用卡类型识别。"""
    card = re.sub(r"\s+", "", req_str(request, "card_number"))
    ctype = "未知"
    if re.match(r"^4[0-9]{12}(?:[0-9]{3})?$", card):
        ctype = "Visa"
    elif re.match(r"^5[1-5][0-9]{14}$", card):
        ctype = "MasterCard"
    elif re.match(r"^3[47][0-9]{13}$", card):
        ctype = "American Express"
    elif re.match(r"^6(?:011|5[0-9]{2})[0-9]{12}$", card):
        ctype = "Discover"
    digits = [int(d) for d in card]
    check = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        check += d
    return ok({"type": ctype, "valid": check % 10 == 0})


@endpoint()
def uscc_cn(request):
    """161. 统一社会信用代码校验（简化：18位）。"""
    code = req_str(request, "code").strip().upper()
    valid = bool(re.match(r"^[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}$", code))
    return ok({"valid": valid, "dept": code[0] if valid else "", "type": code[1] if valid else ""})


@endpoint()
def plate_cn(request):
    """162. 中国车牌号校验。"""
    plate = req_str(request, "plate").strip().upper()
    valid = bool(re.match(r"^[\u4e00-\u9fff][A-Z][A-Z0-9]{5,6}$", plate))
    return ok({"valid": valid, "type": "新能源" if len(plate) == 8 else "普通", "region": plate[0] if valid else ""})


@endpoint()
def passport(request):
    """163. 护照号格式校验。"""
    p = req_str(request, "passport").strip()
    valid = bool(re.match(r"^[A-Z]\d{8}$", p))
    return ok({"valid": valid, "pattern": "PXXXXXXXX"})


@endpoint()
def domain(request):
    """164. 域名格式校验。"""
    d = req_str(request, "domain").strip().lower()
    valid = bool(re.match(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", d))
    parts = d.rsplit(".", 1)
    return ok({"valid": valid, "tld": parts[-1] if valid else "", "sld": parts[0] if valid and len(parts) > 1 else ""})


@endpoint()
def json_check(request):
    """165. JSON 格式校验。"""
    text = req_str(request, "json_text")
    try:
        data = json.loads(text)
        return ok({"valid": True, "error": "", "type": type(data).__name__})
    except Exception as e:
        return ok({"valid": False, "error": str(e), "type": ""})


@endpoint()
def xml_check(request):
    """166. XML 格式校验（基础）。"""
    import xml.etree.ElementTree as ET
    text = req_str(request, "xml_text")
    try:
        ET.fromstring(text)
        return ok({"valid": True, "error": ""})
    except Exception as e:
        return ok({"valid": False, "error": str(e)})


@endpoint()
def repeat_char(request):
    """167. 重复字符检测。"""
    text = req_str(request, "text")
    min_len = int(opt_num(request, "min_len", 3, minimum=2, maximum=20, integer=True))
    repeats = re.findall(r"(.)\1{" + str(min_len - 1) + r",}", text)
    return ok({"repeats": repeats})


@endpoint()
def strong_password(request):
    """168. 强密码生成+校验。"""
    import secrets
    import string
    length = int(opt_num(request, "length", 16, minimum=8, maximum=128, integer=True))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    pwd = "".join(secrets.choice(alphabet) for _ in range(length))
    score = sum([len(pwd) >= 8, bool(re.search(r"[A-Z]", pwd)), bool(re.search(r"[a-z]", pwd)),
                 bool(re.search(r"\d", pwd)), bool(re.search(r"[^A-Za-z0-9]", pwd))])
    return ok({"password": pwd, "score": score})


@endpoint()
def tax_number_cn(request):
    """169. 纳税人识别号校验（简化：15/18/20位）。"""
    tax = req_str(request, "tax_no").strip()
    valid = bool(re.match(r"^[0-9A-Z]{15,20}$", tax))
    return ok({"valid": valid})


@endpoint()
def social_security_cn(request):
    """170. 社保号格式校验（身份证号复用）。"""
    ssn = req_str(request, "ssn").strip()
    valid = bool(re.match(r"^\d{17}[\dX]$", ssn))
    return ok({"valid": valid})
