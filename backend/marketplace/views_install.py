# -*- coding: utf-8 -*-
"""应用市场 · 安装接口（8 个）。

安装语义（本地状态模拟，但校验是真实的）：
- 依据平台版本与已装依赖解析出兼容的最新版本，冲突时返回可读原因；
- 付费应用必须先有已支付订单或有效许可证，否则拒绝安装；
- 卸载是软删除（保留记录便于重装与统计），有效安装量随之重算；
- 升级遵循语义化版本比较，允许显式指定目标版本（降级会给出提示）。
"""
from django.db import transaction
from django.utils import timezone

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_str)

from . import services
from .common import (get_install, listing_by_reference, paginate_queryset,
                     parse_dict)
from .models import (
    INSTALL_ACTIVE_STATUS,
    PLATFORM_VERSION,
    Install,
    License,
    Purchase,
)
from .serializers import install_dict, listing_brief, version_brief


def _platform_version(request):
    """平台版本入参（缺省取当前平台版本），必须合法语义化版本。"""
    value = opt_str(request, "platform_version", services.platform_version_value()).strip()
    services.parse_version(value, "平台版本")
    return value


def _paid_access(user, listing):
    """是否具备使用付费应用的资格：已支付订单或有效许可证。"""
    purchase = listing.mp_purchases.filter(owner=user, payment_status="paid").first()
    if purchase is not None:
        return True
    license_obj = listing.mp_licenses.filter(owner=user, status="active").first()
    if license_obj is not None and not services.license_expired(license_obj):
        return True
    return False


def _target_version(request, listing, platform_version, resolution):
    """确定要安装的版本：显式 version_id 优先，否则用解析器结果。"""
    version_id = opt_num(request, "version_id", integer=True)
    if version_id:
        version = listing.mp_versions.filter(pk=int(version_id)).first()
        if version is None:
            raise ValueError("指定的版本不属于该应用")
        if version.status != "published":
            raise ValueError("只能安装已发布版本")
        if not services.platform_compatible(version, platform_version):
            raise ValueError(
                f"版本 {version.version} 要求平台 ≥ {version.min_platform_version}"
            )
        return version
    resolved = resolution.get("resolved") or {}
    if resolved.get("version_id"):
        version = listing.mp_versions.filter(pk=resolved["version_id"]).first()
        if version is not None:
            return version
    return services.best_version_for_platform(listing, platform_version)


@endpoint(("GET", "POST"))
def installs(request):
    """我的应用列表（q/status 分页）或安装应用（含依赖解析与付费校验）。"""
    if request.method == "GET":
        queryset = (Install.objects.filter(owner=request.user)
                    .select_related("listing", "listing__publisher", "version")
                    .order_by("-installed_at"))
        return ok(paginate_queryset(
            request, queryset, install_dict,
            search_fields=("listing__name", "listing__code", "listing__summary"),
        ))

    listing = listing_by_reference(request)
    if listing.status != "published":
        raise ValueError("应用未上架，不能安装")
    platform_version = _platform_version(request)
    resolution = services.resolve_install(
        listing,
        platform_version,
        services.installed_version_map(request.user),
        request.user,
    )
    if not resolution["ok"]:
        reasons = "；".join(
            f"{item['code']}: {item['reason']}" for item in resolution["conflicts"][:5]
        )
        raise ValueError(f"安装解析失败：{reasons}")
    version = _target_version(request, listing, platform_version, resolution)
    if version is None:
        raise ValueError("没有可安装的版本")

    # 付费校验：免费应用不需要订单；付费/增值应用需要已支付或有效许可证
    price, _currency = services.effective_price(listing)
    if listing.pricing_mode == "paid" and price > 0 and not _paid_access(request.user, listing):
        raise ValueError("该应用为付费应用，请先购买后再安装")
    if listing.pricing_mode == "freemium" and price > 0 \
            and not _paid_access(request.user, listing) \
            and not (listing.mp_pricing.trial_days if hasattr(listing, "mp_pricing") else 0):
        # 增值应用无试用期时也必须先付费；有试用期则允许先装（试用许可由购买侧签发）
        raise ValueError("该应用为增值应用，请先购买或开通试用")

    config = parse_dict(request, "config")
    auto_update = opt_bool(request, "auto_update", False)
    idempotency_key = opt_str(request, "idempotency_key", "").strip()
    with transaction.atomic():
        install = (Install.objects.select_for_update()
                   .filter(owner=request.user, listing=listing).first())
        if install is None:
            install = Install.objects.create(
                owner=request.user,
                listing=listing,
                version=version,
                status="installed",
                config=config,
                auto_update=auto_update,
                installed_at=timezone.now(),
            )
            action = "installed"
        else:
            if install.status not in INSTALL_ACTIVE_STATUS:
                install.installed_at = timezone.now()
                action = "reinstalled"
            else:
                action = "already_installed"
            install.uninstalled_at = None
            install.status = "installed"
            install.version = version
            if config:
                install.config = config
            install.auto_update = auto_update
            install.save()
        services.refresh_listing_counters(listing)
        services.emit_event(
            listing, "install.created",
            {"listing": listing.code, "version": version.version,
             "install_id": install.id, "action": action},
            request.user, idempotency_key,
        )
    return ok({
        "install": install_dict(install),
        "action": action,
        "resolution": resolution,
    })


@endpoint(("GET",))
def install_detail(request, pk):
    """安装详情：当前版本、可升级版本与依赖解析结果。"""
    install = get_install(pk, request.user)
    listing = install.listing
    current = install.version.version if install.version_id else ""
    upgrade = None
    if current and services.is_valid_version(current):
        upgrade = services.check_upgrade(
            listing, current, services.platform_version_value())
    resolution = services.resolve_install(
        listing, services.platform_version_value(),
        services.installed_version_map(request.user), request.user,
    )
    data = install_dict(install)
    data["upgrade"] = upgrade
    data["resolution"] = resolution
    return ok(data)


@endpoint()
def install_uninstall(request, pk):
    """卸载应用（软删除，保留安装记录供重装与统计）。"""
    install = get_install(pk, request.user, write=True)
    if install.status == "uninstalled":
        raise ValueError("该应用已卸载")
    with transaction.atomic():
        install.status = "uninstalled"
        install.uninstalled_at = timezone.now()
        install.save(update_fields=["status", "uninstalled_at", "updated_at"])
        services.refresh_listing_counters(install.listing)
        services.emit_event(
            install.listing, "install.uninstalled",
            {"listing": install.listing.code, "install_id": install.id},
            request.user,
        )
    return ok({"id": install.id, "status": install.status,
               "uninstalled_at": install.uninstalled_at.isoformat()})


@endpoint()
def install_enable(request, pk):
    """启用已安装应用（disabled → installed）。"""
    install = get_install(pk, request.user, write=True)
    if install.status == "uninstalled":
        raise ValueError("应用已卸载，请先重新安装")
    if install.status == "installed":
        return ok({"id": install.id, "status": install.status, "changed": False})
    install.status = "installed"
    install.save(update_fields=["status", "updated_at"])
    return ok({"id": install.id, "status": install.status, "changed": True})


@endpoint()
def install_disable(request, pk):
    """禁用已安装应用（installed → disabled，仍计入有效安装量）。"""
    install = get_install(pk, request.user, write=True)
    if install.status == "uninstalled":
        raise ValueError("应用已卸载，不能禁用")
    if install.status == "disabled":
        return ok({"id": install.id, "status": install.status, "changed": False})
    install.status = "disabled"
    install.save(update_fields=["status", "updated_at"])
    return ok({"id": install.id, "status": install.status, "changed": True})


@endpoint()
def install_config(request, pk):
    """更新安装配置（整体替换 JSON 对象）。"""
    install = get_install(pk, request.user, write=True)
    if install.status == "uninstalled":
        raise ValueError("应用已卸载，不能修改配置")
    config = parse_dict(request, "config")
    if len(str(config)) > 200000:
        raise ValueError("配置内容过大（上限 200KB）")
    install.config = config
    install.save(update_fields=["config", "updated_at"])
    return ok({"id": install.id, "config": install.config})


@endpoint()
def install_upgrade(request, pk):
    """升级已安装应用（目标版本或解析器结果；同版本视为已是最新）。"""
    install = get_install(pk, request.user, write=True)
    if install.status == "uninstalled":
        raise ValueError("应用已卸载，不能升级")
    listing = install.listing
    platform_version = _platform_version(request)
    current = install.version.version if install.version_id else "0.0.0"
    if not services.is_valid_version(current):
        raise ValueError("当前安装版本非法，请重新安装")
    version_id = opt_num(request, "version_id", integer=True)
    if version_id:
        target = listing.mp_versions.filter(pk=int(version_id), status="published").first()
        if target is None:
            raise ValueError("目标版本不存在或未发布")
        if not services.platform_compatible(target, platform_version):
            raise ValueError(f"目标版本要求平台 ≥ {target.min_platform_version}")
    else:
        target = services.best_version_for_platform(listing, platform_version)
    if target is None:
        raise ValueError("没有可用于升级的版本")
    if services.compare_versions(target.version, current) <= 0:
        raise ValueError(f"已是最新版本（当前 {current}）")
    profile = services.check_upgrade(listing, current, platform_version)
    with transaction.atomic():
        install.version = target
        install.status = "installed"
        install.last_upgraded_at = timezone.now()
        install.save(update_fields=["version", "status", "last_upgraded_at", "updated_at"])
        services.refresh_listing_counters(listing)
        services.emit_event(
            listing, "install.upgraded",
            {"listing": listing.code, "from": current, "to": target.version,
             "install_id": install.id},
            request.user,
        )
    return ok({
        "install": install_dict(install),
        "from": current,
        "to": target.version,
        "breaking": profile["breaking"],
        "changes": profile["changes"],
    })


@endpoint()
def install_resolve(request):
    """安装解析预演（不落库）：平台兼容、依赖与冲突原因。"""
    listing = listing_by_reference(request)
    platform_version = _platform_version(request)
    resolution = services.resolve_install(
        listing,
        platform_version,
        services.installed_version_map(request.user),
        request.user,
    )
    return ok(resolution)


INSTALL_ENDPOINT_COUNT = 8
