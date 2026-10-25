/**
 * Czysta logika formularza modelu (brief E5-H8c T2, kontrakt WP E5-H8c §1): walidacja okna
 * kontekstu i równoległych zapytań oraz budowa ciała PATCH z PEŁNYM `extra` (K13 „Poprawka
 * 2026-10-10”). Przykłady wejście→wyjście przepisane dosłownie z briefu.
 */

import { describe, expect, it } from 'vitest'

import {
  buildModelPatch,
  CONCURRENCY_DEFAULTS,
  CONCURRENCY_MAX,
  CONCURRENCY_MIN,
  MIN_CONTEXT_WINDOW,
  supportsConcurrency,
  validateConcurrency,
  validateMaxTokens,
} from './modelForm'

describe('stałe (kontrakt §1)', () => {
  it('progi okna kontekstu i równoległości', () => {
    expect(MIN_CONTEXT_WINDOW).toBe(1024)
    expect(CONCURRENCY_MIN).toBe(1)
    expect(CONCURRENCY_MAX).toBe(32)
  })

  it('domyślne równoległości: vision/image2text 3, embedding 4', () => {
    expect(CONCURRENCY_DEFAULTS).toEqual({ vision: 3, image2text: 3, embedding: 4 })
  })
})

describe('supportsConcurrency', () => {
  it.each(['vision', 'image2text', 'embedding'])('typ %s obsługuje współbieżność', (modelType) => {
    expect(supportsConcurrency(modelType)).toBe(true)
  })

  it.each(['chat', 'rerank', '', 'asr'])('typ %s NIE obsługuje współbieżności', (modelType) => {
    expect(supportsConcurrency(modelType)).toBe(false)
  })
})

describe('validateMaxTokens', () => {
  it.each(['', 'abc', '1.5', '-5'])('„%s” → invalid', (value) => {
    expect(validateMaxTokens(value)).toBe('invalid')
  })

  it.each(['100', '1023'])('„%s” → min (poniżej 1024)', (value) => {
    expect(validateMaxTokens(value)).toBe('min')
  })

  it.each(['1024', '128000', ' 1024 '])('„%s” → null (poprawne)', (value) => {
    expect(validateMaxTokens(value)).toBeNull()
  })
})

describe('validateConcurrency', () => {
  it.each(['', '   '])('„%s” → null (domyślne)', (value) => {
    expect(validateConcurrency(value)).toBeNull()
  })

  it.each(['0', '33', '40', '1.5', 'x', '-1'])('„%s” → range', (value) => {
    expect(validateConcurrency(value)).toBe('range')
  })

  it.each(['1', '24', '32', ' 24 '])('„%s” → null (poprawne)', (value) => {
    expect(validateConcurrency(value)).toBeNull()
  })
})

describe('buildModelPatch (przykłady briefu)', () => {
  it('image2text: podmienia max_concurrency, nie gubi innych kluczy', () => {
    const patch = buildModelPatch(
      { model_type: 'image2text', extra: { supports_reasoning: true, max_concurrency: 3 } },
      { maxTokens: '8192', concurrency: '24' },
    )
    expect(patch).toEqual({
      max_tokens: 8192,
      extra: { supports_reasoning: true, max_concurrency: 24 },
    })
  })

  it('image2text: pusta współbieżność usuwa klucz, resztę extra zostawia', () => {
    const patch = buildModelPatch(
      { model_type: 'image2text', extra: { supports_reasoning: true, max_concurrency: 3 } },
      { maxTokens: '8192', concurrency: '' },
    )
    expect(patch).toEqual({ max_tokens: 8192, extra: { supports_reasoning: true } })
    expect('max_concurrency' in patch.extra).toBe(false)
  })

  it('chat: pole współbieżności ignorowane, extra bez zmian', () => {
    const patch = buildModelPatch(
      { model_type: 'chat', extra: { extra_body: { a: 1 } } },
      { maxTokens: '128000', concurrency: '7' },
    )
    expect(patch).toEqual({ max_tokens: 128000, extra: { extra_body: { a: 1 } } })
  })

  it('embedding z pustym extra: dokłada sam klucz max_concurrency', () => {
    const patch = buildModelPatch(
      { model_type: 'embedding', extra: {} },
      { maxTokens: '512', concurrency: '4' },
    )
    expect(patch).toEqual({ max_tokens: 512, extra: { max_concurrency: 4 } })
  })

  it('nie mutuje wejściowego extra i zwraca nowy obiekt', () => {
    const extra = { supports_reasoning: true, max_concurrency: 3 }
    const patch = buildModelPatch(
      { model_type: 'vision', extra },
      { maxTokens: '8192', concurrency: '8' },
    )
    expect(extra).toEqual({ supports_reasoning: true, max_concurrency: 3 })
    expect(patch.extra).not.toBe(extra)
    expect(patch.max_tokens).toBe(8192)
  })

  it('max_tokens jest liczbą (nie łańcuchem)', () => {
    const patch = buildModelPatch(
      { model_type: 'chat', extra: {} },
      { maxTokens: '2048', concurrency: '' },
    )
    expect(typeof patch.max_tokens).toBe('number')
    expect(patch.max_tokens).toBe(2048)
  })
})
