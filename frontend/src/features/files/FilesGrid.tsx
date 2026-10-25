/**
 * Siatka plików (kontrakt WP E4-5c §4, §7): `DataGrid` z paginacją serwerową, zaznaczaniem
 * wierszy (checkbox) i kolumnami `filesColumns`. Bez sortowania — serwer domyślnie zwraca
 * `create_time` malejąco. Zaznaczenie trzyma rodzic jako tablicę identyfikatorów, a siatka
 * tłumaczy je na model DataGrid (`{ type, ids }`).
 */

import { useMemo } from 'react'
import type { JSX } from 'react'
import Box from '@mui/material/Box'
import { DataGrid } from '@mui/x-data-grid'
import type { GridPaginationModel, GridRowSelectionModel } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'

import { actionsFirst, useCompactGrid, useStickyColumns } from '../../components/gridCompact'
import { ScrollShadowBox, withEllipsisHeaders } from '../../components/ScrollShadowBox'
import { useDataGridLocaleText } from '../../hooks/useDataGridLocaleText'
import { resolveLanguage } from '../../i18n'

import { buildColumns } from './filesColumns'
import type { FileAction } from './FileRowActions'
import type { FileItem } from './queries'

/** Rozmiary stron siatki (kontrakt §7): domyślnie 15. */
const PAGE_SIZE_OPTIONS = [15, 30, 50]

/** Wysokość siatki — jsdom nie mierzy kontenera, a `disableVirtualization` i tak renderuje wiersze. */
const GRID_HEIGHT = 420

export type FilesGridProps = {
  rows: FileItem[]
  total: number
  loading: boolean
  page: number
  pageSize: number
  selectedIds: string[]
  onSelectedChange: (ids: string[]) => void
  onPageChange: (page: number, pageSize: number) => void
  onOpenFolder: (id: string) => void
  onAction: (action: FileAction, file: FileItem) => void
}

export function FilesGrid(props: FilesGridProps): JSX.Element {
  const { rows, total, loading, page, pageSize, selectedIds } = props
  const { i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const localeText = useDataGridLocaleText()

  // Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji pierwsza, jej treścią menu ⋮.
  const compact = useCompactGrid()
  const columns = withEllipsisHeaders(
    actionsFirst(
      buildColumns({
        language,
        compact,
        onOpenFolder: props.onOpenFolder,
        onAction: props.onAction,
      }),
      compact,
    ),
  )

  // Nowa tablica przy każdym renderze byłaby dla siatki zmianą modelu zaznaczenia.
  const rowSelectionModel = useMemo<GridRowSelectionModel>(
    () => ({ type: 'include', ids: new Set(selectedIds) }),
    [selectedIds],
  )

  function handleSelection(model: GridRowSelectionModel): void {
    props.onSelectedChange(Array.from(model.ids, (id) => String(id)))
  }

  function handlePagination(model: GridPaginationModel): void {
    // DataGrid liczy strony od 0, a zapytanie i stan strony od 1.
    props.onPageChange(model.page + 1, model.pageSize)
  }

  return (
    <Box data-testid="files-grid">
      <ScrollShadowBox
        scrollTargetSelector=".MuiDataGrid-virtualScroller"
        // Tabele wąskie (K5 + D3 z QA E5-H9-2): <= 600 px przyklejona tylko Nazwa (⋮ tylko,
        // gdy mieści się z Nazwą w ~45% szerokości; checkbox zaznaczania przewija się),
        // 600–900 px także ⋮, desktop checkbox + Nazwa.
        stickyFields={useStickyColumns('name', 190, {
          check: '__check__',
          actions: 'actions',
        })}
      >
        <DataGrid
          rows={rows}
          columns={columns}
          loading={loading}
          rowCount={total}
          paginationMode="server"
          pagination
          paginationModel={{ page: page - 1, pageSize }}
          onPaginationModelChange={handlePagination}
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          checkboxSelection
          disableRowSelectionOnClick
          rowSelectionModel={rowSelectionModel}
          onRowSelectionModelChange={handleSelection}
          disableVirtualization
          localeText={localeText}
          sx={{
            height: GRID_HEIGHT,
            // Wyrównanie zawartości komórek do środka wiersza (T7): MUI X centruje tylko teksty
            // (line-height), elementy `renderCell` (ikona + nazwa, przyciski) siedziały przy górze.
            '& .MuiDataGrid-cell': { display: 'flex', alignItems: 'center' },
          }}
        />
      </ScrollShadowBox>
    </Box>
  )
}
