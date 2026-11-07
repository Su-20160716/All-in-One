<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 顶部标题与全局操作 -->
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="text-[16px] font-semibold text-ink-800">{{ domain.name || '表单设计器' }}</h2>
          <span class="tag-brand">5 个页签</span>
          <span v-if="catalog" class="tag">目录接口已连接</span>
          <span v-else-if="catalogError" class="tag" :title="catalogError">目录降级</span>
        </div>
        <p class="mt-1 text-[12px] text-ink-400">
          {{ domain.description || '表单建模、条件逻辑、版本发布、提交审核与字段统计。' }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="tag">表单 {{ formTotal }}</span>
        <span class="tag">已发布 {{ publishedCount }}</span>
        <span class="tag" :class="overviewPending > 0 ? 'bg-amber-50 text-amber-600' : ''">
          待审核 {{ overviewPending }}
        </span>
        <button class="btn-outline" :disabled="ovLoading" @click="reloadAll">
          {{ ovLoading ? '刷新中…' : '刷新数据' }}
        </button>
        <button class="btn-primary" @click="openCreate">新建表单</button>
      </div>
    </div>

    <!-- 页签 -->
    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="item in TABS"
        :key="item.key"
        type="button"
        class="rounded-pill px-3 py-1 text-[12px] transition-colors"
        :class="tab === item.key ? 'bg-brand-600 text-white' : 'bg-white text-ink-600 border border-ink-200 hover:border-brand-300'"
        @click="switchTab(item.key)"
      >
        {{ item.label }}
        <span
          v-if="item.key === 'forms'"
          class="ml-1 text-[11px]"
          :class="tab === item.key ? 'text-white/80' : 'text-ink-400'"
        >{{ formTotal }}</span>
        <span
          v-else-if="item.key === 'overview'"
          class="ml-1 text-[11px]"
          :class="tab === item.key ? 'text-white/80' : 'text-ink-400'"
        >{{ allForms.length }}</span>
      </button>
      <span class="ml-auto hidden text-[11px] text-ink-400 sm:block">
        数据来源：/api/formstudio/
      </span>
    </div>

    <!-- 表单总览 -->
    <div v-if="tab === 'overview'" class="space-y-4">
      <div v-if="ovError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ ovError }}</span>
        <button type="button" class="shrink-0 font-medium" @click="loadOverview()">重试</button>
      </div>
      <div v-else-if="ovWarning" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-600">
        {{ ovWarning }}
      </div>

      <StatsGrid :items="overviewStats" :loading="ovLoading && !allForms.length" />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <SectionCard
          class="lg:col-span-2"
          title="表单类型分布"
          subtitle="按定义中的表单类型统计，归档表单未计入默认列表"
          dense
        >
          <template #badge>
            <span class="tag">{{ allForms.length }} 个表单</span>
          </template>
          <div v-if="ovLoading && !allForms.length" class="py-12 text-center text-[12px] text-ink-400">
            加载中…
          </div>
          <DonutChart
            v-else
            :data="typeDonut"
            :size="168"
            center-label="表单"
            :center-value="allForms.length"
            legend-position="right"
            empty-text="暂无表单类型数据"
          />
        </SectionCard>

        <SectionCard
          class="lg:col-span-3"
          title="近 14 天提交趋势"
          subtitle="按提交时间按日聚合，含已审核量对比"
          dense
        >
          <template #actions>
            <span class="tag">合计 {{ trendTotal }} 份</span>
          </template>
          <div v-if="ovLoading && !ovTrendRows.length" class="py-12 text-center text-[12px] text-ink-400">
            加载中…
          </div>
          <LineChart
            v-else
            :series="trendSeries"
            :labels="trendLabels"
            :height="220"
            :max-x-labels="7"
            aria-label="近 14 天提交趋势"
            empty-text="近 14 天暂无提交"
          />
        </SectionCard>
      </div>

      <SectionCard title="最近提交" subtitle="取近 14 天内的最新 8 条记录" dense>
        <template #actions>
          <button class="btn-ghost" type="button" @click="switchTab('submissions')">查看全部</button>
          <button class="btn-ghost" type="button" :disabled="ovLoading" @click="loadOverview()">刷新</button>
        </template>
        <div v-if="ovLoading && !ovRecent.length" class="py-10 text-center text-[12px] text-ink-400">
          加载中…
        </div>
        <div v-else-if="!ovRecent.length" class="py-10 text-center text-[12px] text-ink-400">
          近 14 天还没有提交记录
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[760px] text-left">
            <thead class="border-b border-ink-100 bg-ink-50/60">
              <tr>
                <th class="th">表单</th>
                <th class="th">提交人</th>
                <th class="th">状态</th>
                <th class="th">得分</th>
                <th class="th">耗时</th>
                <th class="th">来源</th>
                <th class="th">版本</th>
                <th class="th">提交时间</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in ovRecent" :key="row.id" class="hover:bg-ink-50/60">
                <td class="td">
                  <span class="block max-w-[220px] truncate">{{ row.form_name || '未命名表单' }}</span>
                </td>
                <td class="td">{{ personName(row.submitted_by) }}</td>
                <td class="td">
                  <span class="tag" :class="submissionStatusClass(row.status)">
                    {{ submissionStatusLabel(row.status) }}
                  </span>
                </td>
                <td class="td">{{ scoreText(row) }}</td>
                <td class="td">{{ durationText(row.duration_seconds) }}</td>
                <td class="td">{{ sourceLabel(row.source) }}</td>
                <td class="td">v{{ row.version_no || 0 }}</td>
                <td class="td">{{ formatDate(row.submitted_at, true) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>

    <!-- 表单管理 -->
    <div v-else-if="tab === 'forms'" class="space-y-4">
      <div class="card p-3">
        <div class="flex flex-wrap items-end gap-2">
          <label class="flex min-w-[200px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
            关键词
            <input
              v-model="formQuery"
              class="input"
              placeholder="搜索表单名称 / 编码 / 描述"
              @keyup.enter="applyFormFilters"
            />
          </label>
          <label class="flex w-36 flex-col gap-1 text-[11px] text-ink-500">
            状态
            <select v-model="formStatus" class="input" @change="applyFormFilters">
              <option value="">全部状态</option>
              <option v-for="s in statusOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
          </label>
          <label class="flex w-36 flex-col gap-1 text-[11px] text-ink-500">
            类型
            <select v-model="formTypeFilter" class="input" @change="applyFormFilters">
              <option value="">全部类型</option>
              <option v-for="t in formTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </label>
          <label class="flex items-center gap-1.5 pb-1.5 text-[12px] text-ink-600">
            <input v-model="includeArchived" type="checkbox" class="h-3.5 w-3.5" @change="applyFormFilters" />
            含归档
          </label>
          <button class="btn-primary" type="button" @click="applyFormFilters">查询</button>
          <button class="btn-ghost" type="button" @click="resetFormFilters">重置</button>
          <button class="btn-outline" type="button" @click="openTemplates">从模板创建</button>
          <button class="btn-outline" type="button" :disabled="formsLoading" @click="refreshForms()">
            {{ formsLoading ? '加载中…' : '刷新' }}
          </button>
        </div>

        <div v-if="selectedIds.length" class="mt-3 flex flex-wrap items-center gap-2 rounded-control bg-brand-50 px-3 py-2 text-[12px] text-brand-700">
          <span>已选择 {{ selectedIds.length }} 个表单</span>
          <button class="btn-ghost !py-1" type="button" @click="batchPublish">批量发布</button>
          <button class="btn-ghost !py-1" type="button" @click="batchArchive">批量归档</button>
          <button class="btn-ghost !py-1" type="button" @click="selectedIds = []">清除选择</button>
        </div>
      </div>

      <div class="card overflow-hidden">
        <div v-if="formsLoading && !formItems.length" class="py-12 text-center text-[12px] text-ink-400">
          加载中…
        </div>
        <div v-else-if="formsError" class="flex flex-wrap items-center gap-3 px-4 py-3 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ formsError }}</span>
          <button class="font-medium" type="button" @click="refreshForms()">重试</button>
        </div>
        <div v-else-if="formsEmpty" class="py-14 text-center text-[12px] text-ink-400">
          <p>还没有符合条件的表单</p>
          <div class="mt-3 flex justify-center gap-2">
            <button class="btn-primary" type="button" @click="openCreate">新建表单</button>
            <button class="btn-outline" type="button" @click="openTemplates">从模板创建</button>
          </div>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[1040px] text-left">
            <thead class="border-b border-ink-100 bg-ink-50/60">
              <tr>
                <th class="th w-10">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5"
                    :checked="allSelected"
                    aria-label="全选当前页"
                    @change="toggleAll"
                  />
                </th>
                <th class="th">表单</th>
                <th class="th">类型</th>
                <th class="th">状态</th>
                <th class="th">提交</th>
                <th class="th">字段 / 分区</th>
                <th class="th">负责人</th>
                <th class="th">更新时间</th>
                <th class="th">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="form in formItems" :key="form.id" class="hover:bg-ink-50/60">
                <td class="td">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5"
                    :checked="selectedIds.includes(form.id)"
                    :aria-label="`选择 ${form.name}`"
                    @change="toggleSelect(form.id)"
                  />
                </td>
                <td class="td">
                  <div class="flex min-w-0 flex-col">
                    <span class="truncate text-[13px] font-medium text-ink-800">{{ form.name }}</span>
                    <span class="truncate text-[11px] text-ink-400">{{ form.code }} · #{{ form.id }}</span>
                  </div>
                </td>
                <td class="td">{{ typeLabel(form.form_type) }}</td>
                <td class="td">
                  <span class="tag" :class="formStatusClass(form.status)">{{ formStatusLabel(form.status) }}</span>
                  <span v-if="form.is_expired" class="tag ml-1 bg-amber-50 text-amber-600">已过期</span>
                </td>
                <td class="td">{{ formatNumber(form.submission_count) }}</td>
                <td class="td">{{ form.field_count ?? 0 }} / {{ form.section_count ?? 0 }}</td>
                <td class="td">{{ personName(form.owner) }}</td>
                <td class="td">
                  <span class="block text-[12px] text-ink-600">{{ formatDate(form.updated_at, true) }}</span>
                  <span class="text-[11px] text-ink-400">{{ timeAgo(form.updated_at) }}</span>
                </td>
                <td class="td">
                  <div class="flex flex-wrap items-center gap-1">
                    <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="openDesigner(form)">
                      设计
                    </button>
                    <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="openEdit(form)">
                      编辑
                    </button>
                    <button
                      v-if="canPublish(form)"
                      class="btn-ghost !px-1.5 !py-0.5 !text-[11px]"
                      type="button"
                      @click="askAction('publish', form)"
                    >
                      发布
                    </button>
                    <button
                      v-if="form.status === 'published'"
                      class="btn-ghost !px-1.5 !py-0.5 !text-[11px]"
                      type="button"
                      @click="askAction('close', form)"
                    >
                      关闭
                    </button>
                    <button
                      v-if="form.status !== 'archived'"
                      class="btn-ghost !px-1.5 !py-0.5 !text-[11px]"
                      type="button"
                      @click="askAction('archive', form)"
                    >
                      归档
                    </button>
                    <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="askAction('clone', form)">
                      克隆
                    </button>
                    <button
                      class="btn-ghost !px-1.5 !py-0.5 !text-[11px] !text-rose-600"
                      type="button"
                      @click="askAction('delete', form)"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="formItems.length" class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
          <span>共 {{ formTotal }} 条 · 第 {{ formsPage }} / {{ formsPages }} 页</span>
          <div class="flex items-center gap-2">
            <select
              class="input !w-auto !py-1 !text-[11px]"
              :value="formsPageSize"
              aria-label="每页条数"
              @change="changeFormsPageSize(Number($event.target.value))"
            >
              <option :value="10">10 条/页</option>
              <option :value="20">20 条/页</option>
              <option :value="50">50 条/页</option>
            </select>
            <button class="btn-ghost" type="button" :disabled="formsPage <= 1" @click="goFormsPage(formsPage - 1)">
              上一页
            </button>
            <button class="btn-ghost" type="button" :disabled="formsPage >= formsPages" @click="goFormsPage(formsPage + 1)">
              下一页
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 提交记录 -->
    <SubmissionsPanel
      v-else-if="tab === 'submissions'"
      :forms="allForms"
      @changed="onSubmissionChanged"
    />

    <!-- 字段分析 -->
    <AnalyticsPanel v-else-if="tab === 'analytics'" :forms="allForms" />

    <!-- 模板与分享 -->
    <SettingsPanel v-else :forms="allForms" @changed="onSettingsChanged" />

    <!-- 新建 / 编辑表单 -->
    <Modal v-model="editorOpen" :title="editorMode === 'create' ? '新建表单' : '编辑表单'" width="620px">
      <div class="space-y-3">
        <div v-if="editorError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ editorError }}
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            表单名称 <span class="text-rose-500">*</span>
            <input v-model="editor.name" class="input" maxlength="200" placeholder="例如：客户满意度调查" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            表单编码
            <input v-model="editor.code" class="input" maxlength="64" placeholder="留空自动生成" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            表单类型
            <select v-model="editor.form_type" class="input">
              <option v-for="t in formTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            截止时间
            <input v-model="editor.deadline" class="input" type="datetime-local" />
          </label>
        </div>
        <label class="flex flex-col gap-1 text-[11px] text-ink-500">
          描述
          <textarea v-model="editor.description" class="input min-h-[72px]" maxlength="1000" placeholder="说明表单用途、适用范围与注意事项" />
        </label>
        <div class="flex flex-wrap items-center gap-4 text-[12px] text-ink-600">
          <label class="flex items-center gap-1.5">
            <input v-model="editor.allow_anonymous" type="checkbox" class="h-3.5 w-3.5" />
            允许匿名提交
          </label>
          <label class="flex items-center gap-1.5">
            <input v-model="editor.allow_multiple" type="checkbox" class="h-3.5 w-3.5" />
            允许多次提交
          </label>
        </div>
        <p class="text-[11px] text-ink-400">
          提示：新建后状态为草稿，需要在设计器中保存字段结构并发布后才会接收提交。
        </p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" type="button" @click="editorOpen = false">取消</button>
          <button class="btn-primary" type="button" :disabled="editorSaving" @click="submitEditor">
            {{ editorSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 从模板创建 -->
    <Modal v-model="templateOpen" title="从模板创建表单" width="760px">
      <div class="space-y-3">
        <div class="flex flex-wrap items-end gap-2">
          <label class="flex min-w-[220px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
            新表单名称（可选）
            <input v-model="templateName" class="input" placeholder="留空则沿用模板名称" maxlength="200" />
          </label>
          <button class="btn-outline" type="button" :disabled="templateLoading" @click="loadTemplates">
            {{ templateLoading ? '加载中…' : '刷新模板' }}
          </button>
        </div>
        <div v-if="templateError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ templateError }}</span>
          <button class="font-medium" type="button" @click="loadTemplates">重试</button>
        </div>
        <div v-else-if="templateLoading && !templates.length" class="py-10 text-center text-[12px] text-ink-400">
          模板加载中…
        </div>
        <div v-else-if="!templates.length" class="py-10 text-center text-[12px] text-ink-400">
          暂无可用模板
        </div>
        <div v-else class="grid max-h-[52vh] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
          <div v-for="tpl in templates" :key="tpl.id" class="rounded-control border border-ink-100 p-3">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <p class="truncate text-[13px] font-medium text-ink-800">{{ tpl.name }}</p>
                <p class="mt-0.5 truncate text-[11px] text-ink-400">{{ tpl.description || '暂无说明' }}</p>
              </div>
              <span class="tag shrink-0">{{ tpl.category || '通用' }}</span>
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-400">
              <span class="tag">{{ typeLabel(tpl.form_type) }}</span>
              <span class="tag">{{ tpl.field_count || 0 }} 个字段</span>
              <span v-if="tpl.builtin" class="tag bg-brand-50 text-brand-700">内置</span>
              <span class="tag">已用 {{ tpl.usage_count || 0 }}</span>
            </div>
            <button
              class="btn-primary mt-2 !py-1 w-full"
              type="button"
              :disabled="templateCreatingId === tpl.id"
              @click="createFromTemplate(tpl)"
            >
              {{ templateCreatingId === tpl.id ? '创建中…' : '使用此模板' }}
            </button>
          </div>
        </div>
        <div class="flex justify-end">
          <button class="btn-ghost" type="button" @click="templateOpen = false">关闭</button>
        </div>
      </div>
    </Modal>

    <!-- 通用确认 -->
    <Modal v-model="confirmOpen" :title="confirmState.title" width="420px">
      <div class="space-y-3">
        <p class="text-[12px] leading-relaxed text-ink-600">{{ confirmState.message }}</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" type="button" @click="confirmOpen = false">取消</button>
          <button
            class="btn-primary"
            :class="confirmState.danger ? '!bg-rose-600 hover:!bg-rose-700' : ''"
            type="button"
            :disabled="confirmBusy"
            @click="runConfirm"
          >
            {{ confirmBusy ? '处理中…' : confirmState.confirmText }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 设计器抽屉 -->
    <SchemaDesigner
      v-model="designerOpen"
      :form="designerForm"
      @saved="onDesignerChanged"
      @published="onDesignerChanged"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useAppStore } from '../../stores/app'
import { formstudioApi } from '../../api/platform'
import { findDomain } from '../../api/domains'
import {
  formatDate,
  formatNumber,
  statusTone,
  timeAgo,
  useDomainResource,
} from '../../composables/useDomainResource'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import LineChart from '../../components/platform/LineChart.vue'
import Modal from '../../components/Modal.vue'
import SchemaDesigner from './SchemaDesigner.vue'
import SubmissionsPanel from './SubmissionsPanel.vue'
import AnalyticsPanel from './AnalyticsPanel.vue'
import SettingsPanel from './SettingsPanel.vue'

const app = useAppStore()

const FALLBACK_TABS = [
  { key: 'overview', label: '表单总览' },
  { key: 'forms', label: '表单管理' },
  { key: 'submissions', label: '提交记录' },
  { key: 'analytics', label: '字段分析' },
  { key: 'settings', label: '模板与分享' },
]
const domain = findDomain('formstudio') || { name: '表单设计器', description: '', tabs: FALLBACK_TABS }
const TABS = Array.isArray(domain.tabs) && domain.tabs.length ? domain.tabs : FALLBACK_TABS
const tab = ref('overview')
function switchTab(next) {
  if (!TABS.some((t) => t.key === next)) return
  tab.value = next
}

const FALLBACK_FORM_TYPES = [
  { value: 'survey', label: '问卷' },
  { value: 'quiz', label: '测验' },
  { value: 'collect', label: '信息收集' },
  { value: 'registration', label: '报名登记' },
  { value: 'approval', label: '审批申请' },
  { value: 'feedback', label: '意见反馈' },
]
const FALLBACK_STATUSES = [
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'closed', label: '已关闭' },
  { value: 'archived', label: '已归档' },
]
const SUB_STATUS_LABELS = {
  draft: '草稿',
  submitted: '已提交',
  reviewed: '已审核',
  rejected: '已驳回',
}
const SOURCE_LABELS = {
  web: '网页',
  share: '分享链接',
  api: '接口',
  embed: '嵌入',
  import: '导入',
}

const catalog = ref(null)
const catalogError = ref('')
const formTypes = computed(() =>
  Array.isArray(catalog.value?.form_types) && catalog.value.form_types.length
    ? catalog.value.form_types
    : FALLBACK_FORM_TYPES
)
const statusOptions = computed(() =>
  Array.isArray(catalog.value?.statuses) && catalog.value.statuses.length
    ? catalog.value.statuses
    : FALLBACK_STATUSES
)

function typeLabel(value) {
  const hit = formTypes.value.find((t) => t.value === value)
  return hit ? hit.label : value || '—'
}
function formStatusLabel(value) {
  const hit = statusOptions.value.find((s) => s.value === value)
  return hit ? hit.label : value || '—'
}
function formStatusClass(value) {
  const tone = statusTone(value)
  if (tone === 'success') return 'bg-emerald-50 text-emerald-600'
  if (tone === 'warning') return 'bg-amber-50 text-amber-600'
  if (tone === 'danger') return 'bg-rose-50 text-rose-600'
  return 'bg-ink-100 text-ink-600'
}
function submissionStatusLabel(value) {
  return SUB_STATUS_LABELS[value] || value || '—'
}
function submissionStatusClass(value) {
  if (value === 'reviewed') return 'bg-emerald-50 text-emerald-600'
  if (value === 'submitted') return 'bg-brand-50 text-brand-700'
  if (value === 'rejected') return 'bg-rose-50 text-rose-600'
  return 'bg-ink-100 text-ink-600'
}
function sourceLabel(value) {
  return SOURCE_LABELS[value] || value || '—'
}
function personName(user) {
  if (!user) return '匿名'
  return user.name || user.username || '—'
}
function scoreText(row) {
  if (row?.score === null || row?.score === undefined) return '—'
  const max = row?.max_score
  return max === null || max === undefined ? String(row.score) : `${row.score} / ${max}`
}
function durationText(seconds) {
  const n = Number(seconds)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n < 60) return `${Math.round(n)} 秒`
  const minutes = Math.floor(n / 60)
  const rest = Math.round(n % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
}

// ---------------------------------------------------------------------------
// 目录与总览
// ---------------------------------------------------------------------------
async function loadCatalog() {
  catalogError.value = ''
  try {
    catalog.value = await formstudioApi.get('')
  } catch (e) {
    catalog.value = null
    catalogError.value = e?.message || '目录加载失败'
  }
}

const ovLoading = ref(false)
const ovError = ref('')
const ovWarning = ref('')
const allForms = ref([])
const ovMonthCount = ref(0)
const ovPending = ref(0)
const ovFinalCount = ref(0)
const ovTotalCount = ref(0)
const ovTrendRows = ref([])
const ovRecent = ref([])

const publishedCount = computed(() => allForms.value.filter((f) => f.status === 'published').length)
const overviewPending = computed(() => ovPending.value)
const ovCompletion = computed(() => {
  if (!ovTotalCount.value) return 0
  return (ovFinalCount.value * 100) / ovTotalCount.value
})
const trendTotal = computed(() => ovTrendRows.value.reduce((sum, row) => sum + row.submissions, 0))

function pad2(n) {
  return String(n).padStart(2, '0')
}
function isoDay(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

function buildTrend(items) {
  const bucket = new Map()
  for (const item of items) {
    const stamp = item.submitted_at || item.created_at
    const day = String(stamp || '').slice(0, 10)
    if (!day) continue
    const cell = bucket.get(day) || { submissions: 0, reviewed: 0 }
    cell.submissions += 1
    if (item.status === 'reviewed') cell.reviewed += 1
    bucket.set(day, cell)
  }
  const rows = []
  for (let offset = 13; offset >= 0; offset -= 1) {
    const date = new Date()
    date.setHours(12, 0, 0, 0)
    date.setDate(date.getDate() - offset)
    const key = isoDay(date)
    const cell = bucket.get(key) || { submissions: 0, reviewed: 0 }
    rows.push({ date: key, submissions: cell.submissions, reviewed: cell.reviewed })
  }
  return rows
}

const overviewStats = computed(() => [
  {
    key: 'forms',
    label: '表单数',
    value: allForms.value.length,
    unit: '个',
    hint: `草稿 ${allForms.value.filter((f) => f.status === 'draft').length} 个`,
    icon: '▤',
    tone: 'brand',
  },
  {
    key: 'published',
    label: '已发布',
    value: publishedCount.value,
    unit: '个',
    hint: `关闭 ${allForms.value.filter((f) => f.status === 'closed').length} 个`,
    icon: '◈',
    tone: 'emerald',
  },
  {
    key: 'month',
    label: '本月提交',
    value: ovMonthCount.value,
    unit: '份',
    hint: '按提交时间从当月 1 日起统计',
    icon: '◷',
  },
  {
    key: 'completion',
    label: '平均完成率',
    value: `${ovCompletion.value.toFixed(1)}%`,
    hint: `有效提交 ${formatNumber(ovFinalCount.value)} / 全部 ${formatNumber(ovTotalCount.value)}（含草稿）`,
    icon: '◔',
    tone: 'amber',
  },
  {
    key: 'pending',
    label: '待审核',
    value: ovPending.value,
    unit: '条',
    hint: '状态为已提交、等待审核',
    icon: '◇',
    tone: ovPending.value > 0 ? 'amber' : 'default',
  },
])

const typeDonut = computed(() => {
  const counter = new Map()
  for (const form of allForms.value) {
    const label = typeLabel(form.form_type)
    counter.set(label, (counter.get(label) || 0) + 1)
  }
  return Array.from(counter.entries()).map(([label, value]) => ({ label, value }))
})

const trendLabels = computed(() => ovTrendRows.value.map((row) => row.date.slice(5)))
const trendSeries = computed(() => [
  {
    name: '提交量',
    color: 'var(--brand-500)',
    area: true,
    data: ovTrendRows.value.map((row) => row.submissions),
  },
  {
    name: '已审核',
    color: '#10b981',
    data: ovTrendRows.value.map((row) => row.reviewed),
  },
])

function sortRecent(items) {
  return [...items]
    .sort((a, b) => String(b.submitted_at || '').localeCompare(String(a.submitted_at || '')))
    .slice(0, 8)
}

async function loadOverview(silent = false) {
  if (!silent) ovLoading.value = true
  ovError.value = ''
  ovWarning.value = ''
  const monthStart = new Date()
  monthStart.setDate(1)
  monthStart.setHours(0, 0, 0, 0)
  const trendStart = new Date()
  trendStart.setHours(0, 0, 0, 0)
  trendStart.setDate(trendStart.getDate() - 13)
  const jobs = [
    formstudioApi.list('forms/', { page: 1, page_size: 200 }),
    formstudioApi.list('submissions/', { page: 1, page_size: 1, date_from: isoDay(monthStart) }),
    formstudioApi.list('submissions/', { page: 1, page_size: 1, status: 'submitted' }),
    formstudioApi.list('submissions/', { page: 1, page_size: 1, include_drafts: 1 }),
    formstudioApi.list('submissions/', { page: 1, page_size: 1 }),
    formstudioApi.list('submissions/', {
      page: 1,
      page_size: 200,
      date_from: isoDay(trendStart),
    }),
    formstudioApi.list('submissions/', { page: 1, page_size: 1, status: 'rejected' }),
  ]
  const results = await Promise.allSettled(jobs)
  const failures = []
  const formsRes = results[0]
  if (formsRes.status === 'fulfilled') {
    allForms.value = formsRes.value.items || []
  } else {
    failures.push(formsRes.reason)
  }
  if (results[1].status === 'fulfilled') ovMonthCount.value = results[1].value.count || 0
  else failures.push(results[1].reason)
  if (results[2].status === 'fulfilled') ovPending.value = results[2].value.count || 0
  else failures.push(results[2].reason)
  if (results[3].status === 'fulfilled') ovTotalCount.value = results[3].value.count || 0
  else failures.push(results[3].reason)
  if (results[4].status === 'fulfilled') {
    const nonDraft = results[4].value.count || 0
    const rejected = results[6]?.status === 'fulfilled' ? results[6].value.count || 0 : 0
    ovFinalCount.value = Math.max(0, nonDraft - rejected)
  } else {
    failures.push(results[4].reason)
  }
  if (results[5].status === 'fulfilled') {
    const recent = results[5].value.items || []
    ovTrendRows.value = buildTrend(recent)
    ovRecent.value = sortRecent(recent)
  } else {
    failures.push(results[5].reason)
    ovTrendRows.value = []
    ovRecent.value = []
  }
  if (formsRes.status === 'rejected' && !allForms.value.length) {
    const reason = formsRes.reason
    if (reason?.status === 404 || reason?.status === 405) {
      ovWarning.value = '表单列表接口暂不可用，总览已降级为空态，可稍后重试'
    } else {
      ovError.value = reason?.message || '总览加载失败'
    }
  } else if (failures.length) {
    ovWarning.value = `部分统计接口暂不可用（${failures.length} 项），已按可用数据降级展示`
  }
  ovLoading.value = false
}

function reloadAll() {
  loadCatalog()
  refreshForms()
  loadOverview()
}

// ---------------------------------------------------------------------------
// 表单管理
// ---------------------------------------------------------------------------
const {
  items: formItems,
  loading: formsLoading,
  error: formsError,
  empty: formsEmpty,
  q: formQuery,
  status: formStatus,
  filters: formFilters,
  page: formsPage,
  pageSize: formsPageSize,
  total: formTotal,
  pages: formsPages,
  setPage: setFormsPage,
  setPageSize: setFormsPageSize,
  refresh: refreshForms,
  create: createForm,
  remove: removeForm,
  run: runFormAction,
} = useDomainResource('formstudio', 'forms/', { pageSize: 20, auto: false })

const formTypeFilter = ref('')
const includeArchived = ref(false)

function applyFormFilters() {
  formFilters.value = {
    form_type: formTypeFilter.value || undefined,
    include_archived: includeArchived.value ? 1 : undefined,
  }
  setFormsPage(1)
  refreshForms()
}
function changeFormsPageSize(size) {
  setFormsPageSize(size)
  refreshForms()
}
function goFormsPage(next) {
  setFormsPage(next)
  refreshForms()
}
function resetFormFilters() {
  formQuery.value = ''
  formStatus.value = ''
  formTypeFilter.value = ''
  includeArchived.value = false
  formFilters.value = {}
  setFormsPage(1)
  refreshForms()
}

const selectedIds = ref([])
const selectedForms = computed(() => formItems.value.filter((f) => selectedIds.value.includes(f.id)))
const allSelected = computed(
  () => formItems.value.length > 0 && formItems.value.every((f) => selectedIds.value.includes(f.id))
)
function toggleSelect(id) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}
function toggleAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = formItems.value.map((f) => f.id)
  }
}
function canPublish(form) {
  return form.status === 'draft' || form.status === 'closed'
}

const ACTION_TEXT = {
  publish: { title: '发布表单', message: '发布将校验字段结构并生成新版本快照，之后即可接收提交。', confirmText: '发布' },
  close: { title: '关闭表单', message: '关闭后停止接收新提交，历史数据与版本全部保留。', confirmText: '关闭' },
  archive: { title: '归档表单', message: '归档后表单从默认列表隐藏，提交记录与版本仍可查询。', confirmText: '归档' },
  clone: { title: '克隆表单', message: '将复制分区、字段、校验与逻辑规则，不复制提交、分享链接与 Webhook。', confirmText: '克隆' },
  delete: { title: '删除表单', message: '仅没有提交记录的表单可以删除，删除后不可恢复。', confirmText: '删除', danger: true },
}

const confirmOpen = ref(false)
const confirmBusy = ref(false)
const confirmState = reactive({ title: '', message: '', confirmText: '确定', danger: false, run: null })

function askAction(kind, form) {
  const conf = ACTION_TEXT[kind]
  if (!conf) return
  confirmState.title = conf.title
  confirmState.message = `${conf.message}（${form.name}）`
  confirmState.confirmText = conf.confirmText
  confirmState.danger = Boolean(conf.danger)
  confirmState.run = () => executeFormAction(kind, form)
  confirmOpen.value = true
}
async function runConfirm() {
  if (typeof confirmState.run !== 'function') {
    confirmOpen.value = false
    return
  }
  confirmBusy.value = true
  try {
    await confirmState.run()
    confirmOpen.value = false
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    confirmBusy.value = false
  }
}
async function executeFormAction(kind, form) {
  if (kind === 'publish') {
    await runFormAction(`forms/${form.id}/publish/`, { note: '工作台发布' }, '已发布并生成新版本')
  } else if (kind === 'close') {
    await runFormAction(`forms/${form.id}/close/`, {}, '表单已关闭')
  } else if (kind === 'archive') {
    await runFormAction(`forms/${form.id}/archive/`, {}, '表单已归档')
  } else if (kind === 'clone') {
    await runFormAction(`forms/${form.id}/clone/`, { name: `${form.name} 副本` }, '已克隆表单')
  } else if (kind === 'delete') {
    await removeForm(`forms/${form.id}/`)
  }
  if (kind !== 'design') {
    await refreshForms()
    loadOverview(true)
  }
}

async function batchPublish() {
  const rows = selectedForms.value.filter(canPublish)
  if (!rows.length) {
    app.toastMsg('所选表单中没有可发布的草稿或已关闭表单', 'info')
    return
  }
  confirmState.title = '批量发布'
  confirmState.message = `将依次发布 ${rows.length} 个表单并生成新版本，是否继续？`
  confirmState.confirmText = '批量发布'
  confirmState.danger = false
  confirmState.run = async () => {
    let done = 0
    let failed = 0
    for (const form of rows) {
      try {
        await formstudioApi.action(`forms/${form.id}/publish/`, { note: '批量发布' })
        done += 1
      } catch (e) {
        failed += 1
      }
    }
    app.toastMsg(`批量发布完成：成功 ${done} 个，失败 ${failed} 个`, failed ? 'error' : 'success')
    selectedIds.value = []
    await refreshForms()
    loadOverview(true)
  }
  confirmOpen.value = true
}

async function batchArchive() {
  const rows = selectedForms.value.filter((f) => f.status !== 'archived')
  if (!rows.length) {
    app.toastMsg('所选表单均已归档', 'info')
    return
  }
  confirmState.title = '批量归档'
  confirmState.message = `将归档 ${rows.length} 个表单，归档后默认列表不再展示，是否继续？`
  confirmState.confirmText = '批量归档'
  confirmState.danger = false
  confirmState.run = async () => {
    let done = 0
    let failed = 0
    for (const form of rows) {
      try {
        await formstudioApi.action(`forms/${form.id}/archive/`, {})
        done += 1
      } catch (e) {
        failed += 1
      }
    }
    app.toastMsg(`批量归档完成：成功 ${done} 个，失败 ${failed} 个`, failed ? 'error' : 'success')
    selectedIds.value = []
    await refreshForms()
    loadOverview(true)
  }
  confirmOpen.value = true
}

// ---------------------------------------------------------------------------
// 新建 / 编辑
// ---------------------------------------------------------------------------
const editorOpen = ref(false)
const editorMode = ref('create')
const editorSaving = ref(false)
const editorError = ref('')
const editor = reactive({
  id: null,
  name: '',
  code: '',
  form_type: 'survey',
  description: '',
  allow_anonymous: false,
  allow_multiple: true,
  deadline: '',
})

function resetEditor() {
  editor.id = null
  editor.name = ''
  editor.code = ''
  editor.form_type = 'survey'
  editor.description = ''
  editor.allow_anonymous = false
  editor.allow_multiple = true
  editor.deadline = ''
  editorError.value = ''
}
function toLocalInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}
function openCreate() {
  resetEditor()
  editorMode.value = 'create'
  editorOpen.value = true
}
function openEdit(form) {
  resetEditor()
  editorMode.value = 'edit'
  editor.id = form.id
  editor.name = form.name || ''
  editor.code = form.code || ''
  editor.form_type = form.form_type || 'survey'
  editor.description = form.description || ''
  editor.allow_anonymous = Boolean(form.allow_anonymous)
  editor.allow_multiple = Boolean(form.allow_multiple)
  editor.deadline = toLocalInput(form.deadline)
  editorOpen.value = true
}
async function submitEditor() {
  editorError.value = ''
  if (!editor.name.trim()) {
    editorError.value = '请填写表单名称'
    return
  }
  const payload = {
    name: editor.name.trim(),
    form_type: editor.form_type,
    description: editor.description,
    allow_anonymous: editor.allow_anonymous,
    allow_multiple: editor.allow_multiple,
    deadline: editor.deadline ? new Date(editor.deadline).toISOString() : null,
  }
  if (editor.code.trim()) payload.code = editor.code.trim()
  editorSaving.value = true
  try {
    if (editorMode.value === 'create') {
      await createForm(payload)
    } else {
      await formstudioApi.patch(`forms/${editor.id}/`, payload)
      app.toastMsg('已保存', 'success')
      await refreshForms()
    }
    editorOpen.value = false
    await refreshForms()
    loadOverview(true)
  } catch (e) {
    editorError.value = e?.message || '保存失败'
    app.toastMsg(editorError.value, 'error')
  } finally {
    editorSaving.value = false
  }
}

// ---------------------------------------------------------------------------
// 模板
// ---------------------------------------------------------------------------
const templateOpen = ref(false)
const templateLoading = ref(false)
const templateError = ref('')
const templates = ref([])
const templateName = ref('')
const templateCreatingId = ref(null)

async function loadTemplates() {
  templateLoading.value = true
  templateError.value = ''
  try {
    const data = await formstudioApi.list('templates/', { page: 1, page_size: 100 })
    templates.value = data.items || []
  } catch (e) {
    templateError.value = e?.message || '模板加载失败'
    templates.value = []
  } finally {
    templateLoading.value = false
  }
}
function openTemplates() {
  templateOpen.value = true
  templateName.value = ''
  loadTemplates()
}
async function createFromTemplate(tpl) {
  templateCreatingId.value = tpl.id
  try {
    const payload = { template_id: tpl.id }
    if (templateName.value.trim()) payload.name = templateName.value.trim()
    await formstudioApi.action('forms/from-template/', payload)
    app.toastMsg('已从模板创建表单', 'success')
    templateOpen.value = false
    await refreshForms()
    loadOverview(true)
  } catch (e) {
    app.toastMsg(e?.message || '创建失败', 'error')
  } finally {
    templateCreatingId.value = null
  }
}

// ---------------------------------------------------------------------------
// 设计器与页签联动
// ---------------------------------------------------------------------------
const designerOpen = ref(false)
const designerForm = ref(null)
function openDesigner(form) {
  designerForm.value = form
  designerOpen.value = true
}
function onDesignerChanged() {
  refreshForms()
  loadOverview(true)
}
function onSubmissionChanged() {
  loadOverview(true)
}
function onSettingsChanged() {
  refreshForms()
  loadOverview(true)
}

onMounted(() => {
  loadCatalog()
  refreshForms()
  loadOverview()
})

// 供模板与调试使用（不作为业务契约）
defineExpose({ loadOverview, refreshForms })
</script>