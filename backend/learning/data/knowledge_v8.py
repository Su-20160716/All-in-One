# -*- coding: utf-8 -*-
"""F499：知识点「点级唯一内容」汇总（dsh 2026-10-01）。

背景：学科知识中心里有一批知识点（分布在 159 处章节引用中、去重后 89 个）拿不到点级内容，
`enhanced._generate_*_detail` 只能按章节关键词生成通用话术，导致同一学科下不同知识点
（如「现在进行时 / 过去进行时 / 过去将来时」）显示完全相同的一段文字。

本模块把分片（knowledge_v8_a / b / c / d / e / f / g / h.py）合并成 `{subject: {point: detail}}`，
供 `enhanced.knowledge_detail` 在既有精选表之后、通用生成之前优先查表。

只增不改：任一分片缺失或格式异常都静默跳过，不影响主流程。
"""

import importlib

KNOWLEDGE_V8 = {}

for _name in ("knowledge_v8_a", "knowledge_v8_b", "knowledge_v8_c",
              "knowledge_v8_d", "knowledge_v8_e", "knowledge_v8_f",
              "knowledge_v8_g", "knowledge_v8_h"):
    _mod = None
    try:
        _mod = importlib.import_module("." + _name, __package__)
    except Exception:
        try:
            _mod = importlib.import_module(_name)
        except Exception:
            _mod = None
    if _mod is None:
        continue
    _part = getattr(_mod, "PART", None)
    if not isinstance(_part, dict):
        continue
    for _subj, _pts in _part.items():
        if isinstance(_pts, dict):
            KNOWLEDGE_V8.setdefault(_subj, {}).update(_pts)

# ---- 同义写法别名（课程库与资料用字不一致时，让查表也能命中）----
# 课程库（curriculum.KNOWLEDGE）用「阿伏伽德罗常数」，分片资料按通行写法用了「阿伏加德罗常数」。
_ALIAS = {
    "chemistry": {"阿伏伽德罗常数": "阿伏加德罗常数"},
}
for _subj, _pairs in _ALIAS.items():
    _bucket = KNOWLEDGE_V8.get(_subj, {})
    for _alt, _canon in _pairs.items():
        if _alt not in _bucket and _canon in _bucket:
            _bucket[_alt] = _bucket[_canon]
