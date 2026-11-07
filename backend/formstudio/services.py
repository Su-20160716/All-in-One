# -*- coding: utf-8 -*-
"""formstudio 服务层：schema 校验、类型注册表、条件引擎、校验引擎、计分引擎、
统计聚合、CSV 导出、Webhook 模拟投递、版本对比与分享链接核验。

设计原则
--------
1. **不 eval**：条件与公式走自建分词器 + 递归下降求值器，输入白名单、深度受限，
   任何非法字符/未知标识符都会转成中文 ValueError，而不是把异常抛到解释器层。
2. **schema 是唯一事实源**：发布时快照进 FormVersion，提交时按快照校验，
   表单后续改字段不会改变历史提交的校验/计分口径。
3. **强类型落库**：一次提交同时写 JSON 原值与 text/number/date 列，
   统计接口只做聚合，不做逐行 JSON 解析。
4. **可重放**：Webhook 投递与重试全部入库，失败原因、签名、下次重试时间都能回看。
"""
import csv
import hashlib
import hmac
import io
import json
import math
import re
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import Avg, Count, F, Max, Min, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from formstudio.models import (
    FormAnalyticsSnapshot,
    FormAttachment,
    FormDefinition,
    FormField,
    FormFieldOption,
    FormLogicRule,
    FormReviewTask,
    FormSection,
    FormShareLink,
    FormSubmission,
    FormSubmissionValue,
    FormTemplate,
    FormValidation,
    FormVersion,
    FormWebhook,
    FormWebhookDelivery,
)

# ---------------------------------------------------------------------------
# 1. 字段类型注册表
# ---------------------------------------------------------------------------

FIELD_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^(?:\+?86)?1[3-9]\d{9}$")
URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
HEX_HASH_RE = re.compile(r"^[0-9a-fA-F]{16,128}$")
MAX_ANSWER_JSON_CHARS = 500000
MAX_FILE_SIZE = 50 * 1024 * 1024


class FieldValueError(ValueError):
    """字段级校验错误：带字段 key 与错误码，便于前端定位到具体控件。"""

    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.message = str(message)
        self.code = code


def _is_empty(value):
    """空值统一口径：None/空白串/空列表/空对象都算未填写。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _as_number(value, label="该字段"):
    """安全转数字：拒绝布尔与 NaN/Inf，避免污染统计与公式。"""
    if isinstance(value, bool):
        raise FieldValueError(f"{label}必须是数字", "not_number")
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError):
        raise FieldValueError(f"{label}必须是数字", "not_number")
    if not math.isfinite(num):
        raise FieldValueError(f"{label}必须是有限数字", "not_finite")
    return num


def _validation_of(field):
    """字段的校验配置（容错为 dict）。"""
    data = field.get("validation") or {}
    return data if isinstance(data, dict) else {}


def _options_of(field):
    """字段选项（容错为 list）。"""
    data = field.get("options") or []
    return data if isinstance(data, list) else []


def _option_values(field):
    """选项值 → 选项字典，供选择题快速查询。"""
    out = {}
    for opt in _options_of(field):
        if not isinstance(opt, dict):
            continue
        value = opt.get("value")
        if value is None:
            continue
        out[str(value)] = opt
    return out


def _limit_rule(field):
    """取字段级长度/大小限制，兼容 max_length / maxLen 两种写法。"""
    val = _validation_of(field)
    out = {}
    for key in ("max_length", "min_length", "max", "min", "max_size_mb", "pattern", "regex"):
        if key in val:
            out[key] = val[key]
    return out


def validate_text_value(field, value):
    """单行文本：去首尾空格，长度上限默认 20000。"""
    if isinstance(value, (dict, list)):
        raise FieldValueError("文本字段只接受字符串", "type")
    text = str(value).strip()
    limit = int(_validation_of(field).get("max_length") or 20000)
    if len(text) > limit:
        raise FieldValueError(f"文本长度不能超过 {limit} 个字符", "too_long")
    min_len = int(_validation_of(field).get("min_length") or 0)
    if min_len and len(text) < min_len:
        raise FieldValueError(f"文本长度不能少于 {min_len} 个字符", "too_short")
    return text


def validate_textarea_value(field, value):
    """多行文本：保留换行，长度上限默认 100000。"""
    if isinstance(value, (dict, list)):
        raise FieldValueError("多行文本只接受字符串", "type")
    text = str(value).replace("\r\n", "\n")
    limit = int(_validation_of(field).get("max_length") or 100000)
    if len(text) > limit:
        raise FieldValueError(f"文本长度不能超过 {limit} 个字符", "too_long")
    return text


def validate_number_value(field, value):
    """数字字段：支持整数约束与 min/max 范围。"""
    val = _validation_of(field)
    num = _as_number(value, "数字字段")
    minimum = val.get("min")
    maximum = val.get("max")
    if minimum is not None and num < float(minimum):
        raise FieldValueError(f"数值不能小于 {minimum}", "out_of_range")
    if maximum is not None and num > float(maximum):
        raise FieldValueError(f"数值不能大于 {maximum}", "out_of_range")
    if val.get("integer") and abs(num - round(num)) > 1e-9:
        raise FieldValueError("该字段必须是整数", "not_integer")
    return int(num) if float(num).is_integer() else num


def validate_select_value(field, value):
    """单选：值必须在启用选项内。"""
    options = _option_values(field)
    if not options:
        raise FieldValueError("单选字段尚未配置选项", "no_options")
    key = str(value)
    opt = options.get(key)
    if opt is None:
        raise FieldValueError("请选择有效选项", "not_in_options")
    if opt.get("disabled"):
        raise FieldValueError("该选项已禁用", "option_disabled")
    return key


def validate_multiselect_value(field, value):
    """多选：数组且每项都在选项内，支持最少/最多选择数。"""
    options = _option_values(field)
    if not options:
        raise FieldValueError("多选字段尚未配置选项", "no_options")
    if not isinstance(value, list):
        raise FieldValueError("多选字段必须是数组", "type")
    picked = []
    for item in value:
        key = str(item)
        opt = options.get(key)
        if opt is None:
            raise FieldValueError(f"选项 {item} 不存在", "not_in_options")
        if opt.get("disabled"):
            raise FieldValueError(f"选项 {item} 已禁用", "option_disabled")
        if key not in picked:
            picked.append(key)
    val = _validation_of(field)
    min_choices = int(val.get("min_choices") or 0)
    max_choices = int(val.get("max_choices") or 0)
    if min_choices and len(picked) < min_choices:
        raise FieldValueError(f"至少选择 {min_choices} 项", "too_few")
    if max_choices and len(picked) > max_choices:
        raise FieldValueError(f"最多选择 {max_choices} 项", "too_many")
    return picked


def validate_date_value(field, value):
    """日期：接受 ISO 字符串/date，输出 YYYY-MM-DD；支持 min/max。"""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        text = str(value).strip()
        d = parse_date(text[:10])
        if d is None:
            raise FieldValueError("日期格式应为 YYYY-MM-DD", "bad_date")
    val = _validation_of(field)
    if val.get("min") and str(d) < str(val["min"])[:10]:
        raise FieldValueError(f"日期不能早于 {val['min']}", "out_of_range")
    if val.get("max") and str(d) > str(val["max"])[:10]:
        raise FieldValueError(f"日期不能晚于 {val['max']}", "out_of_range")
    return d.isoformat()


def validate_datetime_value(field, value):
    """日期时间：接受 ISO 字符串/datetime，输出带时区的 ISO。"""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = parse_datetime(text)
        if dt is None:
            d = parse_date(text[:10])
            if d is not None:
                dt = datetime(d.year, d.month, d.day)
        if dt is None:
            raise FieldValueError("日期时间格式不合法", "bad_datetime")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    val = _validation_of(field)
    if val.get("min"):
        lower = parse_datetime(str(val["min"]).replace("Z", "+00:00"))
        if lower and dt < (lower if timezone.is_aware(lower) else timezone.make_aware(lower)):
            raise FieldValueError(f"时间不能早于 {val['min']}", "out_of_range")
    if val.get("max"):
        upper = parse_datetime(str(val["max"]).replace("Z", "+00:00"))
        if upper and dt > (upper if timezone.is_aware(upper) else timezone.make_aware(upper)):
            raise FieldValueError(f"时间不能晚于 {val['max']}", "out_of_range")
    return dt.isoformat()


def validate_boolean_value(field, value):
    """开关：接受布尔与常见字符串表示。"""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "是"):
        return True
    if text in ("0", "false", "no", "off", "否"):
        return False
    raise FieldValueError("开关字段只接受是/否", "type")


def validate_file_value(field, value):
    """文件：只接受元数据（文件名/大小/hash），拒绝任何真实内容字段。"""
    if not isinstance(value, dict):
        raise FieldValueError("文件字段必须提交元数据对象", "type")
    for forbidden in ("content", "data", "base64", "file", "blob"):
        if value.get(forbidden):
            raise FieldValueError("文件内容不落地，只接受文件名/大小/hash", "content_not_allowed")
    name = str(value.get("file_name") or value.get("name") or "").strip()
    if not name:
        raise FieldValueError("缺少文件名", "bad_file")
    if len(name) > 255:
        raise FieldValueError("文件名过长", "bad_file")
    size = value.get("file_size", value.get("size", 0))
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        raise FieldValueError("文件大小必须是整数", "bad_file")
    if size < 0 or size > MAX_FILE_SIZE:
        raise FieldValueError("文件大小超出允许范围", "bad_file")
    max_mb = _validation_of(field).get("max_size_mb")
    if max_mb and size > int(max_mb) * 1024 * 1024:
        raise FieldValueError(f"文件不能超过 {max_mb} MB", "bad_file")
    content_hash = str(value.get("content_hash") or value.get("hash") or "").strip()
    if content_hash and not HEX_HASH_RE.match(content_hash):
        raise FieldValueError("文件哈希格式不合法", "bad_file")
    return {
        "file_name": name,
        "file_size": size,
        "content_hash": content_hash.lower(),
        "mime_type": str(value.get("mime_type") or value.get("type") or "")[:120],
    }


def validate_rating_value(field, value):
    """评分：整数星星，上限取选项数或 validation.max，默认 5 星。"""
    num = _as_number(value, "评分")
    if abs(num - round(num)) > 1e-9:
        raise FieldValueError("评分必须是整数", "not_integer")
    stars = int(round(num))
    options = _options_of(field)
    maximum = int(_validation_of(field).get("max") or (len(options) or 5))
    minimum = int(_validation_of(field).get("min") or 0)
    if stars < minimum or stars > maximum:
        raise FieldValueError(f"评分必须在 {minimum} 到 {maximum} 之间", "out_of_range")
    return stars


def validate_signature_value(field, value):
    """签名：接受 data:image 的 dataURL 或 {hash,size} 元数据，不存二进制。"""
    if isinstance(value, dict):
        content_hash = str(value.get("content_hash") or value.get("hash") or "").strip()
        if not content_hash:
            raise FieldValueError("签名元数据缺少 hash", "bad_signature")
        if not HEX_HASH_RE.match(content_hash):
            raise FieldValueError("签名哈希格式不合法", "bad_signature")
        return {"content_hash": content_hash.lower(), "file_size": int(value.get("size") or 0)}
    text = str(value).strip()
    if not text.startswith("data:image/"):
        raise FieldValueError("签名必须是图片 dataURL", "bad_signature")
    if len(text) > 200000:
        raise FieldValueError("签名图片过大", "bad_signature")
    return text


def _matrix_rows(field):
    """矩阵行定义：validation.rows，支持字符串或 {label, required}。"""
    rows = _validation_of(field).get("rows") or []
    out = []
    for row in rows:
        if isinstance(row, dict):
            label = str(row.get("label") or row.get("value") or "").strip()
            if label:
                out.append({"label": label, "required": bool(row.get("required"))})
        else:
            label = str(row).strip()
            if label:
                out.append({"label": label, "required": False})
    return out


def validate_matrix_value(field, value):
    """矩阵：行来自 validation.rows，列来自 options，逐格校验。"""
    rows = _matrix_rows(field)
    columns = _option_values(field)
    if not rows or not columns:
        raise FieldValueError("矩阵字段缺少行或列定义", "bad_matrix")
    if not isinstance(value, dict):
        raise FieldValueError("矩阵字段必须是对象", "type")
    multi = bool(_validation_of(field).get("multiple"))
    cleaned = {}
    for row in rows:
        label = row["label"]
        cell = value.get(label)
        if _is_empty(cell):
            if row["required"]:
                raise FieldValueError(f"「{label}」必须作答", "matrix_required")
            continue
        if multi:
            if not isinstance(cell, list):
                raise FieldValueError("矩阵该行需要数组", "type")
            picked = []
            for item in cell:
                key = str(item)
                if key not in columns:
                    raise FieldValueError(f"矩阵选项 {item} 不存在", "not_in_options")
                if key not in picked:
                    picked.append(key)
            cleaned[label] = picked
        else:
            key = str(cell)
            if key not in columns:
                raise FieldValueError(f"矩阵选项 {cell} 不存在", "not_in_options")
            cleaned[label] = key
    return cleaned


def validate_email_value(field, value):
    """邮箱：正则校验并转小写。"""
    text = str(value).strip()
    if len(text) > 254 or not EMAIL_RE.match(text):
        raise FieldValueError("邮箱格式不合法", "bad_email")
    return text.lower()


def validate_phone_value(field, value):
    """手机号：支持 +86 前缀的 11 位号码。"""
    text = str(value).strip().replace(" ", "").replace("-", "")
    if not PHONE_RE.match(text):
        raise FieldValueError("手机号格式不合法", "bad_phone")
    return text


def validate_url_value(field, value):
    """链接：仅允许 http/https 且必须有主机名。"""
    text = str(value).strip()
    if len(text) > 2000 or not URL_RE.match(text):
        raise FieldValueError("链接格式不合法", "bad_url")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FieldValueError("链接必须是 http/https 地址", "bad_url")
    return text


def validate_section_value(field, value):
    """分区标题不是输入控件，忽略其值。"""
    return None


# type -> (中文名, 校验器, 是否选项型)
FIELD_TYPE_REGISTRY = {
    "text": {"label": "单行文本", "validate": validate_text_value, "choice": False},
    "textarea": {"label": "多行文本", "validate": validate_textarea_value, "choice": False},
    "number": {"label": "数字", "validate": validate_number_value, "choice": False},
    "select": {"label": "单选", "validate": validate_select_value, "choice": True},
    "multiselect": {"label": "多选", "validate": validate_multiselect_value, "choice": True},
    "date": {"label": "日期", "validate": validate_date_value, "choice": False},
    "datetime": {"label": "日期时间", "validate": validate_datetime_value, "choice": False},
    "boolean": {"label": "开关", "validate": validate_boolean_value, "choice": True},
    "file": {"label": "文件", "validate": validate_file_value, "choice": False},
    "rating": {"label": "评分", "validate": validate_rating_value, "choice": True},
    "signature": {"label": "签名", "validate": validate_signature_value, "choice": False},
    "matrix": {"label": "矩阵", "validate": validate_matrix_value, "choice": True},
    "email": {"label": "邮箱", "validate": validate_email_value, "choice": False},
    "phone": {"label": "手机号", "validate": validate_phone_value, "choice": False},
    "url": {"label": "链接", "validate": validate_url_value, "choice": False},
    "section": {"label": "分区标题", "validate": validate_section_value, "choice": False},
}


def field_type_label(field_type):
    """字段类型中文名（未知类型原样返回）。"""
    spec = FIELD_TYPE_REGISTRY.get(field_type)
    return spec["label"] if spec else field_type


# ---------------------------------------------------------------------------
# 2. 安全公式求值器（禁止 eval）
# ---------------------------------------------------------------------------

FORMULA_FUNCTIONS = {
    "min",
    "max",
    "abs",
    "round",
    "floor",
    "ceil",
    "sum",
    "avg",
    "len",
    "if",
    "coalesce",
    "score",
}
FORMULA_KEYWORDS = {"and", "or", "not", "true", "false"}


def _tokenize_formula(expr):
    """把公式切成 (kind, value) 序列；只允许数字、{字段}、函数名、白名单运算符。"""
    tokens = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            end = expr.find("}", i + 1)
            if end < 0:
                raise ValueError("公式不合法：花括号未闭合")
            key = expr[i + 1:end].strip()
            if not key:
                raise ValueError("公式不合法：字段引用不能为空")
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                raise ValueError(f"公式不合法：字段引用 {key} 不合法")
            tokens.append(("ref", key))
            i = end + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            dot = False
            while j < n and (expr[j].isdigit() or (expr[j] == "." and not dot)):
                dot = dot or expr[j] == "."
                j += 1
            tokens.append(("num", float(expr[i:j])))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            word = expr[i:j]
            low = word.lower()
            if low in FORMULA_KEYWORDS:
                tokens.append(("kw", low))
            elif low in FORMULA_FUNCTIONS:
                tokens.append(("fn", low))
            else:
                raise ValueError(f"公式不合法：未知标识符 {word}（字段请用 {{key}} 引用）")
            i = j
            continue
        two = expr[i:i + 2]
        if two in ("==", "!=", ">=", "<=", "&&", "||"):
            tokens.append(("op", two))
            i += 2
            continue
        if ch in "+-*/%^(),<>!=":
            tokens.append(("op", "==" if ch == "=" else ch))
            i += 1
            continue
        raise ValueError(f"公式不合法：不支持的字符 {ch}")
    return tokens


class _FormulaParser:
    """递归下降解析器；每一步都只返回标量，不执行任何动态代码。"""

    def __init__(self, tokens, context, depth=0):
        self.tokens = tokens
        self.i = 0
        self.context = context or {}
        self.depth = depth
        if depth > 12:
            raise ValueError("公式嵌套过深")

    # -- 工具 --
    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _eat(self, value=None):
        tok = self._peek()
        if tok[0] is None:
            raise ValueError("公式不合法：表达式不完整")
        self.i += 1
        if value is not None and tok[1] != value:
            raise ValueError(f"公式不合法：期望 {value}")
        return tok

    def parse(self):
        if not self.tokens:
            raise ValueError("公式不能为空")
        value = self._or_expr()
        if self.i < len(self.tokens):
            raise ValueError(f"公式不合法：多余内容 {self.tokens[self.i][1]}")
        return value

    def _or_expr(self):
        value = self._and_expr()
        while True:
            kind, token = self._peek()
            if kind == "kw" and token == "or" or kind == "op" and token == "||":
                self.i += 1
                right = self._and_expr()
                value = bool(value) or bool(right)
            else:
                return value

    def _and_expr(self):
        value = self._cmp_expr()
        while True:
            kind, token = self._peek()
            if kind == "kw" and token == "and" or kind == "op" and token == "&&":
                self.i += 1
                right = self._cmp_expr()
                value = bool(value) and bool(right)
            else:
                return value

    def _cmp_expr(self):
        left = self._add_expr()
        kind, token = self._peek()
        if kind == "op" and token in ("==", "!=", ">", ">=", "<", "<="):
            self.i += 1
            right = self._add_expr()
            left_num = _maybe_number(left)
            right_num = _maybe_number(right)
            if left_num is not None and right_num is not None:
                a, b = left_num, right_num
            else:
                a, b = str(left), str(right)
            if token == "==":
                return a == b
            if token == "!=":
                return a != b
            if token == ">":
                return a > b
            if token == ">=":
                return a >= b
            if token == "<":
                return a < b
            return a <= b
        return left

    def _add_expr(self):
        value = self._mul_expr()
        while True:
            kind, token = self._peek()
            if kind == "op" and token in ("+", "-"):
                self.i += 1
                right = self._mul_expr()
                if token == "+":
                    value = _num(value) + _num(right)
                else:
                    value = _num(value) - _num(right)
            else:
                return value

    def _mul_expr(self):
        value = self._unary()
        while True:
            kind, token = self._peek()
            if kind == "op" and token in ("*", "/", "%"):
                self.i += 1
                right = self._unary()
                if token == "*":
                    value = _num(value) * _num(right)
                elif token == "/":
                    divisor = _num(right)
                    if abs(divisor) < 1e-12:
                        raise ValueError("公式不合法：除数不能为 0")
                    value = _num(value) / divisor
                else:
                    divisor = _num(right)
                    if abs(divisor) < 1e-12:
                        raise ValueError("公式不合法：取余除数不能为 0")
                    value = _num(value) % divisor
            else:
                return value

    def _unary(self):
        kind, token = self._peek()
        if kind == "op" and token in ("-", "+", "!"):
            self.i += 1
            value = self._unary()
            if token == "-":
                return -_num(value)
            if token == "!":
                return not bool(value)
            return _num(value)
        if kind == "kw" and token == "not":
            self.i += 1
            return not bool(self._unary())
        return self._power()

    def _power(self):
        value = self._primary()
        kind, token = self._peek()
        if kind == "op" and token == "^":
            self.i += 1
            exponent = self._unary()
            try:
                return _num(value) ** _num(exponent)
            except (OverflowError, ValueError):
                raise ValueError("公式不合法：幂运算溢出")
        return value

    def _primary(self):
        kind, token = self._peek()
        if kind == "num":
            self.i += 1
            return token
        if kind == "ref":
            self.i += 1
            return self.context.get(token, "")
        if kind == "kw" and token in ("true", "false"):
            self.i += 1
            return token == "true"
        if kind == "fn":
            self.i += 1
            name = token
            self._eat("(")
            args = []
            if self._peek() != ("op", ")"):
                while True:
                    args.append(self._or_expr())
                    if self._peek() == ("op", ","):
                        self.i += 1
                        continue
                    break
            self._eat(")")
            return self._call(name, args)
        if kind == "op" and token == "(":
            self.i += 1
            value = self._or_expr()
            self._eat(")")
            return value
        raise ValueError(f"公式不合法：意外的符号 {token}")

    def _call(self, name, args):
        """函数白名单实现；参数错误统一转中文错误。"""
        try:
            if name == "min":
                return min(_num(a) for a in args)
            if name == "max":
                return max(_num(a) for a in args)
            if name == "abs":
                return abs(_num(args[0]))
            if name == "round":
                digits = int(_num(args[1])) if len(args) > 1 else 0
                return round(_num(args[0]), digits)
            if name == "floor":
                return math.floor(_num(args[0]))
            if name == "ceil":
                return math.ceil(_num(args[0]))
            if name == "sum":
                return sum(_num(a) for a in args)
            if name == "avg":
                if not args:
                    return 0
                return sum(_num(a) for a in args) / len(args)
            if name == "len":
                return len(args[0]) if isinstance(args[0], (str, list, dict)) else 0
            if name == "if":
                return args[1] if bool(args[0]) else (args[2] if len(args) > 2 else "")
            if name == "coalesce":
                for arg in args:
                    if not _is_empty(arg):
                        return arg
                return ""
            if name == "score":
                return _num(args[0]) if args else 0
        except (IndexError, TypeError, ValueError):
            raise ValueError(f"公式函数 {name} 参数不合法")
        raise ValueError(f"公式不合法：未知函数 {name}")


def _maybe_number(value):
    """能转数字就返回 float，否则 None（用于比较时决定按数字还是字符串比）。"""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            num = float(value.strip())
        except ValueError:
            return None
        return num if math.isfinite(num) else None
    return None


def _num(value):
    """公式算术转数字：空值/非数字字符串按 0 处理（由 schema 校验兜底类型）。"""
    num = _maybe_number(value)
    if num is not None:
        return num
    if value in (None, ""):
        return 0.0
    raise ValueError(f"公式不合法：{value} 不是数字")


def evaluate_formula(expr, context):
    """对外入口：安全求值，任何错误都以中文 ValueError 抛出。"""
    expr = str(expr or "").strip()
    if not expr:
        raise ValueError("公式不能为空")
    if len(expr) > 2000:
        raise ValueError("公式过长")
    tokens = _tokenize_formula(expr)
    return _FormulaParser(tokens, context).parse()


def formula_field_refs(expr):
    """提取公式引用的字段 key（schema 校验与依赖图用）。"""
    refs = []
    for kind, value in _tokenize_formula(str(expr or "")):
        if kind == "ref" and value not in refs:
            refs.append(value)
    return refs


# ---------------------------------------------------------------------------
# 3. 条件可见性引擎
# ---------------------------------------------------------------------------

CONDITION_OPS = (
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "empty",
    "not_empty",
    "between",
    "starts_with",
    "ends_with",
    "matches",
)


def _compare_values(actual, op, expected):
    """单条比较；空值与类型差异都按可预期的方式降级。"""
    if op == "empty":
        return _is_empty(actual)
    if op == "not_empty":
        return not _is_empty(actual)
    if op == "eq":
        if _is_empty(actual) and _is_empty(expected):
            return True
        a, b = _maybe_number(actual), _maybe_number(expected)
        if a is not None and b is not None:
            return abs(a - b) < 1e-9
        return actual == expected
    if op == "neq":
        return not _compare_values(actual, "eq", expected)
    if op == "in":
        if not isinstance(expected, (list, tuple, set)):
            expected = [expected]
        if isinstance(actual, (list, tuple, set)):
            return any(_compare_values(item, "eq", exp) for item in actual for exp in expected)
        return any(_compare_values(actual, "eq", exp) for exp in expected)
    if op == "not_in":
        return not _compare_values(actual, "in", expected)
    if op == "contains":
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, (list, tuple, set)):
            return any(_compare_values(item, "eq", expected) for item in actual)
        if isinstance(actual, dict):
            return expected in actual
        return False
    if op == "not_contains":
        return not _compare_values(actual, "contains", expected)
    if op == "between":
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            return False
        return _compare_values(actual, "gte", expected[0]) and _compare_values(
            actual, "lte", expected[1]
        )
    if op in ("starts_with", "ends_with", "matches"):
        text = "" if actual is None else str(actual)
        if op == "starts_with":
            return text.startswith(str(expected))
        if op == "ends_with":
            return text.endswith(str(expected))
        try:
            return re.fullmatch(str(expected), text) is not None
        except re.error:
            return False
    # 大小比较：数字优先，其次按 ISO/字符串字典序
    a_num, b_num = _maybe_number(actual), _maybe_number(expected)
    if a_num is not None and b_num is not None:
        left, right = a_num, b_num
    else:
        if actual is None or expected is None:
            return False
        left, right = str(actual), str(expected)
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


def evaluate_condition(condition, answers):
    """条件求值：支持 all/any/not 组合与单条 {field, op, value}。

    空条件视为真（规则无条件生效）；结构非法视为假，避免误触发展示逻辑。
    """
    if not condition:
        return True
    if isinstance(condition, list):
        return all(evaluate_condition(item, answers) for item in condition)
    if not isinstance(condition, dict):
        return False
    for key in ("all", "and"):
        if key in condition:
            children = condition.get(key) or []
            if not isinstance(children, list):
                return False
            return all(evaluate_condition(c, answers) for c in children)
    for key in ("any", "or"):
        if key in condition:
            children = condition.get(key) or []
            if not isinstance(children, list):
                return False
            return any(evaluate_condition(c, answers) for c in children)
    for key in ("not", "none"):
        if key in condition:
            return not evaluate_condition(condition.get(key), answers)
    field = condition.get("field") or condition.get("key")
    if not field:
        return False
    op = str(condition.get("op") or "eq").lower()
    if op not in CONDITION_OPS:
        return False
    return _compare_values(answers.get(field), op, condition.get("value"))


def collect_condition_fields(condition, out=None):
    """递归收集条件引用的字段 key。"""
    out = [] if out is None else out
    if not condition:
        return out
    if isinstance(condition, list):
        for item in condition:
            collect_condition_fields(item, out)
        return out
    if not isinstance(condition, dict):
        return out
    for key in ("all", "and", "any", "or"):
        if key in condition and isinstance(condition[key], list):
            for item in condition[key]:
                collect_condition_fields(item, out)
    for key in ("not", "none"):
        if key in condition:
            collect_condition_fields(condition[key], out)
    field = condition.get("field") or condition.get("key")
    if field and field not in out:
        out.append(field)
    return out


def _initial_states(fields, sections, answers):
    """初始状态：字段自身 condition / 分区 condition 决定可见与必填。"""
    section_visible = {}
    for section in sections or []:
        section_visible[section.get("key")] = evaluate_condition(
            section.get("condition"), answers
        )
    visible = {}
    required = {}
    for field in fields:
        key = field["key"]
        if field.get("type") == "section":
            continue
        is_visible = True
        condition = field.get("condition") or {}
        if condition and not evaluate_condition(condition, answers):
            is_visible = False
        section_key = field.get("section")
        if section_key and section_visible.get(section_key) is False:
            is_visible = False
        visible[key] = is_visible
        required[key] = bool(field.get("required"))
    return visible, required, section_visible


def apply_logic(fields, rules, answers, sections=None, max_passes=3):
    """条件可见性引擎：按优先级执行 show/hide/require/skip/set_value。

    多轮是为了让 set_value 影响依赖它的条件；max_passes 同时兜住「规则互赋」
    这类逻辑环，绝不会死循环（schema 校验阶段还会再显式判环）。
    """
    answers = dict(answers or {})
    effective = dict(answers)
    ordered_rules = sorted(
        [r for r in (rules or []) if r.get("enabled", True)],
        key=lambda r: (int(r.get("priority") or 100), r.get("id") or 0),
    )
    visible, required, section_visible = _initial_states(fields, sections, effective)
    trace = []
    for _ in range(max_passes):
        changed = False
        # 字段自身条件随答案变化重算
        new_visible, new_required, section_visible = _initial_states(
            fields, sections, effective
        )
        for key in list(visible):
            if new_visible.get(key) != visible.get(key):
                changed = True
        for key in list(required):
            if key in new_required and new_required[key] != required.get(key):
                changed = True
        visible.update(new_visible)
        required.update(new_required)
        for rule in ordered_rules:
            if not evaluate_condition(rule.get("condition"), effective):
                continue
            action = rule.get("action")
            target = rule.get("target_key")
            if not target or target not in visible:
                continue
            if action == "show":
                if not visible.get(target):
                    changed = True
                visible[target] = True
                trace.append({"rule": rule.get("name") or rule.get("id"), "action": "show",
                              "target": target})
            elif action == "hide":
                if visible.get(target):
                    changed = True
                visible[target] = False
                trace.append({"rule": rule.get("name") or rule.get("id"), "action": "hide",
                              "target": target})
            elif action == "require":
                if not required.get(target):
                    changed = True
                required[target] = True
                trace.append({"rule": rule.get("name") or rule.get("id"), "action": "require",
                              "target": target})
            elif action == "skip":
                if visible.get(target):
                    changed = True
                visible[target] = False
                trace.append({"rule": rule.get("name") or rule.get("id"), "action": "skip",
                              "target": target})
            elif action == "set_value":
                if effective.get(target) != rule.get("value"):
                    changed = True
                effective[target] = rule.get("value")
                trace.append({"rule": rule.get("name") or rule.get("id"), "action": "set_value",
                              "target": target, "value": rule.get("value")})
        if not changed:
            break
    hidden = [k for k, v in visible.items() if not v]
    return {
        "visible": [k for k, v in visible.items() if v],
        "hidden": hidden,
        "required": [k for k, v in required.items() if v and visible.get(k)],
        "skipped": hidden,
        "values": effective,
        "sections": section_visible,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# 4. schema 构建 / 校验 / 持久化
# ---------------------------------------------------------------------------


def _normalize_option(option):
    """选项规范化：value/label 必填，score 转整数，disabled 转布尔。"""
    if not isinstance(option, dict):
        raise ValueError("选项必须是对象")
    value = option.get("value")
    label = option.get("label")
    if value is None or str(value).strip() == "":
        raise ValueError("选项 value 不能为空")
    if label is None or str(label).strip() == "":
        raise ValueError(f"选项 {value} 的 label 不能为空")
    try:
        score = int(option.get("score") or 0)
    except (TypeError, ValueError):
        raise ValueError(f"选项 {value} 的 score 必须是整数")
    return {
        "value": str(value).strip(),
        "label": str(label).strip(),
        "score": score,
        "disabled": bool(option.get("disabled", False)),
    }


def normalize_schema(schema):
    """把外部 schema 归一成内部稳定结构，缺省值在这里一次性补齐。"""
    if not isinstance(schema, dict):
        raise ValueError("schema 必须是对象")
    sections = []
    raw_sections = schema.get("sections") or []
    if not isinstance(raw_sections, list):
        raise ValueError("sections 必须是数组")
    for index, section in enumerate(raw_sections):
        if not isinstance(section, dict):
            raise ValueError("分区必须是对象")
        key = str(section.get("key") or "").strip()
        if not key:
            raise ValueError(f"第 {index + 1} 个分区缺少 key")
        sections.append(
            {
                "key": key,
                "title": str(section.get("title") or key)[:200],
                "description": str(section.get("description") or ""),
                "order": int(section.get("order", index)),
                "collapsible": bool(section.get("collapsible", False)),
                "condition": section.get("condition") or {},
            }
        )
    fields = []
    raw_fields = schema.get("fields") or []
    if not isinstance(raw_fields, list):
        raise ValueError("fields 必须是数组")
    for index, field in enumerate(raw_fields):
        if not isinstance(field, dict):
            raise ValueError("字段必须是对象")
        key = str(field.get("key") or "").strip()
        if not key:
            raise ValueError(f"第 {index + 1} 个字段缺少 key")
        field_type = str(field.get("type") or field.get("field_type") or "text")
        options = field.get("options") or []
        if not isinstance(options, list):
            raise ValueError(f"字段 {key} 的 options 必须是数组")
        validations = field.get("validations") or []
        if not isinstance(validations, list):
            raise ValueError(f"字段 {key} 的 validations 必须是数组")
        fields.append(
            {
                "key": key,
                "label": str(field.get("label") or key)[:200],
                "type": field_type,
                "required": bool(field.get("required", False)),
                "default": field.get("default", field.get("default_value")),
                "placeholder": str(field.get("placeholder") or "")[:200],
                "help_text": str(field.get("help_text") or ""),
                "order": int(field.get("order", index)),
                "width": str(field.get("width") or "full"),
                "section": str(field.get("section") or "") or "",
                "options": [_normalize_option(o) for o in options],
                "validation": field.get("validation") or {},
                "condition": field.get("condition") or {},
                "validations": [
                    {
                        "rule_type": str(v.get("rule_type") or v.get("type") or "required"),
                        "params": v.get("params") or {},
                        "message": str(v.get("message") or ""),
                        "target_key": str(v.get("target_key") or ""),
                        "order": int(v.get("order", i)),
                        "enabled": bool(v.get("enabled", True)),
                    }
                    for i, v in enumerate(validations)
                    if isinstance(v, dict)
                ],
            }
        )
    logic = []
    raw_logic = schema.get("logic") or []
    if raw_logic and not isinstance(raw_logic, list):
        raise ValueError("logic 必须是数组")
    for index, rule in enumerate(raw_logic):
        if not isinstance(rule, dict):
            raise ValueError("逻辑规则必须是对象")
        logic.append(
            {
                "name": str(rule.get("name") or "")[:200],
                "condition": rule.get("condition") or {},
                "action": str(rule.get("action") or "show"),
                "target_key": str(rule.get("target_key") or rule.get("target") or ""),
                "value": rule.get("value"),
                "priority": int(rule.get("priority", 100)),
                "enabled": bool(rule.get("enabled", True)),
            }
        )
    return {
        "sections": sections,
        "fields": fields,
        "logic": logic,
        "settings": schema.get("settings") or {},
        "form": schema.get("form") or {},
    }


def schema_from_form(form):
    """从数据库读取当前设计，生成与发布快照同构的 schema。"""
    sections = list(form.sections.all().order_by("order", "id"))
    section_keys = {s.pk: s.key for s in sections}
    fields = list(
        form.fields.select_related("section")
        .prefetch_related("option_rows", "validation_rules")
        .order_by("order", "id")
    )
    rules = list(form.logic_rules.all().order_by("priority", "id"))
    return {
        "form": {
            "id": form.pk,
            "code": form.code,
            "name": form.name,
            "form_type": form.form_type,
            "version": None,
            "settings": form.settings or {},
        },
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "description": s.description,
                "order": s.order,
                "collapsible": s.collapsible,
                "condition": s.condition or {},
            }
            for s in sections
        ],
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "type": f.field_type,
                "required": f.required,
                "default": f.default_value,
                "placeholder": f.placeholder,
                "help_text": f.help_text,
                "order": f.order,
                "width": f.width,
                "section": section_keys.get(f.section_id, ""),
                "options": f.option_items(),
                "validation": f.validation or {},
                "condition": f.condition or {},
                "validations": [
                    {
                        "rule_type": v.rule_type,
                        "params": v.params or {},
                        "message": v.message,
                        "target_key": v.target_key,
                        "order": v.order,
                        "enabled": v.enabled,
                    }
                    for v in f.validation_rules.all().order_by("order", "id")
                ],
            }
            for f in fields
        ],
        "logic": [
            {
                "name": r.name,
                "condition": r.condition or {},
                "action": r.action,
                "target_key": r.target_key,
                "value": r.value,
                "priority": r.priority,
                "enabled": r.enabled,
            }
            for r in rules
        ],
        "settings": form.settings or {},
    }


def _detect_cycles(edges):
    """有向图判环：返回 [[a,b,a], ...] 的环路径，供 schema 校验报错。"""
    color = {}
    stack = []
    cycles = []

    def dfs(node):
        color[node] = 1
        stack.append(node)
        for nxt in edges.get(node, ()):  # noqa: B007
            if color.get(nxt, 0) == 1:
                if nxt in stack:
                    idx = stack.index(nxt)
                    cycles.append(stack[idx:] + [nxt])
            elif color.get(nxt, 0) == 0:
                dfs(nxt)
        stack.pop()
        color[node] = 2

    for node in list(edges.keys()):
        if color.get(node, 0) == 0:
            dfs(node)
    return cycles


def collect_schema_issues(schema):
    """schema 全量体检：返回问题列表（不抛异常，接口可一次性回显）。"""
    issues = []
    try:
        norm = normalize_schema(schema)
    except ValueError as exc:
        return [{"code": "schema", "message": str(exc)}]
    section_keys = set()
    for section in norm["sections"]:
        if section["key"] in section_keys:
            issues.append({"code": "section_duplicate", "message": f"分区 key 重复: {section['key']}"})
        section_keys.add(section["key"])
    field_keys = set()
    field_by_key = {}
    for field in norm["fields"]:
        key = field["key"]
        if not FIELD_KEY_RE.match(key):
            issues.append(
                {
                    "code": "field_key",
                    "message": f"字段 key 不合法: {key}（字母开头，仅字母/数字/下划线）",
                }
            )
        if key in field_keys:
            issues.append({"code": "field_duplicate", "message": f"字段 key 重复: {key}"})
        field_keys.add(key)
        field_by_key[key] = field
        if field["type"] not in FIELD_TYPE_REGISTRY:
            issues.append({"code": "field_type", "message": f"字段 {key} 类型未知: {field['type']}"})
        if field["width"] not in ("full", "half", "third"):
            issues.append({"code": "field_width", "message": f"字段 {key} 宽度不合法"})
        if field["section"] and field["section"] not in section_keys:
            issues.append(
                {"code": "field_section", "message": f"字段 {key} 引用了不存在的分区 {field['section']}"}
            )
        if field["type"] in ("select", "multiselect"):
            if not field["options"]:
                issues.append({"code": "options_required", "message": f"字段 {key} 至少需要一个选项"})
        if field["type"] == "matrix":
            if not field["options"]:
                issues.append({"code": "matrix_columns", "message": f"矩阵字段 {key} 缺少列定义"})
            if not _matrix_rows(field):
                issues.append({"code": "matrix_rows", "message": f"矩阵字段 {key} 缺少行定义"})
        seen_values = set()
        for opt in field["options"]:
            if opt["value"] in seen_values:
                issues.append(
                    {"code": "option_duplicate", "message": f"字段 {key} 选项值重复: {opt['value']}"}
                )
            seen_values.add(opt["value"])
        validation = field["validation"]
        if not isinstance(validation, dict):
            issues.append({"code": "validation", "message": f"字段 {key} 的 validation 必须是对象"})
        for rule in field["validations"]:
            if rule["rule_type"] not in {c[0] for c in FormValidation._meta.get_field("rule_type").choices}:
                issues.append(
                    {"code": "rule_type", "message": f"字段 {key} 校验规则类型未知: {rule['rule_type']}"}
                )
            if rule["rule_type"] == "regex":
                pattern = (rule["params"] or {}).get("pattern")
                try:
                    re.compile(str(pattern or ""))
                except re.error:
                    issues.append(
                        {"code": "regex", "message": f"字段 {key} 的正则表达式不合法"}
                    )
            if rule["rule_type"] == "formula":
                expr = (rule["params"] or {}).get("expr")
                try:
                    formula_field_refs(expr)
                except ValueError as exc:
                    issues.append({"code": "formula", "message": f"字段 {key}: {exc}"})
        condition = field["condition"]
        for ref in collect_condition_fields(condition):
            if ref not in field_keys:
                issues.append(
                    {"code": "condition_ref", "message": f"字段 {key} 条件引用了不存在的字段 {ref}"}
                )
    for section in norm["sections"]:
        for ref in collect_condition_fields(section["condition"]):
            if ref not in field_keys:
                issues.append(
                    {
                        "code": "condition_ref",
                        "message": f"分区 {section['key']} 条件引用了不存在的字段 {ref}",
                    }
                )
    edges = defaultdict(set)
    for rule in norm["logic"]:
        target = rule["target_key"]
        if not target:
            issues.append({"code": "logic_target", "message": "逻辑规则缺少目标字段"})
            continue
        if target not in field_keys:
            issues.append(
                {"code": "logic_target", "message": f"逻辑规则目标字段不存在: {target}"}
            )
        if rule["action"] not in {c[0] for c in FormLogicRule._meta.get_field("action").choices}:
            issues.append(
                {"code": "logic_action", "message": f"逻辑规则动作未知: {rule['action']}"}
            )
        refs = collect_condition_fields(rule["condition"])
        for ref in refs:
            if ref not in field_keys:
                issues.append(
                    {"code": "logic_ref", "message": f"逻辑规则条件引用了不存在的字段 {ref}"}
                )
        if rule["action"] == "set_value":
            for ref in refs:
                edges[ref].add(target)
    for field in norm["fields"]:
        for rule in field["validations"]:
            if rule["rule_type"] == "formula" and rule["enabled"]:
                try:
                    for ref in formula_field_refs((rule["params"] or {}).get("expr")):
                        if ref not in field_keys:
                            issues.append(
                                {
                                    "code": "formula_ref",
                                    "message": f"字段 {field['key']} 公式引用了不存在的字段 {ref}",
                                }
                            )
                        edges[ref].add(field["key"])
                except ValueError:
                    pass
        validation = field["validation"] if isinstance(field["validation"], dict) else {}
        formula = validation.get("formula")
        if formula:
            try:
                for ref in formula_field_refs(formula):
                    if ref not in field_keys:
                        issues.append(
                            {
                                "code": "formula_ref",
                                "message": f"字段 {field['key']} 公式引用了不存在的字段 {ref}",
                            }
                        )
                    edges[ref].add(field["key"])
            except ValueError as exc:
                issues.append({"code": "formula", "message": f"字段 {field['key']}: {exc}"})
    for cycle in _detect_cycles(edges):
        issues.append(
            {"code": "logic_cycle", "message": "逻辑规则存在循环依赖: " + " -> ".join(cycle)}
        )
    return issues


def assert_schema_valid(schema):
    """schema 校验失败时抛出中文错误（最多回显 5 条，避免响应体过长）。"""
    issues = collect_schema_issues(schema)
    if issues:
        shown = "；".join(i["message"] for i in issues[:5])
        more = f"（共 {len(issues)} 项问题）" if len(issues) > 5 else ""
        raise ValueError(f"表单结构校验失败：{shown}{more}")
    return True


def persist_schema(form, schema, owner=None):
    """把 schema 事务性写入分区/字段/选项/校验/逻辑规则。

    采用「先删后建」：字段 key 才是对外契约，内部主键变化不影响提交数据
    （提交值按 field_key 存储）。整个替换在事务内完成，读请求不会看到半成品。
    """
    norm = normalize_schema(schema)
    assert_schema_valid(norm)
    owner = owner or form.owner
    with transaction.atomic():
        form.logic_rules.all().delete()
        form.fields.all().delete()
        form.sections.all().delete()
        section_map = {}
        for index, section in enumerate(sorted(norm["sections"], key=lambda s: s["order"])):
            section_map[section["key"]] = FormSection.objects.create(
                owner=owner,
                form=form,
                key=section["key"],
                title=section["title"],
                description=section["description"],
                order=section["order"] if section["order"] is not None else index,
                collapsible=section["collapsible"],
                condition=section["condition"] or {},
            )
        for index, field in enumerate(sorted(norm["fields"], key=lambda f: f["order"])):
            row = FormField.objects.create(
                owner=owner,
                form=form,
                section=section_map.get(field["section"]),
                key=field["key"],
                label=field["label"],
                field_type=field["type"],
                required=field["required"],
                default_value=field["default"],
                placeholder=field["placeholder"],
                help_text=field["help_text"],
                order=field["order"] if field["order"] is not None else index,
                width=field["width"],
                options=field["options"],
                validation=field["validation"] if isinstance(field["validation"], dict) else {},
                condition=field["condition"] or {},
            )
            for opt_index, option in enumerate(field["options"]):
                FormFieldOption.objects.create(
                    owner=owner,
                    field=row,
                    value=option["value"],
                    label=option["label"],
                    order=opt_index,
                    score=option["score"],
                    disabled=option["disabled"],
                )
            for rule_index, rule in enumerate(field["validations"]):
                FormValidation.objects.create(
                    owner=owner,
                    field=row,
                    rule_type=rule["rule_type"],
                    params=rule["params"] if isinstance(rule["params"], dict) else {},
                    message=rule["message"],
                    target_key=rule["target_key"],
                    order=rule["order"] if rule["order"] is not None else rule_index,
                    enabled=rule["enabled"],
                )
        for rule in norm["logic"]:
            FormLogicRule.objects.create(
                owner=owner,
                form=form,
                name=rule["name"],
                condition=rule["condition"] or {},
                action=rule["action"],
                target_key=rule["target_key"],
                value=rule["value"],
                priority=rule["priority"],
                enabled=rule["enabled"],
            )
        if norm["settings"]:
            form.settings = {**(form.settings or {}), **norm["settings"]}
            form.save(update_fields=["settings", "updated_at"])
    return {
        "sections": len(norm["sections"]),
        "fields": len(norm["fields"]),
        "options": sum(len(f["options"]) for f in norm["fields"]),
        "validations": sum(len(f["validations"]) for f in norm["fields"]),
        "logic": len(norm["logic"]),
    }


# ---------------------------------------------------------------------------
# 5. 校验引擎
# ---------------------------------------------------------------------------


def _embedded_rules(field):
    """字段 validation JSON 里的轻量规则，转成与独立规则一致的结构。"""
    validation = _validation_of(field)
    out = []
    if validation.get("pattern") or validation.get("regex"):
        out.append(
            {
                "rule_type": "regex",
                "params": {"pattern": validation.get("pattern") or validation.get("regex")},
                "message": validation.get("pattern_message") or "格式不正确",
                "enabled": True,
            }
        )
    if validation.get("unique"):
        out.append(
            {
                "rule_type": "unique",
                "params": {},
                "message": validation.get("unique_message") or "该值已存在",
                "enabled": True,
            }
        )
    return out


def _rule_error(rule, default_message):
    """规则的自定义提示优先，否则用默认中文提示。"""
    message = str(rule.get("message") or "").strip()
    return message or default_message


def _check_regex(value, pattern, message):
    """正则校验：限制 pattern 与输入长度，避免灾难性回溯。"""
    pattern = str(pattern or "")
    if not pattern:
        return
    if len(pattern) > 500:
        raise FieldValueError("正则表达式过长", "bad_regex")
    if len(str(value)) > 10000:
        raise FieldValueError("待校验文本过长", "too_long")
    try:
        compiled = re.compile(pattern)
    except re.error:
        raise FieldValueError("正则表达式不合法", "bad_regex")
    if compiled.fullmatch(str(value)) is None:
        raise FieldValueError(message, "regex")


def _apply_rule(rule, field, value, answers, form=None, submission=None,
                check_unique=True):
    """执行一条校验规则；不通过抛 FieldValueError。"""
    if not rule.get("enabled", True):
        return
    rule_type = rule.get("rule_type")
    params = rule.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    label = field.get("label") or field.get("key")
    if rule_type == "required":
        if _is_empty(value):
            raise FieldValueError(_rule_error(rule, f"请填写「{label}」"), "required")
        return
    if rule_type in ("min", "max"):
        expected = params.get("value", params.get("min" if rule_type == "min" else "max"))
        if expected is None:
            return
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            actual = float(value)
            expected = float(expected)
        elif isinstance(value, str):
            actual = len(value)
            expected = float(expected)
        elif isinstance(value, list):
            actual = len(value)
            expected = float(expected)
        else:
            return
        if rule_type == "min" and actual < expected:
            raise FieldValueError(
                _rule_error(rule, f"「{label}」不能小于 {expected:g}"), "too_small"
            )
        if rule_type == "max" and actual > expected:
            raise FieldValueError(
                _rule_error(rule, f"「{label}」不能大于 {expected:g}"), "too_large"
            )
        return
    if rule_type == "length":
        text = "" if value is None else str(value)
        minimum = params.get("min")
        maximum = params.get("max")
        if minimum is not None and len(text) < int(minimum):
            raise FieldValueError(
                _rule_error(rule, f"「{label}」长度不能少于 {minimum}"), "too_short"
            )
        if maximum is not None and len(text) > int(maximum):
            raise FieldValueError(
                _rule_error(rule, f"「{label}」长度不能超过 {maximum}"), "too_long"
            )
        return
    if rule_type == "regex":
        _check_regex(value, params.get("pattern"), _rule_error(rule, f"「{label}」格式不正确"))
        return
    if rule_type == "formula":
        expr = params.get("expr")
        if not expr:
            return
        try:
            result = evaluate_formula(expr, _formula_context(field, answers))
        except ValueError as exc:
            raise FieldValueError(str(exc), "formula")
        op = str(params.get("op") or "").lower()
        if op:
            expected = params.get("value")
            if not _compare_values(result, op, expected):
                raise FieldValueError(
                    _rule_error(rule, f"「{label}」未满足公式条件"), "formula"
                )
        elif not bool(result):
            raise FieldValueError(_rule_error(rule, f"「{label}」未满足公式条件"), "formula")
        return
    if rule_type == "unique":
        if not check_unique or form is None or _is_empty(value):
            return
        text = _canonical_text(value)
        qs = FormSubmissionValue.objects.filter(
            form=form,
            field_key=field.get("key"),
            text_value=text,
            submission__status__in=("submitted", "reviewed"),
        )
        if submission is not None and submission.pk:
            qs = qs.exclude(submission_id=submission.pk)
        if qs.exists():
            raise FieldValueError(_rule_error(rule, f"「{label}」的值已存在"), "unique")
        return


def _formula_context(field, answers):
    """公式上下文：答案原样 + 当前字段别名 value。"""
    context = dict(answers or {})
    context.setdefault("value", answers.get(field.get("key")) if answers else None)
    return context


def _canonical_text(value):
    """把任意答案压成唯一性比较用的文本。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "|".join(sorted(str(v) for v in value))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _field_error(field, exc):
    """把字段异常转成统一错误项。"""
    return {
        "field": field.get("key"),
        "label": field.get("label"),
        "code": getattr(exc, "code", "invalid"),
        "message": getattr(exc, "message", str(exc)),
    }


def validate_answers(form, schema, answers, *, check_unique=True,
                     submission=None, collect_all=True):
    """提交校验主入口：逻辑可见性 → 必填 → 类型 → 规则，返回清理后的答案。

    collect_all=True 时一次返回所有错误（前端可逐字段标红）；否则首个错误即中断。
    """
    if not isinstance(answers, dict):
        raise ValueError("answers 必须是对象")
    if len(json.dumps(answers, ensure_ascii=False, default=str)) > MAX_ANSWER_JSON_CHARS:
        raise ValueError("提交内容过大")
    field_map = {f["key"]: f for f in schema.get("fields") or []}
    states = apply_logic(
        schema.get("fields") or [],
        schema.get("logic") or [],
        answers,
        schema.get("sections") or [],
    )
    effective = states["values"]
    errors = []
    cleaned = {}
    required_keys = set(states["required"])
    for field in schema.get("fields") or []:
        key = field["key"]
        if field.get("type") == "section":
            continue
        if key not in states["visible"]:
            # 隐藏/跳过的字段不校验、不落值；已填内容保留在原始 answers 里但不参与计分
            continue
        value = effective.get(key)
        if _is_empty(value) and field.get("default") is not None:
            value = field.get("default")
        required = bool(field.get("required")) or key in required_keys
        if _is_empty(value):
            if required:
                errors.append(
                    {
                        "field": key,
                        "label": field.get("label"),
                        "code": "required",
                        "message": f"请填写「{field.get('label') or key}」",
                    }
                )
            continue
        validator = FIELD_TYPE_REGISTRY.get(field.get("type"), {}).get("validate")
        if validator is None:
            errors.append(
                {
                    "field": key,
                    "label": field.get("label"),
                    "code": "field_type",
                    "message": f"字段类型不支持: {field.get('type')}",
                }
            )
            continue
        try:
            cleaned[key] = validator(field, value)
        except FieldValueError as exc:
            errors.append(_field_error(field, exc))
            continue
        except ValueError as exc:
            errors.append(
                {"field": key, "label": field.get("label"), "code": "invalid", "message": str(exc)}
            )
            continue
        # 独立规则 + validation 内嵌轻量规则
        rules = list(field.get("validations") or []) + _embedded_rules(field)
        for rule in rules:
            try:
                _apply_rule(
                    rule,
                    field,
                    cleaned[key],
                    effective,
                    form=form,
                    submission=submission,
                    check_unique=check_unique,
                )
            except FieldValueError as exc:
                errors.append(_field_error(field, exc))
                if not collect_all:
                    return {"errors": errors, "cleaned": cleaned, "states": states,
                            "values": effective}
        # 公式外置校验（validation.formula + validation.expect）
        validation = _validation_of(field)
        if validation.get("formula"):
            try:
                result = evaluate_formula(validation["formula"], _formula_context(field, effective))
                if "expect" in validation and not _compare_values(
                    result, validation.get("op", "eq"), validation.get("expect")
                ):
                    raise FieldValueError(
                        validation.get("message") or f"「{field.get('label') or key}」不满足公式校验",
                        "formula",
                    )
            except FieldValueError as exc:
                errors.append(_field_error(field, exc))
            except ValueError as exc:
                errors.append(
                    {
                        "field": key,
                        "label": field.get("label"),
                        "code": "formula",
                        "message": str(exc),
                    }
                )
        if not collect_all and errors:
            break
    # 未声明的字段直接忽略，避免脏数据进入统计
    return {"errors": errors, "cleaned": cleaned, "states": states, "values": effective}


# ---------------------------------------------------------------------------
# 6. 计分引擎
# ---------------------------------------------------------------------------


def _option_score(field, value):
    """选择题得分：单选取选项分，多选取命中项之和。"""
    options = _option_values(field)
    if isinstance(value, list):
        total = 0.0
        for item in value:
            opt = options.get(str(item))
            if opt:
                total += float(opt.get("score") or 0)
        return total
    opt = options.get(str(value))
    return float(opt.get("score") or 0) if opt else 0.0


def _max_option_score(field):
    """选择题理论满分：单选取最大正值，多选取所有正分之和。"""
    scores = [float(o.get("score") or 0) for o in _options_of(field)]
    if field.get("type") == "multiselect":
        return sum(s for s in scores if s > 0)
    return max([s for s in scores if s > 0] or [0.0])


def _score_field(field, value, answers):
    """单字段计分：返回 (得分, 满分, 明细)。"""
    if _is_empty(value):
        # 未作答的选择题仍计入满分，保证正确率口径可比较
        max_score = 0.0
        if field.get("type") in ("select", "multiselect"):
            max_score = _max_option_score(field)
        return 0.0, max_score, {"reason": "未作答"}
    field_type = field.get("type")
    if field_type in ("select", "multiselect"):
        return (
            _option_score(field, value),
            _max_option_score(field),
            {"reason": "选项分值"},
        )
    if field_type == "rating":
        validation = _validation_of(field)
        per_star = float(validation.get("points_per_star") or 1)
        maximum = int(validation.get("max") or (len(_options_of(field)) or 5))
        return float(value) * per_star, maximum * per_star, {"reason": "评分折算"}
    validation = _validation_of(field)
    points = float(validation.get("points") or 0)
    if "answer" in validation:
        expected = validation.get("answer")
        actual = value
        if isinstance(actual, list):
            correct = set(map(str, actual)) == set(
                map(str, expected if isinstance(expected, list) else [expected])
            )
        else:
            correct = _canonical_text(actual) == _canonical_text(expected)
        return (points if correct else 0.0), points, {"reason": "标准答案", "correct": correct}
    score_map = validation.get("score_map")
    if isinstance(score_map, dict):
        key = _canonical_text(value)
        awarded = float(score_map.get(key) or 0)
        maximum = max([float(v) for v in score_map.values()] or [0.0])
        return awarded, max(maximum, awarded), {"reason": "分值映射"}
    return 0.0, points, {"reason": "无计分配置"}


def compute_score(form, schema, answers):
    """计分主入口：选项分 + 标准答案 + 评分折算 + settings.scoring 公式规则。

    quiz 表单即使没有任何计分配置也会返回结构完整的 0 分，便于前端统一展示。
    """
    total = 0.0
    max_total = 0.0
    breakdown = []
    states = apply_logic(
        schema.get("fields") or [],
        schema.get("logic") or [],
        answers,
        schema.get("sections") or [],
    )
    for field in schema.get("fields") or []:
        if field.get("type") == "section" or field["key"] not in states["visible"]:
            continue
        value = states["values"].get(field["key"])
        score, maximum, detail = _score_field(field, value, states["values"])
        if maximum:
            max_total += maximum
            total += score
            breakdown.append(
                {
                    "field": field["key"],
                    "label": field.get("label"),
                    "value": value,
                    "score": round(score, 2),
                    "max": round(maximum, 2),
                    "detail": detail,
                }
            )
    settings = (schema.get("settings") or {}) if isinstance(schema, dict) else {}
    scoring = settings.get("scoring") or {}
    rules = scoring.get("rules") if isinstance(scoring, dict) else None
    if isinstance(rules, list):
        context = dict(states["values"] or {})
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if not evaluate_condition(rule.get("condition"), context):
                continue
            points = float(rule.get("points") or 0)
            multiplier = float(rule.get("multiplier") or 0)
            awarded = points
            detail = {"reason": "规则加分", "points": points}
            if rule.get("expr"):
                try:
                    value = evaluate_formula(rule["expr"], context)
                    awarded += float(value) * multiplier
                    detail["expr_value"] = value
                except ValueError as exc:
                    detail["error"] = str(exc)
            total += awarded
            max_total += max(points, 0) + max(multiplier, 0)
            breakdown.append(
                {
                    "field": rule.get("field") or "",
                    "label": rule.get("name") or "计分规则",
                    "score": round(awarded, 2),
                    "max": round(max(points, 0) + max(multiplier, 0), 2),
                    "detail": detail,
                }
            )
    pass_score = None
    if isinstance(scoring, dict) and scoring.get("pass_score") is not None:
        pass_score = float(scoring["pass_score"])
    return {
        "score": round(total, 2),
        "max_score": round(max_total, 2),
        "passed": None if pass_score is None else total >= pass_score,
        "pass_score": pass_score,
        "breakdown": breakdown,
    }

# ---------------------------------------------------------------------------
# 7. 统计聚合
# ---------------------------------------------------------------------------


def final_submissions(form):
    """有效提交（不含草稿与前期待审的驳回记录口径由调用方再筛）。"""
    return form.submissions.filter(status__in=("submitted", "reviewed"))


def _numeric_stats(values):
    """数值统计：均值/中位数/分位/极值/标准差，空集合返回全 0。"""
    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    nums = [v for v in nums if math.isfinite(v)]
    if not nums:
        return {
            "count": 0,
            "avg": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stdev": 0.0,
            "sum": 0.0,
        }
    nums.sort()
    count = len(nums)
    avg = sum(nums) / count
    if count % 2:
        median = nums[count // 2]
    else:
        median = (nums[count // 2 - 1] + nums[count // 2]) / 2
    p90 = nums[min(count - 1, max(0, int(round((count - 1) * 0.9))))]
    variance = sum((v - avg) ** 2 for v in nums) / count
    return {
        "count": count,
        "avg": round(avg, 2),
        "median": round(median, 2),
        "p90": round(p90, 2),
        "min": round(nums[0], 2),
        "max": round(nums[-1], 2),
        "stdev": round(math.sqrt(variance), 2),
        "sum": round(sum(nums), 2),
    }


def _percent(part, total):
    """百分比，保留一位小数；分母为 0 返回 0。"""
    if not total:
        return 0.0
    return round(part * 100.0 / total, 1)


def aggregate_overview(form):
    """表单概览：状态分布、来源、版本、均分、均耗时、完成率、今日/近 7 日。"""
    all_qs = form.submissions.all()
    by_status = {
        row["status"]: row["count"]
        for row in all_qs.values("status").annotate(count=Count("id"))
    }
    final = all_qs.filter(status__in=("submitted", "reviewed"))
    drafts = by_status.get("draft", 0)
    submitted = by_status.get("submitted", 0)
    reviewed = by_status.get("reviewed", 0)
    rejected = by_status.get("rejected", 0)
    final_count = submitted + reviewed
    agg = final.aggregate(
        avg_score=Avg("score"),
        avg_duration=Avg("duration_seconds"),
        max_duration=Max("duration_seconds"),
        min_duration=Min("duration_seconds"),
        answers=Avg("answers_count"),
    )
    today = timezone.localdate()
    week_start = today - timedelta(days=6)
    by_source = {
        row["source"]: row["count"]
        for row in final.values("source").annotate(count=Count("id"))
    }
    by_version = [
        {"version_no": row["version_no"], "count": row["count"]}
        for row in final.values("version_no").annotate(count=Count("id")).order_by("version_no")
    ]
    settings = form.settings or {}
    scoring = settings.get("scoring") if isinstance(settings, dict) else None
    pass_score = None
    if isinstance(scoring, dict) and scoring.get("pass_score") is not None:
        pass_score = float(scoring["pass_score"])
    passed = 0
    if pass_score is not None:
        passed = final.filter(score__gte=pass_score).count()
    return {
        "form_id": form.pk,
        "form_name": form.name,
        "form_type": form.form_type,
        "status": form.status,
        "total": all_qs.count(),
        "submitted": submitted,
        "reviewed": reviewed,
        "rejected": rejected,
        "drafts": drafts,
        "final": final_count,
        "anonymous": final.filter(submitted_by__isnull=True).count(),
        "completion_rate": _percent(final_count, final_count + drafts),
        "review_rate": _percent(reviewed, final_count),
        "reject_rate": _percent(rejected, final_count + rejected),
        "avg_score": round(agg["avg_score"] or 0, 2),
        "avg_duration": round(agg["avg_duration"] or 0, 1),
        "max_duration": agg["max_duration"] or 0,
        "min_duration": agg["min_duration"] or 0,
        "avg_answers": round(agg["answers"] or 0, 1),
        "by_status": by_status,
        "by_source": by_source,
        "by_version": by_version,
        "today": final.filter(submitted_at__date=today).count(),
        "last_7_days": final.filter(submitted_at__date__gte=week_start).count(),
        "pending_reviews": form.submissions.filter(
            review_tasks__status="pending"
        ).distinct().count(),
        "pass_score": pass_score,
        "passed": passed,
        "pass_rate": _percent(passed, final_count) if pass_score is not None else None,
        "last_submission_at": _iso_or_empty(final.order_by("-submitted_at").first()),
        "version_count": form.versions.count(),
        "current_version": (
            form.versions.filter(is_current=True).values_list("version_no", flat=True).first()
        ),
    }


def _iso_or_empty(submission):
    """取提交时间字符串，空对象返回空串。"""
    if submission is None or submission.submitted_at is None:
        return ""
    return submission.submitted_at.isoformat()


def _iter_values(form):
    """一次取出有效提交的所有填报值，减少统计时的查询次数。"""
    return (
        FormSubmissionValue.objects.filter(
            form=form, submission__status__in=("submitted", "reviewed")
        )
        .values("field_key", "raw", "text_value", "number_value", "date_value")
        .iterator()
    )


def _raw_is_empty(raw):
    """统计口径的空值判定（与校验引擎保持一致）。"""
    return _is_empty(raw)


def field_distribution(form, field_key=None):
    """字段分布：选项计数、数值统计、文本 Top、矩阵交叉、附件计数。

    以 schema 为骨架输出，确保「零回答」的字段也会出现在结果里，
    前端不必自己补齐占位。
    """
    try:
        schema = (form.versions.filter(is_current=True).first() or {}).schema
    except AttributeError:
        schema = None
    if not schema:
        schema = schema_from_form(form)
    fields = [f for f in schema.get("fields") or [] if f.get("type") != "section"]
    if field_key:
        fields = [f for f in fields if f["key"] == field_key]
        if not fields:
            raise ValueError("字段不存在")
    values_by_field = defaultdict(list)
    answered = Counter()
    for row in _iter_values(form):
        values_by_field[row["field_key"]].append(row)
        if not _raw_is_empty(row["raw"]):
            answered[row["field_key"]] += 1
    attachment_counts = Counter()
    for row in (
        FormAttachment.objects.filter(
            submission__form=form, submission__status__in=("submitted", "reviewed")
        )
        .values("field_key")
        .annotate(count=Count("id"))
    ):
        attachment_counts[row["field_key"]] = row["count"]
    total_submissions = final_submissions(form).count()
    out = []
    for field in fields:
        key = field["key"]
        rows = values_by_field.get(key, [])
        dtype = field.get("type")
        item = {
            "field_key": key,
            "label": field.get("label"),
            "type": dtype,
            "type_label": field_type_label(dtype),
            "answered": answered.get(key, 0),
            "total": total_submissions,
            "answer_rate": _percent(answered.get(key, 0), total_submissions),
            "distribution": [],
            "stats": {},
        }
        if dtype in ("select", "multiselect", "boolean", "rating"):
            option_labels = {
                str(o.get("value")): o.get("label")
                for o in field.get("options") or []
                if isinstance(o, dict)
            }
            counter = Counter()
            labels = dict(option_labels)
            for row in rows:
                raw = row["raw"]
                if _raw_is_empty(raw):
                    continue
                if dtype == "multiselect" or isinstance(raw, list):
                    for item_value in raw if isinstance(raw, list) else [raw]:
                        counter[str(item_value)] += 1
                elif dtype == "boolean":
                    counter["true" if raw is True else "false"] += 1
                    labels.setdefault("true", "是")
                    labels.setdefault("false", "否")
                else:
                    counter[str(raw)] += 1
            for value, count in counter.most_common():
                item["distribution"].append(
                    {
                        "value": value,
                        "label": labels.get(value, value),
                        "count": count,
                        "percent": _percent(count, total_submissions),
                    }
                )
            if dtype == "rating":
                item["stats"] = _numeric_stats([row["number_value"] for row in rows])
        elif dtype == "number":
            item["stats"] = _numeric_stats([row["number_value"] for row in rows])
        elif dtype in ("date", "datetime"):
            dates = [row["date_value"] for row in rows if row["date_value"]]
            item["stats"] = {
                "count": len(dates),
                "earliest": min(dates).isoformat() if dates else "",
                "latest": max(dates).isoformat() if dates else "",
            }
        elif dtype == "matrix":
            counter = Counter()
            for row in rows:
                raw = row["raw"]
                if not isinstance(raw, dict):
                    continue
                for row_label, cell in raw.items():
                    cells = cell if isinstance(cell, list) else [cell]
                    for col in cells:
                        counter[f"{row_label}::{col}"] += 1
            item["distribution"] = [
                {"value": pair, "label": pair, "count": count, "percent": _percent(count, total_submissions)}
                for pair, count in counter.most_common()
            ]
        elif dtype == "file":
            item["stats"] = {"count": attachment_counts.get(key, 0)}
        elif dtype == "text" or dtype == "textarea" or dtype == "email" or dtype == "phone":
            counter = Counter(row["text_value"] for row in rows if row["text_value"])
            item["distribution"] = [
                {"value": value[:120], "label": value[:120], "count": count,
                 "percent": _percent(count, total_submissions)}
                for value, count in counter.most_common(10)
            ]
        else:
            item["stats"] = {"count": answered.get(key, 0)}
        out.append(item)
    return {
        "form_id": form.pk,
        "submissions": total_submissions,
        "fields": out,
        "count": len(out),
    }


def daily_trend(form, days=30):
    """按日趋势：补齐空缺日期，前端画折线不需要自己补 0。"""
    from django.db.models.functions import TruncDate

    days = max(1, min(int(days or 30), 365))
    end = timezone.localdate()
    start = end - timedelta(days=days - 1)
    rows = (
        final_submissions(form)
        .filter(submitted_at__date__gte=start)
        .annotate(day=TruncDate("submitted_at"))
        .values("day")
        .annotate(
            submissions=Count("id"),
            reviewed=Count("id", filter=Q(status="reviewed")),
            rejected=Count("id", filter=Q(status="rejected")),
            avg_score=Avg("score"),
            avg_duration=Avg("duration_seconds"),
        )
        .order_by("day")
    )
    bucket = {row["day"]: row for row in rows}
    series = []
    total = 0
    cursor = start
    while cursor <= end:
        row = bucket.get(cursor)
        count = int(row["submissions"]) if row else 0
        total += count
        series.append(
            {
                "date": cursor.isoformat(),
                "submissions": count,
                "reviewed": int(row["reviewed"]) if row else 0,
                "rejected": int(row["rejected"]) if row else 0,
                "avg_score": round(row["avg_score"] or 0, 2) if row else 0,
                "avg_duration": round(row["avg_duration"] or 0, 1) if row else 0,
            }
        )
        cursor += timedelta(days=1)
    return {
        "form_id": form.pk,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "total": total,
        "series": series,
    }


def duration_stats(form):
    """填写耗时分布：统计量 + 分桶，便于识别异常长表单。"""
    rows = list(
        final_submissions(form)
        .exclude(duration_seconds__isnull=True)
        .values_list("duration_seconds", flat=True)
    )
    nums = [int(v or 0) for v in rows if (v or 0) > 0]
    stats = _numeric_stats(nums)
    buckets = [
        {"label": "1 分钟内", "min": 0, "max": 60},
        {"label": "1-3 分钟", "min": 60, "max": 180},
        {"label": "3-10 分钟", "min": 180, "max": 600},
        {"label": "10-30 分钟", "min": 600, "max": 1800},
        {"label": "30 分钟以上", "min": 1800, "max": None},
    ]
    for bucket in buckets:
        upper = bucket["max"]
        bucket["count"] = len(
            [v for v in nums if v >= bucket["min"] and (upper is None or v < upper)]
        )
        bucket["percent"] = _percent(bucket["count"], len(nums))
    return {
        "form_id": form.pk,
        "count": len(nums),
        "stats": stats,
        "buckets": buckets,
        "slowest": max(nums) if nums else 0,
        "fastest": min(nums) if nums else 0,
    }


def build_daily_snapshot(form, day=None):
    """生成/更新某天的分析快照（唯一键 form+date，可重复调用幂等）。"""
    day = day or timezone.localdate()
    day_qs = form.submissions.filter(submitted_at__date=day)
    final = day_qs.filter(status__in=("submitted", "reviewed"))
    agg = final.aggregate(avg_score=Avg("score"), avg_duration=Avg("duration_seconds"))
    submitted = final.count()
    drafts = day_qs.filter(status="draft").count()
    reviewed = final.filter(status="reviewed").count()
    by_source = {
        row["source"]: row["count"]
        for row in final.values("source").annotate(count=Count("id"))
    }
    snapshot, _created = FormAnalyticsSnapshot.objects.update_or_create(
        form=form,
        date=day,
        defaults={
            "owner": form.owner,
            "submissions": submitted,
            "drafts": drafts,
            "reviews": reviewed,
            "avg_score": round(agg["avg_score"] or 0, 2),
            "avg_duration": round(agg["avg_duration"] or 0, 1),
            "completion_rate": _percent(submitted, submitted + drafts),
            "viewed": form.view_count,
            "started": submitted + drafts,
            "detail": {"by_source": by_source},
        },
    )
    return snapshot


# ---------------------------------------------------------------------------
# 8. CSV 导出（公式注入防护）
# ---------------------------------------------------------------------------


CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value):
    """单元格转义：列表/对象转文本，并对公式注入前缀加单引号。

    Excel 会把以 = + - @ 开头的单元格当公式执行，CSV 注入是常见的数据外泄入口，
    因此这里统一加前导单引号，保证导出文件只被当作文本渲染。
    """
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "是" if value else "否"
    elif isinstance(value, (list, tuple)):
        text = "；".join(csv_cell(v) if isinstance(v, (dict, list)) else str(v) for v in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    elif isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in CSV_DANGEROUS_PREFIXES:
        text = "'" + text
    return text


def export_submissions_csv(form, submissions, include_meta=True):
    """导出 CSV：表头 = 元信息列 + 字段标签列，值来自已固化的填报值。

    返回 {"filename", "content", "row_count", "columns"}；content 带 UTF-8 BOM，
    Windows Excel 直接打开不会乱码。
    """
    versions = list(form.versions.all().order_by("-version_no"))
    schema = next((v.schema for v in versions if v.is_current and v.schema), None)
    if not schema:
        schema = schema_from_form(form)
    fields = [f for f in schema.get("fields") or [] if f.get("type") != "section"]
    labels = []
    seen = set()
    for field in fields:
        label = str(field.get("label") or field.get("key"))
        if label in seen:
            label = f"{label}({field.get('key')})"
        seen.add(label)
        labels.append(label)
    meta_headers = (
        ["提交ID", "状态", "版本号", "提交人", "提交时间", "耗时(秒)", "得分", "满分", "来源"]
        if include_meta
        else []
    )
    headers = meta_headers + labels
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    rows = 0
    field_keys = [f.get("key") for f in fields]
    for sub in submissions:
        values = {v.field_key: v for v in sub.values.all()}
        row = []
        if include_meta:
            row.extend(
                [
                    sub.pk,
                    sub.status,
                    sub.version_no,
                    sub.submitted_by.username if sub.submitted_by_id else "匿名",
                    sub.submitted_at.isoformat() if sub.submitted_at else "",
                    sub.duration_seconds,
                    "" if sub.score is None else sub.score,
                    "" if sub.max_score is None else sub.max_score,
                    sub.source,
                ]
            )
        for key in field_keys:
            value = values.get(key)
            row.append(csv_cell(value.raw) if value is not None else "")
        writer.writerow(row)
        rows += 1
    filename = f"{form.code}-submissions-{timezone.localdate().isoformat()}.csv"
    return {
        "filename": filename,
        "content": "\ufeff" + buffer.getvalue(),
        "row_count": rows,
        "columns": headers,
    }


# ---------------------------------------------------------------------------
# 9. Webhook 模拟投递与重试
# ---------------------------------------------------------------------------


def validate_webhook_url(url):
    """回调地址只允许 http/https 且必须有主机名。"""
    text = str(url or "").strip()
    if len(text) > 500:
        raise ValueError("回调地址过长")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("回调地址必须是 http/https 地址")
    if " " in text:
        raise ValueError("回调地址不能包含空格")
    return text


def sign_webhook(secret, timestamp, body):
    """HMAC-SHA256 签名：与真实回调服务一致的 timestamp.body 拼接方式。"""
    if not secret:
        return ""
    message = f"{timestamp}.{body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_webhook_payload(event, form, submission=None, extra=None):
    """构造回调请求体；提交事件带提交摘要，便于接收方幂等处理。"""
    payload = {
        "event": event,
        "timestamp": int(timezone.now().timestamp()),
        "form": {
            "id": form.pk,
            "code": form.code,
            "name": form.name,
            "form_type": form.form_type,
            "status": form.status,
        },
    }
    if submission is not None:
        payload["submission"] = {
            "id": submission.pk,
            "status": submission.status,
            "version_no": submission.version_no,
            "score": submission.score,
            "max_score": submission.max_score,
            "duration_seconds": submission.duration_seconds,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
            "answers_count": submission.answers_count,
        }
    if extra:
        payload["extra"] = extra
    return payload


def _simulate_outcome(webhook):
    """模拟真实 HTTP 结果：非法域名/含 fail 的地址失败，timeout. 前缀超时。

    这是一个确定性的模拟器：同一地址的投递结果稳定可复现，方便测试与运维验证重试。
    """
    parsed = urlparse(webhook.url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host.startswith("timeout."):
        return False, 504, "模拟投递超时"
    if host.endswith(".invalid") or "fail" in host or "fail" in path or "error" in path:
        return False, 500, "模拟投递失败：目标返回 500"
    return True, 200, ""


def simulate_delivery(webhook, delivery):
    """投递一次并落库：状态、响应码、签名、耗时、下次重试时间全部可回看。"""
    now = timezone.now()
    body = json.dumps(delivery.payload or {}, ensure_ascii=False, sort_keys=True)
    timestamp = int(now.timestamp())
    delivery.signature = sign_webhook(webhook.secret, timestamp, body)
    if not webhook.enabled:
        delivery.status = "skipped"
        delivery.response_code = None
        delivery.error = "Webhook 已停用"
        delivery.duration_ms = 0
        delivery.next_retry_at = None
        delivery.save()
        return delivery
    try:
        validate_webhook_url(webhook.url)
    except ValueError as exc:
        ok_flag, code, error = False, None, str(exc)
    else:
        ok_flag, code, error = _simulate_outcome(webhook)
    delivery.response_code = code
    delivery.duration_ms = max(1, (len(webhook.url) * 7 + delivery.attempt * 13) % 480)
    if ok_flag:
        delivery.status = "success"
        delivery.error = ""
        delivery.next_retry_at = None
    else:
        delivery.status = "failed"
        delivery.error = error
        if delivery.attempt <= max(0, webhook.max_retries):
            delivery.next_retry_at = now + timedelta(minutes=2 ** min(delivery.attempt, 6))
        else:
            delivery.next_retry_at = None
    delivery.save()
    webhook.last_status = str(code) if code else "failed"
    if ok_flag:
        webhook.failure_count = 0
        webhook.last_error = ""
    else:
        webhook.failure_count += 1
        webhook.last_error = error
    webhook.last_delivery_at = now
    webhook.save(
        update_fields=[
            "last_status",
            "failure_count",
            "last_error",
            "last_delivery_at",
            "updated_at",
        ]
    )
    return delivery


def dispatch_event(form, event, submission=None, extra=None):
    """向所有订阅该事件的启用 Webhook 投递一次（首次尝试）。"""
    payload = build_webhook_payload(event, form, submission, extra)
    deliveries = []
    hooks = form.webhooks.filter(enabled=True).filter(
        Q(event=event) | Q(event="all")
    )
    for hook in hooks:
        delivery = FormWebhookDelivery.objects.create(
            owner=form.owner,
            webhook=hook,
            event=event,
            payload=payload,
            status="pending",
            attempt=1,
        )
        simulate_delivery(hook, delivery)
        deliveries.append(delivery)
    return deliveries


def retry_delivery(delivery):
    """手动重试一次失败投递；成功/跳过状态不允许重试。"""
    if delivery.status != "failed":
        raise ValueError("只有失败的投递可以重试")
    with transaction.atomic():
        delivery = FormWebhookDelivery.objects.select_for_update().select_related("webhook").get(
            pk=delivery.pk
        )
        delivery.attempt += 1
        delivery.status = "pending"
        delivery.next_retry_at = None
        delivery.save(update_fields=["attempt", "status", "next_retry_at", "updated_at"])
        simulate_delivery(delivery.webhook, delivery)
    return delivery


def retry_due_deliveries(limit=50):
    """扫描到期的失败投递并重试，供定时任务调用。"""
    now = timezone.now()
    due = (
        FormWebhookDelivery.objects.filter(
            status="failed", next_retry_at__isnull=False, next_retry_at__lte=now
        )
        .select_related("webhook")
        .order_by("next_retry_at")[:limit]
    )
    results = []
    for delivery in list(due):
        try:
            results.append(retry_delivery(delivery))
        except ValueError:
            continue
    return results


def webhook_stats(form):
    """Webhook 概览：按状态计数 + 最近失败原因。"""
    deliveries = FormWebhookDelivery.objects.filter(webhook__form=form)
    by_status = {
        row["status"]: row["count"]
        for row in deliveries.values("status").annotate(count=Count("id"))
    }
    last_failed = deliveries.filter(status="failed").order_by("-created_at").first()
    return {
        "hooks": form.webhooks.count(),
        "enabled": form.webhooks.filter(enabled=True).count(),
        "deliveries": deliveries.count(),
        "by_status": by_status,
        "last_error": last_failed.error if last_failed else "",
    }


# ---------------------------------------------------------------------------
# 10. 版本发布 / 对比 / 回滚
# ---------------------------------------------------------------------------


def current_version(form):
    """当前生效版本（没有则回退到最新版本）。"""
    return (
        form.versions.filter(is_current=True).order_by("-version_no").first()
        or form.versions.order_by("-version_no").first()
    )


def publish_form(form, user, note="", changelog=""):
    """发布：校验当前 schema → 快照成新版本 → 置为当前版本 → 触发表单发布事件。"""
    schema = schema_from_form(form)
    assert_schema_valid(schema)
    with transaction.atomic():
        form.versions.filter(is_current=True).update(is_current=False)
        last_no = form.versions.aggregate(value=Max("version_no"))["value"] or 0
        version = FormVersion.objects.create(
            owner=form.owner,
            form=form,
            version_no=last_no + 1,
            schema=schema,
            status="published",
            published_by=user if getattr(user, "pk", None) else form.owner,
            published_at=timezone.now(),
            note=str(note or "")[:500],
            changelog=str(changelog or ""),
            is_current=True,
        )
        form.status = "published"
        form.published_at = timezone.now()
        form.closed_at = None
        form.archived_at = None
        form.save(
            update_fields=["status", "published_at", "closed_at", "archived_at", "updated_at"]
        )
        dispatch_event(form, "form.published", extra={"version_no": version.version_no})
    return version


def rollback_to_version(form, version, user, note=""):
    """回滚：把快照写回设计态，再发布一个内容相同的新版本（历史不可篡改）。"""
    if not version.schema:
        raise ValueError("该版本没有可回滚的结构快照")
    persist_schema(form, version.schema, owner=form.owner)
    return publish_form(
        form,
        user,
        note=note or f"回滚至 v{version.version_no}",
        changelog=f"由 v{version.version_no} 回滚生成",
    )


def _field_signature(field):
    """字段对比签名：只比会影响填写/统计的要素。"""
    return {
        "label": field.get("label"),
        "type": field.get("type"),
        "required": bool(field.get("required")),
        "options": [
            {"value": o.get("value"), "label": o.get("label"), "score": o.get("score")}
            for o in field.get("options") or []
            if isinstance(o, dict)
        ],
        "validation": field.get("validation") or {},
        "condition": field.get("condition") or {},
    }


def diff_versions(old_version, new_version):
    """版本对比：字段增删改、分区变化、逻辑规则数量差与摘要。"""
    old_schema = old_version.schema or {}
    new_schema = new_version.schema or {}
    old_fields = {f.get("key"): f for f in old_schema.get("fields") or []}
    new_fields = {f.get("key"): f for f in new_schema.get("fields") or []}
    added = [k for k in new_fields if k not in old_fields]
    removed = [k for k in old_fields if k not in new_fields]
    modified = []
    for key in new_fields:
        if key not in old_fields:
            continue
        old_sig, new_sig = _field_signature(old_fields[key]), _field_signature(new_fields[key])
        changes = {
            name: {"from": old_sig[name], "to": new_sig[name]}
            for name in old_sig
            if old_sig[name] != new_sig[name]
        }
        if changes:
            modified.append({"key": key, "label": new_sig["label"], "changes": changes})
    old_sections = {s.get("key"): s for s in old_schema.get("sections") or []}
    new_sections = {s.get("key"): s for s in new_schema.get("sections") or []}
    section_changes = {
        "added": [k for k in new_sections if k not in old_sections],
        "removed": [k for k in old_sections if k not in new_sections],
        "modified": [
            k
            for k in new_sections
            if k in old_sections
            and _field_signature(old_sections[k]) != _field_signature(new_sections[k])
        ],
    }
    old_logic = old_schema.get("logic") or []
    new_logic = new_schema.get("logic") or []
    return {
        "from": {
            "version_no": old_version.version_no,
            "published_at": old_version.published_at.isoformat() if old_version.published_at else "",
        },
        "to": {
            "version_no": new_version.version_no,
            "published_at": new_version.published_at.isoformat() if new_version.published_at else "",
        },
        "fields": {
            "added": [{"key": k, "label": new_fields[k].get("label")} for k in added],
            "removed": [{"key": k, "label": old_fields[k].get("label")} for k in removed],
            "modified": modified,
        },
        "sections": section_changes,
        "logic": {
            "from": len(old_logic),
            "to": len(new_logic),
            "added": max(0, len(new_logic) - len(old_logic)),
        },
        "summary": {
            "fields_added": len(added),
            "fields_removed": len(removed),
            "fields_modified": len(modified),
            "sections_added": len(section_changes["added"]),
            "sections_removed": len(section_changes["removed"]),
        },
    }


# ---------------------------------------------------------------------------
# 11. 分享链接核验
# ---------------------------------------------------------------------------


def create_share_link(form, user, label="", password="", expires_at=None, max_uses=0):
    """创建分享链接：token 随机不可猜，密码只存哈希，次数上限 0 表示不限。"""
    try:
        max_uses = int(max_uses or 0)
    except (TypeError, ValueError):
        raise ValueError("使用上限必须是整数")
    if max_uses < 0 or max_uses > 1000000:
        raise ValueError("使用上限超出范围")
    password = str(password or "")
    if password and len(password) < 4:
        raise ValueError("访问密码至少 4 位")
    if len(password) > 128:
        raise ValueError("访问密码过长")
    token = ""
    for _ in range(5):
        candidate = secrets.token_urlsafe(30)[:40]
        if not FormShareLink.objects.filter(token=candidate).exists():
            token = candidate
            break
    if not token:
        raise ValueError("生成分享令牌失败，请重试")
    return FormShareLink.objects.create(
        owner=form.owner,
        form=form,
        token=token,
        label=str(label or "")[:120],
        password_hash=make_password(password) if password else "",
        expires_at=expires_at,
        max_uses=max_uses,
    )


def verify_share_link(token, password=None):
    """核验分享链接：存在/启用/未过期/次数未用尽/密码正确，逐项给中文错误。"""
    token = str(token or "").strip()
    if not token:
        raise ValueError("缺少分享令牌")
    link = FormShareLink.objects.select_related("form").filter(token=token).first()
    if link is None:
        raise ValueError("分享链接不存在")
    if not link.active:
        raise ValueError("分享链接已停用")
    if link.is_expired():
        raise ValueError("分享链接已过期")
    if link.max_uses and link.used_count >= link.max_uses:
        raise ValueError("分享链接使用次数已用尽")
    if link.password_hash and not check_password(str(password or ""), link.password_hash):
        raise ValueError("分享密码不正确")
    return link


def consume_share_link(link):
    """消费一次：行锁内自增并复核上限，避免并发超额。"""
    with transaction.atomic():
        locked = FormShareLink.objects.select_for_update().get(pk=link.pk)
        if not locked.active:
            raise ValueError("分享链接已停用")
        if locked.is_expired():
            raise ValueError("分享链接已过期")
        if locked.max_uses and locked.used_count >= locked.max_uses:
            raise ValueError("分享链接使用次数已用尽")
        locked.used_count = F("used_count") + 1
        locked.last_used_at = timezone.now()
        locked.save(update_fields=["used_count", "last_used_at", "updated_at"])
        locked.refresh_from_db(fields=["used_count"])
    return locked


# ---------------------------------------------------------------------------
# 12. 模板与克隆
# ---------------------------------------------------------------------------


BUILTIN_TEMPLATES = [
    {
        "name": "客户满意度调查",
        "category": "调研",
        "description": "NPS + 分项评分 + 开放式建议，适合服务复盘。",
        "form_type": "survey",
        "tags": ["满意度", "NPS", "调研"],
        "schema": {
            "sections": [
                {"key": "basic", "title": "基本信息", "order": 0},
                {"key": "score", "title": "满意度评分", "order": 1},
                {"key": "advice", "title": "改进建议", "order": 2},
            ],
            "fields": [
                {"key": "company", "label": "公司名称", "type": "text", "required": True,
                 "section": "basic", "order": 0, "width": "half"},
                {"key": "contact", "label": "联系人", "type": "text", "required": True,
                 "section": "basic", "order": 1, "width": "half"},
                {"key": "nps", "label": "推荐意愿（0-10）", "type": "rating", "required": True,
                 "section": "score", "order": 2,
                 "validation": {"max": 10, "min": 0}},
                {"key": "service", "label": "服务响应速度", "type": "select", "required": True,
                 "section": "score", "order": 3,
                 "options": [
                     {"value": "great", "label": "非常满意", "score": 5},
                     {"value": "good", "label": "满意", "score": 4},
                     {"value": "normal", "label": "一般", "score": 3},
                     {"value": "bad", "label": "不满意", "score": 1},
                 ]},
                {"key": "advice", "label": "您的建议", "type": "textarea", "required": False,
                 "section": "advice", "order": 4, "placeholder": "请描述可改进之处"},
                {"key": "allow_contact", "label": "是否接受回访", "type": "boolean",
                 "section": "advice", "order": 5, "default": False},
                {"key": "phone", "label": "回访电话", "type": "phone", "required": False,
                 "section": "advice", "order": 6,
                 "condition": {"field": "allow_contact", "op": "eq", "value": True}},
            ],
            "logic": [
                {"name": "接受回访才填电话", "condition": {"field": "allow_contact", "op": "eq", "value": True},
                 "action": "require", "target_key": "phone", "priority": 10},
            ],
        },
    },
    {
        "name": "活动报名登记",
        "category": "报名",
        "description": "姓名/手机/场次/饮食禁忌，带人数上限与截止时间。",
        "form_type": "registration",
        "tags": ["活动", "报名"],
        "schema": {
            "sections": [
                {"key": "person", "title": "报名人信息", "order": 0},
                {"key": "event", "title": "场次选择", "order": 1},
            ],
            "fields": [
                {"key": "name", "label": "姓名", "type": "text", "required": True,
                 "section": "person", "order": 0, "width": "half"},
                {"key": "mobile", "label": "手机号", "type": "phone", "required": True,
                 "section": "person", "order": 1, "width": "half"},
                {"key": "email", "label": "邮箱", "type": "email", "required": False,
                 "section": "person", "order": 2, "width": "half"},
                {"key": "org", "label": "单位", "type": "text", "required": False,
                 "section": "person", "order": 3, "width": "half"},
                {"key": "session", "label": "参加场次", "type": "select", "required": True,
                 "section": "event", "order": 4,
                 "options": [
                     {"value": "am", "label": "上午场"},
                     {"value": "pm", "label": "下午场"},
                 ]},
                {"key": "guests", "label": "同行人数", "type": "number", "required": True,
                 "section": "event", "order": 5, "validation": {"min": 0, "max": 5, "integer": True}},
                {"key": "diet", "label": "饮食禁忌", "type": "multiselect", "required": False,
                 "section": "event", "order": 6,
                 "options": [
                     {"value": "veg", "label": "素食"},
                     {"value": "halal", "label": "清真"},
                     {"value": "allergy", "label": "过敏"},
                 ]},
                {"key": "remark", "label": "备注", "type": "textarea", "required": False,
                 "section": "event", "order": 7},
            ],
            "logic": [],
        },
    },
    {
        "name": "产品反馈问卷",
        "category": "调研",
        "description": "模块满意度 + 问题多选 + 改进建议。",
        "form_type": "feedback",
        "tags": ["产品", "反馈"],
        "schema": {
            "sections": [{"key": "main", "title": "使用体验", "order": 0}],
            "fields": [
                {"key": "score", "label": "整体评分", "type": "rating", "required": True,
                 "section": "main", "order": 0, "validation": {"max": 5}},
                {"key": "modules", "label": "常用模块", "type": "multiselect", "required": True,
                 "section": "main", "order": 1,
                 "options": [
                     {"value": "dashboard", "label": "仪表盘"},
                     {"value": "docs", "label": "文档"},
                     {"value": "im", "label": "消息"},
                     {"value": "report", "label": "报表"},
                 ],
                 "validation": {"min_choices": 1, "max_choices": 4}},
                {"key": "issues", "label": "遇到的问题", "type": "textarea", "required": False,
                 "section": "main", "order": 2},
                {"key": "recommend", "label": "愿意推荐给同事", "type": "boolean",
                 "section": "main", "order": 3},
            ],
            "logic": [
                {"name": "评分低于 3 必须说明原因",
                 "condition": {"field": "score", "op": "lt", "value": 3},
                 "action": "require", "target_key": "issues", "priority": 10},
            ],
        },
    },
    {
        "name": "入职信息收集",
        "category": "收集",
        "description": "基础资料 + 证件附件元数据 + 紧急联系人。",
        "form_type": "collect",
        "tags": ["入职", "人事"],
        "schema": {
            "sections": [
                {"key": "base", "title": "基本信息", "order": 0},
                {"key": "emergency", "title": "紧急联系人", "order": 1},
            ],
            "fields": [
                {"key": "full_name", "label": "姓名", "type": "text", "required": True,
                 "section": "base", "order": 0},
                {"key": "id_no", "label": "证件号码", "type": "text", "required": True,
                 "section": "base", "order": 1,
                 "validations": [{"rule_type": "regex", "params": {"pattern": "^[0-9Xx]{15,18}$"},
                                  "message": "证件号码格式不正确"}]},
                {"key": "join_date", "label": "入职日期", "type": "date", "required": True,
                 "section": "base", "order": 2},
                {"key": "dept", "label": "所属部门", "type": "select", "required": True,
                 "section": "base", "order": 3,
                 "options": [
                     {"value": "rd", "label": "研发"},
                     {"value": "product", "label": "产品"},
                     {"value": "ops", "label": "运营"},
                     {"value": "sales", "label": "销售"},
                 ]},
                {"key": "contract_file", "label": "劳动合同扫描件", "type": "file",
                 "section": "base", "order": 4, "validation": {"max_size_mb": 20}},
                {"key": "emergency_name", "label": "紧急联系人", "type": "text",
                 "section": "emergency", "order": 5, "required": True},
                {"key": "emergency_phone", "label": "紧急联系电话", "type": "phone",
                 "section": "emergency", "order": 6, "required": True},
            ],
            "logic": [],
        },
    },
    {
        "name": "基础知识测验",
        "category": "测验",
        "description": "含选项分值与公式计分的示例测验，满分 100。",
        "form_type": "quiz",
        "tags": ["测验", "培训"],
        "schema": {
            "sections": [{"key": "quiz", "title": "题目", "order": 0}],
            "fields": [
                {"key": "q1", "label": "Python 中用于定义函数的关键字是？", "type": "select",
                 "required": True, "section": "quiz", "order": 0,
                 "options": [
                     {"value": "def", "label": "def", "score": 30},
                     {"value": "func", "label": "func", "score": 0},
                     {"value": "lambda", "label": "lambda", "score": 0},
                 ]},
                {"key": "q2", "label": "以下哪些属于 HTTP 幂等方法？", "type": "multiselect",
                 "required": True, "section": "quiz", "order": 1,
                 "options": [
                     {"value": "get", "label": "GET", "score": 10},
                     {"value": "put", "label": "PUT", "score": 10},
                     {"value": "post", "label": "POST", "score": 0},
                     {"value": "delete", "label": "DELETE", "score": 10},
                 ]},
                {"key": "q3", "label": "Django ORM 中 select_related 用于外键关联查询",
                 "type": "boolean", "required": True, "section": "quiz", "order": 2,
                 "validation": {"answer": True, "points": 20}},
                {"key": "q4", "label": "计算 12 * 4 的结果", "type": "number", "required": True,
                 "section": "quiz", "order": 3,
                 "validation": {"answer": 48, "points": 20}},
                {"key": "q5", "label": "写出你常用的调试方法", "type": "textarea",
                 "required": False, "section": "quiz", "order": 4},
            ],
            "logic": [],
            "settings": {"scoring": {"pass_score": 60}},
        },
    },
    {
        "name": "用印审批申请",
        "category": "审批",
        "description": "印章类型/份数/用途，审批型表单自动生成审核任务。",
        "form_type": "approval",
        "tags": ["审批", "用印"],
        "schema": {
            "sections": [
                {"key": "apply", "title": "申请信息", "order": 0},
                {"key": "detail", "title": "用印说明", "order": 1},
            ],
            "fields": [
                {"key": "applicant", "label": "申请人", "type": "text", "required": True,
                 "section": "apply", "order": 0, "width": "half"},
                {"key": "seal_type", "label": "印章类型", "type": "select", "required": True,
                 "section": "apply", "order": 1, "width": "half",
                 "options": [
                     {"value": "official", "label": "公章"},
                     {"value": "contract", "label": "合同章"},
                     {"value": "finance", "label": "财务章"},
                 ]},
                {"key": "copies", "label": "用印份数", "type": "number", "required": True,
                 "section": "apply", "order": 2, "validation": {"min": 1, "max": 50, "integer": True}},
                {"key": "use_date", "label": "用印日期", "type": "date", "required": True,
                 "section": "apply", "order": 3},
                {"key": "purpose", "label": "用途说明", "type": "textarea", "required": True,
                 "section": "detail", "order": 4},
                {"key": "urgent", "label": "是否加急", "type": "boolean",
                 "section": "detail", "order": 5},
                {"key": "urgent_reason", "label": "加急原因", "type": "textarea",
                 "section": "detail", "order": 6, "condition": {"field": "urgent", "op": "eq", "value": True}},
            ],
            "logic": [
                {"name": "加急必填原因", "condition": {"field": "urgent", "op": "eq", "value": True},
                 "action": "require", "target_key": "urgent_reason", "priority": 10},
            ],
            "settings": {"review_required": True},
        },
    },
]


def ensure_builtin_templates(owner):
    """为用户补齐内置模板（懒创建：首次访问目录时写入，避免数据迁移）。"""
    created = 0
    for spec in BUILTIN_TEMPLATES:
        _obj, is_new = FormTemplate.objects.get_or_create(
            owner=owner,
            name=spec["name"],
            defaults={
                "category": spec["category"],
                "description": spec["description"],
                "form_type": spec["form_type"],
                "schema": spec["schema"],
                "builtin": True,
                "tags": spec["tags"],
            },
        )
        if is_new:
            created += 1
    return created


def unique_form_code(owner, base):
    """生成用户内唯一编码：字母开头、最长 64 位，冲突时追加序号。"""
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(base or "form")).strip("-") or "form"
    if not re.match(r"^[A-Za-z]", text):
        text = f"form-{text}"
    text = text[:56]
    candidate = text
    index = 2
    while FormDefinition.objects.filter(owner=owner, code=candidate).exists():
        candidate = f"{text}-{index}"
        index += 1
    return candidate


def instantiate_template(template, user, code="", name="", settings=None):
    """从模板实例化表单：结构直接落库，状态为草稿，可继续编辑后发布。"""
    owner = user if getattr(user, "pk", None) else template.owner
    final_code = str(code or "").strip() or unique_form_code(owner, template.name)
    if FormDefinition.objects.filter(owner=owner, code=final_code).exists():
        raise ValueError(f"表单编码已存在: {final_code}")
    schema = template.schema or {}
    with transaction.atomic():
        form = FormDefinition.objects.create(
            owner=owner,
            code=final_code,
            name=str(name or template.name)[:200],
            description=template.description,
            form_type=template.form_type,
            status="draft",
            settings={**(schema.get("settings") or {}), **(settings or {})},
        )
        persist_schema(form, schema, owner=owner)
        FormTemplate.objects.filter(pk=template.pk).update(usage_count=F("usage_count") + 1)
    template.refresh_from_db(fields=["usage_count"])
    return form


def clone_form(form, user, code="", name=""):
    """克隆表单：只复制设计态（分区/字段/规则），不复制提交与分享链接。"""
    owner = user if getattr(user, "pk", None) else form.owner
    final_code = str(code or "").strip() or unique_form_code(owner, f"{form.code}-copy")
    if FormDefinition.objects.filter(owner=owner, code=final_code).exists():
        raise ValueError(f"表单编码已存在: {final_code}")
    schema = schema_from_form(form)
    with transaction.atomic():
        clone = FormDefinition.objects.create(
            owner=owner,
            code=final_code,
            name=str(name or f"{form.name} 副本")[:200],
            description=form.description,
            form_type=form.form_type,
            status="draft",
            allow_anonymous=form.allow_anonymous,
            allow_multiple=form.allow_multiple,
            deadline=form.deadline,
            theme=form.theme,
            settings=form.settings,
            submit_message=form.submit_message,
            redirect_url=form.redirect_url,
        )
        persist_schema(clone, schema, owner=owner)
    return clone


def save_form_as_template(form, user, name="", category="自建", description=""):
    """把当前表单另存为模板（同名自动加序号，避免唯一约束报错）。"""
    owner = user if getattr(user, "pk", None) else form.owner
    base = str(name or form.name)[:180]
    final_name = base
    index = 2
    while FormTemplate.objects.filter(owner=owner, name=final_name).exists():
        final_name = f"{base}-{index}"[:200]
        index += 1
    return FormTemplate.objects.create(
        owner=owner,
        name=final_name,
        category=str(category or "自建")[:40],
        description=str(description or form.description),
        form_type=form.form_type,
        schema=schema_from_form(form),
        builtin=False,
        tags=["自建"],
    )


# ---------------------------------------------------------------------------
# 13. 附件元数据与提交事务
# ---------------------------------------------------------------------------


def validate_attachment_metadata(payload):
    """附件元数据校验：只登记不落地，拒绝路径穿越与超限大小。"""
    if not isinstance(payload, dict):
        raise ValueError("附件必须提交元数据对象")
    for forbidden in ("content", "data", "base64", "file", "blob"):
        if payload.get(forbidden):
            raise ValueError("附件内容不落地，只接受文件名/大小/hash")
    name = str(payload.get("file_name") or payload.get("name") or "").strip()
    if not name:
        raise ValueError("缺少文件名")
    if len(name) > 255:
        raise ValueError("文件名过长")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("文件名不能包含路径")
    try:
        size = int(payload.get("file_size", payload.get("size", 0)) or 0)
    except (TypeError, ValueError):
        raise ValueError("文件大小必须是整数")
    if size <= 0 or size > MAX_FILE_SIZE:
        raise ValueError("文件大小超出允许范围")
    content_hash = str(payload.get("content_hash") or payload.get("hash") or "").strip()
    if content_hash and not HEX_HASH_RE.match(content_hash):
        raise ValueError("文件哈希格式不合法")
    return {
        "file_name": name,
        "file_size": size,
        "content_hash": content_hash.lower(),
        "mime_type": str(payload.get("mime_type") or "")[:120],
        "remark": str(payload.get("remark") or "")[:300],
    }


def add_attachment(submission, user, payload):
    """登记附件：字段必须存在且为 file 类型；同一份提交可多次上传。"""
    meta = validate_attachment_metadata(payload)
    field_key = str(payload.get("field_key") or "").strip()
    if not field_key:
        raise ValueError("缺少字段 key")
    schema = (submission.version.schema if submission.version else None) or schema_from_form(
        submission.form
    )
    field = next(
        (f for f in schema.get("fields") or [] if f.get("key") == field_key), None
    )
    if field is None:
        raise ValueError("字段不存在")
    if field.get("type") != "file":
        raise ValueError("该字段不是文件类型")
    return FormAttachment.objects.create(
        owner=submission.owner,
        submission=submission,
        uploaded_by=user if getattr(user, "pk", None) else None,
        field_key=field_key,
        **meta,
    )


def _typed_value(field_type, raw):
    """把答案拆成强类型列；异常值只保留 raw，不阻塞草稿保存。"""
    out = {"text_value": "", "number_value": None, "date_value": None}
    try:
        if field_type in ("number", "rating"):
            num = float(raw)
            out["number_value"] = num
            out["text_value"] = f"{num:g}"
        elif field_type == "boolean":
            out["text_value"] = "true" if raw is True else "false"
        elif field_type == "date":
            d = parse_date(str(raw)[:10])
            if d:
                out["date_value"] = timezone.make_aware(
                    datetime(d.year, d.month, d.day)
                )
                out["text_value"] = d.isoformat()
        elif field_type == "datetime":
            dt = parse_datetime(str(raw).replace("Z", "+00:00"))
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                out["date_value"] = dt
                out["text_value"] = dt.isoformat()
        elif isinstance(raw, (list, tuple)):
            out["text_value"] = "|".join(sorted(str(v) for v in raw))
        elif isinstance(raw, dict):
            out["text_value"] = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        elif raw is not None:
            out["text_value"] = str(raw)
    except (TypeError, ValueError):
        out["text_value"] = str(raw)
    return out


def _replace_values(submission, form, schema, answer_values, score_map=None):
    """重写提交值：先删后批插，保证同一次提交不会残留旧字段。"""
    submission.values.all().delete()
    fields = {f["key"]: f for f in schema.get("fields") or []}
    rows = []
    for key, raw in answer_values.items():
        field = fields.get(key)
        if field is None or field.get("type") == "section":
            continue
        typed = _typed_value(field.get("type"), raw)
        rows.append(
            FormSubmissionValue(
                owner=submission.owner,
                submission=submission,
                form=form,
                field_key=key,
                field_type=field.get("type") or "",
                raw=raw,
                text_value=typed["text_value"],
                number_value=typed["number_value"],
                date_value=typed["date_value"],
                score=(score_map or {}).get(key),
            )
        )
    if rows:
        FormSubmissionValue.objects.bulk_create(rows, batch_size=500)
    return len(rows)


def _draft_cleaned(schema, answers):
    """草稿清理：只保留已知字段，尽量按类型规整，校验失败也保留原值。"""
    fields = {f["key"]: f for f in schema.get("fields") or []}
    cleaned = {}
    for key, raw in (answers or {}).items():
        field = fields.get(key)
        if field is None or field.get("type") == "section" or _is_empty(raw):
            continue
        validator = FIELD_TYPE_REGISTRY.get(field.get("type"), {}).get("validate")
        if validator is None:
            cleaned[key] = raw
            continue
        try:
            cleaned[key] = validator(field, raw)
        except (FieldValueError, ValueError):
            cleaned[key] = raw
    return cleaned


def submission_schema(form, require_published=True):
    """取提交所用版本快照；未发布则报错（草稿提交允许用最新快照）。"""
    version = current_version(form)
    if require_published:
        if version is None or version.status != "published":
            raise ValueError("表单尚未发布")
        return version, (version.schema or {})
    schema = (version.schema if version else None) or schema_from_form(form)
    return version, schema


def _check_multiple(form, user, anonymous, ip):
    """多次提交限制：实名按用户、匿名按 IP（同 IP 视作同一来源）。"""
    if form.allow_multiple:
        return
    final = form.submissions.filter(status__in=("submitted", "reviewed", "rejected"))
    if anonymous:
        if ip:
            final = final.filter(ip=ip)
        else:
            final = final.filter(submitted_by__isnull=True)
    else:
        final = final.filter(submitted_by_id=getattr(user, "id", None))
    if final.exists():
        raise ValueError("该表单不允许重复提交")


class SubmissionValidationError(ValueError):
    """提交校验失败：附带逐字段错误，视图可直接回显 errors。"""

    def __init__(self, errors, message="提交内容校验失败"):
        super().__init__(message)
        self.errors = errors or []


def create_submission(
    form,
    user,
    answers,
    *,
    source="web",
    share_link=None,
    anonymous=False,
    duration_seconds=0,
    ip="",
    user_agent="",
    data=None,
    draft=False,
    existing=None,
):
    """创建/更新提交：草稿只存值，正式提交走完整校验、计分、版本固化与事件。

    所有写操作在一个事务内完成；表单计数用 F 表达式自增，避免并发丢计数。
    """
    if not isinstance(answers, dict):
        raise ValueError("answers 必须是对象")
    if len(json.dumps(answers, ensure_ascii=False, default=str)) > MAX_ANSWER_JSON_CHARS:
        raise ValueError("提交内容过大")
    if not draft:
        reason = form.submit_block_reason()
        if reason:
            raise ValueError(reason)
        _check_multiple(form, user, anonymous, ip)
    version, schema = submission_schema(form, require_published=not draft)
    if draft:
        cleaned = _draft_cleaned(schema, answers)
        score_info = None
        errors = []
    else:
        result = validate_answers(
            form,
            schema,
            answers,
            check_unique=True,
            submission=existing,
            collect_all=True,
        )
        errors = result["errors"]
        cleaned = result["cleaned"]
        if errors:
            raise SubmissionValidationError(errors)
        score_info = compute_score(form, schema, answers)
    source = str(source or "web")
    if source not in {c[0] for c in FormSubmission._meta.get_field("source").choices}:
        source = "web"
    if share_link is not None:
        source = "share"
    try:
        duration_seconds = int(duration_seconds or 0)
    except (TypeError, ValueError):
        duration_seconds = 0
    duration_seconds = max(0, min(duration_seconds, 86400))
    anonymous = bool(anonymous and form.allow_anonymous)
    now = timezone.now()
    score_map = {}
    if score_info:
        for row in score_info["breakdown"]:
            if row.get("field"):
                score_map[row["field"]] = score_map.get(row["field"], 0) + float(
                    row.get("score") or 0
                )
    with transaction.atomic():
        if existing is not None:
            submission = FormSubmission.objects.select_for_update().get(pk=existing.pk)
            if submission.status != "draft" or submission.submitted_by_id != getattr(user, "id", None):
                raise ValueError("只有本人的草稿可以提交")
            if draft:
                submission.status = "draft"
            else:
                submission.status = "submitted"
                submission.submitted_at = now
                submission.submitted_by = None if anonymous else user
                submission.version = version
                submission.version_no = version.version_no if version else 0
                submission.score = score_info["score"]
                submission.max_score = score_info["max_score"]
                submission.duration_seconds = duration_seconds
                submission.share_link = share_link
        else:
            submission = FormSubmission(
                owner=form.owner,
                form=form,
                submitted_by=None if anonymous else user,
                version=version,
                version_no=version.version_no if version else 0,
                status="draft" if draft else "submitted",
                submitted_at=None if draft else now,
                source=source,
                share_link=share_link,
                ip=str(ip or "")[:45],
                user_agent=str(user_agent or "")[:300],
                duration_seconds=duration_seconds,
                score=score_info["score"] if score_info else None,
                max_score=score_info["max_score"] if score_info else None,
            )
        if draft:
            submission.version = version
            submission.version_no = version.version_no if version else 0
            submission.source = source
            submission.share_link = share_link
            submission.ip = str(ip or "")[:45]
            submission.user_agent = str(user_agent or "")[:300]
            submission.duration_seconds = duration_seconds
        submission.answers_count = len(cleaned)
        submission.data = data if isinstance(data, dict) else {}
        submission.save()
        _replace_values(submission, form, schema, cleaned, score_map)
        if not draft:
            FormDefinition.objects.filter(pk=form.pk).update(
                submission_count=F("submission_count") + 1
            )
            review_required = (
                form.form_type == "approval"
                or bool((form.settings or {}).get("review_required"))
            )
            if review_required:
                create_review_task(submission, reviewer=form.owner)
            dispatch_event(form, "submission.created", submission)
            if share_link is not None:
                consume_share_link(share_link)
    form.refresh_from_db(fields=["submission_count"])
    return submission


def create_review_task(submission, reviewer=None, priority="normal", due_at=None):
    """为提交创建审核任务；同一提交已有待办任务时不重复创建。"""
    reviewer = reviewer or submission.owner
    existing = submission.review_tasks.filter(status="pending").first()
    if existing is not None:
        return existing
    return FormReviewTask.objects.create(
        owner=submission.owner,
        submission=submission,
        reviewer=reviewer,
        status="pending",
        priority=str(priority or "normal")[:10],
        due_at=due_at,
    )


def review_submission(submission, reviewer, approve, conclusion=""):
    """审核提交：通过/驳回同时回写提交、任务与 Webhook 事件。"""
    now = timezone.now()
    conclusion = str(conclusion or "")[:2000]
    with transaction.atomic():
        submission = FormSubmission.objects.select_for_update().select_related("form").get(
            pk=submission.pk
        )
        if submission.status not in ("submitted", "rejected", "reviewed"):
            raise ValueError("该提交当前状态不可审核")
        submission.status = "reviewed" if approve else "rejected"
        submission.reviewed_at = now
        submission.review_note = conclusion
        submission.save(update_fields=["status", "reviewed_at", "review_note", "updated_at"])
        task = (
            submission.review_tasks.filter(status="pending").order_by("id").first()
            or submission.review_tasks.filter(reviewer=reviewer).order_by("-id").first()
        )
        if task is None:
            task = create_review_task(submission, reviewer=reviewer)
        task.status = "approved" if approve else "rejected"
        task.conclusion = conclusion
        task.decided_at = now
        if not task.reviewer_id:
            task.reviewer = reviewer
        task.save()
        dispatch_event(
            submission.form,
            "submission.reviewed",
            submission,
            extra={"approved": bool(approve), "conclusion": conclusion},
        )
    return submission


def sync_form_counters(form):
    """按实际有效提交重算计数（删除提交后调用）。"""
    count = form.submissions.exclude(status="draft").count()
    FormDefinition.objects.filter(pk=form.pk).update(submission_count=count)
    form.refresh_from_db(fields=["submission_count"])
    return count
