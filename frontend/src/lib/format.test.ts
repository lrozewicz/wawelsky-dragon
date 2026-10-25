import { describe, expect, it } from 'vitest'

import {
  formatBytes,
  formatDate,
  formatDateTime,
  formatDateTimeSeconds,
  formatNumber,
  sliderValueLabel,
} from './format'

// Intl wstawia NBSP (U+00A0) lub wąską NBSP (U+202F) — każdy biały znak sprowadzamy do zwykłej spacji.
function normalize(value: string): string {
  return value.replace(/\s+/g, ' ')
}

describe('formatNumber', () => {
  it('formatuje liczbę wg locale języka', () => {
    expect(normalize(formatNumber(1234.5, 'en'))).toBe('1,234.5')
    expect(normalize(formatNumber(1234.5, 'pl'))).toBe('1234,5')
  })
})

describe('formatBytes', () => {
  it('formatuje rozmiar z jednostką wg locale', () => {
    expect(normalize(formatBytes(0, 'en'))).toBe('0 B')
    expect(normalize(formatBytes(1024, 'en'))).toBe('1 KB')
    expect(normalize(formatBytes(1536, 'en'))).toBe('1.5 KB')
    expect(normalize(formatBytes(1536, 'pl'))).toBe('1,5 KB')
    expect(normalize(formatBytes(0, 'pl'))).toBe('0 B')
    expect(normalize(formatBytes(1024, 'pl'))).toBe('1 KB')
  })

  it('ogranicza część dziesiętną do jednego miejsca', () => {
    expect(normalize(formatBytes(1234, 'en'))).toBe('1.2 KB')
  })
})

describe('formatDate', () => {
  const value = '2026-09-29T12:00:00Z'

  it('formatuje datę medium wg locale', () => {
    expect(normalize(formatDate(value, 'en', 'UTC'))).toBe('Sep 29, 2026')
    expect(normalize(formatDate(value, 'pl', 'UTC'))).toBe('29 wrz 2026')
  })
})

describe('formatDateTimeSeconds (SC-E67-z2-21)', () => {
  it('pokazuje sekundy, więc zdarzenia z tej samej minuty się różnią', () => {
    const a = formatDateTimeSeconds('2026-10-14T10:05:10Z', 'pl')
    const b = formatDateTimeSeconds('2026-10-14T10:05:40Z', 'pl')
    expect(a).toMatch(/\d{1,2}:\d{2}:\d{2}/)
    expect(a).not.toBe(b)
  })
})

describe('formatDateTime', () => {
  it('zwraca datę medium i godzinę short', () => {
    const formatted = normalize(formatDateTime('2026-09-29T12:00:00Z', 'en', 'UTC'))
    expect(formatted).toContain('Sep 29, 2026')
    expect(formatted).toContain('12:00')
  })
})

describe('sliderValueLabel', () => {
  it('zaokrągla dymek suwaka do 2 miejsc, bez szumu float (SC-V12-z-D1)', () => {
    // Surowe wartości z dymka QA-UI (strzałki MUI dodają krok wprost: 0.35+0.05).
    expect(sliderValueLabel(0.44999999999999996)).toBe('0.45')
    expect(sliderValueLabel(0.39999999999999997)).toBe('0.4')
    // Wartości „okrągłe” bez końcowych zer i bez zmiany zapisu.
    expect(sliderValueLabel(0.2)).toBe('0.2')
    expect(sliderValueLabel(1)).toBe('1')
    expect(sliderValueLabel(0)).toBe('0')
    expect(sliderValueLabel(-0.25)).toBe('-0.25')
  })
})
