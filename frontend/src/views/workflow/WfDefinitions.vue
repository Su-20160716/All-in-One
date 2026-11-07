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
          placeholder="按编码、名称、分类或描述搜索"
          @keyup.enter="refreshList"
        />
      </label>
      <label class="w-32">
        <span class="mb-1 block text-[11px] text-ink-400">状态</span>
        <select v-model="status" class="input">
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
      <button class="btn-primary" @click="refreshList">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="refreshList">刷新</button>
      <span class="ml-auto flex items-center gap-2 text-[11px] text-ink-400">
        <span>共 {{ formatNumber(total) }} 个流程</span>
        <button
          v-if="selected.length"
          class="btn-ghost px-2 text-[12px]"
          :disabled="batchValidating"
          @click="validateSelected"
        >
          {{ batchValidating ? '校验中…' : `批量校验(${selected.length})` }}
        </button>
        <button class="btn-primary px-3 text-[12px]" @click="openCreate">新建流程</button>
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
        <button class="font-medium" @click="refreshList">重试</button>
      </div>
      <div v-else-if="!items.length" class="py-12 text-center text-[12px] text-ink-400">
        没有匹配的流程定义，调整筛选条件或新建一个流程
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1040px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th w-8"><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
              <th class="th">流程</th>
              <th class="th">分类</th>
              <th class="th">状态</th>
              <th class="th">版本</th>
              <th class="th">节点/连线</th>
              <th class="th">实例数</th>
              <th class="th">负责人</th>
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
              <td class="td" @click.stop>
                <input
                  type="checkbox"
                  :checked="selected.includes(row.id)"
                  @change="toggleOne(row.id)"
                />
              </td>
              <td class="td">
                <div class="max-w-[260px]">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate font-medium text-ink-800">{{ row.name }}</span>
                    <span v-if="row.is_editable" class="tag bg-amber-50 text-amber-600">可编辑</span>
                  </div>
                  <div class="truncate font-mono text-[11px] text-ink-400">{{ row.code }}</div>
                </div>
              </td>
              <td class="td text-[12px] text-ink-500">{{ row.category || '通用' }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ statusLabel(row.status) }}</span>
              </td>
              <td class="td text-[12px] text-ink-500">v{{ row.version_no }}</td>
              <td class="td text-[12px] text-ink-500">{{ row.node_count }} / {{ row.transition_count }}</td>
              <td class="td text-[12px] text-ink-500">{{ formatNumber(row.instance_count) }}</td>
              <td class="td text-[12px] text-ink-500">
                {{ row.owner?.name || row.owner?.username || '—' }}
              </td>
              <td class="td text-[12px] text-ink-500">{{ timeAgo(row.updated_at) }}</td>
              <td class="td whitespace-nowrap" @click.stop>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openDetail(row)">查看</button>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openEdit(row)">编辑</button>
                <button
                  class="btn-ghost px-1.5 text-[12px] text-brand-600"
                  :disabled="busyId === row.id"
                  @click="openPublish(row)"
                >发布</button>
                <button
                  v-if="row.status === 'published'"
                  class="btn-ghost px-1.5 text-[12px] text-amber-600"
                  :disabled="busyId === row.id"
                  @click="disableDefinition(row)"
                >停用</button>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openClone(row)">克隆</button>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openValidation(row)">校验</button>
                <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="openDelete(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页 -->
      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
        <span>第 {{ page }} / {{ pages }} 页 · 每页 {{ pageSize }} 条</span>
        <span class="flex items-center gap-1">
          <button class="btn-ghost px-2 text-[12px]" :disabled="page <= 1 || loading" @click="setPage(page - 1)">上一页</button>
          <button
            v-for="p in pageButtons"
            :key="p"
            class="rounded-control px-2 py-0.5 text-[12px]"
            :class="p === page ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-100'"
            @click="setPage(p)"
          >{{ p }}</button>
          <button class="btn-ghost px-2 text-[12px]" :disabled="page >= pages || loading" @click="setPage(page + 1)">下一页</button>
        </span>
      </div>
    </div>

    <!-- 详情抽屉：元信息 + 节点/连线 + 版本列表 -->
    <div v-if="drawerOpen" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDetail"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[620px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="tagClass(statusTone(detail?.status))">{{ statusLabel(detail?.status) }}</span>
              <span class="tag">v{{ detail?.version_no || 1 }}</span>
              <span v-if="detail?.validation" class="tag" :class="detail.validation.valid ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                {{ detail.validation.valid ? '结构校验通过' : `校验失败 ${detail.validation.errors?.length || 0} 项` }}
              </span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">{{ detail?.name || '流程详情' }}</h3>
            <p class="truncate font-mono text-[11px] text-ink-400">{{ detail?.code || '' }}</p>
          </div>
          <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" @click="closeDetail">✕</button>
        </div>

        <div class="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          <div v-if="detailLoading" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
          <div v-else-if="detailError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <div class="truncate">{{ detailError }}</div>
            <button class="mt-1 font-medium" @click="loadDetail(detailId)">重试</button>
          </div>
          <template v-else-if="detail">
            <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
              <div class="text-ink-400">分类</div>
              <div class="text-ink-700">{{ detail.category || '通用' }}</div>
              <div class="text-ink-400">负责人</div>
              <div class="text-ink-700">{{ detail.owner?.name || detail.owner?.username || '—' }}</div>
              <div class="text-ink-400">绑定表单</div>
              <div class="text-ink-700">{{ detail.form_key || '未绑定' }}</div>
              <div class="text-ink-400">发布时间</div>
              <div class="text-ink-700">{{ formatDate(detail.published_at, true) }}</div>
              <div class="text-ink-400">发起权限</div>
              <div class="text-ink-700">{{ permissionText(detail.start_permission) }}</div>
              <div class="text-ink-400">说明</div>
              <div class="text-ink-700">{{ detail.description || '—' }}</div>
            </div>

            <!-- 节点概览 -->
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">节点概览（{{ detail.nodes?.length || 0 }}）</span>
                <span class="text-[11px] text-ink-400">连线 {{ detail.transitions?.length || 0 }} 条</span>
              </div>
              <div v-if="!detail.nodes?.length" class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-400">
                还没有节点，请到设计器补充开始、任务与结束节点后再发布
              </div>
              <ul v-else class="space-y-1">
                <li
                  v-for="node in detail.nodes"
                  :key="node.key"
                  class="flex flex-wrap items-center gap-2 rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <span class="tag" :class="nodeTone(node.node_type)">{{ nodeTypeLabel(node.node_type) }}</span>
                  <span class="min-w-0 flex-1 truncate text-ink-800">{{ node.name }}</span>
                  <span class="font-mono text-[11px] text-ink-400">{{ node.key }}</span>
                  <span v-if="node.sla_minutes" class="text-[11px] text-amber-600">SLA {{ node.sla_minutes }} 分钟</span>
                </li>
              </ul>
            </div>

            <!-- 连线概览 -->
            <div>
              <div class="mb-1 text-[13px] font-medium text-ink-700">连线概览</div>
              <div v-if="!detail.transitions?.length" class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-400">
                暂无连线
              </div>
              <ul v-else class="space-y-1">
                <li
                  v-for="edge in detail.transitions"
                  :key="`${edge.from}-${edge.to}-${edge.priority}`"
                  class="rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="text-ink-800">{{ edge.from }}</span>
                    <span class="text-ink-300">→</span>
                    <span class="text-ink-800">{{ edge.to }}</span>
                    <span v-if="edge.is_default" class="tag bg-brand-50 text-brand-600">默认分支</span>
                    <span class="ml-auto text-[11px] text-ink-400">优先级 {{ edge.priority }}</span>
                  </div>
                  <div v-if="edge.condition" class="mt-0.5 font-mono text-[11px] text-ink-500">
                    条件：{{ edge.condition }}
                  </div>
                </li>
              </ul>
            </div>

            <!-- 版本列表 -->
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">版本列表</span>
                <button class="text-[11px] text-brand-600" :disabled="versionsLoading" @click="loadVersions(detail.id)">刷新</button>
              </div>
              <div v-if="versionsLoading" class="py-3 text-center text-[12px] text-ink-400">加载中…</div>
              <div v-else-if="versionsError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
                <div class="truncate">{{ versionsError }}</div>
                <button class="mt-1 font-medium" @click="loadVersions(detail.id)">重试</button>
              </div>
              <div v-else-if="!versions.length" class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-400">
                还没有发布版本，发布后会在这里生成快照记录
              </div>
              <ul v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="v in versions" :key="v.id" class="flex flex-wrap items-center gap-2 px-2 py-1.5 text-[12px]">
                  <span class="tag" :class="v.is_current ? 'bg-brand-50 text-brand-700' : 'bg-ink-100 text-ink-600'">v{{ v.version_no }}</span>
                  <span class="text-ink-700">{{ versionStatusLabel(v.status) }}</span>
                  <span class="text-[11px] text-ink-400">{{ v.node_count }} 节点 / {{ v.transition_count }} 连线</span>
                  <span class="ml-auto text-[11px] text-ink-400">{{ formatDate(v.published_at, true) }}</span>
                  <span v-if="v.change_note" class="w-full truncate text-[11px] text-ink-500">{{ v.change_note }}</span>
                </li>
              </ul>
            </div>

            <div v-if="detail.validation" class="rounded-control bg-ink-50 px-3 py-2 text-[12px]">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-ink-700">结构校验</span>
                <span class="tag" :class="detail.validation.valid ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                  {{ detail.validation.valid ? '通过' : '未通过' }}
                </span>
                <span class="text-[11px] text-ink-400">
                  节点 {{ detail.validation.stats?.node_count ?? 0 }} · 连线 {{ detail.validation.stats?.transition_count ?? 0 }}
                </span>
              </div>
              <ul v-if="detail.validation.errors?.length" class="mt-1 space-y-0.5 text-[11px] text-rose-600">
                <li v-for="(e, i) in detail.validation.errors.slice(0, 6)" :key="`e-${i}`">· {{ e.message }}</li>
              </ul>
              <ul v-if="detail.validation.warnings?.length" class="mt-1 space-y-0.5 text-[11px] text-amber-600">
                <li v-for="(w, i) in detail.validation.warnings.slice(0, 4)" :key="`w-${i}`">· {{ w.message }}</li>
              </ul>
            </div>
          </template>
        </div>

        <div class="flex flex-wrap items-center justify-end gap-2 border-t border-ink-100 px-4 py-2.5">
          <button class="btn-ghost text-[12px]" @click="closeDetail">关闭</button>
          <button class="btn-ghost text-[12px]" :disabled="!detail" @click="openValidation(detail)">校验</button>
          <button class="btn-ghost text-[12px]" :disabled="!detail" @click="openClone(detail)">克隆</button>
          <button class="btn-ghost text-[12px] text-amber-600" :disabled="!detail || detail.status !== 'published'" @click="disableDefinition(detail)">停用</button>
          <button class="btn-primary text-[12px]" :disabled="!detail" @click="openPublish(detail)">发布</button>
        </div>
      </aside>
    </div>

    <!-- 创建 / 编辑弹窗 -->
    <Modal :show="formOpen" :title="form.id ? '编辑流程定义' : '新建流程定义'" width="580px" @close="formOpen = false">
      <div class="space-y-3">
        <div v-if="formLoading" class="py-6 text-center text-[12px] text-ink-400">加载流程详情…</div>
        <template v-else>
          <div class="grid gap-3 sm:grid-cols-2">
            <label>
              <span class="mb-1 block text-[11px] text-ink-400">流程编码</span>
              <input v-model.trim="form.code" class="input font-mono" placeholder="如 leave_apply" />
              <span class="mt-0.5 block text-[11px] text-ink-400">字母、数字、下划线、点与中划线，发布后尽量不再修改</span>
            </label>
            <label>
              <span class="mb-1 block text-[11px] text-ink-400">流程名称</span>
              <input v-model.trim="form.name" class="input" placeholder="如 请假审批" />
            </label>
            <label>
              <span class="mb-1 block text-[11px] text-ink-400">分类</span>
              <input v-model.trim="form.category" class="input" placeholder="通用" />
            </label>
            <label>
              <span class="mb-1 block text-[11px] text-ink-400">发起权限</span>
              <select v-model="form.permMode" class="input">
                <option value="all">所有人可发起</option>
                <option value="roles">指定角色</option>
                <option value="users">指定用户</option>
                <option value="depts">指定部门</option>
              </select>
            </label>
          </div>
          <label v-if="form.permMode !== 'all'" class="block">
            <span class="mb-1 block text-[11px] text-ink-400">
              {{ form.permMode === 'roles' ? '角色编码（逗号分隔）' : '对象 ID（逗号分隔）' }}
            </span>
            <input
              v-model.trim="form.permValues"
              class="input"
              :placeholder="form.permMode === 'roles' ? '如 manager,hr' : '如 12,34'"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-[11px] text-ink-400">流程说明</span>
            <textarea v-model="form.description" class="input min-h-[72px]" placeholder="描述适用场景、审批要点等"></textarea>
          </label>
          <p class="rounded-control bg-ink-50 px-3 py-2 text-[11px] leading-relaxed text-ink-500">
            新建后为草稿状态；发布前需要先在流程中补齐开始节点与结束节点，结构校验通过才能生成版本。
          </p>
        </template>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="formOpen = false">取消</button>
          <button class="btn-primary" :disabled="saving || formLoading" @click="saveForm">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 发布弹窗 -->
    <Modal :show="publishOpen" title="发布流程版本" width="480px" @close="publishOpen = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">
          将为「{{ publishTarget?.name }}」生成一个不可变版本快照，校验不通过时会拒绝发布。
        </p>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">变更说明（可选）</span>
          <textarea v-model="publishNote" class="input min-h-[64px]" placeholder="本次发布包含哪些调整"></textarea>
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="publishOpen = false">取消</button>
          <button class="btn-primary" :disabled="busy" @click="publishDefinition">
            {{ busy ? '发布中…' : '确认发布' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 克隆弹窗 -->
    <Modal :show="cloneOpen" title="克隆流程定义" width="480px" @close="cloneOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">新流程编码</span>
          <input v-model.trim="cloneForm.code" class="input font-mono" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">新流程名称</span>
          <input v-model.trim="cloneForm.name" class="input" />
        </label>
        <p class="text-[11px] text-ink-400">克隆会复制节点与连线，新流程从草稿开始，不影响原流程的在途实例。</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="cloneOpen = false">取消</button>
          <button class="btn-primary" :disabled="busy" @click="cloneDefinition">
            {{ busy ? '克隆中…' : '确认克隆' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 删除确认 -->
    <Modal :show="deleteOpen" title="删除流程定义" width="440px" @close="deleteOpen = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">
          确认删除「{{ deleteTarget?.name }}」（{{ deleteTarget?.code }}）？存在运行中实例时后端会拒绝删除。
        </p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="deleteOpen = false">取消</button>
          <button class="btn-danger" :disabled="busy" @click="deleteDefinition">
            {{ busy ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 校验结果 -->
    <Modal :show="validationOpen" title="流程结构校验" width="560px" @close="validationOpen = false">
      <div class="space-y-3">
        <div v-if="validationLoading" class="py-6 text-center text-[12px] text-ink-400">校验中…</div>
        <template v-else>
          <div v-if="batchResults.length" class="space-y-1">
            <div
              v-for="r in batchResults"
              :key="r.id"
              class="flex flex-wrap items-center gap-2 rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
            >
              <span class="min-w-0 flex-1 truncate text-ink-700">{{ r.name }}</span>
              <span class="tag" :class="r.valid ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                {{ r.valid ? '通过' : '未通过' }}
              </span>
              <span class="text-[11px] text-ink-400">错误 {{ r.errorCount }} · 警告 {{ r.warningCount }}</span>
            </div>
          </div>
          <template v-else-if="validation">
            <div class="flex flex-wrap items-center gap-2 text-[12px]">
              <span class="font-medium text-ink-700">{{ validationTarget?.name }}</span>
              <span class="tag" :class="validation.valid ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                {{ validation.valid ? '结构校验通过' : '结构校验未通过' }}
              </span>
              <span class="text-[11px] text-ink-400">
                节点 {{ validation.stats?.node_count ?? 0 }} · 连线 {{ validation.stats?.transition_count ?? 0 }}
              </span>
            </div>
            <div v-if="!validation.errors?.length && !validation.warnings?.length" class="rounded-control bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
              没有发现结构问题，可以发布。
            </div>
            <ul v-if="validation.errors?.length" class="space-y-1">
              <li
                v-for="(e, i) in validation.errors"
                :key="`ve-${i}`"
                class="rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600"
              >
                {{ e.message }}<span v-if="e.node" class="ml-1 text-rose-400">[节点 {{ e.node }}]</span>
              </li>
            </ul>
            <ul v-if="validation.warnings?.length" class="space-y-1">
              <li
                v-for="(w, i) in validation.warnings"
                :key="`vw-${i}`"
                class="rounded-control bg-amber-50 px-2 py-1 text-[11px] text-amber-700"
              >
                {{ w.message }}<span v-if="w.node" class="ml-1 text-amber-500">[节点 {{ w.node }}]</span>
              </li>
            </ul>
          </template>
          <div v-else class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            {{ validationError || '校验结果为空，请稍后重试' }}
          </div>
        </template>
        <div class="flex justify-end">
          <button class="btn-primary" @click="validationOpen = false">关闭</button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import {
  formatDate,
  formatNumber,
  statusTone,
  timeAgo,
  useDomainResource,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  /** 父级刷新计数：变化时重新拉取列表 */
  refreshKey: { type: Number, default: 0 },
})

const app = useAppStore()
const api = apiFor('workflow')

const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'disabled', label: '已停用' },
  { value: 'archived', label: '已归档' },
]

const NODE_TYPE_LABELS = {
  start: '开始',
  task: '人工任务',
  decision: '条件分支',
  parallel_split: '并行拆分',
  parallel_join: '并行汇聚',
  end: '结束',
}

const {
  items,
  loading,
  error,
  q,
  status,
  page,
  pageSize,
  total,
  pages,
  setPage,
  setPageSize,
  refresh,
} = useDomainResource('workflow', 'definitions/', { auto: false, pageSize: 10 })

const selected = ref([])
const busy = ref(false)
const busyId = ref(0)

const drawerOpen = ref(false)
const detailId = ref(0)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const versions = ref([])
const versionsLoading = ref(false)
const versionsError = ref('')

const formOpen = ref(false)
const formLoading = ref(false)
const saving = ref(false)
const form = reactive({
  id: 0,
  code: '',
  name: '',
  category: '通用',
  description: '',
  permMode: 'all',
  permValues: '',
})

const publishOpen = ref(false)
const publishTarget = ref(null)
const publishNote = ref('')

const cloneOpen = ref(false)
const cloneForm = reactive({ id: 0, code: '', name: '' })

const deleteOpen = ref(false)
const deleteTarget = ref(null)

const validationOpen = ref(false)
const validationLoading = ref(false)
const validation = ref(null)
const validationError = ref('')
const validationTarget = ref(null)
const batchResults = ref([])
const batchValidating = ref(false)

const allChecked = computed(
  () => items.value.length > 0 && items.value.every((row) => selected.value.includes(row.id))
)

const pageButtons = computed(() => {
  const totalPages = pages.value
  const current = page.value
  const start = Math.max(1, Math.min(current - 2, totalPages - 4))
  const end = Math.min(totalPages, start + 4)
  const out = []
  for (let i = start; i <= end; i += 1) out.push(i)
  return out
})

function statusLabel(value) {
  return STATUS_OPTIONS.find((s) => s.value === value)?.label || value || '未知'
}

function versionStatusLabel(value) {
  return {
    published: '已发布',
    superseded: '已被取代',
    rolled_back: '回滚产生',
  }[value] || value || '未知'
}

function nodeTypeLabel(value) {
  return NODE_TYPE_LABELS[value] || value || '节点'
}

function nodeTone(value) {
  if (value === 'start') return 'bg-emerald-50 text-emerald-600'
  if (value === 'end') return 'bg-ink-100 text-ink-600'
  if (value === 'decision') return 'bg-amber-50 text-amber-600'
  if (value === 'parallel_split' || value === 'parallel_join') return 'bg-brand-50 text-brand-700'
  return 'bg-ink-50 text-ink-600'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function permissionText(permission) {
  if (!permission) return '未配置'
  if (permission.allow_all) return '所有人可发起'
  const parts = []
  if (permission.roles?.length) parts.push(`角色：${permission.roles.join('、')}`)
  if (permission.user_ids?.length) parts.push(`用户：${permission.user_ids.join('、')}`)
  if (permission.dept_ids?.length) parts.push(`部门：${permission.dept_ids.join('、')}`)
  return parts.length ? parts.join('；') : '所有人可发起'
}

function changePageSize(event) {
  setPageSize(Number(event.target.value) || 10)
  refreshList()
}

function toggleOne(id) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id]
}

function toggleAll() {
  selected.value = allChecked.value ? [] : items.value.map((row) => row.id)
}

async function refreshList() {
  selected.value = []
  await refresh()
}

let qTimer = null
watch(q, () => {
  if (qTimer) clearTimeout(qTimer)
  qTimer = setTimeout(() => {
    setPage(1)
    refreshList()
  }, 320)
})
watch(status, () => {
  setPage(1)
  refreshList()
})

// 翻页后清空跨页选择，避免批量校验作用到当前页之外的行
watch(page, () => {
  selected.value = []
})

watch(
  () => props.refreshKey,
  () => {
    refreshList()
  }
)

function openCreate() {
  Object.assign(form, {
    id: 0,
    code: '',
    name: '',
    category: '通用',
    description: '',
    permMode: 'all',
    permValues: '',
  })
  formLoading.value = false
  formOpen.value = true
}

async function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    code: row.code,
    name: row.name,
    category: row.category || '通用',
    description: row.description || '',
    permMode: 'all',
    permValues: '',
  })
  formOpen.value = true
  formLoading.value = true
  try {
    // 列表不带发起权限，编辑前拉一次详情，避免把权限覆盖成默认值
    const data = await api.get(`definitions/${row.id}/`)
    const perm = data.start_permission || {}
    Object.assign(form, {
      code: data.code,
      name: data.name,
      category: data.category || '通用',
      description: data.description || '',
      permMode: perm.allow_all ? 'all' : perm.roles?.length ? 'roles' : perm.user_ids?.length ? 'users' : 'depts',
      permValues: perm.roles?.length
        ? perm.roles.join(',')
        : perm.user_ids?.length
          ? perm.user_ids.join(',')
          : (perm.dept_ids || []).join(','),
    })
  } catch (e) {
    app.toastMsg(e?.message || '流程详情加载失败', 'error')
    formOpen.value = false
  } finally {
    formLoading.value = false
  }
}

function buildPermission() {
  if (form.permMode === 'all') {
    return { allow_all: true, roles: [], user_ids: [], dept_ids: [] }
  }
  const parts = String(form.permValues || '')
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (form.permMode === 'roles') {
    return { allow_all: false, roles: parts, user_ids: [], dept_ids: [] }
  }
  const ids = parts.map((s) => Number(s)).filter((n) => Number.isFinite(n) && n > 0)
  return form.permMode === 'users'
    ? { allow_all: false, roles: [], user_ids: ids, dept_ids: [] }
    : { allow_all: false, roles: [], user_ids: [], dept_ids: ids }
}

async function saveForm() {
  if (!form.code || !form.name) {
    app.toastMsg('流程编码与名称不能为空', 'error')
    return
  }
  saving.value = true
  try {
    const payload = {
      code: form.code,
      name: form.name,
      category: form.category || '通用',
      description: form.description,
      start_permission: buildPermission(),
    }
    if (form.id) {
      await api.post(`definitions/${form.id}/update/`, payload)
      app.toastMsg('流程定义已保存', 'success')
    } else {
      await api.post('definitions/create/', payload)
      app.toastMsg('流程定义已创建', 'success')
    }
    formOpen.value = false
    await refreshList()
    if (drawerOpen.value && detailId.value === form.id) await loadDetail(form.id)
  } catch (e) {
    app.toastMsg(e?.message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

function openPublish(row) {
  publishTarget.value = row
  publishNote.value = ''
  publishOpen.value = true
}

async function publishDefinition() {
  if (!publishTarget.value) return
  busy.value = true
  busyId.value = publishTarget.value.id
  try {
    await api.post(`definitions/${publishTarget.value.id}/publish/`, {
      note: publishNote.value,
    })
    app.toastMsg('流程已发布', 'success')
    publishOpen.value = false
    await refreshList()
    if (drawerOpen.value && detailId.value === publishTarget.value.id) {
      await loadDetail(detailId.value)
      await loadVersions(detailId.value)
    }
  } catch (e) {
    app.toastMsg(e?.message || '发布失败', 'error')
  } finally {
    busy.value = false
    busyId.value = 0
  }
}

async function disableDefinition(row) {
  if (!row) return
  busyId.value = row.id
  try {
    await api.post(`definitions/${row.id}/disable/`)
    app.toastMsg('流程已停用', 'success')
    await refreshList()
    if (drawerOpen.value && detailId.value === row.id) await loadDetail(row.id)
  } catch (e) {
    app.toastMsg(e?.message || '停用失败', 'error')
  } finally {
    busyId.value = 0
  }
}

function openClone(row) {
  Object.assign(cloneForm, {
    id: row.id,
    code: `${row.code}_copy`,
    name: `${row.name}（副本）`,
  })
  cloneOpen.value = true
}

async function cloneDefinition() {
  if (!cloneForm.id) return
  busy.value = true
  try {
    await api.post(`definitions/${cloneForm.id}/clone/`, {
      code: cloneForm.code,
      name: cloneForm.name,
    })
    app.toastMsg('流程已克隆', 'success')
    cloneOpen.value = false
    await refreshList()
  } catch (e) {
    app.toastMsg(e?.message || '克隆失败', 'error')
  } finally {
    busy.value = false
  }
}

function openDelete(row) {
  deleteTarget.value = row
  deleteOpen.value = true
}

async function deleteDefinition() {
  if (!deleteTarget.value) return
  busy.value = true
  try {
    // 后端删除是 POST 动作（无 DELETE 路由），这里显式用 post 避免 405
    await api.post(`definitions/${deleteTarget.value.id}/delete/`)
    app.toastMsg('流程已删除', 'success')
    deleteOpen.value = false
    selected.value = selected.value.filter((id) => id !== deleteTarget.value.id)
    if (detailId.value === deleteTarget.value.id) closeDetail()
    await refreshList()
  } catch (e) {
    app.toastMsg(e?.message || '删除失败', 'error')
  } finally {
    busy.value = false
  }
}

async function openValidation(row) {
  validationTarget.value = row
  validation.value = null
  validationError.value = ''
  batchResults.value = []
  validationOpen.value = true
  validationLoading.value = true
  try {
    validation.value = await api.get(`definitions/${row.id}/validate/`)
  } catch (e) {
    validationError.value = e?.message || '校验失败'
  } finally {
    validationLoading.value = false
  }
}

async function validateSelected() {
  if (!selected.value.length) return
  batchValidating.value = true
  validationOpen.value = true
  validationLoading.value = true
  validation.value = null
  validationError.value = ''
  try {
    const rows = items.value.filter((row) => selected.value.includes(row.id))
    const results = await Promise.allSettled(
      rows.map((row) => api.get(`definitions/${row.id}/validate/`))
    )
    batchResults.value = results.map((result, index) => {
      const row = rows[index]
      if (result.status === 'fulfilled') {
        const data = result.value || {}
        return {
          id: row.id,
          name: row.name,
          valid: data.valid === true,
          errorCount: data.errors?.length || 0,
          warningCount: data.warnings?.length || 0,
        }
      }
      return {
        id: row.id,
        name: row.name,
        valid: false,
        errorCount: 1,
        warningCount: 0,
      }
    })
  } finally {
    validationLoading.value = false
    batchValidating.value = false
  }
}

async function openDetail(row) {
  drawerOpen.value = true
  detailId.value = row.id
  await Promise.all([loadDetail(row.id), loadVersions(row.id)])
}

async function loadDetail(id) {
  if (!id) return
  detailId.value = id
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await api.get(`definitions/${id}/`)
  } catch (e) {
    detail.value = null
    detailError.value = e?.message || '流程详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

async function loadVersions(id) {
  if (!id) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const data = await api.list(`definitions/${id}/versions/`, { page: 1, page_size: 20 })
    versions.value = data.items || []
  } catch (e) {
    versions.value = []
    versionsError.value = e?.message || '版本列表加载失败'
  } finally {
    versionsLoading.value = false
  }
}

function closeDetail() {
  drawerOpen.value = false
  detail.value = null
  detailError.value = ''
  versions.value = []
  versionsError.value = ''
  detailId.value = 0
}

onMounted(() => {
  refresh()
})
</script>