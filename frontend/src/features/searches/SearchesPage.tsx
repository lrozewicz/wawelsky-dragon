/**
 * Strona `/searches` (kontrakt WP E4-4b §4): lista kart wyszukiwarek, tworzenie (nazwa →
 * `/search/:id`), zmiana nazwy z menu karty i usuwanie z potwierdzeniem. Błąd listy pokazuje
 * Alert, błąd mutacji — komunikat nad listą lub w oknie.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import AddIcon from '@mui/icons-material/Add'
import ManageSearchRoundedIcon from '@mui/icons-material/ManageSearchRounded'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardActionArea from '@mui/material/CardActionArea'
import Grid from '@mui/material/Grid'
import IconButton from '@mui/material/IconButton'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../api/envelope'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import PageContainer from '../../components/PageContainer'
import { QueryError } from '../../components/QueryError'
import { resolveLanguage } from '../../i18n'
import { formatDate } from '../../lib/format'

import { SearchNameDialog } from './components/SearchNameDialog'
import {
  searchesListQueryOptions,
  useCreateSearch,
  useDeleteSearch,
  useRenameSearch,
} from './queries'
import type { SearchListItem } from './queries'

/** Liczba szkieletów w stanie ładowania (pełny rząd na najszerszym breakpoincie). */
const SKELETON_COUNT = 8

/** Adres strony wyszukiwarki — trasa `/search/$id` (kontrakt §4). */
function searchHref(id: string): string {
  return `/search/${id}`
}

/** Komunikat błędu mutacji: treść z `ApiError`, a przy błędzie transportu — tekst z i18n. */
function mutationError(error: unknown, fallback: string): string | null {
  if (error === null || error === undefined) return null
  if (error instanceof ApiError && error.message !== '') return error.message
  return fallback
}

type NameDialogState = { mode: 'create' } | { mode: 'rename'; search: SearchListItem }

function CreateSearchDialog(props: { onCreated: (id: string) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const createSearch = useCreateSearch()

  return (
    <SearchNameDialog
      mode="create"
      busy={createSearch.isPending}
      error={mutationError(createSearch.error, t('searches.mutationError'))}
      onSubmit={(name) =>
        createSearch.mutate(name, { onSuccess: (result) => props.onCreated(result.search_id) })
      }
      onClose={props.onClose}
    />
  )
}

function RenameSearchDialog(props: { search: SearchListItem; onClose: () => void }) {
  const { t } = useTranslation()
  const renameSearch = useRenameSearch()

  return (
    <SearchNameDialog
      mode="rename"
      initialName={props.search.name}
      busy={renameSearch.isPending}
      error={mutationError(renameSearch.error, t('searches.mutationError'))}
      onSubmit={(name) =>
        renameSearch.mutate({ id: props.search.id, name }, { onSuccess: props.onClose })
      }
      onClose={props.onClose}
    />
  )
}

function SearchCard(props: { search: SearchListItem; onMenuOpen: (anchor: HTMLElement) => void }) {
  const { t, i18n } = useTranslation()
  const { search } = props

  return (
    <Card data-testid="search-card" sx={{ position: 'relative', height: '100%' }}>
      <CardActionArea component="a" href={searchHref(search.id)} sx={{ height: '100%' }}>
        <Stack spacing={1} sx={{ p: 2, pr: 6, height: '100%', alignItems: 'flex-start' }}>
          <Avatar>{search.name.trim().charAt(0).toUpperCase()}</Avatar>
          <Typography variant="subtitle1" noWrap sx={{ width: '100%' }}>
            {search.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('searches.updated', {
              date: formatDate(search.update_time, resolveLanguage(i18n.language)),
            })}
          </Typography>
        </Stack>
      </CardActionArea>
      <IconButton
        aria-label={t('searches.menu')}
        onClick={(event) => props.onMenuOpen(event.currentTarget)}
        sx={{ position: 'absolute', top: 8, right: 8 }}
      >
        <MoreVertIcon />
      </IconButton>
    </Card>
  )
}

export function SearchesPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const searches = useQuery(searchesListQueryOptions())
  const deleteSearch = useDeleteSearch()

  const [nameDialog, setNameDialog] = useState<NameDialogState | null>(null)
  const [menu, setMenu] = useState<{ anchor: HTMLElement; search: SearchListItem } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<SearchListItem | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  function confirmDelete(): void {
    const search = pendingDelete
    if (search === null) return
    deleteSearch.mutate(search.id, {
      onSettled: () => setPendingDelete(null),
      onError: (error) => setDeleteError(mutationError(error, t('searches.mutationError'))),
    })
  }

  function openDelete(search: SearchListItem): void {
    setDeleteError(null)
    setPendingDelete(search)
  }

  const createButton = (
    <Button
      variant="contained"
      startIcon={<AddIcon />}
      onClick={() => setNameDialog({ mode: 'create' })}
    >
      {t('searches.create')}
    </Button>
  )

  let content: ReactNode
  if (searches.isPending) {
    content = (
      <Grid container spacing={2} data-testid="searches-loading">
        {Array.from({ length: SKELETON_COUNT }, (_, index) => (
          <Grid key={index} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <Skeleton variant="rounded" height={180} />
          </Grid>
        ))}
      </Grid>
    )
  } else if (searches.isError) {
    content = (
      <QueryError message={t('searches.loadError')} onRetry={() => void searches.refetch()} />
    )
  } else if (searches.data.length === 0) {
    content = (
      <EmptyState
        icon={<ManageSearchRoundedIcon fontSize="large" />}
        title={t('searches.emptyTitle')}
        description={t('searches.emptyDescription')}
        action={createButton}
      />
    )
  } else {
    content = (
      <Grid container spacing={2}>
        {searches.data.map((search) => (
          <Grid key={search.id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <SearchCard search={search} onMenuOpen={(anchor) => setMenu({ anchor, search })} />
          </Grid>
        ))}
      </Grid>
    )
  }

  return (
    <PageContainer title={t('searches.title')} actions={createButton} responsiveHeader>
      <Stack spacing={2}>
        {deleteError !== null ? <Alert severity="error">{deleteError}</Alert> : null}
        {content}
      </Stack>

      {menu !== null ? (
        <Menu anchorEl={menu.anchor} open onClose={() => setMenu(null)}>
          <MenuItem
            onClick={() => {
              setMenu(null)
              setNameDialog({ mode: 'rename', search: menu.search })
            }}
          >
            {t('searches.rename')}
          </MenuItem>
          <MenuItem
            onClick={() => {
              setMenu(null)
              openDelete(menu.search)
            }}
          >
            {t('searches.delete')}
          </MenuItem>
        </Menu>
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('searches.deleteTitle')}
        message={t('searches.deleteMessage', { name: pendingDelete?.name ?? '' })}
        confirmLabel={t('searches.delete')}
        cancelLabel={t('searches.cancel')}
        loading={deleteSearch.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      {nameDialog !== null && nameDialog.mode === 'rename' ? (
        <RenameSearchDialog search={nameDialog.search} onClose={() => setNameDialog(null)} />
      ) : null}
      {nameDialog !== null && nameDialog.mode === 'create' ? (
        <CreateSearchDialog
          onClose={() => setNameDialog(null)}
          onCreated={(id) => void navigate({ to: '/search/$id', params: { id } })}
        />
      ) : null}
    </PageContainer>
  )
}
