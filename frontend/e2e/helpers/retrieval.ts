// Pomocniki scenariusza S6-05 (kontrakt WP E3-4b §T4): otwarcie zakładki „Test retrievalu”,
// zadanie pytania i ustawienie progu podobieństwa suwakiem. Bez mocków — te same trasy woła UI.
import type { Page } from '@playwright/test'

import { expect } from '../fixtures'

/** Krok suwaka progu (kontrakt §SettingsCard: `step={0.01}`, zakres 0–1). */
const STEP = 0.01

/** Otwiera zakładkę testu retrievalu datasetu i czeka na pole pytania. */
export async function openRetrievalTab(page: Page, datasetId: string): Promise<void> {
  await page.goto(`/dataset/retrieval/${datasetId}`)
  await expect(page.getByTestId('retrieval-question')).toBeVisible()
}

/**
 * Wpisuje pytanie i uruchamia wyszukiwanie przyciskiem „Uruchom”. Czeka na `POST /api/v1/retrieval`
 * (nasłuch ustawiony przed kliknięciem, inaczej odpowiedź mogłaby umknąć) i sprawdza kopertę API.
 * Komunikat asercji niesie `message` backendu, więc awaria API jest widoczna od razu — bez tego
 * scenariusz kończyłby się gołym przekroczeniem limitu widoczności wyniku.
 */
export async function askQuestion(page: Page, question: string): Promise<void> {
  await page.getByTestId('retrieval-question').fill(question)
  const answered = page.waitForResponse((response) => response.url().includes('/api/v1/retrieval'))
  await page.getByTestId('retrieval-run').click()
  const response = await answered
  const body = (await response.json()) as { code: number; message: string }
  expect(
    response.status(),
    `POST /api/v1/retrieval → HTTP ${response.status()}: ${body.message}`,
  ).toBe(200)
  expect(body.code, `POST /api/v1/retrieval → code ${body.code}: ${body.message}`).toBe(0)
}

/**
 * Próg tak, jak wypisuje go MUI w `aria-valuenow`: suwak dostaje liczbę (`value` prop Slidera),
 * więc React renderuje `String(liczby)` — `0.1`, nie „0.10”. `toFixed(2)` wyrównuje tylko szum
 * zmiennoprzecinkowy kroku 0.01 (`3 × 0.01`), a `Number` zdejmuje końcowe zero.
 */
function ariaValue(value: number): string {
  return String(Number(value.toFixed(2)))
}

/**
 * Ustawia próg podobieństwa: fokus na wejściu suwaka, `Home` (minimum), potem strzałki w prawo,
 * po jednym kroku 0.01. Po każdym kroku czyta `aria-valuenow`, więc zgubione naciśnięcie nie
 * przejdzie cicho (MUI liczy kolejny krok z wartości propa, nie z klawisza).
 */
export async function setThreshold(page: Page, value: number): Promise<void> {
  const input = page.getByTestId('retrieval-threshold').locator('input')
  await input.focus()
  await input.press('Home')
  const steps = Math.round(value / STEP)
  for (let step = 1; step <= steps; step += 1) {
    await input.press('ArrowRight')
    await expect(input).toHaveAttribute('aria-valuenow', ariaValue(step * STEP))
  }
  await expect(input).toHaveAttribute('aria-valuenow', ariaValue(value))
}
