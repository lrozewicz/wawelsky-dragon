// SC-E5-H8z-01 (brief T1, L1/L2 — MAJOR z QA E5-H8d-1, defekt M1): etykieta pola „Nazwa” w
// dialogu „Utwórz czat”, pole puste i w fokusie (autofokus → etykieta w stanie shrink,
// `translate(14px, -9px)`), ma być w CAŁOŚCI czytelna — w ciemnym i jasnym motywie, przy 1280
// i 390 px. Diagnoza (2026-10-11, praca na żywo): etykieta jest malowana w całości (nie ma
// zakrycia), ale jej dolna część leży na obrysie fokusu i ciemnym wypełnieniu pola
// (`MuiOutlinedInput` root ma `backgroundColor: background.default`), a kolor fokusu
// (primary.main = brand[400]) ma w ciemnym motywie ~3,5:1 na papierze — tekst tonie i wygląda
// na „ucięty” (u QA: ~4 px słik). Asercje BEZPOŚREDNIE: `elementFromPoint` w próbkach pola
// etykiety zwraca etykietę, etykieta shrink ma własne tło (łatka w kolorze powierzchni) i
// kontrast ≥ 4.5:1 z powierzchnią dialogu; na końcu strażnik układu i zrzuty do `.task/shots/`.
import { expect, test } from './fixtures'

import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (T11): limiter logowań (10/min per IP+e-mail, CONTRACT E5-2a §4) jest
// współdzielony z całym biegiem — patrz helpers/session.ts.
const session = uiSession('s20-input-label-focus')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.setTimeout(90_000)

type Variant = { mode: 'ciemny' | 'jasny'; colorScheme: 'dark' | 'light'; width: number }

for (const variant of [
  { mode: 'ciemny', colorScheme: 'dark', width: 1280 },
  { mode: 'ciemny', colorScheme: 'dark', width: 390 },
  { mode: 'jasny', colorScheme: 'light', width: 1280 },
  { mode: 'jasny', colorScheme: 'light', width: 390 },
] as Variant[]) {
  test.describe(`etykieta w fokusie (${variant.mode}, ${variant.width})`, () => {
    test.use({
      viewport: { width: variant.width, height: variant.width === 1280 ? 800 : 844 },
      colorScheme: variant.colorScheme,
    })

    test(`SC-E5-H8z-01 etykieta pola w fokusie nad tłem pola (${variant.mode}, ${variant.width})`, async ({
      page,
    }) => {
      await page.goto('/chats')
      // Asercje koloru czytają wartość PO zakończeniu przejścia CSS: przejścia wyłączone →
      // `getComputedStyle` zwraca od razu wartość końcową (flak pełnego biegu verify-full
      // 2026-10-11: odczyt w trakcie przejścia koloru dawał wartość pośrednią).
      await page.addStyleTag({ content: '*{transition:none!important}' })
      // .first(): przycisk nagłówka (PageContainer actions) jest w DOM zawsze; przy pustej
      // liście czatów EmptyState dokłada drugi o tej samej nazwie i klik po samej nazwie
      // przegrywa wyścig z renderem (strict mode violation, bieg 2 z WD_E2E_RETRIES=0).
      await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      // Zakres do etykiety „Nazwa”: okno tworzenia ma od V13-2 drugie pole („Bazy wiedzy
      // (opcjonalnie)”), więc w dialogu są dwie etykiety MUI — sprawdzamy tę od pola nazwy.
      const label = dialog.locator('label.MuiInputLabel-root', { hasText: /Nazwa/ })
      await expect(label).toBeVisible()
      // Pole puste w fokusie (autofokus) → etykieta uniesiona (shrink).
      await expect(label).toHaveAttribute('data-shrink', 'true')
      const field = dialog.getByRole('textbox', { name: /Nazwa/ })
      await expect(field).toBeFocused()

      // Asercja bezpośrednia: każdy punkt pola etykiety trafia w etykietę — nic (tło pola,
      // legend, obrys) nie jest nad nią.
      const covered = await label.evaluate((el) => {
        const rect = el.getBoundingClientRect()
        const fractions: [number, number][] = [
          [0.5, 0.5],
          [0.25, 0.5],
          [0.75, 0.5],
          [0.3, 0.25],
          [0.7, 0.25],
          [0.3, 0.75],
          [0.7, 0.75],
        ]
        const bad: string[] = []
        for (const [fx, fy] of fractions) {
          const x = rect.left + rect.width * fx
          const y = rect.top + rect.height * fy
          const top = document.elementFromPoint(x, y)
          if (top !== null && (top === el || el.contains(top))) continue
          bad.push(
            `(${Math.round(x)},${Math.round(y)}) → ${
              top === null ? 'null' : `${top.tagName.toLowerCase()}.${top.className}`
            }`,
          )
        }
        return bad
      })
      expect(covered, 'etykieta uniesiona leży w całości nad tłem pola (elementFromPoint)').toEqual(
        [],
      )

      // Etykieta shrink ma własne tło (łatka w kolorze powierzchni, patrz inputs.tsx) — bez niej
      // tekst leży wprost na obrysie fokusu i wypełnieniu pola (MAJOR M1, QA E5-H8d-1).
      const labelStyle = await label.evaluate((el) => {
        const style = getComputedStyle(el)
        return { background: style.backgroundColor, color: style.color }
      })
      expect(
        labelStyle.background,
        'etykieta uniesiona ma własne tło (łatka jak notch MUI)',
      ).not.toBe('rgba(0, 0, 0, 0)')

      // Kontrast tekstu etykiety z powierzchnią łatki ≥ 4.5:1 (AA; w dark primary.main —
      // brand[400] — ma 3,5:1 na papierze ciemnego motywu).
      const paper = await dialog.evaluate((el) => getComputedStyle(el).backgroundColor)
      const ratio = await label.evaluate((el, paperColor) => {
        const parse = (value: string): [number, number, number] =>
          value
            .replace(/^rgba?\(/, '')
            .replace(/\)$/, '')
            .split(',')
            .slice(0, 3)
            .map((part) => Number.parseInt(part.trim(), 10) / 255) as [number, number, number]
        const linear = (channel: number): number =>
          channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
        const luminance = ([r, g, b]: [number, number, number]): number =>
          0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
        const a = luminance(parse(getComputedStyle(el).color))
        const b = luminance(parse(paperColor as string))
        const [lighter, darker] = a > b ? [a, b] : [b, a]
        return (lighter + 0.05) / (darker + 0.05)
      }, paper)
      expect(
        ratio,
        `etykieta w fokusie czytelna: kontrast ≥ 4.5:1 (mierzone ${ratio.toFixed(2)}:1)`,
      ).toBeGreaterThanOrEqual(4.5)

      await expectNoLayoutDefects(page, `dialog „Utwórz czat”, pole w fokusie (${variant.mode})`)

      const shot = `../.task/shots/s20-etykieta-${variant.mode}-${variant.width}-focus.png`
      await page.screenshot({ path: shot })

      // Po wpisaniu nazwy etykieta zostaje uniesiona i czytelna (zrzut samokontrolny).
      await field.fill('E2E H8z czat')
      await expect(label).toHaveAttribute('data-shrink', 'true')
      await page.screenshot({
        path: `../.task/shots/s20-etykieta-${variant.mode}-${variant.width}-wpisane.png`,
      })
    })
  })
}

// SC-E5-H8z-02 (brief T4 — MAJOR K6 z QA E5-H8z-1): błąd walidacji dialogu „Nowy folder”
// („Utwórz” z pustą nazwą) ma być czytelny — komunikat (FormHelperText.Mui-error) i etykieta
// (InputLabel.Mui-error) ≥ 4.5:1 względem EFEKTYWNEGO tła. Tła liczone w przeglądarce z łańcucha
// przodków (tło pola / łatka etykiety / dialog paper), łącznie z ciemnym overlay Paper
// (elevation → linear-gradient rgba(255,255,255,α) na background.paper — bez niego dialog w dark
// to rgb(12,16,23), a realnie rysowany rgb(52,55,61), na którym defekt QA miał ~1,3:1).
// Dodatkowo (MINOR review T1): etykieta w polu z błędem w fokusie ma kolor BŁĘDU (nie brand).
for (const variant of [
  { mode: 'ciemny', colorScheme: 'dark', width: 1280 },
  { mode: 'ciemny', colorScheme: 'dark', width: 390 },
  { mode: 'jasny', colorScheme: 'light', width: 1280 },
  { mode: 'jasny', colorScheme: 'light', width: 390 },
] as Variant[]) {
  test.describe(`SC-E5-H8z-02 błąd walidacji czytelny, oba motywy (${variant.mode}, ${variant.width})`, () => {
    test.use({
      viewport: { width: variant.width, height: variant.width === 1280 ? 800 : 844 },
      colorScheme: variant.colorScheme,
    })

    test(`SC-E5-H8z-02 komunikat i etykieta błędu ≥ 4.5:1 (${variant.mode}, ${variant.width})`, async ({
      page,
    }) => {
      await page.goto('/files')
      // Jak wyżej (SC-E5-H8z-01): kontrast i kolor błędu czytane po zakończeniu przejścia —
      // wyłączenie przejść CSS zaraz po wejściu na stronę (flak verify-full 2026-10-11).
      await page.addStyleTag({ content: '*{transition:none!important}' })
      await page.getByTestId('files-add').click()
      await page.getByTestId('files-add-folder').click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      // Puste pole + „Utwórz” → walidacja: komunikat i stan błędu pola.
      await dialog.getByTestId('files-folder-create').click()
      const helper = dialog.locator('.MuiFormHelperText-root.Mui-error')
      await expect(helper).toHaveText('Podaj nazwę folderu.')
      const field = dialog.getByRole('textbox', { name: /Nazwa/ })
      const label = dialog.locator('label.MuiInputLabel-root')
      await expect(label).toHaveClass(/Mui-error/)
      // U11 (08 §4.4): klik przy pustym polu przenosi fokus na pierwsze błędne pole —
      // etykieta ZOSTAJE uniesiona nad polem (data-shrink="true"), nie opada na tło pola.
      await expect(label).toHaveAttribute('data-shrink', 'true')

      // Kontrast komunikatu i etykiety względem efektywnego tła. Tła rysują się od najdalszego
      // przodka (pod spodem) ku elementowi: pierwsza nieprzezroczysta warstwa przesłania
      // wszystko pod sobą, a każda dalsza (potomek, gradient overlay Paper) składa się na wierzch.
      // Etykieta jest uniesiona (U11), więc tłem pod jej dolną krawędzią jest siostrzany
      // MuiOutlinedInput (tło background.default) — tło pola bierzemy wprost.
      const { helperRatio, labelRatio } = await dialog.evaluate((dialogEl) => {
        const parseRgba = (value: string): [number, number, number, number] => {
          const m = /rgba?\(([^)]+)\)/.exec(value)
          const body = m?.[1]
          if (body === undefined) return [0, 0, 0, 0]
          const [r = 0, g = 0, b = 0, a] = body
            .split(/[,\s/]+/)
            .filter(Boolean)
            .map(Number)
          return [r, g, b, a ?? 1]
        }
        const linear = (channel: number): number =>
          channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
        const luminance = ([r, g, b]: [number, number, number]): number =>
          0.2126 * linear(r / 255) + 0.7152 * linear(g / 255) + 0.0722 * linear(b / 255)
        const over = (
          fg: [number, number, number, number],
          bg: [number, number, number, number],
        ): [number, number, number, number] => {
          const a = fg[3] + bg[3] * (1 - fg[3])
          if (a === 0) return [0, 0, 0, 0]
          return [
            (fg[0] * fg[3] + bg[0] * bg[3] * (1 - fg[3])) / a,
            (fg[1] * fg[3] + bg[1] * bg[3] * (1 - fg[3])) / a,
            (fg[2] * fg[3] + bg[2] * bg[3] * (1 - fg[3])) / a,
            a,
          ]
        }
        const effectiveBackground = (el: Element): [number, number, number, number] => {
          const chain: Element[] = []
          for (let node: Element | null = el; node !== null; node = node.parentElement) {
            chain.unshift(node)
          }
          // Stopnie gradientu to nie osobne warstwy: w danym pikselu gradient ma jeden kolor
          // (overlay Paper ma identyczne stopnie, więc średnia = wartość stopnia).
          const gradientColor = (image: string): [number, number, number, number] | null => {
            const stops = [...image.matchAll(/rgba?\([^)]+\)/g)].map((m) => parseRgba(m[0]))
            if (stops.length === 0) return null
            let sr = 0
            let sg = 0
            let sb = 0
            let sa = 0
            for (const stop of stops) {
              sr += stop[0]
              sg += stop[1]
              sb += stop[2]
              sa += stop[3]
            }
            const n = stops.length
            return [sr / n, sg / n, sb / n, sa / n]
          }
          const paints: [number, number, number, number][] = []
          for (const node of chain) {
            const style = getComputedStyle(node)
            const bgc = parseRgba(style.backgroundColor)
            if (bgc[3] > 0) paints.push(bgc)
            if (style.backgroundImage !== 'none') {
              const gradient = gradientColor(style.backgroundImage)
              if (gradient !== null && gradient[3] > 0) paints.push(gradient)
            }
          }
          const baseIndex = paints.findIndex((c) => c[3] >= 1)
          if (baseIndex === -1) return [255, 255, 255, 1]
          let acc = paints[baseIndex]
          if (acc === undefined) return [255, 255, 255, 1]
          for (let i = baseIndex + 1; i < paints.length; i++) {
            const layer = paints[i]
            if (layer !== undefined) acc = over(layer, acc)
          }
          return acc
        }
        const ratioOf = (fgColor: string, bg: [number, number, number, number]): number => {
          const fg = parseRgba(fgColor)
          const a = luminance([fg[0], fg[1], fg[2]])
          const b = luminance([bg[0], bg[1], bg[2]])
          const [lighter, darker] = a > b ? [a, b] : [b, a]
          return (lighter + 0.05) / (darker + 0.05)
        }
        const helperEl = dialogEl.querySelector('.MuiFormHelperText-root.Mui-error')
        const labelEl = dialogEl.querySelector('label.MuiInputLabel-root')
        const fieldEl = dialogEl.querySelector('.MuiOutlinedInput-root')
        if (helperEl === null || labelEl === null || fieldEl === null) {
          throw new Error('brak komunikatu, etykiety lub pola')
        }
        return {
          helperRatio: ratioOf(getComputedStyle(helperEl).color, effectiveBackground(helperEl)),
          labelRatio: ratioOf(
            getComputedStyle(labelEl).color,
            parseRgba(getComputedStyle(fieldEl).backgroundColor),
          ),
        }
      })
      expect(
        helperRatio,
        `komunikat błędu czytelny: kontrast ≥ 4.5:1 (mierzone ${helperRatio.toFixed(2)}:1)`,
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        labelRatio,
        `etykieta w stanie błędu czytelna: kontrast ≥ 4.5:1 (mierzone ${labelRatio.toFixed(2)}:1)`,
      ).toBeGreaterThanOrEqual(4.5)

      await page.screenshot({
        path: `../.task/shots/s20-blad-${variant.mode}-${variant.width}.png`,
      })

      // MINOR review T1: klik w pole z błędem → etykieta uniesiona, w fokusie, ale ma zostać
      // w kolorze BŁĘDU (selektor &.Mui-focused nie może przebić &.Mui-error).
      await field.click()
      await expect(label).toHaveAttribute('data-shrink', 'true')
      const labelFocus = await label.evaluate((el) => getComputedStyle(el).color)
      const helperColor = await helper.evaluate((el) => getComputedStyle(el).color)
      expect(
        labelFocus,
        'etykieta w błędzie w fokusie ma kolor błędu (nie kolor fokusu brand)',
      ).toBe(helperColor)
      await page.screenshot({
        path: `../.task/shots/s20-blad-${variant.mode}-${variant.width}-focus.png`,
      })

      await expectNoLayoutDefects(page, `dialog „Nowy folder”, błąd walidacji (${variant.mode})`)
    })
  })
}
