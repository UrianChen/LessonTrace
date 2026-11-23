<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, dateTime, pct, session, tc, type Report } from '../api'
import Icon from '../components/Icon.vue'

const route = useRoute()
const report = ref<Report | null>(null)
const error = ref('')
const busy = ref(false)
const isTeacher = computed(() => session.user?.role === 'teacher')
const c = computed(() => report.value?.content)
const count = computed(() => c.value?.dimensions.reduce((n, d) => n + d.findings.length, 0) ?? 0)

onMounted(async () => {
  try { report.value = await api<Report>('GET', `/reports/${route.params.id}`) } catch (e: any) { error.value = e.message }
})

async function pdf() {
  try {
    const r = await api<{ url: string }>('GET', `/reports/${report.value!.id}/pdf`)
    window.open(r.url, '_blank')
  } catch (e: any) { error.value = e.message }
}
async function submit() {
  if (!confirm('Once submitted, the Teaching Center can read this version of the report (not the recording, transcript or findings you removed). This cannot be undone. Submit?')) return
  busy.value = true
  try { report.value = await api<Report>('POST', `/reports/${report.value!.id}/submit`) } catch (e: any) { error.value = e.message } finally { busy.value = false }
}
</script>

<template>
  <div class="page report-page">
    <p v-if="error" class="notice bad" role="alert">{{ error }}</p>
    <template v-if="report && c">
      <div class="tools">
        <router-link :to="isTeacher ? '/lessons' : '/reports'" class="btn small ghost"><Icon name="back" />Back</router-link>
        <span class="spacer" />
        <span v-if="report.submitted_at" class="chip ok"><Icon name="check" />Submitted · {{ dateTime(report.submitted_at) }}</span>
        <span v-else-if="isTeacher" class="chip">Only visible to you</span>
        <button v-if="report.has_pdf" class="btn" @click="pdf"><Icon name="download" />Export PDF</button>
        <button v-if="isTeacher && !report.submitted_at" class="btn primary" :disabled="busy" @click="submit"><Icon name="send" />Submit to Teaching Center</button>
      </div>

      <article class="card sheet">
        <header>
          <p class="note">Reviewed and confirmed by the teacher</p>
          <h1>{{ c.lesson.title }}</h1>
          <p class="meta">
            <span>Taught {{ c.lesson.taught_on }}</span>
            <span>{{ c.lesson.teacher }}<template v-if="c.lesson.dept"> ({{ c.lesson.dept }})</template></span>
            <span v-if="c.lesson.duration_ms">{{ tc(c.lesson.duration_ms) }}</span>
            <span>Version {{ c.version }} · {{ dateTime(c.generated_at) }}</span>
          </p>
        </header>

        <section>
          <h2>Class data</h2>
          <dl class="facts">
            <div><dt>Teacher talk</dt><dd>{{ pct(c.metrics.teacher_talk_ratio) }}</dd></div>
            <div><dt>Student talk</dt><dd>{{ pct(c.metrics.student_talk_ratio) }}</dd></div>
            <div><dt>Teacher / student turns</dt><dd>{{ c.metrics.teacher_turns ?? '—' }} / {{ c.metrics.student_turns ?? '—' }}</dd></div>
            <div><dt>Questions</dt><dd>{{ c.metrics.question_count ?? '—' }}</dd></div>
            <div><dt>Avg. wait after a question</dt><dd>{{ c.metrics.avg_wait_ms == null ? '—' : (c.metrics.avg_wait_ms / 1000).toFixed(1) + ' s' }}</dd></div>
            <div><dt>Speech rate</dt><dd>{{ c.metrics.speech_rate_wpm == null ? '—' : Math.round(c.metrics.speech_rate_wpm) + ' wpm' }}</dd></div>
          </dl>
          <p class="small muted">Computed facts, not judgements. Student speech may be under-recorded.</p>
        </section>

        <p v-if="!count" class="muted">No findings were kept</p>
        <template v-for="d in c.dimensions" :key="d.name">
          <section v-if="d.findings.length">
            <h2>{{ d.name }}</h2>
            <div v-for="(f, i) in d.findings" :key="i" class="finding">
              <span class="num">{{ i + 1 }}</span>
              <div class="f-body">
                <p class="obs">{{ f.observation }}</p>
                <div class="sug"><span class="label">Suggestion</span>{{ f.suggestion }}</div>
                <ul>
                  <li v-for="(e, j) in f.evidence" :key="j">
                    <!-- 老师可以点时间码回看片段；中心看不到录像，只显示时间码 -->
                    <router-link v-if="isTeacher" class="mono time" title="Watch this segment in the review page" :to="`/lessons/${report.lesson_id}/review?t=${e.start_ms}`"><Icon name="play" />{{ tc(e.start_ms) }}–{{ tc(e.end_ms) }}</router-link>
                    <span v-else class="mono time">{{ tc(e.start_ms) }}–{{ tc(e.end_ms) }}</span>
                    <q>{{ e.quote }}</q>
                  </li>
                </ul>
              </div>
            </div>
          </section>
        </template>

        <section v-if="c.reflection">
          <h2>Teacher's reflection</h2>
          <p class="reflection">{{ c.reflection }}</p>
        </section>
      </article>
    </template>
  </div>
</template>

<style scoped>
.report-page { max-width: 860px; }
.tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 16px; }
.tools .chip .icon { width: 12px; height: 12px; }
.sheet { padding: 44px 52px; display: grid; gap: 30px; }
.note { display: inline-block; font-size: 12px; font-weight: 500; color: var(--ok); background: var(--ok-soft); padding: 3px 10px; border-radius: 11px; margin-bottom: 14px; }
.sheet h1 { font-size: 26px; margin-bottom: 10px; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 20px; color: var(--ink-3); font-size: 13px; }
section { display: grid; gap: 12px; }
section > h2 { font-size: 17px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
h2 .en { font-weight: 400; font-size: 13px; color: var(--ink-3); margin-left: 8px; }
.facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 0; }
.facts div { padding: 10px 14px; border-radius: var(--radius-s); background: var(--bg); }
.facts dt { font-size: 12px; color: var(--ink-3); }
.facts dd { margin: 2px 0 0; font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.finding { display: flex; gap: 14px; padding: 6px 0 14px; }
.finding + .finding { border-top: 1px solid var(--line); padding-top: 18px; }
.num { flex: none; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: var(--sunken); font-size: 12px; font-weight: 600; color: var(--ink-2); }
.f-body { display: grid; gap: 10px; min-width: 0; }
.obs { font-size: 15px; line-height: 1.65; }
.sug { padding: 8px 12px; border-left: 3px solid var(--line-strong); background: var(--bg); border-radius: 0 var(--radius-s) var(--radius-s) 0; color: var(--ink-2); }
.label { display: block; font-size: 12px; font-weight: 600; color: var(--ink-3); margin-bottom: 2px; }
.finding ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.finding li { display: grid; grid-template-columns: 124px 1fr; gap: 10px; align-items: baseline; font-size: 13px; color: var(--ink-2); }
.time { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; text-decoration: none; }
a.time:hover { text-decoration: underline; }
.time .icon { width: 11px; height: 11px; }
.reflection { white-space: pre-wrap; line-height: 1.75; }
@media (max-width: 700px) { .sheet { padding: 24px 18px; } .facts { grid-template-columns: 1fr 1fr; } .finding li { grid-template-columns: 1fr; gap: 0; } }
</style>
