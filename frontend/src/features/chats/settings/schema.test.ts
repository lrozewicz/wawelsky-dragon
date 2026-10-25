import { describe, expect, it } from 'vitest'

import { chatDetail } from '../../../test/msw/handlers'

import { buildModelOptions } from '../modelsQuery'

import {
  applyPreset,
  buildPatch,
  chatSettingsSchema,
  chatToFormValues,
  PRESET_MAX_TOKENS,
  PRESET_VALUES,
} from './schema'
import type { ChatSettingsValues } from './schema'

/** Czat z nieznanymi kluczami prompt_config/llm_setting — muszą przetrwać zapis (08 §8.2). */
function makeValues(): ChatSettingsValues {
  return chatToFormValues(
    chatDetail({
      name: 'Alfa',
      description: 'Opis',
      dataset_ids: [],
      llm_setting: { thinking: true, parameter: 'precise' },
    }),
  )
}

function issuePaths(values: ChatSettingsValues): string[] {
  const result = chatSettingsSchema.safeParse(values)
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
}

function issueMessages(values: ChatSettingsValues): string[] {
  const result = chatSettingsSchema.safeParse(values)
  return result.success ? [] : result.error.issues.map((issue) => issue.message)
}

describe('chatSettingsSchema — nazwa', () => {
  it('nazwa wymagana po trim', () => {
    const values = makeValues()

    expect(issuePaths({ ...values, name: '   ' })).toEqual(['name'])
    expect(issueMessages({ ...values, name: '   ' })).toEqual(['chat.settings.nameRequired'])
    expect(chatSettingsSchema.safeParse({ ...values, name: '  Alfa  ' }).success).toBe(true)
  })
})

describe('chatSettingsSchema — {knowledge}', () => {
  it('bez baz wiedzy prompt systemowy nie musi zawierać {knowledge}', () => {
    const values = makeValues()

    expect(values.dataset_ids).toEqual([])
    expect(
      chatSettingsSchema.safeParse({
        ...values,
        prompt_config: { ...values.prompt_config, system: 'Jesteś asystentem.' },
      }).success,
    ).toBe(true)
  })

  it('z bazami wiedzy wymaga {knowledge} w promptcie i wskazuje pole', () => {
    const values = makeValues()
    const withDatasets: ChatSettingsValues = {
      ...values,
      dataset_ids: ['ds-1'],
      prompt_config: { ...values.prompt_config, system: 'Jesteś asystentem.' },
    }

    expect(issuePaths(withDatasets)).toEqual(['prompt_config.system'])
    expect(issueMessages(withDatasets)).toEqual(['chat.settings.systemKnowledge'])
  })

  it('z bazami wiedzy i {knowledge} przechodzi', () => {
    const values = makeValues()
    const withDatasets: ChatSettingsValues = {
      ...values,
      dataset_ids: ['ds-1'],
      prompt_config: { ...values.prompt_config, system: 'Odpowiadaj z {knowledge}.' },
    }

    expect(chatSettingsSchema.safeParse(withDatasets).success).toBe(true)
  })
})

describe('buildPatch', () => {
  it('brak zmian → pusta łatka', () => {
    const initial = makeValues()

    expect(buildPatch(initial, makeValues())).toEqual({})
  })

  it('spacje w nazwie nie są zmianą; realna zmiana wysyła nazwę po trim', () => {
    const initial = makeValues()

    expect(buildPatch(initial, { ...initial, name: '  Alfa  ' })).toEqual({})
    expect(buildPatch(initial, { ...initial, name: '  Beta  ' })).toEqual({ name: 'Beta' })
  })

  it('zmiana opisu wysyła tylko opis', () => {
    const initial = makeValues()

    expect(buildPatch(initial, { ...initial, description: 'Nowy opis' })).toEqual({
      description: 'Nowy opis',
    })
  })

  it('zmiana prologue wysyła pełny prompt_config ze starymi kluczami', () => {
    const initial = makeValues()
    const patch = buildPatch(initial, {
      ...initial,
      prompt_config: { ...initial.prompt_config, prologue: 'Cześć!' },
    })

    expect(Object.keys(patch)).toEqual(['prompt_config'])
    expect(patch.prompt_config).toMatchObject({
      prologue: 'Cześć!',
      tts: false,
      parameters: [
        { key: 'knowledge', optional: false },
        { key: 'date', optional: true },
      ],
    })
  })

  it('zmiana suwaka wysyła pełny llm_setting z nieznanym kluczem', () => {
    const initial = makeValues()
    const patch = buildPatch(initial, {
      ...initial,
      llm_setting: { ...initial.llm_setting, temperature: 0.9 },
    })

    expect(Object.keys(patch)).toEqual(['llm_setting'])
    expect(patch.llm_setting).toMatchObject({ thinking: true, temperature: 0.9 })
  })

  it('zmiana baz wiedzy i modelu trafia do łatki', () => {
    const initial = makeValues()
    const patch = buildPatch(initial, { ...initial, dataset_ids: ['ds-1'], llm_id: 'inny-llm' })

    expect(patch).toEqual({ dataset_ids: ['ds-1'], llm_id: 'inny-llm' })
  })

  it('kolejność baz wiedzy jest zmianą', () => {
    const initial: ChatSettingsValues = { ...makeValues(), dataset_ids: ['a', 'b'] }

    expect(buildPatch(initial, { ...initial, dataset_ids: ['b', 'a'] })).toEqual({
      dataset_ids: ['b', 'a'],
    })
  })
})

describe('presety kreatywności', () => {
  const base = makeValues().llm_setting

  it('Improwizacja ustawia 0.8 / 0.9 / 0.1 / 0.1 i max_tokens 4096', () => {
    expect(applyPreset('improvise', base)).toMatchObject({
      parameter: 'improvise',
      temperature: 0.8,
      top_p: 0.9,
      presence_penalty: 0.1,
      frequency_penalty: 0.1,
      max_tokens: PRESET_MAX_TOKENS,
    })
  })

  it('Precyzja ustawia 0.2 / 0.75 / 0.5 / 0.5', () => {
    expect(applyPreset('precise', base)).toMatchObject({
      parameter: 'precise',
      temperature: 0.2,
      top_p: 0.75,
      presence_penalty: 0.5,
      frequency_penalty: 0.5,
    })
  })

  it('Balans ustawia 0.5 / 0.85 / 0.3 / 0.2', () => {
    expect(applyPreset('balance', base)).toMatchObject({
      parameter: 'balance',
      temperature: 0.5,
      top_p: 0.85,
      presence_penalty: 0.3,
      frequency_penalty: 0.2,
    })
  })

  it('Własne zachowuje wartości suwaków', () => {
    const custom = applyPreset('custom', { ...base, temperature: 0.42 })

    expect(custom.parameter).toBe('custom')
    expect(custom.temperature).toBe(0.42)
  })

  it('tabela presetów zgadza się z 08 §8.2', () => {
    expect(PRESET_VALUES).toEqual({
      improvise: { temperature: 0.8, top_p: 0.9, presence_penalty: 0.1, frequency_penalty: 0.1 },
      precise: { temperature: 0.2, top_p: 0.75, presence_penalty: 0.5, frequency_penalty: 0.5 },
      balance: { temperature: 0.5, top_p: 0.85, presence_penalty: 0.3, frequency_penalty: 0.2 },
    })
  })
})

describe('chatToFormValues', () => {
  it('braki w czacie dostają domyślne z 08 §8.2', () => {
    const values = chatToFormValues(
      chatDetail({ prompt_config: {}, llm_setting: {}, rerank_id: '', top_n: 8 }),
    )

    expect(values.prompt_config.quote).toBe(true)
    expect(values.prompt_config.keyword).toBe(false)
    expect(values.prompt_config.system).toBe('')
    expect(values.llm_setting.parameter).toBe('precise')
    expect(values.llm_setting.temperature).toBe(0.2)
    expect(values.similarity_threshold).toBe(0.1)
  })

  it('nieznany preset spada na Precyzję', () => {
    const values = chatToFormValues(chatDetail({ llm_setting: { parameter: 'nieznany' } }))

    expect(values.llm_setting.parameter).toBe('precise')
  })
})

describe('buildModelOptions', () => {
  it('bierze tylko modele czatu, etykietą jest nazwa, wartością model_id', () => {
    const models = [
      { model_id: 'id-chat', name: 'fake-chat', model_type: ['chat'] },
      { model_id: 'id-embd', name: 'fake-embed-1024', model_type: ['embedding'] },
      { model_id: 'id-chat-2', name: 'other-chat', model_type: ['chat'] },
    ]

    expect(buildModelOptions(models, 'id-chat', 'id-chat')).toEqual([
      { id: 'id-chat', label: 'fake-chat' },
      { id: 'id-chat-2', label: 'other-chat' },
    ])
  })

  it('id spoza listy pokazuje samo siebie (etykieta = id), bez duplikatów', () => {
    const models = [{ model_id: 'id-chat', name: 'fake-chat', model_type: ['chat'] }]

    expect(buildModelOptions(models, 'ghost', 'id-chat')).toEqual([
      { id: 'id-chat', label: 'fake-chat' },
      { id: 'ghost', label: 'ghost' },
    ])
  })

  it('gdy /models zawiedzie (pusto), zostaje model bieżący i domyślny', () => {
    expect(buildModelOptions([], 'cur', 'def')).toEqual([
      { id: 'cur', label: 'cur' },
      { id: 'def', label: 'def' },
    ])
    expect(buildModelOptions([], '', '')).toEqual([])
  })

  it('domyślny z users/me/models to nazwa — bez duplikatu, gdy rejestr zna ten model', () => {
    const models = [{ model_id: 'id-chat', name: 'fake-chat', model_type: ['chat'] }]

    // Etykieta 'fake-chat' już jest z wartością model_id — nazwy nie dokładamy drugi raz.
    expect(buildModelOptions(models, '', 'fake-chat')).toEqual([
      { id: 'id-chat', label: 'fake-chat' },
    ])
  })

  it('powtórzony model_id i model bez typu chat nie wchodzą dwa razy', () => {
    const models = [
      { model_id: 'id-chat', name: 'fake-chat', model_type: ['chat'] },
      { model_id: 'id-chat', name: 'fake-chat-2', model_type: ['chat'] },
      { model_id: 'id-rerank', name: 'fake-rerank', model_type: ['rerank'] },
    ]

    expect(buildModelOptions(models, '', '')).toEqual([{ id: 'id-chat', label: 'fake-chat' }])
  })
})
