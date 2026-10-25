// Test regresji D-maj1 (QA E3-H4). Motyw nadawał polu `OutlinedInput` stałą wysokość także przy
// `multiline`; `InputBase` centruje zawartość (`display: inline-flex; align-items: center`), więc
// tekstarea wychodziła poza obramowanie, a zwinięta etykieta (`translate(14px, -9px)`) nachodziła
// na pierwszy wiersz tekstu. jsdom nie liczy layoutu — sprawdzamy samą deklarację `height`
// korzenia: w polu jednoliniowym nadal stała z motywu, w `multiline` nieustawiona.
import type { Theme } from '@mui/material/styles'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import { colorSchemes } from '../themePrimitives'
import { inputsCustomizations } from './inputs'
import { initI18n } from '../../i18n'
import AppTheme from '../AppTheme'

beforeAll(async () => {
  await initI18n('pl')
})

afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-mui-color-scheme')
})

function outlinedRoot(testId: string): HTMLElement {
  const input = screen.getByTestId(testId)
  const root = input.closest('.MuiOutlinedInput-root')
  if (!(root instanceof HTMLElement)) throw new Error('brak korzenia MuiOutlinedInput')
  return root
}

describe('MuiOutlinedInput w motywie', () => {
  it('nie wymusza stałej wysokości na polu multiline, a jednoliniowe zostawia z motywu', () => {
    render(
      <AppTheme>
        <TextField
          multiline
          label="Pytanie"
          slotProps={{ htmlInput: { 'data-testid': 'multi' } }}
        />
        <TextField label="Nazwa" slotProps={{ htmlInput: { 'data-testid': 'single' } }} />
      </AppTheme>,
    )

    // jsdom podstawia `height: auto` za brak reguły i rozwiązuje `2.5rem` (size medium) na 40px.
    expect(getComputedStyle(outlinedRoot('multi')).height).toBe('auto')
    expect(getComputedStyle(outlinedRoot('single')).height).toBe('40px')
  })
})

// Test regresji D-maj2 (QA E3-H4): MUI w stanie disabled zeruje tylko `backgroundColor`
// i `boxShadow`, więc gradient motywu malował się pod tekstem `action.disabled` i przycisk
// był jasną pigułką bez czytelnej etykiety. Motyw musi wprost nadpisać tło, kolor i gradient.
describe('MuiButton contained (primary) disabled', () => {
  it('niesie kolory z motywu i nie zostawia gradientu', () => {
    render(
      <AppTheme>
        <Button variant="contained" color="primary" disabled>
          Zapisz
        </Button>
      </AppTheme>,
    )

    const style = getComputedStyle(screen.getByRole('button', { name: 'Zapisz' }))
    // Wartości `containedDisabledColors.light` po rozwiązaniu hsl → rgb (jsdom): gray[500]/gray[200].
    expect(style.color).toBe('rgb(86, 100, 129)')
    expect(style.backgroundColor).toBe('rgb(218, 222, 231)')
    expect(style.backgroundImage).toBe('none')
  })

  it('w ciemnym motywie daje jasny tekst na ciemnym tle, bez jasnego gradientu', () => {
    document.documentElement.setAttribute('data-mui-color-scheme', 'dark')
    render(
      <AppTheme>
        <Button variant="contained" color="primary" disabled>
          Zapisz
        </Button>
      </AppTheme>,
    )

    const style = getComputedStyle(screen.getByRole('button', { name: 'Zapisz' }))
    // Wartości `containedDisabledColors.dark` (gray[400]/gray[700]) — regresja D-maj2: na tych
    // kolorach malował się jeszcze jasny gradient motywu i tekst `action.disabled` ginął.
    expect(style.color).toBe('rgb(148, 160, 184)')
    expect(style.backgroundColor).toBe('rgb(51, 60, 77)')
    expect(style.backgroundImage).toBe('none')
  })
})

// Test regresji D1 (QA E5-H9-1): korzeń `MuiOutlinedInput` maluje ramkę z `divider` (customizacja
// DEC-305, notchedOutline wyłączony), więc po T2 standardowa reguła MUI dla notchedOutline nie
// robiła nic i ramka pola z błędem zostawała szara (divider) zamiast `error.main`. jsdom nie
// rozwiązuje `var()` z CSS-vars, więc asercja idzie po tokenach: reguły motywu muszą wskazywać
// `error.main` danego trybu (renderowanie sprawdza e2e s24-h9-a `isReddish` w prawdziwej
// przeglądarce). Etykieta (`MuiFormLabel` wyżej) i helperText mają kolor błędu z motywu/MUI.
describe('MuiOutlinedInput — ramka błędu (D1)', () => {
  const rootStyles = (mode: 'light' | 'dark'): Record<string, unknown> => {
    const styleFn = inputsCustomizations.MuiOutlinedInput?.styleOverrides?.root as (args: {
      theme: Theme
    }) => Record<string, unknown>
    if (typeof styleFn !== 'function') throw new Error('root nie jest callbackiem motywu')
    return styleFn({
      theme: {
        vars: {
          palette: colorSchemes[mode].palette,
          shape: { borderRadius: 8 },
        },
        applyStyles: (scheme: string, styles: Record<string, unknown>) => ({
          [`[data-mui-color-scheme="${scheme}"] &`]: styles,
        }),
      } as unknown as Theme,
    }) as Record<string, unknown>
  }

  for (const mode of ['light', 'dark'] as const) {
    it(`błąd bije hover i fokus — borderColor = error.main (${mode})`, () => {
      const styles = rootStyles(mode)
      const errorBorder = { borderColor: colorSchemes[mode].palette.error.main }
      expect(styles['&.Mui-error']).toEqual(errorBorder)
      expect(styles['&.Mui-error:hover']).toEqual(errorBorder)
      expect(styles['&.Mui-error.Mui-focused']).toEqual(errorBorder)

      const darkKey = Object.keys(styles).find((key) =>
        key.includes('[data-mui-color-scheme="dark"]'),
      )
      if (darkKey === undefined) throw new Error('brak bloku dark w regułach korzenia')
      const darkStyles = styles[darkKey] as Record<string, unknown>
      expect(darkStyles['&.Mui-error']).toEqual(errorBorder)
      expect(darkStyles['&.Mui-error:hover']).toEqual(errorBorder)
      expect(darkStyles['&.Mui-error.Mui-focused']).toEqual(errorBorder)
    })
  }
})
