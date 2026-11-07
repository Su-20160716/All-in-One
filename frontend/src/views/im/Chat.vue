<template>
  <div class="flex h-[calc(100vh-110px)] gap-4">
    <!-- 会话列表 -->
    <div class="card flex w-72 shrink-0 flex-col">
      <div class="flex items-center gap-2 border-b border-ink-100 p-3">
        <input v-model="keyword" class="input flex-1" placeholder="搜索会话…" @keyup.enter="loadSessions" />
        <button class="btn-ghost px-2" title="待办面板" @click="toggleTodoPanel">✅</button>
        <button class="btn-primary px-2.5" title="发起聊天" @click="openNew">＋</button>
      </div>
      <div class="flex items-center gap-1 border-b border-ink-100 px-2 py-1.5 text-[11px]">
        <button class="rounded-pill px-2 py-0.5" :class="!showArchived?'bg-brand-600 text-white':'text-ink-500'" @click="showArchived=false; loadSessions()">会话</button>
        <button class="rounded-pill px-2 py-0.5" :class="showArchived?'bg-brand-600 text-white':'text-ink-500'" @click="showArchived=true; loadSessions()">归档</button>
        <!-- #311 @我聚合入口 -->
        <button class="ml-auto rounded-pill px-2 py-0.5 text-brand-600 hover:bg-brand-50" title="@我" @click="openMentions">@我</button>
      </div>
      <!-- #315 会话标签筛选 chips（多选并集 / 可清除） -->
      <div v-if="tags.length" class="flex flex-wrap items-center gap-1 border-b border-ink-100 px-2 py-1.5">
        <button class="rounded-pill px-1.5 py-0.5 text-[10px]" :class="!activeTags.length?'bg-brand-600 text-white':'text-ink-500 hover:bg-ink-50'" @click="clearTags">全部</button>
        <button v-for="t in tags" :key="t" class="rounded-pill px-1.5 py-0.5 text-[10px]" :class="activeTags.includes(t)?'bg-brand-600 text-white':'bg-ink-100 text-ink-600 hover:bg-ink-200'" @click="toggleTag(t)">{{ t }}</button>
      </div>
      <div class="flex-1 overflow-y-auto">
        <div v-for="s in sessions" :key="s.id" class="flex cursor-pointer items-center gap-2.5 border-b border-ink-50 px-3 py-2.5"
          :class="[activeSession?.id === s.id ? 'bg-brand-50/60' : 'hover:bg-ink-50/60', pinDragId === s.id ? 'opacity-40' : '']"
          :draggable="!!s.is_pinned" :title="s.is_muted ? muteText(s) : (s.is_pinned ? '拖动可调整置顶顺序' : '')"
          @dragstart="onPinDragStart(s)" @dragend="onPinDragEnd" @dragover.prevent @drop="onPinDrop(s)" @click="openSession(s)">
          <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-100 text-[13px] font-semibold text-brand-700">{{ avatarText(s) }}</div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1 truncate text-[13px] font-medium">
              <span v-if="s.is_pinned">📌</span><span v-if="s.is_muted">🔕</span>
              <span class="truncate">{{ sessionName(s) }}</span>
              <span v-for="t in (s.tags || [])" :key="t" class="rounded-pill bg-ink-100 px-1 text-[9px] font-normal text-ink-500">{{ t }}</span>
            </div>
            <!-- #316 有草稿时显示 [草稿] 摘要，未读红点仍然保留；#326 显示免打扰剩余时间 -->
            <div class="flex items-center gap-1 truncate text-[11px]" :class="s.draft_summary ? 'text-brand-500' : 'text-ink-400'">
              <span class="truncate">{{ s.draft_summary ? `[草稿] ${s.draft_summary}` : lastText(s) }}</span>
              <span v-if="s.is_muted && s.mute_until" class="shrink-0 text-amber-500">{{ muteLeft(s) }}</span>
            </div>
          </div>
          <div class="shrink-0 text-right">
            <div v-if="s.unread" class="grid h-4 min-w-4 place-items-center rounded-pill px-1 text-[10px] font-medium" :class="s.is_muted ? 'bg-ink-300 text-white' : 'bg-rose-500 text-white'">{{ s.unread }}</div>
          </div>
        </div>
        <div v-if="!sessions.length" class="py-10 text-center text-[12px] text-ink-400">{{ showArchived?'暂无归档会话':'暂无会话' }}</div>
      </div>
    </div>

    <!-- 聊天区 -->
    <div class="card flex min-w-0 flex-1 flex-col">
      <template v-if="activeSession">
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-2.5">
          <div>
            <span class="text-[14px] font-semibold">{{ sessionName(activeSession) }}</span>
            <span class="ml-2 text-[11px] text-ink-400">{{ activeSession.type === 'group' ? activeSession.member_count + ' 人群' : '单聊' }}</span>
            <span v-if="typing" class="ml-2 text-[11px] text-brand-500">{{ typing }} 正在输入…</span>
          </div>
          <div class="flex flex-wrap items-center justify-end gap-1">
            <!-- #317 公告入口：未读时显示红点，点开即标记已读 -->
            <button v-if="activeSession.type === 'group'" class="btn-ghost px-2 text-[12px]" @click="openAnnouncement">
              公告<span v-if="ann.unread" class="ml-0.5 inline-block h-1.5 w-1.5 rounded-full bg-rose-500 align-top"></span>
            </button>
            <button class="btn-ghost px-2 text-[12px]" title="搜索消息" @click="openSearch">🔍</button>
            <button class="btn-ghost px-2 text-[12px]" @click="openExport">⬇ 导出</button>
            <button class="btn-ghost px-2 text-[12px]" @click="openKeyword">关键词</button>
            <button class="btn-ghost px-2 text-[12px]" :class="activeSession.is_pinned ? 'text-brand-600' : ''" @click="togglePin">{{ activeSession.is_pinned ? '取消置顶' : '置顶' }}</button>
            <!-- #326 免打扰菜单：1 小时 / 8 小时 / 明天 / 关闭 -->
            <div class="relative">
              <button class="btn-ghost px-2 text-[12px]" :class="activeSession.is_muted ? 'text-amber-600' : ''" @click="showMute = !showMute">{{ muteLabel(activeSession) }}</button>
              <div v-if="showMute" class="absolute right-0 z-20 mt-1 w-44 rounded-card border border-ink-100 bg-white p-1 text-[12px] shadow-pop">
                <button v-for="opt in muteOptions" :key="opt.value" class="block w-full rounded-control px-2 py-1.5 text-left hover:bg-ink-50" @click="setMute(opt.value)">{{ opt.label }}</button>
                <div class="border-t border-ink-50 px-2 py-1 text-[10px] text-ink-400">{{ activeSession.is_muted ? muteText(activeSession) : '当前未免打扰' }}</div>
              </div>
            </div>
            <button class="btn-ghost px-2 text-[12px]" @click="openTags">标签</button>
            <button class="btn-ghost px-2 text-[12px]" @click="toggleArchiveSession">{{ activeSession.is_archived ? '取消归档' : '归档' }}</button>
            <button v-if="activeSession.type === 'group'" class="btn-ghost px-2 text-[12px]" @click="openGroup">群管理</button>
            <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="leave">退出</button>
          </div>
        </div>

        <!-- 置顶消息区 -->
        <div v-if="pinned.length" class="border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[12px]">
          <span class="font-medium text-amber-700">📌 置顶</span>
          <div v-for="p in pinned" :key="p.id" class="mt-0.5 flex items-center gap-1 text-ink-600">
            <span class="truncate">{{ p.sender_name }}: {{ p.content }}</span>
            <button class="text-ink-400 hover:text-rose-500" @click="unpin(p)">×</button>
          </div>
        </div>

        <div ref="msgBox" class="flex-1 space-y-3 overflow-y-auto bg-ink-50/40 p-4">
          <template v-for="m in messages" :key="m.id">
            <!-- #313 首条未读分割线 -->
            <div v-if="unreadDivider === m.id" class="flex items-center gap-2 py-1 text-[11px] text-rose-500">
              <div class="h-px flex-1 bg-rose-200"></div>以下为新消息<div class="h-px flex-1 bg-rose-200"></div>
            </div>
            <div :id="'msg-' + m.id" class="group flex" :class="m.sender === myId ? 'justify-end' : 'justify-start'">
              <div class="max-w-[70%]">
                <div v-if="m.sender !== myId" class="mb-0.5 text-[11px] text-ink-400">{{ m.sender_name }}</div>
                <!-- #321 引用块可点击跳转到原消息 -->
                <button v-if="m.reply_to_info" class="mb-1 w-full rounded-control border-l-2 border-brand-300 bg-white/70 px-2 py-1 text-left text-[11px] text-ink-500 hover:bg-brand-50/70"
                  title="定位原消息" @click="jumpToQuote(m)">
                  回复 {{ m.reply_to_info.sender_name }}：{{ m.reply_to_info.content }}
                </button>
                <div class="relative rounded-card px-3 py-2 text-[13px] leading-relaxed"
                  :class="[m.sender === myId ? 'bg-brand-600 text-white' : 'bg-white text-ink-800 shadow-card', m.failed ? 'opacity-70 ring-1 ring-rose-400' : '', highlightId === m.id ? 'ring-2 ring-amber-400' : '']">
                  <span v-if="m.is_recalled" class="italic opacity-70">消息已撤回</span>
                  <template v-else>
                    <!-- #322 超过 300 字折叠为 8 行，展开状态按消息 id 记忆 -->
                    <div class="chat-md overflow-hidden" :style="collapseStyle(m)" v-html="renderContent(m)"></div>
                    <!-- #323 图片附件缩略图（160px） -->
                    <div v-if="imageAtts(m).length" class="mt-1 flex flex-wrap gap-1">
                      <img v-for="(a, i) in imageAtts(m)" :key="'img' + i" :src="a.url" :alt="a.name || '图片'"
                        class="h-40 w-40 cursor-pointer rounded-control object-cover" loading="lazy" @click.stop="openLightbox(m, i)" />
                    </div>
                    <div v-if="fileAtts(m).length" class="mt-1 space-y-0.5">
                      <a v-for="(a, i) in fileAtts(m)" :key="'file' + i" :href="a.url" target="_blank" rel="noopener" class="block truncate text-[12px] underline" @click.stop>📎 {{ a.name || '附件' }}</a>
                    </div>
                    <button v-if="isLong(m)" class="mt-1 text-[11px] underline opacity-80" @click.stop="toggleExpand(m.id)">{{ expanded.has(m.id) ? '收起' : '展开全文' }}</button>
                    <span v-if="m.forward_from" class="ml-1 text-[10px] opacity-70">（转发）</span>
                    <!-- #308 译文折叠显示在气泡下方，可切换原文 / 译文 -->
                    <div v-if="translations[m.id]" class="mt-1 border-t border-current/20 pt-1 text-[12px]">
                      <div class="flex items-center gap-1 text-[10px] opacity-70">
                        <span>译文（{{ translations[m.id].target_lang }}）</span>
                        <button class="ml-auto underline" @click.stop="toggleTranslation(m.id)">{{ translations[m.id].showOriginal ? '看译文' : '看原文' }}</button>
                        <button class="underline" @click.stop="closeTranslation(m.id)">收起</button>
                      </div>
                      <div v-if="translations[m.id].open" class="mt-0.5 whitespace-pre-wrap">{{ translations[m.id].showOriginal ? translations[m.id].original : translations[m.id].translated }}</div>
                    </div>
                  </template>
                  <!-- #176 触屏常显「更多」入口；桌面仍走 hover 展开 -->
                  <button v-if="!m.is_recalled && !m.local && menuFor !== m.id" class="absolute -top-2 right-2 rounded-pill bg-white px-1.5 text-[11px] text-ink-500 shadow-card md:hidden" title="更多操作" @click.stop="toggleMenu(m.id)">⋯</button>
                  <div v-if="!m.is_recalled && !m.local"
                    class="absolute -top-2 right-2 gap-1 rounded-pill bg-white px-1 text-[10px] shadow-card"
                    :class="[menuFor === m.id ? 'flex' : 'hidden md:group-hover:flex', m.sender === myId ? 'text-ink-600' : '']">
                    <button @click.stop="replyMsg(m)">回复</button>
                    <button @click.stop="forwardMsg(m)">转发</button>
                    <button v-if="canEdit(m)" @click.stop="startEdit(m)">编辑</button>
                    <button v-if="m.sender === myId && canRecall(m)" @click.stop="recall(m)">撤回</button>
                    <button @click.stop="translateMsg(m)">翻译</button>
                    <button @click.stop="makeTodo(m)">待办</button>
                    <button @click.stop="togglePinMsg(m)">📌</button>
                    <button v-if="canDeleteForAll(m)" class="text-rose-500" @click.stop="deleteForAll(m)">为所有人删除</button>
                    <button @click.stop="deleteForMe(m)">删除</button>
                    <button class="md:hidden" @click.stop="menuFor = null">收起</button>
                  </div>
                </div>
                <div class="mt-0.5 flex items-center gap-1 text-[10px] text-ink-300" :class="m.sender === myId ? 'justify-end' : ''">
                  <span>{{ formatTime(m.created_at) }}</span>
                  <!-- #306 已编辑标注 -->
                  <span v-if="m.edited">· 已编辑</span>
                  <!-- #330 发送失败保留在列表，可重试 -->
                  <template v-if="m.failed">
                    <span class="text-rose-500">· 发送失败</span>
                    <button class="text-brand-600 underline" @click="retrySend(m)">重试</button>
                  </template>
                  <span v-else-if="m.pending" class="text-ink-400">· 发送中…</span>
                  <!-- #309 已读明细入口 -->
                  <button v-if="m.sender === myId && !m.local && !m.failed" class="underline hover:text-brand-600" @click="openReaders(m)">· 已读 {{ m.read_by_count || 0 }}</button>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- 正在回复的消息 -->
        <div v-if="replying" class="flex items-center gap-2 border-t border-ink-100 bg-ink-50 px-3 py-1.5 text-[12px] text-ink-500">
          回复 {{ replying.sender_name }}：{{ replying.content.slice(0, 40) }}
          <button class="ml-auto text-rose-400" @click="replying = null">×</button>
        </div>

        <div class="flex items-center gap-2 border-t border-ink-100 p-3">
          <button class="btn-ghost px-2" title="表情" @click="showEmoji = !showEmoji">😊</button>
          <button class="btn-ghost px-2" title="快捷回复" @click="openQuickReplies">⚡</button>
          <div class="relative flex-1">
            <!-- #150 回车发送、Shift+Enter 换行、输入法组合态不发送 -->
            <textarea ref="draftEl" v-model="draft" rows="1" class="input max-h-24 w-full resize-none leading-relaxed" placeholder="输入消息，回车发送，Shift+Enter 换行…"
              @input="onDraftInput" @click="updateMentionCandidates" @blur="mentionCand = []" @keydown.enter="onDraftEnter"></textarea>
            <!-- #328 输入 @ 弹出成员候选 -->
            <div v-if="mentionCand.length" class="absolute bottom-10 left-0 z-10 w-56 overflow-hidden rounded-card border border-ink-100 bg-white py-1 shadow-pop">
              <button v-for="(c, i) in mentionCand" :key="c.id" class="flex w-full items-center gap-1 px-2 py-1 text-left text-[12px]"
                :class="i === mentionIndex ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50'" @mousedown.prevent="insertMention(c)">
                <span class="truncate">{{ c.display_name }}</span>
                <span class="ml-auto text-[10px] text-ink-400">@{{ c.username }}</span>
              </button>
            </div>
            <div v-if="showEmoji" class="absolute bottom-10 left-0 z-10 grid w-64 grid-cols-8 gap-1 rounded-card border border-ink-100 bg-white p-2 shadow-pop">
              <button v-for="e in emojiList" :key="e" class="text-[16px] hover:scale-125" @click="pickEmoji(e)">{{ e }}</button>
            </div>
          </div>
          <button class="btn-primary" @click="send">发送</button>
        </div>
      </template>
      <div v-else class="grid flex-1 place-items-center text-[13px] text-ink-400">选择一个会话开始聊天</div>
    </div>

    <!-- 新建会话 -->
    <Modal :show="showNew" title="发起聊天" @close="showNew = false">
      <div class="space-y-3">
        <div class="flex gap-2">
          <input v-model="newGroupName" class="input flex-1" placeholder="群名称（填了即建群，可多选成员）" />
        </div>
        <div class="flex gap-2">
          <input v-model="candidateQuery" class="input flex-1" placeholder="搜索用户…" @input="loadCandidates" />
          <button class="btn-outline" @click="loadCandidates">搜索</button>
        </div>
        <div class="max-h-52 space-y-1 overflow-y-auto">
          <div v-for="c in candidates" :key="c.id" class="flex items-center justify-between rounded-control px-2 py-2 hover:bg-ink-50">
            <span class="text-[13px]">{{ c.display_name }} <span class="text-[11px] text-ink-400">@{{ c.username }}</span></span>
            <input type="checkbox" :checked="picked.has(c.id)" @change="togglePick(c.id)" />
          </div>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showNew = false">取消</button>
          <button class="btn-primary" @click="startSession">发起</button>
        </div>
      </div>
    </Modal>

    <!-- 转发（#324 多会话一次提交，逐会话显示成功 / 失败） -->
    <Modal :show="!!forwarding" title="转发给…" @close="forwarding = null">
      <div class="max-h-60 space-y-1 overflow-y-auto">
        <label v-for="s in sessions" :key="s.id" class="flex items-center gap-2 rounded-control px-2 py-2 text-[13px] hover:bg-ink-50">
          <input type="checkbox" :checked="forwardTargets.has(s.id)" @change="toggleForward(s.id)" /> {{ sessionName(s) }}
        </label>
      </div>
      <div v-if="forwardResults.length" class="mt-2 max-h-32 space-y-0.5 overflow-y-auto rounded-control bg-ink-50 p-2 text-[11px]">
        <div v-for="(r, i) in forwardResults" :key="i" :class="r.success ? 'text-emerald-600' : 'text-rose-500'">
          {{ r.success ? '✓' : '✕' }} 会话 {{ r.session_id }}{{ r.session_name ? `（${r.session_name}）` : '' }}{{ r.success ? ' 已转发' : ` ${r.error || '失败'}` }}
        </div>
      </div>
      <div class="mt-3 flex items-center justify-end gap-2">
        <span class="mr-auto text-[11px] text-ink-400">已选 {{ forwardTargets.size }} / 最多 20 个</span>
        <button class="btn-primary" @click="confirmForward">转发</button>
      </div>
    </Modal>

    <!-- 群管理（#312 统计页签 / #329 文件页签） -->
    <Modal :show="showGroup" title="群管理" width="640px" @close="showGroup = false">
      <div class="mb-3 flex gap-1 text-[12px]">
        <button v-for="t in groupTabs" :key="t.value" class="rounded-pill px-2.5 py-0.5" :class="groupTab === t.value ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-50'" @click="switchGroupTab(t.value)">{{ t.label }}</button>
      </div>
      <!-- 成员 -->
      <div v-if="groupTab === 'members'" class="space-y-3">
        <div class="flex gap-2">
          <input v-model="groupAddQ" class="input flex-1" placeholder="搜索用户添加" @input="searchAdd" />
        </div>
        <div v-if="addCandidates.length" class="max-h-32 space-y-1 overflow-y-auto rounded-control border border-ink-100 p-1">
          <div v-for="c in addCandidates" :key="c.id" class="flex items-center justify-between px-2 py-1.5 text-[13px]">
            <span>{{ c.display_name }}</span><button class="btn-outline px-2 py-0.5 text-[11px]" @click="addMember(c.id)">＋</button>
          </div>
        </div>
        <!-- 群成员搜索框 -->
        <input v-model="memberSearchQ" class="input" placeholder="搜索群成员…" />
        <div class="divide-y divide-ink-50">
          <div v-for="m in filteredMembers" :key="m.id" class="flex items-center justify-between py-2 text-[13px]">
            <span>{{ m.display_name }} <span v-if="m.id === activeSession?.owner" class="tag-brand">群主</span></span>
            <button v-if="m.id !== myId" class="btn-ghost px-2 text-[12px] text-rose-500" @click="kick(m.id)">移除</button>
          </div>
        </div>
      </div>
      <!-- 统计 -->
      <div v-else-if="groupTab === 'stats'" class="max-h-[62vh] space-y-3 overflow-y-auto">
        <div v-if="stats" class="space-y-3">
          <div class="grid grid-cols-3 gap-2 text-center">
            <div class="rounded-control bg-ink-50 py-2"><div class="text-[16px] font-semibold">{{ stats.total }}</div><div class="text-[11px] text-ink-400">消息总数</div></div>
            <div class="rounded-control bg-ink-50 py-2"><div class="text-[16px] font-semibold">{{ stats.member_count }}</div><div class="text-[11px] text-ink-400">成员</div></div>
            <div class="rounded-control bg-ink-50 py-2"><div class="text-[16px] font-semibold">{{ stats.active_days }}</div><div class="text-[11px] text-ink-400">活跃天数</div></div>
          </div>
          <div>
            <div class="mb-1 text-[12px] font-medium">成员发言</div>
            <div class="space-y-1">
              <div v-for="(r, ri) in stats.by_member.slice(0, 10)" :key="ri" class="flex items-center gap-2 text-[11px]">
                <span class="w-20 truncate" :title="r.name">{{ r.name }}</span>
                <div class="h-3 flex-1 overflow-hidden rounded bg-ink-100"><div class="h-3 rounded bg-brand-500" :style="{ width: barWidth(r.count) }"></div></div>
                <span class="w-8 text-right text-ink-500">{{ r.count }}</span>
              </div>
              <div v-if="!stats.by_member.length" class="py-3 text-center text-[11px] text-ink-400">暂无数据</div>
            </div>
          </div>
          <div>
            <div class="mb-1 text-[12px] font-medium">24 小时分布</div>
            <div class="grid grid-cols-12 gap-1">
              <div v-for="(n, h) in stats.hour_distribution" :key="h" class="rounded py-1 text-center text-[10px] text-ink-700" :style="{ background: heatColor(n) }" :title="`${h}:00 · ${n} 条`">{{ h }}</div>
            </div>
          </div>
        </div>
        <div v-else class="py-6 text-center text-[12px] text-ink-400">统计加载中…</div>
      </div>
      <!-- 文件 -->
      <div v-else class="space-y-2">
        <div class="flex gap-2">
          <select v-model="filesFilter.type" class="input w-24" @change="loadFiles(1)">
            <option value="">全部类型</option><option value="image">图片</option><option value="file">文件</option>
          </select>
          <select v-model="filesFilter.sender" class="input flex-1" @change="loadFiles(1)">
            <option value="">全部发送者</option>
            <option v-for="m in (activeSession?.members_info || [])" :key="m.id" :value="m.id">{{ m.display_name }}</option>
          </select>
        </div>
        <div class="max-h-[52vh] space-y-1 overflow-y-auto">
          <a v-for="f in files" :key="f.message_id + '-' + f.url" :href="f.url" target="_blank" rel="noopener"
            class="flex items-center gap-2 rounded-control px-2 py-1.5 text-[12px] hover:bg-ink-50">
            <span>{{ f.category === 'image' ? '🖼' : '📎' }}</span>
            <span class="min-w-0 flex-1 truncate">{{ f.name || '附件' }}</span>
            <span class="shrink-0 text-[10px] text-ink-400">{{ f.sender_name }}</span>
          </a>
          <div v-if="!files.length" class="py-6 text-center text-[12px] text-ink-400">暂无附件</div>
        </div>
        <div class="flex items-center justify-between text-[11px] text-ink-500">
          <span>共 {{ filesTotal }} 个</span>
          <div class="flex items-center gap-2">
            <button class="btn-outline px-2 py-0.5" :disabled="filesFilter.page <= 1" @click="loadFiles(filesFilter.page - 1)">上一页</button>
            <span>{{ filesFilter.page }} / {{ filesPages || 1 }}</span>
            <button class="btn-outline px-2 py-0.5" :disabled="filesFilter.page >= filesPages" @click="loadFiles(filesFilter.page + 1)">下一页</button>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 快捷回复（#319 分组标题 + 拖拽排序） -->
    <Modal :show="showQuickReply" title="快捷回复管理" width="620px" @close="showQuickReply = false">
      <div class="space-y-2">
        <div class="max-h-[50vh] space-y-1 overflow-y-auto">
          <div v-for="g in quickReplyGroups" :key="g.name">
            <div class="mb-1 mt-1 text-[11px] font-medium text-ink-500">{{ g.name }} <span class="text-ink-300">（{{ g.items.length }}）</span></div>
            <div v-for="q in g.items" :key="q.id" draggable="true"
              class="mb-1 flex cursor-move items-center gap-2 rounded-control border border-ink-100 p-2"
              @dragstart="qrDragStart(q)" @dragover.prevent @drop="qrDrop(q)">
              <span class="text-ink-300">⋮⋮</span>
              <div class="min-w-0 flex-1">
                <div class="text-[12px] font-medium">{{ q.title || '未命名' }}</div>
                <div class="truncate text-[11px] text-ink-400">{{ q.content }}</div>
              </div>
              <button class="btn-outline text-[11px]" @click="useQuickReply(q)">使用</button>
              <button class="text-[11px] text-brand-600" @click="editQuickReply(q)">编辑</button>
              <button class="text-rose-400" @click="delQuickReply(q)">×</button>
            </div>
          </div>
          <div v-if="!quickReplies.length" class="py-6 text-center text-[12px] text-ink-400">还没有快捷回复</div>
        </div>
        <div class="space-y-2 border-t border-ink-50 pt-2">
          <div class="flex gap-2">
            <input v-model="qrForm.title" class="input w-28" placeholder="标题" />
            <input v-model="qrForm.group" class="input w-28" placeholder="分组（可选）" />
            <input v-model="qrForm.sort_order" type="number" class="input w-20" placeholder="排序" />
          </div>
          <div class="flex gap-2">
            <input v-model="qrForm.content" class="input flex-1" placeholder="快捷回复内容" @keyup.enter="saveQuickReply" />
            <button class="btn-primary" @click="saveQuickReply">{{ qrForm.id ? '保存' : '添加' }}</button>
            <button v-if="qrForm.id" class="btn-ghost" @click="resetQRForm">取消</button>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 关键词提醒（#318 最近命中回看） -->
    <Modal :show="showKeyword" title="关键词提醒" width="580px" @close="showKeyword = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-500">消息内容命中以下任一关键词时，将推送通知提醒（逗号分隔）。</p>
        <input v-model="keywordInput" class="input" placeholder="如：紧急, 上线, @我" />
        <div class="flex justify-end"><button class="btn-primary" @click="saveKeywords">保存</button></div>
        <div class="border-t border-ink-50 pt-2">
          <div class="mb-1 text-[12px] font-medium">最近命中（{{ hits.length }}）</div>
          <div class="max-h-48 space-y-1 overflow-y-auto">
            <button v-for="h in hits" :key="h.id" class="block w-full rounded-control bg-ink-50 px-2 py-1.5 text-left text-[12px] hover:bg-brand-50" @click="jumpToResult(h)">
              <span class="text-ink-500">{{ h.session_name }} · {{ h.sender_name }}：</span>{{ h.content }}
              <span v-if="h.matched_keywords && h.matched_keywords.length" class="ml-1 text-[10px] text-amber-600">{{ h.matched_keywords.join('/') }}</span>
            </button>
            <div v-if="!hits.length" class="py-4 text-center text-[12px] text-ink-400">暂无命中记录</div>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 消息搜索（#320 发送人 / 类型 / 日期 / 含附件 + 分页） -->
    <Modal :show="showSearch" title="搜索消息" width="620px" @close="showSearch = false">
      <div class="space-y-2">
        <input v-model="searchForm.q" class="input" placeholder="关键字" @keyup.enter="doSearch(1)" />
        <div class="flex flex-wrap items-center gap-2">
          <input v-model="searchForm.sender" class="input w-24" placeholder="发送者ID" />
          <select v-model="searchForm.msg_type" class="input w-28">
            <option value="">全部类型</option>
            <option value="text">文本</option>
            <option value="image">图片</option>
            <option value="file">文件</option>
          </select>
          <label class="flex items-center gap-1 text-[12px] text-ink-600"><input v-model="searchForm.has_attachment" type="checkbox" />含附件</label>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <input v-model="searchForm.date_from" type="date" class="input w-36" />
          <span class="text-[11px] text-ink-400">至</span>
          <input v-model="searchForm.date_to" type="date" class="input w-36" />
          <button class="btn-primary ml-auto" @click="doSearch(1)">搜索</button>
        </div>
        <div class="text-[11px] text-ink-400">共 {{ searchTotal }} 条</div>
        <div class="max-h-60 space-y-1 overflow-y-auto">
          <button v-for="m in searchResults" :key="m.id" class="block w-full rounded-control bg-ink-50 px-2 py-1.5 text-left text-[12px] hover:bg-brand-50" @click="jumpToResult(m)">
            <span class="text-ink-500">{{ m.session_name }} · {{ m.sender_name }}：</span>{{ m.content }}
          </button>
          <div v-if="!searchResults.length" class="py-6 text-center text-[12px] text-ink-400">没有匹配的消息</div>
        </div>
        <div class="flex items-center justify-between text-[11px] text-ink-500">
          <button class="btn-outline px-2 py-0.5" :disabled="searchForm.page <= 1" @click="doSearch(searchForm.page - 1)">上一页</button>
          <span>{{ searchForm.page }} / {{ searchPages || 1 }}</span>
          <button class="btn-outline px-2 py-0.5" :disabled="searchForm.page >= searchPages" @click="doSearch(searchForm.page + 1)">下一页</button>
        </div>
      </div>
    </Modal>

    <!-- 编辑消息（#306） -->
    <Modal :show="!!editing" title="编辑消息" @close="editing = null">
      <textarea v-model="editText" rows="4" class="input w-full resize-none" placeholder="消息内容"></textarea>
      <div class="mt-2 flex justify-end gap-2">
        <button class="btn-ghost" @click="editing = null">取消</button>
        <button class="btn-primary" @click="saveEdit">保存</button>
      </div>
    </Modal>

    <!-- 群公告（#317） -->
    <Modal :show="showAnn" title="群公告" @close="showAnn = false">
      <div class="space-y-2">
        <template v-if="ann.can_edit">
          <textarea v-model="ann.announcement" rows="4" class="input w-full resize-none" placeholder="群公告内容"></textarea>
          <div class="flex justify-end"><button class="btn-primary" @click="saveAnnouncement">保存公告</button></div>
        </template>
        <p v-else class="whitespace-pre-wrap text-[13px] text-ink-700">{{ ann.announcement || '暂无公告' }}</p>
      </div>
    </Modal>

    <!-- 会话标签（#315） -->
    <Modal :show="showTags" title="会话标签" @close="showTags = false">
      <div class="space-y-2">
        <input v-model="tagInput" class="input" placeholder="逗号分隔，如：项目A, 重要" />
        <p class="text-[11px] text-ink-400">标签会显示在会话列表并可用于筛选（最多 10 个，每个 20 字）。</p>
        <div class="flex justify-end"><button class="btn-primary" @click="saveTags">保存</button></div>
      </div>
    </Modal>

    <!-- 导出（#325） -->
    <Modal :show="showExport" title="导出聊天记录" @close="showExport = false">
      <div class="space-y-3">
        <div class="flex items-center gap-2">
          <input v-model="exportForm.start" type="date" class="input flex-1" />
          <span class="text-[11px] text-ink-400">至</span>
          <input v-model="exportForm.end" type="date" class="input flex-1" />
        </div>
        <div class="flex gap-4 text-[12px] text-ink-600">
          <label class="flex items-center gap-1"><input v-model="exportForm.format" type="radio" value="md" /> Markdown</label>
          <label class="flex items-center gap-1"><input v-model="exportForm.format" type="radio" value="csv" /> CSV</label>
        </div>
        <p class="text-[11px] text-ink-400">留空日期表示不限范围，单次最多导出 5000 条。</p>
        <div class="flex justify-end"><button class="btn-primary" @click="doExport">导出</button></div>
      </div>
    </Modal>

    <!-- @我（#311） -->
    <Modal :show="showMentions" title="@我" width="600px" @close="showMentions = false">
      <div class="max-h-[60vh] space-y-1 overflow-y-auto">
        <button v-for="m in mentions" :key="m.id" class="block w-full rounded-control bg-ink-50 px-2 py-1.5 text-left text-[12px] hover:bg-brand-50" @click="jumpToResult(m)">
          <span class="text-ink-500">{{ m.session_name }} · {{ m.sender_name }}：</span>{{ m.content }}
        </button>
        <div v-if="!mentions.length" class="py-6 text-center text-[12px] text-ink-400">暂无 @ 我的消息</div>
      </div>
    </Modal>

    <!-- 已读明细抽屉（#309） -->
    <div v-if="readersOpen" class="fixed inset-0 z-[90] flex justify-end bg-ink-900/30" @click.self="readersOpen = false">
      <div class="flex h-full w-80 flex-col bg-white shadow-pop">
        <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2.5">
          <span class="text-[13px] font-semibold">已读明细</span>
          <button class="text-ink-400" @click="readersOpen = false">✕</button>
        </div>
        <div class="flex-1 space-y-3 overflow-y-auto p-3 text-[12px]">
          <div>
            <div class="mb-1 text-[11px] font-medium text-emerald-600">已读 {{ readersData?.read || 0 }}</div>
            <div v-for="u in readersData?.readers || []" :key="u.id" class="rounded-control px-2 py-1 hover:bg-ink-50">{{ u.display_name }}</div>
            <div v-if="!readersData?.readers?.length" class="text-[11px] text-ink-400">暂无</div>
          </div>
          <div>
            <div class="mb-1 text-[11px] font-medium text-rose-500">未读 {{ readersData?.unread || 0 }}</div>
            <div v-for="u in readersData?.unreaders || []" :key="u.id" class="rounded-control px-2 py-1 hover:bg-ink-50">{{ u.display_name }}</div>
            <div v-if="!readersData?.unreaders?.length" class="text-[11px] text-ink-400">暂无</div>
          </div>
        </div>
        <div class="border-t border-ink-100 p-3">
          <button class="btn-primary w-full" :disabled="!readersData?.unreaders?.length" @click="mentionUnread">一键 @ 未读（{{ readersData?.unread || 0 }}）</button>
        </div>
      </div>
    </div>

    <!-- 待办面板（#310） -->
    <div v-if="showTodo" class="fixed inset-0 z-[90] flex justify-end bg-ink-900/30" @click.self="showTodo = false">
      <div class="flex h-full w-80 flex-col bg-white shadow-pop">
        <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2.5">
          <span class="text-[13px] font-semibold">待办（{{ todos.filter((t) => !t.is_done).length }}）</span>
          <button class="text-ink-400" @click="showTodo = false">✕</button>
        </div>
        <div class="flex-1 space-y-1 overflow-y-auto p-2">
          <div v-for="t in todos" :key="t.id" class="rounded-control border border-ink-100 p-2 text-[12px]">
            <div class="flex items-start gap-1">
              <input type="checkbox" :checked="t.is_done" class="mt-0.5" @change="toggleTodo(t)" />
              <span class="min-w-0 flex-1" :class="t.is_done ? 'text-ink-400 line-through' : ''">{{ t.content }}</span>
              <button class="text-rose-400" @click="delTodo(t)">×</button>
            </div>
            <div class="mt-1 flex items-center gap-1 text-[10px] text-ink-400">
              <span class="truncate">{{ t.session_name || '未关联会话' }}</span>
              <input type="date" class="ml-auto rounded border border-ink-100 px-1 text-[10px]" :value="dueDate(t)" @change="setTodoDue(t, $event.target.value)" />
            </div>
          </div>
          <div v-if="!todos.length" class="py-8 text-center text-[12px] text-ink-400">暂无待办，可在消息菜单中「设为待办」</div>
        </div>
      </div>
    </div>

    <!-- 图片灯箱（#323） -->
    <div v-if="lightbox.open" class="fixed inset-0 z-[110] flex flex-col items-center justify-center bg-black/85 p-4" @click.self="lightbox.open = false">
      <div class="mb-2 flex w-full max-w-4xl items-center justify-between text-[12px] text-white/80">
        <span>{{ lightbox.index + 1 }} / {{ lightbox.list.length }} · {{ lightbox.list[lightbox.index]?.name || '图片' }}</span>
        <div class="flex items-center gap-3">
          <a :href="lightbox.list[lightbox.index]?.url" download class="underline">下载</a>
          <button @click="lightbox.open = false">✕</button>
        </div>
      </div>
      <img :src="lightbox.list[lightbox.index]?.url" class="max-h-[75vh] max-w-full rounded-card object-contain" alt="预览" />
      <div class="mt-3 flex gap-3">
        <button class="btn-outline" :disabled="lightbox.index <= 0" @click="lightboxStep(-1)">上一张</button>
        <button class="btn-outline" :disabled="lightbox.index >= lightbox.list.length - 1" @click="lightboxStep(1)">下一张</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { imApi, authApi } from '../../api'
import { imx } from '../../api/imx'
import { useUserStore } from '../../stores/user'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import Modal from '../../components/Modal.vue'

const user = useUserStore()
const app = useAppStore()
// profile 可能在 WS 推送/刷新后才到；用 computed 保证自己的消息不会先渲染到左侧
const myId = computed(() => user.profile?.id)
const sessions = ref([])
const route = useRoute()
const activeSession = ref(null)
const messages = ref([])
const pinned = ref([])
const draft = ref('')
const keyword = ref('')
const typing = ref('')
const showNew = ref(false)
const newGroupName = ref('')
const candidates = ref([])
const candidateQuery = ref('')
const picked = ref(new Set())
const forwarding = ref(null)
const forwardTargets = ref(new Set())
const forwardResults = ref([])
const showGroup = ref(false)
const groupAddQ = ref('')
const addCandidates = ref([])
const msgBox = ref(null)
const showArchived = ref(false)
const replying = ref(null)
const showEmoji = ref(false)
const showQuickReply = ref(false)
const quickReplies = ref([])
const qrForm = ref({ id: null, title: '', content: '', group: '', sort_order: 0 })
const showKeyword = ref(false)
const keywordInput = ref('')
const hits = ref([])
const showSearch = ref(false)
const searchForm = ref({ q: '', sender: '', msg_type: '', date_from: '', date_to: '', has_attachment: false, page: 1, page_size: 20 })
const searchResults = ref([])
const searchTotal = ref(0)
const searchPages = ref(0)
const memberSearchQ = ref('')
const emojiList = ['😀','😂','❤️','👍','🙏','🎉','🔥','✨','💡','✅','❌','⚠️','🚀','😅','🤝','👋','🙌','💪','😴','🥳']

// ===== docs/16 #306–#330 新增状态 =====
const editing = ref(null)            // #306 正在编辑的消息
const editText = ref('')
const translations = ref({})         // #308 messageId -> 翻译结果
const expanded = ref(new Set())      // #322 已展开的消息 id
const highlightId = ref(null)        // #311 / #321 定位高亮
const unreadDivider = ref(null)      // #313 首条未读 id
const readersOpen = ref(false)       // #309 已读抽屉
const readersData = ref(null)
const showTodo = ref(false)          // #310 待办面板
const todos = ref([])
const showMentions = ref(false)      // #311 @我
const mentions = ref([])
const tags = ref([])                 // #315 可用标签
const activeTags = ref([])
const showTags = ref(false)
const tagInput = ref('')
const ann = ref({ announcement: '', unread: false, can_edit: false })  // #317
const showAnn = ref(false)
const groupTab = ref('members')
const stats = ref(null)
const files = ref([])                // #329
const filesFilter = ref({ type: '', sender: '', page: 1 })
const filesTotal = ref(0)
const filesPages = ref(0)
const showMute = ref(false)          // #326
const pinDragId = ref(null)          // #327
const showExport = ref(false)        // #325
const exportForm = ref({ start: '', end: '', format: 'md' })
const draftEl = ref(null)
const mentionCand = ref([])          // #328
const mentionIndex = ref(0)
const lightbox = ref({ open: false, list: [], index: 0 })  // #323
const nowTs = ref(Date.now())        // 免打扰剩余时间刷新

const muteOptions = [
  { value: '1h', label: '免打扰 1 小时' },
  { value: '8h', label: '免打扰 8 小时' },
  { value: 'tomorrow', label: '免打扰到明天' },
  { value: 'off', label: '关闭免打扰' },
]
const groupTabs = [
  { value: 'members', label: '成员' },
  { value: 'stats', label: '统计' },
  { value: 'files', label: '文件' },
]

let unsub = null
let draftTimer = null
let typingTimer = null
let typingSendTimer = null
let tickTimer = null
let typingSent = false
let loadSeq = 0
let localSeq = 0
let qrDragId = null
let pinDrag = null

function otherMember(s) { return (s.members_info || []).find((m) => m.id !== myId.value) }
function sessionName(s) {
  if (!s) return ''
  if (s.type === 'group') return s.name || '群聊'
  return otherMember(s)?.display_name || '会话'
}
function avatarText(s) { return s.type === 'group' ? '👥' : sessionName(s).slice(0, 1) }
function lastText(s) {
  if (!s.last_message) return '暂无消息'
  return `${s.last_message.sender_name === user.displayName ? '我: ' : ''}${s.last_message.content}`
}
function canRecall(m) { return (Date.now() - new Date(m.created_at).getTime()) / 1000 < 120 }

// #306 本人文本消息 10 分钟内可编辑（后端 can_edit 为准，缺失时按时间兜底）
function canEdit(m) {
  if (!m || m.local || m.is_recalled || m.is_deleted || m.sender !== myId.value) return false
  if (m.msg_type && m.msg_type !== 'text') return false
  if (typeof m.can_edit === 'boolean') return m.can_edit
  return (Date.now() - new Date(m.created_at).getTime()) / 1000 < 600
}
// #307 发送者 / 群主可「为所有人删除」
function canDeleteForAll(m) {
  if (!m || m.local) return false
  if (m.sender === myId.value) return true
  return activeSession.value?.type === 'group' && activeSession.value?.owner === myId.value
}
// #322 长消息：超过 300 字折叠为 8 行
function isLong(m) { return !m.is_recalled && (m.content || '').length > 300 }
function collapseStyle(m) {
  return isLong(m) && !expanded.value.has(m.id) ? { maxHeight: '169px' } : {}
}
function toggleExpand(id) {
  const s = new Set(expanded.value)
  s.has(id) ? s.delete(id) : s.add(id)
  expanded.value = s
}
// #323 附件分类
function imageAtts(m) { return (m.attachments || []).filter((a) => a && a.url && String(a.type || '').startsWith('image/')) }
function fileAtts(m) { return (m.attachments || []).filter((a) => a && a.url && !String(a.type || '').startsWith('image/')) }
function openLightbox(m, idx) {
  const list = []
  messages.value.forEach((x) => imageAtts(x).forEach((a) => list.push(a)))
  const target = imageAtts(m)[idx]
  const index = list.findIndex((a) => a.url === target?.url)
  lightbox.value = { open: true, list, index: index < 0 ? 0 : index }
}
function lightboxStep(step) {
  const next = lightbox.value.index + step
  if (next < 0 || next >= lightbox.value.list.length) return
  lightbox.value = { ...lightbox.value, index: next }
}
// #326 免打扰文案与剩余时间
function muteLeft(s) {
  if (!s?.mute_until) return ''
  const ms = new Date(s.mute_until).getTime() - nowTs.value
  if (ms <= 0) return '(已到期)'
  const mins = Math.ceil(ms / 60000)
  if (mins < 60) return `剩余 ${mins} 分钟`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `剩余 ${hours} 小时 ${mins % 60} 分`
  return `剩余 ${Math.ceil(hours / 24)} 天`
}
function muteLabel(s) {
  if (!s?.is_muted) return '免打扰'
  return s.mute_until ? `免打扰 ${muteLeft(s)}` : '取消免打扰'
}
function muteText(s) {
  if (!s?.is_muted) return ''
  return s.mute_until ? `免打扰中，${muteLeft(s)}` : '永久免打扰'
}
// #310 待办到期日（date input 用）
function dueDate(t) {
  if (!t?.remind_at) return ''
  const d = new Date(t.remind_at)
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10)
}
// #312 图表辅助
function barWidth(count) {
  const rows = stats.value?.by_member || []
  const max = Math.max(1, ...rows.map((r) => r.count))
  return `${Math.max(2, Math.round((count / max) * 100))}%`
}
function heatColor(count) {
  const dist = stats.value?.hour_distribution || []
  const max = Math.max(1, ...dist)
  const alpha = 0.08 + 0.8 * (count / max)
  return `rgba(37, 99, 235, ${count ? alpha.toFixed(2) : 0.05})`
}
// #319 快捷回复按分组聚合（组内按 sort_order）
const quickReplyGroups = computed(() => {
  const sorted = [...quickReplies.value].sort(
    (a, b) => String(a.group || '').localeCompare(String(b.group || '')) || (a.sort_order || 0) - (b.sort_order || 0)
  )
  const out = []
  sorted.forEach((q) => {
    const name = q.group || '未分组'
    let bucket = out.find((b) => b.name === name)
    if (!bucket) { bucket = { name, items: [] }; out.push(bucket) }
    bucket.items.push(q)
  })
  return out
})

const filteredMembers = computed(() => {
  const arr = activeSession.value?.members_info || []
  if (!memberSearchQ.value) return arr
  return arr.filter((m) => m.display_name.includes(memberSearchQ.value))
})

// 安全渲染：仅把 ``` 代码块渲染为样式化 <pre>，其余文本转义后按行展示（防 XSS）
function esc(t) { return (t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
function renderContent(m) {
  if (m.is_recalled) return ''
  const parts = (m.content || '').split(/```/)
  let html = ''
  parts.forEach((seg, i) => {
    if (i % 2 === 1) {
      const firstNl = seg.indexOf('\n')
      const lang = firstNl > -1 ? seg.slice(0, firstNl).trim() : ''
      const code = firstNl > -1 ? seg.slice(firstNl + 1) : seg
      html += `<pre style="background:#0f172a;color:#e2e8f0;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px;margin:4px 0;"><span style="color:#64748b">${esc(lang)}</span>\n${esc(code)}</pre>`
    } else {
      html += esc(seg).replace(/\n/g, '<br>')
    }
  })
  return html
}

async function loadSessions() {
  try {
    const r = await imx.sessions({
      search: keyword.value || undefined,
      archived: showArchived.value ? '1' : undefined,
      // #315 多选并集：后端按逗号拆分后取交集非空
      tags: activeTags.value.length ? activeTags.value.join(',') : undefined,
    })
    sessions.value = r.list || []
    tags.value = r.tags || []
  } catch (e) { app.toastMsg(e?.message || '加载会话列表失败', 'error') }
}
// 切换会话时清空上一会话的临时 UI 状态（翻译 / 展开 / 高亮 / 未读线 …）
function resetSessionUi() {
  translations.value = {}
  expanded.value = new Set()
  highlightId.value = null
  unreadDivider.value = null
  mentionCand.value = []
  stats.value = null
  files.value = []
  filesTotal.value = 0
  filesPages.value = 0
  filesFilter.value = { type: '', sender: '', page: 1 }
  groupTab.value = 'members'
}
async function openSession(s) {
  try {
    // 切会话前先把上一会话的草稿落库（防抖窗口内切走会写错会话）
    clearTimeout(draftTimer)
    if (activeSession.value) {
      setSessionDraft(activeSession.value.id, draft.value)
      imApi.setting(activeSession.value.id, { draft: draft.value }).catch(() => {})
      stopTyping()
    }
    const seq = ++loadSeq
    activeSession.value = s
    draft.value = s.draft || ''
    menuFor.value = null
    replying.value = null
    resetSessionUi()
    // #317 顶栏公告未读红点
    ann.value = { announcement: s.announcement || '', unread: !!s.announcement_unread, can_edit: s.type === 'group' && s.owner === myId.value }
    // #313 先取首条未读（标记已读之后就取不到了）
    let firstUnread = null
    try {
      const u = await imx.unreadLine(s.id)
      if (u.has_unread) firstUnread = u.first_unread_id
    } catch (e) { /* 未读线失败不影响主流程 */ }
    const r = await imApi.messages(s.id, { page_size: 30 })
    if (seq !== loadSeq) return  // 旧请求的响应晚到，不能覆盖新会话
    // F5：r.list 是接口响应里的新数组，无其他引用，直接 reverse 即可，
    // 原来的 .slice().reverse() 多一次无用拷贝
    messages.value = (r.list || []).reverse()
    pinned.value = r.pinned || []
    unreadDivider.value = firstUnread && messages.value.some((m) => m.id === firstUnread) ? firstUnread : null
    await imApi.setting(s.id, { mark_read: true })
    if (seq !== loadSeq) return
    s.unread = 0
    nextTick(() => (unreadDivider.value ? scrollToMessage(unreadDivider.value, false) : scrollBottom()))
  } catch (e) { app.toastMsg(e?.message || '打开会话失败', 'error') }
}
async function refreshActiveMessages() {
  const s = activeSession.value
  if (!s) return
  const seq = ++loadSeq
  try {
    const r = await imApi.messages(s.id, { page_size: 30 })
    if (seq !== loadSeq || activeSession.value?.id !== s.id) return
    messages.value = (r.list || []).reverse()
    pinned.value = r.pinned || []
    await imApi.setting(s.id, { mark_read: true })
    s.unread = 0
    nextTick(scrollBottom)
  } catch (e) { /* 静默失败，等待用户手动刷新 */ }
}
let sending = false
// #150 输入法组合态（选词回车）与 Shift+Enter 都不触发发送；#328 有 @ 候选时回车即插入
function onDraftEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  if (mentionCand.value.length) {
    e.preventDefault()
    insertMention(mentionCand.value[Math.min(mentionIndex.value, mentionCand.value.length - 1)])
    return
  }
  if (e.shiftKey) return  // Shift+Enter 保留换行
  e.preventDefault()
  send()
}
// #314 输入事件 2 秒防抖上报 typing=true；清空输入立即上报 typing=false
function onDraftInput() {
  saveDraft()
  updateMentionCandidates()
  const session = activeSession.value
  if (!session) return
  clearTimeout(typingSendTimer)
  if (!draft.value.trim()) {
    stopTyping()
    return
  }
  const sid = session.id
  typingSendTimer = setTimeout(() => {
    if (activeSession.value?.id === sid) notifyTyping(true)
  }, 2000)
}
function notifyTyping(on) {
  const session = activeSession.value
  if (!session || typingSent === on) return
  typingSent = on
  imx.typing(session.id, on).catch(() => {})
}
function stopTyping() {
  clearTimeout(typingSendTimer)
  notifyTyping(false)
}
// #330 发送：先插入本地占位气泡，成功替换为正式消息；失败保留在列表可重试，草稿不清空
async function send() {
  if (sending) return
  const session = activeSession.value
  if (!session) return
  const content = draft.value.trim()
  if (!content) return
  sending = true
  stopTyping()
  const payload = { content }
  if (replying.value) payload.reply_to = replying.value.id
  const tmp = {
    id: `tmp-${++localSeq}`, local: true, sender: myId.value, sender_name: '我',
    content, msg_type: 'text', created_at: new Date().toISOString(),
    pending: true, failed: false, reply_to: payload.reply_to, attachments: [],
  }
  messages.value.push(tmp)
  nextTick(scrollBottom)
  try { await deliver(tmp.id, session, payload) } finally { sending = false }
}
async function deliver(localId, session, payload) {
  const item = messages.value.find((x) => x.id === localId)
  if (item) { item.pending = true; item.failed = false }
  try {
    const m = await imApi.send(session.id, payload)
    const i = messages.value.findIndex((x) => x.id === localId)
    if (i >= 0) messages.value.splice(i, 1, m)
    else if (!messages.value.some((x) => x.id === m.id)) messages.value.push(m)
    // 只有发送成功才清空草稿
    if (activeSession.value?.id === session.id && draft.value.trim() === payload.content) {
      draft.value = ''
      replying.value = null
      showEmoji.value = false
      setSessionDraft(session.id, '')
      await imApi.setting(session.id, { draft: '' })
    }
    nextTick(scrollBottom)
  } catch (e) {
    const cur = messages.value.find((x) => x.id === localId)
    if (cur) { cur.pending = false; cur.failed = true }
    app.toastMsg(e?.message || '发送失败，可点击重试', 'error')
  }
}
function retrySend(m) {
  const session = activeSession.value
  if (!session) return
  const payload = { content: m.content }
  if (m.reply_to) payload.reply_to = m.reply_to
  deliver(m.id, session, payload)
}
// #328 检测光标前的 @ 片段并给出成员候选
function updateMentionCandidates() {
  const el = draftEl.value
  const text = draft.value
  const pos = el && typeof el.selectionStart === 'number' ? el.selectionStart : text.length
  const hit = /@([^\s@]{0,20})$/.exec(text.slice(0, pos))
  if (!hit) { mentionCand.value = []; return }
  const q = hit[1]
  const members = (activeSession.value?.members_info || []).filter((x) => x.id !== myId.value)
  mentionCand.value = members
    .filter((x) => !q || x.display_name.includes(q) || String(x.username || '').includes(q))
    .slice(0, 6)
  mentionIndex.value = 0
}
function insertMention(mem) {
  if (!mem) return
  const el = draftEl.value
  const text = draft.value
  const pos = el && typeof el.selectionStart === 'number' ? el.selectionStart : text.length
  const head = text.slice(0, pos).replace(/@[^\s@]*$/, '') + `@${mem.display_name} `
  draft.value = head + text.slice(pos)
  mentionCand.value = []
  nextTick(() => {
    if (!el) return
    el.focus()
    el.selectionStart = el.selectionEnd = head.length
  })
}
function replyMsg(m) { replying.value = m }
// #176 触屏消息操作条：点「⋯」展开，再次点击收起
const menuFor = ref(null)
function toggleMenu(id) { menuFor.value = menuFor.value === id ? null : id }
function pickEmoji(e) { draft.value += e; showEmoji.value = false }
// #316 草稿摘要同步到会话列表（避免必须刷新列表才看到 [草稿]）
function setSessionDraft(sessionId, text) {
  const s = sessions.value.find((x) => x.id === sessionId)
  if (!s) return
  s.draft = text || ''
  s.draft_summary = text ? text.split(/\s+/).join(' ').slice(0, 50) : ''
}
function saveDraft() {
  if (!activeSession.value) return
  const sessionId = activeSession.value.id
  clearTimeout(draftTimer)
  draftTimer = setTimeout(async () => {
    setSessionDraft(sessionId, draft.value)
    imApi.setting(sessionId, { draft: draft.value }).catch(() => {})
  }, 500)
}
async function togglePin() {
  try {
    await imApi.setting(activeSession.value.id, { is_pinned: !activeSession.value.is_pinned })
    activeSession.value.is_pinned = !activeSession.value.is_pinned
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '置顶操作失败', 'error') }
}
async function toggleArchiveSession() {
  try {
    const v = !activeSession.value.is_archived
    await imApi.setting(activeSession.value.id, { is_archived: v })
    app.toastMsg(v ? '已归档' : '已取消归档', 'success')
    activeSession.value = null
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '归档操作失败', 'error') }
}
async function leave() {
  try {
    if (!confirm('确定退出该会话？群聊将解散或退出')) return
    await imApi.leaveSession(activeSession.value.id)
    activeSession.value = null
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '退出会话失败', 'error') }
}
function recall(m) {
  imApi.recall(m.id).then(() => (m.is_recalled = true)).catch(() => app.toastMsg('撤回失败', 'error'))
}
async function deleteForMe(m) {
  try {
    await imApi.deleteMsg(m.id)
    messages.value = messages.value.filter((x) => x.id !== m.id)
  } catch (e) { app.toastMsg(e?.message || '删除消息失败', 'error') }
}
async function togglePinMsg(m) {
  try {
    await imApi.pinMsg(m.id)
    m.is_pinned = !m.is_pinned
    if (m.is_pinned) pinned.value.unshift(m)
    else pinned.value = pinned.value.filter((p) => p.id !== m.id)
  } catch (e) { app.toastMsg(e?.message || '置顶操作失败', 'error') }
}
function unpin(m) {
  imApi.pinMsg(m.id).then(() => { pinned.value = pinned.value.filter((p) => p.id !== m.id) }).catch(() => app.toastMsg('取消置顶失败', 'error'))
}
// #324 多会话转发，逐会话展示成功 / 失败明细
function forwardMsg(m) {
  forwarding.value = m
  forwardTargets.value = new Set()
  forwardResults.value = []
}
function toggleForward(id) {
  const s = new Set(forwardTargets.value)
  s.has(id) ? s.delete(id) : s.add(id)
  forwardTargets.value = s
}
async function confirmForward() {
  if (!forwardTargets.value.size) return app.toastMsg('请选择会话', 'error')
  try {
    const r = await imx.forward(forwarding.value.id, [...forwardTargets.value])
    forwardResults.value = r.results || []
    app.toastMsg(r.message || '已转发', r.failed_count ? 'error' : 'success')
    if (!r.failed_count) forwarding.value = null
  } catch (e) { app.toastMsg(e?.message || '转发失败', 'error') }
}
function openNew() { showNew.value = true; picked.value = new Set(); newGroupName.value = '' }
let candTimer = null
function loadCandidates() {
  clearTimeout(candTimer)
  candTimer = setTimeout(async () => {
    try {
      candidates.value = (await authApi.directory(candidateQuery.value)).list || []
    } catch (e) { app.toastMsg(e?.message || '搜索失败', 'error') }
  }, 250)
}
function togglePick(id) {
  const s = new Set(picked.value)
  s.has(id) ? s.delete(id) : s.add(id)
  picked.value = s
}
async function startSession() {
  try {
    if (!picked.value.size) return app.toastMsg('请选择成员', 'error')
    const payload = { member_ids: [...picked.value] }
    payload.type = newGroupName.value.trim() || picked.value.size > 1 ? 'group' : 'direct'
    if (newGroupName.value.trim()) payload.name = newGroupName.value.trim()
    const s = await imApi.createSession(payload)
    showNew.value = false
    await loadSessions()
    const found = sessions.value.find((x) => x.id === s.id) || s
    openSession(found)
  } catch (e) { app.toastMsg(e?.message || '创建会话失败', 'error') }
}
let addTimer = null
function searchAdd() {
  clearTimeout(addTimer)
  addTimer = setTimeout(async () => {
    try {
      addCandidates.value = (await authApi.directory(groupAddQ.value)).list || []
    } catch (e) { app.toastMsg(e?.message || '搜索失败', 'error') }
  }, 250)
}
async function addMember(uid) {
  try {
    await imApi.addMembers(activeSession.value.id, [uid])
    app.toastMsg('已添加', 'success')
    const fresh = await imApi.sessionDetail(activeSession.value.id)
    activeSession.value = fresh
  } catch (e) { app.toastMsg(e?.message || '添加成员失败', 'error') }
}
async function kick(uid) {
  try {
    await imApi.removeMember(activeSession.value.id, uid)
    const fresh = await imApi.sessionDetail(activeSession.value.id)
    activeSession.value = fresh
  } catch (e) { app.toastMsg(e?.message || '移出成员失败', 'error') }
}
// #325 导出：选时间范围与格式，下载返回内容并显示条数
function openExport() {
  exportForm.value = { start: '', end: '', format: 'md' }
  showExport.value = true
}
async function doExport() {
  try {
    // fmt 而非 format：format 会被 DRF 当渲染器后缀拦截
    const params = { fmt: exportForm.value.format }
    if (exportForm.value.start) params.start = exportForm.value.start
    if (exportForm.value.end) params.end = exportForm.value.end
    const r = await imx.exportSession(activeSession.value.id, params)
    const type = r.format === 'csv' ? 'text/csv;charset=utf-8' : 'text/markdown;charset=utf-8'
    const blob = new Blob([r.content || ''], { type })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = r.filename || `chat-${activeSession.value.id}.${r.format}`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    showExport.value = false
    app.toastMsg(`已导出 ${r.count} 条${r.truncated ? `（共 ${r.total} 条，超出上限已截断）` : ''}`, 'success')
  } catch (e) { app.toastMsg(e?.message || '导出聊天记录失败', 'error') }
}
// #319 快捷回复：分组 + 排序 + 编辑
async function openQuickReplies() {
  try {
    quickReplies.value = (await imx.quickReplies()).list || []
    resetQRForm()
    showQuickReply.value = true
  } catch (e) { app.toastMsg(e?.message || '加载快捷回复失败', 'error') }
}
function resetQRForm() {
  qrForm.value = { id: null, title: '', content: '', group: '', sort_order: quickReplies.value.length }
}
function editQuickReply(q) {
  qrForm.value = { id: q.id, title: q.title || '', content: q.content || '', group: q.group || '', sort_order: q.sort_order || 0 }
}
function useQuickReply(q) {
  draft.value = q.content
  showQuickReply.value = false
}
async function saveQuickReply() {
  try {
    const payload = {
      title: qrForm.value.title || '',
      content: qrForm.value.content || '',
      group: qrForm.value.group || '',
      sort_order: Number(qrForm.value.sort_order) || 0,
    }
    if (!String(payload.content).trim()) return app.toastMsg('内容不能为空', 'error')
    if (qrForm.value.id) await imx.updateQuickReply(qrForm.value.id, payload)
    else await imx.createQuickReply(payload)
    await openQuickReplies()
  } catch (e) { app.toastMsg(e?.message || '保存快捷回复失败', 'error') }
}
async function delQuickReply(q) {
  try {
    await imx.deleteQuickReply(q.id)
    await openQuickReplies()
  } catch (e) { app.toastMsg(e?.message || '删除快捷回复失败', 'error') }
}
// #319 拖拽排序：按当前展示顺序重排并提交 reorder 接口
function qrDragStart(q) { qrDragId = q.id }
async function qrDrop(target) {
  if (!qrDragId || qrDragId === target.id) return
  const flat = quickReplyGroups.value.flatMap((g) => g.items)
  const from = flat.findIndex((q) => q.id === qrDragId)
  const to = flat.findIndex((q) => q.id === target.id)
  qrDragId = null
  if (from < 0 || to < 0) return
  const [moved] = flat.splice(from, 1)
  flat.splice(to, 0, moved)
  quickReplies.value = flat.map((q, i) => ({ ...q, sort_order: i }))
  try {
    await imx.reorderQuickReplies(flat.map((q, i) => ({ id: q.id, sort_order: i })))
  } catch (e) { app.toastMsg(e?.message || '排序保存失败', 'error') }
}
// #318 关键词最近命中
async function openKeyword() {
  try {
    const r = await imApi.keywordAlert()
    keywordInput.value = (r.keywords || []).join(', ')
    showKeyword.value = true
    loadHits()
  } catch (e) { app.toastMsg(e?.message || '加载关键词失败', 'error') }
}
async function loadHits() {
  try { hits.value = (await imx.keywordHits()).list || [] } catch (e) { hits.value = [] }
}
async function saveKeywords() {
  try {
    const kws = keywordInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    await imApi.saveKeywordAlert(kws)
    app.toastMsg('关键词已保存', 'success')
    showKeyword.value = false
  } catch (e) { app.toastMsg(e?.message || '保存关键词失败', 'error') }
}
// #320 搜索：发送人 / 类型 / 日期 / 含附件 + 分页总数
function openSearch() {
  searchResults.value = []
  searchTotal.value = 0
  searchPages.value = 0
  searchForm.value = { ...searchForm.value, page: 1 }
  showSearch.value = true
}
async function doSearch(page = 1) {
  const f = searchForm.value
  searchForm.value = { ...f, page: Math.max(1, page) }
  const params = { page: searchForm.value.page, page_size: f.page_size || 20 }
  if (f.q) params.q = f.q
  if (f.sender) params.sender = f.sender
  if (f.msg_type) params.msg_type = f.msg_type
  if (f.date_from) params.date_from = f.date_from
  if (f.date_to) params.date_to = f.date_to
  if (f.has_attachment) params.has_attachment = '1'
  try {
    const r = await imx.searchMessages(params)
    searchResults.value = r.list || []
    searchTotal.value = r.total || 0
    searchPages.value = r.pages || 0
  } catch (e) { app.toastMsg(e?.message || '搜索失败', 'error') }
}
// #309 已读明细
async function openReaders(m) {
  try {
    readersData.value = await imx.readers(m.id)
    readersOpen.value = true
  } catch (e) { app.toastMsg(e?.message || '加载已读详情失败', 'error') }
}
function mentionUnread() {
  const list = readersData.value?.unreaders || []
  if (!list.length) return
  const text = list.map((u) => `@${u.display_name} `).join('')
  draft.value = draft.value.trim() ? `${draft.value.trimEnd()} ${text}` : text
  readersOpen.value = false
  nextTick(() => draftEl.value?.focus())
}
// #306 编辑消息
function startEdit(m) {
  editing.value = m
  editText.value = m.content || ''
}
async function saveEdit() {
  const m = editing.value
  if (!m) return
  const content = editText.value.trim()
  if (!content) return app.toastMsg('内容不能为空', 'error')
  try {
    const r = await imx.editMessage(m.id, content)
    const i = messages.value.findIndex((x) => x.id === m.id)
    if (i >= 0) messages.value.splice(i, 1, r)
    editing.value = null
    app.toastMsg('已保存', 'success')
  } catch (e) { app.toastMsg(e?.message || '编辑失败', 'error') }
}
// #307 为所有人删除（广播由后端下发 message.deleted 兜底）
async function deleteForAll(m) {
  if (!confirm('确定对所有人删除这条消息？删除后不可恢复')) return
  try {
    await imx.deleteForAll(m.id)
    messages.value = messages.value.filter((x) => x.id !== m.id)
  } catch (e) { app.toastMsg(e?.message || '删除失败', 'error') }
}
// #308 翻译（本地词典，中英互译）
async function translateMsg(m) {
  try {
    const target = /[\u4e00-\u9fff]/.test(m.content || '') ? 'en' : 'zh'
    const r = await imx.translate(m.id, target)
    translations.value = { ...translations.value, [m.id]: { ...r, open: true, showOriginal: false } }
    if (r.fallback) app.toastMsg('本地词典未覆盖该内容，译文可能未变化', 'error')
  } catch (e) { app.toastMsg(e?.message || '翻译失败', 'error') }
}
function toggleTranslation(id) {
  const t = translations.value[id]
  if (!t) return
  translations.value = { ...translations.value, [id]: { ...t, open: true, showOriginal: !t.showOriginal } }
}
function closeTranslation(id) {
  const t = translations.value[id]
  if (t) translations.value = { ...translations.value, [id]: { ...t, open: false } }
}
// #310 待办面板
function toggleTodoPanel() {
  showTodo.value = !showTodo.value
  if (showTodo.value) loadTodos()
}
async function loadTodos() {
  try { todos.value = (await imx.todos({ sort: 'remind' })).list || [] } catch (e) { app.toastMsg(e?.message || '加载待办失败', 'error') }
}
async function makeTodo(m) {
  try {
    await imx.createTodo({ message_id: m.id })
    app.toastMsg('已加入待办', 'success')
    if (showTodo.value) loadTodos()
  } catch (e) { app.toastMsg(e?.message || '创建待办失败', 'error') }
}
async function toggleTodo(t) {
  try { await imx.updateTodo(t.id, { is_done: !t.is_done }); loadTodos() } catch (e) { app.toastMsg(e?.message || '更新待办失败', 'error') }
}
async function setTodoDue(t, val) {
  try {
    await imx.updateTodo(t.id, { remind_at: val ? `${val}T09:00:00` : '' })
    loadTodos()
  } catch (e) { app.toastMsg(e?.message || '设置到期时间失败', 'error') }
}
async function delTodo(t) {
  try { await imx.deleteTodo(t.id); loadTodos() } catch (e) { app.toastMsg(e?.message || '删除待办失败', 'error') }
}
// #311 @我的消息
async function openMentions() {
  try {
    mentions.value = (await imx.mentions({ limit: 50 })).list || []
    showMentions.value = true
  } catch (e) { app.toastMsg(e?.message || '加载 @ 我的消息失败', 'error') }
}
// #312 / #329 群管理页签
function openGroup() {
  groupTab.value = 'members'
  showGroup.value = true
}
function switchGroupTab(tab) {
  groupTab.value = tab
  if (tab === 'stats') loadStats()
  if (tab === 'files') loadFiles(1)
}
async function loadStats() {
  stats.value = null
  try { stats.value = await imx.stats(activeSession.value.id) } catch (e) { app.toastMsg(e?.message || '加载统计失败', 'error') }
}
async function loadFiles(page = 1) {
  if (!activeSession.value) return
  filesFilter.value.page = Math.max(1, page)
  const params = { page: filesFilter.value.page, page_size: 20 }
  if (filesFilter.value.type) params.type = filesFilter.value.type
  if (filesFilter.value.sender) params.sender = filesFilter.value.sender
  try {
    const r = await imx.sessionFiles(activeSession.value.id, params)
    files.value = r.list || []
    filesTotal.value = r.total || 0
    filesPages.value = r.pages || 0
  } catch (e) { app.toastMsg(e?.message || '加载文件失败', 'error') }
}
// #317 公告未读与发布
function openAnnouncement() {
  showAnn.value = true
  loadAnnouncement()
}
// 会话更新（他人发布公告）时刷新顶栏红点，不打断正在编辑的弹窗
async function refreshAnnouncementFlag() {
  if (!activeSession.value || activeSession.value.type !== 'group' || showAnn.value) return
  try {
    const r = await imx.announcement(activeSession.value.id, false)
    ann.value = { ...ann.value, unread: !!r.unread, can_edit: !!r.can_edit }
  } catch (e) { /* 静默：红点刷新失败不影响使用 */ }
}
async function loadAnnouncement() {
  if (!activeSession.value) return
  try {
    const r = await imx.announcement(activeSession.value.id, false)
    ann.value = r
    if (r.unread) {
      ann.value = { ...(await imx.announcement(activeSession.value.id, true)), unread: false }
      if (activeSession.value) activeSession.value.announcement_unread = false
    }
  } catch (e) { app.toastMsg(e?.message || '加载公告失败', 'error') }
}
async function saveAnnouncement() {
  try {
    ann.value = await imx.publishAnnouncement(activeSession.value.id, ann.value.announcement || '')
    if (activeSession.value) {
      activeSession.value.announcement = ann.value.announcement
      activeSession.value.announcement_unread = false
    }
    app.toastMsg('公告已更新', 'success')
  } catch (e) { app.toastMsg(e?.message || '保存公告失败', 'error') }
}
// #315 标签编辑与筛选
function toggleTag(t) {
  const arr = [...activeTags.value]
  const i = arr.indexOf(t)
  i >= 0 ? arr.splice(i, 1) : arr.push(t)
  activeTags.value = arr
  loadSessions()
}
function clearTags() {
  activeTags.value = []
  loadSessions()
}
function openTags() {
  if (!activeSession.value) return
  tagInput.value = (activeSession.value.tags || []).join(', ')
  showTags.value = true
}
async function saveTags() {
  try {
    const list = tagInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean).slice(0, 10)
    const r = await imx.setSetting(activeSession.value.id, { tags: list })
    if (activeSession.value) activeSession.value.tags = r.tags || list
    showTags.value = false
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '保存标签失败', 'error') }
}
// #326 临时免打扰
async function setMute(duration) {
  const session = activeSession.value
  if (!session) return
  try {
    const r = await imx.mute(session.id, duration)
    session.is_muted = !!r.is_muted
    session.mute_until = r.mute_until
    showMute.value = false
    app.toastMsg(r.message || '已更新免打扰', 'success')
  } catch (e) { app.toastMsg(e?.message || '免打扰设置失败', 'error') }
}
// #327 置顶会话拖拽排序
function onPinDragStart(s) {
  pinDrag = s.is_pinned ? s.id : null
  pinDragId.value = pinDrag
}
function onPinDragEnd() {
  if (!pinDragId.value) return
  pinDrag = null
  pinDragId.value = null
}
async function onPinDrop(target) {
  const fromId = pinDrag
  pinDrag = null
  pinDragId.value = null
  if (!fromId || fromId === target.id || !target.is_pinned) return
  const list = sessions.value.filter((x) => x.is_pinned)
  const from = list.findIndex((x) => x.id === fromId)
  const to = list.findIndex((x) => x.id === target.id)
  if (from < 0 || to < 0) return
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  const items = list.map((x, i) => ({ session_id: x.id, pin_order: i }))
  items.forEach((it) => {
    const s = sessions.value.find((x) => x.id === it.session_id)
    if (s) { s.pin_order = it.pin_order; s.is_pinned = true }
  })
  try {
    await imx.pinOrder(items)
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '置顶排序保存失败', 'error') }
}
// #321 / #311 / #318 / #320 定位与跳转
function scrollBottom() { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight }
function scrollToMessage(id, highlight = true) {
  const el = document.getElementById(`msg-${id}`)
  if (!el) return false
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  if (highlight) {
    highlightId.value = id
    setTimeout(() => { if (highlightId.value === id) highlightId.value = null }, 2000)
  }
  return true
}
// 目标消息不在当前页时，按 before 游标补拉一页
async function ensureMessageLoaded(id) {
  if (messages.value.some((m) => m.id === id)) return true
  if (!activeSession.value) return false
  try {
    const r = await imx.messages(activeSession.value.id, { before: Number(id) + 1, page_size: 30 })
    const extra = (r.list || []).filter((m) => !messages.value.some((x) => x.id === m.id))
    if (!extra.length) return false
    messages.value = [...extra, ...messages.value]
    return true
  } catch (e) { return false }
}
async function jumpToMessage(id) {
  if (!id) return
  const ok = await ensureMessageLoaded(id)
  if (!ok) return app.toastMsg('原消息不在当前历史中', 'error')
  await nextTick()
  scrollToMessage(id)
}
function jumpToQuote(m) { jumpToMessage(m.reply_to_info?.id) }
async function jumpToResult(row) {
  if (!row) return
  showSearch.value = false
  showMentions.value = false
  showKeyword.value = false
  let s = sessions.value.find((x) => x.id === row.session)
  if (!s && activeSession.value?.id === row.session) s = activeSession.value
  if (!s) {
    try { s = await imApi.sessionDetail(row.session) } catch (e) { return app.toastMsg('会话不存在或无权访问', 'error') }
  }
  if (activeSession.value?.id !== s.id) await openSession(s)
  await jumpToMessage(row.id)
}

// #344 仪表盘「提到我」等入口通过 ?session=&message= 跳转，进入后自动打开并定位
async function applyRouteTarget() {
  const sid = Number(route.query.session)
  if (!sid) return
  await loadSessions()
  const mid = Number(route.query.message)
  let s = sessions.value.find((x) => x.id === sid)
  if (!s) {
    try { s = await imApi.sessionDetail(sid) } catch (e) { return }
  }
  await openSession(s)
  if (mid) await jumpToMessage(mid)
}

onMounted(() => {
  loadSessions()
  applyRouteTarget()
  // #326 每 30 秒刷新一次免打扰剩余时间
  tickTimer = setInterval(() => (nowTs.value = Date.now()), 30000)
  unsub = app.onChat((type, data) => {
    if (type === 'chat.message' && activeSession.value && data?.session === activeSession.value.id) {
      // 自己的消息会先以本地占位气泡出现，回显时替换占位避免重复
      if (data.sender === myId.value) {
        const i = messages.value.findIndex((m) => m.local && m.content === data.content)
        if (i >= 0) messages.value.splice(i, 1)
      }
      if (!messages.value.some((m) => m.id === data.id)) messages.value.push(data)
      imApi.setting(activeSession.value.id, { mark_read: true })
      nextTick(scrollBottom)
    } else if (type === 'chat.message') {
      loadSessions()
    } else if (type === 'message.recalled') {
      const m = messages.value.find((x) => x.id === (data?.id ?? data?.message_id))
      if (m) m.is_recalled = true
    } else if (type === 'message.pinned') {
      const m = messages.value.find((x) => x.id === data?.id)
      if (m) m.is_pinned = !!data?.is_pinned
    } else if (type === 'message.edited') {
      const i = messages.value.findIndex((x) => x.id === data?.id)
      if (i >= 0) messages.value.splice(i, 1, { ...messages.value[i], ...data })
    } else if (type === 'message.deleted') {
      const i = messages.value.findIndex((x) => x.id === data?.id)
      if (i >= 0) messages.value.splice(i, 1)
    } else if (type === 'session.updated') {
      loadSessions()
      if (activeSession.value && data?.session_id === activeSession.value.id) refreshAnnouncementFlag()
    } else if (type === 'ws.reconnected') {
      // 断线期间的消息不会补发：重连后重新拉列表与当前会话
      loadSessions()
      refreshActiveMessages()
    } else if ((type === 'chat.typing' || type === 'session.typing') && activeSession.value && data?.session_id === activeSession.value.id) {
      // #314 自己上报的状态回显时忽略；typing=false 立即清空提示
      if (data?.user_id && data.user_id === myId.value) return
      if (data?.is_typing === false) { typing.value = ''; return }
      typing.value = data.user || data.display_name || ''
      clearTimeout(typingTimer)
      typingTimer = setTimeout(() => (typing.value = ''), 2000)
    }
  })
})
onBeforeUnmount(() => {
  loadSeq += 1
  clearTimeout(draftTimer)
  clearTimeout(typingTimer)
  clearTimeout(typingSendTimer)
  clearInterval(tickTimer)
  if (unsub) unsub()
})
</script>
