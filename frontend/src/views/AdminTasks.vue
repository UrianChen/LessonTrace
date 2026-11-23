<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, dateTime, STATUS_LABEL } from '../api'

interface Task { id: number; teacher: string; status: string; error: { stage: string; reason: string } | null; created_at: string }
const tasks = ref<Task[]>([])
const error = ref('')

async function load() {
  try { tasks.value = await api<Task[]>('GET', '/lessons') } catch (e: any) { error.value = e.message }
}
async function retry(t: Task) {
  try { await api('POST', `/lessons/${t.id}/retry`); await load() } catch (e: any) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head"><h1>Tasks</h1><span class="spacer" /><button class="btn" @click="load">Refresh</button></div>
    <p v-if="error" class="notice bad">{{ error }}</p>
    <div class="card">
      <table class="data">
        <thead><tr><th>ID</th><th>Teacher</th><th>Created</th><th>Status</th><th>Failure</th><th /></tr></thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td class="mono">{{ t.id }}</td><td>{{ t.teacher }}</td><td class="small">{{ dateTime(t.created_at) }}</td>
            <td><span class="chip" :class="{ bad: t.status === 'failed', ok: t.status === 'confirmed', info: t.status === 'ready' }">{{ STATUS_LABEL[t.status] ?? t.status }}</span></td>
            <td class="small">{{ t.error ? `${STATUS_LABEL[t.error.stage] ?? t.error.stage}: ${t.error.reason}` : '' }}</td>
            <td class="actions"><button v-if="t.status === 'failed'" class="btn small" @click="retry(t)">Retry</button></td>
          </tr>
          <tr v-if="!tasks.length"><td colspan="6" class="muted">No tasks</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
