# -*- coding: utf-8 -*-
"""可观测性中心 · 数据模型（20 张表）。

设计要点
--------
1. **行级权限唯一收口**：所有业务表都带 ``owner`` 外键，写权限走
   ``core.scoping.can_write``，读权限走数据范围；related_name 一律以
   ``obs_`` 前缀并逐表区分，避免与其它应用抢 User 的反向关系。
2. **时间戳统一**：``created_at`` 自动写入、``updated_at`` 自动刷新；
   业务时间（指标时间戳、告警开始时间、事故起止）单独建模，因为它们
   是「数据本身的属性」，不能与「记录被修改的时间」混用 —— 补录历史
   指标点时必须能写入过去的 timestamp。
3. **指标点写多读多**：MetricPoint 只放最小必要列（值/时间/标签/来源），
   在 (指标, 时间) 上建联合索引；标签走 JSONField，避免为任意维度建表
   导致迁移碎片化。聚合、分位、降采样全部在服务层按批读取后计算。
4. **SLO 计算快照落库**：SloWindow 保存每次计算的窗口结果，ErrorBudget
   保存预算消耗。这样「历史达成率」「预算燃尽趋势」不需要每次重算全量
   指标点，也让复盘时能回看当时的判定口径。
5. **告警/事故/值班是真实可用的状态机**：AlertRule 表达式 + 持续时间为
   唯一真相，AlertEvent 记录触发与恢复；Incident 的合法流转由服务层
   校验（open→acknowledged→mitigated→resolved→postmortem），非法流转
   返回 400，而不是静默改写状态。
6. **金额/百分比用 FloatField 是刻意的**：可观测性里的达成率、错误率、
   预算消耗是统计量而非账务金额，不需要十进制精度；用 Float 便于直接
   与前端图表对齐。
"""
from django.conf import settings
from django.db import models

# ---------------------------------------------------------------------------
# 枚举：同时导出 *_LABELS 供目录接口与视图校验使用，避免字符串字面量散落
# ---------------------------------------------------------------------------

SERVICE_LEVELS = ("P0", "P1", "P2", "P3")
SERVICE_LEVEL_LABELS = {"P0": "核心", "P1": "重要", "P2": "一般", "P3": "边缘"}

SERVICE_STATUS = ("healthy", "degraded", "down", "maintenance", "retired")
SERVICE_STATUS_LABELS = {
    "healthy": "健康",
    "degraded": "降级",
    "down": "故障",
    "maintenance": "维护中",
    "retired": "已下线",
}

ENDPOINT_STATUS = ("up", "degraded", "down", "retired")
ENDPOINT_STATUS_LABELS = {
    "up": "正常",
    "degraded": "降级",
    "down": "不可用",
    "retired": "已下线",
}

METRIC_TYPES = ("gauge", "counter", "histogram")
METRIC_TYPE_LABELS = {"gauge": "瞬时值", "counter": "计数器", "histogram": "直方图"}

SLO_TYPES = ("availability", "latency", "error_rate")
SLO_TYPE_LABELS = {"availability": "可用性", "latency": "延迟", "error_rate": "错误率"}

SLO_STATUS = ("active", "paused", "draft")
SLO_STATUS_LABELS = {"active": "生效中", "paused": "已暂停", "draft": "草稿"}

ALERT_SEVERITIES = ("critical", "warning", "info")
ALERT_SEVERITY_LABELS = {"critical": "严重", "warning": "警告", "info": "提示"}

ALERT_RULE_STATUS = ("active", "disabled", "muted")
ALERT_RULE_STATUS_LABELS = {"active": "启用", "disabled": "停用", "muted": "静默中"}

ALERT_EVENT_STATUS = ("firing", "resolved", "suppressed")
ALERT_EVENT_STATUS_LABELS = {
    "firing": "触发中",
    "resolved": "已恢复",
    "suppressed": "已抑制",
}

INCIDENT_STATUS = ("open", "acknowledged", "mitigated", "resolved", "postmortem")
INCIDENT_STATUS_LABELS = {
    "open": "待响应",
    "acknowledged": "已确认",
    "mitigated": "已缓解",
    "resolved": "已解决",
    "postmortem": "已复盘",
}

INCIDENT_SEVERITIES = ("sev1", "sev2", "sev3", "sev4")
INCIDENT_SEVERITY_LABELS = {
    "sev1": "S1 灾难",
    "sev2": "S2 严重",
    "sev3": "S3 一般",
    "sev4": "S4 轻微",
}

ONCALL_ROTATIONS = ("daily", "weekly")
ONCALL_ROTATION_LABELS = {"daily": "按日轮换", "weekly": "按周轮换"}

HEALTH_CHECK_TYPES = ("http", "tcp", "db", "custom")
HEALTH_CHECK_TYPE_LABELS = {
    "http": "HTTP 探活",
    "tcp": "TCP 探活",
    "db": "数据库探测",
    "custom": "自定义脚本",
}

HEALTH_STATUS = ("up", "down", "degraded", "unknown")
HEALTH_STATUS_LABELS = {
    "up": "正常",
    "down": "不可用",
    "degraded": "降级",
    "unknown": "未知",
}

DEPENDENCY_TYPES = ("http", "grpc", "db", "queue", "cache", "external")
DEPENDENCY_TYPE_LABELS = {
    "http": "HTTP 调用",
    "grpc": "gRPC 调用",
    "db": "数据库",
    "queue": "消息队列",
    "cache": "缓存",
    "external": "外部依赖",
}

CRITICALITIES = ("critical", "high", "medium", "low")
CRITICALITY_LABELS = {
    "critical": "致命",
    "high": "高",
    "medium": "中",
    "low": "低",
}

PANEL_CHART_TYPES = ("line", "area", "bar", "gauge", "stat", "table", "heatmap")
PANEL_CHART_TYPE_LABELS = {
    "line": "折线",
    "area": "面积",
    "bar": "柱状",
    "gauge": "仪表",
    "stat": "单值",
    "table": "表格",
    "heatmap": "热力图",
}

RUNBOOK_STATUS = ("draft", "active", "retired")
RUNBOOK_STATUS_LABELS = {"draft": "草稿", "active": "生效", "retired": "已下线"}

RUNBOOK_EXEC_STATUS = ("running", "succeeded", "failed", "aborted")
RUNBOOK_EXEC_STATUS_LABELS = {
    "running": "执行中",
    "succeeded": "成功",
    "failed": "失败",
    "aborted": "已中止",
}

SILENCE_STATUS = ("active", "expired", "cancelled")
SILENCE_STATUS_LABELS = {
    "active": "生效中",
    "expired": "已过期",
    "cancelled": "已取消",
}

BUDGET_STATUS = ("healthy", "warning", "exhausted")
BUDGET_STATUS_LABELS = {
    "healthy": "健康",
    "warning": "预警",
    "exhausted": "已耗尽",
}


# ---------------------------------------------------------------------------
# 抽象基类：owner + 时间戳，三个字段在 20 张表里语义一致
# ---------------------------------------------------------------------------


class ObservabilityBase(models.Model):
    """所有可观测性表的公共字段。

    ``owner`` 上不建反向名（由子类显式给出 related_name），因为抽象基类
    无法保证 ``%(class)s`` 与其它应用的命名不冲突；显式命名让权限审计
    时能一眼看出反向关系属于哪张表。
    """

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 1. 服务与端点
# ---------------------------------------------------------------------------


class Service(ObservabilityBase):
    """被观测的服务（一个可部署单元），是绝大多数数据表的归属根。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_services", verbose_name="负责人账号")
    name = models.CharField("服务名称", max_length=120, db_index=True)
    slug = models.CharField("服务标识", max_length=80, db_index=True)
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    team = models.CharField("所属团队", max_length=80, blank=True, default="")
    level = models.CharField("服务等级", max_length=4, default="P2",
                             choices=[(v, SERVICE_LEVEL_LABELS[v]) for v in SERVICE_LEVELS])
    status = models.CharField("状态", max_length=20, default="healthy", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    dependency_count = models.IntegerField("依赖数", default=0)
    labels = models.JSONField("标签", default=dict, blank=True)
    repository = models.CharField("代码仓库", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "服务"
        verbose_name_plural = "服务"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "slug"], name="obs_service_owner_slug"),
        ]
        indexes = [
            models.Index(fields=["level", "status"], name="obs_service_level_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.slug})"


class Endpoint(ObservabilityBase):
    """服务暴露的接口/路由，用于按路径维度看可用性。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_endpoints", verbose_name="所有者")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name="endpoints", verbose_name="所属服务")
    path = models.CharField("路径", max_length=300)
    method = models.CharField("方法", max_length=10, default="GET")
    status = models.CharField("状态", max_length=20, default="up", db_index=True)
    description = models.CharField("描述", max_length=300, blank=True, default="")
    timeout_ms = models.IntegerField("超时毫秒", default=3000)
    p95_ms = models.FloatField("P95 延迟毫秒", default=0)

    class Meta:
        verbose_name = "服务端点"
        verbose_name_plural = "服务端点"
        ordering = ["service_id", "path"]
        constraints = [
            models.UniqueConstraint(fields=["service", "method", "path"],
                                    name="obs_endpoint_uniq"),
        ]

    def __str__(self):
        return f"{self.method} {self.path}"


class Dependency(ObservabilityBase):
    """服务间依赖边：upstream 调用 downstream。

    方向刻意从「调用方」指向「被调用方」，因为故障传播方向与之相反：
    downstream 挂了，受影响的是一串 upstream。影响分析在服务层按反向
    边做 BFS，本表只存事实，不做冗余的「受影响服务」列。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_dependencies", verbose_name="所有者")
    upstream = models.ForeignKey(Service, on_delete=models.CASCADE,
                                 related_name="downstream_edges", verbose_name="上游服务")
    downstream = models.ForeignKey(Service, on_delete=models.CASCADE,
                                   related_name="upstream_edges", verbose_name="下游服务")
    dep_type = models.CharField("依赖类型", max_length=20, default="http")
    criticality = models.CharField("关键程度", max_length=20, default="medium")
    timeout_ms = models.IntegerField("超时毫秒", default=1000)
    description = models.CharField("说明", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "服务依赖"
        verbose_name_plural = "服务依赖"
        ordering = ["upstream_id", "downstream_id"]
        constraints = [
            models.UniqueConstraint(fields=["upstream", "downstream"],
                                    name="obs_dependency_uniq"),
        ]

    def __str__(self):
        return f"{self.upstream_id} -> {self.downstream_id}"


# ---------------------------------------------------------------------------
# 2. 指标
# ---------------------------------------------------------------------------


class MetricDef(ObservabilityBase):
    """指标定义：指标名 + 类型 + 单位 + 标签约定。

    (service, name) 唯一：同名指标在不同服务下允许各自定义单位与标签，
    但同一服务内不允许重名，否则告警表达式解析会出现二义性。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_metric_defs", verbose_name="所有者")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name="metrics", verbose_name="所属服务")
    name = models.CharField("指标名", max_length=120, db_index=True)
    metric_type = models.CharField("指标类型", max_length=20, default="gauge")
    unit = models.CharField("单位", max_length=20, blank=True, default="")
    labels = models.JSONField("标签约定", default=dict, blank=True)
    description = models.CharField("描述", max_length=300, blank=True, default="")
    retention_days = models.IntegerField("保留天数", default=30)

    class Meta:
        verbose_name = "指标定义"
        verbose_name_plural = "指标定义"
        ordering = ["service_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["service", "name"], name="obs_metric_uniq"),
        ]
        indexes = [
            models.Index(fields=["name"], name="obs_metric_name_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.service_id})"


class MetricPoint(ObservabilityBase):
    """指标数据点。写入由上报接口完成，读取只走「时间范围 + 聚合」。

    这里不建 (labels->>'key') 的表达式索引：SQLite 不支持，且标签维度的
    过滤量级有限；把标签放 JSON 里换取「任意维度不迁移」的灵活性更划算。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_metric_points", verbose_name="上报人")
    metric = models.ForeignKey(MetricDef, on_delete=models.CASCADE,
                               related_name="points", verbose_name="指标")
    value = models.FloatField("值", default=0)
    timestamp = models.DateTimeField("发生时间", db_index=True)
    labels = models.JSONField("标签", default=dict, blank=True)
    source = models.CharField("上报来源", max_length=80, blank=True, default="agent")

    class Meta:
        verbose_name = "指标点"
        verbose_name_plural = "指标点"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["metric", "timestamp"], name="obs_point_metric_ts_idx"),
            models.Index(fields=["timestamp"], name="obs_point_ts_idx"),
        ]

    def __str__(self):
        return f"{self.metric_id}@{self.timestamp}={self.value}"


# ---------------------------------------------------------------------------
# 3. SLO 与错误预算
# ---------------------------------------------------------------------------


class Slo(ObservabilityBase):
    """服务级目标：可用性 / 延迟 / 错误率。

    ``metrics`` 记录计算口径所用的指标名（total/error/latency），默认值与
    平台约定的标准指标名一致；显式存下来是为了让每个 SLO 能绑定到不同的
    指标口径（例如网关侧 vs 服务侧统计），而不是全局写死一个名字。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_slos", verbose_name="负责人账号")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name="slos", verbose_name="所属服务")
    name = models.CharField("SLO 名称", max_length=120)
    slo_type = models.CharField("目标类型", max_length=20, default="availability")
    target_pct = models.FloatField("目标百分比", default=99.0)
    window_days = models.IntegerField("统计窗口天数", default=30)
    latency_threshold_ms = models.IntegerField("延迟阈值毫秒", default=0)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    metrics = models.JSONField("计算口径", default=dict, blank=True)
    description = models.CharField("描述", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "SLO"
        verbose_name_plural = "SLO"
        ordering = ["service_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["service", "name"], name="obs_slo_uniq"),
        ]

    def __str__(self):
        return f"{self.name} {self.target_pct}%"


class SloWindow(ObservabilityBase):
    """SLO 每次计算的窗口快照（达成率/请求数/燃烧率）。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_slo_windows", verbose_name="计算人")
    slo = models.ForeignKey(Slo, on_delete=models.CASCADE,
                            related_name="windows", verbose_name="SLO")
    start_at = models.DateTimeField("窗口开始")
    end_at = models.DateTimeField("窗口结束")
    attainment_pct = models.FloatField("达成率百分比", default=0)
    total_requests = models.IntegerField("总请求", default=0)
    good_requests = models.IntegerField("好请求", default=0)
    bad_requests = models.IntegerField("坏请求", default=0)
    burn_rate = models.FloatField("燃烧率", default=0)
    met = models.BooleanField("是否达标", default=False)

    class Meta:
        verbose_name = "SLO 窗口"
        verbose_name_plural = "SLO 窗口"
        ordering = ["-start_at"]
        constraints = [
            models.UniqueConstraint(fields=["slo", "start_at", "end_at"],
                                    name="obs_slo_window_uniq"),
        ]

    def __str__(self):
        return f"{self.slo_id} {self.attainment_pct:.2f}%"


class ErrorBudget(ObservabilityBase):
    """错误预算：周期内允许的坏请求总量与消耗情况。

    ``projected_exhaustion`` 允许为空：当消耗速率为 0 时「永远不会耗尽」，
    用 None 表达，而不是写入一个虚假的远期日期。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_error_budgets", verbose_name="所有者")
    slo = models.ForeignKey(Slo, on_delete=models.CASCADE,
                            related_name="budgets", verbose_name="SLO")
    period = models.CharField("预算周期", max_length=20, default="")
    total_allowed = models.FloatField("总额度", default=0)
    consumed = models.FloatField("已消耗", default=0)
    remaining = models.FloatField("剩余", default=0)
    consumed_rate_per_day = models.FloatField("消耗速率(每天)", default=0)
    projected_exhaustion = models.DateField("预测耗尽日", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="healthy")

    class Meta:
        verbose_name = "错误预算"
        verbose_name_plural = "错误预算"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["slo", "period"], name="obs_budget_uniq"),
        ]

    def __str__(self):
        return f"{self.slo_id} {self.period}"


# ---------------------------------------------------------------------------
# 4. 告警
# ---------------------------------------------------------------------------


class AlertRule(ObservabilityBase):
    """告警规则：表达式 + 持续时间 + 严重度 + 通知渠道。

    表达式只支持「指标名 比较符 数值」，是刻意收敛的：可观测性平台里
    90% 的告警是这个形态，支持任意表达式意味着要引入表达式引擎与沙箱，
    收益远低于维护成本。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_alert_rules", verbose_name="所有者")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name="alert_rules", verbose_name="所属服务")
    name = models.CharField("规则名称", max_length=120)
    expression = models.CharField("表达式", max_length=300, default="")
    duration_seconds = models.IntegerField("持续时间秒", default=300)
    severity = models.CharField("严重度", max_length=20, default="warning")
    channels = models.JSONField("通知渠道", default=list, blank=True)
    enabled = models.BooleanField("是否启用", default=True)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    cooldown_seconds = models.IntegerField("抑制间隔秒", default=600)
    last_fired_at = models.DateTimeField("上次触发", null=True, blank=True)
    description = models.CharField("描述", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "告警规则"
        verbose_name_plural = "告警规则"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["service", "enabled"], name="obs_rule_service_idx"),
        ]

    def __str__(self):
        return f"{self.name}[{self.severity}]"


class AlertEvent(ObservabilityBase):
    """告警事件：一次触发到恢复的完整生命周期。

    firing 未恢复时同一规则只允许一条（服务层保证），这样「当前活跃
    告警数」可以直接 count(status="firing")，不需要去重逻辑。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_alert_events", verbose_name="负责人账号")
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE,
                             related_name="events", verbose_name="告警规则")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name="alert_events", verbose_name="所属服务")
    status = models.CharField("状态", max_length=20, default="firing", db_index=True)
    started_at = models.DateTimeField("开始时间")
    ended_at = models.DateTimeField("结束时间", null=True, blank=True)
    value = models.FloatField("触发值", default=0)
    summary = models.CharField("摘要", max_length=300, blank=True, default="")
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    silenced_until = models.DateTimeField("静默到", null=True, blank=True)
    acknowledged_at = models.DateTimeField("确认时间", null=True, blank=True)
    acknowledged_by = models.CharField("确认人", max_length=80, blank=True, default="")

    class Meta:
        verbose_name = "告警事件"
        verbose_name_plural = "告警事件"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "started_at"], name="obs_event_status_idx"),
            models.Index(fields=["rule", "status"], name="obs_event_rule_idx"),
        ]

    def __str__(self):
        return f"{self.rule_id} {self.status}@{self.started_at}"


class Silence(ObservabilityBase):
    """静默窗口：在 [start_at, end_at] 内抑制某条规则的告警。

    静默挂在规则而不是事件上：值班同学的实际诉求是「这条规则接下来两
    小时别叫我」，而不是「这条已经触发的事件别叫我」。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_silences", verbose_name="所有者")
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE,
                             related_name="silences", verbose_name="告警规则")
    start_at = models.DateTimeField("开始时间")
    end_at = models.DateTimeField("结束时间")
    reason = models.CharField("原因", max_length=300, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="obs_silence_creators",
                                   verbose_name="创建人")
    status = models.CharField("状态", max_length=20, default="active", db_index=True)

    class Meta:
        verbose_name = "告警静默"
        verbose_name_plural = "告警静默"
        ordering = ["-start_at"]
        indexes = [
            models.Index(fields=["rule", "start_at", "end_at"],
                         name="obs_silence_window_idx"),
        ]

    def __str__(self):
        return f"silence#{self.pk} rule={self.rule_id}"


# ---------------------------------------------------------------------------
# 5. 事故
# ---------------------------------------------------------------------------


class Incident(ObservabilityBase):
    """事故：从发现到复盘的完整记录。

    ``services`` 存服务 id 列表而不是 M2M：事故涉及的服务在复盘时可能已
    下线（被删除），M2M 会级联丢历史；JSON 列表能保留当时的现场。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_incidents", verbose_name="负责人账号")
    title = models.CharField("标题", max_length=200)
    severity = models.CharField("严重度", max_length=20, default="sev3")
    status = models.CharField("状态", max_length=20, default="open", db_index=True)
    services = models.JSONField("涉及服务", default=list, blank=True)
    started_at = models.DateTimeField("开始时间")
    ended_at = models.DateTimeField("结束时间", null=True, blank=True)
    impact = models.TextField("影响描述", blank=True, default="")
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    commander = models.CharField("事故指挥", max_length=80, blank=True, default="")
    root_cause = models.TextField("根因", blank=True, default="")
    action_items = models.JSONField("行动项", default=list, blank=True)
    acknowledged_at = models.DateTimeField("确认时间", null=True, blank=True)
    mitigated_at = models.DateTimeField("缓解时间", null=True, blank=True)
    resolved_at = models.DateTimeField("解决时间", null=True, blank=True)

    class Meta:
        verbose_name = "事故"
        verbose_name_plural = "事故"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "severity"], name="obs_incident_status_idx"),
            models.Index(fields=["started_at"], name="obs_incident_started_idx"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.title}"


class IncidentUpdate(ObservabilityBase):
    """事故更新记录：谁在什么时候写了什么、顺带做了什么状态变更。

    ``status_change`` 存「from->to」字符串，时间线接口直接按 created_at
    排序输出，不需要再去解析事故当前状态反推历史。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_incident_updates", verbose_name="记录人账号")
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE,
                                 related_name="updates", verbose_name="事故")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="obs_incident_authors", verbose_name="更新人")
    content = models.TextField("内容", blank=True, default="")
    status_change = models.CharField("状态变更", max_length=40, blank=True, default="")
    at = models.DateTimeField("记录时间", db_index=True)

    class Meta:
        verbose_name = "事故更新"
        verbose_name_plural = "事故更新"
        ordering = ["at", "id"]
        indexes = [
            models.Index(fields=["incident", "at"], name="obs_update_incident_idx"),
        ]

    def __str__(self):
        return f"incident#{self.incident_id}@{self.at}"


# ---------------------------------------------------------------------------
# 6. 值班与升级
# ---------------------------------------------------------------------------


class OnCallSchedule(ObservabilityBase):
    """值班表：团队 + 轮换周期 + 成员顺序 + 生效区间。

    成员按顺序轮换（members[0] 从 start_at 开始值第一班），换班只在
    服务层调整 members 或 start_at，不额外建「班次」表 —— 班次可由
    「起始时间 + 周期 + 成员顺序」确定性地算出来，落库反而会漂移。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_oncall_schedules", verbose_name="创建人")
    team = models.CharField("团队", max_length=80, db_index=True)
    name = models.CharField("轮值名称", max_length=120)
    timezone_name = models.CharField("时区", max_length=40, default="Asia/Shanghai")
    rotation = models.CharField("轮换周期", max_length=20, default="weekly")
    start_at = models.DateTimeField("开始时间")
    members = models.JSONField("成员", default=list, blank=True)
    active_from = models.DateTimeField("生效开始", null=True, blank=True)
    active_until = models.DateTimeField("生效结束", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="active")

    class Meta:
        verbose_name = "值班表"
        verbose_name_plural = "值班表"
        ordering = ["team", "name"]
        indexes = [
            models.Index(fields=["team", "start_at"], name="obs_oncall_team_idx"),
        ]

    def __str__(self):
        return f"{self.team}/{self.name}"


class EscalationPolicy(ObservabilityBase):
    """升级策略：按 level 从小到大逐级延迟通知。

    ``delay_minutes`` 是「相对上一级的等待时间」而非绝对时间：这样插入
    一级不需要改其它级的配置，也符合值班同学的心智模型。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_escalation_policies", verbose_name="所有者")
    team = models.CharField("团队", max_length=80, db_index=True)
    level = models.IntegerField("层级", default=1)
    delay_minutes = models.IntegerField("延迟分钟", default=5)
    target_name = models.CharField("目标人", max_length=80, blank=True, default="")
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name="obs_escalation_targets",
                                    verbose_name="目标账号")
    channels = models.JSONField("通知渠道", default=list, blank=True)
    order = models.IntegerField("排序", default=0)
    status = models.CharField("状态", max_length=20, default="active")

    class Meta:
        verbose_name = "升级策略"
        verbose_name_plural = "升级策略"
        ordering = ["team", "level", "order"]
        constraints = [
            models.UniqueConstraint(fields=["team", "level"], name="obs_escalation_uniq"),
        ]

    def __str__(self):
        return f"{self.team}/L{self.level}"


# ---------------------------------------------------------------------------
# 7. 运行手册与健康检查
# ---------------------------------------------------------------------------


class Runbook(ObservabilityBase):
    """运行手册：一组可顺序执行的处置步骤。

    步骤存在 ``steps`` JSON 里（[{"title","command","expect"}]），因为步骤
    的形态由业务决定，独立建表会让「改一版手册」变成 N 行删除插入，
    也会让版本回滚变得不可控。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_runbooks", verbose_name="负责人账号")
    name = models.CharField("手册名称", max_length=120)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="runbooks", verbose_name="所属服务")
    alert_rule = models.ForeignKey(AlertRule, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="runbooks",
                                   verbose_name="适用告警")
    steps = models.JSONField("步骤", default=list, blank=True)
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    version = models.CharField("版本", max_length=20, default="v1.0")
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    executions_count = models.IntegerField("执行次数", default=0)

    class Meta:
        verbose_name = "运行手册"
        verbose_name_plural = "运行手册"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} {self.version}"


class RunbookExecution(ObservabilityBase):
    """运行手册执行记录：每一步的执行结果在 ``steps`` 里逐项落库。

    记录里冗余 ``status`` 与 ``note``，是为了让「执行历史列表」不必展开
    整个 steps 数组；步骤详情只在执行详情接口里返回。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_runbook_executions", verbose_name="执行人账号")
    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE,
                                related_name="executions", verbose_name="运行手册")
    incident = models.ForeignKey(Incident, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="runbook_executions", verbose_name="关联事故")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_runbook_actors", verbose_name="执行人")
    steps = models.JSONField("步骤执行结果", default=list, blank=True)
    status = models.CharField("执行状态", max_length=20, default="running")
    started_at = models.DateTimeField("开始时间")
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    note = models.CharField("备注", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "手册执行记录"
        verbose_name_plural = "手册执行记录"
        ordering = ["-started_at"]

    def __str__(self):
        return f"exec#{self.pk} {self.status}"


class HealthCheck(ObservabilityBase):
    """健康检查配置：探活方式 + 间隔 + 超时 + 当前结论。

    ``status`` 是最近一次执行的结果缓存，历史在执行记录表里；这样服务
    总览一次查询就能拿到当前健康度，不必对每张检查表做子查询。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_health_checks", verbose_name="所有者")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name="health_checks", verbose_name="所属服务")
    check_type = models.CharField("检查类型", max_length=20, default="http")
    config = models.JSONField("配置", default=dict, blank=True)
    interval_seconds = models.IntegerField("间隔秒", default=60)
    timeout_seconds = models.IntegerField("超时秒", default=5)
    status = models.CharField("状态", max_length=20, default="unknown", db_index=True)
    last_checked_at = models.DateTimeField("最后检查", null=True, blank=True)
    last_error = models.CharField("最后错误", max_length=300, blank=True, default="")
    consecutive_failures = models.IntegerField("连续失败次数", default=0)
    enabled = models.BooleanField("是否启用", default=True)
    weight = models.IntegerField("权重", default=1)

    class Meta:
        verbose_name = "健康检查"
        verbose_name_plural = "健康检查"
        ordering = ["service_id", "id"]
        indexes = [
            models.Index(fields=["service", "status"], name="obs_check_service_idx"),
        ]

    def __str__(self):
        return f"{self.check_type}#{self.pk}({self.status})"


class HealthCheckRun(ObservabilityBase):
    """健康检查执行历史：每次执行一条，用于画可用性趋势与排障。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_health_check_runs", verbose_name="执行人")
    health_check = models.ForeignKey(HealthCheck, on_delete=models.CASCADE,
                                     related_name="runs", verbose_name="健康检查")
    status = models.CharField("结果", max_length=20, default="up", db_index=True)
    latency_ms = models.FloatField("耗时毫秒", default=0)
    error = models.CharField("错误", max_length=300, blank=True, default="")
    detail = models.JSONField("明细", default=dict, blank=True)
    checked_at = models.DateTimeField("检查时间", db_index=True)

    class Meta:
        verbose_name = "健康检查记录"
        verbose_name_plural = "健康检查记录"
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["health_check", "checked_at"], name="obs_checkrun_idx"),
        ]

    def __str__(self):
        return f"check#{self.check_id}@{self.checked_at}"


# ---------------------------------------------------------------------------
# 8. 仪表盘面板
# ---------------------------------------------------------------------------


class DashboardPanel(ObservabilityBase):
    """仪表盘面板：查询配置 + 图表类型 + 排序。

    ``query`` 里存指标名、聚合口径、时间窗口等参数，面板渲染时由数据
    接口按此解析；不在后端固定每种面板一个接口，避免面板数量增长时
    路由爆炸。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="obs_dashboard_panels", verbose_name="所有者")
    name = models.CharField("面板名称", max_length=120)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="panels", verbose_name="所属服务")
    chart_type = models.CharField("图表类型", max_length=20, default="line")
    query = models.JSONField("查询配置", default=dict, blank=True)
    order = models.IntegerField("排序", default=0)
    width = models.IntegerField("宽度", default=6)
    height = models.IntegerField("高度", default=4)
    description = models.CharField("描述", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "仪表盘面板"
        verbose_name_plural = "仪表盘面板"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.order}. {self.name}"
