import assert from 'node:assert/strict'
import test from 'node:test'
import { component, mount, flush } from './helpers.mjs'

const timeField = await component('TimeField')
const panel = await component('RequestPanel', { TimeField: timeField })
const button = (ui, text) => ui.all().find(n => n.type === 'button' && ui.text(n).includes(text))
const select = (ui, name) => ui.all().find(n => n.type === 'select' && n.props['aria-label'] === name)
const questions = ['target_job_id', 'window_start', 'window_end', 'due_at'].map(f => ({ path: `operations.0.${f}`, question: f, reason: 'AMBIGUOUS' }))
const job = (id, item, destination, day = '16') => ({ id, item_id: item, kind: 'DELIVERY', from_id: 'WH', to_id: destination,
  window_start: `2026-10-${day}T16:00:00+09:00`, due_at: `2026-10-${day}T16:30:00+09:00` })
const reference = { customers: [{ id: 'C-M', location_id: 'M', name: '미르' }, { id: 'C-X', location_id: 'X', name: '다른고객' }],
  locations: [{ id: 'M', name: '미르디자인' }, { id: 'X', name: '다른고객' }],
  items: [{ id: 'PR-A', model_name: '프린터', service_minutes_by_kind: { DELIVERY: 15 } }, { id: 'NB-A', model_name: '노트북' }],
  jobs: [job('J-TODAY', 'PR-A', 'M'), job('J-NEXT', 'PR-A', 'M', '21'), job('J-NB', 'NB-A', 'M'), job('J-X', 'PR-A', 'X')] }
function scenario(t, missing = false) {
  globalThis.document = { activeElement: null }
  t.after(() => { delete globalThis.document })
  const request = { id: 'R1', revision: 1, received_at: '2026-10-16T09:00:00+09:00', source_customer_id: 'C-X', text: '오늘 4시 프린터 설치를 3시~3시반 사이로 당겨주세요.',
    interpretation: { origin: 'AI', revision: 1, acknowledged_paths: [], payload: { schema_version: 'rental.intent.v1', needs_confirmation: questions,
      operations: [{ operation: 'RESCHEDULE', kind: 'DELIVERY', item_id: 'PR-A', source_customer_id: 'C-X', destination_customer_id: 'C-M',
        target_job_id: 'J-TODAY', window_start: missing ? null : '2026-10-16T15:00:00+09:00',
        window_end: missing ? null : '2026-10-16T15:30:00+09:00', due_at: null, evidence: [] }] } } }
  const ui = mount(panel, { reference, stateRevision: 7, existingRequest: request })
  t.after(() => ui.close())
  return { ui, request }
}

test('actual TimeField shows matched new date/time, and deadline suggestion fills controls and saved payload', async t => {
  const { ui, request } = scenario(t)
  assert.equal(select(ui, '방문 시작 날짜').props.value, '2026-10-16')
  assert.equal(select(ui, '방문 시작 시').props.value, '15')
  assert.equal(select(ui, '방문 종료 분').props.value, '30')
  const target = ui.all().find(n => n.type === 'select' && n.children.some(c => c._value === 'J-TODAY'))
  assert.match(ui.text(target), /10월 16일/)
  assert.match(ui.text(target), /10월 21일/)
  assert.doesNotMatch(ui.text(target), /J-NB|J-X/)
  button(ui, '기존 완료 기한 (16:30)').props.onClick({ preventDefault() {} })
  await flush()
  assert.equal(select(ui, '완료 기한 시').props.value, '16')
  assert.equal(select(ui, '완료 기한 분').props.value, '30')
  const checks = ui.all().filter(n => n.type === 'input' && n.props.type === 'checkbox')
  assert.equal(checks[3].props.checked, true)
  for (let i = 0; i < 3; i++) checks[i].props.onChange()
  await flush()
  let saved
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const data = JSON.parse(options.body)
    if (options.method === 'PUT') {
      saved = data
      return new Response(JSON.stringify({ ...request, interpretation: { revision: 2 } }))
    }
    assert.match(url, /\/plans$/)
    return new Response(JSON.stringify({ id: 'P1' }), { status: 201 })
  })
  assert.equal(button(ui, '조건 확인하고 변경안 계산').props.disabled, false)
  await button(ui, '조건 확인하고 변경안 계산').props.onClick()
  await flush()
  assert.equal(saved.payload.operations[0].window_start, '2026-10-16T15:00:00+09:00')
  assert.equal(saved.payload.operations[0].window_end, '2026-10-16T15:30:00+09:00')
  assert.equal(saved.payload.operations[0].due_at, '2026-10-16T16:30:00+09:00')
  assert.deepEqual(new Set(saved.acknowledged_paths), new Set(questions.map(q => q.path)))
})

test('missing start explains why suggestions are unavailable; manual start unlocks real end controls', async t => {
  const { ui } = scenario(t, true)
  assert.match(ui.text(), /방문 시작 날짜·시각을 먼저 입력/)
  assert.equal(button(ui, '시작 + 현장'), undefined)
  select(ui, '방문 시작 날짜').props.onChange({ target: { value: '2026-10-16' } })
  await flush()
  select(ui, '방문 시작 시').props.onChange({ target: { value: '15' } })
  await flush()
  button(ui, '시작 + 현장 15분 (15:15)').props.onClick({ preventDefault() {} })
  await flush()
  assert.equal(select(ui, '방문 종료 날짜').props.value, '2026-10-16')
  assert.equal(select(ui, '방문 종료 시').props.value, '15')
  assert.equal(select(ui, '방문 종료 분').props.value, '15')
})
