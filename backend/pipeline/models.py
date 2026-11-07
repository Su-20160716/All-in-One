# -*- coding: utf-8 -*-
"""数据集成管道（ETL）· 数据模型。

设计约定（与平台既有应用保持一致）：
- 每个模型都挂 ``owner`` 外键，行级权限统一由 ``core.scoping`` 收口，
  模型层不再重复造权限字段；
- 每个模型都带 ``created_at`` / ``updated_at``，运行链路可完整回放；
- 结构化配置（连接配置、节点参数、字段映射、运行统计、画像）统一用
  ``JSONField``：ETL 的节点参数形态差异极大，为每种节点建列只会让迁移失控，
  而 JSON 也便于「导出 / 导入 / 版本快照」原样往返；
- ``related_name`` 一律使用 ``pipe_`` 前缀显式命名：一个用户会关联十几种
  管道对象，默认的 ``%(class)s_set`` 在跨应用时既易撞名又难读；
- **任何密钥都不落明文**：``Connection.secret_ref`` 只存 ``CredentialRef`` 的名称，
  ``WebhookTrigger.secret_digest`` 只存 SHA-256 摘要，接口回显一律脱敏。
"""
from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.db import models

# ---------------------------------------------------------------------------
# 枚举常量：模型、服务层、视图目录共用同一份，避免字符串各写各的
# ---------------------------------------------------------------------------

CONNECTOR_KINDS = ("http", "database", "file", "webhook", "generator")
CONNECTOR_KIND_LABELS = {
    "http": "HTTP 接口",
    "database": "关系型数据库",
    "file": "文件 / 对象存储",
    "webhook": "Webhook 回调",
    "generator": "内置数据生成器",
}

CONNECTOR_CAPABILITIES = ("read", "write", "stream", "trigger", "sample")
CONNECTOR_CAPABILITY_LABELS = {
    "read": "读取",
    "write": "写入",
    "stream": "流式",
    "trigger": "触发",
    "sample": "样例",
}

CONNECTION_STATUS = ("active", "disabled", "error")
CONNECTION_STATUS_LABELS = {
    "active": "可用",
    "disabled": "已停用",
    "error": "异常",
}

PIPELINE_STATUS = ("draft", "active", "paused", "archived")
PIPELINE_STATUS_LABELS = {
    "draft": "草稿",
    "active": "运行中",
    "paused": "已暂停",
    "archived": "已归档",
}

CONCURRENCY_POLICIES = ("skip", "serial", "allow")
CONCURRENCY_POLICY_LABELS = {
    "skip": "跳过新运行",
    "serial": "串行排队",
    "allow": "允许并发",
}

NODE_TYPES = (
    "source",
    "transform",
    "filter",
    "aggregate",
    "join",
    "sort",
    "dedupe",
    "map",
    "sink",
    "webhook",
)
NODE_TYPE_LABELS = {
    "source": "数据源",
    "transform": "结构转换",
    "filter": "行过滤",
    "aggregate": "聚合",
    "join": "关联",
    "sort": "排序",
    "dedupe": "去重",
    "map": "字段映射",
    "sink": "数据落地",
    "webhook": "回调通知",
}

# 每种节点的可用端口：执行器按端口输出多路行集（如 filter 的 pass / fail）
NODE_PORTS = {
    "source": {"in": [], "out": ["out"]},
    "transform": {"in": ["in"], "out": ["out"]},
    "filter": {"in": ["in"], "out": ["pass", "fail"]},
    "aggregate": {"in": ["in"], "out": ["out"]},
    "join": {"in": ["left", "right"], "out": ["out"]},
    "sort": {"in": ["in"], "out": ["out"]},
    "dedupe": {"in": ["in"], "out": ["out"]},
    "map": {"in": ["in"], "out": ["out"]},
    "sink": {"in": ["in"], "out": []},
    "webhook": {"in": ["in"], "out": []},
}

TRIGGER_TYPES = ("manual", "schedule", "api", "webhook", "retry")
TRIGGER_TYPE_LABELS = {
    "manual": "手动触发",
    "schedule": "定时调度",
    "api": "接口调用",
    "webhook": "Webhook 触发",
    "retry": "失败重跑",
}

RUN_STATUS = ("queued", "running", "success", "failed", "cancelled")
RUN_STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "success": "成功",
    "failed": "失败",
    "cancelled": "已取消",
}

STEP_STATUS = ("pending", "running", "success", "failed", "skipped", "cancelled")
STEP_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "success": "成功",
    "failed": "失败",
    "skipped": "已跳过",
    "cancelled": "已取消",
}

LOG_LEVELS = ("debug", "info", "warning", "error")
LOG_LEVEL_LABELS = {
    "debug": "调试",
    "info": "信息",
    "warning": "警告",
    "error": "错误",
}

QUALITY_RULE_TYPES = (
    "not_null",
    "unique",
    "range",
    "regex",
    "enum",
    "freshness",
    "row_count",
)
QUALITY_RULE_TYPE_LABELS = {
    "not_null": "非空",
    "unique": "唯一",
    "range": "数值区间",
    "regex": "正则匹配",
    "enum": "枚举值",
    "freshness": "时效性",
    "row_count": "行数区间",
}
QUALITY_SEVERITY = ("info", "warning", "error")
QUALITY_SEVERITY_LABELS = {
    "info": "提示",
    "warning": "警告",
    "error": "严重",
}

CREDENTIAL_KINDS = ("token", "password", "api_key", "oauth", "ssh", "certificate")
CREDENTIAL_KIND_LABELS = {
    "token": "访问令牌",
    "password": "账号密码",
    "api_key": "API Key",
    "oauth": "OAuth 凭据",
    "ssh": "SSH 密钥",
    "certificate": "证书",
}

LINEAGE_ENTITY_TYPES = ("connection", "pipeline", "dataset", "table", "webhook", "file")
LINEAGE_ENTITY_TYPE_LABELS = {
    "connection": "连接",
    "pipeline": "管道",
    "dataset": "数据集",
    "table": "数据表",
    "webhook": "Webhook",
    "file": "文件",
}


class PipeStamp(models.Model):
    """所有管道对象的公共字段：owner + 双时间戳。

    ``updated_at`` 用 auto_now 而非触发器：ETL 对象的修改大多来自
    保存节点 / 批量连线这类多行写入，auto_now 能在 save() 层兜住。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_owned",
        verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 连接器 / 连接 / 凭据
# ---------------------------------------------------------------------------


class Connector(PipeStamp):
    """连接器：某一类数据源的类型定义，内置模板与用户自定义共用一张表。

    ``config_template`` 是前端表单的渲染依据（字段名、类型、是否必填、
    默认值），``capabilities`` 声明这一类型能做哪些操作，避免前端出现
    「文件连接器点测试写入」这种不可能成功的按钮。
    """

    name = models.CharField("连接器名称", max_length=120)
    kind = models.CharField("类型", max_length=20, choices=[(k, CONNECTOR_KIND_LABELS[k])
                                                            for k in CONNECTOR_KINDS],
                            default="http", db_index=True)
    config_template = models.JSONField("配置模板", default=dict, blank=True)
    capabilities = models.JSONField("能力标记", default=list, blank=True)
    builtin = models.BooleanField("内置", default=False, db_index=True)
    description = models.TextField("说明", blank=True, default="")
    docs_url = models.CharField("文档地址", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "连接器"
        verbose_name_plural = "连接器"
        ordering = ["-builtin", "kind", "name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="pipe_connector_owner_name_uniq"),
        ]
        indexes = [models.Index(fields=["kind", "builtin"], name="pipe_conn_kind_builtin_idx")]

    def __str__(self) -> str:
        return f"{self.name}[{self.kind}]"


class CredentialRef(PipeStamp):
    """凭据引用：只记录「有一份叫这个名字的密钥」，**绝不存明文**。

    真实部署里明文应由 KMS / 环境变量托管，平台只保留名称与轮换时间。
    因此本表没有任何 value 字段——即便数据库泄露也拿不到密钥本体。
    """

    name = models.CharField("凭据名称", max_length=120)
    kind = models.CharField("凭据类型", max_length=20,
                            choices=[(k, CREDENTIAL_KIND_LABELS[k]) for k in CREDENTIAL_KINDS],
                            default="token")
    description = models.TextField("说明", blank=True, default="")
    provider = models.CharField("托管方", max_length=80, blank=True, default="",
                                help_text="如 env / vault / kms，仅作说明")
    last_rotated_at = models.DateTimeField("最后轮换时间", null=True, blank=True)

    class Meta:
        verbose_name = "凭据引用"
        verbose_name_plural = "凭据引用"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="pipe_credential_owner_name_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.name}({self.kind})"


class Connection(PipeStamp):
    """连接：连接器 + 具体配置。``secret_ref`` 只存 CredentialRef 的名称。

    读写策略：读操作按数据范围（core.scoping.scope_queryset）放开，
    写操作严格 owner；回显配置时服务层会把疑似密钥的键脱敏成 ``****``。
    """

    name = models.CharField("连接名称", max_length=120)
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT,
                                  related_name="connections", verbose_name="连接器")
    config = models.JSONField("连接配置", default=dict, blank=True)
    secret_ref = models.CharField("密钥引用名", max_length=120, blank=True, default="")
    status = models.CharField("状态", max_length=20,
                              choices=[(s, CONNECTION_STATUS_LABELS[s]) for s in CONNECTION_STATUS],
                              default="active", db_index=True)
    last_tested_at = models.DateTimeField("最近测试时间", null=True, blank=True)
    last_error = models.CharField("最近错误", max_length=500, blank=True, default="")
    description = models.TextField("说明", blank=True, default="")

    class Meta:
        verbose_name = "连接"
        verbose_name_plural = "连接"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="pipe_connection_owner_name_uniq"),
        ]
        indexes = [models.Index(fields=["connector", "status"], name="pipe_conn_status_idx")]

    def __str__(self) -> str:
        return f"{self.name}->{self.connector_id}"


# ---------------------------------------------------------------------------
# 管道 / 节点 / 连线 / 映射 / 变量 / 版本
# ---------------------------------------------------------------------------


class Pipeline(PipeStamp):
    """管道：一张 DAG 的元信息与运行护栏。

    ``watermark_field`` / ``watermark_value`` 支撑增量抽取：每次成功运行后
    把该字段的最大值写回，下一次 source 节点只取大于水位的数据。
    ``concurrency`` 决定同管道并发触发时的行为（跳过 / 串行 / 允许）。
    """

    code = models.CharField("编码", max_length=80, db_index=True)
    name = models.CharField("名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField("状态", max_length=20,
                              choices=[(s, PIPELINE_STATUS_LABELS[s]) for s in PIPELINE_STATUS],
                              default="draft", db_index=True)
    concurrency = models.CharField("并发策略", max_length=20,
                                   choices=[(c, CONCURRENCY_POLICY_LABELS[c])
                                            for c in CONCURRENCY_POLICIES],
                                   default="skip")
    max_retries = models.IntegerField("单节点重试上限", default=1)
    timeout_seconds = models.IntegerField("运行超时秒数", default=120)
    assignee = models.CharField("负责人", max_length=80, blank=True, default="")
    tags = models.JSONField("标签", default=list, blank=True)
    watermark_field = models.CharField("增量水位字段", max_length=80, blank=True, default="")
    watermark_value = models.CharField("上次水位值", max_length=200, blank=True, default="")
    row_limit = models.IntegerField("单次行数上限", default=5000)
    version = models.IntegerField("当前版本号", default=0)
    last_run_at = models.DateTimeField("最近运行时间", null=True, blank=True)
    last_run_status = models.CharField("最近运行状态", max_length=20, blank=True, default="")

    class Meta:
        verbose_name = "数据管道"
        verbose_name_plural = "数据管道"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="pipe_pipeline_owner_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["status", "updated_at"], name="pipe_pipeline_status_idx"),
            models.Index(fields=["code"], name="pipe_pipeline_code_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code}:{self.name}"


class PipelineVersion(PipeStamp):
    """管道版本快照：发布 / 手动保存时留档，支持回滚到历史 DAG。"""

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="versions", verbose_name="管道")
    version = models.IntegerField("版本号", default=1)
    snapshot = models.JSONField("DAG 快照", default=dict, blank=True)
    note = models.CharField("版本说明", max_length=300, blank=True, default="")
    published = models.BooleanField("是否发布版本", default=False)

    class Meta:
        verbose_name = "管道版本"
        verbose_name_plural = "管道版本"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "version"], name="pipe_version_pipeline_no_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline_id}#v{self.version}"


class PipeNode(PipeStamp):
    """管道节点：``node_key`` 在管道内唯一，是连线与日志的稳定引用。

    坐标（x/y）只服务前端画布，不参与执行；执行顺序由拓扑排序决定，
    ``order`` 仅用于拓扑同层的稳定排序，保证同构图每次运行结果一致。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="nodes", verbose_name="管道")
    node_key = models.CharField("节点标识", max_length=80)
    name = models.CharField("节点名称", max_length=120)
    node_type = models.CharField("节点类型", max_length=20,
                                 choices=[(t, NODE_TYPE_LABELS[t]) for t in NODE_TYPES],
                                 default="transform", db_index=True)
    config = models.JSONField("节点配置", default=dict, blank=True)
    order = models.IntegerField("排序", default=0)
    position_x = models.FloatField("画布 X", default=0)
    position_y = models.FloatField("画布 Y", default=0)
    enabled = models.BooleanField("启用", default=True)
    description = models.TextField("说明", blank=True, default="")

    class Meta:
        verbose_name = "管道节点"
        verbose_name_plural = "管道节点"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "node_key"], name="pipe_node_key_uniq"),
        ]
        indexes = [models.Index(fields=["pipeline", "node_type"], name="pipe_node_type_idx")]

    def __str__(self) -> str:
        return f"{self.node_key}[{self.node_type}]"


class PipeEdge(PipeStamp):
    """连线：端口决定数据走哪条路（如 filter.fail 接到告警 sink）。"""

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="edges", verbose_name="管道")
    source = models.ForeignKey(PipeNode, on_delete=models.CASCADE,
                               related_name="out_edges", verbose_name="上游节点")
    target = models.ForeignKey(PipeNode, on_delete=models.CASCADE,
                               related_name="in_edges", verbose_name="下游节点")
    source_port = models.CharField("上游端口", max_length=30, default="out")
    target_port = models.CharField("下游端口", max_length=30, default="in")
    order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = "管道连线"
        verbose_name_plural = "管道连线"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "source", "target", "source_port", "target_port"],
                name="pipe_edge_uniq"),
        ]
        indexes = [models.Index(fields=["pipeline"], name="pipe_edge_pipeline_idx")]

    def __str__(self) -> str:
        return f"{self.source_id}:{self.source_port}->{self.target_id}:{self.target_port}"


class Mapping(PipeStamp):
    """字段映射：节点级的源字段 → 目标字段规则。

    与节点 config 内的映射二选一：复杂管道把映射拆表便于逐个开关 /
    单独审计；``expression`` 非空时以表达式结果为准，``cast`` 再兜底转型。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="mappings", verbose_name="管道")
    node = models.ForeignKey(PipeNode, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="mappings", verbose_name="节点")
    source_field = models.CharField("源字段", max_length=120, blank=True, default="")
    target_field = models.CharField("目标字段", max_length=120)
    cast = models.CharField("类型转换", max_length=20, blank=True, default="")
    default_value = models.JSONField("默认值", null=True, blank=True)
    expression = models.TextField("取值表达式", blank=True, default="")
    required = models.BooleanField("必填", default=False)
    order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = "字段映射"
        verbose_name_plural = "字段映射"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["pipeline", "node"], name="pipe_mapping_node_idx")]

    def __str__(self) -> str:
        return f"{self.source_field}->{self.target_field}"


class PipelineVariable(PipeStamp):
    """管道变量：运行期常量（如 API 基址、批次大小），避免硬编码进节点配置。"""

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="variables", verbose_name="管道")
    name = models.CharField("变量名", max_length=80)
    value = models.JSONField("变量值", default=None, null=True, blank=True)
    kind = models.CharField("类型", max_length=20, default="string")
    description = models.CharField("说明", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "管道变量"
        verbose_name_plural = "管道变量"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "name"], name="pipe_variable_name_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.name}={self.value!r}"


# ---------------------------------------------------------------------------
# 调度 / 运行 / 步骤 / 日志 / 输出
# ---------------------------------------------------------------------------


class Schedule(PipeStamp):
    """调度：5 段 cron + 时区，``next_run_at`` 在保存与执行后都会重算。

    不引入 Celery：调度只负责「把到期的管道同步跑起来」，
    扫描接口由前端定时或外部 cron 调用。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="schedules", verbose_name="管道")
    name = models.CharField("调度名称", max_length=120)
    cron = models.CharField("cron 表达式", max_length=120, default="0 * * * *")
    timezone = models.CharField("时区", max_length=64, default="Asia/Shanghai")
    enabled = models.BooleanField("启用", default=True, db_index=True)
    next_run_at = models.DateTimeField("下次运行", null=True, blank=True)
    last_run_at = models.DateTimeField("上次运行", null=True, blank=True)
    last_status = models.CharField("上次状态", max_length=20, blank=True, default="")
    catchup = models.BooleanField("补偿执行", default=False)

    class Meta:
        verbose_name = "调度"
        verbose_name_plural = "调度"
        ordering = ["next_run_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "name"], name="pipe_schedule_name_uniq"),
        ]
        indexes = [models.Index(fields=["enabled", "next_run_at"], name="pipe_schedule_due_idx")]

    def __str__(self) -> str:
        return f"{self.name}({self.cron})"


class PipelineRun(PipeStamp):
    """一次运行：状态机 queued → running → success / failed / cancelled。

    同步执行也不省略 queued：触发器先落库再执行，异常进程被杀时
    至少留下「有这次运行」的证据，而不是彻底静默。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="runs", verbose_name="管道")
    trigger = models.CharField("触发方式", max_length=20,
                               choices=[(t, TRIGGER_TYPE_LABELS[t]) for t in TRIGGER_TYPES],
                               default="manual", db_index=True)
    status = models.CharField("状态", max_length=20,
                              choices=[(s, RUN_STATUS_LABELS[s]) for s in RUN_STATUS],
                              default="queued", db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="pipe_runs_triggered",
                              verbose_name="触发人")
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    duration_ms = models.IntegerField("耗时毫秒", default=0)
    input_rows = models.IntegerField("输入行数", default=0)
    output_rows = models.IntegerField("输出行数", default=0)
    error = models.TextField("错误信息", blank=True, default="")
    watermark_before = models.CharField("运行前水位", max_length=200, blank=True, default="")
    watermark_after = models.CharField("运行后水位", max_length=200, blank=True, default="")
    resumed_from = models.CharField("重跑起点节点", max_length=80, blank=True, default="")
    stats = models.JSONField("运行统计", default=dict, blank=True)

    class Meta:
        verbose_name = "管道运行"
        verbose_name_plural = "管道运行"
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["pipeline", "status"], name="pipe_run_pipe_status_idx"),
            models.Index(fields=["status", "started_at"], name="pipe_run_status_time_idx"),
            models.Index(fields=["trigger"], name="pipe_run_trigger_idx"),
        ]

    def __str__(self) -> str:
        return f"run#{self.pk}[{self.status}]"


class RunStep(PipeStamp):
    """单节点单次尝试的执行记录。

    失败重试会产生多条同 ``node_key`` 不同 ``attempt`` 的记录，
    「失败节点 TOP」统计正需要这份粒度，不能把重试折叠成一行。
    """

    run = models.ForeignKey(PipelineRun, on_delete=models.CASCADE,
                            related_name="steps", verbose_name="运行")
    node = models.ForeignKey(PipeNode, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="steps", verbose_name="节点")
    node_key = models.CharField("节点标识", max_length=80)
    node_type = models.CharField("节点类型", max_length=20, default="transform")
    seq = models.IntegerField("执行序号", default=0)
    attempt = models.IntegerField("尝试次数", default=1)
    status = models.CharField("状态", max_length=20,
                              choices=[(s, STEP_STATUS_LABELS[s]) for s in STEP_STATUS],
                              default="pending", db_index=True)
    duration_ms = models.IntegerField("耗时毫秒", default=0)
    input_rows = models.IntegerField("输入行数", default=0)
    output_rows = models.IntegerField("输出行数", default=0)
    error = models.TextField("错误信息", blank=True, default="")
    summary = models.CharField("日志摘要", max_length=500, blank=True, default="")

    class Meta:
        verbose_name = "运行步骤"
        verbose_name_plural = "运行步骤"
        ordering = ["seq", "id"]
        indexes = [
            models.Index(fields=["run", "seq"], name="pipe_step_run_seq_idx"),
            models.Index(fields=["node_type", "status"], name="pipe_step_type_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.node_key}#{self.attempt}[{self.status}]"


class RunLog(PipeStamp):
    """运行日志：级别 + 消息 + 上下文快照，定位失败时不必再翻步骤表。"""

    run = models.ForeignKey(PipelineRun, on_delete=models.CASCADE,
                            related_name="logs", verbose_name="运行")
    level = models.CharField("级别", max_length=10,
                             choices=[(lv, LOG_LEVEL_LABELS[lv]) for lv in LOG_LEVELS],
                             default="info", db_index=True)
    message = models.CharField("消息", max_length=500)
    node_key = models.CharField("节点标识", max_length=80, blank=True, default="")
    context = models.JSONField("上下文", default=dict, blank=True)
    logged_at = models.DateTimeField("日志时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "运行日志"
        verbose_name_plural = "运行日志"
        ordering = ["logged_at", "id"]
        indexes = [models.Index(fields=["run", "level"], name="pipe_log_run_level_idx")]

    def __str__(self) -> str:
        return f"[{self.level}] {self.message[:40]}"


class PipelineOutput(PipeStamp):
    """落地数据：sink 节点的真实写库结果，也是「输出预览」的数据源。

    一行一条记录（而非把整批塞进一个 JSON）才能做分页、按运行过滤和
    行数统计；单次上限 5000 行，配合 run 索引可安全清理。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="outputs", verbose_name="管道")
    run = models.ForeignKey(PipelineRun, on_delete=models.CASCADE,
                            related_name="outputs", verbose_name="运行")
    node = models.ForeignKey(PipeNode, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="outputs", verbose_name="落地节点")
    dataset = models.CharField("数据集", max_length=120, default="default", db_index=True)
    seq = models.IntegerField("行序号", default=0)
    data = models.JSONField("行数据", default=dict)

    class Meta:
        verbose_name = "管道输出"
        verbose_name_plural = "管道输出"
        ordering = ["seq", "id"]
        indexes = [
            models.Index(fields=["pipeline", "dataset"], name="pipe_output_pipe_ds_idx"),
            models.Index(fields=["run", "seq"], name="pipe_output_run_seq_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.dataset}#{self.seq}"


# ---------------------------------------------------------------------------
# 数据质量
# ---------------------------------------------------------------------------


class DataQualityRule(PipeStamp):
    """质量规则：对运行输出逐条校验，失败样例回写到 QualityResult。

    规则参数全部放 ``params``：不同规则类型需要的键差异很大
    （range 要 min/max、regex 要 pattern、freshness 要 max_age_seconds），
    单表多列会让一半列长期为空。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="quality_rules", verbose_name="管道")
    name = models.CharField("规则名称", max_length=120)
    rule_type = models.CharField("规则类型", max_length=20,
                                 choices=[(t, QUALITY_RULE_TYPE_LABELS[t])
                                          for t in QUALITY_RULE_TYPES],
                                 default="not_null")
    field = models.CharField("校验字段", max_length=120, blank=True, default="")
    params = models.JSONField("规则参数", default=dict, blank=True)
    severity = models.CharField("严重度", max_length=10,
                                choices=[(s, QUALITY_SEVERITY_LABELS[s]) for s in QUALITY_SEVERITY],
                                default="warning")
    enabled = models.BooleanField("启用", default=True, db_index=True)
    description = models.CharField("说明", max_length=300, blank=True, default="")
    last_checked_at = models.DateTimeField("最近检查时间", null=True, blank=True)
    last_passed = models.BooleanField("最近是否通过", null=True, blank=True)

    class Meta:
        verbose_name = "质量规则"
        verbose_name_plural = "质量规则"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "name"], name="pipe_quality_name_uniq"),
        ]
        indexes = [models.Index(fields=["pipeline", "enabled"], name="pipe_quality_enabled_idx")]

    def __str__(self) -> str:
        return f"{self.name}[{self.rule_type}]"


class QualityResult(PipeStamp):
    """规则执行结果：通过与否、失败行数、最多 5 条失败样例。"""

    rule = models.ForeignKey(DataQualityRule, on_delete=models.CASCADE,
                             related_name="results", verbose_name="规则")
    run = models.ForeignKey(PipelineRun, on_delete=models.CASCADE,
                            related_name="quality_results", verbose_name="运行")
    passed = models.BooleanField("是否通过", default=True, db_index=True)
    checked_rows = models.IntegerField("检查行数", default=0)
    failed_rows = models.IntegerField("失败行数", default=0)
    sample = models.JSONField("失败样例", default=list, blank=True)
    message = models.CharField("结果说明", max_length=500, blank=True, default="")
    duration_ms = models.IntegerField("耗时毫秒", default=0)

    class Meta:
        verbose_name = "质量结果"
        verbose_name_plural = "质量结果"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["run", "passed"], name="pipe_qres_run_passed_idx")]

    def __str__(self) -> str:
        return f"{self.rule_id}@{self.run_id}:{'PASS' if self.passed else 'FAIL'}"


# ---------------------------------------------------------------------------
# 血缘 / 画像
# ---------------------------------------------------------------------------


class LineageEdge(PipeStamp):
    """血缘边：上游实体 → 下游实体，附字段级映射。

    实体用 (type, key) 而非外键：血缘会跨到连接、数据集、甚至外部表，
    强行外键会让「没有对应 model 的上游」无处安放。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="lineage_edges", verbose_name="产生血缘的管道")
    run = models.ForeignKey(PipelineRun, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="lineage_edges", verbose_name="来源运行")
    upstream_type = models.CharField("上游类型", max_length=20,
                                     choices=[(t, LINEAGE_ENTITY_TYPE_LABELS[t])
                                              for t in LINEAGE_ENTITY_TYPES],
                                     default="connection")
    upstream_key = models.CharField("上游标识", max_length=200, db_index=True)
    downstream_type = models.CharField("下游类型", max_length=20,
                                       choices=[(t, LINEAGE_ENTITY_TYPE_LABELS[t])
                                                for t in LINEAGE_ENTITY_TYPES],
                                       default="dataset")
    downstream_key = models.CharField("下游标识", max_length=200, db_index=True)
    field_map = models.JSONField("字段映射", default=list, blank=True)

    class Meta:
        verbose_name = "血缘边"
        verbose_name_plural = "血缘边"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "pipeline", "upstream_type", "upstream_key",
                        "downstream_type", "downstream_key"],
                name="pipe_lineage_uniq"),
        ]
        indexes = [
            models.Index(fields=["upstream_key"], name="pipe_lineage_up_idx"),
            models.Index(fields=["downstream_key"], name="pipe_lineage_down_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.upstream_key}->{self.downstream_key}"


class DatasetProfile(PipeStamp):
    """数据画像：行数 + 每字段的空值率 / 唯一值 / 最值 / 均值 / 长度分布。"""

    pipeline = models.ForeignKey(Pipeline, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="profiles", verbose_name="管道")
    run = models.ForeignKey(PipelineRun, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="profiles", verbose_name="运行")
    dataset = models.CharField("数据集", max_length=120, default="default")
    row_count = models.IntegerField("行数", default=0)
    sample_size = models.IntegerField("采样行数", default=0)
    columns = models.JSONField("字段画像", default=list, blank=True)
    sampled_at = models.DateTimeField("采样时间", null=True, blank=True)
    notes = models.CharField("备注", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "数据画像"
        verbose_name_plural = "数据画像"
        ordering = ["-sampled_at", "-id"]
        indexes = [models.Index(fields=["pipeline", "dataset"], name="pipe_profile_ds_idx")]

    def __str__(self) -> str:
        return f"{self.dataset}({self.row_count})"


# ---------------------------------------------------------------------------
# Webhook 触发
# ---------------------------------------------------------------------------


class WebhookTrigger(PipeStamp):
    """入站 Webhook：外部系统用 secret 触发管道。

    secret 只存 SHA-256 摘要与末 4 位提示，创建时回显一次明文；
    之后任何接口都拿不到原文，泄露面仅限「创建响应」。
    """

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE,
                                 related_name="webhooks", verbose_name="管道")
    name = models.CharField("触发名称", max_length=120)
    secret_digest = models.CharField("密钥摘要", max_length=64, blank=True, default="")
    secret_hint = models.CharField("密钥提示", max_length=20, blank=True, default="")
    enabled = models.BooleanField("启用", default=True, db_index=True)
    last_triggered_at = models.DateTimeField("最近触发时间", null=True, blank=True)
    trigger_count = models.IntegerField("触发次数", default=0)
    description = models.CharField("说明", max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "Webhook 触发"
        verbose_name_plural = "Webhook 触发"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "name"], name="pipe_webhook_name_uniq"),
        ]
        indexes = [models.Index(fields=["enabled"], name="pipe_webhook_enabled_idx")]

    def __str__(self) -> str:
        return f"{self.name}->{self.pipeline_id}"

    def set_secret(self, secret: str) -> None:
        """写入新密钥：只留摘要与末 4 位，明文立刻丢弃。"""
        secret = (secret or "").strip()
        self.secret_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        self.secret_hint = f"***{secret[-4:]}" if len(secret) >= 4 else "***"

    def matches(self, secret: str) -> bool:
        """常量时间比较，避免按字符耗时侧信道猜密钥。"""
        if not self.secret_digest:
            return False
        digest = hashlib.sha256((secret or "").strip().encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, self.secret_digest)
