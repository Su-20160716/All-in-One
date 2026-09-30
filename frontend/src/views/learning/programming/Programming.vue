<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">编程语言广场</h2>
        <p class="text-[12px] text-ink-400">10 种主流语言的元信息、学习路线、语法速查、课程与代码片段</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in topTabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="topTab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="topTab = t.v">{{ t.label }}</button>
      </div>
    </div>

    <!-- 语言广场 -->
    <div v-if="topTab === 'square'" class="grid grid-cols-12 gap-4">
      <p class="col-span-12 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        主世界：左列是 10 门语言，各带难度星级（难度 1 最好上手），点一门右侧打开它的专属档案——
        顶部是诞生年份、设计者、类型系统，下面 11 个子标签像翻书一样逐页看；右上角「收藏片段/语言」
        会把这门语言连同 Hello World 收进「我的学习 · 代码收藏」。
      </p>
      <div class="col-span-3 space-y-1.5">
        <button v-for="l in langs" :key="l.key" class="card flex w-full items-center gap-2.5 p-2.5 text-left transition-shadow"
          :class="cur === l.key ? 'ring-2 ring-brand-500' : 'hover:shadow-pop'" @click="openLang(l.key)">
          <span class="text-[18px]">{{ l.icon }}</span>
          <span class="flex-1 text-[13px] font-medium text-ink-800">{{ l.name }}</span>
          <span class="tag">难度{{ l.difficulty }}</span>
        </button>
      </div>

      <div class="col-span-9">
        <div v-if="!cur" class="card grid h-72 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          左边选一门语言（默认可从 Python 开始，难度 ★1）：右边会加载它的 11 个子标签——概览、路线、速查、关键字……
        </div>
        <div v-else class="card p-5">
          <div class="flex flex-wrap items-center gap-3">
            <span class="text-[28px]">{{ detail.icon }}</span>
            <div>
              <h3 class="text-[17px] font-semibold text-ink-900">{{ detail.name }} <span class="text-[12px] font-normal text-ink-400">{{ detail.en }}</span></h3>
              <div class="mt-0.5 flex flex-wrap gap-1.5 text-[11px] text-ink-500">
                <span class="tag">{{ detail.year }} 年诞生</span><span class="tag">{{ detail.designer }}</span>
                <span class="tag">{{ detail.typing }}</span>
              </div>
            </div>
            <button class="btn-outline ml-auto" @click="bookmark">收藏片段/语言</button>
          </div>

          <div class="mt-4 flex flex-wrap gap-1 border-b border-ink-100 pb-2">
            <button v-for="s in subTabs" :key="s.v" class="rounded-pill px-3 py-1 text-[12px]"
              :class="subTab === s.v ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-100'" @click="loadSub(s.v)">{{ s.label }}</button>
          </div>

          <div class="pt-4 text-[13px] leading-7 text-ink-700">
            <!-- 概览 -->
            <div v-if="subTab === 'overview'" class="space-y-3">
              <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                这门语言的名片：一句 summary、几条「为什么学它」、支持的范式与典型领域，底部还有一段可直接复制运行的
                Hello World——第一次点开一门语言，先看这页再往其它标签走。
              </p>
              <p>{{ detail.summary }}</p>
              <div><span class="font-semibold text-ink-800">为什么学它：</span>
                <ul class="ml-4 list-disc"><li v-for="(w, i) in detail.why" :key="i">{{ w }}</li></ul>
              </div>
              <div class="flex flex-wrap gap-1.5"><span class="font-semibold text-ink-800">范式：</span><span v-for="p in detail.paradigms" :key="p" class="tag-brand">{{ p }}</span></div>
              <div class="flex flex-wrap gap-1.5"><span class="font-semibold text-ink-800">领域：</span><span v-for="d in detail.domains" :key="d" class="tag">{{ d }}</span></div>
              <div><span class="font-semibold text-ink-800">Hello World：</span>
                <pre class="mt-1 rounded-control bg-ink-900 p-3 font-mono text-[12px] text-ink-100">{{ detail.hello }}</pre>
              </div>
            </div>

            <!-- 路线 -->
            <div v-else-if="subTab === 'roadmap'">
              <p class="mb-3 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                按阶段排好的地图：入门 / 进阶 / 提高 / 方向（各语言阶段名略有不同），每段写明 goal 和要掌握的
                items 知识点标签，照着从上往下走不会漏基础；学到一半迷路时回这张表对一下位置。
              </p>
              <ol class="space-y-3">
                <li v-for="(r, i) in cache.roadmap" :key="i" class="rounded-control border border-ink-100 p-3">
                  <div class="flex items-center gap-2"><span class="tag-brand">{{ r.stage }}</span><span class="font-semibold text-ink-800">{{ r.title }}</span></div>
                  <div class="mt-1 text-ink-600">目标：{{ r.goal }}</div>
                  <div class="mt-1 flex flex-wrap gap-1.5"><span v-for="t in r.items" :key="t" class="tag">{{ t }}</span></div>
                </li>
              </ol>
              <div v-if="!cache.roadmap?.length" class="rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                这门语言的路线还没加载出来：切到「概览」再切回来，或刷新页面重取。
              </div>
            </div>

            <!-- 速查 -->
            <div v-else-if="subTab === 'cheatsheet'" class="grid gap-2 md:grid-cols-2">
              <p class="col-span-full rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                忘了怎么写就来查：两列卡片按「变量赋值 / 输入输出 / 条件 / for 循环 / 函数 / 异常 / 文件…」
                列出常用语法点，每张配一段可直接复制的 code；文字讲解（note）后端补上后会显示在代码下面。
              </p>
              <div v-for="(c, i) in cache.cheatsheet" :key="i" class="rounded-control border border-ink-100 p-2.5">
                <div class="mb-1 text-[12px] font-semibold text-ink-700">{{ c.point }}</div>
                <pre class="overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ c.code }}</pre>
                <div v-if="c.note" class="mt-1 text-[12px] leading-5 text-ink-500">{{ c.note }}</div>
              </div>
              <div v-if="!cache.cheatsheet?.length" class="col-span-full rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                速查卡还没取到：这门语言的语法速查在切换标签时才请求，稍等或刷新重试。
              </div>
            </div>

            <!-- 关键字 -->
            <div v-else-if="subTab === 'keywords'" class="space-y-3">
              <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                关键字按钮墙：点任意一个（Python 的 def、Rust 的 mut、Go 的 defer…），下方展开它的定义、
                语法和可运行示例，再点一次收起。没点的时候这里只留一行提示，别急着翻走。
              </p>
              <div class="flex flex-wrap gap-1.5">
                <button v-for="k in cache.keywords" :key="k.word || k" class="rounded-pill bg-ink-900 px-2.5 py-1 font-mono text-[12px] text-ink-100 transition hover:bg-brand-600"
                  :class="selKeyword === (k.word || k) ? 'bg-brand-600 ring-2 ring-brand-400' : ''"
                  @click="selectKeyword(k)">{{ k.word || k }}</button>
              </div>
              <div v-if="keywordDetail" class="rounded-control border border-brand-200 bg-brand-50 p-4">
                <div class="flex items-center gap-2">
                  <span class="font-mono text-[16px] font-bold text-brand-700">{{ keywordDetail.word }}</span>
                  <span class="tag-brand">关键字详解</span>
                </div>
                <div class="mt-2 text-[13px] text-ink-700"><span class="font-semibold">定义：</span>{{ keywordDetail.desc }}</div>
                <div class="mt-2 text-[13px] text-ink-700"><span class="font-semibold">语法：</span><code class="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-[12px]">{{ keywordDetail.syntax }}</code></div>
                <div class="mt-2">
                  <div class="text-[13px] font-semibold text-ink-700">示例：</div>
                  <pre class="mt-1 overflow-auto rounded-control bg-ink-900 p-3 font-mono text-[12px] text-ink-100">{{ keywordDetail.example }}</pre>
                </div>
              </div>
              <div v-else class="text-[12px] text-ink-400">点击上方任意关键字查看完整教学（定义、语法、示例）</div>
            </div>

            <!-- 模块用法 -->
            <div v-else-if="subTab === 'modules'" class="space-y-3">
              <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                按模块名挑一个（Python 的 os / random、JavaScript 的 Math / JSON…），下方给出模块说明、
                常用函数清单、完整示例代码和注意事项——写文件、发请求前先来这里对一遍 API，别凭记忆拼函数名。
              </p>
              <div class="grid gap-2 md:grid-cols-2">
                <button v-for="m in cache.modules" :key="m.index" class="rounded-control border border-ink-100 p-3 text-left transition hover:border-brand-300 hover:shadow-sm"
                  :class="selModule === m.index ? 'border-brand-500 ring-2 ring-brand-200' : ''"
                  @click="selectModule(m.index)">
                  <div class="font-mono text-[13px] font-semibold text-brand-700">{{ m.name }}</div>
                  <div class="mt-1 text-[11px] text-ink-500 line-clamp-2">{{ m.desc }}</div>
                </button>
              </div>
              <div v-if="moduleDetail" class="rounded-control border border-brand-200 bg-white p-4 shadow-sm">
                <div class="flex items-center gap-2 border-b border-ink-100 pb-2">
                  <span class="font-mono text-[15px] font-bold text-brand-700">{{ moduleDetail.name }}</span>
                  <span class="tag-brand">模块完整用法</span>
                </div>
                <div class="mt-2 text-[13px] text-ink-700">{{ moduleDetail.desc }}</div>
                <div class="mt-3">
                  <div class="text-[13px] font-semibold text-ink-800">常用函数/方法：</div>
                  <div class="mt-1 flex flex-wrap gap-1">
                    <span v-for="(f, i) in moduleDetail.functions" :key="i" class="tag font-mono text-[11px]">{{ f }}</span>
                  </div>
                </div>
                <div class="mt-3">
                  <div class="text-[13px] font-semibold text-ink-800">完整示例代码：</div>
                  <pre class="mt-1 max-h-96 overflow-auto rounded-control bg-ink-900 p-3 font-mono text-[11px] text-ink-100">{{ moduleDetail.example }}</pre>
                </div>
                <div class="mt-3">
                  <div class="text-[13px] font-semibold text-ink-800">注意事项：</div>
                  <div class="mt-1 text-[12px] text-ink-600">{{ moduleDetail.tips }}</div>
                </div>
              </div>
              <div v-else class="text-[12px] text-ink-400">点击上方任意模块查看完整用法（函数列表、示例代码、注意事项）</div>
            </div>

            <!-- 类型 -->
            <div v-else-if="subTab === 'types'" class="grid gap-2 md:grid-cols-2">
              <p class="col-span-full rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                两列卡片列出这门语言的类型：名称、说明和示例。换语言时类型系统差异最大（静态 / 动态、值 / 引用），
                所以这张表值得扫一遍；点卡片可展开取值范围和转换陷阱（range_note / trap）。
              </p>
              <div v-for="(t, i) in cache.types" :key="i" class="cursor-pointer rounded-control border p-2.5 transition-colors"
                :class="openCard === 't:' + i ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100 hover:border-brand-200'"
                @click="toggleCard('t:' + i)">
                <div class="flex items-center gap-2">
                  <span class="font-mono text-[13px] font-semibold text-brand-700">{{ t.name }}</span>
                  <span class="ml-auto text-[11px] text-brand-600">{{ openCard === 't:' + i ? '收起 ▲' : '详情 ▼' }}</span>
                </div>
                <div class="text-[12px] text-ink-500">{{ t.desc }}</div>
                <pre class="mt-1 rounded-control bg-ink-50 p-2 font-mono text-[11px] text-ink-700">{{ t.example }}</pre>
                <div v-if="openCard === 't:' + i" class="mt-2 space-y-1 border-t border-ink-100 pt-2 text-[12px] leading-6">
                  <div v-if="t.range_note"><span class="font-semibold text-ink-700">取值范围：</span><span class="text-ink-600">{{ t.range_note }}</span></div>
                  <div v-if="t.trap" class="text-rose-500"><span class="font-semibold text-rose-600">转换陷阱：</span>{{ t.trap }}</div>
                  <div v-if="!t.range_note && !t.trap" class="text-ink-400">该类型的取值范围与转换陷阱正由后端逐语言补齐，先看上面的说明与示例。</div>
                </div>
              </div>
              <div v-if="!cache.types?.length" class="col-span-full rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                类型表还没取到：切到「概览」再切回来触发一次请求，或刷新页面。
              </div>
            </div>

            <!-- 课程 -->
            <div v-else-if="subTab === 'lessons'" class="space-y-2">
              <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                每门语言 5 节可折叠课：一行是课名和一句 summary，点开看到本课要点 points 和配套代码。
                按顺序一天只学一节、跟着敲完就走，比囤课有效。
              </p>
              <div v-for="ls in cache.lessons" :key="ls.index" class="rounded-control border border-ink-100">
                <button class="flex w-full items-center justify-between p-3 text-left" @click="openLesson(ls.index)">
                  <span class="font-semibold text-ink-800">{{ ls.title }}</span><span class="text-[12px] text-ink-400">{{ ls.summary }}</span>
                </button>
                <div v-if="lesson && lessonIdx === ls.index" class="border-t border-ink-100 p-3">
                  <ul class="ml-4 list-disc text-[12px] text-ink-600"><li v-for="(p, i) in lesson.points" :key="i">{{ p }}</li></ul>
                  <pre class="mt-2 overflow-auto rounded-control bg-ink-900 p-2.5 font-mono text-[11px] text-ink-100">{{ lesson.code }}</pre>
                </div>
              </div>
              <div v-if="!cache.lessons?.length" class="rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                课程列表还没加载：切到「概览」再切回来，或刷新页面重取。
              </div>
            </div>

            <!-- 片段 -->
            <div v-else-if="subTab === 'snippets'" class="space-y-2">
              <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                按主题分组的可复用片段：黑底代码加一句 explain（比如「Counter 一行完成计数」「yield 惰性产出」）。
                看到合用的点右上角「收藏片段/语言」，它会进「我的学习 · 代码收藏」，下次不用再翻。
              </p>
              <div v-for="s in cache.snippets" :key="s.index" class="rounded-control border border-ink-100 p-3">
                <div class="flex items-center gap-2"><span class="font-semibold text-ink-800">{{ s.title }}</span><span class="tag">{{ s.topic }}</span></div>
                <pre class="mt-1.5 overflow-auto rounded-control bg-ink-900 p-2.5 font-mono text-[11px] text-ink-100">{{ s.code }}</pre>
                <div class="mt-1 text-[12px] text-ink-500">{{ s.explain }}</div>
              </div>
              <div v-if="!cache.snippets?.length" class="rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                片段还没取到：这门语言的片段按需加载，切到别的子标签再切回来试试。
              </div>
            </div>

            <!-- 环境 -->
            <div v-else-if="subTab === 'ide'" class="grid gap-2 md:grid-cols-2">
              <p class="col-span-full rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                这门语言用什么写？这里只给结论：推荐的编辑器 / IDE 与一句话搭建说明。装环境卡住时，
                先照着这几条核对版本和 PATH，比到处搜教程快。
              </p>
              <div v-for="(e, i) in cache.ide" :key="i" class="rounded-control border border-ink-100 p-3">
                <div class="font-semibold text-ink-800">{{ e.name }}</div><div class="text-[12px] text-ink-500">{{ e.desc }}</div>
              </div>
              <div v-if="!cache.ide?.length" class="col-span-full rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                环境建议还没加载：切到「概览」再切回来触发一次请求。
              </div>
            </div>

            <!-- 规范 -->
            <div v-else-if="subTab === 'style'">
              <p class="mb-3 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                公认写法一条条列在这里（命名、缩进、引号、注释、模块组织…）。写完代码回头对照，
                能筛掉大部分“能跑但不规范”的写法——和别人协作时尤其管用。
              </p>
              <ul class="ml-4 list-disc space-y-1">
                <li v-for="(s, i) in cache.style" :key="i">{{ s }}</li>
              </ul>
              <div v-if="!cache.style?.length" class="rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                规范条目还没加载：切到「概览」再切回来，或刷新页面重取。
              </div>
            </div>

            <!-- 报错 -->
            <div v-else-if="subTab === 'errors'" class="space-y-2">
              <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
                卡壳时来这里对号入座：红色是报错原文（SyntaxError、NullPointerException、borrow checker…），
                下面固定两行——「原因」和「解决」。把控制台红字复制过来搜一下，比搜索引擎更快定位。
              </p>
              <div v-for="(e, i) in cache.errors" :key="i" class="rounded-control border border-ink-100 p-3">
                <div class="font-mono text-[13px] font-semibold text-rose-600">{{ e.error }}</div>
                <div class="text-[12px] text-ink-600">原因：{{ e.cause }}</div>
                <div class="text-[12px] text-emerald-600">解决：{{ e.fix }}</div>
              </div>
              <div v-if="!cache.errors?.length" class="rounded-control bg-ink-50 p-3 text-[13px] text-ink-400">
                报错清单还没加载：切到「概览」再切回来触发一次请求。
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 语言对比 -->
    <div v-else-if="topTab === 'compare'" class="card p-5">
      <p class="mb-3 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        还在纠结“学哪门、这俩什么区别”？先点选 2–3 门语言（最多 3 门，再点多的会提示），点「开始对比」
        生成一张表：维度列依次是名称、类型系统、诞生年份、设计者、范式、适用领域、入门难度、Hello World，
        每门语言一列；范式和领域这类数组内容会自动用顿号连开。
      </p>
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <span class="text-[13px] text-ink-600">选择 2-3 门：</span>
        <button v-for="l in langs" :key="l.key" class="tag cursor-pointer"
          :class="cmpKeys.includes(l.key) ? 'bg-brand-600 text-white' : ''" @click="toggleCmp(l.key)">{{ l.name }}</button>
        <button class="btn-primary ml-auto" @click="runCompare">开始对比</button>
      </div>
      <table v-if="cmp.rows.length" class="w-full border-collapse">
        <thead><tr class="border-b border-ink-100">
          <th class="th w-32">维度</th>
          <th v-for="k in cmp.keys" :key="k" class="th">{{ cmp.names[k] }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="(r, i) in cmp.rows" :key="i" class="border-b border-ink-50">
            <td class="td font-medium text-ink-500">{{ r.dimension }}</td>
            <td v-for="k in cmp.keys" :key="k" class="td">{{ fmt(r[k]) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!cmp.rows.length" class="rounded-control bg-ink-50 p-4 text-[13px] leading-6 text-ink-400">
        还没生成对比：在上面点选 2–3 门语言（当前已选 {{ cmpKeys.length }} 门），点「开始对比」后维度表出现在这里。
      </div>
    </div>

    <!-- 术语词典 -->
    <div v-else-if="topTab === 'glossary'" class="card p-5">
      <p class="mb-3 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        99 条跨语言概念（递归、指针、闭包、时间复杂度…）：上面输关键词点「搜索」，或点标签筛选——
        比如点「底层」只看内存相关术语，再点一次标签就取消。每张卡给英文术语和一句白话解释，
        例证语言（example_langs）后端补齐后会以小标签形式挂在卡片下方。
      </p>
      <div class="mb-3 flex gap-2">
        <input v-model="glossQ" class="input w-64" placeholder="搜索术语，如 递归、指针" @keyup.enter="loadGloss" />
        <button class="btn-primary" @click="loadGloss">搜索</button>
        <div class="flex flex-wrap gap-1">
          <button v-for="t in glossTags" :key="t" class="tag cursor-pointer" :class="glossTag === t ? 'bg-brand-600 text-white' : ''" @click="pickTag(t)">{{ t }}</button>
        </div>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <div v-for="(g, i) in gloss" :key="i" class="rounded-control border border-ink-100 p-3">
          <div class="text-[13px] font-semibold text-ink-800">{{ g.term }}</div>
          <div class="text-[12px] text-ink-500">{{ g.desc }}</div>
          <div v-if="g.example_langs && g.example_langs.length" class="mt-1.5 flex flex-wrap gap-1">
            <span class="tag bg-brand-50 text-brand-700">例证语言</span>
            <span v-for="el in g.example_langs" :key="el" class="tag">{{ el }}</span>
          </div>
        </div>
        <div v-if="!gloss.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          没搜到这个词：换个关键词（试试「递归」「指针」），或把当前标签点掉看全部 99 条。
        </div>
      </div>
    </div>

    <!-- F535 我的多语言进度雷达 -->
    <div v-else-if="topTab === 'radar'" class="space-y-3">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        把 10 门语言的学习进度画在一张雷达上：轴是语言、半径是完成百分比（来自你在「我的学习 · 学习进度」保存的记录），
        多边形越饱满学得越广。右侧给已开始门数、平均进度和每门语言的状态，点语言名可直接回广场打开它。
      </p>
      <div class="card p-5">
        <div v-if="progRadarData && progRadarData.langs" class="grid gap-4 md:grid-cols-5">
          <svg class="w-full md:col-span-3" viewBox="0 0 320 280" role="img" aria-label="多语言进度雷达">
            <polygon v-for="(g,i) in prRings" :key="'g'+i" :points="g.pts" fill="none" stroke="#e5e7eb" :stroke-width="g.v===100?1.3:1" />
            <line v-for="(s,i) in prSpokes" :key="'s'+i" :x1="s.x1" :y1="s.y1" :x2="s.x2" :y2="s.y2" stroke="#e5e7eb" stroke-width="1" />
            <polygon :points="prDataPts" fill="rgba(79,70,229,0.16)" stroke="#4f46e5" stroke-width="1.6" />
            <circle v-for="(d,i) in prDots" :key="'d'+i" :cx="d.x" :cy="d.y" r="2.7" :fill="d.done?'#059669':'#4f46e5'" />
            <text v-for="(l,i) in prLabels" :key="'l'+i" :x="l.x" :y="l.y" :text-anchor="l.anchor" fill="#6b7280" font-size="10">{{ l.nm }}</text>
          </svg>
          <div class="self-center space-y-2 md:col-span-2">
            <div class="flex gap-3">
              <div class="flex-1 rounded-control bg-ink-50 p-2 text-center"><div class="text-[18px] font-bold text-brand-700">{{ progRadarData.started_count ?? 0 }}</div><div class="text-[11px] text-ink-400">已开始(门)</div></div>
              <div class="flex-1 rounded-control bg-ink-50 p-2 text-center"><div class="text-[18px] font-bold text-brand-700">{{ Math.round(progRadarData.avg_percent ?? 0) }}%</div><div class="text-[11px] text-ink-400">平均进度</div></div>
            </div>
            <div class="max-h-52 space-y-1 overflow-auto pr-1">
              <div v-for="lg in progRadarData.langs" :key="lg.key" class="flex items-center gap-2 text-[12px]">
                <span class="text-[14px]">{{ lg.icon }}</span>
                <button class="text-left text-ink-700 hover:text-brand-600" @click="jumpLang(lg.key)">{{ lg.name }}</button>
                <span class="tag" :class="prStatus(lg.status).cls">{{ prStatus(lg.status).label }}</span>
                <span class="ml-auto text-ink-400">{{ Math.round(lg.percent) }}%</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="grid h-40 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          正在读取多语言进度…若一直空白，先到「我的学习 · 学习进度」保存几条语言进度，再回这里看雷达。
        </div>
      </div>
    </div>

    <!-- 范式/算法/结构 -->
    <div v-else class="space-y-4">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        三块不绑语言的基本功：六大编程范式（思想 + 代码）、23 个入门算法（难度 / 思路 / 要点）、
        18 种核心数据结构（优点 / 缺点 / 适用场景）。卡片现在可以点开——展开后会给出该条的复杂度分析
        和示例代码。
      </p>
      <div class="card p-5">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">六大编程范式</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="p in paradigms" :key="p.key" class="cursor-pointer rounded-control border p-3 transition-colors"
            :class="openCard === 'p:' + p.key ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100 hover:border-brand-200'"
            @click="toggleCard('p:' + p.key)">
            <div class="flex items-center gap-2">
              <span class="font-semibold text-ink-800">{{ p.name }}</span>
              <span class="ml-auto text-[11px] text-brand-600">{{ openCard === 'p:' + p.key ? '收起 ▲' : '展开 ▼' }}</span>
            </div>
            <div class="text-[12px] text-ink-500">{{ p.idea }}</div>
            <pre class="mt-1 rounded-control bg-ink-50 p-2 font-mono text-[11px] text-ink-700">{{ p.example }}</pre>
            <div v-if="openCard === 'p:' + p.key" class="mt-2 space-y-1 border-t border-ink-100 pt-2 text-[12px] leading-6">
              <div v-if="p.complexity"><span class="font-semibold text-ink-700">复杂度：</span><span class="text-ink-600">{{ p.complexity }}</span></div>
              <div v-if="p.sample"><span class="font-semibold text-ink-700">示例代码：</span>
                <pre class="mt-1 overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ p.sample }}</pre>
              </div>
              <div v-if="!p.complexity && !p.sample" class="text-ink-400">该范式的复杂度与补充示例正由后端逐条补齐，先看上面的思想与代码。</div>
            </div>
          </div>
        </div>
      </div>
      <div class="card p-5">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">23 个入门算法</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="a in algorithms" :key="a.key" class="cursor-pointer rounded-control border p-3 transition-colors"
            :class="openCard === 'a:' + a.key ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100 hover:border-brand-200'"
            @click="toggleCard('a:' + a.key)">
            <div class="flex items-center gap-2"><span class="font-semibold text-ink-800">{{ a.name }}</span><span class="tag-brand">{{ a.level }}</span>
              <span class="ml-auto text-[11px] text-brand-600">{{ openCard === 'a:' + a.key ? '收起 ▲' : '展开 ▼' }}</span></div>
            <div class="text-[12px] text-ink-500">{{ a.idea }}</div>
            <div class="mt-1 flex flex-wrap gap-1"><span v-for="p in a.points" :key="p" class="tag">{{ p }}</span></div>
            <div v-if="openCard === 'a:' + a.key" class="mt-2 space-y-1 border-t border-ink-100 pt-2 text-[12px] leading-6">
              <div v-if="a.complexity"><span class="font-semibold text-ink-700">复杂度：</span><span class="text-ink-600">{{ a.complexity }}</span></div>
              <div v-if="a.sample"><span class="font-semibold text-ink-700">示例代码：</span>
                <pre class="mt-1 overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ a.sample }}</pre>
              </div>
              <div v-if="!a.complexity && !a.sample" class="text-ink-400">该算法的复杂度分析与示例代码正由后端逐条补齐，先按上面的要点手写一遍。</div>
            </div>
          </div>
        </div>
      </div>
      <div class="card p-5">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">18 种核心数据结构</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="d in dataStructures" :key="d.key" class="cursor-pointer rounded-control border p-3 transition-colors"
            :class="openCard === 'd:' + d.key ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100 hover:border-brand-200'"
            @click="toggleCard('d:' + d.key)">
            <div class="flex items-center gap-2">
              <span class="font-semibold text-ink-800">{{ d.name }}</span>
              <span class="ml-auto text-[11px] text-brand-600">{{ openCard === 'd:' + d.key ? '收起 ▲' : '展开 ▼' }}</span>
            </div>
            <div class="text-[12px] text-emerald-600">优：{{ d.pros }}</div>
            <div class="text-[12px] text-rose-500">劣：{{ d.cons }}</div>
            <div class="text-[12px] text-ink-500">适用：{{ d.use }}</div>
            <div v-if="openCard === 'd:' + d.key" class="mt-2 space-y-1 border-t border-ink-100 pt-2 text-[12px] leading-6">
              <div v-if="d.complexity"><span class="font-semibold text-ink-700">复杂度：</span><span class="text-ink-600">{{ d.complexity }}</span></div>
              <div v-if="d.sample"><span class="font-semibold text-ink-700">示例代码：</span>
                <pre class="mt-1 overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ d.sample }}</pre>
              </div>
              <div v-if="!d.complexity && !d.sample" class="text-ink-400">该结构的复杂度与示例正由后端逐条补齐，先记上面的优缺点和适用场景。</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()
const topTabs = [
  { v: 'square', label: '语言广场' }, { v: 'compare', label: '横向对比' },
  { v: 'glossary', label: '术语词典' }, { v: 'algo', label: '范式/算法/结构' },
  { v: 'radar', label: '我的进度' },
]
const subTabs = [
  { v: 'overview', label: '概览' }, { v: 'roadmap', label: '学习路线' }, { v: 'cheatsheet', label: '语法速查' },
  { v: 'keywords', label: '关键字' }, { v: 'modules', label: '模块用法' }, { v: 'types', label: '数据类型' }, { v: 'lessons', label: '入门课程' },
  { v: 'snippets', label: '代码片段' }, { v: 'ide', label: '开发环境' }, { v: 'style', label: '编码规范' }, { v: 'errors', label: '常见报错' },
]
const topTab = ref('square')
const langs = ref([])
const cur = ref('')
const detail = ref({})
const subTab = ref('overview')
const cache = reactive({})
const lesson = ref(null)
const lessonIdx = ref(-1)
const selKeyword = ref('')
const keywordDetail = ref(null)
const selModule = ref(-1)
const moduleDetail = ref(null)
// 卡片通用展开态（'p:范式key' / 'a:算法key' / 'd:结构key' / 't:类型下标'）
const openCard = ref('')
function toggleCard(id) { openCard.value = openCard.value === id ? '' : id }

// 首页「去学」带 ?lang=key 跳进来：读 query 打开对应语言详情
const route = useRoute()
async function openFromQuery() {
  const k = route.query.lang
  if (k && langs.value.some((l) => l.key === k) && cur.value !== k) await openLang(k)
}

async function openLang(key) {
  cur.value = key
  subTab.value = 'overview'
  Object.keys(cache).forEach((k) => delete cache[k])
  selKeyword.value = ''
  keywordDetail.value = null
  selModule.value = -1
  moduleDetail.value = null
  detail.value = (await learnApi.langDetail(key))
  await loadSub('overview')
}
async function loadSub(v) {
  subTab.value = v
  lesson.value = null
  if (v === 'overview') return
  if (cache[v]) return
  const k = cur.value
  const map = {
    roadmap: () => learnApi.langRoadmap(k).then((r) => (cache.roadmap = r.roadmap)),
    cheatsheet: () => learnApi.langCheatsheet(k).then((r) => (cache.cheatsheet = r.cheatsheet)),
    keywords: () => learnApi.langKeywordsDetail(k).then((r) => (cache.keywords = r.keywords)),
    modules: () => learnApi.langModules(k).then((r) => (cache.modules = r.modules)),
    types: () => learnApi.langTypes(k).then((r) => (cache.types = r.types)),
    lessons: () => learnApi.langLessons(k).then((r) => (cache.lessons = r.list)),
    snippets: () => learnApi.langSnippets(k).then((r) => (cache.snippets = r.list)),
    ide: () => learnApi.langIde(k).then((r) => (cache.ide = r.ide)),
    style: () => learnApi.langStyle(k).then((r) => (cache.style = r.style)),
    errors: () => learnApi.langErrors(k).then((r) => (cache.errors = r.errors)),
  }
  await map[v]()
}
async function selectKeyword(k) {
  const word = k.word || k
  if (selKeyword.value === word) { selKeyword.value = ''; keywordDetail.value = null; return }
  selKeyword.value = word
  if (k.word && k.desc) {
    keywordDetail.value = k
  } else {
    keywordDetail.value = await learnApi.langKeywordDetail(cur.value, word)
  }
}
async function selectModule(idx) {
  if (selModule.value === idx) { selModule.value = -1; moduleDetail.value = null; return }
  selModule.value = idx
  moduleDetail.value = await learnApi.langModuleDetail(cur.value, idx)
}
async function openLesson(idx) {
  if (lessonIdx.value === idx) { lessonIdx.value = -1; lesson.value = null; return }
  lessonIdx.value = idx
  lesson.value = (await learnApi.langLesson(cur.value, idx))
}
async function bookmark() {
  await learnApi.addBookmark({ language: cur.value, title: `${detail.value.name} 学习卡`, code: detail.value.hello, note: '从语言广场收藏' })
  app.toastMsg('已加入我的学习-代码收藏', 'success')
}

// 对比
const cmpKeys = ref(['python', 'go'])
const cmp = ref({ keys: [], names: {}, rows: [] })
function toggleCmp(k) {
  const i = cmpKeys.value.indexOf(k)
  if (i >= 0) cmpKeys.value.splice(i, 1)
  else if (cmpKeys.value.length < 3) cmpKeys.value.push(k)
  else app.toastMsg('最多对比 3 门', 'warn')
}
async function runCompare() {
  if (cmpKeys.value.length < 2) return app.toastMsg('至少选 2 门', 'warn')
  cmp.value = (await learnApi.langCompare(cmpKeys.value))
}
const fmt = (v) => (Array.isArray(v) ? v.join('、') : v)

// 术语
const gloss = ref([])
const glossTags = ref([])
const glossQ = ref('')
const glossTag = ref('')
async function loadGloss() {
  gloss.value = (await learnApi.glossary({ q: glossQ.value, tag: glossTag.value })).list
}
async function pickTag(t) { glossTag.value = glossTag.value === t ? '' : t; await loadGloss() }

// 范式/算法/结构
const paradigms = ref([])
const algorithms = ref([])
const dataStructures = ref([])

// ===== F535 多语言进度雷达（手写 SVG）=====
const progRadarData = ref(null)
async function loadProgRadar() {
  try { progRadarData.value = await learnApi.progRadar() } catch { progRadarData.value = { langs: [] } }
}
function prStatus(s) {
  return ({
    learning: { label: '学习中', cls: 'bg-brand-50 text-brand-700' },
    finished: { label: '已完成', cls: 'bg-emerald-50 text-emerald-600' },
    not_started: { label: '未开始', cls: 'bg-ink-100 text-ink-400' },
  })[s] || { label: s, cls: 'tag' }
}
async function jumpLang(key) { topTab.value = 'square'; await openLang(key) }
const PR = { x: 160, y: 135, r: 92 }
const prAxes = computed(() => progRadarData.value?.langs
  ? progRadarData.value.langs.map((l) => ({ key: l.key, name: l.name, percent: Number(l.percent ?? 0), done: l.status === 'finished' }))
  : [])
const prPt = (deg, r) => { const a = deg * Math.PI / 180; return { x: PR.x + r * Math.cos(a), y: PR.y + r * Math.sin(a) } }
function prRing(scale) {
  const n = prAxes.value.length
  return prAxes.value.map((_, i) => {
    const p = prPt(-90 + i * 360 / n, PR.r * scale / 100)
    return p.x.toFixed(1) + ',' + p.y.toFixed(1)
  }).join(' ')
}
const prRings = computed(() => [25, 50, 75, 100].map((v) => ({ v, pts: prRing(v) })))
const prSpokes = computed(() => prAxes.value.map((_, i) => {
  const n = prAxes.value.length, p = prPt(-90 + i * 360 / n, PR.r)
  return { x1: PR.x, y1: PR.y, x2: p.x.toFixed(1), y2: p.y.toFixed(1) }
}))
const prDots = computed(() => prAxes.value.map((ax, i) => {
  const n = prAxes.value.length
  const p = prPt(-90 + i * 360 / n, PR.r * Math.min(100, Math.max(0, ax.percent)) / 100)
  return { x: p.x.toFixed(1), y: p.y.toFixed(1), done: ax.done }
}))
const prDataPts = computed(() => prDots.value.map((d) => d.x + ',' + d.y).join(' '))
const prLabels = computed(() => prAxes.value.map((ax, i) => {
  const n = prAxes.value.length, p = prPt(-90 + i * 360 / n, PR.r + 17)
  let anchor = 'middle'
  if (p.x > PR.x + 6) anchor = 'start'; else if (p.x < PR.x - 6) anchor = 'end'
  const nm = ax.name.length > 8 ? ax.name.slice(0, 8) + '…' : ax.name
  return { x: p.x.toFixed(1), y: (p.y + 3.5).toFixed(1), anchor, nm }
}))
watch(topTab, (v) => { if (v === 'radar' && !progRadarData.value) loadProgRadar() })

onMounted(async () => {
  langs.value = (await learnApi.langCatalog()).list
  // 首页推荐的「去学」带 ?lang=key：优先打开被推荐的那门语言，没带参数时默认 Python
  await openFromQuery()
  if (!cur.value) await openLang('python')
  const [p, a, ds, g] = await Promise.all([
    learnApi.paradigms(), learnApi.algorithms(), learnApi.dataStructures(), learnApi.glossary({})])
  paradigms.value = p.list
  algorithms.value = a.list
  dataStructures.value = ds.list
  gloss.value = g.list
  glossTags.value = g.tags
})

// 在本页再点一次「去学」（同一路由带不同 query）时也能跟着切换语言
watch(() => route.query.lang, (k) => { if (k && langs.value.some((l) => l.key === k) && cur.value !== k) openLang(k) })
</script>
