# -*- coding: utf-8 -*-
"""F515 + F516 编程广场增强数据（dsh 2026-09-30）。

- GLOSSARY_LANGS：99 条术语的「例证语言」，前端 Programming.vue 以标签挂在卡片下方。
- CARD_V8：六大范式 / 23 个算法 / 18 种数据结构的「复杂度 + 示例代码」，卡片点开后展示。

只增不改：本文件独立存在，由 programming.py 末尾的防御式合并段并入；
import 失败不影响主流程（与 chinese_v8 / english_v8 同一套模式）。
"""

# —— F515 术语例证语言（key 必须与 GLOSSARY 的 term 完全一致）——
GLOSSARY_LANGS = {
    "变量 variable": ["Python", "JavaScript", "C"],
    "常量 constant": ["JavaScript", "Rust", "C++"],
    "数据类型 type": ["C", "Java", "Python"],
    "运算符 operator": ["C", "Python", "JavaScript"],
    "表达式 expression": ["Python", "JavaScript", "Java"],
    "语句 statement": ["C", "Java", "Python"],
    "控制流 control flow": ["Python", "JavaScript", "Go"],
    "函数 function": ["Python", "JavaScript", "Go"],
    "参数与实参 parameter/argument": ["Python", "Java", "C"],
    "返回值 return value": ["C", "Python", "Go"],
    "递归 recursion": ["Python", "C", "JavaScript"],
    "作用域 scope": ["JavaScript", "Python", "C++"],
    "闭包 closure": ["JavaScript", "Python", "Go"],
    "高阶函数 higher-order function": ["JavaScript", "Python", "Kotlin"],
    "回调 callback": ["JavaScript", "C", "Python"],
    "数组 array": ["C", "Java", "Python"],
    "链表 linked list": ["C", "C++", "Java"],
    "栈 stack": ["C++", "Java", "Python"],
    "队列 queue": ["Java", "C++", "Python"],
    "哈希表 hash table": ["Python", "Java", "Go"],
    "树 tree": ["C++", "Java", "Python"],
    "堆 heap": ["C++", "Java", "Python"],
    "图 graph": ["C++", "Java", "Python"],
    "算法 algorithm": ["Python", "C++", "Go"],
    "时间复杂度 time complexity": ["Python", "C++", "Java"],
    "空间复杂度 space complexity": ["C", "C++", "Rust"],
    "排序 sorting": ["Python", "Java", "C++"],
    "二分查找 binary search": ["Python", "C++", "Java"],
    "动态规划 DP": ["Python", "C++", "Java"],
    "贪心 greedy": ["Python", "C++", "Go"],
    "编译 compile": ["C", "C++", "Rust", "Go"],
    "解释执行 interpret": ["Python", "JavaScript"],
    "静态/动态类型": ["Java", "C++", "Python", "JavaScript"],
    "强/弱类型": ["Python", "C", "JavaScript"],
    "垃圾回收 GC": ["Java", "Go", "C#", "Python"],
    "指针 pointer": ["C", "C++", "Go"],
    "栈与堆内存 stack/heap": ["C", "C++", "Rust"],
    "并发与并行 concurrency/parallelism": ["Go", "Java", "Python"],
    "线程与进程 thread/process": ["Java", "C++", "Python"],
    "异常 exception": ["Java", "Python", "C#"],
    "面向对象三特性": ["Java", "C++", "Python", "C#"],
    "接口 interface": ["Java", "Go", "C#"],
    "多态 polymorphism": ["Java", "C++", "Python"],
    "封装 encapsulation": ["Java", "C#", "Python"],
    "继承 inheritance": ["Java", "C++", "Python"],
    "API": ["Python", "JavaScript", "Go"],
    "调试 debug": ["Python", "JavaScript", "Java"],
    "版本控制 version control": ["Python", "Go", "JavaScript"],
    "重构 refactor": ["Python", "Java", "JavaScript"],
    "单元测试 unit test": ["Python", "Java", "Go"],
    "字面量 literal": ["Python", "C", "JavaScript"],
    "类型转换 cast/convert": ["C", "Python", "JavaScript"],
    "字符串 string": ["Python", "Java", "C++"],
    "不可变 immutable": ["Python", "Rust", "JavaScript"],
    "可迭代 iterable": ["Python", "JavaScript", "Java"],
    "索引与切片 index/slice": ["Python", "Go", "JavaScript"],
    "短路求值 short-circuit": ["Python", "JavaScript", "C"],
    "三元运算 ternary": ["C", "JavaScript", "Python"],
    "可变参数 varargs": ["Python", "Java", "C"],
    "默认参数 default argument": ["Python", "JavaScript", "C++"],
    "lambda 匿名函数": ["Python", "Java", "C++"],
    "纯函数 pure function": ["Python", "JavaScript", "Kotlin"],
    "副作用 side effect": ["JavaScript", "Python", "C"],
    "柯里化 currying": ["JavaScript", "Python"],
    "不可变数据 immutable data": ["Rust", "JavaScript", "Python"],
    "迭代器 iterator": ["Python", "Java", "C++"],
    "生成器 generator": ["Python", "JavaScript", "C#"],
    "装饰器 decorator": ["Python", "JavaScript"],
    "协程 coroutine": ["Python", "Kotlin", "C#", "Go"],
    "异步 async/await": ["JavaScript", "Python", "C#", "Kotlin"],
    "锁 lock/mutex": ["Go", "Java", "C++"],
    "死锁 deadlock": ["Java", "C++", "Go"],
    "竞态条件 race condition": ["Go", "Java", "C"],
    "调用栈 call stack": ["C", "Python", "Java"],
    "栈溢出 stack overflow": ["C", "Python", "Java"],
    "内存泄漏 memory leak": ["C", "C++", "Java"],
    "野/悬垂指针 dangling pointer": ["C", "C++", "Rust"],
    "值传递与引用传递": ["C", "C++", "Java", "Python"],
    "浅拷贝与深拷贝": ["Python", "JavaScript", "Java"],
    "序列化 serialization": ["Python", "Java", "JavaScript"],
    "编码 encoding": ["Python", "Java", "Go"],
    "正则表达式 regex": ["Python", "JavaScript", "Java"],
    "时间/空间权衡 trade-off": ["Python", "C++", "Go"],
    "分治 divide and conquer": ["Python", "C++", "Java"],
    "递归三要素": ["Python", "C", "Java"],
    "剪枝 pruning": ["Python", "C++", "Java"],
    "缓存 cache": ["Python", "Go", "Java"],
    "类 class": ["Java", "Python", "C++", "C#"],
    "实例 instance": ["Java", "Python", "C++"],
    "构造方法 constructor": ["Java", "Python", "C++"],
    "抽象类/抽象方法 abstract": ["Java", "C#", "Python"],
    "组合优于继承 composition": ["Java", "Go", "Python"],
    "设计模式 design pattern": ["Java", "C++", "Python"],
    "内聚与耦合 cohesion/coupling": ["Java", "Python", "Go"],
    "复杂度最坏/平均/最好": ["Python", "C++", "Java"],
    "原地算法 in-place": ["C", "C++", "Python"],
    "稳定性 stable sort": ["Python", "Java", "C++"],
    "哈希冲突 hash collision": ["Java", "Python", "Go"],
    "负载因子 load factor": ["Java", "Python", "Go"],
}

# —— F516 范式 / 算法 / 结构的复杂度与示例代码（key 必须与对应表的 key 一致）——
CARD_V8 = {
    # 六大编程范式
    "imperative": {
        "complexity": "复杂度取决于循环层数：单层遍历 O(n)，双层嵌套 O(n²)；命令式把「怎么做」写死，优化点最直观。",
        "sample": "nums = [3, 1, 2]\ntotal = 0\nfor x in nums:\n    total += x\nprint(total)  # 6",
    },
    "oop": {
        "complexity": "无固定量级；方法调用本身 O(1)，真实开销由内部实现决定，难点在对象图与继承层次的设计。",
        "sample": "class Dog:\n    def __init__(self, name):\n        self.name = name\n    def bark(self):\n        return f'{self.name}: 汪！'\n\nprint(Dog('旺财').bark())",
    },
    "functional": {
        "complexity": "纯函数可自由并行、可记忆化；map/filter 单遍 O(n)，链式调用仍是 O(n) 而非 O(n²)。",
        "sample": "nums = [1, 2, 3, 4]\nsq = list(map(lambda x: x * x, nums))\nprint(sq)  # [1, 4, 9, 16]",
    },
    "declarative": {
        "complexity": "只声明「要什么」，量级交给引擎（SQL / 正则 / HTML）；写法简单但性能取决于底层实现与索引。",
        "sample": "SELECT name\nFROM user\nWHERE age >= 18\nORDER BY age DESC;",
    },
    "concurrent": {
        "complexity": "吞吐随核心数提升但非线性；加锁后可能退化为串行，锁竞争严重时甚至比单线程更慢。",
        "sample": "import threading\n\ndef work(i):\n    print('worker', i)\n\nthreads = [threading.Thread(target=work, args=(i,)) for i in range(4)]\n[t.start() for t in threads]\n[t.join() for t in threads]",
    },
    "generic": {
        "complexity": "编译期展开（C++ 模板）或单态化（Rust 泛型），运行时无额外开销；代价是编译变慢、体积变大。",
        "sample": "template <typename T>\nT maxv(T a, T b) {\n    return a > b ? a : b;\n}\n// maxv<int>(3, 5) -> 5",
    },
    # 23 个入门算法
    "complexity": {
        "complexity": "量级排序：O(1) < O(log n) < O(n) < O(n log n) < O(n²) < O(2ⁿ) < O(n!)。",
        "sample": "# 同一件事的不同量级\n# O(n)：单层循环\nfor x in arr:\n    pass\n\n# O(n log n)：排序后再处理\narr.sort()",
    },
    "sort-bubble": {
        "complexity": "时间 O(n²)，已有序时最好 O(n)；空间 O(1)；稳定。",
        "sample": "def bubble(a):\n    n = len(a)\n    for i in range(n - 1):\n        swapped = False\n        for j in range(n - 1 - i):\n            if a[j] > a[j + 1]:\n                a[j], a[j + 1] = a[j + 1], a[j]\n                swapped = True\n        if not swapped:\n            break\n    return a",
    },
    "sort-select": {
        "complexity": "时间恒为 O(n²)（与初始顺序无关）；空间 O(1)；不稳定。",
        "sample": "def select(a):\n    n = len(a)\n    for i in range(n - 1):\n        m = i\n        for j in range(i + 1, n):\n            if a[j] < a[m]:\n                m = j\n        a[i], a[m] = a[m], a[i]\n    return a",
    },
    "sort-insert": {
        "complexity": "时间 O(n²)，近乎有序时接近 O(n)；空间 O(1)；稳定，适合小数组与在线数据。",
        "sample": "def insertion(a):\n    for i in range(1, len(a)):\n        cur, j = a[i], i - 1\n        while j >= 0 and a[j] > cur:\n            a[j + 1] = a[j]\n            j -= 1\n        a[j + 1] = cur\n    return a",
    },
    "sort-quick": {
        "complexity": "平均 O(n log n)，最坏（已有序且取端点做基准）O(n²)；空间 O(log n)（递归栈）；不稳定。",
        "sample": "def quick(a):\n    if len(a) <= 1:\n        return a\n    pivot = a[len(a) // 2]\n    left = [x for x in a if x < pivot]\n    mid = [x for x in a if x == pivot]\n    right = [x for x in a if x > pivot]\n    return quick(left) + mid + quick(right)",
    },
    "sort-merge": {
        "complexity": "稳定 O(n log n)；空间 O(n)（需额外数组），是外排序与链表排序的首选。",
        "sample": "def merge_sort(a):\n    if len(a) <= 1:\n        return a\n    mid = len(a) // 2\n    l, r = merge_sort(a[:mid]), merge_sort(a[mid:])\n    out, i, j = [], 0, 0\n    while i < len(l) and j < len(r):\n        if l[i] <= r[j]:\n            out.append(l[i]); i += 1\n        else:\n            out.append(r[j]); j += 1\n    return out + l[i:] + r[j:]",
    },
    "search-binary": {
        "complexity": "O(log n)，前提是序列已有序；比较次数约 log₂n（100 万条最多 20 次）。",
        "sample": "def bsearch(a, target):\n    lo, hi = 0, len(a) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if a[mid] == target:\n            return mid\n        if a[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1",
    },
    "search-linear": {
        "complexity": "O(n)；无需有序，适合小数据或一次性查找。",
        "sample": "def lsearch(a, target):\n    for i, x in enumerate(a):\n        if x == target:\n            return i\n    return -1",
    },
    "dp-intro": {
        "complexity": "时间 = 状态数 × 单次转移代价；空间可用滚动数组从 O(n) 压到 O(1)。",
        "sample": "# 爬楼梯：dp[i] = dp[i-1] + dp[i-2]\ndef climb(n):\n    a, b = 1, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
    },
    "greedy-intro": {
        "complexity": "通常 O(n log n)（含排序）或 O(n)；关键是证明「局部最优可推出全局最优」。",
        "sample": "# 找零：优先用大面额\ndef change(amount, coins=(100, 50, 20, 10, 5, 1)):\n    out = {}\n    for c in coins:\n        out[c], amount = divmod(amount, c)\n    return {k: v for k, v in out.items() if v}",
    },
    "backtrack": {
        "complexity": "最坏指数级 O(bᵈ)（b 分支数、d 深度），靠剪枝把实际搜索量大幅压小。",
        "sample": "def permute(nums, path=[]):\n    if not nums:\n        yield path\n    for i, x in enumerate(nums):\n        yield from permute(nums[:i] + nums[i + 1:], path + [x])",
    },
    "bfs-dfs": {
        "complexity": "BFS 与 DFS 均为 O(V + E)（顶点数 + 边数），空间分别 O(V)（队列）与 O(V)（递归栈）。",
        "sample": "from collections import deque\n\ndef bfs(g, s):\n    seen, q = {s}, deque([s])\n    while q:\n        u = q.popleft()\n        for v in g[u]:\n            if v not in seen:\n                seen.add(v); q.append(v)\n    return seen",
    },
    "two-pointer": {
        "complexity": "O(n)：两个指针各自单调移动，把原本 O(n²) 的嵌套比较降为一次线性扫描。",
        "sample": "def two_sum_sorted(a, target):\n    i, j = 0, len(a) - 1\n    while i < j:\n        s = a[i] + a[j]\n        if s == target:\n            return i, j\n        if s < target:\n            i += 1\n        else:\n            j -= 1\n    return None",
    },
    "recursion": {
        "complexity": "按递推式求解，如归并 T(n) = 2T(n/2) + O(n) → O(n log n)；递归深度受调用栈限制。",
        "sample": "def power(x, n):          # 快速幂 O(log n)\n    if n == 0:\n        return 1\n    half = power(x, n // 2)\n    return half * half * (x if n % 2 else 1)",
    },
    "sort-heap": {
        "complexity": "O(n log n)、空间 O(1)（原地）、不稳定；适合只要前 K 大 / 优先队列场景。",
        "sample": "import heapq\n\ndef heap_sort(a):\n    heapq.heapify(a)\n    return [heapq.heappop(a) for _ in range(len(a))]",
    },
    "sort-shell": {
        "complexity": "约 O(n^1.3)（依赖增量序列，Hibbard 序列为 O(n^1.5)）；空间 O(1)；不稳定。",
        "sample": "def shell(a):\n    gap = len(a) // 2\n    while gap:\n        for i in range(gap, len(a)):\n            cur, j = a[i], i\n            while j >= gap and a[j - gap] > cur:\n                a[j] = a[j - gap]; j -= gap\n            a[j] = cur\n        gap //= 2\n    return a",
    },
    "sort-counting": {
        "complexity": "O(n + k)（k 为值域大小），空间 O(k)；k 远大于 n 时反而浪费，仅适合整数且值域集中。",
        "sample": "def counting(a):\n    if not a:\n        return []\n    lo, hi = min(a), max(a)\n    cnt = [0] * (hi - lo + 1)\n    for x in a:\n        cnt[x - lo] += 1\n    out = []\n    for i, c in enumerate(cnt):\n        out += [i + lo] * c\n    return out",
    },
    "kmp": {
        "complexity": "O(n + m)（文本长 n、模式长 m）；next 数组预处理 O(m)，避免朴素匹配的回溯。",
        "sample": "def kmp_next(p):\n    nxt, k = [-1], -1\n    for i in range(1, len(p)):\n        while k >= 0 and p[i] != p[k + 1]:\n            k = nxt[k]\n        if p[i] == p[k + 1]:\n            k += 1\n        nxt.append(k)\n    return nxt",
    },
    "union-find": {
        "complexity": "路径压缩 + 按秩合并后近似 O(α(n)) ≈ O(1)，几乎常数。",
        "sample": "parent = {}\n\ndef find(x):\n    parent.setdefault(x, x)\n    while parent[x] != x:\n        parent[x] = parent[parent[x]]   # 路径压缩\n        x = parent[x]\n    return x\n\ndef union(a, b):\n    parent[find(a)] = find(b)",
    },
    "mst": {
        "complexity": "Kruskal O(E log E)（排序主导）；Prim 用二叉堆 O(E log V)。",
        "sample": "# Kruskal：按边权排序 + 并查集判环\ndef kruskal(n, edges):\n    edges.sort(key=lambda e: e[2])\n    total = 0\n    for u, v, w in edges:\n        if find(u) != find(v):\n            union(u, v); total += w\n    return total",
    },
    "dijkstra": {
        "complexity": "二叉堆实现 O((V + E) log V)；要求边权非负，负权需改用 Bellman-Ford。",
        "sample": "import heapq\n\ndef dijkstra(g, s):\n    dist = {s: 0}\n    pq = [(0, s)]\n    while pq:\n        d, u = heapq.heappop(pq)\n        if d > dist.get(u, float('inf')):\n            continue\n        for v, w in g[u]:\n            if d + w < dist.get(v, float('inf')):\n                dist[v] = d + w\n                heapq.heappush(pq, (d + w, v))\n    return dist",
    },
    "topo": {
        "complexity": "O(V + E)（Kahn 入度法）；只能用于有向无环图，可用于课程表 / 依赖排序。",
        "sample": "from collections import deque\n\ndef topo(g, indeg):\n    q = deque([u for u in g if indeg[u] == 0])\n    order = []\n    while q:\n        u = q.popleft(); order.append(u)\n        for v in g[u]:\n            indeg[v] -= 1\n            if indeg[v] == 0:\n                q.append(v)\n    return order if len(order) == len(g) else []   # 空列表即有环",
    },
    "knapsack": {
        "complexity": "时间 O(n × W)（物品数 × 容量），空间 O(W)（滚动数组）；W 很大时不可用。",
        "sample": "def knapsack(weights, values, cap):\n    dp = [0] * (cap + 1)\n    for w, v in zip(weights, values):\n        for c in range(cap, w - 1, -1):   # 倒序保证每件只用一次\n            dp[c] = max(dp[c], dp[c - w] + v)\n    return dp[cap]",
    },
    # 18 种核心数据结构
    "array": {
        "complexity": "按下标访问 O(1)；尾部追加均摊 O(1)；中间插入/删除 O(n)；查找 O(n)。",
        "sample": "a = [10, 20, 30]\nprint(a[1])        # 20  —— O(1)\na.insert(1, 15)    # 中间插入 O(n)\nprint(a)           # [10, 15, 20, 30]",
    },
    "linkedlist": {
        "complexity": "已知节点处插入/删除 O(1)；按下标访问 O(n)；无随机访问能力。",
        "sample": "class Node:\n    def __init__(self, v, nxt=None):\n        self.v, self.next = v, nxt\n\nhead = Node(1, Node(2, Node(3)))\nprint(head.next.v)   # 2",
    },
    "stack": {
        "complexity": "压栈 / 出栈 / 取栈顶均 O(1)；只允许在一端操作（后进先出）。",
        "sample": "s = []\ns.append(1); s.append(2)\nprint(s.pop())   # 2  —— 后进先出\nprint(s[-1])     # 1  —— 栈顶",
    },
    "queue": {
        "complexity": "入队 / 出队均摊 O(1)；先进先出，用 collections.deque 避免 list.pop(0) 的 O(n)。",
        "sample": "from collections import deque\nq = deque([1, 2])\nq.append(3)          # 入队\nprint(q.popleft())   # 1  —— 先进先出",
    },
    "hashmap": {
        "complexity": "平均 O(1) 增删查；最坏 O(n)（全部冲突退化为链表）；负载因子过高时扩容。",
        "sample": "d = {'a': 1}\nd['b'] = 2\nprint(d.get('c', 0))   # 0 —— 平均 O(1) 查找",
    },
    "set": {
        "complexity": "平均 O(1) 判存 / 增删；去重与交并差集合运算高效，不保证顺序。",
        "sample": "s = {1, 2, 2, 3}\nprint(s)              # {1, 2, 3} 自动去重\nprint(2 in s)         # True —— O(1) 判存",
    },
    "tree": {
        "complexity": "平衡 BST 增删查 O(log n)；退化成链表时 O(n)，故工程上多用红黑树 / AVL 自平衡。",
        "sample": "# 二叉搜索树查找\nclass T:\n    def __init__(self, v):\n        self.v, self.l, self.r = v, None, None\n\ndef find(node, x):\n    while node:\n        if x == node.v: return node\n        node = node.l if x < node.v else node.r\n    return None",
    },
    "heap": {
        "complexity": "取极值 O(1)、插入 / 弹出 O(log n)、建堆 O(n)；适合 Top-K 与优先队列。",
        "sample": "import heapq\nh = [5, 1, 3]\nheapq.heapify(h)          # O(n) 建堆\nheapq.heappush(h, 0)\nprint(heapq.heappop(h))   # 0 —— 每次 O(log n)",
    },
    "graph": {
        "complexity": "邻接表存储 O(V + E)；遍历 O(V + E)；邻接矩阵存储 O(V²) 但判边 O(1)。",
        "sample": "g = {0: [1, 2], 1: [2], 2: []}\nprint(g[0])          # [1, 2] 邻接表\n# 邻接矩阵：m[0][1] = 1 表示 0→1 有边",
    },
    "trie": {
        "complexity": "插入 / 查询 O(L)（L 为单词长度），与词库规模无关；空间换时间，前缀共享省内存。",
        "sample": "t = {}\ndef add(word):\n    node = t\n    for ch in word:\n        node = node.setdefault(ch, {})\n    node['#'] = True\n\nadd('cat')\nprint('c' in t and 'a' in t['c'])   # True",
    },
    "deque": {
        "complexity": "两端插入 / 删除均摊 O(1)；随机访问 O(1)，是滑动窗口的标配容器。",
        "sample": "from collections import deque\nd = deque([2, 3])\nd.appendleft(1)\nd.append(4)\nprint(d)   # deque([1, 2, 3, 4])",
    },
    "bloom": {
        "complexity": "插入 / 查询 O(k)（k 个哈希函数）；空间远小于哈希表，但有假阳性、不能删除元素。",
        "sample": "# 思想示意：k 个哈希映射到位数组\nbits = [0] * 32\ndef add(x, ks=(1, 7, 13)):\n    for k in ks:\n        bits[(x * k) % 32] = 1\nadd(42)\nprint(all(bits[(42 * k) % 32] for k in (1, 7, 13)))   # True",
    },
    "monotonic": {
        "complexity": "每个元素最多入栈 / 出栈一次，整体 O(n)；用于「下一个更大元素」与滑动窗口最值。",
        "sample": "def next_greater(a):\n    res, st = [-1] * len(a), []\n    for i, x in enumerate(a):\n        while st and a[st[-1]] < x:\n            res[st.pop()] = x\n        st.append(i)\n    return res\n\nprint(next_greater([2, 1, 3]))   # [3, 3, -1]",
    },
    "rbtree": {
        "complexity": "增删查稳定 O(log n)（靠红黑约束保持近似平衡，最长路径 ≤ 2×最短路径）。",
        "sample": "# 工程里直接用有序容器（底层多为红黑树）\nimport bisect\narr = [1, 3, 5]\nbisect.insort(arr, 4)     # 插入并保持有序\nprint(arr)                # [1, 3, 4, 5]",
    },
    "bplustree": {
        "complexity": "增删查 O(log n)，且树高低（阶数大）；叶子串成链表，范围查询高效，是数据库索引的主力结构。",
        "sample": "-- MySQL InnoDB 主键索引即 B+ 树\nSELECT * FROM t\nWHERE id BETWEEN 100 AND 200;   -- 叶子链表顺序扫描，避免回表多次",
    },
    "skiplist": {
        "complexity": "平均 O(log n)、最坏 O(n)（概率保证）；实现比红黑树简单，天然支持范围查询，Redis 的 zset 用它。",
        "sample": "# 思想示意：多层索引，层数随机\nimport random\ndef level():\n    lv = 1\n    while random.random() < 0.5 and lv < 32:\n        lv += 1\n    return lv\nprint(level() >= 1)   # True",
    },
    "adjlist": {
        "complexity": "邻接表空间 O(V + E)、遍历邻居 O(deg)；邻接矩阵空间 O(V²)、判边 O(1)；稀疏图用表、稠密图用矩阵。",
        "sample": "# 邻接表\ng = {0: [1, 2], 1: [2]}\n# 邻接矩阵\nm = [[0] * 3 for _ in range(3)]\nm[0][1] = 1\nprint(g[0], m[0])   # [1, 2] [0, 1, 0]",
    },
    "segtree": {
        "complexity": "建树 O(n)、单点更新 O(log n)、区间查询 O(log n)；适合频繁「区间求和 / 最值 + 单点修改」。",
        "sample": "class Seg:\n    def __init__(self, a):\n        self.n = len(a)\n        self.t = [0] * (2 * self.n)\n        for i, x in enumerate(a):\n            self.t[self.n + i] = x\n        for i in range(self.n - 1, 0, -1):\n            self.t[i] = self.t[2 * i] + self.t[2 * i + 1]\n\n    def query(self, l, r):        # [l, r) 区间和\n        res, l, r = 0, l + self.n, r + self.n\n        while l < r:\n            if l & 1:\n                res += self.t[l]; l += 1\n            if r & 1:\n                r -= 1; res += self.t[r]\n            l //= 2; r //= 2\n        return res",
    },
}
