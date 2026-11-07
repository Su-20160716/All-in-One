# -*- coding: utf-8 -*-
"""合规治理服务层：风险评分、覆盖率、评估得分、差距分析、证据校验、
保留期扫描、同意有效性、评审提醒、审计趋势与合规看板。

为什么单独一层
--------------
1. 视图只做参数提取与权限入口；所有「会写库的计算」集中在此，保证
   接口、测试、离线脚本调用同一套规则。合规结论不能因为入口不同而不同。
2. 所有「扫描/计算」接口必须幂等：扫描只 get_or_create 台账行并更新
   到期日，执行只允许 planned → executed 迁移一次，重复调用返回同一结果。
3. 所有多表写入包在 transaction.atomic() 内：例如「评估完成」会同时写
   评估状态、评估得分与每个评估项的加权分，任何一步失败都必须整体回滚，
   否则会出现「状态已完成但得分是旧值」的自相矛盾数据。
4. 时间口径统一走 timezone.localdate()：逾期判定是本地业务日概念，
   用 UTC 日期会让临近零点的记录提前/延后一天到期。
"""
import hashlib
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from core.scoping import can_write, is_visible, scope_queryset

from governance import templates as template_lib
from governance.models import (
    DATA_ASSET_STATUS,
    Assessment,
    AssessmentItem,
    ConsentRecord,
    Control,
    ControlMapping,
    DataAsset,
    Evidence,
    Finding,
    Framework,
    FrameworkControl,
    Policy,
    PolicyVersion,
    ProcessingActivity,
    RemediationTask,
    RetentionAction,
    RetentionRule,
    Risk,
    RiskMatrixBand,
    RiskTreatment,
)

# ---------------------------------------------------------------------------
# 0. 通用工具
# ---------------------------------------------------------------------------

DEFAULT_BANDS = [
    {"label": "低风险", "min_score": 1, "max_score": 4, "level": "low", "color": "#4caf50"},
    {"label": "中风险", "min_score": 5, "max_score": 9, "level": "medium", "color": "#ff9800"},
    {"label": "高风险", "min_score": 10, "max_score": 14, "level": "high", "color": "#f44336"},
    {"label": "严重风险", "min_score": 15, "max_score": 25, "level": "critical", "color": "#7b1fa2"},
]

# 各控制频率对应的「应当被测试的间隔天数」：连续/自动化的控制久未跑即失效，
# 人工季度控制允许 100 天窗口（含执行宽限），避免刚建的控制就被判超期。
FREQUENCY_WINDOW_DAYS = {
    "continuous": 7,
    "weekly": 14,
    "monthly": 45,
    "quarterly": 100,
    "once": None,
}

EVIDENCE_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


def today():
    """当前业务日期（本地时区）。"""
    return timezone.localdate()


def is_admin(user):
    """平台管理员通行判定（审批/发布类操作允许 owner 与管理员）。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def ensure_visible(obj, user):
    """读权限：必须落在数据范围内，否则中文报错。"""
    if obj is None or not is_visible(obj, user):
        raise ValueError("无权访问该对象")


def ensure_writable(obj, user):
    """写权限：owner 或管理员。

    治理数据的交叉审批场景（合规负责人代填、管理员补录）需要管理员兜底，
    其余角色仍按 owner 严格收口，与 core.scoping 的口径一致。
    """
    if obj is None:
        raise ValueError("对象不存在")
    if is_admin(user):
        return True
    if not can_write(user, obj):
        raise ValueError("无权修改该对象")
    return True


def parse_date(value, key="日期", required=False):
    """YYYY-MM-DD → date；空值按 required 返回 None 或报错。"""
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"参数 {key} 需为 YYYY-MM-DD")


def parse_datetime(value, key="时间", required=False):
    """ISO 8601 → aware datetime；无时区信息按当前时区补齐。"""
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"参数 {key} 需为 ISO 8601 时间")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def parse_int(value, key, default=None, minimum=None, maximum=None, required=False):
    """整型参数：统一走 devtools 的 NaN/边界校验口径。"""
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是整数")
    if minimum is not None and number < minimum:
        raise ValueError(f"参数 {key} 不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"参数 {key} 不能大于 {maximum}")
    return number


def parse_decimal(value, key, default=None, minimum=None, maximum=None):
    """小数参数：用于得分/系数，拒绝 NaN 与 Infinity。"""
    if value in (None, ""):
        return default
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是数字")
    if not number.is_finite():
        raise ValueError(f"参数 {key} 必须是有限数字")
    if minimum is not None and number < Decimal(str(minimum)):
        raise ValueError(f"参数 {key} 不能小于 {minimum}")
    if maximum is not None and number > Decimal(str(maximum)):
        raise ValueError(f"参数 {key} 不能大于 {maximum}")
    return number


def choice(value, key, allowed, default=None, required=False):
    """枚举校验：非法值给出中文可选清单，而不是静默落脏数据。"""
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    text = str(value).strip()
    if text not in allowed:
        raise ValueError(f"参数 {key} 必须是 {'/'.join(allowed)} 之一")
    return text


def json_list(value, key, max_len=200):
    """JSON 数组参数：限定长度，避免超大数组进入数据库。"""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        raise ValueError(f"参数 {key} 必须是数组")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    return list(value)


def pct(numerator, denominator, digits=2):
    """百分比计算：分母为 0 时返回 0，避免除零把看板打挂。"""
    if not denominator:
        return 0.0
    return round(float(numerator) * 100.0 / float(denominator), digits)


def latest_run(test):
    """取某个测试的最近一次执行记录（无记录返回 None）。"""
    return test.runs.order_by("-run_at").first()


def as_iso(value):
    """日期/时间 → ISO 字符串；None 返回 None。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# 1. 风险评分矩阵
# ---------------------------------------------------------------------------


def seed_bands(owner):
    """幂等播种默认分档。

    扫描类接口允许随意重跑，所以这里必须 get_or_create；
    已存在的分档不会被覆盖——用户可能已经按自家矩阵调整过阈值。
    """
    created = 0
    for band in DEFAULT_BANDS:
        _, is_new = RiskMatrixBand.objects.get_or_create(
            owner=owner,
            label=band["label"],
            defaults={
                "min_score": band["min_score"],
                "max_score": band["max_score"],
                "level": band["level"],
                "color": band["color"],
                "enabled": True,
            },
        )
        created += 1 if is_new else 0
    return created


def bands_for(owner):
    """取当前用户生效的分档；没有任何分档时先播种再取。"""
    bands = list(RiskMatrixBand.objects.filter(owner=owner).order_by("min_score"))
    if not bands:
        seed_bands(owner)
        bands = list(RiskMatrixBand.objects.filter(owner=owner).order_by("min_score"))
    return [b for b in bands if b.enabled] or bands


def band_for_score(score, owner=None, bands=None):
    """按分值取分档：返回 {label, level, min_score, max_score}。

    分值先夹在 1..25（矩阵理论区间），越界的分档不会命中，
    默认落到最高一档，避免出现「分值 30 却没有等级」的空洞。
    """
    score = max(1, min(25, int(score or 0)))
    pool = bands or (bands_for(owner) if owner is not None else None)
    if not pool:
        for band in DEFAULT_BANDS:
            if band["min_score"] <= score <= band["max_score"]:
                return dict(band)
        return dict(DEFAULT_BANDS[-1])
    for band in pool:
        low = band.min_score if hasattr(band, "min_score") else band["min_score"]
        high = band.max_score if hasattr(band, "max_score") else band["max_score"]
        if low <= score <= high:
            return {
                "label": band.label if hasattr(band, "label") else band["label"],
                "level": band.level if hasattr(band, "level") else band["level"],
                "min_score": low,
                "max_score": high,
            }
    last = pool[-1]
    return {
        "label": last.label if hasattr(last, "label") else last["label"],
        "level": last.level if hasattr(last, "level") else last["level"],
        "min_score": last.min_score if hasattr(last, "min_score") else last["min_score"],
        "max_score": last.max_score if hasattr(last, "max_score") else last["max_score"],
    }


def risk_score(likelihood, impact):
    """固有风险分 = 可能性 × 影响（各 1..5，结果 1..25）。"""
    likelihood = parse_int(likelihood, "likelihood", required=True, minimum=1, maximum=5)
    impact = parse_int(impact, "impact", required=True, minimum=1, maximum=5)
    return likelihood * impact


def level_for_score(score, owner=None):
    """分值 → 等级（走用户分档配置）。"""
    return band_for_score(score, owner=owner)["level"]


def effectiveness_coefficient(effectiveness):
    """控制有效性系数：有效性 100% → 0，0% → 1。

    剩余风险 = 固有风险 × 系数。系数下限保留 0（完全消减），
    上限 1（控制无效），不做任何「打折」的隐式假设。
    """
    value = float(effectiveness or 0)
    value = max(0.0, min(100.0, value))
    return round(1.0 - value / 100.0, 4)


def residual_score_of(inherent, coefficient):
    """剩余风险分：四舍五入后至少 1（风险不会因为控制而彻底消失的记录）。

    用 ROUND_HALF_UP 而非内置 round()：后者是银行家舍入，
    25 × 0.5 = 12.5 会被舍成 12，与业务口径（得 13）不符。
    """
    product = Decimal(str(float(inherent) * float(coefficient)))
    value = int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(1, min(int(inherent), value))


def control_effectiveness(control):
    """由测试执行历史推导控制有效性（0..100）。

    口径：取每个测试「最近一次执行」的结果，通过数 / 有效执行数 × 100；
    完全没有执行记录的测试不计入分母——未测试 ≠ 无效，但会通过
    `tested_ratio` 单独暴露出来，供覆盖率与看板提示补充测试。
    """
    tests = list(control.tests.all())
    if not tests:
        return {"effectiveness": 0, "tested": 0, "total": 0, "tested_ratio": 0.0}
    passed = failed = 0
    for test in tests:
        run = latest_run(test)
        if run is None or run.result == "unknown":
            continue
        if run.result == "pass":
            passed += 1
        else:
            failed += 1
    tested = passed + failed
    effectiveness = int(round(passed * 100.0 / tested)) if tested else 0
    return {
        "effectiveness": effectiveness,
        "tested": tested,
        "total": len(tests),
        "tested_ratio": pct(tested, len(tests)),
    }


def refresh_control_effectiveness(control, persist=True):
    """重算并（可选）落库控制有效性，返回统计数据。"""
    stats = control_effectiveness(control)
    if persist and control.effectiveness != stats["effectiveness"]:
        control.effectiveness = stats["effectiveness"]
        control.save(update_fields=["effectiveness", "updated_at"])
    return stats


def rescore(risk, effectiveness=None, persist=True, bands=None):
    """重算固有分、剩余分与等级；单一写入口，保证冗余字段同步。

    :param effectiveness: 覆盖风险上的控制有效性（0..100），缺省用现值。
    """
    risk.likelihood = parse_int(risk.likelihood, "likelihood", required=True,
                                minimum=1, maximum=5)
    risk.impact = parse_int(risk.impact, "impact", required=True, minimum=1, maximum=5)
    if effectiveness is not None:
        risk.effectiveness = max(0, min(100, int(effectiveness)))
    inherent = risk_score(risk.likelihood, risk.impact)
    coefficient = effectiveness_coefficient(risk.effectiveness)
    residual = residual_score_of(inherent, coefficient)
    band = band_for_score(residual, owner=risk.owner, bands=bands)
    risk.inherent_score = inherent
    risk.residual_score = residual
    risk.level = band["level"]
    if persist:
        risk.save(update_fields=["likelihood", "impact", "inherent_score",
                                 "residual_score", "level", "effectiveness",
                                 "updated_at"])
    return {
        "inherent_score": inherent,
        "residual_score": residual,
        "level": risk.level,
        "level_label": band.get("label", ""),
        "coefficient": coefficient,
        "effectiveness": risk.effectiveness,
    }


def risk_matrix(owner, bands=None):
    """5×5 风险矩阵：每个格子的分值、等级与当前落位数量。

    矩阵接口是纯计算（不写库），前端热力图与「重新评分」共用同一套分档，
    避免出现「矩阵显示高风险、列表显示中风险」的口径分裂。
    """
    pool = bands or bands_for(owner)
    level_counts = {b.get("level") if isinstance(b, dict) else b.level: 0 for b in pool}
    grid = []
    for likelihood in range(1, 6):
        for impact in range(1, 6):
            score = likelihood * impact
            band = band_for_score(score, owner=owner, bands=pool)
            grid.append({
                "likelihood": likelihood,
                "impact": impact,
                "score": score,
                "level": band["level"],
                "label": band["label"],
            })
            level_counts[band["level"]] = level_counts.get(band["level"], 0) + 1
    risks = list(Risk.objects.filter(owner=owner).exclude(status="closed"))
    placements = [{"id": r.id, "code": r.code, "name": r.name,
                   "likelihood": r.likelihood, "impact": r.impact,
                   "residual_score": r.residual_score, "level": r.level}
                  for r in risks]
    return {
        "bands": [b.to_dict() if hasattr(b, "to_dict") else dict(b) for b in pool],
        "grid": grid,
        "level_cell_counts": level_counts,
        "risks": placements,
        "axes": {"likelihood": [1, 2, 3, 4, 5], "impact": [1, 2, 3, 4, 5]},
    }


def risk_distribution(owner):
    """风险分布：按等级 / 状态 / 类别，含平均剩余分。"""
    qs = Risk.objects.filter(owner=owner)
    by_level = {row["level"]: row["count"] for row in
                qs.values("level").annotate(count=Count("id"))}
    by_status = {row["status"]: row["count"] for row in
                 qs.values("status").annotate(count=Count("id"))}
    by_category = list(qs.values("category").annotate(count=Count("id")).order_by("-count"))
    open_qs = qs.exclude(status="closed")
    average = open_qs.aggregate(avg=Sum("residual_score"), count=Count("id"))
    avg_residual = round(float(average["avg"] or 0) / average["count"], 2) if average["count"] else 0.0
    top = list(open_qs.order_by("-residual_score")[:10])
    return {
        "total": qs.count(),
        "open": open_qs.count(),
        "by_level": {level: by_level.get(level, 0)
                     for level in ("critical", "high", "medium", "low")},
        "by_status": by_status,
        "by_category": by_category,
        "avg_residual": avg_residual,
        "top_risks": [r.to_dict() for r in top],
    }


# ---------------------------------------------------------------------------
# 2. 控制覆盖率
# ---------------------------------------------------------------------------


def framework_coverage(framework):
    """框架达成率：框架条款被「评估通过」或「有效控制覆盖」的比例。

    判定顺序（满足其一即视为已覆盖）：
    1. 存在评估项 status=passed；
    2. 存在映射控制且映射覆盖强度 strength >= 60（阈值口径固定，便于跨期比较）。

    这里用「映射强度」而不是「控制有效性」：覆盖率回答的是「条款有没有人
    设计对应实施」，控制有效性回答的是「实施是否真的在跑」。评估未通过的
    条款仍算「已覆盖」（有实施），其缺陷由 failed 计数与差距分析单列，这样
    覆盖率反映现状基线，整改效果由通过率衡量，两个指标不会互相污染。

    框架本身不存覆盖率字段：覆盖率是随评估与测试时刻变化的派生值，
    落库必然出现「存的是昨天的数」，每次都按当前数据现算是唯一正确口径。
    """
    controls = list(framework.controls.all())
    total = len(controls)
    if not total:
        # 空框架同样返回完整结构：详情接口直接透传该字典，缺键会让前端崩。
        return {
            "framework_id": framework.pk,
            "framework_name": framework.name,
            "control_total": 0,
            "covered": 0,
            "passed": 0,
            "failed": 0,
            "untested": 0,
            "coverage_ratio": 0.0,
            "pass_ratio": 0.0,
            "by_category": [],
            "gaps_preview": [],
            "gap_total": 0,
            "threshold": 60,
        }
    item_rows = {}
    for item in AssessmentItem.objects.filter(
            framework_control__framework=framework).select_related("framework_control"):
        current = item_rows.get(item.framework_control_id)
        # 同一条款可能被多次评估：以「最近一次通过」优先，其次保留最新状态，
        # 避免历史失败把当前已整改的条款永久标红。
        if current is None or item.status == "passed" or current["status"] != "passed":
            item_rows[item.framework_control_id] = {"status": item.status, "id": item.pk}
    mapping_rows = {}
    for mapping in ControlMapping.objects.filter(
            framework_control__framework=framework).select_related("control"):
        mapping_rows.setdefault(mapping.framework_control_id, []).append(mapping)

    covered = passed = failed = 0
    category_stats = {}
    gaps = []
    for control in controls:
        item = item_rows.get(control.pk)
        status = item["status"] if item else "not_started"
        mapped = mapping_rows.get(control.pk, [])
        best_mapping = max([m.strength for m in mapped], default=0)
        is_covered = status == "passed" or best_mapping >= 60
        if status == "passed":
            passed += 1
        if status == "failed":
            failed += 1
        if is_covered:
            covered += 1
        bucket = category_stats.setdefault(
            control.category, {"category": control.category, "total": 0,
                               "covered": 0, "passed": 0, "weight": 0})
        bucket["total"] += 1
        bucket["weight"] += control.weight
        bucket["covered"] += 1 if is_covered else 0
        bucket["passed"] += 1 if status == "passed" else 0
        if not is_covered:
            gaps.append({
                "framework_control_id": control.pk,
                "code": control.code,
                "title": control.title,
                "category": control.category,
                "item_status": status,
                "mapped_controls": len(mapped),
                "best_mapping_strength": best_mapping,
            })
    by_category = []
    for bucket in category_stats.values():
        bucket["coverage_ratio"] = pct(bucket["covered"], bucket["total"])
        by_category.append(bucket)
    by_category.sort(key=lambda row: row["coverage_ratio"])
    return {
        "framework_id": framework.pk,
        "framework_name": framework.name,
        "control_total": total,
        "covered": covered,
        "passed": passed,
        "failed": failed,
        "untested": total - passed - failed,
        "coverage_ratio": pct(covered, total),
        "pass_ratio": pct(passed, total),
        "by_category": by_category,
        "gaps_preview": gaps[:20],
        "gap_total": len(gaps),
        "threshold": 60,
    }


def control_coverage(owner):
    """内部控制的覆盖概览：按类别统计控制数、已测试数、平均有效性。"""
    controls = list(Control.objects.filter(owner=owner))
    buckets = {}
    tested = 0
    for control in controls:
        bucket = buckets.setdefault(
            control.category, {"category": control.category, "total": 0,
                               "active": 0, "tested": 0, "effectiveness_sum": 0})
        bucket["total"] += 1
        bucket["active"] += 1 if control.status == "active" else 0
        if control.last_tested_at:
            tested += 1
            bucket["tested"] += 1
        bucket["effectiveness_sum"] += control.effectiveness
    rows = []
    for bucket in buckets.values():
        rows.append({
            "category": bucket["category"],
            "total": bucket["total"],
            "active": bucket["active"],
            "tested": bucket["tested"],
            "tested_ratio": pct(bucket["tested"], bucket["total"]),
            "avg_effectiveness": round(bucket["effectiveness_sum"] / bucket["total"], 2)
            if bucket["total"] else 0.0,
        })
    rows.sort(key=lambda row: row["avg_effectiveness"])
    return {
        "control_total": len(controls),
        "tested": tested,
        "tested_ratio": pct(tested, len(controls)),
        "by_category": rows,
    }


# ---------------------------------------------------------------------------
# 3. 评估得分
# ---------------------------------------------------------------------------

ITEM_CREDIT = {
    "passed": Decimal("1"),
    "in_progress": Decimal("0.5"),
    "failed": Decimal("0"),
    "not_started": Decimal("0"),
    "not_applicable": None,  # 不适用：从分母剔除
}


def item_credit(item):
    """单个评估项的得分系数：通过 1、进行中 0.5、失败/未开始 0、不适用 None。"""
    return ITEM_CREDIT.get(item.status, Decimal("0"))


def assessment_score(assessment, persist=True):
    """加权评估得分：Σ(系数 × 权重) / Σ(权重) × 100，不适用项剔除。

    权重优先取评估项快照 weight（评估启动时从框架条款复制），
    没有快照时回退到框架条款权重、再回退到 1——历史评估项不会因为
    框架条款权重调整而「追溯改分」，审计口径才站得住。
    """
    shares = []
    weighted = Decimal("0")
    total_weight = Decimal("0")
    for item in assessment.items.select_related("framework_control"):
        credit = item_credit(item)
        if credit is None:
            item.score = Decimal("0")
            if persist:
                item.save(update_fields=["score", "updated_at"])
            continue
        weight = Decimal(str(item.weight or 0))
        if weight <= 0:
            weight = Decimal(str(getattr(item.framework_control, "weight", 1) or 1))
        score = (credit * weight * Decimal("100")).quantize(Decimal("0.01"))
        weighted += credit * weight
        total_weight += weight
        item.score = score
        if persist:
            item.save(update_fields=["score", "updated_at"])
        shares.append({
            "item_id": item.pk,
            "status": item.status,
            "weight": int(weight),
            "credit": float(credit),
            "score": float(score),
        })
    value = (weighted / total_weight * Decimal("100")).quantize(Decimal("0.01")) \
        if total_weight > 0 else Decimal("0")
    if persist:
        assessment.score = value
        assessment.save(update_fields=["score", "updated_at"])
    return {
        "assessment_id": assessment.pk,
        "score": float(value),
        "item_count": len(shares),
        "total_weight": int(total_weight),
        "excluded": assessment.items.filter(status="not_applicable").count(),
        "items": shares,
    }


# ---------------------------------------------------------------------------
# 4. 差距分析
# ---------------------------------------------------------------------------


def framework_gaps(framework):
    """差距分析：框架条款 vs 现有控制 / 评估项，输出缺口清单。

    缺口分三类，前端据此给出不同处置建议：
    - `no_mapping`：没有任何内部实施（应先补控制再谈评估）；
    - `untested`：有实施但从未评估（应安排评估）；
    - `failed`：评估未通过 / 控制有效性不足（应整改）。
    """
    coverage = framework_coverage(framework)
    gaps = []
    for control in framework.controls.all().order_by("code"):
        items = list(control.assessment_items.all())
        latest = None
        for item in items:
            if latest is None or item.updated_at > latest.updated_at:
                latest = item
        mappings = list(control.mappings.select_related("control"))
        best = max([m.control.effectiveness for m in mappings], default=0)
        status = latest.status if latest else "not_started"
        # 判定顺序刻意区分「已达成」与「有实施未达成」：评估通过的条款直接
        # 出列；未通过优先归入整改；没映射才是补建；其余才是排期评估。
        # 已通过但映射控制有效性不足（best<60）仍算缺陷，因为实测已通过而
        # 控制测试不达标，说明存在靠人工兜底的隐患。
        if status == "failed":
            reason = "failed"
            recommendation = "整改控制缺陷并重新测试"
        elif status == "passed":
            continue
        elif not mappings:
            reason = "no_mapping"
            recommendation = "补建内部实施或并入现有控制"
        elif status in ("not_started", "in_progress"):
            reason = "untested"
            recommendation = "安排评估并采集证据"
        elif best < 60:
            reason = "failed"
            recommendation = "整改控制缺陷并重新测试"
        else:
            continue
        gaps.append({
            "framework_control_id": control.pk,
            "code": control.code,
            "title": control.title,
            "category": control.category,
            "weight": control.weight,
            "reason": reason,
            "item_status": status,
            "mapped_control_count": len(mappings),
            "best_effectiveness": best,
            "recommendation": recommendation,
        })
    return {
        "framework_id": framework.pk,
        "framework_name": framework.name,
        "coverage_ratio": coverage["coverage_ratio"],
        "gap_total": len(gaps),
        "gaps": gaps,
        "summary": {
            "no_mapping": sum(1 for g in gaps if g["reason"] == "no_mapping"),
            "untested": sum(1 for g in gaps if g["reason"] == "untested"),
            "failed": sum(1 for g in gaps if g["reason"] == "failed"),
        },
    }


def control_gaps(owner):
    """内部控制的差距：久未测试 / 停用但被映射 / 有效性过低。

    与框架差距互补：框架侧看「条款是否有人负责」，控制侧看「实施了却是否
    真的在跑」。停用控制仍被框架映射是最危险的一类，单列 `inactive_mapped`。
    """
    items = []
    for control in Control.objects.filter(owner=owner).prefetch_related("tests", "framework_mappings"):
        window = FREQUENCY_WINDOW_DAYS.get(control.frequency)
        stale = False
        if window is not None:
            anchor = control.last_tested_at or control.created_at
            stale = (timezone.now() - anchor).days > window
        mapping_count = control.framework_mappings.count()
        reasons = []
        if control.status == "inactive" and mapping_count:
            reasons.append("inactive_mapped")
        if stale:
            reasons.append("stale_test")
        if control.effectiveness and control.effectiveness < 60:
            reasons.append("low_effectiveness")
        if not reasons:
            continue
        items.append({
            "control_id": control.pk,
            "code": control.code,
            "name": control.name,
            "category": control.category,
            "status": control.status,
            "frequency": control.frequency,
            "effectiveness": control.effectiveness,
            "mapping_count": mapping_count,
            "reasons": reasons,
        })
    return {"gap_total": len(items), "controls": items}


# ---------------------------------------------------------------------------
# 5. 证据校验
# ---------------------------------------------------------------------------


def split_hash(value):
    """解析 `算法:摘要`；缺省算法按 sha256 处理（历史数据兼容）。

    返回 (算法, 摘要)。算法不在白名单直接报错——静默降级会让校验形同虚设。
    """
    text = str(value or "").strip()
    if not text:
        return "", ""
    if ":" in text:
        algorithm, digest = text.split(":", 1)
        algorithm = algorithm.lower().strip()
    else:
        algorithm, digest = "sha256", text
    if algorithm not in EVIDENCE_ALGORITHMS:
        raise ValueError(f"不支持的哈希算法: {algorithm}（支持 {'/'.join(EVIDENCE_ALGORITHMS)}）")
    return algorithm, digest.strip().lower()


def compute_hash(payload, algorithm="sha256"):
    """对给定内容计算哈希（字符串按 UTF-8 编码）；不落盘、不联网。"""
    if algorithm not in EVIDENCE_ALGORITHMS:
        raise ValueError(f"不支持的哈希算法: {algorithm}")
    data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    return f"{algorithm}:{hashlib.new(algorithm, data).hexdigest()}"


def evidence_expired(evidence, at=None):
    """是否过期：有效期至 < 今天。"""
    at = at or today()
    return bool(evidence.expires_on and evidence.expires_on < at)


def verify_evidence(evidence, provided_hash=None, content=None, persist=True):
    """证据校验：哈希一致性 + 有效期。

    - provided_hash：外部给出的 `算法:摘要`；
    - content：待校验的原文（接口不存文件，允许调用方传入摘要内容）；
    两者都给时以 content 计算为准。都不给时只做「格式合法性 + 过期」检查，
    并把结论写回 last_check_*，重复调用结果一致（幂等）。
    """
    notes = []
    ok = True
    if content is not None:
        algorithm, _ = split_hash(provided_hash or evidence.hash_value or "sha256:")
        expected = compute_hash(content, algorithm or "sha256")
        stored = evidence.hash_value or ""
        ok = bool(stored) and stored.strip().lower() == expected
        notes.append("哈希一致" if ok else "哈希与登记值不一致")
        if not stored:
            ok = False
            notes.append("证据未登记哈希值")
    elif provided_hash:
        _, digest = split_hash(provided_hash)
        stored = evidence.hash_value or ""
        ok = bool(stored) and stored.strip().lower().endswith(digest)
        notes.append("哈希一致" if ok else "哈希与登记值不一致")
    else:
        try:
            algorithm, digest = split_hash(evidence.hash_value)
        except ValueError as exc:
            ok = False
            algorithm, digest = "", ""
            notes.append(str(exc))
        if not digest:
            ok = False
            notes.append("证据未登记哈希值")
        elif not all(ch in "0123456789abcdef" for ch in digest):
            ok = False
            notes.append("哈希值包含非十六进制字符")
        else:
            notes.append(f"{algorithm} 格式合法")
    expired = evidence_expired(evidence)
    if expired:
        ok = False
        notes.append("证据已过期")
    if persist:
        evidence.last_checked_at = timezone.now()
        evidence.last_check_ok = ok
        evidence.last_check_note = "；".join(notes)[:200]
        evidence.save(update_fields=["last_checked_at", "last_check_ok",
                                     "last_check_note", "updated_at"])
    return {
        "evidence_id": evidence.pk,
        "ok": ok,
        "expired": expired,
        "expires_on": as_iso(evidence.expires_on),
        "algorithm": split_hash(evidence.hash_value)[0] if evidence.hash_value else "",
        "notes": notes,
        "checked_at": as_iso(evidence.last_checked_at),
    }


def expiring_evidences(owner, days=0, only_expired=False):
    """即将到期（days 天内）或已过期证据列表，按到期日升序。"""
    days = parse_int(days, "days", default=0, minimum=0, maximum=3650)
    limit = today() + timedelta(days=days)
    qs = Evidence.objects.filter(owner=owner, expires_on__isnull=False)
    qs = qs.filter(expires_on__lte=limit)
    if only_expired:
        qs = qs.filter(expires_on__lt=today())
    rows = [e.to_dict() for e in qs.order_by("expires_on", "id")]
    return {"items": rows, "count": len(rows), "horizon_days": days}


# ---------------------------------------------------------------------------
# 6. 保留期扫描
# ---------------------------------------------------------------------------


def retention_rules_for(owner):
    """取当前用户的启用规则（按资源类型索引）。"""
    return {rule.resource_kind: rule for rule in
            RetentionRule.objects.filter(owner=owner, enabled=True)}


def retention_due_assets(owner, rules, at):
    """数据资产到期项：资产自带天数优先，否则用规则天数。

    资产登记的 retention_days 是「个案约定」，规则是「默认口径」；
    个案永远优先，否则法务给某类资产单独约定的保留期会被默认规则覆盖。
    """
    rows = []
    rule = rules.get("data_asset")
    for asset in DataAsset.objects.filter(owner=owner).exclude(status="deleted"):
        days = asset.retention_days or (rule.retention_days if rule else 0)
        if not days:
            continue
        due = asset.created_at.date() + timedelta(days=days)
        if due <= at:
            rows.append({
                "resource_kind": "data_asset",
                "resource_id": asset.pk,
                "resource_name": asset.name,
                "due_on": due,
                "action": rule.due_action if rule else "archive",
                "owner": asset.owner_id,
            })
    return rows


def retention_due_evidences(owner, rules, at):
    """证据到期项：以 expires_on 为到期日（证据的有效期本身就是保留义务）。"""
    rows = []
    rule = rules.get("evidence")
    if rule is None:
        return rows
    for evidence in Evidence.objects.filter(owner=owner, expires_on__isnull=False):
        if evidence.expires_on <= at:
            rows.append({
                "resource_kind": "evidence",
                "resource_id": evidence.pk,
                "resource_name": evidence.name,
                "due_on": evidence.expires_on,
                "action": rule.due_action,
                "owner": evidence.owner_id,
            })
    return rows


def retention_due_consents(owner, rules, at):
    """同意记录到期项：从授予时间起算保留天数。"""
    rows = []
    rule = rules.get("consent")
    if rule is None:
        return rows
    for consent in ConsentRecord.objects.filter(owner=owner):
        base = consent.granted_at or consent.created_at
        due = base.date() + timedelta(days=rule.retention_days)
        if due <= at:
            rows.append({
                "resource_kind": "consent",
                "resource_id": consent.pk,
                "resource_name": f"{consent.data_subject}:{consent.purpose}",
                "due_on": due,
                "action": rule.due_action,
                "owner": consent.owner_id,
            })
    return rows


def retention_candidates(owner, at=None):
    """汇总所有到期候选（纯计算，不写库）。"""
    at = at or today()
    rules = retention_rules_for(owner)
    rows = []
    rows.extend(retention_due_assets(owner, rules, at))
    rows.extend(retention_due_evidences(owner, rules, at))
    rows.extend(retention_due_consents(owner, rules, at))
    rows.sort(key=lambda row: (row["due_on"], row["resource_kind"], row["resource_id"]))
    return rows


@transaction.atomic
def scan_retention(owner, at=None):
    """保留期扫描：把到期候选写入台账（幂等）。

    幂等实现要点：
    - 唯一键 (owner, resource_kind, resource_id, action) 挡重复行；
    - 已存在行只刷新 due_on / resource_name，不改 status，
      否则用户执行过的记录会在下次扫描时被「复活」成待执行。
    """
    at = at or today()
    created = updated = 0
    items = []
    for row in retention_candidates(owner, at):
        obj, is_new = RetentionAction.objects.get_or_create(
            owner=owner,
            resource_kind=row["resource_kind"],
            resource_id=row["resource_id"],
            action=row["action"],
            defaults={
                "resource_name": row["resource_name"],
                "due_on": row["due_on"],
                "status": "planned",
            },
        )
        if is_new:
            created += 1
        else:
            changed = False
            if obj.due_on != row["due_on"]:
                obj.due_on = row["due_on"]
                changed = True
            if row["resource_name"] and obj.resource_name != row["resource_name"]:
                obj.resource_name = row["resource_name"][:200]
                changed = True
            if changed:
                obj.save(update_fields=["due_on", "resource_name", "updated_at"])
                updated += 1
        items.append(obj.to_dict())
    return {
        "scanned_at": as_iso(timezone.now()),
        "due_total": len(items),
        "created": created,
        "updated": updated,
        "items": items,
    }


def retention_due_list(owner, at=None, include_executed=False):
    """到期台账列表（读取口径，不写库）。"""
    at = at or today()
    qs = RetentionAction.objects.filter(owner=owner, due_on__lte=at)
    if not include_executed:
        qs = qs.filter(status="planned")
    rows = [obj.to_dict() for obj in qs.order_by("due_on", "id")]
    return {"items": rows, "count": len(rows), "as_of": as_iso(at)}


@transaction.atomic
def execute_retention(action_obj, note=""):
    """执行到期动作：只改状态并记录，不真实删数据。

    合规模拟的必要性：真实删除不可逆，接口默认「标记执行」并提供
    executed_at + note 作为可审计凭据；重复执行返回 same 标记，绝不重复
    迁移状态，也不会把资产二次匿名化。
    """
    if action_obj.status == "executed":
        return {"action": action_obj.to_dict(), "changed": False, "reason": "already_executed"}
    if action_obj.status == "skipped":
        return {"action": action_obj.to_dict(), "changed": False, "reason": "already_skipped"}
    target_status = {"delete": "deleted", "anonymize": "anonymized", "archive": "archived"}
    action_obj.status = "executed"
    action_obj.executed_at = timezone.now()
    action_obj.note = (note or "按保留规则执行")[:200]
    action_obj.save(update_fields=["status", "executed_at", "note", "updated_at"])
    applied = None
    if action_obj.resource_kind == "data_asset":
        asset = DataAsset.objects.filter(pk=action_obj.resource_id, owner=action_obj.owner).first()
        if asset is not None:
            new_status = target_status.get(action_obj.action, DATA_ASSET_STATUS[1])
            asset.status = new_status
            asset.save(update_fields=["status", "updated_at"])
            applied = {"data_asset_id": asset.pk, "status": asset.status}
    return {"action": action_obj.to_dict(), "changed": True, "applied": applied}


# ---------------------------------------------------------------------------
# 7. 同意有效性校验
# ---------------------------------------------------------------------------


def consent_validity(consent, purpose=None, at=None):
    """同意有效性：状态 + 目的 + 时间三项联合判定。

    任何一项不满足都判无效，并给出中文原因：合规场景需要「为什么无效」，
    只返回布尔值无法向数据主体解释。
    """
    at = at or today()
    reasons = []
    if consent.status == "withdrawn":
        reasons.append("同意已撤回")
    elif consent.status == "expired":
        reasons.append("同意已标记过期")
    elif consent.status != "granted":
        reasons.append(f"当前状态 {consent.status} 不构成有效同意")
    if consent.expires_on and consent.expires_on < at:
        reasons.append("同意已超过有效期")
    if purpose and consent.purpose != purpose:
        reasons.append("目的与请求不一致")
    valid = not reasons
    return {
        "consent_id": consent.pk,
        "valid": valid,
        "reasons": reasons,
        "status": consent.status,
        "purpose": consent.purpose,
        "checked_at": as_iso(at),
        "expires_on": as_iso(consent.expires_on),
    }


def consent_summary(owner):
    """同意池概览：状态分布 + 目的分布 + 近 30 天撤回数。"""
    qs = ConsentRecord.objects.filter(owner=owner)
    by_status = {row["status"]: row["count"] for row in
                 qs.values("status").annotate(count=Count("id"))}
    since = timezone.now() - timedelta(days=30)
    return {
        "total": qs.count(),
        "by_status": {status: by_status.get(status, 0)
                      for status in ("granted", "withdrawn", "expired")},
        "withdrawn_last_30d": qs.filter(status="withdrawn", withdrawn_at__gte=since).count(),
        "by_purpose": list(qs.values("purpose").annotate(count=Count("id"))
                           .order_by("-count")[:10]),
    }


# ---------------------------------------------------------------------------
# 8. 政策评审提醒
# ---------------------------------------------------------------------------


def policy_review_reminders(owner, days=30):
    """下次评审日 ≤ N 天的策略清单（含已逾期）。

    只提醒 approved / published；草稿没有评审周期，停用策略不再需要评审，
    把它们混进来会让提醒列表永远有噪音。
    """
    days = parse_int(days, "days", default=30, minimum=0, maximum=3650)
    limit = today() + timedelta(days=days)
    qs = Policy.objects.filter(owner=owner, status__in=("approved", "published"),
                               next_review_on__isnull=False, next_review_on__lte=limit)
    rows = []
    for policy in qs.order_by("next_review_on", "id"):
        remaining = (policy.next_review_on - today()).days
        rows.append({
            "policy_id": policy.pk,
            "code": policy.code,
            "name": policy.name,
            "status": policy.status,
            "next_review_on": as_iso(policy.next_review_on),
            "days_remaining": remaining,
            "overdue": remaining < 0,
        })
    overdue = sum(1 for row in rows if row["overdue"])
    return {
        "horizon_days": days,
        "count": len(rows),
        "overdue": overdue,
        "items": rows,
    }


# ---------------------------------------------------------------------------
# 9. 审计发现趋势与整改及时率
# ---------------------------------------------------------------------------


def month_key(value):
    """日期 → YYYY-MM（趋势分桶键）。"""
    return value.strftime("%Y-%m")


def month_range(end, months):
    """生成连续月份序列：缺失月份补 0，趋势图不能出现断档。"""
    months = max(1, min(36, int(months)))
    keys = []
    year, month = end.year, end.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(keys))


def finding_trend(owner, months=6):
    """审计发现趋势：按月统计新增 / 解决 / 其中严重及以上。"""
    months = parse_int(months, "months", default=6, minimum=1, maximum=36)
    keys = month_range(today(), months)
    opened = {key: 0 for key in keys}
    resolved = {key: 0 for key in keys}
    severe = {key: 0 for key in keys}
    for finding in Finding.objects.filter(owner=owner):
        created_key = month_key(finding.created_at.date())
        if created_key in opened:
            opened[created_key] += 1
            if finding.severity in ("high", "critical"):
                severe[created_key] += 1
        closed_on = finding.closed_on
        if closed_on is None and finding.status in ("resolved", "verified"):
            closed_on = finding.updated_at.date()
        if closed_on and month_key(closed_on) in resolved:
            resolved[month_key(closed_on)] += 1
    series = [{"month": key, "opened": opened[key], "resolved": resolved[key],
               "severe": severe[key]} for key in keys]
    return {
        "months": months,
        "series": series,
        "totals": {
            "opened": sum(opened.values()),
            "resolved": sum(resolved.values()),
            "severe": sum(severe.values()),
        },
        "net_open": sum(opened.values()) - sum(resolved.values()),
    }


def remediation_timeliness(owner):
    """整改及时率：按时完成 / 已完成，以及当前逾期数。

    口径：完成时间以 completed_on（缺省 verified_at 日期）为准，
    与 due_on 比较；未完成的按「今天已过截止日」计逾期，
    这样看板能同时回答「历史表现」与「当前压力」。
    """
    tasks = list(RemediationTask.objects.filter(owner=owner))
    at = today()
    done = [t for t in tasks if t.status in ("done", "verified")]
    on_time = 0
    delays = []
    for task in done:
        finished = task.completed_on or (task.verified_at.date() if task.verified_at else None)
        if finished is None or task.due_on is None:
            continue
        if finished <= task.due_on:
            on_time += 1
        else:
            delays.append((finished - task.due_on).days)
    overdue = [t for t in tasks if t.is_overdue(at)]
    return {
        "total": len(tasks),
        "done": len(done),
        "on_time": on_time,
        "timeliness_ratio": pct(on_time, len(done)),
        "overdue": len(overdue),
        "avg_delay_days": round(sum(delays) / len(delays), 1) if delays else 0.0,
        "overdue_items": [t.to_dict() for t in overdue[:20]],
    }


# ---------------------------------------------------------------------------
# 10. 合规看板
# ---------------------------------------------------------------------------


def framework_summary(owner):
    """全部框架的达成率汇总（取每个框架一次计算，避免重复 SQL）。"""
    rows = []
    for framework in Framework.objects.filter(owner=owner).order_by("-created_at"):
        coverage = framework_coverage(framework)
        rows.append({
            "framework_id": framework.pk,
            "name": framework.name,
            "version": framework.version,
            "kind": framework.kind,
            "status": framework.status,
            "control_total": coverage["control_total"],
            "covered": coverage["covered"],
            "coverage_ratio": coverage["coverage_ratio"],
            "pass_ratio": coverage["pass_ratio"],
        })
    average = round(sum(row["coverage_ratio"] for row in rows) / len(rows), 2) if rows else 0.0
    return {"count": len(rows), "average_coverage": average, "items": rows}


def dpia_coverage(owner):
    """DPIA 覆盖率：处理活动中已完成 DPIA 的比例。

    跨境或高风险活动未覆盖时单独列出，监管检查首先看这两类。
    """
    qs = ProcessingActivity.objects.filter(owner=owner)
    total = qs.count()
    done = qs.filter(dpia_done=True).count()
    risky_missing = list(qs.filter(dpia_done=False)
                         .filter(Q(cross_border=True)).values("id", "name", "cross_border"))
    return {
        "activity_total": total,
        "dpia_done": done,
        "coverage_ratio": pct(done, total),
        "cross_border_missing": risky_missing,
    }


def dashboard(owner):
    """合规看板：框架达成率、开放风险、逾期整改、DPIA 覆盖率与到期提醒。

    看板必须一次请求拿到全部指标：各卡片分别请求会让前端出现「同一时刻
    不同口径」的画面，也会把数据库打成一串 N+1。
    """
    frameworks = framework_summary(owner)
    distribution = risk_distribution(owner)
    timeliness = remediation_timeliness(owner)
    dpia = dpia_coverage(owner)
    reminders = policy_review_reminders(owner, 30)
    evidence_due = expiring_evidences(owner, 30)
    assessments = Assessment.objects.filter(owner=owner)
    running = assessments.filter(status__in=("planned", "in_progress"))
    overdue_assessments = [a.to_dict() for a in running if a.effective_status() == "overdue"]
    open_findings = Finding.objects.filter(owner=owner).exclude(status__in=("resolved", "verified"))
    high_findings = open_findings.filter(severity__in=("high", "critical"))
    control_stats = control_coverage(owner)
    return {
        "frameworks": {
            "count": frameworks["count"],
            "average_coverage": frameworks["average_coverage"],
            "items": frameworks["items"],
        },
        "risks": {
            "total": distribution["total"],
            "open": distribution["open"],
            "by_level": distribution["by_level"],
            "avg_residual": distribution["avg_residual"],
            "critical_open": distribution["by_level"].get("critical", 0),
        },
        "remediations": {
            "total": timeliness["total"],
            "overdue": timeliness["overdue"],
            "timeliness_ratio": timeliness["timeliness_ratio"],
        },
        "dpia": dpia,
        "policies": {
            "due_30d": reminders["count"],
            "overdue": reminders["overdue"],
        },
        "evidence": {
            "expiring_30d": evidence_due["count"],
        },
        "assessments": {
            "total": assessments.count(),
            "running": running.count(),
            "overdue": len(overdue_assessments),
            "overdue_items": overdue_assessments[:10],
        },
        "findings": {
            "open": open_findings.count(),
            "high": high_findings.count(),
        },
        "controls": {
            "total": control_stats["control_total"],
            "tested_ratio": control_stats["tested_ratio"],
        },
        "generated_at": as_iso(timezone.now()),
    }


# ---------------------------------------------------------------------------
# 11. 序号与校验辅助（供视图复用）
# ---------------------------------------------------------------------------


def next_code(model, owner, prefix, field="code", width=4):
    """生成下一个业务编号（如 RSK-0007）。

    并发下可能撞号，因此调用方仍需捕获 IntegrityError 或以唯一约束兜底；
    这里用 max(编号后缀) + 1 而不是 count，删除后不会复用已用编号。
    """
    values = model.objects.filter(owner=owner).values_list(field, flat=True)
    highest = 0
    for value in values:
        text = str(value or "")
        if not text.startswith(prefix):
            continue
        tail = text[len(prefix):].lstrip("-")
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}-{highest + 1:0{width}d}"


def require_status(obj, allowed, action="执行该操作"):
    """状态机前置校验：给出「当前状态 X 不能…」的可读错误。"""
    if obj.status not in allowed:
        raise ValueError(f"当前状态 {obj.status} 不能{action}")
    return obj


def owner_queryset(model, user, **filters):
    """按数据范围读取（列表接口统一入口）。"""
    return scope_queryset(model.objects.filter(**filters), user)


def assigned(obj, user, owner_field="owner"):
    """是否本人拥有（用于「我的」筛选）。"""
    return getattr(obj, f"{owner_field}_id", None) == getattr(user, "id", None)


def risk_open_count(owner):
    """开放风险数（看板与卡片复用）。"""
    return Risk.objects.filter(owner=owner).exclude(status="closed").count()


def policy_publish_version(policy, user, change_note="", version=None):
    """批准/发布时固化版本快照（幂等：同一版本号只保留一条）。

    版本号缺省按 v<序号> 递增；内容与主表一致，发布后主表继续编辑不会
    影响已发布快照——这正是审计要的「不可变证据」。
    """
    if not version:
        count = policy.versions.count() + 1
        version = f"v{count}.0"
    existing = policy.versions.filter(version=version).first()
    if existing is not None:
        return existing
    return PolicyVersion.objects.create(
        owner=user,
        policy=policy,
        version=version,
        content_snapshot=policy.content,
        change_note=change_note,
        approver_name=policy.approved_by_name or getattr(user, "username", ""),
        published_at=timezone.now() if policy.status == "published" else None,
    )


def compare_versions(policy, left, right):
    """版本对比：按行做简单差异（新增/删除/相同）供前端高亮。

    只做行级 diff 而不是字符级：制度文本以条款为行，行级差异足够定位
    「哪一条被改了」，字符级 diff 在长文本上既慢又难读。
    """
    import difflib

    left_lines = (left.content_snapshot or "").splitlines()
    right_lines = (right.content_snapshot or "").splitlines()
    rows = []
    for line in difflib.unified_diff(left_lines, right_lines,
                                     fromfile=left.version, tofile=right.version, lineterm=""):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            rows.append({"kind": "hunk", "text": line})
        elif line.startswith("+"):
            rows.append({"kind": "added", "text": line[1:]})
        elif line.startswith("-"):
            rows.append({"kind": "removed", "text": line[1:]})
        else:
            rows.append({"kind": "context", "text": line[1:] if line.startswith(" ") else line})
    identical = (left.content_snapshot or "") == (right.content_snapshot or "")
    return {
        "left": left.to_dict(),
        "right": right.to_dict(),
        "identical": identical,
        "added": sum(1 for row in rows if row["kind"] == "added"),
        "removed": sum(1 for row in rows if row["kind"] == "removed"),
        "diff": rows,
    }


# ---------------------------------------------------------------------------
# 11. 框架模板：把内置条款库落到 FrameworkControl
# ---------------------------------------------------------------------------


def apply_framework_template(framework, kind=None, update_existing=False):
    """把内置条款库写入框架（按 code 幂等，重复应用只补缺）。

    幂等的关键：以 (framework, code) 为准判断存在性，已存在的条款默认
    不覆盖——用户可能已经改过标题或权重，模板只负责「补齐」而不是
    「重置」。需要按最新模板刷新时显式传 update_existing=True。

    返回 created/skipped/updated 三个计数，前端据此展示「本次新增 N 条」，
    重复点击时 created=0 但不会报错，也不会产生重复条款。
    """
    spec_kind = kind or framework.kind
    # custom 框架没有内置条款：允许显式指定模板，否则给出可操作的中文提示。
    if not template_lib.TEMPLATES.get(str(spec_kind or "").strip()):
        raise ValueError(
            f"框架 {framework.name} 没有可用的内置条款库（可选: "
            f"{', '.join(template_lib.template_kinds())}）")
    rows = template_lib.template_controls(spec_kind)
    existing = {
        item.code: item
        for item in FrameworkControl.objects.filter(framework=framework, code__in=[r["code"] for r in rows])
    }
    created, updated, skipped = [], [], []
    with transaction.atomic():
        for row in rows:
            current = existing.get(row["code"])
            if current is None:
                FrameworkControl.objects.create(
                    owner=framework.owner,
                    framework=framework,
                    code=row["code"],
                    title=row["title"],
                    description=row["description"],
                    category=row["category"],
                    weight=row["weight"],
                )
                created.append(row["code"])
                continue
            if not update_existing:
                skipped.append(row["code"])
                continue
            changed = False
            if current.title != row["title"]:
                current.title = row["title"]
                changed = True
            if current.description != row["description"]:
                current.description = row["description"]
                changed = True
            if current.category != row["category"]:
                current.category = row["category"]
                changed = True
            if current.weight != row["weight"]:
                current.weight = row["weight"]
                changed = True
            if changed:
                current.save(update_fields=["title", "description", "category", "weight", "updated_at"])
                updated.append(row["code"])
            else:
                skipped.append(row["code"])
    return {
        "framework_id": framework.pk,
        "framework_name": framework.name,
        "template_kind": spec_kind,
        "template_name": template_lib.get_template(spec_kind)["name"],
        "total": len(rows),
        "created": len(created),
        "updated": len(updated),
        "skipped": len(skipped),
        "created_codes": created[:50],
        "updated_codes": updated[:50],
        "update_existing": bool(update_existing),
    }


# ---------------------------------------------------------------------------
# 12. 合规日历：把散落在各表的「到期日」聚成一条时间线
# ---------------------------------------------------------------------------

# 日历来源：顺序即前端默认分组顺序。键名用英文常量而不是中文，
# 方便前端做筛选与图标映射；中文标签统一从这里取，避免两处不一致。
CALENDAR_SOURCES = (
    "policy_review",
    "assessment_deadline",
    "control_test",
    "evidence_expiry",
    "remediation_due",
    "finding_due",
    "retention_due",
    "consent_expiry",
    "risk_review",
)
CALENDAR_SOURCE_LABELS = {
    "policy_review": "策略评审",
    "assessment_deadline": "评估截止",
    "control_test": "控制测试",
    "evidence_expiry": "证据到期",
    "remediation_due": "整改进度",
    "finding_due": "审计发现",
    "retention_due": "保留期动作",
    "consent_expiry": "同意到期",
    "risk_review": "风险复核",
}


def _calendar_event(kind, title, due_on, ref_id, status="", owner_name="", priority=2):
    """构造一条日历事件（内部助手）：统一计算剩余天数与逾期标记。"""
    remaining = (due_on - today()).days
    return {
        "kind": kind,
        "kind_label": CALENDAR_SOURCE_LABELS.get(kind, kind),
        "title": title,
        "due_on": due_on.isoformat(),
        "days_remaining": remaining,
        "overdue": remaining < 0,
        "status": status,
        "owner_name": owner_name,
        "ref_id": ref_id,
        "priority": priority,
    }


def compliance_calendar(owner, days=30, sources=None):
    """合规日历：窗口内所有到期事项（含已逾期），按到期日排序。

    「已逾期」无论窗口多短都会返回：逾期事项的价值恰恰在于立刻被看到，
    如果按 days 截断，用户把窗口设成 7 天反而看不到最该处理的东西。

    所有来源只读不写：日历是视图，不是台账。需要落地的动作由各自模块的
    扫描/执行接口完成，避免「打开日历就改数据」的副作用。
    """
    days = int(days if days is not None else 30)
    cutoff = today() + timedelta(days=max(days, 0))
    wanted = [s for s in (sources or CALENDAR_SOURCES) if s in CALENDAR_SOURCES]
    events = []

    def in_window(value):
        return bool(value and value <= cutoff)

    if "policy_review" in wanted:
        rows = Policy.objects.filter(
            owner=owner, status__in=("approved", "published"),
            next_review_on__isnull=False, next_review_on__lte=cutoff)
        for policy in rows:
            events.append(_calendar_event(
                "policy_review", f"评审策略：{policy.name}", policy.next_review_on,
                policy.pk, policy.status, policy.owner_name, priority=2))

    if "assessment_deadline" in wanted:
        rows = Assessment.objects.filter(
            owner=owner, status__in=("planned", "in_progress"),
            end_on__isnull=False, end_on__lte=cutoff)
        for assessment in rows:
            events.append(_calendar_event(
                "assessment_deadline", f"完成评估：{assessment.name}", assessment.end_on,
                assessment.pk, assessment.status, assessment.lead_name, priority=2))

    if "control_test" in wanted:
        # 控制测试是「周期还没到但快到了」的前瞻计划，与 gaps 的「已超期」
        # 互补：一个催排期，一个报欠账。
        rows = Control.objects.filter(owner=owner, status="active").exclude(frequency="once")
        for control in rows:
            window = FREQUENCY_WINDOW_DAYS.get(control.frequency)
            if not window:
                continue
            anchor = control.last_tested_at or control.created_at
            anchor_date = anchor.date() if hasattr(anchor, "date") else anchor
            due_on = anchor_date + timedelta(days=window)
            if in_window(due_on):
                events.append(_calendar_event(
                    "control_test", f"测试控制：{control.name}", due_on,
                    control.pk, control.frequency, "", priority=3 if due_on < today() else 2))

    if "evidence_expiry" in wanted:
        rows = Evidence.objects.filter(
            owner=owner, expires_on__isnull=False, expires_on__lte=cutoff)
        for evidence in rows:
            events.append(_calendar_event(
                "evidence_expiry", f"续期证据：{evidence.name}", evidence.expires_on,
                evidence.pk, evidence.kind, evidence.collected_by_name, priority=1))

    if "remediation_due" in wanted:
        rows = RemediationTask.objects.filter(
            owner=owner, due_on__isnull=False, due_on__lte=cutoff
        ).exclude(status__in=("done", "verified"))
        for task in rows:
            events.append(_calendar_event(
                "remediation_due", f"完成整改：{task.finding.title if task.finding_id else task.measure[:40]}",
                task.due_on, task.pk, task.status, task.owner_name, priority=3))

    if "finding_due" in wanted:
        rows = Finding.objects.filter(
            owner=owner, due_on__isnull=False, due_on__lte=cutoff
        ).exclude(status__in=("resolved", "verified"))
        for finding in rows:
            events.append(_calendar_event(
                "finding_due", f"关闭发现：{finding.title}", finding.due_on,
                finding.pk, finding.status, finding.remediation_owner,
                priority=3 if finding.severity in ("high", "critical") else 2))

    if "retention_due" in wanted:
        rows = RetentionAction.objects.filter(
            owner=owner, status="planned", due_on__isnull=False, due_on__lte=cutoff)
        for action in rows:
            label = action.resource_name or action.resource_kind
            events.append(_calendar_event(
                "retention_due", f"执行保留期动作：{label}",
                action.due_on, action.pk, action.status, "", priority=1))

    if "consent_expiry" in wanted:
        rows = ConsentRecord.objects.filter(
            owner=owner, status="granted", expires_on__isnull=False, expires_on__lte=cutoff)
        for consent in rows:
            events.append(_calendar_event(
                "consent_expiry", f"续签同意：{consent.data_subject}", consent.expires_on,
                consent.pk, consent.status, "", priority=1))

    if "risk_review" in wanted:
        rows = Risk.objects.filter(
            owner=owner, review_on__isnull=False, review_on__lte=cutoff
        ).exclude(status="closed")
        for risk in rows:
            events.append(_calendar_event(
                "risk_review", f"复核风险：{risk.name}", risk.review_on,
                risk.pk, risk.status, risk.owner_name,
                priority=3 if risk.level in ("high", "critical") else 2))

    events.sort(key=lambda row: (row["due_on"], -row["priority"], row["title"]))
    by_kind = {source: 0 for source in wanted}
    for event in events:
        by_kind[event["kind"]] = by_kind.get(event["kind"], 0) + 1
    overdue = [event for event in events if event["overdue"]]
    due_soon = [event for event in events if 0 <= event["days_remaining"] <= 7]
    return {
        "window_days": days,
        "cutoff": cutoff.isoformat(),
        "today": today().isoformat(),
        "count": len(events),
        "overdue": len(overdue),
        "due_soon": len(due_soon),
        "by_kind": by_kind,
        "sources": list(wanted),
        "items": events,
    }


def _ics_escape(text):
    """iCalendar 文本转义：反斜杠、分号、逗号与换行都有语法含义。"""
    value = str(text or "")
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return value.replace("\r\n", "\\n").replace("\n", "\\n")


def _ics_fold(line):
    """按 RFC 5545 折行：每行不超过 75 个八位字节，续行以空格开头。"""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    chunks = []
    while raw:
        take = 74 if not chunks else 73
        # 避免在多字节字符中间切断：逐字节回退到 UTF-8 边界
        cut = min(take, len(raw))
        while cut > 0 and (raw[cut - 1] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(raw[:cut].decode("utf-8", "ignore"))
        raw = raw[cut:]
    return [chunks[0]] + [" " + chunk for chunk in chunks[1:]]


def calendar_ics(owner, days=30, sources=None):
    """把合规日历导出为 iCalendar 文本（全天事件，可导入日历客户端）。

    不落文件、不写库：返回文本由前端下载，避免在服务端留下「谁的日历」
    这类可推断个人工作安排的痕迹。
    """
    data = compliance_calendar(owner, days=days, sources=sources)
    stamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//QoderCN//Governance Calendar//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in data["items"]:
        day = event["due_on"].replace("-", "")
        summary = f"[{event['kind_label']}] {event['title']}"
        description = (
            f"状态: {event['status'] or '-'}；剩余 {event['days_remaining']} 天"
            + ("（已逾期）" if event["overdue"] else "")
        )
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:gov-{event['kind']}-{event['ref_id']}@governance.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            f"CATEGORIES:{_ics_escape(event['kind_label'])}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    folded = []
    for line in lines:
        folded.extend(_ics_fold(line))
    content = "\r\n".join(folded) + "\r\n"
    return {
        "filename": f"governance-calendar-{today().isoformat()}.ics",
        "format": "ics",
        "event_total": len(data["items"]),
        "window_days": data["window_days"],
        "content": content,
    }


# ---------------------------------------------------------------------------
# 13. 控制测试计划：按频率推算下次应测日期
# ---------------------------------------------------------------------------


def control_test_plan(owner, days=30):
    """控制测试计划：未来 N 天内应执行的控制测试（前瞻口径）。

    与 control_gaps 的区别：gaps 报「已经欠账」，本接口排「即将到期」。
    锚点取 last_tested_at，从未测过则取创建时间——刚建的控制不会一上来
    就被判超期，但超过一个完整周期仍未测就会进入计划。
    """
    days = int(days if days is not None else 30)
    cutoff = today() + timedelta(days=max(days, 0))
    rows = Control.objects.filter(owner=owner, status="active").exclude(frequency="once")
    items = []
    for control in rows:
        window = FREQUENCY_WINDOW_DAYS.get(control.frequency)
        if not window:
            continue
        anchor = control.last_tested_at or control.created_at
        anchor_date = anchor.date() if hasattr(anchor, "date") else anchor
        due_on = anchor_date + timedelta(days=window)
        if due_on > cutoff:
            continue
        items.append({
            "control_id": control.pk,
            "code": control.code,
            "name": control.name,
            "category": control.category,
            "frequency": control.frequency,
            "last_tested_at": control.last_tested_at.isoformat() if control.last_tested_at else None,
            "due_on": due_on.isoformat(),
            "days_remaining": (due_on - today()).days,
            "overdue": due_on < today(),
            "effectiveness": control.effectiveness,
        })
    items.sort(key=lambda row: (row["due_on"], row["code"]))
    return {
        "window_days": days,
        "cutoff": cutoff.isoformat(),
        "count": len(items),
        "overdue": sum(1 for row in items if row["overdue"]),
        "items": items,
    }


# ---------------------------------------------------------------------------
# 14. 责任分布：按负责人聚合待办，识别「忙不过来」的人
# ---------------------------------------------------------------------------


def workload_summary(owner, limit=50):
    """按负责人聚合未结事项（审计发现/整改/风险处置/评估）。

    同名视为同一人：治理场景里负责人是姓名文本而非账号体系，强行关联
    users 表会让「外部审计师」「供应商联系人」无法登记。聚合结果用于
    发现超载，不用于绩效，因此口径是「未结事项条数」而非工时。
    """
    buckets = {}

    def push(name, kind, overdue=False):
        key = (name or "").strip() or "未指派"
        bucket = buckets.setdefault(key, {
            "owner_name": key,
            "total": 0,
            "overdue": 0,
            "by_kind": {},
        })
        bucket["total"] += 1
        bucket["overdue"] += 1 if overdue else 0
        bucket["by_kind"][kind] = bucket["by_kind"].get(kind, 0) + 1

    for finding in Finding.objects.filter(owner=owner).exclude(status__in=("resolved", "verified")):
        push(finding.remediation_owner, "finding", finding.is_overdue())

    for task in RemediationTask.objects.filter(owner=owner).exclude(status__in=("done", "verified")):
        push(task.owner_name, "remediation", task.is_overdue())

    for treatment in RiskTreatment.objects.filter(owner=owner).exclude(status__in=("done", "cancelled")):
        overdue = bool(treatment.due_on and treatment.due_on < today()
                       and treatment.status != "done")
        push(treatment.owner_name, "treatment", overdue)

    for risk in Risk.objects.filter(owner=owner).exclude(status="closed"):
        push(risk.owner_name, "risk_top" if risk.level in ("high", "critical") else "risk")

    for assessment in Assessment.objects.filter(owner=owner, status__in=("planned", "in_progress")):
        push(assessment.lead_name, "assessment", assessment.effective_status() == "overdue")

    items = sorted(buckets.values(), key=lambda row: (-row["total"], -row["overdue"], row["owner_name"]))
    for row in items:
        # 评分让「量大且逾期多」的人排前面：逾期权重高于条数，
        # 因为合规整改的逾期本身就是监管风险。
        row["load_score"] = row["total"] + row["overdue"] * 2
    items.sort(key=lambda row: (-row["load_score"], row["owner_name"]))
    return {
        "count": len(items),
        "unassigned": next((row["total"] for row in items if row["owner_name"] == "未指派"), 0),
        "items": items[:max(1, int(limit or 50))],
    }


# ---------------------------------------------------------------------------
# 15. 导出：CSV 文本（不落文件，前端直接下载）
# ---------------------------------------------------------------------------


def csv_cell(value):
    """单元格转义：防 CSV 公式注入 + 统一 None/日期格式。

    以 = + - @ 开头的文本会被 Excel 当公式执行（=HYPERLINK 等），
    治理数据里「风险名称」是自由文本，必须加前缀单引号阻断。
    """
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "是" if value else "否"
    elif isinstance(value, (date, datetime)):
        text = value.isoformat()
    elif isinstance(value, Decimal):
        text = f"{value:.2f}"
    else:
        text = str(value)
    # 换行与引号交给 csv 模块处理，这里只处理公式前缀。
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return text


def to_csv(headers, rows):
    """把二维数据渲染为 CSV 文本（逗号分隔、CRLF 行尾，兼容 Excel）。"""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([csv_cell(item) for item in headers])
    for row in rows:
        writer.writerow([csv_cell(item) for item in row])
    return buffer.getvalue()


def _export_payload(name, headers, rows, limit):
    """统一导出结构：元数据 + 表头 + 行 + 文本，前端可预览也可下载。"""
    limited = rows[:limit]
    return {
        "filename": f"{name}-{today().isoformat()}.csv",
        "format": "csv",
        "headers": headers,
        "count": len(limited),
        "truncated": len(rows) > limit,
        "content": to_csv(headers, limited),
    }


def export_risks(owner, limit=5000):
    """导出风险台账（含固有/剩余分与等级）。"""
    headers = ["编号", "名称", "类别", "可能性", "影响", "固有分", "剩余分",
               "等级", "状态", "负责人", "复核日"]
    rows = [
        [risk.code, risk.name, risk.category, risk.likelihood, risk.impact,
         risk.inherent_score, risk.residual_score, risk.level, risk.status,
         risk.owner_name, risk.review_on]
        for risk in Risk.objects.filter(owner=owner).order_by("code")
    ]
    return _export_payload("governance-risks", headers, rows, limit)


def export_findings(owner, limit=5000):
    """导出审计发现台账（含严重度、整改负责人与逾期标记）。"""
    headers = ["审计", "发现标题", "严重度", "状态", "整改负责人", "截止日", "逾期", "关闭日"]
    rows = [
        [finding.audit.name if finding.audit_id else "", finding.title, finding.severity,
         finding.status, finding.remediation_owner, finding.due_on,
         finding.is_overdue(), finding.closed_on]
        for finding in Finding.objects.filter(owner=owner).select_related("audit").order_by("-created_at")
    ]
    return _export_payload("governance-findings", headers, rows, limit)


def export_controls(owner, limit=5000):
    """导出内部控制台账（频率、自动化、有效性与最近测试时间）。"""
    headers = ["编号", "名称", "类别", "频率", "自动化", "状态", "有效性%", "最近测试", "映射数"]
    rows = [
        [control.code, control.name, control.category, control.frequency,
         control.automated, control.status, control.effectiveness,
         control.last_tested_at, control.framework_mappings.count()]
        for control in Control.objects.filter(owner=owner).order_by("code")
    ]
    return _export_payload("governance-controls", headers, rows, limit)


def export_assessment_items(owner, assessment_id=None, limit=5000):
    """导出评估项明细（可按 assessment_id 限定单次评估）。"""
    qs = AssessmentItem.objects.filter(owner=owner).select_related(
        "assessment", "framework_control", "control")
    if assessment_id:
        qs = qs.filter(assessment_id=assessment_id)
    headers = ["评估", "条款编号", "条款标题", "状态", "权重", "得分系数", "证据说明", "备注"]
    coefficient = {"passed": 1, "in_progress": 0.5, "failed": 0}
    rows = []
    for item in qs.order_by("assessment_id", "id"):
        rows.append([
            item.assessment.name if item.assessment_id else "",
            item.framework_control.code if item.framework_control_id else (item.control.code if item.control_id else ""),
            item.framework_control.title if item.framework_control_id else (item.control.name if item.control_id else ""),
            item.status,
            item.weight,
            coefficient.get(item.status, ""),
            item.evidence_note,
            item.note,
        ])
    return _export_payload("governance-assessment-items", headers, rows, limit)


def export_retention_actions(owner, limit=5000):
    """导出保留期动作台账（便于交给法务/存储团队执行）。"""
    headers = ["资源类型", "资源名称", "动作", "状态", "到期日", "执行时间", "说明"]
    rows = [
        [action.resource_kind, action.resource_name, action.action, action.status,
         action.due_on, action.executed_at, action.note]
        for action in RetentionAction.objects.filter(owner=owner).order_by("due_on", "id")
    ]
    return _export_payload("governance-retention-actions", headers, rows, limit)
