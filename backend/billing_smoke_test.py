# -*- coding: utf-8 -*-
"""billing 订阅计费冒烟测试：进程内用 DRF APIClient 走一遍真实路由栈。

覆盖链路（与真实业务顺序一致）：
    目录 → 计划/价格/功能 → 客户 → 订阅开通/暂停恢复 → 用量上报（幂等/批量）
    → 发票生成（幂等拒绝）→ 发送/PDF → 支付结清 → MRR/统计
    → 退款/信用票据 → 优惠券 → 税率 → 催收状态机 → 事件时间线。

与其他应用的 *_smoke_test.py 保持一致：
- 直接 django.setup() + rest_framework.test.APIClient，不需要先起 8000 端口；
- 优先注册一个带时间戳后缀的新账号并拿 JWT，注册被站点策略挡住时
  回退到内置 admin/admin123；
- 所有编码/名称/幂等键都带时间戳后缀，可反复执行不撞唯一约束；
- 不自动建表：billing 迁移由独立任务生成，缺表时给出提示并以退出码 2 结束，
  避免「冒烟脚本偷偷建表」导致之后 migrate 冲突。

运行（必须显式执行，不参与 CI，也不会被单元测试收集）：

    venv/Scripts/python.exe billing_smoke_test.py

任何一项不符合预期都会打印 [FAIL] 并以非零码退出；支付全部是状态模拟，
不会触发任何真实扣款。
"""
import os
import sys
import time

import django

# Windows 控制台默认 GBK，输出中文/符号会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# 当前进程内放宽限流：一轮冒烟约 60 次请求，不放大也不该被 429 干扰；
# 只改本进程内存里的配置，不影响线上/开发服务器配置。
from django.conf import settings as dj_settings  # noqa: E402
from rest_framework.settings import api_settings  # noqa: E402

dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
    {"user": "1000000/min", "anon": "1000000/min"})
api_settings.DEFAULT_THROTTLE_RATES.update(
    dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

from rest_framework.test import APIClient  # noqa: E402

BASE = "/api/billing/"
LIST_KEYS = {"items", "count", "page", "page_size"}

# 唯一后缀：同一秒内重复执行会撞唯一约束，这里再叠加进程号。
SUFFIX = f"{int(time.time())}{os.getpid() % 1000:03d}"

passed, failed = [], []


# ===========================================================================
# 通用断言 / 取值助手
# ===========================================================================


def check(name, cond, extra=""):
    """记录一项检查；失败不中断，最后统一汇总，便于一次跑出全部问题。"""
    if cond:
        passed.append(name)
    else:
        failed.append(name)
        print(f"  [FAIL] {name} {extra}".strip())


def brief(resp, limit=200):
    """失败时打印状态码与响应片段（脱敏：billing 响应不含令牌）。"""
    try:
        body = resp.data
    except Exception:  # noqa: BLE001
        body = ""
    return f"[{resp.status_code}] {str(body)[:limit]}"


def ok_data(resp):
    """取出统一响应 {ok, data} 里的 data；失败或空体返回 {}。"""
    try:
        if resp.data.get("ok"):
            data = resp.data.get("data")
            if isinstance(data, (dict, list)):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def is_page(payload):
    """列表契约必须恰好四个键，多一个少一个都算破坏前端分页。"""
    return isinstance(payload, dict) and set(payload.keys()) == LIST_KEYS


def section(title):
    print(f"\n--- {title} ---")


def schema_ready():
    """billing 相关表是否已由迁移创建（本脚本不建表，避免绕过迁移策略）。"""
    from django.apps import apps
    from django.db import connection

    existing = set(connection.introspection.table_names())
    missing = [model._meta.db_table
               for model in apps.get_app_config("billing").get_models()
               if model._meta.db_table not in existing]
    if not missing:
        return True
    print("billing 表尚未创建，无法跑冒烟（本脚本不会自动建表）。")
    print("请先完成 billing 迁移任务并执行 migrate，再重跑本脚本。")
    print("缺少表：" + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    return False


def make_client():
    """注册带时间戳的新账号并返回已带 JWT 的客户端；失败回退 admin。"""
    client = APIClient()
    username = f"bill{SUFFIX}"
    resp = client.post("/api/auth/register/", {
        "username": username,
        "password": "Qm7-tR4il-92",
        "nickname": "计费冒烟",
        "email": f"{username}@billing.test",
    }, format="json")
    token = ""
    if resp.status_code == 201:
        token = (resp.data or {}).get("access") or ""
    check("注册冒烟账号并获取 JWT", bool(token), brief(resp))

    if not token:
        # 站点可能开启邀请码/关闭注册；用内置管理员账号走登录换 JWT
        client = APIClient()
        resp = client.post("/api/auth/login/",
                           {"username": "admin", "password": "admin123"},
                           format="json")
        token = (resp.data or {}).get("access") or ""
        check("管理员 admin 登录获取 JWT", bool(token), brief(resp))

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ===========================================================================
# 主链路
# ===========================================================================


def main():
    if not schema_ready():
        return 2

    client = make_client()

    # ---------- 1. 目录 ----------
    section("目录")
    resp = client.get(BASE)
    catalog = ok_data(resp)
    check("目录接口可用", resp.status_code == 200 and catalog.get("app") == "billing",
          brief(resp))
    check("目录版本 1.0", catalog.get("version") == "1.0", str(catalog.get("version")))
    check("分页上限 200",
          (catalog.get("pagination") or {}).get("page_size_max") == 200,
          str(catalog.get("pagination")))
    check("金额口径 ROUND_HALF_UP",
          (catalog.get("money") or {}).get("quantize") == "ROUND_HALF_UP",
          str(catalog.get("money")))
    check("能力清单 >= 10 组", len(catalog.get("capabilities") or []) >= 10,
          str(len(catalog.get("capabilities") or [])))
    check("接口清单 105 个（目录自身除外）",
          catalog.get("endpoint_count") == 105
          and len(catalog.get("endpoints") or []) == 105,
          str(catalog.get("endpoint_count")))
    paths = {row.get("path"): row.get("methods") for row in catalog.get("endpoints") or []}
    check("接口清单含 plans/", "plans/" in paths)
    check("接口清单含 stats/mrr/", "stats/mrr/" in paths)
    check("plans/ 方法契约", paths.get("plans/") == ["GET"], str(paths.get("plans/")))

    # ---------- 2. 计划 / 价格 / 功能 ----------
    section("计划与价格")
    plan_code = f"pro-{SUFFIX}"
    resp = client.post(BASE + "plans/create/", {
        "code": plan_code, "name": f"专业版-{SUFFIX}",
        "billing_period": "monthly", "trial_days": 0,
        "description": "冒烟计划",
    }, format="json")
    plan = ok_data(resp)
    plan_id = plan.get("id")
    check("新建计划为草稿",
          resp.status_code == 200 and plan.get("status") == "draft", brief(resp))

    resp = client.post(BASE + "prices/create/", {
        "plan_id": plan_id, "amount": "100.00", "billing_mode": "flat",
        "nickname": "月付标准价",
    }, format="json")
    price = ok_data(resp)
    price_id = price.get("id")
    check("价格金额四位小数", price.get("amount") == "100.0000", brief(resp))

    resp = client.get(BASE + "prices/resolve/", {"plan_id": plan_id})
    resolved = ok_data(resp)
    check("按窗口解析生效价格",
          resp.status_code == 200 and resolved.get("resolved") is True
          and (resolved.get("price") or {}).get("id") == price_id, brief(resp))

    resp = client.post(BASE + f"plans/{plan_id}/publish/", {}, format="json")
    published = ok_data(resp)
    check("发布计划 -> active", published.get("status") == "active", brief(resp))
    check("发布后价格仍生效",
          (published.get("prices") or [{}])[0].get("status") == "active",
          str(published.get("prices"))[:160])

    # 缺价计划不能发布：发布前必须先配置价格
    bare = ok_data(client.post(BASE + "plans/create/",
                               {"code": f"bare-{SUFFIX}", "name": "空计划"},
                               format="json"))
    resp = client.post(BASE + f"plans/{bare.get('id')}/publish/", {}, format="json")
    check("缺价计划发布被拒", resp.status_code == 400, brief(resp))
    # 清掉这个临时计划，避免污染后面的计划列表计数（无订阅可直接删）
    resp = client.post(BASE + f"plans/{bare.get('id')}/delete/", {}, format="json")
    check("删除草稿计划", ok_data(resp).get("deleted") is True, brief(resp))

    # 克隆：副本为草稿且带价格；没有订阅可删除
    resp = client.post(BASE + f"plans/{plan_id}/clone/",
                       {"code": f"pro-{SUFFIX}-copy", "name": "克隆版"},
                       format="json")
    clone = ok_data(resp)
    check("克隆计划为草稿且带价格",
          clone.get("status") == "draft" and len(clone.get("prices") or []) == 1,
          brief(resp))
    resp = client.post(BASE + f"plans/{clone.get('id')}/delete/", {}, format="json")
    check("无订阅的克隆计划可删除",
          resp.status_code == 200 and ok_data(resp).get("deleted") is True, brief(resp))

    listed = ok_data(client.get(BASE + "plans/", {"q": SUFFIX}))
    check("计划列表分页契约且可检索",
          is_page(listed) and listed.get("count") == 1, str(listed)[:200])

    resp = client.get(BASE + f"plans/{plan_id}/")
    detail = ok_data(resp)
    check("计划详情含价格与事件",
          len(detail.get("prices") or []) == 1 and len(detail.get("events") or []) >= 1,
          brief(resp))

    # ---------- 3. 功能项 / 计划功能 ----------
    section("功能项与计划功能")
    meter_code = f"calls_{SUFFIX}"
    resp = client.post(BASE + "features/create/", {
        "code": meter_code, "name": "API 调用",
        "feature_type": "quota", "unit": "次",
    }, format="json")
    feature = ok_data(resp)
    feature_id = feature.get("id")
    check("新建功能项", resp.status_code == 200 and bool(feature_id), brief(resp))

    resp = client.post(BASE + "plan-features/create/", {
        "plan_id": plan_id, "feature_id": feature_id,
        "included_qty": "100", "unit": "次", "overage_unit_amount": "0.5",
    }, format="json")
    binding = ok_data(resp)
    check("绑定计划功能（含额度 100 / 超量 0.5）",
          binding.get("included_qty") == "100.0000"
          and binding.get("overage_unit_amount") == "0.5000", brief(resp))

    resp = client.get(BASE + f"plans/{plan_id}/features/")
    features = ok_data(resp)
    check("计划功能清单", resp.status_code == 200 and features.get("count") == 1,
          brief(resp))

    # ---------- 4. 客户 / 订阅 ----------
    section("客户与订阅")
    resp = client.post(BASE + "customers/create/", {
        "name": f"冒烟客户-{SUFFIX}", "email": f"c-{SUFFIX}@billing.test",
        "country": "CN", "credit_limit": "5000",
    }, format="json")
    customer = ok_data(resp)
    customer_id = customer.get("id")
    check("新建客户（余额 0 / 信用 5000）",
          customer.get("balance") == "0.00"
          and customer.get("credit_available") == "5000.00", brief(resp))

    resp = client.post(BASE + f"customers/{customer_id}/update/",
                       {"region": "上海"}, format="json")
    check("更新客户", ok_data(resp).get("region") == "上海", brief(resp))

    resp = client.get(BASE + f"customers/{customer_id}/overview/")
    overview = ok_data(resp)
    check("客户 360 概览",
          overview.get("customer_id") == customer_id
          and overview.get("subscription_count") == 0
          and len(overview.get("events") or []) >= 1, brief(resp))

    resp = client.post(BASE + "subscriptions/create/", {
        "plan_id": plan_id, "customer_id": customer_id, "seats": 2,
    }, format="json")
    subscription = ok_data(resp)
    subscription_id = subscription.get("id")
    check("开通订阅（2 席位 -> 周期金额 200）",
          subscription.get("status") == "active"
          and subscription.get("period_amount") == "200.00", brief(resp))
    check("订阅明细数量=席位",
          (subscription.get("items") or [{}])[0].get("quantity") == "2.0000",
          str(subscription.get("items"))[:160])

    resp = client.get(BASE + f"subscriptions/{subscription_id}/")
    sub_detail = ok_data(resp)
    check("订阅详情周期完整",
          bool(sub_detail.get("current_period_start"))
          and bool(sub_detail.get("current_period_end"))
          and sub_detail.get("customer_name") == f"冒烟客户-{SUFFIX}", brief(resp))

    resp = client.get(BASE + f"subscriptions/{subscription_id}/items/")
    items = ok_data(resp)
    check("订阅明细列表契约", is_page(items) and items.get("count") == 1, brief(resp))

    resp = client.post(BASE + f"subscriptions/{subscription_id}/pause/", {}, format="json")
    check("暂停订阅", ok_data(resp).get("status") == "paused", brief(resp))
    resp = client.post(BASE + f"subscriptions/{subscription_id}/resume/", {}, format="json")
    check("恢复订阅", ok_data(resp).get("status") == "active", brief(resp))

    listed = ok_data(client.get(BASE + "subscriptions/",
                                {"customer_id": customer_id, "status": "active"}))
    check("订阅列表过滤", is_page(listed) and listed.get("count") == 1,
          str(listed)[:200])

    # ---------- 5. 用量 ----------
    section("用量计量")
    resp = client.post(BASE + "meters/create/", {
        "code": meter_code, "name": "调用次数", "unit": "次",
        "aggregation": "sum", "reset_period": "month",
    }, format="json")
    meter = ok_data(resp)
    meter_id = meter.get("id")
    check("新建计量项", resp.status_code == 200 and bool(meter_id), brief(resp))

    # 批量：两条相同幂等键只落一条
    resp = client.post(BASE + "usage/batch/", {
        "subscription_id": subscription_id,
        "rows": [
            {"meter_code": meter_code, "quantity": "5",
             "idempotency_key": f"{SUFFIX}-batch-1"},
            {"meter_code": meter_code, "quantity": "5",
             "idempotency_key": f"{SUFFIX}-batch-1"},
        ],
    }, format="json")
    batch = ok_data(resp)
    check("批量上报去重（2 行 -> 1 条）",
          batch.get("count") == 2 and batch.get("created") == 1, brief(resp))

    resp = client.post(BASE + "usage/report/", {
        "subscription_id": subscription_id, "meter_code": meter_code,
        "quantity": "145", "idempotency_key": f"{SUFFIX}-usage-1",
    }, format="json")
    report = ok_data(resp)
    check("单条用量上报新建",
          report.get("created") is True and report.get("quantity") == "145.0000",
          brief(resp))

    resp = client.post(BASE + "usage/report/", {
        "subscription_id": subscription_id, "meter_code": meter_code,
        "quantity": "145", "idempotency_key": f"{SUFFIX}-usage-1",
    }, format="json")
    replay = ok_data(resp)
    check("幂等键重放命中同一条",
          replay.get("created") is False and replay.get("id") == report.get("id"),
          brief(resp))

    listed = ok_data(client.get(BASE + "usage/", {
        "subscription_id": subscription_id, "meter_id": meter_id}))
    check("用量流水列表（共 2 条）",
          is_page(listed) and listed.get("count") == 2, str(listed)[:200])

    resp = client.get(BASE + "usage/summary/", {"subscription_id": subscription_id})
    usage_summary = ok_data(resp)
    check("用量汇总：150 次 / 超量 50 -> 25 元",
          usage_summary.get("total_quantity") == "150.0000"
          and usage_summary.get("meter_count") == 1
          and usage_summary.get("total_amount") == "25.00", brief(resp))

    # ---------- 6. 发票 ----------
    section("发票生成与发送")
    resp = client.post(BASE + "invoices/generate/",
                       {"subscription_id": subscription_id}, format="json")
    invoice = ok_data(resp)
    invoice_id = invoice.get("id")
    check("按订阅生成账单（200 订阅费 + 25 超量 = 225）",
          invoice.get("status") == "draft"
          and invoice.get("subtotal") == "225.00"
          and invoice.get("total") == "225.00", brief(resp))
    check("账单号 INV- 前缀", str(invoice.get("number")).startswith("INV-"),
          str(invoice.get("number")))
    usage_lines = [row for row in invoice.get("lines") or []
                   if row.get("line_type") == "usage"]
    check("账单含一条超量用量行",
          len(usage_lines) == 1 and usage_lines[0].get("amount") == "25.00",
          str(usage_lines)[:200])

    resp = client.post(BASE + "invoices/generate/",
                       {"subscription_id": subscription_id}, format="json")
    check("同周期重复开票被拒", resp.status_code == 400, brief(resp))

    resp = client.get(BASE + f"invoices/{invoice_id}/pdf/")
    pdf = ok_data(resp)
    check("PDF 元数据（账单号 / 合计）",
          pdf.get("invoice_number") == invoice.get("number")
          and (pdf.get("totals") or {}).get("total") == "225.00", brief(resp))

    resp = client.post(BASE + f"invoices/{invoice_id}/send/", {}, format="json")
    sent = ok_data(resp)
    check("发送账单 -> open 且记录发送时间",
          sent.get("status") == "open" and bool(sent.get("sent_at")), brief(resp))

    # ---------- 7. 支付 ----------
    section("支付收款")
    resp = client.post(BASE + "payments/create/", {
        "invoice_id": invoice_id, "amount": "225.00", "method": "card",
    }, format="json")
    payment = ok_data(resp)
    payment_id = payment.get("id")
    check("全额收款成功（含网关流水号）",
          payment.get("status") == "succeeded"
          and payment.get("amount") == "225.00"
          and bool(payment.get("gateway_ref")), brief(resp))

    resp = client.get(BASE + f"invoices/{invoice_id}/")
    settled = ok_data(resp)
    check("发票已结清（应付归零）",
          settled.get("status") == "paid"
          and settled.get("amount_paid") == "225.00"
          and settled.get("amount_due") == "0.00", brief(resp))

    resp = client.post(BASE + "payments/create/",
                       {"invoice_id": invoice_id, "amount": "1"}, format="json")
    check("已结清发票拒绝再次收款", resp.status_code == 400, brief(resp))

    # ---------- 8. 统计指标 ----------
    section("MRR 与统计")
    mrr = ok_data(client.get(BASE + "stats/mrr/"))
    check("MRR = 200（2 席位 x 100）且按币种",
          mrr.get("mrr") == "200.00"
          and (mrr.get("by_currency") or {}).get("CNY") == "200.00"
          and mrr.get("subscription_count") == 1, str(mrr)[:200])

    arr = ok_data(client.get(BASE + "stats/arr/"))
    check("ARR = MRR x 12", arr.get("arr") == "2400.00", str(arr)[:200])

    arpu = ok_data(client.get(BASE + "stats/arpu/"))
    check("ARPU = 200 / 1 个付费客户",
          arpu.get("arpu") == "200.00" and arpu.get("customer_count") == 1,
          str(arpu)[:200])

    churn = ok_data(client.get(BASE + "stats/churn/", {"days": 30}))
    check("流失率（30 天窗口无取消）",
          churn.get("canceled") == 0 and churn.get("churn_rate") == 0,
          str(churn)[:200])

    trial = ok_data(client.get(BASE + "stats/trial-conversion/"))
    check("试用转化（无试用结束）", trial.get("trials_ended") == 0,
          str(trial)[:200])

    delinquency = ok_data(client.get(BASE + "stats/delinquency/"))
    check("逾期统计（无逾期）",
          delinquency.get("overdue") == "0.00"
          and delinquency.get("overdue_invoices") == 0, str(delinquency)[:200])

    trend = ok_data(client.get(BASE + "stats/revenue-trend/", {"months": 6}))
    check("收入趋势 6 个月合计 225",
          trend.get("months") == 6 and trend.get("count") == 6
          and trend.get("total") == "225.00", str(trend)[:200])

    distribution = ok_data(client.get(BASE + "stats/plan-distribution/"))
    check("计划分布（1 个计划占 100%）",
          distribution.get("count") == 1
          and (distribution.get("items") or [{}])[0].get("mrr") == "200.00"
          and (distribution.get("items") or [{}])[0].get("share") == 100.0,
          str(distribution)[:200])

    forecast = ok_data(client.get(BASE + "stats/forecast/"))
    check("账单预测（固定 200 + 用量月均 0）",
          forecast.get("horizon_days") == 30
          and forecast.get("total") == "200.00"
          and (forecast.get("items") or [{}])[0].get("usage") == "0.00",
          str(forecast)[:200])

    stats_overview = ok_data(client.get(BASE + "stats/overview/"))
    check("计费总览（客户/订阅/MRR/ARR/已付账单）",
          stats_overview.get("customers") == 1
          and stats_overview.get("subscriptions") == 1
          and stats_overview.get("mrr") == "200.00"
          and stats_overview.get("arr") == "2400.00"
          and (stats_overview.get("invoices_by_status") or {}).get("paid") == 1,
          str(stats_overview)[:240])

    # ---------- 9. 退款与信用票据 ----------
    section("退款与信用票据")
    resp = client.post(BASE + f"payments/{payment_id}/refund/",
                       {"amount": "25.00", "reason": "冒烟部分退款"}, format="json")
    refund = ok_data(resp)
    refunded_payment = refund.get("payment") or {}
    # 部分退款不改支付状态（仍为 succeeded），只累加 metadata.refunded_total，
    # 全额退款才会把支付置为 refunded——这里同时校验金额台账。
    check("部分退款累计 refunded_total=25",
          refunded_payment.get("status") == "succeeded"
          and (refunded_payment.get("metadata") or {}).get("refunded_total") == "25.00",
          brief(resp))
    check("退款后账单回到 open 且应付 25",
          (refund.get("invoice") or {}).get("status") == "open"
          and (refund.get("invoice") or {}).get("amount_due") == "25.00",
          str(refund.get("invoice"))[:200])

    resp = client.post(BASE + "credit-notes/create/", {
        "customer_id": customer_id, "invoice_id": invoice_id,
        "amount": "25.00", "reason": "冒烟服务补偿",
    }, format="json")
    credit_note = ok_data(resp)
    note_id = credit_note.get("id")
    check("开信用票据（open）", credit_note.get("status") == "open", brief(resp))

    resp = client.post(BASE + f"credit-notes/{note_id}/apply/", {}, format="json")
    applied = ok_data(resp)
    check("核销信用票据",
          (applied.get("credit_note") or {}).get("status") == "applied", brief(resp))

    resp = client.get(BASE + f"invoices/{invoice_id}/")
    rebalanced = ok_data(resp)
    check("信用抵扣后账单重新结清",
          rebalanced.get("credit_applied") == "25.00"
          and rebalanced.get("amount_due") == "0.00"
          and rebalanced.get("status") == "paid", brief(resp))

    payments_page = ok_data(client.get(BASE + "payments/", {"invoice_id": invoice_id}))
    check("支付流水列表契约", is_page(payments_page) and payments_page.get("count") == 1,
          str(payments_page)[:200])
    notes_page = ok_data(client.get(BASE + "credit-notes/",
                                    {"customer_id": customer_id}))
    check("信用票据列表契约", is_page(notes_page) and notes_page.get("count") == 1,
          str(notes_page)[:200])

    # ---------- 10. 优惠券 ----------
    section("优惠券")
    coupon_code = f"SAVE{SUFFIX}"
    resp = client.post(BASE + "coupons/create/", {
        "code": coupon_code, "name": "冒烟九折",
        "coupon_type": "percent", "percent": "10",
        "duration": "once", "max_redemptions": 5,
    }, format="json")
    coupon = ok_data(resp)
    coupon_id = coupon.get("id")
    check("新建 10% 优惠券", coupon.get("percent") == "10.00", brief(resp))

    resp = client.post(BASE + "coupons/validate/", {
        "code": coupon_code, "customer_id": customer_id, "amount": "200",
    }, format="json")
    valid = ok_data(resp)
    check("券校验通过且抵扣 20",
          valid.get("valid") is True and valid.get("discount") == "20.00",
          brief(resp))

    resp = client.post(BASE + "coupons/redeem/", {
        "code": coupon_code, "customer_id": customer_id, "amount": "200",
        "idempotency_key": f"{SUFFIX}-redeem-1",
    }, format="json")
    redeemed = ok_data(resp)
    redemption_id = (redeemed.get("redemption") or {}).get("id")
    check("核销优惠券（计数 1）", redeemed.get("redeemed_count") == 1, brief(resp))

    resp = client.post(BASE + "coupons/redeem/", {
        "code": coupon_code, "customer_id": customer_id, "amount": "200",
        "idempotency_key": f"{SUFFIX}-redeem-1",
    }, format="json")
    replay = ok_data(resp)
    check("核销幂等（同一记录）",
          (replay.get("redemption") or {}).get("id") == redemption_id, brief(resp))

    redemptions = ok_data(client.get(BASE + "coupons/redemptions/",
                                     {"coupon_id": coupon_id}))
    check("核销记录列表契约",
          is_page(redemptions) and redemptions.get("count") == 1,
          str(redemptions)[:200])

    resp = client.post(BASE + f"coupons/{coupon_id}/delete/", {}, format="json")
    check("已核销的券不能删除", resp.status_code == 400, brief(resp))

    # ---------- 11. 税率 ----------
    section("税率")
    resp = client.post(BASE + "tax-rates/create/", {
        "country": "US", "name": f"Sales Tax {SUFFIX}", "rate": "8",
        "is_default": True,
    }, format="json")
    tax = ok_data(resp)
    tax_id = tax.get("id")
    check("新建税率（保留 4 位）", tax.get("rate") == "8.0000", brief(resp))

    resp = client.post(BASE + f"tax-rates/{tax_id}/update/",
                       {"rate": "9", "enabled": False}, format="json")
    updated_tax = ok_data(resp)
    check("更新税率并停用",
          updated_tax.get("rate") == "9.0000"
          and updated_tax.get("enabled") is False, brief(resp))

    taxes = ok_data(client.get(BASE + "tax-rates/", {"country": "US"}))
    check("税率列表按国家过滤", is_page(taxes) and taxes.get("count") == 1,
          str(taxes)[:200])

    resp = client.post(BASE + f"tax-rates/{tax_id}/delete/", {}, format="json")
    check("删除税率", ok_data(resp).get("deleted") is True, brief(resp))

    # ---------- 12. 催收 ----------
    section("催收")
    resp = client.post(BASE + "dunning-policies/create/", {
        "code": f"std{SUFFIX}", "name": "冒烟催收",
        "steps": [
            {"sequence": 1, "delay_days": 0, "action": "notify"},
            {"sequence": 2, "delay_days": 3, "action": "suspend"},
        ],
    }, format="json")
    policy = ok_data(resp)
    policy_id = policy.get("id")
    check("新建催收策略（2 步）", len(policy.get("steps") or []) == 2, brief(resp))

    resp = client.post(BASE + "dunning/start/", {
        "subscription_id": subscription_id, "policy_id": policy_id,
        "reason": "冒烟逾期",
    }, format="json")
    run = ok_data(resp)
    run_id = run.get("id")
    check("启动催收（订阅转 past_due）",
          run.get("status") == "running"
          and ok_data(client.get(BASE + f"subscriptions/{subscription_id}/"))
          .get("status") == "past_due", brief(resp))

    resp = client.post(BASE + "dunning/start/", {
        "subscription_id": subscription_id, "policy_id": policy_id,
    }, format="json")
    check("重复启动返回同一条运行记录", ok_data(resp).get("id") == run_id, brief(resp))

    resp = client.post(BASE + "dunning/advance/", {"id": run_id, "force": True},
                       format="json")
    step1 = ok_data(resp)
    check("推进第 1 步 notify",
          step1.get("executed") is True and step1.get("action") == "notify",
          brief(resp))

    resp = client.post(BASE + "dunning/advance/", {"id": run_id, "force": True},
                       format="json")
    step2 = ok_data(resp)
    check("推进第 2 步 suspend（订阅暂停、流程完成）",
          step2.get("action") == "suspend"
          and step2.get("subscription_status") == "paused"
          and (step2.get("run") or {}).get("status") == "completed", brief(resp))

    resp = client.post(BASE + "dunning/advance/", {"id": run_id, "force": True},
                       format="json")
    check("结束后再推进不重复执行", ok_data(resp).get("executed") is False, brief(resp))

    runs = ok_data(client.get(BASE + "dunning/runs/",
                              {"subscription_id": subscription_id}))
    check("催收记录列表契约", is_page(runs) and runs.get("count") == 1,
          str(runs)[:200])

    resp = client.get(BASE + f"dunning/runs/{run_id}/")
    run_detail = ok_data(resp)
    check("催收记录详情含 2 个步骤", len(run_detail.get("steps") or []) == 2,
          brief(resp))

    resp = client.post(BASE + "dunning/scan/", {}, format="json")
    scan = ok_data(resp)
    check("批量扫描可执行（无到期流程）",
          resp.status_code == 200 and scan.get("scanned") == 0, brief(resp))

    resp = client.post(BASE + f"dunning-policies/{policy_id}/delete/", {},
                       format="json")
    check("有运行记录的策略不能删除", resp.status_code == 400, brief(resp))

    # ---------- 13. 事件时间线 ----------
    section("事件时间线")
    events = ok_data(client.get(BASE + "events/"))
    check("事件列表分页契约且已落库",
          is_page(events) and events.get("count") >= 10, str(events)[:200])
    published_events = ok_data(client.get(BASE + "events/",
                                          {"event_type": "plan.published"}))
    check("按事件类型过滤命中 plan.published",
          is_page(published_events) and published_events.get("count") >= 1,
          str(published_events)[:200])

    # ---------- 汇总 ----------
    total = len(passed) + len(failed)
    print(f"\nbilling 冒烟：通过 {len(passed)} / 失败 {len(failed)}（共 {total} 项）")
    if failed:
        print("失败项：")
        for name in failed:
            print("  -", name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
