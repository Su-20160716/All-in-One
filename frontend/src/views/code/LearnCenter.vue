<script setup>
/**
 * 代码学习中心（v6 · L5 竞技教学）
 *
 * 路由：/code/learn
 *
 * 五个标签页：
 * - 总览：个人学习看板（指标 / 7 天打卡 / 成就进度 / 错题数）
 * - 每日一题：今日题目 + 编辑器 + 判题
 * - 成就：徽章墙（已解锁高亮 / 未解锁显示进度条）
 * - 错题本：错题列表 / 标记掌握 / 复习
 * - 学习路径：生成路径 / 勾选进度
 * - 竞技场：战力统计 + 三榜 + 随机挑战
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../stores/app'
import CodeEditor from '../../components/CodeEditor.vue'
import Modal from '../../components/Modal.vue'
import codeApi from '../../api/code.js'
import { formatTime } from '../../utils/format'

const app = useAppStore()
const router = useRouter()

const tab = ref('overview')
const TABS = [
  { key: 'overview', label: '总览', icon: '📊' },
  { key: 'daily', label: '每日一题', icon: '📅' },
  { key: 'achievement', label: '成就', icon: '🏅' },
  { key: 'wrong', label: '错题本', icon: '📕' },
  { key: 'path', label: '学习路径', icon: '🗺' },
  { key: 'arena', label: '竞技场', icon: '⚔️' },
]

// ---- 总览 ----
const overview = ref(null)
const overviewLoading = ref(false)

async function loadOverview() {
  overviewLoading.value = true
  try {
    overview.value = await codeApi.learnOverview()
  } catch (e) {
    app.toastMsg?.('加载总览失败')
  } finally {
    overviewLoading.value = false
  }
}

// ---- 每日一题 ----
const daily = ref(null)
const dailyCode = ref('')
const dailyResult = ref(null)
const dailyBusy = ref(false)
const dailyHistory = ref(null)

async function loadDaily() {
  try {
    const res = await codeApi.dailyToday()
    daily.value = res
    if (!dailyCode.value) dailyCode.value = (res.challenge && res.challenge.template) || ''
  } catch (e) {
    app.toastMsg?.('加载今日题目失败')
  }
}

async function loadDailyHistory() {
  try {
    dailyHistory.value = await codeApi.dailyHistory(30)
  } catch { /* 静默 */ }
}

async function submitDaily() {
  if (dailyBusy.value) return
  if (!dailyCode.value.trim()) {
    app.toastMsg?.('先写点代码')
    return
  }
  dailyBusy.value = true
  dailyResult.value = null
  try {
    const res = await codeApi.dailySubmit({
      code: dailyCode.value,
      language: daily.value?.challenge?.language || 'python',
    })
    dailyResult.value = res
    if (res.accepted) {
      app.toastMsg?.(`通过！连续打卡 ${res.streak} 天 🎉`)
    } else {
      app.toastMsg?.(`未通过：${verdictLabel(res.verdict)}（${res.passed}/${res.total}）`)
    }
    if (res.unlocked && res.unlocked.length) {
      res.unlocked.forEach((u) => app.toastMsg?.(`解锁成就 ${u.icon} ${u.name}`))
    }
    loadDaily()
    loadDailyHistory()
    if (overview.value) loadOverview()
  } catch (e) {
    app.toastMsg?.(e?.message || '提交失败')
  } finally {
    dailyBusy.value = false
  }
}

function verdictLabel(v) {
  return {
    accepted: '通过', wrong_answer: '答案错误', time_limit: '超时',
    runtime_error: '运行时错误', compile_error: '编译错误',
    unavailable: '运行时不可用', rejected: '已拒绝',
  }[v] || v
}

function verdictClass(v) {
  if (v === 'accepted') return 'text-emerald-600'
  if (v === 'unavailable') return 'text-ink-400'
  return 'text-rose-600'
}

// ---- 成就 ----
const achievements = ref(null)

async function loadAchievements() {
  try {
    achievements.value = await codeApi.achievements()
  } catch (e) {
    app.toastMsg?.('加载成就失败')
  }
}

const tierStyle = {
  bronze: 'from-amber-100 to-amber-50 border-amber-300',
  silver: 'from-slate-100 to-slate-50 border-slate-300',
  gold: 'from-yellow-100 to-amber-50 border-yellow-400',
}

// ---- 错题本 ----
const wrong = ref(null)
const wrongFilter = ref('unmastered')

async function loadWrong() {
  try {
    wrong.value = await codeApi.wrongList({ filter: wrongFilter.value, limit: 200 })
  } catch (e) {
    app.toastMsg?.('加载错题本失败')
  }
}

async function reviewWrong(w, mastered) {
  try {
    await codeApi.wrongReview(w.id, mastered ? { mastered: true } : {})
    loadWrong()
    app.toastMsg?.(mastered ? '已标记掌握 ✓' : '已记录一次复习')
  } catch (e) {
    app.toastMsg?.('操作失败')
  }
}

async function removeWrong(w) {
  if (!window.confirm(`从错题本移除「${w.title}」？`)) return
  try {
    await codeApi.wrongDelete(w.id)
    loadWrong()
    app.toastMsg?.('已移除')
  } catch (e) {
    app.toastMsg?.('移除失败')
  }
}

// ---- 学习路径 ----
const paths = ref(null)
const pathDetail = ref(null)
const genOpen = ref(false)
const genForm = ref({ language: 'python', level: 'beginner', goal: '' })
const genBusy = ref(false)

async function loadPaths() {
  try {
    paths.value = await codeApi.pathList(20)
  } catch (e) {
    app.toastMsg?.('加载学习路径失败')
  }
}

async function generatePath() {
  if (genBusy.value) return
  genBusy.value = true
  try {
    const res = await codeApi.pathGenerate({ ...genForm.value })
    genOpen.value = false
    app.toastMsg?.(`路径已生成（${res.source === 'llm' ? 'AI' : '本地模板'}）`)
    await loadPaths()
    openPath(res.id)
  } catch (e) {
    app.toastMsg?.(e?.message || '生成失败')
  } finally {
    genBusy.value = false
  }
}

async function openPath(id) {
  try {
    pathDetail.value = await codeApi.pathDetail(id)
  } catch (e) {
    app.toastMsg?.('打开路径失败')
  }
}

async function tickItem(stageIdx, itemIdx) {
  const p = pathDetail.value
  if (!p) return
  const key = `${stageIdx}-${itemIdx}`
  const done = !(p.progress || []).includes(key)
  try {
    const res = await codeApi.pathTick(p.id, key, done)
    p.progress = res.progress
    p.done_items = res.done_items
    p.percent = res.percent
    // 同步列表里的百分比
    const it = (paths.value?.items || []).find((x) => x.id === p.id)
    if (it) {
      it.done_items = res.done_items
      it.percent = res.percent
    }
  } catch (e) {
    app.toastMsg?.('更新失败')
  }
}

async function deletePath(p) {
  if (!window.confirm(`删除学习路径「${p.title}」？`)) return
  try {
    await codeApi.pathDelete(p.id)
    if (pathDetail.value?.id === p.id) pathDetail.value = null
    loadPaths()
    app.toastMsg?.('已删除')
  } catch (e) {
    app.toastMsg?.('删除失败')
  }
}

function isDone(stageIdx, itemIdx) {
  return ((pathDetail.value?.progress) || []).includes(`${stageIdx}-${itemIdx}`)
}

// ---- 竞技场 ----
const arena = ref(null)
const challenge = ref(null)
const arenaCode = ref('')
const arenaResult = ref(null)
const arenaBusy = ref(false)

async function loadArena() {
  try {
    arena.value = await codeApi.arenaBoard()
  } catch (e) {
    app.toastMsg?.('加载竞技场失败')
  }
}

async function drawChallenge(difficulty = '') {
  try {
    challenge.value = await codeApi.arenaChallenge(difficulty)
    arenaCode.value = challenge.value.template || ''
    arenaResult.value = null
  } catch (e) {
    app.toastMsg?.('抽题失败')
  }
}

async function submitChallenge() {
  if (arenaBusy.value || !challenge.value) return
  if (!arenaCode.value.trim()) {
    app.toastMsg?.('先写点代码')
    return
  }
  arenaBusy.value = true
  arenaResult.value = null
  try {
    const res = await codeApi.arenaSubmit({
      title: challenge.value.title,
      code: arenaCode.value,
    })
    arenaResult.value = res
    app.toastMsg?.(res.accepted ? '挑战成功 🎉' : `未通过：${verdictLabel(res.verdict)}`)
    loadArena()
  } catch (e) {
    app.toastMsg?.(e?.message || '提交失败')
  } finally {
    arenaBusy.value = false
  }
}

// ---- 标签切换 ----
const loaded = ref({})
function switchTab(k) {
  tab.value = k
  if (loaded.value[k]) return
  loaded.value[k] = true
  if (k === 'daily') { loadDaily(); loadDailyHistory() }
  if (k === 'achievement') loadAchievements()
  if (k === 'wrong') loadWrong()
  if (k === 'path') loadPaths()
  if (k === 'arena') loadArena()
}

onMounted(() => {
  loadOverview()
  loaded.value.overview = true
})
</script>

<template>
  <div class="p-5">
    <!-- 头部 -->
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-ink-900">代码学习中心</h1>
        <p class="mt-0.5 text-sm text-ink-500">每日一题 · 成就徽章 · 错题复盘 · 学习路径 · 竞技比拼</p>
      </div>
      <button class="btn-outline" @click="router.push('/code')">← 回代码工坊</button>
    </div>

    <!-- 标签栏 -->
    <div class="mb-4 flex flex-wrap gap-1.5">
      <button
        v-for="t in TABS"
        :key="t.key"
        class="rounded-lg px-3 py-1.5 text-sm transition"
        :class="tab === t.key
          ? 'bg-brand-600 text-white shadow-sm'
          : 'bg-ink-100 text-ink-600 hover:bg-ink-200'"
        @click="switchTab(t.key)"
      >
        {{ t.icon }} {{ t.label }}
      </button>
    </div>

    <!-- ============ 总览 ============ -->
    <div v-if="tab === 'overview'">
      <div v-if="overviewLoading" class="card py-12 text-center text-ink-400">加载中…</div>
      <template v-else-if="overview">
        <!-- 指标卡 -->
        <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="card">
            <div class="text-xs text-ink-500">连续打卡</div>
            <div class="mt-1 text-2xl font-semibold text-brand-600">
              {{ overview.daily_streak }}<span class="ml-0.5 text-sm font-normal text-ink-400">天</span>
            </div>
          </div>
          <div class="card">
            <div class="text-xs text-ink-500">累计执行</div>
            <div class="mt-1 text-2xl font-semibold text-ink-900">{{ overview.metrics.run_count }}</div>
          </div>
          <div class="card">
            <div class="text-xs text-ink-500">判题通过</div>
            <div class="mt-1 text-2xl font-semibold text-ink-900">{{ overview.metrics.judge_accepted }}</div>
          </div>
          <div class="card">
            <div class="text-xs text-ink-500">待消化错题</div>
            <div class="mt-1 text-2xl font-semibold"
                 :class="overview.wrong.unmastered ? 'text-rose-600' : 'text-emerald-600'">
              {{ overview.wrong.unmastered }}
            </div>
          </div>
        </div>

        <!-- 近 7 天打卡 -->
        <div class="card mb-4">
          <div class="mb-3 text-sm font-semibold text-ink-900">近 7 天</div>
          <div class="flex gap-2">
            <div
              v-for="d in overview.week"
              :key="String(d.date)"
              class="flex-1 rounded-lg border py-2 text-center text-xs"
              :class="d.passed
                ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                : (d.done ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-ink-200 bg-ink-50 text-ink-400')"
            >
              <div class="font-medium">{{ String(d.date).slice(5) }}</div>
              <div class="mt-0.5">{{ d.passed ? '✓' : (d.done ? '…' : '—') }}</div>
            </div>
          </div>
        </div>

        <!-- 成就 + 路径 -->
        <div class="grid gap-3 md:grid-cols-2">
          <div class="card">
            <div class="mb-2 flex items-center justify-between">
              <div class="text-sm font-semibold text-ink-900">成就进度</div>
              <button class="btn-ghost text-xs" @click="switchTab('achievement')">查看全部 →</button>
            </div>
            <div class="text-3xl font-semibold text-ink-900">
              {{ overview.achievements.unlocked }}
              <span class="text-base font-normal text-ink-400">/ {{ overview.achievements.total }}</span>
            </div>
            <div class="mt-2 h-2 overflow-hidden rounded-full bg-ink-100">
              <div class="h-full rounded-full bg-brand-500 transition-all"
                   :style="{ width: (overview.achievements.total
                     ? (overview.achievements.unlocked * 100 / overview.achievements.total) : 0) + '%' }" />
            </div>
          </div>

          <div class="card">
            <div class="mb-2 flex items-center justify-between">
              <div class="text-sm font-semibold text-ink-900">进行中的学习路径</div>
              <button class="btn-ghost text-xs" @click="switchTab('path')">管理 →</button>
            </div>
            <template v-if="overview.active_path">
              <div class="truncate font-medium text-ink-800">{{ overview.active_path.title }}</div>
              <div class="mt-1 text-xs text-ink-500">
                {{ overview.active_path.done_items }} / {{ overview.active_path.total_items }} 项
              </div>
              <div class="mt-2 h-2 overflow-hidden rounded-full bg-ink-100">
                <div class="h-full rounded-full bg-emerald-500 transition-all"
                     :style="{ width: overview.active_path.percent + '%' }" />
              </div>
            </template>
            <div v-else class="py-3 text-sm text-ink-400">
              还没有学习路径，
              <button class="text-brand-600 underline" @click="switchTab('path')">去生成一份</button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ============ 每日一题 ============ -->
    <div v-else-if="tab === 'daily'">
      <div v-if="daily" class="grid gap-4 lg:grid-cols-2">
        <!-- 题目 -->
        <div class="card">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <span class="tag-brand">{{ String(daily.challenge.date) }}</span>
            <span class="tag">{{ daily.challenge.difficulty }}</span>
            <span class="tag">{{ daily.challenge.language }}</span>
            <span v-if="daily.challenge.solved" class="tag bg-emerald-100 text-emerald-700">今日已通过 ✓</span>
            <span v-if="daily.streak" class="ml-auto text-xs text-brand-600">🔥 连续 {{ daily.streak }} 天</span>
          </div>
          <h2 class="mb-2 text-lg font-semibold text-ink-900">{{ daily.challenge.title }}</h2>
          <pre class="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink-700">{{ daily.challenge.description }}</pre>
          <div class="mt-3 flex flex-wrap gap-1.5">
            <span v-for="t in daily.challenge.tags" :key="t"
                  class="rounded bg-ink-100 px-1.5 py-0.5 text-[11px] text-ink-600">{{ t }}</span>
          </div>
          <div class="mt-3 text-xs text-ink-400">
            共 {{ daily.challenge.case_count }} 个测试用例 · 未通过会自动进错题本
          </div>
        </div>

        <!-- 作答 -->
        <div class="card overflow-hidden p-0">
          <CodeEditor
            v-model="dailyCode"
            :language="daily.challenge.language"
            height="42vh"
          />
          <div class="flex items-center justify-between border-t border-ink-100 px-3 py-2">
            <div class="text-xs text-ink-500">
              <span v-if="dailyResult" :class="verdictClass(dailyResult.verdict)" class="font-medium">
                {{ verdictLabel(dailyResult.verdict) }} · {{ dailyResult.passed }}/{{ dailyResult.total }}
                <span class="text-ink-400">· {{ dailyResult.duration_ms }}ms</span>
              </span>
              <span v-else>写好后点提交</span>
            </div>
            <button class="btn-primary" :disabled="dailyBusy" @click="submitDaily">
              {{ dailyBusy ? '判题中…' : '提交' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 判题结果 -->
      <div v-if="dailyResult" class="card mt-4">
        <div class="mb-2 text-sm font-semibold text-ink-900">用例结果</div>
        <div class="space-y-2">
          <div v-for="r in dailyResult.results" :key="r.index"
               class="rounded border px-3 py-2 text-xs"
               :class="r.verdict === 'accepted'
                 ? 'border-emerald-200 bg-emerald-50'
                 : 'border-rose-200 bg-rose-50'">
            <div class="mb-1 font-medium" :class="verdictClass(r.verdict)">
              用例 {{ r.index }} · {{ verdictLabel(r.verdict) }}
            </div>
            <div class="grid gap-1 font-mono sm:grid-cols-2">
              <div><span class="text-ink-400">输入：</span>{{ r.stdin || '(空)' }}</div>
              <div><span class="text-ink-400">期望：</span>{{ r.expected }}</div>
              <div class="sm:col-span-2"><span class="text-ink-400">实际：</span>{{ r.actual || '(空)' }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 历史 -->
      <div v-if="dailyHistory" class="card mt-4">
        <div class="mb-3 flex items-center justify-between">
          <div class="text-sm font-semibold text-ink-900">打卡历史</div>
          <div class="text-xs text-ink-500">
            已过 {{ dailyHistory.solved }} / {{ dailyHistory.total }} 题（{{ dailyHistory.rate }}%）
          </div>
        </div>
        <div v-if="!dailyHistory.items.length" class="py-4 text-center text-sm text-ink-400">
          还没有记录，今天开始吧
        </div>
        <div v-else class="space-y-1.5">
          <div v-for="h in dailyHistory.items" :key="h.id"
               class="flex items-center gap-3 rounded border border-ink-100 px-3 py-2 text-sm">
            <span class="w-20 shrink-0 text-xs text-ink-400">{{ String(h.date).slice(5) }}</span>
            <span class="min-w-0 flex-1 truncate text-ink-800">{{ h.title }}</span>
            <span class="shrink-0 text-xs" :class="h.passed ? 'text-emerald-600' : 'text-rose-600'">
              {{ h.passed ? '通过' : `${h.passed_count}/${h.total_count}` }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 成就 ============ -->
    <div v-else-if="tab === 'achievement'">
      <div v-if="!achievements" class="card py-12 text-center text-ink-400">加载中…</div>
      <template v-else>
        <div class="card mb-4 flex items-center justify-between">
          <div>
            <div class="text-sm text-ink-500">已解锁徽章</div>
            <div class="mt-1 text-3xl font-semibold text-ink-900">
              {{ achievements.unlocked_count }}
              <span class="text-base font-normal text-ink-400">/ {{ achievements.total_count }}</span>
            </div>
          </div>
          <div class="text-right text-xs text-ink-500">
            <div>累计执行 {{ achievements.metrics.run_count }} 次</div>
            <div>覆盖 {{ achievements.metrics.language_count }} 种语言</div>
          </div>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="a in achievements.items"
            :key="a.id"
            class="card border bg-gradient-to-br"
            :class="a.unlocked
              ? (tierStyle[a.tier] || tierStyle.bronze)
              : 'border-ink-200 from-ink-50 to-white opacity-70'"
          >
            <div class="flex items-start gap-3">
              <div class="text-3xl" :class="a.unlocked ? '' : 'grayscale'">{{ a.icon }}</div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="font-semibold text-ink-900">{{ a.name }}</span>
                  <span v-if="a.unlocked" class="text-xs text-emerald-600">✓</span>
                </div>
                <div class="mt-0.5 text-xs text-ink-500">{{ a.description }}</div>
                <div v-if="!a.unlocked" class="mt-2">
                  <div class="h-1.5 overflow-hidden rounded-full bg-ink-200">
                    <div class="h-full rounded-full bg-brand-500" :style="{ width: a.percent + '%' }" />
                  </div>
                  <div class="mt-1 text-[11px] text-ink-400">
                    进度 {{ a.progress }} / {{ a.target }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ============ 错题本 ============ -->
    <div v-else-if="tab === 'wrong'">
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <button
          v-for="f in [{ k: 'unmastered', l: '待掌握' }, { k: 'mastered', l: '已掌握' }, { k: '', l: '全部' }]"
          :key="f.k"
          class="rounded-lg px-3 py-1.5 text-sm transition"
          :class="wrongFilter === f.k ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-600 hover:bg-ink-200'"
          @click="wrongFilter = f.k; loadWrong()"
        >
          {{ f.l }}
        </button>
        <div v-if="wrong" class="ml-auto text-xs text-ink-500">
          待掌握 {{ wrong.unmastered }} · 已掌握 {{ wrong.mastered }} · 共 {{ wrong.total }}
        </div>
      </div>

      <div v-if="!wrong" class="card py-12 text-center text-ink-400">加载中…</div>
      <div v-else-if="!wrong.items.length" class="card py-12 text-center text-ink-400">
        这里空空的，说明你还没翻过车（或者翻完就掌握了）
      </div>
      <div v-else class="space-y-2.5">
        <div v-for="w in wrong.items" :key="w.id" class="card">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="font-medium text-ink-900">{{ w.title }}</span>
                <span v-if="w.mastered" class="tag bg-emerald-100 text-emerald-700">已掌握</span>
                <span class="tag">{{ w.language }}</span>
                <span class="tag">{{ { judge: '判题', daily: '每日一题', arena: '挑战', manual: '手动' }[w.source] || w.source }}</span>
              </div>
              <div v-if="w.reason" class="mt-1 text-xs text-rose-600">{{ w.reason }}</div>
              <div class="mt-1 text-xs text-ink-400">
                复习 {{ w.review_count }} 次
                <span v-if="w.last_reviewed_at"> · 上次 {{ formatTime(w.last_reviewed_at) }}</span>
              </div>
            </div>
            <div class="flex shrink-0 gap-1.5">
              <button class="btn-outline h-7 px-2 text-xs" @click="reviewWrong(w, false)">复习一次</button>
              <button
                v-if="!w.mastered"
                class="btn-outline h-7 px-2 text-xs"
                @click="reviewWrong(w, true)"
              >标记掌握</button>
              <button class="btn-ghost h-7 px-2 text-xs text-rose-600" @click="removeWrong(w)">移除</button>
            </div>
          </div>
          <!-- 失败用例 -->
          <div v-if="w.failed_cases && w.failed_cases.length" class="mt-2 space-y-1">
            <div v-for="c in w.failed_cases" :key="c.index"
                 class="rounded bg-ink-50 px-2.5 py-1.5 font-mono text-[11px] text-ink-600">
              <span class="text-ink-400">用例{{ c.index }}：</span>
              输入 <span class="text-ink-800">{{ c.stdin || '(空)' }}</span>
              → 期望 <span class="text-emerald-700">{{ c.expected }}</span>
              ，实际 <span class="text-rose-600">{{ c.actual || '(空)' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 学习路径 ============ -->
    <div v-else-if="tab === 'path'">
      <div class="mb-3 flex items-center justify-between">
        <div class="text-sm text-ink-500">
          照着走就行，不用自己纠结先学啥
        </div>
        <button class="btn-primary" @click="genOpen = true">＋ 生成路径</button>
      </div>

      <div v-if="!paths" class="card py-12 text-center text-ink-400">加载中…</div>
      <template v-else>
        <div v-if="!paths.items.length" class="card mb-4 py-12 text-center text-ink-400">
          还没有学习路径，点右上角生成一份
        </div>

        <div class="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="p in paths.items"
            :key="p.id"
            class="card cursor-pointer transition hover:shadow-md"
            :class="pathDetail && pathDetail.id === p.id ? 'ring-2 ring-brand-400' : ''"
            @click="openPath(p.id)"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="truncate font-medium text-ink-900">{{ p.title }}</div>
                <div class="mt-0.5 text-xs text-ink-500">
                  {{ p.language }} · {{ p.stage_count }} 阶段 · {{ p.source === 'llm' ? 'AI 生成' : '模板生成' }}
                </div>
              </div>
              <button class="btn-ghost h-6 shrink-0 px-1.5 text-xs text-rose-600"
                      @click.stop="deletePath(p)">删除</button>
            </div>
            <div class="mt-3">
              <div class="mb-1 flex justify-between text-[11px] text-ink-500">
                <span>{{ p.done_items }} / {{ p.total_items }} 项</span>
                <span>{{ p.percent }}%</span>
              </div>
              <div class="h-2 overflow-hidden rounded-full bg-ink-100">
                <div class="h-full rounded-full bg-brand-500 transition-all"
                     :style="{ width: p.percent + '%' }" />
              </div>
            </div>
          </div>
        </div>

        <!-- 路径详情 -->
        <div v-if="pathDetail" class="card">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div class="text-base font-semibold text-ink-900">{{ pathDetail.title }}</div>
              <div class="mt-0.5 text-xs text-ink-500">
                {{ pathDetail.language }} · {{ pathDetail.level }}
                <span v-if="pathDetail.goal"> · 目标：{{ pathDetail.goal }}</span>
                · 总计约 {{ pathDetail.stages.reduce((s, x) => s + (x.hours || 0), 0) }} 小时
              </div>
            </div>
            <div class="text-right">
              <div class="text-sm font-medium text-ink-900">{{ pathDetail.percent }}%</div>
              <div class="text-[11px] text-ink-400">
                {{ pathDetail.done_items }} / {{ pathDetail.total_items }}
              </div>
            </div>
          </div>

          <div class="space-y-3">
            <div v-for="(st, si) in pathDetail.stages" :key="si"
                 class="rounded-lg border border-ink-200 p-3">
              <div class="mb-2 flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <span class="flex h-6 w-6 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
                    {{ si + 1 }}
                  </span>
                  <span class="font-medium text-ink-900">{{ st.stage }}</span>
                </div>
                <span class="text-xs text-ink-400">约 {{ st.hours || 0 }} 小时</span>
              </div>
              <div class="space-y-1">
                <label
                  v-for="(item, ii) in (st.items || [])"
                  :key="ii"
                  class="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm transition hover:bg-ink-50"
                >
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5"
                    :checked="isDone(si, ii)"
                    @change="tickItem(si, ii)"
                  />
                  <span :class="isDone(si, ii) ? 'text-ink-400 line-through' : 'text-ink-700'">{{ item }}</span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ============ 竞技场 ============ -->
    <div v-else-if="tab === 'arena'">
      <div v-if="!arena" class="card py-12 text-center text-ink-400">加载中…</div>
      <template v-else>
        <!-- 我的战力 -->
        <div class="card mb-4">
          <div class="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div class="text-xs text-ink-500">战力</div>
              <div class="text-3xl font-semibold text-brand-600">{{ arena.me.power }}</div>
            </div>
            <div class="flex gap-6 text-sm">
              <div class="text-center">
                <div class="text-xs text-ink-500">执行</div>
                <div class="font-semibold text-ink-900">{{ arena.me.run_count }}</div>
              </div>
              <div class="text-center">
                <div class="text-xs text-ink-500">判题通过</div>
                <div class="font-semibold text-ink-900">{{ arena.me.accepted_count }}</div>
              </div>
              <div class="text-center">
                <div class="text-xs text-ink-500">每日一题</div>
                <div class="font-semibold text-ink-900">{{ arena.me.daily_solved }}</div>
              </div>
              <div class="text-center">
                <div class="text-xs text-ink-500">连续打卡</div>
                <div class="font-semibold text-ink-900">{{ arena.me.streak }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 榜单 -->
        <div class="mb-4 grid gap-3 md:grid-cols-3">
          <div v-for="(rows, key) in arena.boards" :key="key" class="card">
            <div class="mb-2 text-sm font-semibold text-ink-900">
              {{ { runners: '🏃 执行榜', solvers: '✅ 解题榜', daily: '📅 打卡榜' }[key] }}
            </div>
            <div v-if="!rows.length" class="py-4 text-center text-xs text-ink-400">暂无数据</div>
            <div v-else class="space-y-1">
              <div
                v-for="r in rows"
                :key="r.rank"
                class="flex items-center gap-2 rounded px-2 py-1 text-sm"
                :class="r.is_me ? 'bg-brand-50 font-medium' : ''"
              >
                <span class="w-6 text-xs"
                      :class="r.rank <= 3 ? 'text-amber-600 font-semibold' : 'text-ink-400'">
                  {{ r.rank }}
                </span>
                <span class="min-w-0 flex-1 truncate text-ink-800">
                  {{ r.username }}<span v-if="r.is_me" class="text-brand-600">（我）</span>
                </span>
                <span class="text-xs text-ink-500">{{ r.value }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 随机挑战 -->
        <div class="card">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div class="text-sm font-semibold text-ink-900">随机挑战</div>
            <div class="flex gap-1.5">
              <button class="btn-outline h-7 px-2 text-xs" @click="drawChallenge('')">抽一题</button>
              <button class="btn-ghost h-7 px-2 text-xs" @click="drawChallenge('easy')">简单</button>
              <button class="btn-ghost h-7 px-2 text-xs" @click="drawChallenge('medium')">中等</button>
            </div>
          </div>

          <div v-if="!challenge" class="py-8 text-center text-sm text-ink-400">
            点「抽一题」开始挑战
          </div>
          <template v-else>
            <div class="mb-3 rounded-lg bg-ink-50 p-3">
              <div class="mb-1 flex items-center gap-2">
                <span class="font-medium text-ink-900">{{ challenge.title }}</span>
                <span class="tag">{{ challenge.difficulty }}</span>
                <span class="tag">{{ challenge.language }}</span>
              </div>
              <pre class="whitespace-pre-wrap font-sans text-sm text-ink-700">{{ challenge.description }}</pre>
            </div>

            <div class="overflow-hidden rounded-lg border border-ink-200">
              <CodeEditor v-model="arenaCode" :language="challenge.language" height="34vh" />
            </div>

            <div class="mt-3 flex items-center justify-between">
              <div v-if="arenaResult" class="text-xs">
                <span :class="verdictClass(arenaResult.verdict)" class="font-medium">
                  {{ verdictLabel(arenaResult.verdict) }} · {{ arenaResult.passed }}/{{ arenaResult.total }}
                </span>
              </div>
              <div v-else class="text-xs text-ink-400">共 {{ challenge.case_count }} 个用例</div>
              <button class="btn-primary" :disabled="arenaBusy" @click="submitChallenge">
                {{ arenaBusy ? '判题中…' : '提交挑战' }}
              </button>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- 生成路径模态框 -->
    <Modal :show="genOpen" title="生成学习路径" @close="genOpen = false">
      <div class="space-y-3">
        <div>
          <label class="mb-1 block text-sm text-ink-700">目标语言</label>
          <select v-model="genForm.language" class="input w-full">
            <option value="python">Python</option>
            <option value="javascript">JavaScript</option>
            <option value="typescript">TypeScript</option>
            <option value="java">Java</option>
            <option value="go">Go</option>
            <option value="rust">Rust</option>
            <option value="cpp">C++</option>
            <option value="c">C</option>
            <option value="php">PHP</option>
            <option value="ruby">Ruby</option>
            <option value="lua">Lua</option>
            <option value="sql">SQL</option>
            <option value="bash">Bash</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-sm text-ink-700">当前水平</label>
          <select v-model="genForm.level" class="input w-full">
            <option value="beginner">零基础</option>
            <option value="intermediate">有一定基础</option>
            <option value="advanced">进阶提升</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-sm text-ink-700">学习目标（可选）</label>
          <input v-model="genForm.goal" class="input w-full" placeholder="例：能做后端接口开发" />
        </div>
        <p class="text-xs text-ink-400">
          有配 LLM 就用 AI 生成，没配就用内置模板——两种都能用。
        </p>
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-outline" @click="genOpen = false">取消</button>
        <button class="btn-primary" :disabled="genBusy" @click="generatePath">
          {{ genBusy ? '生成中…' : '生成' }}
        </button>
      </div>
    </Modal>
  </div>
</template>
