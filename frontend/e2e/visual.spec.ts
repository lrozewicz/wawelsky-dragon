// Przegląd wizualny kluczowych ekranów (analiza 2026-10-09): wady wizualne (nakładanie, ucięcia, okna poza
// ekranem, nieczytelne etykiety) znajdował dopiero właściciel. Ten spec dla każdego ekranu × wariantu
// (jasny 1280, ciemny 1280, jasny 390) robi dwie rzeczy:
//   1. `expectNoLayoutDefects` — deterministyczna kontrola układu (helpers/layout.ts),
//   2. `toHaveScreenshot` — porównanie ze zrzutem wzorcowym w `visual.spec.ts-snapshots/`.
// Dane celowo „trudne”: nazwa bazy 120 znaków, długi dokument, długa nazwa czatu.
// Zrzuty wzorcowe: brakujące zapisuje pierwszy bieg (`updateSnapshots: 'missing'` w playwright.config.ts);
// zmiana wyglądu = świadoma aktualizacja `bun run e2e -- e2e/visual.spec.ts --update-snapshots` + obejrzenie
// nowych plików (Read) i wpis w raporcie TL. Zrzuty wzorcowe służą też jako makiety stanu „jest” (08 §Reguły UX).
// Logowanie RAZ na plik (wzór E5-H8c T11): limiter logowań 10/min per IP+e-mail — plik z ~20 testami
// logującymi się w każdym teście tripił falę 429 (ujawniło się przy wzorcach T8).
import { existsSync } from 'node:fs'

import type { Locator, Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createChat, createDataset, seedCorpus } from './helpers'
import { deleteAllFiles } from './helpers/files'
import { dropFile } from './helpers/dnd'
import { SAMPLE_MIME, sampleBytes } from './helpers/h9'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const LONG_DATASET =
  'Baza wiedzy o bardzo długiej nazwie — roczniki statystyczne GUS 2019–2024, rynek pracy, ' +
  'ludność, mieszkania i ceny'
const LONG_CHAT = 'Asystent analityczny dla działu statystyki publicznej i raportowania kwartalnego'
const DOC_NAME = 'raport-rynek-pracy-2024-wersja-ostateczna-po-korekcie-redakcyjnej.txt'
const DOC_BODY = Array.from(
  { length: 40 },
  (_, i) =>
    `Akapit ${i + 1}. Stopa bezrobocia rejestrowanego w Polsce na koniec 2022 roku wyniosła 5,2%, ` +
    'a według BAEL przeciętna w roku stopa bezrobocia wyniosła 2,9%. Dane pochodzą z tablic rynku pracy.',
).join('\n\n')

type Variant = { name: string; viewport: { width: number; height: number }; dark: boolean }

const LIGHT_1280: Variant = {
  name: 'light-1280',
  viewport: { width: 1280, height: 800 },
  dark: false,
}
const DARK_1280: Variant = { name: 'dark-1280', viewport: { width: 1280, height: 800 }, dark: true }
const LIGHT_390: Variant = { name: 'light-390', viewport: { width: 390, height: 844 }, dark: false }

const VARIANTS: Variant[] = [LIGHT_1280, DARK_1280, LIGHT_390]

const session = uiSession('visual')
test.use({ storageState: session.statePath })
// Retry wyłączony (wzór s24-h9-a): zrzuty są deterministyczne (animacje wyłączone, czcionki
// awaited), a retry w NOWYM workerze nie odpala beforeAll — test startowałby bez pliku sesji
// (statePath liczone z PID; ENOENT) i bez seeda, przegrywając w sposób niediagnostyczny.
test.describe.configure({ retries: 0 })

let datasetId = ''
let documentId = ''
let chatId = ''

// Kolejność hooków ma znaczenie: NAJPIERW reset i seed (nowe konto admina), DOPIERO POTEM
// logowanie — sesja z konta sprzed resetu byłaby unieważniona (refresh → 401 → ekran logowania).
test.beforeAll(async ({ browser }) => {
  // Kontekst API tymczasowy, BEZ storageState: fixture `request` dziedziczy `storageState`
  // z opcji PIERWSZEGO testu workera — przy selekcji --grep (pierwszy pasujący test z sesją
  // z pliku) jego utworzenie czyta plik sesji, który dopiero hook B niżej zapisze, i pada
  // na ENOENT zanim cokolwiek zaseeduje (ujawnione biegiem wzorców T7). Fixture `browser`
  // pliku sesji nie czyta, a jawne `storageState: undefined` wyłącza odczyt w newContext.
  const api = await browser.newContext({ storageState: undefined })
  const request = api.request
  await resetDb(request)
  const token = await apiLogin(request)
  const corpus = await seedCorpus(request, token, {
    datasetName: LONG_DATASET,
    documentName: DOC_NAME,
    documentBody: DOC_BODY,
  })
  datasetId = corpus.datasetId
  documentId = corpus.documentId
  await createDataset(request, token, 'Pusta baza')
  chatId = await createChat(request, token, { name: LONG_CHAT, datasetIds: [datasetId] })
  await api.close()
})

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

// Stan wyjściowy dla kolejnych specyfikacji: seed K9 jak po global-setup.
test.afterAll(async ({ request }) => {
  await resetDb(request)
})

/** Ekran gotowy: brak wskaźników ładowania, czcionki wczytane. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.MuiCircularProgress-root, .MuiSkeleton-root')).toHaveCount(0, {
    timeout: 15_000,
  })
  await page.evaluate(() => document.fonts.ready)
}

async function check(
  page: Page,
  screen: string,
  variant: Variant,
  options: { fullPage?: boolean } = {},
): Promise<void> {
  await settle(page)
  await expectNoLayoutDefects(page, `${screen} (${variant.name})`, { soft: true })
  const name = `${screen}-${variant.name}.png`
  const updating = test.info().config.updateSnapshots === 'all'
  // Brak wzorca nie oblewa biegu (wzorce tworzy się świadomie: `--update-snapshots` w kontenerze agentów,
  // potem obejrzenie Read i commit) — zrzut idzie jako załącznik z adnotacją `visual-baseline-missing`.
  if (!updating && !existsSync(test.info().snapshotPath(name))) {
    test.info().annotations.push({ type: 'visual-baseline-missing', description: name })
    // Zrzut zgodny z options (T11, dodatek): pełna strona tam, gdzie wzorzec byłby fullPage.
    await test.info().attach(name, {
      body: await page.screenshot(options.fullPage ? { fullPage: true } : undefined),
      contentType: 'image/png',
    })
    return
  }
  await expect(page).toHaveScreenshot(name, options.fullPage ? { fullPage: true } : undefined)
}

/**
 * Wzorzec TYLKO elementu (dialog albo szuflada): tło strony zawiera dane zależne od środowiska
 * — daty kart i list („17 paź 2026” = dzień biegu), port stosu w adresie MCP, losowe prefiksy
 * tokenów kluczy i liczbę plików na liście datasetu (upload z testu T8 w pełnym verify-full) —
 * więc zrzut całostronicowy różniłby się między biegami (2–15 % pikseli: „Nowy klucz API” 4–5 %,
 * szuflada 1440 do ~15 % przy 4 plikach w tle, czerwień T7 + review). W MUI v9 `role="dialog"`
 * leży bezpośrednio na paperze (Dialog.js: PaperSlot additionalProps), więc locator
 * `getByRole('dialog')` to sam element okna; szuflada to `.MuiDrawer-paper`. Cień elewacji
 * wychodzi poza prostokąt elementu i jest przycięty — makieta pokazuje samą treść panelu.
 * Kontrola układu strony pod panelem zostaje (jak w `check()`), w wariancie miękkim.
 */
async function elementShot(
  page: Page,
  element: Locator,
  name: string,
  variant: Variant,
): Promise<void> {
  await settle(page)
  await expectNoLayoutDefects(page, `${name} (${variant.name})`, { soft: true })
  await expect(element).toHaveScreenshot(`${name}-${variant.name}.png`)
}

for (const variant of VARIANTS) {
  test.describe(`wygląd logowania ${variant.name}`, () => {
    // Ekran logowania wymaga świeżej przeglądarki — bez sesji pliku (wzór s24-h9-a2).
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.dark ? 'dark' : 'light',
      storageState: undefined,
    })

    test(`ekran logowania — ${variant.name}`, async ({ page }) => {
      await page.goto('/login')
      await check(page, 'login', variant)
    })
  })

  test.describe(`wygląd ${variant.name}`, () => {
    test.use({ viewport: variant.viewport, colorScheme: variant.dark ? 'dark' : 'light' })

    test(`ekrany po zalogowaniu — ${variant.name}`, async ({ page }) => {
      // Sesja z cookie pliku (jeden `session.login` w beforeAll) — bez formularza logowania.
      await page.goto('/')
      const screens: [string, string][] = [
        ['home', '/'],
        ['datasets', '/datasets'],
        ['dataset-files', `/dataset/files/${datasetId}`],
        ['dataset-configuration', `/dataset/configuration/${datasetId}`],
        ['dataset-retrieval', `/dataset/retrieval/${datasetId}`],
        ['chats', '/chats'],
        ['chat', `/chat/${chatId}`],
        ['searches', '/searches'],
        ['files', '/files'],
        ['settings-model', '/user-setting/model'],
        ['settings-profile', '/user-setting/profile'],
        ['admin-users', '/admin/users'],
      ]
      for (const [screen, path] of screens) {
        await test.step(screen, async () => {
          await page.goto(path)
          await check(page, screen, variant)
        })
      }
      await test.step('chunks', async () => {
        await page.goto(`/dataset/files/${datasetId}`)
        await page.getByRole('link', { name: DOC_NAME }).click()
        await expect(page).toHaveURL(/\/chunk\/parsed\/chunks/)
        await check(page, 'chunks', variant)
      })
    })
  })
}

// ── Wzorce T8 (WP E5-H9): Klucze API, fokus vs błąd, upload, Pliki 390 px po przewinięciu ──

/** Warianty wzorców T8 — Klucze API w obu motywach i obu szerokościach 1440/390 (SCENARIOS.md „Wygląd”). */
const T8_VARIANTS: Variant[] = [
  { name: 'light-1440', viewport: { width: 1440, height: 900 }, dark: false },
  { name: 'dark-1440', viewport: { width: 1440, height: 900 }, dark: true },
  { name: 'light-390', viewport: { width: 390, height: 844 }, dark: false },
  { name: 'dark-390', viewport: { width: 390, height: 844 }, dark: true },
]

test.describe('klucze API — lista i karta MCP (T8)', () => {
  // Jeden klucz w liście: wzorzec pokazuje wiersz siatki, nie stan pusty (ślad sprząta resetDb z afterAll).
  test.beforeAll(async ({ request }) => {
    const token = await apiLogin(request)
    const response = await request.post(`${API_URL}/api/v1/system/tokens?name=E2E visual`, {
      headers: { authorization: `Bearer ${token}` },
    })
    expect(response.status(), 'POST /api/v1/system/tokens').toBe(200)
  })

  for (const variant of T8_VARIANTS) {
    // use() per POD-describe: use() w pętli w jednym describe nadpisuje opcje WSZYSTKICH jego
    // testów (ostatni wariant wygrywa) — każdy wariant potrzebuje własnej grupy.
    test.describe(`motyw ${variant.name}`, () => {
      test.use({ viewport: variant.viewport, colorScheme: variant.dark ? 'dark' : 'light' })
      test('zrzut całej strony', async ({ page }) => {
        // fullPage: karta „Serwer MCP” i lista kluczy są jeden pod drugim — jeden zrzut obejmuje obie.
        await page.goto('/user-setting/api')
        await check(page, 'api-keys', variant, { fullPage: true })
      })
    })
  }
})

test.describe('pole w fokusie vs z błędem (T8; SC-E5-H9-01 k. 1–2)', () => {
  for (const variant of [LIGHT_1280, DARK_1280]) {
    test.describe(`motyw ${variant.name}`, () => {
      test.use({ viewport: variant.viewport, colorScheme: variant.dark ? 'dark' : 'light' })
      test('konfiguracja datasetu', async ({ page }) => {
        await page.goto(`/dataset/configuration/${datasetId}`)
        // Stan fokusu (k. 1): ramka i etykieta w akcencie `secondary` — celowo nie czerwone.
        const field = page.getByRole('textbox', { name: 'Nazwa', exact: true })
        await field.click()
        await expect(field).toBeFocused()
        // Pole w kadrze na pewno: formularz jest wyższy niż okno, a pozycja przewinięcia po
        // kliku nie jest deterministyczna (obserwowane zrzuty i z polem, i z dołem formularza).
        await field.scrollIntoViewIfNeeded()
        await expect(field).toBeFocused()
        await check(page, 'field-focus', variant)

        // Stan błędu (k. 2): czyszczenie wymaganego pola + „Zapisz” — dopiero teraz czerwień
        // (ramka, etykieta nad polem, komunikat pod polem), wyraźnie inna niż fokus powyżej.
        await field.fill('')
        await page.getByRole('button', { name: 'Zapisz' }).click()
        await expect(page.getByText('Pole wymagane')).toBeVisible()
        await field.scrollIntoViewIfNeeded()
        await check(page, 'field-error', variant)
      })
    })
  }
})

test.describe('dialog uploadu „Przesłano 3 z 3” (T8; SC-E5-H9-03 k. 2)', () => {
  test.use({ viewport: { width: 1280, height: 800 } })
  test('koniec przesyłania trzech plików', async ({ page }) => {
    await page.goto(`/dataset/files/${datasetId}`)
    await page.getByTestId('files-add').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    for (const name of ['sample.pdf', 'sample.docx', 'sample.xlsx'] as const) {
      await dropFile(
        page,
        page.getByTestId('upload-dropzone'),
        sampleBytes(name),
        name,
        SAMPLE_MIME[name],
      )
    }
    await page.getByTestId('upload-start').click()
    await expect(dialog.getByText('Przesłano 3 z 3'), 'koniec uploadu (T4)').toBeVisible({
      timeout: 60_000,
    })
    await check(page, 'upload-done', LIGHT_1280)
  })
})

test.describe('tabela Plików 390 px po przewinięciu (T8; SC-E5-H9-07 k. 2)', () => {
  // /files to menedżer plików (nie dokumenty datasetów) — bez zasiewu jest pusty (EmptyState,
  // brak siatki); dwa pliki o długich nazwach wymuszają poziomy przewijak (K5). Główna pętla
  // wzorców bierze stan pusty „files-390” WCZEŚNIEJ, więc obie makiety są spójne.
  test.beforeAll(async ({ request }) => {
    const token = await apiLogin(request)
    for (const name of [
      'wzorzec-t8-raport-zestawienie-kwartalne-roczniki-gus-390.txt',
      'wzorzec-t8-zestawienie-drugie-dla-poziomego-przewijania-tabeli.txt',
    ]) {
      const response = await request.post(`${API_URL}/api/v1/files`, {
        headers: { authorization: `Bearer ${token}` },
        multipart: {
          file: { name, mimeType: 'text/plain', buffer: Buffer.from('Treść wzorca T8', 'utf-8') },
        },
      })
      expect(response.status(), `POST /api/v1/files (${name})`).toBe(200)
    }
  })

  test.use({ viewport: { width: 390, height: 844 } })
  test('cień na lewej krawędzi i przyklejona pierwsza kolumna', async ({ page }) => {
    await page.goto('/files')
    await check(page, 'files-390', LIGHT_390)
    // Przewinięcie w poziomie: cień przenosi się na lewą krawędź, pierwsza kolumna zostaje.
    await page.locator('.MuiDataGrid-virtualScroller').hover({ position: { x: 350, y: 120 } })
    await page.mouse.wheel(600, 0)
    await expect(page.getByTestId('scroll-shadow-left')).toBeVisible()
    await check(page, 'files-390-scrolled', LIGHT_390)
  })
})

// ── Wzorce T7 (WP E6-1b): sekcja „Metadane” konfiguracji, szuflada metadanych dokumentu
// i kreator filtra metadanych (Ręczny, 2 warunki) w szufladzie czatu — oba motywy, 390 i 1440 px
// (SCENARIOS.md „Wygląd”; ta sama macierz wariantów co T8_VARIANTS). Dane wsiewa przedAll przez
// API (kontrakt WP E6-1b §1): pola + przełącznik na wspólnej bazie i metadane dokumentu —
// sekcja i szuflada pokazują wypełniony stan (nie puste stany). Bieg głównego pętli wzorców
// i testy T8 odbyły się WCZEŚNIEJ (kolejność deklaracji), więc ich wzorce niczego z tego nie widzą.

/** Wartość 200 znaków (SC-E6-1b-03 krok 4): zawijanie w szufladzie, wielokropek chipa. */
const LONG_VALUE = 'x'.repeat(200)

test.describe('wzorce metadanych E6-1b (T7)', () => {
  test.beforeAll(async ({ request }) => {
    const token = await apiLogin(request)
    const headers = { authorization: `Bearer ${token}` }
    // Pola metadanych (PUT …/metadata/config) i przełącznik (zwykły PUT datasetu, kontrakt §1).
    const config = await request.put(`${API_URL}/api/v1/datasets/${datasetId}/metadata/config`, {
      headers,
      data: {
        metadata: [
          { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane', enum: null },
          {
            key: 'typ',
            type: 'string',
            description: 'Rodzaj dokumentu',
            enum: ['raport', 'rocznik', 'ustawa'],
          },
        ],
      },
    })
    expect(config.status(), 'PUT /api/v1/datasets/{id}/metadata/config').toBe(200)
    const enabled = await request.put(`${API_URL}/api/v1/datasets/${datasetId}`, {
      headers,
      data: { parser_config: { enable_metadata: true } },
    })
    expect(enabled.status(), 'PUT /api/v1/datasets/{id} (enable_metadata)').toBe(200)
    // Metadane dokumentu: szuflada pokaże 3 wiersze (wartość 200 znaków ćwiczy zawijanie),
    // a `useMetaKeys` kreatora dostaje klucze rok/typ/region.
    const patched = await request.patch(
      `${API_URL}/api/v1/datasets/${datasetId}/documents/${documentId}`,
      { headers, data: { meta_fields: { rok: '2023', typ: 'raport', region: LONG_VALUE } } },
    )
    expect(patched.status(), 'PATCH /api/v1/datasets/{id}/documents/{id} (meta_fields)').toBe(200)
  })

  for (const variant of T8_VARIANTS) {
    test.describe(`motyw ${variant.name}`, () => {
      test.use({ viewport: variant.viewport, colorScheme: variant.dark ? 'dark' : 'light' })

      test('sekcja „Metadane” konfiguracji datasetu', async ({ page }) => {
        await page.goto(`/dataset/configuration/${datasetId}`)
        // Sekcja w kadrze od nagłówka: „Metadane”, przełącznik i „+ Pole” nad wierszami pól
        // (na 390 px sekcja jest wyższa niż okno — dolna krawędź przycina „Zaawansowane”).
        // −120 px koła po scrollIntoView zdejmuje przyklejony pasek aplikacji z nagłówka.
        const heading = page.getByRole('heading', { name: 'Metadane' })
        await heading.evaluate((el) => el.scrollIntoView({ block: 'start' }))
        const box = await heading.boundingBox()
        if (box !== null) {
          await page.mouse.move(box.x + 40, Math.max(box.y + 8, 70))
          await page.mouse.wheel(0, -120)
        }
        await check(page, 'metadata-config', variant)
      })

      test('szuflada metadanych dokumentu', async ({ page }) => {
        await page.goto(`/dataset/files/${datasetId}`)
        const row = page.getByRole('row').filter({ hasText: DOC_NAME })
        await expect(row).toBeVisible()
        await row.getByTestId('row-actions-menu').click()
        await page.getByRole('menuitem', { name: 'Metadane' }).click()
        await expect(page.getByRole('dialog', { name: DOC_NAME })).toBeVisible()
        // Wzorzec TYLKO szuflady (jak dialogi T4): tło (lista plików) zależy od biegu —
        // w pełnym verify-full test uploadu T8 dokłada 3 pliki przed szufladą (4 vs 1
        // w wąskich biegach), a „Data przesłania” zależy od zegara — wzorzec całostronicowy
        // 1440 rozjeżdżał się o ~2–15 % (czerwień verify-full T7, review).
        await elementShot(
          page,
          page.locator('.MuiDrawer-paper').filter({ hasText: DOC_NAME }),
          'metadata-drawer',
          variant,
        )
      })

      test('kreator filtra metadanych w szufladzie czatu (Ręczny, 2 warunki)', async ({ page }) => {
        await page.goto(`/chat/${chatId}`)
        await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
        await page.getByRole('tab', { name: 'Asystent' }).click()
        const advanced = page.getByRole('button', { name: 'Zaawansowane' })
        if ((await advanced.getAttribute('aria-expanded')) === 'false') await advanced.click()
        await page.getByText('Filtr metadanych', { exact: true }).click()
        const modes = page.getByRole('radiogroup', { name: 'Tryb filtra metadanych' })
        await expect(modes).toBeVisible()
        await modes.getByRole('radio', { name: 'Ręczny' }).check()
        const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
        await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
        await page.getByRole('option', { name: 'typ', exact: true }).click()
        await warunek1.getByRole('combobox', { name: 'Operator' }).click()
        await page.getByRole('option', { name: '=', exact: true }).click()
        await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
        await page.getByRole('option', { name: 'raport' }).click()
        await page.getByRole('button', { name: '+ Warunek' }).click()
        const warunek2 = page.getByRole('group', { name: 'Warunek 2' })
        await warunek2.getByRole('combobox', { name: 'Klucz' }).click()
        await page.getByRole('option', { name: 'rok', exact: true }).click()
        await warunek2.getByRole('combobox', { name: 'Operator' }).click()
        await page.getByRole('option', { name: '=', exact: true }).click()
        await warunek2.getByRole('combobox', { name: 'Wartość' }).click()
        await page.getByRole('option', { name: '2023' }).click()
        // Oba warunki w kadrze: przewijak szuflady zakotwiczony na tytule sekcji (block:'start').
        // Pozycja przewinięcia z klików comboboxów NIE jest powtarzalna między biegami (klik
        // przewija tylko element niecałkowicie widoczny; kilka px różnicy układu zmienia wynik —
        // diff wzorca light/dark-390, wyrocznia 2026-10-13).
        await page
          .getByText('Filtr metadanych', { exact: true })
          .evaluate((el) => el.scrollIntoView({ block: 'start' }))
        await check(page, 'metadata-filter-chat', variant)
      })
    })
  }
})

// ── Wzorce T4/V13-2 (SC-V13-12 k1, U12): krótkie dialogi 390 px, oba motywy ─────────────────
// Dialogi z listy k1 scenariusza: potwierdzenie usunięcia (baza z długą nazwą, czat, plik),
// zmiana nazwy czatu, „Nowy czat”, „Nowy klucz API”, „Odrzucić zmiany?”. Motyw wyrównuje je
// poniżej `sm` (margines 16 px, wysokość do treści); wzorce to makiety stanu „jest” — każdy
// dialog tylko otwieramy i zamykamy (Anuluj), nigdy nie potwierdzamy akcji nieodwracalnej.
// Dane bierze z seeda beforeAll (długa nazwa bazy/czatu ćwiczy zawijanie w komunikacie).

test.describe('wzorce krótkich dialogów 390 px (T4; SC-V13-12 k1)', () => {
  // Plik do wzorca „Usuń pliki” (ścieżka docelowa: root). Menedżer plików najpierw CZYSZCZONY
  // (wzorce T8 wczytały wcześniej swoje pliki i ich zrzuty już są zrobione): w tle dialogu
  // zostaje dokładnie jeden wiersz — deterministyczne tło wzorca w obu motywach.
  test.beforeAll(async ({ request }) => {
    const token = await apiLogin(request)
    await deleteAllFiles(request, token)
    const response = await request.post(`${API_URL}/api/v1/files`, {
      headers: { authorization: `Bearer ${token}` },
      multipart: {
        file: {
          name: 'wzorzec-t4-usuniecie-pliku.txt',
          mimeType: 'text/plain',
          buffer: Buffer.from('Treść wzorca T4', 'utf-8'),
        },
      },
    })
    expect(response.status(), 'POST /api/v1/files (wzorzec T4)').toBe(200)
  })

  for (const variant of T8_VARIANTS.filter((v) => v.viewport.width === 390)) {
    test.describe(`motyw ${variant.name}`, () => {
      test.use({ viewport: variant.viewport, colorScheme: variant.dark ? 'dark' : 'light' })

      test('potwierdzenie usunięcia bazy (długa nazwa w komunikacie)', async ({ page }) => {
        await page.goto('/datasets')
        await page
          .getByRole('button', {
            name: new RegExp(`Menu bazy wiedzy ${LONG_DATASET.slice(0, 40)}`),
          })
          .click()
        await page.getByRole('menuitem', { name: 'Usuń' }).click()
        const dialog = page.getByRole('dialog', { name: 'Usuń bazę wiedzy' })
        await expect(dialog).toBeVisible()
        await check(page, 'dialog-delete-dataset', variant)
        await dialog.getByRole('button', { name: 'Anuluj' }).click()
        await expect(dialog).toBeHidden()
      })

      test('potwierdzenie usunięcia czatu', async ({ page }) => {
        await page.goto('/chats')
        const card = page.getByTestId('chat-card').filter({ hasText: LONG_CHAT }).first()
        await expect(card).toBeVisible()
        await card
          .getByRole('button', { name: new RegExp(`Menu czatu ${LONG_CHAT.slice(0, 40)}`) })
          .click()
        await page.getByRole('menuitem', { name: 'Usuń' }).click()
        const dialog = page.getByRole('dialog', { name: 'Usuń czat' })
        await expect(dialog).toBeVisible()
        await elementShot(page, dialog, 'dialog-delete-chat', variant)
        await dialog.getByRole('button', { name: 'Anuluj' }).click()
        await expect(dialog).toBeHidden()
      })

      test('potwierdzenie usunięcia pliku', async ({ page }) => {
        await page.goto('/files')
        const row = page
          .getByRole('row')
          .filter({ hasText: 'wzorzec-t4-usuniecie-pliku.txt' })
          .first()
        await expect(row, 'wiersz pliku na liście').toBeVisible({ timeout: 30_000 })
        await row.getByTestId('row-actions-menu').click()
        await page.getByRole('menuitem', { name: 'Usuń' }).click()
        const dialog = page.getByRole('dialog', { name: 'Usuń pliki' })
        await expect(dialog).toBeVisible()
        await elementShot(page, dialog, 'dialog-delete-file', variant)
        await dialog.getByRole('button', { name: 'Anuluj' }).click()
        await expect(dialog).toBeHidden()
      })

      test('zmiana nazwy czatu', async ({ page }) => {
        await page.goto('/chats')
        const card = page.getByTestId('chat-card').filter({ hasText: LONG_CHAT }).first()
        await expect(card).toBeVisible()
        await card
          .getByRole('button', { name: new RegExp(`Menu czatu ${LONG_CHAT.slice(0, 40)}`) })
          .click()
        await page.getByRole('menuitem', { name: 'Zmień nazwę' }).click()
        const dialog = page.getByRole('dialog', { name: 'Zmień nazwę' })
        await expect(dialog).toBeVisible()
        await elementShot(page, dialog, 'dialog-rename-chat', variant)
        await dialog.getByRole('button', { name: 'Anuluj' }).click()
        await expect(dialog).toBeHidden()
      })

      test('„Nowy czat”', async ({ page }) => {
        await page.goto('/chats')
        // Przycisk strony zostaje „Utwórz czat”; dialog od T2b nosi tytuł „Nowy czat” (nazwa
        // dostępna) — po nim lokalizujemy okno (czerwień T7).
        await page.getByRole('button', { name: 'Utwórz czat' }).click()
        const dialog = page.getByRole('dialog', { name: 'Nowy czat' })
        await expect(dialog).toBeVisible()
        await elementShot(page, dialog, 'dialog-new-chat', variant)
        await dialog.getByRole('button', { name: 'Anuluj' }).click()
        await expect(dialog).toBeHidden()
      })

      test('„Nowy klucz API”', async ({ page }) => {
        await page.goto('/user-setting/api')
        await page.getByRole('button', { name: 'Utwórz klucz' }).click()
        const dialog = page.getByRole('dialog', { name: 'Nowy klucz API' })
        await expect(dialog).toBeVisible()
        await elementShot(page, dialog, 'dialog-new-api-key', variant)
        await dialog.getByRole('button', { name: 'Zamknij' }).click()
        await expect(dialog).toBeHidden()
      })

      test('„Odrzucić zmiany?”', async ({ page }) => {
        await page.goto(`/chat/${chatId}`)
        await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
        const drawer = page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
        await expect(drawer).toBeVisible()
        await drawer.getByRole('tab', { name: 'Model' }).click()
        const preset = drawer.getByRole('combobox', { name: 'Kreatywność' })
        const original = await preset.inputValue()
        await preset.click()
        const options = page.getByRole('listbox').getByRole('option')
        const other = (await options.allTextContents())
          .map((name) => name.trim())
          .find((name) => name !== original && name !== '')
        expect(other, 'lista presetów ma wartość inną niż bieżąca').toBeTruthy()
        await page.getByRole('option', { name: other, exact: true }).click()
        // Preset przyszedł (formularz brudny, listbox zamknięty) — bez tego pierwsze Esc
        // schodzi na domykający się listbox i dialog się nie otwiera (wzór: s31 sc12, bieg T4).
        await expect(preset, 'preset po zmianie').toHaveValue(other as string)
        await page.keyboard.press('Escape')
        const dialog = page.getByRole('dialog', { name: 'Odrzucić zmiany?' })
        await expect(dialog).toBeVisible()
        await check(page, 'dialog-discard-changes', variant)
        // „Odrzuć” domyka szufladę (wzór: s31-v13-2-sc12); „Wróć do edycji” zostawiłoby
        // formularz wciąż zmienionym i kolejne Esc otworzyłoby dialog ponownie.
        await dialog.getByRole('button', { name: 'Odrzuć' }).click()
        await expect(dialog).toBeHidden()
        await expect(drawer).toBeHidden({ timeout: 10_000 })
      })
    })
  }
})
