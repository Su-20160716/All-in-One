# -*- coding: utf-8 -*-
"""合规治理 · 数据模型（22 个）。

分层与约定
----------
1. 全部业务表都带 `owner` 外键（行级权限统一走 core.scoping），并继承
   `GovTimeStamped` 拿到 created_at / updated_at；owner 的 related_name 逐表
   显式书写而不是 `%(class)s`，这样反向查询名在代码里是「可读且稳定」的，
   也避免以后新增抽象基类时出现同名冲突。
2. 状态机字段一律用 CharField + choices 常量而不是 database enum：
   SQLite 的 CHECK 约束在历史数据修正时要重建表，而业务状态（草案 → 评审 →
   批准 → 发布）可能按企业实际情况扩展，CharField 让扩展只需改常量。
3. 计算类字段（风险分值、评估得分、覆盖率）在设计上「允许冗余存储」：
   分值会被接口高频排序与筛选，实时计算会让列表查询变成 N+1；因此由
   governance.services 统一写入，读写分离，服务层是唯一计算入口。
4. 证据只存元数据 + 哈希，不落真实文件：本平台的文件存储另有 files 应用，
   治理证据需要的是「可校验的引用」，把二进制搬进来只会带来合规风险
   （敏感证据副本扩散）与容量问题。
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# 枚举：与前端下拉共用一份中文标签，避免后端出现「魔法字符串」
# ---------------------------------------------------------------------------

FRAMEWORK_KINDS = ("iso27001", "gdpr", "soc2", "custom")
FRAMEWORK_KIND_LABELS = {
    "iso27001": "ISO 27001",
    "gdpr": "GDPR",
    "soc2": "SOC 2",
    "custom": "自定义框架",
}

FRAMEWORK_STATUS = ("draft", "active", "retired")
FRAMEWORK_STATUS_LABELS = {
    "draft": "草案",
    "active": "生效",
    "retired": "已停用",
}

POLICY_KINDS = ("security", "privacy", "conduct", "operational")
POLICY_KIND_LABELS = {
    "security": "信息安全",
    "privacy": "隐私保护",
    "conduct": "行为准则",
    "operational": "运营管理",
}

POLICY_STATUS = ("draft", "reviewing", "approved", "published", "retired")
POLICY_STATUS_LABELS = {
    "draft": "草稿",
    "reviewing": "评审中",
    "approved": "已批准",
    "published": "已发布",
    "retired": "已停用",
}

CONTROL_FREQUENCIES = ("once", "quarterly", "monthly", "weekly", "continuous")
CONTROL_FREQUENCY_LABELS = {
    "once": "一次性",
    "quarterly": "每季度",
    "monthly": "每月",
    "weekly": "每周",
    "continuous": "持续",
}

CONTROL_STATUS = ("active", "inactive")
CONTROL_STATUS_LABELS = {"active": "启用", "inactive": "停用"}

TEST_METHODS = ("manual", "automated")
TEST_METHOD_LABELS = {"manual": "人工", "automated": "自动化"}

TEST_RESULTS = ("pass", "fail", "unknown")
TEST_RESULT_LABELS = {"pass": "通过", "fail": "失败", "unknown": "未执行"}

ASSESSMENT_STATUS = ("planned", "in_progress", "completed", "overdue")
ASSESSMENT_STATUS_LABELS = {
    "planned": "已计划",
    "in_progress": "进行中",
    "completed": "已完成",
    "overdue": "已逾期",
}

ASSESSMENT_ITEM_STATUS = ("not_started", "in_progress", "passed", "failed", "not_applicable")
ASSESSMENT_ITEM_LABELS = {
    "not_started": "未开始",
    "in_progress": "进行中",
    "passed": "通过",
    "failed": "未通过",
    "not_applicable": "不适用",
}

EVIDENCE_TARGETS = ("control", "policy", "assessment", "risk")
EVIDENCE_TARGET_LABELS = {
    "control": "控制",
    "policy": "策略",
    "assessment": "评估",
    "risk": "风险",
}
EVIDENCE_KINDS = ("link", "file", "hash")
EVIDENCE_KIND_LABELS = {"link": "链接", "file": "文件引用", "hash": "哈希指纹"}

RISK_LEVELS = ("low", "medium", "high", "critical")
RISK_LEVEL_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
}

RISK_STATUS = ("identified", "assessing", "treating", "monitored", "closed")
RISK_STATUS_LABELS = {
    "identified": "已识别",
    "assessing": "评估中",
    "treating": "处置中",
    "monitored": "监控中",
    "closed": "已关闭",
}

TREATMENT_STRATEGIES = ("mitigate", "transfer", "avoid", "accept")
TREATMENT_STRATEGY_LABELS = {
    "mitigate": "降低",
    "transfer": "转移",
    "avoid": "规避",
    "accept": "接受",
}

TREATMENT_STATUS = ("planned", "in_progress", "done", "cancelled")
TREATMENT_STATUS_LABELS = {
    "planned": "已计划",
    "in_progress": "进行中",
    "done": "已完成",
    "cancelled": "已取消",
}

DATA_ASSET_KINDS = ("personal", "financial", "operational")
DATA_ASSET_KIND_LABELS = {
    "personal": "个人信息",
    "financial": "财务数据",
    "operational": "运营数据",
}

DATA_CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
DATA_CLASSIFICATION_LABELS = {
    "public": "公开",
    "internal": "内部",
    "confidential": "机密",
    "restricted": "严格受限",
}

DATA_ASSET_STATUS = ("active", "archived", "anonymized", "deleted")
DATA_ASSET_STATUS_LABELS = {
    "active": "在用",
    "archived": "已归档",
    "anonymized": "已匿名化",
    "deleted": "已删除",
}

PROCESSING_STATUS = ("draft", "active", "suspended", "closed")
PROCESSING_STATUS_LABELS = {
    "draft": "草稿",
    "active": "生效",
    "suspended": "已暂停",
    "closed": "已关闭",
}

RETENTION_KINDS = ("data_asset", "evidence", "consent")
RETENTION_KIND_LABELS = {
    "data_asset": "数据资产",
    "evidence": "证据",
    "consent": "同意记录",
}

RETENTION_ACTIONS = ("delete", "anonymize", "archive")
RETENTION_ACTION_LABELS = {
    "delete": "删除",
    "anonymize": "匿名化",
    "archive": "归档",
}

RETENTION_RUN_STATUS = ("planned", "executed", "skipped")
RETENTION_RUN_LABELS = {
    "planned": "待执行",
    "executed": "已执行",
    "skipped": "已跳过",
}

CONSENT_STATUS = ("granted", "withdrawn", "expired")
CONSENT_STATUS_LABELS = {
    "granted": "已授予",
    "withdrawn": "已撤回",
    "expired": "已过期",
}

AUDIT_KINDS = ("internal", "external", "surprise")
AUDIT_KIND_LABELS = {
    "internal": "内部审计",
    "external": "外部审计",
    "surprise": "突击审计",
}

AUDIT_STATUS = ("planned", "in_progress", "completed", "cancelled")
AUDIT_STATUS_LABELS = {
    "planned": "已计划",
    "in_progress": "进行中",
    "completed": "已完成",
    "cancelled": "已取消",
}

FINDING_SEVERITIES = ("low", "medium", "high", "critical")
FINDING_SEVERITY_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
}

FINDING_STATUS = ("open", "in_progress", "resolved", "verified")
FINDING_STATUS_LABELS = {
    "open": "待处理",
    "in_progress": "处理中",
    "resolved": "已解决",
    "verified": "已验证",
}

REMEDIATION_STATUS = ("open", "in_progress", "done", "verified")
REMEDIATION_STATUS_LABELS = {
    "open": "待开始",
    "in_progress": "进行中",
    "done": "已完成",
    "verified": "已验证",
}


class GovTimeStamped(models.Model):
    """统一时间戳基类。

    auto_now / auto_now_add 由数据库层之外的对象保存钩子写入，测试与批量脚本
    也能直接拿到时间；抽象基类不生成表，所有具体模型复用同一套口径。
    """

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 1. 框架与控制项
# ---------------------------------------------------------------------------


class Framework(GovTimeStamped):
    """合规框架：ISO 27001 / GDPR / SOC2 / 自定义。

    框架是「评估与控制」的根：覆盖面、差距分析、达成率都按框架汇总，
    因此 version 参与唯一约束——同一框架的不同版本需要能并存，
    否则升级版本时会覆盖历史评估的归属。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_frameworks", verbose_name="所有者")
    name = models.CharField("框架名称", max_length=120)
    version = models.CharField("版本", max_length=40, default="2022")
    kind = models.CharField("类型", max_length=20, choices=[(k, FRAMEWORK_KIND_LABELS[k]) for k in FRAMEWORK_KINDS],
                            default="custom")
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)

    class Meta:
        verbose_name = "合规框架"
        verbose_name_plural = "合规框架"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name", "version"],
                                    name="gov_framework_owner_name_ver_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="gov_fw_owner_status_idx"),
        ]

    def __str__(self):
        return f"{self.name} {self.version}"

    def publish(self):
        """把框架置为生效：草案态之外也允许重复调用（幂等），便于脚本重跑。"""
        self.status = "active"
        self.save(update_fields=["status", "updated_at"])
        return self

    def to_dict(self):
        return {
            "id": self.pk,
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "kind_label": FRAMEWORK_KIND_LABELS.get(self.kind, self.kind),
            "description": self.description,
            "status": self.status,
            "status_label": FRAMEWORK_STATUS_LABELS.get(self.status, self.status),
            "control_count": getattr(self, "control_total", None)
            if hasattr(self, "control_total") else self.controls.count(),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class FrameworkControl(GovTimeStamped):
    """框架条款（控制项）：编号 + 标题 + 类别 + 权重。

    weight 是评估加权得分的权重来源：ISO 里「访问控制」与「文档标识」的
    重要性显然不同，等权计算会把文档类条款的合规感放大。weight 落在
    1..10，服务层计算得分时按 weight 求和，而不是简单计数。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_framework_controls", verbose_name="所有者")
    framework = models.ForeignKey(Framework, on_delete=models.CASCADE,
                                  related_name="controls", verbose_name="框架")
    code = models.CharField("控制编号", max_length=60)
    title = models.CharField("控制标题", max_length=200)
    description = models.TextField("控制描述", blank=True, default="")
    category = models.CharField("类别", max_length=60, default="通用", db_index=True)
    weight = models.PositiveSmallIntegerField("权重", default=1)

    class Meta:
        verbose_name = "框架控制项"
        verbose_name_plural = "框架控制项"
        ordering = ["framework_id", "code"]
        constraints = [
            models.UniqueConstraint(fields=["framework", "code"],
                                    name="gov_fwcontrol_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["framework", "category"], name="gov_fwc_fw_cat_idx"),
        ]

    def __str__(self):
        return f"{self.code} {self.title}"

    def to_dict(self):
        return {
            "id": self.pk,
            "framework_id": self.framework_id,
            "code": self.code,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "weight": self.weight,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ControlMapping(GovTimeStamped):
    """框架条款 ↔ 内部控制的映射（差距分析的判据）。

    之所以单独建表而不是在 Control 上放一个 framework_control 外键：
    一条内部实施（例如「统一身份认证」）往往同时满足多条框架条款，
    一对一外键会让合规团队为同一条控制建多份副本。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_control_mappings", verbose_name="所有者")
    framework_control = models.ForeignKey(FrameworkControl, on_delete=models.CASCADE,
                                          related_name="mappings", verbose_name="框架条款")
    control = models.ForeignKey("governance.Control", on_delete=models.CASCADE,
                                related_name="framework_mappings", verbose_name="内部实施")
    strength = models.PositiveSmallIntegerField("覆盖强度%", default=100)
    note = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "控制映射"
        verbose_name_plural = "控制映射"
        ordering = ["framework_control_id", "control_id"]
        constraints = [
            models.UniqueConstraint(fields=["framework_control", "control"],
                                    name="gov_control_mapping_uniq"),
        ]

    def __str__(self):
        return f"{self.framework_control_id}->{self.control_id}"

    def to_dict(self):
        return {
            "id": self.pk,
            "framework_control_id": self.framework_control_id,
            "control_id": self.control_id,
            "strength": self.strength,
            "note": self.note,
            "created_at": _iso(self.created_at),
        }


# ---------------------------------------------------------------------------
# 2. 策略与版本
# ---------------------------------------------------------------------------


class Policy(GovTimeStamped):
    """制度策略：草案 → 评审 → 批准 → 发布 → 停用。

    状态推进由服务层校验（不允许跳级），这里只存状态与时间锚点；
    next_review_on 是评审提醒的依据，允许为空表示「不设周期评审」。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_policies", verbose_name="所有者")
    code = models.CharField("策略编码", max_length=60)
    name = models.CharField("策略名称", max_length=200)
    kind = models.CharField("类型", max_length=20, default="security", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    content = models.TextField("正文", blank=True, default="")
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    scope = models.CharField("适用范围", max_length=200, blank=True, default="")
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)
    next_review_on = models.DateField("下次评审日", null=True, blank=True, db_index=True)
    current_version = models.CharField("当前版本", max_length=40, blank=True, default="")
    approved_by_name = models.CharField("批准人", max_length=80, blank=True, default="")
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "治理策略"
        verbose_name_plural = "治理策略"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="gov_policy_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="gov_policy_owner_status_idx"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def to_dict(self):
        return {
            "id": self.pk,
            "code": self.code,
            "name": self.name,
            "kind": self.kind,
            "kind_label": POLICY_KIND_LABELS.get(self.kind, self.kind),
            "description": self.description,
            "owner_name": self.owner_name,
            "scope": self.scope,
            "status": self.status,
            "status_label": POLICY_STATUS_LABELS.get(self.status, self.status),
            "next_review_on": _iso(self.next_review_on),
            "current_version": self.current_version,
            "approved_by_name": self.approved_by_name,
            "published_at": _iso(self.published_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class PolicyVersion(GovTimeStamped):
    """策略版本快照：发布/批准时固化正文，回滚即「重新发布某历史版本」。

    正文快照必须独立落库，不能只存一个指针——制度审计要求能证明
    「某年某月生效的文本写的是什么」，而策略主表会继续被编辑。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_policy_versions", verbose_name="所有者")
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE,
                               related_name="versions", verbose_name="策略")
    version = models.CharField("版本号", max_length=40)
    content_snapshot = models.TextField("内容快照", blank=True, default="")
    change_note = models.TextField("变更说明", blank=True, default="")
    approver_name = models.CharField("审批人", max_length=80, blank=True, default="")
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "策略版本"
        verbose_name_plural = "策略版本"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["policy", "version"],
                                    name="gov_policy_version_uniq"),
        ]
        indexes = [
            models.Index(fields=["policy", "-created_at"], name="gov_pv_policy_time_idx"),
        ]

    def __str__(self):
        return f"{self.policy_id}@{self.version}"

    def to_dict(self):
        return {
            "id": self.pk,
            "policy_id": self.policy_id,
            "version": self.version,
            "change_note": self.change_note,
            "approver_name": self.approver_name,
            "published_at": _iso(self.published_at),
            "content_present": bool(self.content_snapshot),
            "content_length": len(self.content_snapshot or ""),
            "created_at": _iso(self.created_at),
        }


# ---------------------------------------------------------------------------
# 3. 控制与测试
# ---------------------------------------------------------------------------


class Control(GovTimeStamped):
    """内部控制（实施项）：编号、频率、自动化标记、启停状态。

    automated 与 frequency 共同决定「应该多频繁地产生测试记录」，
    服务层据此判断控制是否「久未测试」，而不是由前端每周提醒。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_controls", verbose_name="所有者")
    code = models.CharField("控制编码", max_length=60)
    name = models.CharField("控制名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    category = models.CharField("类别", max_length=60, default="通用", db_index=True)
    owner_name = models.CharField("控制负责人", max_length=80, blank=True, default="")
    frequency = models.CharField("执行频率", max_length=20, default="quarterly")
    automated = models.BooleanField("自动化", default=False)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    effectiveness = models.PositiveSmallIntegerField("有效性%", default=0)
    last_tested_at = models.DateTimeField("最近测试时间", null=True, blank=True)

    class Meta:
        verbose_name = "内部控制"
        verbose_name_plural = "内部控制"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="gov_control_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "category"], name="gov_control_cat_idx"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def to_dict(self):
        return {
            "id": self.pk,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "owner_name": self.owner_name,
            "frequency": self.frequency,
            "frequency_label": CONTROL_FREQUENCY_LABELS.get(self.frequency, self.frequency),
            "automated": self.automated,
            "status": self.status,
            "status_label": CONTROL_STATUS_LABELS.get(self.status, self.status),
            "effectiveness": self.effectiveness,
            "last_tested_at": _iso(self.last_tested_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ControlTest(GovTimeStamped):
    """控制测试定义：步骤 JSON + 通过条件 + 最近结果。

    steps 存为数组（每步一句可执行描述），是为了让自动化执行器与人工
    复核共用同一份定义；最近结果冗余在测试定义上，列表页无需联表。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_control_tests", verbose_name="所有者")
    control = models.ForeignKey(Control, on_delete=models.CASCADE,
                                related_name="tests", verbose_name="控制")
    name = models.CharField("测试名称", max_length=200)
    method = models.CharField("方法", max_length=20, default="manual")
    steps = models.JSONField("测试步骤", default=list, blank=True)
    pass_criteria = models.TextField("通过条件", blank=True, default="")
    last_result = models.CharField("最近结果", max_length=20, default="unknown", db_index=True)
    last_run_at = models.DateTimeField("最近执行时间", null=True, blank=True)

    class Meta:
        verbose_name = "控制测试"
        verbose_name_plural = "控制测试"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["control", "method"], name="gov_ctrl_test_method_idx"),
        ]

    def __str__(self):
        return f"{self.control_id}:{self.name}"

    def to_dict(self):
        return {
            "id": self.pk,
            "control_id": self.control_id,
            "name": self.name,
            "method": self.method,
            "method_label": TEST_METHOD_LABELS.get(self.method, self.method),
            "steps": self.steps or [],
            "step_count": len(self.steps or []),
            "pass_criteria": self.pass_criteria,
            "last_result": self.last_result,
            "last_result_label": TEST_RESULT_LABELS.get(self.last_result, self.last_result),
            "last_run_at": _iso(self.last_run_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ControlTestRun(GovTimeStamped):
    """控制测试执行历史。

    单独建表而不是把结果塞进 ControlTest.steps 的 JSON：
    「结果历史」接口需要按时间倒序分页、按结果聚合，JSON 数组做不到索引。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_control_test_runs", verbose_name="所有者")
    test = models.ForeignKey(ControlTest, on_delete=models.CASCADE,
                             related_name="runs", verbose_name="测试")
    result = models.CharField("结果", max_length=20, default="pass", db_index=True)
    note = models.TextField("执行说明", blank=True, default="")
    runner_name = models.CharField("执行人", max_length=80, blank=True, default="")
    duration_ms = models.PositiveIntegerField("耗时(毫秒)", default=0)
    run_at = models.DateTimeField("执行时间", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "控制测试记录"
        verbose_name_plural = "控制测试记录"
        ordering = ["-run_at"]
        indexes = [
            models.Index(fields=["test", "-run_at"], name="gov_ctrl_run_time_idx"),
            models.Index(fields=["result", "-run_at"], name="gov_ctrl_run_result_idx"),
        ]

    def __str__(self):
        return f"run#{self.pk}:{self.result}"

    def to_dict(self):
        return {
            "id": self.pk,
            "test_id": self.test_id,
            "result": self.result,
            "result_label": TEST_RESULT_LABELS.get(self.result, self.result),
            "note": self.note,
            "runner_name": self.runner_name,
            "duration_ms": self.duration_ms,
            "run_at": _iso(self.run_at),
            "created_at": _iso(self.created_at),
        }


# ---------------------------------------------------------------------------
# 4. 评估与评估项
# ---------------------------------------------------------------------------


class Assessment(GovTimeStamped):
    """合规评估活动：框架 + 范围 + 起止 + 负责人 + 得分。

    score 由服务层在「完成/批量更新」时重算，冗余存储用于列表排序；
    逾期状态不靠定时任务改写数据库——status=planned/in_progress 且
    end_on 已过的评估在读取时被判为 overdue，避免扫描任务漂移。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_assessments", verbose_name="所有者")
    name = models.CharField("评估名称", max_length=200)
    framework = models.ForeignKey(Framework, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="assessments", verbose_name="框架")
    scope = models.CharField("评估范围", max_length=200, blank=True, default="")
    status = models.CharField("状态", max_length=20, default="planned", db_index=True)
    start_on = models.DateField("开始日期", null=True, blank=True)
    end_on = models.DateField("结束日期", null=True, blank=True)
    lead_name = models.CharField("负责人", max_length=80, blank=True, default="")
    score = models.DecimalField("得分", max_digits=5, decimal_places=2, default=0)

    class Meta:
        verbose_name = "合规评估"
        verbose_name_plural = "合规评估"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="gov_assess_owner_status_idx"),
            models.Index(fields=["framework", "status"], name="gov_assess_fw_status_idx"),
        ]

    def __str__(self):
        return self.name

    def effective_status(self, today=None):
        """读取时的「有效状态」：计划中/进行中但已过结束日 → 逾期。

        逾期是时间推导出来的事实，不需要后台任务去刷字段；
        额外返回 effective_status 让前端展示与统计口径一致。
        """
        today = today or timezone.localdate()
        if self.status in ("planned", "in_progress") and self.end_on and self.end_on < today:
            return "overdue"
        return self.status

    def to_dict(self, today=None):
        return {
            "id": self.pk,
            "name": self.name,
            "framework_id": self.framework_id,
            "framework_name": getattr(self.framework, "name", "") if self.framework_id else "",
            "scope": self.scope,
            "status": self.status,
            "effective_status": self.effective_status(today),
            "status_label": ASSESSMENT_STATUS_LABELS.get(self.effective_status(today), ""),
            "start_on": _iso(self.start_on),
            "end_on": _iso(self.end_on),
            "lead_name": self.lead_name,
            "score": float(self.score or 0),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class AssessmentItem(GovTimeStamped):
    """评估项：一条框架条款或一条内部控制的评估结论。

    framework_control 与 control 至少给一个：前者用于框架达成率，
    后者用于「控制有效性」；两个都给时以框架条款的 weight 为准。
    remediation_task 可空——只有未通过项才需要整改，但允许先记录后补建。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_assessment_items", verbose_name="所有者")
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE,
                                   related_name="items", verbose_name="评估")
    framework_control = models.ForeignKey(FrameworkControl, on_delete=models.SET_NULL,
                                          null=True, blank=True,
                                          related_name="assessment_items", verbose_name="框架条款")
    control = models.ForeignKey(Control, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="assessment_items", verbose_name="内部控制")
    status = models.CharField("状态", max_length=20, default="not_started", db_index=True)
    evidence_note = models.TextField("证据说明", blank=True, default="")
    note = models.TextField("备注", blank=True, default="")
    score = models.DecimalField("得分", max_digits=5, decimal_places=2, default=0)
    weight = models.PositiveSmallIntegerField("权重", default=1)
    remediation_task = models.ForeignKey("governance.RemediationTask", on_delete=models.SET_NULL,
                                         null=True, blank=True,
                                         related_name="assessment_items", verbose_name="整改任务")

    class Meta:
        verbose_name = "评估项"
        verbose_name_plural = "评估项"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["assessment", "status"], name="gov_item_assess_status_idx"),
            models.Index(fields=["framework_control", "status"], name="gov_item_fwc_status_idx"),
        ]

    def __str__(self):
        return f"item#{self.pk}:{self.status}"

    def to_dict(self):
        return {
            "id": self.pk,
            "assessment_id": self.assessment_id,
            "framework_control_id": self.framework_control_id,
            "framework_control_code": getattr(self.framework_control, "code", "") if self.framework_control_id else "",
            "control_id": self.control_id,
            "control_name": getattr(self.control, "name", "") if self.control_id else "",
            "status": self.status,
            "status_label": ASSESSMENT_ITEM_LABELS.get(self.status, self.status),
            "evidence_note": self.evidence_note,
            "note": self.note,
            "score": float(self.score or 0),
            "weight": self.weight,
            "remediation_task_id": self.remediation_task_id,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


# ---------------------------------------------------------------------------
# 5. 证据
# ---------------------------------------------------------------------------


class Evidence(GovTimeStamped):
    """证据元数据：对象类型 + 对象 ID + 哈希指纹 + 有效期。

    只存元数据不存文件：file 类型也只是一个外部引用（例如 files 应用的
    file_id 或内部文档编号），这样证据可以被多方校验而不产生副本。

    hash_value 采用 `算法:摘要` 形式（如 `sha256:ab12…`），服务层据此
    选择对应 hashlib 构造器做一致性校验；未知算法直接报错而不是静默通过。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_evidences", verbose_name="所有者")
    target_kind = models.CharField("对象类型", max_length=20, default="control", db_index=True)
    target_id = models.IntegerField("对象 ID", default=0)
    name = models.CharField("证据名称", max_length=200)
    kind = models.CharField("证据类型", max_length=20, default="link")
    reference = models.CharField("引用地址", max_length=500, blank=True, default="")
    hash_value = models.CharField("哈希值", max_length=160, blank=True, default="")
    collected_by_name = models.CharField("采集人", max_length=80, blank=True, default="")
    collected_at = models.DateTimeField("采集时间", null=True, blank=True)
    expires_on = models.DateField("有效期至", null=True, blank=True, db_index=True)
    last_checked_at = models.DateTimeField("最近校验时间", null=True, blank=True)
    last_check_ok = models.BooleanField("最近校验通过", null=True, blank=True)
    last_check_note = models.CharField("校验说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "合规证据"
        verbose_name_plural = "合规证据"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_kind", "target_id"], name="gov_evidence_target_idx"),
            models.Index(fields=["owner", "expires_on"], name="gov_evidence_expire_idx"),
        ]

    def __str__(self):
        return f"{self.target_kind}:{self.target_id} {self.name}"

    def to_dict(self):
        today = timezone.localdate()
        return {
            "id": self.pk,
            "target_kind": self.target_kind,
            "target_kind_label": EVIDENCE_TARGET_LABELS.get(self.target_kind, self.target_kind),
            "target_id": self.target_id,
            "name": self.name,
            "kind": self.kind,
            "kind_label": EVIDENCE_KIND_LABELS.get(self.kind, self.kind),
            "reference": self.reference,
            "hash_value": self.hash_value,
            "collected_by_name": self.collected_by_name,
            "collected_at": _iso(self.collected_at),
            "expires_on": _iso(self.expires_on),
            "expired": bool(self.expires_on and self.expires_on < today),
            "last_checked_at": _iso(self.last_checked_at),
            "last_check_ok": self.last_check_ok,
            "last_check_note": self.last_check_note,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


# ---------------------------------------------------------------------------
# 6. 风险与处置
# ---------------------------------------------------------------------------


class RiskMatrixBand(GovTimeStamped):
    """风险矩阵分值 → 等级的分档配置。

    阈值放表里而不是写死常量：不同企业把 12 分叫「高」还是「中」并无统一
    标准，写死会让合规团队无法对齐自家矩阵。默认分档由服务层幂等播种。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_risk_bands", verbose_name="所有者")
    label = models.CharField("分档名称", max_length=40)
    min_score = models.PositiveSmallIntegerField("最低分", default=0)
    max_score = models.PositiveSmallIntegerField("最高分", default=25)
    level = models.CharField("等级", max_length=20, default="low")
    color = models.CharField("颜色", max_length=20, blank=True, default="")
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "风险分档"
        verbose_name_plural = "风险分档"
        ordering = ["min_score"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "label"], name="gov_risk_band_uniq"),
        ]

    def __str__(self):
        return f"{self.label}[{self.min_score}-{self.max_score}]"

    def to_dict(self):
        return {
            "id": self.pk,
            "label": self.label,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "level": self.level,
            "level_label": RISK_LEVEL_LABELS.get(self.level, self.level),
            "color": self.color,
            "enabled": self.enabled,
        }


class Risk(GovTimeStamped):
    """风险条目：可能性 × 影响 = 固有风险；乘控制有效性系数得剩余风险。

    inherent_score / residual_score / level 都是冗余字段：
    列表需要按分值与等级筛选排序，实时连乘会让分页查询退化；
    服务层 rescore() 是唯一写入口，保证「分值与等级」永远同步。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_risks", verbose_name="所有者")
    code = models.CharField("风险编号", max_length=40)
    name = models.CharField("风险名称", max_length=200)
    category = models.CharField("类别", max_length=60, default="通用", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    likelihood = models.PositiveSmallIntegerField("可能性", default=3)
    impact = models.PositiveSmallIntegerField("影响", default=3)
    inherent_score = models.PositiveSmallIntegerField("固有风险分", default=9, db_index=True)
    residual_score = models.PositiveSmallIntegerField("剩余风险分", default=9, db_index=True)
    level = models.CharField("等级", max_length=20, default="medium", db_index=True)
    status = models.CharField("状态", max_length=20, default="identified", db_index=True)
    owner_name = models.CharField("风险负责人", max_length=80, blank=True, default="")
    review_on = models.DateField("复核日期", null=True, blank=True)
    effectiveness = models.PositiveSmallIntegerField("控制有效性%", default=0)
    treatment_plan = models.TextField("处置概述", blank=True, default="")

    class Meta:
        verbose_name = "风险"
        verbose_name_plural = "风险"
        ordering = ["-residual_score", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="gov_risk_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="gov_risk_owner_status_idx"),
            models.Index(fields=["owner", "level"], name="gov_risk_owner_level_idx"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def to_dict(self):
        return {
            "id": self.pk,
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "likelihood": self.likelihood,
            "impact": self.impact,
            "inherent_score": self.inherent_score,
            "residual_score": self.residual_score,
            "level": self.level,
            "level_label": RISK_LEVEL_LABELS.get(self.level, self.level),
            "status": self.status,
            "status_label": RISK_STATUS_LABELS.get(self.status, self.status),
            "owner_name": self.owner_name,
            "review_on": _iso(self.review_on),
            "effectiveness": self.effectiveness,
            "treatment_plan": self.treatment_plan,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class RiskTreatment(GovTimeStamped):
    """风险处置：降低 / 转移 / 规避 / 接受。

    「接受」也需要建一条记录——审计要看到「为什么接受」而不是空着，
    因此 strategy=accept 时服务层强制要求 action 写明接受理由。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_risk_treatments", verbose_name="所有者")
    risk = models.ForeignKey(Risk, on_delete=models.CASCADE,
                             related_name="treatments", verbose_name="风险")
    strategy = models.CharField("处置策略", max_length=20, default="mitigate")
    action = models.TextField("处置行动", blank=True, default="")
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    due_on = models.DateField("截止日期", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="planned", db_index=True)
    completed_on = models.DateField("完成日期", null=True, blank=True)

    class Meta:
        verbose_name = "风险处置"
        verbose_name_plural = "风险处置"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["risk", "status"], name="gov_treat_risk_status_idx"),
            models.Index(fields=["owner", "due_on"], name="gov_treat_due_idx"),
        ]

    def __str__(self):
        return f"{self.risk_id}:{self.strategy}"

    def to_dict(self):
        return {
            "id": self.pk,
            "risk_id": self.risk_id,
            "risk_name": getattr(self.risk, "name", "") if self.risk_id else "",
            "strategy": self.strategy,
            "strategy_label": TREATMENT_STRATEGY_LABELS.get(self.strategy, self.strategy),
            "action": self.action,
            "owner_name": self.owner_name,
            "due_on": _iso(self.due_on),
            "status": self.status,
            "status_label": TREATMENT_STATUS_LABELS.get(self.status, self.status),
            "completed_on": _iso(self.completed_on),
            "overdue": bool(self.due_on and self.status not in ("done", "cancelled")
                            and self.due_on < timezone.localdate()),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


# ---------------------------------------------------------------------------
# 7. 数据资产、处理活动、保留与同意
# ---------------------------------------------------------------------------


class DataAsset(GovTimeStamped):
    """数据资产台账：类型、分级、存储位置、保留天数、是否含个人信息。

    retention_days 为 0 表示「不设自动到期」；保留期扫描以资产登记时间
    （created_at）为起点而非最后修改时间——数据保留义务从采集开始算。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_data_assets", verbose_name="所有者")
    name = models.CharField("资产名称", max_length=200)
    kind = models.CharField("数据类型", max_length=20, default="operational", db_index=True)
    classification = models.CharField("分级", max_length=20, default="internal", db_index=True)
    owner_name = models.CharField("数据负责人", max_length=80, blank=True, default="")
    storage_location = models.CharField("存储位置", max_length=200, blank=True, default="")
    retention_days = models.PositiveIntegerField("保留天数", default=0)
    contains_pii = models.BooleanField("含个人信息", default=False)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    description = models.TextField("描述", blank=True, default="")

    class Meta:
        verbose_name = "数据资产"
        verbose_name_plural = "数据资产"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "classification"], name="gov_asset_class_idx"),
            models.Index(fields=["owner", "kind"], name="gov_asset_kind_idx"),
        ]

    def __str__(self):
        return self.name

    def retention_due_on(self, base=None):
        """保留到期日：登记时间 + 保留天数；未设天数返回 None。"""
        if not self.retention_days:
            return None
        from datetime import timedelta

        base = base or self.created_at
        return (base.date() if hasattr(base, "date") else base) + timedelta(days=self.retention_days)

    def to_dict(self):
        due = self.retention_due_on()
        return {
            "id": self.pk,
            "name": self.name,
            "kind": self.kind,
            "kind_label": DATA_ASSET_KIND_LABELS.get(self.kind, self.kind),
            "classification": self.classification,
            "classification_label": DATA_CLASSIFICATION_LABELS.get(self.classification, self.classification),
            "owner_name": self.owner_name,
            "storage_location": self.storage_location,
            "retention_days": self.retention_days,
            "retention_due_on": _iso(due),
            "contains_pii": self.contains_pii,
            "status": self.status,
            "status_label": DATA_ASSET_STATUS_LABELS.get(self.status, self.status),
            "description": self.description,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ProcessingActivity(GovTimeStamped):
    """数据处理活动（ROPA 记录）：目的、法律依据、数据类别、跨境、DPIA。

    legal_basis 用自由文本而不是枚举：GDPR 第 6 条的六种依据在各国落地
    表述差异很大，枚举会逼迫合规人员做不准确的映射。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_processing_activities", verbose_name="所有者")
    name = models.CharField("活动名称", max_length=200)
    purpose = models.TextField("处理目的", blank=True, default="")
    legal_basis = models.CharField("法律依据", max_length=120, blank=True, default="")
    data_categories = models.JSONField("数据类别", default=list, blank=True)
    subject_categories = models.JSONField("主体类别", default=list, blank=True)
    recipients = models.TextField("接收方", blank=True, default="")
    cross_border = models.BooleanField("跨境传输", default=False)
    retention_period = models.CharField("保留期", max_length=80, blank=True, default="")
    dpia_done = models.BooleanField("DPIA 已完成", default=False)
    dpia_on = models.DateField("DPIA 完成日期", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)
    risks = models.ManyToManyField(Risk, blank=True, related_name="processing_activities",
                                   verbose_name="关联风险")

    class Meta:
        verbose_name = "处理活动"
        verbose_name_plural = "处理活动"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="gov_ropa_owner_status_idx"),
        ]

    def __str__(self):
        return self.name

    def to_dict(self):
        return {
            "id": self.pk,
            "name": self.name,
            "purpose": self.purpose,
            "legal_basis": self.legal_basis,
            "data_categories": self.data_categories or [],
            "subject_categories": self.subject_categories or [],
            "recipients": self.recipients,
            "cross_border": self.cross_border,
            "retention_period": self.retention_period,
            "dpia_done": self.dpia_done,
            "dpia_on": _iso(self.dpia_on),
            "status": self.status,
            "status_label": PROCESSING_STATUS_LABELS.get(self.status, self.status),
            "risk_ids": list(self.risks.values_list("id", flat=True)) if self.pk else [],
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class RetentionRule(GovTimeStamped):
    """保留规则：按资源类型给出保留天数与到期动作。

    同一用户同一资源类型只允许一条启用规则（唯一约束），
    否则扫描会出现「同一资产命中两条冲突规则」的歧义。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_retention_rules", verbose_name="所有者")
    resource_kind = models.CharField("资源类型", max_length=20, default="data_asset")
    retention_days = models.PositiveIntegerField("保留天数", default=365)
    due_action = models.CharField("到期动作", max_length=20, default="archive")
    condition = models.CharField("适用条件", max_length=200, blank=True, default="")
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "保留规则"
        verbose_name_plural = "保留规则"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "resource_kind"],
                                    name="gov_retention_rule_uniq"),
        ]

    def __str__(self):
        return f"{self.resource_kind}:{self.retention_days}d"

    def to_dict(self):
        return {
            "id": self.pk,
            "resource_kind": self.resource_kind,
            "resource_kind_label": RETENTION_KIND_LABELS.get(self.resource_kind, self.resource_kind),
            "retention_days": self.retention_days,
            "due_action": self.due_action,
            "due_action_label": RETENTION_ACTION_LABELS.get(self.due_action, self.due_action),
            "condition": self.condition,
            "enabled": self.enabled,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class RetentionAction(GovTimeStamped):
    """保留期到期台账（扫描产物 + 执行记录）。

    幂等性靠唯一约束（owner + 资源类型 + 资源 ID + 动作）：
    反复扫描只会更新已有行的 due_on，不会堆出重复待办；
    执行也只允许从 planned 迁移一次，重复调用返回同一结果。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_retention_actions", verbose_name="所有者")
    rule = models.ForeignKey(RetentionRule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="actions", verbose_name="规则")
    resource_kind = models.CharField("资源类型", max_length=20, default="data_asset")
    resource_id = models.IntegerField("资源 ID", default=0)
    resource_name = models.CharField("资源名称", max_length=200, blank=True, default="")
    action = models.CharField("动作", max_length=20, default="archive")
    status = models.CharField("状态", max_length=20, default="planned", db_index=True)
    due_on = models.DateField("到期日", null=True, blank=True)
    executed_at = models.DateTimeField("执行时间", null=True, blank=True)
    note = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "保留期动作"
        verbose_name_plural = "保留期动作"
        ordering = ["due_on", "id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "resource_kind", "resource_id", "action"],
                                    name="gov_retention_action_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="gov_ret_action_status_idx"),
        ]

    def __str__(self):
        return f"{self.resource_kind}:{self.resource_id} {self.action}"

    def to_dict(self):
        return {
            "id": self.pk,
            "rule_id": self.rule_id,
            "resource_kind": self.resource_kind,
            "resource_kind_label": RETENTION_KIND_LABELS.get(self.resource_kind, self.resource_kind),
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "action": self.action,
            "action_label": RETENTION_ACTION_LABELS.get(self.action, self.action),
            "status": self.status,
            "status_label": RETENTION_RUN_LABELS.get(self.status, self.status),
            "due_on": _iso(self.due_on),
            "executed_at": _iso(self.executed_at),
            "note": self.note,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ConsentRecord(GovTimeStamped):
    """同意记录：数据主体 + 目的 + 状态 + 授予/撤回时间 + 证据引用。

    同意是「可举证」的事实，所以撤回时间、来源、证据引用都必填式保存；
    有效性由服务层按状态 + 目的 + 时间（expires_on）三项联合判定。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_consents", verbose_name="所有者")
    data_subject = models.CharField("数据主体", max_length=120, db_index=True)
    purpose = models.CharField("目的", max_length=200)
    status = models.CharField("状态", max_length=20, default="granted", db_index=True)
    granted_at = models.DateTimeField("授予时间", null=True, blank=True)
    withdrawn_at = models.DateTimeField("撤回时间", null=True, blank=True)
    expires_on = models.DateField("有效期至", null=True, blank=True)
    source = models.CharField("来源", max_length=80, blank=True, default="")
    evidence_ref = models.CharField("证据引用", max_length=200, blank=True, default="")
    note = models.TextField("备注", blank=True, default="")

    class Meta:
        verbose_name = "同意记录"
        verbose_name_plural = "同意记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["data_subject", "purpose"], name="gov_consent_subject_idx"),
            models.Index(fields=["owner", "status"], name="gov_consent_status_idx"),
        ]

    def __str__(self):
        return f"{self.data_subject}:{self.purpose}"

    def to_dict(self):
        today = timezone.localdate()
        return {
            "id": self.pk,
            "data_subject": self.data_subject,
            "purpose": self.purpose,
            "status": self.status,
            "status_label": CONSENT_STATUS_LABELS.get(self.status, self.status),
            "granted_at": _iso(self.granted_at),
            "withdrawn_at": _iso(self.withdrawn_at),
            "expires_on": _iso(self.expires_on),
            "expired_by_date": bool(self.expires_on and self.expires_on < today),
            "source": self.source,
            "evidence_ref": self.evidence_ref,
            "note": self.note,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


# ---------------------------------------------------------------------------
# 8. 审计、发现与整改
# ---------------------------------------------------------------------------


class Audit(GovTimeStamped):
    """审计活动：内部 / 外部 / 突击，含范围、起止、审计人与结论。"""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_audits", verbose_name="所有者")
    name = models.CharField("审计名称", max_length=200)
    kind = models.CharField("类型", max_length=20, default="internal", db_index=True)
    scope = models.CharField("审计范围", max_length=200, blank=True, default="")
    start_on = models.DateField("开始日期", null=True, blank=True)
    end_on = models.DateField("结束日期", null=True, blank=True)
    status = models.CharField("状态", max_length=20, default="planned", db_index=True)
    auditor_name = models.CharField("审计人", max_length=80, blank=True, default="")
    conclusion = models.TextField("审计结论", blank=True, default="")

    class Meta:
        verbose_name = "审计"
        verbose_name_plural = "审计"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "kind"], name="gov_audit_kind_idx"),
            models.Index(fields=["owner", "status"], name="gov_audit_status_idx"),
        ]

    def __str__(self):
        return self.name

    def to_dict(self):
        return {
            "id": self.pk,
            "name": self.name,
            "kind": self.kind,
            "kind_label": AUDIT_KIND_LABELS.get(self.kind, self.kind),
            "scope": self.scope,
            "start_on": _iso(self.start_on),
            "end_on": _iso(self.end_on),
            "status": self.status,
            "status_label": AUDIT_STATUS_LABELS.get(self.status, self.status),
            "auditor_name": self.auditor_name,
            "conclusion": self.conclusion,
            "finding_count": self.findings.count() if self.pk else 0,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class Finding(GovTimeStamped):
    """审计发现：严重度 + 整改负责人 + 截止日 + 状态。

    status 的 verified 只能由整改验证接口推进，避免「自己说自己改好了」；
    这是审计闭环的关键控制点。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_findings", verbose_name="所有者")
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE,
                              related_name="findings", verbose_name="审计")
    title = models.CharField("发现标题", max_length=200)
    severity = models.CharField("严重度", max_length=20, default="medium", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    remediation_owner = models.CharField("整改负责人", max_length=80, blank=True, default="")
    due_on = models.DateField("整改截止日", null=True, blank=True, db_index=True)
    status = models.CharField("状态", max_length=20, default="open", db_index=True)
    closed_on = models.DateField("关闭日期", null=True, blank=True)

    class Meta:
        verbose_name = "审计发现"
        verbose_name_plural = "审计发现"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["audit", "severity"], name="gov_finding_severity_idx"),
            models.Index(fields=["owner", "status"], name="gov_finding_status_idx"),
        ]

    def __str__(self):
        return self.title

    def is_overdue(self, today=None):
        """逾期判定：未解决且截止日已过。"""
        today = today or timezone.localdate()
        if self.status in ("resolved", "verified"):
            return False
        return bool(self.due_on and self.due_on < today)

    def to_dict(self):
        return {
            "id": self.pk,
            "audit_id": self.audit_id,
            "audit_name": getattr(self.audit, "name", "") if self.audit_id else "",
            "title": self.title,
            "severity": self.severity,
            "severity_label": FINDING_SEVERITY_LABELS.get(self.severity, self.severity),
            "description": self.description,
            "remediation_owner": self.remediation_owner,
            "due_on": _iso(self.due_on),
            "status": self.status,
            "status_label": FINDING_STATUS_LABELS.get(self.status, self.status),
            "overdue": self.is_overdue(),
            "closed_on": _iso(self.closed_on),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class RemediationTask(GovTimeStamped):
    """整改任务：措施 + 负责人 + 截止 + 验证人 + 验证时间。

    验证人与负责人分离是审计要求；verifier_name/verified_at 为空即「未验证」，
    「验证」接口只允许填一次（重复调用返回已有结果，保持幂等）。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="gov_remediations", verbose_name="所有者")
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE,
                                related_name="remediations", verbose_name="发现")
    measure = models.TextField("整改措施", blank=True, default="")
    owner_name = models.CharField("负责人", max_length=80, blank=True, default="")
    due_on = models.DateField("截止日期", null=True, blank=True, db_index=True)
    status = models.CharField("状态", max_length=20, default="open", db_index=True)
    completed_on = models.DateField("完成日期", null=True, blank=True)
    verifier_name = models.CharField("验证人", max_length=80, blank=True, default="")
    verified_at = models.DateTimeField("验证时间", null=True, blank=True)

    class Meta:
        verbose_name = "整改任务"
        verbose_name_plural = "整改任务"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["finding", "status"], name="gov_remedy_finding_idx"),
            models.Index(fields=["owner", "due_on"], name="gov_remedy_due_idx"),
        ]

    def __str__(self):
        return f"remediation#{self.pk}"

    def is_overdue(self, today=None):
        today = today or timezone.localdate()
        if self.status in ("done", "verified"):
            return False
        return bool(self.due_on and self.due_on < today)

    def to_dict(self):
        return {
            "id": self.pk,
            "finding_id": self.finding_id,
            "finding_title": getattr(self.finding, "title", "") if self.finding_id else "",
            "measure": self.measure,
            "owner_name": self.owner_name,
            "due_on": _iso(self.due_on),
            "status": self.status,
            "status_label": REMEDIATION_STATUS_LABELS.get(self.status, self.status),
            "completed_on": _iso(self.completed_on),
            "verifier_name": self.verifier_name,
            "verified_at": _iso(self.verified_at),
            "overdue": self.is_overdue(),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


def _iso(value):
    """日期/时间统一转 ISO 字符串；空值给 None（前端判断更简单）。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
