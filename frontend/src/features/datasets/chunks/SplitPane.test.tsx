/**
 * Testy `SplitPane` (kontrakt WP E3-4a §SplitPane): dzielnik jest separatorem z zakresem 20–70,
 * strzałki przesuwają go o 5 punktów i zatrzymują się na granicach, a poniżej progu `md`
 * panele układają się w kolumnę bez dzielnika (bez `useMediaQuery` nie da się tego sprawdzić —
 * jsdom odpowiada na każde media query `false`).
 */

import { cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { SplitPane } from './SplitPane'

afterEach(cleanup)
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** Zapytanie progu `md` (`theme.breakpoints.down('md')`) — o to samo pyta komponent. */
const NARROW_QUERY = '(max-width:899.95px)'

/** Szerokość kontenera udawana w jsdom (bez niej `getBoundingClientRect` zwraca same zera). */
const CONTAINER_WIDTH = 1000

// jsdom nie implementuje przechwytywania wskaźnika ani pomiaru układu — atrapy jak przy
// `Element.scrollTo` w `ChatWorkspacePage.mobile.test.tsx`.
beforeEach(() => {
  Object.defineProperty(Element.prototype, 'setPointerCapture', {
    value: vi.fn(),
    configurable: true,
    writable: true,
  })
  Object.defineProperty(Element.prototype, 'releasePointerCapture', {
    value: vi.fn(),
    configurable: true,
    writable: true,
  })
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: CONTAINER_WIDTH,
    bottom: 100,
    width: CONTAINER_WIDTH,
    height: 100,
    toJSON: () => ({}),
  } as DOMRect)
})

/** Atrapa `matchMedia` jak w `ChatWorkspacePage.mobile.test.tsx` — jsdom nie mierzy okna. */
function stubMatchMedia(narrow: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === NARROW_QUERY && narrow,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })),
  )
}

function separator(): HTMLElement {
  return screen.getByTestId('chunks-split-separator')
}

async function renderPane(initialLeftPercent?: number): Promise<void> {
  await renderWithProviders(
    <SplitPane
      left={<p>Lewy panel</p>}
      right={<p>Prawy panel</p>}
      initialLeftPercent={initialLeftPercent}
    />,
  )
}

describe('SplitPane', () => {
  it('renderuje oba panele, a dzielnik ma atrybuty separatora i zakres 20–70', async () => {
    await renderPane()

    expect(screen.getByText('Lewy panel')).toBeInTheDocument()
    expect(screen.getByText('Prawy panel')).toBeInTheDocument()

    const bar = separator()
    expect(bar).toHaveAttribute('role', 'separator')
    expect(bar).toHaveAttribute('aria-orientation', 'vertical')
    expect(bar).toHaveAttribute('aria-valuenow', '40')
    expect(bar).toHaveAttribute('aria-valuemin', '20')
    expect(bar).toHaveAttribute('aria-valuemax', '70')
    expect(bar).toHaveAttribute('aria-label', 'Zmień szerokość paneli')
    expect(bar).toHaveAttribute('tabindex', '0')
  })

  it('szerokość startową bierze z `initialLeftPercent`', async () => {
    await renderPane(55)

    expect(separator()).toHaveAttribute('aria-valuenow', '55')
  })

  it('strzałki przesuwają dzielnik o 5 punktów', async () => {
    await renderPane()

    fireEvent.keyDown(separator(), { key: 'ArrowRight' })
    expect(separator()).toHaveAttribute('aria-valuenow', '45')

    fireEvent.keyDown(separator(), { key: 'ArrowLeft' })
    fireEvent.keyDown(separator(), { key: 'ArrowLeft' })
    expect(separator()).toHaveAttribute('aria-valuenow', '35')

    // Pozostałe klawisze nie zmieniają szerokości.
    fireEvent.keyDown(separator(), { key: 'ArrowUp' })
    expect(separator()).toHaveAttribute('aria-valuenow', '35')
  })

  it('zatrzymuje się na granicach 70 i 20', async () => {
    await renderPane()

    for (let step = 0; step < 10; step += 1) fireEvent.keyDown(separator(), { key: 'ArrowRight' })
    expect(separator()).toHaveAttribute('aria-valuenow', '70')

    for (let step = 0; step < 20; step += 1) fireEvent.keyDown(separator(), { key: 'ArrowLeft' })
    expect(separator()).toHaveAttribute('aria-valuenow', '20')
  })

  it('szerokość startowa spoza zakresu jest przycinana do granicy', async () => {
    await renderPane(90)

    expect(separator()).toHaveAttribute('aria-valuenow', '70')
  })

  it('przeciąganie ustawia szerokość z pozycji wskaźnika, a `pointercancel` je kończy', async () => {
    await renderPane()

    const bar = separator()
    fireEvent.pointerDown(bar, { pointerId: 1, clientX: 400 })
    expect(bar).toHaveAttribute('aria-valuenow', '40')

    fireEvent.pointerMove(bar, { pointerId: 1, clientX: 700 })
    expect(bar).toHaveAttribute('aria-valuenow', '70')

    // Po przerwaniu gestu ruch nad dzielnikiem nie zmienia już szerokości.
    fireEvent.pointerCancel(bar, { pointerId: 1 })
    fireEvent.pointerMove(bar, { pointerId: 1, clientX: 300 })
    expect(bar).toHaveAttribute('aria-valuenow', '70')

    // Puszczenie wskaźnika też kończy przeciąganie (ruch nad dzielnikiem jest ignorowany).
    fireEvent.pointerDown(bar, { pointerId: 2, clientX: 400 })
    fireEvent.pointerMove(bar, { pointerId: 2, clientX: 400 })
    expect(bar).toHaveAttribute('aria-valuenow', '40')

    fireEvent.pointerUp(bar, { pointerId: 2 })
    fireEvent.pointerMove(bar, { pointerId: 2, clientX: 300 })
    expect(bar).toHaveAttribute('aria-valuenow', '40')
  })

  it('poniżej progu `md` nie ma dzielnika', async () => {
    stubMatchMedia(true)

    await renderPane()

    expect(screen.queryByTestId('chunks-split-separator')).not.toBeInTheDocument()
    expect(screen.getByText('Lewy panel')).toBeInTheDocument()
    expect(screen.getByText('Prawy panel')).toBeInTheDocument()
  })
})
