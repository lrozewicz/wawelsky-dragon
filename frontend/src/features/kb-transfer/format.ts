/**
 * Formatowanie liczb i rozmiarów w UI transferu bazy wiedzy (MINOR T4, spec 08 §7.15):
 * grupowanie cyfr wymuszone, bo `Intl.NumberFormat('pl-PL')` nie grupuje 4-cyfrowych
 * („7251” zamiast „7 251”), a liczba i jednostka rozmiaru dzielone twardej spacji —
 * „ok. 74 MB” nie łamie się między liczbą a jednostką w wierszu paska przy 390 px.
 */

import type { Language } from '../../i18n'

const LOCALES: Record<Language, string> = { pl: 'pl-PL', en: 'en-US' }

const BYTE_UNITS = ['KB', 'MB', 'GB', 'TB'] as const

/** Twarda spacja (nbsp) między liczbą a jednostką i jako separator tysięcy w pl-PL. */
export const NUMBER_SPACE = ' '

/** Liczba z grupowaniem cyfr także 4-cyfrowej („7 251”); separator zależy od języka. */
export function formatGrouped(value: number, language: Language): string {
  return new Intl.NumberFormat(LOCALES[language], { useGrouping: 'always' }).format(value)
}

/** Rozmiar paczki: podstawa 1024, jednostki B…TB, najwyżej jedno miejsce po przecinku. */
export function formatPackageBytes(bytes: number, language: Language): string {
  let value = bytes
  let unit = 'B'
  for (const candidate of BYTE_UNITS) {
    if (value < 1024) break
    value /= 1024
    unit = candidate
  }
  return `${formatGrouped(Math.round(value * 10) / 10, language)}${NUMBER_SPACE}${unit}`
}
