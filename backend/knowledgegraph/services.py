# -*- coding: utf-8 -*-
"""knowledgegraph 服务层：图算法、实体解析、合并拆分、规则抽取、DSL、统计与快照。

为什么把算法放在服务层而不是视图里：
- 图遍历 / 最短路 / 社区检测都是纯计算，输入是「实体列表 + 关系列表」，
  与 ORM、请求上下文无关，放在这里可以单独测试，也方便以后换存储；
- 视图只负责按数据范围取数（scope_queryset）与组装响应，避免每个接口
  各写一份过滤逻辑，出现「某个接口忘了过滤已删除边」这类系统性错误；
- 所有遍历入口统一做规模校验（深度 ≤ 5、节点 ≤ 500），超限直接抛
  ValueError（视图层转 400），而不是悄悄截断返回一个不可信的结果。

数据形态约定：
- 实体 lite dict：{"id", "name", "canonical_name", "entity_type_id",
  "confidence", "status", "description", "attrs", "created_at"}；
- 关系 lite dict：{"id", "src", "dst", "type_id", "weight", "confidence"}；
- 邻接表：{"out": {id: [edge]}, "in": {id: [edge]}}，edge 额外带 other 字段，
  由 build_adjacency 统一生成，遍历函数不再自己判断方向。
"""
import heapq
import math
import random
import re
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from knowledgegraph.models import (MAX_GRAPH_NODES, MAX_TRAVERSAL_DEPTH,
                                   NAME_SUFFIX_NOISE, PUNCTUATION_CHARS,
                                   Entity, EntityAlias, EntityTag, GraphAudit,
                                   MergeLog, PathCache, Relation, clamp_confidence)

# ---------------------------------------------------------------------------
# 常量：DSL 支持的四类查询 + 抽取模式
# ---------------------------------------------------------------------------

DSL_KINDS = ("neighbors", "path", "subgraph", "search")

DSL_ALLOWED_KEYS = {
    "neighbors": {"entity_id", "depth", "direction", "types", "min_weight",
                  "min_confidence", "limit"},
    "path": {"start", "end", "max_depth", "weighted", "direction", "types"},
    "subgraph": {"start", "depth", "direction", "types", "min_weight",
                 "min_confidence", "limit"},
    "search": {"q", "limit", "types", "min_confidence"},
}

DSL_REQUIRED_KEYS = {
    "neighbors": {"entity_id"},
    "path": {"start", "end"},
    "subgraph": {"start"},
    "search": {"q"},
}

# 规则抽取：中文关系表达高度模式化，词典 + 正则足以覆盖办公语料里的
# 主体-关系-客体三元组；这里刻意不接 LLM，保证离线、可解释、可复现。
EXTRACTION_PATTERNS = (
    {
        "code": "belongs_to",
        "name": "属于",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"(?:属于|隶属于|归属于|隶属|归属)"
                 r"(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30})",
        "confidence": 0.78,
    },
    {
        "code": "located_in",
        "name": "位于",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"(?:位于|坐落于|地处)"
                 r"(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30})",
        "confidence": 0.8,
    },
    {
        "code": "owner_of",
        "name": "负责人",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"的(?:负责人|主管|经理|校长|院长|CEO|总经理)"
                 r"(?:是|为)"
                 r"(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30})",
        "confidence": 0.75,
    },
    {
        "code": "part_of",
        "name": "组成部分",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"是(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"的(?:一部分|组成部分|下属|子公司|子部门)",
        "confidence": 0.72,
    },
    {
        "code": "partners_with",
        "name": "合作",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"(?:与|和)(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"(?:合作|合资|签署|共建)",
        "confidence": 0.62,
    },
    {
        "code": "invests_in",
        "name": "投资",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"投资(?:了)?(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30})",
        "confidence": 0.66,
    },
    {
        "code": "contains",
        "name": "包含",
        "regex": r"(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?)"
                 r"(?:包含|包括|下设)(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30})",
        "confidence": 0.6,
    },
)

# 名称规范化时的同义词：把常见全称 / 别称折叠到同一规范形式。
# 只收录「确定无歧义」的映射，避免把「一中」误折成「第一中学」这类扩张。
NAME_SYNONYMS = {
    "人工智能": ("ai", "artificialintelligence"),
    "信息技术": ("it", "informationtechnology"),
    "研发部": ("研究与开发部", "r&d"),
    "人力资源部": ("人事部", "hr"),
    "财务部": ("财务处", "finance"),
    "市场部": ("营销部", "marketing"),
}

# 供前端展示的抽取模式目录（不含正则原文，避免把实现细节暴露给界面）
PATTERN_CATALOG = tuple(
    {"code": item["code"], "name": item["name"], "confidence": item["confidence"]}
    for item in EXTRACTION_PATTERNS
)

# 名称相似度超过该阈值才建议合并：0.82 是在「简称 vs 全称」与
# 「同名前缀的不同实体」之间的经验折中，低于它误报会明显变多。
MERGE_SIMILARITY_THRESHOLD = 0.82


# ---------------------------------------------------------------------------
# 0. 小工具
# ---------------------------------------------------------------------------


def clamp(value, default=0.8):
    """置信度 / 权重夹取到 [0,1]，非法值回落默认。"""
    return clamp_confidence(value, default)


def entity_lite(entity):
    """把 Entity 实例压成算法层需要的轻量字典（避免算法反向依赖 ORM）。"""
    return {
        "id": entity.id,
        "ontology_id": entity.ontology_id,
        "name": entity.name,
        "canonical_name": entity.canonical_name or normalize_name(entity.name),
        "entity_type_id": entity.entity_type_id,
        "confidence": entity.confidence,
        "status": entity.status,
        "description": entity.description or "",
        "attrs": entity.attrs or {},
        "created_at": entity.created_at,
    }


def relation_lite(relation):
    """关系实例 → 算法层字典。"""
    rtype = getattr(relation, "relation_type", None)
    return {
        "id": relation.id,
        "src": relation.source_entity_id,
        "dst": relation.target_entity_id,
        "type_id": relation.relation_type_id,
        "weight": relation.weight,
        "confidence": relation.confidence,
        "directed": True if rtype is None else bool(rtype.directed),
    }


def entities_lite(queryset):
    """批量压缩实体（列表推导保持与 queryset 一致的顺序）。"""
    return [entity_lite(e) for e in queryset]


def relations_lite(queryset):
    """批量压缩关系。"""
    return [relation_lite(r) for r in queryset]


# ---------------------------------------------------------------------------
# 1. 名称规范化与相似度（实体解析基础）
# ---------------------------------------------------------------------------


def _strip_punctuation(text):
    """把标点替换为空格再压缩：直接删除会让「A-B」与「AB」意外粘连。"""
    chars = [" " if ch in PUNCTUATION_CHARS else ch for ch in text]
    return "".join(chars)


def normalize_name(name):
    """名称规范化：全半角、大小写、标点、空白、企业后缀、同义词。

    规范化结果用于去重与检索，不用于展示：原始写法保留在 Entity.name，
    规范名写 Entity.canonical_name，两者分离才能在「保留原文」与
    「准确去重」之间同时满足。
    """
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = text.casefold()
    text = _strip_punctuation(text)
    words = text.split()
    joined = "".join(words)
    # 后缀剔除放在去空格之后：中英文后缀在去空格后都能命中
    for suffix in NAME_SUFFIX_NOISE:
        suffix_norm = "".join(_strip_punctuation(suffix.casefold()).split())
        if suffix_norm and joined.endswith(suffix_norm) and len(joined) > len(suffix_norm):
            joined = joined[: -len(suffix_norm)]
            break
    # 同义词折叠：命中任一别称就替换为规范词（只替换一次，避免循环映射）
    for canonical, synonyms in NAME_SYNONYMS.items():
        for synonym in synonyms:
            syn = "".join(_strip_punctuation(synonym.casefold()).split())
            if syn and syn in joined:
                joined = joined.replace(syn, canonical)
                break
    return joined.strip()


def name_tokens(name):
    """名称切词：中文按字二元组、拉丁按词，输出用于 Jaccard 的 token 集合。

    不引入分词依赖：二元组对中文实体名的区分度足够，且对简称 / 全称
    这类「部分包含」关系天然友好（"腾讯" 的 bigram 是 "腾讯"，
    "腾讯科技" 的 bigram 包含 "腾讯" 与 "讯科" 等，Jaccard 不会过低）。
    """
    text = normalize_name(name)
    tokens = set()
    latin = re.findall(r"[a-z0-9]+", text)
    tokens.update(latin)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    if len(cjk) == 1:
        tokens.add(cjk[0])
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i] + cjk[i + 1])
    return tokens


def levenshtein(a, b, max_len=200):
    """编辑距离（滚动数组 O(min(n,m)) 空间）。

    超长名称截断到 max_len：图谱名称极少超过 200 字，无上限会让
    批量查重的复杂度失控，且截断对「是否重复」的判断影响可以忽略。
    """
    a = str(a or "")[:max_len]
    b = str(b or "")[:max_len]
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def jaccard(a_tokens, b_tokens):
    """集合 Jaccard；两边都为空视为 0（不是 1，空名称不应互相「完全相似」）。"""
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return inter / union if union else 0.0


def similarity(name_a, name_b):
    """综合相似度 = 0.6 × 编辑距离相似度 + 0.4 × token Jaccard。

    规范化后完全相同直接返回 1：避免「大小写不同但本质同名」被算法
    的字符差异扣分，导致绝对应该合并的候选反而排不到前面。
    """
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    longest = max(len(norm_a), len(norm_b))
    edit_score = 1.0 - (levenshtein(norm_a, norm_b) / longest) if longest else 0.0
    token_score = jaccard(name_tokens(norm_a), name_tokens(norm_b))
    score = 0.6 * edit_score + 0.4 * token_score
    # 包含关系是实体去重里最强的信号之一（「腾讯」/「腾讯科技」/「腾讯云」）：
    # 纯字符编辑距离会把「腾讯科技」判成 0.5 左右，低于人工合并阈值，
    # 这里给出 0.8 起的保底分，同时保留短名比例，避免「中国」吞掉「中国银行」。
    short, long = sorted((norm_a, norm_b), key=len)
    if short and short in long:
        containment = 0.8 + 0.2 * len(short) / len(long)
        score = max(score, containment)
    return round(max(0.0, min(1.0, score)), 4)


def duplicate_suggestions(entities, threshold=MERGE_SIMILARITY_THRESHOLD,
                          same_type_only=True, limit=50):
    """找出可能重复的实体对（合并建议）。

    先用「规范名长度差」剪枝：长度差超过 40% 的名称几乎不可能相似，
    剪掉后再算编辑距离，避免 1500 个实体两两比较时的平方级开销。
    实体规模上限 2000，超过只比较前 2000 个并在结果里标注 truncated。
    """
    rows = list(entities)[:2000]
    truncated = len(list(entities)) > 2000
    suggestions = []
    for i in range(len(rows)):
        a = rows[i]
        norm_a = a.get("canonical_name") or normalize_name(a.get("name", ""))
        if not norm_a:
            continue
        for j in range(i + 1, len(rows)):
            b = rows[j]
            if same_type_only and a.get("entity_type_id") != b.get("entity_type_id"):
                continue
            norm_b = b.get("canonical_name") or normalize_name(b.get("name", ""))
            if not norm_b:
                continue
            short_name, long_name = sorted((norm_a, norm_b), key=len)
            # 包含关系（腾讯 / 腾讯科技）不允许被长度差剪枝误杀
            if short_name and short_name not in long_name and \
                    (len(long_name) - len(short_name)) / len(long_name) > 0.4:
                continue
            score = similarity(norm_a, norm_b)
            if score < threshold:
                continue
            suggestions.append({
                "source_id": a["id"],
                "source_name": a.get("name", ""),
                "target_id": b["id"],
                "target_name": b.get("name", ""),
                "score": score,
                "reason": "规范名一致" if norm_a == norm_b else "名称高度相似",
            })
    suggestions.sort(key=lambda x: (-x["score"], x["source_id"]))
    return {"items": suggestions[:limit], "count": len(suggestions),
            "threshold": threshold, "truncated": truncated}


def merge_preview(source, target):
    """合并预览：不写库，先告诉用户会迁移多少关系 / 别名 / 标签。"""
    if source.id == target.id:
        raise ValueError("不能把实体合并到自身")
    relations = Relation.objects.filter(
        Q(source_entity=source) | Q(target_entity=source), status="active")
    aliases = EntityAlias.objects.filter(entity=source)
    tags = EntityTag.objects.filter(entity=source)
    self_loops = 0
    for rel in relations:
        new_src = target.id if rel.source_entity_id == source.id else rel.source_entity_id
        new_dst = target.id if rel.target_entity_id == source.id else rel.target_entity_id
        if new_src == new_dst:
            self_loops += 1
    return {
        "source": {"id": source.id, "name": source.name},
        "target": {"id": target.id, "name": target.name},
        "relation_count": relations.count(),
        "alias_count": aliases.count(),
        "tag_count": tags.count(),
        "self_loops_after_merge": self_loops,
        "similarity": similarity(source.name, target.name),
    }


# ---------------------------------------------------------------------------
# 2. 图结构：邻接表、遍历、子图、最短路
# ---------------------------------------------------------------------------


def build_adjacency(relations, directed=True):
    """构建正向 / 反向邻接表。

    反向表始终构建：direction="in" 与 "both" 都依赖它；无向图把每条边
    同时写进两个方向，遍历函数无需再区分「是否无向」。
    """
    out = defaultdict(list)
    incoming = defaultdict(list)
    for rel in relations:
        src = rel["src"]
        dst = rel["dst"]
        base = {
            "id": rel.get("id"),
            "type_id": rel.get("type_id"),
            "weight": float(rel.get("weight") or 1.0),
            "confidence": float(rel.get("confidence") or 0.8),
        }
        out[src].append({**base, "src": src, "dst": dst, "other": dst})
        incoming[dst].append({**base, "src": src, "dst": dst, "other": src})
        # 单条无向边（关系类型 directed=False）也要能反向遍历；
        # 全局 directed=False 则整张图按无向处理。
        if not directed or rel.get("directed") is False:
            out[dst].append({**base, "src": dst, "dst": src, "other": src})
            incoming[src].append({**base, "src": dst, "dst": src, "other": dst})
    return {"out": dict(out), "in": dict(incoming)}


def edge_allowed(edge, type_ids=None, min_weight=None, min_confidence=None):
    """边过滤：类型白名单、权重下限、置信度下限。

    过滤器集中在这里，遍历 / 最短路 / 统计共用同一套判定，
    避免「子图查得到、最短路查不到」这种口径不一致。
    """
    if type_ids and edge.get("type_id") not in type_ids:
        return False
    if min_weight is not None and float(edge.get("weight") or 0) < float(min_weight):
        return False
    if min_confidence is not None and float(edge.get("confidence") or 0) < float(min_confidence):
        return False
    return True


def _neighbor_edges(node, adjacency, direction):
    """按方向取 node 的候选边；both 合并正反向并按边 id 去重。"""
    if direction == "out":
        return list(adjacency["out"].get(node, []))
    if direction == "in":
        return list(adjacency["in"].get(node, []))
    seen = set()
    merged = []
    for edge in adjacency["out"].get(node, []) + adjacency["in"].get(node, []):
        key = edge.get("id")
        if key is None:
            key = (edge["src"], edge["dst"], edge.get("type_id"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(edge)
    return merged


def traverse(start_id, adjacency, depth=1, direction="both", type_ids=None,
             min_weight=None, min_confidence=None, limit=MAX_GRAPH_NODES):
    """BFS 遍历：返回 reachable 节点（带最短跳数）与途经边。

    这是邻居 / 子图两个接口的公共内核；limit 同时约束返回节点数，
    超限抛 ValueError，由视图转 400，绝不静默截断。
    """
    if depth < 1 or depth > MAX_TRAVERSAL_DEPTH:
        raise ValueError(f"遍历深度必须在 1–{MAX_TRAVERSAL_DEPTH} 之间")
    if limit < 1 or limit > MAX_GRAPH_NODES:
        raise ValueError(f"返回节点上限必须在 1–{MAX_GRAPH_NODES} 之间")
    if direction not in ("out", "in", "both"):
        raise ValueError("direction 仅支持 out/in/both")
    distances = {start_id: 0}
    queue = deque([start_id])
    edges = []
    edge_seen = set()
    while queue:
        node = queue.popleft()
        current_depth = distances[node]
        if current_depth >= depth:
            continue
        for edge in _neighbor_edges(node, adjacency, direction):
            if not edge_allowed(edge, type_ids, min_weight, min_confidence):
                continue
            key = edge.get("id")
            if key is None:
                key = (edge["src"], edge["dst"], edge.get("type_id"))
            if key not in edge_seen:
                edge_seen.add(key)
                edges.append({
                    "id": edge.get("id"),
                    "source": edge["src"],
                    "target": edge["dst"],
                    "type_id": edge.get("type_id"),
                    "weight": edge.get("weight"),
                    "confidence": edge.get("confidence"),
                    "depth": current_depth + 1,
                })
            other = edge["other"]
            if other not in distances:
                if len(distances) >= limit:
                    raise ValueError(
                        f"返回节点数超过上限 {limit}，请缩小深度或增加类型/权重过滤")
                distances[other] = current_depth + 1
                queue.append(other)
    nodes = [{"id": node, "distance": dist} for node, dist in
             sorted(distances.items(), key=lambda kv: (kv[1], kv[0]))]
    return {"nodes": nodes, "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges)}


def neighbors(start_id, adjacency, direction="both", depth=1, type_ids=None,
              min_weight=None, min_confidence=None, limit=MAX_GRAPH_NODES):
    """邻居查询的语义包装：depth 默认 1，返回不含起点。"""
    result = traverse(start_id, adjacency, depth=depth, direction=direction,
                      type_ids=type_ids, min_weight=min_weight,
                      min_confidence=min_confidence, limit=limit)
    result["center"] = start_id
    result["nodes"] = [n for n in result["nodes"] if n["id"] != start_id]
    result["node_count"] = len(result["nodes"])
    return result


def subgraph(start_id, adjacency, depth=2, direction="both", type_ids=None,
             min_weight=None, min_confidence=None, limit=MAX_GRAPH_NODES):
    """K 跳子图：BFS 深度 ≤ 5、节点 ≤ 500，超出抛 ValueError。"""
    result = traverse(start_id, adjacency, depth=depth, direction=direction,
                      type_ids=type_ids, min_weight=min_weight,
                      min_confidence=min_confidence, limit=limit)
    result["center"] = start_id
    result["depth"] = depth
    return result


def dfs_order(start_id, adjacency, direction="out", type_ids=None,
              min_weight=None, min_confidence=None, limit=MAX_GRAPH_NODES):
    """DFS 先序（迭代实现，避免深图递归爆栈）。

    与 BFS 共用邻接表，但访问顺序不同：用于「按链路展开」的展示场景，
    depth 由显式栈记录，超过 MAX_TRAVERSAL_DEPTH 直接忽略后继。
    """
    visited = set()
    order = []
    stack = [(start_id, 0)]
    while stack:
        node, depth = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        order.append({"id": node, "depth": depth})
        if depth >= MAX_TRAVERSAL_DEPTH:
            continue
        for edge in _neighbor_edges(node, adjacency, direction):
            if not edge_allowed(edge, type_ids, min_weight, min_confidence):
                continue
            if edge["other"] in visited:
                continue
            stack.append((edge["other"], depth + 1))
            if len(order) + len(stack) > limit:
                raise ValueError(f"返回节点数超过上限 {limit}")
    return {"nodes": order, "node_count": len(order)}


def shortest_path(start_id, end_id, adjacency, direction="out", type_ids=None,
                  min_weight=None, min_confidence=None):
    """无权最短路（BFS）：不存在时返回空列表，而不是抛错。

    「查不到路径」是正常业务结果（两个实体本来就无关），前端需要展示
    「无关联」而不是一个红色错误，所以这里把不存在表达为空数组。
    """
    if start_id == end_id:
        return [start_id]
    previous = {start_id: None}
    queue = deque([start_id])
    while queue:
        node = queue.popleft()
        for edge in _neighbor_edges(node, adjacency, direction):
            if not edge_allowed(edge, type_ids, min_weight, min_confidence):
                continue
            other = edge["other"]
            if other in previous:
                continue
            previous[other] = node
            if other == end_id:
                return _reconstruct(previous, end_id)
            queue.append(other)
    return []


def _reconstruct(previous, end_id):
    """按前驱表回溯路径（BFS 前驱一定构成最短路）。"""
    path = []
    node = end_id
    while node is not None:
        path.append(node)
        node = previous.get(node)
    path.reverse()
    return path


def shortest_path_weighted(start_id, end_id, adjacency, direction="out",
                           type_ids=None, min_weight=None, min_confidence=None,
                           weight_mode="inverse"):
    """带权 Dijkstra：返回 (节点列表, 总代价)；不可达返回 ([], None)。

    代价口径：
    - inverse（默认）：cost = 1/weight，强关系优先，适合「找最可信的关联链」；
    - weight：cost = weight，适合把权重当距离的自定义场景。
    权重大于 0 由模型层保证（视图会夹取），这里再兜底一次除零。
    """
    if start_id == end_id:
        return [start_id], 0.0
    if weight_mode not in ("inverse", "weight"):
        raise ValueError("weight_mode 仅支持 inverse/weight")
    distances = {start_id: 0.0}
    previous = {start_id: None}
    heap = [(0.0, start_id)]
    visited = set()
    while heap:
        cost, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        if node == end_id:
            break
        for edge in _neighbor_edges(node, adjacency, direction):
            if not edge_allowed(edge, type_ids, min_weight, min_confidence):
                continue
            weight = float(edge.get("weight") or 1.0)
            if weight_mode == "inverse":
                step = 1.0 / max(weight, 0.01)
            else:
                step = max(weight, 0.0)
            new_cost = cost + step
            other = edge["other"]
            if other in visited:
                continue
            if new_cost < distances.get(other, math.inf):
                distances[other] = new_cost
                previous[other] = node
                heapq.heappush(heap, (new_cost, other))
    if end_id not in distances:
        return [], None
    return _reconstruct(previous, end_id), round(distances[end_id], 4)


def path_edges(path, relations, directed=True):
    """把节点路径还原成边序列（按路径相邻对匹配，允许无向边反向匹配）。"""
    if len(path) < 2:
        return []
    index = defaultdict(list)
    for rel in relations:
        index[(rel["src"], rel["dst"])].append(rel)
        if not directed:
            index[(rel["dst"], rel["src"])].append(rel)
    edges = []
    for a, b in zip(path, path[1:]):
        candidates = index.get((a, b)) or []
        if not candidates:
            continue
        # 同两端可能有多条类型不同的边，取权重最高的一条用于展示
        best = max(candidates, key=lambda r: (r.get("weight") or 0,
                                              r.get("confidence") or 0))
        edges.append({"source": a, "target": b, "relation_id": best.get("id"),
                      "type_id": best.get("type_id"), "weight": best.get("weight"),
                      "confidence": best.get("confidence")})
    return edges


# ---------------------------------------------------------------------------
# 3. 合并 / 拆分（事务内迁移关系，去重自环与重复边）
# ---------------------------------------------------------------------------


def _lock_entities(source_id, target_id):
    """在事务内按主键顺序锁两行，避免 AB / BA 交叉合并死锁。"""
    locked = {e.id: e for e in Entity.objects.select_for_update()
              .filter(pk__in=[source_id, target_id]).order_by("id")}
    if source_id not in locked or target_id not in locked:
        raise ValueError("源实体或目标实体不存在")
    return locked[source_id], locked[target_id]


@transaction.atomic
def merge_entities(source, target, user, reason="", request_obj=None):
    """把 source 并入 target：迁移关系 / 别名 / 标签，写合并日志与审计。

    关键规则（为什么）：
    - 禁止合并到自身：没有意义且会把自己标成 merged，图谱直接丢点；
    - 迁移后出现自环（A-B 且合并后两端相同）必须丢弃：自环会让
      路径搜索陷入自我循环，也会让度中心性虚高；
    - 迁移后出现重复边（同类型同两端）合并为一条：保留权重 / 置信度
      更高的那条，属性做浅合并，否则同一关系会在图谱里「叠影」；
    - 源实体不物理删除，status=merged 并写 merged_into：历史引用仍可解释。
    """
    if source.id == target.id:
        raise ValueError("不能把实体合并到自身")
    if source.ontology_id != target.ontology_id:
        raise ValueError("只能合并同一本体下的实体")
    locked_source, locked_target = _lock_entities(source.id, target.id)
    if locked_source.status != "active" or locked_target.status != "active":
        raise ValueError("只有生效状态的实体可以合并")

    moved = 0
    deduped = 0
    self_loops = 0
    moved_aliases = 0
    merged_tags = 0
    relations = list(Relation.objects.select_for_update().filter(
        Q(source_entity=locked_source) | Q(target_entity=locked_source),
        status="active"))
    rewritten = []

    # 阶段一：把源端替换为目标端，丢弃自环（自环会让路径搜索与度中心性虚高）
    for rel in relations:
        new_src = locked_target.id if rel.source_entity_id == locked_source.id else rel.source_entity_id
        new_dst = locked_target.id if rel.target_entity_id == locked_source.id else rel.target_entity_id
        if new_src == new_dst:
            rel.status = "deleted"
            rel.save(update_fields=["status", "updated_at"])
            self_loops += 1
            continue
        rel.source_entity_id = new_src
        rel.target_entity_id = new_dst
        rel.save(update_fields=["source_entity", "target_entity", "updated_at"])
        rewritten.append(rel)

    # 阶段二：合并「同类型 + 无向端点相同」的重复边。
    # 合并场景下 A→B 与 B→A 往往来自两条重复实体，方向差异只是录入顺序，
    # 因此按无向端点判重；保留最新的一条（pk 最大），其余吸收权重后删除。
    handled = set()
    survivors = []
    for rel in rewritten:
        if rel.id in handled:
            continue
        group = list(Relation.objects.select_for_update().filter(
            ontology_id=rel.ontology_id,
            relation_type_id=rel.relation_type_id,
            status="active",
        ).filter(
            Q(source_entity_id=rel.source_entity_id,
              target_entity_id=rel.target_entity_id)
            | Q(source_entity_id=rel.target_entity_id,
                target_entity_id=rel.source_entity_id)
        ))
        if not group:
            group = [rel]
        group_ids = {row.id for row in group}
        handled.update(group_ids)
        keep = max(group, key=lambda row: row.id)
        for row in group:
            if row.id == keep.id:
                continue
            keep.weight = max(keep.weight, row.weight)
            keep.confidence = max(keep.confidence, row.confidence)
            keep.attrs = {**(row.attrs or {}), **(keep.attrs or {})}
            row.status = "deleted"
            row.save(update_fields=["status", "updated_at"])
            deduped += 1
        keep.save(update_fields=["weight", "confidence", "attrs", "updated_at"])
        survivors.append(keep)

    # 只有「被迁移且最终保留」的边才计入 moved：被去重掉的迁移不算净迁移
    rewritten_ids = {row.id for row in rewritten}
    moved = sum(1 for keep in survivors if keep.id in rewritten_ids)

    # 别名迁移：目标已有同名别名时直接丢弃源别名，避免唯一约束冲突
    existing_aliases = {a.alias.casefold() for a in
                        EntityAlias.objects.filter(entity=locked_target)}
    for alias in EntityAlias.objects.filter(entity=locked_source):
        key = alias.alias.casefold()
        if key in existing_aliases:
            alias.delete()
            continue
        alias.entity = locked_target
        alias.save(update_fields=["entity", "updated_at"])
        existing_aliases.add(key)
        moved_aliases += 1

    # 标签合并：同标签取较大权重，其余迁移
    target_tags = {t.tag: t for t in EntityTag.objects.filter(entity=locked_target)}
    for tag in EntityTag.objects.filter(entity=locked_source):
        current = target_tags.get(tag.tag)
        if current:
            current.weight = max(current.weight, tag.weight)
            current.save(update_fields=["weight", "updated_at"])
            tag.delete()
        else:
            tag.entity = locked_target
            tag.save(update_fields=["entity", "updated_at"])
            target_tags[tag.tag] = tag
        merged_tags += 1

    # 属性浅合并：目标值优先，源值只补空缺；merged_into 保留可回放线索
    locked_target.attrs = {**(locked_source.attrs or {}), **(locked_target.attrs or {})}
    if locked_target.description == "" and locked_source.description:
        locked_target.description = locked_source.description
    locked_target.confidence = max(locked_target.confidence, locked_source.confidence)
    locked_target.save(update_fields=["attrs", "description", "confidence",
                                      "updated_at"])
    locked_source.status = "merged"
    locked_source.attrs = {**(locked_source.attrs or {}), "merged_into": locked_target.id}
    locked_source.save(update_fields=["status", "attrs", "updated_at"])

    log = MergeLog.objects.create(
        owner=user,
        request=request_obj,
        ontology_id=locked_target.ontology_id,
        source_entity=locked_source,
        target_entity=locked_target,
        moved_relations=moved,
        merged_aliases=moved_aliases,
        operator=user,
        detail={
            "reason": reason,
            "deduped_relations": deduped,
            "dropped_self_loops": self_loops,
            "merged_tags": merged_tags,
            "source_name": locked_source.name,
            "target_name": locked_target.name,
            "source_id": locked_source.id,
            "target_id": locked_target.id,
        },
    )
    GraphAudit.objects.create(
        owner=user, ontology_id=locked_target.ontology_id, action="entity.merge",
        target_type="entity", target_id=locked_target.id,
        summary=f"合并实体 {locked_source.name} → {locked_target.name}",
        detail={"log_id": log.id, "moved": moved, "deduped": deduped,
                "self_loops": self_loops, "reason": reason},
        actor=user,
    )
    # 合并改变了图结构，旧缓存必须失效，否则会返回指向已合并实体的幽灵路径
    invalidate_path_cache(locked_target.ontology_id,
                          [locked_source.id, locked_target.id])
    return {
        "source_id": locked_source.id,
        "target_id": locked_target.id,
        "moved_relations": moved,
        "deduped_relations": deduped,
        "dropped_self_loops": self_loops,
        "moved_aliases": moved_aliases,
        "merged_tags": merged_tags,
        "log_id": log.id,
    }


@transaction.atomic
def split_entity(entity, user, name, relation_ids=None, alias_ids=None,
                 entity_type=None, description=""):
    """拆分实体：新建一个实体并迁入指定的关系 / 别名。

    拆分的典型场景是「一个实体被过度合并」：人工挑出一部分关系与别名，
    迁到新实体上，原实体保持不变。两边都指向同一实体的关系迁移后
    会变成自环，直接跳过。
    """
    if entity.status != "active":
        raise ValueError("只有生效状态的实体可以拆分")
    name = (name or "").strip()
    if not name:
        raise ValueError("拆分后的实体名称不能为空")
    relation_ids = list(relation_ids or [])
    alias_ids = list(alias_ids or [])
    if not relation_ids and not alias_ids:
        raise ValueError("拆分至少需要选择一条关系或一个别名")

    new_entity = Entity.objects.create(
        owner=user,
        ontology_id=entity.ontology_id,
        entity_type=entity_type or entity.entity_type,
        name=name[:200],
        canonical_name=normalize_name(name)[:200] or name[:200],
        description=(description or "")[:2000],
        attrs={"split_from": entity.id},
        source_id=entity.source_id,
        confidence=entity.confidence,
        status="active",
        created_by=user,
    )

    moved_relations = 0
    skipped_self_loops = 0
    if relation_ids:
        rows = Relation.objects.select_for_update().filter(
            pk__in=relation_ids[:500], status="active").filter(
            Q(source_entity=entity) | Q(target_entity=entity))
        for rel in rows:
            old_src, old_dst = rel.source_entity_id, rel.target_entity_id
            if old_src == entity.id:
                rel.source_entity_id = new_entity.id
            if old_dst == entity.id:
                rel.target_entity_id = new_entity.id
            if rel.source_entity_id == rel.target_entity_id:
                # 两端都被迁到新实体 → 自环，保留没有意义
                skipped_self_loops += 1
                continue
            duplicate = Relation.objects.filter(
                ontology_id=rel.ontology_id, relation_type_id=rel.relation_type_id,
                source_entity_id=rel.source_entity_id,
                target_entity_id=rel.target_entity_id,
                status="active").exclude(pk=rel.pk).first()
            if duplicate:
                duplicate.weight = max(duplicate.weight, rel.weight)
                duplicate.save(update_fields=["weight", "updated_at"])
                rel.status = "deleted"
                rel.save(update_fields=["status", "updated_at"])
                continue
            rel.save(update_fields=["source_entity", "target_entity", "updated_at"])
            moved_relations += 1

    moved_aliases = 0
    if alias_ids:
        aliases = EntityAlias.objects.select_for_update().filter(
            pk__in=alias_ids[:500], entity=entity)
        existing = {a.alias.casefold() for a in
                    EntityAlias.objects.filter(entity=new_entity)}
        for alias in aliases:
            if alias.alias.casefold() in existing:
                continue
            alias.entity = new_entity
            alias.save(update_fields=["entity", "updated_at"])
            existing.add(alias.alias.casefold())
            moved_aliases += 1

    GraphAudit.objects.create(
        owner=user, ontology_id=entity.ontology_id, action="entity.split",
        target_type="entity", target_id=new_entity.id,
        summary=f"从 {entity.name} 拆分出 {new_entity.name}",
        detail={"from_id": entity.id, "moved_relations": moved_relations,
                "moved_aliases": moved_aliases,
                "skipped_self_loops": skipped_self_loops},
        actor=user,
    )
    invalidate_path_cache(entity.ontology_id, [entity.id, new_entity.id])
    return {
        "entity_id": new_entity.id,
        "from_id": entity.id,
        "moved_relations": moved_relations,
        "moved_aliases": moved_aliases,
        "skipped_self_loops": skipped_self_loops,
    }


# ---------------------------------------------------------------------------
# 4. 规则抽取（词典 + 正则，本地可解释）
# ---------------------------------------------------------------------------


def _sentences(text):
    """按中英文句末标点切句：正则跨句匹配会把不相邻的实体连成假关系。"""
    parts = re.split(r"[。！？!?；;\n]+", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def _dictionary_terms(dictionary):
    """把词典入参统一成 [(term, meta)]。

    支持三种形态：list[str]、dict[term, meta]、list[{name, type, ...}]，
    因为来源可能是手填词表、JSON 配置或前端表格导出的对象数组。
    """
    rows = []
    if isinstance(dictionary, dict):
        for term, meta in dictionary.items():
            rows.append((str(term), meta if isinstance(meta, dict) else {}))
    elif isinstance(dictionary, list):
        for item in dictionary:
            if isinstance(item, str):
                rows.append((item, {}))
            elif isinstance(item, dict) and item.get("name"):
                rows.append((str(item["name"]), item))
    return [(term.strip(), meta) for term, meta in rows if term and term.strip()]


def extract_candidates(text, dictionary=None, patterns=None,
                       max_candidates=200):
    """从文本中抽取候选实体与关系（纯本地规则，不联网、不调模型）。

    返回结构：
    - entity 候选：payload={type, occurrences, positions, evidence}
    - relation 候选：payload={source, target, relation_code, relation_name,
      evidence, position}
    实体候选会去重（按规范名取最高置信度）；关系候选按「源|关系|目标」
    三元组去重，避免同一句话里重复模式刷屏。
    """
    text = str(text or "")
    if len(text) > 200000:
        raise ValueError("待抽取文本超过 200000 字符，请拆分为多个来源")
    candidates = []
    entity_index = {}

    def add_entity(name, meta=None, confidence=0.6, evidence="", position=0):
        norm = normalize_name(name)
        if not norm:
            return
        current = entity_index.get(norm)
        if current:
            current["payload"]["occurrences"] += 1
            current["confidence"] = max(current["confidence"], confidence)
            if evidence and evidence not in current["payload"]["evidence"]:
                current["payload"]["evidence"] = (
                    current["payload"]["evidence"] + " / " + evidence)[-300:]
            return
        payload = {
            "type": (meta or {}).get("type") or (meta or {}).get("entity_type") or "",
            "occurrences": 1,
            "positions": [position],
            "evidence": evidence[:300],
        }
        item = {"kind": "entity", "name": name.strip()[:200],
                "payload": payload, "confidence": round(confidence, 4)}
        entity_index[norm] = item
        candidates.append(item)

    # ① 词典匹配：出现即候选，出现次数与词典置信度共同决定置信度
    for term, meta in _dictionary_terms(dictionary):
        count = text.count(term)
        if not count:
            continue
        base = meta.get("confidence", 0.62)
        boosted = min(0.95, float(base) + min(0.2, 0.03 * (count - 1)))
        add_entity(term, meta, boosted, evidence=f"词典命中：{term}")

    # ② 正则模式：每个模式在句内匹配，产出关系 + 两端实体候选
    pattern_rows = patterns if patterns is not None else list(EXTRACTION_PATTERNS)
    relation_seen = set()
    for sentence in _sentences(text):
        for pattern in pattern_rows:
            try:
                compiled = re.compile(pattern["regex"])
            except (re.error, KeyError) as exc:
                raise ValueError(f"抽取模式非法: {exc}")
            for match in compiled.finditer(sentence):
                groups = match.groupdict()
                left = (groups.get("a") or "").strip(" 　，。；：、")
                right = (groups.get("b") or "").strip(" 　，。；：、")
                if not left or not right or normalize_name(left) == normalize_name(right):
                    continue
                key = f"{normalize_name(left)}|{pattern['code']}|{normalize_name(right)}"
                if key in relation_seen:
                    continue
                relation_seen.add(key)
                confidence = round(clamp(pattern.get("confidence", 0.6), 0.6), 4)
                evidence = match.group(0)[:200]
                add_entity(left, {}, confidence, evidence=evidence,
                           position=match.start())
                add_entity(right, {}, confidence, evidence=evidence,
                           position=match.start())
                candidates.append({
                    "kind": "relation",
                    "name": f"{left}-{pattern['name']}-{right}",
                    "confidence": confidence,
                    "payload": {
                        "source": left.strip()[:200],
                        "target": right.strip()[:200],
                        "relation_code": pattern["code"],
                        "relation_name": pattern["name"],
                        "evidence": evidence,
                        "position": match.start(),
                    },
                })
                if len(candidates) >= max_candidates:
                    return candidates[:max_candidates]
    candidates.sort(key=lambda item: (-item["confidence"], item["kind"], item["name"]))
    return candidates[:max_candidates]


def summarize_candidates(candidates):
    """候选统计：前端任务卡片直接展示「实体 N / 关系 M」。"""
    entity_count = sum(1 for c in candidates if c["kind"] == "entity")
    relation_count = sum(1 for c in candidates if c["kind"] == "relation")
    return {
        "entity_count": entity_count,
        "relation_count": relation_count,
        "total": len(candidates),
        "avg_confidence": round(
            sum(c["confidence"] for c in candidates) / len(candidates), 4
        ) if candidates else 0.0,
    }


# ---------------------------------------------------------------------------
# 5. DSL 解析（neighbors / path / subgraph / search）
# ---------------------------------------------------------------------------


def _split_dsl_args(raw):
    """按逗号切参数，引号与括号内的逗号不切。

    DSL 里同时可能出现 `q="北京,上海"` 与 `types=[1,2]`，简单 split(",")
    会把字符串和数组都切碎，所以维护一个括号 / 引号深度。
    """
    args = []
    current = []
    depth = 0
    quote = ""
    for ch in raw:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
            continue
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        args.append("".join(current).strip())
    return [a for a in args if a]


def _parse_dsl_value(raw):
    """DSL 值：字符串（带引号）/ 布尔 / 数字 / 数组 / 裸字符串。"""
    raw = raw.strip()
    if not raw:
        raise ValueError("DSL 语法错误：参数值不能为空")
    if (raw.startswith('"') and raw.endswith('"')) or \
            (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        values = []
        for part in _split_dsl_args(inner):
            value = _parse_dsl_value(part)
            if not isinstance(value, (int, float, str)):
                raise ValueError("DSL 数组只支持数字或字符串")
            values.append(value)
        return values
    lowered = raw.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        return raw
    raise ValueError(f"DSL 参数值无法识别: {raw}")


def parse_dsl(text):
    """解析图查询 DSL，返回 {kind, params, raw}；非法语法给中文提示。

    语法：``kind(key=value, key2=[1,2])``，kind ∈ neighbors/path/subgraph/search。
    解析只做语法与参数白名单校验，不查库；查库由 run_dsl 在视图层完成，
    这样「解析预览」接口可以完全独立于数据权限。
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("DSL 不能为空")
    if len(raw) > 2000:
        raise ValueError("DSL 长度不能超过 2000 字符")
    match = re.fullmatch(r"\s*([a-zA-Z_]+)\s*\((.*)\)\s*", raw, re.S)
    if not match:
        raise ValueError("DSL 语法应为 func(key=value, ...)")
    kind = match.group(1).lower()
    if kind not in DSL_KINDS:
        raise ValueError(f"DSL 函数仅支持: {'/'.join(DSL_KINDS)}")
    body = match.group(2).strip()
    params = {}
    if body:
        for part in _split_dsl_args(body):
            if "=" not in part:
                raise ValueError(f"DSL 参数缺少等号: {part}")
            key, _, value = part.partition("=")
            key = key.strip()
            if key not in DSL_ALLOWED_KEYS[kind]:
                raise ValueError(f"DSL {kind} 不支持参数: {key}")
            if key in params:
                raise ValueError(f"DSL 参数重复: {key}")
            params[key] = _parse_dsl_value(value)
    missing = DSL_REQUIRED_KEYS[kind] - set(params)
    if missing:
        raise ValueError(f"DSL 缺少必填参数: {', '.join(sorted(missing))}")
    return {"kind": kind, "params": params, "raw": raw}


def validate_dsl_params(kind, params):
    """对解析后的参数做业务校验（范围、方向、列表类型），返回规范化参数。

    与 parse_dsl 分开：保存的查询可能直接以 params JSON 形式提交，
    没有经过 DSL 文本解析，同样需要同一套校验。
    """
    if kind not in DSL_KINDS:
        raise ValueError(f"查询类型仅支持: {'/'.join(DSL_KINDS)}")
    allowed = DSL_ALLOWED_KEYS[kind]
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"{kind} 不支持参数: {', '.join(sorted(unknown))}")
    clean = dict(params)

    def as_int(key, minimum, maximum):
        # params 形态没有经过解析器，缺键 / 空值必须明确报「缺少必填参数」，
        # 否则会以「必须是整数」误导调用方去改类型。
        if clean.get(key) in (None, ""):
            raise ValueError(f"缺少必填参数: {key}")
        try:
            value = int(clean[key])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"参数 {key} 必须是整数")
        if value < minimum or value > maximum:
            raise ValueError(f"参数 {key} 必须在 {minimum}–{maximum} 之间")
        clean[key] = value
        return value

    if kind in ("neighbors", "subgraph"):
        as_int("entity_id" if kind == "neighbors" else "start", 1, 2 ** 31 - 1)
        clean.setdefault("depth", 1 if kind == "neighbors" else 2)
        as_int("depth", 1, MAX_TRAVERSAL_DEPTH)
    if kind == "path":
        as_int("start", 1, 2 ** 31 - 1)
        as_int("end", 1, 2 ** 31 - 1)
        clean.setdefault("max_depth", MAX_TRAVERSAL_DEPTH)
        as_int("max_depth", 1, MAX_TRAVERSAL_DEPTH)
        clean["weighted"] = bool(clean.get("weighted", False))
    if kind == "search":
        q = str(clean.get("q") or "").strip()
        if not q:
            raise ValueError("搜索关键字不能为空")
        clean["q"] = q
        clean.setdefault("limit", 20)
        as_int("limit", 1, MAX_GRAPH_NODES)
    if "direction" in clean:
        if clean["direction"] not in ("out", "in", "both"):
            raise ValueError("direction 仅支持 out/in/both")
    if "types" in clean:
        raw_types = clean["types"]
        if isinstance(raw_types, (str, int)):
            raw_types = [raw_types]
        if not isinstance(raw_types, list):
            raise ValueError("types 必须是数组")
        try:
            clean["types"] = [int(t) for t in raw_types]
        except (TypeError, ValueError):
            raise ValueError("types 只能包含整数")
    for key in ("min_weight", "min_confidence"):
        if key in clean:
            try:
                clean[key] = float(clean[key])
            except (TypeError, ValueError):
                raise ValueError(f"参数 {key} 必须是数字")
    return clean


def run_dsl(parsed, context):
    """执行解析后的 DSL。

    context 由视图提供：
    - adjacency：build_adjacency 的结果；
    - search：callable(q, limit, types) -> 搜索结果；
    - exists：callable(entity_id) -> bool（校验实体在当前数据范围内）。
    服务层不直接查库，保证算法与权限解耦、可单独测试。
    """
    kind = parsed["kind"]
    params = validate_dsl_params(kind, parsed.get("params") or {})
    exists = context.get("exists") or (lambda _id: True)
    if kind == "neighbors":
        entity_id = params["entity_id"]
        if not exists(entity_id):
            raise ValueError("起点实体不存在或无权访问")
        return neighbors(entity_id, context["adjacency"],
                         direction=params.get("direction", "both"),
                         depth=params.get("depth", 1),
                         type_ids=params.get("types"),
                         min_weight=params.get("min_weight"),
                         min_confidence=params.get("min_confidence"),
                         limit=params.get("limit", MAX_GRAPH_NODES))
    if kind == "subgraph":
        start = params["start"]
        if not exists(start):
            raise ValueError("起点实体不存在或无权访问")
        return subgraph(start, context["adjacency"],
                        depth=params.get("depth", 2),
                        direction=params.get("direction", "both"),
                        type_ids=params.get("types"),
                        min_weight=params.get("min_weight"),
                        min_confidence=params.get("min_confidence"),
                        limit=params.get("limit", MAX_GRAPH_NODES))
    if kind == "path":
        start, end = params["start"], params["end"]
        if not exists(start) or not exists(end):
            raise ValueError("起点或终点实体不存在或无权访问")
        if params.get("weighted"):
            path, cost = shortest_path_weighted(
                start, end, context["adjacency"],
                direction=params.get("direction", "both"),
                type_ids=params.get("types"),
                weight_mode="inverse")
        else:
            path, cost = shortest_path(
                start, end, context["adjacency"],
                direction=params.get("direction", "both"),
                type_ids=params.get("types")), None
        return {"path": path, "cost": cost, "found": bool(path)}
    search_fn = context.get("search")
    if search_fn is None:
        raise ValueError("当前上下文不支持搜索")
    return search_fn(params["q"], params.get("limit", 20), params.get("types"))


def describe_dsl():
    """DSL 语法说明（目录与预览接口共用）。"""
    return {
        "kinds": list(DSL_KINDS),
        "grammar": "func(key=value, ...)",
        "functions": {
            "neighbors": {"required": ["entity_id"],
                          "optional": ["depth", "direction", "types",
                                       "min_weight", "min_confidence", "limit"]},
            "path": {"required": ["start", "end"],
                     "optional": ["max_depth", "weighted", "direction", "types"]},
            "subgraph": {"required": ["start"],
                         "optional": ["depth", "direction", "types",
                                      "min_weight", "min_confidence", "limit"]},
            "search": {"required": ["q"],
                       "optional": ["limit", "types", "min_confidence"]},
        },
        "limits": {"depth": MAX_TRAVERSAL_DEPTH, "nodes": MAX_GRAPH_NODES},
    }


# ---------------------------------------------------------------------------
# 6. 统计：度分布 / 连通分量 / 社区 / 中心性 / 类型分布 / 增长趋势
# ---------------------------------------------------------------------------


def _undirected_neighbors(relations):
    """无向邻接（集合），统计类算法不需要边 id 与权重。"""
    adjacency = defaultdict(set)
    for rel in relations:
        src, dst = rel["src"], rel["dst"]
        if src == dst:
            continue
        adjacency[src].add(dst)
        adjacency[dst].add(src)
    return adjacency


def degree_distribution(entities, relations, top=20):
    """度分布：出度 / 入度 / 总度，按度分桶并给出 TOP 节点。"""
    out_degree = Counter()
    in_degree = Counter()
    for rel in relations:
        out_degree[rel["src"]] += 1
        in_degree[rel["dst"]] += 1
    ids = [e["id"] for e in entities]
    buckets = Counter()
    rows = []
    for entity in entities:
        total = out_degree[entity["id"]] + in_degree[entity["id"]]
        bucket = ("0" if total == 0 else "1" if total == 1 else "2-3" if total <= 3
                  else "4-7" if total <= 7 else "8-15" if total <= 15 else "16+")
        buckets[bucket] += 1
        rows.append({
            "entity_id": entity["id"],
            "name": entity["name"],
            "out_degree": out_degree[entity["id"]],
            "in_degree": in_degree[entity["id"]],
            "degree": total,
        })
    rows.sort(key=lambda r: (-r["degree"], r["entity_id"]))
    total_degree = sum(r["degree"] for r in rows)
    return {
        "entity_count": len(ids),
        "relation_count": len(relations),
        "avg_degree": round(total_degree / len(ids), 4) if ids else 0.0,
        "max_degree": rows[0]["degree"] if rows else 0,
        "buckets": dict(sorted(buckets.items())),
        "top": rows[:top],
        "isolated": sum(1 for r in rows if r["degree"] == 0),
    }


def connected_components(entities, relations, top=20):
    """连通分量：并查集统计数量、最大分量与分量规模分布。"""
    parent = {e["id"]: e["id"] for e in entities}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for rel in relations:
        if rel["src"] in parent and rel["dst"] in parent:
            union(rel["src"], rel["dst"])
    groups = defaultdict(list)
    for entity in entities:
        groups[find(entity["id"])].append(entity["id"])
    sizes = sorted((len(v) for v in groups.values()), reverse=True)
    components = sorted(groups.values(), key=lambda v: (-len(v), v[0]))
    return {
        "component_count": len(components),
        "largest_size": sizes[0] if sizes else 0,
        "isolated_nodes": sum(1 for s in sizes if s == 1),
        "size_distribution": dict(sorted(Counter(sizes).items())),
        "components": [{"size": len(c), "entity_ids": c[:50]} for c in components[:top]],
    }


def label_propagation(entities, relations, max_iter=20, top=20):
    """标签传播社区检测（确定性实现，便于测试与复现）。

    每次迭代按「度降序 + id 升序」处理节点，邻居标签计数并列时取最小
    标签 id：完全确定性的顺序让同一份图永远得到同一组社区，避免测试
    随机抖动；最多 20 轮，收敛即停。
    """
    adjacency = _undirected_neighbors(relations)
    node_ids = [e["id"] for e in entities]
    labels = {node: node for node in node_ids}
    degree = {node: len(adjacency.get(node, ())) for node in node_ids}
    order = sorted(node_ids, key=lambda n: (-degree[n], n))
    iterations = 0
    for _ in range(max_iter):
        changed = False
        for node in order:
            neighbors = adjacency.get(node) or set()
            if not neighbors:
                continue
            counter = Counter(labels[n] for n in neighbors if n in labels)
            best_count = max(counter.values())
            candidates = [label for label, count in counter.items() if count == best_count]
            chosen = min(candidates)
            if chosen != labels[node]:
                labels[node] = chosen
                changed = True
        iterations += 1
        if not changed:
            break
    groups = defaultdict(list)
    for node in node_ids:
        groups[labels[node]].append(node)
    communities = sorted(groups.values(), key=lambda v: (-len(v), v[0]))
    return {
        "community_count": len(communities),
        "iterations": iterations,
        "modularity_hint": round(
            sum((len(c) / len(node_ids)) ** 2 for c in communities), 4
        ) if node_ids else 0.0,
        "communities": [
            {"size": len(c), "entity_ids": c[:50]} for c in communities[:top]
        ],
    }


def degree_centrality(entities, relations, top=20):
    """度中心性：degree / (n-1)，范围 0–1。"""
    n = len(entities)
    adjacency = _undirected_neighbors(relations)
    rows = []
    denominator = max(n - 1, 1)
    for entity in entities:
        score = len(adjacency.get(entity["id"], ())) / denominator if n > 1 else 0.0
        rows.append({"entity_id": entity["id"], "name": entity["name"],
                     "score": round(score, 4)})
    rows.sort(key=lambda r: (-r["score"], r["entity_id"]))
    return {"items": rows[:top], "count": len(rows)}


def betweenness_approx(entities, relations, samples=32, seed=42, top=20):
    """近似介数中心性：Brandes 算法 + 固定随机种子采样源点。

    精确介数是 O(V*E)，500 节点 × 2000 边已经足够慢；采样 32 个源点
    （不重复、按 id 排序后抽样）在展示 TOP 节点时足够稳定，还不会
    拖垮单次请求。固定 seed 保证同一份图结果可复现。
    """
    node_ids = sorted(e["id"] for e in entities)
    if len(node_ids) < 3:
        return {"items": [], "count": 0, "samples": 0, "normalized": False}
    adjacency = _undirected_neighbors(relations)
    sample_size = max(1, min(int(samples or 32), len(node_ids)))
    rng = random.Random(seed)
    sources = rng.sample(node_ids, sample_size)
    centrality = Counter()
    for source in sources:
        stack = []
        predecessors = {node: [] for node in node_ids}
        sigma = {node: 0.0 for node in node_ids}
        distance = {node: -1 for node in node_ids}
        sigma[source] = 1.0
        distance[source] = 0
        queue = deque([source])
        while queue:
            node = queue.popleft()
            stack.append(node)
            for neighbor in adjacency.get(node, ()):
                if distance[neighbor] < 0:
                    distance[neighbor] = distance[node] + 1
                    queue.append(neighbor)
                if distance[neighbor] == distance[node] + 1:
                    sigma[neighbor] += sigma[node]
                    predecessors[neighbor].append(node)
        dependency = {node: 0.0 for node in node_ids}
        while stack:
            node = stack.pop()
            for prev in predecessors[node]:
                if sigma[node]:
                    dependency[prev] += (sigma[prev] / sigma[node]) * (1 + dependency[node])
            if node != source:
                centrality[node] += dependency[node]
    # 无向图每对节点被算了两次，采样时按 (n-1)(n-2)/2 归一化
    norm = ((len(node_ids) - 1) * (len(node_ids) - 2)) / 2
    scale = norm * (sample_size / len(node_ids)) if norm > 0 else 1
    names = {e["id"]: e["name"] for e in entities}
    rows = [{"entity_id": node, "name": names.get(node, ""),
             "score": round(centrality[node] / scale, 6)}
            for node in node_ids if centrality[node] > 0]
    rows.sort(key=lambda r: (-r["score"], r["entity_id"]))
    return {"items": rows[:top], "count": len(rows), "samples": sample_size,
            "normalized": True}


def type_distribution(entities, type_names=None):
    """类型分布：按 entity_type_id 聚合，附中文名与占比。"""
    counter = Counter(e.get("entity_type_id") for e in entities)
    rows = []
    for type_id, count in counter.most_common():
        rows.append({
            "entity_type_id": type_id,
            "name": (type_names or {}).get(type_id, ""),
            "count": count,
            "ratio": round(count / len(entities), 4) if entities else 0.0,
        })
    return {"items": rows, "count": len(entities)}


def growth_trend(created_ats, days=30, today=None):
    """增长趋势：按天统计新增与累计。

    日期桶只保留有数据的区间；缺失的中间日期补 0，前端折线图才不会
    因为跳过空日而把两天连成一条斜线（视觉上虚增增速）。
    """
    days = int(days or 30)
    if days < 1 or days > 365:
        raise ValueError("days 必须在 1–365 之间")
    today = today or timezone.localdate()
    start = today - timedelta(days=days - 1)
    buckets = {start + timedelta(days=i): 0 for i in range(days)}
    for value in created_ats:
        if value is None:
            continue
        day = value.date() if hasattr(value, "date") else value
        if day in buckets:
            buckets[day] += 1
    items = []
    cumulative = 0
    for day in sorted(buckets):
        cumulative += buckets[day]
        items.append({"date": day.isoformat(), "created": buckets[day],
                      "cumulative": cumulative})
    return {"days": days, "items": items, "total": cumulative}


# ---------------------------------------------------------------------------
# 7. 快照与对比
# ---------------------------------------------------------------------------


def snapshot_stats(entities, relations, type_names=None):
    """生成快照统计（节点 / 边 / 度 / 连通分量 / 类型分布）。

    只保留聚合值：完整节点快照不可持续（每周一次、上万节点），
    对比接口关心的是规模与结构变化，不是逐条差异。
    """
    degrees = degree_distribution(entities, relations, top=10)
    components = connected_components(entities, relations, top=5)
    types = type_distribution(entities, type_names)
    density = (len(relations) / (len(entities) * (len(entities) - 1))
               if len(entities) > 1 else 0.0)
    return {
        "node_count": len(entities),
        "edge_count": len(relations),
        "density": round(density, 6),
        "avg_degree": degrees["avg_degree"],
        "max_degree": degrees["max_degree"],
        "isolated_nodes": degrees["isolated"],
        "component_count": components["component_count"],
        "largest_component": components["largest_size"],
        "type_distribution": {str(row["entity_type_id"]): row["count"]
                              for row in types["items"]},
        "top_degree": degrees["top"],
        "generated_at": timezone.now().isoformat(),
    }


def diff_stats(old_stats, new_stats):
    """对比两份快照统计：规模增量 + 类型增减 + 结构变化。"""
    old_stats = old_stats or {}
    new_stats = new_stats or {}
    numeric_keys = ("node_count", "edge_count", "avg_degree", "max_degree",
                    "isolated_nodes", "component_count", "largest_component",
                    "density")
    deltas = {}
    for key in numeric_keys:
        old_value = old_stats.get(key) or 0
        new_value = new_stats.get(key) or 0
        deltas[key] = {
            "old": old_value,
            "new": new_value,
            "delta": round(float(new_value) - float(old_value), 6),
        }
    old_types = old_stats.get("type_distribution") or {}
    new_types = new_stats.get("type_distribution") or {}
    added = {k: v for k, v in new_types.items() if k not in old_types}
    removed = {k: v for k, v in old_types.items() if k not in new_types}
    changed = {}
    for key in set(old_types) & set(new_types):
        delta = int(new_types[key]) - int(old_types[key])
        if delta:
            changed[key] = {"old": old_types[key], "new": new_types[key],
                            "delta": delta}
    return {"deltas": deltas, "types_added": added, "types_removed": removed,
            "types_changed": changed,
            "node_delta": deltas["node_count"]["delta"],
            "edge_delta": deltas["edge_count"]["delta"]}


# ---------------------------------------------------------------------------
# 8. 路径缓存
# ---------------------------------------------------------------------------


def path_cache_lookup(ontology_id, start_id, end_id, max_depth, weighted=False,
                      ttl_hours=24, owner=None):
    """按「起终点 + 深度 + 是否带权」查缓存；过期视为未命中。

    键里必须带 weighted：无权最短路与带权最短路可能给出不同路径，
    复用缓存会让「带权」开关看起来失效；owner 过滤防止共享本体时
    把别人的缓存结果当自己的（缓存行本身也受 owner 唯一键约束）。
    """
    cutoff = timezone.now() - timedelta(hours=ttl_hours)
    qs = PathCache.objects.filter(
        ontology_id=ontology_id, start_entity_id=start_id,
        end_entity_id=end_id, max_depth=max_depth, weighted=weighted,
        generated_at__gte=cutoff)
    if owner is not None:
        qs = qs.filter(owner=owner)
    return qs.first()


def store_path_cache(ontology_id, start_id, end_id, max_depth, path, cost=0.0,
                     weighted=False, owner=None):
    """写入 / 刷新路径缓存（唯一键冲突时更新，保证并发下不炸唯一约束）。"""
    if owner is None:
        raise ValueError("写入路径缓存必须指定所有者")
    cache, _ = PathCache.objects.update_or_create(
        owner=owner, ontology_id=ontology_id, start_entity_id=start_id,
        end_entity_id=end_id, max_depth=max_depth, weighted=weighted,
        defaults={
            "path": path or [],
            "cost": round(float(cost or 0), 6),
            "generated_at": timezone.now(),
        },
    )
    return cache


def invalidate_path_cache(ontology_id, entity_ids=None):
    """失效路径缓存：实体变化后，所有涉及它的起终点缓存都不再可信。"""
    qs = PathCache.objects.filter(ontology_id=ontology_id)
    if entity_ids:
        ids = list(entity_ids)
        qs = qs.filter(Q(start_entity_id__in=ids) | Q(end_entity_id__in=ids))
    count, _ = qs.delete()
    return count


# ---------------------------------------------------------------------------
# 9. 搜索（名称 / 别名 / 描述 / 属性，加权评分）
# ---------------------------------------------------------------------------


def _score_field(text, query, weight):
    """字段命中评分：完全相等 > 前缀 > 包含，规范化后比较以兼容大小写。"""
    if not text:
        return 0.0, ""
    norm_text = normalize_name(text)
    norm_query = normalize_name(query)
    if not norm_query:
        return 0.0, ""
    if norm_text == norm_query:
        return weight * 3, "exact"
    if norm_text.startswith(norm_query):
        return weight * 2, "prefix"
    if norm_query in norm_text:
        return weight * 1, "contains"
    # 中文二元组召回：避免「腾讯科技有限公司」搜不到「腾讯」
    query_tokens = name_tokens(query)
    if query_tokens and query_tokens.issubset(name_tokens(text)):
        return weight * 0.6, "tokens"
    return 0.0, ""


def score_entity(entity, aliases, query):
    """单个实体的搜索得分；返回 (score, matched_fields)。

    权重设计：名称 10 / 规范名 8 / 别名 6 / 标签不参与（标签单独接口）/
    描述 2 / 属性 1.5。名称与别名权重远高于描述，避免「描述里提了一句」
    把无关实体顶到结果第一。
    """
    score = 0.0
    fields = []
    for value, weight, label in (
        (entity.get("name"), 10.0, "name"),
        (entity.get("canonical_name"), 8.0, "canonical_name"),
    ):
        part, kind = _score_field(value, query, weight)
        if part:
            score += part
            fields.append(f"{label}:{kind}")
    for alias in aliases or ():
        part, kind = _score_field(alias, query, 6.0)
        if part:
            score += part
            fields.append(f"alias:{kind}")
    part, kind = _score_field(entity.get("description"), query, 2.0)
    if part:
        score += part
        fields.append(f"description:{kind}")
    attrs = entity.get("attrs") or {}
    for key, value in attrs.items():
        if isinstance(value, (str, int, float)):
            part, kind = _score_field(str(value), query, 1.5)
            if part:
                score += part
                fields.append(f"attrs.{key}:{kind}")
    return round(score, 4), fields


def search_entities(entities, alias_map, query, limit=20, type_ids=None,
                    min_confidence=None):
    """加权搜索：返回按得分排序的实体与命中字段说明。

    alias_map: {entity_id: [alias, ...]}；由视图一次性批量查出后传入，
    避免在循环里对每个实体单独查别名（N+1 查询）。
    """
    query = str(query or "").strip()
    if not query:
        raise ValueError("搜索关键字不能为空")
    if len(query) > 200:
        raise ValueError("搜索关键字不能超过 200 字符")
    limit = int(limit or 20)
    if limit < 1 or limit > MAX_GRAPH_NODES:
        raise ValueError(f"搜索数量必须在 1–{MAX_GRAPH_NODES} 之间")
    results = []
    for entity in entities:
        if type_ids and entity.get("entity_type_id") not in type_ids:
            continue
        if min_confidence is not None and float(entity.get("confidence") or 0) < float(min_confidence):
            continue
        score, fields = score_entity(entity, alias_map.get(entity["id"]), query)
        if score <= 0:
            continue
        results.append({
            "entity_id": entity["id"],
            "name": entity["name"],
            "entity_type_id": entity.get("entity_type_id"),
            "score": score,
            "matched_fields": fields,
            "confidence": entity.get("confidence"),
        })
    results.sort(key=lambda r: (-r["score"], r["entity_id"]))
    return {"items": results[:limit], "count": len(results), "query": query}
