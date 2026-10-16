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
  PREPARATION_DEPENDENCY: '앞 장비의 준비 완료가 출발보다 늦음',
  SUBSTITUTE_SHORTAGE: '대체할 장비 부족',
  MOCK_ENGINE_UNSUPPORTED: '현재 계산 엔진이 지원하지 않는 요청',
  EMPLOYEE_OVERLAP: '직원 일정 겹침',
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
