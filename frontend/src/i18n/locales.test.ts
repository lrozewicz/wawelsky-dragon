import { describe, expect, it } from 'vitest'

type Locale = Record<string, string>
type Bundles = Record<string, Locale>

const plModules = import.meta.glob<Locale>('../locales/pl/*.json', {
  eager: true,
  import: 'default',
})
const enModules = import.meta.glob<Locale>('../locales/en/*.json', {
  eager: true,
  import: 'default',
})

// Nazwa obszaru (plik bez katalogu i rozszerzenia) z pełnej ścieżki modułu.
function areaFromPath(path: string): string {
  return (
    path
      .split('/')
      .pop()
      ?.replace(/\.json$/, '') ?? path
  )
}

// Moduły globa (`{ścieżka: słownik}`) → `{obszar: słownik}`.
function toBundles(modules: Record<string, Locale>): Bundles {
  const bundles: Bundles = {}
  for (const [path, locale] of Object.entries(modules)) {
    bundles[areaFromPath(path)] = locale
  }
  return bundles
}

// Klucze obecne w `base`, których brakuje w `other` (posortowane) — podstawa testu kompletności.
function compareLocales(base: Locale, other: Locale): string[] {
  return Object.keys(base)
    .filter((key) => !(key in other))
    .sort()
}

// Klucze występujące w więcej niż jednym pliku danego języka (`plik:klucz`, posortowane).
function findDuplicateKeys(bundles: Bundles): string[] {
  const owner = new Map<string, string>()
  const duplicates: string[] = []
  for (const [area, locale] of Object.entries(bundles)) {
    for (const key of Object.keys(locale)) {
      if (owner.has(key)) duplicates.push(`${area}:${key}`)
      else owner.set(key, area)
    }
  }
  return duplicates.sort()
}

// Scala słowniki obszarów w jeden płaski słownik języka.
function mergeBundles(bundles: Bundles): Locale {
  return Object.assign({}, ...Object.values(bundles))
}

// Nazwy placeholderów `{{x}}` w wartości tłumaczenia (posortowane).
function placeholders(value: string): string[] {
  return [...value.matchAll(/\{\{(\w+)\}\}/g)].map((match) => match[1] ?? '').sort()
}

describe('compareLocales', () => {
  it('zwraca niepustą listę różnic, gdy brakuje klucza', () => {
    expect(compareLocales({ 'a.b': 'x' }, {})).toEqual(['a.b'])
    expect(compareLocales({ 'a.b': 'x', 'c.d': 'y' }, { 'a.b': 'x' })).toEqual(['c.d'])
  })

  it('zwraca pustą listę dla zgodnych zbiorów kluczy', () => {
    expect(compareLocales({ 'a.b': 'x' }, { 'a.b': 'y' })).toEqual([])
  })
})

describe('findDuplicateKeys', () => {
  it('wskazuje klucz powtórzony w drugim pliku', () => {
    expect(findDuplicateKeys({ alpha: { 'alpha.x': 'a' }, beta: { 'alpha.x': 'b' } })).toEqual([
      'beta:alpha.x',
    ])
  })

  it('nie zgłasza kluczy unikalnych w obrębie języka', () => {
    expect(findDuplicateKeys({ alpha: { 'alpha.x': 'a' }, beta: { 'beta.y': 'b' } })).toEqual([])
  })
})

describe('kompletność tłumaczeń', () => {
  const plBundles = toBundles(plModules)
  const enBundles = toBundles(enModules)
  const plLocale: Locale = mergeBundles(plBundles)
  const enLocale: Locale = mergeBundles(enBundles)

  it('pl i en mają ten sam zestaw plików obszarów', () => {
    expect(Object.keys(plBundles).sort()).toEqual(Object.keys(enBundles).sort())
  })

  it('każdy plik obszaru ma te same klucze w pl i en', () => {
    for (const area of Object.keys(plBundles)) {
      expect(compareLocales(plBundles[area] ?? {}, enBundles[area] ?? {}), area).toEqual([])
      expect(compareLocales(enBundles[area] ?? {}, plBundles[area] ?? {}), area).toEqual([])
    }
  })

  it('każdy klucz zaczyna się od nazwy swojego obszaru', () => {
    for (const bundles of [plBundles, enBundles]) {
      for (const [area, locale] of Object.entries(bundles)) {
        for (const key of Object.keys(locale)) {
          expect(key.startsWith(`${area}.`), `${area}: ${key}`).toBe(true)
        }
      }
    }
  })

  it('nie ma klucza powtórzonego między plikami tego samego języka', () => {
    expect(findDuplicateKeys(plBundles)).toEqual([])
    expect(findDuplicateKeys(enBundles)).toEqual([])
  })

  it('pl i en mają identyczne zbiory kluczy', () => {
    expect(compareLocales(plLocale, enLocale)).toEqual([])
    expect(compareLocales(enLocale, plLocale)).toEqual([])
  })

  it('nie ma pustych wartości (po trim)', () => {
    for (const [key, value] of Object.entries(plLocale)) {
      expect(value.trim(), `pl: ${key}`).not.toBe('')
    }
    for (const [key, value] of Object.entries(enLocale)) {
      expect(value.trim(), `en: ${key}`).not.toBe('')
    }
  })

  it('te same klucze mają te same placeholdery w obu językach', () => {
    for (const key of Object.keys(plLocale)) {
      expect(placeholders(enLocale[key] ?? ''), `en: ${key}`).toEqual(
        placeholders(plLocale[key] ?? ''),
      )
    }
  })

  // Jawny wyjątek od niezmiennika DEC-356 („EN = tekst serwera co do znaku”), sankcjonowany
  // przez DEC-371: nieobsługiwany typ pliku ma w EN ujednolicony komunikat
  // „Unsupported file type: {{filename}}” zamiast rekonstrukcji tekstu serwera — jedno
  // źródło tekstu dla ścieżki serwerowej (w. 1) i klienckiej (w. 2). Ta asercja pilnuje,
  // żeby wyjątek pozostał jawny: zmiana brzmienia bez decyzji = czerwień.
  it('serverMsg.fileTypeUnsupported: EN ≠ tekst serwera — odstępstwo od DEC-356 (DEC-371)', () => {
    const en = enBundles.serverMsg?.['serverMsg.fileTypeUnsupported']
    expect(en).toBe('Unsupported file type: {{filename}}')
    expect(en).not.toBe('{{filename}}: This type of file has not been supported yet!')
    expect(plBundles.serverMsg?.['serverMsg.fileTypeNotSupported']).toBeUndefined()
  })
})
