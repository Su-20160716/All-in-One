# -*- coding: utf-8 -*-
"""contracts 目录接口：应用元信息 + 枚举 + 业务阈值说明。

目录接口是前端「一次拉全」的入口：枚举、状态机、审批阈值、提醒档位都从这里取，
避免各页面自己硬编码枚举中文名，改一处漏一处。
"""
from devtools.common import endpoint, ok
from contracts import services
from contracts.common import CATALOG_ENUMS
from contracts.models import (AMENDMENT_STATUS, CONTRACT_STATUS, CONTRACT_TYPES,
                              EXPIRY_REMIND_STAGES, OBLIGATION_CYCLES,
                              OBLIGATION_STATUS, PARTY_ROLES, PAYMENT_STATUS,
                              RISK_LEVELS, RISK_STATUS, SIGNATURE_METHODS,
                              TEMPLATE_STATUS, Contract, ContractReminder,
                              ContractObligation, ContractRisk,
                              ContractSignature, ContractTemplate)

FEATURE_LIST = [
    {"key": "templates", "name": "合同模板与标准条款", "endpoints": 12},
    {"key": "contracts", "name": "合同台账与状态机", "endpoints": 16},
    {"key": "versions", "name": "版本快照与条款对比", "endpoints": 5},
    {"key": "obligations", "name": "履约义务与排期", "endpoints": 9},
    {"key": "milestones", "name": "里程碑跟踪", "endpoints": 4},
    {"key": "amendments", "name": "变更单与审批", "endpoints": 6},
    {"key": "signatures", "name": "签署指纹", "endpoints": 3},
    {"key": "payments", "name": "付款计划与逾期", "endpoints": 6},
    {"key": "renewals", "name": "续约跟进", "endpoints": 5},
    {"key": "risks", "name": "风险项与评分", "endpoints": 4},
    {"key": "reminders", "name": "到期扫描与提醒", "endpoints": 2},
    {"key": "stats", "name": "组合统计与健康度", "endpoints": 6},
]


def catalog_data():
    """目录数据（不含接口清单，接口清单由 urls 里的包装视图注入）。"""
    return {
        "app": "contracts",
        "name": "合同全生命周期",
        "version": "1.0",
        "description": "模板 → 起草 → 审批 → 签署 → 履约 → 付款 → 续约/终止 → 归档",
        "features": FEATURE_LIST,
        "views": [
            {"key": "ledger", "name": "合同台账"},
            {"key": "templates", "name": "模板与条款库"},
            {"key": "execution", "name": "履约跟踪"},
            {"key": "finance", "name": "付款与续约"},
            {"key": "risk", "name": "风险与提醒"},
        ],
        "amount_bands": [
            {"up_to": "100000", "level": 1, "route": "部门主管"},
            {"up_to": "1000000", "level": 2, "route": "部门主管 → 法务审核"},
            {"up_to": "5000000", "level": 3,
             "route": "部门主管 → 法务审核 → 财务总监"},
            {"up_to": None, "level": 4,
             "route": "部门主管 → 法务审核 → 财务总监 → 总经理"},
        ],
        "expiry_stages": list(EXPIRY_REMIND_STAGES),
        "status_flow": {
            "draft": ["reviewing"],
            "reviewing": ["approved", "draft"],
            "approved": ["signing"],
            "signing": ["active", "terminated"],
            "active": ["expiring", "expired", "terminated", "completed"],
            "expiring": ["active", "expired", "terminated", "completed"],
            "expired": ["completed", "archived"],
            "terminated": ["archived"],
            "completed": ["archived"],
            "archived": [],
        },
        "enums": CATALOG_ENUMS,
    }


@endpoint(("GET",))
def meta(request):
    """返回全部枚举与阈值说明（前端下拉与状态机的唯一来源）。"""
    return ok({
        "enums": CATALOG_ENUMS,
        "status_keys": list(CONTRACT_STATUS),
        "contract_type_keys": list(CONTRACT_TYPES),
        "obligation_cycle_keys": list(OBLIGATION_CYCLES),
        "obligation_status_keys": list(OBLIGATION_STATUS),
        "payment_status_keys": list(PAYMENT_STATUS),
        "risk_level_keys": list(RISK_LEVELS),
        "risk_status_keys": list(RISK_STATUS),
        "signature_method_keys": list(SIGNATURE_METHODS),
        "party_role_keys": list(PARTY_ROLES),
        "template_status_keys": list(TEMPLATE_STATUS),
        "amendment_status_keys": list(AMENDMENT_STATUS),
        "expiry_stages": list(EXPIRY_REMIND_STAGES),
        "risk_keywords": services.CLAUSE_RISK_KEYWORDS,
        "approval_thresholds": [
            {"up_to": str(limit) if limit else None, "level": level,
             "label": label}
            for limit, level, label in services.APPROVAL_THRESHOLDS
        ],
    })


@endpoint(("GET",))
def counts(request):
    """数据规模概览：各子域数量，前端工作台角标直接使用。"""
    from core.scoping import scope_queryset

    contracts = scope_queryset(Contract.objects.all(), request.user)
    return ok({
        "contracts": contracts.count(),
        "templates": ContractTemplate.objects.filter(owner=request.user).count(),
        "obligations": ContractObligation.objects.filter(
            contract__in=contracts).count(),
        "open_risks": ContractRisk.objects.filter(
            contract__in=contracts).exclude(status__in=("closed", "accepted")).count(),
        "pending_signatures": ContractSignature.objects.filter(
            contract__in=contracts, status="pending").count(),
        "reminders": ContractReminder.objects.filter(
            contract__in=contracts).count(),
    })
