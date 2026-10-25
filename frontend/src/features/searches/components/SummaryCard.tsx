/**
 * Karta „Podsumowanie AI” (kontrakt WP E4-4b §4): markdown odpowiedzi z cytowaniami, zwijany
 * do 208 px z przyciskiem rozwiń/zwiń. Treść idzie przez `MarkdownWithCitations`, więc znaczniki
 * `[ID:n]` stają się chipami otwierającymi dokumenty.
 *
 * Stany strumienia: pusty tekst w trakcie streamu pokazuje „Generowanie…”, a `phase === 'error'`
 * dokłada `Alert` z komunikatem błędu. Przycisk zwijania istnieje tylko wtedy, gdy jest co zwijać
 * (niepusta odpowiedź).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { StreamState } from '../../chat-stream/reducer'
import type { StreamPhase } from '../../chats/stream/useChatStream'
import { MarkdownWithCitations } from '../../chats/messages/MarkdownWithCitations'

export type SummaryCardProps = {
  phase: StreamPhase
  state: StreamState
  onOpenDocument: (docId: string, docName: string) => void
}

/** Wysokość zwiniętego podsumowania w pikselach (08 §7.8). */
const COLLAPSED_MAX_HEIGHT = 208

export function SummaryCard(props: SummaryCardProps): JSX.Element {
  const { phase, state, onOpenDocument } = props
  const { t } = useTranslation()

  const [expanded, setExpanded] = useState(false)

  const hasAnswer = state.answer !== ''
  const loading = phase === 'streaming' && !hasAnswer

  return (
    <Card data-testid="summary-card">
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {t('searches.summary.title')}
        </Typography>

        {phase === 'error' ? (
          <Alert severity="error" sx={{ mb: 1 }}>
            {state.error === null
              ? t('searches.summary.error')
              : `${t('searches.summary.error')} ${state.error}`}
          </Alert>
        ) : null}

        {loading ? (
          <Typography color="text.secondary">{t('searches.summary.loading')}</Typography>
        ) : (
          <Box
            data-testid="summary-content"
            sx={expanded ? undefined : { maxHeight: COLLAPSED_MAX_HEIGHT, overflow: 'hidden' }}
          >
            <MarkdownWithCitations
              text={state.answer}
              citations={state.citations}
              onOpenDocument={onOpenDocument}
            />
          </Box>
        )}

        {hasAnswer ? (
          <Button
            size="small"
            data-testid="summary-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? t('searches.summary.collapse') : t('searches.summary.expand')}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}
