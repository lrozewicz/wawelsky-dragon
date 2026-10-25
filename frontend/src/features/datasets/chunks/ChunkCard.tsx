/**
 * Karta pojedynczego chunku (kontrakt WP E3-4a §ChunkCard): zaznaczenie, typ, treść
 * (markdown albo tabela HTML) i przełącznik dostępności. Czysto prezentacyjna — stan i mutacje
 * należą do panelu (T4). Zdarzenia myszy na kontrolkach zatrzymują propagację, żeby klik w nie
 * nie wchodził w podgląd karty; klawiatura działa tylko wtedy, gdy fokus jest na samej karcie.
 */

import type { JSX, KeyboardEvent } from 'react'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import Box from '@mui/material/Box'
import Card from '@mui/material/Card'
import Checkbox from '@mui/material/Checkbox'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { HtmlTable } from './HtmlTable'
import type { Chunk } from './queries'

export type ChunkCardProps = {
  chunk: Chunk
  selected: boolean
  /** true = „Pełny tekst”, false = „Skrócony” (przycięcie do 4 linii). */
  expanded: boolean
  /** Wybrany do podglądu dokumentu (obramowanie). */
  active: boolean
  onToggleSelect: (id: string) => void
  onToggleAvailable: (id: string, available: boolean) => void
  onActivate: (chunk: Chunk) => void
  onEdit: (chunk: Chunk) => void
}

/** Klucz etykiety typu; pusty albo nieznany `doc_type_kwd` traktujemy jak zwykły tekst. */
const TYPE_KEYS = {
  text: 'chunks.type.text',
  table: 'chunks.type.table',
  image: 'chunks.type.image',
} as const

function typeKey(docTypeKwd: string): string {
  return docTypeKwd in TYPE_KEYS ? TYPE_KEYS[docTypeKwd as keyof typeof TYPE_KEYS] : TYPE_KEYS.text
}

export function ChunkCard(props: ChunkCardProps): JSX.Element {
  const { chunk, selected, expanded, active } = props
  const { onToggleSelect, onToggleAvailable, onActivate, onEdit } = props
  const { t } = useTranslation()

  const isTable = chunk.doc_type_kwd === 'table' || chunk.content.startsWith('<table')

  function handleKeyDown(event: KeyboardEvent<HTMLElement>): void {
    // Karta jest kontenerem — reakcja tylko na klawisz na niej samej, nie na kontrolkach w środku.
    if (event.target !== event.currentTarget) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    // Spacja przewija stronę — przy przełączaniu zaznaczenia trzeba ją wyłączyć.
    if (event.key === ' ') event.preventDefault()
    onToggleSelect(chunk.id)
  }

  return (
    <Card
      variant="outlined"
      role="group"
      tabIndex={0}
      data-testid={`chunk-card-${chunk.id}`}
      onClick={() => {
        onActivate(chunk)
      }}
      onDoubleClick={() => {
        onEdit(chunk)
      }}
      onKeyDown={handleKeyDown}
      sx={{
        // Długa lista bez wirtualizacji (DEC-142) — przeglądarka pomija koszt ukrytych kart.
        contentVisibility: 'auto',
        containIntrinsicSize: 'auto 120px',
        cursor: 'pointer',
        borderColor: active ? 'primary.main' : undefined,
      }}
    >
      <Stack direction="row" spacing={1} sx={{ p: 1, alignItems: 'flex-start' }}>
        <Checkbox
          checked={selected}
          data-testid={`chunk-select-${chunk.id}`}
          slotProps={{ input: { 'aria-label': t('chunks.card.select') } }}
          onClick={(event) => {
            event.stopPropagation()
          }}
          onChange={() => {
            onToggleSelect(chunk.id)
          }}
        />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
            <Chip size="small" color="default" label={t(typeKey(chunk.doc_type_kwd))} />
            <Box sx={{ flex: 1 }} />
            <Switch
              checked={chunk.available}
              data-testid={`chunk-switch-${chunk.id}`}
              slotProps={{ input: { 'aria-label': t('chunks.card.available') } }}
              onClick={(event) => {
                event.stopPropagation()
              }}
              onChange={() => {
                onToggleAvailable(chunk.id, !chunk.available)
              }}
            />
            <IconButton
              data-testid={`chunk-edit-${chunk.id}`}
              aria-label={t('chunks.card.edit')}
              onClick={(event) => {
                event.stopPropagation()
                onEdit(chunk)
              }}
            >
              <EditOutlinedIcon />
            </IconButton>
          </Stack>
          <Box
            sx={{
              opacity: chunk.available ? 1 : 0.6,
              ...(expanded
                ? {}
                : {
                    display: '-webkit-box',
                    WebkitBoxOrient: 'vertical',
                    WebkitLineClamp: 4,
                    overflow: 'hidden',
                  }),
            }}
          >
            {isTable ? (
              <HtmlTable html={chunk.content} />
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                {chunk.content}
              </ReactMarkdown>
            )}
          </Box>
          {chunk.important_keywords.length > 0 ? (
            <Stack
              direction="row"
              aria-label={t('chunks.card.keywords')}
              sx={{ flexWrap: 'wrap', gap: 0.5, mt: 1 }}
            >
              {chunk.important_keywords.map((keyword) => (
                <Chip key={keyword} size="small" variant="outlined" label={keyword} />
              ))}
            </Stack>
          ) : null}
        </Box>
      </Stack>
    </Card>
  )
}
