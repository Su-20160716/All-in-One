import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'
import { t } from '../i18n'

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
  // F3：文件共享落地页（免登录，独立布局）。与 /share/code|board 子路径
  // 并存不冲突（router 静态段优先）；API 走 /api/share/<token>/。
  {
    path: '/share/:token',
    name: 'file-share',
    component: () => import('../views/files/SharedFile.vue'),
    meta: { public: true, title: '共享文件' },
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
      // ── 业务中心（1 个目录页 + 全部模块工作台，模块由后端目录动态注册）──
      { path: 'biz', name: 'biz-hub', component: () => import('../views/biz/BizHub.vue'), meta: { title: '业务中心' } },
      {
        path: 'biz/:slug',
        name: 'biz-workspace',
        component: () => import('../views/biz/BizWorkspace.vue'),
        props: (route) => ({ module: route.params.slug }),
        meta: { title: '业务模块' },
      },
      // ── 平台能力域（后端 12 个新应用的已交付工作台）──
      { path: 'platform/workflow', name: 'platform-workflow', component: () => import('../views/workflow/WorkflowConsole.vue'), meta: { title: '流程引擎' } },
      { path: 'platform/forms', name: 'platform-forms', component: () => import('../views/formstudio/FormStudio.vue'), meta: { title: '表单设计器' } },
      { path: 'platform/reporting', name: 'platform-reporting', component: () => import('../views/reporting/ReportingWorkbench.vue'), meta: { title: '报表与仪表盘' } },
      { path: 'platform/rules', name: 'platform-rules', component: () => import('../views/rules/RuleStudio.vue'), meta: { title: '规则引擎' } },
      { path: 'platform/contracts', name: 'platform-contracts', component: () => import('../views/contracts/ContractCenter.vue'), meta: { title: '合同中心' } },
      { path: 'platform/pipeline', name: 'platform-pipeline', component: () => import('../views/pipeline/PipelineStudio.vue'), meta: { title: '数据管道' } },
      { path: 'platform/billing', name: 'platform-billing', component: () => import('../views/billing/BillingCenter.vue'), meta: { title: '订阅计费' } },
      { path: 'platform/marketplace', name: 'platform-marketplace', component: () => import('../views/marketplace/Marketplace.vue'), meta: { title: '应用市场' } },
      { path: 'im', name: 'im', component: () => import('../views/im/Chat.vue'), meta: { title: '站内消息' } },
      { path: 'tools', name: 'tools', component: () => import('../views/tools/Tools.vue'), meta: { title: '小工具' } },
      { path: 'toolbox/devtools', name: 'toolbox-devtools', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'devtools' }, meta: { title: '开发工具箱' } },
      { path: 'toolbox/minitools', name: 'toolbox-minitools', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'minitools' }, meta: { title: '迷你工具箱' } },
      { path: 'toolbox/dataintel', name: 'toolbox-dataintel', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'dataintel' }, meta: { title: '数据智能中心' } },
      { path: 'toolbox/office', name: 'toolbox-office', component: () => import('../views/toolbox/DomainExplorer.vue'), props: { domain: 'officesuite' }, meta: { title: '办公套件' } },
      { path: 'office/helpdesk', name: 'office-helpdesk', component: () => import('../views/office/Helpdesk.vue'), meta: { title: '工单台' } },
      { path: 'office/duty', name: 'office-duty', component: () => import('../views/office/DutyWeek.vue'), meta: { title: '值班排班' } },
      { path: 'office/todo', name: 'office-todo', component: () => import('../views/office/TodoQuadrant.vue'), meta: { title: '待办四象限' } },
      { path: 'office/meeting', name: 'office-meeting', component: () => import('../views/office/Meeting.vue'), meta: { title: '会议室预订' } },
      { path: 'office/calendar', name: 'office-calendar', component: () => import('../views/office/CalendarWeek.vue'), meta: { title: '日程周视图' } },
      { path: 'office/approvals', name: 'office-approvals', component: () => import('../views/office/Approvals.vue'), meta: { title: '审批中心' } },
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
      { path: 'admin/stats', name: 'admin-stats', component: () => import('../views/admin/AdminStats.vue'), meta: { title: '统计面板', requiresAdmin: true } },
      { path: 'admin/health', name: 'admin-health', component: () => import('../views/admin/AdminHealth.vue'), meta: { title: '系统健康', requiresAdmin: true } },
      { path: 'admin/users', name: 'admin-users', component: () => import('../views/admin/AdminUsers.vue'), meta: { title: '用户管理', requiresAdmin: true } },
      { path: 'admin/roles', name: 'admin-roles', component: () => import('../views/admin/AdminRoles.vue'), meta: { title: '角色权限', requiresAdmin: true } },
      { path: 'admin/org', name: 'admin-org', component: () => import('../views/admin/AdminOrg.vue'), meta: { title: '组织架构', requiresAdmin: true } },
      { path: 'admin/logs', name: 'admin-logs', component: () => import('../views/admin/AdminLogs.vue'), meta: { title: '操作日志', requiresAdmin: true } },
      { path: 'admin/announcements', name: 'admin-announcements', component: () => import('../views/admin/AdminAnnouncements.vue'), meta: { title: '公告管理', requiresAdmin: true } },
      { path: 'admin/settings', name: 'admin-settings', component: () => import('../views/admin/AdminSettings.vue'), meta: { title: '站点设置', requiresAdmin: true } },
      { path: 'profile', name: 'profile', component: () => import('../views/Profile.vue'), meta: { title: '个人设置' } },
      { path: 'developer', name: 'developer', component: () => import('../views/Developer.vue'), meta: { title: '开发者门户' } },
    ],
  },
  // F617 个人公开主页（本次唯一获准的共享文件改动：仅追加这一条路由）
  { path: '/u/:username', name: 'public-profile', component: () => import('../views/Profile.vue'), meta: { public: true, title: '个人主页' } },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFound.vue'), meta: { title: '页面不存在' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const user = useUserStore()
  if (!to.meta.public && !user.loggedIn) {
    return { name: 'login' }
  }
  // F9：管理路由双保险——进入前强制刷新权限，降权后不能靠 localStorage 快照蒙混
  if (to.meta.requiresAdmin) {
    await user.fetchPermissions()
    if (!user.isAdmin) {
      return { path: '/dashboard' }
    }
  }
  if (to.name === 'login' && user.loggedIn) {
    return { path: '/dashboard' }
  }
  // #201 标题走词典：meta.titleKey 优先，缺省时沿用中文 title 作为兜底
  const appName = t('app.name', '全能协作平台')
  const pageTitle = to.meta.titleKey ? t(to.meta.titleKey, to.meta.title) : to.meta.title
  document.title = pageTitle ? `${pageTitle} · ${appName}` : appName
  return true
})

export default router
