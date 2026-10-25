/**
 * Strona chunków dokumentu (08 §7.5, kontrakt WP E3-4a §ChunksPage): pasek z „Wstecz” i
 * breadcrumbami (bazy wiedzy → pliki datasetu → dokument), a pod nim dwupanelowy układ —
 * podgląd dokumentu po lewej (`DocumentPreview` z `features/chats/preview`) i `ChunksPanel`
 * po prawej. Nazwa i typ dokumentu przychodzą z panelu (`onDocLoaded`), bo niesie je lista chunków.
 *
 * Klik w chunk w dokumencie PDF ustawia numer strony z `positions[0][0]`; numer jedzie do podglądu
 * propem `page` (DocumentPreview dokłada wtedy do adresu PDF-a fragment `#page=N`, kontrakt
 * WP E3-H2a §K5) i zostaje na atrybucie `data-page` kontenera podglądu.
 */

import { useCallback, useState } from 'react'
import type { JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import Breadcrumbs from '@mui/material/Breadcrumbs'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { DocumentPreview } from '../../chats/preview/DocumentPreview'
import { datasetQueryOptions } from '../queries'
import { ChunksPanel } from './ChunksPanel'
import type { Chunk, ChunkDoc } from './queries'
import { SplitPane } from './SplitPane'

export type ChunksPageProps = {
  datasetId: string
  docId: string
}

/**
 * Styl linków breadcrumbów. `MuiLink` nie przepuszcza `params` trasy przez typy `component`,
 * a breadcrumb do plików datasetu wymaga `id` — dlatego linki to komponenty routera z kolorem
 * dziedziczonym po `Breadcrumbs` (jak `MuiLink color="inherit"`).
 */
const BREADCRUMB_LINK_STYLE = { color: 'inherit' }

/** Numer pierwszej strony z pozycji chunku, gdy pozycja jest liczbą; inaczej `null`. */
function firstPositionPage(chunk: Chunk): number | null {
  const page = chunk.positions[0]?.[0]
  return typeof page === 'number' ? page : null
}

export function ChunksPage(props: ChunksPageProps): JSX.Element {
  const { datasetId, docId } = props
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [doc, setDoc] = useState<ChunkDoc | null>(null)
  const [pdfPage, setPdfPage] = useState<number | null>(null)

  const dataset = useQuery(datasetQueryOptions(datasetId))
  // Tożsamość stabilna — efekt w panelu zależy od tego callbacku (nie może się zmieniać co render).
  const handleDocLoaded = useCallback((loaded: ChunkDoc) => {
    setDoc(loaded)
  }, [])

  const docName = doc?.name ?? '…'
  const isPdf = doc !== null && (doc.type === 'pdf' || docName.toLowerCase().endsWith('.pdf'))

  function handleActivateChunk(chunk: Chunk): void {
    if (!isPdf) return
    const page = firstPositionPage(chunk)
    if (page !== null) setPdfPage(page)
  }

  return (
    <Stack spacing={2} data-testid="chunks-page" sx={{ flex: 1, minHeight: 0, p: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <IconButton
          data-testid="chunks-back"
          aria-label={t('chunks.back')}
          onClick={() => {
            void navigate({ to: '/dataset/files/$id', params: { id: datasetId } })
          }}
        >
          <ArrowBackRoundedIcon />
        </IconButton>
        <Breadcrumbs aria-label={t('chunks.breadcrumbs.label')}>
          <Link to="/datasets" style={BREADCRUMB_LINK_STYLE}>
            {t('chunks.breadcrumbs.datasets')}
          </Link>
          <Link to="/dataset/files/$id" params={{ id: datasetId }} style={BREADCRUMB_LINK_STYLE}>
            {dataset.data?.name ?? '…'}
          </Link>
          <Typography color="text.primary">{docName}</Typography>
        </Breadcrumbs>
      </Stack>

      <SplitPane
        left={
          <Stack
            spacing={1}
            data-testid="chunks-preview"
            data-page={pdfPage ?? undefined}
            sx={{ minWidth: 0 }}
          >
            <Typography variant="h6">{t('chunks.preview.title')}</Typography>
            <DocumentPreview
              key={docId}
              documentId={docId}
              documentName={docName}
              page={pdfPage ?? undefined}
            />
          </Stack>
        }
        right={
          <ChunksPanel
            datasetId={datasetId}
            docId={docId}
            onActivateChunk={handleActivateChunk}
            onDocLoaded={handleDocLoaded}
          />
        }
      />
    </Stack>
  )
}
