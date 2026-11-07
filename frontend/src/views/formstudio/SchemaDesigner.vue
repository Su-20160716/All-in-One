<template>
  <div v-if="modelValue" class="fixed inset-0 z-[96] flex justify-end">
    <div class="absolute inset-0 bg-ink-900/40" @click="requestClose"></div>
    <aside class="relative z-10 flex h-full w-full max-w-[900px] flex-col bg-white shadow-pop">
      <!-- 头部 -->
      <div class="flex flex-wrap items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="tag">设计器</span>
            <span v-if="form" class="tag" :class="formStatusClass(form.status)">{{ formStatusLabel(form.status) }}</span>
            <span v-if="form" class="tag">#{{ form.id }}</span>
            <span v-if="dirty" class="tag bg-amber-50 text-amber-600">未保存</span>
          </div>
          <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">
            {{ form?.name || '表单设计' }}
          </h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            分区 {{ schema.sections.length }} · 字段 {{ schema.fields.length }} ·
            逻辑 {{ (schema.logic || []).length }} · 当前版本 v{{ summary.current_version ?? 0 }}
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <button class="btn-outline" type="button" :disabled="loading || validating" @click="validateSchema">
            {{ validating ? '校验中…' : '校验结构' }}
          </button>
          <button class="btn-outline" type="button" :disabled="loading || saving" @click="saveDraft">
            {{ saving ? '保存中…' : '保存结构' }}
          </button>
          <button class="btn-primary" type="button" :disabled="loading || publishing" @click="publish">
            {{ publishing ? '发布中…' : '发布新版本' }}
          </button>
          <button class="shrink-0 px-1 text-ink-400 hover:text-ink-600" aria-label="关闭设计器" type="button" @click="requestClose">
            ✕
          </button>
        </div>
      </div>

      <!-- 主体 -->
      <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        <div v-if="loading" class="py-16 text-center text-[12px] text-ink-400">设计结构加载中…</div>
        <div v-else-if="error" class="rounded-control bg-rose-50 px-3 py-3 text-[12px] text-rose-600">
          <div class="flex flex-wrap items-center gap-3">
            <span class="min-w-0 flex-1">{{ error }}</span>
            <button class="shrink-0 font-medium" type="button" @click="load">重试</button>
          </div>
        </div>
        <template v-else>
          <div v-if="saveError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            {{ saveError }}
          </div>
          <div v-if="notice" class="rounded-control bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
            {{ notice }}
          </div>
          <div v-if="issues.length" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span>结构体检发现 {{ issues.length }} 个问题</span>
              <button class="text-[11px] font-medium" type="button" @click="issues = []">忽略</button>
            </div>
            <ul class="mt-1 list-disc space-y-0.5 pl-4 text-[11px]">
              <li v-for="(issue, index) in issues.slice(0, 8)" :key="`issue-${index}`">{{ issue.message || issue.code }}</li>
            </ul>
            <p v-if="issues.length > 8" class="mt-1 text-[11px]">还有 {{ issues.length - 8 }} 条，请先修正后再发布</p>
          </div>

          <!-- 分区管理 -->
          <section class="rounded-control border border-ink-100">
            <header class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
              <div>
                <h4 class="text-[13px] font-semibold text-ink-800">分区</h4>
                <p class="text-[11px] text-ink-400">分区用于组织字段，key 必须唯一且不能为空</p>
              </div>
              <button class="btn-outline !py-1" type="button" @click="addSection">新增分区</button>
            </header>
            <div v-if="!schema.sections.length" class="px-3 py-6 text-center text-[12px] text-ink-400">
              还没有分区，可直接新增，字段也可以不归属任何分区
            </div>
            <div v-else class="divide-y divide-ink-50">
              <div
                v-for="(section, index) in schema.sections"
                :key="`section-${index}`"
                class="flex flex-wrap items-end gap-2 px-3 py-2"
                :class="isActiveSection(section.key) ? 'bg-brand-50/40' : ''"
              >
                <span class="pb-2 text-[11px] text-ink-400">{{ index + 1 }}</span>
                <label class="flex min-w-[160px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
                  标题
                  <input v-model="section.title" class="input !py-1" maxlength="200" placeholder="分区标题" />
                </label>
                <label class="flex w-40 flex-col gap-1 text-[11px] text-ink-500">
                  key
                  <input v-model="section.key" class="input !py-1 font-mono !text-[11px]" maxlength="64" placeholder="section_key" />
                </label>
                <label class="flex items-center gap-1.5 pb-1.5 text-[11px] text-ink-600">
                  <input v-model="section.collapsible" type="checkbox" class="h-3.5 w-3.5" />
                  可折叠
                </label>
                <button
                  class="btn-ghost !px-1.5 !py-1 !text-[11px]"
                  type="button"
                  :class="isActiveSection(section.key) ? '!text-brand-700' : ''"
                  @click="setActiveSection(section.key)"
                >
                  {{ isActiveSection(section.key) ? '当前分区' : '设为当前' }}
                </button>
                <button class="btn-ghost !px-1.5 !py-1 !text-[11px]" type="button" :disabled="index === 0" @click="moveSection(index, -1)">
                  上移
                </button>
                <button
                  class="btn-ghost !px-1.5 !py-1 !text-[11px]"
                  type="button"
                  :disabled="index === schema.sections.length - 1"
                  @click="moveSection(index, 1)"
                >
                  下移
                </button>
                <button
                  class="btn-ghost !px-1.5 !py-1 !text-[11px] !text-rose-600"
                  type="button"
                  @click="askDeleteSection(section)"
                >
                  删除
                </button>
              </div>
            </div>
          </section>

          <!-- 字段设计 -->
          <section class="rounded-control border border-ink-100">
            <header class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
              <div>
                <h4 class="text-[13px] font-semibold text-ink-800">字段</h4>
                <p class="text-[11px] text-ink-400">新增字段会加入当前分区，字段 key 发布后不建议修改</p>
              </div>
              <div class="flex flex-wrap items-center gap-1.5">
                <select v-model="newFieldType" class="input !w-auto !py-1 !text-[11px]" aria-label="新字段类型">
                  <option v-for="type in FIELD_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option>
                </select>
                <button class="btn-primary !py-1" type="button" @click="addField">添加字段</button>
              </div>
            </header>

            <div class="flex flex-wrap gap-1 border-b border-ink-50 px-3 py-2">
              <button
                type="button"
                class="rounded-pill px-2.5 py-1 text-[11px]"
                :class="activeSection === ALL_KEY ? 'bg-ink-700 text-white' : 'bg-ink-50 text-ink-600 hover:bg-ink-100'"
                @click="setActiveSection(ALL_KEY)"
              >
                全部（{{ schema.fields.length }}）
              </button>
              <button
                v-for="section in schema.sections"
                :key="`chip-${section.key}`"
                type="button"
                class="rounded-pill px-2.5 py-1 text-[11px]"
                :class="activeSection === section.key ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-600 hover:bg-ink-100'"
                @click="setActiveSection(section.key)"
              >
                {{ section.title || section.key }}（{{ countInSection(section.key) }}）
              </button>
              <button
                type="button"
                class="rounded-pill px-2.5 py-1 text-[11px]"
                :class="activeSection === NONE_KEY ? 'bg-ink-700 text-white' : 'bg-ink-50 text-ink-600 hover:bg-ink-100'"
                @click="setActiveSection(NONE_KEY)"
              >
                未分区（{{ countInSection('') }}）
              </button>
            </div>

            <div v-if="!visibleFields.length" class="px-3 py-8 text-center text-[12px] text-ink-400">
              当前视图下还没有字段，点击右上角「添加字段」
            </div>
            <div v-else class="divide-y divide-ink-50">
              <div v-for="field in visibleFields" :key="field._uid" class="px-3 py-2">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="tag" :class="field.required ? 'bg-rose-50 text-rose-600' : ''">
                    {{ field.required ? '必填' : '选填' }}
                  </span>
                  <span class="min-w-0 flex-1 truncate text-[13px] text-ink-800">{{ field.label || '未命名字段' }}</span>
                  <span class="tag">{{ field.key }}</span>
                  <span class="tag">{{ fieldTypeLabel(field.type) }}</span>
                  <span v-if="field.condition?._enabled" class="tag bg-amber-50 text-amber-600">条件显示</span>
                  <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="toggleField(field)">
                    {{ expandedKey === field._uid ? '收起' : '编辑' }}
                  </button>
                  <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="moveField(field, -1)">
                    上移
                  </button>
                  <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="moveField(field, 1)">
                    下移
                  </button>
                  <button
                    class="btn-ghost !px-1.5 !py-0.5 !text-[11px] !text-rose-600"
                    type="button"
                    @click="askDeleteField(field)"
                  >
                    删除
                  </button>
                </div>

                <div v-if="expandedKey === field._uid" class="mt-2 rounded-control bg-ink-50/70 p-3">
                  <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      字段标题
                      <input v-model="field.label" class="input !py-1" maxlength="200" />
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      字段 key
                      <input v-model="field.key" class="input !py-1 font-mono !text-[11px]" maxlength="64" />
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      类型
                      <select v-model="field.type" class="input !py-1" @change="onTypeChange(field)">
                        <option v-for="type in FIELD_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option>
                      </select>
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      所在分区
                      <select v-model="field.section" class="input !py-1">
                        <option value="">未分区</option>
                        <option v-for="section in schema.sections" :key="`field-section-${section.key}`" :value="section.key">
                          {{ section.title || section.key }}
                        </option>
                      </select>
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      宽度
                      <select v-model="field.width" class="input !py-1">
                        <option value="full">整行</option>
                        <option value="half">半行</option>
                        <option value="third">三分之一</option>
                      </select>
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      占位提示
                      <input v-model="field.placeholder" class="input !py-1" maxlength="200" />
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500 sm:col-span-2">
                      帮助说明
                      <input v-model="field.help_text" class="input !py-1" maxlength="500" />
                    </label>
                    <label class="flex flex-col gap-1 text-[11px] text-ink-500">
                      默认值
                      <select v-if="field.type === 'boolean'" v-model="field.default_input" class="input !py-1">
                        <option value="">无默认值</option>
                        <option value="true">是</option>
                        <option value="false">否</option>
                      </select>
                      <input
                        v-else
                        v-model="field.default_input"
                        class="input !py-1"
                        :type="field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'"
                        :placeholder="field.type === 'multiselect' ? '多个值用英文逗号分隔' : '可留空'"
                      />
                    </label>
                    <label class="flex items-center gap-1.5 pt-4 text-[11px] text-ink-600">
                      <input v-model="field.required" type="checkbox" class="h-3.5 w-3.5" />
                      必填字段
                    </label>
                  </div>

                  <!-- 选项编辑 -->
                  <div
                    v-if="field.type === 'select' || field.type === 'multiselect'"
                    class="mt-3 rounded-control border border-ink-100 bg-white p-2"
                  >
                    <div class="mb-1.5 flex items-center justify-between">
                      <span class="text-[12px] font-medium text-ink-700">选项</span>
                      <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="addOption(field)">
                        添加选项
                      </button>
                    </div>
                    <div v-if="!field.options.length" class="py-2 text-center text-[11px] text-amber-600">
                      选择题至少需要一个选项
                    </div>
                    <div v-else class="space-y-1.5">
                      <div
                        v-for="(option, optionIndex) in field.options"
                        :key="`option-${field.key}-${optionIndex}`"
                        class="flex flex-wrap items-center gap-1.5"
                      >
                        <input v-model="option.value" class="input !w-28 !py-0.5 !text-[11px]" placeholder="值" />
                        <input v-model="option.label" class="input !w-36 !py-0.5 !text-[11px]" placeholder="标签" />
                        <input v-model.number="option.score" class="input !w-20 !py-0.5 !text-[11px]" type="number" placeholder="分值" />
                        <label class="flex items-center gap-1 text-[11px] text-ink-500">
                          <input v-model="option.disabled" type="checkbox" class="h-3 w-3" />
                          禁用
                        </label>
                        <button
                          class="btn-ghost !px-1.5 !py-0.5 !text-[11px] !text-rose-600"
                          type="button"
                          @click="removeOption(field, optionIndex)"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>

                  <!-- 条件显示 -->
                  <div class="mt-3 rounded-control border border-ink-100 bg-white p-2">
                    <label class="flex items-center gap-1.5 text-[12px] text-ink-600">
                      <input v-model="field.condition._enabled" type="checkbox" class="h-3.5 w-3.5" />
                      条件显示（满足条件时才展示该字段）
                    </label>
                    <div v-if="field.condition._enabled" class="mt-2 flex flex-wrap items-end gap-1.5">
                      <label class="flex min-w-[150px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
                        依赖字段
                        <select v-model="field.condition.field" class="input !py-1 !text-[11px]">
                          <option value="">请选择字段</option>
                          <option
                            v-for="other in schema.fields.filter((f) => f.key !== field.key)"
                            :key="`cond-${other.key}`"
                            :value="other.key"
                          >
                            {{ other.label }}（{{ other.key }}）
                          </option>
                        </select>
                      </label>
                      <label class="flex w-32 flex-col gap-1 text-[11px] text-ink-500">
                        运算符
                        <select v-model="field.condition.op" class="input !py-1 !text-[11px]">
                          <option v-for="op in CONDITION_OPS" :key="op.value" :value="op.value">{{ op.label }}</option>
                        </select>
                      </label>
                      <label class="flex min-w-[120px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
                        比较值
                        <input
                          v-model="field.condition.value"
                          class="input !py-1 !text-[11px]"
                          :placeholder="field.condition.op === 'in' ? '多个值用英文逗号分隔' : '条件值'"
                        />
                      </label>
                    </div>
                    <p class="mt-1 text-[11px] text-ink-400">
                      支持 eq / neq / gt / gte / lt / lte / in / not_in / contains / empty 等运算符。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 版本 -->
          <section class="rounded-control border border-ink-100">
            <header class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
              <div>
                <h4 class="text-[13px] font-semibold text-ink-800">版本</h4>
                <p class="text-[11px] text-ink-400">发布即生成快照；回滚会写回设计态并发布一个内容相同的新版本</p>
              </div>
              <div class="flex flex-wrap items-center gap-1.5">
                <input v-model="versionNote" class="input !w-52 !py-1 !text-[11px]" maxlength="500" placeholder="版本说明" />
                <button class="btn-outline !py-1" type="button" :disabled="versionsLoading" @click="loadVersions">
                  {{ versionsLoading ? '加载中…' : '刷新版本' }}
                </button>
              </div>
            </header>
            <div v-if="versionsError" class="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px] text-rose-600">
              <span class="min-w-0 flex-1">{{ versionsError }}</span>
              <button class="font-medium" type="button" @click="loadVersions">重试</button>
            </div>
            <div v-else-if="versionsLoading && !versions.length" class="px-3 py-6 text-center text-[12px] text-ink-400">
              加载中…
            </div>
            <div v-else-if="!versions.length" class="px-3 py-6 text-center text-[12px] text-ink-400">
              还没有发布版本
            </div>
            <template v-else>
              <div class="flex flex-wrap items-end gap-2 border-b border-ink-50 px-3 py-2">
                <label class="flex w-40 flex-col gap-1 text-[11px] text-ink-500">
                  对比基准
                  <select v-model="compareLeft" class="input !py-1 !text-[11px]">
                    <option v-for="version in versions" :key="`left-${version.id}`" :value="version.id">v{{ version.version_no }}</option>
                  </select>
                </label>
                <label class="flex w-40 flex-col gap-1 text-[11px] text-ink-500">
                  对比目标
                  <select v-model="compareRight" class="input !py-1 !text-[11px]">
                    <option v-for="version in versions" :key="`right-${version.id}`" :value="version.id">v{{ version.version_no }}</option>
                  </select>
                </label>
                <button class="btn-outline !py-1" type="button" :disabled="comparing || compareLeft === compareRight" @click="compareVersions">
                  {{ comparing ? '对比中…' : '版本对比' }}
                </button>
                <span v-if="compareError" class="text-[11px] text-rose-600">{{ compareError }}</span>
              </div>
              <div class="divide-y divide-ink-50">
                <div v-for="version in versions" :key="`version-${version.id}`" class="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px]">
                  <span class="tag bg-brand-50 text-brand-700">v{{ version.version_no }}</span>
                  <span v-if="version.is_current" class="tag bg-emerald-50 text-emerald-600">当前版本</span>
                  <span class="min-w-0 flex-1 truncate text-ink-700">{{ version.note || '未填写版本说明' }}</span>
                  <span class="text-[11px] text-ink-400">{{ version.field_count }} 字段 / {{ version.section_count }} 分区</span>
                  <span class="text-[11px] text-ink-400">{{ formatDate(version.published_at, true) }}</span>
                  <button
                    class="btn-ghost !px-1.5 !py-0.5 !text-[11px]"
                    type="button"
                    @click="setCompare(version.id)"
                  >
                    设为基准
                  </button>
                  <button
                    v-if="!version.is_current"
                    class="btn-ghost !px-1.5 !py-0.5 !text-[11px] !text-rose-600"
                    type="button"
                    @click="askRollback(version)"
                  >
                    回滚到此版本
                  </button>
                </div>
              </div>
            </template>
          </section>

          <p class="text-[11px] text-ink-400">
            保存结构走批量 schema 接口（先删后建），发布前会执行结构体检；设计态与历史提交按版本快照隔离。
          </p>
        </template>
      </div>
    </aside>
  </div>

  <!-- 确认 -->
  <Modal v-model="confirmOpen" :title="confirmState.title" width="420px">
    <div class="space-y-3">
      <p class="text-[12px] leading-relaxed text-ink-600">{{ confirmState.message }}</p>
      <div class="flex justify-end gap-2">
        <button class="btn-ghost" type="button" @click="confirmOpen = false">取消</button>
        <button class="btn-primary" type="button" :disabled="confirmBusy" @click="runConfirm">
          {{ confirmBusy ? '处理中…' : confirmState.confirmText }}
        </button>
      </div>
    </div>
  </Modal>

  <!-- 版本对比 -->
  <Modal v-model="compareOpen" title="版本对比" width="760px">
    <div v-if="comparison" class="space-y-3">
      <div class="flex flex-wrap items-center gap-2 text-[12px]">
        <span class="tag">v{{ comparison.from?.version_no }}</span>
        <span class="text-ink-400">→</span>
        <span class="tag bg-brand-50 text-brand-700">v{{ comparison.to?.version_no }}</span>
        <span class="tag">新增字段 {{ comparison.summary?.fields_added ?? 0 }}</span>
        <span class="tag">删除字段 {{ comparison.summary?.fields_removed ?? 0 }}</span>
        <span class="tag">修改字段 {{ comparison.summary?.fields_modified ?? 0 }}</span>
        <span class="tag">新增分区 {{ comparison.summary?.sections_added ?? 0 }}</span>
      </div>

      <div>
        <p class="mb-1 text-[12px] font-medium text-ink-700">字段变化</p>
        <div v-if="!comparison.fields?.added?.length && !comparison.fields?.removed?.length && !comparison.fields?.modified?.length" class="rounded-control bg-ink-50 px-3 py-3 text-[12px] text-ink-400">
          字段结构无变化
        </div>
        <div v-else class="space-y-2">
          <div v-if="comparison.fields?.added?.length" class="flex flex-wrap items-center gap-1">
            <span class="text-[11px] text-emerald-600">新增</span>
            <span v-for="field in comparison.fields.added" :key="`add-${field.key}`" class="tag bg-emerald-50 text-emerald-600">
              {{ field.label }}（{{ field.key }}）
            </span>
          </div>
          <div v-if="comparison.fields?.removed?.length" class="flex flex-wrap items-center gap-1">
            <span class="text-[11px] text-rose-600">删除</span>
            <span v-for="field in comparison.fields.removed" :key="`remove-${field.key}`" class="tag bg-rose-50 text-rose-600">
              {{ field.label }}（{{ field.key }}）
            </span>
          </div>
          <div v-if="comparison.fields?.modified?.length" class="overflow-x-auto rounded-control border border-ink-100">
            <table class="w-full min-w-[520px] text-left">
              <thead class="border-b border-ink-100 bg-ink-50/60">
                <tr>
                  <th class="th">字段</th>
                  <th class="th">变化项</th>
                  <th class="th">原值 → 新值</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="field in comparison.fields.modified" :key="`mod-${field.key}`">
                  <td class="td">{{ field.label }}（{{ field.key }}）</td>
                  <td class="td">{{ Object.keys(field.changes || {}).join('、') }}</td>
                  <td class="td">
                    <div v-for="(change, name) in field.changes" :key="`change-${field.key}-${name}`" class="text-[11px] text-ink-600">
                      {{ name }}：{{ textOf(change.from) }} → {{ textOf(change.to) }}
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-2 text-[12px] sm:grid-cols-2">
        <div class="rounded-control bg-ink-50 px-3 py-2">
          <p class="text-[11px] text-ink-400">分区变化</p>
          <p class="text-ink-700">
            新增 {{ comparison.sections?.added?.length || 0 }} / 删除 {{ comparison.sections?.removed?.length || 0 }} /
            修改 {{ comparison.sections?.modified?.length || 0 }}
          </p>
        </div>
        <div class="rounded-control bg-ink-50 px-3 py-2">
          <p class="text-[11px] text-ink-400">逻辑规则</p>
          <p class="text-ink-700">
            由 {{ comparison.logic?.from ?? 0 }} 条变为 {{ comparison.logic?.to ?? 0 }} 条
          </p>
        </div>
      </div>
      <div class="flex justify-end">
        <button class="btn-ghost" type="button" @click="compareOpen = false">关闭</button>
      </div>
    </div>
  </Modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useAppStore } from '../../stores/app'
import { formstudioApi } from '../../api/platform'
import { formatDate } from '../../composables/useDomainResource'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  form: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved', 'published'])

const app = useAppStore()

const FIELD_TYPES = [
  { value: 'text', label: '单行文本' },
  { value: 'textarea', label: '多行文本' },
  { value: 'number', label: '数字' },
  { value: 'select', label: '单选' },
  { value: 'multiselect', label: '多选' },
  { value: 'date', label: '日期' },
  { value: 'boolean', label: '开关' },
  { value: 'file', label: '文件' },
  { value: 'rating', label: '评分' },
  { value: 'email', label: '邮箱' },
  { value: 'phone', label: '手机号' },
  { value: 'url', label: '链接' },
]
const CONDITION_OPS = [
  { value: 'eq', label: '等于' },
  { value: 'neq', label: '不等于' },
  { value: 'gt', label: '大于' },
  { value: 'gte', label: '大于等于' },
  { value: 'lt', label: '小于' },
  { value: 'lte', label: '小于等于' },
  { value: 'in', label: '属于' },
  { value: 'not_in', label: '不属于' },
  { value: 'contains', label: '包含' },
  { value: 'not_contains', label: '不包含' },
  { value: 'empty', label: '为空' },
  { value: 'not_empty', label: '不为空' },
  { value: 'between', label: '介于' },
  { value: 'starts_with', label: '开头是' },
  { value: 'ends_with', label: '结尾是' },
]
const FORM_STATUS_LABELS = {
  draft: '草稿',
  published: '已发布',
  closed: '已关闭',
  archived: '已归档',
}

const ALL_KEY = '__all__'
const NONE_KEY = '__none__'

const loading = ref(false)
const error = ref('')
const saving = ref(false)
const publishing = ref(false)
const validating = ref(false)
const saveError = ref('')
const notice = ref('')
const dirty = ref(false)
const issues = ref([])
const summary = ref({})
const activeSection = ref(ALL_KEY)
const expandedKey = ref('')
const newFieldType = ref('text')
const versionNote = ref('')
const versions = ref([])
const versionsLoading = ref(false)
const versionsError = ref('')
const compareLeft = ref('')
const compareRight = ref('')
const comparing = ref(false)
const compareError = ref('')
const comparison = ref(null)
const compareOpen = ref(false)

const schema = ref({ form: {}, sections: [], fields: [], logic: [], settings: {} })

let applying = false
watch(
  schema,
  () => {
    if (applying) return
    dirty.value = true
  },
  { deep: true }
)

function formStatusLabel(value) {
  return FORM_STATUS_LABELS[value] || value || '—'
}
function formStatusClass(value) {
  if (value === 'published') return 'bg-emerald-50 text-emerald-600'
  if (value === 'draft') return 'bg-amber-50 text-amber-600'
  if (value === 'closed') return 'bg-ink-100 text-ink-600'
  return 'bg-ink-100 text-ink-600'
}
function fieldTypeLabel(value) {
  const hit = FIELD_TYPES.find((type) => type.value === value)
  return hit ? hit.label : value || '—'
}
function textOf(value) {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch (e) {
      return String(value)
    }
  }
  return String(value)
}
function isActiveSection(key) {
  return activeSection.value === key
}
function setActiveSection(key) {
  activeSection.value = key
}
function countInSection(key) {
  return schema.value.fields.filter((field) => (field.section || '') === (key || '')).length
}

function defaultToInput(field) {
  const value = field.default
  if (value === null || value === undefined || value === '') return ''
  if (Array.isArray(value)) return value.join(',')
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch (e) {
      return ''
    }
  }
  return String(value)
}
let fieldUid = 0
function nextFieldUid() {
  fieldUid += 1
  return `f${fieldUid}`
}
function ensureField(raw) {
  const field = raw && typeof raw === 'object' ? raw : {}
  field._uid = field._uid || nextFieldUid()
  field.key = String(field.key || '')
  field.label = String(field.label || '')
  field.type = String(field.type || field.field_type || 'text')
  field.required = Boolean(field.required)
  field.placeholder = String(field.placeholder || '')
  field.help_text = String(field.help_text || '')
  field.width = field.width || 'full'
  field.section = String(field.section || '')
  field.validation = field.validation && typeof field.validation === 'object' ? field.validation : {}
  field.validations = Array.isArray(field.validations) ? field.validations : []
  field.options = Array.isArray(field.options)
    ? field.options
        .filter((option) => option && typeof option === 'object')
        .map((option) => ({
          value: String(option.value ?? ''),
          label: String(option.label ?? option.value ?? ''),
          score: Number(option.score) || 0,
          disabled: Boolean(option.disabled),
        }))
    : []
  const condition = field.condition && typeof field.condition === 'object' ? field.condition : {}
  const hadCondition = Boolean(condition.field)
  field.condition = {
    _enabled: hadCondition,
    field: String(condition.field || ''),
    op: String(condition.op || 'eq'),
    value: condition.value === null || condition.value === undefined
      ? ''
      : Array.isArray(condition.value)
        ? condition.value.join(',')
        : String(condition.value),
  }
  field.default_input = defaultToInput(field)
  return field
}
function ensureSection(raw) {
  const section = raw && typeof raw === 'object' ? raw : {}
  section.key = String(section.key || '')
  section.title = String(section.title || section.key || '')
  section.description = String(section.description || '')
  section.collapsible = Boolean(section.collapsible)
  return section
}

function applySchema(data) {
  const raw = data?.schema || {}
  const next = {
    form: raw.form && typeof raw.form === 'object' ? raw.form : {},
    sections: Array.isArray(raw.sections) ? raw.sections.map(ensureSection) : [],
    fields: Array.isArray(raw.fields) ? raw.fields.map(ensureField) : [],
    logic: Array.isArray(raw.logic) ? raw.logic : [],
    settings: raw.settings && typeof raw.settings === 'object' ? raw.settings : {},
  }
  applying = true
  schema.value = next
  summary.value = data?.summary || {}
  issues.value = Array.isArray(data?.issues) ? data.issues : []
  if (!next.sections.some((section) => section.key === activeSection.value)) {
    activeSection.value = ALL_KEY
  }
  expandedKey.value = ''
  dirty.value = false
  Promise.resolve().then(() => {
    applying = false
    dirty.value = false
  })
}

const visibleFields = computed(() => {
  if (activeSection.value === ALL_KEY) return schema.value.fields
  if (activeSection.value === NONE_KEY) {
    return schema.value.fields.filter((field) => !field.section)
  }
  return schema.value.fields.filter((field) => field.section === activeSection.value)
})

async function load() {
  if (!props.form?.id) return
  loading.value = true
  error.value = ''
  saveError.value = ''
  notice.value = ''
  try {
    const data = await formstudioApi.get(`forms/${props.form.id}/schema/`)
    applySchema(data)
    await loadVersions()
  } catch (e) {
    error.value = e?.message || '设计结构加载失败'
  } finally {
    loading.value = false
  }
}

async function loadVersions() {
  if (!props.form?.id) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const data = await formstudioApi.list(`forms/${props.form.id}/versions/`, { page: 1, page_size: 50 })
    versions.value = data.items || []
    if (!compareLeft.value && versions.value.length) compareLeft.value = versions.value[0].id
    if (!compareRight.value && versions.value.length > 1) compareRight.value = versions.value[1].id
    if (versions.value.length === 1 && !compareRight.value) compareRight.value = versions.value[0].id
  } catch (e) {
    versions.value = []
    versionsError.value = e?.message || '版本加载失败'
  } finally {
    versionsLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// 结构编辑
// ---------------------------------------------------------------------------
function uniqueKey(prefix, existing) {
  let index = existing.length + 1
  let key = `${prefix}_${index}`
  while (existing.includes(key)) {
    index += 1
    key = `${prefix}_${index}`
  }
  return key
}
function addSection() {
  const keys = schema.value.sections.map((section) => section.key)
  const key = uniqueKey('section', keys)
  schema.value.sections.push({
    key,
    title: `分区 ${schema.value.sections.length + 1}`,
    description: '',
    collapsible: false,
  })
  activeSection.value = key
}
function moveSection(index, delta) {
  const target = index + delta
  if (target < 0 || target >= schema.value.sections.length) return
  const rows = schema.value.sections
  const current = rows[index]
  rows[index] = rows[target]
  rows[target] = current
}

function targetSectionForNewField() {
  if (activeSection.value === ALL_KEY || activeSection.value === NONE_KEY) {
    return schema.value.sections[0]?.key || ''
  }
  return activeSection.value
}

function addField() {
  const keys = schema.value.fields.map((field) => field.key)
  const key = uniqueKey('field', keys)
  const type = newFieldType.value
  const field = ensureField({
    key,
    label: `新字段 ${schema.value.fields.length + 1}`,
    type,
    required: false,
    section: targetSectionForNewField(),
    width: 'full',
    options: [],
  })
  if (type === 'select' || type === 'multiselect') {
    field.options = [
      { value: 'option_1', label: '选项 1', score: 0, disabled: false },
      { value: 'option_2', label: '选项 2', score: 0, disabled: false },
    ]
  }
  schema.value.fields.push(field)
  expandedKey.value = field._uid
}
function onTypeChange(field) {
  if ((field.type === 'select' || field.type === 'multiselect') && !field.options.length) {
    field.options = [
      { value: 'option_1', label: '选项 1', score: 0, disabled: false },
      { value: 'option_2', label: '选项 2', score: 0, disabled: false },
    ]
  }
}
function addOption(field) {
  const index = field.options.length + 1
  let value = `option_${index}`
  const used = field.options.map((option) => option.value)
  while (used.includes(value)) {
    value = `${value}_x`
  }
  field.options.push({ value, label: `选项 ${index}`, score: 0, disabled: false })
}
function removeOption(field, index) {
  field.options.splice(index, 1)
}
function toggleField(field) {
  expandedKey.value = expandedKey.value === field._uid ? '' : field._uid
}
function moveField(field, delta) {
  const group = schema.value.fields.filter((row) => (row.section || '') === (field.section || ''))
  const position = group.indexOf(field)
  const neighbor = group[position + delta]
  if (!neighbor) return
  const rows = schema.value.fields
  const from = rows.indexOf(field)
  const to = rows.indexOf(neighbor)
  if (from < 0 || to < 0) return
  rows[from] = neighbor
  rows[to] = field
}

// ---------------------------------------------------------------------------
// 确认
// ---------------------------------------------------------------------------
const confirmOpen = ref(false)
const confirmBusy = ref(false)
const confirmState = reactive({ title: '', message: '', confirmText: '确定', run: null })

function askDeleteSection(section) {
  confirmState.title = '删除分区'
  confirmState.message = `分区「${section.title || section.key}」下的字段不会被删除，而是变为未分区。确认删除？`
  confirmState.confirmText = '删除分区'
  confirmState.run = () => {
    const index = schema.value.sections.indexOf(section)
    if (index >= 0) schema.value.sections.splice(index, 1)
    for (const field of schema.value.fields) {
      if (field.section === section.key) field.section = ''
    }
    if (activeSection.value === section.key) activeSection.value = ALL_KEY
  }
  confirmOpen.value = true
}
function askDeleteField(field) {
  confirmState.title = '删除字段'
  confirmState.message = `确认删除字段「${field.label || field.key}」？保存结构后该字段会从设计态移除。`
  confirmState.confirmText = '删除字段'
  confirmState.run = () => {
    const index = schema.value.fields.indexOf(field)
    if (index >= 0) schema.value.fields.splice(index, 1)
    if (expandedKey.value === field._uid) expandedKey.value = ''
  }
  confirmOpen.value = true
}
function askRollback(version) {
  confirmState.title = '回滚版本'
  confirmState.message = `将设计态回滚到 v${version.version_no}，并发布一个内容相同的新版本。历史版本与提交不会被删除。确认继续？`
  confirmState.confirmText = '确认回滚'
  confirmState.run = () => rollback(version)
  confirmOpen.value = true
}
function requestClose() {
  if (!dirty.value) {
    closeDrawer()
    return
  }
  confirmState.title = '放弃未保存的修改'
  confirmState.message = '设计结构有未保存的修改，关闭后这些修改会丢失。确认关闭？'
  confirmState.confirmText = '放弃并关闭'
  confirmState.run = () => {
    dirty.value = false
    closeDrawer()
  }
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
function closeDrawer() {
  emit('update:modelValue', false)
}

// ---------------------------------------------------------------------------
// 保存 / 校验 / 发布
// ---------------------------------------------------------------------------
function conditionValue(field) {
  const condition = field.condition || {}
  const raw = condition.value
  const text = raw === null || raw === undefined ? '' : String(raw).trim()
  const referenced = schema.value.fields.find((row) => row.key === condition.field)
  const refType = referenced?.type
  if (!text) return ''
  if (condition.op === 'in' || condition.op === 'not_in' || condition.op === 'between') {
    const parts = text.split(',').map((part) => part.trim()).filter(Boolean)
    return parts.map((part) => (refType === 'number' || refType === 'rating' ? Number(part) : part))
  }
  if (refType === 'number' || refType === 'rating') {
    const num = Number(text)
    return Number.isFinite(num) ? num : text
  }
  if (refType === 'boolean') return text === 'true'
  return text
}
function parseDefault(field) {
  const input = field.default_input
  if (input === '' || input === null || input === undefined) return null
  if (field.type === 'boolean') return String(input) === 'true'
  if (field.type === 'number') {
    const num = Number(input)
    return Number.isFinite(num) ? num : null
  }
  if (field.type === 'multiselect') {
    return String(input)
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
  }
  return input
}
function buildPayload() {
  const sections = schema.value.sections.map((section, index) => ({
    key: String(section.key || '').trim(),
    title: String(section.title || section.key || '').trim(),
    description: section.description || '',
    order: index,
    collapsible: Boolean(section.collapsible),
    condition: section.condition && typeof section.condition === 'object' ? section.condition : {},
  }))
  const fields = schema.value.fields.map((field, index) => ({
    key: String(field.key || '').trim(),
    label: String(field.label || '').trim(),
    type: field.type,
    required: Boolean(field.required),
    default: parseDefault(field),
    placeholder: field.placeholder || '',
    help_text: field.help_text || '',
    order: index,
    width: field.width || 'full',
    section: field.section || '',
    options: (field.options || []).map((option) => ({
      value: String(option.value || '').trim(),
      label: String(option.label || option.value || '').trim(),
      score: Number(option.score) || 0,
      disabled: Boolean(option.disabled),
    })),
    validation: field.validation && typeof field.validation === 'object' ? field.validation : {},
    condition: field.condition?._enabled && field.condition?.field
      ? { field: field.condition.field, op: field.condition.op || 'eq', value: conditionValue(field) }
      : {},
    validations: Array.isArray(field.validations) ? field.validations : [],
  }))
  return {
    form: schema.value.form || {},
    settings: schema.value.settings || {},
    sections,
    fields,
    logic: Array.isArray(schema.value.logic) ? schema.value.logic : [],
  }
}
function validatePayload(payload) {
  const problems = []
  const sectionKeys = new Set()
  for (const section of payload.sections) {
    if (!section.key) problems.push('分区 key 不能为空')
    if (sectionKeys.has(section.key)) problems.push(`分区 key 重复：${section.key}`)
    sectionKeys.add(section.key)
  }
  const fieldKeys = new Set()
  for (const field of payload.fields) {
    if (!field.key) problems.push('字段 key 不能为空')
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(field.key)) {
      problems.push(`字段 key 不合法：${field.key}（字母开头，仅字母/数字/下划线）`)
    }
    if (fieldKeys.has(field.key)) problems.push(`字段 key 重复：${field.key}`)
    fieldKeys.add(field.key)
    if (!field.label) problems.push(`字段 ${field.key} 缺少标题`)
    if (field.section && !sectionKeys.has(field.section)) {
      problems.push(`字段 ${field.key} 引用了不存在的分区 ${field.section}`)
    }
    if (field.type === 'select' || field.type === 'multiselect') {
      if (!field.options.length) problems.push(`字段 ${field.key} 至少需要一个选项`)
      const values = new Set()
      for (const option of field.options) {
        if (!option.value) problems.push(`字段 ${field.key} 存在空选项值`)
        if (values.has(option.value)) problems.push(`字段 ${field.key} 选项值重复：${option.value}`)
        values.add(option.value)
      }
    }
  }
  return problems
}
async function persist(silent = false) {
  if (!props.form?.id) throw new Error('表单不存在')
  const payload = buildPayload()
  const problems = validatePayload(payload)
  if (problems.length) {
    saveError.value = problems[0]
    throw new Error(problems[0])
  }
  saveError.value = ''
  const data = await formstudioApi.action(`forms/${props.form.id}/schema/`, { schema: payload })
  summary.value = data?.summary || summary.value
  dirty.value = false
  if (!silent) {
    notice.value = '结构已保存'
    app.toastMsg('结构已保存', 'success')
  }
  emit('saved')
  return data
}
async function saveDraft() {
  saving.value = true
  notice.value = ''
  try {
    await persist()
  } catch (e) {
    saveError.value = e?.message || '保存失败'
    app.toastMsg(saveError.value, 'error')
  } finally {
    saving.value = false
  }
}
async function validateSchema() {
  if (!props.form?.id) return
  validating.value = true
  saveError.value = ''
  notice.value = ''
  try {
    const payload = buildPayload()
    const data = await formstudioApi.action(`forms/${props.form.id}/schema/validate/`, { schema: payload })
    issues.value = Array.isArray(data?.issues) ? data.issues : []
    if (issues.value.length) {
      app.toastMsg(`结构体检发现 ${issues.value.length} 个问题`, 'error')
    } else {
      notice.value = '结构体检通过，可以发布'
      app.toastMsg('结构体检通过', 'success')
    }
  } catch (e) {
    saveError.value = e?.message || '校验失败'
    app.toastMsg(saveError.value, 'error')
  } finally {
    validating.value = false
  }
}
async function publish() {
  if (!props.form?.id) return
  publishing.value = true
  notice.value = ''
  try {
    await persist(true)
    const data = await formstudioApi.action(`forms/${props.form.id}/publish/`, {
      note: versionNote.value.trim(),
    })
    const versionNo = data?.version?.version_no
    notice.value = versionNo ? `已发布 v${versionNo}` : '已发布新版本'
    app.toastMsg(notice.value, 'success')
    versionNote.value = ''
    await loadVersions()
    emit('published')
  } catch (e) {
    saveError.value = e?.message || '发布失败'
    app.toastMsg(saveError.value, 'error')
  } finally {
    publishing.value = false
  }
}

// ---------------------------------------------------------------------------
// 版本对比 / 回滚
// ---------------------------------------------------------------------------
function setCompare(id) {
  compareLeft.value = id
  if (String(compareRight.value) === String(id) && versions.value.length > 1) {
    const other = versions.value.find((version) => version.id !== id)
    if (other) compareRight.value = other.id
  }
}
async function compareVersions() {
  if (!props.form?.id) return
  if (!compareLeft.value || !compareRight.value) {
    compareError.value = '请选择两个版本'
    return
  }
  if (String(compareLeft.value) === String(compareRight.value)) {
    compareError.value = '请选择不同的版本'
    return
  }
  comparing.value = true
  compareError.value = ''
  try {
    comparison.value = await formstudioApi.action(`forms/${props.form.id}/versions/compare/`, {
      left_id: compareLeft.value,
      right_id: compareRight.value,
    })
    compareOpen.value = true
  } catch (e) {
    compareError.value = e?.message || '版本对比失败'
    app.toastMsg(compareError.value, 'error')
  } finally {
    comparing.value = false
  }
}
async function rollback(version) {
  if (!version?.id) return
  const data = await formstudioApi.action(`versions/${version.id}/rollback/`, {
    note: versionNote.value.trim() || `回滚至 v${version.version_no}`,
  })
  const versionNo = data?.version?.version_no
  app.toastMsg(versionNo ? `已回滚并发布 v${versionNo}` : '已回滚版本', 'success')
  await load()
  emit('published')
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) load()
  }
)
watch(
  () => props.form?.id,
  () => {
    if (props.modelValue) load()
  }
)
</script>