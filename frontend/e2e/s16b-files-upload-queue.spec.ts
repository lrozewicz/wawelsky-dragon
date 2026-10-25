// Scenariusz S16b (kontrakt WP E5-H6a §C1): dialog uploadu menedżera Plików czyści kolejkę po
// zamknięciu, więc dwa kolejne uploady po jednym pliku (drugi przez drag&drop z prawdziwym
// `DataTransfer`) zostawiają w folderze dokładnie 2 pliki. Sprawdzane w dwóch szerokościach:
// desktop i telefon 390×844. Backend nie jest mockowany — te same trasy woła UI, a resztki
// sprząta `test.afterEach` przez API (`helpers/files.ts`).
import { expect, resetDb, test } from './fixtures'
import { apiLogin, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteAllFiles } from './helpers/files'

const FIRST_NAME = 'e2e-s16b-a.txt'
const SECOND_NAME = 'e2e-s16b-b.txt'
const BODY = 'Treść pliku e2e S16b'

/** Token sesji do sprzątania; brak, gdy test padł przed logowaniem. */
let token: string | undefined

test.afterEach(async ({ request }) => {
  if (token === undefined) return
  await deleteAllFiles(request, token)
  token = undefined
})

const VIEWPORTS = [
  { label: 'desktop', viewport: { width: 1280, height: 720 } },
  { label: 'mobile 390x844', viewport: { width: 390, height: 844 } },
]

for (const { label, viewport } of VIEWPORTS) {
  test.describe(`S16b ${label}`, () => {
    test.use({ viewport })

    test('dwa uploady z zamknięciem dialogu między nimi dają 2 pliki w folderze', async ({
      page,
      request,
    }) => {
      // Reset, logowanie, dwa dialogi i odświeżenia listy — zapas ponad domyślne 30 s.
      test.setTimeout(120_000)

      await resetDb(request)
      token = await apiLogin(request)
      await loginViaUi(page)

      await page.goto('/files')
      await expect(page.getByRole('heading', { name: 'Pliki' })).toBeVisible()

      // 1. Upload pliku przez ukryty input; po „Przesłano” zamykamy dialog.
      await page.getByTestId('files-add').click()
      await page.getByTestId('files-add-upload').click()
      let dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await page.getByTestId('files-upload-input').setInputFiles({
        name: FIRST_NAME,
        mimeType: 'text/plain',
        buffer: Buffer.from(BODY),
      })
      await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({ timeout: 60_000 })
      await page.getByTestId('files-upload-close').click()
      await expect(dialog).toBeHidden()

      // 2. Drugi upload przez drag&drop. Przed nim nowy dialog musi mieć PUSTĄ kolejkę — bez
      //    czyszczenia stanu po zamknięciu (kontrakt C1) zostałaby w nim nazwa pierwszego pliku.
      await page.getByTestId('files-add').click()
      await page.getByTestId('files-add-upload').click()
      dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await expect(dialog.getByText(FIRST_NAME)).toBeHidden()
      await dropFile(
        page,
        dialog.getByTestId('files-upload-dropzone'),
        Buffer.from(BODY),
        SECOND_NAME,
        'text/plain',
      )
      await expect(dialog.getByTestId('files-upload-item-0')).toContainText(SECOND_NAME)
      await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({ timeout: 60_000 })
      await page.getByTestId('files-upload-close').click()
      await expect(dialog).toBeHidden()

      // 3. W folderze są dokładnie dwa pliki (foldery odfiltrowane po rozszerzeniu).
      await expect(
        page.getByTestId('files-grid').getByRole('row').filter({ hasText: '.txt' }),
      ).toHaveCount(2)
    })
  })
}
