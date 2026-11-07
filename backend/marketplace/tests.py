# -*- coding: utf-8 -*-
"""marketplace 测试：语义化版本、安装解析、许可证、评价聚合、商业分成、
Webhook 投递、合集/举报状态机、截图/兼容标签、统计与权限边界。

运行：venv/Scripts/python.exe manage.py test marketplace -v 1
（测试库为内存 sqlite，不触碰开发库，也不会发起任何网络请求）
"""
from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from marketplace import services
from marketplace.models import (
    Collection,
    Install,
    License,
    Listing,
    MarketplaceEvent,
    Purchase,
    Review,
    WebhookDelivery,
)

User = get_user_model()

BASE = "/api/marketplace"


def ensure_marketplace_tables():
    """测试库补建 marketplace 表。

    本应用暂不提交迁移文件（迁移统一生成是独立任务），空的 migrations 包
    会让 Django 认为该应用「已迁移但没有迁移」，测试库不会 sync 建表。
    这里只在建表阶段做一次幂等补建，不影响开发库/生产库的迁移策略。
    """
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in apps.get_app_config("marketplace").get_models():
            if model._meta.db_table not in existing:
                editor.create_model(model)


class MarketplaceBase(TestCase):
    """公共夹具：四个角色（发布者 / 买家 / 路人 / 管理员）与请求助手。"""

    @classmethod
    def setUpClass(cls):
        # 必须在 TestCase 开启类级事务之前建表（SQLite 事务内不能 DDL）
        ensure_marketplace_tables()
        super().setUpClass()

    def setUp(self):
        self.client = APIClient()
        self.maker = User.objects.create_user(
            username="maker", password="pass1234", nickname="开发者")
        self.buyer = User.objects.create_user(
            username="buyer", password="pass1234", nickname="买家")
        self.other = User.objects.create_user(
            username="other", password="pass1234", nickname="路人")
        self.admin = User.objects.create_user(
            username="admin", password="pass1234", nickname="管理员",
            is_staff=True)

    # ---------- 请求助手 ----------

    def get(self, path, user, params=None):
        """以指定用户身份 GET。"""
        self.client.force_authenticate(user=user)
        return self.client.get(BASE + path, params or {})

    def post(self, path, user, payload=None):
        """以指定用户身份 POST JSON。"""
        self.client.force_authenticate(user=user)
        return self.client.post(BASE + path, payload or {}, format="json")

    def assert_ok(self, response, status=200):
        """断言成功并返回 data，失败时回显错误便于定位。"""
        self.assertEqual(
            response.status_code, status,
            f"期望 {status}，实际 {response.status_code}: {response.data}"
        )
        body = response.data
        self.assertTrue(body.get("ok"))
        return body.get("data")

    def assert_fail(self, response, contains="", status=400):
        """断言 400 业务失败（可校验中文原因片段）。"""
        self.assertEqual(
            response.status_code, status,
            f"期望 {status}，实际 {response.status_code}: {response.data}"
        )
        body = response.data
        self.assertFalse(body.get("ok"))
        if contains:
            self.assertIn(contains, str(body.get("error")))
        return body

    # ---------- 业务助手 ----------

    def make_publisher(self, user=None, name="星河工作室", slug="starlab",
                       email="dev@starlab.example.com"):
        """创建发布者并返回 id。"""
        data = self.assert_ok(self.post("/publishers/", user or self.maker, {
            "name": name,
            "slug": slug,
            "contact_email": email,
            "summary": "专注效率工具",
        }))
        return data["id"]

    def verify_publisher(self, publisher_id):
        """管理员认证发布者。"""
        self.assert_ok(self.post(
            f"/publishers/{publisher_id}/verify/", self.admin, {}))

    def make_category(self, code="tools", name="效率工具", parent_id=None):
        """管理员创建分类并返回 id。"""
        payload = {"code": code, "name": name}
        if parent_id:
            payload["parent_id"] = parent_id
        return self.assert_ok(self.post("/categories/", self.admin, payload))["id"]

    def make_listing(self, publisher_id, name="专注时钟", code="focus-clock",
                     category_id=None, listing_type="app", pricing_mode="free",
                     tags=None):
        """创建应用草稿并返回 id。"""
        payload = {
            "name": name,
            "code": code,
            "publisher_id": publisher_id,
            "type": listing_type,
            "pricing_mode": pricing_mode,
            "summary": "番茄工作法与专注统计",
            "tags": tags or ["效率", "专注"],
        }
        if category_id:
            payload["category_id"] = category_id
        return self.assert_ok(self.post("/listings/", self.maker, payload))["id"]

    def make_version(self, listing_id, version="1.0.0", min_platform="3.0.0",
                     manifest=None, changelog=""):
        """创建版本草稿并返回 id。"""
        return self.assert_ok(self.post(
            f"/listings/{listing_id}/versions/", self.maker, {
                "version": version,
                "min_platform_version": min_platform,
                "manifest": manifest or {"requires": []},
                "changelog": changelog or f"发布 {version}",
                "package_size": 1024,
            }))["id"]

    def publish_listing(self, listing_id):
        """提交审核并由管理员审核通过。"""
        self.assert_ok(self.post(f"/listings/{listing_id}/submit/", self.maker, {}))
        return self.assert_ok(self.post(
            f"/listings/{listing_id}/approve/", self.admin, {"note": "通过"}))

    def bootstrap_listing(self, pricing_mode="free", versions=None,
                          category_id=None, code="focus-clock"):
        """一步到位：认证发布者 → 建应用 → 建版本 → 审核上架。"""
        publisher_id = self.make_publisher()
        self.verify_publisher(publisher_id)
        listing_id = self.make_listing(
            publisher_id, code=code, pricing_mode=pricing_mode,
            category_id=category_id)
        for version, min_platform in (versions or [("1.0.0", "3.0.0")]):
            self.make_version(listing_id, version, min_platform)
        self.publish_listing(listing_id)
        return publisher_id, listing_id


# ===========================================================================
# 1. 语义化版本（纯函数）
# ===========================================================================


class SemverTests(MarketplaceBase):
    """版本解析、比较、范围约束与升级差异。"""

    def test_parse_and_compare(self):
        parsed = services.parse_version("v1.2.3-beta.2+build.7")
        self.assertEqual(parsed["major"], 1)
        self.assertEqual(parsed["minor"], 2)
        self.assertEqual(parsed["patch"], 3)
        self.assertEqual(parsed["prerelease"], ("beta", "2"))
        self.assertTrue(parsed["is_prerelease"])

        # build 不参与比较；预发布低于正式版
        self.assertEqual(services.compare_versions("1.0.0+a", "1.0.0+b"), 0)
        self.assertLess(services.compare_versions("1.0.0-beta", "1.0.0"), 0)
        self.assertLess(services.compare_versions("1.0.0-alpha", "1.0.0-beta"), 0)
        self.assertLess(services.compare_versions("1.0.0-beta.2", "1.0.0-beta.10"), 0)
        with self.assertRaisesMessage(ValueError, "语义化版本"):
            services.parse_version("1.2")

    def test_satisfies_and_ranges(self):
        self.assertTrue(services.satisfies("1.4.2", ">=1.2.0"))
        self.assertTrue(services.satisfies("1.9.9", "^1.4.0"))
        self.assertFalse(services.satisfies("2.0.0", "^1.4.0"))
        self.assertTrue(services.satisfies("0.2.9", "^0.2.3"))
        self.assertFalse(services.satisfies("0.3.0", "^0.2.3"))
        # 空格是 AND，|| 是 OR
        self.assertTrue(services.satisfies("1.5.0", ">=1.2.0 <2.0.0"))
        self.assertFalse(services.satisfies("2.1.0", ">=1.2.0 <2.0.0"))
        self.assertTrue(services.satisfies("3.1.0", "^1.0.0 || ^3.0.0"))
        # 预发布默认不被稳定范围匹配（避免误判可安装）
        self.assertFalse(services.satisfies("2.0.0-beta", ">=1.0.0"))
        self.assertTrue(services.satisfies("2.0.0-beta", ">=2.0.0-beta"))
        # ~1.4 → >=1.4.0 <1.5.0
        self.assertTrue(services.satisfies("1.4.9", "~1.4"))
        self.assertFalse(services.satisfies("1.5.0", "~1.4"))
        self.assertEqual(services.max_satisfying(
            ["1.0.0", "1.4.0", "1.5.0", "2.0.0"], "^1.0.0"), "1.5.0")
        with self.assertRaisesMessage(ValueError, "无法识别"):
            services.parse_range(">=abc")

    def test_next_and_diff(self):
        self.assertEqual(services.next_version("1.2.3", "patch"), "1.2.4")
        self.assertEqual(services.next_version("1.2.3", "minor"), "1.3.0")
        self.assertEqual(services.next_version("1.2.3", "major"), "2.0.0")
        self.assertTrue(services.is_breaking_change("1.9.0", "2.0.0"))
        self.assertTrue(services.is_breaking_change("0.1.5", "0.2.0"))
        self.assertFalse(services.is_breaking_change("1.0.0", "1.1.0"))
        diff = services.diff_versions("1.2.3", "1.2.5")
        self.assertEqual(diff["direction"], "upgrade")
        self.assertEqual(diff["level"], "patch")
        self.assertEqual(diff["patch_delta"], 2)
        self.assertFalse(diff["breaking"])
        self.assertEqual(services.highest_version(
            ["1.0.0", "2.0.0-rc.1", "2.0.0"]), "2.0.0")


class LicenseUtilTests(MarketplaceBase):
    """许可证密钥生成/哈希/掩码的纯函数行为。"""

    def test_key_helpers(self):
        key = services.generate_license_key()
        self.assertGreaterEqual(len(key), 20)
        self.assertEqual(services.hash_license_key(key),
                         services.hash_license_key(key))
        self.assertNotEqual(services.hash_license_key(key),
                            services.hash_license_key(key + "x"))
        masked = services.mask_license_key(key)
        self.assertIn("****", masked)
        self.assertNotEqual(masked, key)


# ===========================================================================
# 2. 发布者 / 分类（权限与基础 CRUD）
# ===========================================================================


class PublisherCategoryTests(MarketplaceBase):
    """发布者认证、分类树与管理员边界。"""

    def test_publisher_lifecycle_and_admin_guards(self):
        publisher_id = self.make_publisher()
        detail = self.assert_ok(self.get(f"/publishers/{publisher_id}/", self.buyer))
        self.assertEqual(detail["status"], "pending")
        self.assertEqual(detail["slug"], "starlab")

        # 重名 slug 拒绝
        self.assert_fail(self.post("/publishers/", self.buyer, {
            "name": "冒名工作室", "slug": "starlab"}), "已被占用")
        # 非所有者不能改
        self.assert_fail(self.post(
            f"/publishers/{publisher_id}/update/", self.buyer, {"name": "x"}),
            "无权修改")
        # 认证仅管理员
        self.assert_fail(self.post(
            f"/publishers/{publisher_id}/verify/", self.maker, {}), "仅管理员")
        self.assert_ok(self.post(
            f"/publishers/{publisher_id}/verify/", self.admin, {}))
        # 分成比例仅管理员可调
        self.assert_fail(self.post(
            f"/publishers/{publisher_id}/update/", self.maker,
            {"revenue_share": 80}), "仅管理员")
        data = self.assert_ok(self.post(
            f"/publishers/{publisher_id}/update/", self.admin,
            {"revenue_share": 75}))
        self.assertEqual(data["revenue_share"], 75.0)

        mine = self.assert_ok(self.get("/publishers/mine/", self.maker))
        self.assertEqual(mine["count"], 1)
        stats = self.assert_ok(self.get(
            f"/publishers/{publisher_id}/overview/", self.maker))
        self.assertEqual(stats["listings"]["total"], 0)
        self.assert_fail(self.get(
            f"/publishers/{publisher_id}/overview/", self.buyer), "无权查看")

    def test_category_crud_and_tree(self):
        root = self.make_category("tools", "效率工具")
        child = self.make_category("focus", "专注", parent_id=root)
        self.assert_fail(self.post("/categories/", self.maker, {
            "code": "bad", "name": "无权限"}), "仅管理员")
        tree = self.assert_ok(self.get("/categories/tree/", self.buyer))
        roots = {item["code"]: item for item in tree["items"]}
        self.assertIn("tools", roots)
        self.assertEqual(roots["tools"]["children"][0]["code"], "focus")

        # 有子分类时不能直接删父级
        self.assert_fail(self.post(
            f"/categories/{root}/delete/", self.admin, {}), "子分类")
        self.assert_ok(self.post(f"/categories/{child}/delete/", self.admin, {}))
        self.assert_ok(self.post(f"/categories/{root}/delete/", self.admin, {}))
        # parent_id 不能成环：用不存在的父级覆盖
        empty = self.assert_ok(self.get("/categories/", self.buyer))
        self.assertEqual(empty["count"], 0)


# ===========================================================================
# 3. 应用与版本生命周期
# ===========================================================================


class ListingLifecycleTests(MarketplaceBase):
    """草稿 → 审核 → 上架 → 下架/暂停 → 克隆/推荐位/标签。"""

    def test_full_lifecycle_and_guards(self):
        publisher_id = self.make_publisher()
        category_id = self.make_category()
        listing_id = self.make_listing(publisher_id, category_id=category_id)
        self.make_version(listing_id, "1.0.0")

        # 未认证发布者不能提交审核
        self.assert_fail(self.post(
            f"/listings/{listing_id}/submit/", self.maker, {}), "尚未认证")
        self.verify_publisher(publisher_id)
        submitted = self.assert_ok(self.post(
            f"/listings/{listing_id}/submit/", self.maker, {}))
        self.assertEqual(submitted["status"], "reviewing")

        # 审核仅管理员
        self.assert_fail(self.post(
            f"/listings/{listing_id}/approve/", self.maker, {}), "仅管理员")
        approved = self.assert_ok(self.post(
            f"/listings/{listing_id}/approve/", self.admin, {"note": "ok"}))
        self.assertEqual(approved["status"], "published")
        self.assertEqual(approved["latest_version"]["version"], "1.0.0")

        # 公开列表 / 搜索 / 详情
        listing = self.assert_ok(self.get("/listings/", self.buyer))
        self.assertEqual(listing["count"], 1)
        found = self.assert_ok(self.get(
            "/listings/search/", self.buyer, {"q": "专注"}))
        self.assertEqual(found["count"], 1)
        detail = self.assert_ok(self.get(
            f"/listings/{listing_id}/", self.buyer))
        self.assertFalse(detail["viewer"]["installed"])
        self.assertEqual(detail["latest_version"]["version"], "1.0.0")

        # 已上架不能直接编辑；管理员可以（代运营）
        self.assert_fail(self.post(
            f"/listings/{listing_id}/update/", self.maker, {"name": "改名"}),
            "不能直接编辑")
        self.assert_ok(self.post(
            f"/listings/{listing_id}/update/", self.admin, {"summary": "运营改写"}))

        # 下架 → 重新上架
        delisted = self.assert_ok(self.post(
            f"/listings/{listing_id}/delist/", self.maker, {"reason": "维护"}))
        self.assertEqual(delisted["status"], "delisted")
        hidden = self.assert_ok(self.get("/listings/", self.buyer))
        self.assertEqual(hidden["count"], 0)
        republished = self.assert_ok(self.post(
            f"/listings/{listing_id}/publish/", self.maker, {}))
        self.assertEqual(republished["status"], "published")

        # 推荐位与标签仅管理员/维护者
        self.assert_fail(self.post(
            f"/listings/{listing_id}/feature/", self.maker, {}), "仅管理员")
        featured = self.assert_ok(self.post(
            f"/listings/{listing_id}/feature/", self.admin,
            {"featured": True, "featured_rank": 3}))
        self.assertTrue(featured["featured"])
        tags = self.assert_ok(self.post(
            f"/listings/{listing_id}/tags/", self.maker,
            {"tags": "效率, 专注,效率"}))
        self.assertEqual(tags["tags"], ["效率", "专注"])

        # 克隆：复制版本但不复制安装/订单/评价
        clone = self.assert_ok(self.post(
            f"/listings/{listing_id}/clone/", self.maker, {}))
        self.assertEqual(clone["status"], "draft")
        clone_versions = self.assert_ok(self.get(
            f"/listings/{clone['id']}/versions/", self.maker))
        self.assertEqual(clone_versions["count"], 1)

        # 暂停仅管理员，上架状态被收敛
        self.assert_fail(self.post(
            f"/listings/{listing_id}/suspend/", self.maker, {"reason": "x"}),
            "仅管理员")
        suspended = self.assert_ok(self.post(
            f"/listings/{listing_id}/suspend/", self.admin, {"reason": "违规"}))
        self.assertEqual(suspended["status"], "suspended")
        self.assert_fail(self.post(
            f"/listings/{listing_id}/publish/", self.maker, {}), "仅管理员")

    def test_reject_withdraw_and_validation(self):
        publisher_id = self.make_publisher()
        self.verify_publisher(publisher_id)
        listing_id = self.make_listing(publisher_id, code="flow-app")
        # 版本号必须严格 semver
        self.assert_fail(self.post(
            f"/listings/{listing_id}/versions/", self.maker,
            {"version": "1.0"}), "语义化版本")
        self.make_version(listing_id, "1.0.0")
        # 重复版本号
        self.assert_fail(self.post(
            f"/listings/{listing_id}/versions/", self.maker,
            {"version": "1.0.0"}), "已存在")

        self.assert_ok(self.post(f"/listings/{listing_id}/submit/", self.maker, {}))
        self.assert_ok(self.post(f"/listings/{listing_id}/withdraw/", self.maker, {}))
        self.assert_ok(self.post(f"/listings/{listing_id}/submit/", self.maker, {}))
        # 驳回必须给理由
        self.assert_fail(self.post(
            f"/listings/{listing_id}/reject/", self.admin, {"reason": ""}),
            "缺少必填")
        rejected = self.assert_ok(self.post(
            f"/listings/{listing_id}/reject/", self.admin,
            {"reason": "截图不清晰"}))
        self.assertEqual(rejected["status"], "draft")

    def test_pagination_cap_and_visibility(self):
        publisher_id = self.make_publisher()
        listing_id = self.make_listing(publisher_id, code="draft-only")
        # 草稿对他人不可见
        self.assert_fail(self.get(f"/listings/{listing_id}/", self.buyer), "未上架")
        self.assert_ok(self.get(f"/listings/{listing_id}/", self.maker))
        # page_size 上限 200
        self.assert_fail(self.get(
            "/listings/", self.buyer, {"page_size": 201}), "page_size")
        # 非法 status 枚举
        self.assert_fail(self.get(
            "/listings/", self.buyer, {"status": "flying"}), "status")
        # 他人不能在该发布者下建应用
        self.assert_fail(self.post("/listings/", self.buyer, {
            "name": "越权应用", "publisher_id": publisher_id}), "无权")
        # 有安装时不能删除应用（先上架再安装）
        self.verify_publisher(publisher_id)
        self.make_version(listing_id, "1.0.0")
        self.publish_listing(listing_id)
        self.assert_ok(self.post("/installs/", self.buyer,
                                 {"listing_id": listing_id}))
        self.assert_ok(self.post(f"/listings/{listing_id}/delist/", self.maker, {}))
        self.assert_fail(self.post(
            f"/listings/{listing_id}/delete/", self.maker, {}), "安装")

    def test_version_compare_and_management(self):
        publisher_id = self.make_publisher()
        self.verify_publisher(publisher_id)
        listing_id = self.make_listing(publisher_id, code="ver-app")
        v1 = self.make_version(listing_id, "1.0.0", manifest={"requires": []})
        v2 = self.make_version(
            listing_id, "2.0.0-beta.1", "3.2.0",
            manifest={"requires": [{"code": "core-kit", "range": "^1.0.0"}]})
        compare = self.assert_ok(self.get("/versions/compare/", self.buyer, {
            "listing_id": listing_id, "from": "1.0.0", "to": "2.0.0-beta.1"}))
        self.assertTrue(compare["diff"]["breaking"])
        self.assertEqual(compare["requires"]["added"][0]["code"], "core-kit")
        self.assert_fail(self.get("/versions/compare/", self.buyer, {
            "listing_id": listing_id, "from": "1.0.0", "to": "9.9.9"}),
            "不存在")

        # 草稿版本可改/可删，发布后不可删
        updated = self.assert_ok(self.post(
            f"/versions/{v1}/update/", self.maker, {"changelog": "补充说明"}))
        self.assertEqual(updated["changelog"], "补充说明")
        # 依赖不存在时发布版本应被拦下
        self.assert_fail(self.post(
            f"/versions/{v2}/publish/", self.maker, {}), "依赖检查")
        self.assert_ok(self.post(f"/versions/{v1}/publish/", self.maker, {}))
        self.assert_fail(self.post(
            f"/versions/{v1}/delete/", self.maker, {}), "草稿")
        delisted = self.assert_ok(self.post(
            f"/versions/{v1}/delist/", self.maker, {}))
        self.assertEqual(delisted["status"], "delisted")
        self.assert_fail(self.post(
            f"/versions/{v1}/publish/", self.maker, {}), "已下架")
        self.assert_ok(self.post(f"/versions/{v2}/delete/", self.maker, {}))
        # 升级检查：没有候选时给出原因
        check = self.assert_ok(self.get(
            f"/listings/{listing_id}/upgrade-check/", self.maker,
            {"current_version": "1.0.0"}))
        self.assertFalse(check["upgrade_available"])


# ===========================================================================
# 4. 安装解析与升级
# ===========================================================================


class InstallFlowTests(MarketplaceBase):
    """平台兼容选版、依赖冲突、安装/启停/配置/升级/卸载。"""

    def test_platform_resolution_install_and_upgrade(self):
        publisher_id = self.make_publisher()
        self.verify_publisher(publisher_id)
        listing_id = self.make_listing(publisher_id, code="platform-app")
        self.make_version(listing_id, "1.0.0", "3.0.0")
        self.make_version(listing_id, "1.1.0", "3.2.0")
        self.make_version(listing_id, "2.0.0", "3.9.0")
        self.publish_listing(listing_id)
        # 审核发布的是最高版本 2.0.0，平台 3.8 不兼容；单独发布 1.1.0
        versions = self.assert_ok(self.get(
            f"/listings/{listing_id}/versions/", self.maker))
        by_version = {row["version"]: row["id"] for row in versions["items"]}
        self.assert_ok(self.post(
            f"/versions/{by_version['1.1.0']}/publish/", self.maker, {}))
        self.assert_ok(self.post(
            f"/versions/{by_version['1.0.0']}/publish/", self.maker, {}))

        resolved = self.assert_ok(self.post("/installs/resolve/", self.buyer, {
            "listing_id": listing_id, "platform_version": "3.8.0"}))
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["resolved"]["version"], "1.1.0")

        data = self.assert_ok(self.post("/installs/", self.buyer, {
            "listing_id": listing_id, "platform_version": "3.8.0",
            "auto_update": True}))
        install_id = data["install"]["id"]
        self.assertEqual(data["install"]["version"]["version"], "1.1.0")
        self.assertEqual(data["action"], "installed")

        current = self.assert_ok(self.get(
            f"/installs/{install_id}/", self.buyer))
        self.assertEqual(current["version"]["version"], "1.1.0")
        self.assertIn("resolution", current)

        # 配置必须是 JSON 对象
        self.assert_fail(self.post(
            f"/installs/{install_id}/config/", self.buyer,
            {"config": ["x"]}), "必须是对象")
        conf = self.assert_ok(self.post(
            f"/installs/{install_id}/config/", self.buyer,
            {"config": {"theme": "dark"}}))
        self.assertEqual(conf["config"]["theme"], "dark")

        disabled = self.assert_ok(self.post(
            f"/installs/{install_id}/disable/", self.buyer, {}))
        self.assertTrue(disabled["changed"])
        enabled = self.assert_ok(self.post(
            f"/installs/{install_id}/enable/", self.buyer, {}))
        self.assertTrue(enabled["changed"])

        # 新版本发布后可升级
        self.make_version(listing_id, "1.2.0", "3.0.0")
        new_versions = self.assert_ok(self.get(
            f"/listings/{listing_id}/versions/", self.maker))
        target = {row["version"]: row["id"] for row in new_versions["items"]}["1.2.0"]
        self.assert_ok(self.post(f"/versions/{target}/publish/", self.maker, {}))
        upgraded = self.assert_ok(self.post(
            f"/installs/{install_id}/upgrade/", self.buyer,
            {"platform_version": "3.8.0"}))
        self.assertEqual(upgraded["from"], "1.1.0")
        self.assertEqual(upgraded["to"], "1.2.0")
        self.assertFalse(upgraded["breaking"])
        self.assert_fail(self.post(
            f"/installs/{install_id}/upgrade/", self.buyer,
            {"platform_version": "3.8.0"}), "已是最新")

        listing = Listing.objects.get(pk=listing_id)
        self.assertEqual(listing.install_count, 1)
        mine = self.assert_ok(self.get("/installs/", self.buyer))
        self.assertEqual(mine["count"], 1)
        self.assert_fail(self.get(
            f"/installs/{install_id}/", self.maker), "无权访问")

        uninstalled = self.assert_ok(self.post(
            f"/installs/{install_id}/uninstall/", self.buyer, {}))
        self.assertEqual(uninstalled["status"], "uninstalled")
        self.assert_fail(self.post(
            f"/installs/{install_id}/uninstall/", self.buyer, {}), "已卸载")
        listing.refresh_from_db()
        self.assertEqual(listing.install_count, 0)

    def test_dependency_conflict_reason(self):
        publisher_id = self.make_publisher()
        self.verify_publisher(publisher_id)
        dep_id = self.make_listing(
            publisher_id, name="核心组件", code="core-kit")
        self.make_version(dep_id, "1.0.0")
        self.publish_listing(dep_id)

        main_id = self.make_listing(
            publisher_id, name="依赖方", code="dep-user")
        self.make_version(main_id, "1.0.0", manifest={
            "requires": [{"code": "core-kit", "range": "^1.0.0"}]})
        self.publish_listing(main_id)
        ok = self.assert_ok(self.post("/installs/resolve/", self.buyer, {
            "listing_id": main_id}))
        self.assertTrue(ok["ok"])
        codes = {item["code"] for item in ok["plan"]}
        self.assertIn("core-kit", codes)

        bad_id = self.make_listing(
            publisher_id, name="坏依赖", code="bad-dep")
        self.make_version(bad_id, "1.0.0", manifest={
            "requires": [{"code": "ghost-lib", "range": "^2.0.0"}]})
        # 依赖不存在：提交审核时就会被拦下
        self.assert_fail(self.post(
            f"/listings/{bad_id}/submit/", self.maker, {}), "依赖检查")
        # 版本发布同样拦截
        versions = self.assert_ok(self.get(
            f"/listings/{bad_id}/versions/", self.maker))
        version_id = versions["items"][0]["id"]
        self.assert_fail(self.post(
            f"/versions/{version_id}/publish/", self.maker, {}), "依赖检查")


# ===========================================================================
# 5. 评价与评分聚合
# ===========================================================================


class ReviewRatingTests(MarketplaceBase):
    """评价待审、发布后计分、隐藏重算、有用票与回复。"""

    def test_review_moderation_and_rating(self):
        publisher_id, listing_id = self.bootstrap_listing()

        # 星级越界与重复评价
        self.assert_fail(self.post(
            f"/listings/{listing_id}/reviews/", self.buyer, {"rating": 6}), "")
        review = self.assert_ok(self.post(
            f"/listings/{listing_id}/reviews/", self.buyer, {
                "rating": 5, "title": "很好用", "content": "专注统计很准"}))
        review_id = review["id"]
        self.assertEqual(review["status"], "pending")
        self.assert_fail(self.post(
            f"/listings/{listing_id}/reviews/", self.buyer, {"rating": 4}),
            "已经评价过")

        # 待审评价不计入评分
        rating = self.assert_ok(self.get(
            f"/listings/{listing_id}/rating/", self.buyer))
        self.assertEqual(rating["rating_count"], 0)
        self.assertEqual(rating["by_status"]["pending"], 1)

        # 只有维护者/管理员能发布评价
        self.assert_fail(self.post(
            f"/reviews/{review_id}/publish/", self.buyer, {}), "维护者")
        published = self.assert_ok(self.post(
            f"/reviews/{review_id}/publish/", self.maker, {}))
        self.assertEqual(published["rating_summary"]["rating"], 5.0)
        listing = Listing.objects.get(pk=listing_id)
        self.assertEqual(listing.rating_count, 1)
        self.assertEqual(float(listing.rating), 5.0)

        # 有用票：自己不能投，路人可以（再点取消）
        self.assert_fail(self.post(
            f"/reviews/{review_id}/helpful/", self.buyer, {}), "自己")
        voted = self.assert_ok(self.post(
            f"/reviews/{review_id}/helpful/", self.other, {}))
        self.assertTrue(voted["helpful"])
        self.assertEqual(voted["helpful_count"], 1)
        unvoted = self.assert_ok(self.post(
            f"/reviews/{review_id}/helpful/", self.other, {}))
        self.assertFalse(unvoted["helpful"])

        # 回复权限与计数
        self.assert_fail(self.post(
            f"/reviews/{review_id}/replies/", self.other,
            {"content": "路过"}), "只有评价作者")
        reply = self.assert_ok(self.post(
            f"/reviews/{review_id}/replies/", self.maker,
            {"content": "感谢反馈"}))
        self.assert_ok(self.get(
            f"/reviews/{review_id}/replies/", self.buyer))
        deleted = self.assert_ok(self.post(
            f"/replies/{reply['id']}/delete/", self.maker, {}))
        self.assertEqual(deleted["reply_count"], 0)

        # 隐藏必须给原因，隐藏后评分归零
        self.assert_fail(self.post(
            f"/reviews/{review_id}/hide/", self.maker, {"reason": ""}),
            "缺少必填")
        hidden = self.assert_ok(self.post(
            f"/reviews/{review_id}/hide/", self.maker, {"reason": "刷分"}))
        self.assertEqual(hidden["rating_summary"]["rating"], 0.0)
        listing.refresh_from_db()
        self.assertEqual(listing.rating_count, 0)
        self.assert_fail(self.post(
            f"/reviews/{review_id}/update/", self.buyer, {"rating": 1}),
            "已被隐藏")

        # 评价公开列表只含已发布
        public = self.assert_ok(self.get(
            f"/listings/{listing_id}/reviews/", self.buyer))
        self.assertEqual(public["count"], 0)
        mine = self.assert_ok(self.get("/reviews/mine/", self.buyer))
        self.assertEqual(mine["count"], 1)
        self.assert_ok(self.post(
            f"/reviews/{review_id}/delete/", self.maker, {}))


# ===========================================================================
# 6. 定价、购买、许可证与收入分成
# ===========================================================================


class CommerceTests(MarketplaceBase):
    """付费应用：定价 → 购买签发许可证 → 激活/校验 → 退款撤销。"""

    def test_paid_purchase_license_and_refund(self):
        publisher_id, listing_id = self.bootstrap_listing(pricing_mode="paid")

        priced = self.assert_ok(self.post(
            f"/listings/{listing_id}/pricing/", self.maker, {
                "mode": "paid", "price": "99.00", "currency": "CNY",
                "period": "one_time"}))
        pricing_id = priced["pricing"]["id"]
        self.assertEqual(priced["pricing"]["price"], 99.0)

        # 付费应用未购买不能安装
        self.assert_fail(self.post("/installs/", self.buyer, {
            "listing_id": listing_id}), "请先购买")
        # 免费应用走购买入口也不应产生订单
        free_id = self.make_listing(
            publisher_id, name="免费应用", code="free-app")
        self.make_version(free_id, "1.0.0")
        self.publish_listing(free_id)
        self.assert_fail(self.post(
            "/purchases/", self.buyer, {"listing_id": free_id}), "免费应用")
        # 发布者不能购买自己的应用
        self.assert_fail(self.post(
            "/purchases/", self.maker, {"listing_id": listing_id}), "自己")

        bought = self.assert_ok(self.post("/purchases/", self.buyer, {
            "listing_id": listing_id, "max_activations": 1}))
        purchase_id = bought["id"]
        self.assertEqual(bought["price"], 99.0)
        self.assertTrue(bought["license_key"])
        license_id = bought["license"]["id"]
        self.assertEqual(bought["license"]["status"], "active")
        self.assert_fail(self.post(
            "/purchases/", self.buyer, {"listing_id": listing_id}),
            "重复购买")

        self.assertEqual(bought["status"], "paid")
        # 购买后可以安装
        self.assert_ok(self.post("/installs/", self.buyer, {
            "listing_id": listing_id}))

        # 分成：发布者 70%，平台 30%
        detail = self.assert_ok(self.get(
            f"/purchases/{purchase_id}/", self.maker))
        self.assertEqual(detail["breakdown"]["gross"], 99.0)
        self.assertEqual(detail["breakdown"]["publisher_net"], 69.3)
        self.assertEqual(detail["breakdown"]["platform_fee"], 29.7)
        overview = self.assert_ok(self.get(
            f"/publishers/{publisher_id}/overview/", self.maker))
        self.assertEqual(overview["revenue"]["publisher_net"], 69.3)

        # 许可证校验：密钥/应用一致性
        verified = self.assert_ok(self.post("/licenses/verify/", self.buyer, {
            "key": bought["license_key"],
            "listing_code": "focus-clock"}))
        self.assertTrue(verified["valid"])
        self.assert_fail(self.post("/licenses/verify/", self.buyer, {
            "key": "LK-FAKE-KEY"}), "无效")

        # 激活上限 1：第二台设备被拒，停用后可换绑
        first = self.assert_ok(self.post(
            f"/licenses/{license_id}/activate/", self.buyer,
            {"device_id": "device-a"}))
        self.assertEqual(first["activation_count"], 1)
        self.assert_fail(self.post(
            f"/licenses/{license_id}/activate/", self.buyer,
            {"device_id": "device-b"}), "上限")
        deactivated = self.assert_ok(self.post(
            f"/licenses/{license_id}/deactivate/", self.buyer, {}))
        self.assertEqual(deactivated["remaining"], 0)
        self.assert_ok(self.post(
            f"/licenses/{license_id}/activate/", self.buyer,
            {"device_id": "device-b"}))
        self.assert_fail(self.post(
            f"/licenses/{license_id}/activate/", self.maker,
            {"device_id": "hack"}), "无权")

        licenses = self.assert_ok(self.get("/licenses/", self.buyer))
        self.assertEqual(licenses["count"], 1)
        self.assert_ok(self.get(
            f"/purchases/{purchase_id}/license/", self.buyer))
        # 明细不返回密钥哈希
        license_detail = self.assert_ok(self.get(
            f"/licenses/{license_id}/", self.buyer))
        self.assertNotIn("key_hash", license_detail)

        # 退款：撤销许可证，安装资格随之失效
        refunded = self.assert_ok(self.post(
            f"/purchases/{purchase_id}/refund/", self.buyer,
            {"reason": "不需要了"}))
        self.assertEqual(refunded["status"], "refunded")
        self.assertEqual(refunded["license"]["status"], "revoked")
        after = self.assert_ok(self.post("/licenses/verify/", self.buyer, {
            "key": bought["license_key"]}))
        self.assertFalse(after["valid"])
        self.assertIn("撤销", "；".join(after["reasons"]))
        self.assert_fail(self.post(
            f"/purchases/{purchase_id}/refund/", self.buyer, {}), "已退款")
        self.assert_fail(self.post("/installs/", self.other, {
            "listing_id": listing_id}), "请先购买")

        revenue = self.assert_ok(self.get("/stats/revenue/", self.admin))
        self.assertEqual(revenue["refund_cny"], 99.0)
        self.assertEqual(revenue["orders"], 1)
        self.assert_fail(self.get("/stats/revenue/", self.maker), "仅管理员")

    def test_pricing_validation_and_delete_guard(self):
        publisher_id, listing_id = self.bootstrap_listing(pricing_mode="paid")
        self.assert_fail(self.post(
            f"/listings/{listing_id}/pricing/", self.maker,
            {"mode": "paid", "price": "0"}), "必须大于 0")
        self.assert_fail(self.post(
            f"/listings/{listing_id}/pricing/", self.maker,
            {"mode": "unknown"}), "mode")
        priced = self.assert_ok(self.post(
            f"/listings/{listing_id}/pricing/", self.maker,
            {"mode": "paid", "price": "10", "currency": "USD"}))
        pricing_id = priced["pricing"]["id"]
        updated = self.assert_ok(self.post(
            f"/pricing/{pricing_id}/update/", self.maker,
            {"price": "12.5", "trial_days": 7}))
        self.assertEqual(updated["price"], 12.5)
        self.assert_ok(self.post("/purchases/", self.buyer, {
            "listing_id": listing_id, "pay": False}))
        # 有订单（含待支付）时不能删除定价
        self.assert_fail(self.post(
            f"/pricing/{pricing_id}/delete/", self.maker, {}), "购买订单")
        self.assertEqual(Purchase.objects.filter(
            listing_id=listing_id).count(), 1)


# ===========================================================================
# 7. Webhook 与事件
# ===========================================================================


class WebhookEventTests(MarketplaceBase):
    """订阅创建（密钥一次）、模拟投递成功/失败、事件与投递记录。"""

    def test_webhook_delivery_and_events(self):
        publisher_id, listing_id = self.bootstrap_listing()
        sub = self.assert_ok(self.post("/webhooks/", self.maker, {
            "publisher_id": publisher_id,
            "url": "https://hooks.example.com/marketplace",
            "events": ["*"],
        }))
        sub_id = sub["id"]
        self.assertTrue(sub["secret"])
        # 详情不回显密钥
        detail = self.assert_ok(self.get(f"/webhooks/{sub_id}/", self.maker))
        self.assertNotIn("secret", detail)

        tested = self.assert_ok(self.post(
            f"/webhooks/{sub_id}/test/", self.maker, {}))
        self.assertTrue(tested["success"])
        self.assertEqual(tested["status"], 200)

        # URL 含 fail 时模拟 500，便于验证失败分支
        failing = self.assert_ok(self.post("/webhooks/", self.maker, {
            "publisher_id": publisher_id,
            "url": "https://fail.example.com/hook",
            "events": ["install.created"],
        }))
        failed_test = self.assert_ok(self.post(
            f"/webhooks/{failing['id']}/test/", self.maker, {}))
        self.assertFalse(failed_test["success"])
        self.assertEqual(failed_test["status"], 500)

        # 触发安装事件：买家安装 → 事件属于买家，投递写到发布者订阅
        self.assert_ok(self.post("/installs/", self.buyer, {
            "listing_id": listing_id, "idempotency_key": "install-once"}))
        deliveries = self.assert_ok(self.get(
            f"/webhooks/{sub_id}/deliveries/", self.maker))
        self.assertGreaterEqual(deliveries["count"], 1)
        self.assertEqual(deliveries["items"][0]["event_type"], "install.created")
        success_only = self.assert_ok(self.get(
            f"/webhooks/{sub_id}/deliveries/", self.maker, {"status": "success"}))
        self.assertGreaterEqual(success_only["count"], 1)

        # 幂等键重复安装不重复投递
        self.assert_ok(self.post("/installs/", self.buyer, {
            "listing_id": listing_id, "idempotency_key": "install-once"}))
        events = self.assert_ok(self.get("/events/", self.buyer))
        self.assertEqual(events["count"], 1)
        event_id = events["items"][0]["id"]
        self.assert_ok(self.get(f"/events/{event_id}/", self.buyer))
        self.assert_fail(self.get(f"/events/{event_id}/", self.other), "无权")
        event = MarketplaceEvent.objects.get(pk=event_id)
        # 含 fail 的订阅会让该事件标记为部分失败，但成功订阅的投递仍保留
        self.assertEqual(event.status, "failed")
        self.assertIn("Webhook", event.error)

        # 非所有者不能建订阅、非法事件被拒
        self.assert_fail(self.post("/webhooks/", self.buyer, {
            "publisher_id": publisher_id, "url": "https://x.example.com",
            "events": ["*"]}), "无权")
        self.assert_fail(self.post("/webhooks/", self.maker, {
            "publisher_id": publisher_id, "url": "ftp://bad",
            "events": ["*"]}), "http")
        self.assert_fail(self.post("/webhooks/", self.maker, {
            "publisher_id": publisher_id, "url": "https://ok.example.com",
            "events": ["nothing.happened"]}), "不支持的事件")
        deleted = self.assert_ok(self.post(
            f"/webhooks/{failing['id']}/delete/", self.maker, {}))
        self.assertTrue(deleted["deleted"])


# ===========================================================================
# 8. 合集与举报
# ===========================================================================


class CollectionReportTests(MarketplaceBase):
    """合集发布/排序/去重与举报状态机。"""

    def test_collection_publish_and_reorder(self):
        publisher_id = self.make_publisher()
        self.verify_publisher(publisher_id)
        first = self.make_listing(publisher_id, name="应用甲", code="app-a")
        second = self.make_listing(publisher_id, name="应用乙", code="app-b")
        self.make_version(first, "1.0.0")
        self.make_version(second, "1.0.0")
        self.publish_listing(first)
        self.publish_listing(second)

        collection = self.assert_ok(self.post("/collections/", self.maker, {
            "title": "效率精选", "slug": "efficiency-picks",
            "description": "值得一试"}))
        collection_id = collection["id"]
        self.assert_fail(self.post("/collections/", self.maker, {
            "title": "重复", "slug": "efficiency-picks"}), "已被占用")

        added = self.assert_ok(self.post(
            f"/collections/{collection_id}/items/", self.maker,
            {"listing_id": first}))
        self.assertTrue(added["created"])
        again = self.assert_ok(self.post(
            f"/collections/{collection_id}/items/", self.maker,
            {"listing_id": first}))
        self.assertFalse(again["created"])
        self.assert_ok(self.post(
            f"/collections/{collection_id}/items/", self.maker,
            {"listing_id": second}))

        # 草稿合集对他人不可见
        self.assert_fail(self.get(
            f"/collections/{collection_id}/", self.buyer), "未发布")
        published = self.assert_ok(self.post(
            f"/collections/{collection_id}/publish/", self.maker, {}))
        self.assertEqual(published["items"], 2)
        public = self.assert_ok(self.get("/collections/public/", self.buyer))
        self.assertEqual(public["count"], 1)
        self.assert_fail(self.post(
            f"/collections/{collection_id}/publish/", self.maker, {}), "已发布")

        detail = self.assert_ok(self.get(
            f"/collections/{collection_id}/", self.buyer))
        item_ids = [item["id"] for item in detail["items"]]
        reordered = self.assert_ok(self.post(
            f"/collections/{collection_id}/items/reorder/", self.maker,
            {"items": list(reversed(item_ids)) + item_ids[:1]}))
        self.assertEqual(reordered["items"][0], item_ids[-1])
        self.assert_fail(self.post(
            f"/collections/{collection_id}/items/reorder/", self.maker,
            {"items": [999999]}), "不包含")
        removed = self.assert_ok(self.post(
            f"/collection-items/{item_ids[0]}/delete/", self.maker, {}))
        self.assertTrue(removed["deleted"])
        self.assert_fail(self.post(
            f"/collections/{collection_id}/publish/", self.maker, {}), "已发布")

    def test_report_state_machine(self):
        publisher_id, listing_id = self.bootstrap_listing()
        report = self.assert_ok(self.post("/reports/", self.buyer, {
            "listing_id": listing_id, "reason": "broken",
            "detail": "打开后闪退"}))
        report_id = report["id"]
        self.assertEqual(report["status"], "pending")
        # 同一用户重复举报被拦
        self.assert_fail(self.post("/reports/", self.buyer, {
            "listing_id": listing_id, "reason": "spam"}), "已举报")
        # 不能举报自己的应用
        self.assert_fail(self.post("/reports/", self.maker, {
            "listing_id": listing_id, "reason": "spam"}), "自己")
        # 枚举与权限
        self.assert_fail(self.post("/reports/", self.other, {
            "listing_id": listing_id, "reason": "nonsense"}), "reason")
        self.assert_fail(self.post(
            f"/reports/{report_id}/handle/", self.buyer,
            {"action": "review"}), "仅管理员")

        reviewed = self.assert_ok(self.post(
            f"/reports/{report_id}/handle/", self.admin, {"action": "review"}))
        self.assertEqual(reviewed["status"], "reviewing")
        self.assert_fail(self.post(
            f"/reports/{report_id}/handle/", self.admin,
            {"action": "resolve"}), "处理结论")
        resolved = self.assert_ok(self.post(
            f"/reports/{report_id}/handle/", self.admin,
            {"action": "resolve", "resolution": "已联系开发者修复"}))
        self.assertEqual(resolved["status"], "resolved")
        self.assert_fail(self.post(
            f"/reports/{report_id}/handle/", self.admin,
            {"action": "dismiss"}), "不能流转")

        detail = self.assert_ok(self.get(f"/reports/{report_id}/", self.admin))
        self.assertEqual(detail["transitions"], [])
        listing_data = self.assert_ok(self.get(
            f"/reports/", self.admin))
        self.assertEqual(listing_data["summary"]["total"], 1)
        self.assertEqual(listing_data["summary"]["by_status"]["resolved"], 1)


# ===========================================================================
# 9. 截图 / 兼容标签
# ===========================================================================


class ScreenshotCompatTests(MarketplaceBase):
    """截图元数据与兼容标签的校验、排序和删除。"""

    def test_screenshots_and_compat_tags(self):
        publisher_id, listing_id = self.bootstrap_listing()
        self.assert_fail(self.post(
            f"/listings/{listing_id}/screenshots/", self.maker,
            {"file_name": "a.txt", "file_url": "https://cdn.example.com/a.txt",
             "mime_type": "text/plain"}), "image/")
        shot = self.assert_ok(self.post(
            f"/listings/{listing_id}/screenshots/", self.maker, {
                "file_name": "home.png",
                "file_url": "https://cdn.example.com/home.png",
                "width": 1280, "height": 800, "caption": "首页"}))
        second = self.assert_ok(self.post(
            f"/listings/{listing_id}/screenshots/", self.maker, {
                "file_name": "stats.png",
                "file_url": "https://cdn.example.com/stats.png"}))
        listing_shots = self.assert_ok(self.get(
            f"/listings/{listing_id}/screenshots/", self.buyer))
        self.assertEqual(listing_shots["count"], 2)
        reordered = self.assert_ok(self.post(
            f"/listings/{listing_id}/screenshots/reorder/", self.maker,
            {"items": [second["id"], shot["id"]]}))
        self.assertEqual(reordered["reordered"], 2)
        updated = self.assert_ok(self.post(
            f"/screenshots/{shot['id']}/update/", self.maker,
            {"caption": "首页改版"}))
        self.assertEqual(updated["caption"], "首页改版")
        self.assert_ok(self.post(
            f"/screenshots/{second['id']}/delete/", self.maker, {}))

        self.assert_fail(self.post(
            f"/listings/{listing_id}/compatibility/", self.maker,
            {"platform_version": "3.2", "tag": "verified"}), "语义化版本")
        self.assert_fail(self.post(
            f"/listings/{listing_id}/compatibility/", self.maker,
            {"platform_version": "3.2.0", "tag": "unknown"}), "tag")
        compat = self.assert_ok(self.post(
            f"/listings/{listing_id}/compatibility/", self.maker,
            {"platform_version": "3.2.0", "tag": "verified",
             "note": "回归通过"}))
        self.assert_fail(self.post(
            f"/listings/{listing_id}/compatibility/", self.maker,
            {"platform_version": "3.2.0", "tag": "verified"}), "已存在")
        tags = self.assert_ok(self.get(
            f"/listings/{listing_id}/compatibility/", self.buyer,
            {"platform_version": "3.2.0"}))
        self.assertEqual(tags["count"], 1)
        self.assert_ok(self.post(
            f"/compatibility/{compat['id']}/delete/", self.maker, {}))


# ===========================================================================
# 10. 统计与目录
# ===========================================================================


class StatsCatalogTests(MarketplaceBase):
    """市场统计口径、管理员边界与目录端点数。"""

    def test_stats_and_catalog(self):
        publisher_id, listing_id = self.bootstrap_listing()
        self.assert_ok(self.post("/installs/", self.buyer, {
            "listing_id": listing_id}))

        catalog = self.assert_ok(self.get("/", self.buyer))
        self.assertEqual(len(catalog["domains"]), 9)
        self.assertEqual(catalog["pagination"]["page_size_max"], 200)
        self.assertEqual(len(catalog["endpoints"]), 101)

        overview = self.assert_ok(self.get("/stats/overview/", self.buyer))
        self.assertEqual(overview["published_listings"], 1)
        self.assertEqual(overview["active_installs"], 1)
        categories = self.assert_ok(self.get("/stats/categories/", self.buyer))
        self.assertIn("items", categories)
        publishers = self.assert_ok(self.get(
            "/stats/publishers/", self.buyer, {"limit": 5}))
        self.assertIn("items", publishers)
        installs = self.assert_ok(self.get(
            "/stats/installs/", self.buyer, {"days": 7, "mine": 1}))
        self.assertEqual(len(installs["items"]), 7)
        ratings = self.assert_ok(self.get("/stats/ratings/", self.buyer))
        self.assertIn("distribution", ratings["overall"])
        self.assert_ok(self.get("/stats/revenue/", self.admin))

        # 发布者暂停级联下架其应用
        suspended = self.assert_ok(self.post(
            f"/publishers/{publisher_id}/suspend/", self.admin,
            {"reason": "违规运营"}))
        self.assertEqual(suspended["count"], 1)
        listing = Listing.objects.get(pk=listing_id)
        self.assertEqual(listing.status, "suspended")
        self.assert_fail(self.post(
            f"/listings/{listing_id}/update/", self.maker, {"name": "x"}),
            "已被暂停")
        public = self.assert_ok(self.get("/listings/", self.buyer))
        self.assertEqual(public["count"], 0)


class SerializerIntegrityTests(MarketplaceBase):
    """落库字段与序列化一致性（权重/评分/安装计数）。"""

    def test_aggregate_and_counters_persist(self):
        publisher_id, listing_id = self.bootstrap_listing()
        listing = Listing.objects.get(pk=listing_id)
        self.assertIsNotNone(listing.latest_version)
        self.assertEqual(listing.latest_version.version, "1.0.0")

        self.assert_ok(self.post("/installs/", self.buyer, {
            "listing_id": listing_id}))
        listing.refresh_from_db()
        self.assertEqual(listing.install_count, 1)
        self.assertEqual(Install.objects.filter(
            listing_id=listing_id, status="installed").count(), 1)

        review = self.assert_ok(self.post(
            f"/listings/{listing_id}/reviews/", self.buyer, {"rating": 4}))
        self.assert_ok(self.post(
            f"/reviews/{review['id']}/publish/", self.maker, {}))
        listing.refresh_from_db()
        self.assertEqual(listing.rating_count, 1)
        self.assertEqual(float(listing.rating), 4.0)
        self.assertTrue(Review.objects.filter(
            listing_id=listing_id, status="published").exists())

        summary = self.assert_ok(self.get(
            f"/listings/{listing_id}/rating/", self.buyer))
        self.assertEqual(summary["distribution"]["4"], 1)
        self.assertEqual(summary["listing"]["rating_count"], 1)

        # 合集条目与 Collection 计数一致
        collection = self.assert_ok(self.post("/collections/", self.other, {
            "title": "我的收藏", "slug": "my-fav"}))
        self.assert_ok(self.post(
            f"/collections/{collection['id']}/items/", self.other,
            {"listing_id": listing_id}))
        self.assertEqual(Collection.objects.get(
            pk=collection["id"]).mp_items.count(), 1)

        # 许可证有效期字段与状态
        self.assert_ok(self.post(
            f"/listings/{listing_id}/pricing/", self.maker,
            {"mode": "paid", "price": "1.00"}))
        bought = self.assert_ok(self.post("/purchases/", self.other, {
            "listing_id": listing_id, "max_activations": 2}))
        license_obj = License.objects.get(pk=bought["license"]["id"])
        self.assertEqual(license_obj.status, "active")
        self.assertIsNone(license_obj.expires_at)
        self.assertEqual(license_obj.max_activations, 2)
        self.assertLessEqual(
            license_obj.created_at, timezone.now() + timedelta(seconds=1))
        deliveries = WebhookDelivery.objects.count()
        self.assertEqual(deliveries, 0)
