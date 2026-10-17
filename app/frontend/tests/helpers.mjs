import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, nextTick } from 'vue'

const dataUrl = js => 'data:text/javascript;base64,' + Buffer.from(js).toString('base64')
const transpile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
export const apiModuleUrl = dataUrl(transpile(await readFile(new URL('../src/api.ts', import.meta.url), 'utf8')))
export const timingModuleUrl = dataUrl(transpile(await readFile(new URL('../src/queueTiming.ts', import.meta.url), 'utf8')))
const formatUrl = dataUrl(transpile(await readFile(new URL('../src/format.ts', import.meta.url), 'utf8')))

export async function component(name, stubs = {}) {
  const source = await readFile(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: name + '.vue' })
  let js = transpile(compileScript(descriptor, { id: name, inlineTemplate: true }).content)
  js = js.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]\.\.\/api['"]/g, `from '${apiModuleUrl}'`)
    .replace(/from ['"]\.\.\/format['"]/g, `from '${formatUrl}'`)
    .replace(/from ['"]\.\.\/queueTiming['"]/g, `from '${timingModuleUrl}'`)
    .replace(/import (\w+) from ['"]\.\/(\w+)\.vue['"];?/g, (_, binding, child) => `const ${binding} = globalThis.__queueStubs['${child}'];`)
  globalThis.__queueStubs = { QueueMeasurement: { render: () => null }, ...stubs }
  return (await import(dataUrl(js))).default
}

// Vue's real runtime with an in-memory host: no browser, DOM dependency or AI.
export function mount(component, props) {
  const node = (type, text = '') => ({ type, text, children: [], props: {}, parent: null,
    tagName: type.toUpperCase(), addEventListener() {}, removeEventListener() {},
    get options() { return this.children.filter(c => c.type === 'option') } })
  const renderer = createRenderer({
    createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text; n.children = [] },
    parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
    patchProp: (n, key, _, value) => { n.props[key] = value; if (key === 'value') n._value = value },
    insert(n, parent, anchor = null) {
      if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, n); n.parent = parent
    },
    remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1) },
  })
  const root = node('root')
  const app = renderer.createApp(component, props)
  app.mount(root)
  const all = (n = root) => [n, ...n.children.flatMap(c => all(c))]
  const text = (n = root) => n.type === '#comment' ? '' : n.text + n.children.map(c => text(c)).join('')
  return { root, all, text, close: () => app.unmount() }
}
export async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
