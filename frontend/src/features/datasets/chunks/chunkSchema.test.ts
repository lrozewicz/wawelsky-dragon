/**
 * Testy `chunkFormSchema` (kontrakt WP E3-4a §ChunkDialog): treść wymagana po `trim`, a wartość
 * po walidacji jest przycięta (to ją wysyła `ChunkDialog`). Puste listy i `available` przechodzą.
 */

import { describe, expect, it } from 'vitest'

import { chunkFormSchema } from './chunkSchema'
import type { ChunkFormValues } from './chunkSchema'

const base: ChunkFormValues = {
  content: 'abc',
  important_keywords: [],
  questions: [],
  available: true,
}

describe('chunkFormSchema', () => {
  it('poprawna treść przechodzi i wraca przycięta', () => {
    const result = chunkFormSchema.safeParse({ ...base, content: '  abc  ' })
    expect(result.success).toBe(true)
    expect(result.success && result.data.content).toBe('abc')
  })

  it('pusta treść to błąd z kluczem `chunks.dialog.contentRequired`', () => {
    const result = chunkFormSchema.safeParse({ ...base, content: '' })
    expect(result.success).toBe(false)
    expect(result.success === false && result.error.issues[0]?.message).toBe(
      'chunks.dialog.contentRequired',
    )
  })

  it('treść z samych spacji to błąd (trim przed sprawdzeniem długości)', () => {
    const result = chunkFormSchema.safeParse({ ...base, content: '   ' })
    expect(result.success).toBe(false)
  })

  it('listy słów kluczowych i pytań przechodzą razem z treścią', () => {
    const result = chunkFormSchema.safeParse({
      ...base,
      important_keywords: ['a', 'b'],
      questions: ['q?'],
      available: false,
    })
    expect(result.success).toBe(true)
    expect(result.success && result.data.important_keywords).toEqual(['a', 'b'])
    expect(result.success && result.data.questions).toEqual(['q?'])
    expect(result.success && result.data.available).toBe(false)
  })
})
