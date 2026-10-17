import assert from 'node:assert/strict'
import test from 'node:test'

import { apiModuleUrl } from './helpers.mjs'
const { api, ApiError, requestError } = await import(apiModuleUrl)

for (const status of [502, 504, 524]) test(`HTML ${status} preserves HTTP status/trace without exposing proxy HTML`, async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>private proxy details</html>', { status, headers: { 'X-Trace-Id': 'trace-123' } }))
  await assert.rejects(api.latestQueue(), e => {
    assert.ok(e instanceof ApiError)
    assert.equal(e.status, status)
    assert.equal(e.code, `HTTP_${status}`)
    assert.equal(e.traceId, 'trace-123')
    assert.ok(!e.message.includes('private'))
    assert.match(requestError(e).message, /trace-123/)
    return true
  })
})

test('backend JSON AI error retains its domain code and message', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ error: { code: 'AI_TIMEOUT', message: '모델 응답 지연' }, trace_id: 'domain-trace' }), { status: 502 }))
  await assert.rejects(api.latestQueue(), e => e.code === 'AI_TIMEOUT' && e.message === '모델 응답 지연' && e.traceId === 'domain-trace')
})

test('only fetch rejection becomes NETWORK, not local code exceptions', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('fetch failed') })
  await assert.rejects(api.latestQueue(), e => e.code === 'NETWORK' && e.status === 0)
  assert.equal(requestError(new TypeError('local bug')).code, 'CLIENT_ERROR')
})

for (const body of ['<html>unexpected page</html>', '']) test(`invalid successful response is typed instead of NETWORK (${body ? 'HTML' : 'empty'})`, async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(body))
  await assert.rejects(api.latestQueue(), e => e.code === 'INVALID_RESPONSE' && e.status === 200)
})

test('interrupted response body is distinguishable from transport failure', async t => {
  t.mock.method(globalThis, 'fetch', async () => ({ status: 200, headers: new Headers(), text: async () => { throw new Error('closed') } }))
  await assert.rejects(api.latestQueue(), e => e.code === 'RESPONSE_INTERRUPTED' && e.status === 200)
})
