import assert from 'node:assert/strict'
import test from 'node:test'
import { h } from 'vue'
import { component, mount, flush } from './helpers.mjs'

const panel = await component('RequestPanel', { TimeField: {
  props: ['modelValue', 'label'], render() { return h('div', { 'data-field': this.label }, this.modelValue ?? '') },
} })
const button = (ui, text) => ui.all().find(n => n.type === 'button' && ui.text(n).includes(text))
function scenario(t, { start = '2026-10-16T16:00:00+09:00', end = null, existing = '2026-10-16T11:30:00+09:00', duration = 30 } = {}) {
  globalThis.document = { activeElement: null }
  t.after(() => { delete globalThis.document })
  const request = { id: 'R1', received_at: '2026-10-16T09:00:00+09:00', text: '정수기 AS 오후 4시',
    source_customer_id: 'C1', interpretation: { origin: 'AI', acknowledged_paths: [], payload: {
      operations: [{ operation: 'RESCHEDULE', kind: 'AS', target_job_id: 'J1', item_id: 'WP',
        source_customer_id: 'C1', evidence: [], window_start: start, window_end: end, due_at: null }],
      needs_confirmation: [{ path: 'operations.0.window_end', question: '방문 종료' }, { path: 'operations.0.due_at', question: '완료 기한' }],
    } } }
  const reference = { customers: [{ id: 'C1', location_id: 'L1' }], locations: [],
    items: [{ id: 'WP', service_minutes_by_kind: duration ? { AS: duration } : {} }],
    jobs: [{ id: 'J1', kind: 'AS', from_id: 'L1', due_at: existing }] }
  const ui = mount(panel, { reference, stateRevision: 7, existingRequest: request })
  t.after(() => ui.close())
  return ui
}

test('late AS uses service completion suggestion and requires a human click to fill deadline', async t => {
  const ui = scenario(t)
  assert.equal(button(ui, '기존 완료 기한 (11:30)'), undefined)
  const deadline = () => ui.all().find(n => n.props['data-field'] === '완료 기한')
  assert.equal(ui.text(deadline()), '')
  button(ui, '방문 종료 기준 (16:30)').props.onClick({ preventDefault() {} })
  await flush()
  assert.match(ui.text(deadline()), /2026-10-16T16:30:00/)
})

test('existing promise is suggested when it still covers the new service end', t => {
  const ui = scenario(t, { existing: '2026-10-16T17:30:00+09:00' })
  assert.ok(button(ui, '기존 완료 기한 (17:30)'))
  assert.equal(button(ui, '방문 종료 기준'), undefined)
})

test('deadline suggestion respects selected visit end rather than only service duration', t => {
  const ui = scenario(t, { end: '2026-10-16T17:00:00+09:00' })
  assert.ok(button(ui, '방문 종료 기준 (17:00)'))
})

test('previous-day deadline is never suggested for a later-day visit', t => {
  const ui = scenario(t, { start: '2026-10-17T16:00:00+09:00', existing: '2026-10-16T17:30:00+09:00' })
  assert.equal(button(ui, '기존 완료 기한'), undefined)
  assert.ok(button(ui, '방문 종료 기준 (16:30)'))
})

test('unknown AS duration and absent visit end do not fabricate a deadline', t => {
  const ui = scenario(t, { duration: null })
  assert.equal(button(ui, '기존 완료 기한'), undefined)
  assert.equal(button(ui, '방문 종료 기준'), undefined)
})


for (const end of ['2026-10-16T10:30:00+09:00', '2026-10-16T16:10:00+09:00'])
  test(`stale or too-short visit end cannot revive an obsolete morning deadline (${end})`, t => {
    const ui = scenario(t, { end })
    assert.equal(button(ui, '기존 완료 기한'), undefined)
    assert.ok(button(ui, '방문 종료 기준 (16:30)'))
  })
