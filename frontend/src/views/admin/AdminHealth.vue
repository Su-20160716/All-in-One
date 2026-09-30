<template>
  <div class="space-y-4">
    <!-- F627 后端健康卡 -->
    <div class="card p-4">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">后端健康卡</h3>
        <div class="flex items-center gap-2">
          <span class="tag" :class="health.status === 'ok' ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
            {{ health.status === 'ok' ? '正常' : health.status || '未知' }}
          </span>
          <button class="btn-outline text-[12px]" @click="load">刷新</button>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <div class="rounded-control bg-ink-50 p-3">
          <div class="text-[11px] text-ink-400">数据库</div>
          <div class="text-[15px] font-semibold">{{ health.db?.ok ? '连接正常' : '连接异常' }}</div>
          <div class="text-[11px] text-ink-400">{{ health.db?.engine || '-' }} · {{ health.db?.latency_ms ?? '-' }} ms</div>
        </div>
        <div class="rounded-control bg-ink-50 p-3">
          <div class="text-[11px] text-ink-400">数据表</div>
          <div class="text-[15px] font-semibold">{{ health.tables?.count ?? 0 }} 张</div>
          <div class="text-[11px] text-ink-400">迁移记录 {{ health.migration?.count ?? 0 }} 条</div>
        </div>
        <div class="rounded-control bg-ink-50 p-3">
          <div class="text-[11px] text-ink-400">最新迁移</div>
          <div class="truncate text-[13px] font-semibold">{{ health.migration?.latest?.app || '-' }}</div>
          <div class="truncate text-[11px] text-ink-400">{{ health.migration?.latest?.name || '-' }}</div>
        </div>
        <div class="rounded-control bg-ink-50 p-3">
          <div class="text-[11px] text-ink-400">存储占用</div>
          <div class="text-[15px] font-semibold">{{ health.storage?.total_text || '0 B' }}</div>
          <div class="text-[11px] text-ink-400">库 {{ health.storage?.db_text || '-' }} / 媒体 {{ health.storage?.media_text || '-' }}</div>
        </div>
      </div>
      <div class="mt-2 flex flex-wrap gap-3 text-[11px] text-ink-400">
        <span>版本 {{ health.runtime?.version || '-' }}</span>
        <span>Python {{ health.runtime?.python || '-' }}</span>
        <span>Django {{ health.runtime?.django || '-' }}</span>
        <span>DEBUG {{ health.runtime?.debug }}</span>
        <span>已运行 {{ health.runtime?.uptime_text || '-' }}</span>
        <span>检查于 {{ (health.checked_at || '').slice(11, 19) }}</span>
      </div>
    </div>

    <!-- F635 数据表行数 / 体积统计 -->
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">数据表行数 / 体积统计</h3>
        <div class="flex items-center gap-2 text-[11px] text-ink-400">
          <span>表 {{ stats.total_tables ?? 0 }} 张 · 行 {{ stats.total_rows ?? 0 }} · 库 {{ stats.db_text || '-' }}</span>
          <span v-if="stats.size_source === 'estimate'" class="tag bg-amber-50 text-amber-600">体积为估算</span>
          <button class="btn-outline text-[12px]" @click="loadStats">刷新</button>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[560px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr><th class="th">表</th><th class="th">应用</th><th class="th text-right">行数</th><th class="th text-right">体积</th><th class="th w-40">占比</th></tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="t in stats.tables || []" :key="t.table">
              <td class="td font-mono text-[11px]">{{ t.table }}</td>
              <td class="td text-[12px] text-ink-500">{{ t.app }}</td>
              <td class="td text-right">{{ t.rows }}</td>
              <td class="td text-right text-ink-500">{{ t.bytes_text }}</td>
              <td class="td">
                <div class="h-1.5 w-full rounded-full bg-ink-100">
                  <div class="h-1.5 rounded-full bg-brand-400" :style="{ width: Math.min(100, t.pct) + '%' }"></div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!(stats.tables || []).length" class="py-8 text-center text-[12px] text-ink-400">暂无数据</div>
      </div>
      <div v-if="stats.truncated" class="mt-1 text-[11px] text-ink-400">仅展示体积/行数前 60 张表</div>
    </div>

    <!-- F642 关于页（管理端视图） -->
    <div class="card p-4">
      <h3 class="mb-2 text-[14px] font-semibold">关于平台</h3>
      <div class="grid gap-2 text-[12px] sm:grid-cols-2 lg:grid-cols-3">
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-400">版本</span><span class="font-medium">{{ about.version || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-400">最近提交</span>
          <span v-if="about.git?.available" class="font-mono font-medium">{{ about.git.hash }} · {{ about.git.date }}</span>
          <span v-else class="text-ink-400">{{ about.git?.reason || '不可用' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-400">运行时长</span><span class="font-medium">{{ about.runtime?.uptime_text || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-400">Python / Django</span>
          <span class="font-medium">{{ about.runtime?.python || '-' }} / {{ about.runtime?.django || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-400">数据库</span><span class="font-medium">{{ about.database?.engine || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-400">服务时间</span>
          <span class="font-medium">{{ (about.runtime?.server_time || '').slice(0, 19).replace('T', ' ') }}</span>
        </div>
      </div>
      <div v-if="about.git?.available" class="mt-2 truncate text-[11px] text-ink-400">{{ about.git.subject }}</div>
      <div class="mt-2 flex flex-wrap gap-2 text-[11px]">
        <span v-for="(v, k) in about.flags || {}" :key="k" class="tag" :class="v ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
          {{ k }}: {{ v }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { corexApi } from '../../api/corex'

const health = ref({})
const stats = ref({})
const about = ref({})

async function load() {
  try { health.value = await corexApi.healthCard() } catch (e) { health.value = { status: 'unknown' } }
}
async function loadStats() {
  try { stats.value = await corexApi.tableStats({ top: 60 }) } catch (e) { stats.value = {} }
}
async function loadAbout() {
  try { about.value = await corexApi.about() } catch (e) { about.value = {} }
}
onMounted(() => { load(); loadStats(); loadAbout() })
</script>
