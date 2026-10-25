// SC-E5-H9-01…02 (brief WP E5-H9 T1a; asercje U11 i krok 4 uzupełnia T9): scenariusze z
// `work/wp/E5-H9/SCENARIOS.md` — akcent fokusu/kontrolek (T2: `secondary`) i walidacja U11
// (T3/T9). SC-03…04 są w `s24-h9-a2.spec.ts`; `test.fixme`/`test.skip` zabronione.
import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { createDataset } from './helpers'
import { dropFile } from './helpers/dnd'
import {
  apiTokenOnce,
  computedStyle,
  isGreenish,
  isReddish,
  SAMPLE_MIME,
  sampleBytes,
} from './helpers/h9'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (T11): limiter logowań 10/min per IP+e-mail jest współdzielony w biegu
// (`helpers/session.ts`).
const session = uiSession('s24-h9-a')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.setTimeout(90_000)

// Retry wyłączony dla tego pliku: czerwienie są świadome (raport zadania T1a), a pass retry
// tworzy nowego workera — beforeAll loguje się ponownie przez UI i łącznie z pozostałymi
// logowaniami dobija limiter 10/min (429 kaskadowo wyłączało resztę pliku; MAJOR review T1a).
test.describe.configure({ retries: 0 })

/** Wyłącza przejścia CSS: kolory stanów czytane od razu jako wartość końcowa (wzór s20). */
async function freezeTransitions(page: Page): Promise<void> {
  await page.addStyleTag({ content: '*{transition:none!important}' })
}

// ── SC-E5-H9-01: fokus i włączone kontrolki nie wyglądają jak błąd ─────────────────────────
for (const variant of [
  { mode: 'jasny', colorScheme: 'light' },
  { mode: 'ciemny', colorScheme: 'dark' },
] as const) {
  test.describe(`SC-E5-H9-01 konfiguracja datasetu (${variant.mode})`, () => {
    test.use({ viewport: { width: 1280, height: 800 }, colorScheme: variant.colorScheme })
    let cleanup: { token: string; datasetId: string } | undefined
    test.afterEach(async ({ request }) => {
      if (cleanup !== undefined) {
        await deleteDataset(request, cleanup.token, cleanup.datasetId)
        cleanup = undefined
      }
    })

    test(`SC-E5-H9-01 krok 1 i 5: fokus pola „Nazwa” nie czerwony; „Zapisz” bez akcentu (${variant.mode})`, async ({
      page,
      request,
    }) => {
      const token = await apiTokenOnce(request)
      cleanup = {
        token,
        datasetId: await createDataset(request, token, `E2E H9-01 fokus (${variant.mode})`),
      }
      await page.goto(`/dataset/configuration/${cleanup.datasetId}`)
      await freezeTransitions(page)

      // Krok 1: klik w pole „Nazwa” — ramka i etykieta w akcencie nie-czerwonym (po T2: `secondary`).
      const field = page.getByRole('textbox', { name: 'Nazwa', exact: true })
      await field.click()
      await expect(field).toBeFocused()
      const border = await computedStyle(
        page.locator('.MuiOutlinedInput-root.Mui-focused'),
        'border-color',
      )
      const labelColor = await computedStyle(
        page.locator('label.MuiInputLabel-root.Mui-focused'),
        'color',
      )
      expect
        .soft(isReddish(border), `krok 1: ramka fokusu czerwona (${border}) — T2: akcent secondary`)
        .toBe(false)
      expect
        .soft(isReddish(labelColor), `krok 1: etykieta fokusu czerwona (${labelColor}) — T2`)
        .toBe(false)

      // Krok 5: przycisk główny „Zapisz” nie przyjmuje koloru akcentu fokusu (regresja T2:
      // zmiana akcentu nie może przemalować przycisków głównych — mają zostać kolorem marki).
      const save = page.getByRole('button', { name: 'Zapisz' })
      const saveBackground = await computedStyle(save, 'background-color')
      expect(saveBackground, 'krok 5: kolor marki, nie akcentu fokusu').not.toBe(border)

      await expectNoLayoutDefects(page, `konfiguracja datasetu, fokus pola (${variant.mode})`)
    })

    test(`SC-E5-H9-01 krok 2 i 3: przełącznik i suwak nie czerwone; „Zapisz” aktywne (${variant.mode})`, async ({
      page,
      request,
    }) => {
      const token = await apiTokenOnce(request)
      cleanup = {
        token,
        datasetId: await createDataset(request, token, `E2E H9-01 kontrolki (${variant.mode})`),
      }
      await page.goto(`/dataset/configuration/${cleanup.datasetId}`)
      await freezeTransitions(page)

      // Krok 3: włączony przełącznik („Zaawansowane” → „Excel jako HTML”) i suwak nie-czerwoni
      // (akcent `secondary`). MUI Switch ma rolę `switch`.
      await page.getByRole('button', { name: 'Zaawansowane' }).click()
      const html4excel = page.getByRole('switch', { name: 'Excel jako HTML' })
      await html4excel.click()
      const switchThumb = page.locator('.MuiSwitch-root .Mui-checked .MuiSwitch-thumb')
      const switchColor = await computedStyle(switchThumb, 'color')
      expect
        .soft(isReddish(switchColor), `krok 3: przełącznik czerwony (${switchColor}) — T2`)
        .toBe(false)
      const slider = page.locator('.MuiSlider-root').first()
      const thumbColor = await computedStyle(slider.locator('.MuiSlider-thumb'), 'background-color')
      const trackColor = await computedStyle(slider.locator('.MuiSlider-track'), 'background-color')
      expect
        .soft(isReddish(thumbColor), `krok 3: suwak (uchwyt) czerwony (${thumbColor}) — T2`)
        .toBe(false)
      expect
        .soft(isReddish(trackColor), `krok 3: suwak (ścieżka) czerwona (${trackColor}) — T2`)
        .toBe(false)

      // Krok 2 (U11): czyszczenie nazwy nie wyłącza „Zapisz”; JEDEN klik ujawnia czerwień
      // i wraca fokusem (T9): mousedown „Zapisz” nie zabiera fokusu polu, więc helperText
      // pojawia się dopiero po kliku — układ nie przeskakuje między mousedown a mouseup.
      const name = page.getByRole('textbox', { name: 'Nazwa', exact: true })
      await name.fill('')
      const save = page.getByRole('button', { name: 'Zapisz' })
      await expect(save, 'krok 2 (U11): „Zapisz” aktywny przy pustym polu').toBeEnabled()
      await save.click()
      await expect(page.getByText('Pole wymagane'), 'krok 2: komunikat pod polem').toBeVisible()
      await expect.soft(name, 'krok 2: fokus na polu Nazwa od pierwszego kliku (T9)').toBeFocused()
      await expect
        .soft(page.locator('label.MuiInputLabel-root.Mui-error'), 'krok 2: etykieta nad polem')
        .toHaveAttribute('data-shrink', 'true')
      const errRoot = page.locator('.MuiOutlinedInput-root.Mui-error')
      const errorBorder = await computedStyle(errRoot, 'border-color')
      expect(isReddish(errorBorder), `krok 2: ramka błędu czerwona (${errorBorder})`).toBe(true)
    })
  })
}

test('SC-E5-H9-01 krok 4: upload — postęp nie czerwony, znacznik sukcesu zielony', async ({
  page,
  request,
}) => {
  const token = await apiTokenOnce(request)
  const datasetId = await createDataset(request, token, 'E2E H9-01 upload')
  // Sprzątanie także przy czerwieni asercji (try/finally).
  try {
    await page.goto(`/dataset/files/${datasetId}`)
    await freezeTransitions(page)
    await page.getByTestId('files-add').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    await dropFile(
      page,
      page.getByTestId('upload-dropzone'),
      sampleBytes('sample.pdf'),
      'sample.pdf',
      SAMPLE_MIME['sample.pdf'],
    )
    await expect(dialog.getByText('sample.pdf')).toBeVisible()
    // Pasek postępu istnieje od dodania do kolejki (wartość 0) — kolor czytany bez wyścigu.
    const bar = page.getByTestId('upload-progress-0').locator('.MuiLinearProgress-bar1')
    const barColor = await computedStyle(bar, 'background-color')
    expect(isReddish(barColor), `krok 4: pasek postępu czerwony (${barColor})`).toBe(false)

    await page.getByTestId('upload-start').click()
    const marker = dialog.getByText('Przesłano', { exact: true })
    await expect(marker).toBeVisible({ timeout: 60_000 })
    // SC-01 krok 4: znacznik sukcesu przy pliku jest zielony (`success`), nie czerwony.
    const markerColor = await computedStyle(marker, 'color')
    expect(isReddish(markerColor), `krok 4: znacznik czerwony (${markerColor})`).toBe(false)
    expect(isGreenish(markerColor), `krok 4: znacznik sukcesu zielony (${markerColor})`).toBe(true)
    await expectNoLayoutDefects(page, 'dialog uploadu po zakończeniu')
  } finally {
    await deleteDataset(request, token, datasetId)
  }
})

// ── SC-E5-H9-02: ta sama walidacja pustego pola we wszystkich dialogach tworzenia (U11) ────
test.describe('SC-E5-H9-02 walidacja pustego pola (U11)', () => {
  type DialogSpec = { label: string; path: string; open: (page: Page) => Promise<void> }
  const dialogs: DialogSpec[] = [
    {
      label: 'Utwórz czat',
      path: '/chats',
      open: (page) => page.getByRole('button', { name: 'Utwórz czat' }).first().click(),
    },
    {
      label: 'Nowy folder',
      path: '/files',
      open: async (page) => {
        await page.getByTestId('files-add').click()
        await page.getByTestId('files-add-folder').click()
      },
    },
    {
      label: 'Utwórz dataset',
      path: '/datasets',
      // .first(): przycisk nagłówka jest w DOM zawsze; pusty stan dokłada drugi (wzór s20).
      open: (page) => page.getByRole('button', { name: 'Utwórz dataset' }).first().click(),
    },
    {
      label: 'Utwórz Search',
      path: '/searches',
      open: (page) => page.getByRole('button', { name: 'Utwórz wyszukiwarkę' }).first().click(),
    },
    {
      label: 'Nowy użytkownik',
      path: '/admin/users',
      open: (page) => page.getByTestId('admin-users-new').click(),
    },
  ]

  for (const spec of dialogs) {
    test(`SC-E5-H9-02 krok 1-2 (${spec.label}): przycisk aktywny, klik → komunikat, fokus, etykieta`, async ({
      page,
    }) => {
      await page.goto(spec.path)
      await spec.open(page)
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      // Krok 1 (U11): przycisk główny aktywny przy pustym polu — wyłączenie tylko w trakcie
      // wysyłki (K2 kontraktu).
      const submit = dialog.getByRole('button', { name: 'Utwórz', exact: true })
      await expect(
        submit,
        `krok 1 (U11): przycisk główny aktywny — ${spec.label} (T3)`,
      ).toBeEnabled()

      // Krok 2: klik przy pustym polu → komunikat pod polem, fokus wraca na pole, etykieta
      // zostaje nad polem (shrink).
      await submit.click()
      // .Mui-error: dialog datasetu ma stały helperText (metoda chunkowania) — sam
      // '.MuiFormHelperText-root' łamie strict mode (dwa dopasowania).
      await expect(dialog.locator('.MuiFormHelperText-root.Mui-error')).toBeVisible()
      const field = dialog.locator('input').first()
      await expect
        .soft(field, `krok 2 (U11): fokus na błędnym polu — ${spec.label} (T3)`)
        .toBeFocused()
      await expect
        .soft(
          dialog.locator('label.MuiInputLabel-root.Mui-error'),
          `krok 2 (U11): etykieta nad polem (shrink) — ${spec.label} (T3)`,
        )
        .toHaveAttribute('data-shrink', 'true')
    })
  }

  test('SC-E5-H9-02 krok 3 i 5 (Nowy folder): wpisanie gasi komunikat; ponowne otwarcie czyste', async ({
    page,
  }) => {
    await page.goto('/files')
    await page.getByTestId('files-add').click()
    await page.getByTestId('files-add-folder').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // Krok 2 wtórnie: stan błędu („Nowy folder” ma przycisk aktywny już dziś).
    await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
    const helper = dialog.locator('.MuiFormHelperText-root')
    await expect(helper).toBeVisible()
    // Krok 3: komunikat znika od razu po wpisaniu wartości.
    await dialog.getByTestId('files-folder-name').fill('E2E H9-02 folder')
    await expect(helper).toBeHidden()
    // Krok 5: zamknięcie i ponowne otwarcie — stan czysty (U7).
    await dialog.getByRole('button', { name: 'Anuluj' }).click()
    await expect(dialog).toBeHidden()
    await page.getByTestId('files-add').click()
    await page.getByTestId('files-add-folder').click()
    await expect(dialog.getByTestId('files-folder-name')).toHaveValue('')
    await expect(dialog.locator('.MuiFormHelperText-root')).toHaveCount(0)
  })

  test('SC-E5-H9-02 krok 1 (Nowy klucz API): przycisk aktywny — nazwa opcjonalna', async ({
    page,
  }) => {
    await page.goto('/user-setting/api')
    await page.getByRole('button', { name: 'Utwórz klucz' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // Nazwa klucza jest opcjonalna, więc „puste pole” tu nie blokuje — przycisk ma (i ma być)
    // aktywny (K2: wyłączenie tylko w trakcie wysyłki). Kroku 2 brak — nie ma pola wymaganego.
    await expect(dialog.getByRole('button', { name: 'Utwórz', exact: true })).toBeEnabled()
  })
})
