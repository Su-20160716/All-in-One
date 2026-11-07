# -*- coding: utf-8 -*-
"""功能开关 · Django Admin 注册。

Admin 只用于内部排障与数据修复，正常业务操作走 /api/flags/ 接口。
这里刻意保持「只读为主」：评估日志、曝光、审计事件不允许在 Admin 里
修改，避免绕过接口层的校验、审计与缓存失效。
"""
from django.contrib import admin

from flags.models import (
    Assignment,
    Audience,
    AuditEvent,
    Environment,
    EvaluationLog,
    Experiment,
    ExperimentMetric,
    Exposure,
    Flag,
    FlagDependency,
    FlagVersion,
    Guardrail,
    Project,
    Rollout,
    Segment,
    SegmentRule,
    TargetingRule,
    Variant,
)

# 不要在这里改 admin.site 的全局标题：flags 被自动发现时会影响其他应用的
# 后台显示，属于跨模块副作用。命名空间内的展示交给菜单与 verbose_name。


class ReadOnlyAdmin(admin.ModelAdmin):
    """只读基类：历史类数据只允许查看，防止绕过审计改数。"""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EnvironmentInline(admin.TabularInline):
    model = Environment
    extra = 0
    fields = ("key", "name", "env_type", "enabled", "sort_order")
    ordering = ("sort_order", "id")


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0
    fields = ("key", "name", "weight", "payload")
    ordering = ("id",)


class TargetingRuleInline(admin.TabularInline):
    model = TargetingRule
    extra = 0
    fields = ("priority", "conditions", "condition_logic", "variant_key", "percentage", "enabled")
    ordering = ("priority", "id")


class SegmentRuleInline(admin.TabularInline):
    model = SegmentRule
    extra = 0
    fields = ("field", "operator", "value", "logic", "sort_order")
    ordering = ("sort_order", "id")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "name", "status", "environment_count", "owner", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("key", "name", "description")
    ordering = ("-created_at", "-id")
    readonly_fields = ("created_at", "updated_at")
    inlines = (EnvironmentInline,)


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "key", "name", "env_type", "enabled", "sort_order")
    list_filter = ("env_type", "enabled")
    search_fields = ("key", "name", "project__key", "project__name")
    ordering = ("project_id", "sort_order", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Flag)
class FlagAdmin(admin.ModelAdmin):
    list_display = (
        "id", "key", "name", "project", "environment", "flag_type",
        "status", "temporary", "last_evaluated_at", "updated_at",
    )
    list_filter = ("flag_type", "status", "temporary", "permanent", "environment__env_type")
    search_fields = ("key", "name", "description", "assignee", "project__key")
    ordering = ("-updated_at", "-id")
    readonly_fields = ("last_evaluated_at", "created_at", "updated_at")
    inlines = (VariantInline, TargetingRuleInline)


@admin.register(FlagVersion)
class FlagVersionAdmin(ReadOnlyAdmin):
    list_display = ("id", "flag", "version", "publisher", "change_note", "created_at")
    search_fields = ("flag__key", "change_note")
    ordering = ("-created_at", "-id")


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "name", "rule_match", "member_count", "owner", "updated_at")
    list_filter = ("rule_match",)
    search_fields = ("name", "description", "project__key")
    ordering = ("project_id", "id")
    readonly_fields = ("member_count", "created_at", "updated_at")
    inlines = (SegmentRuleInline,)


@admin.register(SegmentRule)
class SegmentRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "segment", "field", "operator", "logic", "sort_order")
    list_filter = ("operator", "logic")
    search_fields = ("field", "segment__name")
    ordering = ("segment_id", "sort_order", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Rollout)
class RolloutAdmin(admin.ModelAdmin):
    list_display = ("id", "flag", "percentage", "segment", "status", "start_at", "end_at")
    list_filter = ("status",)
    search_fields = ("flag__key", "flag__name")
    ordering = ("-created_at", "-id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TargetingRule)
class TargetingRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "flag", "priority", "variant_key", "percentage", "enabled")
    list_filter = ("enabled", "condition_logic")
    search_fields = ("flag__key", "note")
    ordering = ("flag_id", "priority", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ("id", "flag", "key", "name", "weight")
    search_fields = ("flag__key", "key", "name")
    ordering = ("flag_id", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "flag", "status", "primary_metric",
        "min_sample_size", "start_at", "end_at",
    )
    list_filter = ("status",)
    search_fields = ("name", "hypothesis", "primary_metric", "flag__key")
    ordering = ("-created_at", "-id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ExperimentMetric)
class ExperimentMetricAdmin(admin.ModelAdmin):
    list_display = ("id", "experiment", "name", "metric_type", "direction", "unit")
    list_filter = ("metric_type", "direction")
    search_fields = ("name", "experiment__name")
    ordering = ("experiment_id", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Assignment)
class AssignmentAdmin(ReadOnlyAdmin):
    list_display = ("id", "experiment", "user_key", "variant_key", "bucket", "created_at")
    search_fields = ("user_key", "experiment__name")
    ordering = ("-created_at", "-id")


@admin.register(Exposure)
class ExposureAdmin(ReadOnlyAdmin):
    list_display = ("id", "experiment", "user_key", "variant_key", "exposed_at")
    search_fields = ("user_key", "experiment__name")
    ordering = ("-exposed_at", "-id")


@admin.register(EvaluationLog)
class EvaluationLogAdmin(ReadOnlyAdmin):
    list_display = ("id", "flag", "user_key", "matched_rule", "latency_ms", "evaluated_at")
    list_filter = ("environment",)
    search_fields = ("user_key", "matched_rule", "flag__key")
    ordering = ("-evaluated_at", "-id")


@admin.register(Audience)
class AudienceAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "name", "rule_logic", "member_count", "updated_at")
    list_filter = ("rule_logic",)
    search_fields = ("name", "description", "project__key")
    ordering = ("project_id", "id")
    readonly_fields = ("member_count", "created_at", "updated_at")


@admin.register(FlagDependency)
class FlagDependencyAdmin(admin.ModelAdmin):
    list_display = ("id", "flag", "depends_on", "relation", "expected_value")
    list_filter = ("relation",)
    search_fields = ("flag__key", "depends_on__key")
    ordering = ("flag_id", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Guardrail)
class GuardrailAdmin(admin.ModelAdmin):
    list_display = (
        "id", "flag", "metric", "comparator", "threshold",
        "window_minutes", "action", "triggered_count", "last_value",
    )
    list_filter = ("action", "comparator")
    search_fields = ("metric", "flag__key")
    ordering = ("flag_id", "id")
    readonly_fields = ("triggered_at", "triggered_count", "last_value", "created_at", "updated_at")


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ("id", "project", "actor_name", "action", "object_type", "object_id", "created_at")
    list_filter = ("object_type", "action")
    search_fields = ("actor_name", "action", "object_type", "note")
    ordering = ("-created_at", "-id")
