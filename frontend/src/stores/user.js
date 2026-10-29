import { defineStore } from 'pinia'
import { authApi } from '../api'

// localStorage 里的 JSON 可能被手工改坏/写入半截 → 解析失败时清掉并回落默认值，
// 否则异常会在 app.mount 之前抛出，整站白屏且无法自愈。
function loadJson(key, fallback) {
  const raw = localStorage.getItem(key)
  if (!raw) return fallback
  try {
    return JSON.parse(raw)
  } catch {
    localStorage.removeItem(key)
    return fallback
  }
}

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('access_token') || '',
    refresh: localStorage.getItem('refresh_token') || '',
    profile: loadJson('user_profile', null),
    permissions: loadJson('user_permissions', []),
    isAdmin: localStorage.getItem('is_admin') === '1',
  }),
  getters: {
    loggedIn: (s) => !!s.token,
    displayName: (s) => s.profile?.nickname || s.profile?.username || '未登录',
    hasPerm: (s) => (code) => s.isAdmin || s.permissions.includes(code),
  },
  actions: {
    setTokens(access, refresh) {
      this.token = access
      this.refresh = refresh
      localStorage.setItem('access_token', access)
      localStorage.setItem('refresh_token', refresh)
    },
    setProfile(p) {
      this.profile = p
      localStorage.setItem('user_profile', JSON.stringify(p))
    },
    async login(data) {
      const res = await authApi.login(data)
      this.setTokens(res.access, res.refresh)
      this.setProfile(res.user)
      await this.fetchPermissions()
    },
    async register(data) {
      const res = await authApi.register(data)
      this.setTokens(res.access, res.refresh)
      this.setProfile(res.user)
      await this.fetchPermissions()
    },
    async fetchProfile() {
      try {
        const p = await authApi.profile()
        this.setProfile(p)
        return p
      } catch (e) {
        return null
      }
    },
    async fetchPermissions() {
      try {
        const r = await authApi.myPermissions()
        this.permissions = r.permissions || []
        this.isAdmin = !!r.is_admin
        localStorage.setItem('user_permissions', JSON.stringify(this.permissions))
        localStorage.setItem('is_admin', this.isAdmin ? '1' : '0')
      } catch (e) {
        // 网络抖动时保留上一次已知权限（后端仍有鉴权），不要把管理员菜单打没
      }
    },
    async refreshProfile() {
      await this.fetchProfile()
    },
    async logout() {
      try {
        await authApi.logout(this.refresh)
      } catch (e) { /* ignore */ }
      this.token = ''
      this.refresh = ''
      this.profile = null
      this.permissions = []
      this.isAdmin = false
      // 只清认证数据，保留 theme / 快捷入口 / 侧边栏折叠等本地偏好
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user_profile')
      localStorage.removeItem('user_permissions')
      localStorage.removeItem('is_admin')
    },
  },
})
