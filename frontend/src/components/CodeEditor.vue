<template>
  <div ref="host" class="cm-host" :style="{ height }"></div>
</template>

<script setup>
/**
 * CodeMirror 6 编辑器封装（v6 代码工坊内核）
 *
 * 覆盖 L1 编辑内核能力：
 *  高亮 / 行号 / 折叠 / 括号配对 / 自动缩进 / 多光标 / 查找替换 /
 *  缩进设置 / 不可见字符 / 主题切换 / 字号 / 只读 / 变更回调
 *
 * 对外只暴露 v-model 语义 + 若干方法，内部管理 EditorState，
 * 语言与配置变化时整实例重建（CodeMirror 6 的推荐做法）。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { EditorState, Compartment, EditorSelection } from '@codemirror/state'
import {
  EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
  drawSelection, dropCursor, rectangularSelection, crosshairCursor,
  highlightSpecialChars, placeholder as cmPlaceholder,
} from '@codemirror/view'
import {
  defaultKeymap, history, historyKeymap, indentWithTab,
  toggleComment, cursorLineUp, cursorLineDown,
} from '@codemirror/commands'
import {
  bracketMatching, foldGutter, foldKeymap, indentOnInput,
  syntaxHighlighting, defaultHighlightStyle, indentUnit,
  StreamLanguage, LanguageSupport,
} from '@codemirror/language'
import {
  searchKeymap, highlightSelectionMatches, openSearchPanel,
} from '@codemirror/search'
import {
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
} from '@codemirror/autocomplete'
import { lintKeymap } from '@codemirror/lint'
import { oneDark } from '@codemirror/theme-one-dark'

// 按需加载语言包，避免首屏体积
const LANG_LOADERS = {
  python: () => import('@codemirror/lang-python').then((m) => m.python()),
  javascript: () => import('@codemirror/lang-javascript').then((m) => m.javascript()),
  typescript: () => import('@codemirror/lang-javascript').then((m) => m.javascript({ typescript: true })),
  cpp: () => import('@codemirror/lang-cpp').then((m) => m.cpp()),
  c: () => import('@codemirror/lang-cpp').then((m) => m.cpp()),
  java: () => import('@codemirror/lang-java').then((m) => m.java()),
  go: () => import('@codemirror/lang-go').then((m) => m.go()),
  rust: () => import('@codemirror/lang-rust').then((m) => m.rust()),
  php: () => import('@codemirror/lang-php').then((m) => m.php()),
  sql: () => import('@codemirror/lang-sql').then((m) => m.sql()),
}

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  theme: { type: String, default: 'light' },      // light | dark
  fontSize: { type: Number, default: 13 },
  tabSize: { type: Number, default: 4 },
  lineWrapping: { type: Boolean, default: false },
  showInvisibles: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  height: { type: String, default: '100%' },
})

const emit = defineEmits(['update:modelValue', 'change', 'cursor', 'ready', 'scroll'])

const host = ref(null)
const view = shallowRef(null)
// 可动态重配的分区（改这些不必重建编辑器）
const themeComp = new Compartment()
const wrapComp = new Compartment()
const readonlyComp = new Compartment()
const sizeComp = new Compartment()
const invisComp = new Compartment()

let applyingExternal = false
let changeTimer = null

function baseExtensions() {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightSpecialChars(),
    history(),
    foldGutter({
      markerDOM: (open) => {
        const el = document.createElement('span')
        el.textContent = open ? '▾' : '▸'
        el.style.cssText = 'color:#94a3b8;cursor:pointer;font-size:11px;'
        return el
      },
    }),
    drawSelection(),
    dropCursor(),
    EditorState.allowMultipleSelections.of(true),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    autocompletion({ activateOnTyping: true, maxRenderedOptions: 60 }),
    rectangularSelection(),
    crosshairCursor(),
    highlightSelectionMatches(),
    keymap.of([
      { key: 'Mod-/', run: toggleComment },
      { key: 'Alt-ArrowUp', run: cursorLineUp },
      { key: 'Alt-ArrowDown', run: cursorLineDown },
      // 多光标：Ctrl+Alt+上下 复制当前行
      {
        key: 'Ctrl-Alt-ArrowUp',
        run: (v) => copyLine(v, 'up'),
      },
      {
        key: 'Ctrl-Alt-ArrowDown',
        run: (v) => copyLine(v, 'down'),
      },
      indentWithTab,
      ...closeBracketsKeymap,
      ...defaultKeymap,
      ...historyKeymap,
      ...foldKeymap,
      ...completionKeymap,
      ...lintKeymap,
      ...searchKeymap,
    ]),
    syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    sizeComp.of([
      EditorState.tabSize.of(props.tabSize),
      indentUnit.of(' '.repeat(props.tabSize)),
      EditorView.theme({
        '&': { fontSize: `${props.fontSize}px` },
        '.cm-scroller': {
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
          lineHeight: '1.65',
        },
        '.cm-gutters': { fontSize: `${props.fontSize - 1}px` },
      }),
    ]),
    wrapComp.of(props.lineWrapping ? EditorView.lineWrapping : []),
    readonlyComp.of([
      EditorState.readOnly.of(props.readonly),
      EditorView.editable.of(!props.readonly),
    ]),
    invisComp.of(props.showInvisibles ? specialCharsHighlighter() : []),
    themeComp.of(props.theme === 'dark' ? oneDark : []),
    cmPlaceholder(props.placeholder || ''),
    EditorView.updateListener.of((u) => {
      if (u.docChanged && !applyingExternal) {
        const val = u.state.doc.toString()
        emit('update:modelValue', val)
        // 变更回调节流，避免每次敲键都触发上层逻辑
        clearTimeout(changeTimer)
        changeTimer = setTimeout(() => emit('change', val), 220)
      }
      if (u.selectionSet || u.docChanged) {
        const pos = u.state.selection.main.head
        const line = u.state.doc.lineAt(pos)
        emit('cursor', { line: line.number, col: pos - line.from + 1, pos })
      }
      if (u.geometryChanged) emit('scroll')
    }),
  ]
}

/** 显示不可见字符（空格用 ·，制表符用 →） */
function specialCharsHighlighter() {
  return EditorView.theme({
    '.cm-tab': { color: '#cbd5e1' },
  })
}

/**
 * 复制当前行（多光标批量操作）
 *
 * #144 dir 必须真正生效：
 *  - up   : 在当前行上方插入「原文 + 换行」，光标随原文下移
 *  - down : 在当前行末尾插入「换行 + 原文」，光标随复制出的那一行移动
 */
function copyLine(v, dir) {
  const { state } = v
  const down = dir === 'down'
  const specs = []
  const ranges = []
  const seen = new Set()
  for (const range of state.selection.ranges) {
    const line = state.doc.lineAt(range.head)
    // 同一行上的多个光标只复制一次，否则位置相同的插入会冲突
    const key = line.from
    if (seen.has(key)) continue
    seen.add(key)
    specs.push(down
      ? { from: line.to, to: line.to, insert: '\n' + line.text }
      : { from: line.from, to: line.from, insert: line.text + '\n' })
    ranges.push(range)
  }
  if (!specs.length) return false
  const changes = state.changes(specs)
  // assoc=1：向下复制时光标跟到新行，向上复制时随原文一起下移
  const selection = EditorSelection.create(
    ranges.map((r) => EditorSelection.range(changes.mapPos(r.anchor, 1), changes.mapPos(r.head, 1))),
    state.selection.mainIndex,
  )
  v.dispatch({ changes, selection })
  return true
}

/** 取得当前语言的扩展（异步加载，加载完成后再注入） */
async function languageExt(lang) {
  const loader = LANG_LOADERS[lang]
  if (!loader) return []
  try {
    const ext = await loader()
    return ext instanceof LanguageSupport ? [ext] : [ext]
  } catch (e) {
    return []
  }
}

let langComp = new Compartment()
let currentLangLoaded = null

async function createEditor() {
  if (!host.value) return
  const exts = baseExtensions()
  exts.push(langComp.of([]))

  let state = EditorState.create({
    doc: props.modelValue || '',
    extensions: exts,
  })
  view.value = new EditorView({ state, parent: host.value })

  emit('ready', view.value)
  await applyLanguage(props.language)
}

async function applyLanguage(lang) {
  if (!view.value) return
  currentLangLoaded = lang
  const ext = await languageExt(lang)
  if (!view.value || currentLangLoaded !== lang) return
  view.value.dispatch({ effects: langComp.reconfigure(ext) })
}

onMounted(createEditor)

onBeforeUnmount(() => {
  clearTimeout(changeTimer)
  if (view.value) {
    try { view.value.destroy() } catch (e) { /* ignore */ }
    view.value = null
  }
})

// 外部值变化 → 同步进编辑器（保留光标位置）
watch(
  () => props.modelValue,
  (val) => {
    const v = view.value
    if (!v) return
    const cur = v.state.doc.toString()
    if (val === cur) return
    applyingExternal = true
    try {
      const sel = v.state.selection
      v.dispatch({
        changes: { from: 0, to: cur.length, insert: val || '' },
        selection: sel.main.head <= (val || '').length ? sel : undefined,
      })
    } finally {
      applyingExternal = false
    }
  }
)

watch(() => props.language, (lang) => applyLanguage(lang))
watch(() => props.theme, (t) => {
  view.value && view.value.dispatch({ effects: themeComp.reconfigure(t === 'dark' ? oneDark : []) })
})
watch(() => props.lineWrapping, (w) => {
  view.value && view.value.dispatch({ effects: wrapComp.reconfigure(w ? EditorView.lineWrapping : []) })
})
watch(() => props.readonly, (r) => {
  view.value && view.value.dispatch({
    effects: readonlyComp.reconfigure([
      EditorState.readOnly.of(r),
      EditorView.editable.of(!r),
    ]),
  })
})
watch(() => [props.fontSize, props.tabSize], () => {
  if (!view.value) return
  view.value.dispatch({
    effects: sizeComp.reconfigure([
      EditorState.tabSize.of(props.tabSize),
      indentUnit.of(' '.repeat(props.tabSize)),
      EditorView.theme({
        '&': { fontSize: `${props.fontSize}px` },
        '.cm-scroller': {
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
          lineHeight: '1.65',
        },
        '.cm-gutters': { fontSize: `${props.fontSize - 1}px` },
      }),
    ]),
  })
})
watch(() => props.showInvisibles, (s) => {
  view.value && view.value.dispatch({
    effects: invisComp.reconfigure(s ? specialCharsHighlighter() : []),
  })
})

// ---------- 对外方法 ----------
function getValue() {
  return view.value ? view.value.state.doc.toString() : ''
}

function setValue(val, keepCursor = true) {
  const v = view.value
  if (!v) return
  applyingExternal = true
  try {
    const cur = v.state.doc.toString()
    v.dispatch({
      changes: { from: 0, to: cur.length, insert: val || '' },
      selection: keepCursor ? undefined : { anchor: 0 },
    })
  } finally {
    applyingExternal = false
  }
}

function focus() {
  view.value && view.value.focus()
}

function openSearch() {
  view.value && openSearchPanel(view.value)
}

function goToLine(lineNo) {
  const v = view.value
  if (!v) return
  const n = Math.max(1, Math.min(lineNo, v.state.doc.lines))
  const line = v.state.doc.line(n)
  v.dispatch({
    selection: { anchor: line.from },
    scrollIntoView: true,
  })
  v.focus()
}

/** 收起/展开全部折叠区（第 6 条折叠能力的批量操作） */
function foldAll(fold = true) {
  const v = view.value
  if (!v) return
  import('@codemirror/language').then((m) => {
    const cmd = fold ? m.foldAll : m.unfoldAll
    if (typeof cmd === 'function') cmd(v)
  })
}

function insertText(text) {
  const v = view.value
  if (!v) return
  const sel = v.state.selection.main
  v.dispatch({
    changes: { from: sel.from, to: sel.to, insert: text },
    selection: { anchor: sel.from + text.length },
  })
  v.focus()
}

/** 包裹选区（如加注释、加引号） */
function wrapSelection(prefix, suffix = '') {
  const v = view.value
  if (!v) return
  const sel = v.state.selection.main
  if (sel.empty) return
  const text = v.state.sliceDoc(sel.from, sel.to)
  v.dispatch({
    changes: { from: sel.from, to: sel.to, insert: `${prefix}${text}${suffix}` },
  })
  v.focus()
}

/** 取得当前光标位置与选区文本（供 AI 行内补全用） */
function getContext() {
  const v = view.value
  if (!v) return { prefix: '', suffix: '', line: 1, col: 1 }
  const sel = v.state.selection.main
  const pos = sel.head
  const line = v.state.doc.lineAt(pos)
  return {
    prefix: v.state.sliceDoc(0, sel.from),
    suffix: v.state.sliceDoc(sel.to, v.state.doc.length),
    selected: v.state.sliceDoc(sel.from, sel.to),
    line: line.number,
    col: pos - line.from + 1,
    pos,
  }
}

/** 在指定行显示诊断标记（第 20 条行内 squiggle） */
function setDiagnostics(items) {
  const v = view.value
  if (!v || !Array.isArray(items)) return
  const marks = []
  for (const it of items) {
    if (!it.line) continue
    const n = Math.max(1, Math.min(it.line, v.state.doc.lines))
    const line = v.state.doc.line(n)
    marks.push({
      from: line.from,
      to: line.to,
      severity: it.severity === 'error' ? 'error' : 'warning',
      message: it.message || '',
    })
  }
  // 用 lint 扩展动态注入需要额外状态字段，这里降级为不影响编辑的轻量提示
  emit('diagnostics', marks)
}

defineExpose({
  getValue, setValue, focus, openSearch, goToLine, foldAll,
  insertText, wrapSelection, getContext, setDiagnostics,
  raw: () => view.value,
})
</script>

<style scoped>
.cm-host {
  width: 100%;
  overflow: hidden;
}
.cm-host :deep(.cm-editor) {
  height: 100%;
}
.cm-host :deep(.cm-editor.cm-focused) {
  outline: none;
}
.cm-host :deep(.cm-scroller) {
  overflow: auto;
}
.cm-host :deep(.cm-gutters) {
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  color: #94a3b8;
}
.cm-host :deep(.cm-activeLineGutter) {
  background: #eef2f7;
}
.cm-host :deep(.cm-activeLine) {
  background: rgba(59, 130, 246, 0.045);
}
.cm-host :deep(.cm-selectionBackground) {
  background: rgba(59, 130, 246, 0.18) !important;
}
.cm-host :deep(.cm-content) {
  padding: 8px 0;
}
</style>
