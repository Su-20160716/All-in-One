# -*- coding: utf-8 -*-
"""应用市场 · 服务层（纯业务计算，视图只做编排）。

模块内容
--------
1. 语义化版本：解析 / 比较 / 范围约束（>= > <= < ^ ~ =，支持 || 与空格 AND）；
2. 安装解析：平台兼容 + 已装依赖 + 依赖传递，冲突给出可读原因；
3. 许可证：密钥哈希比对、有效期、激活次数、应用一致性；
4. 评分聚合：加权平均 + 分布 + 隐藏评价后重算；
5. 搜索排序：关键词（标题/标签/简介/详情）+ 评分 + 安装量 + 推荐位；
6. 收入分成：平台抽成、退款冲减、按发布者/按月汇总；
7. 升级检查：当前版本 → 最新可升级版本 + 变更说明 + 是否破坏性；
8. 合集管理：发布校验、排序去重；
9. 举报处置状态机；
10. 市场统计：分类分布、发布者 TOP、安装趋势、评分分布、收入汇总。

实现原则
--------
- 所有金额用 Decimal 计算并 quantize 到分，禁止 float 参与分成；
- 所有对外函数失败时抛 ValueError（中文提示），由 @endpoint 统一转 400；
- 不访问网络：Webhook 投递用本地模拟（见 deliver_event 注释）。
"""
import hashlib
import math
import re
import secrets
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from .models import (
    CURRENCY_CHOICES,
    INSTALL_ACTIVE_STATUS,
    LISTING_PUBLIC_STATUS,
    PLATFORM_VERSION,
    REPORT_TRANSITIONS,
    Category,
    Collection,
    CollectionItem,
    CompatibilityTag,
    Install,
    License,
    Listing,
    ListingReport,
    ListingVersion,
    MarketplaceEvent,
    Pricing,
    Publisher,
    Purchase,
    Review,
    Screenshot,
    WebhookDelivery,
    WebhookSubscription,
)

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
# 固定汇率表（本地模拟，不联网取价）：所有跨币种汇总折算成 CNY。
CURRENCY_RATES = {
    "CNY": Decimal("1"),
    "USD": Decimal("7.20"),
    "EUR": Decimal("7.80"),
}
CURRENCY_VALUES = tuple(item[0] for item in CURRENCY_CHOICES)


def money(value):
    """统一金额口径：Decimal → 两位小数（四舍五入到分）。"""
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def money_out(value):
    """金额输出为 float，便于 JSON 序列化（内部一律用 Decimal 计算）。"""
    return float(money(value))


def to_cny(amount, currency="CNY"):
    """按固定汇率折算人民币；未知币种按 1:1 兜底并保持可解释。"""
    rate = CURRENCY_RATES.get(str(currency or "CNY").upper(), Decimal("1"))
    return money(Decimal(str(amount or 0)) * rate)


# ===========================================================================
# 1. 语义化版本
# ===========================================================================

# 严格要求 major.minor.patch；pre-release 与 build 元数据可省略。
# 比较时 build 不参与（SemVer 2.0 规定），pre-release 优先级低于正式版。
_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)
# 约束里的版本允许 1~3 段（~1.2 / ^1），便于运营配置时少写零。
_CONSTRAINT_VERSION_RE = re.compile(
    r"^(>=|<=|>|<|==|=|\^|~)?\s*v?(\d+(?:\.\d+){0,2})(?:-([0-9A-Za-z.-]+))?$"
)
_OPERATOR_VALUES = (">=", "<=", ">", "<", "=", "==", "^", "~")


def _pre_tokens(raw):
    """拆分 pre-release 标识；空串表示正式版。"""
    if not raw:
        return ()
    return tuple(raw.split("."))


def parse_version(raw, field="版本号"):
    """解析严格语义化版本 → 结构化 dict（含可供排序的 key）。

    失败抛 ValueError：调用方（版本创建/范围解析）需要明确的 400 提示，
    而不是静默把非法版本当 0.0.0 处理（那会把兼容判断整体带偏）。
    """
    text = str(raw if raw is not None else "").strip()
    match = _VERSION_RE.match(text)
    if not match:
        raise ValueError(
            f"{field} “{text}” 不是合法的语义化版本，格式应为 major.minor.patch[-pre][+build]"
        )
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    pre = _pre_tokens(match.group(4))
    build = _pre_tokens(match.group(5))
    return {
        "raw": text.lstrip("v"),
        "major": major,
        "minor": minor,
        "patch": patch,
        "prerelease": pre,
        "build": build,
        "is_prerelease": bool(pre),
    }


def is_valid_version(raw):
    """宽松判定（下拉过滤/导入数据清洗用，不抛异常）。"""
    try:
        parse_version(raw)
        return True
    except ValueError:
        return False


def _cmp(a, b):
    return (a > b) - (a < b)


def _compare_pre(left, right):
    """pre-release 比较：数字段按数值，字符串段按字典序；数字 < 字符串。"""
    if not left and not right:
        return 0
    if not left:
        return 1  # 正式版 > 预发布版
    if not right:
        return -1
    for i in range(max(len(left), len(right))):
        if i >= len(left):
            return -1
        if i >= len(right):
            return 1
        x, y = left[i], right[i]
        x_num, y_num = x.isdigit(), y.isdigit()
        if x_num and y_num:
            if int(x) != int(y):
                return _cmp(int(x), int(y))
            continue
        if x_num != y_num:
            # 数字标识符优先级低于字母数字标识符
            return -1 if x_num else 1
        if x != y:
            return _cmp(x, y)
    return 0


def compare_versions(left, right):
    """比较两个版本字符串：返回 -1 / 0 / 1。"""
    a = parse_version(left, "版本号")
    b = parse_version(right, "版本号")
    for key in ("major", "minor", "patch"):
        if a[key] != b[key]:
            return _cmp(a[key], b[key])
    return _compare_pre(a["prerelease"], b["prerelease"])


def sort_versions(versions, reverse=True):
    """版本字符串列表排序（默认从新到旧）。"""
    from functools import cmp_to_key

    return sorted(list(versions), key=cmp_to_key(compare_versions), reverse=reverse)


def highest_version(versions):
    """取最高版本；空列表返回 None。"""
    ordered = sort_versions([v for v in versions if is_valid_version(v)], reverse=True)
    return ordered[0] if ordered else None


def _padded(raw, field="版本号"):
    """把 1~3 段版本补零成 major.minor.patch，便于范围展开。"""
    text = str(raw or "").strip()
    if text.count(".") >= 2:
        parse_version(text, field)
        return text
    parts = [int(p) for p in text.lstrip("v").split(".") if p != ""]
    if not parts:
        raise ValueError(f"{field} “{text}” 不是合法的版本号")
    while len(parts) < 3:
        parts.append(0)
    return ".".join(str(p) for p in parts)


def parse_range(expression, field="版本范围"):
    """解析范围表达式 → 若干 OR 分组，每组是 AND 的 (op, version)。

    支持：``>=1.2.0``、``>=1.0.0 <2.0.0``、``^1.4.0``、``~1.4``、``1.2.3``、
    ``*``（任意）、``||``（或）。空表达式视为任意版本，便于可选依赖。
    """
    text = str(expression or "").strip()
    if not text or text == "*":
        return [[("*", None)]]
    groups = []
    for chunk in text.split("||"):
        chunk = chunk.strip()
        if not chunk:
            continue
        tokens = [t for t in re.split(r"[\s,]+", chunk) if t]
        group = []
        for token in tokens:
            match = _CONSTRAINT_VERSION_RE.match(token)
            if not match:
                raise ValueError(f"{field} “{expression}” 含无法识别的约束 “{token}”")
            op = match.group(1) or "="
            raw_version = match.group(2)
            pre = match.group(3)
            provided = len(raw_version.split("."))
            base = _padded(raw_version, field)
            if pre:
                base = f"{base}-{pre}"
            group.extend(_expand_constraint(op, base, provided))
        if not group:
            raise ValueError(f"{field} “{expression}” 没有有效约束")
        groups.append(group)
    if not groups:
        return [[("*", None)]]
    return groups


def _expand_constraint(op, base, provided):
    """把 ^ / ~ 展开成 >= 与 < 的组合，其余原样保留。"""
    parsed = parse_version(base, "版本范围")
    major, minor, patch = parsed["major"], parsed["minor"], parsed["patch"]
    if op in ("=", "=="):
        return [("=", base)]
    if op in (">=", ">", "<=", "<"):
        return [(op, base)]
    if op == "^":
        # ^1.2.3 → >=1.2.3 <2.0.0；^0.2.3 → >=0.2.3 <0.3.0；^0.0.3 → <0.0.4
        if major > 0 or provided == 1:
            upper = f"{major + 1}.0.0"
        elif minor > 0 or provided == 2:
            upper = f"0.{minor + 1}.0"
        else:
            upper = f"0.0.{patch + 1}"
        return [(">=", base), ("<", upper)]
    if op == "~":
        # ~1.4.2 → >=1.4.2 <1.5.0；~1.4 → >=1.4.0 <1.5.0；~1 → >=1.0.0 <2.0.0
        if provided <= 1:
            upper = f"{major + 1}.0.0"
        else:
            upper = f"{major}.{minor + 1}.0"
        return [(">=", base), ("<", upper)]
    raise ValueError(f"不支持的版本运算符 {op}")


def _matches(version, op, target):
    if op == "*":
        return True
    result = compare_versions(version, target)
    if op == "=":
        return result == 0
    if op == ">=":
        return result >= 0
    if op == ">":
        return result > 0
    if op == "<=":
        return result <= 0
    if op == "<":
        return result < 0
    return False


def satisfies(version, expression):
    """版本是否满足范围表达式（OR 组之间任一满足，组内全部满足）。

    SemVer 约定：不含预发布标识的范围默认不匹配预发布版本，避免
    ``>=1.0.0`` 把 2.0.0-beta 误判为可安装的稳定版本。
    """
    parsed = parse_version(version, "版本号")
    groups = parse_range(expression, "版本范围")
    for group in groups:
        if not group:
            continue
        allow_pre = any(
            op != "*" and target and "-" in str(target) for op, target in group
        )
        if parsed["is_prerelease"] and not allow_pre:
            continue
        if all(_matches(version, op, target) for op, target in group):
            return True
    return False


def explain_satisfies(version, expression):
    """范围判定明细（排障/前端提示用）。"""
    try:
        parsed = parse_version(version, "版本号")
        groups = parse_range(expression, "版本范围")
    except ValueError as exc:
        return {"valid": False, "reason": str(exc)}
    detail = []
    for group in groups:
        checks = []
        for op, target in group:
            checks.append({
                "operator": op,
                "target": target,
                "pass": _matches(version, op, target) if op != "*" else True,
            })
        detail.append(checks)
    return {
        "version": parsed["raw"],
        "range": expression or "*",
        "satisfied": satisfies(version, expression),
        "prerelease": parsed["is_prerelease"],
        "groups": detail,
    }


def max_satisfying(versions, expression, include_prerelease=False):
    """在候选版本里取满足范围的最大版本；没有返回 None。"""
    candidates = []
    for raw in versions:
        if not include_prerelease and is_valid_version(raw) and parse_version(raw)["is_prerelease"]:
            continue
        try:
            if satisfies(raw, expression):
                candidates.append(raw)
        except ValueError:
            continue
    return highest_version(candidates)


def next_version(version, part="patch"):
    """按 major/minor/patch 递增（发版草稿用）。"""
    parsed = parse_version(version, "版本号")
    if part not in ("major", "minor", "patch"):
        raise ValueError("part 支持 major/minor/patch")
    if part == "major":
        return f"{parsed['major'] + 1}.0.0"
    if part == "minor":
        return f"{parsed['major']}.{parsed['minor'] + 1}.0"
    return f"{parsed['major']}.{parsed['minor']}.{parsed['patch'] + 1}"


def is_breaking_change(old, new):
    """是否破坏性升级：主版本变化，或 0.x 时代次版本变化。"""
    a = parse_version(old, "旧版本")
    b = parse_version(new, "新版本")
    if b["major"] != a["major"]:
        return True
    # 0.x 阶段 API 未稳定，次版本提升默认视为破坏性
    return a["major"] == 0 and b["minor"] != a["minor"]


def diff_versions(old, new):
    """版本差异：方向、级别与序号差。"""
    a = parse_version(old, "旧版本")
    b = parse_version(new, "新版本")
    direction = "same"
    cmp_result = compare_versions(old, new)
    # compare_versions(old, new) < 0 表示 new 更高，方向应从「旧 → 新」判断
    if cmp_result < 0:
        direction = "upgrade"
    elif cmp_result > 0:
        direction = "downgrade"
    level = "patch"
    if a["major"] != b["major"]:
        level = "major"
    elif a["minor"] != b["minor"]:
        level = "minor"
    return {
        "from": a["raw"],
        "to": b["raw"],
        "direction": direction,
        "level": level,
        "breaking": is_breaking_change(old, new),
        "major_delta": b["major"] - a["major"],
        "minor_delta": b["minor"] - a["minor"],
        "patch_delta": b["patch"] - a["patch"],
    }


# ===========================================================================
# 2. 平台兼容与安装解析
# ===========================================================================


def platform_compatible(version, platform_version=None):
    """版本的最低平台要求是否被当前平台满足。"""
    target = platform_version or PLATFORM_VERSION
    minimum = getattr(version, "min_platform_version", "") or "0.0.0"
    return compare_versions(minimum, target) <= 0


def published_versions(listing, platform_version=None, include_incompatible=False):
    """应用的已发布版本，按版本从新到旧；可选过滤平台不兼容项。"""
    queryset = listing.mp_versions.filter(status="published")
    versions = [v for v in queryset if is_valid_version(v.version)]
    if platform_version and not include_incompatible:
        versions = [v for v in versions if platform_compatible(v, platform_version)]
    return sorted(versions, key=lambda v: _version_sort_key(v.version), reverse=True)


def _version_sort_key(raw):
    """版本排序 key：与 compare_versions 等价，但可被 sorted 直接使用。"""
    parsed = parse_version(raw)
    # 预发布版排在同号正式版之前，用 0/1 标记后再跟 pre 段
    pre_flag = 0 if parsed["is_prerelease"] else 1
    pre = []
    for token in parsed["prerelease"]:
        pre.append((0, int(token), "") if token.isdigit() else (1, 0, token))
    return (parsed["major"], parsed["minor"], parsed["patch"], pre_flag, tuple(pre))


def best_version_for_platform(listing, platform_version=None, expression=""):
    """在平台兼容范围内挑最高版本（可叠加额外范围约束）。"""
    candidates = []
    for version in published_versions(listing, platform_version):
        if expression:
            try:
                if not satisfies(version.version, expression):
                    continue
            except ValueError:
                continue
        candidates.append(version)
    return candidates[0] if candidates else None


def best_any_version(listing, allow_delisted=False, platform_version=None):
    """不限发布状态的最高版本（审核/提交时用来挑待发布版本）。

    与 best_version_for_platform 的区别：后者只认 published，用于安装解析；
    这里允许草稿版本，因为「提交审核 → 审核通过自动发布」需要覆盖草稿。
    """
    queryset = listing.mp_versions.all()
    if not allow_delisted:
        queryset = queryset.exclude(status="delisted")
    versions = [v for v in queryset if is_valid_version(v.version)]
    if platform_version:
        versions = [v for v in versions if platform_compatible(v, platform_version)]
    versions.sort(key=lambda v: _version_sort_key(v.version), reverse=True)
    return versions[0] if versions else None


def resolve_install(listing, platform_version=None, installed_versions=None,
                    user=None, max_depth=6):
    """安装解析：根据平台版本与已装依赖，选出可安装的最新版本。

    返回结构：
        ok           是否可完成解析（无冲突）
        listing      被安装应用标识
        resolved     主应用的版本信息
        plan         安装/升级动作列表（含依赖）
        conflicts    冲突列表（code + reason + required_by + 已装版本）
        warnings     非阻断提示（被替换的旧版本、周期依赖等）
        checked      解析过的应用数量
    冲突时 resolved 为 None，但仍会尽量收集全部冲突而不是遇到第一个就返回，
    便于前端一次性告知用户。
    """
    target_platform = platform_version or PLATFORM_VERSION
    installed_map = {str(k): str(v) for k, v in (installed_versions or {}).items()}
    result = {
        "ok": True,
        "listing": listing.code,
        "platform_version": target_platform,
        "resolved": None,
        "plan": [],
        "conflicts": [],
        "warnings": [],
        "checked": 0,
    }
    if listing.status != "published":
        result["ok"] = False
        result["conflicts"].append({
            "code": listing.code,
            "required_by": None,
            "range": "",
            "installed": installed_map.get(listing.code),
            "reason": "应用未上架，不能安装",
        })
        return result

    visited = {}
    queue = [(listing, "", None, 0)]
    while queue:
        current, required_range, required_by, depth = queue.pop(0)
        if depth > max_depth:
            result["warnings"].append({
                "code": current.code,
                "message": f"依赖层级超过 {max_depth} 层，已停止继续解析",
            })
            continue
        key = (current.id, required_range)
        if key in visited:
            continue
        visited[key] = True
        result["checked"] += 1

        candidate = best_version_for_platform(current, target_platform, required_range)
        if candidate is None:
            all_versions = published_versions(current, None, include_incompatible=True)
            if not all_versions:
                reason = "没有已发布的版本"
            elif not any(platform_compatible(v, target_platform) for v in all_versions):
                reason = f"所有版本都要求更高的平台版本（当前 {target_platform}）"
            else:
                reason = f"没有满足版本范围 “{required_range or '*'}`” 的版本"
            result["conflicts"].append({
                "code": current.code,
                "required_by": required_by,
                "range": required_range,
                "installed": installed_map.get(current.code),
                "reason": reason,
            })
            continue

        installed_version = installed_map.get(current.code)
        action = "install"
        if installed_version:
            try:
                if satisfies(installed_version, required_range or "*"):
                    action = "keep"
                elif compare_versions(installed_version, candidate.version) < 0:
                    action = "upgrade"
                else:
                    action = "downgrade"
                    result["warnings"].append({
                        "code": current.code,
                        "message": f"已安装 {installed_version} 高于目标 {candidate.version}，将降级",
                    })
            except ValueError:
                action = "upgrade"
                result["warnings"].append({
                    "code": current.code,
                    "message": f"已安装版本 {installed_version} 非法，将按目标版本覆盖",
                })

        entry = {
            "code": current.code,
            "name": current.name,
            "listing_id": current.id,
            "version": candidate.version,
            "version_id": candidate.id,
            "installed_version": installed_version,
            "action": action,
            "required_by": required_by,
            "required_range": required_range,
        }
        if current.id == listing.id:
            result["resolved"] = entry
        if action != "keep":
            result["plan"].append(entry)

        # 递归解析 manifest.requires；同一应用不同约束分别校验，避免漏冲突
        requires = (candidate.manifest or {}).get("requires") or []
        if not isinstance(requires, list):
            result["warnings"].append({
                "code": current.code,
                "message": "manifest.requires 不是数组，已跳过依赖解析",
            })
            requires = []
        for requirement in requires:
            if not isinstance(requirement, dict):
                continue
            dep_code = str(requirement.get("code") or "").strip()
            dep_range = str(requirement.get("range") or "").strip()
            if not dep_code:
                continue
            dep = Listing.objects.filter(code=dep_code).first()
            if dep is None:
                result["conflicts"].append({
                    "code": dep_code,
                    "required_by": current.code,
                    "range": dep_range,
                    "installed": installed_map.get(dep_code),
                    "reason": f"{current.code} 依赖的应用 {dep_code} 不存在",
                })
                continue
            queue.append((dep, dep_range, current.code, depth + 1))

    result["ok"] = not result["conflicts"]
    if not result["ok"]:
        result["resolved"] = None
    return result


def installed_version_map(user):
    """当前用户已安装应用的 {code: version} 映射（解析器输入）。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    rows = (Install.objects.filter(owner=user, status__in=INSTALL_ACTIVE_STATUS)
            .select_related("listing", "version"))
    return {
        row.listing.code: (row.version.version if row.version_id else "")
        for row in rows
    }


# ===========================================================================
# 3. 许可证
# ===========================================================================

_LICENSE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混淆的 I/O/0/1


def generate_license_key():
    """生成 MKT-XXXX-XXXX-XXXX-XXXX 形式的许可证密钥（明文只返回一次）。"""
    groups = [
        "".join(secrets.choice(_LICENSE_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]
    return "MKT-" + "-".join(groups)


def hash_license_key(key):
    """密钥哈希：SHA-256（大小写与空白归一化），数据库中只存哈希。"""
    normalized = str(key or "").strip().upper().replace(" ", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mask_license_key(key):
    """展示用提示：只保留最后一组，避免日志/列表泄露完整密钥。"""
    text = str(key or "").strip()
    if len(text) <= 4:
        return "****"
    return "****-" + text[-4:]


def license_expired(license_obj, now=None):
    """是否已过期（无到期时间视为永久有效）。"""
    if license_obj.expires_at is None:
        return False
    return license_obj.expires_at < (now or timezone.now())


def license_snapshot(license_obj, now=None):
    """许可证概览：有效期、激活使用、剩余天数。"""
    now = now or timezone.now()
    activations = license_obj.activations or []
    if not isinstance(activations, list):
        activations = []
    remaining = None
    if license_obj.expires_at is not None:
        remaining = max(0, (license_obj.expires_at - now).days)
    return {
        "id": license_obj.id,
        "listing_id": license_obj.listing_id,
        "listing_code": license_obj.listing.code,
        "type": license_obj.type,
        "status": license_obj.status,
        "expired": license_expired(license_obj, now),
        "expires_at": license_obj.expires_at.isoformat() if license_obj.expires_at else None,
        "remaining_days": remaining,
        "activation_count": len(activations),
        "max_activations": license_obj.max_activations,
        "devices": [
            {"device_id": item.get("device_id"), "at": item.get("at")}
            for item in activations if isinstance(item, dict)
        ],
        "last_verified_at": (
            license_obj.last_verified_at.isoformat()
            if license_obj.last_verified_at else None
        ),
    }


def verify_license(license_obj, key, listing=None, device_id="", mark=True, now=None):
    """许可证校验：哈希比对 + 有效期 + 状态 + 应用一致性 + 激活次数。

    返回 dict（valid + reasons），不抛异常，便于批量校验逐条给出原因；
    单条校验接口用它决定是否写 last_verified_at。
    """
    now = now or timezone.now()
    reasons = []
    if license_obj is None:
        return {"valid": False, "reasons": ["许可证不存在"], "license": None}
    if key is not None:
        if hash_license_key(key) != license_obj.key_hash:
            reasons.append("许可证密钥不匹配")
    if license_obj.status == "revoked":
        reasons.append("许可证已被撤销")
    elif license_obj.status == "expired":
        reasons.append("许可证已过期")
    if license_expired(license_obj, now):
        reasons.append("许可证已超过有效期")
        if license_obj.status == "active":
            # 过期即时落库，避免列表长期显示「有效」与实际校验结果矛盾
            license_obj.status = "expired"
            license_obj.save(update_fields=["status", "updated_at"])
    if listing is not None:
        expected = getattr(listing, "code", None) or str(listing)
        if license_obj.listing_id and license_obj.listing.code != expected:
            reasons.append(f"许可证属于应用 {license_obj.listing.code}，与 {expected} 不一致")
    activations = license_obj.activations or []
    if not isinstance(activations, list):
        activations = []
    if device_id:
        if any(item.get("device_id") == device_id for item in activations if isinstance(item, dict)):
            pass  # 已激活设备重复校验是幂等的
        elif len(activations) >= max(0, license_obj.max_activations):
            reasons.append(
                f"激活次数已达上限 {license_obj.max_activations}，请先停用其他设备"
            )
    valid = not reasons
    if mark and valid:
        license_obj.last_verified_at = now
        license_obj.save(update_fields=["last_verified_at", "updated_at"])
    snapshot = license_snapshot(license_obj, now)
    return {"valid": valid, "reasons": reasons, "license": snapshot}


def activate_license(license_obj, device_id, meta=None, now=None):
    """激活设备：同一设备重复激活幂等，超出上限抛 ValueError。"""
    now = now or timezone.now()
    device = str(device_id or "").strip()
    if not device:
        raise ValueError("缺少必填参数: device_id")
    check = verify_license(license_obj, None, device_id=device, mark=False, now=now)
    if not check["valid"]:
        raise ValueError("；".join(check["reasons"]))
    activations = list(license_obj.activations or [])
    for item in activations:
        if isinstance(item, dict) and item.get("device_id") == device:
            item["last_seen_at"] = now.isoformat()
            if isinstance(meta, dict):
                item["meta"] = meta
            license_obj.last_verified_at = now
            license_obj.save(update_fields=["activations", "last_verified_at", "updated_at"])
            return {"activated": True, "already": True, "license": license_snapshot(license_obj, now)}
    activations.append({
        "device_id": device,
        "at": now.isoformat(),
        "meta": meta if isinstance(meta, dict) else {},
    })
    license_obj.activations = activations
    license_obj.last_verified_at = now
    license_obj.save(update_fields=["activations", "last_verified_at", "updated_at"])
    return {"activated": True, "already": False, "license": license_snapshot(license_obj, now)}


def deactivate_license(license_obj, device_id=""):
    """停用设备：指定设备或全部停用；未激活设备返回明确提示。"""
    activations = [x for x in (license_obj.activations or []) if isinstance(x, dict)]
    device = str(device_id or "").strip()
    if device:
        remaining = [x for x in activations if x.get("device_id") != device]
        if len(remaining) == len(activations):
            raise ValueError("该设备未激活此许可证")
    else:
        remaining = []
    license_obj.activations = remaining
    license_obj.save(update_fields=["activations", "updated_at"])
    return {"deactivated": len(activations) - len(remaining), "remaining": len(remaining)}


def license_status_of(license_obj, now=None):
    """许可证对外状态：有效 / 过期 / 撤销（供列表过滤）。"""
    if license_obj.status == "revoked":
        return "revoked"
    if license_expired(license_obj, now):
        return "expired"
    return license_obj.status


def issue_license(purchase, license_type="perpetual", key=None, max_activations=3,
                  trial_days=0):
    """为订单签发许可证：按类型决定有效期，返回 (license, 明文密钥)。

    明文密钥只在此处返回一次，数据库只保存哈希。
    """
    plain = key or generate_license_key()
    now = timezone.now()
    expires_at = None
    if license_type == "subscription":
        period = getattr(getattr(purchase.listing, "mp_pricing", None), "period", "month")
        days = {"month": 30, "year": 365, "one_time": 3650}.get(period, 30)
        expires_at = now + timedelta(days=days)
    elif license_type == "trial":
        expires_at = now + timedelta(days=max(1, int(trial_days or 14)))
    license_obj = License.objects.create(
        owner=purchase.owner,
        listing=purchase.listing,
        purchase=purchase,
        key_hash=hash_license_key(plain),
        key_hint=mask_license_key(plain),
        type=license_type,
        expires_at=expires_at,
        status="active",
        max_activations=max(1, int(max_activations or 1)),
    )
    return license_obj, plain


# ===========================================================================
# 4. 评分聚合
# ===========================================================================


def review_weight(review, now=None):
    """评价权重：已购买 1.0 起，近期 +10%，被大量点有用 +0.1（上限 1.3）。

    权重只影响加权平均，不改变分布计数：分布要能直接对照「多少条 5 星」。
    """
    now = now or timezone.now()
    weight = 1.0
    if review.verified_purchase:
        weight += 0.0  # 已购买是基准权重，未购买会被下调
    else:
        weight *= 0.8
    age_days = (now - review.created_at).days if review.created_at else 0
    if age_days <= 90:
        weight *= 1.1
    if review.helpful_count > 5:
        weight += 0.1
    return round(min(weight, 1.3), 3)


def aggregate_rating(listing, commit=True):
    """按已发布评价重算评分：加权平均 + 1~5 星分布。

    隐藏/删除评价后调用同一函数即可得到一致结果（可重复执行）。
    """
    reviews = Review.objects.filter(listing=listing, status="published")
    distribution = {str(i): 0 for i in range(1, 6)}
    weighted_sum = 0.0
    weight_total = 0.0
    count = 0
    now = timezone.now()
    for review in reviews:
        rating = int(review.rating or 0)
        if rating < 1 or rating > 5:
            continue
        count += 1
        distribution[str(rating)] += 1
        weight = review_weight(review, now)
        weighted_sum += rating * weight
        weight_total += weight
    average = round(weighted_sum / weight_total, 2) if weight_total else 0.0
    if commit:
        listing.rating = Decimal(str(average))
        listing.rating_count = count
        listing.save(update_fields=["rating", "rating_count", "updated_at"])
    return {
        "listing_id": listing.id,
        "rating": average,
        "rating_count": count,
        "distribution": distribution,
        "weighted": True,
    }


def rating_distribution(queryset=None):
    """全局评分分布（按评价条数，不按应用），供统计页使用。"""
    reviews = (queryset if queryset is not None else Review.objects.all())
    rows = (reviews.filter(status="published")
            .values("rating").annotate(c=Count("id")))
    distribution = {str(i): 0 for i in range(1, 6)}
    for row in rows:
        key = str(row["rating"])
        if key in distribution:
            distribution[key] = row["c"]
    total = sum(distribution.values())
    average = 0.0
    if total:
        average = round(
            sum(int(k) * v for k, v in distribution.items()) / total, 2
        )
    return {"total": total, "average": average, "distribution": distribution}


# ===========================================================================
# 5. 搜索与排序
# ===========================================================================


def search_tokens(query):
    """关键词切分：按空白拆词并去重；空查询返回空列表（表示不过滤）。"""
    text = str(query or "").strip().lower()
    if not text:
        return []
    seen = []
    for token in re.split(r"[\s,，、]+", text):
        token = token.strip()
        if token and token not in seen:
            seen.append(token)
    return seen[:20]


def _text_hit(text, token):
    return token in str(text or "").lower()


def score_listing(listing, tokens, now=None):
    """关键词相关度分值（0 表示不相关）。

    权重设计：标题命中（100/60）> 标签精确（40）> 简介（20）> 发布者（10）
    > 详情（8）。再叠加质量信号：评分 ×4（上限 20）、安装量对数、推荐位。
    """
    score = 0
    title = str(listing.name or "").lower()
    tags = [str(t).lower() for t in (listing.tags or []) if isinstance(t, str)]
    summary = str(listing.summary or "").lower()
    description = str(listing.description or "").lower()
    publisher_name = str(getattr(listing.publisher, "name", "") or "").lower()
    for token in tokens:
        if title == token:
            score += 100
        elif token in title:
            score += 60
        if token in tags:
            score += 40
        elif any(token in tag for tag in tags):
            score += 25
        if token in summary:
            score += 20
        if token in publisher_name:
            score += 10
        if token in description:
            score += 8
    if tokens and score == 0:
        return 0
    now = now or timezone.now()
    score += min(float(listing.rating or 0) * 4, 20)
    score += min(math.log10(max(listing.install_count, 0) + 1) * 6, 18)
    if listing.featured:
        score += 15
    # 新上架应用给一点冷启动权重（30 天内 +5）
    if listing.published_at and (now - listing.published_at).days <= 30:
        score += 5
    return round(score, 2)


def search_listings(queryset, query="", sort="relevance", now=None, limit=500):
    """搜索 + 排序，返回 [(listing, score)]。

    sort 支持 relevance / rating / installs / newest / price / featured。
    价格排序把免费（或没有定价）放前面，付费按折算人民币升序。
    """
    now = now or timezone.now()
    supported = ("relevance", "rating", "installs", "newest", "price", "featured")
    if sort not in supported:
        raise ValueError(f"sort 支持 {'/'.join(supported)}")
    tokens = search_tokens(query)
    items = []
    for listing in queryset.select_related("publisher", "category")[:limit]:
        score = score_listing(listing, tokens, now)
        if tokens and score <= 0:
            continue
        items.append((listing, score))

    if sort == "relevance":
        items.sort(key=lambda pair: (
            -pair[1],
            -pair[0].install_count,
            -float(pair[0].rating or 0),
            -pair[0].id,
        ))
    elif sort == "rating":
        items.sort(key=lambda pair: (
            -float(pair[0].rating or 0),
            -pair[0].rating_count,
            -pair[0].install_count,
        ))
    elif sort == "installs":
        items.sort(key=lambda pair: (-pair[0].install_count, -float(pair[0].rating or 0)))
    elif sort == "newest":
        items.sort(key=lambda pair: (
            -(pair[0].published_at.timestamp() if pair[0].published_at else pair[0].created_at.timestamp()),
        ))
    elif sort == "featured":
        items.sort(key=lambda pair: (
            -int(bool(pair[0].featured)),
            pair[0].featured_rank,
            -pair[0].install_count,
        ))
    else:  # price
        items.sort(key=lambda pair: (_listing_price_cny(pair[0]), -pair[1]))
    return items


def _listing_price_cny(listing):
    """列表价格排序值：无定价或免费为 0，付费折算人民币。"""
    pricing = _pricing_of(listing)
    if pricing is None or pricing.mode == "free" or pricing.price <= 0:
        return Decimal("0")
    return to_cny(pricing.price, pricing.currency)


def _pricing_of(listing):
    """安全取定价（OneToOne 不存在时返回 None，避免 RelatedObjectDoesNotExist 冒泡）。"""
    try:
        return listing.mp_pricing
    except Pricing.DoesNotExist:
        return None


# ===========================================================================
# 6. 定价、购买与收入分成
# ===========================================================================


def pricing_payload(listing):
    """定价信息（含是否免费与可试用天数）。"""
    pricing = _pricing_of(listing)
    if pricing is None:
        return {
            "mode": listing.pricing_mode,
            "price": 0.0,
            "currency": "CNY",
            "trial_days": 0,
            "period": "one_time",
            "active": True,
            "configured": False,
        }
    return {
        "mode": pricing.mode,
        "price": float(pricing.price),
        "currency": pricing.currency,
        "trial_days": pricing.trial_days,
        "period": pricing.period,
        "active": pricing.active,
        "configured": True,
    }


def effective_price(listing):
    """实际成交价：免费模式恒为 0；未配置定价按应用定价模式兜底。"""
    pricing = _pricing_of(listing)
    if listing.pricing_mode == "free":
        return Decimal("0"), "CNY"
    if pricing is None:
        return Decimal("0"), "CNY"
    if pricing.mode == "free":
        return Decimal("0"), pricing.currency
    if not pricing.active:
        raise ValueError("该应用定价已停用，暂不可购买")
    return money(pricing.price), pricing.currency


def publisher_share_pct(publisher):
    """发布者分成比例（0-100），异常数据收敛到合法区间。"""
    try:
        value = Decimal(str(publisher.revenue_share if publisher else 70))
    except Exception:  # noqa: BLE001 —— 历史脏数据兜底
        value = Decimal("70")
    if value < 0:
        value = Decimal("0")
    if value > 100:
        value = Decimal("100")
    return value


def purchase_breakdown(purchase):
    """单笔订单的收入拆分：成交额、平台抽成、发布者净收入、退款冲减。"""
    publisher = purchase.listing.publisher
    share = publisher_share_pct(publisher)
    gross = money(purchase.price if purchase.payment_status in ("paid", "refunded") else 0)
    refund = money(purchase.refund_amount if purchase.payment_status == "refunded" else 0)
    net_gross = money(gross - refund)
    publisher_net = money(net_gross * share / HUNDRED)
    platform_fee = money(net_gross - publisher_net)
    return {
        "order_no": purchase.order_no,
        "listing_code": purchase.listing.code,
        "publisher_id": publisher.id,
        "publisher": publisher.name,
        "currency": purchase.currency,
        "gross": money_out(gross),
        "refund": money_out(refund),
        "net_gross": money_out(net_gross),
        "publisher_share_pct": float(share),
        "publisher_net": money_out(publisher_net),
        "platform_fee": money_out(platform_fee),
        "status": purchase.payment_status,
    }


def publisher_revenue(publisher, purchases=None, days=None):
    """按发布者汇总收入：流水、退款、净收入、平台抽成（原币 + 折算 CNY）。"""
    rows = purchases
    if rows is None:
        rows = Purchase.objects.filter(
            listing__publisher=publisher,
            payment_status__in=("paid", "refunded"),
        )
    if days:
        cutoff = timezone.now() - timedelta(days=int(days))
        rows = rows.filter(created_at__gte=cutoff)
    totals = {
        "gross": Decimal("0"),
        "refund": Decimal("0"),
        "net_gross": Decimal("0"),
        "publisher_net": Decimal("0"),
        "platform_fee": Decimal("0"),
        "orders": 0,
        "refunded_orders": 0,
    }
    by_currency = {}
    by_listing = {}
    for purchase in rows.select_related("listing", "listing__publisher"):
        breakdown = purchase_breakdown(purchase)
        totals["orders"] += 1
        if purchase.payment_status == "refunded":
            totals["refunded_orders"] += 1
        for key in ("gross", "refund", "net_gross", "publisher_net", "platform_fee"):
            totals[key] += Decimal(str(breakdown[key]))
        bucket = by_currency.setdefault(
            purchase.currency, {"gross": Decimal("0"), "refund": Decimal("0"),
                                "publisher_net": Decimal("0"), "platform_fee": Decimal("0"),
                                "orders": 0}
        )
        bucket["gross"] += Decimal(str(breakdown["gross"]))
        bucket["refund"] += Decimal(str(breakdown["refund"]))
        bucket["publisher_net"] += Decimal(str(breakdown["publisher_net"]))
        bucket["platform_fee"] += Decimal(str(breakdown["platform_fee"]))
        bucket["orders"] += 1
        listing_bucket = by_listing.setdefault(
            purchase.listing.code,
            {"code": purchase.listing.code, "name": purchase.listing.name,
             "publisher_net": Decimal("0"), "orders": 0},
        )
        listing_bucket["publisher_net"] += Decimal(str(breakdown["publisher_net"]))
        listing_bucket["orders"] += 1

    result = {
        "publisher_id": publisher.id,
        "publisher": publisher.name,
        "share_pct": float(publisher_share_pct(publisher)),
        "orders": totals["orders"],
        "refunded_orders": totals["refunded_orders"],
        "gross": money_out(totals["gross"]),
        "refund": money_out(totals["refund"]),
        "net_gross": money_out(totals["net_gross"]),
        "publisher_net": money_out(totals["publisher_net"]),
        "platform_fee": money_out(totals["platform_fee"]),
        "publisher_net_cny": money_out(
            sum(to_cny(v["publisher_net"], cur) for cur, v in by_currency.items())
        ),
        "by_currency": {
            cur: {k: money_out(v) if isinstance(v, Decimal) else v for k, v in bucket.items()}
            for cur, bucket in by_currency.items()
        },
        "by_listing": sorted(
            [
                {
                    "code": v["code"],
                    "name": v["name"],
                    "publisher_net": money_out(v["publisher_net"]),
                    "orders": v["orders"],
                }
                for v in by_listing.values()
            ],
            key=lambda x: -x["publisher_net"],
        ),
    }
    return result


def revenue_summary(purchases=None, days=None):
    """全市场收入汇总：总额（CNY）、平台/发布者、按月、退款。"""
    rows = purchases
    if rows is None:
        rows = Purchase.objects.filter(payment_status__in=("paid", "refunded"))
    if days:
        cutoff = timezone.now() - timedelta(days=int(days))
        rows = rows.filter(created_at__gte=cutoff)
    rows = rows.select_related("listing", "listing__publisher")

    totals = {
        "gross_cny": Decimal("0"),
        "refund_cny": Decimal("0"),
        "net_cny": Decimal("0"),
        "publisher_net_cny": Decimal("0"),
        "platform_fee_cny": Decimal("0"),
        "orders": 0,
        "refunded_orders": 0,
    }
    by_publisher = {}
    by_month = {}
    by_currency = {}
    for purchase in rows:
        breakdown = purchase_breakdown(purchase)
        currency = purchase.currency
        gross_cny = to_cny(breakdown["gross"], currency)
        refund_cny = to_cny(breakdown["refund"], currency)
        net_cny = to_cny(breakdown["net_gross"], currency)
        publisher_cny = to_cny(breakdown["publisher_net"], currency)
        platform_cny = to_cny(breakdown["platform_fee"], currency)
        totals["orders"] += 1
        totals["gross_cny"] += gross_cny
        totals["refund_cny"] += refund_cny
        totals["net_cny"] += net_cny
        totals["publisher_net_cny"] += publisher_cny
        totals["platform_fee_cny"] += platform_cny
        if purchase.payment_status == "refunded":
            totals["refunded_orders"] += 1

        pub = by_publisher.setdefault(
            purchase.listing.publisher_id,
            {"publisher_id": purchase.listing.publisher_id,
             "publisher": purchase.listing.publisher.name,
             "orders": 0, "net_cny": Decimal("0"),
             "publisher_net_cny": Decimal("0"),
             "platform_fee_cny": Decimal("0")},
        )
        pub["orders"] += 1
        pub["net_cny"] += net_cny
        pub["publisher_net_cny"] += publisher_cny
        pub["platform_fee_cny"] += platform_cny

        stamp = purchase.purchased_at or purchase.created_at
        month_key = stamp.strftime("%Y-%m") if stamp else "unknown"
        month = by_month.setdefault(
            month_key, {"month": month_key, "orders": 0, "gross_cny": Decimal("0"),
                        "publisher_net_cny": Decimal("0")},
        )
        month["orders"] += 1
        month["gross_cny"] += gross_cny
        month["publisher_net_cny"] += publisher_cny

        bucket = by_currency.setdefault(
            currency, {"currency": currency, "gross": Decimal("0"),
                       "refund": Decimal("0"), "orders": 0},
        )
        bucket["gross"] += Decimal(str(breakdown["gross"]))
        bucket["refund"] += Decimal(str(breakdown["refund"]))
        bucket["orders"] += 1

    return {
        "orders": totals["orders"],
        "refunded_orders": totals["refunded_orders"],
        "gross_cny": money_out(totals["gross_cny"]),
        "refund_cny": money_out(totals["refund_cny"]),
        "net_cny": money_out(totals["net_cny"]),
        "publisher_net_cny": money_out(totals["publisher_net_cny"]),
        "platform_fee_cny": money_out(totals["platform_fee_cny"]),
        "platform_share_pct": (
            round(float(totals["platform_fee_cny"] / totals["net_cny"]) * 100, 2)
            if totals["net_cny"] else 0.0
        ),
        "by_currency": {
            cur: {k: money_out(v) if isinstance(v, Decimal) else v for k, v in bucket.items()}
            for cur, bucket in by_currency.items()
        },
        "by_publisher": sorted(
            [
                {
                    "publisher_id": v["publisher_id"],
                    "publisher": v["publisher"],
                    "orders": v["orders"],
                    "net_cny": money_out(v["net_cny"]),
                    "publisher_net_cny": money_out(v["publisher_net_cny"]),
                    "platform_fee_cny": money_out(v["platform_fee_cny"]),
                }
                for v in by_publisher.values()
            ],
            key=lambda x: -x["net_cny"],
        ),
        "by_month": sorted(
            [
                {
                    "month": v["month"],
                    "orders": v["orders"],
                    "gross_cny": money_out(v["gross_cny"]),
                    "publisher_net_cny": money_out(v["publisher_net_cny"]),
                }
                for v in by_month.values()
            ],
            key=lambda x: x["month"],
        ),
    }


# ===========================================================================
# 7. 升级检查
# ===========================================================================


def upgrade_candidates(listing, current_version, platform_version=None):
    """可升级版本列表：大于当前版本、已发布、平台兼容。"""
    try:
        current = parse_version(current_version, "当前版本")
    except ValueError:
        raise ValueError(f"当前版本 “{current_version}” 不是合法的语义化版本")
    items = []
    for version in published_versions(listing, platform_version):
        if _version_sort_key(version.version) <= _version_sort_key(current["raw"]):
            continue
        items.append(version)
    return items


def check_upgrade(listing, current_version, platform_version=None):
    """升级检查：当前 → 最新可升级版本 + 变更说明 + 破坏性标记。

    返回 upgrade_available / latest / changes / breaking / reason：
    - reason 为空表示可以升级；否则给出「已是最新 / 无兼容版本」等说明；
    - changes 汇总途经版本的 changelog，按版本从旧到新排列，便于拼升级指引。
    """
    target_platform = platform_version or PLATFORM_VERSION
    candidates = upgrade_candidates(listing, current_version, target_platform)
    if not candidates:
        any_published = published_versions(listing, None, include_incompatible=True)
        reason = "已是最新版本"
        if any_published:
            newer = [
                v for v in any_published
                if is_valid_version(v.version)
                and compare_versions(v.version, current_version) > 0
            ]
            if newer:
                reason = f"存在更高版本，但要求平台 ≥ {newer[0].min_platform_version}"
        return {
            "listing_id": listing.id,
            "listing_code": listing.code,
            "current_version": current_version,
            "platform_version": target_platform,
            "upgrade_available": False,
            "latest": None,
            "changes": [],
            "breaking": False,
            "reason": reason,
        }
    latest = candidates[0]
    ordered = list(reversed(candidates))  # 旧 → 新
    changes = [
        {
            "version": version.version,
            "changelog": version.changelog,
            "published_at": version.published_at.isoformat() if version.published_at else None,
            "breaking": bool(version.breaking) or is_breaking_change(
                current_version, version.version
            ),
            "min_platform_version": version.min_platform_version,
            "package_size": version.package_size,
        }
        for version in ordered
    ]
    breaking = any(item["breaking"] for item in changes) or is_breaking_change(
        current_version, latest.version
    )
    return {
        "listing_id": listing.id,
        "listing_code": listing.code,
        "current_version": current_version,
        "platform_version": target_platform,
        "upgrade_available": True,
        "latest": {
            "id": latest.id,
            "version": latest.version,
            "changelog": latest.changelog,
            "min_platform_version": latest.min_platform_version,
            "published_at": latest.published_at.isoformat() if latest.published_at else None,
            "package_size": latest.package_size,
            "checksum": latest.checksum,
        },
        "changes": changes,
        "breaking": breaking,
        "reason": "",
        "diff": diff_versions(current_version, latest.version),
    }


# ===========================================================================
# 8. 合集
# ===========================================================================


def collection_listings(collection):
    """合集内的应用（按条目顺序），只返回仍可见的应用。"""
    items = (CollectionItem.objects.filter(collection=collection)
             .select_related("listing", "listing__publisher", "listing__category")
             .order_by("order", "id"))
    return [item.listing for item in items]


def dedupe_collection_items(collection):
    """去重合集条目（保留排序最靠前的一条），返回删除数量。

    数据库唯一约束已保证新数据不重复；这里处理历史数据/并发插入残留，
    保证「发布合集」时不会出现同一应用两次。
    """
    seen = set()
    duplicates = []
    for item in CollectionItem.objects.filter(collection=collection).order_by("order", "id"):
        if item.listing_id in seen:
            duplicates.append(item)
        else:
            seen.add(item.listing_id)
    for item in duplicates:
        item.delete()
    return len(duplicates)


def reorder_collection(collection, ordered_ids):
    """按给定 id 顺序重排；未提交的条目追加在末尾，保持不丢数据。"""
    ids = []
    for raw in ordered_ids or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError("items 只能包含整数 id")
        if value not in ids:
            ids.append(value)
    items = {item.id: item for item in CollectionItem.objects.filter(collection=collection)}
    if not items:
        raise ValueError("合集还没有条目")
    unknown = [i for i in ids if i not in items]
    if unknown:
        raise ValueError(f"合集条目不包含 id: {unknown[0]}")
    position = 0
    for item_id in ids:
        item = items.pop(item_id)
        if item.order != position:
            item.order = position
            item.save(update_fields=["order", "updated_at"])
        position += 1
    for item in sorted(items.values(), key=lambda x: (x.order, x.id)):
        if item.order != position:
            item.order = position
            item.save(update_fields=["order", "updated_at"])
        position += 1
    return position


def publish_collection(collection):
    """发布合集：至少 1 个条目，且所有应用都已上架（否则列出不可发布的标识）。"""
    if collection.status == "published":
        raise ValueError("合集已发布")
    dedupe_collection_items(collection)
    items = list(CollectionItem.objects.filter(collection=collection)
                 .select_related("listing"))
    if not items:
        raise ValueError("合集至少需要 1 个应用才能发布")
    blocked = sorted({
        item.listing.code for item in items
        if item.listing.status != "published"
    })
    if blocked:
        raise ValueError(f"以下应用未上架，不能发布合集: {', '.join(blocked[:10])}")
    collection.status = "published"
    collection.published_at = timezone.now()
    collection.save(update_fields=["status", "published_at", "updated_at"])
    return {"id": collection.id, "status": collection.status,
            "items": len(items), "published_at": collection.published_at.isoformat()}


def add_collection_item(collection, listing):
    """加入合集：同一应用重复加入返回已有条目（幂等），而不是报错。"""
    existing = CollectionItem.objects.filter(collection=collection, listing=listing).first()
    if existing is not None:
        return existing, False
    last = (CollectionItem.objects.filter(collection=collection)
            .order_by("-order").values_list("order", flat=True).first())
    item = CollectionItem.objects.create(
        owner=collection.owner,
        collection=collection,
        listing=listing,
        order=(last or -1) + 1,
    )
    return item, True


# ===========================================================================
# 9. 举报处置
# ===========================================================================


def transition_report(report, action, resolution="", actor=None):
    """举报状态机流转：pending → reviewing → resolved / dismissed。

    action 取 review / resolve / dismiss；resolved 必须给出处理结论，
    避免「已处置」但没有记录处置口径（申诉时无法复盘）。
    """
    mapping = {"review": "reviewing", "resolve": "resolved", "dismiss": "dismissed"}
    if action not in mapping:
        raise ValueError("action 支持 review/resolve/dismiss")
    target = mapping[action]
    if target not in REPORT_TRANSITIONS.get(report.status, ()):
        raise ValueError(f"举报当前状态 {report.status} 不能流转到 {target}")
    text = str(resolution or "").strip()
    if target == "resolved" and not text:
        raise ValueError("处置为已解决时必须填写处理结论")
    if target == "dismissed" and not text:
        text = "经核查举报不成立"
    report.status = target
    report.resolution = text[:2000]
    report.handled_at = timezone.now()
    report.save(update_fields=["status", "resolution", "handled_at", "updated_at"])
    return {
        "id": report.id,
        "status": report.status,
        "resolution": report.resolution,
        "handled_at": report.handled_at.isoformat(),
        "actor": getattr(actor, "username", ""),
    }


def report_summary(queryset):
    """举报按状态 + 原因汇总。"""
    by_status = {row["status"]: row["c"] for row in
                 queryset.values("status").annotate(c=Count("id"))}
    by_reason = {row["reason"]: row["c"] for row in
                 queryset.values("reason").annotate(c=Count("id"))}
    return {"total": queryset.count(), "by_status": by_status, "by_reason": by_reason}


# ===========================================================================
# 10. 事件与 Webhook（本地模拟投递）
# ===========================================================================


def webhook_matches(subscription, event_type):
    """订阅是否关心该事件：支持 ``*`` 通配与精确匹配。"""
    events = subscription.events or []
    if not isinstance(events, list) or not events:
        return False
    return "*" in events or event_type in events


def _simulate_delivery(subscription, event_type, payload):
    """本地投递模拟：校验 URL 形态后返回确定性结果，不发起任何网络请求。

    设计原因：环境禁止联网，但投递语义（订阅匹配、失败计数、最近状态、
    幂等）必须真实可测。约定：URL 含 ``fail`` 时模拟 500，其余模拟 200；
    停用的订阅不投递。
    """
    url = str(subscription.url or "")
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, 400, "回调地址必须是 http(s) URL"
    if "fail" in url.lower():
        return False, 500, "模拟回调失败（URL 含 fail）"
    return True, 200, f"模拟投递成功: {event_type}"


def deliver_event(event):
    """把事件投递给发布者的匹配订阅，写投递记录并维护订阅健康度。"""
    if event.listing_id is None:
        subscriptions = WebhookSubscription.objects.filter(
            owner=event.owner, status="active"
        ).select_related("publisher")
    else:
        subscriptions = WebhookSubscription.objects.filter(
            Q(listing=event.listing) | Q(listing__isnull=True, publisher=event.listing.publisher),
            status="active",
        ).select_related("publisher")
    deliveries = []
    payload = {
        "event": event.event_type,
        "id": event.pk,
        "listing": event.listing.code if event.listing_id else None,
        "data": event.payload or {},
        "at": timezone.now().isoformat(),
    }
    for subscription in subscriptions:
        if not webhook_matches(subscription, event.event_type):
            continue
        ok_flag, status, body = _simulate_delivery(subscription, event.event_type, payload)
        delivery = WebhookDelivery.objects.create(
            owner=subscription.owner,
            subscription=subscription,
            event_type=event.event_type,
            payload=payload,
            response_status=status,
            response_body=body,
            success=ok_flag,
        )
        subscription.last_delivery_at = delivery.delivered_at
        subscription.last_status = status
        subscription.failure_count = 0 if ok_flag else subscription.failure_count + 1
        subscription.save(update_fields=["last_delivery_at", "last_status",
                                         "failure_count", "updated_at"])
        deliveries.append(delivery)
    return deliveries


def emit_event(listing, event_type, payload, owner, idempotency_key=""):
    """写市场事件并投递；幂等键重复时直接返回原事件（不重复投递）。

    返回 (event, created)。调用方应在 transaction.atomic 内使用，
    保证「事件 + 投递」与主业务写入同生共死。
    """
    key = str(idempotency_key or "").strip() or None
    if key:
        existing = MarketplaceEvent.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return existing, False
    event = MarketplaceEvent.objects.create(
        owner=owner,
        listing=listing,
        event_type=str(event_type or "")[:60],
        payload=payload if isinstance(payload, dict) else {},
        idempotency_key=key,
        status="pending",
        attempts=1,
    )
    deliveries = deliver_event(event)
    event.status = "processed" if all(d.success for d in deliveries) else "failed"
    event.processed_at = timezone.now()
    if event.status == "failed":
        event.error = "部分 Webhook 投递失败"
    event.save(update_fields=["status", "processed_at", "error", "updated_at"])
    return event, True


def test_webhook(subscription, event_type="webhook.test", payload=None):
    """手动测试投递：不写 MarketplaceEvent，只写投递记录并返回结果。"""
    if subscription.status != "active":
        raise ValueError("订阅已停用，不能测试投递")
    ok_flag, status, body = _simulate_delivery(
        subscription, event_type, payload if isinstance(payload, dict) else {}
    )
    delivery = WebhookDelivery.objects.create(
        owner=subscription.owner,
        subscription=subscription,
        event_type=str(event_type or "webhook.test")[:60],
        payload=payload if isinstance(payload, dict) else {},
        response_status=status,
        response_body=body,
        success=ok_flag,
    )
    subscription.last_delivery_at = delivery.delivered_at
    subscription.last_status = status
    subscription.failure_count = 0 if ok_flag else subscription.failure_count + 1
    subscription.save(update_fields=["last_delivery_at", "last_status",
                                     "failure_count", "updated_at"])
    return {
        "success": ok_flag,
        "status": status,
        "body": body,
        "subscription_id": subscription.id,
        "delivery_id": delivery.id,
    }


# ===========================================================================
# 11. 市场统计
# ===========================================================================


def marketplace_overview(now=None):
    """市场概览：发布者/应用/安装/评价/收入的规模指标。"""
    now = now or timezone.now()
    listings = Listing.objects.all()
    published = listings.filter(status="published")
    by_status = {row["status"]: row["c"] for row in
                 listings.values("status").annotate(c=Count("id"))}
    by_type = {row["type"]: row["c"] for row in
               published.values("type").annotate(c=Count("id"))}
    installs = Install.objects.all()
    installs_active = installs.filter(status__in=INSTALL_ACTIVE_STATUS)
    reviews = Review.objects.all()
    revenue = revenue_summary()
    return {
        "generated_at": now.isoformat(),
        "platform_version": PLATFORM_VERSION,
        "publishers": Publisher.objects.count(),
        "verified_publishers": Publisher.objects.filter(status="verified").count(),
        "listings": listings.count(),
        "published_listings": published.count(),
        "listings_by_status": by_status,
        "listings_by_type": by_type,
        "installs": installs.count(),
        "active_installs": installs_active.count(),
        "installed_users": installs_active.values("owner_id").distinct().count(),
        "reviews": reviews.count(),
        "published_reviews": reviews.filter(status="published").count(),
        "pending_reviews": reviews.filter(status="pending").count(),
        "pending_reports": ListingReport.objects.filter(status="pending").count(),
        "collections": Collection.objects.count(),
        "published_collections": Collection.objects.filter(status="published").count(),
        "revenue": {
            "orders": revenue["orders"],
            "gross_cny": revenue["gross_cny"],
            "net_cny": revenue["net_cny"],
            "publisher_net_cny": revenue["publisher_net_cny"],
            "platform_fee_cny": revenue["platform_fee_cny"],
            "refund_cny": revenue["refund_cny"],
        },
    }


def category_distribution():
    """分类分布：每个分类的应用数、安装量、平均评分（含未分类）。"""
    rows = []
    categories = Category.objects.all().prefetch_related("mp_category_listings")
    for category in categories.select_related("parent"):
        listings = category.mp_category_listings.filter(status="published")
        count = listings.count()
        installs = listings.aggregate(total=Sum("install_count"))["total"] or 0
        rating = listings.aggregate(value=Avg("rating"))["value"]
        rows.append({
            "category_id": category.id,
            "code": category.code,
            "name": category.name,
            "parent_id": category.parent_id,
            "listings": count,
            "installs": int(installs),
            "avg_rating": round(float(rating or 0), 2),
        })
    uncategorized = Listing.objects.filter(status="published", category__isnull=True)
    rows.append({
        "category_id": None,
        "code": "",
        "name": "未分类",
        "parent_id": None,
        "listings": uncategorized.count(),
        "installs": int(uncategorized.aggregate(total=Sum("install_count"))["total"] or 0),
        "avg_rating": round(float(uncategorized.aggregate(value=Avg("rating"))["value"] or 0), 2),
    })
    rows.sort(key=lambda x: (-x["listings"], x["name"]))
    return {"total_categories": Category.objects.count(), "items": rows}


def top_publishers(limit=10, days=None):
    """发布者 TOP：按安装量、收入、应用数综合展示（默认 10 个）。"""
    limit = max(1, min(int(limit or 10), 100))
    rows = []
    for publisher in Publisher.objects.all():
        listings = publisher.mp_publisher_listings.all()
        published = listings.filter(status="published")
        installs = published.aggregate(total=Sum("install_count"))["total"] or 0
        revenue = publisher_revenue(publisher, days=days)
        rows.append({
            "publisher_id": publisher.id,
            "name": publisher.name,
            "slug": publisher.slug,
            "status": publisher.status,
            "listings": listings.count(),
            "published_listings": published.count(),
            "installs": int(installs),
            "orders": revenue["orders"],
            "publisher_net_cny": revenue["publisher_net_cny"],
            "share_pct": revenue["share_pct"],
        })
    rows.sort(key=lambda x: (-x["installs"], -x["publisher_net_cny"], x["name"]))
    return {"items": rows[:limit], "count": len(rows)}


def install_trend(days=30, owner=None):
    """安装趋势：近 N 天每日安装/卸载/净增 + 累计曲线（按自然日）。"""
    days = int(days or 30)
    if days < 1 or days > 365:
        raise ValueError("days 需在 1~365 之间")
    now = timezone.now()
    start_day = (now - timedelta(days=days - 1)).date()
    installs = Install.objects.filter(installed_at__date__gte=start_day)
    uninstalls = Install.objects.filter(uninstalled_at__date__gte=start_day)
    if owner is not None:
        installs = installs.filter(owner=owner)
        uninstalls = uninstalls.filter(owner=owner)
    install_map = {}
    for row in installs.values("installed_at__date").annotate(c=Count("id")):
        install_map[row["installed_at__date"]] = row["c"]
    uninstall_map = {}
    for row in uninstalls.values("uninstalled_at__date").annotate(c=Count("id")):
        uninstall_map[row["uninstalled_at__date"]] = row["c"]
    base_active = 0
    if owner is not None:
        base_active = Install.objects.filter(
            owner=owner, installed_at__date__lt=start_day,
            status__in=INSTALL_ACTIVE_STATUS,
        ).count()
    else:
        base_active = Install.objects.filter(
            installed_at__date__lt=start_day, status__in=INSTALL_ACTIVE_STATUS,
        ).count()
    items = []
    cumulative = base_active
    for index in range(days):
        day = start_day + timedelta(days=index)
        installed = install_map.get(day, 0)
        removed = uninstall_map.get(day, 0)
        cumulative = max(0, cumulative + installed - removed)
        items.append({
            "date": day.isoformat(),
            "installs": installed,
            "uninstalls": removed,
            "net": installed - removed,
            "cumulative": cumulative,
        })
    total_installs = sum(item["installs"] for item in items)
    total_uninstalls = sum(item["uninstalls"] for item in items)
    return {
        "days": days,
        "start": start_day.isoformat(),
        "end": now.date().isoformat(),
        "total_installs": total_installs,
        "total_uninstalls": total_uninstalls,
        "net": total_installs - total_uninstalls,
        "items": items,
    }


def rating_statistics(limit=10):
    """评分分布：全市场 + 评分最高的应用（至少 1 条发布评价）。"""
    overall = rating_distribution()
    rows = []
    listings = (Listing.objects.filter(rating_count__gt=0, status="published")
                .select_related("publisher")
                .order_by("-rating", "-rating_count")[:max(1, min(int(limit or 10), 50))])
    for listing in listings:
        rows.append({
            "listing_id": listing.id,
            "code": listing.code,
            "name": listing.name,
            "rating": float(listing.rating or 0),
            "rating_count": listing.rating_count,
            "publisher": listing.publisher.name,
        })
    return {"overall": overall, "top_rated": rows}


def revenue_statistics(days=None):
    """收入统计：全市场汇总 + 平台/发布者分成 + 月度走势。"""
    summary = revenue_summary(days=days)
    summary["top_publishers"] = summary["by_publisher"][:10]
    return summary


def listing_health(listing):
    """应用健康度：版本/评分/安装/举报的综合评分（运营看板用）。"""
    versions = listing.mp_versions.filter(status="published").count()
    reports = listing.mp_reports.filter(status__in=("pending", "reviewing")).count()
    score = 100
    if not versions:
        score -= 30
    if listing.rating_count == 0:
        score -= 10
    elif float(listing.rating) < 3:
        score -= 20
    if listing.status != "published":
        score -= 25
    score -= min(reports * 5, 30)
    if listing.featured:
        score += 5
    score = max(0, min(100, score))
    return {
        "listing_id": listing.id,
        "code": listing.code,
        "score": score,
        "published_versions": versions,
        "open_reports": reports,
        "rating": float(listing.rating or 0),
        "install_count": listing.install_count,
    }


def refresh_listing_counters(listing):
    """重算应用的安装量与最新版本（安装/卸载/发版后调用）。

    安装量口径：有效安装记录数（installed/disabled），不累计历史卸载，
    这样「安装量」与当前可服务用户数一致；趋势统计另行按时间聚合。
    """
    active = Install.objects.filter(listing=listing, status__in=INSTALL_ACTIVE_STATUS).count()
    latest = best_version_for_platform(listing, None)
    listing.install_count = active
    listing.latest_version = latest
    listing.save(update_fields=["install_count", "latest_version", "updated_at"])
    return {"install_count": active, "latest_version": latest.version if latest else None}


def ensure_no_broken_dependency(listing, version, platform_version=None):
    """发布前自检：manifest 里的依赖必须存在且范围可满足（避免上线即坏）。"""
    issues = []
    manifest = version.manifest or {}
    requires = manifest.get("requires") or []
    if not isinstance(requires, list):
        return [{"code": listing.code, "message": "manifest.requires 必须是数组"}]
    for requirement in requires:
        if not isinstance(requirement, dict):
            continue
        code = str(requirement.get("code") or "").strip()
        expression = str(requirement.get("range") or "").strip()
        if not code:
            continue
        try:
            parse_range(expression or "*", "依赖版本范围")
        except ValueError as exc:
            issues.append({"code": code, "message": str(exc)})
            continue
        dependency = Listing.objects.filter(code=code).first()
        if dependency is None:
            issues.append({"code": code, "message": "依赖应用不存在"})
            continue
        candidates = [
            v.version for v in published_versions(dependency, platform_version)
        ]
        if not candidates:
            issues.append({"code": code, "message": "依赖应用没有可安装版本"})
            continue
        if not max_satisfying(candidates, expression or "*"):
            issues.append({
                "code": code,
                "message": f"没有满足 {expression or '*'} 的已发布版本",
            })
    return issues


def platform_version_value():
    """对外暴露的平台版本（目录/兼容检查共用）。"""
    return PLATFORM_VERSION


def safe_day(value):
    """把 date/datetime/字符串归一成 date（统计聚合用）。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def day_bounds(day):
    """某个自然日的起止 aware datetime（趋势补零用）。"""
    day = safe_day(day) or timezone.localdate()
    start = datetime.combine(day, dt_time.min)
    return timezone.make_aware(start), timezone.make_aware(start + timedelta(days=1))
