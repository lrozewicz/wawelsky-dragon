/**
 * Zakładka „Pliki” szczegółów datasetu (kontrakt WP E3-3b §T5 i §T7): pasek narzędzi z filtrami
 * (slot `metadataFilter` — WP E6-1b T5b), `DataGrid` z paginacją i sortowaniem serwerowym
 * (`create_time` i `name` — WP E3-H2a §K1) oraz akcje wiersza i zbiorcze; odświeżanie w trakcie
 * parsowania wnoszą `refetchInterval` z `documentsListQueryOptions` (T1a). Stan dialogów akcji
 * (także szuflady metadanych, WP E6-1b T5a) trzyma `useFileActions` (widok: `FileActionDialogs`,
 * T7); kolumna „Metadane” (≥ 1536 px, kontrakt WP E6-1b §4) wpisuje się z `showMetadata`.
 */

import { useMemo, useState } from 'react'
import type { JSX } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import useMediaQuery from '@mui/material/useMediaQuery'
import { DataGrid } from '@mui/x-data-grid'
import type { GridPaginationModel, GridRowSelectionModel, GridSortModel } from '@mui/x-data-grid'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../../components/EmptyState'
import { actionsFirst, useCompactGrid, useStickyColumns } from '../../../components/gridCompact'
import { QueryError } from '../../../components/QueryError'
import { ScrollShadowBox, withEllipsisHeaders } from '../../../components/ScrollShadowBox'
import { useDataGridLocaleText } from '../../../hooks/useDataGridLocaleText'
import { resolveLanguage } from '../../../i18n'
import { datasetKeys } from '../queries'
import { BulkActionBar } from './BulkActionBar'
import { FileActionDialogs } from './FileActionDialogs'
import { buildColumns } from './filesColumns'
import { FilesSubtitle } from './FilesSubtitle'
import { FilesToolbar } from './FilesToolbar'
import { useToggleDocument } from './mutations'
import type { ParsingStatusDoc } from './ParsingStatusCell'
import { ProcessLogDialog } from './ProcessLogDialog'
import { DEFAULT_DOCUMENTS_QUERY, documentKeys, documentsListQueryOptions } from './queries'
import type { DocumentsQuery } from './queries'
import { RowActions } from './RowActions'
import { UploadDialog } from './UploadDialog'
import { useFileActions } from './useFileActions'
import { useMetadataListFilter } from './useMetadataListFilter'

/** Rozmiary stron siatki (kontrakt §T5). */
const PAGE_SIZE_OPTIONS = [10, 25, 50]

/** Wysokość siatki — jsdom nie mierzy kontenera, a `disableVirtualization` i tak renderuje wiersze. */
const GRID_HEIGHT = 420

/**
 * Sortowalne serwerowo kolumny siatki (kontrakt WP E3-H2a §K1, DEC-138): `name` to pole `name`,
 * a `create_time` („Data przesłania”) zostaje domyślnym `orderby`. `update_time` obsługuje API,
 * ale nie ma go w siatce.
 */
const SORT_FIELD = 'create_time'
const NAME_FIELD = 'name'

/**
 * Cykl kliknięć nagłówka: `desc` ↔ `asc`. Domyślny cykl DataGrid kończy się stanem pustym
 * (`['asc','desc',null]`), a przy kontrolowanym `sortModel` ten stan wracałby do `desc:true` —
 * sortowanie rosnące byłoby nieosiągalne z UI.
 */
const SORT_ORDER = ['asc', 'desc'] as const

export type DatasetFilesTabProps = {
  datasetId: string
}

export function DatasetFilesTab(props: DatasetFilesTabProps): JSX.Element {
  const { datasetId } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const localeText = useDataGridLocaleText()
  const queryClient = useQueryClient()

  const [query, setQuery] = useState<DocumentsQuery>(DEFAULT_DOCUMENTS_QUERY)
  // Kształt modelu zaznaczenia w wersji 9 DataGrid: `{ type, ids }` — `exclude` odwraca sens zbioru.
  const [rowSelectionModel, setRowSelectionModel] = useState<GridRowSelectionModel>({
    type: 'include',
    ids: new Set(),
  })
  const [uploadOpen, setUploadOpen] = useState(false)
  const [logDoc, setLogDoc] = useState<ParsingStatusDoc | null>(null)

  // Nowa tablica przy każdym renderze byłaby dla siatki zmianą modelu sortowania i wracała na stronę 1.
  const sortModel = useMemo<GridSortModel>(
    () => [
      {
        field: query.orderby === 'name' ? NAME_FIELD : SORT_FIELD,
        sort: query.desc ? 'desc' : 'asc',
      },
    ],
    [query.orderby, query.desc],
  )

  const documents = useQuery(documentsListQueryOptions(datasetId, query))
  const toggle = useToggleDocument(datasetId)
  const selectedDocs = useMemo(() => {
    const rows = documents.data?.docs ?? []
    return rowSelectionModel.type === 'include'
      ? rows.filter((doc) => rowSelectionModel.ids.has(doc.id))
      : rows.filter((doc) => !rowSelectionModel.ids.has(doc.id))
  }, [documents.data, rowSelectionModel])
  const actions = useFileActions(datasetId, selectedDocs)
  const { filterBar: metadataFilterBar, clearFilter: clearMetaFilter } = useMetadataListFilter(
    datasetId,
    query,
    applyQuery,
  )

  /**
   * Czyści zaznaczenie: przycisk „Wyczyść” na pasku zbiorczym oraz zmiana widoku (strona, filtr,
   * sortowanie), po której wiersze z poprzedniego widoku znikają. Po samych akcjach zbiorczych
   * zaznaczenia nie ruszamy (kontrakt WP E3-H2a §K6) — `DataGrid` sam wypuszcza id wierszy,
   * których nie ma już na liście.
   */
  function clearSelection(): void {
    setRowSelectionModel({ type: 'include', ids: new Set() })
  }

  /** Zmiana strony lub filtra unieważnia zaznaczenie — wiersze z poprzedniego widoku znikają. */
  function applyQuery(next: DocumentsQuery): void {
    setQuery(next)
    clearSelection()
  }

  function handlePaginationChange(model: GridPaginationModel): void {
    if (model.page === query.page - 1 && model.pageSize === query.pageSize) return
    applyQuery({ ...query, page: model.page + 1, pageSize: model.pageSize })
  }

  /**
   * Klik nagłówka: kolumna wybiera `orderby` (`name` albo `create_time`), a kierunek idzie za
   * cyklem DataGrid (`asc` ↔ `desc`). Puste sortowanie wraca do domyślnego `create_time` malejąco.
   */
  function handleSortChange(model: GridSortModel): void {
    const item = model.find((entry) => entry.field === SORT_FIELD || entry.field === NAME_FIELD)
    const orderby: DocumentsQuery['orderby'] = item?.field === NAME_FIELD ? 'name' : 'create_time'
    const desc = item?.sort !== 'asc'
    if (orderby === query.orderby && desc === query.desc) return
    applyQuery({ ...query, orderby, desc, page: 1 })
  }

  // Wzorzec < md (kontrakt WP E3-7 §C2): ⋮ jako dane menu (z „Metadane”, WP E6-1b T5a);
  // kolumna „Metadane” dopiero ≥ 1536 px (xl; TL 2026-10-13: przy 1280 nie mieści się) —
  // jsdom bez `matchMedia` widzi wersję bez niej (jak `useCompactGrid`).
  const compact = useCompactGrid()
  const showMetadata = useMediaQuery('(min-width:1536px)')
  // Metoda chunkowania ukryta md–xl (E67-z2 T6); jsdom bez matchMedia ją pokazuje.
  const showMethod = compact || showMetadata || typeof window.matchMedia !== 'function'
  // 125 = próg decyzji D3 (QA E5-H9-2): ⋮ przewija się z tabelą na 390 px (≠ minWidth kolumny name).
  const stickyFields = useStickyColumns('name', 125, { check: '__check__', actions: 'actions' })

  const columns = withEllipsisHeaders(
    actionsFirst(
      buildColumns({
        datasetId,
        language,
        compact,
        compactActions: actions.rowMenuItems,
        showMetadata,
        showMethod,
        onToggle: (doc, enabled) => {
          toggle.mutate({ id: doc.id, enabled })
        },
        onParse: actions.onParse,
        onStop: actions.onStop,
        onOpenLog: (doc) => {
          setLogDoc(doc)
        },
        onOpenMethod: actions.onOpenMethod,
        renderActions: (doc) => (
          <RowActions
            doc={doc}
            onRename={() => actions.onRename(doc)}
            onDownload={() => actions.onDownload(doc)}
            onDelete={() => actions.onDelete(doc)}
            onMetadata={() => actions.onMetadata(doc)}
            onOpenMethod={() => actions.onOpenMethod(doc)}
          />
        ),
      }),
      compact,
    ),
  )

  // Pusty wynik aktywnego filtra metadanych (WP E6-1b §4): NIE stan pustego datasetu.
  const filterEmpty =
    !documents.isPending && (documents.data?.total ?? 0) === 0 && query.metadataCondition !== ''

  return (
    <Stack spacing={2}>
      <FilesSubtitle docs={documents.data?.docs ?? []} />

      <FilesToolbar
        query={query}
        onChange={applyQuery}
        onAdd={() => setUploadOpen(true)}
        metadataFilter={metadataFilterBar}
        showAdd={!filterEmpty}
      />

      <BulkActionBar
        count={selectedDocs.length}
        onParse={actions.bulk.onParse}
        onCancel={actions.bulk.onCancel}
        onEnable={actions.bulk.onEnable}
        onDisable={actions.bulk.onDisable}
        onDelete={actions.bulk.onDelete}
        onClear={clearSelection}
      />

      {documents.isError ? (
        <QueryError
          message={t('datasets.files.loadError')}
          onRetry={() => void documents.refetch()}
        />
      ) : !documents.isPending && (documents.data?.total ?? 0) === 0 ? (
        // Pusty stan poza siatką (kontrakt §C6): `DataGrid` z zerem wierszy to `role="grid"`
        // bez dzieci, co axe zgłasza jako `aria-required-children` (critical).
        filterEmpty ? (
          // 0 trafień aktywnego filtra metadanych (WP E6-1b §4): akcją jest zdjęcie filtra.
          <EmptyState
            title={t('metadata.listFilter.empty')}
            action={
              <Button variant="outlined" onClick={clearMetaFilter}>
                {t('metadata.listFilter.clearFilter')}
              </Button>
            }
          />
        ) : (
          <EmptyState
            title={t('datasets.files.empty')}
            description={t('datasets.files.emptyHint')}
          />
        )
      ) : (
        <Box data-testid="files-grid">
          <ScrollShadowBox
            scrollTargetSelector=".MuiDataGrid-virtualScroller"
            // K5 + D3 (QA E5-H9-2): <= 600 px tylko Nazwa, 600–900 px także ⋮, desktop checkbox.
            stickyFields={stickyFields}
          >
            <DataGrid
              rows={documents.data?.docs ?? []}
              columns={columns}
              loading={documents.isPending || documents.isFetching}
              rowCount={documents.data?.total ?? 0}
              paginationMode="server"
              sortingMode="server"
              pagination
              paginationModel={{ page: query.page - 1, pageSize: query.pageSize }}
              onPaginationModelChange={handlePaginationChange}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              sortModel={sortModel}
              onSortModelChange={handleSortChange}
              sortingOrder={SORT_ORDER}
              checkboxSelection
              disableRowSelectionOnClick
              rowSelectionModel={rowSelectionModel}
              onRowSelectionModelChange={setRowSelectionModel}
              disableVirtualization
              localeText={localeText}
              sx={{
                height: GRID_HEIGHT,
                // Wyrównanie zawartości komórek do środka wiersza (T7): MUI X centruje tylko
                // teksty (line-height), elementy `renderCell` (switch, chip, przyciski) siedziały
                // przy górze wiersza.
                '& .MuiDataGrid-cell': { display: 'flex', alignItems: 'center' },
              }}
            />
          </ScrollShadowBox>
        </Box>
      )}

      <UploadDialog
        open={uploadOpen}
        datasetId={datasetId}
        onClose={() => {
          setUploadOpen(false)
        }}
        onUploaded={() => {
          void queryClient.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
          // Nagłówek („N plików · rozmiar”) czyta szczegół zbioru (`datasetQueryOptions`), a klucze
          // zapytań działają prefiksowo — unieważnienie samych dokumentów nie ruszy licznika (U3).
          void queryClient.invalidateQueries({ queryKey: datasetKeys.detail(datasetId) })
        }}
      />

      <ProcessLogDialog
        open={logDoc !== null}
        doc={logDoc}
        onClose={() => {
          setLogDoc(null)
        }}
      />

      <FileActionDialogs model={actions.dialogs} />
    </Stack>
  )
}
