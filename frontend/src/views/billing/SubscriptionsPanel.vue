<template>
  <section class="space-y-3">
    <!-- 筛选条 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <label class="min-w-[220px] flex-1">
        <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
        <input
          v-model="q"
          class="input"
          type="search"
          placeholder="按客户名称、套餐编码或套餐名称搜索"
          @keyup.enter="searchNow"
        />
      </label>
      <label class="w-36">
        <span class="mb-1 block text-[11px] text-ink-400">状态</span>
        <select v-model="status" class="input" @change="searchNow">
          <option value="">全部状态</option>
          <option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
      </label>
      <label class="w-28">
        <span class="mb-1 block text-[11px] text-ink-400">每页</span>
        <select class="input" :value="pageSize" @change="changePageSize($event)">
          <option v-for="n in [10, 20, 50]" :key="n" :value="n">{{ n }} 条</option>
        </select>
      </label>
      <button class="btn-primary" @click="searchNow">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="loadList">刷新</button>
      <span class="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span>共 {{ formatNumber(count) }} 个订阅</span>
        <button class="btn-outline px-3 py-1 text-[12px]" @click="openCreate">开通订阅</button>
      </span>
    </div>

    <!-- 列表 -->
    <div class="card overflow-hidden">
      <div v-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div
        v-else-if="error"
        class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="font-medium" @click="loadList">重试</button>
      </div>
      <div v-else-if="unavailable && !items.length" class="py-12 text-center text-[12px] text-amber-700">
        {{ unavailable }}。订阅端点恢复后重新刷新即可加载。
      </div>
      <div v-else-if="!items.length" class="py-12 text-center text-[12px] text-ink-400">
        {{ q || status ? '没有匹配的订阅，调整筛选条件后重试' : '还没有订阅，点击右上角「开通订阅」创建第一个' }}
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1080px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">客户 / 套餐</th>
              <th class="th">状态</th>
              <th class="th">席位</th>
              <th class="th">当前周期</th>
              <th class="th">周期金额</th>
              <th class="th">续费</th>
              <th class="th">更新时间</th>
              <th class="th">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr
              v-for="row in items"
              :key="row.id"
              class="cursor-pointer hover:bg-ink-50/50"
              @click="openDetail(row)"
            >
              <td class="td">
                <div class="max-w-[240px]">
                  <div class="truncate font-medium text-ink-800">{{ row.customer_name || '未命名客户' }}</div>
                  <div class="truncate text-[11px] text-ink-400">
                    {{ row.plan_name || '未命名套餐' }}
                    <span class="font-mono">· {{ row.plan_code || '—' }}</span>
                  </div>
                </div>
              </td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ row.status_label || statusLabel(row.status) }}</span>
                <span v-if="row.cancel_at_period_end" class="tag ml-1 bg-amber-50 text-amber-600">期末取消</span>
                <span v-if="row.in_trial" class="tag ml-1 bg-indigo-50 text-indigo-600">试用</span>
              </td>
              <td class="td text-[12px] text-ink-500">{{ formatNumber(row.seats) }}</td>
              <td class="td text-[12px] text-ink-500">
                {{ row.current_period_start || '—' }} ~ {{ row.current_period_end || '—' }}
                <div class="text-[11px] text-ink-400">{{ row.current_period_days || 0 }} 天</div>
              </td>
              <td class="td">
                {{ formatMoney(row.period_amount, row.currency) }}
                <div class="text-[11px] text-ink-400">月均 {{ formatMoney(row.monthly_value, row.currency) }}</div>
              </td>
              <td class="td text-[12px]" :class="row.auto_renew ? 'text-emerald-600' : 'text-ink-400'">
                {{ row.auto_renew ? '自动续费' : '手动续费' }}
              </td>
              <td class="td text-[12px] text-ink-500">{{ formatDate(row.updated_at, true) }}</td>
              <td class="td whitespace-nowrap" @click.stop>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openDetail(row)">详情</button>
                <button
                  class="btn-ghost px-1.5 text-[12px] text-brand-600"
                  :disabled="!canChange(row)"
                  @click="openChange(row)"
                >升降级</button>
                <button
                  v-if="row.status === 'paused'"
                  class="btn-ghost px-1.5 text-[12px] text-emerald-600"
                  @click="openAction('resume', row)"
                >恢复</button>
                <button
                  v-else-if="row.status === 'active' || row.status === 'past_due'"
                  class="btn-ghost px-1.5 text-[12px] text-amber-600"
                  @click="openAction('pause', row)"
                >暂停</button>
                <button
                  v-if="row.status !== 'canceled'"
                  class="btn-ghost px-1.5 text-[12px] text-rose-500"
                  @click="openAction('cancel', row)"
                >取消</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页 -->
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

    <!-- 开通订阅 -->
    <Modal :show="createOpen" title="开通订阅" width="620px" @close="closeCreate">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">客户</span>
            <select v-model="createForm.customer_id" class="input">
              <option value="">请选择客户</option>
              <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}（{{ c.currency }}）</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">套餐</span>
            <select v-model="createForm.plan_id" class="input" @change="onPlanChange">
              <option value="">请选择已发布套餐</option>
              <option v-for="p in activePlans" :key="p.id" :value="p.id">
                {{ p.name }} · {{ p.billing_period_label || p.billing_period }}
              </option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">价格</span>
            <select v-model="createForm.price_id" class="input">
              <option value="">按套餐默认价格</option>
              <option v-for="p in planPrices" :key="p.id" :value="p.id">
                {{ p.currency }} {{ p.amount }} · {{ p.billing_mode_label || p.billing_mode }}
              </option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">席位数量</span>
            <input v-model.number="createForm.seats" class="input" type="number" min="1" max="100000" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">开始日期</span>
            <input v-model="createForm.start_date" class="input" type="date" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">币种</span>
            <input v-model="createForm.currency" class="input" maxlength="8" placeholder="默认取客户币种" />
          </label>
        </div>
        <label class="flex items-center gap-2 rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          <input v-model="createForm.trial" type="checkbox" />
          <span>以试用方式开通（按套餐试用天数计算，可稍后转正）</span>
        </label>
        <p v-if="selectedPlan" class="rounded-control bg-brand-50 px-3 py-2 text-[12px] text-brand-700">
          {{ selectedPlan.name }}：{{ selectedPlan.billing_period_label || selectedPlan.billing_period }}，
          试用 {{ selectedPlan.trial_days || 0 }} 天，包含 {{ (selectedPlan.plan_features || []).length }} 项功能配置。
        </p>
        <div v-if="createError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ createError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeCreate">取消</button>
          <button class="btn-primary" :disabled="creating" @click="submitCreate">
            {{ creating ? '开通中…' : '确认开通' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 详情抽屉 -->
    <div v-if="drawerOpen" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDetail"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[640px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="tagClass(statusTone(detail?.status))">
                {{ detail?.status_label || statusLabel(detail?.status) }}
              </span>
              <span v-if="detail?.in_trial" class="tag bg-indigo-50 text-indigo-600">试用中</span>
              <span v-if="detail?.cancel_at_period_end" class="tag bg-amber-50 text-amber-600">期末取消</span>
              <span class="tag">{{ detail?.currency || 'CNY' }}</span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">
              {{ detail?.customer_name || '订阅详情' }}
            </h3>
            <p class="truncate text-[11px] text-ink-400">
              {{ detail?.plan_name || '—' }} · {{ detail?.plan_code || '—' }} · 订阅 #{{ detailId }}
            </p>
          </div>
          <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" @click="closeDetail">✕</button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <div v-if="detailLoading" class="py-10 text-center text-[12px] text-ink-400">详情加载中…</div>
          <div v-else-if="detailError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <div class="truncate">{{ detailError }}</div>
            <button class="mt-1 font-medium" @click="loadDetail(detailId)">重试</button>
          </div>
          <template v-else-if="detail">
            <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
              <div class="text-ink-400">客户</div>
              <div class="text-ink-700">{{ detail.customer_name || '—' }}</div>
              <div class="text-ink-400">套餐</div>
              <div class="text-ink-700">{{ detail.plan_name || '—' }}（{{ detail.plan_code || '—' }}）</div>
              <div class="text-ink-400">席位</div>
              <div class="text-ink-700">{{ formatNumber(detail.seats) }}</div>
              <div class="text-ink-400">开始日期</div>
              <div class="text-ink-700">{{ detail.start_date || '—' }}</div>
              <div class="text-ink-400">试用结束</div>
              <div class="text-ink-700">{{ formatDate(detail.trial_end, true) }}</div>
              <div class="text-ink-400">当前周期</div>
              <div class="text-ink-700">
                {{ detail.current_period_start || '—' }} ~ {{ detail.current_period_end || '—' }}
                （{{ detail.current_period_days || 0 }} 天）
              </div>
              <div class="text-ink-400">周期金额</div>
              <div class="text-ink-700">{{ formatMoney(detail.period_amount, detail.currency) }}</div>
              <div class="text-ink-400">月均价值</div>
              <div class="text-ink-700">{{ formatMoney(detail.monthly_value, detail.currency) }}</div>
              <div class="text-ink-400">自动续费</div>
              <div class="text-ink-700">{{ detail.auto_renew ? '是' : '否' }}</div>
              <div class="text-ink-400">取消原因</div>
              <div class="text-ink-700">{{ detail.cancel_reason || '—' }}</div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">订阅明细</span>
                <span class="tag">{{ (detail.items || []).length }} 条</span>
              </div>
              <div v-if="!(detail.items || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                该订阅没有价格明细
              </div>
              <div v-else class="overflow-x-auto rounded-control border border-ink-100">
                <table class="w-full min-w-[520px]">
                  <thead class="bg-ink-50/60">
                    <tr>
                      <th class="th">价格 ID</th>
                      <th class="th">计费模式</th>
                      <th class="th">单价</th>
                      <th class="th">数量</th>
                      <th class="th">生效区间</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-ink-50">
                    <tr v-for="line in detail.items" :key="line.id">
                      <td class="td font-mono text-[12px]">#{{ line.price_id }}</td>
                      <td class="td text-[12px] text-ink-500">{{ line.billing_mode || '—' }}</td>
                      <td class="td text-[12px]">{{ line.currency }} {{ line.unit_amount }}</td>
                      <td class="td text-[12px]">{{ line.quantity }}</td>
                      <td class="td text-[11px] text-ink-500">{{ line.effective_from || '—' }} ~ {{ line.effective_to || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">当期用量</span>
                <span class="tag">合计 {{ formatMoney(detail.usage?.total_amount) }}</span>
              </div>
              <div v-if="!(detail.usage?.items || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                当期还没有用量记录
              </div>
              <div v-else class="overflow-x-auto rounded-control border border-ink-100">
                <table class="w-full min-w-[560px]">
                  <thead class="bg-ink-50/60">
                    <tr>
                      <th class="th">计量项</th>
                      <th class="th">记录</th>
                      <th class="th">用量</th>
                      <th class="th">包含量</th>
                      <th class="th">超量</th>
                      <th class="th">金额</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-ink-50">
                    <tr v-for="u in detail.usage.items" :key="u.meter_id">
                      <td class="td text-[12px]">{{ u.meter_name }} <span class="font-mono text-[11px] text-ink-400">{{ u.meter_code }}</span></td>
                      <td class="td text-[12px] text-ink-500">{{ u.records }}</td>
                      <td class="td text-[12px]">{{ u.quantity }} {{ u.unit }}</td>
                      <td class="td text-[12px] text-ink-500">{{ u.included }}</td>
                      <td class="td text-[12px] text-amber-600">{{ u.billable }}</td>
                      <td class="td text-[12px]">{{ formatMoney(u.amount) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">近期发票</span>
                <span class="tag">{{ (detail.recent_invoices || []).length }} 张</span>
              </div>
              <div v-if="!(detail.recent_invoices || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                还没有为该订阅生成发票
              </div>
              <ul v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="inv in detail.recent_invoices" :key="inv.id" class="flex items-center gap-2 px-3 py-1.5 text-[12px]">
                  <span class="min-w-0 flex-1 truncate font-mono text-ink-600">{{ inv.number }}</span>
                  <span class="tag" :class="tagClass(statusTone(inv.status))">{{ inv.status_label || inv.status }}</span>
                  <span class="w-24 shrink-0 text-right">{{ formatMoney(inv.total, inv.currency) }}</span>
                  <span class="w-24 shrink-0 text-right text-[11px] text-ink-400">到期 {{ inv.due_date || '—' }}</span>
                </li>
              </ul>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">订阅事件</span>
                <span class="tag">{{ (detail.events || []).length }} 条</span>
              </div>
              <div v-if="!(detail.events || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                暂无事件记录
              </div>
              <ul v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="ev in detail.events" :key="ev.id" class="flex items-start gap-2 px-3 py-1.5 text-[12px]">
                  <span class="min-w-0 flex-1 truncate text-ink-700">{{ ev.event_type }}</span>
                  <span class="shrink-0 text-[11px] text-ink-400">{{ formatDate(ev.created_at, true) }}</span>
                </li>
              </ul>
            </div>
          </template>
        </div>

        <div class="flex flex-wrap items-center gap-2 border-t border-ink-100 px-4 py-2.5">
          <button
            v-if="detail?.status === 'trialing'"
            class="btn-outline px-3 py-1 text-[12px]"
            @click="openAction('trial-convert', detail)"
          >试用转正</button>
          <button
            v-if="detail?.status === 'paused'"
            class="btn-outline px-3 py-1 text-[12px]"
            @click="openAction('resume', detail)"
          >恢复订阅</button>
          <button
            v-else-if="detail?.status === 'active' || detail?.status === 'past_due'"
            class="btn-outline px-3 py-1 text-[12px]"
            @click="openAction('pause', detail)"
          >暂停订阅</button>
          <button
            v-if="detail?.status !== 'canceled'"
            class="btn-outline px-3 py-1 text-[12px]"
            @click="openAction('renew', detail)"
          >续费一期</button>
          <button
            v-if="canChange(detail)"
            class="btn-outline px-3 py-1 text-[12px]"
            @click="openChange(detail)"
          >升级 / 降级</button>
          <span class="ml-auto flex gap-2">
            <button
              v-if="detail?.status !== 'canceled'"
              class="btn-danger px-3 py-1 text-[12px]"
              @click="openAction('cancel', detail)"
            >期末取消</button>
            <button
              v-if="detail?.status !== 'canceled'"
              class="btn-danger px-3 py-1 text-[12px]"
              @click="openAction('cancel-now', detail)"
            >立即取消</button>
          </span>
        </div>
      </aside>
    </div>

    <!-- 变更套餐：预览 + 按比例折算 -->
    <Modal :show="changeOpen" title="变更套餐（按天折算）" width="680px" @close="closeChange">
      <div class="space-y-3">
        <div class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          当前套餐：{{ changeRow?.plan_name || '—' }} ·
          周期 {{ changeRow?.current_period_start || '—' }} ~ {{ changeRow?.current_period_end || '—' }}
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">目标套餐</span>
            <select v-model="changeForm.new_plan_id" class="input" @change="previewChange">
              <option value="">请选择套餐</option>
              <option v-for="p in changePlans" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">席位数量</span>
            <input v-model.number="changeForm.seats" class="input" type="number" min="1" @change="previewChange" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">变更原因（可选）</span>
          <input v-model="changeForm.reason" class="input" maxlength="200" placeholder="记录在事件时间线中" />
        </label>

        <div v-if="changePreviewLoading" class="rounded-control bg-ink-50 px-3 py-4 text-center text-[12px] text-ink-400">
          正在计算折算金额…
        </div>
        <div v-else-if="changePreviewError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ changePreviewError }}
        </div>
        <div v-else-if="changePreview" class="space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag-brand">{{ changePreview.from_plan }} → {{ changePreview.to_plan }}</span>
            <span class="tag" :class="changePreview.upgrade ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'">
              {{ changePreview.upgrade ? '升级' : '降级' }}
            </span>
            <span class="tag">已用 {{ changePreview.total_days - changePreview.remaining_days }} 天 / 剩余 {{ changePreview.remaining_days }} 天</span>
            <span class="tag">折算比例 {{ ratioText(changePreview.ratio) }}</span>
          </div>
          <div class="grid grid-cols-2 gap-2 text-[12px] sm:grid-cols-3">
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">原周期金额</div>
              <div class="mt-0.5 font-medium text-ink-800">{{ formatMoney(changePreview.old_period_amount, changePreview.currency) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">新周期金额</div>
              <div class="mt-0.5 font-medium text-ink-800">{{ formatMoney(changePreview.new_period_amount, changePreview.currency) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">已用部分抵扣</div>
              <div class="mt-0.5 font-medium text-emerald-700">{{ formatMoney(changePreview.credit, changePreview.currency) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">剩余部分应收</div>
              <div class="mt-0.5 font-medium text-ink-800">{{ formatMoney(changePreview.charge, changePreview.currency) }}</div>
            </div>
            <div class="rounded-control bg-brand-50 px-3 py-2">
              <div class="text-[11px] text-brand-600">应付差额</div>
              <div class="mt-0.5 font-medium text-brand-700">{{ formatMoney(changePreview.net, changePreview.currency) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">折算基准时间</div>
              <div class="mt-0.5 text-[11px] text-ink-700">{{ formatDate(changePreview.at, true) }}</div>
            </div>
          </div>
          <p class="text-[11px] text-ink-400">
            正差额会为客户生成一张折算发票；负差额进入客户账户余额，下次开票自动抵扣。
          </p>
        </div>
        <div v-if="changeError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ changeError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeChange">取消</button>
          <button class="btn-primary" :disabled="changeSubmitting || !changePreview" @click="submitChange">
            {{ changeSubmitting ? '提交中…' : '确认变更' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 生命周期动作 -->
    <Modal :show="actionOpen" :title="actionMeta.title" width="520px" @close="closeAction">
      <div class="space-y-3 text-[12px]">
        <p class="text-ink-600">{{ actionMeta.description }}</p>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-ink-600">
          订阅 #{{ actionRow?.id }} · {{ actionRow?.customer_name || '—' }} · {{ actionRow?.plan_name || '—' }}
        </div>
        <label v-if="actionMeta.needReason" class="block text-ink-600">
          <span class="mb-1 block">原因</span>
          <textarea v-model="actionReason" class="input min-h-[72px]" maxlength="200" placeholder="取消原因会记录在订阅事件中" />
        </label>
        <div v-if="actionError" class="rounded-control bg-rose-50 px-3 py-2 text-rose-600">{{ actionError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeAction">返回</button>
          <button class="btn-primary" :disabled="actionBusy" @click="submitAction">
            {{ actionBusy ? '处理中…' : actionMeta.confirmText }}
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { billingApi } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
  statusTone,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])
const app = useAppStore()

const STATUS_OPTIONS = [
  { value: 'trialing', label: '试用中' },
  { value: 'active', label: '生效中' },
  { value: 'past_due', label: '逾期' },
  { value: 'paused', label: '已暂停' },
  { value: 'canceled', label: '已取消' },
]

const STATUS_LABELS = {
  trialing: '试用中',
  active: '生效中',
  past_due: '逾期',
  paused: '已暂停',
  canceled: '已取消',
}

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const q = ref('')
const status = ref('')
const loading = ref(false)
const error = ref('')
const unavailable = ref('')

const customers = ref([])
const plans = ref([])
const prices = ref([])
const lookupsLoading = ref(false)

const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = ref(defaultCreateForm())

const drawerOpen = ref(false)
const detailId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const changeOpen = ref(false)
const changeRow = ref(null)
const changeForm = ref({ new_plan_id: '', seats: 1, reason: '' })
const changePreview = ref(null)
const changePreviewLoading = ref(false)
const changePreviewError = ref('')
const changeSubmitting = ref(false)
const changeError = ref('')

const actionOpen = ref(false)
const actionType = ref('')
const actionRow = ref(null)
const actionReason = ref('')
const actionBusy = ref(false)
const actionError = ref('')

const ACTION_META = {
  pause: {
    title: '暂停订阅',
    description: '暂停后不再产生周期费用，订阅保留在当前周期内，可随时恢复。',
    confirmText: '确认暂停',
    needReason: false,
  },
  resume: {
    title: '恢复订阅',
    description: '恢复后将重新进入计费周期，试用中的订阅会从暂停点继续。',
    confirmText: '确认恢复',
    needReason: false,
  },
  cancel: {
    title: '期末取消订阅',
    description: '在当前周期结束时取消，周期内仍可正常使用；可随时撤销。',
    confirmText: '确认期末取消',
    needReason: true,
  },
  'cancel-now': {
    title: '立即取消订阅',
    description: '立即终止订阅并释放资源，未使用部分按平台规则处理，操作不可撤销。',
    confirmText: '确认立即取消',
    needReason: true,
  },
  renew: {
    title: '续费一期',
    description: '按套餐周期推进账期并生成一张订阅发票，便于人工确认收款。',
    confirmText: '确认续费',
    needReason: false,
  },
  activate: {
    title: '激活订阅',
    description: '将订阅立即置为生效状态，并生成首期发票。',
    confirmText: '确认激活',
    needReason: false,
  },
  'trial-convert': {
    title: '试用转正',
    description: '结束试用并转为付费订阅，按套餐价格生成首期发票。',
    confirmText: '确认转正',
    needReason: false,
  },
}

const pages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const pageButtons = computed(() => {
  const total = pages.value
  const start = Math.max(1, Math.min(page.value - 2, total - 4))
  const end = Math.min(total, start + 4)
  const out = []
  for (let i = start; i <= end; i += 1) out.push(i)
  return out
})

const activePlans = computed(() => plans.value.filter((p) => p.status === 'active'))
const changePlans = computed(() => plans.value.filter((p) => p.status === 'active'))

const selectedPlan = computed(() =>
  plans.value.find((p) => String(p.id) === String(createForm.value.plan_id)) || null
)

const planPrices = computed(() =>
  prices.value.filter((p) => String(p.plan_id) === String(createForm.value.plan_id))
)

const actionMeta = computed(() => ACTION_META[actionType.value] || {
  title: '订阅操作',
  description: '',
  confirmText: '确认',
  needReason: false,
})

function statusLabel(value) {
  return STATUS_LABELS[value] || value || '未知'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function ratioText(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  const pct = n <= 1 ? n * 100 : n
  return `${pct.toFixed(1)}%`
}

function isUnavailable(e) {
  const code = Number(e?.status || e?.response?.status || 0)
  return code === 404 || code === 405
}

function todayText() {
  return new Date().toISOString().slice(0, 10)
}

function defaultCreateForm() {
  return {
    customer_id: '',
    plan_id: '',
    price_id: '',
    seats: 1,
    start_date: todayText(),
    trial: false,
    currency: '',
  }
}

function canChange(row) {
  return Boolean(row && row.status !== 'canceled' && row.status !== 'paused')
}

async function loadList() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (status.value) params.status = status.value
    const data = await billingApi.list('subscriptions/', params)
    items.value = data.items || []
    count.value = data.count || 0
    page.value = data.page || page.value
    pageSize.value = data.page_size || pageSize.value
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) {
      unavailable.value = '订阅列表端点缺失（404/405）'
    } else {
      error.value = e?.message || '订阅列表加载失败'
      app.toastMsg(error.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

async function loadLookups() {
  lookupsLoading.value = true
  const requests = [
    billingApi.list('customers/', { page: 1, page_size: 200 }),
    billingApi.list('plans/', { page: 1, page_size: 200 }),
    billingApi.list('prices/', { page: 1, page_size: 200 }),
  ]
  const results = await Promise.allSettled(requests)
  if (results[0].status === 'fulfilled') customers.value = results[0].value.items || []
  if (results[1].status === 'fulfilled') plans.value = results[1].value.items || []
  if (results[2].status === 'fulfilled') prices.value = results[2].value.items || []
  lookupsLoading.value = false
}

async function loadDetail(id) {
  if (!id) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await billingApi.get(`subscriptions/${id}/`)
  } catch (e) {
    detail.value = null
    detailError.value = e?.message || '订阅详情加载失败'
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
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
  const next = Number(event?.target?.value) || 20
  pageSize.value = Math.min(200, Math.max(1, next))
  page.value = 1
  loadList()
}

function openCreate() {
  createForm.value = defaultCreateForm()
  createError.value = ''
  createOpen.value = true
  if (!customers.value.length || !plans.value.length || !prices.value.length) loadLookups()
}

function closeCreate() {
  if (creating.value) return
  createOpen.value = false
}

function onPlanChange() {
  createForm.value.price_id = ''
  const first = planPrices.value[0]
  if (first) {
    createForm.value.price_id = first.id
    createForm.value.currency = first.currency
  }
}

async function submitCreate() {
  createError.value = ''
  if (!createForm.value.customer_id) {
    createError.value = '请选择客户'
    return
  }
  if (!createForm.value.plan_id) {
    createError.value = '请选择套餐'
    return
  }
  creating.value = true
  try {
    const payload = {
      customer_id: Number(createForm.value.customer_id),
      plan_id: Number(createForm.value.plan_id),
      seats: Number(createForm.value.seats) || 1,
      trial: Boolean(createForm.value.trial),
    }
    if (createForm.value.price_id) payload.price_id = Number(createForm.value.price_id)
    if (createForm.value.start_date) payload.start_date = createForm.value.start_date
    if (createForm.value.currency) payload.currency = createForm.value.currency
    const created = await billingApi.create('subscriptions/create/', payload)
    app.toastMsg('订阅已开通', 'success')
    createOpen.value = false
    await loadList()
    if (created?.id) {
      detailId.value = created.id
      drawerOpen.value = true
      loadDetail(created.id)
    }
  } catch (e) {
    createError.value = e?.message || '开通订阅失败'
    app.toastMsg(createError.value, 'error')
  } finally {
    creating.value = false
  }
}

function openDetail(row) {
  detailId.value = row.id
  drawerOpen.value = true
  loadDetail(row.id)
}

function closeDetail() {
  drawerOpen.value = false
}

function openChange(row) {
  if (!row) return
  changeRow.value = row
  changeForm.value = {
    new_plan_id: '',
    seats: row.seats || 1,
    reason: '',
  }
  changePreview.value = null
  changePreviewError.value = ''
  changeError.value = ''
  changeOpen.value = true
  if (!plans.value.length) loadLookups()
}

function closeChange() {
  if (changeSubmitting.value) return
  changeOpen.value = false
}

async function previewChange() {
  changePreview.value = null
  changePreviewError.value = ''
  if (!changeForm.value.new_plan_id || !changeRow.value) return
  changePreviewLoading.value = true
  try {
    changePreview.value = await billingApi.action(
      `subscriptions/${changeRow.value.id}/change-preview/`,
      {
        new_plan_id: Number(changeForm.value.new_plan_id),
        seats: Number(changeForm.value.seats) || 1,
      }
    )
  } catch (e) {
    changePreviewError.value = e?.message || '折算预览失败'
  } finally {
    changePreviewLoading.value = false
  }
}

async function submitChange() {
  if (!changeRow.value || !changeForm.value.new_plan_id) return
  changeSubmitting.value = true
  changeError.value = ''
  try {
    const result = await billingApi.action(
      `subscriptions/${changeRow.value.id}/change-plan/`,
      {
        new_plan_id: Number(changeForm.value.new_plan_id),
        seats: Number(changeForm.value.seats) || 1,
        reason: changeForm.value.reason || '',
        generate: true,
      }
    )
    const invoice = result?.invoice
    app.toastMsg(invoice ? `套餐已变更，并生成发票 ${invoice.number}` : '套餐已变更', 'success')
    changeOpen.value = false
    detailId.value = changeRow.value.id
    await loadList()
    if (drawerOpen.value) loadDetail(detailId.value)
  } catch (e) {
    changeError.value = e?.message || '变更套餐失败'
    app.toastMsg(changeError.value, 'error')
  } finally {
    changeSubmitting.value = false
  }
}

function openAction(type, row) {
  if (!row || !ACTION_META[type]) return
  actionType.value = type
  actionRow.value = row
  actionReason.value = ''
  actionError.value = ''
  actionOpen.value = true
}

function closeAction() {
  if (actionBusy.value) return
  actionOpen.value = false
}

async function submitAction() {
  if (!actionRow.value || !actionType.value) return
  if (actionMeta.value.needReason && !actionReason.value.trim()) {
    actionError.value = '请填写原因'
    return
  }
  actionBusy.value = true
  actionError.value = ''
  try {
    const payload = {}
    if (actionMeta.value.needReason) payload.reason = actionReason.value.trim()
    const result = await billingApi.action(
      `subscriptions/${actionRow.value.id}/${actionType.value}/`,
      payload
    )
    const invoice = result?.invoice
    app.toastMsg(invoice ? `操作成功，已生成发票 ${invoice.number}` : '操作成功', 'success')
    actionOpen.value = false
    const currentId = actionRow.value.id
    await loadList()
    if (drawerOpen.value && detailId.value === currentId) loadDetail(currentId)
  } catch (e) {
    actionError.value = e?.message || '操作失败'
    app.toastMsg(actionError.value, 'error')
  } finally {
    actionBusy.value = false
  }
}

watch(status, () => {
  page.value = 1
  loadList()
})

watch(() => props.reloadToken, () => {
  loadList()
  loadLookups()
})

onMounted(() => {
  loadList()
  loadLookups()
})
</script>