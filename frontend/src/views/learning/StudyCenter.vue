<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">我的学习</h2>
        <p class="text-[12px] text-ink-400">学习进度、代码收藏、专注打卡、学习计划与掌握度，全部云端保存</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in tabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="switchTab(t.v)">{{ t.label }}</button>
      </div>
    </div>

    <!-- 学习概览（#83 #84 #85） -->
    <template v-if="tab === 'overview'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        一眼看清“最近学了没”：上面三张数字卡分别是今日 / 本周 / 本月累计分钟（数据来自「专注记录」的打卡）；
        中间 14 天柱状图按最大值归一，鼠标停在柱上看当天分钟；下面月历可前后翻，有记录的日子整块填深色——
        空白格多说明该去打卡了。
      </p>
      <div class="grid grid-cols-3 gap-3">
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ todayMin }}</div><div class="text-[12px] text-ink-400">今日(分钟)</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ weekMin }}</div><div class="text-[12px] text-ink-400">本周(分钟)</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ monthMin }}</div><div class="text-[12px] text-ink-400">本月(分钟)</div></div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">近 14 天趋势</h3>
        <div class="flex items-end gap-1" style="height: 80px">
          <div v-for="(d, i) in trend14" :key="i" class="flex-1 rounded-t bg-brand-400" :style="{ height: Math.max(4, d.minutes / (maxTrend || 1) * 76) + 'px' }" :title="d.date + ' ' + d.minutes + '分钟'"></div>
        </div>
        <div class="mt-1 flex justify-between text-[10px] text-ink-400"><span>14天前</span><span>今天</span></div>
      </div>

      <!-- F541 弱项雷达：按学科/题型的订正率，右侧给补弱顺序 -->
      <div class="card p-4">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-[14px] font-semibold text-ink-800">弱项雷达（错题订正率）</h3>
          <div class="flex gap-1 text-[11px]">
            <button class="rounded px-2 py-0.5" :class="weakMode==='subject'?'bg-brand-600 text-white':'bg-ink-100 text-ink-500'" @click="weakMode='subject'">按学科</button>
            <button class="rounded px-2 py-0.5" :class="weakMode==='type'?'bg-brand-600 text-white':'bg-ink-100 text-ink-500'" @click="weakMode='type'">按题型</button>
          </div>
        </div>
        <div v-if="weakOrder.length" class="grid gap-3" :class="weakAxes.length>=3?'md:grid-cols-5':''">
          <svg v-if="weakAxes.length>=3" class="w-full md:col-span-3" viewBox="0 0 300 250" role="img" aria-label="弱项雷达图">
            <polygon v-for="(g,i) in weakRings" :key="'g'+i" :points="g.pts" fill="none" stroke="#e5e7eb" :stroke-width="g.v===100?1.3:1" />
            <line v-for="(s,i) in weakSpokes" :key="'s'+i" :x1="s.x1" :y1="s.y1" :x2="s.x2" :y2="s.y2" stroke="#e5e7eb" stroke-width="1" />
            <polygon :points="weakDataPts" fill="rgba(79,70,229,0.16)" stroke="#4f46e5" stroke-width="1.6" />
            <circle v-for="(d,i) in weakDots" :key="'d'+i" :cx="d.x" :cy="d.y" r="2.7" :fill="d.weak?'#dc2626':'#4f46e5'" />
            <text v-for="(l,i) in weakLabels" :key="'l'+i" :x="l.x" :y="l.y" :text-anchor="l.anchor" :fill="l.weak?'#dc2626':'#6b7280'" font-size="10">{{ l.nm }} {{ l.rate }}%</text>
          </svg>
          <div class="self-center space-y-1.5" :class="weakAxes.length>=3?'md:col-span-2':''">
            <div class="text-[12px] font-medium text-ink-600">优先补弱顺序</div>
            <div v-for="(o,i) in weakOrder" :key="i" class="flex items-center gap-2 text-[12px]">
              <span class="w-4 text-ink-400">{{ i+1 }}</span>
              <span :class="o.weak?'font-medium text-red-600':'text-ink-600'">{{ o.name }}</span>
              <span class="ml-auto text-ink-400">{{ Math.round(o.fixed_rate) }}%</span>
            </div>
            <p class="pt-1 text-[11px] leading-5 text-ink-400">红色＝订正率低于 60%，越靠前越该先补；订正率会随错题本「订正掌握」与错题重练上升。</p>
            <p v-if="weakAxes.length<3" class="text-[11px] leading-5 text-ink-400">当前涉及的学科/题型还少，再多积累一些错题，这里会展开完整雷达。</p>
          </div>
        </div>
        <div v-else class="grid h-28 place-items-center px-6 text-center text-[12px] leading-6 text-ink-400">
          还没有足够错题：去「题库」智能组卷交卷或「刷题训练」，把做错的题留下来，这里会按学科、题型算出订正率并画成雷达。
        </div>
      </div>

      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">学习日历（{{ calYear }}年{{ calMonth + 1 }}月）</h3>
        <div class="mb-1 flex justify-between text-[12px]">
          <button class="btn-outline px-2" @click="shiftMonth(-1)">‹ 上月</button>
          <button class="btn-outline px-2" @click="shiftMonth(1)">下月 ›</button>
        </div>
        <div class="grid grid-cols-7 gap-1 text-center text-[11px] text-ink-400">
          <span v-for="w in ['一','二','三','四','五','六','日']" :key="w">{{ w }}</span>
        </div>
        <div class="mt-1 grid grid-cols-7 gap-1">
          <div v-for="(cell, i) in calendarCells" :key="i"
               class="aspect-square rounded text-[11px] leading-6"
               :class="cell.day ? (cell.minutes ? 'bg-brand-500 text-white' : 'bg-ink-50 text-ink-400') : ''"
               :title="cell.day ? cell.day + '：' + (cell.minutes ? cell.minutes + '分钟' : '无记录') : ''">
            {{ cell.day || '' }}
          </div>
        </div>
      </div>
    </template>

    <!-- 学习进度 + 掌握度 -->
    <template v-else-if="tab === 'progress'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        左边是 upsert 表单：领域选编程/学科/工具，目标标识填 python、junior.math 这类 key，同一组 key 重复保存只会更新不会新建；
        拖滑块定百分比、选状态、写备注。下面按学科算「错题掌握度」。右边列表每条都能点开——看名称、目标、备注、
        更新时间和该进度的变更历史。
      </p>
      <div class="grid grid-cols-12 gap-4">
        <div class="card col-span-12 p-4 lg:col-span-5">
          <h3 class="mb-3 text-[14px] font-semibold text-ink-800">记录 / 更新进度</h3>
          <div class="space-y-2">
            <select v-model="pf.domain" class="input"><option value="programming">编程</option><option value="school">学科</option><option value="tool">工具</option></select>
            <input v-model="pf.target_key" class="input" placeholder="目标标识，如 python 或 junior.math" />
            <input v-model="pf.target_name" class="input" placeholder="目标名称，如 Python / 初中数学" />
            <div class="flex items-center gap-2"><input v-model.number="pf.percent" type="range" min="0" max="100" class="flex-1" /><span class="w-12 text-[13px] text-brand-700">{{ pf.percent }}%</span></div>
            <select v-model="pf.status" class="input"><option value="learning">学习中</option><option value="finished">已完成</option></select>
            <input v-model="pf.note" class="input" placeholder="备注（可选）" />
            <button class="btn-primary w-full" @click="saveProgress">保存进度</button>
          </div>
          <div v-if="mastery.by_subject" class="mt-4">
            <h3 class="mb-2 text-[14px] font-semibold text-ink-800">错题掌握度</h3>
            <div v-for="(v, k) in mastery.by_subject" :key="k" class="mb-1.5">
              <div class="flex justify-between text-[12px] text-ink-500"><span>{{ k }}</span><span>{{ v.mastered }}/{{ v.total }}（{{ v.mastery }}%）</span></div>
              <div class="h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: v.mastery + '%' }"></div></div>
            </div>
          </div>
          <div v-else class="mt-4 rounded-control bg-ink-50 p-3 text-[12px] leading-6 text-ink-400">
            还没有错题掌握度：去「题库与组卷」或「编程刷题训练」把做错的题收进错题本，这里会按学科算出订正率。
          </div>
        </div>
        <div class="card col-span-12 p-4 lg:col-span-7">
          <h3 class="mb-3 text-[14px] font-semibold text-ink-800">进度列表（{{ progress.length }}）· 点一条看详情</h3>
          <div v-for="p in progress" :key="p.id" class="mb-2 rounded-control border p-3 transition-colors"
            :class="openP === p.id ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100'">
            <button class="flex w-full items-center gap-2 text-left" @click="toggleP(p.id)">
              <span class="tag-brand">{{ domainName(p.domain) }}</span><span class="text-[13px] font-medium text-ink-800">{{ p.target_name || p.target_key }}</span>
              <span v-if="p.status === 'finished'" class="tag bg-emerald-50 text-emerald-600">已完成</span>
              <span class="ml-auto text-[12px] text-brand-600">{{ openP === p.id ? '收起 ▲' : '详情 ▼' }}</span>
            </button>
            <div class="mt-1.5 h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: p.percent + '%' }"></div></div>
            <div class="mt-1 text-[11px] text-ink-400">{{ p.percent }}% · 更新于 {{ fmt(p.updated_at) }}</div>

            <div v-if="openP === p.id" class="mt-2 space-y-2 border-t border-ink-100 pt-2">
              <div class="grid grid-cols-1 gap-x-4 gap-y-1 text-[12px] text-ink-600 md:grid-cols-2">
                <div><span class="text-ink-400">名称：</span>{{ p.target_name || '（未填写目标名称）' }}</div>
                <div><span class="text-ink-400">目标标识：</span><code class="rounded bg-ink-100 px-1 font-mono text-[11px]">{{ p.target_key }}</code></div>
                <div><span class="text-ink-400">领域：</span>{{ domainName(p.domain) }}</div>
                <div><span class="text-ink-400">状态：</span>{{ p.status === 'finished' ? '已完成' : '学习中' }}</div>
                <div><span class="text-ink-400">备注：</span>{{ p.note || '（无备注）' }}</div>
                <div><span class="text-ink-400">更新时间：</span>{{ fmt(p.updated_at) }}　<span class="text-ink-400">创建于 {{ fmt(p.created_at) }}</span></div>
              </div>
              <div class="rounded-control bg-white p-2 text-[12px] leading-6 text-ink-500 ring-1 ring-ink-100">
                <span class="font-semibold text-ink-600">相关说明：</span>{{ progressHint(p) }}
              </div>
              <div>
                <div class="mb-1 text-[12px] font-semibold text-ink-600">变更历史</div>
                <div v-if="histOf(p).length" class="space-y-0.5">
                  <div v-for="(h, hi) in histOf(p)" :key="hi" class="text-[11px] leading-5 text-ink-500">
                    {{ h.at }}：进度更新到 {{ h.percent }}%<span v-if="h.note">（{{ h.note }}）</span>
                  </div>
                </div>
                <div v-else class="rounded-control bg-ink-50 p-2 text-[11px] leading-5 text-ink-400">
                  暂无历史：本次会话里点一次「保存进度」就会在这里记下一条；后端若返回 history 字段也会一并展示。
                </div>
              </div>
            </div>
          </div>
          <div v-if="!progress.length" class="grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
            还没有任何进度：在左侧选领域、填目标标识（如 python）、拖一下滑块点「保存进度」，这里就会长出第一根进度条。
          </div>
        </div>
      </div>
    </template>

    <!-- 代码收藏 -->
    <template v-else-if="tab === 'bookmark'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        自己的代码剪贴板：上面一行填语言 key（python / go…）、标题和代码点「收藏」即可新增；
        下面两列黑底展示，编程广场右上角「收藏片段/语言」进来的学习卡也汇到这里。用不上的直接删，云端保存换设备不丢。
      </p>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="bf.language" class="input col-span-2" placeholder="语言 key，如 python" />
          <input v-model="bf.title" class="input col-span-3" placeholder="标题" />
          <input v-model="bf.code" class="input col-span-6" placeholder="代码 / 命令" />
          <button class="btn-primary col-span-1" @click="addBookmark">收藏</button>
        </div>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <div v-for="b in bookmarks" :key="b.id" class="card p-3">
          <div class="flex items-center gap-2"><span class="tag-brand">{{ b.language }}</span><span class="text-[13px] font-semibold text-ink-800">{{ b.title }}</span>
            <button class="btn-danger ml-auto" @click="delBookmark(b.id)">删除</button></div>
          <pre class="mt-1.5 overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ b.code }}</pre>
          <div v-if="b.note" class="mt-1 text-[12px] text-ink-400">{{ b.note }}</div>
        </div>
        <div v-if="!bookmarks.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          收藏夹还是空的：去「编程语言广场」选一门语言点「收藏片段/语言」，或直接在上面贴一段常用命令。
        </div>
      </div>
    </template>

    <!-- 专注记录 -->
    <template v-else-if="tab === 'session'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        打卡式记录：学完一次就填科目、分钟、日期点「打卡」（番茄钟建议一次 25 分钟）。上面三张卡统计累计分钟、
        次数和小时，中间按科目汇总出“哪科花得最多”，下面逐条列出可删除——「学习概览」的柱状图与月历读的就是这些数据。
      </p>
      <div class="grid grid-cols-3 gap-3">
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ sessSummary.total_minutes || 0 }}</div><div class="text-[12px] text-ink-400">累计分钟</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ sessSummary.count || 0 }}</div><div class="text-[12px] text-ink-400">专注次数</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ Math.round((sessSummary.total_minutes || 0) / 60 * 10) / 10 }}</div><div class="text-[12px] text-ink-400">累计小时</div></div>
      </div>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="sf.subject" class="input col-span-3" placeholder="科目/主题，如 数学" />
          <input v-model.number="sf.minutes" type="number" class="input col-span-2" placeholder="分钟" />
          <input v-model="sf.study_date" type="date" class="input col-span-3" />
          <button class="btn-primary col-span-2" @click="addSession">打卡</button>
          <div class="col-span-2 text-[12px] leading-8 text-ink-400">番茄钟建议 25 分钟</div>
        </div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">按科目统计</h3>
        <div class="flex flex-wrap gap-2"><span v-for="(m, k) in sessSummary.by_subject" :key="k" class="tag-brand">{{ k }}：{{ m }} 分钟</span></div>
        <div v-if="!Object.keys(sessSummary.by_subject || {}).length" class="text-[13px] leading-6 text-ink-400">
          还没有按科目汇总：在上面填「数学 · 25 分钟」打卡一次，这里就会出现「数学：25 分钟」的标签。
        </div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">打卡记录</h3>
        <div v-for="s in sessions" :key="s.id" class="flex items-center gap-3 border-b border-ink-50 py-1.5 text-[13px]">
          <span class="tag-brand">{{ s.subject }}</span><span>{{ s.minutes }} 分钟</span><span class="text-ink-400">{{ s.study_date }}</span>
          <button class="btn-danger ml-auto" @click="delSession(s.id)">删除</button>
        </div>
        <div v-if="!sessions.length" class="text-[13px] leading-6 text-ink-400">
          今天还没打卡：填科目和分钟点「打卡」，学习日历和 14 天趋势立刻亮起来。
        </div>
      </div>
    </template>

    <!-- 学习计划 -->
    <template v-else>
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        把大目标拆到每一天：填计划名称（如「30 天背单词」）、科目、总任务量、天数和开始日期点「生成计划」，
        系统按天排出任务（默认每 4 天休一天）。卡片上进度条用 − / ＋ 手动推进完成量，点「查看每日安排」
        展开逐日清单，不需要的计划直接删。
      </p>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="plf.title" class="input col-span-3" placeholder="计划名称，如 30 天背单词" />
          <input v-model="plf.subject" class="input col-span-2" placeholder="科目" />
          <input v-model.number="plf.total" type="number" class="input col-span-2" placeholder="总任务量" />
          <input v-model.number="plf.days" type="number" class="input col-span-1" placeholder="天数" />
          <input v-model="plf.start_date" type="date" class="input col-span-2" />
          <button class="btn-primary col-span-2" @click="addPlan">生成计划</button>
        </div>
      </div>
      <div class="grid gap-3 md:grid-cols-2">
        <div v-for="p in plans" :key="p.id" class="card p-4">
          <div class="flex items-center gap-2"><span class="text-[14px] font-semibold text-ink-800">{{ p.title }}</span><span class="tag">{{ p.subject }}</span>
            <button class="btn-danger ml-auto" @click="delPlan(p.id)">删除</button></div>
          <div class="mt-2 h-2 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: (p.total ? p.finished / p.total * 100 : 0) + '%' }"></div></div>
          <div class="mt-1 flex items-center gap-2 text-[12px] text-ink-500">
            <span>已完成 {{ p.finished }}/{{ p.total }}，{{ p.days }} 天</span>
            <button class="btn-outline px-2 py-0.5" @click="bumpPlan(p, -1)">-</button>
            <button class="btn-outline px-2 py-0.5" @click="bumpPlan(p, 1)">+</button>
          </div>
          <details class="mt-2"><summary class="cursor-pointer text-[12px] text-brand-600">查看每日安排</summary>
            <ol class="mt-1 ml-4 list-decimal text-[12px] text-ink-500"><li v-for="(d, i) in p.plan" :key="i">{{ d }}</li></ol>
          </details>
        </div>
        <div v-if="!plans.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          还没有计划：在上面填「100 道题 · 7 天」这类数字点「生成计划」，马上得到一张带每日任务的进度卡。
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const tabs = [
  { v: 'overview', label: '学习概览' },
  { v: 'progress', label: '学习进度' }, { v: 'bookmark', label: '代码收藏' },
  { v: 'session', label: '专注记录' }, { v: 'plan', label: '学习计划' },
]
const tab = ref('overview')
const today = new Date().toISOString().slice(0, 10)
const domainName = (d) => ({ programming: '编程', school: '学科', tool: '工具' })[d] || d
const fmt = (t) => (t || '').replace('T', ' ').slice(0, 16)

const progress = ref([])
const mastery = ref({})
const pf = reactive({ domain: 'programming', target_key: '', target_name: '', percent: 0, status: 'learning', note: '' })
// F544：进度条目可点开 —— 展开区展示名称/目标/备注/更新时间/相关说明与变更历史
const openP = ref(null)
const histMap = ref({})
function toggleP(id) { openP.value = openP.value === id ? null : id }
function histOf(p) {
  const api = Array.isArray(p.history)
    ? p.history.map((h) => ({ at: fmt(h.updated_at || h.created_at || h.at || ''), percent: h.percent, note: h.note || h.message || '' }))
    : []
  const local = histMap.value[`${p.domain}:${p.target_key}`] || []
  return [...api, ...local]
}
function progressHint(p) {
  if (p.status === 'finished') {
    return `已标记「已完成」：${p.target_name || p.target_key} 停在 ${p.percent}%。若又练了新内容，可在左侧用同一目标标识再保存一次，历史会继续往下记。`
  }
  if (!p.percent) {
    return `这条刚建立、进度还是 0%：到左侧把领域和目标标识填成同一组，拖动滑块到 20%~30% 再保存，就能看到第一段推进。`
  }
  return `还差 ${100 - p.percent}% 达成目标：${domainName(p.domain)}领域的「${p.target_name || p.target_key}」按 upsert 更新——同一目标标识重复保存只覆盖百分比与备注，不会产生第二条；下方「错题掌握度」会随你订正错题同步上升。`
}
async function loadProgress() {
  progress.value = (await learnApi.progress()).list
  mastery.value = (await learnApi.mastery())
}
async function saveProgress() {
  if (!pf.target_key) return app.toastMsg('请填写目标标识', 'warn')
  const saved = await learnApi.saveProgress({ ...pf })
  const key = `${pf.domain}:${pf.target_key}`
  const list = histMap.value[key] || (histMap.value[key] = [])
  list.unshift({ at: fmt(saved?.updated_at) || fmt(new Date().toISOString()), percent: saved?.percent ?? pf.percent, note: pf.note || '保存进度' })
  app.toastMsg('进度已保存', 'success')
  await loadProgress()
}

const bookmarks = ref([])
const bf = reactive({ language: 'python', title: '', code: '' })
async function loadBookmarks() { bookmarks.value = (await learnApi.bookmarks()).list }
async function addBookmark() {
  if (!bf.title) return app.toastMsg('请填写标题', 'warn')
  await learnApi.addBookmark({ ...bf }); bf.title = ''; bf.code = ''
  await loadBookmarks()
}
async function delBookmark(id) { await learnApi.delBookmark(id); await loadBookmarks() }

const sessions = ref([])
const sessSummary = ref({})
const sf = reactive({ subject: '数学', minutes: 25, study_date: today })
async function loadSessions() { const data = await learnApi.sessions(); sessions.value = data.list; sessSummary.value = data }
async function addSession() { await learnApi.addSession({ ...sf }); await loadSessions() }
async function delSession(id) { await learnApi.delSession(id); await loadSessions() }

const plans = ref([])
const plf = reactive({ title: '', subject: '', total: 100, days: 7, start_date: today })
async function loadPlans() { plans.value = (await learnApi.plans()).list }
async function addPlan() {
  if (!plf.title) return app.toastMsg('请填写计划名称', 'warn')
  await learnApi.addPlan({ ...plf })
  plf.title = ''
  await loadPlans()
}
async function bumpPlan(p, delta) { await learnApi.updatePlan({ id: p.id, finished: Math.max(0, p.finished + delta) }); await loadPlans() }
async function delPlan(id) { await learnApi.delPlan(id); await loadPlans() }

// ===== F541 弱项雷达（手写 SVG，不引 ECharts）=====
const weakness = ref({})
const weakMode = ref('subject')
async function loadWeakness() {
  try { weakness.value = await learnApi.weaknessRadar() } catch { weakness.value = {} }
}
const SUBJECT_CN = {
  chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学',
  biology: '生物', history: '历史', geography: '地理', politics: '道德与法治', science: '科学', society: '社会',
}
const WK = { x: 150, y: 118, r: 84 }
const wkPt = (deg, r) => { const a = deg * Math.PI / 180; return { x: WK.x + r * Math.cos(a), y: WK.y + r * Math.sin(a) } }
const weakAxes = computed(() => {
  const isSubj = weakMode.value === 'subject'
  const src = isSubj ? weakness.value.by_subject : weakness.value.by_type
  return (src || []).map((it) => {
    const raw = it.name ?? it.label ?? ''
    return { name: isSubj ? (SUBJECT_CN[raw] ?? raw) : raw, rate: Number(it.fixed_rate ?? 0), weak: !!it.weak }
  }).slice().sort((a, b) => a.rate - b.rate).slice(0, 8)
})
// 后端 order 是学科名字符串数组（如 ["chinese"]），映射到 by_subject 取订正率并翻译成中文名
const weakOrder = computed(() => {
  const subj = weakness.value.by_subject || []
  return (weakness.value.order || []).map((o) => {
    const raw = typeof o === 'string' ? o : (o.name ?? '')
    const hit = subj.find((s) => s.name === raw)
    const rate = hit ? Number(hit.fixed_rate ?? 0) : (typeof o === 'object' ? Number(o.fixed_rate ?? 0) : 0)
    const weak = hit ? !!hit.weak : (typeof o === 'object' ? !!o.weak : true)
    return { name: SUBJECT_CN[raw] ?? raw, fixed_rate: rate, weak }
  })
})
function wkRing(scale) {
  const n = weakAxes.value.length
  return weakAxes.value.map((_, i) => {
    const p = wkPt(-90 + i * 360 / n, WK.r * scale / 100)
    return p.x.toFixed(1) + ',' + p.y.toFixed(1)
  }).join(' ')
}
const weakRings = computed(() => [25, 50, 75, 100].map(v => ({ v, pts: wkRing(v) })))
const weakSpokes = computed(() => weakAxes.value.map((_, i) => {
  const n = weakAxes.value.length, p = wkPt(-90 + i * 360 / n, WK.r)
  return { x1: WK.x, y1: WK.y, x2: p.x.toFixed(1), y2: p.y.toFixed(1) }
}))
const weakDots = computed(() => weakAxes.value.map((ax, i) => {
  const n = weakAxes.value.length
  const p = wkPt(-90 + i * 360 / n, WK.r * Math.min(100, Math.max(0, ax.rate)) / 100)
  return { x: p.x.toFixed(1), y: p.y.toFixed(1), weak: ax.weak }
}))
const weakDataPts = computed(() => weakDots.value.map(d => d.x + ',' + d.y).join(' '))
const weakLabels = computed(() => weakAxes.value.map((ax, i) => {
  const n = weakAxes.value.length, p = wkPt(-90 + i * 360 / n, WK.r + 16)
  let anchor = 'middle'
  if (p.x > WK.x + 6) anchor = 'start'; else if (p.x < WK.x - 6) anchor = 'end'
  const nm = ax.name.length > 6 ? ax.name.slice(0, 6) + '…' : ax.name
  return { x: p.x.toFixed(1), y: (p.y + 3.5).toFixed(1), anchor, nm, rate: Math.round(ax.rate), weak: ax.weak }
}))

// ===== 学习概览（#83 #84 #85）=====
const todayMin = ref(0), weekMin = ref(0), monthMin = ref(0)
const trend14 = ref([]), maxTrend = ref(1)
const calYear = ref(new Date().getFullYear()), calMonth = ref(new Date().getMonth())
const dayMap = ref({})
const calendarCells = computed(() => {
  const y = calYear.value, m = calMonth.value
  const first = new Date(y, m, 1)
  let startWeekday = (first.getDay() + 6) % 7 // 周一为 0
  const daysInMonth = new Date(y, m + 1, 0).getDate()
  const cells = []
  for (let i = 0; i < startWeekday; i++) cells.push({ day: '', minutes: 0 })
  for (let d = 1; d <= daysInMonth; d++) {
    const iso = `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, minutes: dayMap.value[iso] || 0 })
  }
  return cells
})
function shiftMonth(d) {
  let m = calMonth.value + d, y = calYear.value
  if (m < 0) { m = 11; y-- }
  if (m > 11) { m = 0; y++ }
  calMonth.value = m; calYear.value = y
}
async function loadOverview() {
  const data = await learnApi.sessions()
  const list = data.list || []
  dayMap.value = {}
  list.forEach(s => { dayMap.value[s.study_date] = (dayMap.value[s.study_date] || 0) + (s.minutes || 0) })
  const now = new Date()
  const iso = (dt) => dt.toISOString().slice(0, 10)
  const t = iso(now)
  todayMin.value = dayMap.value[t] || 0
  const wk = dayMap.value[t] || 0
  weekMin.value = 0; monthMin.value = 0
  trend14.value = []
  for (let i = 13; i >= 0; i--) {
    const d = new Date(now - i * 86400000)
    const key = iso(d)
    const min = dayMap.value[key] || 0
    trend14.value.push({ date: key, minutes: min })
    if (i < 7) weekMin.value += min
    if (d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) monthMin.value += min
  }
  maxTrend.value = Math.max(...trend14.value.map(x => x.minutes), 1)
}

async function switchTab(v) {
  tab.value = v
  if (v === 'overview') { await loadOverview(); await loadWeakness() }
  if (v === 'progress') await loadProgress()
  if (v === 'bookmark') await loadBookmarks()
  if (v === 'session') await loadSessions()
  if (v === 'plan') await loadPlans()
}

onMounted(() => { loadOverview(); loadWeakness() })
</script>
