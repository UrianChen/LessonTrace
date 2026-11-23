<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, dateTime, session, type Report } from '../api'

const reports = ref<Report[]>([])
const loading = ref(true)
const error = ref('')
const isCenter = session.user?.role === 'center'

onMounted(async () => {
  try { reports.value = await api<Report[]>('GET', '/reports') } catch (e: any) { error.value = e.message } finally { loading.value = false }
})
</script>

<template>
  <div class="page">
    <div class="page-head"><h1>{{ isCenter ? 'Submitted Reports' : 'My Reports' }}</h1></div>
    <p v-if="error" class="notice bad">{{ error }}</p>
    <p v-if="loading" class="muted">Loading…</p>
    <div v-else-if="!reports.length" class="card empty">
      {{ isCenter ? 'No reports have been submitted' : 'No reports yet' }}
    </div>
    <div v-else class="card">
      <table class="data">
        <thead><tr><th>Lesson</th><th>Date taught</th><th v-if="isCenter">Teacher</th><th>Version</th><th>Generated</th><th>Submitted</th><th /></tr></thead>
        <tbody>
          <tr v-for="r in reports" :key="r.id">
            <td><b style="font-weight: 600">{{ r.title }}</b></td>
            <td>{{ r.taught_on }}</td>
            <td v-if="isCenter">{{ r.teacher }}</td>
            <td>v{{ r.version }}</td>
            <td class="small">{{ dateTime(r.created_at) }}</td>
            <td class="small"><span v-if="r.submitted_at" class="chip ok">{{ dateTime(r.submitted_at) }}</span><span v-else class="chip">Not submitted</span></td>
            <td class="actions"><router-link class="btn small" :to="`/reports/${r.id}`">Open</router-link></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
