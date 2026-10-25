/**
 * Pole pytania w obszarze rozmowy (kontrakt WP E3-5b §T6a): Enter wysyła, Shift+Enter wstawia nową linię,
 * a przycisk zmienia się w Stop, dopóki trwa stream. Enter w trakcie kompozycji IME zatwierdza znak
 * w edytorze metody wejścia, więc nie wysyła wiadomości. Pusty tekst (po trim) nie leci do `onSend`.
 */

import * as React from 'react'
import { useState } from 'react'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import SendOutlinedIcon from '@mui/icons-material/SendOutlined'
import StopOutlinedIcon from '@mui/icons-material/StopOutlined'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

export type ChatInputProps = {
  streaming: boolean
  disabled?: boolean
  onSend: (text: string) => void
  onStop: () => void
  /** Opisy warunków filtra metadanych czatu (chipy nad polem); klik otwiera edycję filtra. */
  filterLabels?: string[]
  onEditFilter?: () => void
}

export function ChatInput(props: ChatInputProps) {
  const { streaming, disabled = false, onSend, onStop, filterLabels = [], onEditFilter } = props
  const { t } = useTranslation()
  const [text, setText] = useState('')

  const trimmed = text.trim()
  const canSend = trimmed !== '' && !disabled

  const send = () => {
    if (!canSend) return
    onSend(trimmed)
    setText('')
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (streaming) return
    send()
  }

  return (
    <Box>
      {filterLabels.length > 0 ? (
        // Chipy aktywnego filtra (SC-E67-06 k5): przyciski dostępne z klawiatury, klik = edycja filtra.
        <Stack
          role="group"
          aria-label={t('chat.input.filterChip.group')}
          direction="row"
          useFlexGap
          sx={{ flexWrap: 'wrap', gap: 1, px: 2, pt: 1 }}
        >
          {filterLabels.map((label, index) => (
            <Chip
              key={index}
              size="small"
              label={label}
              title={label}
              // Ikona edycji: chip wygląda na klikalny (klik otwiera edycję filtra).
              icon={<EditOutlinedIcon />}
              onClick={onEditFilter}
              sx={{
                maxWidth: '100%',
                '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' },
              }}
            />
          ))}
        </Stack>
      ) : null}
      <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-end', p: 2, pb: 1.5 }}>
        {/* pb 1.5 zamiast 2 — pole pytania przy dolnej krawędzi okna (SC-E5-H8d-06: odstęp
          od dołu ≤ 24 px; po paddingu pola i ramce zostaje 21 px zamiast 25). */}
        <TextField
          fullWidth
          multiline
          maxRows={8}
          placeholder={t('chat.input.placeholder')}
          disabled={disabled}
          value={text}
          onChange={(event) => setText(event.target.value)}
          slotProps={{ htmlInput: { onKeyDown: handleKeyDown } }}
        />
        {streaming ? (
          <IconButton aria-label={t('chat.input.stop')} disabled={disabled} onClick={onStop}>
            <StopOutlinedIcon />
          </IconButton>
        ) : (
          <IconButton aria-label={t('chat.input.send')} disabled={!canSend} onClick={send}>
            <SendOutlinedIcon />
          </IconButton>
        )}
      </Stack>
    </Box>
  )
}
