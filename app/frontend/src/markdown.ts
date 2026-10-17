// Deliberately limited Markdown: headings, bullet lists, quotes and **bold**.
// Text is rendered through Vue interpolation. No raw HTML, links or images.
export type Inline = { text: string; strong: boolean }
export type Block = { kind: 'heading' | 'list' | 'quote' | 'paragraph'; lines: Inline[][] }

function literal(text: string): string {
  return text.replace(/\\(.)/g, '$1')
}

export function inline(text: string): Inline[] {
  const parts: Inline[] = []
  let buffer = ''
  const flush = () => { if (buffer) { parts.push({ text: buffer, strong: false }); buffer = '' } }
  for (let i = 0; i < text.length;) {
    if (text[i] === '\\' && i + 1 < text.length) {
      buffer += text[i + 1]; i += 2; continue
    }
    if (text.startsWith('**', i)) {
      let end = i + 2
      while (end < text.length) {
        if (text[end] === '\\') { end += 2; continue }
        if (text.startsWith('**', end)) break
        end++
      }
      if (end < text.length && end > i + 2) {
        flush(); parts.push({ text: literal(text.slice(i + 2, end)), strong: true }); i = end + 2; continue
      }
    }
    buffer += text[i++]
  }
  flush()
  return parts
}

export function blocks(markdown: string): Block[] {
  const result: Block[] = []
  let current: Block | undefined
  for (const line of markdown.replace(/\r\n?/g, '\n').split('\n')) {
    if (!line.trim()) { current = undefined; continue }
    const heading = /^#{1,3} (.+)$/.exec(line)
    const kind: Block['kind'] = heading ? 'heading' : line.startsWith('- ') ? 'list' : line.startsWith('> ') ? 'quote' : 'paragraph'
    const text = heading ? heading[1]! : kind === 'list' || kind === 'quote' ? line.slice(2) : line
    if (!current || current.kind !== kind || kind === 'heading') {
      current = { kind, lines: [] }; result.push(current)
    }
    current.lines.push(inline(text))
  }
  return result
}
