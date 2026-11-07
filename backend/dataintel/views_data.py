# -*- coding: utf-8 -*-
"""dataintel · 数据面接口：dataset(6) profile(5) transform(6) calc(5) = 22 个。

行数据来源统一走 load_rows()：可直接传 rows 数组，或传 dataset_id 从库里取
（dataset 归属走 core.scoping 行级权限收口）。

第三轮 S26（406–410）追加：transform/one-hot、transform/lag、transform/mask-pii、
profile/unique-values、dataset/<pk>/export —— 变换结果只落新 DatasetVersion，
不改写 Dataset.rows（可回滚）。
"""
import json
import math
import random
import re

from core.scoping import is_visible, scope_queryset

from dataintel.models import Dataset, DatasetVersion
from dataintel.statkit import (mean, median, pearson, quantile, stdev,
                               variance)

from devtools.common import endpoint, fail, ok, opt_bool, opt_num, opt_str, p, req, req_list, req_num, req_str


def load_rows(request):
    """从 rows 数组或 dataset_id 读取行数据（统一入口）。"""
    dataset_id = p(request, "dataset_id")
    if dataset_id:
        try:
            ds = Dataset.objects.get(pk=int(dataset_id))
        except (Dataset.DoesNotExist, ValueError, TypeError):
            raise ValueError("数据集不存在")
        if not is_visible(ds, request.user):
            raise ValueError("无权访问该数据集")
        return ds.rows or [], ds
    rows = p(request, "rows")
    if rows is None:
        raise ValueError("请传 rows 数组或 dataset_id")
    if isinstance(rows, str):
        rows = json.loads(rows)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("rows 必须是对象数组")
    if len(rows) > 5000:
        raise ValueError("rows 超过 5000 行上限")
    return rows, None


def _numeric_fields(rows):
    fields = set(rows[0].keys()) if rows else set()
    out = []
    for f in sorted(fields):
        vals = [r[f] for r in rows if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)]
        if len(vals) >= max(2, len(rows) * 0.5):
            out.append(f)
    return out


# =====================================================================
# dataset 数据集（6）
# =====================================================================


@endpoint()
def dataset_create(request):
    """创建数据集（name/description/columns/rows）。"""
    rows = p(request, "rows") or []
    if isinstance(rows, str):
        rows = json.loads(rows)
    if not isinstance(rows, list):
        raise ValueError("rows 必须是数组")
    if len(rows) > 5000:
        raise ValueError("rows 超过 5000 行上限")
    cols = p(request, "columns") or []
    if not cols and rows:
        cols = [{"name": k, "type": ("number" if isinstance(rows[0][k], (int, float)) and not isinstance(rows[0][k], bool) else "string")}
                for k in rows[0].keys()]
    ds = Dataset.objects.create(
        name=req_str(request, "name")[:120],
        description=opt_str(request, "description")[:500],
        owner=request.user,
        columns=cols, rows=rows,
    )
    if rows:
        try:
            from dataintel.views_plus import snapshot_version

            snapshot_version(ds, request.user, note=f"创建时 {len(rows)} 行")
        except Exception:  # noqa: BLE001
            pass
    return ok({"id": ds.id, "name": ds.name, "row_count": ds.row_count,
               "columns": ds.columns, "created_at": ds.created_at.isoformat()})


@endpoint()
def dataset_list(request):
    """我的数据集列表（行级权限收口）。"""
    qs = scope_queryset(Dataset.objects.all(), request.user)
    items = [{"id": d.id, "name": d.name, "row_count": d.row_count,
              "columns": d.columns, "description": d.description,
              "updated_at": d.updated_at.isoformat()} for d in qs[:100]]
    return ok({"items": items, "count": len(items)})


@endpoint()
def dataset_detail(request, pk):
    """数据集详情（含前 N 行预览）。"""
    try:
        ds = Dataset.objects.get(pk=pk)
    except Dataset.DoesNotExist:
        raise ValueError("数据集不存在")
    if not is_visible(ds, request.user):
        raise ValueError("无权访问该数据集")
    preview_n = int(opt_num(request, "preview", 20, minimum=1, maximum=200) or 20)
    return ok({"id": ds.id, "name": ds.name, "description": ds.description,
               "columns": ds.columns, "row_count": ds.row_count,
               "preview": ds.rows[:preview_n], "updated_at": ds.updated_at.isoformat()})


@endpoint()
def dataset_delete(request, pk):
    """删除数据集（仅所有者或数据范围可见者）。"""
    try:
        ds = Dataset.objects.get(pk=pk)
    except Dataset.DoesNotExist:
        raise ValueError("数据集不存在")
    if not is_visible(ds, request.user):
        raise ValueError("无权删除该数据集")
    name, nid = ds.name, ds.id
    ds.delete()
    return ok({"deleted": True, "id": nid, "name": name})


@endpoint()
def dataset_rows_import(request, pk):
    """追加导入行数据（append/replace 两种模式）。"""
    try:
        ds = Dataset.objects.get(pk=pk)
    except Dataset.DoesNotExist:
        raise ValueError("数据集不存在")
    if not is_visible(ds, request.user):
        raise ValueError("无权写入该数据集")
    rows = p(request, "rows")
    if rows is None:
        raise ValueError("rows 必填")
    if isinstance(rows, str):
        rows = json.loads(rows)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("rows 必须是对象数组")
    mode = opt_str(request, "mode", "append")
    total_rows = len(rows) if mode == "replace" else len(ds.rows or []) + len(rows)
    if total_rows > 5000:
        raise ValueError("超过 5000 行上限，请改用 replace 或先清理")
    if mode == "replace":
        ds.rows = rows
    else:
        ds.rows = (ds.rows or []) + rows
    ds.row_count = total_rows
    new_keys = {k for r in rows for k in r} - {c["name"] for c in ds.columns}
    ds.columns = ds.columns + [{"name": k, "type": "string"} for k in sorted(new_keys)]
    ds.save()
    # F48：导入即留版本快照；版本能力失败不能影响导入本身
    version = None
    try:
        from dataintel.views_plus import snapshot_version

        version = snapshot_version(ds, request.user, note=f"{mode} {len(rows)} 行").version
    except Exception:  # noqa: BLE001
        version = None
    return ok({"id": ds.id, "row_count": ds.row_count, "mode": mode,
               "added": len(rows), "version": version})


@endpoint()
def dataset_rows_query(request, pk):
    """查询数据集行：分页 + 字段过滤（field__op=value 风格参数）。"""
    try:
        ds = Dataset.objects.get(pk=pk)
    except Dataset.DoesNotExist:
        raise ValueError("数据集不存在")
    if not is_visible(ds, request.user):
        raise ValueError("无权访问该数据集")
    rows = ds.rows or []
    field = opt_str(request, "field")
    op = opt_str(request, "op", "eq")
    value = p(request, "value")
    if field:
        def keep(r):
            v = r.get(field)
            try:
                if op == "eq":
                    return v == value
                if op == "ne":
                    return v != value
                if op == "gt":
                    return v is not None and float(v) > float(value)
                if op == "gte":
                    return v is not None and float(v) >= float(value)
                if op == "lt":
                    return v is not None and float(v) < float(value)
                if op == "lte":
                    return v is not None and float(v) <= float(value)
                if op == "contains":
                    return value is not None and str(value) in str(v)
            except (TypeError, ValueError):
                return False
            return True
        rows = [r for r in rows if keep(r)]
    offset = int(opt_num(request, "offset", 0, minimum=0) or 0)
    limit = int(opt_num(request, "limit", 50, minimum=1, maximum=500) or 50)
    return ok({"rows": rows[offset:offset + limit], "total": len(rows),
               "offset": offset, "limit": limit})


# =====================================================================
# profile 数据画像（5）
# =====================================================================


@endpoint()
def profile_describe(request):
    """数值字段统计描述：均值/标准差/分位数/极值/离群点。"""
    rows, _ = load_rows(request)
    field = req_str(request, "field")
    vals = [float(r[field]) for r in rows if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]
    if len(vals) < 2:
        raise ValueError(f"字段 {field} 的数值样本不足（{len(vals)} 个）")
    q1, q2, q3 = quantile(vals, 0.25), quantile(vals, 0.5), quantile(vals, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = [v for v in vals if v < lo or v > hi]
    return ok({"field": field, "count": len(vals), "mean": round(mean(vals), 6),
               "std": round(stdev(vals), 6), "min": min(vals), "max": max(vals),
               "q1": round(q1, 6), "median": round(q2, 6), "q3": round(q3, 6),
               "iqr": round(iqr, 6), "cv": round(stdev(vals) / mean(vals), 4) if mean(vals) else None,
               "outliers": {"count": len(outliers), "fence": [round(lo, 4), round(hi, 4)],
                            "values": outliers[:50]}})


@endpoint()
def profile_freq(request):
    """类别字段的频次/占比 TOP 表。"""
    rows, _ = load_rows(request)
    field = req_str(request, "field")
    top = int(opt_num(request, "top", 20, minimum=1, maximum=100) or 20)
    counter = {}
    for r in rows:
        v = str(r.get(field, ""))
        counter[v] = counter.get(v, 0) + 1
    total = len(rows) or 1
    items = sorted(counter.items(), key=lambda kv: -kv[1])[:top]
    return ok({"field": field, "unique": len(counter), "total": len(rows),
               "items": [{"value": k, "count": c, "pct": round(c / total * 100, 2)} for k, c in items]})


@endpoint()
def profile_corr(request):
    """数值字段皮尔逊相关矩阵。"""
    rows, _ = load_rows(request)
    fields = p(request, "fields") or _numeric_fields(rows)
    if len(fields) < 2:
        raise ValueError("数值字段不足 2 个，无法计算相关矩阵")
    if len(fields) > 30:
        raise ValueError("最多同时计算 30 个字段的相关矩阵")

    def _is_num(r, f):
        v = r.get(f)
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    matrix = {a: {} for a in fields}
    pair_n = {}
    for i, a in enumerate(fields):
        matrix[a][a] = 1.0
        for b in fields[i + 1:]:
            pairs = [(float(r[a]), float(r[b])) for r in rows if _is_num(r, a) and _is_num(r, b)]
            if len(pairs) < 3:
                matrix[a][b] = matrix[b][a] = None
                continue
            rv = round(pearson([x for x, _ in pairs], [y for _, y in pairs]), 4)
            matrix[a][b] = matrix[b][a] = rv
            pair_n[(a, b)] = len(pairs)
    if not pair_n:
        raise ValueError("有效样本不足 3 行")
    n = min(pair_n.values())
    pairs = sorted(((a, b, matrix[a][b]) for (a, b) in pair_n),
                   key=lambda t: -abs(t[2]))
    return ok({"fields": fields, "matrix": matrix, "n": n,
               "top_pairs": [{"a": a, "b": b, "r": r, "n": pair_n[(a, b)]} for a, b, r in pairs[:10]]})


@endpoint()
def profile_missing(request):
    """缺失值画像：每字段缺失数/占比/空串计数。"""
    rows, _ = load_rows(request)
    if not rows:
        raise ValueError("rows 为空")
    fields = sorted({k for r in rows for k in r})
    items = []
    for f in fields:
        missing = sum(1 for r in rows if r.get(f) is None)
        blank = sum(1 for r in rows if isinstance(r.get(f), str) and not r.get(f).strip())
        items.append({"field": f, "missing": missing, "blank": blank,
                      "pct": round((missing + blank) / len(rows) * 100, 2)})
    items.sort(key=lambda x: -x["pct"])
    return ok({"total_rows": len(rows), "fields": items,
               "worst_field": items[0]["field"] if items else None})


@endpoint()
def profile_dtype_infer(request):
    """字段类型推断：number/boolean/date/string，附样本值。"""
    rows, _ = load_rows(request)
    if not rows:
        raise ValueError("rows 为空")
    fields = sorted({k for r in rows for k in r})
    items = []
    date_re = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")
    for f in fields:
        vals = [r.get(f) for r in rows if r.get(f) is not None]
        nums = sum(1 for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool))
        bools = sum(1 for v in vals if isinstance(v, bool))
        dates = sum(1 for v in vals if isinstance(v, str) and date_re.match(v))
        kind = "string"
        if vals and bools == len(vals):
            kind = "boolean"
        elif vals and dates >= len(vals) * 0.8:
            kind = "date"
        elif vals and nums >= len(vals) * 0.8:
            kind = "number"
        items.append({"field": f, "type": kind, "non_null": len(vals), "sample": vals[:3]})
    return ok({"fields": items, "count": len(items)})


# =====================================================================
# transform 数据变换（6）
# =====================================================================


@endpoint()
def transform_pivot(request):
    """透视表：index 行 × columns 列 × agg 聚合。"""
    rows, _ = load_rows(request)
    index = req_str(request, "index")
    column = opt_str(request, "column")
    value = req_str(request, "value")
    agg = opt_str(request, "agg", "sum")
    funcs = {"sum": lambda vs: sum(vs), "mean": lambda vs: mean(vs), "count": len,
             "max": max, "min": min, "median": median}
    if agg not in funcs:
        raise ValueError(f"agg 支持 {list(funcs)}")
    table, keys, cols = {}, set(), set()
    for r in rows:
        ik = str(r.get(index, ""))
        if column:
            ck = str(r.get(column, ""))
            cols.add(ck)
        else:
            ck = "_all"
        keys.add(ik)
        table.setdefault((ik, ck), []).append(r.get(value))
    result = {}
    for ik in sorted(keys):
        result[ik] = {}
        for ck in (sorted(cols) if column else ["_all"]):
            vs = [v for v in table.get((ik, ck), []) if isinstance(v, (int, float)) and not isinstance(v, bool)]
            result[ik][ck if column else agg] = round(funcs[agg](vs), 6) if (vs or agg == "count") and (vs or agg == "count") else (0 if agg != "count" else len(table.get((ik, ck), [])))
    return ok({"index": index, "column": column, "agg": agg, "pivot": result,
               "rows": len(result), "cols": len(cols) + (0 if column else 0) or 1})


@endpoint()
def transform_groupby(request):
    """分组聚合：by 字段 + aggs=[{field, func}]。"""
    rows, _ = load_rows(request)
    by = req_str(request, "by")
    aggs = p(request, "aggs") or [{"field": by, "func": "count"}]
    funcs = {"sum": sum, "mean": mean, "count": len, "max": max, "min": min, "median": median, "std": lambda vs: stdev(vs)}
    groups = {}
    for r in rows:
        groups.setdefault(str(r.get(by, "")), []).append(r)
    out = []
    for gk, rs in sorted(groups.items()):
        row = {by: gk, "_count": len(rs)}
        for spec in aggs:
            if not isinstance(spec, dict) or "field" not in spec:
                raise ValueError("aggs 每项需为 {field, func}")
            f, fn = spec["field"], spec.get("func", "mean")
            if fn not in funcs:
                raise ValueError(f"func 支持 {list(funcs)}")
            vs = [r.get(f) for r in rs if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)]
            if fn == "count":
                row[f"{f}_{fn}"] = len(rs)
            elif vs:
                row[f"{f}_{fn}"] = round(funcs[fn](vs), 6)
            else:
                row[f"{f}_{fn}"] = None
        out.append(row)
    return ok({"groups": out, "group_count": len(out)})


_OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, ">": lambda a, b: float(a) > float(b),
        ">=": lambda a, b: float(a) >= float(b), "<": lambda a, b: float(a) < float(b),
        "<=": lambda a, b: float(a) <= float(b),
        "contains": lambda a, b: str(b) in str(a), "startswith": lambda a, b: str(a).startswith(str(b)),
        "endswith": lambda a, b: str(a).endswith(str(b))}


def _match_expr(row, expr):
    """mini 表达式：field op value 以 and/or 连接（不可混用）。"""
    expr = expr.strip()
    if " and " in expr.lower() and " or " in expr.lower():
        raise ValueError("表达式中 and/or 不可混用（请用两条规则分步过滤）")
    glue = " and " if " and " in expr.lower() else " or "
    parts = re.split(glue, expr, flags=re.I)
    results = []
    for part in parts:
        m = re.match(r"^\s*([\w\u4e00-\u9fff]+)\s*(==|!=|>=|<=|>|<|contains|startswith|endswith)\s*(.+?)\s*$", part.strip(), re.I)
        if not m:
            raise ValueError(f"无法解析条件: {part.strip()}")
        field, op, raw = m.group(1), m.group(2).lower(), m.group(3).strip().strip("'\"")
        if field not in row:
            results.append(False)
            continue
        try:
            results.append(_OPS[op](row[field], raw))
        except (TypeError, ValueError):
            results.append(False)
    return all(results) if glue.strip().lower() == "and" else any(results)


@endpoint()
def transform_filter_expr(request):
    """表达式行过滤：age > 30 and city contains 深圳。"""
    rows, _ = load_rows(request)
    expr = req_str(request, "expr")
    kept = [r for r in rows if _match_expr(r, expr)]
    return ok({"rows": kept, "kept": len(kept), "dropped": len(rows) - len(kept), "expr": expr})


@endpoint()
def transform_sample(request):
    """抽样：random（可复现 seed）/ systematic 等距。"""
    rows, _ = load_rows(request)
    n = int(req_num(request, "n", 10, minimum=1, maximum=1000) or 10)
    method = opt_str(request, "method", "random")
    seed = p(request, "seed")
    rng = random.Random(seed) if seed is not None else random.Random()
    if method == "systematic":
        k = max(1, len(rows) // n)
        picked = rows[::k][:n]
    elif method == "random":
        picked = rng.sample(rows, min(n, len(rows)))
    else:
        raise ValueError("method 支持 random/systematic")
    return ok({"sample": picked, "picked": len(picked), "from": len(rows), "method": method})


@endpoint()
def transform_normalize(request):
    """字段归一化：minmax / zscore，就地生成 field_norm 列。"""
    rows, _ = load_rows(request)
    fields = req_list(request, "fields")
    method = opt_str(request, "method", "minmax")
    out = [dict(r) for r in rows]
    for f in fields:
        vals = [r[f] for r in rows if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)]
        if len(vals) < 2:
            continue
        if method == "minmax":
            lo, hi = min(vals), max(vals)
            rng = (hi - lo) or 1.0
            for r in out:
                if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool):
                    r[f"{f}_norm"] = round((r[f] - lo) / rng, 6)
        elif method == "zscore":
            mu, sd = mean(vals), stdev(vals) or 1.0
            for r in out:
                if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool):
                    r[f"{f}_norm"] = round((r[f] - mu) / sd, 6)
        else:
            raise ValueError("method 支持 minmax/zscore")
    return ok({"rows": out, "method": method, "fields": fields, "count": len(out)})


@endpoint()
def transform_sort(request):
    """行排序：多字段、支持数字/字符串混排与倒序。"""
    rows, _ = load_rows(request)
    by = req_list(request, "by")
    if isinstance(by, str):
        by = [by]
    order = opt_str(request, "order", "asc").lower()
    reverse = order == "desc"

    def key_fn(r):
        out = []
        for f in by:
            v = r.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((0, float(v)))
            elif v in (None, ""):
                out.append((2, 0.0))  # 缺失值垫底，不阻塞排序
            else:
                out.append((1, str(v)))
        return tuple(out)
    try:
        sorted_rows = sorted(rows, key=key_fn, reverse=reverse)
    except TypeError:
        raise ValueError("排序字段类型混杂（同字段需同为数字或文本）")
    return ok({"rows": sorted_rows, "count": len(sorted_rows), "by": by, "order": order})


# =====================================================================
# calc 数据计算器（5）
# =====================================================================


def _eval_row_expr(expr, row):
    """行级安全表达式（ast 白名单：字段为变量，仅数值字段参与）。"""
    import ast

    allowed = {k: float(v) for k, v in row.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    funcs = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt, "log": math.log}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in allowed:
                return allowed[node.id]
            raise ValueError(f"字段 {node.id} 不是数值列或不存在")
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod):
            l, r = ev(node.left), ev(node.right)
            return {ast.Add: l + r, ast.Sub: l - r, ast.Mult: l * r,
                    ast.Div: l / r, ast.Pow: l ** r, ast.Mod: l % r}[type(node.op)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
            return funcs[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"表达式不支持: {type(node).__name__}")

    return ev(ast.parse(expr, mode="eval").body)


@endpoint()
def calc_expr_row(request):
    """行级公式列：如 revenue - cost 生成新列 profit。"""
    rows, _ = load_rows(request)
    expr = req_str(request, "expr")
    name = opt_str(request, "name", "calc")[:40]
    if not re.fullmatch(r"[\w\u4e00-\u9fff]+", name):
        raise ValueError("新列名只能包含中英文/数字/下划线")
    out, errors = [], 0
    for r in rows:
        row = dict(r)
        try:
            row[name] = round(_eval_row_expr(expr, row), 6)
        except (ValueError, ZeroDivisionError, OverflowError):
            row[name] = None
            errors += 1
        out.append(row)
    computed = [r[name] for r in out if r[name] is not None]
    return ok({"rows": out, "column": name, "computed": len(computed), "errors": errors,
               "min": min(computed) if computed else None, "max": max(computed) if computed else None})


@endpoint()
def calc_pct_change(request):
    """环比/同比变化率序列：[(cur-prev)/prev]。"""
    values = req_list(request, "values")
    try:
        vals = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values 必须是数字数组")
    if len(vals) < 2:
        raise ValueError("至少 2 个值")
    changes = []
    for i in range(1, len(vals)):
        prev = vals[i - 1]
        changes.append(None if prev == 0 else round((vals[i] - prev) / abs(prev) * 100, 4))
    return ok({"values": vals, "pct_changes": changes,
               "biggest_jump": max((c for c in changes if c is not None), default=None),
               "biggest_drop": min((c for c in changes if c is not None), default=None)})


@endpoint()
def calc_weighted(request):
    """加权计算：加权平均 / 总分 / 归一化权重。"""
    items = req_list(request, "items")
    try:
        pairs = [(float(i["value"]), float(i.get("weight", 1))) for i in items]
    except (TypeError, KeyError, ValueError):
        raise ValueError('items 每项需为 {value, weight}')
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        raise ValueError("权重总和必须 > 0")
    wmean = sum(v * w for v, w in pairs) / total_w
    return ok({"weighted_mean": round(wmean, 6), "total_weight": total_w,
               "weighted_total": round(sum(v * w for v, w in pairs), 6),
               "normalized_weights": [round(w / total_w, 4) for _, w in pairs],
               "items": [{"value": v, "weight": w, "share": round(w / total_w * 100, 2)} for v, w in pairs]})


@endpoint()
def calc_running_total(request):
    """累计值：running total / running mean / 增量。"""
    values = req_list(request, "values")
    try:
        vals = [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values 必须是数字数组")
    total, out = 0.0, []
    for i, v in enumerate(vals, 1):
        total += v
        out.append({"i": i, "value": v, "running_total": round(total, 6),
                    "running_mean": round(total / i, 6), "delta": round(v - vals[i - 2], 6) if i > 1 else None})
    return ok({"series": out, "final_total": round(total, 6), "count": len(vals)})


@endpoint()
def calc_vlookup(request):
    """两表按键左连接合并（vlookup/join）。"""
    rows, _ = load_rows(request)
    lookup_rows = p(request, "lookup_rows")
    if isinstance(lookup_rows, str):
        lookup_rows = json.loads(lookup_rows)
    if not isinstance(lookup_rows, list):
        raise ValueError("lookup_rows 必须是数组")
    key = req_str(request, "key")
    fields = p(request, "fields") or sorted({k for r in lookup_rows if isinstance(r, dict) for k in r} - {key})
    index_map = {}
    for r in lookup_rows:
        if isinstance(r, dict):
            index_map.setdefault(str(r.get(key)), r)
    merged, hit = [], 0
    for r in rows:
        m = index_map.get(str(r.get(key)))
        row = dict(r)
        if m:
            hit += 1
            for f in fields:
                if f != key and f in m:
                    row[f] = m[f]
        row.setdefault("_matched", bool(m))
        merged.append(row)
    return ok({"rows": merged, "matched": hit, "unmatched": len(rows) - hit,
               "key": key, "brought_fields": [f for f in fields if f != key]})


DATA_FAMILY_COUNT = 6 + 5 + 6 + 5  # = 22（不含 S26 追加 5 个）


# =====================================================================
# 第三轮 S26（406–410）：特征展开 / 时序移位 / PII 脱敏 / 取值画像 / 导出
# =====================================================================


def _build_columns(ds, rows, extra=None):
    """列定义：原 columns → 行里出现的新键 → 本次新增列（extra=[(name,type)]）。"""
    out, seen = [], set()
    for c in (getattr(ds, "columns", None) or []):
        if isinstance(c, dict) and c.get("name") and c["name"] not in seen:
            out.append({"name": c["name"], "type": c.get("type", "string")})
            seen.add(c["name"])
    for r in rows:
        for k in r:
            if k not in seen:
                out.append({"name": k, "type": "string"})
                seen.add(k)
    for name, typ in (extra or []):
        if name not in seen:
            out.append({"name": name, "type": typ})
            seen.add(name)
    return out


def _save_transform_version(ds, user, rows, columns, note):
    """把变换结果落成新 DatasetVersion（照抄 views_plus.snapshot_version 的落版口径）。

    与 snapshot_version 的区别：快照内容来自变换后的 rows，而不是 Dataset.rows；
    rows 内联入库（≤5000 行规模可控），不写 MEDIA，MEDIA 不可写时行为一致。
    """
    import hashlib

    payload = json.dumps(rows or [], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    last = ds.versions.order_by("-version").first()
    if last is not None and last.rows_hash == h:
        return last, False
    version = (last.version if last else 0) + 1
    obj = DatasetVersion.objects.create(
        dataset=ds, version=version, rows_hash=h, row_count=len(rows),
        columns=columns or [], rows=rows, storage_path="",
        note=(note or "")[:200],
        created_by=user if getattr(user, "pk", None) else None,
    )
    return obj, True


def _persist(ds, user, rows, columns, note):
    """落版并返回 (version_dict|None, error|None)，失败不影响接口主体结果。"""
    if ds is None:
        return None, "未传 dataset_id，变换结果未落版本"
    try:
        version, created = _save_transform_version(ds, user, rows, columns, note)
    except Exception as e:  # noqa: BLE001 —— 落版失败降级
        return None, f"{type(e).__name__}: {e}"
    return {"id": version.pk, "version": version.version, "created": created,
            "row_count": version.row_count, "note": version.note}, None


@endpoint()
def transform_one_hot(request):
    """406 独热编码：field 的 TOP N 取值展开为 0/1 列，落新 DatasetVersion。"""
    rows, ds = load_rows(request)
    field = req_str(request, "field")
    if not rows:
        raise ValueError("rows 为空")
    if not any(field in r for r in rows):
        raise ValueError(f"字段 {field} 不存在")
    top_n = int(req_num(request, "top_n", 10, minimum=1, maximum=50, integer=True))
    with_other = opt_bool(request, "other", True)

    counter = {}
    for r in rows:
        raw = r.get(field)
        key = "" if raw is None else str(raw)
        counter[key] = counter.get(key, 0) + 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0] == "", kv[0]))
    kept = ranked[:top_n]
    kept_values = [v for v, _ in kept]

    used, mapping = set(), []
    for value, count in kept:
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value).strip("_")[:30] or "empty"
        name, i = f"{field}_{slug}", 2
        while name in used:
            name = f"{field}_{slug}_{i}"
            i += 1
        used.add(name)
        mapping.append({"value": value if value != "" else "(空)",
                        "raw": value, "column": name, "count": count,
                        "pct": round(count / len(rows) * 100, 2)})
    other_col = f"{field}_other" if with_other and len(ranked) > len(kept) else None

    out = []
    for r in rows:
        raw = r.get(field)
        key = "" if raw is None else str(raw)
        new = dict(r)
        for m in mapping:
            new[m["column"]] = 1 if key == m["raw"] else 0
        if other_col:
            new[other_col] = 0 if key in kept_values else 1
        out.append(new)

    new_columns = [m["column"] for m in mapping] + ([other_col] if other_col else [])
    columns = _build_columns(ds, out, [(c, "number") for c in new_columns])
    version, err = _persist(ds, request.user, out, columns, f"one-hot {field} top{top_n}")
    return ok({
        "field": field,
        "top_n": top_n,
        "new_columns": new_columns,
        "other_column": other_col,
        "mapping": mapping,
        "unique": len(ranked),
        "coverage": round(sum(c for _, c in kept) / len(rows) * 100, 2),
        "rows": out,
        "preview": out[:20],
        "total_rows": len(out),
        "version": version,
        "version_error": err,
    })


def _order_key(field):
    """排序键：数字优先、缺失垫底（与 transform_sort 同口径）。"""

    def key_fn(r):
        v = r.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return (0, float(v), "")
        if v in (None, ""):
            return (2, 0.0, "")
        return (1, 0.0, str(v))

    return key_fn


@endpoint()
def transform_lag(request):
    """407 时序位移：按 order_by 排序后生成 lag/lead 列，落新 DatasetVersion。"""
    rows, ds = load_rows(request)
    field = req_str(request, "field")
    if not rows:
        raise ValueError("rows 为空")
    if not any(field in r for r in rows):
        raise ValueError(f"字段 {field} 不存在")
    order_by = opt_str(request, "order_by").strip()
    periods = int(req_num(request, "periods", 1, minimum=1, maximum=12, integer=True))
    if order_by and not any(order_by in r for r in rows):
        raise ValueError(f"排序字段 {order_by} 不存在")

    ordered = list(rows) if not order_by else sorted(rows, key=_order_key(order_by))
    values = [r.get(field) for r in ordered]
    new_columns = []
    for k in range(1, periods + 1):
        new_columns.extend([f"{field}_lag{k}", f"{field}_lead{k}"])

    out = []
    for i, r in enumerate(ordered):
        new = dict(r)
        for k in range(1, periods + 1):
            new[f"{field}_lag{k}"] = values[i - k] if i - k >= 0 else None
            new[f"{field}_lead{k}"] = values[i + k] if i + k < len(values) else None
        if order_by:
            new["_row_no"] = i + 1
        out.append(new)

    columns = _build_columns(ds, out, [(c, "number") for c in new_columns])
    version, err = _persist(ds, request.user, out, columns,
                            f"lag/lead {field} ×{periods}" + (f" by {order_by}" if order_by else ""))
    return ok({
        "field": field,
        "order_by": order_by or None,
        "periods": periods,
        "new_columns": new_columns,
        "rows": out,
        "preview": out[:20],
        "total_rows": len(out),
        "version": version,
        "version_error": err,
        "hint": "lag = 前 periods 行取值，lead = 后 periods 行取值，边界为 null",
    })


_PII_RULES = (
    # 顺序敏感：身份证 → 银行卡 → 手机号 → 邮箱（先长后短，避免二次命中）
    ("id_card", re.compile(r"(?<!\d)(\d{6})(?:\d{8})(\d{3}[\dXx])(?!\d)"),
     lambda m: m.group(1) + "********" + m.group(2).upper()),
    ("bank_card", re.compile(r"(?<!\d)(\d{4})(\d{8,11})(\d{4})(?!\d)"),
     lambda m: m.group(1) + "*" * len(m.group(2)) + m.group(3)),
    ("phone", re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"),
     lambda m: m.group(1) + "****" + m.group(2)),
    ("email", re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
     lambda m: m.group(1) + "***" + m.group(2)),
)


@endpoint()
def transform_mask_pii(request):
    """408 PII 脱敏：手机/邮箱/身份证/银行卡正则替换后落新 DatasetVersion。"""
    rows, ds = load_rows(request)
    if not rows:
        raise ValueError("rows 为空")
    raw_fields = p(request, "fields")
    if isinstance(raw_fields, str) and raw_fields.strip():
        try:
            raw_fields = json.loads(raw_fields)
        except json.JSONDecodeError:
            raw_fields = [x.strip() for x in raw_fields.split(",") if x.strip()]
    if raw_fields:
        fields = [str(f) for f in raw_fields]
    else:
        fields = [k for k in rows[0].keys()]
    if len(fields) > 50:
        raise ValueError("单次最多脱敏 50 个字段")
    missing = [f for f in fields if not any(f in r for r in rows)]
    if missing:
        raise ValueError(f"字段不存在: {', '.join(missing[:3])}")

    out, hits = [], {}
    for r in rows:
        new = dict(r)
        for f in fields:
            v = new.get(f)
            if not isinstance(v, str) or not v:
                continue
            text, field_hits = v, {}
            for kind, pattern, repl in _PII_RULES:
                text, n = pattern.subn(repl, text)
                if n:
                    field_hits[kind] = n
                    hits[kind] = hits.get(kind, 0) + n
            if field_hits:
                summary = hits.setdefault("_by_field", {})
                for kind, n in field_hits.items():
                    summary.setdefault(f, {})
                    summary[f][kind] = summary[f].get(kind, 0) + n
                new[f] = text
        out.append(new)

    by_field = hits.pop("_by_field", {})
    total = sum(hits.values())
    masked_fields = sorted(by_field.keys())
    columns = _build_columns(ds, out)
    version, err = _persist(ds, request.user, out, columns,
                            f"mask-pii {', '.join(masked_fields[:5]) or '无命中'}")
    return ok({
        "fields": fields,
        "masked_fields": masked_fields,
        "hits": hits,
        "by_field": by_field,
        "total_hits": total,
        "rows": out,
        "preview": out[:20],
        "total_rows": len(out),
        "version": version,
        "version_error": err,
        "rules": ["id_card", "bank_card", "phone", "email"],
    })


@endpoint(("GET",))
def profile_unique_values(request):
    """409 取值分布：去重值 + 计数 TOP N + 占比（供画像页图表渲染）。"""
    rows, _ = load_rows(request)
    field = req_str(request, "field")
    if not rows:
        raise ValueError("rows 为空")
    if not any(field in r for r in rows):
        raise ValueError(f"字段 {field} 不存在")
    limit = int(req_num(request, "limit", 20, minimum=1, maximum=100, integer=True))

    counter, blanks = {}, 0
    for r in rows:
        v = r.get(field)
        if v is None or (isinstance(v, str) and not v.strip()):
            blanks += 1
            continue
        key = str(v)
        counter[key] = counter.get(key, 0) + 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    total = len(rows)
    items = [{"value": k, "count": c, "pct": round(c / total * 100, 2), "rank": i + 1}
             for i, (k, c) in enumerate(ranked[:limit])]
    shown = sum(i["count"] for i in items)
    return ok({
        "field": field,
        "total": total,
        "unique": len(counter),
        "blank": blanks,
        "limit": limit,
        "items": items,
        "other_values": max(0, len(ranked) - len(items)),
        "other_count": max(0, total - blanks - shown),
        "coverage": round(shown / total * 100, 2) if total else 0,
        "truncated": len(ranked) > len(items),
    })


def _export_cell(value):
    """导出单元格：None → 空串，嵌套结构 → JSON 文本。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False)


@endpoint(("GET",))
def dataset_export(request, pk):
    """410 数据集导出：fmt=csv（默认，core.platform.csv_response）| json。"""
    from django.http import HttpResponse

    try:
        ds = Dataset.objects.get(pk=pk)
    except Dataset.DoesNotExist:
        raise ValueError("数据集不存在")
    if not is_visible(ds, request.user):
        raise ValueError("无权导出该数据集")
    fmt = opt_str(request, "fmt", "csv").lower() or "csv"
    if fmt not in ("csv", "json"):
        raise ValueError("fmt 支持 csv/json")
    rows = ds.rows or []
    cols = [c["name"] for c in (ds.columns or [])
            if isinstance(c, dict) and c.get("name")]
    for r in rows:
        if isinstance(r, dict):
            for k in r:
                if k not in cols:
                    cols.append(k)
    raw_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", ds.name or "").strip("_")[:40]
    safe = f"dataset-{ds.pk}" + (f"-{raw_name}" if raw_name else "")

    if fmt == "json":
        payload = json.dumps({"id": ds.id, "name": ds.name, "description": ds.description,
                              "columns": ds.columns or [], "row_count": len(rows),
                              "rows": rows}, ensure_ascii=False)
        resp = HttpResponse(payload, content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = f"attachment; filename={safe}.json"
        return resp

    from core.platform import csv_response

    body = [[_export_cell(r.get(c)) if isinstance(r, dict) else "" for c in cols] for r in rows]
    return csv_response(f"{safe}.csv", cols, body)
