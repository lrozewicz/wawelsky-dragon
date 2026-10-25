export type CitationSegment = { type: 'text'; text: string } | { type: 'citation'; index: number }

type CodeSpan = { text: string; code: boolean }

// Dopisuje tekst, scalamy go z poprzednim segmentem tekstowym (kontrakt §4).
function pushText(segments: CitationSegment[], text: string): void {
  if (text === '') return
  const last = segments.at(-1)
  if (last !== undefined && last.type === 'text') {
    last.text += text
    return
  }
  segments.push({ type: 'text', text })
}

// Rozbija tekst na fragmenty prozy i kodu: blok ``` … ``` oraz inline `…`.
// Niedomknięty blok/kod inline ciągnie się do końca tekstu.
function splitCode(text: string): CodeSpan[] {
  const spans: CodeSpan[] = []
  const backticks = /`+/g
  let open: string | null = null
  let start = 0
  let match = backticks.exec(text)
  while (match !== null) {
    const delimiter = text.slice(match.index, backticks.lastIndex)
    if (open === null) {
      if (match.index > start) spans.push({ text: text.slice(start, match.index), code: false })
      open = delimiter
      start = match.index
    } else if (delimiter === open) {
      spans.push({ text: text.slice(start, backticks.lastIndex), code: true })
      open = null
      start = backticks.lastIndex
    }
    match = backticks.exec(text)
  }
  if (open === null) {
    if (start < text.length) spans.push({ text: text.slice(start), code: false })
  } else {
    spans.push({ text: text.slice(start), code: true })
  }
  return spans
}

// Znaczniki w prozie zamienia na segmenty cytowań; poza zakresem chunków — usuwa z tekstu.
function tokenizeProse(segments: CitationSegment[], text: string, chunkCount: number): void {
  const marker = /\[ID:(\d+)\]/g
  let last = 0
  let match = marker.exec(text)
  while (match !== null) {
    pushText(segments, text.slice(last, match.index))
    const index = Number(match[1])
    if (index < chunkCount) segments.push({ type: 'citation', index })
    last = marker.lastIndex
    match = marker.exec(text)
  }
  pushText(segments, text.slice(last))
}

export function tokenizeCitations(text: string, chunkCount: number): CitationSegment[] {
  const segments: CitationSegment[] = []
  for (const span of splitCode(text)) {
    if (span.code) pushText(segments, span.text)
    else tokenizeProse(segments, span.text, chunkCount)
  }
  return segments
}
