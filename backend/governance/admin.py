# -*- coding: utf-8 -*-
"""合规治理后台：挂在 Django admin 上的运维入口。

治理数据的日常操作走业务接口（状态机、权限、审计日志都在接口层），
admin 只承担两类场景：
1. 线上排障：按编号/标题快速检索一条记录，看原始字段与时间戳；
2. 数据修复：批量改状态、导出异常数据。因此所有时间戳字段与 owner
   都设为只读——owner 决定行级权限，误改会让数据「易主」且难以察觉。

列表页只展示「一眼能判断对错」的字段，长文本（正文、措施）留给详情页，
避免 admin 列表在宽屏下横向滚动到无法使用。
"""
from django.contrib import admin

from governance.models import (
    Assessment,
    AssessmentItem,
    Audit,
    ConsentRecord,
    Control,
    ControlMapping,
    ControlTest,
    ControlTestRun,
    DataAsset,
    Evidence,
    Finding,
    Framework,
    FrameworkControl,
    Policy,
    PolicyVersion,
    ProcessingActivity,
    RemediationTask,
    RetentionAction,
    RetentionRule,
    Risk,
    RiskMatrixBand,
    RiskTreatment,
)

READONLY = ("created_at", "updated_at")


class GovAdmin(admin.ModelAdmin):
    """治理模型的公共配置：owner 与时间戳只读，统一按更新时间倒序。"""

    readonly_fields = READONLY
    list_per_page = 50

    def get_queryset(self, request):
        # admin 默认不套业务权限：这里保留全量（运维视角），
        # 但把 owner 一并 select 出来，避免列表页 N+1。
        return super().get_queryset(request).select_related("owner")


@admin.register(Framework)
class FrameworkAdmin(GovAdmin):
    """框架：按类型/状态筛选，按名称检索。"""

    list_display = ("id", "name", "version", "kind", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("name", "version", "description")
    readonly_fields = READONLY + ("owner",)


@admin.register(FrameworkControl)
class FrameworkControlAdmin(GovAdmin):
    """框架条款：按框架与类别筛选，编号可检索。"""

    list_display = ("id", "framework", "code", "title", "category", "weight")
    list_filter = ("category",)
    search_fields = ("code", "title", "description")
    raw_id_fields = ("framework",)
    readonly_fields = READONLY + ("owner",)


@admin.register(ControlMapping)
class ControlMappingAdmin(GovAdmin):
    """控制映射：条款 ↔ 实施，强度异常（<60）需要人工复核。"""

    list_display = ("id", "framework_control", "control", "strength", "created_at")
    list_filter = ("strength",)
    search_fields = ("note",)
    raw_id_fields = ("framework_control", "control")
    readonly_fields = READONLY + ("owner",)


@admin.register(Policy)
class PolicyAdmin(GovAdmin):
    """策略：状态与评审日期是运维最常看的两个字段。"""

    list_display = ("id", "code", "name", "kind", "status", "current_version", "next_review_on")
    list_filter = ("kind", "status")
    search_fields = ("code", "name", "description", "content")
    readonly_fields = READONLY + ("owner",)


@admin.register(PolicyVersion)
class PolicyVersionAdmin(GovAdmin):
    """策略版本快照：发布后不可变，admin 只读查阅。"""

    list_display = ("id", "policy", "version", "approver_name", "published_at", "created_at")
    list_filter = ("published_at",)
    search_fields = ("version", "change_note")
    raw_id_fields = ("policy",)
    readonly_fields = READONLY + ("owner",)


@admin.register(Control)
class ControlAdmin(GovAdmin):
    """内部控制：有效性、频率与最近测试时间决定差距结论。"""

    list_display = ("id", "code", "name", "category", "frequency", "automated",
                    "status", "effectiveness", "last_tested_at")
    list_filter = ("category", "frequency", "status", "automated")
    search_fields = ("code", "name", "description")
    readonly_fields = READONLY + ("owner",)


@admin.register(ControlTest)
class ControlTestAdmin(GovAdmin):
    """控制测试定义：步骤与通过标准。"""

    list_display = ("id", "control", "name", "method", "last_result", "last_run_at")
    list_filter = ("method", "last_result")
    search_fields = ("name", "pass_criteria")
    raw_id_fields = ("control",)
    readonly_fields = READONLY + ("owner",)


@admin.register(ControlTestRun)
class ControlTestRunAdmin(GovAdmin):
    """控制测试执行记录：只追加，不允许改历史结论。"""

    list_display = ("id", "test", "result", "duration_ms", "runner_name", "run_at")
    list_filter = ("result",)
    raw_id_fields = ("test",)
    readonly_fields = READONLY + ("owner",)


@admin.register(Assessment)
class AssessmentAdmin(GovAdmin):
    """合规评估：得分与状态并排，便于核对加权计算。"""

    list_display = ("id", "name", "framework", "status", "score", "start_on", "end_on", "lead_name")
    list_filter = ("status",)
    search_fields = ("name", "scope", "lead_name")
    raw_id_fields = ("framework",)
    readonly_fields = READONLY + ("owner",)


@admin.register(AssessmentItem)
class AssessmentItemAdmin(GovAdmin):
    """评估项：按状态筛选未通过项，是整改派单的入口。"""

    list_display = ("id", "assessment", "framework_control", "control", "status", "weight")
    list_filter = ("status",)
    search_fields = ("note", "evidence_note")
    raw_id_fields = ("assessment", "framework_control", "control", "remediation_task")
    readonly_fields = READONLY + ("owner",)


@admin.register(Evidence)
class EvidenceAdmin(GovAdmin):
    """证据：只看哈希与有效期，不存文件本体。"""

    list_display = ("id", "name", "target_kind", "target_id", "kind",
                    "last_check_ok", "expires_on")
    list_filter = ("target_kind", "kind", "last_check_ok")
    search_fields = ("name", "reference", "hash_value")
    readonly_fields = READONLY + ("owner",)


@admin.register(RiskMatrixBand)
class RiskMatrixBandAdmin(GovAdmin):
    """风险分档配置：改档位会改变全量风险的等级口径，操作需谨慎。"""

    list_display = ("id", "label", "level", "min_score", "max_score", "color")
    list_filter = ("level",)
    readonly_fields = READONLY + ("owner",)


@admin.register(Risk)
class RiskAdmin(GovAdmin):
    """风险：固有分/剩余分/等级三列并排，便于发现「分值没重算」的脏数据。"""

    list_display = ("id", "code", "name", "category", "inherent_score",
                    "residual_score", "level", "status", "effectiveness")
    list_filter = ("level", "status", "category")
    search_fields = ("code", "name", "description", "treatment_plan")
    readonly_fields = READONLY + ("owner",)


@admin.register(RiskTreatment)
class RiskTreatmentAdmin(GovAdmin):
    """风险处置：按策略与状态筛选，接受类必须写明理由。"""

    list_display = ("id", "risk", "strategy", "status", "owner_name", "due_on")
    list_filter = ("strategy", "status")
    search_fields = ("action",)
    raw_id_fields = ("risk",)
    readonly_fields = READONLY + ("owner",)


@admin.register(DataAsset)
class DataAssetAdmin(GovAdmin):
    """数据资产：分级与是否含个人信息是隐私统计的基础。"""

    list_display = ("id", "name", "kind", "classification", "contains_pii",
                    "retention_days", "status")
    list_filter = ("kind", "classification", "contains_pii", "status")
    search_fields = ("name", "storage_location", "description")
    readonly_fields = READONLY + ("owner",)


@admin.register(ProcessingActivity)
class ProcessingActivityAdmin(GovAdmin):
    """处理活动：DPIA 状态与跨境标记要在列表就能看到。"""

    list_display = ("id", "name", "legal_basis", "cross_border", "dpia_done", "status")
    list_filter = ("cross_border", "dpia_done", "status")
    search_fields = ("name", "purpose")
    readonly_fields = READONLY + ("owner",)


@admin.register(RetentionRule)
class RetentionRuleAdmin(GovAdmin):
    """保留规则：同资源类型只允许一条，重复配置在数据库层就会被拒绝。"""

    list_display = ("id", "resource_kind", "retention_days", "due_action", "enabled")
    list_filter = ("resource_kind", "due_action", "enabled")
    readonly_fields = READONLY + ("owner",)


@admin.register(RetentionAction)
class RetentionActionAdmin(GovAdmin):
    """保留期台账：扫描产物，重复扫描只更新到期日不新增行。"""

    list_display = ("id", "resource_kind", "resource_name", "action",
                    "status", "due_on", "executed_at")
    list_filter = ("resource_kind", "action", "status")
    search_fields = ("resource_name", "note")
    readonly_fields = READONLY + ("owner",)


@admin.register(ConsentRecord)
class ConsentRecordAdmin(GovAdmin):
    """同意记录：状态 + 有效期，撤回时间必须可查。"""

    list_display = ("id", "data_subject", "purpose", "status", "granted_at",
                    "withdrawn_at", "expires_on")
    list_filter = ("status",)
    search_fields = ("data_subject", "purpose", "source")
    readonly_fields = READONLY + ("owner",)


@admin.register(Audit)
class AuditAdmin(GovAdmin):
    """审计活动：按范围与状态筛选，起止日期用于统计周期。"""

    list_display = ("id", "name", "kind", "status", "auditor_name", "start_on", "end_on")
    list_filter = ("kind", "status")
    search_fields = ("name", "scope", "auditor_name")
    readonly_fields = READONLY + ("owner",)


@admin.register(Finding)
class FindingAdmin(GovAdmin):
    """审计发现：严重度与逾期是审计报告的核心指标。"""

    list_display = ("id", "audit", "title", "severity", "status",
                    "remediation_owner", "due_on", "closed_on")
    list_filter = ("severity", "status")
    search_fields = ("title", "description")
    raw_id_fields = ("audit",)
    readonly_fields = READONLY + ("owner",)


@admin.register(RemediationTask)
class RemediationTaskAdmin(GovAdmin):
    """整改任务：验证人/验证时间只读，防止绕过验证闭环。"""

    list_display = ("id", "finding", "owner_name", "status", "due_on",
                    "completed_on", "verifier_name", "verified_at")
    list_filter = ("status",)
    search_fields = ("measure", "owner_name", "verifier_name")
    raw_id_fields = ("finding",)
    readonly_fields = READONLY + ("owner",)
