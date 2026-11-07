# -*- coding: utf-8 -*-
"""formstudio 路由：表单设计器 61 个业务接口（含 GET/POST 多方法共 72 个方法）。

前缀：/api/formstudio/
约定：固定路径（from-template/public/verify/mine）必须排在 <int:pk> 之前，
虽然 Django 的 int 转换器本身不会误吞字符串，保持顺序仍能减少阅读成本。
"""
from django.urls import path

from formstudio import views_analytics as a
from formstudio import views_forms as f
from formstudio import views_submissions as s

urlpatterns = [
    # ---- 目录 ----
    path("", f.catalog, name="formstudio-catalog"),
    path("catalog/", f.catalog, name="formstudio-catalog-alias"),

    # ---- 表单定义 ----
    path("forms/", f.form_collection),
    path("forms/from-template/", f.form_from_template),
    path("forms/<int:pk>/", f.form_item),
    path("forms/<int:pk>/publish/", f.form_publish),
    path("forms/<int:pk>/close/", f.form_close),
    path("forms/<int:pk>/archive/", f.form_archive),
    path("forms/<int:pk>/clone/", f.form_clone),
    path("forms/<int:pk>/save-as-template/", f.form_save_as_template),

    # ---- schema ----
    path("forms/<int:pk>/schema/", f.form_schema),
    path("forms/<int:pk>/schema/validate/", f.form_schema_validate),

    # ---- 版本 ----
    path("forms/<int:pk>/versions/", f.form_version_list),
    path("forms/<int:pk>/versions/compare/", f.version_compare),
    path("versions/<int:pk>/", f.version_detail),
    path("versions/<int:pk>/rollback/", f.version_rollback),

    # ---- 分区 ----
    path("forms/<int:pk>/sections/", f.form_section_collection),
    path("forms/<int:pk>/sections/reorder/", f.form_section_reorder),
    path("sections/<int:pk>/", f.section_item),

    # ---- 字段 ----
    path("forms/<int:pk>/fields/", f.form_field_collection),
    path("forms/<int:pk>/fields/reorder/", f.form_field_reorder),
    path("fields/<int:pk>/", f.field_item),
    path("fields/<int:pk>/options/", f.field_options),

    # ---- 校验规则 ----
    path("forms/<int:pk>/validations/", f.form_validation_list),
    path("validations/", f.validation_create),
    path("validations/<int:pk>/", f.validation_item),

    # ---- 逻辑规则 ----
    path("forms/<int:pk>/logic/", f.form_logic_list),
    path("forms/<int:pk>/logic/test/", f.logic_test),
    path("logic/", f.logic_create),
    path("logic/<int:pk>/", f.logic_item),

    # ---- 提交 ----
    path("submissions/public/", s.submission_public),
    path("submissions/mine/", s.submission_mine),
    path("submissions/draft/", s.submission_draft_create),
    path("submissions/", s.submission_collection),
    path("submissions/<int:pk>/", s.submission_detail),
    path("submissions/<int:pk>/draft/", s.submission_draft_update),
    path("submissions/<int:pk>/delete/", s.submission_delete),
    path("submissions/<int:pk>/approve/", s.submission_approve),
    path("submissions/<int:pk>/reject/", s.submission_reject),
    path("submissions/<int:pk>/attachments/", s.submission_attachments),

    # ---- 统计与导出 ----
    path("forms/<int:pk>/stats/", a.form_stats),
    path("forms/<int:pk>/stats/fields/", a.form_stats_fields),
    path("forms/<int:pk>/stats/trend/", a.form_stats_trend),
    path("forms/<int:pk>/stats/duration/", a.form_stats_duration),
    path("forms/<int:pk>/stats/snapshots/", a.form_stats_snapshots),
    path("forms/<int:pk>/export/", a.form_export),

    # ---- 分享链接 ----
    path("forms/<int:pk>/share-links/", a.form_share_links),
    path("share-links/", a.share_link_list),
    path("share-links/verify/", a.share_link_verify),
    path("share-links/<int:pk>/disable/", a.share_link_disable),

    # ---- Webhook ----
    path("webhooks/", a.webhook_collection),
    path("webhooks/<int:pk>/", a.webhook_item),
    path("webhooks/<int:pk>/test/", a.webhook_test),
    path("webhooks/<int:pk>/deliveries/", a.webhook_deliveries),
    path("deliveries/", a.delivery_list),
    path("deliveries/<int:pk>/retry/", a.delivery_retry),

    # ---- 模板 ----
    path("templates/", a.template_list),
    path("templates/<int:pk>/", a.template_detail),
    path("templates/<int:pk>/instantiate/", a.template_instantiate),

    # ---- 审核任务 ----
    path("review-tasks/mine/", s.review_task_mine),
    path("review-tasks/<int:pk>/decide/", s.review_task_decide),

    # ---- 评论 ----
    path("forms/<int:pk>/comments/", s.form_comments),
    path("comments/<int:pk>/resolve/", s.comment_resolve),
]
