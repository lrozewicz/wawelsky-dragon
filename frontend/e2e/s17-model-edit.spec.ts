// Scenariusze E5-H8c (CONTRACT WP E5-H8c §1 i §4, SCENARIOS.md SC-03/04/05): edycja modelu —
// okno kontekstu („Okno kontekstu (tokeny)" zamiast „Max tokens"), równoległe zapytania (pole
// tylko dla vision/embedding, `extra` z zachowanymi kluczami obcymi) i widok Modele na 390 px.
// Na bazie (bez implementacji T3/T6) testy są CZERWONE z właściwej przyczyny: brak przycisku
// „Edytuj model", brak etykiety „Okno kontekstu (tokeny)" / „Równoległe zapytania", łamanie
// przycisków na wąskim ekranie. Instancje z modelami tworzymy przez API (helpers/models.ts),
// bo nazwy modeli są unikalne w rejestrze tenantu (duplikat → 102, K13 §4).
import type { APIRequestContext, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'
import {
  createInstanceWithModels,
  deleteInstance,
  getInstanceModels,
  listInstances,
  patchInstanceModel,
  setProfileLanguage,
} from './helpers/models'
import type { InstanceModelSpec } from './helpers/models'

/** Unikalny sufiks — duplikat (nazwa, typ) w rejestrze tenantu → 102 (K13 §4). */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

// Logowanie RAZ na plik (T11): limiter logowań liczy KAŻDĄ próbę (10/min per IP+e-mail,
// CONTRACT E5-2a §4) i jest współdzielony z całym biegiem verify-full — świeże logowanie w każdym
// z ~20 testów tripiło falę 429. Testy startują z sesją z `storageState` (cookie `wd_refresh`);
// `afterEach` zapisuje stan po rotacji cookie (reuse zużytego tokenu → 401 rodziny, C9).
const session = uiSession('s17-model-edit')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

// Zapas na powolne środowisko: zasiew instancji przez API i interakcje z siatką (domyślne 30 s
// bywa ciasne przy obciążonym hoście; dłuższy limit nie zwalnia już throttle'a logowań, bo
// logowanie jest jedno na plik).
test.setTimeout(90_000)

/**
 * Współdzielony token admina na cały bieg pliku: limiter logowań liczy KAŻDĄ próbę
 * (10/min per IP+e-mail, CONTRACT E5-2a §4), a testów jest kilkanaście — świeże logowanie
 * w każdym teście i afterEach tripiło 429 i zanieczyszczało przyczyny czerwieni.
 */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

/** Instancje do sprzątania po każdym teście (afterEach). */
const createdInstances: string[] = []

test.afterEach(async ({ request }) => {
  const token = await adminToken(request)
  await setProfileLanguage(request, token, 'pl')
  for (const id of createdInstances.splice(0)) {
    await deleteInstance(request, token, id)
  }
})

/** Zasiew instancji z modelami + rejestracja do sprzątania. */
async function seedInstance(
  request: Parameters<typeof createInstanceWithModels>[0],
  token: string,
  models: InstanceModelSpec[],
  name = `E2E S17 ${uniq()}`,
): Promise<{ instanceId: string; instanceName: string }> {
  const instanceId = await createInstanceWithModels(request, token, name, models)
  createdInstances.push(instanceId)
  return { instanceId, instanceName: name }
}

/** Ustawienia → Modele z wybraną instancją scenariusza (sesja z `storageState`, bez logowania). */
async function openModelsPage(page: Page, instanceId: string, instanceName: string): Promise<void> {
  await page.goto('/user-setting/model')
  await page.getByTestId(`instance-item-${instanceId}`).click()
  await expect(
    page.getByRole('heading', { name: `Modele instancji: ${instanceName}` }),
  ).toBeVisible()
}

/** Wiersz siatki modeli z daną nazwą (nagłówki kolumn nie zawierają nazwy modelu). */
function modelRow(page: Page, modelName: string) {
  return page.getByRole('row').filter({ hasText: modelName })
}

/**
 * Przewija okno na górę przed jawnym pomiarem strażnika i końcowym strażnikiem (fixtures.ts).
 * Diagnoza T9 (2026-10-11): `scrollIntoViewIfNeeded` i klik w wiersz przewijają okno (tu: do
 * 335 px), więc treść siatki ląduje POD stałym banerem aplikacji (`AppNavbar`, `position: fixed`,
 * 57 px, nieprzezroczysty) — strażnik porównuje surowe prostokąty i zgłasza wówczas fałszywy
 * `overlap` ze spanem „Wawelsky Dragon”. Wizualnie nic się nie nakłada (QA-UI: PASS), a przy
 * scroll 0 wady nie ma (treść startuje na y=64 = `mt: 8` w `AppLayout`). Strona przewija się
 * w oknie (brak kontenerów przewijalnych), więc wystarczy `window.scrollTo`; rAF domyka klatkę
 * po przewinięciu.
 */
async function scrollToTopForLayoutGuard(page: Page): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)))
}

/**
 * Zawija poziomy przewin siatki na start. Przywrócenie fokusu na ✎ (po zamknięciu dialogu)
 * zostawia siatkę przewiniętą do kolumny akcji; strażnik układu mierzy wtedy surowe prostokąty
 * nagłówków wystających poza kontener przewinięcia (niewidoczny dla użytkownika overlap z
 * listą instancji — fałszywy pozytyw). Wołane na końcu testów kończących zamknięciem dialogu.
 */
async function resetGridScroll(page: Page): Promise<void> {
  await page.locator('.MuiDataGrid-virtualScroller').evaluate((el) => el.scrollTo({ left: 0 }))
}

/** Przycisk ✎ w wierszu (kontrakt §1: aria-label „Edytuj model <nazwa>") — brak na bazie. */
function editButton(page: Page, modelName: string) {
  return modelRow(page, modelName).getByRole('button', { name: `Edytuj model ${modelName}` })
}

/** Pole okna kontekstu w dialogu (kontrakt §1: `data-testid="model-max-tokens"`). */
function maxTokensField(page: Page) {
  return page.getByLabel('Okno kontekstu (tokeny)')
}

/** Pole równoległych zapytań (kontrakt §1: `data-testid="model-concurrency"`). */
function concurrencyField(page: Page) {
  return page.getByLabel('Równoległe zapytania')
}

test('SC-E5-H8c-03 okno kontekstu: etykieta i pomoc w „Dodaj model”, brak „Max tokens”', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: `fake-chat-${uniq()}`, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Siatka: kolumna „Okno kontekstu” (SC-E5-H8c-03 krok 1) — przed otwarciem dialogu, bo MUI
  // przy otwartym modalu nadaje tłu `aria-hidden` i `getByRole` nie widzi elementów siatki.
  await expect(page.getByRole('columnheader', { name: 'Okno kontekstu' })).toBeVisible()

  // Krok 1: „Dodaj model” (czat) → pole „Okno kontekstu (tokeny)” z podpowiedzią z makiety.
  await page.getByRole('button', { name: 'Dodaj model' }).click()
  const dialog = page.getByRole('dialog', { name: 'Dodaj model' })
  await expect(dialog).toBeVisible()
  await expect(maxTokensField(page)).toBeVisible()
  await expect(dialog.getByText('Ile tokenów (pytanie + historia + fragmenty bazy)')).toBeVisible()

  // Kontrakt §1: „Nie wolno zostawić w UI napisu «Max tokens» (PL ani EN)”.
  await expect(page.getByText('Max tokens')).toHaveCount(0)

  await expectNoLayoutDefects(page, 'dialog „Dodaj model” (SC-E5-H8c-03 krok 1)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-E5-H8c-03 edycja: ✎ → 128000 → „Zapisz”, siatka i F5 pokazują nową wartość', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const chat = `fake-chat-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: chat, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Krok 2: ✎ przy istniejącym modelu czatu → wpisuje 128000 → „Zapisz”.
  await editButton(page, chat).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
  await expect(dialog).toBeVisible()
  await expect(maxTokensField(page)).toHaveValue('8192')
  await maxTokensField(page).fill('128000')
  await dialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(dialog).toBeHidden()

  // Siatka pokazuje 128000; po F5 nadal 128000 (zapis utrwalony na serwerze).
  await expect(modelRow(page, chat)).toContainText('128000')
  await page.reload()
  await page.getByTestId(`instance-item-${instanceId}`).click()
  await expect(modelRow(page, chat)).toContainText('128000')
  const models = await getInstanceModels(request, token, instanceId)
  expect(models.find((model) => model.name === chat)?.max_tokens).toBe(128000)

  await expectNoLayoutDefects(page, 'siatka modeli po edycji okna kontekstu')
})

test('SC-E5-H8c-03 walidacja: 100 → błąd „Co najmniej 1024”, „Zapisz” nieaktywny', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const chat = `fake-chat-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: chat, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Krok 4: wartość poniżej minimum → błąd przy polu (helperText), „Zapisz” nieaktywny.
  await editButton(page, chat).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
  await expect(dialog).toBeVisible()
  await maxTokensField(page).fill('100')
  await expect(dialog.getByText('Co najmniej 1024')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Zapisz' })).toBeDisabled()

  await expectNoLayoutDefects(page, 'dialog edycji z błędem walidacji (SC-E5-H8c-03 krok 4)')
})

test('SC-E5-H8c-03 Anuluj: ponowne otwarcie pokazuje wartości z serwera', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const chat = `fake-chat-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: chat, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Wpis nowej wartości i „Anuluj” — nic nie zapisuje (PATCH nie wychodzi z przeglądarki).
  await editButton(page, chat).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
  await expect(dialog).toBeVisible()
  await maxTokensField(page).fill('128000')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
  const unchanged = await getInstanceModels(request, token, instanceId)
  expect(unchanged.find((model) => model.name === chat)?.max_tokens).toBe(8192)

  // Ponowne otwarcie = stan czysty: wartość z serwera, nie to, co wpisano poprzednio.
  await editButton(page, chat).click()
  await expect(page.getByRole('dialog', { name: `Edytuj model: ${chat}` })).toBeVisible()
  await expect(maxTokensField(page)).toHaveValue('8192')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(page.getByRole('dialog', { name: `Edytuj model: ${chat}` })).toBeHidden()

  // Siatka nadal pokazuje wartość z serwera (asercja po zamknięciu dialogu: przy otwartym
  // modalu tło jest `aria-hidden` i `getByRole('row')` nie znajduje wierszy).
  await expect(modelRow(page, chat)).toContainText('8192')
  await resetGridScroll(page)
})

test('SC-E5-H8c-03 Esc zamyka dialog, fokus wraca na ✎', async ({ page, request }) => {
  const token = await adminToken(request)
  const chat = `fake-chat-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: chat, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  await editButton(page, chat).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()

  // Fokus wraca na przycisk ✎ wiersza (MUI przywraca fokus — `disableRestoreFocus` nieustawione).
  await expect(editButton(page, chat)).toBeFocused()
  const unchanged = await getInstanceModels(request, token, instanceId)
  expect(unchanged.find((model) => model.name === chat)?.max_tokens).toBe(8192)
  await resetGridScroll(page)
})

test.describe('SC-E5-H8c-03 warianty', () => {
  test('wariant EN: „Context window (tokens)” i pomoc po angielsku', async ({ page, request }) => {
    // Profil admina nadpisuje locale przeglądarki po zalogowaniu (authState.applyUser),
    // więc wariant EN ustawia język profilu przez API, nie sam `locale`.
    const token = await adminToken(request)
    await setProfileLanguage(request, token, 'en')
    const chat = `fake-chat-${uniq()}`
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: chat, modelType: 'chat', maxTokens: 8192 },
    ])
    await page.goto('/user-setting/model')
    await page.getByTestId(`instance-item-${instanceId}`).click()
    await expect(
      page.getByRole('heading', { name: `Instance models: ${instanceName}` }),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Add model' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add model' })
    await expect(dialog).toBeVisible()
    await expect(page.getByLabel('Context window (tokens)')).toBeVisible()
    await expect(dialog.getByText('How many tokens (question + history')).toBeVisible()
    await expect(page.getByText('Max tokens')).toHaveCount(0)
    await expectNoLayoutDefects(page, 'dialog „Add model” (EN)')
  })

  test('wariant 500: błąd API przy „Zapisz” → Alert w dialogu, pola zostają', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const chat = `fake-chat-${uniq()}`
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: chat, modelType: 'chat', maxTokens: 8192 },
    ])
    await openModelsPage(page, instanceId, instanceName)

    // PATCH modelu kończy się błędem API — dialog zostaje otwarty z Alertem i wartościami pól.
    // Koperta RAGFlow: HTTP 200 + `code ≠ 0` (odpowiedź HTTP 500 logowałaby się jako błąd
    // konsoli i wywaliła test strażnikiem z `fixtures.ts`); UI widzi ten sam `ApiError`.
    await page.route(`**/api/v1/providers/litellm/instances/*/models/${chat}`, async (route) => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 500, message: 'E2E: symulowana awaria zapisu' }),
        })
        return
      }
      await route.continue()
    })

    await editButton(page, chat).click()
    const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
    await expect(dialog).toBeVisible()
    await maxTokensField(page).fill('128000')
    await dialog.getByRole('button', { name: 'Zapisz' }).click()
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('alert')).toContainText('symulowana awaria zapisu')
    await expect(maxTokensField(page)).toHaveValue('128000')
    await expectNoLayoutDefects(page, 'dialog edycji z Alertem 500')
  })

  test.describe('wariant ciemny', () => {
    test.use({ colorScheme: 'dark' })

    test('wariant ciemny: dialog edycji czytelny w ciemnym motywie', async ({ page, request }) => {
      const token = await adminToken(request)
      const chat = `fake-chat-${uniq()}`
      const { instanceId, instanceName } = await seedInstance(request, token, [
        { name: chat, modelType: 'chat', maxTokens: 8192 },
      ])
      await openModelsPage(page, instanceId, instanceName)

      await editButton(page, chat).click()
      const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
      await expect(dialog).toBeVisible()
      await expect(maxTokensField(page)).toBeVisible()
      await expectNoLayoutDefects(page, 'dialog edycji modelu (ciemny motyw)')
      await dialog.getByRole('button', { name: 'Anuluj' }).click()
      await expect(dialog).toBeHidden()
      await resetGridScroll(page)
    })
  })
})

test('SC-E5-H8c-04 równoległe zapytania: pole wizji, zapis 24, „extra” zachowane', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const ocr = `fake-ocr-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: `fake-chat-${uniq()}`, modelType: 'chat', maxTokens: 8192 },
    // Krok 2 (przygotowanie): model wizji z obcymi kluczami `extra` — po zapisie z UI
    // `supports_reasoning` ma zostać, a `max_concurrency` ma zmienić się na 24.
    { name: ocr, modelType: 'vision', extra: { supports_reasoning: true, max_concurrency: 3 } },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Krok 1: ✎ przy modelu wizji → pole „Równoległe zapytania” (puste = „domyślnie 3”).
  await editButton(page, ocr).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${ocr}` })
  await expect(dialog).toBeVisible()
  await expect(concurrencyField(page)).toHaveValue('')
  await expect(concurrencyField(page)).toHaveAttribute('placeholder', 'domyślnie 3')
  await expect(dialog.getByText('Ile stron/partii worker wysyła')).toBeVisible()

  // Krok 2: wpisuje 24, „Zapisz”, otwiera dialog ponownie → 24.
  await concurrencyField(page).fill('24')
  await dialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(dialog).toBeHidden()
  await editButton(page, ocr).click()
  await expect(page.getByRole('dialog', { name: `Edytuj model: ${ocr}` })).toBeVisible()
  await expect(concurrencyField(page)).toHaveValue('24')

  // Inne klucze `extra` zachowane, `max_concurrency` podmienione (GET …/models przed/po).
  const models = await getInstanceModels(request, token, instanceId)
  expect(models.find((model) => model.name === ocr)?.extra).toEqual({
    supports_reasoning: true,
    max_concurrency: 24,
  })
  await expectNoLayoutDefects(page, 'dialog edycji modelu wizji (SC-E5-H8c-04)')
})

test('SC-E5-H8c-04 czyszczenie pola: klucz max_concurrency znika, supports_reasoning zostaje', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const ocr = `fake-ocr-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: ocr, modelType: 'vision', extra: { supports_reasoning: true, max_concurrency: 3 } },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Wpis 24 i zapis — stan wyjściowy kroku 3.
  await editButton(page, ocr).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${ocr}` })
  await expect(dialog).toBeVisible()
  await concurrencyField(page).fill('24')
  await dialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(dialog).toBeHidden()
  const after24 = await getInstanceModels(request, token, instanceId)
  expect(after24.find((model) => model.name === ocr)?.extra).toEqual({
    supports_reasoning: true,
    max_concurrency: 24,
  })

  // Krok 3: czyści pole, „Zapisz” → wraca „domyślnie 3”, klucz usunięty z `extra`,
  // pozostałe klucze (supports_reasoning) zachowane.
  await editButton(page, ocr).click()
  await expect(concurrencyField(page)).toHaveValue('24')
  await concurrencyField(page).fill('')
  await dialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(dialog).toBeHidden()
  const afterClear = await getInstanceModels(request, token, instanceId)
  expect(afterClear.find((model) => model.name === ocr)?.extra).toEqual({
    supports_reasoning: true,
  })

  await editButton(page, ocr).click()
  await expect(concurrencyField(page)).toHaveValue('')
  await expect(concurrencyField(page)).toHaveAttribute('placeholder', 'domyślnie 3')
  await expectNoLayoutDefects(page, 'dialog edycji po wyczyszczeniu pola (SC-E5-H8c-04 krok 3)')
})

test('SC-E5-H8c-04 walidacja: 0 i 40 → błąd „Wartość od 1 do 32”, „Zapisz” nieaktywny', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const ocr = `fake-ocr-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: ocr, modelType: 'vision', extra: { supports_reasoning: true, max_concurrency: 3 } },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Krok 4: wartości poza zakresem 1–32 → błąd przy polu, „Zapisz” nieaktywny.
  await editButton(page, ocr).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${ocr}` })
  await expect(dialog).toBeVisible()
  for (const value of ['0', '40']) {
    await concurrencyField(page).fill(value)
    await expect(dialog.getByText('Wartość od 1 do 32')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  }
  await expectNoLayoutDefects(page, 'dialog edycji z błędem zakresu (SC-E5-H8c-04 krok 4)')
})

test('SC-E5-H8c-04 model czatu: pola „Równoległe zapytania” nie ma', async ({ page, request }) => {
  const token = await adminToken(request)
  const chat = `fake-chat-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: chat, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Krok 5: ✎ przy modelu czatu → pola „Równoległe zapytania” NIE ma (pole tylko dla
  // vision/image2text/embedding, kontrakt §1).
  await editButton(page, chat).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
  await expect(dialog).toBeVisible()
  await expect(concurrencyField(page)).toHaveCount(0)
  await expect(maxTokensField(page)).toBeVisible()
  await expectNoLayoutDefects(page, 'dialog edycji modelu czatu (SC-E5-H8c-04 krok 5)')
})

test('SC-E5-H8c-04 wariant 500: Alert w dialogu, pola zostają', async ({ page, request }) => {
  const token = await adminToken(request)
  const ocr = `fake-ocr-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: ocr, modelType: 'vision', extra: { supports_reasoning: true, max_concurrency: 3 } },
  ])
  await openModelsPage(page, instanceId, instanceName)

  // Jak wyżej: koperta z `code 500` przy HTTP 200 (bez błędu konsoli), ten sam `ApiError`.
  await page.route(`**/api/v1/providers/litellm/instances/*/models/${ocr}`, async (route) => {
    if (route.request().method() === 'PATCH') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 500, message: 'E2E: symulowana awaria zapisu' }),
      })
      return
    }
    await route.continue()
  })

  await editButton(page, ocr).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${ocr}` })
  await expect(dialog).toBeVisible()
  await concurrencyField(page).fill('24')
  await dialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('alert')).toContainText('symulowana awaria zapisu')
  await expect(concurrencyField(page)).toHaveValue('24')
  await expectNoLayoutDefects(page, 'dialog edycji wizji z Alertem 500')
})

test.describe('poprawki po QA-UI (T7: defekty D1–D5)', () => {
  // POST …/models zawsze nadaje `max_tokens` 8192 (backend `_new_model`), więc model BEZ okna
  // kontekstu istnieje wyłącznie w zasiewie instancji `default` (`fake-vision`, NULL z K9 §3).
  test('SC-E5-H8c-04 qa D1: model wizji bez max_tokens — dialog bez błędu, zapis 8192 i 24', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const instances = await listInstances(request, token)
    const seed = instances.find((instance) => instance.instance_name === 'default')
    expect(seed, 'instancja „default” z zasiewu na liście').toBeDefined()
    await openModelsPage(page, seed!.id, seed!.instance_name)

    await editButton(page, 'fake-vision').click()
    const dialog = page.getByRole('dialog', { name: 'Edytuj model: fake-vision' })
    await expect(dialog).toBeVisible()
    // D1: pole startuje od domyślnego okna kontekstu backendu (8192), bez błędu przy otwarciu,
    // „Zapisz” aktywny przed jakąkolwiek zmianą.
    await expect(maxTokensField(page)).toHaveValue('8192')
    await expect(dialog.getByText('Co najmniej 1024')).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Zapisz' })).toBeEnabled()

    // Wpisanie 24 w „Równoległe zapytania” i zapis: PATCH ma max_tokens 8192 i max_concurrency 24.
    await concurrencyField(page).fill('24')
    await dialog.getByRole('button', { name: 'Zapisz' }).click()
    await expect(dialog).toBeHidden()
    const models = await getInstanceModels(request, token, seed!.id)
    const saved = models.find((model) => model.name === 'fake-vision')
    expect(saved?.max_tokens, 'zapisane okno kontekstu = domyślne 8192').toBe(8192)
    expect(saved?.extra, 'extra po zapisie').toEqual({ max_concurrency: 24 })
    await resetGridScroll(page)
    // Sprzątanie po teście: zasiew wraca bez klucza `max_concurrency` (max_tokens zostaje 8192 —
    // PATCH nie przyjmuje null, kolejny bieg zaczyna od resetu bazy).
    await patchInstanceModel(request, token, seed!.id, 'fake-vision', { extra: {} })
  })

  test('SC-E5-H8c-04 qa D2: podpowiedź „domyślnie 3” widoczna (CSS), nie tylko atrybutem', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const instances = await listInstances(request, token)
    const seed = instances.find((instance) => instance.instance_name === 'default')
    expect(seed, 'instancja „default” z zasiewu na liście').toBeDefined()
    await openModelsPage(page, seed!.id, seed!.instance_name)

    await editButton(page, 'fake-vision').click()
    const dialog = page.getByRole('dialog', { name: 'Edytuj model: fake-vision' })
    await expect(dialog).toBeVisible()
    await expect(concurrencyField(page)).toHaveValue('')
    await expect(concurrencyField(page)).toHaveAttribute('placeholder', 'domyślnie 3')
    // D2: MUI chowa placeholder (opacity 0), gdy etykieta nie jest zwinięta — użytkownik ma GO
    // WIDZIEĆ w pustym polu, więc pseudo-element ::placeholder ma realną nieprzezroczystość.
    const opacity = await concurrencyField(page).evaluate((el) => {
      return getComputedStyle(el, '::placeholder').opacity
    })
    expect(Number(opacity), 'placeholder „domyślnie 3” widoczny (opacity > 0)').toBeGreaterThan(0)
    await dialog.getByRole('button', { name: 'Anuluj' }).click()
    await expect(dialog).toBeHidden()
    await resetGridScroll(page)
  })

  test('SC-E5-H8c-03 qa D4: siatka na 1280 px bez poziomego przewijaka, ✎ w widocznym obszarze', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const chat = `fake-chat-${uniq()}`
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: chat, modelType: 'chat', maxTokens: 8192 },
    ])
    await openModelsPage(page, instanceId, instanceName)

    // D4: treść siatki (suma kolumn) mieści się w kontenerze — brak poziomego przewijaka
    // na 1280 px. Mierzymy `virtualScrollerContent`, nie `scrollWidth` scrollera: ten ostatni
    // dodaje stałe ~5 px za separator ostatniej kolumny (uchwyt zmiany szerokości w MUI X),
    // co nie jest przewijakiem widocznym dla użytkownika.
    const scroller = page.locator('.MuiDataGrid-virtualScroller')
    const { content, client } = await scroller.evaluate((el) => ({
      content: el.querySelector('.MuiDataGrid-virtualScrollerContent')?.getBoundingClientRect()
        .width,
      client: el.clientWidth,
    }))
    expect(
      content,
      `treść siatki ${Math.round(content!)}px mieści się w kontenerze ${client}px`,
    ).toBeLessThanOrEqual(client)

    // Kolumna akcji nie schodzi poza ekran: ✎ w obrębie widocznego obszaru 1280 px.
    const box = await editButton(page, chat).boundingBox()
    expect(box, 'przycisk ✎ zmierzony').not.toBeNull()
    expect(box!.x, '✎ lewa krawędź w oknie').toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width, '✎ prawa krawędź w oknie 1280 px').toBeLessThanOrEqual(1280)
  })

  test('SC-E5-H8c-03 qa D5: „Dodaj model” bez czerwieni pola nazwy przed wpisem', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: `fake-chat-${uniq()}`, modelType: 'chat', maxTokens: 8192 },
    ])
    await openModelsPage(page, instanceId, instanceName)

    await page.getByRole('button', { name: 'Dodaj model' }).click()
    const dialog = page.getByRole('dialog', { name: 'Dodaj model' })
    await expect(dialog).toBeVisible()
    const nameField = dialog.getByLabel(/Nazwa modelu/)
    await expect(nameField).toBeVisible()
    // D5: gwiazdka `required` zostaje, ale żaden element formularza nie ma stanu błędu,
    // dopóki użytkownik nie opuści pola (blur) albo nie spróbuje zapisać.
    await expect(nameField).not.toHaveAttribute('aria-invalid', 'true')
    await expect(dialog.locator('.Mui-error')).toHaveCount(0)
  })
})

test.describe('poprawki po QA-UI #2 (T8: D3/D5/D6/D7)', () => {
  // (D6) Kosz „Usuń model” renderuje się jako „…” (QA T8, D4-delete-btn-hires.png): komórka
  // kolumny akcji (90 px po T7, padding 0 10 px) jest węższa niż dwa IconButton (72 px), więc
  // DataGrid obcina treść z ellipsis. Wymóg: przycisk w całości wewnątrz komórki i brak
  // przepełnienia (scrollWidth ≤ clientWidth) przy 1280 px.
  test('SC-E5-H8c-03 qa2 D6: kosz „Usuń model” w całości w komórce akcji (1280 px)', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const chat = `fake-chat-${uniq()}`
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: chat, modelType: 'chat', maxTokens: 8192 },
    ])
    await openModelsPage(page, instanceId, instanceName)

    const del = modelRow(page, chat).getByRole('button', { name: `Usuń model ${chat}` })
    await expect(del).toBeVisible()
    const cell = del.locator('xpath=ancestor::div[@role="gridcell"]')
    const btnBox = await del.boundingBox()
    const cellBox = await cell.boundingBox()
    expect(btnBox, 'przycisk kosza zmierzony').not.toBeNull()
    expect(cellBox, 'komórka kolumny akcji zmierzona').not.toBeNull()
    expect(btnBox!.x, 'kosz zaczyna się w komórce').toBeGreaterThanOrEqual(cellBox!.x - 0.5)
    expect(
      btnBox!.x + btnBox!.width,
      'kosz kończy się w komórce (bez ucięcia „…”)',
    ).toBeLessThanOrEqual(cellBox!.x + cellBox!.width + 0.5)
    const width = await cell.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }))
    expect(
      width.scroll,
      `komórka akcji bez przepełnienia (scrollWidth ${width.scroll} ≤ clientWidth ${width.client})`,
    ).toBeLessThanOrEqual(width.client)
  })

  // (D7) Nagłówek panelu instancji („Dostawca: OpenAI-compatible / LiteLLM”) zawija się do 2
  // linii obok przycisku „+ Dodaj instancję” (układ poziomy, odstęp ~0) — przycisk ściśnięty
  // między tytułem a listą instancji na 1280 px. Wymóg: odstęp ≥ 8 px, przycisk w jednej linii.
  test('SC-E5-H8c-05 qa2 D7: odstęp ≥ 8 px między nagłówkiem instancji a „Dodaj instancję”', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: `fake-chat-${uniq()}`, modelType: 'chat', maxTokens: 8192 },
    ])
    await openModelsPage(page, instanceId, instanceName)

    const title = page.getByText('Dostawca: OpenAI-compatible / LiteLLM')
    const add = page.getByRole('button', { name: 'Dodaj instancję' })
    await expect(title).toBeVisible()
    await expect(add).toBeVisible()
    const titleBox = await title.boundingBox()
    const addBox = await add.boundingBox()
    expect(titleBox, 'nagłówek panelu instancji zmierzony').not.toBeNull()
    expect(addBox, 'przycisk „Dodaj instancję” zmierzony').not.toBeNull()
    expect(addBox!.height, '„Dodaj instancję” w jednej linii (bez łamania)').toBeLessThanOrEqual(40)
    // Odstęp w osi układania (pion dla kolumny, poziom dla wiersza): maksimum z obu separacji.
    const gapX = Math.max(
      addBox!.x - (titleBox!.x + titleBox!.width),
      titleBox!.x - (addBox!.x + addBox!.width),
    )
    const gapY = Math.max(
      addBox!.y - (titleBox!.y + titleBox!.height),
      titleBox!.y - (addBox!.y + addBox!.height),
    )
    expect(
      Math.max(gapX, gapY),
      `nagłówek nie dotyka przycisku (odstęp ${Math.max(gapX, gapY)} px ≥ 8 px)`,
    ).toBeGreaterThanOrEqual(8)
  })

  // (D5) „Dodaj model” otwiera się z autoFocus na polu nazwy, a fokus motywu jest czerwony
  // (primary) — dialog od otwarcia wygląda jak błąd walidacji (QA T8, D5-add-model-open…).
  // Wymóg: po otwarciu document.activeElement nie jest polem nazwy (fokus zostaje na dialogu).
  test('SC-E5-H8c-03 qa2 D5: po otwarciu „Dodaj model” fokus nie jest na polu nazwy', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: `fake-chat-${uniq()}`, modelType: 'chat', maxTokens: 8192 },
    ])
    await openModelsPage(page, instanceId, instanceName)

    await page.getByRole('button', { name: 'Dodaj model' }).click()
    const dialog = page.getByRole('dialog', { name: 'Dodaj model' })
    await expect(dialog).toBeVisible()
    const nameField = dialog.getByLabel(/Nazwa modelu/)
    await expect(nameField).toBeVisible()
    const nameFocused = await nameField.evaluate((el) => document.activeElement === el)
    expect(nameFocused, 'pole nazwy nie ma fokusa po otwarciu dialogu (D5)').toBe(false)
  })

  // (D3) Obramowanie motywu (border na korzeniu OutlinedInput, notchedOutline: none) rysuje się
  // PRZEZ pływającą etykietę — najwyraźniej w stanie fokusa, gdy dochodzi pierścień (QA T8,
  // D3-label-context-hires.png). Wymóg: prostokąt etykiety nie przecina prostokąta pola
  // (label.bottom ≤ input.top) przy fokusie każdego pola.
  test('SC-E5-H8c-04 qa2 D3: etykieta pól dialogu nie przecina obramowania przy fokusie', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ocr = `fake-ocr-${uniq()}`
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: ocr, modelType: 'vision', extra: { max_concurrency: 3 } },
    ])
    await openModelsPage(page, instanceId, instanceName)

    await editButton(page, ocr).click()
    const dialog = page.getByRole('dialog', { name: `Edytuj model: ${ocr}` })
    await expect(dialog).toBeVisible()
    for (const field of [maxTokensField(page), concurrencyField(page)]) {
      await field.focus()
      const measure = await field.evaluate((el) => {
        const input = (el.closest('.MuiInputBase-root') ?? el) as HTMLElement
        const label =
          input.ownerDocument.querySelector(`label[for="${el.id}"]`) ?? input.querySelector('label')
        const inputTop = input.getBoundingClientRect().top
        const labelBottom = label === null ? Number.NaN : label.getBoundingClientRect().bottom
        return { inputTop, labelBottom }
      })
      expect(
        measure.labelBottom,
        `etykieta nad obramowaniem pola (label.bottom ${measure.labelBottom} ≤ input.top ${measure.inputTop})`,
      ).toBeLessThanOrEqual(measure.inputTop + 0.5)
    }
  })
})

test.describe('SC-E5-H8c-05 ustawienia Modele na telefonie (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('przyciski nagłówków bez łamania linii, akcje wiersza widoczne', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const chat = `fake-chat-${uniq()}`
    // Krótka, deterministyczna nazwa (MINOR z T1): próg 80 px wysokości nagłówka „Modele
    // instancji: …” dotyczy układu, nie długości nazwy — sufiks o stałej szerokości nie daje flaka.
    const { instanceId, instanceName } = await seedInstance(
      request,
      token,
      [
        { name: chat, modelType: 'chat', maxTokens: 8192 },
        { name: `fake-ocr-${uniq()}`, modelType: 'vision' },
        { name: `fake-embed-${uniq()}`, modelType: 'embedding' },
      ],
      `S17 m${String(Date.now() % 100_000).padStart(5, '0')}`,
    )
    await page.goto('/user-setting/model')
    await page.getByTestId(`instance-item-${instanceId}`).click()
    await expect(
      page.getByRole('heading', { name: `Modele instancji: ${instanceName}` }),
    ).toBeVisible()

    // Krok 1: „Dodaj instancję”, „Dodaj model”, „Pobierz z /v1/models” — każdy na jednej linii
    // tekstu, w całości w oknie 390 px (kontrakt §4: kolumna pod nagłówkiem albo ikona).
    for (const name of ['Dodaj instancję', 'Dodaj model', 'Pobierz z /v1/models']) {
      const button = page.getByRole('button', { name })
      await button.scrollIntoViewIfNeeded()
      const box = await button.boundingBox()
      expect(box, `przycisk „${name}” widoczny`).not.toBeNull()
      expect(
        box!.height,
        `„${name}” — tekst przycisku bez łamania na 2–3 linie`,
      ).toBeLessThanOrEqual(40)
      expect(box!.x, `„${name}” — lewa krawędź w oknie`).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width, `„${name}” — prawa krawędź w oknie 390 px`).toBeLessThanOrEqual(
        390,
      )
    }
    // Nagłówek panelu modeli nie jest ściskany do wielu linii przez przyciski (kontrakt §4).
    const heading = page.getByRole('heading', { name: `Modele instancji: ${instanceName}` })
    await heading.scrollIntoViewIfNeeded()
    const headingBox = await heading.boundingBox()
    expect(headingBox, 'nagłówek panelu widoczny').not.toBeNull()
    expect(headingBox!.height, 'nagłówek panelu bez nadmiernego łamania').toBeLessThanOrEqual(80)

    await expectNoLayoutDefects(page, 'Ustawienia → Modele na 390 px')

    // ✎ i 🗑 w wierszu widoczne; przy 390 px (< md) jako pozycje menu ⋮ (kontrakt §1).
    const row = modelRow(page, chat)
    await row.getByTestId('row-actions-menu').scrollIntoViewIfNeeded()
    await row.getByTestId('row-actions-menu').click()
    await expect(page.getByRole('menuitem', { name: 'Edytuj model' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: 'Usuń model' })).toBeVisible()
    await page.keyboard.press('Escape')
    // Końcowy strażnik (fixtures.ts) mierzy zaraz po teście: tranzycja wyjściowa menu trzyma
    // jeszcze backdrop MUI (aria-hidden, ale przechwytujący elementFromPoint — 18× fałszywych
    // „covered”); czekamy na realny unmount modala, nie tylko na zejście z drzewa dostępności.
    await expect(page.locator('.MuiBackdrop-root')).toHaveCount(0)
    // Menu ⋮ przewinęło okno do wiersza (335 px); przed końcowym strażnikiem wracamy na górę
    // i mierzymy jawnie w stanie wyjściowym strony (patrz `scrollToTopForLayoutGuard`).
    await scrollToTopForLayoutGuard(page)
    await expectNoLayoutDefects(page, 'Ustawienia → Modele na 390 px (scroll 0)')
  })

  test('dialog „Edytuj model” mieści się w ekranie bez poziomego przewijania', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const chat = `fake-chat-${uniq()}`
    const { instanceId, instanceName } = await seedInstance(request, token, [
      { name: chat, modelType: 'chat', maxTokens: 8192 },
    ])
    await page.goto('/user-setting/model')
    await page.getByTestId(`instance-item-${instanceId}`).click()
    await expect(
      page.getByRole('heading', { name: `Modele instancji: ${instanceName}` }),
    ).toBeVisible()

    // Krok 2: otwiera „Edytuj model” (menu ⋮ przy 390 px) — dialog w całości w ekranie.
    const row = modelRow(page, chat)
    await row.getByTestId('row-actions-menu').click()
    await page.getByRole('menuitem', { name: 'Edytuj model' }).click()
    const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
    await expect(dialog).toBeVisible()

    const field = maxTokensField(page)
    await expect(field).toBeVisible()
    const fieldBox = await field.boundingBox()
    expect(fieldBox, 'pole okna kontekstu zmierzone').not.toBeNull()
    expect(fieldBox!.x).toBeGreaterThanOrEqual(0)
    expect(fieldBox!.x + fieldBox!.width).toBeLessThanOrEqual(390)
    const save = dialog.getByRole('button', { name: 'Zapisz' })
    await expect(save).toBeVisible()
    const saveBox = await save.boundingBox()
    expect(saveBox, 'przycisk „Zapisz” zmierzony').not.toBeNull()
    expect(saveBox!.x + saveBox!.width).toBeLessThanOrEqual(390)

    await expectNoLayoutDefects(page, 'dialog „Edytuj model” na 390 px')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    // Tranzycja wyjściowa dialogu trzyma backdrop MUI (jak w teście 1 — fałszywe „covered”).
    await expect(page.locator('.MuiBackdrop-root')).toHaveCount(0)
    // Otwarcie menu ⋮ przewinęło okno do wiersza (335 px); przed końcowym strażnikiem wracamy
    // na górę i mierzymy jawnie w stanie wyjściowym strony (patrz `scrollToTopForLayoutGuard`).
    await scrollToTopForLayoutGuard(page)
    await expectNoLayoutDefects(page, 'dialog „Edytuj model” na 390 px (scroll 0)')
  })
})
