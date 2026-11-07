# -*- coding: utf-8 -*-
"""订阅计费 · 数据模型（20 张表）。

设计要点
--------
1. 所有业务表统一带 ``owner`` 外键（行级权限唯一收口）与 ``created_at`` /
   ``updated_at`` 时间戳，related_name 一律 ``billing_*`` 前缀，避免与
   其它应用的 User 反向关系撞名。
2. 金额一律用 ``DecimalField``，绝不使用 FloatField —— SQLite 的 REAL 是
   二进制浮点，0.1 + 0.2 会得到 0.30000000000000004，对账场景不可接受。
   单价字段保留 4 位（按量计价的单价可能低于 1 分），汇总金额保留 2 位。
3. 计费周期边界用 ``DateField``（含起始、不含结束）：账单周期是「自然日」
   概念，用 DateTime 会引入时区比较的边界歧义；用量发生时间才用 DateTime。
4. 计划的功能上限、阶梯配置、事件负载等半结构化数据放 JSONField：这些
   字段的形态由产品配置决定，建独立表会让配置入口碎片化，也会让一次
   保存变成多表写入。
5. 幂等：UsageRecord / BillingEvent / CouponRedemption 保留幂等键并加
   条件唯一约束，业务层重复提交时直接返回既有记录，而不是靠「先查后写」
   的竞态窗口。
"""
import calendar
from decimal import Decimal

from django.conf import settings
from django.db import models

# ---------------------------------------------------------------------------
# 枚举（同时导出 *_VALUES 供视图层校验，避免视图里散落字符串字面量）
# ---------------------------------------------------------------------------

PLAN_PERIODS = ("monthly", "yearly", "one_time")
PLAN_PERIOD_LABELS = {"monthly": "按月", "yearly": "按年", "one_time": "一次性"}

PLAN_STATUS = ("draft", "active", "archived")
PLAN_STATUS_LABELS = {"draft": "草稿", "active": "已发布", "archived": "已停用"}

FEATURE_TYPES = ("boolean", "quota", "metered")
FEATURE_TYPE_LABELS = {"boolean": "开关", "quota": "配额", "metered": "计量"}

BILLING_MODES = ("flat", "per_unit", "tiered")
BILLING_MODE_LABELS = {"flat": "固定价", "per_unit": "按量", "tiered": "阶梯"}

CUSTOMER_STATUS = ("active", "archived")
CUSTOMER_STATUS_LABELS = {"active": "正常", "archived": "已归档"}

SUBSCRIPTION_STATUS = ("trialing", "active", "past_due", "canceled", "paused")
SUBSCRIPTION_STATUS_LABELS = {
    "trialing": "试用中",
    "active": "生效中",
    "past_due": "逾期",
    "canceled": "已取消",
    "paused": "已暂停",
}
# 会占用资源的「在服」状态：试用、生效、逾期都还在服务期，暂停与取消不算
LIVE_SUBSCRIPTION_STATUS = ("trialing", "active", "past_due")

INVOICE_STATUS = ("draft", "open", "paid", "void", "uncollectible")
INVOICE_STATUS_LABELS = {
    "draft": "草稿",
    "open": "待支付",
    "paid": "已支付",
    "void": "已作废",
    "uncollectible": "无法收回",
}
# 会被重复生成逻辑拦截的「未结清」状态
INVOICE_BLOCKING_STATUS = ("draft", "open", "paid")

LINE_TYPES = ("subscription", "usage", "proration", "discount", "tax", "credit")
LINE_TYPE_LABELS = {
    "subscription": "订阅费",
    "usage": "用量费",
    "proration": "折算",
    "discount": "折扣",
    "tax": "税费",
    "credit": "抵扣",
}

PAYMENT_STATUS = ("pending", "succeeded", "failed", "refunded")
PAYMENT_STATUS_LABELS = {
    "pending": "处理中",
    "succeeded": "已成功",
    "failed": "已失败",
    "refunded": "已退款",
}
PAYMENT_METHODS = ("card", "bank_transfer", "alipay", "wechat", "manual", "credit")
PAYMENT_METHOD_LABELS = {
    "card": "银行卡",
    "bank_transfer": "对公转账",
    "alipay": "支付宝",
    "wechat": "微信支付",
    "manual": "人工登记",
    "credit": "账户余额",
}

CREDIT_NOTE_STATUS = ("draft", "open", "applied", "void")
CREDIT_NOTE_STATUS_LABELS = {
    "draft": "草稿",
    "open": "待核销",
    "applied": "已核销",
    "void": "已作废",
}

COUPON_TYPES = ("percent", "fixed")
COUPON_TYPE_LABELS = {"percent": "百分比", "fixed": "固定金额"}

COUPON_DURATIONS = ("once", "repeating", "forever")
COUPON_DURATION_LABELS = {"once": "仅一次", "repeating": "重复 N 期", "forever": "永久"}

COUPON_STATUS = ("active", "archived")
COUPON_STATUS_LABELS = {"active": "可用", "archived": "已停用"}

METER_AGGREGATIONS = ("sum", "max", "latest", "count")
METER_AGGREGATION_LABELS = {
    "sum": "求和",
    "max": "最大值",
    "latest": "最新值",
    "count": "次数",
}

METER_RESET_PERIODS = ("day", "month", "none")
METER_RESET_LABELS = {"day": "按日", "month": "按月", "none": "不重置"}

DUNNING_ACTIONS = ("notify", "suspend", "cancel")
DUNNING_ACTION_LABELS = {"notify": "通知", "suspend": "暂停服务", "cancel": "取消订阅"}

DUNNING_RUN_STATUS = ("running", "completed", "recovered", "failed")
DUNNING_RUN_STATUS_LABELS = {
    "running": "催收中",
    "completed": "已走完",
    "recovered": "已回款",
    "failed": "异常",
}

EVENT_STATUS = ("pending", "processed", "failed")
EVENT_STATUS_LABELS = {"pending": "待处理", "processed": "已处理", "failed": "处理失败"}


def choices(values):
    """把值元组转成 Django choices；展示名由 *_LABELS 提供。

    中英文分离：接口返回 label 供前端直出，数据库只存稳定英文码，
    改名/翻译不会导致历史数据迁移。
    """
    labels = {}
    for name in (
        PLAN_PERIOD_LABELS, PLAN_STATUS_LABELS, FEATURE_TYPE_LABELS,
        BILLING_MODE_LABELS, CUSTOMER_STATUS_LABELS, SUBSCRIPTION_STATUS_LABELS,
        INVOICE_STATUS_LABELS, LINE_TYPE_LABELS, PAYMENT_STATUS_LABELS,
        PAYMENT_METHOD_LABELS, CREDIT_NOTE_STATUS_LABELS, COUPON_TYPE_LABELS,
        COUPON_DURATION_LABELS, COUPON_STATUS_LABELS, METER_AGGREGATION_LABELS,
        METER_RESET_LABELS, DUNNING_ACTION_LABELS, DUNNING_RUN_STATUS_LABELS,
        EVENT_STATUS_LABELS,
    ):
        labels.update(name)
    return [(v, labels.get(v, v)) for v in values]


def label_of(value, labels):
    """取枚举中文名，未登记时回退原值（历史脏数据也能安全渲染）。"""
    return labels.get(value, value)


def last_day_of_month(year, month):
    """该月最后一天（闰年 2 月自动 29）。

    抽成函数而不是在每个模型里算：周期推进、账单预测、逾期扫描都要用，
    calendar.monthrange 是唯一正确处理闰年的写法。
    """
    return calendar.monthrange(year, month)[1]


class OwnedQuerySet(models.QuerySet):
    """常用聚合捷径：金额字段求和时统一走 Decimal。

    Django 的 Sum 在 SQLite 上返回 Decimal（DecimalField 聚合），但空集
    返回 None，这里统一兜底为 0，避免调用方到处写 ``or 0``。
    """

    def total(self, field):
        value = self.aggregate(v=models.Sum(field))["v"]
        return value if value is not None else Decimal("0")


class OwnedModel(models.Model):
    """带 owner 与时间戳的抽象基类。

    所有计费数据都归属某个平台用户（运营/财务），行级权限只认 owner，
    与 core.scoping 的约定保持一致；租户隔离由 scoping 在查询层统一处理，
    业务表不重复存 tenant_id（否则两套隔离规则会打架）。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_owned",
        verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        abstract = True

    def touch(self):
        """显式刷新更新时间（批量 update 绕过 auto_now，需要显式落库时用）。"""
        self.save(update_fields=["updated_at"])


# ===========================================================================
# 一、产品目录：Plan / Price / Feature / PlanFeature
# ===========================================================================


class Plan(OwnedModel):
    """订阅计划：售卖的最小单元（基础版/专业版/企业版…）。

    ``limits`` 存 JSON 而不是拆 Feature 外键：计划的功能上限是一次性配置，
    读多写少，JSON 一次查询就能取全；需要结构化统计时再由 PlanFeature 承载
    单价与包含量（两者分工：limits 是「能不能用/上限多少」，PlanFeature 是
    「超了怎么收费」）。
    """

    code = models.CharField("计划编码", max_length=60)
    name = models.CharField("计划名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    billing_period = models.CharField("计费周期", max_length=16, default="monthly",
                                      choices=choices(PLAN_PERIODS))
    trial_days = models.IntegerField("试用天数", default=0)
    status = models.CharField("状态", max_length=16, default="draft",
                              choices=choices(PLAN_STATUS), db_index=True)
    sort_order = models.IntegerField("排序", default=0)
    limits = models.JSONField("功能上限", default=dict, blank=True)
    metadata = models.JSONField("扩展信息", default=dict, blank=True)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "订阅计划"
        verbose_name_plural = "订阅计划"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="billing_plan_owner_code_uniq"),
        ]
        indexes = [models.Index(fields=["status", "billing_period"], name="billing_plan_status_idx")]

    def __str__(self):
        return f"{self.name}({self.code})"

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def period_label(self):
        return label_of(self.billing_period, PLAN_PERIOD_LABELS)


class Price(OwnedModel):
    """计划价格：同一计划可按币种/时间段并存多条，取价时按生效时间窗口解析。

    单价留 4 位小数：按量计费常见 0.002 元/次这类价格，2 位会把单价抹成 0。
    阶梯配置 tiers 的形态：``[{"up_to": 100, "unit_amount": "0.5"}, ...]``，
    最后一档 ``up_to`` 为 null 表示「以上」。
    """

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE,
                             related_name="prices", verbose_name="计划")
    currency = models.CharField("币种", max_length=8, default="CNY", db_index=True)
    amount = models.DecimalField("金额/单价", max_digits=16, decimal_places=4, default=Decimal("0"))
    billing_mode = models.CharField("计费模式", max_length=16, default="flat",
                                    choices=choices(BILLING_MODES))
    tiers = models.JSONField("阶梯配置", default=list, blank=True)
    effective_from = models.DateField("生效起始", null=True, blank=True)
    effective_to = models.DateField("生效截止", null=True, blank=True)
    status = models.CharField("状态", max_length=16, default="active")
    nickname = models.CharField("价格别名", max_length=120, blank=True, default="")

    class Meta:
        verbose_name = "计划价格"
        verbose_name_plural = "计划价格"
        ordering = ["plan_id", "currency", "-effective_from", "-id"]
        constraints = [
            # 同计划同币种同生效日只允许一条，避免取价时出现「两个当前价」
            models.UniqueConstraint(fields=["plan", "currency", "effective_from"],
                                    name="billing_price_window_uniq"),
        ]
        indexes = [models.Index(fields=["plan", "currency", "status"], name="billing_price_lookup_idx")]

    def __str__(self):
        return f"{self.plan_id}/{self.currency}/{self.amount}"

    def covers(self, day):
        """该价格在指定日期是否生效（左闭右开，与账期口径一致）。"""
        if self.status != "active":
            return False
        if self.effective_from and day < self.effective_from:
            return False
        if self.effective_to and day >= self.effective_to:
            return False
        return True


class Feature(OwnedModel):
    """功能项：计划可包含的开关/配额/计量能力（如 API 调用量、成员数）。"""

    code = models.CharField("功能编码", max_length=60)
    name = models.CharField("功能名称", max_length=120)
    feature_type = models.CharField("类型", max_length=16, default="boolean",
                                    choices=choices(FEATURE_TYPES))
    description = models.TextField("描述", blank=True, default="")
    unit = models.CharField("计量单位", max_length=20, blank=True, default="")
    status = models.CharField("状态", max_length=16, default="active")

    class Meta:
        verbose_name = "功能项"
        verbose_name_plural = "功能项"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="billing_feature_owner_code_uniq"),
        ]

    def __str__(self):
        return f"{self.name}({self.code})"


class PlanFeature(OwnedModel):
    """计划-功能绑定：包含量、单位与超量单价（按量计费的核心定价输入）。"""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE,
                             related_name="plan_features", verbose_name="计划")
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE,
                                related_name="plan_features", verbose_name="功能")
    included_qty = models.DecimalField("包含量", max_digits=16, decimal_places=4,
                                       default=Decimal("0"))
    unit = models.CharField("单位", max_length=20, blank=True, default="")
    overage_unit_amount = models.DecimalField("超量单价", max_digits=16, decimal_places=4,
                                              default=Decimal("0"))
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "计划功能"
        verbose_name_plural = "计划功能"
        ordering = ["plan_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "feature"], name="billing_plan_feature_uniq"),
        ]

    def __str__(self):
        return f"{self.plan_id}-{self.feature_id}"


# ===========================================================================
# 二、客户与订阅
# ===========================================================================


class Customer(OwnedModel):
    """付费客户（企业/个人账户）。

    ``balance`` 是预存余额（正数为客户可用），``credit_limit`` 是允许透支的额度；
    可用信用 = balance + credit_limit - 未结清应收，由服务层统一计算。
    """

    name = models.CharField("客户名称", max_length=200)
    email = models.EmailField("邮箱", blank=True, default="")
    tax_id = models.CharField("税号", max_length=60, blank=True, default="")
    address = models.TextField("地址", blank=True, default="")
    country = models.CharField("国家/地区", max_length=8, default="CN")
    region = models.CharField("省/州", max_length=60, blank=True, default="")
    currency = models.CharField("结算币种", max_length=8, default="CNY")
    status = models.CharField("状态", max_length=16, default="active",
                              choices=choices(CUSTOMER_STATUS), db_index=True)
    balance = models.DecimalField("账户余额", max_digits=16, decimal_places=2,
                                  default=Decimal("0"))
    credit_limit = models.DecimalField("信用额度", max_digits=16, decimal_places=2,
                                       default=Decimal("0"))
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "客户"
        verbose_name_plural = "客户"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "email"], name="billing_customer_idx")]

    def __str__(self):
        return self.name


class Subscription(OwnedModel):
    """订阅：客户 + 计划 + 生命周期状态。

    周期边界 ``current_period_start`` / ``current_period_end`` 左闭右开；
    试用期用 DateTime（``trial_end``），因为试用常按「小时级」到期触发转化，
    而账单周期只需要日精度。
    """

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name="subscriptions", verbose_name="客户")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT,
                             related_name="subscriptions", verbose_name="计划")
    status = models.CharField("状态", max_length=16, default="active",
                              choices=choices(SUBSCRIPTION_STATUS), db_index=True)
    currency = models.CharField("币种", max_length=8, default="CNY")
    seats = models.IntegerField("席位数", default=1)
    start_date = models.DateField("开始日期")
    trial_end = models.DateTimeField("试用结束", null=True, blank=True)
    current_period_start = models.DateField("当前周期起始")
    current_period_end = models.DateField("当前周期结束（不含）")
    cancel_at_period_end = models.BooleanField("期末取消", default=False)
    auto_renew = models.BooleanField("自动续费", default=True)
    canceled_at = models.DateTimeField("取消时间", null=True, blank=True)
    cancel_reason = models.CharField("取消原因", max_length=200, blank=True, default="")
    paused_at = models.DateTimeField("暂停时间", null=True, blank=True)
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "订阅"
        verbose_name_plural = "订阅"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "current_period_end"], name="billing_sub_status_idx"),
            models.Index(fields=["customer", "status"], name="billing_sub_customer_idx"),
        ]

    def __str__(self):
        return f"订阅#{self.pk} {self.customer_id} {self.status}"

    @property
    def status_label(self):
        return label_of(self.status, SUBSCRIPTION_STATUS_LABELS)

    @property
    def is_live(self):
        """是否仍在提供服务（试用/生效/逾期）。"""
        return self.status in LIVE_SUBSCRIPTION_STATUS

    @property
    def current_period_days(self):
        """当前周期天数（至少 1，防御脏数据导致的除零）。"""
        return max((self.current_period_end - self.current_period_start).days, 1)


class SubscriptionItem(OwnedModel):
    """订阅明细行：一个订阅可含多条价格（基础费 + 加购席/插件）。

    生效区间让「中途加购」可以按天折算，而不必改历史账单。
    """

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE,
                                     related_name="items", verbose_name="订阅")
    price = models.ForeignKey(Price, on_delete=models.PROTECT,
                              related_name="subscription_items", verbose_name="价格")
    quantity = models.DecimalField("数量", max_digits=12, decimal_places=2,
                                   default=Decimal("1"))
    effective_from = models.DateField("生效起始", null=True, blank=True)
    effective_to = models.DateField("生效截止", null=True, blank=True)
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "订阅明细"
        verbose_name_plural = "订阅明细"
        ordering = ["subscription_id", "id"]
        indexes = [models.Index(fields=["subscription", "effective_from"], name="billing_item_idx")]

    def __str__(self):
        return f"{self.subscription_id}/{self.price_id} x{self.quantity}"

    def active_on(self, day):
        """在指定日期是否生效（左闭右开）。"""
        if self.effective_from and day < self.effective_from:
            return False
        if self.effective_to and day >= self.effective_to:
            return False
        return True


# ===========================================================================
# 三、用量计量
# ===========================================================================


class Meter(OwnedModel):
    """计量项：定义「怎么聚合」而不是「怎么收费」。

    聚合方式与收费解耦：同一计量项可以按 sum 计费，也可以按 max 计峰值，
    收费规则由 PlanFeature 的超量单价决定。
    """

    code = models.CharField("计量编码", max_length=60)
    name = models.CharField("计量名称", max_length=120)
    aggregation = models.CharField("聚合方式", max_length=16, default="sum",
                                   choices=choices(METER_AGGREGATIONS))
    unit = models.CharField("单位", max_length=20, blank=True, default="")
    reset_period = models.CharField("重置周期", max_length=16, default="month",
                                    choices=choices(METER_RESET_PERIODS))
    status = models.CharField("状态", max_length=16, default="active")
    description = models.TextField("描述", blank=True, default="")

    class Meta:
        verbose_name = "计量项"
        verbose_name_plural = "计量项"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="billing_meter_owner_code_uniq"),
        ]

    def __str__(self):
        return f"{self.name}({self.code})"


class UsageRecord(OwnedModel):
    """用量流水：一条上报记录 = 一次计量事件。

    ``idempotency_key`` 做条件唯一（空串不参与），让重试上报天然幂等；
    ``invoiced`` 标记是否已被某张发票收割，避免同一笔用量重复计费。
    """

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE,
                                     related_name="usage_records", verbose_name="订阅")
    meter = models.ForeignKey(Meter, on_delete=models.CASCADE,
                              related_name="usage_records", verbose_name="计量项")
    quantity = models.DecimalField("数量", max_digits=18, decimal_places=4,
                                   default=Decimal("0"))
    occurred_at = models.DateTimeField("发生时间", db_index=True)
    idempotency_key = models.CharField("幂等键", max_length=120, blank=True, default="")
    source = models.CharField("来源", max_length=60, blank=True, default="api")
    invoiced = models.BooleanField("已计入发票", default=False, db_index=True)
    invoice = models.ForeignKey("Invoice", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="usage_records", verbose_name="所属发票")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "用量流水"
        verbose_name_plural = "用量流水"
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="billing_usage_idem_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["subscription", "meter", "occurred_at"],
                         name="billing_usage_lookup_idx"),
            models.Index(fields=["subscription", "invoiced"], name="billing_usage_inv_idx"),
        ]

    def __str__(self):
        return f"{self.subscription_id}/{self.meter_id} {self.quantity}"


# ===========================================================================
# 四、账单与收款
# ===========================================================================


class Invoice(OwnedModel):
    """发票/账单：金额字段全部是「已量化」的汇总值，行项才是真源。

    ``total = subtotal - discount_total + tax_total``，由服务层 recalc 维护；
    任何直接改金额的入口都必须重新 recalc，防止行项与汇总对不上。
    ``period_start/end`` 允许为空：手工补开的账单不一定对应订阅周期。
    """

    number = models.CharField("发票编号", max_length=40)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name="invoices", verbose_name="客户")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="invoices", verbose_name="订阅")
    status = models.CharField("状态", max_length=16, default="draft",
                              choices=choices(INVOICE_STATUS), db_index=True)
    source = models.CharField("来源", max_length=20, default="subscription")
    currency = models.CharField("币种", max_length=8, default="CNY")
    period_start = models.DateField("周期起始", null=True, blank=True)
    period_end = models.DateField("周期结束（不含）", null=True, blank=True)
    subtotal = models.DecimalField("小计", max_digits=16, decimal_places=2, default=Decimal("0"))
    discount_total = models.DecimalField("折扣", max_digits=16, decimal_places=2, default=Decimal("0"))
    tax_total = models.DecimalField("税费", max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField("总额", max_digits=16, decimal_places=2, default=Decimal("0"))
    amount_paid = models.DecimalField("已付", max_digits=16, decimal_places=2, default=Decimal("0"))
    credit_applied = models.DecimalField("抵扣", max_digits=16, decimal_places=2, default=Decimal("0"))
    due_date = models.DateField("到期日", null=True, blank=True, db_index=True)
    paid_at = models.DateTimeField("付款时间", null=True, blank=True)
    sent_at = models.DateTimeField("发送时间", null=True, blank=True)
    voided_at = models.DateTimeField("作废时间", null=True, blank=True)
    notes = models.TextField("备注", blank=True, default="")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "发票"
        verbose_name_plural = "发票"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "number"], name="billing_invoice_number_uniq"),
        ]
        indexes = [
            models.Index(fields=["customer", "status"], name="billing_invoice_cust_idx"),
            models.Index(fields=["subscription", "period_start"], name="billing_invoice_period_idx"),
            models.Index(fields=["status", "due_date"], name="billing_invoice_due_idx"),
        ]

    def __str__(self):
        return self.number

    @property
    def amount_due(self):
        """未结金额：总额 - 已付 - 抵扣，负数按 0（多付部分进余额）。"""
        value = (self.total or Decimal("0")) - (self.amount_paid or Decimal("0")) \
            - (self.credit_applied or Decimal("0"))
        return value if value > 0 else Decimal("0")

    @property
    def is_open(self):
        return self.status == "open"

    @property
    def is_overdue(self):
        from django.utils import timezone

        return bool(self.status == "open" and self.due_date
                    and self.due_date < timezone.localdate() and self.amount_due > 0)


class InvoiceLine(OwnedModel):
    """发票行项：账单的明细真源（订阅费/用量/折算/折扣/税/抵扣）。"""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                related_name="lines", verbose_name="发票")
    line_type = models.CharField("行类型", max_length=20, default="subscription",
                                 choices=choices(LINE_TYPES))
    description = models.CharField("说明", max_length=200)
    quantity = models.DecimalField("数量", max_digits=16, decimal_places=4,
                                   default=Decimal("1"))
    unit_amount = models.DecimalField("单价", max_digits=16, decimal_places=4,
                                      default=Decimal("0"))
    amount = models.DecimalField("金额", max_digits=16, decimal_places=2,
                                 default=Decimal("0"))
    metadata = models.JSONField("元数据", default=dict, blank=True)
    sort_order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = "发票行"
        verbose_name_plural = "发票行"
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["invoice", "line_type"], name="billing_line_idx")]

    def __str__(self):
        return f"{self.invoice_id} {self.line_type} {self.amount}"


class Payment(OwnedModel):
    """支付流水：真实扣款由网关完成，本系统只登记结果（状态模拟）。

    状态机 pending → succeeded / failed，succeeded → refunded。
    网关流水号本地生成（SIM- 前缀），保证「同一笔支付」可被前端与对账
    脚本唯一定位；不联网、不接真实渠道是无外部依赖的硬约束。
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="payments", verbose_name="发票")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name="payments", verbose_name="客户")
    amount = models.DecimalField("金额", max_digits=16, decimal_places=2, default=Decimal("0"))
    currency = models.CharField("币种", max_length=8, default="CNY")
    method = models.CharField("支付方式", max_length=20, default="card",
                              choices=choices(PAYMENT_METHODS))
    status = models.CharField("状态", max_length=16, default="pending",
                              choices=choices(PAYMENT_STATUS), db_index=True)
    gateway_ref = models.CharField("网关流水号", max_length=80, blank=True, default="",
                                   db_index=True)
    failure_reason = models.CharField("失败原因", max_length=200, blank=True, default="")
    paid_at = models.DateTimeField("支付时间", null=True, blank=True)
    attempts = models.IntegerField("尝试次数", default=1)
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "支付"
        verbose_name_plural = "支付"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["customer", "status"], name="billing_payment_cust_idx"),
            models.Index(fields=["invoice", "status"], name="billing_payment_inv_idx"),
        ]

    def __str__(self):
        return f"支付#{self.pk} {self.amount} {self.status}"


class CreditNote(OwnedModel):
    """信用票据（红字）：退款/补偿的凭证，可核销到发票或客户余额。"""

    number = models.CharField("票据编号", max_length=40)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name="credit_notes", verbose_name="客户")
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="credit_notes", verbose_name="关联发票")
    amount = models.DecimalField("金额", max_digits=16, decimal_places=2, default=Decimal("0"))
    currency = models.CharField("币种", max_length=8, default="CNY")
    reason = models.TextField("原因", blank=True, default="")
    status = models.CharField("状态", max_length=16, default="open",
                              choices=choices(CREDIT_NOTE_STATUS), db_index=True)
    applied_at = models.DateTimeField("核销时间", null=True, blank=True)
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "信用票据"
        verbose_name_plural = "信用票据"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "number"], name="billing_credit_note_uniq"),
        ]
        indexes = [models.Index(fields=["customer", "status"], name="billing_credit_cust_idx")]

    def __str__(self):
        return self.number


# ===========================================================================
# 五、优惠券
# ===========================================================================


class Coupon(OwnedModel):
    """优惠券：百分比或固定金额减免。

    ``duration`` 决定核销后影响几期：once 仅当前账单、repeating 连续 N 期、
    forever 永久。核销次数用 redeemed_count 冗余计数（列表页要展示余量，
    每次 count 聚合会拖慢列表），真源仍是 CouponRedemption。
    """

    code = models.CharField("优惠码", max_length=60)
    name = models.CharField("名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    coupon_type = models.CharField("类型", max_length=16, default="percent",
                                   choices=choices(COUPON_TYPES))
    percent = models.DecimalField("折扣百分比", max_digits=6, decimal_places=2,
                                  default=Decimal("0"))
    amount = models.DecimalField("固定减免", max_digits=16, decimal_places=2,
                                 default=Decimal("0"))
    currency = models.CharField("币种", max_length=8, default="CNY")
    duration = models.CharField("持续时间", max_length=16, default="once",
                                choices=choices(COUPON_DURATIONS))
    duration_months = models.IntegerField("持续期数", default=1)
    max_redemptions = models.IntegerField("最大核销次数", default=0)
    redeemed_count = models.IntegerField("已核销次数", default=0)
    valid_from = models.DateTimeField("生效时间", null=True, blank=True)
    valid_until = models.DateTimeField("失效时间", null=True, blank=True)
    status = models.CharField("状态", max_length=16, default="active",
                              choices=choices(COUPON_STATUS), db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="coupons", verbose_name="限定客户")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "优惠券"
        verbose_name_plural = "优惠券"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="billing_coupon_code_uniq"),
        ]
        indexes = [models.Index(fields=["status", "valid_until"], name="billing_coupon_idx")]

    def __str__(self):
        return self.code

    @property
    def remaining(self):
        """剩余可核销次数（0 表示不限）。"""
        if not self.max_redemptions:
            return 0
        return max(self.max_redemptions - self.redeemed_count, 0)


class CouponRedemption(OwnedModel):
    """优惠券核销记录：一次核销 = 一次减免事实，金额入账后不可改。"""

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE,
                               related_name="redemptions", verbose_name="优惠券")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name="coupon_redemptions", verbose_name="客户")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="coupon_redemptions", verbose_name="订阅")
    amount = models.DecimalField("抵扣金额", max_digits=16, decimal_places=2,
                                 default=Decimal("0"))
    currency = models.CharField("币种", max_length=8, default="CNY")
    idempotency_key = models.CharField("幂等键", max_length=120, blank=True, default="")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "优惠券核销"
        verbose_name_plural = "优惠券核销"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="billing_redemption_idem_uniq",
            ),
        ]
        indexes = [models.Index(fields=["coupon", "customer"], name="billing_redemption_idx")]

    def __str__(self):
        return f"{self.coupon_id}/{self.customer_id} {self.amount}"


# ===========================================================================
# 六、催收（Dunning）
# ===========================================================================


class DunningPolicy(OwnedModel):
    """催收策略：一组有序的催收步骤（逾期 D+3 通知、D+7 暂停、D+14 取消）。"""

    code = models.CharField("策略编码", max_length=60)
    name = models.CharField("策略名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField("状态", max_length=16, default="active")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "催收策略"
        verbose_name_plural = "催收策略"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="billing_dunning_policy_uniq"),
        ]

    def __str__(self):
        return f"{self.name}({self.code})"


class DunningStep(OwnedModel):
    """催收步骤：策略内的一个动作，delay_days 相对逾期起算日。

    sequence 唯一保证「第几步」不会出现并列，推进时只需按序取下一个。
    """

    policy = models.ForeignKey(DunningPolicy, on_delete=models.CASCADE,
                               related_name="steps", verbose_name="策略")
    sequence = models.IntegerField("序号", default=1)
    delay_days = models.IntegerField("延迟天数", default=0)
    action = models.CharField("动作", max_length=16, default="notify",
                              choices=choices(DUNNING_ACTIONS))
    template = models.TextField("通知模板", blank=True, default="")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "催收步骤"
        verbose_name_plural = "催收步骤"
        ordering = ["policy_id", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["policy", "sequence"], name="billing_dunning_step_uniq"),
        ]

    def __str__(self):
        return f"{self.policy_id}#{self.sequence} D+{self.delay_days} {self.action}"


class DunningRun(OwnedModel):
    """一次催收流程实例：记录当前走到第几步、下次重试时间与最终结果。"""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE,
                                     related_name="dunning_runs", verbose_name="订阅")
    policy = models.ForeignKey(DunningPolicy, on_delete=models.PROTECT,
                               related_name="runs", verbose_name="策略")
    status = models.CharField("状态", max_length=16, default="running",
                              choices=choices(DUNNING_RUN_STATUS), db_index=True)
    current_step = models.IntegerField("当前步骤序号", default=0)
    started_at = models.DateTimeField("开始时间")
    next_retry_at = models.DateTimeField("下次执行", null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    note = models.CharField("备注", max_length=200, blank=True, default="")
    metadata = models.JSONField("扩展信息", default=dict, blank=True)

    class Meta:
        verbose_name = "催收记录"
        verbose_name_plural = "催收记录"
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["status", "next_retry_at"], name="billing_dunning_due_idx"),
            models.Index(fields=["subscription", "status"], name="billing_dunning_sub_idx"),
        ]

    def __str__(self):
        return f"催收#{self.pk} 订阅{self.subscription_id} {self.status}"


# ===========================================================================
# 七、税率与事件
# ===========================================================================


class TaxRate(OwnedModel):
    """税率：按国家/地区与生效区间解析，税率存百分比（13 表示 13%）。

    存百分比而不是 0.13：财务录入与对账口径一致，减少「13 还是 0.13」的
    人工换算错误；换算集中在服务层 percent_amount。
    """

    country = models.CharField("国家/地区", max_length=8, default="CN")
    region = models.CharField("省/州", max_length=60, blank=True, default="")
    name = models.CharField("税种名称", max_length=120, default="增值税")
    rate = models.DecimalField("税率(%)", max_digits=7, decimal_places=4,
                               default=Decimal("0"))
    effective_from = models.DateField("生效起始", null=True, blank=True)
    effective_to = models.DateField("生效截止", null=True, blank=True)
    enabled = models.BooleanField("启用", default=True, db_index=True)
    is_default = models.BooleanField("默认税率", default=False)

    class Meta:
        verbose_name = "税率"
        verbose_name_plural = "税率"
        ordering = ["country", "region", "id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "country", "region", "name"],
                                    name="billing_tax_rate_uniq"),
        ]
        indexes = [models.Index(fields=["country", "region", "enabled"], name="billing_tax_lookup_idx")]

    def __str__(self):
        return f"{self.name} {self.rate}%"

    def covers(self, day):
        if not self.enabled:
            return False
        if self.effective_from and day < self.effective_from:
            return False
        if self.effective_to and day >= self.effective_to:
            return False
        return True


class BillingEvent(OwnedModel):
    """计费事件流水：状态变更、发票生成、支付、催收动作的审计轨迹。

    幂等键（如 ``invoice:12:generated``）让业务重试不会重复记账；事件写入
    与业务写在同一事务里，保证「有账必有据」。
    """

    event_type = models.CharField("事件类型", max_length=60, db_index=True)
    object_type = models.CharField("对象类型", max_length=40, blank=True, default="")
    object_id = models.IntegerField("对象 ID", null=True, blank=True)
    payload = models.JSONField("负载", default=dict, blank=True)
    idempotency_key = models.CharField("幂等键", max_length=160, blank=True, default="")
    status = models.CharField("处理状态", max_length=16, default="processed",
                              choices=choices(EVENT_STATUS), db_index=True)
    processed_at = models.DateTimeField("处理时间", null=True, blank=True)
    error = models.CharField("错误信息", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "计费事件"
        verbose_name_plural = "计费事件"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="billing_event_idem_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["event_type", "created_at"], name="billing_event_type_idx"),
            models.Index(fields=["object_type", "object_id"], name="billing_event_object_idx"),
        ]

    def __str__(self):
        return f"{self.event_type}#{self.object_id}"
