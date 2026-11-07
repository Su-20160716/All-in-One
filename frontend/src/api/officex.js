/**
 * 办公套件 S26 前端接线（条目 354/355/357/358/359/360/361/362/363）。
 *
 * 与 api/projectsx.js 同风格：只收敛「第三轮新增/此前前端未接线」的 officesuite 接口，
 * 沿用 request 的 Bearer / 刷新 / 错误文案统一处理。
 *
 * 后端 officesuite 端点在 devtools.endpoint 下统一返回 {ok, data}；
 * 这里用 unwrap 把 data 拍平，页面里直接拿业务字段（错误仍是 reject，由页面 catch + toast）。
 * 附件流（export/ics）不做拆包，返回 Blob。
 */
import request from './request'
import { apiUrl } from './base'

const D = '/officesuite'

function unwrap(p) {
  return p.then((r) => (r && typeof r === 'object' && r.ok === true && r.data !== undefined ? r.data : r))
}

export const officex = {
  // ---------------- 354 待办四象限 ----------------
  // POST todo/quadrant/ → {date, quadrants|groups[{key,name,hint,accent,count,items}], counts, total}
  todoQuadrant: () => unwrap(request.post(`${D}/todo/quadrant/`, {})),
  // 老接口：完成 / 重开单条待办
  todoComplete: (pk) => unwrap(request.post(`${D}/todo/${pk}/complete/`, {})),
  todoReopen: (pk) => unwrap(request.post(`${D}/todo/${pk}/reopen/`, {})),

  // ---------------- 355 会议室预订 ----------------
  // {items[{id,name,capacity,location,facilities,active,owner,favorite}], count, favorite_count}
  rooms: (params) => unwrap(request.get(`${D}/meeting/room/list/`, { params })),
  // {room, date, occupied[{id,start_at,end_at,title}], occupied_count}
  roomAvailability: (pk, date) =>
    unwrap(request.get(`${D}/meeting/room/${pk}/availability/`, { params: { date } })),
  // 入参 room_id / start_at / end_at / title；冲突时 400 + message（直接 toast）
  bookRoom: (data) => unwrap(request.post(`${D}/meeting/book/`, data)),
  // {items[obj_dict + room/start_at/end_at], count}
  myBookings: (params) => unwrap(request.get(`${D}/meeting/my-bookings/`, { params })),

  // ---------------- 357 常用会议室收藏 ----------------
  roomFavorites: () => unwrap(request.get(`${D}/meeting/room/favorites/`)),
  addRoomFavorite: (room_id) => unwrap(request.post(`${D}/meeting/room/favorites/`, { room_id })),
  // 后端 DELETE 从请求体取 room_id（devtools._payload 对非 GET 只读 body）
  removeRoomFavorite: (room_id) =>
    unwrap(request.delete(`${D}/meeting/room/favorites/`, { data: { room_id } })),

  // ---------------- 358 日程周视图 ----------------
  // 后端 agenda_week 读 date 参数（取该日所在周），这里同时带上 start 兼容
  agendaWeek: (start) =>
    unwrap(request.get(`${D}/calendar/agenda/week/`, { params: { date: start, start } })),
  // 入参 start_at / end_at（或 duration_minutes）/ resource / exclude
  // → {conflicts, conflict_count, resource_conflicts, has_conflict}
  conflictCheck: (data) => unwrap(request.post(`${D}/calendar/conflict-check/`, data)),
  createEvent: (data) => unwrap(request.post(`${D}/calendar/event/create/`, data)),

  // ---------------- 359 日程导出 .ics ----------------
  // 附件流：带 JWT 取 Blob 后 saveBlob；失败可回落到 exportIcsUrl + window.open
  exportIcs: (start, end) =>
    request.get(`${D}/calendar/export/ics/`, {
      params: { start, end },
      responseType: 'blob',
    }),
  exportIcsUrl: (start, end) =>
    apiUrl(
      `${D}/calendar/export/ics/?start=${encodeURIComponent(start || '')}&end=${encodeURIComponent(end || '')}`
    ),

  // ---------------- 360 今日聚焦 ----------------
  // {date, agenda[], agenda_count, todos[], todo_count, overdue_count, approvals:{count, items}}
  focusToday: () => unwrap(request.get(`${D}/focus/today/`)),

  // ---------------- 361 审批中心 ----------------
  approvalPending: () => unwrap(request.get(`${D}/approval/my-pending/`)),
  approvalSubmitted: (params) => unwrap(request.get(`${D}/approval/my-submitted/`, { params })),
  approvalEvents: (pk) => unwrap(request.get(`${D}/approval/${pk}/events/`)),
  // 通过：note 可选
  approvalApprove: (pk, note) => unwrap(request.post(`${D}/approval/${pk}/approve/`, { note: note || '' })),
  // 驳回：reason 必填
  approvalReject: (pk, reason) => unwrap(request.post(`${D}/approval/${pk}/reject/`, { reason })),
  // 催办：note 可选
  approvalUrge: (pk, note) =>
    unwrap(request.post(`${D}/approval/${pk}/urge/`, { note: note || '请尽快处理' })),
  // ---------------- 362 审批超时扫描 ----------------
  // → {hours, scanned, overdue, notified, skipped, items}
  approvalOverdueCheck: (hours = 24) =>
    unwrap(request.post(`${D}/approval/overdue-check/`, {}, { params: { hours } })),

  // ---------------- 363 时段内空闲车辆 ----------------
  // {start, end, items[空闲], count, busy[], busy_count, total}
  vehicleAvailable: (start, end) =>
    unwrap(request.get(`${D}/vehicle/available/`, { params: { start, end } })),
}

export default officex
