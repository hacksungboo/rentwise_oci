import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/markdown.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
const { inline, blocks } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))

test('headings, facts, preserved promises and notice are separate semantic blocks', () => {
  const result = blocks('### 변경 핵심\n\n- 회수 **14:00**\n- 준비 **14:30~15:00**\n\n### 유지되는 약속\n\n- 납품 **12:00** 유지\n\n> **확정 전 안내**\n> 현재 일정은 그대로입니다.')
  assert.deepEqual(result.map(b => b.kind), ['heading', 'list', 'heading', 'list', 'quote'])
  assert.equal(result[1].lines[1][1].text, '14:30~15:00')
  assert.equal(result[1].lines[1][1].strong, true)
})

test('escaped user punctuation remains text including inside server emphasis', () => {
  const parts = inline('**고객 \\*\\*다른 강조\\*\\***와 \\[링크\\]\\(x\\)')
  assert.deepEqual(parts[0], { text: '고객 **다른 강조**', strong: true })
  assert.equal(parts.slice(1).map(p => p.text).join(''), '와 [링크](x)')
})

test('HTML, script, links and images are inert strings without URL or HTML tokens', () => {
  for (const text of ['<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '[click](javascript:alert(1))', '![image](https://example.com/x)']) {
    assert.deepEqual(inline(text), [{ text, strong: false }])
  }
})

test('unmatched markers, CRLF and empty content remain stable', () => {
  assert.equal(inline('**열린 강조').map(p => p.text).join(''), '**열린 강조')
  assert.deepEqual(blocks(''), [])
  assert.deepEqual(blocks('### 제목\r\n\r\n- 사실').map(b => b.kind), ['heading', 'list'])
})
