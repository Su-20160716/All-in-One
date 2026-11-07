<template>
  <section class="space-y-3">
    <!-- 工具栏 -->
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <input v-model="q" class="input w-52" placeholder="搜索名称 / 编码 / 分类 / 描述" />
      <select v-model="status" class="input w-28">
        <option value="">全部状态</option>
        <option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
      <input v-model="category" class="input w-36" list="report-categories" placeholder="全部分类" />
      <datalist id="report-categories">
        <option v-for="c in categoryOptions" :key="c" :value="c" />
      </datalist>
      <label class="flex items-center gap-1 text-[12px] text-ink-600">
        <input v-model="favoriteOnly" type="checkbox" @change="applyFilters" />
        只看收藏
      </label>
      <span class="tag">共 {{ count }} 张</span>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn-ghost" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
        <button class="btn-outline" @click="resetFilters">重置</button>
        <button class="btn-primary" @click="openCreate">新建报表</button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="card p-0">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
        <div>
          <h3 class="text-[14px] font-semibold text-ink-800">报表台账</h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            支持关键词、状态、分类与收藏过滤；每行可直接执行、查看结果、导出、发布、归档、克隆与分享。
          </p>
        </div>
        <span v-if="lastLoadedText" class="text-[11px] text-ink-400">最近加载 {{ lastLoadedText }}</span>
      </div>

      <div v-if="loading && !items.length" class="space-y-2 p-4">
        <div v-for="n in 6" :key="`sk-${n}`" class="h-9 animate-pulse rounded-control bg-ink-50"></div>
      </div>

      <div v-else-if="unavailable" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
        <span class="min-w-0 flex-1">{{ unavailable }}。列表已降级为空态，不影响其他页签。</span>
        <button class="font-medium text-brand-600" @click="load">重试</button>
      </div>

      <div v-else-if="error" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-rose-50 px-3 py-2.5 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="font-medium" @click="load">重试</button>
      </div>

      <div v-else-if="!items.length" class="px-4 py-12 text-center">
        <p class="text-[13px] text-ink-500">
          {{ hasFilters ? '当前筛选条件下没有报表' : '还没有创建任何报表' }}
        </p>
        <p class="mt-1 text-[11px] text-ink-400">报表用于组织页面、组件与筛选器，创建后可以绑定数据集并发布分享。</p>
        <div class="mt-3 flex justify-center gap-2">
          <button v-if="hasFilters" class="btn-outline" @click="resetFilters">清空筛选</button>
          <button class="btn-primary" @click="openCreate">新建报表</button>
        </div>
      </div>

      <div v-else class="overflow-auto">
        <table class="w-full min-w-[1120px]">
          <thead class="bg-ink-50">
            <tr>
              <th class="th w-8"></th>
              <th class="th">名称 / 编码</th>
              <th class="th w-28">分类</th>
              <th class="th w-24">状态</th>
              <th class="th w-20 text-right">页面</th>
              <th class="th w-24 text-right">执行次数</th>
              <th class="th w-36">最近执行</th>
              <th class="th w-36">更新时间</th>
              <th class="th w-[330px]">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="align-top hover:bg-ink-50/50">
              <td class="td">
                <button
                  class="text-[15px] leading-none"
                  :class="isFavorite(row.id) ? 'text-amber-500' : 'text-ink-300 hover:text-amber-400'"
                  :title="isFavorite(row.id) ? '取消收藏' : '收藏报表'"
                  :aria-label="isFavorite(row.id) ? '取消收藏' : '收藏报表'"
                  @click="toggleFavorite(row)"
                >★</button>
              </td>
              <td class="td">
                <button class="block max-w-[280px] truncate text-left text-[13px] font-medium text-ink-800 hover:text-brand-600" @click="openResult(row)">
                  {{ row.name || '未命名报表' }}
                </button>
                <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <span class="font-mono text-[10px] text-ink-400">{{ row.code || '—' }}</span>
                  <span v-if="row.description" class="max-w-[240px] truncate text-[10px] text-ink-400" :title="row.description">
                    {{ row.description }}
                  </span>
                </div>
              </td>
              <td class="td"><span class="tag">{{ row.category || '通用' }}</span></td>
              <td class="td">
                <span class="tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
                <div v-if="row.published_at" class="mt-1 text-[10px] text-ink-400">{{ fmtDate(row.published_at) }}</div>
              </td>
              <td class="td text-right tabular-nums">{{ row.page_count ?? 0 }}</td>
              <td class="td text-right tabular-nums">{{ fmtInt(row.run_count) }}</td>
              <td class="td text-[11px] text-ink-500">{{ fmtDT(row.last_run_at) }}</td>
              <td class="td text-[11px] text-ink-500">{{ fmtDT(row.updated_at) }}</td>
              <td class="td">
                <div class="flex flex-wrap gap-x-2.5 gap-y-1 text-[11px]">
                  <button class="text-brand-600 hover:underline" @click="openEdit(row)">编辑</button>
                  <button class="text-brand-600 hover:underline" @click="openRun(row)">执行</button>
                  <button class="text-brand-600 hover:underline" @click="openResult(row)">结果</button>
                  <button class="text-ink-500 hover:text-brand-600" @click="exportReport(row, 'csv')">导出 CSV</button>
                  <button class="text-ink-500 hover:text-brand-600" @click="exportReport(row, 'json')">导出 JSON</button>
                  <button class="text-ink-500 hover:text-brand-600" @click="openShare(row)">分享</button>
                  <button v-if="row.status !== 'published'" class="text-emerald-600 hover:underline" @click="publishReport(row)">发布</button>
                  <button v-if="row.status !== 'archived'" class="text-amber-600 hover:underline" @click="archiveReport(row)">归档</button>
                  <button class="text-ink-500 hover:text-brand-600" @click="cloneReport(row)">克隆</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页 -->
      <div v-if="count > 0" class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-4 py-2.5 text-[12px] text-ink-500">
        <div class="flex items-center gap-2">
          <span>第 {{ page }} / {{ totalPages }} 页，共 {{ count }} 条</span>
          <select :value="pageSize" class="input w-24 py-1" @change="changePageSize($event)">
            <option v-for="size in PAGE_SIZES" :key="size" :value="size">每页 {{ size }}</option>
          </select>
        </div>
        <div class="flex items-center gap-1">
          <button class="btn-outline px-2 py-0.5" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <button
            v-for="p in pageButtons"
            :key="p"
            class="min-w-7 rounded-control px-2 py-0.5 text-[12px]"
            :class="p === page ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-100'"
            @click="goPage(p)"
          >{{ p }}</button>
          <button class="btn-outline px-2 py-0.5" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑 -->
    <Modal :show="formOpen" :title="form.id ? '编辑报表' : '新建报表'" width="680px" @close="closeForm">
      <div v-if="formLoading" class="py-10 text-center text-[12px] text-ink-400">加载报表详情…</div>
      <div v-else class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">名称 <span class="text-rose-500">*</span></span>
            <input v-model="form.name" class="input" placeholder="如：月度经营分析" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">编码 <span class="text-rose-500">*</span></span>
            <input v-model="form.code" class="input font-mono" placeholder="如：monthly_ops" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">分类</span>
            <input v-model="form.category" class="input" list="report-categories" placeholder="通用" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">默认数据集</span>
            <select v-model="form.dataset_id" class="input">
              <option value="">不绑定（后续在组件中选择）</option>
              <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}（{{ d.primary_model }}）</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">主题</span>
            <select v-model="form.theme" class="input">
              <option value="light">浅色</option>
              <option value="dark">深色</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">结果缓存秒数</span>
            <input v-model.number="form.cache_ttl" class="input" type="number" min="0" max="86400" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">描述</span>
          <textarea v-model="form.description" class="input min-h-20" placeholder="说明报表口径、使用对象与更新频率" />
        </label>
        <p class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          报表本身不含取数逻辑：数据集用于后续组件绑定，这里选择的默认数据集会随报表权限配置一起保存，执行弹窗会自动带出该数据集的参数默认值。
        </p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeForm">取消</button>
          <button class="btn-primary" :disabled="saving" @click="saveForm">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Modal>

    <!-- 执行参数 -->
    <Modal :show="runOpen" :title="`执行报表：${runTarget?.name || ''}`" width="620px" @close="runOpen = false">
      <div class="space-y-3">
        <div v-if="runDetailLoading" class="py-8 text-center text-[12px] text-ink-400">正在读取组件筛选器与数据集参数…</div>
        <template v-else>
          <div v-if="paramFields.length" class="space-y-2">
            <div class="text-[12px] font-medium text-ink-700">参数</div>
            <label v-for="field in paramFields" :key="field.key" class="block text-[12px] text-ink-600">
              <span class="mb-1 flex items-center gap-1">
                <span>{{ field.label }}</span>
                <span v-if="field.required" class="text-rose-500">*</span>
                <span class="font-mono text-[10px] text-ink-400">{{ field.key }}</span>
              </span>
              <input v-model="paramValues[field.key]" class="input" :placeholder="field.placeholder || '留空使用默认值'" />
              <span v-if="field.hint" class="mt-0.5 block text-[10px] text-ink-400">{{ field.hint }}</span>
            </label>
          </div>
          <div v-else class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-500">
            该报表的组件没有绑定参数，可直接执行。
          </div>

          <div class="space-y-2">
            <div class="flex items-center justify-between text-[12px] text-ink-600">
              <span>附加参数</span>
              <button class="text-brand-600" @click="extraParams.push({ key: '', value: '' })">添加一行</button>
            </div>
            <div v-for="(row, idx) in extraParams" :key="`extra-${idx}`" class="flex items-center gap-2">
              <input v-model="row.key" class="input w-40" placeholder="参数名" />
              <input v-model="row.value" class="input flex-1" placeholder="参数值" />
              <button class="text-ink-400 hover:text-rose-500" @click="extraParams.splice(idx, 1)">删除</button>
            </div>
            <p v-if="!extraParams.length" class="text-[11px] text-ink-400">筛选器参数之外的自定义参数，会原样传给执行接口。</p>
          </div>

          <label class="flex items-center gap-2 text-[12px] text-ink-600">
            <input v-model="runBypass" type="checkbox" />
            跳过结果缓存，强制重新计算
          </label>

          <div v-if="runError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ runError }}</div>

          <div class="flex justify-end gap-2">
            <button class="btn-ghost" @click="runOpen = false">取消</button>
            <button class="btn-primary" :disabled="runSubmitting" @click="submitRun">
              {{ runSubmitting ? '执行中…' : '执行并查看结果' }}
            </button>
          </div>
        </template>
      </div>
    </Modal>

    <!-- 结果 -->
    <Modal :show="resultOpen" :title="`执行结果：${resultTarget?.name || ''}`" width="1120px" @close="resultOpen = false">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span v-if="resultPayload?.meta?.status" class="tag" :class="statusClass(resultPayload.meta.status === 'failed' ? 'failed' : 'success')">
            {{ resultPayload.meta.status === 'failed' ? '执行失败' : '执行成功' }}
          </span>
          <span v-if="resultPayload?.meta?.cached" class="tag bg-amber-50 text-amber-700">缓存命中</span>
          <span v-if="resultPayload" class="tag">耗时 {{ fmtMs(resultPayload.meta?.duration_ms) }}</span>
          <span v-if="resultPayload" class="tag">行数 {{ fmtInt(resultPayload.meta?.row_total) }}</span>
          <span v-if="resultPayload?.meta?.generated_at" class="text-[11px] text-ink-400">
            生成于 {{ fmtDT(resultPayload.meta.generated_at) }}
          </span>
          <div class="ml-auto flex flex-wrap gap-1.5">
            <button class="btn-outline px-2 py-0.5" :disabled="resultLoading" @click="reloadResult">刷新结果</button>
            <button class="btn-outline px-2 py-0.5" @click="exportReport(resultTarget, 'csv')">导出 CSV</button>
            <button class="btn-outline px-2 py-0.5" @click="exportReport(resultTarget, 'json')">导出 JSON</button>
          </div>
        </div>

        <div v-if="resultLoading" class="py-12 text-center text-[12px] text-ink-400">结果加载中…</div>
        <div v-else-if="resultError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ resultError }}</div>
        <div v-else-if="resultEmpty" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          {{ resultEmpty }}
        </div>
        <div v-else-if="!resultPages.length" class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-500">
          报表还没有页面或组件，结果为空。可先编辑报表并添加组件，或在数据集页预览数据。
        </div>

        <template v-else>
          <div class="flex flex-wrap items-center gap-1 border-b border-ink-100">
            <button
              v-for="(p, idx) in resultPages"
              :key="`page-${p.id}`"
              class="-mb-px border-b-2 px-3 py-1.5 text-[12px]"
              :class="activePage === idx ? 'border-brand-600 text-brand-700' : 'border-transparent text-ink-500 hover:text-ink-700'"
              @click="activePage = idx"
            >{{ p.title || `页面 ${idx + 1}` }}</button>
          </div>

          <div class="grid gap-3 lg:grid-cols-2">
            <div
              v-for="widget in currentPageWidgets"
              :key="`widget-${widget.id}`"
              class="rounded-control border border-ink-100 p-3"
            >
              <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <h4 class="truncate text-[13px] font-medium text-ink-800">{{ widget.title || '未命名组件' }}</h4>
                    <span class="tag">{{ widgetTypeLabel(widget.type) }}</span>
                  </div>
                  <p v-if="widget.description" class="mt-0.5 truncate text-[11px] text-ink-400">{{ widget.description }}</p>
                </div>
                <div v-if="supportsChart(widget)" class="flex shrink-0 items-center gap-1 rounded-control bg-ink-50 p-0.5">
                  <button
                    class="rounded px-2 py-0.5 text-[11px]"
                    :class="viewMode(widget) === 'table' ? 'bg-white text-ink-800 shadow-card' : 'text-ink-500'"
                    @click="setViewMode(widget, 'table')"
                  >表格</button>
                  <button
                    class="rounded px-2 py-0.5 text-[11px]"
                    :class="viewMode(widget) === 'chart' ? 'bg-white text-ink-800 shadow-card' : 'text-ink-500'"
                    @click="setViewMode(widget, 'chart')"
                  >图表</button>
                </div>
              </div>

              <div v-if="widget.result?.meta?.error" class="rounded-control bg-rose-50 px-2.5 py-2 text-[12px] text-rose-600">
                {{ widget.result.meta.error }}
              </div>

              <template v-else-if="widget.type === 'kpi'">
                <div class="rounded-control bg-ink-50/60 p-3">
                  <div class="text-[11px] text-ink-500">{{ widget.title }}</div>
                  <div class="mt-1 flex items-baseline gap-1">
                    <span class="text-[24px] font-semibold text-ink-900">{{ kpiValue(widget) }}</span>
                    <span v-if="widget.result?.meta?.unit" class="text-[11px] text-ink-400">{{ widget.result.meta.unit }}</span>
                  </div>
                  <div class="mt-1 flex flex-wrap gap-2 text-[11px] text-ink-400">
                    <span>公式 {{ widget.result?.meta?.formula || '—' }}</span>
                    <span v-if="widget.result?.meta?.comparison && widget.result.meta.comparison !== 'none'">
                      对照 {{ widget.result.meta.comparison }}
                    </span>
                    <span v-if="kpiRow(widget).delta_pct !== null && kpiRow(widget).delta_pct !== undefined">
                      变化 {{ fmtPct(kpiRow(widget).delta_pct) }}
                    </span>
                  </div>
                </div>
              </template>

              <template v-else-if="widget.type === 'text'">
                <p class="whitespace-pre-wrap text-[12px] leading-relaxed text-ink-600">
                  {{ widget.result?.rows?.[0]?.text || '暂无文本内容' }}
                </p>
              </template>

              <template v-else-if="viewMode(widget) === 'chart' && ['table', 'bar', 'line', 'pie'].includes(widget.type)">
                <BarChart
                  v-if="widget.type === 'bar' || widget.type === 'table'"
                  :data="barData(widget)"
                  :height="200"
                  empty-text="该组件没有可绘制的数据"
                />
                <LineChart
                  v-else-if="widget.type === 'line'"
                  :series="lineSeries(widget)"
                  :labels="lineLabels(widget)"
                  :height="200"
                  empty-text="该组件没有可绘制的数据"
                />
                <DonutChart
                  v-else
                  :data="pieData(widget)"
                  :size="160"
                  legend-position="bottom"
                  empty-text="该组件没有可绘制的数据"
                />
              </template>

              <template v-else>
                <div class="max-h-[260px] overflow-auto rounded-control border border-ink-50">
                  <table class="w-full min-w-[320px]">
                    <thead class="bg-ink-50">
                      <tr>
                        <th v-for="col in widget.result?.columns || []" :key="col.key" class="th whitespace-nowrap">
                          {{ col.label || col.key }}
                        </th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-ink-50">
                      <tr v-for="(row, idx) in widgetRows(widget)" :key="`row-${widget.id}-${idx}`">
                        <td v-for="col in widget.result?.columns || []" :key="`${col.key}-${idx}`" class="td whitespace-nowrap text-[11px]">
                          {{ cellText(row[col.key]) }}
                        </td>
                      </tr>
                      <tr v-if="!widgetRows(widget).length">
                        <td class="td text-center text-[11px] text-ink-400" :colspan="Math.max(1, (widget.result?.columns || []).length)">
                          没有返回数据行
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p v-if="rowOverflow(widget)" class="mt-1 text-[10px] text-ink-400">
                  仅展示前 {{ RESULT_ROW_LIMIT }} 行，完整数据请导出 CSV/JSON。
                </p>
              </template>
            </div>
            <div v-if="!currentPageWidgets.length" class="rounded-control bg-ink-50 px-3 py-8 text-center text-[12px] text-ink-400">
              该页面还没有组件
            </div>
          </div>
        </template>
      </div>
    </Modal>

    <!-- 分享 -->
    <Modal :show="shareOpen" :title="`分享报表：${shareTarget?.name || ''}`" width="720px" @close="shareOpen = false">
      <div class="space-y-3">
        <div class="grid gap-2 sm:grid-cols-3">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">有效期（天，0 为长期）</span>
            <input v-model.number="shareDays" class="input" type="number" min="0" max="365" />
          </label>
          <label class="block text-[12px] text-ink-600 sm:col-span-2">
            <span class="mb-1 block">备注</span>
            <input v-model="shareNote" class="input" placeholder="如：给运营周会使用" />
          </label>
        </div>
        <label class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="shareReadonly" type="checkbox" />
          只读访问（公开接口仅执行已发布报表）
        </label>
        <div class="flex justify-end">
          <button class="btn-primary" :disabled="shareSaving" @click="createShare">
            {{ shareSaving ? '创建中…' : '创建分享链接' }}
          </button>
        </div>

        <div v-if="createdShare" class="rounded-control border border-emerald-200 bg-emerald-50 p-3 text-[12px] text-emerald-800">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-medium">新链接已创建</span>
            <span class="font-mono text-[11px]">{{ shareUrl(createdShare) }}</span>
            <button class="ml-auto text-brand-700" @click="copyShare(createdShare)">复制</button>
          </div>
          <p class="mt-1 text-[11px] text-emerald-700">
            令牌 {{ createdShare.token }}，过期时间 {{ createdShare.expires_at ? fmtDT(createdShare.expires_at) : '长期有效' }}。
          </p>
        </div>

        <div class="border-t border-ink-100 pt-2">
          <div class="mb-1.5 flex items-center justify-between text-[12px] text-ink-600">
            <span>已有分享链接</span>
            <button class="text-brand-600" :disabled="shareListLoading" @click="loadShares">
              {{ shareListLoading ? '加载中…' : '刷新' }}
            </button>
          </div>
          <div v-if="shareListError" class="rounded-control bg-rose-50 px-3 py-2 text-[11px] text-rose-600">{{ shareListError }}</div>
          <div v-else-if="!shares.length" class="rounded-control bg-ink-50 px-3 py-3 text-[11px] text-ink-400">
            该报表还没有分享链接
          </div>
          <ul v-else class="divide-y divide-ink-50">
            <li v-for="item in shares" :key="item.id" class="flex flex-wrap items-center gap-2 py-2 text-[11px]">
              <span class="font-mono text-ink-600">{{ item.token }}</span>
              <span class="tag" :class="item.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-ink-100 text-ink-500'">
                {{ item.enabled ? '启用' : '已停用' }}
              </span>
              <span v-if="item.expired" class="tag bg-rose-50 text-rose-600">已过期</span>
              <span class="text-ink-400">{{ item.view_count }} 次访问</span>
              <span class="text-ink-400">{{ item.note || '无备注' }}</span>
              <div class="ml-auto flex gap-2">
                <button class="text-brand-600" @click="copyShare(item)">复制</button>
                <button v-if="item.enabled" class="text-rose-500" @click="disableShare(item)">停用</button>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { reportingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { saveBlob } from '../../utils/download'
import Modal from '../../components/Modal.vue'
import BarChart from '../../components/platform/BarChart.vue'
import LineChart from '../../components/platform/LineChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const app = useAppStore()

const PAGE_SIZES = [10, 20, 50]
const RESULT_ROW_LIMIT = 50
const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已归档' },
]
const DEFAULT_CATEGORIES = ['通用', '运营', '财务', '销售', '管理']
const WIDGET_TYPE_LABELS = {
  table: '表格',
  bar: '柱状图',
  line: '折线图',
  pie: '饼图',
  kpi: '指标卡',
  pivot: '透视表',
  heatmap: '热力图',
  text: '文本',
}

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const q = ref('')
const status = ref('')
const category = ref('')
const favoriteOnly = ref(false)
const loading = ref(false)
const loadedOnce = ref(false)
const error = ref('')
const unavailable = ref('')
const lastLoadedAt = ref(null)

const favoriteIds = ref([])
const datasets = ref([])

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const hasFilters = computed(() => Boolean(q.value.trim() || status.value || category.value || favoriteOnly.value))
const categoryOptions = computed(() => {
  const set = new Set(DEFAULT_CATEGORIES)
  for (const row of items.value) {
    if (row.category) set.add(row.category)
  }
  return Array.from(set)
})
const pageButtons = computed(() => {
  const total = totalPages.value
  const current = page.value
  const start = Math.max(1, Math.min(current - 2, total - 4))
  const end = Math.min(total, start + 4)
  const out = []
  for (let i = start; i <= end; i += 1) out.push(i)
  return out
})
const lastLoadedText = computed(() => {
  const d = lastLoadedAt.value
  if (!d) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
})

function isUnavailable(e) {
  const s = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return s === 404 || s === 405 || /not found|method not allowed|405/i.test(message)
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function fmtInt(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN')
}

function fmtMs(value) {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—'
  if (n < 1000) return `${Math.round(n)} ms`
  if (n < 60000) return `${(n / 1000).toFixed(2)} s`
  return `${(n / 60000).toFixed(1)} min`
}

function fmtPct(value, digits = 1) {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—'
  return `${n.toFixed(digits)}%`
}

function fmtDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function fmtDT(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusLabel(value) {
  const map = { draft: '草稿', published: '已发布', archived: '已归档' }
  return map[value] || value || '未知'
}

function statusClass(value) {
  if (value === 'published' || value === 'success') return 'bg-emerald-50 text-emerald-700'
  if (value === 'draft' || value === 'running') return 'bg-amber-50 text-amber-700'
  if (value === 'archived' || value === 'failed') return 'bg-rose-50 text-rose-600'
  return 'bg-ink-100 text-ink-600'
}

function widgetTypeLabel(value) {
  return WIDGET_TYPE_LABELS[value] || value || '组件'
}

function cellText(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isFavorite(id) {
  return favoriteIds.value.includes(Number(id))
}

// ---------------------------------------------------------------------------
// 列表
// ---------------------------------------------------------------------------

async function load() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (status.value) params.status = status.value
    if (category.value.trim()) params.category = category.value.trim()
    if (favoriteOnly.value) params.favorite = true
    const data = await reportingApi.list('reports/', params)
    items.value = data.items
    count.value = data.count
    if (data.page) page.value = data.page
    lastLoadedAt.value = new Date()
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) {
      unavailable.value = '报表列表接口不存在或方法不可用（404/405）'
    } else {
      error.value = e?.message || '报表列表加载失败'
      app.toastMsg(error.value, 'error')
    }
  } finally {
    loading.value = false
    loadedOnce.value = true
  }
}

async function loadFavorites() {
  try {
    const data = await reportingApi.list('reports/favorites/', { page: 1, page_size: 200 })
    favoriteIds.value = data.items.map((row) => Number(row.report_id)).filter((id) => Number.isFinite(id))
  } catch {
    favoriteIds.value = []
  }
}

async function loadDatasetOptions() {
  if (datasets.value.length) return
  try {
    const data = await reportingApi.list('datasets/', { page: 1, page_size: 200 })
    datasets.value = data.items
  } catch {
    datasets.value = []
  }
}

let searchTimer = null
watch(q, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    page.value = 1
    load()
  }, 320)
})

watch([status, category, favoriteOnly], () => {
  page.value = 1
  load()
})

function applyFilters() {
  page.value = 1
  load()
}

function resetFilters() {
  q.value = ''
  status.value = ''
  category.value = ''
  favoriteOnly.value = false
  page.value = 1
  load()
}

function goPage(next) {
  const target = Math.min(Math.max(1, next), totalPages.value)
  if (target === page.value) return
  page.value = target
  load()
}

function changePageSize(event) {
  const size = Number(event.target.value) || 20
  pageSize.value = size
  page.value = 1
  load()
}

// ---------------------------------------------------------------------------
// 新建 / 编辑
// ---------------------------------------------------------------------------

const formOpen = ref(false)
const formLoading = ref(false)
const saving = ref(false)
const form = ref({})

function emptyForm() {
  return {
    id: null,
    name: '',
    code: '',
    category: '通用',
    description: '',
    dataset_id: '',
    theme: 'light',
    cache_ttl: 300,
    permissions: {},
    originalModel: '',
  }
}

function openCreate() {
  form.value = emptyForm()
  formOpen.value = true
  loadDatasetOptions()
}

async function openEdit(row) {
  form.value = { ...emptyForm(), ...row, dataset_id: '' }
  formOpen.value = true
  formLoading.value = true
  loadDatasetOptions()
  try {
    const detail = await reportingApi.get(`reports/${row.id}/`)
    const permissions = detail?.permissions && typeof detail.permissions === 'object' ? detail.permissions : {}
    form.value = {
      ...emptyForm(),
      ...detail,
      dataset_id: permissions.default_dataset_id ?? '',
      theme: detail.theme || 'light',
      cache_ttl: detail.cache_ttl ?? 300,
      permissions,
    }
  } catch (e) {
    app.toastMsg(e?.message || '报表详情加载失败', 'error')
  } finally {
    formLoading.value = false
  }
}

function closeForm() {
  if (saving.value) return
  formOpen.value = false
}

async function saveForm() {
  const f = form.value
  if (!String(f.name || '').trim()) {
    app.toastMsg('请填写报表名称', 'error')
    return
  }
  if (!String(f.code || '').trim()) {
    app.toastMsg('请填写报表编码', 'error')
    return
  }
  saving.value = true
  try {
    const permissions = { ...(f.permissions || {}) }
    if (f.dataset_id) permissions.default_dataset_id = Number(f.dataset_id)
    else delete permissions.default_dataset_id
    const payload = {
      name: String(f.name).trim(),
      code: String(f.code).trim(),
      category: String(f.category || '').trim() || '通用',
      description: f.description || '',
      theme: f.theme || 'light',
      cache_ttl: Number(f.cache_ttl) || 0,
      permissions,
    }
    if (f.id) {
      await reportingApi.update(`reports/${f.id}/update/`, payload)
      app.toastMsg('报表已保存', 'success')
    } else {
      await reportingApi.create('reports/create/', { ...payload, with_page: true })
      app.toastMsg('报表已创建', 'success')
    }
    formOpen.value = false
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------------------
// 行操作：发布 / 归档 / 克隆 / 收藏
// ---------------------------------------------------------------------------

async function publishReport(row) {
  try {
    await reportingApi.action(`reports/${row.id}/publish/`, {})
    app.toastMsg('报表已发布', 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '发布失败', 'error')
  }
}

async function archiveReport(row) {
  try {
    await reportingApi.action(`reports/${row.id}/archive/`, {})
    app.toastMsg('报表已归档', 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '归档失败', 'error')
  }
}

async function cloneReport(row) {
  try {
    const data = await reportingApi.action(`reports/${row.id}/clone/`, {})
    const name = data?.report?.name || '副本'
    app.toastMsg(`已克隆为「${name}」`, 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '克隆失败', 'error')
  }
}

async function toggleFavorite(row) {
  try {
    const data = await reportingApi.action(`reports/${row.id}/favorite/`, {})
    const id = Number(row.id)
    if (data?.favorited) {
      if (!favoriteIds.value.includes(id)) favoriteIds.value = [...favoriteIds.value, id]
      app.toastMsg('已收藏', 'success')
    } else {
      favoriteIds.value = favoriteIds.value.filter((item) => item !== id)
      app.toastMsg('已取消收藏', 'success')
    }
    if (favoriteOnly.value) await load()
  } catch (e) {
    app.toastMsg(e?.message || '收藏操作失败', 'error')
  }
}

// ---------------------------------------------------------------------------
// 执行参数
// ---------------------------------------------------------------------------

const runOpen = ref(false)
const runTarget = ref(null)
const runDetailLoading = ref(false)
const runSubmitting = ref(false)
const runBypass = ref(false)
const runError = ref('')
const paramFields = ref([])
const paramValues = ref({})
const extraParams = ref([])

function addParamField(map, key, payload) {
  const name = String(key || '').trim()
  if (!name || map.has(name)) return
  map.set(name, { key: name, ...payload })
}

async function openRun(row) {
  runTarget.value = row
  runOpen.value = true
  runError.value = ''
  paramFields.value = []
  paramValues.value = {}
  extraParams.value = []
  runBypass.value = false
  runDetailLoading.value = true
  try {
    const map = new Map()
    const detail = await reportingApi.get(`reports/${row.id}/`)
    for (const p of detail?.pages || []) {
      for (const w of p.widgets || []) {
        for (const f of w.filters || []) {
          const key = f.bound_param || f.field
          addParamField(map, key, {
            label: f.label || f.bound_param || f.field,
            hint: `字段 ${f.field}，操作符 ${f.operator}`,
            placeholder: f.default_value === null || f.default_value === undefined ? '' : String(f.default_value),
            required: false,
            default: f.default_value,
          })
        }
      }
    }
    const datasetId = detail?.permissions?.default_dataset_id
    if (datasetId) {
      try {
        const dataset = await reportingApi.get(`datasets/${datasetId}/`)
        for (const param of dataset?.params || []) {
          addParamField(map, param.name, {
            label: param.description || param.name,
            hint: `${param.ptype}${param.required ? '，必填' : ''}`,
            required: Boolean(param.required),
            default: param.default,
          })
        }
      } catch {
        /* 数据集参数读取失败不阻塞执行 */
      }
    }
    paramFields.value = Array.from(map.values())
    const values = {}
    for (const field of paramFields.value) {
      values[field.key] = field.default === null || field.default === undefined ? '' : String(field.default)
    }
    paramValues.value = values
  } catch (e) {
    runError.value = e?.message || '报表详情加载失败，仍可手动填写参数'
  } finally {
    runDetailLoading.value = false
  }
}

function buildParams() {
  const params = {}
  for (const field of paramFields.value) {
    const value = paramValues.value[field.key]
    if (value !== '' && value !== null && value !== undefined) params[field.key] = value
  }
  for (const row of extraParams.value) {
    const key = String(row.key || '').trim()
    if (!key) continue
    params[key] = row.value
  }
  return params
}

async function submitRun() {
  if (!runTarget.value) return
  runSubmitting.value = true
  runError.value = ''
  try {
    const payload = await reportingApi.action(`reports/${runTarget.value.id}/run/`, {
      params: buildParams(),
      bypass_cache: Boolean(runBypass.value),
    })
    const meta = payload?.meta || {}
    if (meta.status === 'failed') {
      runError.value = meta.error || '报表执行失败'
      app.toastMsg(runError.value, 'error')
      return
    }
    app.toastMsg(meta.cached ? '已命中缓存结果' : '报表执行完成', 'success')
    runOpen.value = false
    resultTarget.value = runTarget.value
    resultPayload.value = payload
    resultError.value = ''
    resultEmpty.value = ''
    resultLoading.value = false
    activePage.value = 0
    viewModes.value = {}
    resultOpen.value = true
  } catch (e) {
    runError.value = e?.message || '执行失败'
    app.toastMsg(runError.value, 'error')
  } finally {
    runSubmitting.value = false
  }
}

// ---------------------------------------------------------------------------
// 结果查看与导出
// ---------------------------------------------------------------------------

const resultOpen = ref(false)
const resultLoading = ref(false)
const resultError = ref('')
const resultEmpty = ref('')
const resultTarget = ref(null)
const resultPayload = ref(null)
const activePage = ref(0)
const viewModes = ref({})

const resultPages = computed(() => (Array.isArray(resultPayload.value?.pages) ? resultPayload.value.pages : []))
const currentPageWidgets = computed(() => {
  const p = resultPages.value[activePage.value]
  return Array.isArray(p?.widgets) ? p.widgets : []
})

function widgetRows(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return rows.slice(0, RESULT_ROW_LIMIT)
}

function rowOverflow(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return rows.length > RESULT_ROW_LIMIT
}

function supportsChart(widget) {
  return ['table', 'bar', 'line', 'pie'].includes(widget?.type)
}

function defaultViewMode(widget) {
  return widget?.type === 'table' ? 'table' : 'chart'
}

function viewMode(widget) {
  return viewModes.value[widget.id] || defaultViewMode(widget)
}

function setViewMode(widget, mode) {
  viewModes.value = { ...viewModes.value, [widget.id]: mode }
}

function kpiRow(widget) {
  return widget?.result?.rows?.[0] || {}
}

function kpiValue(widget) {
  const value = kpiRow(widget).value
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function axisKey(widget) {
  const meta = widget?.result?.meta || {}
  const columns = widget?.result?.columns || []
  return meta.x || meta.name || columns[0]?.key || ''
}

function seriesKeys(widget) {
  const meta = widget?.result?.meta || {}
  const columns = widget?.result?.columns || []
  if (Array.isArray(meta.series) && meta.series.length) return meta.series
  const metrics = columns.filter((c) => c.role === 'metric').map((c) => c.key)
  if (metrics.length) return metrics.slice(0, 3)
  return columns.slice(1, 3).map((c) => c.key)
}

function columnLabel(widget, key) {
  const col = (widget?.result?.columns || []).find((c) => c.key === key)
  return col?.label || key
}

function labelOf(widget, row, index) {
  const key = axisKey(widget)
  const value = key ? row[key] : index
  if (value === null || value === undefined || value === '') return `第 ${index + 1} 项`
  return String(value)
}

function barData(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  const key = seriesKeys(widget)[0]
  return rows.slice(0, 30).map((row, index) => ({
    label: labelOf(widget, row, index),
    value: Number(row[key]) || 0,
  }))
}

function lineLabels(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return rows.map((row, index) => labelOf(widget, row, index))
}

function lineSeries(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return seriesKeys(widget).map((key) => ({
    name: columnLabel(widget, key),
    data: rows.map((row) => {
      const n = Number(row[key])
      return Number.isFinite(n) ? n : null
    }),
  }))
}

function pieData(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  const key = seriesKeys(widget)[0]
  return rows.slice(0, 30).map((row, index) => ({
    label: labelOf(widget, row, index),
    value: Number(row[key]) || 0,
  }))
}

async function openResult(row) {
  if (!row) return
  resultTarget.value = row
  resultOpen.value = true
  resultPayload.value = null
  resultError.value = ''
  resultEmpty.value = ''
  activePage.value = 0
  viewModes.value = {}
  await loadResult(row)
}

async function loadResult(row) {
  if (!row) return
  resultLoading.value = true
  resultError.value = ''
  resultEmpty.value = ''
  try {
    const data = await reportingApi.get(`reports/${row.id}/result/`)
    if (data?.available === false) {
      resultEmpty.value = data.message || '还没有缓存结果，请先执行一次报表'
      resultPayload.value = null
      return
    }
    resultPayload.value = data?.payload || data || null
    if (!resultPayload.value) resultEmpty.value = '结果接口未返回 payload'
  } catch (e) {
    resultPayload.value = null
    resultError.value = isUnavailable(e) ? '结果接口不可用（404/405），请改用「执行」获取实时结果' : (e?.message || '结果加载失败')
  } finally {
    resultLoading.value = false
  }
}

async function reloadResult() {
  if (!resultTarget.value) return
  await loadResult(resultTarget.value)
}

function mimeOf(fmt) {
  return fmt === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8'
}

async function exportReport(row, fmt) {
  if (!row) {
    app.toastMsg('请先选择报表', 'error')
    return
  }
  try {
    const data = await reportingApi.action(`reports/${row.id}/export/`, { fmt, params: {} })
    if (!data?.content) {
      app.toastMsg('导出接口没有返回内容', 'error')
      return
    }
    const filename = data.filename || `${row.code || 'report'}.${fmt}`
    saveBlob(new Blob([data.content], { type: mimeOf(fmt) }), filename)
    app.toastMsg(`已导出 ${filename}`, 'success')
  } catch (e) {
    app.toastMsg(e?.message || '导出失败', 'error')
  }
}

// ---------------------------------------------------------------------------
// 分享链接
// ---------------------------------------------------------------------------

const shareOpen = ref(false)
const shareTarget = ref(null)
const shareDays = ref(7)
const shareNote = ref('')
const shareReadonly = ref(true)
const shareSaving = ref(false)
const shareListLoading = ref(false)
const shareListError = ref('')
const shares = ref([])
const createdShare = ref(null)

async function openShare(row) {
  shareTarget.value = row
  shareOpen.value = true
  shareDays.value = 7
  shareNote.value = ''
  shareReadonly.value = true
  createdShare.value = null
  shares.value = []
  shareListError.value = ''
  await loadShares()
}

async function loadShares() {
  if (!shareTarget.value) return
  shareListLoading.value = true
  shareListError.value = ''
  try {
    const data = await reportingApi.list('shares/', { report_id: shareTarget.value.id, page: 1, page_size: 50 })
    shares.value = data.items
  } catch (e) {
    shares.value = []
    shareListError.value = isUnavailable(e) ? '分享列表接口不可用（404/405）' : (e?.message || '分享列表加载失败')
  } finally {
    shareListLoading.value = false
  }
}

async function createShare() {
  if (!shareTarget.value) return
  shareSaving.value = true
  try {
    const data = await reportingApi.action(`reports/${shareTarget.value.id}/share/`, {
      days: Number(shareDays.value) || 0,
      readonly: Boolean(shareReadonly.value),
      note: shareNote.value,
    })
    createdShare.value = data
    shares.value = [data, ...shares.value]
    app.toastMsg('分享链接已创建', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '创建分享链接失败', 'error')
  } finally {
    shareSaving.value = false
  }
}

async function disableShare(item) {
  try {
    await reportingApi.action(`shares/${item.id}/disable/`, {})
    app.toastMsg('分享链接已停用', 'success')
    await loadShares()
  } catch (e) {
    app.toastMsg(e?.message || '停用失败', 'error')
  }
}

function shareUrl(item) {
  const hint = item?.url_hint || `/api/reporting/share/${item?.token || ''}/`
  if (/^https?:/i.test(hint)) return hint
  return `${window.location.origin}${hint.startsWith('/') ? '' : '/'}${hint}`
}

async function copyShare(item) {
  const text = shareUrl(item)
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const area = document.createElement('textarea')
      area.value = text
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    app.toastMsg('链接已复制', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '复制失败，请手动选择链接', 'error')
  }
}

watch(() => props.reloadToken, () => {
  loadFavorites()
  load()
})

onMounted(() => {
  load()
  loadFavorites()
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})
</script>