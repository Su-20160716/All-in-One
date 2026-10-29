# -*- coding: utf-8 -*-
"""用户可控正则的安全编译（防 ReDoS）。

Python 的 `re` 没有超时机制，一旦遇到 `(a+)+$` 这类嵌套量词，单次
`match` 就能把 worker 卡死几分钟（期间同进程所有请求排队）。
这里在编译前做三道闸：

1. 模式长度上限（超长模式本身也难排查）
2. 嵌套量词 / 量化反向引用的启发式拒绝（覆盖绝大多数灾难性回溯写法）
3. 待匹配文本长度上限（调用方用 guard_subject 收口）

被拒时抛 RegexSafetyError（ValueError 子类），各接口按 400 统一返回。
"""
import re

MAX_PATTERN_LENGTH = 500
MAX_SUBJECT_LENGTH = 200_000
MAX_MATCHES = 1_000

# (a+)+ / (?:a*)* / ([a-z]+){2,} —— 括号内含量词、括号外再套量词
_NESTED_QUANT = re.compile(r"\((?:\?:)?[^()]{0,200}[+*}][^()]{0,200}\)\s*[+*{]")
# \1+ / \2{2,}
_QUANTIFIED_BACKREF = re.compile(r"\\[1-9][+*{]")


class RegexSafetyError(ValueError):
    """正则被安全策略拒绝（语法错误 / 回溯风险 / 过长）"""


def compile_safe(pattern, flags=0):
    """编译用户正则；不安全或语法错误时抛 RegexSafetyError"""
    text = str(pattern or "")
    if len(text) > MAX_PATTERN_LENGTH:
        raise RegexSafetyError(f"正则过长（上限 {MAX_PATTERN_LENGTH} 字符）")
    if _NESTED_QUANT.search(text):
        raise RegexSafetyError("正则含嵌套量词（如 (a+)+），可能触发灾难性回溯，已拒绝")
    if _QUANTIFIED_BACKREF.search(text):
        raise RegexSafetyError("正则对反向引用再加量词，可能触发灾难性回溯，已拒绝")
    try:
        return re.compile(text, flags)
    except re.error as exc:
        raise RegexSafetyError(f"正则语法错误：{exc}") from exc


def guard_subject(text):
    """限制待匹配文本长度；超长抛 RegexSafetyError"""
    text = "" if text is None else str(text)
    if len(text) > MAX_SUBJECT_LENGTH:
        raise RegexSafetyError(f"文本过长（上限 {MAX_SUBJECT_LENGTH} 字符）")
    return text
