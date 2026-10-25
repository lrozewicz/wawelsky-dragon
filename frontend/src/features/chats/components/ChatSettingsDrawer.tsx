/**
 * Szuflada ustawień czatu (08 §7.7 p. 3, §8.2): `Drawer anchor="right"` (440 px, pełna szerokość
 * poniżej `sm`); treść to `ChatSettingsForm` (wydzielony plik, remontowany per otwarcie przez
 * `key={chatId}`). Zamknięcie przy niezapisanych zmianach (Esc, tło, „Anuluj”, ✕) pyta
 * „Odrzucić zmiany?” — wspólny `useDiscardGuard` (SC-V12-07); „brudny” żyje w formularzu,
 * więc tylko on podnosi fakt zmiany do szuflady.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import CloseIcon from '@mui/icons-material/Close'
import Alert from '@mui/material/Alert'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { useDiscardGuard } from '../../../components/useDiscardGuard'
import { chatQueryOptions } from '../queries'
import { ChatSettingsForm } from './ChatSettingsForm'

export type ChatSettingsDrawerProps = {
  chatId: string
  open: boolean
  onClose: () => void
  /** Otwarcie od chipa filtra (SC-E67-06 k5): sekcja filtra rozwinięta i w widoku. */
  focusFilter?: boolean
}

export function ChatSettingsDrawer(props: ChatSettingsDrawerProps) {
  const { chatId, open, onClose, focusFilter = false } = props
  const { t } = useTranslation()
  const chat = useQuery({ ...chatQueryOptions(chatId), enabled: open })

  // Strażnik niezapisanych zmian (SC-V12-07): Esc/tło/„Anuluj”/✕ przy brudnym formularzu pyta
  // „Odrzucić zmiany?”. Stan „brudny” podnosi formularz (żyje poniżej); zamknięcie szuflady
  // zeruje go od razu (korekta podczas renderu, wzorzec: `SearchSettingsDrawer`) — ponowne
  // otwarcie startuje czysto, zanim formularz się zamontuje i zgłosi rzeczywisty stan.
  const [dirty, setDirty] = useState(false)
  const [lastOpen, setLastOpen] = useState(open)
  if (lastOpen !== open) {
    setLastOpen(open)
    setDirty(false)
  }
  const { requestClose, dialog } = useDiscardGuard({ dirty, onClose, context: 'chat', open })

  let content: ReactNode = null
  if (open) {
    if (chat.data !== undefined) {
      content = (
        <ChatSettingsForm
          key={chatId}
          chatId={chatId}
          chat={chat.data}
          onClose={onClose}
          onCancel={requestClose}
          onDirtyChange={setDirty}
          focusFilter={focusFilter}
        />
      )
    } else if (chat.isError) {
      content = (
        <Alert severity="error" sx={{ m: 2 }}>
          {t('chat.settings.loadError')}
        </Alert>
      )
    } else {
      content = (
        <Stack spacing={2} sx={{ p: 2 }}>
          <Skeleton variant="rounded" height={56} />
          <Skeleton variant="rounded" height={56} />
          <Skeleton variant="rounded" height={120} />
        </Stack>
      )
    }
  }

  return (
    <>
      {/* min(…, 100vw) — szuflada mieści się w całości także na wąskim ekranie (R-UI-01). */}
      <Drawer
        anchor="right"
        open={open}
        onClose={requestClose}
        // Otwarcie od chipa filtra to „skok” do sekcji — bez wsuwania, żeby ekran od razu był ustalony.
        transitionDuration={focusFilter ? 0 : undefined}
        slotProps={{
          paper: { sx: { width: { xs: 'min(100%, 100vw)', sm: 'min(440px, 100vw)' } } },
        }}
      >
        <Stack sx={{ height: '100%' }}>
          {/* Nagłówek z ✕ (SC-E5-H8d-02: „zamyka ✕ i Esc”; QA E5-H8z-3 D1) — zamyka przez
              strażnika (przy zmianach pyta „Odrzucić zmiany?”, SC-V12-07). */}
          <Stack
            direction="row"
            sx={{ p: 2, pb: 1, alignItems: 'center', justifyContent: 'space-between' }}
          >
            <Typography variant="h6">{t('chat.settings.title')}</Typography>
            <IconButton aria-label={t('common.close')} onClick={requestClose}>
              <CloseIcon />
            </IconButton>
          </Stack>
          {content}
        </Stack>
      </Drawer>
      {dialog}
    </>
  )
}
