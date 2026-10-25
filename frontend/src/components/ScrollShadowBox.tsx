/**
 * Kontener przewijania tabeli (K5 WP E5-H9): gradientowy cień na krawędzi, po której jest
 * co przewijać (`data-testid="scroll-shadow-left"` / `"scroll-shadow-right"` — renderowane
 * tylko wtedy), przyklejona pierwsza kolumna `DataGrid` (`position: sticky; left: 0`,
 * tło `background.paper`) i nagłówki z wielokropkiem + natywnym `title`.
 *
 * `DataGrid` przewija się własnym elementem (`.MuiDataGrid-virtualScroller`), więc użycie
 * wokół siatki przekazuje go w `scrollTargetSelector`; bez selektora obserwowany jest sam
 * kontener. Przewijanie łapie zdarzenie `scroll`, a zmiany wymiarów (wejście/wyjście
 * pionowego przewijaka, resize okna) — `ResizeObserver` (w jsdom: atrapa no-op z setup.ts).
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import Box from '@mui/material/Box'
import { useColorScheme } from '@mui/material/styles'
import type { CSSObject, SxProps, Theme } from '@mui/material/styles'
import type { GridColDef, GridColumnHeaderParams } from '@mui/x-data-grid'

/** Szerokość (px) gradientu cienia na krawędzi kontenera. */
const SHADOW_WIDTH = 24

/**
 * Pomijalny nadmiar przewijania (px). MUI X rysuje separator ostatniej kolumny 5 px poza
 * treścią (`right: -5px`, szerokość 10), więc gdy kolumny mieszczą się w kontenerze,
 * `scrollWidth` = `clientWidth` + 5 (pomiar T15: 995 vs 990 na liście dokumentów, Plikach,
 * Modelach i Użytkownikach przy 1280/1440). Cień z takiego nadmiaru to fałszywa wskazówka
 * przewijania zachodząca na ostatni przycisk (wada MAJOR); przewinięcie o tyle nie ma sensu
 * wizualnego, a przy realnym przewijaniu (390 px) nadmiar liczy się w setkach pikseli.
 */
const SCROLL_SLACK_PX = 8

/**
 * Kolory gradientu cienia (krawędź → zanik). Na ciemnym tle czarny gradient jest niewidoczny
 * (D2 z QA E5-H9-2: kontrast ~1.06 względem `background.paper` hsl 220 30% 7%) — krawędź robi
 * jasna poświata, mierzalna kontrastem WCAG >= 1.3 (pilnuje test komponentowy).
 */
function shadowStops(resolvedMode: 'light' | 'dark' | undefined): [string, string] {
  return resolvedMode === 'dark'
    ? ['rgba(255, 255, 255, 0.2)', 'rgba(255, 255, 255, 0)']
    : ['rgba(0, 0, 0, 0.14)', 'rgba(0, 0, 0, 0)']
}

export type ScrollShadowBoxProps = {
  children: ReactNode
  /** Selektor elementu przewijającego wewnątrz kontenera (domyślnie: sam kontener). */
  scrollTargetSelector?: string
  /**
   * Pola `DataGrid` przyklejone do lewej krawędzi (w kolejności od początku; puste — żadna).
   * Selekcja po `data-field`, nie po pozycji: `DataGrid` v9 wstawia w wierszu i nagłówkach
   * dodatkowe elementy-placeholdery (offset pinowania), przez co `nth-child` się przesuwa.
   */
  stickyFields?: readonly string[]
  sx?: SxProps<Theme>
}

/** Stan cieni: czy po danej stronie elementu przewijającego zostało coś do przewinięcia. */
type Shadows = { left: boolean; right: boolean }

/**
 * Rozstawia przyklejone kolumny i zwraca łączną szerokość (px) sticky obszaru — od niej
 * zaczyna się cień lewy (MUI X: lewy cień poziomy startuje za ostatnią przypiętą kolumną).
 * Szerokości kolumn zna tylko przeglądarka, więc kolejne `left` (suma poprzednich) ustawiane
 * są wprost na nagłówkach i komórkach każdego wiersza; bez danych (stan pusty) — 0.
 */
function layoutStickyColumns(container: HTMLElement, fields: readonly string[]): number {
  let offset = 0
  for (const field of fields) {
    const elements = container.querySelectorAll<HTMLElement>(`[data-field="${field}"]`)
    elements.forEach((element) => {
      element.style.left = `${offset}px`
    })
    offset += (elements[0] as HTMLElement | undefined)?.offsetWidth ?? 0
  }
  return offset
}

/**
 * Tła przyklejonych komórek jak tła wiersza (K5: nieprzezroczyste `background.default` jak tło siatki — T8; hover/zaznaczenie
 * wiersza nie mogą się „przecinać” z przyklejoną kolumną). Kolor interakcji MUI jest
 * półprzezroczysty, więc nakładam go gradientem `background-image` na nieprzezroczysty
 * `background-color: background.default` — bez liczenia mieszania kolorów w JS.
 */
function stickyFieldsSx(fields: readonly string[]): (theme: Theme) => CSSObject {
  const byField = fields.map((field) => `[data-field="${field}"]`).join(',')
  const headerSelector = `& .MuiDataGrid-columnHeader:is(${byField})`
  const cellSelector = `& .MuiDataGrid-cell:is(${byField})`
  return (theme) => {
    // Motyw z CSS variables (AppTheme): wartości z `vars` zmieniają się ze schematem —
    // `theme.palette` trzyma stałą, jasną paletę (wzór: `ColorModeIconDropdown`).
    const palette = (theme.vars || theme).palette
    const paper = palette.background.paper
    // Komórki: tło wiersza = tło siatki (`background.default`, motyw `dataGrid`); nagłówki: `paper`.
    const cellBackground = palette.background.default
    const hover = palette.action.hover
    const selected = palette.action.selected
    return {
      // z-index nagłówka 40 i komórki 1: nad separatorami kolumn (30) i treścią przewijaną
      // pod spodem — wartości jak dla przypiętych kolumn w stylach `DataGrid`. `left` rozstawia
      // `layoutStickyColumns` (style inline) — każda kolejna kolumna za poprzednią.
      [headerSelector]: {
        position: 'sticky',
        left: 0,
        zIndex: 40,
        backgroundColor: paper,
      },
      // Nagłówek checkboxa nie ma tytułu, a jego separator (`absolute; right: -5px`) wystaje
      // poza kolumnę — wygląda jak ucięty tekst bez podpowiedzi (SC-E5-H9-07 k. 2); bez niego
      // kolumna checkboxa jest domknięta, a granicę rysuje następny nagłówek.
      '& .MuiDataGrid-columnHeaderCheckbox .MuiDataGrid-columnSeparator': { display: 'none' },
      [cellSelector]: {
        position: 'sticky',
        left: 0,
        zIndex: 1,
        backgroundColor: cellBackground,
      },
      [`& .MuiDataGrid-row:hover .MuiDataGrid-cell:is(${byField})`]: {
        backgroundImage: `linear-gradient(${hover}, ${hover})`,
      },
      [`& .MuiDataGrid-row.Mui-selected .MuiDataGrid-cell:is(${byField})`]: {
        backgroundImage: `linear-gradient(${selected}, ${selected})`,
      },
      [`& .MuiDataGrid-row.Mui-selected:hover .MuiDataGrid-cell:is(${byField})`]: {
        backgroundImage: `linear-gradient(${hover}, ${hover}), linear-gradient(${selected}, ${selected})`,
      },
      // M2 (WP V12-2 C.5): ostatni wiersz był bez dolnej linii pod przyklejoną komórką —
      // nieprzezroczyste tło sticky komórki zakrywa ramkę `row: last-of-type` (motyw dataGrid).
      // Linię pod ostatnim wierszem rysuje więc sama komórka, tym samym kolorem `divider`.
      [`& .MuiDataGrid-row:last-of-type .MuiDataGrid-cell:is(${byField})`]: {
        borderBottom: `1px solid ${palette.divider}`,
      },
    }
  }
}

/** Cień jednej krawędzi: absolutny nad tabelą, bez przechwytywania wskaźnika. */
function shadowSx(side: 'left' | 'right', offset: number, stops: [string, string]): CSSObject {
  return {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: SHADOW_WIDTH,
    zIndex: 45,
    pointerEvents: 'none',
    ...(side === 'left' ? { left: offset } : { right: 0 }),
    background: `linear-gradient(to ${side === 'left' ? 'right' : 'left'}, ${stops[0]}, ${stops[1]})`,
  }
}

export function ScrollShadowBox(props: ScrollShadowBoxProps): JSX.Element {
  const { children, scrollTargetSelector, stickyFields, sx } = props
  const fields = stickyFields ?? []
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [shadows, setShadows] = useState<Shadows>({ left: false, right: false })
  const [stickyWidth, setStickyWidth] = useState(0)
  // Motyw aplikacji rozwiązuje schemat providerem CSS variables (AppTheme); bez niego
  // (`useColorScheme` zwraca pusty kontekst) cień przybiera barwę dla jasnego tła.
  const { mode, systemMode } = useColorScheme()
  const stops = shadowStops((systemMode || mode) as 'light' | 'dark' | undefined)

  // Klucz pól zamiast referencji tablicy: gridy budują listę w renderze (wariant compact),
  // a efekt nie ma się przepinać przy każdym renderze.
  const fieldsKey = fields.join('|')
  useEffect(() => {
    // Ref jest ustawiony przed uruchomieniem efektów (gwarancja React) — bez gałęzi na null.
    const container = containerRef.current as HTMLElement
    const target =
      scrollTargetSelector === undefined
        ? container
        : container.querySelector<HTMLElement>(scrollTargetSelector)
    if (target === null) return
    const sticky = fieldsKey.length === 0 ? [] : fieldsKey.split('|')
    const update = () => {
      const { scrollLeft, scrollWidth, clientWidth } = target
      setShadows({
        left: scrollLeft > 1,
        right: scrollWidth - (scrollLeft + clientWidth) > SCROLL_SLACK_PX,
      })
      setStickyWidth(layoutStickyColumns(container, sticky))
    }
    update()
    target.addEventListener('scroll', update, { passive: true })
    const observer = new ResizeObserver(update)
    observer.observe(target)
    return () => {
      target.removeEventListener('scroll', update)
      observer.disconnect()
    }
  }, [scrollTargetSelector, fieldsKey])

  return (
    <Box
      ref={containerRef}
      sx={[
        { position: 'relative', minWidth: 0 },
        fields.length > 0 && stickyFieldsSx(fields),
        ...(Array.isArray(sx) ? sx : [sx]),
      ]}
    >
      {children}
      {shadows.left && (
        <Box data-testid="scroll-shadow-left" sx={shadowSx('left', stickyWidth, stops)} />
      )}
      {shadows.right && <Box data-testid="scroll-shadow-right" sx={shadowSx('right', 0, stops)} />}
    </Box>
  )
}

/**
 * Tytuł nagłówka kolumny z wielokropkiem i natywnym `title` (K5). Domyślny tytuł `DataGrid`
 * ma wielokropek, ale pełną etykietę pokazuje tylko tooltipem MUI — bez atrybutu `title`,
 * którego wymaga scenariusz SC-E5-H9-07 („nigdy ucięte na krawędzi bez podpowiedzi”).
 */
export function GridHeaderTitle(props: { label: string }): JSX.Element {
  const { label } = props
  return (
    <Box
      // Klasa domyślnego tytułu `DataGrid` — spójny wygląd (grubość, wysokość linii) i cel
      // testów e2e szukających `.MuiDataGrid-columnHeaderTitle`.
      className="MuiDataGrid-columnHeaderTitle"
      title={label}
      sx={{
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        fontWeight: 'var(--unstable_DataGrid-headWeight)',
        lineHeight: 'normal',
      }}
    >
      {label}
    </Box>
  )
}

/**
 * Dodaje kolumnom bez własnego `renderHeader` nagłówek z `title` (K5) — bez mutacji wejścia;
 * kolumny bez `headerName` (np. checkbox) zostają bez zmian.
 */
export function withEllipsisHeaders<T extends GridColDef>(columns: T[]): T[] {
  return columns.map((column) =>
    typeof column.headerName === 'string' && column.renderHeader === undefined
      ? {
          ...column,
          // `headerName` jest stringiem (warunek powyżej); rzutowanie tylko dla typów.
          renderHeader: (params: GridColumnHeaderParams) => (
            <GridHeaderTitle label={params.colDef.headerName as string} />
          ),
        }
      : column,
  )
}
