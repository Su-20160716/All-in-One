import axios from 'axios'
import { API_URL, rewriteBackendUrls } from './base'

const request = axios.create({
  baseURL: API_URL,
  timeout: 60000,
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshing = null

request.interceptors.response.use(
  (res) => rewriteBackendUrls(res.data),
  async (error) => {
    const { response, config } = error
    if (response && response.status === 401 && !config._retry) {
      config._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          refreshing = refreshing || axios.post(`${API_URL}/auth/refresh/`, { refresh }).then((r) => r.data)
          const { access } = await refreshing
          refreshing = null
          localStorage.setItem('access_token', access)
          config.headers.Authorization = `Bearer ${access}`
          return request(config)
        } catch (e) {
          refreshing = null
          localStorage.clear()
          window.location.href = '/login'
        }
      } else {
        window.location.href = '/login'
      }
    }
    const message =
      response?.data?.message || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

export default request
