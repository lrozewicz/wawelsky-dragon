// SC-V12-z-V1…V4 (brief T2, QA-UI: MINOR-y traktowane jak MAJOR): cztery drobne poprawki
// wizualne z przebiegów V12-z-1 i V12-z-2b.
//   V1 — kropkowana ramka strefy importu kontrastowa z tłem dialogu w ciemnym motywie
//        (V12-z-2b MINOR-1, dark-5-import-1280.png); w jasnym bez zmian (divider).
//   V2 — brak testu: snippet trafienia skraca SERWER (backend/app/domain/retrieval/highlight.py,
//        okno ±120 znaków bez wielokropka) — front renderuje `highlight` w całości, nie ma
//        obcinania po stronie klienta; zmiana należy do backendu (poza zakresem T2).
//   V3 — chip „Metadane: n warunków” nie zawija „Prześlij plik” do drugiej linii paska
//        narzędzi (V12-z-1 MINOR, C15-filtr-tabela.png).
//   V4 — 390 px, Klucze API: szkielet wierszy zamiast gołego szarego prostokąta w stanie
//        ładowania (V12-z-2b MINOR-2, SC-V12-01-1-klucze-390.png).
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

// Logowanie RAZ na plik (limiter logowań współdzielony z biegiem — patrz helpers/session.ts).
const session = uiSession('s30-v12z-visual')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

/** Otwiera dialog „Importuj bazę wiedzy” na liście baz (wzór s17b). */
async function openImportDialog(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Importuj' }).click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(dialog).toBeVisible()
  return dialog
}

test.describe('SC-V12-z-V1 ramka strefy importu w ciemnym motywie', () => {
  test.describe('ciemny 1280', () => {
    test.use({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark' })

    test('kropkowana ramka ma kontrast ≥ 3:1 z tłem dialogu (ciemny, 1280)', async ({ page }) => {
      await page.goto('/datasets')
      await page.addStyleTag({ content: '*{transition:none!important}' })
      const dialog = await openImportDialog(page)
      const dropzone = dialog.getByTestId('kb-import-dropzone')
      await expect(dropzone).toBeVisible()

      // Kontrast WCAG koloru ramki z tłem dialogu (non-text ≥ 3:1). W V12-z-2b divider
      // (alpha gray-700 0,6) ginął na ciemnym papierze — ramki nie było widać wcale.
      const measured = await dropzone.evaluate((el) => {
        const parse = (color: string): [number, number, number, number] => {
          const match = color.match(/rgba?\(([^)]+)\)/)
          if (match === null || match[1] === undefined) {
            throw new Error(`Nieznany format koloru: ${color}`)
          }
          const parts = match[1].split(',').map((part) => Number(part.trim()))
          return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, parts[3] ?? 1]
        }
        const luminance = ([r, g, b]: [number, number, number]): number => {
          const linear = (c: number): number =>
            c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
          return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
        }
        const surface = el.closest('[role="dialog"]') ?? document.body
        const border = parse(getComputedStyle(el).borderTopColor)
        const background = parse(getComputedStyle(surface).backgroundColor)
        const l1 = luminance([border[0] / 255, border[1] / 255, border[2] / 255])
        const l2 = luminance([background[0] / 255, background[1] / 255, background[2] / 255])
        const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1]
        return {
          ratio: (hi + 0.05) / (lo + 0.05),
          border: getComputedStyle(el).borderTopColor,
          background: getComputedStyle(surface).backgroundColor,
        }
      })
      expect(
        measured.ratio,
        `kontrast ramki (${measured.border}) z tłem dialogu (${measured.background})`,
      ).toBeGreaterThanOrEqual(3)
      // Ramka dashed (kropkowana wg QA) — styl bez zmian, liczy się widoczność.
      await expect(dropzone).toHaveCSS('border-style', 'dashed')
      await expectNoLayoutDefects(page, 'dialog importu w ciemnym motywie (SC-V12-z-V1)')
    })
  })

  test.describe('jasny 1280', () => {
    test.use({ viewport: { width: 1280, height: 800 }, colorScheme: 'light' })

    test('ramka w jasnym bez zmian — kolor divider (regresja nadpisania)', async ({ page }) => {
      await page.goto('/datasets')
      const dialog = await openImportDialog(page)
      const dropzone = dialog.getByTestId('kb-import-dropzone')
      await expect(dropzone).toBeVisible()

      // Próbka z `divider` motywu: kolor ramki strefy ma być dokładnie tym tokenem.
      const colors = await dropzone.evaluate((el) => {
        const probe = document.createElement('div')
        el.appendChild(probe)
        probe.style.borderColor = 'var(--template-palette-divider)'
        const border = getComputedStyle(el).borderTopColor
        const divider = getComputedStyle(probe).borderTopColor
        probe.remove()
        return { border, divider }
      })
      expect(colors.border, 'ramka strefy w jasnym = divider (bez zmian)').toBe(colors.divider)
    })
  })
})

test.describe('SC-V12-z-V3 chip filtra w pasku plików', () => {
  // Dataset z polem `rok` i jednym dokumentem z metadanymi `rok: 2023` (upload + PATCH przez
  // API — parsowanie nic nie wnosi do układu paska). Dokument MUSI pasować do filtra: przy
  // zerze trafień „Prześlij plik” jest chowany z kontraktu (WP E6-1b §4, `showAdd=false`).
  let shared: Promise<{ token: string; datasetId: string }> | undefined

  function seeded(request: APIRequestContext): Promise<{ token: string; datasetId: string }> {
    shared ??= (async () => {
      const token = await apiLogin(request)
      const datasetId = await createDataset(request, token, 'E2E S30 baza z konfiguracją')
      const envelope = async <T>(pending: Promise<APIResponse>, label: string): Promise<T> => {
        const response = await pending
        const body = (await response.json()) as { code: number; message: string; data: T }
        expect(response.status(), `${label}: HTTP ${response.status()}`).toBe(200)
        expect(body.code, `${label}: ${body.message}`).toBe(0)
        return body.data
      }
      const headers = { authorization: `Bearer ${token}` }
      await envelope<unknown>(
        request.put(`${API_URL}/api/v1/datasets/${datasetId}/metadata/config`, {
          headers,
          data: {
            metadata: [
              { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane', enum: null },
            ],
          },
        }),
        'PUT …/metadata/config',
      )
      const [doc] = await envelope<{ id: string }[]>(
        request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
          headers,
          multipart: {
            file: {
              name: 'e2e-s30-rok-2023.txt',
              mimeType: 'text/plain',
              buffer: Buffer.from('Raport o środowisku z 2023 roku.', 'utf-8'),
            },
          },
        }),
        'POST …/documents (fixture)',
      )
      expect(doc, 'upload zwrócił dokładnie jeden dokument').toBeDefined()
      await envelope<unknown>(
        request.patch(`${API_URL}/api/v1/datasets/${datasetId}/documents/${doc?.id}`, {
          headers,
          data: { meta_fields: { rok: '2023' } },
        }),
        'PATCH …/documents/{id} (meta_fields)',
      )
      return { token, datasetId }
    })()
    return shared
  }

  test.afterAll(async ({ request }) => {
    if (shared === undefined) return
    const { token, datasetId } = await shared
    await deleteDataset(request, token, datasetId)
  })

  test('chip „Metadane: 1 warunek” nie zawija „Prześlij plik” do drugiej linii (1280)', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    const { datasetId } = await seeded(request)

    await page.goto(`/dataset/files/${datasetId}`)
    await expect(page.getByTestId('files-search')).toBeVisible()

    // Filtr metadanych: warunek `rok = 2023`. Wartość: przy znanych wartościach combobox
    // z podpowiedziami (metadane dokumentu dają `2023`), bez nich pole tekstowe — oba
    // kształty (wzór `fillConditionValue` z s25).
    await page.getByTestId('metadata-filter').click()
    const row = page.getByRole('group', { name: 'Warunek 1' })
    await expect(row).toBeVisible()
    await row.getByRole('combobox', { name: 'Klucz' }).click()
    await page.getByRole('option', { name: 'rok', exact: true }).click()
    await row.getByRole('combobox', { name: 'Operator' }).click()
    await page.getByRole('option', { name: '=', exact: true }).click()
    const valueBox = row
      .getByRole('combobox', { name: 'Wartość' })
      .or(row.getByRole('textbox', { name: 'Wartość' }))
    await valueBox.click()
    const option = page.getByRole('option', { name: '2023', exact: true })
    if ((await option.count()) > 0) {
      await option.click()
    } else {
      await page.keyboard.type('2023')
      await page.keyboard.press('Enter')
    }
    await page.getByRole('button', { name: 'Zastosuj' }).click()

    const chip = page.getByTestId('metadata-filter-chip')
    await expect(chip).toBeVisible()

    // Defekt z C15: chip wypychał „Prześlij plik” do drugiego wiersza. Teraz cały pasek
    // stoi w jednym wierszu — środeki (y + wysokość/2; elementy mają różne wysokości,
    // wiersz je centruje) zgodne w granicach kilku px.
    const center = (box: { y: number; height: number }): number => box.y + box.height / 2
    const searchBox = await page.getByTestId('files-search').boundingBox()
    const addButton = await page.getByTestId('files-add').boundingBox()
    const chipBox = await chip.boundingBox()
    expect(searchBox, 'pole wyszukiwania widoczne').not.toBeNull()
    expect(addButton, 'przycisk „Prześlij plik” widoczny').not.toBeNull()
    expect(chipBox, 'chip filtra widoczny').not.toBeNull()
    expect(
      Math.abs(center(searchBox ?? { y: 0, height: 0 }) - center(addButton ?? { y: 1, height: 0 })),
      '„Prześlij plik” w wierszu wyszukiwania',
    ).toBeLessThanOrEqual(4)
    expect(
      Math.abs(center(chipBox ?? { y: 0, height: 0 }) - center(searchBox ?? { y: 1, height: 0 })),
      'chip w wierszu wyszukiwania',
    ).toBeLessThanOrEqual(4)
    await expectNoLayoutDefects(page, 'pasek narzędzi plików z chipem filtra (SC-V12-z-V3)')
  })
})

test.describe('SC-V12-z-V4 szkielet ładowania kluczy API', () => {
  test.describe('390 px', () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test('szkielet wierszy zamiast gołego szarego prostokąta (390)', async ({ page }) => {
      // Opóźniony chunk `KeysGrid` — stan ładowania staje się obserwowalny jak na wolnym
      // łączeniu (w V12-z-2b: 1–2 s pustego prostokąta przy pierwszym wejściu).
      await page.route(/KeysGrid/, async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 1200))
        await route.continue()
      })
      await page.goto('/user-setting/api')

      // Fallback `Suspense` to szkielet wierszy (nagłówek + dane), nie jeden prostokąt.
      const skeleton = page.getByTestId('keys-grid-skeleton')
      await expect(skeleton).toBeVisible()
      expect(
        await skeleton.locator('.MuiSkeleton-root').count(),
        'szkielet ma nagłówek i wiersze, nie jeden prostokąt',
      ).toBeGreaterThan(2)

      // Po doładowaniu chunku szkielet znika, a strona przechodzi do siatki.
      await expect(skeleton).toBeHidden({ timeout: 30_000 })
      await expectNoLayoutDefects(page, 'strona Klucze API po załadowaniu (SC-V12-z-V4)')
    })
  })
})
