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
      <div class="card col-span-4 max-h-[72vh] overflow-auto p-3">
        <div class="mb-2 flex gap-2">
          <select v-model="pStage" class="input w-28" @change="loadPoems"><option value="">全部</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
          <button class="btn-outline" @click="loadDrill">接句练习</button>
        </div>
        <button v-for="p in poems" :key="p.key" class="block w-full rounded-control px-3 py-2 text-left"
          :class="poem?.key === p.key ? 'bg-brand-600 text-white' : 'hover:bg-ink-50'" @click="openPoem(p.key)">
          <div class="text-[13px] font-medium">{{ p.title }}</div>
          <div class="text-[11px]" :class="poem?.key === p.key ? 'text-white/80' : 'text-ink-400'">{{ p.dynasty }} · {{ p.author }}</div>
        </button>
      </div>
      <div class="card col-span-8 p-5">
        <div v-if="drill.length" class="space-y-3">
          <h3 class="text-[15px] font-semibold text-ink-800">古诗接句 / 默写（{{ drill.length }} 题）</h3>
          <div v-for="(d, i) in drill" :key="i" class="rounded-control border border-ink-100 p-3">
            <div class="text-[12px] text-ink-400">《{{ d.poem }}》{{ d.author }}</div>
            <div class="mt-1 text-[14px] text-ink-800">上句：{{ d.prompt }}，下句是？</div>
            <div class="mt-2 flex gap-2">
              <input v-model="drillAns[i]" class="input" placeholder="默写接句" />
              <button class="btn-outline" @click="d.show = !d.show">{{ d.show ? '隐藏' : '看答案' }}</button>
            </div>
            <div v-if="d.show" class="mt-1 text-[13px] font-medium text-brand-700">参考答案：{{ d.answer }}</div>
          </div>
        </div>
        <div v-else-if="poem">
          <h3 class="text-[18px] font-semibold text-ink-900">{{ poem.title }}</h3>
          <div class="mt-0.5 text-[12px] text-ink-400">{{ poem.dynasty }} · {{ poem.author }}</div>
          <p class="mt-4 whitespace-pre-wrap text-[15px] leading-9 text-ink-800">{{ poem.text }}</p>
          <div class="mt-4 rounded-control bg-ink-50 p-3"><div class="text-[12px] font-semibold text-ink-600">译文</div>
            <p class="mt-1 text-[13px] leading-7 text-ink-600">{{ poem.translation }}</p></div>
          <div class="mt-2 rounded-control bg-brand-50 p-3"><div class="text-[12px] font-semibold text-brand-700">主旨赏析</div>
            <p class="mt-1 text-[13px] leading-7 text-brand-800">{{ poem.theme }}</p></div>
        </div>
        <div v-else class="grid h-40 place-items-center text-[13px] text-ink-400">选择古诗查看，或开始接句练习</div>
      </div>
    </div>

    <!-- 成语 -->
    <div v-else-if="tab === 'idiom'" class="grid grid-cols-12 gap-4">
      <div class="card col-span-7 p-4">
        <div class="mb-3 flex gap-2">
          <input v-model="idiomQ" class="input" placeholder="搜索成语，如 蛇" @keyup.enter="loadIdioms" />
          <button class="btn-primary" @click="loadIdioms">搜索</button>
        </div>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="x in idioms" :key="x.word" class="rounded-control border border-ink-100 p-3">
            <div class="flex items-baseline gap-2"><span class="text-[15px] font-semibold text-ink-900">{{ x.word }}</span><span class="font-mono text-[11px] text-ink-400">{{ x.pinyin }}</span></div>
            <div class="mt-1 text-[12px] text-ink-600">{{ x.meaning }}</div>
            <div class="mt-1 text-[12px] text-ink-400">例：{{ x.example }}</div>
          </div>
        </div>
      </div>
      <div class="card col-span-5 p-4">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">成语接龙</h3>
        <div class="flex gap-2">
          <input v-model="chainWord" class="input" placeholder="输入一个成语，如 画蛇添足" @keyup.enter="runChain" />
          <button class="btn-primary" @click="runChain">接龙</button>
        </div>
        <div v-if="chain" class="mt-3">
          <div class="text-[13px] text-ink-600">「{{ chain.word }}」末字为 <b class="text-brand-700">{{ chain.tail }}</b>，可接：</div>
          <div v-if="chain.next.length" class="mt-2 flex flex-wrap gap-1.5">
            <button v-for="w in chain.next" :key="w" class="tag-brand cursor-pointer" @click="chainWord = w; runChain()">{{ w }}</button>
          </div>
          <div v-else class="mt-2 text-[13px] text-ink-400">词库中暂无以该字开头的成语</div>
        </div>
      </div>
    </div>

    <!-- 汉字 -->
    <div v-else class="card p-4">
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
      </div>
      <div v-if="activeHanzi" class="mt-3 rounded-control bg-ink-50 p-3 text-[13px] leading-7 text-ink-700">
        <b class="text-[16px] text-ink-900">{{ activeHanzi.char }}</b>（{{ activeHanzi.pinyin }}），部首 {{ activeHanzi.radical }}，共 {{ activeHanzi.strokes }} 画。{{ activeHanzi.meaning }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { learnApi } from '../../../api'

const tabs = [{ v: 'poem', label: '古诗文' }, { v: 'idiom', label: '成语' }, { v: 'hanzi', label: '汉字字典' }]
const tab = ref('poem')

const poems = ref([])
const poem = ref(null)
const pStage = ref('')
const drill = ref([])
const drillAns = ref({})
async function loadPoems() { poems.value = (await learnApi.poems(pStage.value ? { stage: pStage.value } : {})).list }
async function openPoem(key) { drill.value = []; poem.value = (await learnApi.poem(key)) }
async function loadDrill() { poem.value = null; drillAns.value = {}; drill.value = (await learnApi.poemDrill({ n: 6 })).list }

const idioms = ref([])
const idiomQ = ref('')
const chainWord = ref('画蛇添足')
const chain = ref(null)
async function loadIdioms() { idioms.value = (await learnApi.idioms(idiomQ.value)).list }
async function runChain() { if (!chainWord.value) return; chain.value = (await learnApi.idiomChain(chainWord.value)) }

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
  const h = await learnApi.hanzi({})
  hanziList.value = h.list
  radicals.value = h.radicals
})
</script>
