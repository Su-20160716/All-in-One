# -*- coding: utf-8 -*-
"""minitools · 金融计算家族（16 个）。

与已有能力去重：
- num/compound-interest（一次性复利本息）→ 这里做年金/NPV/IRR/折旧/个税/定投等
- num/loan-payment（等额本息月供）→ 这里做等额本金计划、按月供反推额度
- num/discount-calc（打折）→ 不重复
"""
import math

from .common import endpoint, ok, opt_num, p, req_num, req_list


def _rate_month(annual_pct):
    """年利率(百分数) -> 月利率小数。"""
    return annual_pct / 100.0 / 12.0


@endpoint()
def loan_equal_principal(request):
    """F01. 等额本金月供计划：每月还本金固定，利息逐月递减。"""
    principal = req_num(request, "principal", minimum=0)
    annual_rate = req_num(request, "annual_rate", minimum=0)
    months = int(req_num(request, "months", minimum=1))
    r = _rate_month(annual_rate)
    monthly_principal = principal / months
    schedule = []
    balance = principal
    total_interest = 0.0
    for k in range(1, months + 1):
        interest = balance * r
        total = monthly_principal + interest
        total_interest += interest
        balance -= monthly_principal
        schedule.append({
            "month": k,
            "principal": round(monthly_principal, 2),
            "interest": round(interest, 2),
            "payment": round(total, 2),
            "balance": round(max(balance, 0), 2),
        })
    return ok({
        "monthly_principal": round(monthly_principal, 2),
        "first_payment": round(monthly_principal + principal * r, 2),
        "last_payment": round(monthly_principal + (monthly_principal) * r, 2),
        "total_interest": round(total_interest, 2),
        "total_payment": round(principal + total_interest, 2),
        "schedule": schedule,
    })


@endpoint()
def roi(request):
    """F02. ROI 投资回报率。"""
    cost = req_num(request, "cost", minimum=0)
    gain = req_num(request, "gain")
    if cost == 0:
        raise ValueError("成本不能为 0")
    roi = (gain - cost) / cost * 100.0
    return ok({"roi_pct": round(roi, 2), "net_profit": round(gain - cost, 2)})


@endpoint()
def annuity_fv(request):
    """F03. 普通年金终值：期末定期定额存款到期总额。"""
    pmt = req_num(request, "pmt", minimum=0)
    annual_rate = req_num(request, "annual_rate", minimum=0)
    years = req_num(request, "years", minimum=0)
    r = annual_rate / 100.0
    n = years
    if r == 0:
        fv = pmt * n
    else:
        fv = pmt * (((1 + r) ** n - 1) / r)
    return ok({"fv": round(fv, 2), "total_deposits": round(pmt * n, 2),
               "interest_earned": round(fv - pmt * n, 2)})


@endpoint()
def annuity_pv(request):
    """F04. 普通年金现值：未来 n 年每年末取 pmt，现在需一次性存入多少。"""
    pmt = req_num(request, "pmt", minimum=0)
    annual_rate = req_num(request, "annual_rate", minimum=0)
    years = req_num(request, "years", minimum=0)
    r = annual_rate / 100.0
    n = years
    if r == 0:
        pv = pmt * n
    else:
        pv = pmt * (1 - (1 + r) ** (-n)) / r
    return ok({"pv": round(pv, 2)})


@endpoint()
def depreciation_straight(request):
    """F05. 直线法折旧。"""
    cost = req_num(request, "cost", minimum=0)
    salvage = opt_num(request, "salvage", default=0, minimum=0)
    life = int(req_num(request, "life_years", minimum=1))
    annual = (cost - salvage) / life
    schedule = []
    book = cost
    for y in range(1, life + 1):
        book -= annual
        schedule.append({"year": y, "depreciation": round(annual, 2),
                         "book_value": round(book, 2)})
    return ok({"annual_depreciation": round(annual, 2), "schedule": schedule})


@endpoint()
def depreciation_ddb(request):
    """F06. 双倍余额递减法折旧。"""
    cost = req_num(request, "cost", minimum=0)
    salvage = opt_num(request, "salvage", default=0, minimum=0)
    life = int(req_num(request, "life_years", minimum=1))
    rate = 2.0 / life
    schedule = []
    book = cost
    for y in range(1, life + 1):
        dep = book * rate
        # 最后两年切换直线法（简化：不低于残值）
        if book - dep < salvage:
            dep = book - salvage
        book -= dep
        schedule.append({"year": y, "depreciation": round(dep, 2),
                         "book_value": round(book, 2)})
    return ok({"schedule": schedule})


@endpoint()
def depreciation_syd(request):
    """F07. 年数总和法折旧。"""
    cost = req_num(request, "cost", minimum=0)
    salvage = opt_num(request, "salvage", default=0, minimum=0)
    life = int(req_num(request, "life_years", minimum=1))
    syd = life * (life + 1) / 2.0
    depreciable = cost - salvage
    schedule = []
    book = cost
    for y in range(1, life + 1):
        dep = depreciable * (life - y + 1) / syd
        book -= dep
        schedule.append({"year": y, "depreciation": round(dep, 2),
                         "book_value": round(book, 2)})
    return ok({"schedule": schedule})


# 中国综合所得年度税率表（应纳税所得额 = 年收入 - 60000 起征点 - 专项附加等）
_IIT_BRACKETS = [
    (36000, 0.03, 0),
    (144000, 0.10, 2520),
    (300000, 0.20, 16920),
    (420000, 0.25, 31920),
    (660000, 0.30, 52920),
    (960000, 0.35, 85920),
    (float("inf"), 0.45, 181920),
]


@endpoint()
def income_tax_cn(request):
    """F08. 中国个人所得税（综合所得年度累进，简化版）。

    income: 全年税前收入；deduction: 专项扣除+附加扣除合计（可选，默认 0）。
    起征点 60000/年。
    """
    income = req_num(request, "income", minimum=0)
    deduction = opt_num(request, "deduction", default=0, minimum=0)
    taxable = max(0.0, income - 60000 - deduction)
    for upper, rate, quick in _IIT_BRACKETS:
        if taxable <= upper:
            tax = max(0.0, taxable * rate - quick)
            return ok({
                "taxable_income": round(taxable, 2),
                "rate_pct": round(rate * 100, 2),
                "quick_deduction": quick,
                "tax": round(tax, 2),
                "after_tax": round(income - tax, 2),
                "effective_rate_pct": round(tax / income * 100, 2) if income else 0,
            })
    raise ValueError("税级计算异常")


@endpoint()
def npv(request):
    """F09. 净现值 NPV。cashflows[0] 为期初投入（应为负）。"""
    rate = req_num(request, "rate", minimum=0)
    flows = req_list(request, "cashflows")
    r = rate / 100.0
    total = 0.0
    for t, cf in enumerate(flows):
        total += float(cf) / ((1 + r) ** t)
    return ok({"npv": round(total, 2)})


@endpoint()
def irr(request):
    """F10. 内部收益率 IRR（二分法，cashflows[0] 为期初投入）。"""
    flows = req_list(request, "cashflows")
    if len(flows) < 2:
        raise ValueError("至少需要两期现金流")
    fv = [float(x) for x in flows]
    if fv[0] >= 0:
        raise ValueError("第一期现金流应为负（期初投入）")

    def npv_at(rate):
        return sum(cf / ((1 + rate) ** t) for t, cf in enumerate(fv))

    lo, hi = -0.99, 10.0
    flo = npv_at(lo)
    fhi = npv_at(hi)
    if flo * fhi > 0:
        return ok({"irr_pct": None, "note": "在 [-99%, 1000%] 区间未找到 IRR"})
    for _ in range(200):
        mid = (lo + hi) / 2.0
        fm = npv_at(mid)
        if abs(fm) < 1e-7:
            break
        if flo * fm < 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    irr = (lo + hi) / 2.0
    return ok({"irr_pct": round(irr * 100, 4)})


@endpoint()
def credit_card_interest(request):
    """F11. 信用卡循环利息：日息万分之五，按月复利。"""
    balance = req_num(request, "balance", minimum=0)
    days = int(req_num(request, "days", minimum=1))
    daily_rate = 0.0005
    interest = balance * daily_rate * days
    return ok({
        "daily_rate_pct": 0.05,
        "interest": round(interest, 2),
        "total_due": round(balance + interest, 2),
        "annualized_pct": round(daily_rate * 365 * 100, 2),
    })


@endpoint()
def dca_return(request):
    """F12. 定投收益：每月固定投入 monthly，n 年后最终价值 final_value，求年化。"""
    monthly = req_num(request, "monthly", minimum=0)
    years = req_num(request, "years", minimum=0)
    final = req_num(request, "final_value", minimum=0)
    n = int(round(years * 12))
    if n <= 0:
        raise ValueError("年限需大于 0")
    total_in = monthly * n
    profit = final - total_in
    # 简化年化：资金平均占用约一半时间
    avg_capital = total_in / 2.0 if years > 0 else total_in
    annualized = (profit / avg_capital / years * 100.0) if years > 0 else 0.0
    return ok({
        "total_invested": round(total_in, 2),
        "final_value": round(final, 2),
        "profit": round(profit, 2),
        "annualized_pct_simple": round(annualized, 2),
    })


@endpoint()
def brokerage_fee(request):
    """F13. A 股交易手续费：佣金(最低5元,默认万2.5)+印花税(卖出0.05%)+过户费(0.001%)。"""
    price = req_num(request, "price", minimum=0)
    shares = int(req_num(request, "shares", minimum=1))
    side = p(request, "side", "buy")
    commission_rate = opt_num(request, "commission_rate", default=0.025) / 100.0
    amount = price * shares
    commission = max(5.0, amount * commission_rate)
    transfer_fee = amount * 0.00001
    stamp_tax = amount * 0.0005 if side == "sell" else 0.0
    total = commission + transfer_fee + stamp_tax
    return ok({
        "amount": round(amount, 2),
        "commission": round(commission, 2),
        "transfer_fee": round(transfer_fee, 2),
        "stamp_tax": round(stamp_tax, 2),
        "total_fee": round(total, 2),
        "fee_pct": round(total / amount * 100, 4) if amount else 0,
    })


@endpoint()
def inflation_adjust(request):
    """F14. 通胀调整：今天 X 元在 n 年后相当于今天多少购买力。"""
    amount = req_num(request, "amount", minimum=0)
    inflation = req_num(request, "inflation", minimum=0)
    years = req_num(request, "years", minimum=0)
    real = amount / ((1 + inflation / 100.0) ** years)
    return ok({"today_equivalent": round(real, 2),
               "lost_value": round(amount - real, 2)})


@endpoint()
def rule_of_72(request):
    """F15. 72 法则：本金翻倍所需年数 ≈ 72 / 年化收益率%。"""
    rate = req_num(request, "annual_rate", minimum=0.0001)
    years = 72.0 / rate
    return ok({"double_years": round(years, 2),
               "triple_years": round(111.0 / rate, 2)})


@endpoint()
def max_loan(request):
    """F16. 按月供反推可贷额度（等额本息）。"""
    monthly_payment = req_num(request, "monthly_payment", minimum=0)
    annual_rate = req_num(request, "annual_rate", minimum=0)
    months = int(req_num(request, "months", minimum=1))
    r = _rate_month(annual_rate)
    if r == 0:
        p = monthly_payment * months
    else:
        p = monthly_payment * (1 - (1 + r) ** (-months)) / r
    return ok({"max_principal": round(p, 2)})
