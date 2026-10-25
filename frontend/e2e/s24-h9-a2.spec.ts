// SC-E5-H9-03…04 (brief WP E5-H9 T1a): scenariusze z `work/wp/E5-H9/SCENARIOS.md` w prawdziwej
// przeglądarce — koniec uploadu i trwałość języka. SC-01…02 są w `s24-h9-a.spec.ts` (bramka
// 300 linii; nazwa `-b` należy do briefu T1b, dlatego `-a2`). Stan na wp/E5-H9 (@ec9ee5a8)
// ŚWIADOMIE odbiega od scenariuszy, więc testy są czerwone dokładnie tam (z przyczyną w
// komunikacie asercji), a zazieleniają je zadania T4 (koniec uploadu: „Przesłano N z M”,
// „Gotowe”) i T5 (język: domyślne teksty czatu). `test.fixme`/`test.skip` są zabronione;
// pozostałe scenariusze e2e nie zmieniają się.
import type { Page } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { createDataset, deleteAllChats } from './helpers'
import { dropFile } from './helpers/dnd'
import { apiTokenOnce, SAMPLE_MIME, sampleBytes } from './helpers/h9'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

// Logowanie RAZ na plik (T11): limiter logowań 10/min per IP+e-mail jest współdzielony w biegu
// (`helpers/session.ts`); describe SC-04 nadpisuje `storageState` świadomie (świeża przeglądarka).
const session = uiSession('s24-h9-a2')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.setTimeout(90_000)

// Retry wyłączony dla tego pliku: czerwienie są świadome (raport zadania T1a), a pass retry
// tworzy nowego workera — beforeAll loguje się ponownie przez UI i łącznie z pozostałymi
// logowaniami dobija limiter 10/min (429 kaskadowo wyłączało resztę pliku; MAJOR review T1a).
test.describe.configure({ retries: 0 })

// ── SC-E5-H9-03: upload w datasecie sygnalizuje koniec ─────────────────────────────────────
test.describe('SC-E5-H9-03 upload sygnalizuje koniec', () => {
  let cleanup: { token: string; datasetId: string } | undefined
  test.afterEach(async ({ request }) => {
    if (cleanup !== undefined) {
      await deleteDataset(request, cleanup.token, cleanup.datasetId)
      cleanup = undefined
    }
  })

  test('SC-E5-H9-03 krok 1-2: trzy pliki → „Przesłano 3 z 3” i „Gotowe”', async ({
    page,
    request,
  }) => {
    const token = await apiTokenOnce(request)
    cleanup = { token, datasetId: await createDataset(request, token, 'E2E H9-03 trzy pliki') }
    await page.goto(`/dataset/files/${cleanup.datasetId}`)
    await page.getByTestId('files-add').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Krok 1: 3 prawdziwe pliki z fixtures, upuszczone prawdziwym DataTransfer (helpers/dnd).
    for (const name of ['sample.pdf', 'sample.docx', 'sample.xlsx'] as const) {
      await dropFile(
        page,
        page.getByTestId('upload-dropzone'),
        sampleBytes(name),
        name,
        SAMPLE_MIME[name],
      )
    }
    await expect(dialog.getByText('sample.xlsx')).toBeVisible()
    await page.getByTestId('upload-start').click()
    // exact: etykieta per plik to dokładnie „Przesłano” (po T4 streszczenie „Przesłano 3 z 3”
    // nie może wejść do licznika).
    await expect(dialog.getByText('Przesłano', { exact: true })).toHaveCount(3, { timeout: 60_000 })

    // Krok 2: koniec uploadu — „Przesłano 3 z 3”; „Anuluj” zmienia się w główne „Gotowe”
    // (T4), aktywne i z fokusem (SC-E5-H9-03 krok 2).
    await expect
      .soft(dialog.getByText('Przesłano 3 z 3'), 'krok 2: streszczenie końca uploadu (T4)')
      .toBeVisible()
    const done = dialog.getByRole('button', { name: 'Gotowe' })
    await expect.soft(done, 'krok 2: przycisk końcowy „Gotowe” (T4)').toBeVisible()
    await expect.soft(done, 'krok 2: „Gotowe” aktywne').toBeEnabled()
    await expect.soft(done, 'krok 2: fokus na „Gotowe”').toBeFocused()
    // T15b: po pełnym sukcesie „Prześlij” wyłączone — nie ma czego ponawiać.
    await expect
      .soft(dialog.getByTestId('upload-start'), 'krok 2: „Prześlij” wyłączone po pełnym sukcesie')
      .toBeDisabled()
    await expectNoLayoutDefects(page, 'dialog uploadu po zakończeniu (3 z 3)')
  })

  test('SC-E5-H9-03 krok 3: odrzucony plik 0 B → „Przesłano 2 z 3” z przyczyną', async ({
    page,
    request,
  }) => {
    const token = await apiTokenOnce(request)
    cleanup = { token, datasetId: await createDataset(request, token, 'E2E H9-03 odrzucony') }
    await page.goto(`/dataset/files/${cleanup.datasetId}`)
    await page.getByTestId('files-add').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    await dropFile(
      page,
      page.getByTestId('upload-dropzone'),
      sampleBytes('sample.pdf'),
      'sample.pdf',
      SAMPLE_MIME['sample.pdf'],
    )
    await dropFile(
      page,
      page.getByTestId('upload-dropzone'),
      Buffer.alloc(0),
      'pusty.pdf',
      'application/pdf',
    )
    // Przyczyna odrzucenia 0 B widoczna od razu (U10 — dziś ostrzeżenie pod strefą).
    await expect(page.getByTestId('upload-unreadable')).toBeVisible()
    await dropFile(
      page,
      page.getByTestId('upload-dropzone'),
      sampleBytes('sample.docx'),
      'sample.docx',
      SAMPLE_MIME['sample.docx'],
    )
    await page.getByTestId('upload-start').click()
    await expect(dialog.getByText('Przesłano', { exact: true })).toHaveCount(2, { timeout: 60_000 })

    // Krok 3: streszczenie z odrzuceniem — „Gotowe” aktywne mimo odrzuconego pliku (SC-03 k.3).
    await expect
      .soft(dialog.getByText('Przesłano 2 z 3'), 'krok 3: streszczenie z odrzuceniem (T4)')
      .toBeVisible()
    await expect
      .soft(dialog.getByRole('button', { name: 'Gotowe' }), 'krok 3: „Gotowe” aktywne')
      .toBeEnabled()
    await expectNoLayoutDefects(page, 'dialog uploadu po zakończeniu (2 z 3)')
  })
})

// ── Odporność logowania UI na limiter (T16) ────────────────────────────────────────────────
// Limiter logowań (10/min) jest współdzielony przez cały bieg, a SC-04 loguje się przez
// formularz UI (persona świeżej przeglądarki). Po kliknięciu albo jest `home-banner`
// (sukces), albo alert limitera „Too many login attempts…" (backend odpowiada HTTP 200
// z kopertą `code != 0`) — czekamy okno 61 s i ponawiamy; inny alert (np. złe hasło)
// pada natychmiast. Wzór: `helpers/session.ts`.
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
const LIMITER_WINDOW_MS = 61_000
const LOGIN_ATTEMPTS = 3

async function loginUiResilient(page: Page): Promise<void> {
  for (let attempt = 1; attempt <= LOGIN_ATTEMPTS; attempt += 1) {
    if (attempt > 1) {
      await sleep(LIMITER_WINDOW_MS)
      await page.goto('/login')
      await page.getByTestId('login-email').fill(ADMIN_EMAIL)
      await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
    }
    await page.getByTestId('login-submit').click()
    await page
      .locator('[data-testid="home-banner"], [data-testid="login-error"]')
      .first()
      .waitFor({ state: 'visible', timeout: 15_000 })
    if (await page.getByTestId('home-banner').isVisible()) return
    await expect(
      page.getByTestId('login-error'),
      'alert logowania to limiter logowań, nie inny błąd',
    ).toContainText('Too many login attempts')
  }
  throw new Error(`login UI: limiter logowań puścił dopiero po ${LOGIN_ATTEMPTS} próbach`)
}

// ── SC-E5-H9-04: język interfejsu jest trwały i spójny ─────────────────────────────────────
test.describe('SC-E5-H9-04 język trwały i spójny', () => {
  // Persona: przeglądarka w EN (krok 5 „stan obecny”: pierwsze wejście bez wyboru → język
  // przeglądarki — asercja na starcie pierwszego testu). Świeży kontekst, bez sesji pliku.
  test.use({ storageState: undefined, locale: 'en-US' })
  // Flaga sprzątania: czat z kroku 4 znika także wtedy, gdy asercja T5 padnie (MINOR review T1a).
  let chatCreated = false

  test('SC-E5-H9-04 krok 1-3: wybór „Polski” przetrwa wylogowanie i ponowne logowanie (także F5)', async ({
    page,
  }) => {
    await page.goto('/login')
    // Krok 5 (stan obecny): świeża przeglądarka EN bez wyboru → ekran logowania po angielsku.
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
    await page.getByTestId('login-email').fill(ADMIN_EMAIL)
    await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
    await page.getByTestId('login-submit').click()
    await expect(page.getByTestId('home-banner')).toBeVisible()
    // Po logowaniu front stosuje język konta (`authState.applyUser`); konto z seedu bez wyboru
    // rozwiązuje się do „pl” — z tego stanu budujemy personę „użytkownik z UI w EN”.
    await expect(page.getByRole('button', { name: 'Język' })).toBeVisible()
    await page.getByRole('button', { name: 'Język' }).click()
    await page.getByRole('menuitem', { name: 'English' }).click()
    await expect(page.getByRole('button', { name: 'Language' })).toBeVisible()

    // Krok 1: zmiana języka na „Polski” — cały UI po polsku.
    await page.getByRole('button', { name: 'Language' }).click()
    await page.getByRole('menuitem', { name: 'Polski' }).click()
    await expect(page.getByRole('button', { name: 'Język' })).toBeVisible()
    await expect(
      page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
    ).toBeVisible()

    // Krok 2: wylogowanie — ekran logowania po polsku (ostatni wybór zapamiętany w przeglądarce).
    await page.getByRole('button', { name: 'Menu użytkownika' }).click()
    await page.getByRole('menuitem', { name: 'Wyloguj' }).click()
    await expect(page).toHaveURL(/\/login/)
    await expect(
      page.getByRole('button', { name: 'Zaloguj się' }),
      'krok 2: ekran logowania po wylogowaniu po polsku',
    ).toBeVisible()

    // Krok 3: ponowne logowanie i F5 — UI po polsku.
    await page.getByTestId('login-email').fill(ADMIN_EMAIL)
    await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
    await page.getByTestId('login-submit').click()
    await expect(page.getByRole('button', { name: 'Język' })).toBeVisible()
    await page.reload()
    await expect(
      page.getByRole('button', { name: 'Język' }),
      'krok 3: F5 trzyma polski',
    ).toBeVisible()
  })

  test('SC-E5-H9-04 krok 4: nowy czat przy UI PL — opis i powitanie po polsku (sprawdzone GET-em)', async ({
    page,
    request,
  }) => {
    // Limiter potrafi przyjąć to logowanie (T16) — budżet na 2 czekania okna po 61 s.
    test.setTimeout(240_000)
    await page.goto('/login')
    await page.getByTestId('login-email').fill(ADMIN_EMAIL)
    await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
    await loginUiResilient(page)
    await expect(page.getByTestId('home-banner')).toBeVisible()
    // UI po polsku: konto bez wyboru rozwiązuje się do „pl” (`authState.applyUser`) — persona
    // „użytkownik przy UI PL” jest spełniona od zalogowania.
    await expect(page.getByRole('button', { name: 'Język' })).toBeVisible()

    await page.getByRole('navigation').getByRole('link', { name: 'Czat' }).click()
    await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel(/Nazwa/).fill('E2E H9-04 czat')
    await dialog.getByRole('button', { name: 'Utwórz' }).click()
    await expect(page).toHaveURL(/\/chat\/[^/]+$/)
    const chatId = page.url().split('/chat/')[1] ?? ''
    // Sprzątanie w afterEach — także przy porażce asercji (resztki po próbie 1 psuły retry).
    chatCreated = true

    // Front dziś wysyła samo `{name}` — backend domyśla się angielskiego upstreamu
    // (prologue „Hi! I'm your assistant…”). T5: front wysyła `chat.defaultDescription`
    // i `chat.defaultPrologue` w języku UI; weryfikacja treścią z SCENARIOS.md przez GET.
    const token = await apiTokenOnce(request)
    const response = await request.get(`${API_URL}/api/v1/chats/${chatId}`, {
      headers: { authorization: `Bearer ${token}` },
    })
    const body = (await response.json()) as {
      data: { description: string; prompt_config?: { prologue?: string } }
    }
    expect(body.data.description, 'krok 4: opis nowego czatu po polsku (T5)').toContain(
      'Pomocny asystent',
    )
    expect(
      body.data.prompt_config?.prologue ?? '',
      'krok 4: powitanie asystenta po polsku (T5)',
    ).toContain('Cześć')
  })

  test.afterEach(async ({ request }) => {
    if (!chatCreated) return
    chatCreated = false
    await deleteAllChats(request, await apiTokenOnce(request))
  })
})
