# -*- coding: utf-8 -*-
"""contracts 模型层：合同全生命周期 20 张表（模板 / 条款 / 主体 / 履约 / 财务 / 风险）。

设计约定（与平台其他应用一致）：
- 每张表统一挂 owner 外键（负责人 / 创建人），行级权限由 core.scoping 收口，
  模型层不再自造权限字段，避免「读范围」与「写权限」混淆；
- 每张表都带 created_at / updated_at：合同类数据是审计对象，任何一条都要求可回放；
- 金额一律 DecimalField(18, 2)，禁止 float：合同金额参与累计、对账与违约计算，
  浮点误差会在多期付款后放大成「差一分钱」的脏账；
- related_name 全部手工命名并统一 ct_ 前缀：一个用户会关联十几种合同对象，
  默认的 %(class)s_set 在跨应用聚合时容易撞名，显式命名让反向查询稳定可读；
- 结构化扩展（模板变量、标签、签章元数据）用 JSONField，避免为每种形态加列，
  但**状态机字段一律用 CharField + 显式枚举**，保证非法流转能在服务层被拦截；
- 唯一约束尽量下沉到数据库：排期/付款期次/提醒去重都靠唯一键兜底，
  并发场景下「先查再写」必然有竞态，只有唯一约束能真正保证幂等。
"""
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# 枚举常量：视图、服务与前端目录共用，集中定义避免字符串各写各的
# ---------------------------------------------------------------------------

CONTRACT_STATUS = (
    "draft", "reviewing", "approved", "signing",
    "active", "expiring", "expired", "terminated", "completed", "archived",
)
CONTRACT_STATUS_LABELS = {
    "draft": "草稿",
    "reviewing": "审批中",
    "approved": "已批准",
    "signing": "签署中",
    "active": "履行中",
    "expiring": "即将到期",
    "expired": "已到期",
    "terminated": "已终止",
    "completed": "已完成",
    "archived": "已归档",
}

CONTRACT_TYPES = ("purchase", "sales", "service", "lease", "labor", "nda")
CONTRACT_TYPE_LABELS = {
    "purchase": "采购合同",
    "sales": "销售合同",
    "service": "服务合同",
    "lease": "租赁合同",
    "labor": "劳务合同",
    "nda": "保密协议",
}

# 类型权重：租赁/劳务的履约不确定性与用工合规风险高于普通买卖与保密协议
CONTRACT_TYPE_WEIGHT = {
    "purchase": 10,
    "sales": 8,
    "service": 12,
    "lease": 15,
    "labor": 18,
    "nda": 5,
}

RENEWAL_MODES = ("none", "auto", "manual", "negotiated")
RENEWAL_MODE_LABELS = {
    "none": "不续约",
    "auto": "自动续约",
    "manual": "人工续约",
    "negotiated": "协商续约",
}

PARTY_ROLES = ("party_a", "party_b", "party_c")
PARTY_ROLE_LABELS = {"party_a": "甲方", "party_b": "乙方", "party_c": "丙方"}

PARTY_TYPES = ("company", "person", "government")
PARTY_TYPE_LABELS = {"company": "企业", "person": "自然人", "government": "政府机构"}

OBLIGATION_CYCLES = ("once", "monthly", "quarterly", "yearly")
OBLIGATION_CYCLE_LABELS = {
    "once": "一次性",
    "monthly": "每月",
    "quarterly": "每季",
    "yearly": "每年",
}
OBLIGATION_STATUS = ("pending", "doing", "done", "overdue", "waived")
OBLIGATION_STATUS_LABELS = {
    "pending": "待履行",
    "doing": "履行中",
    "done": "已完成",
    "overdue": "已逾期",
    "waived": "已豁免",
}

OBLIGATION_EVENT_ACTIONS = ("complete", "postpone", "waive", "reopen")
OBLIGATION_EVENT_ACTION_LABELS = {
    "complete": "完成",
    "postpone": "延期",
    "waive": "豁免",
    "reopen": "重新打开",
}

MILESTONE_STATUS = ("planned", "doing", "achieved", "missed")
MILESTONE_STATUS_LABELS = {
    "planned": "未开始",
    "doing": "进行中",
    "achieved": "已达成",
    "missed": "未达成",
}

AMENDMENT_TYPES = ("clause", "amount", "date", "party", "scope", "other")
AMENDMENT_TYPE_LABELS = {
    "clause": "条款变更",
    "amount": "金额变更",
    "date": "期限变更",
    "party": "主体变更",
    "scope": "范围变更",
    "other": "其他",
}
AMENDMENT_STATUS = ("draft", "submitted", "approved", "rejected", "effective")
AMENDMENT_STATUS_LABELS = {
    "draft": "草稿",
    "submitted": "待审批",
    "approved": "已批准",
    "rejected": "已驳回",
    "effective": "已生效",
}

APPROVAL_DECISIONS = ("pending", "approved", "rejected", "skipped")
APPROVAL_DECISION_LABELS = {
    "pending": "待审批",
    "approved": "同意",
    "rejected": "驳回",
    "skipped": "跳过",
}

SIGNATURE_METHODS = ("electronic", "seal", "handwritten", "scan")
SIGNATURE_METHOD_LABELS = {
    "electronic": "电子签",
    "seal": "印章",
    "handwritten": "手写签名",
    "scan": "扫描件",
}
SIGNATURE_STATUS = ("pending", "signed", "refused", "revoked")
SIGNATURE_STATUS_LABELS = {
    "pending": "待签署",
    "signed": "已签署",
    "refused": "已拒签",
    "revoked": "已撤销",
}

PAYMENT_STATUS = ("planned", "partial", "paid", "overdue", "cancelled")
PAYMENT_STATUS_LABELS = {
    "planned": "计划中",
    "partial": "部分收款",
    "paid": "已结清",
    "overdue": "已逾期",
    "cancelled": "已取消",
}

RISK_LEVELS = ("low", "medium", "high", "critical")
RISK_LEVEL_LABELS = {"low": "低", "medium": "中", "high": "高", "critical": "严重"}
# 风险分权重：严重风险项对总分贡献是低风险的 5 倍，避免「一堆小风险」掩盖重大风险
RISK_LEVEL_WEIGHT = {"low": 3, "medium": 8, "high": 15, "critical": 25}

RISK_STATUS = ("open", "mitigated", "accepted", "closed")
RISK_STATUS_LABELS = {
    "open": "待处理",
    "mitigated": "已缓解",
    "accepted": "已接受",
    "closed": "已关闭",
}

RENEWAL_TYPES = ("auto", "manual", "renegotiate", "terminate")
RENEWAL_TYPE_LABELS = {
    "auto": "自动续约",
    "manual": "人工续约",
    "renegotiate": "重新谈判",
    "terminate": "到期终止",
}
RENEWAL_STATUS = ("pending", "confirmed", "declined", "expired")
RENEWAL_STATUS_LABELS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "declined": "已放弃",
    "expired": "已失效",
}

TEMPLATE_STATUS = ("draft", "published", "disabled")
TEMPLATE_STATUS_LABELS = {"draft": "草稿", "published": "已发布", "disabled": "已停用"}

REMINDER_KINDS = ("expiry", "renewal", "obligation", "payment", "approval")
REMINDER_KIND_LABELS = {
    "expiry": "到期提醒",
    "renewal": "续约提醒",
    "obligation": "履约提醒",
    "payment": "付款提醒",
    "approval": "审批提醒",
}
REMINDER_CHANNELS = ("inapp", "email", "sms", "wecom")
REMINDER_CHANNEL_LABELS = {
    "inapp": "站内信",
    "email": "邮件",
    "sms": "短信",
    "wecom": "企业微信",
}
REMINDER_STATUS = ("sent", "read", "failed")
REMINDER_STATUS_LABELS = {"sent": "已发送", "read": "已读", "failed": "发送失败"}

ATTACHMENT_KINDS = ("contract", "attachment", "evidence", "invoice", "other")
ATTACHMENT_KIND_LABELS = {
    "contract": "合同正文",
    "attachment": "附件",
    "evidence": "履约证据",
    "invoice": "发票",
    "other": "其他",
}

CURRENCIES = ("CNY", "USD", "EUR", "HKD", "JPY")
CURRENCY_LABELS = {
    "CNY": "人民币",
    "USD": "美元",
    "EUR": "欧元",
    "HKD": "港币",
    "JPY": "日元",
}

# 到期提醒的分段阈值（天）：30/15/7/1 四档覆盖「月度摸底 + 周提醒 + 临期 + 最后通牒」
EXPIRY_REMIND_STAGES = (30, 15, 7, 1)

AUDIT_ACTIONS = (
    "create", "update", "submit", "approve", "reject", "sign", "activate",
    "expire", "terminate", "complete", "archive", "clone", "rollback",
    "obligation", "payment", "renewal", "risk", "reminder",
)
AUDIT_ACTION_LABELS = {
    "create": "创建",
    "update": "更新",
    "submit": "提交审批",
    "approve": "审批通过",
    "reject": "审批驳回",
    "sign": "发起签署",
    "activate": "生效",
    "expire": "标记到期",
    "terminate": "终止",
    "complete": "完成",
    "archive": "归档",
    "clone": "克隆",
    "rollback": "版本回滚",
    "obligation": "履约变更",
    "payment": "付款变更",
    "renewal": "续约变更",
    "risk": "风险变更",
    "reminder": "提醒扫描",
}


def _money_default():
    """Decimal 默认值必须显式给 Decimal，不能给 0（int 会被驱动转成 float）。"""
    return Decimal("0.00")


def to_decimal(value, field="金额"):
    """把任意入参安全转成两位小数 Decimal；非数字直接抛中文错误。

    合同金额来自 JSON / 表单，可能是 "1000.5"、"1,000" 或 None。
    统一在这里收口，避免把 float 直接写进 DecimalField 造成精度漂移。
    """
    if value in (None, ""):
        return Decimal("0.00")
    try:
        raw = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} 必须是数字")
    if not raw.is_finite():
        raise ValueError(f"{field} 必须是有限数字")
    return raw.quantize(Decimal("0.01"))


def gen_series_uid(prefix="series"):
    """生成排期唯一串：根义务的 uid 参与唯一约束，重复生成才能被数据库拦住。"""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class ContractBase(models.Model):
    """合同域公共字段：owner + 时间戳。

    注意：owner 一律显式指定 related_name（子类用 ct_ 前缀），
    这里不提供默认值，避免 %(class)s_set 在跨应用聚合时重名。
    """

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def touch(self):
        """显式刷新 updated_at：批量 update_fields 时必须带上它，否则时间戳不走。"""
        self.updated_at = timezone.now()
        return self.updated_at


# ---------------------------------------------------------------------------
# 模板与条款
# ---------------------------------------------------------------------------


class ContractTemplate(ContractBase):
    """合同模板：正文 + 变量定义 + 版本，是起草合同的起点。

    variables 存 [{name, label, required, default}]，渲染时只允许这里声明的
    变量（白名单），防止用户把任意上下文（如 request 对象）渲染进正文。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_templates", verbose_name="创建人")
    code = models.CharField("模板编码", max_length=60, db_index=True)
    name = models.CharField("模板名称", max_length=200)
    template_type = models.CharField("合同类型", max_length=20, default="service")
    scene = models.CharField("适用场景", max_length=120, blank=True, default="")
    body = models.TextField("模板正文", blank=True, default="")
    variables = models.JSONField("变量定义", default=list, blank=True)
    version = models.CharField("版本号", max_length=20, default="v1.0")
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "合同模板"
        verbose_name_plural = "合同模板"
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"],
                                    name="ctm_template_owner_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="ctm_tpl_owner_status_idx"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def variable_names(self):
        """返回模板声明的变量名集合（支持 ["a"] 与 [{name: "a"}] 两种历史形态）。"""
        names = set()
        for item in self.variables or []:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                names.add(name)
        return names

    def required_variables(self):
        """必填变量名：渲染预览时缺这些必须报错，可选变量允许走默认值。"""
        names = []
        for item in self.variables or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name and item.get("required", True):
                names.append(name)
        return names

    def publish(self):
        """发布模板：只有 published 状态可被关联到新合同（服务层据此拦截）。"""
        self.status = "published"
        self.touch()
        self.save(update_fields=["status", "updated_at"])


class ClauseLibrary(ContractBase):
    """标准条款库：可复用条款，按分类/风险等级/适用法域检索。

    条款库与模板条款（Clause）是「定义」与「实例」的关系：
    库里的条款改了不影响已实例化到模板里的正文，避免历史合同被追溯篡改。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_clause_library", verbose_name="创建人")
    category = models.CharField("条款分类", max_length=40, default="通用", db_index=True)
    title = models.CharField("条款标题", max_length=200)
    body = models.TextField("条款正文", blank=True, default="")
    risk_level = models.CharField("风险等级", max_length=20, default="low", db_index=True)
    jurisdiction = models.CharField("适用法域", max_length=40, default="CN")
    tags = models.JSONField("标签", default=list, blank=True)
    status = models.CharField("状态", max_length=20, default="active")
    usage_count = models.IntegerField("引用次数", default=0)
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "标准条款"
        verbose_name_plural = "标准条款"
        indexes = [
            models.Index(fields=["owner", "category"], name="ctm_clause_owner_cat_idx"),
        ]

    def __str__(self):
        return f"[{self.category}] {self.title}"

    def mark_used(self):
        """引用计数：用 F 表达式自增，避免并发下「读到旧值再写」丢计数。"""
        ClauseLibrary.objects.filter(pk=self.pk).update(
            usage_count=models.F("usage_count") + 1)
        self.refresh_from_db(fields=["usage_count"])


class Clause(ContractBase):
    """模板内条款实例：有排序、可选标记与替代组。

    alt_group 非空表示同组条款互斥（如「仲裁」与「诉讼」二选一），
    合同起草时同组只能保留一条，冲突检测在服务层做。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_clauses", verbose_name="创建人")
    template = models.ForeignKey(ContractTemplate, on_delete=models.CASCADE,
                                 related_name="clauses", verbose_name="所属模板")
    library = models.ForeignKey(ClauseLibrary, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="clause_instances",
                                verbose_name="来源条款")
    title = models.CharField("条款标题", max_length=200)
    body = models.TextField("条款正文", blank=True, default="")
    order = models.IntegerField("排序", default=0)
    optional = models.BooleanField("可选条款", default=False)
    alt_group = models.CharField("替代组", max_length=40, blank=True, default="")
    risk_level = models.CharField("风险等级", max_length=20, default="low")
    variables = models.JSONField("条款变量", default=list, blank=True)
    note = models.TextField("内部说明", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "模板条款"
        verbose_name_plural = "模板条款"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["template", "order"], name="ctm_clause_tpl_order_idx"),
        ]

    def __str__(self):
        return f"{self.order}. {self.title}"


# ---------------------------------------------------------------------------
# 合同主体与合同主表
# ---------------------------------------------------------------------------


class ContractParty(ContractBase):
    """合同参与方：甲/乙/丙方，带统一信用代码与签署顺序。

    sign_order 决定签署指纹的先后（多方法律要求「先甲后乙」），
    同一份合同的签署顺序冲突在视图层校验。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_parties", verbose_name="创建人")
    contract = models.ForeignKey("Contract", on_delete=models.CASCADE,
                                 related_name="parties", verbose_name="合同")
    name = models.CharField("主体名称", max_length=200)
    party_type = models.CharField("主体类型", max_length=20, default="company")
    credit_code = models.CharField("统一信用代码", max_length=40, blank=True, default="")
    contact = models.CharField("联系人", max_length=60, blank=True, default="")
    phone = models.CharField("联系电话", max_length=40, blank=True, default="")
    address = models.CharField("地址", max_length=200, blank=True, default="")
    role = models.CharField("角色", max_length=20, default="party_b", db_index=True)
    sign_order = models.IntegerField("签署顺序", default=1)
    signed = models.BooleanField("已签署", default=False)
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "合同主体"
        verbose_name_plural = "合同主体"
        ordering = ["sign_order", "id"]
        indexes = [
            models.Index(fields=["contract", "role"], name="ctm_party_contract_role_idx"),
        ]

    def __str__(self):
        return f"{self.get_role_label()}: {self.name}"

    def get_role_label(self):
        return PARTY_ROLE_LABELS.get(self.role, self.role)


class Contract(ContractBase):
    """合同主表：金额、期限、状态机与风险分都挂在这里。

    状态机流转规则集中在 contracts/state.py，模型只负责数据；
    金额派生（已付 / 未付 / 逾期）走属性，避免多处重复 SUM 逻辑。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_contracts", verbose_name="创建人")
    number = models.CharField("合同编号", max_length=60, db_index=True)
    name = models.CharField("合同名称", max_length=200)
    contract_type = models.CharField("合同类型", max_length=20, default="service",
                                     db_index=True)
    amount = models.DecimalField("合同金额", max_digits=18, decimal_places=2,
                                 default=_money_default)
    currency = models.CharField("币种", max_length=8, default="CNY")
    sign_date = models.DateField("签订日", null=True, blank=True)
    effective_date = models.DateField("生效日", null=True, blank=True)
    expire_date = models.DateField("到期日", null=True, blank=True, db_index=True)
    renewal_mode = models.CharField("续约方式", max_length=16, default="none")
    risk_score = models.IntegerField("风险分", default=0)
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name="ct_responsible_contracts",
                                    verbose_name="负责人")
    counterparty_name = models.CharField("相对方", max_length=200, blank=True, default="")
    counterparty_party = models.ForeignKey(ContractParty, on_delete=models.SET_NULL,
                                           null=True, blank=True,
                                           related_name="counterparty_contracts",
                                           verbose_name="相对方主体")
    template = models.ForeignKey(ContractTemplate, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="contracts",
                                 verbose_name="来源模板")
    current_version = models.ForeignKey("ContractVersion", on_delete=models.SET_NULL,
                                        null=True, blank=True,
                                        related_name="current_of_contracts",
                                        verbose_name="当前版本")
    tags = models.ManyToManyField("ContractTag", blank=True, related_name="contracts",
                                  verbose_name="标签")
    remark = models.TextField("备注", blank=True, default="")
    data = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "合同"
        verbose_name_plural = "合同"
        constraints = [
            models.UniqueConstraint(fields=["owner", "number"],
                                    name="ctm_contract_owner_number_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="ctm_contract_owner_status_idx"),
            models.Index(fields=["expire_date"], name="ctm_contract_expire_idx"),
        ]

    def __str__(self):
        return f"{self.number} {self.name}"

    # ---- 期限派生 ----

    def days_to_expiry(self, today=None):
        """距到期天数：无到期日返回 None；已过期为负数，前端据此判红。"""
        if not self.expire_date:
            return None
        today = today or timezone.localdate()
        return (self.expire_date - today).days

    @property
    def is_expired(self):
        days = self.days_to_expiry()
        return days is not None and days < 0

    def is_active_like(self):
        """是否处于「仍在履行」的语义状态（到期扫描只处理这几档）。"""
        return self.status in ("active", "expiring")

    def expiry_bucket(self, today=None):
        """到期分段：expired / d7 / d30 / d90 / later / none，用于分组统计。"""
        days = self.days_to_expiry(today)
        if days is None:
            return "none"
        if days < 0:
            return "expired"
        if days <= 7:
            return "d7"
        if days <= 30:
            return "d30"
        if days <= 90:
            return "d90"
        return "later"

    # ---- 金额派生（以付款计划为口径，而非合同总额）----

    def paid_amount(self, payments=None):
        """已付金额：只统计 paid/partial 期次的实付部分，取消期次不计。"""
        rows = self.payments.all() if payments is None else payments
        total = Decimal("0.00")
        for row in rows:
            if row.status == "cancelled":
                continue
            total += to_decimal(row.paid_amount, "实付金额")
        return total

    def planned_amount(self, payments=None):
        """计划金额：付款计划合计，用于和合同总额对账。"""
        rows = self.payments.all() if payments is None else payments
        total = Decimal("0.00")
        for row in rows:
            if row.status == "cancelled":
                continue
            total += to_decimal(row.plan_amount, "计划金额")
        return total

    def unpaid_amount(self, payments=None):
        """未付金额 = 合同总额 - 已付（负数归零，防止超付被算成负债权）。"""
        rest = to_decimal(self.amount) - self.paid_amount(payments)
        return rest if rest > 0 else Decimal("0.00")

    def overdue_amount(self, payments=None, today=None):
        """逾期金额：计划日已过且未结清期次的剩余额。"""
        today = today or timezone.localdate()
        rows = self.payments.all() if payments is None else payments
        total = Decimal("0.00")
        for row in rows:
            if row.status in ("paid", "cancelled"):
                continue
            if not row.plan_date or row.plan_date >= today:
                continue
            rest = to_decimal(row.plan_amount) - to_decimal(row.paid_amount)
            if rest > 0:
                total += rest
        return total

    def main_party(self):
        """取甲方（主签约主体）；历史数据可能没有 party_a，退化为第一个主体。"""
        parties = list(self.parties.all())
        for p in parties:
            if p.role == "party_a":
                return p
        return parties[0] if parties else None


class ContractVersion(ContractBase):
    """合同版本快照：每次正文变更落一版，is_current 保证只有一个当前版。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_versions", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="versions", verbose_name="合同")
    version_no = models.IntegerField("版本号", default=1)
    body_snapshot = models.TextField("正文快照", blank=True, default="")
    change_summary = models.TextField("变更摘要", blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True,
                                   related_name="ct_versions_created",
                                   verbose_name="创建人")
    is_current = models.BooleanField("当前版本", default=False)

    class Meta(ContractBase.Meta):
        verbose_name = "合同版本"
        verbose_name_plural = "合同版本"
        ordering = ["-version_no"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "version_no"],
                                    name="ctm_version_contract_no_uniq"),
        ]

    def __str__(self):
        return f"#{self.version_no} of {self.contract_id}"


# ---------------------------------------------------------------------------
# 履约：义务 / 事件 / 里程碑
# ---------------------------------------------------------------------------


class ContractObligation(ContractBase):
    """履约义务：周期义务由服务层按 series_uid 幂等展开成未来 N 期。

    series_uid 是幂等的关键：根义务 uid 形如 series-xxx，展开出的期次为
    "series-xxx#2026-01-01"。唯一约束 (contract, series_uid) 保证重复点击
    「生成排期」不会产生重复行。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_obligations", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="obligations", verbose_name="合同")
    party = models.ForeignKey(ContractParty, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name="obligations",
                              verbose_name="义务方")
    party_name = models.CharField("义务方名称", max_length=200, blank=True, default="")
    content = models.TextField("义务内容")
    trigger = models.CharField("触发条件", max_length=200, blank=True, default="")
    cycle = models.CharField("周期", max_length=16, default="once")
    due_date = models.DateField("截止日", null=True, blank=True, db_index=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name="ct_obligations_responsible",
                                    verbose_name="责任人")
    responsible_name = models.CharField("责任人名称", max_length=60, blank=True,
                                        default="")
    status = models.CharField("状态", max_length=20, default="pending", db_index=True)
    priority = models.CharField("优先级", max_length=16, default="normal")
    series_uid = models.CharField("排期标识", max_length=120, null=True, blank=True)
    recurring_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name="generated",
                                       verbose_name="排期来源")
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "履约义务"
        verbose_name_plural = "履约义务"
        ordering = ["due_date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "series_uid"],
                                    name="ctm_obligation_series_uniq"),
        ]
        indexes = [
            models.Index(fields=["contract", "status"],
                         name="ctm_oblig_ct_status_idx"),
            models.Index(fields=["due_date", "status"],
                         name="ctm_obligation_due_status_idx"),
        ]

    def __str__(self):
        return f"{self.content[:20]} [{self.status}]"

    def is_overdue(self, today=None):
        """逾期判定：未完成/未豁免且截止日已过。"""
        today = today or timezone.localdate()
        if self.status in ("done", "waived") or not self.due_date:
            return False
        return self.due_date < today

    def mark_status(self, status, extra_fields=()):
        """状态变更统一入口：刷新时间戳并只写必要字段，避免整行覆盖。"""
        self.status = status
        self.touch()
        fields = ["status", "updated_at", *extra_fields]
        self.save(update_fields=fields)


class ObligationEvent(ContractBase):
    """履约事件：完成 / 延期 / 豁免 / 重开的记录与证据。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_obligation_events", verbose_name="创建人")
    obligation = models.ForeignKey(ContractObligation, on_delete=models.CASCADE,
                                   related_name="events", verbose_name="义务")
    action = models.CharField("动作", max_length=20, default="complete")
    note = models.TextField("说明", blank=True, default="")
    evidence = models.CharField("证据", max_length=300, blank=True, default="")
    happened_at = models.DateTimeField("发生时间", default=timezone.now)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True,
                              related_name="ct_obligation_events_acted",
                              verbose_name="操作人")
    from_due_date = models.DateField("原截止日", null=True, blank=True)
    to_due_date = models.DateField("新截止日", null=True, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "履约事件"
        verbose_name_plural = "履约事件"
        ordering = ["-happened_at", "-id"]

    def __str__(self):
        return f"{self.action}@{self.obligation_id}"


class ContractMilestone(ContractBase):
    """合同里程碑：交付/验收/上线等关键节点，计划日 vs 实际日衡量达成率。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_milestones", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="milestones", verbose_name="合同")
    name = models.CharField("里程碑", max_length=200)
    plan_date = models.DateField("计划日期", null=True, blank=True)
    actual_date = models.DateField("实际日期", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="planned", db_index=True)
    amount = models.DecimalField("金额", max_digits=18, decimal_places=2,
                                 default=_money_default)
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "合同里程碑"
        verbose_name_plural = "合同里程碑"
        ordering = ["plan_date", "id"]

    def __str__(self):
        return self.name

    def is_late(self):
        """是否延期达成：实际日期晚于计划日期即算延期（无实际日则不算）。"""
        if not (self.actual_date and self.plan_date):
            return False
        return self.actual_date > self.plan_date


# ---------------------------------------------------------------------------
# 变更与审批
# ---------------------------------------------------------------------------


class ContractAmendment(ContractBase):
    """合同变更单：记录变更前后条款、类型与审批结论。

    before_text / after_text 用整段文本而非结构化 diff：
    变更内容可能是金额、期限、主体，结构化会立刻退化成 JSON 大杂烩。
    条款级 diff 由服务层按「条」解析后再算。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_amendments", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="amendments", verbose_name="合同")
    code = models.CharField("变更单号", max_length=60)
    change_type = models.CharField("变更类型", max_length=20, default="clause")
    before_text = models.TextField("变更前", blank=True, default="")
    after_text = models.TextField("变更后", blank=True, default="")
    effective_date = models.DateField("生效日", null=True, blank=True)
    approval_status = models.CharField("审批状态", max_length=20, default="draft",
                                       db_index=True)
    reason = models.TextField("变更原因", blank=True, default="")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name="ct_amendments_approved",
                                    verbose_name="审批人")
    decided_at = models.DateTimeField("审批时间", null=True, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "合同变更"
        verbose_name_plural = "合同变更"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "code"],
                                    name="ctm_amendment_contract_code_uniq"),
        ]

    def __str__(self):
        return f"{self.code} [{self.approval_status}]"


class ContractApproval(ContractBase):
    """审批节点：一个合同按金额阈值生成一串节点，逐节点通过/驳回。

    decision 为 pending 的节点是可操作的；合同整体状态由「全部节点通过」
    或「任一节点驳回」推导，避免节点结论与主表状态打架。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_approvals", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="approvals", verbose_name="合同")
    node = models.IntegerField("节点序号", default=1)
    node_name = models.CharField("节点名称", max_length=60)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name="ct_approvals_assigned",
                                 verbose_name="审批人")
    decision = models.CharField("结论", max_length=20, default="pending")
    opinion = models.TextField("意见", blank=True, default="")
    decided_at = models.DateTimeField("审批时间", null=True, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "合同审批"
        verbose_name_plural = "合同审批"
        ordering = ["node", "id"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "node"],
                                    name="ctm_approval_contract_node_uniq"),
        ]

    def __str__(self):
        return f"#{self.node} {self.node_name} [{self.decision}]"


class ContractSignature(ContractBase):
    """签署记录：只存哈希指纹与状态，不接第三方 CA。

    指纹 = sha256(正文 + 签署人 + 签署时间)，用于事后校验「同一时刻同一人
    签署的正文是否被改过」；真实电子签章的证书链不在本项目范围内。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_signatures", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="signatures", verbose_name="合同")
    party = models.ForeignKey(ContractParty, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name="signatures",
                              verbose_name="签署方")
    signer_name = models.CharField("签署人", max_length=60)
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                               null=True, blank=True,
                               related_name="ct_signatures_owned",
                               verbose_name="签署账号")
    method = models.CharField("签署方式", max_length=20, default="electronic")
    hash_fingerprint = models.CharField("哈希指纹", max_length=64, blank=True,
                                        default="")
    signed_at = models.DateTimeField("签署时间", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="pending", db_index=True)
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "签署记录"
        verbose_name_plural = "签署记录"
        ordering = ["-signed_at", "-id"]
        indexes = [
            models.Index(fields=["contract", "status"],
                         name="ctm_sign_contract_status_idx"),
        ]

    def __str__(self):
        return f"{self.signer_name} [{self.status}]"


# ---------------------------------------------------------------------------
# 财务：付款计划 / 续约
# ---------------------------------------------------------------------------


class ContractPayment(ContractBase):
    """付款计划与实付登记：期次唯一，逾期由计划日 + 状态推导。

    金额双轨（计划/实付）是必需的：合同经常分期，计划额与实付额不一致时
    要能算出「欠多少」，而不能只存一个当前金额。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_payments", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="payments", verbose_name="合同")
    period_no = models.IntegerField("期次", default=1)
    plan_amount = models.DecimalField("计划金额", max_digits=18, decimal_places=2,
                                      default=_money_default)
    plan_date = models.DateField("计划日期", null=True, blank=True)
    paid_amount = models.DecimalField("实付金额", max_digits=18, decimal_places=2,
                                      default=_money_default)
    paid_date = models.DateField("实付日期", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="planned", db_index=True)
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "付款计划"
        verbose_name_plural = "付款计划"
        ordering = ["period_no", "id"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "period_no"],
                                    name="ctm_payment_contract_period_uniq"),
        ]

    def __str__(self):
        return f"第{self.period_no}期 {self.plan_amount}"

    def remaining(self):
        """剩余应收/应付：取消期次按 0 处理，避免逾期统计把作废期算进去。"""
        if self.status == "cancelled":
            return Decimal("0.00")
        rest = to_decimal(self.plan_amount) - to_decimal(self.paid_amount)
        return rest if rest > 0 else Decimal("0.00")

    def is_overdue(self, today=None):
        """逾期：非结清、非取消且计划日期已过。"""
        today = today or timezone.localdate()
        if self.status in ("paid", "cancelled") or not self.plan_date:
            return False
        return self.plan_date < today

    def sync_status(self, today=None):
        """按实付额推导状态：全额→paid，部分→partial，过期未付→overdue。

        这个推导必须集中在一处，否则「登记实付」和「逾期扫描」各写一遍，
        两个入口迟早给出不一致的状态。
        """
        today = today or timezone.localdate()
        if self.status == "cancelled":
            return self.status
        plan = to_decimal(self.plan_amount)
        paid = to_decimal(self.paid_amount)
        if plan > 0 and paid >= plan:
            self.status = "paid"
        elif paid > 0:
            self.status = "partial"
        elif self.plan_date and self.plan_date < today:
            self.status = "overdue"
        else:
            self.status = "planned"
        return self.status


class ContractRenewal(ContractBase):
    """续约跟进：记录续约类型、新到期日与提醒天数。

    同一合同可以有多次续约记录（历史留痕），确认后回写主表的到期日与状态。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_renewals", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="renewals", verbose_name="合同")
    renewal_type = models.CharField("续约类型", max_length=20, default="manual")
    new_expire_date = models.DateField("新到期日", null=True, blank=True)
    remind_days = models.IntegerField("提前提醒天数", default=30)
    status = models.CharField("状态", max_length=20, default="pending", db_index=True)
    note = models.TextField("说明", blank=True, default="")
    decided_at = models.DateTimeField("处理时间", null=True, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "续约记录"
        verbose_name_plural = "续约记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["contract", "status"],
                         name="ctm_renewal_ct_status_idx"),
        ]

    def __str__(self):
        return f"{self.renewal_type} -> {self.new_expire_date}"


# ---------------------------------------------------------------------------
# 风险、资料与提醒
# ---------------------------------------------------------------------------


class ContractRisk(ContractBase):
    """风险项：等级 + 描述 + 缓解措施，参与合同风险评分。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_risks", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="risks", verbose_name="合同")
    title = models.CharField("风险项", max_length=200)
    level = models.CharField("等级", max_length=20, default="medium", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    mitigation = models.TextField("缓解措施", blank=True, default="")
    status = models.CharField("状态", max_length=20, default="open", db_index=True)
    score = models.IntegerField("风险分", default=0)

    class Meta(ContractBase.Meta):
        verbose_name = "合同风险"
        verbose_name_plural = "合同风险"
        ordering = ["-score", "-created_at"]

    def __str__(self):
        return f"{self.title} [{self.level}]"

    def weight(self):
        """风险项权重：关闭/已接受的风险不再参与评分（避免历史包袱拉高总分）。"""
        if self.status in ("closed", "accepted"):
            return 0
        return RISK_LEVEL_WEIGHT.get(self.level, 8)


class ContractAttachment(ContractBase):
    """附件元数据：只登记文件指纹与存储键，文件本体走 files 应用。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_attachments", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="attachments", verbose_name="合同")
    file_name = models.CharField("文件名", max_length=200)
    kind = models.CharField("资料类型", max_length=20, default="attachment")
    file_size = models.BigIntegerField("文件大小", default=0)
    mime = models.CharField("MIME", max_length=100, blank=True, default="")
    storage_key = models.CharField("存储键", max_length=300, blank=True, default="")
    checksum = models.CharField("校验和", max_length=64, blank=True, default="")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name="ct_attachments_uploaded",
                                    verbose_name="上传人")
    remark = models.TextField("备注", blank=True, default="")

    class Meta(ContractBase.Meta):
        verbose_name = "合同附件"
        verbose_name_plural = "合同附件"
        ordering = ["-created_at"]

    def __str__(self):
        return self.file_name


class ContractTag(ContractBase):
    """合同标签：同一用户下名称唯一，用于台账分组与筛选。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_tags", verbose_name="创建人")
    name = models.CharField("标签名", max_length=40)
    color = models.CharField("颜色", max_length=20, default="#409EFF")
    usage_count = models.IntegerField("使用次数", default=0)

    class Meta(ContractBase.Meta):
        verbose_name = "合同标签"
        verbose_name_plural = "合同标签"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"],
                                    name="ctm_tag_owner_name_uniq"),
        ]

    def __str__(self):
        return self.name


class ContractReminder(ContractBase):
    """提醒记录：到期/续约/履约/付款的推送留痕，dedupe_key 保证幂等。

    扫描接口可以被定时任务反复调用，同一 (合同, 类型, 阈值, 目标日)
    只能产生一条记录；去重键落到唯一约束，而不是「先查再写」。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_reminders", verbose_name="创建人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="reminders", verbose_name="合同")
    kind = models.CharField("提醒类型", max_length=20, default="expiry", db_index=True)
    stage = models.IntegerField("阈值天数", default=0)
    channel = models.CharField("渠道", max_length=20, default="inapp")
    status = models.CharField("状态", max_length=20, default="sent")
    message = models.TextField("内容", blank=True, default="")
    target_date = models.DateField("目标日期", null=True, blank=True)
    dedupe_key = models.CharField("去重键", max_length=120, null=True, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "合同提醒"
        verbose_name_plural = "合同提醒"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["dedupe_key"],
                                    name="ctm_reminder_dedupe_uniq"),
        ]
        indexes = [
            models.Index(fields=["contract", "kind"],
                         name="ctm_reminder_contract_kind_idx"),
        ]

    def __str__(self):
        return f"{self.kind}@{self.stage}"


class ContractAudit(ContractBase):
    """合同操作审计：状态流转与关键动作的追加型日志（不提供修改入口）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="ct_audits", verbose_name="操作人")
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE,
                                 related_name="audits", verbose_name="合同")
    action = models.CharField("动作", max_length=30, default="update")
    from_status = models.CharField("原状态", max_length=20, blank=True, default="")
    to_status = models.CharField("新状态", max_length=20, blank=True, default="")
    note = models.TextField("说明", blank=True, default="")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True,
                              related_name="ct_audits_acted", verbose_name="操作账号")
    payload = models.JSONField("附加信息", default=dict, blank=True)

    class Meta(ContractBase.Meta):
        verbose_name = "合同审计"
        verbose_name_plural = "合同审计"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["contract", "created_at"],
                         name="ctm_audit_contract_time_idx"),
        ]

    def __str__(self):
        return f"{self.action}: {self.from_status}->{self.to_status}"
