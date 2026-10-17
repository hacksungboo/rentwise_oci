import assert from 'node:assert/strict'
import test from 'node:test'
import { timingModuleUrl, apiModuleUrl, component, mount, flush } from './helpers.mjs'
const { QueueTiming, partition, timingCsv } = await import(timingModuleUrl)
const { api, observeApi } = await import(apiModuleUrl)
const context = { build_sha: 'test-build', engine_mode: 'real', dataset_version: 'rental-synth-busy-v1',
  clock_anchor: '2026-10-16T09:00:00+09:00', state_revision: 7, current_plan_id: 'PL-007', total_assets: 132, employees: 12, customers: 38 }
function harness() {
  let time = 0, seq = 0
  const run = new QueueTiming(context, 'tester', 'seed-hash', 'FAKE', () => time, () => '2026-10-17T00:00:00.000Z')
  const begin = (path, method = 'POST', request_id) => {
    const e = { stage: 'start', id: ++seq, path, method, request_id, started_ms: time }; run.observe(e); return e
  }
  const end = (e, result, error_code) => run.observe({ ...e, stage: 'end', ended_ms: time, result, error_code })
  const advance = ms => { time += ms }
  const send = (path, ms, result, method = 'POST', request_id, error) => {
    const e = begin(path, method, request_id); advance(ms); end(e, result, error)
  }
  const q = { id: 'Q1', state_revision: 7, items: [1, 2, 3].map(i => ({ position: i,
    state: i === 1 ? 'RECEIVED' : 'WAITING', request: { id: `R${i}` } })) }
  const create = () => send('/request-queues', 100, q)
  return { run, begin, end, advance, send, create, q }
}
function process(h, i, hold = false) {
  h.send('/request-queues/Q1/interpret', 3000, { status: 'NEEDS_REVIEW', interpretation: { origin: 'AI' } }, 'POST', `R${i}`)
  h.advance(10000)
  h.send(`/requests/R${i}/interpretation`, 100, { status: 'READY' }, 'PUT')
  h.send('/request-queues/Q1/plan', 2000, { id: `P${i}`, status: 'READY', base_state_revision: 6 + i }, 'POST', `R${i}`)
  h.send(`/plans/P${i}/explanation`, 1000, { status: 'OK', explanation: { source: 'AI' } })
  h.advance(5000)
  h.send(`/plans/P${i}/${hold ? 'hold' : 'confirm'}`, 100, { new_state_revision: 7 + i })
}
test('three FIFO decisions partition wall time exactly; queue wait never double-counted', () => {
  const h = harness(); h.advance(50000); h.create()
  for (let i = 1; i <= 3; i++) process(h, i)
  const r = h.run.report()
  assert.equal(r.status, 'COMPLETED'); assert.equal(r.all_confirmed, true); assert.equal(r.timing_valid, true)
  assert.deepEqual(r.totals, { ai_interpret_ms: 9000, ai_explanation_ms: 3000, solver_ms: 6000,
    other_ms: 700, human_estimate_ms: 45000, total_ms: 63700 })
  assert.deepEqual(r.entries.map(e => e.queue_wait_ms), [100, 21300, 42500])
  assert.deepEqual(r.entries.map(e => e.base_revisions), [[7], [8], [9]])
  assert.deepEqual(r.entries.map(e => e.confirmed_revision), [8, 9, 10])
  assert.equal(r.entries.reduce((sum, row) => sum + row.metrics.total_ms, r.setup_ms), r.totals.total_ms)
  assert.equal(r.ended_at, '2026-10-17T00:01:03.700Z')
  h.advance(5000); assert.equal(h.run.report().totals.total_ms, 63700)
  assert.doesNotMatch(JSON.stringify(r), /고객|password|API_KEY/)
})
test('parallel GET and explanation/confirm count once with explicit precedence', () => {
  const s = (kind, start_ms, end_ms) => ({ kind, start_ms, end_ms })
  assert.deepEqual(partition(0, 100, [s('other', 10, 90), s('other', 20, 80), s('ai_explanation', 30, 70)]), {
    ai_interpret_ms: 0, ai_explanation_ms: 40, solver_ms: 0, other_ms: 40, human_estimate_ms: 20, total_ms: 100 })
})
test('errors and retries remain in trace; holds are not counted as three confirmed', () => {
  const h = harness(); h.create()
  h.send('/request-queues/Q1/interpret', 2000, null, 'POST', 'R1', 'AI_TIMEOUT')
  h.advance(500); process(h, 1, true); process(h, 2); process(h, 3)
  const r = h.run.report()
  assert.equal(r.status, 'COMPLETED'); assert.equal(r.all_confirmed, false)
  assert.equal(r.entries[0].outcome, 'HELD'); assert.equal(r.totals.ai_interpret_ms, 11000)
  assert.equal(r.spans.filter(s => s.error_code === 'AI_TIMEOUT').length, 1)
  assert.match(timingCsv(r), /AI_TIMEOUT/)
})
test('explanation system fallback and error code survive export', () => {
  const h = harness(); h.create()
  h.send('/request-queues/Q1/plan', 100, { id: 'P1', base_state_revision: 7 }, 'POST', 'R1')
  h.send('/plans/P1/explanation', 1000, { status: 'FALLBACK', error_code: 'AI_BUDGET_EXCEEDED', explanation: { source: 'SYSTEM' } })
  const r = h.run.report(); assert.equal(r.spans.at(-1).error_code, 'AI_BUDGET_EXCEEDED')
  assert.ok(r.entries[0].origins.includes('EXPLANATION_SYSTEM'))
})
test('external decision after lost response invalidates run without inventing confirmation timing', () => {
  const h = harness(); h.create()
  h.send('/request-queues/Q1', 100, { items: [{ state: 'CONFIRMED', request: { id: 'R1' } }] }, 'GET')
  const r = h.run.report(); assert.equal(r.status, 'ABORTED'); assert.equal(r.timing_valid, false)
  assert.ok(r.issues.includes('EXTERNAL_DECISION_OR_LOST_RESPONSE'))
})
test('hidden page, abort, stale start and non-fresh queue remain incomplete/invalid', () => {
  const h = harness(); h.create(); h.run.invalidate('PAGE_HIDDEN'); h.advance(200); h.run.abort('OPERATOR_STOPPED')
  assert.equal(h.run.report().timing_valid, false); assert.equal(h.run.report().totals.total_ms, 300)
  assert.equal(h.run.report().entries[1].metrics, null)
  const x = harness(); x.q.state_revision = 8; x.create(); assert.ok(x.run.report().issues.includes('INITIAL_REVISION_CHANGED'))
  const y = harness(); y.q.items[0].state = 'CONFIRMED'; y.create(); assert.equal(y.run.report().status, 'ABORTED')
})
test('unrelated calls are ignored and CSV protects formulas while preserving build context', () => {
  const h = harness(); h.create()
  h.send('/requests/UNRELATED/interpret', 100, { status: 'NEEDS_REVIEW' })
  h.send('/plans/UNRELATED/customer-message', 100, {})
  assert.equal(h.run.report().spans.length, 1)
  const r = h.run.report(); r.operator = '=HYPERLINK("bad")'
  const csv = timingCsv(r)
  assert.match(csv, /build_sha/); assert.match(csv, /test-build/); assert.match(csv, /'=/)
})
test('API observers record full fetch/body latency and errors; observer exception cannot break work', async t => {
  const events = []
  const off = observeApi(e => events.push(e)); const broken = observeApi(() => { throw Error('observer') })
  t.after(off); t.after(broken)
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ queue: null })))
  assert.deepEqual(await api.latestQueue(), { queue: null })
  assert.equal(events[0].stage, 'start'); assert.equal(events[1].stage, 'end')
  assert.ok(events[1].ended_ms >= events[0].started_ms)
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('offline') })
  await assert.rejects(api.queue('Q1'), e => e.code === 'NETWORK')
  assert.equal(events.at(-1).error_code, 'NETWORK')
})
const measurement = await component('QueueMeasurement')
const button = (ui, text) => ui.all().find(n => n.type === 'button' && ui.text(n).includes(text))
test('actual measurement UI arms without AI and exports interrupted partial record', async t => {
  let visibilityListener, calls = 0, captured, filename
  const doc = { visibilityState: 'visible', addEventListener: (name, fn) => { visibilityListener = fn }, removeEventListener() {},
    createElement: () => ({ set href(value) {}, set download(value) { filename = value }, click() {} }) }
  globalThis.document = doc
  t.mock.method(globalThis, 'fetch', async () => { calls++; return new Response('{}') })
  t.mock.method(URL, 'createObjectURL', blob => { captured = blob; return 'blob:test' })
  t.mock.method(URL, 'revokeObjectURL', () => {})
  const ui = mount(measurement, { context, canStart: true }); t.after(() => { ui.close(); delete globalThis.document })
  await button(ui, '다음 3건 측정 준비').props.onClick(); await flush()
  assert.equal(calls, 0); assert.match(ui.text(), /접수를 기다리는 중/)
  doc.visibilityState = 'hidden'; visibilityListener(); await flush()
  assert.match(ui.text(), /PAGE_HIDDEN/)
  await button(ui, '측정 중단').props.onClick(); await flush()
  await button(ui, '측정 JSON 저장').props.onClick()
  const json = JSON.parse(await captured.text())
  assert.equal(json.status, 'ABORTED'); assert.equal(json.timing_valid, false)
  assert.match(filename, /timing.json/); assert.equal(calls, 0)
})

test('actual Vue panel observes three real API wrappers in FIFO and exports complete totals without extra requests', async t => {
  let captured, count = 0
  globalThis.document = { activeElement: null, addEventListener() {}, removeEventListener() {},
    createElement: () => ({ click() {} }) }
  t.mock.method(URL, 'createObjectURL', blob => { captured = blob; return 'blob:done' })
  t.mock.method(URL, 'revokeObjectURL', () => {})
  const q = harness().q
  t.mock.method(globalThis, 'fetch', async (url, opts) => {
    count++
    const body = opts.body ? JSON.parse(opts.body) : {}
    let value
    if (url.endsWith('/request-queues')) value = q
    else if (url.endsWith('/interpret')) value = { id: body.request_id, status: 'NEEDS_REVIEW', interpretation: { origin: 'AI' } }
    else if (url.endsWith('/interpretation')) value = { status: 'READY' }
    else if (url.endsWith('/plan')) value = { id: 'P' + body.request_id.slice(1), status: 'READY', base_state_revision: 6 + Number(body.request_id.slice(1)) }
    else if (url.endsWith('/explanation')) value = { status: 'OK', explanation: { source: 'AI' } }
    else if (url.endsWith('/confirm')) value = { new_state_revision: 7 + Number(url.match(/\/plans\/P(\d)/)[1]) }
    else throw new Error('unexpected request')
    return new Response(JSON.stringify(value))
  })
  const ui = mount(measurement, { context, canStart: true })
  t.after(() => { ui.close(); delete globalThis.document })
  ui.all().find(n => n.type === 'select').props['onUpdate:modelValue']('FAKE')
  await button(ui, '다음 3건 측정 준비').props.onClick()
  await api.createQueue([], 'test-only')
  for (let i = 1; i <= 3; i++) {
    await api.queuedInterpret('Q1', `R${i}`, 1)
    await api.saveInterpretation(`R${i}`, 1, {}, [])
    const plan = await api.queuedPlan('Q1', `R${i}`, 2)
    await api.explainPlan(plan)
    await api.confirm(plan.id, 1, plan.base_state_revision)
  }
  await flush()
  assert.match(ui.text(), /측정 종료/); assert.match(ui.text(), /3건 모두 확정/)
  await button(ui, '측정 JSON 저장').props.onClick()
  const r = JSON.parse(await captured.text())
  assert.equal(count, 16); assert.equal(r.status, 'COMPLETED'); assert.equal(r.timing_valid, true)
  assert.equal(r.evidence, 'FAKE'); assert.equal(r.spans.length, 16)
  assert.deepEqual(r.entries.map(e => e.confirmed_revision), [8, 9, 10])
  const sum = Object.entries(r.totals).filter(([k]) => k !== 'total_ms').reduce((n, [, value]) => n + value, 0)
  assert.ok(Math.abs(sum - r.totals.total_ms) < .001)
  await button(ui, '기록표 CSV 저장').props.onClick()
  assert.equal((await captured.text()).trim().split('\r\n').length, 5)
})

test('in-flight explanation is clipped at last decision and does not extend batch wall time', () => {
  const h = harness(); h.create(); process(h, 1); process(h, 2)
  h.send('/request-queues/Q1/plan', 100, { id: 'P3', base_state_revision: 9 }, 'POST', 'R3')
  const e = h.begin('/plans/P3/explanation'); h.advance(100)
  h.send('/plans/P3/confirm', 100, { new_state_revision: 10 })
  const r = h.run.report(); assert.equal(r.spans.find(s => s.id === e.id).completed, false)
  assert.equal(r.timing_valid, false); assert.ok(r.issues.includes('DECISION_WITH_PENDING_AI'))
  const total = r.totals.total_ms; h.advance(5000); h.end(e, { status: 'OK' })
  assert.equal(h.run.report().totals.total_ms, total)
})
