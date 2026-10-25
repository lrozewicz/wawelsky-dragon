/**
 * Test zgodności szablonu promptu z backendem (kontrakt WP E5-H6e C2): `DEFAULT_SYSTEM_PROMPT`
 * musi być DOSŁOWNIE tekstem `DEFAULT_PROMPT_CONFIG["system"]` z
 * `backend/app/domain/chat/config.py` — inaczej UI wypełniałby czat innym promptem niż domyślny
 * backendu. Cwd vitestu to katalog frontendu (wzór: `src/api/schema.test.ts`).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { DEFAULT_SYSTEM_PROMPT } from './defaultPrompt'

const CONFIG_PATH = join(process.cwd(), '..', 'backend', 'app', 'domain', 'chat', 'config.py')

/** Rozwija escape'y Pythona z literału (`\n`, `\"`, `\\`) — tyle wystarcza dla tego bloku. */
function unescapeLiteral(literal: string): string {
  return literal.replace(/\\([\s\S])/g, (_match, char: string) => {
    if (char === 'n') return '\n'
    if (char === 't') return '\t'
    if (char === 'r') return '\r'
    return char
  })
}

/**
 * Wartość `"system"` z `DEFAULT_PROMPT_CONFIG`: wyciąga blok nawiasu i skleja jego literały
 * (Pythona robi to samo w czasie importu — sąsiednie stringi łączą się w jeden).
 */
function backendSystemPrompt(source: string): string {
  const block = /DEFAULT_PROMPT_CONFIG[\s\S]*?"system": \(\s*([\s\S]*?)\n\s*\),/.exec(source)
  expect(block, 'blok "system" w DEFAULT_PROMPT_CONFIG').not.toBeNull()
  const literals = ((block as RegExpExecArray)[1] ?? '').matchAll(
    /"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'/g,
  )
  return [...literals].map((match) => unescapeLiteral(match[1] ?? match[2] ?? '')).join('')
}

describe('DEFAULT_SYSTEM_PROMPT', () => {
  it('zawiera {knowledge} i zaczyna się własnym tekstem WD', () => {
    expect(DEFAULT_SYSTEM_PROMPT).toContain('{knowledge}')
    expect(
      DEFAULT_SYSTEM_PROMPT.startsWith('You are an assistant grounded in the dataset below'),
    ).toBe(true)
  })

  it('jest dosłownie równy DEFAULT_PROMPT_CONFIG["system"] z backendu', () => {
    const expected = backendSystemPrompt(readFileSync(CONFIG_PATH, 'utf8'))

    expect(expected.length).toBeGreaterThan(0)
    expect(DEFAULT_SYSTEM_PROMPT).toBe(expected)
  })
})
