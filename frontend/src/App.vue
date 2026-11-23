<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { session, setSession } from './api'

const router = useRouter()
const ROLE = { teacher: 'Teacher', center: 'Teaching Center', admin: 'Admin' }
const nav = computed(() => {
  switch (session.user?.role) {
    case 'teacher': return [['/lessons', 'My Lessons'], ['/reports', 'Reports']]
    case 'center': return [['/reports', 'Submitted Reports']]
    case 'admin': return [['/admin/users', 'Accounts'], ['/admin/logs', 'Access Log'], ['/admin/tasks', 'Tasks']]
    default: return []
  }
})
function logout() {
  setSession(null, null)
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <header v-if="session.user" class="top">
      <router-link to="/" class="brand"><span class="logo" aria-hidden="true" />LessonTrace</router-link>
      <nav aria-label="Main">
        <router-link v-for="[to, label] in nav" :key="to" :to="to">{{ label }}</router-link>
      </nav>
      <span class="spacer" />
      <span class="who"><b>{{ session.user.name }}</b><span class="muted">{{ ROLE[session.user.role] }}</span></span>
      <button class="btn small ghost" @click="logout">Sign out</button>
    </header>
    <main><router-view /></main>
  </div>
</template>

<style scoped>
.shell { height: 100%; display: flex; flex-direction: column; }
.top { display: flex; align-items: center; gap: 24px; height: 52px; padding: 0 24px; background: var(--surface); border-bottom: 1px solid var(--line); flex: none; }
.brand { display: flex; align-items: center; gap: 9px; font-weight: 700; font-size: 15px; letter-spacing: -.01em; color: var(--ink); text-decoration: none; }
.logo { width: 18px; height: 18px; border-radius: 5px; background: var(--accent); position: relative; }
.logo::after { content: ""; position: absolute; left: 7px; top: 5px; border: 4px solid transparent; border-left: 6px solid #fff; border-right: 0; }
nav { display: flex; gap: 2px; align-self: stretch; }
nav a { display: flex; align-items: center; padding: 0 12px; white-space: nowrap; color: var(--ink-2); font-weight: 500; text-decoration: none; border-bottom: 2px solid transparent; margin-bottom: -1px; }
nav a:hover { color: var(--ink); }
nav a.router-link-active { color: var(--accent); border-bottom-color: var(--accent); }
.who { display: flex; gap: 8px; align-items: baseline; font-size: 13px; }
.who b { font-weight: 600; }
main { flex: 1; min-height: 0; overflow: auto; }
@media (max-width: 640px) { .top { gap: 10px; padding: 0 12px; } .who { display: none; } nav a { padding: 0 8px; } }
</style>
