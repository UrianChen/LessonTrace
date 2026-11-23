<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, STATUS_LABEL, tc, uploadFile, type Lesson } from '../api'
import Icon from '../components/Icon.vue'

const lessons = ref<Lesson[]>([])
const loading = ref(true)
const error = ref('')
let timer: number | undefined

const STAGES = ['transcribing', 'segmenting', 'analyzing']
const STAGE_LABEL = ['Transcribe', 'Segment', 'Analyze']
const isProcessing = (l: Lesson) => STAGES.includes(l.status) || (l.status === 'uploaded' && l.started)

async function load() {
  try {
    lessons.value = await api<Lesson[]>('GET', '/lessons')
    error.value = ''
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  load()
  // 定时查询状态；没有课在处理时请求很轻
  timer = window.setInterval(() => { if (lessons.value.some(isProcessing)) load() }, 4000)
})
onBeforeUnmount(() => clearInterval(timer))

function stageState(l: Lesson, i: number): 'done' | 'active' | 'todo' {
  const cur = l.status === 'uploaded' ? -1 : STAGES.indexOf(l.status)
  return i < cur ? 'done' : i === cur ? 'active' : 'todo'
}

// ---- 上传 ----
const showUpload = ref(false)
const form = reactive({ title: '', taught_on: new Date().toISOString().slice(0, 10) })
const video = ref<File | null>(null)
const slides = ref<File | null>(null)
const up = reactive({ busy: false, step: '', ratio: 0, error: '' })
const MAX = 4 * 1024 ** 3
const tooBig = computed(() => !!video.value && video.value.size > MAX)

function pick(e: Event, target: 'video' | 'slides') {
  const f = (e.target as HTMLInputElement).files?.[0] ?? null
  if (target === 'video') video.value = f
  else slides.value = f
}

async function submitUpload() {
  if (!video.value || tooBig.value) return
  up.busy = true
  up.error = ''
  let lessonId: number | null = null
  try {
    const r = await api<{ lesson: Lesson; upload: { video_url: string; slides_url: string | null } }>('POST', '/lessons', {
      title: form.title, taught_on: form.taught_on, video_filename: video.value.name, video_size: video.value.size,
      slides_filename: slides.value?.name ?? null,
    })
    lessonId = r.lesson.id
    if (slides.value && r.upload.slides_url) {
      up.step = 'Uploading slides'
      await uploadFile(r.upload.slides_url, slides.value, x => (up.ratio = x))
    }
    up.step = 'Uploading recording'
    up.ratio = 0
    await uploadFile(r.upload.video_url, video.value, x => (up.ratio = x))
    up.step = 'Starting'
    await api('POST', `/lessons/${lessonId}/start`)
    showUpload.value = false
    form.title = ''
    video.value = slides.value = null
    await load()
  } catch (e: any) {
    up.error = e.message
    if (lessonId != null) await api('DELETE', `/lessons/${lessonId}`).catch(() => {})  // 没传完的不留空壳
  } finally {
    up.busy = false
    up.step = ''
  }
}

async function retry(l: Lesson) {
  try { await api('POST', `/lessons/${l.id}/retry`); await load() } catch (e: any) { error.value = e.message }
}
async function remove(l: Lesson) {
  if (!confirm(`Delete “${l.title}”? The recording, transcript, findings and reports will all be removed. This cannot be undone.`)) return
  try { await api('DELETE', `/lessons/${l.id}`); await load() } catch (e: any) { error.value = e.message }
}

const fileSize = (f: File | null) => (f ? (f.size >= 1024 ** 3 ? (f.size / 1024 ** 3).toFixed(2) + ' GB' : Math.max(1, Math.round(f.size / 1024 ** 2)) + ' MB') : '')
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>My Lessons</h1>
      <span class="spacer" />
      <button class="btn primary" @click="showUpload = true"><Icon name="upload" />Upload a lesson</button>
    </div>
    <p v-if="error" class="notice bad" role="alert" style="margin-bottom: 14px">{{ error }}</p>
    <p v-if="loading" class="muted">Loading…</p>
    <div v-else-if="!lessons.length" class="card empty">
      <h2>No lessons yet</h2>
      <button class="btn primary" style="margin-top: 16px" @click="showUpload = true"><Icon name="upload" />Upload a lesson</button>
    </div>

    <div class="list">
      <article v-for="l in lessons" :key="l.id" class="card lesson" :class="l.status">
        <div class="l-main">
          <div class="l-title">
            <h2>{{ l.title }}</h2>
            <span class="chip" :class="{ ok: l.status === 'confirmed', info: l.status === 'ready', bad: l.status === 'failed', warn: isProcessing(l) }">
              {{ STATUS_LABEL[l.status] }}
            </span>
          </div>
          <p class="small muted">
            {{ l.taught_on }}<template v-if="l.duration_ms"> · {{ tc(l.duration_ms) }}</template>
<template v-if="!l.has_slides"> · no slides</template>
          </p>

          <template v-if="isProcessing(l)">
            <ol class="stages" aria-label="Processing progress">
              <li v-for="(label, i) in STAGE_LABEL" :key="label" :class="stageState(l, i)"><i>{{ i + 1 }}</i>{{ label }}</li>
              <li class="todo"><i>4</i>Review</li>
            </ol>
            <p v-if="l.queue_position" class="small muted">{{ l.queue_position }} ahead in the queue</p>
          </template>

          <p v-else-if="l.status === 'failed'" class="notice bad">
            {{ STATUS_LABEL[l.error?.stage ?? ''] ?? l.error?.stage }} failed: {{ l.error?.reason }}
          </p>

          <p v-else-if="l.status === 'uploaded'" class="notice">Upload did not finish. Delete it and upload again.</p>

          <div v-else-if="l.progress" class="l-progress">
            <div class="progress"><i :style="{ width: (l.progress.total ? l.progress.processed / l.progress.total * 100 : 0) + '%' }" /></div>
            <span class="small muted">{{ l.progress.processed }} / {{ l.progress.total }} reviewed</span>
          </div>
        </div>

        <div class="l-actions">
          <router-link v-if="l.status === 'ready'" class="btn primary" :to="`/lessons/${l.id}/review`">{{ l.progress?.processed ? 'Continue review' : 'Start review' }}</router-link>
          <router-link v-if="l.latest_report_id" class="btn" :class="{ primary: l.status === 'confirmed' }" :to="`/reports/${l.latest_report_id}`"><Icon name="doc" />View report</router-link>
          <router-link v-if="l.status === 'confirmed'" class="btn ghost" :to="`/lessons/${l.id}/review`">Back to review</router-link>
          <button v-if="l.status === 'failed'" class="btn" @click="retry(l)"><Icon name="refresh" />Retry</button>
          <button class="btn ghost danger small" @click="remove(l)"><Icon name="trash" />Delete</button>
        </div>
      </article>
    </div>

    <div v-if="showUpload" class="modal-back" @click.self="!up.busy && (showUpload = false)">
      <form class="card modal" @submit.prevent="submitUpload">
        <h2>Upload a lesson</h2>
        <label class="field"><span>Lesson title</span><input v-model="form.title" type="text" required maxlength="200" /></label>
        <label class="field"><span>Date taught</span><input v-model="form.taught_on" type="date" required /></label>

        <div class="field">
          <span>Recording</span>
          <label class="file" :class="{ chosen: video, bad: tooBig }">
            <input type="file" accept=".mp4,.mov,.mkv,.webm,.m4v,.avi,video/*" required @change="pick($event, 'video')" />
            <span class="btn small">Choose file</span>
            <span class="fname">{{ video ? video.name : 'No file chosen' }}</span>
            <span v-if="video" class="small muted">{{ fileSize(video) }}</span>
          </label>
          <small>Taught in English, up to 2 hours and 4 GB</small>
          <p v-if="tooBig" class="notice bad">The file is larger than 4 GB</p>
        </div>

        <div class="field">
          <span>Slides <em>optional</em></span>
          <label class="file" :class="{ chosen: slides }">
            <input type="file" accept=".pdf,.pptx" @change="pick($event, 'slides')" />
            <span class="btn small">Choose file</span>
            <span class="fname">{{ slides ? slides.name : 'No file chosen' }}</span>
            <span v-if="slides" class="small muted">{{ fileSize(slides) }}</span>
          </label>
          <small>PDF or PPTX</small>
        </div>

        <div v-if="up.busy" class="uploading">
          <div class="row small"><span>{{ up.step }}…</span><span class="spacer" /><span class="mono">{{ Math.round(up.ratio * 100) }}%</span></div>
          <div class="progress"><i :style="{ width: up.ratio * 100 + '%' }" /></div>
        </div>
        <p v-if="up.error" class="notice bad" role="alert">{{ up.error }}</p>
        <div class="modal-foot">
          <button type="button" class="btn" :disabled="up.busy" @click="showUpload = false">Cancel</button>
          <button class="btn primary" :disabled="up.busy || !video || tooBig">{{ up.busy ? 'Uploading…' : 'Upload and process' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.list { display: grid; gap: 14px; }
.lesson { display: flex; gap: 24px; padding: 20px 22px; align-items: center; }
.l-main { flex: 1; min-width: 0; display: grid; gap: 8px; }
.l-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.l-title h2 { font-size: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.l-progress { display: grid; gap: 6px; max-width: 420px; margin-top: 2px; }
.l-actions { flex: none; display: flex; flex-direction: column; align-items: stretch; gap: 6px; min-width: 132px; }
.l-actions .small { align-self: flex-end; }

.stages { display: flex; list-style: none; margin: 6px 0 2px; padding: 0; max-width: 560px; }
.stages li { flex: 1; display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-3); position: relative; }
.stages li:not(:last-child)::after { content: ""; flex: 1; height: 2px; margin: 0 10px 0 4px; background: var(--line); }
.stages i { flex: none; width: 20px; height: 20px; display: grid; place-items: center; border-radius: 50%; font-style: normal; font-size: 11px; font-weight: 600; background: var(--sunken); color: var(--ink-3); }
.stages li.done { color: var(--ok); }
.stages li.done i { background: var(--ok); color: #fff; }
.stages li.done::after { background: var(--ok); }
.stages li.active { color: var(--accent); font-weight: 600; }
.stages li.active i { background: var(--accent); color: #fff; animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 0 5px var(--accent-soft); } }

.field em { font-style: normal; font-weight: 400; color: var(--ink-3); margin-left: 4px; }
.file { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px dashed var(--line-strong); border-radius: var(--radius-s); cursor: pointer; }
.file:hover { border-color: var(--accent); background: #fafcfd; }
.file.chosen { border-style: solid; }
.file.bad { border-color: var(--bad); }
.file input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.file:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
.file .btn { pointer-events: none; }
.fname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
.file.chosen .fname { color: var(--ink); font-weight: 500; }
.uploading { display: grid; gap: 6px; }

@media (max-width: 720px) {
  .lesson { flex-direction: column; align-items: stretch; gap: 14px; }
  .l-actions { flex-direction: row; flex-wrap: wrap; }
  .stages li { flex-direction: column; align-items: flex-start; gap: 3px; }
  .stages li::after { display: none; }
}
</style>
