<template>
  <div class="flex gap-4">
    <!-- 目录树 -->
    <div class="card w-64 shrink-0 self-start p-3">
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
        <div v-if="activeTag" class="mb-1 rounded-control bg-brand-50/50 px-2 py-1.5 text-[12px] text-brand-700">
          标签「{{ activeTag }}」<button @click="activeTag = null">×</button>
        </div>
        <div v-if="activeFolder" class="mb-1 rounded-control bg-brand-50/50 px-2 py-1.5 text-[12px] text-brand-700">
          📁 {{ folderName(activeFolder) }}<button @click="filterFolder(null)"> ×</button>
        </div>
        <div v-for="n in shownList" :key="n.id" class="flex cursor-pointer items-center justify-between rounded-control px-2 py-1.5 hover:bg-ink-50" :class="activeNote === n.id ? 'bg-brand-50 text-brand-700' : ''" @click="openNote(n.id)">
          <span class="min-w-0 flex-1 truncate">
            <span v-if="n.color" class="mr-1 inline-block h-2 w-2 shrink-0 rounded-full align-middle" :style="{ background: colorHex(n.color) }"></span>{{ n.is_pinned ? '📌' : n.is_public ? '🌐' : n.is_favorite ? '★' : n.is_archived ? '📦' : '📄' }} {{ n.title }}
          </span>
        </div>
        <div v-if="!shownList.length" class="py-6 text-center text-[12px] text-ink-400">没有匹配的笔记</div>
      </div>

      <!-- #24 标签云 -->
      <div v-if="sideTab !== 'trash'" class="mt-3 border-t border-ink-100 pt-2">
        <div class="mb-1 flex items-center justify-between px-1">
          <span class="text-[11px] text-ink-400">标签云</span>
          <button class="text-[11px] text-brand-600" @click="showTagMgr = true">管理</button>
        </div>
        <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-1">
          <span v-for="t in cloudTags" :key="t.id" class="cursor-pointer text-brand-600 hover:underline"
                :style="{ fontSize: (11 + (t.weight || 0) * 6) + 'px', opacity: 0.55 + (t.weight || 0) * 0.45 }"
                @click="filterByTag(t.name)">#{{ t.name }}</span>
        </div>
      </div>

      <div class="mt-3 space-y-0.5 border-t border-ink-100 pt-2">
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showTemplates = true">📋 从模板新建</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showImport = true">📥 批量导入 MD</button>
        <button v-if="current" class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="insertTemplatePrompt">📥 插入模板到正文</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showStats = true; loadStats()">📊 写作统计</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="exportSelected">⬇ 导出所选 ZIP</button>
        <a :href="noteApi.exportAllUrl()" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">⬇ 导出全部 ZIP</a>
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
    <div class="min-w-0 flex-1">
      <div v-if="current" class="card overflow-hidden" :class="readingMode ? 'reading-mode' : ''">
        <div class="flex flex-wrap items-center gap-2 border-b border-ink-100 px-4 py-2">
          <input type="checkbox" :checked="exportIds.has(current.id)" @change="toggleExportPick(current.id)" title="勾选导出" />
          <input v-model="current.title" class="min-w-[120px] flex-1 border-none bg-transparent text-[16px] font-semibold focus:outline-none" placeholder="笔记标题" />
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
          <button class="btn-ghost px-2 text-[12px]" @click="openMerge">🔀 合并</button>
          <button class="btn-ghost px-2 text-[12px]" @click="openSplit">✂ 拆分</button>
          <button class="btn-ghost px-2 text-[12px]" @click="openCitation">🔖 引用</button>
          <button v-if="selectedWord" class="btn-ghost px-2 text-[12px] text-brand-600" title="存入学习区生词本" @click="saveWord">📚 存生词「{{ selectedWord }}」</button>
          <button class="btn-ghost px-2 text-[12px]" @click="loadOutline">大纲</button>
          <button class="btn-ghost px-2 text-[12px]" @click="aiOutline">✨AI大纲</button>
          <button class="btn-ghost px-2 text-[12px]" @click="loadFlashcards">🃏回顾</button>
          <button class="btn-ghost px-2 text-[12px]" :class="rightPanel ? 'text-brand-600' : ''" @click="rightPanel = !rightPanel">
            🔗 关联<span v-if="backlinkCount" class="ml-0.5 text-brand-600">{{ backlinkCount }}</span>
          </button>
          <button class="btn-ghost px-2 text-[12px]" :class="collabMode ? 'text-emerald-600' : ''" @click="toggleCollab">👥 协同</button>
          <button class="btn-ghost px-2 text-[12px]" @click="duplicate">复制</button>
          <a :href="noteApi.exportUrl(current.id)" class="btn-ghost px-2 text-[12px]">导出</a>
          <button class="btn-ghost px-2 text-[12px]" @click="showVersions = true; loadVersions()">🕘</button>
          <button class="btn-ghost px-2 text-[12px]" @click="showShortcuts = true">？</button>
          <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="deleteNote">🗑</button>
        </div>
        <div class="flex border-b border-ink-100">
          <button class="flex-1 border-b-2 px-3 py-2 text-[13px]" :class="editorTab === 'write' ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'" @click="editorTab = 'write'">编辑</button>
          <button class="flex-1 border-b-2 px-3 py-2 text-[13px]" :class="editorTab === 'preview' ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'" @click="editorTab = 'preview'">预览</button>
        </div>
        <div class="flex">
          <div class="relative flex-1">
            <textarea v-show="editorTab !== 'preview'"
                      :value="collabMode ? collabText : current.content"
                      class="h-[52vh] w-full resize-none bg-ink-50/50 p-4 font-mono text-[13px] leading-relaxed focus:outline-none"
                      :style="readingMode ? { fontSize: '15px', lineHeight: '1.9' } : {}"
                      placeholder="支持 Markdown…  输入 [[ 可引用其他笔记建立双链"
                      @input="onContentInput"
                      @keyup="editorKeyup($event.target)"
                      @click="editorKeyup($event.target)"
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
          </div>
          <!-- #18 字数/结构统计侧栏 -->
          <div class="hidden w-40 shrink-0 border-l border-ink-100 bg-ink-50/30 p-3 text-[11px] text-ink-500 lg:block">
            <div class="mb-1 font-medium text-ink-600">结构统计</div>
            <div>字数：{{ statWords }} 字</div>
            <div>段落：{{ statParas }} 段</div>
            <div>标题：{{ statHeadings }} 个</div>
            <div>列表项：{{ statLists }} 条</div>
            <div>预计阅读：{{ statReadMin }} 分钟</div>
          </div>
        </div>
        <div ref="previewRef" v-show="editorTab !== 'write'" class="markdown-body h-[52vh] overflow-y-auto bg-white p-4"
             :style="readingMode ? { fontSize: '15.5px', lineHeight: '1.95', maxWidth: '760px', margin: '0 auto' } : {}"
             v-html="rendered" @mouseup="trackSelection(null)"></div>
        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
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

    <!-- 右侧：关联（双链）/ AI 面板 -->
    <aside v-if="current && rightPanel" class="w-72 shrink-0">
      <div class="card p-3">
        <div class="mb-2 flex gap-1 text-[12px]">
          <button class="flex-1 rounded-control px-2 py-1"
                  :class="rightTab === 'links' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                  @click="rightTab = 'links'">反链 {{ backlinkCount }}</button>
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

    <!-- 模板 -->
    <Modal :show="showTemplates" title="从模板新建" @close="showTemplates = false">
      <div class="grid grid-cols-2 gap-2">
        <button v-for="t in templates" :key="t.key" class="rounded-card border border-ink-100 p-3 text-left hover:border-brand-400" @click="useTemplate(t.key)">
          <div class="text-[13px] font-medium text-ink-800">{{ t.title }}</div>
        </button>
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
    <Modal :show="showTagMgr" title="标签管理" @close="showTagMgr = false">
      <div class="space-y-2">
        <div v-for="t in tags" :key="t.id" class="flex items-center gap-2">
          <input v-model="t.name" class="input flex-1" @change="saveTag(t)" />
          <input v-model="t.color" type="color" class="h-8 w-10 rounded-control border border-ink-200" @change="saveTag(t)" />
          <button class="btn-danger px-2 text-[12px]" @click="delTag(t)">删除</button>
        </div>
        <div class="flex gap-2">
          <input v-model="newTagName" class="input flex-1" placeholder="新标签名" @keyup.enter="addNewTag" />
          <button class="btn-primary" @click="addNewTag">新增</button>
        </div>
      </div>
    </Modal>

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

    <!-- #23 快捷键面板 -->
    <Modal :show="showShortcuts" title="编辑器快捷键" width="480px" @close="showShortcuts = false">
      <div class="space-y-1.5 text-[13px]">
        <div class="flex justify-between"><span>保存（自动防抖已开启）</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+S</kbd></div>
        <div class="flex justify-between"><span>加粗 **…**</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+B</kbd></div>
        <div class="flex justify-between"><span>斜体 *…*</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+I</kbd></div>
        <div class="flex justify-between"><span>插入双链</span><kbd class="rounded bg-ink-100 px-1.5">[[</kbd></div>
        <div class="flex justify-between"><span>打开快捷键面板</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+/</kbd></div>
        <div class="flex justify-between"><span>切换编辑/预览</span><kbd class="rounded bg-ink-100 px-1.5">Ctrl+E</kbd></div>
      </div>
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { aiApi, noteApi } from '../../api'
import { notex } from '../../api/notex'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import { NoteCollab } from '../../utils/collab'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const tree = ref([])
const tags = ref([])
const cloudTags = ref([])
const current = ref(null)
const activeNote = ref(null)
const activeTag = ref(null)
const tagNotes = ref([])
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
let saveTimer = null

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

// #18 本地结构统计
const statWords = computed(() => (current.value?.content || '').replace(/\s/g, '').length)
const statParas = computed(() => (current.value?.content || '').split(/\n\s*\n/).filter((s) => s.trim()).length)
const statHeadings = computed(() => ((current.value?.content || '').match(/^#{1,6}\s/gm) || []).length)
const statLists = computed(() => ((current.value?.content || '').match(/^\s*([-*+]|\d+\.)\s/gm) || []).length)
const statReadMin = computed(() => Math.max(1, Math.round(statWords.value / 300)))

const shownList = computed(() => (activeTag.value ? tagNotes.value : flattenTree(tree.value)))
function flattenTree(nodes) {
  const out = []
  for (const n of nodes) { out.push(n); if (n.children) out.push(...flattenTree(n.children)) }
  return out
}
const rendered = computed(() => {
  try { return marked.parse(current.value?.content || '') } catch (e) { return current.value?.content || '' }
})

async function loadTree() {
  const r = await noteApi.tree()
  tree.value = r.tree || []
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
  if (collabMode.value) stopCollab()
  current.value = await noteApi.detail(id)
  activeNote.value = id
  activeTag.value = null
  selectedWord.value = ''
  backlinks.value = current.value.backlinks || []
  outgoingLinks.value = current.value.outgoing_links || []
  aiSummary.value = current.value.ai_summary || ''
  aiPoints.value = []
  aiQa.value = []
  linkSuggest.value = []
  resetAiInfo()
  if (rightPanel.value) loadDangling()
}
async function createNote() {
  const n = await noteApi.create({ title: '未命名笔记', content: '' })
  loadTree(); openNote(n.id)
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
function autoSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(async () => {
    if (!current.value || collabMode.value) return
    saving.value = true
    current.value = await noteApi.update(current.value.id, { title: current.value.title, content: current.value.content })
    loadTree()
    setTimeout(() => (saving.value = false), 600)
  }, 800)
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
  if (collabMode.value && collab) {
    collab.applyLocalText(e.target.value)
    return
  }
  autoSave()
  detectLinkQuery(e.target)
}
function detectLinkQuery(el) {
  if (!el || collabMode.value) return
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
  const val = current.value.content || ''
  current.value.content = `${val.slice(0, linkQuery.start)}[[${title}]]${val.slice(linkQuery.end)}`
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
function toggleCollab() {
  if (collabMode.value) { stopCollab(); return }
  if (!current.value) return
  collabMode.value = true
  collabStatus.value = 'connecting'
  collabText.value = current.value.content || ''
  collab = new NoteCollab(current.value.id, {
    initialContent: current.value.content || '',
    onText: (t) => { collabText.value = t; current.value.content = t },
    onStatus: (s) => { collabStatus.value = s },
    onPresence: (list) => { collabPeers.value = (list || []).map((p) => p.name) },
  })
  collab.connect()
  app.toastMsg('已开启协同编辑，内容将实时同步', 'success')
}
function stopCollab() {
  if (collab) collab.destroy()
  collab = null
  collabMode.value = false
  collabStatus.value = 'off'
  collabPeers.value = []
  if (current.value) noteApi.detail(current.value.id).then((r) => { current.value = r })
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
async function filterByTag(name) {
  if (activeTag.value === name) { activeTag.value = null; tagNotes.value = []; return }
  activeTag.value = name
  activeFolder.value = null
  tagNotes.value = (await noteApi.list({ tag: name, all: 1, page_size: 100 })).list || []
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
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'notes_selected.zip'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { app.toastMsg(e.message || '导出失败', 'error') }
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
    try {
      const r = await noteApi.list({ pinned: 1, all: 1, page_size: 200 })
      tree.value = (r.list || []).map((n) => ({ ...n, children: [] }))
    } catch (e) { tree.value = [] }
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
    if (current.value && current.value.id === t.note_id) openNote(t.note_id)
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
function copyText(text) {
  navigator.clipboard?.writeText(text)
  app.toastMsg('已复制引用格式', 'success')
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
  activeTag.value = null
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

// #23 快捷键：Ctrl+/ 打开面板，Ctrl+E 切换预览
function onKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === '/') { e.preventDefault(); showShortcuts.value = true }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'e' && current.value) {
    e.preventDefault(); editorTab.value = editorTab.value === 'write' ? 'preview' : 'write'
  }
}

onMounted(() => {
  loadTree(); loadTags(); loadTemplates(); ensureAiStatus(); loadDangling()
  loadFolders(); loadLocalWords(); loadTodos()
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => { if (collab) collab.destroy(); window.removeEventListener('keydown', onKeydown) })
</script>

<style scoped>
/* F577 阅读模式（排版态）：更舒适的字号与行距、正文限宽居中 */
.reading-mode textarea {
  font-size: 15.5px !important;
  line-height: 2 !important;
  letter-spacing: 0.02em;
}
.reading-mode .markdown-body {
  font-size: 15.5px;
  line-height: 2;
  max-width: 46rem;
  margin: 0 auto;
}
</style>
