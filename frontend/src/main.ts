import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import 'video.js/dist/video-js.css'
import './style.css'
import App from './App.vue'
import { session, type Role } from './api'

const home: Record<Role, string> = { teacher: '/lessons', center: '/reports', admin: '/admin/users' }

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: () => (session.user ? home[session.user.role] : '/login') },
    { path: '/login', component: () => import('./views/Login.vue'), meta: { public: true } },
    { path: '/lessons', component: () => import('./views/Lessons.vue'), meta: { roles: ['teacher'] } },
    { path: '/lessons/:id/review', component: () => import('./views/Review.vue'), meta: { roles: ['teacher'], wide: true } },
    { path: '/reports', component: () => import('./views/Reports.vue'), meta: { roles: ['teacher', 'center'] } },
    { path: '/reports/:id', component: () => import('./views/ReportView.vue'), meta: { roles: ['teacher', 'center'] } },
    { path: '/admin/users', component: () => import('./views/AdminUsers.vue'), meta: { roles: ['admin'] } },
    { path: '/admin/logs', component: () => import('./views/AdminLogs.vue'), meta: { roles: ['admin'] } },
    { path: '/admin/tasks', component: () => import('./views/AdminTasks.vue'), meta: { roles: ['admin'] } },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

// 这里只管把人带到该去的页面；真正的权限校验在服务端每个接口上
router.beforeEach(to => {
  const user = session.user
  if (to.meta.public) return user && to.path === '/login' ? home[user.role] : true
  if (!user) return '/login'
  const roles = to.meta.roles as Role[] | undefined
  if (roles && !roles.includes(user.role)) return home[user.role]
  return true
})

createApp(App).use(router).mount('#app')
