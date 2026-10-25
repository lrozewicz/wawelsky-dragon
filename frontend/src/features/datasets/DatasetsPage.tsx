/**
 * Strona `/datasets` (08 §7.3): karty baz wiedzy („N plików”), tworzenie dialogiem
 * (nazwa, model embeddingu, metoda chunkowania → `/dataset/files/:id`), zmiana nazwy z menu
 * karty i usuwanie z potwierdzeniem. `?isCreate=true` (wejście z Home) otwiera dialog;
 * jego zamknięcie czyści parametr — wzór 1:1 z `features/chats/ChatsPage.tsx`.
 * Pasek zadań eksportu/importu (08 §7.15 (b)) montuje `<KbTransferHost>` wokół strony (nagłówek
 * w środku — przycisk „Importuj" i dialog importu korzystają z jego kontekstu, T6).
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useRouteContext, useSearch } from '@tanstack/react-router'
import AddIcon from '@mui/icons-material/Add'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined'
import StorageRoundedIcon from '@mui/icons-material/StorageRounded'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Grid from '@mui/material/Grid'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../components/EmptyState'
import PageContainer from '../../components/PageContainer'
import { QueryError } from '../../components/QueryError'
import { canExport } from '../kb-transfer/canExport'
import { KbTransferHost } from '../kb-transfer/KbTransferHost'
import { ChatNameDialog } from '../chats/components/ChatNameDialog'
import { mutationMessage } from './config/helpers'

import { CreateDatasetDialog } from './CreateDatasetDialog'
import { DatasetCard } from './DatasetCard'
import { DeleteDatasetDialog } from './DeleteDatasetDialog'
import { DatasetsHeader } from './DatasetsHeader'
import { ExportDialogSlot } from './ExportDialogSlot'
import { datasetsListQueryOptions, useDeleteDatasets, useUpdateDataset } from './queries'
import type { DatasetListed } from './queries'

/** Liczba szkieletów w stanie ładowania (pełny rząd na najszerszym breakpoincie). */
const SKELETON_COUNT = 8

type NameDialogState = { mode: 'create' } | { mode: 'rename'; dataset: DatasetListed }

function RenameDatasetDialog(props: { dataset: DatasetListed; onClose: () => void }) {
  const { t } = useTranslation()
  const updateDataset = useUpdateDataset(props.dataset.id)

  return (
    <ChatNameDialog
      title={t('datasets.list.rename')}
      submitLabel={t('datasets.list.renameSubmit')}
      initialName={props.dataset.name}
      loading={updateDataset.isPending}
      error={
        updateDataset.error === null
          ? null
          : mutationMessage(updateDataset.error, t('datasets.list.renameError'), t)
      }
      onSubmit={(name) => updateDataset.mutate({ name }, { onSuccess: props.onClose })}
      onClose={props.onClose}
    />
  )
}

export function DatasetsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  // Trasa jest cienka, a strona nie ma propsów — parametr czytamy sami (jak `ChatsPage`).
  const search = useSearch({ strict: false })
  const isCreate = search.isCreate === true

  const datasets = useQuery(datasetsListQueryOptions())
  const deleteDatasets = useDeleteDatasets()
  // Widoczność „Eksportuj” (CONTRACT WP E7-2 §8): właściciel bazy albo superuser.
  const user = useRouteContext({ strict: false, select: (context) => context.auth?.user ?? null })

  const [nameDialog, setNameDialog] = useState<NameDialogState | null>(
    isCreate ? { mode: 'create' } : null,
  )
  const [menu, setMenu] = useState<{ anchor: HTMLElement; dataset: DatasetListed } | null>(null)
  const [exportTarget, setExportTarget] = useState<{ id: string; name: string } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<DatasetListed | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  function closeNameDialog(): void {
    setNameDialog(null)
    // Zamknięcie okna kończy także wejście z parametrem — adres wraca do `/datasets`.
    if (isCreate) void navigate({ to: '/datasets', search: {} })
  }

  function confirmDelete(): void {
    const dataset = pendingDelete
    if (dataset === null) return
    deleteDatasets.mutate([dataset.id], {
      onSettled: () => setPendingDelete(null),
      onError: (error) => setDeleteError(mutationMessage(error, t('datasets.list.deleteError'), t)),
    })
  }

  function openDelete(dataset: DatasetListed): void {
    setDeleteError(null)
    setPendingDelete(dataset)
  }

  const createButton = (
    <Button
      variant="contained"
      startIcon={<AddIcon />}
      onClick={() => setNameDialog({ mode: 'create' })}
      sx={{ whiteSpace: 'nowrap' }}
    >
      {t('datasets.list.create')}
    </Button>
  )

  let content: ReactNode
  if (datasets.isPending) {
    content = (
      <Grid container spacing={2} data-testid="datasets-loading">
        {Array.from({ length: SKELETON_COUNT }, (_, index) => (
          <Grid key={index} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <Skeleton variant="rounded" height={160} />
          </Grid>
        ))}
      </Grid>
    )
  } else if (datasets.isError) {
    content = (
      <QueryError message={t('datasets.list.error')} onRetry={() => void datasets.refetch()} />
    )
  } else if (datasets.data.length === 0) {
    content = (
      <EmptyState
        icon={<StorageRoundedIcon fontSize="large" />}
        title={t('datasets.list.emptyTitle')}
        description={t('datasets.list.emptyDescription')}
        action={createButton}
      />
    )
  } else {
    content = (
      <Grid container spacing={2}>
        {datasets.data.map((dataset) => (
          <Grid key={dataset.id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <DatasetCard dataset={dataset} onMenuOpen={(anchor) => setMenu({ anchor, dataset })} />
          </Grid>
        ))}
      </Grid>
    )
  }

  return (
    <KbTransferHost>
      {/* Host otacza też nagłówek strony (funkcja `(taskBar) => …`): przycisk „Importuj" i dialog
          importu korzystają z kontekstu hosta, a pasek zadań (08 §7.15 (b)) zostaje pod nagłówkiem
          listy — dokładnie w tym samym miejscu DOM co przy owinięciu samej zawartości. */}
      {(taskBar) => (
        <PageContainer>
          <DatasetsHeader createButton={createButton} />
          {taskBar}
          <Stack spacing={2}>
            {deleteError !== null ? <Alert severity="error">{deleteError}</Alert> : null}
            {content}
          </Stack>

          {menu !== null ? (
            <Menu anchorEl={menu.anchor} open onClose={() => setMenu(null)}>
              {/* Pozycja tylko dla właściciela bazy i superusera (CONTRACT WP E7-2 §8). */}
              {user !== null && canExport(menu.dataset, user) ? (
                <MenuItem
                  onClick={() => {
                    setMenu(null)
                    setExportTarget({ id: menu.dataset.id, name: menu.dataset.name })
                  }}
                >
                  <ListItemIcon>
                    <FileDownloadOutlinedIcon />
                  </ListItemIcon>
                  <ListItemText>{t('kbTransfer.export.menuItem')}</ListItemText>
                </MenuItem>
              ) : null}
              <MenuItem
                onClick={() => {
                  setMenu(null)
                  setNameDialog({ mode: 'rename', dataset: menu.dataset })
                }}
              >
                <ListItemIcon>
                  <EditOutlinedIcon />
                </ListItemIcon>
                <ListItemText>{t('datasets.list.rename')}</ListItemText>
              </MenuItem>
              <MenuItem
                onClick={() => {
                  setMenu(null)
                  openDelete(menu.dataset)
                }}
              >
                <ListItemIcon>
                  <DeleteOutlineRoundedIcon />
                </ListItemIcon>
                <ListItemText>{t('datasets.list.delete')}</ListItemText>
              </MenuItem>
            </Menu>
          ) : null}

          {/* Dialog usuwania z listą powiązań (SC-V12-04) — montowany tylko na czas otwarcia,
              żeby zapytanie usage leciało wyłącznie dla aktywnej bazy (T4). */}
          {pendingDelete !== null ? (
            <DeleteDatasetDialog
              dataset={pendingDelete}
              loading={deleteDatasets.isPending}
              onConfirm={confirmDelete}
              onCancel={() => setPendingDelete(null)}
            />
          ) : null}

          {nameDialog !== null && nameDialog.mode === 'rename' ? (
            <RenameDatasetDialog dataset={nameDialog.dataset} onClose={closeNameDialog} />
          ) : null}
          {nameDialog !== null && nameDialog.mode === 'create' ? (
            <CreateDatasetDialog
              onClose={closeNameDialog}
              onCreated={(id) => void navigate({ to: '/dataset/files/$id', params: { id } })}
            />
          ) : null}
          {exportTarget !== null ? (
            <ExportDialogSlot dataset={exportTarget} onClose={() => setExportTarget(null)} />
          ) : null}
        </PageContainer>
      )}
    </KbTransferHost>
  )
}
