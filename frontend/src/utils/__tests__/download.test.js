import { describe, expect, it } from 'vitest'
import { normalizeApiUrl } from '../download'

describe('normalizeApiUrl', () => {
  it('去掉相对路径的 /api 前缀（axios 实例已带 baseURL）', () => {
    expect(normalizeApiUrl('/api/files/1/raw/')).toBe('/files/1/raw/')
  })

  it('保留绝对地址', () => {
    expect(normalizeApiUrl('https://api.example.com/api/files/1/')).toBe('https://api.example.com/api/files/1/')
  })

  it('非 /api 相对路径原样返回', () => {
    expect(normalizeApiUrl('/media/a.png')).toBe('/media/a.png')
  })

  it('空值原样返回', () => {
    expect(normalizeApiUrl('')).toBe('')
  })
})
