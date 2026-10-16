<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, ApiError, requestKey, type PlanView, type QueueInput, type Reference, type RequestQueue, type RequestView } from '../api'
import PlanReview from './PlanReview.vue'
import RequestPanel from './RequestPanel.vue'

const props = defineProps<{ reference: Reference; stateRevision: number }>()
const emit = defineEmits<{
  (e: 'preview', value: PlanView | null): void
  (e: 'changed'): void
}>()
const queue = ref<RequestQueue | null>(null)
const plan = ref<PlanView | null>(null)
const rows = ref<QueueInput[]>(Array.from({ length: 3 }, () => ({ source_customer_id: '', text: '' })))
const busy = ref(false)
const childBusy = ref(false)
const loaded = ref(false)
const error = ref('')
const holdReason = ref('')
const composing = ref(false)
let alive = true
let submission: { fingerprint: string; key: string } | null = null
const current = computed(() => queue.value?.items.find((i) => i.request.id === queue.value?.current_request_id))
const customerName = (id: string | null) => props.reference.customers.find((c) => c.id === id)?.name ?? '거래처 미지정'
const stateLabel: Record<string, string> = { WAITING: '대기', RECEIVED: '해석 대기', INTERPRETING: '해석 중',
  NEEDS_REVIEW: '조건 확인', READY: '계산 대기', DRAFTED: '변경안 검토', CONFIRMED: '반영 완료', HELD: '보류', CANCELLED: '취소' }
const canSubmit = computed(() => rows.value.every((r) => r.text.trim() && r.source_customer_id))

function fail(e: unknown) {
  error.value = e instanceof ApiError ? `${e.message} (${e.code})` : '서버에 연결하지 못했습니다. 새로고침해 접수 여부를 확인해 주세요.'
}
function preview(p: PlanView | null) {
  childBusy.value = false
  plan.value = p
  if (p && current.value) current.value.state = 'DRAFTED'
  emit('preview', p)
}
function updated(request: RequestView) {
  if (!current.value || current.value.request.id !== request.id) return
  current.value.request = request
  current.value.state = request.status
}

async function refresh(autoInterpret = false, restorePlan = true) {
  busy.value = true
  childBusy.value = false
  error.value = ''
  try {
    const q = queue.value ? await api.queue(queue.value.id) : (await api.latestQueue()).queue
    if (!alive) return
    queue.value = q
    preview(null)
    const item = current.value
    if (q && item && autoInterpret && !item.request.interpretation && item.state !== 'INTERPRETING') {
      try {
        await api.queuedInterpret(q.id, item.request.id, item.request.revision)
      } catch (e) {
        if (alive) fail(e) // Stop here; never automatically retry or skip a failed request.
      }
      if (!alive) return
      queue.value = await api.queue(q.id)
    }
    const saved = current.value?.request.plans?.[0]
    if (restorePlan && saved && ['READY', 'UNRESOLVED'].includes(saved.status)) {
      const p = await api.plan(saved.id)
      if (alive) preview(p)
    }
  } catch (e) {
    if (alive) fail(e)
  } finally {
    if (alive) { busy.value = false; loaded.value = true }
  }
}

async function submit() {
  if (busy.value || !canSubmit.value) return
  const items = rows.value.map((r) => ({ ...r, text: r.text.trim() }))
  const fingerprint = JSON.stringify(items)
  if (submission?.fingerprint !== fingerprint) submission = { fingerprint, key: requestKey() }
  busy.value = true
  error.value = ''
  try {
    const result = await api.createQueue(items, submission!.key)
    if (!alive) return
    queue.value = result
    composing.value = false
    await refresh(true)
  } catch (e) {
    if (alive) fail(e)
  } finally {
    if (alive) busy.value = false
  }
}
async function afterDecision() {
  if (!alive) return
  preview(null)
  holdReason.value = ''
  emit('changed') // Reload board/reference from DB; next plan uses server-side current revision.
  await refresh(true)
}
async function hold() {
  if (!queue.value || !current.value || !holdReason.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await api.queuedHold(queue.value.id, current.value.request.id, holdReason.value)
    if (alive) await afterDecision()
  } catch (e) {
    if (alive) fail(e)
  } finally {
    if (alive) busy.value = false
  }
}
async function reviewAgain() {
  // Preserve the saved human interpretation; recomputation gets the latest revision.
  emit('changed')
  preview(null)
  await refresh(false, false)
}
function newQueue() {
  composing.value = true
  submission = null
  rows.value = Array.from({ length: 3 }, () => ({ source_customer_id: '', text: '' }))
  preview(null)
}
onMounted(() => refresh()) // Restore only: opening the page never incurs an AI charge.
onUnmounted(() => { alive = false })
</script>

<template>
  <div class="queue" aria-label="요청 대기열">
    <section class="queue-card">
      <header>
        <h2>요청 대기열</h2>
        <p>최대 3건을 함께 접수하고, 앞 요청을 확정·보류한 뒤 다음 요청을 처리합니다.</p>
      </header>
      <div v-if="!loaded" role="status">대기열을 불러오는 중…</div>
      <template v-else-if="!queue || composing">
        <div v-for="(row, i) in rows" :key="i" class="entry">
          <strong>요청 {{ i + 1 }}</strong>
          <label class="field"><span>보낸 거래처</span>
            <select v-model="row.source_customer_id" :disabled="busy">
              <option value="" disabled>거래처 선택</option>
              <option v-for="c in reference.customers" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
          <label class="field"><span>요청 내용</span>
            <textarea v-model="row.text" maxlength="2000" :disabled="busy" :aria-label="`요청 ${i + 1} 내용`" />
          </label>
        </div>
        <button class="btn primary" :disabled="!canSubmit || busy" @click="submit">{{ busy ? '접수·처리 중…' : '3건 함께 접수하고 순서대로 처리' }}</button>
        <button v-if="queue" class="btn ghost" :disabled="busy" @click="composing = false">이전 처리 내역</button>
      </template>
      <template v-else>
        <div class="queue-heading"><span>최신 일정 r{{ queue.state_revision }}</span>
          <button class="btn small" :disabled="busy || childBusy" @click="refresh()">대기열 새로고침</button>
        </div>
        <ol class="items">
          <li v-for="item in queue.items" :key="item.request.id" :class="{ active: item.request.id === queue.current_request_id }">
            <div><strong>{{ item.position }}. {{ customerName(item.request.source_customer_id) }}</strong>
              <span class="badge" :class="{ ok: item.state === 'CONFIRMED' }">{{ stateLabel[item.state] ?? item.state }}</span>
            </div>
            <p>{{ item.request.text }}</p>
            <small v-if="item.hold_reason">보류 사유: {{ item.hold_reason }}</small>
          </li>
        </ol>
        <p v-if="busy" role="status">현재 요청을 처리하는 중…</p>
        <p v-else-if="queue.status === 'DONE'" role="status">모든 요청을 처리했습니다. 반영 완료와 보류 내역을 확인하세요.</p>
        <p v-else>현재 요청만 처리합니다. 다음 변경안은 앞서 확정된 최신 일정에서 계산합니다.</p>
        <button v-if="queue.status === 'DONE'" class="btn primary" @click="newQueue">새 요청 3건 접수</button>
      </template>
      <div v-if="error" class="banner error" role="alert">{{ error }}</div>
    </section>

    <template v-if="current && !composing && !busy">
      <div v-if="current.state === 'INTERPRETING'" class="queue-card" role="status">
        다른 화면에서 해석 중입니다. 잠시 후 대기열을 새로고침하세요. 연결이 끊겼다면 최대 2분 후 다시 처리할 수 있습니다.
      </div>
      <template v-else>
        <PlanReview v-if="plan" :key="plan.id" :plan="plan" cancel-label="조건 수정·재계산" @confirmed="afterDecision" @held="afterDecision" @cancel="reviewAgain" />
        <RequestPanel v-else :key="current.request.id" :reference="reference" :state-revision="stateRevision"
                      :existing-request="current.request" :queue-id="queue!.id" @plan="preview" @updated="updated" @busy="(v) => (childBusy = v)" />
        <section v-if="!plan" class="queue-card">
          <label class="field"><span>이 요청을 보류하고 다음으로</span>
            <input v-model="holdReason" maxlength="200" placeholder="예: 고객에게 방문 가능 시간 재확인 필요" :disabled="childBusy" />
          </label>
          <button class="btn" :disabled="!holdReason.trim() || childBusy" @click="hold">사유를 기록하고 보류</button>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.queue { display: grid; gap: 12px; min-width: 0; }
.queue-card { display: grid; gap: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 18px; min-width: 0; }
header p, .queue-card > p { color: var(--ink-3); font-size: 13px; line-height: 1.6; }
.entry { display: grid; gap: 8px; border-top: 1px solid var(--line); padding-top: 12px; }
textarea { min-height: 72px; }
.queue-heading, .items li > div { display: flex; gap: 8px; justify-content: space-between; align-items: center; flex-wrap: wrap; }
.items { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.items li { border: 1px solid var(--line); border-radius: var(--radius-s); padding: 10px; font-size: 13px; min-width: 0; }
.items li.active { border-color: var(--ink); background: var(--bg); }
.items p { margin-top: 6px; overflow-wrap: anywhere; }
.items small { color: var(--ink-3); }
</style>
