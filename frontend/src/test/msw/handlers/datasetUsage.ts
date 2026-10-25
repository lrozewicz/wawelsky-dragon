/**
 * Handler MSW powiązań bazy wiedzy (K20 §4): `GET /api/wd/v1/datasets/:datasetId/usage`.
 * Koperta WD: sukces `{data: DatasetUsage}`. Domyślnie puste powiązania — dialog usuwania na
 * ekranie listy nie wymaga danych; testy podmieniają stan przez `…datasetUsageHandlers(usage)`
 * albo rejestrują własny handler tej trasy (np. 500 dla stanu błędu).
 */

import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type { components } from '../../../api/schema.gen'
import { apiUrl } from './common'

export type FixtureDatasetUsage = components['schemas']['DatasetUsage']

export function fixtureDatasetUsage(
  overrides: Partial<FixtureDatasetUsage> = {},
): FixtureDatasetUsage {
  return {
    chats: [],
    searches: [],
    hidden_chats: 0,
    hidden_searches: 0,
    truncated: false,
    ...overrides,
  }
}

/** Pozycja listy powiązań (`UsageItem`): czat albo wyszukiwarka. */
export function fixtureUsageItem(name: string): FixtureDatasetUsage['chats'][number] {
  return { id: `usage-${name}`, name }
}

/** Handler trasy użycia zadaną odpowiedzią (wzór: `datasetsHandlers(items)`). */
export function datasetUsageHandlers(
  usage: FixtureDatasetUsage = fixtureDatasetUsage(),
): HttpHandler[] {
  return [
    http.get(apiUrl('/api/wd/v1/datasets/:datasetId/usage'), () =>
      HttpResponse.json({ data: usage }),
    ),
  ]
}
