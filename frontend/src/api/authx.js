/**
 * 账号个人能力扩展接口（F613–F626）
 *
 * 与 src/api/index.js 的 authApi 互补：本次只新增文件，不改动既有文件。
 * 所有路径都以 /api 为前缀（request 的 baseURL 已带 /api）。
 */
import request from './request'

export const authxApi = {
  // ---- F614 注销申请（7 天冷静期，可撤销）----
  deactivateState: () => request.get('/auth/profile/deactivate-request/'),
  requestDeactivate: (data) => request.post('/auth/profile/deactivate-request/', data),
  cancelDeactivate: () => request.post('/auth/profile/deactivate-request/cancel/', {}),

  // ---- F615 TOTP 双因素 ----
  totpStatus: () => request.get('/auth/profile/2fa/'),
  totpSetup: () => request.post('/auth/profile/2fa/setup/', {}),
  totpVerify: (data) => request.post('/auth/profile/2fa/verify/', data),

  // ---- F616 安全评分卡 ----
  securityScore: () => request.get('/auth/profile/security-score/'),

  // ---- F617 个人公开主页 ----
  publicProfile: (username) => request.get(`/auth/profile/public/${encodeURIComponent(username)}/`),

  // ---- F618 关注 / 粉丝 ----
  followToggle: (username) => request.post(`/auth/profile/follow/${encodeURIComponent(username)}/`, {}),
  followList: (type = 'following', limit = 50) =>
    request.get('/auth/profile/follow/', { params: { type, limit } }),

  // ---- F619 新手任务清单（6 步引导）----
  onboarding: () => request.get('/auth/profile/onboarding/'),

  // ---- F620 时区与周起始日偏好 ----
  preferences: () => request.get('/auth/profile/preferences/'),
  savePreferences: (data) => request.put('/auth/profile/preferences/', data),

  // ---- F621 长期访问令牌 PAT ----
  tokens: () => request.get('/auth/profile/tokens/'),
  createToken: (data) => request.post('/auth/profile/tokens/', data),
  revokeToken: (id) => request.delete(`/auth/profile/tokens/${id}/`),

  // ---- F622 昵称变更历史 ----
  nicknameHistory: () => request.get('/auth/profile/nickname-history/'),

  // ---- F623 头像历史切换 ----
  avatarHistory: () => request.get('/auth/profile/avatar/history/'),
  restoreAvatar: (id) => request.post(`/auth/profile/avatar/history/${id}/restore/`, {}),

  // ---- F624 通讯录备注名（仅自己可见）----
  contacts: () => request.get('/auth/profile/contacts/'),
  saveContact: (data) => request.post('/auth/profile/contacts/', data),
  deleteContact: (id) => request.delete(`/auth/profile/contacts/${id}/`),

  // ---- F625 邀请效果看板 ----
  inviteDashboard: () => request.get('/auth/profile/invite-dashboard/'),

  // ---- F636 角色变更历史（管理员）----
  roleAudit: (params) => request.get('/auth/admin/role-audit/', { params }),
}

export default authxApi
