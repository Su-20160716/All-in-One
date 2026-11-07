<template>
  <section class="space-y-3">
    <!-- 筛选条 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <label class="min-w-[200px] flex-1">
        <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
        <input
          v-model="q"
          class="input"
          type="search"
          placeholder="按发票编号、客户名称或备注搜索"
          @keyup.enter="searchNow"
        />
      </label>
      <label class="w-32">
        <span class="mb-1 block text-[11px] text-ink-400">状态</span>
        <select v-model="status" class="input" @change="searchNow">
          <option value="">全部状态</option>
          <option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
      </label>
      <label class="w-44">
        <span class="mb-1 block text-[11px] text-ink-400">客户</span>
        <select v-model="customerId" class="input" @change="searchNow">
          <option value="">全部客户</option>
          <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </label>
      <label class="w-32">
        <span class="mb-1 block text-[11px] text-ink-400">周期</span>
        <select v-model="periodKey" class="input">
          <option value="">全部周期</option>
          <option value="this_month">本月</option>
          <option value="last_month">上月</option>
          <option value="this_quarter">本季度</option>
        </select>
      </label>
      <label class="flex items-center gap-1 pb-1.5 text-[12px] text-ink-600">
        <input v-model="overdueOnly" type="checkbox" @change="searchNow" />
        仅逾期
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
        <span>共 {{ formatNumber(count) }} 张</span>
        <button class="btn-outline px-2 py-1 text-[12px]" :disabled="scanning" @click="scanOverdue">
          {{ scanning ? '扫描中…' : '逾期扫描' }}
        </button>
        <button class="btn-primary px-3 py-1 text-[12px]" @click="openGenerate">生成发票</button>
      </span>
    </div>

    <!-- 逾期扫描结果 -->
    <div
      v-if="scanResult"
      class="card flex flex-wrap items-center gap-2 border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800"
    >
      <span class="min-w-0 flex-1">
        逾期扫描完成：{{ scanResult.count }} 张发票逾期，合计待收
        {{ formatMoney(scanResult.total_due) }}；扫描时间 {{ formatDate(scanResult.scanned_at, true) }}。
      </span>
      <button class="btn-outline px-2 py-0.5" @click="scanOpen = true">查看明细</button>
      <button class="btn-ghost px-2 py-0.5" @click="scanResult = null">关闭</button>
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
        {{ unavailable }}。发票端点恢复后重新刷新即可加载。
      </div>
      <div v-else-if="!visibleItems.length" class="py-12 text-center text-[12px] text-ink-400">
        {{ hasFilters ? '没有匹配的发票，调整筛选条件后重试' : '还没有发票，点击「生成发票」按订阅生成一张' }}
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1080px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">发票编号</th>
              <th class="th">客户</th>
              <th class="th">状态</th>
              <th class="th">账单周期</th>
              <th class="th">总额</th>
              <th class="th">已付 / 待收</th>
              <th class="th">到期日</th>
              <th class="th">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr
              v-for="row in visibleItems"
              :key="row.id"
              class="cursor-pointer hover:bg-ink-50/50"
              @click="openDetail(row)"
            >
              <td class="td">
                <div class="font-mono text-[12px] text-ink-700">{{ row.number || '—' }}</div>
                <div class="text-[11px] text-ink-400">{{ row.source === 'manual' ? '手工账单' : '订阅生成' }}</div>
              </td>
              <td class="td max-w-[180px] truncate">{{ row.customer_name || '—' }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ row.status_label || statusLabel(row.status) }}</span>
                <span v-if="row.is_overdue" class="tag ml-1 bg-rose-50 text-rose-600">逾期</span>
              </td>
              <td class="td text-[12px] text-ink-500">{{ periodText(row) }}</td>
              <td class="td">{{ formatMoney(row.total, row.currency) }}</td>
              <td class="td text-[12px]">
                <span class="text-emerald-600">{{ formatMoney(row.amount_paid, row.currency) }}</span>
                <span class="text-ink-300"> / </span>
                <span class="text-rose-600">{{ formatMoney(row.amount_due, row.currency) }}</span>
              </td>
              <td class="td text-[12px] text-ink-500">{{ formatDate(row.due_date) }}</td>
              <td class="td whitespace-nowrap" @click.stop>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openDetail(row)">详情</button>
                <button
                  v-if="row.status === 'draft'"
                  class="btn-ghost px-1.5 text-[12px] text-brand-600"
                  :disabled="busyId === row.id"
                  @click="sendInvoice(row)"
                >发送</button>
                <button
                  v-if="row.status === 'open' || row.status === 'draft'"
                  class="btn-ghost px-1.5 text-[12px] text-emerald-600"
                  @click="openMarkPaid(row)"
                >标记支付</button>
                <button
                  v-if="row.status === 'open' || row.status === 'draft'"
                  class="btn-ghost px-1.5 text-[12px] text-rose-500"
                  @click="openVoid(row)"
                >作废</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
        <span>
          第 {{ page }} / {{ pages }} 页 · 每页 {{ pageSize }} 条
          <span v-if="periodKey" class="ml-1 text-ink-400">（本页周期筛选后 {{ visibleItems.length }} 条）</span>
        </span>
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

    <!-- 生成发票 -->
    <Modal :show="generateOpen" title="按订阅生成发票" width="640px" @close="closeGenerate">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600 sm:col-span-2">
            <span class="mb-1 block">订阅</span>
            <select v-model="generateForm.subscription_id" class="input" @change="onSubscriptionChange">
              <option value="">请选择订阅</option>
              <option v-for="s in subscriptions" :key="s.id" :value="s.id">
                #{{ s.id }} · {{ s.customer_name }} · {{ s.plan_name }}（{{ s.status_label || s.status }}）
              </option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">账期起始</span>
            <input v-model="generateForm.period_start" class="input" type="date" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">到期天数</span>
            <input v-model.number="generateForm.due_days" class="input" type="number" min="0" max="365" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">优惠码（可选）</span>
            <input v-model="generateForm.coupon_code" class="input" maxlength="60" placeholder="生成时校验并抵扣" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">币种（可选）</span>
            <input v-model="generateForm.currency" class="input" maxlength="8" placeholder="默认取订阅币种" />
          </label>
        </div>
        <label class="flex items-center gap-2 rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          <input v-model="generateForm.include_usage" type="checkbox" />
          合并当期未开票用量（按计量项汇总后写入用量行）
        </label>
        <label class="flex items-center gap-2 rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          <input v-model="generateForm.send" type="checkbox" />
          生成后立即发送（草稿 → 待支付）
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">备注</span>
          <textarea v-model="generateForm.notes" class="input min-h-[64px]" maxlength="2000" placeholder="会写入发票备注" />
        </label>
        <p v-if="selectedSubscription" class="rounded-control bg-brand-50 px-3 py-2 text-[12px] text-brand-700">
          当前账期 {{ selectedSubscription.current_period_start || '—' }} ~
          {{ selectedSubscription.current_period_end || '—' }}，周期金额
          {{ formatMoney(selectedSubscription.period_amount, selectedSubscription.currency) }}。
          账期结束由套餐周期自动推导。
        </p>
        <div v-if="generateError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ generateError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeGenerate">取消</button>
          <button class="btn-primary" :disabled="generating" @click="submitGenerate">
            {{ generating ? '生成中…' : '确认生成' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 发票详情抽屉 -->
    <div v-if="drawerOpen" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDetail"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[660px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="tagClass(statusTone(detail?.status))">
                {{ detail?.status_label || statusLabel(detail?.status) }}
              </span>
              <span v-if="detail?.is_overdue" class="tag bg-rose-50 text-rose-600">逾期</span>
              <span class="tag">{{ detail?.currency || 'CNY' }}</span>
              <span class="tag">{{ detail?.source === 'manual' ? '手工账单' : '订阅生成' }}</span>
            </div>
            <h3 class="mt-1 truncate font-mono text-[15px] font-semibold text-ink-900">
              {{ detail?.number || '发票详情' }}
            </h3>
            <p class="truncate text-[11px] text-ink-400">{{ detail?.customer_name || '—' }}</p>
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
              <div class="text-ink-400">账单周期</div>
              <div class="text-ink-700">{{ periodText(detail) }}</div>
              <div class="text-ink-400">到期日</div>
              <div class="text-ink-700">{{ formatDate(detail.due_date) }}</div>
              <div class="text-ink-400">已付 / 抵扣</div>
              <div class="text-ink-700">
                {{ formatMoney(detail.amount_paid, detail.currency) }} /
                {{ formatMoney(detail.credit_applied, detail.currency) }}
              </div>
              <div class="text-ink-400">创建时间</div>
              <div class="text-ink-700">{{ formatDate(detail.created_at, true) }}</div>
              <div class="text-ink-400">发送时间</div>
              <div class="text-ink-700">{{ formatDate(detail.sent_at, true) }}</div>
              <div class="text-ink-400">结清时间</div>
              <div class="text-ink-700">{{ formatDate(detail.paid_at, true) }}</div>
              <div class="text-ink-400">备注</div>
              <div class="break-all text-ink-700">{{ detail.notes || '—' }}</div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">行项</span>
                <span class="tag">{{ (detail.lines || []).length }} 行</span>
              </div>
              <div v-if="!(detail.lines || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                该发票没有行项，可能是空草稿
              </div>
              <div v-else class="overflow-x-auto rounded-control border border-ink-100">
                <table class="w-full min-w-[560px]">
                  <thead class="bg-ink-50/60">
                    <tr>
                      <th class="th">类型</th>
                      <th class="th">说明</th>
                      <th class="th">数量</th>
                      <th class="th">单价</th>
                      <th class="th">金额</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-ink-50">
                    <tr v-for="line in detail.lines" :key="line.id">
                      <td class="td text-[12px]">{{ line.line_type_label || line.line_type }}</td>
                      <td class="td max-w-[220px] truncate text-[12px]">{{ line.description }}</td>
                      <td class="td text-[12px] text-ink-500">{{ line.quantity }}</td>
                      <td class="td text-[12px] text-ink-500">{{ line.unit_amount }}</td>
                      <td class="td text-[12px]">{{ formatMoney(line.amount, detail.currency) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="mt-2 ml-auto w-full max-w-[280px] space-y-1 rounded-control bg-ink-50 px-3 py-2 text-[12px]">
                <div class="flex justify-between"><span class="text-ink-500">小计</span><span>{{ formatMoney(detail.subtotal, detail.currency) }}</span></div>
                <div class="flex justify-between"><span class="text-ink-500">折扣</span><span class="text-emerald-600">-{{ formatMoney(detail.discount_total, detail.currency) }}</span></div>
                <div class="flex justify-between"><span class="text-ink-500">税费</span><span>{{ formatMoney(detail.tax_total, detail.currency) }}</span></div>
                <div class="flex justify-between border-t border-ink-200 pt-1 font-medium">
                  <span>应收总额</span><span>{{ formatMoney(detail.total, detail.currency) }}</span>
                </div>
                <div class="flex justify-between font-medium text-rose-600">
                  <span>待收</span><span>{{ formatMoney(detail.amount_due, detail.currency) }}</span>
                </div>
              </div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">收款记录</span>
                <span class="tag">{{ (detail.payments || []).length }} 条</span>
              </div>
              <div v-if="!(detail.payments || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                还没有收款记录，可标记支付或发送给客户
              </div>
              <ul v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="pay in detail.payments" :key="pay.id" class="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[12px]">
                  <span class="min-w-0 flex-1 truncate">{{ pay.method_label || pay.method }} · {{ pay.gateway_ref || '无流水号' }}</span>
                  <span class="tag" :class="tagClass(statusTone(pay.status))">{{ pay.status_label || pay.status }}</span>
                  <span class="w-24 shrink-0 text-right">{{ formatMoney(pay.amount, pay.currency) }}</span>
                  <span class="w-28 shrink-0 text-right text-[11px] text-ink-400">{{ formatDate(pay.paid_at, true) }}</span>
                  <button
                    v-if="pay.status === 'succeeded'"
                    class="btn-ghost px-1.5 text-[11px] text-rose-500"
                    @click="openRefund(pay)"
                  >退款</button>
                </li>
              </ul>
            </div>

            <div v-if="(detail.credit_notes || []).length">
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">信用票据</span>
                <span class="tag">{{ detail.credit_notes.length }} 张</span>
              </div>
              <ul class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="note in detail.credit_notes" :key="note.id" class="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[12px]">
                  <span class="min-w-0 flex-1 truncate font-mono text-ink-600">{{ note.number }}</span>
                  <span class="tag" :class="tagClass(statusTone(note.status))">{{ note.status_label || note.status }}</span>
                  <span class="w-24 shrink-0 text-right">{{ formatMoney(note.amount, note.currency) }}</span>
                </li>
              </ul>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">账单事件</span>
                <span class="tag">{{ (detail.events || []).length }} 条</span>
              </div>
              <div v-if="!(detail.events || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                暂无事件
              </div>
              <ul v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="ev in detail.events" :key="ev.id" class="flex items-center gap-2 px-3 py-1.5 text-[12px]">
                  <span class="min-w-0 flex-1 truncate text-ink-700">{{ ev.event_type }}</span>
                  <span class="shrink-0 text-[11px] text-ink-400">{{ formatDate(ev.created_at, true) }}</span>
                </li>
              </ul>
            </div>
          </template>
        </div>

        <div class="flex flex-wrap items-center gap-2 border-t border-ink-100 px-4 py-2.5">
          <button
            v-if="detail?.status === 'draft'"
            class="btn-outline px-3 py-1 text-[12px]"
            :disabled="busyId === detail?.id"
            @click="sendInvoice(detail)"
          >发送发票</button>
          <button
            v-if="detail?.status === 'draft'"
            class="btn-outline px-3 py-1 text-[12px]"
            :disabled="recalcBusy"
            @click="recalcInvoice(detail)"
          >{{ recalcBusy ? '重算中…' : '重算汇总' }}</button>
          <button
            v-if="detail?.status === 'open' || detail?.status === 'draft'"
            class="btn-primary px-3 py-1 text-[12px]"
            @click="openMarkPaid(detail)"
          >标记支付</button>
          <button
            v-if="detail?.status === 'open' || detail?.status === 'draft'"
            class="btn-danger ml-auto px-3 py-1 text-[12px]"
            @click="openVoid(detail)"
          >作废发票</button>
        </div>
      </aside>
    </div>

    <!-- 标记支付 -->
    <Modal :show="markPaidOpen" title="登记收款" width="480px" @close="closeMarkPaid">
      <div class="space-y-3 text-[12px]">
        <p class="text-ink-600">
          为发票 {{ markPaidInvoice?.number }} 登记收款，可部分收款；全额后自动置为已支付。
        </p>
        <label class="block text-ink-600">
          <span class="mb-1 block">收款金额（{{ markPaidInvoice?.currency || 'CNY' }}）</span>
          <input v-model="markPaidForm.amount" class="input" inputmode="decimal" placeholder="默认待收金额" />
        </label>
        <label class="block text-ink-600">
          <span class="mb-1 block">支付方式</span>
          <select v-model="markPaidForm.method" class="input">
            <option v-for="m in PAYMENT_METHODS" :key="m.value" :value="m.value">{{ m.label }}</option>
          </select>
        </label>
        <div v-if="markPaidError" class="rounded-control bg-rose-50 px-3 py-2 text-rose-600">{{ markPaidError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeMarkPaid">取消</button>
          <button class="btn-primary" :disabled="markPaidBusy" @click="submitMarkPaid">
            {{ markPaidBusy ? '登记中…' : '确认收款' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 作废发票 -->
    <Modal :show="voidOpen" title="作废发票" width="480px" @close="closeVoid">
      <div class="space-y-3 text-[12px]">
        <p class="text-ink-600">
          作废后发票不可再收款，已占用的用量流水会被释放；该操作不可撤销。
        </p>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-ink-600">
          {{ voidInvoice?.number }} · {{ voidInvoice?.customer_name }} · 总额
          {{ formatMoney(voidInvoice?.total, voidInvoice?.currency) }}
        </div>
        <label class="block text-ink-600">
          <span class="mb-1 block">作废原因</span>
          <textarea v-model="voidForm.reason" class="input min-h-[64px]" maxlength="500" placeholder="会写入账单事件" />
        </label>
        <div v-if="voidError" class="rounded-control bg-rose-50 px-3 py-2 text-rose-600">{{ voidError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeVoid">取消</button>
          <button class="btn-danger" :disabled="voidBusy" @click="submitVoid">
            {{ voidBusy ? '作废中…' : '确认作废' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 退款 -->
    <Modal :show="refundOpen" title="支付退款" width="480px" @close="closeRefund">
      <div class="space-y-3 text-[12px]">
        <p class="text-ink-600">退款会同步冲减发票已付金额与客户余额，可部分退款。</p>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-ink-600">
          支付 #{{ refundPayment?.id }} · {{ refundPayment?.method_label || refundPayment?.method }} ·
          原金额 {{ formatMoney(refundPayment?.amount, refundPayment?.currency) }}
        </div>
        <label class="block text-ink-600">
          <span class="mb-1 block">退款金额（{{ refundPayment?.currency || 'CNY' }}）</span>
          <input v-model="refundForm.amount" class="input" inputmode="decimal" placeholder="默认原支付金额" />
        </label>
        <label class="block text-ink-600">
          <span class="mb-1 block">退款原因</span>
          <input v-model="refundForm.reason" class="input" maxlength="300" placeholder="可选" />
        </label>
        <div v-if="refundError" class="rounded-control bg-rose-50 px-3 py-2 text-rose-600">{{ refundError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeRefund">取消</button>
          <button class="btn-primary" :disabled="refundBusy" @click="submitRefund">
            {{ refundBusy ? '退款中…' : '确认退款' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 逾期扫描明细 -->
    <Modal :show="scanOpen" title="逾期发票明细" width="720px" @close="scanOpen = false">
      <div class="space-y-2 text-[12px]">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag bg-amber-50 text-amber-700">{{ scanResult?.count || 0 }} 张</span>
          <span class="tag">合计待收 {{ formatMoney(scanResult?.total_due) }}</span>
          <span class="text-ink-400">扫描时间 {{ formatDate(scanResult?.scanned_at, true) }}</span>
        </div>
        <div v-if="!(scanResult?.items || []).length" class="py-6 text-center text-ink-400">
          没有逾期未结清的发票
        </div>
        <div v-else class="max-h-[50vh] overflow-auto rounded-control border border-ink-100">
          <table class="w-full min-w-[620px]">
            <thead class="bg-ink-50">
              <tr>
                <th class="th">发票编号</th>
                <th class="th">客户</th>
                <th class="th">币种</th>
                <th class="th">待收</th>
                <th class="th">逾期天数</th>
                <th class="th">到期日</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in scanResult.items" :key="row.invoice_id">
                <td class="td font-mono text-[12px]">{{ row.number }}</td>
                <td class="td max-w-[180px] truncate">{{ row.customer }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.currency }}</td>
                <td class="td">{{ formatMoney(row.amount_due, row.currency) }}</td>
                <td class="td text-[12px] text-rose-600">{{ row.days_overdue }} 天</td>
                <td class="td text-[12px] text-ink-500">{{ formatDate(row.due_date) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex justify-end">
          <button class="btn-ghost" @click="scanOpen = false">关闭</button>
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
  { value: 'draft', label: '草稿' },
  { value: 'open', label: '待支付' },
  { value: 'paid', label: '已支付' },
  { value: 'void', label: '已作废' },
  { value: 'uncollectible', label: '无法收回' },
]

const STATUS_LABELS = {
  draft: '草稿',
  open: '待支付',
  paid: '已支付',
  void: '已作废',
  uncollectible: '无法收回',
}

const PAYMENT_METHODS = [
  { value: 'manual', label: '人工登记' },
  { value: 'card', label: '银行卡' },
  { value: 'bank_transfer', label: '对公转账' },
  { value: 'alipay', label: '支付宝' },
  { value: 'wechat', label: '微信支付' },
  { value: 'credit', label: '账户余额' },
]

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const q = ref('')
const status = ref('')
const customerId = ref('')
const periodKey = ref('')
const overdueOnly = ref(false)
const loading = ref(false)
const error = ref('')
const unavailable = ref('')
const busyId = ref(null)
const recalcBusy = ref(false)

const customers = ref([])
const subscriptions = ref([])

const generateOpen = ref(false)
const generating = ref(false)
const generateError = ref('')
const generateForm = ref(defaultGenerateForm())

const drawerOpen = ref(false)
const detailId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const markPaidOpen = ref(false)
const markPaidInvoice = ref(null)
const markPaidForm = ref({ amount: '', method: 'manual' })
const markPaidBusy = ref(false)
const markPaidError = ref('')

const voidOpen = ref(false)
const voidInvoice = ref(null)
const voidForm = ref({ reason: '' })
const voidBusy = ref(false)
const voidError = ref('')

const refundOpen = ref(false)
const refundPayment = ref(null)
const refundForm = ref({ amount: '', reason: '' })
const refundBusy = ref(false)
const refundError = ref('')

const scanOpen = ref(false)
const scanning = ref(false)
const scanResult = ref(null)

const pages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const pageButtons = computed(() => {
  const total = pages.value
  const start = Math.max(1, Math.min(page.value - 2, total - 4))
  const end = Math.min(total, start + 4)
  const out = []
  for (let i = start; i <= end; i += 1) out.push(i)
  return out
})

const hasFilters = computed(() =>
  Boolean(q.value.trim() || status.value || customerId.value || overdueOnly.value || periodKey.value)
)

const selectedSubscription = computed(() =>
  subscriptions.value.find((s) => String(s.id) === String(generateForm.value.subscription_id)) || null
)

function pad(n) {
  return String(n).padStart(2, '0')
}

function dateText(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function periodRange() {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  if (periodKey.value === 'this_month') {
    return [dateText(new Date(y, m, 1)), dateText(new Date(y, m + 1, 1))]
  }
  if (periodKey.value === 'last_month') {
    return [dateText(new Date(y, m - 1, 1)), dateText(new Date(y, m, 1))]
  }
  if (periodKey.value === 'this_quarter') {
    const quarterStart = Math.floor(m / 3) * 3
    return [dateText(new Date(y, quarterStart, 1)), dateText(new Date(y, quarterStart + 3, 1))]
  }
  return null
}

const visibleItems = computed(() => {
  const range = periodRange()
  if (!range) return items.value
  return items.value.filter((row) => {
    const start = String(row.period_start || '')
    return start && start >= range[0] && start < range[1]
  })
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

function periodText(row) {
  if (!row?.period_start && !row?.period_end) return '—'
  return `${row.period_start || '—'} ~ ${row.period_end || '—'}`
}

function isUnavailable(e) {
  const code = Number(e?.status || e?.response?.status || 0)
  return code === 404 || code === 405
}

function defaultGenerateForm() {
  return {
    subscription_id: '',
    period_start: dateText(new Date()),
    due_days: 7,
    include_usage: true,
    send: false,
    coupon_code: '',
    currency: '',
    notes: '',
  }
}

async function loadList() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (status.value) params.status = status.value
    if (customerId.value) params.customer_id = customerId.value
    if (overdueOnly.value) params.overdue = '1'
    const data = await billingApi.list('invoices/', params)
    items.value = data.items || []
    count.value = data.count || 0
    page.value = data.page || page.value
    pageSize.value = data.page_size || pageSize.value
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) {
      unavailable.value = '发票列表端点缺失（404/405）'
    } else {
      error.value = e?.message || '发票列表加载失败'
      app.toastMsg(error.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

async function loadLookups() {
  const results = await Promise.allSettled([
    billingApi.list('customers/', { page: 1, page_size: 200 }),
    billingApi.list('subscriptions/', { page: 1, page_size: 200 }),
  ])
  if (results[0].status === 'fulfilled') customers.value = results[0].value.items || []
  if (results[1].status === 'fulfilled') subscriptions.value = results[1].value.items || []
}

async function loadDetail(id) {
  if (!id) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await billingApi.get(`invoices/${id}/`)
  } catch (e) {
    detail.value = null
    detailError.value = e?.message || '发票详情加载失败'
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
  pageSize.value = Math.min(200, Math.max(1, Number(event?.target?.value) || 20))
  page.value = 1
  loadList()
}

function openGenerate() {
  generateForm.value = defaultGenerateForm()
  generateError.value = ''
  generateOpen.value = true
  if (!subscriptions.value.length) loadLookups()
}

function closeGenerate() {
  if (generating.value) return
  generateOpen.value = false
}

function onSubscriptionChange() {
  const sub = selectedSubscription.value
  if (!sub) return
  if (sub.current_period_start) generateForm.value.period_start = sub.current_period_start
  if (sub.currency) generateForm.value.currency = sub.currency
}

async function submitGenerate() {
  generateError.value = ''
  if (!generateForm.value.subscription_id) {
    generateError.value = '请选择订阅'
    return
  }
  generating.value = true
  try {
    const payload = {
      subscription_id: Number(generateForm.value.subscription_id),
      due_days: Number(generateForm.value.due_days) || 0,
      include_usage: Boolean(generateForm.value.include_usage),
      send: Boolean(generateForm.value.send),
    }
    if (generateForm.value.period_start) payload.period_start = generateForm.value.period_start
    if (generateForm.value.coupon_code.trim()) payload.coupon_code = generateForm.value.coupon_code.trim()
    if (generateForm.value.currency.trim()) payload.currency = generateForm.value.currency.trim().toUpperCase()
    if (generateForm.value.notes.trim()) payload.notes = generateForm.value.notes.trim()
    const invoice = await billingApi.action('invoices/generate/', payload)
    app.toastMsg(`发票 ${invoice?.number || ''} 已生成`, 'success')
    generateOpen.value = false
    await loadList()
    if (invoice?.id) {
      detailId.value = invoice.id
      drawerOpen.value = true
      detail.value = invoice
    }
  } catch (e) {
    generateError.value = e?.message || '生成发票失败'
    app.toastMsg(generateError.value, 'error')
  } finally {
    generating.value = false
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

async function sendInvoice(row) {
  if (!row?.id) return
  busyId.value = row.id
  try {
    const updated = await billingApi.action(`invoices/${row.id}/send/`, {})
    app.toastMsg('发票已发送', 'success')
    await loadList()
    if (drawerOpen.value && detailId.value === row.id) detail.value = updated
  } catch (e) {
    app.toastMsg(e?.message || '发送发票失败', 'error')
  } finally {
    busyId.value = null
  }
}

async function recalcInvoice(row) {
  if (!row?.id) return
  recalcBusy.value = true
  try {
    detail.value = await billingApi.action(`invoices/${row.id}/recalc/`, {})
    app.toastMsg('发票汇总已重算', 'success')
    await loadList()
  } catch (e) {
    app.toastMsg(e?.message || '重算失败', 'error')
  } finally {
    recalcBusy.value = false
  }
}

function openMarkPaid(row) {
  markPaidInvoice.value = row
  markPaidForm.value = { amount: row?.amount_due || '', method: 'manual' }
  markPaidError.value = ''
  markPaidOpen.value = true
}

function closeMarkPaid() {
  if (markPaidBusy.value) return
  markPaidOpen.value = false
}

async function submitMarkPaid() {
  if (!markPaidInvoice.value?.id) return
  markPaidBusy.value = true
  markPaidError.value = ''
  try {
    const payload = { method: markPaidForm.value.method || 'manual' }
    if (String(markPaidForm.value.amount || '').trim()) payload.amount = markPaidForm.value.amount
    const result = await billingApi.action(`invoices/${markPaidInvoice.value.id}/mark-paid/`, payload)
    app.toastMsg('收款已登记', 'success')
    markPaidOpen.value = false
    await loadList()
    if (result?.invoice && drawerOpen.value && detailId.value === result.invoice.id) {
      detail.value = result.invoice
    } else if (result?.invoice?.id) {
      detailId.value = result.invoice.id
      drawerOpen.value = true
      detail.value = result.invoice
    }
  } catch (e) {
    markPaidError.value = e?.message || '登记收款失败'
    app.toastMsg(markPaidError.value, 'error')
  } finally {
    markPaidBusy.value = false
  }
}

function openVoid(row) {
  voidInvoice.value = row
  voidForm.value = { reason: '' }
  voidError.value = ''
  voidOpen.value = true
}

function closeVoid() {
  if (voidBusy.value) return
  voidOpen.value = false
}

async function submitVoid() {
  if (!voidInvoice.value?.id) return
  voidBusy.value = true
  voidError.value = ''
  try {
    const payload = {}
    if (voidForm.value.reason.trim()) payload.reason = voidForm.value.reason.trim()
    const updated = await billingApi.action(`invoices/${voidInvoice.value.id}/void/`, payload)
    app.toastMsg('发票已作废', 'success')
    voidOpen.value = false
    await loadList()
    if (drawerOpen.value && detailId.value === updated?.id) detail.value = updated
  } catch (e) {
    voidError.value = e?.message || '作废失败'
    app.toastMsg(voidError.value, 'error')
  } finally {
    voidBusy.value = false
  }
}

function openRefund(payment) {
  refundPayment.value = payment
  refundForm.value = { amount: payment?.amount || '', reason: '' }
  refundError.value = ''
  refundOpen.value = true
}

function closeRefund() {
  if (refundBusy.value) return
  refundOpen.value = false
}

async function submitRefund() {
  if (!refundPayment.value?.id) return
  refundBusy.value = true
  refundError.value = ''
  try {
    const payload = {}
    if (String(refundForm.value.amount || '').trim()) payload.amount = refundForm.value.amount
    if (refundForm.value.reason.trim()) payload.reason = refundForm.value.reason.trim()
    await billingApi.action(`payments/${refundPayment.value.id}/refund/`, payload)
    app.toastMsg('退款已登记', 'success')
    refundOpen.value = false
    await loadList()
    if (drawerOpen.value && detailId.value) loadDetail(detailId.value)
  } catch (e) {
    refundError.value = e?.message || '退款失败'
    app.toastMsg(refundError.value, 'error')
  } finally {
    refundBusy.value = false
  }
}

async function scanOverdue() {
  scanning.value = true
  try {
    scanResult.value = await billingApi.action('invoices/overdue-scan/', {})
    app.toastMsg(`逾期扫描完成：${scanResult.value?.count || 0} 张`, 'success')
    await loadList()
  } catch (e) {
    app.toastMsg(e?.message || '逾期扫描失败', 'error')
  } finally {
    scanning.value = false
  }
}

watch(() => props.reloadToken, () => {
  loadList()
  loadLookups()
})

onMounted(() => {
  loadList()
  loadLookups()
})
</script>