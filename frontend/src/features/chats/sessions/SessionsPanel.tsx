/**
 * Kolumna rozmów czatu (kontrakt WP E3-5b §T4): lista sesji z filtrem po nazwie, „+" na sesję
 * tymczasową (DEC-078: `onSelect(null)`, bez `POST /sessions`), zmiana nazwy, usuwanie
 * z potwierdzeniem i zwijanie do wąskiego paska. Stan listy bierze z T1 (`sessionQueries`),
 * okna z `src/components`, napisy z i18n (`chat.sessions.*`).
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import AddIcon from '@mui/icons-material/Add'
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded'
import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Divider from '@mui/material/Divider'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'

import { ChatNameDialog } from '../components/ChatNameDialog'
import { sessionsListQueryOptions, useDeleteSessions, useRenameSession } from './sessionQueries'
import type { Session } from './sessionQueries'

/** Szerokości panelu (08 §7.7): pełna kolumna i pasek po zwinięciu. Poniżej `sm` kolumna,
 * jako zawartość szuflady mobilnej (T7 E5-H8z), rozciąga się na całą szerokość szuflady. */
export const SESSIONS_PANEL_WIDTH = 280
const COLLAPSED_WIDTH = 56
/** Liczba szkieletów w stanie ładowania listy. */
const LOADING_ROWS = 3

export type SessionsPanelProps = {
  chatId: string
  chatName?: string
  activeSessionId: string | null
  onSelect: (sessionId: string | null) => void
  collapsed: boolean
  onToggleCollapsed: () => void
}

/** Komunikat błędu mutacji: treść z `ApiError`, a przy błędzie transportu — tekst z i18n. */
function mutationError(error: unknown, fallback: string): string | null {
  if (error === null || error === undefined) return null
  if (error instanceof ApiError && error.message !== '') return error.message
  return fallback
}

export function SessionsPanel(props: SessionsPanelProps) {
  const { chatId, chatName, activeSessionId, onSelect, collapsed, onToggleCollapsed } = props
  const { t } = useTranslation()

  const list = useQuery(sessionsListQueryOptions(chatId))
  const renameSession = useRenameSession(chatId)
  const deleteSessions = useDeleteSessions(chatId)

  const [filter, setFilter] = useState('')
  const [menu, setMenu] = useState<{ anchor: HTMLElement; session: Session } | null>(null)
  const [renameTarget, setRenameTarget] = useState<Session | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null)

  if (collapsed) {
    return (
      <Box
        component="aside"
        data-testid="sessions-panel"
        sx={{
          width: COLLAPSED_WIDTH,
          flexShrink: 0,
          borderRight: '1px solid',
          borderColor: 'divider',
          p: 1,
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <IconButton aria-label={t('chat.sessions.expand')} onClick={onToggleCollapsed}>
          <ChevronRightRoundedIcon />
        </IconButton>
      </Box>
    )
  }

  const sessions = list.data ?? []
  const needle = filter.trim().toLowerCase()
  const visible = sessions.filter((session) => session.name.toLowerCase().includes(needle))

  function openMenu(anchor: HTMLElement, session: Session): void {
    setMenu({ anchor, session })
  }

  function openRenameDialog(session: Session): void {
    renameSession.reset()
    setRenameTarget(session)
  }

  function openDeleteDialog(session: Session): void {
    deleteSessions.reset()
    setDeleteTarget(session)
  }

  /** Zamyka menu sesji i woła wybraną akcję na jej rozmowie. */
  function pick(action: (session: Session) => void): void {
    const session = menu?.session
    setMenu(null)
    if (session !== undefined) action(session)
  }

  function confirmDelete(): void {
    const session = deleteTarget
    if (session === null) return
    deleteSessions.mutate([session.id], {
      onSuccess: () => {
        // Usunięcie rozmowy, którą użytkownik ma otwartą, wraca do sesji tymczasowej.
        if (session.id === activeSessionId) onSelect(null)
      },
      onSettled: () => setDeleteTarget(null),
    })
  }

  let content: ReactNode
  if (list.isPending) {
    content = (
      <Stack spacing={1} sx={{ p: 1.5 }} data-testid="sessions-loading">
        {Array.from({ length: LOADING_ROWS }, (_, index) => (
          <Skeleton key={index} variant="rounded" height={36} />
        ))}
      </Stack>
    )
  } else if (list.isError) {
    content = (
      <Box sx={{ p: 1.5 }}>
        <QueryError message={t('chat.sessions.error')} onRetry={() => void list.refetch()} />
      </Box>
    )
  } else if (visible.length === 0) {
    // Pusta lista i puste (ale niepuste w danych) wyniki filtra mówią tym samym komponentem.
    const noSessions = sessions.length === 0
    content = (
      <Box sx={{ p: 1.5 }}>
        <EmptyState
          title={noSessions ? t('chat.sessions.emptyTitle') : t('chat.sessions.noResults')}
          description={noSessions ? t('chat.sessions.emptyDescription') : undefined}
        />
      </Box>
    )
  } else {
    content = (
      <List dense disablePadding>
        {visible.map((session) => {
          const isActive = session.id === activeSessionId
          return (
            <ListItem
              key={session.id}
              disablePadding
              secondaryAction={
                <IconButton
                  size="small"
                  aria-label={t('chat.sessions.menu', { name: session.name })}
                  onClick={(event) => openMenu(event.currentTarget, session)}
                >
                  <MoreVertIcon fontSize="small" />
                </IconButton>
              }
            >
              <ListItemButton
                selected={isActive}
                aria-current={isActive ? 'true' : undefined}
                onClick={() => onSelect(session.id)}
                // Rezerwa miejsca na absolutne ⋮ (wrapper `right: 16`, szerokość ~36 px).
                // Nadpisanie motywu (`MuiListItem` → `& .MuiButtonBase-root`) zbija MUI-ową
                // rezerwację 48 px do 8 px, więc wielokropek długiej nazwy wchodził pod ikonę
                // (QA E5-H8z-2 C7). Selektor z klasą — żeby przebić specyficzność motywu
                // (`& .MuiButtonBase-root`, również (0,2,0); sx wchodzi do arkusza później).
                sx={{ '&.MuiListItemButton-root': { pr: 9 } }}
              >
                <ListItemText primary={session.name} slotProps={{ primary: { noWrap: true } }} />
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>
    )
  }

  return (
    <Box
      component="aside"
      data-testid="sessions-panel"
      sx={{
        width: { xs: '100%', sm: SESSIONS_PANEL_WIDTH },
        flexShrink: 0,
        borderRight: '1px solid',
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Stack direction="row" spacing={1} sx={{ p: 1.5, alignItems: 'center' }}>
        <Avatar sx={{ width: 32, height: 32 }}>
          {(chatName ?? '').trim().charAt(0).toUpperCase()}
        </Avatar>
        <Typography variant="subtitle1" noWrap sx={{ flexGrow: 1, minWidth: 0 }}>
          {chatName}
        </Typography>
        <IconButton
          aria-label={t('chat.sessions.collapse')}
          onClick={onToggleCollapsed}
          sx={{ ml: 'auto' }}
        >
          <ChevronLeftRoundedIcon />
        </IconButton>
      </Stack>
      <Divider />
      <Stack direction="row" spacing={1} sx={{ px: 1.5, py: 1, alignItems: 'center' }}>
        <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
          {t('chat.sessions.count', { n: sessions.length })}
        </Typography>
        <IconButton aria-label={t('chat.sessions.new')} onClick={() => onSelect(null)}>
          <AddIcon />
        </IconButton>
      </Stack>

      <Box sx={{ px: 1.5, pb: 1 }}>
        <TextField
          fullWidth
          size="small"
          label={t('chat.sessions.search')}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </Box>

      {deleteSessions.error !== null ? (
        <Box sx={{ px: 1.5, pb: 1 }}>
          <Alert severity="error">
            {mutationError(deleteSessions.error, t('chat.sessions.deleteError'))}
          </Alert>
        </Box>
      ) : null}

      <Box sx={{ flexGrow: 1, overflowY: 'auto' }}>{content}</Box>

      <Menu
        anchorEl={menu?.anchor ?? null}
        open={menu !== null}
        onClose={() => setMenu(null)}
        slotProps={{ list: { 'aria-label': t('chat.sessions.menuLabel') } }}
      >
        <MenuItem onClick={() => pick(openRenameDialog)}>{t('chat.sessions.rename')}</MenuItem>
        <MenuItem onClick={() => pick(openDeleteDialog)}>{t('chat.sessions.delete')}</MenuItem>
      </Menu>

      {renameTarget !== null ? (
        <ChatNameDialog
          title={t('chat.sessions.rename')}
          submitLabel={t('chat.sessions.renameSubmit')}
          initialName={renameTarget.name}
          loading={renameSession.isPending}
          error={mutationError(renameSession.error, t('chat.sessions.renameError'))}
          onSubmit={(name) =>
            renameSession.mutate(
              { sessionId: renameTarget.id, name },
              { onSuccess: () => setRenameTarget(null) },
            )
          }
          onClose={() => setRenameTarget(null)}
        />
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        title={t('chat.sessions.deleteTitle')}
        message={t('chat.sessions.deleteMessage', { name: deleteTarget?.name ?? '' })}
        confirmLabel={t('chat.sessions.delete')}
        cancelLabel={t('common.cancel')}
        loading={deleteSessions.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </Box>
  )
}
