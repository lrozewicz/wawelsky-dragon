import type { Language } from '../i18n'

const LOCALES: Record<Language, string> = { pl: 'pl-PL', en: 'en-US' }

const BYTE_UNITS = ['KB', 'MB', 'GB', 'TB'] as const

export function formatDate(
  value: Date | string | number,
  language: Language,
  timeZone?: string,
): string {
  return new Intl.DateTimeFormat(LOCALES[language], { dateStyle: 'medium', timeZone }).format(
    new Date(value),
  )
}

export function formatDateTime(
  value: Date | string | number,
  language: Language,
  timeZone?: string,
): string {
  return new Intl.DateTimeFormat(LOCALES[language], {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone,
  }).format(new Date(value))
}

/** Data i czas z sekundami (`HH:mm:ss`) — odróżnia zdarzenia z tej samej minuty (SC-E67-z2-21). */
export function formatDateTimeSeconds(value: Date | string | number, language: Language): string {
  return new Intl.DateTimeFormat(LOCALES[language], {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(new Date(value))
}

export function formatNumber(value: number, language: Language): string {
  return new Intl.NumberFormat(LOCALES[language]).format(value)
}

// Podstawa 1024, jednostki B…TB, najwyżej jedno miejsce po przecinku.
export function formatBytes(bytes: number, language: Language): string {
  let value = bytes
  let unit = 'B'
  for (const candidate of BYTE_UNITS) {
    if (value < 1024) break
    value /= 1024
    unit = candidate
  }
  return `${formatNumber(Math.round(value * 10) / 10, language)} ${unit}`
}

/**
 * Etykieta dymka suwaka (SC-V12-z-D1): strzałki MUI dodają krok wprost (0.35+0.05 →
 * `0.39999999999999997`), więc dymek ma pokazywać liczbę zaokrągloną do 2 miejsc, bez szumu
 * float i bez końcowych zer. Używana jako `valueLabelFormat` wszystkich suwaków.
 */
export function sliderValueLabel(value: number): string {
  return String(Number(value.toFixed(2)))
}
