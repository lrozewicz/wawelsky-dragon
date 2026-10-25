/**
 * Wiadomość użytkownika (kontrakt WP E3-5b §T5b): dymek wyrównany do prawej, bez akcji.
 * Treść idzie jako czysty tekst (bez markdownu i cytowań) — nowe linie zachowuje `pre-wrap`.
 */

import type { JSX } from 'react'
import Box from '@mui/material/Box'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { ChatMessage } from '../sessions/chatMessages'

export type UserMessageProps = { message: ChatMessage }

export function UserMessage(props: UserMessageProps): JSX.Element {
  const { message } = props
  const { t } = useTranslation()

  return (
    <Box
      component="article"
      aria-label={t('chat.msg.user')}
      data-testid="message-user"
      sx={{ display: 'flex', justifyContent: 'flex-end' }}
    >
      <Paper variant="outlined" sx={{ p: 1.5, maxWidth: '80%' }}>
        <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {message.content}
        </Typography>
      </Paper>
    </Box>
  )
}
