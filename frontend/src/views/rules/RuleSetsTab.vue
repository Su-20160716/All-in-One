<template>
  <div class="space-y-3">
    <!-- 筛选与操作 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <label class="flex min-w-[180px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
        关键词
        <input v-model="q" class="input" placeholder="编码 / 名称 / 分类 / 描述" @keyup.enter="applyFilters" />
      </label>
      <label class="flex w-[140px] flex-col gap-1 text-[11px] text-ink-500">
        状态
        <select v-model="status" class="input" @change="applyFilters">
          <option value="">全部状态</option>
          <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label class="flex w-[150px] flex-col gap-1 text-[11px] text-ink-500">
        分类
        <select v-model="category" class="input" @change="applyFilters">
          <option value="">全部分类</option>
          <option v-for="item in categoryOptions" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn-outline" :disabled="loading" @click="applyFilters">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="resetFilters">重置</button>
      <button class="btn-primary ml-auto" @click="openCreate">新建规则集</button>
    </div>

    <div v-if="listNotice" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      {{ listNotice }}
    </div>

    <!-- 列表 -->
    <div class="card overflow-hidden">
      <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2">
        <span class="text-[13px] font-medium text-ink-700">规则集列表</span>
        <span class="text-[11px] text-ink-400">共 {{ total }} 个 · 第 {{ page }}/{{ pages }} 页</span>
      </div>

      <div v-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="listError" class="flex items-center gap-3 bg-rose-50 px-3 py-3 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ listError }}</span>
        <button class="shrink-0 font-medium" @click="loadList">重试</button>
      </div>
      <div v-else-if="!items.length" class="px-3 py-12 text-center text-[12px] text-ink-400">
        还没有规则集，点击「新建规则集」创建第一个
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[900px]">
          <thead class="bg-ink-50/60">
            <tr>
              <th class="th">编码</th>
              <th class="th">名称</th>
              <th class="th">分类</th>
              <th class="th">状态</th>
              <th class="th">版本</th>
              <th class="th">命中策略</th>
              <th class="th">优先级</th>
              <th class="th">更新时间</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr
              v-for="row in items"
              :key="row.id"
              class="transition-colors hover:bg-ink-50/50"
              :class="String(row.id) === String(rulesetId) ? 'bg-brand-50/40' : ''"
            >
              <td class="td font-mono text-[12px]">{{ row.code }}</td>
              <td class="td">
                <button class="max-w-[220px] truncate text-left font-medium text-brand-600" @click="openDetail(row)">
                  {{ row.name }}
                </button>
                <div class="max-w-[240px] truncate text-[11px] text-ink-400">{{ row.description || '—' }}</div>
              </td>
              <td class="td"><span class="tag">{{ row.category || '自定义' }}</span></td>
              <td class="td">
                <span class="tag" :class="statusClass(row.status)">{{ row.status_label || row.status }}</span>
              </td>
              <td class="td">v{{ row.version_no }}</td>
              <td class="td text-[12px]">{{ hitPolicyLabel(row.hit_policy) }}</td>
              <td class="td">{{ row.priority }}</td>
              <td class="td text-[12px] text-ink-500">{{ fmtDate(row.updated_at) }}</td>
              <td class="td">
                <div class="flex flex-wrap justify-end gap-1">
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openDetail(row)">详情</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openEdit(row)">编辑</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="acting" @click="actOnList(row, 'publish')">发布</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="acting" @click="actOnList(row, 'pause')">暂停</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="acting" @click="validateRuleSet(row)">校验</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="acting" @click="cloneRuleSet(row)">克隆</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="askDelete(row)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2">
        <span class="text-[11px] text-ink-400">每页 {{ pageSize }} 条</span>
        <div class="flex items-center gap-1">
          <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <span class="px-2 text-[12px] text-ink-500">{{ page }} / {{ pages }}</span>
          <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 规则集编辑器 -->
    <Modal v-model="editorShow" :title="form.id ? '编辑规则集' : '新建规则集'" width="680px">
      <div v-if="editorError" class="mb-3 flex items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ editorError }}</span>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          编码
          <input v-model.trim="form.code" class="input font-mono" :disabled="!!form.id" placeholder="如 risk_loan" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          名称
          <input v-model.trim="form.name" class="input" placeholder="规则集名称" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          分类
          <input v-model.trim="form.category" class="input" placeholder="自定义" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          状态
          <select v-model="form.status" class="input">
            <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          命中策略
          <select v-model="form.hit_policy" class="input">
            <option v-for="item in HIT_POLICY_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          优先级
          <input v-model.number="form.priority" type="number" class="input" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          最多执行规则数
          <input v-model.number="form.max_executions" type="number" min="1" max="1000" class="input" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          超时毫秒
          <input v-model.number="form.timeout_ms" type="number" min="50" max="60000" class="input" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600 sm:col-span-2">
          标签（逗号分隔）
          <input v-model.trim="form.tags" class="input" placeholder="风控, 信贷" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600 sm:col-span-2">
          描述
          <textarea v-model.trim="form.description" class="input min-h-[72px]" placeholder="用途、生效范围、负责人约定"></textarea>
        </label>
      </div>
      <p class="mt-2 text-[11px] text-ink-400">编码创建后不可修改；发布后才参与自动执行。</p>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="editorShow = false">取消</button>
        <button class="btn-primary" :disabled="saving" @click="saveRuleSet">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </Modal>

    <!-- 规则集详情 -->
    <Modal v-model="detailShow" :title="detail ? `${detail.name} · ${detail.code}` : '规则集详情'" width="1000px">
      <div v-if="detailLoading" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="detailError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ detailError }}</span>
        <button class="shrink-0 font-medium" @click="reloadDetail">重试</button>
      </div>
      <template v-else-if="detail">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag" :class="statusClass(detail.status)">{{ detail.status_label || detail.status }}</span>
          <span class="tag">v{{ detail.version_no }}</span>
          <span class="tag">{{ hitPolicyLabel(detail.hit_policy) }}</span>
          <span class="text-[11px] text-ink-400">更新于 {{ fmtDate(detail.updated_at, true) }}</span>
          <div class="ml-auto flex flex-wrap gap-1.5">
            <button class="btn-outline py-1 text-[11px]" :disabled="acting" @click="actOnDetail('publish')">发布</button>
            <button class="btn-ghost py-1 text-[11px]" :disabled="acting" @click="actOnDetail('pause')">暂停</button>
            <button class="btn-ghost py-1 text-[11px]" :disabled="acting" @click="actOnDetail('archive')">归档</button>
            <button class="btn-ghost py-1 text-[11px]" :disabled="acting" @click="actOnDetail('clone')">克隆</button>
            <button class="btn-ghost py-1 text-[11px]" :disabled="acting" @click="validateDetail">校验</button>
          </div>
        </div>

        <div class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">规则</div>
            <div class="text-[15px] font-semibold text-ink-800">{{ detail.rule_count ?? detail.rules?.length ?? 0 }}</div>
            <div class="text-[10px] text-ink-400">启用 {{ detail.enabled_rule_count ?? 0 }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">决策表</div>
            <div class="text-[15px] font-semibold text-ink-800">{{ detail.table_count ?? detail.decision_tables?.length ?? 0 }}</div>
            <div class="text-[10px] text-ink-400">变量 {{ detail.variable_count ?? 0 }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">历史版本</div>
            <div class="text-[15px] font-semibold text-ink-800">{{ detail.version_count ?? versions.length }}</div>
            <div class="text-[10px] text-ink-400">可回滚</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">未解决冲突</div>
            <div class="text-[15px] font-semibold" :class="detail.open_conflicts ? 'text-rose-600' : 'text-ink-800'">
              {{ detail.open_conflicts ?? 0 }}
            </div>
            <div class="text-[10px] text-ink-400">调度 {{ detail.schedule_count ?? 0 }}</div>
          </div>
        </div>

        <div class="mt-3 flex items-center gap-1.5 border-b border-ink-100 pb-2">
          <button
            v-for="t in DETAIL_TABS"
            :key="t.key"
            class="rounded-pill px-2.5 py-1 text-[12px]"
            :class="detailTab === t.key ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
            @click="detailTab = t.key"
          >
            {{ t.label }}
          </button>
          <button class="btn-ghost ml-auto py-1 text-[11px]" :disabled="detailLoading" @click="reloadDetail">刷新</button>
        </div>

        <!-- 规则 -->
        <div v-if="detailTab === 'rules'" class="mt-2">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-[12px] text-ink-500">规则按优先级升序执行，优先级数字越小越先执行</span>
            <button class="btn-primary py-1 text-[11px]" @click="openRuleCreate">新增规则</button>
          </div>
          <div v-if="!detail.rules?.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
            还没有规则，新增后配置条件与动作
          </div>
          <div v-else class="divide-y divide-ink-50">
            <div v-for="rule in detail.rules" :key="rule.id" class="py-2">
              <div class="flex flex-wrap items-center gap-2">
                <span class="tag" :class="rule.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                  {{ rule.enabled ? '启用' : '停用' }}
                </span>
                <span class="min-w-0 flex-1 truncate text-[13px] font-medium text-ink-800">{{ rule.name }}</span>
                <span class="text-[11px] text-ink-400">优先级 {{ rule.priority }}</span>
                <span class="text-[11px] text-ink-400">命中 {{ rule.hit_count }}</span>
                <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="toggleRule(rule)">
                  {{ rule.enabled ? '停用' : '启用' }}
                </button>
                <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openRuleEdit(rule)">编辑</button>
                <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="askDeleteRule(rule)">删除</button>
              </div>
              <div class="mt-1 truncate font-mono text-[11px] text-ink-500">
                {{ rule.condition || '条件由可视化条件行拼装' }}
              </div>
            </div>
          </div>
        </div>

        <!-- 版本 -->
        <div v-else-if="detailTab === 'versions'" class="mt-2">
          <div v-if="versionsLoading" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
          <div v-else-if="versionsError" class="flex items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <span class="min-w-0 flex-1">{{ versionsError }}</span>
            <button class="shrink-0 font-medium" @click="loadVersions(detail.id)">重试</button>
          </div>
          <div v-else-if="!versions.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
            还没有发布版本，发布规则集会生成版本快照
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full min-w-[620px]">
              <thead class="bg-ink-50/60">
                <tr>
                  <th class="th">版本</th>
                  <th class="th">发布说明</th>
                  <th class="th">发布人</th>
                  <th class="th">发布时间</th>
                  <th class="th text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="ver in versions" :key="ver.id">
                  <td class="td">v{{ ver.version_no }}</td>
                  <td class="td">{{ ver.note || '—' }}</td>
                  <td class="td">{{ ver.published_by?.username || ver.published_by?.nickname || '—' }}</td>
                  <td class="td text-[12px] text-ink-500">{{ fmtDate(ver.created_at, true) }}</td>
                  <td class="td text-right">
                    <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="acting" @click="askRollback(ver)">
                      回滚到此版本
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 资产 -->
        <div v-else class="mt-2 grid gap-3 sm:grid-cols-2">
          <div class="rounded-control border border-ink-100 p-3">
            <div class="mb-1.5 text-[12px] font-medium text-ink-700">变量定义</div>
            <div v-if="!detail.variables?.length" class="py-4 text-center text-[12px] text-ink-400">暂无变量</div>
            <div v-else class="divide-y divide-ink-50">
              <div v-for="v in detail.variables" :key="v.id" class="flex items-center gap-2 py-1.5 text-[12px]">
                <span class="font-mono text-ink-700">{{ v.name }}</span>
                <span class="tag">{{ v.type }}</span>
                <span class="min-w-0 flex-1 truncate text-right text-ink-400">{{ v.description || '—' }}</span>
              </div>
            </div>
          </div>
          <div class="rounded-control border border-ink-100 p-3">
            <div class="mb-1.5 text-[12px] font-medium text-ink-700">决策表</div>
            <div v-if="!detail.decision_tables?.length" class="py-4 text-center text-[12px] text-ink-400">暂无决策表</div>
            <div v-else class="divide-y divide-ink-50">
              <div v-for="t in detail.decision_tables" :key="t.id" class="flex items-center gap-2 py-1.5 text-[12px]">
                <span class="min-w-0 flex-1 truncate text-ink-700">{{ t.name }}</span>
                <span class="tag">{{ t.inputs?.length || 0 }} 入 / {{ t.outputs?.length || 0 }} 出</span>
                <span class="tag" :class="t.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                  {{ t.enabled ? '启用' : '停用' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </Modal>

    <!-- 规则编辑器 -->
    <Modal v-model="ruleShow" :title="ruleForm.id ? '编辑规则' : '新增规则'" width="920px">
      <div v-if="ruleError" class="mb-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ ruleError }}</div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label class="flex flex-col gap-1 text-[12px] text-ink-600 sm:col-span-2">
          规则名称
          <input v-model.trim="ruleForm.name" class="input" placeholder="如 高额订单人工复核" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          优先级
          <input v-model.number="ruleForm.priority" type="number" class="input" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600 sm:col-span-2">
          说明
          <input v-model.trim="ruleForm.description" class="input" placeholder="命中后的业务含义" />
        </label>
        <label class="flex items-center gap-2 pt-5 text-[12px] text-ink-600">
          <input v-model="ruleForm.enabled" type="checkbox" class="h-3.5 w-3.5" />
          启用该规则
        </label>
      </div>

      <div class="mt-4">
        <div class="mb-1.5 flex items-center justify-between">
          <span class="text-[12px] font-medium text-ink-700">可视化条件</span>
          <div class="flex gap-1">
            <button class="btn-ghost py-1 text-[11px]" @click="applyConditionsToExpression">用条件行覆盖表达式</button>
            <button class="btn-ghost py-1 text-[11px]" @click="addCondition">添加条件</button>
          </div>
        </div>
        <div v-if="!ruleForm.conditions.length" class="rounded-control border border-dashed border-ink-200 py-4 text-center text-[11px] text-ink-400">
          没有条件行时视为恒命中，请谨慎使用
        </div>
        <div v-else class="space-y-1.5">
          <div v-for="(row, index) in ruleForm.conditions" :key="index" class="flex flex-wrap items-center gap-1.5">
            <select v-if="index > 0" v-model="row.logic_group" class="input w-[72px] py-1 text-[12px]">
              <option value="and">且</option>
              <option value="or">或</option>
            </select>
            <span v-else class="w-[72px] text-center text-[11px] text-ink-400">当</span>
            <input v-model.trim="row.field" class="input w-[168px] py-1 font-mono text-[12px]" placeholder="facts.amount" />
            <select v-model="row.operator" class="input w-[122px] py-1 text-[12px]" @change="onOperatorChange(row)">
              <option v-for="op in OPERATORS" :key="op.value" :value="op.value">{{ op.label }}</option>
            </select>
            <input
              v-model.trim="row.valueText"
              class="input min-w-[120px] flex-1 py-1 text-[12px]"
              :disabled="row.operator === 'is_null' || row.operator === 'is_not_null'"
              :placeholder="valuePlaceholder(row.operator)"
            />
            <label class="flex items-center gap-1 text-[11px] text-ink-500">
              <input v-model="row.enabled" type="checkbox" class="h-3.5 w-3.5" />
              启用
            </label>
            <button class="btn-ghost px-2 py-0.5 text-[11px] text-rose-600" @click="removeCondition(index)">移除</button>
          </div>
        </div>
        <p class="mt-1 text-[11px] text-ink-400">集合用逗号分隔（a,b），区间写作 100,200；字段路径支持 facts.xxx 与 vars.xxx。</p>
      </div>

      <div class="mt-4">
        <div class="mb-1.5 flex items-center justify-between">
          <span class="text-[12px] font-medium text-ink-700">动作</span>
          <button class="btn-ghost py-1 text-[11px]" @click="addAction">添加动作</button>
        </div>
        <div v-if="!ruleForm.action_items.length" class="rounded-control border border-dashed border-ink-200 py-4 text-center text-[11px] text-ink-400">
          还没有动作，命中后不会产生任何效果
        </div>
        <div v-else class="space-y-2">
          <div v-for="(row, index) in ruleForm.action_items" :key="index" class="rounded-control border border-ink-100 p-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="text-[11px] text-ink-400">#{{ index + 1 }}</span>
              <select v-model="row.type" class="input w-[132px] py-1 text-[12px]" @change="onActionTypeChange(row)">
                <option v-for="item in ACTION_TYPES" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
              <span class="text-[11px] text-ink-400">{{ actionHint(row.type) }}</span>
              <button class="btn-ghost ml-auto px-2 py-0.5 text-[11px] text-rose-600" @click="removeAction(index)">移除</button>
            </div>
            <div class="mt-1.5 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              <label v-for="field in actionFields(row.type)" :key="field.key" class="flex flex-col gap-0.5 text-[11px] text-ink-500">
                {{ field.label }}
                <input
                  v-model.trim="row.params[field.key]"
                  class="input py-1 text-[12px]"
                  :placeholder="field.placeholder || ''"
                />
              </label>
            </div>
          </div>
        </div>
      </div>

      <label class="mt-4 flex flex-col gap-1 text-[12px] text-ink-600">
        条件表达式（留空时由条件行自动拼装）
        <textarea
          v-model.trim="ruleForm.condition"
          class="input min-h-[64px] font-mono text-[12px]"
          placeholder="facts.amount >= 1000 and facts.channel == 'app'"
        ></textarea>
      </label>

      <div class="mt-2 rounded-control bg-ink-50/60 px-3 py-2 font-mono text-[11px] text-ink-500">
        条件行预览：{{ conditionsPreview }}
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="ruleShow = false">取消</button>
        <button class="btn-primary" :disabled="ruleSaving" @click="saveRule">
          {{ ruleSaving ? '保存中…' : '保存规则' }}
        </button>
      </div>
    </Modal>

    <!-- 校验结果 -->
    <Modal v-model="validateShow" title="规则集静态校验" width="680px">
      <div v-if="validateLoading" class="py-8 text-center text-[12px] text-ink-400">校验中…</div>
      <template v-else-if="validateReport">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag" :class="validateReport.valid ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
            {{ validateReport.valid ? '校验通过' : '存在错误' }}
          </span>
          <span class="tag">错误 {{ validateReport.errors?.length || 0 }}</span>
          <span class="tag">告警 {{ validateReport.warnings?.length || 0 }}</span>
          <span class="text-[11px] text-ink-400">规则 {{ validateReport.stats?.rules || 0 }} · 启用 {{ validateReport.stats?.enabled_rules || 0 }}</span>
        </div>
        <div class="mt-3 space-y-2">
          <div>
            <div class="mb-1 text-[12px] font-medium text-rose-600">错误</div>
            <div v-if="!validateReport.errors?.length" class="text-[12px] text-ink-400">无</div>
            <ul v-else class="space-y-1">
              <li v-for="(item, i) in validateReport.errors" :key="`e-${i}`" class="rounded-control bg-rose-50 px-2 py-1 text-[12px] text-rose-700">
                {{ item.message }}
              </li>
            </ul>
          </div>
          <div>
            <div class="mb-1 text-[12px] font-medium text-amber-600">告警</div>
            <div v-if="!validateReport.warnings?.length" class="text-[12px] text-ink-400">无</div>
            <ul v-else class="max-h-[220px] space-y-1 overflow-y-auto">
              <li v-for="(item, i) in validateReport.warnings" :key="`w-${i}`" class="rounded-control bg-amber-50 px-2 py-1 text-[12px] text-amber-700">
                {{ item.message }}
              </li>
            </ul>
          </div>
        </div>
        <div class="mt-4 flex justify-end gap-2">
          <button class="btn-ghost" @click="validateShow = false">关闭</button>
          <button class="btn-primary" :disabled="acting" @click="publishAfterValidate">发布规则集</button>
        </div>
      </template>
    </Modal>

    <!-- 通用确认 -->
    <Modal v-model="confirm.show" :title="confirm.title" width="420px">
      <p class="text-[13px] text-ink-600">{{ confirm.text }}</p>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="confirm.show = false">取消</button>
        <button class="btn-primary" :class="confirm.danger ? '!bg-rose-600 hover:!bg-rose-700' : ''" :disabled="acting" @click="runConfirm">
          确认
        </button>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Modal from '../../components/Modal.vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate } from '../../composables/useDomainResource'

const props = defineProps({
  rulesetId: { type: [String, Number], default: '' },
  rulesets: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['select', 'changed'])
const api = apiFor('rules')
const app = useAppStore()

const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'active', label: '生效中' },
  { value: 'paused', label: '已暂停' },
  { value: 'archived', label: '已归档' },
]

const HIT_POLICY_OPTIONS = [
  { value: 'first', label: '首条命中' },
  { value: 'all', label: '全部命中' },
  { value: 'priority', label: '最高优先级命中' },
  { value: 'collect', label: '汇总所有命中输出' },
]

const OPERATORS = [
  { value: '==', label: '等于' },
  { value: '!=', label: '不等于' },
  { value: '>', label: '大于' },
  { value: '>=', label: '大于等于' },
  { value: '<', label: '小于' },
  { value: '<=', label: '小于等于' },
  { value: 'in', label: '属于集合' },
  { value: 'not_in', label: '不属于集合' },
  { value: 'contains', label: '包含' },
  { value: 'not_contains', label: '不包含' },
  { value: 'between', label: '介于区间' },
  { value: 'is_null', label: '为空' },
  { value: 'is_not_null', label: '不为空' },
  { value: 'matches', label: '正则匹配' },
  { value: 'like', label: '模糊匹配' },
]

const ACTION_TYPES = [
  { value: 'set_field', label: '设置字段' },
  { value: 'notify', label: '站内通知' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'route', label: '路由分派' },
  { value: 'score', label: '评分累加' },
  { value: 'flag', label: '打标' },
  { value: 'approve', label: '输出通过' },
  { value: 'reject', label: '输出驳回' },
  { value: 'create_task', label: '创建任务' },
]

const DETAIL_TABS = [
  { key: 'rules', label: '规则' },
  { key: 'versions', label: '版本' },
  { key: 'assets', label: '变量与决策表' },
]

const HIT_POLICY_LABELS = {
  first: '首条命中',
  all: '全部命中',
  priority: '最高优先级',
  collect: '汇总输出',
}

const items = ref([])
const q = ref('')
const status = ref('')
const category = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const listError = ref('')
const listNotice = ref('')
const acting = ref(false)

const editorShow = ref(false)
const editorError = ref('')
const saving = ref(false)
const form = ref(emptyForm())

const detailShow = ref(false)
const detail = ref(null)
const detailTargetId = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const detailTab = ref('rules')
const versions = ref([])
const versionsLoading = ref(false)
const versionsError = ref('')

const ruleShow = ref(false)
const ruleSaving = ref(false)
const ruleError = ref('')
const ruleForm = ref(emptyRuleForm())

const validateShow = ref(false)
const validateLoading = ref(false)
const validateReport = ref(null)
const validateTargetId = ref('')

const confirm = ref({ show: false, title: '', text: '', danger: false, action: null })

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

const categoryOptions = computed(() => {
  const set = new Set(['自定义', '风控', '营销', '审批', '定价', '运营'])
  for (const item of props.rulesets) {
    if (item.category) set.add(item.category)
  }
  for (const item of items.value) {
    if (item.category) set.add(item.category)
  }
  return Array.from(set)
})

const conditionsPreview = computed(() => {
  const rows = ruleForm.value.conditions.filter((row) => row.enabled && row.field)
  if (!rows.length) return 'true（恒命中）'
  return rows
    .map((row, index) => {
      const text = conditionRowText(row)
      const connector = index === 0 ? '' : row.logic_group === 'or' ? ' or ' : ' and '
      return `${connector}${text}`
    })
    .join('')
    .trim()
})

function quoteLiteral(text) {
  const raw = String(text ?? '').trim()
  if (raw === '') return 'null'
  if (/^-?\d+(\.\d+)?$/.test(raw)) return raw
  if (raw === 'true' || raw === 'false' || raw === 'null') return raw
  return JSON.stringify(raw)
}

function conditionRowText(row) {
  const field = row.field || 'facts.field'
  const raw = String(row.valueText || '').trim()
  const values = raw.split(',').map((part) => part.trim()).filter(Boolean)
  if (row.operator === 'is_null' || row.operator === 'is_not_null') {
    return `${field} ${row.operator === 'is_null' ? 'is null' : 'is not null'}`
  }
  if (row.operator === 'in' || row.operator === 'not_in') {
    const list = values.map(quoteLiteral).join(', ')
    return `${field} ${row.operator === 'in' ? 'in' : 'not in'} [${list}]`
  }
  if (row.operator === 'between') {
    const list = values.map(quoteLiteral)
    return `${field} between ${list[0] ?? 'null'} and ${list[1] ?? 'null'}`
  }
  if (row.operator === 'contains' || row.operator === 'not_contains') {
    const keyword = row.operator === 'contains' ? 'like' : 'not like'
    return `${field} ${keyword} ${quoteLiteral(`%${raw}%`)}`
  }
  return `${field} ${row.operator} ${quoteLiteral(raw)}`
}

function applyConditionsToExpression() {
  if (!ruleForm.value.conditions.filter((row) => row.field).length) {
    ruleForm.value.condition = ''
    app.toastMsg('没有有效条件行，已清空表达式（恒命中）', 'info')
    return
  }
  ruleForm.value.condition = conditionsPreview.value
  app.toastMsg('表达式已按条件行覆盖', 'success')
}

function emptyForm() {
  return {
    id: null,
    code: '',
    name: '',
    category: '自定义',
    description: '',
    status: 'draft',
    hit_policy: 'first',
    priority: 0,
    max_executions: 100,
    timeout_ms: 2000,
    tags: '',
  }
}

function emptyRuleForm() {
  return {
    id: null,
    ruleset_id: '',
    name: '',
    description: '',
    priority: 100,
    enabled: true,
    condition: '',
    conditions: [emptyCondition()],
    action_items: [emptyAction()],
  }
}

function emptyCondition() {
  return { field: '', operator: '==', valueText: '', logic_group: 'and', enabled: true }
}

function emptyAction(type = 'set_field') {
  return { type, params: {} }
}

function hitPolicyLabel(value) {
  return HIT_POLICY_LABELS[value] || value || '—'
}

function statusClass(value) {
  const map = {
    active: 'bg-emerald-50 text-emerald-600',
    draft: 'bg-amber-50 text-amber-600',
    paused: 'bg-amber-50 text-amber-600',
    archived: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function fmtDate(value, withTime = false) {
  return formatDate(value, withTime)
}

function isMissingEndpoint(e) {
  const s = e?.response?.status
  return s === 404 || s === 405 || s === 501
}

function buildParams() {
  const params = { page: page.value, page_size: pageSize.value }
  if (q.value.trim()) params.q = q.value.trim()
  if (status.value) params.status = status.value
  if (category.value) params.category = category.value
  return params
}

async function loadList() {
  if (!api) {
    listError.value = '规则引擎接口不可用'
    return
  }
  loading.value = true
  listError.value = ''
  listNotice.value = ''
  try {
    const data = await api.list('rulesets/', buildParams())
    items.value = data.items || []
    total.value = Number(data.count) || 0
    if (!items.value.length && !total.value) listNotice.value = ''
  } catch (e) {
    items.value = []
    total.value = 0
    if (isMissingEndpoint(e)) {
      listNotice.value = '当前后端未提供规则集列表接口，页面已降级为空态'
    } else {
      listError.value = e?.message || '规则集加载失败'
      app.toastMsg(listError.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  loadList()
}

function resetFilters() {
  q.value = ''
  status.value = ''
  category.value = ''
  page.value = 1
  loadList()
}

function goPage(next) {
  page.value = Math.min(Math.max(1, next), pages.value)
  loadList()
}

function openCreate() {
  form.value = emptyForm()
  editorError.value = ''
  editorShow.value = true
}

function openEdit(row) {
  form.value = {
    id: row.id,
    code: row.code || '',
    name: row.name || '',
    category: row.category || '自定义',
    description: row.description || '',
    status: row.status || 'draft',
    hit_policy: row.hit_policy || 'first',
    priority: Number(row.priority) || 0,
    max_executions: Number(row.max_executions) || 100,
    timeout_ms: Number(row.timeout_ms) || 2000,
    tags: Array.isArray(row.tags) ? row.tags.join(', ') : '',
  }
  editorError.value = ''
  editorShow.value = true
}

async function saveRuleSet() {
  if (!form.value.code.trim()) {
    editorError.value = '请填写规则集编码'
    return
  }
  if (!form.value.name.trim()) {
    editorError.value = '请填写规则集名称'
    return
  }
  saving.value = true
  editorError.value = ''
  const payload = {
    code: form.value.code.trim(),
    name: form.value.name.trim(),
    category: form.value.category.trim() || '自定义',
    description: form.value.description,
    status: form.value.status,
    hit_policy: form.value.hit_policy,
    priority: Number(form.value.priority) || 0,
    max_executions: Number(form.value.max_executions) || 100,
    timeout_ms: Number(form.value.timeout_ms) || 2000,
    tags: form.value.tags ? form.value.tags.split(',').map((s) => s.trim()).filter(Boolean) : [],
  }
  try {
    if (form.value.id) {
      await api.post(`rulesets/${form.value.id}/`, payload)
      app.toastMsg('规则集已更新', 'success')
    } else {
      await api.create('rulesets/', payload)
      app.toastMsg('规则集已创建', 'success')
    }
    editorShow.value = false
    await loadList()
    emit('changed')
  } catch (e) {
    editorError.value = e?.message || '保存失败'
    app.toastMsg(editorError.value, 'error')
  } finally {
    saving.value = false
  }
}

async function openDetail(row) {
  detail.value = null
  detailTargetId.value = row.id
  detailError.value = ''
  detailTab.value = 'rules'
  versions.value = []
  detailShow.value = true
  emit('select', row.id)
  await loadDetail(row.id)
  loadVersions(row.id)
}

async function loadDetail(id) {
  if (!api) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await api.get(`rulesets/${id}/`)
  } catch (e) {
    detail.value = null
    detailError.value = e?.message || '规则集详情加载失败'
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function reloadDetail() {
  if (detail.value?.id) await loadDetail(detail.value.id)
  else if (detailTargetId.value) await loadDetail(detailTargetId.value)
}

async function loadVersions(id) {
  if (!api || !id) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const data = await api.list(`rulesets/${id}/versions/`, { page: 1, page_size: 50 })
    versions.value = data.items || []
  } catch (e) {
    versions.value = []
    if (isMissingEndpoint(e)) {
      versionsError.value = '当前后端未提供版本列表接口'
    } else {
      versionsError.value = e?.message || '版本列表加载失败'
    }
  } finally {
    versionsLoading.value = false
  }
}

async function actOnList(row, action) {
  acting.value = true
  try {
    await api.action(`rulesets/${row.id}/${action}/`, { note: '工作台操作' })
    app.toastMsg(action === 'publish' ? '已发布新版本' : '已暂停', 'success')
    await loadList()
    if (detail.value?.id === row.id) {
      await loadDetail(row.id)
      await loadVersions(row.id)
    }
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    acting.value = false
  }
}

async function actOnDetail(action) {
  const rs = detail.value
  if (!rs) return
  if (action === 'clone') {
    cloneRuleSet(rs)
    return
  }
  acting.value = true
  try {
    await api.action(`rulesets/${rs.id}/${action}/`, {})
    const labels = { publish: '已发布', pause: '已暂停', archive: '已归档' }
    app.toastMsg(labels[action] || '操作成功', 'success')
    await loadDetail(rs.id)
    await loadVersions(rs.id)
    await loadList()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    acting.value = false
  }
}

function cloneRuleSet(row) {
  confirm.value = {
    show: true,
    title: '克隆规则集',
    text: `将「${row.name}」克隆为新的草稿规则集，编码自动加后缀。`,
    danger: false,
    action: async () => {
      acting.value = true
      try {
        await api.action(`rulesets/${row.id}/clone/`, { name: `${row.name} 副本` })
        app.toastMsg('已克隆为新草稿', 'success')
        await loadList()
        emit('changed')
      } catch (e) {
        app.toastMsg(e?.message || '克隆失败', 'error')
      } finally {
        acting.value = false
      }
    },
  }
}

function askDelete(row) {
  confirm.value = {
    show: true,
    title: '删除规则集',
    text: `删除「${row.name}」会同时移除规则、版本与调度，操作不可撤销。`,
    danger: true,
    action: async () => {
      acting.value = true
      try {
        await api.action(`rulesets/${row.id}/delete/`, {})
        app.toastMsg('规则集已删除', 'success')
        if (String(props.rulesetId) === String(row.id)) emit('select', '')
        if (detail.value?.id === row.id) detailShow.value = false
        await loadList()
        emit('changed')
      } catch (e) {
        app.toastMsg(e?.message || '删除失败', 'error')
      } finally {
        acting.value = false
      }
    },
  }
}

async function runConfirm() {
  const action = confirm.value.action
  confirm.value.show = false
  if (typeof action === 'function') await action()
}

async function validateRuleSet(row) {
  validateTargetId.value = row.id
  validateReport.value = null
  validateShow.value = true
  validateLoading.value = true
  try {
    validateReport.value = await api.action(`rulesets/${row.id}/validate/`, {})
  } catch (e) {
    validateShow.value = false
    app.toastMsg(e?.message || '校验失败', 'error')
  } finally {
    validateLoading.value = false
  }
}

async function validateDetail() {
  if (detail.value) await validateRuleSet(detail.value)
}

async function publishAfterValidate() {
  if (!validateTargetId.value) return
  acting.value = true
  try {
    await api.action(`rulesets/${validateTargetId.value}/publish/`, { note: '工作台发布' })
    app.toastMsg('已发布新版本', 'success')
    validateShow.value = false
    if (detail.value?.id === validateTargetId.value) {
      await loadDetail(validateTargetId.value)
      await loadVersions(validateTargetId.value)
    }
    await loadList()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '发布失败', 'error')
  } finally {
    acting.value = false
  }
}

function askRollback(version) {
  const rs = detail.value
  if (!rs) return
  confirm.value = {
    show: true,
    title: '回滚版本',
    text: `将「${rs.name}」回滚到 v${version.version_no}，当前配置会被快照覆盖并生成新版本。`,
    danger: true,
    action: async () => {
      acting.value = true
      try {
        await api.action(`rulesets/${rs.id}/rollback/`, { version_id: version.id })
        app.toastMsg(`已回滚到 v${version.version_no}`, 'success')
        await loadDetail(rs.id)
        await loadVersions(rs.id)
        await loadList()
      } catch (e) {
        app.toastMsg(e?.message || '回滚失败', 'error')
      } finally {
        acting.value = false
      }
    },
  }
}

// ---- 规则编辑 ----

function valueToText(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join(',')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function coerceValue(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return ''
  if (/^-?\d+(\.\d+)?$/.test(raw)) return Number(raw)
  if (raw === 'true') return true
  if (raw === 'false') return false
  if (raw === 'null') return null
  if ((raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'))) {
    try {
      return JSON.parse(raw)
    } catch (e) {
      return raw
    }
  }
  return raw
}

function parseConditionValue(row) {
  const op = row.operator
  if (op === 'is_null' || op === 'is_not_null') return null
  if (op === 'in' || op === 'not_in' || op === 'between') {
    return String(row.valueText || '')
      .split(',')
      .map((part) => part.trim())
      .filter((part) => part !== '')
      .map(coerceValue)
  }
  return coerceValue(row.valueText)
}

function valuePlaceholder(op) {
  if (op === 'in' || op === 'not_in') return 'A,B,C'
  if (op === 'between') return '100,200'
  if (op === 'is_null' || op === 'is_not_null') return '无需填写'
  return '比较值'
}

function onOperatorChange(row) {
  if (row.operator === 'is_null' || row.operator === 'is_not_null') row.valueText = ''
}

function addCondition() {
  ruleForm.value.conditions.push(emptyCondition())
}

function removeCondition(index) {
  ruleForm.value.conditions.splice(index, 1)
}

function addAction() {
  ruleForm.value.action_items.push(emptyAction())
}

function removeAction(index) {
  ruleForm.value.action_items.splice(index, 1)
}

function onActionTypeChange(row) {
  row.params = {}
}

function actionHint(type) {
  const map = {
    set_field: '把计算结果写回事实字段',
    notify: '命中后创建站内通知',
    webhook: '仅入库排队，由外部投递器消费',
    route: '把事实路由到指定队列',
    score: '在现有分值上累加',
    flag: '写入 facts.flags 标记',
    approve: '输出通过决策',
    reject: '输出驳回决策',
    create_task: '生成待办任务',
  }
  return map[type] || ''
}

function actionFields(type) {
  const map = {
    set_field: [
      { key: 'field', label: '目标字段', placeholder: 'facts.level' },
      { key: 'value', label: '写入值', placeholder: 'high' },
    ],
    notify: [
      { key: 'title', label: '标题', placeholder: '规则命中提醒' },
      { key: 'message', label: '正文', placeholder: '订单 {facts.order_no} 命中风控' },
      { key: 'to', label: '接收人', placeholder: '用户名，可空' },
    ],
    webhook: [
      { key: 'url', label: 'Webhook 地址', placeholder: 'https://example.com/hook' },
      { key: 'method', label: '请求方法', placeholder: 'POST' },
    ],
    route: [{ key: 'target', label: '目标队列', placeholder: 'risk-review' }],
    score: [
      { key: 'field', label: '评分字段', placeholder: 'facts.score' },
      { key: 'delta', label: '累加值', placeholder: '10' },
    ],
    flag: [
      { key: 'name', label: '标记名', placeholder: 'need_review' },
      { key: 'value', label: '标记值', placeholder: 'true / false' },
    ],
    approve: [{ key: 'reason', label: '通过理由', placeholder: '满足自动通过条件' }],
    reject: [{ key: 'reason', label: '驳回理由', placeholder: '命中高风险规则' }],
    create_task: [
      { key: 'title', label: '任务标题', placeholder: '人工复核订单 {facts.order_no}' },
      { key: 'assignee', label: '处理人', placeholder: '用户名，可空' },
      { key: 'due_days', label: '几天后到期', placeholder: '1' },
    ],
  }
  return map[type] || []
}

function openRuleCreate() {
  if (!detail.value) return
  ruleForm.value = emptyRuleForm()
  ruleForm.value.ruleset_id = detail.value.id
  ruleError.value = ''
  ruleShow.value = true
}

async function openRuleEdit(rule) {
  ruleError.value = ''
  ruleForm.value = {
    id: rule.id,
    ruleset_id: rule.ruleset_id || detail.value?.id,
    name: rule.name || '',
    description: rule.description || '',
    priority: Number(rule.priority) || 100,
    enabled: rule.enabled !== false,
    condition: rule.condition || '',
    conditions: [],
    action_items: [],
  }
  ruleShow.value = true
  try {
    const full = await api.get(`rules/${rule.id}/`)
    ruleForm.value.condition = full.condition || ''
    ruleForm.value.conditions = (full.conditions || []).map((row) => ({
      field: row.field || '',
      operator: row.operator || '==',
      valueText: valueToText(row.value),
      logic_group: row.logic_group || 'and',
      enabled: row.enabled !== false,
    }))
    ruleForm.value.action_items = (full.action_items || []).map((row) => ({
      type: row.type || 'set_field',
      params: { ...(row.params || {}) },
    }))
    if (!ruleForm.value.conditions.length) ruleForm.value.conditions.push(emptyCondition())
    if (!ruleForm.value.action_items.length) ruleForm.value.action_items.push(emptyAction())
  } catch (e) {
    ruleShow.value = false
    app.toastMsg(e?.message || '规则详情加载失败', 'error')
  }
}

async function saveRule() {
  if (!ruleForm.value.name.trim()) {
    ruleError.value = '请填写规则名称'
    return
  }
  const payload = {
    ruleset_id: ruleForm.value.ruleset_id,
    name: ruleForm.value.name.trim(),
    description: ruleForm.value.description,
    priority: Number(ruleForm.value.priority) || 100,
    enabled: !!ruleForm.value.enabled,
    condition: ruleForm.value.condition,
    conditions: ruleForm.value.conditions
      .filter((row) => row.field.trim())
      .map((row, index) => ({
        field: row.field.trim(),
        operator: row.operator,
        value: parseConditionValue(row),
        logic_group: row.logic_group || 'and',
        sort_order: index,
        enabled: !!row.enabled,
      })),
    action_items: ruleForm.value.action_items.map((row, index) => ({
      type: row.type,
      params: cleanParams(row.params),
      sort_order: index,
      enabled: true,
    })),
  }
  ruleSaving.value = true
  ruleError.value = ''
  try {
    if (ruleForm.value.id) {
      await api.post(`rules/${ruleForm.value.id}/`, payload)
      app.toastMsg('规则已更新', 'success')
    } else {
      await api.post('rules/', payload)
      app.toastMsg('规则已创建', 'success')
    }
    ruleShow.value = false
    await loadDetail(ruleForm.value.ruleset_id)
    await loadList()
  } catch (e) {
    ruleError.value = e?.message || '保存失败'
    app.toastMsg(ruleError.value, 'error')
  } finally {
    ruleSaving.value = false
  }
}

function cleanParams(params) {
  const out = {}
  for (const [key, value] of Object.entries(params || {})) {
    if (value === '' || value === null || value === undefined) continue
    out[key] = value
  }
  return out
}

async function toggleRule(rule) {
  acting.value = true
  try {
    await api.action(`rules/${rule.id}/toggle/`, { enabled: !rule.enabled })
    app.toastMsg(rule.enabled ? '规则已停用' : '规则已启用', 'success')
    if (detail.value) await loadDetail(detail.value.id)
  } catch (e) {
    app.toastMsg(e?.message || '切换失败', 'error')
  } finally {
    acting.value = false
  }
}

function askDeleteRule(rule) {
  confirm.value = {
    show: true,
    title: '删除规则',
    text: `确认删除规则「${rule.name}」？条件与动作会一并删除。`,
    danger: true,
    action: async () => {
      acting.value = true
      try {
        await api.action(`rules/${rule.id}/delete/`, {})
        app.toastMsg('规则已删除', 'success')
        if (detail.value) await loadDetail(detail.value.id)
        await loadList()
      } catch (e) {
        app.toastMsg(e?.message || '删除失败', 'error')
      } finally {
        acting.value = false
      }
    },
  }
}

watch(
  () => props.refreshKey,
  () => loadList()
)

watch(
  () => props.rulesetId,
  (value) => {
    if (value && detail.value && String(detail.value.id) !== String(value)) {
      detailShow.value = false
    }
  }
)

onMounted(loadList)
</script>