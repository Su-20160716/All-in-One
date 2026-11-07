<template>
  <div class="space-y-4" :class="themeClass">
    <div class="card space-y-3 p-4">
      <div class="flex flex-wrap items-center gap-3">
        <div class="h-3 w-12 rounded-pill" :style="{ background: project?.color || '#0ea5e9' }"></div>
        <h2 class="text-[16px] font-bold text-ink-900">{{ project?.name }}</h2>
        <span v-if="project?.is_archived" class="tag bg-amber-50 text-amber-600">已归档</span>
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <button class="btn-ghost text-[12px]" @click="showShare=true; loadShare()">分享</button>
          <button class="btn-ghost text-[12px]" @click="openMembers">成员</button>
          <button class="btn-ghost text-[12px]" @click="showStats = true; loadStats(); loadBurndown(); loadWorkload()">统计</button>
          <button class="btn-ghost text-[12px]" @click="openReport">周报</button>
          <button class="btn-ghost text-[12px]" @click="openSettings">设置</button>
          <button class="btn-outline" @click="showNewCard = { board: null }">＋ 新卡片</button>
        </div>
      </div>
      <!-- 294/298：项目内页签（看板 / 动态 / 站会） -->
      <div class="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-2">
        <button v-for="t in viewTabs" :key="t.v" class="rounded-pill px-3 py-1 text-[12px]"
          :class="viewTab === t.v ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:text-brand-600'"
          @click="switchView(t.v)">{{ t.label }}</button>
        <template v-if="viewTab === 'board'">
          <input ref="searchInput" v-model="cardKw" class="input w-44" placeholder="筛选卡片…（/ 聚焦，支持 C-12）" @input="onKwInput" />
          <span v-if="searchTotal !== null" class="text-[11px] text-ink-500">命中 {{ searchTotal }} 张</span>
          <span v-if="searchLoading" class="text-[11px] text-ink-300">搜索中…</span>
          <select v-model="prioFilter" class="input w-28" @change="onFilterChange">
            <option value="">全部优先级</option><option value="urgent">紧急</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option>
          </select>
          <select v-model="assigneeFilter" class="input w-28" @change="onFilterChange">
            <option value="">全部负责人</option><option v-for="(n,i) in project?.member_names||[]" :key="n" :value="project.member_ids[i]">{{ n }}</option>
          </select>
          <select v-model="dueFilter" class="input w-28" @change="onFilterChange">
            <option value="">全部到期</option><option value="overdue">已逾期</option><option value="today">今天</option><option value="week">本周</option><option value="nodate">无日期</option>
          </select>
          <label class="flex items-center gap-1 text-[11px] text-ink-500">
            <input v-model="hideEmpty" type="checkbox" @change="saveCollapsed" />隐藏空列
          </label>
          <button class="btn-ghost text-[12px]" @click="exportCsv">导出 CSV</button>
          <button class="btn-ghost text-[12px]" :class="compact?'text-brand-600':''" @click="compact=!compact; saveTheme()">{{ compact?'⊟ 紧凑':'⊞ 完整' }}</button>
          <button class="btn-ghost text-[12px]" @click="cycleTheme">🎨 {{ themeName }}</button>
          <span class="ml-auto text-[11px] text-ink-400">Ctrl/⌘ 点击多选 · n 新建 · / 搜索</span>
        </template>
      </div>
    </div>

    <!-- 294：项目动态（分页 + 操作人/动作筛选） -->
    <div v-if="viewTab === 'activities'" class="card space-y-3 p-4">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-semibold text-ink-800">项目动态</span>
        <select v-model="actActor" class="input w-32" @change="loadActivities(1)">
          <option value="">全部成员</option>
          <option v-for="(n, i) in project?.member_names || []" :key="n" :value="project.member_ids[i]">{{ n }}</option>
        </select>
        <input v-model="actAction" class="input w-44" placeholder="动作关键词，如 完成" @input="onActActionInput" />
        <span class="text-[11px] text-ink-400">共 {{ actTotal }} 条</span>
        <button class="btn-ghost ml-auto text-[12px]" @click="loadActivities(1)">刷新</button>
      </div>
      <div class="max-h-[60vh] space-y-2 overflow-y-auto" @scroll="onActivityScroll">
        <div v-for="a in activities" :key="a.id" class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          <span class="font-medium text-ink-800">{{ a.user_name }}</span> {{ a.action }}
          <span v-if="a.target" class="text-ink-500">{{ a.target }}</span>
          <span class="ml-1 text-[10px] text-ink-300">{{ formatTime(a.created_at) }}</span>
        </div>
        <div v-if="!activities.length && !actLoading" class="grid h-24 place-items-center text-[12px] text-ink-400">暂无动态</div>
        <div v-if="actLoading" class="py-2 text-center text-[11px] text-ink-300">加载中…</div>
        <button v-else-if="actHasMore" class="btn-ghost w-full text-[12px]" @click="loadActivities(actPage + 1)">加载更多</button>
      </div>
    </div>

    <!-- 298：站会（按成员昨日完成 / 今日计划 / 阻塞） -->
    <div v-else-if="viewTab === 'standup'" class="card space-y-3 p-4">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-semibold text-ink-800">站会 · {{ standup.date || '-' }}</span>
        <span class="text-[11px] text-ink-400">
          昨日完成 {{ standup.summary?.done ?? 0 }} · 进行中 {{ standup.summary?.doing ?? 0 }} · 阻塞 {{ standup.summary?.blocked ?? 0 }}
        </span>
        <button class="btn-outline ml-auto text-[12px]" @click="copyStandup">一键复制作站会文本</button>
      </div>
      <div v-if="standupLoading" class="grid h-24 place-items-center text-[12px] text-ink-400">加载中…</div>
      <div v-else class="grid gap-3 md:grid-cols-2">
        <div v-for="m in standup.per_member || []" :key="m.user_id" class="rounded-control border border-ink-100 p-3">
          <div class="text-[13px] font-semibold text-ink-800">{{ m.display_name }}</div>
          <div class="mt-1.5 text-[11px] font-medium text-ink-500">昨日完成</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="c in m.done_yesterday" :key="'d' + c.id" class="rounded-pill bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">{{ c.code }} {{ c.title }}</span>
            <span v-if="!m.done_yesterday.length" class="text-[11px] text-ink-300">无</span>
          </div>
          <div class="mt-1.5 text-[11px] font-medium text-ink-500">今日计划</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="c in m.today_plan" :key="'t' + c.id" class="rounded-pill bg-brand-50 px-1.5 py-0.5 text-[10px] text-brand-700">{{ c.code }} {{ c.title }}</span>
            <span v-if="!m.today_plan.length" class="text-[11px] text-ink-300">无</span>
          </div>
          <div class="mt-1.5 text-[11px] font-medium text-ink-500">阻塞</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="c in m.blocked" :key="'b' + c.id" class="rounded-pill bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600">{{ c.code }} {{ c.title }}（{{ c.reason }}）</span>
            <span v-if="!m.blocked.length" class="text-[11px] text-ink-300">无</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 看板 -->
    <template v-else>
      <!-- #173 首屏骨架：接口慢时不再整屏空白 -->
      <div v-if="loading" class="flex items-start gap-3 overflow-x-auto pb-2">
        <div v-for="i in 3" :key="i" class="w-72 shrink-0 rounded-card bg-ink-100/70 p-2.5">
          <Skeleton :rows="3" />
        </div>
      </div>
      <div v-else class="flex items-start gap-3 overflow-x-auto pb-2">
        <div v-for="b in visibleBoards" :key="b.id"
          class="shrink-0 rounded-card bg-ink-100/70 p-2.5"
          :class="isCollapsed(b.id) ? 'w-12' : 'w-72'"
          @dragover.prevent @drop="onDrop($event, b.id)">
          <!-- 293：折叠列只保留竖排标题与计数 -->
          <div v-if="isCollapsed(b.id)" class="flex flex-col items-center gap-2 py-1">
            <button class="btn-ghost px-1 text-[12px]" title="展开列" @click="toggleCollapse(b.id)">⇥</button>
            <span class="text-[12px] font-semibold text-ink-600 [writing-mode:vertical-rl]">{{ b.name }}</span>
            <span class="text-[11px] text-ink-400">{{ matchCards(b).length }}</span>
            <span v-if="wipInfo(b).limit" class="rounded-pill px-1 py-0.5 text-[10px]"
              :class="wipInfo(b).over ? 'bg-rose-100 font-semibold text-rose-600' : 'bg-white text-ink-500'">{{ wipInfo(b).active }}/{{ wipInfo(b).limit }}</span>
          </div>
          <template v-else>
            <div class="mb-2 flex items-center justify-between px-1">
              <span class="text-[13px] font-semibold text-ink-700">
                {{ b.name }} <span class="text-[11px] font-normal text-ink-400">{{ matchCards(b).length }}</span>
                <!-- 283：列头 active/limit，超限标红 -->
                <span v-if="wipInfo(b).limit" class="ml-1 rounded-pill px-1.5 py-0.5 text-[10px]"
                  :class="wipInfo(b).over ? 'bg-rose-100 font-semibold text-rose-600' : 'bg-white text-ink-500'"
                  :title="wipInfo(b).over ? `超出 WIP 上限：${wipInfo(b).active}/${wipInfo(b).limit}` : '在办/上限'">
                  {{ wipInfo(b).active }}/{{ wipInfo(b).limit }}
                </span>
              </span>
              <div class="flex gap-1">
                <button class="btn-ghost px-1.5 text-[12px]" title="折叠列" @click="toggleCollapse(b.id)">⇤</button>
                <button class="btn-ghost px-1.5 text-[12px]" @click="renameBoard(b)">✎</button>
                <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="removeBoard(b)">✕</button>
              </div>
            </div>
            <div class="space-y-2">
              <div v-for="c in matchCards(b)" :key="c.id" :data-card-id="c.id"
                class="card group relative cursor-grab p-3 active:cursor-grabbing"
                :class="[cardTone(c), selectedIds.includes(c.id) ? 'ring-2 ring-brand-400' : '', highlightCardId === c.id ? 'ring-2 ring-amber-400' : '']"
                draggable="true" @dragstart="onDragStart($event, c)" @click="onCardClick($event, c)">
                <div class="flex items-start justify-between gap-2">
                  <!-- 292：服务端返回的 highlight.title 已转义，可直接渲染 -->
                  <span class="text-[13px] font-medium leading-snug" v-html="cardTitleHtml(c)"></span>
                  <span class="shrink-0 text-[12px]">{{ prioIcon(c.priority) }}</span>
                </div>
                <div v-if="!compact" class="mt-2 flex flex-wrap items-center gap-1">
                  <span v-for="l in c.labels || []" :key="labelName(l)" class="rounded-pill px-1.5 py-0.5 text-[10px]" :style="labelStyle(l)">{{ labelName(l) }}</span>
                </div>
                <div v-if="!compact && c.subtask_total" class="mt-2">
                  <div class="h-1.5 w-full overflow-hidden rounded-pill bg-ink-100"><div class="h-full rounded-pill bg-emerald-500" :style="{ width: (c.progress||0)+'%' }"></div></div>
                </div>
                <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
                  <span v-if="c.due_date" :class="dueTone(c)">{{ dueIcon(c) }} {{ c.due_date }}</span>
                  <!-- 301：剩 N 天 / 逾期 N 天 胶囊，hover 精确到期日 -->
                  <span v-if="c.due_date" class="rounded-pill px-1.5 py-0.5 text-[10px]" :class="countdownTone(c)" :title="`到期日：${c.due_date}`">{{ countdownText(c) }}</span>
                  <!-- 289：spent/estimate 双数值，超估标红 -->
                  <span v-if="c.estimated_minutes" class="rounded-pill px-1 py-0.5 text-[10px]"
                    :class="c.estimate_over ? 'bg-rose-50 font-medium text-rose-600' : 'text-ink-500'"
                    :title="`已花费 ${fmtH(c.spent_minutes)} / 预估 ${fmtH(c.estimated_minutes)}`">{{ fmtH(c.spent_minutes) }}/{{ fmtH(c.estimated_minutes) }}</span>
                  <span v-if="!compact && c.subtask_total">☑ {{ c.subtask_done }}/{{ c.subtask_total }}</span>
                  <span v-if="!compact && c.comment_count">💬 {{ c.comment_count }}</span>
                  <span v-if="c.assignee_names.length" class="ml-auto">{{ c.assignee_names.map((n) => n.slice(0, 1)).join('') }}</span>
                </div>
                <button class="absolute right-1 top-1 hidden rounded bg-white/90 px-1 text-[10px] shadow group-hover:block" title="复制卡片" @click.stop="quickCopy(c)">⧉</button>
                <!-- #172 触屏也能改列：卡片上的「移动到列」选择器 -->
                <button class="absolute right-6 top-1 rounded bg-white/90 px-1 text-[10px] shadow md:opacity-0 md:group-hover:opacity-100" title="移动到列" @click.stop="toggleMovePicker(c.id)">⇄</button>
                <!-- 288/295/300：卡片菜单 -->
                <button class="absolute right-11 top-1 rounded bg-white/90 px-1 text-[10px] shadow md:opacity-0 md:group-hover:opacity-100" title="更多操作" @click.stop="toggleCardMenu(c)">⋯</button>
                <div v-if="cardMenuFor === c.id" class="mt-2 rounded-control border border-brand-200 bg-white p-1.5" @click.stop @dragstart.stop.prevent>
                  <button class="block w-full rounded px-1.5 py-1 text-left text-[11px] text-ink-600 hover:bg-ink-50" @click="quickCopy(c)">⧉ 复制卡片</button>
                  <button class="block w-full rounded px-1.5 py-1 text-left text-[11px] text-ink-600 hover:bg-ink-50" @click="saveAsTemplate(c)">💾 存为模板</button>
                  <button class="block w-full rounded px-1.5 py-1 text-left text-[11px] text-ink-600 hover:bg-ink-50" @click="openApplyTemplate(c)">📋 套用模板</button>
                  <button class="block w-full rounded px-1.5 py-1 text-left text-[11px] text-ink-600 hover:bg-ink-50" @click="resolveCard(c)">✓ 标记解决</button>
                  <button class="block w-full rounded px-1.5 py-1 text-left text-[11px] text-ink-600 hover:bg-ink-50" @click="toggleWatch(c)">{{ watchMap[c.id] ? '★ 取消关注' : '☆ 关注' }}</button>
                  <button class="block w-full rounded px-1.5 py-1 text-left text-[11px] text-ink-600 hover:bg-ink-50" @click="archiveCard(c)">🗄 归档卡片</button>
                </div>
                <div v-if="movePickerFor === c.id" class="mt-2 rounded-control border border-brand-200 bg-white p-1.5" @click.stop @dragstart.stop.prevent>
                  <div class="mb-1 text-[10px] text-ink-400">移动到列</div>
                  <select class="input py-1 text-[11px]" :value="''" @change="moveCardTo(c, $event.target.value)">
                    <option value="">选择目标列…</option>
                    <option v-for="tb in boards" :key="tb.id" :value="tb.id" :disabled="Number(tb.id) === Number(c.board)">{{ tb.name }}</option>
                  </select>
                </div>
              </div>
            </div>
            <button class="mt-2 w-full rounded-control border border-dashed border-ink-200 py-1.5 text-[12px] text-ink-400 hover:border-brand-300 hover:text-brand-600" @click="showNewCard = { board: b.id }">＋ 添加卡片</button>
          </template>
        </div>
        <div class="w-56 shrink-0">
          <button class="w-full rounded-card border border-dashed border-ink-200 py-2.5 text-[12px] text-ink-400 hover:border-brand-300 hover:text-brand-600" @click="addBoard">＋ 新建列</button>
        </div>
      </div>

      <!-- 291：多选浮动工具条（Ctrl/⌘ 点击卡片多选） -->
      <div v-if="selectedIds.length" class="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-card bg-white px-3 py-2 shadow-pop ring-1 ring-ink-100">
        <div class="flex flex-wrap items-center gap-2 text-[12px]">
          <span class="font-semibold text-brand-600">已选 {{ selectedIds.length }} 张</span>
          <select class="input w-28 py-1 text-[12px]" :value="''" @change="batchStatus($event.target.value)">
            <option value="">改状态…</option>
            <option value="todo">待办</option><option value="doing">进行中</option><option value="done">已完成</option>
          </select>
          <select class="input w-28 py-1 text-[12px]" :value="''" @change="batchAssign($event.target.value)">
            <option value="">指派给…</option>
            <option v-for="(n, i) in project?.member_names || []" :key="n" :value="project.member_ids[i]">{{ n }}</option>
          </select>
          <select class="input w-28 py-1 text-[12px]" :value="''" @change="batchMoveTo($event.target.value)">
            <option value="">移动到列…</option>
            <option v-for="tb in boards" :key="tb.id" :value="tb.id">{{ tb.name }}</option>
          </select>
          <button class="btn-outline py-1 text-[12px]" @click="batchArchive">归档</button>
          <button class="btn-ghost py-1 text-[12px]" @click="clearSelection">取消选择</button>
        </div>
      </div>
    </template>

    <!-- 新建卡片 -->
    <Modal :show="!!showNewCard" title="新建任务卡片" @close="showNewCard = null">
      <div class="space-y-3">
        <select v-if="!showNewCard?.board" v-model="cardForm.board" class="input">
          <option :value="null" disabled>选择列</option>
          <option v-for="b in boards" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>
        <input v-model="cardForm.title" class="input" placeholder="任务标题" />
        <textarea v-model="cardForm.description" class="input h-20 resize-none" placeholder="描述（选填）"></textarea>
        <div class="flex gap-3">
          <select v-model="cardForm.priority" class="input w-1/2">
            <option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="urgent">紧急</option>
          </select>
          <input v-model="cardForm.due_date" type="date" class="input w-1/2" />
        </div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="showNewCard = null">取消</button><button class="btn-primary" @click="createCard">创建</button></div>
      </div>
    </Modal>

    <!-- 卡片详情 -->
    <Modal :show="!!activeCard" :title="activeCard?.title" width="640px" @close="activeCard = null">
      <div v-if="activeCard" class="space-y-4">
        <!-- 290：详情 / 时间线页签 -->
        <div class="flex flex-wrap items-center gap-2 border-b border-ink-100 pb-2">
          <button v-for="t in detailTabs" :key="t.v" class="rounded-pill px-3 py-1 text-[12px]"
            :class="detailTab === t.v ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-500'"
            @click="switchDetailTab(t.v)">{{ t.label }}</button>
          <span class="ml-auto text-[11px] text-ink-400">{{ activeCard.code }}<span v-if="activeCard.resolved_at" class="ml-1 text-emerald-600">· 已解决</span></span>
          <button class="btn-ghost text-[11px]" @click="toggleWatch(activeCard)">{{ watchMap[activeCard.id] ? '★ 取消关注' : '☆ 关注' }}</button>
        </div>
        <template v-if="detailTab === 'detail'">
        <div class="flex flex-wrap gap-2">
          <select v-model="activeCard.priority" class="input w-32" @change="updateCard({ priority: activeCard.priority })">
            <option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="urgent">紧急</option>
          </select>
          <select v-model="activeCard.status" class="input w-32" @change="updateCard({ status: activeCard.status })">
            <option value="todo">待办</option><option value="doing">进行中</option><option value="done">已完成</option>
          </select>
          <input v-model="activeCard.due_date" type="date" class="input w-40" @change="updateCard({ due_date: activeCard.due_date })" />
          <div class="flex items-center gap-1"><span class="text-[12px] text-ink-500">故事点</span><input v-model.number="activeCard.story_points" type="number" min="0" class="input w-20" @change="updateCard({ story_points: activeCard.story_points })" /></div>
        </div>
        <textarea v-model="activeCard.description" class="input h-20 resize-none" placeholder="任务描述" @change="updateCard({ description: activeCard.description })"></textarea>

        <!-- 负责人 -->
        <div>
          <div class="mb-1 text-[12px] font-medium text-ink-600">负责人</div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="(name, i) in project?.member_names || []" :key="i" class="rounded-pill px-2 py-0.5 text-[11px]" :class="activeCard.assignee_ids.includes(project.member_ids[i]) ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-500'" @click="toggleAssignee(project.member_ids[i])">{{ name }}</button>
          </div>
        </div>

        <!-- 标签 -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">标签</div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span v-for="l in activeCard.labels || []" :key="labelName(l)" class="rounded-pill px-2 py-0.5 text-[11px]" :style="labelStyle(l)">{{ labelName(l) }} <button @click="removeLabel(labelName(l))">×</button></span>
            <input v-model="labelInput" class="input w-24 py-1 text-[12px]" placeholder="+标签" @keyup.enter="addLabel" />
          </div>
        </div>

        <!-- 子任务 -->
        <div>
          <div class="mb-1.5 flex items-center justify-between">
            <span class="text-[12px] font-medium text-ink-600">子任务 {{ activeCard.subtask_done }}/{{ activeCard.subtask_total }}（{{ activeCard.progress }}%）</span>
          </div>
          <div class="h-1.5 w-full overflow-hidden rounded-pill bg-ink-100"><div class="h-full rounded-pill bg-emerald-500" :style="{ width: (activeCard.progress||0)+'%' }"></div></div>
          <div class="mt-1.5 space-y-1">
            <div v-for="s in subtasks" :key="s.id" class="group flex items-center gap-2 text-[13px]">
              <input type="checkbox" :checked="s.is_done" @change="toggleSubtask(s)" />
              <span :class="s.is_done ? 'text-ink-300 line-through' : 'text-ink-700'">{{ s.title }}</span>
              <button class="ml-auto text-[11px] text-rose-400 opacity-0 group-hover:opacity-100" @click="delSubtask(s)">删除</button>
            </div>
          </div>
          <div class="mt-1.5 flex gap-2">
            <input v-model="subInput" class="input py-1 text-[12px]" placeholder="新增子任务，回车" @keyup.enter="addSubtask" />
          </div>
        </div>

        <!-- 285/288：验收清单 DoD（模板套用会回填，未全部勾选结单需二次确认） -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">验收清单 {{ dod.done }}/{{ dod.total }}</div>
          <div class="space-y-1">
            <div v-for="d in dod.list" :key="d.id" class="group flex items-center gap-2 text-[13px]">
              <input type="checkbox" :checked="d.is_done" @change="toggleDod(d)" />
              <span :class="d.is_done ? 'text-ink-300 line-through' : 'text-ink-700'">{{ d.content }}</span>
              <button class="ml-auto text-[11px] text-rose-400 opacity-0 group-hover:opacity-100" @click="delDodItem(d)">删除</button>
            </div>
          </div>
          <div class="mt-1.5 flex gap-2">
            <input v-model="dodInput" class="input py-1 text-[12px]" placeholder="新增验收项，回车" @keyup.enter="addDodItem" />
          </div>
        </div>

        <!-- 工时 -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">工时记录（累计 {{ fmtH(activeCard.spent_minutes) }}）</div>
          <!-- 289：预估 / 已用 / 剩余估时 -->
          <div class="mb-1.5 flex flex-wrap items-center gap-2 text-[11px]">
            <span class="text-ink-500">预估</span>
            <input v-model.number="estimateHours" type="number" min="0" step="0.5" class="input w-16 py-0.5 text-[11px]" @change="saveEstimate" />
            <span class="text-ink-400">小时</span>
            <span class="text-ink-500">已用 {{ fmtH(activeCard.spent_minutes) }}</span>
            <span :class="activeCard.estimate_over ? 'font-medium text-rose-500' : 'text-emerald-600'">剩余 {{ fmtH(activeCard.remaining_minutes) }}</span>
            <span v-if="activeCard.estimate_over" class="rounded-pill bg-rose-50 px-1.5 py-0.5 text-rose-600">超出 {{ fmtH(activeCard.estimate_diff) }}</span>
          </div>
          <div class="space-y-1">
            <div v-for="w in worklogs" :key="w.id" class="flex items-center justify-between text-[12px] text-ink-600">
              <span>{{ w.user_name }} · {{ (w.minutes / 60).toFixed(1) }}h · {{ w.note || '-' }}</span>
              <button class="text-rose-400" @click="delWorklog(w)">×</button>
            </div>
          </div>
          <div class="mt-1.5 flex gap-2">
            <input v-model.number="wlMinutes" type="number" min="1" class="input w-24 py-1 text-[12px]" placeholder="分钟" />
            <input v-model="wlNote" class="input flex-1 py-1 text-[12px]" placeholder="工作说明" @keyup.enter="addWorklog" />
            <button class="btn-outline py-1 text-[12px]" @click="addWorklog">记录</button>
          </div>
        </div>

        <!-- 评论 -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">评论 ({{ comments.length }})</div>
          <div class="max-h-40 space-y-2 overflow-y-auto">
            <div v-for="cm in comments" :key="cm.id" class="group rounded-control bg-ink-50 px-3 py-2">
              <div class="flex items-center text-[11px] text-ink-400">
                <span>{{ cm.author_name }} · {{ formatTime(cm.created_at) }}</span>
                <span class="ml-auto opacity-0 group-hover:opacity-100">
                  <button class="mr-2 text-brand-600" @click="editComment(cm)">编辑</button>
                  <button v-if="cm.can_delete" class="text-rose-500" @click="delComment(cm)">删除</button>
                </span>
              </div>
              <div class="mt-0.5 text-[13px] text-ink-700">{{ cm.content }}</div>
            </div>
          </div>
          <div class="mt-2 flex gap-2">
            <input v-model="commentInput" class="input" placeholder="写评论…" @keyup.enter="addComment" />
            <button class="btn-primary" @click="addComment">发送</button>
          </div>
        </div>

        </template>
        <!-- 290：时间线（倒序，滚动或按钮继续加载） -->
        <div v-else class="max-h-[60vh] space-y-2 overflow-y-auto" @scroll="onTimelineScroll">
          <div v-for="(e, i) in timeline" :key="e.type + e.at + i" class="flex gap-2 rounded-control bg-ink-50 px-3 py-2">
            <span class="mt-0.5 text-[12px]">{{ timelineIcon(e.type) }}</span>
            <div class="min-w-0 flex-1">
              <div class="break-words text-[12px] text-ink-700">{{ e.text }}</div>
              <div class="text-[10px] text-ink-400">{{ e.user || '系统' }} · {{ formatTime(e.at) }}</div>
            </div>
          </div>
          <div v-if="!timeline.length && !timelineLoading" class="grid h-24 place-items-center text-[12px] text-ink-400">暂无时间线</div>
          <div v-if="timelineLoading" class="py-2 text-center text-[11px] text-ink-300">加载中…</div>
          <button v-else-if="timelineHasMore" class="btn-ghost w-full text-[12px]" @click="loadTimeline()">加载更多</button>
        </div>

        <div class="flex justify-between border-t border-ink-100 pt-3">
          <button class="btn-outline" @click="copyCard">⧉ 复制卡片</button>
          <button class="btn-danger" @click="deleteCard">删除任务</button>
        </div>
      </div>
    </Modal>

    <!-- 成员管理 -->
    <Modal :show="showMembers" title="成员管理" @close="showMembers = false">
      <div class="space-y-3">
        <div class="flex gap-2">
          <input v-model="memberQ" class="input flex-1" placeholder="搜索用户名/昵称" @input="searchMembers" />
        </div>
        <div v-if="candidates.length" class="max-h-40 space-y-1 overflow-y-auto rounded-control border border-ink-100 p-1">
          <div v-for="c in candidates" :key="c.id" class="flex items-center justify-between rounded-control px-2 py-1.5 text-[13px] hover:bg-ink-50">
            <span>{{ c.display_name }}</span>
            <button class="btn-outline px-2 py-0.5 text-[11px]" @click="addMembers([c.id])">＋ 添加</button>
          </div>
        </div>
        <div class="divide-y divide-ink-50">
          <!-- 304：每位成员显示在办 / 逾期数量 -->
          <div v-for="m in memberRows" :key="m.id" class="flex items-center justify-between py-2 text-[13px]">
            <span>
              {{ m.display_name }}
              <span class="ml-2 text-[11px]" :class="m.overdue_count ? 'text-rose-500' : 'text-ink-400'">
                在办 {{ m.open_count }} · 逾期 {{ m.overdue_count }}
              </span>
            </span>
            <button v-if="!m.is_owner" class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="removeMember(m.id)">移除</button>
          </div>
          <div v-if="!memberRows.length" class="py-3 text-center text-[12px] text-ink-400">暂无成员</div>
        </div>
      </div>
    </Modal>

    <!-- 统计 + 燃尽图 -->
    <Modal :show="showStats" title="项目统计" width="560px" @close="showStats = false">
      <div v-if="stats" class="space-y-4">
        <div class="grid grid-cols-3 gap-2 text-center">
          <div class="rounded-control bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.total }}</div><div class="text-[11px] text-ink-500">总任务</div></div>
          <div class="rounded-control bg-emerald-50 p-3"><div class="text-[20px] font-bold text-emerald-600">{{ stats.done }}</div><div class="text-[11px] text-ink-500">已完成</div></div>
          <div class="rounded-control bg-rose-50 p-3"><div class="text-[20px] font-bold text-rose-600">{{ stats.overdue }}</div><div class="text-[11px] text-ink-500">已逾期</div></div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">燃尽图（剩余工作量）</div>
          <svg v-if="burn.dates && burn.dates.length" :viewBox="`0 0 520 200`" class="w-full rounded-control bg-ink-50">
            <polyline :points="linePoints(burn.remaining)" fill="none" stroke="#0ea5e9" stroke-width="2" />
            <polyline :points="linePoints(burn.ideal)" fill="none" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="4 3" />
          </svg>
          <div v-else class="grid h-24 place-items-center rounded-control bg-ink-50 text-[12px] text-ink-400">暂无数据</div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">各列分布</div>
          <div v-for="b in stats.by_board" :key="b.board__name" class="mb-1 flex justify-between text-[12px]"><span>{{ b.board__name }}</span><span class="text-ink-400">{{ b.c }} 张</span></div>
        </div>
        <div>
          <div class="mb-1.5 flex items-center justify-between text-[12px] font-medium text-ink-600">
            <span>成员负载（未完成卡片）</span>
            <span class="text-[10px] font-normal text-ink-400">超过 8 张标红</span>
          </div>
          <div v-if="workload.length" class="space-y-1.5">
            <div v-for="w in workload" :key="w.user_id">
              <div class="flex items-center justify-between text-[11px]">
                <span :class="w.heavy ? 'font-medium text-rose-600' : 'text-ink-600'">{{ w.display_name }}</span>
                <span :class="w.heavy ? 'text-rose-500' : 'text-ink-400'">{{ w.open }} 在办 · {{ w.overdue }} 逾期</span>
              </div>
              <div class="h-1.5 w-full overflow-hidden rounded-pill bg-ink-100">
                <div class="h-full rounded-pill" :class="w.heavy ? 'bg-rose-400' : 'bg-brand-400'" :style="{ width: (w.load_percent || 0) + '%' }"></div>
              </div>
              <div v-if="w.heavy" class="mt-0.5 text-[10px] text-rose-500">负载过高，建议先转移或完成部分任务</div>
            </div>
          </div>
          <div v-else class="text-[12px] text-ink-400">暂无数据</div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">最近动态</div>
          <div class="max-h-40 space-y-1.5 overflow-y-auto">
            <div v-for="a in stats.activities" :key="a.id" class="text-[12px] text-ink-500"><span class="font-medium text-ink-700">{{ a.user_name }}</span> {{ a.action }} {{ a.target }} <span class="text-[10px] text-ink-300">{{ formatTime(a.created_at) }}</span></div>
          </div>
        </div>
      </div>
    </Modal>

    <!-- #166 页内输入对话框，替代原生 prompt（可校验空值与长度，移动端样式统一） -->
    <Modal :show="!!askDialog" :title="askDialog?.title || ''" width="420px" @close="closeAsk">
      <div class="space-y-3">
        <input v-model="askValue" class="input" :placeholder="askDialog?.placeholder || ''"
          :maxlength="askDialog?.maxLength || undefined" @keydown.enter="onAskEnter" />
        <div class="flex items-center justify-between text-[11px] text-ink-400">
          <span v-if="askDialog?.hint">{{ askDialog.hint }}</span>
          <span v-else>&nbsp;</span>
          <span>{{ askValue.length }} / {{ askDialog?.maxLength || '-' }}</span>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeAsk">取消</button>
          <button class="btn-primary" @click="submitAsk">{{ askDialog?.confirmText || '确定' }}</button>
        </div>
      </div>
    </Modal>

    <!-- 分享链接 -->
    <Modal :show="showShare" title="只读分享看板" @close="showShare = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-500">生成免登录只读链接，任何人可查看当前看板（不可编辑）。</p>
        <div v-if="shareUrl" class="flex items-center gap-2 rounded-control bg-ink-50 p-2">
          <input :value="shareUrl" readonly class="input flex-1 py-1 text-[12px]" />
          <button class="btn-outline text-[12px]" @click="copyShare">复制链接</button>
          <button class="btn-ghost text-[12px] text-rose-500" @click="revokeShare">撤销</button>
        </div>
        <div v-else class="flex justify-end">
          <button class="btn-primary" @click="genShare">生成分享链接</button>
        </div>
      </div>
    </Modal>

    <!-- 288：套用卡片模板（回填标题前缀 / 估时 / 标签 / DoD） -->
    <Modal :show="showTemplateApply" title="套用卡片模板" width="480px" @close="showTemplateApply = false">
      <div class="space-y-3">
        <select v-model="tplForm.tpl" class="input">
          <option :value="null" disabled>选择模板</option>
          <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
        <select v-model="tplForm.board" class="input">
          <option :value="null" disabled>选择目标列</option>
          <option v-for="b in boards" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>
        <input v-model="tplForm.prefix" class="input" maxlength="50" placeholder="标题前缀（选填）" />
        <p class="text-[11px] text-ink-400">套用后会自动带入模板的估时、标签、优先级与验收清单。</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showTemplateApply = false">取消</button>
          <button class="btn-primary" @click="applyTemplate">套用</button>
        </div>
      </div>
    </Modal>

    <!-- 296 / 286：项目设置（已归档卡片 + 迭代） -->
    <Modal :show="showSettings" title="项目设置" width="640px" @close="showSettings = false">
      <div class="space-y-5">
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">已归档卡片（{{ archivedTotal }}）</div>
          <div class="flex gap-2">
            <input v-model="archivedKw" class="input flex-1" placeholder="按标题/描述筛选" @input="onArchivedKw" />
            <button class="btn-outline text-[12px]" @click="loadArchived(1)">刷新</button>
          </div>
          <div class="mt-2 max-h-56 divide-y divide-ink-50 overflow-y-auto">
            <div v-for="c in archived" :key="c.id" class="flex items-center justify-between gap-2 py-2 text-[12px]">
              <span class="min-w-0 truncate text-ink-700">{{ c.code }} {{ c.title }}</span>
              <span class="shrink-0">
                <button class="mr-2 text-brand-600" @click="restoreArchived(c)">恢复</button>
                <button class="text-rose-500" @click="deleteArchived(c)">彻底删除</button>
              </span>
            </div>
            <div v-if="!archived.length" class="py-6 text-center text-[12px] text-ink-400">暂无归档卡片</div>
          </div>
          <button v-if="archivedHasMore" class="btn-ghost mt-1 w-full text-[12px]" @click="loadArchived(archivedPage + 1)">加载更多</button>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">迭代</div>
          <div class="space-y-1">
            <div v-for="s in sprints" :key="s.id" class="flex items-center justify-between rounded-control bg-ink-50 px-2 py-1.5 text-[12px]">
              <span>{{ s.name }} <span class="text-[11px] text-ink-400">{{ s.status }} · {{ s.stats?.done }}/{{ s.stats?.total }}</span></span>
              <span class="shrink-0">
                <button v-if="s.status !== 'active' && s.status !== 'closed'" class="mr-2 text-brand-600" @click="sprintStart(s)">开始</button>
                <button v-if="s.status === 'active'" class="text-rose-500" @click="sprintClose(s)">结束</button>
              </span>
            </div>
            <div v-if="!sprints.length" class="text-[12px] text-ink-400">暂无迭代</div>
          </div>
          <p class="mt-1 text-[11px] text-ink-400">开启迭代时会校验卡片估时是否超出成员容量，超出需再次确认。</p>
        </div>
      </div>
    </Modal>

    <!-- 299：生成周报（渲染 Markdown，可复制 / 下载 .md） -->
    <Modal :show="showReport" title="生成周报" width="640px" @close="showReport = false">
      <div v-if="report" class="space-y-3">
        <div class="max-h-[50vh] overflow-y-auto rounded-control bg-ink-50 p-3 text-[13px] leading-relaxed text-ink-700" v-html="reportHtml"></div>
        <div class="flex justify-end gap-2">
          <button class="btn-outline" @click="copyReport">复制</button>
          <button class="btn-primary" @click="downloadReport">下载 .md</button>
        </div>
      </div>
      <div v-else class="grid h-24 place-items-center text-[12px] text-ink-400">生成中…</div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { projectApi } from '../../api'
import { pxApi } from '../../api/projectsx'
import { shareUrl as buildShareUrl } from '../../api/base'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import { renderMarkdown } from '../../utils/markdown'
import Modal from '../../components/Modal.vue'
import Skeleton from '../../components/Skeleton.vue'

const route = useRoute()
const app = useAppStore()
const projectId = route.params.id
const project = ref(null)
const boards = ref([])
const cardKw = ref('')
const prioFilter = ref('')
const assigneeFilter = ref('')
const dueFilter = ref('')
const compact = ref(localStorage.getItem('board_compact') === '1')
const themeIdx = ref(Number(localStorage.getItem('board_theme') || 0))
const showNewCard = ref(null)
const cardForm = reactive({ board: null, title: '', description: '', priority: 'medium', due_date: '' })
const activeCard = ref(null)
const comments = ref([])
const commentInput = ref('')
const labelInput = ref('')
const subtasks = ref([])
const subInput = ref('')
const worklogs = ref([])
const wlMinutes = ref(null)
const wlNote = ref('')
const showMembers = ref(false)
const memberQ = ref('')
const candidates = ref([])
const showStats = ref(false)
const stats = ref(null)
const burn = ref({ dates: [], remaining: [], ideal: [] })
const showShare = ref(false)
const shareUrl = ref('')
const shareToken = ref('')
// #173 首屏加载骨架（只在第一次进入时显示，后续刷新不闪）
const loading = ref(true)
// #172 触屏「移动到列」选择器
const movePickerFor = ref(null)
let dragCard = null

// ===== 第三轮升级（281–305）状态 =====
const viewTabs = [
  { v: 'board', label: '看板' },
  { v: 'activities', label: '动态' },
  { v: 'standup', label: '站会' },
]
const viewTab = ref('board')
const searchInput = ref(null)
// 292：服务端搜索（命中 id 集合 + 总数 + 高亮）
const searchTotal = ref(null)
const searchLoading = ref(false)
const serverIds = ref(null)
const highlightMap = ref({})
let searchSeq = 0
// 305：编号跳转高亮
const highlightCardId = ref(null)
// 293：折叠列 / 隐藏空列（localStorage: board_collapsed）
const collapsedIds = ref([])
const hideEmpty = ref(false)
// 283：GET /boards/<id>/wip-limit 返回的上限
const wipLimits = ref({})
// 288：卡片模板
const templates = ref([])
const showTemplateApply = ref(false)
const tplForm = reactive({ tpl: null, board: null, prefix: '' })
// 289：详情页预估工时输入（小时）
const estimateHours = ref(0)
// 290：时间线
const detailTabs = [{ v: 'detail', label: '详情' }, { v: 'timeline', label: '时间线' }]
const detailTab = ref('detail')
const timeline = ref([])
const timelinePage = ref(1)
const timelineHasMore = ref(false)
const timelineLoading = ref(false)
// 291：多选
const selectedIds = ref([])
// 294：动态
const activities = ref([])
const actTotal = ref(0)
const actPage = ref(1)
const actHasMore = ref(false)
const actLoading = ref(false)
const actActor = ref('')
const actAction = ref('')
// 295：关注状态
const cardMenuFor = ref(null)
const watchMap = ref({})
// 296 / 286：设置弹窗
const showSettings = ref(false)
const archived = ref([])
const archivedTotal = ref(0)
const archivedPage = ref(1)
const archivedHasMore = ref(false)
const archivedKw = ref('')
const sprints = ref([])
// 297：成员负载
const workload = ref([])
// 298：站会
const standup = ref({})
const standupLoading = ref(false)
// 299：周报
const showReport = ref(false)
const report = ref(null)
// 304：成员（含在办/逾期数）
const memberRows = ref([])
// 285：DoD 验收清单
const dod = reactive({ list: [], total: 0, done: 0 })
const dodInput = ref('')


const THEME_BGS = ['', 'bg-sky-50/40', 'bg-amber-50/40', 'bg-emerald-50/40', 'bg-slate-100/60']
const THEME_NAMES = ['浅色', '天蓝', '暖橙', '青绿', '深灰']
const themeClass = ref(THEME_BGS[themeIdx.value])
const themeName = THEME_NAMES[themeIdx.value]
function cycleTheme() { themeIdx.value = (themeIdx.value + 1) % THEME_BGS.length; themeClass.value = THEME_BGS[themeIdx.value]; localStorage.setItem('board_theme', String(themeIdx.value)) }
function saveTheme() { localStorage.setItem('board_compact', compact.value ? '1' : '0') }

const LABEL_COLORS = ['#dbeafe', '#fce7f3', '#dcfce7', '#fef9c3', '#ffedd5', '#e0e7ff', '#f3e8ff']
const LABEL_TEXT = ['#1d4ed8', '#be185d', '#15803d', '#a16207', '#c2410c', '#4338ca', '#7e22ce']
function labelName(l) { return typeof l === 'string' ? l : (l.name || '') }
function labelStyle(l) {
  const name = labelName(l)
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  const i = h % LABEL_COLORS.length
  return { background: LABEL_COLORS[i], color: LABEL_TEXT[i] }
}

const prioIcon = (p) => ({ low: '🟢', medium: '🟡', high: '🟠', urgent: '🔴' }[p] || '⚪')
function todayStr() { return new Date().toISOString().slice(0, 10) }
function dueTone(c) {
  if (c.is_overdue) return 'font-medium text-rose-500'
  if (c.due_date === todayStr()) return 'font-medium text-orange-500'
  return ''
}
function dueIcon(c) {
  if (c.is_overdue) return '⚠'
  if (c.due_date === todayStr()) return '📌'
  return '🗓'
}
function cardTone(c) {
  if (c.is_overdue) return 'border-l-4 border-l-rose-400'
  if (c.due_date === todayStr()) return 'border-l-4 border-l-orange-400'
  return ''
}
function escapeHtml(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
// 292：有关键词且服务端已返回结果时按命中 id 过滤，高亮片段来自后端（已转义）
function cardTitleHtml(c) {
  const hl = highlightMap.value[c.id]
  return hl ? hl : escapeHtml(c.title)
}
function matchCards(b) {
  const today = todayStr()
  return (b.cards || []).filter((c) => {
    const okKw = serverIds.value ? serverIds.value.has(c.id) : (!cardKw.value || c.title.includes(cardKw.value))
    const okPrio = !prioFilter.value || c.priority === prioFilter.value
    const okAssignee = !assigneeFilter.value || (c.assignee_ids || []).map(String).includes(String(assigneeFilter.value))
    let okDue = true
    if (dueFilter.value === 'overdue') okDue = c.is_overdue
    else if (dueFilter.value === 'today') okDue = c.due_date === today
    else if (dueFilter.value === 'week') { const diff = (new Date(c.due_date) - new Date(today)) / 86400000; okDue = c.due_date && diff >= 0 && diff <= 7 }
    else if (dueFilter.value === 'nodate') okDue = !c.due_date
    return okKw && okPrio && okAssignee && okDue
  })
}
// 293：隐藏空列后的可见列
const visibleBoards = computed(() =>
  hideEmpty.value ? boards.value.filter((b) => matchCards(b).length > 0) : boards.value
)
function isCollapsed(id) { return collapsedIds.value.includes(id) }
function toggleCollapse(id) {
  collapsedIds.value = isCollapsed(id) ? collapsedIds.value.filter((x) => x !== id) : [...collapsedIds.value, id]
  saveCollapsed()
}
function loadCollapsed() {
  try {
    const raw = JSON.parse(localStorage.getItem('board_collapsed') || '{}')
    collapsedIds.value = Array.isArray(raw?.ids) ? raw.ids : []
    hideEmpty.value = !!raw?.hideEmpty
  } catch {
    collapsedIds.value = []
    hideEmpty.value = false
  }
}
function saveCollapsed() {
  localStorage.setItem('board_collapsed', JSON.stringify({ ids: collapsedIds.value, hideEmpty: hideEmpty.value }))
}
// 283：优先用 GET wip-limit 的上限，在办数取看板接口的实时值
function wipInfo(b) {
  const cached = wipLimits.value[b.id] || {}
  const limit = b.wip_limit ?? cached.limit ?? 0
  const active = b.active_count ?? cached.active ?? 0
  return { active, limit, over: !!limit && active > limit }
}
// 289：分钟 → 小时展示
function fmtH(minutes) {
  const m = Number(minutes) || 0
  if (!m) return '0h'
  return `${Math.round((m / 60) * 10) / 10}h`
}
// 301：到期倒计时
function daysLeft(c) {
  if (!c.due_date) return null
  return Math.round((new Date(`${c.due_date}T00:00:00`) - new Date(`${todayStr()}T00:00:00`)) / 86400000)
}
function countdownText(c) {
  if (c.status === 'done') return '已完成'
  const days = daysLeft(c)
  if (days === null) return ''
  if (days < 0) return `逾期 ${Math.abs(days)} 天`
  if (days === 0) return '今天到期'
  return `剩 ${days} 天`
}
function countdownTone(c) {
  if (c.status === 'done') return 'bg-ink-100 text-ink-400'
  const days = daysLeft(c)
  if (days === null) return ''
  if (days < 0) return 'bg-rose-50 font-medium text-rose-600'
  if (days === 0) return 'bg-orange-50 font-medium text-orange-600'
  if (days <= 2) return 'bg-amber-50 text-amber-600'
  return 'bg-ink-100 text-ink-500'
}

// S2-B1：看板实时事件去抖时间戳——本地写操作都会走 load()，
// 距上次 load 1.5s 内的 WS 回弹视为「自己刚操作过」直接忽略，
// 避免本地操作→后端广播→前端再刷新的回环。
let lastLocalBoardWrite = 0

async function load() {
  lastLocalBoardWrite = Date.now()
  try {
    const r = await projectApi.board(projectId)
    project.value = r.project
    boards.value = r.boards || []
    // 283：列头 active/limit 取 GET /boards/<id>/wip-limit（列集合变化时才批量拉取）
    const ids = boards.value.map((b) => b.id).join(',')
    if (ids !== wipLoadedFor) loadWipLimits()
  } catch (e) { app.toastMsg(e?.message || '加载看板失败', 'error') } finally { loading.value = false }
}
let wipLoadedFor = ''
async function loadWipLimits() {
  const list = [...boards.value]
  wipLoadedFor = list.map((b) => b.id).join(',')
  const rows = await Promise.allSettled(list.map((b) => pxApi.wipLimit(b.id)))
  const map = {}
  rows.forEach((r, i) => {
    if (r.status === 'fulfilled' && r.value) {
      map[list[i].id] = { active: r.value.active, limit: r.value.limit, over: r.value.over_limit }
    }
  })
  wipLimits.value = map
}

// #166 页内输入对话框：替换 addBoard / renameBoard / editComment 三处原生 prompt
const askDialog = ref(null)
const askValue = ref('')
function openAsk(opts, action) {
  askDialog.value = { maxLength: 40, confirmText: '确定', ...opts, action }
  askValue.value = opts?.value || ''
}
function closeAsk() { askDialog.value = null; askValue.value = '' }
function onAskEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  submitAsk()
}
function submitAsk() {
  const d = askDialog.value
  if (!d) return
  const v = askValue.value.trim()
  if (!v) return app.toastMsg('内容不能为空', 'warn')
  if (d.maxLength && v.length > d.maxLength) return app.toastMsg(`最多 ${d.maxLength} 个字符`, 'warn')
  const action = d.action
  closeAsk()
  action?.(v)
}
function addBoard() {
  openAsk({ title: '新建列', placeholder: '列名称，如 待办 / 进行中', maxLength: 30, confirmText: '创建' }, async (name) => {
    try {
      await projectApi.createBoard(projectId, name)
      load()
    } catch (e) { app.toastMsg(e?.message || '新建列失败', 'error') }
  })
}
function renameBoard(b) {
  openAsk({ title: `重命名「${b.name}」`, value: b.name, maxLength: 30, confirmText: '保存' }, async (name) => {
    try {
      await projectApi.renameBoard(b.id, name)
      load()
    } catch (e) { app.toastMsg(e?.message || '重命名失败', 'error') }
  })
}
function editComment(cm) {
  openAsk({ title: '修改评论', value: cm.content, placeholder: '评论内容', maxLength: 500, confirmText: '保存' }, async (content) => {
    try {
      const r = await projectApi.updateComment(activeCard.value.id, cm.id, content)
      Object.assign(cm, r)
    } catch (e) { app.toastMsg(e?.message || '修改评论失败', 'error') }
  })
}
async function removeBoard(b) {
  try {
    if (confirm(`删除列「${b.name}」及所有卡片？`)) { await projectApi.deleteBoard(b.id); load() }
  } catch (e) { app.toastMsg(e?.message || '删除列失败', 'error') }
}
async function createCard() {
  try {
    const boardId = showNewCard.value.board || cardForm.board
    if (!cardForm.title.trim() || !boardId) return app.toastMsg('请填写标题并选择列', 'error')
    await projectApi.createCard(boardId, { title: cardForm.title, description: cardForm.description, priority: cardForm.priority, due_date: cardForm.due_date || null })
    app.toastMsg('已创建', 'success')
    Object.assign(cardForm, { board: null, title: '', description: '', due_date: '' })
    showNewCard.value = null
    load()
  } catch (e) { app.toastMsg(e?.message || '创建卡片失败', 'error') }
}
function onDragStart(e, card) { dragCard = card; e.dataTransfer.effectAllowed = 'move' }
async function onDrop(e, targetBoardId) {
  if (!dragCard) return
  const card = dragCard
  dragCard = null
  try {
    const target = boards.value.find((b) => Number(b.id) === Number(targetBoardId))
    if (!target) return
    // 283：拖入前先校验目标列 WIP 上限，超限提示并回滚（不落库，重拉服务端状态）
    if (card.status !== 'done' && Number(card.board) !== Number(target.id)) {
      const wip = wipInfo(target)
      if (wip.limit && wip.active >= wip.limit) {
        app.toastMsg(`「${target.name}」在办 ${wip.active}/${wip.limit} 已达 WIP 上限，已回滚`, 'warn')
        load()
        return
      }
    }
    // 按鼠标位置计算插入下标：落在卡片上半区插到其前面，否则插到后面；
    // #159 下标以「可见卡片」定位到全量列表中的真实位置，隐藏卡片不会造成偏移
    const col = e.currentTarget
    const els = [...(col?.querySelectorAll?.('[data-card-id]') || [])]
    const all = target.cards || []
    let index = all.length
    for (let i = 0; i < els.length; i++) {
      const r = els[i].getBoundingClientRect()
      if (e.clientY < r.top + r.height / 2) {
        const pos = all.findIndex((c) => Number(c.id) === Number(els[i].dataset.cardId))
        index = pos >= 0 ? pos : all.length
        break
      }
    }
    // 同列拖动时被拖卡片自身还在列表里，需扣掉它的位置（卡片字段是 board）
    if (Number(card.board) === Number(target.id)) {
      const origin = all.findIndex((c) => Number(c.id) === Number(card.id))
      if (origin >= 0 && origin < index) index -= 1
    }
    await projectApi.moveCard(card.id, target.id, index)
  } catch (err) {
    app.toastMsg(err?.message || '移动卡片失败', 'error')
  } finally {
    // 成功或失败都以服务端为准重拉，失败后界面不会停在一个假的落位
    load()
  }
}
// #172 触屏改列：追加到目标列末尾
function toggleMovePicker(id) { movePickerFor.value = movePickerFor.value === id ? null : id }
async function moveCardTo(c, boardId) {
  movePickerFor.value = null
  if (!boardId) return
  const target = boards.value.find((b) => Number(b.id) === Number(boardId))
  if (!target || Number(target.id) === Number(c.board)) return
  try {
    await projectApi.moveCard(c.id, target.id, (target.cards || []).length)
    app.toastMsg(`已移动到「${target.name}」`, 'success')
  } catch (e) {
    app.toastMsg(e?.message || '移动卡片失败', 'error')
  } finally {
    load()
  }
}
let cardSeq = 0
async function openCard(c) {
  const seq = ++cardSeq
  try {
    const [full, cm, dd] = await Promise.all([
      projectApi.card(c.id),
      projectApi.comments(c.id),
      pxApi.dod(c.id).catch(() => null),
    ])
    if (seq !== cardSeq || (full && full.id != null && full.id !== c.id)) return
    activeCard.value = { ...full }
    comments.value = cm.list || []
    subtasks.value = full.subtasks || []
    worklogs.value = full.worklogs || []
    applyDod(dd)
    estimateHours.value = Math.round((full.estimated_minutes || 0) / 60 * 10) / 10
    // 290：每次打开重置到详情页签与时间线分页
    detailTab.value = 'detail'
    timeline.value = []
    timelinePage.value = 1
    timelineHasMore.value = false
    loadWatchState(full.id)
  } catch (e) { if (seq === cardSeq) app.toastMsg(e?.message || '打开卡片失败', 'error') }
}
// Ctrl/⌘ 点击多选，普通点击打开详情
function onCardClick(e, c) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault()
    selectedIds.value = selectedIds.value.includes(c.id)
      ? selectedIds.value.filter((x) => x !== c.id)
      : [...selectedIds.value, c.id]
    return
  }
  openCard(c)
}
async function updateCard(patch) {
  try {
    const r = await projectApi.updateCard(activeCard.value.id, patch)
    activeCard.value = { ...activeCard.value, ...r }
    load()
  } catch (e) {
    // 285：DoD 未完成时后端返回 needs_confirm，二次确认后带 force=1 重试
    if (e?.response?.data?.needs_confirm) {
      if (confirm(`${e.message}\n仍要结单？`)) return updateCard({ ...patch, force: true })
    }
    app.toastMsg(e?.message || '更新卡片失败', 'error')
    // 失败回滚：重新拉服务端数据，避免本地乐观修改与服务端长期不一致
    try {
      if (activeCard.value) {
        const full = await projectApi.card(activeCard.value.id)
        activeCard.value = { ...full }
      }
    } catch { /* ignore */ }
  }
}
async function deleteCard() {
  try {
    if (!confirm('删除该任务？')) return
    await projectApi.deleteCard(activeCard.value.id)
    activeCard.value = null
    load()
  } catch (e) { app.toastMsg(e?.message || '删除卡片失败', 'error') }
}
async function copyCard() {
  try {
    await projectApi.copyCard(activeCard.value.id)
    app.toastMsg('已复制', 'success')
    activeCard.value = null
    load()
  } catch (e) { app.toastMsg(e?.message || '复制卡片失败', 'error') }
}
async function quickCopy(c) {
  try {
    await projectApi.copyCard(c.id)
    app.toastMsg('已复制卡片', 'success')
    load()
  } catch (e) { app.toastMsg(e?.message || '复制卡片失败', 'error') }
}
async function addComment() {
  try {
    const content = commentInput.value.trim()
    if (!content) return
    comments.value.push(await projectApi.addComment(activeCard.value.id, content))
    commentInput.value = ''
  } catch (e) { app.toastMsg(e?.message || '发表评论失败', 'error') }
}
async function delComment(cm) {
  try {
    await projectApi.deleteComment(activeCard.value.id, cm.id)
    comments.value = comments.value.filter((x) => x.id !== cm.id)
  } catch (e) { app.toastMsg(e?.message || '删除评论失败', 'error') }
}
async function addLabel() {
  try {
    const l = labelInput.value.trim()
    if (!l) return
    const labels = [...(activeCard.value.labels || []), l]
    labelInput.value = ''
    await updateCard({ labels })
  } catch (e) { app.toastMsg(e?.message || '添加标签失败', 'error') }
}
async function removeLabel(l) {
  try {
    await updateCard({ labels: (activeCard.value.labels || []).filter((x) => labelName(x) !== l) })
  } catch (e) { app.toastMsg(e?.message || '移除标签失败', 'error') }
}
async function toggleAssignee(uid) {
  try {
    let ids = [...activeCard.value.assignee_ids]
    ids = ids.includes(uid) ? ids.filter((x) => x !== uid) : [...ids, uid]
    await updateCard({ assignee_ids: ids })
  } catch (e) { app.toastMsg(e?.message || '调整负责人失败', 'error') }
}
async function addSubtask() {
  try {
    const title = subInput.value.trim()
    if (!title) return
    subtasks.value.push(await projectApi.addSubtask(activeCard.value.id, title))
    subInput.value = ''
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '添加子任务失败', 'error') }
}
async function toggleSubtask(s) {
  try {
    const r = await projectApi.updateSubtask(activeCard.value.id, s.id, { is_done: !s.is_done })
    Object.assign(s, r)
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '更新子任务失败', 'error') }
}
async function delSubtask(s) {
  try {
    await projectApi.deleteSubtask(activeCard.value.id, s.id)
    subtasks.value = subtasks.value.filter((x) => x.id !== s.id)
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '删除子任务失败', 'error') }
}
async function addWorklog() {
  try {
    if (!wlMinutes.value) return
    const wl = await projectApi.addWorklog(activeCard.value.id, { minutes: wlMinutes.value, note: wlNote.value })
    worklogs.value.push(wl)
    wlMinutes.value = null; wlNote.value = ''
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '记录工时失败', 'error') }
}
async function delWorklog(w) {
  try {
    await projectApi.deleteWorklog(activeCard.value.id, w.id)
    worklogs.value = worklogs.value.filter((x) => x.id !== w.id)
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '删除工时失败', 'error') }
}
async function refreshCardMeta() {
  try {
    const full = await projectApi.card(activeCard.value.id)
    activeCard.value = {
      ...activeCard.value,
      subtask_total: full.subtask_total, subtask_done: full.subtask_done, progress: full.progress,
      spent_minutes: full.spent_minutes, estimated_minutes: full.estimated_minutes,
      estimate_diff: full.estimate_diff, estimate_over: full.estimate_over, remaining_minutes: full.remaining_minutes,
    }
  } catch (e) { app.toastMsg(e?.message || '刷新卡片失败', 'error') }
}
let memberTimer = null
// 304：成员接口一次返回成员（含 open_count / overdue_count）与候选
async function loadMembers(q = '') {
  try {
    const r = await pxApi.members(projectId, q)
    memberRows.value = r.members || []
    candidates.value = r.candidates || []
  } catch (e) { app.toastMsg(e?.message || '加载成员失败', 'error') }
}
function openMembers() {
  showMembers.value = true
  loadMembers(memberQ.value)
}
function searchMembers() {
  clearTimeout(memberTimer)
  memberTimer = setTimeout(() => loadMembers(memberQ.value), 300)
}
async function addMembers(ids) {
  try {
    await projectApi.addMembers(projectId, ids)
    app.toastMsg('已添加', 'success')
    await Promise.all([load(), loadMembers(memberQ.value)])
  } catch (e) { app.toastMsg(e?.message || '添加成员失败', 'error') }
}
async function removeMember(uid) {
  try {
    await projectApi.removeMember(projectId, uid)
    await Promise.all([load(), loadMembers(memberQ.value)])
  } catch (e) { app.toastMsg(e?.message || '移出成员失败', 'error') }
}
async function loadStats() {
  try {
    stats.value = await projectApi.stats(projectId)
  } catch (e) { app.toastMsg(e?.message || '加载统计失败', 'error') }
}
async function loadBurndown() {
  try {
    burn.value = await projectApi.burndown(projectId)
  } catch (e) { app.toastMsg(e?.message || '加载燃尽图失败', 'error') }
}
function linePoints(arr) {
  if (!arr || arr.length < 2) return ''
  const max = Math.max(...arr, 1)
  const w = 520, h = 180, pad = 10
  return arr.map((v, i) => `${(i / (arr.length - 1)) * (w - 2 * pad) + pad},${h - pad - (v / max) * (h - 2 * pad)}`).join(' ')
}
async function loadShare() {
  shareUrl.value = ''; shareToken.value = ''
}
async function genShare() {
  try {
    const r = await projectApi.createShare(projectId)
    shareToken.value = r.token
    // F4：对外链接走 base.js shareUrl()，部署时给出正确的前端站点地址
    shareUrl.value = buildShareUrl(r.token)
    app.toastMsg('已生成分享链接', 'success')
  } catch (e) { app.toastMsg(e?.message || '生成分享链接失败', 'error') }
}
function copyShare() {
  // 剪贴板在非安全上下文/无权限时会 reject，吞掉避免触发全局兜底弹错
  navigator.clipboard?.writeText(shareUrl.value).catch(() => {})
  app.toastMsg('已复制', 'success')
}
async function revokeShare() {
  try {
    if (!shareToken.value) return
    await projectApi.revokeShare(projectId, shareToken.value)
    shareUrl.value = ''; shareToken.value = ''
    app.toastMsg('已撤销', 'success')
  } catch (e) { app.toastMsg(e?.message || '撤销分享失败', 'error') }
}
// ===== 294：项目动态 =====
let actTimer = null
function switchView(v) {
  viewTab.value = v
  if (v === 'activities' && !activities.value.length) loadActivities(1)
  if (v === 'standup') loadStandup()
}
function onActActionInput() {
  clearTimeout(actTimer)
  actTimer = setTimeout(() => loadActivities(1), 300)
}
async function loadActivities(page = 1) {
  actLoading.value = true
  try {
    const r = await pxApi.activities(projectId, {
      page,
      page_size: 30,
      actor: actActor.value || undefined,
      action: actAction.value.trim() || undefined,
    })
    activities.value = page === 1 ? (r.list || []) : [...activities.value, ...(r.list || [])]
    actTotal.value = r.total || 0
    actPage.value = page
    actHasMore.value = !!r.has_more
  } catch (e) { app.toastMsg(e?.message || '加载动态失败', 'error') } finally { actLoading.value = false }
}
function onActivityScroll(e) {
  const el = e.target
  if (actHasMore.value && !actLoading.value && el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
    loadActivities(actPage.value + 1)
  }
}

// ===== 298：站会 =====
async function loadStandup() {
  standupLoading.value = true
  try { standup.value = await pxApi.standup(projectId) } catch (e) {
    app.toastMsg(e?.message || '加载站会失败', 'error')
  } finally { standupLoading.value = false }
}
function standupText() {
  const d = standup.value || {}
  const fmtList = (arr) => (arr || []).map((c) => `${c.code || ''} ${c.title}`.trim()).join('；') || '无'
  const lines = [`站会 ${d.date || ''}`.trim()]
  for (const m of d.per_member || []) {
    lines.push(`${m.display_name}：`)
    lines.push(`  昨日完成：${fmtList(m.done_yesterday)}`)
    lines.push(`  今日计划：${fmtList(m.today_plan)}`)
    lines.push(`  阻塞：${(m.blocked || []).map((c) => `${c.code || ''} ${c.title}（${c.reason || ''}）`.trim()).join('；') || '无'}`)
  }
  return lines.join('\n')
}
async function copyStandup() {
  try {
    await navigator.clipboard.writeText(standupText())
    app.toastMsg('已复制站会文本', 'success')
  } catch { app.toastMsg('复制失败，请手动选择文本', 'warn') }
}

// ===== 292 / 305：服务端搜索与编号跳转 =====
let kwTimer = null
function onKwInput() {
  clearTimeout(kwTimer)
  kwTimer = setTimeout(runSearch, 300)
}
function onFilterChange() {
  if (cardKw.value.trim()) onKwInput()
}
async function runSearch() {
  const kw = cardKw.value.trim()
  if (!kw) {
    // 清空关键词回退本地过滤
    serverIds.value = null
    searchTotal.value = null
    highlightMap.value = {}
    searchLoading.value = false
    return
  }
  const num = kw.match(/^c-?\s*(\d+)$/i)
  if (num) { jumpToNumber(num[1]); return }
  const seq = ++searchSeq
  searchLoading.value = true
  try {
    const r = await pxApi.search(projectId, {
      q: kw,
      priority: prioFilter.value || undefined,
      assignee: assigneeFilter.value || undefined,
      due: dueFilter.value || undefined,
      page_size: 200,
    })
    if (seq !== searchSeq) return
    const rows = r.list || []
    serverIds.value = new Set(rows.map((c) => c.id))
    searchTotal.value = r.total ?? rows.length
    highlightMap.value = Object.fromEntries(rows.map((c) => [c.id, c.highlight?.title || '']))
  } catch (e) {
    if (seq === searchSeq) app.toastMsg(e?.message || '搜索失败', 'error')
  } finally {
    if (seq === searchSeq) searchLoading.value = false
  }
}
async function jumpToNumber(num) {
  const code = `C-${num}`
  try {
    const card = await pxApi.byNumber(projectId, code)
    cardKw.value = ''
    serverIds.value = null
    searchTotal.value = null
    highlightMap.value = {}
    // 目标列若被折叠 / 隐藏空列过滤掉，先让它可见
    if (isCollapsed(card.board)) collapsedIds.value = collapsedIds.value.filter((x) => x !== card.board)
    if (hideEmpty.value) hideEmpty.value = false
    saveCollapsed()
    await load()
    highlightCardId.value = card.id
    document.querySelector(`[data-card-id="${card.id}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    await openCard(card)
    setTimeout(() => { highlightCardId.value = null }, 3000)
  } catch (e) { app.toastMsg(e?.message || `${code} 不存在`, 'warn') }
}

// ===== 303：导出当前筛选结果的 CSV（含 BOM） =====
const statusName = (s) => ({ todo: '待办', doing: '进行中', done: '已完成' }[s] || s)
const prioName = (p) => ({ low: '低', medium: '中', high: '高', urgent: '紧急' }[p] || p)
function csvCell(v) {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
function exportCsv() {
  const header = ['编号', '列', '标题', '状态', '优先级', '负责人', '标签', '到期日', '预估(h)', '已用(h)', '子任务', '验收']
  const rows = []
  for (const b of boards.value) {
    for (const c of matchCards(b)) {
      rows.push([
        c.code || '', b.name, c.title, statusName(c.status), prioName(c.priority),
        (c.assignee_names || []).join('、'), (c.labels || []).map(labelName).join('、'),
        c.due_date || '',
        c.estimated_minutes ? (c.estimated_minutes / 60).toFixed(1) : '',
        c.spent_minutes ? (c.spent_minutes / 60).toFixed(1) : '',
        c.subtask_total ? `${c.subtask_done}/${c.subtask_total}` : '',
        c.dod_total ? `${c.dod_done}/${c.dod_total}` : '',
      ])
    }
  }
  const csv = [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${project.value?.name || '项目'}-卡片-${todayStr()}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  app.toastMsg(`已导出 ${rows.length} 张卡片`, 'success')
}

// ===== 291：批量操作 =====
function clearSelection() { selectedIds.value = [] }
async function runBatch(payload) {
  try {
    const r = await pxApi.batch(payload)
    app.toastMsg(r.message || '批量操作完成', 'success')
    clearSelection()
    load()
  } catch (e) {
    // 285：批量结单同样受 DoD 校验，确认后带 force=1 重试
    if (e?.response?.data?.needs_confirm && confirm(`${e.message}\n仍要结单？`)) {
      return runBatch({ ...payload, force: true })
    }
    app.toastMsg(e?.message || '批量操作失败', 'error')
  }
}
function batchStatus(status) {
  if (!status || !selectedIds.value.length) return
  runBatch({ project_id: Number(projectId), card_ids: [...selectedIds.value], action: 'status', status })
}
function batchAssign(uid) {
  if (!uid || !selectedIds.value.length) return
  runBatch({ project_id: Number(projectId), card_ids: [...selectedIds.value], action: 'assignees', user_ids: [Number(uid)] })
}
function batchArchive() {
  if (!selectedIds.value.length) return
  runBatch({ project_id: Number(projectId), card_ids: [...selectedIds.value], action: 'archive', is_archived: true })
}
async function batchMoveTo(boardId) {
  if (!boardId || !selectedIds.value.length) return
  const payload = { project_id: Number(projectId), board_id: Number(boardId), card_ids: [...selectedIds.value] }
  try {
    const r = await pxApi.batchMove(payload)
    app.toastMsg(r.message || '已批量移动', 'success')
    clearSelection()
    load()
  } catch (e) {
    // 283/291：目标列超 WIP 时二次确认后 force=1 强移
    if (e?.response?.data?.over_limit && confirm(`${e.message}\n仍要移入？`)) {
      try {
        const r2 = await pxApi.batchMove({ ...payload, force: true })
        app.toastMsg(r2.message || '已批量移动', 'success')
        clearSelection()
        load()
      } catch (e2) { app.toastMsg(e2?.message || '批量移动失败', 'error') }
      return
    }
    app.toastMsg(e?.message || '批量移动失败', 'error')
  }
}

// ===== 295 / 300：卡片菜单 =====
async function toggleCardMenu(c) {
  const open = cardMenuFor.value === c.id
  cardMenuFor.value = open ? null : c.id
  movePickerFor.value = null
  if (!open) loadWatchState(c.id)
}
async function loadWatchState(cardId) {
  try {
    const r = await pxApi.watch(cardId)
    watchMap.value = { ...watchMap.value, [cardId]: !!r.watching }
  } catch { /* 关注状态拿不到不影响菜单其它操作 */ }
}
async function toggleWatch(c) {
  const cur = !!watchMap.value[c.id]
  try {
    if (cur) await pxApi.unwatch(c.id)
    else await pxApi.watchOn(c.id)
    watchMap.value = { ...watchMap.value, [c.id]: !cur }
    app.toastMsg(cur ? '已取消关注' : '已关注该卡片', 'success')
  } catch (e) { app.toastMsg(e?.message || '操作失败', 'error') }
}
function resolveCard(c) {
  cardMenuFor.value = null
  openAsk({ title: '标记解决', placeholder: '解决说明（必填）', maxLength: 200, confirmText: '标记解决' }, async (reason) => {
    try {
      await pxApi.resolve(c.id, reason)
      app.toastMsg('已标记解决', 'success')
      if (activeCard.value?.id === c.id) {
        const full = await projectApi.card(c.id)
        activeCard.value = { ...full }
        if (detailTab.value === 'timeline') loadTimeline(true)
      }
      load()
    } catch (e) { app.toastMsg(e?.message || '标记解决失败', 'error') }
  })
}
async function archiveCard(c) {
  cardMenuFor.value = null
  try {
    await pxApi.archiveCard(c.id, true)
    app.toastMsg('已归档，可在项目设置中恢复', 'success')
    load()
  } catch (e) { app.toastMsg(e?.message || '归档失败', 'error') }
}

// ===== 288：卡片模板 =====
async function loadTemplates() {
  const r = await pxApi.templates()
  templates.value = r.list || []
}
function saveAsTemplate(c) {
  cardMenuFor.value = null
  openAsk({ title: '存为模板', value: c.title, maxLength: 200, confirmText: '保存' }, async (name) => {
    try {
      await pxApi.saveTemplate(c.id, { name })
      app.toastMsg('已存为模板', 'success')
    } catch (e) { app.toastMsg(e?.message || '存为模板失败', 'error') }
  })
}
async function openApplyTemplate(c) {
  cardMenuFor.value = null
  try {
    await loadTemplates()
    if (!templates.value.length) {
      app.toastMsg('还没有卡片模板，可先在卡片菜单里存为模板', 'warn')
      return
    }
    Object.assign(tplForm, { tpl: templates.value[0].id, board: c.board, prefix: '' })
    showTemplateApply.value = true
  } catch (e) { app.toastMsg(e?.message || '加载模板失败', 'error') }
}
async function applyTemplate() {
  if (!tplForm.tpl || !tplForm.board) {
    app.toastMsg('请选择模板与目标列', 'warn')
    return
  }
  try {
    await pxApi.applyTemplate(tplForm.tpl, { board_id: Number(tplForm.board), title_prefix: tplForm.prefix || '' })
    app.toastMsg('已套用模板', 'success')
    showTemplateApply.value = false
    load()
  } catch (e) { app.toastMsg(e?.message || '套用模板失败', 'error') }
}

// ===== 290：时间线 =====
function timelineIcon(t) {
  return ({ created: '🆕', started: '▶', completed: '✅', resolved: '✔', comment: '💬', worklog: '⏱', activity: '•' }[t] || '•')
}
function switchDetailTab(t) {
  detailTab.value = t
  if (t === 'timeline' && !timeline.value.length) loadTimeline(true)
}
async function loadTimeline(reset = false) {
  if (!activeCard.value || timelineLoading.value) return
  if (reset) { timeline.value = []; timelinePage.value = 1; timelineHasMore.value = false }
  timelineLoading.value = true
  try {
    const r = await pxApi.timeline(activeCard.value.id, { page: timelinePage.value, page_size: 30 })
    timeline.value = [...timeline.value, ...(r.list || [])]
    timelineHasMore.value = !!r.has_more
    timelinePage.value += 1
  } catch (e) { app.toastMsg(e?.message || '加载时间线失败', 'error') } finally { timelineLoading.value = false }
}
function onTimelineScroll(e) {
  const el = e.target
  if (timelineHasMore.value && !timelineLoading.value && el.scrollTop + el.clientHeight >= el.scrollHeight - 40) loadTimeline()
}

// ===== 285 / 289：验收清单与预估工时 =====
function applyDod(r) {
  Object.assign(dod, { list: r?.list || [], total: r?.total || 0, done: r?.done || 0 })
}
async function addDodItem() {
  const content = dodInput.value.trim()
  if (!content || !activeCard.value) return
  try {
    await pxApi.addDod(activeCard.value.id, content)
    dodInput.value = ''
    applyDod(await pxApi.dod(activeCard.value.id))
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '添加验收项失败', 'error') }
}
async function toggleDod(d) {
  try {
    await pxApi.updateDod(activeCard.value.id, d.id, { is_done: !d.is_done })
    applyDod(await pxApi.dod(activeCard.value.id))
  } catch (e) { app.toastMsg(e?.message || '更新验收项失败', 'error') }
}
async function delDodItem(d) {
  try {
    await pxApi.deleteDod(activeCard.value.id, d.id)
    applyDod(await pxApi.dod(activeCard.value.id))
  } catch (e) { app.toastMsg(e?.message || '删除验收项失败', 'error') }
}
async function saveEstimate() {
  if (!activeCard.value) return
  try {
    const minutes = Math.max(0, Math.round((Number(estimateHours.value) || 0) * 60))
    await pxApi.setEstimate(activeCard.value.id, minutes)
    await refreshCardMeta()
    load()
  } catch (e) { app.toastMsg(e?.message || '保存预估失败', 'error') }
}

// ===== 296 / 286：项目设置（归档卡片 + 迭代） =====
let archivedTimer = null
function openSettings() {
  showSettings.value = true
  loadArchived(1)
  loadSprints()
}
function onArchivedKw() {
  clearTimeout(archivedTimer)
  archivedTimer = setTimeout(() => loadArchived(1), 300)
}
async function loadArchived(page = 1) {
  try {
    const r = await pxApi.archivedCards(projectId, { q: archivedKw.value.trim() || undefined, page, page_size: 50 })
    archived.value = page === 1 ? (r.list || []) : [...archived.value, ...(r.list || [])]
    archivedTotal.value = r.total || 0
    archivedPage.value = page
    archivedHasMore.value = !!r.has_more
  } catch (e) { app.toastMsg(e?.message || '加载归档卡片失败', 'error') }
}
async function restoreArchived(c) {
  try {
    const r = await pxApi.archivedAction(projectId, { action: 'restore', card_ids: [c.id] })
    app.toastMsg(r.message || '已恢复', 'success')
    await Promise.all([loadArchived(archivedPage.value), load()])
  } catch (e) { app.toastMsg(e?.message || '恢复失败', 'error') }
}
async function deleteArchived(c) {
  if (!confirm(`彻底删除「${c.title}」？删除后不可恢复`)) return
  try {
    const r = await pxApi.archivedAction(projectId, { action: 'delete', card_ids: [c.id] })
    app.toastMsg(r.message || '已彻底删除', 'success')
    await loadArchived(archivedPage.value)
  } catch (e) { app.toastMsg(e?.message || '彻底删除失败', 'error') }
}
async function loadSprints() {
  try { sprints.value = (await pxApi.sprints(projectId)).list || [] } catch (e) {
    app.toastMsg(e?.message || '加载迭代失败', 'error')
  }
}
// 286：开启前容量校验，超容量返回 409 warning，确认后带 confirm=1 再提交
async function sprintStart(s) {
  try {
    await pxApi.sprintAction(projectId, s.id, 'start', { daily_hours: 6 })
    app.toastMsg('迭代已开始', 'success')
    loadSprints()
  } catch (e) {
    if (e?.response?.data?.warning && confirm(`${e.message}\n仍要开始？`)) {
      try {
        await pxApi.sprintAction(projectId, s.id, 'start', { daily_hours: 6, confirm: true })
        app.toastMsg('迭代已开始', 'success')
        loadSprints()
      } catch (e2) { app.toastMsg(e2?.message || '开始迭代失败', 'error') }
      return
    }
    app.toastMsg(e?.message || '开始迭代失败', 'error')
  }
}
async function sprintClose(s) {
  try {
    const r = await pxApi.sprintAction(projectId, s.id, 'close', {})
    app.toastMsg(r.carried_over ? `已结束迭代，结转 ${r.carried_over} 张` : '已结束迭代', 'success')
    loadSprints()
    load()
  } catch (e) { app.toastMsg(e?.message || '结束迭代失败', 'error') }
}

// ===== 297：成员负载 =====
async function loadWorkload() {
  try { workload.value = (await pxApi.workload(projectId)).list || [] } catch (e) {
    app.toastMsg(e?.message || '加载成员负载失败', 'error')
  }
}

// ===== 299：周报 =====
async function openReport() {
  showReport.value = true
  report.value = null
  try {
    report.value = await pxApi.weeklyReport(projectId)
  } catch (e) {
    app.toastMsg(e?.message || '生成周报失败', 'error')
    showReport.value = false
  }
}
// 轻量 Markdown 渲染复用 #F6 的安全链路（marked + DOMPurify）
const reportHtml = computed(() => renderMarkdown(report.value?.markdown || ''))
async function copyReport() {
  try {
    await navigator.clipboard.writeText(report.value?.markdown || '')
    app.toastMsg('已复制周报', 'success')
  } catch { app.toastMsg('复制失败，请手动选择文本', 'warn') }
}
function downloadReport() {
  const md = report.value?.markdown || ''
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = report.value?.filename || `${project.value?.name || '项目'}-周报-${todayStr()}.md`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ===== 302：快捷键（输入框内与弹窗打开时自动禁用） =====
function anyModalOpen() {
  return !!(showNewCard.value || activeCard.value || showMembers.value || showStats.value ||
    showShare.value || askDialog.value || showTemplateApply.value || showSettings.value || showReport.value)
}
function onKeydown(e) {
  const t = e.target
  const tag = (t?.tagName || '').toLowerCase()
  const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || !!t?.isContentEditable
  if (e.key === 'Escape') {
    if (typing) { t.blur(); return }
    if (cardMenuFor.value) { cardMenuFor.value = null; return }
    if (movePickerFor.value) { movePickerFor.value = null; return }
    if (selectedIds.value.length) { clearSelection(); return }
    if (activeCard.value) { activeCard.value = null; return }
    if (showNewCard.value) { showNewCard.value = null; return }
    if (showTemplateApply.value) { showTemplateApply.value = false; return }
    if (showSettings.value) { showSettings.value = false; return }
    if (showReport.value) { showReport.value = false; return }
    if (showMembers.value) { showMembers.value = false; return }
    if (showStats.value) { showStats.value = false; return }
    if (showShare.value) { showShare.value = false; return }
    return
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return
  if (anyModalOpen() || viewTab.value !== 'board') return
  if (e.key === 'n' || e.key === 'N') {
    e.preventDefault()
    showNewCard.value = { board: null }
  } else if (e.key === '/') {
    e.preventDefault()
    searchInput.value?.focus()
  }
}

// S2-B1：订阅看板实时事件（项目成员多端同步卡片创建/更新/删除/批量）
let offBoardEvent = null
onMounted(() => {
  loadCollapsed()
  load()
  window.addEventListener('keydown', onKeydown)
  offBoardEvent = app.onBoardEvent((type, data) => {
    // 本地操作已各自刷新，这里只处理「非本人触发」的远端事件；
    // 事件 data 不带操作者信息，用「距上次本地刷新 <1.5s 则跳过」避免
    // 自己操作引发的回弹刷新（F5 已修 reverse，这里沿用同一保守策略）
    if (Date.now() - lastLocalBoardWrite > 1500) load()
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  offBoardEvent?.()
})
</script>
