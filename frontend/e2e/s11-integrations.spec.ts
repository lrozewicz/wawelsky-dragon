// Scenariusz S6-11 (08-frontend §11.2; brief WP E4-3d/T5, DEC-183 — pełny cykl na stubie Graph
// `fake-graph`, DEC-152 — wariant „zły sekret"). Stos testowy ma lokalny stub Microsoft Graph,
// więc scenariusz obejmuje cały cykl integracji SharePoint: test połączenia, wybór bibliotek
// (pole `excluded_library_names` = Archiwum), zapis, synchronizację do 3 dokumentów w datasecie
// docelowym, edycję i usunięcie. Wariant A (zły sekret) zachowuje dawny scenariusz odrzucenia:
// krok `graph_auth: failed`, alert przy zapisie, pusta lista po stronie API, sekret wyłącznie
// w polu hasła. Błędów konsoli pilnuje fixture `page` (`./fixtures`); `takeOverConsoleGuard`
// z `./helpers/integrations` zdejmuje jego nasłuch i zakłada równoważny z jednym wąskim wyjątkiem:
// oczekiwanym 400 z zapisu przy złym sekrecie (DEC-152). Wariant B nie potrzebuje już wyjątku na
// 404 — po usunięciu integracji UI nie odpytuje tras usuniętego zasobu (T6).
import type { Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import {
  deleteAllIntegrations,
  listDatasetDocuments,
  listIntegrations,
  pollRunFinished,
  takeOverConsoleGuard,
} from './helpers/integrations'

// Stałe stubu Graph (kontrakt E4-3d C5): poprawny sekret i witryna, której szuka stub.
const TENANT = 'tenant-e2e'
const CLIENT = 'client-e2e'
const SECRET = 'fake-graph-secret'
const SITE_URL = 'https://contoso.sharepoint.test/sites/e2e'
// Biblioteka archiwalna wykluczona po nazwie — w datasecie mają zostać 3 pliki, nie 4 (C3).
const EXCLUDED_LIBRARY = 'Archiwum'
const WRONG_SECRET = 'secret-e2e-nieprawdziwy'
const DATASET_DOCUMENTS = ['notatka.txt', 'sample.docx', 'sample.pdf']

/** Otwiera Admin → Integracje i asertuje adres oraz pusty stan listy. */
async function openIntegrations(page: Page): Promise<void> {
  await loginViaUi(page)
  await page.getByRole('navigation').getByRole('link', { name: 'Administracja' }).click()
  await page.getByTestId('admin-tab-integrations').click()
  await expect(page).toHaveURL(/\/admin\/integrations$/)
  await expect(page.getByTestId('admin-integrations')).toContainText('Brak integracji')
}

test('S6-11: zły sekret — test połączenia i odrzucenie zapisu (stub Graph)', async ({
  page,
  request,
}) => {
  // Reset stosu (K9) przed wariantem: czyści dane oraz limiter logowania (`LoginGuard.reset()`
  // w `services/reset.py`). Bez tego dwa logowania tego pliku (API + UI w każdym z 2 testów)
  // dobijają do limitu 10 prób/min per IP+e-mail i logowanie UI kończy się alertem
  // „Too many login attempts, please try again later".
  await resetDb(request)
  const token = await apiLogin(request)
  const datasetName = `S11 zły sekret ${Date.now()}`
  await deleteAllIntegrations(request, token)
  await createDataset(request, token, datasetName)
  // 400 z zapisu jest w tym wariancie oczekiwany (DEC-152) — przejmujemy strażnik konsoli
  // z jednym wąskim wyjątkiem, resztę błędów nadal wywala asercja na końcu.
  const consoleErrors = takeOverConsoleGuard(page)

  try {
    // 1. Menu → „Administracja" → zakładka „Integracje"; lista startuje pusta.
    await openIntegrations(page)

    // 2. Formularz integracji; test połączenia ze złym sekretem zwraca krok `graph_auth: failed`
    // (asercja patrzy na stan kroku, nie na treść komunikatu z Microsoft).
    await page.getByTestId('integration-add').click()
    const dialog = page.getByTestId('integration-form')
    await dialog.getByTestId('integration-field-name').fill('S11 zły sekret')
    await dialog.getByTestId('integration-field-dataset_id').click()
    await page.getByRole('option', { name: datasetName }).click()
    await dialog.getByTestId('integration-field-tenant_id').fill(TENANT)
    await dialog.getByTestId('integration-field-client_id').fill(CLIENT)
    await dialog.getByTestId('integration-field-client_secret').fill(WRONG_SECRET)
    await dialog.getByTestId('integration-field-site_url').fill(SITE_URL)

    await dialog.getByTestId('integration-test').click()
    const testResult = dialog.getByTestId('integration-test-result')
    await expect(testResult).toBeVisible({ timeout: 30_000 })
    await expect(testResult.getByTestId('integration-test-graph_auth')).toContainText('Błąd')

    // 3. Zapis przy złym sekrecie jest odrzucany: alert błędu w dialogu, dialog zostaje otwarty,
    // lista po stronie API pusta, a sekret nie wycieka poza pole, w które go wpisano.
    await dialog.getByTestId('integration-save').click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog).toBeVisible()
    expect(
      await listIntegrations(request, token),
      'lista integracji po odrzuconym zapisie',
    ).toEqual([])
    // React trzyma `value` kontrolowanego `<input>` także w atrybucie (react-dom `updateInput`
    // → `setDefaultValue`), więc otwarty formularz ZAWIERA wpisany sekret — dokładnie raz, jako
    // wartość pola hasła. Drugie wystąpienie znaczyłoby wyciek (alert, inny węzeł, cache zapytań).
    const openDialogHtml = await page.content()
    expect(openDialogHtml.split(WRONG_SECRET).length - 1, 'sekret tylko w polu hasła').toBe(1)
    await expect(dialog.getByTestId('integration-field-client_secret')).toHaveAttribute(
      'type',
      'password',
    )

    // 4. Anulowanie wraca do pustego stanu; ponowne otwarcie nie odtwarza sekretu.
    await dialog.getByRole('button', { name: 'Anuluj' }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByTestId('admin-integrations')).toContainText('Brak integracji')
    // Zamknięcie odmontowuje formularz — po sekrecie nie zostaje w DOM ani ślad.
    expect(await page.content(), 'sekret zostaje w DOM po zamknięciu dialogu').not.toContain(
      WRONG_SECRET,
    )

    await page.getByTestId('integration-add').click()
    const reopened = page.getByTestId('integration-form')
    await expect(reopened.getByTestId('integration-field-name')).toHaveValue('')
    await expect(reopened.getByTestId('integration-field-client_secret')).toHaveValue('')
    await reopened.getByRole('button', { name: 'Anuluj' }).click()
    await expect(reopened).toBeHidden()

    // 5. Przeładowanie trasy integracji: zakładka i pusty stan bez błędów konsoli.
    await page.reload()
    await expect(page).toHaveURL(/\/admin\/integrations$/)
    await expect(page.getByTestId('admin-integrations')).toContainText('Brak integracji')
    expect(consoleErrors, 'nieoczekiwane błędy konsoli').toEqual([])
  } finally {
    await deleteAllIntegrations(request, token)
  }
})

test('S6-11: pełny cykl na stubie Graph — zapis, sync, dokumenty, edycja, usunięcie', async ({
  page,
  request,
}) => {
  // Synchronizacja chodzi w tle (worker) — kontrakt przebiegu dopuszcza do 120 s (brief T5 p. 5),
  // więc scenariusz dostaje zapas ponad domyślne 30 s Playwrighta.
  test.setTimeout(180_000)

  // Strażnik konsoli z jednym wąskim wyjątkiem na oczekiwany 400 z wariantu A (DEC-152). Wariant B
  // nie potrzebuje wyjątków — usunięcie integracji nie dociąga już tras usuniętego zasobu (T6).
  const consoleErrors = takeOverConsoleGuard(page)

  // Reset stosu (K9): czyste dane i limiter logowania przed własnymi próbami (jak w wariancie A).
  await resetDb(request)
  const token = await apiLogin(request)
  const datasetName = `S11 cykl ${Date.now()}`
  const integrationName = 'S11 integracja stub'
  const editedName = 'S11 integracja stub (po edycji)'
  await deleteAllIntegrations(request, token)
  const datasetId = await createDataset(request, token, datasetName)

  try {
    await openIntegrations(page)

    // 1. Formularz z poprawnymi danymi stubu; „wybór dysków" = wykluczenie biblioteki Archiwum.
    await page.getByTestId('integration-add').click()
    const dialog = page.getByTestId('integration-form')
    await dialog.getByTestId('integration-field-name').fill(integrationName)
    await dialog.getByTestId('integration-field-dataset_id').click()
    await page.getByRole('option', { name: datasetName }).click()
    await dialog.getByTestId('integration-field-tenant_id').fill(TENANT)
    await dialog.getByTestId('integration-field-client_id').fill(CLIENT)
    await dialog.getByTestId('integration-field-client_secret').fill(SECRET)
    await dialog.getByTestId('integration-field-site_url').fill(SITE_URL)
    const excluded = dialog.getByTestId('integration-field-excluded_library_names')
    await excluded.fill(EXCLUDED_LIBRARY)
    await excluded.press('Enter')

    // 2. Test połączenia: wszystkie trzy kroki OK (token, witryna, dataset).
    await dialog.getByTestId('integration-test').click()
    const testResult = dialog.getByTestId('integration-test-result')
    await expect(testResult).toBeVisible({ timeout: 30_000 })
    await expect(testResult.getByTestId('integration-test-graph_auth')).toContainText('OK')
    await expect(testResult.getByTestId('integration-test-site_resolution')).toContainText('OK')
    await expect(testResult.getByTestId('integration-test-dataset_exists')).toContainText('OK')

    // 3. Zapis przechodzi (backend rozwiązał witrynę przez stub) — wiersz w gridzie.
    await dialog.getByTestId('integration-save').click()
    await expect(dialog).toBeHidden()
    const grid = page.getByTestId('integrations-grid')
    await expect(grid).toContainText(integrationName)

    // Jasny motyw, główny ekran scenariusza: lista integracji z zapisanym wierszem.
    await expectNoSeriousA11y(page, 'S6-11 integracje — lista z wierszem')

    const rows = await listIntegrations(request, token)
    expect(rows, 'lista integracji po zapisie').toHaveLength(1)
    const id = rows[0]!.id

    // 4. Szczegóły → synchronizacja z potwierdzeniem; przebieg dochodzi do `success`.
    await page.getByTestId(`integration-open-${id}`).click()
    const details = page.getByTestId('integration-details')
    await expect(details).toBeVisible()
    await expect(details).toContainText(integrationName)

    await page.getByTestId('integration-sync').click()
    const syncConfirm = page.getByRole('dialog').filter({ hasText: 'Uruchomić synchronizację?' })
    await syncConfirm.getByRole('button', { name: 'Synchronizuj' }).click()

    const status = await pollRunFinished(request, token, id)
    expect(status.latest_run?.status, 'status przebiegu synchronizacji').toBe('success')
    // Cache zapytań ma `staleTime` 30 s (`app/queryClient.ts`), a pierwsze odpytanie statusu po
    // zleceniu trafia w wyścig z workerem (wiersz przebiegu jeszcze nie istnieje) — dlatego
    // przeładowujemy trasę: nowy cache, świeży stan szczegółów i chip „Sukces".
    await page.reload()
    await expect(page).toHaveURL(/\/admin\/integrations$/)
    await page.getByTestId(`integration-open-${id}`).click()
    const syncedDetails = page.getByTestId('integration-details')
    await expect(syncedDetails).toBeVisible()
    await expect(syncedDetails.getByText('Sukces').first()).toBeVisible({ timeout: 30_000 })

    // 5. Dataset docelowy ma dokładnie 3 dokumenty (biblioteka Archiwum wykluczona — C3).
    const documents = await listDatasetDocuments(request, token, datasetId)
    expect([...documents].sort(), 'dokumenty w datasecie po synchronizacji').toEqual(
      DATASET_DOCUMENTS,
    )

    // 6. Edycja: zmiana nazwy, zapis, nowa nazwa w gridzie.
    await syncedDetails.getByRole('button', { name: 'Zamknij' }).click()
    await expect(syncedDetails).toBeHidden()
    await page.getByTestId(`integration-edit-${id}`).click()
    const editDialog = page.getByTestId('integration-form')
    const nameField = editDialog.getByTestId('integration-field-name')
    await expect(nameField).toHaveValue(integrationName)
    await nameField.fill(editedName)
    await editDialog.getByTestId('integration-save').click()
    await expect(editDialog).toBeHidden()
    await expect(grid).toContainText(editedName)

    // 7. Usunięcie z potwierdzeniem — lista po stronie API pusta; dokumenty w datasecie zostają
    // (domyślnie `delete_docs_on_integration_delete=false`, więc nie asertujemy ich zniknięcia).
    await page.getByTestId(`integration-open-${id}`).click()
    const detailsAgain = page.getByTestId('integration-details')
    await expect(detailsAgain).toBeVisible()
    await page.getByTestId('integration-delete').click()
    const deleteConfirm = page.getByRole('dialog').filter({ hasText: 'Usunąć integrację?' })
    await deleteConfirm.getByRole('button', { name: 'Usuń integrację' }).click()
    await expect(detailsAgain).toBeHidden()
    expect(await listIntegrations(request, token), 'lista po usunięciu integracji').toEqual([])
    expect(
      await listDatasetDocuments(request, token, datasetId),
      'dokumenty zostają w datasecie po usunięciu integracji',
    ).toHaveLength(DATASET_DOCUMENTS.length)
    expect(consoleErrors, 'nieoczekiwane błędy konsoli').toEqual([])
  } finally {
    await deleteAllIntegrations(request, token)
  }
})
