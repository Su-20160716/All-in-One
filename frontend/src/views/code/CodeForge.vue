<template>
  <div class="flex h-[calc(100vh-56px)] flex-col overflow-hidden bg-slate-50">
    <!-- ============ 顶栏 ============ -->
    <div class="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 py-2">
      <div class="flex items-center gap-2">
        <span class="text-[15px]">🧑‍💻</span>
        <span class="text-[13px] font-semibold text-ink-900">代码工坊</span>
        <span class="tag-brand">v6</span>
      </div>

      <div class="mx-1 h-5 w-px bg-slate-200"></div>

      <!-- 工作区切换 -->
      <select v-model="activeWsId" class="input h-7 py-0 text-[12px]" style="width: 190px" @change="onSwitchWorkspace">
        <option :value="null">— 选择工作区 —</option>
        <option v-for="w in workspaces" :key="w.id" :value="w.id">
          {{ w.icon }} {{ w.name }}（{{ w.file_count }}）
        </option>
      </select>

      <button class="btn-outline h-7 px-2 text-[12px]" @click="showWsModal = true">＋ 新建</button>
      <button v-if="activeWs" class="btn-ghost h-7 px-2 text-[12px]" @click="openWsSettings">⚙ 设置</button>
      <button v-if="activeWs" class="btn-ghost h-7 px-2 text-[12px]" @click="doCloneWs">⧉ 克隆</button>
      <button v-if="activeWs" class="btn-ghost h-7 px-2 text-[12px]" @click="doExportZip">⬇ 导出 zip</button>

      <div class="flex-1"></div>

      <!-- 运行按钮组 -->
      <span v-if="runtimesForLang" class="text-[11px]" :class="runtimesForLang.available ? 'text-emerald-600' : 'text-amber-600'">
        {{ runtimesForLang.available ? '● ' + (runtimesForLang.version || '就绪') : '○ ' + runtimesForLang.available_hint }}
      </span>
      <button
        class="btn-primary h-7 gap-1 px-3 text-[12px]"
        :disabled="!canRun || running"
        :title="canRun ? 'Ctrl+Enter' : '缺少运行时或未选文件'"
        @click="doRun"
      >
        <span v-if="running" class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>
        {{ running ? '运行中…' : '▶ 运行' }}
      </button>
      <button class="btn-outline h-7 px-2 text-[12px]" :disabled="running" @click="doJudge">⚖ 判题</button>

      <div class="mx-1 h-5 w-px bg-slate-200"></div>

      <button class="btn-ghost h-7 px-2 text-[12px]" :title="theme === 'dark' ? '切浅色' : '切深色'" @click="toggleTheme">
        {{ theme === 'dark' ? '☀' : '🌙' }}
      </button>
      <button class="btn-ghost h-7 px-2 text-[12px]" @click="drawer = drawer === 'ai' ? '' : 'ai'">🤖 AI</button>
      <button class="btn-ghost h-7 px-2 text-[12px]" @click="drawer = drawer === 'analysis' ? '' : 'analysis'">📊 分析</button>
      <button class="btn-ghost h-7 px-2 text-[12px]" @click="openTodos">📌 TODO</button>
      <button class="btn-ghost h-7 px-2 text-[12px]" @click="openInsights">📈 洞察</button>
      <button class="btn-ghost h-7 px-2 text-[12px]" @click="drawer = drawer === 'history' ? '' : 'history'">🕘 历史</button>
      <button
        v-if="dailyInfo"
        class="btn-ghost h-7 px-2 text-[12px]"
        :title="dailyInfo.solved ? `今日一题《${dailyInfo.title}》已完成 ✓` : `每日一题提醒：《${dailyInfo.title}》还没做`"
        @click="goDaily"
      >
        📅 每日一题
        <span v-if="!dailyInfo.solved" class="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-rose-500 align-middle"></span>
      </button>
      <button
        class="btn-ghost h-7 px-2 text-[12px]"
        title="代码学习中心"
        @click="router.push('/code/learn')"
      >🏅 学习</button>
      <button class="btn-ghost h-7 px-2 text-[12px]" @click="showHelp = true">❔</button>
    </div>

    <div class="flex min-h-0 flex-1">
      <!-- ============ 左：文件树 ============ -->
      <aside class="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div class="flex items-center gap-1 border-b border-slate-100 px-2 py-1.5">
          <input v-model="fileQuery" class="input h-6 flex-1 py-0 text-[11px]" placeholder="筛选文件…" />
          <button class="btn-ghost h-6 w-6 px-0 text-[13px]" title="新建文件" @click="showFileModal = true">＋</button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto py-1">
          <template v-if="activeWs">
            <TreeNode
              v-for="node in filteredTree"
              :key="node.path"
              :node="node"
              :active-id="activeFileId"
              :depth="0"
              @open="openFile"
              @ctx="onTreeCtx"
            />
            <div v-if="!filteredTree.length" class="px-3 py-6 text-center text-[11px] text-ink-400">
              {{ fileQuery ? '没有匹配的文件' : '工作区还是空的' }}
            </div>
          </template>
          <div v-else class="px-3 py-6 text-center text-[11px] text-ink-400">
            先创建或选择一个工作区
          </div>
        </div>

        <!-- F674 最近打开：一键重开 -->
        <div v-if="recentFiles.length" class="border-t border-slate-100 p-1.5">
          <div class="mb-0.5 flex items-center gap-1 px-1 text-[10px] text-ink-400">
            <span>最近打开</span>
            <button class="ml-auto hover:text-ink-600" title="清空记录" @click="clearRecent">清空</button>
          </div>
          <button
            v-for="r in recentFiles.slice(0, 6)"
            :key="r.id"
            class="block w-full truncate rounded px-1.5 py-[3px] text-left text-[11px] text-ink-600 hover:bg-slate-100"
            :title="r.path"
            @click="openFile({ id: r.id })"
          >
            <span class="text-ink-300">›</span> {{ r.name }}
          </button>
        </div>

        <!-- 片段库入口 -->
        <div class="border-t border-slate-100 p-1.5">
          <button class="btn-ghost h-6 w-full justify-start gap-1 px-2 text-[11px]" @click="showSnippetPanel = true">
            🧩 片段库
            <span class="ml-auto text-ink-400">{{ snippetCount }}</span>
          </button>
        </div>
      </aside>

      <!-- ============ 中：编辑器 + 输出 ============ -->
      <main class="flex min-w-0 flex-1 flex-col">
        <!-- 标签栏 -->
        <div class="flex shrink-0 items-center gap-0.5 overflow-x-auto border-b border-slate-200 bg-slate-50 px-1 py-1">
          <div
            v-for="t in tabs"
            :key="t.id"
            class="group flex cursor-pointer items-center gap-1.5 rounded-t px-2.5 py-1 text-[12px] transition"
            :class="t.id === activeFileId
              ? 'bg-white font-medium text-brand-700 shadow-sm'
              : 'text-ink-600 hover:bg-white/70'"
            @click="openFile({ id: t.id })"
          >
            <span v-if="t.dirty" class="h-1.5 w-1.5 rounded-full bg-amber-500" :title="'未保存'"></span>
            <span>{{ t.name }}</span>
            <span
              class="rounded px-1 text-[13px] leading-none text-ink-300 opacity-0 transition group-hover:opacity-100"
              :class="{ 'opacity-100': t.id === activeFileId }"
              @click.stop="closeTab(t)"
            >×</span>
          </div>
          <div v-if="!tabs.length" class="px-2 py-1 text-[11px] text-ink-400">未打开任何文件</div>
          <div class="flex-1"></div>
          <span v-if="activeFile" class="whitespace-nowrap px-2 text-[11px] text-ink-400">
            {{ cursorInfo.line }}:{{ cursorInfo.col }}
            <span class="mx-1">·</span>
            {{ editorLines }} 行
            <span class="mx-1">·</span>
            {{ activeFile.language }}
          </span>
        </div>

        <!-- 工具栏 -->
        <div v-if="activeFile" class="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-100 bg-white px-2 py-1">
          <button class="btn-ghost h-6 px-1.5 text-[11px]" title="保存 (Ctrl+S)" @click="saveCurrent">
            💾 保存
          </button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" title="查找替换 (Ctrl+F)" @click="editorRef?.openSearch()">🔍 查找</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" title="折叠全部" @click="editorRef?.foldAll(true)">⊟ 折叠</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" title="展开全部" @click="editorRef?.foldAll(false)">⊞ 展开</button>

          <div class="mx-0.5 h-4 w-px bg-slate-200"></div>

          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="toggleWrap" :class="{ 'text-brand-600': lineWrapping }">↩ 换行</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="showInvisibles = !showInvisibles" :class="{ 'text-brand-600': showInvisibles }">¶ 空白符</button>
          <label class="flex items-center gap-1 text-[11px] text-ink-500">
            字号
            <input v-model.number="fontSize" type="range" min="11" max="20" class="h-1 w-16" />
            <span class="w-5 text-ink-700">{{ fontSize }}</span>
          </label>
          <label class="flex items-center gap-1 text-[11px] text-ink-500">
            缩进
            <select v-model.number="tabSize" class="input h-5 py-0 text-[11px]" style="width: 46px">
              <option :value="2">2</option>
              <option :value="4">4</option>
              <option :value="8">8</option>
            </select>
          </label>

          <!-- F670 行高 / 字距：滑杆 + localStorage + Compartment 重配 -->
          <div class="mx-0.5 h-4 w-px bg-slate-200"></div>
          <label class="flex items-center gap-1 text-[11px] text-ink-500">
            行高
            <input v-model.number="lineHeight" type="range" min="1.2" max="2.4" step="0.05" class="h-1 w-16" />
            <span class="w-7 text-ink-700">{{ lineHeight.toFixed(2) }}</span>
          </label>
          <label class="flex items-center gap-1 text-[11px] text-ink-500">
            字距
            <input v-model.number="letterSpacing" type="range" min="-0.5" max="2" step="0.1" class="h-1 w-14" />
            <span class="w-7 text-ink-700">{{ letterSpacing.toFixed(1) }}</span>
          </label>

          <div class="mx-0.5 h-4 w-px bg-slate-200"></div>

          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="doSnapshot">📌 快照</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="graphDrawer = !graphDrawer" :class="{ 'text-brand-600': graphDrawer }">◲ 版本</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="commentDrawer = !commentDrawer" :class="{ 'text-brand-600': commentDrawer }">
            💬 评论 <span v-if="unresolvedComments" class="tag">{{ unresolvedComments }}</span>
          </button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="doShare">🔗 分享</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="doSecretScan" :title="secretFindings.length ? `发现 ${secretFindings.length} 处` : '涉密扫描'">
            🛡 扫描
            <span v-if="secretFindings.length" class="ml-0.5 text-rose-600">{{ secretFindings.length }}</span>
          </button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="doComplexity">⏱ 复杂度</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="openTemplateMenu" title="插入常用代码模板">📋 模板</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="doAiReview" :disabled="reviewing" title="AI 代码评审">🤖 评审</button>

          <div class="mx-0.5 h-4 w-px bg-slate-200"></div>

          <!-- F676 运行参数预设 / F677 统计卡 / F675 括号提示 / F673 行书签 -->
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="openRunCfg" title="按语言保存 stdin / 参数 / 超时">⚙ 运行参数</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" @click="openStatsCard" title="行数 / 注释率 / 函数数">📐 统计</button>
          <button
            class="btn-ghost h-6 px-1.5 text-[11px]"
            :class="{ 'text-amber-600 font-medium': braceIssues.length }"
            title="括号 / 引号未闭合行提示"
            @click="checkBrackets(true)"
          >{{ braceIssues.length ? `) ${braceIssues.length}` : '括号 ✓' }}</button>
          <button class="btn-ghost h-6 px-1.5 text-[11px]" title="行书签（点行号左侧圆点切换）" @click="openBookmarks">
            🔖{{ currentBookmarks.length ? ` ${currentBookmarks.length}` : ' 书签' }}
          </button>

          <div class="flex-1"></div>
          <span v-if="saveState" class="text-[11px]" :class="saveState === 'saved' ? 'text-emerald-600' : 'text-amber-600'">
            {{ saveState === 'saved' ? '已保存' : '保存中…' }}
          </span>
        </div>

        <!-- 编辑器 -->
        <div class="min-h-0 flex-1 bg-white">
          <CodeEditor
            v-if="activeFile"
            ref="editorRef"
            v-model="code"
            :language="activeFile.language"
            :theme="theme"
            :font-size="fontSize"
            :tab-size="tabSize"
            :line-wrapping="lineWrapping"
            :show-invisibles="showInvisibles"
            :key="activeFile.id + '-' + theme"
            @change="onCodeChange"
            @cursor="(c) => (cursorInfo = c)"
            @ready="onEditorReady"
          />
          <div v-else class="grid h-full place-items-center text-[12px] text-ink-400">
            <div class="text-center">
              <div class="mb-2 text-3xl">📄</div>
              <div>从左侧选择或新建一个文件开始</div>
            </div>
          </div>
        </div>

        <!-- 输出面板 -->
        <div v-if="output.open" class="flex shrink-0 flex-col border-t border-slate-200 bg-white" :style="{ height: outputHeight + 'px' }">
          <div class="flex items-center gap-1 border-b border-slate-100 px-2 py-1">
            <button
              v-for="tab in outputTabs"
              :key="tab.key"
              class="rounded px-2 py-0.5 text-[11px] transition"
              :class="output.tab === tab.key ? 'bg-slate-900 text-white' : 'text-ink-500 hover:bg-slate-100'"
              @click="output.tab = tab.key"
            >
              {{ tab.label }}
              <span v-if="tab.count !== undefined" class="ml-1 opacity-70">{{ tab.count }}</span>
            </button>
            <div class="flex-1"></div>
            <span v-if="output.meta" class="mr-1 text-[11px]" :class="statusColor(output.status)">
              {{ output.meta }}
            </span>
            <template v-if="output.tab === 'stdout' || output.tab === 'stderr'">
              <button class="btn-ghost h-5 px-1 text-[11px]" title="在输出中查找（高亮 + 上/下跳转）" @click="toggleOutFind">🔎</button>
              <button
                class="btn-ghost h-5 px-1 text-[11px]"
                :class="{ 'text-brand-600': consoleMode }"
                title="控制台风格（等宽 + ANSI 颜色）"
                @click="toggleConsole"
              >🎨</button>
            </template>
            <button class="btn-ghost h-5 px-1 text-[11px]" title="复制输出" @click="copyOutput">⧉</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" title="下载输出" @click="downloadOutput">⬇</button>
            <button class="btn-ghost h-5 px-1.5 text-[11px]" @click="output.open = false">×</button>
          </div>

          <!-- F671 输出内查找：高亮 + 上/下跳转 -->
          <div
            v-if="outFind.open && (output.tab === 'stdout' || output.tab === 'stderr')"
            class="flex items-center gap-1 border-b border-slate-100 bg-slate-50 px-2 py-1"
          >
            <input
              ref="outFindInput"
              v-model="outFind.q"
              class="input h-5 flex-1 py-0 text-[11px]"
              placeholder="在输出中查找…（Enter 下一个）"
              @keydown.enter.prevent="moveFind(1)"
              @keydown.shift.enter.prevent="moveFind(-1)"
              @keydown.esc="outFind.open = false"
            />
            <span class="whitespace-nowrap text-[11px] text-ink-500">
              {{ outMatchCount ? `${outFind.idx + 1} / ${outMatchCount}` : (outFind.q ? '无匹配' : '') }}
            </span>
            <button class="btn-ghost h-5 px-1 text-[11px]" :disabled="!outMatchCount" @click="moveFind(-1)">▲</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" :disabled="!outMatchCount" @click="moveFind(1)">▼</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="outFind.open = false">×</button>
          </div>

          <div class="min-h-0 flex-1 overflow-auto">
            <!-- stdout（F678 控制台风格 + F671 查找高亮） -->
            <pre
              v-if="output.tab === 'stdout'"
              class="whitespace-pre-wrap break-words p-3 font-mono text-[12px] leading-relaxed"
              :class="consoleMode ? 'min-h-full bg-slate-900 text-slate-100' : 'text-ink-800'"
            ><span
              v-for="(seg, i) in outSegs" :key="i"
              :style="seg.style"
            >{{ seg.text }}</span><span v-if="!output.stdout">（无标准输出）</span></pre>

            <!-- stderr -->
            <pre
              v-else-if="output.tab === 'stderr'"
              class="whitespace-pre-wrap break-words p-3 font-mono text-[12px] leading-relaxed"
              :class="consoleMode ? 'min-h-full bg-slate-950 text-rose-100' : 'text-rose-600'"
            ><span
              v-for="(seg, i) in outSegs" :key="i"
              :style="seg.style"
            >{{ seg.text }}</span><span v-if="!output.stderr">（无错误输出）</span></pre>

            <!-- 诊断 -->
            <div v-else-if="output.tab === 'diag'" class="p-2">
              <div v-if="!diagnostics.length" class="p-3 text-[12px] text-ink-400">未识别到结构化诊断</div>
              <div
                v-for="(d, i) in diagnostics"
                :key="i"
                class="mb-1 cursor-pointer rounded border border-slate-200 p-2 text-[12px] hover:border-brand-400 hover:bg-brand-50/40"
                @click="d.line && editorRef?.goToLine(d.line)"
              >
                <div class="flex items-center gap-2">
                  <span class="tag" :class="d.severity === 'error' ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'">
                    {{ d.severity || 'info' }}
                  </span>
                  <span class="font-mono font-medium text-ink-900">{{ d.type }}</span>
                  <span v-if="d.line" class="text-[11px] text-ink-500">第 {{ d.line }} 行<template v-if="d.column">:{{ d.column }}</template></span>
                </div>
                <div class="mt-1 text-ink-700">{{ d.message }}</div>
                <div v-if="d.frames && d.frames.length" class="mt-1 space-y-0.5">
                  <div v-for="(fr, fi) in d.frames.slice(-6)" :key="fi" class="font-mono text-[11px] text-ink-400">
                    ↳ {{ fr.file }}:{{ fr.line }} <span v-if="fr.function">in {{ fr.function }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 结构化建议 -->
            <div v-else-if="output.tab === 'hint'" class="p-3">
              <div v-if="hints.length" class="space-y-2">
                <div v-for="(h, i) in hints" :key="i" class="rounded border border-slate-200 p-2">
                  <div class="flex items-center gap-2">
                    <span class="tag" :class="priorityClass(h.priority)">{{ h.priority }}</span>
                    <span class="text-[12px] font-medium text-ink-900">{{ h.title }}</span>
                  </div>
                  <div class="mt-1 text-[12px] text-ink-600">{{ h.detail }}</div>
                </div>
              </div>
              <div v-else class="text-[12px] text-ink-400">暂无建议</div>
            </div>

            <!-- 判题结果 -->
            <div v-else-if="output.tab === 'judge'" class="p-3">
              <div v-if="!judgeResult" class="text-[12px] text-ink-400">点「判题」按钮，用测试用例验证当前代码</div>
              <template v-else>
                <div class="mb-2 flex items-center gap-2">
                  <span class="tag" :class="verdictClass(judgeResult.verdict)">{{ verdictLabel(judgeResult.verdict) }}</span>
                  <span class="text-[12px] text-ink-600">
                    通过 {{ judgeResult.passed }} / {{ judgeResult.total }} · {{ judgeResult.duration_ms }}ms
                  </span>
                  <span v-if="judgeResult.skipped" class="tag bg-ink-100 text-ink-500">
                    已跳过 {{ judgeResult.skipped }} 条停用用例
                  </span>
                </div>
                <div class="space-y-1">
                  <div
                    v-for="r in judgeResult.results"
                    :key="r.index"
                    class="rounded border border-slate-200 p-2 text-[12px]"
                  >
                    <div class="flex items-center gap-2">
                      <span class="tag" :class="verdictClass(r.verdict)">{{ verdictLabel(r.verdict) }}</span>
                      <span class="text-ink-600">用例 #{{ r.index }}</span>
                      <span class="text-[11px] text-ink-400">{{ r.duration_ms }}ms</span>
                    </div>
                    <div v-if="r.verdict !== 'accepted'" class="mt-1.5 grid grid-cols-2 gap-2">
                      <div>
                        <div class="mb-0.5 text-[11px] text-ink-400">期望</div>
                        <pre class="max-h-24 overflow-auto rounded bg-slate-50 p-1.5 font-mono text-[11px]">{{ r.expected || '(空)' }}</pre>
                      </div>
                      <div>
                        <div class="mb-0.5 text-[11px] text-ink-400">实际</div>
                        <pre class="max-h-24 overflow-auto rounded bg-rose-50 p-1.5 font-mono text-[11px]">{{ r.actual || r.stderr || '(空)' }}</pre>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- 输出面板收起时的细条 -->
        <div v-else class="flex shrink-0 items-center gap-2 border-t border-slate-200 bg-white px-2 py-0.5 text-[11px] text-ink-400">
          <button class="hover:text-ink-700" @click="openOutput('stdout')">展开输出面板</button>
          <span v-if="lastOutputPreview" class="truncate font-mono">{{ lastOutputPreview }}</span>
        </div>
      </main>

      <!-- ============ 右：抽屉（AI / 分析 / 历史 / 版本 / 评论） ============ -->
      <aside
        v-if="anyDrawerOpen"
        class="flex w-80 shrink-0 flex-col border-l border-slate-200 bg-white"
      >
        <div class="flex items-center gap-1 border-b border-slate-100 px-2 py-1.5">
          <template v-if="drawer === 'ai'">
            <span class="text-[12px] font-semibold text-ink-900">🤖 智能辅助</span>
            <span v-if="aiStatus" class="tag" :class="aiStatus.llm && aiStatus.llm.configured ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'">
              {{ aiStatus.llm && aiStatus.llm.configured ? 'LLM 已接入' : '本地模式' }}
            </span>
          </template>
          <span v-else-if="drawer === 'analysis'" class="text-[12px] font-semibold text-ink-900">📊 静态分析</span>
          <span v-else-if="drawer === 'history'" class="text-[12px] font-semibold text-ink-900">🕘 运行历史</span>
          <span v-else-if="drawer === 'bookmark'" class="text-[12px] font-semibold text-ink-900">
            🔖 行书签<span v-if="currentBookmarks.length" class="tag ml-1">{{ currentBookmarks.length }}</span>
          </span>
          <span v-else-if="graphDrawer" class="text-[12px] font-semibold text-ink-900">◲ 版本历史</span>
          <span v-else-if="commentDrawer" class="text-[12px] font-semibold text-ink-900">💬 行评论</span>
          <div class="flex-1"></div>
          <button class="btn-ghost h-5 px-1 text-[12px]" @click="closeDrawers">×</button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2">
          <!-- ---- AI 抽屉 ---- -->
          <template v-if="drawer === 'ai'">
            <div class="mb-2 grid grid-cols-2 gap-1">
              <button
                v-for="act in aiActions"
                :key="act.key"
                class="btn-outline h-7 text-[11px]"
                :disabled="aiBusy || !activeFile"
                @click="runAi(act.key)"
              >
                {{ act.icon }} {{ act.label }}
              </button>
            </div>

            <div class="mb-2 rounded border border-slate-200 p-2">
              <div class="mb-1 text-[11px] font-medium text-ink-700">生成代码</div>
              <textarea
                v-model="aiInstruction"
                class="input mb-1 h-14 resize-none py-1 text-[11px]"
                placeholder="描述你的需求，例如：读入 N 个整数，输出其中位数"
              ></textarea>
              <div class="flex gap-1">
                <button class="btn-primary h-6 flex-1 text-[11px]" :disabled="aiBusy || !aiInstruction.trim()" @click="runAi('generate')">
                  生成并插入
                </button>
                <button class="btn-outline h-6 text-[11px]" :disabled="aiBusy" @click="runAi('chat_edit')">改写当前</button>
              </div>
            </div>

            <div class="mb-2 rounded border border-slate-200 p-2">
              <div class="mb-1 text-[11px] font-medium text-ink-700">解释报错</div>
              <button class="btn-outline h-6 w-full text-[11px]" :disabled="aiBusy" @click="runAi('error_explain')">
                分析最近一次报错
              </button>
            </div>

            <div class="mb-2 rounded border border-slate-200 p-2">
              <div class="mb-1 text-[11px] font-medium text-ink-700">其它工具</div>
              <div class="grid grid-cols-2 gap-1">
                <button class="btn-outline h-6 text-[11px]" :disabled="aiBusy" @click="aiTool('regex')">正则生成</button>
                <button class="btn-outline h-6 text-[11px]" :disabled="aiBusy" @click="aiTool('nl2sql')">NL→SQL</button>
                <button class="btn-outline h-6 text-[11px]" :disabled="aiBusy" @click="aiTool('learning_path')">学习路径</button>
                <button class="btn-outline h-6 text-[11px]" :disabled="aiBusy" @click="aiTool('testdata')">测试数据</button>
              </div>
            </div>

            <div v-if="aiBusy" class="flex items-center gap-2 p-2 text-[11px] text-ink-500">
              <span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600"></span>
              处理中…
            </div>

            <div v-if="aiResult" class="rounded border border-slate-200">
              <div class="flex items-center gap-1 border-b border-slate-100 px-2 py-1">
                <span class="tag" :class="aiSource === 'llm' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'">
                  {{ aiSource === 'llm' ? '模型输出' : '本地分析' }}
                </span>
                <div class="flex-1"></div>
                <button class="btn-ghost h-5 px-1 text-[11px]" @click="copyText(aiResult)">复制</button>
                <button v-if="aiIsCode" class="btn-ghost h-5 px-1 text-[11px]" @click="insertAiResult">插入</button>
                <button v-if="aiIsCode" class="btn-ghost h-5 px-1 text-[11px]" @click="replaceWithAiResult">替换</button>
              </div>
              <pre class="max-h-[420px] overflow-auto whitespace-pre-wrap break-words p-2 font-mono text-[11px] leading-relaxed text-ink-800">{{ aiResult }}</pre>
            </div>
          </template>

          <!-- ---- 分析抽屉 ---- -->
          <template v-else-if="drawer === 'analysis'">
            <div class="mb-2 flex flex-wrap gap-1">
              <button class="btn-outline h-6 text-[11px]" :disabled="!activeFile" @click="loadAnalysis">全面分析</button>
              <button class="btn-outline h-6 text-[11px]" :disabled="!activeFile" @click="doComplexity">复杂度</button>
              <button class="btn-outline h-6 text-[11px]" :disabled="!activeFile" @click="loadQuality">质量评分</button>
              <button class="btn-outline h-6 text-[11px]" :disabled="!activeFile" @click="drawer = ''; doDuplicateCheck()">查重</button>
            </div>

            <div v-if="analysis" class="space-y-2">
              <div class="rounded border border-slate-200 p-2">
                <div class="mb-1.5 text-[11px] font-medium text-ink-700">代码指标</div>
                <div class="grid grid-cols-2 gap-1 gap-x-3 text-[11px]">
                  <Metric label="总行数" :value="analysis.metrics.total_lines" />
                  <Metric label="有效代码" :value="analysis.metrics.code_lines" />
                  <Metric label="注释行" :value="analysis.metrics.comment_lines" />
                  <Metric label="注释率" :value="pct(analysis.metrics.comment_ratio)" />
                  <Metric label="函数" :value="analysis.metrics.functions" />
                  <Metric label="类" :value="analysis.metrics.classes" />
                  <Metric label="圈复杂度" :value="analysis.metrics.cyclomatic" />
                  <Metric label="最长行" :value="analysis.metrics.max_line_length" />
                </div>
              </div>

              <div class="rounded border border-slate-200 p-2">
                <div class="mb-1 flex items-center gap-2">
                  <span class="text-[11px] font-medium text-ink-700">质量评分</span>
                  <span class="ml-auto text-[16px] font-bold" :class="scoreColor(analysis.metrics.quality_score)">
                    {{ analysis.metrics.quality_score }}
                  </span>
                </div>
                <div class="mb-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div class="h-full rounded-full transition-all" :class="barColor(analysis.metrics.quality_score)" :style="{ width: analysis.metrics.quality_score + '%' }"></div>
                </div>
                <div v-if="analysis.metrics.deductions?.length" class="space-y-0.5">
                  <div v-for="(d, i) in analysis.metrics.deductions" :key="i" class="text-[11px] text-ink-500">· {{ d }}</div>
                </div>
              </div>

              <div class="rounded border border-slate-200 p-2">
                <div class="mb-1 flex items-center gap-2">
                  <span class="text-[11px] font-medium text-ink-700">复杂度</span>
                  <span class="tag bg-brand-50 text-brand-700">{{ analysis.complexity.big_o }}</span>
                </div>
                <div class="text-[11px] text-ink-600">{{ analysis.complexity.hint }}</div>
                <div class="mt-1 flex gap-3 text-[11px] text-ink-500">
                  <span>循环嵌套 {{ analysis.complexity.max_loop_depth }} 层</span>
                  <span v-if="analysis.complexity.recursive" class="text-amber-600">含递归</span>
                </div>
              </div>

              <div v-if="analysis.outline?.length" class="rounded border border-slate-200 p-2">
                <div class="mb-1 text-[11px] font-medium text-ink-700">大纲</div>
                <div class="space-y-0.5">
                  <OutlineItem v-for="(o, i) in analysis.outline" :key="i" :item="o" :depth="0" @jump="(l) => editorRef?.goToLine(l)" />
                </div>
              </div>

              <div class="rounded border border-slate-200 p-2">
                <div class="mb-1 flex items-center gap-2">
                  <span class="text-[11px] font-medium text-ink-700">问题清单</span>
                  <span class="tag">{{ analysis.issues?.length || 0 }}</span>
                </div>
                <div v-if="!analysis.issues?.length" class="text-[11px] text-emerald-600">未发现明显问题</div>
                <div class="max-h-64 space-y-0.5 overflow-y-auto">
                  <div
                    v-for="(it, i) in analysis.issues"
                    :key="i"
                    class="cursor-pointer rounded px-1 py-0.5 text-[11px] hover:bg-slate-50"
                    @click="it.line && editorRef?.goToLine(it.line)"
                  >
                    <span class="text-ink-400">{{ it.line }}</span>
                    <span class="mx-1" :class="it.severity === 'error' ? 'text-rose-600' : it.severity === 'warning' ? 'text-amber-600' : 'text-sky-600'">
                      {{ it.severity === 'error' ? '✕' : it.severity === 'warning' ? '!' : 'i' }}
                    </span>
                    {{ it.message }}
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="py-8 text-center text-[11px] text-ink-400">点「全面分析」开始</div>
          </template>

          <!-- ---- 历史抽屉 ---- -->
          <template v-else-if="drawer === 'history'">
            <div class="mb-2 flex gap-1">
              <button class="btn-outline h-6 flex-1 text-[11px]" @click="loadHistory">刷新</button>
              <button class="btn-ghost h-6 text-[11px]" @click="clearHistory">清空</button>
            </div>
            <div v-if="runHistory.length" class="space-y-1">
              <div
                v-for="r in runHistory"
                :key="r.id"
                class="cursor-pointer rounded border border-slate-200 p-1.5 text-[11px] hover:border-brand-400"
                @click="loadRunDetail(r.id)"
              >
                <div class="flex items-center gap-1.5">
                  <span class="tag" :class="statusTagClass(r.status)">{{ statusLabel(r.status) }}</span>
                  <span class="font-mono text-ink-700">{{ r.language }}</span>
                  <span class="ml-auto text-ink-400">{{ r.duration_ms }}ms</span>
                </div>
                <div class="mt-0.5 text-ink-400">{{ fmtTime(r.created_at) }}</div>
                <div v-if="r.stdout_preview" class="mt-0.5 truncate font-mono text-ink-500">{{ r.stdout_preview }}</div>
              </div>
            </div>
            <div v-else class="py-8 text-center text-[11px] text-ink-400">还没有运行记录</div>

            <!-- 贡献热力图 -->
            <div class="mt-3 rounded border border-slate-200 p-2">
              <div class="mb-1.5 flex items-center gap-2">
                <span class="text-[11px] font-medium text-ink-700">运行热力图</span>
                <span v-if="runStats" class="ml-auto text-[11px] text-ink-500">
                  连续 {{ runStats.streak_days }} 天 · 共 {{ runStats.total }} 次
                </span>
              </div>
              <div v-if="runStats" class="flex flex-wrap gap-0.5">
                <span
                  v-for="c in runStats.heatmap"
                  :key="c.date"
                  class="h-2.5 w-2.5 rounded-sm"
                  :class="heatClass(c.count)"
                  :title="`${c.date}：${c.count} 次`"
                ></span>
              </div>
            </div>

            <div v-if="runStats" class="mt-2 rounded border border-slate-200 p-2">
              <div class="mb-1 text-[11px] font-medium text-ink-700">语言分布</div>
              <div class="space-y-0.5">
                <div v-for="l in runStats.by_language" :key="l.language" class="flex items-center gap-2 text-[11px]">
                  <span class="w-20 truncate text-ink-600">{{ l.language }}</span>
                  <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div class="h-full bg-brand-500" :style="{ width: (l.n / maxLangCount) * 100 + '%' }"></div>
                  </div>
                  <span class="w-6 text-right text-ink-500">{{ l.n }}</span>
                </div>
              </div>
            </div>
          </template>

          <!-- ---- F673 行书签抽屉（侧栏跳转） ---- -->
          <template v-else-if="drawer === 'bookmark'">
            <div class="mb-2 flex items-center gap-1">
              <span class="text-[11px] text-ink-500">{{ activeFile?.path || '未打开文件' }}</span>
              <div class="flex-1"></div>
              <button class="btn-outline h-6 text-[11px]" :disabled="!activeFile" @click="toggleBookmark(cursorInfo.line)">
                ＋ 标当前行（{{ cursorInfo.line }}）
              </button>
            </div>
            <div v-if="!currentBookmarks.length" class="py-8 text-center text-[12px] text-ink-400">
              还没有书签<br /><span class="text-[11px]">点击行号左侧的圆点，或用上方按钮标记</span>
            </div>
            <div v-else class="space-y-1">
              <div
                v-for="line in currentBookmarks"
                :key="line"
                class="group flex cursor-pointer items-center gap-2 rounded border border-slate-200 px-2 py-1.5 text-[12px] hover:border-amber-300 hover:bg-amber-50/40"
                @click="editorRef?.goToLine(line)"
              >
                <span class="text-amber-500">●</span>
                <span class="font-mono text-ink-700">第 {{ line }} 行</span>
                <span class="min-w-0 flex-1 truncate text-ink-400">{{ linePreview(line) }}</span>
                <button class="btn-ghost h-5 px-1 text-[11px] text-rose-600 opacity-0 group-hover:opacity-100" @click.stop="toggleBookmark(line)">移除</button>
              </div>
            </div>
            <p class="mt-2 text-[11px] text-ink-400">书签按文件保存在本机（localStorage），刷新不丢。</p>
          </template>

          <!-- ---- 版本抽屉 ---- -->
          <template v-else-if="graphDrawer">
            <div class="mb-2 flex gap-1">
              <button class="btn-outline h-6 flex-1 text-[11px]" @click="loadVersions">刷新</button>
              <button class="btn-outline h-6 text-[11px]" @click="doSnapshot">📌 新建快照</button>
            </div>
            <div v-if="versions.length" class="space-y-1">
              <div
                v-for="(v, i) in versions"
                :key="v.id"
                class="rounded border p-1.5 text-[11px]"
                :class="diffTarget === v.id ? 'border-brand-400 bg-brand-50/40' : 'border-slate-200'"
              >
                <div class="flex items-center gap-1.5">
                  <span class="tag">v{{ versions.length - i }}</span>
                  <span class="truncate text-ink-700">{{ v.message }}</span>
                  <span class="ml-auto shrink-0 text-ink-400">{{ v.size }}B</span>
                </div>
                <div class="mt-0.5 truncate font-mono text-ink-500">{{ v.preview }}</div>
                <div class="mt-1 flex items-center gap-1">
                  <span class="text-ink-400">{{ fmtTime(v.created_at) }}</span>
                  <div class="flex-1"></div>
                  <button class="btn-ghost h-5 px-1 text-[11px]" @click="viewDiff(v.id)">比对当前</button>
                  <button class="btn-ghost h-5 px-1 text-[11px] text-amber-700" @click="doRollback(v)">回滚</button>
                </div>
              </div>
            </div>
            <div v-else class="py-8 text-center text-[11px] text-ink-400">还没有版本快照</div>

            <!-- diff 视图 -->
            <div v-if="diffData" class="mt-3 rounded border border-slate-200">
              <div class="flex items-center gap-2 border-b border-slate-100 px-2 py-1">
                <span class="text-[11px] font-medium text-ink-700">差异</span>
                <span class="tag bg-emerald-100 text-emerald-700">+{{ diffData.stats.add }}</span>
                <span class="tag bg-rose-100 text-rose-700">-{{ diffData.stats.del }}</span>
                <div class="flex-1"></div>
                <button class="btn-ghost h-5 px-1 text-[11px]" @click="diffData = null">×</button>
              </div>
              <pre class="max-h-72 overflow-auto p-1.5 font-mono text-[11px] leading-relaxed"><span
                v-for="(h, i) in diffData.diff"
                :key="i"
                class="block px-1"
                :class="h.type === 'add' ? 'bg-emerald-50 text-emerald-700'
                  : h.type === 'del' ? 'bg-rose-50 text-rose-700'
                  : h.type === 'hunk' ? 'bg-slate-100 text-sky-700'
                  : 'text-ink-600'"
              >{{ h.type === 'add' ? '+' : h.type === 'del' ? '-' : ' ' }}{{ h.text }}</span></pre>
            </div>
          </template>

          <!-- ---- 评论抽屉 ---- -->
          <template v-else-if="commentDrawer">
            <div class="mb-2 rounded border border-slate-200 p-2">
              <div class="mb-1 flex items-center gap-1.5 text-[11px] text-ink-600">
                <span>针对第</span>
                <input v-model.number="newCommentLine" type="number" min="1" class="input h-5 w-12 py-0 text-[11px]" />
                <span>行</span>
                <button class="btn-ghost h-5 px-1 text-[11px]" @click="newCommentLine = cursorInfo.line">用当前行</button>
              </div>
              <textarea v-model="newCommentText" class="input mb-1 h-12 resize-none py-1 text-[11px]" placeholder="写下你的意见…"></textarea>
              <button class="btn-primary h-6 w-full text-[11px]" :disabled="!newCommentText.trim()" @click="addComment">发表评论</button>
            </div>
            <div v-if="comments.length" class="space-y-1.5">
              <div v-for="c in comments" :key="c.id" class="rounded border p-1.5 text-[11px]" :class="c.resolved ? 'border-slate-200 opacity-60' : 'border-slate-300'">
                <div class="flex items-center gap-1.5">
                  <span class="tag">L{{ c.line }}</span>
                  <span class="font-medium text-ink-800">{{ c.author }}</span>
                  <span class="ml-auto text-ink-400">{{ fmtTime(c.created_at) }}</span>
                </div>
                <div class="mt-1 cursor-pointer text-ink-700" @click="editorRef?.goToLine(c.line)">{{ c.content }}</div>
                <div v-for="r in c.replies" :key="r.id" class="mt-1 border-l-2 border-slate-200 pl-2 text-ink-600">
                  <span class="font-medium">{{ r.author }}</span>：{{ r.content }}
                </div>
                <div class="mt-1 flex gap-1">
                  <button class="btn-ghost h-5 px-1 text-[11px]" @click="replyTo = replyTo === c.id ? null : c.id">回复</button>
                  <button class="btn-ghost h-5 px-1 text-[11px]" @click="toggleResolve(c)">{{ c.resolved ? '重开' : '解决' }}</button>
                  <button v-if="c.is_mine" class="btn-ghost h-5 px-1 text-[11px] text-rose-600" @click="removeComment(c)">删除</button>
                </div>
                <div v-if="replyTo === c.id" class="mt-1 flex gap-1">
                  <input v-model="replyText" class="input h-6 flex-1 py-0 text-[11px]" placeholder="回复…" @keyup.enter="sendReply(c)" />
                  <button class="btn-outline h-6 text-[11px]" @click="sendReply(c)">发送</button>
                </div>
              </div>
            </div>
            <div v-else class="py-8 text-center text-[11px] text-ink-400">还没有评论</div>
          </template>
        </div>
      </aside>
    </div>

    <!-- ============ 模态框 ============ -->
    <Modal v-model="showWsModal" title="新建工作区">
      <div class="space-y-2">
        <div>
          <label class="mb-1 block text-[12px] text-ink-600">工作区名</label>
          <input v-model="wsForm.name" class="input" placeholder="例如：算法练习" />
        </div>
        <div>
          <label class="mb-1 block text-[12px] text-ink-600">主语言</label>
          <select v-model="wsForm.language" class="input">
            <option v-for="l in languages" :key="l.key" :value="l.key">
              {{ l.name }}{{ l.available ? '' : '（本机未安装）' }}
            </option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-[12px] text-ink-600">描述（可选）</label>
          <textarea v-model="wsForm.description" class="input h-16 resize-none"></textarea>
        </div>
        <label class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="wsForm.with_entry" type="checkbox" />
          自动创建入口文件（含语言模板）
        </label>
      </div>
      <template #footer>
        <button class="btn-outline" @click="showWsModal = false">取消</button>
        <button class="btn-primary" :disabled="!wsForm.name.trim()" @click="doCreateWs">创建</button>
      </template>
    </Modal>

    <Modal v-model="showFileModal" title="新建文件">
      <div class="space-y-2">
        <div>
          <label class="mb-1 block text-[12px] text-ink-600">路径（支持子目录）</label>
          <input v-model="fileForm.path" class="input" placeholder="例如：utils/helper.py" @keyup.enter="doCreateFile" />
          <div class="mt-1 text-[11px] text-ink-400">扩展名决定语言：.py .js .cpp .go .rs .java .sql 等</div>
        </div>
      </div>
      <template #footer>
        <button class="btn-outline" @click="showFileModal = false">取消</button>
        <button class="btn-primary" :disabled="!fileForm.path.trim()" @click="doCreateFile">创建</button>
      </template>
    </Modal>

    <Modal v-model="showJudgeModal" title="判题测试用例">
      <div class="space-y-2">
        <div>
          <label class="mb-1 block text-[12px] text-ink-600">题目名</label>
          <input v-model="judgeForm.title" class="input" />
        </div>
        <div>
          <div class="mb-1 flex items-center gap-2">
            <label class="text-[12px] text-ink-600">测试用例</label>
            <span class="text-[11px] text-ink-400">启用 {{ enabledCaseCount }}/{{ judgeForm.testcases.length }}（停用的判题时跳过）</span>
            <div class="flex-1"></div>
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="setAllCases(true)">全部启用</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="setAllCases(false)">全部停用</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="addCase">＋ 加一条</button>
          </div>
          <div v-for="(c, i) in judgeForm.testcases" :key="i" class="mb-1 rounded border border-slate-200 p-1.5"
            :class="{ 'opacity-60 bg-slate-50': c.enabled === false }">
            <div class="mb-1 flex items-center gap-1">
              <input
                type="checkbox"
                :checked="c.enabled !== false"
                class="accent-brand-600"
                @change="c.enabled = $event.target.checked"
              />
              <label class="cursor-pointer text-[11px] text-ink-500">#{{ i + 1 }}</label>
              <span v-if="c.enabled === false" class="tag bg-ink-100 text-ink-400">已停用</span>
              <div class="flex-1"></div>
              <button class="btn-ghost h-5 px-1 text-[11px]" @click="c.enabled = c.enabled === false">{{ c.enabled === false ? '启用' : '停用' }}</button>
              <button v-if="judgeForm.testcases.length > 1" class="btn-ghost h-5 px-1 text-[11px] text-rose-600" @click="judgeForm.testcases.splice(i, 1)">删除</button>
            </div>
            <div class="grid grid-cols-2 gap-1">
              <textarea v-model="c.stdin" class="input h-12 resize-none py-1 font-mono text-[11px]" placeholder="输入 stdin"></textarea>
              <textarea v-model="c.expected" class="input h-12 resize-none py-1 font-mono text-[11px]" placeholder="期望输出"></textarea>
            </div>
          </div>
        </div>
        <label class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="judgeForm.ignore_whitespace" type="checkbox" />
          忽略行尾空白与首尾空行
        </label>
      </div>
      <template #footer>
        <button class="btn-outline" @click="showJudgeModal = false">取消</button>
        <button class="btn-primary" @click="runJudge">开始判题</button>
      </template>
    </Modal>

    <Modal v-model="showSnippetPanel" title="代码片段库" width="720px">
      <div class="mb-2 flex gap-1">
        <input v-model="snippetQuery" class="input h-7 flex-1 py-0 text-[12px]" placeholder="搜索标题、描述或代码…" @keyup.enter="loadSnippets" />
        <select v-model="snippetTagFilter" class="input h-7 py-0 text-[12px]" style="width: 110px" @change="loadSnippets">
          <option value="">全部标签</option>
          <option v-for="t in snippetTags" :key="t.name" :value="t.name">{{ t.name }}（{{ t.count }}）</option>
        </select>
        <!-- F669 收藏夹分组：按组筛选 -->
        <select v-model="snippetFolderFilter" class="input h-7 py-0 text-[12px]" style="width: 120px" @change="loadSnippets" title="按收藏夹分组筛选">
          <option value="">全部分组</option>
          <option value="__mine">我的收藏 ★</option>
          <option v-for="f in snippetFolders" :key="f.key" :value="f.key">{{ f.label }}（{{ f.count }}）</option>
        </select>
        <button class="btn-outline h-7 text-[12px]" @click="loadSnippets">搜索</button>
        <button class="btn-primary h-7 text-[12px]" :disabled="!activeFile" @click="saveCurrentAsSnippet">存为片段</button>
      </div>
      <div class="mb-1.5 flex flex-wrap items-center gap-1 text-[11px] text-ink-400">
        <span v-for="f in snippetFolders" :key="f.key" class="tag bg-slate-100 text-ink-500">{{ f.label }} {{ f.count }}</span>
        <span v-if="!snippetFolders.length">还没有分组：给片段点「★ 收藏」后可归入分组</span>
      </div>
      <div class="max-h-96 space-y-1 overflow-y-auto">
        <div v-for="s in snippets" :key="s.id" class="rounded border border-slate-200 p-2">
          <div class="flex items-center gap-2">
            <span class="text-[12px] font-medium text-ink-900">{{ s.title }}</span>
            <span class="tag">{{ s.language }}</span>
            <span v-if="s.folder" class="tag bg-brand-50 text-brand-700">📁 {{ s.folder }}</span>
            <span v-for="t in s.tags" :key="t" class="tag bg-brand-50 text-brand-700">{{ t }}</span>
            <div class="flex-1"></div>
            <button
              v-if="s.is_mine"
              class="btn-ghost h-5 px-1 text-[11px]"
              :class="s.is_favorite ? 'text-amber-500' : 'text-ink-300'"
              :title="s.is_favorite ? '取消收藏' : '收藏'"
              @click="toggleSnippetFav(s)"
            >★</button>
            <span class="text-[11px] text-ink-400">{{ s.owner }}</span>
          </div>
          <div v-if="s.description" class="mt-0.5 text-[11px] text-ink-500">{{ s.description }}</div>
          <pre class="mt-1 max-h-24 overflow-auto rounded bg-slate-50 p-1.5 font-mono text-[11px] text-ink-700">{{ s.code }}</pre>
          <div class="mt-1 flex gap-1">
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="insertSnippet(s)">插入</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="copyText(s.code)">复制</button>
            <button class="btn-ghost h-5 px-1 text-[11px]" @click="copySnippetInto(s)">存入我的库</button>
            <button v-if="s.is_mine" class="btn-ghost h-5 px-1 text-[11px]" @click="moveSnippetToFolder(s)">📁 归组</button>
            <button v-if="s.is_mine" class="btn-ghost h-5 px-1 text-[11px] text-rose-600" @click="removeSnippet(s)">删除</button>
          </div>
        </div>
        <div v-if="!snippets.length" class="py-8 text-center text-[12px] text-ink-400">还没有片段，先存一个吧</div>
      </div>
    </Modal>

    <Modal v-model="showBoardModal" title="排行榜" width="600px">
      <div class="max-h-96 overflow-y-auto">
        <table class="w-full text-[12px]">
          <thead>
            <tr class="border-b border-slate-200">
              <th class="th">名次</th>
              <th class="th">用户</th>
              <th class="th">通过题数</th>
              <th class="th">提交次数</th>
              <th class="th">运行次数</th>
              <th class="th">积分</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in leaderboard" :key="r.rank" class="border-b border-slate-100">
              <td class="td">
                <span :class="r.rank <= 3 ? 'font-bold text-amber-600' : ''">{{ r.rank }}</span>
              </td>
              <td class="td">{{ r.user }}</td>
              <td class="td">{{ r.solved }}</td>
              <td class="td">{{ r.attempts }}</td>
              <td class="td">{{ r.runs }}</td>
              <td class="td font-medium">{{ r.score }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!leaderboard.length" class="py-8 text-center text-[12px] text-ink-400">还没有提交记录</div>
      </div>
    </Modal>

    <Modal v-model="showHelp" title="代码工坊 使用说明" width="640px">
      <div class="space-y-2 text-[12px] leading-relaxed text-ink-700">
        <div>
          <div class="mb-0.5 font-semibold text-ink-900">运行环境</div>
          <div>本机探测到 <b>{{ availableRuntimeCount }}</b> 个可用运行时。未安装的语言按钮会置灰，代码照常保存，装好即可运行。</div>
        </div>
        <div>
          <div class="mb-0.5 font-semibold text-ink-900">安全边界</div>
          <div>执行在独立临时目录中进行，环境变量白名单、无 shell 直通、输出 64KB 截断、默认 5 秒超时（上限 30 秒）。检测到高危操作（如 <code class="rounded bg-slate-100 px-1">rm -rf /</code>、磁盘格式化、反弹 shell）会直接拒绝。</div>
        </div>
        <div>
          <div class="mb-0.5 font-semibold text-ink-900">快捷键</div>
          <div class="space-y-0.5 font-mono text-[11px]">
            <div>Ctrl + Enter　　运行当前代码</div>
            <div>Ctrl + S　　　　保存（含快照）</div>
            <div>Ctrl + F　　　　查找替换</div>
            <div>Ctrl + /　　　　注释 / 取消注释</div>
            <div>Ctrl + Alt + ↑/↓　复制当前行</div>
            <div>Alt + ↑/↓　　　移动当前行</div>
          </div>
        </div>
        <div>
          <div class="mb-0.5 font-semibold text-ink-900">已有能力</div>
          <div>版本历史与回滚 · 行级评论 · Yjs 实时协同 · 判题与排行榜 · 代码片段库 · 全文检索 · 涉密扫描 · 代码查重 · 复杂度与质量评分 · 流程图抽取 · 分享链接 · 代码归属统计 · TODO 聚合 · 工程洞察 · 每日一题 · 成就徽章 · 错题本 · 学习路径</div>
        </div>
      </div>
    </Modal>

    <!-- ============ F676 运行参数预设 ============ -->
    <Modal :show="showRunCfg" title="⚙ 运行参数（按语言保存预设）" width="560px" @close="showRunCfg = false">
      <div class="space-y-3 text-[12px]">
        <div class="flex items-center gap-2">
          <span class="text-ink-500">当前语言</span>
          <span class="tag-brand">{{ activeFile?.language || 'python' }}</span>
          <div class="flex-1"></div>
          <select
            class="input h-7 w-56 py-0 text-[12px]"
            :value="activePresetId"
            @change="choosePresetById(Number($event.target.value))"
          >
            <option :value="0">— 不使用预设 —</option>
            <option v-for="p in langPresets" :key="p.id" :value="p.id">
              {{ p.name }}{{ p.is_default ? ' ★' : '' }}
            </option>
          </select>
        </div>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-500">标准输入 stdin（运行时自动喂给程序）</span>
          <textarea v-model="runCfg.stdin" class="input h-28 resize-none font-mono text-[12px]" placeholder="每行一个输入，如&#10;3 5&#10;7 9"></textarea>
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="mb-1 block text-[11px] text-ink-500">命令行参数（空格分隔）</span>
            <input v-model="runCfg.args" class="input font-mono text-[12px]" placeholder="-O --verbose" />
          </label>
          <label class="block">
            <span class="mb-1 block text-[11px] text-ink-500">超时（秒）</span>
            <input v-model.number="runCfg.timeout" type="number" min="0.5" max="30" step="0.5" class="input" />
          </label>
        </div>
        <p class="text-[11px] text-ink-400">
          预设按语言保存在服务端（run/presets），换设备也能用；未保存的改动仅作用于当前语言。
        </p>
        <div class="flex justify-end gap-2">
          <button v-if="activePreset" class="btn-danger" @click="removeRunPreset">删除预设</button>
          <button class="btn-outline" @click="choosePreset(null); showRunCfg = false">清空</button>
          <button class="btn-primary" :disabled="!activeFile" @click="saveRunPreset">保存预设</button>
        </div>
      </div>
    </Modal>

    <!-- ============ F677 代码统计卡 ============ -->
    <Modal :show="showStatsCard" title="📐 代码统计卡" width="520px" @close="showStatsCard = false">
      <div v-if="statsLoading" class="py-10 text-center text-[13px] text-ink-400">统计中…</div>
      <template v-else-if="statsCard">
        <div class="grid grid-cols-3 gap-2">
          <div class="rounded border border-ink-100 p-2.5 text-center">
            <div class="text-[11px] text-ink-500">总行数</div>
            <div class="text-xl font-semibold text-ink-900">{{ statsCard.total_lines }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5 text-center">
            <div class="text-[11px] text-ink-500">代码行</div>
            <div class="text-xl font-semibold text-sky-600">{{ statsCard.code_lines }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5 text-center">
            <div class="text-[11px] text-ink-500">注释率</div>
            <div class="text-xl font-semibold text-emerald-600">{{ statsCard.comment_ratio_pct }}%</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5 text-center">
            <div class="text-[11px] text-ink-500">函数数</div>
            <div class="text-xl font-semibold text-brand-600">{{ statsCard.function_count }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5 text-center">
            <div class="text-[11px] text-ink-500">类数</div>
            <div class="text-xl font-semibold text-purple-600">{{ statsCard.class_count }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5 text-center">
            <div class="text-[11px] text-ink-500">质量分</div>
            <div class="text-xl font-semibold" :class="scoreColor(statsCard.quality_score)">{{ statsCard.quality_score }}</div>
          </div>
        </div>
        <div class="mt-3 space-y-1.5 text-[12px]">
          <div class="flex items-center gap-2">
            <span class="w-24 text-ink-500">注释 / 空行</span>
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
              <div class="h-full bg-emerald-500" :style="{ width: Math.min(100, statsCard.comment_ratio_pct) + '%' }"></div>
            </div>
            <span class="w-28 text-right text-ink-500">{{ statsCard.comment_lines }} / {{ statsCard.blank_lines }} 行</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-24 text-ink-500">函数密度</span>
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
              <div class="h-full bg-brand-500" :style="{ width: Math.min(100, statsCard.function_density * 4) + '%' }"></div>
            </div>
            <span class="w-28 text-right text-ink-500">{{ statsCard.function_density }} 个/百行</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-24 text-ink-500">平均行长</span>
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
              <div class="h-full bg-sky-500" :style="{ width: Math.min(100, statsCard.avg_line_length / 1.2) + '%' }"></div>
            </div>
            <span class="w-28 text-right text-ink-500">{{ statsCard.avg_line_length }} 字符</span>
          </div>
        </div>
        <div class="mt-3 grid grid-cols-3 gap-2 border-t border-ink-100 pt-2 text-[11px] text-ink-500">
          <span>空行率 {{ statsCard.blank_ratio_pct }}%</span>
          <span>TODO {{ statsCard.todo_count }} 处</span>
          <span>圈复杂度 {{ statsCard.cyclomatic }}</span>
          <span>最长行 {{ statsCard.max_line_length }}</span>
          <span>{{ statsCard.bytes }} 字节</span>
          <span>{{ activeFile?.language }}</span>
        </div>
      </template>
      <div v-else class="py-10 text-center text-[13px] text-ink-400">打开一个文件后即可统计</div>
    </Modal>

    <!-- ============ F675 括号 / 引号未闭合提示 ============ -->
    <Modal :show="showBracePanel" title=") 括号 / 引号未闭合提示" width="520px" @close="showBracePanel = false">
      <div v-if="!braceIssues.length" class="py-8 text-center text-[13px] text-emerald-600">
        ✓ 括号与引号全部配对，很干净
      </div>
      <div v-else class="max-h-80 space-y-1 overflow-y-auto">
        <button
          v-for="(it, i) in braceIssues"
          :key="i"
          class="flex w-full items-center gap-2 rounded border border-amber-200 bg-amber-50/60 px-2 py-1.5 text-left text-[12px] hover:border-amber-400"
          @click="showBracePanel = false; editorRef?.goToLine(it.line)"
        >
          <span class="tag bg-amber-100 text-amber-700">L{{ it.line }}:{{ it.col }}</span>
          <span class="text-ink-700">{{ it.message }}</span>
        </button>
      </div>
      <p class="mt-2 text-[11px] text-ink-400">轻量自查（忽略字符串与注释），随输入自动刷新；点击条目跳到对应行。</p>
    </Modal>

    <!-- ============ L4：TODO 聚合面板 ============ -->
    <Modal :show="showTodos" title="📌 TODO 聚合" width="760px" @close="showTodos = false">
      <div v-if="todosBusy" class="py-10 text-center text-sm text-ink-400">扫描中…</div>
      <template v-else-if="todosData">
        <!-- 标签筛选 -->
        <div class="mb-3 flex flex-wrap items-center gap-1.5">
          <button
            class="rounded px-2 py-0.5 text-[11px]"
            :class="todoTag === '' ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-600 hover:bg-ink-200'"
            @click="openTodos('')"
          >全部 {{ todosData.total }}</button>
          <button
            v-for="t in todosData.by_tag"
            :key="t.tag"
            class="rounded px-2 py-0.5 text-[11px]"
            :class="todoTag === t.tag ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-600 hover:bg-ink-200'"
            @click="openTodos(t.tag)"
          >{{ t.tag }} {{ t.count }}</button>
          <span class="ml-auto text-[11px] text-ink-400">已扫描 {{ todosData.scanned_files }} 个文件</span>
        </div>

        <div v-if="!todosData.items.length" class="py-10 text-center text-sm text-ink-400">
          干净得像刚擦过的键盘，没有待办标记
        </div>
        <div v-else class="max-h-[55vh] space-y-1.5 overflow-y-auto">
          <div
            v-for="(it, i) in todosData.items"
            :key="i"
            class="cursor-pointer rounded border border-ink-100 px-2.5 py-2 text-[12px] transition hover:border-brand-300 hover:bg-brand-50/40"
            @click="jumpToTodo(it)"
          >
            <div class="flex items-center gap-2">
              <span
                class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
                :class="{
                  'bg-rose-100 text-rose-700': it.level === 'high',
                  'bg-amber-100 text-amber-700': it.level === 'medium',
                  'bg-sky-100 text-sky-700': it.level === 'low',
                  'bg-ink-100 text-ink-500': it.level === 'info',
                }"
              >{{ it.tag }}</span>
              <span class="min-w-0 flex-1 truncate text-ink-800">{{ it.text || '（无描述）' }}</span>
              <span v-if="it.done" class="shrink-0 text-[10px] text-emerald-600">已完成</span>
            </div>
            <div class="mt-1 truncate font-mono text-[10px] text-ink-400">
              {{ it.path }}:{{ it.line }}
            </div>
          </div>
        </div>
      </template>
    </Modal>

    <!-- ============ L4：工程洞察面板 ============ -->
    <Modal :show="showInsights" title="📈 工程洞察" width="760px" @close="showInsights = false">
      <div v-if="insightsBusy" class="py-10 text-center text-sm text-ink-400">统计中…</div>
      <template v-else-if="insightsData">
        <!-- 概要 -->
        <div class="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded border border-ink-100 p-2.5">
            <div class="text-[11px] text-ink-500">文件数</div>
            <div class="text-xl font-semibold text-ink-900">{{ insightsData.summary.files }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5">
            <div class="text-[11px] text-ink-500">代码行</div>
            <div class="text-xl font-semibold text-ink-900">{{ insightsData.summary.lines }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5">
            <div class="text-[11px] text-ink-500">近 30 天执行</div>
            <div class="text-xl font-semibold text-ink-900">{{ insightsData.summary.runs_30d }}</div>
          </div>
          <div class="rounded border border-ink-100 p-2.5">
            <div class="text-[11px] text-ink-500">成功率</div>
            <div class="text-xl font-semibold"
                 :class="insightsData.summary.success_rate >= 60 ? 'text-emerald-600' : 'text-rose-600'">
              {{ insightsData.summary.success_rate }}%
            </div>
          </div>
        </div>

        <!-- 健康度 -->
        <div class="mb-4 rounded border border-ink-100 p-3">
          <div class="mb-1.5 flex items-center justify-between">
            <span class="text-[12px] font-semibold text-ink-900">工程健康度</span>
            <span class="text-sm font-semibold"
                  :class="insightsData.summary.health >= 80 ? 'text-emerald-600'
                    : (insightsData.summary.health >= 60 ? 'text-amber-600' : 'text-rose-600')">
              {{ insightsData.summary.health }} / 100
            </span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-ink-100">
            <div
              class="h-full rounded-full transition-all"
              :class="insightsData.summary.health >= 80 ? 'bg-emerald-500'
                : (insightsData.summary.health >= 60 ? 'bg-amber-500' : 'bg-rose-500')"
              :style="{ width: insightsData.summary.health + '%' }"
            />
          </div>
          <div v-if="insightsData.alerts.length" class="mt-2 space-y-0.5">
            <div v-for="(a, i) in insightsData.alerts" :key="i" class="text-[11px] text-amber-700">
              ⚠ {{ a }}
            </div>
          </div>
          <div v-else class="mt-2 text-[11px] text-emerald-600">✓ 没发现明显问题</div>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <!-- 语言分布 -->
          <div>
            <div class="mb-2 text-[12px] font-semibold text-ink-900">语言分布</div>
            <div v-if="!insightsData.languages.length" class="text-[11px] text-ink-400">暂无数据</div>
            <div v-else class="space-y-1.5">
              <div v-for="l in insightsData.languages" :key="l.language">
                <div class="flex justify-between text-[11px]">
                  <span class="text-ink-700">{{ l.language }}</span>
                  <span class="text-ink-400">{{ l.count }} 个 · {{ l.percent }}%</span>
                </div>
                <div class="mt-0.5 h-1.5 overflow-hidden rounded-full bg-ink-100">
                  <div class="h-full rounded-full bg-brand-500" :style="{ width: l.percent + '%' }" />
                </div>
              </div>
            </div>
          </div>

          <!-- 目录分布 -->
          <div>
            <div class="mb-2 text-[12px] font-semibold text-ink-900">目录分布</div>
            <div v-if="!insightsData.directories.length" class="text-[11px] text-ink-400">暂无数据</div>
            <div v-else class="space-y-1">
              <div
                v-for="d in insightsData.directories"
                :key="d.dir"
                class="flex items-center justify-between rounded bg-ink-50 px-2 py-1 text-[11px]"
              >
                <span class="truncate font-mono text-ink-700">{{ d.dir }}</span>
                <span class="shrink-0 text-ink-400">{{ d.count }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 大文件告警 -->
        <div v-if="insightsData.biggest.length" class="mt-4">
          <div class="mb-2 text-[12px] font-semibold text-ink-900">体积最大的文件</div>
          <div class="space-y-1">
            <div
              v-for="b in insightsData.biggest"
              :key="b.id"
              class="flex items-center justify-between rounded bg-ink-50 px-2 py-1 text-[11px]"
            >
              <span class="truncate font-mono text-ink-700">{{ b.path }}</span>
              <span class="shrink-0 text-ink-400">{{ (b.size / 1024).toFixed(1) }} KB</span>
            </div>
          </div>
        </div>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Compartment, StateEffect, StateField } from '@codemirror/state'
import { EditorView, GutterMarker, gutter } from '@codemirror/view'
import { codeApi } from '../../api/code'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import CodeEditor from '../../components/CodeEditor.vue'

const router = useRouter()
const app = useAppStore()

// ===== 内部小组件 =====
const TreeNode = {
  name: 'TreeNode',
  props: { node: Object, activeId: Number, depth: Number },
  emits: ['open', 'ctx'],
  setup(props, { emit }) {
    const collapsed = ref(false)
    return () => {
      const n = props.node
      const pad = { paddingLeft: `${6 + props.depth * 10}px` }
      if (n.type === 'dir') {
        return h('div', [
          h('div', {
            class: 'flex cursor-pointer items-center gap-1 rounded px-1 py-[3px] text-[12px] text-ink-600 hover:bg-slate-100',
            style: pad,
            onClick: () => { collapsed.value = !collapsed.value },
          }, [
            h('span', { class: 'text-[10px] text-ink-400' }, collapsed.value ? '▸' : '▾'),
            h('span', {}, '📁'),
            h('span', { class: 'truncate' }, n.name),
          ]),
          !collapsed.value && h('div', n.children.map((c) =>
            h(TreeNode, {
              node: c,
              activeId: props.activeId,
              depth: props.depth + 1,
              onOpen: (f) => emit('open', f),
              onCtx: (f, e) => emit('ctx', f, e),
            })
          )),
        ])
      }
      return h('div', {
        class: [
          'group flex cursor-pointer items-center gap-1 rounded px-1 py-[3px] text-[12px]',
          n.id === props.activeId ? 'bg-brand-50 text-brand-700' : 'text-ink-700 hover:bg-slate-100',
        ],
        style: pad,
        onClick: () => emit('open', { id: n.id }),
        onContextmenu: (e) => { e.preventDefault(); emit('ctx', n, e) },
      }, [
        h('span', {}, n.is_entry ? '⭐' : '📄'),
        h('span', { class: 'truncate' }, n.name),
        n.is_favorite ? h('span', { class: 'ml-auto text-[10px]' }, '★') : null,
      ])
    }
  },
}

const Metric = {
  props: { label: String, value: [String, Number] },
  setup(props) {
    return () => h('div', { class: 'flex items-center justify-between' }, [
      h('span', { class: 'text-ink-400' }, props.label),
      h('span', { class: 'font-medium text-ink-800' }, String(props.value ?? '-')),
    ])
  },
}

const OutlineItem = {
  props: { item: Object, depth: Number },
  emits: ['jump'],
  setup(props, { emit }) {
    return () => {
      const it = props.item
      const icon = it.type === 'class' ? 'C' : it.type === 'struct' ? 'S' : 'ƒ'
      const color = it.type === 'class' ? 'text-purple-600' : it.type === 'struct' ? 'text-sky-600' : 'text-brand-600'
      return h('div', [
        h('div', {
          class: 'flex cursor-pointer items-center gap-1 rounded px-1 py-[2px] text-[11px] hover:bg-slate-50',
          style: { paddingLeft: `${4 + props.depth * 10}px` },
          onClick: () => emit('jump', it.line),
        }, [
          h('span', { class: `font-mono text-[10px] ${color}` }, icon),
          h('span', { class: 'truncate text-ink-700' }, it.name || '(匿名)'),
          h('span', { class: 'ml-auto text-ink-300' }, 'L' + it.line),
        ]),
        ...(it.children || []).map((c) =>
          h(OutlineItem, { item: c, depth: props.depth + 1, onJump: (l) => emit('jump', l) })
        ),
      ])
    }
  },
}

// ===== 状态 =====
const workspaces = ref([])
const activeWsId = ref(null)
const activeWs = ref(null)
const tree = ref([])
const fileQuery = ref('')

const tabs = ref([])          // [{id, name, path, dirty, language}]
const activeFileId = ref(null)
const activeFile = ref(null)
const code = ref('')
const editorRef = ref(null)
const cursorInfo = ref({ line: 1, col: 1 })

const languages = ref([])
const runtimes = ref({})

const theme = ref(localStorage.getItem('code-theme') || 'light')
const fontSize = ref(Number(localStorage.getItem('code-font') || 13))
const tabSize = ref(Number(localStorage.getItem('code-tab') || 4))
const lineWrapping = ref(localStorage.getItem('code-wrap') === '1')
const showInvisibles = ref(false)

const drawer = ref('')            // ai | analysis | history
const graphDrawer = ref(false)
const commentDrawer = ref(false)
const showHelp = ref(false)
const showWsModal = ref(false)
const showFileModal = ref(false)
const showJudgeModal = ref(false)
const showSnippetPanel = ref(false)
const showBoardModal = ref(false)
// L4 工程化：TODO 聚合面板 / 工程洞察面板
const showTodos = ref(false)
const todosData = ref(null)
const todosBusy = ref(false)
const todoTag = ref('')
const showInsights = ref(false)
const insightsData = ref(null)
const insightsBusy = ref(false)

const output = reactive({
  open: false, tab: 'stdout',
  stdout: '', stderr: '', status: '', meta: '',
})
const outputHeight = ref(220)
const diagnostics = ref([])
const hints = ref([])
const running = ref(false)
const saveState = ref('')
const lastOutputPreview = ref('')

const wsForm = reactive({ name: '', description: '', language: 'python', with_entry: true })
const fileForm = reactive({ path: '' })
const judgeForm = reactive({
  title: '未命名题目', ignore_whitespace: true,
  testcases: [{ stdin: '', expected: '', enabled: true }],
})
const judgeResult = ref(null)

const analysis = ref(null)
const runHistory = ref([])
const runStats = ref(null)
const versions = ref([])
const diffData = ref(null)
const diffTarget = ref(null)

const comments = ref([])
const unresolvedComments = ref(0)
const newCommentLine = ref(1)
const newCommentText = ref('')
const replyTo = ref(null)
const replyText = ref('')

const aiStatus = ref(null)
const aiInstruction = ref('')
const aiResult = ref('')
const aiSource = ref('')
const aiIsCode = ref(false)
const aiBusy = ref(false)

const sectionfindingsPlaceholder = null
const secretFindings = ref([])

const snippets = ref([])
const snippetQuery = ref('')
const snippetTagFilter = ref('')
const snippetTags = ref([])
const snippetCount = ref(0)
const leaderboard = ref([])

// ===== F669 片段收藏夹分组 =====
const snippetFolders = ref([])
const snippetFolderFilter = ref('')

// ===== F670 行高 / 字距（滑杆 + localStorage + Compartment 重配）=====
const lineHeight = ref(Number(localStorage.getItem('code-lh') || 1.65))
const letterSpacing = ref(Number(localStorage.getItem('code-ls') || 0))

// ===== F671 输出内查找 =====
const outFind = reactive({ open: false, q: '', idx: 0 })
const outFindInput = ref(null)

// ===== F673 行书签（localStorage）=====
const bookmarks = ref(loadJson('code-bookmarks', {}))
const showBracePanel = ref(false)

// ===== F674 最近打开文件 =====
const recentFiles = ref(loadJson('code-recent', []))

// ===== F675 括号 / 引号未闭合提示 =====
const braceIssues = ref([])
let braceTimer = null

// ===== F676 运行参数预设 =====
const showRunCfg = ref(false)
const runPresets = ref([])
const activePresetId = ref(Number(localStorage.getItem('code-preset') || 0))
const runCfgMap = ref(loadJson('code-runcfg', {}))

// ===== F677 代码统计卡 =====
const showStatsCard = ref(false)
const statsCard = ref(null)
const statsLoading = ref(false)

// ===== F678 控制台风格输出 =====
const consoleMode = ref(localStorage.getItem('code-console') !== '0')

// ===== F680 每日一题站内提醒 =====
const dailyInfo = ref(null)

function loadJson(key, fallback) {
  try {
    const v = JSON.parse(localStorage.getItem(key))
    return v === null || v === undefined ? fallback : v
  } catch (e) {
    return fallback
  }
}

const aiActions = [
  { key: 'explain', label: '解释代码', icon: '📖' },
  { key: 'find_bugs', label: '找 Bug', icon: '🐞' },
  { key: 'refactor', label: '重构', icon: '🛠' },
  { key: 'tests', label: '生成测试', icon: '🧪' },
  { key: 'comment', label: '加注释', icon: '💬' },
  { key: 'review', label: '代码审查', icon: '🔍' },
  { key: 'translate', label: '翻译语言', icon: '🌐' },
  { key: 'reverse_question', label: '反向出题', icon: '❓' },
]

// ===== 计算属性 =====
const filteredTree = computed(() => {
  if (!fileQuery.value.trim()) return tree.value
  const q = fileQuery.value.toLowerCase()
  const walk = (nodes) => {
    const out = []
    for (const n of nodes) {
      if (n.type === 'dir') {
        const kids = walk(n.children || [])
        if (kids.length) out.push({ ...n, children: kids })
      } else if (n.name.toLowerCase().includes(q) || n.path.toLowerCase().includes(q)) {
        out.push(n)
      }
    }
    return out
  }
  return walk(tree.value)
})

const runtimesForLang = computed(() => {
  const f = activeFile.value
  if (!f) return null
  return runtimes.value[f.language] || null
})

const canRun = computed(() => Boolean(activeFile.value && runtimesForLang.value?.available))

const editorLines = computed(() => (code.value || '').split('\n').length)

const outputTabs = computed(() => {
  const t = [
    { key: 'stdout', label: '标准输出' },
    { key: 'stderr', label: '错误输出', count: output.stderr ? 1 : undefined },
    { key: 'diag', label: '诊断', count: diagnostics.value.length || undefined },
  ]
  if (hints.value.length) t.push({ key: 'hint', label: '建议', count: hints.value.length })
  t.push({ key: 'judge', label: '判题' })
  return t
})

const anyDrawerOpen = computed(() => Boolean(drawer.value || graphDrawer.value || commentDrawer.value))

const maxLangCount = computed(() => {
  if (!runStats.value?.by_language?.length) return 1
  return Math.max(...runStats.value.by_language.map((x) => x.n), 1)
})

const availableRuntimeCount = computed(() =>
  Object.values(runtimes.value).filter((r) => r.available).length
)

// ===== F669/F671/F672/F673/F676/F677/F678 计算属性 =====
const currentBookmarks = computed(() => bookmarks.value[String(activeFileId.value)] || [])
const langKey = computed(() => activeFile.value?.language || 'python')
const langPresets = computed(() => runPresets.value.filter((p) => p.language === langKey.value))
const activePreset = computed(() =>
  runPresets.value.find((p) => p.id === activePresetId.value) || null
)
const enabledCaseCount = computed(() =>
  judgeForm.testcases.filter((c) => c.enabled !== false).length
)
/** 按语言隔离的运行参数（stdin / args / timeout） */
const runCfg = computed(() => runCfgMap.value[langKey.value] || { stdin: '', args: '', timeout: 5 })
const outputPlainText = computed(() => (output.tab === 'stderr' ? output.stderr : output.stdout))
const outMatchCount = computed(() => {
  const q = outFind.q
  if (!q) return 0
  const hay = outputPlainText.value.toLowerCase()
  const needle = q.toLowerCase()
  if (!needle) return 0
  let n = 0
  let at = hay.indexOf(needle)
  while (at !== -1 && n < 1000) {
    n += 1
    at = hay.indexOf(needle, at + Math.max(1, needle.length))
  }
  return n
})
/** 输出分段：ANSI 简化上色（F678）+ 查找高亮（F671） */
const outSegs = computed(() =>
  buildSegments(outputPlainText.value, outFind.q, outFind.idx, consoleMode.value)
)

// ===== 方法 =====
function pct(v) { return ((v || 0) * 100).toFixed(1) + '%' }
function fmtTime(s) { return s ? new Date(s).toLocaleString('zh-CN', { hour12: false }) : '' }

function statusColor(s) {
  return s === 'ok' ? 'text-emerald-600' : s === 'timeout' ? 'text-amber-600' : s === 'unavailable' ? 'text-sky-600' : 'text-rose-600'
}
function statusLabel(s) {
  return { ok: '成功', error: '错误', timeout: '超时', memory: '内存超限', rejected: '已拦截', unavailable: '环境不可用' }[s] || s
}
function statusTagClass(s) {
  return {
    ok: 'bg-emerald-100 text-emerald-700',
    error: 'bg-rose-100 text-rose-700',
    timeout: 'bg-amber-100 text-amber-700',
    rejected: 'bg-rose-100 text-rose-700',
    unavailable: 'bg-sky-100 text-sky-700',
    memory: 'bg-orange-100 text-orange-700',
  }[s] || 'bg-slate-100 text-ink-600'
}
function scoreColor(s) {
  return s >= 90 ? 'text-emerald-600' : s >= 70 ? 'text-amber-600' : 'text-rose-600'
}
function barColor(s) {
  return s >= 90 ? 'bg-emerald-500' : s >= 70 ? 'bg-amber-500' : 'bg-rose-500'
}
function priorityClass(p) {
  return p === 'high' ? 'bg-rose-100 text-rose-700' : p === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-ink-600'
}
function heatClass(n) {
  if (!n) return 'bg-slate-100'
  if (n < 3) return 'bg-emerald-200'
  if (n < 8) return 'bg-emerald-400'
  if (n < 16) return 'bg-emerald-500'
  return 'bg-emerald-700'
}
function verdictLabel(v) {
  return {
    accepted: '通过', wrong_answer: '答案错误', time_limit: '超时',
    runtime_error: '运行错误', compile_error: '编译错误', unavailable: '环境不可用', pending: '等待中',
  }[v] || v
}
function verdictClass(v) {
  return v === 'accepted' ? 'bg-emerald-100 text-emerald-700' : v === 'pending' ? 'bg-slate-100 text-ink-600' : 'bg-rose-100 text-rose-700'
}

// ============================================================
// F678 控制台风格输出：ANSI 转义的简化正则解析（零第三方依赖）
// ============================================================
const ANSI_RE = /\x1b\[([0-9;]*)m/g
const ANSI_FG = {
  30: '#64748b', 31: '#f87171', 32: '#4ade80', 33: '#facc15',
  34: '#60a5fa', 35: '#c084fc', 36: '#22d3ee', 37: '#e2e8f0',
  90: '#94a3b8', 91: '#fca5a5', 92: '#86efac', 93: '#fde047',
  94: '#93c5fd', 95: '#d8b4fe', 96: '#67e8f9', 97: '#f8fafc',
}
const ANSI_BG = {
  40: '#1e293b', 41: '#7f1d1d', 42: '#14532d', 43: '#713f12',
  44: '#1e3a8a', 45: '#581c87', 46: '#164e64', 47: '#334155',
}

/** 把带 ANSI SGR 的文本解析成 [{text, style}]（只支持常用子集，够渲染控制台输出） */
function parseAnsi(text) {
  const out = []
  if (!text) return out
  const st = { color: '', background: '', fontWeight: '', textDecoration: '' }
  const push = (from, to) => {
    if (to > from) out.push({ text: text.slice(from, to), style: { ...st } })
  }
  let last = 0
  let m
  ANSI_RE.lastIndex = 0
  while ((m = ANSI_RE.exec(text))) {
    push(last, m.index)
    const codes = (m[1] || '0').split(';')
    for (let i = 0; i < codes.length; i += 1) {
      const n = parseInt(codes[i], 10)
      if (Number.isNaN(n)) continue
      if (n === 0) {
        st.color = ''; st.background = ''; st.fontWeight = ''; st.textDecoration = ''
      } else if (n === 1) st.fontWeight = '700'
      else if (n === 22) st.fontWeight = ''
      else if (n === 4) st.textDecoration = 'underline'
      else if (n === 24) st.textDecoration = ''
      else if (n === 39) st.color = ''
      else if (n === 49) st.background = ''
      else if (n === 38 || n === 48) i += 2 // 256/truecolor 扩展：跳过参数
      else if (ANSI_FG[n]) st.color = ANSI_FG[n]
      else if (ANSI_BG[n]) st.background = ANSI_BG[n]
    }
    last = ANSI_RE.lastIndex
  }
  push(last, text.length)
  return out
}

/** 分段：先按 ANSI 切色块，再按查找命中把色块二次切开（F671 高亮 + F678 上色） */
function buildSegments(text, q, activeIdx, dark) {
  if (!text) return []
  const base = dark ? parseAnsi(text) : [{ text, style: {} }]
  const apply = (seg, hit) => {
    if (!hit) return { text: seg.text, style: seg.style, hit: 0 }
    return {
      text: seg.text,
      hit,
      style: {
        background: hit === 2 ? '#f59e0b' : '#fde047',
        color: '#0f172a',
        fontWeight: hit === 2 ? '700' : (seg.style.fontWeight || ''),
        textDecoration: seg.style.textDecoration || '',
      },
    }
  }
  if (!q) return base.map((s) => apply(s, 0))
  const hay = text.toLowerCase()
  const needle = q.toLowerCase()
  if (!needle) return base.map((s) => apply(s, 0))
  const ranges = []
  let at = hay.indexOf(needle)
  while (at !== -1 && ranges.length < 1000) {
    ranges.push([at, at + needle.length])
    at = hay.indexOf(needle, at + Math.max(1, needle.length))
  }
  if (!ranges.length) return base.map((s) => apply(s, 0))
  const mark = new Uint8Array(text.length)
  ranges.forEach(([rs, re], r) => {
    const v = r === activeIdx ? 2 : 1
    for (let k = rs; k < re && k < text.length; k += 1) mark[k] = v
  })
  const out = []
  let offset = 0
  for (const seg of base) {
    let start = 0
    let cur = offset < mark.length ? mark[offset] : 0
    for (let i = 1; i <= seg.text.length; i += 1) {
      const next = i < seg.text.length ? mark[offset + i] : -1
      if (next !== cur || i === seg.text.length) {
        const piece = seg.text.slice(start, i)
        if (piece) out.push(apply({ text: piece, style: seg.style }, cur))
        start = i
        if (next !== -1) cur = next
      }
    }
    offset += seg.text.length
  }
  return out
}

// ============================================================
// F670 行高 / 字距：接 CodeEditor 既有 Compartment 重配机制
// （不在组件内部改代码，用 appendConfig 追加自己的分区）
// ============================================================
const typoComp = new Compartment()
let typoView = null

function typoTheme() {
  return EditorView.theme({
    '.cm-scroller': {
      lineHeight: String(lineHeight.value),
      letterSpacing: `${letterSpacing.value}px`,
    },
  })
}

function applyTypography() {
  const v = editorRef.value?.raw?.()
  if (!v) return
  try {
    if (typoView !== v) {
      typoView = v
      v.dispatch({ effects: StateEffect.appendConfig.of(typoComp.of(typoTheme())) })
    } else {
      v.dispatch({ effects: typoComp.reconfigure(typoTheme()) })
    }
  } catch (e) { /* 编辑器销毁瞬间忽略 */ }
}

// ============================================================
// F673 行书签：自定义 gutter（点行号旁标记）+ 侧栏跳转
// ============================================================
const bmEffect = StateEffect.define()
const bmField = StateField.define({
  create: () => new Set(),
  update(val, tr) {
    for (const e of tr.effects) {
      if (e.is(bmEffect)) return new Set(e.value)
    }
    return val
  },
})

class BookMarkDot extends GutterMarker {
  toDOM() {
    const el = document.createElement('span')
    el.textContent = '●'
    el.className = 'cm-bookmark-dot'
    return el
  }
}

const bmGutter = gutter({
  class: 'cm-bookmark-gutter',
  lineMarker: (view, line) =>
    view.state.field(bmField).has(line.number) ? new BookMarkDot() : null,
  domEventHandlers: {
    mousedown: (view, line) => {
      toggleBookmark(line.number)
      return true
    },
  },
})

function ensureBookmarkGutter(view) {
  try {
    if (!view.state.field(bmField, false)) {
      view.dispatch({ effects: StateEffect.appendConfig.of([bmField, bmGutter]) })
    }
    syncBookmarks()
  } catch (e) { /* ignore */ }
}

function syncBookmarks() {
  const v = editorRef.value?.raw?.()
  if (!v || !v.state.field(bmField, false)) return
  v.dispatch({ effects: bmEffect.of([...currentBookmarks.value]) })
}

function toggleBookmark(line) {
  if (!activeFileId.value || !line) return
  const key = String(activeFileId.value)
  const cur = new Set(bookmarks.value[key] || [])
  const added = !cur.has(line)
  if (added) cur.add(line)
  else cur.delete(line)
  bookmarks.value = { ...bookmarks.value, [key]: [...cur].sort((a, b) => a - b) }
  localStorage.setItem('code-bookmarks', JSON.stringify(bookmarks.value))
  syncBookmarks()
  app.toastMsg?.(added ? `已加书签：第 ${line} 行` : `已移除书签：第 ${line} 行`, 'success')
}

function openBookmarks() {
  drawer.value = 'bookmark'
}

function linePreview(line) {
  const arr = (code.value || '').split('\n')
  return (arr[line - 1] || '').trim().slice(0, 60)
}

// ============================================================
// F674 最近打开文件
// ============================================================
function pushRecent(f) {
  if (!f) return
  const item = { id: f.id, name: f.name, path: f.path, at: Date.now() }
  recentFiles.value = [item, ...recentFiles.value.filter((x) => x.id !== item.id)].slice(0, 12)
  localStorage.setItem('code-recent', JSON.stringify(recentFiles.value))
}

function clearRecent() {
  recentFiles.value = []
  localStorage.removeItem('code-recent')
}

// ============================================================
// F675 括号 / 引号未闭合行提示（轻量自查，忽略字符串与注释）
// ============================================================
function scanUnbalanced(src) {
  const lines = (src || '').split('\n')
  const issues = []
  const stack = []
  const openOf = { ')': '(', ']': '[', '}': '{' }
  const quotes = ["'", '"', '`']
  let inBlock = false
  for (let li = 0; li < lines.length && issues.length < 60; li += 1) {
    const line = lines[li]
    let i = 0
    let inStr = null
    while (i < line.length) {
      const c = line[i]
      if (inBlock) {
        if (c === '*' && line[i + 1] === '/') { inBlock = false; i += 2; continue }
        i += 1
        continue
      }
      if (inStr) {
        if (c === '\\') { i += 2; continue }
        if (c === inStr) inStr = null
        i += 1
        continue
      }
      if (c === '/' && line[i + 1] === '*') { inBlock = true; i += 2; continue }
      if (c === '/' && line[i + 1] === '/') break
      if (c === '#') break
      if (quotes.includes(c)) { inStr = c; i += 1; continue }
      if (c === '(' || c === '[' || c === '{') {
        stack.push({ ch: c, line: li + 1, col: i + 1 })
        i += 1
        continue
      }
      if (c === ')' || c === ']' || c === '}') {
        if (stack.length && stack[stack.length - 1].ch === openOf[c]) stack.pop()
        else issues.push({ line: li + 1, col: i + 1, message: `多余的「${c}」（找不到配对的开括号）` })
        i += 1
        continue
      }
      i += 1
    }
    if (inStr && inStr !== '`') {
      issues.push({ line: li + 1, col: Math.max(1, line.length), message: `行尾仍在 ${inStr} 引号内（字符串未闭合）` })
    }
  }
  for (const st of stack) {
    if (issues.length >= 60) break
    issues.push({ line: st.line, col: st.col, message: `「${st.ch}」未闭合（缺少右括号）` })
  }
  return issues.slice(0, 60)
}

function scheduleBraceCheck() {
  clearTimeout(braceTimer)
  braceTimer = setTimeout(() => checkBrackets(false), 500)
}

function checkBrackets(openPanel) {
  braceIssues.value = scanUnbalanced(editorRef.value?.getValue?.() ?? code.value)
  if (openPanel) showBracePanel.value = true
}

// ============================================================
// F676 运行参数预设
// ============================================================
function ensureRunCfg() {
  const k = langKey.value
  if (!runCfgMap.value[k]) {
    runCfgMap.value = { ...runCfgMap.value, [k]: { stdin: '', args: '', timeout: 5 } }
  }
  return runCfgMap.value[k]
}

async function loadRunPresets() {
  try {
    const res = await codeApi.runPresets()
    runPresets.value = res.items || []
  } catch (e) { /* ignore */ }
}

function openRunCfg() {
  ensureRunCfg()
  showRunCfg.value = true
  loadRunPresets()
}

function choosePreset(p) {
  activePresetId.value = p ? p.id : 0
  localStorage.setItem('code-preset', String(activePresetId.value))
  if (p) {
    const cfg = ensureRunCfg()
    cfg.stdin = p.stdin || ''
    cfg.args = (p.args || []).join(' ')
    cfg.timeout = p.timeout || 5
  }
}

function choosePresetById(id) {
  choosePreset(runPresets.value.find((p) => p.id === id) || null)
}

async function saveRunPreset() {
  if (!activeFile.value) return
  const fallback = `${langKey.value} 预设`
  const name = window.prompt('预设名称（按语言保存 stdin / 参数 / 超时）',
    activePreset.value && activePreset.value.language === langKey.value ? activePreset.value.name : fallback)
  if (!name) return
  const cfg = ensureRunCfg()
  const payload = {
    language: langKey.value,
    name,
    stdin: cfg.stdin || '',
    args: cfg.args || '',
    timeout: Number(cfg.timeout) || 5,
  }
  try {
    const res = activePreset.value && activePreset.value.language === langKey.value
      ? await codeApi.updateRunPreset(activePreset.value.id, payload)
      : await codeApi.createRunPreset(payload)
    await loadRunPresets()
    activePresetId.value = res.id
    localStorage.setItem('code-preset', String(res.id))
    app.toastMsg?.('预设已保存', 'success')
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || '保存预设失败', 'error')
  }
}

async function removeRunPreset() {
  if (!activePreset.value) return
  try {
    await codeApi.deleteRunPreset(activePreset.value.id)
    choosePreset(null)
    await loadRunPresets()
    app.toastMsg?.('预设已删除', 'success')
  } catch (e) {
    app.toastMsg?.('删除失败', 'error')
  }
}

// ============================================================
// F677 代码统计卡
// ============================================================
async function openStatsCard() {
  showStatsCard.value = true
  if (!activeFile.value) { statsCard.value = null; return }
  statsLoading.value = true
  try {
    const res = await codeApi.codeStats({
      language: activeFile.value.language,
      code: editorRef.value?.getValue() ?? code.value,
    })
    statsCard.value = res.card || null
  } catch (e) {
    app.toastMsg?.('统计失败', 'error')
  } finally {
    statsLoading.value = false
  }
}

// ============================================================
// F671 输出内查找 + F678 控制台开关
// ============================================================
function toggleOutFind() {
  outFind.open = !outFind.open
  if (outFind.open) {
    nextTick(() => {
      const el = outFindInput.value
      if (el && el.focus) el.focus()
    })
  }
}

function moveFind(step) {
  const n = outMatchCount.value
  if (!n) return
  outFind.idx = (outFind.idx + step + n) % n
  nextTick(() => {
    const el = document.querySelector('pre.cm-out-pre [data-active="1"]')
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}

function toggleConsole() {
  consoleMode.value = !consoleMode.value
  localStorage.setItem('code-console', consoleMode.value ? '1' : '0')
  app.toastMsg?.(consoleMode.value ? '已开启控制台风格（ANSI 颜色）' : '已切换为纯文本输出', 'success')
}

// ============================================================
// F680 每日一题站内提醒
// ============================================================
async function checkDailyReminder() {
  try {
    const st = await codeApi.dailyReminder()
    dailyInfo.value = st
    if (st && !st.solved && !localStorage.getItem(`code-daily-ack-${st.date}`)) {
      await codeApi.notifyDailyReminder()
      localStorage.setItem(`code-daily-ack-${st.date}`, '1')
      app.toastMsg?.(`📬 每日一题提醒：《${st.title}》还没完成，已发站内通知`, 'info')
    }
  } catch (e) { /* ignore */ }
}

function goDaily() {
  if (dailyInfo.value && !dailyInfo.value.solved) {
    app.toastMsg?.(`今日一题《${dailyInfo.value.title}》（${dailyInfo.value.difficulty}）待完成`, 'info')
  } else if (dailyInfo.value) {
    app.toastMsg?.('今日一题已完成 ✓', 'success')
  }
  router.push('/code/learn')
}

// ============================================================
// F669 片段收藏夹分组（前端）
// ============================================================
async function toggleSnippetFav(s) {
  try {
    const res = await codeApi.updateSnippet(s.id, { is_favorite: !s.is_favorite })
    s.is_favorite = res.is_favorite
    await loadSnippets()
    app.toastMsg?.(s.is_favorite ? '已收藏 ★' : '已取消收藏', 'success')
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || '操作失败', 'error')
  }
}

async function moveSnippetToFolder(s) {
  const cur = window.prompt('归入收藏夹分组（留空 = 移出分组）', s.folder || '')
  if (cur === null) return
  const folder = cur.trim().slice(0, 60)
  try {
    await codeApi.updateSnippet(s.id, { folder })
    await loadSnippets()
    app.toastMsg?.(folder ? `已归入「${folder}」` : '已移出分组', 'success')
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || '操作失败', 'error')
  }
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('code-theme', theme.value)
}
function toggleWrap() {
  lineWrapping.value = !lineWrapping.value
  localStorage.setItem('code-wrap', lineWrapping.value ? '1' : '0')
}

function openOutput(tab) {
  output.open = true
  if (tab) output.tab = tab
}

function closeDrawers() {
  drawer.value = ''
  graphDrawer.value = false
  commentDrawer.value = false
}

// ---- L4：TODO 聚合 ----
async function openTodos(tag = '') {
  showTodos.value = true
  todoTag.value = tag
  todosBusy.value = true
  try {
    const params = {}
    // 当前在工作区里就只看这个工作区，否则看全部
    if (activeWsId.value) params.workspace = activeWsId.value
    if (tag) params.tag = tag
    todosData.value = await codeApi.todos(params)
  } catch (e) {
    app.toastMsg?.('扫描 TODO 失败')
  } finally {
    todosBusy.value = false
  }
}

function jumpToTodo(item) {
  // 打开对应文件并跳到行号
  openFile({ id: item.file_id }).then(() => {
    showTodos.value = false
    nextTick(() => editorRef.value?.goToLine?.(item.line))
  }).catch(() => {
    app.toastMsg?.('该文件可能不在当前工作区')
  })
}

// ---- L4：工程洞察 ----
async function openInsights() {
  showInsights.value = true
  insightsBusy.value = true
  try {
    insightsData.value = await codeApi.insights(activeWsId.value || null)
  } catch (e) {
    app.toastMsg?.('加载洞察失败')
  } finally {
    insightsBusy.value = false
  }
}

// ---- 初始化 ----
async function loadMeta() {
  try {
    const [langRes, rtRes, aiRes] = await Promise.all([
      codeApi.languages(), codeApi.runtimes(), codeApi.aiStatus(),
    ])
    languages.value = langRes.languages || []
    runtimes.value = Object.fromEntries((rtRes.runtimes || []).map((r) => [r.key, r]))
    aiStatus.value = aiRes
  } catch (e) {
    app.toastMsg?.('加载环境信息失败：' + (e?.message || e))
  }
}

async function loadWorkspaces() {
  const res = await codeApi.workspaces({ include_archived: true })
  workspaces.value = res.items || []
  if (!activeWsId.value && workspaces.value.length) {
    activeWsId.value = workspaces.value[0].id
    await loadWorkspace(activeWsId.value)
  }
}

async function loadWorkspace(id) {
  const res = await codeApi.workspace(id)
  activeWs.value = res
  const treeRes = await codeApi.fileTree(id)
  tree.value = treeRes.tree || []
}

async function onSwitchWorkspace() {
  if (!activeWsId.value) {
    activeWs.value = null
    tree.value = []
    return
  }
  await loadWorkspace(activeWsId.value)
  tabs.value = []
  activeFileId.value = null
  activeFile.value = null
  code.value = ''
}

async function doCreateWs() {
  try {
    const res = await codeApi.createWorkspace({ ...wsForm })
    showWsModal.value = false
    wsForm.name = ''
    wsForm.description = ''
    await loadWorkspaces()
    activeWsId.value = res.id
    await loadWorkspace(res.id)
    app.toastMsg?.('工作区已创建')
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || e?.message || '创建失败')
  }
}

async function openWsSettings() {
  if (!activeWs.value) return
  const ws = activeWs.value
  const name = window.prompt('工作区名称', ws.name)
  if (name === null) return
  const icon = window.prompt('图标 emoji', ws.icon || '📁')
  if (icon === null) return
  try {
    await codeApi.updateWorkspace(ws.id, { name, icon })
    await loadWorkspaces()
    await loadWorkspace(ws.id)
    app.toastMsg?.('已更新')
  } catch (e) {
    app.toastMsg?.('更新失败')
  }
}

async function doCloneWs() {
  if (!activeWs.value) return
  const res = await codeApi.cloneWorkspace(activeWs.value.id)
  await loadWorkspaces()
  app.toastMsg?.(`已克隆为「${res.name}」`)
}

async function doExportZip() {
  if (!activeWs.value) return
  try {
    const blob = await codeApi.exportZip({ workspace: activeWs.value.id })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // #81 导出文件名规范化：语言_时间戳.zip
    const ext = activeFile.value?.language || activeWs.value?.name || 'project'
    const ts = new Date().toISOString().slice(0, 19).replace(/\D/g, '')
    a.download = `${(ext || 'project').replace(/[^a-z0-9]/gi, '_').toLowerCase()}_${ts}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    app.toastMsg?.('导出失败')
  }
}

// ===== #77 常用代码模板 / #62 AI 评审 =====
const reviewing = ref(false)
const TEMPLATES = {
  python: [
    ['main 入口', 'def main():\n    print("Hello, World!")\n\n\nif __name__ == "__main__":\n    main()\n'],
    ['读取文件', 'with open("data.txt", "r", encoding="utf-8") as f:\n    content = f.read()\nprint(content)\n'],
    ['快速排序', 'def quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    mid = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + mid + quicksort(right)\n'],
    ['写 CSV', 'import csv\nwith open("out.csv", "w", newline="", encoding="utf-8") as f:\n    w = csv.writer(f)\n    w.writerow(["name", "age"])\n    w.writerow(["Alice", 30])\n'],
  ],
  javascript: [
    ['main 入口', 'function main() {\n  console.log("Hello, World!");\n}\nmain();\n'],
    ['读 JSON 文件', 'const fs = require("fs");\nconst data = JSON.parse(fs.readFileSync("data.json", "utf-8"));\nconsole.log(data);\n'],
    ['数组去重', 'const uniq = (arr) => [...new Set(arr)];\nconsole.log(uniq([1, 2, 2, 3]));\n'],
  ],
  java: [
    ['main 类', 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }\n}\n'],
  ],
  cpp: [
    ['main 入口', '#include <iostream>\nusing namespace std;\nint main() {\n    cout << "Hello, World!" << endl;\n    return 0;\n}\n'],
  ],
  go: [
    ['main 包', 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, World!")\n}\n'],
  ],
}
function openTemplateMenu() {
  if (!activeFile.value) { app.toastMsg?.('先打开一个文件'); return }
  const lang = (activeFile.value.language || 'python').toLowerCase()
  const list = TEMPLATES[lang] || TEMPLATES.python
  const choice = window.prompt('插入模板（输入序号）：\n' + list.map((t, i) => `${i + 1}. ${t[0]}`).join('\n'), '1')
  const idx = parseInt(choice, 10) - 1
  if (idx >= 0 && list[idx]) {
    code.value = (code.value ? code.value + '\n\n' : '') + list[idx][1]
    app.toastMsg?.(`已插入模板：${list[idx][0]}`, 'success')
  }
}
async function doAiReview() {
  if (!activeFile.value || !code.value.trim()) { app.toastMsg?.('先打开并填写代码'); return }
  reviewing.value = true
  try {
    const r = await codeApi.aiReview({ code: code.value, language: activeFile.value.language })
    const data = r.data || r
    const msgs = [(`评审结论：${data.summary || ''}`), ...(data.comments || []).map(c => `[${c.severity}] 行${c.line}: ${c.message}`)]
    if (data.suggestions?.length) msgs.push('建议：' + data.suggestions.join('；'))
    window.alert('🤖 AI 代码评审\n\n' + msgs.join('\n'))
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || '评审失败', 'error')
  } finally {
    reviewing.value = false
  }
}

async function doCreateFile() {
  if (!activeWsId.value) return
  try {
    const res = await codeApi.createFile({ workspace: activeWsId.value, path: fileForm.path })
    showFileModal.value = false
    fileForm.path = ''
    await loadWorkspace(activeWsId.value)
    await openFile({ id: res.id })
    app.toastMsg?.('文件已创建')
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || '创建失败')
  }
}

async function openFile(node) {
  if (!node?.id) return
  // 已在标签中 → 直接切换
  const exist = tabs.value.find((t) => t.id === node.id)
  if (exist) {
    activeFileId.value = node.id
  } else {
    activeFileId.value = node.id
  }
  try {
    const res = await codeApi.file(node.id)
    activeFile.value = res
    code.value = res.content || ''
    if (!tabs.value.find((t) => t.id === res.id)) {
      tabs.value.push({
        id: res.id, name: res.name, path: res.path,
        dirty: false, language: res.language,
      })
    }
    newCommentLine.value = 1
    pushRecent(res)          // F674 最近打开
    scheduleBraceCheck()     // F675 打开即自查
    await Promise.all([loadComments(), loadVersions()])
  } catch (e) {
    app.toastMsg?.('打开失败')
  }
}

function closeTab(t) {
  const idx = tabs.value.findIndex((x) => x.id === t.id)
  if (idx < 0) return
  tabs.value.splice(idx, 1)
  if (activeFileId.value === t.id) {
    const next = tabs.value[Math.max(0, idx - 1)]
    if (next) openFile({ id: next.id })
    else { activeFileId.value = null; activeFile.value = null; code.value = '' }
  }
}

function onCodeChange(val) {
  const t = tabs.value.find((x) => x.id === activeFileId.value)
  if (t) t.dirty = true
  scheduleAutoSave()
  scheduleBraceCheck()   // F675：输入后轻量括号自查
}

let autoSaveTimer = null
function scheduleAutoSave() {
  clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => {
    // 自动保存：静默落库，不打快照（快照由 ⌘S 或手动触发）
    if (activeFileId.value) saveCurrent(true)
  }, 2500)
}

async function saveCurrent(silent = false, snapshot = false) {
  if (!activeFileId.value) return
  const id = activeFileId.value
  const content = editorRef.value?.getValue() ?? code.value
  try {
    saveState.value = 'saving'
    const res = await codeApi.updateFile(id, { content, snapshot })
    const t = tabs.value.find((x) => x.id === id)
    if (t) t.dirty = false
    if (activeFile.value && activeFile.value.id === id) {
      activeFile.value.lines = res.lines
      activeFile.value.size = res.size
    }
    saveState.value = 'saved'
    setTimeout(() => { saveState.value = '' }, 1500)
    if (!silent) app.toastMsg?.('已保存')
    if (snapshot) await loadVersions()
  } catch (e) {
    saveState.value = ''
    if (!silent) app.toastMsg?.('保存失败')
  }
}

async function doSnapshot() {
  if (!activeFileId.value) return
  const msg = window.prompt('版本说明', '手动快照')
  if (msg === null) return
  await saveCurrent(true, false)
  await codeApi.createVersion(activeFileId.value, msg || '手动快照')
  await loadVersions()
  graphDrawer.value = true
  app.toastMsg?.('快照已创建')
}

// ---- 运行 ----
async function doRun() {
  if (!activeFileId.value || running.value) return
  running.value = true
  output.open = true
  output.tab = 'stdout'
  output.stdout = '运行中…'
  output.stderr = ''
  diagnostics.value = []
  hints.value = []
  try {
    // F676：带上该语言的运行参数预设（stdin / args / timeout）
    const cfg = runCfgMap.value[activeFile.value?.language || 'python'] || null
    const payload = {
      file: activeFileId.value,
      code: editorRef.value?.getValue() ?? code.value,
      timeout: cfg && Number(cfg.timeout) ? Math.min(30, Math.max(0.5, Number(cfg.timeout))) : 5,
    }
    if (cfg && cfg.stdin) payload.stdin = cfg.stdin
    if (cfg && cfg.args && String(cfg.args).trim()) {
      payload.args = String(cfg.args).trim().split(/\s+/)
    }
    const res = await codeApi.run(payload)
    output.stdout = res.stdout || ''
    output.stderr = res.stderr || ''
    output.status = res.status
    diagnostics.value = res.diagnostics || []
    output.meta = `${statusLabel(res.status)} · ${res.duration_ms}ms${
      res.memory_kb ? ' · ' + Math.round(res.memory_kb / 1024) + 'MB' : ''
    }`
    lastOutputPreview.value = (res.stdout || res.stderr || '').split('\n')[0].slice(0, 80)
    if (res.status === 'rejected') {
      output.tab = 'stderr'
      app.toastMsg?.('检测到高危操作，已拒绝执行')
    } else if (res.status === 'unavailable') {
      output.tab = 'stderr'
    } else if (res.status !== 'ok') {
      output.tab = diagnostics.value.length ? 'diag' : 'stderr'
    }
    if (res.run_id) loadHistory()
    if (res.status !== 'ok' && activeFileId.value) {
      // 顺手给一份本地重构建议
      codeApi.refactorHints({
        language: activeFile.value?.language || 'python',
        code: editorRef.value?.getValue() ?? code.value,
      }).then((r) => { hints.value = r.hints || [] }).catch(() => {})
    }
  } catch (e) {
    output.stderr = e?.response?.data?.error || e?.message || '运行失败'
    output.status = 'error'
    output.tab = 'stderr'
  } finally {
    running.value = false
  }
}

function addCase() {
  judgeForm.testcases.push({ stdin: '', expected: '', enabled: true })
}

/** F672 测试用例批量启用 / 停用 */
function setAllCases(on) {
  judgeForm.testcases.forEach((c) => { c.enabled = on })
}

function doJudge() {
  if (!activeFileId.value) return
  judgeResult.value = null
  showJudgeModal.value = true
}

async function runJudge() {
  if (!activeFileId.value) return
  showJudgeModal.value = false
  running.value = true
  output.open = true
  output.tab = 'judge'
  try {
    const res = await codeApi.judge({
      language: activeFile.value?.language || 'python',
      code: editorRef.value?.getValue() ?? code.value,
      title: judgeForm.title,
      ignore_whitespace: judgeForm.ignore_whitespace,
      testcases: judgeForm.testcases.filter((c) => c.expected !== '' || c.stdin !== ''),
    })
    judgeResult.value = res
    await loadLeaderboard()
    app.toastMsg?.(`判题完成：${verdictLabel(res.verdict)}（${res.passed}/${res.total}）`)
  } catch (e) {
    app.toastMsg?.(e?.response?.data?.error || '判题失败')
  } finally {
    running.value = false
  }
}

// ---- 输出操作 ----
function currentOutputText() {
  if (output.tab === 'stdout') return output.stdout
  if (output.tab === 'stderr') return output.stderr
  if (output.tab === 'diag') return JSON.stringify(diagnostics.value, null, 2)
  if (output.tab === 'hint') return JSON.stringify(hints.value, null, 2)
  if (output.tab === 'judge') return JSON.stringify(judgeResult.value, null, 2)
  return ''
}

async function copyOutput() {
  await copyText(currentOutputText())
  app.toastMsg?.('已复制')
}

function downloadOutput() {
  const blob = new Blob([currentOutputText()], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `output-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

async function copyText(t) {
  try {
    await navigator.clipboard.writeText(t || '')
    app.toastMsg?.('已复制到剪贴板')
  } catch (e) {
    app.toastMsg?.('复制失败，请手动选择')
  }
}

// ---- 版本 ----
async function loadVersions() {
  if (!activeFileId.value) return
  try {
    const res = await codeApi.versions(activeFileId.value)
    versions.value = res.items || []
  } catch (e) { /* ignore */ }
}

async function viewDiff(vid) {
  diffTarget.value = vid
  try {
    const res = await codeApi.versionDiff(activeFileId.value, { from: vid })
    diffData.value = res
  } catch (e) {
    app.toastMsg?.('比对失败')
  }
}

async function doRollback(v) {
  if (!window.confirm(`确认回滚到「${v.message}」？当前内容会先存为快照。`)) return
  try {
    const res = await codeApi.rollback(activeFileId.value, v.id)
    code.value = res.content || ''
    await loadVersions()
    app.toastMsg?.('已回滚')
  } catch (e) {
    app.toastMsg?.('回滚失败')
  }
}

// ---- 评论 ----
async function loadComments() {
  if (!activeFileId.value) return
  try {
    const res = await codeApi.comments(activeFileId.value)
    comments.value = res.items || []
    unresolvedComments.value = res.unresolved || 0
  } catch (e) { /* ignore */ }
}

async function addComment() {
  if (!newCommentText.value.trim()) return
  try {
    await codeApi.createComment(activeFileId.value, {
      line: newCommentLine.value || 1,
      content: newCommentText.value,
    })
    newCommentText.value = ''
    await loadComments()
  } catch (e) {
    app.toastMsg?.('发表失败')
  }
}

async function sendReply(c) {
  if (!replyText.value.trim()) return
  try {
    await codeApi.createComment(activeFileId.value, {
      line: c.line, content: replyText.value, parent: c.id,
    })
    replyText.value = ''
    replyTo.value = null
    await loadComments()
  } catch (e) {
    app.toastMsg?.('回复失败')
  }
}

async function toggleResolve(c) {
  await codeApi.resolveComment(activeFileId.value, c.id)
  await loadComments()
}

async function removeComment(c) {
  await codeApi.deleteComment(activeFileId.value, c.id)
  await loadComments()
}

// ---- 分析 ----
async function loadAnalysis() {
  if (!activeFile.value) return
  const payload = {
    language: activeFile.value.language,
    code: editorRef.value?.getValue() ?? code.value,
  }
  try {
    const [an, ol] = await Promise.all([codeApi.analyze(payload), codeApi.outline(payload)])
    analysis.value = { ...an, outline: ol.outline || [] }
    diagnostics.value = (an.issues || []).map((i) => ({ ...i, type: i.rule }))
  } catch (e) {
    app.toastMsg?.('分析失败')
  }
}

async function loadQuality() {
  if (!activeFile.value) return
  try {
    const res = await codeApi.quality({
      language: activeFile.value.language,
      code: editorRef.value?.getValue() ?? code.value,
    })
    if (!analysis.value) analysis.value = { metrics: res.metrics, complexity: {}, issues: res.issues }
    else {
      analysis.value.metrics = res.metrics
      analysis.value.issues = res.issues
    }
    app.toastMsg?.(`质量评分 ${res.score}（${res.grade}）`)
  } catch (e) {
    app.toastMsg?.('评分失败')
  }
}

async function doComplexity() {
  if (!activeFile.value) return
  try {
    const res = await codeApi.complexity({
      language: activeFile.value.language,
      code: editorRef.value?.getValue() ?? code.value,
    })
    if (!analysis.value) analysis.value = { metrics: {}, complexity: res, issues: [] }
    else analysis.value.complexity = res
    drawer.value = 'analysis'
    app.toastMsg?.(`时间复杂度估算：${res.big_o}`)
  } catch (e) {
    app.toastMsg?.('分析失败')
  }
}

async function doDuplicateCheck() {
  if (!activeFile.value || !activeWsId.value) return
  try {
    const res = await codeApi.similarity({
      workspace: activeWsId.value,
      language: activeFile.value.language,
      code: editorRef.value?.getValue() ?? code.value,
    })
    if (!res.matches?.length) {
      app.toastMsg?.('未发现相似文件')
      return
    }
    const top = res.matches[0]
    app.toastMsg?.(`最相似：${top.path}（${top.percent}）—— ${top.verdict}`)
  } catch (e) {
    app.toastMsg?.('查重失败')
  }
}

async function doSecretScan() {
  if (!activeFile.value) return
  try {
    const res = await codeApi.secretScan({
      language: activeFile.value.language,
      code: editorRef.value?.getValue() ?? code.value,
    })
    secretFindings.value = res.findings || []
    openOutput('diag')
    diagnostics.value = (res.findings || []).map((f) => ({
      severity: f.severity === 'high' ? 'error' : 'warning',
      type: f.type,
      message: `第 ${f.line} 行：${f.masked} —— ${f.advice}`,
      line: f.line,
      column: 1,
    }))
    if (res.count) app.toastMsg?.(`发现 ${res.count} 处敏感信息（风险：${res.risk}）`)
    else app.toastMsg?.('未发现敏感信息')
  } catch (e) {
    app.toastMsg?.('扫描失败')
  }
}

// ---- AI ----
async function runAi(action) {
  if (!activeFile.value || aiBusy.value) return
  aiBusy.value = true
  aiResult.value = ''
  try {
    const codeText = editorRef.value?.getValue() ?? code.value
    let res
    if (action === 'generate') {
      res = await codeApi.aiGenerate({
        language: activeFile.value.language,
        instruction: aiInstruction.value,
      })
      aiResult.value = res.code || ''
      aiIsCode.value = true
      aiSource.value = res.source
      aiInstruction.value = ''
    } else if (action === 'chat_edit') {
      if (!aiInstruction.value.trim()) {
        app.toastMsg?.('请先在上方输入修改要求')
        aiBusy.value = false
        return
      }
      res = await codeApi.aiChatEdit({
        language: activeFile.value.language,
        code: codeText,
        instruction: aiInstruction.value,
      })
      aiResult.value = res.code || ''
      aiSource.value = res.source || 'local'
      aiIsCode.value = true
    } else if (action === 'error_explain') {
      res = await codeApi.aiErrorExplain({
        language: activeFile.value.language,
        code: codeText,
        error: output.stderr || '',
        file: activeFileId.value,
      })
      aiResult.value = res.result || ''
      aiSource.value = res.source
      aiIsCode.value = false
    } else if (action === 'translate') {
      const target = window.prompt('翻译成哪种语言？', 'javascript')
      if (!target) { aiBusy.value = false; return }
      res = await codeApi.aiTransform({
        action, language: activeFile.value.language, code: codeText, target,
      })
      aiResult.value = res.result || ''
      aiSource.value = res.source
      aiIsCode.value = true
    } else {
      res = await codeApi.aiTransform({
        action, language: activeFile.value.language, code: codeText,
      })
      aiResult.value = res.result || ''
      aiSource.value = res.source
      aiIsCode.value = ['refactor', 'tests', 'comment'].includes(action)
    }
    if (res.note) app.toastMsg?.(res.note)
  } catch (e) {
    aiResult.value = e?.response?.data?.error || e?.message || 'AI 调用失败'
    aiIsCode.value = false
  } finally {
    aiBusy.value = false
  }
}

async function aiTool(kind) {
  aiBusy.value = true
  try {
    if (kind === 'regex') {
      const desc = window.prompt('描述你要匹配的内容', '匹配中国大陆手机号')
      if (!desc) { aiBusy.value = false; return }
      const res = await codeApi.aiRegex({ instruction: desc, language: activeFile.value?.language || 'python' })
      aiResult.value = res.result
      aiIsCode.value = false
    } else if (kind === 'nl2sql') {
      const desc = window.prompt('用自然语言描述你要查什么', '统计最近 7 天每天的新增用户数')
      if (!desc) { aiBusy.value = false; return }
      const schema = window.prompt('表结构（可留空）', 'users(id, name, created_at)') || ''
      const res = await codeApi.aiNl2sql({ instruction: desc, schema })
      aiResult.value = res.result
      aiIsCode.value = true
    } else if (kind === 'learning_path') {
      const goal = window.prompt('你的学习目标', '掌握动态规划')
      if (!goal) { aiBusy.value = false; return }
      const res = await codeApi.aiLearningPath({ goal })
      aiResult.value = res.result
      aiIsCode.value = false
    } else if (kind === 'testdata') {
      if (!activeFile.value) { aiBusy.value = false; return }
      const res = await codeApi.aiTransform({
        action: 'testdata',
        language: activeFile.value.language,
        code: editorRef.value?.getValue() ?? code.value,
      })
      aiResult.value = res.result
      aiIsCode.value = false
    }
    aiSource.value = res?.source || 'local'
    drawer.value = 'ai'
  } catch (e) {
    app.toastMsg?.('调用失败')
  } finally {
    aiBusy.value = false
  }
}

function insertAiResult() {
  editorRef.value?.insertText(aiResult.value)
  app.toastMsg?.('已插入')
}

async function replaceWithAiResult() {
  if (!activeFileId.value) return
  if (!window.confirm('用当前结果覆盖文件内容？原内容会存为快照。')) return
  try {
    const res = await codeApi.aiApply(activeFileId.value, {
      code: aiResult.value, message: 'AI 修改前快照',
    })
    if (res.file) {
      code.value = res.file.content
      activeFile.value = { ...activeFile.value, ...res.file }
    }
    await loadVersions()
    app.toastMsg?.('已替换')
  } catch (e) {
    app.toastMsg?.('替换失败')
  }
}

async function onEditorReady(view) {
  // Ctrl+Enter 运行 / Ctrl+S 保存 由外层接管
  view.dom.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      doRun()
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault()
      saveCurrent(false, true)
    }
  })
}

// ---- 历史 ----
async function loadHistory() {
  try {
    const [h, s] = await Promise.all([codeApi.runHistory({ limit: 30 }), codeApi.runStats()])
    runHistory.value = h.items || []
    runStats.value = s
  } catch (e) { /* ignore */ }
}

async function loadRunDetail(id) {
  try {
    const r = await codeApi.runDetail(id)
    output.open = true
    output.stdout = r.stdout || ''
    output.stderr = r.stderr || ''
    output.status = r.status
    output.meta = `${statusLabel(r.status)} · ${r.duration_ms}ms · ${fmtTime(r.created_at)}`
    diagnostics.value = r.diagnostics || []
    output.tab = r.stdout ? 'stdout' : 'stderr'
  } catch (e) {
    app.toastMsg?.('加载失败')
  }
}

async function clearHistory() {
  if (!window.confirm('清空全部运行历史？')) return
  await codeApi.clearRuns()
  await loadHistory()
  app.toastMsg?.('已清空')
}

async function loadLeaderboard() {
  try {
    const res = await codeApi.leaderboard(20)
    leaderboard.value = res.items || []
  } catch (e) { /* ignore */ }
}

// ---- 片段库 ----
async function loadSnippets() {
  try {
    const params = { limit: 60 }
    if (snippetQuery.value.trim()) params.q = snippetQuery.value.trim()
    if (snippetTagFilter.value) params.tag = snippetTagFilter.value
    // F669 按收藏夹分组筛选
    if (snippetFolderFilter.value === '__mine') params.favorite = true
    else if (snippetFolderFilter.value) params.folder = snippetFolderFilter.value
    const [res, tg, fo] = await Promise.all([
      codeApi.snippets(params), codeApi.snippetTags(), codeApi.snippetFolders(),
    ])
    snippets.value = res.items || []
    snippetTags.value = tg.tags || []
    snippetFolders.value = fo.folders || []
    snippetCount.value = snippets.value.length
  } catch (e) { /* ignore */ }
}

async function saveCurrentAsSnippet() {
  if (!activeFile.value) return
  const title = window.prompt('片段标题', activeFile.value.name)
  if (!title) return
  try {
    await codeApi.createSnippet({
      title,
      description: `来自 ${activeWs.value?.name || ''}/${activeFile.value.path}`,
      language: activeFile.value.language,
      code: editorRef.value?.getValue() ?? code.value,
      tags: [activeFile.value.language],
    })
    await loadSnippets()
    app.toastMsg?.('已存入片段库')
  } catch (e) {
    app.toastMsg?.('保存失败')
  }
}

function insertSnippet(s) {
  if (!activeFile.value) {
    app.toastMsg?.('请先打开一个文件')
    return
  }
  editorRef.value?.insertText(s.code)
  codeApi.copySnippet(s.id).catch(() => {})
  app.toastMsg?.('已插入')
}

async function copySnippetInto(s) {
  const res = await codeApi.copySnippet(s.id, true)
  await loadSnippets()
  app.toastMsg?.(`已存入我的库：${res.title}`)
}

async function removeSnippet(s) {
  if (!window.confirm(`删除片段「${s.title}」？`)) return
  await codeApi.deleteSnippet(s.id)
  await loadSnippets()
}

// ---- 分享 ----
async function doShare() {
  if (!activeFileId.value) return
  const allowRun = window.confirm('访客是否可以直接运行这段代码？\n确定 = 允许运行，取消 = 只读')
  try {
    const res = await codeApi.createShare({ file: activeFileId.value, allow_run: allowRun })
    const full = `${location.origin}${res.url}`
    await copyText(full)
    app.toastMsg?.('分享链接已复制到剪贴板')
  } catch (e) {
    app.toastMsg?.('创建分享失败')
  }
}

// ---- 生命周期 ----
onMounted(async () => {
  await loadMeta()
  await loadWorkspaces()
  await loadSnippets()
  await loadHistory()
})

onBeforeUnmount(() => {
  clearTimeout(autoSaveTimer)
})

// 抽屉互斥
watch(drawer, (v) => { if (v) { graphDrawer.value = false; commentDrawer.value = false } })
watch(graphDrawer, (v) => { if (v) { drawer.value = ''; commentDrawer.value = false } })
watch(commentDrawer, (v) => { if (v) { drawer.value = ''; graphDrawer.value = false } })
watch(fontSize, (v) => localStorage.setItem('code-font', String(v)))
watch(tabSize, (v) => localStorage.setItem('code-tab', String(v)))
</script>

<style scoped>
.td {
  padding: 6px 8px;
  color: #334155;
}
</style>
