// Scenariusz S6-06 (08 §11.2, kontrakt WP E3-3a §T6): konfiguracja datasetu — pola „Zaawansowane”
// poza DOM do rozwinięcia akordeonu, model embeddingu zablokowany przy istniejących chunkach,
// zmiana metody na Q&A: zapis (PUT) utrwala zmianę, a dialog „Zastosować zmiany do istniejących
// plików?” (E5-H8c §2) pyta o istniejące dokumenty — „Tylko nowe pliki” zostawia pliki w spokoju.
// Drugi dataset bez dokumentów pokazuje, że embedding jest odblokowany, gdy chunków nie ma.
// Datasety powstają przez API (kontrakt §T6: helper `seedCorpus`); UI sprawdza zachowanie formularza.
import type { APIRequestContext, Page } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { apiLogin, createDataset, seedCorpus } from './helpers'
import { expectNoSeriousA11y } from './helpers/axe'

const SEEDED_NAME = 'E2E S6-06 baza z dokumentem'
const EMPTY_NAME = 'E2E S6-06 baza bez dokumentów'
const DOCUMENT_NAME = 'e2e-s06-smok.txt'
const DOCUMENT_BODY = [
  'Wawelski smok mieszkał w jamie pod Wawelem.',
  '',
  'Legenda o smoku wawelskim: smok pilnował zbocza Wawelu, a zguba miasta miała',
  'na imię Zygfryd. Smok wawelski został pokonany przez szewca Skubę.',
  '',
].join('\n')

type Shared = { seededId: string; emptyId: string }

let shared: Promise<Shared> | undefined

/** Jeden wsiew na plik: baza z dokumentem sparsowanym do DONE i baza bez dokumentów. */
function seeded(request: APIRequestContext): Promise<Shared> {
  shared ??= (async () => {
    const token = await apiLogin(request)
    const corpus = await seedCorpus(request, token, {
      datasetName: SEEDED_NAME,
      documentName: DOCUMENT_NAME,
      documentBody: DOCUMENT_BODY,
    })
    const emptyId = await createDataset(request, token, EMPTY_NAME)
    return { seededId: corpus.datasetId, emptyId }
  })()
  return shared
}

/** Logowanie kontem z seedu K9 przez UI (jak S6-01, S7a i S6-02). */
async function loginViaUi(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()
}

test('S6-06: akordeon Zaawansowane, zablokowany embedding i zmiana metody na Q&A', async ({
  page,
  request,
}) => {
  // Wsiew parsuje dokument (odpytywanie workera) — jak w S6-07/S6-08.
  test.setTimeout(180_000)
  const { seededId } = await seeded(request)

  await loginViaUi(page)
  await page.goto(`/dataset/configuration/${seededId}`)
  await expect(page.getByRole('heading', { name: SEEDED_NAME })).toBeVisible()

  // 1. Pola „Zaawansowane” są poza DOM, dopóki akordeon jest zwinięty. Selektor po roli, nie po
  //    etykiecie: `getByLabel('Język')` trafia też w przycisk języka w nagłówku aplikacji.
  await expect(page.getByRole('combobox', { name: 'Język' })).toBeHidden()
  await expect(page.getByText(/Nakładanie \(%\)/)).toBeHidden()

  // 2. Model embeddingu jest zablokowany, bo baza ma już chunki (metoda `naive`).
  await expect(page.getByRole('combobox', { name: 'Model embeddingu' })).toBeDisabled()

  // 3. Rozwinięcie „Zaawansowane” odsłania pola sekcji ADV.
  await page.getByRole('button', { name: 'Zaawansowane' }).click()
  await expect(page.getByRole('combobox', { name: 'Język' })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Zespół' })).toBeVisible()
  await expect(page.getByText(/Nakładanie \(%\)/)).toBeVisible()

  // Główny ekran scenariusza: formularz konfiguracji datasetu (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-06 konfiguracja datasetu')

  // 4. Zmiana metody na Q&A + Zapisz → PUT utrwala zmianę, a POTEM (kontrakt E5-H8c §2) pojawia
  //    się dialog „Zastosować zmiany do istniejących plików?” z listą zmienionych pól.
  await page.getByRole('combobox', { name: 'Metoda chunkowania' }).click()
  await page.getByRole('option', { name: 'Q&A' }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = page.getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Zmieniono: Metoda chunkowania.')
  await dialog.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Zapisano')).toBeVisible()

  // 5. F5 — metoda wraca z backendu jako Q&A (PUT utrwalił zmianę).
  await page.reload()
  await expect(page.getByRole('heading', { name: SEEDED_NAME })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Metoda chunkowania' })).toContainText('Q&A')
})

test('S6-06: baza bez dokumentów ma odblokowany model embeddingu', async ({ page, request }) => {
  test.setTimeout(180_000)
  const { emptyId } = await seeded(request)

  await loginViaUi(page)
  await page.goto(`/dataset/configuration/${emptyId}`)
  await expect(page.getByRole('heading', { name: EMPTY_NAME })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Model embeddingu' })).toBeEnabled()
})
