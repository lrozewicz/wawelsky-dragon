import { describe, expect, it } from 'vitest'

import { fixtureDatasetDetail } from '../../../test/msw/handlers'
import type { Dataset } from '../queries'

import { buildConfigPatch, configSchema, datasetToValues } from './schema'
import type { ConfigValues } from './schema'

/** Szczegół datasetu z atrapy MSW, rzutowany na typ z kontraktu (podzbiór `DatasetDetail`). */
function makeDataset(overrides: Record<string, unknown> = {}): Dataset {
  return fixtureDatasetDetail(overrides) as unknown as Dataset
}

function valuesOf(dataset: Dataset): ConfigValues {
  return datasetToValues(dataset)
}

/** Pole metadanych w kształcie drutu — dokładnie to, co `fieldsToWire` wysyła w ciele PUT. */
const rokWire = { key: 'rok', type: 'string', description: null, enum: null }

describe('datasetToValues', () => {
  it('czyta parser_config z domyślnymi, gdy kluczy brak', () => {
    const dataset = makeDataset({ parser_config: {} })
    const values = valuesOf(dataset)

    expect(values).toEqual({
      name: 'Baza testowa',
      description: '',
      language: 'Polish',
      permission: 'me',
      embedding_model: 'fake-embd',
      chunk_method: 'naive',
      layout_recognize: 'DeepDOC',
      chunk_token_num: 512,
      delimiter: '\n',
      overlapped_percent: 0,
      html4excel: false,
      auto_keywords: 0,
      auto_questions: 0,
      llm_id: '',
      pages: [],
      enable_metadata: false,
    })
  })

  it('przepisuje wartości parser_config i nieznaną metodę sprowadza do General', () => {
    const dataset = makeDataset({
      description: 'Opis bazy',
      permission: 'team',
      chunk_method: 'tag',
      parser_config: {
        layout_recognize: 'Plain Text',
        chunk_token_num: 256,
        delimiter: ';',
        overlapped_percent: 10,
        html4excel: true,
        auto_keywords: 5,
        auto_questions: 2,
        llm_id: 'fake-llm',
      },
    })
    const values = valuesOf(dataset)

    expect(values.description).toBe('Opis bazy')
    expect(values.permission).toBe('team')
    expect(values.chunk_method).toBe('naive')
    expect(values.layout_recognize).toBe('Plain Text')
    expect(values.chunk_token_num).toBe(256)
    expect(values.delimiter).toBe(';')
    expect(values.overlapped_percent).toBe(10)
    expect(values.html4excel).toBe(true)
    expect(values.auto_keywords).toBe(5)
    expect(values.auto_questions).toBe(2)
    expect(values.llm_id).toBe('fake-llm')
  })

  it('null w opisie i brak parser_config nie wywracają odczytu', () => {
    const dataset = makeDataset({ description: null })
    const withoutConfig = { ...dataset, parser_config: null } as unknown as Dataset

    expect(valuesOf(withoutConfig).description).toBe('')
    expect(valuesOf(withoutConfig).chunk_token_num).toBe(512)
  })
})

describe('configSchema', () => {
  it('wymaga nazwy po trim', () => {
    const values = valuesOf(makeDataset())
    const result = configSchema.safeParse({ ...values, name: '   ' })

    expect(result.success).toBe(false)
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))).toEqual([
      'name',
    ])
    expect(result.success ? [] : result.error.issues.map((issue) => issue.message)).toEqual([
      'common.required',
    ])
    expect(configSchema.safeParse({ ...values, name: '  Baza  ' }).success).toBe(true)
  })

  it('pilnuje zakresów i limitu opisu', () => {
    const values = valuesOf(makeDataset())

    expect(configSchema.safeParse(values).success).toBe(true)
    expect(configSchema.safeParse({ ...values, description: 'x'.repeat(513) }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, chunk_token_num: 63 }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, chunk_token_num: 2049 }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, overlapped_percent: 31 }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, overlapped_percent: -1 }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, auto_keywords: 31 }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, auto_questions: 11 }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, chunk_method: 'tag' }).success).toBe(false)
    expect(configSchema.safeParse({ ...values, permission: 'all' }).success).toBe(false)
  })
})

describe('buildConfigPatch', () => {
  it('bez zmian zwraca pustą łatkę', () => {
    const dataset = makeDataset()
    const values = valuesOf(dataset)

    expect(buildConfigPatch(dataset, values)).toEqual({})
    // Spacje na brzegach nazwy nie są zmianą.
    expect(buildConfigPatch(dataset, { ...values, name: '  Baza testowa  ' })).toEqual({})
  })

  it('wysyła wyłącznie zmienione pola top-level', () => {
    const dataset = makeDataset()
    const values = valuesOf(dataset)
    const patch = buildConfigPatch(dataset, {
      ...values,
      name: 'Nowa nazwa',
      description: 'Nowy opis',
      chunk_method: 'qa',
    })

    expect(patch).toEqual({
      name: 'Nowa nazwa',
      description: 'Nowy opis',
      chunk_method: 'qa',
    })
  })

  it('scala parser_config z zachowaniem nieznanych kluczy', () => {
    const dataset = makeDataset({
      parser_config: { chunk_token_num: 128, delimiter: '\n', raptor: { use_raptor: true } },
    })
    const values = valuesOf(dataset)
    const patch = buildConfigPatch(dataset, {
      ...values,
      layout_recognize: 'VLM',
      auto_keywords: 7,
      html4excel: true,
    })

    expect(patch).toEqual({
      parser_config: {
        chunk_token_num: 128,
        delimiter: '\n',
        raptor: { use_raptor: true },
        layout_recognize: 'VLM',
        auto_keywords: 7,
        html4excel: true,
      },
    })
  })

  it('nie wysyła embedding_model przy istniejących chunkach', () => {
    const dataset = makeDataset({ chunk_count: 12 })
    const values = valuesOf(dataset)

    expect(buildConfigPatch(dataset, { ...values, embedding_model: 'other-embd' })).toEqual({})
  })

  it('wysyła embedding_model, gdy baza nie ma jeszcze chunków', () => {
    const dataset = makeDataset({ chunk_count: 0 })
    const values = valuesOf(dataset)

    expect(buildConfigPatch(dataset, { ...values, embedding_model: 'other-embd' })).toEqual({
      embedding_model: 'other-embd',
    })
  })

  it('pola akordeonu trafiają do parser_config, a nie na wierzch', () => {
    const dataset = makeDataset()
    const values = valuesOf(dataset)
    const patch = buildConfigPatch(dataset, {
      ...values,
      language: 'English',
      permission: 'team',
      chunk_token_num: 1024,
      delimiter: ';',
      overlapped_percent: 20,
      auto_questions: 3,
      llm_id: 'fake-llm',
    })

    expect(patch).toEqual({
      language: 'English',
      permission: 'team',
      parser_config: {
        chunk_token_num: 1024,
        delimiter: ';',
        overlapped_percent: 20,
        auto_questions: 3,
        llm_id: 'fake-llm',
      },
    })
  })

  it('enable_metadata trafia do parser_config tylko po zmianie', () => {
    const dataset = makeDataset()
    const values = valuesOf(dataset)

    expect(buildConfigPatch(dataset, values)).toEqual({})
    // parser_config jest zawsze scalony w całości (z kluczami z GET), zmiana tylko dopisuje.
    expect(buildConfigPatch(dataset, { ...values, enable_metadata: true })).toEqual({
      parser_config: { chunk_token_num: 128, delimiter: '\n', enable_metadata: true },
    })
  })

  it('zmieniona lista pól metadanych idzie do parser_config w kształcie drutu', () => {
    const dataset = makeDataset({
      parser_config: { chunk_token_num: 128, metadata: [rokWire] },
    })
    const values = valuesOf(dataset)

    // Ta sama lista (trim i kształt drutu) — bez pól metadanych w łatce.
    expect(buildConfigPatch(dataset, values, [{ key: 'rok', description: '', enum: [] }])).toEqual(
      {},
    )
    // Zmieniona lista — nowy kształt drutu w parser_config (kontrakt WP E6-1b §1).
    expect(
      buildConfigPatch(dataset, values, [{ key: 'rok', description: 'Rok', enum: [] }]),
    ).toEqual({
      parser_config: { chunk_token_num: 128, metadata: [{ ...rokWire, description: 'Rok' }] },
    })
  })

  it('metadata w łatce scala się z pozostałymi zmianami parser_config', () => {
    const dataset = makeDataset({ parser_config: { chunk_token_num: 128 } })
    const values = valuesOf(dataset)
    const patch = buildConfigPatch(dataset, { ...values, delimiter: ';' }, [
      { key: 'rok', description: '', enum: [] },
    ])

    expect(patch).toEqual({
      parser_config: {
        chunk_token_num: 128,
        delimiter: ';',
        metadata: [rokWire],
      },
    })
  })
})
