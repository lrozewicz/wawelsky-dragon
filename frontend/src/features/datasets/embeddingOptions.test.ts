import { describe, expect, it } from 'vitest'

import { fixtureModel } from '../../test/msw/handlers'

import { buildEmbeddingOptions } from './embeddingOptions'

// Rejestr jak w złocie `system--11.json`: model czatu i dwa modele embeddingu.
const embedding = (modelId: string, name: string) =>
  fixtureModel({ model_id: modelId, name, model_type: ['embedding'] })

describe('buildEmbeddingOptions', () => {
  it('bierze tylko modele embeddingu i domyślny wskazuje po nazwie', () => {
    const result = buildEmbeddingOptions(
      [fixtureModel(), embedding('embd-1', 'fake-embd'), embedding('embd-2', 'other-embd')],
      'other-embd',
    )

    expect(result.options).toEqual([
      { id: 'embd-1', label: 'fake-embd' },
      { id: 'embd-2', label: 'other-embd' },
    ])
    expect(result.defaultId).toBe('embd-2')
  })

  it('brak dopasowania po nazwie → pierwsza opcja', () => {
    const result = buildEmbeddingOptions(
      [embedding('embd-1', 'fake-embd'), embedding('embd-2', 'other-embd')],
      'nie-ma-takiego',
    )

    expect(result.defaultId).toBe('embd-1')
  })

  it('pusta lista modeli → puste opcje i pusty identyfikator', () => {
    expect(buildEmbeddingOptions([], 'fake-embd')).toEqual({ options: [], defaultId: '' })
  })

  it('same modele nie-embeddingowe → puste opcje i pusty identyfikator', () => {
    expect(buildEmbeddingOptions([fixtureModel()], 'fake-chat')).toEqual({
      options: [],
      defaultId: '',
    })
  })
})
