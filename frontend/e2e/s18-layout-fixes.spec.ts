// Scenariusze SC-E5-H8d-02…06 (work/wp/E5-H8d/SCENARIOS.md, R-UI-01…05): wady układu znalezione
// w przeglądzie zrzutów 390 px (2026-10-09) — szuflada ustawień czatu poza ekranem, zasłonięte
// zakładki admina, długa nazwa pliku bez wielokropka, zasłonięte przyciski menedżera plików i pole
// pytania oderwane od dolnej krawędzi. Asercje są BEZPOŚREDNIE (getBoundingClientRect /
// elementFromPoint), więc padają na bazie niezależnie od `layout-known-defects.ts` (kontrakt C4);
// strażnik `expectNoLayoutDefects` zostaje na końcu każdego testu — lista znanych wad nie jest tu
// zmieniana. Backend nie jest mockowany.
import type { Locator, Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'

import {
  POLL_TIMEOUT_MS,
  apiLogin,
  createChat,
  createDataset,
  deleteAllChats,
  loginViaUi,
} from './helpers'
import { deleteAllFiles, deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'

const NARROW = { width: 390, height: 844 }
const WIDE = { width: 1280, height: 800 }

const DATASET_NAME = 'E2E S18 długa nazwa'
// Nazwa pliku 70 znaków (SC-E5-H8d-04: „plik o nazwie 70 znaków”; wzór: fixture z visual.spec.ts,
// który ma 69 znaków — dopisane „2” daje dokładnie 70).
const LONG_NAME = 'raport-rynek-pracy-2024-wersja-ostateczna-po-korekcie-redakcyjnej2.txt'
const DOC_BODY =
  'Zamek Królewski na Wawelu wznosi się na wzór nad Wisłą i przez stulecia był siedzibą królów Polski.'
const FOLDER_NAME = 'E2E S18 folder'
const FILE_NAME = 'e2e-s18-plik.txt'
const FILE_BODY = 'Treść pliku e2e S18'
const CHAT_NAME = 'E2E S18 czat'
// Pytanie długości ponad ekran (fake-llm skraca ODPOWIEDŹ do ~100 znaków — „Odpowiedź testowa: ”
// plus pierwsze 80 znaków pytania, tools/fake-llm answers.py — więc długość listy bierze się z
// wypowiedzi użytkownika; istotne są asercje: pole przy dole, lista się przewija, ostatnia widoczna).
const LONG_QUESTION = 'Opowiedz o Wawelu, smoku wawelskim, katedrze i dzwonie Zygmunt. '.repeat(45)

/** Dane scenariusza do sprzątania; ustawiane po udanym seedu przez API. */
let cleanup: { token: string; chats?: boolean; files?: boolean; datasetId?: string } | undefined

test.afterEach(async ({ request }) => {
  if (cleanup === undefined) return
  if (cleanup.chats === true) await deleteAllChats(request, cleanup.token)
  if (cleanup.files === true) await deleteAllFiles(request, cleanup.token)
  if (cleanup.datasetId !== undefined)
    await deleteDataset(request, cleanup.token, cleanup.datasetId)
  cleanup = undefined
})

/** Odczyt prostokąta w przestrzeni strony (viewport) — do asercji krawędzi. */
async function rectOf(locator: Locator): Promise<{ left: number; right: number; bottom: number }> {
  return locator.evaluate((el) => {
    const rect = el.getBoundingClientRect()
    return { left: rect.left, right: rect.right, bottom: rect.bottom }
  })
}

/** Pole pytania ma sięgać dolnej krawędzi okna (odstęp ≤ 24 px; SC-E5-H8d-06). */
async function assertFieldAtBottom(page: Page, input: Locator, when: string): Promise<void> {
  const { bottom } = await rectOf(input)
  const viewportHeight = page.viewportSize()?.height ?? 0
  expect(
    bottom,
    `${when}: dolna krawędź pola pytania ≥ ${viewportHeight} − 24 px (mierzone: ${bottom})`,
  ).toBeGreaterThanOrEqual(viewportHeight - 24)
}

/** Środek pionowy prostokąta elementu (viewport). */
async function centerYOf(locator: Locator): Promise<number> {
  return locator.evaluate((el) => {
    const rect = el.getBoundingClientRect()
    return rect.top + rect.height / 2
  })
}

/**
 * R-UI-04 naprawdę (T7): przy 1280 px kolumna akcji kończy się w obrębie kontenera przewijania
 * siatki (`.MuiDataGrid-virtualScroller` — brak poziomego przewijania treści; MUI X dokłada za
 * ostatnią kolumnę 5 px wypełniacza paska przewijania, więc `scrollWidth` bywa o te 5 px większe
 * bez żadnego ucięcia), a KAŻDY przycisk wiersza leży w całości wewnątrz kontenera — klip nie
 * ucina ostatniego przycisku (kosz / ⋮).
 */
async function assertRowFitsGrid(row: Locator, when: string): Promise<void> {
  const scroller = row.page().locator('.MuiDataGrid-virtualScroller')
  const scrollerBox = await scroller.boundingBox()
  expect(scrollerBox, `${when}: kontener przewijania siatki widoczny`).not.toBeNull()
  const rightLimit = scrollerBox!.x + scrollerBox!.width
  const actionsCell = row.locator('[data-field="actions"]')
  const cellRight = await actionsCell.evaluate((el) => el.getBoundingClientRect().right)
  expect(
    cellRight,
    `${when}: prawa krawędź kolumny akcji (${cellRight}) ≤ prawa krawędź siatki (${rightLimit}) — bez przewijania poziomego`,
  ).toBeLessThanOrEqual(rightLimit + 1)
  const buttons = row.getByRole('button')
  const count = await buttons.count()
  expect(count, `${when}: wiersz ma przyciski`).toBeGreaterThan(0)
  for (let i = 0; i < count; i += 1) {
    const box = await buttons.nth(i).boundingBox()
    expect(box, `${when}: przycisk ${i} ma prostokąt`).not.toBeNull()
    expect(
      box!.x + box!.width,
      `${when}: prawa krawędź przycisku ${i} (${box!.x + box!.width}) ≤ prawa krawędź siatki (${rightLimit})`,
    ).toBeLessThanOrEqual(rightLimit + 1)
  }
}

test.describe('SC-E5-H8d-02 szuflada ustawień czatu mieści się na ekranie (390)', () => {
  test.use({ viewport: NARROW })

  test('szuflada w całości w viewportcie, Esc zamyka', async ({ page, request }) => {
    test.setTimeout(60_000)
    await resetDb(request)
    const token = await apiLogin(request)
    const chatId = await createChat(request, token, { name: `${CHAT_NAME} 02` })
    cleanup = { token, chats: true }

    await loginViaUi(page)
    await page.goto(`/chat/${chatId}`)
    await page.getByRole('button', { name: 'Ustawienia czatu' }).click()

    // Szuflada „Ustawienia czatu” (paper) ma mieścić się w CAŁOŚCI: left ≥ 0 i right ≤ 390 (R-UI-01).
    const paper = page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
    await expect(paper).toBeVisible()
    // Koniec animacji wejścia MUI Slide przed pomiarem (MINOR z T1): tuż po `toBeVisible` slajd
    // trwa i „right” zależy od fazy (na bazie mierzono 571–622 px). Easing MUI nie przestrzeliwuje,
    // więc `right` maleje monotonicznie do wartości ustalonej — poll czeka właśnie na nią.
    const viewportWidth = page.viewportSize()?.width ?? 0
    await expect.poll(async () => (await rectOf(paper)).right).toBeLessThanOrEqual(viewportWidth)
    const { left, right } = await rectOf(paper)
    expect(left, `lewa krawędź szuflady ≥ 0 (mierzone: ${left})`).toBeGreaterThanOrEqual(0)
    expect(
      right,
      `prawa krawędź szuflady ≤ ${viewportWidth} (mierzone: ${right})`,
    ).toBeLessThanOrEqual(viewportWidth)

    // Klawiatura: Esc zamyka szufladę (wariant scenariusza).
    await page.keyboard.press('Escape')
    await expect(paper).toBeHidden()
    await expectNoLayoutDefects(page, 'czat po zamknięciu szuflady (390)')
  })
})

test.describe('SC-E5-H8d-03 zakładki admina niezasłonięte i klikalne (390)', () => {
  test.use({ viewport: NARROW })

  const TABS = [
    { testId: 'admin-tab-users', path: /\/admin\/users$/, content: 'admin-users' },
    { testId: 'admin-tab-access', path: /\/admin\/access$/, content: 'admin-access' },
    { testId: 'admin-tab-status', path: /\/admin\/status$/, content: 'admin-status' },
    {
      testId: 'admin-tab-integrations',
      path: /\/admin\/integrations$/,
      content: 'admin-integrations',
    },
  ]

  test('każda zakładka osiągalna bez zasłonięcia; klik otwiera treść', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000)
    await resetDb(request)
    cleanup = undefined // administracja niczego nie tworzy
    await loginViaUi(page)
    await page.goto('/admin/users')
    await expect(page.getByTestId('admin-users')).toBeVisible()

    const viewportWidth = page.viewportSize()?.width ?? 0

    /**
     * Zakładki przycięte krawędzią: część widoczna, ale nie w CAŁOŚCI — ani w oknie, ani w
     * obszarze klienta scrollera paska (pod widocznym przyciskiem przewijania). Taka zakładka
     * jest widoczna dla użytkownika, ale klik w jej środek trafia w klip lub sąsiada (U3).
     */
    const clippedTabs = async (): Promise<string[]> => {
      const scrollerBox = await page.locator('.MuiTabs-scroller').boundingBox()
      const bad: string[] = []
      for (const { testId } of TABS) {
        const box = await page.getByTestId(testId).boundingBox()
        if (box === null) continue
        // W ogóle poza oknem (albo w całości w nim) — to nie jest „przycięcie”.
        const intersectsWindow = box.x < viewportWidth && box.x + box.width > 0
        if (!intersectsWindow) continue
        if (box.x < -1 || box.x + box.width > viewportWidth + 1) {
          bad.push(testId)
          continue
        }
        // W całości w oknie, ale wystaje z obszaru klienta scrollera — leży pod widocznym
        // przyciskiem przewijania albo pod klipem paska (na bazie: „Dostęp do asystentów”).
        if (scrollerBox !== null) {
          const left = scrollerBox.x
          const right = scrollerBox.x + scrollerBox.width
          const inside = box.x >= left - 1 && box.x + box.width <= right + 1
          const outside = box.x + box.width <= left + 1 || box.x >= right - 1
          if (!inside && !outside) bad.push(testId)
        }
      }
      return bad
    }

    // Wzmocnienie (R-UI-02): telefon dostaje narzędzie nawigacji — widoczne przyciski
    // przewijania — albo (układ po naprawie: zakładki zawijane) wszystkie zakładki mieszczą się
    // w całości w oknie.
    const scrollButtons = page.locator('.MuiTabs-scrollButtons')
    await expect
      .poll(async () => {
        if (await scrollButtons.last().isVisible()) return true
        return (await clippedTabs()).length === 0
      })
      .toBe(true)
    expect(
      await clippedTabs(),
      'żadna widoczna zakładka nie jest przycięta oknem ani scrollerem paska',
    ).toEqual([])

    // Droga użytkownika: klik BEZ force i BEZ ręcznego scrollIntoView — wszystkie zakładki,
    // także „Dostęp do asystentów”, otwierają swoją treść. „Niezasłonięte” pilują asercje
    // bezpośrednie wyżej (strażnik po zmianie T4 pomija elementy przycięte przez klip).
    for (const { testId, path, content } of TABS) {
      const tab = page.getByTestId(testId)
      await tab.click()
      await expect(page).toHaveURL(path)
      await expect(page.getByTestId(content)).toBeVisible()
    }
    expect(
      await clippedTabs(),
      'po przejściu zakładek żadna widoczna zakładka nie jest przycięta',
    ).toEqual([])
    await expectNoLayoutDefects(page, 'administracja po przejściu zakładek (390)')
  })
})

for (const [label, viewport] of [
  ['1280', WIDE],
  ['390', NARROW],
] as const) {
  test.describe(`SC-E5-H8d-04 długa nazwa pliku w datasecie (${label})`, () => {
    test.use({ viewport })

    test('nazwa 70 znaków: wielokropek, podpowiedź, nie wchodzi w kolumnę daty', async ({
      page,
      request,
    }) => {
      test.setTimeout(120_000)
      await resetDb(request)
      const token = await apiLogin(request)
      const datasetId = await createDataset(request, token, DATASET_NAME)
      cleanup = { token, datasetId }

      // Wiersz listy wystarczy — plik wchodzimy przez API bez parsowania (upload-only).
      const uploaded = await request.post(
        `${process.env.WD_E2E_API_URL ?? ''}/api/v1/datasets/${datasetId}/documents`,
        {
          headers: { authorization: `Bearer ${token}` },
          multipart: {
            file: {
              name: LONG_NAME,
              mimeType: 'text/plain',
              buffer: Buffer.from(DOC_BODY, 'utf-8'),
            },
          },
        },
      )
      expect(uploaded.status(), `upload dokumentu: HTTP ${uploaded.status()}`).toBe(200)
      const uploadedBody = (await uploaded.json()) as { code: number; data: { id: string }[] }
      expect(uploadedBody.code, 'koperta uploadu').toBe(0)
      // Id dokumentu z odpowiedzi uploadu — parse w wariancie 1280 używa go jawnie (data-id
      // wiersza bywa niedostępne i API milczy wtedy z code 102, co rozłaziło się z czerwienią).
      const uploadedDocId = uploadedBody.data[0]!.id

      await loginViaUi(page)
      await page.goto(`/dataset/files/${datasetId}`)
      const row = page.getByRole('row').filter({ has: page.getByRole('link', { name: LONG_NAME }) })
      await expect(row).toBeVisible()
      expect(LONG_NAME, 'nazwa scenariusza ma 70 znaków').toHaveLength(70)

      const link = row.getByRole('link', { name: LONG_NAME })
      // Podpowiedź z PEŁNĄ nazwą (hover/fokus; kontrakt: „pełna nazwa w podpowiedzi”).
      await expect(link).toHaveAttribute('title', LONG_NAME)

      // Wielokropek: computed `text-overflow: ellipsis` gdziekolwiek na łańcuchu link → komórka.
      const ellipsis = await link.evaluate((el) => {
        const cell = el.closest('.MuiDataGrid-cell')
        for (let node: Element | null = el; node !== null; node = node.parentElement) {
          if (getComputedStyle(node).textOverflow === 'ellipsis') return true
          if (node === cell) return false
        }
        return false
      })
      expect(ellipsis, 'text-overflow: ellipsis na komórce nazwy').toBe(true)

      // Geometria: prawa krawędź nazwy nie przekracza lewej krawędzi kolumny „Data przesłania”.
      const { right: nameRight } = await rectOf(link)
      const dateLeft = await row
        .locator('[data-field="create_time"]')
        .evaluate((el) => el.getBoundingClientRect().left)
      expect(
        nameRight,
        `prawa krawędź nazwy (${nameRight}) ≤ lewa krawędź kolumny daty (${dateLeft})`,
      ).toBeLessThanOrEqual(dateLeft)

      // T7: przy 1280 px kolumna „Akcje” i komórka statusu mieszczą się w siatce bez przewijania
      // poziomego, a pigułka statusu i przycisk ponowienia mają wspólną oś pionową (±4 px).
      // Pigułka („Sukces”) + ↻ pojawiają się dopiero po sparsowaniu — dokument prowadzimy do
      // „done” tym samym API, które woła przycisk ▶ (wzór seedCorpus).
      if (label === '1280') {
        const parseResponse = await request.post(
          `${process.env.WD_E2E_API_URL ?? ''}/api/v1/datasets/${datasetId}/documents/parse`,
          {
            headers: { authorization: `Bearer ${cleanup?.token ?? ''}` },
            data: { document_ids: [uploadedDocId] },
          },
        )
        expect(parseResponse.status(), `parse dokumentu: HTTP ${parseResponse.status()}`).toBe(200)
        const parseBody = (await parseResponse.json()) as {
          code: number
          data: { success_count: number }
        }
        expect(parseBody.code, 'koperta parse').toBe(0)
        expect(parseBody.data.success_count, 'parse przyjął dokument').toBe(1)
        // Parse szedł poza UI (API), więc react-query nie unieważnił listy, a `shouldPoll`
        // nie pollowa dokumentu w idle — odświeżamy jak użytkownik F5, by lista pobrała stan.
        await page.reload()
        await expect(row, 'wiersz po odświeżeniu').toBeVisible()

        const chip = row.locator('[data-testid^="status-log-"]')
        await expect(chip, 'pigulka statusu po sparsowaniu').toHaveText('Sukces', {
          timeout: POLL_TIMEOUT_MS,
        })
        await assertRowFitsGrid(row, 'dataset 1280 — wiersz')
        const reparse = row.locator('[data-testid^="status-parse-"]')
        await expect(reparse).toBeVisible()
        const chipCenterY = await centerYOf(chip)
        const reparseCenterY = await centerYOf(reparse)
        expect(
          Math.abs(chipCenterY - reparseCenterY),
          `dataset 1280: pigulka (${chipCenterY}) vs ponowienie (${reparseCenterY}) ≤ 4 px`,
        ).toBeLessThanOrEqual(4)
      }

      await expectNoLayoutDefects(page, `dataset pliki — długa nazwa (${label})`)
    })
  })

  test.describe(`SC-E5-H8d-05 menedżer plików bez zasłoniętych przycisków (${label})`, () => {
    test.use({ viewport })

    test('folder i plik: środek każdego widocznego przycisku jest klikalny', async ({
      page,
      request,
    }) => {
      test.setTimeout(120_000)
      await resetDb(request)
      const token = await apiLogin(request)
      cleanup = { token, files: true }

      await loginViaUi(page)
      await page.goto('/files')
      await expect(page.getByRole('heading', { name: 'Pliki' })).toBeVisible()

      // Folder przez UI (wzór S6-13)…
      await page.getByTestId('files-add').click()
      await page.getByTestId('files-add-folder').click()
      const folderDialog = page.getByRole('dialog')
      await folderDialog.getByTestId('files-folder-name').fill(FOLDER_NAME)
      await folderDialog.getByTestId('files-folder-create').click()
      await expect(folderDialog).toBeHidden()
      // …i plik, żeby siatka miała oba rodzaje wierszy.
      await page.getByTestId('files-add').click()
      await page.getByTestId('files-add-upload').click()
      const uploadDialog = page.getByRole('dialog')
      await expect(uploadDialog).toBeVisible()
      await page.getByTestId('files-upload-input').setInputFiles({
        name: FILE_NAME,
        mimeType: 'text/plain',
        buffer: Buffer.from(FILE_BODY),
      })
      await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
        timeout: 60_000,
      })
      await page.getByTestId('files-upload-close').click()
      await expect(uploadDialog).toBeHidden()
      await expect(
        page.getByTestId('files-grid').getByRole('row').filter({ hasText: FOLDER_NAME }),
      ).toBeVisible()

      // R-UI-04: środek KAŻDEGO widocznego przycisku jest osiągalny — elementFromPoint zwraca
      // ten przycisk albo jego potomka (ta sama semantyka „covered” co w strażniku
      // helpers/layout.ts, łącznie z pomijaniem toastów Snackbar — znikają same i nie są wadą
      // układu ekranu).
      const covered = await page.evaluate(() => {
        const describe = (el: Element): string => {
          const id = el.getAttribute('data-testid') ?? el.getAttribute('aria-label') ?? el.id
          const text = (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 30)
          return `${el.tagName.toLowerCase()}${id ? `[${id}]` : ''}${text ? ` „${text}”` : ''}`
        }
        const bad: string[] = []
        for (const el of Array.from(document.querySelectorAll('button'))) {
          // Toasty są pomijane w całości (skanowany przycisk i zasłaniający element).
          if (el.closest('.MuiSnackbar-root') !== null) continue
          const rect = el.getBoundingClientRect()
          if (rect.width < 1 || rect.height < 1) continue
          const style = getComputedStyle(el)
          if (style.visibility === 'hidden' || style.display === 'none') continue
          const x = rect.left + rect.width / 2
          const y = rect.top + rect.height / 2
          if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue
          const top = document.elementFromPoint(x, y)
          if (top === null || top === el || el.contains(top) || top.contains(el)) continue
          if (top.closest('.MuiSnackbar-root') !== null) continue
          const owner = el.closest(
            '.MuiFormControl-root, .MuiButtonBase-root, .MuiInputBase-root, label',
          )
          if (owner !== null && owner.contains(top)) continue
          bad.push(`${describe(el)} zasłonięty przez ${top === null ? 'null' : describe(top)}`)
        }
        return bad
      })
      expect(covered, `zasłonięte przyciski menedżera plików (${label})`).toEqual([])

      // T7 (R-UI-04 naprawdę): przy 1280 px przyciski akcji wiersza pliku mieszczą się w całości
      // w obszarze siatki bez przewijania poziomego (kosz przycięty prawą krawędzią na bazie),
      // a ikona komórki „Nazwa” leży na osi pionowej komórki „Data” (±4 px).
      if (label === '1280') {
        const fileRow = page
          .getByTestId('files-grid')
          .getByRole('row')
          .filter({ hasText: FILE_NAME })
        await expect(fileRow).toBeVisible()
        await assertRowFitsGrid(fileRow, 'menedżer 1280 — wiersz pliku')
        const iconCenterY = await centerYOf(fileRow.locator('[data-field="name"] svg'))
        const dateCenterY = await centerYOf(fileRow.locator('[data-field="update_time"]'))
        expect(
          Math.abs(iconCenterY - dateCenterY),
          `menedżer 1280: ikona nazwy (${iconCenterY}) vs data (${dateCenterY}) ≤ 4 px`,
        ).toBeLessThanOrEqual(4)
      }

      await expectNoLayoutDefects(page, `menedżer plików — folder i plik (${label})`)
    })
  })

  test.describe(`SC-E5-H8d-06 pole pytania przy dolnej krawędzi (${label})`, () => {
    test.use({ viewport })

    test('pusta rozmowa i wymiana z długą wypowiedzią — pole zostaje przy dole', async ({
      page,
      request,
    }) => {
      test.setTimeout(180_000)
      await resetDb(request)
      const token = await apiLogin(request)
      const chatId = await createChat(request, token, { name: `${CHAT_NAME} 06 ${label}` })
      cleanup = { token, chats: true }

      await loginViaUi(page)
      await page.goto(`/chat/${chatId}`)
      const input = page.getByPlaceholder('Wpisz pytanie…')
      await expect(input).toBeVisible()

      // Krok 1: nowa pusta rozmowa — pole przy dolnej krawędzi, bez pustej przestrzeni pod nim.
      await assertFieldAtBottom(page, input, 'pusta rozmowa')

      // Krok 2: wymiana z treścią dłuższą niż ekran — pole ZOSTAJE przy dole, lista przewija się
      // nad nim, a ostatnia (asystenta) wiadomość jest widoczna.
      await input.fill(LONG_QUESTION)
      await page.getByRole('button', { name: 'Wyślij' }).click()
      await expect(page.getByTestId('message-assistant').last()).toContainText(
        'Odpowiedź testowa:',
        { timeout: 60_000 },
      )
      // Koniec streamu: przycisk wraca z „Zatrzymaj” na „Wyślij”.
      await expect(page.getByRole('button', { name: 'Wyślij' })).toBeVisible({ timeout: 60_000 })

      const scrolls = await page
        .getByTestId('message-list')
        .evaluate((el) => el.scrollHeight > el.clientHeight)
      expect(scrolls, 'lista wiadomości przewija się (treść dłuższa niż ekran)').toBe(true)
      await assertFieldAtBottom(page, input, 'po wymianie')
      await expect(page.getByTestId('message-assistant').last()).toBeInViewport()

      await expectNoLayoutDefects(page, `czat po wymianie (${label})`)
    })
  })
}
