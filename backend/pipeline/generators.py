# -*- coding: utf-8 -*-
"""数据源模拟与连接配置校验。

平台不联网、也不允许任意 SQL / HTTP 直连（安全边界），但 ETL 的
「配置是否正确」必须在保存前就能验证，否则错误只能在生产运行时暴露。
因此这里做两件事：

1. **配置校验**：按连接器类型逐项校验 URL / 端口 / 文件格式等，
   错误消息带字段名，前端可直接定位；
2. **模拟执行**：用确定性伪随机数生成结构正确的样例行（同一 seed
   结果完全一致），下游的过滤、聚合、落地、质量检查都在真实数据上跑。

真实 HTTP / SQL 客户端由部署侧的同步器接入，本模块不发起任何网络请求。
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta

from pipeline.catalog import MAX_RUN_ROWS
from pipeline.expressions import cast_value

# ---------------------------------------------------------------------------
# 内置数据集模板：字段名与业务场景对齐，方便前端直接演示
# ---------------------------------------------------------------------------

DATASET_SCHEMAS = {
    "orders": {
        "label": "订单",
        "fields": [
            {"name": "order_id", "type": "string", "prefix": "ORD"},
            {"name": "customer", "type": "string"},
            {"name": "city", "type": "enum", "values": ["上海", "北京", "深圳", "杭州", "成都"]},
            {"name": "status", "type": "enum", "values": ["paid", "pending", "refunded", "cancelled"]},
            {"name": "amount", "type": "float", "min": 10, "max": 5000},
            {"name": "qty", "type": "int", "min": 1, "max": 8},
            {"name": "paid", "type": "bool"},
            {"name": "created_at", "type": "datetime"},
        ],
    },
    "users": {
        "label": "用户",
        "fields": [
            {"name": "user_id", "type": "string", "prefix": "U"},
            {"name": "name", "type": "string"},
            {"name": "email", "type": "string"},
            {"name": "city", "type": "enum", "values": ["上海", "北京", "深圳", "杭州"]},
            {"name": "age", "type": "int", "min": 18, "max": 65},
            {"name": "vip", "type": "bool"},
            {"name": "signup_date", "type": "date"},
        ],
    },
    "events": {
        "label": "埋点事件",
        "fields": [
            {"name": "event_id", "type": "string", "prefix": "EVT"},
            {"name": "user_id", "type": "string", "prefix": "U"},
            {"name": "event_type", "type": "enum", "values": ["view", "click", "add_cart", "pay"]},
            {"name": "page", "type": "string"},
            {"name": "duration_ms", "type": "int", "min": 5, "max": 9000},
            {"name": "occurred_at", "type": "datetime"},
        ],
    },
    "products": {
        "label": "商品",
        "fields": [
            {"name": "sku", "type": "string", "prefix": "SKU"},
            {"name": "name", "type": "string"},
            {"name": "category", "type": "enum", "values": ["数码", "家居", "服饰", "食品"]},
            {"name": "price", "type": "float", "min": 5, "max": 3000},
            {"name": "stock", "type": "int", "min": 0, "max": 500},
            {"name": "active", "type": "bool"},
        ],
    },
    "logs": {
        "label": "服务日志",
        "fields": [
            {"name": "log_id", "type": "string", "prefix": "LOG"},
            {"name": "level", "type": "enum", "values": ["debug", "info", "warning", "error"]},
            {"name": "service", "type": "enum", "values": ["gateway", "order", "payment", "search"]},
            {"name": "message", "type": "string"},
            {"name": "latency_ms", "type": "int", "min": 1, "max": 3000},
            {"name": "logged_at", "type": "datetime"},
        ],
    },
}

_WORD_POOL = ("alpha", "beta", "gamma", "delta", "echo", "nova", "orbit", "pulse",
              "river", "solar", "terra", "vivid", "wave", "zen", "atlas", "comet")
_NAME_POOL = ("张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十")
_PAGE_POOL = ("/home", "/search", "/detail", "/cart", "/checkout", "/profile")

_BASE_DT = datetime(2024, 1, 1, 8, 0, 0)


def _stable_seed(value) -> int:
    """把任意配置文本映射成稳定 seed：同样配置每次生成同样样例。"""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _pick(rng: random.Random, values):
    return values[rng.randrange(len(values))]


def _gen_value(rng: random.Random, field: dict, index: int, dataset: str):
    """按字段定义生成一个值；所有分支都保证类型与声明一致。"""
    kind = (field.get("type") or "string").lower()
    name = field.get("name") or "field"
    prefix = field.get("prefix") or name[:3].upper()

    if kind == "int":
        low = int(field.get("min", 1))
        high = int(field.get("max", 1000))
        if high < low:
            low, high = high, low
        return rng.randint(low, high)
    if kind == "float":
        low = float(field.get("min", 0))
        high = float(field.get("max", 1000))
        if high < low:
            low, high = high, low
        return round(rng.uniform(low, high), 2)
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "enum":
        values = field.get("values") or ["a", "b", "c"]
        return _pick(rng, values)
    if kind == "date":
        return (_BASE_DT + timedelta(days=rng.randint(0, 120))).date().isoformat()
    if kind == "datetime":
        return (_BASE_DT + timedelta(minutes=rng.randint(0, 60 * 24 * 120))).isoformat()
    if kind == "json":
        return {"k": _pick(rng, _WORD_POOL), "n": rng.randint(1, 9)}
    if field.get("format") == "email" or name.endswith("email"):
        return f"{_pick(rng, _WORD_POOL)}{rng.randint(1, 99)}@example.com"
    if field.get("unique"):
        return f"{prefix}-{index + 1:05d}"
    if name in ("name", "customer", "user_name"):
        return _pick(rng, _NAME_POOL)
    if name in ("page", "url"):
        return _pick(rng, _PAGE_POOL)
    if name.startswith("message"):
        return f"{_pick(rng, _WORD_POOL)} {_pick(rng, _WORD_POOL)} {rng.randint(100, 999)}"
    return f"{prefix}-{rng.randint(1000, 9999)}-{index % 97}"


def generate_rows(spec: dict | None, limit: int = MAX_RUN_ROWS) -> list[dict]:
    """生成样例行（确定性）。

    spec 支持：
    - ``inline_rows`` / ``rows``：直接给定的行（文件连接器粘贴数据、API 调试）；
    - ``dataset``：内置数据集名，缺省 orders；
    - ``count``：行数；
    - ``seed``：随机种子；
    - ``fields``：覆盖数据集字段定义；
    - ``null_rate``：按比例注入 None（用于质量规则演示）。
    """
    spec = spec or {}
    if not isinstance(spec, dict):
        raise ValueError("数据源配置必须是对象")

    inline = spec.get("inline_rows")
    if inline is None:
        inline = spec.get("rows")
    if inline is not None:
        if not isinstance(inline, list) or any(not isinstance(r, dict) for r in inline):
            raise ValueError("inline_rows 必须是对象数组")
        if len(inline) > limit:
            raise ValueError(f"单次运行行数上限 {limit}，当前 {len(inline)} 行")
        return [dict(row) for row in inline]

    dataset = str(spec.get("dataset") or "orders")
    schema = DATASET_SCHEMAS.get(dataset)
    if schema is None:
        raise ValueError(f"未知内置数据集：{dataset}")
    fields = spec.get("fields") or schema["fields"]
    if not isinstance(fields, list) or not fields:
        raise ValueError("字段定义必须是非空数组")

    count = _int_value(spec.get("count", 20), "count", minimum=1)
    if count > limit:
        raise ValueError(f"单次运行行数上限 {limit}，当前请求 {count} 行")
    seed = _int_value(spec.get("seed", 42), "seed")
    rng = random.Random(seed)
    null_rate = float(spec.get("null_rate") or 0)
    null_rate = max(0.0, min(0.9, null_rate))

    rows: list[dict] = []
    for index in range(count):
        row: dict = {}
        for field in fields:
            if not isinstance(field, dict) or not field.get("name"):
                raise ValueError("字段定义必须是包含 name 的对象")
            value = _gen_value(rng, field, index, dataset)
            if null_rate and rng.random() < null_rate:
                value = None
            row[str(field["name"])] = value
        rows.append(row)
    return rows


def _int_value(value, name: str, minimum: int | None = None,
               maximum: int | None = None) -> int:
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name} 必须是整数")
    if minimum is not None and num < minimum:
        raise ValueError(f"参数 {name} 不能小于 {minimum}")
    if maximum is not None and num > maximum:
        raise ValueError(f"参数 {name} 不能大于 {maximum}")
    return num


# ---------------------------------------------------------------------------
# 连接配置校验
# ---------------------------------------------------------------------------

_DB_ENGINES = ("postgresql", "mysql", "sqlite", "oracle", "mssql")
_FILE_FORMATS = ("csv", "json", "ndjson", "parquet", "xlsx", "txt")


def _require(config: dict, key: str, label: str) -> str:
    value = config.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"连接配置缺少{label}（{key}）")
    return str(value).strip()


def _check_url(url: str, label: str = "接口地址") -> str:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"{label}必须以 http:// 或 https:// 开头")
    if len(url) > 500:
        raise ValueError(f"{label}长度不能超过 500 字符")
    return url


def validate_connection_config(kind: str, config: dict) -> dict:
    """按连接器类型校验配置，返回归一化后的配置副本。"""
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("连接配置必须是 JSON 对象")
    config = dict(config)

    if kind == "http":
        url = _check_url(_require(config, "url", "接口地址"))
        method = str(config.get("method") or "GET").upper()
        if method not in ("GET", "POST"):
            raise ValueError("HTTP 方法只支持 GET / POST")
        timeout = _int_value(config.get("timeout", 10), "timeout", 1, 120)
        sample_size = _int_value(config.get("sample_size", 5), "sample_size",
                                 1, MAX_RUN_ROWS)
        if "headers" in config and not isinstance(config["headers"], dict):
            raise ValueError("请求头必须是对象")
        return {**config, "url": url, "method": method, "timeout": timeout,
                "sample_size": sample_size}

    if kind == "database":
        engine = str(config.get("engine") or "postgresql").lower()
        if engine not in _DB_ENGINES:
            raise ValueError(f"数据库类型只支持：{', '.join(_DB_ENGINES)}")
        database = _require(config, "database", "库名")
        if engine != "sqlite":
            _require(config, "host", "主机")
            port = _int_value(config.get("port", 5432), "port", 1, 65535)
        else:
            port = 0
        table = config.get("table") or ""
        if table and not isinstance(table, str):
            raise ValueError("表名必须是字符串")
        return {**config, "engine": engine, "database": database,
                "host": config.get("host") or "", "port": port,
                "table": table.strip()}

    if kind == "file":
        path = _require(config, "path", "文件路径")
        fmt = str(config.get("format") or "csv").lower()
        if fmt not in _FILE_FORMATS:
            raise ValueError(f"文件格式只支持：{', '.join(_FILE_FORMATS)}")
        encoding = str(config.get("encoding") or "utf-8")
        if len(encoding) > 30:
            raise ValueError("编码名称过长")
        if "has_header" in config and not isinstance(config["has_header"], bool):
            raise ValueError("has_header 必须是布尔值")
        return {**config, "path": path, "format": fmt, "encoding": encoding}

    if kind == "webhook":
        url = _check_url(_require(config, "url", "回调地址"), "回调地址")
        method = str(config.get("method") or "POST").upper()
        if method not in ("POST", "PUT"):
            raise ValueError("Webhook 方法只支持 POST / PUT")
        timeout = _int_value(config.get("timeout", 5), "timeout", 1, 60)
        retry = _int_value(config.get("retry", 2), "retry", 0, 5)
        return {**config, "url": url, "method": method,
                "timeout": timeout, "retry": retry}

    if kind == "generator":
        dataset = str(config.get("dataset") or "orders")
        if dataset not in DATASET_SCHEMAS:
            raise ValueError(f"未知内置数据集：{dataset}")
        count = _int_value(config.get("count", 20), "count", 1, MAX_RUN_ROWS)
        seed = _int_value(config.get("seed", 42), "seed")
        return {**config, "dataset": dataset, "count": count, "seed": seed}

    raise ValueError(f"未知连接器类型：{kind}")


# ---------------------------------------------------------------------------
# 模拟执行：不发起网络 / SQL，返回结构正确的样例行
# ---------------------------------------------------------------------------


def simulate_http_rows(config: dict, limit: int = MAX_RUN_ROWS) -> dict:
    """模拟 HTTP 拉取：按 sample_size 生成样例行，并给出模拟状态码 / 延迟。"""
    url = str(config.get("url") or "")
    count = _int_value(config.get("sample_size", 5), "sample_size", 1, limit)
    rng = random.Random(_stable_seed(f"http:{url}"))
    fields = [
        {"name": "id", "type": "string", "prefix": "API", "unique": True},
        {"name": "status", "type": "enum", "values": ["ok", "pending", "error"]},
        {"name": "amount", "type": "float", "min": 1, "max": 999},
        {"name": "created_at", "type": "datetime"},
    ]
    rows = [{f["name"]: _gen_value(rng, f, i, "http") for f in fields}
            for i in range(count)]
    latency = 20 + _stable_seed(url) % 280
    return {
        "rows": rows,
        "meta": {
            "mode": "simulated",
            "url": url,
            "method": str(config.get("method") or "GET").upper(),
            "status_code": 200,
            "latency_ms": latency,
            "row_count": len(rows),
        },
    }


def simulate_database_rows(config: dict, limit: int = MAX_RUN_ROWS) -> dict:
    """模拟数据库查询：按表名稳定生成行，表名不同数据不同。"""
    table = str(config.get("table") or "records")
    count = _int_value(config.get("sample_size", 5), "sample_size", 1, limit)
    rng = random.Random(_stable_seed(f"db:{config.get('database')}:{table}"))
    columns = config.get("columns") or ["id", "code", "value", "updated_at"]
    if not isinstance(columns, list) or not columns:
        raise ValueError("columns 必须是非空数组")
    rows = []
    for i in range(count):
        row = {}
        for col in columns:
            col = str(col)
            if col.endswith("_at") or col.endswith("_time"):
                row[col] = (_BASE_DT + timedelta(hours=rng.randint(0, 720))).isoformat()
            elif col in ("id", "code", "name"):
                row[col] = f"{table}-{i + 1:04d}"
            else:
                row[col] = round(rng.uniform(1, 1000), 2)
        rows.append(row)
    return {
        "rows": rows,
        "meta": {
            "mode": "simulated",
            "engine": config.get("engine"),
            "table": table,
            "row_count": len(rows),
            "latency_ms": 15 + _stable_seed(table) % 200,
        },
    }


def simulate_file_rows(config: dict, limit: int = MAX_RUN_ROWS) -> dict:
    """模拟文件读取：优先使用粘贴的 inline_rows，否则按路径稳定生成。"""
    inline = config.get("inline_rows")
    path = str(config.get("path") or "inline")
    if inline is not None:
        rows = generate_rows({"inline_rows": inline}, limit)
    else:
        count = _int_value(config.get("sample_size", 4), "sample_size", 1, min(limit, 200))
        rng = random.Random(_stable_seed(f"file:{path}"))
        fields = [
            {"name": "line_no", "type": "int", "min": 1, "max": 9999},
            {"name": "sku", "type": "string", "prefix": "SKU"},
            {"name": "qty", "type": "int", "min": 1, "max": 50},
            {"name": "price", "type": "float", "min": 1, "max": 500},
        ]
        rows = [{f["name"]: _gen_value(rng, f, i, "file") for f in fields}
                for i in range(count)]
    return {
        "rows": rows,
        "meta": {
            "mode": "simulated",
            "path": path,
            "format": config.get("format") or "csv",
            "row_count": len(rows),
        },
    }


def simulate_generator_rows(config: dict, limit: int = MAX_RUN_ROWS) -> dict:
    """模拟内置生成器：直接复用 generate_rows，保证与真实运行同源。"""
    rows = generate_rows(config, limit)
    return {"rows": rows, "meta": {"mode": "simulated", "dataset": config.get("dataset"),
                                   "row_count": len(rows)}}


def source_rows(node_config: dict, limit: int = MAX_RUN_ROWS) -> dict:
    """source 节点取数统一入口：按 connector_kind 分发到对应模拟器。"""
    if not isinstance(node_config, dict):
        raise ValueError("source 节点配置必须是对象")
    kind = str(node_config.get("connector_kind") or "generator")
    if kind == "http":
        return simulate_http_rows(node_config, limit)
    if kind == "database":
        return simulate_database_rows(node_config, limit)
    if kind == "file":
        return simulate_file_rows(node_config, limit)
    if kind == "webhook":
        # Webhook 作为数据源时代表「外部推送过来的行」，用 inline_rows 承载
        return simulate_file_rows({**node_config, "path": "webhook"}, limit)
    if kind == "generator":
        return simulate_generator_rows(node_config, limit)
    raise ValueError(f"未知连接器类型：{kind}")


def estimate_source_rows(node_config: dict) -> int:
    """运行前的行数估算：用于在 400 阶段就拦住超限请求。"""
    if not isinstance(node_config, dict):
        return 0
    kind = str(node_config.get("connector_kind") or "generator")
    if kind == "generator":
        try:
            return int(float(node_config.get("count", 20)))
        except (TypeError, ValueError):
            return 20
    if kind == "http":
        return int(float(node_config.get("sample_size", 5) or 5))
    if kind in ("file", "webhook"):
        inline = node_config.get("inline_rows")
        if isinstance(inline, list):
            return len(inline)
        return int(float(node_config.get("sample_size", 4) or 4))
    if kind == "database":
        return int(float(node_config.get("sample_size", 5) or 5))
    return 0


def mark_connection_error(connection, message: str) -> None:
    """记录测试失败：状态置 error + 最近错误，便于列表一眼看出坏连接。"""
    from django.utils import timezone

    connection.status = "error"
    connection.last_tested_at = timezone.now()
    connection.last_error = str(message)[:500]
    connection.save(update_fields=["status", "last_tested_at", "last_error", "updated_at"])


def test_connection(connection) -> dict:
    """模拟测试连接：校验配置 + 返回样例，不发起真实网络 / SQL。"""
    from django.utils import timezone

    kind = connection.connector.kind if connection.connector_id else ""
    config = validate_connection_config(kind, connection.config or {})
    sample = source_rows({**config, "connector_kind": kind}, limit=50)
    rows = sample.get("rows") or []
    latency = int((sample.get("meta") or {}).get("latency_ms") or 0)
    connection.config = config
    connection.status = "active"
    connection.last_tested_at = timezone.now()
    connection.last_error = ""
    connection.save(update_fields=["config", "status", "last_tested_at",
                                   "last_error", "updated_at"])
    return {
        "connection_id": connection.id,
        "status": "success",
        "latency_ms": latency,
        "row_count": len(rows),
        "sample": rows[:5],
        "fields": list(rows[0].keys()) if rows else [],
        "meta": sample.get("meta") or {},
        "message": "连接配置校验通过（模拟执行，未发起真实网络请求）",
    }


def simulate_webhook_delivery(url: str, payload: dict, method: str = "POST") -> dict:
    """模拟 Webhook 投递：返回固定成功响应，延迟由 URL 稳定推导。"""
    _check_url(url, "回调地址")
    if method not in ("POST", "PUT"):
        raise ValueError("Webhook 方法只支持 POST / PUT")
    safe_payload = payload if isinstance(payload, dict) else {}
    return {
        "mode": "simulated",
        "url": url,
        "method": method,
        "status_code": 202,
        "latency_ms": 10 + _stable_seed(f"{url}:{len(safe_payload)}") % 90,
        "accepted": True,
    }


def cast_row(row: dict, casts: dict) -> dict:
    """按 {字段: 类型} 批量转型，供连接器输出规范化使用。"""
    if not isinstance(row, dict) or not casts:
        return dict(row or {})
    out = dict(row)
    for field, cast in casts.items():
        if field in out:
            out[field] = cast_value(out[field], cast)
    return out


def today_text() -> str:
    """今天的 ISO 日期（样例数据与调度共用口径）。"""
    return date.today().isoformat()
