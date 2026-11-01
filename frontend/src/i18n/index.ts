import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

export const SUPPORTED_LANGUAGES = ['pl', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]
export const LANGUAGE_STORAGE_KEY = 'wd.language'

// Pakiety tłumaczeń ładowane leniwie (osobny chunk per obszar i język).
const bundles = import.meta.glob<Record<string, string>>('../locales/*/*.json', {
  import: 'default',
})

export const DEFAULT_LANGUAGE: Language = 'en'
const LOGIN_CHOICE_STORAGE_KEY = 'wd.loginLanguage'

// Kod albo nazwa języka: 'pl-PL', 'PL' i 'Polish' (domyślna wartość `users.language`) → 'pl';
// inne, puste lub brak → język domyślny.
export function resolveLanguage(candidate: string | null | undefined): Language {
  const prefix = candidate?.slice(0, 2).toLowerCase()
  return prefix === 'pl' || prefix === 'po' ? 'pl' : DEFAULT_LANGUAGE
}

// Bez zapisanego wyboru obowiązuje język domyślny, niezależnie od języka przeglądarki.
export function detectLanguage(): Language {
  return resolveLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY))
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
      fallbackLng: DEFAULT_LANGUAGE,
      keySeparator: false,
      nsSeparator: false,
      interpolation: { escapeValue: false },
    })
  }
  // Język domyślny nie jest wyborem użytkownika — zapis tylko przy jawnym języku.
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

// Wybór na ekranie logowania ma zastąpić język konta. Trzymany w `sessionStorage`, bo logowanie
// OIDC przechodzi przez przekierowanie, a wybór dotyczy tylko najbliższego logowania w tej karcie.
export async function chooseLanguageOnLogin(language: Language): Promise<void> {
  await changeLanguage(language)
  sessionStorage.setItem(LOGIN_CHOICE_STORAGE_KEY, language)
}

export function takeLoginLanguageChoice(): Language | null {
  const choice = sessionStorage.getItem(LOGIN_CHOICE_STORAGE_KEY)
  sessionStorage.removeItem(LOGIN_CHOICE_STORAGE_KEY)
  return choice === null ? null : resolveLanguage(choice)
}

export { i18n }
