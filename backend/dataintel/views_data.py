# -*- coding: utf-8 -*-
"""dataintel · 数据面接口：dataset(6) profile(5) transform(6) calc(5) = 22 个。

行数据来源统一走 load_rows()：可直接传 rows 数组，或传 dataset_id 从库里取
（dataset 归属走 core.scoping 行级权限收口）。
"""
import json
import math
import random
import re

from core.scoping import is_visible, scope_queryset

from dataintel.models import Dataset
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
    if mode == "replace":
        ds.rows = rows
    else:
        ds.rows = (ds.rows or []) + rows
    ds.row_count = len(ds.rows)
    if ds.row_count > 5000:
        raise ValueError("超过 5000 行上限，请改用 replace 或先清理")
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


DATA_FAMILY_COUNT = 6 + 5 + 6 + 5  # = 22
