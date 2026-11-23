<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, session, type User } from '../api'

const users = ref<User[]>([])
const error = ref('')
const ROLE = { teacher: 'Teacher', center: 'Teaching Center', admin: 'Admin' }
const form = reactive({ open: false, username: '', password: '', name: '', role: 'teacher', dept: '', busy: false, error: '' })

async function load() {
  try { users.value = await api<User[]>('GET', '/users') } catch (e: any) { error.value = e.message }
}
onMounted(load)

async function add() {
  form.busy = true
  form.error = ''
  try {
    await api('POST', '/users', { username: form.username, password: form.password, name: form.name, role: form.role, dept: form.dept })
    Object.assign(form, { open: false, username: '', password: '', name: '', dept: '' })
    await load()
  } catch (e: any) { form.error = e.message } finally { form.busy = false }
}
async function toggle(u: User) {
  if (u.active && !confirm(`Disable ${u.name}? They will be signed out and unable to sign in.`)) return
  try { await api('PATCH', `/users/${u.id}`, { active: !u.active }); await load() } catch (e: any) { error.value = e.message }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>Accounts</h1><span class="spacer" />
      <button class="btn primary" @click="form.open = true">Add account</button>
    </div>
    <p v-if="error" class="notice bad" style="margin-bottom: 12px">{{ error }}</p>
    <div class="card">
      <table class="data">
        <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Department</th><th>Status</th><th /></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td class="mono">{{ u.username }}</td><td>{{ u.name }}</td><td>{{ ROLE[u.role] }}</td><td>{{ u.dept || '—' }}</td>
            <td><span class="chip" :class="u.active ? 'ok' : 'bad'">{{ u.active ? 'Active' : 'Disabled' }}</span></td>
            <td class="actions"><button v-if="u.id !== session.user?.id" class="btn small" :class="{ danger: u.active }" @click="toggle(u)">{{ u.active ? 'Disable' : 'Enable' }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="form.open" class="modal-back" @click.self="form.open = false">
      <form class="card modal" @submit.prevent="add">
        <h2>Add account</h2>
        <label class="field"><span>Username</span><input v-model="form.username" type="text" required minlength="3" pattern="[A-Za-z0-9_.\-]+" autocomplete="off" /></label>
        <label class="field"><span>Initial password <em style="font-style: normal; font-weight: 400; color: var(--ink-3)">at least 8 characters</em></span><input v-model="form.password" type="password" required minlength="8" autocomplete="new-password" /></label>
        <label class="field"><span>Name</span><input v-model="form.name" type="text" required /></label>
        <label class="field"><span>Role</span>
          <select v-model="form.role"><option value="teacher">Teacher</option><option value="center">Teaching Center</option><option value="admin">Admin</option></select>
        </label>
        <label class="field"><span>Department <em style="font-style: normal; font-weight: 400; color: var(--ink-3)">optional</em></span><input v-model="form.dept" type="text" /></label>
        <p v-if="form.error" class="notice bad">{{ form.error }}</p>
        <div class="modal-foot"><button type="button" class="btn" @click="form.open = false">Cancel</button><button class="btn primary" :disabled="form.busy">Add</button></div>
      </form>
    </div>
  </div>
</template>
