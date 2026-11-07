# -*- coding: utf-8 -*-
"""流程引擎 · 目录接口（能力域元信息）。

前端流程工作台启动时先拉这个接口，拿到节点类型、状态枚举、表达式语法与
全部端点清单，避免把枚举硬编码在页面里（后端一改前端就漂移）。
"""
from django.db.models import Count

from devtools.common import endpoint, ok

from core.scoping import scope_queryset
from workflow import services
from workflow.models import (
    ASSIGNEE_TYPE_CHOICES,
    DEFINITION_STATUS_CHOICES,
    DELEGATION_SCOPE_CHOICES,
    INSTANCE_STATUS_CHOICES,
    NODE_TYPE_CHOICES,
    PRIORITY_CHOICES,
    TASK_ACTION_CHOICES,
    TASK_STATUS_CHOICES,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowTask,
)
from workflow.serializers import now_iso

# 能力域：与 urls.py 的分组保持一致，前端可据此渲染导航
CAPABILITY_DOMAINS = [
    {"key": "definition", "name": "流程定义", "description": "定义、版本、发布与导入导出",
     "endpoint_prefixes": ["definitions", "versions"]},
    {"key": "design", "name": "流程设计", "description": "节点、连线与整图保存/校验",
     "endpoint_prefixes": ["nodes", "transitions", "graph"]},
    {"key": "runtime", "name": "流程运行", "description": "发起、实例、变量、评论与回放",
     "endpoint_prefixes": ["instances"]},
    {"key": "task", "name": "任务办理", "description": "待办、已办、认领、办理、转办与委派",
     "endpoint_prefixes": ["tasks"]},
    {"key": "monitor", "name": "运行监控", "description": "SLA 扫描、指标、瓶颈与趋势",
     "endpoint_prefixes": ["monitor", "audit"]},
    {"key": "collaboration", "name": "协作配置", "description": "委托、通知、Webhook 与 SLA 策略",
     "endpoint_prefixes": ["delegations", "notifications", "webhooks", "sla-policies"]},
]

EXPRESSION_GUIDE = {
    "operators": ["==", "!=", ">", ">=", "<", "<=", "and", "or", "not", "in", "not in",
                  "+", "-", "*", "/", "%"],
    "literals": ["数字", "字符串（单/双引号）", "true/false", "null", "列表 [1, 2, 3]"],
    "variables": "支持点路径与下标：amount、form.days、items[0].qty、payload.approved",
    "examples": [
        {"expression": 'amount >= 5000 and category == "采购"', "meaning": "金额达标且属于采购类"},
        {"expression": 'priority in ["high", "urgent"]', "meaning": "高优先级或紧急"},
        {"expression": "not starter_is_manager", "meaning": "发起人不是主管"},
        {"expression": 'form.days > 3', "meaning": "表单里的天数大于 3（字符串数字自动转数值）"},
    ],
    "safety": "解释执行，不使用 eval/exec；长度上限 4000 字符、600 个词法单元、64 层嵌套",
}


def build_catalog(user):
    """构造目录数据：路由层拿到后再注入端点清单，避免循环依赖。"""
    definitions = scope_queryset(WorkflowDefinition.objects.all(), user)
    instances = services.instance_queryset_for(user)
    tasks = WorkflowTask.objects.filter(instance__in=instances)
    definition_by_status = {
        row["status"]: row["c"] for row in definitions.values("status").annotate(c=Count("id"))
    }
    instance_by_status = {
        row["status"]: row["c"] for row in instances.values("status").annotate(c=Count("id"))
    }
    return {
        "name": "流程引擎",
        "version": "1.0",
        "generated_at": now_iso(),
        "domains": CAPABILITY_DOMAINS,
        "node_types": [{"value": v, "label": label} for v, label in NODE_TYPE_CHOICES],
        "assignee_types": [{"value": v, "label": label} for v, label in ASSIGNEE_TYPE_CHOICES],
        "definition_statuses": [{"value": v, "label": label} for v, label in DEFINITION_STATUS_CHOICES],
        "instance_statuses": [{"value": v, "label": label} for v, label in INSTANCE_STATUS_CHOICES],
        "task_statuses": [{"value": v, "label": label} for v, label in TASK_STATUS_CHOICES],
        "task_actions": [{"value": v, "label": label} for v, label in TASK_ACTION_CHOICES],
        "priorities": [{"value": v, "label": label} for v, label in PRIORITY_CHOICES],
        "delegation_scopes": [{"value": v, "label": label} for v, label in DELEGATION_SCOPE_CHOICES],
        "expression": EXPRESSION_GUIDE,
        "pagination": {"page_size_default": 20, "page_size_max": 200,
                       "response_shape": ["items", "count", "page", "page_size"]},
        "counts": {
            "definitions": sum(definition_by_status.values()),
            "definitions_by_status": definition_by_status,
            "instances": sum(instance_by_status.values()),
            "instances_by_status": instance_by_status,
            "open_tasks": tasks.filter(status__in=("pending", "claimed")).count(),
            "overdue_tasks": tasks.filter(status__in=("pending", "claimed"), is_overdue=True).count(),
        },
    }


@endpoint(("GET",))
def catalog(request):
    """流程引擎目录：能力域、枚举、表达式语法与当前用户的规模统计。"""
    return ok(build_catalog(request.user))
