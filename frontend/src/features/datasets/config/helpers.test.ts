/**
 * Testy `configSaveReason` (SC-V12-08): powód wyłącznego „Zapisz” — brak zmian, błąd klucza
 * metadanych, a przy aktywnym przycisku (zmiany bez błędów) — brak tekstu. Prawdziwy i18next
 * (wzór: `errorText.test.ts`) — asercje na pełnych tekstach z interpolacją {{field}}.
 */

import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { configSaveReason } from './helpers'

const plMessages: Record<string, string> = {
  'common.noChangesToSave': 'Brak zmian do zapisania',
  'datasets.config.reason.fixField': 'Popraw: {{field}}',
  'datasets.config.metadata.key': 'Klucz',
}

async function createT(): Promise<TFunction> {
  const instance = i18next.createInstance()
  await instance.init({
    lng: 'pl',
    fallbackLng: 'pl',
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    resources: { pl: { translation: plMessages } },
  })
  return instance.t
}

let t: TFunction

beforeAll(async () => {
  t = await createT()
})

describe('configSaveReason', () => {
  it('brak zmian → „Brak zmian do zapisania”, niezależnie od błędów metadanych', () => {
    expect(configSaveReason(t, true, false)).toBe('Brak zmian do zapisania')
    expect(configSaveReason(t, true, true)).toBe('Brak zmian do zapisania')
  })

  it('zmiany z błędem klucza metadanych → „Popraw: Klucz”', () => {
    expect(configSaveReason(t, false, true)).toBe('Popraw: Klucz')
  })

  it('zmiany bez błędów → przycisk aktywny, powodu brak', () => {
    expect(configSaveReason(t, false, false)).toBeNull()
  })
})
