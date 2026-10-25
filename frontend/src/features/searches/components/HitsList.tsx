/**
 * Lista trafień wyszukiwania (kontrakt WP E4-4b §4): nazwa dokumentu jako przycisk otwierający
 * dokument, treść z podświetleniem BEZ `dangerouslySetInnerHTML` — `<em>`/`<mark>` z backendu
 * rozbijamy na części, obce tagi usuwamy (tekst zostaje). Gdy `highlight` jest pusty, bierzemy
 * `content` i podświetlamy słowa pytania (≥3 znaki, bez rozróżniania wielkości liter).
 */

import type { JSX } from 'react'
import { useTranslation } from 'react-i18next'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

import { EmptyState } from '../../../components/EmptyState'
import type { RetrievalChunk } from '../../datasets/retrieval/queries'

export type HitsListProps = {
  chunks: RetrievalChunk[]
  question: string
  onOpenDocument: (docId: string, docName: string) => void
}

export type TextPart = { text: string; match: boolean }

/** Znacznik inny niż `<em>`/`<mark>` (z atrybutami) — do usunięcia z tekstu. */
const OTHER_TAG = /<(?!\/?(?:em|mark)\b)[^>]*>/gi
/** Wyróżniony fragment zwrócony przez backend. */
const MATCHED_SPAN = /<(?:em|mark)>([\s\S]*?)<\/(?:em|mark)>/gi
/** Najkrótsze słowo pytania, które warto podświetlić. */
const MIN_QUESTION_WORD = 3

/** Dopina fragment, o ile nie jest pusty. */
function pushPart(parts: TextPart[], text: string, match: boolean): void {
  if (text !== '') parts.push({ text, match })
}

/** Dzieli `highlight` po `<em>…</em>`/`<mark>…</mark>`; pozostałe tagi usuwa, tekst zostaje. */
export function splitHighlight(highlight: string): TextPart[] {
  const cleaned = highlight.replace(OTHER_TAG, '')
  const parts: TextPart[] = []
  let cursor = 0

  for (const match of cleaned.matchAll(MATCHED_SPAN)) {
    const index = match.index ?? 0
    pushPart(parts, cleaned.slice(cursor, index), false)
    pushPart(parts, match[1] ?? '', true)
    cursor = index + match[0].length
  }
  pushPart(parts, cleaned.slice(cursor), false)

  return parts
}

/** Znaki o znaczeniu w wyrażeniu regularnym — słowa pytania wstawiamy do wzorca dosłownie. */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Dzieli treść po słowach pytania (≥3 znaki, bez rozróżniania wielkości liter). */
export function splitQuestion(content: string, question: string): TextPart[] {
  const words = question
    .split(/\s+/)
    .filter((word) => word.length >= MIN_QUESTION_WORD)
    .map(escapeRegExp)

  const parts: TextPart[] = []
  let cursor = 0

  if (words.length > 0) {
    for (const match of content.matchAll(new RegExp(words.join('|'), 'gi'))) {
      const index = match.index ?? 0
      pushPart(parts, content.slice(cursor, index), false)
      pushPart(parts, match[0], true)
      cursor = index + match[0].length
    }
  }
  pushPart(parts, content.slice(cursor), false)

  return parts
}

/** Treść chunku: części `match` jako `<mark>`, reszta jako zwykły tekst. */
function ChunkContent(props: { chunk: RetrievalChunk; question: string }): JSX.Element {
  const { chunk, question } = props
  const highlight = chunk.highlight ?? ''
  const parts =
    highlight === '' ? splitQuestion(chunk.content, question) : splitHighlight(highlight)

  return (
    <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
      {parts.map((part, index) =>
        part.match ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </Typography>
  )
}

/** Pojedyncze trafienie: przycisk z nazwą dokumentu i treść z podświetleniem. */
function HitItem(props: {
  chunk: RetrievalChunk
  question: string
  onOpenDocument: (docId: string, docName: string) => void
}): JSX.Element {
  const { chunk, question, onOpenDocument } = props
  const { t } = useTranslation()

  return (
    <Card variant="outlined" data-testid="search-hit">
      <CardContent>
        <Stack spacing={1}>
          <Button
            size="small"
            sx={{ alignSelf: 'flex-start' }}
            aria-label={t('searches.hits.openDocument', { name: chunk.document_keyword })}
            onClick={() => onOpenDocument(chunk.document_id, chunk.document_keyword)}
          >
            {chunk.document_keyword}
          </Button>
          <ChunkContent chunk={chunk} question={question} />
        </Stack>
      </CardContent>
    </Card>
  )
}

export function HitsList(props: HitsListProps): JSX.Element {
  const { chunks, question, onOpenDocument } = props
  const { t } = useTranslation()

  if (chunks.length === 0) return <EmptyState title={t('searches.hits.empty')} />

  return (
    <Stack spacing={2} data-testid="search-hits">
      {chunks.map((chunk) => (
        <HitItem key={chunk.id} chunk={chunk} question={question} onOpenDocument={onOpenDocument} />
      ))}
    </Stack>
  )
}
