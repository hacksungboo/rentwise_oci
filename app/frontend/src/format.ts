// 표시 문구와 시각 변환 (Asia/Seoul 고정)

export const KIND_LABEL: Record<string, string> = {
  DELIVERY: '납품', PICKUP: '회수', AS: 'A/S', TRANSFER: '고객 간 이동', PREP: '창고 준비',
}

export const STATE_LABEL: Record<string, string> = {
  READY_WAREHOUSE: '창고 준비 완료', AT_CUSTOMER: '고객 보유', IN_TRANSIT: '이동 중',
  PREP_REQUIRED: '준비 필요', REPAIR: '수리 중', UNAVAILABLE: '사용 불가',
}

export const REASON_LABEL: Record<string, string> = {
  RETURN_DELAY: '회수 시각이 늦어짐',
  PREFERRED_EMPLOYEE_CONFLICT: '담당 직원 일정과 겹쳐 다른 직원 배정',
  SAME_MODEL_SUBSTITUTE: '같은 모델 장비로 대체',
  PREPARATION_DEPENDENCY: '반납이 늦어져 창고 준비도 함께 이동',
  RETURN_TO_PREP: '반납 후 창고 준비',
  RETURN_PREP: '반납 후 창고 준비',
  READY_DELIVERY: '준비 완료 후 납품',
  ASSET_REUSE: '같은 장비를 다음 납품에 사용',
  STAFF_REASSIGNED: '다른 직원으로 변경',
  NO_VALID_CANDIDATE: '조건을 모두 지키는 계획을 찾지 못함',
  SEARCH_LIMIT: '탐색 한도 안에서 계획을 찾지 못함',
  SEARCH_SCOPE_LIMIT: '한 번에 바뀌는 작업이 너무 많음',
  UNSUPPORTED_OPERATION: '이 엔진이 아직 지원하지 않는 요청',
  B_V1_PERSISTENCE_UNSUPPORTED: '현재 저장 범위를 넘는 변경',
  B_V1_UNSUPPORTED_OPERATION: '이 엔진이 아직 지원하지 않는 요청',
  UNCONFIRMED_FIELDS: '확인되지 않은 조건이 있음',
  EMPLOYEE_BREAK: '직원 휴식 시간과 겹침',
  DUE_AT: '완료 기한을 넘김',
  VISIT_WINDOW: '방문 가능 시간을 벗어남',
  SUBSTITUTE_SHORTAGE: '대체할 장비 부족',
  MOCK_ENGINE_UNSUPPORTED: '현재 계산 엔진이 지원하지 않는 요청',
  EMPLOYEE_OVERLAP: '직원 일정 겹침',
  QUICK_SERVICE_REQUIRED: '내부 배송 인력 부족으로 퀵 배정 · 실제 호출 필요',
  PICKUP_NEXT_WORKDAY: '고객 방문 가능한 다음 근무일로 회수 제안',
  QUICK_RESOURCE_SCOPE: '이 퀵 자원은 지정된 배송 업무에만 배정할 수 있음',
}

export const CONFIRM_FIELD_LABEL: Record<string, string> = {
  window_start: '방문 시작', window_end: '방문 종료', due_at: '완료 기한', quantity: '수량',
  target_job_id: '변경할 작업', item_id: '품목', kind: '업무',
}

const tz = 'Asia/Seoul'
const hm = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz })
const md = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'short', timeZone: tz })

export const time = (iso: string | null | undefined) => (iso ? hm.format(new Date(iso)) : '—')
export const dayLabel = (iso: string) => md.format(new Date(iso))

/** ISO(+09:00) ↔ <input type="datetime-local"> 값 */
export function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(new Date(iso).getTime() + 9 * 3600_000)
  return d.toISOString().slice(0, 16)
}
export function fromLocalInput(v: string): string | null {
  return v ? `${v}:00+09:00` : null
}

/** 하루 중 분(KST) */
export function minuteOfDay(iso: string): number {
  const d = new Date(new Date(iso).getTime() + 9 * 3600_000)
  return d.getUTCHours() * 60 + d.getUTCMinutes()
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
