/**
 * Ramka strefy importu w ciemnym motywie (QA V12-z-2b MINOR-1): w jasnym zostaje `divider`,
 * w ciemnym schemacie styl ma nadpisanie w kolorze `text.secondary` (divider = alpha gray-700
 * 0,6 ginie na tle dialogu). Kontrast pary liczymy wg WCAG na wartościach z `colorSchemes`
 * (motyw pełen zmiennych CSS: jsdom nie rozwiąże reguł schematu w `getComputedStyle`).
 */
import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { colorSchemes, gray } from '../../theme/themePrimitives'
import { ImportDropzone } from './ImportDropzone'

afterEach(cleanup)

type Rgb = [number, number, number]

// hsl() → składowe 0–1 (algorytm CSS Color 3), jak w `theme/contrast.test.ts`.
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
  return [
    Math.min(1, Math.max(0, red + offset)),
    Math.min(1, Math.max(0, green + offset)),
    Math.min(1, Math.max(0, blue + offset)),
  ]
}

function relativeLuminance([r, g, b]: Rgb): number {
  const linear = (channel: number): number =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
}

function contrast(a: Rgb, b: Rgb): number {
  const lighter = Math.max(relativeLuminance(a), relativeLuminance(b))
  const darker = Math.min(relativeLuminance(a), relativeLuminance(b))
  return (lighter + 0.05) / (darker + 0.05)
}

/** Reguły CSS z arkuszy jsdom dotyczące klas elementu (styl sx żyje w `<style>` emotion). */
function cssFor(element: HTMLElement): string {
  const names = [...element.classList]
  const rules: string[] = []
  for (const sheet of Array.from(document.styleSheets)) {
    for (const rule of Array.from(sheet.cssRules)) {
      const text = rule.cssText
      if (names.some((name) => text.includes(name))) rules.push(text)
    }
  }
  return rules.join('\n')
}

describe('ImportDropzone — ramka w motywach (QA V12-z-2b MINOR-1)', () => {
  it('styl zawiera nadpisanie ciemnego schematu w kolorze text.secondary', async () => {
    // renderWithProviders montuje AppTheme (motyw pełen zmiennych CSS) — reguły sx idą
    // do arkusza jsdom z selektorem schematu, jak w przeglądarce.
    await renderWithProviders(
      <ImportDropzone onFiles={() => {}} emptyFile={false} errorText={null} />,
    )

    const css = cssFor(screen.getByTestId('kb-import-dropzone'))

    // Jasny: divider (bez zmian).
    expect(css).toMatch(/border-color:\s*var\(--template-palette-divider\)/)
    // Ciemny: selektor schematu z AppTheme (`colorSchemeSelector: 'data-mui-color-scheme'`).
    expect(css).toContain('[data-mui-color-scheme="dark"]')
    expect(css).toMatch(/border-color:\s*var\(--template-palette-text-secondary\)/)
  })

  it('kolor ciemnej ramki ma kontrast ≥ 3:1 z tłem dialogu (WCAG na non-text)', () => {
    const dark = colorSchemes.dark.palette
    // text.secondary schematu ciemnego = gray[400] (themePrimitives), tło dialogu = paper.
    expect(dark.text.secondary).toBe(gray[400])
    const border = hslToRgb(220, 20, 65)
    const paper = hslToRgb(220, 30, 7)
    expect(dark.background.paper).toBe('hsl(220, 30%, 7%)')
    expect(contrast(border, paper)).toBeGreaterThanOrEqual(3)
  })

  it('renderuje strefę z podpowiedzią i przyciskiem wyboru pliku (regresja sx na funkcji)', async () => {
    await renderWithProviders(
      <ImportDropzone onFiles={() => {}} emptyFile={false} errorText={null} />,
    )

    expect(screen.getByTestId('kb-import-dropzone')).toHaveTextContent(
      'Przeciągnij paczkę .wdkb.zip tutaj',
    )
    expect(screen.getByRole('button', { name: 'Wybierz plik' })).toBeInTheDocument()
  })
})
