// Scenariusze SC-E67-z2-13…15 i część SC-E67-z2-18 (nagłówek rozmowy) — work/wp/E67-z2/SCENARIOS.md,
// brief T3: wady wizualne z QA-UI E67-z2-1 — chipy metadanych (1600 px), przycisk „Utwórz wyszukiwarkę”
// (390 PL), nazwy plików w tabeli (390, 1280), nagłówki/daty tabeli użytkowników (EN), kafelek
// „Zobacz wszystkie” (390 PL), nagłówek rozmowy (wielokropek + title).
// Testy pisane PRZED poprawkami (czerwone z właściwej przyczyny). Wzorzec: s27-e67z2-a.spec.ts.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, Page } from '@playwright/test'

import { ADMIN_EMAIL, expect, test } from './fixtures'
import { apiLogin, createChat, createDataset } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const WIDE = { width: 1600, height: 900 }
const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }

const FILE_A = 'gus_pracujacy_w_gospodarce_narodowej_2025.txt'
const FILE_B = 'gus_rocznik_statystyczny_rzeczypospolitej_2025.txt'
const TXT_PATH = fileURLToPath(new URL('./fixtures/metadata-rok-typ.txt', import.meta.url))
const LONG_SESSION_NAME =
  'Ile osób pracowało w gospodarce narodowej w 2024 roku według rocznika statystycznego GUS i ile z nich było zatrudnionych w przemyśle'

let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

const session = uiSession('s27-e67z2-c')
test.use({ storageState: session.statePath })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

const cleanupDatasets: string[] = []
test.afterEach(async ({ context, request }) => {
  const token = await adminToken(request)
  for (const id of cleanupDatasets.splice(0)) await deleteDataset(request, token, id)
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

type Envelope<T> = { code: number; message: string; data: T }

/** Dataset z dwoma plikami o długich nazwach z tym samym początkiem; plik A ma metadane. */
async function seedFiles(request: APIRequestContext): Promise<{ id: string; name: string }> {
  const token = await adminToken(request)
  const name = `E2E z2c ${Date.now()}`
  const id = await createDataset(request, token, name)
  cleanupDatasets.push(id)
  const headers = { authorization: `Bearer ${token}` }
  const ids: string[] = []
  for (const fileName of [FILE_A, FILE_B]) {
    const response = await request.post(`${API_URL}/api/v1/datasets/${id}/documents`, {
      headers,
      multipart: {
        file: { name: fileName, mimeType: 'text/plain', buffer: readFileSync(TXT_PATH) },
      },
    })
    const body = (await response.json()) as Envelope<{ id: string }[]>
    expect(body.code, `upload ${fileName}: ${body.message}`).toBe(0)
    ids.push(body.data[0]!.id)
  }
  const patched = await request.patch(`${API_URL}/api/v1/datasets/${id}/documents/${ids[0]}`, {
    headers,
    data: { meta_fields: { rok: '2023', typ: 'raport', region: 'mazowieckie' } },
  })
  const patchedBody = (await patched.json()) as Envelope<unknown>
  expect(patchedBody.code, `PATCH meta_fields: ${patchedBody.message}`).toBe(0)
  return { id, name }
}

async function openFiles(page: Page, seeded: { id: string; name: string }): Promise<void> {
  await page.goto(`/dataset/files/${seeded.id}`)
  await expect(page.getByRole('heading', { name: seeded.name })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: FILE_A })).toBeVisible()
}

test('SC-E67-z2-13 1600 px: chipy metadanych w karcie Pliki pokazują pełne „klucz: wartość”', async ({
  page,
  request,
}) => {
  const seeded = await seedFiles(request)
  await page.setViewportSize(WIDE)
  await openFiles(page, seeded)
  const row = page.getByRole('row').filter({ hasText: FILE_A })
  const chips = row.locator('[data-field="meta_fields"] .MuiChip-label')
  await expect(chips.first()).toBeVisible()
  const clipped = await chips.evaluateAll((labels) =>
    labels
      .filter((label) => label.scrollWidth > label.clientWidth + 1)
      .map((label) => label.textContent),
  )
  expect(clipped, 'chipy metadanych nieucięte (scrollWidth ≤ clientWidth)').toEqual([])
  await expect(row.getByText('rok: 2023')).toBeVisible()
  await expect(row.getByText('typ: raport')).toBeVisible()
  await shot(page, 'desktop-1600-chips')
  await page.emulateMedia({ colorScheme: 'dark' })
  await shot(page, 'desktop-1600-chips-dark')
  await expectNoLayoutDefects(page, 'karta Pliki 1600 px: chipy metadanych (SC-13)')
})

test('SC-E67-z2-14 390 PL: przycisk „Utwórz wyszukiwarkę” w jednej linii i z paddingiem', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/searches')
  const buttons = page.getByRole('button', { name: 'Utwórz wyszukiwarkę' })
  await expect(buttons.first()).toBeVisible()
  for (const button of await buttons.all()) {
    // Ikona „+” i tekst leżą w jednej linii; zawinięty tekst daje trzecią wartość top.
    const text = await button.evaluate((el) => {
      const range = document.createRange()
      const node = [...el.childNodes].find((child) => child.nodeType === Node.TEXT_NODE)
      if (node === undefined) return { tops: 99 }
      range.selectNodeContents(node)
      return { tops: new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size }
    })
    expect(text.tops, 'przycisk „Utwórz wyszukiwarkę” nie zawija tekstu').toBe(1)
    const edges = await button.evaluate((el) => {
      const node = [...el.childNodes].find((child) => child.nodeType === Node.TEXT_NODE)
      const range = document.createRange()
      range.selectNodeContents(node ?? el)
      const rect = range.getBoundingClientRect()
      const box = el.getBoundingClientRect()
      return { left: rect.left - box.left, right: box.right - rect.right }
    })
    expect(edges.left, 'odstęp tekstu od lewej krawędzi przycisku').toBeGreaterThanOrEqual(6)
    expect(edges.right, 'odstęp tekstu od prawej krawędzi przycisku').toBeGreaterThanOrEqual(6)
  }
  await shot(page, 'mobile-searches')
  await expectNoLayoutDefects(page, 'lista Wyszukiwarek 390 PL (SC-14)')
})

// Minimum widocznych znaków nazwy: 1280 px — kolumna ≥ 180 px (Metoda chunkowania ukryta < xl), zawijająca się do 2 linii, 390 px — 160 px.
for (const [label, viewport, minChars] of [
  ['1280', DESKTOP, 24],
  ['390', MOBILE, 20],
] as const) {
  test(`SC-E67-z2-15 ${label}: tabela plików — nazwy plików odróżnialne (≥ ${minChars} widocznych znaków)`, async ({
    page,
    request,
  }) => {
    const seeded = await seedFiles(request)
    await page.setViewportSize(viewport)
    await openFiles(page, seeded)
    const links = [FILE_A, FILE_B].map((name) =>
      page.getByRole('row').filter({ hasText: name }).getByRole('link').first(),
    )
    for (const link of links) await expect(link).toBeVisible()
    // Dwa różne pliki muszą różnić się widocznym początkiem: po pierwszych N widocznych znakach.
    const heads = await Promise.all(
      links.map((link) =>
        link.evaluate((el) => {
          const text = el.textContent ?? ''
          const range = document.createRange()
          const node = el.firstChild!
          let visible = 0
          for (let i = 1; i <= text.length; i += 1) {
            range.setStart(node, 0)
            range.setEnd(node, i)
            const rects = [...range.getClientRects()]
            const box = el.getBoundingClientRect()
            const last = rects[rects.length - 1]
            if (
              last !== undefined &&
              last.right <= box.right + 1 &&
              last.bottom <= box.bottom + 1
            ) {
              visible = i
            }
          }
          return text.slice(0, visible)
        }),
      ),
    )
    expect(heads[0], 'widoczny początek nazwy A').not.toBe(heads[1])
    expect(heads[0]!.length, 'widocznych znaków nazwy A').toBeGreaterThanOrEqual(minChars)
    await shot(page, `files-${label}`)
    await page.emulateMedia({ colorScheme: 'dark' })
    await shot(page, `files-${label}-dark`)
    await expectNoLayoutDefects(page, `tabela plików ${label} px (SC-15)`)
  })
}

test('SC-E67-z2-15 390 PL: strona główna — kafelek „Zobacz wszystkie” nieucięty', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  await seedFiles(request)
  await createChat(request, token, { name: `E2E z2c czat ${Date.now()}` })
  await page.setViewportSize(MOBILE)
  await page.goto('/')
  const tiles = page.getByTestId('resource-card').filter({ hasText: 'Zobacz wszystkie' })
  await expect(tiles.first()).toBeVisible()
  for (const tile of await tiles.all()) {
    const label = tile.getByText('Zobacz wszystkie')
    const clipped = await label.evaluate((el) => el.scrollWidth > el.clientWidth + 1)
    expect(clipped, 'tekst „Zobacz wszystkie” nieucięty w kafelku').toBe(false)
    const fits = await tile.evaluate((el) => {
      const rect = el.getBoundingClientRect()
      const text = el.querySelector('p, h6, span, div')
      const textRect = text?.getBoundingClientRect()
      return textRect === undefined ? true : textRect.right <= rect.right + 1
    })
    expect(fits, 'tekst mieści się w kafelku').toBe(true)
  }
  await shot(page, 'mobile-home')
  await page.emulateMedia({ colorScheme: 'dark' })
  await shot(page, 'mobile-home-dark')
  await expectNoLayoutDefects(page, 'strona główna 390 PL (SC-15)')
})

test.describe('tabela użytkowników (EN)', () => {
  test.use({ locale: 'en-US' })

  for (const [label, viewport] of [
    ['1280', DESKTOP],
    ['390', MOBILE],
  ] as const) {
    test(`SC-E67-z2-15 ${label} EN: tabela użytkowników — nagłówki i data bez wielokropka`, async ({
      page,
    }) => {
      // Język profilu wygrywa z `wd.language` (K4) — podmieniamy go w odpowiedzi, bez zmiany konta z seedu.
      await page.route('**/api/v1/users/me', async (route) => {
        const response = await route.fetch()
        const json = (await response.json()) as { data: Record<string, unknown> }
        json.data.language = 'en'
        await route.fulfill({ response, json })
      })
      await page.setViewportSize(viewport)
      await page.goto('/admin/users')
      await expect(page.getByRole('columnheader', { name: 'Actions' })).toBeVisible()
      await expect(page.getByRole('gridcell', { name: ADMIN_EMAIL }).first()).toBeVisible()
      const clipped = await page
        .locator('.MuiDataGrid-columnHeaderTitle, .MuiDataGrid-cell')
        .evaluateAll((nodes) =>
          nodes
            .filter((el) => el.scrollWidth > el.clientWidth + 1)
            .map((el) => `${el.textContent}`),
        )
      expect(clipped, 'nagłówki i komórki tabeli użytkowników nieucięte').toEqual([])
      await shot(page, `users-${label}-en`)
      await page.emulateMedia({ colorScheme: 'dark' })
      await shot(page, `users-${label}-en-dark`)
      await expectNoLayoutDefects(page, `tabela użytkowników ${label} EN (SC-15)`)
    })
  }
})

test('SC-E67-z2-18 nagłówek rozmowy: wielokropek i title z pełną nazwą', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const chat = await createChat(request, token, { name: `E2E z2c nagłówek ${Date.now()}` })
  const response = await request.post(`${API_URL}/api/v1/chats/${chat}/sessions`, {
    headers: { authorization: `Bearer ${token}` },
    data: { name: LONG_SESSION_NAME },
  })
  const body = (await response.json()) as Envelope<{ id: string }>
  expect(body.code, `POST sessions: ${body.message}`).toBe(0)
  await page.setViewportSize(MOBILE)
  await page.goto(`/chat/${chat}?conversationId=${body.data.id}`)
  const header = page.getByTestId('chat-column').getByRole('heading', { level: 6 }).first()
  await expect(header).toBeVisible()
  await expect(header).toContainText('Ile osób pracowało')
  await expect(header, 'title z pełną nazwą rozmowy').toHaveAttribute('title', LONG_SESSION_NAME)
  const overflow = await header.evaluate((el) => ({
    ellipsis: getComputedStyle(el).textOverflow,
    cut: el.scrollWidth > el.clientWidth,
  }))
  expect(overflow.ellipsis, 'text-overflow: ellipsis').toBe('ellipsis')
  expect(overflow.cut, 'długa nazwa przekracza szerokość nagłówka (test sensowny)').toBe(true)
  await shot(page, 'mobile-chat-header')
  await expectNoLayoutDefects(page, 'nagłówek rozmowy 390 (SC-18)')
})
