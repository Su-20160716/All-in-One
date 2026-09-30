import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  // 代码分享页（免登录，独立布局，不套 AppShell）
  // 路径与后端 share_create 返回的 url 保持一致：/share/code/<token>/
  {
    path: '/share/code/:token',
    name: 'code-share',
    component: () => import('../views/code/SharedCode.vue'),
    meta: { public: true, title: '共享代码' },
  },
  {
    path: '/share/board/:token',
    name: 'board-share',
    component: () => import('../views/projects/SharedBoard.vue'),
    meta: { public: true, title: '只读看板' },
  },
  {
    path: '/',
    component: () => import('../AppShell.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '工作台' } },
      { path: 'search', name: 'search', component: () => import('../views/Search.vue'), meta: { title: '全文搜索' } },
      { path: 'ai', name: 'ai', component: () => import('../views/AiAssistant.vue'), meta: { title: 'AI 助手' } },
      { path: 'files', name: 'files', component: () => import('../views/files/Files.vue'), meta: { title: '文件管理' } },
      { path: 'files/trash', name: 'trash', component: () => import('../views/files/Trash.vue'), meta: { title: '回收站' } },
      { path: 'files/shares', name: 'shares', component: () => import('../views/files/Shares.vue'), meta: { title: '共享链接' } },
      { path: 'files/analysis', name: 'file-analysis', component: () => import('../views/files/Analysis.vue'), meta: { title: '存储分析' } },
      { path: 'notes', name: 'notes', component: () => import('../views/notes/Notes.vue'), meta: { title: '笔记知识库' } },
      { path: 'projects', name: 'projects', component: () => import('../views/projects/Projects.vue'), meta: { title: '项目看板' } },
      { path: 'projects/my-tasks', name: 'my-tasks', component: () => import('../views/projects/MyTasks.vue'), meta: { title: '我的任务' } },
      { path: 'projects/:id/board', name: 'board', component: () => import('../views/projects/Board.vue'), meta: { title: '看板' } },
      { path: 'im', name: 'im', component: () => import('../views/im/Chat.vue'), meta: { title: '站内消息' } },
      { path: 'tools', name: 'tools', component: () => import('../views/tools/Tools.vue'), meta: { title: '小工具' } },
      { path: 'toolbox/devtools', name: 'toolbox-devtools', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'devtools' }, meta: { title: '开发工具箱' } },
      { path: 'toolbox/minitools', name: 'toolbox-minitools', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'minitools' }, meta: { title: '迷你工具箱' } },
      { path: 'toolbox/dataintel', name: 'toolbox-dataintel', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'dataintel' }, meta: { title: '数据智能中心' } },
      { path: 'toolbox/office', name: 'toolbox-office', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'officesuite' }, meta: { title: '办公套件' } },
      { path: 'office/helpdesk', name: 'office-helpdesk', component: () => import('../views/office/Helpdesk.vue'), meta: { title: '工单台' } },
      { path: 'office/duty', name: 'office-duty', component: () => import('../views/office/DutyWeek.vue'), meta: { title: '值班排班' } },
      { path: 'learning', name: 'learning-home', component: () => import('../views/learning/LearningHome.vue'), meta: { title: '学习中心' } },
      { path: 'learning/programming', name: 'learning-programming', component: () => import('../views/learning/programming/Programming.vue'), meta: { title: '编程语言广场' } },
      { path: 'learning/drill', name: 'learning-drill', component: () => import('../views/learning/programming/CodeDrill.vue'), meta: { title: '编程刷题训练' } },
      { path: 'learning/school', name: 'learning-school', component: () => import('../views/learning/school/SchoolSubjects.vue'), meta: { title: '学科知识中心' } },
      { path: 'learning/chinese', name: 'learning-chinese', component: () => import('../views/learning/school/ChineseGarden.vue'), meta: { title: '语文园地' } },
      { path: 'learning/english', name: 'learning-english', component: () => import('../views/learning/school/EnglishCorner.vue'), meta: { title: '英语角' } },
      { path: 'learning/questions', name: 'learning-questions', component: () => import('../views/learning/school/QuestionBank.vue'), meta: { title: '题库与组卷' } },
      { path: 'learning/tools', name: 'learning-tools', component: () => import('../views/learning/LearnTools.vue'), meta: { title: '学习工具箱' } },
      { path: 'learning/study', name: 'learning-study', component: () => import('../views/learning/StudyCenter.vue'), meta: { title: '我的学习' } },
      // ── 代码工坊（v6）────────────────────────────────────────────
      { path: 'code', name: 'code-forge', component: () => import('../views/code/CodeForge.vue'), meta: { title: '代码工坊' } },
      { path: 'code/learn', name: 'code-learn', component: () => import('../views/code/LearnCenter.vue'), meta: { title: '代码学习中心' } },
      { path: 'announcements', name: 'announcements', component: () => import('../views/Announcements.vue'), meta: { title: '系统公告' } },
      { path: 'admin/stats', name: 'admin-stats', component: () => import('../views/admin/AdminStats.vue'), meta: { title: '统计面板' } },
      { path: 'admin/users', name: 'admin-users', component: () => import('../views/admin/AdminUsers.vue'), meta: { title: '用户管理' } },
      { path: 'admin/roles', name: 'admin-roles', component: () => import('../views/admin/AdminRoles.vue'), meta: { title: '角色权限' } },
      { path: 'admin/org', name: 'admin-org', component: () => import('../views/admin/AdminOrg.vue'), meta: { title: '组织架构' } },
      { path: 'admin/logs', name: 'admin-logs', component: () => import('../views/admin/AdminLogs.vue'), meta: { title: '操作日志' } },
      { path: 'admin/announcements', name: 'admin-announcements', component: () => import('../views/admin/AdminAnnouncements.vue'), meta: { title: '公告管理' } },
      { path: 'admin/settings', name: 'admin-settings', component: () => import('../views/admin/AdminSettings.vue'), meta: { title: '站点设置' } },
      { path: 'profile', name: 'profile', component: () => import('../views/Profile.vue'), meta: { title: '个人设置' } },
    ],
  },
  // F617 个人公开主页（本次唯一获准的共享文件改动：仅追加这一条路由）
  { path: '/u/:username', name: 'public-profile', component: () => import('../views/Profile.vue'), meta: { public: true, title: '个人主页' } },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const user = useUserStore()
  if (!to.meta.public && !user.loggedIn) {
    return { name: 'login' }
  }
  if (to.name === 'login' && user.loggedIn) {
    return { path: '/dashboard' }
  }
  document.title = to.meta.title ? `${to.meta.title} · 全能协作平台` : '全能协作平台'
  return true
})

export default router
