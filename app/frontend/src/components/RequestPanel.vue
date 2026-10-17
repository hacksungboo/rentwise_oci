<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, requestError, type RequestError, type Intent, type PlanView, type Reference, type RequestView } from '../api'
import { CONFIRM_FIELD_LABEL, KIND_LABEL, addDays, fromLocalInput, time, toLocalInput } from '../format'
import TimeField from './TimeField.vue'

const props = defineProps<{ reference: Reference; stateRevision: number; existingRequest?: RequestView; queueId?: string; interpretationError?: RequestError & { requestId: string } }>()
const emit = defineEmits<{
  (e: 'plan', p: PlanView): void
  (e: 'busy', value: boolean): void
  (e: 'updated', value: RequestView): void
}>()

const SAMPLES = [
  { label: '회수 일정 변경', customer: 'C-H', text: '안녕하세요 한빛상사입니다. 오늘 프린터 회수를 오후 2시로 미뤄 주실 수 있을까요?' },
  { label: '추가 납품', customer: 'C-B', text: '바른법무사무소입니다. 내일 오전에 노트북 1대 추가로 납품 부탁드립니다.' },
]

const customer = ref('C-H')
const text = ref('')
const req = ref<RequestView | null>(null)
const draft = ref<Intent | null>(null)
const acked = ref<Set<string>>(new Set())
const busy = ref<'' | 'interpret' | 'plan'>('')
watch(busy, (value) => emit('busy', !!value))
const error = ref<{ message: string; code: string } | null>(null)

const locName = computed(() => Object.fromEntries(props.reference.locations.map((l) => [l.id, l.name])))
const custName = computed(() => Object.fromEntries(props.reference.customers.map((c) => [c.id, c.name])))
const custLoc = computed(() => Object.fromEntries(props.reference.customers.map((c) => [c.id, c.location_id])))
const origin = computed(() => req.value?.interpretation?.origin)

function fail(e: unknown) {
  error.value = requestError(e)
}

function useSample(s: (typeof SAMPLES)[number]) {
  customer.value = s.customer
  text.value = s.text
}

// AI 해석이 실패해도 시연·업무가 멈추지 않도록: 기존 작업을 골라 사람이 조건을 직접 입력
const unsaved = ref<RequestView | null>(null)
watch(() => props.existingRequest, (r) => {
  if (!r) return
  customer.value = r.source_customer_id ?? ''
  text.value = r.text
  req.value = r.interpretation ? r : null
  unsaved.value = r.interpretation ? null : r
  draft.value = r.interpretation ? JSON.parse(JSON.stringify(r.interpretation.payload)) : null
  acked.value = new Set(r.interpretation?.acknowledged_paths ?? [])
  const failure = props.interpretationError
  error.value = failure?.requestId === r.id && !r.interpretation ? failure : null
}, { immediate: true })
watch(() => props.interpretationError, (failure) => {
  if (failure && failure.requestId === props.existingRequest?.id && !props.existingRequest?.interpretation)
    error.value = failure
}, { immediate: true })
const manualJob = ref('')
const manualJobs = computed(() => {
  const loc = custLoc.value[customer.value]
  return props.reference.jobs.filter((j) => j.kind !== 'PREP' && (j.from_id === loc || j.to_id === loc))
})
const unsupportedReview = computed(() => !!props.queueId && error.value?.code === 'AI_REVIEW_UNSUPPORTED')
const canManual = computed(() => !!unsaved.value && !!error.value && error.value.code !== 'NETWORK')

async function interpret() {
  busy.value = 'interpret'
  error.value = null
  try {
    const created = unsaved.value && unsaved.value.text === text.value && unsaved.value.source_customer_id === customer.value
      ? unsaved.value : await api.createRequest(customer.value, text.value)
    unsaved.value = created
    const r = props.queueId ? await api.queuedInterpret(props.queueId, created.id, created.revision)
      : await api.interpret(created.id, created.revision)
    req.value = r
    emit('updated', r)
    unsaved.value = null
    draft.value = JSON.parse(JSON.stringify(r.interpretation!.payload))
    acked.value = new Set()
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
}

function startManual() {
  const job = props.reference.jobs.find((j) => j.id === manualJob.value)
  if (!job || !unsaved.value) return
  const ask = (f: string, q: string) => ({ path: `operations.0.${f}`, reason: 'MISSING', question: q })
  draft.value = {
    schema_version: 'rental.intent.v1',
    operations: [{
      operation: 'RESCHEDULE', kind: job.kind as 'DELIVERY' | 'PICKUP' | 'AS' | 'TRANSFER', target_job_id: job.id,
      item_id: null, asset_ids: [], quantity: null, source_customer_id: customer.value, destination_customer_id: null,
      window_start: null, window_end: null, due_at: null, rental_end_at: null, priority_hint: 'UNKNOWN', evidence: [],
    }],
    needs_confirmation: [ask('window_start', '바뀐 방문 시작 시각을 입력하세요.'),
      ask('window_end', '방문 종료 시각을 입력하세요.'), ask('due_at', '완료 기한을 입력하세요.')],
  }
  req.value = unsaved.value
  unsaved.value = null
  acked.value = new Set()
  error.value = null
}

function restart() {
  req.value = null
  draft.value = null
  error.value = null
}

// 원문 하이라이트: 근거 인용 구절
const highlighted = computed(() => {
  const src = req.value?.text ?? ''
  const quotes = (draft.value?.operations ?? []).flatMap((o) => o.evidence.map((e) => e.quote)).filter(Boolean)
  const marks: [number, number][] = []
  for (const q of quotes) {
    const i = src.indexOf(q)
    if (i >= 0 && !marks.some(([a, b]) => i < b && i + q.length > a)) marks.push([i, i + q.length])
  }
  marks.sort((a, b) => a[0] - b[0])
  const out: { t: string; m: boolean }[] = []
  let cur = 0
  for (const [a, b] of marks) {
    if (a > cur) out.push({ t: src.slice(cur, a), m: false })
    out.push({ t: src.slice(a, b), m: true })
    cur = b
  }
  if (cur < src.length) out.push({ t: src.slice(cur), m: false })
  return out
})

function jobsFor(opIndex: number) {
  const op = draft.value!.operations[opIndex]
  const loc = custLoc.value[op.source_customer_id ?? customer.value]
  return props.reference.jobs.filter((j) => j.kind === op.kind && (j.from_id === loc || j.to_id === loc))
}
function jobLabel(j: Reference['jobs'][number]) {
  const site = j.kind === 'DELIVERY' ? j.to_id : j.from_id
  return `${KIND_LABEL[j.kind]} · ${locName.value[site]} · ${time(j.window_start)} (${j.id})`
}
function evidenceFor(opIndex: number, field: string) {
  return draft.value!.operations[opIndex].evidence.find((e) => e.path === field)?.quote
}

// 선택 가능한 날짜: 요청 수신일부터 7일 (배정 계획 범위)
const days = computed(() => {
  const start = toLocalInput(req.value?.received_at ?? null).slice(0, 10)
  return start ? Array.from({ length: 7 }, (_, n) => addDays(start, n)) : []
})

const confirmations = computed(() => draft.value?.needs_confirmation ?? [])
function fieldOf(path: string) {
  return path.split('.').pop() ?? path
}
function filled(path: string) {
  const [, idx, f] = path.split('.')
  const op = draft.value?.operations[Number(idx)] as unknown as Record<string, unknown> | undefined
  const v = op?.[f]
  return v !== null && v !== undefined && v !== ''
}
function toggle(path: string) {
  const s = new Set(acked.value)
  s.has(path) ? s.delete(path) : s.add(path)
  acked.value = s
}
// 확인 항목별 추천값 (사람이 눌러야만 채워짐)
function suggestion(path: string): { label: string; apply: () => void } | null {
  const [, idx, f] = path.split('.')
  const op = draft.value?.operations[Number(idx)]
  if (!op) return null
  if (f === 'window_end' && op.window_start) {
    const item = props.reference.items.find((it) => it.id === op.item_id)
    const mins = item?.service_minutes_by_kind?.[op.kind] ?? 10
    const v = new Date(new Date(op.window_start).getTime() + mins * 60_000).toISOString()
    return { label: `시작 + 현장 ${mins}분 (${time(v)})`, apply: () => (op.window_end = toKst(v)) }
  }
  if (f === 'due_at' && op.window_start) {
    const existing = props.reference.jobs.find((j) => j.id === op.target_job_id)
    if (op.kind === 'AS' && existing?.due_at) {
      const due = existing.due_at
      return { label: `기존 완료 기한 (${time(due)})`, apply: () => (op.due_at = due) }
    }
    const day = toLocalInput(op.window_start).slice(0, 10)
    return { label: '당일 17:00', apply: () => (op.due_at = `${day}T17:00:00+09:00`) }
  }
  return null
}
function toKst(isoUtc: string) {
  return fromLocalInput(toLocalInput(isoUtc))
}
function applySuggestion(path: string) {
  const s = suggestion(path)
  if (!s) return
  s.apply()
  const set = new Set(acked.value)
  set.add(path)
  acked.value = set
}

const ready = computed(() => confirmations.value.every((c) => acked.value.has(c.path) && filled(c.path)))

async function plan() {
  if (!req.value || !draft.value) return
  busy.value = 'plan'
  error.value = null
  try {
    const saved = await api.saveInterpretation(req.value.id, req.value.revision, draft.value, [...acked.value])
    emit('updated', saved)
    const p = props.queueId ? await api.queuedPlan(props.queueId, saved.id, saved.interpretation!.revision)
      : await api.createPlan(saved.id, saved.interpretation!.revision, props.stateRevision)
    req.value = saved
    emit('plan', p)
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <section class="panel" aria-label="고객 요청 처리">
    <!-- 1. 요청 입력 -->
    <template v-if="!req">
      <header>
        <h2>{{ queueId ? '이번 요청 처리' : '고객 요청 받기' }}</h2>
        <p>{{ queueId ? '해석 실패 시 재시도하거나 기존 작업을 골라 직접 입력할 수 있습니다.' : '카톡·문자로 받은 내용을 그대로 붙여넣으세요.' }}</p>
      </header>
      <div v-if="!queueId" class="samples">
        <span>예시</span>
        <button v-for="s in SAMPLES" :key="s.label" class="btn small" type="button" @click="useSample(s)">{{ s.label }}</button>
      </div>
      <label class="field">
        <span>보낸 거래처</span>
        <select v-model="customer" :disabled="!!queueId">
          <option v-if="queueId && !customer" value="">미지정</option>
          <option v-for="c in reference.customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </label>
      <label class="field">
        <span>요청 내용</span>
        <textarea v-model="text" :readonly="!!queueId" maxlength="2000" placeholder="예: 오늘 프린터 회수를 오후 2시로 미뤄 주세요" />
      </label>
      <div v-if="error" class="banner error">{{ error.message }} <small>{{ error.code }}</small></div>
      <p v-if="unsupportedReview" class="note">현재 화면에서 확인할 수 없는 조건입니다. 같은 원문을 재해석해도 해결되지 않습니다. 기존 업무 변경은 직접 입력할 수 있고, 신규 설치는 사유를 적어 보류한 뒤 별도로 검토해 주세요.</p>
      <div v-if="canManual || (queueId && unsaved)" class="manual">
        <span>기존 작업을 골라 직접 입력</span>
        <select v-model="manualJob">
          <option value="" disabled>작업 선택</option>
          <option v-for="j in manualJobs" :key="j.id" :value="j.id">{{ KIND_LABEL[j.kind] }} · {{ j.id }} · {{ time(j.window_start) }}</option>
        </select>
        <button class="btn small" type="button" :disabled="!manualJob" @click="startManual">직접 입력</button>
      </div>
      <button class="btn primary wide" :disabled="!text.trim() || !!busy || unsupportedReview" @click="interpret">
        {{ busy === 'interpret' ? '요청을 읽는 중…' : '요청 해석하기' }}
      </button>
    </template>

    <!-- 2. 해석 확인 -->
    <template v-else-if="draft">
      <header class="row">
        <div>
          <h2>조건 확인</h2>
          <p>{{ custName[req.source_customer_id ?? ''] }} · {{ time(req.received_at) }} 수신</p>
        </div>
        <span class="badge" :class="origin === 'AI' ? 'ai' : origin === 'MOCK' ? 'mock' : 'human'">
          {{ origin === 'AI' ? 'AI 해석' : origin === 'MOCK' ? '고정 응답 (AI 연동 전)' : '사람 확인본' }}
        </span>
      </header>

      <blockquote class="source">
        <template v-for="(s, i) in highlighted" :key="i"><mark v-if="s.m">{{ s.t }}</mark><template v-else>{{ s.t }}</template></template>
      </blockquote>

      <div v-for="(op, i) in draft.operations" :key="i" class="op">
        <div class="op-head">
          <span class="kind-dot" :class="'k-' + op.kind" />
          <strong>{{ op.operation === 'RESCHEDULE' ? '일정 변경' : '새 업무' }} · {{ KIND_LABEL[op.kind] }}</strong>
        </div>
        <div class="grid">
          <label class="field">
            <span>업무</span>
            <select v-model="op.kind">
              <option v-for="k in ['DELIVERY', 'PICKUP', 'AS', 'TRANSFER']" :key="k" :value="k">{{ KIND_LABEL[k] }}</option>
            </select>
            <em v-if="evidenceFor(i, 'kind')">근거 “{{ evidenceFor(i, 'kind') }}”</em>
          </label>
          <label class="field">
            <span>품목</span>
            <select v-model="op.item_id">
              <option :value="null">선택</option>
              <option v-for="it in reference.items" :key="it.id" :value="it.id">{{ it.model_name }}</option>
            </select>
            <em v-if="evidenceFor(i, 'item_id')">근거 “{{ evidenceFor(i, 'item_id') }}”</em>
          </label>
          <label v-if="op.operation === 'RESCHEDULE'" class="field full">
            <span>변경할 기존 작업</span>
            <select v-model="op.target_job_id">
              <option :value="null">선택</option>
              <option v-for="j in jobsFor(i)" :key="j.id" :value="j.id">{{ jobLabel(j) }}</option>
            </select>
          </label>
          <label v-else class="field">
            <span>수량</span>
            <input v-model.number="op.quantity" type="number" min="1" max="12" />
          </label>
          <div class="field">
            <TimeField v-model="op.window_start" :days="days" label="방문 시작" />
            <em v-if="evidenceFor(i, 'window_start')">근거 “{{ evidenceFor(i, 'window_start') }}”</em>
          </div>
          <div class="field">
            <TimeField v-model="op.window_end" :days="days" label="방문 종료" />
          </div>
          <div class="field">
            <TimeField v-model="op.due_at" :days="days" label="완료 기한" />
          </div>
        </div>
      </div>

      <div v-if="confirmations.length" class="checks">
        <h3>확인이 필요한 항목</h3>
        <label v-for="c in confirmations" :key="c.path" class="check" :class="{ done: acked.has(c.path) && filled(c.path) }">
          <input type="checkbox" :checked="acked.has(c.path)" :disabled="!filled(c.path)" @change="toggle(c.path)" />
          <span>
            <b>{{ CONFIRM_FIELD_LABEL[fieldOf(c.path)] ?? fieldOf(c.path) }}</b>
            {{ c.question }}
            <small v-if="!filled(c.path)">위 칸을 채우거나 추천값을 쓰세요.</small>
          </span>
          <button v-if="suggestion(c.path) && !filled(c.path)" type="button" class="btn small suggest"
                  @click.prevent="applySuggestion(c.path)">{{ suggestion(c.path)!.label }}</button>
        </label>
      </div>

      <div v-if="error" class="banner error">{{ error.message }} <small>{{ error.code }}</small></div>
      <div class="actions">
        <button v-if="!queueId" class="btn ghost" :disabled="!!busy" @click="restart">다시 입력</button>
        <button class="btn primary" :disabled="!ready || !!busy" @click="plan">
          {{ busy === 'plan' ? '변경안 계산 중…' : '조건 확인하고 변경안 계산' }}
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 18px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-content: start; min-width: 0; }
.panel :deep(input), .panel :deep(select), .panel :deep(textarea) { min-width: 0; max-width: 100%; }
header p { color: var(--ink-3); font-size: 13.5px; margin-top: 2px; }
header.row { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
.manual { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--ink-2); }
.manual select { min-width: 0; flex: 1 1 160px; }
.samples { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.samples > span { font-size: 13px; color: var(--ink-3); margin-right: 2px; }
.wide { width: 100%; height: 42px; }
.source { margin: 0; padding: 12px 14px; background: var(--bg); border-radius: var(--radius-s); border-left: 3px solid var(--ink); font-size: 14.5px; line-height: 1.7; }
mark { background: none; color: inherit; text-decoration: underline 3px var(--tag); text-underline-offset: 3px; font-weight: 600; }
.op { display: grid; gap: 10px; }
.op-head { display: flex; gap: 8px; align-items: center; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; }
.grid > * { min-width: 0; }
select { text-overflow: ellipsis; }
.grid .full { grid-column: 1 / -1; }
.field em { font-style: normal; font-size: 12px; color: #6b5200; }
.checks { display: grid; gap: 8px; padding: 12px; border: 1px solid #f1d98a; background: #fffbea; border-radius: var(--radius-s); }
.check { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 4px 8px; font-size: 13.5px; align-items: start; }
.check .suggest { grid-column: 2; justify-self: start; }
.check input { margin-top: 3px; }
.check b { font-weight: 600; margin-right: 4px; }
.check small { display: block; color: var(--ink-3); }
.check.done { color: var(--ink-3); }
.actions { display: flex; justify-content: space-between; gap: 8px; }
.actions .primary { flex: 1; min-width: 0; height: 42px; }
@media (max-width: 520px) { .grid { grid-template-columns: 1fr; } }
</style>
