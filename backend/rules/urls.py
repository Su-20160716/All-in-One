# -*- coding: utf-8 -*-
"""rules 路由：79 个接口，全部挂载在 /api/rules/ 下。

分组与 views.py 一一对应：
- 目录 1
- 规则集 12（含导入 / 发布 / 回滚 / 版本列表）
- 版本 2（详情 + 对比）
- 规则 6、条件 4、动作 3、变量 3
- 决策表 6、决策行 2
- 评估 2 + 评估记录 4
- 测试用例 6、仿真 2、冲突 4
- 调度 6、审批 3
- 统计 5、执行日志 2
- 标签 2、模板 2、任务 1、通知 1
"""
from django.urls import path

from rules import views as v

urlpatterns = [
    # ---- 目录 ----
    path("", v.catalog, name="rules-catalog"),

    # ---- 规则集（12）----
    path("rulesets/", v.rulesets, name="rules-rulesets"),
    path("rulesets/import/", v.ruleset_import, name="rules-ruleset-import"),
    path("rulesets/<int:pk>/", v.ruleset_detail, name="rules-ruleset-detail"),
    path("rulesets/<int:pk>/delete/", v.ruleset_delete, name="rules-ruleset-delete"),
    path("rulesets/<int:pk>/publish/", v.ruleset_publish, name="rules-ruleset-publish"),
    path("rulesets/<int:pk>/pause/", v.ruleset_pause, name="rules-ruleset-pause"),
    path("rulesets/<int:pk>/archive/", v.ruleset_archive, name="rules-ruleset-archive"),
    path("rulesets/<int:pk>/clone/", v.ruleset_clone, name="rules-ruleset-clone"),
    path("rulesets/<int:pk>/validate/", v.ruleset_validate, name="rules-ruleset-validate"),
    path("rulesets/<int:pk>/export/", v.ruleset_export, name="rules-ruleset-export"),
    path("rulesets/<int:pk>/rollback/", v.ruleset_rollback, name="rules-ruleset-rollback"),
    path("rulesets/<int:pk>/versions/", v.versions_list, name="rules-versions-list"),

    # ---- 版本（2）----
    path("versions/compare/", v.versions_compare, name="rules-versions-compare"),
    path("versions/<int:pk>/", v.version_detail, name="rules-version-detail"),

    # ---- 规则（6）----
    path("rules/", v.rules, name="rules-rules"),
    path("rules/reorder/", v.rules_reorder, name="rules-rules-reorder"),
    path("rules/import/", v.rules_import, name="rules-rules-import"),
    path("rules/<int:pk>/", v.rule_detail, name="rules-rule-detail"),
    path("rules/<int:pk>/delete/", v.rule_delete, name="rules-rule-delete"),
    path("rules/<int:pk>/toggle/", v.rule_toggle, name="rules-rule-toggle"),

    # ---- 条件（4）----
    path("conditions/", v.conditions, name="rules-conditions"),
    path("conditions/compose/", v.conditions_compose, name="rules-conditions-compose"),
    path("conditions/<int:pk>/update/", v.condition_update, name="rules-condition-update"),
    path("conditions/<int:pk>/delete/", v.condition_delete, name="rules-condition-delete"),

    # ---- 动作（3）----
    path("actions/", v.actions, name="rules-actions"),
    path("actions/<int:pk>/update/", v.action_update, name="rules-action-update"),
    path("actions/<int:pk>/delete/", v.action_delete, name="rules-action-delete"),

    # ---- 变量（3）----
    path("variables/", v.variables, name="rules-variables"),
    path("variables/<int:pk>/update/", v.variable_update, name="rules-variable-update"),
    path("variables/<int:pk>/delete/", v.variable_delete, name="rules-variable-delete"),

    # ---- 决策表（6）----
    path("tables/", v.tables, name="rules-tables"),
    path("tables/<int:pk>/", v.table_detail, name="rules-table-detail"),
    path("tables/<int:pk>/delete/", v.table_delete, name="rules-table-delete"),
    path("tables/<int:pk>/rows/", v.table_rows, name="rules-table-rows"),
    path("tables/<int:pk>/rows/bulk/", v.table_rows_bulk, name="rules-table-rows-bulk"),
    path("tables/<int:pk>/evaluate/", v.table_evaluate, name="rules-table-evaluate"),

    # ---- 决策行（2）----
    path("rows/<int:pk>/update/", v.row_update, name="rules-row-update"),
    path("rows/<int:pk>/delete/", v.row_delete, name="rules-row-delete"),

    # ---- 评估（2）----
    path("evaluate/", v.evaluate, name="rules-evaluate"),
    path("evaluate/batch/", v.evaluate_batch, name="rules-evaluate-batch"),

    # ---- 评估记录（4）----
    path("evaluations/", v.evaluations, name="rules-evaluations"),
    path("evaluations/<int:pk>/", v.evaluation_detail, name="rules-evaluation-detail"),
    path("evaluations/<int:pk>/miss-diagnose/", v.evaluation_miss_diagnose,
         name="rules-evaluation-miss-diagnose"),
    path("evaluations/<int:pk>/reevaluate/", v.evaluation_reevaluate,
         name="rules-evaluation-reevaluate"),

    # ---- 测试用例（6）----
    path("testcases/", v.testcases, name="rules-testcases"),
    path("testcases/run-all/", v.testcases_run_all, name="rules-testcases-run-all"),
    path("testcases/coverage/", v.testcases_coverage, name="rules-testcases-coverage"),
    path("testcases/<int:pk>/update/", v.testcase_update, name="rules-testcase-update"),
    path("testcases/<int:pk>/delete/", v.testcase_delete, name="rules-testcase-delete"),
    path("testcases/<int:pk>/run/", v.testcase_run, name="rules-testcase-run"),

    # ---- 仿真（2）----
    path("simulations/", v.simulations, name="rules-simulations"),
    path("simulations/<int:pk>/", v.simulation_detail, name="rules-simulation-detail"),

    # ---- 冲突（4）----
    path("conflicts/", v.conflicts, name="rules-conflicts"),
    path("conflicts/detect/", v.conflicts_detect, name="rules-conflicts-detect"),
    path("conflicts/<int:pk>/resolve/", v.conflict_resolve, name="rules-conflict-resolve"),
    path("conflicts/<int:pk>/ignore/", v.conflict_ignore, name="rules-conflict-ignore"),

    # ---- 调度（6）----
    path("schedules/", v.schedules, name="rules-schedules"),
    path("schedules/scan/", v.schedules_scan, name="rules-schedules-scan"),
    path("schedules/<int:pk>/update/", v.schedule_update, name="rules-schedule-update"),
    path("schedules/<int:pk>/toggle/", v.schedule_toggle, name="rules-schedule-toggle"),
    path("schedules/<int:pk>/run/", v.schedule_run, name="rules-schedule-run"),
    path("schedules/<int:pk>/delete/", v.schedule_delete, name="rules-schedule-delete"),

    # ---- 审批（3）----
    path("approvals/", v.approvals, name="rules-approvals"),
    path("approvals/<int:pk>/approve/", v.approval_approve, name="rules-approval-approve"),
    path("approvals/<int:pk>/reject/", v.approval_reject, name="rules-approval-reject"),

    # ---- 统计（5）----
    path("stats/overview/", v.stats_overview, name="rules-stats-overview"),
    path("stats/top-rules/", v.stats_top_rules, name="rules-stats-top-rules"),
    path("stats/failures/", v.stats_failures, name="rules-stats-failures"),
    path("stats/latency/", v.stats_latency, name="rules-stats-latency"),
    path("stats/trend/", v.stats_trend, name="rules-stats-trend"),

    # ---- 执行日志（2）----
    path("logs/", v.logs, name="rules-logs"),
    path("logs/<int:pk>/", v.log_detail, name="rules-log-detail"),

    # ---- 标签（2）----
    path("tags/", v.tags, name="rules-tags"),
    path("tags/<int:pk>/delete/", v.tag_delete, name="rules-tag-delete"),

    # ---- 模板（2）----
    path("templates/", v.templates, name="rules-templates"),
    path("templates/apply/", v.template_apply, name="rules-template-apply"),

    # ---- 任务 / 通知（2）----
    path("tasks/", v.tasks, name="rules-tasks"),
    path("notifications/", v.notifications, name="rules-notifications"),
]

# 接口数是产品契约的一部分：路由漏挂会被这里直接拦下，而不是等前端 404
assert len(urlpatterns) == 79, f"rules 接口数应为 79，实际 {len(urlpatterns)}"
