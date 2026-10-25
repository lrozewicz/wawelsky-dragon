import { createTheme } from '@mui/material/styles'
import { describe, expect, it } from 'vitest'

import { containedDisabledColors, focusedLabelColor } from './customizations/inputs'
import { parsingStatusColor, type ParsingStatus } from './parsingStatus'
import { colorSchemes, steel } from './themePrimitives'

// Minimalny kontrast tekstu wg WCAG 2.x (level AA).
const MIN_CONTRAST = 4.5

type Rgb = [number, number, number]

const clamp = (channel: number): number => Math.min(1, Math.max(0, channel))

// hsl() → składowe 0–1 (algorytm CSS Color 3).
function hslToRgb(hue: number, saturation: number, lightness: number): Rgb {
  const s = saturation / 100
  const l = lightness / 100
  const chroma = (1 - Math.abs(2 * l - 1)) * s
  const sector = ((((hue % 360) + 360) % 360) / 60) % 6
  const x = chroma * (1 - Math.abs((sector % 2) - 1))
  const [red, green, blue] =
    sector < 1
      ? [chroma, x, 0]
      : sector < 2
        ? [x, chroma, 0]
        : sector < 3
          ? [0, chroma, x]
          : sector < 4
            ? [0, x, chroma]
            : sector < 5
              ? [x, 0, chroma]
              : [chroma, 0, x]
  const offset = l - chroma / 2
  return [clamp(red + offset), clamp(green + offset), clamp(blue + offset)]
}

// Obsługuje hsl()/hsla()/rgb()/#hex. Kanał alfa jest ignorowany — pary z alfą
// (divider, action) nie są w tym teście sprawdzane.
function parseColor(value: string): Rgb {
  const text = value.trim().toLowerCase()

  if (text.startsWith('#')) {
    const digits = text.slice(1)
    // #rgb i #rgba rozwija do postaci pełnej; 8 znaków to #rrggbbaa (alfa ignorowana).
    const expanded =
      digits.length <= 4
        ? digits
            .split('')
            .map((digit) => digit + digit)
            .join('')
        : digits
    if (expanded.length !== 6 && expanded.length !== 8) {
      throw new Error(`Nieobsługiwany format koloru: ${value}`)
    }
    return [
      Number.parseInt(expanded.slice(0, 2), 16) / 255,
      Number.parseInt(expanded.slice(2, 4), 16) / 255,
      Number.parseInt(expanded.slice(4, 6), 16) / 255,
    ]
  }

  const match = /^(hsl|rgb)a?\(([^)]+)\)$/.exec(text)
  if (!match) throw new Error(`Nieobsługiwany format koloru: ${value}`)
  const [, fn = '', body = ''] = match
  const parts = body.split(/[\s,/]+/).filter((part) => part !== '')

  if (fn === 'hsl') {
    const [hue = '0', saturation = '0', lightness = '0'] = parts
    return hslToRgb(
      Number.parseFloat(hue),
      Number.parseFloat(saturation),
      Number.parseFloat(lightness),
    )
  }

  const [red = '0', green = '0', blue = '0'] = parts
  return [
    Number.parseFloat(red) / 255,
    Number.parseFloat(green) / 255,
    Number.parseFloat(blue) / 255,
  ]
}

function relativeLuminance([red, green, blue]: Rgb): number {
  const linear = (channel: number): number =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)
}

function contrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(parseColor(foreground))
  const b = relativeLuminance(parseColor(background))
  const [lighter, darker] = a > b ? [a, b] : [b, a]
  return (lighter + 0.05) / (darker + 0.05)
}

describe('contrastRatio', () => {
  it('zwraca 21 dla czerni na bieli', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
  })

  it('zwraca 1 dla identycznych kolorów', () => {
    expect(contrastRatio('#777777', '#777777')).toBe(1)
  })

  it('parsuje hsl(), hsla(), rgb() i #hex na ten sam kolor', () => {
    const red = contrastRatio('#ff0000', '#ffffff')
    expect(contrastRatio('hsl(0, 100%, 50%)', 'rgb(255, 255, 255)')).toBeCloseTo(red, 10)
    expect(contrastRatio('hsla(0, 100%, 50%, 0.5)', '#ffffff')).toBeCloseTo(red, 10)
    expect(contrastRatio('#ff0000ff', '#ffffff')).toBeCloseTo(red, 10)
    expect(() => contrastRatio('nie-kolor', '#ffffff')).toThrow()
  })
})

const MODES = ['light', 'dark'] as const

type Mode = (typeof MODES)[number]

// Pary (etykieta, kolor tekstu, tło) czytane wprost z tokenów schematu kolorów.
function themePairs(mode: Mode): [string, string, string][] {
  const { palette } = colorSchemes[mode]
  return [
    ['text.primary / background.default', palette.text.primary, palette.background.default],
    ['text.primary / background.paper', palette.text.primary, palette.background.paper],
    ['text.secondary / background.default', palette.text.secondary, palette.background.default],
    ['text.secondary / background.paper', palette.text.secondary, palette.background.paper],
    ['primary.contrastText / primary.main', palette.primary.contrastText, palette.primary.main],
  ]
}

const STATUSES: ParsingStatus[] = ['pending', 'running', 'cancel', 'done', 'fail']

for (const mode of MODES) {
  describe(`kontrast tokenów motywu — tryb ${mode}`, () => {
    for (const [label, foreground, background] of themePairs(mode)) {
      it(`${label} ≥ ${MIN_CONTRAST}:1`, () => {
        expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(MIN_CONTRAST)
      })
    }
  })
}

// Nakłada półprzezroczysty kolor na nieprzezroczyste tło (mieszanie kanałów w sRGB, jak CSS).
function compositeOver(foreground: string, opacity: number, background: string): string {
  const [fr, fg, fb] = parseColor(foreground)
  const [br, bg, bb] = parseColor(background)
  const channel = (front: number, back: number): number =>
    Math.round((front * opacity + back * (1 - opacity)) * 255)
  return `rgb(${channel(fr, br)}, ${channel(fg, bg)}, ${channel(fb, bb)})`
}

// Aktywny segment Czat/Wyszukiwanie (`ToggleButtonGroup`): tekst z `inputs.tsx`, tło to domyślne
// MUI `alpha(text.primary, action.selectedOpacity)` nałożone na tło strony (`background.default`,
// Home rysuje segment wprost na `PageContainer`). W light motywowa reguła grupy (`steel[600]`)
// przegrywa kaskadę z domyślną MUI (`&.Mui-selected` → `text.primary`), dlatego bierzemy kolor
// efektywny; w dark wygrywa reguła przycisku z `inputs.tsx` (`steel[300]` — DEC-305).
const SEGMENT_TEXT: Record<Mode, string> = {
  light: colorSchemes.light.palette.text.primary,
  dark: steel[300],
}

// Domyślne `action.selectedOpacity` MUI (0.08 light / 0.16 dark) — nie nadpisane w motywie.
function activeSegmentBackground(mode: Mode): string {
  const { palette } = colorSchemes[mode]
  const { selectedOpacity } = createTheme({ palette: { mode } }).palette.action
  return compositeOver(palette.text.primary, selectedOpacity, palette.background.default)
}

describe('kontrast aktywnego segmentu Czat/Wyszukiwanie', () => {
  for (const mode of MODES) {
    it(`tekst na tle segmentu — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      expect(
        contrastRatio(SEGMENT_TEXT[mode], activeSegmentBackground(mode)),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })
  }
})

// WCAG 1.4.3 wyłącza stan disabled z progu AA; przyjmujemy 3:1 (jak dla tekstu dużego), bo
// etykieta przycisku musi pozostać czytelna. Pary bierzemy wprost z motywu
// (`customizations/inputs.tsx` → `containedDisabledColors`), więc zmiana kolorów tam łamie test.
// Regresja D-maj2 (QA E3-H4): przycisk „Zapisz” w dark był jasną pigułką z tekstem 30% bieli.
const MIN_DISABLED_CONTRAST = 3

describe('kontrast przycisku contained (primary) w stanie disabled', () => {
  for (const mode of MODES) {
    it(`tekst na tle przycisku — tryb ${mode} ≥ ${MIN_DISABLED_CONTRAST}:1`, () => {
      const { color, backgroundColor } = containedDisabledColors[mode]
      expect(contrastRatio(color, backgroundColor)).toBeGreaterThanOrEqual(MIN_DISABLED_CONTRAST)
    })
  }
})

// Etykieta pola outlined w fokusie (`customizations/inputs.tsx` → `focusedLabelColor`):
// uniesiona (shrink) etykieta ma łatkę w kolorze `background.paper`, więc para to tekst vs
// paper; etykieta nieuniesiona (pole w fokusie bez shrink) leży na tle pola — tekst vs
// `background.default`. DEC-305: akcent fokusu = secondary (steel), nie czerwień marki —
// fokus nie może wyglądać jak błąd (SC-E5-H9-01). Light steel[600] (6.8:1 na paper), dark
// steel[300] (9.4:1 na paper).
const MIN_CONTROL_CONTRAST = 3

describe('kontrast etykiety pola w fokusie (secondary)', () => {
  for (const mode of MODES) {
    it(`kolor fokusu etykiety / background.paper — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      expect(
        contrastRatio(focusedLabelColor[mode], colorSchemes[mode].palette.background.paper),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })

    it(`kolor fokusu etykiety / background.default — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      expect(
        contrastRatio(focusedLabelColor[mode], colorSchemes[mode].palette.background.default),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })
  }
})

// Ramka pola w fokusie i włączone kontrolki (secondary.main, `inputs.tsx`/`controls.tsx`):
// WCAG 1.4.11 (non-text) — element interfejsu ≥ 3:1 względem sąsiadującego tła. Tła: tło pola
// (`background.default`) i powierzchnia (`background.paper`), oba motywy (DEC-305).
describe('kontrast akcentu kontrolek (secondary.main)', () => {
  for (const mode of MODES) {
    const { palette } = colorSchemes[mode]

    it(`secondary.main / background.default — tryb ${mode} ≥ ${MIN_CONTROL_CONTRAST}:1`, () => {
      expect(
        contrastRatio(palette.secondary.main, palette.background.default),
      ).toBeGreaterThanOrEqual(MIN_CONTROL_CONTRAST)
    })

    it(`secondary.main / background.paper — tryb ${mode} ≥ ${MIN_CONTROL_CONTRAST}:1`, () => {
      expect(
        contrastRatio(palette.secondary.main, palette.background.paper),
      ).toBeGreaterThanOrEqual(MIN_CONTROL_CONTRAST)
    })
  }
})

// Przycisk `contained color="error"` (np. „Usuń” w dialogu usuwania użytkownika): tekst
// `error.contrastText` na tle `error.main`. W dark error.main = red[200] (jasny), więc MUI
// wylicza ciemny tekst — para mierzona wprost z motywu (SC-E5-H9-01, wariant).
describe('kontrast przycisku contained (error)', () => {
  for (const mode of MODES) {
    it(`error.contrastText / error.main — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      const { error } = createTheme({ palette: { mode, ...colorSchemes[mode].palette } }).palette
      expect(contrastRatio(error.contrastText, error.main)).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })
  }
})

// Tekst błędu walidacji (`FormHelperText.Mui-error`, `InputLabel.Mui-error`) czyta MUI
// z `palette.error.main`. Tła, na których leży (MAJOR K6, QA E5-H8z-1: komunikat
// „Podaj nazwę folderu." miał w dark ~1,3:1, etykieta ~2,15:1):
//   - `background.paper` — komunikat na powierzchni dialogu i uniesiona etykieta na łatce,
//   - `background.default` — tło pola (`MuiOutlinedInput` root), na którym leży etykieta
//     nieuniesiona (pole w błędzie bez fokusu).
describe('kontrast koloru błędu walidacji', () => {
  for (const mode of MODES) {
    const errorMain = colorSchemes[mode].palette.error.main
    it(`error.main / background.paper — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      expect(
        contrastRatio(errorMain, colorSchemes[mode].palette.background.paper),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })

    it(`error.main / tło pola (background.default) — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      expect(
        contrastRatio(errorMain, colorSchemes[mode].palette.background.default),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })
  }
})

describe('kontrast kolorów statusów parsowania', () => {
  for (const status of STATUSES) {
    it(`${status} — light na background.paper`, () => {
      expect(
        contrastRatio(
          parsingStatusColor[status].light,
          colorSchemes.light.palette.background.paper,
        ),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })

    it(`${status} — dark na background.paper`, () => {
      expect(
        contrastRatio(parsingStatusColor[status].dark, colorSchemes.dark.palette.background.paper),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })
  }
})

// D3 (QA E5-H9-1): zielony znacznik „Przesłano” w dialogach uploadu (`doneMarkerColorSx`)
// nie może iść za `success.main` — green[400] w jasnym motywie miał ~2.4:1 na paperze. Token
// `done` z `parsingStatusColor` daje pary w obu trybach; test dowiązuje regułę do znacznika.
describe('kontrast zielonego znacznika uploadu („Przesłano”)', () => {
  for (const mode of ['light', 'dark'] as const) {
    it(`done / background.paper — tryb ${mode} ≥ ${MIN_CONTRAST}:1`, () => {
      expect(
        contrastRatio(parsingStatusColor.done[mode], colorSchemes[mode].palette.background.paper),
      ).toBeGreaterThanOrEqual(MIN_CONTRAST)
    })
  }
})
