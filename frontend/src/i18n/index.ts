import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

export const SUPPORTED_LANGUAGES = ['pl', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]
export const LANGUAGE_STORAGE_KEY = 'wd.language'

// Pakiety tłumaczeń ładowane leniwie (osobny chunk per obszar i język).
const bundles = import.meta.glob<Record<string, string>>('../locales/*/*.json', {
  import: 'default',
})

// Prefiks kodu języka ('en-US' → 'en', 'PL' → 'pl'); nieznany, pusty lub brak → 'pl'.
export function resolveLanguage(candidate: string | null | undefined): Language {
  const prefix = candidate?.slice(0, 2).toLowerCase()
  return prefix === 'en' ? 'en' : 'pl'
}

// Zapisany wybór użytkownika ma pierwszeństwo nad językiem przeglądarki.
export function detectLanguage(): Language {
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
  return resolveLanguage(stored ?? navigator.language)
}

async function loadBundle(language: Language): Promise<void> {
  if (i18n.hasResourceBundle(language, 'translation')) return
  const prefix = `../locales/${language}/`
  const parts = await Promise.all(
    Object.entries(bundles)
      .filter(([path]) => path.startsWith(prefix))
      .map(([, load]) => load()),
  )
  if (parts.length === 0) throw new Error(`Brak pakietu tłumaczeń dla języka: ${language}`)
  i18n.addResourceBundle(language, 'translation', Object.assign({}, ...parts), true, true)
}

// Inicjalizacja idempotentna — kolejne wywołania tylko przełączają język.
export async function initI18n(language?: Language): Promise<typeof i18n> {
  const lng = language ?? detectLanguage()
  if (!i18n.isInitialized) {
    // Klucze są płaskie (z kropkami), więc bez rozdzielania na sekcje i przestrzenie nazw.
    await i18n.use(initReactI18next).init({
      lng,
      fallbackLng: 'pl',
      keySeparator: false,
      nsSeparator: false,
      interpolation: { escapeValue: false },
    })
  }
  // Język wykryty z przeglądarki nie jest wyborem użytkownika — zapis tylko przy jawnym języku.
  if (language === undefined) await applySessionLanguage(lng)
  else await changeLanguage(lng)
  return i18n
}

// Zmiana języka samego UI, bez zapisu wyboru (DEC-306): preferencja konta stosowana po
// zalogowaniu nie nadpisuje ostatniego wyboru przeglądarki (`wd.language`).
export async function applySessionLanguage(language: Language): Promise<void> {
  await loadBundle(language)
  await i18n.changeLanguage(language)
  document.documentElement.lang = language
}

export async function changeLanguage(language: Language): Promise<void> {
  await applySessionLanguage(language)
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
}

export { i18n }
