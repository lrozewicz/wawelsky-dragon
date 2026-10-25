/**
 * Testy ScrollShadowBox (K5 WP E5-H9): stan cieni z wymiarów przewijania, `scrollTargetSelector`
 * (element przewijający `DataGrid`), sticky kolumny i nagłówki z `title`. jsdom nie liczy
 * układu — wymiary przewijania (`scrollLeft`/`scrollWidth`/`clientWidth`/`offsetWidth`)
 * podstawiane są atrapami, a zdarzenie `scroll` wywoływane ręcznie.
 */

import { act, cleanup, render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { createTheme, ThemeProvider } from '@mui/material/styles'
import type { GridColDef } from '@mui/x-data-grid'

import { colorSchemes } from '../theme/themePrimitives'

import { GridHeaderTitle, ScrollShadowBox, withEllipsisHeaders } from './ScrollShadowBox'

afterEach(cleanup)

const light = createTheme()
// Motyw z CSS variables (jak AppTheme): tła sticky idą z `theme.vars`, a provider z
// `defaultMode="dark"` rozwiązuje schemat cienia (`useColorScheme`).
const dark = createTheme({
  cssVariables: { colorSchemeSelector: 'data-mui-color-scheme', cssVarPrefix: 'template' },
  colorSchemes: { light: true, dark: true },
})

/** Kontrast WCAG krawędzi cienia (rgba nad tłem `hsl(H, S%, L%)`) — miara widoczności (D2). */
function edgeContrast(background: string, image: string): number {
  const linear = (channel: number): number =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  const luminance = ([r, g, b]: [number, number, number]): number =>
    0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
  const edgeChannels = (image.match(/[\d.]+/g) ?? []).map(Number)
  const [edgeRed = 0, edgeGreen = 0, edgeBlue = 0] = edgeChannels
  const alpha = edgeChannels[3] ?? 1
  const [hue = 0, sat = 0, light = 0] = (background.match(/[\d.]+/g) ?? []).map(Number)
  const chroma = (1 - Math.abs(2 * (light / 100) - 1)) * (sat / 100)
  const second = chroma * (1 - Math.abs(((hue / 60) % 2) - 1))
  // RGB sektora 60° (hsl → rgb); indeks floor(h/60) % 6.
  const sectors: number[][] = [
    [chroma, second, 0],
    [second, chroma, 0],
    [0, chroma, second],
    [0, second, chroma],
    [second, 0, chroma],
    [chroma, 0, second],
  ]
  const mix = light / 100 - chroma / 2
  const sectorRow = sectors[Math.floor(hue / 60) % 6] as [number, number, number]
  const paper: [number, number, number] = [
    sectorRow[0] + mix,
    sectorRow[1] + mix,
    sectorRow[2] + mix,
  ]
  const edge: [number, number, number] = [
    (edgeRed / 255) * alpha + paper[0] * (1 - alpha),
    (edgeGreen / 255) * alpha + paper[1] * (1 - alpha),
    (edgeBlue / 255) * alpha + paper[2] * (1 - alpha),
  ]
  const edgeLum = luminance(edge)
  const paperLum = luminance(paper)
  const lighter = Math.max(edgeLum, paperLum)
  const darker = Math.min(edgeLum, paperLum)
  return (lighter + 0.05) / (darker + 0.05)
}

function renderBox(ui: ReactElement, mode: 'light' | 'dark' = 'light'): ReturnType<typeof render> {
  return mode === 'dark'
    ? render(
        <ThemeProvider theme={dark} defaultMode="dark">
          {ui}
        </ThemeProvider>,
      )
    : render(<ThemeProvider theme={light}>{ui}</ThemeProvider>)
}

/** Podmienia wymiar przewijania elementu (jsdom nie implementuje geometrii układu). */
function mockMetric(element: HTMLElement, name: string, value: number): void {
  Object.defineProperty(element, name, { value, configurable: true })
}

describe('ScrollShadowBox', () => {
  it('renderuje treść; bez przewinięcia i bez nadmiaru nie ma cieni', () => {
    const { container } = renderBox(
      <ScrollShadowBox sx={{ minWidth: 80 }}>
        <div data-testid="content">treść</div>
      </ScrollShadowBox>,
    )
    expect(screen.getByTestId('content')).toBeInTheDocument()
    expect(screen.queryByTestId('scroll-shadow-left')).not.toBeInTheDocument()
    expect(screen.queryByTestId('scroll-shadow-right')).not.toBeInTheDocument()
    // sx obiektowy (gałąź „nie tablica”) dociera do kontenera.
    expect(container.firstElementChild).toHaveStyle({ minWidth: '80px' })
  })

  it('treść szersza od kontenera: prawy cień; po przewinięciu do końca: tylko lewy', () => {
    const { container } = renderBox(
      <ScrollShadowBox>
        <div>treść</div>
      </ScrollShadowBox>,
    )
    const box = container.firstElementChild as HTMLElement
    // Element przewijający to sam kontener (bez `scrollTargetSelector`).
    mockMetric(box, 'scrollWidth', 200)
    mockMetric(box, 'clientWidth', 100)
    mockMetric(box, 'scrollLeft', 0)
    act(() => {
      box.dispatchEvent(new Event('scroll'))
    })
    expect(screen.getByTestId('scroll-shadow-right')).toBeVisible()
    expect(screen.queryByTestId('scroll-shadow-left')).not.toBeInTheDocument()

    mockMetric(box, 'scrollLeft', 100)
    act(() => {
      box.dispatchEvent(new Event('scroll'))
    })
    expect(screen.getByTestId('scroll-shadow-left')).toBeVisible()
    expect(screen.queryByTestId('scroll-shadow-right')).not.toBeInTheDocument()
  })

  it('obserwuje element wskazany selektorem, a nie kontener', () => {
    const { container } = renderBox(
      <ScrollShadowBox scrollTargetSelector=".inner">
        <div className="inner">siatka</div>
      </ScrollShadowBox>,
    )
    const inner = container.querySelector('.inner') as HTMLElement
    mockMetric(inner, 'scrollWidth', 300)
    mockMetric(inner, 'clientWidth', 150)
    mockMetric(inner, 'scrollLeft', 0)
    act(() => {
      inner.dispatchEvent(new Event('scroll'))
    })
    expect(screen.getByTestId('scroll-shadow-right')).toBeVisible()
    // sx tablicowy (gałąź „tablica”) — bez błędu renderu.
    renderBox(
      <ScrollShadowBox sx={[{ minWidth: 80 }]}>
        <div />
      </ScrollShadowBox>,
    )
  })

  it('bez trafienia selektora nie renderuje cieni', () => {
    renderBox(
      <ScrollShadowBox scrollTargetSelector=".brak">
        <div>treść</div>
      </ScrollShadowBox>,
    )
    expect(screen.queryByTestId('scroll-shadow-right')).not.toBeInTheDocument()
    expect(screen.queryByTestId('scroll-shadow-left')).not.toBeInTheDocument()
  })

  it('sticky kolumny: pola z listy przyklejone, pozostałe nie; cień lewy za nimi', () => {
    const { container } = renderBox(
      <ScrollShadowBox stickyFields={['__check__', 'name']}>
        <div className="MuiDataGrid-main">
          <div className="MuiDataGrid-columnHeaders">
            <div role="row">
              <div
                role="columnheader"
                className="MuiDataGrid-columnHeader MuiDataGrid-columnHeaderCheckbox"
                data-field="__check__"
                data-testid="h1"
              >
                A
                <div className="MuiDataGrid-columnSeparator" data-testid="sep1" />
              </div>
              <div
                role="columnheader"
                className="MuiDataGrid-columnHeader"
                data-field="name"
                data-testid="h2"
              >
                B
              </div>
              <div
                role="columnheader"
                className="MuiDataGrid-columnHeader"
                data-field="size"
                data-testid="h3"
              >
                C
              </div>
            </div>
          </div>
          <div className="MuiDataGrid-row">
            <div className="MuiDataGrid-cellOffsetLeft" />
            <div className="MuiDataGrid-cell" data-field="__check__" data-testid="c1">
              a
            </div>
            <div className="MuiDataGrid-cell" data-field="name" data-testid="c2">
              b
            </div>
            <div className="MuiDataGrid-cell" data-field="size" data-testid="c3">
              c
            </div>
          </div>
        </div>
      </ScrollShadowBox>,
    )
    expect(screen.getByTestId('h1')).toHaveStyle({ position: 'sticky', left: '0px' })
    // Tło sticky: nieprzezroczysty `background.paper` (K5) — inaczej przewijana treść
    // prześwitywała pod przyklejoną pierwszą kolumną.
    expect(screen.getByTestId('h1')).toHaveStyle({ backgroundColor: 'rgb(255, 255, 255)' })
    expect(screen.getByTestId('h2')).toHaveStyle({ backgroundColor: 'rgb(255, 255, 255)' })
    expect(screen.getByTestId('c1')).toHaveStyle({ backgroundColor: 'rgb(255, 255, 255)' })
    expect(screen.getByTestId('c2')).toHaveStyle({ backgroundColor: 'rgb(255, 255, 255)' })
    // Nagłówek checkboxa bez tytułu — separator nie może wystawać poza kolumnę (SC-E5-H9-07).
    expect(screen.getByTestId('sep1')).toHaveStyle({ display: 'none' })
    expect(screen.getByTestId('h2')).toHaveStyle({ position: 'sticky' })
    expect(screen.getByTestId('h3')).not.toHaveStyle({ position: 'sticky' })
    expect(screen.getByTestId('c1')).toHaveStyle({ position: 'sticky', left: '0px' })
    expect(screen.getByTestId('c2')).toHaveStyle({ position: 'sticky' })
    expect(screen.getByTestId('c3')).not.toHaveStyle({ position: 'sticky' })

    // Cień lewy zaczyna się za przyklejonymi kolumnami: 64 + 48 (pierwsze elementy z polami);
    // elementy-placeholdery bez `data-field` (offset pinowania) nie wliczają się.
    const box = container.firstElementChild as HTMLElement
    mockMetric(screen.getByTestId('h1'), 'offsetWidth', 64)
    mockMetric(screen.getByTestId('h2'), 'offsetWidth', 48)
    mockMetric(box, 'scrollWidth', 300)
    mockMetric(box, 'clientWidth', 100)
    mockMetric(box, 'scrollLeft', 20)
    act(() => {
      box.dispatchEvent(new Event('scroll'))
    })
    expect(screen.getByTestId('scroll-shadow-left')).toHaveStyle({ left: '112px' })
    expect(screen.getByTestId('scroll-shadow-right')).toBeVisible()
  })

  it('bez wierszy szerokość sticky liczy z nagłówków; ciemny motyw ma własną gęstość cienia', () => {
    const { container } = renderBox(
      <ScrollShadowBox stickyFields={['a', 'b', 'brak']}>
        <div className="MuiDataGrid-main">
          <div className="MuiDataGrid-columnHeaders">
            <div role="row">
              <div role="columnheader" className="MuiDataGrid-columnHeader" data-field="a">
                A
              </div>
              <div role="columnheader" className="MuiDataGrid-columnHeader" data-field="b">
                B
              </div>
            </div>
          </div>
        </div>
      </ScrollShadowBox>,
      'dark',
    )
    const box = container.firstElementChild as HTMLElement
    const headers = box.querySelectorAll<HTMLElement>('[role="columnheader"]')
    mockMetric(headers[0] as HTMLElement, 'offsetWidth', 40)
    mockMetric(headers[1] as HTMLElement, 'offsetWidth', 24)
    mockMetric(box, 'scrollWidth', 200)
    mockMetric(box, 'clientWidth', 100)
    mockMetric(box, 'scrollLeft', 10)
    act(() => {
      box.dispatchEvent(new Event('scroll'))
    })
    // Pole bez nagłówka („brak”) wnosi 0; tła sticky z CSS variables motywu (`theme.vars`).
    expect(screen.getByTestId('scroll-shadow-left')).toHaveStyle({ left: '64px' })
    // D2 (QA E5-H9-2): krawędź cienia w ciemnym motywie (jasna poświata) ma kontrast >= 1.3
    // względem papieru aplikacji — czarny gradient miał ~1.06 i był niewidoczny.
    const image = getComputedStyle(screen.getByTestId('scroll-shadow-right')).backgroundImage
    expect(edgeContrast(colorSchemes.dark.palette.background.paper, image)).toBeGreaterThanOrEqual(
      1.3,
    )
  })

  it('GridHeaderTitle: pełna etykieta w atrybucie title i klasa tytułu siatki', () => {
    renderBox(<GridHeaderTitle label="Data przesłania" />)
    const title = screen.getByText('Data przesłania')
    expect(title).toHaveAttribute('title', 'Data przesłania')
    expect(title.className).toContain('MuiDataGrid-columnHeaderTitle')
  })

  it('withEllipsisHeaders: dodaje nagłówek z title, nie nadpisuje własnego renderHeader', () => {
    const custom = (): ReactElement => <div data-testid="custom-header" />
    const first: GridColDef = { field: 'a', headerName: 'Kol A' }
    const columns = withEllipsisHeaders([
      first,
      { field: 'b', headerName: 'Kol B', renderHeader: custom },
      { field: 'c' },
    ])
    expect(columns[0]?.renderHeader).toBeTypeOf('function')
    expect(columns[1]?.renderHeader).toBe(custom)
    expect(columns[2]?.renderHeader).toBeUndefined()

    // Wywołanie renderHeader zwraca tytuł z natywnym `title` (pełna etykieta przy ucięciu).
    // Parametr w typach DataGrid wymaga `GridStateColDef` — częściowy obiekt wystarcza funkcji.
    const column = columns[0] as NonNullable<(typeof columns)[number]>
    const params = { field: column.field, colDef: column } as Parameters<
      NonNullable<GridColDef['renderHeader']>
    >[0]
    const header = column.renderHeader?.(params) as ReactElement
    renderBox(header)
    expect(screen.getByTitle('Kol A').className).toContain('MuiDataGrid-columnHeaderTitle')
  })
})
