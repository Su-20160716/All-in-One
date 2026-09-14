/**
 * 笔记实时协同（Yjs CRDT over 现有 WebSocket 通道）
 *
 * 与服务端的分工：
 *  - 服务端只做「增量中继 + 快照持久化」，不做 CRDT 合并
 *  - 合并全部在客户端由 Yjs 完成（update 可交换、幂等，因此快照 + 增量日志
 *    足以让任何新客户端还原出完整文档）
 *
 * 用法：
 *   const collab = new NoteCollab(noteId, { initialContent, onText, onPresence, onStatus })
 *   collab.connect()
 *   collab.applyLocalText(newValue)   // textarea 输入时调用
 *   collab.destroy()
 */
import * as Y from 'yjs'
import { createSocket } from './ws'

function u8ToB64(u8) {
  let s = ''
  for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i])
  return btoa(s)
}

function b64ToU8(b64) {
  const bin = atob(b64)
  const u8 = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return u8
}

const SNAPSHOT_INTERVAL = 20000 // 定期压缩快照，避免增量日志无限增长

export class NoteCollab {
  constructor(noteId, opts = {}) {
    this.noteId = noteId
    this.opts = opts
    this.doc = new Y.Doc()
    this.ytext = this.doc.getText('content')
    this.socket = null
    this.destroyed = false
    this.dirty = false
    this.seeded = false
    this.remoteLoaded = false
    this.snapshotTimer = null
    this.revision = 0
    this.participants = []
    this._suppress = false
  }

  connect() {
    this.socket = createSocket(`/ws/notes/${this.noteId}/`, {
      onOpen: () => this._emitStatus('connected'),
      onClose: () => {
        if (!this.destroyed) this._emitStatus('closed')
      },
      onMessage: (msg) => this._onMessage(msg),
    })

    // 本地修改 → 广播
    this.doc.on('update', (update, origin) => {
      if (origin === 'remote' || this._suppress) return
      this.dirty = true
      this._send({ type: 'yjs.update', update: u8ToB64(update) })
    })

    // 远端合并结果 → 回填编辑器
    this.ytext.observe(() => {
      if (!this.remoteLoaded) return
      this.opts.onText && this.opts.onText(this.ytext.toString())
    })

    this.snapshotTimer = setInterval(() => {
      if (this.dirty) this.compact()
    }, SNAPSHOT_INTERVAL)
    this._emitStatus('connecting')
  }

  _onMessage(msg) {
    switch (msg.type) {
      case 'collab.init': {
        const data = msg.data || {}
        this.revision = data.revision || 0
        this.participants = data.participants || []
        this._suppress = true
        try {
          if (data.snapshot) Y.applyUpdate(this.doc, b64ToU8(data.snapshot), 'remote')
          for (const upd of data.updates || []) {
            try { Y.applyUpdate(this.doc, b64ToU8(upd), 'remote') } catch (e) { /* 跳过坏包 */ }
          }
          // 服务端无任何状态 → 用本地内容作为初始种子
          if (!data.snapshot && !(data.updates || []).length && this.opts.initialContent) {
            this.ytext.insert(0, this.opts.initialContent)
            this.seeded = true
          }
        } finally {
          this._suppress = false
        }
        this.remoteLoaded = true
        this.opts.onText && this.opts.onText(this.ytext.toString())
        this.opts.onPresence && this.opts.onPresence(this.participants)
        this._emitStatus('ready')
        break
      }
      case 'yjs.update':
        try { Y.applyUpdate(this.doc, b64ToU8(msg.data.update), 'remote') } catch (e) { /* ignore */ }
        break
      case 'yjs.snapshot':
        try { Y.applyUpdate(this.doc, b64ToU8(msg.data.snapshot), 'remote') } catch (e) { /* ignore */ }
        this.revision = msg.data.revision || this.revision
        break
      case 'presence':
        this.opts.onEvent && this.opts.onEvent(
          `${msg.data.sender} ${msg.data.action === 'join' ? '加入' : '离开'}了协同编辑`
        )
        break
      case 'awareness':
        this.opts.onAwareness && this.opts.onAwareness(msg.data)
        break
      case 'collab.compact':
        this.compact()
        break
      default:
        break
    }
  }

  _send(payload) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
    }
  }

  /** 把编辑器的最新文本映射为 CRDT 操作（前后缀 diff，保留并发语义） */
  applyLocalText(newValue) {
    if (this.destroyed) return
    const oldValue = this.ytext.toString()
    if (newValue === oldValue) return

    let start = 0
    const minLen = Math.min(oldValue.length, newValue.length)
    while (start < minLen && oldValue[start] === newValue[start]) start++
    let endOld = oldValue.length
    let endNew = newValue.length
    while (endOld > start && endNew > start && oldValue[endOld - 1] === newValue[endNew - 1]) {
      endOld--
      endNew--
    }
    const inserted = newValue.slice(start, endNew)
    const removed = endOld - start

    this.doc.transact(() => {
      if (removed > 0) this.ytext.delete(start, removed)
      if (inserted) this.ytext.insert(start, inserted)
    })
  }

  /** 压缩为快照并回写正文（服务端据此更新全文索引与双链） */
  compact() {
    if (this.destroyed) return
    try {
      const snapshot = u8ToB64(Y.encodeStateAsUpdate(this.doc))
      this._send({ type: 'yjs.snapshot', snapshot, text: this.ytext.toString() })
      this.dirty = false
    } catch (e) { /* ignore */ }
  }

  /** 广播光标位置（在线协作感知） */
  sendCursor(position) {
    this._send({ type: 'awareness', state: { cursor: position } })
  }

  text() {
    return this.ytext.toString()
  }

  _emitStatus(status) {
    this.opts.onStatus && this.opts.onStatus(status)
  }

  destroy() {
    this.destroyed = true
    clearInterval(this.snapshotTimer)
    if (this.dirty) this.compact()
    try { this.socket && this.socket.close() } catch (e) { /* ignore */ }
    try { this.doc.destroy() } catch (e) { /* ignore */ }
  }
}
