# -*- coding: utf-8 -*-
"""合规治理 · 路由（148 个接口，含目录 1 个）。

分组（括号内为接口数）：
- catalog     目录                                                     (1)
- framework   框架 8 + 条款 6 + 控制映射 3 + 覆盖率/差距 2 + 模板 2      (21)
- policy      策略 9 + 版本/对比/回滚 3                                 (12)
- control     控制 6 + 测试 7 + 差距 1                                  (14)
- assessment  评估 7 + 评估项 7 + 得分/报告 2                           (16)
- evidence    证据 7                                                    (7)
- risk        风险 7 + 处置 5                                           (12)
- privacy     数据资产 6 + 处理活动 9                                   (15)
- retention   保留规则 5 + 扫描/到期/执行/台账 4 + 同意 7              (16)
- audit       审计 7 + 发现 6 + 整改 5                                  (18)
- stats       看板与统计 6 + 合规日历 6                                 (12)
- template    条款库列表/详情 2                                         (2)
- export      导出目录 + 5 个数据集                                     (6)

所有路径挂在 /api/governance/ 下；列表统一返回 {items,count,page,page_size}。
目录接口额外返回 endpoints（从 urlpatterns 反推的 path/methods 明细），
前端因此不必硬编码接口清单。
"""
import logging
import traceback

from django.urls import path

from devtools.common import endpoint_index
from governance import (
    views_assessment,
    views_audit,
    views_calendar,
    views_catalog,
    views_control,
    views_evidence,
    views_export,
    views_policy,
    views_privacy,
    views_retention,
    views_risk,
    views_stats,
    views_templates,
)

logger = logging.getLogger("governance")


def _catalog(request):
    """目录 + 接口明细：endpoints 放在 data 层，与其它应用目录结构一致。"""
    response = views_catalog.catalog(request)
    try:
        inner = response.data.get("data")
        if isinstance(inner, dict):
            inner["endpoints"] = endpoint_index(urlpatterns, exclude=("",))
            inner["endpoint_count"] = len(inner["endpoints"])
    except Exception:  # noqa: BLE001 —— 目录增强失败不影响主响应
        logger.warning("governance catalog endpoints 导出失败:\n%s", traceback.format_exc())
    return response


urlpatterns = [
    # ---- 目录（1）----
    path("", _catalog, name="governance-catalog"),

    # ---- 框架（8）----
    path("frameworks/", views_catalog.framework_list),
    path("frameworks/create/", views_catalog.framework_create),
    path("frameworks/<int:pk>/", views_catalog.framework_detail),
    path("frameworks/<int:pk>/update/", views_catalog.framework_update),
    path("frameworks/<int:pk>/delete/", views_catalog.framework_delete),
    path("frameworks/<int:pk>/publish/", views_catalog.framework_publish),
    path("frameworks/<int:pk>/controls/", views_catalog.framework_controls),
    path("frameworks/<int:pk>/coverage/", views_catalog.framework_coverage),
    path("frameworks/<int:pk>/gaps/", views_catalog.framework_gaps),

    # ---- 框架条款（6）----
    path("framework-controls/", views_catalog.framework_control_list),
    path("framework-controls/create/", views_catalog.framework_control_create),
    path("framework-controls/<int:pk>/", views_catalog.framework_control_detail),
    path("framework-controls/<int:pk>/update/", views_catalog.framework_control_update),
    path("framework-controls/<int:pk>/delete/", views_catalog.framework_control_delete),

    # ---- 控制映射（3）----
    path("control-mappings/", views_catalog.mapping_list),
    path("control-mappings/link/", views_catalog.mapping_link),
    path("control-mappings/unlink/", views_catalog.mapping_unlink),

    # ---- 策略（12）----
    path("policies/", views_policy.policy_list),
    path("policies/create/", views_policy.policy_create),
    path("policies/<int:pk>/", views_policy.policy_detail),
    path("policies/<int:pk>/update/", views_policy.policy_update),
    path("policies/<int:pk>/delete/", views_policy.policy_delete),
    path("policies/<int:pk>/submit-review/", views_policy.policy_submit_review),
    path("policies/<int:pk>/approve/", views_policy.policy_approve),
    path("policies/<int:pk>/publish/", views_policy.policy_publish),
    path("policies/<int:pk>/retire/", views_policy.policy_retire),
    path("policies/<int:pk>/versions/", views_policy.policy_versions),
    path("policies/<int:pk>/versions/compare/", views_policy.policy_version_compare),
    path("policies/<int:pk>/rollback/", views_policy.policy_rollback),

    # ---- 控制（14）----
    path("controls/", views_control.control_list),
    path("controls/create/", views_control.control_create),
    path("controls/gaps/", views_control.control_gaps),
    path("controls/<int:pk>/", views_control.control_detail),
    path("controls/<int:pk>/update/", views_control.control_update),
    path("controls/<int:pk>/delete/", views_control.control_delete),
    path("controls/<int:pk>/toggle/", views_control.control_toggle),
    path("control-tests/", views_control.control_test_list),
    path("control-tests/create/", views_control.control_test_create),
    path("control-tests/<int:pk>/", views_control.control_test_detail),
    path("control-tests/<int:pk>/update/", views_control.control_test_update),
    path("control-tests/<int:pk>/delete/", views_control.control_test_delete),
    path("control-tests/<int:pk>/run/", views_control.control_test_run),
    path("control-tests/<int:pk>/history/", views_control.control_test_history),

    # ---- 评估（16）----
    path("assessments/", views_assessment.assessment_list),
    path("assessments/create/", views_assessment.assessment_create),
    path("assessments/<int:pk>/", views_assessment.assessment_detail),
    path("assessments/<int:pk>/update/", views_assessment.assessment_update),
    path("assessments/<int:pk>/delete/", views_assessment.assessment_delete),
    path("assessments/<int:pk>/start/", views_assessment.assessment_start),
    path("assessments/<int:pk>/complete/", views_assessment.assessment_complete),
    path("assessments/<int:pk>/items/", views_assessment.assessment_items),
    path("assessments/items/create/", views_assessment.assessment_item_create),
    path("assessments/items/bulk/", views_assessment.assessment_items_bulk),
    path("assessments/<int:pk>/score/", views_assessment.assessment_score_view),
    path("assessments/<int:pk>/report/", views_assessment.assessment_report),
    path("assessment-items/<int:pk>/", views_assessment.assessment_item_detail),
    path("assessment-items/<int:pk>/update/", views_assessment.assessment_item_update),
    path("assessment-items/<int:pk>/delete/", views_assessment.assessment_item_delete),

    # ---- 证据（7）----
    path("evidences/", views_evidence.evidence_list),
    path("evidences/create/", views_evidence.evidence_create),
    path("evidences/expired/", views_evidence.evidence_expired),
    path("evidences/<int:pk>/", views_evidence.evidence_detail),
    path("evidences/<int:pk>/update/", views_evidence.evidence_update),
    path("evidences/<int:pk>/delete/", views_evidence.evidence_delete),
    path("evidences/<int:pk>/verify/", views_evidence.evidence_verify),

    # ---- 风险（12）----
    path("risks/", views_risk.risk_list),
    path("risks/create/", views_risk.risk_create),
    path("risks/matrix/", views_risk.risk_matrix),
    path("risks/<int:pk>/", views_risk.risk_detail),
    path("risks/<int:pk>/update/", views_risk.risk_update),
    path("risks/<int:pk>/delete/", views_risk.risk_delete),
    path("risks/<int:pk>/rescore/", views_risk.risk_rescore),
    path("risks/<int:pk>/treatments/", views_risk.risk_treatments),
    path("risks/treatments/create/", views_risk.risk_treatment_create),
    path("risk-treatments/<int:pk>/", views_risk.risk_treatment_detail),
    path("risk-treatments/<int:pk>/update/", views_risk.risk_treatment_update),
    path("risk-treatments/<int:pk>/complete/", views_risk.risk_treatment_complete),

    # ---- 数据资产（6）----
    path("data-assets/", views_privacy.data_asset_list),
    path("data-assets/create/", views_privacy.data_asset_create),
    path("data-assets/classification/", views_privacy.data_asset_classification),
    path("data-assets/<int:pk>/", views_privacy.data_asset_detail),
    path("data-assets/<int:pk>/update/", views_privacy.data_asset_update),
    path("data-assets/<int:pk>/delete/", views_privacy.data_asset_delete),

    # ---- 处理活动（9）----
    path("processing-activities/", views_privacy.processing_list),
    path("processing-activities/create/", views_privacy.processing_create),
    path("processing-activities/<int:pk>/", views_privacy.processing_detail),
    path("processing-activities/<int:pk>/update/", views_privacy.processing_update),
    path("processing-activities/<int:pk>/delete/", views_privacy.processing_delete),
    path("processing-activities/<int:pk>/dpia/", views_privacy.processing_dpia),
    path("processing-activities/<int:pk>/risks/", views_privacy.processing_risks),
    path("processing-activities/<int:pk>/risks/link/", views_privacy.processing_risk_link),
    path("processing-activities/<int:pk>/risks/unlink/", views_privacy.processing_risk_unlink),

    # ---- 保留规则与动作（9）----
    path("retention-rules/", views_retention.retention_rule_list),
    path("retention-rules/create/", views_retention.retention_rule_create),
    path("retention-rules/<int:pk>/", views_retention.retention_rule_detail),
    path("retention-rules/<int:pk>/update/", views_retention.retention_rule_update),
    path("retention-rules/<int:pk>/delete/", views_retention.retention_rule_delete),
    path("retention/scan/", views_retention.retention_scan_view),
    path("retention/due/", views_retention.retention_due_view),
    path("retention/execute/", views_retention.retention_execute_view),
    path("retention/actions/", views_retention.retention_action_list),

    # ---- 同意（7）----
    path("consents/", views_retention.consent_list),
    path("consents/create/", views_retention.consent_create),
    path("consents/summary/", views_retention.consent_summary_view),
    path("consents/<int:pk>/", views_retention.consent_detail),
    path("consents/<int:pk>/update/", views_retention.consent_update),
    path("consents/<int:pk>/withdraw/", views_retention.consent_withdraw),
    path("consents/<int:pk>/validity/", views_retention.consent_validity_view),

    # ---- 审计（7）----
    path("audits/", views_audit.audit_list),
    path("audits/create/", views_audit.audit_create),
    path("audits/<int:pk>/", views_audit.audit_detail),
    path("audits/<int:pk>/update/", views_audit.audit_update),
    path("audits/<int:pk>/delete/", views_audit.audit_delete),
    path("audits/<int:pk>/findings/", views_audit.audit_findings),
    path("audits/findings/create/", views_audit.audit_finding_create),

    # ---- 发现（6）----
    path("findings/", views_audit.finding_list),
    path("findings/<int:pk>/", views_audit.finding_detail),
    path("findings/<int:pk>/update/", views_audit.finding_update),
    path("findings/<int:pk>/delete/", views_audit.finding_delete),
    path("findings/<int:pk>/remediations/", views_audit.finding_remediations),
    path("findings/remediations/create/", views_audit.finding_remediation_create),

    # ---- 整改（5）----
    path("remediations/", views_audit.remediation_list),
    path("remediations/<int:pk>/", views_audit.remediation_detail),
    path("remediations/<int:pk>/update/", views_audit.remediation_update),
    path("remediations/<int:pk>/verify/", views_audit.remediation_verify),

    # ---- 统计（6）----
    path("stats/dashboard/", views_stats.stats_dashboard),
    path("stats/framework-coverage/", views_stats.stats_framework_coverage),
    path("stats/risk-distribution/", views_stats.stats_risk_distribution),
    path("stats/overdue-remediations/", views_stats.stats_overdue_remediations),
    path("stats/review-reminders/", views_stats.stats_review_reminders),
    path("stats/finding-trend/", views_stats.stats_finding_trend),

    # ---- 条款库模板（4）----
    path("templates/", views_templates.template_list),
    path("templates/<str:kind>/", views_templates.template_detail),
    path("frameworks/from-template/", views_templates.framework_from_template),
    path("frameworks/<int:pk>/apply-template/", views_templates.framework_apply_template),

    # ---- 合规日历（6）----
    path("stats/calendar/", views_calendar.calendar_events),
    path("stats/calendar/ics/", views_calendar.calendar_ics),
    path("stats/calendar/sources/", views_calendar.calendar_sources),
    path("stats/calendar/summary/", views_calendar.calendar_summary),
    path("stats/control-plan/", views_calendar.control_test_plan),
    path("stats/workload/", views_calendar.workload),

    # ---- 导出（6）----
    path("exports/", views_export.export_catalog),
    path("exports/risks/", views_export.export_risks),
    path("exports/findings/", views_export.export_findings),
    path("exports/controls/", views_export.export_controls),
    path("exports/assessment-items/", views_export.export_assessment_items),
    path("exports/retention-actions/", views_export.export_retention_actions),
]
