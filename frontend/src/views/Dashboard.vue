<template>
  <div class="mx-auto max-w-6xl space-y-5">
    <!-- F665 首页公告横幅：未读置顶公告 -->
    <div v-if="banner" class="card flex items-start gap-3 border-l-4 border-amber-400 bg-amber-50/70 p-4">
      <span class="mt-0.5 text-[18px]">📢</span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag bg-amber-100 text-amber-700">{{ banner.level || '公告' }}</span>
          <RouterLink to="/announcements" class="truncate text-[14px] font-semibold text-ink-800 hover:text-brand-600">
            {{ banner.title }}
          </RouterLink>
          <span v-if="!banner.is_read" class="tag bg-rose-100 text-rose-600">未读</span>
        </div>
        <p class="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink-500">{{ banner.content }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <button class="btn-outline px-2 py-1 text-[12px]" @click="dismissBanner">知道了</button>
        <button class="text-ink-300 hover:text-ink-500" @click="banner = null">×</button>
      </div>
    </div>

    <div class="card flex items-center justify-between p-5">
      <div>
        <h2 class="text-[18px] font-bold text-ink-900">你好，{{ user.displayName }} 👋</h2>
        <p class="mt-1 text-[13px] text-ink-500">{{ today }}，今天也高效工作吧。</p>
      </div>
      <div class="flex gap-2">
        <RouterLink to="/projects/my-tasks" class="btn-outline">我的任务</RouterLink>
        <RouterLink to="/files" class="btn-primary">上传文件</RouterLink>
        <RouterLink to="/notes" class="btn-outline">写笔记</RouterLink>
      </div>
    </div>

    <!-- #97 可编辑快捷入口 + F664 emoji 图标选择 -->
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[13px] font-medium text-ink-700">快捷入口</span>
        <button class="text-[12px] text-brand-600" @click="editingQuick = !editingQuick">
          {{ editingQuick ? '完成' : '编辑' }}
        </button>
      </div>
      <div class="flex flex-wrap gap-2">
        <div v-for="(q, qi) in quickLinks" :key="q.url" class="group flex items-center">
          <!-- F25：http(s) 开头按外链处理，用原生 a + 新窗口；内部路径才走 RouterLink -->
          <component
            :is="isExternalUrl(q.url) ? 'a' : RouterLink"
            v-bind="isExternalUrl(q.url)
              ? { href: q.url, target: '_blank', rel: 'noopener noreferrer' }
              : { to: q.url }"
            class="btn-outline text-[12px]"
          >
            <span v-if="pickingFor !== qi" class="cursor-pointer" @click.prevent.stop="openEmojiPicker(qi)">
              {{ q.icon || '🔗' }}
            </span>
            <select v-else class="mr-1 max-w-[64px] cursor-pointer border-0 bg-transparent text-[12px] outline-none"
                    :value="q.icon" @change="setIcon(qi, $event.target.value)">
              <option v-for="e in EMOJIS" :key="e" :value="e">{{ e }}</option>
            </select>
            {{ q.label }}
          </component>
          <button v-if="editingQuick" class="ml-1 text-rose-400" @click="removeQuick(q)">×</button>
        </div>
        <div v-if="editingQuick" class="flex items-center gap-1">
          <button class="btn-outline px-2 text-[12px]" title="选择图标" @click="openEmojiPicker('new')">
            {{ newQuick.icon || '图标' }}
          </button>
          <select v-if="pickingFor === 'new'" class="input w-16 text-[12px]"
                  :value="newQuick.icon" @change="setIcon('new', $event.target.value)">
            <option v-for="e in EMOJIS" :key="e" :value="e">{{ e }}</option>
          </select>
          <input v-model="newQuick.label" class="input w-20 text-[12px]" placeholder="名称" />
          <input v-model="newQuick.url" class="input w-28 text-[12px]" placeholder="路径或网址" />
          <button class="btn-primary text-[12px]" @click="addQuick">添加</button>
        </div>
      </div>
      <!-- F664 emoji 调色板 -->
      <div v-if="pickingFor !== null" class="mt-2 flex flex-wrap gap-1 rounded-control bg-ink-50 p-2">
        <button v-for="e in EMOJIS" :key="e"
                class="h-7 w-7 rounded-control text-[15px] hover:bg-white hover:shadow-pop"
                @click="setIcon(pickingFor, e)">{{ e }}</button>
        <button class="ml-1 text-[12px] text-ink-400 hover:text-rose-500" @click="pickingFor = null">收起</button>
      </div>
    </div>

    <!-- #331/#332 卡片半宽/全宽与分组：右上角 ⋯ 切换尺寸，分组标题折叠状态本地记忆 -->
    <div class="flex flex-wrap items-center justify-between gap-2 px-1 text-[11px] text-ink-400">
      <span>卡片右上角 ⋯ 可切换半宽 / 全宽，布局自动保存</span>
      <span>点击分组标题可整组折叠</span>
    </div>

    <!-- ================= 工作 ================= -->
    <section class="space-y-2">
      <div class="flex items-center gap-2">
        <button class="flex items-center gap-1.5 text-[13px] font-semibold text-ink-700" @click="toggleGroup('work')">
          <span class="text-[10px] text-ink-400">{{ collapsedGroups.work ? '▸' : '▾' }}</span>
          🗂️ 工作
          <span v-if="collapsedGroups.work" class="text-[11px] font-normal text-ink-300">已折叠</span>
        </button>
        <span class="h-px flex-1 bg-ink-100"></span>
      </div>
      <div v-show="!collapsedGroups.work" class="grid gap-4 lg:grid-cols-2">
        <!-- S26-360 今日聚焦：当日日程 / 今日到期待办 / 待我审批 三段聚合 -->
        <div class="card p-4" :class="colClass('focus')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">🎯 今日聚焦</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-300">
              <span v-if="stamps.focus">更新于 {{ stamps.focus }}</span>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadFocus">↻</button>
              <CardMenu card-key="focus" :size="layoutSize('focus')" @size="(s) => setCardSize('focus', s)" />
            </span>
          </div>
          <div v-if="cardErrors.focus" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.focus }}</span>
            <button class="shrink-0 font-medium" @click="loadFocus">重试</button>
          </div>
          <div v-else-if="!focus" class="py-6 text-center text-[12px] text-ink-400">今日聚焦加载中…</div>
          <div v-else class="mt-2 grid gap-3 md:grid-cols-3">
            <div class="rounded-control bg-ink-50/70 p-2.5">
              <div class="mb-1 flex items-center justify-between text-[11px] text-ink-500">
                <span>📅 今日日程 {{ focus.agenda_count ?? 0 }}</span>
                <RouterLink to="/office/calendar" class="text-brand-600">周视图</RouterLink>
              </div>
              <div v-if="focusAgenda.length" class="space-y-1">
                <RouterLink v-for="a in focusAgenda" :key="a.id" to="/office/calendar"
                            class="flex items-center gap-1.5 hover:bg-white/60">
                  <span class="shrink-0 font-mono text-[10px] text-ink-400">{{ fmtClock(a.start_at) }}</span>
                  <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ a.title }}</span>
                </RouterLink>
              </div>
              <div v-else class="py-2 text-[11px] text-ink-400">今天暂无日程</div>
            </div>
            <div class="rounded-control bg-ink-50/70 p-2.5">
              <div class="mb-1 flex items-center justify-between text-[11px] text-ink-500">
                <span>
                  ✅ 待办 {{ focus.todo_count ?? 0 }}
                  <span v-if="focus.overdue_count" class="text-rose-500">· 逾期 {{ focus.overdue_count }}</span>
                </span>
                <RouterLink to="/office/todo" class="text-brand-600">四象限</RouterLink>
              </div>
              <div v-if="focusTodos.length" class="space-y-1">
                <RouterLink v-for="t in focusTodos" :key="t.id" to="/office/todo"
                            class="flex items-center gap-1.5 hover:bg-white/60">
                  <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="t.overdue ? 'bg-rose-500' : 'bg-brand-400'"></span>
                  <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ t.title }}</span>
                  <span class="shrink-0 text-[10px]" :class="t.overdue ? 'text-rose-500' : 'text-ink-400'">
                    {{ t.overdue ? '逾期' : '今天' }}
                  </span>
                </RouterLink>
              </div>
              <div v-else class="py-2 text-[11px] text-ink-400">今天没有到期待办</div>
            </div>
            <div class="rounded-control bg-ink-50/70 p-2.5">
              <div class="mb-1 flex items-center justify-between text-[11px] text-ink-500">
                <span>📝 待我审批 {{ focus.approvals?.count ?? 0 }}</span>
                <RouterLink to="/office/approvals" class="text-brand-600">去审批</RouterLink>
              </div>
              <div v-if="focusApprovals.length" class="space-y-1">
                <RouterLink v-for="r in focusApprovals" :key="r.id" to="/office/approvals"
                            class="flex items-center gap-1.5 hover:bg-white/60">
                  <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ r.title }}</span>
                  <span class="shrink-0 text-[10px] text-ink-400">{{ r.owner }}</span>
                </RouterLink>
              </div>
              <div v-else class="py-2 text-[11px] text-ink-400">没有待处理审批</div>
            </div>
          </div>
        </div>

        <!-- F657 今日到期聚合卡 / #348 今天与已逾期分组 + 一键延期 -->
        <div class="card p-4" :class="colClass('due')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">📅 今日到期</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-300">
              <span v-if="stamps.due">更新于 {{ stamps.due }}</span>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadDue">↻</button>
              <CardMenu card-key="due" :size="layoutSize('due')" @size="(s) => setCardSize('due', s)" />
            </span>
          </div>
          <div v-if="cardErrors.due" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.due }}</span>
            <button class="shrink-0 font-medium" @click="loadDue">重试</button>
          </div>
          <div class="mt-1 flex items-end gap-2">
            <div class="text-[24px] font-bold text-amber-500">{{ due?.total ?? 0 }}</div>
            <div class="mb-1 text-[11px] text-ink-400">
              今天 · 已逾期 <span class="font-medium text-rose-500">{{ due?.overdue_total ?? 0 }}</span>
            </div>
          </div>
          <div class="mt-2 space-y-1.5">
            <div v-for="g in (due?.groups || [])" :key="g.key"
                 class="flex items-center gap-2 rounded-control px-2 py-1 hover:bg-ink-50">
              <RouterLink :to="g.link || '/dashboard'" class="min-w-0 flex-1">
                <span class="text-[12px] text-ink-600">{{ g.label }}</span>
                <span v-if="g.error" class="ml-1 text-[11px] text-ink-300">该模块暂不可用</span>
              </RouterLink>
              <span class="shrink-0 text-[13px] font-semibold"
                    :class="g.count ? 'text-ink-900' : 'text-ink-300'">{{ g.count }}</span>
              <span v-if="g.overdue" class="shrink-0 rounded-pill bg-rose-50 px-1.5 text-[10px] text-rose-500">逾期 {{ g.overdue }}</span>
            </div>
            <div v-if="due?.errors?.length" class="text-[11px] text-rose-400">
              部分模块取数失败，已跳过 {{ due.errors.length }} 个
            </div>
          </div>
          <!-- #348 已逾期分组 + 一键延期一天 -->
          <div v-if="dueOverdueItems.length" class="mt-2 border-t border-ink-50 pt-2">
            <div class="mb-1 flex items-center justify-between text-[11px]">
              <span class="font-medium text-rose-500">已逾期 · {{ dueOverdueItems.length }}</span>
              <span class="text-ink-300">一键延期 +1 天</span>
            </div>
            <div class="space-y-0.5">
              <div v-for="it in dueOverdueItems.slice(0, 6)" :key="it.kind + '-' + it.id"
                   class="flex items-center gap-2 rounded-control px-2 py-0.5 hover:bg-ink-50">
                <span class="min-w-0 flex-1 truncate text-[11px] text-ink-600">{{ it.title }}</span>
                <span class="shrink-0 text-[10px] text-rose-400">逾期 {{ it.days_overdue }} 天</span>
                <button class="shrink-0 text-[10px] text-brand-600 hover:underline"
                        :disabled="postponing === it.kind + '-' + it.id"
                        @click="postponeDue(it)">
                  {{ postponing === it.kind + '-' + it.id ? '延期…' : '+1 天' }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="dueItems.length" class="mt-2 space-y-0.5 border-t border-ink-50 pt-2">
            <div v-for="it in dueItems" :key="it.key" class="truncate text-[11px] text-ink-400">
              · {{ it.title }}
            </div>
          </div>
        </div>

        <!-- F659 今日日程卡 -->
        <div class="card p-4" :class="colClass('schedule')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">🗓️ 今日日程</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-300">
              <span v-if="stamps.schedule">更新于 {{ stamps.schedule }}</span>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadSchedule">↻</button>
              <CardMenu card-key="schedule" :size="layoutSize('schedule')" @size="(s) => setCardSize('schedule', s)" />
            </span>
          </div>
          <div v-if="cardErrors.schedule" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.schedule }}</span>
            <button class="shrink-0 font-medium" @click="loadSchedule">重试</button>
          </div>
          <div class="mt-2 space-y-1">
            <div v-for="m in scheduleMeetings" :key="'m' + m.id"
                 class="flex items-center gap-2 rounded-control px-2 py-1"
                 :class="m.mine ? 'bg-brand-50' : 'hover:bg-ink-50'">
              <span class="shrink-0 text-[11px] text-ink-400">{{ fmtClock(m.start_at) }}</span>
              <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ m.title }}</span>
              <span v-if="m.mine" class="shrink-0 text-[10px] text-brand-600">我的</span>
            </div>
            <div v-for="d in scheduleDuty" :key="'d' + d.id"
                 class="flex items-center gap-2 rounded-control px-2 py-1"
                 :class="d.mine ? 'bg-emerald-50' : 'hover:bg-ink-50'">
              <span class="shrink-0 text-[11px] text-ink-400">值班</span>
              <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ d.member }} · {{ d.shift }}</span>
              <span v-if="d.mine" class="shrink-0 text-[10px] text-emerald-600">我</span>
            </div>
            <div v-if="!scheduleMeetings.length && !scheduleDuty.length"
                 class="py-3 text-center text-[12px] text-ink-400">
              {{ scheduleError ? '日程数据暂不可用' : '今天没有会议与值班' }}
            </div>
          </div>
        </div>

        <!-- 待办聚合 -->
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4" :class="colClass('todo')">
          <RouterLink to="/projects/my-tasks" class="card p-4 hover:shadow-pop">
            <div class="text-[12px] text-ink-500">已逾期</div>
            <div class="mt-1 text-[24px] font-bold text-rose-500">{{ todo.overdue ?? 0 }}</div>
          </RouterLink>
          <RouterLink to="/projects/my-tasks" class="card p-4 hover:shadow-pop">
            <div class="text-[12px] text-ink-500">今日到期</div>
            <div class="mt-1 text-[24px] font-bold text-amber-500">{{ todo.today ?? 0 }}</div>
          </RouterLink>
          <RouterLink to="/im" class="card p-4 hover:shadow-pop">
            <div class="text-[12px] text-ink-500">未读消息</div>
            <div class="mt-1 text-[24px] font-bold text-brand-600">{{ todo.unread_messages ?? 0 }}</div>
          </RouterLink>
          <div class="card p-4">
            <div class="text-[12px] text-ink-500">本周到期</div>
            <div class="mt-1 text-[24px] font-bold text-ink-900">{{ todo.week ?? 0 }}</div>
          </div>
          <div v-if="cardErrors.todo" class="col-span-full flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.todo }}</span>
            <button class="shrink-0 font-medium" @click="loadTodo">重试</button>
          </div>
        </div>

        <!-- #53 可拖拽排序的统计卡片（F668 顺序同步到服务端） -->
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4" :class="colClass('stats')" ref="statGrid">
          <div v-for="s in orderedStatCards" :key="s.label" class="card p-4 cursor-move"
               draggable="true" @dragstart="onDragStart($event, s.label)" @dragover.prevent @drop="onDrop($event, s.label)">
            <div class="text-[12px] text-ink-500">{{ s.label }}</div>
            <div class="mt-1 text-[24px] font-bold text-ink-900">{{ s.value }}</div>
            <div class="mt-0.5 text-[11px] text-ink-400">{{ s.note }}</div>
          </div>
          <div v-if="cardErrors.stats" class="col-span-full flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.stats }}</span>
            <button class="shrink-0 font-medium" @click="loadStats">重试</button>
          </div>
        </div>

        <!-- #345 里程碑：我参与项目 7 天内到期 -->
        <div class="card p-4" :class="colClass('milestones')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">🏁 里程碑（7 天内）</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-300">
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadMilestones">↻</button>
              <CardMenu card-key="milestones" :size="layoutSize('milestones')" @size="(s) => setCardSize('milestones', s)" />
            </span>
          </div>
          <div v-if="cardErrors.milestones" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.milestones }}</span>
            <button class="shrink-0 font-medium" @click="loadMilestones">重试</button>
          </div>
          <div v-if="milestones.length" class="mt-1 space-y-1">
            <RouterLink v-for="m in milestones" :key="m.id" :to="`/projects/${m.project_id}/board`"
                        class="flex items-center gap-2 rounded-control px-2 py-1 hover:bg-ink-50">
              <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="m.overdue ? 'bg-rose-500' : 'bg-amber-400'"></span>
              <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ m.name }}</span>
              <span class="shrink-0 text-[10px] text-ink-400">{{ m.project_name }}</span>
              <span class="shrink-0 rounded-pill px-1.5 text-[10px]"
                    :class="m.overdue ? 'bg-rose-50 text-rose-500' : 'bg-amber-50 text-amber-600'">
                {{ m.overdue ? '逾期 ' + (-m.days_left) + ' 天' : (m.days_left === 0 ? '今天' : m.days_left + ' 天后') }}
              </span>
            </RouterLink>
          </div>
          <div v-else class="py-6 text-center text-[12px] text-ink-400">近 7 天没有到期里程碑</div>
        </div>

        <!-- #346 项目健康：未完成 / 逾期 / 本周完成 -->
        <div class="card p-4" :class="colClass('health')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">🩺 项目健康</span>
            <span class="flex items-center gap-1 text-[10px]">
              <span class="rounded-pill bg-rose-50 px-1.5 text-rose-500">红 {{ health.summary?.red ?? 0 }}</span>
              <span class="rounded-pill bg-amber-50 px-1.5 text-amber-600">黄 {{ health.summary?.yellow ?? 0 }}</span>
              <span class="rounded-pill bg-emerald-50 px-1.5 text-emerald-600">绿 {{ health.summary?.green ?? 0 }}</span>
              <button class="rounded-pill px-1 text-[11px] text-ink-300 hover:bg-ink-50" title="刷新" @click="loadHealth">↻</button>
              <CardMenu card-key="health" :size="layoutSize('health')" @size="(s) => setCardSize('health', s)" />
            </span>
          </div>
          <div v-if="cardErrors.health" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.health }}</span>
            <button class="shrink-0 font-medium" @click="loadHealth">重试</button>
          </div>
          <div v-if="health.list?.length" class="mt-1 divide-y divide-ink-50">
            <RouterLink v-for="p in health.list" :key="p.project_id" :to="`/projects/${p.project_id}/board`"
                        class="flex items-center gap-2 py-1.5 hover:bg-ink-50">
              <span class="h-2 w-2 shrink-0 rounded-full" :class="healthDot(p.level)" :title="p.label"></span>
              <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ p.name }}</span>
              <span class="shrink-0 text-[10px] text-ink-400">未完成 {{ p.unfinished }}</span>
              <span class="shrink-0 text-[10px]" :class="p.overdue ? 'text-rose-500' : 'text-ink-400'">逾期 {{ p.overdue }}</span>
              <span class="shrink-0 text-[10px] text-emerald-600">本周完成 {{ p.done_this_week }}</span>
              <span class="tag shrink-0">{{ p.label }}</span>
            </RouterLink>
          </div>
          <div v-else class="py-6 text-center text-[12px] text-ink-400">暂无参与中的项目</div>
        </div>
      </div>
    </section>

    <!-- ================= 学习 ================= -->
    <section class="space-y-2">
      <div class="flex items-center gap-2">
        <button class="flex items-center gap-1.5 text-[13px] font-semibold text-ink-700" @click="toggleGroup('study')">
          <span class="text-[10px] text-ink-400">{{ collapsedGroups.study ? '▸' : '▾' }}</span>
          📚 学习
          <span v-if="collapsedGroups.study" class="text-[11px] font-normal text-ink-300">已折叠</span>
        </button>
        <span class="h-px flex-1 bg-ink-100"></span>
      </div>
      <div v-show="!collapsedGroups.study" class="grid gap-4 lg:grid-cols-2">
        <!-- F658 今日学习卡 -->
        <div class="card p-4" :class="colClass('learning')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">📚 今日学习</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-300">
              <span v-if="stamps.learning">更新于 {{ stamps.learning }}</span>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadLearning">↻</button>
              <CardMenu card-key="learning" :size="layoutSize('learning')" @size="(s) => setCardSize('learning', s)" />
            </span>
          </div>
          <div v-if="cardErrors.learning" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.learning }}</span>
            <button class="shrink-0 font-medium" @click="loadLearning">重试</button>
          </div>
          <template v-if="!learning?.error">
            <div class="mt-1 flex items-end gap-2">
              <div class="text-[24px] font-bold text-brand-600">{{ learning?.minutes ?? 0 }}</div>
              <div class="mb-1 text-[11px] text-ink-400">/ {{ learning?.goal_minutes ?? 60 }} 分钟目标</div>
            </div>
            <div class="mt-2 h-2 overflow-hidden rounded-pill bg-ink-100">
              <div class="h-full rounded-pill bg-brand-500 transition-all"
                   :style="{ width: Math.min(100, learning?.percent || 0) + '%' }"></div>
            </div>
            <div class="mt-2 flex items-center justify-between text-[12px] text-ink-500">
              <span>🔥 连续 <b class="text-ink-800">{{ learning?.streak ?? 0 }}</b> 天</span>
              <span>今日 {{ learning?.sessions ?? 0 }} 次记录</span>
              <span :class="learning?.reached ? 'text-emerald-600' : 'text-amber-500'">
                {{ learning?.reached ? '已达目标' : '还差 ' + Math.max(0, (learning?.goal_minutes || 0) - (learning?.minutes || 0)) + ' 分钟' }}
              </span>
            </div>
            <div v-if="learning?.subjects?.length" class="mt-1 truncate text-[11px] text-ink-400">
              科目：{{ learning.subjects.join('、') }}
            </div>
          </template>
          <div v-else class="mt-3 text-[12px] text-ink-400">学习数据暂不可用（learning 模块未响应）</div>
        </div>

        <!-- #342 14 天产出趋势 + 环比虚线 -->
        <div class="card p-5" :class="colClass('trend')">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-[14px] font-semibold">近 14 天产出</h3>
            <CardMenu card-key="trend" :size="layoutSize('trend')" @size="(s) => setCardSize('trend', s)" />
          </div>
          <div v-if="cardErrors.trend" class="mb-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.trend }}</span>
            <button class="shrink-0 font-medium" @click="loadTrend">重试</button>
          </div>
          <div class="relative flex h-32 items-end gap-1">
            <!-- 上周同期虚线 -->
            <svg v-if="compareSeries.length" class="pointer-events-none absolute inset-0 h-full w-full"
                 viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <polyline v-for="s in compareSeries" :key="s.key" :points="s.points" fill="none"
                        :stroke="s.color" stroke-width="1.5" stroke-dasharray="4 3"
                        vector-effect="non-scaling-stroke" opacity="0.75" />
            </svg>
            <div v-for="(lb, i) in trend.labels" :key="i" class="group flex flex-1 flex-col items-center justify-end gap-0.5">
              <div class="flex w-full items-end justify-center gap-px" :title="`${lb} 笔记${trend.notes[i]} 文件${trend.files[i]} 完成${trend.tasks_done[i]}`">
                <div class="w-1/3 rounded-t bg-brand-400" :style="{ height: barH(trend.notes[i]) }"></div>
                <div class="w-1/3 rounded-t bg-emerald-400" :style="{ height: barH(trend.files[i]) }"></div>
                <div class="w-1/3 rounded-t bg-amber-400" :style="{ height: barH(trend.tasks_done[i]) }"></div>
              </div>
              <span class="text-[9px] text-ink-300">{{ lb }}</span>
            </div>
          </div>
          <div class="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-ink-400">
            <span>■ 笔记</span><span class="text-emerald-400">■ 文件</span><span class="text-amber-400">■ 完成任务</span>
            <span v-if="trendCompare" class="inline-flex items-center gap-1">
              <svg width="18" height="6" aria-hidden="true"><line x1="0" y1="3" x2="18" y2="3" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="3 2" /></svg>
              上周同期
            </span>
          </div>
          <!-- #342 环比增减百分比 -->
          <div v-if="trendChanges.length" class="mt-1.5 flex flex-wrap gap-3 text-[11px]">
            <span v-for="c in trendChanges" :key="c.key" class="inline-flex items-center gap-1">
              <span class="text-ink-500">{{ c.label }}</span>
              <b :class="changeClass(c)">{{ changeArrow(c) }} {{ changeText(c) }}</b>
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- ================= 消息 ================= -->
    <section class="space-y-2">
      <div class="flex items-center gap-2">
        <button class="flex items-center gap-1.5 text-[13px] font-semibold text-ink-700" @click="toggleGroup('im')">
          <span class="text-[10px] text-ink-400">{{ collapsedGroups.im ? '▸' : '▾' }}</span>
          💬 消息
          <span v-if="collapsedGroups.im" class="text-[11px] font-normal text-ink-300">已折叠</span>
        </button>
        <span class="h-px flex-1 bg-ink-100"></span>
      </div>
      <div v-show="!collapsedGroups.im" class="grid gap-4 lg:grid-cols-2">
        <!-- #344 提到我：最近 5 条 @ 我的消息 -->
        <div class="card p-4" :class="colClass('mentions')">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">💬 提到我</span>
            <span class="flex items-center gap-1 text-[11px] text-ink-300">
              <RouterLink to="/im" class="text-brand-600">去消息</RouterLink>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadMentions">↻</button>
              <CardMenu card-key="mentions" :size="layoutSize('mentions')" @size="(s) => setCardSize('mentions', s)" />
            </span>
          </div>
          <div v-if="cardErrors.mentions" class="mt-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.mentions }}</span>
            <button class="shrink-0 font-medium" @click="loadMentions">重试</button>
          </div>
          <div v-if="mentions.length" class="mt-1 space-y-1">
            <button v-for="m in mentions" :key="m.id"
                    class="flex w-full items-start gap-2 rounded-control px-2 py-1 text-left hover:bg-ink-50"
                    @click="openMention(m)">
              <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400"></span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[12px] text-ink-700">{{ m.content }}</span>
                <span class="block text-[10px] text-ink-400">{{ m.sender }} · {{ m.session_name }} · {{ fmtDateTime(m.created_at) }}</span>
              </span>
            </button>
          </div>
          <div v-else class="py-6 text-center text-[12px] text-ink-400">暂无 @ 我的消息</div>
        </div>
      </div>
    </section>

    <!-- ================= 系统 ================= -->
    <section class="space-y-2">
      <div class="flex items-center gap-2">
        <button class="flex items-center gap-1.5 text-[13px] font-semibold text-ink-700" @click="toggleGroup('system')">
          <span class="text-[10px] text-ink-400">{{ collapsedGroups.system ? '▸' : '▾' }}</span>
          🖥️ 系统
          <span v-if="collapsedGroups.system" class="text-[11px] font-normal text-ink-300">已折叠</span>
        </button>
        <span class="h-px flex-1 bg-ink-100"></span>
      </div>
      <div v-show="!collapsedGroups.system" class="grid gap-4 lg:grid-cols-2">
        <!-- F660 存储用量卡：总量 + 类型占比迷你条 -->
        <div class="card p-5" :class="colClass('storage')">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-[13px] font-medium text-ink-700">存储空间</span>
            <span class="flex items-center gap-2 text-[12px] text-ink-500">
              <span>{{ storage.total_text || formatSize(stats.storage_bytes) }} / {{ storage.quota_text || stats.quota_mb + ' MB' }}</span>
              <span v-if="stamps.storage" class="text-[11px] text-ink-300">更新于 {{ stamps.storage }}</span>
              <button class="rounded-pill px-1 text-[12px] hover:bg-ink-50" title="刷新" @click="loadStorage">↻</button>
              <CardMenu card-key="storage" :size="layoutSize('storage')" @size="(s) => setCardSize('storage', s)" />
            </span>
          </div>
          <div v-if="cardErrors.storage" class="mb-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.storage }}</span>
            <button class="shrink-0 font-medium" @click="loadStorage">重试</button>
          </div>
          <div class="h-2.5 overflow-hidden rounded-pill bg-ink-100">
            <div class="h-full rounded-pill bg-brand-500" :style="{ width: Math.min(100, storage.percent || stats.quota_used_pct || 0) + '%' }"></div>
          </div>
          <div v-if="storage.by_kind?.length" class="mt-3">
            <!-- 迷你占比条（手写 flex 分段，不引图表库） -->
            <div class="flex h-2 overflow-hidden rounded-pill bg-ink-100">
              <div v-for="(k, i) in storage.by_kind" :key="k.kind"
                   :title="`${k.kind}: ${k.text} (${k.percent}%)`"
                   :style="{ width: k.percent + '%', background: PALETTE[i % PALETTE.length] }"></div>
            </div>
            <div class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-500">
              <span v-for="(k, i) in storage.by_kind" :key="'lg' + k.kind" class="inline-flex items-center gap-1">
                <span class="inline-block h-2 w-2 rounded-pill" :style="{ background: PALETTE[i % PALETTE.length] }"></span>
                {{ k.kind }} · {{ k.count }} 个 · {{ k.text }} · {{ k.percent }}%
              </span>
            </div>
          </div>
          <div v-else class="mt-2 text-[11px] text-ink-400">
            {{ storage.error ? '存储统计暂不可用' : '暂无文件类型分布' }}
          </div>
        </div>

        <!-- F666 最近动态时间线（#343 模块筛选） -->
        <div class="card p-5" :class="colClass('activity')">
          <div class="mb-2 flex items-center justify-between">
            <h3 class="text-[14px] font-semibold">最近动态</h3>
            <span class="flex items-center gap-2 text-[11px] text-ink-300">
              <span v-if="stamps.activity">更新于 {{ stamps.activity }}</span>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadActivity">↻</button>
              <CardMenu card-key="activity" :size="layoutSize('activity')" @size="(s) => setCardSize('activity', s)" />
            </span>
          </div>
          <div class="mb-2 flex flex-wrap gap-1">
            <button v-for="m in ACTIVITY_CHIPS" :key="m.value || 'all'"
                    class="rounded-pill px-2 py-0.5 text-[11px] transition"
                    :class="activityModule === m.value ? 'bg-brand-500 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
                    @click="setActivityModule(m.value)">{{ m.label }}</button>
          </div>
          <div v-if="cardErrors.activity" class="mb-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.activity }}</span>
            <button class="shrink-0 font-medium" @click="loadActivity">重试</button>
          </div>
          <div v-if="activity.length" class="relative space-y-3 pl-4">
            <div class="absolute bottom-1 left-[3px] top-1 w-px bg-ink-100"></div>
            <button v-for="(a, i) in activity" :key="i"
                    class="relative flex w-full items-start gap-2 text-left hover:bg-ink-50/60"
                    @click="router.push(a.link || '/dashboard')">
              <span class="absolute -left-4 top-1.5 h-2 w-2 rounded-full"
                    :class="i === 0 ? 'bg-brand-500' : 'bg-ink-200'"></span>
              <span class="tag shrink-0">{{ a.label }}</span>
              <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ a.title }}</span>
              <span class="shrink-0 text-[11px] text-ink-300">{{ a.at_text }}</span>
            </button>
          </div>
          <div v-else class="py-6 text-center text-[12px] text-ink-400">
            {{ activityError ? '动态聚合暂不可用' : '暂无最近动态' }}
          </div>
        </div>

        <!-- 最新通知（#333 合并通知直接展示后端合并后的 content） -->
        <div class="card p-5" :class="colClass('notifications')">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-[14px] font-semibold">最新通知</h3>
            <span class="flex items-center gap-2">
              <button class="text-[12px] text-brand-600" @click="app.markAllRead">全部已读</button>
              <CardMenu card-key="notifications" :size="layoutSize('notifications')" @size="(s) => setCardSize('notifications', s)" />
            </span>
          </div>
          <div v-if="app.notifications.length" class="space-y-2">
            <div v-for="n in app.notifications.slice(0, 6)" :key="n.id" class="flex items-start gap-2 rounded-control px-2 py-1.5 hover:bg-ink-50">
              <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" :class="n.is_read ? 'bg-ink-200' : 'bg-brand-500'"></span>
              <div class="min-w-0">
                <div class="truncate text-[13px]">{{ n.title }}</div>
                <div class="whitespace-pre-line text-[11px] text-ink-400">{{ n.content }}</div>
              </div>
              <span class="ml-auto shrink-0 text-[10px] text-ink-300">{{ formatTime(n.created_at) }}</span>
            </div>
          </div>
          <div v-else class="py-6 text-center text-[12px] text-ink-400">暂无通知</div>
        </div>

        <!-- #350 性能监控面板：最近 100 次样本 + 均值与趋势箭头 -->
        <div v-if="latencyStats.samples" class="card p-5" :class="colClass('latency')">
          <div class="mb-2 flex items-center justify-between">
            <h3 class="text-[14px] font-semibold">接口延迟监控</h3>
            <span class="flex items-center gap-2 text-[11px] text-ink-300">
              <span>{{ latencyStats.samples }}/100 次样本</span>
              <button class="text-[12px] text-ink-400 hover:text-rose-500" @click="clearLatency">清空数据</button>
              <CardMenu card-key="latency" :size="layoutSize('latency')" @size="(s) => setCardSize('latency', s)" />
            </span>
          </div>
          <div class="grid grid-cols-3 gap-3">
            <div class="rounded-control bg-ink-50 p-3 text-center">
              <div class="text-[11px] text-ink-500">P50</div>
              <div class="text-[20px] font-bold text-ink-900">{{ latencyStats.p50 }}ms</div>
            </div>
            <div class="rounded-control bg-ink-50 p-3 text-center">
              <div class="text-[11px] text-ink-500">P95</div>
              <div class="text-[20px] font-bold text-amber-500">{{ latencyStats.p95 }}ms</div>
            </div>
            <div class="rounded-control bg-ink-50 p-3 text-center">
              <div class="text-[11px] text-ink-500">P99</div>
              <div class="text-[20px] font-bold text-rose-500">{{ latencyStats.p99 }}ms</div>
            </div>
          </div>
          <div class="mt-2 flex items-center justify-center gap-2 text-[12px]">
            <span class="text-ink-500">平均</span>
            <b class="text-ink-900">{{ latencyStats.avg }}ms</b>
            <span :class="latencyStats.trend > 0 ? 'text-rose-500' : (latencyStats.trend < 0 ? 'text-emerald-600' : 'text-ink-400')">
              {{ latencyStats.trend > 0 ? '↑' : (latencyStats.trend < 0 ? '↓' : '→') }}
              {{ Math.abs(latencyStats.trend) }}ms
            </span>
            <span class="text-[10px] text-ink-300">相对前半段样本</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ================= 个人 ================= -->
    <section class="space-y-2">
      <div class="flex items-center gap-2">
        <button class="flex items-center gap-1.5 text-[13px] font-semibold text-ink-700" @click="toggleGroup('personal')">
          <span class="text-[10px] text-ink-400">{{ collapsedGroups.personal ? '▸' : '▾' }}</span>
          👤 个人
          <span v-if="collapsedGroups.personal" class="text-[11px] font-normal text-ink-300">已折叠</span>
        </button>
        <span class="h-px flex-1 bg-ink-100"></span>
      </div>
      <div v-show="!collapsedGroups.personal" class="grid gap-4 lg:grid-cols-2">
        <!-- #347 每日简报卡：最近一期推送 + 定时推送设置 -->
        <div class="card p-5" :class="colClass('summary')">
          <div class="mb-2 flex items-center justify-between">
            <h3 class="text-[14px] font-semibold">📊 每日简报</h3>
            <span class="flex items-center gap-2 text-[11px] text-ink-300">
              <button class="text-brand-600" @click="pushSummaryNow">立即推送</button>
              <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadSummary">↻</button>
              <CardMenu card-key="summary" :size="layoutSize('summary')" @size="(s) => setCardSize('summary', s)" />
            </span>
          </div>
          <div v-if="cardErrors.summary" class="mb-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.summary }}</span>
            <button class="shrink-0 font-medium" @click="loadSummary">重试</button>
          </div>
          <template v-if="summary">
            <div v-if="summary.latest_push" class="rounded-control bg-ink-50 p-2.5">
              <div class="flex items-center justify-between gap-2 text-[11px]">
                <span class="truncate font-medium text-ink-700">{{ summary.latest_push.title }}</span>
                <span class="shrink-0 text-ink-300">{{ fmtDateTime(summary.latest_push.pushed_at) }}</span>
              </div>
              <div class="mt-1 text-[12px] text-ink-600">{{ summary.latest_push.headline }}</div>
              <div class="mt-1.5 flex flex-wrap gap-1">
                <span v-for="it in (summary.latest_push.items || [])" :key="it.key" class="tag bg-white">
                  {{ it.label }} {{ it.value }}{{ it.unit }}
                </span>
              </div>
            </div>
            <div v-else class="rounded-control bg-ink-50 p-2.5 text-[12px] text-ink-500">
              暂无历史简报。今日：{{ summary.headline }}
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-2 border-t border-ink-50 pt-2 text-[11px] text-ink-500">
              <label class="flex items-center gap-1">
                <input v-model="dailyCfg.enabled" type="checkbox" /> 每日推送
              </label>
              <input v-model="dailyCfg.time" type="time" class="input w-24 py-0.5 text-[11px]" aria-label="每日简报推送时间" />
              <button class="btn-outline px-2 py-0.5 text-[11px]" @click="saveDailyPush">保存</button>
              <span v-if="summary.schedule?.next_push_at" class="text-ink-300">下次 {{ fmtDateTime(summary.schedule.next_push_at) }}</span>
            </div>
          </template>
          <div v-else class="py-4 text-center text-[12px] text-ink-400">简报加载中…</div>
        </div>

        <div class="card p-5" :class="colClass('notes')">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-[14px] font-semibold">最近编辑的笔记</h3>
            <span class="flex items-center gap-2">
              <RouterLink to="/notes" class="text-[12px] text-brand-600">全部</RouterLink>
              <CardMenu card-key="notes" :size="layoutSize('notes')" @size="(s) => setCardSize('notes', s)" />
            </span>
          </div>
          <div v-if="cardErrors.notes" class="mb-2 flex items-center gap-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
            <span class="min-w-0 flex-1 truncate">{{ cardErrors.notes }}</span>
            <button class="shrink-0 font-medium" @click="loadNotes">重试</button>
          </div>
          <div v-if="recentNotes.length" class="space-y-2">
            <RouterLink v-for="n in recentNotes" :key="n.id" to="/notes" class="flex items-center justify-between rounded-control px-2 py-1.5 hover:bg-ink-50">
              <span class="truncate text-[13px]">{{ n.title }}</span>
              <span class="shrink-0 text-[11px] text-ink-400">{{ formatTime(n.updated_at) }}</span>
            </RouterLink>
          </div>
          <div v-else class="py-6 text-center text-[12px] text-ink-400">还没有笔记</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { coreApi, dashApi, noteApi } from '../api'
import { dashx } from '../api/dashx'
import { notifyx } from '../api/notifyx'
import { officex } from '../api/officex'
import { formatSize, formatTime } from '../utils/format'

// localStorage 可能存着损坏的 JSON（手工改过/写入中断），解析失败时清掉回落默认值，
// 否则首页会在 setup 阶段直接抛错变成白屏
function loadJson(key, fallback = null) {
  const raw = localStorage.getItem(key)
  if (!raw) return fallback
  try {
    return JSON.parse(raw)
  } catch {
    localStorage.removeItem(key)
    return fallback
  }
}

const router = useRouter()
const user = useUserStore()
const app = useAppStore()
const stats = ref({})
const todo = ref({})
const trend = ref({})
const recentNotes = ref([])
const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })

// ---------------- #331/#332 卡片尺寸、分组与折叠 ----------------
const GROUP_LABELS = { work: '工作', study: '学习', system: '系统', personal: '个人', im: '消息' }
const DEFAULT_CARDS = [
  { key: 'focus', group: 'work', size: 'full' },
  { key: 'due', group: 'work', size: 'half' },
  { key: 'schedule', group: 'work', size: 'half' },
  { key: 'todo', group: 'work', size: 'full' },
  { key: 'stats', group: 'work', size: 'full' },
  { key: 'milestones', group: 'work', size: 'half' },
  { key: 'health', group: 'work', size: 'full' },
  { key: 'learning', group: 'study', size: 'half' },
  { key: 'trend', group: 'study', size: 'full' },
  { key: 'mentions', group: 'im', size: 'half' },
  { key: 'storage', group: 'system', size: 'half' },
  { key: 'activity', group: 'system', size: 'full' },
  { key: 'notifications', group: 'system', size: 'half' },
  { key: 'latency', group: 'system', size: 'half' },
  { key: 'summary', group: 'personal', size: 'full' },
  { key: 'notes', group: 'personal', size: 'half' },
]
const LAYOUT_KEY = 'dashboard_layout_v2'
const layoutCards = ref(DEFAULT_CARDS.map((c) => ({ ...c })))
const collapsedGroups = reactive({
  work: false,
  study: false,
  system: false,
  personal: false,
  im: false,
  ...(loadJson('dashboard_groups_collapsed', {}) || {}),
})

function layoutSize(key) {
  return layoutCards.value.find((c) => c.key === key)?.size || 'half'
}
function colClass(key) {
  return layoutSize(key) === 'full' ? 'lg:col-span-2' : ''
}
function mergeLayout(cards) {
  const byKey = new Map((cards || []).filter((c) => c && c.key).map((c) => [c.key, c]))
  layoutCards.value = DEFAULT_CARDS.map((c) => ({ ...c, ...(byKey.get(c.key) || {}) }))
}
async function loadLayout() {
  const local = loadJson(LAYOUT_KEY)
  if (Array.isArray(local)) mergeLayout(local)
  try {
    const r = await dashx.layout()
    if (Array.isArray(r.layout?.cards) && r.layout.cards.length) mergeLayout(r.layout.cards)
  } catch (e) { /* 服务端不可用时沿用本地布局 */ }
}
function persistLayout() {
  const cards = layoutCards.value.map(({ key, size, group }) => ({ key, size, group }))
  localStorage.setItem(LAYOUT_KEY, JSON.stringify(cards))
  dashx.saveLayout({ cards }).catch(() => {})
}
function setCardSize(key, size) {
  if (size !== 'half' && size !== 'full') return
  layoutCards.value = layoutCards.value.map((c) => (c.key === key ? { ...c, size } : c))
  persistLayout()
}
function toggleGroup(group) {
  collapsedGroups[group] = !collapsedGroups[group]
  localStorage.setItem('dashboard_groups_collapsed', JSON.stringify(collapsedGroups))
}

// 轻量卡片菜单：半宽/全宽切换（#331）
const CardMenu = defineComponent({
  name: 'CardMenu',
  props: { cardKey: { type: String, required: true }, size: { type: String, default: 'half' } },
  emits: ['size'],
  setup(props, { emit }) {
    const open = ref(false)
    const close = () => (open.value = false)
    onMounted(() => document.addEventListener('click', close))
    onBeforeUnmount(() => document.removeEventListener('click', close))
    return () => h('div', { class: 'relative inline-flex' }, [
      h('button', {
        type: 'button',
        class: 'rounded-pill px-1 text-[13px] leading-none text-ink-300 hover:bg-ink-50 hover:text-ink-600',
        title: '卡片设置',
        'aria-label': '卡片设置',
        onClick: (e) => { e.stopPropagation(); open.value = !open.value },
      }, '⋯'),
      open.value
        ? h('div', { class: 'absolute right-0 top-5 z-30 w-24 rounded-card border border-ink-100 bg-white p-1 shadow-pop' },
          [['half', '半宽'], ['full', '全宽']].map(([value, label]) =>
            h('button', {
              key: value,
              type: 'button',
              class: [
                'block w-full rounded-control px-2 py-1 text-left text-[12px] hover:bg-ink-50',
                props.size === value ? 'font-medium text-brand-600' : 'text-ink-600',
              ],
              onClick: (e) => { e.stopPropagation(); open.value = false; emit('size', value) },
            }, label)
          ))
        : null,
    ])
  },
})

// ---------------- #349 单卡错误态 ----------------
const cardErrors = reactive({})
function setCardError(key, e) {
  cardErrors[key] = e?.response?.data?.message || e?.message || '加载失败'
}
function clearCardError(key) {
  delete cardErrors[key]
}

// ---------------- F665 首页公告横幅 ----------------
const banner = ref(null)
async function loadBanner() {
  try {
    const r = await coreApi.announcements()
    const list = r.list || []
    banner.value = list.find((a) => a.is_pinned && !a.is_read) || list.find((a) => a.is_pinned) || null
  } catch (e) { banner.value = null }
}
async function dismissBanner() {
  const b = banner.value
  banner.value = null
  if (b && !b.is_read) {
    try { await coreApi.readAnnouncement(b.id) } catch (e) { /* ignore */ }
  }
}

// ---------------- F657–F659 / F660 / F666 今日卡片与动态 ----------------
const due = ref(null)
const learning = ref(null)
const schedule = ref(null)
const storage = ref({})
const activity = ref([])
const activityError = ref(false)
const scheduleError = ref(false)
const activityModule = ref('')
const ACTIVITY_CHIPS = [
  { value: '', label: '全部' },
  { value: 'notes', label: '笔记' },
  { value: 'files', label: '文件' },
  { value: 'tasks', label: '任务' },
  { value: 'notifications', label: '通知' },
  { value: 'messages', label: '消息' },
]
// F667 卡片数据更新时间戳
const stamps = reactive({ focus: '', due: '', learning: '', schedule: '', storage: '', activity: '' })

function stampOf(iso) {
  if (!iso) return new Date().toLocaleTimeString('zh-CN', { hour12: false })
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('zh-CN', { hour12: false })
}

async function loadStats() {
  try {
    stats.value = await dashApi.stats()
    clearCardError('stats')
  } catch (e) { setCardError('stats', e) }
}
async function loadTodo() {
  try {
    todo.value = await dashApi.todoAggregate()
    clearCardError('todo')
  } catch (e) { setCardError('todo', e) }
}
async function loadTrend() {
  try {
    trend.value = await dashx.personalTrend({ compare: 1 })
    clearCardError('trend')
  } catch (e) { setCardError('trend', e) }
}
async function loadNotes() {
  try {
    const r = await noteApi.recent()
    recentNotes.value = r.list || []
    clearCardError('notes')
  } catch (e) { setCardError('notes', e) }
}
async function loadDue() {
  try {
    const r = await dashx.todayDue(true)
    due.value = r
    stamps.due = stampOf(r.fetched_at)
    clearCardError('due')
  } catch (e) {
    setCardError('due', e)
    due.value = due.value || { total: 0, groups: [], errors: [{ module: 'all' }] }
  }
}
// ---------------- S26-360 今日聚焦 ----------------
const focus = ref(null)
const focusAgenda = computed(() => (focus.value?.agenda || []).slice(0, 4))
const focusTodos = computed(() => (focus.value?.todos || []).slice(0, 4))
const focusApprovals = computed(() => (focus.value?.approvals?.items || []).slice(0, 3))
async function loadFocus() {
  try {
    const r = await officex.focusToday()
    focus.value = r
    stamps.focus = stampOf()
    clearCardError('focus')
  } catch (e) {
    // 单卡失败：卡片内展示 message + 重试，其余卡片照常渲染
    setCardError('focus', e)
    app.toastMsg(e?.message || '今日聚焦加载失败', 'error')
  }
}

async function loadLearning() {
  try {
    const r = await dashx.todayLearning()
    learning.value = r
    stamps.learning = stampOf(r.fetched_at)
    if (r.error) setCardError('learning', { message: r.message || '学习数据加载失败' })
    else clearCardError('learning')
  } catch (e) {
    setCardError('learning', e)
    learning.value = { error: 'unavailable', minutes: 0, streak: 0, goal_minutes: 60, percent: 0 }
  }
}
async function loadSchedule() {
  try {
    const r = await dashx.todaySchedule()
    schedule.value = r
    scheduleError.value = !!(r.errors && r.errors.length)
    stamps.schedule = stampOf(r.fetched_at)
    if (scheduleError.value) setCardError('schedule', { message: '日程/值班部分模块加载失败' })
    else clearCardError('schedule')
  } catch (e) {
    setCardError('schedule', e)
    scheduleError.value = true
    schedule.value = { meetings: { items: [] }, duty: { items: [] } }
  }
}
async function loadStorage() {
  try {
    const r = await dashx.storageUsage()
    storage.value = r
    stamps.storage = stampOf(r.fetched_at)
    if (r.error) setCardError('storage', { message: r.message || '存储用量加载失败' })
    else clearCardError('storage')
  } catch (e) {
    setCardError('storage', e)
    storage.value = { error: 'unavailable', by_kind: [] }
  }
}
async function loadActivity() {
  try {
    const r = await dashx.recentActivity(activityModule.value)
    activity.value = r.list || []
    activityError.value = !!(r.errors && r.errors.length)
    stamps.activity = stampOf(r.fetched_at)
    if (activityError.value) setCardError('activity', { message: '部分动态模块加载失败' })
    else clearCardError('activity')
  } catch (e) {
    setCardError('activity', e)
    activityError.value = true
    activity.value = []
  }
}
function setActivityModule(module) {
  activityModule.value = module
  loadActivity()
}

// ---------------- #348 已逾期分组与一键延期 ----------------
const postponing = ref('')
const dueOverdueItems = computed(() => {
  const out = []
  for (const g of due.value?.groups || []) {
    for (const it of (g.overdue_items || [])) {
      out.push({ ...it, kind: g.key, groupLabel: g.label })
    }
  }
  return out
})
async function postponeDue(item) {
  const token = `${item.kind}-${item.id}`
  postponing.value = token
  try {
    await dashx.postponeDue(item.kind, item.id, 1)
    app.toastMsg('已延期一天')
    await loadDue()
  } catch (e) {
    app.toastMsg(e.message || '延期失败', 'error')
  } finally {
    postponing.value = ''
  }
}

const dueItems = computed(() => {
  const out = []
  for (const g of due.value?.groups || []) {
    for (const it of (g.items || []).slice(0, 2)) {
      out.push({ key: `${g.key}-${it.id}`, title: it.title })
    }
  }
  return out.slice(0, 4)
})
const scheduleMeetings = computed(() => (schedule.value?.meetings?.items || []).slice(0, 3))
const scheduleDuty = computed(() => (schedule.value?.duty?.items || []).slice(0, 2))
const PALETTE = ['#6366f1', '#10b981', '#f59e0b', '#f43f5e', '#0ea5e9', '#8b5cf6', '#14b8a6', '#94a3b8']

function fmtClock(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function fmtDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${d.getMonth() + 1}-${d.getDate()} ${hh}:${mm}`
}

// ---------------- #344 提到我 ----------------
const mentions = ref([])
async function loadMentions() {
  try {
    const r = await dashx.mentions(5)
    mentions.value = r.list || []
    clearCardError('mentions')
  } catch (e) { setCardError('mentions', e) }
}
function openMention(m) {
  if (!m?.session_id) return
  // 站内消息路由只注册了 /im，带上会话与消息参数；Chat 页后续可通过 route.query 定位
  router.push({ path: '/im', query: { session: m.session_id, ...(m.message_id ? { message: m.message_id } : {}) } })
}

// ---------------- #345 里程碑 ----------------
const milestones = ref([])
async function loadMilestones() {
  try {
    const r = await dashx.milestones(7, true)
    milestones.value = r.list || []
    clearCardError('milestones')
  } catch (e) { setCardError('milestones', e) }
}

// ---------------- #346 项目健康 ----------------
const health = ref({ list: [], summary: {} })
const healthDot = (level) => ({ red: 'bg-rose-500', yellow: 'bg-amber-400', green: 'bg-emerald-500' }[level] || 'bg-ink-300')
async function loadHealth() {
  try {
    const r = await dashx.projectHealth(20)
    health.value = { list: r.list || [], summary: r.summary || {} }
    clearCardError('health')
  } catch (e) { setCardError('health', e) }
}

// ---------------- #347 每日简报 ----------------
const summary = ref(null)
const dailyCfg = reactive({ enabled: false, time: '18:00' })
async function loadSummary() {
  try {
    const r = await dashx.dailySummary()
    summary.value = r
    if (r.schedule) {
      dailyCfg.enabled = !!r.schedule.enabled
      dailyCfg.time = r.schedule.time || '18:00'
    }
    clearCardError('summary')
  } catch (e) { setCardError('summary', e) }
}
async function saveDailyPush() {
  try {
    await notifyx.saveSettings({
      daily_push_enabled: dailyCfg.enabled,
      daily_push_time: dailyCfg.time || null,
    })
    app.toastMsg('每日简报设置已保存')
    await loadSummary()
  } catch (e) {
    app.toastMsg(e.message || '保存失败', 'error')
  }
}
async function pushSummaryNow() {
  try {
    const r = await dashx.pushDailySummary({ force: 1 })
    app.toastMsg(r.suppressed ? '已推送（当前免打扰）' : '已发送每日简报')
    await loadSummary()
    app.refreshNotificationsSoon(0)
  } catch (e) {
    app.toastMsg(e.message || '推送失败', 'error')
  }
}

// ---------------- #342 环比对比 ----------------
const trendCompare = computed(() => trend.value?.compare || null)
const trendMax = computed(() => {
  const cur = [trend.value.notes, trend.value.files, trend.value.tasks_done].filter(Array.isArray).flat()
  const prev = trendCompare.value
    ? [trendCompare.value.notes, trendCompare.value.files, trendCompare.value.tasks_done].filter(Array.isArray).flat()
    : []
  return Math.max(1, ...cur, ...prev)
})
function barH(v) {
  return Math.max(2, Math.round(((v || 0) / trendMax.value) * 100)) + 'px'
}
function linePoints(series) {
  if (!Array.isArray(series) || series.length < 2) return ''
  return series.map((v, i) => {
    const x = (i / (series.length - 1)) * 100
    const y = 96 - Math.min(96, ((v || 0) / trendMax.value) * 92)
    return `${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
}
const compareSeries = computed(() => {
  const c = trendCompare.value
  if (!c) return []
  return [
    { key: 'notes', color: '#38bdf8', points: linePoints(c.notes) },
    { key: 'files', color: '#34d399', points: linePoints(c.files) },
    { key: 'tasks', color: '#fbbf24', points: linePoints(c.tasks_done) },
  ].filter((s) => s.points)
})
const trendChanges = computed(() => {
  const ch = trendCompare.value?.change
  if (!ch) return []
  return [
    { key: 'notes', label: '笔记', ...ch.notes },
    { key: 'files', label: '文件', ...ch.files },
    { key: 'tasks', label: '完成任务', ...ch.tasks_done },
  ].filter((c) => c && c.key)
})
function changeText(c) {
  if (c.percent == null) return c.current > 0 ? '新增' : '持平'
  return `${c.percent > 0 ? '+' : ''}${c.percent}%`
}
function changeArrow(c) {
  if (c.percent == null) return c.current > 0 ? '↑' : '→'
  return c.percent > 0 ? '↑' : (c.percent < 0 ? '↓' : '→')
}
function changeClass(c) {
  if (c.percent == null) return c.current > 0 ? 'text-emerald-600' : 'text-ink-400'
  if (c.percent > 0) return 'text-emerald-600'
  return c.percent < 0 ? 'text-rose-500' : 'text-ink-400'
}

// #53 拖拽排序（F668：同步服务端，跨浏览器一致）
let dragLabel = null
const cardOrder = ref(loadJson('dashboard_card_order'))
async function loadCardOrder() {
  try {
    const r = await dashx.cardOrder()
    if (r.order && r.order.length) {
      cardOrder.value = r.order
      localStorage.setItem('dashboard_card_order', JSON.stringify(r.order))
    }
  } catch (e) { /* 服务端不可用时沿用本地顺序 */ }
}

const statCards = computed(() => [
  { label: '我的文件', value: stats.value.files ?? '-', note: `${formatSize(stats.value.storage_bytes || 0)} 已用` },
  { label: '我的笔记', value: stats.value.notes ?? '-', note: `${stats.value.folders ?? 0} 个文件夹` },
  { label: '参与项目', value: stats.value.projects ?? '-', note: `${stats.value.my_tasks ?? 0} 个进行中任务` },
  { label: '收藏文件', value: todo.value.starred_files ?? '-', note: `置顶笔记 ${todo.value.pinned_notes ?? 0}` },
])
const orderedStatCards = computed(() => {
  if (!cardOrder.value) return statCards.value
  return [...statCards.value].sort((a, b) => {
    const ia = cardOrder.value.indexOf(a.label)
    const ib = cardOrder.value.indexOf(b.label)
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib)
  })
})
function onDragStart(e, label) { dragLabel = label }
function onDrop(e, targetLabel) {
  if (!dragLabel || dragLabel === targetLabel) return
  const order = statCards.value.map(c => c.label)
  const from = order.indexOf(dragLabel)
  const to = order.indexOf(targetLabel)
  order.splice(to, 0, order.splice(from, 1)[0])
  cardOrder.value = order
  localStorage.setItem('dashboard_card_order', JSON.stringify(order))
  // F668：同步到服务端，换浏览器登录后顺序一致（失败静默，本地已保存）
  dashx.saveCardOrder(order).catch(() => {})
}

// #97 快捷入口 + F664 emoji 图标选择
const editingQuick = ref(false)
const newQuick = reactive({ label: '', url: '', icon: '🔗' })
const defaultQuicks = [
  { icon: '📁', label: '文件', url: '/files' },
  { icon: '📝', label: '笔记', url: '/notes' },
  { icon: '📋', label: '项目', url: '/projects' },
  { icon: '💬', label: '消息', url: '/im' },
  { icon: '🔍', label: '搜索', url: '/search' },
]
const quickLinks = ref(loadJson('quick_links') || defaultQuicks)
// F25：快捷入口允许填外链。RouterLink 会把 "https://x" 当成站内路径拼到 #/ 后面，必须分流。
const isExternalUrl = (url) => /^https?:\/\//i.test(String(url || '').trim())
function normalizeQuickUrl(raw) {
  const u = String(raw || '').trim()
  if (!u) return ''
  if (/^https?:\/\//i.test(u)) return u
  if (u.startsWith('/')) return u
  // 形如 www.example.com / example.com 的裸域名补 https，其余按站内路径处理
  if (/^[\w-]+(\.[\w-]+)+([/?#].*)?$/.test(u)) return 'https://' + u
  return '/' + u
}
const EMOJIS = ['📁', '📝', '📋', '💬', '🔍', '🏠', '📊', '🗓️', '✉️', '🧮',
                '🌐', '✨', '🧹', '📚', '🎵', '🎨', '📅', '✅', '❤️', '⭐',
                '🔥', '💡', '🚀', '📌', '📈', '📉', '🗂️', '🗃️', '🕒', '🎯']
const pickingFor = ref(null)
function openEmojiPicker(target) {
  if (!editingQuick.value && target !== 'new') editingQuick.value = true
  pickingFor.value = pickingFor.value === target ? null : target
}
function setIcon(target, emoji) {
  if (target === 'new') newQuick.icon = emoji
  else if (quickLinks.value[target]) quickLinks.value[target].icon = emoji
  pickingFor.value = null
  saveQuick()
}
function saveQuick() { localStorage.setItem('quick_links', JSON.stringify(quickLinks.value)) }
function addQuick() {
  if (!newQuick.label || !newQuick.url) return
  const url = normalizeQuickUrl(newQuick.url)
  if (!url) return
  quickLinks.value.push({ icon: newQuick.icon || '🔗', label: newQuick.label, url })
  newQuick.label = ''; newQuick.url = ''; newQuick.icon = '🔗'
  saveQuick()
}
function removeQuick(q) {
  quickLinks.value = quickLinks.value.filter(x => x !== q)
  saveQuick()
}

// #94/#350 性能监控：最近 100 次样本持久化，展示均值与趋势箭头
const EMPTY_LATENCY = { samples: 0, p50: 0, p95: 0, p99: 0, avg: 0, trend: 0 }
const latencyStats = ref({ ...EMPTY_LATENCY })
function computeLatency() {
  try {
    let samples = JSON.parse(localStorage.getItem('api_latency_samples') || '[]')
    if (!Array.isArray(samples) || !samples.length) return
    if (samples.length > 100) {
      samples = samples.slice(-100)
      localStorage.setItem('api_latency_samples', JSON.stringify(samples))
    }
    const durations = samples.map((s) => Number(s.duration) || 0).sort((a, b) => a - b)
    const p = (pct) => durations[Math.max(0, Math.ceil(durations.length * pct) - 1)] || 0
    const avg = Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
    const half = Math.floor(samples.length / 2)
    const mean = (list) => (list.length ? list.reduce((a, s) => a + (Number(s.duration) || 0), 0) / list.length : 0)
    const trendDelta = Math.round(mean(samples.slice(half)) - mean(samples.slice(0, half)))
    latencyStats.value = { samples: samples.length, p50: p(0.5), p95: p(0.95), p99: p(0.99), avg, trend: trendDelta }
  } catch (e) { /* ignore */ }
}
function clearLatency() {
  localStorage.removeItem('api_latency_samples')
  latencyStats.value = { ...EMPTY_LATENCY }
}

onMounted(async () => {
  // 通知/未读由全局 store 统一拉取并合并，避免与 App.vue 重复请求
  app.refreshNotificationsSoon(0)
  // #349 单卡失败不影响其他卡片：所有加载器各自兜底，并用 allSettled 汇总
  await Promise.allSettled([
    loadStats(),
    loadTodo(),
    loadTrend(),
    loadNotes(),
    loadBanner(),
    loadFocus(),
    loadDue(),
    loadLearning(),
    loadSchedule(),
    loadStorage(),
    loadActivity(),
    loadCardOrder(),
    loadLayout(),
    loadMentions(),
    loadMilestones(),
    loadHealth(),
    loadSummary(),
  ])
  computeLatency()
})
</script>
