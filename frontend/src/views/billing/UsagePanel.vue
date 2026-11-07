<template>
  <section class="space-y-3">
    <!-- 查询与上报 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <label class="w-52">
        <span class="mb-1 block text-[11px] text-ink-400">订阅</span>
        <select v-model="subscriptionId" class="input">
          <option value="">全部订阅</option>
          <option v-for="s in subscriptions" :key="s.id" :value="s.id">
            #{{ s.id }} · {{ s.customer_name }}
          </option>
        </select>
      </label>
      <label class="w-44">
        <span class="mb-1 block text-[11px] text-ink-400">计量项</span>
        <select v-model="meterId" class="input">
          <option value="">全部计量项</option>
          <option v-for="m in meters" :key="m.id" :value="m.id">{{ m.name }}（{{ m.code }}）</option>
        </select>
      </label>
      <label class="w-32">
        <span class="mb-1 block text-[11px] text-ink-400">开票状态</span>
        <select v-model="invoiced" class="input">
          <option value="">全部</option>
          <option value="false">未开票</option>
          <option value="true">已开票</option>
        </select>
      </label>
      <label class="w-36">
        <span class="mb-1 block text-[11px] text-ink-400">起始日期</span>
        <input v-model="startDate" class="input" type="date" />
      </label>
      <label class="w-36">
        <span class="mb-1 block text-[11px] text-ink-400">截止日期</span>
        <input v-model="endDate" class="input" type="date" />
      </label>
      <label class="w-24">
        <span class="mb-1 block text-[11px] text-ink-400">每页</span>
        <select class="input" :value="pageSize" @change="changePageSize($event)">
          <option v-for="n in [10, 20, 50]" :key="n" :value="n">{{ n }} 条</option>
        </select>
      </label>
      <button class="btn-primary" @click="searchNow">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="loadList">刷新</button>
      <span class="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span>共 {{ formatNumber(count) }} 条流水</span>
        <button class="btn-outline px-2 py-1 text-[12px]" @click="openReport">上报用量</button>
        <button class="btn-primary px-3 py-1 text-[12px]" @click="openBatch">批量上报</button>
      </span>
    </div>

    <!-- 账期汇总 -->
    <SectionCard title="账期用量汇总" subtitle="按订阅与账期汇总包含量、超量与应计金额，直接回答账单里为什么有这条费用">
      <template #actions>
        <span class="tag">合计 {{ formatMoney(summary.total_amount) }}</span>
        <span class="tag">{{ formatNumber(summary.meter_count) }} 个计量项</span>
        <button class="btn-ghost px-2 text-[12px]" :disabled="summaryLoading" @click="loadSummary">
          {{ summaryLoading ? '加载中…' : '刷新汇总' }}
        </button>
      </template>

      <div class="mb-3 grid gap-2 sm:grid-cols-4">
        <label class="block text-[12px] text-ink-600 sm:col-span-2">
          <span class="mb-1 block text-[11px] text-ink-400">汇总订阅</span>
          <select v-model="summarySubscriptionId" class="input" @change="onSummarySubscriptionChange">
            <option value="">请选择订阅</option>
            <option v-for="s in subscriptions" :key="s.id" :value="s.id">
              #{{ s.id }} · {{ s.customer_name }} · {{ s.plan_name }}
            </option>
          </select>
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block text-[11px] text-ink-400">账期起始</span>
          <input v-model="summaryStart" class="input" type="date" />
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block text-[11px] text-ink-400">账期结束</span>
          <input v-model="summaryEnd" class="input" type="date" />
        </label>
      </div>

      <div v-if="summaryError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ summaryError }}</span>
        <button class="font-medium" @click="loadSummary">重试</button>
      </div>
      <div v-else-if="summaryLoading && !(summary.items || []).length" class="py-8 text-center text-[12px] text-ink-400">汇总加载中…</div>
      <div v-else-if="!summarySubscriptionId" class="py-8 text-center text-[12px] text-ink-400">
        选择一个订阅后查看账期用量汇总
      </div>
      <div v-else-if="!(summary.items || []).length" class="py-8 text-center text-[12px] text-ink-400">
        当前账期还没有用量记录，可先上报单条或批量用量
      </div>
      <template v-else>
        <div class="mb-3 grid gap-2 sm:grid-cols-4">
          <div class="rounded-control bg-ink-50 px-3 py-2">
            <div class="text-[11px] text-ink-400">账期</div>
            <div class="mt-0.5 text-[12px] font-medium text-ink-800">
              {{ summary.period_start || '—' }} ~ {{ summary.period_end || '—' }}
            </div>
          </div>
          <div class="rounded-control bg-brand-50 px-3 py-2">
            <div class="text-[11px] text-brand-600">计量项</div>
            <div class="mt-0.5 text-[16px] font-semibold text-brand-700">{{ formatNumber(summary.meter_count) }}</div>
          </div>
          <div class="rounded-control bg-ink-50 px-3 py-2">
            <div class="text-[11px] text-ink-400">总用量</div>
            <div class="mt-0.5 text-[16px] font-semibold text-ink-800">{{ summary.total_quantity }}</div>
          </div>
          <div class="rounded-control bg-emerald-50 px-3 py-2">
            <div class="text-[11px] text-emerald-600">应计金额</div>
            <div class="mt-0.5 text-[16px] font-semibold text-emerald-700">{{ formatMoney(summary.total_amount) }}</div>
          </div>
        </div>
        <div class="overflow-x-auto rounded-control border border-ink-100">
          <table class="w-full min-w-[760px]">
            <thead class="bg-ink-50/60">
              <tr>
                <th class="th">计量项</th>
                <th class="th">聚合</th>
                <th class="th">记录</th>
                <th class="th">用量</th>
                <th class="th">包含量</th>
                <th class="th">超量</th>
                <th class="th">超量单价</th>
                <th class="th">金额</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in summary.items" :key="row.meter_id">
                <td class="td text-[12px]">
                  {{ row.meter_name }}
                  <span class="font-mono text-[11px] text-ink-400">{{ row.meter_code }}</span>
                </td>
                <td class="td text-[12px] text-ink-500">{{ row.aggregation }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.records }}</td>
                <td class="td text-[12px]">{{ row.quantity }} {{ row.unit }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.included }}</td>
                <td class="td text-[12px] text-amber-600">{{ row.billable }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.unit_amount }}</td>
                <td class="td text-[12px] font-medium">{{ formatMoney(row.amount) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </SectionCard>

    <!-- 趋势与流水 -->
    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard class="lg:col-span-2" title="用量趋势" subtitle="按发生日期聚合当前订阅的用量流水（最多读取最近 200 条）">
        <template #actions>
          <span class="tag">{{ trendRows.length }} 天</span>
          <button class="btn-ghost px-2 text-[12px]" :disabled="trendLoading" @click="loadTrend">
            {{ trendLoading ? '加载中…' : '刷新' }}
          </button>
        </template>
        <div v-if="!summarySubscriptionId" class="grid h-[200px] place-items-center text-[12px] text-ink-400">
          选择订阅后展示用量趋势
        </div>
        <div v-else-if="trendError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ trendError }}
        </div>
        <div v-else-if="trendLoading && !trendRows.length" class="grid h-[200px] place-items-center text-[12px] text-ink-400">
          趋势加载中…
        </div>
        <BarChart
          v-else
          :data="trendBars"
          :height="200"
          color="var(--brand-400)"
          :format="formatQuantity"
          empty-text="当前订阅还没有用量流水"
        />
        <template #footer>
          <span>峰值 {{ trendPeak }} · 总用量 {{ trendTotal }}</span>
        </template>
      </SectionCard>

      <SectionCard title="上报提示" subtitle="接入方重试很常见，幂等键保证同一次上报只计一次">
        <ul class="space-y-2 text-[12px] text-ink-600">
          <li class="rounded-control bg-ink-50 px-3 py-2">
            单条上报可指定计量项 ID 或编码；重复幂等键会返回原记录并标记 created=false。
          </li>
          <li class="rounded-control bg-ink-50 px-3 py-2">
            批量上报整体在一个事务内执行，单行失败会整体回滚，最多 500 行。
          </li>
          <li class="rounded-control bg-ink-50 px-3 py-2">
            已计入发票的流水会标记 invoiced=true，重新生成账单时不会重复计费。
          </li>
        </ul>
        <template #footer>
          <div class="flex flex-wrap gap-2">
            <button class="text-brand-600" @click="openReport">上报一条</button>
            <button class="text-brand-600" @click="openBatch">批量上报</button>
            <button class="ml-auto text-brand-600" @click="focusMeters">维护计量项</button>
          </div>
        </template>
      </SectionCard>
    </div>

    <div class="card overflow-hidden">
      <div class="flex flex-wrap items-center gap-2 border-b border-ink-100 px-3 py-2">
        <span class="text-[13px] font-medium text-ink-700">用量流水</span>
        <span class="tag">{{ formatNumber(count) }} 条</span>
        <span class="ml-auto text-[11px] text-ink-400">
          {{ subscriptionId ? `订阅 #${subscriptionId}` : '全部订阅' }}
          {{ meterId ? ` · 计量项 #${meterId}` : '' }}
        </span>
      </div>

      <div v-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div
        v-else-if="error"
        class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="font-medium" @click="loadList">重试</button>
      </div>
      <div v-else-if="unavailable && !items.length" class="py-12 text-center text-[12px] text-amber-700">
        {{ unavailable }}。用量端点恢复后重新刷新即可加载。
      </div>
      <div v-else-if="!items.length" class="py-12 text-center text-[12px] text-ink-400">
        {{ subscriptionId || meterId || startDate || endDate ? '没有匹配的用量流水，调整筛选条件后重试' : '还没有用量流水，先上报一条或批量上报' }}
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[980px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">发生时间</th>
              <th class="th">订阅</th>
              <th class="th">计量项</th>
              <th class="th">数量</th>
              <th class="th">来源</th>
              <th class="th">幂等键</th>
              <th class="th">开票</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/50">
              <td class="td text-[12px] text-ink-500">{{ formatDate(row.occurred_at, true) }}</td>
              <td class="td text-[12px]">#{{ row.subscription_id }}</td>
              <td class="td text-[12px]">
                {{ row.meter_name || '—' }}
                <span class="font-mono text-[11px] text-ink-400">{{ row.meter_code }}</span>
              </td>
              <td class="td text-[12px]">{{ row.quantity }} {{ row.unit }}</td>
              <td class="td text-[12px] text-ink-500">{{ row.source || '—' }}</td>
              <td class="td max-w-[200px] truncate font-mono text-[11px] text-ink-400">{{ row.idempotency_key || '—' }}</td>
              <td class="td">
                <span class="tag" :class="row.invoiced ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                  {{ row.invoiced ? '已计入' : '未开票' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
        <span>第 {{ page }} / {{ pages }} 页 · 每页 {{ pageSize }} 条</span>
        <span class="flex items-center gap-1">
          <button class="btn-ghost px-2 text-[12px]" :disabled="page <= 1 || loading" @click="gotoPage(page - 1)">上一页</button>
          <button
            v-for="p in pageButtons"
            :key="p"
            class="rounded-control px-2 py-0.5 text-[12px]"
            :class="p === page ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-100'"
            @click="gotoPage(p)"
          >{{ p }}</button>
          <button class="btn-ghost px-2 text-[12px]" :disabled="page >= pages || loading" @click="gotoPage(page + 1)">下一页</button>
        </span>
      </div>
    </div>

    <!-- 计量项 CRUD -->
    <SectionCard id="usage-meters" title="计量项" subtitle="聚合方式与重置周期决定账单口径；已产生流水的计量项建议停用而不是删除">
      <template #actions>
        <input v-model="meterQ" class="input w-40 py-1 text-[12px]" placeholder="搜索编码/名称" @keyup.enter="loadMeters" />
        <button class="btn-ghost px-2 text-[12px]" @click="loadMeters">查询</button>
        <button class="btn-primary px-3 py-1 text-[12px]" @click="openMeter()">新建计量项</button>
      </template>

      <div v-if="meterLoading && !meters.length" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="meterError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ meterError }}</span>
        <button class="font-medium" @click="loadMeters">重试</button>
      </div>
      <div v-else-if="!meters.length" class="py-8 text-center text-[12px] text-ink-400">
        还没有计量项，新建一个 api.calls 之类的计量编码后即可上报用量
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[860px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">编码 / 名称</th>
              <th class="th">聚合方式</th>
              <th class="th">单位</th>
              <th class="th">重置周期</th>
              <th class="th">状态</th>
              <th class="th">说明</th>
              <th class="th">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in meters" :key="row.id" class="hover:bg-ink-50/50">
              <td class="td">
                <div class="font-mono text-[12px] text-ink-700">{{ row.code }}</div>
                <div class="text-[11px] text-ink-400">{{ row.name }}</div>
              </td>
              <td class="td text-[12px] text-ink-500">{{ row.aggregation_label || row.aggregation }}</td>
              <td class="td text-[12px] text-ink-500">{{ row.unit || '—' }}</td>
              <td class="td text-[12px] text-ink-500">{{ row.reset_period_label || row.reset_period }}</td>
              <td class="td">
                <span class="tag" :class="row.status === 'active' ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                  {{ row.status === 'active' ? '启用' : '停用' }}
                </span>
              </td>
              <td class="td max-w-[220px] truncate text-[12px] text-ink-500">{{ row.description || '—' }}</td>
              <td class="td whitespace-nowrap">
                <button class="btn-ghost px-1.5 text-[12px]" @click="openMeter(row)">编辑</button>
                <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="askRemoveMeter(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </SectionCard>

    <!-- 单条上报 -->
    <Modal :show="reportOpen" title="上报用量" width="560px" @close="closeReport">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600 sm:col-span-2">
            <span class="mb-1 block">订阅</span>
            <select v-model="reportForm.subscription_id" class="input">
              <option value="">请选择订阅</option>
              <option v-for="s in subscriptions" :key="s.id" :value="s.id">
                #{{ s.id }} · {{ s.customer_name }} · {{ s.plan_name }}
              </option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">计量项</span>
            <select v-model="reportForm.meter_id" class="input">
              <option value="">请选择计量项</option>
              <option v-for="m in meters" :key="m.id" :value="m.id">{{ m.name }}（{{ m.code }}）</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">数量</span>
            <input v-model="reportForm.quantity" class="input" inputmode="decimal" placeholder="必须大于 0" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">发生时间</span>
            <input v-model="reportForm.occurred_at" class="input" type="datetime-local" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">来源</span>
            <input v-model="reportForm.source" class="input" maxlength="60" placeholder="api / sdk / manual" />
          </label>
          <label class="block text-[12px] text-ink-600 sm:col-span-2">
            <span class="mb-1 block">幂等键</span>
            <span class="flex gap-2">
              <input v-model="reportForm.idempotency_key" class="input" maxlength="120" placeholder="重复提交会返回原记录" />
              <button class="btn-outline shrink-0 px-2 text-[12px]" @click="fillReportKey">重新生成</button>
            </span>
          </label>
        </div>
        <div v-if="reportError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ reportError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeReport">取消</button>
          <button class="btn-primary" :disabled="reporting" @click="submitReport">
            {{ reporting ? '上报中…' : '确认上报' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 批量上报 -->
    <Modal :show="batchOpen" title="批量上报用量" width="760px" @close="closeBatch">
      <div class="space-y-3">
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">订阅</span>
          <select v-model="batchForm.subscription_id" class="input">
            <option value="">请选择订阅</option>
            <option v-for="s in subscriptions" :key="s.id" :value="s.id">
              #{{ s.id }} · {{ s.customer_name }} · {{ s.plan_name }}
            </option>
          </select>
        </label>
        <div class="overflow-x-auto rounded-control border border-ink-100">
          <table class="w-full min-w-[680px]">
            <thead class="bg-ink-50/60">
              <tr>
                <th class="th w-10">#</th>
                <th class="th">计量项</th>
                <th class="th">数量</th>
                <th class="th">发生时间</th>
                <th class="th">幂等键</th>
                <th class="th w-12">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="(row, index) in batchForm.rows" :key="row.key">
                <td class="td text-[12px] text-ink-400">{{ index + 1 }}</td>
                <td class="td">
                  <select v-model="row.meter_id" class="input py-1 text-[12px]">
                    <option value="">请选择</option>
                    <option v-for="m in meters" :key="m.id" :value="m.id">{{ m.code }}</option>
                  </select>
                </td>
                <td class="td">
                  <input v-model="row.quantity" class="input py-1 text-[12px]" inputmode="decimal" placeholder="数量" />
                </td>
                <td class="td">
                  <input v-model="row.occurred_at" class="input py-1 text-[12px]" type="datetime-local" />
                </td>
                <td class="td">
                  <input v-model="row.idempotency_key" class="input py-1 font-mono text-[11px]" maxlength="120" />
                </td>
                <td class="td">
                  <button class="btn-ghost px-1 text-[12px] text-rose-500" :disabled="batchForm.rows.length <= 1" @click="removeBatchRow(index)">删</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button class="btn-outline px-3 py-1 text-[12px]" :disabled="batchForm.rows.length >= 50" @click="addBatchRow">
            增加一行
          </button>
          <span class="text-[11px] text-ink-400">最多 50 行；每行幂等键可留空，由后端生成</span>
          <span class="ml-auto text-[11px] text-ink-400">当前 {{ batchForm.rows.length }} 行</span>
        </div>
        <div v-if="batchResult" class="rounded-control bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
          批量上报完成：提交 {{ batchResult.count }} 条，新建 {{ batchResult.created }} 条；
          重复幂等键已自动跳过。
        </div>
        <div v-if="batchError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ batchError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeBatch">取消</button>
          <button class="btn-primary" :disabled="batching" @click="submitBatch">
            {{ batching ? '提交中…' : '提交批量上报' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 计量项编辑 -->
    <Modal :show="meterModalOpen" :title="meterForm.id ? '编辑计量项' : '新建计量项'" width="560px" @close="closeMeter">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">编码</span>
            <input v-model="meterForm.code" class="input" maxlength="60" placeholder="如 api.calls" :disabled="Boolean(meterForm.id)" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">名称</span>
            <input v-model="meterForm.name" class="input" maxlength="120" placeholder="如 API 调用次数" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">聚合方式</span>
            <select v-model="meterForm.aggregation" class="input">
              <option value="sum">求和</option>
              <option value="max">最大值</option>
              <option value="latest">最新值</option>
              <option value="count">次数</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">重置周期</span>
            <select v-model="meterForm.reset_period" class="input">
              <option value="month">按月</option>
              <option value="day">按日</option>
              <option value="none">不重置</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">单位</span>
            <input v-model="meterForm.unit" class="input" maxlength="20" placeholder="次 / GB / 分钟" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">状态</span>
            <select v-model="meterForm.status" class="input">
              <option value="active">启用</option>
              <option value="archived">停用</option>
            </select>
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">说明</span>
          <textarea v-model="meterForm.description" class="input min-h-[64px]" maxlength="5000" placeholder="说明该计量的采集口径" />
        </label>
        <div v-if="meterFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ meterFormError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeMeter">取消</button>
          <button class="btn-primary" :disabled="meterSaving" @click="saveMeter">
            {{ meterSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 删除计量项确认 -->
    <Modal :show="meterDeleteOpen" title="删除计量项" width="440px" @close="meterDeleteOpen = false">
      <div class="space-y-3 text-[12px]">
        <p class="text-ink-600">
          确认删除计量项 {{ meterDeleteTarget?.name }}（{{ meterDeleteTarget?.code }}）？
          已产生用量流水的计量项会被后端拒绝删除，请改为停用。
        </p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="meterDeleteOpen = false">取消</button>
          <button class="btn-danger" :disabled="meterDeleting" @click="removeMeter">
            {{ meterDeleting ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { billingApi } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import BarChart from '../../components/platform/BarChart.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])
const app = useAppStore()

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const subscriptionId = ref('')
const meterId = ref('')
const invoiced = ref('')
const startDate = ref('')
const endDate = ref('')
const loading = ref(false)
const error = ref('')
const unavailable = ref('')

const subscriptions = ref([])
const meters = ref([])

const summarySubscriptionId = ref('')
const summaryStart = ref('')
const summaryEnd = ref('')
const summary = ref({ items: [] })
const summaryLoading = ref(false)
const summaryError = ref('')

const trendRows = ref([])
const trendLoading = ref(false)
const trendError = ref('')

const reportOpen = ref(false)
const reportForm = ref(defaultReportForm())
const reporting = ref(false)
const reportError = ref('')

const batchOpen = ref(false)
const batchForm = ref(defaultBatchForm())
const batching = ref(false)
const batchError = ref('')
const batchResult = ref(null)
let batchKeySeq = 0

const meterQ = ref('')
const meterLoading = ref(false)
const meterError = ref('')
const meterModalOpen = ref(false)
const meterForm = ref(defaultMeterForm())
const meterFormError = ref('')
const meterSaving = ref(false)
const meterDeleteOpen = ref(false)
const meterDeleteTarget = ref(null)
const meterDeleting = ref(false)

const pages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const pageButtons = computed(() => {
  const total = pages.value
  const start = Math.max(1, Math.min(page.value - 2, total - 4))
  const end = Math.min(total, start + 4)
  const out = []
  for (let i = start; i <= end; i += 1) out.push(i)
  return out
})

const trendBars = computed(() =>
  trendRows.value.map((row) => ({ label: row.date.slice(5), value: row.quantity }))
)

const trendTotal = computed(() =>
  trendRows.value.reduce((sum, row) => sum + (Number(row.quantity) || 0), 0)
)

const trendPeak = computed(() =>
  trendRows.value.reduce((max, row) => Math.max(max, Number(row.quantity) || 0), 0)
)

const selectedSummarySubscription = computed(() =>
  subscriptions.value.find((s) => String(s.id) === String(summarySubscriptionId.value)) || null
)

function pad(n) {
  return String(n).padStart(2, '0')
}

function dateText(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function nowLocalText() {
  const d = new Date()
  return `${dateText(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function isoText(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toISOString()
}

function formatQuantity(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function randomKey(prefix = 'usage') {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function isUnavailable(e) {
  const code = Number(e?.status || e?.response?.status || 0)
  return code === 404 || code === 405
}

function defaultReportForm() {
  return {
    subscription_id: '',
    meter_id: '',
    quantity: '',
    occurred_at: nowLocalText(),
    idempotency_key: randomKey(),
    source: 'manual',
  }
}

function newBatchRow() {
  batchKeySeq += 1
  return {
    key: `row-${batchKeySeq}`,
    meter_id: '',
    quantity: '',
    occurred_at: nowLocalText(),
    idempotency_key: randomKey('batch'),
  }
}

function defaultBatchForm() {
  return {
    subscription_id: '',
    rows: [newBatchRow(), newBatchRow(), newBatchRow()],
  }
}

function defaultMeterForm() {
  return {
    id: null,
    code: '',
    name: '',
    aggregation: 'sum',
    reset_period: 'month',
    unit: '',
    status: 'active',
    description: '',
  }
}

async function loadList() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (subscriptionId.value) params.subscription_id = subscriptionId.value
    if (meterId.value) params.meter_id = meterId.value
    if (invoiced.value) params.invoiced = invoiced.value
    if (startDate.value) params.start = startDate.value
    if (endDate.value) params.end = endDate.value
    const data = await billingApi.list('usage/', params)
    items.value = data.items || []
    count.value = data.count || 0
    page.value = data.page || page.value
    pageSize.value = data.page_size || pageSize.value
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) {
      unavailable.value = '用量流水端点缺失（404/405）'
    } else {
      error.value = e?.message || '用量流水加载失败'
      app.toastMsg(error.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

async function loadLookups() {
  const results = await Promise.allSettled([
    billingApi.list('subscriptions/', { page: 1, page_size: 200 }),
    billingApi.list('meters/', { page: 1, page_size: 200 }),
  ])
  if (results[0].status === 'fulfilled') subscriptions.value = results[0].value.items || []
  if (results[1].status === 'fulfilled') meters.value = results[1].value.items || []
  if (!summarySubscriptionId.value && subscriptions.value.length) {
    summarySubscriptionId.value = subscriptions.value[0].id
    const sub = subscriptions.value[0]
    summaryStart.value = sub.current_period_start || ''
    summaryEnd.value = sub.current_period_end || ''
    loadSummary()
    loadTrend()
  }
}

async function loadMeters() {
  meterLoading.value = true
  meterError.value = ''
  try {
    const params = { page: 1, page_size: 200 }
    if (meterQ.value.trim()) params.q = meterQ.value.trim()
    const data = await billingApi.list('meters/', params)
    meters.value = data.items || []
  } catch (e) {
    meterError.value = isUnavailable(e)
      ? '计量项端点缺失（404/405）'
      : (e?.message || '计量项加载失败')
  } finally {
    meterLoading.value = false
  }
}

async function loadSummary() {
  if (!summarySubscriptionId.value) {
    summary.value = { items: [] }
    return
  }
  summaryLoading.value = true
  summaryError.value = ''
  try {
    const parts = [`subscription_id=${encodeURIComponent(summarySubscriptionId.value)}`]
    if (summaryStart.value) parts.push(`period_start=${encodeURIComponent(summaryStart.value)}`)
    if (summaryEnd.value) parts.push(`period_end=${encodeURIComponent(summaryEnd.value)}`)
    summary.value = await billingApi.get(`usage/summary/?${parts.join('&')}`)
  } catch (e) {
    summary.value = { items: [] }
    summaryError.value = isUnavailable(e)
      ? '用量汇总端点缺失（404/405）'
      : (e?.message || '用量汇总加载失败')
  } finally {
    summaryLoading.value = false
  }
}

async function loadTrend() {
  if (!summarySubscriptionId.value) {
    trendRows.value = []
    return
  }
  trendLoading.value = true
  trendError.value = ''
  try {
    const data = await billingApi.list('usage/', {
      subscription_id: summarySubscriptionId.value,
      page: 1,
      page_size: 200,
    })
    const buckets = new Map()
    for (const row of data.items || []) {
      const day = String(row.occurred_at || '').slice(0, 10)
      if (!day) continue
      const amount = Number(row.quantity) || 0
      const current = buckets.get(day) || { date: day, quantity: 0, records: 0 }
      current.quantity += amount
      current.records += 1
      buckets.set(day, current)
    }
    trendRows.value = Array.from(buckets.values()).sort((a, b) => a.date.localeCompare(b.date))
  } catch (e) {
    trendRows.value = []
    trendError.value = e?.message || '用量趋势加载失败'
  } finally {
    trendLoading.value = false
  }
}

function onSummarySubscriptionChange() {
  const sub = selectedSummarySubscription.value
  summaryStart.value = sub?.current_period_start || ''
  summaryEnd.value = sub?.current_period_end || ''
  loadSummary()
  loadTrend()
}

function searchNow() {
  page.value = 1
  loadList()
}

function gotoPage(next) {
  const target = Math.min(Math.max(1, Number(next) || 1), pages.value)
  if (target === page.value) return
  page.value = target
  loadList()
}

function changePageSize(event) {
  pageSize.value = Math.min(200, Math.max(1, Number(event?.target?.value) || 20))
  page.value = 1
  loadList()
}

function openReport() {
  reportForm.value = defaultReportForm()
  if (subscriptionId.value) reportForm.value.subscription_id = subscriptionId.value
  if (meterId.value) reportForm.value.meter_id = meterId.value
  reportError.value = ''
  reportOpen.value = true
}

function closeReport() {
  if (reporting.value) return
  reportOpen.value = false
}

function fillReportKey() {
  reportForm.value.idempotency_key = randomKey()
}

async function submitReport() {
  reportError.value = ''
  if (!reportForm.value.subscription_id) {
    reportError.value = '请选择订阅'
    return
  }
  if (!reportForm.value.meter_id) {
    reportError.value = '请选择计量项'
    return
  }
  const quantity = Number(reportForm.value.quantity)
  if (!Number.isFinite(quantity) || quantity <= 0) {
    reportError.value = '数量必须大于 0'
    return
  }
  reporting.value = true
  try {
    const payload = {
      subscription_id: Number(reportForm.value.subscription_id),
      meter_id: Number(reportForm.value.meter_id),
      quantity,
      source: reportForm.value.source || 'manual',
    }
    if (reportForm.value.occurred_at) payload.occurred_at = isoText(reportForm.value.occurred_at)
    if (reportForm.value.idempotency_key.trim()) {
      payload.idempotency_key = reportForm.value.idempotency_key.trim()
    }
    const result = await billingApi.action('usage/report/', payload)
    app.toastMsg(result?.created === false ? '幂等键已存在，返回原记录' : '用量已上报', 'success')
    reportOpen.value = false
    await loadList()
    loadSummary()
    loadTrend()
  } catch (e) {
    reportError.value = e?.message || '上报失败'
    app.toastMsg(reportError.value, 'error')
  } finally {
    reporting.value = false
  }
}

function openBatch() {
  batchForm.value = defaultBatchForm()
  if (subscriptionId.value) batchForm.value.subscription_id = subscriptionId.value
  batchError.value = ''
  batchResult.value = null
  batchOpen.value = true
}

function closeBatch() {
  if (batching.value) return
  batchOpen.value = false
}

function addBatchRow() {
  if (batchForm.value.rows.length >= 50) return
  batchForm.value.rows.push(newBatchRow())
}

function removeBatchRow(index) {
  if (batchForm.value.rows.length <= 1) return
  batchForm.value.rows.splice(index, 1)
}

async function submitBatch() {
  batchError.value = ''
  batchResult.value = null
  if (!batchForm.value.subscription_id) {
    batchError.value = '请选择订阅'
    return
  }
  const rows = []
  for (let i = 0; i < batchForm.value.rows.length; i += 1) {
    const row = batchForm.value.rows[i]
    if (!row.meter_id && !row.quantity) continue
    const quantity = Number(row.quantity)
    if (!row.meter_id) {
      batchError.value = `第 ${i + 1} 行缺少计量项`
      return
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      batchError.value = `第 ${i + 1} 行数量必须大于 0`
      return
    }
    const item = {
      meter_id: Number(row.meter_id),
      quantity,
    }
    if (row.occurred_at) item.occurred_at = isoText(row.occurred_at)
    if (row.idempotency_key.trim()) item.idempotency_key = row.idempotency_key.trim()
    rows.push(item)
  }
  if (!rows.length) {
    batchError.value = '至少填写一行用量'
    return
  }
  batching.value = true
  try {
    const result = await billingApi.action('usage/batch/', {
      subscription_id: Number(batchForm.value.subscription_id),
      rows,
    })
    batchResult.value = result
    app.toastMsg(`批量上报完成：新建 ${result?.created || 0} 条`, 'success')
    await loadList()
    loadSummary()
    loadTrend()
  } catch (e) {
    batchError.value = e?.message || '批量上报失败'
    app.toastMsg(batchError.value, 'error')
  } finally {
    batching.value = false
  }
}

function openMeter(row) {
  meterForm.value = row
    ? {
        id: row.id,
        code: row.code,
        name: row.name,
        aggregation: row.aggregation,
        reset_period: row.reset_period,
        unit: row.unit || '',
        status: row.status,
        description: row.description || '',
      }
    : defaultMeterForm()
  meterFormError.value = ''
  meterModalOpen.value = true
}

function closeMeter() {
  if (meterSaving.value) return
  meterModalOpen.value = false
}

async function saveMeter() {
  meterFormError.value = ''
  if (!meterForm.value.code.trim()) {
    meterFormError.value = '请填写计量编码'
    return
  }
  if (!meterForm.value.name.trim()) {
    meterFormError.value = '请填写计量名称'
    return
  }
  meterSaving.value = true
  try {
    const payload = {
      code: meterForm.value.code.trim(),
      name: meterForm.value.name.trim(),
      aggregation: meterForm.value.aggregation,
      reset_period: meterForm.value.reset_period,
      unit: meterForm.value.unit,
      status: meterForm.value.status,
      description: meterForm.value.description,
    }
    if (meterForm.value.id) {
      delete payload.code
      await billingApi.update(`meters/${meterForm.value.id}/update/`, payload)
      app.toastMsg('计量项已更新', 'success')
    } else {
      await billingApi.create('meters/create/', payload)
      app.toastMsg('计量项已创建', 'success')
    }
    meterModalOpen.value = false
    await loadMeters()
  } catch (e) {
    meterFormError.value = e?.message || '保存计量项失败'
    app.toastMsg(meterFormError.value, 'error')
  } finally {
    meterSaving.value = false
  }
}

function askRemoveMeter(row) {
  meterDeleteTarget.value = row
  meterDeleteOpen.value = true
}

async function removeMeter() {
  if (!meterDeleteTarget.value?.id) return
  meterDeleting.value = true
  try {
    await billingApi.remove(`meters/${meterDeleteTarget.value.id}/delete/`)
    app.toastMsg('计量项已删除', 'success')
    meterDeleteOpen.value = false
    await loadMeters()
  } catch (e) {
    app.toastMsg(e?.message || '删除计量项失败', 'error')
  } finally {
    meterDeleting.value = false
  }
}

function focusMeters() {
  nextTick(() => {
    const el = document.getElementById('usage-meters')
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

watch(subscriptionId, () => {
  page.value = 1
  loadList()
})

watch(meterId, () => {
  page.value = 1
  loadList()
})

watch(invoiced, () => {
  page.value = 1
  loadList()
})

watch(() => props.reloadToken, () => {
  loadList()
  loadMeters()
  loadLookups()
  loadSummary()
  loadTrend()
})

onMounted(() => {
  loadList()
  loadLookups()
  loadMeters()
})
</script>