<template>
  <div class="flex min-h-screen items-center justify-center bg-ink-50 p-4">
    <div class="w-full max-w-2xl">
      <!-- 头部 -->
      <div class="mb-4 text-center">
        <div class="text-[13px] text-ink-400">全能协作平台 · 文件分享</div>
      </div>

      <!-- 加载中 -->
      <div v-if="loading" class="card p-10 text-center text-[13px] text-ink-400">加载中…</div>

      <!-- 错误 / 不存在 / 过期 / 撤销 -->
      <div v-else-if="error" class="card p-10 text-center">
        <div class="text-[32px]">🔗</div>
        <div class="mt-2 text-[14px] font-medium text-ink-700">{{ error }}</div>
        <div class="mt-1 text-[12px] text-ink-400">请联系分享者确认链接状态</div>
      </div>

      <!-- 需要密码 -->
      <div v-else-if="needPassword" class="card p-6">
        <h3 class="mb-3 text-[14px] font-semibold text-ink-800">🔒 {{ t('files.needPassword', '此链接需要访问密码') }}</h3>
        <div class="flex gap-2">
          <!-- #191 密码框通过 aria-describedby 关联错误提示，读屏可播报 -->
          <input v-model="password" class="input flex-1" type="password" placeholder="请输入访问密码"
                 :aria-invalid="!!pwError"
                 :aria-describedby="pwError ? 'share-pw-error' : undefined"
                 @keyup.enter="submitPassword" />
          <button class="btn-primary" @click="submitPassword">验证</button>
        </div>
        <p v-if="pwError" id="share-pw-error" role="alert" class="mt-2 text-[12px] text-rose-500">{{ pwError }}</p>
      </div>

      <!-- 内容 -->
      <div v-else-if="data" class="card overflow-hidden">
        <div class="flex items-center gap-3 border-b border-ink-100 px-4 py-3">
          <span class="text-[20px]">{{ iconOf(data) }}</span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[14px] font-semibold text-ink-800">{{ data.name }}</div>
            <div class="text-[12px] text-ink-400">
              {{ data.type === 'folder' ? `${data.files.length} 个文件` : sizeText(data.size) }}
              · {{ data.permission === 'download' || data.permission === 'edit' ? '可下载' : '仅预览' }}
            </div>
          </div>
          <button v-if="data.type === 'file' && data.can_download" class="btn-primary px-3 text-[12px]"
                  @click="downloadFile(data.id, data.name)">⬇ 下载</button>
        </div>

        <!-- 图片预览 -->
        <div v-if="data.type === 'file' && data.kind === 'image' && mediaUrl" class="flex justify-center bg-ink-50 p-4">
          <img :src="mediaUrl" :alt="`${data.name} 预览图`" class="max-h-[60vh] rounded-control object-contain" />
        </div>

        <!-- 文本预览 -->
        <pre v-else-if="data.type === 'file' && data.preview"
             class="max-h-[55vh] overflow-auto bg-ink-50 p-4 text-[12px] leading-relaxed text-ink-700">{{ data.preview }}</pre>

        <!-- 文件夹列表 -->
        <div v-else-if="data.type === 'folder'" class="divide-y divide-ink-50">
          <div v-for="f in data.files" :key="f.id" class="flex items-center gap-3 px-4 py-2.5">
            <span class="text-[16px]">{{ kindIcon(f.kind) }}</span>
            <div class="min-w-0 flex-1">
              <div class="truncate text-[13px] text-ink-700">{{ f.name }}</div>
              <div class="text-[11px] text-ink-400">{{ sizeText(f.size) }}</div>
            </div>
            <button v-if="data.permission === 'download' || data.permission === 'edit'"
                    class="btn-ghost px-2 text-[12px] text-brand-600"
                    @click="downloadFile(f.id, f.name)">下载</button>
          </div>
          <div v-if="!data.files.length" class="py-8 text-center text-[12px] text-ink-400">文件夹为空</div>
        </div>

        <!-- S24-223 收集上传：开启 allow_upload 的文件夹分享可直接投递文件 -->
        <div v-if="data.type === 'folder' && data.allow_upload" class="border-t border-ink-100 p-4">
          <div class="mb-2 text-[13px] font-medium text-ink-700">上传文件到该文件夹</div>
          <div class="flex flex-wrap items-center gap-2 text-[12px]">
            <input ref="uploadInput" type="file" class="hidden" @change="pickUpload" />
            <button class="btn-outline px-2" @click="uploadInput?.click()">选择文件</button>
            <span class="text-ink-400">单个文件 ≤ {{ data.upload_max_mb || 50 }}MB，同名自动加序号</span>
            <button class="btn-primary px-3" :disabled="uploading || !uploadFile" @click="doUpload">
              {{ uploading ? '上传中…' : '上传' }}
            </button>
          </div>
          <div v-if="uploadFile" class="mt-1 truncate text-[12px] text-ink-500">已选择：{{ uploadFile.name }}</div>
          <div v-if="uploadMsg" class="mt-1 text-[12px]" :class="uploadError ? 'text-rose-600' : 'text-emerald-600'">{{ uploadMsg }}</div>
        </div>

        <!-- 其他类型：仅提示 -->
        <div v-else-if="data.type === 'file'" class="p-8 text-center text-[12px] text-ink-400">该类型不支持在线预览，请下载后查看</div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * F3 文件共享落地页（公开，免登录）
 *
 * 路由：/share/:token（前端 history 路由，与后端 API /api/share/<token>/ 解耦）
 * 数据：GET /api/share/<token>/（AllowAny；密码通过 ?password= 校验）
 * 下载：GET /api/share/<token>/download/<pk>/（同样免登录，受 max_downloads 限制）
 *
 * 注意：这里必须用**裸 axios**——项目 request 实例的 401 拦截器会跳 /login，
 * 而公开页的 401/403 是「密码错误/次数超限」这类业务结果，不能跳登录。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { onBeforeUnmount } from 'vue'
import { API_URL, apiUrl } from '../../api/base'
import { saveBlob } from '../../utils/download'
import { formatSize } from '../../utils/format'
import { t } from '../../i18n'

const route = useRoute()
const token = computed(() => route.params.token)

const loading = ref(true)
const error = ref('')
const data = ref(null)
const needPassword = ref(false)
const password = ref('')
const pwError = ref('')
const mediaUrl = ref('')
let mediaObjectUrl = ''
// S24-223 收集上传
const uploadInput = ref(null)
const uploadFile = ref(null)
const uploading = ref(false)
const uploadMsg = ref('')
const uploadError = ref(false)
function pickUpload(e) {
  uploadFile.value = (e.target.files || [])[0] || null
  e.target.value = ''
  uploadMsg.value = ''
}
async function doUpload() {
  if (!uploadFile.value || uploading.value) return
  uploading.value = true
  uploadMsg.value = ''
  try {
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    const r = await axios.post(`${API_URL}/share/${token.value}/upload/`, fd, { headers: pwHeaders() })
    uploadMsg.value = r.data?.message || '上传成功'
    uploadError.value = false
    uploadFile.value = null
    await load()
  } catch (e) {
    uploadError.value = true
    uploadMsg.value = e?.response?.data?.message || t('files.uploadFailed', '上传失败')
  } finally {
    uploading.value = false
  }
}
function releaseMedia() {
  if (mediaObjectUrl) {
    URL.revokeObjectURL(mediaObjectUrl)
    mediaObjectUrl = ''
  }
  mediaUrl.value = ''
}
onBeforeUnmount(releaseMedia)
// 密码放请求头而不是查询串，避免进入浏览器历史、Referer 与访问日志
function pwHeaders() {
  return password.value ? { 'X-Share-Password': password.value } : {}
}

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await axios.get(`${API_URL}/share/${token.value}/`, { headers: pwHeaders() })
    if (r.status === 200) {
      data.value = r.data
      needPassword.value = false
      // 图片必须带密码读取：先拉 blob 再转 objectURL，URL 中不再出现密码
      if (r.data.type === 'file' && r.data.kind === 'image' && r.data.url) {
        try {
          const br = await axios.get(apiUrl(r.data.url), { responseType: 'blob', headers: pwHeaders() })
          releaseMedia()
          mediaObjectUrl = URL.createObjectURL(br.data)
          mediaUrl.value = mediaObjectUrl
        } catch (e) {
          mediaUrl.value = ''
        }
      }
    }
  } catch (e) {
    const status = e?.response?.status
    const msg = e?.response?.data?.message || e?.response?.data?.error
    if (status === 401 && !password.value) {
      needPassword.value = true
    } else if (status === 401) {
      pwError.value = msg || t('files.passwordWrong', '密码错误')
      needPassword.value = true
    } else if (status === 404) {
      error.value = t('files.linkMissing', '链接不存在或已被撤销')
    } else if (status === 410) {
      error.value = msg || t('files.linkExpired', '链接已过期')
    } else if (status === 429) {
      error.value = msg || t('files.downloadLimit', '下载次数已达上限')
    } else {
      error.value = msg || t('common.loadFailed', '加载失败')
    }
  } finally {
    loading.value = false
  }
}

async function submitPassword() {
  pwError.value = ''
  if (!password.value) {
    pwError.value = t('files.passwordSubmit', '请输入密码')
    return
  }
  await load()
}

async function downloadFile(id, name) {
  try {
    const r = await axios.get(`${API_URL}/share/${token.value}/download/${id}/`, {
      responseType: 'blob',
      headers: pwHeaders(),
    })
    saveBlob(r.data, name || 'download')
  } catch (e) {
    const msg = e?.response?.data?.message
    // blob 错误体尝试解析
    let hint = msg
    if (!hint && e?.response?.data instanceof Blob) {
      try {
        hint = JSON.parse(await e.response.data.text()).message
      } catch {
        /* ignore */
      }
    }
    alert(hint || t('files.downloadFailed', '下载失败'))
  }
}

function iconOf(d) {
  if (d.type === 'folder') return '📁'
  return kindIcon(d.kind)
}
function kindIcon(kind) {
  return { image: '🖼', video: '🎬', audio: '🎵', archive: '📦', text: '📄' }[kind] || '📄'
}
function sizeText(n) {
  return formatSize(n || 0)
}
</script>
