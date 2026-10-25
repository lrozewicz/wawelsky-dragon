/**
 * Szkielet ładowania siatki kluczy API (QA V12-z-2b MINOR-2): wiersze zamiast gołego
 * szarego prostokąta — widać, że tabela się ładuje, a nie że strona jest pusta/uszkodzona.
 * Używany w dwóch miejscach tej trasy: fallback `Suspense` w `routes/_app/user-setting/api.tsx`
 * (ładowanie chunku `ApiKeysPage`) i fallback `Suspense` w `ApiKeysPage` (chunk `KeysGrid`).
 */

import type { JSX } from 'react'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'

/** Wysokość wiersza nagłówka siatki (jak nagłówek `DataGrid`). */
const HEADER_HEIGHT = 56
/** Wysokość wiersza danych siatki i liczba wierszy szkieletu — razem ≈ 420 px (`GRID_HEIGHT`). */
const ROW_HEIGHT = 52
const ROW_COUNT = 6

export function GridSkeleton(): JSX.Element {
  return (
    <Stack spacing={1} data-testid="keys-grid-skeleton" aria-busy="true">
      <Skeleton variant="rounded" height={HEADER_HEIGHT} />
      {Array.from({ length: ROW_COUNT }, (_, row) => (
        <Skeleton key={row} variant="rounded" height={ROW_HEIGHT} />
      ))}
    </Stack>
  )
}
