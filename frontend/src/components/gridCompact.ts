/**
 * Wzorzec < md (kontrakt WP E3-7 §C2): na wąskim ekranie akcje wiersza wędrują na początek
 * listy (pierwsza kolumna danych, przed nią `DataGrid` wstawia jeszcze checkbox), gdzie
 * zastępuje je menu ⋮ (`RowActionsMenu`). `useCompactGrid` czyta punkt przełamania motywu
 * (`md`), więc w jsdom bez `matchMedia` zwraca `false` — testy jednostkowe widzą wersję desktop.
 */

import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'

/** Czy listę rysujemy w trybie compact (`< md`). */
export function useCompactGrid(): boolean {
  const theme = useTheme()
  return useMediaQuery(theme.breakpoints.down('md'))
}

/**
 * W trybie compact przenosi kolumnę o `field === 'actions'` na początek tablicy wynikowej
 * (nie mutując wejścia); poza nim zwraca wejście bez zmian (ta sama referencja), żeby model
 * kolumn `DataGrid` nie zmieniał się przy każdym renderze.
 */
export function actionsFirst<T extends { field: string }>(columns: T[], compact: boolean): T[] {
  if (!compact) return columns
  const index = columns.findIndex((column) => column.field === 'actions')
  const actions = columns[index]
  if (index < 0 || actions === undefined) return columns
  return [actions, ...columns.filter((column) => column.field !== 'actions')]
}

/** Czy ekran wąski (<= 600 px, D3 z QA E5-H9-2): przyklejona tylko Nazwa (± ⋮). */
export function useNarrowGrid(): boolean {
  const theme = useTheme()
  return useMediaQuery(theme.breakpoints.down('sm'))
}

/**
 * Kolumny przyklejone do lewej krawędzi (K5 + D3 z QA E5-H9-2): desktop — checkbox (+⋮ na
 * < md) i kolumna `name`; viewport <= 600 px — tylko `name`, a ⋮ dołącza, gdy `name`+⋮
 * mieszczą się w ~45% szerokości okna (ma zostać widoczny pas przewijanej treści >= 150 px).
 * Checkbox zaznaczania na wąskim ekranie przewija się z tabelą. `actionsWidth` — szerokość
 * kolumny ⋮ (domyślnie 64 px, każda siatka ma `RowActionsMenu` o tej szerokości).
 */
export function useStickyColumns(
  name: string,
  nameMinWidth: number,
  options: { check?: string; actions?: string; actionsWidth?: number } = {},
): string[] {
  const narrow = useNarrowGrid()
  const compact = useCompactGrid()
  if (narrow) {
    const windowWidth = typeof window === 'undefined' ? Infinity : window.innerWidth
    const together = nameMinWidth + (options.actionsWidth ?? 64)
    return options.actions !== undefined && together <= windowWidth * 0.45
      ? [options.actions, name]
      : [name]
  }
  return [
    ...(options.check !== undefined ? [options.check] : []),
    ...(compact && options.actions !== undefined ? [options.actions] : []),
    name,
  ]
}
