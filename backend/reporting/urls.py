# -*- coding: utf-8 -*-
"""reporting 路由表：/api/reporting/ 下的全部接口。

约定
----
- 列表接口统一以 ``/`` 结尾（项目其它模块一致），前端拼接不会 301；
- 读接口用 GET，写接口用 POST（端点装饰器里声明允许方法）；
- 路由顺序遵循「静态段在参数段之前」（如 ``datasets/quick-preview/`` 在
  ``datasets/<int:pk>/`` 之前），避免被 int 转换器误吞。
"""
from django.urls import path

from reporting.views_catalog import (
    catalog, cron_preview, formula_eval, formula_validate, meta_options,
    model_detail_view, model_fields_view, models_list, registry_summary,
    resolver_sanity,
)
from reporting.views_dashboard import (
    dashboard_available_widgets, dashboard_create, dashboard_delete,
    dashboard_detail, dashboard_export, dashboard_update, dashboard_widget_add,
    dashboard_widget_remove, dashboard_widget_update, dashboard_reorder,
    dashboards_list, public_share, share_disable, share_update, shares_list,
)
from reporting.views_ops import (
    export_jobs_list, metrics_overview, metrics_report, quality_check_view,
    run_detail, runs_list, schedule_create, schedule_delete, schedule_detail,
    schedule_next, schedule_run_now, schedule_toggle, schedule_update,
    schedules_due, schedules_list, subscription_cancel, subscription_create,
    subscription_update, subscriptions_list,
)
from reporting.views_report import (
    annotation_create, annotation_delete, annotation_update, annotations_list,
    favorites_list, page_delete, page_reorder, page_update, page_widget_create,
    page_widgets, report_archive, report_clone, report_create, report_delete,
    report_detail, report_export, report_favorite, report_page_create,
    report_pages, report_preview, report_publish, report_result, report_run,
    report_runs, report_share_create, report_snapshots, report_update,
    reports_list, widget_delete, widget_filter_create, widget_filter_delete,
    widget_filter_update, widget_filters, widget_reorder, widget_run,
    widget_update,
)
from reporting.views_source import (
    dataset_create, dataset_delete, dataset_detail, dataset_field_create,
    dataset_field_delete, dataset_field_update, dataset_fields,
    dataset_fields_reorder, dataset_fields_save, dataset_join_create,
    dataset_join_delete, dataset_param_create, dataset_param_delete,
    dataset_preview, dataset_quick_preview, dataset_schema, dataset_update,
    dataset_values, datasets_list, source_create, source_delete, source_detail,
    source_test, source_toggle, source_update, sources_list,
)

urlpatterns = [
    # ---- 目录 / 元信息（10） ----
    path("", catalog, name="reporting-catalog"),
    path("models/", models_list, name="reporting-models"),
    path("models/<str:label>/", model_detail_view, name="reporting-model-detail"),
    path("models/<str:label>/fields/", model_fields_view, name="reporting-model-fields"),
    path("meta/", meta_options, name="reporting-meta"),
    path("formula/eval/", formula_eval, name="reporting-formula-eval"),
    path("formula/validate/", formula_validate, name="reporting-formula-validate"),
    path("cron/preview/", cron_preview, name="reporting-cron-preview"),
    path("registry/", registry_summary, name="reporting-registry"),
    path("resolver/", resolver_sanity, name="reporting-resolver"),

    # ---- 数据源（7） ----
    path("sources/", sources_list, name="reporting-sources"),
    path("sources/create/", source_create, name="reporting-source-create"),
    path("sources/<int:pk>/", source_detail, name="reporting-source-detail"),
    path("sources/<int:pk>/update/", source_update, name="reporting-source-update"),
    path("sources/<int:pk>/delete/", source_delete, name="reporting-source-delete"),
    path("sources/<int:pk>/test/", source_test, name="reporting-source-test"),
    path("sources/<int:pk>/toggle/", source_toggle, name="reporting-source-toggle"),

    # ---- 数据集（15） ----
    path("datasets/", datasets_list, name="reporting-datasets"),
    path("datasets/create/", dataset_create, name="reporting-dataset-create"),
    path("datasets/quick-preview/", dataset_quick_preview, name="reporting-dataset-quick"),
    path("datasets/fields/<int:pk>/update/", dataset_field_update,
         name="reporting-dataset-field-update"),
    path("datasets/fields/<int:pk>/delete/", dataset_field_delete,
         name="reporting-dataset-field-delete"),
    path("datasets/joins/<int:pk>/delete/", dataset_join_delete,
         name="reporting-dataset-join-delete"),
    path("datasets/params/<int:pk>/delete/", dataset_param_delete,
         name="reporting-dataset-param-delete"),
    path("datasets/<int:pk>/", dataset_detail, name="reporting-dataset-detail"),
    path("datasets/<int:pk>/update/", dataset_update, name="reporting-dataset-update"),
    path("datasets/<int:pk>/delete/", dataset_delete, name="reporting-dataset-delete"),
    path("datasets/<int:pk>/fields/", dataset_fields, name="reporting-dataset-fields"),
    path("datasets/<int:pk>/fields/save/", dataset_fields_save,
         name="reporting-dataset-fields-save"),
    path("datasets/<int:pk>/fields/create/", dataset_field_create,
         name="reporting-dataset-field-create"),
    path("datasets/<int:pk>/fields/reorder/", dataset_fields_reorder,
         name="reporting-dataset-fields-reorder"),
    path("datasets/<int:pk>/joins/create/", dataset_join_create,
         name="reporting-dataset-join-create"),
    path("datasets/<int:pk>/params/create/", dataset_param_create,
         name="reporting-dataset-param-create"),
    path("datasets/<int:pk>/preview/", dataset_preview, name="reporting-dataset-preview"),
    path("datasets/<int:pk>/values/", dataset_values, name="reporting-dataset-values"),
    path("datasets/<int:pk>/schema/", dataset_schema, name="reporting-dataset-schema"),

    # ---- 报表（17） ----
    path("reports/", reports_list, name="reporting-reports"),
    path("reports/create/", report_create, name="reporting-report-create"),
    path("reports/favorites/", favorites_list, name="reporting-favorites"),
    path("reports/<int:pk>/", report_detail, name="reporting-report-detail"),
    path("reports/<int:pk>/update/", report_update, name="reporting-report-update"),
    path("reports/<int:pk>/delete/", report_delete, name="reporting-report-delete"),
    path("reports/<int:pk>/clone/", report_clone, name="reporting-report-clone"),
    path("reports/<int:pk>/publish/", report_publish, name="reporting-report-publish"),
    path("reports/<int:pk>/archive/", report_archive, name="reporting-report-archive"),
    path("reports/<int:pk>/run/", report_run, name="reporting-report-run"),
    path("reports/<int:pk>/preview/", report_preview, name="reporting-report-preview"),
    path("reports/<int:pk>/result/", report_result, name="reporting-report-result"),
    path("reports/<int:pk>/snapshots/", report_snapshots, name="reporting-report-snapshots"),
    path("reports/<int:pk>/export/", report_export, name="reporting-report-export"),
    path("reports/<int:pk>/runs/", report_runs, name="reporting-report-runs"),
    path("reports/<int:pk>/favorite/", report_favorite, name="reporting-report-favorite"),
    path("reports/<int:pk>/share/", report_share_create, name="reporting-report-share"),

    # ---- 报表页面（5） ----
    path("reports/<int:pk>/pages/", report_pages, name="reporting-report-pages"),
    path("reports/<int:pk>/pages/create/", report_page_create,
         name="reporting-report-page-create"),
    path("pages/<int:pk>/update/", page_update, name="reporting-page-update"),
    path("pages/<int:pk>/delete/", page_delete, name="reporting-page-delete"),
    path("reports/<int:pk>/pages/reorder/", page_reorder, name="reporting-page-reorder"),

    # ---- 报表组件（6） ----
    path("pages/<int:pk>/widgets/", page_widgets, name="reporting-page-widgets"),
    path("pages/<int:pk>/widgets/create/", page_widget_create,
         name="reporting-page-widget-create"),
    path("widgets/<int:pk>/update/", widget_update, name="reporting-widget-update"),
    path("widgets/<int:pk>/delete/", widget_delete, name="reporting-widget-delete"),
    path("pages/<int:pk>/widgets/reorder/", widget_reorder, name="reporting-widget-reorder"),
    path("widgets/<int:pk>/run/", widget_run, name="reporting-widget-run"),

    # ---- 组件筛选器（4） ----
    path("widgets/<int:pk>/filters/", widget_filters, name="reporting-widget-filters"),
    path("widgets/<int:pk>/filters/create/", widget_filter_create,
         name="reporting-widget-filter-create"),
    path("filters/<int:pk>/update/", widget_filter_update, name="reporting-filter-update"),
    path("filters/<int:pk>/delete/", widget_filter_delete, name="reporting-filter-delete"),

    # ---- 批注（4） ----
    path("annotations/", annotations_list, name="reporting-annotations"),
    path("annotations/create/", annotation_create, name="reporting-annotation-create"),
    path("annotations/<int:pk>/update/", annotation_update, name="reporting-annotation-update"),
    path("annotations/<int:pk>/delete/", annotation_delete, name="reporting-annotation-delete"),

    # ---- 仪表盘（11） ----
    path("dashboards/", dashboards_list, name="reporting-dashboards"),
    path("dashboards/create/", dashboard_create, name="reporting-dashboard-create"),
    path("dashboards/available-widgets/", dashboard_available_widgets,
         name="reporting-dashboard-available-widgets"),
    path("dashboards/<int:pk>/", dashboard_detail, name="reporting-dashboard-detail"),
    path("dashboards/<int:pk>/update/", dashboard_update, name="reporting-dashboard-update"),
    path("dashboards/<int:pk>/delete/", dashboard_delete, name="reporting-dashboard-delete"),
    path("dashboards/<int:pk>/widgets/add/", dashboard_widget_add,
         name="reporting-dashboard-widget-add"),
    path("dashboards/<int:pk>/widgets/reorder/", dashboard_reorder,
         name="reporting-dashboard-widget-reorder"),
    path("dashboards/<int:pk>/export/", dashboard_export, name="reporting-dashboard-export"),
    path("dashboard-widgets/<int:pk>/update/", dashboard_widget_update,
         name="reporting-dashboard-widget-update"),
    path("dashboard-widgets/<int:pk>/remove/", dashboard_widget_remove,
         name="reporting-dashboard-widget-remove"),

    # ---- 分享（4） ----
    path("shares/", shares_list, name="reporting-shares"),
    path("shares/<int:pk>/update/", share_update, name="reporting-share-update"),
    path("shares/<int:pk>/disable/", share_disable, name="reporting-share-disable"),
    path("share/<str:token>/", public_share, name="reporting-public-share"),

    # ---- 计划任务（9） ----
    path("schedules/", schedules_list, name="reporting-schedules"),
    path("schedules/create/", schedule_create, name="reporting-schedule-create"),
    path("schedules/due/", schedules_due, name="reporting-schedules-due"),
    path("schedules/<int:pk>/", schedule_detail, name="reporting-schedule-detail"),
    path("schedules/<int:pk>/update/", schedule_update, name="reporting-schedule-update"),
    path("schedules/<int:pk>/delete/", schedule_delete, name="reporting-schedule-delete"),
    path("schedules/<int:pk>/toggle/", schedule_toggle, name="reporting-schedule-toggle"),
    path("schedules/<int:pk>/run-now/", schedule_run_now, name="reporting-schedule-run-now"),
    path("schedules/<int:pk>/next/", schedule_next, name="reporting-schedule-next"),

    # ---- 订阅（4） ----
    path("subscriptions/", subscriptions_list, name="reporting-subscriptions"),
    path("subscriptions/create/", subscription_create, name="reporting-subscription-create"),
    path("subscriptions/<int:pk>/update/", subscription_update,
         name="reporting-subscription-update"),
    path("subscriptions/<int:pk>/cancel/", subscription_cancel,
         name="reporting-subscription-cancel"),

    # ---- 指标 / 质量 / 流水 / 导出任务（6） ----
    path("metrics/overview/", metrics_overview, name="reporting-metrics-overview"),
    path("metrics/reports/<int:pk>/", metrics_report, name="reporting-metrics-report"),
    path("quality/check/", quality_check_view, name="reporting-quality-check"),
    path("runs/", runs_list, name="reporting-runs"),
    path("runs/<int:pk>/", run_detail, name="reporting-run-detail"),
    path("export-jobs/", export_jobs_list, name="reporting-export-jobs"),
]


# 接口数量下限：少于 50 个说明路由表被误删，导入阶段直接失败（自检用）
ENDPOINT_COUNT = len(urlpatterns)
MIN_ENDPOINT_COUNT = 50
if ENDPOINT_COUNT < MIN_ENDPOINT_COUNT:  # pragma: no cover —— 保护性断言
    raise RuntimeError(f"reporting 接口数量异常：{ENDPOINT_COUNT} < {MIN_ENDPOINT_COUNT}")
