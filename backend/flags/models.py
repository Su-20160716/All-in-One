# -*- coding: utf-8 -*-
"""功能开关与实验 · 数据模型。

本应用承载「功能开关（feature flag）→ 灰度发布 → A/B 实验」三段能力，模型
按领域分为四组：

1. 组织层：Project / Environment / Audience
2. 开关层：Flag / FlagVersion / Variant / TargetingRule / Rollout
3. 细分层：Segment / SegmentRule
4. 实验与治理层：Experiment / ExperimentMetric / Assignment / Exposure /
   EvaluationLog / FlagDependency / Guardrail / AuditEvent

统一约定（与平台其他应用一致）
--------------------------------
- 每个模型都有 ``owner`` 外键，行级权限统一走 ``core.scoping``，模型本身
  不额外存权限字段；
- 每个模型都有 created_at / updated_at（auto_now），便于审计与缓存失效；
- ``related_name`` 全部显式命名且全局唯一，避免反向查询互相覆盖；
- 枚举值使用模块常量而不是 Django choices：开关平台需要在不改表结构的前提下
  新增操作符/指标类型，choices 会带来一次无意义的迁移。

为什么把 ``as_dict`` 放在模型上
--------------------------------
序列化字段需要与模型强绑定（新增字段时只改一处），而视图还需要按接口裁剪。
这里提供「全量字典」，视图可再取子集；避免十个视图各写一份字段列表导致
同一个开关在不同接口返回不同字段名。
"""
from django.conf import settings
from django.db import models

# ---------------------------------------------------------------------------
# 枚举常量
# ---------------------------------------------------------------------------

PROJECT_STATUS = ("active", "archived")
PROJECT_STATUS_LABELS = {"active": "启用", "archived": "已归档"}

ENV_TYPES = ("production", "staging", "dev")
ENV_TYPE_LABELS = {"production": "生产", "staging": "预发", "dev": "开发"}

FLAG_TYPES = ("boolean", "multivariate")
FLAG_TYPE_LABELS = {"boolean": "布尔开关", "multivariate": "多变量开关"}

FLAG_STATUS = ("active", "inactive", "archived")
FLAG_STATUS_LABELS = {"active": "启用", "inactive": "停用", "archived": "已归档"}

ROLLOUT_STATUS = ("scheduled", "running", "paused", "completed")
ROLLOUT_STATUS_LABELS = {
    "scheduled": "待开始",
    "running": "进行中",
    "paused": "已暂停",
    "completed": "已完成",
}

EXPERIMENT_STATUS = ("draft", "running", "paused", "concluded")
EXPERIMENT_STATUS_LABELS = {
    "draft": "草稿",
    "running": "进行中",
    "paused": "已暂停",
    "concluded": "已结束",
}

METRIC_TYPES = ("conversion", "revenue", "count")
METRIC_TYPE_LABELS = {"conversion": "转化率", "revenue": "收入", "count": "计数"}

METRIC_DIRECTIONS = ("increase", "decrease")
METRIC_DIRECTION_LABELS = {"increase": "越大越好", "decrease": "越小越好"}

GUARDRAIL_ACTIONS = ("pause", "rollback", "notify")
GUARDRAIL_ACTION_LABELS = {"pause": "暂停灰度", "rollback": "回滚开关", "notify": "仅告警"}

DEPENDENCY_RELATIONS = ("requires", "forbids")
DEPENDENCY_RELATION_LABELS = {"requires": "依赖开启", "forbids": "依赖关闭"}

LOGIC_OPS = ("and", "or")
LOGIC_OP_LABELS = {"and": "全部满足", "or": "任一满足"}

# 条件求值器支持的操作符。列表也是目录接口对外暴露的能力清单，
# 新增操作符只需要在 services.evaluate_condition 增加分支并同步这里。
OPERATORS = (
    "eq",
    "neq",
    "in",
    "not_in",
    "contains",
    "starts_with",
    "ends_with",
    "gt",
    "gte",
    "lt",
    "lte",
    "regex",
    "semver_gte",
    "semver_lt",
)

OPERATOR_LABELS = {
    "eq": "等于",
    "neq": "不等于",
    "in": "属于集合",
    "not_in": "不属于集合",
    "contains": "包含",
    "starts_with": "前缀匹配",
    "ends_with": "后缀匹配",
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
    "regex": "正则匹配",
    "semver_gte": "版本大于等于",
    "semver_lt": "版本小于",
}

# 条件字段前缀：user.* 取用户属性，custom.* 取自定义属性，其余按扁平上下文取。
FIELD_PREFIXES = ("user.", "custom.")

# 评估日志保留条数。评估是高频写路径，日志只用于排障与统计，
# 超过上限后按时间截断，既保证可观测性又避免单表无限膨胀。
EVALUATION_LOG_KEEP = 2000

# 实验最少两个组：没有配置变体时使用 control/treatment 均分。
DEFAULT_EXPERIMENT_VARIANTS = ("control", "treatment")


class TimeStamped(models.Model):
    """只提供时间戳的抽象基类，owner 由各模型显式声明。

    这里不把 owner 放进抽象基类，是因为 ``related_name`` 需要逐模型唯一；
    用 ``%(class)s`` 虽然能自动生成，但反向名字会随类名变化，调用方难以检索。
    """

    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


class Project(TimeStamped):
    """功能开关项目：一个项目下可以有多个环境。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_projects",
        verbose_name="所有者",
    )
    name = models.CharField("名称", max_length=120)
    key = models.SlugField("项目标识", max_length=64, db_index=True)
    description = models.TextField("描述", blank=True, default="")
    environment_count = models.IntegerField("环境数量", default=0)
    members = models.JSONField("成员列表", default=list, blank=True)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)

    class Meta:
        verbose_name = "开关项目"
        verbose_name_plural = "开关项目"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="flags_project_owner_key_uniq"),
        ]

    def __str__(self):
        return f"{self.name} ({self.key})"

    def member_ids(self):
        """把 members JSON 归一成整数集合，脏数据（字符串/字典）直接忽略。"""
        out = set()
        for item in self.members or []:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                out.add(item)
            elif isinstance(item, str) and item.strip().isdigit():
                out.add(int(item.strip()))
            elif isinstance(item, dict):
                value = item.get("id")
                if isinstance(value, int):
                    out.add(value)
                elif isinstance(value, str) and value.isdigit():
                    out.add(int(value))
        return out

    def as_dict(self, stats=None):
        data = {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "description": self.description,
            "environment_count": self.environment_count,
            "members": self.members or [],
            "member_count": len(self.member_ids()),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if stats is not None:
            data["stats"] = stats
        return data


class Environment(TimeStamped):
    """项目环境：production / staging / dev，生产环境写操作会额外写审计。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_environments",
        verbose_name="所有者",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="environments",
        verbose_name="所属项目",
    )
    name = models.CharField("名称", max_length=80)
    key = models.SlugField("环境标识", max_length=64, db_index=True)
    env_type = models.CharField("环境类型", max_length=20, default="dev", db_index=True)
    sort_order = models.IntegerField("排序", default=0)
    enabled = models.BooleanField("是否启用", default=True)

    class Meta:
        verbose_name = "开关环境"
        verbose_name_plural = "开关环境"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "key"], name="flags_env_project_key_uniq"),
        ]

    def __str__(self):
        return f"{self.project.key}/{self.key}"

    @property
    def is_production(self):
        return self.env_type == "production"

    def as_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_key": getattr(self.project, "key", ""),
            "name": self.name,
            "key": self.key,
            "env_type": self.env_type,
            "env_type_label": ENV_TYPE_LABELS.get(self.env_type, self.env_type),
            "sort_order": self.sort_order,
            "enabled": self.enabled,
            "is_production": self.is_production,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Flag(TimeStamped):
    """功能开关。

    ``temporary`` 与 ``permanent`` 互斥：临时开关用于上线保护（到期应清理），
    永久开关用于长期配置。两者都为 False 视为未声明生命周期。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_flags",
        verbose_name="所有者",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="flags",
        verbose_name="所属项目",
    )
    environment = models.ForeignKey(
        Environment,
        on_delete=models.CASCADE,
        related_name="flags",
        verbose_name="所属环境",
    )
    key = models.SlugField("开关键名", max_length=120, db_index=True)
    name = models.CharField("名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    flag_type = models.CharField("类型", max_length=20, default="boolean", db_index=True)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    temporary = models.BooleanField("临时开关", default=False)
    permanent = models.BooleanField("永久开关", default=False)
    labels = models.JSONField("标签", default=list, blank=True)
    assignee = models.CharField("负责人", max_length=120, blank=True, default="")
    default_variant = models.CharField("默认变体", max_length=80, blank=True, default="")
    last_evaluated_at = models.DateTimeField("上次评估时间", null=True, blank=True)

    class Meta:
        verbose_name = "功能开关"
        verbose_name_plural = "功能开关"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "environment", "status"], name="flags_flag_scope_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["environment", "key"], name="flags_flag_env_key_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.key} [{self.environment_id}]"

    @property
    def is_boolean(self):
        return self.flag_type == "boolean"

    @property
    def is_active(self):
        return self.status == "active"

    def lifecycle(self):
        if self.temporary:
            return "temporary"
        if self.permanent:
            return "permanent"
        return "unspecified"

    def as_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_key": getattr(self.project, "key", ""),
            "environment_id": self.environment_id,
            "environment_key": getattr(self.environment, "key", ""),
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "flag_type": self.flag_type,
            "flag_type_label": FLAG_TYPE_LABELS.get(self.flag_type, self.flag_type),
            "status": self.status,
            "status_label": FLAG_STATUS_LABELS.get(self.status, self.status),
            "temporary": self.temporary,
            "permanent": self.permanent,
            "lifecycle": self.lifecycle(),
            "labels": self.labels or [],
            "assignee": self.assignee,
            "default_variant": self.default_variant,
            "last_evaluated_at": self.last_evaluated_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class FlagVersion(TimeStamped):
    """开关版本：发布时固化「变体 + 定向规则 + 灰度 + 基础属性」快照。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_flag_versions",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="所属开关",
    )
    version = models.IntegerField("版本号", default=1)
    rules_snapshot = models.JSONField("规则快照", default=dict, blank=True)
    change_note = models.TextField("变更说明", blank=True, default="")
    publisher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="flags_published_versions",
        verbose_name="发布人",
    )

    class Meta:
        verbose_name = "开关版本"
        verbose_name_plural = "开关版本"
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["flag", "version"], name="flags_version_flag_ver_uniq"),
        ]

    def __str__(self):
        return f"{self.flag_id}@v{self.version}"

    def as_dict(self, with_snapshot=True):
        data = {
            "id": self.id,
            "flag_id": self.flag_id,
            "version": self.version,
            "change_note": self.change_note,
            "publisher_id": self.publisher_id,
            "publisher": getattr(self.publisher, "username", "") if self.publisher_id else "",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if with_snapshot:
            data["rules_snapshot"] = self.rules_snapshot or {}
        return data


class Segment(TimeStamped):
    """用户细分：规则条件组合，命中后可被灰度与实验引用。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_segments",
        verbose_name="所有者",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="segments",
        verbose_name="所属项目",
    )
    name = models.CharField("名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    rules = models.JSONField("规则", default=list, blank=True)
    rule_match = models.CharField("规则组合", max_length=10, default="and")
    member_count = models.IntegerField("成员数缓存", default=0)

    class Meta:
        verbose_name = "用户细分"
        verbose_name_plural = "用户细分"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="flags_segment_proj_name_uniq"),
        ]

    def __str__(self):
        return f"{self.project_id}:{self.name}"

    def as_dict(self, with_rules=True):
        data = {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "rule_match": self.rule_match,
            "rule_count": len(self.rules or []) + self.segment_rules.count(),
            "member_count": self.member_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if with_rules:
            data["rules"] = self.rules or []
        return data


class SegmentRule(TimeStamped):
    """细分的单条结构化规则；与 Segment.rules 的 JSON 版本共存。

    提供独立表是为了让 UI 可以逐条增删改并排序，而 JSON 版本用于快速
    导入/导出与实验快照。求值时两者取并集（见 services.segment_conditions）。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_segment_rules",
        verbose_name="所有者",
    )
    segment = models.ForeignKey(
        Segment,
        on_delete=models.CASCADE,
        related_name="segment_rules",
        verbose_name="所属细分",
    )
    field = models.CharField("字段", max_length=120)
    operator = models.CharField("操作符", max_length=30, default="eq")
    value = models.JSONField("比较值", default=None, null=True, blank=True)
    logic = models.CharField("与上一条的关系", max_length=10, default="and")
    sort_order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = "细分规则"
        verbose_name_plural = "细分规则"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.field} {self.operator}"

    def as_dict(self):
        return {
            "id": self.id,
            "segment_id": self.segment_id,
            "field": self.field,
            "operator": self.operator,
            "operator_label": OPERATOR_LABELS.get(self.operator, self.operator),
            "value": self.value,
            "logic": self.logic,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Rollout(TimeStamped):
    """灰度发布：按百分比放量，可绑定细分与生效时间窗口。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_rollouts",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="rollouts",
        verbose_name="所属开关",
    )
    percentage = models.IntegerField("放量百分比", default=0)
    segment = models.ForeignKey(
        Segment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rollouts",
        verbose_name="限定细分",
    )
    salt = models.CharField("分桶盐值", max_length=120, blank=True, default="")
    start_at = models.DateTimeField("开始时间", null=True, blank=True)
    end_at = models.DateTimeField("结束时间", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="running", db_index=True)

    class Meta:
        verbose_name = "灰度发布"
        verbose_name_plural = "灰度发布"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["flag", "status"], name="flags_rollout_flag_status_idx"),
        ]

    def __str__(self):
        return f"rollout#{self.id} {self.percentage}%"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "percentage": self.percentage,
            "segment_id": self.segment_id,
            "segment_name": getattr(self.segment, "name", "") if self.segment_id else "",
            "salt": self.salt,
            "start_at": self.start_at,
            "end_at": self.end_at,
            "status": self.status,
            "status_label": ROLLOUT_STATUS_LABELS.get(self.status, self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TargetingRule(TimeStamped):
    """定向规则：按优先级求值，命中后返回指定变体或按权重选变体。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_targeting_rules",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="targeting_rules",
        verbose_name="所属开关",
    )
    priority = models.IntegerField("优先级", default=100)
    conditions = models.JSONField("条件", default=list, blank=True)
    condition_logic = models.CharField("条件组合", max_length=10, default="and")
    variant_key = models.CharField("返回变体", max_length=80, blank=True, default="")
    percentage = models.IntegerField("命中后放量", default=100)
    enabled = models.BooleanField("是否启用", default=True)
    note = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "定向规则"
        verbose_name_plural = "定向规则"
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["flag", "priority"], name="flags_target_flag_prio_uniq"
            ),
        ]

    def __str__(self):
        return f"target#{self.id} p{self.priority}"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "priority": self.priority,
            "conditions": self.conditions or [],
            "condition_logic": self.condition_logic,
            "variant_key": self.variant_key,
            "percentage": self.percentage,
            "enabled": self.enabled,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Variant(TimeStamped):
    """开关变体：多变量开关的返回选项，weight 决定分桶占比。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_variants",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name="所属开关",
    )
    key = models.SlugField("变体键", max_length=80)
    name = models.CharField("变体名称", max_length=120)
    weight = models.IntegerField("权重", default=0)
    payload = models.JSONField("负载", default=dict, blank=True)

    class Meta:
        verbose_name = "开关变体"
        verbose_name_plural = "开关变体"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["flag", "key"], name="flags_variant_flag_key_uniq"),
        ]

    def __str__(self):
        return f"{self.key}@{self.weight}"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "key": self.key,
            "name": self.name,
            "weight": self.weight,
            "payload": self.payload or {},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Experiment(TimeStamped):
    """A/B 实验：绑定一个开关，按用户稳定入组并记录曝光。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_experiments",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="experiments",
        verbose_name="所属开关",
    )
    name = models.CharField("实验名称", max_length=200)
    hypothesis = models.TextField("实验假设", blank=True, default="")
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)
    start_at = models.DateTimeField("开始时间", null=True, blank=True)
    end_at = models.DateTimeField("结束时间", null=True, blank=True)
    primary_metric = models.CharField("主指标", max_length=120, blank=True, default="")
    min_sample_size = models.IntegerField("最小样本量", default=100)
    description = models.TextField("描述", blank=True, default="")

    class Meta:
        verbose_name = "A/B 实验"
        verbose_name_plural = "A/B 实验"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["flag", "status"], name="flags_exp_flag_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["flag", "name"], name="flags_exp_flag_name_uniq"),
        ]

    def __str__(self):
        return f"{self.name} [{self.status}]"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "flag_key": getattr(self.flag, "key", ""),
            "name": self.name,
            "hypothesis": self.hypothesis,
            "status": self.status,
            "status_label": EXPERIMENT_STATUS_LABELS.get(self.status, self.status),
            "start_at": self.start_at,
            "end_at": self.end_at,
            "primary_metric": self.primary_metric,
            "min_sample_size": self.min_sample_size,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ExperimentMetric(TimeStamped):
    """实验指标定义：转化/收入/计数的口径与优化方向。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_experiment_metrics",
        verbose_name="所有者",
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="metrics",
        verbose_name="所属实验",
    )
    name = models.CharField("指标名称", max_length=120)
    metric_type = models.CharField("指标类型", max_length=20, default="conversion")
    unit = models.CharField("单位", max_length=40, blank=True, default="")
    direction = models.CharField("优化方向", max_length=20, default="increase")
    note = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "实验指标"
        verbose_name_plural = "实验指标"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "name"], name="flags_exp_metric_name_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.experiment_id}:{self.name}"

    def as_dict(self):
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "name": self.name,
            "metric_type": self.metric_type,
            "metric_type_label": METRIC_TYPE_LABELS.get(self.metric_type, self.metric_type),
            "unit": self.unit,
            "direction": self.direction,
            "direction_label": METRIC_DIRECTION_LABELS.get(self.direction, self.direction),
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Assignment(TimeStamped):
    """实验分组缓存：同一实验 + 用户只落一条，保证跨请求稳定入组。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_assignments",
        verbose_name="所有者",
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="所属实验",
    )
    user_key = models.CharField("用户键", max_length=200, db_index=True)
    variant_key = models.CharField("变体", max_length=80)
    bucket = models.IntegerField("分桶值", default=0)

    class Meta:
        verbose_name = "实验分组"
        verbose_name_plural = "实验分组"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "user_key"], name="flags_assign_exp_user_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.user_key} -> {self.variant_key}"

    def as_dict(self):
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "user_key": self.user_key,
            "variant_key": self.variant_key,
            "bucket": self.bucket,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Exposure(TimeStamped):
    """曝光记录：实验 + 用户键唯一，重复上报走幂等更新而不是插入。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_exposures",
        verbose_name="所有者",
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="exposures",
        verbose_name="所属实验",
    )
    user_key = models.CharField("用户键", max_length=200, db_index=True)
    variant_key = models.CharField("变体", max_length=80)
    exposed_at = models.DateTimeField("曝光时间", null=True, blank=True)
    context = models.JSONField("上下文", default=dict, blank=True)

    class Meta:
        verbose_name = "实验曝光"
        verbose_name_plural = "实验曝光"
        ordering = ["-exposed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "user_key"], name="flags_exposure_exp_user_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.user_key} @ {self.variant_key}"

    def as_dict(self):
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "user_key": self.user_key,
            "variant_key": self.variant_key,
            "exposed_at": self.exposed_at,
            "context": self.context or {},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class EvaluationLog(TimeStamped):
    """评估日志：开关 + 用户 + 结果 + 命中原因 + 耗时。

    environment 用 SET_NULL：删环境不应连带删掉历史评估数据（统计仍需要）。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_evaluation_logs",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="evaluation_logs",
        verbose_name="所属开关",
    )
    environment = models.ForeignKey(
        Environment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluation_logs",
        verbose_name="环境",
    )
    user_key = models.CharField("用户键", max_length=200, db_index=True)
    result = models.JSONField("评估结果", default=dict, blank=True)
    matched_rule = models.CharField("命中规则", max_length=200, blank=True, default="")
    latency_ms = models.FloatField("耗时(ms)", default=0)
    evaluated_at = models.DateTimeField("评估时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "评估日志"
        verbose_name_plural = "评估日志"
        ordering = ["-evaluated_at"]
        indexes = [
            models.Index(fields=["flag", "-evaluated_at"], name="flags_evallog_flag_time_idx"),
            models.Index(fields=["environment", "-evaluated_at"], name="flags_evallog_env_time_idx"),
        ]

    def __str__(self):
        return f"{self.flag_id}:{self.user_key}"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "flag_key": getattr(self.flag, "key", ""),
            "environment_id": self.environment_id,
            "user_key": self.user_key,
            "result": self.result or {},
            "matched_rule": self.matched_rule,
            "latency_ms": self.latency_ms,
            "evaluated_at": self.evaluated_at,
            "created_at": self.created_at,
        }


class Audience(TimeStamped):
    """受众：项目级的可复用用户集合定义，供定向/实验选人。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_audiences",
        verbose_name="所有者",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="audiences",
        verbose_name="所属项目",
    )
    name = models.CharField("名称", max_length=120)
    rules = models.JSONField("规则", default=list, blank=True)
    rule_logic = models.CharField("规则组合", max_length=10, default="and")
    description = models.TextField("描述", blank=True, default="")
    member_count = models.IntegerField("成员数缓存", default=0)

    class Meta:
        verbose_name = "受众"
        verbose_name_plural = "受众"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="flags_audience_proj_name_uniq"),
        ]

    def __str__(self):
        return f"{self.project_id}:{self.name}"

    def as_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "rules": self.rules or [],
            "rule_logic": self.rule_logic,
            "description": self.description,
            "member_count": self.member_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class FlagDependency(TimeStamped):
    """开关依赖：本开关 requires（依赖上游开启）或 forbids（要求上游关闭）。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_dependencies",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="dependencies",
        verbose_name="本开关",
    )
    depends_on = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="dependents",
        verbose_name="依赖开关",
    )
    expected_value = models.JSONField("期望值", default=None, null=True, blank=True)
    relation = models.CharField("关系", max_length=20, default="requires")

    class Meta:
        verbose_name = "开关依赖"
        verbose_name_plural = "开关依赖"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["flag", "depends_on"], name="flags_dependency_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.flag_id} {self.relation} {self.depends_on_id}"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "depends_on_id": self.depends_on_id,
            "depends_on_key": getattr(self.depends_on, "key", ""),
            "expected_value": self.expected_value,
            "relation": self.relation,
            "relation_label": DEPENDENCY_RELATION_LABELS.get(self.relation, self.relation),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Guardrail(TimeStamped):
    """护栏：实验/灰度期间监控指标，超阈值时按动作记录并处置。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_guardrails",
        verbose_name="所有者",
    )
    flag = models.ForeignKey(
        Flag,
        on_delete=models.CASCADE,
        related_name="guardrails",
        verbose_name="所属开关",
    )
    metric = models.CharField("监控指标", max_length=120)
    threshold = models.FloatField("阈值", default=0)
    window_minutes = models.IntegerField("观察窗口(分钟)", default=60)
    action = models.CharField("触发动作", max_length=20, default="notify")
    comparator = models.CharField("比较方向", max_length=4, default="gte")
    triggered_at = models.DateTimeField("最近触发时间", null=True, blank=True)
    triggered_count = models.IntegerField("触发次数", default=0)
    last_value = models.FloatField("最近观测值", null=True, blank=True)

    class Meta:
        verbose_name = "实验护栏"
        verbose_name_plural = "实验护栏"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["flag", "metric"], name="flags_guardrail_flag_metric_uniq"),
        ]

    def __str__(self):
        return f"{self.metric} {self.comparator} {self.threshold}"

    def as_dict(self):
        return {
            "id": self.id,
            "flag_id": self.flag_id,
            "metric": self.metric,
            "threshold": self.threshold,
            "window_minutes": self.window_minutes,
            "action": self.action,
            "action_label": GUARDRAIL_ACTION_LABELS.get(self.action, self.action),
            "comparator": self.comparator,
            "triggered_at": self.triggered_at,
            "triggered_count": self.triggered_count,
            "last_value": self.last_value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class AuditEvent(TimeStamped):
    """审计事件：谁在什么对象上做了什么，前后值是什么。

    actor 用 SET_NULL：用户注销后审计记录仍需保留（操作者名字另存在
    actor_name 快照里），这是审计与普通业务外键最大的区别。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flags_audit_events",
        verbose_name="所有者",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name="所属项目",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="flags_audit_actions",
        verbose_name="操作者",
    )
    actor_name = models.CharField("操作者名称", max_length=120, blank=True, default="")
    object_type = models.CharField("对象类型", max_length=40, db_index=True)
    object_id = models.IntegerField("对象ID", default=0, db_index=True)
    action = models.CharField("动作", max_length=60, db_index=True)
    before = models.JSONField("变更前", default=dict, blank=True)
    after = models.JSONField("变更后", default=dict, blank=True)
    note = models.CharField("备注", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "开关审计"
        verbose_name_plural = "开关审计"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"], name="flags_audit_proj_time_idx"),
            models.Index(fields=["object_type", "object_id"], name="flags_audit_obj_idx"),
        ]

    def __str__(self):
        return f"{self.action} {self.object_type}#{self.object_id}"

    def as_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "actor_id": self.actor_id,
            "actor": self.actor_name,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "action": self.action,
            "before": self.before or {},
            "after": self.after or {},
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
