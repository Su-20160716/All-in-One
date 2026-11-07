<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 头部 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-start gap-3">
        <div class="grid h-11 w-11 shrink-0 place-items-center rounded-control bg-brand-50 text-[22px]">{{ meta.icon }}</div>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-[16px] font-semibold text-ink-900">{{ meta.name }}</h2>
            <span class="tag-brand">{{ meta.group }}</span>
            <span v-if="featureCount" class="tag">{{ featureCount }} 项能力</span>
            <span v-if="detailFailed" class="tag bg-amber-50 text-amber-600">详情降级</span>
          </div>
          <p class="mt-1 text-[12px] text-ink-500">{{ meta.description }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-if="hasSubscription"
            class="btn-outline"
            :class="subscription.enabled ? 'text-brand-700 border-brand-300' : ''"
            @click="toggleSubscription"
          >{{ subscription.enabled ? '已订阅' : '订阅更新' }}</button>
          <RouterLink to="/biz" class="btn-ghost">← 业务中心</RouterLink>
        </div>
      </div>
      <!-- 页签 -->
      <div class="mt-3 flex gap-1 border-b border-ink-100">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="-mb-px border-b-2 px-3 py-1.5 text-[13px] transition-colors"
          :class="tab === t.key ? 'border-brand-600 font-medium text-brand-700' : 'border-transparent text-ink-500 hover:text-ink-700'"
          @click="switchTab(t.key)"
        >{{ t.label }}</button>
      </div>
    </div>

    <!-- 全局错误提示 -->
    <div v-if="banner" class="card flex flex-wrap items-center gap-2 border-rose-200 bg-rose-50 p-3 text-[12px] text-rose-600">
      <span class="flex-1">{{ banner }}</span>
      <button class="btn-outline px-2 py-0.5" @click="reloadAll">重试</button>
      <button class="btn-ghost px-2 py-0.5" @click="banner = ''">关闭</button>
    </div>

    <!-- 统计卡 -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <div v-for="s in statCards" :key="s.key" class="card p-3">
        <div class="text-[11px] text-ink-400">{{ s.label }}</div>
        <div class="mt-1 text-[18px] font-semibold" :class="s.tone || 'text-ink-800'">
          {{ statsLoading ? '…' : s.value }}
        </div>
      </div>
    </div>

    <!-- ───────────── 记录页签 ───────────── -->
    <section v-if="tab === 'records'" class="space-y-3">
      <!-- 工具栏 -->
      <div class="card flex flex-wrap items-center gap-2 p-3">
        <input v-model="filters.q" class="input w-48" placeholder="搜索标题/标签…" />
        <select v-model="filters.status" class="input w-32">
          <option value="">全部状态</option>
          <option v-for="o in statusOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
        </select>
        <select v-model="filters.category" class="input w-32">
          <option value="">全部分类</option>
          <option v-for="o in categoryOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
        </select>
        <select v-model="filters.priority" class="input w-28">
          <option value="">全部优先级</option>
          <option v-for="o in PRIORITIES" :key="o.key" :value="o.key">{{ o.label }}</option>
        </select>
        <select v-model="filters.owner" class="input w-32">
          <option value="">全部负责人</option>
          <option v-for="m in members" :key="m.id" :value="m.id">{{ m.name || m.username }}</option>
        </select>
        <select v-model="ordering" class="input w-32">
          <option v-for="o in ORDERINGS" :key="o.key" :value="o.key">{{ o.label }}</option>
        </select>
        <label class="flex items-center gap-1 text-[12px] text-ink-600">
          <input v-model="showArchived" type="checkbox" @change="onScopeChange" /> 归档
        </label>
        <label class="flex items-center gap-1 text-[12px] text-ink-600">
          <input v-model="showTrash" type="checkbox" @change="onScopeChange" /> 回收站
        </label>
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <button class="btn-ghost" :disabled="recordsLoading" @click="reloadAll">{{ recordsLoading ? '加载中…' : '刷新' }}</button>
          <button class="btn-primary" @click="openCreate">＋ 新建</button>
          <button class="btn-outline" @click="pickImport">导入 CSV</button>
          <button class="btn-outline" @click="exportCsv">导出 CSV</button>
          <input ref="fileInput" type="file" accept=".csv,text/csv" class="hidden" @change="onImportFile" />
        </div>
      </div>

      <!-- 回收站说明 -->
      <div v-if="showTrash" class="card border-amber-200 bg-amber-50 p-2.5 text-[12px] text-amber-700">
        当前处于回收站视图，仅显示已删除记录；可逐条「恢复」或批量选中后删除。
      </div>

      <!-- 导入结果 -->
      <div v-if="importResult" class="card p-3 text-[12px]">
        <div class="flex items-center gap-2">
          <span class="font-medium text-ink-700">导入完成</span>
          <span class="tag">共 {{ importResult.total }}</span>
          <span class="tag bg-emerald-50 text-emerald-600">成功 {{ importResult.created }}</span>
          <span v-if="importErrors.length" class="tag bg-rose-50 text-rose-600">失败 {{ importErrors.length }}</span>
          <button class="btn-ghost ml-auto px-2 py-0.5" @click="importResult = null">关闭</button>
        </div>
        <ul v-if="importErrors.length" class="mt-1.5 list-disc pl-5 text-rose-600">
          <li v-for="err in importErrors.slice(0, 8)" :key="err.row">第 {{ err.row }} 行：{{ err.message }}</li>
        </ul>
      </div>

      <!-- 批量条 -->
      <div v-if="selected.length" class="card flex flex-wrap items-center gap-2 border-brand-200 bg-brand-50/50 p-2.5">
        <span class="text-[12px] font-medium text-ink-700">已选 {{ selected.length }} 条</span>
        <select v-model="bulkStatus" class="input w-28">
          <option value="">改状态…</option>
          <option v-for="o in statusOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
        </select>
        <button class="btn-outline px-2 py-1" :disabled="!bulkStatus" @click="applyBulk('status')">应用</button>
        <select v-model="bulkOwner" class="input w-32">
          <option value="">指派给…</option>
          <option v-for="m in members" :key="m.id" :value="m.id">{{ m.name || m.username }}</option>
        </select>
        <button class="btn-outline px-2 py-1" :disabled="bulkOwner === ''" @click="applyBulk('owner')">应用</button>
        <input v-model="bulkTags" class="input w-32" placeholder="打标签…" />
        <button class="btn-outline px-2 py-1" :disabled="!bulkTags.trim()" @click="applyBulk('tag')">应用</button>
        <button class="btn-outline px-2 py-1" @click="applyBulk('archive')">归档</button>
        <button class="btn-danger px-2 py-1" @click="applyBulk('delete')">删除</button>
        <button class="btn-ghost ml-auto px-2 py-1" @click="selected = []">取消选择</button>
      </div>

      <!-- 记录表格 -->
      <div class="card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full min-w-[1020px]">
            <thead class="bg-ink-50/70">
              <tr>
                <th class="th w-9"><input type="checkbox" :checked="allSelected" @change="toggleAll" /></th>
                <th class="th">标题</th>
                <th class="th w-24">状态</th>
                <th class="th w-24">分类</th>
                <th class="th w-20">优先级</th>
                <th class="th w-28">负责人</th>
                <th class="th w-28">到期日</th>
                <th class="th w-36">标签</th>
                <th class="th w-32">更新时间</th>
                <th class="th w-44">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="recordsLoading" class="border-t border-ink-50">
                <td class="td text-center text-ink-400" colspan="10">加载中…</td>
              </tr>
              <tr v-else-if="listError" class="border-t border-ink-50">
                <td class="td text-center text-rose-600" colspan="10">
                  {{ listError }}
                  <button class="ml-2 underline" @click="loadRecords">重试</button>
                </td>
              </tr>
              <tr v-else-if="!records.length" class="border-t border-ink-50">
                <td class="td text-center text-ink-400" colspan="10">
                  <div class="py-8">
                    <div class="text-[26px]">{{ showTrash ? '🗑' : '📭' }}</div>
                    <div class="mt-1">{{ showTrash ? '回收站为空' : '暂无记录，点击「新建」录入第一条' }}</div>
                    <button v-if="!showTrash" class="btn-primary mt-2" @click="openCreate">＋ 新建记录</button>
                  </div>
                </td>
              </tr>
              <template v-else>
                <tr v-for="r in records" :key="r.id" class="border-t border-ink-50 hover:bg-ink-50/50">
                  <td class="td"><input v-model="selected" type="checkbox" :value="r.id" /></td>
                  <td class="td">
                    <button class="max-w-[320px] truncate text-left font-medium text-ink-800 hover:text-brand-600" @click="openDetail(r)">{{ r.title }}</button>
                    <div class="mt-0.5 flex flex-wrap items-center gap-1">
                      <span v-if="r.favorite" class="text-[11px] text-amber-500">★ 收藏</span>
                      <span v-if="r.is_deleted" class="tag bg-rose-50 text-rose-600">已删除</span>
                      <span v-else-if="r.archived" class="tag">已归档</span>
                    </div>
                  </td>
                  <td class="td">
                    <span class="tag" :class="statusClass(r.status)">{{ r.status_label || r.status || '—' }}</span>
                  </td>
                  <td class="td">{{ r.category || '—' }}</td>
                  <td class="td">
                    <span class="tag" :class="priorityColor(r.priority)">{{ priorityLabel(r.priority) }}</span>
                  </td>
                  <td class="td">{{ ownerName(r.owner) }}</td>
                  <td class="td" :class="isOverdue(r) ? 'font-medium text-rose-600' : ''">
                    {{ r.due_date ? formatDate(r.due_date) : '—' }}
                  </td>
                  <td class="td">
                    <template v-if="(r.tags || []).length">
                      <span v-for="t in (r.tags || []).slice(0, 2)" :key="t" class="tag mr-1">{{ t }}</span>
                      <span v-if="(r.tags || []).length > 2" class="text-[11px] text-ink-400">+{{ r.tags.length - 2 }}</span>
                    </template>
                    <span v-else class="text-ink-300">—</span>
                  </td>
                  <td class="td text-[12px] text-ink-400">{{ formatTime(r.updated_at) }}</td>
                  <td class="td">
                    <div class="flex flex-wrap gap-0.5 text-[12px]">
                      <button class="btn-ghost px-1.5 py-0.5" title="详情" @click="openDetail(r)">👁</button>
                      <button class="btn-ghost px-1.5 py-0.5" title="编辑" @click="openEdit(r)">✎</button>
                      <button class="btn-ghost px-1.5 py-0.5" :class="r.favorite ? 'text-amber-500' : ''" title="收藏" @click="toggleFavorite(r)">{{ r.favorite ? '★' : '☆' }}</button>
                      <button class="btn-ghost px-1.5 py-0.5" title="复制" @click="duplicate(r)">⧉</button>
                      <template v-if="r.is_deleted">
                        <button class="btn-ghost px-1.5 py-0.5 text-emerald-600" title="恢复" @click="restore(r)">↺</button>
                      </template>
                      <template v-else>
                        <button class="btn-ghost px-1.5 py-0.5" :title="r.archived ? '取消归档' : '归档'" @click="toggleArchive(r)">{{ r.archived ? '⇱' : '🗄' }}</button>
                        <button class="btn-ghost px-1.5 py-0.5 text-rose-500" title="删除" @click="removeRecord(r)">✕</button>
                      </template>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
          <span>共 {{ totalCount }} 条 · 第 {{ page }} / {{ totalPages }} 页</span>
          <span v-if="summary.overdue" class="text-rose-500">其中逾期 {{ summary.overdue }}</span>
          <select :value="pageSize" class="input ml-auto w-24 py-0.5" @change="changePageSize">
            <option :value="10">10 条/页</option>
            <option :value="20">20 条/页</option>
            <option :value="50">50 条/页</option>
          </select>
          <button class="btn-outline px-2 py-0.5" :disabled="page <= 1 || recordsLoading" @click="goPage(page - 1)">上一页</button>
          <button class="btn-outline px-2 py-0.5" :disabled="page >= totalPages || recordsLoading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </section>

    <!-- ───────────── 分析页签 ───────────── -->
    <section v-else-if="tab === 'analytics'" class="space-y-3">
      <div class="flex items-center gap-2">
        <h3 class="text-[14px] font-semibold text-ink-800">数据分析</h3>
        <span v-if="analyticsError" class="text-[12px] text-rose-600">{{ analyticsError }}</span>
        <button class="btn-outline ml-auto" :disabled="analyticsLoading" @click="loadAnalytics">{{ analyticsLoading ? '加载中…' : '刷新分析' }}</button>
      </div>

      <div v-if="analyticsLoading && !trend.items.length" class="card grid h-48 place-items-center text-[13px] text-ink-400">分析数据加载中…</div>

      <template v-else>
        <!-- 趋势 -->
        <div class="card p-4">
          <div class="mb-3 flex flex-wrap items-center gap-3">
            <h4 class="text-[13px] font-semibold text-ink-800">近 {{ trend.days || 30 }} 天趋势</h4>
            <span class="flex items-center gap-1 text-[11px] text-ink-500"><i class="inline-block h-2 w-2 rounded-sm bg-brand-400"></i>新建</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-500"><i class="inline-block h-2 w-2 rounded-sm bg-emerald-400"></i>完成</span>
          </div>
          <div v-if="trend.items.length" class="flex h-40 items-end gap-[2px] overflow-x-auto">
            <div
              v-for="d in trend.items"
              :key="d.date"
              class="flex h-full min-w-[6px] flex-1 items-end gap-px"
              :title="`${d.date} · 新建 ${d.created} · 完成 ${d.closed}`"
            >
              <div class="w-1/2 rounded-t-sm bg-brand-400" :style="{ height: barHeight(d.created) }"></div>
              <div class="w-1/2 rounded-t-sm bg-emerald-400" :style="{ height: barHeight(d.closed) }"></div>
            </div>
          </div>
          <div v-else class="py-10 text-center text-[12px] text-ink-400">暂无趋势数据</div>
          <div v-if="trend.items.length" class="mt-1 flex justify-between text-[10px] text-ink-400">
            <span>{{ trend.items[0].date }}</span>
            <span>{{ trend.items[trend.items.length - 1].date }}</span>
          </div>
        </div>

        <!-- 分布 -->
        <div class="grid gap-3 lg:grid-cols-2">
          <div v-for="d in distributionCards" :key="d.field" class="card p-4">
            <h4 class="mb-2 text-[13px] font-semibold text-ink-800">{{ d.title }}</h4>
            <div v-if="d.items.length" class="space-y-2">
              <div v-for="it in d.items" :key="it.key">
                <div class="flex items-center justify-between text-[12px]">
                  <span class="truncate text-ink-600">{{ it.label || it.key || '未填写' }}</span>
                  <span class="ml-2 shrink-0 text-ink-400">{{ it.count }} · {{ percentText(it.percent) }}%</span>
                </div>
                <div class="mt-0.5 h-1.5 overflow-hidden rounded-pill bg-ink-100">
                  <div class="h-full rounded-pill bg-brand-500" :style="{ width: barWidth(it.percent) }"></div>
                </div>
              </div>
            </div>
            <div v-else class="py-6 text-center text-[12px] text-ink-400">暂无分布数据</div>
          </div>
        </div>

        <div class="grid gap-3 lg:grid-cols-2">
          <!-- 逾期清单 -->
          <div class="card p-4">
            <div class="mb-2 flex items-center gap-2">
              <h4 class="text-[13px] font-semibold text-ink-800">逾期清单</h4>
              <span class="tag bg-rose-50 text-rose-600">{{ overdue.count }}</span>
            </div>
            <ul v-if="overdue.results.length" class="divide-y divide-ink-50">
              <li v-for="r in overdue.results.slice(0, 10)" :key="r.id" class="flex items-center gap-2 py-1.5 text-[12px]">
                <button class="min-w-0 flex-1 truncate text-left text-ink-700 hover:text-brand-600" @click="openDetail(r)">{{ r.title }}</button>
                <span class="shrink-0 text-rose-500">{{ formatDate(r.due_date) }}</span>
                <span class="w-20 shrink-0 truncate text-ink-400">{{ ownerName(r.owner) }}</span>
              </li>
            </ul>
            <div v-else class="py-6 text-center text-[12px] text-ink-400">没有逾期记录</div>
          </div>

          <!-- 数据质量 -->
          <div class="card p-4">
            <div class="mb-2 flex items-center gap-2">
              <h4 class="text-[13px] font-semibold text-ink-800">数据质量</h4>
              <span class="tag" :class="qualityTone">{{ quality.score == null ? '—' : quality.score }} 分</span>
              <span v-if="quality.checked" class="text-[11px] text-ink-400">检查 {{ quality.checked }} 条</span>
            </div>
            <ul v-if="quality.issues.length" class="space-y-1.5">
              <li v-for="it in quality.issues" :key="it.key" class="flex items-center gap-2 text-[12px]">
                <span class="min-w-0 flex-1 truncate text-ink-600">{{ it.label || it.key }}</span>
                <span class="tag bg-amber-50 text-amber-600">{{ it.count }}</span>
                <span v-if="(it.sample_ids || []).length" class="text-[11px] text-ink-400">样例 #{{ it.sample_ids.slice(0, 3).join(', #') }}</span>
              </li>
            </ul>
            <div v-else class="py-6 text-center text-[12px] text-ink-400">未发现质量问题</div>
          </div>
        </div>
      </template>
    </section>

    <!-- ───────────── 设置页签 ───────────── -->
    <section v-else class="space-y-3">
      <!-- 能力清单 -->
      <div class="card p-4">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">模块能力清单</h3>
          <span class="tag">{{ featureCount }} 项</span>
          <span v-if="detailFailed" class="text-[12px] text-rose-600">模块详情接口不可用，能力清单暂不可见</span>
          <span class="ml-auto font-mono text-[11px] text-ink-400">/api/biz/{{ slug }}/</span>
        </div>
        <div v-if="featureGroups.length" class="mt-3 space-y-3">
          <div v-for="g in featureGroups" :key="g.name">
            <div class="mb-1 flex items-center gap-2">
              <h4 class="text-[12px] font-semibold text-ink-700">{{ g.name }}</h4>
              <span class="text-[11px] text-ink-400">{{ g.items.length }} 项</span>
            </div>
            <ul class="divide-y divide-ink-50 rounded-control border border-ink-100">
              <li v-for="f in g.items" :key="f.key" class="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[12px]">
                <span class="rounded-pill px-1.5 py-0.5 font-mono text-[10px] font-semibold" :class="f.method === 'GET' ? 'bg-sky-100 text-sky-700' : 'bg-violet-100 text-violet-700'">{{ f.method || 'POST' }}</span>
                <span class="font-medium text-ink-700">{{ f.name }}</span>
                <span class="min-w-0 flex-1 truncate text-ink-400">{{ f.desc }}</span>
                <code class="shrink-0 rounded bg-ink-50 px-1.5 py-0.5 font-mono text-[10px] text-ink-500">{{ f.endpoint }}</code>
              </li>
            </ul>
          </div>
        </div>
        <div v-else-if="!detail" class="mt-3 text-[12px] text-ink-400">能力清单加载中…</div>
        <div v-else class="mt-3 text-[12px] text-ink-400">该模块暂未上报能力清单。</div>
      </div>

      <!-- 保存视图 -->
      <div class="card p-4">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">保存视图</h3>
          <span class="tag">{{ savedViews.length }}</span>
          <div class="ml-auto flex items-center gap-2">
            <input v-model="viewName" class="input w-44" placeholder="视图名称，如：本周逾期" />
            <button class="btn-outline" :disabled="!viewName.trim()" @click="saveView">保存当前筛选</button>
          </div>
        </div>
        <ul v-if="savedViews.length" class="mt-3 divide-y divide-ink-50 rounded-control border border-ink-100">
          <li v-for="v in savedViews" :key="v.id" class="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px]">
            <span class="font-medium text-ink-700">{{ v.name }}</span>
            <span class="min-w-0 flex-1 truncate text-[11px] text-ink-400">{{ viewSummary(v) }}</span>
            <button class="btn-outline px-2 py-0.5" @click="applyView(v)">应用</button>
            <button class="btn-ghost px-2 py-0.5 text-rose-500" @click="removeView(v)">删除</button>
          </li>
        </ul>
        <div v-else class="mt-3 text-[12px] text-ink-400">暂无保存视图；设置好筛选后输入名称保存，下次一键还原。</div>
      </div>

      <!-- 订阅设置 -->
      <div v-if="hasSubscription" class="card p-4">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">订阅设置</h3>
          <span class="ml-auto text-[11px] text-ink-400">
            上次发送：{{ subscription.last_sent_at ? formatTime(subscription.last_sent_at) : '从未发送' }}
          </span>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-3 text-[13px]">
          <label class="flex items-center gap-1.5">
            <input v-model="subscription.enabled" type="checkbox" /> 启用订阅
          </label>
          <select v-model="subscription.frequency" class="input w-32">
            <option value="daily">每日</option>
            <option value="weekly">每周</option>
            <option value="monthly">每月</option>
          </select>
          <button class="btn-primary" @click="saveSubscription">保存订阅</button>
        </div>
      </div>
    </section>

    <!-- ───────────── 新建/编辑弹窗 ───────────── -->
    <Modal v-model="formOpen" :title="form.id ? '编辑记录' : '新建记录'" width="680px">
      <div class="space-y-3">
        <div>
          <label class="mb-1 block text-[12px] font-medium text-ink-600">标题 <span class="text-rose-500">*</span></label>
          <input v-model="form.title" class="input" placeholder="请输入标题" @keyup.enter="submitForm" />
        </div>
        <div class="grid gap-2 sm:grid-cols-2">
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">状态</label>
            <select v-if="statusOptions.length" v-model="form.status" class="input">
              <option value="">未设置</option>
              <option v-for="o in statusOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
            </select>
            <input v-else v-model="form.status" class="input" placeholder="状态" />
          </div>
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">分类</label>
            <select v-if="categoryOptions.length" v-model="form.category" class="input">
              <option value="">未设置</option>
              <option v-for="o in categoryOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
            </select>
            <input v-else v-model="form.category" class="input" placeholder="分类" />
          </div>
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">优先级</label>
            <select v-model="form.priority" class="input">
              <option value="">未设置</option>
              <option v-for="o in PRIORITIES" :key="o.key" :value="o.key">{{ o.label }}</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">负责人</label>
            <select v-model="form.owner_id" class="input">
              <option value="">未指派</option>
              <option v-for="m in members" :key="m.id" :value="m.id">{{ m.name || m.username }}</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">到期日</label>
            <input v-model="form.due_date" type="date" class="input" />
          </div>
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">标签（逗号分隔）</label>
            <input v-model="form.tags" class="input" placeholder="如：重点, 续约" />
          </div>
        </div>

        <!-- 模块自定义字段 -->
        <div v-if="dynamicFields.length" class="rounded-control border border-ink-100 p-3">
          <div class="mb-2 text-[12px] font-semibold text-ink-600">模块字段</div>
          <div class="grid gap-2 sm:grid-cols-2">
            <div v-for="f in dynamicFields" :key="f.key">
              <label class="mb-1 block text-[12px] text-ink-500">
                {{ f.label || f.key }}<span v-if="f.required" class="text-rose-500"> *</span>
              </label>
              <select v-if="f.type === 'select'" v-model="form.data[f.key]" class="input">
                <option value="">未设置</option>
                <option v-for="o in normOptions(f.options)" :key="o.key" :value="o.key">{{ o.label }}</option>
              </select>
              <label v-else-if="f.type === 'bool' || f.type === 'boolean'" class="flex items-center gap-1.5 pt-1 text-[13px] text-ink-700">
                <input v-model="form.data[f.key]" type="checkbox" /> 是
              </label>
              <textarea v-else-if="f.type === 'textarea'" v-model="form.data[f.key]" class="input h-16 resize-none"></textarea>
              <input v-else-if="f.type === 'number'" v-model.number="form.data[f.key]" type="number" class="input" />
              <input v-else-if="f.type === 'date'" v-model="form.data[f.key]" type="date" class="input" />
              <input v-else v-model="form.data[f.key]" class="input" />
            </div>
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-1">
          <button class="btn-ghost" @click="formOpen = false">取消</button>
          <button class="btn-primary" :disabled="saving" @click="submitForm">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Modal>

    <!-- ───────────── 详情抽屉 ───────────── -->
    <Teleport to="body">
      <div v-if="detailOpen" class="fixed inset-0 z-[95] bg-ink-900/40" @click.self="closeDetail">
        <aside class="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col bg-white shadow-pop">
          <header class="flex items-center gap-2 border-b border-ink-100 px-4 py-3">
            <span class="tag-brand shrink-0">{{ meta.icon }} {{ meta.name }}</span>
            <h3 class="min-w-0 flex-1 truncate text-[14px] font-semibold text-ink-900">{{ current?.title }}</h3>
            <button class="btn-ghost px-2 py-0.5" title="关闭" @click="closeDetail">✕</button>
          </header>

          <div class="flex-1 space-y-4 overflow-y-auto p-4">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="statusClass(current?.status)">{{ current?.status_label || current?.status || '—' }}</span>
              <span v-if="current?.priority" class="tag" :class="priorityColor(current.priority)">{{ priorityLabel(current.priority) }}</span>
              <span v-if="current?.category" class="tag">{{ current.category }}</span>
              <span v-if="current?.is_deleted" class="tag bg-rose-50 text-rose-600">已删除</span>
              <span v-else-if="current?.archived" class="tag">已归档</span>
              <span v-if="current?.favorite" class="tag bg-amber-50 text-amber-600">★ 已收藏</span>
            </div>

            <div class="flex flex-wrap gap-1.5">
              <button class="btn-outline px-2 py-1" @click="toggleFavorite(current)">{{ current?.favorite ? '取消收藏' : '收藏' }}</button>
              <button class="btn-outline px-2 py-1" @click="duplicate(current)">复制</button>
              <button class="btn-outline px-2 py-1" @click="openEdit(current)">编辑</button>
              <button v-if="current?.is_deleted" class="btn-outline px-2 py-1 text-emerald-600" @click="restore(current)">恢复</button>
              <template v-else>
                <button class="btn-outline px-2 py-1" @click="toggleArchive(current)">{{ current?.archived ? '取消归档' : '归档' }}</button>
                <button class="btn-danger px-2 py-1" @click="removeRecord(current)">删除</button>
              </template>
            </div>

            <div class="grid grid-cols-2 gap-2 text-[12px]">
              <div><span class="text-ink-400">负责人：</span>{{ ownerName(current?.owner) }}</div>
              <div><span class="text-ink-400">部门：</span>{{ current?.department || '—' }}</div>
              <div><span class="text-ink-400">到期日：</span><span :class="isOverdue(current) ? 'text-rose-600' : ''">{{ current?.due_date ? formatDate(current.due_date) : '—' }}</span></div>
              <div><span class="text-ink-400">创建时间：</span>{{ formatTime(current?.created_at) }}</div>
              <div><span class="text-ink-400">更新时间：</span>{{ formatTime(current?.updated_at) }}</div>
              <div><span class="text-ink-400">记录 ID：</span>#{{ current?.id }}</div>
            </div>

            <div v-if="(current?.tags || []).length" class="flex flex-wrap gap-1">
              <span v-for="t in current.tags" :key="t" class="tag">{{ t }}</span>
            </div>

            <div>
              <h4 class="mb-1 text-[12px] font-semibold text-ink-700">字段</h4>
              <dl v-if="fieldRows.length" class="grid grid-cols-1 gap-1.5 rounded-control border border-ink-100 p-3 text-[12px] sm:grid-cols-2">
                <div v-for="row in fieldRows" :key="row.key" class="min-w-0">
                  <dt class="text-ink-400">{{ row.label }}</dt>
                  <dd class="break-words text-ink-700">{{ row.value }}</dd>
                </div>
              </dl>
              <div v-else class="text-[12px] text-ink-400">该记录没有额外字段</div>
            </div>

            <div>
              <h4 class="mb-1 text-[12px] font-semibold text-ink-700">原始数据</h4>
              <pre class="max-h-48 overflow-auto whitespace-pre-wrap rounded-control bg-ink-900 p-2.5 font-mono text-[11px] leading-relaxed text-ink-100">{{ rawData }}</pre>
            </div>

            <div>
              <h4 class="mb-1 flex items-center gap-2 text-[12px] font-semibold text-ink-700">
                评论 <span class="tag">{{ comments.length }}</span>
              </h4>
              <ul v-if="comments.length" class="space-y-2">
                <li v-for="c in comments" :key="c.id" class="rounded-control bg-ink-50 p-2 text-[12px]">
                  <div class="flex items-center gap-1.5 text-[11px] text-ink-400">
                    <span class="font-medium text-ink-600">{{ ownerName(c.actor || c.user) }}</span>
                    <span>{{ formatTime(c.created_at || c.at) }}</span>
                  </div>
                  <div class="mt-0.5 whitespace-pre-wrap text-ink-700">{{ c.content || c.body || c.text }}</div>
                </li>
              </ul>
              <div v-else class="text-[12px] text-ink-400">暂无评论</div>
              <div class="mt-2 flex gap-2">
                <input v-model="commentText" class="input flex-1" placeholder="写下评论，回车发送" @keyup.enter="postComment" />
                <button class="btn-primary" :disabled="!commentText.trim() || commentSending" @click="postComment">{{ commentSending ? '发送中…' : '发表' }}</button>
              </div>
            </div>

            <div>
              <h4 class="mb-1 text-[12px] font-semibold text-ink-700">时间线</h4>
              <ul v-if="timeline.length" class="space-y-1.5 border-l-2 border-ink-100 pl-3">
                <li v-for="(e, i) in timeline" :key="i" class="text-[12px]">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="tag" :class="e.kind === 'comment' ? 'bg-sky-50 text-sky-600' : 'bg-ink-100 text-ink-500'">{{ e.kind === 'comment' ? '评论' : '活动' }}</span>
                    <span class="font-medium text-ink-700">{{ e.label || e.action }}</span>
                    <span class="text-[11px] text-ink-400">{{ ownerName(e.actor) }} · {{ formatTime(e.at) }}</span>
                  </div>
                  <div v-if="e.content || e.detail" class="mt-0.5 whitespace-pre-wrap text-[11px] text-ink-500">{{ e.content || e.detail }}</div>
                </li>
              </ul>
              <div v-else class="text-[12px] text-ink-400">暂无时间线记录</div>
            </div>
          </div>
        </aside>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { bizApi } from '../../api/bizx'
import { findBizModule } from '../../biz/catalog'
import { t } from '../../i18n'
import { useAppStore } from '../../stores/app'
import { formatDate, formatTime, priorityColor } from '../../utils/format'
import { saveBlob, describeDownloadError } from '../../utils/download'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  module: { type: String, required: true },
})

const app = useAppStore()
const slug = computed(() => props.module)

const tabs = [
  { key: 'records', label: '记录' },
  { key: 'analytics', label: '分析' },
  { key: 'settings', label: '设置' },
]

const PRIORITIES = [
  { key: 'low', label: '低' },
  { key: 'normal', label: '普通' },
  { key: 'high', label: '高' },
  { key: 'urgent', label: '紧急' },
]

const ORDERINGS = [
  { key: '-updated_at', label: '最近更新' },
  { key: '-created_at', label: '最新创建' },
  { key: 'due_date', label: '到期日 ↑' },
  { key: '-due_date', label: '到期日 ↓' },
  { key: 'title', label: '标题 A-Z' },
]

// ---------------- 模块元数据 ----------------
const detail = ref(null)
const detailFailed = ref(false)
const meta = computed(() => {
  const c = findBizModule(slug.value) || { name: slug.value, group: '业务模块', icon: '🧩', description: '' }
  const d = detail.value
  return {
    name: d?.name || c.name,
    group: d?.group || c.group,
    icon: d?.icon || c.icon,
    description: d?.description || c.description,
  }
})
const featureCount = computed(() => detail.value?.features?.length || 0)

// 动态路由 /biz/:slug 的 meta.title 只有“业务模块”，按真实模块名回填标签页标题
watch(
  () => meta.value.name,
  (name) => {
    if (name) document.title = `${name} · ${t('app.name', '全能协作平台')}`
  },
  { immediate: true }
)
const hasSubscription = computed(() => {
  const list = detail.value?.features || []
  return list.some((f) => /subscription|订阅/i.test(`${f.key || ''} ${f.name || ''} ${f.endpoint || ''}`))
})

// 状态/分类选项：后端是 [{key,label}] 或字符串数组都兼容
function normOptions(list) {
  if (!Array.isArray(list)) return []
  return list.map((o) => {
    if (typeof o === 'string') return { key: o, label: o }
    const key = o?.key ?? o?.value ?? o?.label ?? ''
    return { key, label: o?.label ?? o?.name ?? String(key) }
  })
}
const statusOptions = computed(() => normOptions(detail.value?.statuses))
const categoryOptions = computed(() => normOptions(detail.value?.categories))
const BUILTIN_KEYS = new Set(['title', 'status', 'category', 'priority', 'owner', 'owner_id', 'due_date', 'tags'])
const dynamicFields = computed(() =>
  (detail.value?.fields || []).filter((f) => f && f.key && !BUILTIN_KEYS.has(f.key))
)

// ---------------- 页签 / 提示 ----------------
const tab = ref('records')
const banner = ref('')

function fail(e, fallback) {
  app.toastMsg(e?.message || fallback, 'error')
}

// ---------------- 成员 ----------------
const members = ref([])
async function loadMembers() {
  try {
    members.value = (await bizApi.members()) || []
  } catch (e) {
    members.value = []
  }
}

// ---------------- 统计 ----------------
const stats = ref(null)
const statsLoading = ref(false)
const statCards = computed(() => {
  const s = stats.value || {}
  const rateRaw = s.completion_rate
  let rateText = '—'
  if (rateRaw != null && rateRaw !== '' && Number.isFinite(Number(rateRaw))) {
    const rate = Number(rateRaw)
    rateText = `${Math.round(rate <= 1 ? rate * 100 : rate)}%`
  }
  return [
    { key: 'total', label: '总数', value: num(s.total) },
    { key: 'active', label: '活跃', value: num(s.active), tone: 'text-brand-600' },
    { key: 'done', label: '完成', value: num(s.done), tone: 'text-emerald-600' },
    { key: 'overdue', label: '逾期', value: num(s.overdue), tone: 'text-rose-600' },
    { key: 'rate', label: '完成率', value: rateText },
    { key: 'new7d', label: '近 7 天新增', value: num(s.new_7d) },
  ]
})
function num(v) {
  return v == null ? '—' : Number(v)
}
async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await bizApi.stats(slug.value)
    if (banner.value.startsWith('统计接口')) banner.value = ''
  } catch (e) {
    stats.value = null
    banner.value = '统计接口暂不可用，统计卡显示为「—」。'
  } finally {
    statsLoading.value = false
  }
}

// ---------------- 记录列表 ----------------
const records = ref([])
const totalCount = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summary = reactive({ total: 0, overdue: 0 })
const recordsLoading = ref(false)
const listError = ref('')
const selected = ref([])
const filters = reactive({ q: '', status: '', category: '', priority: '', owner: '' })
const ordering = ref('-updated_at')
const showArchived = ref(false)
const showTrash = ref(false)
const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize.value)))
const allSelected = computed(
  () => records.value.length > 0 && records.value.every((r) => selected.value.includes(r.id))
)

function queryParams(withPaging = true) {
  const p = {}
  if (filters.q.trim()) p.q = filters.q.trim()
  if (filters.status) p.status = filters.status
  if (filters.category) p.category = filters.category
  if (filters.priority) p.priority = filters.priority
  if (filters.owner !== '' && filters.owner != null) p.owner = filters.owner
  if (ordering.value) p.ordering = ordering.value
  if (showArchived.value && !showTrash.value) p.archived = 1
  if (showTrash.value) p.deleted = 1
  if (withPaging) {
    p.page = page.value
    p.page_size = pageSize.value
  }
  return p
}

let recordsSeq = 0
async function loadRecords() {
  const seq = ++recordsSeq
  recordsLoading.value = true
  listError.value = ''
  try {
    const d = (await bizApi.records(slug.value, queryParams())) || {}
    if (seq !== recordsSeq) return
    records.value = Array.isArray(d.results) ? d.results : []
    totalCount.value = Number(d.count) || 0
    if (d.page) page.value = Number(d.page) || 1
    summary.total = d.summary?.total ?? totalCount.value
    summary.overdue = d.summary?.overdue ?? 0
    selected.value = selected.value.filter((id) => records.value.some((r) => r.id === id))
  } catch (e) {
    if (seq !== recordsSeq) return
    records.value = []
    totalCount.value = 0
    listError.value = e?.message || '记录加载失败'
  } finally {
    if (seq === recordsSeq) recordsLoading.value = false
  }
}

function toggleAll() {
  if (allSelected.value) selected.value = []
  else selected.value = records.value.map((r) => r.id)
}
function goPage(n) {
  page.value = Math.min(Math.max(1, n), totalPages.value)
  loadRecords()
}
function changePageSize(e) {
  pageSize.value = Number(e.target.value) || 20
  page.value = 1
  loadRecords()
}
function onScopeChange() {
  if (showTrash.value) showArchived.value = false
  page.value = 1
  selected.value = []
  loadRecords()
}

// 搜索防抖 300ms
let searchTimer = null
watch(
  () => filters.q,
  () => {
    clearTimeout(searchTimer)
    searchTimer = setTimeout(() => {
      page.value = 1
      loadRecords()
    }, 300)
  }
)
// 其它筛选即时生效
watch([() => filters.status, () => filters.category, () => filters.priority, () => filters.owner, ordering], () => {
  page.value = 1
  selected.value = []
  loadRecords()
})

// ---------------- 行内操作 ----------------
function ownerName(o) {
  if (!o) return '—'
  if (typeof o === 'string') return o
  return o.name || o.username || '—'
}
function priorityLabel(p) {
  const hit = PRIORITIES.find((x) => x.key === p)
  return hit ? hit.label : p || '—'
}
const STATUS_COLOR = {
  todo: 'bg-ink-100 text-ink-500',
  open: 'bg-sky-50 text-sky-600',
  new: 'bg-sky-50 text-sky-600',
  doing: 'bg-sky-50 text-sky-600',
  in_progress: 'bg-sky-50 text-sky-600',
  pending: 'bg-amber-50 text-amber-600',
  review: 'bg-violet-50 text-violet-600',
  approved: 'bg-emerald-50 text-emerald-600',
  done: 'bg-emerald-50 text-emerald-600',
  closed: 'bg-emerald-50 text-emerald-600',
  blocked: 'bg-rose-50 text-rose-600',
  rejected: 'bg-rose-50 text-rose-600',
  cancelled: 'bg-ink-100 text-ink-400',
}
function statusClass(key) {
  return STATUS_COLOR[key] || 'bg-ink-100 text-ink-500'
}
function isOverdue(r) {
  if (!r || !r.due_date) return false
  if (['done', 'closed', 'cancelled'].includes(String(r.status || ''))) return false
  const raw = String(r.due_date)
  const d = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? new Date(`${raw}T23:59:59`) : new Date(raw)
  if (isNaN(d.getTime())) return false
  return d.getTime() < Date.now()
}

async function toggleFavorite(r) {
  if (!r) return
  try {
    const d = await bizApi.favorite(slug.value, r.id)
    const fav = d && typeof d.favorite === 'boolean' ? d.favorite : !r.favorite
    r.favorite = fav
    if (current.value?.id === r.id) current.value.favorite = fav
    app.toastMsg(fav ? '已收藏' : '已取消收藏', 'success')
  } catch (e) {
    fail(e, '收藏失败')
  }
}
async function duplicate(r) {
  if (!r) return
  try {
    await bizApi.duplicateRecord(slug.value, r.id)
    app.toastMsg('已复制记录', 'success')
    closeDetail()
    reloadAll()
  } catch (e) {
    fail(e, '复制失败')
  }
}
async function toggleArchive(r) {
  if (!r) return
  try {
    if (r.archived) await bizApi.unarchiveRecord(slug.value, r.id)
    else await bizApi.archiveRecord(slug.value, r.id)
    app.toastMsg(r.archived ? '已取消归档' : '已归档', 'success')
    closeDetail()
    reloadAll()
  } catch (e) {
    fail(e, '归档操作失败')
  }
}
async function restore(r) {
  if (!r) return
  try {
    await bizApi.restoreRecord(slug.value, r.id)
    app.toastMsg('已恢复', 'success')
    closeDetail()
    reloadAll()
  } catch (e) {
    fail(e, '恢复失败')
  }
}
async function removeRecord(r) {
  if (!r) return
  if (!confirm(`确定删除「${r.title}」？删除后可在回收站恢复。`)) return
  try {
    await bizApi.deleteRecord(slug.value, r.id)
    app.toastMsg('已删除', 'success')
    closeDetail()
    reloadAll()
  } catch (e) {
    fail(e, '删除失败')
  }
}

// ---------------- 批量 ----------------
const bulkStatus = ref('')
const bulkOwner = ref('')
const bulkTags = ref('')
async function applyBulk(action) {
  const ids = [...selected.value]
  if (!ids.length) return
  if (action === 'delete' && !confirm(`确定删除选中的 ${ids.length} 条记录？`)) return
  const payload = { action, ids }
  if (action === 'status') payload.status = bulkStatus.value
  if (action === 'owner') payload.owner_id = bulkOwner.value
  if (action === 'tag') payload.tags = bulkTags.value.split(',').map((s) => s.trim()).filter(Boolean)
  try {
    const d = (await bizApi.bulk(slug.value, payload)) || {}
    app.toastMsg(`批量完成：更新 ${d.updated ?? ids.length} 条${d.skipped ? `，跳过 ${d.skipped} 条` : ''}`, 'success')
    selected.value = []
    bulkStatus.value = ''
    bulkOwner.value = ''
    bulkTags.value = ''
    reloadAll()
  } catch (e) {
    fail(e, '批量操作失败')
  }
}

// ---------------- 新建 / 编辑 ----------------
const formOpen = ref(false)
const saving = ref(false)
const form = reactive({ id: null, title: '', status: '', category: '', priority: '', owner_id: '', due_date: '', tags: '', data: {} })

function resetForm() {
  form.id = null
  form.title = ''
  form.status = statusOptions.value.length ? statusOptions.value[0].key : ''
  form.category = ''
  form.priority = ''
  form.owner_id = ''
  form.due_date = ''
  form.tags = ''
  form.data = {}
}
function openCreate() {
  resetForm()
  formOpen.value = true
}
function openEdit(r) {
  if (!r) return
  form.id = r.id
  form.title = r.title || ''
  form.status = r.status || ''
  form.category = r.category || ''
  form.priority = r.priority || ''
  form.owner_id = r.owner?.id ?? ''
  form.due_date = r.due_date ? String(r.due_date).slice(0, 10) : ''
  form.tags = Array.isArray(r.tags) ? r.tags.join(', ') : ''
  form.data = r.data && typeof r.data === 'object' ? { ...r.data } : {}
  formOpen.value = true
}
async function submitForm() {
  const title = form.title.trim()
  if (!title) {
    app.toastMsg('标题不能为空', 'error')
    return
  }
  const payload = {
    title,
    status: form.status || undefined,
    category: form.category || undefined,
    priority: form.priority || undefined,
    owner_id: form.owner_id === '' ? null : form.owner_id,
    due_date: form.due_date || null,
    tags: form.tags.split(',').map((s) => s.trim()).filter(Boolean),
    data: form.data,
  }
  saving.value = true
  try {
    if (form.id) await bizApi.updateRecord(slug.value, form.id, payload)
    else await bizApi.createRecord(slug.value, payload)
    app.toastMsg(form.id ? '已保存' : '已创建', 'success')
    formOpen.value = false
    closeDetail()
    reloadAll()
  } catch (e) {
    fail(e, '保存失败')
  } finally {
    saving.value = false
  }
}

// ---------------- 导入 / 导出 ----------------
const fileInput = ref(null)
const importResult = ref(null)
const importErrors = computed(() => (Array.isArray(importResult.value?.errors) ? importResult.value.errors : []))
function pickImport() {
  fileInput.value?.click()
}
async function onImportFile(e) {
  const file = e.target.files && e.target.files[0]
  e.target.value = ''
  if (!file) return
  try {
    const csv = await file.text()
    const d = (await bizApi.importRecords(slug.value, { csv })) || {}
    importResult.value = { total: d.total ?? 0, created: d.created ?? 0, errors: d.errors || [] }
    app.toastMsg(`导入完成：成功 ${d.created ?? 0} 条`, (d.errors || []).length ? 'info' : 'success')
    reloadAll()
  } catch (err) {
    fail(err, '导入失败')
  }
}
function todayStr() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
}
async function exportCsv() {
  try {
    const blob = await bizApi.exportCsv(slug.value, queryParams(false))
    saveBlob(blob, `${meta.value.name}-${todayStr()}.csv`)
    app.toastMsg('已导出 CSV', 'success')
  } catch (e) {
    app.toastMsg(await describeDownloadError(e), 'error')
  }
}

// ---------------- 详情抽屉 ----------------
const detailOpen = ref(false)
const current = ref(null)
const comments = ref([])
const timeline = ref([])
const commentText = ref('')
const commentSending = ref(false)

async function openDetail(r) {
  if (!r) return
  const id = r.id
  current.value = { ...r }
  detailOpen.value = true
  comments.value = []
  timeline.value = []
  commentText.value = ''
  // 列表行可能不含完整字段，这里再拉一次详情；失败时保留列表数据可用
  try {
    const full = await bizApi.record(slug.value, id)
    if (current.value?.id === id && full && typeof full === 'object') current.value = full
  } catch (e) { /* 保持列表快照 */ }
  try {
    const list = (await bizApi.comments(slug.value, id)) || []
    if (current.value?.id === id) comments.value = list
  } catch (e) { /* 评论接口失败不阻断详情 */ }
  try {
    const list = (await bizApi.timeline(slug.value, id)) || []
    if (current.value?.id === id) timeline.value = list
  } catch (e) { /* 时间线失败不阻断详情 */ }
}
function closeDetail() {
  detailOpen.value = false
  current.value = null
}
async function postComment() {
  const content = commentText.value.trim()
  if (!content || !current.value) return
  const id = current.value.id
  commentSending.value = true
  try {
    await bizApi.addComment(slug.value, id, content)
    if (current.value?.id === id) commentText.value = ''
    const list = (await bizApi.comments(slug.value, id)) || []
    if (current.value?.id === id) comments.value = list
    const tl = (await bizApi.timeline(slug.value, id)) || []
    if (current.value?.id === id) timeline.value = tl
    app.toastMsg('评论已发表', 'success')
  } catch (e) {
    fail(e, '评论失败')
  } finally {
    commentSending.value = false
  }
}

function fmtVal(v) {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v)
    } catch (e) {
      return String(v)
    }
  }
  return String(v)
}
const fieldRows = computed(() => {
  const rec = current.value
  if (!rec) return []
  const defs = (detail.value?.fields || []).filter((f) => f && f.key && !BUILTIN_KEYS.has(f.key))
  const rows = []
  for (const f of defs) {
    const v = rec.data && typeof rec.data === 'object' ? rec.data[f.key] : undefined
    rows.push({ key: f.key, label: f.label || f.key, value: fmtVal(v) })
  }
  for (const k of Object.keys(rec.data || {})) {
    if (!defs.some((f) => f.key === k)) rows.push({ key: k, label: k, value: fmtVal(rec.data[k]) })
  }
  return rows
})
const rawData = computed(() => {
  const d = current.value?.data
  if (d == null) return '{}'
  try {
    return JSON.stringify(d, null, 2)
  } catch (e) {
    return String(d)
  }
})

// ---------------- 分析 ----------------
const analyticsLoading = ref(false)
const analyticsError = ref('')
const trend = ref({ days: 30, items: [] })
const dists = reactive({ status: [], category: [], priority: [], owner: [] })
const overdue = reactive({ count: 0, results: [] })
const quality = reactive({ score: null, issues: [], checked: 0 })
const DIST_TITLES = { status: '状态分布', category: '分类分布', priority: '优先级分布', owner: '负责人分布' }
const distributionCards = computed(() =>
  ['status', 'category', 'priority', 'owner'].map((field) => ({
    field,
    title: DIST_TITLES[field],
    items: dists[field] || [],
  }))
)
const qualityTone = computed(() => {
  const s = quality.score
  if (s == null) return 'bg-ink-100 text-ink-500'
  return s >= 80 ? 'bg-emerald-50 text-emerald-600' : s >= 60 ? 'bg-amber-50 text-amber-600' : 'bg-rose-50 text-rose-600'
})
function barHeight(v) {
  const items = trend.value.items || []
  const max = Math.max(1, ...items.map((x) => Math.max(Number(x.created) || 0, Number(x.closed) || 0)))
  const pct = Math.max(0, Math.min(100, ((Number(v) || 0) / max) * 100))
  return `${pct}%`
}
function barWidth(p) {
  let n = Number(p) || 0
  // 兼容后端用 0-1 小数表示占比的情况
  if (n > 0 && n <= 1) n *= 100
  return `${Math.max(0, Math.min(100, n))}%`
}
function percentText(p) {
  let n = Number(p) || 0
  if (n > 0 && n <= 1) n *= 100
  return Math.round(n)
}
async function loadAnalytics() {
  analyticsLoading.value = true
  analyticsError.value = ''
  const [t, s, c, p, o, ov, q] = await Promise.allSettled([
    bizApi.trend(slug.value, 30),
    bizApi.distribution(slug.value, 'status'),
    bizApi.distribution(slug.value, 'category'),
    bizApi.distribution(slug.value, 'priority'),
    bizApi.distribution(slug.value, 'owner'),
    bizApi.overdue(slug.value),
    bizApi.quality(slug.value),
  ])
  if (t.status === 'fulfilled' && t.value) trend.value = { days: t.value.days || 30, items: t.value.items || [] }
  const pick = (res) => (res.status === 'fulfilled' && res.value && Array.isArray(res.value.items) ? res.value.items : [])
  dists.status = pick(s)
  dists.category = pick(c)
  dists.priority = pick(p)
  dists.owner = pick(o)
  if (ov.status === 'fulfilled' && ov.value) {
    overdue.count = Number(ov.value.count) || 0
    overdue.results = Array.isArray(ov.value.results) ? ov.value.results : []
  }
  if (q.status === 'fulfilled' && q.value) {
    quality.score = q.value.score ?? null
    quality.issues = Array.isArray(q.value.issues) ? q.value.issues : []
    quality.checked = Number(q.value.checked) || 0
  }
  const failed = [t, s, c, p, o, ov, q].filter((r) => r.status === 'rejected').length
  if (failed) analyticsError.value = `${failed} 个分析接口暂不可用，已展示可用部分。`
  analyticsLoading.value = false
}

// ---------------- 保存视图 / 订阅 ----------------
const savedViews = ref([])
const viewName = ref('')
const subscription = reactive({ enabled: false, frequency: 'daily', last_sent_at: null })

async function loadSavedViews() {
  try {
    savedViews.value = (await bizApi.savedViews(slug.value)) || []
  } catch (e) {
    savedViews.value = []
  }
}
function viewParams(v) {
  return v?.params || v?.query || v?.filters || {}
}
function viewSummary(v) {
  const p = viewParams(v)
  const parts = []
  if (p.q) parts.push(`搜索:${p.q}`)
  if (p.status) parts.push(`状态:${p.status}`)
  if (p.category) parts.push(`分类:${p.category}`)
  if (p.priority) parts.push(`优先级:${p.priority}`)
  if (p.owner) parts.push(`负责人:${p.owner}`)
  if (p.ordering) parts.push(`排序:${p.ordering}`)
  if (p.archived) parts.push('含归档')
  if (p.deleted) parts.push('回收站')
  return parts.length ? parts.join(' · ') : '无筛选条件'
}
async function saveView() {
  const name = viewName.value.trim()
  if (!name) return
  const params = queryParams(false)
  try {
    await bizApi.createSavedView(slug.value, { name, params, query: params, filters: params })
    viewName.value = ''
    app.toastMsg('视图已保存', 'success')
    loadSavedViews()
  } catch (e) {
    fail(e, '保存视图失败')
  }
}
function applyView(v) {
  const p = viewParams(v)
  filters.q = p.q || ''
  filters.status = p.status || ''
  filters.category = p.category || ''
  filters.priority = p.priority || ''
  filters.owner = p.owner ?? ''
  ordering.value = p.ordering || '-updated_at'
  showArchived.value = !!(p.archived === 1 || p.archived === true || p.archived === '1')
  showTrash.value = !!(p.deleted === 1 || p.deleted === true || p.deleted === '1')
  page.value = 1
  tab.value = 'records'
  loadRecords()
  app.toastMsg(`已应用视图「${v.name}」`, 'success')
}
async function removeView(v) {
  if (!confirm(`删除视图「${v.name}」？`)) return
  try {
    await bizApi.deleteSavedView(slug.value, v.id)
    app.toastMsg('视图已删除', 'success')
    loadSavedViews()
  } catch (e) {
    fail(e, '删除视图失败')
  }
}
async function loadSubscription() {
  if (!hasSubscription.value) return
  try {
    const d = (await bizApi.subscription(slug.value)) || {}
    subscription.enabled = !!d.enabled
    subscription.frequency = d.frequency || 'daily'
    subscription.last_sent_at = d.last_sent_at || null
  } catch (e) { /* 订阅接口失败时保持默认关闭 */ }
}
async function saveSubscription() {
  try {
    const d = (await bizApi.saveSubscription(slug.value, { enabled: subscription.enabled, frequency: subscription.frequency })) || {}
    subscription.enabled = !!d.enabled
    subscription.frequency = d.frequency || subscription.frequency
    subscription.last_sent_at = d.last_sent_at ?? subscription.last_sent_at
    app.toastMsg('订阅设置已保存', 'success')
  } catch (e) {
    fail(e, '订阅保存失败')
  }
}
async function toggleSubscription() {
  subscription.enabled = !subscription.enabled
  await saveSubscription()
}

// ---------------- 加载编排 ----------------
const featureGroups = computed(() => {
  const list = detail.value?.features || []
  const groups = []
  for (const f of list) {
    const name = f.group || '通用能力'
    let g = groups.find((x) => x.name === name)
    if (!g) {
      g = { name, items: [] }
      groups.push(g)
    }
    g.items.push(f)
  }
  return groups
})

function switchTab(key) {
  tab.value = key
  if (key === 'analytics') loadAnalytics()
  if (key === 'settings') {
    loadSavedViews()
    loadSubscription()
  }
}

async function loadModuleDetail() {
  detailFailed.value = false
  try {
    detail.value = await bizApi.moduleDetail(slug.value)
    loadSubscription()
  } catch (e) {
    detailFailed.value = true
    banner.value = `模块详情（/api/biz/${slug.value}/）暂不可用，字段与能力清单已降级，但记录列表仍可使用。`
  }
}

let routeSeen = slug.value
function reloadAll() {
  banner.value = ''
  loadModuleDetail()
  loadMembers()
  loadRecords()
  loadStats()
  if (tab.value === 'analytics') loadAnalytics()
  if (tab.value === 'settings') {
    loadSavedViews()
    loadSubscription()
  }
}

function resetForModule() {
  detail.value = null
  stats.value = null
  records.value = []
  totalCount.value = 0
  page.value = 1
  selected.value = []
  Object.assign(filters, { q: '', status: '', category: '', priority: '', owner: '' })
  ordering.value = '-updated_at'
  showArchived.value = false
  showTrash.value = false
  tab.value = 'records'
  banner.value = ''
  importResult.value = null
  trend.value = { days: 30, items: [] }
  dists.status = []
  dists.category = []
  dists.priority = []
  dists.owner = []
  overdue.count = 0
  overdue.results = []
  quality.score = null
  quality.issues = []
  quality.checked = 0
  savedViews.value = []
  subscription.enabled = false
  subscription.frequency = 'daily'
  subscription.last_sent_at = null
  closeDetail()
}

// 所有业务模块共用同一路由组件：模块切换时整体重置
watch(
  () => props.module,
  (next) => {
    if (next === routeSeen) return
    routeSeen = next
    resetForModule()
    cleanupTimers()
    reloadAll()
  }
)

function cleanupTimers() {
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = null
  }
}

onMounted(() => {
  reloadAll()
})

onBeforeUnmount(() => {
  cleanupTimers()
})
</script>
