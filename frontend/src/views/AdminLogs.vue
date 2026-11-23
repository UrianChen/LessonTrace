<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, dateTime, type User } from '../api'

interface Log { id: number; user_id: number | null; user: string | null; action: string; target_type: string | null; target_id: string | null; ip: string | null; at: string }

const ACTION: Record<string, string> = {
  login: 'Sign in', login_failed: 'Failed sign-in', create_lesson: 'Create lesson', view_lesson: 'View lesson', delete_lesson: 'Delete lesson',
  retry_lesson: 'Retry processing', reanalyze_lesson: 'Re-analyze', generate_report: 'Generate report', view_report: 'View report',
  download_report: 'Download report', submit_report: 'Submit report', create_user: 'Add account', enable_user: 'Enable account', disable_user: 'Disable account',
}
const TARGET: Record<string, string> = { lesson: 'Lesson', report: 'Report', user: 'Account' }
const SIZE = 50

const users = ref<User[]>([])
const logs = ref<Log[]>([])
const total = ref(0)
const error = ref('')
const filter = reactive({ user_id: '', since: '', until: '', page: 1 })
const pages = computed(() => Math.max(1, Math.ceil(total.value / SIZE)))

async function load() {
  const q = new URLSearchParams({ page: String(filter.page), size: String(SIZE) })
  if (filter.user_id) q.set('user_id', filter.user_id)
  if (filter.since) q.set('since', new Date(filter.since).toISOString())
  if (filter.until) q.set('until', new Date(filter.until).toISOString())
  try {
    const r = await api<{ total: number; items: Log[] }>('GET', `/audit-logs?${q}`)
    logs.value = r.items
    total.value = r.total
    error.value = ''
  } catch (e: any) { error.value = e.message }
}
function search() { filter.page = 1; load() }
function go(d: number) { filter.page += d; load() }
onMounted(async () => {
  users.value = await api<User[]>('GET', '/users').catch(() => [])
  load()
})
</script>

<template>
  <div class="page">
    <div class="page-head"><h1>Access Log</h1></div>
    <form class="card row wrap" style="margin-bottom: 14px; align-items: end; padding: 14px 16px; gap: 12px" @submit.prevent="search">
      <label class="field" style="width: 180px"><span>User</span>
        <select v-model="filter.user_id"><option value="">All</option><option v-for="u in users" :key="u.id" :value="String(u.id)">{{ u.name }} ({{ u.username }})</option></select>
      </label>
      <label class="field" style="width: 210px"><span>From</span><input v-model="filter.since" type="datetime-local" /></label>
      <label class="field" style="width: 210px"><span>To</span><input v-model="filter.until" type="datetime-local" /></label>
      <button class="btn primary">Filter</button>
    </form>
    <p v-if="error" class="notice bad">{{ error }}</p>
    <div class="card">
      <table class="data">
        <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>IP address</th></tr></thead>
        <tbody>
          <tr v-for="l in logs" :key="l.id">
            <td class="small mono">{{ dateTime(l.at) }}</td>
            <td>{{ l.user ?? '—' }}</td>
            <td><span class="chip" :class="{ bad: l.action === 'login_failed' }">{{ ACTION[l.action] ?? l.action }}</span></td>
            <td class="small">{{ TARGET[l.target_type ?? ''] ?? l.target_type ?? '' }} {{ l.target_id }}</td>
            <td class="small mono">{{ l.ip ?? '—' }}</td>
          </tr>
          <tr v-if="!logs.length"><td colspan="5" class="muted">No entries</td></tr>
        </tbody>
      </table>
    </div>
    <div class="row" style="margin-top: 12px">
      <span class="small muted">{{ total }} entries · page {{ filter.page }} of {{ pages }}</span><span class="spacer" />
      <button class="btn small" :disabled="filter.page <= 1" @click="go(-1)">Previous</button>
      <button class="btn small" :disabled="filter.page >= pages" @click="go(1)">Next</button>
    </div>
  </div>
</template>
