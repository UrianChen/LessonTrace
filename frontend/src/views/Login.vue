<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setSession, type User } from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const r = await api<{ token: string; user: User }>('POST', '/auth/login', { username: username.value, password: password.value })
    setSession(r.token, r.user)
    router.push('/')
  } catch (e: any) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <header class="hero">
      <div class="brand"><span class="logo" aria-hidden="true" />LessonTrace</div>
      <h1>Look back at your lesson, with every observation linked to the recording</h1>
      <p class="tag">Evidence you can replay · No scores · You decide what stays</p>
    </header>
    <form class="card box" @submit.prevent="submit">
      <h2>Sign in</h2>
      <label class="field"><span>Username</span><input v-model="username" type="text" autocomplete="username" required autofocus /></label>
      <label class="field"><span>Password</span><input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="error" class="notice bad" role="alert">{{ error }}</p>
      <button class="btn primary block" :disabled="busy">{{ busy ? 'Signing in…' : 'Sign in' }}</button>
    </form>
  </div>
</template>

<style scoped>
.wrap { min-height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 36px; padding: 48px 20px 72px; }
.hero { text-align: center; max-width: 640px; }
.brand { display: inline-flex; align-items: center; gap: 12px; font-weight: 700; font-size: 26px; letter-spacing: -.01em; margin-bottom: 20px; }
.logo { width: 34px; height: 34px; border-radius: 9px; background: var(--accent); position: relative; }
.logo::after { content: ""; position: absolute; left: 13px; top: 9px; border: 8px solid transparent; border-left: 12px solid #fff; border-right: 0; }
.hero h1 { font-size: 24px; font-weight: 600; line-height: 1.35; margin-bottom: 10px; }
.tag { color: var(--ink-3); font-size: 14px; }
.box { width: min(380px, 100%); padding: 28px; display: grid; gap: 16px; }
.box h2 { font-size: 18px; }
@media (max-width: 640px) { .wrap { gap: 24px; padding: 32px 16px; } .brand { font-size: 22px; } .hero h1 { font-size: 19px; } }
</style>
