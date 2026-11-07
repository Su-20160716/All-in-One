# -*- coding: utf-8 -*-
"""rules 数据模型：规则集 / 规则 / 决策表 / 评估与执行审计 / 仿真与审批。

设计约定（与平台既有应用一致）：
- 所有模型统一挂 owner 外键，行级权限由 core.scoping 收口，模型层不再造权限字段；
- 所有模型带 created_at / updated_at（审计轨迹一律可回放）；
- 结构化配置（事实、动作参数、条件单元格、快照）统一用 JSONField，
  避免为每种动作/单元格形态新增列，也便于导入导出原样往返；
- related_name 全部以 rr_ 前缀手工命名：一个用户会关联十几种规则对象，
  默认的 %(class)s_set 在跨应用时容易重名，显式命名让反向查询可读且稳定。
"""
from django.conf import settings
from django.db import models

# ---------------------------------------------------------------------------
# 枚举常量：视图层与前端目录共用，集中定义避免字符串各写各的
# ---------------------------------------------------------------------------

RULESET_STATUS = ("draft", "active", "paused", "archived")
RULESET_STATUS_LABELS = {
    "draft": "草稿",
    "active": "生效中",
    "paused": "已暂停",
    "archived": "已归档",
}

HIT_POLICIES = ("first", "all", "priority", "collect")
HIT_POLICY_LABELS = {
    "first": "首条命中",
    "all": "全部命中",
    "priority": "最高优先级命中",
    "collect": "汇总所有命中输出",
}

ACTION_TYPES = (
    "set_field",
    "notify",
    "webhook",
    "approve",
    "reject",
    "route",
    "create_task",
    "score",
    "flag",
)
ACTION_TYPE_LABELS = {
    "set_field": "设置字段",
    "notify": "站内通知",
    "webhook": "Webhook 投递",
    "approve": "输出通过决策",
    "reject": "输出驳回决策",
    "route": "路由分派",
    "create_task": "创建任务",
    "score": "评分累加",
    "flag": "打标",
}

# 条件可视化编辑使用的操作符（展示值）；引擎内部会翻译成表达式。
CONDITION_OPERATORS = (
    "==", "!=", ">", ">=", "<", "<=",
    "in", "not_in", "contains", "not_contains",
    "between", "is_null", "is_not_null", "matches", "like",
)
CONDITION_OPERATOR_LABELS = {
    "==": "等于",
    "!=": "不等于",
    ">": "大于",
    ">=": "大于等于",
    "<": "小于",
    "<=": "小于等于",
    "in": "属于集合",
    "not_in": "不属于集合",
    "contains": "包含",
    "not_contains": "不包含",
    "between": "介于区间",
    "is_null": "为空",
    "is_not_null": "不为空",
    "matches": "正则匹配",
    "like": "模糊匹配",
}

VARIABLE_TYPES = ("string", "number", "boolean", "date", "json")

CONFLICT_TYPES = ("duplicate", "overlap", "unreachable", "contradiction", "shadowed")
CONFLICT_TYPE_LABELS = {
    "duplicate": "条件重复",
    "overlap": "条件重叠",
    "unreachable": "不可达规则",
    "contradiction": "动作冲突",
    "shadowed": "被高优先级规则覆盖",
}
CONFLICT_SEVERITIES = ("low", "medium", "high")
CONFLICT_STATUS = ("open", "resolved", "ignored")

APPROVAL_STATUS = ("pending", "approved", "rejected", "cancelled")
EXECUTION_STATUS = ("success", "failed", "skipped")
EVALUATION_STATUS = ("success", "degraded", "timeout", "error")
TASK_STATUS = ("open", "done", "cancelled")
NOTIFICATION_STATUS = ("queued", "sent", "failed", "read")


# ---------------------------------------------------------------------------
# 规则集与版本
# ---------------------------------------------------------------------------


class RuleSet(models.Model):
    """规则集：一组规则的运行单元，承载命中策略与执行预算。

    命中策略决定多条规则同时命中时如何取舍：
    - first    : 按优先级取第一条命中，最省算力；
    - all      : 全部命中的动作都执行（如多条提醒）；
    - priority : 只执行优先级最高的一条（优先级数值越小越优先）；
    - collect  : 全部执行并把各自输出汇总成数组，供评分/路由聚合场景使用。
    max_executions / timeout_ms 是运行时护栏：规则再多也必须有执行上限，
    否则一次错误配置就能拖垮请求线程。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_sets", verbose_name="所有者",
    )
    code = models.CharField("编码", max_length=64, db_index=True)
    name = models.CharField("名称", max_length=200)
    category = models.CharField("分类", max_length=60, default="自定义", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField("状态", max_length=20, default="draft",
                              choices=[(s, RULESET_STATUS_LABELS[s]) for s in RULESET_STATUS],
                              db_index=True)
    version_no = models.IntegerField("当前版本号", default=1)
    hit_policy = models.CharField("命中策略", max_length=20, default="first",
                                  choices=[(s, HIT_POLICY_LABELS[s]) for s in HIT_POLICIES])
    max_executions = models.IntegerField("最多执行规则数", default=100)
    timeout_ms = models.IntegerField("超时毫秒", default=2000)
    priority = models.IntegerField("规则集优先级", default=0)
    tags = models.JSONField("标签", default=list, blank=True)
    settings = models.JSONField("扩展配置", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则集"
        verbose_name_plural = "规则集"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="rr_ruleset_owner_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["status", "category"], name="rr_ruleset_status_cat_idx"),
        ]

    def __str__(self):
        return f"{self.code} {self.name} [{self.status}]"


class RuleSetVersion(models.Model):
    """规则集版本快照：发布时把整套规则序列化留档，支持对比与回滚。

    快照是「发布态」的唯一真相：线上评估只读当前表，回滚时用快照整体覆盖，
    这样即使中途有人手工改表，也能回到某个已知可用版本。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_ruleset_versions", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="versions", verbose_name="规则集")
    version_no = models.IntegerField("版本号")
    snapshot = models.JSONField("快照", default=dict, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rr_published_versions", verbose_name="发布人",
    )
    note = models.CharField("发布说明", max_length=500, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则集版本"
        verbose_name_plural = "规则集版本"
        ordering = ["-version_no", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["ruleset", "version_no"],
                                    name="rr_version_ruleset_no_uniq"),
        ]

    def __str__(self):
        return f"{self.ruleset_id} v{self.version_no}"


# ---------------------------------------------------------------------------
# 规则 / 条件 / 动作 / 变量
# ---------------------------------------------------------------------------


class Rule(models.Model):
    """单条规则：条件表达式 + 动作列表。

    condition 手写表达式与 RuleCondition 可视化条件二选一：
    有 condition 时优先使用；为空时由 services 依据 conditions 拼装。
    这样既支持高级用户直接写表达式，也支持低代码页面拖拽生成。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rules", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="rules", verbose_name="规则集")
    name = models.CharField("规则名称", max_length=200)
    description = models.CharField("说明", max_length=500, blank=True, default="")
    priority = models.IntegerField("优先级", default=100)
    enabled = models.BooleanField("启用", default=True, db_index=True)
    condition = models.TextField("条件表达式", blank=True, default="")
    actions = models.JSONField("动作列表", default=list, blank=True)
    tags = models.JSONField("标签", default=list, blank=True)
    hit_count = models.IntegerField("命中次数", default=0)
    last_hit_at = models.DateTimeField("最后命中时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则"
        verbose_name_plural = "规则"
        ordering = ["priority", "id"]
        indexes = [
            models.Index(fields=["ruleset", "enabled", "priority"],
                         name="rr_rule_set_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.name}(p{self.priority})"


class RuleCondition(models.Model):
    """可视化条件：一行一个「字段 操作符 值」，logic_group 表示与前一行的连接方式。

    第一行的 logic_group 无意义（默认 and），保留字段是为了前端表格不跳列。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_conditions", verbose_name="所有者",
    )
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE,
                             related_name="conditions", verbose_name="规则")
    field = models.CharField("字段路径", max_length=200)
    operator = models.CharField("操作符", max_length=20, default="==")
    value = models.JSONField("比较值", null=True, blank=True, default=None)
    logic_group = models.CharField("逻辑组", max_length=3, default="and")
    sort_order = models.IntegerField("排序", default=0)
    enabled = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则条件"
        verbose_name_plural = "规则条件"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.field} {self.operator} {self.value!r}"


class RuleAction(models.Model):
    """动作行：与 Rule.actions 等价，但可逐条启停与排序（可视化编辑用）。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_actions", verbose_name="所有者",
    )
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE,
                             related_name="action_items", verbose_name="规则")
    type = models.CharField("动作类型", max_length=20, default="set_field",
                            choices=[(t, ACTION_TYPE_LABELS[t]) for t in ACTION_TYPES])
    params = models.JSONField("参数", default=dict, blank=True)
    sort_order = models.IntegerField("排序", default=0)
    enabled = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则动作"
        verbose_name_plural = "规则动作"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.type}#{self.sort_order}"


class RuleVariable(models.Model):
    """规则变量：给表达式提供带默认值的符号，避免把魔法值写死在条件里。

    变量参与求值时优先级低于调用方显式传入的同名值，方便灰度覆盖。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_variables", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="variables", verbose_name="规则集")
    name = models.CharField("变量名", max_length=80)
    var_type = models.CharField("类型", max_length=20, default="string",
                                choices=[(t, t) for t in VARIABLE_TYPES])
    default_value = models.JSONField("默认值", null=True, blank=True, default=None)
    description = models.CharField("说明", max_length=300, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则变量"
        verbose_name_plural = "规则变量"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["ruleset", "name"], name="rr_var_ruleset_name_uniq"),
        ]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 评估 / 执行日志
# ---------------------------------------------------------------------------


class RuleEvaluation(models.Model):
    """一次规则集评估的完整留痕：事实、命中、决策、耗时与追踪 ID。

    trace 为前端调试面板准备（条件树 + 每步布尔值），体积受服务层截断，
    避免一个超大事实把 JSON 字段撑爆。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_evaluations", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="evaluations", verbose_name="规则集")
    ruleset_code = models.CharField("规则集编码", max_length=64, blank=True, default="")
    facts = models.JSONField("输入事实", default=dict, blank=True)
    variables = models.JSONField("变量", default=dict, blank=True)
    matched_rules = models.JSONField("命中规则", default=list, blank=True)
    decision = models.JSONField("决策结果", default=dict, blank=True)
    trace = models.JSONField("追踪详情", default=dict, blank=True)
    duration_ms = models.FloatField("耗时毫秒", default=0)
    caller = models.CharField("调用方", max_length=100, blank=True, default="api")
    trace_id = models.CharField("追踪 ID", max_length=64, blank=True, default="", db_index=True)
    status = models.CharField("状态", max_length=20, default="success", db_index=True)
    error = models.TextField("错误", blank=True, default="")
    source = models.CharField("来源", max_length=40, blank=True, default="manual")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则评估"
        verbose_name_plural = "规则评估"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ruleset", "created_at"], name="rr_eval_ruleset_time_idx"),
            models.Index(fields=["owner", "status"], name="rr_eval_owner_status_idx"),
        ]

    def __str__(self):
        return f"eval#{self.pk} {self.ruleset_code} {self.status}"


class RuleExecutionLog(models.Model):
    """动作执行日志：每个动作一条，失败不吞——错误原文与重试次数都要能查。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_execution_logs", verbose_name="所有者",
    )
    evaluation = models.ForeignKey(RuleEvaluation, on_delete=models.CASCADE,
                                   null=True, blank=True, related_name="logs",
                                   verbose_name="评估")
    rule = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="execution_logs", verbose_name="规则")
    rule_name = models.CharField("规则名", max_length=200, blank=True, default="")
    action_type = models.CharField("动作类型", max_length=20, blank=True, default="")
    status = models.CharField("状态", max_length=20, default="success", db_index=True)
    error = models.TextField("错误", blank=True, default="")
    retries = models.IntegerField("重试次数", default=0)
    duration_ms = models.FloatField("耗时毫秒", default=0)
    detail = models.JSONField("执行明细", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "动作执行日志"
        verbose_name_plural = "动作执行日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["evaluation", "status"], name="rr_log_eval_status_idx"),
        ]

    def __str__(self):
        return f"log#{self.pk} {self.action_type} {self.status}"


# ---------------------------------------------------------------------------
# 测试用例 / 仿真
# ---------------------------------------------------------------------------


class RuleTestCase(models.Model):
    """回归用例：固定输入事实 + 期望输出，批量运行后给出通过率与覆盖率。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_test_cases", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="test_cases", verbose_name="规则集")
    name = models.CharField("用例名称", max_length=200)
    facts = models.JSONField("输入事实", default=dict, blank=True)
    expected = models.JSONField("期望输出", default=dict, blank=True)
    passed = models.BooleanField("是否通过", default=False)
    last_run_at = models.DateTimeField("最后运行时间", null=True, blank=True)
    last_result = models.JSONField("最后结果", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则测试用例"
        verbose_name_plural = "规则测试用例"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class RuleSimulation(models.Model):
    """批量仿真：一次灌入多条事实，产出命中分布与耗时分位，用于上线前压测。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_simulations", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="simulations", verbose_name="规则集")
    name = models.CharField("仿真名称", max_length=200, default="批量仿真")
    facts = models.JSONField("事实批次", default=list, blank=True)
    summary = models.JSONField("结果摘要", default=dict, blank=True)
    results = models.JSONField("逐条结果", default=list, blank=True)
    duration_ms = models.FloatField("总耗时毫秒", default=0)
    status = models.CharField("状态", max_length=20, default="success")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则仿真"
        verbose_name_plural = "规则仿真"
        ordering = ["-created_at"]

    def __str__(self):
        return f"sim#{self.pk} {self.name}"


# ---------------------------------------------------------------------------
# 决策表
# ---------------------------------------------------------------------------


class RuleDecisionTable(models.Model):
    """决策表：输入列 × 条件单元格 × 输出列，比规则表达式更贴近业务填表习惯。

    inputs / outputs 均存 [{"name","field","type"}]；field 为空时按 name 取事实。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_decision_tables", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="decision_tables", verbose_name="决策表")
    name = models.CharField("名称", max_length=200)
    description = models.CharField("说明", max_length=500, blank=True, default="")
    inputs = models.JSONField("输入列", default=list, blank=True)
    outputs = models.JSONField("输出列", default=list, blank=True)
    hit_policy = models.CharField("命中策略", max_length=20, default="first")
    enabled = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "决策表"
        verbose_name_plural = "决策表"
        ordering = ["id"]

    def __str__(self):
        return self.name


class DecisionRow(models.Model):
    """决策表行：conditions 以列名为键，值支持通配 * / 区间 / 集合 / 比较前缀。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_decision_rows", verbose_name="所有者",
    )
    table = models.ForeignKey(RuleDecisionTable, on_delete=models.CASCADE,
                              related_name="rows", verbose_name="决策表")
    conditions = models.JSONField("条件单元格", default=dict, blank=True)
    outputs = models.JSONField("输出", default=dict, blank=True)
    priority = models.IntegerField("优先级", default=100)
    enabled = models.BooleanField("启用", default=True)
    remark = models.CharField("备注", max_length=300, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "决策表行"
        verbose_name_plural = "决策表行"
        ordering = ["priority", "id"]

    def __str__(self):
        return f"row#{self.pk} p{self.priority}"


# ---------------------------------------------------------------------------
# 调度 / 冲突 / 审批
# ---------------------------------------------------------------------------


class RuleSchedule(models.Model):
    """调度：简化 cron（分 时 日 月 周）驱动规则集周期性评估。

    next_run_at 落库而不是每次现算：扫描接口按索引取到期任务，
    避免每次轮询把所有 cron 重新展开一遍。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_schedules", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="schedules", verbose_name="规则集")
    name = models.CharField("调度名称", max_length=200, blank=True, default="")
    cron = models.CharField("cron 表达式", max_length=120, default="*/5 * * * *")
    facts = models.JSONField("预设事实", default=dict, blank=True)
    enabled = models.BooleanField("启用", default=True)
    last_run_at = models.DateTimeField("上次运行时间", null=True, blank=True)
    next_run_at = models.DateTimeField("下次运行时间", null=True, blank=True, db_index=True)
    run_count = models.IntegerField("运行次数", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则调度"
        verbose_name_plural = "规则调度"
        ordering = ["next_run_at", "id"]

    def __str__(self):
        return f"{self.name or self.cron}({self.ruleset_id})"


class RuleConflict(models.Model):
    """冲突记录：规则对之间的重复/重叠/不可达/动作矛盾，检测结果持久化便于跟踪处理。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_conflicts", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="conflicts", verbose_name="规则集")
    rule_a = models.ForeignKey(Rule, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="conflicts_as_a", verbose_name="规则A")
    rule_b = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="conflicts_as_b", verbose_name="规则B")
    conflict_type = models.CharField("冲突类型", max_length=20, default="overlap")
    severity = models.CharField("严重度", max_length=20, default="medium")
    status = models.CharField("状态", max_length=20, default="open", db_index=True)
    detail = models.JSONField("明细", default=dict, blank=True)
    note = models.CharField("处理说明", max_length=500, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则冲突"
        verbose_name_plural = "规则冲突"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ruleset", "status"], name="rr_conflict_set_status_idx"),
        ]

    def __str__(self):
        return f"{self.conflict_type} {self.rule_a_id}/{self.rule_b_id}"


class RuleApproval(models.Model):
    """规则变更审批：高风险规则集的上线/回滚先走审批，通过后才落库生效。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_approvals", verbose_name="申请人",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,
                                related_name="approvals", verbose_name="规则集")
    change = models.JSONField("变更内容", default=dict, blank=True)
    status = models.CharField("状态", max_length=20, default="pending", db_index=True)
    note = models.CharField("说明", max_length=500, blank=True, default="")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rr_reviewed_approvals", verbose_name="审批人",
    )
    review_note = models.CharField("审批意见", max_length=500, blank=True, default="")
    reviewed_at = models.DateTimeField("审批时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则变更审批"
        verbose_name_plural = "规则变更审批"
        ordering = ["-created_at"]

    def __str__(self):
        return f"approval#{self.pk} {self.status}"


# ---------------------------------------------------------------------------
# 标签 / 模板 / 任务 / 通知
# ---------------------------------------------------------------------------


class RuleTag(models.Model):
    """标签字典：规则集多对多挂载，用于跨分类筛选与治理看板。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_tags", verbose_name="所有者",
    )
    name = models.CharField("标签名", max_length=60)
    color = models.CharField("颜色", max_length=20, default="#409eff")
    rulesets = models.ManyToManyField(RuleSet, related_name="tag_refs", blank=True,
                                      verbose_name="规则集")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则标签"
        verbose_name_plural = "规则标签"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="rr_tag_owner_name_uniq"),
        ]

    def __str__(self):
        return self.name


class RuleTemplate(models.Model):
    """规则模板：把一套规则集结构保存为可复用模板；内置模板由服务层常量提供。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_templates", verbose_name="所有者",
    )
    name = models.CharField("模板名", max_length=200)
    category = models.CharField("分类", max_length=60, default="通用")
    description = models.CharField("说明", max_length=500, blank=True, default="")
    template = models.JSONField("模板内容", default=dict, blank=True)
    builtin = models.BooleanField("内置", default=False)
    usage_count = models.IntegerField("使用次数", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则模板"
        verbose_name_plural = "规则模板"
        ordering = ["-builtin", "name"]

    def __str__(self):
        return self.name


class RuleTask(models.Model):
    """动作 create_task 的落库目标：规则命中后生成的人工跟进任务。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_tasks", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="tasks", verbose_name="规则集")
    rule = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="tasks", verbose_name="规则")
    evaluation = models.ForeignKey(RuleEvaluation, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="tasks", verbose_name="评估")
    title = models.CharField("任务标题", max_length=300)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rr_assigned_rule_tasks", verbose_name="处理人",
    )
    due_date = models.DateField("截止日期", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="open", db_index=True)
    payload = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则任务"
        verbose_name_plural = "规则任务"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class RuleNotification(models.Model):
    """动作 notify / webhook 的投递台账。

    站内通知直接落本表；webhook 因平台禁止联网而记录为 queued 模拟投递，
    保留 url 与 payload 供审计，不发起真实外部请求。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rr_rule_notifications", verbose_name="所有者",
    )
    ruleset = models.ForeignKey(RuleSet, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="notifications", verbose_name="规则集")
    rule = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="notifications", verbose_name="规则")
    evaluation = models.ForeignKey(RuleEvaluation, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="notifications", verbose_name="评估")
    channel = models.CharField("渠道", max_length=20, default="inapp")
    target = models.CharField("接收方/地址", max_length=300, blank=True, default="")
    title = models.CharField("标题", max_length=300, blank=True, default="")
    body = models.TextField("正文", blank=True, default="")
    status = models.CharField("状态", max_length=20, default="queued", db_index=True)
    payload = models.JSONField("载荷", default=dict, blank=True)
    sent_at = models.DateTimeField("发送时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "规则通知"
        verbose_name_plural = "规则通知"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel}:{self.title}"
