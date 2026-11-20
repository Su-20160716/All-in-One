<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="input flex items-center justify-between text-left"
      :aria-expanded="open"
      @click="toggle"
    >
      <span :class="modelValue ? 'text-ink-800' : 'text-ink-400'">{{ modelValue || '请选择出生日期' }}</span>
      <svg class="h-4 w-4 shrink-0 text-ink-400" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <rect x="3" y="4.5" width="14" height="12" rx="2.5" stroke="currentColor" stroke-width="1.5" />
        <path d="M3 8.5h14M7 3v3M13 3v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
      </svg>
    </button>

    <Transition name="dp">
      <div v-if="open" class="dp-panel" @click.stop>
        <div class="dp-head">
          <span>{{ tmp.year }} 年</span>
          <span>{{ tmp.month }} 月</span>
          <span>{{ tmp.day }} 日</span>
        </div>
        <div class="relative">
          <div class="dp-highlight"></div>
          <div class="grid grid-cols-3 gap-1">
            <div ref="yearCol" class="dp-wheel" @scroll.passive="onScroll('year')">
              <div class="dp-pad"></div>
              <button
                v-for="y in years"
                :key="y"
                type="button"
                class="dp-item"
                :class="{ 'dp-item--on': y === tmp.year }"
                @click="pick('year', y)"
              >{{ y }} 年</button>
              <div class="dp-pad"></div>
            </div>
            <div ref="monthCol" class="dp-wheel" @scroll.passive="onScroll('month')">
              <div class="dp-pad"></div>
              <button
                v-for="m in months"
                :key="m"
                type="button"
                class="dp-item"
                :class="{ 'dp-item--on': m === tmp.month }"
                @click="pick('month', m)"
              >{{ m }} 月</button>
              <div class="dp-pad"></div>
            </div>
            <div ref="dayCol" class="dp-wheel" @scroll.passive="onScroll('day')">
              <div class="dp-pad"></div>
              <button
                v-for="d in days"
                :key="d"
                type="button"
                class="dp-item"
                :class="{ 'dp-item--on': d === tmp.day }"
                @click="pick('day', d)"
              >{{ d }} 日</button>
              <div class="dp-pad"></div>
            </div>
          </div>
        </div>
        <div class="mt-2 flex items-center justify-end gap-2">
          <button type="button" class="rounded-control px-3 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50" @click="open = false">取消</button>
          <button type="button" class="btn-primary px-4 py-1.5 text-[12px]" @click="confirm">确定</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const ITEM_H = 36
const currentYear = new Date().getFullYear()
const years = Array.from({ length: currentYear - 1900 + 1 }, (_, i) => currentYear - i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const open = ref(false)
const root = ref(null)
const yearCol = ref(null)
const monthCol = ref(null)
const dayCol = ref(null)
const cols = { year: yearCol, month: monthCol, day: dayCol }

const tmp = reactive({ year: 2000, month: 1, day: 1 })
const maxDay = computed(() => new Date(tmp.year, tmp.month, 0).getDate())
const days = computed(() => Array.from({ length: maxDay.value }, (_, i) => i + 1))

const timers = {}

function parseValue() {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(props.modelValue || '')
  if (!m) return null
  const year = Number(m[1])
  const month = Number(m[2])
  const day = Number(m[3])
  if (year < 1900 || year > currentYear || month < 1 || month > 12 || day < 1 || day > 31) return null
  return { year, month, day }
}

function scrollCol(unit, index, smooth = false) {
  const el = cols[unit].value
  if (!el || index < 0) return
  const top = index * ITEM_H
  if (smooth && el.scrollTo) el.scrollTo({ top, behavior: 'smooth' })
  else el.scrollTop = top
}

function scrollAll() {
  scrollCol('year', years.indexOf(tmp.year))
  scrollCol('month', tmp.month - 1)
  scrollCol('day', tmp.day - 1)
}

function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  const parsed = parseValue()
  const init = parsed || { year: 2000, month: 1, day: 1 }
  tmp.year = init.year
  tmp.month = init.month
  tmp.day = Math.min(init.day, new Date(init.year, init.month, 0).getDate())
  open.value = true
  nextTick(scrollAll)
}

function clampDay() {
  if (tmp.day > maxDay.value) {
    tmp.day = maxDay.value
    nextTick(() => scrollCol('day', tmp.day - 1))
  }
}

// 滚动停止后吸附到最近一项，实现「滚动选择」
function onScroll(unit) {
  if (!open.value) return
  clearTimeout(timers[unit])
  timers[unit] = setTimeout(() => {
    const el = cols[unit].value
    if (!el) return
    const index = Math.round(el.scrollTop / ITEM_H)
    if (unit === 'year') {
      const y = years[Math.min(Math.max(index, 0), years.length - 1)]
      if (y !== tmp.year) {
        tmp.year = y
        clampDay()
      }
    } else if (unit === 'month') {
      const m = Math.min(Math.max(index + 1, 1), 12)
      if (m !== tmp.month) {
        tmp.month = m
        clampDay()
      }
    } else {
      const d = Math.min(Math.max(index + 1, 1), maxDay.value)
      tmp.day = d
    }
  }, 120)
}

function pick(unit, value) {
  if (unit === 'year') {
    tmp.year = value
    clampDay()
    scrollCol('year', years.indexOf(value), true)
  } else if (unit === 'month') {
    tmp.month = value
    clampDay()
    scrollCol('month', value - 1, true)
  } else {
    tmp.day = value
    scrollCol('day', value - 1, true)
  }
}

function confirm() {
  const pad = (n) => String(n).padStart(2, '0')
  emit('update:modelValue', `${tmp.year}-${pad(tmp.month)}-${pad(tmp.day)}`)
  open.value = false
}

function onDocClick(e) {
  if (open.value && root.value && !root.value.contains(e.target)) open.value = false
}

function onKeydown(e) {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.dp-panel {
  position: absolute;
  z-index: 40;
  margin-top: 0.3rem;
  width: 100%;
  min-width: 264px;
  padding: 0.6rem;
  border-radius: var(--radius-card);
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  box-shadow: var(--shadow-pop);
}

.dp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0.35rem 0.4rem;
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-600);
}

.dp-highlight {
  position: absolute;
  top: 72px;
  left: 0;
  right: 0;
  height: 36px;
  border-radius: var(--radius-control);
  border-top: 1px solid color-mix(in srgb, var(--brand-500) 35%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--brand-500) 35%, transparent);
  background: color-mix(in srgb, var(--brand-500) 6%, transparent);
  pointer-events: none;
}

.dp-wheel {
  height: 180px;
  overflow-y: auto;
  scroll-snap-type: y mandatory;
  scrollbar-width: none;
  overscroll-behavior: contain;
}

.dp-wheel::-webkit-scrollbar {
  display: none;
}

.dp-pad {
  height: 72px;
}

.dp-item {
  display: block;
  width: 100%;
  height: 36px;
  scroll-snap-align: center;
  font-size: 13px;
  color: var(--color-ink-500);
  transition: color 0.15s ease;
}

.dp-item:hover {
  color: var(--color-ink-700);
}

.dp-item--on {
  color: var(--brand-600);
  font-weight: 600;
}

.dp-enter-active,
.dp-leave-active {
  transition: opacity 0.16s ease, transform 0.16s var(--ease-spring);
}

.dp-enter-from,
.dp-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
