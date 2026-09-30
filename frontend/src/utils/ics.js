/**
 * 纯前端生成 iCalendar (.ics) 文件（#89）
 *
 * 用法：
 *   import { downloadIcs } from '../utils/ics'
 *   downloadIcs([{ title: '周会', start: '2026-09-25T10:00:00', end: '2026-09-25T11:00:00', location: '301', description: '...' }])
 */

function pad(n) { return String(n).padStart(2, '0') }

function toIcsDate(d) {
  const dt = new Date(d)
  return `${dt.getUTCFullYear()}${pad(dt.getUTCMonth() + 1)}${pad(dt.getUTCDate())}`
    + `T${pad(dt.getUTCHours())}${pad(dt.getUTCMinutes())}${pad(dt.getUTCSeconds())}Z`
}

function escapeText(s) {
  return String(s || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n')
}

export function eventsToIcs(events, calName = '我的日历') {
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//AllInOne//OfficeSuite//CN',
    'CALSCALE:GREGORIAN',
    `X-WR-CALNAME:${escapeText(calName)}`,
  ]
  events.forEach((e, i) => {
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:${Date.now()}-${i}@allinone`)
    lines.push(`SUMMARY:${escapeText(e.title)}`)
    if (e.start) lines.push(`DTSTART:${toIcsDate(e.start)}`)
    if (e.end) lines.push(`DTEND:${toIcsDate(e.end)}`)
    if (e.location) lines.push(`LOCATION:${escapeText(e.location)}`)
    if (e.description) lines.push(`DESCRIPTION:${escapeText(e.description)}`)
    lines.push('END:VEVENT')
  })
  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

export function downloadIcs(events, filename = 'calendar.ics') {
  const ics = eventsToIcs(events)
  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.ics') ? filename : `${filename}.ics`
  a.click()
  URL.revokeObjectURL(url)
}
