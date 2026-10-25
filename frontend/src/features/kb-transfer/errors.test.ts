import { describe, expect, it } from 'vitest'

import { KB_ERROR_SLUGS, kbErrorMessageKey, kbPackageErrorOverrideKey } from './errors'

type Locale = Record<string, string>

const plModules = import.meta.glob<Locale>('../../locales/pl/*.json', {
  eager: true,
  import: 'default',
})
const enModules = import.meta.glob<Locale>('../../locales/en/*.json', {
  eager: true,
  import: 'default',
})

function merge(modules: Record<string, Locale>): Locale {
  return Object.assign({}, ...Object.values(modules))
}

const pl = merge(plModules)
const en = merge(enModules)

/** Slugi z tabeli kodów K19 §3 (`not_a_package` dopisany K20 §2) i błędy walidacji paczki. */
const K19_SLUGS = [
  'validation_failed',
  'forbidden',
  'invalid_signature',
  'not_found',
  'export_in_progress',
  'offset_mismatch',
  'import_not_ready',
  'name_conflict',
  'embedding_model_required',
  'embedding_model_unknown',
  'export_expired',
  'package_too_large',
  'not_a_package',
  'invalid_archive',
  'manifest_invalid',
  'schema_too_new',
  'unsafe_path',
  'archive_too_large',
  'checksum_mismatch',
  'missing_entry',
  'unexpected_entry',
  'dimension_mismatch',
]

describe('kbErrorMessageKey', () => {
  it('znany slug K19 mapuje na kbTransfer.error.<slug>', () => {
    expect(kbErrorMessageKey('checksum_mismatch')).toBe('kbTransfer.error.checksum_mismatch')
    expect(kbErrorMessageKey('export_in_progress')).toBe('kbTransfer.error.export_in_progress')
    expect(kbErrorMessageKey('dimension_mismatch')).toBe('kbTransfer.error.dimension_mismatch')
  })

  it('nieznany kod mapuje na kbTransfer.error.unknown', () => {
    expect(kbErrorMessageKey('zzz')).toBe('kbTransfer.error.unknown')
    expect(kbErrorMessageKey('')).toBe('kbTransfer.error.unknown')
    expect(kbErrorMessageKey('UNKNOWN')).toBe('kbTransfer.error.unknown')
  })
})

describe('KB_ERROR_SLUGS', () => {
  it('pokrywa wszystkie slugi z K19 §3', () => {
    expect([...KB_ERROR_SLUGS].sort()).toEqual([...K19_SLUGS].sort())
  })
})

describe('klucze i18n obszaru kbTransfer', () => {
  it('każdy slug i `unknown` mają tekst w pl i en', () => {
    for (const code of [...K19_SLUGS, 'unknown']) {
      const key = kbErrorMessageKey(code)
      expect(pl[key], `pl: ${key}`).toBeTruthy()
      expect(en[key], `en: ${key}`).toBeTruthy()
    }
  })

  it('komunikaty wymagane przez brief mają wskazane treści', () => {
    expect(pl['kbTransfer.error.schema_too_new']).toContain('schemat {{version}}')
    expect(pl['kbTransfer.error.schema_too_new']).toContain('zaktualizuj instalację')
    expect(pl['kbTransfer.error.checksum_mismatch']).toContain('Paczka uszkodzona (suma kontrolna)')
    expect(pl['kbTransfer.error.invalid_archive']).toContain(
      'To nie jest poprawna paczka bazy wiedzy (.wdkb.zip)',
    )
  })

  it('EN kody walidacji i klucz bloku szczegółów mają teksty (SC-V12-06 k.4)', () => {
    // D1 (QA V12-2-1): w EN Alert dostaje tekst po `code` — kody walidacji muszą mieć
    // sensowne angielskie teksty, a polski komunikat serwera trafia w zwinięty blok.
    expect(en['kbTransfer.error.details']).toBe('Technical details')
    expect(pl['kbTransfer.error.details']).toBe('Szczegóły techniczne')
    expect(en['kbTransfer.error.manifest_invalid']).toBe('The package has an invalid manifest.')
    expect(en['kbTransfer.error.unexpected_entry']).toContain('not listed in the manifest')
    expect(en['kbTransfer.error.unsafe_path']).toContain('unsafe entry path')
    expect(en['kbTransfer.error.missing_entry']).toContain('missing a file')
    expect(en['kbTransfer.error.checksum_mismatch']).toContain('checksum mismatch')
  })
})

describe('kbPackageErrorOverrideKey (SC-E67-z2-20, K20 §2: mapowanie wyłącznie po code)', () => {
  it('invalid_archive dostaje komunikat z i18n zamiast technicznego ogona API', () => {
    const key = kbPackageErrorOverrideKey({
      code: 'invalid_archive',
      message: 'To nie jest poprawne archiwum ZIP: File is not a zip file',
    })
    expect(key).toBe('kbTransfer.error.invalid_archive')
    expect(pl[key ?? '']).toBe('To nie jest poprawna paczka bazy wiedzy (.wdkb.zip).')
    expect(en[key ?? '']).toBeTruthy()
  })

  it('not_a_package dostaje komunikat z i18n w języku UI (SC-V12-02)', () => {
    const key = kbPackageErrorOverrideKey({
      code: 'not_a_package',
      message: 'To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).',
    })
    expect(key).toBe('kbTransfer.error.not_a_package')
    expect(pl[key ?? '']).toBe(
      'To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).',
    )
    expect(en[key ?? '']).toBe(
      'This is not a Wawelsky Dragon knowledge base package (manifest.json is missing).',
    )
  })

  it('błędy z nazwą wpisu w komunikacie API zostawiają komunikat API', () => {
    expect(
      kbPackageErrorOverrideKey({
        code: 'unexpected_entry',
        message: 'Nieoczekiwany wpis „notatka.txt” w paczce',
      }),
    ).toBeNull()
    expect(
      kbPackageErrorOverrideKey({
        code: 'unsafe_path',
        message: 'Niebezpieczna ścieżka wpisu „../x”: segment „.”, „..” albo pusty',
      }),
    ).toBeNull()
  })

  it('pozostałe błędy zostawiają komunikat API', () => {
    expect(
      kbPackageErrorOverrideKey({ code: 'missing_entry', message: 'manifest.json' }),
    ).toBeNull()
    expect(kbPackageErrorOverrideKey({ code: 'checksum_mismatch', message: 'x' })).toBeNull()
  })
})
