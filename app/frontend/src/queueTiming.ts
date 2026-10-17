import type { ApiObservation, RequestQueue } from './api'

export type TimingKind = 'ai_interpret' | 'ai_explanation' | 'solver' | 'other'
type Outcome = 'PENDING' | 'CONFIRMED' | 'HELD'
export interface TimingContext {
  build_sha: string; engine_mode: string; dataset_version: string; clock_anchor: string
  state_revision: number; current_plan_id: string; total_assets: number; employees: number; customers: number
}
interface Entry {
  request_id: string; position: number; active_ms: number | null; end_ms: number | null; outcome: Outcome
  plan_ids: string[]; base_revisions: number[]; confirmed_revision: number | null; origins: string[]
}
interface Span {
  id: number; kind: TimingKind; request_id: string | null; path: string; method: string
  start_ms: number; end_ms: number | null; error_code: string | null; result_status: string | null
}
const kinds: TimingKind[] = ['ai_interpret', 'ai_explanation', 'solver', 'other']

// Disjoint wall-clock intervals: parallel GETs and explain/confirm overlap count once.
export function partition(start: number, end: number, spans: Span[]) {
  const totals = { ai_interpret_ms: 0, ai_explanation_ms: 0, solver_ms: 0, other_ms: 0, human_estimate_ms: 0 }
  const cuts = [...new Set([start, end, ...spans.flatMap(s => [Math.max(start, Math.min(end, s.start_ms)),
    Math.max(start, Math.min(end, s.end_ms ?? end))])])].sort((a, b) => a - b)
  for (let i = 1; i < cuts.length; i++) {
    const a = cuts[i - 1], b = cuts[i]
    const kind = kinds.find(k => spans.some(s => s.kind === k && s.start_ms <= a && (s.end_ms ?? end) >= b))
    const key = (kind ? `${kind}_ms` : 'human_estimate_ms') as keyof typeof totals
    totals[key] += b - a
  }
  return { ...totals, total_ms: end - start }
}

export class QueueTiming {
  readonly schema_version = 'queue-timing.v1'
  readonly run_id: string
  readonly armed_at: string
  started_at: string | null = null
  status: 'ARMED' | 'RUNNING' | 'COMPLETED' | 'ABORTED' = 'ARMED'
  queue_id: string | null = null
  issues: string[] = []
  private start: number | null = null
  private end: number | null = null
  private entries: Entry[] = []
  private spans: Span[] = []
  private now: () => number
  constructor(readonly context: TimingContext, readonly operator: string, readonly seed_sha256: string,
    readonly evidence: 'UNVERIFIED' | 'REAL' | 'FAKE', now = () => performance.now(), private wall = () => new Date().toISOString()) {
    this.now = now
    this.armed_at = wall()
    this.run_id = `QT-${this.armed_at}`
  }
  get current() { return this.entries.find(r => r.end_ms === null) }
  invalidate(reason: string) { if (!this.issues.includes(reason)) this.issues.push(reason) }
  abort(reason: string) {
    if (!['ARMED', 'RUNNING'].includes(this.status)) return
    this.invalidate(reason); this.end = this.start === null ? 0 : this.now() - this.start; this.status = 'ABORTED'
  }
  observe(event: ApiObservation) {
    if (this.status === 'COMPLETED' || this.status === 'ABORTED') return
    const creation = event.method === 'POST' && event.path === '/request-queues'
    if (this.status === 'ARMED') {
      if (!creation || event.stage !== 'start') return
      this.status = 'RUNNING'; this.start = event.started_ms; this.started_at = this.wall()
    }
    const offset = (value: number) => value - this.start!
    if (event.stage === 'start') {
      let kind: TimingKind = 'other'
      const request = event.path.match(/^\/requests\/([^/]+)\/(interpret|interpretation)$/)
      const plan = event.path.match(/^\/plans\/([^/]+)(?:\/(explanation|confirm|hold))?$/)
      const queuePath = this.queue_id && (event.path === `/request-queues/${this.queue_id}` || event.path.startsWith(`/request-queues/${this.queue_id}/`))
      const row = request ? this.entries.find(r => r.request_id === request[1])
        : plan ? this.entries.find(r => r.plan_ids.includes(plan[1])) : this.current
      if (!creation && !(queuePath || (request && row) || (plan && row)
        || /^\/(operations(?:\?|$)|reference$)/.test(event.path))) return
      if (event.method === 'POST' && /\/interpret$/.test(event.path)) kind = 'ai_interpret'
      if (event.method === 'POST' && plan?.[2] === 'explanation') kind = 'ai_explanation'
      if (event.method === 'POST' && /\/plan$/.test(event.path)) kind = 'solver'
      if (event.request_id && event.request_id !== this.current?.request_id) this.invalidate('UNEXPECTED_REQUEST')
      this.spans.push({ id: event.id, kind, request_id: row?.request_id ?? null, path: event.path, method: event.method,
        start_ms: offset(event.started_ms), end_ms: null, error_code: null, result_status: null })
      return
    }
    const span = this.spans.find(s => s.id === event.id)
    if (!span) return
    span.end_ms = offset(event.ended_ms!)
    span.error_code = event.error_code ?? null
    if (event.error_code) {
      if (creation) this.abort('QUEUE_CREATION_FAILED')
      return // Failed attempts remain in the same measured request, never retried here.
    }
    const result = event.result as any
    if (typeof result?.error_code === 'string') span.error_code = result.error_code
    span.result_status = result?.status ?? result?.explanation?.source ?? null
    if (creation) {
      const q = result as RequestQueue
      this.queue_id = q.id
      if (q.state_revision !== this.context.state_revision) this.invalidate('INITIAL_REVISION_CHANGED')
      if (q.items?.length !== 3 || q.items.some(i => i.state !== (i.position === 1 ? 'RECEIVED' : 'WAITING'))) {
        this.abort('FRESH_THREE_REQUESTS_REQUIRED'); return
      }
      this.entries = [...q.items].sort((a, b) => a.position - b.position).map((item, index) => ({
        request_id: item.request.id, position: item.position, active_ms: index === 0 ? span.end_ms : null,
        end_ms: null, outcome: 'PENDING', plan_ids: [], base_revisions: [], confirmed_revision: null, origins: [],
      }))
      return
    }
    const row = this.entries.find(r => r.request_id === span.request_id)
    if (span.kind === 'ai_interpret' && row && result?.interpretation?.origin) row.origins.push(result.interpretation.origin)
    if (span.kind === 'ai_explanation' && row) row.origins.push(`EXPLANATION_${result?.explanation?.source ?? 'UNKNOWN'}`)
    if (span.kind === 'solver' && row && typeof result?.id === 'string') {
      row.plan_ids.push(result.id); row.base_revisions.push(result.base_state_revision)
    }
    const confirm = event.method === 'POST' && /\/confirm$/.test(event.path)
    const hold = event.method === 'POST' && /\/hold$/.test(event.path)
    if ((confirm || hold) && row) {
      if (row !== this.current) { this.invalidate('OUT_OF_ORDER_DECISION'); return }
      if (this.spans.some(s => s.request_id === row.request_id && s.kind.startsWith('ai_') && s.end_ms === null))
        this.invalidate('DECISION_WITH_PENDING_AI')
      row.end_ms = span.end_ms; row.outcome = confirm ? 'CONFIRMED' : 'HELD'
      row.confirmed_revision = confirm ? result?.new_state_revision ?? null : null
      const next = this.current
      if (next) next.active_ms = span.end_ms
      else { this.end = span.end_ms; this.status = 'COMPLETED' }
    }
    if (event.method === 'GET' && event.path === `/request-queues/${this.queue_id}` && result?.items) {
      for (const item of result.items) {
        const saved = this.entries.find(r => r.request_id === item.request.id)
        for (const p of item.request.plans ?? []) {
          if (saved && !saved.plan_ids.includes(p.id)) {
            saved.plan_ids.push(p.id); this.invalidate('RESTORED_UNOBSERVED_PLAN')
          }
        }
      }
      if (result.items.some((item: any) => ['CONFIRMED', 'HELD', 'CANCELLED'].includes(item.state)
        && this.entries.find(r => r.request_id === item.request.id)?.outcome === 'PENDING')) this.abort('EXTERNAL_DECISION_OR_LOST_RESPONSE')
    }
  }
  report() {
    const end = this.end ?? (this.start === null ? 0 : this.now() - this.start)
    const total = partition(0, end, this.spans)
    // Receipt/queue initialization is not human review; allocate unobserved setup to other.
    const setupEnd = this.entries[0]?.active_ms ?? end
    const setup = partition(0, setupEnd, this.spans)
    total.other_ms += setup.human_estimate_ms; total.human_estimate_ms -= setup.human_estimate_ms
    return {
      schema_version: this.schema_version, run_id: this.run_id, armed_at: this.armed_at, started_at: this.started_at,
      ended_at: this.end === null || this.started_at === null ? null : new Date(Date.parse(this.started_at) + this.end).toISOString(),
      status: this.status, queue_id: this.queue_id, context: this.context, operator: this.operator,
      seed_sha256: this.seed_sha256 || null, evidence: this.evidence,
      timing_valid: this.status === 'COMPLETED' && !this.issues.length,
      all_confirmed: this.entries.length === 3 && this.entries.every(r => r.outcome === 'CONFIRMED'),
      issues: [...this.issues], totals: total, setup_ms: setupEnd,
      entries: this.entries.map(r => ({ ...r, queue_wait_ms: r.active_ms === null ? null : r.active_ms,
        metrics: r.active_ms === null ? null : partition(r.active_ms, r.end_ms ?? end, this.spans) })),
      spans: this.spans.map(s => ({ ...s, end_ms: Math.min(s.end_ms ?? end, end), completed: s.end_ms !== null && s.end_ms <= end })),
      notes: 'Browser wall time; AI/solver include HTTP overhead and cache. Human estimate includes idle time. No independent quality verdict.',
    }
  }
}

export function timingCsv(report: ReturnType<QueueTiming['report']>) {
  const columns = ['run_id', 'queue_id', 'request_id', 'position', 'outcome', 'timing_valid', 'evidence', 'queue_wait_ms',
    'ai_interpret_ms', 'ai_explanation_ms', 'solver_ms', 'human_estimate_ms', 'other_ms', 'total_ms',
    'base_revisions', 'confirmed_revision', 'error_codes', 'build_sha', 'dataset_version', 'clock_anchor',
    'engine_mode', 'seed_sha256', 'operator', 'issues']
  const quote = (value: unknown) => {
    const raw = value === null || value === undefined ? '' : String(value)
    // Spreadsheet formula injection protection, including operator-controlled IDs.
    return '"' + (/^[=+\-@\t\r]/.test(raw) ? "'" + raw : raw).replace(/"/g, '""') + '"'
  }
  const rows = report.entries.map(row => ({ ...row, ...row.metrics, run_id: report.run_id, queue_id: report.queue_id,
    timing_valid: report.timing_valid, evidence: report.evidence, base_revisions: row.base_revisions.join(';'),
    error_codes: report.spans.filter(s => s.request_id === row.request_id && s.error_code).map(s => s.error_code).join(';') }))
  const total = { ...report.totals, run_id: report.run_id, queue_id: report.queue_id, request_id: 'TOTAL',
    outcome: report.status, timing_valid: report.timing_valid, evidence: report.evidence }
  const metadata = { ...report.context, seed_sha256: report.seed_sha256, operator: report.operator, issues: report.issues.join(';') }
  return '\uFEFF' + [columns, ...[...rows, total].map(row => columns.map(key => ({ ...row, ...metadata } as Record<string, unknown>)[key]))]
    .map(row => row.map(quote).join(',')).join('\r\n')
}
