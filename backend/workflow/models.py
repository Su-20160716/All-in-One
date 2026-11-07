# -*- coding: utf-8 -*-
"""流程引擎 · 数据模型。

设计约定（与平台其他应用保持一致）：
- 每个业务模型都带 ``owner`` 外键做行级权限收口，写权限统一走 core.scoping；
- 每张表都有 created_at / updated_at，便于审计与增量同步；
- 所有 related_name 显式命名并加 ``wf_`` 前缀，避免与其他应用的默认反向名冲突；
- 高频过滤字段（状态 / 实例 / 节点 / 截止时间）建索引，列表接口不扫全表；
- 模型只承载「数据 + 派生计算」，跨表推进逻辑放在 services.py，视图只做编排。

状态机总览：
- 定义：draft → published → disabled / archived（发布后不可直接改图，只能回滚或克隆）
- 实例：running → completed / rejected / cancelled / terminated
- 任务：pending → claimed → completed / cancelled（退回会新建任务而不是复活旧任务）
- 令牌：active → consumed / cancelled（并行网关用多令牌表达分支）
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# 枚举常量
#
# 用模块级常量而不是只有 choices：服务层与视图层需要做集合判定
# （例如「终态集合」「可编辑状态集合」），集中一处避免拼写漂移。
# ---------------------------------------------------------------------------

NODE_TYPE_CHOICES = [
    ("start", "开始"),
    ("task", "人工任务"),
    ("decision", "条件分支"),
    ("parallel_split", "并行拆分"),
    ("parallel_join", "并行汇聚"),
    ("end", "结束"),
]
NODE_TYPE_VALUES = tuple(item[0] for item in NODE_TYPE_CHOICES)

ASSIGNEE_TYPE_CHOICES = [
    ("none", "无需指派"),
    ("user", "指定用户"),
    ("role", "按角色"),
    ("dept", "按部门"),
    ("manager", "按主管链"),
    ("expression", "表达式"),
]
ASSIGNEE_TYPE_VALUES = tuple(item[0] for item in ASSIGNEE_TYPE_CHOICES)

DEFINITION_STATUS_CHOICES = [
    ("draft", "草稿"),
    ("published", "已发布"),
    ("disabled", "已停用"),
    ("archived", "已归档"),
]
DEFINITION_STATUS_VALUES = tuple(item[0] for item in DEFINITION_STATUS_CHOICES)
# 只有这两个状态允许直接改图：published 的实例正在跑，改图会让在途令牌指向不存在/语义变化的节点
DEFINITION_EDITABLE_STATUS = ("draft", "disabled")

VERSION_STATUS_CHOICES = [
    ("published", "已发布"),
    ("superseded", "已被取代"),
    ("rolled_back", "回滚产生"),
]

INSTANCE_STATUS_CHOICES = [
    ("running", "运行中"),
    ("completed", "已完成"),
    ("rejected", "已拒绝"),
    ("cancelled", "已取消"),
    ("terminated", "已终止"),
]
INSTANCE_STATUS_VALUES = tuple(item[0] for item in INSTANCE_STATUS_CHOICES)
INSTANCE_OPEN_STATUS = ("running",)
INSTANCE_FINAL_STATUS = ("completed", "rejected", "cancelled", "terminated")

TOKEN_STATUS_CHOICES = [
    ("active", "活跃"),
    ("consumed", "已消费"),
    ("cancelled", "已取消"),
]

TASK_STATUS_CHOICES = [
    ("pending", "待认领"),
    ("claimed", "处理中"),
    ("completed", "已完成"),
    ("cancelled", "已取消"),
    ("expired", "已过期"),
]
TASK_STATUS_VALUES = tuple(item[0] for item in TASK_STATUS_CHOICES)
TASK_OPEN_STATUS = ("pending", "claimed")
TASK_ACTION_CHOICES = [
    ("approve", "同意"),
    ("reject", "拒绝"),
    ("return", "退回"),
    ("add_sign", "加签"),
    ("transfer", "转办"),
    ("complete", "完成"),
]

COMMENT_KIND_CHOICES = [
    ("comment", "评论"),
    ("decision", "决策说明"),
    ("system", "系统消息"),
]

VARIABLE_TYPE_CHOICES = [
    ("string", "字符串"),
    ("number", "数字"),
    ("boolean", "布尔"),
    ("json", "JSON"),
    ("date", "日期"),
    ("datetime", "日期时间"),
]

TIMER_TYPE_CHOICES = [
    ("remind", "到期提醒"),
    ("timeout", "超时升级"),
    ("escalate", "逐级上报"),
    ("custom", "自定义"),
]
TIMER_STATUS_CHOICES = [
    ("scheduled", "待触发"),
    ("fired", "已触发"),
    ("cancelled", "已取消"),
]

DELEGATION_STATUS_CHOICES = [
    ("active", "生效中"),
    ("revoked", "已撤销"),
    ("expired", "已过期"),
]
DELEGATION_SCOPE_CHOICES = [
    ("all", "全部任务"),
    ("definition", "指定流程"),
    ("tasks", "指定任务"),
]

NOTIFICATION_CHANNEL_CHOICES = [
    ("inapp", "站内"),
    ("webhook", "Webhook"),
    ("email", "邮件"),
]
NOTIFICATION_STATUS_CHOICES = [
    ("pending", "待发送"),
    ("sent", "已发送"),
    ("failed", "发送失败"),
    ("read", "已读"),
]
NOTIFICATION_LEVEL_CHOICES = [
    ("info", "普通"),
    ("success", "成功"),
    ("warning", "警告"),
    ("danger", "危险"),
]

PRIORITY_CHOICES = [
    ("low", "低"),
    ("normal", "普通"),
    ("high", "高"),
    ("urgent", "紧急"),
]

SNAPSHOT_REASON_CHOICES = [
    ("start", "发起"),
    ("manual", "手动"),
    ("task", "任务流转"),
    ("complete", "完成"),
    ("cancel", "取消"),
    ("terminate", "终止"),
    ("sla", "SLA 扫描"),
    ("rollback", "版本回滚"),
]


def _now():
    """统一取当前时间（便于测试注入 / 未来替换时钟）。"""
    return timezone.now()


def _json_dict():
    """JSONField 默认空对象（返回实例而不是 dict 类型，否则无法序列化）。"""
    return {}


def _json_list():
    """JSONField 默认空数组（返回实例而不是 list 类型）。"""
    return []


# ---------------------------------------------------------------------------
# 1. SLA 策略
# ---------------------------------------------------------------------------


class WorkflowSlaPolicy(models.Model):
    """SLA 策略：按优先级给「响应」「解决」两个时限，可被流程定义引用。

    为什么把时限放在策略而不是节点：同一个审批流在不同优先级下（普通报销 vs
    紧急采购）时限完全不同，策略可以复用，节点只覆盖单节点特例（sla_minutes）。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_sla_policies", verbose_name="所有者",
    )
    code = models.CharField("策略编码", max_length=40)
    name = models.CharField("策略名称", max_length=120)
    priority = models.CharField("适用优先级", max_length=10, choices=PRIORITY_CHOICES,
                                default="normal", db_index=True)
    response_minutes = models.IntegerField("响应时限(分钟)", default=240)
    resolve_minutes = models.IntegerField("解决时限(分钟)", default=1440)
    business_hours = models.BooleanField("仅工作时间计时", default=True)
    escalate_to = models.CharField("升级对象", max_length=20, default="manager")
    active = models.BooleanField("启用", default=True, db_index=True)
    description = models.TextField("说明", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "SLA 策略"
        verbose_name_plural = "SLA 策略"
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="wf_sla_owner_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "active"], name="wf_sla_owner_active_idx"),
        ]

    def __str__(self):
        return f"{self.code}({self.priority})"

    @property
    def response_delta(self):
        """响应时限的 timedelta（负值视为 0，避免 due 时间落到过去）。"""
        from datetime import timedelta

        return timedelta(minutes=max(int(self.response_minutes or 0), 0))

    @property
    def resolve_delta(self):
        """解决时限的 timedelta。"""
        from datetime import timedelta

        return timedelta(minutes=max(int(self.resolve_minutes or 0), 0))

    def response_due(self, start):
        """从 start 起算的响应截止时间。"""
        return (start or _now()) + self.response_delta

    def resolve_due(self, start):
        """从 start 起算的解决截止时间。"""
        return (start or _now()) + self.resolve_delta

    def to_payload(self):
        """轻量字典，供 catalog 与监控接口复用。"""
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "priority": self.priority,
            "response_minutes": self.response_minutes,
            "resolve_minutes": self.resolve_minutes,
            "business_hours": self.business_hours,
            "active": self.active,
        }


# ---------------------------------------------------------------------------
# 2. 流程定义
# ---------------------------------------------------------------------------


class WorkflowDefinition(models.Model):
    """流程定义：一个可发起、可发布版本的流程模板。

    ``code`` 在同一 owner 下唯一，作为外部系统对接的稳定标识（业务单号前缀、
    导入导出时的引用键），不做全局唯一以免多租户/多人各自维护同名流程冲突。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_definitions", verbose_name="所有者",
    )
    code = models.CharField("流程编码", max_length=64, db_index=True)
    name = models.CharField("流程名称", max_length=200, db_index=True)
    category = models.CharField("分类", max_length=40, default="通用", db_index=True)
    description = models.TextField("说明", blank=True, default="")
    version_no = models.IntegerField("当前版本号", default=1)
    status = models.CharField("状态", max_length=20, choices=DEFINITION_STATUS_CHOICES,
                              default="draft", db_index=True)
    # 发起权限：{"allow_all": true} 或 {"roles": [...], "user_ids": [...], "dept_ids": [...]}
    start_permission = models.JSONField("发起权限", default=_json_dict, blank=True)
    form_key = models.CharField("绑定表单", max_length=64, blank=True, default="")
    icon = models.CharField("图标", max_length=40, blank=True, default="")
    tags = models.JSONField("标签", default=_json_list, blank=True)
    settings = models.JSONField("扩展配置", default=_json_dict, blank=True)
    sla_policy = models.ForeignKey(
        WorkflowSlaPolicy, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="definitions", verbose_name="SLA 策略",
    )
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程定义"
        verbose_name_plural = "流程定义"
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="wf_def_owner_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="wf_def_owner_status_idx"),
            models.Index(fields=["category", "status"], name="wf_def_cat_status_idx"),
        ]

    def __str__(self):
        return f"{self.code} v{self.version_no} [{self.status}]"

    # ---- 派生属性（序列化层直接复用，避免每个视图重复 count）----

    @property
    def is_published(self):
        """是否处于已发布状态。"""
        return self.status == "published"

    @property
    def is_editable(self):
        """图结构是否允许直接编辑（发布/归档后必须先回滚或克隆）。"""
        return self.status in DEFINITION_EDITABLE_STATUS

    @property
    def node_count(self):
        """节点数量（调用方应尽量用 annotate 避免 N+1）。"""
        return self.nodes.count()

    @property
    def transition_count(self):
        """连线数量。"""
        return self.transitions.count()

    @property
    def instance_count(self):
        """已发起实例数。"""
        return self.instances.count()

    @property
    def latest_version(self):
        """最近一个版本快照。"""
        return self.versions.order_by("-version_no").first()

    def next_version_no(self):
        """下一个发布版本号：以最大历史版本为准，避免删除版本后号段回退。"""
        last = self.versions.order_by("-version_no").values_list("version_no", flat=True).first()
        if last is None:
            # 从未发布过时 version_no 仍是字段默认占位值，首个正式版本必须是 1，
            # 否则草稿的占位号会被当成历史版本而把首个版本顶到 v2。
            return 1
        return max(int(last), int(self.version_no or 0)) + 1

    def permission_payload(self):
        """规范化发起权限，兼容空值与 allow_all 缺省。"""
        data = self.start_permission if isinstance(self.start_permission, dict) else {}
        return {
            "allow_all": bool(data.get("allow_all", False)),
            "roles": [str(x) for x in (data.get("roles") or [])],
            "user_ids": [int(x) for x in (data.get("user_ids") or []) if str(x).isdigit()],
            "dept_ids": [int(x) for x in (data.get("dept_ids") or []) if str(x).isdigit()],
        }

    def entry_node(self):
        """取开始节点（缓存到实例属性，单次请求内只查一次）。"""
        cached = getattr(self, "_wf_entry_node", None)
        if cached is None:
            cached = self.nodes.filter(node_type="start").order_by("id").first()
            self._wf_entry_node = cached
        return cached

    def end_nodes(self):
        """全部结束节点。"""
        return self.nodes.filter(node_type="end").order_by("id")

    def default_sla_minutes(self):
        """未指定节点 SLA 时的兜底响应分钟数。"""
        policy = self.sla_policy
        if policy is not None and policy.active:
            return max(int(policy.response_minutes or 0), 0)
        return int((self.settings or {}).get("default_sla_minutes", 1440) or 0)

    def setting(self, key, default=None):
        """读取 settings JSON 中的单个键。"""
        data = self.settings if isinstance(self.settings, dict) else {}
        return data.get(key, default)


# ---------------------------------------------------------------------------
# 3. 流程版本
# ---------------------------------------------------------------------------


class WorkflowVersion(models.Model):
    """流程版本：发布时对节点/连线/配置做不可变快照，支持审计、对比与回滚。

    快照存 JSON 而不是复制节点行：版本只读、数量多，行复制会把节点表撑爆，
    且回滚时需要「整图原子替换」，JSON 一次写入更直接。
    """

    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.CASCADE,
        related_name="versions", verbose_name="流程定义",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_versions", verbose_name="所有者",
    )
    version_no = models.IntegerField("版本号")
    snapshot = models.JSONField("图快照", default=_json_dict, blank=True)
    publisher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wf_published_versions", verbose_name="发布人",
    )
    published_at = models.DateTimeField("发布时间", default=_now)
    change_note = models.TextField("变更说明", blank=True, default="")
    status = models.CharField("版本状态", max_length=20, choices=VERSION_STATUS_CHOICES,
                              default="published", db_index=True)
    node_count = models.IntegerField("节点数", default=0)
    transition_count = models.IntegerField("连线数", default=0)
    checksum = models.CharField("快照校验和", max_length=64, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程版本"
        verbose_name_plural = "流程版本"
        ordering = ["-version_no", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["definition", "version_no"], name="wf_version_def_no_uniq"),
        ]
        indexes = [
            models.Index(fields=["definition", "-version_no"], name="wf_version_def_no_idx"),
        ]

    def __str__(self):
        return f"{self.definition.code} v{self.version_no}"

    @property
    def is_current(self):
        """是否为定义当前指向的版本号。"""
        return int(self.definition.version_no or 0) == int(self.version_no or 0)

    @property
    def nodes_payload(self):
        """快照中的节点数组（防御式取默认空列表）。"""
        data = self.snapshot if isinstance(self.snapshot, dict) else {}
        nodes = data.get("nodes")
        return nodes if isinstance(nodes, list) else []

    @property
    def transitions_payload(self):
        """快照中的连线数组。"""
        data = self.snapshot if isinstance(self.snapshot, dict) else {}
        items = data.get("transitions")
        return items if isinstance(items, list) else []

    def node_keys(self):
        """快照里的节点 key 集合，供对比接口使用。"""
        return {str(n.get("key")) for n in self.nodes_payload if n.get("key")}

    def find_node(self, key):
        """按 key 取快照节点。"""
        for node in self.nodes_payload:
            if str(node.get("key")) == str(key):
                return node
        return None


# ---------------------------------------------------------------------------
# 4. 流程节点
# ---------------------------------------------------------------------------


class WorkflowNode(models.Model):
    """流程节点：开始 / 人工任务 / 条件分支 / 并行拆分 / 并行汇聚 / 结束。

    节点 ``key`` 在同一流程内唯一，连线、条件表达式、退回目标都用 key 引用，
    这样导出导入、克隆、版本对比不必依赖自增主键。
    """

    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.CASCADE,
        related_name="nodes", verbose_name="流程定义",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_nodes", verbose_name="所有者",
    )
    key = models.CharField("节点标识", max_length=64)
    name = models.CharField("节点名称", max_length=200)
    node_type = models.CharField("节点类型", max_length=20, choices=NODE_TYPE_CHOICES,
                                 default="task", db_index=True)
    assignee_type = models.CharField("办理人类型", max_length=20, choices=ASSIGNEE_TYPE_CHOICES,
                                     default="user")
    assignee_rule = models.JSONField("指派规则", default=_json_dict, blank=True)
    sla_minutes = models.IntegerField("处理时限(分钟)", default=0)
    form_fields = models.JSONField("表单字段", default=_json_list, blank=True)
    config = models.JSONField("节点配置", default=_json_dict, blank=True)
    position_x = models.IntegerField("画布 X", default=0)
    position_y = models.IntegerField("画布 Y", default=0)
    order = models.IntegerField("排序", default=0)
    allow_reject = models.BooleanField("允许拒绝", default=True)
    allow_return = models.BooleanField("允许退回", default=True)
    allow_add_sign = models.BooleanField("允许加签", default=True)
    allow_transfer = models.BooleanField("允许转办", default=True)
    require_comment = models.BooleanField("必须填写意见", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程节点"
        verbose_name_plural = "流程节点"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["definition", "key"], name="wf_node_def_key_uniq"),
        ]
        indexes = [
            models.Index(fields=["definition", "node_type"], name="wf_node_def_type_idx"),
        ]

    def __str__(self):
        return f"{self.key}({self.node_type})"

    # ---- 类型判定 ----

    @property
    def is_start(self):
        """是否开始节点。"""
        return self.node_type == "start"

    @property
    def is_end(self):
        """是否结束节点。"""
        return self.node_type == "end"

    @property
    def is_task(self):
        """是否人工任务节点。"""
        return self.node_type == "task"

    @property
    def is_gateway(self):
        """是否网关（条件分支或并行网关）。"""
        return self.node_type in ("decision", "parallel_split", "parallel_join")

    @property
    def is_parallel(self):
        """是否并行网关。"""
        return self.node_type in ("parallel_split", "parallel_join")

    @property
    def sla_hours(self):
        """时限的小时表示（前端展示用）。"""
        return round(float(self.sla_minutes or 0) / 60.0, 2)

    @property
    def has_condition(self):
        """是否存在入口跳过条件。"""
        return bool((self.config or {}).get("skip_if"))

    def config_value(self, key, default=None):
        """读取节点配置。"""
        data = self.config if isinstance(self.config, dict) else {}
        return data.get(key, default)

    def outgoing_edges(self):
        """出边（按优先级排序，决定分支求值顺序）。"""
        return self.outgoing.select_related("to_node").order_by("priority", "id")

    def incoming_edges(self):
        """入边。"""
        return self.incoming.select_related("from_node").order_by("priority", "id")

    def outgoing_count(self):
        """出边数量。"""
        return self.outgoing.count()

    def incoming_count(self):
        """入边数量。"""
        return self.incoming.count()

    def assignee_summary(self):
        """指派规则的一行摘要，用于流程图与待办展示。"""
        rule = self.assignee_rule if isinstance(self.assignee_rule, dict) else {}
        if self.assignee_type == "user":
            ids = rule.get("user_ids") or []
            names = rule.get("usernames") or []
            return "、".join([str(x) for x in names] or [str(x) for x in ids]) or "指定用户"
        if self.assignee_type == "role":
            return "角色：" + "、".join([str(x) for x in (rule.get("roles") or [])])
        if self.assignee_type == "dept":
            return "部门：" + "、".join([str(x) for x in (rule.get("dept_ids") or [])])
        if self.assignee_type == "manager":
            return f"主管链第 {int(rule.get('level', 1) or 1)} 级"
        if self.assignee_type == "expression":
            return f"表达式：{rule.get('expression', '')}"
        return "无需指派"


# ---------------------------------------------------------------------------
# 5. 流程连线
# ---------------------------------------------------------------------------


class WorkflowTransition(models.Model):
    """流程连线：from → to，带条件表达式、优先级与默认分支标记。

    优先级越小越先求值；同一节点最多一个默认分支（由服务层校验），
    保证「条件都没命中时」有确定性的兜底路径。
    """

    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.CASCADE,
        related_name="transitions", verbose_name="流程定义",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_transitions", verbose_name="所有者",
    )
    from_node = models.ForeignKey(
        WorkflowNode, on_delete=models.CASCADE,
        related_name="outgoing", verbose_name="源节点",
    )
    to_node = models.ForeignKey(
        WorkflowNode, on_delete=models.CASCADE,
        related_name="incoming", verbose_name="目标节点",
    )
    condition = models.TextField("条件表达式", blank=True, default="")
    priority = models.IntegerField("优先级", default=100)
    is_default = models.BooleanField("默认分支", default=False)
    label = models.CharField("连线标签", max_length=100, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程连线"
        verbose_name_plural = "流程连线"
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_node", "to_node", "priority"], name="wf_trans_from_to_prio_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["definition", "from_node"], name="wf_trans_def_from_idx"),
            models.Index(fields=["definition", "to_node"], name="wf_trans_def_to_idx"),
        ]

    def __str__(self):
        return f"{self.from_node_id}->{self.to_node_id}"

    @property
    def has_condition(self):
        """是否配置了条件。"""
        return bool((self.condition or "").strip())

    def matches(self, context):
        """求值条件：空条件恒为真（普通连线）。"""
        if not self.has_condition:
            return True
        from workflow.services import evaluate_condition

        return bool(evaluate_condition(self.condition, context or {}))

    def edge_key(self):
        """(from_key, to_key) 二元组，供图算法构建邻接表。"""
        return str(self.from_node.key), str(self.to_node.key)


# ---------------------------------------------------------------------------
# 6. 流程实例
# ---------------------------------------------------------------------------


class WorkflowInstance(models.Model):
    """流程实例：一次真实发起，承载业务单号、上下文与当前节点。

    ``business_no`` 全局唯一：它是外部系统（OA/ERP）与流程引擎之间的幂等键，
    重复发起同一业务单会撞唯一约束，从而在服务层返回「业务单号已存在」。
    """

    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.CASCADE,
        related_name="instances", verbose_name="流程定义",
    )
    version = models.ForeignKey(
        WorkflowVersion, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="instances", verbose_name="发起版本",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_instances", verbose_name="所有者",
    )
    starter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_started_instances", verbose_name="发起人",
    )
    business_no = models.CharField("业务单号", max_length=64, unique=True, db_index=True)
    business_key = models.CharField("业务键", max_length=128, blank=True, default="", db_index=True)
    title = models.CharField("标题", max_length=200)
    category = models.CharField("分类", max_length=40, default="通用", db_index=True)
    status = models.CharField("状态", max_length=20, choices=INSTANCE_STATUS_CHOICES,
                              default="running", db_index=True)
    current_node = models.ForeignKey(
        WorkflowNode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="current_instances", verbose_name="当前节点",
    )
    context = models.JSONField("上下文", default=_json_dict, blank=True)
    priority = models.CharField("优先级", max_length=10, choices=PRIORITY_CHOICES,
                                default="normal", db_index=True)
    result = models.CharField("结果", max_length=50, blank=True, default="")
    due_at = models.DateTimeField("截止时间", null=True, blank=True)
    started_at = models.DateTimeField("发起时间", default=_now, db_index=True)
    finished_at = models.DateTimeField("完成时间", null=True, blank=True)
    last_activity_at = models.DateTimeField("最后活动时间", default=_now)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程实例"
        verbose_name_plural = "流程实例"
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-started_at"], name="wf_inst_status_started_idx"),
            models.Index(fields=["definition", "status"], name="wf_inst_def_status_idx"),
            models.Index(fields=["starter", "status"], name="wf_inst_starter_status_idx"),
            models.Index(fields=["due_at"], name="wf_inst_due_idx"),
        ]

    def __str__(self):
        return f"{self.business_no} [{self.status}]"

    # ---- 状态判定 ----

    @property
    def is_running(self):
        """是否运行中。"""
        return self.status == "running"

    @property
    def is_finished(self):
        """是否终态。"""
        return self.status in INSTANCE_FINAL_STATUS

    @property
    def current_node_name(self):
        """当前节点名（列表直接展示，避免前端二次请求）。"""
        return self.current_node.name if self.current_node_id else ""

    @property
    def duration_minutes(self):
        """耗时分钟：未完成为「至今」，已完成为「发起 → 完成」。"""
        end = self.finished_at or _now()
        if not self.started_at:
            return 0
        return max(int((end - self.started_at).total_seconds() // 60), 0)

    @property
    def is_overdue(self):
        """运行中且已过截止时间。"""
        return bool(self.is_running and self.due_at and _now() > self.due_at)

    @property
    def open_task_count(self):
        """未结任务数。"""
        return self.tasks.filter(status__in=TASK_OPEN_STATUS).count()

    @property
    def task_count(self):
        """任务总数。"""
        return self.tasks.count()

    @property
    def progress_pct(self):
        """以任务完成比例近似流程进度，任务为 0 时运行中记 0、终态记 100。"""
        total = self.tasks.count()
        if total == 0:
            return 0 if self.is_running else 100
        done = self.tasks.filter(status="completed").count()
        return int(round(done * 100.0 / total))

    def context_value(self, path, default=None):
        """按 a.b.c 读取上下文，缺失返回默认值（条件表达式用同一套语义）。"""
        cur = self.context if isinstance(self.context, dict) else {}
        for part in str(path).split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def merge_context(self, extra):
        """合并上下文（浅合并；嵌套结构由调用方自行保证）。"""
        base = self.context if isinstance(self.context, dict) else {}
        if isinstance(extra, dict):
            base = {**base, **extra}
        self.context = base
        return base

    def touch(self):
        """刷新最后活动时间（不落库，由调用方统一 save）。"""
        self.last_activity_at = _now()

    def finish(self, status, result="", node=None):
        """写入终态：状态、结果、完成时间、当前节点一次设齐。"""
        if status not in INSTANCE_FINAL_STATUS:
            raise ValueError(f"非法的实例终态: {status}")
        self.status = status
        self.result = (result or "")[:50]
        self.finished_at = _now()
        if node is not None:
            self.current_node = node
        self.touch()

    def can_be_cancelled_by(self, user):
        """只有发起人、所有者或管理员能取消运行中的实例。"""
        if not self.is_running or user is None:
            return False
        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True
        return user.id in (self.owner_id, self.starter_id)

    def active_token_count(self):
        """活跃令牌数（并行分支看板用）。"""
        return self.tokens.filter(status="active").count()


# ---------------------------------------------------------------------------
# 7. 执行令牌
# ---------------------------------------------------------------------------


class WorkflowToken(models.Model):
    """执行令牌：流程引擎的「执行指针」。

    串行流程只有一个令牌；并行网关拆分时一个令牌裂变为多个子令牌，
    汇聚时要求同一汇聚节点的令牌数达到入边数才合并。parent 记录裂变来源，
    便于前端画布高亮当前分支。
    """

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="tokens", verbose_name="流程实例",
    )
    node = models.ForeignKey(
        WorkflowNode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tokens", verbose_name="所在节点",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_tokens", verbose_name="所有者",
    )
    status = models.CharField("状态", max_length=20, choices=TOKEN_STATUS_CHOICES,
                              default="active", db_index=True)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="children", verbose_name="父令牌",
    )
    branch_label = models.CharField("分支标签", max_length=100, blank=True, default="")
    generation = models.IntegerField("分裂代数", default=0)
    consumed_at = models.DateTimeField("消费时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "执行令牌"
        verbose_name_plural = "执行令牌"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["instance", "status"], name="wf_token_inst_status_idx"),
            models.Index(fields=["instance", "node"], name="wf_token_inst_node_idx"),
        ]

    def __str__(self):
        return f"token#{self.pk} {self.status}"

    @property
    def is_active(self):
        """是否仍在推进。"""
        return self.status == "active"

    def consume(self):
        """消费令牌（进入结束节点、分支拆分、汇聚合并时调用）。"""
        self.status = "consumed"
        self.consumed_at = _now()

    def cancel(self):
        """取消令牌（实例被拒绝/取消/终止时调用）。"""
        self.status = "cancelled"
        self.consumed_at = _now()


# ---------------------------------------------------------------------------
# 8. 人工任务
# ---------------------------------------------------------------------------


class WorkflowTask(models.Model):
    """人工任务：待办 / 已办。

    候选人三件套（users/roles/depts）在创建任务时「解析成快照」写入 JSON：
    角色、部门成员会随时间变化，如果每次鉴权都实时查角色，历史待办会莫名
    易主；快照保证「谁当时该办」与审计一致。assignee 为空表示待认领。
    """

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="tasks", verbose_name="流程实例",
    )
    node = models.ForeignKey(
        WorkflowNode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks", verbose_name="节点",
    )
    token = models.ForeignKey(
        WorkflowToken, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks", verbose_name="令牌",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_tasks", verbose_name="创建人",
    )
    parent_task = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="add_sign_tasks", verbose_name="加签来源",
    )
    name = models.CharField("任务名称", max_length=200)
    status = models.CharField("状态", max_length=20, choices=TASK_STATUS_CHOICES,
                              default="pending", db_index=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wf_assigned_tasks", verbose_name="办理人",
    )
    candidate_users = models.JSONField("候选用户ID", default=_json_list, blank=True)
    candidate_roles = models.JSONField("候选角色", default=_json_list, blank=True)
    candidate_depts = models.JSONField("候选部门ID", default=_json_list, blank=True)
    # 候选集的去规范化索引（形如 ",u:3,u:7,r:manager,d:2,"）：候选池存在 JSON
    # 数组里，SQLite/MySQL 的 JSON 数组查询都不可移植，落成文本后才能用
    # LIKE 在数据库层筛「我的待办」，避免每次请求全表扫未结任务。
    candidate_index = models.TextField("候选索引", blank=True, default="", db_index=True)
    assignee_source = models.CharField("指派来源", max_length=30, blank=True, default="")
    action = models.CharField("办理动作", max_length=20, choices=TASK_ACTION_CHOICES,
                              blank=True, default="")
    comment = models.TextField("办理意见", blank=True, default="")
    payload = models.JSONField("提交数据", default=_json_dict, blank=True)
    priority = models.CharField("优先级", max_length=10, choices=PRIORITY_CHOICES,
                                default="normal", db_index=True)
    due_at = models.DateTimeField("办理截止", null=True, blank=True)
    is_overdue = models.BooleanField("已逾期", default=False, db_index=True)
    claimed_at = models.DateTimeField("认领时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程任务"
        verbose_name_plural = "流程任务"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "assignee"], name="wf_task_status_assignee_idx"),
            models.Index(fields=["status", "due_at"], name="wf_task_status_due_idx"),
            models.Index(fields=["instance", "status"], name="wf_task_inst_status_idx"),
            models.Index(fields=["node", "status"], name="wf_task_node_status_idx"),
        ]

    def __str__(self):
        return f"task#{self.pk} {self.name} [{self.status}]"

    # ---- 状态与派生 ----

    @property
    def is_open(self):
        """是否未结（待认领或处理中）。"""
        return self.status in TASK_OPEN_STATUS

    @property
    def is_claimed(self):
        """是否已被认领/指派。"""
        return self.status == "claimed"

    @property
    def is_completed(self):
        """是否已完成。"""
        return self.status == "completed"

    @property
    def assignee_name(self):
        """办理人展示名。"""
        if self.assignee_id is None:
            return ""
        return getattr(self.assignee, "display_name", "") or self.assignee.username

    @property
    def duration_minutes(self):
        """办理耗时：从创建到完成（未完成按至今）。"""
        end = self.completed_at or _now()
        return max(int((end - self.created_at).total_seconds() // 60), 0)

    @property
    def wait_minutes(self):
        """等待时长：从创建到认领（未认领按至今）。"""
        end = self.claimed_at or _now()
        return max(int((end - self.created_at).total_seconds() // 60), 0)

    @property
    def overdue_minutes(self):
        """逾期分钟数；未逾期返回 0。"""
        if not self.due_at:
            return 0
        end = self.completed_at or _now()
        return max(int((end - self.due_at).total_seconds() // 60), 0)

    @property
    def candidate_user_ids(self):
        """候选用户 id 列表（JSON 里可能混入字符串，统一转 int）。"""
        out = []
        for x in (self.candidate_users or []):
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out

    def candidate_user_queryset(self):
        """候选用户对象（加签弹窗、转办弹窗展示用）。"""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.filter(id__in=self.candidate_user_ids, is_active=True)

    def build_candidate_index(self):
        """把候选用户/角色/部门压成可 LIKE 的索引串。

        统一带首尾逗号，查询侧用 ``",u:3,"`` 精确匹配，避免 ``u:13`` 误命中
        ``u:3``；三要素任一为空时也照样产出合法串，方便直接落库。
        """
        tokens = []
        for uid in self.candidate_user_ids:
            tokens.append(f"u:{uid}")
        for code in (self.candidate_roles or []):
            code = str(code or "").strip()
            if code:
                tokens.append(f"r:{code}")
        for dept in (self.candidate_depts or []):
            if str(dept).isdigit():
                tokens.append(f"d:{int(dept)}")
        return "," + ",".join(tokens) + "," if tokens else ""

    def save(self, *args, **kwargs):
        """保存时同步候选索引，避免各调用方漏更新导致待办丢任务。"""
        update_fields = kwargs.get("update_fields")
        if update_fields is None or {"candidate_users", "candidate_roles",
                                     "candidate_depts"} & set(update_fields):
            self.candidate_index = self.build_candidate_index()
            if update_fields is not None:
                kwargs["update_fields"] = list(set(update_fields) | {"candidate_index"})
        return super().save(*args, **kwargs)

    @staticmethod
    def candidate_tokens_for(user):
        """当前用户作为候选人时的索引 token 列表（用户 + 角色 + 部门）。"""
        if user is None or not getattr(user, "id", None):
            return []
        tokens = [f"u:{user.id}"]
        roles = getattr(user, "roles", None)
        if roles is not None:
            try:
                tokens.extend(f"r:{code}" for code in roles.values_list("code", flat=True) if code)
            except Exception:  # pragma: no cover - 角色表异常不应阻断待办查询
                pass
        dept_id = getattr(user, "department_id", None)
        if dept_id:
            tokens.append(f"d:{int(dept_id)}")
        return tokens

    def is_candidate(self, user):
        """用户是否在候选集内（用户/角色/部门三种快照任一命中）。"""
        if user is None:
            return False
        uid = getattr(user, "id", None)
        if uid and uid in self.candidate_user_ids:
            return True
        roles = set(self.candidate_roles or [])
        if roles:
            user_roles = set(user.roles.values_list("code", flat=True)) if getattr(user, "roles", None) else set()
            if roles & user_roles:
                return True
        depts = set(self.candidate_depts or [])
        if depts:
            dept_id = getattr(user, "department_id", None)
            if dept_id and int(dept_id) in {int(x) for x in depts if str(x).isdigit()}:
                return True
        return False

    def can_be_operated_by(self, user):
        """办理权限：未结 + （指派给本人 / 本人在候选集 / 管理员）。

        候选集是创建时的快照，所以这里不再实时展开角色，避免历史任务易主。
        委派/转办会把任务指派给别人但保留原候选集，原候选人仍可接管，
        因此指派命中后继续回落到候选判断，而不是直接拒绝。
        """
        if user is None or not self.is_open:
            return False
        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True
        uid = getattr(user, "id", None)
        if self.assignee_id and self.assignee_id == uid:
            return True
        return self.is_candidate(user)

    def claim(self, user):
        """认领：只允许待认领状态，且调用方已完成权限校验。"""
        if self.status != "pending":
            raise ValueError("只有待认领任务可以认领")
        self.assignee = user
        self.status = "claimed"
        self.claimed_at = _now()
        return self

    def open_add_sign_count(self):
        """未结的加签任务数（全部结清后令牌才能继续推进）。"""
        return self.add_sign_tasks.filter(status__in=TASK_OPEN_STATUS).count()


# ---------------------------------------------------------------------------
# 9. 评论
# ---------------------------------------------------------------------------


class WorkflowComment(models.Model):
    """流程评论/决策说明：与任务意见分离，支持内部可见（仅办理人/管理员）。"""

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="comments", verbose_name="流程实例",
    )
    task = models.ForeignKey(
        WorkflowTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="comments", verbose_name="任务",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_comments", verbose_name="作者",
    )
    content = models.TextField("内容")
    kind = models.CharField("类型", max_length=20, choices=COMMENT_KIND_CHOICES, default="comment")
    is_internal = models.BooleanField("仅内部可见", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程评论"
        verbose_name_plural = "流程评论"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["instance", "created_at"], name="wf_comment_inst_time_idx"),
        ]

    def __str__(self):
        return f"comment#{self.pk}"

    @property
    def author_name(self):
        """作者展示名。"""
        return getattr(self.owner, "display_name", "") or getattr(self.owner, "username", "")


# ---------------------------------------------------------------------------
# 10. 附件
# ---------------------------------------------------------------------------


class WorkflowAttachment(models.Model):
    """流程附件：只登记元数据与外链，文件本体由 files 应用/对象存储负责。"""

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="attachments", verbose_name="流程实例",
    )
    task = models.ForeignKey(
        WorkflowTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attachments", verbose_name="任务",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_attachments", verbose_name="上传人",
    )
    name = models.CharField("文件名", max_length=200)
    url = models.CharField("访问地址", max_length=500, blank=True, default="")
    size = models.IntegerField("大小(字节)", default=0)
    mime = models.CharField("MIME", max_length=100, blank=True, default="")
    checksum = models.CharField("校验和", max_length=64, blank=True, default="")
    kind = models.CharField("类型", max_length=20, default="file")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程附件"
        verbose_name_plural = "流程附件"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["instance", "created_at"], name="wf_attach_inst_time_idx"),
        ]

    def __str__(self):
        return self.name

    @property
    def size_kb(self):
        """KB 展示。"""
        return round(int(self.size or 0) / 1024.0, 1)


# ---------------------------------------------------------------------------
# 11. 流程变量
# ---------------------------------------------------------------------------


class WorkflowVariable(models.Model):
    """实例变量：key/value/type，条件表达式与指派表达式统一从这里取数。

    值统一存 JSON（字符串也是 JSON 字符串），读取时按 var_type 做一次强转，
    避免「表单提交的是字符串 '3'，金额条件 > 5000 永远为假」这类隐式类型 bug。
    """

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="variables", verbose_name="流程实例",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_variables", verbose_name="所有者",
    )
    key = models.CharField("变量名", max_length=100)
    value = models.JSONField("值", null=True, blank=True)
    var_type = models.CharField("类型", max_length=20, choices=VARIABLE_TYPE_CHOICES, default="string")
    is_secret = models.BooleanField("敏感", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程变量"
        verbose_name_plural = "流程变量"
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(fields=["instance", "key"], name="wf_var_inst_key_uniq"),
        ]

    def __str__(self):
        return f"{self.key}={self.value}"

    @property
    def typed_value(self):
        """按声明类型返回值；转换失败时回退原始值而不是抛错。"""
        raw = self.value
        if raw is None:
            return None
        try:
            if self.var_type == "number":
                if isinstance(raw, bool):
                    return int(raw)
                if isinstance(raw, (int, float)):
                    return raw
                text = str(raw).strip()
                return float(text) if "." in text else int(text)
            if self.var_type == "boolean":
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, (int, float)):
                    return bool(raw)
                return str(raw).strip().lower() in ("1", "true", "yes", "on")
            if self.var_type == "json":
                return raw
            if self.var_type == "date":
                return str(raw)[:10]
            if self.var_type == "datetime":
                return str(raw)[:19]
            return str(raw)
        except (TypeError, ValueError):
            return raw


# ---------------------------------------------------------------------------
# 12. 定时器
# ---------------------------------------------------------------------------


class WorkflowTimer(models.Model):
    """定时器：到期提醒、超时升级。

    扫描接口按 ``status=scheduled and fire_at<=now`` 取一批，触发后立刻改成
    fired，天然幂等——重复调用不会重复发通知。
    """

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="timers", verbose_name="流程实例",
    )
    task = models.ForeignKey(
        WorkflowTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="timers", verbose_name="任务",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_timers", verbose_name="所有者",
    )
    timer_type = models.CharField("类型", max_length=20, choices=TIMER_TYPE_CHOICES, default="remind")
    fire_at = models.DateTimeField("触发时间", db_index=True)
    status = models.CharField("状态", max_length=20, choices=TIMER_STATUS_CHOICES,
                              default="scheduled", db_index=True)
    fired_at = models.DateTimeField("实际触发时间", null=True, blank=True)
    attempts = models.IntegerField("触发次数", default=0)
    repeat_minutes = models.IntegerField("重复间隔(分钟)", default=0)
    payload = models.JSONField("附加数据", default=_json_dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程定时器"
        verbose_name_plural = "流程定时器"
        ordering = ["fire_at", "id"]
        indexes = [
            models.Index(fields=["status", "fire_at"], name="wf_timer_status_fire_idx"),
            models.Index(fields=["instance", "status"], name="wf_timer_inst_status_idx"),
        ]

    def __str__(self):
        return f"{self.timer_type}@{self.fire_at}"

    @property
    def is_due(self):
        """是否已到触发时间且尚未触发。"""
        return self.status == "scheduled" and self.fire_at is not None and self.fire_at <= _now()

    def mark_fired(self):
        """标记已触发（由扫描任务调用）。"""
        self.status = "fired"
        self.fired_at = _now()
        self.attempts = int(self.attempts or 0) + 1
        return self

    def cancel(self):
        """取消未触发的定时器。"""
        if self.status == "scheduled":
            self.status = "cancelled"
        return self


# ---------------------------------------------------------------------------
# 13. 委托
# ---------------------------------------------------------------------------


class WorkflowDelegation(models.Model):
    """任务委托：在时间段内把「应由我办理」的任务自动加派给受托人。

    委托不改变原任务的 assignee（保留责任链），只在指派解析时把受托人
    追加进候选集，这样原办理人仍可处理，受托人也能接手。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_delegations", verbose_name="所有者",
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_delegations_out", verbose_name="委托人",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_delegations_in", verbose_name="受托人",
    )
    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="delegations", verbose_name="限定流程",
    )
    scope = models.CharField("范围", max_length=20, choices=DELEGATION_SCOPE_CHOICES, default="all")
    start_at = models.DateTimeField("开始时间", default=_now)
    end_at = models.DateTimeField("结束时间")
    status = models.CharField("状态", max_length=20, choices=DELEGATION_STATUS_CHOICES,
                              default="active", db_index=True)
    reason = models.TextField("委托原因", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "任务委托"
        verbose_name_plural = "任务委托"
        ordering = ["-start_at", "-id"]
        indexes = [
            models.Index(fields=["from_user", "status"], name="wf_deleg_from_status_idx"),
            models.Index(fields=["to_user", "status"], name="wf_deleg_to_status_idx"),
        ]

    def __str__(self):
        return f"{self.from_user_id}->{self.to_user_id}"

    @property
    def is_active(self):
        """状态为 active 且当前时间在窗口内。"""
        if self.status != "active":
            return False
        now = _now()
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True

    def covers(self, definition=None):
        """是否覆盖指定流程：all 覆盖全部；definition 需要绑定同一流程。"""
        if self.scope == "all":
            return True
        if self.scope == "definition":
            return bool(definition is not None and self.definition_id == definition.id)
        return False


# ---------------------------------------------------------------------------
# 14. 通知（站内 + Webhook 模拟投递）
# ---------------------------------------------------------------------------


class WorkflowNotification(models.Model):
    """流程通知：站内信落库，Webhook/邮件渠道以状态模拟（不发起真实网络请求）。

    dedup_key 非空时同收件人只落一条，用来抑制「每次扫描都提醒一遍」。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_notification_records", verbose_name="创建人",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_notifications", verbose_name="接收人",
    )
    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications", verbose_name="流程实例",
    )
    task = models.ForeignKey(
        WorkflowTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications", verbose_name="任务",
    )
    title = models.CharField("标题", max_length=200)
    content = models.TextField("内容", blank=True, default="")
    level = models.CharField("级别", max_length=10, choices=NOTIFICATION_LEVEL_CHOICES, default="info")
    channel = models.CharField("渠道", max_length=20, choices=NOTIFICATION_CHANNEL_CHOICES, default="inapp")
    status = models.CharField("状态", max_length=20, choices=NOTIFICATION_STATUS_CHOICES,
                              default="sent", db_index=True)
    dedup_key = models.CharField("去重键", max_length=120, blank=True, default="", db_index=True)
    payload = models.JSONField("载荷", default=_json_dict, blank=True)
    sent_at = models.DateTimeField("发送时间", null=True, blank=True)
    read_at = models.DateTimeField("阅读时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程通知"
        verbose_name_plural = "流程通知"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "status"], name="wf_notif_recipient_status_idx"),
            models.Index(fields=["instance", "created_at"], name="wf_notif_inst_time_idx"),
        ]

    def __str__(self):
        return f"{self.recipient_id}:{self.title[:30]}"

    @property
    def is_read(self):
        """是否已读（read_at 为准，兼容 status=read 的写入路径）。"""
        return self.read_at is not None or self.status == "read"

    def mark_read(self):
        """标记已读（幂等：已读不再改时间）。"""
        if self.read_at is None:
            self.read_at = _now()
        self.status = "read"
        return self


# ---------------------------------------------------------------------------
# 15. 审计日志
# ---------------------------------------------------------------------------


class WorkflowAuditLog(models.Model):
    """审计日志：谁、在什么时间、对哪个对象做了什么、前后状态如何、耗时多少。

    审计只追加不修改（updated_at 保留是为了统一模型约定），
    时间线接口与合规导出都以此表为主干。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_audit_logs", verbose_name="所有者",
    )
    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, null=True, blank=True,
        related_name="audit_logs", verbose_name="流程实例",
    )
    task = models.ForeignKey(
        WorkflowTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_logs", verbose_name="任务",
    )
    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_logs", verbose_name="流程定义",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wf_audit_actions", verbose_name="操作者",
    )
    action = models.CharField("动作", max_length=40, db_index=True)
    from_status = models.CharField("原状态", max_length=20, blank=True, default="")
    to_status = models.CharField("新状态", max_length=20, blank=True, default="")
    detail = models.JSONField("详情", default=_json_dict, blank=True)
    duration_ms = models.IntegerField("耗时(毫秒)", default=0)
    ip = models.CharField("IP", max_length=45, blank=True, default="")
    created_at = models.DateTimeField("发生时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程审计日志"
        verbose_name_plural = "流程审计日志"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["instance", "-created_at"], name="wf_audit_inst_time_idx"),
            models.Index(fields=["actor", "-created_at"], name="wf_audit_actor_time_idx"),
            models.Index(fields=["definition", "action"], name="wf_audit_def_action_idx"),
        ]

    def __str__(self):
        return f"{self.action}@{self.created_at:%Y-%m-%d %H:%M}"

    @property
    def actor_name(self):
        """操作者展示名（系统动作可能无 actor）。"""
        if self.actor_id is None:
            return "系统"
        return getattr(self.actor, "display_name", "") or self.actor.username


# ---------------------------------------------------------------------------
# 16. 实例快照（回放）
# ---------------------------------------------------------------------------


class WorkflowSnapshot(models.Model):
    """实例快照：每次关键流转写入一份完整状态，用于回放与问题定位。

    快照按 seq 递增，checksum 保证「同样的状态得到同样的指纹」，
    回放接口按 seq 升序拼接即可还原任意时刻。
    """

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE,
        related_name="snapshots", verbose_name="流程实例",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_snapshots", verbose_name="所有者",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wf_snapshots_created", verbose_name="触发人",
    )
    seq = models.IntegerField("序号", default=1)
    reason = models.CharField("触发原因", max_length=40, choices=SNAPSHOT_REASON_CHOICES,
                              default="manual")
    node_key = models.CharField("当前节点", max_length=64, blank=True, default="")
    state = models.JSONField("状态快照", default=_json_dict, blank=True)
    token_count = models.IntegerField("活跃令牌数", default=0)
    task_count = models.IntegerField("未结任务数", default=0)
    checksum = models.CharField("校验和", max_length=64, blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "实例快照"
        verbose_name_plural = "实例快照"
        ordering = ["-seq", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["instance", "seq"], name="wf_snapshot_inst_seq_uniq"),
        ]
        indexes = [
            models.Index(fields=["instance", "seq"], name="wf_snapshot_inst_seq_idx"),
        ]

    def __str__(self):
        return f"snapshot#{self.seq} of {self.instance_id}"


# ---------------------------------------------------------------------------
# 17. 指标滚动表
# ---------------------------------------------------------------------------


class WorkflowMetric(models.Model):
    """日粒度指标滚动表：把「趋势」查询从扫实例表变成扫小表。

    引擎在发起/完成/拒绝时同步累加当日行；历史数据（上线前）通过
    services.refresh_metric_day() 重算，保证趋势图与明细一致。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_metrics", verbose_name="所有者",
    )
    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.CASCADE, null=True, blank=True,
        related_name="metrics", verbose_name="流程定义",
    )
    metric_date = models.DateField("日期", db_index=True)
    instances_started = models.IntegerField("发起数", default=0)
    instances_completed = models.IntegerField("完成数", default=0)
    instances_rejected = models.IntegerField("拒绝数", default=0)
    tasks_created = models.IntegerField("任务创建数", default=0)
    tasks_completed = models.IntegerField("任务完成数", default=0)
    overdue_tasks = models.IntegerField("逾期任务数", default=0)
    avg_duration_minutes = models.FloatField("平均时长(分钟)", default=0.0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程指标"
        verbose_name_plural = "流程指标"
        ordering = ["-metric_date", "definition_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "definition", "metric_date"], name="wf_metric_owner_def_date_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "metric_date"], name="wf_metric_owner_date_idx"),
        ]

    def __str__(self):
        return f"{self.metric_date} started={self.instances_started}"

    @property
    def completion_rate(self):
        """当日完成率（完成 / 发起）。"""
        started = int(self.instances_started or 0)
        if started <= 0:
            return 0.0
        return round(int(self.instances_completed or 0) * 100.0 / started, 1)


# ---------------------------------------------------------------------------
# 18. Webhook 订阅（模拟投递）
# ---------------------------------------------------------------------------


class WorkflowWebhook(models.Model):
    """Webhook 订阅：事件命中时落一条投递记录并更新状态，不发起真实网络请求。

    生产接入时把 ``_simulate_delivery`` 换成带签名与重试的 HTTP 客户端即可，
    数据模型与接口契约不变（events 支持 ``task.created`` 这类点分事件名）。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="wf_webhooks", verbose_name="所有者",
    )
    definition = models.ForeignKey(
        WorkflowDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="webhooks", verbose_name="限定流程",
    )
    name = models.CharField("名称", max_length=120)
    url = models.CharField("回调地址", max_length=500)
    events = models.JSONField("订阅事件", default=_json_list, blank=True)
    secret = models.CharField("签名密钥", max_length=64, blank=True, default="")
    active = models.BooleanField("启用", default=True, db_index=True)
    last_status = models.CharField("最近状态", max_length=20, blank=True, default="")
    last_delivery_at = models.DateTimeField("最近投递时间", null=True, blank=True)
    failure_count = models.IntegerField("累计失败", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "流程 Webhook"
        verbose_name_plural = "流程 Webhook"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "active"], name="wf_webhook_owner_active_idx"),
        ]

    def __str__(self):
        return f"{self.name}->{self.url[:40]}"

    def matches(self, event):
        """事件是否命中：空订阅表示全订阅，支持 ``task.*`` 通配。"""
        name = str(event or "")
        events = [str(x) for x in (self.events or [])]
        if not events:
            return True
        for pattern in events:
            if pattern == name or pattern == "*":
                return True
            if pattern.endswith(".*") and name.startswith(pattern[:-1]):
                return True
        return False
