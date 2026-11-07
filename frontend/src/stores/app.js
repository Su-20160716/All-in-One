import { defineStore } from 'pinia'
import { coreApi } from '../api'
import { connectWs } from '../utils/ws'

let toastTimer = null
let notifTimer = null
let notificationsInflight = null
let unreadInflight = null

export const useAppStore = defineStore('app', {
  state: () => ({
    notifications: [],
    unreadCount: 0,
    wsConnected: false,
    wsOpenedOnce: false,
    toast: { show: false, text: '', type: 'info' },
    chatListeners: [],
    fileListeners: [],
    boardListeners: [],
  }),
  actions: {
    toastMsg(text, type = 'info') {
      this.toast = { show: true, text, type }
      // 新提示要完整展示 2.6s：清掉上一条的定时器，否则会被提前关闭
      if (toastTimer) clearTimeout(toastTimer)
      toastTimer = setTimeout(() => {
        this.toast.show = false
        toastTimer = null
      }, 2600)
    },
    onChat(cb) {
      this.chatListeners.push(cb)
      return () => {
        this.chatListeners = this.chatListeners.filter((f) => f !== cb)
      }
    },
    // S2-B1：文件/看板实时事件订阅（页面 onMounted 订阅、onUnmounted 退订）
    onFileEvent(cb) {
      this.fileListeners.push(cb)
      return () => {
        this.fileListeners = this.fileListeners.filter((f) => f !== cb)
      }
    },
    onBoardEvent(cb) {
      this.boardListeners.push(cb)
      return () => {
        this.boardListeners = this.boardListeners.filter((f) => f !== cb)
      }
    },
    async fetchNotifications() {
      if (notificationsInflight) return notificationsInflight
      notificationsInflight = coreApi.notifications({ page_size: 20 })
        .then((r) => { this.notifications = r.list || [] })
        .catch(() => {})
        .finally(() => { notificationsInflight = null })
      return notificationsInflight
    },
    async fetchUnread() {
      if (unreadInflight) return unreadInflight
      unreadInflight = coreApi.unreadCount()
        .then((r) => { this.unreadCount = r.count })
        .catch(() => {})
        .finally(() => { unreadInflight = null })
      return unreadInflight
    },
    // #197 通知刷新合并：WS 突发多条通知 / 页面首屏同时拉取时只发一轮请求
    refreshNotificationsSoon(delay = 200) {
      clearTimeout(notifTimer)
      notifTimer = setTimeout(() => {
        notifTimer = null
        this.fetchUnread()
        this.fetchNotifications()
      }, delay)
    },
    async markAllRead() {
      try {
        await coreApi.markRead([])
        this.notifications.forEach((n) => (n.is_read = true))
        this.unreadCount = 0
      } catch (e) { /* ignore */ }
    },
    async markOneRead(n) {
      try {
        await coreApi.markRead([n.id])
        n.is_read = true
        this.unreadCount = Math.max(0, this.unreadCount - 1)
      } catch (e) { /* ignore */ }
    },
    initWs() {
      if (this.wsConnected) return
      connectWs({
        onOpen: () => {
          const reconnected = this.wsOpenedOnce
          this.wsConnected = true
          this.wsOpenedOnce = true
          // 断线期间的消息/未读不会补发，重连后主动增量同步
          if (reconnected) {
            this.refreshNotificationsSoon(0)
            this.chatListeners.forEach((cb) => cb('ws.reconnected', {}))
          }
        },
        onClose: () => (this.wsConnected = false),
        onMessage: (msg) => {
          if (msg.type === 'notification') {
            // 合并刷新：短时间多条通知只触发一轮 HTTP
            this.refreshNotificationsSoon()
            this.toastMsg(msg.data?.title || '新通知', 'info')
          } else if ([
            'chat.message', 'message.recalled', 'message.pinned', 'message.edited',
            'message.deleted', 'session.updated', 'session.typing', 'group.system', 'chat.typing',
          ].includes(msg.type)) {
            this.chatListeners.forEach((cb) => cb(msg.type, msg.data))
          } else if (msg.type === 'file.event') {
            // S2-B1：文件变动（上传/删除/更新）——页面级订阅者自行决定是否刷新
            this.fileListeners.forEach((cb) => cb(msg.type, msg.data))
          } else if (msg.type === 'board.event') {
            // S2-B1：看板/卡片变动
            this.boardListeners.forEach((cb) => cb(msg.type, msg.data))
          }
        },
      })
    },
  },
})
