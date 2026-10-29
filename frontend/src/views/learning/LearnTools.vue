<template>
  <div class="mx-auto max-w-6xl">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">学习工具箱</h2>
        <p class="text-[12px] text-ink-400">共 {{ total }} 个服务端计算工具，覆盖数理计算、英语、化学、学习方法</p>
      </div>
      <input v-model="kw" class="input w-56" placeholder="搜索工具…" />
    </div>

    <div v-if="recentTools.length" class="mb-3 flex flex-wrap items-center gap-2 rounded-control border border-ink-100 bg-white px-3 py-2">
      <span class="text-[12px] font-medium text-ink-600">最近用过：</span>
      <button v-for="r in recentTools" :key="r.key" class="tag-brand cursor-pointer" @click="reopenTool(r.key)" :title="r.used_at">{{ r.name }}</button>
    </div>

    <p class="mb-4 rounded-control border border-ink-100 bg-white px-4 py-3 text-[12.5px] leading-relaxed text-ink-500">
      使用流程：左侧选工具 → 右侧填 JSON 参数（每个工具预置示例入参，可点「重置示例」还原）→ 执行 → 下方查看结构化结果并复制。工具分为数理计算、化学、英语语文、成绩与学习管理、思维与基础训练五组。
    </p>

    <div class="grid grid-cols-12 gap-4">
      <div class="col-span-3 space-y-3">
        <div v-for="(items, cat) in filteredCatalog" :key="cat" class="card p-2">
          <div class="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">{{ cat }}</div>
          <button v-for="t in items" :key="t.key" class="block w-full rounded-control px-2 py-1.5 text-left text-[13px] transition-colors"
            :class="activeKey === t.key ? 'bg-brand-600 text-white' : 'text-ink-600 hover:bg-ink-100'" @click="pick(t)">{{ t.name }}</button>
        </div>
      </div>

      <div class="col-span-9">
        <div v-if="current" class="card p-5">
          <div class="mb-1 flex items-center gap-2">
            <h3 class="text-[15px] font-semibold text-ink-800">{{ current.name }}</h3>
            <span class="tag-brand">{{ current.cat }}</span><span class="font-mono text-[11px] text-ink-400">{{ current.key }}</span>
          </div>
          <p class="mb-3 text-[12px] text-ink-400">{{ current.desc }}</p>

          <div v-if="guide" class="mb-2 rounded-control bg-ink-100 px-3 py-2 text-[12px] leading-relaxed text-ink-500">
            <span class="font-medium text-ink-600">参数说明：</span>{{ guide.params }}
          </div>

          <label class="block">
            <span class="mb-1 block text-[12px] font-medium text-ink-600">参数（JSON，可直接修改示例）</span>
            <textarea v-model="paramText" class="input h-44 resize-none font-mono text-[12px]" spellcheck="false"></textarea>
          </label>
          <div class="mt-3 flex items-center gap-2">
            <button class="btn-primary" :disabled="running" @click="run">{{ running ? '计算中…' : '执 行' }}</button>
            <button class="btn-outline" @click="resetParam">重置示例</button>
            <button class="btn-ghost" @click="copyResult">复制结果</button>
            <span v-if="err" class="text-[12px] text-rose-500">{{ err }}</span>
          </div>

          <div v-if="result !== null" class="mt-4">
            <div class="mb-1 flex items-center justify-between">
              <div class="text-[12px] font-medium text-ink-600">结果</div>
              <button class="btn-ghost" @click="showRaw = !showRaw">{{ showRaw ? '结构化视图' : '查看原始 JSON' }}</button>
            </div>

            <template v-if="!isRaw">
              <dl v-if="dlPairs.length" class="mt-2 grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1 rounded-control border border-ink-100 px-3 py-2 text-[12px]">
                <template v-for="p in dlPairs" :key="p[0]">
                  <dt class="font-mono text-ink-400">{{ p[0] }}</dt>
                  <dd class="break-all text-ink-700">{{ p[1] }}</dd>
                </template>
              </dl>
              <div v-if="tableData" class="mt-2 overflow-auto rounded-control border border-ink-100">
                <table class="w-full border-collapse text-left text-[12px]">
                  <caption v-if="tableData.caption" class="bg-ink-100 px-3 py-1 text-left font-mono text-[11px] text-ink-500">{{ tableData.caption }}</caption>
                  <thead>
                    <tr class="bg-ink-100 text-ink-500">
                      <th v-for="c in tableData.cols" :key="c" class="whitespace-nowrap px-3 py-1.5 font-medium">{{ c }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in tableData.rows" :key="i" class="border-t border-ink-100">
                      <td v-for="(cell, j) in row" :key="j" class="px-3 py-1.5 font-mono text-ink-700">{{ cell }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <pre v-if="isRaw" class="mt-2 max-h-[26rem] overflow-auto whitespace-pre-wrap rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ pretty }}</pre>

            <div v-if="guide && guide.read" class="mt-2 rounded-control bg-ink-100 px-3 py-2 text-[12px] leading-relaxed text-ink-500">
              <span class="font-medium text-ink-600">结果怎么读：</span>{{ guide.read }}
            </div>
          </div>
        </div>
        <div v-else class="card grid h-64 place-items-center text-[13px] text-ink-400">左侧选一个工具，填好 JSON 参数后点「执 行」，结构化结果会展示在这里。</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const catalog = ref({})
const total = ref(0)
const kw = ref('')
const activeKey = ref('')
const current = ref(null)
const paramText = ref('{}')
const result = ref(null)
const running = ref(false)
const err = ref('')
const showRaw = ref(false)

// 每个工具的示例入参（无则空对象，工具内部用默认值）
const EXAMPLES = {
  'arith-gen': { n: 8, op: 'mixed', max: 100 }, 'fraction-simplify': { a: 12, b: 18 },
  'gcd-lcm': { nums: '12,18,24' }, prime: { n: 360 }, roman: { mode: 'to_roman', n: 2024 },
  quadratic: { a: 1, b: -5, c: 6 }, linear2: { a1: 1, b1: 1, c1: 5, a2: 1, b2: -1, c2: 1 },
  sequence: { kind: 'arithmetic', a1: 2, d: 3, n: 10 }, 'plane-geo': { shape: 'trapezoid', dims: '3,4,2' },
  'solid-geo': { shape: 'sphere', dims: '2' }, percent: { part: 25, whole: 80 },
  'unit-convert': { table: 'length', value: 1, from: 'km', to: 'm' }, temp: { value: 100, from: 'c' },
  'molar-mass': { formula: 'H2SO4' },
  'balance-check': { left: [{ f: 'Fe', n: 3 }, { f: 'O2', n: 2 }], right: [{ f: 'Fe3O4', n: 1 }] },
  'en-word-freq': { text: 'I like apples. I like milk. Apples are good.' },
  'en-readability': { text: 'The cat sat on the mat. It was a warm and sunny day. We played in the small green garden.' },
  'en-inflect': { word: 'study' }, pinyin: { text: '学习中文水山' },
  'composition-count': { text: '我爱学习。Learning is fun!\n\n第二段 here。' },
  'score-stats': { scores: '66,77,88,99,100,77' }, rank: { scores: '90,80,90,70', method: 'dense' },
  gpa: { score: 87 }, ebbinghaus: { start: '2026-09-11' }, pomodoro: { sessions: '25,25,50,65' },
  'roll-call': { names: '张三,李四,王五,赵六', n: 2 }, group: { names: 'a,b,c,d,e,f', by: 'count', count: 3 },
  'study-plan': { total: 100, days: 7, rest_every: 4, start: '2026-09-11' },
  'flashcard-sched': { level: 2, rating: 'good' }, 'truth-table': { expr: 'A and (B or not C)' },
  'study-time': { start: '08:30', end: '10:15' }, rmb: { number: 1234.56 },
  'calendar-math': { year: 2024, date: '2026-09-11', start: '2026-09-01', end: '2026-09-11' },
  'clock-drill': { n: 5 }, pattern: { n: 4, kind: 'arithmetic' }, 'ipa-table': {},
  'multiplication-table': { mode: 'drill', n: 8 }, 'unit-rate-table': {},
  probability: { kind: 'dice', n: 200 },
  'points-to-flashcard': { text: '光合作用：植物利用光能合成有机物\n呼吸作用：分解有机物释放能量\n- 牛顿第二定律：F=ma' },
}

// 每个工具的参数说明（params）与结果解读（read），key 不在此表则说明块隐藏
const TOOL_GUIDES = {
  'arith-gen': { params: 'n题量、op运算类型(mixed混合)、max操作数上限，如8题≤100', read: 'list逐题给题目与answer答案，count为总题数' },
  'fraction-simplify': { params: 'a、b两个整数分子分母，如a=12、b=18，b不能为0', read: 'numerator/denominator为约分后分子分母，附带分数小数' },
  'gcd-lcm': { params: 'nums填逗号分隔整数串，如"12,18,24"，至少给两个数', read: 'gcd为最大公约数，lcm为最小公倍数，nums回显输入' },
  prime: { params: 'n传一个待判断的正整数，如360，非正整数会返回提示', read: 'is_prime是否质数，factors为质因数列表，factor_expr算式' },
  roman: { params: 'mode选to_roman转罗马数字或to_number转回数字，n为数值', read: '输出roman罗马串与number数值，两边互转结果成对出现' },
  quadratic: { params: 'a、b、c对应ax²+bx+c=0的三个系数，可为负数或零', read: 'disc判别式，roots含两个根，disc<0时给复数根' },
  linear2: { params: 'a1,b1,c1与a2,b2,c2两组系数，对应两个方程的六项', read: 'det为行列式，x/y是方程组解，kind提示唯一或无解' },
  sequence: { params: 'kind选arithmetic(配d)或geometric(配q)，再给a1首项与n', read: 'a_n为第n项，sum_n为前n项和，formula给通项公式' },
  'plane-geo': { params: 'shape选rectangle/circle等，dims按序逗号给所需边长', read: 'shape回显图形名，area为面积、perimeter为周长' },
  'solid-geo': { params: 'shape选sphere/cylinder/cone等，dims逗号给半径高棱长', read: 'shape回显立体名，volume为体积、surface为表面积' },
  percent: { params: '给part与whole求占比，或给whole与percent求part部分量', read: '返回percent百分比；化简比时给ratio与simplified' },
  'unit-convert': { params: 'table选length/mass等表，value数值，from与to为单位符号', read: 'result为换算结果，in_base为折算到基准单位的值' },
  temp: { params: 'value温度数值，from选c/f/k标明当前温标，如100与c', read: '同时给出C摄氏、F华氏、K开尔文三个换算值' },
  'molar-mass': { params: 'formula填化学式字符串如H2SO4，注意元素大小写规范', read: 'molar_mass为摩尔质量(配unit)，atoms列各元素个数' },
  'balance-check': { params: 'left与right各传[{f化学式,n系数}]数组，比较两边原子', read: 'balanced是否配平，rows逐元素对比两边原子数，看message' },
  'en-word-freq': { params: 'text填一段英文，忽略大小写与标点统计每个单词次数', read: 'total_words总词数，unique_words词种数，另有词频排行' },
  'en-readability': { params: 'text填一段英文句子，句子越短单词越简单分数越高', read: 'words词数、sentences句数，另给Flesch难度分与参考年级' },
  'en-inflect': { params: 'word填规则变化的英文单词，如study，测试多种词形', read: 'plural复数、past过去式、ing分词等各含form与rule说明' },
  pinyin: { params: 'text填要注音的中文，可多个字，示例"学习中文水山"', read: 'annotated为逐字拼音，unknown列未识别字，可核对多音字' },
  'composition-count': { params: 'text粘贴作文原文，支持空行分段，中英文混排均可', read: 'chinese_chars汉字数、english_words英文词数、段落统计' },
  'score-stats': { params: 'scores填逗号分隔的成绩，如"66,77,88,99,100,77"', read: 'count个数、mean均值、median中位数，另含方差与及格率' },
  rank: { params: 'scores成绩串，method选standard/dense/competition并列规则', read: 'list逐条给score与rank，同分名次按method规则并列' },
  gpa: { params: 'score填百分制分数如87，也可传多个分数求平均绩点', read: '返回gpa绩点、grade等级字母，多分时附count个数' },
  ebbinghaus: { params: 'start填首次学习日期YYYY-MM-DD，按默认间隔生成复习点', read: 'start回显起始日，list按序给7轮复习日期与轮次' },
  pomodoro: { params: 'sessions填逗号分隔的专注时长分钟，如"25,25,50,65"', read: '看total_minutes总时长与count分段数，附小时折算' },
  'roll-call': { params: 'names填逗号分隔名单如"张三,李四,王五"，n为抽取人数', read: 'picked为中签者，total为名单总人数，可重复点名' },
  group: { params: 'names名单串，by选count按组数或size按每组人数分组', read: 'group_count组数，groups含no编号与members组员名单' },
  'study-plan': { params: 'total总任务量、days天数、rest_every每几天休息、start起始日', read: 'plan逐日列日期与任务量，per_day_avg为日均分配量' },
  'flashcard-sched': { params: 'level当前盒子等级1-5，rating答recognition/hard/good/easy', read: 'new_level调度后等级，另给下次复习间隔与日期' },
  'truth-table': { params: 'expr写命题公式，支持and/or/not与括号，如A and (B or not C)', read: 'rows逐行列真值组合，variables为变量，另判是否重言' },
  'study-time': { params: 'start与end填HH:MM格式起止时刻，可跨中午求区间', read: 'total_minutes总分钟数，text写成几小时几分钟，附小数小时' },
  rmb: { params: 'number填金额如1234.56，支持小数与负数金额', read: 'upper为人民币大写文本，number回显原金额' },
  'calendar-math': { params: 'year年份、date具体日期、start/end区间起止，按需填写', read: 'list逐项给日期、星期与是否闰年，count为条目数' },
  'clock-drill': { params: 'n出题数量，随机生成钟面认读题目供练习', read: 'count题数，list逐题给钟面时刻与标准答案' },
  pattern: { params: 'n生成项数，kind选arithmetic等差或square平方规律', read: '列出已知项与规律类型，可据此推出后续每一项' },
  'ipa-table': { params: '无需参数，传空对象{}即可，可加group筛选音标分组', read: 'groups按元音辅音分组，counts各组数量，total总数' },
  'multiplication-table': { params: 'mode选table出九九表或drill随机抽查，n为乘数上限', read: 'rows按行列给乘积表，drill时count题数、list含答案' },
  'unit-rate-table': { params: '无需参数，传空对象{}，返回各进率对照表', read: 'tables按长度面积质量分组，逐项给进率与换算关系' },
  probability: { params: 'kind选dice骰子/coin硬币，n为模拟实验次数如200', read: 'frequency为各结果实际次数，附理论概率与总次数' },
  'points-to-flashcard': { params: 'text每行写一个要点，行首加"-"表示该行已挖空', read: 'count卡数，cards逐张给front正面与back背面文本' },
}

const guide = computed(() => TOOL_GUIDES[activeKey.value] || null)

const filteredCatalog = computed(() => {
  const out = {}
  for (const [cat, items] of Object.entries(catalog.value)) {
    const hit = items
      .filter((t) => !kw.value || t.name.includes(kw.value) || t.key.includes(kw.value) || t.desc.includes(kw.value))
      .map((t) => ({ ...t, cat }))
    if (hit.length) out[cat] = hit
  }
  return out
})
const pretty = computed(() => JSON.stringify(result.value, null, 2))

// —— 结果结构化：标量/纯标量字段用 <dl>，数组用表格，否则回退原黑框 ——
function fmtVal(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
const resObj = computed(() => (result.value !== null && typeof result.value === 'object' && !Array.isArray(result.value) ? result.value : null))

const tableData = computed(() => {
  const r = result.value
  let arr = null
  let caption = ''
  if (Array.isArray(r)) arr = r
  else if (resObj.value) {
    const k = Object.keys(resObj.value).find((key) => Array.isArray(resObj.value[key]))
    if (k) { arr = resObj.value[k]; caption = k }
  }
  if (!Array.isArray(arr) || !arr.length) return null
  if (arr.every((x) => x !== null && typeof x === 'object' && !Array.isArray(x))) {
    const cols = [...new Set(arr.flatMap((o) => Object.keys(o)))]
    return { caption, cols, rows: arr.map((o) => cols.map((c) => fmtVal(o[c]))) }
  }
  if (arr.every((x) => x === null || typeof x !== 'object')) {
    return { caption, cols: ['值'], rows: arr.map((x) => [fmtVal(x)]) }
  }
  return null
})

const dlPairs = computed(() => {
  const r = result.value
  if (r === null || r === undefined) return []
  if (typeof r !== 'object' || Array.isArray(r)) return [['result', fmtVal(r)]]
  const scalars = Object.entries(r).filter(([, v]) => v === null || typeof v !== 'object')
  if (scalars.length) return scalars.map(([k, v]) => [k, fmtVal(v)])
  const inner = r.result
  if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
    return Object.entries(inner).filter(([, v]) => v === null || typeof v !== 'object').map(([k, v]) => [k, fmtVal(v)])
  }
  return []
})

const isRaw = computed(() => showRaw.value || (dlPairs.value.length === 0 && !tableData.value))

function pick(t) {
  activeKey.value = t.key
  current.value = t
  result.value = null
  err.value = ''
  showRaw.value = false
  resetParam()
}
function resetParam() { paramText.value = JSON.stringify(EXAMPLES[current.value.key] ?? {}, null, 2) }
async function run() {
  let params
  try { params = JSON.parse(paramText.value || '{}') } catch (e) { err.value = '参数不是合法 JSON'; return }
  running.value = true; err.value = ''
  try {
    result.value = (await learnApi.toolRun(activeKey.value, params)).result
    try { await learnApi.saveToolUsage(activeKey.value); await loadRecent() } catch { /* 历史记录失败不影响本次结果 */ }
  } catch (e) {
    err.value = e?.message || '执行失败'
  } finally { running.value = false }
}
async function copyResult() {
  if (result.value === null) return
  await navigator.clipboard.writeText(pretty.value)
  app.toastMsg('结果已复制', 'success')
}

// F538 工具使用历史：最近用过的工具可一键重开
const recentTools = ref([])
async function loadRecent() { recentTools.value = (await learnApi.toolUsage()).list }
function findTool(key) {
  for (const [cat, items] of Object.entries(catalog.value)) {
    const t = items.find((x) => x.key === key)
    if (t) return { ...t, cat }
  }
  return null
}
function reopenTool(key) {
  const t = findTool(key) || { key, name: recentTools.value.find((r) => r.key === key)?.name || key, cat: '', desc: '' }
  pick(t)
}

onMounted(async () => {
  const data = await learnApi.toolCatalog()
  catalog.value = data.categories
  total.value = data.total
  await loadRecent()
})
</script>
