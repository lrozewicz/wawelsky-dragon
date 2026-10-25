/**
 * Strona `/files` (kontrakt WP E4-5c §2, §7): breadcrumbs, wyszukiwanie z debounce, przycisk
 * „Dodaj” z menu (Prześlij/Nowy folder), siatka z paginacją serwerową i stan pusty/błąd, pasek
 * akcji zbiorczych oraz dialogi (T4). Stan celów dialogów i handlery trzyma `useFilesActions`,
 * a same okna renderuje `FilesDialogs`. Kontrakt §7 mówi o `Route.useSearch()`; trasa jest cienka,
 * a strona nie ma propsów, więc parametr czytamy przez `useSearch({ strict: false })` — tak samo
 * jak `ChatsPage` i `DatasetsPage` — dzięki czemu komponent da się testować bez całości drzewa tras.
 */

import { useEffect, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import AddIcon from '@mui/icons-material/Add'
import Button from '@mui/material/Button'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../components/EmptyState'
import PageContainer from '../../components/PageContainer'
import { QueryError } from '../../components/QueryError'

import { FilesBreadcrumbs } from './FilesBreadcrumbs'
import { FilesBulkBar } from './FilesBulkBar'
import { FilesDialogs } from './FilesDialogs'
import { FilesGrid } from './FilesGrid'
import { DEFAULT_FILES_QUERY, filesListQueryOptions } from './queries'
import { useFilesActions } from './useFilesActions'

/** Opóźnienie wyszukiwania (kontrakt §2). */
export const SEARCH_DEBOUNCE_MS = 300

export function FilesPage(): JSX.Element {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const search = useSearch({ strict: false })
  const folder = typeof search.folder === 'string' ? search.folder : undefined

  const [searchText, setSearchText] = useState('')
  const [keywords, setKeywords] = useState('')
  const [page, setPage] = useState(DEFAULT_FILES_QUERY.page)
  const [pageSize, setPageSize] = useState(DEFAULT_FILES_QUERY.pageSize)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  // Ostatni widok, dla którego ustawiono stronę — zmiana folderu lub frazy wraca na stronę 1
  // i czyści zaznaczenie (kontrakt §2), także przy nawigacji wstecz.
  const [view, setView] = useState<{ folder: string | undefined; keywords: string }>({
    folder,
    keywords,
  })

  // Tekst trafia do zapytania 300 ms po ostatnim znaku (wzór `UsersPage`).
  useEffect(() => {
    const timer = setTimeout(() => {
      setKeywords(searchText)
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [searchText])

  // Korekta stanu w renderze (wzorzec React) — bez efektu i kaskadowego renderu.
  if (view.folder !== folder || view.keywords !== keywords) {
    setView({ folder, keywords })
    setPage(DEFAULT_FILES_QUERY.page)
    setSelectedIds([])
  }

  const files = useQuery(
    filesListQueryOptions({
      ...DEFAULT_FILES_QUERY,
      parentId: folder,
      keywords,
      page,
      pageSize,
    }),
  )

  const rows = files.data?.files ?? []
  const actions = useFilesActions({
    rows,
    selectedIds,
    onClearSelection: () => {
      setSelectedIds([])
    },
  })

  function goToFolder(id: string | undefined): void {
    void navigate(
      id === undefined ? { to: '/files', search: {} } : { to: '/files', search: { folder: id } },
    )
  }

  function openDialog(request: 'upload' | 'folder'): void {
    setMenuAnchor(null)
    actions.openDialog(request)
  }

  const toolbar = (
    <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 2 }}>
      <TextField
        size="small"
        placeholder={t('files.search')}
        value={searchText}
        data-testid="files-search"
        onChange={(event) => setSearchText(event.target.value)}
        sx={{ minWidth: 240 }}
      />
      <Button
        variant="contained"
        startIcon={<AddIcon />}
        data-testid="files-add"
        onClick={(event) => setMenuAnchor(event.currentTarget)}
      >
        {t('files.add')}
      </Button>
    </Stack>
  )

  let content: ReactNode
  if (files.isError) {
    content = (
      <QueryError message={t('files.error.loadFailed')} onRetry={() => void files.refetch()} />
    )
  } else if (!files.isPending && (files.data?.total ?? 0) === 0) {
    content = (
      <EmptyState
        title={keywords === '' ? t('files.empty.title') : t('files.empty.noResults')}
        description={keywords === '' ? t('files.empty.description') : undefined}
      />
    )
  } else {
    content = (
      <FilesGrid
        rows={rows}
        total={files.data?.total ?? 0}
        loading={files.isPending || files.isFetching}
        page={page}
        pageSize={pageSize}
        selectedIds={selectedIds}
        onSelectedChange={setSelectedIds}
        onPageChange={(nextPage, nextPageSize) => {
          setPage(nextPage)
          setPageSize(nextPageSize)
          setSelectedIds([])
        }}
        onOpenFolder={goToFolder}
        onAction={actions.onAction}
      />
    )
  }

  return (
    <PageContainer title={t('files.title')} actions={toolbar}>
      <Stack spacing={2}>
        {/* Na korzeniu tytuł strony już mówi „Pliki” — okruszki dopiero w podfolderze. */}
        {folder === undefined ? null : (
          <FilesBreadcrumbs folderId={folder} onNavigate={goToFolder} />
        )}
        {!files.isError && (files.data?.total ?? 0) > 0 ? (
          <FilesBulkBar
            count={actions.selectedCount}
            linkDisabled={actions.linkDisabled}
            onLink={actions.linkSelected}
            onMove={actions.moveSelected}
            onDelete={actions.deleteSelected}
            onClear={actions.clearSelection}
          />
        ) : null}
        {content}
      </Stack>

      <Menu anchorEl={menuAnchor} open={menuAnchor !== null} onClose={() => setMenuAnchor(null)}>
        <MenuItem data-testid="files-add-upload" onClick={() => openDialog('upload')}>
          {t('files.upload')}
        </MenuItem>
        <MenuItem data-testid="files-add-folder" onClick={() => openDialog('folder')}>
          {t('files.newFolder')}
        </MenuItem>
      </Menu>

      <FilesDialogs
        parentId={folder}
        dialog={actions.dialog}
        renameTarget={actions.renameTarget}
        moveTargets={actions.moveTargets}
        linkTargets={actions.linkTargets}
        deleteTargets={actions.deleteTargets}
        previewDoc={actions.previewDoc}
        deleting={actions.deleting}
        onCloseDialog={actions.closeDialog}
        onCloseRename={actions.closeRename}
        onCloseMove={actions.closeMove}
        onCloseLink={actions.closeLink}
        onCloseDelete={actions.closeDelete}
        onClosePreview={actions.closePreview}
        onConfirmDelete={actions.confirmDelete}
      />
    </PageContainer>
  )
}
