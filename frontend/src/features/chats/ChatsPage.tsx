/**
 * Strona `/chats` (08 §7.6): lista kart czatów, tworzenie (tylko nazwa → `/chat/:id`),
 * zmiana nazwy z menu karty i usuwanie z potwierdzeniem.
 * `?isCreate=true` (wejście z Home) otwiera okno tworzenia; jego zamknięcie czyści parametr.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import AddIcon from '@mui/icons-material/Add'
import ChatBubbleOutlineRoundedIcon from '@mui/icons-material/ChatBubbleOutlineRounded'
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

import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import PageContainer from '../../components/PageContainer'
import { QueryError } from '../../components/QueryError'
import { resolveLanguage } from '../../i18n'
import { formatDate } from '../../lib/format'

import { ChatNameDialog } from './components/ChatNameDialog'
import { chatsListQueryOptions, useCreateChat, useDeleteChats, useUpdateChat } from './queries'
import type { ChatListItem } from './queries'
import { mutationError } from './settings/tabs'

/** Liczba szkieletów w stanie ładowania (pełny rząd na najszerszym breakpoincie). */
const SKELETON_COUNT = 8

/** Trasa `/chat/$id` powstaje w T6 tego samego WP — do tego czasu adres budujemy jako href. */
function chatHref(id: string): string {
  return `/chat/${id}`
}

type NameDialogState = { mode: 'create' } | { mode: 'rename'; chat: ChatListItem }

function CreateChatDialog(props: { onCreated: (id: string) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const createChat = useCreateChat()

  return (
    <ChatNameDialog
      // Tytuł wg makiety SC-V13-10 (QA MINOR-3); przycisk strony zostaje „Utwórz czat”.
      title={t('chats.createTitle')}
      submitLabel={t('chats.createSubmit')}
      // SC-V13-10: okno tworzenia ma pole „Bazy wiedzy (opcjonalnie)”; zmiana nazwy — nie.
      showDatasets
      loading={createChat.isPending}
      error={mutationError(createChat.error, t('chats.createError'), t)}
      onSubmit={(name, datasetIds) =>
        // Domyślne teksty nowego czatu w języku UI (K4/DEC-306; K20 §5 p. 3/DEC-358): EN = teksty
        // upstream, PL = polskie odpowiedniki. `dataset_ids` trafia do body tylko gdy wybrano bazy.
        createChat.mutate(
          {
            name,
            description: t('chat.defaultDescription'),
            prologue: t('chat.defaultPrologue'),
            emptyResponse: t('chat.defaultEmptyResponse'),
            datasetIds,
          },
          { onSuccess: (chat) => props.onCreated(chat.id) },
        )
      }
      onClose={props.onClose}
    />
  )
}

function RenameChatDialog(props: { chat: ChatListItem; onClose: () => void }) {
  const { t } = useTranslation()
  const updateChat = useUpdateChat(props.chat.id)

  return (
    <ChatNameDialog
      title={t('chats.rename')}
      submitLabel={t('chats.renameSubmit')}
      initialName={props.chat.name}
      loading={updateChat.isPending}
      error={mutationError(updateChat.error, t('chats.renameError'), t)}
      onSubmit={(name) => updateChat.mutate({ name }, { onSuccess: props.onClose })}
      onClose={props.onClose}
    />
  )
}

function ChatCard(props: { chat: ChatListItem; onMenuOpen: (anchor: HTMLElement) => void }) {
  const { t, i18n } = useTranslation()
  const { chat } = props

  return (
    <Card data-testid="chat-card" sx={{ position: 'relative', height: '100%' }}>
      <CardActionArea component="a" href={chatHref(chat.id)} sx={{ height: '100%' }}>
        <Stack spacing={1} sx={{ p: 2, pr: 6, height: '100%', alignItems: 'flex-start' }}>
          <Avatar>{chat.name.trim().charAt(0).toUpperCase()}</Avatar>
          <Typography variant="subtitle1" noWrap sx={{ width: '100%' }}>
            {chat.name}
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {chat.description}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {formatDate(chat.update_time, resolveLanguage(i18n.language))}
          </Typography>
        </Stack>
      </CardActionArea>
      <IconButton
        aria-label={t('chats.menuLabel', { name: chat.name })}
        onClick={(event) => props.onMenuOpen(event.currentTarget)}
        sx={{ position: 'absolute', top: 8, right: 8 }}
      >
        <MoreVertIcon />
      </IconButton>
    </Card>
  )
}

export function ChatsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  // Trasa jest cienka, a strona nie ma propsów (kontrakt §5/§7) — parametr czytamy sami.
  const search = useSearch({ strict: false })
  const isCreate = search.isCreate === true

  const chats = useQuery(chatsListQueryOptions())
  const deleteChats = useDeleteChats()

  // `?isCreate=true` z Home otwiera okno tworzenia już przy wejściu na stronę.
  const [nameDialog, setNameDialog] = useState<NameDialogState | null>(
    isCreate ? { mode: 'create' } : null,
  )
  const [menu, setMenu] = useState<{ anchor: HTMLElement; chat: ChatListItem } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<ChatListItem | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  function closeNameDialog(): void {
    setNameDialog(null)
    // Zamknięcie okna kończy także wejście z parametrem — adres wraca do `/chats`.
    if (isCreate) void navigate({ to: '/chats', search: {} })
  }

  function confirmDelete(): void {
    const chat = pendingDelete
    if (chat === null) return
    deleteChats.mutate([chat.id], {
      onSettled: () => setPendingDelete(null),
      onError: (error) => setDeleteError(mutationError(error, t('chats.deleteError'), t)),
    })
  }

  function openDelete(chat: ChatListItem): void {
    setDeleteError(null)
    setPendingDelete(chat)
  }

  const createButton = (
    <Button
      variant="contained"
      startIcon={<AddIcon />}
      onClick={() => setNameDialog({ mode: 'create' })}
    >
      {t('chats.create')}
    </Button>
  )

  let content: ReactNode
  if (chats.isPending) {
    content = (
      <Grid container spacing={2} data-testid="chats-loading">
        {Array.from({ length: SKELETON_COUNT }, (_, index) => (
          <Grid key={index} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <Skeleton variant="rounded" height={180} />
          </Grid>
        ))}
      </Grid>
    )
  } else if (chats.isError) {
    content = <QueryError message={t('chats.error')} onRetry={() => void chats.refetch()} />
  } else if (chats.data.length === 0) {
    content = (
      <EmptyState
        icon={<ChatBubbleOutlineRoundedIcon fontSize="large" />}
        title={t('chats.emptyTitle')}
        description={t('chats.emptyDescription')}
        action={createButton}
      />
    )
  } else {
    content = (
      <Grid container spacing={2}>
        {chats.data.map((chat) => (
          <Grid key={chat.id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
            <ChatCard chat={chat} onMenuOpen={(anchor) => setMenu({ anchor, chat })} />
          </Grid>
        ))}
      </Grid>
    )
  }

  return (
    // SC-E5-H9-06: przy pustej liście (i w trakcie ładowania) jedyną akcją tworzenia jest
    // przycisk w stanie pustym — przycisk w nagłówku pojawia się dopiero z kartami czatów.
    <PageContainer
      title={t('chats.title')}
      actions={chats.data !== undefined && chats.data.length > 0 ? createButton : null}
    >
      <Stack spacing={2}>
        {deleteError !== null ? <Alert severity="error">{deleteError}</Alert> : null}
        {content}
      </Stack>

      {menu !== null ? (
        <Menu anchorEl={menu.anchor} open onClose={() => setMenu(null)}>
          <MenuItem
            onClick={() => {
              setMenu(null)
              setNameDialog({ mode: 'rename', chat: menu.chat })
            }}
          >
            {t('chats.rename')}
          </MenuItem>
          <MenuItem
            onClick={() => {
              setMenu(null)
              openDelete(menu.chat)
            }}
          >
            {t('chats.delete')}
          </MenuItem>
        </Menu>
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('chats.deleteTitle')}
        message={t('chats.deleteMessage', { name: pendingDelete?.name ?? '' })}
        confirmLabel={t('chats.delete')}
        cancelLabel={t('common.cancel')}
        loading={deleteChats.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      {nameDialog !== null && nameDialog.mode === 'rename' ? (
        <RenameChatDialog chat={nameDialog.chat} onClose={closeNameDialog} />
      ) : null}
      {nameDialog !== null && nameDialog.mode === 'create' ? (
        <CreateChatDialog
          onClose={closeNameDialog}
          onCreated={(id) => void navigate({ href: chatHref(id) })}
        />
      ) : null}
    </PageContainer>
  )
}
