import { reactive } from 'vue'

export type Role = 'teacher' | 'center' | 'admin'
export interface User { id: number; username: string; name: string; role: Role; dept: string; active: boolean }

export interface Lesson {
  id: number; title: string; taught_on: string; status: string
  error: { stage: string; reason: string } | null
  duration_ms: number | null; has_slides: boolean; created_at: string; started: boolean
  queue_position?: number | null
  progress?: { total: number; processed: number }
  skipped_dimensions?: Record<string, string>
  latest_report_id?: number | null
}
export interface Sentence { id: number; idx: number; start_ms: number; end_ms: number; speaker: string; text: string }
export interface Segment {
  id: string; start_ms: number; end_ms: number; title: string
  slide_page: number | null; sentence_from: number; sentence_to: number
}
export interface Evidence {
  segment_id: string; quote: string
  start_ms?: number; end_ms?: number; quote_start_ms?: number; quote_end_ms?: number
}
export interface Finding {
  id: number; dimension: string; observation: string; suggestion: string
  status: 'draft' | 'accepted' | 'edited' | 'rejected'; source: 'model' | 'teacher'; evidence: Evidence[]
}
export interface Dimension { name: string; name_zh: string; definition: string }
export interface Question { sentence_idx: number; at_ms: number; segment: string | null; wait_ms: number | null; answered_by: string | null }
export interface Metrics {
  lesson: {
    speakers_identified?: boolean
    teacher_talk_ms?: number; student_talk_ms?: number
    teacher_talk_ratio?: number | null; student_talk_ratio?: number | null
    teacher_turns?: number; student_turns?: number; speech_rate_wpm?: number | null
    question_count?: number; avg_wait_ms?: number | null; student_question_count?: number
    questions?: Question[]
    slide_dwell?: { page_no: number; start_ms: number | null; end_ms: number | null; dwell_ms: number | null }[]
  }
  segments: Record<string, Record<string, number | null>>
  note: string
}
export interface ReportContent {
  header_note: string; version: number; generated_at: string
  lesson: { title: string; taught_on: string; teacher: string; dept: string; duration_ms: number | null }
  metrics: Metrics['lesson']
  dimensions: { name: string; name_zh: string; findings: { observation: string; suggestion: string; source: string; evidence: Evidence[] }[] }[]
  reflection: string
}
export interface Report {
  id: number; lesson_id: number; version: number; created_at: string; submitted_at: string | null
  title: string; taught_on: string; teacher: string; has_pdf: boolean; content?: ReportContent
}

const TOKEN_KEY = 'lessontrace.token'
const USER_KEY = 'lessontrace.user'

function load<T>(key: string): T | null {
  try { return JSON.parse(localStorage.getItem(key) || 'null') } catch { return null }
}

export const session = reactive<{ token: string | null; user: User | null }>({
  token: load<string>(TOKEN_KEY), user: load<User>(USER_KEY),
})

export function setSession(token: string | null, user: User | null) {
  session.token = token
  session.user = user
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, JSON.stringify(token))
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } else {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    }
  } catch { /* falls back to this session only */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch('/api' + path, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(session.token ? { Authorization: `Bearer ${session.token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check that the services are running.')
  }
  if (res.status === 401 && path !== '/auth/login') {
    setSession(null, null)
    location.assign('/login')
    throw new ApiError(401, 'Your session has expired. Please sign in again.')
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const d = data?.detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join('; ') : `Request failed (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return data as T
}

/** 用签名地址把文件直传到对象存储，不经过 API 进程。 */
export function uploadFile(url: string, file: File, onProgress: (ratio: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)))
    xhr.onerror = () => reject(new Error('Upload interrupted. Check your connection and try again.'))
    xhr.send(file)
  })
}

export function tc(ms: number | null | undefined): string {
  if (ms == null) return '—'
  const s = Math.floor(ms / 1000)
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mm}:${ss}` : `${mm}:${ss}`
}

export function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

export const STATUS_LABEL: Record<string, string> = {
  uploaded: 'Uploaded', transcribing: 'Transcribing', segmenting: 'Segmenting', analyzing: 'Analyzing',
  ready: 'Ready for review', confirmed: 'Confirmed', failed: 'Failed',
}
