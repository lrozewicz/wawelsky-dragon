/**
 * Karta „Wyniki” testu retrievalu (kontrakt WP E3-4b §R/ResultsCard.tsx): nagłówek „Łącznie N”,
 * filtr dokumentów z licznikami z `doc_aggs`, karty wyników z chipami procentów i bezpiecznym
 * podświetleniem, dwa puste stany oraz paginacja, gdy liczba wyników przekracza `pageSize`.
 * Podświetlenie idzie przez `parseHighlight` (bez `dangerouslySetInnerHTML`).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { useTranslation } from 'react-i18next'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Checkbox from '@mui/material/Checkbox'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import FormControlLabel from '@mui/material/FormControlLabel'
import Pagination from '@mui/material/Pagination'
import Popover from '@mui/material/Popover'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

import { EmptyState } from '../../../components/EmptyState'

import type { DocAgg, RetrievalChunk, RetrievalResult } from './queries'
import { formatPercent, parseHighlight } from './schema'

export type ResultsCardProps = {
  result: RetrievalResult | undefined
  loading: boolean
  allDocs: DocAgg[]
  selectedDocIds: string[]
  page: number
  pageSize: number
  /** Filtr metadanych był aktywny w ostatnim uruchomieniu (SC-E6-1b-06 krok 2). */
  filterActive: boolean
  onDocsChange: (ids: string[]) => void
  onPageChange: (page: number) => void
}

/** Treść chunku z wyróżnieniami: część `match` jako `<mark>`, reszta jako zwykły tekst. */
function ChunkContent(props: { chunk: RetrievalChunk }): JSX.Element {
  const parts = parseHighlight(props.chunk.highlight ?? props.chunk.content)

  return (
    <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
      {parts.map((part, index) =>
        part.match ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </Typography>
  )
}

/** Pojedynczy wynik: nazwa dokumentu, chipy podobieństw i treść z podświetleniem. */
function ResultItem(props: { chunk: RetrievalChunk }): JSX.Element {
  const { chunk } = props
  const { t } = useTranslation()

  return (
    <Card variant="outlined" data-testid="retrieval-result">
      <CardContent>
        <Stack spacing={1}>
          <Typography variant="caption" color="text.secondary">
            {chunk.document_keyword}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            <Chip
              size="small"
              color="primary"
              data-testid="retrieval-chip-hybrid"
              label={`${t('retrieval.chip.hybrid')} ${formatPercent(chunk.similarity)}%`}
            />
            <Chip
              size="small"
              label={`${t('retrieval.chip.term')} ${formatPercent(chunk.term_similarity)}%`}
            />
            <Chip
              size="small"
              label={`${t('retrieval.chip.vector')} ${formatPercent(chunk.vector_similarity)}%`}
            />
          </Stack>
          <ChunkContent chunk={chunk} />
        </Stack>
      </CardContent>
    </Card>
  )
}

export function ResultsCard(props: ResultsCardProps): JSX.Element {
  const {
    result,
    loading,
    allDocs,
    selectedDocIds,
    page,
    pageSize,
    filterActive,
    onDocsChange,
    onPageChange,
  } = props
  const { t } = useTranslation()
  // Kotwica popovera filtra (element przycisku) — `null` = zamknięty.
  const [filterAnchor, setFilterAnchor] = useState<HTMLElement | null>(null)

  /** Nowa lista wybranych dokumentów po zaznaczeniu/odznaczeniu jednego z nich. */
  const toggleDoc = (docId: string, checked: boolean): string[] =>
    checked ? [...selectedDocIds, docId] : selectedDocIds.filter((id) => id !== docId)

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {t('retrieval.results.title')}
        </Typography>

        {result === undefined ? null : (
          <Stack
            direction="row"
            spacing={2}
            sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2 }}
          >
            <Typography data-testid="retrieval-total">
              {t('retrieval.results.total', { count: result.total })}
            </Typography>
            <Button
              size="small"
              data-testid="retrieval-doc-filter"
              onClick={(event) => setFilterAnchor(event.currentTarget)}
            >
              {`${t('retrieval.results.filter')} (${selectedDocIds.length})`}
            </Button>
          </Stack>
        )}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : result === undefined ? (
          <EmptyState title={t('retrieval.results.notRun')} />
        ) : result.chunks.length === 0 ? (
          <Box data-testid="retrieval-empty">
            <EmptyState
              // Aktywny filtr metadanych dostaje własny komunikat (SC-E6-1b-06 krok 2):
              // wykluczenie zamiast ogólnego „nie znaleziono”.
              title={
                filterActive
                  ? t('retrieval.results.metadataExcluded')
                  : t('retrieval.results.empty')
              }
            />
          </Box>
        ) : (
          <Stack spacing={2}>
            {result.chunks.map((chunk) => (
              <ResultItem key={chunk.id} chunk={chunk} />
            ))}
            {result.total > pageSize ? (
              <Pagination
                count={Math.ceil(result.total / pageSize)}
                page={page}
                onChange={(_event, next) => onPageChange(next)}
                sx={{ alignSelf: 'center' }}
              />
            ) : null}
          </Stack>
        )}

        <Popover
          open={filterAnchor !== null}
          anchorEl={filterAnchor}
          onClose={() => setFilterAnchor(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        >
          <Stack spacing={1} sx={{ p: 2, minWidth: 240 }}>
            <Button
              size="small"
              onClick={() => {
                onDocsChange([])
                setFilterAnchor(null)
              }}
            >
              {t('retrieval.results.filterAll')}
            </Button>
            {allDocs.map((doc) => (
              <FormControlLabel
                key={doc.doc_id}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedDocIds.includes(doc.doc_id)}
                    onChange={(event) => onDocsChange(toggleDoc(doc.doc_id, event.target.checked))}
                  />
                }
                label={`${doc.doc_name} (${doc.count})`}
              />
            ))}
          </Stack>
        </Popover>
      </CardContent>
    </Card>
  )
}
