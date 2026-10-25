/**
 * Wiadomość asystenta (kontrakt WP E3-5b §T5b): akordeon „Myślenie…”, treść z cytowaniami
 * (`MarkdownWithCitations`), chipy dokumentów z `docAggs`, pasek akcji (Kopiuj, 👍, 👎,
 * Wygeneruj ponownie) i stany `aborted`/`error`.
 * Akordeon jest rozwinięty tylko w trakcie streamu z niepustym myśleniem; po zakończeniu zwija się
 * sam, ale użytkownik może go otworzyć ręcznie (dalsze napisy nie rozwijają go ponownie).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import RefreshIcon from '@mui/icons-material/Refresh'
import ThumbDownIcon from '@mui/icons-material/ThumbDown'
import ThumbUpIcon from '@mui/icons-material/ThumbUp'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import Snackbar from '@mui/material/Snackbar'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { ChatMessage } from '../sessions/chatMessages'

import { copyToClipboard } from '../../settings/api/copyToClipboard'
import { copyErrorSx } from '../../settings/api/copyErrorSx'
import { FeedbackDialog } from './FeedbackDialog'
import { MarkdownWithCitations } from './MarkdownWithCitations'

export type AssistantMessageProps = {
  message: ChatMessage
  onOpenDocument: (docId: string, docName: string) => void
  onFeedback: (message: ChatMessage, thumbup: boolean, feedback: string | null) => void
  /** Tylko przy ostatniej wiadomości asystenta; brak = akcja ukryta. */
  onRegenerate?: () => void
}

export function AssistantMessage(props: AssistantMessageProps): JSX.Element {
  const { message, onOpenDocument, onFeedback, onRegenerate } = props
  const { t } = useTranslation()

  const [copied, setCopied] = useState(false)
  // Porażka kopiowania (SC-E5-H9-08): komunikat w TREŚCI wiadomości (nie w portalu Snackbara),
  // bo ma być widoczny obok zaznaczonego tekstu do ręcznej kopii (Ctrl+C).
  const [copyFailed, setCopyFailed] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  // Rozwinięty tylko w trakcie streamu z niepustym myśleniem; zmiana klucza przy zejściu ze stanu
  // „streaming” montuje akordeon od nowa (zwinięty), a użytkownik może go potem otworzyć ręcznie.
  const thinkingWhileStreaming = message.status === 'streaming' && message.thinking !== ''

  // Prologue nie ma akcji poza Kopiuj — nie ma go czemu oceniać ani powtarzać.
  const isGreeting = message.key === 'greeting'

  // Kopiowanie przez `copyToClipboard` (brief E6-2 T9): działa też bez `navigator.clipboard`
  // (HTTP); „Skopiowano” wyłącznie po udanej kopii, porażka dostaje czytelny komunikat.
  async function handleCopy(): Promise<void> {
    const ok = await copyToClipboard(message.content)
    setCopied(ok)
    setCopyFailed(!ok)
  }

  return (
    <Box
      component="article"
      aria-label={t('chat.msg.assistant')}
      data-testid="message-assistant"
      sx={{ maxWidth: '100%' }}
    >
      <Stack spacing={1}>
        {message.thinking === '' ? null : (
          <Accordion
            key={thinkingWhileStreaming ? 'thinking-live' : 'thinking-done'}
            disableGutters
            variant="outlined"
            defaultExpanded={thinkingWhileStreaming}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" color="text.secondary">
                {t('chat.msg.thinking')}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {message.thinking}
              </Typography>
            </AccordionDetails>
          </Accordion>
        )}

        {message.status === 'aborted' ? (
          <Chip size="small" label={t('chat.msg.aborted')} sx={{ alignSelf: 'flex-start' }} />
        ) : null}

        {message.status === 'error' ? (
          <Alert severity="error">{message.error ?? t('chat.msg.error')}</Alert>
        ) : null}

        <MarkdownWithCitations
          text={message.content}
          citations={message.citations}
          onOpenDocument={onOpenDocument}
        />

        {message.docAggs.length === 0 ? null : (
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {message.docAggs.map((docAgg) => (
              <Chip
                key={docAgg.docId}
                component="button"
                size="small"
                label={t('chat.msg.docChip', { name: docAgg.docName, count: docAgg.count })}
                onClick={() => onOpenDocument(docAgg.docId, docAgg.docName)}
              />
            ))}
          </Stack>
        )}

        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <Tooltip title={t('chat.msg.copy')}>
            <IconButton
              size="small"
              aria-label={t('chat.msg.copy')}
              onClick={() => void handleCopy()}
            >
              <ContentCopyIcon fontSize="small" />
            </IconButton>
          </Tooltip>

          {isGreeting ? null : (
            <>
              <Tooltip title={t('chat.msg.thumbUp')}>
                <IconButton
                  size="small"
                  aria-label={t('chat.msg.thumbUp')}
                  aria-pressed={message.thumbup === true}
                  color={message.thumbup === true ? 'primary' : 'default'}
                  onClick={() => onFeedback(message, true, null)}
                >
                  <ThumbUpIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title={t('chat.msg.thumbDown')}>
                <IconButton
                  size="small"
                  aria-label={t('chat.msg.thumbDown')}
                  aria-pressed={message.thumbup === false}
                  color={message.thumbup === false ? 'primary' : 'default'}
                  onClick={() => setFeedbackOpen(true)}
                >
                  <ThumbDownIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              {onRegenerate === undefined ? null : (
                <Tooltip title={t('chat.msg.regenerate')}>
                  <IconButton
                    size="small"
                    aria-label={t('chat.msg.regenerate')}
                    onClick={onRegenerate}
                  >
                    <RefreshIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            </>
          )}
        </Stack>

        {copyFailed ? (
          <Typography
            variant="body2"
            sx={copyErrorSx}
            role="alert"
            data-testid="message-copy-error"
          >
            {t('settings.common.copyFailed')}
          </Typography>
        ) : null}
      </Stack>

      <Snackbar
        open={copied}
        autoHideDuration={2000}
        message={t('chat.msg.copied')}
        onClose={() => setCopied(false)}
      />

      {feedbackOpen ? (
        <FeedbackDialog
          onClose={() => setFeedbackOpen(false)}
          onSubmit={(feedback) => {
            setFeedbackOpen(false)
            onFeedback(message, false, feedback)
          }}
        />
      ) : null}
    </Box>
  )
}
