<template>
  <div class="flex gap-4">
    <!-- 左侧文件夹树 -->
    <div class="card w-60 shrink-0 self-start p-3">
      <div class="mb-2 flex items-center justify-between px-1">
        <span class="text-[12px] font-semibold text-ink-600">文件夹</span>
        <button class="btn-ghost px-1.5 text-[12px]" @click="newFolderDialog">＋ 新建</button>
      </div>
      <div class="space-y-0.5">
        <div class="flex cursor-pointer items-center justify-between rounded-control px-2 py-1.5 text-[13px]" :class="!currentFolder && !quickFilter ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50'" @click="openFolder(null)">
          <span>📁 全部文件</span>
        </div>
        <div v-for="f in folders" :key="f.id" class="group flex cursor-pointer items-center gap-1.5 rounded-control px-2 py-1.5 text-[13px]" :class="currentFolder === f.id ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50'" @click="openFolder(f.id)">
          <span class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: f.color || '#94a3b8' }"></span>
          <span class="flex-1 truncate">{{ f.name }}</span>
          <button class="text-[11px] text-ink-300 opacity-0 group-hover:opacity-100" @click.stop="colorFolder(f)">🎨</button>
        </div>
      </div>
      <div class="mt-3 space-y-0.5 border-t border-ink-100 pt-2">
        <div v-for="q in quickFilters" :key="q.v" class="cursor-pointer rounded-control px-2 py-1.5 text-[12px]" :class="quickFilter === q.v ? 'bg-brand-50 text-brand-700' : 'text-ink-500 hover:bg-ink-50'" @click="useQuick(q.v)">{{ q.label }}</div>
        <RouterLink to="/files/analysis" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">📊 存储分析</RouterLink>
        <RouterLink to="/files/trash" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">🗑 回收站</RouterLink>
        <RouterLink to="/files/shares" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">🔗 共享链接</RouterLink>
      </div>
    </div>

    <!-- 右侧 -->
    <div class="min-w-0 flex-1 space-y-3">
      <div class="card flex flex-wrap items-center gap-2 p-3">
        <input v-model="keyword" class="input w-48" placeholder="搜索文件…" @keyup.enter="doSearch" />
        <select v-model="kindFilter" class="input w-28" @change="loadFiles">
          <option value="">全部类型</option>
          <option v-for="(label, k) in KIND_NAMES" :key="k" :value="k">{{ label }}</option>
        </select>
        <select v-model="ordering" class="input w-36" @change="loadFiles">
          <option value="-created_at">最新优先</option>
          <option value="created_at">最早优先</option>
          <option value="-size">体积最大</option>
          <option value="name">名称 A-Z</option>
        </select>
        <button class="btn-outline" @click="doSearch">搜索</button>
        <div class="ml-auto flex gap-2">
          <button class="btn-outline" @click="showText = true">＋ 新建文本</button>
          <button class="btn-primary" @click="pickFiles">⬆ 上传</button>
        </div>
      </div>

      <!-- 批量操作条 -->
      <div v-if="selected.size" class="card flex items-center gap-2 p-2.5">
        <span class="text-[12px] text-ink-500">已选 {{ selected.size }} 项</span>
        <button class="btn-outline px-2 text-[12px]" @click="batch('star')">收藏</button>
        <button class="btn-outline px-2 text-[12px]" @click="batchMove">移动到…</button>
        <button class="btn-outline px-2 text-[12px]" @click="batchDownload">打包下载</button>
        <button class="btn-danger px-2 text-[12px]" @click="batch('trash')">删除</button>
        <button class="btn-ghost px-2 text-[12px]" @click="selected.clear()">取消选择</button>
      </div>

      <div class="card overflow-hidden">
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-2.5">
          <span class="text-[13px] font-medium text-ink-700">{{ listTitle }}（{{ files.length }}）</span>
          <label class="flex items-center gap-1 text-[12px] text-ink-500"><input type="checkbox" :checked="allChecked" @change="toggleAll" /> 全选</label>
        </div>
        <div v-if="files.length" class="divide-y divide-ink-50">
          <div v-for="f in files" :key="f.id" class="group flex items-center gap-3 px-4 py-2.5 hover:bg-ink-50/60">
            <input type="checkbox" :checked="selected.has(f.id)" @change="toggleOne(f.id)" />
            <button class="text-[16px]" @click="toggleStar(f)">{{ f.is_star ? '⭐' : '☆' }}</button>
            <img v-if="f.thumbnail_url" :src="f.thumbnail_url" class="h-8 w-8 rounded-control object-cover" />
            <span v-else class="text-[18px]">{{ fileIcon(f.kind, f.ext) }}</span>
            <div class="min-w-0 flex-1">
              <div class="truncate text-[13px] font-medium text-ink-800">{{ f.name }}</div>
              <div class="text-[11px] text-ink-400">{{ f.size_text }} · {{ f.folder_name }} · {{ formatTime(f.created_at) }}<span v-if="f.description"> · {{ f.description }}</span></div>
            </div>
            <div class="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button v-if="f.kind === 'text'" class="btn-ghost px-2 text-[12px]" @click="editText(f)">编辑</button>
              <button v-if="f.previewable" class="btn-ghost px-2 text-[12px]" @click="openPreview(f)">
                {{ f.kind === 'text' ? '预览' : '查看' }}
              </button>
              <a :href="fileApi.downloadUrl(f.id)" class="btn-ghost px-2 text-[12px]">下载</a>
              <button class="btn-ghost px-2 text-[12px]" @click="openShare(f)">分享</button>
              <button class="btn-ghost px-2 text-[12px]" @click="editDesc(f)">备注</button>
              <button class="btn-ghost px-2 text-[12px]" @click="copyOne(f)">复制</button>
              <button class="btn-ghost px-2 text-[12px]" @click="renameFile(f)">重命名</button>
              <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="trashFile(f)">删除</button>
            </div>
          </div>
        </div>
        <div v-else-if="!loading" class="py-16 text-center">
          <div class="text-[32px]">📂</div>
          <div class="mt-2 text-[13px] text-ink-400">此处暂无文件</div>
        </div>
        <div v-if="loading" class="py-16 text-center text-[13px] text-ink-400">加载中…</div>
      </div>

      <div v-if="uploading" class="card p-4">
        <div class="mb-1.5 flex justify-between text-[12px]"><span>{{ uploadName }}</span><span>{{ uploadProgress }}%</span></div>
        <div class="h-2 overflow-hidden rounded-pill bg-ink-100"><div class="h-full rounded-pill bg-brand-500 transition-all" :style="{ width: uploadProgress + '%' }"></div></div>
      </div>
    </div>

    <!-- 新建文件夹 -->
    <Modal :show="showNewFolder" title="新建文件夹" @close="showNewFolder = false">
      <input v-model="newFolderName" class="input" placeholder="文件夹名称" @keyup.enter="createFolder" />
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="showNewFolder = false">取消</button><button class="btn-primary" @click="createFolder">创建</button></div>
    </Modal>

    <!-- 重命名 -->
    <Modal :show="!!renaming" :title="renaming?.isFolder ? '重命名文件夹' : '重命名文件'" @close="renaming = null">
      <input v-model="renameValue" class="input" @keyup.enter="doRename" />
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="renaming = null">取消</button><button class="btn-primary" @click="doRename">确定</button></div>
    </Modal>

    <!-- 移动到 -->
    <Modal :show="showMove" title="移动到文件夹" @close="showMove = false">
      <select v-model="moveTarget" class="input">
        <option :value="null">根目录</option>
        <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.name }}</option>
      </select>
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="showMove = false">取消</button><button class="btn-primary" @click="confirmMove">移动</button></div>
    </Modal>

    <!-- 新建/编辑文本 -->
    <Modal :show="showText || !!editingText" :title="editingText ? '编辑：' + editingText.name : '新建文本文件'" width="680px" @close="closeText">
      <input v-if="!editingText" v-model="textName" class="input mb-2" placeholder="文件名（不含扩展名）" />
      <textarea v-model="textContent" class="input h-72 resize-none font-mono text-[12px]" placeholder="输入文本内容…"></textarea>
      <div class="mt-3 flex justify-end gap-2">
        <button class="btn-ghost" @click="closeText">取消</button>
        <button class="btn-primary" @click="saveText">保存</button>
      </div>
    </Modal>

    <!-- 备注 -->
    <Modal :show="!!descTarget" title="文件备注" @close="descTarget = null">
      <textarea v-model="descValue" class="input h-28 resize-none" placeholder="给文件加个备注…"></textarea>
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="descTarget = null">取消</button><button class="btn-primary" @click="saveDesc">保存</button></div>
    </Modal>

    <!-- 分享 -->
    <Modal :show="!!sharing" title="生成共享链接" @close="sharing = null">
      <div class="space-y-3 text-[13px]">
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">权限</span>
          <select v-model="shareForm.permission" class="input w-40"><option value="view">仅预览</option><option value="download">可下载</option></select></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">过期时间</span>
          <select v-model="shareForm.expire_hours" class="input w-40"><option :value="null">永久</option><option :value="1">1 小时</option><option :value="24">24 小时</option><option :value="168">7 天</option></select></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">访问密码</span><input v-model="shareForm.password" class="input w-40" placeholder="可选" /></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">下载上限</span><input v-model.number="shareForm.max_downloads" type="number" class="input w-40" placeholder="不限" /></div>
        <div v-if="shareResult" class="rounded-control bg-ink-50 p-3">
          <div class="truncate font-mono text-[12px] text-brand-700">{{ shareUrl() }}</div>
        </div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="sharing = null">关闭</button><button v-if="!shareResult" class="btn-primary" @click="createShare">生成链接</button></div>
      </div>
    </Modal>

    <!-- 多类型在线预览：图片 / 视频 / 音频 / PDF / 文本 / Office（转 PDF 后内嵌） -->
    <Modal :show="!!previewing" :title="previewing?.name" width="max-w-3xl" @close="closePreview">
      <div v-if="previewing" class="space-y-3">
        <div class="flex flex-wrap items-center gap-2 text-[12px] text-ink-500">
          <span class="tag">{{ previewLabel }}</span>
          <span>{{ previewing.size_text }}</span>
          <span v-if="previewState.supports_range" class="tag-brand">支持拖动播放</span>
          <div class="ml-auto flex gap-2">
            <button v-if="previewState.needs_convert" class="btn-primary px-2 text-[12px]"
                    :disabled="converting" @click="convertToPdf">
              {{ converting ? '转换中…' : '转换为 PDF 预览' }}
            </button>
            <a :href="fileApi.downloadUrl(previewing.id)" class="btn-ghost px-2 text-[12px]">下载</a>
          </div>
        </div>

        <div v-if="previewing.preview_type === 'image'" class="flex justify-center">
          <img :src="fileApi.rawUrl(previewing.id)" class="max-h-[65vh] rounded-control object-contain" />
        </div>

        <video v-else-if="previewing.preview_type === 'video'" controls preload="metadata"
               class="max-h-[65vh] w-full rounded-control bg-black">
          <source :src="fileApi.rawUrl(previewing.id)" />
          您的浏览器不支持视频播放，请下载后观看。
        </video>

        <audio v-else-if="previewing.preview_type === 'audio'" controls
               class="w-full rounded-control">
          <source :src="fileApi.rawUrl(previewing.id)" />
        </audio>

        <iframe v-else-if="previewing.preview_type === 'pdf' || previewState.preview_url"
                :src="previewState.preview_url || fileApi.pdfUrl(previewing.id)"
                class="h-[65vh] w-full rounded-control border border-ink-100"></iframe>

        <pre v-else-if="previewing.preview_type === 'text'"
             class="max-h-[65vh] overflow-auto rounded-control bg-ink-50 p-3 text-[12px] leading-relaxed text-ink-700">{{ previewContent }}</pre>

        <div v-else-if="previewing.preview_type === 'office'" class="rounded-control bg-ink-50 p-4 text-[13px] text-ink-600">
          <div v-if="previewState.needs_convert">
            <div class="font-medium text-ink-800">Office 文档需要先转成 PDF 才能内嵌预览</div>
            <div class="mt-1">点击右上角「转换为 PDF 预览」即可（首次转换约需数秒）。</div>
            <div v-if="officeHint" class="mt-2 rounded-control bg-amber-50 p-2 text-[12px] text-amber-700">
              {{ officeHint }}
            </div>
          </div>
          <div v-else-if="previewState.pdf_error" class="text-rose-600">转换失败：{{ previewState.pdf_error }}</div>
        </div>

        <div v-else class="rounded-control bg-ink-50 p-4 text-[13px] text-ink-500">
          该格式暂不支持在线预览，请下载后查看。
        </div>
      </div>
    </Modal>

    <input ref="fileInput" type="file" multiple class="hidden" @change="onFilePicked" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fileApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatTime, fileIcon } from '../../utils/format'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const folders = ref([])
const files = ref([])
const currentFolder = ref(null)
const quickFilter = ref('')
const keyword = ref('')
const kindFilter = ref('')
const ordering = ref('-created_at')
const loading = ref(false)
const selected = ref(new Set())
const KIND_NAMES = { image: '图片', video: '视频', audio: '音频', archive: '压缩包', text: '文档', other: '其它' }
const quickFilters = [
  { v: 'starred', label: '⭐ 我的收藏' },
  { v: 'recent', label: '🕘 最近访问' },
]

const showNewFolder = ref(false)
const newFolderName = ref('')
const renaming = ref(null)
const renameValue = ref('')
const showMove = ref(false)
const moveTarget = ref(null)
const showText = ref(false)
const editingText = ref(null)
const textName = ref('')
const textContent = ref('')
const descTarget = ref(null)
const descValue = ref('')
const sharing = ref(null)
const shareForm = ref({})
const shareResult = ref(null)
const previewing = ref(null)
const previewState = ref({})
const previewContent = ref('')
const converting = ref(false)
const officeHint = ref('')
const fileInput = ref(null)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadName = ref('')
const CHUNK_SIZE = 5 * 1024 * 1024

const listTitle = computed(() => {
  if (quickFilter.value === 'starred') return '我的收藏'
  if (quickFilter.value === 'recent') return '最近访问'
  if (keyword.value) return '搜索结果'
  return '文件列表'
})
const allChecked = computed(() => files.value.length > 0 && files.value.every((f) => selected.value.has(f.id)))

async function loadFolders() {
  const r = await fileApi.folders(null)
  folders.value = r.list || []
}
async function loadFiles() {
  loading.value = true
  try {
    if (quickFilter.value === 'starred') {
      files.value = (await fileApi.starred()).list || []
    } else if (quickFilter.value === 'recent') {
      files.value = (await fileApi.recent()).list || []
    } else if (keyword.value) {
      files.value = ((await fileApi.search({ q: keyword.value, kind: kindFilter.value, ordering: ordering.value })).list) || []
    } else {
      files.value = ((await fileApi.list({ folder: currentFolder.value ?? '', kind: kindFilter.value, ordering: ordering.value })).list) || []
    }
  } catch (e) { app.toastMsg(e.message, 'error') } finally { loading.value = false }
}
function openFolder(id) {
  currentFolder.value = id
  quickFilter.value = ''
  keyword.value = ''
  loadFiles()
}
function useQuick(v) {
  quickFilter.value = v
  currentFolder.value = null
  keyword.value = ''
  loadFiles()
}
function doSearch() { quickFilter.value = ''; loadFiles() }
function newFolderDialog() { showNewFolder.value = true; newFolderName.value = '' }
async function createFolder() {
  if (!newFolderName.value.trim()) return
  await fileApi.createFolder({ name: newFolderName.value.trim(), parent: currentFolder.value })
  showNewFolder.value = false
  app.toastMsg('已创建', 'success')
  loadFolders()
}
async function colorFolder(f) {
  const colors = ['#0ea5e9', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#94a3b8']
  const idx = colors.indexOf(f.color)
  const color = colors[(idx + 1) % colors.length]
  await fileApi.updateFolder(f.id, { color })
  loadFolders()
}
function renameFile(f) { renaming.value = { ...f, isFolder: false }; renameValue.value = f.name }
async function doRename() {
  if (!renameValue.value.trim()) return
  await fileApi.rename(renaming.value.id, renameValue.value.trim())
  renaming.value = null
  app.toastMsg('已重命名', 'success')
  loadFiles()
}
async function toggleStar(f) {
  await fileApi.star(f.id)
  f.is_star = !f.is_star
}
async function trashFile(f) {
  await fileApi.remove(f.id)
  app.toastMsg('已移入回收站', 'success')
  loadFiles()
}
async function copyOne(f) {
  await fileApi.copy(f.id)
  app.toastMsg('已复制一份', 'success')
  loadFiles()
}
function editDesc(f) { descTarget.value = f; descValue.value = f.description || '' }
async function saveDesc() {
  await fileApi.update(descTarget.value.id, { description: descValue.value })
  descTarget.value = null
  app.toastMsg('备注已保存', 'success')
  loadFiles()
}
function toggleOne(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
function toggleAll() {
  if (allChecked.value) selected.value = new Set()
  else selected.value = new Set(files.value.map((f) => f.id))
}
async function batch(action) {
  await fileApi.batch({ file_ids: [...selected.value], action })
  selected.value = new Set()
  app.toastMsg('批量操作完成', 'success')
  loadFiles()
}
function batchMove() { showMove.value = true; moveTarget.value = null }
async function confirmMove() {
  await fileApi.batch({ file_ids: [...selected.value], action: 'move', folder: moveTarget.value })
  showMove.value = false
  selected.value = new Set()
  app.toastMsg('已移动', 'success')
  loadFiles()
}
async function batchDownload() {
  try {
    const blob = await fileApi.batchDownload([...selected.value])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '打包下载.zip'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { app.toastMsg(e.message, 'error') }
}
function closeText() { showText.value = false; editingText.value = null; textName.value = ''; textContent.value = '' }

// ---- 多类型在线预览 ----
const previewLabel = computed(() => ({
  image: '图片', video: '视频', audio: '音频', pdf: 'PDF', text: '文本', office: 'Office 文档',
}[previewing.value?.preview_type] || '文件'))

async function openPreview(f) {
  previewing.value = f
  previewState.value = { preview_url: f.preview_type === 'pdf' ? fileApi.pdfUrl(f.id) : '' }
  previewContent.value = ''
  if (f.preview_type === 'text') {
    const r = await fileApi.preview(f.id)
    previewContent.value = r.content || ''
  } else if (f.preview_type === 'office') {
    const r = await fileApi.preview(f.id)
    previewState.value = r
    if (!r.office_available) officeHint.value = r.office_hint || ''
  }
}

function closePreview() {
  previewing.value = null
  previewState.value = {}
  previewContent.value = ''
}

async function convertToPdf() {
  if (!previewing.value) return
  converting.value = true
  try {
    const r = await fileApi.toPdf(previewing.value.id)
    if (r.ok) {
      app.toastMsg('转换完成', 'success')
      previewState.value = { ...previewState.value, preview_url: r.pdf_url, needs_convert: false }
    } else {
      officeHint.value = r.message || '转换失败'
      app.toastMsg(r.message || '转换失败', 'error')
    }
  } catch (e) {
    app.toastMsg(e.message || '转换失败', 'error')
  } finally {
    converting.value = false
  }
}

async function editText(f) {
  const r = await fileApi.preview(f.id)
  editingText.value = f
  textContent.value = r.content || ''
}
async function saveText() {
  if (editingText.value) {
    await fileApi.saveText(editingText.value.id, textContent.value)
    app.toastMsg('已保存', 'success')
  } else {
    if (!textName.value.trim()) return app.toastMsg('请填写文件名', 'error')
    await fileApi.createText({ name: textName.value.trim(), content: textContent.value, folder: currentFolder.value })
    app.toastMsg('已创建', 'success')
  }
  closeText()
  loadFiles()
}
function openShare(f) { sharing.value = f; shareResult.value = null; shareForm.value = { permission: 'view', expire_hours: null, password: '', max_downloads: null } }
async function createShare() {
  const payload = { file_id: sharing.value.id, ...shareForm.value }
  Object.keys(payload).forEach((k) => (payload[k] === '' || payload[k] === null) && delete payload[k])
  shareResult.value = await fileApi.createShare(payload)
  navigator.clipboard?.writeText(shareUrl())
  app.toastMsg('链接已复制', 'success')
}
const shareUrl = () => shareResult.value ? `${location.origin}/share/${shareResult.value.token}` : ''
function pickFiles() { fileInput.value?.click() }
async function onFilePicked(e) {
  const list = Array.from(e.target.files || [])
  e.target.value = ''
  for (const file of list) await uploadOne(file)
}
async function uploadOne(file) {
  uploading.value = true
  uploadName.value = file.name
  uploadProgress.value = 0
  try {
    const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))
    const init = await fileApi.uploadInit({ filename: file.name, folder_id: currentFolder.value, file_size: file.size, chunk_size: CHUNK_SIZE, total_chunks: totalChunks, sha1: '' })
    if (init.sec_pass) { app.toastMsg('秒传成功', 'success'); return }
    for (let i = 0; i < totalChunks; i++) {
      if (init.uploaded?.includes(i)) continue
      const blob = file.slice(i * CHUNK_SIZE, i * CHUNK_SIZE + CHUNK_SIZE)
      const fd = new FormData()
      fd.append('upload_id', init.upload_id)
      fd.append('index', i)
      fd.append('chunk', blob, `${file.name}.part${i}`)
      await fileApi.uploadChunk(fd)
      uploadProgress.value = Math.round(((i + 1) / totalChunks) * 90)
    }
    await fileApi.uploadComplete(init.upload_id)
    uploadProgress.value = 100
    app.toastMsg(`${file.name} 上传完成`, 'success')
    loadFiles()
  } catch (e) { app.toastMsg(`${file.name} 上传失败：${e.message}`, 'error') } finally { uploading.value = false }
}
onMounted(() => { loadFolders(); loadFiles() })
</script>
