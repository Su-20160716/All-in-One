<template>
  <div class="flex gap-4">
    <!-- 左侧文件夹树 -->
    <div class="card w-60 shrink-0 self-start p-3">
      <div class="mb-2 flex items-center justify-between px-1">
        <span class="text-[12px] font-semibold text-ink-600">文件夹</span>
        <button class="btn-ghost px-1.5 text-[12px]" @click="newFolderDialog">＋ 新建</button>
      </div>
      <div class="space-y-0.5">
        <div class="flex cursor-pointer items-center justify-between rounded-control px-2 py-1.5 text-[13px]"
             :class="[!currentFolder && !quickFilter ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50', dragOverFolder === 0 ? 'ring-2 ring-brand-400 bg-brand-50' : '']"
             @click="openFolder(null)" @dragover.prevent="onFolderDragOver(0)" @dragleave="onFolderDragLeave(0)" @drop.prevent="onFolderDrop(0, $event)">
          <span>📁 全部文件</span>
          <span v-if="keyword && folderHits[0] !== undefined" class="rounded-pill bg-brand-50 px-1.5 text-[10px] text-brand-700">{{ folderHits[0] }}</span>
        </div>
        <div v-for="f in folders" :key="f.id" class="group flex cursor-pointer items-center gap-1.5 rounded-control px-2 py-1.5 text-[13px]"
             :class="[currentFolder === f.id ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50', dragOverFolder === f.id ? 'ring-2 ring-brand-400 bg-brand-50' : '']"
             @click="openFolder(f.id)" @dragover.prevent="onFolderDragOver(f.id)" @dragleave="onFolderDragLeave(f.id)" @drop.prevent="onFolderDrop(f.id, $event)">
          <span class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: f.color || '#94a3b8' }"></span>
          <span class="flex-1 truncate">{{ f.name }}</span>
          <span v-if="keyword && folderHits[f.id] !== undefined" class="rounded-pill bg-brand-50 px-1.5 text-[10px] text-brand-700">{{ folderHits[f.id] }}</span>
          <button class="text-[11px] text-ink-300 opacity-0 group-hover:opacity-100" title="下载文件夹" @click.stop="downloadFolder(f)">⬇</button>
          <button class="text-[11px] text-ink-300 opacity-0 group-hover:opacity-100" title="分享文件夹" @click.stop="shareFolder(f)">🔗</button>
          <button class="text-[11px] text-ink-300 opacity-0 group-hover:opacity-100" title="换颜色" @click.stop="colorFolder(f)">🎨</button>
        </div>
      </div>
      <div class="mt-3 space-y-0.5 border-t border-ink-100 pt-2">
        <div v-for="q in quickFilters" :key="q.v" class="cursor-pointer rounded-control px-2 py-1.5 text-[12px]" :class="quickFilter === q.v ? 'bg-brand-50 text-brand-700' : 'text-ink-500 hover:bg-ink-50'" @click="useQuick(q.v)">{{ q.label }}</div>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showTemplates = true">🗂 文件夹模板</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="cleanupEmpty">🧹 清理空文件夹</button>
        <RouterLink to="/files/analysis" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">📊 存储分析</RouterLink>
        <RouterLink to="/files/trash" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">🗑 回收站</RouterLink>
        <RouterLink to="/files/shares" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">🔗 共享链接</RouterLink>
      </div>

      <!-- 文件标签（#1） -->
      <div v-if="allTags.length" class="mt-3 border-t border-ink-100 pt-2">
        <div class="mb-1 flex items-center justify-between px-1">
          <span class="text-[11px] text-ink-400">标签</span>
          <button class="text-[11px] text-brand-600" @click="openTagStats">📊 统计</button>
        </div>
        <div class="flex flex-wrap gap-1 px-1">
          <span v-for="t in allTags" :key="t.id" class="cursor-pointer rounded-control px-1.5 py-0.5 text-[11px]"
                :class="activeFileTag === t.name ? 'bg-brand-50 text-brand-700' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
                @click="filterByTag(t.name)">#{{ t.name }}<span class="opacity-60">{{ t.use_count || '' }}</span></span>
        </div>
      </div>
    </div>

    <!-- 右侧 -->
    <div class="min-w-0 flex-1 space-y-3">
      <div class="card flex flex-wrap items-center gap-2 p-3">
        <div class="relative">
          <input v-model="keyword" class="input w-48" placeholder="搜索文件…" @keyup.enter="doSearch"
                 @focus="showSearchHistory = true" @blur="showSearchHistory = false" />
          <!-- S24-227 搜索历史下拉（localStorage 保留 10 条） -->
          <div v-if="showSearchHistory && searchHistory.length"
               class="absolute left-0 top-full z-20 mt-1 w-64 rounded-card border border-ink-100 bg-white p-1 shadow-lg">
            <div class="px-2 py-1 text-[11px] text-ink-400">搜索历史</div>
            <div v-for="h in searchHistory" :key="h" class="flex items-center gap-1 rounded-control px-2 py-1 text-[12px] hover:bg-ink-50">
              <button class="min-w-0 flex-1 truncate text-left" @mousedown.prevent="applyHistory(h)">{{ h }}</button>
              <button class="px-1 text-ink-300 hover:text-rose-500" title="删除该记录" @mousedown.prevent="removeHistory(h)">×</button>
            </div>
          </div>
        </div>
        <select v-model="kindFilter" class="input w-28" @change="loadFiles()">
          <option value="">全部类型</option>
          <option v-for="(label, k) in KIND_NAMES" :key="k" :value="k">{{ label }}</option>
        </select>
        <select v-model="ordering" class="input w-36" @change="loadFiles(); savePrefs()">
          <option value="-created_at">最新优先</option>
          <option value="created_at">最早优先</option>
          <option value="-size">体积最大</option>
          <option value="name">名称 A-Z</option>
        </select>
        <button class="btn-outline" @click="doSearch">搜索</button>
        <span v-if="keyword && folderHitsTotal" class="tag tag-brand">命中 {{ folderHitsTotal }}</span>
        <span v-if="activeFileTag" class="tag tag-brand">#{{ activeFileTag }} <button @click="filterByTag('')">×</button></span>
        <div class="ml-auto flex flex-wrap gap-2">
          <button class="btn-outline" @click="exportCsv">⬇ CSV</button>
          <button class="btn-outline" @click="openOps">🕘 记录</button>
          <button class="btn-outline" @click="exportFavJson">⭐ 导出收藏</button>
          <button class="btn-outline" @click="pickFavJson">📥 导入收藏</button>
          <button class="btn-outline" @click="showText = true">＋ 新建文本</button>
          <!-- S24-216 上传重名策略 -->
          <select v-model="uploadConflict" class="input w-24 text-[12px]" title="重名文件处理方式"
                  @change="saveUploadConflict">
            <option value="rename">重名改名</option>
            <option value="skip">重名跳过</option>
            <option value="overwrite">重名覆盖</option>
          </select>
          <button class="btn-primary" @click="pickFiles">⬆ 上传</button>
        </div>
      </div>

      <!-- F556 搜索命中分布（点击按文件夹过滤） -->
      <div v-if="keyword && folderHitList.length" class="card flex flex-wrap items-center gap-2 p-2.5 text-[12px]">
        <span class="text-ink-400">命中分布：</span>
        <button v-for="h in folderHitList" :key="h.folder_id" class="tag"
                :class="hitFilterFolder === h.folder_id ? 'tag-brand' : ''"
                @click="filterHits(h.folder_id)">{{ h.folder_name }} · {{ h.count }}</button>
        <button v-if="hitFilterFolder !== undefined" class="btn-ghost px-1.5 text-[12px]" @click="filterHits(undefined)">显示全部</button>
      </div>

      <!-- 批量操作条 -->
      <div v-if="selected.size" class="card flex flex-wrap items-center gap-2 p-2.5">
        <span class="text-[12px] text-ink-500">已选 {{ selected.size }} 项</span>
        <button class="btn-outline px-2 text-[12px]" @click="batch('star')">收藏</button>
        <button class="btn-outline px-2 text-[12px]" @click="showBatchTag = true">打标签</button>
        <button class="btn-outline px-2 text-[12px]" @click="showBatchRename = true">批量重命名</button>
        <button class="btn-outline px-2 text-[12px]" @click="batchMove">移动到…</button>
        <button class="btn-outline px-2 text-[12px]" @click="openBatchCopy">复制到…</button>
        <button class="btn-outline px-2 text-[12px]" @click="openBatchGroup">分组</button>
        <button class="btn-outline px-2 text-[12px]" @click="batchDownload">打包下载</button>
        <button class="btn-danger px-2 text-[12px]" @click="batch('trash')">删除</button>
        <button class="btn-ghost px-2 text-[12px]" @click="selected.clear()">取消选择</button>
      </div>

      <!-- 上传队列（#2） -->
      <div v-if="uploadQueue.length" class="card space-y-2 p-3">
        <div v-for="(q, i) in uploadQueue" :key="i" class="text-[12px]">
          <div class="mb-1 flex justify-between"><span class="truncate">{{ q.name }}</span><span>{{ q.status === 'done' ? '✓' : q.progress + '%' }}</span></div>
          <div class="h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full rounded-pill transition-all" :class="q.status === 'error' ? 'bg-rose-500' : 'bg-brand-500'" :style="{ width: q.progress + '%' }"></div></div>
        </div>
      </div>

      <!-- S24-233 断点续传：上次未完成的上传 -->
      <div v-if="pendingUploads.length" class="card flex flex-wrap items-center gap-2 p-3 text-[12px]">
        <span class="text-ink-600">检测到未完成的上传 {{ pendingUploads.length }} 个</span>
        <span v-for="p in pendingUploads" :key="p.upload_id" class="tag">
          {{ p.name }}（{{ p.done }}/{{ p.total }} 片）
          <button class="ml-1 text-brand-600" @click="resumeUpload(p)">继续上传</button>
          <button class="ml-1 text-ink-400 hover:text-rose-500" title="忽略该记录" @click="dropResume(p.upload_id)">×</button>
        </span>
      </div>

      <div class="card overflow-hidden">
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-2.5">
          <span class="text-[13px] font-medium text-ink-700">{{ listTitle }}（{{ files.length }}）</span>
          <label class="flex items-center gap-1 text-[12px] text-ink-500"><input type="checkbox" :checked="allChecked" @change="toggleAll" /> 全选</label>
        </div>
        <div v-if="files.length" class="divide-y divide-ink-50">
          <div v-for="f in files" :key="f.id" class="group flex cursor-pointer flex-wrap items-center gap-3 px-4 py-2.5 hover:bg-ink-50/60" :class="focusedId === f.id ? 'bg-brand-50/40' : ''"
               draggable="true" @dragstart="onRowDragStart(f, $event)" @click="focusRow(f)">
            <input type="checkbox" :checked="selected.has(f.id)" @click.stop @change="toggleOne(f.id)" />
            <button class="text-[16px]" @click.stop="toggleStar(f)">{{ f.is_star ? '⭐' : '☆' }}</button>
            <img v-if="f.thumbnail_url" :src="f.thumbnail_url" class="h-8 w-8 rounded-control object-cover" />
            <span v-else class="grid h-8 w-8 place-items-center rounded-control text-[14px]" :class="typeMeta(f).color">{{ typeMeta(f).icon }}</span>
            <div class="min-w-0 flex-1">
              <div class="truncate text-[13px] font-medium text-ink-800">{{ f.name }}</div>
              <div class="text-[11px] text-ink-400"><span v-if="dimLabel(f)" class="tag mr-1">{{ dimLabel(f) }}</span>{{ f.size_text }} · {{ f.folder_name }} · {{ formatTime(f.created_at) }}<span v-if="f.description"> · {{ f.description }}</span></div>
              <div v-if="f.tag_names && f.tag_names.length" class="mt-0.5 flex flex-wrap gap-1">
                <span v-for="tg in f.tag_names" :key="tg" class="rounded-control bg-ink-50 px-1 py-0.5 text-[10px] text-ink-500">#{{ tg }}</span>
              </div>
            </div>
            <!-- #175 行内操作：移动端常显，桌面 hover / 键盘聚焦时才显示 -->
            <div class="flex shrink-0 flex-wrap items-center justify-end gap-1 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100" @click.stop>
              <button v-if="f.kind === 'text'" class="btn-ghost px-2 text-[12px]" @click="editText(f)">编辑</button>
              <button v-if="f.previewable" class="btn-ghost px-2 text-[12px]" @click="openPreview(f)">
                {{ f.kind === 'text' ? '预览' : '查看' }}
              </button>
              <button class="btn-ghost px-2 text-[12px]" @click="downloadOne(f)">下载</button>
              <button class="btn-ghost px-2 text-[12px]" @click="openShare(f)">分享</button>
              <button class="btn-ghost px-2 text-[12px]" @click="openVisibility(f)">可见性</button>
              <button class="btn-ghost px-2 text-[12px]" @click="editDesc(f)">备注</button>
              <!-- S24-224 文本沉淀为笔记 -->
              <button v-if="f.kind === 'text'" class="btn-ghost px-2 text-[12px]" @click="toNote(f)">转为笔记</button>
              <!-- S24-226 最近访问单条移除 -->
              <button v-if="quickFilter === 'recent'" class="btn-ghost px-2 text-[12px]" @click="removeRecent(f)">移除</button>
              <template v-if="quickFilter === 'starred'">
                <button class="btn-ghost px-1.5 text-[12px]" title="上移" @click="moveStar(f, -1)">↑</button>
                <button class="btn-ghost px-1.5 text-[12px]" title="下移" @click="moveStar(f, 1)">↓</button>
              </template>
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

    <!-- 文件夹模板（#3） -->
    <Modal :show="showTemplates" title="从模板创建文件夹" @close="showTemplates = false">
      <div class="grid grid-cols-2 gap-2">
        <button v-for="t in folderTemplates" :key="t.key" class="rounded-card border border-ink-100 p-3 text-left hover:border-brand-400" @click="useFolderTemplate(t.key)">
          <div class="text-[13px] font-medium text-ink-800">🗂 {{ t.name }}</div>
          <div class="mt-1 text-[11px] text-ink-400">{{ Object.keys(t.structure || {}).join(' / ') }}</div>
        </button>
      </div>
      <div class="mt-3 text-[11px] text-ink-400">将在当前位置（{{ currentFolder ? '所选文件夹内' : '根目录' }}）一键递归生成目录。</div>
    </Modal>

    <!-- 批量打标签 -->
    <Modal :show="showBatchTag" title="批量打标签" @close="showBatchTag = false">
      <input v-model="batchTagInput" class="input" placeholder="标签名（多个用逗号分隔）" />
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="showBatchTag = false">取消</button><button class="btn-primary" @click="applyBatchTag">确定</button></div>
    </Modal>

    <!-- 批量重命名（#8） -->
    <Modal :show="showBatchRename" title="批量重命名" @close="showBatchRename = false">
      <div class="space-y-3 text-[13px]">
        <label class="flex items-center gap-2"><input type="radio" value="prefix" v-model="renameMode" /> 序号前缀（如 P01_）</label>
        <label class="flex items-center gap-2"><input type="radio" value="replace" v-model="renameMode" /> 查找替换</label>
        <input v-if="renameMode === 'prefix'" v-model="renamePrefix" class="input" placeholder="前缀，如 设计稿_" />
        <template v-else>
          <input v-model="renameFind" class="input" placeholder="查找内容" />
          <input v-model="renameReplace" class="input" placeholder="替换为" />
        </template>
      </div>
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="showBatchRename = false">取消</button><button class="btn-primary" @click="doBatchRename">执行</button></div>
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

    <!-- S24-228 批量复制到 -->
    <Modal :show="showCopy" title="复制到文件夹" @close="showCopy = false">
      <select v-model="copyTarget" class="input">
        <option :value="null">根目录</option>
        <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.name }}</option>
      </select>
      <div class="mt-2 text-[11px] text-ink-400">复制出的文件命名为「原名(副本)」，原文件保持不变。</div>
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="showCopy = false">取消</button><button class="btn-primary" @click="confirmCopy">复制</button></div>
    </Modal>

    <!-- S24-235 批量归入收藏分组 -->
    <Modal :show="showBatchGroup" title="归入收藏分组" @close="showBatchGroup = false">
      <input v-model="batchGroupValue" class="input" list="file-groups" placeholder="分组名（留空表示取消分组）" />
      <datalist id="file-groups">
        <option v-for="g in starGroups" :key="g.name" :value="g.name" />
      </datalist>
      <div class="mt-2 flex flex-wrap gap-1">
        <button v-for="g in starGroups" :key="'p' + g.name" class="tag" @click="batchGroupValue = g.name">#{{ g.name }} {{ g.count }}</button>
      </div>
      <div class="mt-4 flex justify-end gap-2"><button class="btn-ghost" @click="showBatchGroup = false">取消</button><button class="btn-primary" @click="confirmGroup">确定</button></div>
    </Modal>

    <!-- S24-215 移动冲突预检 -->
    <Modal :show="!!moveConflicts" title="目标目录存在同名文件" width="560px" @close="moveConflicts = null">
      <div class="space-y-2 text-[12px]">
        <div class="text-ink-600">移动到「{{ moveConflicts?.target?.name || '根目录' }}」有 {{ moveConflicts?.conflicts?.length || 0 }} 个同名文件，请选择处理方式：</div>
        <div class="max-h-40 space-y-0.5 overflow-y-auto">
          <div v-for="c in moveConflicts?.conflicts || []" :key="c.id" class="truncate rounded-control bg-ink-50 px-2 py-1">{{ c.name }}</div>
        </div>
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="moveConflicts = null">取消</button>
        <button class="btn-outline" @click="runMove('skip')">跳过同名</button>
        <button class="btn-primary" @click="runMove('rename')">自动改名</button>
      </div>
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

    <!-- 分享（S24-223：文件夹分享支持允许访客上传） -->
    <Modal :show="!!sharing" :title="shareIsFolder ? '文件夹共享链接' : '生成共享链接'" @close="sharing = null">
      <div class="space-y-3 text-[13px]">
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">权限</span>
          <select v-model="shareForm.permission" class="input w-40"><option value="view">仅预览</option><option value="download">可下载</option></select></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">过期时间</span>
          <select v-model="shareForm.expire_hours" class="input w-40"><option :value="null">永久</option><option :value="1">1 小时</option><option :value="24">24 小时</option><option :value="168">7 天</option></select></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">访问密码</span><input v-model="shareForm.password" class="input w-40" placeholder="可选" /></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">下载上限</span><input v-model.number="shareForm.max_downloads" type="number" class="input w-40" placeholder="不限" /></div>
        <label v-if="shareIsFolder" class="flex items-center gap-2"><input v-model="shareForm.allow_upload" type="checkbox" /> 允许上传（访客可把文件投递进来）</label>
        <div v-if="shareResult" class="space-y-2 rounded-control bg-ink-50 p-3">
          <div class="truncate font-mono text-[12px] text-brand-700">{{ shareUrl() }}</div>
          <div class="flex flex-wrap gap-2">
            <button class="btn-outline px-2 text-[12px]" @click="copyText(shareUrl(), '链接已复制')">复制链接</button>
            <button class="btn-outline px-2 text-[12px]" @click="copyMarkdown">复制 Markdown</button>
            <button class="btn-outline px-2 text-[12px]" @click="copyHtml">复制 HTML</button>
            <button v-if="shareResult.allow_upload" class="btn-outline px-2 text-[12px]" @click="copyText(shareUrl(), '收集链接已复制，访客可在分享页直接上传')">复制收集链接</button>
          </div>
          <div v-if="shareResult.allow_upload" class="text-[11px] text-ink-500">访客打开该链接即可把文件上传到共享文件夹（单个 ≤50MB，后端校验扩展名）。</div>
        </div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="sharing = null">关闭</button><button v-if="!shareResult" class="btn-primary" @click="createShare">生成链接</button></div>
      </div>
    </Modal>

    <!-- 多类型在线预览：图片 / 视频 / 音频 / PDF / 文本 / Office（转 PDF 后内嵌） -->
    <Modal :show="!!previewing" :title="previewing?.name" width="768px" @close="closePreview">
      <div v-if="previewing" class="space-y-3">
        <div class="flex flex-wrap items-center gap-2 text-[12px] text-ink-500">
          <span class="tag">{{ previewLabel }}</span>
          <span>{{ previewing.size_text }}</span>
          <span v-if="previewState.supports_range" class="tag-brand">支持拖动播放</span>
          <div class="ml-auto flex items-center gap-2">
            <!-- F558 预览缩放（记忆上次缩放比例） -->
            <div class="flex items-center rounded-control border border-ink-100 text-[12px]">
              <button class="px-2 py-1 hover:bg-ink-50" @click="changeZoom(-25)">−</button>
              <span class="w-11 border-x border-ink-100 py-1 text-center">{{ zoom }}%</span>
              <button class="px-2 py-1 hover:bg-ink-50" @click="changeZoom(25)">＋</button>
            </div>
            <button v-if="previewState.needs_convert" class="btn-primary px-2 text-[12px]"
                    :disabled="converting" @click="convertToPdf">
              {{ converting ? '转换中…' : '转换为 PDF 预览' }}
            </button>
            <button class="btn-ghost px-2 text-[12px]" @click="downloadOne(previewing)">下载</button>
          </div>
        </div>

        <!-- F2：媒体源走带 JWT 的 objectURL（裸 URL 不带令牌会 401） -->
        <div v-if="previewing.preview_type === 'image'" class="flex justify-center overflow-auto">
          <img v-if="mediaUrl" :src="mediaUrl" class="max-h-[55vh] rounded-control object-contain transition-transform"
               :style="{ transform: 'scale(' + zoom / 100 + ')' }" />
          <div v-else class="py-10 text-[12px] text-ink-400">媒体加载中…</div>
        </div>

        <video v-else-if="previewing.preview_type === 'video'" controls preload="metadata"
               class="max-h-[55vh] w-full rounded-control bg-black">
          <source v-if="mediaUrl" :src="mediaUrl" />
          您的浏览器不支持视频播放，请下载后观看。
        </video>

        <audio v-else-if="previewing.preview_type === 'audio'" controls
               class="w-full rounded-control">
          <source v-if="mediaUrl" :src="mediaUrl" />
        </audio>

        <iframe v-else-if="previewing.preview_type === 'pdf' || previewState.preview_url"
                :src="previewState.preview_url || mediaUrl"
                class="h-[55vh] w-full rounded-control border border-ink-100"></iframe>

        <div v-else-if="previewing.preview_type === 'text'" class="space-y-2">
          <!-- S24-221 预览内查找：高亮全部命中并支持上下跳转（不请求后端） -->
          <div class="flex flex-wrap items-center gap-2 text-[12px]">
            <input ref="findInput" v-model="findText" class="input w-52 py-1" placeholder="查找文本…（Enter 下一个）"
                   @keyup.enter.exact="nextMatch(1)" @keyup.shift.enter="nextMatch(-1)" />
            <span class="text-ink-400">{{ findText ? `${findCount ? findPos + 1 : 0}/${findCount}` : '输入关键词查找' }}</span>
            <button class="btn-ghost px-2 text-[12px]" :disabled="!findCount" @click="nextMatch(-1)">上一个</button>
            <button class="btn-ghost px-2 text-[12px]" :disabled="!findCount" @click="nextMatch(1)">下一个</button>
          </div>
          <pre ref="findPre"
               class="max-h-[55vh] overflow-auto rounded-control bg-ink-50 p-3 leading-relaxed text-ink-700"
               :style="{ fontSize: (12 * zoom / 100) + 'px' }" v-html="highlightContent"></pre>
        </div>

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

        <!-- EXIF 信息（#4） -->
        <div v-if="exifInfo" class="rounded-control bg-ink-50 p-3 text-[12px] text-ink-600">
          <div class="mb-1 font-medium text-ink-700">照片信息</div>
          <div v-if="exifInfo.dimensions">尺寸：{{ exifInfo.dimensions }}</div>
          <div v-if="exifInfo.camera">设备：{{ exifInfo.camera }}</div>
          <div v-if="exifInfo.taken">拍摄时间：{{ exifInfo.taken }}</div>
          <div v-if="!exifInfo.dimensions && !exifInfo.camera && !exifInfo.taken" class="text-ink-400">未读取到 EXIF 信息（可能已被剥离）</div>
        </div>

        <div v-if="previewUnsupported" class="rounded-control bg-ink-50 p-4 text-[13px] text-ink-500">
          该格式暂不支持在线预览，请下载后查看。
        </div>
      </div>
    </Modal>

    <!-- F559 移动/复制操作记录 -->
    <Modal :show="showOps" title="文件操作记录" width="640px" @close="showOps = false">
      <div class="mb-2 flex items-center gap-2 text-[12px]">
        <select v-model="opsAction" class="input w-32" @change="loadOps">
          <option value="">全部操作</option>
          <option value="move">移动</option>
          <option value="copy">复制</option>
          <option value="rename">重命名</option>
          <option value="upload">上传</option>
        </select>
        <span class="text-ink-400">共 {{ opsList.length }} 条</span>
        <button class="btn-ghost ml-auto px-2 text-[12px]" @click="toggleHeatmap">{{ showHeatmap ? '列表' : '热力图' }}</button>
        <button class="btn-ghost px-2 text-[12px]" @click="loadOps">刷新</button>
      </div>
      <!-- S24-220 操作热力图：按日期 × 动作聚合，色深表示操作量 -->
      <div v-if="showHeatmap" class="mb-2 rounded-control bg-ink-50 p-2">
        <div class="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
          <span>近 {{ heatmap.days || 180 }} 天 · 共 {{ heatmap.total || 0 }} 次操作</span>
          <span v-for="a in heatmap.by_action || []" :key="a.action">{{ a.label }} {{ a.count }}</span>
        </div>
        <div class="flex flex-wrap gap-[3px]">
          <span v-for="d in heatmap.days_list || []" :key="d.date" :title="`${d.date}：${d.count} 次`"
                class="h-3 w-3 rounded-sm" :style="{ background: heatColor(d.count) }"></span>
        </div>
      </div>
      <div v-if="!showHeatmap" class="max-h-[50vh] space-y-1 overflow-y-auto">
        <div v-for="o in opsList" :key="o.id" class="rounded-control bg-ink-50 px-3 py-2 text-[12px]">
          <div class="flex justify-between"><span class="font-medium text-ink-700">{{ o.action_label }} · {{ o.file_name }}</span><span class="text-ink-400">{{ formatTime(o.created_at) }}</span></div>
          <div class="text-ink-500">
            <span v-if="o.from_folder || o.to_folder">{{ o.from_folder || '根目录' }} → {{ o.to_folder || '根目录' }}</span>
            <span v-if="o.detail" class="ml-1">{{ o.detail }}</span>
          </div>
        </div>
        <div v-if="!opsList.length" class="py-8 text-center text-[12px] text-ink-400">暂无操作记录</div>
      </div>
    </Modal>

    <!-- F561 文件可见性快照 -->
    <Modal :show="!!visTarget" :title="`可见性：${visTarget ? visTarget.name : ''}`" width="560px" @close="visTarget = null">
      <div v-if="visState" class="space-y-3 text-[13px]">
        <div class="rounded-control bg-ink-50 p-3">
          <div class="flex justify-between"><span>当前状态</span><span class="font-medium" :class="visState.visibility === 'private' ? 'text-ink-700' : 'text-brand-600'">{{ visState.visibility_label }}</span></div>
          <div class="mt-1 flex justify-between text-[12px] text-ink-500"><span>数据范围</span><span>{{ visState.data_scope }}</span></div>
          <div class="mt-1 flex justify-between text-[12px] text-ink-500"><span>有效分享</span><span>{{ visState.active_shares }} 条</span></div>
        </div>
        <div>
          <div class="mb-1 text-[12px] font-medium text-ink-600">分享链接</div>
          <div v-for="s in visState.shares" :key="s.token" class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-1.5 text-[12px]">
            <span class="truncate font-mono">{{ s.url }}</span>
            <span class="shrink-0" :class="s.is_expired ? 'text-rose-500' : s.is_revoked ? 'text-ink-400' : 'text-emerald-600'">
              {{ s.is_revoked ? '已撤销' : s.is_expired ? '已过期' : s.permission }}
            </span>
          </div>
          <div v-if="!visState.shares.length" class="text-[12px] text-ink-400">从未生成过分享链接</div>
        </div>
        <div>
          <div class="mb-1 text-[12px] font-medium text-ink-600">快照历史（{{ visState.history_count }}）</div>
          <div class="max-h-40 space-y-1 overflow-y-auto">
            <div v-for="h in visState.history" :key="h.id" class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-1.5 text-[11px]">
              <span>{{ h.visibility_label }}<span v-if="h.note" class="text-ink-400"> · {{ h.note }}</span></span>
              <span class="text-ink-400">{{ formatTime(h.created_at) }}</span>
            </div>
            <div v-if="!visState.history.length" class="text-[11px] text-ink-400">暂无快照</div>
          </div>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="visTarget = null">关闭</button>
          <button class="btn-primary" @click="takeSnapshot">记录当前快照</button>
        </div>
      </div>
      <div v-else class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
    </Modal>

    <!-- F563 标签统计与点击过滤 -->
    <Modal :show="showTagStats" title="标签统计" width="560px" @close="showTagStats = false">
      <div class="mb-2 flex justify-between text-[12px] text-ink-500">
        <span>共 {{ tagStats.total_tags || 0 }} 个标签 · 未打标 {{ tagStats.untagged || 0 }} 个</span>
        <span>总占用 {{ tagStats.total_text || '0 B' }}</span>
      </div>
      <div class="max-h-[50vh] space-y-1 overflow-y-auto">
        <button v-for="t in tagStats.list || []" :key="t.id"
                class="flex w-full items-center gap-2 rounded-control bg-ink-50 px-3 py-2 text-left text-[12px] hover:bg-ink-100"
                @click="filterByTag(t.name); showTagStats = false">
          <span class="h-2.5 w-2.5 rounded-sm" :style="{ background: (!t.color || t.color === 'default') ? '#94a3b8' : t.color }"></span>
          <span class="flex-1 truncate font-medium text-ink-700">#{{ t.name }}</span>
          <span class="text-ink-500">{{ t.count }} 个 · {{ t.count_pct }}%</span>
          <span class="w-24 text-right text-ink-500">{{ t.bytes_text }}</span>
          <span class="w-12 text-right text-brand-600">{{ t.pct }}%</span>
        </button>
        <div v-if="!(tagStats.list || []).length" class="py-8 text-center text-[12px] text-ink-400">还没有标签</div>
      </div>
      <!-- S24-217 标签合并：把 from 的文件关系整体并入 to -->
      <div class="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3 text-[12px]">
        <span class="text-ink-500">合并标签</span>
        <select v-model="mergeFrom" class="input w-32">
          <option :value="null">来源标签</option>
          <option v-for="t in tagStats.list || []" :key="'f' + t.id" :value="t.id">#{{ t.name }}</option>
        </select>
        <span class="text-ink-400">→</span>
        <select v-model="mergeTo" class="input w-32">
          <option :value="null">目标标签</option>
          <option v-for="t in tagStats.list || []" :key="'t' + t.id" :value="t.id">#{{ t.name }}</option>
        </select>
        <button class="btn-outline px-2 text-[12px]" :disabled="!mergeFrom || !mergeTo || mergeFrom === mergeTo" @click="doTagMerge">合并到</button>
        <span class="text-[11px] text-ink-400">合并后来源标签会被删除，文件关系全部转到目标标签。</span>
      </div>
      <div class="mt-2 text-[11px] text-ink-400">点击标签即可按它过滤文件列表。</div>
    </Modal>

    <input ref="fileInput" type="file" multiple class="hidden" @change="onFilePicked" />
    <input ref="favInput" type="file" accept="application/json,.json" class="hidden" @change="onFavPicked" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fileApi } from '../../api'
import request from '../../api/request'
import { filesx } from '../../api/filesx'
import { shareUrl as buildShareUrl } from '../../api/base'
import { useAppStore } from '../../stores/app'
import { formatTime, fileIcon, fileTypeMeta } from '../../utils/format'
import { describeDownloadError, downloadWithAuth, loadMediaObjectUrl, saveBlob } from '../../utils/download'
import { sha1File } from '../../utils/sha1'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const route = useRoute()
const folders = ref([])
const files = ref([])
const currentFolder = ref(null)
const quickFilter = ref('')
const keyword = ref('')
const kindFilter = ref('')
const ordering = ref('-created_at')
const loading = ref(false)
const selected = ref(new Set())
const focusedId = ref(null)
const KIND_NAMES = { image: '图片', video: '视频', audio: '音频', archive: '压缩包', text: '文档', other: '其它' }
const quickFilters = [
  { v: 'starred', label: '⭐ 我的收藏' },
  { v: 'recent', label: '🕘 最近访问' },
]

// #1 文件标签
const allTags = ref([])
const activeFileTag = ref('')
const showBatchTag = ref(false)
const batchTagInput = ref('')

// #3 文件夹模板
const showTemplates = ref(false)
const folderTemplates = ref([])

// #8 批量重命名
const showBatchRename = ref(false)
const renameMode = ref('prefix')
const renamePrefix = ref('')
const renameFind = ref('')
const renameReplace = ref('')

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
const creatingShare = ref(false)
const previewing = ref(null)
const previewState = ref({})
const previewContent = ref('')
// F2：媒体预览的 objectURL（带 JWT 拉取后本地引用）
const mediaUrl = ref('')
const converting = ref(false)
const officeHint = ref('')
const exifInfo = ref(null)
const fileInput = ref(null)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadName = ref('')
const uploadQueue = ref([])
const CHUNK_SIZE = 5 * 1024 * 1024

// ---- S24-211–235 前端状态 ----
const searchHistory = ref([])          // 227 搜索历史
const showSearchHistory = ref(false)
const dragOverFolder = ref(null)       // 213 拖拽高亮目标目录（0 = 根目录）
const dragFileId = ref(null)
const uploadConflict = ref('rename')   // 216 重名策略
const pendingUploads = ref([])         // 233 未完成上传
const resumeTarget = ref(null)
const showCopy = ref(false)            // 228 批量复制
const copyTarget = ref(null)
const showBatchGroup = ref(false)      // 235 收藏分组
const batchGroupValue = ref('')
const starGroups = ref([])
const moveConflicts = ref(null)        // 215 移动冲突预检结果
const mergeFrom = ref(null)            // 217 标签合并
const mergeTo = ref(null)
const shareIsFolder = ref(false)       // 223 文件夹分享
const findText = ref('')               // 221 预览内查找
const findPos = ref(0)
const findPre = ref(null)
const showHeatmap = ref(false)         // 220 操作热力图
const heatmap = ref({})

// 预览兜底提示只应在「确实没有可用渲染器」时出现；
// 之前 v-else 挂在 EXIF 块后面，导致 txt/pdf 等都显示"不支持预览"
const PREVIEW_TYPES = ['image', 'video', 'audio', 'pdf', 'text', 'office']
const previewUnsupported = computed(() => {
  if (!previewing.value) return false
  if (previewState.value?.preview_url) return false
  return !PREVIEW_TYPES.includes(previewing.value.preview_type)
})

// ---- F547–F564 文件中心新增能力 ----
const dims = ref({})              // F553 图片分辨率徽章
const folderHits = ref({})        // F556 文件夹命中计数（folder_id -> count）
const folderHitIds = ref({})      // F556 文件夹命中 ids
const folderHitList = ref([])     // F556 命中分布
const folderHitsTotal = ref(0)
const hitFilterFolder = ref(undefined)
const zoom = ref(100)             // F558 预览缩放记忆
const showOps = ref(false)        // F559 操作记录
const opsList = ref([])
const opsAction = ref('')
const visTarget = ref(null)       // F561 可见性快照
const visState = ref(null)
const showTagStats = ref(false)   // F563 标签统计
const tagStats = ref({})
const favInput = ref(null)        // F564 收藏/标签 JSON 导入

const listTitle = computed(() => {
  if (quickFilter.value === 'starred') return '我的收藏'
  if (quickFilter.value === 'recent') return '最近访问'
  if (activeFileTag.value) return `标签：${activeFileTag.value}`
  if (keyword.value) return '搜索结果'
  return '文件列表'
})
const allChecked = computed(() => files.value.length > 0 && files.value.every((f) => selected.value.has(f.id)))

function typeMeta(f) { return fileTypeMeta(f.kind, f.ext) }

// #11/#7 偏好记忆
function savePrefs() {
  try {
    localStorage.setItem('files.prefs', JSON.stringify({ folder: currentFolder.value, ordering: ordering.value }))
  } catch (e) { /* ignore */ }
}
function loadPrefs() {
  try {
    const raw = localStorage.getItem('files.prefs')
    if (raw) {
      const p = JSON.parse(raw)
      if (p.ordering) ordering.value = p.ordering
      if (p.folder !== undefined && p.folder !== null) currentFolder.value = p.folder
    }
  } catch (e) { /* ignore */ }
}

async function loadFolders() {
  const r = await fileApi.folders(null)
  folders.value = r.list || []
}
async function loadFileTags() {
  try { allTags.value = (await fileApi.fileTags()).list || [] } catch (e) { allTags.value = [] }
}
async function loadFolderTemplates() {
  try { folderTemplates.value = (await fileApi.folderTemplates()).list || [] } catch (e) { folderTemplates.value = [] }
}
let loadSeq = 0
// #142 保留模式：实时事件触发的刷新不清空选区，仅按 id 交集裁剪
async function loadFiles(preserveSelection = false) {
  const seq = ++loadSeq
  loading.value = true
  // 用户主动切目录/筛选后旧选中项不可见，必须清空，避免批量操作误伤
  if (!preserveSelection) selected.value = new Set()
  try {
    const params = { kind: kindFilter.value, ordering: ordering.value }
    let next = []
    if (quickFilter.value === 'starred') {
      next = (await fileApi.starred()).list || []
    } else if (quickFilter.value === 'recent') {
      next = (await fileApi.recent()).list || []
    } else if (keyword.value) {
      let list = ((await fileApi.search({ q: keyword.value, kind: kindFilter.value })).list) || []
      // F556 按命中文件夹过滤搜索结果
      if (hitFilterFolder.value !== undefined) {
        const ids = new Set(folderHitIds.value[hitFilterFolder.value] || [])
        list = list.filter((f) => ids.has(f.id))
      }
      next = list
    } else {
      params.folder = currentFolder.value ?? ''
      if (activeFileTag.value) params.tag = activeFileTag.value
      next = ((await fileApi.list(params)).list) || []
    }
    if (seq !== loadSeq) return
    files.value = next
    if (preserveSelection && selected.value.size) {
      const ids = new Set(next.map((f) => f.id))
      const kept = new Set([...selected.value].filter((id) => ids.has(id)))
      if (kept.size !== selected.value.size) selected.value = kept
    }
    loadDims()
  } catch (e) {
    if (seq === loadSeq) app.toastMsg(e.message, 'error')
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}
function openFolder(id) {
  currentFolder.value = id
  quickFilter.value = ''
  keyword.value = ''
  savePrefs()
  loadFiles()
}
function useQuick(v) {
  quickFilter.value = v
  currentFolder.value = null
  keyword.value = ''
  activeFileTag.value = ''
  loadFiles()
}
function filterByTag(name) {
  activeFileTag.value = name || ''
  if (name) { quickFilter.value = ''; keyword.value = '' }
  loadFiles()
}
function doSearch() {
  quickFilter.value = ''
  hitFilterFolder.value = undefined
  pushHistory(keyword.value)
  showSearchHistory.value = false
  loadFiles()
  loadFolderHits()
}

// S24-227 搜索历史（localStorage，10 条去重）
function loadSearchHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem('files.searchHistory') || '[]')
    searchHistory.value = Array.isArray(raw) ? raw.slice(0, 10) : []
  } catch (e) { searchHistory.value = [] }
}
function saveSearchHistory() {
  try { localStorage.setItem('files.searchHistory', JSON.stringify(searchHistory.value.slice(0, 10))) } catch (e) { /* ignore */ }
}
function pushHistory(q) {
  const k = String(q || '').trim()
  if (!k) return
  searchHistory.value = [k, ...searchHistory.value.filter((x) => x !== k)].slice(0, 10)
  saveSearchHistory()
}
function applyHistory(h) {
  keyword.value = h
  showSearchHistory.value = false
  doSearch()
}
function removeHistory(h) {
  searchHistory.value = searchHistory.value.filter((x) => x !== h)
  saveSearchHistory()
}

// ---- S24-213 HTML5 拖拽：文件行 → 文件夹行 = 移动；本地文件 → 文件夹 = 上传 ----
function onRowDragStart(f, e) {
  dragFileId.value = f.id
  try {
    e.dataTransfer.setData('application/x-file-id', String(f.id))
    e.dataTransfer.effectAllowed = 'move'
  } catch (err) { /* 部分浏览器不允许自定义类型 */ }
}
function onFolderDragOver(id) { dragOverFolder.value = id }
function onFolderDragLeave(id) { if (dragOverFolder.value === id) dragOverFolder.value = null }
async function onFolderDrop(folderId, e) {
  dragOverFolder.value = null
  const dropped = Array.from(e?.dataTransfer?.files || [])
  const rawId = Number(e?.dataTransfer?.getData('application/x-file-id') || 0)
  dragFileId.value = null
  if (dropped.length) {
    // 本地文件拖入 → 直接上传到该目录（0 视为根目录）
    const target = folderId || null
    const batch = dropped.map((f) => ({ name: f.name, progress: 0, status: 'uploading' }))
    uploadQueue.value = batch
    dropped.forEach((f, i) => uploadOne(f, i, batch, target))
    return
  }
  if (rawId) {
    // 已多选且拖拽的是其中一员时，整批移动
    if (!selected.value.has(rawId)) selected.value = new Set([rawId])
    moveTarget.value = folderId || null
    await confirmMove()
  }
}

// S24-212 文件夹整包下载
async function downloadFolder(f) {
  try {
    await downloadWithAuth(filesx.folderDownloadUrl(f.id), `${f.name}.zip`)
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}

// S24-218 一键清理空文件夹
async function cleanupEmpty() {
  try {
    const r = await filesx.emptyFolders()
    const list = r.list || []
    if (!list.length) return app.toastMsg('没有空文件夹', 'info')
    if (!confirm(`发现 ${list.length} 个空文件夹（无文件且无子目录），是否全部删除？`)) return
    const res = await filesx.cleanupEmptyFolders(list.map((x) => x.id))
    app.toastMsg(res.message || `已删除 ${res.deleted} 个空文件夹`, 'success')
    loadFolders()
  } catch (e) { app.toastMsg(e.message || '清理失败', 'error') }
}
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
async function useFolderTemplate(key) {
  try {
    const r = await fileApi.folderFromTemplate({ key, parent: currentFolder.value ?? null })
    app.toastMsg(`已创建 ${r.count} 个文件夹`, 'success')
    showTemplates.value = false
    loadFolders()
  } catch (e) { app.toastMsg(e.message, 'error') }
}
async function applyBatchTag() {
  const names = batchTagInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
  if (!names.length) { showBatchTag.value = false; return }
  try {
    await fileApi.batchTag({ file_ids: [...selected.value], tags: names, action: 'set' })
    app.toastMsg('标签已更新', 'success')
    showBatchTag.value = false
    batchTagInput.value = ''
    selected.value = new Set()
    loadFileTags(); loadFiles()
  } catch (e) { app.toastMsg(e.message, 'error') }
}
async function doBatchRename() {
  try {
    const data = { file_ids: [...selected.value], mode: renameMode.value }
    if (renameMode.value === 'prefix') data.prefix = renamePrefix.value
    else { data.find = renameFind.value; data.replace = renameReplace.value }
    const r = await fileApi.batchRename(data)
    app.toastMsg(`已重命名 ${r.renamed?.length || 0} 个文件`, 'success')
    showBatchRename.value = false
    selected.value = new Set()
    loadFiles()
  } catch (e) { app.toastMsg(e.message, 'error') }
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
function focusRow(f) { focusedId.value = f.id }
function toggleAll() {
  if (allChecked.value) selected.value = new Set()
  else selected.value = new Set(files.value.map((f) => f.id))
}
async function batch(action) {
  if (!selected.value.size) { app.toastMsg('请先选择文件', 'error'); return }
  if (action === 'trash' && !confirm(`将选中的 ${selected.value.size} 个文件移入回收站？`)) return
  await fileApi.batch({ file_ids: [...selected.value], action })
  selected.value = new Set()
  app.toastMsg('批量操作完成', 'success')
  loadFiles()
}
function batchMove() { showMove.value = true; moveTarget.value = null }
// S24-215 先 dry_run 预检，有冲突时让用户选择跳过 / 改名
async function confirmMove() {
  if (!selected.value.size) return app.toastMsg('请先选择文件', 'error')
  try {
    const pre = await fileApi.batch({
      file_ids: [...selected.value], action: 'move', folder: moveTarget.value, dry_run: true,
    })
    if (pre.conflict_count) {
      moveConflicts.value = pre
      return
    }
    await runMove('')
  } catch (e) { app.toastMsg(e.message || '移动失败', 'error') }
}
async function runMove(onConflict) {
  const folder = moveConflicts.value ? (moveConflicts.value.target?.id || null) : moveTarget.value
  try {
    const data = { file_ids: [...selected.value], action: 'move', folder }
    if (onConflict) data.on_conflict = onConflict
    const r = await fileApi.batch(data)
    app.toastMsg(r.message || '已移动', 'success')
    moveConflicts.value = null
    showMove.value = false
    selected.value = new Set()
    loadFiles()
  } catch (e) { app.toastMsg(e.message || '移动失败', 'error') }
}
// S24-228 批量复制到目标目录
function openBatchCopy() {
  if (!selected.value.size) return app.toastMsg('请先选择文件', 'error')
  showCopy.value = true
  copyTarget.value = null
}
async function confirmCopy() {
  try {
    const r = await fileApi.batch({ file_ids: [...selected.value], action: 'copy', folder: copyTarget.value })
    app.toastMsg(r.message || '已复制', 'success')
    if ((r.failed || []).length) app.toastMsg(`${r.failed.length} 个文件复制失败`, 'warn')
    showCopy.value = false
    selected.value = new Set()
    loadFiles()
  } catch (e) { app.toastMsg(e.message || '复制失败', 'error') }
}
// S24-235 批量归入收藏分组（分组候选复用 StarredFileView 聚合）
async function openBatchGroup() {
  if (!selected.value.size) return app.toastMsg('请先选择文件', 'error')
  showBatchGroup.value = true
  batchGroupValue.value = ''
  try {
    const r = await fileApi.starred()
    // 后端 groups 为 [{ favorite_group, c }]，这里统一成 name/count
    starGroups.value = (r.groups || [])
      .filter((g) => g.favorite_group)
      .map((g) => ({ name: g.favorite_group, count: g.c }))
  } catch (e) { starGroups.value = [] }
}
async function confirmGroup() {
  try {
    const r = await fileApi.batch({
      file_ids: [...selected.value], action: 'group', group: batchGroupValue.value.trim(),
    })
    app.toastMsg(r.message || '已更新分组', 'success')
    showBatchGroup.value = false
    selected.value = new Set()
    loadFiles()
  } catch (e) { app.toastMsg(e.message || '分组失败', 'error') }
}
async function batchDownload() {
  try {
    const blob = await fileApi.batchDownload([...selected.value])
    saveBlob(blob, '打包下载.zip')
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}
function closeText() { showText.value = false; editingText.value = null; textName.value = ''; textContent.value = '' }

// ---- 多类型在线预览 ----
const previewLabel = computed(() => ({
  image: '图片', video: '视频', audio: '音频', pdf: 'PDF', text: '文本', office: 'Office 文档',
}[previewing.value?.preview_type] || '文件'))

// #4 极简 JPEG EXIF 解析（无依赖）
async function parseExif(rawUrl) {
  exifInfo.value = null
  try {
    const buf = await (await fetch(rawUrl)).arrayBuffer()
    const view = new DataView(buf)
    if (view.getUint16(0) !== 0xFFD8) return // 非 JPEG
    let offset = 2
    while (offset < view.byteLength) {
      const marker = view.getUint16(offset)
      if (marker === 0xFFE1) {
        const tiff = offset + 4
        if (view.getUint32(tiff) !== 0x49492A00) break
        const le = true
        const ifd0 = tiff + view.getUint32(tiff + 4, le)
        const num = view.getUint16(ifd0, le)
        let exifIfd = 0
        for (let i = 0; i < num; i++) {
          const e = ifd0 + 2 + i * 12
          const tag = view.getUint16(e, le)
          const type = view.getUint16(e + 2, le)
          const cnt = view.getUint32(e + 4, le)
          const valOff = tiff + view.getUint32(e + 8, le)
          const str = (p, n) => { let s = ''; for (let k = 0; k < n; k++) s += String.fromCharCode(view.getUint8(p + k)); return s.replace(/\\0.*$/, '') }
          if (tag === 0x010F) exifInfo.value = { ...exifInfo.value, camera: str(valOff, Math.min(cnt, 32)) }
          if (tag === 0x0110) exifInfo.value = { ...exifInfo.value, camera: (exifInfo.value?.camera ? exifInfo.value.camera + ' ' : '') + str(valOff, 32) }
          if (tag === 0x0132 || tag === 0x9003) exifInfo.value = { ...exifInfo.value, taken: str(valOff, 20).trim() }
          if (tag === 0xA002) exifInfo.value = { ...exifInfo.value, w: view.getUint32(valOff, le) }
          if (tag === 0xA003) exifInfo.value = { ...exifInfo.value, h: view.getUint32(valOff, le) }
          if (tag === 0x8769) exifIfd = tiff + view.getUint32(e + 8, le)
        }
        if (exifIfd) {
          const n2 = view.getUint16(exifIfd, le)
          for (let i = 0; i < n2; i++) {
            const e = exifIfd + 2 + i * 12
            const tag = view.getUint16(e, le)
            const valOff = tiff + view.getUint32(e + 8, le)
            if (tag === 0x9003) {
              let s = ''; for (let k = 0; k < 20; k++) s += String.fromCharCode(view.getUint8(valOff + k))
              exifInfo.value = { ...exifInfo.value, taken: s.replace(/\\0.*$/, '').trim() }
            }
          }
        }
        if (exifInfo.value?.w && exifInfo.value?.h) exifInfo.value.dimensions = `${exifInfo.value.w} × ${exifInfo.value.h}`
        break
      }
      offset += 2 + view.getUint16(offset + 2)
    }
  } catch (e) { /* 忽略解析失败 */ }
}

async function openPreview(f) {
  const seq = ++previewSeq
  releaseMedia()
  previewing.value = f
  previewState.value = { preview_url: '' }
  previewContent.value = ''
  exifInfo.value = null
  findText.value = ''
  findPos.value = 0
  // F2：图片/视频/音频/PDF 的直链都要 JWT，改走 blob objectURL
  if (['image', 'video', 'audio', 'pdf'].includes(f.preview_type)) {
    try {
      const m = await loadMediaObjectUrl(
        f.preview_type === 'pdf' ? fileApi.pdfUrl(f.id) : fileApi.rawUrl(f.id),
      )
      if (seq !== previewSeq) { m.revoke(); return }
      mediaUrl.value = m.url
      mediaRevoke = m.revoke
    } catch (e) {
      if (seq === previewSeq) app.toastMsg(await describeDownloadError(e), 'error')
    }
  }
  if (f.preview_type === 'text') {
    const r = await fileApi.preview(f.id)
    if (seq !== previewSeq) return
    previewContent.value = r.content || ''
  } else if (f.preview_type === 'office') {
    const r = await fileApi.preview(f.id)
    if (seq !== previewSeq) return
    previewState.value = r
    if (!r.office_available) officeHint.value = r.office_hint || ''
  } else if (f.preview_type === 'image') {
    parseExif(mediaUrl.value)
  }
}
let previewSeq = 0

// F2：objectURL 生命周期管理——切换/关闭/卸载都必须释放
let mediaRevoke = null
// S2-B1：文件实时事件退订函数（onFileEvent 返回的 cleanup）
let offFileEvent = null
function releaseMedia() {
  if (mediaRevoke) {
    mediaRevoke()
    mediaRevoke = null
  }
  mediaUrl.value = ''
}
onBeforeUnmount(releaseMedia)

function closePreview() {
  releaseMedia()
  previewing.value = null
  previewState.value = {}
  previewContent.value = ''
  exifInfo.value = null
  findText.value = ''
  findPos.value = 0
}

// S24-221 预览内查找：命中全部高亮、n/total、Enter/Shift+Enter 跳转
const findCount = computed(() => {
  const q = findText.value.trim().toLowerCase()
  if (!q) return 0
  const hay = (previewContent.value || '').toLowerCase()
  let i = 0
  let n = 0
  while ((i = hay.indexOf(q, i)) !== -1) { n += 1; i += q.length }
  return n
})
const highlightContent = computed(() => {
  const text = previewContent.value || ''
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const q = findText.value.trim().toLowerCase()
  if (!q) return esc(text)
  const lower = text.toLowerCase()
  const total = findCount.value || 1
  const current = findPos.value % total
  let out = ''
  let i = 0
  let n = 0
  while (true) {
    const at = lower.indexOf(q, i)
    if (at === -1) { out += esc(text.slice(i)); break }
    out += esc(text.slice(i, at))
    const hit = esc(text.slice(at, at + q.length))
    out += n === current
      ? `<mark id="find-hit" style="background:#fb923c;color:#fff">${hit}</mark>`
      : `<mark style="background:#fde68a">${hit}</mark>`
    n += 1
    i = at + q.length
  }
  return out
})
function nextMatch(step) {
  if (!findCount.value) return
  findPos.value = (findPos.value + step + findCount.value) % findCount.value
  nextTick(() => findPre.value?.querySelector('#find-hit')?.scrollIntoView({ block: 'center' }))
}
watch(findText, () => {
  findPos.value = 0
  nextTick(() => findPre.value?.querySelector('#find-hit')?.scrollIntoView({ block: 'center' }))
})

// F2：带 JWT 下载（裸 <a href> 不带令牌会 401）
async function downloadOne(f) {
  if (!f) return
  try {
    await downloadWithAuth(fileApi.downloadUrl(f.id), f.name)
  } catch (e) {
    app.toastMsg(await describeDownloadError(e), 'error')
  }
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
  if (r.truncated) {
    return app.toastMsg('文件超过 256KB，暂不支持在线编辑（避免截断后覆盖原文件）', 'error')
  }
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
function openShare(f) {
  sharing.value = f
  shareIsFolder.value = false
  shareResult.value = null
  shareForm.value = { permission: 'view', expire_hours: null, password: '', max_downloads: null, allow_upload: false }
}
// S24-223 文件夹分享（可开启访客上传，形成收集链接）
function shareFolder(f) {
  sharing.value = f
  shareIsFolder.value = true
  shareResult.value = null
  shareForm.value = { permission: 'download', expire_hours: null, password: '', max_downloads: null, allow_upload: true }
}
async function createShare() {
  if (creatingShare.value) return  // 防双击生成两条链接
  creatingShare.value = true
  try {
    const payload = shareIsFolder.value
      ? { folder_id: sharing.value.id, ...shareForm.value }
      : { file_id: sharing.value.id, ...shareForm.value }
    Object.keys(payload).forEach((k) => (payload[k] === '' || payload[k] === null || payload[k] === false) && delete payload[k])
    shareResult.value = await fileApi.createShare(payload)
    let copied = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl())
        copied = true
      }
    } catch { /* 剪贴板不可用（非 HTTPS/权限拒绝）时降级为手动复制 */ }
    app.toastMsg(copied ? '链接已复制' : '分享已创建，请手动复制链接', copied ? 'success' : 'warn')
  } catch (e) {
    app.toastMsg(e?.message || '生成分享链接失败', 'error')
  } finally {
    creatingShare.value = false
  }
}
// S24-230 分享结果可复制 Markdown / HTML（带可读文件名）
async function copyText(text, okMsg = '已复制') {
  try {
    await navigator.clipboard.writeText(text)
    app.toastMsg(okMsg, 'success')
  } catch (e) { app.toastMsg('剪贴板不可用，请手动复制', 'warn') }
}
function shareTitle() {
  const n = sharing.value?.name || '文件'
  return n.replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]))
}
function copyMarkdown() { copyText(`[${shareTitle()}](${shareUrl()})`, 'Markdown 已复制') }
function copyHtml() { copyText(`<a href="${shareUrl()}">${shareTitle()}</a>`, 'HTML 已复制') }
// F4：对外链接统一走 base.js 的 shareUrl()（VITE_PUBLIC_BASE + /share/:token），
// 不再本地拼 location.origin，部署到 CF Pages 时也能给出正确地址
const shareUrl = () => shareResult.value ? buildShareUrl(shareResult.value.token) : ''
function pickFiles() { fileInput.value?.click() }
async function onFilePicked(e) {
  const list = Array.from(e.target.files || [])
  e.target.value = ''
  // S24-233 续传：必须重新选择本地同名文件（浏览器不允许持久化 File 对象）
  if (resumeTarget.value) {
    const target = resumeTarget.value
    resumeTarget.value = null
    const picked = list.find((f) => f.name === target.name)
    if (!picked) return app.toastMsg('请选择与记录同名的文件以继续上传', 'error')
    const batch = [{ name: picked.name, progress: 0, status: 'uploading' }]
    uploadQueue.value = batch
    await uploadOne(picked, 0, batch, target.folder ?? null, target.upload_id)
    return
  }
  // #2 多文件队列（batch 引用固定，避免新一批覆盖后旧批次写错行）
  const batch = list.map((f) => ({ name: f.name, progress: 0, status: 'uploading' }))
  uploadQueue.value = batch
  list.forEach((f, i) => uploadOne(f, i, batch))
}

// S24-216 上传重名策略记忆
function loadUploadConflict() {
  try { uploadConflict.value = localStorage.getItem('files.uploadConflict') || 'rename' } catch (e) { /* ignore */ }
}
function saveUploadConflict() {
  try { localStorage.setItem('files.uploadConflict', uploadConflict.value) } catch (e) { /* ignore */ }
}

// S24-233 断点续传：upload_id / 文件名 / 已完成分片数落 localStorage
const RESUME_KEY = 'files.uploads'
function loadResumeMap() {
  try { return JSON.parse(localStorage.getItem(RESUME_KEY) || '{}') || {} } catch (e) { return {} }
}
function saveResumeMap(map) {
  try { localStorage.setItem(RESUME_KEY, JSON.stringify(map)) } catch (e) { /* ignore */ }
}
function setResume(uploadId, patch) {
  const map = loadResumeMap()
  map[uploadId] = { ...(map[uploadId] || {}), ...patch }
  saveResumeMap(map)
}
function clearResume(uploadId) {
  const map = loadResumeMap()
  if (!(uploadId in map)) return
  delete map[uploadId]
  saveResumeMap(map)
  pendingUploads.value = pendingUploads.value.filter((p) => p.upload_id !== uploadId)
}
async function validateResume() {
  const map = loadResumeMap()
  const rows = []
  for (const [uploadId, info] of Object.entries(map)) {
    try {
      const s = await fileApi.uploadStatus(uploadId)
      if (s.status !== 'uploading') { clearResume(uploadId); continue }
      rows.push({
        upload_id: uploadId, name: s.filename || info.name,
        total: s.total_chunks || info.total || 0, done: (s.uploaded || []).length,
        folder: info.folder ?? null,
      })
    } catch (e) { clearResume(uploadId) }
  }
  pendingUploads.value = rows
}
function dropResume(uploadId) { clearResume(uploadId) }
function resumeUpload(p) { resumeTarget.value = p; fileInput.value?.click() }

async function uploadOne(file, idx, batch, targetFolderId, resumeId) {
  // 单文件才用全局进度条；多文件并行时进度以 uploadQueue 各自为准，避免数值乱跳
  const single = uploadQueue.value.length <= 1
  // 进入上传即快照目录：await sha1 期间用户切目录不应改变目标位置
  const folderId = targetFolderId !== undefined ? targetFolderId : currentFolder.value
  const updateRow = (patch) => {
    if (idx != null && uploadQueue.value === batch && batch[idx]) {
      uploadQueue.value[idx] = { ...uploadQueue.value[idx], ...patch }
    }
  }
  uploading.value = true
  if (single) {
    uploadName.value = file.name
    uploadProgress.value = 0
  }
  try {
    let init
    if (resumeId) {
      // 续传：沿用已有 upload_id 与已上传分片
      const st = await fileApi.uploadStatus(resumeId)
      init = { sec_pass: false, upload_id: resumeId, uploaded: st.uploaded || [] }
    } else {
      // F14：先算真实 sha1 让秒传真正生效（后端 uploadInit 按 sha1+owner 命中已存在文件）。
      // 计算失败（极端环境）降级为空串——后端按无秒传处理，只是少一个优化。
      let sha1 = ''
      try {
        sha1 = await sha1File(file)
      } catch {
        sha1 = ''
      }
      const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))
      init = await fileApi.uploadInit({ filename: file.name, folder_id: folderId, file_size: file.size, chunk_size: CHUNK_SIZE, total_chunks: totalChunks, sha1 })
      if (init.sec_pass) {
        updateRow({ progress: 100, status: 'done' })
        app.toastMsg('秒传成功', 'success'); return
      }
    }
    const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))
    setResume(init.upload_id, { name: file.name, total: totalChunks, size: file.size, folder: folderId })
    for (let i = 0; i < totalChunks; i++) {
      if (init.uploaded?.includes(i)) continue
      const blob = file.slice(i * CHUNK_SIZE, i * CHUNK_SIZE + CHUNK_SIZE)
      const fd = new FormData()
      fd.append('upload_id', init.upload_id)
      fd.append('index', i)
      fd.append('chunk', blob, `${file.name}.part${i}`)
      await fileApi.uploadChunk(fd)
      setResume(init.upload_id, { done: i + 1 })
      const pct = Math.round(((i + 1) / totalChunks) * 90)
      if (single) uploadProgress.value = pct
      updateRow({ progress: pct, status: 'uploading' })
    }
    // S24-216 完成时按上传设置处理重名
    const done = await request.post('/files/upload/complete/', {
      upload_id: init.upload_id, on_conflict: uploadConflict.value,
    })
    clearResume(init.upload_id)
    if (single) uploadProgress.value = 100
    if (done?.skipped?.length) {
      updateRow({ progress: 100, status: 'done' })
      app.toastMsg(`「${file.name}」同名已跳过`, 'info')
      return
    }
    if (done?.overwritten) app.toastMsg(`已覆盖同名文件「${file.name}」`, 'info')
    else if (done && done.renamed) app.toastMsg(`重名，已自动改名为「${done.renamed.final}」`, 'info')
    updateRow({ progress: 100, status: 'done' })
    app.toastMsg(`${file.name} 上传完成`, 'success')
    loadFiles()
  } catch (e) {
    app.toastMsg(`${file.name} 上传失败：${e.message}`, 'error')
    updateRow({ status: 'error' })
  } finally {
    // 并行上传时，任何一个结束都不能把整体状态置为「已完成」
    uploading.value = uploadQueue.value.some((q) => q.status === 'uploading')
  }
}

// ================= F547–F564 文件中心新增能力 =================

// F550 文件清单导出 CSV（带 JWT 走 blob 下载）
async function exportCsv() {
  try {
    const params = {}
    if (keyword.value) params.keyword = keyword.value
    if (kindFilter.value) params.kind = kindFilter.value
    if (activeFileTag.value) params.tag = activeFileTag.value
    if (quickFilter.value === 'starred') params.star = 1
    await downloadWithAuth(filesx.exportCsvUrl(params), '文件清单.csv')
    app.toastMsg('已导出 CSV', 'success')
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}

// F553 图片分辨率批量徽章（后端计算并缓存，失败静默降级）
async function loadDims() {
  const IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'avif']
  const pending = files.value.filter((f) =>
    (f.kind === 'image' || IMAGE_EXTS.includes((f.ext || '').toLowerCase())) &&
    !dims.value[f.id] && !(f.width && f.height))
  if (!pending.length) return
  try {
    const r = await filesx.imageDims(pending.map((f) => f.id))
    const next = { ...dims.value }
    ;(r.list || []).forEach((d) => { if (d.label) next[d.id] = d.label })
    dims.value = next
  } catch (e) { /* 降级：不显示徽章 */ }
}
function dimLabel(f) {
  if (dims.value[f.id]) return dims.value[f.id]
  if (f.width && f.height) return `${f.width}×${f.height}`
  return ''
}

// F555 收藏夹自定义排序（上移/下移后持久化）
async function moveStar(f, dir) {
  const list = [...files.value]
  const idx = list.findIndex((x) => x.id === f.id)
  const j = idx + dir
  if (idx < 0 || j < 0 || j >= list.length) return
  const tmp = list[idx]
  list[idx] = list[j]
  list[j] = tmp
  files.value = list
  try {
    await filesx.starOrder(list.map((x) => x.id))
    app.toastMsg('收藏排序已保存', 'success')
  } catch (e) { app.toastMsg(e.message || '排序失败', 'error'); loadFiles() }
}

// F556 文件夹搜索命中计数徽章
async function loadFolderHits() {
  if (!keyword.value) {
    folderHits.value = {}
    folderHitIds.value = {}
    folderHitList.value = []
    folderHitsTotal.value = 0
    return
  }
  try {
    const r = await filesx.folderHits(keyword.value)
    const map = {}
    const ids = {}
    ;(r.hits || []).forEach((h) => {
      map[h.folder_id] = h.count
      ids[h.folder_id] = h.ids || []
    })
    folderHits.value = map
    folderHitIds.value = ids
    folderHitList.value = (r.hits || []).slice(0, 12)
    folderHitsTotal.value = r.total || 0
  } catch (e) {
    folderHits.value = {}
    folderHitIds.value = {}
    folderHitList.value = []
    folderHitsTotal.value = 0
  }
}
function filterHits(folderId) {
  hitFilterFolder.value = folderId
  loadFiles()
}

// F558 预览缩放记忆
function loadZoom() {
  try {
    const v = parseInt(localStorage.getItem('files.previewZoom'), 10)
    if (v >= 25 && v <= 400) zoom.value = v
  } catch (e) { /* ignore */ }
}
function changeZoom(step) {
  zoom.value = Math.min(400, Math.max(25, zoom.value + step))
  try { localStorage.setItem('files.previewZoom', String(zoom.value)) } catch (e) { /* ignore */ }
}

// F559 移动/复制操作记录
async function openOps() {
  showOps.value = true
  await loadOps()
}
async function loadOps() {
  try {
    const r = await filesx.operations({ action: opsAction.value, limit: 100 })
    opsList.value = r.list || []
  } catch (e) { opsList.value = [] }
}
// S24-220 操作热力图
async function toggleHeatmap() {
  showHeatmap.value = !showHeatmap.value
  if (showHeatmap.value && !(heatmap.value.days_list || []).length) {
    try { heatmap.value = await filesx.opsHeatmap(180) } catch (e) { heatmap.value = {} }
  }
}
function heatColor(n) {
  if (!n) return '#eef2f6'
  const ratio = n / (heatmap.value.max || 1)
  if (ratio > 0.75) return '#0369a1'
  if (ratio > 0.5) return '#0ea5e9'
  if (ratio > 0.25) return '#7dd3fc'
  return '#bae6fd'
}

// F561 文件可见性快照
async function openVisibility(f) {
  visTarget.value = f
  visState.value = null
  try {
    visState.value = await filesx.visibility(f.id)
  } catch (e) {
    app.toastMsg(e.message || '加载失败', 'error')
    visTarget.value = null
  }
}
async function takeSnapshot() {
  if (!visTarget.value) return
  try {
    await filesx.takeVisibilitySnapshot(visTarget.value.id, '手动记录')
    visState.value = await filesx.visibility(visTarget.value.id)
    app.toastMsg('已记录可见性快照', 'success')
  } catch (e) { app.toastMsg(e.message || '记录失败', 'error') }
}

// F563 标签统计与点击过滤
async function openTagStats() {
  showTagStats.value = true
  mergeFrom.value = null
  mergeTo.value = null
  try { tagStats.value = await filesx.tagsStats() } catch (e) { tagStats.value = {} }
}
// S24-217 合并标签
async function doTagMerge() {
  if (!mergeFrom.value || !mergeTo.value || mergeFrom.value === mergeTo.value) return
  if (!confirm('合并后来源标签会被删除，确认合并？')) return
  try {
    const r = await filesx.tagMerge(mergeFrom.value, mergeTo.value)
    app.toastMsg(r.message || '已合并标签', 'success')
    await openTagStats()
    loadFileTags()
    loadFiles()
  } catch (e) { app.toastMsg(e.message || '合并失败', 'error') }
}
// S24-224 文本文件转为笔记
async function toNote(f) {
  try {
    const r = await filesx.toNote(f.id)
    app.toastMsg(`已转为笔记「${r.title}」（${r.words} 字）`, 'success')
  } catch (e) { app.toastMsg(e.message || '转为笔记失败', 'error') }
}
// S24-226 移除单条最近访问
async function removeRecent(f) {
  try {
    await filesx.removeRecent(f.id)
    files.value = files.value.filter((x) => x.id !== f.id)
    app.toastMsg('已移除该记录', 'success')
  } catch (e) { app.toastMsg(e.message || '移除失败', 'error') }
}

// F564 收藏/标签导出导入 JSON
async function exportFavJson() {
  try {
    const blob = await filesx.favoritesExport()
    saveBlob(blob, '收藏与标签.json')
    app.toastMsg('已导出收藏与标签 JSON', 'success')
  } catch (e) { app.toastMsg(await describeDownloadError(e), 'error') }
}
function pickFavJson() { favInput.value?.click() }
async function onFavPicked(e) {
  const file = (e.target.files || [])[0]
  e.target.value = ''
  if (!file) return
  try {
    const text = await file.text()
    let payload
    try {
      payload = JSON.parse(text)
    } catch (err) { app.toastMsg('不是合法的 JSON 文件', 'error'); return }
    const r = await filesx.favoritesImport(payload)
    app.toastMsg(r.message || '导入完成', 'success')
    loadFiles()
    loadFileTags()
  } catch (err) { app.toastMsg(err.message || '导入失败', 'error') }
}

// #10 空格键快速预览
function onKeydown(e) {
  const tag = (e.target.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return
  if (e.code === 'Space' && focusedId.value) {
    const f = files.value.find((x) => x.id === focusedId.value)
    if (f && f.previewable) { e.preventDefault(); openPreview(f) }
  }
}

onMounted(() => {
  loadPrefs()
  loadZoom()
  loadSearchHistory()
  loadUploadConflict()
  validateResume()
  loadFolders(); loadFileTags(); loadFolderTemplates()
  // F23：从全局搜索带 ?q= 跳入时填充关键词并直接搜索（原来只落模块首页，不定位）
  const q = route.query.q
  if (q) {
    keyword.value = String(q)
    loadFiles()
  } else {
    loadFiles()
  }
  window.addEventListener('keydown', onKeydown)
  // S2-B1：订阅文件实时事件（多标签页/多端同步）——上传/删除/更新后静默刷新
  offFileEvent = app.onFileEvent((type, data) => {
    if (data?.action === 'uploaded' || data?.action === 'deleted' || data?.action === 'updated') {
      // #142 实时刷新保留已选文件，批量操作不中断
      loadFiles(true)
    }
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  offFileEvent?.()
})
</script>
