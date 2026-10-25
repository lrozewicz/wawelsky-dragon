import { describe, expect, it } from 'vitest'

import { searchFixtureApp } from '../../../test/msw/handlers'
import { PRESET_VALUES } from '../../chats/settings/schema'

import { buildUpdateBody, searchSettingsSchema, toFormValues } from './schema'
import type { SearchSettingsValues } from './schema'

/** Wyszukiwarka z kluczami nieobsługiwanymi przez UI — muszą przeżyć zapis (kontrakt §2). */
function makeValues(): SearchSettingsValues {
  return toFormValues(searchFixtureApp)
}

function issuePaths(values: SearchSettingsValues): string[] {
  const result = searchSettingsSchema.safeParse(values)
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
}

function issueMessages(values: SearchSettingsValues): string[] {
  const result = searchSettingsSchema.safeParse(values)
  return result.success ? [] : result.error.issues.map((issue) => issue.message)
}

describe('toFormValues', () => {
  it('czyta pola search_config z fixture wyszukiwarki', () => {
    expect(toFormValues(searchFixtureApp)).toMatchObject({
      name: 'Wyszukiwarka testowa',
      kbIds: ['ds-1'],
      summary: true,
      llmId: 'fake-chat',
      preset: 'precise',
      relatedSearch: true,
      similarityThreshold: 0.2,
      vectorSimilarityWeight: 0.3,
      useRerank: false,
      rerankId: '',
    })
  })

  it('pusty search_config dostaje domyślne', () => {
    const values = toFormValues({ ...searchFixtureApp, search_config: {} })

    expect(values).toMatchObject({
      kbIds: [],
      summary: false,
      llmId: '',
      preset: 'precise',
      relatedSearch: false,
      similarityThreshold: 0.2,
      vectorSimilarityWeight: 0.3,
      useRerank: false,
      rerankId: '',
    })
  })

  it('niepuste rerank_id włącza model rerank', () => {
    const values = toFormValues({
      ...searchFixtureApp,
      search_config: { ...searchFixtureApp.search_config, rerank_id: 'fake-rerank' },
    })

    expect(values.useRerank).toBe(true)
    expect(values.rerankId).toBe('fake-rerank')
  })

  it('nieznany preset spada na Precyzję', () => {
    const values = toFormValues({
      ...searchFixtureApp,
      search_config: {
        ...searchFixtureApp.search_config,
        llm_setting: { parameter: 'nieznany' },
      },
    })

    expect(values.preset).toBe('precise')
  })

  it('meta_data_filter czytany przez filterFromWire: brak → wyłączony, ręczny → warunki (E6-1b)', () => {
    expect(toFormValues(searchFixtureApp).metaDataFilter).toEqual({
      method: 'off',
      logic: 'and',
      manual: [],
      semi_auto: [],
    })

    const wire = {
      method: 'manual',
      logic: 'and',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    }
    const values = toFormValues({
      ...searchFixtureApp,
      search_config: { ...searchFixtureApp.search_config, meta_data_filter: wire },
    })
    expect(values.metaDataFilter).toEqual({
      method: 'manual',
      logic: 'and',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
      semi_auto: [],
    })
  })
})

describe('buildUpdateBody', () => {
  it('nadpisuje kb_ids i zachowuje nieznane klucze search_config', () => {
    const body = buildUpdateBody({ ...makeValues(), kbIds: ['a', 'b'] }, searchFixtureApp)

    expect(body.name).toBe('Wyszukiwarka testowa')
    expect(body.search_config.kb_ids).toEqual(['a', 'b'])
    expect(body.search_config.use_kg).toBe(false)
    expect(body.search_config.chat_id).toBe('fake-chat')
    expect(body.search_config.related_search).toBe(true)
  })

  it('meta_data_filter idzie do search_config: ręczny → warunki, wyłączony → `{}` (E6-1b)', () => {
    const manual = {
      ...makeValues(),
      metaDataFilter: {
        method: 'manual' as const,
        logic: 'and' as const,
        manual: [{ key: 'typ', op: '=' as const, value: 'raport' }],
        semi_auto: [],
      },
    }
    expect(buildUpdateBody(manual, searchFixtureApp).search_config.meta_data_filter).toEqual({
      method: 'manual',
      logic: 'and',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
    expect(buildUpdateBody(makeValues(), searchFixtureApp).search_config.meta_data_filter).toEqual(
      {},
    )
  })

  it('zachowuje top_k, web_search i llm_setting.thinking', () => {
    const current = {
      ...searchFixtureApp,
      search_config: {
        ...searchFixtureApp.search_config,
        top_k: 42,
        web_search: true,
        llm_setting: { parameter: 'precise', thinking: true },
      },
    }
    const values: SearchSettingsValues = {
      ...makeValues(),
      kbIds: ['ds-1'],
      summary: false,
      preset: 'balance',
    }

    const body = buildUpdateBody(values, current)

    expect(body.search_config.top_k).toBe(42)
    expect(body.search_config.web_search).toBe(true)
    expect(body.search_config.use_kg).toBe(false)
    expect(body.search_config.summary).toBe(false)
    expect(body.search_config.llm_setting).toMatchObject({
      thinking: true,
      parameter: 'balance',
      temperature: PRESET_VALUES.balance.temperature,
      top_p: PRESET_VALUES.balance.top_p,
    })
  })

  it('useRerank wyłącza model rerank pustym rerank_id', () => {
    const values = makeValues()

    expect(
      buildUpdateBody({ ...values, useRerank: false, rerankId: 'fake-rerank' }, searchFixtureApp)
        .search_config.rerank_id,
    ).toBe('')
    expect(
      buildUpdateBody({ ...values, useRerank: true, rerankId: 'fake-rerank' }, searchFixtureApp)
        .search_config.rerank_id,
    ).toBe('fake-rerank')
  })
})

describe('searchSettingsSchema', () => {
  it('nazwa wymagana po trim', () => {
    expect(issuePaths({ ...makeValues(), name: '   ' })).toEqual(['name'])
    expect(issueMessages({ ...makeValues(), name: '   ' })).toEqual([
      'searches.settings.nameRequired',
    ])
    expect(searchSettingsSchema.safeParse({ ...makeValues(), name: '  Alfa  ' }).success).toBe(true)
  })

  it('wymaga co najmniej jednej bazy wiedzy', () => {
    expect(issuePaths({ ...makeValues(), kbIds: [] })).toEqual(['kbIds'])
    expect(issueMessages({ ...makeValues(), kbIds: [] })).toEqual([
      'searches.settings.kbIdsRequired',
    ])
  })

  it('podsumowanie bez modelu wskazuje llmId', () => {
    expect(issuePaths({ ...makeValues(), summary: true, llmId: '' })).toEqual(['llmId'])
    expect(issueMessages({ ...makeValues(), summary: true, llmId: '' })).toEqual([
      'searches.settings.llmRequired',
    ])
  })

  it('bez podsumowania pusty model jest dozwolony', () => {
    expect(
      searchSettingsSchema.safeParse({ ...makeValues(), summary: false, llmId: '' }).success,
    ).toBe(true)
  })

  it('liczby spoza zakresu 0..1 są błędem', () => {
    expect(issuePaths({ ...makeValues(), similarityThreshold: 1.5 })).toEqual([
      'similarityThreshold',
    ])
    expect(issuePaths({ ...makeValues(), vectorSimilarityWeight: -0.1 })).toEqual([
      'vectorSimilarityWeight',
    ])
  })
})
