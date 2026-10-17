<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, ApiError, type Card, type Ghost, type Lane, type Ops, type PlanView, type Reference, type User, type VersionInfo } from './api'
import InventoryStrip from './components/InventoryStrip.vue'
import LoginView from './components/LoginView.vue'
import PlanReview from './components/PlanReview.vue'
import RequestPanel from './components/RequestPanel.vue'
import RequestQueue from './components/RequestQueue.vue'
import SystemPanel from './components/SystemPanel.vue'
import TimelineBoard from './components/TimelineBoard.vue'
import { addDays, dayLabel } from './format'

const user = ref<User | null>(null)
const checking = ref(true)
const ops = ref<Ops | null>(null)
const reference = ref<Reference | null>(null)
const version = ref<VersionInfo | null>(null)
const plan = ref<PlanView | null>(null)
const previewing = computed(() => !!plan.value && plan.value.status === 'READY'
  && plan.value.solver_status === 'FEASIBLE' && plan.value.base_state_revision === ops.value?.workspace.state_revision)
const date = ref<string | undefined>(undefined)
const loadError = ref('')
const toast = ref('')
const panelKey = ref(0)
const requestMode = ref<'single' | 'queue'>('queue')
function changeMode(mode: 'single' | 'queue') {
  plan.value = null
  requestMode.value = mode
}
const showSystem = ref(false)
let toastTimer: number | undefined

async function load() {
  loadError.value = ''
  try {
    const [o, r] = await Promise.all([api.operations(date.value), api.reference()])
    ops.value = o
    reference.value = r
    date.value = o.date
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) user.value = null
    else loadError.value = e instanceof ApiError ? e.message : '서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.'
  }
}

onMounted(async () => {
  try {
    user.value = (await api.me()).user
  } catch {
    user.value = null
  }
  checking.value = false
  api.version().then((v) => (version.value = v)).catch(() => {})
  if (user.value) await load()
})

async function onLogin(u: User) {
  user.value = u
  await load()
}
async function logout() {
  await api.logout().catch(() => {})
  user.value = null
  plan.value = null
}

function say(msg: string) {
  toast.value = msg
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toast.value = ''), 4200)
}

async function shiftDay(n: number) {
  if (!date.value) return
  date.value = addDays(date.value, n)
  await load()
}

async function onConfirmed(r: { confirmed_plan_id: string; new_state_revision: number }) {
  const before = ops.value?.workspace.state_revision
  plan.value = null
  panelKey.value++
  await load() // DB에서 다시 읽어 확정본을 보여준다
  say(`변경안을 확정하고 저장했습니다. 상태 버전 r${before} → r${r.new_state_revision}`)
}
function onHeld() {
  plan.value = null
  panelKey.value++
  say('변경안을 보류했습니다. 현재 계획은 바뀌지 않았습니다.')
}
function onCancel() {
  plan.value = null
  panelKey.value++
}

async function resetDemo() {
  if (!confirm('시연 데이터를 처음 상태로 되돌릴까요? 확정한 변경도 모두 사라집니다.')) return
  await api.reset()
  plan.value = null
  panelKey.value++
  date.value = undefined
  await load()
  say('시연 데이터를 처음 상태로 되돌렸습니다.')
}

// ---------------------------------------------------------------- 보드 데이터: 현재 계획 또는 변경안
const dayStart = computed(() => (date.value ? new Date(`${date.value}T00:00:00+09:00`).getTime() : 0))
const onDay = (s: string, e: string) => new Date(s).getTime() < dayStart.value + 86400_000 && new Date(e).getTime() > dayStart.value

const board = computed(() => {
  if (!ops.value) return null
  const lanes: Lane[] = ops.value.employees.map((l) => ({ ...l, items: [...l.items] }))
  let prep: Card[] = [...ops.value.prep_items]
  const ghosts: Ghost[] = []
  const changed = new Set<string>()
  const hot = new Set<string>()
  if (plan.value && previewing.value) {
    for (const d of plan.value.diff) {
      if (!d.changed) continue
      const strip = (c: Card) => c.job_id !== d.job_id
      lanes.forEach((l) => (l.items = l.items.filter(strip)))
      prep = prep.filter(strip)
      if (d.before && onDay(d.before.start_at, d.before.end_at)) {
        ghosts.push({ job_id: d.job_id, lane: d.before.employee_id ?? 'PREP', start_at: d.before.start_at, end_at: d.before.end_at, kind: d.kind })
      }
      if (d.after && onDay(d.after.start_at, d.after.end_at)) {
        const card: Card = {
          job_id: d.job_id, kind: d.kind, asset_ids: d.after.asset_ids, start_at: d.after.start_at, end_at: d.after.end_at,
          segments: d.after.segments, site_id: d.site_id, site_name: d.site_name, reason_codes: d.reason_codes,
        }
        const lane = lanes.find((l) => l.id === d.after!.employee_id)
        if (lane) lane.items.push(card)
        else prep.push(card)
      }
      changed.add(d.job_id)
      ;[...(d.before?.asset_ids ?? []), ...(d.after?.asset_ids ?? [])].forEach((a) => hot.add(a))
    }
  }
  return { lanes, prep, ghosts, changed, hot }
})

const engineLabel = computed(() => (ops.value?.workspace.engine_mode === 'real' ? 'AI 배정 엔진' : '고정 응답 엔진 (AI 연동 전)'))
const isAdmin = computed(() => user.value?.role === 'ADMIN')
</script>

<template>
  <div v-if="checking" class="splash" aria-busy="true" />
  <LoginView v-else-if="!user" @login="onLogin" />

  <div v-else class="app">
    <header class="top">
      <div class="brand">
        <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#18223A"/><rect x="7" y="9" width="18" height="5" rx="2" fill="#F4C542"/><rect x="7" y="18" width="11" height="5" rx="2" fill="#7FD1C8"/></svg>
        <strong>rentwise</strong>
      </div>

      <nav v-if="ops" class="day" aria-label="날짜">
        <button class="btn ghost small" aria-label="전날" @click="shiftDay(-1)">‹</button>
        <span class="num">{{ dayLabel(`${ops.date}T09:00:00+09:00`) }}</span>
        <button class="btn ghost small" aria-label="다음날" @click="shiftDay(1)">›</button>
      </nav>

      <div v-if="ops" class="state">
        <span class="badge" title="현재 확정 계획">계획 {{ ops.workspace.current_plan_id }}</span>
        <span class="badge num" title="확정할 때마다 1씩 오릅니다">상태 r{{ ops.workspace.state_revision }}</span>
        <span class="badge" :class="ops.workspace.engine_mode === 'real' ? 'ai' : 'mock'">{{ engineLabel }}</span>
        <span v-if="version?.db" class="badge" :title="version.db_banner ?? ''">{{ version.db === 'oracle' ? 'Oracle DB' : version.db }}</span>
        <button v-if="version?.cloud" class="badge cloud" :class="version.cloud.provider" type="button" @click="showSystem = true"
                title="실행 환경 보기">
          <i />{{ version.cloud.provider === 'oci' ? `OCI ${version.cloud.region} · ${version.cloud.display_name}` : '로컬 실행' }}
        </button>
      </div>

      <div class="who">
        <span>{{ user.name }}</span>
        <button v-if="isAdmin" class="btn ghost small" @click="resetDemo">시연 초기화</button>
        <button class="btn ghost small" @click="logout">로그아웃</button>
      </div>
    </header>

    <div v-if="loadError" class="banner error page">{{ loadError }}</div>

    <main v-if="ops && reference && board" class="layout">
      <section class="left">
        <div class="board-head">
          <h2>{{ previewing ? '변경안 미리보기' : '오늘의 배차' }}</h2>
          <p v-if="previewing">노란 테두리가 바뀌는 작업, 점선은 원래 위치입니다.</p>
          <p v-else-if="plan">적용할 변경안이 없어 현재 확정 일정을 표시합니다.</p>
          <p v-else>직원별 이동·현장 작업과 창고 준비 시간입니다.</p>
        </div>
        <TimelineBoard :lanes="board.lanes" :prep="board.prep" :ghosts="board.ghosts" :changed="board.changed" />
        <InventoryStrip :ops="ops" :hot="board.hot" />
      </section>

      <aside class="right">
        <template v-if="isAdmin">
          <nav class="request-modes" aria-label=" 요청 접수 방식">
            <button class="btn" :class="{ primary: requestMode === 'queue' }" @click="changeMode('queue')">3건 순차 처리</button>
            <button class="btn" :class="{ primary: requestMode === 'single' }" @click="changeMode('single')">단일 요청</button>
          </nav>
          <RequestQueue v-if="requestMode === 'queue'" :key="panelKey" :reference="reference" :state-revision="ops.workspace.state_revision"
                        @preview="(p) => (plan = p)" @changed="load" />
          <template v-else>
            <PlanReview v-if="plan" :plan="plan" @confirmed="onConfirmed" @held="onHeld" @cancel="onCancel" />
            <RequestPanel v-else :key="panelKey" :reference="reference" :state-revision="ops.workspace.state_revision" @plan="(p) => (plan = p)" />
          </template>
        </template>
        <section v-else class="staff">
          <h2>{{ user.name }}님의 작업</h2>
          <p>왼쪽 보드에서 내 일정을 확인하세요. 현장 완료 기록 화면은 다음 단계에서 열립니다.</p>
        </section>
      </aside>
    </main>

    <footer v-if="version" class="foot num">
      빌드 {{ version.build_sha.slice(0, 7) }} · {{ version.image_tag }}<template v-if="version.server"> · {{ version.server }}</template>
    </footer>

    <SystemPanel v-if="showSystem" @close="showSystem = false" />

    <Transition name="toast">
      <div v-if="toast" class="toast" role="status">{{ toast }}</div>
    </Transition>
  </div>
</template>

<style scoped>
.splash { min-height: 100vh; }
.app { min-height: 100vh; display: grid; grid-template-rows: auto auto 1fr auto; grid-template-columns: minmax(0, 1fr); }
.top { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 18px; padding: 10px 20px; background: var(--surface); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 8px; font-size: 17px; letter-spacing: -.01em; }
.day { display: flex; align-items: center; gap: 2px; font-weight: 600; }
.state { display: flex; gap: 6px; flex-wrap: wrap; }
.who { margin-left: auto; display: flex; align-items: center; gap: 4px; font-size: 14px; color: var(--ink-2); }
.page { margin: 12px 20px 0; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 420px); gap: 18px; padding: 18px 20px; align-items: start; }
.left { display: grid; gap: 14px; min-width: 0; }
.board-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.board-head p { color: var(--ink-3); font-size: 13.5px; }
.right { position: sticky; top: 70px; min-width: 0; }
.request-modes { display: flex; gap: 8px; margin-bottom: 10px; }
.staff { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-m); padding: 18px; display: grid; gap: 6px; }
.staff p { color: var(--ink-2); font-size: 14px; }
.cloud { border: 0; cursor: pointer; font: inherit; font-size: 12.5px; font-weight: 600; }
.cloud i { width: 8px; height: 8px; border-radius: 50%; background: var(--ink-3); display: inline-block; }
.cloud.oci { background: #fbe9e6; color: #8a2a1c; }
.cloud.oci i { background: #c74634; box-shadow: 0 0 0 3px rgba(199, 70, 52, .18); }
.foot { padding: 8px 20px 16px; font-size: 12px; color: var(--ink-3); }
.toast { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); background: var(--ink); color: #fff; padding: 12px 18px; border-radius: var(--radius-s); font-size: 14.5px; box-shadow: 0 8px 24px rgba(24, 34, 58, .25); z-index: 50; }
.toast-enter-active, .toast-leave-active { transition: opacity .2s, transform .2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 8px); }
@media (max-width: 1100px) {
  .layout { grid-template-columns: 1fr; }
  .right { position: static; }
}
</style>
