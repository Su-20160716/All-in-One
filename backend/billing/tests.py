# -*- coding: utf-8 -*-
"""billing 测试：目录、商品目录、客户/订阅生命周期、用量、账单/收款、
优惠券、催收、税率、统计指标与行级权限隔离。

运行：venv/Scripts/python.exe manage.py test billing -v 1
（测试库为内存 sqlite，不触碰开发库，也不会发起任何网络请求；支付全部为
状态模拟，网关流水号仅本地生成。）

注意：backend/code 包会遮蔽标准库 code，导致 manage.py test 的 pdb 导入失败；
因此测试统一用「独立脚本注入标准库 code 后再调用 Django 测试命令」的方式运行，
与 rules 应用保持一致。
"""
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from billing import services
from billing.models import (
    Coupon,
    Customer,
    Invoice,
    Plan,
    Subscription,
    TaxRate,
    UsageRecord,
)

User = get_user_model()

BASE = "/api/billing/"


def ensure_billing_tables():
    """测试库补建 billing 表。

    本应用不提交迁移文件（迁移统一生成是独立任务），但空的 migrations 包
    会让 Django 认为该应用「已迁移但无迁移」，测试库不会 sync 建表。
    这里只对测试库做一次幂等补建，不影响开发库/生产库的迁移策略。
    """
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in apps.get_app_config("billing").get_models():
            if model._meta.db_table not in existing:
                editor.create_model(model)


class BillingApiBase(TestCase):
    """接口测试基类：三个账号（普通/另一个普通/管理员）+ 通用断言。"""

    @classmethod
    def setUpClass(cls):
        # 必须在 TestCase 开启类级事务之前建表：SQLite 不允许在事务中关闭外键检查
        ensure_billing_tables()
        super().setUpClass()

    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", password="pass1234", nickname="爱丽丝")
        self.other = User.objects.create_user(
            username="bob", password="pass1234", nickname="鲍勃")
        self.admin = User.objects.create_user(
            username="root", password="pass1234", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    # ---- 请求 helper ----

    def get(self, path, params=None):
        return self.client.get(BASE + path, params or {})

    def post(self, path, data=None):
        return self.client.post(BASE + path, data if data is not None else {},
                                format="json")

    def as_user(self, user):
        self.client.force_authenticate(user)

    # ---- 断言 helper ----

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def bad(self, response, status=400):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertFalse(body.get("ok"), body)
        return body

    def assert_page(self, data):
        """列表契约：恰好 items/count/page/page_size 四个键。"""
        self.assertEqual(set(data.keys()), {"items", "count", "page", "page_size"})
        self.assertIsInstance(data["items"], list)

    # ---- 数据 helper ----

    def create_plan(self, code="pro", amount="100.00", billing_period="monthly",
                    trial_days=0, publish=True, **overrides):
        payload = {"code": code, "name": f"计划-{code}",
                   "billing_period": billing_period, "trial_days": trial_days}
        payload.update(overrides)
        plan = self.ok(self.post("plans/create/", payload))
        price = self.ok(self.post("prices/create/", {
            "plan_id": plan["id"], "amount": amount, "billing_mode": "flat"}))
        if publish:
            plan = self.ok(self.post(f"plans/{plan['id']}/publish/"))
        return plan, price

    def create_customer(self, name="ACME", **overrides):
        payload = {"name": name, "email": "billing@acme.test"}
        payload.update(overrides)
        return self.ok(self.post("customers/create/", payload))

    def create_subscription(self, plan_id, customer_id, **overrides):
        payload = {"plan_id": plan_id, "customer_id": customer_id, "seats": 1}
        payload.update(overrides)
        return self.ok(self.post("subscriptions/create/", payload))

    def create_meter(self, code="api_calls", **overrides):
        payload = {"code": code, "name": f"计量-{code}", "unit": "次"}
        payload.update(overrides)
        return self.ok(self.post("meters/create/", payload))

    def make_invoice(self, customer_id, amount="100.00", **overrides):
        payload = {
            "customer_id": customer_id,
            "lines": [{"line_type": "subscription", "description": "测试服务费",
                       "quantity": "1", "unit_amount": amount, "amount": amount}],
        }
        payload.update(overrides)
        return self.ok(self.post("invoices/create/", payload))

    def make_paid_bundle(self):
        """标准套餐：已发布月付计划 + 客户 + 生效订阅。"""
        plan, price = self.create_plan()
        customer = self.create_customer()
        subscription = self.create_subscription(plan["id"], customer["id"])
        return plan, price, customer, subscription


class CatalogTests(BillingApiBase):
    """目录与路由：枚举、分页契约、接口清单。"""

    def test_catalog(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "billing")
        self.assertEqual(data["version"], "1.0")
        self.assertIn("subscription_status", data["enums"])
        self.assertEqual(data["pagination"]["page_size_max"], 200)
        self.assertEqual(data["money"]["quantize"], "ROUND_HALF_UP")
        self.assertGreaterEqual(len(data["capabilities"]), 10)
        # 目录 1 个端点被排除，其余 105 个全部进入端点数
        self.assertEqual(data["endpoint_count"], 105)
        paths = {row["path"] for row in data["endpoints"]}
        self.assertIn("plans/", paths)
        self.assertIn("stats/mrr/", paths)
        methods = {row["path"]: row["methods"] for row in data["endpoints"]}
        self.assertEqual(methods["plans/"], ["GET"])

    def test_route_count(self):
        from billing.urls import urlpatterns

        self.assertEqual(len(urlpatterns), 106)


class PlanCatalogTests(BillingApiBase):
    """计划/价格/功能项/计划功能：发布、克隆、停用与唯一约束。"""

    def test_plan_price_publish_clone_archive(self):
        plan, price = self.create_plan(code="starter")
        self.assertEqual(plan["status"], "active")
        self.assertEqual(price["amount"], "100.0000")

        detail = self.ok(self.get(f"plans/{plan['id']}/"))
        self.assertEqual(detail["code"], "starter")
        self.assertEqual(len(detail["prices"]), 1)
        self.assertIn("events", detail)

        listed = self.ok(self.get("plans/", {"q": "starter"}))
        self.assert_page(listed)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["id"], plan["id"])

        clone = self.ok(self.post(f"plans/{plan['id']}/clone/", {"code": "starter_copy"}))
        self.assertEqual(clone["status"], "draft")
        self.assertEqual(len(clone["prices"]), 1)

        # 未发布计划不能开通订阅（避免测试价被误开）
        customer = self.create_customer()
        self.bad(self.post("subscriptions/create/", {
            "plan_id": clone["id"], "customer_id": customer["id"]}))

        # 克隆副本没有订阅，可以删除；原计划已有订阅后不能删除
        deleted = self.ok(self.post(f"plans/{clone['id']}/delete/"))
        self.assertTrue(deleted["deleted"])

        archived = self.ok(self.post(f"plans/{plan['id']}/archive/"))
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["prices"][0]["status"], "archived")

        # 缺价发布与编码非法都必须是 400
        bare = self.ok(self.post("plans/create/", {"code": "bare", "name": "空计划"}))
        self.bad(self.post(f"plans/{bare['id']}/publish/"))
        self.bad(self.post("plans/create/", {"code": "中文编码", "name": "坏编码"}))

    def test_price_window_and_resolve(self):
        plan = self.ok(self.post("plans/create/", {"code": "svc", "name": "服务"}))
        self.ok(self.post("prices/create/", {
            "plan_id": plan["id"], "amount": "10", "billing_mode": "per_unit"}))
        # 同计划同币种同生效日（None）重复必须被拒绝
        self.bad(self.post("prices/create/", {
            "plan_id": plan["id"], "amount": "20", "billing_mode": "per_unit"}))
        resolved = self.ok(self.get("prices/resolve/", {"plan_id": plan["id"]}))
        self.assertEqual(resolved["price"]["amount"], "10.0000")
        self.assertTrue(resolved["resolved"])
        listed = self.ok(self.get("prices/", {"plan_id": plan["id"]}))
        self.assert_page(listed)
        self.assertEqual(listed["count"], 1)

    def test_feature_and_plan_feature(self):
        plan, _price = self.create_plan(code="team")
        feature = self.ok(self.post("features/create/", {
            "code": "api_calls", "name": "API 调用", "feature_type": "quota",
            "unit": "次"}))
        binding = self.ok(self.post("plan-features/create/", {
            "plan_id": plan["id"], "feature_id": feature["id"],
            "included_qty": "100", "unit": "次", "overage_unit_amount": "0.5"}))
        self.assertEqual(binding["included_qty"], "100.0000")

        features = self.ok(self.get(f"plans/{plan['id']}/features/"))
        self.assertEqual(features["plan_id"], plan["id"])
        self.assertEqual(features["count"], 1)

        bound = self.ok(self.get("plan-features/", {"plan_id": plan["id"]}))
        self.assert_page(bound)
        self.assertEqual(bound["items"][0]["feature_code"], "api_calls")

        updated = self.ok(self.post(f"plan-features/{binding['id']}/update/", {
            "included_qty": "200"}))
        self.assertEqual(updated["included_qty"], "200.0000")

        deleted = self.ok(self.post(f"plan-features/{binding['id']}/delete/"))
        self.assertTrue(deleted["deleted"])
        removed = self.ok(self.post(f"features/{feature['id']}/delete/"))
        self.assertTrue(removed["deleted"])


class CustomerTests(BillingApiBase):
    """客户：唯一性、更新、概览与删除保护。"""

    def test_customer_crud_and_overview(self):
        customer = self.create_customer(name="星河科技", credit_limit="5000")
        self.assertEqual(customer["credit_available"], "5000.00")
        self.bad(self.post("customers/create/", {"name": "星河科技"}))
        self.bad(self.post("customers/create/", {
            "name": "坏邮箱", "email": "not-an-email"}))

        updated = self.ok(self.post(f"customers/{customer['id']}/update/", {
            "region": "上海", "balance": "88.50"}))
        self.assertEqual(updated["balance"], "88.50")
        self.assertEqual(updated["region"], "上海")

        overview = self.ok(self.get(f"customers/{customer['id']}/overview/"))
        self.assertEqual(overview["customer_id"], customer["id"])
        self.assertEqual(overview["balance"], "88.50")
        self.assertEqual(overview["subscription_count"], 0)
        self.assertGreaterEqual(len(overview["events"]), 1)

        listed = self.ok(self.get("customers/", {"q": "星河"}))
        self.assert_page(listed)
        self.assertEqual(listed["count"], 1)

        plan, _price = self.create_plan(code="keep")
        self.create_subscription(plan["id"], customer["id"])
        self.bad(self.post(f"customers/{customer['id']}/delete/"))

        lone = self.create_customer(name="单体客户")
        deleted = self.ok(self.post(f"customers/{lone['id']}/delete/"))
        self.assertTrue(deleted["deleted"])

    def test_subscription_items(self):
        plan, _price = self.create_plan(code="addon")
        customer = self.create_customer()
        subscription = self.create_subscription(plan["id"], customer["id"])
        extra = self.ok(self.post("prices/create/", {
            "plan_id": plan["id"], "amount": "30", "billing_mode": "flat",
            "effective_from": services.today().isoformat(), "nickname": "加购包"}))
        item = self.ok(self.post("subscriptions/items/add/", {
            "id": subscription["id"], "price_id": extra["id"], "quantity": "2"}))
        self.assertEqual(item["quantity"], "2.0000")

        items = self.ok(self.get(f"subscriptions/{subscription['id']}/items/"))
        self.assert_page(items)
        self.assertEqual(items["count"], 2)

        removed = self.ok(self.post("subscriptions/items/remove/", {
            "id": subscription["id"], "item_id": item["id"]}))
        self.assertIsNotNone(removed["effective_to"])
        # 只剩一条明细时不允许再移除
        single = self.create_subscription(plan["id"], customer["id"], seats=2)
        only = self.ok(self.get(f"subscriptions/{single['id']}/items/"))
        self.bad(self.post("subscriptions/items/remove/", {
            "id": single["id"], "item_id": only["items"][0]["id"]}))


class SubscriptionLifecycleTests(BillingApiBase):
    """订阅生命周期：开通、暂停/恢复、取消、续期、删除与试用转正。"""

    def test_active_subscription_lifecycle(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        self.assertEqual(subscription["status"], "active")
        self.assertEqual(subscription["period_amount"], "100.00")

        detail = self.ok(self.get(f"subscriptions/{subscription['id']}/"))
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(detail["customer_name"], customer["name"])

        paused = self.ok(self.post(f"subscriptions/{subscription['id']}/pause/"))
        self.assertEqual(paused["status"], "paused")
        resumed = self.ok(self.post(f"subscriptions/{subscription['id']}/resume/"))
        self.assertEqual(resumed["status"], "active")

        updated = self.ok(self.post(f"subscriptions/{subscription['id']}/update/",
                                    {"seats": 3, "auto_renew": False}))
        self.assertEqual(updated["seats"], 3)
        self.assertFalse(updated["auto_renew"])

        renewed = self.ok(self.post(f"subscriptions/{subscription['id']}/renew/"))
        self.assertTrue(renewed["renewed"])
        self.assertIsNotNone(renewed["invoice"])
        self.assertEqual(renewed["invoice"]["status"], "draft")

        canceled = self.ok(self.post(f"subscriptions/{subscription['id']}/cancel/",
                                     {"reason": "项目结束"}))
        self.assertTrue(canceled["cancel_at_period_end"])
        self.assertNotEqual(canceled["status"], "canceled")

        # 期末取消后再次续费才真正失效，且不再开票
        ended = self.ok(self.post(f"subscriptions/{subscription['id']}/renew/"))
        self.assertFalse(ended["renewed"])
        self.assertEqual(ended["subscription"]["status"], "canceled")

        # 有账单的订阅不能删除
        self.bad(self.post(f"subscriptions/{subscription['id']}/delete/"))

    def test_cancel_now_and_delete_clean(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        canceled = self.ok(self.post(f"subscriptions/{subscription['id']}/cancel-now/",
                                     {"reason": "立即停"}))
        self.assertEqual(canceled["status"], "canceled")
        deleted = self.ok(self.post(f"subscriptions/{subscription['id']}/delete/"))
        self.assertTrue(deleted["deleted"])
        self.assertEqual(Subscription.objects.count(), 0)

    def test_trial_conversion(self):
        plan, _price = self.create_plan(code="trial", amount="50", trial_days=14)
        customer = self.create_customer()
        subscription = self.create_subscription(plan["id"], customer["id"])
        self.assertEqual(subscription["status"], "trialing")
        self.assertTrue(subscription["in_trial"])

        result = self.ok(self.post(f"subscriptions/{subscription['id']}/trial-convert/"))
        self.assertTrue(result["changed"])
        self.assertEqual(result["subscription"]["status"], "active")
        self.assertIsNotNone(result["invoice"])
        self.assertEqual(result["invoice"]["total"], "50.00")

        # 已转正再调用必须失败（幂等入口用错误提示，避免重复开票）
        self.bad(self.post(f"subscriptions/{subscription['id']}/trial-convert/"))

    def test_plan_change_with_proration(self):
        cheap, _cprice = self.create_plan(code="basic", amount="100")
        expensive, _eprice = self.create_plan(code="premium", amount="300")
        customer = self.create_customer()
        subscription = self.create_subscription(cheap["id"], customer["id"])

        preview = self.ok(self.post(
            f"subscriptions/{subscription['id']}/change-preview/",
            {"new_plan_id": expensive["id"]}))
        self.assertTrue(preview["upgrade"])
        self.assertEqual(preview["new_period_amount"], "300.00")
        self.assertEqual(preview["old_period_amount"], "100.00")
        self.assertGreater(Decimal(preview["net"]), Decimal("0"))

        changed = self.ok(self.post(f"subscriptions/{subscription['id']}/change-plan/", {
            "new_plan_id": expensive["id"], "reason": "升级"}))
        self.assertEqual(changed["subscription"]["plan_id"], expensive["id"])
        self.assertIsNotNone(changed["invoice"])
        self.assertEqual(changed["invoice"]["status"], "open")
        self.assertGreater(Decimal(changed["invoice"]["total"]), Decimal("0"))

        same = self.bad(self.post(f"subscriptions/{subscription['id']}/change-plan/",
                                  {"new_plan_id": expensive["id"]}))
        self.assertIn("相同", same["error"])


class UsageTests(BillingApiBase):
    """用量：幂等上报、批量、列表过滤、汇总与包含额度计费。"""

    def test_usage_report_and_summary(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        meter = self.create_meter()
        first = self.ok(self.post("usage/report/", {
            "subscription_id": subscription["id"], "meter_code": meter["code"],
            "quantity": "10", "idempotency_key": "evt-1"}))
        self.assertTrue(first["created"])
        self.assertEqual(first["quantity"], "10.0000")

        replay = self.ok(self.post("usage/report/", {
            "subscription_id": subscription["id"], "meter_code": meter["code"],
            "quantity": "10", "idempotency_key": "evt-1"}))
        self.assertFalse(replay["created"])
        self.assertEqual(replay["id"], first["id"])

        batch = self.ok(self.post("usage/batch/", {
            "subscription_id": subscription["id"],
            "rows": [
                {"meter_code": meter["code"], "quantity": "2", "idempotency_key": "evt-2"},
                {"meter_code": meter["code"], "quantity": "3", "idempotency_key": "evt-3"},
                {"meter_code": meter["code"], "quantity": "3", "idempotency_key": "evt-3"},
            ]}))
        self.assertEqual(batch["count"], 3)
        self.assertEqual(batch["created"], 2)

        listed = self.ok(self.get("usage/", {"subscription_id": subscription["id"],
                                             "meter_id": meter["id"]}))
        self.assert_page(listed)
        self.assertEqual(listed["count"], 3)
        self.assertTrue(all(row["invoiced"] is False for row in listed["items"]))

        summary = self.ok(self.get("usage/summary/", {
            "subscription_id": subscription["id"]}))
        self.assertEqual(summary["meter_count"], 1)
        self.assertEqual(summary["total_quantity"], "15.0000")
        # 没有绑定功能额度时，全部用量按 0 元计（计划未配置该计量项）
        self.assertEqual(summary["total_amount"], "0.00")

        # 未来时间戳是接入方常见错误，必须拒绝
        future = (services.now() + timedelta(hours=2)).isoformat()
        self.bad(self.post("usage/report/", {
            "subscription_id": subscription["id"], "meter_code": meter["code"],
            "quantity": "1", "occurred_at": future}))

    def test_usage_overage_billed_on_invoice(self):
        plan, _price = self.create_plan(code="metered", amount="100")
        feature = self.ok(self.post("features/create/", {
            "code": "api_calls", "name": "API 调用", "feature_type": "quota"}))
        self.ok(self.post("plan-features/create/", {
            "plan_id": plan["id"], "feature_id": feature["id"],
            "included_qty": "100", "overage_unit_amount": "0.5"}))
        customer = self.create_customer()
        subscription = self.create_subscription(plan["id"], customer["id"])
        meter = self.create_meter()
        self.ok(self.post("usage/report/", {
            "subscription_id": subscription["id"], "meter_code": meter["code"],
            "quantity": "150"}))

        invoice = self.ok(self.post("invoices/generate/", {
            "subscription_id": subscription["id"]}))
        usage_lines = [row for row in invoice["lines"] if row["line_type"] == "usage"]
        self.assertEqual(len(usage_lines), 1)
        self.assertEqual(usage_lines[0]["amount"], "25.00")
        self.assertEqual(invoice["total"], "125.00")

        # 用量已被发票占用，不能重复计入
        record = UsageRecord.objects.get()
        self.assertTrue(record.invoiced)
        self.assertEqual(record.invoice_id, invoice["id"])

    def test_meter_crud(self):
        meter = self.create_meter(code="seats", aggregation="max", reset_period="none")
        self.assertEqual(meter["aggregation"], "max")
        updated = self.ok(self.post(f"meters/{meter['id']}/update/", {
            "name": "席位数", "status": "archived"}))
        self.assertEqual(updated["name"], "席位数")
        deleted = self.ok(self.post(f"meters/{meter['id']}/delete/"))
        self.assertTrue(deleted["deleted"])


class InvoiceTests(BillingApiBase):
    """账单：生成幂等、税费、发送、收款、退款、信用票据、作废与 PDF。"""

    def test_invoice_full_flow(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        self.ok(self.post("tax-rates/create/", {
            "country": "CN", "name": "增值税", "rate": "10", "is_default": True}))

        invoice = self.ok(self.post("invoices/generate/", {
            "subscription_id": subscription["id"]}))
        self.assertEqual(invoice["status"], "draft")
        self.assertEqual(invoice["subtotal"], "100.00")
        self.assertEqual(invoice["tax_total"], "10.00")
        self.assertEqual(invoice["total"], "110.00")
        self.assertTrue(invoice["number"].startswith("INV-"))

        # 同周期重复生成必须被拒绝（幂等保护）
        self.bad(self.post("invoices/generate/", {
            "subscription_id": subscription["id"]}))

        sent = self.ok(self.post(f"invoices/{invoice['id']}/send/"))
        self.assertEqual(sent["status"], "open")
        self.assertIsNotNone(sent["sent_at"])
        # 重复发送幂等
        again = self.ok(self.post(f"invoices/{invoice['id']}/send/"))
        self.assertEqual(again["id"], invoice["id"])

        pdf = self.ok(self.get(f"invoices/{invoice['id']}/pdf/"))
        self.assertEqual(pdf["invoice_number"], invoice["number"])
        self.assertEqual(pdf["totals"]["total"], "110.00")
        self.assertTrue(pdf["lines"])

        partial = self.ok(self.post("payments/create/", {
            "invoice_id": invoice["id"], "amount": "60", "method": "card"}))
        self.assertEqual(partial["status"], "succeeded")
        self.assertEqual(partial["amount"], "60.00")

        settled = self.ok(self.post(f"invoices/{invoice['id']}/mark-paid/", {
            "method": "manual"}))
        self.assertEqual(settled["invoice"]["status"], "paid")
        self.assertEqual(settled["payment"]["amount"], "50.00")

        refunded = self.ok(self.post(f"payments/{settled['payment']['id']}/refund/", {
            "amount": "20", "reason": "部分退款"}))
        self.assertEqual(refunded["invoice"]["status"], "open")
        self.assertEqual(refunded["invoice"]["amount_due"], "20.00")

        note = self.ok(self.post("credit-notes/create/", {
            "customer_id": customer["id"], "invoice_id": invoice["id"],
            "amount": "20", "reason": "服务补偿"}))
        self.assertEqual(note["status"], "open")
        applied = self.ok(self.post(f"credit-notes/{note['id']}/apply/", {}))
        self.assertEqual(applied["credit_note"]["status"], "applied")
        refreshed = self.ok(self.get(f"invoices/{invoice['id']}/"))
        self.assertEqual(refreshed["credit_applied"], "20.00")
        self.assertEqual(refreshed["amount_due"], "0.00")
        self.assertEqual(refreshed["status"], "paid")

        listed = self.ok(self.get("payments/", {"invoice_id": invoice["id"]}))
        self.assert_page(listed)
        self.assertEqual(listed["count"], 2)

        notes = self.ok(self.get("credit-notes/", {"customer_id": customer["id"]}))
        self.assert_page(notes)
        self.assertEqual(notes["count"], 1)

    def test_manual_invoice_crud_and_overdue(self):
        customer = self.create_customer()
        invoice = self.make_invoice(customer["id"], amount="80")
        self.assertEqual(invoice["status"], "draft")
        self.assertEqual(invoice["total"], "80.00")

        recalc = self.ok(self.post(f"invoices/{invoice['id']}/recalc/"))
        self.assertEqual(recalc["total"], "80.00")

        updated = self.ok(self.post(f"invoices/{invoice['id']}/update/", {
            "notes": "改备注",
            "lines": [{"line_type": "subscription", "description": "调整后",
                       "quantity": "1", "unit_amount": "120", "amount": "120"}]}))
        self.assertEqual(updated["total"], "120.00")
        self.assertEqual(len(updated["lines"]), 1)

        self.ok(self.post(f"invoices/{invoice['id']}/send/"))
        # 已发送（非草稿）不能改行项，也不能删除
        self.bad(self.post(f"invoices/{invoice['id']}/update/", {"notes": "x"}))
        self.bad(self.post(f"invoices/{invoice['id']}/delete/"))

        voided = self.ok(self.post(f"invoices/{invoice['id']}/void/", {"reason": "重开"}))
        self.assertEqual(voided["status"], "void")
        deleted = self.ok(self.post(f"invoices/{invoice['id']}/delete/"))
        self.assertTrue(deleted["deleted"])

        past = (services.today() - timedelta(days=5)).isoformat()
        overdue = self.make_invoice(customer["id"], amount="40", due_date=past)
        self.ok(self.post(f"invoices/{overdue['id']}/send/"))
        scan = self.ok(self.post("invoices/overdue-scan/", {}))
        self.assertEqual(scan["count"], 1)
        self.assertEqual(scan["total_due"], "40.00")
        self.assertGreaterEqual(scan["items"][0]["days_overdue"], 5)

    def test_void_releases_usage(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        meter = self.create_meter()
        self.ok(self.post("usage/report/", {
            "subscription_id": subscription["id"], "meter_code": meter["code"],
            "quantity": "1"}))
        invoice = self.ok(self.post("invoices/generate/", {
            "subscription_id": subscription["id"]}))
        self.assertTrue(UsageRecord.objects.get().invoiced)
        self.ok(self.post(f"invoices/{invoice['id']}/void/", {"reason": "错开"}))
        self.assertFalse(UsageRecord.objects.get().invoiced)
        # 作废后同周期可以重新开票（用量重新占用）
        reopened = self.ok(self.post("invoices/generate/", {
            "subscription_id": subscription["id"]}))
        self.assertEqual(reopened["status"], "draft")


class PaymentTests(BillingApiBase):
    """支付：余额充值、信用支付、失败重试与退款边界。"""

    def test_topup_credit_payment_and_retry(self):
        customer = self.create_customer()
        topup = self.ok(self.post("payments/create/", {
            "customer_id": customer["id"], "amount": "200",
            "method": "bank_transfer"}))
        self.assertEqual(topup["status"], "succeeded")
        self.assertTrue(topup["invoice_id"] is None)
        refreshed = self.ok(self.get(f"customers/{customer['id']}/"))
        self.assertEqual(refreshed["balance"], "200.00")

        invoice = self.make_invoice(customer["id"], amount="120")
        self.ok(self.post(f"invoices/{invoice['id']}/send/"))
        paid = self.ok(self.post(f"invoices/{invoice['id']}/mark-paid/", {
            "method": "credit"}))
        self.assertEqual(paid["invoice"]["status"], "paid")
        # 余额支付后剩余 80
        refreshed = self.ok(self.get(f"customers/{customer['id']}/"))
        self.assertEqual(refreshed["balance"], "80.00")

        # 发票已结清，不能再次收款
        self.bad(self.post("payments/create/", {
            "invoice_id": invoice["id"], "amount": "1"}))

        # 未结清发票：pending → 重试成功；模拟失败 → 重试成功
        second = self.make_invoice(customer["id"], amount="30")
        self.ok(self.post(f"invoices/{second['id']}/send/"))
        pending = self.ok(self.post("payments/create/", {
            "invoice_id": second["id"], "amount": "30", "auto_capture": False}))
        self.assertEqual(pending["status"], "pending")
        retried = self.ok(self.post(f"payments/{pending['id']}/retry/", {}))
        self.assertEqual(retried["status"], "succeeded")
        self.assertEqual(retried["attempts"], 2)

        third = self.make_invoice(customer["id"], amount="25")
        self.ok(self.post(f"invoices/{third['id']}/send/"))
        failed = self.ok(self.post("payments/create/", {
            "invoice_id": third["id"], "amount": "25",
            "metadata": {"simulate_failure": True}}))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("模拟网关拒绝", failed["failure_reason"])
        recovered = self.ok(self.post(f"payments/{failed['id']}/retry/", {}))
        self.assertEqual(recovered["status"], "succeeded")

        refund = self.ok(self.post(f"payments/{recovered['id']}/refund/", {}))
        self.assertEqual(refund["payment"]["status"], "refunded")
        self.assertEqual(refund["invoice"]["status"], "open")
        self.bad(self.post(f"payments/{recovered['id']}/refund/", {}))


class CouponTests(BillingApiBase):
    """优惠券：校验、核销幂等、上限、客户限制与账单叠加。"""

    def test_coupon_validate_redeem(self):
        customer = self.create_customer()
        coupon = self.ok(self.post("coupons/create/", {
            "code": "SAVE10", "name": "九折", "coupon_type": "percent",
            "percent": "10", "duration": "once", "max_redemptions": 2}))
        self.assertEqual(coupon["percent"], "10.00")

        checked = self.ok(self.post("coupons/validate/", {
            "code": "SAVE10", "customer_id": customer["id"], "amount": "200"}))
        self.assertTrue(checked["valid"])
        self.assertEqual(checked["discount"], "20.00")

        first = self.ok(self.post("coupons/redeem/", {
            "code": "SAVE10", "customer_id": customer["id"], "amount": "200",
            "idempotency_key": "redeem-1"}))
        self.assertEqual(first["redeemed_count"], 1)
        again = self.ok(self.post("coupons/redeem/", {
            "code": "SAVE10", "customer_id": customer["id"], "amount": "200",
            "idempotency_key": "redeem-1"}))
        self.assertEqual(again["redemption"]["id"], first["redemption"]["id"])

        # 一次性券同一客户第二次直接失败
        self.bad(self.post("coupons/redeem/", {
            "code": "SAVE10", "customer_id": customer["id"], "amount": "200",
            "idempotency_key": "redeem-2"}))

        records = self.ok(self.get("coupons/redemptions/", {
            "coupon_id": coupon["id"]}))
        self.assert_page(records)
        self.assertEqual(records["count"], 1)
        self.bad(self.post(f"coupons/{coupon['id']}/delete/"))

        # 指定客户的券不能给其他客户用
        restricted = self.ok(self.post("coupons/create/", {
            "code": "ONLYME", "name": "专属", "coupon_type": "fixed",
            "amount": "50", "customer_id": customer["id"]}))
        self.assertEqual(restricted["coupon_type"], "fixed")
        other = self.create_customer(name="别家")
        self.bad(self.post("coupons/validate/", {
            "code": "ONLYME", "customer_id": other["id"], "amount": "100"}))

    def test_coupon_applied_to_invoice(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        self.ok(self.post("coupons/create/", {
            "code": "TENOFF", "name": "减十元", "coupon_type": "fixed",
            "amount": "10"}))
        invoice = self.ok(self.post("invoices/generate/", {
            "subscription_id": subscription["id"], "coupon_code": "TENOFF"}))
        self.assertEqual(invoice["discount_total"], "10.00")
        self.assertEqual(invoice["total"], "90.00")
        self.assertEqual(Coupon.objects.get(code="TENOFF").redeemed_count, 1)


class DunningTests(BillingApiBase):
    """催收：策略步骤、状态机推进、运行记录与批量扫描。"""

    def test_dunning_state_machine(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        policy = self.ok(self.post("dunning-policies/create/", {
            "code": "std", "name": "标准催收",
            "steps": [
                {"sequence": 1, "delay_days": 0, "action": "notify"},
                {"sequence": 2, "delay_days": 1, "action": "suspend"},
                {"sequence": 3, "delay_days": 2, "action": "cancel"},
            ]}))
        self.assertEqual(len(policy["steps"]), 3)

        run = self.ok(self.post("dunning/start/", {
            "subscription_id": subscription["id"], "policy_id": policy["id"],
            "reason": "账单逾期"}))
        self.assertEqual(run["status"], "running")
        self.assertEqual(
            Subscription.objects.get(pk=subscription["id"]).status, "past_due")

        # 同一订阅重复启动返回同一条运行记录（幂等）
        replay = self.ok(self.post("dunning/start/", {
            "subscription_id": subscription["id"], "policy_id": policy["id"]}))
        self.assertEqual(replay["id"], run["id"])

        first = self.ok(self.post("dunning/advance/", {
            "id": run["id"], "force": True}))
        self.assertTrue(first["executed"])
        self.assertEqual(first["action"], "notify")

        second = self.ok(self.post("dunning/advance/", {
            "id": run["id"], "force": True}))
        self.assertEqual(second["action"], "suspend")
        self.assertEqual(second["subscription_status"], "paused")

        third = self.ok(self.post("dunning/advance/", {
            "id": run["id"], "force": True}))
        self.assertEqual(third["action"], "cancel")
        self.assertEqual(third["subscription_status"], "canceled")
        self.assertEqual(third["run"]["status"], "completed")

        # 结束后再推进不重复执行
        done = self.ok(self.post("dunning/advance/", {
            "id": run["id"], "force": True}))
        self.assertFalse(done["executed"])

        runs = self.ok(self.get("dunning/runs/", {
            "subscription_id": subscription["id"]}))
        self.assert_page(runs)
        self.assertEqual(runs["count"], 1)
        detail = self.ok(self.get(f"dunning/runs/{run['id']}/"))
        self.assertEqual(len(detail["steps"]), 3)

        scan = self.ok(self.post("dunning/scan/", {}))
        self.assertEqual(scan["scanned"], 0)

        # 策略已有运行记录，删除被拒绝
        self.bad(self.post(f"dunning-policies/{policy['id']}/delete/"))

    def test_dunning_policy_validation(self):
        self.bad(self.post("dunning-policies/create/", {
            "code": "bad", "name": "坏策略", "steps": []}))
        self.bad(self.post("dunning-policies/create/", {
            "code": "bad", "name": "坏策略",
            "steps": [{"sequence": 1, "delay_days": 5, "action": "notify"},
                      {"sequence": 2, "delay_days": 1, "action": "cancel"}]}))
        self.bad(self.post("dunning-policies/create/", {
            "code": "bad", "name": "坏策略",
            "steps": [{"sequence": 1, "delay_days": 1, "action": "explode"}]}))
        good = self.ok(self.post("dunning-policies/create/", {
            "code": "good", "name": "好策略",
            "steps": [{"sequence": 1, "delay_days": 3, "action": "notify"}]}))
        updated = self.ok(self.post(
            f"dunning-policies/{good['id']}/update/",
            {"name": "好策略2", "steps": [
                {"sequence": 1, "delay_days": 0, "action": "notify"},
                {"sequence": 2, "delay_days": 7, "action": "cancel"}]}))
        self.assertEqual(updated["name"], "好策略2")
        self.assertEqual(len(updated["steps"]), 2)
        deleted = self.ok(self.post(f"dunning-policies/{good['id']}/delete/"))
        self.assertTrue(deleted["deleted"])


class TaxAndEventTests(BillingApiBase):
    """税率与事件：默认税率唯一、更新/删除与审计时间线。"""

    def test_tax_rate_crud_and_events(self):
        first = self.ok(self.post("tax-rates/create/", {
            "country": "CN", "region": "上海", "name": "增值税", "rate": "6",
            "is_default": True}))
        second = self.ok(self.post("tax-rates/create/", {
            "country": "CN", "name": "增值税-默认", "rate": "9", "is_default": True}))
        # 新默认税率应把旧默认标记清掉
        self.assertFalse(TaxRate.objects.get(pk=first["id"]).is_default)
        self.assertTrue(TaxRate.objects.get(pk=second["id"]).is_default)

        updated = self.ok(self.post(f"tax-rates/{second['id']}/update/", {
            "rate": "13", "enabled": False}))
        self.assertEqual(updated["rate"], "13.0000")
        self.assertFalse(updated["enabled"])

        listed = self.ok(self.get("tax-rates/", {"country": "CN"}))
        self.assert_page(listed)
        self.assertEqual(listed["count"], 2)

        self.ok(self.post(f"tax-rates/{first['id']}/delete/"))

        events = self.ok(self.get("events/", {"event_type": "tax_rate.created"}))
        self.assert_page(events)
        self.assertGreaterEqual(events["count"], 2)


class StatsTests(BillingApiBase):
    """统计：MRR/ARR/ARPU/流失/转化/逾期/趋势/分布/预测/总览。"""

    def test_metrics_after_paid_invoice(self):
        plan, _price, customer, subscription = self.make_paid_bundle()
        invoice = self.ok(self.post("invoices/generate/", {
            "subscription_id": subscription["id"]}))
        self.ok(self.post(f"invoices/{invoice['id']}/send/"))
        self.ok(self.post(f"invoices/{invoice['id']}/mark-paid/", {}))

        mrr = self.ok(self.get("stats/mrr/"))
        self.assertEqual(mrr["mrr"], "100.00")
        self.assertEqual(mrr["by_currency"]["CNY"], "100.00")
        self.assertEqual(mrr["subscription_count"], 1)

        arr = self.ok(self.get("stats/arr/"))
        self.assertEqual(arr["arr"], "1200.00")

        arpu = self.ok(self.get("stats/arpu/"))
        self.assertEqual(arpu["arpu"], "100.00")
        self.assertEqual(arpu["customer_count"], 1)

        churn = self.ok(self.get("stats/churn/", {"days": 30}))
        self.assertEqual(churn["churn_rate"], 0)
        self.assertEqual(churn["canceled"], 0)

        trial = self.ok(self.get("stats/trial-conversion/"))
        self.assertEqual(trial["trials_ended"], 0)

        delinquency = self.ok(self.get("stats/delinquency/"))
        self.assertEqual(delinquency["overdue"], "0.00")
        self.assertEqual(delinquency["overdue_invoices"], 0)

        trend = self.ok(self.get("stats/revenue-trend/", {"months": 6}))
        self.assertEqual(trend["months"], 6)
        self.assertEqual(trend["total"], "100.00")
        self.assertEqual(trend["count"], 6)

        distribution = self.ok(self.get("stats/plan-distribution/"))
        self.assertEqual(distribution["count"], 1)
        self.assertEqual(distribution["items"][0]["mrr"], "100.00")
        self.assertEqual(distribution["items"][0]["share"], 100.0)

        forecast = self.ok(self.get("stats/forecast/"))
        self.assertEqual(forecast["horizon_days"], 30)
        self.assertEqual(forecast["total"], "100.00")
        self.assertEqual(forecast["items"][0]["forecast"], "100.00")

        overview = self.ok(self.get("stats/overview/"))
        self.assertEqual(overview["customers"], 1)
        self.assertEqual(overview["subscriptions"], 1)
        self.assertEqual(overview["mrr"], "100.00")
        self.assertEqual(overview["arr"], "1200.00")
        self.assertEqual(overview["invoices_by_status"].get("paid"), 1)

    def test_delinquency_and_trial_metrics(self):
        plan, _price = self.create_plan(code="trial2", trial_days=7)
        customer = self.create_customer()
        trial = self.create_subscription(plan["id"], customer["id"])
        self.ok(self.post(f"subscriptions/{trial['id']}/trial-convert/"))

        past = (services.today() - timedelta(days=10)).isoformat()
        invoice = self.make_invoice(customer["id"], amount="50", due_date=past)
        self.ok(self.post(f"invoices/{invoice['id']}/send/"))

        stats = self.ok(self.get("stats/delinquency/"))
        self.assertEqual(stats["overdue"], "50.00")
        self.assertEqual(stats["delinquency_rate"], 100.0)

        converted = self.ok(self.get("stats/trial-conversion/"))
        self.assertEqual(converted["trials_ended"], 1)
        self.assertEqual(converted["converted"], 1)


class SecurityAndPagingTests(BillingApiBase):
    """行级权限与分页上限：普通用户互不可见，管理员可看全部。"""

    def test_scoping_isolation(self):
        customer = self.create_customer(name="Alice 客户")
        self.as_user(self.other)
        self.bad(self.get(f"customers/{customer['id']}/"))
        self.bad(self.post(f"customers/{customer['id']}/update/", {"region": "北京"}))
        listed = self.ok(self.get("customers/"))
        self.assertEqual(listed["count"], 0)

        self.as_user(self.admin)
        admin_list = self.ok(self.get("customers/"))
        self.assertEqual(admin_list["count"], 1)
        admin_detail = self.ok(self.get(f"customers/{customer['id']}/"))
        self.assertEqual(admin_detail["name"], "Alice 客户")

    def test_page_size_cap(self):
        package = self.make_paid_bundle()
        plan_id = package[0]["id"]
        customer_id = package[2]["id"]
        self.create_subscription(plan_id, customer_id, seats=2)

        capped = self.bad(self.get("subscriptions/", {"page_size": 500}))
        self.assertIn("page_size", capped["error"])
        page = self.ok(self.get("subscriptions/", {"page_size": 200, "page": 1}))
        self.assert_page(page)
        self.assertEqual(page["page_size"], 200)
        self.assertEqual(page["count"], 2)

        filtered = self.ok(self.get("subscriptions/", {"status": "active"}))
        self.assertEqual(filtered["count"], 2)
        missing = self.ok(self.get("subscriptions/", {"status": "canceled"}))
        self.assertEqual(missing["count"], 0)

    def test_invalid_enum_and_missing_fields(self):
        self.bad(self.post("plans/create/", {
            "code": "enum", "name": "枚举", "billing_period": "weekly"}))
        self.bad(self.post("plans/create/", {"name": "缺编码"}))
        self.bad(self.post("customers/create/", {"name": "客户", "status": "weird"}))
        self.bad(self.post("invoices/create/", {"customer_id": 999999}))

    def test_admin_write_and_event_timeline(self):
        plan, price, customer, subscription = self.make_paid_bundle()
        self.as_user(self.admin)
        detail = self.ok(self.get(f"subscriptions/{subscription['id']}/"))
        self.assertEqual(detail["plan_id"], plan["id"])
        updated = self.ok(self.post(f"plans/{plan['id']}/update/", {
            "description": "管理员改的描述"}))
        self.assertEqual(updated["description"], "管理员改的描述")

        events = self.ok(self.get("events/", {"object_type": "Plan",
                                              "object_id": plan["id"]}))
        self.assertGreaterEqual(events["count"], 2)
        self.assertEqual(events["items"][0]["object_type"], "Plan")

        # 计划已有订阅，不能删除
        self.bad(self.post(f"plans/{plan['id']}/delete/"))

    def test_service_money_helpers(self):
        """金额工具：Decimal 量化、按比例、安全除法与阶梯计算。"""
        self.assertEqual(services.quantize_money("1.005"), Decimal("1.01"))
        self.assertEqual(services.quantize_unit("1.00005"), Decimal("1.0001"))
        self.assertEqual(services.percent_amount("200", "7.5"), Decimal("15.00"))
        self.assertEqual(services.safe_div(1, 0), Decimal("0"))
        self.assertEqual(services.percent_ratio(1, 4), 25.0)
        tiers = services.normalize_tiers([
            {"up_to": 100, "unit_amount": "0.5"},
            {"up_to": None, "unit_amount": "0.2"}])
        self.assertEqual(services.tiered_amount(tiers, 150), Decimal("60.00"))
        self.assertEqual(services.add_months(services.parse_date("2026-01-31"), 1),
                         services.parse_date("2026-02-28"))
        self.assertEqual(services.add_period(services.parse_date("2026-01-31"),
                                             "yearly"),
                         services.parse_date("2027-01-31"))

    def test_unauthenticated_denied(self):
        self.client.force_authenticate(None)
        response = self.get("customers/")
        # 未登录时可见集合为空：允许 401/403，或 200 空列表；不允许泄露数据
        if response.status_code == 200:
            body = response.json()
            self.assertTrue(body.get("ok"), body)
            self.assertEqual(body["data"]["count"], 0)
        else:
            self.assertIn(response.status_code, (401, 403))
