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
        <h3 class="mb-3 text-[14px] font-semibold text-ink-800">🔒 此链接需要访问密码</h3>
        <div class="flex gap-2">
          <input v-model="password" class="input flex-1" type="password" placeholder="请输入访问密码"
                 @keyup.enter="submitPassword" />
          <button class="btn-primary" @click="submitPassword">验证</button>
        </div>
        <p v-if="pwError" class="mt-2 text-[12px] text-rose-500">{{ pwError }}</p>
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
          <img :src="mediaUrl" class="max-h-[60vh] rounded-control object-contain" />
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

        <!-- 其他类型：仅提示 -->
        <div v-else class="p-8 text-center text-[12px] text-ink-400">该类型不支持在线预览，请下载后查看</div>
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
import { API_URL, withBackendBase } from '../../api/base'
import { saveBlob } from '../../utils/download'
import { formatSize } from '../../utils/format'

const route = useRoute()
const token = computed(() => route.params.token)

const loading = ref(true)
const error = ref('')
const data = ref(null)
const needPassword = ref(false)
const password = ref('')
const pwError = ref('')
const mediaUrl = ref('')

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await axios.get(`${API_URL}/share/${token.value}/`, {
      params: password.value ? { password: password.value } : {},
    })
    if (r.status === 200) {
      data.value = r.data
      needPassword.value = false
      // 图片走带补全的媒体地址（/media/... 相对路径）
      if (r.data.type === 'file' && r.data.kind === 'image' && r.data.url) {
        mediaUrl.value = withBackendBase(r.data.url)
      }
    }
  } catch (e) {
    const status = e?.response?.status
    const msg = e?.response?.data?.message || e?.response?.data?.error
    if (status === 401 && !password.value) {
      needPassword.value = true
    } else if (status === 401) {
      pwError.value = msg || '密码错误'
      needPassword.value = true
    } else if (status === 404) {
      error.value = '链接不存在或已被撤销'
    } else if (status === 410) {
      error.value = msg || '链接已过期'
    } else if (status === 429) {
      error.value = msg || '下载次数已达上限'
    } else {
      error.value = msg || '加载失败'
    }
  } finally {
    loading.value = false
  }
}

async function submitPassword() {
  pwError.value = ''
  if (!password.value) {
    pwError.value = '请输入密码'
    return
  }
  await load()
}

async function downloadFile(id, name) {
  try {
    const r = await axios.get(`${API_URL}/share/${token.value}/download/${id}/`, {
      responseType: 'blob',
      params: password.value ? { password: password.value } : {},
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
    alert(hint || '下载失败')
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
