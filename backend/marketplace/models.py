# -*- coding: utf-8 -*-
"""应用市场 · 数据模型（19 张表）。

设计约定
--------
1. 所有业务模型统一带 ``owner`` 外键（行级权限收口，写权限走 core.scoping），
   并带 ``created_at`` / ``updated_at`` 便于审计与增量同步；
2. 所有 related_name 显式命名并统一加 ``mp_`` 前缀，避免与其他应用的反向名冲突；
3. 枚举用模块级常量（而不是只用 choices）：服务层要做集合判定（例如
   「可公开发布状态」「终态集合」），集中一处避免拼写漂移；
4. 模型只承载「数据 + 简单派生」，版本解析、依赖解析、许可证校验、评分聚合、
   收入分成等跨表计算全部放在 services.py，视图只做编排；
5. 本应用当前不提交迁移文件（迁移统一生成属于独立任务），测试库由 tests.py
   里的 ensure_marketplace_tables 幂等补建，不触碰开发库。

状态机总览
----------
- 发布者：pending（待认证）→ verified（已认证）→ suspended（已暂停，可恢复）
- 应用：draft → reviewing → published → suspended / delisted
  （驳回回到 draft，并记录 review_note）
- 版本：draft → published → delisted（已发布版本不物理删除）
- 安装：installed ⇄ disabled，installed/disabled → uninstalled（终态）
- 评价：pending → published → hidden（可恢复），隐藏后触发评分重算
- 购买：pending → paid → refunded / failed
- 许可证：active → expired（到期）/ revoked（撤销）
- 举报：pending → reviewing → resolved / dismissed
- 合集：draft → published
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

# 平台当前版本：安装解析与兼容性判断的基准值。
# 放在模型层是为了让服务层与视图层共用同一份默认值，避免两处写死漂移。
PLATFORM_VERSION = "3.8.0"

# ---------------------------------------------------------------------------
# 枚举常量
# ---------------------------------------------------------------------------

PUBLISHER_STATUS_CHOICES = [
    ("pending", "待认证"),
    ("verified", "已认证"),
    ("suspended", "已暂停"),
]
PUBLISHER_STATUS_VALUES = tuple(item[0] for item in PUBLISHER_STATUS_CHOICES)

LISTING_TYPE_CHOICES = [
    ("app", "应用"),
    ("plugin", "插件"),
    ("integration", "集成"),
    ("template", "模板"),
    ("theme", "主题"),
]
LISTING_TYPE_VALUES = tuple(item[0] for item in LISTING_TYPE_CHOICES)

LISTING_STATUS_CHOICES = [
    ("draft", "草稿"),
    ("reviewing", "审核中"),
    ("published", "已上架"),
    ("suspended", "已暂停"),
    ("delisted", "已下架"),
]
LISTING_STATUS_VALUES = tuple(item[0] for item in LISTING_STATUS_CHOICES)
# 只有这两个状态对普通登录用户可见：审核中的草稿提前曝光会绕过审核流程
LISTING_PUBLIC_STATUS = ("published",)
# 「可编辑」状态：审核中锁定，避免审核期间改内容导致审核结论与上架内容不一致
LISTING_EDITABLE_STATUS = ("draft", "delisted", "suspended")

PRICING_MODE_CHOICES = [
    ("free", "免费"),
    ("paid", "付费"),
    ("freemium", "免费增值"),
]
PRICING_MODE_VALUES = tuple(item[0] for item in PRICING_MODE_CHOICES)

VERSION_STATUS_CHOICES = [
    ("draft", "草稿"),
    ("published", "已发布"),
    ("delisted", "已下架"),
]
VERSION_STATUS_VALUES = tuple(item[0] for item in VERSION_STATUS_CHOICES)

INSTALL_STATUS_CHOICES = [
    ("installed", "已安装"),
    ("disabled", "已禁用"),
    ("uninstalled", "已卸载"),
]
INSTALL_STATUS_VALUES = tuple(item[0] for item in INSTALL_STATUS_CHOICES)
INSTALL_ACTIVE_STATUS = ("installed", "disabled")

REVIEW_STATUS_CHOICES = [
    ("pending", "待审"),
    ("published", "已发布"),
    ("hidden", "已隐藏"),
]
REVIEW_STATUS_VALUES = tuple(item[0] for item in REVIEW_STATUS_CHOICES)

PURCHASE_STATUS_CHOICES = [
    ("pending", "待支付"),
    ("paid", "已支付"),
    ("refunded", "已退款"),
    ("failed", "支付失败"),
]
PURCHASE_STATUS_VALUES = tuple(item[0] for item in PURCHASE_STATUS_CHOICES)

LICENSE_TYPE_CHOICES = [
    ("perpetual", "永久"),
    ("subscription", "订阅"),
    ("trial", "试用"),
]
LICENSE_TYPE_VALUES = tuple(item[0] for item in LICENSE_TYPE_CHOICES)

LICENSE_STATUS_CHOICES = [
    ("active", "有效"),
    ("expired", "已过期"),
    ("revoked", "已撤销"),
]
LICENSE_STATUS_VALUES = tuple(item[0] for item in LICENSE_STATUS_CHOICES)

WEBHOOK_STATUS_CHOICES = [
    ("active", "启用"),
    ("disabled", "停用"),
]

EVENT_STATUS_CHOICES = [
    ("pending", "待处理"),
    ("processed", "已处理"),
    ("failed", "处理失败"),
]
EVENT_STATUS_VALUES = tuple(item[0] for item in EVENT_STATUS_CHOICES)

COLLECTION_STATUS_CHOICES = [
    ("draft", "草稿"),
    ("published", "已发布"),
]
COLLECTION_STATUS_VALUES = tuple(item[0] for item in COLLECTION_STATUS_CHOICES)

REPORT_STATUS_CHOICES = [
    ("pending", "待处理"),
    ("reviewing", "处理中"),
    ("resolved", "已处置"),
    ("dismissed", "已驳回"),
]
REPORT_STATUS_VALUES = tuple(item[0] for item in REPORT_STATUS_CHOICES)
# 举报状态机的合法流转（服务层 transition_report 使用）
REPORT_TRANSITIONS = {
    "pending": ("reviewing", "dismissed"),
    "reviewing": ("resolved", "dismissed"),
    "resolved": (),
    "dismissed": (),
}

REPORT_REASON_CHOICES = [
    ("malware", "恶意代码"),
    ("copyright", "侵权"),
    ("spam", "垃圾/误导"),
    ("broken", "无法使用"),
    ("other", "其他"),
]

CURRENCY_CHOICES = [
    ("CNY", "人民币"),
    ("USD", "美元"),
    ("EUR", "欧元"),
]

# 平台默认分成比例（发布者拿 70%）；发布者可单独设置 revenue_share 覆盖。
PLATFORM_DEFAULT_PUBLISHER_SHARE = Decimal("70.00")

# 免费/试用/订阅的默认试用天数
DEFAULT_TRIAL_DAYS = 14


class MarketplaceBase(models.Model):
    """市场通用字段：owner + 时间戳 + 备注（抽象基类，不建表）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="%(class)s_owned", verbose_name="所有者")
    remark = models.TextField("备注", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"#{self.pk} {self.__class__.__name__}"


class Publisher(MarketplaceBase):
    """发布者（开发者/厂商）：认证、暂停与分成结算是收入计算的前提。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_publishers", verbose_name="账号所有者")
    name = models.CharField("发布者名称", max_length=120)
    slug = models.SlugField("标识", max_length=80, unique=True)
    summary = models.CharField("简介", max_length=500, blank=True, default="")
    website = models.CharField("官网", max_length=300, blank=True, default="")
    contact_email = models.CharField("联系邮箱", max_length=200, blank=True, default="")
    status = models.CharField("状态", max_length=20, choices=PUBLISHER_STATUS_CHOICES,
                              default="pending", db_index=True)
    # 发布者分成比例（百分比，0-100），平台收入 = 流水 × (100 - revenue_share)%
    revenue_share = models.DecimalField("分成比例%", max_digits=5, decimal_places=2,
                                        default=PLATFORM_DEFAULT_PUBLISHER_SHARE)
    settlement_info = models.JSONField("结算信息", default=dict, blank=True)
    verified_at = models.DateTimeField("认证时间", null=True, blank=True)
    suspended_reason = models.CharField("暂停原因", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "发布者"
        verbose_name_plural = "发布者"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="mp_publisher_status_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.slug})"


class Category(MarketplaceBase):
    """应用分类：支持两级以上树形结构，删除前必须为空（服务层校验）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_categories", verbose_name="创建人")
    code = models.SlugField("编码", max_length=60, unique=True)
    name = models.CharField("名称", max_length=80)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="mp_children", verbose_name="上级分类")
    order = models.IntegerField("排序", default=0, db_index=True)
    icon = models.CharField("图标", max_length=120, blank=True, default="")
    active = models.BooleanField("启用", default=True, db_index=True)
    description = models.CharField("描述", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "应用分类"
        verbose_name_plural = "应用分类"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["parent", "order"], name="mp_category_tree_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.code})"


class Listing(MarketplaceBase):
    """应用（含插件/集成/模板/主题）主表。

    ``rating`` / ``install_count`` / ``latest_version`` 是冗余聚合字段：
    列表与搜索每次实时聚合代价高，写入路径（评价/安装/发版）负责维护，
    并提供 services.aggregate_rating 等函数做可重复的全量重算。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_listings", verbose_name="维护人")
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE,
                                  related_name="mp_publisher_listings", verbose_name="发布者")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="mp_category_listings", verbose_name="分类")
    code = models.SlugField("应用标识", max_length=100, unique=True)
    name = models.CharField("应用名称", max_length=200)
    summary = models.CharField("一句话简介", max_length=500, blank=True, default="")
    description = models.TextField("详细介绍", blank=True, default="")
    icon = models.CharField("图标", max_length=300, blank=True, default="")
    type = models.CharField("类型", max_length=20, choices=LISTING_TYPE_CHOICES,
                            default="app", db_index=True)
    status = models.CharField("状态", max_length=20, choices=LISTING_STATUS_CHOICES,
                              default="draft", db_index=True)
    pricing_mode = models.CharField("定价模式", max_length=20, choices=PRICING_MODE_CHOICES,
                                    default="free", db_index=True)
    latest_version = models.ForeignKey("ListingVersion", null=True, blank=True,
                                       on_delete=models.SET_NULL,
                                       related_name="mp_latest_for_listings",
                                       verbose_name="最新版本")
    rating = models.DecimalField("评分", max_digits=3, decimal_places=2, default=0)
    rating_count = models.IntegerField("评分人数", default=0)
    install_count = models.IntegerField("安装量", default=0)
    featured = models.BooleanField("推荐位", default=False, db_index=True)
    featured_rank = models.IntegerField("推荐排序", default=0)
    tags = models.JSONField("标签", default=list, blank=True)
    audit = models.JSONField("审核记录", default=dict, blank=True)
    submitted_at = models.DateTimeField("提交审核时间", null=True, blank=True)
    published_at = models.DateTimeField("上架时间", null=True, blank=True)
    delisted_at = models.DateTimeField("下架时间", null=True, blank=True)
    review_note = models.TextField("审核意见", blank=True, default="")

    class Meta:
        verbose_name = "应用"
        verbose_name_plural = "应用"
        ordering = ["-featured", "-install_count", "-created_at"]
        indexes = [
            models.Index(fields=["status", "type"], name="mp_listing_status_type_idx"),
            models.Index(fields=["publisher", "status"], name="mp_listing_pub_status_idx"),
            models.Index(fields=["category", "status"], name="mp_listing_cat_status_idx"),
            models.Index(fields=["-install_count"], name="mp_listing_installs_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.code})"


class ListingVersion(MarketplaceBase):
    """应用版本：语义化版本 + 兼容平台下限 + 依赖清单（manifest）。

    manifest 结构约定：
        {"requires": [{"code": "dep.plugin", "range": ">=1.2.0"}],
         "platform": ">=3.0.0", "permissions": [...], "entry": "main.js"}
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_listing_versions", verbose_name="提交人")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_versions", verbose_name="应用")
    version = models.CharField("版本号", max_length=40)
    changelog = models.TextField("变更说明", blank=True, default="")
    min_platform_version = models.CharField("平台版本下限", max_length=40, default="3.0.0")
    manifest = models.JSONField("清单", default=dict, blank=True)
    package_size = models.BigIntegerField("包大小(字节)", default=0)
    checksum = models.CharField("校验和", max_length=128, blank=True, default="")
    status = models.CharField("状态", max_length=20, choices=VERSION_STATUS_CHOICES,
                              default="draft", db_index=True)
    breaking = models.BooleanField("破坏性变更", default=False)
    download_count = models.IntegerField("下载量", default=0)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "应用版本"
        verbose_name_plural = "应用版本"
        ordering = ["-published_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["listing", "version"],
                                    name="mp_listing_version_uniq"),
        ]
        indexes = [
            models.Index(fields=["listing", "status"], name="mp_version_listing_status_idx"),
        ]

    def __str__(self):
        return f"{self.listing.code}@{self.version}"


class Install(MarketplaceBase):
    """安装记录：一个用户对同一应用只保留一条（重新安装复用记录）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_installs", verbose_name="安装者")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_installs", verbose_name="应用")
    version = models.ForeignKey(ListingVersion, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="mp_installs", verbose_name="版本")
    status = models.CharField("状态", max_length=20, choices=INSTALL_STATUS_CHOICES,
                              default="installed", db_index=True)
    config = models.JSONField("配置", default=dict, blank=True)
    auto_update = models.BooleanField("自动更新", default=False)
    installed_at = models.DateTimeField("安装时间", default=timezone.now)
    uninstalled_at = models.DateTimeField("卸载时间", null=True, blank=True)
    last_upgraded_at = models.DateTimeField("最近升级", null=True, blank=True)

    class Meta:
        verbose_name = "安装记录"
        verbose_name_plural = "安装记录"
        ordering = ["-installed_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "listing"], name="mp_install_owner_listing_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="mp_install_owner_status_idx"),
            models.Index(fields=["listing", "status"], name="mp_install_listing_status_idx"),
        ]

    def __str__(self):
        return f"{self.owner_id}->{self.listing.code}[{self.status}]"


class Review(MarketplaceBase):
    """用户评价：同一用户对同一应用只能有一条；隐藏后重新聚合评分。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_reviews", verbose_name="评价人")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_reviews", verbose_name="应用")
    rating = models.IntegerField("评分", default=5)
    title = models.CharField("标题", max_length=200, blank=True, default="")
    content = models.TextField("内容", blank=True, default="")
    status = models.CharField("状态", max_length=20, choices=REVIEW_STATUS_CHOICES,
                              default="pending", db_index=True)
    reply_count = models.IntegerField("回复数", default=0)
    helpful_count = models.IntegerField("有用数", default=0)
    verified_purchase = models.BooleanField("已购买", default=False)
    hidden_reason = models.CharField("隐藏原因", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "评价"
        verbose_name_plural = "评价"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "listing"], name="mp_review_owner_listing_uniq"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5),
                                   name="mp_review_rating_range"),
        ]
        indexes = [
            models.Index(fields=["listing", "status"], name="mp_review_listing_status_idx"),
        ]

    def __str__(self):
        return f"{self.listing.code} {self.rating}星"


class ReviewReply(MarketplaceBase):
    """评价回复：发布者或管理员回复，回复数冗余在 Review.reply_count。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_review_replies", verbose_name="回复人")
    review = models.ForeignKey(Review, on_delete=models.CASCADE,
                               related_name="mp_replies", verbose_name="评价")
    content = models.TextField("回复内容", blank=True, default="")

    class Meta:
        verbose_name = "评价回复"
        verbose_name_plural = "评价回复"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["review", "created_at"], name="mp_reply_review_idx"),
        ]

    def __str__(self):
        return f"reply#{self.pk}->review#{self.review_id}"


class ReviewHelpful(MarketplaceBase):
    """「有用」投票：一人一票，避免刷票；计数冗余在 Review.helpful_count。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_review_helpfuls", verbose_name="投票人")
    review = models.ForeignKey(Review, on_delete=models.CASCADE,
                               related_name="mp_helpfuls", verbose_name="评价")

    class Meta:
        verbose_name = "评价有用票"
        verbose_name_plural = "评价有用票"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "review"], name="mp_review_helpful_uniq"),
        ]

    def __str__(self):
        return f"helpful#{self.pk}"


class Pricing(MarketplaceBase):
    """定价：一个应用一份有效定价（OneToOne），修改即覆盖，保留 audit 记录。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_pricings", verbose_name="维护人")
    listing = models.OneToOneField(Listing, on_delete=models.CASCADE,
                                   related_name="mp_pricing", verbose_name="应用")
    mode = models.CharField("模式", max_length=20, choices=PRICING_MODE_CHOICES, default="free")
    price = models.DecimalField("价格", max_digits=10, decimal_places=2, default=0)
    currency = models.CharField("币种", max_length=8, choices=CURRENCY_CHOICES, default="CNY")
    trial_days = models.IntegerField("试用天数", default=0)
    period = models.CharField("周期", max_length=20, default="one_time")
    active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "定价"
        verbose_name_plural = "定价"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.listing.code} {self.price} {self.currency}"


class Purchase(MarketplaceBase):
    """购买订单：支付状态机 pending → paid → refunded / failed，退款冲减收入。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_purchases", verbose_name="购买者")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_purchases", verbose_name="应用")
    version = models.ForeignKey(ListingVersion, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="mp_purchases", verbose_name="购买版本")
    order_no = models.CharField("订单号", max_length=48, unique=True)
    price = models.DecimalField("成交价", max_digits=10, decimal_places=2, default=0)
    currency = models.CharField("币种", max_length=8, default="CNY")
    payment_status = models.CharField("支付状态", max_length=20,
                                      choices=PURCHASE_STATUS_CHOICES,
                                      default="pending", db_index=True)
    channel = models.CharField("支付渠道", max_length=30, blank=True, default="local")
    purchased_at = models.DateTimeField("购买时间", null=True, blank=True)
    refunded_at = models.DateTimeField("退款时间", null=True, blank=True)
    refund_amount = models.DecimalField("退款金额", max_digits=10, decimal_places=2, default=0)
    invoice = models.JSONField("发票信息", default=dict, blank=True)

    class Meta:
        verbose_name = "购买订单"
        verbose_name_plural = "购买订单"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "payment_status"], name="mp_purchase_owner_status_idx"),
            models.Index(fields=["listing", "payment_status"], name="mp_purchase_listing_idx"),
        ]

    def __str__(self):
        return f"{self.order_no} {self.payment_status}"


class License(MarketplaceBase):
    """许可证：只存密钥哈希（不可逆），明文仅在签发时返回一次。

    激活信息放 JSON 列表 ``activations``（[{device_id, at, meta}]），
    激活上限由 ``max_activations`` 控制，校验时同时检查有效期与应用一致性。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_licenses", verbose_name="被授权人")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_licenses", verbose_name="应用")
    purchase = models.OneToOneField(Purchase, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="mp_license", verbose_name="订单")
    key_hash = models.CharField("密钥哈希", max_length=128, db_index=True)
    key_hint = models.CharField("密钥提示", max_length=32, blank=True, default="")
    type = models.CharField("类型", max_length=20, choices=LICENSE_TYPE_CHOICES,
                            default="perpetual")
    expires_at = models.DateTimeField("到期时间", null=True, blank=True)
    status = models.CharField("状态", max_length=20, choices=LICENSE_STATUS_CHOICES,
                              default="active", db_index=True)
    max_activations = models.IntegerField("激活次数上限", default=3)
    activations = models.JSONField("激活设备", default=list, blank=True)
    last_verified_at = models.DateTimeField("最后校验", null=True, blank=True)
    revoked_reason = models.CharField("撤销原因", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "许可证"
        verbose_name_plural = "许可证"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="mp_license_owner_status_idx"),
            models.Index(fields=["listing", "status"], name="mp_license_listing_idx"),
        ]

    def __str__(self):
        return f"lic#{self.pk} {self.listing.code} {self.type}"


class WebhookSubscription(MarketplaceBase):
    """发布者 Webhook：事件订阅 + 本地模拟投递（不联网）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_webhook_subscriptions", verbose_name="创建人")
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE,
                                  related_name="mp_webhooks", verbose_name="发布者")
    listing = models.ForeignKey(Listing, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="mp_webhooks", verbose_name="应用")
    url = models.CharField("回调地址", max_length=500)
    events = models.JSONField("事件类型", default=list, blank=True)
    secret = models.CharField("签名密钥", max_length=120, blank=True, default="")
    status = models.CharField("状态", max_length=20, choices=WEBHOOK_STATUS_CHOICES,
                              default="active", db_index=True)
    last_delivery_at = models.DateTimeField("最近投递", null=True, blank=True)
    last_status = models.IntegerField("最近响应码", default=0)
    failure_count = models.IntegerField("累计失败", default=0)

    class Meta:
        verbose_name = "Webhook 订阅"
        verbose_name_plural = "Webhook 订阅"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["publisher", "status"], name="mp_webhook_pub_status_idx"),
        ]

    def __str__(self):
        return f"hook#{self.pk} {self.url}"


class WebhookDelivery(MarketplaceBase):
    """Webhook 投递记录：模拟投递的结果用于列表与排障。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_webhook_deliveries", verbose_name="所属账号")
    subscription = models.ForeignKey(WebhookSubscription, on_delete=models.CASCADE,
                                     related_name="mp_deliveries", verbose_name="订阅")
    event_type = models.CharField("事件类型", max_length=60)
    payload = models.JSONField("负载", default=dict, blank=True)
    response_status = models.IntegerField("响应码", default=200)
    response_body = models.CharField("响应摘要", max_length=500, blank=True, default="")
    success = models.BooleanField("成功", default=True)
    attempt = models.IntegerField("尝试次数", default=1)
    delivered_at = models.DateTimeField("投递时间", default=timezone.now)

    class Meta:
        verbose_name = "Webhook 投递"
        verbose_name_plural = "Webhook 投递"
        ordering = ["-delivered_at"]
        indexes = [
            models.Index(fields=["subscription", "-delivered_at"], name="mp_delivery_sub_idx"),
        ]

    def __str__(self):
        return f"delivery#{self.pk} {self.event_type} {self.response_status}"


class MarketplaceEvent(MarketplaceBase):
    """市场事件：幂等键去重，状态记录本地处理结果（安装/购买/评价等）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_events", verbose_name="触发人")
    listing = models.ForeignKey(Listing, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="mp_events", verbose_name="应用")
    event_type = models.CharField("事件类型", max_length=60, db_index=True)
    payload = models.JSONField("负载", default=dict, blank=True)
    idempotency_key = models.CharField("幂等键", max_length=120, unique=True, blank=True,
                                       null=True)
    status = models.CharField("状态", max_length=20, choices=EVENT_STATUS_CHOICES,
                              default="pending", db_index=True)
    attempts = models.IntegerField("尝试次数", default=0)
    error = models.CharField("错误", max_length=500, blank=True, default="")
    processed_at = models.DateTimeField("处理时间", null=True, blank=True)

    class Meta:
        verbose_name = "市场事件"
        verbose_name_plural = "市场事件"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "status"], name="mp_event_type_status_idx"),
        ]

    def __str__(self):
        return f"{self.event_type}#{self.pk}[{self.status}]"


class Collection(MarketplaceBase):
    """合集：运营侧的应用清单，草稿态不对外；发布后按条目顺序展示。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_collections", verbose_name="创建人")
    slug = models.SlugField("标识", max_length=100, unique=True)
    title = models.CharField("标题", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    cover = models.CharField("封面", max_length=300, blank=True, default="")
    order = models.IntegerField("排序", default=0, db_index=True)
    status = models.CharField("状态", max_length=20, choices=COLLECTION_STATUS_CHOICES,
                              default="draft", db_index=True)
    featured = models.BooleanField("推荐", default=False)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "合集"
        verbose_name_plural = "合集"
        ordering = ["order", "-created_at"]
        indexes = [
            models.Index(fields=["status", "order"], name="mp_collection_status_idx"),
        ]

    def __str__(self):
        return f"{self.title}({self.slug})"


class CollectionItem(MarketplaceBase):
    """合集条目：同一合集内同一应用只能出现一次（排序去重的数据层兜底）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_collection_items", verbose_name="创建人")
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE,
                                   related_name="mp_items", verbose_name="合集")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_collection_items", verbose_name="应用")
    order = models.IntegerField("排序", default=0, db_index=True)

    class Meta:
        verbose_name = "合集条目"
        verbose_name_plural = "合集条目"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["collection", "listing"],
                                    name="mp_collection_listing_uniq"),
        ]
        indexes = [
            models.Index(fields=["collection", "order"], name="mp_collection_item_order_idx"),
        ]

    def __str__(self):
        return f"{self.collection.slug}#{self.order} {self.listing.code}"


class ListingReport(MarketplaceBase):
    """举报：状态机 pending → reviewing → resolved / dismissed。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_reports", verbose_name="举报人")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_reports", verbose_name="应用")
    reason = models.CharField("原因", max_length=30, choices=REPORT_REASON_CHOICES,
                              default="other")
    detail = models.TextField("详细说明", blank=True, default="")
    evidence = models.JSONField("证据", default=list, blank=True)
    status = models.CharField("状态", max_length=20, choices=REPORT_STATUS_CHOICES,
                              default="pending", db_index=True)
    resolution = models.TextField("处理结论", blank=True, default="")
    handled_at = models.DateTimeField("处理时间", null=True, blank=True)

    class Meta:
        verbose_name = "应用举报"
        verbose_name_plural = "应用举报"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="mp_report_status_idx"),
        ]

    def __str__(self):
        return f"report#{self.pk} {self.listing.code} [{self.status}]"


class Screenshot(MarketplaceBase):
    """应用截图：文件元数据（不落地存储），order 控制展示顺序。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_screenshots", verbose_name="上传人")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_screenshots", verbose_name="应用")
    file_name = models.CharField("文件名", max_length=255)
    file_url = models.CharField("文件地址", max_length=500)
    mime_type = models.CharField("MIME", max_length=80, default="image/png")
    file_size = models.BigIntegerField("文件大小", default=0)
    width = models.IntegerField("宽", default=0)
    height = models.IntegerField("高", default=0)
    order = models.IntegerField("排序", default=0, db_index=True)
    caption = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "应用截图"
        verbose_name_plural = "应用截图"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["listing", "order"], name="mp_screenshot_order_idx"),
        ]

    def __str__(self):
        return f"{self.listing.code}#{self.order} {self.file_name}"


class CompatibilityTag(MarketplaceBase):
    """兼容性标签：声明某应用在某个平台版本上已验证（如 3.8.0 + 「已验证」）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mp_compat_tags", verbose_name="维护人")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE,
                                related_name="mp_compat_tags", verbose_name="应用")
    platform_version = models.CharField("平台版本", max_length=40)
    tag = models.CharField("标签", max_length=40, default="verified")
    note = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "兼容标签"
        verbose_name_plural = "兼容标签"
        ordering = ["platform_version", "tag"]
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "platform_version", "tag"],
                name="mp_compat_listing_version_tag_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["listing", "platform_version"], name="mp_compat_listing_idx"),
        ]

    def __str__(self):
        return f"{self.listing.code} {self.platform_version} {self.tag}"
