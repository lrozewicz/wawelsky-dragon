// Kontrakt WP E3-5a §2: rozdzielenie bloku `<think>…</think>` od odpowiedzi.
const CLOSED_THINK = /^\s*<think>([\s\S]*?)<\/think>\s*([\s\S]*)$/
const OPEN_THINK = /^\s*<think>/

/**
 * Rozbija tekst na część myślenia i część odpowiedzi.
 * Niedomknięty `<think>` na początku tekstu oznacza trwające myślenie (cały tekst do `thinking`).
 */
export function splitThink(text: string): { thinking: string; answer: string } {
  const match = CLOSED_THINK.exec(text)
  if (match !== null) {
    const [, thinking = '', answer = ''] = match
    return { thinking: thinking.trim(), answer }
  }
  if (OPEN_THINK.test(text)) {
    return { thinking: text.replace(OPEN_THINK, '').trim(), answer: '' }
  }
  return { thinking: '', answer: text }
}
