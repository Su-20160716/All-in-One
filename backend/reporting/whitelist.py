# -*- coding: utf-8 -*-
"""模型白名单与字段路径解析（报表取数的唯一入口）。

为什么需要白名单
----------------
数据集/报表是**用户可编辑的配置**。如果允许配置里写「Python import 路径」
或「SQL 片段」，等于把任意代码执行 / 任意 SQL 交给前端表单。这里的做法：

1. 只认 ``app_label.ModelName`` 形式的标签，且该 app 必须是
   ``settings.INSTALLED_APPS`` 里的**本地应用**（名字不含点，且源码目录在
   项目 BASE_DIR 下）——第三方与 django.contrib 全部拒绝；
2. 用 ``django.apps.apps.get_model`` 解析，不用 ``importlib``，
   解析不到的标签直接 ValueError；
3. 字段路径逐段走 ``Model._meta.get_field`` 校验，只有真实存在的关系/
   具体字段/JSON 键才放行；
4. 表达式的 SQL 全部由 ORM 生成（F / Cast / Trunc / 聚合函数），
   本模块不拼接任何字符串成 SQL。

白名单结果做进程内缓存（建模静态不变），测试里用
``clear_model_cache()`` 重置，避免 TestCase 之间互相影响。
"""
from functools import lru_cache

from django.apps import apps
from django.conf import settings
from django.db.models import F, FileField, FloatField, JSONField
from django.db.models.fields import (
    AutoField, BigIntegerField, BinaryField, BooleanField, CharField, DateField,
    DateTimeField, DecimalField, EmailField, FloatField as FloatFieldModel,
    IntegerField, PositiveBigIntegerField, PositiveIntegerField,
    PositiveSmallIntegerField, SlugField, SmallIntegerField, TextField,
    TimeField, URLField, UUIDField,
)
from django.db.models.functions import Cast

# 本应用自身不进白名单：报表工具不拿报表元数据做演示数据集，
# 免得「删数据集的报表」这类自引用把演示数据搅乱。
EXCLUDED_APPS = {"reporting"}

# 文件类字段不暴露：白名单一旦包含 FileField，前端就能把别人的附件路径
# 当普通列导出来，绕过 files 应用自己的权限校验。
EXCLUDED_FIELD_CLASSES = (FileField, BinaryField)

MAX_PATH_DEPTH = 4  # 关系跳数上限：再深基本是配置写错，且 SQL JOIN 会爆


def _is_local_app(cfg):
    """判断 AppConfig 是否是「本地应用」。

    三条同时满足：名字不含点（排除 django.contrib.* / rest_framework.* 等）、
    不是本应用、源码目录在 BASE_DIR 之内（排除 site-packages 里的第三方 app）。
    """
    name = cfg.name or ""
    if not name or "." in name or name in EXCLUDED_APPS:
        return False
    try:
        base = str(getattr(settings, "BASE_DIR", "") or "")
        path = str(cfg.path or "")
    except Exception:  # noqa: BLE001 —— 个别 app 拿不到 path 时按非本地处理
        return False
    if not base or not path:
        return True
    return path.startswith(base)


def _model_type(field):
    """把 Django 字段映射成报表字段类型（前端按类型选聚合/格式化）。"""
    if getattr(field, "is_relation", False):
        return "string"
    if isinstance(field, BooleanField):
        return "bool"
    if isinstance(field, DateTimeField):
        return "datetime"
    if isinstance(field, DateField):
        return "date"
    if isinstance(field, TimeField):
        return "string"
    if isinstance(field, DecimalField):
        return "decimal"
    if isinstance(field, (FloatFieldModel,)):
        return "number"
    if isinstance(field, (IntegerField, SmallIntegerField, BigIntegerField,
                          PositiveIntegerField, PositiveSmallIntegerField,
                          PositiveBigIntegerField, AutoField)):
        return "integer"
    if isinstance(field, JSONField):
        return "json"
    if isinstance(field, (CharField, TextField, EmailField, SlugField, URLField, UUIDField)):
        return "string"
    return "string"


def _describe_field(field):
    """字段元信息（不含任何数据行，只描述结构）。"""
    desc = {
        "name": field.name,
        "verbose_name": str(getattr(field, "verbose_name", field.name)),
        "type": _model_type(field),
        "nullable": bool(getattr(field, "null", False)),
        "relation": None,
    }
    if getattr(field, "is_relation", False):
        related = field.related_model
        if related is not None:
            desc["relation"] = model_label(related)
        desc["type"] = "string"
    return desc


def model_label(model):
    """``app_label.ModelName`` 形式的标签（模型白名单的唯一标识）。"""
    return f"{model._meta.app_label}.{model._meta.object_name}"


def _iter_models():
    """遍历白名单候选模型（跳过代理模型与不受管模型）。"""
    for cfg in apps.get_app_configs():
        if not _is_local_app(cfg):
            continue
        if cfg.models_module is None:
            continue
        for model in cfg.get_models():
            meta = model._meta
            if meta.proxy or not meta.managed:
                continue
            if meta.abstract:
                continue
            yield model


@lru_cache(maxsize=1)
def _whitelist_map():
    """标签 → (模型, app 标签, 模型名, verbose_name, 字段列表)。"""
    out = {}
    for model in _iter_models():
        fields = []
        for field in model._meta.concrete_fields:
            if isinstance(field, EXCLUDED_FIELD_CLASSES):
                continue
            fields.append(_describe_field(field))
        fields.sort(key=lambda f: f["name"])
        out[model_label(model)] = {
            "model": model,
            "app_label": model._meta.app_label,
            "model_name": model._meta.object_name,
            "verbose_name": str(model._meta.verbose_name),
            "fields": fields,
            "count": len(fields),
        }
    return out


def clear_model_cache():
    """清空白名单缓存（测试 / 动态装 app 的极端场景用）。"""
    _whitelist_map.cache_clear()


def whitelist_labels():
    """全部可用的模型标签（排序后返回，前端下拉用）。"""
    return sorted(_whitelist_map().keys())


def whitelist_entries():
    """模型白名单明细：[{label, app_label, model, verbose_name, field_count}]。"""
    out = []
    for label, info in sorted(_whitelist_map().items()):
        out.append({
            "label": label,
            "app_label": info["app_label"],
            "model": info["model_name"],
            "verbose_name": info["verbose_name"],
            "field_count": len(info["fields"]),
        })
    return out


def model_info(label):
    """取白名单条目的元信息；非白名单模型抛 ValueError（中文提示）。"""
    info = _whitelist_map().get(str(label or ""))
    if info is None:
        raise ValueError(
            f"模型 {label} 不在白名单内（仅允许本地应用的 app_label.ModelName）"
        )
    return info


def get_whitelisted_model(label):
    """按标签取模型类；这里用 apps.get_model 而非 import，杜绝任意导入。"""
    info = model_info(label)
    return info["model"]


def model_fields(label):
    """模型字段元信息列表（白名单内）。"""
    return model_info(label)["fields"]


def model_detail(label):
    """模型详情：字段 + 关系 + 行数量提示（行数不查库，避免目录接口变重）。"""
    info = model_info(label)
    relations = []
    for field in info["model"]._meta.concrete_fields:
        if getattr(field, "is_relation", False) and not isinstance(field, EXCLUDED_FIELD_CLASSES):
            relations.append({
                "name": field.name,
                "target": model_label(field.related_model) if field.related_model else "",
                "nullable": bool(getattr(field, "null", False)),
            })
    return {
        "label": label,
        "app_label": info["app_label"],
        "model": info["model_name"],
        "verbose_name": info["verbose_name"],
        "fields": info["fields"],
        "relations": relations,
        "pk_field": info["model"]._meta.pk.name if info["model"]._meta.pk else "id",
    }


def _check_segment(segment, original):
    """路径段只允许字母数字下划线（JSON 键额外允许 -），杜绝奇怪注入。"""
    if not segment:
        raise ValueError(f"字段路径 {original} 含空段")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(ch not in allowed for ch in segment):
        raise ValueError(f"字段路径 {original} 含非法字符：{segment}")


def split_path(path):
    """把 ``a.b__c`` 统一拆成 ['a','b','c']，并做基础字符校验。"""
    text = str(path or "").strip()
    if not text:
        raise ValueError("字段路径不能为空")
    if len(text) > 160:
        raise ValueError("字段路径过长（上限 160 字符）")
    parts = [seg for seg in text.replace("__", ".").split(".")]
    for seg in parts:
        _check_segment(seg, text)
    return parts


def resolve_path(model, path):
    """解析字段路径，返回 {orm_path, type, field, is_json, json_keys, relation}。

    关系段继续往下走（用于跨表列，如 ``owner.username``）；
    遇到 JSONField 时剩余段视为 JSON 键，类型按 json 处理；
    其余情况最后一段必须是具体标量字段，否则报配置错误。
    """
    parts = split_path(path)
    current = model
    walked = []
    for idx, seg in enumerate(parts):
        last = idx == len(parts) - 1
        try:
            field = current._meta.get_field(seg)
        except Exception:  # noqa: BLE001 —— FieldDoesNotExist 归一成配置错误
            raise ValueError(f"模型 {model_label(current)} 不存在字段 {seg}")
        if isinstance(field, EXCLUDED_FIELD_CLASSES):
            raise ValueError(f"字段 {path} 不可用于报表（文件/二进制字段）")
        if isinstance(field, JSONField):
            keys = parts[idx + 1:]
            if len(keys) > MAX_PATH_DEPTH:
                raise ValueError(f"字段 {path} 的 JSON 层级过深")
            return {
                "orm_path": "__".join(walked + [seg] + keys),
                "type": "json",
                "field": field,
                "is_json": True,
                "json_keys": keys,
                "relation": None,
            }
        if getattr(field, "is_relation", False):
            if field.many_to_many:
                # 多对多会引入重复行，聚合口径不可控，直接禁掉
                raise ValueError(f"字段 {path} 经过多对多关系，报表不支持")
            if last:
                # 以关系字段结尾：按主键字符串输出（如 owner 显示 owner_id）
                return {
                    "orm_path": "__".join(walked + [seg]),
                    "type": "string",
                    "field": field,
                    "is_json": False,
                    "json_keys": [],
                    "relation": model_label(field.related_model) if field.related_model else None,
                }
            if len(walked) >= MAX_PATH_DEPTH:
                raise ValueError(f"字段 {path} 的关系跳数超过 {MAX_PATH_DEPTH}")
            current = field.related_model
            walked.append(seg)
            continue
        if not last:
            raise ValueError(f"字段 {path} 中 {seg} 不是关系字段，无法继续下钻")
        return {
            "orm_path": "__".join(walked + [seg]),
            "type": _model_type(field),
            "field": field,
            "is_json": False,
            "json_keys": [],
            "relation": None,
        }
    raise ValueError(f"字段路径 {path} 无法解析")


def same_relation_target(model, via, target_label):
    """校验 ``via`` 关系从 ``model`` 走到的是 ``target_label``。

    数据集关联配置里目标模型是写死的字符串，若不校验，用户可以把
    "关联模型" 填成任意白名单模型而实际 join 到另一张表 —— 展示与会话
    语义直接错位。这里强制一致。
    """
    parts = split_path(via)
    current = model
    for seg in parts:
        try:
            field = current._meta.get_field(seg)
        except Exception:  # noqa: BLE001
            raise ValueError(f"模型 {model_label(current)} 不存在关系字段 {seg}")
        if not getattr(field, "is_relation", False):
            raise ValueError(f"字段 {seg} 不是关系字段，不能作为关联路径")
        if field.many_to_many:
            raise ValueError("关联路径不支持多对多关系")
        current = field.related_model
    actual = model_label(current)
    if actual != target_label:
        raise ValueError(f"关联路径 {via} 实际指向 {actual}，与声明 {target_label} 不一致")
    return current


def value_expression(resolved):
    """把解析结果转成 ORM 表达式。

    JSON 键在 SQLite 上是文本提取，直接 SUM 会报错，所以这里统一 Cast 成
    Float；非数值类型保持原样（聚合层会再按需 Cast）。
    """
    path = resolved["orm_path"]
    if resolved.get("is_json"):
        return Cast(F(path), output_field=FloatField())
    return F(path)


def numeric_expression(resolved):
    """数值聚合表达式：整数/金额/数值/JSON 全部转 float，聚合结果可直接 JSON 化。"""
    if resolved.get("is_json"):
        return Cast(F(resolved["orm_path"]), output_field=FloatField())
    ftype = resolved.get("type")
    if ftype in ("integer", "number", "decimal"):
        return Cast(F(resolved["orm_path"]), output_field=FloatField())
    return Cast(F(resolved["orm_path"]), output_field=FloatField())


def group_expression(resolved, bucket=""):
    """分组表达式：时间字段可按 day/week/month/quarter/year 分桶。"""
    from django.db.models.functions import (
        TruncDay, TruncHour, TruncMonth, TruncQuarter, TruncWeek,
        TruncYear,
    )

    path = resolved["orm_path"]
    ftype = resolved.get("type")
    if bucket:
        if ftype not in ("datetime", "date"):
            raise ValueError(f"时间分桶只能用于日期字段（当前类型 {ftype}）")
        table = {
            "hour": TruncHour,
            "day": TruncDay,
            "week": TruncWeek,
            "month": TruncMonth,
            "quarter": TruncQuarter,
            "year": TruncYear,
        }
        fn = table.get(bucket)
        if fn is None:
            raise ValueError(f"不支持的时间分桶：{bucket}")
        return fn(F(path))
    if resolved.get("is_json"):
        # JSON 里的日期/数字键：保持 JSON 语义，不做 Cast，避免分组值被抹平
        return F(path)
    if ftype in ("integer", "number", "decimal"):
        return F(path)
    return F(path)


def default_ordering(model):
    """模型自身 Meta.ordering 可用则用，否则按 -pk（保证分页稳定）。"""
    ordering = list(getattr(model._meta, "ordering", None) or [])
    pk = model._meta.pk.name if model._meta.pk else "id"
    if ordering:
        return ordering
    return [f"-{pk}"]


def has_field(model, path):
    """存在性判定（不抛异常），用于宽松校验。"""
    try:
        resolve_path(model, path)
        return True
    except ValueError:
        return False


def compare_value_type(ftype):
    """给前端标注「这个字段能做什么」：能否求和、能否分桶。"""
    return {
        "numeric": ftype in ("integer", "number", "decimal"),
        "temporal": ftype in ("datetime", "date"),
        "groupable": ftype in ("string", "bool", "integer", "date", "datetime", "json"),
    }
