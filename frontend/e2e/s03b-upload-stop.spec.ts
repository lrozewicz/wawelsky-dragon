// Scenariusz S6-03, akt drugi (08 §11.2, kontrakt WP E3-3b §T8): zatrzymanie parsowania dużego
// pliku. Plik powstaje w teście (~3 MB tekstu), więc parsowanie trwa na tyle długo, że stan
// „W kolejce”/„Parsowanie” da się złapać z UI i kliknąć ⊗.
// Selektory siatki są CSS-owe, nie oparte na rolach: popover komórki statusu (otwierany
// hoverem/fokusem) ustawia `aria-hidden` na resztę strony, więc `getByRole` przestaje widzieć
// wiersze, dopóki popover jest otwarty.
import { expect, resetDb, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset, loginViaUi } from './helpers'
import { expectNoSeriousA11y } from './helpers/axe'

const DATASET_NAME = 'E2E S6-03 baza ze stopem'
const LARGE_NAME = 'duzy.txt'

/** Rozmiar bufora: przy ~3 MB parsowanie nie kończy się między dwoma odświeżeniami siatki. */
const LARGE_TARGET_BYTES = 3 * 1024 * 1024

const LARGE_LINE =
  'Zamek Królewski na Wawelu wznosi się na wzgórzu nad Wisłą w Krakowie i przez stulecia był siedzibą królów Polski.\n'

/** Powtarzane zdania o Wawelu do zadanej liczby bajtów; numer wiersza czyni linie różnymi. */
function largeText(targetBytes: number): string {
  const parts: string[] = []
  let bytes = 0
  let index = 1
  while (bytes < targetBytes) {
    const line = `${String(index)}. ${LARGE_LINE}`
    parts.push(line)
    bytes += Buffer.byteLength(line, 'utf8')
    index += 1
  }
  return parts.join('')
}

/** Jedyny dokument w bazie — komórka statusu jest jednoznaczna. */
const STATUS_CELL = '[data-testid^="status-cell-"]'
const STOP_BUTTON = '[data-testid^="status-stop-"]'

test('S6-03: stop parsowania dużego pliku przechodzi w „Anulowano”', async ({ page, request }) => {
  test.setTimeout(240_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  await expect(page.locator(STATUS_CELL)).toHaveCount(0)

  // 1. Przesłanie pliku z pamięci z włączonym „Parsuj po przesłaniu”.
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await page.getByTestId('upload-input').setInputFiles({
    name: LARGE_NAME,
    mimeType: 'text/plain',
    buffer: Buffer.from(largeText(LARGE_TARGET_BYTES), 'utf8'),
  })
  await expect(page.getByTestId('upload-parse-toggle')).toBeChecked()
  await page.getByTestId('upload-start').click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toHaveCount(1, {
    timeout: POLL_TIMEOUT_MS,
  })
  await expect(page.getByTestId('upload-start')).toBeDisabled({ timeout: POLL_TIMEOUT_MS }) // po sukcesie T15b
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(dialog).toBeHidden()

  // 2. ⊗ jest w DOM tylko w stanie „W kolejce” albo „Parsowanie” — czekamy na niego, nie na czas
  //    (`waitForTimeout` zakazany), i klikamy, dopóki parsowanie biegnie.
  const stop = page.locator(STOP_BUTTON)
  await stop.waitFor({ state: 'visible', timeout: POLL_TIMEOUT_MS })
  await stop.click()

  // 3. Po `POST /documents/stop` backend ustawia `run = CANCEL` → chip „Anulowano”.
  await expect(page.locator(STATUS_CELL), 'status po zatrzymaniu').toHaveText('Anulowano', {
    timeout: POLL_TIMEOUT_MS,
  })

  // Główny ekran scenariusza: siatka plików datasetu po zatrzymaniu (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-03b pliki datasetu')
})
