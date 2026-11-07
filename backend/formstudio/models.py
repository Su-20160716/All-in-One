# -*- coding: utf-8 -*-
"""formstudio 数据模型：表单设计器 / 问卷 / 测验 / 收集 / 报名 / 审批 / 反馈。

设计要点
--------
1. 表单定义（FormDefinition）只存元信息，结构化的分区、字段、校验、逻辑规则
   各自成表，既能按字段做统计，又能在发布时把整份 schema 快照进 FormVersion。
2. 提交（FormSubmission）固化 ``version_no`` 与版本外键，表单后续改版不会影响
   历史提交的统计口径；填报值落到 FormSubmissionValue 的强类型列（文本/数字/日期），
   避免每次统计都解析 JSON。
3. 匿名表单允许 ``submitted_by`` 为空，但 ``owner`` 始终是表单创建者，
   行级权限统一走 core.scoping，不额外引入权限字段。
4. 附件只存元数据（文件名/大小/hash），不落盘；webhook 投递同样只入库留痕，
   由服务层模拟投递状态与重试节奏。
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# 枚举：全部以「字符串常量 + choices」双份维护，便于前端直接消费常量，
# 同时让 Django admin / 表单拿到可读标签。
# ---------------------------------------------------------------------------

FORM_TYPE_CHOICES = [
    ("survey", "问卷"),
    ("quiz", "测验"),
    ("collect", "信息收集"),
    ("registration", "报名登记"),
    ("approval", "审批申请"),
    ("feedback", "意见反馈"),
]

FORM_STATUS_CHOICES = [
    ("draft", "草稿"),
    ("published", "已发布"),
    ("closed", "已关闭"),
    ("archived", "已归档"),
]

FIELD_TYPE_CHOICES = [
    ("text", "单行文本"),
    ("textarea", "多行文本"),
    ("number", "数字"),
    ("select", "单选"),
    ("multiselect", "多选"),
    ("date", "日期"),
    ("datetime", "日期时间"),
    ("boolean", "开关"),
    ("file", "文件"),
    ("rating", "评分"),
    ("signature", "签名"),
    ("matrix", "矩阵"),
    ("email", "邮箱"),
    ("phone", "手机号"),
    ("url", "链接"),
    ("section", "分区标题"),
]

FIELD_WIDTH_CHOICES = [
    ("full", "整行"),
    ("half", "半行"),
    ("third", "三分之一"),
]

VALIDATION_RULE_CHOICES = [
    ("required", "必填"),
    ("min", "最小值"),
    ("max", "最大值"),
    ("regex", "正则"),
    ("length", "长度"),
    ("formula", "公式"),
    ("unique", "唯一"),
]

LOGIC_ACTION_CHOICES = [
    ("show", "显示"),
    ("hide", "隐藏"),
    ("require", "设为必填"),
    ("skip", "跳过"),
    ("set_value", "赋值"),
]

SUBMISSION_STATUS_CHOICES = [
    ("draft", "草稿"),
    ("submitted", "已提交"),
    ("reviewed", "已审核"),
    ("rejected", "已驳回"),
]

SUBMISSION_SOURCE_CHOICES = [
    ("web", "网页"),
    ("share", "分享链接"),
    ("api", "接口"),
    ("embed", "嵌入"),
    ("import", "导入"),
]

WEBHOOK_EVENT_CHOICES = [
    ("submission.created", "提交创建"),
    ("submission.reviewed", "审核完成"),
    ("form.published", "表单发布"),
    ("all", "全部事件"),
]

DELIVERY_STATUS_CHOICES = [
    ("pending", "待投递"),
    ("success", "成功"),
    ("failed", "失败"),
    ("skipped", "已跳过"),
]

REVIEW_STATUS_CHOICES = [
    ("pending", "待处理"),
    ("approved", "通过"),
    ("rejected", "驳回"),
]

COMMENT_VISIBILITY_CHOICES = [
    ("internal", "内部"),
    ("public", "公开"),
]


class TimeStampedModel(models.Model):
    """只抽时间戳，不抽 owner：每个模型显式声明 owner 与唯一 related_name。"""

    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


class FormDefinition(TimeStampedModel):
    """表单定义：一个表单的设计态与发布态入口。

    status 状态机：draft → published → closed → archived；
    归档只影响列表默认过滤，不删除任何提交数据。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_forms",
        verbose_name="创建者",
    )
    code = models.CharField("表单编码", max_length=64, db_index=True)
    name = models.CharField("表单名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    form_type = models.CharField(
        "表单类型", max_length=20, choices=FORM_TYPE_CHOICES, default="survey", db_index=True
    )
    status = models.CharField(
        "状态", max_length=20, choices=FORM_STATUS_CHOICES, default="draft", db_index=True
    )
    allow_anonymous = models.BooleanField("允许匿名", default=False)
    allow_multiple = models.BooleanField("允许多次提交", default=True)
    deadline = models.DateTimeField("截止时间", null=True, blank=True)
    theme = models.JSONField("主题配置", default=dict, blank=True)
    settings = models.JSONField("表单设置", default=dict, blank=True)
    submit_message = models.CharField(
        "提交后提示", max_length=300, default="提交成功，感谢参与。"
    )
    redirect_url = models.CharField("提交后跳转", max_length=500, blank=True, default="")
    submission_count = models.IntegerField("提交计数", default=0)
    view_count = models.IntegerField("浏览计数", default=0)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    closed_at = models.DateTimeField("关闭时间", null=True, blank=True)
    archived_at = models.DateTimeField("归档时间", null=True, blank=True)

    class Meta:
        verbose_name = "表单定义"
        verbose_name_plural = "表单定义"
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="fs_form_owner_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="fs_form_owner_status_idx"),
            models.Index(fields=["form_type", "status"], name="fs_form_type_status_idx"),
        ]

    def __str__(self):
        return f"{self.code}:{self.name}"

    # -- 业务状态判定 -------------------------------------------------------
    def is_expired(self) -> bool:
        """截止时间是否已过（无截止时间视为未过期）。"""
        return bool(self.deadline and self.deadline <= timezone.now())

    def is_open(self) -> bool:
        """当前是否可接收提交：已发布、未关闭、未过期。"""
        return self.status == "published" and not self.is_expired()

    def submit_block_reason(self) -> str:
        """不能提交时的中文原因；空串表示可以提交。"""
        if self.status == "draft":
            return "表单尚未发布"
        if self.status == "closed":
            return "表单已关闭"
        if self.status == "archived":
            return "表单已归档"
        if self.is_expired():
            return "表单已过截止时间"
        return ""

    def touch_view(self, delta: int = 1) -> None:
        """浏览计数：用 F 表达式避免并发覆盖。"""
        FormDefinition.objects.filter(pk=self.pk).update(view_count=models.F("view_count") + delta)
        self.refresh_from_db(fields=["view_count"])


class FormVersion(TimeStampedModel):
    """表单版本：每次发布都会落一份 schema 快照，历史提交按版本号统计。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_versions",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="表单",
    )
    version_no = models.PositiveIntegerField("版本号", default=1)
    schema = models.JSONField("结构快照", default=dict, blank=True)
    status = models.CharField("发布时表单状态", max_length=20, default="published")
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fs_published_versions",
        verbose_name="发布人",
    )
    published_at = models.DateTimeField("发布时间", default=timezone.now)
    note = models.CharField("版本说明", max_length=500, blank=True, default="")
    changelog = models.TextField("变更日志", blank=True, default="")
    is_current = models.BooleanField("当前版本", default=False, db_index=True)

    class Meta:
        verbose_name = "表单版本"
        verbose_name_plural = "表单版本"
        ordering = ["-version_no", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["form", "version_no"], name="fs_version_form_no_uniq"),
        ]
        indexes = [
            models.Index(fields=["form", "is_current"], name="fs_version_form_current_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}#v{self.version_no}"

    def field_count(self) -> int:
        """快照中的字段数（前端版本列表用，避免整份 schema 下发）。"""
        return len((self.schema or {}).get("fields") or [])

    def section_count(self) -> int:
        """快照中的分区数。"""
        return len((self.schema or {}).get("sections") or [])


class FormSection(TimeStampedModel):
    """表单分区：字段按 section 分组，支持折叠与显隐条件。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_sections",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="sections",
        verbose_name="表单",
    )
    key = models.CharField("分区标识", max_length=64)
    title = models.CharField("分区标题", max_length=200)
    description = models.TextField("分区描述", blank=True, default="")
    order = models.IntegerField("排序", default=0)
    collapsible = models.BooleanField("可折叠", default=False)
    condition = models.JSONField("显示条件", default=dict, blank=True)

    class Meta:
        verbose_name = "表单分区"
        verbose_name_plural = "表单分区"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["form", "key"], name="fs_section_form_key_uniq"),
        ]
        indexes = [
            models.Index(fields=["form", "order"], name="fs_section_form_order_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}:{self.key}"


class FormField(TimeStampedModel):
    """表单字段：存储层保留 options/validation/condition 的 JSON 冗余快照。

    冗余是为了「读一个字段就能完成渲染与校验」，FormFieldOption 则是可统计、
    可计分的规范化形态；保存时由服务层把两者对齐。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_fields",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name="表单",
    )
    section = models.ForeignKey(
        FormSection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fields",
        verbose_name="所属分区",
    )
    key = models.CharField("字段标识", max_length=64)
    label = models.CharField("字段标题", max_length=200)
    field_type = models.CharField(
        "字段类型", max_length=20, choices=FIELD_TYPE_CHOICES, default="text", db_index=True
    )
    required = models.BooleanField("必填", default=False)
    default_value = models.JSONField("默认值", null=True, blank=True)
    placeholder = models.CharField("占位提示", max_length=200, blank=True, default="")
    help_text = models.TextField("帮助说明", blank=True, default="")
    order = models.IntegerField("排序", default=0)
    width = models.CharField(
        "宽度", max_length=10, choices=FIELD_WIDTH_CHOICES, default="full"
    )
    options = models.JSONField("选项快照", default=list, blank=True)
    validation = models.JSONField("校验配置", default=dict, blank=True)
    condition = models.JSONField("显示条件", default=dict, blank=True)

    class Meta:
        verbose_name = "表单字段"
        verbose_name_plural = "表单字段"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["form", "key"], name="fs_field_form_key_uniq"),
        ]
        indexes = [
            models.Index(fields=["form", "order"], name="fs_field_form_order_idx"),
            models.Index(fields=["section", "order"], name="fs_field_section_order_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}:{self.key}({self.field_type})"

    def option_items(self):
        """选项：优先取规范化子表，回退到 JSON 快照（批量 schema 保存时只写快照）。"""
        rows = list(self.option_rows.all().order_by("order", "id"))
        if rows:
            return [
                {
                    "value": r.value,
                    "label": r.label,
                    "score": r.score,
                    "disabled": r.disabled,
                }
                for r in rows
            ]
        return list(self.options or [])

    def option_values(self):
        """选项值集合，供选择题校验器快速判重。"""
        return {str(o.get("value")) for o in self.option_items() if o.get("value") is not None}


class FormFieldOption(models.Model):
    """字段选项：单值/多值/评分的可计分选项。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_field_options",
        verbose_name="创建者",
    )
    field = models.ForeignKey(
        FormField,
        on_delete=models.CASCADE,
        related_name="option_rows",
        verbose_name="字段",
    )
    value = models.CharField("选项值", max_length=120)
    label = models.CharField("选项标签", max_length=200)
    order = models.IntegerField("排序", default=0)
    score = models.IntegerField("分值", default=0)
    disabled = models.BooleanField("禁用", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "字段选项"
        verbose_name_plural = "字段选项"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["field", "value"], name="fs_option_field_value_uniq"),
        ]
        indexes = [
            models.Index(fields=["field", "order"], name="fs_option_field_order_idx"),
        ]

    def __str__(self):
        return f"{self.field_id}:{self.value}"


class FormValidation(TimeStampedModel):
    """独立校验规则：与字段 JSON 内的轻量规则并存，便于按规则类型批量维护。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_validations",
        verbose_name="创建者",
    )
    field = models.ForeignKey(
        FormField,
        on_delete=models.CASCADE,
        related_name="validation_rules",
        verbose_name="目标字段",
    )
    rule_type = models.CharField(
        "规则类型", max_length=20, choices=VALIDATION_RULE_CHOICES, default="required", db_index=True
    )
    params = models.JSONField("规则参数", default=dict, blank=True)
    message = models.CharField("错误提示", max_length=300, blank=True, default="")
    target_key = models.CharField("关联字段", max_length=64, blank=True, default="")
    order = models.IntegerField("排序", default=0)
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "校验规则"
        verbose_name_plural = "校验规则"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["field", "rule_type"], name="fs_val_field_rule_idx"),
        ]

    def __str__(self):
        return f"{self.field_id}:{self.rule_type}"


class FormLogicRule(TimeStampedModel):
    """逻辑规则：条件成立时对目标字段执行 show/hide/require/skip/set_value。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_logic_rules",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="logic_rules",
        verbose_name="表单",
    )
    name = models.CharField("规则名称", max_length=200, blank=True, default="")
    condition = models.JSONField("条件表达式", default=dict, blank=True)
    action = models.CharField(
        "动作", max_length=20, choices=LOGIC_ACTION_CHOICES, default="show", db_index=True
    )
    target_key = models.CharField("目标字段", max_length=64)
    value = models.JSONField("赋值", null=True, blank=True)
    priority = models.IntegerField("优先级", default=100)
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "逻辑规则"
        verbose_name_plural = "逻辑规则"
        ordering = ["priority", "id"]
        indexes = [
            models.Index(fields=["form", "enabled"], name="fs_logic_form_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}:{self.action}->{self.target_key}"


class FormSubmission(TimeStampedModel):
    """提交：owner 固定为表单创建者（匿名也成立），submitted_by 记录实际填报人。

    version_no 在提交时固化；统计接口默认按版本号分组，改版不回溯。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_submissions",
        verbose_name="表单创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="submissions",
        verbose_name="表单",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fs_made_submissions",
        verbose_name="填报人",
    )
    version = models.ForeignKey(
        FormVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
        verbose_name="表单版本",
    )
    version_no = models.PositiveIntegerField("版本号", default=0, db_index=True)
    status = models.CharField(
        "状态", max_length=20, choices=SUBMISSION_STATUS_CHOICES, default="submitted", db_index=True
    )
    score = models.FloatField("得分", null=True, blank=True)
    max_score = models.FloatField("满分", null=True, blank=True)
    duration_seconds = models.IntegerField("填写耗时秒", default=0)
    ip = models.CharField("IP", max_length=45, blank=True, default="")
    user_agent = models.CharField("UA", max_length=300, blank=True, default="")
    source = models.CharField(
        "来源", max_length=20, choices=SUBMISSION_SOURCE_CHOICES, default="web"
    )
    share_link = models.ForeignKey(
        "FormShareLink",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
        verbose_name="分享链接",
    )
    answers_count = models.IntegerField("答题数", default=0)
    data = models.JSONField("附加数据", default=dict, blank=True)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True, db_index=True)
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    review_note = models.TextField("审核意见", blank=True, default="")

    class Meta:
        verbose_name = "表单提交"
        verbose_name_plural = "表单提交"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["form", "status"], name="fs_sub_form_status_idx"),
            models.Index(fields=["form", "submitted_at"], name="fs_sub_form_date_idx"),
            models.Index(fields=["owner", "status"], name="fs_sub_owner_status_idx"),
            models.Index(fields=["submitted_by", "status"], name="fs_sub_user_status_idx"),
            models.Index(fields=["form", "version_no"], name="fs_sub_form_version_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}#{self.pk}[{self.status}]"

    def is_final(self) -> bool:
        """是否已进入审核生命周期（草稿之外）。"""
        return self.status in ("submitted", "reviewed", "rejected")


class FormSubmissionValue(models.Model):
    """填报值：强类型落库，统计时无需反复解析 JSON。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_submission_values",
        verbose_name="表单创建者",
    )
    submission = models.ForeignKey(
        FormSubmission,
        on_delete=models.CASCADE,
        related_name="values",
        verbose_name="提交",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="submission_values",
        verbose_name="表单",
        null=True,
        blank=True,
    )
    field_key = models.CharField("字段标识", max_length=64, db_index=True)
    field_type = models.CharField("字段类型", max_length=20, blank=True, default="text")
    raw = models.JSONField("原始值", null=True, blank=True)
    text_value = models.TextField("文本值", blank=True, default="")
    number_value = models.FloatField("数字值", null=True, blank=True)
    date_value = models.DateTimeField("日期值", null=True, blank=True)
    score = models.FloatField("该字段得分", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "填报值"
        verbose_name_plural = "填报值"
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "field_key"], name="fs_value_submission_key_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["form", "field_key"], name="fs_value_form_key_idx"),
            models.Index(fields=["field_key", "text_value"], name="fs_value_key_text_idx"),
        ]

    def __str__(self):
        return f"{self.submission_id}:{self.field_key}"


class FormAttachment(models.Model):
    """附件元数据：本平台只登记不落地，content_hash 用于去重与完整性核对。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_attachments",
        verbose_name="表单创建者",
    )
    submission = models.ForeignKey(
        FormSubmission,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="提交",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fs_uploaded_attachments",
        verbose_name="上传人",
    )
    field_key = models.CharField("字段标识", max_length=64, db_index=True)
    file_name = models.CharField("文件名", max_length=255)
    file_size = models.BigIntegerField("字节数", default=0)
    content_hash = models.CharField("内容哈希", max_length=64, blank=True, default="")
    mime_type = models.CharField("MIME", max_length=120, blank=True, default="")
    remark = models.CharField("备注", max_length=300, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "表单附件"
        verbose_name_plural = "表单附件"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["submission", "field_key"], name="fs_attach_sub_field_idx"),
        ]

    def __str__(self):
        return f"{self.submission_id}:{self.file_name}"


class FormShareLink(TimeStampedModel):
    """分享链接：token 公开、密码只存哈希，过期/次数双重限制在服务层统一核验。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_share_links",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="share_links",
        verbose_name="表单",
    )
    token = models.CharField("令牌", max_length=64, unique=True, db_index=True)
    label = models.CharField("备注", max_length=120, blank=True, default="")
    password_hash = models.CharField("密码哈希", max_length=128, blank=True, default="")
    expires_at = models.DateTimeField("过期时间", null=True, blank=True)
    max_uses = models.IntegerField("使用上限", default=0)
    used_count = models.IntegerField("已用次数", default=0)
    active = models.BooleanField("启用", default=True, db_index=True)
    last_used_at = models.DateTimeField("最后使用", null=True, blank=True)

    class Meta:
        verbose_name = "分享链接"
        verbose_name_plural = "分享链接"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["form", "active"], name="fs_share_form_active_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}:{self.token[:8]}"

    def is_expired(self) -> bool:
        """是否已过期（无过期时间视为长期有效）。"""
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def remaining_uses(self):
        """剩余可用次数；None 表示不限次数。"""
        if not self.max_uses:
            return None
        return max(0, self.max_uses - self.used_count)

    def requires_password(self) -> bool:
        """是否设置了访问密码。"""
        return bool(self.password_hash)


class FormWebhook(TimeStampedModel):
    """Webhook 订阅：只做「入库模拟投递」，状态、次数、最后错误全部真实落库。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_webhooks",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="webhooks",
        verbose_name="表单",
    )
    url = models.CharField("回调地址", max_length=500)
    event = models.CharField(
        "订阅事件", max_length=40, choices=WEBHOOK_EVENT_CHOICES, default="submission.created"
    )
    secret = models.CharField("签名密钥", max_length=128, blank=True, default="")
    headers = models.JSONField("附加请求头", default=dict, blank=True)
    enabled = models.BooleanField("启用", default=True, db_index=True)
    max_retries = models.IntegerField("最大重试", default=3)
    timeout_seconds = models.IntegerField("超时秒", default=5)
    failure_count = models.IntegerField("连续失败", default=0)
    last_status = models.CharField("最后状态", max_length=10, blank=True, default="")
    last_error = models.TextField("最后错误", blank=True, default="")
    last_delivery_at = models.DateTimeField("最后投递时间", null=True, blank=True)

    class Meta:
        verbose_name = "Webhook"
        verbose_name_plural = "Webhook"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["form", "enabled"], name="fs_hook_form_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.form_id}->{self.event}"

    def masked_secret(self) -> str:
        """密钥脱敏：只回显末 4 位，避免列表接口泄露。"""
        if not self.secret:
            return ""
        return "*" * max(0, len(self.secret) - 4) + self.secret[-4:]


class FormWebhookDelivery(TimeStampedModel):
    """一次投递尝试：payload 与签名都落库，便于排查与重放。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_webhook_deliveries",
        verbose_name="创建者",
    )
    webhook = models.ForeignKey(
        FormWebhook,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="Webhook",
    )
    event = models.CharField("事件", max_length=40)
    payload = models.JSONField("请求体", default=dict, blank=True)
    status = models.CharField(
        "状态", max_length=10, choices=DELIVERY_STATUS_CHOICES, default="pending", db_index=True
    )
    attempt = models.IntegerField("第几次尝试", default=1)
    response_code = models.IntegerField("响应码", null=True, blank=True)
    signature = models.CharField("签名", max_length=64, blank=True, default="")
    error = models.TextField("错误", blank=True, default="")
    duration_ms = models.IntegerField("耗时毫秒", default=0)
    next_retry_at = models.DateTimeField("下次重试", null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Webhook 投递"
        verbose_name_plural = "Webhook 投递"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["webhook", "status"], name="fs_delivery_hook_status_idx"),
            models.Index(fields=["status", "next_retry_at"], name="fs_delivery_retry_idx"),
        ]

    def __str__(self):
        return f"{self.webhook_id}#{self.attempt}[{self.status}]"


class FormAnalyticsSnapshot(TimeStampedModel):
    """按日汇总：提交数/草稿数/均分/均耗时/完成率，唯一键 (form, date) 做 upsert。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_snapshots",
        verbose_name="创建者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="snapshots",
        verbose_name="表单",
    )
    date = models.DateField("日期", db_index=True)
    submissions = models.IntegerField("提交数", default=0)
    drafts = models.IntegerField("草稿数", default=0)
    reviews = models.IntegerField("审核数", default=0)
    avg_score = models.FloatField("平均分", default=0)
    avg_duration = models.FloatField("平均耗时秒", default=0)
    completion_rate = models.FloatField("完成率", default=0)
    viewed = models.IntegerField("浏览数", default=0)
    started = models.IntegerField("开始填写数", default=0)
    detail = models.JSONField("明细", default=dict, blank=True)

    class Meta:
        verbose_name = "分析快照"
        verbose_name_plural = "分析快照"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["form", "date"], name="fs_snapshot_form_date_uniq"),
        ]

    def __str__(self):
        return f"{self.form_id}@{self.date}"


class FormTemplate(TimeStampedModel):
    """内置/自定义模板：schema 结构与发布快照同构，可直接实例化为表单。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_templates",
        verbose_name="创建者",
    )
    name = models.CharField("模板名称", max_length=200)
    category = models.CharField("分类", max_length=40, default="通用", db_index=True)
    description = models.TextField("说明", blank=True, default="")
    form_type = models.CharField(
        "表单类型", max_length=20, choices=FORM_TYPE_CHOICES, default="survey"
    )
    schema = models.JSONField("模板结构", default=dict, blank=True)
    builtin = models.BooleanField("内置", default=False, db_index=True)
    usage_count = models.IntegerField("使用次数", default=0)
    tags = models.JSONField("标签", default=list, blank=True)

    class Meta:
        verbose_name = "表单模板"
        verbose_name_plural = "表单模板"
        ordering = ["-usage_count", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="fs_template_owner_name_uniq"),
        ]
        indexes = [
            models.Index(fields=["builtin", "category"], name="fs_template_builtin_cat_idx"),
        ]

    def __str__(self):
        return self.name


class FormReviewTask(TimeStampedModel):
    """审核任务：审批型表单提交后自动派给表单创建者，也可由 owner 改派。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_review_tasks_created",
        verbose_name="创建者",
    )
    submission = models.ForeignKey(
        FormSubmission,
        on_delete=models.CASCADE,
        related_name="review_tasks",
        verbose_name="提交",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fs_review_tasks",
        verbose_name="审核人",
    )
    status = models.CharField(
        "状态", max_length=20, choices=REVIEW_STATUS_CHOICES, default="pending", db_index=True
    )
    conclusion = models.TextField("审核结论", blank=True, default="")
    priority = models.CharField("优先级", max_length=10, default="normal")
    due_at = models.DateTimeField("截止时间", null=True, blank=True)
    decided_at = models.DateTimeField("处理时间", null=True, blank=True)

    class Meta:
        verbose_name = "审核任务"
        verbose_name_plural = "审核任务"
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["reviewer", "status"], name="fs_review_user_status_idx"),
            models.Index(fields=["submission", "status"], name="fs_review_sub_status_idx"),
        ]

    def __str__(self):
        return f"task#{self.pk}:{self.status}"


class FormComment(TimeStampedModel):
    """表单/提交评论：parent 为空是主评论，否则是回复；resolved 由表单创建者收口。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fs_comments",
        verbose_name="作者",
    )
    form = models.ForeignKey(
        FormDefinition,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="表单",
    )
    submission = models.ForeignKey(
        FormSubmission,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="comments",
        verbose_name="提交",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        verbose_name="父评论",
    )
    body = models.TextField("内容")
    visibility = models.CharField(
        "可见范围", max_length=10, choices=COMMENT_VISIBILITY_CHOICES, default="internal"
    )
    resolved = models.BooleanField("已解决", default=False)

    class Meta:
        verbose_name = "表单评论"
        verbose_name_plural = "表单评论"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["form", "-created_at"], name="fs_comment_form_date_idx"),
            models.Index(fields=["submission", "-created_at"], name="fs_comment_sub_date_idx"),
        ]

    def __str__(self):
        return f"comment#{self.pk}"
