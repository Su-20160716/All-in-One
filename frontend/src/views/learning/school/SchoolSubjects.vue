<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">学科知识中心</h2>
        <p class="text-[12px] text-ink-400">小学 / 初中 / 高中：知识点树、公式手册（可代入计算）、英语语法、化学元素与方程式</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in tabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="tab = t.v">{{ t.label }}</button>
      </div>
    </div>

    <!-- 知识点树 -->
    <div v-if="tab === 'point'" class="grid grid-cols-12 gap-4">
      <p class="col-span-12 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第一间「知识点」：先选学段、再选学科，或直接在搜索框输「方程」回车。左侧是章节—知识点树（搜索时变成结果列表），
        点一枚标签，右侧给出编号、蓝底定义、核心要点、黑底公式、典型例题、学习方法和红色易错点；
        讲解 / 考法 / 易错三段后端补齐后会自动出现，最后可「标记为学习中」写进个人进度。
      </p>
      <div class="col-span-12 flex flex-wrap items-end gap-3">
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学段</span>
          <select v-model="stage" class="input w-32" @change="onStage"><option v-for="s in stages" :key="s.key" :value="s.key">{{ s.name }}</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学科</span>
          <select v-model="subject" class="input w-36" @change="loadTree"><option v-for="s in curSubjects" :key="s.key" :value="s.key">{{ s.name }}</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">搜索知识点</span>
          <input v-model="pointQ" class="input w-56" placeholder="如 方程" @keyup.enter="searchPoint" /></label>
        <button class="btn-primary" @click="searchPoint">搜索</button>
      </div>

      <div class="card col-span-7 max-h-[70vh] overflow-auto p-4">
        <div v-if="pointResults.length" class="space-y-1">
          <button v-for="p in pointResults" :key="p.id" class="block w-full rounded-control px-2 py-1.5 text-left text-[13px] hover:bg-ink-50" @click="openPoint(p.id)">{{ p.chapter }} / {{ p.name }}</button>
        </div>
        <template v-else>
          <div v-if="pointQ" class="mb-2 rounded-control bg-amber-50 px-3 py-1.5 text-[12px] leading-5 text-amber-700">
            没有匹配「{{ pointQ }}」的知识点——换个别名试试（如「方程」试试「方程组」），下面先显示章节树。
          </div>
          <div v-for="(c, ci) in chapters" :key="ci" class="mb-2">
            <div class="rounded-control bg-ink-50 px-3 py-1.5 text-[13px] font-semibold text-ink-700">{{ c.chapter }}</div>
            <div class="flex flex-wrap gap-1.5 p-2">
              <button v-for="(pt, pi) in c.points" :key="pi" class="tag-brand cursor-pointer" @click="openPoint(`${stage}.${subject}.${ci}.${pi}`)">{{ pt }}</button>
            </div>
          </div>
          <div v-if="!chapters.length" class="px-1 text-[13px] leading-6 text-ink-400">
            这个学段 / 学科还没有章节：换个学科（小学数学、初中物理都各有内容），或用上方搜索框直接找知识点。
          </div>
        </template>
      </div>
      <div class="card col-span-5 max-h-[70vh] overflow-auto p-4">
        <div v-if="!point" class="grid h-40 place-items-center px-4 text-center text-[13px] leading-6 text-ink-400">点左边任意知识点标签，这里展开定义、要点、例题和易错点</div>
        <div v-else>
          <div class="flex items-center gap-2">
            <h3 class="text-[15px] font-semibold text-ink-900">{{ point.name }}</h3>
            <span class="tag">{{ point.chapter }}</span>
          </div>
          <p class="mt-1 text-[11px] text-ink-400">编号 {{ point.id }}</p>

          <!-- 完整知识点详情 -->
          <div v-if="point.detail" class="mt-3 space-y-3">
            <div class="rounded-control bg-brand-50 p-3">
              <div class="text-[12px] font-semibold text-brand-700">定义</div>
              <div class="mt-1 text-[12px] leading-6 text-ink-700">{{ point.detail.definition }}</div>
            </div>

            <div v-if="point.detail.insight" class="rounded-control bg-white p-3 ring-1 ring-ink-100">
              <div class="text-[12px] font-semibold text-ink-700">讲解</div>
              <div class="mt-1 text-[12px] leading-6 text-ink-600">{{ point.detail.insight }}</div>
            </div>

            <div v-if="point.detail.key_points?.length">
              <div class="text-[12px] font-semibold text-ink-700">核心要点</div>
              <ul class="mt-1 ml-4 list-disc space-y-0.5">
                <li v-for="(kp, i) in point.detail.key_points" :key="i" class="text-[12px] leading-5 text-ink-600">{{ kp }}</li>
              </ul>
            </div>

            <div v-if="point.detail.formulas?.length">
              <div class="text-[12px] font-semibold text-ink-700">公式/方法</div>
              <div class="mt-1 space-y-1">
                <div v-for="(f, i) in point.detail.formulas" :key="i" class="rounded-control bg-ink-900 px-2 py-1 font-mono text-[11px] text-ink-100">{{ f }}</div>
              </div>
            </div>

            <div v-if="point.detail.examples?.length">
              <div class="text-[12px] font-semibold text-ink-700">典型例题</div>
              <div class="mt-1 space-y-1">
                <div v-for="(ex, i) in point.detail.examples" :key="i" class="rounded-control border border-ink-100 bg-ink-50 p-2 text-[11px] leading-5 text-ink-600">{{ ex }}</div>
              </div>
            </div>

            <div v-if="point.detail.methods">
              <div class="text-[12px] font-semibold text-ink-700">学习方法/解题技巧</div>
              <div class="mt-1 text-[12px] leading-6 text-ink-600">{{ point.detail.methods }}</div>
            </div>

            <div v-if="point.detail.exam_tip" class="rounded-control bg-amber-50 p-3">
              <div class="text-[12px] font-semibold text-amber-700">考法</div>
              <div class="mt-1 text-[12px] leading-6 text-amber-700">{{ point.detail.exam_tip }}</div>
            </div>

            <div v-if="point.detail.pitfall" class="rounded-control bg-rose-50 p-3">
              <div class="text-[12px] font-semibold text-rose-600">易错</div>
              <div class="mt-1 text-[12px] leading-6 text-rose-500">{{ point.detail.pitfall }}</div>
            </div>

            <div v-if="point.detail.common_mistakes?.length">
              <div class="text-[12px] font-semibold text-rose-600">常见易错点</div>
              <ul class="mt-1 ml-4 list-disc space-y-0.5">
                <li v-for="(cm, i) in point.detail.common_mistakes" :key="i" class="text-[12px] leading-5 text-rose-500">{{ cm }}</li>
              </ul>
            </div>
          </div>

          <div v-if="point.related_formulas?.length" class="mt-3">
            <div class="mb-1 text-[12px] font-semibold text-ink-600">相关公式</div>
            <div class="flex flex-wrap gap-1.5"><span v-for="f in point.related_formulas" :key="f" class="tag">{{ f }}</span></div>
          </div>
          <!-- F526 掌握度自评 -->
          <div class="mt-4 rounded-control border border-ink-100 p-3">
            <div class="mb-1 flex items-center justify-between text-[12px]">
              <span class="font-semibold text-ink-700">我对这个知识点的掌握度</span>
              <span class="text-ink-400">{{ ['', '入门', '初学', '基本掌握', '较熟练', '能教别人'][myStars] || '点星自评' }}</span>
            </div>
            <div class="flex gap-1 text-[20px] leading-none">
              <button v-for="n in 5" :key="n" @click="ratePoint(n)" :class="n <= myStars ? 'text-amber-400' : 'text-ink-200'">★</button>
            </div>
          </div>

          <!-- F539 关联知识点推荐 -->
          <div v-if="relatedPoints.length" class="mt-3">
            <div class="mb-1 text-[12px] font-semibold text-ink-700">学完这个，接着看（关联推荐）</div>
            <div class="flex flex-wrap gap-1.5">
              <button v-for="rp in relatedPoints" :key="rp.id" class="tag-brand cursor-pointer" @click="openPoint(rp.id)" :title="rp.chapter">{{ rp.name }}</button>
            </div>
          </div>

          <button class="btn-outline mt-4" @click="savePointProgress">标记为学习中</button>
        </div>
      </div>
    </div>

    <!-- 公式手册 -->
    <div v-else-if="tab === 'formula'" class="grid grid-cols-12 gap-4">
      <p class="col-span-12 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第二间「公式手册」：60 条公式按学段（小学 / 初中 / 高中）和学科（数学 / 物理 / 化学）过滤。
        左边点一条，右边黑底显示公式本身、用法说明，下面按公式里的变量自动生成带中文提示的输入框；
        填数值点「代入计算」，服务端用安全的 AST 求值（内置 π、e、g）算出结果——查得到，也算得出。
      </p>
      <div class="card col-span-5 max-h-[70vh] overflow-auto p-3">
        <div class="mb-2 flex gap-2">
          <select v-model="fStage" class="input w-28"><option value="">全部学段</option><option v-for="s in stages" :key="s.key" :value="s.key">{{ s.name }}</option></select>
          <select v-model="fSubject" class="input w-32"><option value="">全部学科</option><option value="math">数学</option><option value="physics">物理</option><option value="chemistry">化学</option></select>
        </div>
        <div v-if="!filteredFormulas.length" class="px-1 text-[13px] leading-6 text-ink-400">
          当前筛选没有公式：把学段 / 学科切回「全部」，60 条公式就都回来了。
        </div>
        <button v-for="f in filteredFormulas" :key="f.key" class="block w-full rounded-control px-3 py-2 text-left"
          :class="activeFormula?.key === f.key ? 'bg-brand-600 text-white' : 'hover:bg-ink-50'" @click="pickFormula(f)">
          <div class="text-[13px] font-medium">{{ f.name }}</div>
          <div class="font-mono text-[11px]" :class="activeFormula?.key === f.key ? 'text-white/80' : 'text-ink-400'">{{ f.formula }}</div>
        </button>
      </div>
      <div class="card col-span-7 p-5">
        <div v-if="!activeFormula" class="grid h-40 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          左边点一条公式（如勾股定理、欧姆定律），这里会给出黑底公式、按变量生成的输入框和「代入计算」按钮
        </div>
        <div v-else class="space-y-3">
          <div class="flex items-center gap-2">
            <h3 class="text-[16px] font-semibold text-ink-900">{{ activeFormula.name }}</h3>
            <button class="btn-outline px-2 py-0.5 text-[12px]" @click="favFormula">{{ favKeys.includes(activeFormula.key) ? '★ 已收藏' : '☆ 收藏' }}</button>
          </div>
          <div class="rounded-control bg-ink-900 p-3 text-center font-mono text-[15px] text-ink-100">{{ activeFormula.formula }}</div>
          <div v-if="usageObj" class="space-y-1 rounded-control bg-ink-50 p-3 text-[12px] leading-6 text-ink-600">
            <div v-if="usageObj.scenario"><span class="font-semibold text-ink-700">适用场景：</span>{{ usageObj.scenario }}</div>
            <div v-if="usageObj.pitfall" class="text-rose-500"><span class="font-semibold text-rose-600">易错：</span>{{ usageObj.pitfall }}</div>
            <div v-if="usageObj.example" class="font-mono text-[12px] text-brand-700"><span class="font-sans font-semibold">例子：</span>{{ usageObj.example }}</div>
          </div>
          <p v-else-if="formulaDetail.usage" class="text-[12px] leading-6 text-ink-500">{{ formulaDetail.usage }}</p>
          <div class="grid grid-cols-2 gap-3">
            <label v-for="pair in activeFormula.vars" :key="pair[0]" class="block">
              <span class="mb-1 block text-[12px] text-ink-500">{{ pair[1] }}（{{ pair[0] }}）</span>
              <input v-model.number="calcVals[pair[0]]" type="number" step="any" class="input" :placeholder="`输入 ${pair[1]}`" />
            </label>
          </div>
          <button class="btn-primary" @click="calc">代入计算</button>
          <div v-if="calcResult !== null" class="rounded-control bg-brand-50 p-3 text-[14px] font-semibold text-brand-700">计算结果：{{ calcResult }}</div>
        </div>
      </div>
    </div>

    <!-- 英语语法 -->
    <div v-else-if="tab === 'grammar'" class="grid grid-cols-12 gap-4">
      <p class="col-span-12 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第三间「英语语法」：28 个语法点按学段筛（小学到高中）。左边点标题，右边给一条蓝底规则讲解，
        下面逐条配等宽例句；后端补齐后还会出现「易错」和「相近语法辨析」两段——正好解决“规则会背、
        一做就混”的问题。
      </p>
      <div class="card col-span-4 max-h-[70vh] overflow-auto p-3">
        <select v-model="gStage" class="input mb-2"><option value="">全部学段</option><option v-for="s in stages" :key="s.key" :value="s.key">{{ s.name }}</option></select>
        <div v-if="!filteredGrammar.length" class="px-1 text-[13px] leading-6 text-ink-400">这个学段暂时没有语法点，把筛选切回「全部学段」。</div>
        <button v-for="g in filteredGrammar" :key="g.key" class="block w-full rounded-control px-3 py-2 text-left text-[13px]"
          :class="grammar?.key === g.key ? 'bg-brand-600 text-white' : 'hover:bg-ink-50'" @click="openGrammar(g.key)">{{ g.title }}</button>
      </div>
      <div class="card col-span-8 p-5">
        <div v-if="!grammar" class="grid h-40 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">在左边点一个语法点（如「一般现在时」），这里给出规则和例句</div>
        <div v-else>
          <h3 class="text-[16px] font-semibold text-ink-900">{{ grammar.title }}</h3>
          <p class="mt-3 rounded-control bg-brand-50 p-3 text-[13px] leading-7 text-brand-800">{{ grammar.rule }}</p>
          <div class="mt-3 space-y-1.5">
            <div v-for="(e, i) in grammar.examples" :key="i" class="rounded-control border border-ink-100 p-2 font-mono text-[13px] text-ink-700">{{ e }}</div>
          </div>
          <div v-if="grammar.pitfall" class="mt-3 rounded-control bg-rose-50 p-3">
            <div class="text-[12px] font-semibold text-rose-600">易错</div>
            <div class="mt-1 text-[13px] leading-6 text-rose-500">{{ grammar.pitfall }}</div>
          </div>
          <div v-if="grammar.contrast" class="mt-2 rounded-control bg-amber-50 p-3">
            <div class="text-[12px] font-semibold text-amber-700">相近语法辨析</div>
            <div class="mt-1 text-[13px] leading-6 text-amber-700">{{ grammar.contrast }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 化学 -->
    <div v-else class="space-y-4">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第四间「化学」：上半部分是元素周期表——按碱金属、卤素等类别筛选，一格格是序数、符号、中文名，
        点某格下方给出相对原子质量、类别与常温状态（存在 / 用途 / 特性补齐后会一起展示）；
        下半部分是化学方程式卡片，标着反应类型、学段和条件，点卡片可展开配平思路与考点。
      </p>
      <div class="card p-4">
        <div class="mb-3 flex flex-wrap items-center gap-2">
          <h3 class="text-[15px] font-semibold text-ink-800">常用元素（{{ elements.length }}）</h3>
          <button v-for="c in elemCats" :key="c" class="tag cursor-pointer" :class="elemCat === c ? 'bg-brand-600 text-white' : ''" @click="elemCat = elemCat === c ? '' : c">{{ c }}</button>
        </div>
        <div class="grid grid-cols-3 gap-2 md:grid-cols-6 lg:grid-cols-9">
          <button v-for="e in filteredElements" :key="e.number" class="rounded-control border p-2 text-center transition-colors hover:border-brand-400"
            :class="element?.number === e.number ? 'border-brand-500 bg-brand-50' : 'border-ink-100'" @click="openElement(e.number)">
            <div class="text-[10px] text-ink-400">{{ e.number }}</div>
            <div class="text-[18px] font-bold text-ink-800">{{ e.symbol }}</div>
            <div class="text-[11px] text-ink-500">{{ e.name }}</div>
          </button>
          <div v-if="!filteredElements.length" class="col-span-3 rounded-control bg-ink-50 p-3 text-center text-[13px] leading-6 text-ink-400 md:col-span-6 lg:col-span-9">
            这个类别下没有收录元素：再点一次类别标签取消筛选，118 个常用元素就都显示了。
          </div>
        </div>
        <div v-if="element" class="mt-3 rounded-control bg-ink-50 p-3 text-[13px] leading-6 text-ink-700">
          {{ element.number }} 号元素 {{ element.name }}（{{ element.symbol }}），相对原子质量 {{ element.mass }}，类别 {{ element.category }}，常温状态 {{ element.state }}
          <div v-if="element.story" class="mt-1.5 space-y-1 border-t border-ink-200 pt-1.5 text-[12px] text-ink-600">
            <div v-if="element.story.occurrence"><span class="font-semibold text-ink-700">存在：</span>{{ element.story.occurrence }}</div>
            <div v-if="element.story.uses"><span class="font-semibold text-ink-700">用途：</span>{{ element.story.uses }}</div>
            <div v-if="element.story.trait"><span class="font-semibold text-ink-700">特性：</span>{{ element.story.trait }}</div>
            <div v-if="!element.story.occurrence && !element.story.uses && !element.story.trait" class="text-ink-400">该元素的存在 / 用途 / 特性讲解待后端补充。</div>
          </div>
        </div>
      </div>

      <!-- F530 化学方程式配平练习 -->
      <div class="card p-4">
        <h3 class="mb-3 flex items-center gap-2 text-[15px] font-semibold text-ink-800">方程式配平练习
          <span class="tag-brand">{{ epRes ? '已判分' : '填系数' }}</span>
          <button class="btn-outline ml-auto px-2 py-0.5" @click="newEquation">下一题</button>
        </h3>
        <div v-if="ep.key">
          <div class="text-[12px] text-ink-400">{{ ep.type }}<span v-if="ep.condition"> · 条件：{{ ep.condition }}</span></div>
          <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-2 font-mono text-[14px] text-ink-800">
            <template v-for="(f, i) in ep.left_forms" :key="'l' + i">
              <input v-model.number="epLeft[i]" type="number" min="1" class="input h-8 w-14 px-1 text-center" />
              <span>{{ f }}</span><span v-if="i < ep.left_forms.length - 1"> + </span>
            </template>
            <span class="px-1">→</span>
            <template v-for="(f, i) in ep.right_forms" :key="'r' + i">
              <input v-model.number="epRight[i]" type="number" min="1" class="input h-8 w-14 px-1 text-center" />
              <span>{{ f }}</span><span v-if="i < ep.right_forms.length - 1"> + </span>
            </template>
          </div>
          <button class="btn-primary mt-3" @click="submitEquation">提交配平</button>
          <div v-if="epRes" class="mt-3 rounded-control p-3 text-[13px] leading-6" :class="epRes.correct ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600'">
            <div class="font-semibold">{{ epRes.correct ? '✓ 配平正确' : '✗ 配平不对' }}</div>
            <div class="mt-1 font-mono text-ink-700">{{ epRes.equation }}</div>
            <div v-if="!epRes.correct" class="mt-1 font-mono text-ink-500">正确系数：左 [{{ epRes.left_answer.join(', ') }}] · 右 [{{ epRes.right_answer.join(', ') }}]</div>
            <div v-if="epRes.balance_tip" class="mt-1 text-[12px] text-ink-500">配平思路：{{ epRes.balance_tip }}</div>
          </div>
        </div>
        <div v-else class="text-[13px] leading-6 text-ink-400">点「下一题」抽一条方程式，给每种物质填系数。</div>
      </div>

      <div class="card p-4">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">化学方程式（{{ equations.length }}）· 点卡片看配平思路与考点</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="eq in equations" :key="eq.key" class="cursor-pointer rounded-control border p-3 transition-colors"
            :class="openEq === eq.key ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100 hover:border-brand-200'"
            @click="toggleEq(eq.key)">
            <div class="flex items-center gap-2"><span class="tag-brand">{{ eq.type }}</span><span class="tag">{{ stageName(eq.stage) }}</span><span v-if="eq.condition" class="tag">条件：{{ eq.condition }}</span>
              <span class="ml-auto text-[11px] text-brand-600">{{ openEq === eq.key ? '收起 ▲' : '讲解 ▼' }}</span></div>
            <div class="mt-1.5 font-mono text-[14px] text-ink-900">{{ eq.equation }}</div>
            <div v-if="eq.phenomenon || eq.phenomenon_note" class="mt-1 text-[12px] text-ink-500">现象：{{ eq.phenomenon || eq.phenomenon_note }}</div>
            <div v-if="openEq === eq.key" class="mt-2 space-y-1 border-t border-ink-100 pt-2 text-[12px] leading-6">
              <div v-if="eq.balance_tip"><span class="font-semibold text-ink-700">配平思路：</span><span class="text-ink-600">{{ eq.balance_tip }}</span></div>
              <div v-if="!eq.phenomenon && eq.phenomenon_note" class="text-ink-500"><span class="font-semibold text-ink-700">现象：</span>{{ eq.phenomenon_note }}</div>
              <div v-if="eq.exam_tip" class="text-amber-700"><span class="font-semibold">考点：</span>{{ eq.exam_tip }}</div>
              <div v-if="!eq.balance_tip && !eq.exam_tip" class="text-ink-400">
                本条的配平思路与考点还在逐条补齐；先把上面的反应类型、条件和现象记牢（{{ stageName(eq.stage) }} 范围）。
              </div>
            </div>
          </div>
          <div v-if="!equations.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
            方程式还没加载出来：刷新页面重取，52 条方程式会按反应类型分列在这里。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()
const tabs = [
  { v: 'point', label: '知识点' }, { v: 'formula', label: '公式手册' },
  { v: 'grammar', label: '英语语法' }, { v: 'chem', label: '化学' },
]
const tab = ref('point')
const stages = ref([])
const stageName = (k) => stages.value.find((s) => s.key === k)?.name || k

// 知识点
const stage = ref('primary')
const subject = ref('math')
const chapters = ref([])
const point = ref(null)
const pointQ = ref('')
const pointResults = ref([])
const curSubjects = computed(() => stages.value.find((s) => s.key === stage.value)?.subjects || [])
function onStage() { subject.value = curSubjects.value[0]?.key; loadTree() }
async function loadTree() {
  pointResults.value = []
  chapters.value = (await learnApi.knowledgeTree({ stage: stage.value, subject: subject.value })).chapters
}
// F526 掌握度自评 + F539 关联推荐
const myStars = ref(0)
const relatedPoints = ref([])
async function openPoint(id) {
  point.value = await learnApi.knowledge(id)
  myStars.value = 0
  try { relatedPoints.value = (await learnApi.knowledgeRelated(id)).list } catch { relatedPoints.value = [] }
}
async function ratePoint(n) {
  myStars.value = n
  const sk = `${point.value.stage}.${point.value.subject}`
  await learnApi.saveMasteryRating({ stage_subject: sk, point: point.value.name, stars: n })
  app.toastMsg(`已按 ${n} 星记录掌握度`, 'success')
}
async function searchPoint() {
  if (!pointQ.value) { pointResults.value = []; return loadTree() }
  pointResults.value = (await learnApi.knowledgeSearch(pointQ.value)).list
}
async function savePointProgress() {
  await learnApi.saveProgress({ domain: 'school', target_key: point.value.id, target_name: point.value.name, percent: 20 })
  app.toastMsg('已记录学习进度', 'success')
}

// 公式
const formulas = ref([])
const fStage = ref('')
const fSubject = ref('')
const activeFormula = ref(null)
const formulaDetail = ref({})
const calcVals = ref({})
const calcResult = ref(null)
const filteredFormulas = computed(() => formulas.value.filter((f) =>
  (!fStage.value || f.stage === fStage.value) && (!fSubject.value || f.subject === fSubject.value)))
async function pickFormula(f) {
  activeFormula.value = f
  calcResult.value = null
  calcVals.value = {}
  formulaDetail.value = (await learnApi.formula(f.key))
}
// usage 兼容两种后端返回：纯字符串 / {scenario, pitfall, example} 对象
const usageObj = computed(() => {
  const u = formulaDetail.value?.usage
  return u && typeof u === 'object' && !Array.isArray(u) ? u : null
})
async function calc() {
  const data = await learnApi.formulaCalc(activeFormula.value.key, calcVals.value)
  calcResult.value = data.result
}
// F532 公式收藏夹
const favKeys = ref([])
async function loadFavKeys() { favKeys.value = (await learnApi.formulaFavorites()).keys }
async function favFormula() {
  const r = await learnApi.toggleFormulaFavorite(activeFormula.value.key)
  await loadFavKeys()
  app.toastMsg(r.favorited ? '已加入公式收藏夹' : '已取消收藏', r.favorited ? 'success' : 'warn')
}

// 语法
const grammarList = ref([])
const gStage = ref('')
const grammar = ref(null)
const filteredGrammar = computed(() => grammarList.value.filter((g) => !gStage.value || g.stage === gStage.value))
async function openGrammar(key) { grammar.value = (await learnApi.grammarDetail(key)) }

// 化学
const elements = ref([])
const element = ref(null)
const elemCats = ref([])
const elemCat = ref('')
const equations = ref([])
// 方程式卡片可点开（S5/F503）：配平思路 / 现象解读 / 考点，字段不存在时不渲染
const openEq = ref('')
function toggleEq(k) { openEq.value = openEq.value === k ? '' : k }
const filteredElements = computed(() => elements.value.filter((e) => !elemCat.value || e.category === elemCat.value))
async function openElement(n) { element.value = (await learnApi.element(n)) }
// F530 方程式配平练习
const ep = ref({})
const epLeft = ref([])
const epRight = ref([])
const epRes = ref(null)
async function newEquation() {
  epRes.value = null
  ep.value = await learnApi.equationPractice()
  epLeft.value = ep.value.left_forms.map(() => 1)
  epRight.value = ep.value.right_forms.map(() => 1)
}
async function submitEquation() {
  epRes.value = await learnApi.equationPracticeSubmit({
    key: ep.value.key,
    left: epLeft.value.map((x) => Number(x) || 0),
    right: epRight.value.map((x) => Number(x) || 0),
  })
}

onMounted(async () => {
  stages.value = (await learnApi.stages()).list
  await loadTree()
  formulas.value = (await learnApi.formulas()).list
  grammarList.value = (await learnApi.grammar()).list
  const [el, eq] = await Promise.all([learnApi.elements(), learnApi.equations()])
  elements.value = el.list
  elemCats.value = el.categories
  equations.value = eq.list
  await loadFavKeys()
  await newEquation()
})
</script>
