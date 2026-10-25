// Wspólna sesja UI dla plików e2e logujących się w każdym teście (E5-H8c T11): limiter logowań
// liczy KAŻDĄ próbę (10/min per IP+e-mail, CONTRACT E5-2a §4) i jest współdzielony przez cały
// bieg `verify-full`, więc plik z ~20 testami logującymi się UI-owo tripił falę 429. Wzorzec:
// JEDNO logowanie na plik w `beforeAll` (plik `storageState`), a każdy test startuje z sesją
// odtworzoną z cookie `wd_refresh` (refresh przy starcie strony, 08 §5.3) — bez formularza.
//
// T14: logowanie w beforeAll idzie przez API (origin frontu, Set-Cookie jak przy formularzu),
// a przy limiterze czeka do kolejnego okna i ponawia — pełny bieg (setki logowań) nie urywa
// plików na beforeAll (lawina 429, docs/review-misses.md). T16: limiter przychodzi też jako
// HTTP 200 z kopertą `code != 0` (przestrzeń ragflow), nie tylko jako HTTP 429.
//
// Rotacja (C9): każdy `POST /auth/refresh` wymienia cookie, a ponowne użycie zużytego tokenu
// unieważnia rodzinę (401). `afterEach` zapisuje AKTUALNY stan kontekstu, więc kolejny test
// zawsze startuje ze świeżym cookie; testy w pliku biegną sekwencyjnie (workers = 1).
import os from 'node:os'
import path from 'node:path'
import type { Browser, BrowserContext } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from '../fixtures'

export type UiSession = {
  /** Ścieżka pliku `storageState` — do `test.use({ storageState })` w zakresie pliku. */
  statePath: string
  /** Logowanie raz na plik: `test.beforeAll(async ({ browser }) => session.login(browser))`. */
  login: (browser: Browser) => Promise<void>
  /** Odświeżenie pliku po teście: `test.afterEach(async ({ context }) => session.save(context))`. */
  save: (context: BrowserContext) => Promise<void>
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Okno limitera logowań (CONTRACT E5-2a §4): `"10/min"` — po 61 s najstarsza próba wypada. */
const LIMITER_WINDOW_MS = 61_000
/** Maksymalnie 3 próby (2 czekania) — potem czytelny błąd, nie ciche zamartwianie się. */
const LOGIN_ATTEMPTS = 3

/**
 * Logowanie kontem z seedu przez API na ORIGINIE FRONTU (WD_E2E_BASE_URL + proxy `/api`):
 * `Set-Cookie wd_refresh` trafia pod domenę frontu, dokładnie jak przy formularzu logowania,
 * więc storageState kontekstu odtwarza sesję w kolejnych testach. Limiter liczy każdą próbę
 * w oknie przesuwnym i jest współdzielony z całym biegiem — czekamy do kolejnego okna
 * i ponawiamy (T14; T16: rozpoznajemy oba kształty odpowiedzi limitera).
 */
async function apiLoginWithBackoff(request: BrowserContext['request']): Promise<void> {
  const base = process.env.WD_E2E_BASE_URL ?? ''
  expect(base, 'brak WD_E2E_BASE_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  const url = `${base}/api/v1/auth/login`
  let lastStatus = 0
  let lastBody = ''
  for (let attempt = 1; attempt <= LOGIN_ATTEMPTS; attempt += 1) {
    const response = await request.post(url, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    })
    const status = response.status()
    const text = await response.text()
    // Limiter w dwóch kształtach (T16): HTTP 429 (przestrzeń wd) albo HTTP 200 z kopertą
    // `code != 0` (przestrzeń ragflow — `_handle_wd_error` w backend/app/api/errors.py zwraca
    // 200 dla WDError). Rozstrzyga komunikat z `LoginGuard.hit` (auth_ratelimit.py).
    if (status === 429 || text.includes('Too many login attempts')) {
      lastStatus = status
      lastBody = text.slice(0, 200)
      if (attempt < LOGIN_ATTEMPTS) await sleep(LIMITER_WINDOW_MS)
      continue
    }
    if (status !== 200) {
      throw new Error(`login API: nieoczekiwany HTTP ${status} — ${text.slice(0, 200)}`)
    }
    const body = JSON.parse(text) as { code: number; message: string }
    expect(body.code, `login API: ${body.message}`).toBe(0)
    return
  }
  throw new Error(
    `login API: limiter logowań puścił dopiero po ${LOGIN_ATTEMPTS} próbach (ostatnio HTTP ${lastStatus}) — ${lastBody}`,
  )
}

/** Sesja UI o nazwie pliku spec; PID w nazwie pliku rozdziela równoległe procesy pracownika. */
export function uiSession(spec: string): UiSession {
  const statePath = path.join(os.tmpdir(), `wd-e2e-${spec}-${process.pid}-state.json`)
  return {
    statePath,
    async login(browser: Browser): Promise<void> {
      // Backoff limitera czeka do 2 okien (~123 s) — `setTimeout` w beforeAll podnosi timeout
      // HOOKA (nie testów).
      test.setTimeout(240_000)
      // Playwright 1.63: `browser` w beforeAll tworzy konteksty z opcjami `test.use` — a plik
      // `storageState` powstaje dopiero po tym logowaniu. Jawny `undefined` wyłącza odczyt.
      const context = await browser.newContext({ storageState: undefined })
      await apiLoginWithBackoff(context.request)
      // Weryfikacja w przeglądarce jak dotąd: sesja z cookie `wd_refresh` startuje ze strony —
      // refresh przy starcie odtwarza sesję (08 §5.3); `home-banner` potwierdza zalogowanie.
      const page = await context.newPage()
      await page.goto('/')
      await expect(page.getByTestId('home-banner')).toBeVisible()
      await context.storageState({ path: statePath })
      await context.close()
    },
    async save(context: BrowserContext): Promise<void> {
      // Plików mieszających testy z sesją i bez (np. ekran logowania w visual.spec.ts) nie
      // nadpisujemy stanem pustym: kontekst bez cookie `wd_refresh` skasowałby sesję pliku
      // i kolejne testy startowałyby z ekranem logowania.
      const state = await context.storageState()
      if (!state.cookies.some((cookie) => cookie.name === 'wd_refresh')) return
      await context.storageState({ path: statePath })
    },
  }
}
