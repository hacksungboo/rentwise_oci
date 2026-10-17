<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { observeApi } from '../api'
import { QueueTiming, timingCsv, type TimingContext } from '../queueTiming'

const props = defineProps<{ context?: TimingContext; canStart: boolean }>()
const run = ref<QueueTiming | null>(null)
const tick = ref(0)
const operator = ref('')
const seedHash = ref('')
const evidence = ref<'UNVERIFIED' | 'REAL' | 'FAKE'>('UNVERIFIED')
const report = computed(() => { void tick.value; return run.value?.report() })
const seconds = (value?: number | null) => value == null ? '—' : (value / 1000).toFixed(2) + '초'
let unsubscribe: (() => void) | undefined
let timer: ReturnType<typeof setInterval> | undefined
const active = computed(() => run.value?.status === 'ARMED' || run.value?.status === 'RUNNING')
function arm() {
  if (!props.canStart || !props.context || active.value) return
  unsubscribe?.()
  run.value = new QueueTiming({ ...props.context }, operator.value.trim(), seedHash.value.trim(), evidence.value)
  unsubscribe = observeApi(event => { run.value?.observe(event); tick.value++ })
}
function stop() { run.value?.abort('OPERATOR_STOPPED'); tick.value++ }
function hidden() {
  if (active.value && document.visibilityState === 'hidden') { run.value?.invalidate('PAGE_HIDDEN'); tick.value++ }
}
function download(format: 'json' | 'csv') {
  if (!report.value) return
  const snapshot = report.value
  const blob = new Blob([format === 'json' ? JSON.stringify(snapshot, null, 2) : timingCsv(snapshot)],
    { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = `${snapshot.queue_id ?? 'queue'}-timing.${format}`; link.click()
  URL.revokeObjectURL(url)
}
onMounted(() => {
  document.addEventListener?.('visibilitychange', hidden)
  timer = setInterval(() => { if (active.value) tick.value++ }, 1000)
})
onUnmounted(() => {
  run.value?.abort('VIEW_UNMOUNTED')
  unsubscribe?.(); clearInterval(timer)
  document.removeEventListener?.('visibilitychange', hidden)
})
</script>

<template>
  <details class="measurement">
    <summary>3건 처리시간 측정</summary>
    <p>새 3건 접수 직전부터 마지막 확정·보류 응답까지 측정합니다. 측정 자체는 AI를 호출하지 않습니다.</p>
    <template v-if="!run">
      <label class="field"><span>측정자 식별자 (선택)</span><input v-model="operator" maxlength="80" /></label>
      <label class="field"><span>운영 seed SHA256 (선택)</span><input v-model="seedHash" maxlength="64" /></label>
      <label class="field"><span>측정 환경 기록</span><select v-model="evidence">
        <option value="UNVERIFIED">실제 AI 여부 미확인</option>
        <option value="REAL">실제 AI · 운영 로그 대조 필요</option>
        <option value="FAKE">FakeClient · 연습용</option>
      </select></label>
      <button class="btn" :disabled="!canStart || !context" @click="arm">다음 3건 측정 준비</button>
      <p v-if="!canStart">새 요청 3건 접수 화면에서 시작하세요.</p>
    </template>
    <template v-else-if="report">
      <p role="status">{{ report.status === 'ARMED' ? '접수를 기다리는 중' : report.status === 'RUNNING' ? '측정 중' : report.status === 'COMPLETED' ? '측정 종료' : '측정 중단' }} · 전체 {{ seconds(report.totals.total_ms) }}</p>
      <div class="table-wrap">
        <table>
          <caption>요청별 소요시간 · API 대기에는 네트워크가 포함됩니다</caption>
          <thead><tr><th>요청</th><th>AI 해석</th><th>AI 설명</th><th>일정 계산</th><th>사람 확인 추정</th><th>기타 API</th><th>합계</th></tr></thead>
          <tbody><tr v-for="row in report.entries" :key="row.request_id">
            <th>{{ row.position }} · {{ row.outcome }}</th>
            <td>{{ seconds(row.metrics?.ai_interpret_ms) }}</td><td>{{ seconds(row.metrics?.ai_explanation_ms) }}</td>
            <td>{{ seconds(row.metrics?.solver_ms) }}</td><td>{{ seconds(row.metrics?.human_estimate_ms) }}</td>
            <td>{{ seconds(row.metrics?.other_ms) }}</td><td>{{ seconds(row.metrics?.total_ms) }}</td>
          </tr></tbody>
          <tfoot><tr><th>전체 (접수 포함)</th><td>{{ seconds(report.totals.ai_interpret_ms) }}</td>
            <td>{{ seconds(report.totals.ai_explanation_ms) }}</td><td>{{ seconds(report.totals.solver_ms) }}</td>
            <td>{{ seconds(report.totals.human_estimate_ms) }}</td><td>{{ seconds(report.totals.other_ms) }}</td>
            <td>{{ seconds(report.totals.total_ms) }}</td></tr></tfoot>
        </table>
      </div>
      <p>사람 확인 추정은 API 대기가 없는 구간이며 읽기·수정·유휴 시간을 포함합니다. 선행 요청 대기는 합계에 중복 가산하지 않습니다.</p>
      <p v-if="report.status === 'COMPLETED'">{{ report.all_confirmed ? '3건 모두 확정됨. 정확성은 별도로 판정하세요.' : '보류가 포함된 처리 결과입니다. 3건 확정 성공 시간으로 집계하지 마세요.' }}</p>
      <p v-if="report.issues.length" class="banner error">비교 제외 사유: {{ report.issues.join(', ') }}</p>
      <div class="buttons">
        <button v-if="active" class="btn" @click="stop">측정 중단</button>
        <button class="btn" @click="download('json')">측정 JSON 저장</button>
        <button class="btn" @click="download('csv')">기록표 CSV 저장</button>
      </div>
      <p>현재 화면 메모리에만 보관합니다. 새로고침·화면 전환 전에 저장하세요. 다음 측정은 새로고침 후 준비하세요.</p>
    </template>
  </details>
</template>

<style scoped>
.measurement { border: 1px solid var(--line); border-radius: var(--radius-m); padding: 14px; background: var(--surface); }
summary { cursor: pointer; font-weight: 700; }
p, label, button { margin-top: 10px; }
p, caption { font-size: 12px; line-height: 1.6; color: var(--ink-3); }
.table-wrap { overflow-x: auto; margin-top: 12px; }
table { border-collapse: collapse; font-size: 12px; white-space: nowrap; width: 100%; }
th, td { padding: 6px; text-align: right; border-bottom: 1px solid var(--line); }
.buttons { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
