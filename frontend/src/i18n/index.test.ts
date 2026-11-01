import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  LANGUAGE_STORAGE_KEY,
  applySessionLanguage,
  changeLanguage,
  detectLanguage,
  i18n,
  initI18n,
  resolveLanguage,
} from './index'

describe('resolveLanguage', () => {
  it('mapuje kod lub nazwę języka, domyślnie en', () => {
    expect(resolveLanguage('en-US')).toBe('en')
    expect(resolveLanguage('en')).toBe('en')
    expect(resolveLanguage('PL')).toBe('pl')
    expect(resolveLanguage('pl-PL')).toBe('pl')
    expect(resolveLanguage('Polish')).toBe('pl')
    expect(resolveLanguage('English')).toBe('en')
    expect(resolveLanguage('de')).toBe('en')
    expect(resolveLanguage(null)).toBe('en')
    expect(resolveLanguage(undefined)).toBe('en')
  })
})

describe('initI18n i changeLanguage', () => {
  it('ładuje pakiet en, a changeLanguage przełącza na pl', async () => {
    await initI18n('en')
    expect(i18n.t('nav.home')).toBe('Home')

    await changeLanguage('pl')
    expect(i18n.t('nav.home')).toBe('Start')
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('pl')
    expect(document.documentElement.lang).toBe('pl')
  })

  it('jest idempotentne i aktualizuje document.lang', async () => {
    await initI18n('pl')
    expect(i18n.t('nav.home')).toBe('Start')
    await initI18n('en')
    expect(i18n.t('nav.home')).toBe('Home')
    expect(document.documentElement.lang).toBe('en')
  })
})

describe('initI18n bez jawnego języka', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)
  })

  it('bez wyboru startuje po angielsku mimo polskiej przeglądarki i niczego nie zapisuje', async () => {
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('pl-PL')

    await initI18n()

    expect(i18n.language).toBe('en')
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull()
  })

  it('zachowuje zapisany wybór mimo innego języka przeglądarki', async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'pl')
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-US')

    await initI18n()

    expect(i18n.language).toBe('pl')
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('pl')
  })
})

describe('applySessionLanguage', () => {
  afterEach(() => {
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)
  })

  it('zmienia język UI bez zapisu ostatniego wyboru (DEC-306)', async () => {
    await initI18n('pl')
    expect(i18n.t('nav.home')).toBe('Start')
    // initI18n sam zapisuje wybór — czyszczenie, by widzieć wyłącznie skutek applySessionLanguage.
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)

    await applySessionLanguage('en')

    expect(i18n.t('nav.home')).toBe('Home')
    expect(document.documentElement.lang).toBe('en')
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull()
  })
})

describe('detectLanguage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('zapisany wybór ma pierwszeństwo', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'pl')
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-US')
    expect(detectLanguage()).toBe('pl')
  })

  it('bez zapisu daje en, także przy polskiej przeglądarce', () => {
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('pl-PL')
    expect(detectLanguage()).toBe('en')
  })
})
