// Scenariusze SC-E5-H9-05…08 (work/wp/E5-H9/SCENARIOS.md; brief T1b): testy e2e pisane PRZED
// implementacją — czerwone tam, gdzie UI dziś odbiega (U8 nazwy, K5 tabele 390 px, K3
// „copy.failed”). Zgodnie z briefem funkcji NIE implementują: brak testidów cienia przewijania,
// sticky kolumny czy komunikatu porażki kopiowania raportuje wyrocznia Playwrighta jako porażkę
// testu. Backend nie jest mockowany — te same trasy woła UI; resztki danych sprząta `afterAll`
// przez API (wzór s13/s21).
import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset, deleteAllChats } from './helpers'
import { deleteDataset } from './helpers/files'
import { createSession, uploadDocument } from './helpers/h9'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (E5-H8c T11): limiter logowań liczy każdą próbę (10/min), wzór s21.
const session = uiSession('s24-h9-b')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Współdzielony token admina na cały bieg pliku (jeden `apiLogin` — limiter logowań). */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: Parameters<typeof apiLogin>[0]): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

/** Ślady danych scenariuszy do sprzątania po biegu (reset K9 biegnie raz, przed zestawem). */
const datasetIds: string[] = []
let createdKey: string | null = null
let chatsTouched = false

test.afterAll(async ({ request }) => {
  if (adminTokenPromise === undefined) return
  const token = await adminTokenPromise
  if (chatsTouched) await deleteAllChats(request, token)
  for (const id of datasetIds) await deleteDataset(request, token, id)
  if (createdKey !== null) {
    const response = await request.delete(`${API_URL}/api/v1/system/tokens/${createdKey}`, {
      headers: { authorization: `Bearer ${token}` },
    })
    expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
  }
})

test('SC-E5-H9-05: nazwy i etykiety mówią, co znaczą (U8)', async ({ page, request }) => {
  test.setTimeout(120_000)
  const token = await adminToken(request)
  const datasetId = await createDataset(request, token, 'E2E SC-E5-H9-05')
  datasetIds.push(datasetId)
  await uploadDocument(request, token, datasetId, 'e2e-sc05.txt')

  // Krok 1: lista dokumentów (≥ xl, gdzie kolumna jest widoczna) — kolumna metody to „Metoda chunkowania”.
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto(`/dataset/files/${datasetId}`)
  const grid = page.getByTestId('files-grid')
  await expect(grid.getByRole('row').filter({ hasText: 'e2e-sc05.txt' })).toBeVisible()
  await expect(grid.getByRole('columnheader', { name: 'Metoda chunkowania' })).toBeVisible()
  await expect(grid.getByRole('columnheader', { name: 'Metoda parsowania' })).toHaveCount(0)

  // Krok 2: Konfiguracja → „Dodaj zakres” — nowy wiersz z PUSTYMI „Od”/„Do” (nie ukryte „1-1”),
  // fokus w polu „Od”; sprzątamy wiersz, by nie zostawiać śladów w formularzu.
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByTestId('pages-add')).toBeVisible()
  await page.getByTestId('pages-add').click()
  await expect(page.getByTestId('pages-from-0')).toHaveValue('')
  await expect(page.getByTestId('pages-to-0')).toHaveValue('')
  await expect(page.getByTestId('pages-from-0')).toBeFocused()
  await page.getByTestId('pages-remove-0').click()

  // Krok 3: Admin → Status systemu — „Ostatni sygnał” z podpowiedzią „heartbeat usługi”.
  await page.getByRole('navigation').getByRole('link', { name: 'Administracja' }).click()
  await expect(page).toHaveURL(/\/admin\/users$/)
  await page.getByTestId('admin-tab-status').click()
  const workers = page.getByTestId('admin-status-workers')
  // Czekamy na tętno workera ze stosu testowego — wzorzec pasuje do starej i nowej etykiety.
  await expect(workers.getByText(/Ostatni sygnał|Tętno/).first()).toBeVisible({ timeout: 30_000 })
  await expect(workers.getByText('Ostatni sygnał')).toBeVisible()
  await expect(workers.getByText('Tętno')).toHaveCount(0)
  await workers.getByText('Ostatni sygnał').first().hover()
  await expect(page.getByText('heartbeat usługi')).toBeVisible()

  // Krok 4: paginacja po polsku — „Wierszy na stronę”, „1–N z M”, bez angielskich resztek.
  await page.getByTestId('admin-tab-users').click()
  await expect(page).toHaveURL(/\/admin\/users$/)
  const footer = page.locator('.MuiTablePagination-root')
  await expect(footer).toContainText('Wierszy na stronę')
  await expect(footer).toContainText(/1–\d+ z \d+/)
  await expect(footer).not.toContainText('Rows per page')
  await expect(footer).not.toContainText('of')
})

test('SC-E5-H9-06: pusta lista czatów ma jedną akcję', async ({ page, request }) => {
  const token = await adminToken(request)
  await deleteAllChats(request, token) // stan pusty niezależny od innych plików biegu
  chatsTouched = true

  // Krok 1: lista pusta — DOKŁADNIE jeden przycisk „Utwórz czat” (ten w nagłówku ukryty).
  await page.goto('/chats')
  const empty = page.getByTestId('empty-state')
  await expect(empty).toBeVisible()
  await expect(page.getByRole('button', { name: 'Utwórz czat' })).toHaveCount(1)
  await expect(empty.getByRole('button', { name: 'Utwórz czat' })).toBeVisible()

  // Krok 2: czat utworzony → przycisk w nagłówku widoczny, stan pusty znika.
  await empty.getByRole('button', { name: 'Utwórz czat' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/Nazwa/).fill('E2E SC-E5-H9-06')
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  await page.goto('/chats')
  await expect(page.getByTestId('empty-state')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Utwórz czat' })).toBeVisible()
})

test.describe('SC-E5-H9-07 tabele na 390 px (U3)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('cień przewijania, sticky pierwsza kolumna, nagłówki bez ucięcia', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const token = await adminToken(request)
    const datasetId = await createDataset(request, token, 'E2E SC-E5-H9-07')
    datasetIds.push(datasetId)
    await uploadDocument(request, token, datasetId, 'e2e-sc07-dokument-o-dłuższej-nazwie.txt')

    await page.goto(`/dataset/files/${datasetId}`)
    const grid = page.getByTestId('files-grid')
    await expect(grid.getByRole('row').filter({ hasText: 'e2e-sc07' })).toBeVisible()

    // Krok 1: cień na prawej krawędzi (jest co przewijać); lewego jeszcze nie ma — K5 (testidy).
    const shadowRight = page.getByTestId('scroll-shadow-right')
    const shadowLeft = page.getByTestId('scroll-shadow-left')
    await expect(shadowRight).toBeVisible()
    await expect(shadowLeft).toHaveCount(0)

    // D3 (QA E5-H9-2): na 390 px przyklejona jest tylko kolumna Nazwa — checkbox zaznaczania
    // i menu ⋮ przewijają się z tabelą.
    const nameHeader = grid.locator('[role="columnheader"][data-field="name"]')
    await expect(nameHeader).toHaveCSS('position', 'sticky')
    const nameCell = grid
      .getByRole('row')
      .filter({ hasText: 'e2e-sc07' })
      .locator('[role="gridcell"][data-field="name"]')
    await expect(nameCell).toHaveCSS('position', 'sticky')
    await expect(grid.locator('[role="columnheader"][data-field="__check__"]')).not.toHaveCSS(
      'position',
      'sticky',
    )
    await expect(grid.locator('[role="columnheader"][data-field="actions"]')).not.toHaveCSS(
      'position',
      'sticky',
    )

    // Widoczny pas przewijanej treści: kontener minus przyklejona kolumna >= 150 px (D3).
    const scrollStrip = await grid
      .locator('.MuiDataGrid-virtualScroller')
      .evaluate((scroller: HTMLElement) => {
        const sticky = scroller.querySelector<HTMLElement>('[data-field="name"]')
        return scroller.clientWidth - (sticky?.offsetWidth ?? 0)
      })
    expect(scrollStrip, 'widoczny pas przewijanej treści (D3)').toBeGreaterThanOrEqual(150)

    // Krok 2: przewinięcie tabeli w poziomie → cień przenosi się na lewą krawędź.
    await grid.locator('.MuiDataGrid-virtualScroller').hover({ position: { x: 350, y: 120 } })
    await page.mouse.wheel(600, 0)
    await expect(shadowLeft).toBeVisible()

    // Nagłówki pełne albo z wielokropkiem i `title` — nigdy ucięte na krawędzi (U3/K5).
    const truncated = await grid.locator('[role="columnheader"]').evaluateAll((cells) =>
      cells
        .map((cell) => {
          const title = cell.querySelector('.MuiDataGrid-columnHeaderTitle') ?? cell
          if (title.scrollWidth <= title.clientWidth + 1) return null
          const holder = title.closest('[title]') ?? (title.hasAttribute('title') ? title : null)
          const style = getComputedStyle(title)
          const hint = holder?.getAttribute('title') ?? ''
          return style.textOverflow === 'ellipsis' && hint !== '' ? null : (title.textContent ?? '')
        })
        .filter((text): text is string => text !== null),
    )
    expect(truncated, 'nagłówki ucięte bez wielokropka i title').toEqual([])

    // Admin → Użytkownicy (k1): przyklejony E-mail (identyfikator użytkownika), ⋮ przewija się,
    // a pas przewijanej treści >= 150 px (T12 — QA końcowy A: przy 200 px pas wynosił ~140 px).
    // Na 390 px nawigacja boczna jest za hamburgerem — wchodzimy prosto z URL (wzór kroku 3).
    await page.goto('/admin/users')
    await expect(page).toHaveURL(/\/admin\/users$/)
    const usersGrid = page.getByTestId('admin-users').locator('.MuiDataGrid-root')
    const adminRow = usersGrid.getByRole('row').filter({ hasText: 'admin@wd.test' }).first()
    await expect(adminRow).toBeVisible()
    const emailHeader = usersGrid.locator('[role="columnheader"][data-field="email"]')
    await expect(emailHeader).toHaveCSS('position', 'sticky')
    const emailCell = adminRow.locator('[role="gridcell"][data-field="email"]')
    await expect(emailCell).toHaveCSS('position', 'sticky')
    await expect(usersGrid.locator('[role="columnheader"][data-field="actions"]')).not.toHaveCSS(
      'position',
      'sticky',
    )
    const usersStrip = await usersGrid
      .locator('.MuiDataGrid-virtualScroller')
      .evaluate((scroller: HTMLElement) => {
        const sticky = scroller.querySelector<HTMLElement>('[data-field="email"]')
        return scroller.clientWidth - (sticky?.offsetWidth ?? 0)
      })
    expect(
      usersStrip,
      'widoczny pas przewijanej treści w Użytkownikach (k1)',
    ).toBeGreaterThanOrEqual(150)
  })

  test('kroki 3–5: narzędzia admina wyrównane, szkielet ładowania, profil 60 znaków', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)

    // Krok 4 NAJPIERW (świeża nawigacja): opóźniona odpowiedź trasy — wstrzymujemy chunk strony Użytkownicy.
    let release: (() => void) | undefined
    const gate = new Promise<void>((resolve) => (release = resolve))
    await page.route(/\/assets\/UsersPage-[^/]*\.js/, async (route) => {
      await gate
      await route.continue()
    })
    await page.goto('/admin/users')
    await expect(page.locator('.MuiSkeleton-root').first(), 'krok 4: szkielet (U5)').toBeVisible()
    release?.()
    const search = page.getByTestId('admin-users-search')
    await expect(search).toBeVisible()

    // Krok 3 (390 px): „Nowy użytkownik” startuje przy tej samej lewej krawędzi (useFlexGap
    // FilesToolbar — bez wcięcia 16 px od margin-left).
    const button = page.getByTestId('admin-users-new')
    await expect(button).toBeVisible()
    const [searchBox, buttonBox] = await Promise.all([search.boundingBox(), button.boundingBox()])
    expect(
      Math.abs((buttonBox?.x ?? 0) - (searchBox?.x ?? 0)),
      `krok 3: lewe krawędzie pola (${searchBox?.x}) i przycisku (${buttonBox?.x})`,
    ).toBeLessThanOrEqual(1)

    // Krok 5: nazwa dokładnie 60 znaków (T11, dodatek) BEZ spacji zawija się w karcie
    // (overflow-wrap:anywhere), nie wychodzi poza kartę; wiersz strefy czasowej pokazuje
    // pełne „Nie ustawiono”.
    const me = await request.get(`${API_URL}/api/v1/users/me`, {
      headers: { authorization: `Bearer ${token}` },
    })
    const meBody = (await me.json()) as { data: { nickname: string } }
    const originalName = meBody.data.nickname
    const name60 = 'EwaKarolinaKatarzynaZofiaMariaElżbietaJadwigaBarbaraKrystyna'
    expect(name60, 'nazwa profilu ma dokładnie 60 znaków').toHaveLength(60)
    await page.goto('/user-setting/profile')
    await page.getByTestId('profile-edit-name').click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel(/Nazwa/).fill(name60)
    await dialog.getByRole('button', { name: 'Zapisz' }).click()
    await expect(dialog).toHaveCount(0)
    const nameRow = page.getByTestId('profile-row-name')
    await expect(nameRow).toContainText(name60)
    const cardWidths = await nameRow
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")][1]')
      .evaluate((card: HTMLElement) => ({ scroll: card.scrollWidth, client: card.clientWidth }))
    expect(
      cardWidths.scroll,
      `krok 5: nazwa 60 znaków nie wychodzi poza kartę (${cardWidths.scroll} > ${cardWidths.client})`,
    ).toBeLessThanOrEqual(cardWidths.client + 1)
    const emptyValue = page.getByTestId('profile-row-timezone').getByText('Nie ustawiono')
    await expect(emptyValue).toBeVisible()
    const overflow = await emptyValue.evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(overflow, 'krok 5: „Nie ustawiono” pełne, bez ucięcia').toBeLessThanOrEqual(1)

    // Przywrócenie nazwy przez API — kolejne pliki biegu widzą konto z seedu.
    const restore = await request.patch(`${API_URL}/api/v1/users/me`, {
      headers: { authorization: `Bearer ${token}` },
      data: { nickname: originalName },
    })
    expect(restore.status(), 'przywrócenie nazwy admina').toBe(200)
  })
})

test.describe('SC-E5-H9-08 kopiowanie, które się nie udało, mówi o tym', () => {
  type InitScript = Parameters<Page['addInitScript']>[0]

  /** Oba mechanizmy zawodzą: `navigator.clipboard.writeText` odrzuca, `execCommand` zwraca false. */
  function clipboardDenied(): InitScript {
    return () => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: () => Promise.reject(new DOMException('odmowa', 'NotAllowedError')) },
        configurable: true,
      })
      document.execCommand = ((commandId: string) =>
        commandId !== 'copy') as typeof document.execCommand
    }
  }

  // Tekst porażki z K3 (kontrakt WP E5-H9) — dziś UI pokazuje wariant bez „(Ctrl+C)” albo nic.
  const COPY_FAILED = 'Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie (Ctrl+C)'

  test('asystent i klucz API: komunikat porażki, nigdy „Skopiowano”; nota MCP', async ({
    page,
    request,
  }) => {
    await page.addInitScript(clipboardDenied())
    const token = await adminToken(request)

    // Krok 1a: kopiowanie odpowiedzi asystenta (prologue sesji czatu).
    const chatId = await createChat(request, token, { name: 'E2E SC-E5-H9-08' })
    chatsTouched = true
    const sessionId = await createSession(request, token, chatId)
    await page.goto(`/chat/${chatId}?conversationId=${sessionId}`)
    const message = page.getByTestId('message-assistant').first()
    await expect(message).toBeVisible()
    await message.getByRole('button', { name: 'Kopiuj' }).click()
    await expect(message).toContainText(COPY_FAILED)
    await expect(message).not.toContainText('Skopiowano')

    // Krok 1b: klucz API — komunikat porażki w dialogu, bez fałszywego „Skopiowano”.
    await page.goto('/user-setting/api')
    await page.getByRole('button', { name: 'Utwórz klucz' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // M1 (QA E5-H9-2): fokus po otwarciu dialogu od razu w polu nazwy.
    await expect(dialog.getByRole('textbox', { name: 'Nazwa (opcjonalna)' })).toBeFocused()
    await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
    const tokenField = dialog.getByTestId('settings-new-token')
    await expect(tokenField).toBeVisible()
    const keyValue = ((await tokenField.textContent()) ?? '').trim()
    expect(keyValue, 'pełny token zaczyna się od „ragflow-”').toMatch(/^ragflow-/)
    createdKey = keyValue // sprzątanie w afterAll także wtedy, gdy asercje kopiowania poniżej padną
    await dialog.getByRole('button', { name: 'Kopiuj token' }).click()
    await expect(dialog.getByTestId('settings-copy-error')).toContainText(COPY_FAILED)
    await expect(dialog).not.toContainText('Skopiowano')

    // Krok 2: karta „Serwer MCP” — nota odsyła do runbooka TEKSTEM (bez martwego linku).
    await expect(page.getByTestId('mcp-card')).toContainText(
      'Instrukcja: runbook administratora, §13 Serwer MCP',
    )
  })
})
