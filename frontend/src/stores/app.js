import { defineStore } from 'pinia'
import { coreApi } from '../api'
import { connectWs } from '../utils/ws'

export const useAppStore = defineStore('app', {
  state: () => ({
    notifications: [],
    unreadCount: 0,
    wsConnected: false,
    toast: { show: false, text: '', type: 'info' },
    chatListeners: [],
    fileListeners: [],
    boardListeners: [],
  }),
  actions: {
    toastMsg(text, type = 'info') {
      this.toast = { show: true, text, type }
      setTimeout(() => (this.toast.show = false), 2600)
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
      try {
        const r = await coreApi.notifications({ page_size: 20 })
        this.notifications = r.list || []
      } catch (e) { /* ignore */ }
    },
    async fetchUnread() {
      try {
        const r = await coreApi.unreadCount()
        this.unreadCount = r.count
      } catch (e) { /* ignore */ }
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
        onOpen: () => (this.wsConnected = true),
        onClose: () => (this.wsConnected = false),
        onMessage: (msg) => {
          if (msg.type === 'notification') {
            this.fetchUnread()
            this.fetchNotifications()
            this.toastMsg(msg.data?.title || '新通知', 'info')
          } else if (['chat.message', 'message.recalled', 'session.updated', 'group.system', 'chat.typing'].includes(msg.type)) {
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
