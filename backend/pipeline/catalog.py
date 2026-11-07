# -*- coding: utf-8 -*-
"""管道目录：连接器模板、节点类型、聚合函数、转换算子等元信息。

目录既是前端渲染表单的依据，也是后端校验的唯一事实来源：
视图层不允许再写一份节点类型清单，否则前后端一定会漂移。
"""
from __future__ import annotations

from django.db import transaction

from pipeline.models import (CONCURRENCY_POLICIES, CONCURRENCY_POLICY_LABELS,
                             CONNECTION_STATUS, CONNECTION_STATUS_LABELS,
                             CONNECTOR_CAPABILITIES, CONNECTOR_CAPABILITY_LABELS,
                             CONNECTOR_KINDS, CONNECTOR_KIND_LABELS,
                             CREDENTIAL_KINDS, CREDENTIAL_KIND_LABELS,
                             LINEAGE_ENTITY_TYPES, LINEAGE_ENTITY_TYPE_LABELS,
                             LOG_LEVELS, LOG_LEVEL_LABELS, NODE_PORTS,
                             NODE_TYPE_LABELS, NODE_TYPES, PIPELINE_STATUS,
                             PIPELINE_STATUS_LABELS, QUALITY_RULE_TYPE_LABELS,
                             QUALITY_RULE_TYPES, QUALITY_SEVERITY,
                             QUALITY_SEVERITY_LABELS, RUN_STATUS,
                             RUN_STATUS_LABELS, STEP_STATUS, STEP_STATUS_LABELS,
                             TRIGGER_TYPES, TRIGGER_TYPE_LABELS, Connector)

# 单次运行行数上限：同步执行意味着请求线程要扛完整批数据，
# 5000 行是「够用且不会把 gunicorn worker 拖死」的经验值。
MAX_RUN_ROWS = 5000
# 单次接口返回的预览上限，与列表分页上限保持一致
MAX_PAGE_SIZE = 200
# 节点重试上限：再多只会把一次坏配置放大成请求超时
MAX_RETRIES = 5
# 管道超时上限（秒）
MAX_TIMEOUT = 900
# 画像采样的默认行数
DEFAULT_PROFILE_SAMPLE = 1000

AGG_FUNCS = ("count", "count_distinct", "sum", "avg", "min", "max", "first", "last")
AGG_FUNC_LABELS = {
    "count": "计数",
    "count_distinct": "去重计数",
    "sum": "求和",
    "avg": "平均值",
    "min": "最小值",
    "max": "最大值",
    "first": "首个值",
    "last": "末个值",
}

TRANSFORM_OPS = ("rename", "select", "drop", "fill", "cast", "concat",
                 "split", "replace", "lower", "upper", "trim", "prefix")
TRANSFORM_OP_LABELS = {
    "rename": "字段重命名",
    "select": "保留字段",
    "drop": "删除字段",
    "fill": "空值填充",
    "cast": "类型转换",
    "concat": "字段拼接",
    "split": "字段拆分",
    "replace": "文本替换",
    "lower": "转小写",
    "upper": "转大写",
    "trim": "去空白",
    "prefix": "加前缀",
}

JOIN_TYPES = ("inner", "left", "right", "full")
JOIN_TYPE_LABELS = {
    "inner": "内连接",
    "left": "左连接",
    "right": "右连接",
    "full": "全连接",
}

DEDUPE_KEEP = ("first", "last")
DEDUPE_KEEP_LABELS = {"first": "保留首条", "last": "保留末条"}

FIELD_TYPES = ("int", "float", "string", "bool", "date", "datetime", "enum", "json")
FIELD_TYPE_LABELS = {
    "int": "整数",
    "float": "小数",
    "string": "文本",
    "bool": "布尔",
    "date": "日期",
    "datetime": "日期时间",
    "enum": "枚举",
    "json": "JSON",
}

CAST_TYPES = ("string", "int", "float", "bool", "date", "datetime", "json")
CAST_TYPE_LABELS = {
    "string": "文本",
    "int": "整数",
    "float": "小数",
    "bool": "布尔",
    "date": "日期",
    "datetime": "日期时间",
    "json": "JSON",
}

# 每种节点在前端表单里需要暴露的配置字段（也是服务端允许的键）
NODE_TYPE_CATALOG = [
    {
        "type": "source",
        "label": "数据源",
        "ports": NODE_PORTS["source"],
        "description": "读取 HTTP / 数据库 / 文件 / Webhook / 生成器的数据，是 DAG 的唯一入口",
        "fields": [
            {"name": "connector_kind", "type": "enum", "required": True,
             "values": list(CONNECTOR_KINDS), "label": "连接器类型"},
            {"name": "connection_id", "type": "int", "required": False, "label": "连接 ID"},
            {"name": "dataset", "type": "string", "required": False, "label": "数据集 / 表名"},
            {"name": "count", "type": "int", "required": False, "label": "生成行数"},
            {"name": "seed", "type": "int", "required": False, "label": "随机种子"},
        ],
    },
    {
        "type": "transform",
        "label": "结构转换",
        "ports": NODE_PORTS["transform"],
        "description": "重命名 / 保留 / 删除 / 填充 / 类型转换等结构操作",
        "fields": [
            {"name": "operations", "type": "array", "required": True, "label": "操作列表"},
        ],
    },
    {
        "type": "filter",
        "label": "行过滤",
        "ports": NODE_PORTS["filter"],
        "description": "按表达式过滤，pass / fail 两个端口分别输出命中与未命中的行",
        "fields": [
            {"name": "condition", "type": "expression", "required": True, "label": "过滤条件"},
        ],
    },
    {
        "type": "filter",
        "label": "行过滤",
        "ports": NODE_PORTS["filter"],
        "description": "按表达式过滤，pass / fail 两个端口分别输出命中与未命中的行",
        "fields": [
            {"name": "condition", "type": "expression", "required": True, "label": "过滤条件"},
        ],
    },
    {
        "type": "aggregate",
        "label": "聚合",
        "ports": NODE_PORTS["aggregate"],
        "description": "group by + count/sum/avg/min/max 等指标",
        "fields": [
            {"name": "group_by", "type": "array", "required": False, "label": "分组字段"},
            {"name": "metrics", "type": "array", "required": True, "label": "聚合指标"},
        ],
    },
    {
        "type": "join",
        "label": "关联",
        "ports": NODE_PORTS["join"],
        "description": "left / right 两个输入端口的内存关联",
        "fields": [
            {"name": "left_on", "type": "array", "required": True, "label": "左键"},
            {"name": "right_on", "type": "array", "required": True, "label": "右键"},
            {"name": "how", "type": "enum", "required": False,
             "values": list(JOIN_TYPES), "label": "连接方式"},
        ],
    },
    {
        "type": "sort",
        "label": "排序",
        "ports": NODE_PORTS["sort"],
        "description": "多字段排序，数字按数值比较、空值固定在后",
        "fields": [
            {"name": "keys", "type": "array", "required": True, "label": "排序键"},
        ],
    },
    {
        "type": "dedupe",
        "label": "去重",
        "ports": NODE_PORTS["dedupe"],
        "description": "按键去重，可保留首条或末条",
        "fields": [
            {"name": "keys", "type": "array", "required": True, "label": "去重键"},
            {"name": "keep", "type": "enum", "required": False,
             "values": list(DEDUPE_KEEP), "label": "保留策略"},
        ],
    },
    {
        "type": "map",
        "label": "字段映射",
        "ports": NODE_PORTS["map"],
        "description": "源字段 → 目标字段，支持表达式取值与类型转换",
        "fields": [
            {"name": "mappings", "type": "array", "required": True, "label": "映射列表"},
        ],
    },
    {
        "type": "sink",
        "label": "数据落地",
        "ports": NODE_PORTS["sink"],
        "description": "把行写入平台输出表，供预览 / 画像 / 质量检查使用",
        "fields": [
            {"name": "dataset", "type": "string", "required": True, "label": "输出数据集"},
        ],
    },
    {
        "type": "webhook",
        "label": "回调通知",
        "ports": NODE_PORTS["webhook"],
        "description": "模拟向外部 URL 投递结果摘要（只做配置校验与模拟投递）",
        "fields": [
            {"name": "url", "type": "string", "required": True, "label": "回调地址"},
        ],
    },
]

# 去掉重复的 filter 条目（上面为了可读性排了两块，这里按 type 去重）
_seen_types: set[str] = set()
NODE_TYPE_CATALOG = [item for item in NODE_TYPE_CATALOG
                     if not (item["type"] in _seen_types or _seen_types.add(item["type"]))]


def _field(name, kind, label, required=False, default=None, values=None,
           placeholder="", help_text=""):
    """构造配置模板字段，避免五个连接器各写一套长字典。"""
    item = {"name": name, "type": kind, "label": label, "required": required}
    if default is not None:
        item["default"] = default
    if values:
        item["values"] = values
    if placeholder:
        item["placeholder"] = placeholder
    if help_text:
        item["help"] = help_text
    return item


BUILTIN_CONNECTORS = [
    {
        "name": "HTTP JSON 接口",
        "kind": "http",
        "capabilities": ["read", "sample"],
        "description": "通过 GET / POST 拉取 JSON 数据，支持分页参数与超时配置",
        "config_template": {
            "fields": [
                _field("url", "string", "接口地址", True, placeholder="https://api.example.com/orders"),
                _field("method", "enum", "请求方法", False, "GET", ["GET", "POST"]),
                _field("timeout", "int", "超时秒数", False, 10),
                _field("sample_size", "int", "样例行数", False, 5, help_text="模拟执行返回的行数"),
                _field("headers", "json", "请求头", False, {}),
                _field("data_path", "string", "数据路径", False, "data",
                       help_text="响应 JSON 中数组所在的键"),
            ],
        },
    },
    {
        "name": "PostgreSQL 数据库",
        "kind": "database",
        "capabilities": ["read", "write", "sample"],
        "description": "关系型数据库直连配置，真实执行由外部同步器负责，平台内做配置校验与样例生成",
        "config_template": {
            "fields": [
                _field("engine", "enum", "数据库类型", True, "postgresql",
                       ["postgresql", "mysql", "sqlite", "oracle", "mssql"]),
                _field("host", "string", "主机", True, placeholder="127.0.0.1"),
                _field("port", "int", "端口", True, 5432),
                _field("database", "string", "库名", True),
                _field("schema", "string", "模式", False, "public"),
                _field("table", "string", "表名", False),
            ],
        },
    },
    {
        "name": "CSV / JSON 文件",
        "kind": "file",
        "capabilities": ["read", "sample"],
        "description": "从本地目录或对象存储读取结构化文件；也可直接粘贴行数据用于试跑",
        "config_template": {
            "fields": [
                _field("path", "string", "文件路径", True, placeholder="/data/orders.csv"),
                _field("format", "enum", "格式", False, "csv",
                       ["csv", "json", "ndjson", "parquet", "xlsx", "txt"]),
                _field("encoding", "string", "编码", False, "utf-8"),
                _field("has_header", "bool", "含表头", False, True),
            ],
        },
    },
    {
        "name": "Webhook 回调",
        "kind": "webhook",
        "capabilities": ["trigger", "write"],
        "description": "向外部系统推送运行结果，支持重试与签名头（签名值只存引用名）",
        "config_template": {
            "fields": [
                _field("url", "string", "回调地址", True, placeholder="https://hooks.example.com/etl"),
                _field("method", "enum", "方法", False, "POST", ["POST", "PUT"]),
                _field("timeout", "int", "超时秒数", False, 5),
                _field("retry", "int", "重试次数", False, 2),
                _field("signature_header", "string", "签名字段", False, "X-Signature"),
            ],
        },
    },
    {
        "name": "内置数据生成器",
        "kind": "generator",
        "capabilities": ["read", "sample"],
        "description": "按数据集模板生成确定性样例数据，用于联调与演示，不依赖任何外部系统",
        "config_template": {
            "fields": [
                _field("dataset", "enum", "数据集", True, "orders",
                       ["orders", "users", "events", "products", "logs"]),
                _field("count", "int", "行数", False, 20),
                _field("seed", "int", "随机种子", False, 42),
            ],
        },
    },
]


@transaction.atomic
def ensure_builtin_connectors(owner) -> list[Connector]:
    """按需为用户补齐 5 个内置连接器，返回其列表。

    采用 get_or_create + owner 唯一约束：首屏与并发首访都不会产生重复行。
    """
    created = []
    for spec in BUILTIN_CONNECTORS:
        obj, _ = Connector.objects.get_or_create(
            owner=owner,
            name=spec["name"],
            defaults={
                "kind": spec["kind"],
                "capabilities": list(spec["capabilities"]),
                "config_template": spec["config_template"],
                "builtin": True,
                "description": spec["description"],
            },
        )
        created.append(obj)
    return created


def builtin_templates() -> list[dict]:
    """内置连接器模板（纯静态，未落库也能展示）。"""
    return [
        {
            "name": spec["name"],
            "kind": spec["kind"],
            "kind_label": CONNECTOR_KIND_LABELS.get(spec["kind"], spec["kind"]),
            "capabilities": list(spec["capabilities"]),
            "description": spec["description"],
            "config_template": spec["config_template"],
        }
        for spec in BUILTIN_CONNECTORS
    ]


def catalog_payload() -> dict:
    """目录数据：前端据此渲染连接器下拉、节点面板与表达式补全。"""
    return {
        "app": "pipeline",
        "title": "数据集成管道",
        "limits": {
            "max_run_rows": MAX_RUN_ROWS,
            "max_page_size": MAX_PAGE_SIZE,
            "max_retries": MAX_RETRIES,
            "max_timeout": MAX_TIMEOUT,
            "profile_sample": DEFAULT_PROFILE_SAMPLE,
        },
        "connector_kinds": [{"value": k, "label": CONNECTOR_KIND_LABELS[k]}
                            for k in CONNECTOR_KINDS],
        "connector_capabilities": [{"value": c, "label": CONNECTOR_CAPABILITY_LABELS[c]}
                                   for c in CONNECTOR_CAPABILITIES],
        "connection_status": [{"value": s, "label": CONNECTION_STATUS_LABELS[s]}
                              for s in CONNECTION_STATUS],
        "credential_kinds": [{"value": k, "label": CREDENTIAL_KIND_LABELS[k]}
                             for k in CREDENTIAL_KINDS],
        "pipeline_status": [{"value": s, "label": PIPELINE_STATUS_LABELS[s]}
                            for s in PIPELINE_STATUS],
        "concurrency_policies": [{"value": c, "label": CONCURRENCY_POLICY_LABELS[c]}
                                 for c in CONCURRENCY_POLICIES],
        "node_types": [{"value": t, "label": NODE_TYPE_LABELS[t], "ports": NODE_PORTS[t]}
                       for t in NODE_TYPES],
        "node_panel": NODE_TYPE_CATALOG,
        "field_types": [{"value": t, "label": FIELD_TYPE_LABELS[t]} for t in FIELD_TYPES],
        "cast_types": [{"value": t, "label": CAST_TYPE_LABELS[t]} for t in CAST_TYPES],
        "transform_ops": [{"value": op, "label": TRANSFORM_OP_LABELS[op]}
                          for op in TRANSFORM_OPS],
        "aggregate_funcs": [{"value": f, "label": AGG_FUNC_LABELS[f]} for f in AGG_FUNCS],
        "join_types": [{"value": j, "label": JOIN_TYPE_LABELS[j]} for j in JOIN_TYPES],
        "dedupe_keep": [{"value": k, "label": DEDUPE_KEEP_LABELS[k]} for k in DEDUPE_KEEP],
        "trigger_types": [{"value": t, "label": TRIGGER_TYPE_LABELS[t]} for t in TRIGGER_TYPES],
        "run_status": [{"value": s, "label": RUN_STATUS_LABELS[s]} for s in RUN_STATUS],
        "step_status": [{"value": s, "label": STEP_STATUS_LABELS[s]} for s in STEP_STATUS],
        "log_levels": [{"value": lv, "label": LOG_LEVEL_LABELS[lv]} for lv in LOG_LEVELS],
        "quality_rule_types": [{"value": t, "label": QUALITY_RULE_TYPE_LABELS[t]}
                               for t in QUALITY_RULE_TYPES],
        "quality_severity": [{"value": s, "label": QUALITY_SEVERITY_LABELS[s]}
                             for s in QUALITY_SEVERITY],
        "lineage_entity_types": [{"value": t, "label": LINEAGE_ENTITY_TYPE_LABELS[t]}
                                 for t in LINEAGE_ENTITY_TYPES],
        "connector_templates": builtin_templates(),
        "datasets": list_dataset_names(),
    }


def list_dataset_names() -> list[dict]:
    """内置数据集清单（生成器可用）。"""
    from pipeline.generators import DATASET_SCHEMAS

    return [
        {
            "name": name,
            "label": schema["label"],
            "fields": [{"name": f["name"], "type": f["type"]} for f in schema["fields"]],
        }
        for name, schema in DATASET_SCHEMAS.items()
    ]
