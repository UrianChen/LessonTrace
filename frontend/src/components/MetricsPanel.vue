<script setup lang="ts">
import { computed } from 'vue'
import { pct, tc, type Metrics } from '../api'

const props = defineProps<{ metrics: Metrics; durationMs: number }>()
const emit = defineEmits<{ seek: [ms: number] }>()

const m = computed(() => props.metrics.lesson)
const questions = computed(() => m.value.questions ?? [])
const dwell = computed(() => m.value.slide_dwell ?? [])
const maxDwell = computed(() => Math.max(1, ...dwell.value.map(d => d.dwell_ms ?? 0)))
const ticks = computed(() => {
  const step = props.durationMs > 40 * 60000 ? 10 * 60000 : props.durationMs > 12 * 60000 ? 5 * 60000 : 60000
  const out: number[] = []
  for (let t = 0; t <= props.durationMs; t += step) out.push(t)
  return out
})
const x = (ms: number) => (props.durationMs ? (ms / props.durationMs) * 100 : 0)
const teacherShare = computed(() => (m.value.teacher_talk_ratio ?? 0) * 100)
const noSpeakers = computed(() => m.value.speakers_identified === false)
</script>

<template>
  <div class="panel">
    <p class="small muted">Computed facts, not judgements. Student speech may be under-recorded.</p>

    <p v-if="noSpeakers" class="notice">
      Speakers were not separated, so the teacher/student split is unavailable.
    </p>

    <section v-if="!noSpeakers">
      <h3>Talk time</h3>
      <div class="bar" role="img" :aria-label="`Teacher ${pct(m.teacher_talk_ratio)}, students ${pct(m.student_talk_ratio)}`">
        <i class="t" :style="{ width: teacherShare + '%' }" /><i class="s" :style="{ width: 100 - teacherShare + '%' }" />
      </div>
      <div class="row small legend">
        <span><b class="dot t" />Teacher {{ pct(m.teacher_talk_ratio) }} ({{ tc(m.teacher_talk_ms) }}, {{ m.teacher_turns ?? 0 }} {{ m.teacher_turns === 1 ? 'turn' : 'turns' }})</span>
        <span class="spacer" />
        <span><b class="dot s" />Students {{ pct(m.student_talk_ratio) }} ({{ tc(m.student_talk_ms) }}, {{ m.student_turns ?? 0 }} {{ m.student_turns === 1 ? 'turn' : 'turns' }})</span>
      </div>
    </section>

    <section class="tiles">
      <div><span class="small muted">{{ noSpeakers ? 'Questions' : 'Teacher questions' }}</span><strong>{{ m.question_count ?? 0 }}</strong></div>
      <div><span class="small muted">Avg. wait after a question</span><strong>{{ m.avg_wait_ms == null ? '—' : (m.avg_wait_ms / 1000).toFixed(1) }}<small> s</small></strong></div>
      <div><span class="small muted">{{ noSpeakers ? 'Speech rate' : 'Teacher speech rate' }}</span><strong>{{ m.speech_rate_wpm == null ? '—' : Math.round(m.speech_rate_wpm) }}<small> wpm</small></strong></div>
      <div><span class="small muted">Student questions</span><strong>{{ m.student_question_count ?? 0 }}</strong></div>
    </section>

    <section>
      <h3>Questions over time</h3>
      <p v-if="!questions.length" class="small muted">No questions detected</p>
      <div v-else class="timeline">
        <div class="track">
          <button v-for="q in questions" :key="q.sentence_idx" class="q" :style="{ left: x(q.at_ms) + '%' }"
                  :title="`${tc(q.at_ms)} · wait ${q.wait_ms == null ? '—' : (q.wait_ms / 1000).toFixed(1) + ' s'}`"
                  :aria-label="`Jump to the question at ${tc(q.at_ms)}`" @click="emit('seek', q.at_ms)" />
        </div>
        <div class="axis"><span v-for="t in ticks" :key="t" class="mono" :style="{ left: x(t) + '%' }">{{ tc(t) }}</span></div>
      </div>
    </section>

    <section>
      <h3>Time per slide</h3>
      <p v-if="!dwell.length" class="small muted">No slides</p>
      <table v-else class="dwell">
        <tr v-for="d in dwell" :key="d.page_no">
          <th class="small">Slide {{ d.page_no }}</th>
          <td>
            <button v-if="d.dwell_ms != null" class="dbar" :style="{ width: Math.max(2, (d.dwell_ms / maxDwell) * 100) + '%' }"
                    :title="`Jump to ${tc(d.start_ms)}`" @click="emit('seek', d.start_ms!)" />
            <span v-else class="small muted">Not matched</span>
          </td>
          <td class="mono small">{{ d.dwell_ms == null ? '' : tc(d.dwell_ms) }}</td>
        </tr>
      </table>
    </section>
  </div>
</template>

<style scoped>
.panel { display: grid; gap: 24px; padding: 2px 2px 20px; }
.panel h3 { font-size: 14px; }
section { display: grid; gap: 8px; }
.bar { display: flex; gap: 2px; height: 16px; }
.bar i { display: block; border-radius: 4px; min-width: 3px; }
.t { background: var(--teacher); }
.s { background: var(--student); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.legend { color: var(--ink-2); }
.tiles { grid-template-columns: repeat(2, 1fr); gap: 10px; }
.tiles > div { display: grid; gap: 2px; padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow); }
.tiles strong { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tiles small { font-size: 12px; font-weight: 400; color: var(--ink-3); }
.timeline { padding: 0 22px; }
.track { position: relative; height: 28px; border-bottom: 1px solid var(--ink-3); }
.q { position: absolute; bottom: 0; width: 9px; height: 20px; margin-left: -4.5px; padding: 0; border: 0; border-radius: 2px 2px 0 0; background: var(--teacher); opacity: .8; cursor: pointer; }
.q:hover { opacity: 1; height: 26px; }
.axis { position: relative; height: 18px; }
.axis span { position: absolute; transform: translateX(-50%); font-size: 11px; color: var(--ink-3); top: 3px; }
.dwell { width: 100%; border-collapse: collapse; }
.dwell th { width: 64px; text-align: left; font-weight: 400; color: var(--ink-2); padding: 3px 0; }
.dwell td:last-child { width: 56px; text-align: right; color: var(--ink-2); }
.dbar { display: block; height: 12px; padding: 0; border: 0; border-radius: 3px; background: var(--teacher); cursor: pointer; }
.dbar:hover { filter: brightness(1.15); }
</style>
