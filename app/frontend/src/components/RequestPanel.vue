<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, ApiError, type Intent, type PlanView, type Reference, type RequestView } from '../api'
import { CONFIRM_FIELD_LABEL, KIND_LABEL, fromLocalInput, time, toLocalInput } from '../format'

const props = defineProps<{ reference: Reference; stateRevision: number }>()
const emit = defineEmits<{ (e: 'plan', p: PlanView): void }>()

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
const error = ref<{ message: string; code: string } | null>(null)

const locName = computed(() => Object.fromEntries(props.reference.locations.map((l) => [l.id, l.name])))
const custName = computed(() => Object.fromEntries(props.reference.customers.map((c) => [c.id, c.name])))
const custLoc = computed(() => Object.fromEntries(props.reference.customers.map((c) => [c.id, c.location_id])))
const origin = computed(() => req.value?.interpretation?.origin)

function fail(e: unknown) {
  error.value = e instanceof ApiError ? { message: e.message, code: e.code } : { message: '서버에 연결하지 못했습니다.', code: 'NETWORK' }
}

function useSample(s: (typeof SAMPLES)[number]) {
  customer.value = s.customer
  text.value = s.text
}

async function interpret() {
  busy.value = 'interpret'
  error.value = null
  try {
    const created = await api.createRequest(customer.value, text.value)
    const r = await api.interpret(created.id, created.revision)
    req.value = r
    draft.value = JSON.parse(JSON.stringify(r.interpretation!.payload))
    acked.value = new Set()
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
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

type TimeField = 'window_start' | 'window_end' | 'due_at'
function setTime(i: number, f: TimeField, v: string) {
  draft.value!.operations[i][f] = fromLocalInput(v)
}

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
const ready = computed(() => confirmations.value.every((c) => acked.value.has(c.path) && filled(c.path)))

async function plan() {
  if (!req.value || !draft.value) return
  busy.value = 'plan'
  error.value = null
  try {
    const saved = await api.saveInterpretation(req.value.id, req.value.revision, draft.value, [...acked.value])
    const p = await api.createPlan(saved.id, saved.interpretation!.revision, props.stateRevision)
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
        <h2>고객 요청 받기</h2>
        <p>카톡·문자로 받은 내용을 그대로 붙여넣으세요.</p>
      </header>
      <div class="samples">
        <span>예시</span>
        <button v-for="s in SAMPLES" :key="s.label" class="btn small" type="button" @click="useSample(s)">{{ s.label }}</button>
      </div>
      <label class="field">
        <span>보낸 거래처</span>
        <select v-model="customer">
          <option v-for="c in reference.customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </label>
      <label class="field">
        <span>요청 내용</span>
        <textarea v-model="text" maxlength="2000" placeholder="예: 오늘 프린터 회수를 오후 2시로 미뤄 주세요" />
      </label>
      <div v-if="error" class="banner error">{{ error.message }} <small>{{ error.code }}</small></div>
      <button class="btn primary wide" :disabled="!text.trim() || !!busy" @click="interpret">
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
          <label class="field">
            <span>방문 시작</span>
            <input type="datetime-local" :value="toLocalInput(op.window_start)" @input="setTime(i, 'window_start', ($event.target as HTMLInputElement).value)" />
            <em v-if="evidenceFor(i, 'window_start')">근거 “{{ evidenceFor(i, 'window_start') }}”</em>
          </label>
          <label class="field">
            <span>방문 종료</span>
            <input type="datetime-local" :value="toLocalInput(op.window_end)" @input="setTime(i, 'window_end', ($event.target as HTMLInputElement).value)" />
          </label>
          <label class="field">
            <span>완료 기한</span>
            <input type="datetime-local" :value="toLocalInput(op.due_at)" @input="setTime(i, 'due_at', ($event.target as HTMLInputElement).value)" />
          </label>
        </div>
      </div>

      <div v-if="confirmations.length" class="checks">
        <h3>확인이 필요한 항목</h3>
        <label v-for="c in confirmations" :key="c.path" class="check" :class="{ done: acked.has(c.path) && filled(c.path) }">
          <input type="checkbox" :checked="acked.has(c.path)" :disabled="!filled(c.path)" @change="toggle(c.path)" />
          <span>
            <b>{{ CONFIRM_FIELD_LABEL[fieldOf(c.path)] ?? fieldOf(c.path) }}</b>
            {{ c.question }}
            <small v-if="!filled(c.path)">위 칸을 먼저 채워 주세요.</small>
          </span>
        </label>
      </div>

      <div v-if="error" class="banner error">{{ error.message }} <small>{{ error.code }}</small></div>
      <div class="actions">
        <button class="btn ghost" @click="restart">다시 입력</button>
        <button class="btn primary" :disabled="!ready || !!busy" @click="plan">
          {{ busy === 'plan' ? '변경안 계산 중…' : '조건 확인하고 변경안 계산' }}
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 18px; display: grid; gap: 14px; align-content: start; }
header p { color: var(--ink-3); font-size: 13.5px; margin-top: 2px; }
header.row { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
.samples { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.samples > span { font-size: 13px; color: var(--ink-3); margin-right: 2px; }
.wide { width: 100%; height: 42px; }
.source { margin: 0; padding: 12px 14px; background: var(--bg); border-radius: var(--radius-s); border-left: 3px solid var(--ink); font-size: 14.5px; line-height: 1.7; }
mark { background: none; color: inherit; text-decoration: underline 3px var(--tag); text-underline-offset: 3px; font-weight: 600; }
.op { display: grid; gap: 10px; }
.op-head { display: flex; gap: 8px; align-items: center; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; }
.grid .full { grid-column: 1 / -1; }
.field em { font-style: normal; font-size: 12px; color: #6b5200; }
.checks { display: grid; gap: 8px; padding: 12px; border: 1px solid #f1d98a; background: #fffbea; border-radius: var(--radius-s); }
.check { display: grid; grid-template-columns: 20px 1fr; gap: 8px; font-size: 13.5px; align-items: start; }
.check input { margin-top: 3px; }
.check b { font-weight: 600; margin-right: 4px; }
.check small { display: block; color: var(--ink-3); }
.check.done { color: var(--ink-3); }
.actions { display: flex; justify-content: space-between; gap: 8px; }
.actions .primary { flex: 1; height: 42px; }
@media (max-width: 520px) { .grid { grid-template-columns: 1fr; } }
</style>
