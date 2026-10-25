// Zakresy stron `parser_config.pages` (§T4, SC-E5-H9-05): odczyt, walidacja pustych wierszy
// i łotka PUT. Wydzielone z `schema.test.ts` przez limit rozmiaru pliku (wzór: fields.tsx).
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

describe('zakresy stron w schemacie konfiguracji', () => {
  it('przepisuje zakresy stron, a wpisy złego kształtu pomija', () => {
    const withPages = valuesOf(
      makeDataset({
        parser_config: {
          pages: [
            [2, 2],
            [4, 9],
          ],
        },
      }),
    )
    expect(withPages.pages).toEqual([
      [2, 2],
      [4, 9],
    ])

    const malformed = valuesOf(
      makeDataset({ parser_config: { pages: [[2, 2], ['x', 3], 7] as unknown } }),
    )
    expect(malformed.pages).toEqual([[2, 2]])
  })

  it('wiersz zakresu pusty w całości przepuszcza, a półpełny daje errorIncomplete', () => {
    const values = valuesOf(makeDataset())

    // Pusty wiersz jest pomijany przy zapisie — walidacja go nie odrzuca.
    expect(configSchema.safeParse({ ...values, pages: [[null, null]] }).success).toBe(true)

    // Wypełnione tylko „Od” albo tylko „Do” — błąd pod edytorem, zapis zablokowany.
    const partial = configSchema.safeParse({ ...values, pages: [[2, null]] })
    expect(partial.success).toBe(false)
    expect(partial.success ? [] : partial.error.issues.map((issue) => issue.message)).toEqual([
      'datasets.config.pages.errorIncomplete',
    ])
    expect(configSchema.safeParse({ ...values, pages: [[null, 2]] }).success).toBe(false)
  })

  it('zmianę zakresów stron wysyła do parser_config, a nie na wierzch', () => {
    const dataset = makeDataset({ parser_config: { chunk_token_num: 128, delimiter: '\n' } })
    const values = valuesOf(dataset)
    const patch = buildConfigPatch(dataset, {
      ...values,
      layout_recognize: 'fake-vision',
      pages: [[2, 2]],
    })

    expect(patch).toEqual({
      parser_config: {
        chunk_token_num: 128,
        delimiter: '\n',
        layout_recognize: 'fake-vision',
        pages: [[2, 2]],
      },
    })
  })

  it('bez zmiany zakresów nie wysyła ich (porównanie zawartości, nie referencji)', () => {
    const dataset = makeDataset({ parser_config: { pages: [[2, 2]] } })
    const values = valuesOf(dataset)

    expect(buildConfigPatch(dataset, { ...values, pages: [[2, 2]] })).toEqual({})
  })

  it('niewypełniony wiersz zakresu pomija (SC-E5-H9-05, bez ukrytego „1-1”)', () => {
    const dataset = makeDataset()
    const values = valuesOf(dataset)

    // Sam pusty wiersz = brak zmiany → pusta łatka (przycisk „Zapisz” nieaktywny).
    expect(buildConfigPatch(dataset, { ...values, pages: [[null, null]] })).toEqual({})

    // Obok pustego wiersza realna zmiana: `parser_config` (scalony w całości) niesie
    // wyłącznie pełne zakresy — `null` nie trafia do łatki.
    expect(
      buildConfigPatch(dataset, {
        ...values,
        pages: [
          [null, null],
          [2, 2],
        ],
      }),
    ).toEqual({
      parser_config: { chunk_token_num: 128, delimiter: '\n', pages: [[2, 2]] },
    })
  })

  it('wyczyszczenie zakresów wysyła puste `pages` do parser_config', () => {
    const dataset = makeDataset({ parser_config: { chunk_token_num: 128, pages: [[2, 2]] } })
    const values = valuesOf(dataset)
    const patch = buildConfigPatch(dataset, { ...values, pages: [] })

    expect(patch).toEqual({
      parser_config: { chunk_token_num: 128, pages: [] },
    })
  })
})
