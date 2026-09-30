# -*- coding: utf-8 -*-
"""编程通用知识：术语词典、编程范式、算法入门目录、数据结构词典，
以及跨 10 种语言的练习题库（单选 / 读程序写结果 / 代码填空 / 找错）。
"""

# ---------------- 编程范式 ----------------
PARADIGMS = [
    {"key": "imperative", "name": "命令式", "idea": "告诉计算机一步步怎么做，关注执行步骤。", "languages": ["C", "Python", "Go"], "example": "sum=0; for x in list: sum+=x"},
    {"key": "oop", "name": "面向对象", "idea": "把数据与行为封装成对象，通过继承、多态组织代码。", "languages": ["Java", "C++", "C#", "Python"], "example": "dog.bark()"},
    {"key": "functional", "name": "函数式", "idea": "用纯函数与不可变数据计算，避免副作用，强调 map/reduce。", "languages": ["Haskell", "JavaScript", "Python", "Scala"], "example": "list(map(lambda x:x*2, xs))"},
    {"key": "declarative", "name": "声明式", "idea": "描述想要什么结果，而不是怎么实现，如 SQL、HTML。", "languages": ["SQL", "HTML", "Prolog"], "example": "SELECT * FROM t WHERE id=1"},
    {"key": "concurrent", "name": "并发/响应式", "idea": "以轻量执行单元与消息通信处理大量并发任务。", "languages": ["Go", "Erlang", "Rust"], "example": "go handle(conn)"},
    {"key": "generic", "name": "泛型/元编程", "idea": "编写与具体类型无关、可复用的抽象代码。", "languages": ["C++(模板)", "Java(泛型)", "Rust(泛型)", "C#"], "example": "fn max<T:Ord>(a:T,b:T)->T"},
]

# ---------------- 编程术语词典 ----------------
GLOSSARY = [
    {"term": "变量 variable", "en": "variable", "desc": "给一块内存起名字，用来存放可改变的数据。", "tags": ["基础"]},
    {"term": "常量 constant", "en": "constant", "desc": "一旦赋值就不能改变的量，如 const/let(final/val)。", "tags": ["基础"]},
    {"term": "数据类型 type", "en": "data type", "desc": "规定数据的种类与可执行操作，分基本类型与复合类型。", "tags": ["基础"]},
    {"term": "运算符 operator", "en": "operator", "desc": "对数据进行运算的符号，如算术、比较、逻辑、位运算。", "tags": ["基础"]},
    {"term": "表达式 expression", "en": "expression", "desc": "由变量、常量、运算符组成、能算出一个值的式子。", "tags": ["基础"]},
    {"term": "语句 statement", "en": "statement", "desc": "执行一个动作的完整指令，如赋值语句、if 语句。", "tags": ["基础"]},
    {"term": "控制流 control flow", "en": "control flow", "desc": "决定代码执行顺序：顺序、分支(if/switch)、循环(for/while)。", "tags": ["基础"]},
    {"term": "函数 function", "en": "function", "desc": "可重复调用、接收参数并可返回值的一段代码。", "tags": ["基础"]},
    {"term": "参数与实参 parameter/argument", "en": "parameter", "desc": "形参是函数定义里的占位，实参是调用时真正传入的值。", "tags": ["基础"]},
    {"term": "返回值 return value", "en": "return", "desc": "函数执行后交还给调用处的结果。", "tags": ["基础"]},
    {"term": "递归 recursion", "en": "recursion", "desc": "函数直接或间接调用自身，须有终止条件防止无限递归。", "tags": ["进阶"]},
    {"term": "作用域 scope", "en": "scope", "desc": "变量可被访问的范围，分全局、局部、块级作用域。", "tags": ["进阶"]},
    {"term": "闭包 closure", "en": "closure", "desc": "函数与其定义时所在作用域变量的组合，可记住环境。", "tags": ["进阶"]},
    {"term": "高阶函数 higher-order function", "en": "higher-order function", "desc": "接收函数为参数或返回函数的函数，如 map/filter。", "tags": ["进阶"]},
    {"term": "回调 callback", "en": "callback", "desc": "把函数作为参数传入，在特定时机被调用，常见于异步。", "tags": ["进阶"]},
    {"term": "数组 array", "en": "array", "desc": "连续存储的同类型元素序列，按下标随机访问。", "tags": ["数据结构"]},
    {"term": "链表 linked list", "en": "linked list", "desc": "节点通过指针相连的线性结构，增删快、随机访问慢。", "tags": ["数据结构"]},
    {"term": "栈 stack", "en": "stack", "desc": "后进先出(LIFO)结构，push/pop，用于调用栈、撤销。", "tags": ["数据结构"]},
    {"term": "队列 queue", "en": "queue", "desc": "先进先出(FIFO)结构，enqueue/dequeue，用于排队任务。", "tags": ["数据结构"]},
    {"term": "哈希表 hash table", "en": "hash map", "desc": "通过哈希函数把键映射到位置，平均 O(1) 查找，如 dict/Map。", "tags": ["数据结构"]},
    {"term": "树 tree", "en": "tree", "desc": "分层结构，有根与子节点，二叉树、搜索树是常见形式。", "tags": ["数据结构"]},
    {"term": "堆 heap", "en": "heap", "desc": "可用数组表示的完全二叉树，分大顶/小顶堆，用于优先队列。", "tags": ["数据结构"]},
    {"term": "图 graph", "en": "graph", "desc": "顶点与边组成的网络，用于社交关系、路径规划。", "tags": ["数据结构"]},
    {"term": "算法 algorithm", "en": "algorithm", "desc": "解决问题的有限、确定步骤，关注正确性与复杂度。", "tags": ["算法"]},
    {"term": "时间复杂度 time complexity", "en": "big-o", "desc": "用大 O 描述运行时间随数据规模 n 的增长，如 O(1)/O(n)/O(log n)。", "tags": ["算法"]},
    {"term": "空间复杂度 space complexity", "en": "space complexity", "desc": "算法额外占用内存随 n 的增长量级。", "tags": ["算法"]},
    {"term": "排序 sorting", "en": "sorting", "desc": "把元素按规则排列，常见冒泡/选择/插入/快排/归并。", "tags": ["算法"]},
    {"term": "二分查找 binary search", "en": "binary search", "desc": "在有序序列中每次折半，O(log n) 定位目标。", "tags": ["算法"]},
    {"term": "动态规划 DP", "en": "dynamic programming", "desc": "把问题拆成重叠子问题并记忆结果，自底向上求解。", "tags": ["算法"]},
    {"term": "贪心 greedy", "en": "greedy", "desc": "每一步选当前最优，期望得到全局最优（需证明）。", "tags": ["算法"]},
    {"term": "编译 compile", "en": "compile", "desc": "把源代码整体翻译成机器码/字节码的过程。", "tags": ["工程"]},
    {"term": "解释执行 interpret", "en": "interpret", "desc": "逐行读取并立即执行源码，无需先生成可执行文件。", "tags": ["工程"]},
    {"term": "静态/动态类型", "en": "typing", "desc": "静态类型在编译期确定(C/Java)，动态类型在运行期确定(Python/JS)。", "tags": ["工程"]},
    {"term": "强/弱类型", "en": "strong/weak", "desc": "强类型不轻易隐式转换(Python)，弱类型会自动转换(JS/C)。", "tags": ["工程"]},
    {"term": "垃圾回收 GC", "en": "garbage collection", "desc": "运行时自动回收不再使用的内存，如 JVM/JS/Python。", "tags": ["工程"]},
    {"term": "指针 pointer", "en": "pointer", "desc": "保存内存地址的变量，C/C++ 中可直接操作内存。", "tags": ["底层"]},
    {"term": "栈与堆内存 stack/heap", "en": "memory", "desc": "栈存局部变量自动回收，堆手动或由 GC 管理、空间更大。", "tags": ["底层"]},
    {"term": "并发与并行 concurrency/parallelism", "en": "concurrency", "desc": "并发是交替处理多任务，并行是真正同时执行。", "tags": ["底层"]},
    {"term": "线程与进程 thread/process", "en": "process", "desc": "进程是资源分配单位，线程是 CPU 调度单位，同进程线程共享内存。", "tags": ["底层"]},
    {"term": "异常 exception", "en": "exception", "desc": "运行期错误对象，用 try/catch(Python 为 except)捕获处理。", "tags": ["工程"]},
    {"term": "面向对象三特性", "en": "oop pillars", "desc": "封装(隐藏细节)、继承(复用扩展)、多态(同一接口不同实现)。", "tags": ["OOP"]},
    {"term": "接口 interface", "en": "interface", "desc": "只约定方法签名而不写实现，类实现接口来保证具备某种能力。", "tags": ["OOP"]},
    {"term": "多态 polymorphism", "en": "polymorphism", "desc": "父类引用指向不同子类对象，调用同一方法表现不同行为。", "tags": ["OOP"]},
    {"term": "封装 encapsulation", "en": "encapsulation", "desc": "把数据与方法捆绑并控制访问权限，对外暴露必要接口。", "tags": ["OOP"]},
    {"term": "继承 inheritance", "en": "inheritance", "desc": "子类获得父类属性与方法，实现复用与层次分类。", "tags": ["OOP"]},
    {"term": "API", "en": "application programming interface", "desc": "程序对外提供的调用约定，函数、类、网络接口都算 API。", "tags": ["工程"]},
    {"term": "调试 debug", "en": "debug", "desc": "定位并修复缺陷，常用断点、单步、打印与日志。", "tags": ["工程"]},
    {"term": "版本控制 version control", "en": "git", "desc": "记录代码历史、支持分支协作，Git 是事实标准。", "tags": ["工程"]},
    {"term": "重构 refactor", "en": "refactor", "desc": "不改变外部行为，只改善内部结构与可读性。", "tags": ["工程"]},
    {"term": "单元测试 unit test", "en": "unit test", "desc": "对最小代码单元(函数/方法)编写自动化断言验证正确性。", "tags": ["工程"]},
    {"term": "字面量 literal", "en": "literal", "desc": "代码中直接写出的固定值，如 3、'hi'、true、[1,2]。", "tags": ["基础"]},
    {"term": "类型转换 cast/convert", "en": "type conversion", "desc": "把一种类型转为另一种，分隐式自动转换与显式转换(int/str)。", "tags": ["基础"]},
    {"term": "字符串 string", "en": "string", "desc": "由字符组成的不可变序列，支持索引、切片、拼接与格式化。", "tags": ["基础"]},
    {"term": "不可变 immutable", "en": "immutable", "desc": "对象创建后其值不能被修改，如 Python 元组/字符串、Java String。", "tags": ["基础"]},
    {"term": "可迭代 iterable", "en": "iterable", "desc": "可被 for 逐个取出元素的对象，如列表、字符串、range、生成器。", "tags": ["基础"]},
    {"term": "索引与切片 index/slice", "en": "slice", "desc": "用下标取元素，用 [起:止:步] 取一段，多数语言下标从 0 开始。", "tags": ["基础"]},
    {"term": "短路求值 short-circuit", "en": "short circuit", "desc": "逻辑与/或在结果已定时不再计算右侧，如 a and b、a || b。", "tags": ["基础"]},
    {"term": "三元运算 ternary", "en": "ternary", "desc": "根据条件在两个值中取一个，如 a if c else b / c?a:b。", "tags": ["基础"]},
    {"term": "可变参数 varargs", "en": "variadic", "desc": "函数接收任意数量实参，如 *args、...rest、params int[]。", "tags": ["基础"]},
    {"term": "默认参数 default argument", "en": "default argument", "desc": "调用时省略则使用预设值的形参。", "tags": ["基础"]},
    {"term": "lambda 匿名函数", "en": "lambda", "desc": "没有名字的短小函数，常作为参数传给排序、过滤等高阶函数。", "tags": ["进阶"]},
    {"term": "纯函数 pure function", "en": "pure function", "desc": "相同输入必得相同输出且无副作用，不依赖也不改变外部状态。", "tags": ["进阶"]},
    {"term": "副作用 side effect", "en": "side effect", "desc": "函数除返回值外对外部状态的改变，如改全局变量、写文件、发请求。", "tags": ["进阶"]},
    {"term": "柯里化 currying", "en": "currying", "desc": "把多参函数变为一系列单参函数，如 f(a,b)→f(a)(b)。", "tags": ["进阶"]},
    {"term": "不可变数据 immutable data", "en": "immutability", "desc": "更新时返回新对象而非原地修改，便于回溯与并发安全。", "tags": ["进阶"]},
    {"term": "迭代器 iterator", "en": "iterator", "desc": "记录遍历位置、可用 next 逐个取值的对象，耗尽即止。", "tags": ["进阶"]},
    {"term": "生成器 generator", "en": "generator", "desc": "用 yield 惰性产出序列，按需计算，节省内存。", "tags": ["进阶"]},
    {"term": "装饰器 decorator", "en": "decorator", "desc": "在不改原函数代码的前提下为其增加通用行为，如日志、计时、权限。", "tags": ["进阶"]},
    {"term": "协程 coroutine", "en": "coroutine", "desc": "可挂起恢复的轻量并发单元，用 async/await 协作式调度。", "tags": ["底层"]},
    {"term": "异步 async/await", "en": "async", "desc": "非阻塞处理 IO 密集任务，await 等待异步结果而不卡住线程。", "tags": ["底层"]},
    {"term": "锁 lock/mutex", "en": "mutex", "desc": "多线程访问共享资源时保证同一时刻只有一方进入临界区。", "tags": ["底层"]},
    {"term": "死锁 deadlock", "en": "deadlock", "desc": "多个线程互相持有对方需要的资源而永久等待，需按固定顺序加锁避免。", "tags": ["底层"]},
    {"term": "竞态条件 race condition", "en": "race condition", "desc": "结果依赖多个线程执行先后顺序而产生不确定错误。", "tags": ["底层"]},
    {"term": "调用栈 call stack", "en": "call stack", "desc": "记录函数调用层次的栈结构，栈溢出常因递归过深。", "tags": ["底层"]},
    {"term": "栈溢出 stack overflow", "en": "stack overflow", "desc": "递归缺少终止或层级过深导致调用栈超过上限。", "tags": ["底层"]},
    {"term": "内存泄漏 memory leak", "en": "memory leak", "desc": "不再使用的内存未能释放，长期累积使程序变慢甚至崩溃。", "tags": ["底层"]},
    {"term": "野/悬垂指针 dangling pointer", "en": "dangling pointer", "desc": "指向已释放内存的指针，继续使用会导致未定义行为。", "tags": ["底层"]},
    {"term": "值传递与引用传递", "en": "pass by value/reference", "desc": "值传递复制实参，函数内改不影响外部；引用传递共享同一对象。", "tags": ["底层"]},
    {"term": "浅拷贝与深拷贝", "en": "shallow/deep copy", "desc": "浅拷贝只复制外层、嵌套对象仍共享；深拷贝递归复制全部层级。", "tags": ["进阶"]},
    {"term": "序列化 serialization", "en": "serialization", "desc": "把对象转为可存储/传输的字节或 JSON，反序列化则还原。", "tags": ["工程"]},
    {"term": "编码 encoding", "en": "encoding", "desc": "字符与字节之间的映射，常见 ASCII/UTF-8/GBK，乱码多因编解码不一致。", "tags": ["工程"]},
    {"term": "正则表达式 regex", "en": "regex", "desc": "用模式串描述文本规则，用于匹配、查找、替换与校验。", "tags": ["工程"]},
    {"term": "时间/空间权衡 trade-off", "en": "trade-off", "desc": "常可用更多内存换更快速度(如表/缓存)，或反之，需按场景取舍。", "tags": ["算法"]},
    {"term": "分治 divide and conquer", "en": "divide and conquer", "desc": "把问题拆成同类子问题分别求解再合并，如归并排序。", "tags": ["算法"]},
    {"term": "递归三要素", "en": "recursion base", "desc": "明确递归定义、基线(终止)条件与向基线收敛的递归步骤。", "tags": ["算法"]},
    {"term": "剪枝 pruning", "en": "pruning", "desc": "搜索中提前排除不可能得到更优解的分支以减少计算。", "tags": ["算法"]},
    {"term": "缓存 cache", "en": "cache", "desc": "把昂贵计算或读取的结果暂存，命中时直接返回，如记忆化搜索。", "tags": ["工程"]},
    {"term": "类 class", "en": "class", "desc": "创建对象的蓝图，定义属性(字段)与行为(方法)。", "tags": ["OOP"]},
    {"term": "实例 instance", "en": "instance", "desc": "依据类创建出的具体对象，各自拥有独立的属性值。", "tags": ["OOP"]},
    {"term": "构造方法 constructor", "en": "constructor", "desc": "创建对象时自动调用、用于初始化字段的特殊方法(__init__/构造器)。", "tags": ["OOP"]},
    {"term": "抽象类/抽象方法 abstract", "en": "abstract", "desc": "只声明不实现、必须由子类重写，用于定义统一抽象。", "tags": ["OOP"]},
    {"term": "组合优于继承 composition", "en": "composition", "desc": "优先通过持有其他对象复用能力，比深层继承更灵活、耦合更低。", "tags": ["OOP"]},
    {"term": "设计模式 design pattern", "en": "design pattern", "desc": "面向对象设计中反复出现问题的成熟解法，如单例、工厂、观察者。", "tags": ["OOP"]},
    {"term": "内聚与耦合 cohesion/coupling", "en": "cohesion coupling", "desc": "高内聚指模块职责集中，低耦合指模块间依赖少，是良好设计目标。", "tags": ["工程"]},
    {"term": "复杂度最坏/平均/最好", "en": "case complexity", "desc": "同一算法在最坏、平均、最好输入下的复杂度可能不同，常关注最坏与平均。", "tags": ["算法"]},
    {"term": "原地算法 in-place", "en": "in-place", "desc": "只借助 O(1) 额外空间完成操作，如原地快排。", "tags": ["算法"]},
    {"term": "稳定性 stable sort", "en": "stable", "desc": "排序后相等元素保持原有相对顺序称为稳定，如归并、冒泡。", "tags": ["算法"]},
    {"term": "哈希冲突 hash collision", "en": "hash collision", "desc": "不同键映射到同一位置，用链地址法或开放寻址法解决。", "tags": ["数据结构"]},
    {"term": "负载因子 load factor", "en": "load factor", "desc": "哈希表已用槽位占比，超过阈值触发扩容(rehash)以保持效率。", "tags": ["数据结构"]},
]

# ---------------- 算法入门目录 ----------------
ALGORITHMS = [
    {"key": "complexity", "name": "复杂度分析", "level": "入门", "idea": "学会用大 O 评估算法快慢与内存占用。", "points": ["O(1) 常数", "O(log n) 对数", "O(n) 线性", "O(n log n)", "O(n²) 平方"]},
    {"key": "sort-bubble", "name": "冒泡排序", "level": "入门", "idea": "相邻元素两两比较交换，每轮把最大的冒到末尾。", "points": ["稳定排序", "时间 O(n²)", "空间 O(1)", "适合教学理解交换"]},
    {"key": "sort-select", "name": "选择排序", "level": "入门", "idea": "每轮从未排序区选最小放到已排序区末尾。", "points": ["交换次数少", "时间 O(n²)", "不稳定"]},
    {"key": "sort-insert", "name": "插入排序", "level": "入门", "idea": "像整理手牌，把元素插入前方有序区。", "points": ["对近乎有序数据很快", "时间 O(n²)", "稳定"]},
    {"key": "sort-quick", "name": "快速排序", "level": "进阶", "idea": "选基准分区，小的在左大的在右，递归处理。", "points": ["平均 O(n log n)", "原地分区", "最坏 O(n²)", "实践中最快之一"]},
    {"key": "sort-merge", "name": "归并排序", "level": "进阶", "idea": "分治：对半排序后再合并两个有序段。", "points": ["稳定 O(n log n)", "需要 O(n) 额外空间", "适合外排序"]},
    {"key": "search-binary", "name": "二分查找", "level": "入门", "idea": "有序数组中每次折半缩小范围。", "points": ["前提有序", "O(log n)", "注意循环边界与中点溢出"]},
    {"key": "search-linear", "name": "线性查找", "level": "入门", "idea": "从头到尾逐个比较。", "points": ["无需有序", "O(n)", "最简单直接"]},
    {"key": "dp-intro", "name": "动态规划入门", "level": "提高", "idea": "定义状态与转移方程，用子问题答案拼出大问题。", "points": ["最优子结构", "重叠子问题", "状态转移方程", "斐波那契/背包入门"]},
    {"key": "greedy-intro", "name": "贪心入门", "level": "进阶", "idea": "每步取当前最优，需证明贪心选择性质。", "points": ["找零钱问题", "区间调度", "并非总能得到全局最优"]},
    {"key": "backtrack", "name": "回溯/搜索", "level": "提高", "idea": "试错：选择-递归-撤销，系统枚举所有可能，如全排列、N 皇后。", "points": ["DFS 框架", "剪枝", "路径与选择列表"]},
    {"key": "bfs-dfs", "name": "图的遍历 BFS/DFS", "level": "进阶", "idea": "广度优先用队列层层扩展，深度优先用栈/递归一路到底。", "points": ["BFS 求最短步数", "DFS 求所有方案", "visited 防重复"]},
    {"key": "two-pointer", "name": "双指针", "level": "进阶", "idea": "用两个下标协同扫描，如有序两数之和、去重。", "points": ["对撞指针", "快慢指针", "滑动窗口"]},
    {"key": "recursion", "name": "递归与分治", "level": "入门", "idea": "把问题化为更小同类问题，注意基线条件。", "points": ["递归三要素", "调用栈", "汉诺塔/阶乘"]},
    {"key": "sort-heap", "name": "堆排序", "level": "提高", "idea": "借助大顶堆不断取堆顶并调整，实现原地排序。", "points": ["时间稳定 O(n log n)", "不稳定", "建堆 O(n)", "无需额外数组"]},
    {"key": "sort-shell", "name": "希尔排序", "level": "进阶", "idea": "按递减增量分组插入排序，最后整体近乎有序。", "points": ["插入排序改进", "增量序列影响效率", "不稳定", "平均优于 O(n²)"]},
    {"key": "sort-counting", "name": "计数/桶排序", "level": "进阶", "idea": "数据范围有限且为整数时，用计数数组统计实现线性排序。", "points": ["O(n+k)", "非比较排序", "需额外空间", "要求值域集中"]},
    {"key": "kmp", "name": "KMP 字符串匹配", "level": "提高", "idea": "预处理模式串的前缀函数，匹配失败时不回退主串指针。", "points": ["next/前缀函数", "O(n+m)", "避免重复比较", "用于查找子串"]},
    {"key": "union-find", "name": "并查集", "level": "提高", "idea": "用 parent 数组管理元素的分组，支持快速合并与判断同组。", "points": ["find 查根", "union 合并", "路径压缩", "按秩合并近 O(1)"]},
    {"key": "mst", "name": "最小生成树", "level": "提高", "idea": "在带权连通图中选边连接所有点且总权最小，Kruskal/Prime。", "points": ["Kruskal 并查集+排序", "Prim 从点扩展", "总权最小", "无环 n-1 条边"]},
    {"key": "dijkstra", "name": "最短路径 Dijkstra", "level": "提高", "idea": "从源点用优先队列每次确定最近未访问点并松弛邻边。", "points": ["非负权", "贪心+堆 O((V+E)logV)", "松弛操作", "单源最短路径"]},
    {"key": "topo", "name": "拓扑排序", "level": "提高", "idea": "对有向无环图反复取入度为 0 的点输出，安排先后次序。", "points": ["入度表+队列", "检测环", "任务依赖排序", "结果可不唯一"]},
    {"key": "knapsack", "name": "0/1 背包", "level": "提高", "idea": "每件物品选或不选，用 dp[j]=max(dp[j],dp[j-w]+v) 滚动求容量内最大价值。", "points": ["状态定义", "逆序枚举容量", "O(nV)", "可扩展完全/多重背包"]},
]

# ---------------- 数据结构词典 ----------------
DATA_STRUCTURES = [
    {"key": "array", "name": "数组", "pros": "随机访问 O(1)，内存连续缓存友好", "cons": "中间插入删除 O(n)，定长数组扩容代价高", "use": "需要按下标频繁读取、大小可预估"},
    {"key": "linkedlist", "name": "链表", "pros": "已知节点处增删 O(1)，动态增长", "cons": "随机访问 O(n)，额外存指针", "use": "频繁头尾增删、实现栈队列"},
    {"key": "stack", "name": "栈", "pros": "压入弹出 O(1)，结构简单", "cons": "只能访问栈顶", "use": "括号匹配、表达式求值、函数调用、撤销"},
    {"key": "queue", "name": "队列", "pros": "入队出队 O(1)", "cons": "不能随机访问", "use": "排队、BFS、消息缓冲、任务调度"},
    {"key": "hashmap", "name": "哈希表", "pros": "平均增删查 O(1)", "cons": "无序、最坏退化 O(n)、占内存", "use": "去重、计数、按键快速查找、缓存"},
    {"key": "set", "name": "集合", "pros": "元素唯一，成员判断快", "cons": "不保序(普通集合)", "use": "去重、交集并集差集"},
    {"key": "tree", "name": "二叉树/搜索树", "pros": "有序维护，查找插入 O(log n)(平衡时)", "cons": "实现复杂，可能失衡", "use": "有序数据、范围查询、索引"},
    {"key": "heap", "name": "堆/优先队列", "pros": "取最值 O(1)，插入调整 O(log n)", "cons": "不适合查找任意元素", "use": "TopK、定时任务、Dijkstra"},
    {"key": "graph", "name": "图", "pros": "表达任意关系网络", "cons": "算法复杂，邻接矩阵占空间", "use": "社交网络、地图路径、依赖关系"},
    {"key": "trie", "name": "字典树 Trie", "pros": "前缀检索高效，按字符共享", "cons": "节点多、耗内存", "use": "搜索提示、输入法、敏感词"},
    {"key": "deque", "name": "双端队列", "pros": "两端都能 O(1) 进出", "cons": "中间访问慢", "use": "滑动窗口、单调队列"},
    {"key": "bloom", "name": "布隆过滤器", "pros": "极省空间判断元素可能存在", "cons": "有误判、不能删除(标准)", "use": "缓存穿透防护、海量去重"},
    {"key": "monotonic", "name": "单调栈/单调队列", "pros": "每个元素最多进出一次，整体 O(n) 求最近更大/更小", "cons": "只维护单调性，不保留全部元素", "use": "下一个更大元素、滑动窗口最值"},
    {"key": "rbtree", "name": "平衡二叉树(红黑树)", "pros": "通过旋转着色保持近似平衡，操作稳定 O(log n)", "cons": "实现复杂、常数比哈希大", "use": "有序映射/集合(TreeMap、C++ map)"},
    {"key": "bplustree", "name": "B 树 / B+ 树", "pros": "矮胖多叉、磁盘 IO 少，叶子有序相连便于范围查询", "cons": "插入删除需分裂合并", "use": "数据库与文件系统索引"},
    {"key": "skiplist", "name": "跳表 SkipList", "pros": "多层索引平均 O(log n)，实现比平衡树简单、易并发", "cons": "靠随机层级，占额外指针", "use": "Redis ZSet、有序表"},
    {"key": "adjlist", "name": "邻接表/邻接矩阵", "pros": "邻接表省空间适合稀疏图，矩阵判断边 O(1) 适合稠密图", "cons": "邻接表查边慢，矩阵占 O(V²)", "use": "图的存储与遍历"},
    {"key": "segtree", "name": "线段树", "pros": "区间查询与单点/区间更新均 O(log n)", "cons": "需约 4n 空间，实现有门槛", "use": "区间和/最值、动态统计"},
]

# ---------------- 练习题库 ----------------
# type: quiz 单选 / output 读程序写结果 / fill 填空 / bug 找错
# level: 1 入门 2 进阶 3 提高
DRILLS = [
    # ===== Python =====
    {"id": "py-q1", "lang": "python", "type": "quiz", "level": 1, "stem": "Python 中用于输出内容到控制台的函数是？",
     "options": ["echo()", "print()", "console.log()", "printf()"], "answer": 1, "explain": "Python 用内置函数 print() 输出。"},
    {"id": "py-q2", "lang": "python", "type": "quiz", "level": 1, "stem": "表达式 len([1,2,3]) 的结果是？",
     "options": ["2", "3", "4", "报错"], "answer": 1, "explain": "列表有 3 个元素，len 返回 3。"},
    {"id": "py-q3", "lang": "python", "type": "quiz", "level": 2, "stem": "下列哪种结构键唯一、通过键快速查值？",
     "options": ["list", "tuple", "dict", "set"], "answer": 2, "explain": "dict 字典是键值映射，键唯一且查找平均 O(1)。"},
    {"id": "py-o1", "lang": "python", "type": "output", "level": 1, "stem": "阅读代码，写出输出结果：",
     "code": "s = 0\nfor i in range(1, 4):\n    s += i\nprint(s)", "answer": "6", "explain": "range(1,4) 是 1,2,3，求和为 6（不含 4）。"},
    {"id": "py-o2", "lang": "python", "type": "output", "level": 2, "stem": "阅读代码，写出输出结果：",
     "code": "print([x*x for x in range(3)])", "answer": "[0, 1, 4]", "explain": "range(3) 为 0,1,2，平方后组成列表。"},
    {"id": "py-f1", "lang": "python", "type": "fill", "level": 1, "stem": "补全代码：定义一个接收两个参数并返回之和的函数。",
     "code": "____ add(a, b):\n    ____ a + b", "answer": "def,return", "explain": "定义函数用 def，返回用 return。"},
    {"id": "py-b1", "lang": "python", "type": "bug", "level": 2, "stem": "下面代码想遍历列表却报错，问题出在哪？",
     "code": "xs = [1,2,3]\nfor i in xs:\n    if xs[i] == 2:\n        print('found')",
     "options": ["不能用 for 遍历列表", "把元素值当下标用了，应直接判断 i == 2", "列表不能用 == 比较", "缺少 else"], "answer": 1,
     "explain": "for i in xs 中 i 已经是元素值(1/2/3)，不能再当索引 xs[i]，直接写 if i == 2。"},

    # ===== JavaScript =====
    {"id": "js-q1", "lang": "javascript", "type": "quiz", "level": 1, "stem": "JS 中声明一个不可重新赋值的变量用？",
     "options": ["var", "let", "const", "static"], "answer": 2, "explain": "const 声明常量绑定，不能再赋值。"},
    {"id": "js-q2", "lang": "javascript", "type": "quiz", "level": 2, "stem": "[1,2,3].map(x=>x*2) 的结果是？",
     "options": ["[1,2,3]", "[2,4,6]", "[1,4,9]", "6"], "answer": 1, "explain": "map 对每个元素乘 2，得到 [2,4,6]。"},
    {"id": "js-o1", "lang": "javascript", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "let r = [];\nfor (let i=0;i<3;i++) r.push(i);\nconsole.log(r.length);", "answer": "3", "explain": "push 了 0,1,2 三个元素，length 为 3。"},
    {"id": "js-f1", "lang": "javascript", "type": "fill", "level": 1, "stem": "补全：定义一个箭头函数，返回两数之和。",
     "code": "const add = (a,b) ____ a + b;", "answer": "=>", "explain": "箭头函数用 =>，单表达式可省略花括号与 return。"},
    {"id": "js-b1", "lang": "javascript", "type": "bug", "level": 2, "stem": "比较结果与预期不符，原因是？",
     "code": "console.log('10' == 10, '10' === 10);",
     "options": ["两者都为 true", "== 会隐式转换故为 true，=== 类型不同为 false", "两者都为 false", "语法错误"], "answer": 1,
     "explain": "== 比较时会做类型转换，=== 同时比较类型与值，开发中应使用 ===。"},

    # ===== C =====
    {"id": "c-q1", "lang": "c", "type": "quiz", "level": 1, "stem": "C 程序的入口函数是？",
     "options": ["start()", "main()", "init()", "begin()"], "answer": 1, "explain": "C 程序从 main 函数开始执行。"},
    {"id": "c-q2", "lang": "c", "type": "quiz", "level": 2, "stem": "已有 int a=5; int *p=&a; 则 *p 的值是？",
     "options": ["a 的地址", "5", "随机值", "0"], "answer": 1, "explain": "&a 取地址赋给 p，*p 解引用得到 a 的值 5。"},
    {"id": "c-o1", "lang": "c", "type": "output", "level": 1, "stem": "阅读代码，写出输出：",
     "code": "int s=0,i;\nfor(i=1;i<=3;i++) s+=i;\nprintf(\"%d\",s);", "answer": "6", "explain": "1+2+3=6。"},
    {"id": "c-f1", "lang": "c", "type": "fill", "level": 2, "stem": "补全：在堆上申请能放 n 个 int 的空间并释放。",
     "code": "int *p = ____(n * sizeof(int));\n____(p);", "answer": "malloc,free", "explain": "malloc 申请堆内存，用完 free 释放。"},
    {"id": "c-b1", "lang": "c", "type": "bug", "level": 3, "stem": "scanf 读取整数失败/异常，最可能缺少什么？",
     "code": "int a;\nscanf(\"%d\", a);",
     "options": ["应该用 printf", "scanf 需要变量地址，应写 &a", "%d 应为 %s", "变量不能叫 a"], "answer": 1,
     "explain": "scanf 需要把输入写入变量，必须传地址 &a。"},

    # ===== C++ =====
    {"id": "cpp-q1", "lang": "cpp", "type": "quiz", "level": 1, "stem": "C++ 标准输出流对象是？",
     "options": ["cout", "print", "echo", "System.out"], "answer": 0, "explain": "用 std::cout 配合 << 输出。"},
    {"id": "cpp-q2", "lang": "cpp", "type": "quiz", "level": 2, "stem": "vector 末尾添加元素的方法是？",
     "options": ["add()", "push_back()", "append()", "insert_last()"], "answer": 1, "explain": "vector 用 push_back 在尾部追加。"},
    {"id": "cpp-o1", "lang": "cpp", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "vector<int> v={3,1,2};\nsort(v.begin(),v.end());\ncout<<v[0];", "answer": "1", "explain": "升序排序后最小元素 1 在下标 0。"},
    {"id": "cpp-f1", "lang": "cpp", "type": "fill", "level": 2, "stem": "补全：用范围 for 输出每个元素。",
     "code": "____(int x : v) cout << x;", "answer": "for", "explain": "C++11 范围 for：for(类型 变量:容器)。"},
    {"id": "cpp-b1", "lang": "cpp", "type": "bug", "level": 3, "stem": "以下内存使用的问题是？",
     "code": "int* p = new int(5);\n/* 忘记释放 */",
     "options": ["语法错误", "内存泄漏，应 delete p", "new 不能这样初始化", "p 是野指针"], "answer": 1,
     "explain": "new 出的堆内存需要 delete 释放，否则内存泄漏；现代代码优先智能指针。"},

    # ===== Java =====
    {"id": "java-q1", "lang": "java", "type": "quiz", "level": 1, "stem": "Java 中输出一行到控制台的写法是？",
     "options": ["print()", "cout.print()", "System.out.println()", "console.log()"], "answer": 2, "explain": "System.out.println 输出并换行。"},
    {"id": "java-q2", "lang": "java", "type": "quiz", "level": 2, "stem": "Java 中实现“一个类具备某接口约定”的关键字是？",
     "options": ["extends", "implements", "import", "throws"], "answer": 1, "explain": "类用 implements 实现接口，extends 用于继承类。"},
    {"id": "java-o1", "lang": "java", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "int s=0;\nfor(int i=1;i<=4;i++) s+=i;\nSystem.out.println(s);", "answer": "10", "explain": "1+2+3+4=10。"},
    {"id": "java-f1", "lang": "java", "type": "fill", "level": 1, "stem": "补全：定义一个返回整数、名为 add 的方法。",
     "code": "public ____ int add(int a,int b){ return a+b; }", "answer": "static", "explain": "在 main 中直接调用需声明 static（或通过对象调用）。"},
    {"id": "java-b1", "lang": "java", "type": "bug", "level": 2, "stem": "运行抛出 NullPointerException，可能原因是？",
     "code": "String s = null;\nSystem.out.println(s.length());",
     "options": ["length 拼写错误", "s 为 null 就调用方法，需先判空", "String 没有 length", "应为 size()"], "answer": 1,
     "explain": "null 引用不能调用方法，使用前判空或用 Optional。"},

    # ===== Go =====
    {"id": "go-q1", "lang": "go", "type": "quiz", "level": 1, "stem": "Go 中启动一个并发协程的关键字是？",
     "options": ["async", "go", "thread", "spawn"], "answer": 1, "explain": "在函数调用前加 go 即启动 goroutine。"},
    {"id": "go-q2", "lang": "go", "type": "quiz", "level": 2, "stem": "Go 中切片追加元素的内建函数是？",
     "options": ["push", "append", "add", "insert"], "answer": 1, "explain": "append(s, elems...) 返回扩容后的切片。"},
    {"id": "go-o1", "lang": "go", "type": "output", "level": 1, "stem": "阅读代码，写出输出：",
     "code": "s := 0\nfor i := 1; i <= 3; i++ { s += i }\nfmt.Println(s)", "answer": "6", "explain": "1+2+3=6。"},
    {"id": "go-f1", "lang": "go", "type": "fill", "level": 2, "stem": "补全：创建一个字符串到整数的映射并取值。",
     "code": "m := ____(map[string]int)\nv := m[\"a\"]", "answer": "make", "explain": "map 必须用 make 创建后才能写入。"},
    {"id": "go-b1", "lang": "go", "type": "bug", "level": 3, "stem": "向 map 写入时 panic，原因是？",
     "code": "var m map[string]int\nm[\"a\"] = 1",
     "options": ["键类型错误", "nil map 未 make 就写入", "不能用字符串键", "应使用 struct"], "answer": 1,
     "explain": "只声明的 map 是 nil，读取可以、写入会 panic，需 make(map[K]V)。"},

    # ===== Rust =====
    {"id": "rs-q1", "lang": "rust", "type": "quiz", "level": 1, "stem": "Rust 中声明可变变量需要哪个关键字？",
     "options": ["var", "let mut", "mutable", "volatile"], "answer": 1, "explain": "let 默认不可变，let mut 才可变。"},
    {"id": "rs-q2", "lang": "rust", "type": "quiz", "level": 2, "stem": "Rust 用哪个类型替代 null 来表示可能缺失？",
     "options": ["Nullable", "Option<T>", "Any", "Void"], "answer": 1, "explain": "Option 枚举 Some/None 在类型层面表达有无。"},
    {"id": "rs-o1", "lang": "rust", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "let v=vec![1,2,3];\nlet s:i32=v.iter().sum();\nprintln!(\"{}\",s);", "answer": "6", "explain": "1+2+3=6。"},
    {"id": "rs-f1", "lang": "rust", "type": "fill", "level": 1, "stem": "补全：定义一个返回 i32 的函数。",
     "code": "fn add(a:i32,b:i32) ____ i32 { a+b }", "answer": "->", "explain": "Rust 用 -> 标注返回类型。"},
    {"id": "rs-b1", "lang": "rust", "type": "bug", "level": 3, "stem": "编译报错 value borrowed after move，原因是？",
     "code": "let s1=String::from(\"a\");\nlet s2=s1;\nprintln!(\"{}\",s1);",
     "options": ["String 不能赋值", "s1 的所有权已移动给 s2，不能再用", "应使用 ==", "缺少 mut"], "answer": 1,
     "explain": "赋值默认移动所有权；想共享用借用 &s1，想复制用 clone()。"},

    # ===== C# =====
    {"id": "cs-q1", "lang": "csharp", "type": "quiz", "level": 1, "stem": "C# 中类型推断声明局部变量可用？",
     "options": ["dim", "var", "let", "auto"], "answer": 1, "explain": "var 在编译期根据右侧推断类型，仍是静态类型。"},
    {"id": "cs-q2", "lang": "csharp", "type": "quiz", "level": 2, "stem": "对集合做声明式过滤/投影用的是？",
     "options": ["SQL", "LINQ", "Regex", "Reflection"], "answer": 1, "explain": "LINQ 提供 Where/Select 等链式查询。"},
    {"id": "cs-o1", "lang": "csharp", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "var l=new List<int>{1,2,3};\nConsole.WriteLine(l.Sum());", "answer": "6", "explain": "Sum 求和 1+2+3=6（需 using System.Linq）。"},
    {"id": "cs-f1", "lang": "csharp", "type": "fill", "level": 2, "stem": "补全：定义异步方法。",
     "code": "async ____<string> Get(){ return await Read(); }", "answer": "Task", "explain": "异步方法返回 Task 或 Task<T>。"},
    {"id": "cs-b1", "lang": "csharp", "type": "bug", "level": 2, "stem": "出现 NullReferenceException，应优先怎么改？",
     "code": "string name=null;\nvar l=name.Length;",
     "options": ["把 Length 改 Size", "用 name?.Length 安全访问并兜底", "加 foreach", "改成 int"], "answer": 1,
     "explain": "空条件运算符 ?. 在为 null 时返回 null 而不是抛异常。"},

    # ===== Swift =====
    {"id": "sw-q1", "lang": "swift", "type": "quiz", "level": 1, "stem": "Swift 中声明常量的关键字是？",
     "options": ["var", "let", "const", "val"], "answer": 1, "explain": "let 声明常量，var 声明变量。"},
    {"id": "sw-q2", "lang": "swift", "type": "quiz", "level": 2, "stem": "Swift 中表示“可能为 nil”的写法是？",
     "options": ["String!", "String?", "String*", "OptionalString"], "answer": 1, "explain": "类型后加 ? 是可选类型 Optional。"},
    {"id": "sw-o1", "lang": "swift", "type": "output", "level": 1, "stem": "阅读代码，写出输出：",
     "code": "var s=0\nfor i in 1...3 { s+=i }\nprint(s)", "answer": "6", "explain": "1...3 为闭区间 1,2,3，和为 6。"},
    {"id": "sw-f1", "lang": "swift", "type": "fill", "level": 2, "stem": "补全：安全解包可选值，失败就返回。",
     "code": "____ let v = opt else { return }", "answer": "guard", "explain": "guard let 提前解包，失败走 else 退出。"},
    {"id": "sw-b1", "lang": "swift", "type": "bug", "level": 3, "stem": "运行崩溃 found nil while unwrapping，原因是？",
     "code": "var s:String? = nil\nlet v = s!",
     "options": ["应使用 var", "对为 nil 的可选值强制解包 !", "String 不能为可选", "语法错误"], "answer": 1,
     "explain": "! 强制解包为 nil 时崩溃，应使用 if let/guard let/??。"},

    # ===== Kotlin =====
    {"id": "kt-q1", "lang": "kotlin", "type": "quiz", "level": 1, "stem": "Kotlin 中声明只读变量的关键字是？",
     "options": ["let", "const", "val", "final"], "answer": 2, "explain": "val 只读，var 可变。"},
    {"id": "kt-q2", "lang": "kotlin", "type": "quiz", "level": 2, "stem": "Kotlin 里安全调用(为 null 不崩溃)的运算符是？",
     "options": ["?.", "!!", "::", "->"], "answer": 0, "explain": "?. 安全调用；!! 是强制解包可能抛 NPE。"},
    {"id": "kt-o1", "lang": "kotlin", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "val l=listOf(1,2,3)\nprintln(l.filter{it>1}.sum())", "answer": "5", "explain": "过滤掉 1 剩 2,3，求和为 5。"},
    {"id": "kt-f1", "lang": "kotlin", "type": "fill", "level": 1, "stem": "补全：定义函数。",
     "code": "____ add(a:Int,b:Int):Int = a+b", "answer": "fun", "explain": "Kotlin 用 fun 定义函数。"},
    {"id": "kt-b1", "lang": "kotlin", "type": "bug", "level": 3, "stem": "以下哪行可能抛空指针，应避免？",
     "code": "var s:String? = null\nval a = s!!.length",
     "options": ["用 s?.length 或 ?: 兜底，!! 在为 null 时抛 NPE", "String 不能可空", "length 应为 size", "应改 var"], "answer": 0,
     "explain": "!! 强制断言非空，为 null 即抛 NPE；优先 ?. 与 ?:。"},

    # ===== Python 补充 =====
    {"id": "py-q4", "lang": "python", "type": "quiz", "level": 2, "stem": "关于 list 与 tuple，下列说法正确的是？",
     "options": ["二者都可变", "list 可变、tuple 不可变", "二者都不可变", "tuple 用方括号"], "answer": 1,
     "explain": "列表 list 可变，元组 tuple 创建后不可修改。"},
    {"id": "py-o3", "lang": "python", "type": "output", "level": 2, "stem": "阅读代码，写出输出结果：",
     "code": "d = {'a': 1}\nd['b'] = 2\nprint(len(d))", "answer": "2", "explain": "新增键 b 后字典有 2 个键值对。"},
    {"id": "py-b2", "lang": "python", "type": "bug", "level": 3, "stem": "第二次调用结果与预期不符，根本原因是？",
     "code": "def add(x, acc=[]):\n    acc.append(x)\n    return acc\nprint(add(1))\nprint(add(2))",
     "options": ["append 用法错误", "可变默认参数在多次调用间共享同一个列表", "函数不能有默认参数", "return 位置错误"], "answer": 1,
     "explain": "默认参数在函数定义时只创建一次，可变默认值会在调用间累积；应写 acc=None 并在内部新建。"},
    # ===== JavaScript 补充 =====
    {"id": "js-q3", "lang": "javascript", "type": "quiz", "level": 2, "stem": "typeof null 的结果是？",
     "options": ["\"null\"", "\"undefined\"", "\"object\"", "\"number\""], "answer": 2,
     "explain": "这是 JS 历史遗留：typeof null 返回 \"object\"，判空要用 === null。"},
    {"id": "js-o2", "lang": "javascript", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "const a = [1,2,3];\nconst b = a;\nb.push(4);\nconsole.log(a.length);", "answer": "4",
     "explain": "数组是引用类型，b 与 a 指向同一数组，push 后 a 也变为 4 个元素。"},
    {"id": "js-b2", "lang": "javascript", "type": "bug", "level": 3, "stem": "判断 0.1+0.2===0.3 为 false，原因是？",
     "code": "console.log(0.1 + 0.2); // 0.30000000000000004",
     "options": ["JS 无法处理小数", "二进制浮点无法精确表示部分十进制小数，应比较差值是否足够小", "应改用整数除法", "需要先 parseInt"], "answer": 1,
     "explain": "IEEE754 双精度存在舍入误差，比较浮点数应判断 |a-b| 是否小于极小值 epsilon。"},
    # ===== C 补充 =====
    {"id": "c-q3", "lang": "c", "type": "quiz", "level": 2, "stem": "数组名作为函数实参传递时，本质传递的是？",
     "options": ["整个数组的拷贝", "数组首元素地址", "数组长度", "最后一个元素"], "answer": 1,
     "explain": "数组名在多数表达式中退化为指向首元素的指针。"},
    {"id": "c-o2", "lang": "c", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "int a[5] = {1,2,3};\nprintf(\"%d %d\", a[2], a[3]);", "answer": "3 0",
     "explain": "部分初始化时未显式赋值的元素自动初始化为 0。"},
    {"id": "c-b2", "lang": "c", "type": "bug", "level": 2, "stem": "if 条件恒为真，问题在于？",
     "code": "if (a = 5) { ... }",
     "options": ["应为比较 ==，误写成赋值 =", "if 后不能有花括号", "5 必须加引号", "变量不能叫 a"], "answer": 0,
     "explain": "= 是赋值，表达式值为 5(非0即真)；相等比较要用 ==。"},
    # ===== C++ 补充 =====
    {"id": "cpp-q3", "lang": "cpp", "type": "quiz", "level": 2, "stem": "关于 C++ 引用(reference)，正确的是？",
     "options": ["可以声明后再绑定", "定义时必须初始化且不能改绑", "可以为空", "与指针完全相同"], "answer": 1,
     "explain": "引用是对象的别名，必须初始化且一经绑定不可更改，也不存在空引用。"},
    {"id": "cpp-o2", "lang": "cpp", "type": "output", "level": 1, "stem": "阅读代码，写出输出：",
     "code": "string s = \"hello\";\ncout << s.size();", "answer": "5", "explain": "hello 有 5 个字符，size 返回长度 5。"},
    {"id": "cpp-b2", "lang": "cpp", "type": "bug", "level": 3, "stem": "向 vector 追加元素后继续使用旧迭代器，可能？",
     "code": "auto it = v.begin();\nv.push_back(99);\n*it; // 危险",
     "options": ["迭代器失效导致未定义行为", "语法错误", "push_back 不能用", "it 会自动更新"], "answer": 0,
     "explain": "扩容会重新分配内存，旧迭代器/引用失效，应在增删后重新获取。"},
    # ===== Java 补充 =====
    {"id": "java-q3", "lang": "java", "type": "quiz", "level": 2, "stem": "比较两个字符串内容是否相等应使用？",
     "options": ["s1 == s2", "s1.equals(s2)", "s1 = s2", "s1.compare(s2)"], "answer": 1,
     "explain": "== 比较引用地址，equals 才比较字符内容。"},
    {"id": "java-o2", "lang": "java", "type": "output", "level": 1, "stem": "阅读代码，写出输出：",
     "code": "String s = \"hello\";\nSystem.out.println(s.charAt(0));", "answer": "h",
     "explain": "charAt(0) 取下标 0 的字符 h。"},
    {"id": "java-b2", "lang": "java", "type": "bug", "level": 3, "stem": "在 for-each 遍历 ArrayList 时 remove 元素会？",
     "code": "for (String x : list) if (x.equals(\"a\")) list.remove(x);",
     "options": ["正常删除", "抛出 ConcurrentModificationException", "编译报错", "删除整个列表"], "answer": 1,
     "explain": "遍历中结构性修改触发快速失败，应用 Iterator.remove 或 removeIf。"},
    # ===== Go 补充 =====
    {"id": "go-q3", "lang": "go", "type": "quiz", "level": 2, "stem": "Go 中声明了局部变量却未使用，会？",
     "options": ["仅警告", "编译不通过", "运行报错", "自动删除"], "answer": 1,
     "explain": "Go 强制要求声明的局部变量与导入的包必须被使用，否则编译失败。"},
    {"id": "go-o2", "lang": "go", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "m := map[string]int{\"a\": 1}\nv, ok := m[\"b\"]\nfmt.Println(v, ok)", "answer": "0 false",
     "explain": "取不存在的键返回值类型零值 0，逗号 ok 形式返回 false。"},
    {"id": "go-b2", "lang": "go", "type": "bug", "level": 3, "stem": "对切片再切片后 append 意外改到原数据，因为？",
     "code": "a := []int{1,2,3}\nb := a[:2]\nb = append(b, 9)\n// a 也被改变",
     "options": ["切片共享底层数组且容量足够时 append 原地写入", "Go 的 bug", "必须先 copy 才能切片", "append 返回值无用"], "answer": 0,
     "explain": "切片是对底层数组的视图，未扩容时 append 会写回同一底层数组；需要独立副本用 copy。"},
    # ===== Rust 补充 =====
    {"id": "rs-q3", "lang": "rust", "type": "quiz", "level": 3, "stem": "Rust 借用检查的核心规则是？",
     "options": ["可同时有多个可变借用", "可有任意多个不可变借用，或唯一一个可变借用，二者不能同时存在", "不允许借用", "借用不需要生命周期"], "answer": 1,
     "explain": "同一时刻要么多个只读共享借用，要么一个可变独占借用，以此在编译期避免数据竞争。"},
    {"id": "rs-o2", "lang": "rust", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "let v = vec![1,2,3,4];\nlet n = v.iter().filter(|x| *x % 2 == 0).count();\nprintln!(\"{}\", n);", "answer": "2",
     "explain": "偶数为 2、4，共 2 个，count 计数为 2。"},
    {"id": "rs-b2", "lang": "rust", "type": "bug", "level": 3, "stem": "编译报错 cannot borrow as mutable because it is also borrowed as immutable，因为？",
     "code": "let r1 = &v;\nlet r2 = &mut v;\nprintln!(\"{}\", r1);",
     "options": ["把 v 声明为 mut 即可", "不可变借用 r1 仍存活时又进行可变借用，违反借用规则", "不能用 println", "应使用裸指针"], "answer": 1,
     "explain": "共享借用未结束时不能再可变借用；调整作用域，让 r1 最后一次使用之后再进行可变借用。"},
    # ===== C# 补充 =====
    {"id": "cs-q3", "lang": "csharp", "type": "quiz", "level": 2, "stem": "下列属于值类型的是？",
     "options": ["class", "string", "int(结构体)", "数组"], "answer": 2,
     "explain": "int 等基本类型是结构体、属于值类型，赋值时复制；class/string/数组是引用类型。"},
    {"id": "cs-o2", "lang": "csharp", "type": "output", "level": 1, "stem": "阅读代码，写出输出：",
     "code": "var s = \"Hello\";\nConsole.WriteLine(s.ToUpper());", "answer": "HELLO",
     "explain": "ToUpper 把字符串转为全大写 HELLO。"},
    {"id": "cs-b2", "lang": "csharp", "type": "bug", "level": 3, "stem": "foreach 遍历 List 时在循环内 Add/Remove 会？",
     "code": "foreach (var x in list) list.Add(x);",
     "options": ["正常执行", "抛出 InvalidOperationException(集合被修改)", "自动跳过", "只加一次"], "answer": 1,
     "explain": "枚举器检测到遍历期间版本变化即抛异常；应先收集再统一增删，或用 for 倒序删除。"},
    # ===== Swift 补充 =====
    {"id": "sw-q3", "lang": "swift", "type": "quiz", "level": 2, "stem": "Swift 中赋值时默认复制、属于值类型的是？",
     "options": ["class", "struct", "protocol", "closure"], "answer": 1,
     "explain": "struct/enum 是值类型，赋值传拷贝；class 是引用类型。"},
    {"id": "sw-o2", "lang": "swift", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "let a = [1,2,3]\nprint(a.map { $0 * 2 })", "answer": "[2, 4, 6]",
     "explain": "map 对每个元素乘 2，得到 [2,4,6]。"},
    {"id": "sw-b2", "lang": "swift", "type": "bug", "level": 2, "stem": "访问数组越界会发生什么？",
     "code": "let a = [1,2,3]\nlet x = a[5]",
     "options": ["返回 nil", "返回 0", "运行时直接崩溃(index out of range)", "编译报错"], "answer": 2,
     "explain": "数组下标越界不是返回 nil 而是运行时陷阱崩溃，访问前先判断下标范围。"},
    # ===== Kotlin 补充 =====
    {"id": "kt-q3", "lang": "kotlin", "type": "quiz", "level": 2, "stem": "data class 会自动生成下列哪组成员？",
     "options": ["仅构造函数", "equals/hashCode/toString/copy/componentN", "线程同步代码", "数据库表"], "answer": 1,
     "explain": "数据类自动按主构造属性生成相等性、拷贝与解构等方法。"},
    {"id": "kt-o2", "lang": "kotlin", "type": "output", "level": 2, "stem": "阅读代码，写出输出：",
     "code": "val r = (1..5).filter { it % 2 == 1 }.sum()\nprintln(r)", "answer": "9",
     "explain": "区间内奇数为 1,3,5，求和为 9。"},
    {"id": "kt-b2", "lang": "kotlin", "type": "bug", "level": 3, "stem": "对可空 var 属性判空后仍无法智能转换，因为？",
     "code": "var name: String? = null\nif (name != null) println(name.length) // 可能报错",
     "options": ["局部 val 才能稳定智能转换，可变属性可能在判断后被别处改空，应用 ?. 或先赋给局部 val", "Kotlin 不支持判空", "length 不存在", "必须用 !!"], "answer": 0,
     "explain": "可变(var)且非局部的属性无法保证判空后不变，故不能 smart cast，用 name?.length 或 val n=name。"},
]


def drills_by(lang=None, dtype=None, level=None):
    out = DRILLS
    if lang:
        out = [d for d in out if d["lang"] == lang]
    if dtype:
        out = [d for d in out if d["type"] == dtype]
    if level:
        out = [d for d in out if d["level"] == int(level)]
    return out


def public_drill(d, with_answer=False):
    """对外结构：默认不带答案，交卷判分时由服务端核对。"""
    item = {k: d.get(k) for k in ("id", "lang", "type", "level", "stem", "code", "options")}
    if with_answer:
        item["answer"] = d["answer"]
        item["explain"] = d["explain"]
    return item


# ---- v8 唯一文本合并（dsh 2026-09-30）：F515 术语例证语言 + F516 范式/算法/结构 复杂度与示例 ----
# 只增不改：只往既有条目上挂新字段，不动任何原有 key；import 失败不影响主流程。
try:
    from . import programming_v8 as _p8
except ImportError:  # 兼容脚本直连导入（无包上下文）
    try:
        import programming_v8 as _p8
    except ImportError:
        _p8 = None

if _p8 is not None:
    _GL = getattr(_p8, "GLOSSARY_LANGS", {})
    _CV = getattr(_p8, "CARD_V8", {})
    for _g in GLOSSARY:
        if _g.get("term") in _GL:
            _g["example_langs"] = _GL[_g["term"]]
    for _nm in ("PARADIGMS", "ALGORITHMS", "DATA_STRUCTURES"):
        for _item in globals()[_nm]:
            if _item.get("key") in _CV:
                _item.update(_CV[_item["key"]])
