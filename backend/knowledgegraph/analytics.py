# -*- coding: utf-8 -*-
"""knowledgegraph · 进阶图分析算法。

services.py 承担「与业务强相关」的图操作（遍历、最短路、合并、抽取），
本模块只放与业务无关、可用纯数据结构验证的算法：

- PageRank：有向加权的重要性排序，权重取关系 weight；
- 紧密度中心性：BFS 距离的调和平均，孤立点自然不会拉低整体分数；
- k-core：迭代剥离低度节点的核数分解，用来识别图谱的「骨架」；
- 聚类系数：局部三角闭合率，衡量实体邻域的内聚程度；
- 图密度 / 互惠率 / 自环：一眼看清图谱是稀疏还是稠密；
- 环路枚举：有限长度内的简单环，用于发现「A 属于 B、B 属于 A」脏数据；
- K 短路：Yen 算法，给业务提供备选路径而不是只有唯一解；
- 相似簇：把两两相似度超过阈值的实体聚成一簇，供批量合并使用。

设计约束：
- 只接受 list[dict]（实体 / 关系的 lite 结构），不碰 ORM，便于单测；
- 所有函数对空图、单点图、断链图都必须返回合法结构而不是抛异常；
- 复杂度对 500 节点 / 2000 边规模可控，超过由视图层统一拦截。
"""
import heapq
from collections import Counter, defaultdict, deque

# 浮点比较容差：PageRank 迭代终止条件与 K 短路去重都用同一口径
EPSILON = 1e-9


def _node_ids(entities):
    """稳定排序的节点 id 列表：多次调用结果一致，便于复现。"""
    return sorted({entity["id"] for entity in entities})


def _directed_neighbors(relations):
    """有向邻接：node -> [(neighbor, weight)]，保留重边（PageRank 需要）。"""
    neighbors = defaultdict(list)
    for rel in relations:
        weight = float(rel.get("weight") or 1.0)
        if weight <= 0:
            # 非正权重会让 PageRank 的归一化失效，统一按 1 处理
            weight = 1.0
        neighbors[rel["src"]].append((rel["dst"], weight))
    return neighbors


def _undirected_neighbors(relations):
    """无向邻接：node -> set(neighbor)，统计类算法共用。"""
    neighbors = defaultdict(set)
    for rel in relations:
        src, dst = rel["src"], rel["dst"]
        if src == dst:
            # 自环不构成有效邻居关系，聚类 / k-core 里都应忽略
            continue
        neighbors[src].add(dst)
        neighbors[dst].add(src)
    return neighbors


def _out_degree_counter(relations):
    """有向出度计数（含自环），PageRank 的悬挂节点判定要用。"""
    counter = Counter()
    for rel in relations:
        counter[rel["src"]] += 1
    return counter


def pagerank(entities, relations, damping=0.85, iterations=30,
             tolerance=1e-6, top=20):
    """PageRank：有向加权重要性排序。

    实现要点：
    - 悬挂节点（出度为 0）把自身权重均摊给全图，否则总权重会随迭代衰减；
    - 边权直接作为转移概率的分子，权重高的关系传递更多重要性；
    - 用 L1 差作为终止条件，最多 iterations 轮，保证请求耗时可控。
    """
    node_ids = _node_ids(entities)
    n = len(node_ids)
    if n == 0:
        return {"items": [], "count": 0, "iterations": 0,
                "damping": damping, "converged": True}
    damping = min(0.99, max(0.0, float(damping)))
    iterations = max(1, min(int(iterations), 200))
    tolerance = max(0.0, float(tolerance))

    neighbors = _directed_neighbors(relations)
    out_weight = defaultdict(float)
    for src, edges in neighbors.items():
        out_weight[src] = sum(weight for _dst, weight in edges)

    initial = 1.0 / n
    ranks = {node: initial for node in node_ids}
    converged = False
    used = 0
    for step in range(iterations):
        used = step + 1
        # 悬挂节点把权重贡献给全图，先算总量再均摊
        dangling = sum(ranks[node] for node in node_ids if out_weight[node] == 0)
        base = (1.0 - damping) / n + damping * dangling / n
        updated = {node: base for node in node_ids}
        for src in node_ids:
            total = out_weight[src]
            if total <= 0:
                continue
            share = damping * ranks[src] / total
            for dst, weight in neighbors.get(src, ()):
                if dst in updated:
                    updated[dst] += share * weight
        delta = sum(abs(updated[node] - ranks[node]) for node in node_ids)
        ranks = updated
        if delta <= tolerance:
            converged = True
            break

    names = {entity["id"]: entity.get("name", "") for entity in entities}
    rows = [{"entity_id": node, "name": names.get(node, ""),
             "score": round(ranks[node], 6)} for node in node_ids]
    rows.sort(key=lambda row: (-row["score"], row["entity_id"]))
    return {
        "items": rows[:max(1, int(top))],
        "count": len(rows),
        "iterations": used,
        "damping": damping,
        "converged": converged,
    }


def _bfs_distances(start, neighbors):
    """无向 BFS 距离表；返回 dict[node, hops]，start 自身距离为 0。"""
    distance = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in neighbors.get(node, ()):  # 邻居是 set，遍历无重复
            if nxt in distance:
                continue
            distance[nxt] = distance[node] + 1
            queue.append(nxt)
    return distance


def closeness_centrality(entities, relations, top=20):
    """紧密度中心性：可达节点距离倒数的均值（调和中心性）。

    直接用「1 / 平均距离」在含孤立点的图里会全部变成 0；调和形式
    只对可达节点求和再除以 n-1，既保留孤立点惩罚，又不会让断链图
    整体失去区分度。
    """
    node_ids = _node_ids(entities)
    n = len(node_ids)
    names = {entity["id"]: entity.get("name", "") for entity in entities}
    if n <= 1:
        return {"items": [], "count": 0, "normalized": False}
    neighbors = _undirected_neighbors(relations)
    rows = []
    for node in node_ids:
        distance = _bfs_distances(node, neighbors)
        reachable = len(distance) - 1  # 去掉自身
        total = sum(1.0 / hops for other, hops in distance.items() if other != node)
        score = total / (n - 1)
        rows.append({
            "entity_id": node,
            "name": names.get(node, ""),
            "score": round(score, 6),
            "reachable": reachable,
        })
    rows.sort(key=lambda row: (-row["score"], row["entity_id"]))
    return {"items": rows[:max(1, int(top))], "count": len(rows),
            "normalized": True}


def k_core(entities, relations, top=20):
    """k-core 分解：返回每个节点的核数与核数分布。

    经典剥离算法（Bucket 版）：反复删掉度数小于当前 k 的节点，
    剩下节点的最大 k 就是图的核心度。这里用「最小堆 + 惰性删除」，
    避免每轮全图扫描，O((V+E) log V)。
    """
    node_ids = _node_ids(entities)
    neighbors = _undirected_neighbors(relations)
    degree = {node: len(neighbors.get(node, ())) for node in node_ids}
    # 堆里允许过期条目：出堆时度数已变小就跳过，等于惰性更新
    heap = [(degree[node], node) for node in node_ids]
    heapq.heapify(heap)
    removed = set()
    core = {}
    current = 0
    while heap:
        value, node = heapq.heappop(heap)
        if node in removed:
            continue
        if value > degree[node]:
            heapq.heappush(heap, (degree[node], node))
            continue
        removed.add(node)
        current = max(current, value)
        core[node] = current
        for nxt in neighbors.get(node, ()):
            if nxt in removed:
                continue
            degree[nxt] = max(0, degree[nxt] - 1)
            heapq.heappush(heap, (degree[nxt], nxt))

    names = {entity["id"]: entity.get("name", "") for entity in entities}
    rows = [{"entity_id": node, "name": names.get(node, ""),
             "core": core.get(node, 0)} for node in node_ids]
    rows.sort(key=lambda row: (-row["core"], row["entity_id"]))
    distribution = Counter(row["core"] for row in rows)
    max_core = max(distribution) if distribution else 0
    return {
        "items": rows[:max(1, int(top))],
        "count": len(rows),
        "max_core": max_core,
        "distribution": {str(k): distribution[k] for k in sorted(distribution)},
    }


def clustering_coefficient(entities, relations, top=20):
    """局部聚类系数：邻居之间实际连边数 / 可能连边数。

    全局平均系数是「局部系数的均值」，与「三角形数 / 三元组数」口径
    不同，这两个值一起返回，避免调用方把两种定义混用。
    """
    node_ids = _node_ids(entities)
    neighbors = _undirected_neighbors(relations)
    names = {entity["id"]: entity.get("name", "") for entity in entities}

    triangles = 0
    rows = []
    for node in node_ids:
        peers = neighbors.get(node, set())
        degree = len(peers)
        if degree < 2:
            score = 0.0
        else:
            links = 0
            ordered = sorted(peers)
            for index, left in enumerate(ordered):
                left_peers = neighbors.get(left, set())
                for right in ordered[index + 1:]:
                    if right in left_peers:
                        links += 1
            possible = degree * (degree - 1) / 2
            score = links / possible if possible else 0.0
            triangles += links
        rows.append({"entity_id": node, "name": names.get(node, ""),
                     "degree": degree, "coefficient": round(score, 6)})

    rows.sort(key=lambda row: (-row["coefficient"], -row["degree"],
                               row["entity_id"]))
    average = sum(row["coefficient"] for row in rows) / len(rows) if rows else 0.0
    # 每条三角形被三个顶点各计一次
    triangle_count = triangles // 3
    possible_triples = sum(
        len(neighbors.get(node, ())) * (len(neighbors.get(node, ())) - 1) / 2
        for node in node_ids)
    transitivity = (3 * triangle_count / possible_triples) if possible_triples else 0.0
    return {
        "items": rows[:max(1, int(top))],
        "count": len(rows),
        "average": round(average, 6),
        "transitivity": round(transitivity, 6),
        "triangles": triangle_count,
    }


def graph_density(entities, relations):
    """图密度与互惠率。

    density = E / (V*(V-1))，有向图分母不再除以 2；
    互惠率 = 双向边对数 / 无向边对数，用来发现「只记了单向关系」的数据。
    """
    node_ids = _node_ids(entities)
    n = len(node_ids)
    directed_pairs = {(rel["src"], rel["dst"]) for rel in relations
                      if rel["src"] != rel["dst"]}
    self_loops = sum(1 for rel in relations if rel["src"] == rel["dst"])
    reciprocal = 0
    seen = set()
    for src, dst in directed_pairs:
        if (dst, src) in directed_pairs and (dst, src) not in seen:
            seen.add((src, dst))
            reciprocal += 1
    undirected_pairs = len(directed_pairs) - reciprocal
    denominator = n * (n - 1)
    density = len(directed_pairs) / denominator if denominator else 0.0
    return {
        "entity_count": n,
        "relation_count": len(relations),
        "directed_pairs": len(directed_pairs),
        "undirected_pairs": undirected_pairs,
        "reciprocal_pairs": reciprocal,
        "reciprocity": round(reciprocal / len(directed_pairs), 6)
        if directed_pairs else 0.0,
        "self_loops": self_loops,
        "density": round(density, 6),
        "max_edges": denominator,
    }


def find_cycles(entities, relations, max_cycles=20, max_length=5,
                directed=True):
    """枚举有限长度的简单环（DFS + 规范旋转去重）。

    业务价值：环路是知识图谱最常见的脏数据形态（A 属于 B、B 属于 A）。
    只枚举长度 ≤ max_length 的环，且用「最小节点作为起点」规范化，
    保证同一个环只出现一次；无向图额外把反向旋转视为同一个环。
    """
    max_cycles = max(1, min(int(max_cycles), 200))
    max_length = max(2, min(int(max_length), 10))
    node_ids = _node_ids(entities)
    valid = set(node_ids)
    names = {entity["id"]: entity.get("name", "") for entity in entities}
    neighbors = defaultdict(set)
    for rel in relations:
        src, dst = rel["src"], rel["dst"]
        if src not in valid or dst not in valid or src == dst:
            continue
        neighbors[src].add(dst)
        if not directed or rel.get("directed") is False:
            neighbors[dst].add(src)

    cycles = []
    seen = set()

    def canonical(path):
        """把环旋转到最小节点开头，得到唯一键。"""
        body = path[:-1]
        if not body:
            return ()
        pivot = body.index(min(body))
        rotated = tuple(body[pivot:] + body[:pivot])
        return rotated

    def visit(start, node, path, on_path):
        if len(path) > max_length:
            return
        for nxt in sorted(neighbors.get(node, ())):
            if nxt == start and len(path) >= 2:
                key = canonical(path + [start])
                if key and key not in seen:
                    seen.add(key)
                    cycles.append(list(key) + [key[0]])
                continue
            # 只允许比 start 大的节点作为中间点，天然消掉旋转重复
            if nxt < start or nxt in on_path:
                continue
            on_path.add(nxt)
            path.append(nxt)
            visit(start, nxt, path, on_path)
            path.pop()
            on_path.remove(nxt)

    for start in node_ids:
        visit(start, start, [start], {start})
        if len(cycles) >= max_cycles:
            break

    items = []
    for cycle in cycles[:max_cycles]:
        items.append({
            "nodes": cycle[:-1],
            "length": len(cycle) - 1,
            "names": [names.get(node, "") for node in cycle[:-1]],
        })
    return {"items": items, "count": len(items), "max_length": max_length,
            "directed": directed}


def _dijkstra(adjacency, start, end, direction="both", type_ids=None,
              banned_edges=None, banned_nodes=None, weighted=False):
    """单源最短路（Yen 的钉住子问题）。

    与 services.shortest_path_weighted 的差异：这里需要支持「禁用某条边 /
    某个节点」来求备选路径，因此单独实现一份，权重模式固定为 1/weight，
    与加权最短路接口保持同一口径。
    """
    banned_edges = banned_edges or set()
    banned_nodes = banned_nodes or set()
    if start in banned_nodes or end in banned_nodes:
        return None
    frontier = [(0.0, [start])]
    best = {start: 0.0}
    while frontier:
        cost, path = heapq.heappop(frontier)
        node = path[-1]
        if node == end:
            return {"path": path, "cost": round(cost, 6)}
        if cost > best.get(node, float("inf")) + EPSILON:
            continue
        edges = []
        if direction in ("out", "both"):
            edges.extend(adjacency["out"].get(node, []))
        if direction in ("in", "both"):
            edges.extend(adjacency["in"].get(node, []))
        seen_edges = set()
        for edge in edges:
            edge_key = (edge.get("id"), edge["src"], edge["dst"])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            if type_ids and edge.get("type_id") not in type_ids:
                continue
            if (edge["src"], edge["dst"]) in banned_edges:
                continue
            nxt = edge["other"]
            if nxt in banned_nodes or nxt in path:
                continue
            weight = float(edge.get("weight") or 1.0)
            step = (1.0 / max(weight, 1e-6)) if weighted else 1.0
            new_cost = cost + step
            if new_cost + EPSILON < best.get(nxt, float("inf")):
                best[nxt] = new_cost
                heapq.heappush(frontier, (new_cost, path + [nxt]))
    return None


def k_shortest_paths(adjacency, start, end, k=3, direction="both",
                     type_ids=None, weighted=True, max_cost=None):
    """Yen 算法：按代价升序返回前 k 条无环备选路径。

    与「只给一条最短路」相比，备选路径能支撑「换一条通路解释两个实体
    的关系」这类业务诉求；k 上限 10，避免组合爆炸拖垮单次请求。
    """
    k = max(1, min(int(k), 10))
    if start == end:
        raise ValueError("起点与终点不能相同")
    first = _dijkstra(adjacency, start, end, direction=direction,
                      type_ids=type_ids, weighted=weighted)
    if first is None:
        return {"items": [], "count": 0, "k": k}
    accepted = [first]
    candidates = []
    # 候选堆元素：(cost, 序号, path)；序号用于避免 path 列表不可比较
    counter = 0
    for _ in range(k - 1):
        previous = accepted[-1]["path"]
        for index in range(len(previous) - 1):
            spur = previous[index]
            root = previous[:index + 1]
            banned_edges = set()
            for row in accepted:
                row_path = row["path"]
                if row_path[:index + 1] == root and len(row_path) > index + 1:
                    banned_edges.add((row_path[index], row_path[index + 1]))
            banned_nodes = set(root[:-1])
            spur_result = _dijkstra(
                adjacency, spur, end, direction=direction, type_ids=type_ids,
                banned_edges=banned_edges, banned_nodes=banned_nodes,
                weighted=weighted)
            if spur_result is None:
                continue
            total_path = root[:-1] + spur_result["path"]
            if total_path in (row["path"] for row in accepted):
                continue
            if total_path in (row[2] for row in candidates):
                continue
            total_cost = spur_result["cost"]
            # 根路径的代价没有在子问题里累计，需要补上
            root_cost = _dijkstra(
                adjacency, start, spur, direction=direction,
                type_ids=type_ids, weighted=weighted)
            if root_cost is not None:
                total_cost += root_cost["cost"]
            if max_cost is not None and total_cost > float(max_cost):
                continue
            counter += 1
            heapq.heappush(candidates, (total_cost, counter, total_path))
        if not candidates:
            break
        cost, _seq, path = heapq.heappop(candidates)
        accepted.append({"path": path, "cost": round(cost, 6)})

    items = [{"rank": index + 1, "path": row["path"],
              "length": len(row["path"]) - 1, "cost": row["cost"]}
             for index, row in enumerate(accepted)]
    return {"items": items, "count": len(items), "k": k}


def similarity_clusters(entities, threshold=0.82, limit=100):
    """相似实体聚类：两两相似度超过阈值的实体并查集合并。

    与 duplicate_suggestions 的区别：那个接口返回「实体对」，适合逐条
    审核；这里返回「簇」，适合批量合并同一实体的多种写法。为了避免
    O(n²) 爆掉，超过 2000 个实体时只处理前 2000 个并标注 truncated；
    长度差 > 40% 且互不包含的名称直接跳过，与查重口径保持一致。
    """
    from knowledgegraph import services

    rows = list(entities)[:2000]
    truncated = len(list(entities)) > 2000
    threshold = min(1.0, max(0.5, float(threshold)))
    parent = {row["id"]: row["id"] for row in rows}
    names = {row["id"]: row.get("name", "") for row in rows}
    norms = {}
    for row in rows:
        norm = row.get("canonical_name") or services.normalize_name(row.get("name", ""))
        norms[row["id"]] = norm

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for index, left in enumerate(rows):
        norm_left = norms.get(left["id"], "")
        if not norm_left:
            continue
        for right in rows[index + 1:]:
            norm_right = norms.get(right["id"], "")
            if not norm_right:
                continue
            short_name, long_name = sorted((norm_left, norm_right), key=len)
            if short_name not in long_name and \
                    (len(long_name) - len(short_name)) / len(long_name) > 0.4:
                continue
            if services.similarity(norm_left, norm_right) >= threshold:
                union(left["id"], right["id"])

    groups = defaultdict(list)
    for row in rows:
        groups[find(row["id"])].append(row)
    clusters = []
    for root, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda row: row["id"])
        clusters.append({
            "cluster_id": root,
            "size": len(members),
            "entity_ids": [row["id"] for row in members],
            "names": [row.get("name", "") for row in members],
            "suggested_target": members[0]["id"],
        })
    clusters.sort(key=lambda row: (-row["size"], row["cluster_id"]))
    return {
        "items": clusters[:max(1, int(limit))],
        "count": len(clusters),
        "threshold": threshold,
        "truncated": truncated,
        "entity_count": len(rows),
        "names": names,
    }
