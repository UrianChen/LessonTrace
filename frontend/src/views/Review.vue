<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, tc, type Dimension, type Evidence, type Finding, type Lesson, type Metrics, type Report, type Segment, type Sentence } from '../api'
import Icon from '../components/Icon.vue'
import MetricsPanel from '../components/MetricsPanel.vue'
import Player from '../components/Player.vue'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)

const lesson = ref<Lesson | null>(null)
const sentences = ref<Sentence[]>([])
const segments = ref<Segment[]>([])
const findings = ref<Finding[]>([])
const dims = ref<Dimension[]>([])
const metrics = ref<Metrics | null>(null)
const videoSrc = ref('')
const loading = ref(true)
const error = ref('')
const tab = ref<'findings' | 'metrics'>('findings')

const player = ref<InstanceType<typeof Player>>()
const transcriptEl = ref<HTMLElement>()
const findingsEl = ref<HTMLElement>()
const currentMs = ref(0)
const mark = ref<{ from: number; to: number } | null>(null)   // 当前高亮的引文所在句子
const dirty = ref(false)                                        // 文字稿改过，可以重新分析

async function load() {
  try {
    const [l, s, g, f, d, m, v] = await Promise.all([
      api<Lesson>('GET', `/lessons/${id}`), api<Sentence[]>('GET', `/lessons/${id}/transcript`),
      api<Segment[]>('GET', `/lessons/${id}/segments`), api<Finding[]>('GET', `/lessons/${id}/findings`),
      api<Dimension[]>('GET', '/dimensions'), api<Metrics>('GET', `/lessons/${id}/metrics`),
      api<{ url: string }>('GET', `/lessons/${id}/video`),
    ])
    lesson.value = l; sentences.value = s; segments.value = g; findings.value = f
    dims.value = d; metrics.value = m; videoSrc.value = v.url
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
  const t = Number(route.query.t)
  if (Number.isFinite(t) && t > 0) nextTick(() => setTimeout(() => { player.value?.seek(t, false); scrollToMs(t) }, 400))
}
onMounted(load)

// ---- 文字稿 ----
const groups = computed(() => segments.value.map(g => {
  const list = sentences.value.slice(g.sentence_from, g.sentence_to + 1)
  return { seg: g, sentences: list, paras: paragraphs(list) }
}))
const activeIdx = computed(() => {
  const t = currentMs.value
  let found = -1
  for (const s of sentences.value) {
    if (s.start_ms > t) break
    found = s.idx
  }
  return found
})
function segTitle(g: Segment, first?: Sentence) {
  if (g.title) return g.title
  const words = (first?.text ?? '').split(/\s+/)
  return words.slice(0, 8).join(' ') + (words.length > 8 ? '…' : '')
}
function scrollToMs(ms: number) {
  const s = sentences.value.find(x => x.end_ms > ms) ?? sentences.value.at(-1)
  if (!s) return
  transcriptEl.value?.querySelector(`[data-idx="${s.idx}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}
let lastScrolled = -1
// 点了证据后文字稿先停在引文处，播到引文再继续跟随。跳转刚发出时播放器还会报一两次旧时间，要容忍。
let hold: { from: number; until: number; at: number } | null = null
function onTime(ms: number) {
  currentMs.value = ms
  if (hold) {
    const left = ms >= hold.until || (ms < hold.from - 500 && performance.now() - hold.at > 1000)
    if (!left) return
    hold = null
  }
  if (follow.value && activeIdx.value !== lastScrolled && !hovering.value && !sel.value) {
    lastScrolled = activeIdx.value
    transcriptEl.value?.querySelector(`[data-idx="${lastScrolled}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
}
const hovering = ref(false)

function clickSentence(s: Sentence) {
  if (window.getSelection()?.toString().trim()) return   // 正在选字，不跳转
  mark.value = null
  hold = null
  player.value?.seek(s.start_ms)
}

/** 点证据：播放器跳到片段起点并播放到片段终点，文字稿滚动并高亮引文。 */
function playEvidence(ev: Evidence) {
  if (ev.start_ms == null || ev.end_ms == null) return
  mark.value = { from: ev.quote_start_ms ?? ev.start_ms, to: ev.quote_end_ms ?? ev.end_ms }
  hold = { from: ev.start_ms, until: mark.value.from, at: performance.now() }
  player.value?.playRange(ev.start_ms, ev.end_ms)
  scrollToMs(mark.value.from)
}
const isMarked = (s: Sentence) => !!mark.value && s.start_ms >= mark.value.from && s.end_ms <= mark.value.to

// ---- 修正文字稿 ----
const editingSentence = reactive<{ id: number | null; text: string; speaker: string; busy: boolean }>({ id: null, text: '', speaker: 'teacher', busy: false })
function editSentence(s: Sentence) {
  Object.assign(editingSentence, { id: s.id, text: s.text, speaker: s.speaker })
}
async function saveSentence() {
  editingSentence.busy = true
  try {
    const s = await api<Sentence>('PATCH', `/sentences/${editingSentence.id}`, { text: editingSentence.text, speaker: editingSentence.speaker })
    sentences.value[s.idx] = s
    editingSentence.id = null
    dirty.value = true
    metrics.value = await api<Metrics>('GET', `/lessons/${id}/metrics`)
    findings.value = await api<Finding[]>('GET', `/lessons/${id}/findings`)
  } catch (e: any) {
    error.value = e.message
  } finally {
    editingSentence.busy = false
  }
}
async function reanalyze() {
  if (!confirm('Re-analyzing replaces the findings you have not handled yet. Findings you accepted or edited are kept. Continue?')) return
  try { await api('POST', `/lessons/${id}/reanalyze`); router.push('/lessons') } catch (e: any) { error.value = e.message }
}

// ---- 在文字稿上选一段作为证据 ----
const sel = ref<{ seg: string; text: string; x: number; y: number } | null>(null)
function onSelect() {
  const s = window.getSelection()
  const text = s?.toString().replace(/\s+/g, ' ').trim() ?? ''
  if (!s || s.rangeCount === 0 || text.length < 3) { sel.value = null; return }
  const segOf = (n: Node | null) => (n instanceof Element ? n : n?.parentElement)?.closest<HTMLElement>('[data-seg]')?.dataset.seg
  const a = segOf(s.anchorNode), b = segOf(s.focusNode)
  if (!a || !b) { sel.value = null; return }
  const r = s.getRangeAt(0).getBoundingClientRect()
  sel.value = { seg: a === b ? a : '', text, x: r.left + r.width / 2, y: r.top }
}
function clearSel() {
  sel.value = null
  window.getSelection()?.removeAllRanges()
}
document.addEventListener('selectionchange', onSelectionGone)
function onSelectionGone() {
  if (!window.getSelection()?.toString().trim()) sel.value = null
}
onBeforeUnmount(() => document.removeEventListener('selectionchange', onSelectionGone))

function useSelection() {
  if (!sel.value?.seg) return
  const ev = { segment_id: sel.value.seg, quote: sel.value.text }
  if (editor.open) editor.evidence.push(ev)
  else openEditor(null, [ev])
  tab.value = 'findings'
  clearSel()
}

// ---- 条目 ----
const visible = computed(() => findings.value.filter(f => f.status !== 'rejected'))
const rejected = computed(() => findings.value.filter(f => f.status === 'rejected'))
const pending = computed(() => findings.value.filter(f => f.status === 'draft').length)
const byDim = computed(() => dims.value.map(d => ({ dim: d, items: visible.value.filter(f => f.dimension === d.name) })))
const showRejected = ref(false)
const STATUS = { draft: 'To do', accepted: 'Accepted', edited: 'Edited', rejected: 'Removed' }

function replace(f: Finding) {
  const i = findings.value.findIndex(x => x.id === f.id)
  if (i >= 0) findings.value[i] = f
  else findings.value.push(f)
}
async function act(f: Finding, action: 'accept' | 'reject') {
  try { replace(await api<Finding>('PATCH', `/findings/${f.id}`, { action })) } catch (e: any) { error.value = e.message }
}

const editor = reactive<{ open: boolean; id: number | null; dimension: string; observation: string; suggestion: string
  evidence: { segment_id: string; quote: string }[]; busy: boolean; error: string }>(
  { open: false, id: null, dimension: '', observation: '', suggestion: '', evidence: [], busy: false, error: '' })

function openEditor(f: Finding | null, evidence: { segment_id: string; quote: string }[] = []) {
  Object.assign(editor, {
    open: true, id: f?.id ?? null, dimension: f?.dimension ?? dims.value[0]?.name ?? '', error: '',
    observation: f?.observation ?? '', suggestion: f?.suggestion ?? '',
    evidence: f ? f.evidence.map(e => ({ segment_id: e.segment_id, quote: e.quote })) : evidence,
  })
  nextTick(() => findingsEl.value?.scrollTo({ top: 0, behavior: 'smooth' }))
}
async function saveEditor() {
  if (!editor.evidence.length) { editor.error = 'Add at least one piece of evidence: select some text in the transcript.'; return }
  editor.busy = true
  editor.error = ''
  try {
    const body = { observation: editor.observation, suggestion: editor.suggestion, evidence: editor.evidence }
    replace(editor.id == null
      ? await api<Finding>('POST', `/lessons/${id}/findings`, { ...body, dimension: editor.dimension })
      : await api<Finding>('PATCH', `/findings/${editor.id}`, { ...body, action: 'edit' }))
    editor.open = false
  } catch (e: any) {
    editor.error = e.message
  } finally {
    editor.busy = false
  }
}

// ---- 报告 ----
const report = reactive({ open: false, reflection: '', busy: false, error: '' })
async function generateReport() {
  report.busy = true
  report.error = ''
  try {
    const r = await api<Report>('POST', `/lessons/${id}/report`, { reflection: report.reflection })
    router.push(`/reports/${r.id}`)
  } catch (e: any) {
    report.error = e.message
  } finally {
    report.busy = false
  }
}

// ---- 版面辅助 ----
const speakersKnown = computed(() => sentences.value.some(s => s.speaker !== 'unknown'))
const SPEAKER: Record<string, string> = { teacher: 'Teacher', student: 'Student', unknown: 'Unknown' }
const follow = ref(true)
const filter = ref<'all' | 'todo' | 'done'>('all')
const doneCount = computed(() => findings.value.length - pending.value)
const progressPct = computed(() => (findings.value.length ? Math.round((doneCount.value / findings.value.length) * 100) : 0))
const activeSeg = computed(() => {
  const t = currentMs.value
  return segments.value.find(g => t >= g.start_ms && t < g.end_ms)?.id ?? ''
})
const shown = computed(() => byDim.value
  .map(g => ({ dim: g.dim, items: g.items.filter(f => filter.value === 'all' || (filter.value === 'todo') === (f.status === 'draft')) }))
  .filter(g => g.items.length))

/** 把一个片段里的句子排成段落：说话人变了，或停顿超过 1.5 秒，就另起一段。 */
function paragraphs(list: Sentence[]) {
  const out: { speaker: string; sentences: Sentence[] }[] = []
  let prev: Sentence | null = null
  for (const s of list) {
    if (!prev || prev.speaker !== s.speaker || s.start_ms - prev.end_ms >= 1500) out.push({ speaker: s.speaker, sentences: [] })
    out[out.length - 1].sentences.push(s)
    prev = s
  }
  return out
}
</script>

<template>
  <div v-if="loading" class="page muted">Loading…</div>
  <div v-else-if="!lesson" class="page"><p class="notice bad">{{ error || 'Lesson not found' }}</p></div>
  <div v-else class="review">
    <header class="bar">
      <router-link to="/lessons" class="btn small ghost" aria-label="Back to My Lessons"><Icon name="back" />My Lessons</router-link>
      <div class="title">
        <h1>{{ lesson.title }}</h1>
        <span class="small muted">{{ lesson.taught_on }} · {{ tc(lesson.duration_ms) }}</span>
      </div>
      <span class="spacer" />
      <div class="prog" :title="pending ? `${pending} left to review` : 'All reviewed'">
        <span class="small"><b>{{ doneCount }}</b> / {{ findings.length }} reviewed</span>
        <div class="progress"><i :style="{ width: progressPct + '%' }" /></div>
      </div>
      <button v-if="lesson.status === 'ready'" class="btn small" :class="dirty ? 'primary' : 'ghost'" @click="reanalyze">
        <Icon name="refresh" />Re-analyze
      </button>
      <button class="btn primary" :disabled="pending > 0" :title="pending ? `Review the remaining ${pending} findings first` : ''" @click="report.open = true">
        <Icon name="doc" />Generate report
      </button>
    </header>
    <p v-if="error" class="notice bad top-err" role="alert">{{ error }} <button class="btn small ghost" @click="error = ''">Dismiss</button></p>

    <div class="cols">
      <!-- 左：播放器 + 文字稿 -->
      <section class="left">
        <Player v-if="videoSrc" ref="player" :src="videoSrc" @time="onTime" />

        <div class="card transcript-card">
          <div class="pane-head">
            <h2>Transcript</h2>
            <span class="spacer" />
            <span v-if="dirty" class="chip warn">Edited</span>
            <label class="follow small"><input v-model="follow" type="checkbox" /> Follow playback</label>
          </div>
          <div ref="transcriptEl" class="transcript" @mouseup="onSelect" @mouseenter="hovering = true" @mouseleave="hovering = false">
            <section v-for="g in groups" :key="g.seg.id" class="seg" :class="{ current: g.seg.id === activeSeg }" :data-seg="g.seg.id">
              <header class="seg-head">
                <button class="seg-play" :title="`Play segment ${g.seg.id}`" @click="player?.playRange(g.seg.start_ms, g.seg.end_ms)">
                  <Icon name="play" /><span class="mono">{{ tc(g.seg.start_ms) }}</span>
                </button>
                <span class="seg-title">{{ segTitle(g.seg, g.sentences[0]) }}</span>
                <span class="spacer" />
                <span v-if="g.seg.slide_page" class="chip">Slide {{ g.seg.slide_page }}</span>
              </header>
              <div v-for="(p, pi) in g.paras" :key="pi" class="para" :class="p.speaker">
                <span v-if="speakersKnown" class="who">{{ SPEAKER[p.speaker] }}</span>
                <div class="text">
                  <template v-for="s in p.sentences" :key="s.id">
                    <span class="s" :class="{ active: s.idx === activeIdx, marked: isMarked(s), editing: editingSentence.id === s.id }"
                          :data-idx="s.idx" @click="clickSentence(s)">{{ s.text }}<span class="fixwrap"><button
                          class="fix" title="Correct the text or speaker" aria-label="Correct this sentence" @click.stop="editSentence(s)"><Icon name="edit" /></button></span></span>{{ ' ' }}
                  </template>
                  <form v-if="p.sentences.some(s => s.id === editingSentence.id)" class="sent-edit" @submit.prevent="saveSentence">
                    <textarea v-model="editingSentence.text" rows="2" required aria-label="Sentence text" />
                    <div class="row">
                      <select v-model="editingSentence.speaker" aria-label="Speaker">
                        <option value="teacher">Teacher</option><option value="student">Student</option><option value="unknown">Unknown</option>
                      </select>
                      <span class="spacer" />
                      <button type="button" class="btn small ghost" @click="editingSentence.id = null">Cancel</button>
                      <button class="btn small primary" :disabled="editingSentence.busy">Save</button>
                    </div>
                  </form>
                </div>
              </div>
            </section>
          </div>
        </div>
      </section>

      <!-- 右：分析条目 / 课堂数据 -->
      <section class="right">
        <div class="pane-head bare">
          <div class="seg-ctl" role="tablist">
            <button role="tab" :aria-selected="tab === 'findings'" @click="tab = 'findings'">Findings</button>
            <button role="tab" :aria-selected="tab === 'metrics'" @click="tab = 'metrics'">Class data</button>
          </div>
          <span class="spacer" />
          <button v-if="tab === 'findings' && !editor.open" class="btn small" @click="openEditor(null)"><Icon name="plus" />Add finding</button>
        </div>

        <div v-show="tab === 'findings'" ref="findingsEl" class="scroll">
          <form v-if="editor.open" class="card editor" @submit.prevent="saveEditor">
            <h3>{{ editor.id == null ? 'Add finding' : 'Edit finding' }}</h3>
            <label v-if="editor.id == null" class="field"><span>Dimension</span>
              <select v-model="editor.dimension"><option v-for="d in dims" :key="d.name" :value="d.name">{{ d.name }}</option></select>
            </label>
            <label class="field"><span>Observation</span><textarea v-model="editor.observation" rows="3" required /></label>
            <label class="field"><span>Suggestion</span><textarea v-model="editor.suggestion" rows="2" required /></label>
            <div class="field">
              <span>Evidence</span>
              <p v-if="!editor.evidence.length" class="ev-empty small">Select some text in the transcript</p>
              <div v-for="(e, i) in editor.evidence" :key="i" class="ev-edit">
                <span class="mono code">{{ e.segment_id }}</span>
                <q>{{ e.quote }}</q>
                <button type="button" class="btn small ghost danger" aria-label="Remove this evidence" @click="editor.evidence.splice(i, 1)"><Icon name="trash" /></button>
              </div>
            </div>
            <p v-if="editor.error" class="notice bad" role="alert">{{ editor.error }}</p>
            <div class="modal-foot">
              <button type="button" class="btn small ghost" @click="editor.open = false">Cancel</button>
              <button class="btn small primary" :disabled="editor.busy">Save</button>
            </div>
          </form>

          <div v-if="findings.length" class="filters">
            <div class="seg-ctl">
              <button :aria-pressed="filter === 'all'" @click="filter = 'all'">All<span class="n">{{ visible.length }}</span></button>
              <button :aria-pressed="filter === 'todo'" @click="filter = 'todo'">To do<span class="n">{{ pending }}</span></button>
              <button :aria-pressed="filter === 'done'" @click="filter = 'done'">Done<span class="n">{{ visible.length - pending }}</span></button>
            </div>
          </div>

          <p v-for="(why, name) in lesson.skipped_dimensions" :key="name" class="notice">
            “{{ name }}” was not analyzed: {{ why }}.
          </p>
          <div v-if="!findings.length" class="card empty">
            <p>No findings</p>
          </div>
          <div v-else-if="!shown.length" class="card empty">
            <p>{{ filter === 'todo' ? 'All reviewed' : 'Nothing reviewed yet' }}</p>
          </div>

          <section v-for="g in shown" :key="g.dim.name" class="dim">
            <h3 :title="g.dim.definition">{{ g.dim.name }}<span class="count">{{ g.items.length }}</span></h3>
            <article v-for="f in g.items" :key="f.id" class="card finding" :class="f.status">
              <div v-if="f.status !== 'draft' || f.source === 'teacher'" class="f-meta">
                <span v-if="f.status !== 'draft'" class="chip ok"><Icon name="check" />{{ STATUS[f.status] }}</span>
                <span v-if="f.source === 'teacher'" class="chip info">Added by you</span>
              </div>
              <p class="obs">{{ f.observation }}</p>
              <div class="sug"><span class="label">Suggestion</span>{{ f.suggestion }}</div>
              <ul class="evidence" aria-label="Evidence">
                <li v-for="(e, i) in f.evidence" :key="i">
                  <button class="ev" :title="`Play segment ${e.segment_id} and show the quote in the transcript`" @click="playEvidence(e)">
                    <span class="ev-play"><Icon name="play" /></span>
                    <span class="ev-body"><q>{{ e.quote }}</q><span class="mono time">{{ tc(e.start_ms) }}–{{ tc(e.end_ms) }}</span></span>
                  </button>
                </li>
              </ul>
              <div class="f-actions">
                <button v-if="f.status === 'draft'" class="btn small primary" @click="act(f, 'accept')"><Icon name="check" />Accept</button>
                <button class="btn small" :class="{ ghost: f.status !== 'draft' }" @click="openEditor(f)"><Icon name="edit" />Edit</button>
                <span class="spacer" />
                <button class="btn small ghost danger" @click="act(f, 'reject')"><Icon name="trash" />Remove</button>
              </div>
            </article>
          </section>

          <section v-if="rejected.length" class="dim">
            <button class="btn small ghost" @click="showRejected = !showRejected">{{ showRejected ? 'Hide' : 'Show' }} removed findings ({{ rejected.length }})</button>
            <template v-if="showRejected">
              <article v-for="f in rejected" :key="f.id" class="card finding rejected">
                <p class="obs">{{ f.observation }}</p>
                <div class="f-actions"><button class="btn small" @click="act(f, 'accept')"><Icon name="undo" />Restore and accept</button></div>
              </article>
            </template>
          </section>
        </div>

        <div v-show="tab === 'metrics'" class="scroll">
          <MetricsPanel v-if="metrics" :metrics="metrics" :duration-ms="lesson.duration_ms ?? 0" @seek="ms => { mark = null; player?.seek(ms); scrollToMs(ms) }" />
        </div>
      </section>
    </div>

    <button v-if="sel" class="sel-btn btn small primary" :style="{ left: sel.x + 'px', top: sel.y + 'px' }" :disabled="!sel.seg"
            @mousedown.prevent @click="useSelection">
      <Icon v-if="sel.seg" name="plus" />{{ !sel.seg ? 'Evidence cannot span segments' : editor.open ? 'Add as evidence' : 'New finding from this text' }}
    </button>

    <div v-if="report.open" class="modal-back" @click.self="!report.busy && (report.open = false)">
      <form class="card modal" @submit.prevent="generateReport">
        <h2>Generate report</h2>
        <p class="muted">Includes the {{ visible.length }} findings you kept. Only you can see it until you submit it.</p>
        <label class="field"><span>Reflection <em style="font-style: normal; font-weight: 400; color: var(--ink-3)">optional</em></span><textarea v-model="report.reflection" rows="5" /></label>
        <p v-if="report.error" class="notice bad" role="alert">{{ report.error }}</p>
        <div class="modal-foot">
          <button type="button" class="btn" :disabled="report.busy" @click="report.open = false">Cancel</button>
          <button class="btn primary" :disabled="report.busy">{{ report.busy ? 'Generating…' : 'Generate report' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.review { height: 100%; display: flex; flex-direction: column; }
.bar { display: flex; align-items: center; gap: 12px; padding: 10px 20px; background: var(--surface); border-bottom: 1px solid var(--line); flex: none; }
.title { min-width: 0; display: grid; }
.title h1 { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.prog { display: grid; gap: 4px; width: 132px; }
.prog .small { color: var(--ink-2); }
.prog b { color: var(--ink); font-variant-numeric: tabular-nums; }
.top-err { margin: 10px 20px 0; }

.cols { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(380px, 460px); gap: 20px; padding: 16px 20px 20px; }
.left, .right { min-height: 0; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.left :deep(.frame) { flex: none; width: min(100%, calc(38vh * 16 / 9)); margin: 0 auto; }

.pane-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--line); flex: none; }
.pane-head.bare { padding: 0; border: 0; min-height: 34px; }
.pane-head h2 { font-size: 14px; }
.follow { display: flex; align-items: center; gap: 5px; color: var(--ink-2); cursor: pointer; user-select: none; }
.follow input { accent-color: var(--accent); }

/* ---- 文字稿 ---- */
.transcript-card { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.transcript { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; scroll-padding-top: 44px; }
.seg { padding: 0 18px 14px; border-bottom: 1px solid var(--line); border-left: 3px solid transparent; }
.seg:last-child { border-bottom: 0; }
.seg.current { border-left-color: var(--accent); }
.seg-head { display: flex; align-items: center; gap: 10px; position: sticky; top: 0; z-index: 2; padding: 10px 0 8px; background: var(--surface); }
.seg-play { display: inline-flex; align-items: center; gap: 4px; height: 24px; padding: 0 8px 0 6px; border: 0; border-radius: 12px; background: var(--accent-soft); color: var(--accent); font-size: 12px; cursor: pointer; }
.seg-play:hover { background: var(--accent); color: #fff; }
.seg-play .icon { width: 12px; height: 12px; }
.seg-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.code { font-size: 11px; color: var(--ink-3); }
.para { display: flex; gap: 12px; margin-top: 8px; }
.para .who { flex: none; width: 34px; padding-top: 3px; font-size: 12px; font-weight: 600; color: var(--teacher); user-select: none; }
.para.student .who { color: var(--student); }
.para.unknown .who { color: var(--ink-3); }
.para .text { flex: 1; min-width: 0; font-size: 15px; line-height: 1.75; color: var(--ink); overflow-wrap: anywhere; }
.para.student .text { color: #5a3a17; }
.s { cursor: pointer; border-radius: 3px; padding: 1px 0; -webkit-box-decoration-break: clone; box-decoration-break: clone; }
.s:hover { background: var(--sunken); }
.s.active { background: var(--accent-soft); }
.s.marked { background: var(--mark); }
.s.editing { outline: 1px dashed var(--accent); }
.fixwrap { position: relative; display: inline-block; width: 0; height: 0; user-select: none; }
.fix { position: absolute; left: 3px; bottom: -5px; width: 22px; height: 22px; padding: 0; display: grid; place-items: center; border: 1px solid var(--line-strong); border-radius: 5px; background: var(--surface); color: var(--ink-2); box-shadow: var(--shadow); cursor: pointer; opacity: 0; pointer-events: none; }
.fix .icon { width: 13px; height: 13px; }
.s:hover .fix, .fix:focus-visible { opacity: 1; pointer-events: auto; }
.fix:hover { color: var(--accent); border-color: var(--accent); }
.sent-edit { display: grid; gap: 8px; margin: 8px 0 4px; padding: 10px; border: 1px solid var(--accent); border-radius: var(--radius-s); background: #fafcfd; font-size: 14px; }
.sent-edit select { width: 96px; }

/* ---- 条目 ---- */
.scroll { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding: 2px 4px 16px 2px; }
.filters { display: flex; }
.dim { display: grid; gap: 10px; }
.dim h3 { display: flex; align-items: baseline; gap: 8px; padding-top: 4px; }
.dim h3 .en { font-weight: 400; font-size: 12px; color: var(--ink-3); }
.dim h3 .count { margin-left: auto; font-size: 12px; font-weight: 500; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.finding { padding: 14px 16px; display: grid; gap: 10px; }
.finding.accepted, .finding.edited { background: #fbfdfc; border-color: #d6e7de; box-shadow: none; }
.finding.rejected { opacity: .65; box-shadow: none; }
.f-meta { display: flex; gap: 6px; }
.f-meta .icon { width: 12px; height: 12px; }
.obs { font-size: 15px; line-height: 1.6; }
.sug { padding: 8px 12px; border-left: 3px solid var(--line-strong); background: var(--bg); border-radius: 0 var(--radius-s) var(--radius-s) 0; color: var(--ink-2); }
.label { display: block; font-size: 12px; font-weight: 600; color: var(--ink-3); margin-bottom: 2px; }
.evidence { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.ev { display: flex; gap: 10px; align-items: flex-start; width: 100%; text-align: left; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius-s); background: var(--surface); cursor: pointer; transition: border-color .12s, background .12s; }
.ev:hover { border-color: var(--accent); background: var(--accent-soft); }
.ev-play { flex: none; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: var(--accent-soft); color: var(--accent); }
.ev:hover .ev-play { background: var(--accent); color: #fff; }
.ev-play .icon { width: 12px; height: 12px; }
.ev-body { display: grid; gap: 2px; min-width: 0; }
.ev q { font-size: 13px; color: var(--ink); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.ev .time { font-size: 11px; color: var(--ink-3); }
.f-actions { display: flex; gap: 6px; align-items: center; margin-top: 2px; }
.editor { padding: 16px; display: grid; gap: 12px; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.ev-empty { padding: 10px 12px; border: 1px dashed var(--line-strong); border-radius: var(--radius-s); color: var(--ink-3); }
.ev-edit { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; font-size: 13px; padding: 4px 4px 4px 10px; border: 1px solid var(--line); border-radius: var(--radius-s); }
.sel-btn { position: fixed; transform: translate(-50%, calc(-100% - 8px)); z-index: 40; box-shadow: var(--shadow-pop); }

@media (max-width: 1100px) { .hint { display: none; } }
@media (max-width: 900px) {
  .review { height: auto; }
  .bar { flex-wrap: wrap; }
  .cols { grid-template-columns: minmax(0, 1fr); padding: 12px; }
  .bar { padding: 10px 12px; }
  .title { flex: 1 1 60%; }
  .seg { padding: 0 12px 12px; }
  .transcript-card { max-height: 60vh; }
  .left :deep(.frame) { width: 100%; }
}
</style>
