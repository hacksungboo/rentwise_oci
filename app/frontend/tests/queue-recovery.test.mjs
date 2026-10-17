import assert from 'node:assert/strict'
import test from 'node:test'
import { h } from 'vue'
import { component, mount, flush } from './helpers.mjs'

const panel = await component('RequestPanel', { TimeField: { render: () => h('span') } })
const queueComponent = await component('RequestQueue', {
  RequestPanel: panel,
  PlanReview: { emits: ['held'], render() { return h('button', { onClick: () => this.$emit('held') }, 'hold-plan') } },
})
const reference = {
  customers: ['C1', 'C2', 'C3'].map((id, i) => ({ id, name: `고객${i}`, location_id: id })),
  locations: [], items: [], employees: [], assets: [],
  jobs: [{ id: 'J3', kind: 'AS', from_id: 'C3', to_id: 'WH', asset_ids: [], window_start: null, due_at: null }],
}
const intent = { schema_version: 'rental.intent.v1', operations: [], needs_confirmation: [] }
function state(advanced = false, stored = false, interpreting = false) {
  return {
    id: 'Q1', status: 'ACTIVE', state_revision: 9, current_request_id: advanced ? 'R3' : 'R2',
    items: ['R1', 'R2', 'R3'].map((id, i) => ({ position: i + 1,
      state: i === 0 ? 'CONFIRMED' : i === 1 ? (advanced ? 'HELD' : 'DRAFTED') : (interpreting ? 'INTERPRETING' : advanced ? 'RECEIVED' : 'WAITING'),
      hold_reason: i === 1 && advanced ? '방문 재확인' : null,
      request: { id, revision: 1, status: i === 0 ? 'CONFIRMED' : i === 1 ? (advanced ? 'HELD' : 'READY') : stored ? 'NEEDS_REVIEW' : 'RECEIVED',
        source_customer_id: `C${i + 1}`, text: '추가 설치, 반납일 미정',
        interpretation: i === 1 || (i === 2 && stored) ? { payload: intent, acknowledged_paths: [], origin: 'AI' } : null,
        plans: i === 1 ? [{ id: 'P2', status: 'READY' }] : [] },
    })),
  }
}
const json = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
const button = (ui, text) => ui.all().find(n => n.type === 'button' && ui.text(n).includes(text))

async function scenario(t, { stored = false, disconnected = false, readFails = false, interpreting = false, domain = false } = {}) {
  globalThis.document = { activeElement: null }
  t.after(() => { delete globalThis.document })
  let reads = 0, posts = 0
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url.endsWith('/latest')) return json({ queue: state() })
    if (url.endsWith('/plans/P2')) return json({ id: 'P2' })
    if (url.endsWith('/interpret')) {
      posts++
      if (disconnected) throw new TypeError('connection closed')
      if (domain) return new Response(JSON.stringify({ error: { code: 'AI_REVIEW_UNSUPPORTED', message: '대여 종료일·무기한 여부를 현재 화면에서 확인할 수 없습니다.' }, trace_id: 'unsupported-trace' }), { status: 422 })
      return new Response('<html>Bad Gateway</html>', { status: 502 })
    }
    if (url.endsWith('/request-queues/Q1')) {
      reads++
      if (reads === 2 && readFails) throw new TypeError('GET unavailable')
      return json(state(true, reads > 1 && stored, interpreting))
    }
    throw new Error(`Unexpected request: ${options.method} ${url}`)
  })
  const ui = mount(queueComponent, { reference, stateRevision: 9 })
  t.after(() => ui.close())
  await flush()
  await button(ui, 'hold-plan').props.onClick()
  await flush(); await flush()
  return { ui, posts: () => posts }
}

test('third request domain rejection is preserved after first confirm and second hold; manual fallback works', async t => {
  const { ui, posts } = await scenario(t, { domain: true })
  assert.match(ui.text(), /AI_REVIEW_UNSUPPORTED/)
  assert.match(ui.text(), /대여 종료일·무기한/)
  assert.equal(button(ui, '요청 해석하기').props.disabled, true)
  assert.match(ui.text(), /반영 완료/)
  assert.match(ui.text(), /보류 사유: 방문 재확인/)
  const select = ui.all().find(n => n.type === 'select' && n.children.some(c => c._value === 'J3'))
  select.props['onUpdate:modelValue']('J3')
  await flush()
  assert.equal(button(ui, '직접 입력').props.disabled, false)
  assert.equal(posts(), 1)
})

test('HTML gateway error is typed; reloading queue never automatically re-bills', async t => {
  const { ui, posts } = await scenario(t)
  assert.match(ui.text(), /HTTP_502/)
  assert.doesNotMatch(ui.text(), /NETWORK|<html>/)
  await button(ui, '대기열 새로고침').props.onClick()
  await flush()
  assert.equal(posts(), 1)
  assert.match(ui.text(), /HTTP_502/)
  const select = ui.all().find(n => n.type === 'select' && n.children.some(c => c._value === 'J3'))
  select.props['onUpdate:modelValue']('J3')
  await flush()
  assert.equal(button(ui, '직접 입력').props.disabled, false)
})

test('lost POST response restores an already saved interpretation without retry or stale error', async t => {
  const { ui, posts } = await scenario(t, { disconnected: true, stored: true })
  assert.match(ui.text(), /조건 확인/)
  assert.doesNotMatch(ui.text(), /QUEUE_RESPONSE_UNCONFIRMED|응답을 받지 못했습니다/)
  assert.equal(posts(), 1)
})

test('lost POST without stored result permits explicit manual fallback after verified GET', async t => {
  const { ui, posts } = await scenario(t, { disconnected: true })
  assert.match(ui.text(), /QUEUE_RESPONSE_UNCONFIRMED/)
  const select = ui.all().find(n => n.type === 'select' && n.children.some(c => c._value === 'J3'))
  select.props['onUpdate:modelValue']('J3')
  await flush()
  assert.equal(button(ui, '직접 입력').props.disabled, false)
  assert.equal(posts(), 1)
})

test('failed recovery GET blocks work until read-only recovery succeeds', async t => {
  const { ui, posts } = await scenario(t, { readFails: true })
  assert.match(ui.text(), /현재 처리 상태를 확인할 수 없습니다/)
  assert.equal(button(ui, '요청 해석하기'), undefined)
  await button(ui, '저장 상태 다시 확인').props.onClick()
  await flush()
  assert.ok(button(ui, '요청 해석하기'))
  assert.equal(posts(), 1)
})

test('live server lease keeps manual input and re-interpretation hidden', async t => {
  const { ui, posts } = await scenario(t, { interpreting: true })
  assert.match(ui.text(), /다른 화면에서 해석 중/)
  assert.equal(button(ui, '직접 입력'), undefined)
  assert.equal(posts(), 0)
})
