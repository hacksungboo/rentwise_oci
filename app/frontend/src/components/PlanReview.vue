<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, ApiError, type PlanView, type PlanExplanationResult } from '../api'
import { KIND_LABEL, REASON_LABEL, time } from '../format'

const props = defineProps<{ plan: PlanView; cancelLabel?: string }>()
const emit = defineEmits<{
  (e: 'confirmed', r: { confirmed_plan_id: string; new_state_revision: number }): void
  (e: 'held'): void
  (e: 'cancel'): void
}>()

const busy = ref<'' | 'confirm' | 'hold'>('')
const error = ref<{ message: string; code: string } | null>(null)

const explaining = ref(false)
const explanation = ref<PlanExplanationResult | null>(null)
const explanationError = ref('')
let explanationRequest = 0
const explanationKey = computed(() => [props.plan.id, props.plan.revision, props.plan.base_state_revision,
  props.plan.current_state_revision, props.plan.input_hash, props.plan.status].join(':'))
watch(explanationKey, () => {
  explanationRequest++
  explaining.value = false
  explanation.value = null
  explanationError.value = ''
})
async function explain() {
  if (explaining.value || explanation.value || !readyToConfirm.value || busy.value) return
  const key = explanationKey.value
  const request = ++explanationRequest
  const plan = props.plan
  explaining.value = true
  explanationError.value = ''
  try {
    const result = await api.explainPlan(plan)
    if (request !== explanationRequest || key !== explanationKey.value) return
    const e = result.explanation
    if (e.plan_id !== plan.id || e.plan_revision !== plan.revision || e.base_state_revision !== plan.base_state_revision || e.input_hash !== plan.input_hash) {
      explanationError.value = '최신 변경안의 설명을 다시 불러와 주세요.'
      return
    }
    explanation.value = result
  } catch (e) {
    if (request === explanationRequest && key === explanationKey.value)
      explanationError.value = e instanceof ApiError ? e.message : '설명을 불러오지 못했습니다. 아래 변경 내역을 확인해 주세요.'
  } finally {
    if (request === explanationRequest) explaining.value = false
  }
}

const changed = computed(() => props.plan.diff.filter((d) => d.changed))
const readyToConfirm = computed(() => props.plan.status === 'READY')
const statusBadge = computed(() => {
  switch (props.plan.status) {
    case 'READY': return { cls: 'ok', text: '실행 가능' }
    case 'STALE': return { cls: 'warn', text: '기준 상태가 바뀜' }
    case 'UNRESOLVED': return { cls: 'warn', text: '해결 안 됨' }
    case 'HELD': return { cls: '', text: '보류됨' }
    default: return { cls: '', text: props.plan.status }
  }
})
const label = (id: string) => {
  const d = props.plan.diff.find((x) => x.job_id === id)
  return d ? `${KIND_LABEL[d.kind] ?? d.kind}${d.site_name && d.kind !== 'PREP' ? ` · ${d.site_name}` : ''}` : id
}

function sameAssets(a: string[] = [], b: string[] = []) {
  return a.join() === b.join()
}

async function confirm() {
  busy.value = 'confirm'
  error.value = null
  try {
    emit('confirmed', await api.confirm(props.plan.id, props.plan.revision, props.plan.base_state_revision))
  } catch (e) {
    error.value = e instanceof ApiError ? { message: e.message, code: e.code } : { message: '서버에 연결하지 못했습니다.', code: 'NETWORK' }
  } finally {
    busy.value = ''
  }
}
async function hold() {
  busy.value = 'hold'
  try {
    await api.hold(props.plan.id, props.plan.revision, '책임자 보류')
    emit('held')
  } catch (e) {
    error.value = e instanceof ApiError ? { message: e.message, code: e.code } : { message: '서버에 연결하지 못했습니다.', code: 'NETWORK' }
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <section class="panel" aria-label="변경안 검토">
    <header class="row">
      <div>
        <h2>변경안 검토</h2>
        <p>바뀌는 작업 {{ changed.length }}건 · 확정 전까지 현재 계획은 그대로입니다.</p>
      </div>
      <span class="badge" :class="statusBadge.cls">{{ statusBadge.text }}</span>
    </header>

    <div v-if="plan.is_mock" class="banner info">
      고정 규칙 계산기(AI 엔진 연동 전)로 만든 변경안입니다.
    </div>

    <section class="explanation" aria-label="변경안 설명" :aria-busy="explaining">
      <div class="explanation-head">
        <div>
          <h3>{{ explanation?.explanation.source === 'SYSTEM' ? '계산 결과 요약' : 'AI 변경 설명' }}</h3>
          <p v-if="!explanation">변경 이유와 유지되는 약속을 한눈에 확인하세요.</p>
        </div>
        <button v-if="!explanation" class="btn explain-btn" :disabled="explaining || !readyToConfirm || !!busy" @click="explain">
          {{ explaining ? '설명 정리 중…' : 'AI 설명 보기' }}
        </button>
      </div>
      <div aria-live="polite">
        <template v-if="explanation">
          <p v-if="explanation.status === 'FALLBACK'" class="explanation-note">AI 설명을 불러오지 못해 계산 결과 요약을 표시합니다.</p>
          <p v-for="(paragraph, i) in explanation.explanation.paragraphs" :key="'p' + i">{{ paragraph }}</p>
          <div v-if="explanation.explanation.preserved.length" class="preserved">
            <strong>유지되는 약속</strong>
            <ul><li v-for="(item, i) in explanation.explanation.preserved" :key="i">{{ item }}</li></ul>
          </div>
          <p class="explanation-note">{{ explanation.explanation.notice }}</p>
        </template>
        <p v-if="explanationError" class="explanation-note">{{ explanationError }}</p>
      </div>
    </section>

    <ol v-if="plan.result.impact_edges?.length" class="chain">
      <li v-for="(e, i) in plan.result.impact_edges" :key="i">
        <span class="from">{{ label(e.from_job_id) }}</span>
        <span class="why">{{ REASON_LABEL[e.reason] ?? e.reason }}</span>
        <span class="to">{{ label(e.to_job_id) }}</span>
      </li>
    </ol>

    <ul class="changes">
      <li v-for="d in changed" :key="d.job_id">
        <div class="title">
          <span class="kind-dot" :class="'k-' + d.kind" />
          <strong>{{ KIND_LABEL[d.kind] }}</strong>
          <span>{{ d.kind === 'PREP' ? '창고' : d.site_name }}</span>
          <small>{{ d.job_id }}</small>
        </div>
        <div class="cmp num">
          <div class="before">
            <span>{{ d.before?.employee_name ?? (d.kind === 'PREP' ? '창고' : '—') }}</span>
            <span>{{ time(d.before?.service_start_at) }}</span>
            <span class="asset-tag muted" v-for="a in d.before?.asset_ids ?? []" :key="a">{{ a }}</span>
          </div>
          <span class="arrow" aria-label="에서">›</span>
          <div class="after">
            <span :class="{ diff: d.before?.employee_id !== d.after?.employee_id }">{{ d.after?.employee_name ?? (d.kind === 'PREP' ? '창고' : '—') }}</span>
            <span :class="{ diff: d.before?.service_start_at !== d.after?.service_start_at }">{{ time(d.after?.service_start_at) }}</span>
            <span class="asset-tag" :class="{ hot: !sameAssets(d.before?.asset_ids, d.after?.asset_ids) }" v-for="a in d.after?.asset_ids ?? []" :key="a">{{ a }}</span>
          </div>
        </div>
        <p v-if="d.reason_codes.length" class="reasons">{{ d.reason_codes.map((r) => REASON_LABEL[r] ?? r).join(', ') }}</p>
      </li>
    </ul>

    <div v-for="(u, i) in plan.result.unresolved ?? []" :key="'u' + i" class="banner error">
      {{ REASON_LABEL[u.code] ?? u.code }}
      <small v-if="u.details?.message">{{ u.details.message }}</small>
    </div>
    <div v-for="(v, i) in plan.result.violations ?? []" :key="'v' + i" class="banner error">
      {{ REASON_LABEL[v.code] ?? v.code }} <small>{{ v.job_ids.join(', ') }}</small>
    </div>
    <div v-if="plan.status === 'STALE'" class="banner error">
      다른 변경이 먼저 확정되었습니다. 요청을 다시 계산해 주세요.
    </div>
    <div v-if="error" class="banner error">{{ error.message }} <small>{{ error.code }}</small></div>

    <div class="actions">
      <button class="btn ghost" :disabled="!!busy" @click="emit('cancel')">{{ cancelLabel ?? '다시 입력' }}</button>
      <button class="btn" :disabled="!!busy || plan.status === 'HELD'" @click="hold">보류</button>
      <button class="btn confirm" :disabled="!readyToConfirm || !!busy" @click="confirm">
        {{ busy === 'confirm' ? '확정 중…' : '이 변경안으로 확정' }}
      </button>
    </div>

    <details class="tech">
      <summary>계산 근거</summary>
      <dl class="num">
        <dt>변경안</dt><dd>{{ plan.id }} (기준 계획 {{ plan.base_plan_id }})</dd>
        <dt>기준 상태 버전</dt><dd>r{{ plan.base_state_revision }} / 현재 r{{ plan.current_state_revision }}</dd>
        <dt>계산 엔진</dt><dd>{{ plan.engine_mode }} · {{ plan.solver_status }}</dd>
        <dt>입력 해시</dt><dd class="hash">{{ plan.input_hash }}</dd>
        <dt>예약 변경</dt><dd>{{ plan.result.reservation_changes?.length ?? 0 }}건</dd>
      </dl>
    </details>
  </section>
</template>

<style scoped>
.explanation { background: color-mix(in srgb, var(--ok, #158558) 5%, var(--surface)); border: 1px solid var(--line); border-radius: var(--radius-s); padding: 12px; display: grid; gap: 10px; }
.explanation-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; }
.explanation h3 { font-size: 14px; margin: 0; }
.explanation p { font-size: 13.5px; line-height: 1.65; margin: 5px 0; overflow-wrap: anywhere; }
.explanation .explanation-note { font-size: 12px; color: var(--ink-3); }
.explain-btn { min-height: 36px; font-size: 13px; white-space: nowrap; }
.preserved { margin-top: 10px; font-size: 13px; line-height: 1.65; }
.preserved ul { margin: 4px 0 0; padding-left: 18px; }

.panel { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 18px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-content: start; min-width: 0; }
header p { color: var(--ink-3); font-size: 13.5px; margin-top: 2px; }
header.row .badge { flex-shrink: 0; white-space: nowrap; }
header.row { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
.chain { margin: 0; padding: 0; list-style: none; display: grid; gap: 0; counter-reset: c; }
.chain li { position: relative; padding: 0 0 12px 22px; display: grid; gap: 1px; font-size: 13.5px; }
.chain li::before { content: ''; position: absolute; left: 5px; top: 6px; width: 8px; height: 8px; border-radius: 50%; background: var(--ink); }
.chain li:not(:last-child)::after { content: ''; position: absolute; left: 8.5px; top: 16px; bottom: 0; width: 1px; background: var(--line); }
.chain .from { font-weight: 600; }
.chain .why { color: var(--ink-2); }
.chain .to { color: var(--ink); }
.changes { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.changes li { border: 1px solid var(--line); border-radius: var(--radius-s); padding: 10px 12px; display: grid; gap: 8px; }
.title { display: flex; gap: 7px; align-items: center; font-size: 14px; }
.title small { margin-left: auto; color: var(--ink-3); font-size: 12px; }
.cmp { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 8px; align-items: center; font-size: 13.5px; }
.cmp > div { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.before { color: var(--ink-3); }
.arrow { font-size: 20px; color: var(--ink-3); }
.after .diff { font-weight: 700; background: color-mix(in srgb, var(--tag) 35%, white); padding: 0 4px; border-radius: 3px; }
.reasons { font-size: 12.5px; color: var(--ink-2); }
.actions { display: flex; gap: 8px; }
.actions .confirm { flex: 1; height: 42px; }
.tech { font-size: 13px; color: var(--ink-2); }
.tech summary { cursor: pointer; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0 0; }
dt { color: var(--ink-3); }
dd { margin: 0; }
.hash { word-break: break-all; font-size: 12px; }
</style>
