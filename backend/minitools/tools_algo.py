# -*- coding: utf-8 -*-
"""minitools · 算法演示家族（13 个）：逐步追踪可视化。

去重：devtools/math 有 matrix/linear-solve/primes/expr/dist/dijkstra；
这里只做教学向步骤演示，不做工程求解。
"""
from .common import endpoint, ok, opt_bool, opt_num, opt_str, req_list, req_num, req_str


def _get_list(request, key="array"):
    vals = req_list(request, key)
    try:
        return [float(v) for v in vals]
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是数字数组")


@endpoint()
def bubble_steps(request):
    """A01. 冒泡排序每一步。"""
    arr = _get_list(request)
    a = arr[:]
    steps = [{"i": -1, "j": -1, "array": list(a), "note": "初始"}]
    n = len(a)
    for i in range(n - 1):
        for j in range(n - 1 - i):
            if a[j] > a[j + 1]:
                a[j], a[j + 1] = a[j + 1], a[j]
                steps.append({"i": i, "j": j, "array": list(a),
                              "note": f"交换 a[{j}] 与 a[{j+1}]"})
    steps.append({"i": -1, "j": -1, "array": list(a), "note": "完成"})
    return ok({"sorted": a, "steps": steps})


@endpoint()
def quick_steps(request):
    """A02. 快速排序分区过程。"""
    arr = _get_list(request)
    a = list(arr)
    events = []

    def qs(lo, hi):
        if lo >= hi:
            return
        pivot = a[hi]
        i = lo - 1
        for j in range(lo, hi):
            if a[j] <= pivot:
                i += 1
                a[i], a[j] = a[j], a[i]
                events.append({"array": list(a), "note": f"区间[{lo},{hi}] 交换位置 {i}<->{j}"})
        a[i + 1], a[hi] = a[hi], a[i + 1]
        events.append({"array": list(a), "note": f"pivot={pivot} 归位到 {i+1}"})
        qs(lo, i)
        qs(i + 2, hi)

    qs(0, len(a) - 1)
    return ok({"sorted": a, "steps": events})


@endpoint()
def binary_search_steps(request):
    """A03. 二分查找过程（输入数组需已排序）。"""
    arr = _get_list(request, "array")
    target = req_num(request, "target")
    lo, hi = 0, len(arr) - 1
    steps = []
    found = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        steps.append({"lo": lo, "hi": hi, "mid": mid,
                      "value": arr[mid], "compare": "==" if arr[mid] == target
                      else ("<" if arr[mid] < target else ">")})
        if arr[mid] == target:
            found = mid
            break
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return ok({"found_index": found, "steps": steps})


@endpoint()
def euclid_steps(request):
    """A04. 欧几里得求 gcd 的每一步。"""
    a = int(req_num(request, "a", minimum=0))
    b = int(req_num(request, "b", minimum=0))
    steps = []
    while b:
        steps.append({"a": a, "b": b, "quotient": a // b, "remainder": a % b})
        a, b = b, a % b
    return ok({"gcd": a, "steps": steps})


@endpoint()
def knapsack_dp(request):
    """A05. 0/1 背包 DP 表演示。weights/values 等长，capacity 背包容量。"""
    weights = _get_list(request, "weights")
    values = _get_list(request, "values")
    if len(weights) != len(values):
        raise ValueError("weights 与 values 长度需一致")
    cap = int(req_num(request, "capacity", minimum=0))
    n = len(weights)
    dp = [[0] * (cap + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        w = int(weights[i - 1])
        v = values[i - 1]
        for c in range(cap + 1):
            if w <= c:
                dp[i][c] = max(dp[i - 1][c], dp[i - 1][c - w] + v)
            else:
                dp[i][c] = dp[i - 1][c]
    return ok({"max_value": dp[n][cap], "dp_table": dp})


@endpoint()
def coin_greedy(request):
    """A06. 贪心找零（币值需为 canonical 才最优）。"""
    amount = int(req_num(request, "amount", minimum=0))
    coins = _get_list(request, "coins")
    coins = sorted([int(c) for c in coins], reverse=True)
    used = {}
    remain = amount
    for c in coins:
        cnt = remain // c
        if cnt:
            used[c] = cnt
            remain -= cnt * c
    return ok({"amount": amount, "used": used, "remainder": remain,
               "count": sum(used.values())})


GRAPH = {
    "A": ["B", "C"], "B": ["A", "D", "E"], "C": ["A", "F"],
    "D": ["B"], "E": ["B", "F"], "F": ["C", "E"],
}


@endpoint()
def bfs(request):
    """A07. BFS 广度优先遍历（内置样例图，可传 start）。"""
    start = opt_str(request, "start", "A")
    visited, queue, order = set(), [start], []
    while queue:
        node = queue.pop(0)
        if node in visited or node not in GRAPH:
            continue
        visited.add(node)
        order.append(node)
        queue.extend(n for n in GRAPH[node] if n not in visited)
    return ok({"graph": GRAPH, "start": start, "order": order})


@endpoint()
def dfs(request):
    """A08. DFS 深度优先遍历。"""
    start = opt_str(request, "start", "A")
    visited, order = set(), []

    def go(n):
        if n in visited or n not in GRAPH:
            return
        visited.add(n)
        order.append(n)
        for nb in GRAPH[n]:
            go(nb)

    go(start)
    return ok({"graph": GRAPH, "start": start, "order": order})


@endpoint()
def prim_mst(request):
    """A09. Prim 最小生成树（内置图）。"""
    edges = [
        ("A", "B", 4), ("A", "C", 2), ("B", "C", 1), ("B", "D", 5),
        ("C", "D", 8), ("C", "E", 10), ("D", "E", 2), ("D", "F", 6), ("E", "F", 3),
    ]
    nodes = sorted({n for e in edges for n in e[:2]})
    start = opt_str(request, "start", nodes[0])
    in_tree = {start}
    chosen = []
    while len(in_tree) < len(nodes):
        best = None
        for u, v, w in edges:
            if (u in in_tree) ^ (v in in_tree):
                if best is None or w < best[2]:
                    best = (u, v, w)
        if best is None:
            break
        chosen.append(best)
        in_tree.add(best[0])
        in_tree.add(best[1])
    return ok({"nodes": nodes, "mst_edges": chosen,
               "total_weight": sum(w for _, _, w in chosen)})


@endpoint()
def topo_sort(request):
    """A10. 拓扑排序（Kahn 算法，nodes/edges 可选）。"""
    nodes = ["A", "B", "C", "D", "E", "F"]
    edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"), ("D", "E"), ("C", "F")]
    indeg = {n: 0 for n in nodes}
    adj = {n: [] for n in nodes}
    for u, v in edges:
        indeg[v] += 1
        adj[u].append(v)
    queue = [n for n, d in indeg.items() if d == 0]
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for nb in adj[n]:
            indeg[nb] -= 1
            if indeg[nb] == 0:
                queue.append(nb)
    return ok({"order": order, "is_dag": len(order) == len(nodes)})


@endpoint()
def kmp(request):
    """A11. KMP 字符串匹配过程。"""
    text = req_str_text(request)
    pattern = req_str_pat(request)
    # 构建 next 表
    nxt = [0] * len(pattern)
    k = 0
    for i in range(1, len(pattern)):
        while k > 0 and pattern[i] != pattern[k]:
            k = nxt[k - 1]
        if pattern[i] == pattern[k]:
            k += 1
        nxt[i] = k
    events = []
    k = 0
    found = []
    for i, ch in enumerate(text):
        while k > 0 and ch != pattern[k]:
            k = nxt[k - 1]
        if ch == pattern[k]:
            k += 1
        if k == len(pattern):
            found.append(i - k + 1)
            events.append({"i": i, "matched_at": i - k + 1})
            k = nxt[k - 1]
    return ok({"text": text, "pattern": pattern, "next_table": nxt,
               "found_at": found})


# KMP 入参小助手（避免重复写 req_str）
from .common import req_str as _rs  # noqa: E402


def req_str_text(request):
    return _rs(request, "text")


def req_str_pat(request):
    return _rs(request, "pattern")


@endpoint()
def hanoi(request):
    """A12. 汉诺塔移动步骤。"""
    n = int(req_num(request, "n", minimum=1, maximum=10))
    moves = []

    def move(k, src, dst, aux):
        if k == 1:
            moves.append(f"{src} -> {dst}")
            return
        move(k - 1, src, aux, dst)
        moves.append(f"{src} -> {dst}")
        move(k - 1, aux, dst, src)

    move(n, "A", "C", "B")
    return ok({"disks": n, "total_moves": len(moves), "moves": moves})


@endpoint()
def josephus(request):
    """A13. 约瑟夫环：n 人报数到 k 出列，求幸存者。"""
    n = int(req_num(request, "n", minimum=1, maximum=10000))
    k = int(req_num(request, "k", minimum=1))
    people = list(range(1, n + 1))
    out = []
    idx = 0
    while len(people) > 1:
        idx = (idx + k - 1) % len(people)
        out.append(people.pop(idx))
    return ok({"survivor": people[0], "order": out, "n": n, "k": k})
