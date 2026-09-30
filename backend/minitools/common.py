# -*- coding: utf-8 -*-
"""minitools 通用助手：直接复用 devtools/common.py 的实现，避免重复维护。"""
from devtools.common import (  # noqa: F401
    as_lines,
    endpoint,
    endpoint_index,
    fail,
    ok,
    opt_bool,
    opt_num,
    opt_str,
    p,
    req,
    req_list,
    req_num,
    req_str,
)
