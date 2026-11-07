# -*- coding: utf-8 -*-
"""应用市场冒烟测试：发布者认证 / 分类 / 应用与版本 / 审核上架 / 安装解析 /
评价聚合 / 定价购买与许可证 / Webhook 投递 / 合集 / 举报 / 统计。

用法（在 backend 目录，需先启动或直接使用测试客户端）：
    python marketplace_smoke_test.py

特点：全部通过真实 HTTP 路由（APIClient）打，不做 mock；
Webhook 为本地模拟投递（URL 含 fail 时模拟 500），不访问网络。
脚本会在开发库留下 smoke_ 前缀的测试数据，便于人工复核。
"""
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

User = get_user_model()

PASSED, FAILED = [], []
BASE = "/api/marketplace"


def check(name, ok, extra=""):
    """记录一条冒烟结果。"""
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f"  {extra}" if extra and not ok else ""))


def section(title):
    """打印分节标题。"""
    print(f"\n=== {title} ===")


def login(username, password):
    """登录并返回带 Bearer 令牌的客户端。"""
    client = APIClient()
    response = client.post("/api/auth/login/",
                           {"username": username, "password": password},
                           format="json")
    assert response.status_code == 200, f"登录失败 {response.status_code} {response.data}"
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


def ensure_user(username, password="smoke1234"):
    """确保冒烟账号存在（已存在则直接复用）。"""
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"nickname": username},
    )
    if created:
        user.set_password(password)
        user.save(update_fields=["password"])
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def body(response):
    """取统一响应体（成功取 data，失败取 error）。"""
    data = getattr(response, "data", None) or {}
    return data.get("data") if isinstance(data, dict) else None


def error(response):
    """取统一错误信息。"""
    data = getattr(response, "data", None) or {}
    return data.get("error") if isinstance(data, dict) else str(data)


def main():
    ts = int(time.time())
    admin = login("admin", "admin123")
    maker, maker_user = ensure_user(f"smoke_maker_{ts}")
    buyer, buyer_user = ensure_user(f"smoke_buyer_{ts}")
    print(f"冒烟标识: {ts}")

    # ------------------------------------------------------------------
    section("1. 目录与分类")
    # ------------------------------------------------------------------
    r = admin.get(f"{BASE}/")
    catalog = body(r)
    check("目录接口可用", r.status_code == 200 and catalog and catalog.get("endpoints"),
          str(error(r)))
    check("端点数不少于 100", bool(catalog) and len(catalog.get("endpoints") or []) >= 100)
    check("分页上限为 200",
          bool(catalog) and catalog["pagination"]["page_size_max"] == 200)

    r = admin.post(f"{BASE}/categories/", {
        "code": f"smoke-tools-{ts}", "name": "冒烟工具"}, format="json")
    category_id = (body(r) or {}).get("id")
    check("管理员创建分类", r.status_code == 200 and category_id, str(error(r)))

    r = maker.post(f"{BASE}/categories/", {
        "code": f"smoke-bad-{ts}", "name": "越权分类"}, format="json")
    check("非管理员不能建分类", r.status_code == 400 and "仅管理员" in str(error(r)))

    # ------------------------------------------------------------------
    section("2. 发布者与应用版本")
    # ------------------------------------------------------------------
    r = maker.post(f"{BASE}/publishers/", {
        "name": "冒烟工作室", "slug": f"smoke-studio-{ts}",
        "contact_email": "smoke@example.com"}, format="json")
    publisher_id = (body(r) or {}).get("id")
    check("创建发布者", r.status_code == 200 and publisher_id, str(error(r)))

    r = admin.post(f"{BASE}/publishers/{publisher_id}/verify/", {}, format="json")
    check("管理员认证发布者", r.status_code == 200, str(error(r)))

    r = maker.post(f"{BASE}/listings/", {
        "name": "冒烟应用", "code": f"smoke-app-{ts}",
        "publisher_id": publisher_id, "category_id": category_id,
        "type": "app", "pricing_mode": "free",
        "summary": "用于冒烟验证的应用", "tags": ["冒烟", "测试"]}, format="json")
    listing_id = (body(r) or {}).get("id")
    check("创建应用草稿", r.status_code == 200 and listing_id, str(error(r)))

    version_ids = {}
    for version, minimum in (("1.0.0", "3.0.0"), ("1.1.0", "3.2.0")):
        r = maker.post(f"{BASE}/listings/{listing_id}/versions/", {
            "version": version, "min_platform_version": minimum,
            "manifest": {"requires": []},
            "changelog": f"冒烟版本 {version}"}, format="json")
        version_ids[version] = (body(r) or {}).get("id")
        check(f"创建版本 {version}", r.status_code == 200, str(error(r)))

    r = maker.post(f"{BASE}/listings/{listing_id}/submit/", {}, format="json")
    check("提交审核", r.status_code == 200, str(error(r)))
    r = admin.post(f"{BASE}/listings/{listing_id}/approve/",
                   {"note": "冒烟通过"}, format="json")
    check("管理员审核上架", r.status_code == 200, str(error(r)))
    # 审核通过会自动发布最高版本（1.1.0），单独发布接口改测未被自动发布的 1.0.0；
    # 重复发布已发布版本会被拒（"版本已发布"），不属于本步骤要验证的行为。
    r = maker.post(f"{BASE}/versions/{version_ids['1.0.0']}/publish/", {},
                   format="json")
    check("单独发布 1.0.0", r.status_code == 200, str(error(r)))

    r = buyer.get(f"{BASE}/listings/", {"q": "冒烟"})
    data = body(r) or {}
    check("公开列表可检索", r.status_code == 200 and data.get("count", 0) >= 1,
          str(error(r)))
    r = buyer.get(f"{BASE}/listings/{listing_id}/")
    check("详情返回最新版本",
          r.status_code == 200 and (body(r) or {}).get("latest_version"),
          str(error(r)))

    # ------------------------------------------------------------------
    section("3. 安装解析")
    # ------------------------------------------------------------------
    r = buyer.post(f"{BASE}/installs/resolve/", {
        "listing_id": listing_id, "platform_version": "3.8.0"}, format="json")
    resolved = body(r) or {}
    check("解析出平台兼容版本",
          r.status_code == 200 and (resolved.get("resolved") or {}).get("version") == "1.1.0",
          str(error(r)))
    r = buyer.post(f"{BASE}/installs/", {
        "listing_id": listing_id, "platform_version": "3.8.0"}, format="json")
    install_id = ((body(r) or {}).get("install") or {}).get("id")
    check("安装应用", r.status_code == 200 and install_id, str(error(r)))

    # ------------------------------------------------------------------
    section("4. 评价与评分")
    # ------------------------------------------------------------------
    r = buyer.post(f"{BASE}/listings/{listing_id}/reviews/", {
        "rating": 5, "title": "冒烟好评", "content": "功能符合预期"}, format="json")
    review_id = (body(r) or {}).get("id")
    check("提交评价进入待审", r.status_code == 200 and review_id, str(error(r)))
    r = maker.post(f"{BASE}/reviews/{review_id}/publish/", {}, format="json")
    check("维护者发布评价", r.status_code == 200, str(error(r)))
    r = buyer.get(f"{BASE}/listings/{listing_id}/rating/")
    check("评分聚合为 5 星",
          r.status_code == 200 and (body(r) or {}).get("rating") == 5.0,
          str(error(r)))

    # ------------------------------------------------------------------
    section("5. 定价购买与许可证")
    # ------------------------------------------------------------------
    r = maker.post(f"{BASE}/listings/{listing_id}/pricing/", {
        "mode": "paid", "price": "88.00", "currency": "CNY"}, format="json")
    check("设置付费定价", r.status_code == 200, str(error(r)))
    r = buyer.post(f"{BASE}/purchases/", {
        "listing_id": listing_id, "max_activations": 1}, format="json")
    purchase = body(r) or {}
    check("购买并签发许可证", r.status_code == 200 and purchase.get("license_key"),
          str(error(r)))
    license_id = (purchase.get("license") or {}).get("id")
    plain_key = purchase.get("license_key")

    r = buyer.post(f"{BASE}/licenses/verify/", {
        "key": plain_key, "listing_code": f"smoke-app-{ts}"}, format="json")
    check("许可证校验通过", r.status_code == 200 and (body(r) or {}).get("valid"),
          str(error(r)))
    r = buyer.post(f"{BASE}/licenses/{license_id}/activate/",
                   {"device_id": "smoke-device-a"}, format="json")
    check("激活设备", r.status_code == 200 and (body(r) or {}).get("activated"),
          str(error(r)))
    r = buyer.post(f"{BASE}/licenses/{license_id}/activate/",
                   {"device_id": "smoke-device-b"}, format="json")
    check("超激活上限被拒", r.status_code == 400, str(error(r)))

    r = maker.get(f"{BASE}/purchases/{purchase.get('id')}/")
    check("发布者可见分成拆分",
          r.status_code == 200 and (body(r) or {}).get("breakdown"),
          str(error(r)))

    # ------------------------------------------------------------------
    section("6. Webhook 与事件")
    # ------------------------------------------------------------------
    r = maker.post(f"{BASE}/webhooks/", {
        "publisher_id": publisher_id,
        "url": "https://hooks.example.com/marketplace",
        "events": ["*"]}, format="json")
    webhook = body(r) or {}
    check("创建订阅并返回一次密钥",
          r.status_code == 200 and webhook.get("secret"), str(error(r)))
    r = maker.post(f"{BASE}/webhooks/{webhook.get('id')}/test/", {}, format="json")
    check("测试投递成功", r.status_code == 200 and (body(r) or {}).get("success"),
          str(error(r)))
    r = maker.get(f"{BASE}/webhooks/{webhook.get('id')}/deliveries/")
    check("投递记录可查", r.status_code == 200 and (body(r) or {}).get("count", 0) >= 1,
          str(error(r)))

    # ------------------------------------------------------------------
    section("7. 合集与举报")
    # ------------------------------------------------------------------
    r = maker.post(f"{BASE}/collections/", {
        "title": "冒烟精选", "slug": f"smoke-picks-{ts}"}, format="json")
    collection_id = (body(r) or {}).get("id")
    check("创建合集", r.status_code == 200 and collection_id, str(error(r)))
    r = maker.post(f"{BASE}/collections/{collection_id}/items/",
                   {"listing_id": listing_id}, format="json")
    check("加入合集条目", r.status_code == 200, str(error(r)))
    r = maker.post(f"{BASE}/collections/{collection_id}/publish/", {}, format="json")
    check("发布合集", r.status_code == 200, str(error(r)))

    r = buyer.post(f"{BASE}/reports/", {
        "listing_id": listing_id, "reason": "broken",
        "detail": "冒烟举报：无法启动"}, format="json")
    report_id = (body(r) or {}).get("id")
    check("提交举报", r.status_code == 200 and report_id, str(error(r)))
    r = admin.post(f"{BASE}/reports/{report_id}/handle/",
                   {"action": "review"}, format="json")
    check("管理员受理举报", r.status_code == 200, str(error(r)))
    r = admin.post(f"{BASE}/reports/{report_id}/handle/", {
        "action": "resolve", "resolution": "冒烟处置完成"}, format="json")
    check("管理员结案举报", r.status_code == 200, str(error(r)))

    # ------------------------------------------------------------------
    section("8. 统计")
    # ------------------------------------------------------------------
    r = buyer.get(f"{BASE}/stats/overview/")
    check("市场概览可用", r.status_code == 200, str(error(r)))
    r = admin.get(f"{BASE}/stats/revenue/")
    check("收入统计仅管理员可见且可用", r.status_code == 200, str(error(r)))
    r = buyer.get(f"{BASE}/stats/revenue/")
    check("普通用户看不到收入统计", r.status_code == 400, str(error(r)))

    print(f"\n结果: {len(PASSED)} 通过, {len(FAILED)} 失败")
    if FAILED:
        print("失败项: " + ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
