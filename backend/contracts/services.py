# -*- coding: utf-8 -*-
"""contracts 服务层：渲染 / 排期 / 扫描 / 评分 / 路由 / 指纹 / 财务 / 对比 / 健康度 / 组合统计。

分层原因：
- 这十件事都会被多个接口复用（例如到期扫描既服务定时任务也服务台账提醒），
  放进视图就会出现两份实现，迟早不一致；
- 全部是纯计算 + 受控写入，单独成层可以用最少的用例覆盖最关键的规则；
- 多表写入一律包 transaction.atomic()：排期生成、签署、续约确认都要么全成要么全败，
  否则会出现「期次生成一半」「签署记录有了但合同状态没变」这类脏数据。

时间与幂等约定：
- 时间统一由 `today()` 提供，测试可 patch；
- 扫描类接口可重复调用：提醒靠 dedupe_key 唯一约束、排期靠 series_uid 唯一约束，
  不依赖「调用方保证只调一次」这种不可验证的承诺。
"""
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from contracts import state
from contracts.common import parse_day
from contracts.models import (CONTRACT_TYPE_LABELS, CONTRACT_TYPE_WEIGHT,
                              EXPIRY_REMIND_STAGES, Contract,
                              ContractObligation, ContractPayment,
                              ContractReminder, ContractVersion, gen_series_uid,
                              to_decimal)

# 变量占位符：{{ name }} / {{ name | 默认值 }}；只允许标识符，避免把表达式注入正文
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(?:\|\s*([^{}]*?)\s*)?\}\}")

# 条款风险关键词：合同正文里出现这些表述时，即使没登记风险项也要计入条款风险分。
# 词表刻意保持小而准，靠的是「命中即提示复核」而不是自动判责。
CLAUSE_RISK_KEYWORDS = {
    "无限责任": 12,
    "不可撤销": 8,
    "自动续约": 6,
    "单方解除": 10,
    "违约金": 6,
    "排他": 8,
    "最惠国": 6,
    "连带责任": 10,
    "概不退款": 6,
    "放弃抗辩": 8,
}

# 金额分档（元）：分档依据是「审批层级」而不是「赔付上限」，
# 与 build_approval_route 的阈值保持一致，方便业务方用一句话解释风险分来源。
AMOUNT_BANDS = (
    (Decimal("100000"), 8, "10 万以下"),
    (Decimal("1000000"), 18, "10 万 - 100 万"),
    (Decimal("5000000"), 32, "100 万 - 500 万"),
    (None, 48, "500 万以上"),
)

APPROVAL_THRESHOLDS = (
    (Decimal("100000"), 1, "10 万以下"),
    (Decimal("1000000"), 2, "10 万 - 100 万"),
    (Decimal("5000000"), 3, "100 万 - 500 万"),
    (None, 4, "500 万以上"),
)


def today():
    """统一「今天」：时区本地日期，测试可 monkeypatch 固定时钟。"""
    return timezone.localdate()


# ---------------------------------------------------------------------------
# ① 条款变量渲染
# ---------------------------------------------------------------------------


def declared_variables(template):
    """从模板 variables 定义中提取 {name: 默认值}；兼容字符串与字典两种历史形态。"""
    # render_body 内部只传 {"variables": [...]}，服务层调用方传模板实例，两种都接受
    variables = template.get("variables") if isinstance(template, dict) else template.variables
    declared = {}
    for item in variables or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                declared[name] = item.get("default", "")
        else:
            name = str(item or "").strip()
            if name:
                declared[name] = ""
    return declared


def render_body(body, variables, values, strict=True):
    """渲染正文中的 {{变量}} 占位符，返回 (正文, 使用情况)。

    strict=True 时的规则（白名单 + 缺失报错）：
    1. 占位符名必须出现在「模板声明 ∪ 调用方显式传入」的集合里，
       否则视为模板里写错了变量名 —— 直接报错，不静默留空；
    2. 声明了但没传值的变量，若有默认值用默认值，没有则报错；
    3. 支持 {{ name | 默认值 }} 内联默认值，优先级高于 variables 中的默认值；
    4. 不在白名单里的变量绝不从任意上下文取值，杜绝把 request/环境变量渲染进合同。
    """
    provided = {str(k): v for k, v in (values or {}).items()}
    declared = declared_variables({"variables": variables})
    # 白名单只认模板声明：传了未声明的变量说明调用方写错名字，宁可报错也不静默忽略
    unknown = sorted(set(provided) - set(declared))
    if strict and unknown:
        raise ValueError(f"模板变量未在变量定义中声明: {'、'.join(unknown)}")
    whitelist = set(declared)
    used, missing, resolved = [], [], {}

    def replace(match):
        name = match.group(1)
        inline_default = match.group(2)
        if name not in whitelist:
            raise ValueError(f"模板变量未在变量定义中声明: {name}")
        if name in provided and provided[name] not in (None, ""):
            value = provided[name]
        elif inline_default is not None:
            value = inline_default
        else:
            defaults = declared_variables({"variables": variables})
            if name in defaults:
                # 声明过即视为有默认值（空串也是合法默认，例如可选补充条款）
                value = defaults[name] or ""
            elif strict and name not in provided:
                if name not in missing:
                    missing.append(name)
                return match.group(0)
            else:
                value = ""
        used.append(name)
        resolved[name] = "" if value is None else str(value)
        return "" if value is None else str(value)

    rendered = PLACEHOLDER_RE.sub(replace, body or "")
    if missing:
        raise ValueError(f"缺少模板变量取值: {'、'.join(missing)}")
    return rendered, {"used": sorted(set(used)), "resolved": resolved}


def render_template(template, values=None, strict=True):
    """按模板元数据渲染：先校验必填变量，再渲染正文并统计剩余占位符。"""
    values = dict(values or {})
    declared = declared_variables(template)
    if strict:
        absent = [name for name in template.required_variables()
                  if name not in values and declared.get(name) in (None, "")]
        if absent:
            raise ValueError(f"缺少必填模板变量: {'、'.join(absent)}")
    rendered, meta = render_body(template.body, template.variables or [], values, strict)
    leftovers = [m.group(1) for m in PLACEHOLDER_RE.finditer(rendered)]
    return {
        "template_id": template.id,
        "version": template.version,
        "body": rendered,
        "used": meta["used"],
        "resolved": meta["resolved"],
        "unresolved": sorted(set(leftovers)),
        "length": len(rendered),
    }


def build_contract_body(template, values):
    """用模板 + 变量拼出合同正文（起草合同时写首个版本快照）。"""
    return render_template(template, values)["body"]


# ---------------------------------------------------------------------------
# ② 义务排期生成（幂等）
# ---------------------------------------------------------------------------


def month_add(day, months):
    """月份加法：保持「几号」，遇到月末自动回退（1/31 + 1 月 → 2/28）。

    合同排期最怕生成出「2 月 31 日」这种非法日期，所以按目标月的实际天数裁剪。
    """
    if not day:
        return None
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    # 目标月天数：下个月 1 号向前退一天，闰年自然正确
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def cycle_months(cycle):
    """周期 → 月步长：once 返回 0（不展开），未知周期直接报错。"""
    mapping = {"monthly": 1, "quarterly": 3, "yearly": 12}
    if cycle == "once":
        return 0
    if cycle not in mapping:
        raise ValueError(f"不支持的履约周期: {cycle}")
    return mapping[cycle]


def ensure_series_uid(obligation):
    """给根义务补一个稳定 uid：历史数据可能没有，补完才能参与幂等约束。"""
    if not obligation.series_uid:
        obligation.series_uid = gen_series_uid("series")
        obligation.save(update_fields=["series_uid"])
    return obligation.series_uid


def generate_obligation_schedule(contract, periods=4, start_date=None, user=None):
    """按周期生成未来 N 期义务，返回 (新建行, 跳过数)。

    幂等做法：期次的 series_uid = "{根uid}#{date}"，配合
    (contract, series_uid) 唯一约束，重复调用只会命中已有行并计入 skipped。
    只从 due_date / start_date / 今天三者中取起点，避免凭空造出过期期次。
    """
    if periods <= 0:
        raise ValueError("生成期数必须大于 0")
    if periods > 60:
        raise ValueError("单次最多生成 60 期")
    created, skipped = [], 0
    base = start_date or contract.effective_date or today()
    for root in contract.obligations.filter(cycle__in=("monthly", "quarterly", "yearly"),
                                            recurring_from__isnull=True):
        uid = ensure_series_uid(root)
        step = cycle_months(root.cycle)
        anchor = root.due_date or base
        with transaction.atomic():
            for index in range(1, periods + 1):
                due = month_add(anchor, step * index)
                series = f"{uid}#{due.isoformat()}"
                exists = ContractObligation.objects.filter(
                    contract=contract, series_uid=series).exists()
                if exists:
                    skipped += 1
                    continue
                try:
                    row = ContractObligation.objects.create(
                        owner=user or contract.owner,
                        contract=contract,
                        party=root.party,
                        party_name=root.party_name,
                        content=root.content,
                        trigger=root.trigger,
                        cycle=root.cycle,
                        due_date=due,
                        responsible=root.responsible,
                        responsible_name=root.responsible_name,
                        status="pending",
                        priority=root.priority,
                        series_uid=series,
                        recurring_from=root,
                        remark=f"由排期 #{root.id} 自动生成",
                    )
                except IntegrityError:
                    # 并发下另一个请求刚插入同一期次：唯一约束兜底，按跳过处理
                    skipped += 1
                    continue
                created.append(row)
    if created:
        state.log_transition(contract, "obligation", user,
                             f"生成 {len(created)} 期履约排期",
                             contract.status, contract.status,
                             {"created": [row.id for row in created]})
    return created, skipped


def sweep_overdue_obligations(contract, user=None, today_date=None):
    """把「截止日已过且未完成」的义务标记为 overdue，返回被改动的行。

    这里不写履约事件：逾期是系统判定而非人工动作，写事件会污染人工操作时间线，
    真正的人工动作（完成/延期/豁免）才写 ObligationEvent。
    """
    today_date = today_date or today()
    changed = []
    rows = contract.obligations.filter(due_date__lt=today_date,
                                       status__in=("pending", "doing"))
    for row in rows:
        row.status = "overdue"
        row.touch()
        row.save(update_fields=["status", "updated_at"])
        changed.append(row)
    return changed


# ---------------------------------------------------------------------------
# ③ 到期 / 续约扫描（分段提醒，幂等）
# ---------------------------------------------------------------------------


def reminder_dedupe_key(contract, kind, stage, target):
    """去重键：合同 + 类型 + 阈值 + 目标日期，同一个提醒永远不会重复推送。"""
    return f"c{contract.id}:{kind}:{stage}:{target.isoformat() if target else '-'}"


def create_reminder(contract, kind, stage, message, target=None, channel="inapp",
                    owner=None):
    """写一条提醒（幂等）；已存在返回 (None, False)。"""
    key = reminder_dedupe_key(contract, kind, stage, target)
    if ContractReminder.objects.filter(dedupe_key=key).exists():
        return None, False
    try:
        row = ContractReminder.objects.create(
            owner=owner or contract.owner,
            contract=contract,
            kind=kind,
            stage=stage,
            channel=channel,
            status="sent",
            message=message,
            target_date=target,
            dedupe_key=key,
        )
    except IntegrityError:
        return None, False
    return row, True


def expiry_stage_for(days):
    """命中的最紧提醒档位：剩 3 天时只补发「7 天档」，不会把 30/15/7 全补一遍。

    已过期的合同（days < 0）不再归入任何提醒档位：到期提醒的义务是「提前告知」，
    过期后应由逾期/续约扫描接管，否则每次扫描都会重复命中 1 天档。
    """
    if days is None or days < 0:
        return None
    hits = [stage for stage in EXPIRY_REMIND_STAGES if days <= stage]
    return min(hits) if hits else None


def scan_contract_expiry(contract, days=None, channel="inapp", user=None):
    """扫描单份合同：更新临期/到期状态，并按档位补提醒。"""
    days = days if days is not None else contract.days_to_expiry()
    out = {"contract_id": contract.id, "days_to_expiry": days,
           "status_before": contract.status, "status_after": contract.status,
           "reminder": None, "reminder_created": False}
    if days is None:
        return out
    if contract.status in ("active", "expiring"):
        if days < 0:
            state.force_status(contract, "expired", user,
                               f"合同已到期 {abs(days)} 天", action="expire")
        elif days <= 30:
            state.force_status(contract, "expiring", None,
                               f"距到期 {days} 天，转为临期", action="mark_expiring")
        out["status_after"] = contract.status
    stage = expiry_stage_for(days)
    if stage is not None and contract.status not in ("terminated", "completed",
                                                     "archived", "draft"):
        message = f"合同《{contract.name}》距到期还有 {days} 天，请及时跟进续约或收尾"
        row, created = create_reminder(contract, "expiry", stage, message,
                                       contract.expire_date, channel)
        out["reminder"] = row.id if row else None
        out["reminder_created"] = created
    return out


def scan_expiry(contracts, channel="inapp", user=None, mark_status=True):
    """批量到期扫描：返回统计 + 每份合同的明细。

    mark_status=False 时只统计不写库，供前端「预演」用。
    """
    items = []
    marked_expiring = marked_expired = reminders = 0
    for contract in contracts:
        days = contract.days_to_expiry()
        before = contract.status
        if mark_status:
            result = scan_contract_expiry(contract, days, channel, user)
            after = result["status_after"]
            reminders += 1 if result["reminder_created"] else 0
        else:
            after = before
            stage = expiry_stage_for(days) if days is not None else None
            result = {"reminder": None, "reminder_created": False}
            if days is not None and days < 0:
                after = "expired"
            elif days is not None and days <= 30 and before == "active":
                after = "expiring"
            if stage is not None:
                result["reminder"] = None
        if after == "expiring" and before != "expiring":
            marked_expiring += 1
        if after == "expired" and before != "expired":
            marked_expired += 1
        items.append({
            "contract_id": contract.id,
            "number": contract.number,
            "name": contract.name,
            "status": after,
            "days_to_expiry": days,
            "stage": expiry_stage_for(days) if days is not None else None,
            "reminder_created": result["reminder_created"],
        })
    items.sort(key=lambda row: (row["days_to_expiry"] is None,
                                row["days_to_expiry"] if
                                row["days_to_expiry"] is not None else 0))
    return {
        "scanned": len(items),
        "marked_expiring": marked_expiring,
        "marked_expired": marked_expired,
        "reminders_created": reminders,
        "items": items,
    }


def scan_renewal_reminders(contracts, user=None, channel="inapp"):
    """续约提醒：按续约记录上的 remind_days 提前提醒，已确认的不再提醒。"""
    created = 0
    items = []
    for contract in contracts:
        days = contract.days_to_expiry()
        if days is None:
            continue
        for renewal in contract.renewals.filter(status="pending"):
            if days > renewal.remind_days:
                continue
            message = (f"合同《{contract.name}》的续约跟进还剩 {days} 天"
                       f"（提醒阈值 {renewal.remind_days} 天）")
            row, ok = create_reminder(contract, "renewal", renewal.remind_days,
                                      message, contract.expire_date, channel)
            created += 1 if ok else 0
            items.append({"contract_id": contract.id, "renewal_id": renewal.id,
                          "days_to_expiry": days,
                          "reminder_id": row.id if row else None,
                          "created": ok})
    return {"created": created, "items": items}


# ---------------------------------------------------------------------------
# ④ 风险评分
# ---------------------------------------------------------------------------


def amount_band(amount):
    """金额分档 → (分值, 档位名)。"""
    value = to_decimal(amount)
    for limit, score, label in AMOUNT_BANDS:
        if limit is None or value <= limit:
            return score, label
    return 48, "500 万以上"


def scan_clause_keywords(text):
    """条款正文关键词扫描 → 命中列表（词 + 分值），用于解释风险分来源。"""
    hits = []
    for word, weight in CLAUSE_RISK_KEYWORDS.items():
        count = (text or "").count(word)
        if count:
            hits.append({"keyword": word, "weight": weight, "count": count,
                         "score": weight * min(count, 3)})
    return hits


def counterparty_history_score(contract):
    """相对方历史：同一相对方「终止/到期」合同越多，续签风险越高。"""
    name = (contract.counterparty_name or "").strip()
    if not name:
        return 0, 0
    count = (Contract.objects
             .filter(counterparty_name=name, status__in=("terminated", "expired"))
             .exclude(pk=contract.pk).count())
    return min(count * 5, 15), count


def score_risk(contract, persist=True, today_date=None):
    """五维风险评分：金额 / 类型 / 条款 / 履约 / 相对方，输出分项明细。

    分项都设了上限，保证任何单一维度不会吃掉全部分数：
    这样「金额大但履约良好」与「金额小但条款恶劣」能被区分开。
    """
    today_date = today_date or today()
    amount_score, band_label = amount_band(contract.amount)
    type_score = CONTRACT_TYPE_WEIGHT.get(contract.contract_type, 10)

    # 条款维度：登记的风险项 + 正文关键词，取「风险项权重」与「关键词分」的较大者，
    # 避免同一风险被登记项和正文关键词各算一遍导致重复计分。
    risks = list(contract.risks.all())
    risk_item_score = sum(row.weight() for row in risks)
    body = ""
    if contract.current_version_id:
        body = contract.current_version.body_snapshot or ""
    keyword_hits = scan_clause_keywords(body)
    keyword_score = min(sum(hit["score"] for hit in keyword_hits), 40)
    clause_score = min(max(risk_item_score, keyword_score), 40)

    # 履约维度：逾期义务 8 分/条（上限 24），逾期付款期次 6 分/条（上限 18）
    overdue_obligations = [row for row in contract.obligations.all()
                           if row.is_overdue(today_date)]
    if not overdue_obligations:
        overdue_obligations = list(contract.obligations.filter(status="overdue"))
    performance_score = min(len(overdue_obligations) * 8, 24)
    overdue_payments = [row for row in contract.payments.all()
                        if row.is_overdue(today_date)]
    performance_score += min(len(overdue_payments) * 6, 18)
    performance_score = min(performance_score, 40)

    history_score, history_count = counterparty_history_score(contract)
    total = min(amount_score + type_score + clause_score + performance_score
                + history_score, 100)
    level = ("critical" if total >= 75 else "high" if total >= 55
             else "medium" if total >= 35 else "low")
    breakdown = {
        "amount": {"score": amount_score, "band": band_label,
                   "amount": f"{to_decimal(contract.amount):.2f}"},
        "type": {"score": type_score,
                 "type": contract.contract_type,
                 "label": CONTRACT_TYPE_LABELS.get(contract.contract_type,
                                                   contract.contract_type)},
        "clause": {"score": clause_score,
                   "risk_items": [{"id": row.id, "title": row.title,
                                   "level": row.level,
                                   "weight": row.weight()} for row in risks],
                   "keyword_hits": keyword_hits},
        "performance": {"score": performance_score,
                        "overdue_obligations": len(overdue_obligations),
                        "overdue_payments": len(overdue_payments)},
        "counterparty": {"score": history_score,
                         "previous_terminated": history_count,
                         "name": contract.counterparty_name},
    }
    if persist:
        contract.risk_score = total
        contract.touch()
        contract.save(update_fields=["risk_score", "updated_at"])
    return {"total": total, "level": level, "breakdown": breakdown}


# ---------------------------------------------------------------------------
# ⑤ 审批路由
# ---------------------------------------------------------------------------


def amount_band_label(amount):
    """金额所属审批档位（1-4），供路由与前端展示复用。"""
    value = to_decimal(amount)
    for limit, level, label in APPROVAL_THRESHOLDS:
        if limit is None or value <= limit:
            return level, label
    return 4, "500 万以上"


def build_approval_route(amount, contract_type="service"):
    """按金额阈值决定审批节点序列（纯函数，便于测试）。

    节点设计：
    - 10 万以下：部门主管；
    - 10 万 - 100 万：+ 法务；
    - 100 万 - 500 万：+ 财务总监；
    - 500 万以上：+ 总经理；
    - 租赁 / 劳务类无论金额都追加法务（用工与场地条款更容易踩合规线）。
    """
    level, band_label = amount_band_label(amount)
    route = [
        {"node": 1, "name": "部门主管", "threshold": "10 万以下"},
        {"node": 2, "name": "法务审核", "threshold": "10 万 - 100 万"},
        {"node": 3, "name": "财务总监", "threshold": "100 万 - 500 万"},
        {"node": 4, "name": "总经理", "threshold": "500 万以上"},
    ][:level]
    names = [row["name"] for row in route]
    if contract_type in ("lease", "labor") and "法务审核" not in names:
        route.append({"node": len(route) + 1, "name": "法务审核",
                      "threshold": "租赁/劳务强制"})
    return {"band": level, "band_label": band_label,
            "amount": f"{to_decimal(amount):.2f}", "nodes": route}


# ---------------------------------------------------------------------------
# ⑥ 签署指纹
# ---------------------------------------------------------------------------


def signature_payload(contract, signer_name, signed_at):
    """指纹原文：合同编号 + 正文 + 签署人 + 时间，四者任一变化指纹就变。"""
    body = ""
    if contract.current_version_id:
        body = contract.current_version.body_snapshot or ""
    stamp = signed_at.isoformat() if hasattr(signed_at, "isoformat") else str(signed_at)
    return f"{contract.number}|{body}|{signer_name}|{stamp}"


def sign_fingerprint(contract, signer_name, signed_at):
    """sha256(合同正文 + 签署人 + 签署时间)，只做指纹与状态模拟，不接第三方 CA。"""
    payload = signature_payload(contract, signer_name, signed_at)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_fingerprint(signature):
    """校验已有签署记录是否仍与当前正文一致（正文被改过会返回 False）。"""
    expected = sign_fingerprint(signature.contract, signature.signer_name,
                                signature.signed_at)
    return bool(signature.hash_fingerprint) and expected == signature.hash_fingerprint


# ---------------------------------------------------------------------------
# ⑦ 财务汇总
# ---------------------------------------------------------------------------


def empty_money():
    """金额累加器：统一两位小数，避免 Decimal 不同精度相加报错。"""
    return Decimal("0.00")


def finance_summary(contracts, today_date=None):
    """合同财务汇总：总/已付/未付/逾期，并按币种拆分。

    跨币种直接相加没有业务意义，所以总量只统计 CNY 之外时给出 by_currency
    明细，同时给出 overall（= 全部币种按面值相加，仅用于数量级参考）。
    """
    today_date = today_date or today()
    by_currency = {}
    overall = {
        "contract_amount": empty_money(),
        "planned_amount": empty_money(),
        "paid_amount": empty_money(),
        "unpaid_amount": empty_money(),
        "overdue_amount": empty_money(),
        "payment_count": 0,
        "paid_periods": 0,
        "overdue_periods": 0,
    }
    contract_count = 0
    for contract in contracts:
        contract_count += 1
        bucket = by_currency.setdefault(contract.currency, {
            "currency": contract.currency,
            "contracts": 0,
            "contract_amount": empty_money(),
            "planned_amount": empty_money(),
            "paid_amount": empty_money(),
            "unpaid_amount": empty_money(),
            "overdue_amount": empty_money(),
            "payment_count": 0,
        })
        payments = list(contract.payments.all())
        paid = contract.paid_amount(payments)
        planned = contract.planned_amount(payments)
        unpaid = contract.unpaid_amount(payments)
        overdue = contract.overdue_amount(payments, today_date)
        bucket["contracts"] += 1
        bucket["contract_amount"] += to_decimal(contract.amount)
        bucket["planned_amount"] += planned
        bucket["paid_amount"] += paid
        bucket["unpaid_amount"] += unpaid
        bucket["overdue_amount"] += overdue
        bucket["payment_count"] += len(payments)
        overall["contract_amount"] += to_decimal(contract.amount)
        overall["planned_amount"] += planned
        overall["paid_amount"] += paid
        overall["unpaid_amount"] += unpaid
        overall["overdue_amount"] += overdue
        overall["payment_count"] += len(payments)
        overall["paid_periods"] += sum(1 for row in payments if row.status == "paid")
        overall["overdue_periods"] += sum(1 for row in payments
                                          if row.is_overdue(today_date))

    def _dump(bucket):
        out = dict(bucket)
        for key in ("contract_amount", "planned_amount", "paid_amount",
                    "unpaid_amount", "overdue_amount"):
            out[key] = f"{to_decimal(out.get(key)):.2f}"
        planned = to_decimal(bucket.get("planned_amount"))
        paid = to_decimal(bucket.get("paid_amount"))
        out["collection_rate"] = (round(float(paid / planned) * 100, 1)
                                  if planned > 0 else 0.0)
        return out

    return {
        "contract_count": contract_count,
        "overall": _dump(overall),
        "by_currency": sorted((_dump(row) for row in by_currency.values()),
                              key=lambda row: row["currency"]),
    }


def payment_overdue_stats(contracts, today_date=None):
    """付款逾期统计：逾期期次数 / 逾期额 / 最长逾期天数 / 明细。"""
    today_date = today_date or today()
    items = []
    total = empty_money()
    for contract in contracts:
        for row in contract.payments.all():
            if not row.is_overdue(today_date):
                continue
            days = (today_date - row.plan_date).days if row.plan_date else 0
            total += row.remaining()
            items.append({
                "payment_id": row.id,
                "contract_id": contract.id,
                "contract_number": contract.number,
                "currency": contract.currency,
                "period_no": row.period_no,
                "plan_amount": f"{to_decimal(row.plan_amount):.2f}",
                "remaining": f"{row.remaining():.2f}",
                "plan_date": row.plan_date.isoformat() if row.plan_date else None,
                "overdue_days": days,
            })
    items.sort(key=lambda row: -row["overdue_days"])
    return {
        "count": len(items),
        "overdue_total": f"{total:.2f}",
        "max_overdue_days": items[0]["overdue_days"] if items else 0,
        "items": items[:200],
    }


# ---------------------------------------------------------------------------
# ⑧ 版本对比（条款级 diff）
# ---------------------------------------------------------------------------

CLAUSE_HEADING_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零〇0-9]+条[^\n]*|[【\[][^】\]]{1,40}[】\]])\s*$",
    re.MULTILINE)


def split_clauses(body):
    """把正文按「第 X 条 / 【标题】」切分成 [(标题, 正文)]。

    没有识别到标题时退化为「非空行」粒度：这样对比至少能定位到具体句子，
    而不是给出「整篇都变了」这种无用结论。
    """
    text = (body or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    matches = list(CLAUSE_HEADING_RE.finditer(text))
    if not matches:
        return [(f"行 {index + 1}", line.strip()) for index, line in
                enumerate(text.split("\n")) if line.strip()]
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(0).strip(), text[start:end].strip()))
    return sections


def diff_versions(old_body, new_body, max_items=200):
    """条款级 diff：按标题配对，输出新增/删除/修改/未变四条线与统计。

    只做「同标题条款内容是否变化」的判断，不做字符级 LCS：
    合同审阅关心的是「哪一条被改了」，逐字符 diff 噪音远大于信息量。
    """
    old_sections = split_clauses(old_body)
    new_sections = split_clauses(new_body)
    old_map = {title: body for title, body in old_sections}
    new_map = {title: body for title, body in new_sections}
    added, removed, modified, unchanged = [], [], [], []
    for title, body in new_sections:
        if title not in old_map:
            added.append({"title": title, "body": body})
        elif old_map[title] != body:
            modified.append({"title": title, "before": old_map[title],
                             "after": body,
                             "before_len": len(old_map[title]),
                             "after_len": len(body)})
        else:
            unchanged.append({"title": title})
    for title, body in old_sections:
        if title not in new_map:
            removed.append({"title": title, "body": body})
    changed = len(added) + len(removed) + len(modified)
    return {
        "summary": {
            "old_clauses": len(old_sections),
            "new_clauses": len(new_sections),
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "unchanged": len(unchanged),
            "changed": changed,
            "identical": changed == 0 and len(old_sections) == len(new_sections),
        },
        "added": added[:max_items],
        "removed": removed[:max_items],
        "modified": modified[:max_items],
        "unchanged_titles": [row["title"] for row in unchanged][:max_items],
    }


# ---------------------------------------------------------------------------
# ⑨ 履约健康度
# ---------------------------------------------------------------------------


def obligation_health(contract, today_date=None):
    """义务准时率：已完成义务里「完成事件时间 ≤ 截止日」的占比。"""
    today_date = today_date or today()
    rows = list(contract.obligations.exclude(cycle=""))
    if not rows:
        return {"score": 100.0, "total": 0, "on_time": 0, "late": 0,
                "overdue_open": 0}
    on_time = late = overdue_open = 0
    for row in rows:
        events = list(row.events.filter(action="complete").order_by("happened_at"))
        if row.status == "done":
            done_at = events[0].happened_at.date() if events else None
            if done_at and row.due_date and done_at > row.due_date:
                late += 1
            else:
                on_time += 1
        elif row.status == "overdue" or row.is_overdue(today_date):
            overdue_open += 1
    total = on_time + late + overdue_open
    score = (on_time * 100.0 / total) if total else 100.0
    return {"score": round(score, 1), "total": len(rows), "on_time": on_time,
            "late": late, "overdue_open": overdue_open}


def milestone_health(contract, today_date=None):
    """里程碑达成率：已达成 / 已到期（计划日已过）的里程碑。"""
    today_date = today_date or today()
    rows = list(contract.milestones.all())
    if not rows:
        return {"score": 100.0, "total": 0, "achieved": 0, "missed": 0,
                "due": 0}
    achieved = sum(1 for row in rows if row.status == "achieved")
    missed = sum(1 for row in rows if row.status == "missed")
    due = sum(1 for row in rows if row.plan_date and row.plan_date <= today_date)
    if not due:
        return {"score": 100.0 if achieved else 0.0, "total": len(rows),
                "achieved": achieved, "missed": missed, "due": due}
    return {"score": round(achieved * 100.0 / max(due, achieved + missed), 1),
            "total": len(rows), "achieved": achieved, "missed": missed,
            "due": due}


def payment_health(contract, today_date=None):
    """付款及时率：已结清期次中「实付日 ≤ 计划日」占比，逾期未付单独计数。"""
    today_date = today_date or today()
    rows = list(contract.payments.exclude(status="cancelled"))
    if not rows:
        return {"score": 100.0, "total": 0, "on_time": 0, "late": 0,
                "overdue_open": 0}
    on_time = late = overdue_open = 0
    for row in rows:
        if row.status == "paid" and row.paid_date and row.plan_date:
            if row.paid_date <= row.plan_date:
                on_time += 1
            else:
                late += 1
        elif row.status == "paid":
            on_time += 1
        elif row.is_overdue(today_date):
            overdue_open += 1
    total = on_time + late + overdue_open
    score = (on_time * 100.0 / total) if total else 100.0
    return {"score": round(score, 1), "total": len(rows), "on_time": on_time,
            "late": late, "overdue_open": overdue_open}


def health_score(contract, today_date=None):
    """履约健康度 = 义务准时率 45% + 里程碑达成率 25% + 付款及时率 30%。

    权重依据「合同纠纷发生频率」：履约义务最频繁、最容易出问题，占大头；
    里程碑与付款直接关联验收和现金流，权重次之。
    """
    today_date = today_date or today()
    obligations = obligation_health(contract, today_date)
    milestones = milestone_health(contract, today_date)
    payments = payment_health(contract, today_date)
    total = round(obligations["score"] * 0.45 + milestones["score"] * 0.25
                  + payments["score"] * 0.30, 1)
    level = ("excellent" if total >= 90 else "good" if total >= 75
             else "warning" if total >= 60 else "critical")
    weights = {"obligation": 0.45, "milestone": 0.25, "payment": 0.30}
    return {
        "score": total,
        "level": level,
        "components": {
            "obligations": {**obligations, "weight": weights["obligation"]},
            "milestones": {**milestones, "weight": weights["milestone"]},
            "payments": {**payments, "weight": weights["payment"]},
        },
    }


# ---------------------------------------------------------------------------
# ⑩ 组合统计
# ---------------------------------------------------------------------------


def portfolio_stats(contracts, today_date=None):
    """合同组合统计：按状态 / 类型 / 到期月份 / 负责人 / 币种。

    到期月份只看未来 12 个月，超过一年的合同按月分桶意义不大，
    统一归入 beyond_12m，避免前端时间轴被超长月份拉平。
    """
    today_date = today_date or today()
    by_status, by_type, by_month, by_owner, by_currency = {}, {}, {}, {}, {}
    amount_total = empty_money()
    risk_sum = 0
    for contract in contracts:
        by_status[contract.status] = by_status.get(contract.status, 0) + 1
        by_type[contract.contract_type] = by_type.get(contract.contract_type, 0) + 1
        by_currency[contract.currency] = (by_currency.get(contract.currency, 0) + 1)
        amount_total += to_decimal(contract.amount)
        risk_sum += int(contract.risk_score or 0)
        if contract.expire_date:
            months = ((contract.expire_date.year - today_date.year) * 12
                      + contract.expire_date.month - today_date.month)
            if months < 0:
                key = "expired"
            elif months <= 12:
                key = contract.expire_date.strftime("%Y-%m")
            else:
                key = "beyond_12m"
            by_month[key] = by_month.get(key, 0) + 1
        owner_name = getattr(contract.responsible, "username", "") or \
            getattr(contract.owner, "username", "")
        bucket = by_owner.setdefault(owner_name, {"owner": owner_name,
                                                 "count": 0, "amount": empty_money()})
        bucket["count"] += 1
        bucket["amount"] += to_decimal(contract.amount)
    total = sum(by_status.values())
    owner_rows = [{"owner": row["owner"], "count": row["count"],
                   "amount": f"{row['amount']:.2f}"}
                  for row in by_owner.values()]
    owner_rows.sort(key=lambda row: -row["count"])
    return {
        "total": total,
        "amount_total": f"{amount_total:.2f}",
        "avg_risk_score": round(risk_sum / total, 1) if total else 0.0,
        "by_status": by_status,
        "by_type": by_type,
        "by_currency": by_currency,
        "by_expire_month": dict(sorted(by_month.items())),
        "by_owner": owner_rows,
    }


# ---------------------------------------------------------------------------
# 版本 / 变更 / 快照（被多个视图复用）
# ---------------------------------------------------------------------------


def next_version_no(contract):
    """下一个版本号：用 Max 而不是 count，删过版本也不会撞唯一约束。"""
    from django.db.models import Max

    current = contract.versions.aggregate(value=Max("version_no"))["value"] or 0
    return current + 1


def create_version(contract, user, body, summary="", make_current=True):
    """写一个版本快照；make_current=True 时把旧版本的 is_current 清掉。

    必须在事务内调用：清旧当前版 + 建新版 + 回写 contract.current_version
    三步若分步失败，会出现「没有当前版本」或「两个当前版本」。
    """
    version_no = next_version_no(contract)
    if make_current:
        contract.versions.filter(is_current=True).update(is_current=False)
    version = ContractVersion.objects.create(
        owner=user or contract.owner,
        contract=contract,
        version_no=version_no,
        body_snapshot=body,
        change_summary=summary,
        created_by=user if getattr(user, "pk", None) else None,
        is_current=make_current,
    )
    if make_current:
        contract.current_version = version
        contract.touch()
        contract.save(update_fields=["current_version", "updated_at"])
    return version


def rollback_version(contract, version, user, note=""):
    """回滚到指定版本：不删历史，只把该版本内容复制成新版本。"""
    if version.contract_id != contract.id:
        raise ValueError("版本不属于该合同")
    with transaction.atomic():
        new_version = create_version(
            contract, user, version.body_snapshot,
            summary=note or f"回滚到版本 #{version.version_no}")
        state.log_transition(contract, "rollback", user,
                             f"回滚至版本 #{version.version_no}",
                             contract.status, contract.status,
                             {"source_version": version.version_no,
                              "new_version": new_version.version_no})
    return new_version


def apply_amendment(amendment, user):
    """变更单生效：按类型回写合同字段并生成新版本快照。

    金额变更用增量还是覆盖？这里约定 after_text 里放「新的完整值」，
    由视图层解析后传入，服务层只负责落库与留痕，避免文本解析规则散落。
    """
    contract = amendment.contract
    with transaction.atomic():
        if amendment.change_type == "amount":
            new_amount = to_decimal(getattr(amendment, "_new_amount", None)
                                    or amendment.after_text, "变更后金额")
            contract.amount = new_amount
        elif amendment.change_type == "date":
            new_date = getattr(amendment, "_new_expire_date", None)
            if new_date:
                contract.expire_date = new_date
        contract.touch()
        contract.save(update_fields=["amount", "expire_date", "updated_at"])
        if amendment.after_text:
            create_version(contract, user,
                           contract.current_version.body_snapshot
                           if contract.current_version_id
                           else amendment.after_text,
                           summary=f"变更单 {amendment.code} 生效")
        amendment.approval_status = "effective"
        amendment.decided_at = timezone.now()
        amendment.approved_by = user if getattr(user, "pk", None) else None
        amendment.touch()
        amendment.save(update_fields=["approval_status", "decided_at",
                                      "approved_by", "updated_at"])
        state.log_transition(contract, "update", user,
                             f"变更单 {amendment.code} 生效",
                             contract.status, contract.status,
                             {"amendment_id": amendment.id})
    return amendment


# ---------------------------------------------------------------------------
# 付款计划生成
# ---------------------------------------------------------------------------


def payment_plan_preview(amount, periods, ratios=None, first_date=None,
                         interval_days=30):
    """把合同金额拆成 N 期付款计划（纯计算）：支持等分或按比例，末期吸收尾差。

    金额必须按「先量化再补尾差」的方式分配：逐期 round 后总额会与合同金额差
    几分钱，财务对账时这笔差额没有归属。这里把差额全部压到最后一期，
    保证 sum(plan_amount) == amount 恒成立。
    """
    total = to_decimal(amount, "合同金额")
    count = int(periods)
    if count < 1 or count > 60:
        raise ValueError("付款期数必须在 1 到 60 之间")
    interval = int(interval_days)
    if interval < 1 or interval > 365:
        raise ValueError("付款间隔必须在 1 到 365 天之间")
    raw_ratios = []
    if ratios:
        if len(ratios) != count:
            raise ValueError("比例数量必须与期数一致")
        for item in ratios:
            value = to_decimal(item, "付款比例")
            if value <= 0:
                raise ValueError("付款比例必须大于 0")
            raw_ratios.append(value)
    else:
        raw_ratios = [Decimal("1")] * count
    ratio_sum = sum(raw_ratios)
    start = parse_day(first_date) if first_date else timezone.localdate()
    plan = []
    allocated = Decimal("0.00")
    for index, ratio in enumerate(raw_ratios):
        period_no = index + 1
        if period_no == count:
            share = total - allocated
        else:
            share = (total * ratio / ratio_sum).quantize(Decimal("0.01"))
            allocated += share
        plan.append({
            "period_no": period_no,
            "ratio": str((ratio / ratio_sum * 100).quantize(Decimal("0.01"))),
            "plan_amount": share,
            "plan_date": start + timedelta(days=interval * index),
        })
    return {
        "amount": total,
        "periods": count,
        "interval_days": interval,
        "first_date": start,
        "items": plan,
        "ratio_sum": str(ratio_sum),
    }


def build_payment_plan(contract, periods, ratios=None, first_date=None,
                       interval_days=30, user=None):
    """生成付款计划并落库：按 (合同, 期次) 幂等，重复调用只补缺失期次。

    不能覆盖已存在期次：财务可能已经在某期登记了实付，重新生成时把它改回
    计划额会让账实不符。因此已存在就跳过，由调用方决定是否先作废再重建。
    """
    preview = payment_plan_preview(contract.amount, periods, ratios, first_date,
                                   interval_days)
    created = skipped = 0
    rows = []
    today = timezone.localdate()
    with transaction.atomic():
        for item in preview["items"]:
            existing = ContractPayment.objects.filter(
                contract=contract, period_no=item["period_no"]).first()
            if existing is not None:
                skipped += 1
                rows.append(existing)
                continue
            row = ContractPayment.objects.create(
                owner=user or contract.owner,
                contract=contract,
                period_no=item["period_no"],
                plan_amount=item["plan_amount"],
                plan_date=item["plan_date"],
                status="planned",
                remark=f"系统生成（第 {item['period_no']}/{preview['periods']} 期，"
                       f"占比 {item['ratio']}%）",
            )
            row.sync_status(today)
            row.save(update_fields=["status"])
            created += 1
            rows.append(row)
        state.log_transition(contract, "update", user,
                             f"生成 {preview['periods']} 期付款计划，新增 {created} 期",
                             contract.status, contract.status,
                             {"created": created, "skipped": skipped})
    return {"created": created, "skipped": skipped, "rows": rows,
            "preview": preview}


# ---------------------------------------------------------------------------
# 续约窗口
# ---------------------------------------------------------------------------


def renewal_window(contracts, today=None, days=90):
    """续约窗口分析：按剩余天数分档，并给出「自动续约/需人工确认」的处置建议。

    只统计已生效且配置了续约方式的合同：草稿还没签，过期合同要走走期流程，
    把它们混进续约列表会让负责人每天看到一堆无法处理的条目。
    """
    today = today or timezone.localdate()
    horizon = today + timedelta(days=days)
    buckets = {"expired": [], "d7": [], "d30": [], "d60": [], "d90": []}
    for contract in contracts:
        if not contract.expire_date or contract.renewal_mode == "none":
            continue
        if contract.status not in ("active", "expiring", "expired"):
            continue
        left = (contract.expire_date - today).days
        if left < 0:
            buckets["expired"].append(contract)
        elif left <= 7:
            buckets["d7"].append(contract)
        elif left <= 30:
            buckets["d30"].append(contract)
        elif left <= 60:
            buckets["d60"].append(contract)
        elif contract.expire_date <= horizon:
            buckets["d90"].append(contract)
    items = []
    for key in ("expired", "d7", "d30", "d60", "d90"):
        for contract in buckets[key]:
            left = (contract.expire_date - today).days
            auto = contract.renewal_mode == "auto"
            items.append({
                "contract_id": contract.id,
                "number": contract.number,
                "name": contract.name,
                "status": contract.status,
                "renewal_mode": contract.renewal_mode,
                "expire_date": contract.expire_date,
                "days_left": left,
                "bucket": key,
                # 自动续约仍需人工复核金额与条款，只是提醒优先级更高
                "action": ("确认续约" if auto else "发起续约谈判")
                if left >= 0 else "补办续约或终止归档",
                "auto_renew": auto,
            })
    items.sort(key=lambda row: row["days_left"])
    return {
        "scanned": sum(len(value) for value in buckets.values()),
        "within_days": days,
        "buckets": {key: len(value) for key, value in buckets.items()},
        "auto_renew": sum(1 for row in items if row["auto_renew"]),
        "items": items,
    }


# ---------------------------------------------------------------------------
# 条款推荐
# ---------------------------------------------------------------------------


def suggest_clauses(rows, keyword="", risk_level="", contract_type="", limit=20):
    """条款推荐：关键字命中标题/正文/分类/标签，风险等级与合同类型作为加权项。

    排序不是「全文搜索」而是可解释的打分：命中位置越核心权重越高，
    返回 reason 让作者知道为什么被推荐，避免黑盒推荐被直接忽略。
    """
    keyword = (keyword or "").strip().lower()
    risk_level = (risk_level or "").strip()
    contract_type = (contract_type or "").strip()
    scored = []
    for row in rows:
        score = 1
        reasons = []
        title = (row.title or "").lower()
        body = (row.body or "").lower()
        category = (row.category or "").lower()
        tags = [str(item).lower() for item in (row.tags or [])]
        if keyword:
            if keyword in title:
                score += 6
                reasons.append("标题命中")
            if keyword in category:
                score += 4
                reasons.append("分类命中")
            if keyword in tags:
                score += 3
                reasons.append("标签命中")
            if keyword in body:
                score += 2
                reasons.append("正文命中")
            if not reasons:
                continue
        if risk_level and row.risk_level == risk_level:
            score += 2
            reasons.append("风险等级匹配")
        if contract_type and category and contract_type in category:
            score += 2
            reasons.append("适用合同类型")
        score += min(int(row.usage_count or 0), 10) // 2
        scored.append({
            "id": row.id,
            "title": row.title,
            "category": row.category,
            "risk_level": row.risk_level,
            "score": score,
            "reason": "、".join(reasons) or "库内常用条款",
            "body_preview": (row.body or "")[:120],
        })
    scored.sort(key=lambda item: (-item["score"], item["title"]))
    return scored[:max(1, int(limit))]


# ---------------------------------------------------------------------------
# 履约日历
# ---------------------------------------------------------------------------


def obligation_calendar(rows, today=None, months=6):
    """履约日历：把义务按截止月份聚合，输出每月待办/完成/逾期数量。

    日历视图需要「先看量再看条目」，所以按月给出汇总，并只附前 5 条
    最近到期的义务；完整明细仍走 obligations 列表，避免一次返回上千条。
    """
    today = today or timezone.localdate()
    limit_month = today.replace(day=1) + timedelta(days=31 * max(1, int(months)))
    buckets = {}
    for row in rows:
        if not row.due_date:
            continue
        if row.due_date < today - timedelta(days=31 * 12):
            continue
        if row.due_date > limit_month:
            continue
        key = row.due_date.strftime("%Y-%m")
        bucket = buckets.setdefault(key, {
            "month": key,
            "total": 0,
            "pending": 0,
            "done": 0,
            "overdue": 0,
            "items": [],
        })
        bucket["total"] += 1
        if row.status == "done":
            bucket["done"] += 1
        elif row.status == "overdue" or row.is_overdue(today):
            bucket["overdue"] += 1
        else:
            bucket["pending"] += 1
        if len(bucket["items"]) < 5:
            bucket["items"].append({
                "id": row.id,
                "content": row.content[:40],
                "due_date": row.due_date,
                "status": row.status,
                "priority": row.priority,
            })
    result = []
    for key in sorted(buckets):
        bucket = buckets[key]
        bucket["items"].sort(key=lambda item: item["due_date"])
        result.append(bucket)
    return {
        "months": result,
        "total": sum(bucket["total"] for bucket in result),
        "generated_at": today,
    }
