# -*- coding: utf-8 -*-
"""功能开关与实验 · 路由（83 个接口，全部挂在 /api/flags/ 下）。

分组与 views 模块一一对应：
- 目录 1
- 项目 6 + 环境 5
- 开关 12 + 评估 4
- 细分 5 + 细分规则 3
- 灰度 4、定向 5、变体 4
- 实验 10 + 实验指标 3
- 受众 5、依赖 6、护栏 4
- 统计 5、审计 1

路径约定：
- 列表/创建同路径，按 GET/POST 区分；
- 详情用 ``<pk>/``，动作使用 ``update/``、``toggle/`` 等子路径；
- 所有列表响应统一 ``{items,count,page,page_size}``。
"""
from django.urls import path

from flags import views_catalog as c
from flags import views_experiment as e
from flags import views_flag as f
from flags import views_govern as g
from flags import views_project as pr
from flags import views_stats as s
from flags import views_targeting as t

urlpatterns = [
    # ---- 目录（1）----
    path("", c.catalog, name="flags-catalog"),

    # ---- 项目（6）----
    path("projects/", pr.projects, name="flags-projects"),
    path("projects/update/", pr.project_update, name="flags-project-update"),
    path("projects/members/", pr.project_members, name="flags-project-members"),
    path("projects/archive/", pr.project_archive, name="flags-project-archive"),
    path("projects/<int:pk>/", pr.project_detail, name="flags-project-detail"),
    path("projects/<int:pk>/stats/", pr.project_stats, name="flags-project-stats"),

    # ---- 环境（5）----
    path("environments/", pr.environments, name="flags-environments"),
    path("environments/update/", pr.environment_update, name="flags-environment-update"),
    path("environments/toggle/", pr.environment_toggle, name="flags-environment-toggle"),
    path("environments/delete/", pr.environment_delete, name="flags-environment-delete"),
    path("environments/<int:pk>/", pr.environment_detail, name="flags-environment-detail"),

    # ---- 开关（12）----
    path("flags/", f.flags, name="flags-flags"),
    path("flags/update/", f.flag_update, name="flags-flag-update"),
    path("flags/toggle/", f.flag_toggle, name="flags-flag-toggle"),
    path("flags/clone/", f.flag_clone, name="flags-flag-clone"),
    path("flags/archive/", f.flag_archive, name="flags-flag-archive"),
    path("flags/publish/", f.flag_publish, name="flags-flag-publish"),
    path("flags/rollback/", f.flag_rollback, name="flags-flag-rollback"),
    path("flags/delete/", f.flag_delete, name="flags-flag-delete"),
    path("flags/<int:pk>/", f.flag_detail, name="flags-flag-detail"),
    path("flags/<int:pk>/versions/", f.flag_versions, name="flags-flag-versions"),
    path("flags/<int:pk>/stats/", f.flag_stats, name="flags-flag-stats"),
    path("flags/<int:pk>/evaluations/", f.flag_evaluations, name="flags-flag-evaluations"),

    # ---- 评估（4）----
    path("evaluate/", f.evaluate, name="flags-evaluate"),
    path("evaluate/batch/", f.evaluate_batch, name="flags-evaluate-batch"),
    path("evaluate/bool/", f.evaluate_bool, name="flags-evaluate-bool"),
    path("evaluate/explain/", f.evaluate_explain, name="flags-evaluate-explain"),

    # ---- 细分（5）----
    path("segments/", t.segments, name="flags-segments"),
    path("segments/update/", t.segment_update, name="flags-segment-update"),
    path("segments/delete/", t.segment_delete, name="flags-segment-delete"),
    path("segments/preview/", t.segment_preview, name="flags-segment-preview"),
    path("segments/<int:pk>/", t.segment_detail, name="flags-segment-detail"),

    # ---- 细分规则（3）----
    path("segments/rules/", t.segment_rules, name="flags-segment-rules"),
    path("segments/rules/update/", t.segment_rule_update, name="flags-segment-rule-update"),
    path("segments/rules/delete/", t.segment_rule_delete, name="flags-segment-rule-delete"),

    # ---- 灰度（4）----
    path("rollouts/", t.rollouts, name="flags-rollouts"),
    path("rollouts/update/", t.rollout_update, name="flags-rollout-update"),
    path("rollouts/toggle/", t.rollout_toggle, name="flags-rollout-toggle"),
    path("rollouts/advance/", t.rollout_advance, name="flags-rollout-advance"),

    # ---- 定向规则（5）----
    path("targeting-rules/", t.targeting_rules, name="flags-targeting-rules"),
    path("targeting-rules/update/", t.targeting_rule_update, name="flags-targeting-update"),
    path("targeting-rules/delete/", t.targeting_rule_delete, name="flags-targeting-delete"),
    path("targeting-rules/reorder/", t.targeting_rule_reorder, name="flags-targeting-reorder"),
    path("targeting-rules/toggle/", t.targeting_rule_toggle, name="flags-targeting-toggle"),

    # ---- 变体（4）----
    path("variants/", t.variants, name="flags-variants"),
    path("variants/update/", t.variant_update, name="flags-variant-update"),
    path("variants/delete/", t.variant_delete, name="flags-variant-delete"),
    path("variants/weight/", t.variant_weight, name="flags-variant-weight"),

    # ---- 实验（10）----
    path("experiments/", e.experiments, name="flags-experiments"),
    path("experiments/update/", e.experiment_update, name="flags-experiment-update"),
    path("experiments/start/", e.experiment_start, name="flags-experiment-start"),
    path("experiments/pause/", e.experiment_pause, name="flags-experiment-pause"),
    path("experiments/conclude/", e.experiment_conclude, name="flags-experiment-conclude"),
    path("experiments/exposures/", e.experiment_exposure_report,
         name="flags-experiment-exposure-report"),
    path("experiments/<int:pk>/", e.experiment_detail, name="flags-experiment-detail"),
    path("experiments/<int:pk>/results/", e.experiment_results,
         name="flags-experiment-results"),
    path("experiments/<int:pk>/progress/", e.experiment_progress,
         name="flags-experiment-progress"),
    path("experiments/<int:pk>/exposures/", e.experiment_exposures,
         name="flags-experiment-exposures"),

    # ---- 实验指标（3）----
    path("experiment-metrics/", e.experiment_metrics, name="flags-experiment-metrics"),
    path("experiment-metrics/update/", e.experiment_metric_update,
         name="flags-experiment-metric-update"),
    path("experiment-metrics/delete/", e.experiment_metric_delete,
         name="flags-experiment-metric-delete"),

    # ---- 受众（5）----
    path("audiences/", g.audiences, name="flags-audiences"),
    path("audiences/update/", g.audience_update, name="flags-audience-update"),
    path("audiences/delete/", g.audience_delete, name="flags-audience-delete"),
    path("audiences/preview/", g.audience_preview, name="flags-audience-preview"),
    path("audiences/<int:pk>/", g.audience_detail, name="flags-audience-detail"),

    # ---- 依赖（6）----
    path("dependencies/", g.dependencies, name="flags-dependencies"),
    path("dependencies/update/", g.dependency_update, name="flags-dependency-update"),
    path("dependencies/delete/", g.dependency_delete, name="flags-dependency-delete"),
    path("dependencies/graph/", g.dependency_graph, name="flags-dependency-graph"),
    path("dependencies/check-cycles/", g.dependency_check_cycles,
         name="flags-dependency-cycles"),
    path("dependencies/<int:pk>/", g.dependency_detail, name="flags-dependency-detail"),

    # ---- 护栏（4）----
    path("guardrails/", g.guardrails, name="flags-guardrails"),
    path("guardrails/update/", g.guardrail_update, name="flags-guardrail-update"),
    path("guardrails/delete/", g.guardrail_delete, name="flags-guardrail-delete"),
    path("guardrails/check/", g.guardrail_check, name="flags-guardrail-check"),

    # ---- 统计（5）----
    path("stats/overview/", s.stats_overview, name="flags-stats-overview"),
    path("stats/top-flags/", s.stats_top_flags, name="flags-stats-top-flags"),
    path("stats/variant-distribution/", s.stats_variant_distribution,
         name="flags-stats-variant-distribution"),
    path("stats/evaluation-trend/", s.stats_evaluation_trend,
         name="flags-stats-evaluation-trend"),
    path("stats/experiment-board/", s.stats_experiment_board,
         name="flags-stats-experiment-board"),

    # ---- 审计（1）----
    path("audit-events/", g.audit_events, name="flags-audit-events"),
]
