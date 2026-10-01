<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">语文园地</h2>
        <p class="text-[12px] text-ink-400">古诗文赏析与默写接句、成语词典与接龙、汉字字典</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in tabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="tab = t.v">{{ t.label }}</button>
      </div>
    </div>

    <!-- 古诗文 -->
    <div v-if="tab === 'poem'" class="grid grid-cols-12 gap-4">
      <p class="col-span-12 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第一景 · 古诗文：左上角按学段筛篇目（标题下面是「朝代 · 作者」），点一首，右侧像翻开课本——
        大字原文保留换行、灰底译文、蓝底主旨赏析，往下还有逐句赏析与作者小传。想自测就点「接句练习」，
        练习会和原文并排摆着，一边看一边默写，两边互不顶掉。
      </p>
      <div class="card col-span-4 max-h-[72vh] overflow-auto p-3">
        <div class="mb-2 flex gap-2">
          <select v-model="pStage" class="input w-28" @change="loadPoems"><option value="">全部</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
          <button class="btn-outline" @click="loadDrill">接句练习</button>
        </div>
        <div v-if="!poems.length" class="px-1 text-[12px] leading-6 text-ink-400">这个学段还没有收录篇目，把筛选切回「全部」看看 30 首都在不在。</div>
        <button v-for="p in poems" :key="p.key" class="block w-full rounded-control px-3 py-2 text-left"
          :class="poem?.key === p.key ? 'bg-brand-600 text-white' : 'hover:bg-ink-50'" @click="openPoem(p.key)">
          <div class="text-[13px] font-medium">{{ p.title }}</div>
          <div class="text-[11px]" :class="poem?.key === p.key ? 'text-white/80' : 'text-ink-400'">{{ p.dynasty }} · {{ p.author }}</div>
        </button>
      </div>
      <div class="col-span-8 grid gap-4" :class="drill.length && poem ? 'md:grid-cols-2' : ''">
        <div v-if="poem" class="card p-5">
          <h3 class="text-[18px] font-semibold text-ink-900">{{ poem.title }}</h3>
          <div class="mt-0.5 text-[12px] text-ink-400">{{ poem.dynasty }} · {{ poem.author }}</div>
          <p class="mt-4 whitespace-pre-wrap text-[15px] leading-9 text-ink-800">{{ poem.text }}</p>
          <div class="mt-4 rounded-control bg-ink-50 p-3"><div class="text-[12px] font-semibold text-ink-600">译文</div>
            <p class="mt-1 text-[13px] leading-7 text-ink-600">{{ poem.translation }}</p></div>
          <div class="mt-2 rounded-control bg-brand-50 p-3"><div class="text-[12px] font-semibold text-brand-700">主旨赏析</div>
            <p class="mt-1 text-[13px] leading-7 text-brand-800">{{ poem.theme }}</p></div>
          <div v-if="Array.isArray(poem.lines) && poem.lines.length" class="mt-2 rounded-control bg-ink-50 p-3">
            <div class="text-[12px] font-semibold text-ink-600">逐句赏析</div>
            <div v-for="(ln, li) in poem.lines" :key="li" class="mt-1 text-[13px] leading-6 text-ink-600">
              <template v-if="typeof ln === 'string'">{{ ln }}</template>
              <template v-else>
                <span class="font-medium text-ink-700">{{ ln.line || ln.text || ln.shang || `第 ${li + 1} 句` }}</span>
                <template v-if="ln.note || ln.analysis || ln.comment">：{{ ln.note || ln.analysis || ln.comment }}</template>
              </template>
            </div>
          </div>
          <div v-if="poem.author_bio" class="mt-2 rounded-control bg-white p-3 ring-1 ring-ink-100">
            <div class="text-[12px] font-semibold text-ink-600">作者小传</div>
            <p class="mt-1 text-[13px] leading-6 text-ink-600">{{ poem.author_bio }}</p>
          </div>
          <div v-if="Array.isArray(poem.exam_points) && poem.exam_points.length" class="mt-2 rounded-control bg-amber-50 p-3">
            <div class="text-[12px] font-semibold text-amber-700">考点提示</div>
            <ul class="mt-1 ml-4 list-disc space-y-0.5 text-[13px] leading-6 text-amber-700">
              <li v-for="(ep, ei) in poem.exam_points" :key="ei">{{ ep }}</li>
            </ul>
          </div>
        </div>
        <div v-if="drill.length" class="card p-5">
          <h3 class="text-[15px] font-semibold text-ink-800">古诗接句 / 默写（{{ drill.length }} 题）</h3>
          <div v-for="(d, i) in drill" :key="i" class="mt-2 rounded-control border border-ink-100 p-3">
            <div class="text-[12px] text-ink-400">《{{ d.poem }}》{{ d.author }}</div>
            <div class="mt-1 text-[14px] text-ink-800">上句：{{ d.prompt }}，下句是？</div>
            <div class="mt-2 flex gap-2">
              <input v-model="drillAns[i]" class="input" placeholder="默写接句" />
              <button class="btn-outline" @click="d.show = !d.show">{{ d.show ? '隐藏' : '看答案' }}</button>
            </div>
            <div v-if="d.show" class="mt-1 text-[13px] font-medium text-brand-700">参考答案：{{ d.answer }}</div>
          </div>
        </div>
        <div class="card p-5">
          <h3 class="text-[15px] font-semibold text-ink-800">古诗填空 · 自动判分</h3>
          <div v-if="fb.key" class="mt-2">
            <div class="text-[12px] text-ink-400">《{{ fb.title }}》{{ fb.dynasty }} · {{ fb.author }}</div>
            <div class="mt-2 text-[15px] text-ink-800">上句：{{ fb.shang }}，<span class="text-brand-600">下句是？</span></div>
            <div class="mt-2 flex gap-2">
              <input v-model="fbAns" class="input" placeholder="默写整句下句" @keyup.enter="submitFb" />
              <button class="btn-primary" @click="submitFb">提交判分</button>
              <button class="btn-outline" @click="newFb">换一题</button>
            </div>
            <div v-if="fbRes" class="mt-2 text-[13px]" :class="fbRes.correct ? 'font-medium text-emerald-600' : 'text-rose-500'">
              {{ fbRes.correct ? '✓ 默写正确' : '✗ 还不对' }}
              <span class="ml-1 text-ink-500">参考答案：{{ fbRes.right_answer }}</span>
            </div>
          </div>
          <button v-else class="btn-outline mt-2" @click="newFb">开始填空练习</button>
        </div>
        <div v-if="!poem && !drill.length" class="card grid h-40 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          左边点一首诗看原文赏析，或点上方「接句练习」出 6 道默写题——两边会同时打开、并排对照。
        </div>
      </div>
    </div>

    <!-- 成语 -->
    <div v-else-if="tab === 'idiom'" class="grid grid-cols-12 gap-4">
      <p class="col-span-12 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第二景 · 成语：左边搜一个字（试试「蛇」「花」）列出两列成语卡——大字、拼音、释义加一条「例：」用法；
        点卡片还能展开典故、近反义词和易错用法。右边是成语接龙：输入或点「接龙」看末字是哪个字，
        再点候选词一路接下去，词库里接不上时会如实提示。
      </p>
      <div class="card col-span-7 p-4">
        <div class="mb-3 flex gap-2">
          <input v-model="idiomQ" class="input" placeholder="搜索成语，如 蛇" @keyup.enter="loadIdioms" />
          <button class="btn-primary" @click="loadIdioms">搜索</button>
        </div>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="x in idioms" :key="x.word" class="cursor-pointer rounded-control border p-3 transition-colors"
            :class="openIdiom === x.word ? 'border-brand-300 bg-brand-50/50 ring-2 ring-brand-100' : 'border-ink-100 hover:border-brand-200'"
            @click="toggleIdiom(x.word)">
            <div class="flex items-baseline gap-2">
              <span class="text-[15px] font-semibold text-ink-900">{{ x.word }}</span>
              <span class="font-mono text-[11px] text-ink-400">{{ x.pinyin }}</span>
              <span class="ml-auto text-[11px] text-brand-600">{{ openIdiom === x.word ? '收起 ▲' : '典故 ▼' }}</span>
            </div>
            <div class="mt-1 text-[12px] text-ink-600">{{ x.meaning }}</div>
            <div class="mt-1 text-[12px] text-ink-400">例：{{ x.example }}</div>
            <div v-if="openIdiom === x.word" class="mt-2 space-y-1 border-t border-ink-100 pt-2 text-[12px] leading-6">
              <div v-if="x.allusion"><span class="font-semibold text-ink-700">典故：</span><span class="text-ink-600">{{ textOf(x.allusion) }}</span></div>
              <div v-if="asList(x.near).length">
                <span class="font-semibold text-ink-700">近反义：</span>
                <span v-for="(n, ni) in asList(x.near)" :key="ni" class="tag mr-1 mb-1">{{ n }}</span>
              </div>
              <div v-if="x.usage_tip" class="text-amber-700"><span class="font-semibold">易错用法：</span>{{ textOf(x.usage_tip) }}</div>
              <div v-if="!x.allusion && !asList(x.near).length && !x.usage_tip" class="text-ink-400">
                这条成语的典故与近反义正在逐条补齐，先记住上面的释义和「例：」用法。
              </div>
            </div>
          </div>
          <div v-if="!idioms.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
            词库里没搜到这个词：换个字试试（「蛇」「花」「龙」都收了不少），或清空搜索框点「搜索」看全部成语。
          </div>
        </div>
      </div>
      <div class="card col-span-5 p-4">
        <h3 class="mb-3 flex flex-wrap items-center gap-2 text-[15px] font-semibold text-ink-800">
          成语接龙<span class="tag-brand">本局 {{ myChain.length }} 个 · 历史最佳 {{ chainStat.best || 0 }}</span>
        </h3>
        <div class="flex flex-wrap gap-2">
          <input v-model="chainWord" class="input min-w-[160px] flex-1" placeholder="输入一个成语，如 画蛇添足" @keyup.enter="startChain" />
          <select v-model="chainDiff" class="input w-24"><option value="easy">简单</option><option value="normal">普通</option><option value="hard">困难</option></select>
          <button class="btn-primary" @click="startChain">开局</button>
        </div>
        <div v-if="myChain.length" class="mt-2">
          <div class="text-[12px] text-ink-400">本局链：</div>
          <div class="mt-1 flex flex-wrap gap-1">
            <span v-for="(w, wi) in myChain" :key="wi" class="tag-brand">{{ w }}</span>
          </div>
        </div>
        <div v-if="chain" class="mt-3">
          <div class="text-[13px] text-ink-600">「{{ chain.word }}」末字为 <b class="text-brand-700">{{ chain.tail }}</b>，可接：</div>
          <div v-if="chain.next.length" class="mt-2 flex flex-wrap gap-1.5">
            <button v-for="w in chain.next" :key="w" class="tag-brand cursor-pointer" @click="continueChain(w)">{{ w }}</button>
          </div>
          <div v-else class="mt-2 text-[13px] text-ink-400">词库中暂无以该字开头的成语——这局到此为止，可保存战绩。</div>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <button class="btn-outline px-3" :disabled="myChain.length < 2" @click="saveChainRecord">保存本局战绩</button>
          <button class="btn-ghost px-0 text-[12px] text-ink-400" @click="resetChain">清空重开</button>
        </div>
        <div v-if="chainStat.total" class="mt-3 border-t border-ink-100 pt-2 text-[12px] text-ink-500">
          <div class="font-medium text-ink-700">个人战绩（共 {{ chainStat.total }} 局）</div>
          <div class="mt-1">最长链 {{ chainStat.best }}；简单 {{ chainStat.by_difficulty?.easy || 0 }} · 普通 {{ chainStat.by_difficulty?.normal || 0 }} · 困难 {{ chainStat.by_difficulty?.hard || 0 }}</div>
          <div v-for="r in chainStat.list" :key="r.id" class="mt-0.5 text-[11px] text-ink-400">{{ r.difficulty }} · {{ r.length }} 个 · {{ r.created_at }}</div>
        </div>
      </div>
    </div>

    <!-- 汉字 -->
    <div v-else class="space-y-4">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        第三景 · 汉字字典兼拼音库：输入单字点「查字」，或点一排部首标签筛选（如「氵」「木」）。
        每张卡是大字加「拼音 · 几画 · 部首」，点开下方灰条给完整释义；后端补齐后还能看到组词、造句
        和形近字辨析，避免写错别字。
      </p>
      <div class="card p-4">
        <div class="mb-3 flex flex-wrap items-center gap-2">
          <input v-model="hanziChar" class="input w-48" placeholder="查汉字，如 水" @keyup.enter="searchHanzi" />
          <button class="btn-primary" @click="searchHanzi">查字</button>
          <button class="btn-outline" @click="resetHanzi">全部汉字</button>
          <div class="flex flex-wrap gap-1">
            <button v-for="r in radicals" :key="r" class="tag cursor-pointer" :class="hanziRadical === r ? 'bg-brand-600 text-white' : ''" @click="filterRadical(r)">{{ r }}</button>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-6">
          <button v-for="h in hanziList" :key="h.char" class="rounded-control border border-ink-100 p-3 text-left hover:border-brand-400" @click="activeHanzi = h">
            <div class="text-[22px] font-bold text-ink-900">{{ h.char }}</div>
            <div class="text-[11px] text-ink-400">{{ h.pinyin }} · {{ h.strokes }}画 · 部首{{ h.radical }}</div>
          </button>
          <div v-if="!hanziList.length" class="col-span-2 rounded-control bg-ink-50 p-4 text-center text-[13px] leading-6 text-ink-400 md:col-span-4 lg:col-span-6">
            没有匹配的汉字：点「全部汉字」看完整字库，或换一个部首（比如「木」「口」）再筛。
          </div>
        </div>
        <div v-if="activeHanzi" class="mt-3 rounded-control bg-ink-50 p-3 text-[13px] leading-7 text-ink-700">
          <b class="text-[16px] text-ink-900">{{ activeHanzi.char }}</b>（{{ activeHanzi.pinyin }}），部首 {{ activeHanzi.radical }}，共 {{ activeHanzi.strokes }} 画。{{ activeHanzi.meaning }}
          <div v-if="asList(activeHanzi.words).length" class="mt-1">
            <span class="font-semibold text-ink-600">组词：</span>
            <span v-for="(wd, wi) in asList(activeHanzi.words)" :key="wi" class="tag-brand mr-1 mb-1">{{ wd }}</span>
          </div>
          <div v-if="activeHanzi.sentence" class="mt-1"><span class="font-semibold text-ink-600">造句：</span>{{ textOf(activeHanzi.sentence) }}</div>
          <div v-if="activeHanzi.lookalike" class="mt-1 text-amber-700"><span class="font-semibold">形近字辨析：</span>{{ textOf(activeHanzi.lookalike) }}</div>
          <div v-if="!asList(activeHanzi.words).length && !activeHanzi.sentence && !activeHanzi.lookalike" class="mt-1 text-[12px] text-ink-400">
            组词 / 造句 / 形近字还在逐字补充，先按上面的拼音与释义记。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()

const tabs = [{ v: 'poem', label: '古诗文' }, { v: 'idiom', label: '成语' }, { v: 'hanzi', label: '汉字字典' }]
const tab = ref('poem')

const poems = ref([])
const poem = ref(null)
const pStage = ref('')
const drill = ref([])
const drillAns = ref({})
async function loadPoems() { poems.value = (await learnApi.poems(pStage.value ? { stage: pStage.value } : {})).list }
// 打开原文不关练习、打开练习不清原文：两者并排，互不顶掉（S9）
async function openPoem(key) { poem.value = (await learnApi.poem(key)) }
async function loadDrill() { drillAns.value = {}; drill.value = (await learnApi.poemDrill({ n: 6 })).list }

// F528 古诗填空（自动挖空 + 按上句判分）
const fb = ref({})
const fbAns = ref('')
const fbRes = ref(null)
async function newFb() { fbRes.value = null; fbAns.value = ''; fb.value = await learnApi.poemFillBlank() }
async function submitFb() {
  if (!fbAns.value.trim()) return
  fbRes.value = await learnApi.poemFillSubmit({ key: fb.value.key, shang: fb.value.shang, answer: fbAns.value })
}

const idioms = ref([])
const idiomQ = ref('')
const chainWord = ref('画蛇添足')
const chain = ref(null)
const myChain = ref([])
const chainDiff = ref('normal')
const chainStat = ref({})
// 成语卡片可点开（S7）：典故 / 近反义 / 易错用法，字段缺失时优雅隐藏
const openIdiom = ref('')
function toggleIdiom(w) { openIdiom.value = openIdiom.value === w ? '' : w }
const asList = (v) => (Array.isArray(v) ? v : v ? [v] : [])
const textOf = (v) => {
  if (v === null || v === undefined || v === '') return ''
  if (Array.isArray(v)) return v.join('、')
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k}：${x}`).join('；')
  return String(v)
}
async function loadIdioms() { idioms.value = (await learnApi.idioms(idiomQ.value)).list }
// F529 成语接龙：维护本局链 + 战绩记录
async function startChain() {
  if (!chainWord.value) return
  chain.value = await learnApi.idiomChain(chainWord.value)
  myChain.value = [chain.value.word]
}
async function continueChain(w) {
  chainWord.value = w
  chain.value = await learnApi.idiomChain(w)
  if (!myChain.value.includes(w)) myChain.value.push(w)
}
function resetChain() { chain.value = null; myChain.value = []; chainWord.value = '' }
async function saveChainRecord() {
  if (myChain.value.length < 2) return
  await learnApi.saveIdiomChain({ chain: myChain.value, difficulty: chainDiff.value })
  await loadChainStat()
  app.toastMsg(`本局 ${myChain.value.length} 个成语的战绩已保存`, 'success')
}
async function loadChainStat() { chainStat.value = await learnApi.idiomChainRecords() }

const hanziList = ref([])
const radicals = ref([])
const hanziChar = ref('')
const hanziRadical = ref('')
const activeHanzi = ref(null)
async function searchHanzi() { hanziRadical.value = ''; hanziList.value = (await learnApi.hanzi(hanziChar.value ? { char: hanziChar.value } : {})).list }
async function filterRadical(r) { hanziChar.value = ''; hanziRadical.value = hanziRadical.value === r ? '' : r; hanziList.value = (await learnApi.hanzi(hanziRadical.value ? { radical: hanziRadical.value } : {})).list }
async function resetHanzi() { hanziRadical.value = ''; hanziChar.value = ''; hanziList.value = (await learnApi.hanzi({})).list }

onMounted(async () => {
  await loadPoems()
  await loadIdioms()
  await loadChainStat()
  const h = await learnApi.hanzi({})
  hanziList.value = h.list
  radicals.value = h.radicals
})
</script>
