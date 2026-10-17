// 백엔드 /api/v1 호출. 오류는 {error:{code,message,details,retryable}, trace_id} 형식.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
    public traceId?: string,
  ) {
    super(message)
  }
}

async function call<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const e = data?.error
    throw new ApiError(res.status, e?.code ?? 'HTTP_' + res.status, e?.message ?? '요청을 처리하지 못했습니다.', e?.details ?? {}, data?.trace_id)
  }
  return data as T
}

const key = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())
export const requestKey = key

export const api = {
  login: (username: string, password: string) => call<{ user: User }>('POST', '/sessions', { username, password }),
  me: () => call<{ user: User }>('GET', '/sessions/current'),
  logout: () => call('DELETE', '/sessions/current'),
  version: () => call<VersionInfo>('GET', '/version'),
  system: () => call<SystemInfo>('GET', '/system'),
  aiUsage: () => call<AiUsage>('GET', '/admin/ai'),
  operations: (date?: string) => call<Ops>('GET', '/operations' + (date ? `?date=${date}` : '')),
  reference: () => call<Reference>('GET', '/reference'),
  createRequest: (source_customer_id: string, text: string) =>
    call<RequestView>('POST', '/requests', { source_customer_id, text }, { 'Idempotency-Key': key() }),
  createQueue: (items: QueueInput[], idem: string) =>
    call<RequestQueue>('POST', '/request-queues', { items }, { 'Idempotency-Key': idem }),
  latestQueue: () => call<{ queue: RequestQueue | null }>('GET', '/request-queues/latest'),
  queue: (id: string) => call<RequestQueue>('GET', `/request-queues/${id}`),
  queuedInterpret: (queueId: string, id: string, rev: number) =>
    call<RequestView>('POST', `/request-queues/${queueId}/interpret`, { request_id: id, expected_request_revision: rev }),
  queuedPlan: (queueId: string, request_id: string, interpretation_revision: number) =>
    call<PlanView>('POST', `/request-queues/${queueId}/plan`, { request_id, interpretation_revision }),
  queuedHold: (queueId: string, request_id: string, reason: string) =>
    call<RequestQueue>('POST', `/request-queues/${queueId}/hold`, { request_id, reason }),
  plan: (id: string) => call<PlanView>('GET', `/plans/${id}`),
  interpret: (id: string, rev: number) => call<RequestView>('POST', `/requests/${id}/interpret`, { expected_request_revision: rev }),
  saveInterpretation: (id: string, rev: number, payload: Intent, acknowledged_paths: string[]) =>
    call<RequestView>('PUT', `/requests/${id}/interpretation`, { expected_request_revision: rev, payload, acknowledged_paths }),
  createPlan: (request_id: string, interpretation_revision: number, base_state_revision: number) =>
    call<PlanView>('POST', '/plans', { request_id, interpretation_revision, base_state_revision }),
  explainPlan: (p: PlanView) => call<PlanExplanationResult>('POST', `/plans/${p.id}/explanation`,
    { expected_plan_revision: p.revision, base_state_revision: p.base_state_revision, input_hash: p.input_hash }),
  confirm: (planId: string, expected_plan_revision: number, base_state_revision: number) =>
    call<{ confirmed_plan_id: string; new_state_revision: number }>('POST', `/plans/${planId}/confirm`,
      { expected_plan_revision, base_state_revision }, { 'Idempotency-Key': key() }),
  hold: (planId: string, expected_plan_revision: number, reason: string) =>
    call('POST', `/plans/${planId}/hold`, { expected_plan_revision, reason }),
  reset: () => call<{ ok: boolean }>('POST', '/admin/reset'),
}

// ------------------------------------------------------------------ 타입 (백엔드 계약과 같은 필드명)
export interface User { username: string; role: 'ADMIN' | 'STAFF'; name: string; employee_id: string | null }
export interface VersionInfo {
  build_sha: string; image_tag: string; engine_mode: string; db: string | null; db_banner: string | null; server: string
  cloud?: { provider: string; region: string | null; display_name: string | null }
}
export interface SystemInfo {
  cloud: { provider: string; region: string | null; availability_domain?: string | null; fault_domain?: string | null
    display_name: string | null; instance_id?: string | null; shape?: string | null; ocpus?: number | null
    memory_gb?: number | null; private_ip?: string | null; uptime_s: number }
  db: { dialect?: string; banner?: string; pdb?: string; server_host?: string }
  build: { sha: string; image_tag: string; engine_mode: string; server_label: string }
}
export interface AiUsage {
  engine_mode: string; model_id: string; limit_usd: number; settled_usd: number; committed_usd: number
  calls: { ok: number; error: number }
  recent: { at: string; request_id: string | null; status: string; error_code: string | null; attempts: number | null
    input_tokens: number | null; output_tokens: number | null; latency_ms: number | null; provider_call_id: string | null }[]
}
export interface Segment { kind: 'TRAVEL' | 'SERVICE' | 'PREP'; from_id: string; to_id: string; start_at: string; end_at: string }
export interface Card {
  job_id: string; kind: string; asset_ids: string[]; start_at: string; end_at: string; segments: Segment[]
  site_id: string | null; site_name: string | null; customer_id?: string | null
  window_start?: string | null; window_end?: string | null; due_at?: string | null; reason_codes: string[]
}
export interface Ghost { job_id: string; lane: string; start_at: string; end_at: string; kind: string }
export interface Lane { id: string; name: string; shift: [string, string] | null; breaks: { start_at: string; end_at: string }[]; items: Card[] }
export interface Asset { id: string; item_id: string; physical_state: string; location_id: string | null }
export interface Item { id: string; category: string; model_name: string; service_minutes_by_kind?: Record<string, number>; prep_minutes?: number }
export interface AvailWindow { item_id: string; ready_asset_ids: string[]; conditional_assets: { asset_id: string; expected_ready_at: string | null }[]; unavailable_asset_ids: string[] }
export interface Ops {
  workspace: { state_revision: number; current_plan_id: string; dataset_version: string; clock_anchor: string; engine_mode: string }
  date: string; physical_totals: Record<string, number>; total_assets: number
  availability: { windows: AvailWindow[] }; items: Item[]; assets: Asset[]
  employees: Lane[]; prep_items: Card[]
  locations: { id: string; name: string; kind: string; holdings: string[] }[]
}
export interface Reference {
  customers: { id: string; name: string; location_id: string; preferred_employee_id: string | null }[]
  items: Item[]; assets: Asset[]; employees: { id: string; name: string }[]
  locations: { id: string; name: string }[]
  jobs: { id: string; kind: string; from_id: string; to_id: string; asset_ids: string[]; window_start: string | null; due_at: string | null }[]
}
export interface Operation {
  operation: 'CREATE' | 'RESCHEDULE'; kind: 'DELIVERY' | 'PICKUP' | 'AS' | 'TRANSFER'
  target_job_id: string | null; item_id: string | null; asset_ids: string[]; quantity: number | null
  source_customer_id: string | null; destination_customer_id: string | null
  window_start: string | null; window_end: string | null; due_at: string | null; rental_end_at: string | null
  priority_hint: 'NORMAL' | 'URGENT' | 'UNKNOWN'; evidence: { path: string; quote: string }[]
}
export interface Intent {
  schema_version: 'rental.intent.v1'; operations: Operation[]
  needs_confirmation: { path: string; reason: string; question: string }[]
}
export interface RequestView {
  id: string; revision: number; status: string; text: string; source_customer_id: string | null; received_at: string
  interpretation: null | { revision: number; origin: 'AI' | 'MOCK' | 'HUMAN'; payload: Intent; acknowledged_paths: string[] }
  pending_confirmations?: string[]
  plans?: { id: string; status: string }[]
}
export interface QueueInput { source_customer_id: string | null; text: string }
export interface RequestQueue {
  id: string; status: 'ACTIVE' | 'DONE'; created_at: string; current_request_id: string | null; state_revision: number
  items: { position: number; state: string; request: RequestView; hold_reason: string | null }[]
}
export interface DiffSide { employee_id: string | null; employee_name: string | null; asset_ids: string[]; start_at: string; end_at: string; service_start_at: string | null; segments: Segment[] }
export interface DiffRow { job_id: string; kind: string; site_id: string | null; site_name: string | null; changed: boolean; before: DiffSide | null; after: DiffSide | null; reason_codes: string[] }
export interface PlanView {
  id: string; revision: number; status: string; solver_status: string; engine_mode: string; is_mock: boolean
  base_plan_id: string; base_state_revision: number; current_state_revision: number; input_hash: string
  diff: DiffRow[]
  preview_employees?: { id: string; name: string }[]
  fallbacks?: { kind: 'QUICK' | 'PICKUP_NEXT_WORKDAY'; job_id: string; notice: string; status?: string
    old_window_start?: string; old_due_at?: string; window_start?: string; window_end?: string; due_at?: string }[]
  result: {
    impact_edges: { from_job_id: string; to_job_id: string; reason: string; old_time: string | null; new_time: string | null }[]
    violations: { code: string; job_ids: string[] }[]; unresolved: { job_id: string | null; code: string; details: Record<string, unknown> }[]
    reservation_changes: { action: string; old_id: string | null }[]; inherited_paths: string[]
  }
}


export interface PlanExplanation {
  plan_id: string; plan_revision: number; base_state_revision: number; input_hash: string; evidence_hash: string
  source: 'AI' | 'SYSTEM'; paragraphs: string[]; preserved: string[]; notice: string
}
export interface PlanExplanationResult {
  status: 'OK' | 'FALLBACK'; explanation: PlanExplanation; error_code: string | null
}
