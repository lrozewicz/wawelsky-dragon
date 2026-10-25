// Pomocniki scenariuszy SC-E5-H9-01…04 (brief WP E5-H9 T1a): odczyt kolorów stanów MUI przez
// `getComputedStyle` i klasyfikacja „czerwony akcent” oraz wczytywanie próbek do uploadu
// prawdziwym DataTransfer. Decyzja Architekta (BRIEF WP E5-H9 pkt 1, DEC-305): fokus pól,
// włączone przełączniki/checkboxy, suwaki i paski postępu mają być w akcencie `secondary`
// (chłodny niebiesko-stalowy), nigdy w czerwieni marki (brand, hsl 355°) ani błędu (error, hsl 0°).
// Do zadania T2 akcent fokusu i kontrolek jest brandową czerwonią, więc testy klasyfikują
// ODCZEŃ z pikseli CSS, a nie porównują z konkretną stałą — po T2 akcent niebieski przechodzi,
// czerwień (marka i błąd) nie.
import { expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, Locator } from '@playwright/test'

import { apiLogin } from '../helpers'

const API_URL = process.env.WD_E2E_API_URL ?? ''

type Envelope<T> = { code: number; message: string; data: T }

export type Rgb = { r: number; g: number; b: number }

/** Parsuje kolor w postaci `rgb()`/`rgba()` (computed style) do składowych 0–255. */
export function parseRgb(color: string): Rgb | null {
  const match = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/.exec(color)
  if (match === null) return null
  return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]) }
}

/** Odcień HSL (0–360°) i nasycenie (0–1) dla zparsowanego rgb. */
export function rgbToHueSat({ r, g, b }: Rgb): { hue: number; sat: number } {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const delta = max - min
  const sat = max === 0 ? 0 : delta / max
  let hue = 0
  if (delta !== 0) {
    if (max === rn) hue = 60 * (((gn - bn) / delta + 6) % 6)
    else if (max === gn) hue = 60 * ((bn - rn) / delta + 2)
    else hue = 60 * ((rn - gn) / delta + 4)
  }
  return { hue, sat }
}

/**
 * Czy kolor jest „czerwony” jak marka (hsl 355°) i błąd (hsl 0°): odcień w oknie 345–15° przy
 * wyraźnym nasyceniu. Szarości i akcent niebiesko-stalowy (T2) zwracają `false`.
 */
export function isReddish(color: string): boolean {
  const rgb = parseRgb(color)
  if (rgb === null) return false
  const { hue, sat } = rgbToHueSat(rgb)
  return (hue >= 345 || hue <= 15) && sat >= 0.25
}

/** Czy kolor jest zielony jak `success` MUI (odcień ~120–160°) przy wyraźnym nasyceniu. */
export function isGreenish(color: string): boolean {
  const rgb = parseRgb(color)
  if (rgb === null) return false
  const { hue, sat } = rgbToHueSat(rgb)
  return hue >= 90 && hue <= 170 && sat >= 0.25
}

/** Wartość właściwości CSS elementu z computed style. Test wyłącza przejścia CSS
 * (`*{transition:none!important}`), żeby czytać wartość końcową, nie pośrednią (wzór s20). */
export async function computedStyle(locator: Locator, property: string): Promise<string> {
  return locator.evaluate((el, prop) => getComputedStyle(el).getPropertyValue(prop), property)
}

/** Typy MIME próbek z `e2e/fixtures` używanych w scenariuszach SC-E5-H9-01/03. */
export const SAMPLE_MIME = {
  'sample.pdf': 'application/pdf',
  'sample.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'sample.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
} as const

/** Realny bajt próbki z `e2e/fixtures` — ten sam plik czyta Node i `File` na stronie (dropFile). */
export function sampleBytes(name: keyof typeof SAMPLE_MIME): Buffer {
  return readFileSync(fileURLToPath(new URL(`../fixtures/${name}`, import.meta.url)))
}

// Jeden token API na proces pracy: limiter logowań (10/min per IP+e-mail, `auth_ratelimit.py`)
// liczy KAŻDY POST /auth/login, a retries=1 mnoży próby — per-testowe apiLogin wywracały resztę
// pliku przez 429 i restart workera (MAJOR review T1a). Pliki SC-E5-H9 nie wołają resetDb (reset
// K9 biegnie raz, przed całym zestawem), więc token z pierwszego testu jest ważny w kolejnych
// i nie traci praw do tenanta; żywotność tokenu to 15 min.
let apiToken: Promise<string> | undefined
export function apiTokenOnce(request: APIRequestContext): Promise<string> {
  apiToken ??= apiLogin(request)
  return apiToken
}

/** Wgrywa dokument tekstowy do datasetu przez API — bez parsowania (kolumny nie potrzebują stanu). */
export async function uploadDocument(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  name: string,
): Promise<void> {
  const response = await request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
    headers: { authorization: `Bearer ${token}` },
    multipart: {
      file: {
        name,
        mimeType: 'text/plain',
        buffer: Buffer.from('Treść dokumentu SC-E5-H9', 'utf-8'),
      },
    },
  })
  const body = (await response.json()) as Envelope<unknown>
  expect(response.status(), 'upload dokumentu').toBe(200)
  expect(body.code, body.message).toBe(0)
}

/** Tworzy sesję czatu przez API — prologue (pierwsza wiadomość asystenta) ma przycisk „Kopiuj”. */
export async function createSession(
  request: APIRequestContext,
  token: string,
  chatId: string,
): Promise<string> {
  const response = await request.post(`${API_URL}/api/v1/chats/${chatId}/sessions`, {
    headers: { authorization: `Bearer ${token}` },
    data: { name: 'Sesja SC-E5-H9-08' },
  })
  const body = (await response.json()) as Envelope<{ id: string }>
  expect(response.status(), 'POST /chats/{id}/sessions').toBe(200)
  expect(body.code, body.message).toBe(0)
  return body.data.id
}
