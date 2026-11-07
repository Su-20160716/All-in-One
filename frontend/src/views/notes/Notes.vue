<template>
  <div class="note-root flex gap-4" :class="[`density-${density}`, focusMode ? 'focus-mode' : '']">
    <!-- 目录树（F252 专注模式下隐藏） -->
    <div v-if="!focusMode" class="card no-print w-64 shrink-0 self-start p-3">
      <div class="mb-2 flex items-center justify-between px-1">
        <span class="text-[12px] font-semibold text-ink-600">
          {{ sideTab === 'trash' ? '回收站' : sideTab === 'archived' ? '归档' : '笔记目录' }}</span>
        <button v-if="sideTab !== 'trash'" class="btn-primary px-2 py-1 text-[11px]" @click="createNote()">＋ 新建</button>
      </div>
      <div class="mb-2 flex gap-1">
        <button class="flex-1 rounded-control py-1 text-[12px]" :class="sideTab === 'all' ? 'bg-brand-50 text-brand-700' : 'text-ink-500 hover:bg-ink-50'" @click="switchSide('all')">全部</button>
        <button class="flex-1 rounded-control py-1 text-[12px]" :class="sideTab === 'archived' ? 'bg-amber-50 text-amber-600' : 'text-ink-500 hover:bg-ink-50'" @click="switchSide('archived')">归档</button>
        <button class="flex-1 rounded-control py-1 text-[12px]" :class="sideTab === 'trash' ? 'bg-rose-50 text-rose-600' : 'text-ink-500 hover:bg-ink-50'" @click="switchSide('trash')">回收站</button>
      </div>

      <!-- F571 只看置顶 -->
      <div v-if="sideTab === 'all'" class="mb-2">
        <button class="w-full rounded-control py-1 text-[12px]"
                :class="pinnedOnly ? 'bg-brand-50 text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                @click="togglePinnedOnly">📌 {{ pinnedOnly ? '显示全部笔记' : '只看置顶笔记' }}</button>
      </div>

      <div v-if="sideTab === 'trash'" class="space-y-1">
        <div v-for="n in trashList" :key="n.id" class="flex items-center justify-between rounded-control px-2 py-1.5 text-[13px] hover:bg-ink-50">
          <span class="truncate">🗑 {{ n.title }}</span>
          <span class="flex shrink-0 gap-1">
            <button class="text-[11px] text-brand-600" @click="restoreNote(n)">还原</button>
            <button class="text-[11px] text-rose-500" @click="destroyNote(n)">清除</button>
          </span>
        </div>
        <button v-if="trashList.length" class="mt-2 w-full rounded-control bg-rose-50 py-1.5 text-[12px] text-rose-600" @click="emptyTrash">清空回收站</button>
      </div>

      <div v-else class="space-y-0.5 text-[13px]">
        <!-- F582 分组文件夹 -->
        <div v-if="sideTab === 'all'" class="mb-2 border-b border-ink-100 pb-2">
          <div class="mb-1 flex items-center justify-between px-1">
            <span class="text-[11px] text-ink-400">文件夹</span>
            <button class="text-[11px] text-brand-600" @click="showNewFolder = true">＋新建</button>
          </div>
          <div class="flex flex-wrap gap-1 px-1">
            <button class="rounded-control px-1.5 py-0.5 text-[11px]"
                    :class="activeFolder ? 'bg-ink-50 text-ink-500 hover:bg-ink-100' : 'bg-brand-50 text-brand-700'"
                    @click="filterFolder(null)">全部</button>
            <button v-for="f in noteFolders" :key="f.id" class="rounded-control px-1.5 py-0.5 text-[11px]"
                    :class="activeFolder === f.id ? 'bg-brand-50 text-brand-700' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
                    @click="filterFolder(f.id)">📁 {{ f.name }}<span class="opacity-60"> {{ f.note_count }}</span></button>
          </div>
        </div>
        <div v-if="selectedTags.length" class="mb-1 rounded-control bg-brand-50/50 px-2 py-1.5 text-[11px] text-brand-700">
          <div class="flex items-center justify-between">
            <span>标签筛选（{{ tagMode === 'all' ? '交集' : '并集' }}）</span>
            <span class="flex gap-2">
              <button class="underline" @click="toggleTagMode">{{ tagMode === 'all' ? '切并集' : '切交集' }}</button>
              <button @click="clearTags">×</button>
            </span>
          </div>
          <div class="mt-1 flex flex-wrap gap-1">
            <span v-for="t in selectedTags" :key="t" class="tag tag-brand">{{ t }} <button class="ml-0.5" @click="toggleTagFilter(t)">×</button></span>
          </div>
        </div>
        <div v-if="activeFolder" class="mb-1 rounded-control bg-brand-50/50 px-2 py-1.5 text-[12px] text-brand-700">
          📁 {{ folderName(activeFolder) }}<button @click="filterFolder(null)"> ×</button>
        </div>
        <div v-for="row in shownRows" :key="row.n.id"
             class="note-row flex cursor-pointer items-center gap-1 rounded-control px-1 hover:bg-ink-50"
             :class="activeNote === row.n.id ? 'bg-brand-50 text-brand-700' : ''"
             :draggable="row.n.is_pinned ? 'true' : 'false'"
             @dragstart="onPinDragStart(row.n.id)"
             @dragover.prevent
             @drop="onPinDrop(row.n.id)"
             @click="openNote(row.n.id)">
          <input type="checkbox" class="shrink-0" :checked="pickedIds.has(row.n.id)" title="批量选择" @click.stop @change="togglePick(row.n.id)" />
          <button v-if="row.hasChildren" class="w-4 shrink-0 text-[10px] text-ink-400" @click.stop="toggleExpand(row.n.id)">{{ row.expanded ? '▾' : '▸' }}</button>
          <span v-else class="w-4 shrink-0"></span>
          <span class="min-w-0 flex-1 truncate" :style="{ paddingLeft: row.depth * 8 + 'px' }">
            <img v-if="row.n.cover_thumb" :src="row.n.cover_thumb" class="mr-1 inline-block h-4 w-6 rounded object-cover align-middle" alt="" />
            <span v-if="row.n.color" class="mr-1 inline-block h-2 w-2 shrink-0 rounded-full align-middle" :style="{ background: colorHex(row.n.color) }"></span>{{ row.n.icon || noteIcon(row.n) }} {{ row.n.title }}
          </span>
        </div>
        <div v-if="!shownRows.length" class="py-6 text-center text-[12px] text-ink-400">没有匹配的笔记</div>

        <!-- F247–F251 批量操作栏 -->
        <div v-if="pickedIds.size" class="mt-2 rounded-control border border-brand-200 bg-brand-50/60 p-2 text-[11px] text-brand-800">
          <div class="flex items-center justify-between">
            <span>已选 {{ pickedIds.size }} 篇</span>
            <button class="text-ink-500" @click="clearPicks">取消</button>
          </div>
          <div class="mt-1 flex flex-wrap items-center gap-1">
            <select class="input py-0.5 text-[11px]" @change="batchFolder($event.target.value); $event.target.value = ''">
              <option value="">移动到文件夹…</option>
              <option v-for="f in noteFolders" :key="f.id" :value="f.id">{{ f.name }}</option>
            </select>
            <input v-model="batchTagInput" class="input w-24 py-0.5 text-[11px]" placeholder="标签名" list="noteCommonTags" />
            <datalist id="noteCommonTags"><option v-for="t in tags" :key="t.id" :value="t.name" /></datalist>
            <button class="tag" @click="batchTag('tag')">＋标签</button>
            <button class="tag" @click="batchTag('untag')">－标签</button>
            <span class="flex items-center gap-1">
              <button v-for="(label, key) in NOTE_COLORS" :key="key" class="h-3.5 w-3.5 rounded-full border border-white"
                      :style="{ background: colorHex(key) }" :title="'标为' + label" @click="batchColor(key)"></button>
            </span>
          </div>
        </div>
      </div>

      <!-- #24 标签云 -->
      <div v-if="sideTab !== 'trash'" class="mt-3 border-t border-ink-100 pt-2">
        <div class="mb-1 flex items-center justify-between px-1">
          <span class="text-[11px] text-ink-400">标签云</span>
          <button class="text-[11px] text-brand-600" @click="showTagMgr = true">管理</button>
        </div>
        <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-1">
          <span v-for="t in cloudTags" :key="t.id" class="cursor-pointer text-brand-600 hover:underline"
                :class="selectedTags.includes(t.name) ? 'font-semibold underline' : ''"
                :style="{ fontSize: (11 + (t.weight || 0) * 6) + 'px', opacity: 0.55 + (t.weight || 0) * 0.45 }"
                @click="toggleTagFilter(t.name)">#{{ t.name }}</span>
        </div>
      </div>

      <div class="mt-3 space-y-0.5 border-t border-ink-100 pt-2">
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showQuick = true">⚡ 快速记录</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="toggleDensity">{{ density === 'compact' ? '🗂 切换舒适密度' : '🗂 切换紧凑密度' }}</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showTemplates = true">📋 从模板新建</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showImport = true">📥 批量导入 MD</button>
        <button v-if="current" class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="insertTemplatePrompt">📥 插入模板到正文</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showStats = true; loadStats()">📊 写作统计</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="exportSelected">⬇ 导出所选 ZIP</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="exportAll">⬇ 导出全部 ZIP</button>
      </div>

      <!-- F565–F580 新增工具入口 -->
      <div class="mt-3 space-y-0.5 border-t border-ink-100 pt-2">
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openGoals">🎯 字数目标</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openDiary">📅 日记视图</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openRandom">🎲 随机回顾</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openHealth">🩺 健康度报告</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openMentions">💬 未链接提及</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openTodos">
          ☑ 待办清单<span v-if="todoOpenCount" class="ml-1 rounded-pill bg-brand-50 px-1.5 text-[10px] text-brand-700">{{ todoOpenCount }}</span>
        </button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openSnippets">✂ 片段库</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openWeekly">📋 每周回顾</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="openWordbook">📚 生词本</button>
      </div>
    </div>

    <!-- 编辑器 -->
    <div class="min-w-0 flex-1" :class="focusMode ? 'editor-focus' : ''">
      <div v-if="current" class="card overflow-hidden" :class="readingMode ? 'reading-mode' : ''">
        <div class="no-print flex flex-wrap items-center gap-2 border-b border-ink-100 px-4 py-2">
          <input type="checkbox" :checked="exportIds.has(current.id)" @change="toggleExportPick(current.id)" title="勾选导出" />
          <!-- F238 自定义图标 -->
          <button class="btn-ghost px-1 text-[16px]" title="笔记图标" @click="showIconPicker = !showIconPicker">{{ current.icon || '🙂' }}</button>
          <input v-model="current.title" class="min-w-[120px] flex-1 border-none bg-transparent text-[16px] font-semibold focus:outline-none" placeholder="笔记标题" />
          <!-- F252 专注模式 -->
          <button class="btn-ghost px-2 text-[12px]" :class="focusMode ? 'text-brand-600' : ''" title="专注模式（Esc 退出）" @click="toggleFocus">🎯</button>
          <!-- F242 待办进度 -->
          <button class="btn-ghost px-2 text-[12px]" title="待办完成度，点击打开待办弹窗" @click="openTodos">
            ☑ {{ current.todo_done || 0 }}/{{ current.todo_total || 0 }}
          </button>
          <template v-if="!focusMode">
            <button class="btn-ghost px-2 text-[12px]" :class="current.is_favorite ? 'text-amber-500' : ''" @click="toggleFlag('is_favorite')">★</button>
            <button class="btn-ghost px-2 text-[12px]" :class="current.is_pinned ? 'text-brand-600' : ''" @click="toggleFlag('is_pinned')">📌</button>
            <button class="btn-ghost px-2 text-[12px]" :class="current.is_public ? 'text-emerald-600' : ''" @click="toggleFlag('is_public')">🌐</button>
            <button class="btn-ghost px-2 text-[12px]" :class="current.is_archived ? 'text-amber-600' : ''" @click="toggleArchive">{{ current.is_archived ? '取消归档' : '归档' }}</button>
            <!-- F572 六色标记 / F577 阅读模式 / F575 合并 / F576 拆分 / F581 引用 -->
            <button class="btn-ghost px-2 text-[12px]" title="颜色标记" @click="showColorPicker = true">
              <span class="inline-block h-3 w-3 rounded-full border border-ink-200 align-middle"
                    :style="{ background: current.color ? colorHex(current.color) : '#ffffff' }"></span>
            </button>
            <button class="btn-ghost px-2 text-[12px]" :class="readingMode ? 'text-brand-600' : ''" @click="toggleReading">{{ readingMode ? '✍ 写作' : '📖 阅读' }}</button>
            <!-- F239 封面 / F240 提醒 / F237 附件 -->
            <button class="btn-ghost px-2 text-[12px]" :class="current.cover_thumb ? 'text-brand-600' : ''" title="设置封面图" @click="openCoverPicker">🖼 封面</button>
            <button class="btn-ghost px-2 text-[12px]" :class="current.remind_at ? 'text-amber-600' : ''" title="提醒我回看" @click="openReminder">⏰</button>
            <button class="btn-ghost px-2 text-[12px]" title="附件" @click="openAttachments">📎 附件</button>
            <!-- F236 讨论 / F244 查找替换 -->
            <button class="btn-ghost px-2 text-[12px]" :class="rightPanel && rightTab === 'comments' ? 'text-brand-600' : ''" @click="openCommentsPanel">
              💬 讨论<span v-if="current.comment_count" class="ml-0.5 text-rose-500">{{ current.comment_count }}</span>
            </button>
            <button class="btn-ghost px-2 text-[12px]" :class="showFind ? 'text-brand-600' : ''" @click="showFind = !showFind">🔍 查找</button>
            <!-- F255 打印 -->
            <button class="btn-ghost px-2 text-[12px]" @click="printNote">🖨 打印</button>
            <button class="btn-ghost px-2 text-[12px]" @click="openMerge">🔀 合并</button>
            <button class="btn-ghost px-2 text-[12px]" @click="openSplit">✂ 拆分</button>
            <button class="btn-ghost px-2 text-[12px]" @click="openCitation">🔖 引用</button>
            <button v-if="selectedWord" class="btn-ghost px-2 text-[12px] text-brand-600" title="存入学习区生词本" @click="saveWord">📚 存生词「{{ selectedWord }}」</button>
            <button class="btn-ghost px-2 text-[12px]" @click="loadOutline">大纲</button>
            <button class="btn-ghost px-2 text-[12px]" @click="aiOutline">✨AI大纲</button>
            <button class="btn-ghost px-2 text-[12px]" @click="loadFlashcards">🃏回顾</button>
            <button class="btn-ghost px-2 text-[12px]" :class="rightPanel ? 'text-brand-600' : ''" @click="toggleRightPanel">
              🔗 关联<span v-if="backlinkCount" class="ml-0.5 text-brand-600">{{ backlinkCount }}</span>
            </button>
            <button class="btn-ghost px-2 text-[12px]" :class="collabMode ? 'text-emerald-600' : ''" @click="toggleCollab">👥 协同</button>
            <button class="btn-ghost px-2 text-[12px]" @click="duplicate">复制</button>
            <button class="btn-ghost px-2 text-[12px]" @click="exportNote">导出</button>
            <button class="btn-ghost px-2 text-[12px]" @click="showVersions = true; loadVersions()">🕘</button>
            <button class="btn-ghost px-2 text-[12px]" @click="showShortcuts = true">？</button>
            <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="deleteNote">🗑</button>
          </template>
        </div>
        <!-- F238 emoji 选择器 -->
        <div v-if="showIconPicker" class="no-print flex flex-wrap items-center gap-1 border-b border-ink-100 bg-ink-50/60 px-4 py-1.5">
          <button v-for="e in EMOJIS" :key="e" class="rounded px-1 text-[15px] hover:bg-white" @click="setIcon(e)">{{ e }}</button>
          <button class="ml-2 text-[11px] text-ink-500 hover:text-rose-500" @click="setIcon('')">清除图标</button>
        </div>
        <!-- F241 阅读排版控制 -->
        <div v-if="readingMode" class="no-print flex flex-wrap items-center gap-3 border-b border-ink-100 px-4 py-1.5 text-[11px] text-ink-500">
          <label class="flex items-center gap-1">字号
            <input v-model.number="typo.fontSize" type="range" min="14" max="20" step="0.5" class="w-20" @input="persistTypo" />
            <span>{{ typo.fontSize }}px</span>
          </label>
          <label class="flex items-center gap-1">行距
            <input v-model.number="typo.lineHeight" type="range" min="1.5" max="2" step="0.05" class="w-20" @input="persistTypo" />
            <span>{{ typo.lineHeight }}</span>
          </label>
          <label class="flex items-center gap-1">段宽
            <input v-model.number="typo.width" type="range" min="640" max="960" step="20" class="w-20" @input="persistTypo" />
            <span>{{ typo.width }}px</span>
          </label>
          <button class="text-brand-600 hover:underline" @click="resetTypo">恢复默认</button>
          <span v-if="current.remind_at" class="ml-auto text-amber-600">⏰ {{ formatTime(current.remind_at) }}</span>
        </div>
        <!-- F244 查找/替换面板 -->
        <div v-if="showFind" class="no-print flex flex-wrap items-center gap-2 border-b border-ink-100 bg-ink-50/60 px-4 py-1.5 text-[12px]">
          <input v-model="findQuery" class="input w-40 py-1 text-[12px]" placeholder="查找内容" />
          <input v-model="findReplaceText" class="input w-40 py-1 text-[12px]" placeholder="替换为" />
          <label class="flex items-center gap-1 text-[11px] text-ink-500"><input v-model="findCaseSensitive" type="checkbox" /> 区分大小写</label>
          <label class="flex items-center gap-1 text-[11px] text-ink-500"><input v-model="findWholeWord" type="checkbox" /> 整词匹配</label>
          <span class="text-ink-500">命中 {{ findCount }} 处</span>
          <button class="btn-outline px-2 py-1 text-[11px]" :disabled="!findCount" @click="replaceOne">替换当前</button>
          <button class="btn-outline px-2 py-1 text-[11px]" :disabled="!findCount" @click="replaceAll">全部替换</button>
        </div>
        <div class="no-print flex border-b border-ink-100">
          <button class="flex-1 border-b-2 px-3 py-2 text-[13px]" :class="editorTab === 'write' ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'" @click="editorTab = 'write'">编辑</button>
          <button class="flex-1 border-b-2 px-3 py-2 text-[13px]" :class="editorTab === 'preview' ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'" @click="editorTab = 'preview'">预览</button>
        </div>
        <div class="flex">
          <div class="relative flex-1">
            <textarea v-show="editorTab !== 'preview'"
                      ref="contentEl"
                      :value="collabMode ? collabText : current.content"
                      class="h-[52vh] w-full resize-none bg-ink-50/50 p-4 font-mono text-[13px] leading-relaxed focus:outline-none"
                      :style="editorStyle"
                      placeholder="支持 Markdown…  输入 [[ 可引用其他笔记建立双链，可直接粘贴/拖入图片"
                      @input="onContentInput"
                      @keyup="editorKeyup($event.target)"
                      @click="editorKeyup($event.target)"
                      @scroll="onPaneScroll"
                      @paste="onContentPaste"
                      @drop="onContentDrop"
                      @dragover.prevent
                      @mouseup="trackSelection"></textarea>
            <div v-if="linkSuggest.length && editorTab !== 'preview'"
                 class="absolute left-4 top-2 z-10 w-60 overflow-hidden rounded-control border border-ink-100 bg-white shadow-pop">
              <div class="border-b border-ink-50 px-2 py-1 text-[11px] text-ink-400">选择要引用的笔记</div>
              <button v-for="s in linkSuggest" :key="s.id"
                      class="block w-full px-2 py-1.5 text-left hover:bg-ink-50"
                      @click="insertLink(s.title)">
                <div class="truncate text-[12px] font-medium text-ink-700">{{ s.title }}</div>
                <div v-if="s.excerpt" class="truncate text-[11px] text-ink-400">{{ s.excerpt }}</div>
              </button>
              <button class="block w-full px-2 py-1.5 text-left text-[12px] text-ink-400 hover:bg-ink-50"
                      @click="linkSuggest = []">取消</button>
            </div>
            <div v-if="uploadingImage" class="absolute bottom-3 right-3 rounded-pill bg-white px-2 py-1 text-[11px] text-brand-600 shadow-pop">
              图片上传中… {{ uploadProgress }}%
            </div>
          </div>
          <!-- #18 字数/结构统计侧栏 -->
          <div class="no-print hidden w-40 shrink-0 border-l border-ink-100 bg-ink-50/30 p-3 text-[11px] text-ink-500 lg:block">
            <div class="mb-1 font-medium text-ink-600">结构统计</div>
            <div>字数：{{ stat.words }} 字</div>
            <div>段落：{{ stat.paras }} 段</div>
            <div>标题：{{ stat.headings }} 个</div>
            <div>列表项：{{ stat.lists }} 条</div>
            <div>预计阅读：{{ statReadMin }} 分钟</div>
            <div class="mt-2">待办：{{ current.todo_done || 0 }}/{{ current.todo_total || 0 }}</div>
          </div>
        </div>
        <div v-if="editorTab !== 'write'" ref="previewRef" class="markdown-body print-body h-[52vh] overflow-y-auto bg-white p-4"
             :style="previewStyle"
             @scroll="onPaneScroll"
             @click="onPreviewClick"
             @mouseover="onPreviewHover"
             @mouseleave="hideWikiPreview"
             v-html="rendered" @mouseup="trackSelection(null)"></div>
        <div class="no-print flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
          <span>
            v{{ current.version }} · {{ current.words || 0 }} 字 · 约 {{ current.reading_minutes || statReadMin }} 分钟 · {{ formatTime(current.updated_at) }}
            <span v-if="current.source" class="ml-1">{{ sourceLabel(current.source) }}</span>
            <span v-if="collabMode" class="ml-2 tag" :class="collabStatus === 'ready' ? 'tag-brand' : ''">
              协同 {{ collabStatusLabel }}<span v-if="collabPeers.length"> · {{ collabPeers.join('、') }}</span>
            </span>
          </span>
          <div class="flex flex-wrap items-center gap-2">
            <!-- F582 当前笔记所属文件夹 -->
            <select class="input w-28 py-1 text-[11px]" :value="current.folder ?? null" @change="moveToFolder($event.target.value)">
              <option :value="null">未分组</option>
              <option v-for="f in noteFolders" :key="f.id" :value="f.id">📁 {{ f.name }}</option>
            </select>
            <input v-model="tagInput" class="input w-32 py-1 text-[12px]" placeholder="+ 标签" @keyup.enter="addTag" />
            <span v-for="t in current.tag_names" :key="t" class="tag tag-brand">{{ t }} <button class="ml-0.5" @click="removeTag(t)">×</button></span>
            <span v-if="collabMode" class="text-emerald-500">协同模式（自动同步）</span>
            <span v-else-if="saving" class="text-emerald-500">已保存</span>
          </div>
        </div>
      </div>
      <div v-else class="card grid place-items-center py-24">
        <div class="text-center">
          <div class="text-[36px]">📝</div>
          <div class="mt-2 text-[14px] font-medium text-ink-700">选择或创建一篇笔记</div>
          <button class="btn-primary mt-4" @click="createNote()">新建笔记</button>
        </div>
      </div>
    </div>

    <!-- 右侧：关联（双链+相关推荐）/ AI / 讨论 -->
    <aside v-if="current && rightPanel && !focusMode" class="card no-print w-72 shrink-0 self-start">
      <div class="card p-3">
        <div class="mb-2 flex gap-1 text-[12px]">
          <button class="flex-1 rounded-control px-2 py-1"
                  :class="rightTab === 'links' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                  @click="rightTab = 'links'">反链 {{ backlinkCount }}</button>
          <button class="flex-1 rounded-control px-2 py-1"
                  :class="rightTab === 'comments' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                  @click="rightTab = 'comments'; loadComments()">讨论 {{ comments.length }}</button>
          <button class="flex-1 rounded-control px-2 py-1"
                  :class="rightTab === 'ai' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                  @click="rightTab = 'ai'">AI 助手</button>
        </div>

        <!-- 双链 -->
        <div v-if="rightTab === 'links'" class="space-y-2">
          <div>
            <div class="mb-1 text-[11px] font-medium text-ink-500">反向链接（谁引用了本篇）</div>
            <div v-if="!backlinks.length" class="rounded-control bg-ink-50 p-2 text-[11px] text-ink-400">
              还没有笔记引用本篇。在别的笔记里写 <code>[[{{ current.title }}]]</code> 即可建立双链。
            </div>
            <button v-for="b in backlinks" :key="b.link_id"
                    class="block w-full rounded-control px-2 py-1.5 text-left hover:bg-ink-50"
                    @click="openNote(b.note_id)">
              <div class="truncate text-[12px] font-medium text-ink-700">{{ b.title }}</div>
              <div class="truncate text-[11px] text-ink-400">{{ b.excerpt }}</div>
            </button>
          </div>

          <div class="border-t border-ink-100 pt-2">
            <div class="mb-1 text-[11px] font-medium text-ink-500">出链（本篇引用了谁）</div>
            <div v-if="!outgoingLinks.length" class="text-[11px] text-ink-400">暂无出链</div>
            <div v-for="o in outgoingLinks" :key="o.link_id" class="flex items-center gap-1 py-0.5 text-[12px]">
              <span :class="o.resolved ? 'text-brand-600' : 'text-amber-500'">{{ o.resolved ? '→' : '○' }}</span>
              <button v-if="o.resolved" class="truncate text-ink-700 hover:underline" @click="openNote(o.target_id)">
                {{ o.title }}
              </button>
              <span v-else class="truncate text-amber-600">{{ o.title }}</span>
              <button v-if="!o.resolved" class="ml-auto shrink-0 text-[11px] text-brand-600" @click="createFromTitle(o.title)">
                创建
              </button>
            </div>
          </div>

          <div v-if="dangling.length" class="border-t border-ink-100 pt-2">
            <div class="mb-1 text-[11px] font-medium text-ink-500">悬浮链接（被引用但未创建）</div>
            <div v-for="d in dangling" :key="d.title" class="flex items-center gap-1 py-0.5 text-[12px]">
              <span class="truncate text-ink-600">{{ d.title }}</span>
              <span class="text-[11px] text-ink-400">×{{ d.ref_count }}</span>
              <button class="ml-auto shrink-0 text-[11px] text-brand-600" @click="createFromTitle(d.title)">创建</button>
            </div>
          </div>

          <button class="btn-outline w-full py-1 text-[12px]" @click="loadGraph">查看关系图谱</button>

          <!-- F245 相关笔记推荐 -->
          <div class="border-t border-ink-100 pt-2">
            <div class="mb-1 flex items-center justify-between text-[11px] font-medium text-ink-500">
              <span>相关笔记（按标签/标题相似）</span>
              <button class="text-brand-600" @click="loadRelated">刷新</button>
            </div>
            <div v-if="!relatedNotes.length" class="text-[11px] text-ink-400">暂无相关推荐</div>
            <button v-for="r in relatedNotes" :key="r.id"
                    class="block w-full rounded-control px-2 py-1.5 text-left hover:bg-ink-50"
                    @click="openNote(r.id)">
              <div class="truncate text-[12px] font-medium text-ink-700">{{ r.icon || '📄' }} {{ r.title }}</div>
              <div class="truncate text-[11px] text-ink-400">{{ r.reason }}</div>
            </button>
          </div>
        </div>

        <!-- F236 讨论 -->
        <div v-else-if="rightTab === 'comments'" class="space-y-2">
          <div v-if="commentParent" class="rounded-control bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
            回复 @{{ commentParentAuthor }}<button class="ml-1 underline" @click="cancelReply">取消</button>
          </div>
          <div class="rounded-control bg-ink-50 p-2 text-[11px] text-ink-500">
            <div class="flex items-center justify-between">
              <span>引用选中文本</span>
              <button class="text-brand-600" @click="grabQuote">引用正文选中</button>
            </div>
            <div class="mt-1 max-h-16 overflow-y-auto whitespace-pre-wrap">{{ commentQuote || '（未选择，可直接评论）' }}</div>
          </div>
          <textarea v-model="commentDraft" class="input h-20 resize-none text-[12px]" placeholder="写下评审意见…"></textarea>
          <div class="flex justify-end gap-1">
            <button class="btn-ghost px-2 py-1 text-[12px]" @click="commentDraft = ''; commentQuote = ''; cancelReply()">清空</button>
            <button class="btn-primary px-2 py-1 text-[12px]" @click="submitComment">发表</button>
          </div>
          <div v-if="commentFilterOpen" class="text-[11px] text-ink-400">
            未解决 {{ unresolvedCount }} 条 ·
            <button class="text-brand-600" @click="toggleCommentFilter">只看全部</button>
          </div>
          <div class="max-h-[46vh] space-y-2 overflow-y-auto">
            <div v-for="c in shownComments" :key="c.id" class="rounded-card border border-ink-100 p-2"
                 :class="[c.resolved ? 'opacity-60' : '', c.parent ? 'ml-3' : '']">
              <div class="flex items-center justify-between text-[11px] text-ink-400">
                <span>{{ c.author_name || '匿名' }} · {{ formatTime(c.created_at) }}</span>
                <span class="flex gap-1">
                  <button v-if="!c.parent && !c.resolved" class="text-emerald-600" @click="resolveComment(c)">解决</button>
                  <button v-if="!c.parent" class="text-brand-600" @click="startReply(c)">回复</button>
                  <button class="text-rose-500" @click="removeComment(c)">删除</button>
                </span>
              </div>
              <div v-if="c.quote" class="mt-1 border-l-2 border-amber-300 pl-1.5 text-[11px] text-ink-500">{{ c.quote }}</div>
              <div class="mt-1 whitespace-pre-wrap text-[12px] text-ink-700">{{ c.content }}</div>
              <div v-if="c.reply_count" class="mt-0.5 text-[10px] text-ink-400">{{ c.reply_count }} 条回复</div>
            </div>
            <div v-if="!comments.length" class="py-4 text-center text-[11px] text-ink-400">还没有讨论</div>
          </div>
        </div>

        <!-- AI -->
        <div v-else class="space-y-2">
          <button class="btn-primary w-full py-1.5 text-[12px]" :disabled="aiBusy" @click="aiSummarize">
            {{ aiBusy ? '生成中…' : '✨ 生成 AI 摘要' }}
          </button>
          <div v-if="aiSummary" class="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-control bg-ink-50 p-2 text-[12px] leading-relaxed text-ink-700">
            {{ aiSummary }}
          </div>
          <ul v-if="aiPoints.length" class="space-y-0.5 text-[12px] text-ink-600">
            <li v-for="(p, i) in aiPoints" :key="i">· {{ p }}</li>
          </ul>

          <div class="border-t border-ink-100 pt-2">
            <div class="mb-1 text-[11px] font-medium text-ink-500">就本篇内容提问</div>
            <div v-for="(qa, i) in aiQa" :key="i" class="mb-2 text-[12px]">
              <div class="font-medium text-ink-700">Q：{{ qa.q }}</div>
              <div class="mt-0.5 whitespace-pre-wrap text-ink-600">A：{{ qa.a }}</div>
              <div v-if="qa.refs?.length" class="mt-0.5 text-[11px] text-ink-400">
                来源：{{ qa.refs.map(r => r.title).join('、') }}
              </div>
            </div>
            <div class="flex gap-1">
              <input v-model="aiQuestion" class="input py-1 text-[12px]" placeholder="问点什么…" @keyup.enter="aiAsk" />
              <button class="btn-outline shrink-0 px-2 py-1 text-[12px]" :disabled="aiBusy" @click="aiAsk">问</button>
            </div>
          </div>
          <div class="text-[11px] text-ink-400">
            提供方：{{ aiProvider || '本地' }}<span v-if="aiHint"> · {{ aiHint }}</span>
          </div>
        </div>
      </div>
    </aside>
  </div>

    <!-- 模板（F243 增加我的模板） -->
    <Modal :show="showTemplates" title="从模板新建" width="560px" @close="showTemplates = false">
      <div class="grid grid-cols-2 gap-2">
        <button v-for="t in templates" :key="t.key" class="rounded-card border border-ink-100 p-3 text-left hover:border-brand-400" @click="useTemplate(t.key)">
          <div class="text-[13px] font-medium text-ink-800">{{ t.title }}</div>
        </button>
      </div>
      <div class="mt-3 border-t border-ink-100 pt-2">
        <div class="mb-1 flex items-center justify-between text-[12px] font-medium text-ink-600">
          <span>我的模板 {{ myTemplates.length }} 个</span>
          <button class="text-brand-600" :disabled="!current" :class="!current ? 'opacity-40' : ''" @click="saveAsTemplate">＋ 把当前笔记存为模板</button>
        </div>
        <div class="max-h-52 space-y-1 overflow-y-auto">
          <div v-for="t in myTemplates" :key="t.id" class="flex items-center gap-2 rounded-control bg-ink-50 px-2 py-1.5 text-[12px]">
            <span class="min-w-0 flex-1 truncate">{{ t.icon || '📋' }} {{ t.title }}</span>
            <button class="shrink-0 text-brand-600" @click="useMyTemplate(t)">用</button>
            <button class="shrink-0 text-rose-500" @click="removeMyTemplate(t)">删</button>
          </div>
          <div v-if="!myTemplates.length" class="py-2 text-center text-[11px] text-ink-400">还没有自建模板</div>
        </div>
      </div>
    </Modal>

    <!-- F246 快速记录 -->
    <Modal :show="showQuick" title="快速记录" width="520px" @close="showQuick = false">
      <textarea v-model="quickText" class="input h-32 resize-none text-[13px]" placeholder="随手记下想法（Ctrl+Enter 保存）"
                @keydown.ctrl.enter="submitQuick"></textarea>
      <div class="mt-2 text-[11px] text-ink-400">标题自动取首行；保存后不跳转，可继续记录。</div>
      <div class="mt-3 flex justify-end gap-2">
        <button class="btn-ghost" @click="showQuick = false">取消</button>
        <button class="btn-primary" :disabled="!quickText.trim()" @click="submitQuick">保存</button>
      </div>
    </Modal>

    <!-- F239 封面选择 -->
    <Modal :show="showCoverPicker" title="设置封面图" width="560px" @close="showCoverPicker = false">
      <div class="mb-2 flex gap-2">
        <input v-model="coverQuery" class="input flex-1" placeholder="搜索我的图片…" @keyup.enter="loadCoverFiles" />
        <button class="btn-outline" @click="loadCoverFiles">搜索</button>
      </div>
      <div class="grid max-h-64 grid-cols-4 gap-2 overflow-y-auto">
        <button v-for="f in coverFiles" :key="f.id" class="overflow-hidden rounded-card border border-ink-100 hover:border-brand-400" @click="setCover(f.id)">
          <img :src="f.thumbnail || f.url" :alt="f.name" class="h-20 w-full object-cover" />
          <div class="truncate px-1 py-0.5 text-[10px] text-ink-500">{{ f.name }}</div>
        </button>
        <div v-if="!coverFiles.length" class="col-span-4 py-6 text-center text-[12px] text-ink-400">没有可用的图片文件</div>
      </div>
      <div class="mt-3 flex justify-between">
        <button class="btn-ghost text-[12px]" @click="setCover(null)">清除封面</button>
        <button class="btn-ghost" @click="showCoverPicker = false">取消</button>
      </div>
    </Modal>

    <!-- F237 附件 -->
    <Modal :show="showAttachments" title="笔记附件" width="560px" @close="showAttachments = false">
      <div class="space-y-1">
        <div v-for="a in attachments" :key="a.id" class="flex items-center gap-2 rounded-control bg-ink-50 px-2 py-1.5 text-[12px]">
          <span class="min-w-0 flex-1 truncate">{{ a.kind === 'image' ? '🖼' : '📎' }} {{ a.name }}</span>
          <button class="shrink-0 text-brand-600" @click="insertAttachmentLink(a)">插入链接</button>
          <button class="shrink-0 text-rose-500" @click="unbindAttachment(a)">移除</button>
        </div>
        <div v-if="!attachments.length" class="py-2 text-center text-[11px] text-ink-400">还没有附件</div>
      </div>
      <div class="mt-3 border-t border-ink-100 pt-2">
        <div class="mb-1 text-[12px] font-medium text-ink-600">绑定已有文件</div>
        <div class="mb-1 flex gap-2">
          <input v-model="attachQuery" class="input flex-1" placeholder="搜索我的文件…" @keyup.enter="loadAttachFiles" />
          <button class="btn-outline" @click="loadAttachFiles">搜索</button>
        </div>
        <div class="max-h-40 space-y-1 overflow-y-auto">
          <button v-for="f in attachFiles" :key="f.id" class="flex w-full items-center gap-2 rounded-control px-2 py-1 text-left text-[12px] hover:bg-ink-50" @click="bindAttachment(f)">
            <span class="min-w-0 flex-1 truncate">{{ f.name }}</span>
            <span class="shrink-0 text-[11px] text-ink-400">{{ Math.round((f.size || 0) / 1024) }} KB</span>
          </button>
          <div v-if="!attachFiles.length" class="py-2 text-center text-[11px] text-ink-400">没有可绑定的文件</div>
        </div>
      </div>
    </Modal>

    <!-- F240 提醒 -->
    <Modal :show="showReminder" title="回看提醒" width="420px" @close="showReminder = false">
      <input v-model="reminderInput" type="datetime-local" class="input" />
      <div class="mt-2 text-[11px] text-ink-400">
        <span v-if="current && current.reminded_at">已于 {{ formatTime(current.reminded_at) }} 提醒过。</span>
        <span v-else>到点后由系统命令 send_note_reminders 发送站内提醒。</span>
      </div>
      <div class="mt-4 flex justify-between">
        <button class="btn-ghost text-[12px]" @click="saveReminder(null)">清除提醒</button>
        <span class="flex gap-2">
          <button class="btn-ghost" @click="showReminder = false">取消</button>
          <button class="btn-primary" :disabled="!reminderInput" @click="saveReminder(reminderInput)">保存</button>
        </span>
      </div>
    </Modal>

    <!-- 大纲（#13 AI大纲结果也展示在此） -->
    <Modal :show="showOutline" title="内容大纲" @close="showOutline = false">
      <div v-if="aiOutlineSummary" class="mb-3 rounded-control bg-brand-50 p-2 text-[12px] leading-relaxed text-brand-800">{{ aiOutlineSummary }}</div>
      <div class="space-y-1">
        <button v-for="(h, i) in outline" :key="i" class="block w-full rounded-control px-1 py-1 text-left text-[13px] text-ink-700 hover:bg-brand-50 hover:text-brand-700"
                :style="{ paddingLeft: (h.level - 1) * 14 + 8 + 'px' }" @click="jumpOutline(h)">
          {{ h.level === 1 ? '■' : '▸' }} {{ h.title || h.text }}
        </button>
        <div v-if="!outline.length" class="text-[12px] text-ink-400">使用 # ## ### 生成标题即可提取大纲</div>
        <div v-else class="pt-1 text-[11px] text-ink-400">点击标题可跳转到正文对应位置</div>
      </div>
    </Modal>

    <!-- 批量导入 MD（#14） -->
    <Modal :show="showImport" title="批量导入 Markdown" width="640px" @close="showImport = false">
      <textarea v-model="importMd" class="input h-64 resize-none font-mono text-[12px]" placeholder="粘贴 Markdown，按 # 一级标题自动切分为多篇笔记…"></textarea>
      <div class="mt-3 flex justify-end gap-2">
        <button class="btn-ghost" @close="showImport = false" @click="showImport = false">取消</button>
        <button class="btn-primary" @click="doImport">导入</button>
      </div>
    </Modal>

    <!-- 闪卡回顾（#15） -->
    <Modal :show="showCards" title="闪卡回顾" width="520px" @close="showCards = false">
      <div v-if="cards.length" class="space-y-3">
        <div class="rounded-card border border-ink-100 p-4 text-center">
          <div class="text-[11px] text-ink-400">问题 {{ cardIdx + 1 }}/{{ cards.length }}</div>
          <div class="mt-1 text-[15px] font-medium text-ink-800">{{ cards[cardIdx].front }}</div>
          <button v-if="!cardShow" class="btn-outline mt-3 text-[12px]" @click="cardShow = true">显示答案</button>
          <div v-else class="mt-3 whitespace-pre-wrap rounded-control bg-ink-50 p-3 text-left text-[12px] text-ink-600">{{ cards[cardIdx].back }}</div>
        </div>
        <div class="flex justify-between">
          <button class="btn-outline text-[12px]" @click="cardIdx = (cardIdx - 1 + cards.length) % cards.length; cardShow = false">上一张</button>
          <button class="btn-outline text-[12px]" @click="cardIdx = (cardIdx + 1) % cards.length; cardShow = false">下一张</button>
        </div>
      </div>
      <div v-else class="py-8 text-center text-[12px] text-ink-400">本篇没有可抽取的小节（用 ## 标题分段即可生成闪卡）</div>
    </Modal>

    <!-- 统计 -->
    <Modal :show="showStats" title="写作统计" @close="showStats = false">
      <div class="grid grid-cols-3 gap-3 text-center">
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.total || 0 }}</div><div class="text-[11px] text-ink-400">笔记数</div></div>
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.total_words || 0 }}</div><div class="text-[11px] text-ink-400">总字数</div></div>
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.favorite || 0 }}</div><div class="text-[11px] text-ink-400">收藏数</div></div>
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.updated_7d || 0 }}</div><div class="text-[11px] text-ink-400">近7天更新</div></div>
      </div>
      <!-- F573 笔记来源统计 -->
      <div class="mt-4">
        <div class="mb-2 flex items-center justify-between text-[13px] font-medium text-ink-700">
          <span>来源统计</span>
          <span class="text-[11px] font-normal text-ink-400">共 {{ sourcesData.total || 0 }} 篇 · {{ sourcesData.total_words || 0 }} 字</span>
        </div>
        <div v-if="(sourcesData.list || []).length" class="space-y-1.5">
          <div v-for="s in sourcesData.list" :key="s.source">
            <div class="mb-0.5 flex justify-between text-[12px]">
              <span>{{ s.label }}</span>
              <span class="text-ink-400">{{ s.count }} 篇 · {{ s.words }} 字 · {{ s.pct }}%</span>
            </div>
            <div class="h-2 rounded-full bg-ink-100">
              <div class="h-full rounded-full bg-brand-500" :style="{ width: s.pct + '%' }"></div>
            </div>
          </div>
        </div>
        <div v-else class="text-[12px] text-ink-400">暂无来源数据</div>
      </div>
    </Modal>

    <!-- 标签管理 -->
    <Modal :show="showTagMgr" title="标签管理" width="520px" @close="showTagMgr = false">
      <div class="space-y-2">
        <div v-for="t in tags" :key="t.id" class="flex items-center gap-2">
          <input v-model="t.name" class="input flex-1" @change="saveTag(t)" />
          <input v-model="t.color" type="color" class="h-8 w-10 rounded-control border border-ink-200" @change="saveTag(t)" />
          <!-- F256 合并到 -->
          <select class="input w-20 py-1 text-[11px]" @change="mergeTag(t, $event.target.value); $event.target.value = ''">
            <option value="">合并到…</option>
            <option v-for="o in tags" :key="o.id" :value="o.id" :disabled="o.id === t.id">{{ o.name }}</option>
          </select>
          <button class="btn-danger px-2 text-[12px]" @click="delTag(t)">删除</button>
        </div>
        <div class="flex gap-2">
          <input v-model="newTagName" class="input flex-1" placeholder="新标签名" @keyup.enter="addNewTag" />
          <button class="btn-primary" @click="addNewTag">新增</button>
        </div>
      </div>
    </Modal>

    <!-- F259 同名笔记提示 -->
    <Modal :show="showDuplicate" title="已有同名笔记" width="420px" @close="showDuplicate = false">
      <div class="text-[12px] text-ink-600">已新建，但库里已有同标题笔记，双链 [[标题]] 会指向最新一篇：</div>
      <div class="mt-2 space-y-1">
        <button v-for="d in duplicateExisting" :key="d.id"
                class="block w-full truncate rounded-control bg-ink-50 px-2 py-1.5 text-left text-[12px] hover:bg-ink-100"
                @click="openExistingDuplicate(d)">{{ d.title }}</button>
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="openCreatedDuplicate">保留新建</button>
        <button class="btn-primary" @click="showDuplicate = false">知道了</button>
      </div>
    </Modal>

    <!-- F257 双链悬停预览 -->
    <div v-if="wikiCard" class="fixed z-40 w-64 rounded-card border border-ink-100 bg-white p-2.5 shadow-pop"
         :style="{ left: wikiPos.x + 'px', top: wikiPos.y + 'px' }"
         @mouseleave="hideWikiPreview">
      <div class="text-[13px] font-medium text-ink-800">{{ wikiCard.icon || '📄' }} {{ wikiCard.title }}</div>
      <div class="mt-1 line-clamp-4 text-[11px] leading-relaxed text-ink-500">{{ wikiCard.excerpt || wikiCard.message || '（空笔记）' }}</div>
      <div class="mt-1 flex flex-wrap gap-1">
        <span v-for="t in wikiCard.tags || []" :key="t" class="tag">{{ t }}</span>
      </div>
      <button v-if="wikiCard.id" class="mt-1 text-[11px] text-brand-600 hover:underline" @click="openWikiCard">打开 →</button>
    </div>

    <!-- 版本 -->
    <Modal :show="showVersions" title="版本历史" width="520px" @close="showVersions = false">
      <div v-if="versions.length" class="space-y-2">
        <div v-for="v in versions" :key="v.id" class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-2">
          <div><div class="text-[13px] font-medium">v{{ v.version }} · {{ v.title }}</div><div class="text-[11px] text-ink-400">{{ formatTime(v.created_at) }} {{ v.created_by_name }}</div></div>
          <div class="flex gap-1">
            <button class="btn-outline px-2 py-1 text-[12px]" @click="diffWith(v)">对比</button>
            <button class="btn-outline px-2 py-1 text-[12px]" @click="rollback(v)">回滚</button>
          </div>
        </div>
      </div>
      <div v-else class="py-8 text-center text-[12px] text-ink-400">暂无版本</div>
    </Modal>

    <!-- #22 版本差异高亮 -->
    <Modal :show="showDiff" :title="`版本差异 ${diffFrom} → ${diffTo}`" width="640px" @close="showDiff = false">
      <div class="max-h-[60vh] overflow-auto rounded-control bg-ink-50 p-3 font-mono text-[12px] leading-relaxed">
        <div v-for="(line, i) in diffLines" :key="i" class="whitespace-pre-wrap"
             :class="line.startsWith('+') ? 'bg-emerald-50 text-emerald-700' : line.startsWith('-') ? 'bg-rose-50 text-rose-700' : line.startsWith('@@') ? 'text-brand-600' : 'text-ink-500'">
          {{ line }}
        </div>
        <div v-if="!diffLines.length" class="text-ink-400">两版本内容相同</div>
      </div>
    </Modal>

    <!-- #23 快捷键面板（#145 只列真实可用的组合键） -->
    <Modal :show="showShortcuts" title="编辑器快捷键" width="480px" @close="showShortcuts = false">
      <div class="space-y-1.5 text-[13px]">
        <div class="flex justify-between"><span>立即保存</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+S</kbd></div>
        <div class="flex justify-between"><span>输入 [[ 触发双链建议</span><kbd class="rounded bg-ink-100 px-1.5">[[</kbd></div>
        <div class="flex justify-between"><span>打开快捷键面板</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+/</kbd></div>
        <div class="flex justify-between"><span>切换编辑/预览</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+E</kbd></div>
      </div>
      <div class="mt-3 text-[11px] text-ink-400">正文编辑时还会自动防抖保存，Ctrl+S 用于立即落盘。</div>
    </Modal>

    <!-- 双链关系图谱 -->
    <Modal :show="showGraph" title="笔记关系图谱" width="640px" @close="showGraph = false">
      <div v-if="graph" class="space-y-3">
        <div class="flex gap-3 text-[12px] text-ink-500">
          <span>笔记 {{ graph.node_count }} 篇</span>
          <span>链接 {{ graph.edge_count }} 条</span>
        </div>
        <div class="max-h-[50vh] space-y-1 overflow-y-auto">
          <div v-for="n in graph.nodes.slice(0, 60)" :key="n.id"
               class="flex items-center gap-2 rounded-control px-2 py-1.5 hover:bg-ink-50">
            <span class="tag" :class="n.degree ? 'tag-brand' : ''">{{ n.degree }}</span>
            <button class="min-w-0 flex-1 truncate text-left text-[13px] text-ink-700 hover:underline"
                    @click="showGraph = false; openNote(n.id)">{{ n.title }}</button>
            <span v-if="n.is_orphan" class="text-[11px] text-ink-400">孤立</span>
          </div>
        </div>
        <div v-if="graph.nodes.length" class="text-[11px] text-ink-400">
          按关联度排序。用 <code>[[标题]]</code> 建立链接后，这里会自动出现关系。
        </div>
      </div>
      <div v-else class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
    </Modal>
    <!-- F565 写作字数目标 -->
    <Modal :show="showGoals" title="写作字数目标" width="520px" @close="showGoals = false">
      <div class="mb-3 grid grid-cols-3 gap-2 text-center">
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[18px] font-bold">{{ goalsData.today_words || 0 }}</div><div class="text-[11px] text-ink-400">今日新增字数</div></div>
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[18px] font-bold">{{ goalsData.week_words || 0 }}</div><div class="text-[11px] text-ink-400">本周新增</div></div>
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[18px] font-bold">{{ goalsData.month_words || 0 }}</div><div class="text-[11px] text-ink-400">本月新增</div></div>
      </div>
      <div class="space-y-2">
        <div v-for="g in goalsData.goals || []" :key="g.id" class="rounded-card border border-ink-100 p-2.5">
          <div class="flex items-center justify-between text-[12px]">
            <span class="font-medium text-ink-700">{{ g.period_label }}目标 {{ g.target }} 字<span v-if="g.note_title" class="text-ink-400"> · 《{{ g.note_title }}》</span></span>
            <span :class="g.achieved ? 'text-emerald-600' : 'text-ink-500'">{{ g.current }}/{{ g.target }}（{{ g.pct }}%）</span>
          </div>
          <div class="mt-1.5 h-2 overflow-hidden rounded-full bg-ink-100">
            <div class="h-full rounded-full" :class="g.achieved ? 'bg-emerald-500' : 'bg-brand-500'" :style="{ width: g.pct + '%' }"></div>
          </div>
          <div class="mt-1 text-right">
            <button class="text-[11px] text-rose-500" @click="removeGoal(g.id)">删除目标</button>
          </div>
        </div>
        <div v-if="!(goalsData.goals || []).length" class="py-4 text-center text-[12px] text-ink-400">还没有目标，先定一个小目标吧 🎯</div>
      </div>
      <div class="mt-3 flex items-center gap-2 border-t border-ink-100 pt-3 text-[12px]">
        <input v-model.number="newGoal.target" type="number" min="1" class="input w-24" placeholder="字数" />
        <select v-model="newGoal.period" class="input w-32">
          <option value="day">每天</option>
          <option value="week">每周</option>
          <option value="month">每月</option>
          <option v-if="current" value="note">本篇笔记</option>
        </select>
        <button class="btn-primary ml-auto" @click="addGoal">新增目标</button>
      </div>
    </Modal>

    <!-- F566 日记视图 -->
    <Modal :show="showDiary" :title="`日记视图 · ${diary.year || ''} 年 ${diary.month || ''} 月`" width="640px" @close="showDiary = false">
      <div class="mb-2 flex items-center justify-between text-[12px]">
        <button class="btn-outline px-2 py-1 text-[12px]" @click="shiftDiary(-1)">← 上月</button>
        <span class="text-ink-500">本月 {{ diary.total_notes || 0 }} 篇 · {{ diary.total_words || 0 }} 字 · 空白 {{ diary.empty_days || 0 }} 天</span>
        <button class="btn-outline px-2 py-1 text-[12px]" @click="shiftDiary(1)">下月 →</button>
      </div>
      <div class="grid grid-cols-7 gap-1">
        <div v-for="w in ['一', '二', '三', '四', '五', '六', '日']" :key="w" class="py-1 text-center text-[11px] text-ink-400">{{ w }}</div>
        <div v-for="p in (diary.first_weekday || 0)" :key="'pad' + p"></div>
        <button v-for="d in (diary.days || [])" :key="d.date" class="rounded-control border py-1 text-center"
                :class="d.count ? 'border-brand-400 bg-brand-50 text-brand-700' : (diaryDay && diaryDay.date === d.date ? 'border-ink-300' : 'border-ink-100 text-ink-300')"
                @click="diaryDay = d">
          <div class="text-[11px]">{{ d.day }}</div>
          <div v-if="d.count" class="text-[10px]">{{ d.count }}篇</div>
        </button>
      </div>
      <div v-if="diaryDay" class="mt-3 rounded-control bg-ink-50 p-2">
        <div class="mb-1 flex justify-between text-[12px] font-medium">
          <span>{{ diaryDay.date }}（{{ WEEK_NAMES[diaryDay.weekday] }}）</span>
          <button class="text-ink-400" @click="diaryDay = null">×</button>
        </div>
        <button v-for="n in diaryDay.notes" :key="n.id" class="block w-full truncate rounded-control px-2 py-1 text-left text-[12px] hover:bg-ink-100"
                @click="showDiary = false; openNote(n.id)">📄 {{ n.title }} <span class="text-ink-400">{{ n.words }} 字</span></button>
        <div v-if="!diaryDay.notes.length" class="py-2 text-[12px] text-ink-400">这一天没有新建笔记</div>
      </div>
    </Modal>

    <!-- F567 未链接提及 -->
    <Modal :show="showMentions" title="未链接提及" width="640px" @close="showMentions = false">
      <div class="mb-2 text-[12px] text-ink-400">这些笔记标题在正文里被提到，但没写成 <code>[[标题]]</code>；点「转为双链」可一键补链。</div>
      <div class="max-h-[55vh] space-y-2 overflow-y-auto">
        <div v-for="m in mentions" :key="m.target_id" class="rounded-card border border-ink-100 p-2.5">
          <div class="flex items-center justify-between text-[13px]">
            <button class="font-medium text-ink-700 hover:text-brand-600" @click="showMentions = false; openNote(m.target_id)">《{{ m.target_title }}》</button>
            <span class="text-[11px] text-ink-400">被提及 {{ m.count }} 次</span>
          </div>
          <div v-for="s in m.sources" :key="s.note_id" class="mt-1 flex items-start gap-2 text-[12px]">
            <button class="shrink-0 text-brand-600 hover:underline" @click="showMentions = false; openNote(s.note_id)">{{ s.note_title }}</button>
            <span class="min-w-0 flex-1 truncate text-ink-400">{{ s.excerpt }}</span>
            <button class="shrink-0 text-[11px] text-brand-600" @click="linkifyMention(m, s)">转为双链</button>
          </div>
        </div>
        <div v-if="!mentions.length" class="py-8 text-center text-[12px] text-ink-400">没有未链接提及，链接生态很健康 🎉</div>
      </div>
    </Modal>

    <!-- F569 健康度报告 -->
    <Modal :show="showHealth" title="笔记健康度报告" width="680px" @close="showHealth = false">
      <div class="flex items-center gap-4">
        <svg viewBox="0 0 100 100" class="h-28 w-28 shrink-0" role="img" aria-label="健康分环形图">
          <circle cx="50" cy="50" r="42" fill="none" stroke="#eef2f6" stroke-width="10" />
          <circle cx="50" cy="50" r="42" fill="none" :stroke="gradeColor(health.grade)" stroke-width="10"
                  stroke-linecap="round" :stroke-dasharray="healthDash" transform="rotate(-90 50 50)" />
          <text x="50" y="48" text-anchor="middle" fill="#1e293b" style="font-size:17px;font-weight:700">{{ health.avg_score || 0 }}</text>
          <text x="50" y="64" text-anchor="middle" fill="#94a3b8" style="font-size:9px">健康分 {{ health.grade || '-' }}</text>
        </svg>
        <div class="min-w-0 flex-1 space-y-1 text-[12px]">
          <div class="flex justify-between"><span>笔记总数</span><span>{{ health.note_count || 0 }}</span></div>
          <div class="flex justify-between"><span>满分笔记</span><span>{{ health.perfect || 0 }}</span></div>
          <div v-for="(c, g) in (health.distribution || {})" :key="g" class="flex justify-between"><span>{{ g }} 级</span><span>{{ c }} 篇</span></div>
        </div>
      </div>
      <div class="mt-3 space-y-1.5">
        <div v-for="i in health.issues || []" :key="i.type">
          <div class="mb-0.5 flex justify-between text-[12px]"><span>{{ i.label }}</span><span class="text-ink-400">{{ i.count }} 篇 · {{ i.pct }}%</span></div>
          <div class="h-1.5 rounded-full bg-ink-100"><div class="h-full rounded-full bg-amber-400" :style="{ width: Math.min(100, i.pct) + '%' }"></div></div>
        </div>
        <div v-if="!(health.issues || []).length" class="text-[12px] text-ink-400">没有发现问题 🎉</div>
      </div>
      <div class="mt-3">
        <div class="mb-1 text-[12px] font-medium text-ink-600">最需要照顾的笔记</div>
        <div class="max-h-44 space-y-1 overflow-y-auto">
          <button v-for="n in health.worst || []" :key="n.id" class="flex w-full items-center justify-between rounded-control bg-ink-50 px-2.5 py-1.5 text-[12px] hover:bg-ink-100"
                  @click="showHealth = false; openNote(n.id)">
            <span class="truncate">{{ n.title }}</span>
            <span class="shrink-0" :style="{ color: gradeColor(n.grade) }">{{ n.score }} 分 · {{ n.issues.length }} 项</span>
          </button>
          <div v-if="!(health.worst || []).length" class="py-3 text-center text-[12px] text-ink-400">暂无数据</div>
        </div>
      </div>
    </Modal>

    <!-- F572 六色标记 -->
    <Modal :show="showColorPicker" title="笔记颜色标记" @close="showColorPicker = false">
      <div class="flex flex-wrap gap-2">
        <button v-for="(label, key) in NOTE_COLORS" :key="key" class="flex items-center gap-1.5 rounded-control border px-3 py-2 text-[13px]"
                :class="current && current.color === key ? 'border-brand-400 bg-brand-50' : 'border-ink-100 hover:border-ink-200'"
                @click="setColor(key)">
          <span class="h-4 w-4 rounded-full" :style="{ background: colorHex(key) }"></span>{{ label }}
        </button>
        <button class="rounded-control border border-ink-100 px-3 py-2 text-[13px] hover:border-ink-200" @click="setColor('')">无标记</button>
      </div>
      <div class="mt-3 text-[11px] text-ink-400">颜色会显示在笔记列表的小圆点上，方便快速区分。</div>
    </Modal>

    <!-- F574 个人片段库 -->
    <Modal :show="showSnippets" title="个人片段库" width="640px" @close="showSnippets = false">
      <div class="mb-2 flex gap-2 text-[12px]">
        <input v-model="snippetQuery" class="input flex-1" placeholder="搜索片段…" @input="loadSnippets" />
        <button class="btn-outline" @click="showNewSnippet = !showNewSnippet">＋ 新建</button>
      </div>
      <div v-if="showNewSnippet" class="mb-2 space-y-2 rounded-card bg-ink-50 p-2.5">
        <input v-model="newSnippet.title" class="input" placeholder="片段标题" />
        <textarea v-model="newSnippet.content" class="input h-24 resize-none font-mono text-[12px]" placeholder="片段内容（Markdown）"></textarea>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showNewSnippet = false">取消</button>
          <button class="btn-primary" @click="createSnippet">保存</button>
        </div>
      </div>
      <div class="max-h-[45vh] space-y-1.5 overflow-y-auto">
        <div v-for="s in snippets" :key="s.id" class="rounded-card border border-ink-100 p-2.5">
          <div class="flex items-center justify-between text-[13px]">
            <span class="font-medium text-ink-700">{{ s.title }}</span>
            <span class="text-[11px] text-ink-400">已用 {{ s.use_count }} 次</span>
          </div>
          <div class="mt-0.5 truncate text-[12px] text-ink-400">{{ s.preview }}</div>
          <div class="mt-1.5 flex justify-end gap-2">
            <button class="btn-primary px-2 py-1 text-[12px]" :disabled="!current" @click="insertSnippet(s)">插入当前笔记</button>
            <button class="btn-danger px-2 py-1 text-[12px]" @click="removeSnippet(s.id)">删除</button>
          </div>
        </div>
        <div v-if="!snippets.length" class="py-8 text-center text-[12px] text-ink-400">还没有片段，把常用文本存进来吧 ✂</div>
      </div>
    </Modal>

    <!-- F575 合并笔记 -->
    <Modal :show="showMerge" title="合并笔记" width="560px" @close="showMerge = false">
      <div class="mb-2 text-[12px] text-ink-400">把《{{ current ? current.title : '' }}》并入另一篇：目标笔记保留，源内容追加到目标末尾。</div>
      <input v-model="mergeQuery" class="input mb-2" placeholder="搜索目标笔记…" @input="searchMergeTargets" />
      <div class="max-h-56 space-y-1 overflow-y-auto">
        <button v-for="n in mergeTargets" :key="n.id"
                class="flex w-full items-center justify-between rounded-control px-2 py-1.5 text-left text-[13px]"
                :class="mergeTarget === n.id ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50'"
                @click="mergeTarget = n.id">
          <span class="truncate">{{ n.title }}</span><span class="shrink-0 text-[11px] text-ink-400">{{ n.words }} 字</span>
        </button>
        <div v-if="!mergeTargets.length" class="py-4 text-center text-[12px] text-ink-400">输入关键词搜索目标笔记</div>
      </div>
      <label class="mt-2 flex items-center gap-1.5 text-[12px]"><input type="checkbox" v-model="keepSource" /> 合并后保留源笔记</label>
      <div class="mt-3 flex justify-end gap-2">
        <button class="btn-ghost" @click="showMerge = false">取消</button>
        <button class="btn-primary" :disabled="!mergeTarget" @click="doMerge">合并</button>
      </div>
    </Modal>

    <!-- F576 拆分笔记 -->
    <Modal :show="showSplit" title="按一级标题拆分笔记" width="560px" @close="showSplit = false">
      <div class="mb-2 text-[12px] text-ink-400">按 <code># 一级标题</code> 拆成多篇（与本篇同级、同文件夹、同标签）：</div>
      <div class="max-h-56 space-y-1 overflow-y-auto">
        <div v-for="(s, i) in splitSections" :key="i" class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-1.5 text-[13px]">
          <span class="truncate">{{ i + 1 }}. {{ s.title }}</span><span class="shrink-0 text-[11px] text-ink-400">{{ s.words }} 字</span>
        </div>
        <div v-if="!splitSections.length" class="py-4 text-center text-[12px] text-ink-400">没有可拆分的一级标题</div>
      </div>
      <label class="mt-2 flex items-center gap-1.5 text-[12px]"><input type="checkbox" v-model="keepOriginal" /> 拆分后保留原笔记</label>
      <div class="mt-3 flex justify-end gap-2">
        <button class="btn-ghost" @click="showSplit = false">取消</button>
        <button class="btn-primary" :disabled="!splitSections.length" @click="doSplit">拆分</button>
      </div>
    </Modal>

    <!-- F578 生词本（学习区联动） -->
    <Modal :show="showWordbook" title="生词本（学习区联动）" width="560px" @close="showWordbook = false">
      <div class="mb-2 text-[12px] text-ink-400">在编辑/预览里选中单词，点工具栏「📚 存生词」即可加入学习区生词本；接口不可用时自动本地暂存，不会报错。</div>
      <div class="mb-2 flex gap-2">
        <input v-model="wordInput" class="input flex-1" placeholder="手动添加单词…" @keyup.enter="saveWord(wordInput)" />
        <button class="btn-primary" @click="saveWord(wordInput)">添加</button>
        <button class="btn-outline" @click="loadWordbook">刷新</button>
        <button v-if="localWords.length" class="btn-outline" @click="syncLocalWords">同步本地</button>
      </div>
      <div class="max-h-56 space-y-1 overflow-y-auto">
        <div v-for="(w, i) in wordList" :key="i" class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-1.5 text-[13px]">
          <span>{{ w.word }}<span v-if="w.phonetic" class="ml-1 text-[11px] text-ink-400">{{ w.phonetic }}</span></span>
          <span class="truncate text-[12px] text-ink-400">{{ w.meaning || (w.local ? '本地暂存' : '') }}</span>
        </div>
        <div v-if="!wordList.length" class="py-6 text-center text-[12px] text-ink-400">生词本是空的</div>
      </div>
      <div v-if="localWords.length" class="mt-2 text-[11px] text-amber-600">有 {{ localWords.length }} 个词仅存在本地（生词本暂不可用时的降级存储）。</div>
    </Modal>

    <!-- F579 每周回顾清单 -->
    <Modal :show="showWeekly" :title="`每周回顾 · ${weekly.week || ''}`" width="680px" @close="showWeekly = false">
      <div class="mb-2 flex items-center justify-between text-[12px]">
        <button class="btn-outline px-2 py-1 text-[12px]" @click="loadWeekly(weekly.prev_week)">← 上周</button>
        <span class="text-ink-400">{{ weekly.start || '' }} ~ {{ weekly.end || '' }}</span>
        <button class="btn-outline px-2 py-1 text-[12px]" @click="loadWeekly(weekly.next_week)">下周 →</button>
      </div>
      <div class="grid grid-cols-4 gap-2 text-center">
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[17px] font-bold">{{ weekly.stats ? weekly.stats.created : 0 }}</div><div class="text-[11px] text-ink-400">新建笔记</div></div>
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[17px] font-bold">{{ weekly.stats ? weekly.stats.updated : 0 }}</div><div class="text-[11px] text-ink-400">更新笔记</div></div>
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[17px] font-bold">{{ weekly.stats ? weekly.stats.words_written : 0 }}</div><div class="text-[11px] text-ink-400">写作字数</div></div>
        <div class="rounded-card bg-ink-50 p-2"><div class="text-[17px] font-bold">{{ weekly.stats ? weekly.stats.new_links : 0 }}</div><div class="text-[11px] text-ink-400">新增双链</div></div>
      </div>
      <div class="mt-2 flex flex-wrap gap-1.5 text-[11px]">
        <span v-for="t in (weekly.top_tags || [])" :key="t.name" class="tag">#{{ t.name }} ×{{ t.count }}</span>
        <span v-if="!(weekly.top_tags || []).length" class="text-ink-400">本周没有标签活动</span>
      </div>
      <div class="mt-3 grid grid-cols-2 gap-3 text-[12px]">
        <div>
          <div class="mb-1 font-medium text-ink-600">本周新建</div>
          <button v-for="n in (weekly.created_notes || [])" :key="n.id" class="block w-full truncate rounded-control px-2 py-1 text-left hover:bg-ink-50"
                  @click="showWeekly = false; openNote(n.id)">📄 {{ n.title }} · {{ n.words }} 字</button>
          <div v-if="!(weekly.created_notes || []).length" class="text-ink-400">无</div>
        </div>
        <div>
          <div class="mb-1 font-medium text-ink-600">本周更新</div>
          <button v-for="n in (weekly.updated_notes || [])" :key="n.id" class="block w-full truncate rounded-control px-2 py-1 text-left hover:bg-ink-50"
                  @click="showWeekly = false; openNote(n.id)">✏️ {{ n.title }}</button>
          <div v-if="!(weekly.updated_notes || []).length" class="text-ink-400">无</div>
        </div>
      </div>
      <div class="mt-3 rounded-control bg-ink-50 p-2.5 text-[12px] text-ink-500">
        待办：未完成 {{ weekly.stats ? weekly.stats.open_todos : 0 }} 项 · 已完成 {{ weekly.stats ? weekly.stats.done_todos : 0 }} 项 ·
        长期未更新 {{ weekly.stats ? weekly.stats.stale : 0 }} 篇 · 新增字数(新建) {{ weekly.stats ? weekly.stats.words_new : 0 }}
      </div>
    </Modal>

    <!-- F580 待办抽取清单 -->
    <Modal :show="showTodos" title="待办清单（- [ ] 抽取）" width="640px" @close="showTodos = false">
      <div class="mb-2 flex items-center gap-2 text-[12px]">
        <button class="tag" :class="todoFilter === 'open' ? 'tag-brand' : ''" @click="todoFilter = 'open'; loadTodos()">未完成 {{ todoOpenCount }}</button>
        <button class="tag" :class="todoFilter === 'done' ? 'tag-brand' : ''" @click="todoFilter = 'done'; loadTodos()">已完成 {{ todoDoneCount }}</button>
        <button class="tag" :class="todoFilter === 'all' ? 'tag-brand' : ''" @click="todoFilter = 'all'; loadTodos()">全部</button>
        <label v-if="current" class="ml-auto flex items-center gap-1 text-ink-500">
          <input type="checkbox" v-model="todoMine" @change="loadTodos" /> 只看当前笔记
        </label>
      </div>
      <div class="max-h-[50vh] space-y-1 overflow-y-auto">
        <div v-for="(t, i) in todos" :key="i" class="flex items-start gap-2 rounded-control bg-ink-50 px-3 py-1.5 text-[13px]">
          <input type="checkbox" :checked="t.done" class="mt-1" @change="toggleTodoItem(t)" />
          <div class="min-w-0 flex-1">
            <div :class="t.done ? 'text-ink-400 line-through' : 'text-ink-700'">{{ t.text || '(空待办)' }}</div>
            <button class="text-[11px] text-brand-600 hover:underline" @click="showTodos = false; openNote(t.note_id)">{{ t.note_title }}</button>
          </div>
          <span class="shrink-0 text-[11px] text-ink-400">{{ t.done ? '✓' : '' }}</span>
        </div>
        <div v-if="!todos.length" class="py-8 text-center text-[12px] text-ink-400">没有待办项，写上 <code>- [ ] 任务</code> 试试</div>
      </div>
    </Modal>

    <!-- F581 参考文献引用格式 -->
    <Modal :show="showCitation" title="生成参考文献引用" width="600px" @close="showCitation = false">
      <div class="mb-2 flex gap-2 text-[12px]">
        <button v-for="s in citation.styles" :key="s.key" class="tag"
                :class="citation.style === s.key ? 'tag-brand' : ''"
                @click="citation.style = s.key; loadCitation()">{{ s.label }}</button>
        <span class="ml-auto text-ink-400">引用当前笔记</span>
      </div>
      <div class="max-h-56 space-y-2 overflow-y-auto">
        <div v-for="it in citation.items" :key="it.id" class="rounded-card bg-ink-50 p-2.5">
          <div class="mb-1 text-[11px] text-ink-400">《{{ it.title }}》</div>
          <div class="text-[12px] leading-relaxed text-ink-700">{{ it.text }}</div>
          <div class="mt-1 text-right"><button class="text-[11px] text-brand-600 hover:underline" @click="copyText(it.text)">复制</button></div>
        </div>
        <div v-if="!citation.items.length" class="py-6 text-center text-[12px] text-ink-400">暂无可引用的笔记</div>
      </div>
      <div class="mt-2 text-[11px] text-ink-400">公开分享的笔记会自动带上分享地址。</div>
    </Modal>

    <!-- F582 新建笔记文件夹 -->
    <Modal :show="showNewFolder" title="新建笔记文件夹" @close="showNewFolder = false">
      <input v-model="newFolderName" class="input" placeholder="文件夹名称" @keyup.enter="createNoteFolder" />
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="showNewFolder = false">取消</button>
        <button class="btn-primary" @click="createNoteFolder">创建</button>
      </div>
    </Modal>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useAutosave } from '../../composables/useAutosave'
import { aiApi, fileApi, noteApi } from '../../api'
import { API_URL } from '../../api/base'
import { notex } from '../../api/notex'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import { describeDownloadError, downloadWithAuth, saveBlob } from '../../utils/download'
import { sha1File } from '../../utils/sha1'
// #189 yjs/CRDT 体积较大（约 226KB），只在真正开启协同时动态加载
// import { NoteCollab } from '../../utils/collab'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const tree = ref([])
const tags = ref([])
const cloudTags = ref([])
const current = ref(null)
const contentEl = ref(null)
const activeNote = ref(null)
const sideTab = ref('all')
const trashList = ref([])
const editorTab = ref('write')
const showVersions = ref(false)
const versions = ref([])
const showTemplates = ref(false)
const templates = ref([])
const showOutline = ref(false)
const outline = ref([])
const aiOutlineSummary = ref('')
const showStats = ref(false)
const stats = ref({})
const showTagMgr = ref(false)
const newTagName = ref('')
const saving = ref(false)
const tagInput = ref('')

// #14 导入 / #15 闪卡 / #22 diff / #23 快捷键
const showImport = ref(false)
const importMd = ref('')
const showCards = ref(false)
const cards = ref([])
const cardIdx = ref(0)
const cardShow = ref(false)
const showDiff = ref(false)
const diffLines = ref([])
const diffFrom = ref('')
const diffTo = ref('')
const showShortcuts = ref(false)

// 多选导出（#21）
const exportIds = ref(new Set())

// ---- 双链 ----
const rightPanel = ref(false)
const rightTab = ref('links')
const backlinks = ref([])
const outgoingLinks = ref([])
const dangling = ref([])
const graph = ref(null)
const showGraph = ref(false)
const linkSuggest = ref([])
let linkQuery = { start: -1, end: -1 }
let openSeq = 0

const backlinkCount = computed(() => backlinks.value.length)

// ---- AI ----
const aiBusy = ref(false)
const aiSummary = ref('')
const aiPoints = ref([])
const aiQa = ref([])
const aiQuestion = ref('')
const aiProvider = ref('')
const aiHint = ref('')

// ---- 协同 ----
const collabMode = ref(false)
const collabStatus = ref('off')
const collabPeers = ref([])
const collabText = ref('')
let collab = null

const collabStatusLabel = computed(() => ({
  off: '未开启', connecting: '连接中', connected: '已连接', ready: '同步中', closed: '已断开',
}[collabStatus.value] || collabStatus.value))

// #18 本地结构统计：一次扫描 + 180ms 防抖，避免每次按键跑 4 条全量正则
const activeContent = computed(() => (collabMode.value ? collabText.value : (current.value?.content || '')))
const stat = ref({ words: 0, paras: 0, headings: 0, lists: 0 })
let statTimer = null
watch(activeContent, (text) => {
  clearTimeout(statTimer)
  statTimer = setTimeout(() => {
    const t = text || ''
    stat.value = {
      words: t.replace(/\s/g, '').length,
      paras: t.split(/\n\s*\n/).filter((s) => s.trim()).length,
      headings: (t.match(/^#{1,6}\s/gm) || []).length,
      lists: (t.match(/^\s*([-*+]|\d+\.)\s/gm) || []).length,
    }
  }, 180)
}, { immediate: true })
const statReadMin = computed(() => Math.max(1, Math.round(stat.value.words / 300)))

// F258：目录树按展开状态扁平化返回（带层级用于缩进）
const shownRows = computed(() => {
  const out = []
  const walk = (nodes, depth) => {
    for (const n of nodes) {
      const children = n.children || []
      out.push({ n, depth, hasChildren: children.length > 0, expanded: isExpanded(n.id) })
      if (children.length && isExpanded(n.id)) walk(children, depth + 1)
    }
  }
  walk(tree.value || [], 0)
  return out
})
// F6：marked + DOMPurify 安全渲染（marked 本身不消毒，直接 v-html 有 XSS 风险）
// F257：渲染后再把 [[标题]] 包成可悬停预览的 .wl 节点
const rendered = computed(() => decorateWikilinks(renderMarkdown(current.value?.content || '')))

async function loadTree() {
  const r = await noteApi.tree()
  tree.value = r.tree || []
  // F258：树更新后清掉已删除笔记的展开记录，避免 localStorage 无限膨胀
  pruneExpanded()
}
async function loadTags() {
  const r = await noteApi.tags()
  tags.value = r.list || []
  try { cloudTags.value = (await noteApi.tagCloud()).list || [] } catch (e) { cloudTags.value = [] }
}
async function loadTrash() {
  const r = await noteApi.trash()
  trashList.value = r.list || []
}
async function loadArchived() {
  const r = await noteApi.list({ archived: 1, all: 1, page_size: 200 })
  tree.value = (r.list || []).map((n) => ({ ...n, children: [] }))
}
async function loadTemplates() {
  const r = await noteApi.templates()
  templates.value = r.list || []
}
function switchSide(t) {
  sideTab.value = t
  if (t === 'trash') loadTrash()
  else if (t === 'archived') loadArchived()
  else loadTree()
}
async function openNote(id) {
  // 切换序号：快速连点时只允许最后一次响应落地
  const seq = ++openSeq
  // F7：切笔记前先把上一篇的待存内容落库（防抖窗口内不丢）
  await flushSave()
  if (seq !== openSeq) return
  if (collabMode.value) stopCollab()
  const r = await noteApi.detail(id)
  if (seq !== openSeq) return
  current.value = r
  activeNote.value = id
  selectedWord.value = ''
  backlinks.value = current.value.backlinks || []
  outgoingLinks.value = current.value.outgoing_links || []
  aiSummary.value = current.value.ai_summary || ''
  aiPoints.value = []
  aiQa.value = []
  linkSuggest.value = []
  resetAiInfo()
  // F236/F245：面板打开时跟随当前笔记刷新
  comments.value = []
  relatedNotes.value = []
  cancelReply()
  commentQuote.value = ''
  if (rightPanel.value) {
    loadDangling()
    loadRelated()
    if (rightTab.value === 'comments') loadComments()
  }
  // F254：恢复到上次阅读位置
  restoreScroll(id)
}
async function createNote(title) {
  const n = await noteApi.create({ title: title || '未命名笔记', content: '' })
  createdNoteId.value = n.id
  loadTree()
  openNote(n.id)
  // F259：同标题已存在时提示，可保留新建或直接打开旧笔记
  if (n.duplicate_titles?.length) {
    duplicateExisting.value = n.duplicate_titles
    showDuplicate.value = true
    app.toastMsg(`已有同名笔记《${n.title}》，双链会指向最新一篇`, 'info')
  }
}
async function useTemplate(key) {
  const n = await noteApi.fromTemplate(key)
  showTemplates.value = false
  loadTree(); openNote(n.id)
}
// #20 插入模板到当前正文
function insertTemplatePrompt() {
  if (!current.value) return
  const tpl = templates.value.find((t) => t.key === 'meeting') || templates.value[0]
  if (!tpl) return
  current.value.content = (current.value.content || '') + '\n\n' + tpl.content
  autoSave()
  app.toastMsg(`已插入「${tpl.title}」`, 'success')
}
async function duplicate() {
  if (!current.value) return
  const n = await noteApi.copy(current.value.id)
  app.toastMsg('已复制', 'success')
  loadTree(); openNote(n.id)
}
async function deleteNote() {
  await noteApi.remove(current.value.id)
  // F254：删除后清掉本地阅读位置
  clearScroll(current.value.id)
  app.toastMsg('已移入回收站', 'success')
  current.value = null
  loadTree()
}
async function restoreNote(n) {
  await noteApi.batch({ action: 'restore', note_ids: [n.id] })
  loadTrash(); loadTree()
}
async function destroyNote(n) {
  if (!confirm('彻底删除无法恢复？')) return
  await noteApi.batch({ action: 'destroy', note_ids: [n.id] })
  clearScroll(n.id)
  loadTrash()
}
async function emptyTrash() {
  if (!confirm('清空回收站？')) return
  await noteApi.emptyTrash()
  loadTrash()
}
// #16 归档
async function toggleArchive() {
  if (!current.value) return
  const act = current.value.is_archived ? 'unarchive' : 'archive'
  await noteApi.batch({ action: act, note_ids: [current.value.id] })
  current.value.is_archived = !current.value.is_archived
  app.toastMsg(current.value.is_archived ? '已归档' : '已取消归档', 'success')
  loadTree()
}
// F7：防抖自动保存 + 离开前强制落盘（切笔记/切标签/关页面不丢最后一段输入）
const { schedule: scheduleSave, flush: flushSave } = useAutosave(
  async () => {
    if (!current.value || collabMode.value) return
    const id = current.value.id
    const title = current.value.title
    const content = current.value.content
    saving.value = true
    try {
      const saved = await noteApi.update(id, { title, content })
      // 请求期间可能已切到另一篇：只回写时间戳，绝不整体覆盖编辑器当前内容
      if (current.value && current.value.id === id) {
        current.value.updated_at = saved?.updated_at ?? current.value.updated_at
      }
      loadTree()
    } finally {
      setTimeout(() => (saving.value = false), 600)
    }
  },
  { delay: 800, beacon: beaconSave },
)
function autoSave() { scheduleSave() }

// F7：保底通道。页面隐藏/卸载时异步请求可能被取消，用 fetch keepalive
// 复用同一 PATCH 接口（sendBeacon 带不了 Authorization 头，同步 XHR 已废弃）
function beaconSave() {
  if (!current.value || collabMode.value) return
  const token = localStorage.getItem('access_token')
  if (!token) return
  const id = current.value.id
  const title = current.value.title
  const content = current.value.content
  const body = JSON.stringify({ title, content })
  // fetch keepalive 请求体上限约 64KB；超长笔记降级写入本地草稿，避免静默丢失
  if (body.length > 60000) {
    try {
      localStorage.setItem(`note_beacon_draft_${id}`, JSON.stringify({ title, content, ts: Date.now() }))
    } catch (e) { /* ignore */ }
    return
  }
  try {
    fetch(`${API_URL}/notes/${id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body,
      keepalive: true,
    })
  } catch {
    /* ignore */
  }
}

// ================= 双链 =================
async function loadBacklinks() {
  if (!current.value) return
  const r = await noteApi.backlinks(current.value.id)
  backlinks.value = r.backlinks || []
  outgoingLinks.value = r.outgoing_links || []
  if (rightPanel.value) loadDangling()
}
async function loadDangling() {
  try {
    dangling.value = (await noteApi.dangling()).list || []
  } catch (e) { dangling.value = [] }
}
async function loadGraph() {
  graph.value = await noteApi.linkGraph(120)
  showGraph.value = true
}
async function createFromTitle(title) {
  const n = await noteApi.fromTitle(title)
  app.toastMsg('已创建并接上双链', 'success')
  loadTree()
  if (n.id) openNote(n.id)
}
function onContentInput(e) {
  const val = e.target.value
  if (collabMode.value && collab) {
    collab.applyLocalText(val)
    collabText.value = val
    current.value && (current.value.content = val)
    detectLinkQuery(e.target)
    return
  }
  if (!current.value) return
  // 必须回写 state：自动保存/beacon 都从 current.content 取值
  current.value.content = val
  autoSave()
  detectLinkQuery(e.target)
}
function detectLinkQuery(el) {
  if (!el) return
  const pos = el.selectionStart ?? 0
  const before = (el.value || '').slice(0, pos)
  const open = before.lastIndexOf('[[')
  if (open < 0) { linkSuggest.value = []; return }
  const frag = before.slice(open + 2)
  if (frag.includes(']]') || frag.includes('\n') || frag.length > 30) {
    linkSuggest.value = []
    return
  }
  linkQuery = { start: open, end: pos }
  noteApi.linkSuggest(frag.trim(), current.value?.id)
    .then((r) => { linkSuggest.value = (r.list || []).slice(0, 8) })
    .catch(() => { linkSuggest.value = [] })
}
function insertLink(title) {
  if (!current.value || linkQuery.start < 0) return
  const end = linkQuery.end ?? linkQuery.start
  if (collabMode.value && collab) {
    const val = collabText.value || ''
    const next = `${val.slice(0, linkQuery.start)}[[${title}]]${val.slice(end)}`
    collab.applyLocalText(next)
    collabText.value = next
    current.value.content = next
    linkSuggest.value = []
    return
  }
  const el = contentEl.value
  // 以 textarea 当前值为准：current.content 可能还没跟上最近一次输入
  const val = el ? el.value : (current.value.content || '')
  const next = `${val.slice(0, linkQuery.start)}[[${title}]]${val.slice(end)}`
  current.value.content = next
  if (el) {
    el.value = next
    const caret = linkQuery.start + title.length + 4
    el.focus()
    el.setSelectionRange(caret, caret)
  }
  linkSuggest.value = []
  autoSave()
  setTimeout(loadBacklinks, 900)
}

// ================= AI =================
function resetAiInfo() {
  aiHint.value = ''
  aiProvider.value = ''
}
async function ensureAiStatus() {
  if (aiProvider.value) return
  try {
    const s = await aiApi.status()
    aiProvider.value = s.mode_label || s.provider
    aiHint.value = s.configured ? '' : '未配置大模型，使用本地降级'
  } catch (e) { aiProvider.value = '本地' }
}
async function aiSummarize() {
  if (!current.value || aiBusy.value) return
  aiBusy.value = true
  try {
    const r = await aiApi.summarize(current.value.id, { force: false })
    aiSummary.value = r.summary || ''
    aiPoints.value = r.key_points || []
    aiProvider.value = r.provider === 'cache' ? '缓存' : (r.provider === 'llm' ? '大模型' : '本地降级')
    aiHint.value = r.fallback_reason || ''
  } catch (e) {
    app.toastMsg(e.message || '生成失败', 'error')
  } finally {
    aiBusy.value = false
  }
}
// #13 AI 大纲（后端本地抽取式降级）
async function aiOutline() {
  if (!current.value) return
  try {
    const r = await noteApi.aiOutline(current.value.id)
    outline.value = r.outline || []
    aiOutlineSummary.value = r.summary || ''
    showOutline.value = true
  } catch (e) { app.toastMsg(e.message || '生成失败', 'error') }
}
async function aiAsk() {
  const q = aiQuestion.value.trim()
  if (!q || !current.value || aiBusy.value) return
  aiBusy.value = true
  try {
    const r = await aiApi.askNote(current.value.id, q)
    aiQa.value.unshift({ q, a: r.answer, refs: r.references || [] })
    aiQuestion.value = ''
    aiProvider.value = r.provider === 'llm' ? '大模型' : '本地降级'
    aiHint.value = r.fallback_reason || ''
  } catch (e) {
    app.toastMsg(e.message || '提问失败', 'error')
  } finally {
    aiBusy.value = false
  }
}

// ================= 协同编辑 =================
async function toggleCollab() {
  if (collabMode.value) { stopCollab(); return }
  if (!current.value) return
  const note = current.value
  collabMode.value = true
  collabStatus.value = 'connecting'
  collabText.value = note.content || ''
  try {
    const { NoteCollab } = await import('../../utils/collab')
    // 加载期间用户可能已关闭协同或切走笔记
    if (!collabMode.value || current.value?.id !== note.id) return
    collab = new NoteCollab(note.id, {
      initialContent: note.content || '',
      onText: (t) => { collabText.value = t; current.value.content = t },
      onStatus: (s) => { collabStatus.value = s },
      onPresence: (list) => { collabPeers.value = (list || []).map((p) => p.name) },
    })
    collab.connect()
    app.toastMsg('已开启协同编辑，内容将实时同步', 'success')
  } catch (e) {
    collabMode.value = false
    collabStatus.value = 'off'
    app.toastMsg(e?.message || '协同模块加载失败', 'error')
  }
}
function stopCollab() {
  const noteId = current.value?.id
  if (collab) collab.destroy()
  collab = null
  collabMode.value = false
  collabStatus.value = 'off'
  collabPeers.value = []
  if (noteId) {
    noteApi.detail(noteId).then((r) => {
      // 响应回来时可能已切到别的笔记，只更新仍指向同一篇的情况
      if (current.value && current.value.id === noteId) current.value = r
    })
  }
}
async function toggleFlag(flag) {
  current.value = await noteApi.update(current.value.id, { [flag]: !current.value[flag] })
  loadTree()
}
async function addTag() {
  const name = tagInput.value.trim()
  if (!name) return
  current.value = await noteApi.update(current.value.id, { tags: [...(current.value.tag_names || []), name] })
  tagInput.value = ''
  loadTags(); loadTree()
}
async function removeTag(name) {
  current.value = await noteApi.update(current.value.id, { tags: current.value.tag_names.filter((t) => t !== name) })
  loadTags()
}
async function loadVersions() {
  versions.value = (await noteApi.versions(current.value.id)).list || []
}
async function rollback(v) {
  const r = await noteApi.rollback(current.value.id, v.version)
  current.value = r.note
  showVersions.value = false
  loadTree()
}
// #22 与上一版本对比
async function diffWith(v) {
  const idx = versions.value.indexOf(v)
  const prev = versions.value[idx + 1]
  if (!prev) { app.toastMsg('没有更早版本可对比', 'error'); return }
  try {
    const r = await noteApi.versionDiff(current.value.id, prev.version, v.version)
    diffLines.value = r.diff || []
    diffFrom.value = 'v' + prev.version
    diffTo.value = 'v' + v.version
    showDiff.value = true
  } catch (e) { app.toastMsg(e.message || '对比失败', 'error') }
}
async function loadOutline() {
  outline.value = (await noteApi.outline(current.value.id)).outline || []
  aiOutlineSummary.value = ''
  showOutline.value = true
}
// #15 闪卡
async function loadFlashcards() {
  if (!current.value) return
  const r = await noteApi.flashcards(current.value.id)
  cards.value = r.cards || []
  cardIdx.value = 0
  cardShow.value = false
  showCards.value = true
}
async function loadStats() {
  stats.value = await noteApi.stats()
  // F573 来源统计
  try { sourcesData.value = await notex.sources() } catch (e) { sourcesData.value = {} }
}
async function saveTag(t) {
  await noteApi.updateTag(t.id, { name: t.name, color: t.color })
  loadTags()
}
async function delTag(t) {
  await noteApi.deleteTag(t.id)
  loadTags()
}
async function addNewTag() {
  if (!newTagName.value.trim()) return
  await noteApi.createTag({ name: newTagName.value.trim(), color: '#0ea5e9' })
  newTagName.value = ''
  loadTags()
}
// #14 批量导入
async function doImport() {
  if (!importMd.value.trim()) { showImport.value = false; return }
  try {
    const r = await noteApi.batchImport({ markdown: importMd.value })
    app.toastMsg(`已导入 ${r.count} 篇笔记`, 'success')
    importMd.value = ''
    showImport.value = false
    loadTree()
  } catch (e) { app.toastMsg(e.message || '导入失败', 'error') }
}
// #21 多选导出
function toggleExportPick(id) {
  const s = new Set(exportIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  exportIds.value = s
}
async function exportSelected() {
  if (!exportIds.value.size) { app.toastMsg('请先勾选要导出的笔记（编辑器标题前的复选框）', 'error'); return }
  try {
    const blob = await noteApi.exportSelected({ note_ids: [...exportIds.value], format: 'zip' })
    saveBlob(blob, 'notes_selected.zip')
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}
async function exportNote() {
  if (!current.value) return
  try {
    await downloadWithAuth(noteApi.exportUrl(current.value.id), `${current.value.title || 'note'}.md`)
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}
async function exportAll() {
  try {
    await downloadWithAuth(noteApi.exportAllUrl(), 'notes.zip')
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}

// ================= F565–F582 笔记知识库新增能力 =================

const NOTE_COLORS = { red: '红', orange: '橙', yellow: '黄', green: '绿', blue: '蓝', purple: '紫' }
const COLOR_HEX = { red: '#ef4444', orange: '#f97316', yellow: '#eab308', green: '#22c55e', blue: '#3b82f6', purple: '#8b5cf6' }
const SOURCE_LABELS = { manual: '手动创建', template: '模板创建', import: '批量导入', copy: '复制副本', link: '双链创建', split: '拆分生成', merge: '合并生成' }
const WEEK_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
function colorHex(key) { return COLOR_HEX[key] || '#cbd5e1' }
function sourceLabel(s) { return SOURCE_LABELS[s] || s || '' }

// ---- F571 只看置顶 ----
const pinnedOnly = ref(false)
async function togglePinnedOnly() {
  pinnedOnly.value = !pinnedOnly.value
  if (sideTab.value !== 'all') return
  if (pinnedOnly.value) {
    selectedTags.value = []
    try {
      const r = await noteApi.list({ pinned: 1, all: 1, page_size: 200 })
      tree.value = (r.list || []).map((n) => ({ ...n, children: [] }))
    } catch (e) { tree.value = [] }
  } else if (selectedTags.value.length) {
    loadTagNotes()
  } else {
    activeFolder.value ? filterFolder(activeFolder.value) : loadTree()
  }
}

// ---- F565 字数目标 ----
const showGoals = ref(false)
const goalsData = ref({})
const newGoal = ref({ target: 500, period: 'day' })
async function openGoals() {
  showGoals.value = true
  try { goalsData.value = await notex.goals() } catch (e) { goalsData.value = {} }
}
async function addGoal() {
  const target = Number(newGoal.value.target)
  if (!target || target <= 0) { app.toastMsg('请填写目标字数', 'error'); return }
  const payload = { target, period: newGoal.value.period }
  if (payload.period === 'note') {
    if (!current.value) { app.toastMsg('请先打开一篇笔记', 'error'); return }
    payload.note_id = current.value.id
  }
  try {
    await notex.createGoal(payload)
    app.toastMsg('目标已创建 🎯', 'success')
    openGoals()
  } catch (e) { app.toastMsg(e.message || '创建失败', 'error') }
}
async function removeGoal(id) {
  try { await notex.deleteGoal(id); openGoals() } catch (e) { app.toastMsg(e.message || '删除失败', 'error') }
}

// ---- F566 日记视图 ----
const showDiary = ref(false)
const diary = ref({})
const diaryDay = ref(null)
async function openDiary() {
  showDiary.value = true
  diaryDay.value = null
  const now = new Date()
  await loadDiary(now.getFullYear(), now.getMonth() + 1)
}
async function loadDiary(year, month) {
  try {
    diary.value = await notex.diary(year, month)
    diaryDay.value = null
  } catch (e) { app.toastMsg(e.message || '加载失败', 'error') }
}
function shiftDiary(dir) {
  const p = dir < 0 ? diary.value.prev : diary.value.next
  if (p) loadDiary(p.year, p.month)
}

// ---- F567 未链接提及 ----
const showMentions = ref(false)
const mentions = ref([])
async function openMentions() {
  showMentions.value = true
  try { mentions.value = (await notex.unlinkedMentions(50)).list || [] } catch (e) { mentions.value = [] }
}
async function linkifyMention(m, s) {
  try {
    const n = await noteApi.detail(s.note_id)
    if (!(n.content || '').includes(m.target_title)) { app.toastMsg('原文已变化，请重新打开', 'error'); return }
    const content = n.content.replace(m.target_title, `[[${m.target_title}]]`)
    await noteApi.update(n.id, { content })
    app.toastMsg('已转为双链', 'success')
    if (current.value && current.value.id === n.id) openNote(n.id)
    openMentions()
  } catch (e) { app.toastMsg(e.message || '操作失败', 'error') }
}

// ---- F568 随机回顾 ----
async function openRandom() {
  try {
    const n = await notex.random(current.value ? current.value.id : undefined)
    app.toastMsg(`🎲 随机抽到《${n.title}》（可抽 ${n.pool_size} 篇）`, 'info')
    openNote(n.id)
  } catch (e) { app.toastMsg(e.message || '没有可回顾的笔记', 'error') }
}

// ---- F569 健康度报告 ----
const showHealth = ref(false)
const health = ref({})
const healthDash = computed(() => {
  const C = 2 * Math.PI * 42
  const score = Math.max(0, Math.min(100, Number(health.value.avg_score) || 0))
  return `${((score / 100) * C).toFixed(1)} ${C.toFixed(1)}`
})
function gradeColor(g) { return { A: '#22c55e', B: '#0ea5e9', C: '#f59e0b', D: '#ef4444' }[g] || '#94a3b8' }
async function openHealth() {
  showHealth.value = true
  try { health.value = await notex.health({ limit: 30 }) } catch (e) { health.value = {} }
}

// ---- F570 大纲点击跳转 ----
const previewRef = ref(null)
async function jumpOutline(h) {
  const title = String(h.title || h.text || '').trim()
  editorTab.value = 'preview'
  showOutline.value = false
  await nextTick()
  const root = previewRef.value
  if (!root) return
  const heads = Array.from(root.querySelectorAll('h1,h2,h3,h4,h5,h6'))
  const target = heads.find((el) => el.textContent.trim() === title) ||
    heads.find((el) => el.textContent.trim().includes(title))
  if (!target) { app.toastMsg('未在正文中找到该标题', 'error'); return }
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const old = target.style.background
  target.style.background = 'rgba(14,165,233,0.18)'
  setTimeout(() => { target.style.background = old }, 1400)
}

// ---- F572 六色标记 ----
const showColorPicker = ref(false)
async function setColor(key) {
  if (!current.value) return
  try {
    const r = await noteApi.update(current.value.id, { color: key })
    current.value = { ...current.value, color: r.color }
    showColorPicker.value = false
    loadTree()
    app.toastMsg(key ? `已标记为${NOTE_COLORS[key]}` : '已清除颜色', 'success')
  } catch (e) { app.toastMsg(e.message || '设置失败', 'error') }
}

// ---- F573 来源统计 ----
const sourcesData = ref({})

// ---- F574 片段库 ----
const showSnippets = ref(false)
const snippets = ref([])
const snippetQuery = ref('')
const showNewSnippet = ref(false)
const newSnippet = ref({ title: '', content: '' })
async function openSnippets() {
  showSnippets.value = true
  await loadSnippets()
}
async function loadSnippets() {
  try { snippets.value = (await notex.snippets({ q: snippetQuery.value })).list || [] } catch (e) { snippets.value = [] }
}
async function createSnippet() {
  if (!newSnippet.value.title.trim() && !newSnippet.value.content.trim()) {
    app.toastMsg('标题或内容不能为空', 'error')
    return
  }
  try {
    await notex.createSnippet({ ...newSnippet.value })
    newSnippet.value = { title: '', content: '' }
    showNewSnippet.value = false
    loadSnippets()
    app.toastMsg('片段已保存 ✂', 'success')
  } catch (e) { app.toastMsg(e.message || '保存失败', 'error') }
}
async function insertSnippet(s) {
  if (!current.value) { app.toastMsg('请先打开一篇笔记', 'error'); return }
  current.value.content = `${current.value.content || ''}\n\n${s.content}`
  autoSave()
  try { await notex.useSnippet(s.id); loadSnippets() } catch (e) { /* 计数失败不影响插入 */ }
  app.toastMsg(`已插入「${s.title}」`, 'success')
}
async function removeSnippet(id) {
  if (!confirm('删除该片段？')) return
  try { await notex.deleteSnippet(id); loadSnippets() } catch (e) { app.toastMsg(e.message || '删除失败', 'error') }
}

// ---- F575 合并 ----
const showMerge = ref(false)
const mergeQuery = ref('')
const mergeTargets = ref([])
const mergeTarget = ref(null)
const keepSource = ref(false)
async function openMerge() {
  if (!current.value) return
  showMerge.value = true
  mergeTarget.value = null
  mergeQuery.value = ''
  await searchMergeTargets()
}
async function searchMergeTargets() {
  try {
    const r = await noteApi.list({ all: 1, search: mergeQuery.value || '', page_size: 30 })
    mergeTargets.value = (r.list || []).filter((n) => n.id !== current.value?.id && !n.is_deleted)
  } catch (e) { mergeTargets.value = [] }
}
async function doMerge() {
  if (!mergeTarget.value || !current.value) return
  try {
    const r = await notex.merge({
      source_id: current.value.id, target_id: mergeTarget.value, keep_source: keepSource.value,
    })
    app.toastMsg(r.message || '已合并 🔀', 'success')
    showMerge.value = false
    loadTree()
    if (r.source_deleted) openNote(mergeTarget.value)
    else openNote(current.value.id)
  } catch (e) { app.toastMsg(e.message || '合并失败', 'error') }
}

// ---- F576 拆分 ----
const showSplit = ref(false)
const splitSections = ref([])
const keepOriginal = ref(true)
async function openSplit() {
  if (!current.value) return
  showSplit.value = true
  splitSections.value = []
  try {
    const r = await notex.split(current.value.id, { preview: true })
    splitSections.value = r.sections || []
  } catch (e) { splitSections.value = []; app.toastMsg(e.message || '无法拆分', 'error') }
}
async function doSplit() {
  if (!current.value) return
  try {
    const r = await notex.split(current.value.id, { keep_original: keepOriginal.value })
    app.toastMsg(r.message || '已拆分 ✂', 'success')
    showSplit.value = false
    loadTree()
    if (r.created && r.created.length) openNote(r.created[0].id)
  } catch (e) { app.toastMsg(e.message || '拆分失败', 'error') }
}

// ---- F577 阅读模式 ----
const readingMode = ref(typeof localStorage !== 'undefined' && localStorage.getItem('notes.readingMode') === '1')
function toggleReading() {
  readingMode.value = !readingMode.value
  try { localStorage.setItem('notes.readingMode', readingMode.value ? '1' : '0') } catch (e) { /* ignore */ }
  if (readingMode.value) editorTab.value = 'preview'
}

// ---- F578 选词存生词（失败降级不报错） ----
const selectedWord = ref('')
const showWordbook = ref(false)
const wordInput = ref('')
const wordList = ref([])
const localWords = ref([])
function trackSelection(el) {
  let sel = ''
  if (el && typeof el.selectionStart === 'number') {
    sel = (el.value || '').slice(el.selectionStart, el.selectionEnd)
  } else if (typeof window !== 'undefined' && window.getSelection) {
    sel = String(window.getSelection() || '')
  }
  sel = sel.trim()
  selectedWord.value = (sel && sel.length <= 40 && !sel.includes('\n')) ? sel : ''
}
function editorKeyup(el) {
  detectLinkQuery(el)
  trackSelection(el)
}
function persistLocalWords() {
  try { localStorage.setItem('notes.localWords', JSON.stringify(localWords.value)) } catch (e) { /* ignore */ }
}
function loadLocalWords() {
  try { localWords.value = JSON.parse(localStorage.getItem('notes.localWords') || '[]') } catch (e) { localWords.value = [] }
}
async function saveWord(word) {
  let w = String(word || selectedWord.value || '').trim()
  if (!w) { app.toastMsg('请先在正文里选中一个单词', 'info'); return }
  if (w.length > 60) w = w.slice(0, 60)
  wordInput.value = ''
  try {
    await notex.addWord(w)
    app.toastMsg(`「${w}」已加入学习区生词本 📚`, 'success')
  } catch (e) {
    // 降级：生词本不可用时本地暂存，不抛错
    loadLocalWords()
    localWords.value = [{ word: w, local: true, at: Date.now() },
      ...localWords.value.filter((x) => x.word !== w)]
    persistLocalWords()
    app.toastMsg(`「${w}」已本地暂存（生词本暂不可用）`, 'info')
  }
  selectedWord.value = ''
  if (showWordbook.value) loadWordbook()
}
async function loadWordbook() {
  loadLocalWords()
  try {
    const r = await notex.listWords()
    wordList.value = [...(r.list || []).map((x) => ({ ...x, local: false })), ...localWords.value]
  } catch (e) {
    wordList.value = [...localWords.value]
  }
}
async function openWordbook() {
  showWordbook.value = true
  await loadWordbook()
}
async function syncLocalWords() {
  loadLocalWords()
  const ok = []
  for (const item of [...localWords.value]) {
    try { await notex.addWord(item.word); ok.push(item.word) } catch (e) { /* 保留本地 */ }
  }
  if (ok.length) {
    localWords.value = localWords.value.filter((w) => !ok.includes(w.word))
    persistLocalWords()
    app.toastMsg(`已同步 ${ok.length} 个词到生词本`, 'success')
  } else {
    app.toastMsg('生词本仍不可用，稍后再试', 'info')
  }
  loadWordbook()
}

// ---- F579 每周回顾 ----
const showWeekly = ref(false)
const weekly = ref({})
async function openWeekly() {
  showWeekly.value = true
  await loadWeekly()
}
async function loadWeekly(week) {
  try { weekly.value = await notex.weeklyReview(week || undefined) } catch (e) { app.toastMsg(e.message || '加载失败', 'error') }
}

// ---- F580 待办抽取清单 ----
const showTodos = ref(false)
const todos = ref([])
const todoFilter = ref('open')
const todoMine = ref(false)
const todoOpenCount = ref(0)
const todoDoneCount = ref(0)
async function openTodos() {
  showTodos.value = true
  await loadTodos()
}
async function loadTodos() {
  try {
    const params = { include_done: todoFilter.value === 'open' ? 0 : 1, limit: 500 }
    if (todoMine.value && current.value) params.note_id = current.value.id
    const r = await notex.todos(params)
    let list = r.list || []
    if (todoFilter.value === 'done') list = list.filter((t) => t.done)
    if (todoFilter.value === 'open') list = list.filter((t) => !t.done)
    todos.value = list
    todoOpenCount.value = r.open_count || 0
    todoDoneCount.value = r.done_count || 0
  } catch (e) { todos.value = [] }
}
async function toggleTodoItem(t) {
  try {
    const r = await notex.toggleTodo({ note_id: t.note_id, line_no: t.line_no })
    t.done = r.done
    todoOpenCount.value = Math.max(0, todoOpenCount.value + (r.done ? -1 : 1))
    todoDoneCount.value = Math.max(0, todoDoneCount.value + (r.done ? 1 : -1))
    // F242：就地更新进度与正文勾选，不重新拉详情（避免打断编辑）
    if (current.value && current.value.id === t.note_id) {
      current.value.todo_done = Math.max(0, (current.value.todo_done || 0) + (r.done ? 1 : -1))
      const lines = (current.value.content || '').split('\n')
      const idx = Number(t.line_no)
      if (lines[idx] != null && /\[[ xX]\]/.test(lines[idx])) {
        lines[idx] = lines[idx].replace(/\[[ xX]\]/, r.done ? '[x]' : '[ ]')
        current.value.content = lines.join('\n')
        autoSave()
      }
    }
  } catch (e) { app.toastMsg(e.message || '更新失败', 'error') }
}

// ---- F581 引用格式 ----
const showCitation = ref(false)
const citation = ref({
  style: 'gbt7714',
  styles: [{ key: 'gbt7714', label: 'GB/T 7714-2015' }, { key: 'apa', label: 'APA 7th' }],
  items: [],
})
async function openCitation() {
  showCitation.value = true
  await loadCitation()
}
async function loadCitation() {
  try {
    const params = { style: citation.value.style }
    if (current.value) params.ids = String(current.value.id)
    const r = await notex.citation(params)
    citation.value = {
      ...citation.value,
      items: r.items || [],
      styles: r.styles || citation.value.styles,
    }
  } catch (e) { citation.value = { ...citation.value, items: [] } }
}
async function copyText(text) {
  let copied = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      copied = true
    }
  } catch { /* 非 HTTPS / 权限拒绝 */ }
  if (!copied) {
    // 降级：临时 textarea + execCommand，仍失败则如实提示
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      copied = document.execCommand('copy')
      document.body.removeChild(ta)
    } catch { copied = false }
  }
  app.toastMsg(copied ? '已复制引用格式' : '复制失败，请手动选择文本', copied ? 'success' : 'error')
}

// ---- F582 分组文件夹 ----
const noteFolders = ref([])
const activeFolder = ref(null)
const showNewFolder = ref(false)
const newFolderName = ref('')
async function loadFolders() {
  try { noteFolders.value = (await notex.folders()).list || [] } catch (e) { noteFolders.value = [] }
}
function folderName(id) {
  const f = noteFolders.value.find((x) => x.id === id)
  return f ? f.name : '未分组'
}
async function filterFolder(id) {
  activeFolder.value = id
  selectedTags.value = []
  pinnedOnly.value = false
  if (id == null) { await loadTree(); return }
  try {
    const r = await noteApi.list({ folder: id, all: 1, page_size: 200 })
    tree.value = (r.list || []).map((n) => ({ ...n, children: [] }))
  } catch (e) { tree.value = [] }
}
async function createNoteFolder() {
  const name = newFolderName.value.trim()
  if (!name) return
  try {
    await notex.createFolder({ name })
    newFolderName.value = ''
    showNewFolder.value = false
    loadFolders()
    app.toastMsg('文件夹已创建 📁', 'success')
  } catch (e) { app.toastMsg(e.message || '创建失败', 'error') }
}
async function moveToFolder(val) {
  if (!current.value) return
  const folder = (val === '' || val === 'null' || val === null) ? null : Number(val)
  try {
    const r = await noteApi.update(current.value.id, { folder })
    current.value = { ...current.value, folder: r.folder, folder_name: r.folder_name }
    loadFolders()
    if (activeFolder.value != null) filterFolder(activeFolder.value)
    app.toastMsg(`已移动到「${folderName(folder)}」`, 'success')
  } catch (e) { app.toastMsg(e.message || '移动失败', 'error') }
}

// ================= F236–F260 协作 / 素材 / 推荐 / 视图 =================

// ---- F252 专注模式 / F253 紧凑密度（均持久化） ----
const focusMode = ref(readFlag('notes.focusMode'))
function readFlag(key) {
  try { return localStorage.getItem(key) === '1' } catch (e) { return false }
}
function readDensity() {
  try { return localStorage.getItem('notes.density') === 'compact' ? 'compact' : 'comfortable' } catch (e) { return 'comfortable' }
}
const density = ref(readDensity())
function toggleFocus() {
  focusMode.value = !focusMode.value
  try { localStorage.setItem('notes.focusMode', focusMode.value ? '1' : '0') } catch (e) { /* ignore */ }
  applyFocusClass()
}
// F252：给 body 打标记，:global 样式里隐藏全局侧栏与顶栏
function applyFocusClass() {
  try { document.body.classList.toggle('note-focus', focusMode.value) } catch (e) { /* ignore */ }
}
function toggleDensity() {
  density.value = density.value === 'compact' ? 'comfortable' : 'compact'
  try { localStorage.setItem('notes.density', density.value) } catch (e) { /* ignore */ }
}

// ---- F258 目录树展开状态（null = 默认全展开） ----
const EXPAND_KEY = 'notes.expandedIds'
const expandedIds = ref(readExpanded())
function readExpanded() {
  try {
    const raw = localStorage.getItem(EXPAND_KEY)
    if (raw == null) return null
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? new Set(arr) : null
  } catch (e) { return null }
}
function collectIds(nodes, out = []) {
  for (const n of nodes || []) {
    out.push(n.id)
    if (n.children) collectIds(n.children, out)
  }
  return out
}
function isExpanded(id) {
  return expandedIds.value === null ? true : expandedIds.value.has(id)
}
function persistExpanded() {
  if (!expandedIds.value) return
  try { localStorage.setItem(EXPAND_KEY, JSON.stringify([...expandedIds.value])) } catch (e) { /* ignore */ }
}
function toggleExpand(id) {
  if (expandedIds.value === null) {
    expandedIds.value = new Set(collectIds(tree.value).filter((x) => x !== id))
  } else {
    const s = new Set(expandedIds.value)
    s.has(id) ? s.delete(id) : s.add(id)
    expandedIds.value = s
  }
  persistExpanded()
}
function pruneExpanded() {
  if (!expandedIds.value) return
  const valid = new Set(collectIds(tree.value))
  const next = new Set([...expandedIds.value].filter((id) => valid.has(id)))
  if (next.size !== expandedIds.value.size) {
    expandedIds.value = next
    persistExpanded()
  }
}
// 没有自定义图标时给一个稳定的默认表情
const DEFAULT_ICONS = ['📝', '📄', '🗒', '📃']
function noteIcon(n) {
  return DEFAULT_ICONS[(Number(n?.id) || 0) % DEFAULT_ICONS.length]
}

// ---- F247–F251 批量操作 ----
const pickedIds = ref(new Set())
const batchTagInput = ref('')
function togglePick(id) {
  const s = new Set(pickedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  pickedIds.value = s
}
function clearPicks() { pickedIds.value = new Set() }
async function runBatch(payload, okText) {
  if (!pickedIds.value.size) return
  try {
    const r = await noteApi.batch({ ...payload, note_ids: [...pickedIds.value] })
    app.toastMsg(okText || r.message || '已处理', 'success')
    clearPicks()
    loadTree()
    loadTags()
  } catch (e) { app.toastMsg(e.message || '批量操作失败', 'error') }
}
function batchFolder(val) {
  if (val === '' || val == null) return
  const folder = Number(val)
  runBatch({ action: 'folder', folder }, `已移动到「${folderName(folder)}」`)
}
function batchTag(action) {
  const name = batchTagInput.value.trim()
  if (!name) { app.toastMsg('请先填写标签名', 'error'); return }
  runBatch({ action, tag: name }, action === 'tag' ? `已为该标签批量打标「${name}」` : `已批量移除标签「${name}」`)
}
function batchColor(key) { runBatch({ action: 'color', color: key }, `已批量标为${NOTE_COLORS[key]}`) }

// ---- F249 多标签筛选（交集 / 并集） ----
const selectedTags = ref([])
const tagMode = ref('any')
async function loadTagNotes() {
  if (!selectedTags.value.length) { await loadTree(); return }
  try {
    const r = await noteApi.list({
      tags: selectedTags.value.join(','), mode: tagMode.value, all: 1, page_size: 200,
    })
    tree.value = (r.list || []).map((n) => ({ ...n, children: [] }))
  } catch (e) { tree.value = [] }
}
function toggleTagFilter(name) {
  const list = selectedTags.value.includes(name)
    ? selectedTags.value.filter((t) => t !== name)
    : [...selectedTags.value, name]
  selectedTags.value = list
  activeFolder.value = null
  pinnedOnly.value = false
  loadTagNotes()
}
function toggleTagMode() {
  tagMode.value = tagMode.value === 'all' ? 'any' : 'all'
  if (selectedTags.value.length) loadTagNotes()
}
function clearTags() {
  selectedTags.value = []
  activeFolder.value ? filterFolder(activeFolder.value) : loadTree()
}

// ---- F238 图标 ----
const EMOJIS = ['📝', '📄', '📚', '💡', '⭐', '🔥', '✅', '📌', '🗓', '🧠', '🎯', '❤️',
  '😀', '🙂', '😎', '🚀', '🌱', '☕', '🎵', '🏆', '🔖', '🧩']
const showIconPicker = ref(false)
async function setIcon(icon) {
  if (!current.value) return
  try {
    const r = await noteApi.update(current.value.id, { icon })
    current.value = { ...current.value, icon: r.icon }
    showIconPicker.value = false
    loadTree()
  } catch (e) { app.toastMsg(e.message || '设置图标失败', 'error') }
}

// ---- F241 阅读排版（本地持久化） ----
const DEFAULT_TYPO = { fontSize: 16, lineHeight: 1.9, width: 760 }
const typo = ref(loadTypo())
function loadTypo() {
  try {
    const saved = JSON.parse(localStorage.getItem('notes.typo') || 'null')
    return saved ? { ...DEFAULT_TYPO, ...saved } : { ...DEFAULT_TYPO }
  } catch (e) { return { ...DEFAULT_TYPO } }
}
function persistTypo() {
  try { localStorage.setItem('notes.typo', JSON.stringify(typo.value)) } catch (e) { /* ignore */ }
}
function resetTypo() {
  typo.value = { ...DEFAULT_TYPO }
  persistTypo()
}
const previewStyle = computed(() => ({
  fontSize: `${typo.value.fontSize}px`,
  lineHeight: typo.value.lineHeight,
  maxWidth: `${typo.value.width}px`,
  margin: '0 auto',
}))
const editorStyle = computed(() => (readingMode.value
  ? { fontSize: `${typo.value.fontSize}px`, lineHeight: typo.value.lineHeight }
  : {}))

// ---- F244 查找 / 替换 ----
const showFind = ref(false)
const findQuery = ref('')
const findReplaceText = ref('')
const findCaseSensitive = ref(false)
const findWholeWord = ref(false)
function escapeReg(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
function findPattern() {
  const q = findQuery.value
  if (!q) return null
  const body = findWholeWord.value ? `\\b${escapeReg(q)}\\b` : escapeReg(q)
  try { return new RegExp(body, findCaseSensitive.value ? 'g' : 'gi') } catch (e) { return null }
}
const findCount = computed(() => {
  const re = findPattern()
  if (!re) return 0
  return ((current.value?.content || '').match(re) || []).length
})
// 写回正文（textarea 与 state 同步，再触发自动保存）
function setContent(next) {
  if (!current.value) return
  current.value.content = next
  const el = contentEl.value
  if (el) el.value = next
  autoSave()
}
function replaceOne() {
  if (!current.value) return
  const re = findPattern()
  if (!re) return
  re.lastIndex = 0
  const m = re.exec(current.value.content || '')
  if (!m) { app.toastMsg('没有找到匹配内容', 'info'); return }
  const text = current.value.content || ''
  setContent(text.slice(0, m.index) + findReplaceText.value + text.slice(m.index + m[0].length))
}
function replaceAll() {
  if (!current.value) return
  const re = findPattern()
  if (!re) return
  const text = current.value.content || ''
  const next = text.replace(re, () => findReplaceText.value)
  if (next === text) { app.toastMsg('没有找到匹配内容', 'info'); return }
  setContent(next)
  app.toastMsg('已全部替换', 'success')
}

// ---- F246 快速记录 ----
const showQuick = ref(false)
const quickText = ref('')
async function submitQuick() {
  const content = quickText.value.trim()
  if (!content) return
  try {
    const n = await notex.quick({ content })
    quickText.value = ''
    loadTree()
    app.toastMsg(`已速记为《${n.title}》`, 'success')
  } catch (e) { app.toastMsg(e.message || '速记失败', 'error') }
}

// ---- F236 讨论 ----
const comments = ref([])
const commentDraft = ref('')
const commentQuote = ref('')
const commentParent = ref(null)
const commentParentAuthor = ref('')
const commentFilterOpen = ref(false)
const unresolvedCount = computed(() => comments.value.filter((c) => !c.resolved && !c.parent).length)
const shownComments = computed(() => (commentFilterOpen.value
  ? comments.value.filter((c) => !c.resolved)
  : comments.value))
async function loadComments() {
  if (!current.value) return
  try {
    comments.value = (await notex.comments(current.value.id)).list || []
  } catch (e) { comments.value = [] }
}
function openCommentsPanel() {
  rightPanel.value = true
  rightTab.value = 'comments'
  loadComments()
}
function grabQuote() {
  let sel = ''
  const el = contentEl.value
  if (el && typeof el.selectionStart === 'number' && el.selectionEnd > el.selectionStart) {
    sel = el.value.slice(el.selectionStart, el.selectionEnd)
  } else if (typeof window !== 'undefined' && window.getSelection) {
    sel = String(window.getSelection() || '')
  }
  sel = sel.trim()
  if (!sel) { app.toastMsg('请先在正文中选中要引用的文本', 'info'); return }
  commentQuote.value = sel.slice(0, 500)
}
function startReply(c) {
  commentParent.value = c.id
  commentParentAuthor.value = c.author_name || '匿名'
  grabQuote()
}
function cancelReply() {
  commentParent.value = null
  commentParentAuthor.value = ''
}
async function submitComment() {
  if (!current.value) return
  const content = commentDraft.value.trim()
  if (!content) { app.toastMsg('评论内容不能为空', 'error'); return }
  try {
    await notex.createComment(current.value.id, {
      content, quote: commentQuote.value || '', parent: commentParent.value || null,
    })
    commentDraft.value = ''
    commentQuote.value = ''
    cancelReply()
    await loadComments()
    current.value.comment_count = unresolvedCount.value
    app.toastMsg('已发表讨论', 'success')
  } catch (e) { app.toastMsg(e.message || '发表失败', 'error') }
}
async function resolveComment(c) {
  if (!current.value) return
  try {
    await notex.updateComment(current.value.id, c.id, { resolved: true })
    await loadComments()
    current.value.comment_count = unresolvedCount.value
  } catch (e) { app.toastMsg(e.message || '操作失败', 'error') }
}
async function removeComment(c) {
  if (!current.value || !confirm('删除这条讨论？')) return
  try {
    await notex.deleteComment(current.value.id, c.id)
    await loadComments()
    current.value.comment_count = unresolvedCount.value
  } catch (e) { app.toastMsg(e.message || '删除失败', 'error') }
}
function toggleCommentFilter() {
  commentFilterOpen.value = !commentFilterOpen.value
}

// ---- F245 相关笔记 ----
const relatedNotes = ref([])
async function loadRelated() {
  if (!current.value) return
  try {
    relatedNotes.value = (await notex.related(current.value.id)).list || []
  } catch (e) { relatedNotes.value = [] }
}
function toggleRightPanel() {
  rightPanel.value = !rightPanel.value
  if (!rightPanel.value) return
  loadDangling()
  if (rightTab.value === 'links') loadRelated()
  if (rightTab.value === 'comments') loadComments()
}

// ---- F237 附件 ----
const showAttachments = ref(false)
const attachments = ref([])
const attachQuery = ref('')
const attachFiles = ref([])
async function openAttachments() {
  showAttachments.value = true
  await Promise.all([loadAttachments(), loadAttachFiles()])
}
async function loadAttachments() {
  if (!current.value) return
  try {
    attachments.value = (await notex.attachments(current.value.id)).list || []
  } catch (e) { attachments.value = [] }
}
async function loadAttachFiles() {
  try {
    const r = await notex.attachableFiles({ q: attachQuery.value || '', limit: 30 })
    attachFiles.value = r.list || []
  } catch (e) { attachFiles.value = [] }
}
async function bindAttachment(f) {
  if (!current.value) return
  try {
    await notex.bindAttachment(current.value.id, { file_id: f.id })
    await loadAttachments()
    app.toastMsg('已绑定附件', 'success')
  } catch (e) { app.toastMsg(e.message || '绑定失败', 'error') }
}
async function unbindAttachment(a) {
  if (!current.value) return
  try {
    await notex.removeAttachment(current.value.id, a.id)
    await loadAttachments()
  } catch (e) { app.toastMsg(e.message || '移除失败', 'error') }
}
function insertAttachmentLink(a) {
  const md = a.kind === 'image'
    ? `\n![${a.name}](${a.thumbnail || a.url})\n`
    : `\n[📎 ${a.name}](${a.url})\n`
  insertIntoContent(md)
  showAttachments.value = false
}
// F237：正文里的附件链接带文件 id，点击时用带鉴权的下载通道（直开链接无 Authorization 头）
async function onPreviewClick(e) {
  const a = e.target?.closest?.('a')
  if (!a) return
  const hit = (a.getAttribute('href') || '').match(/\/api\/files\/(\d+)\/(?:download|raw)\//)
  if (!hit) return
  e.preventDefault()
  try {
    await downloadWithAuth(fileApi.downloadUrl(hit[1]), a.textContent.trim() || `file-${hit[1]}`)
  } catch (err) {
    app.toastMsg(await describeDownloadError(err), 'error')
  }
}

// ---- F239 封面图 ----
const showCoverPicker = ref(false)
const coverQuery = ref('')
const coverFiles = ref([])
async function openCoverPicker() {
  showCoverPicker.value = true
  await loadCoverFiles()
}
async function loadCoverFiles() {
  try {
    const r = await notex.attachableFiles({ kind: 'image', q: coverQuery.value || '', limit: 40 })
    coverFiles.value = r.list || []
  } catch (e) { coverFiles.value = [] }
}
async function setCover(fileId) {
  if (!current.value) return
  try {
    const r = await noteApi.update(current.value.id, { cover_file_id: fileId })
    current.value = { ...current.value, cover_file: r.cover_file, cover_thumb: r.cover_thumb }
    showCoverPicker.value = false
    loadTree()
    app.toastMsg(fileId ? '封面已更新' : '封面已清除', 'success')
  } catch (e) { app.toastMsg(e.message || '设置封面失败', 'error') }
}

// ---- F240 回看提醒 ----
const showReminder = ref(false)
const reminderInput = ref('')
function openReminder() {
  const raw = current.value?.remind_at || ''
  reminderInput.value = raw ? String(raw).slice(0, 16) : ''
  showReminder.value = true
}
async function saveReminder(val) {
  if (!current.value) return
  try {
    const r = await noteApi.update(current.value.id, { remind_at: val || null })
    current.value = { ...current.value, remind_at: r.remind_at, reminded_at: r.reminded_at }
    showReminder.value = false
    app.toastMsg(val ? '提醒已设置，到点会推送站内消息' : '提醒已清除', 'success')
  } catch (e) { app.toastMsg(e.message || '设置提醒失败', 'error') }
}

// ---- F243 我的模板 ----
const myTemplates = ref([])
async function loadMyTemplates() {
  try { myTemplates.value = (await notex.myTemplates()).list || [] } catch (e) { myTemplates.value = [] }
}
watch(showTemplates, (open) => { if (open) loadMyTemplates() })
async function saveAsTemplate() {
  if (!current.value) { app.toastMsg('请先打开一篇笔记', 'error'); return }
  try {
    await notex.createMyTemplate({
      title: current.value.title,
      content: current.value.content,
      icon: current.value.icon,
      tags: current.value.tag_names || [],
    })
    await loadMyTemplates()
    app.toastMsg('已把当前笔记存为模板 📋', 'success')
  } catch (e) { app.toastMsg(e.message || '保存模板失败', 'error') }
}
async function useMyTemplate(t) {
  try {
    const n = await notex.fromMyTemplate(t.id)
    showTemplates.value = false
    loadTree()
    openNote(n.id)
  } catch (e) { app.toastMsg(e.message || '创建失败', 'error') }
}
async function removeMyTemplate(t) {
  if (!confirm(`删除模板「${t.title}」？`)) return
  try {
    await notex.deleteMyTemplate(t.id)
    await loadMyTemplates()
  } catch (e) { app.toastMsg(e.message || '删除失败', 'error') }
}

// ---- F259 同名笔记提示 ----
const showDuplicate = ref(false)
const duplicateExisting = ref([])
const createdNoteId = ref(null)
function openExistingDuplicate(d) {
  showDuplicate.value = false
  openNote(d.id)
}
function openCreatedDuplicate() {
  showDuplicate.value = false
  if (createdNoteId.value) openNote(createdNoteId.value)
}

// ---- F256 合并标签 ----
async function mergeTag(src, toId) {
  if (!toId) return
  const target = Number(toId)
  const dst = tags.value.find((x) => x.id === target)
  if (!dst || !confirm(`把「${src.name}」合并到「${dst.name}」？源标签会被删除`)) return
  try {
    const r = await notex.mergeTags({ from_id: src.id, to_id: target })
    app.toastMsg(r.message || '已合并标签', 'success')
    loadTags()
    loadTree()
  } catch (e) { app.toastMsg(e.message || '合并失败', 'error') }
}

// ---- F257 双链悬停预览 ----
const wikiCard = ref(null)
const wikiPos = ref({ x: 0, y: 0 })
const wikiCache = new Map()
let wikiTimer = null
let wikiHoverTitle = ''
function escapeAttr(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
// 在已消毒的 HTML 上包 .wl（只注入自己拼好的 span，属性已转义）
function decorateWikilinks(html) {
  if (!html) return html
  return html.replace(/\[\[([^[\]\n]{1,120})\]\]/g, (m, raw) => {
    const parts = raw.replace(/&amp;/g, '&').split('|')
    const title = (parts[0] || '').trim()
    const label = (parts[1] || '').trim() || title
    const attr = escapeAttr(title)
    return `<span class="wl" role="button" title="${attr}" data-wiki="${attr}">${label}</span>`
  })
}
function onPreviewHover(e) {
  const el = e.target?.closest?.('.wl')
  if (!el) return
  const title = el.dataset?.wiki
  if (!title || title === wikiHoverTitle) return
  clearTimeout(wikiTimer)
  wikiHoverTitle = title
  const rect = el.getBoundingClientRect()
  // 300ms 延迟，避免扫过正文时频繁请求
  wikiTimer = setTimeout(() => showWikiPreview(title, rect), 300)
}
async function showWikiPreview(title, rect) {
  const key = `${current.value?.id || 0}|${title}`
  let data = wikiCache.get(key)
  if (!data) {
    try {
      data = await notex.previewByTitle(title, current.value?.id)
      wikiCache.set(key, data)
    } catch (e) {
      data = { title, message: '这篇笔记还没创建，写好后会自动建立双链' }
    }
  }
  if (wikiHoverTitle !== title) return
  const maxX = (window.innerWidth || 1024) - 280
  wikiPos.value = {
    x: Math.max(8, Math.min(rect.left, maxX)),
    y: Math.max(8, rect.bottom + 6),
  }
  wikiCard.value = data
}
function hideWikiPreview() {
  clearTimeout(wikiTimer)
  wikiTimer = null
  wikiHoverTitle = ''
  wikiCard.value = null
}
function openWikiCard() {
  if (!wikiCard.value?.id) return
  const id = wikiCard.value.id
  hideWikiPreview()
  openNote(id)
}

// ---- F250 粘贴 / 拖入图片：分片上传到「笔记图片」后按光标插入 ----
const IMAGE_FOLDER = '笔记图片'
const CHUNK_SIZE = 5 * 1024 * 1024
const uploadingImage = ref(false)
const uploadProgress = ref(0)
let imageFolderId = null
async function ensureImageFolder() {
  if (imageFolderId) return imageFolderId
  try {
    const r = await fileApi.folders(null)
    const hit = (r.list || []).find((f) => f.name === IMAGE_FOLDER)
    imageFolderId = hit ? hit.id : (await fileApi.createFolder({ name: IMAGE_FOLDER })).id
  } catch (e) { imageFolderId = null }
  return imageFolderId
}
function onContentPaste(e) {
  const items = Array.from(e.clipboardData?.items || [])
  const hit = items.find((it) => it.kind === 'file' && String(it.type).startsWith('image/'))
  if (!hit) return
  e.preventDefault()
  const file = hit.getAsFile()
  if (file) uploadImage(file)
}
function onContentDrop(e) {
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => String(f.type).startsWith('image/'))
  if (!files.length) return
  e.preventDefault()
  files.forEach((f) => uploadImage(f))
}
async function uploadImage(file) {
  if (!current.value) { app.toastMsg('请先打开一篇笔记', 'error'); return }
  uploadingImage.value = true
  uploadProgress.value = 0
  try {
    const folderId = await ensureImageFolder()
    let sha1 = ''
    try { sha1 = await sha1File(file) } catch (e) { sha1 = '' }
    const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))
    const init = await fileApi.uploadInit({
      filename: file.name, folder_id: folderId, file_size: file.size,
      chunk_size: CHUNK_SIZE, total_chunks: totalChunks, sha1,
    })
    let fm = init.file
    if (!init.sec_pass) {
      for (let i = 0; i < totalChunks; i++) {
        if (init.uploaded?.includes(i)) continue
        const fd = new FormData()
        fd.append('upload_id', init.upload_id)
        fd.append('index', i)
        fd.append('chunk', file.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE), `${file.name}.part${i}`)
        await fileApi.uploadChunk(fd)
        uploadProgress.value = Math.round(((i + 1) / totalChunks) * 100)
      }
      fm = (await fileApi.uploadComplete(init.upload_id)).file
    }
    if (!fm) throw new Error('上传结果缺少文件信息')
    insertIntoContent(`\n![${fm.name || '图片'}](${fm.url})\n`)
    app.toastMsg('图片已插入正文', 'success')
  } catch (e) {
    app.toastMsg(e.message || '图片上传失败', 'error')
  } finally {
    uploadingImage.value = false
    uploadProgress.value = 0
  }
}
// 统一在光标处插入 Markdown 片段
function insertIntoContent(md) {
  if (!current.value) return
  if (editorTab.value === 'preview') editorTab.value = 'write'
  const el = contentEl.value
  const val = el ? el.value : (current.value.content || '')
  const pos = el && typeof el.selectionStart === 'number' ? el.selectionStart : val.length
  const next = val.slice(0, pos) + md + val.slice(pos)
  setContent(next)
  if (el) {
    const caret = pos + md.length
    el.focus()
    el.setSelectionRange(caret, caret)
  }
}

// ---- F254 阅读位置（按笔记本地记忆，滚动节流保存） ----
const SCROLL_PREFIX = 'notes.scroll.'
let scrollTimer = null
function onPaneScroll(e) {
  const id = current.value?.id
  if (!id || !e?.target) return
  const top = e.target.scrollTop || 0
  clearTimeout(scrollTimer)
  scrollTimer = setTimeout(() => {
    try { localStorage.setItem(`${SCROLL_PREFIX}${id}`, String(Math.round(top))) } catch (err) { /* ignore */ }
  }, 300)
}
function restoreScroll(id) {
  let top = 0
  try { top = Number(localStorage.getItem(`${SCROLL_PREFIX}${id}`) || 0) } catch (e) { top = 0 }
  if (!top) return
  nextTick(() => {
    if (current.value?.id !== id) return
    const el = editorTab.value === 'preview' ? previewRef.value : contentEl.value
    if (el) el.scrollTop = top
  })
}
function clearScroll(id) {
  try { localStorage.removeItem(`${SCROLL_PREFIX}${id}`) } catch (e) { /* ignore */ }
}

// ---- F260 置顶拖拽排序 ----
let pinDragId = null
function onPinDragStart(id) { pinDragId = id }
async function onPinDrop(targetId) {
  const from = pinDragId
  pinDragId = null
  if (!from || from === targetId) return
  const pinned = shownRows.value.filter((r) => r.n.is_pinned).map((r) => r.n.id)
  if (!pinned.includes(from) || !pinned.includes(targetId)) {
    app.toastMsg('只有置顶笔记之间可以拖拽排序', 'info')
    return
  }
  const order = pinned.filter((id) => id !== from)
  const idx = order.indexOf(targetId)
  order.splice(idx < 0 ? order.length : idx, 0, from)
  try {
    await notex.pinOrder(order)
    app.toastMsg('置顶顺序已更新', 'success')
    loadTree()
  } catch (e) { app.toastMsg(e.message || '排序失败', 'error') }
}

// ---- F255 打印预览 ----
function printNote() {
  if (!current.value) return
  const prev = editorTab.value
  editorTab.value = 'preview'
  nextTick(() => {
    const restore = () => { editorTab.value = prev }
    window.addEventListener('afterprint', restore, { once: true })
    try { window.print() } finally { setTimeout(restore, 500) }
  })
}

// #23 快捷键：Ctrl+/ 打开面板，Ctrl+E 切换预览，#145 Ctrl+S 立即保存
function onKeydown(e) {
  // F252：Esc 退出专注模式（其它弹窗由各自组件处理）
  if (e.key === 'Escape' && focusMode.value) {
    toggleFocus()
    return
  }
  const mod = e.ctrlKey || e.metaKey
  if (!mod) return
  const key = (e.key || '').toLowerCase()
  if (key === '/') { e.preventDefault(); showShortcuts.value = true; return }
  if (key === 'e' && current.value) {
    e.preventDefault(); editorTab.value = editorTab.value === 'write' ? 'preview' : 'write'
    return
  }
  if (key === 's' && current.value) {
    // 始终拦截：否则浏览器会弹出「另存为网页」
    e.preventDefault()
    if (collabMode.value) { app.toastMsg('协作模式已实时同步，无需保存', 'info'); return }
    flushSave()
      .then(() => app.toastMsg('已保存', 'success'))
      .catch((err) => app.toastMsg(err?.message || '保存失败', 'error'))
  }
}

onMounted(() => {
  loadTree(); loadTags(); loadTemplates(); ensureAiStatus(); loadDangling()
  loadFolders(); loadLocalWords(); loadTodos()
  applyFocusClass()
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  flushSave()
  clearTimeout(statTimer)
  clearTimeout(scrollTimer)
  if (collab) collab.destroy()
  window.removeEventListener('keydown', onKeydown)
  try { document.body.classList.remove('note-focus') } catch (e) { /* ignore */ }
})
</script>

<style scoped>
/* F253 列表密度：紧凑压缩行高，舒适保留留白 */
.density-compact .note-row { padding-top: 1px; padding-bottom: 1px; font-size: 12px; }
.density-compact .note-row img { height: 12px; width: 18px; }
.density-comfortable .note-row { padding-top: 4px; padding-bottom: 4px; }

/* F252 专注模式：隐藏侧栏后正文居中收窄 */
.focus-mode { justify-content: center; }
.editor-focus { width: 100%; max-width: 960px; margin: 0 auto; }
.focus-mode .editor-focus textarea,
.focus-mode .editor-focus .markdown-body { min-height: 70vh; }
@media screen {
  :global(body.note-focus #app > div > aside),
  :global(body.note-focus #app > div > div > header) { display: none !important; }
}

/* F577 阅读模式：字号/行距/段宽由 F241 的 style 绑定控制 */
.reading-mode textarea { letter-spacing: 0.02em; }

/* F257 双链悬停预览的锚点样式 */
:deep(.wl) { color: #0284c7; border-bottom: 1px dashed #7dd3fc; cursor: help; }

/* F255 打印：只保留正文预览，白底，外链展开完整 URL */
@media print {
  :global(body) { background: #fff !important; }
  :global(body *) { visibility: hidden; }
  .print-body, .print-body * { visibility: visible; }
  .no-print { display: none !important; }
  .print-body {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: auto !important;
    max-height: none !important;
    max-width: none !important;
    overflow: visible !important;
    padding: 0 !important;
    background: #fff !important;
  }
  .print-body a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 11px; color: #555; }
  .print-body img { max-width: 100%; }
}
</style>
