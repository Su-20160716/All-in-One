# -*- coding: utf-8 -*-
"""contracts 路由：合同全生命周期，全部挂在 /api/contracts/ 下。

分组（与视图模块一一对应）：
- catalog   目录 / 元信息 / 规模        3
- template  模板与条款库               22
- contract  合同主档与状态机           38
- execution 履约 / 里程碑 / 变更 / 审批 23
- finance   付款 / 续约 / 风险 / 提醒   19
- stats     组合统计                    7

集合查询与创建拆成两条路径（/xxx/ 与 /xxx/create/），详情与动作同理，
这是平台既有约定：前端按「资源 + 动作」调用，不需要额外的 REST 语义层。
"""
from django.urls import path

from devtools.common import endpoint, endpoint_index
from contracts import views_catalog as cat
from contracts import views_contract as c
from contracts import views_execution as ex
from contracts import views_finance as f
from contracts import views_stats as st
from contracts import views_template as t


@endpoint(("GET",))
def _catalog(request):
    """目录 + 接口清单：endpoint_index 从 urlpatterns 反推方法，避免手写清单漂移。"""
    from devtools.common import ok

    data = cat.catalog_data()
    try:
        data["endpoints"] = endpoint_index(urlpatterns, exclude=("", "catalog/"))
        data["endpoint_count"] = len(data["endpoints"])
    except Exception:  # noqa: BLE001 —— 目录增强失败不影响主响应
        import logging
        import traceback

        logging.getLogger("contracts").warning(
            "contracts 目录接口清单导出失败:\n%s", traceback.format_exc())
    return ok(data)


urlpatterns = [
    # ---- 目录（3）----
    path("", _catalog, name="contracts-catalog"),
    path("meta/", cat.meta, name="contracts-meta"),
    path("counts/", cat.counts, name="contracts-counts"),

    # ---- 模板（13）----
    path("templates/", t.templates, name="contracts-templates"),
    path("templates/create/", t.template_create, name="contracts-template-create"),
    path("templates/stats/", t.template_stats, name="contracts-template-stats"),
    path("templates/<int:pk>/", t.template_detail, name="contracts-template-detail"),
    path("templates/<int:pk>/update/", t.template_update,
         name="contracts-template-update"),
    path("templates/<int:pk>/delete/", t.template_delete,
         name="contracts-template-delete"),
    path("templates/<int:pk>/publish/", t.template_publish,
         name="contracts-template-publish"),
    path("templates/<int:pk>/disable/", t.template_disable,
         name="contracts-template-disable"),
    path("templates/<int:pk>/clone/", t.template_clone,
         name="contracts-template-clone"),
    path("templates/<int:pk>/render/", t.template_render,
         name="contracts-template-render"),
    path("templates/<int:pk>/clauses/", t.template_clauses,
         name="contracts-template-clauses"),
    path("templates/<int:pk>/clauses/add/", t.clause_add,
         name="contracts-template-clause-add"),
    path("templates/<int:pk>/clauses/reorder/", t.clause_reorder,
         name="contracts-template-clauses-reorder"),
    path("templates/<int:pk>/clauses/from-library/", t.clause_from_library,
         name="contracts-template-clause-from-library"),

    # ---- 模板条款（2）----
    path("clauses/<int:pk>/update/", t.clause_update, name="contracts-clause-update"),
    path("clauses/<int:pk>/delete/", t.clause_delete, name="contracts-clause-delete"),

    # ---- 条款库（5）----
    path("clauses/library/", t.library_list, name="contracts-library"),
    path("clauses/library/create/", t.library_create,
         name="contracts-library-create"),
    path("clauses/library/stats/", t.library_stats, name="contracts-library-stats"),
    path("clauses/library/suggest/", t.library_suggest,
         name="contracts-library-suggest"),
    path("clauses/library/<int:pk>/update/", t.library_update,
         name="contracts-library-update"),
    path("clauses/library/<int:pk>/delete/", t.library_delete,
         name="contracts-library-delete"),

    # ---- 合同台账（3）----
    path("contracts/", c.contracts, name="contracts-contracts"),
    path("contracts/create/", c.contract_create, name="contracts-contract-create"),
    path("contracts/expiring/", c.contract_expiring, name="contracts-expiring"),
    path("contracts/<int:pk>/", c.contract_detail, name="contracts-contract-detail"),

    # ---- 合同编辑与状态机（13）----
    path("contracts/<int:pk>/update/", c.contract_update,
         name="contracts-contract-update"),
    path("contracts/<int:pk>/delete/", c.contract_delete,
         name="contracts-contract-delete"),
    path("contracts/<int:pk>/submit/", c.contract_submit,
         name="contracts-contract-submit"),
    path("contracts/<int:pk>/approve/", c.contract_approve,
         name="contracts-contract-approve"),
    path("contracts/<int:pk>/reject/", c.contract_reject,
         name="contracts-contract-reject"),
    path("contracts/<int:pk>/sign/", c.contract_sign,
         name="contracts-contract-sign"),
    path("contracts/<int:pk>/activate/", c.contract_activate,
         name="contracts-contract-activate"),
    path("contracts/<int:pk>/terminate/", c.contract_terminate,
         name="contracts-contract-terminate"),
    path("contracts/<int:pk>/complete/", c.contract_complete,
         name="contracts-contract-complete"),
    path("contracts/<int:pk>/archive/", c.contract_archive,
         name="contracts-contract-archive"),
    path("contracts/<int:pk>/clone/", c.contract_clone,
         name="contracts-contract-clone"),
    path("contracts/<int:pk>/timeline/", c.contract_timeline,
         name="contracts-contract-timeline"),
    path("contracts/<int:pk>/audit/", c.contract_audit,
         name="contracts-contract-audit"),
    path("contracts/<int:pk>/export/", c.contract_export,
         name="contracts-contract-export"),
    path("contracts/<int:pk>/risk/score/", f.risk_score,
         name="contracts-contract-risk-score"),

    # ---- 版本（3）----
    path("contracts/<int:pk>/versions/", c.versions_list,
         name="contracts-versions"),
    path("contracts/<int:pk>/versions/create/", c.version_create,
         name="contracts-version-create"),
    path("versions/compare/", c.versions_compare, name="contracts-versions-compare"),
    path("versions/<int:pk>/", c.version_detail, name="contracts-version-detail"),
    path("versions/<int:pk>/rollback/", c.version_rollback,
         name="contracts-version-rollback"),

    # ---- 参与方（3）----
    path("contracts/<int:pk>/parties/", c.parties_list,
         name="contracts-parties"),
    path("contracts/<int:pk>/parties/create/", c.party_create,
         name="contracts-party-create"),
    path("parties/<int:pk>/update/", c.party_update, name="contracts-party-update"),
    path("parties/<int:pk>/delete/", c.party_delete, name="contracts-party-delete"),

    # ---- 签署（2）----
    path("contracts/<int:pk>/signatures/", c.signatures_list,
         name="contracts-signatures"),
    path("contracts/<int:pk>/signatures/create/", c.signature_create,
         name="contracts-signature-create"),
    path("signatures/<int:pk>/status/", c.signature_status,
         name="contracts-signature-status"),

    # ---- 附件与标签（4）----
    path("contracts/<int:pk>/attachments/", c.attachments_list,
         name="contracts-attachments"),
    path("contracts/<int:pk>/attachments/create/", c.attachment_create,
         name="contracts-attachment-create"),
    path("attachments/<int:pk>/delete/", c.attachment_delete,
         name="contracts-attachment-delete"),
    path("contracts/<int:pk>/tags/", c.contract_tags, name="contracts-contract-tags"),
    path("contracts/<int:pk>/tags/detail/", c.contract_tags_detail,
         name="contracts-contract-tags-detail"),
    path("tags/", c.tags_list, name="contracts-tags"),
    path("tags/create/", c.tag_create, name="contracts-tag-create"),
    path("tags/<int:pk>/delete/", c.tag_delete, name="contracts-tag-delete"),

    # ---- 履约义务（9）----
    path("contracts/<int:pk>/obligations/", ex.obligations_list,
         name="contracts-obligations"),
    path("contracts/<int:pk>/obligations/create/", ex.obligation_create,
         name="contracts-obligation-create"),
    path("obligations/", ex.obligations_all, name="contracts-obligations-all"),
    path("obligations/overdue/", ex.obligations_overdue,
         name="contracts-obligations-overdue"),
    path("obligations/calendar/", ex.obligations_calendar,
         name="contracts-obligations-calendar"),
    path("obligations/<int:pk>/update/", ex.obligation_update,
         name="contracts-obligation-update"),
    path("obligations/<int:pk>/delete/", ex.obligation_delete,
         name="contracts-obligation-delete"),
    path("obligations/<int:pk>/complete/", ex.obligation_complete,
         name="contracts-obligation-complete"),
    path("obligations/<int:pk>/postpone/", ex.obligation_postpone,
         name="contracts-obligation-postpone"),
    path("obligations/<int:pk>/waive/", ex.obligation_waive,
         name="contracts-obligation-waive"),
    path("obligations/<int:pk>/schedule/", ex.obligation_schedule,
         name="contracts-obligation-schedule"),
    path("obligations/<int:pk>/events/", ex.obligation_events,
         name="contracts-obligation-events"),

    # ---- 里程碑（3）----
    path("contracts/<int:pk>/milestones/", ex.milestones_list,
         name="contracts-milestones"),
    path("contracts/<int:pk>/milestones/create/", ex.milestone_create,
         name="contracts-milestone-create"),
    path("milestones/<int:pk>/update/", ex.milestone_update,
         name="contracts-milestone-update"),
    path("milestones/<int:pk>/complete/", ex.milestone_complete,
         name="contracts-milestone-complete"),

    # ---- 变更单（3）----
    path("contracts/<int:pk>/amendments/", ex.amendments_list,
         name="contracts-amendments"),
    path("contracts/<int:pk>/amendments/create/", ex.amendment_create,
         name="contracts-amendment-create"),
    path("amendments/<int:pk>/update/", ex.amendment_update,
         name="contracts-amendment-update"),
    path("amendments/<int:pk>/submit/", ex.amendment_submit,
         name="contracts-amendment-submit"),
    path("amendments/<int:pk>/approve/", ex.amendment_approve,
         name="contracts-amendment-approve"),

    # ---- 审批（2）----
    path("contracts/<int:pk>/approvals/", ex.approvals_list,
         name="contracts-approvals"),
    path("approvals/pending/", ex.approvals_pending,
         name="contracts-approvals-pending"),

    # ---- 付款（5）----
    path("contracts/<int:pk>/payments/", f.payments_list,
         name="contracts-payments"),
    path("contracts/<int:pk>/payments/create/", f.payment_create,
         name="contracts-payment-create"),
    path("payments/overdue/", f.payments_overdue, name="contracts-payments-overdue"),
    path("contracts/<int:pk>/payments/plan/", f.payment_plan,
         name="contracts-payment-plan"),
    path("payments/<int:pk>/update/", f.payment_update,
         name="contracts-payment-update"),
    path("payments/<int:pk>/pay/", f.payment_pay, name="contracts-payment-pay"),
    path("payments/<int:pk>/cancel/", f.payment_cancel,
         name="contracts-payment-cancel"),

    # ---- 续约（3）----
    path("contracts/<int:pk>/renewals/", f.renewals_list, name="contracts-renewals"),
    path("contracts/<int:pk>/renewals/create/", f.renewal_create,
         name="contracts-renewal-create"),
    path("renewals/upcoming/", f.renewals_upcoming, name="contracts-renewals-upcoming"),
    path("renewals/<int:pk>/confirm/", f.renewal_confirm,
         name="contracts-renewal-confirm"),

    # ---- 风险（3）----
    path("contracts/<int:pk>/risks/", f.risks_list, name="contracts-risks"),
    path("contracts/<int:pk>/risks/create/", f.risk_create,
         name="contracts-risk-create"),
    path("risks/<int:pk>/update/", f.risk_update, name="contracts-risk-update"),

    # ---- 提醒与财务（3）----
    path("reminders/scan/", f.reminder_scan, name="contracts-reminders-scan"),
    path("reminders/", f.reminders_list, name="contracts-reminders"),
    path("reminders/<int:pk>/ack/", f.reminder_ack,
         name="contracts-reminder-ack"),
    path("finance/summary/", f.finance_summary, name="contracts-finance-summary"),

    # ---- 统计（6）----
    path("stats/overview/", st.stats_overview, name="contracts-stats-overview"),
    path("stats/renewal-window/", st.stats_renewal_window,
         name="contracts-stats-renewal-window"),
    path("stats/expiry/", st.stats_expiry, name="contracts-stats-expiry"),
    path("stats/amount/", st.stats_amount, name="contracts-stats-amount"),
    path("stats/risk/", st.stats_risk, name="contracts-stats-risk"),
    path("stats/health/", st.stats_health, name="contracts-stats-health"),
    path("stats/owner-load/", st.stats_owner_load, name="contracts-stats-owner-load"),
]

# 路径数自检：接口函数 104 个；集合查询与创建拆成独立路径（/xxx/ 与 /xxx/create/）。
# 断言放这里，后续新增漏挂路由会立刻在启动时暴露，而不是等前端联调才发现。
_EXPECTED_PATTERNS = 112
assert len(urlpatterns) == _EXPECTED_PATTERNS, \
    f"contracts 路由数应为 {_EXPECTED_PATTERNS}，实际 {len(urlpatterns)}"
