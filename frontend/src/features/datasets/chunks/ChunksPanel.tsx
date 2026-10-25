/**
 * Prawy panel strony chunków (08 §7.5, kontrakt WP E3-4a §ChunksPanel): nagłówek z licznikiem,
 * pasek narzędzi, pasek zaznaczenia, lista kart, paginacja serwerowa (30 na stronę) i dialogi
 * (chunku oraz potwierdzenia usunięcia). Stan i mutacje trzyma `useChunksPanelState` — tutaj
 * zostaje sam układ i pojedyncze różnice wobec niego (klik w kartę idzie też do rodzica).
 */

import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import Pagination from '@mui/material/Pagination'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'

import { ChunkCard } from './ChunkCard'
import { ChunkDialog } from './ChunkDialog'
import { ChunksToolbar } from './ChunksToolbar'
import type { Chunk, ChunkDoc } from './queries'
import { SelectionBar } from './SelectionBar'
import { useChunksPanelState } from './useChunksPanelState'

export type ChunksPanelProps = {
  datasetId: string
  docId: string
  onActivateChunk: (chunk: Chunk) => void
  /** Nazwa i typ dokumentu dla breadcrumbów i podglądu (kontrakt §ChunksPanelProps). */
  onDocLoaded?: (doc: ChunkDoc) => void
}

export function ChunksPanel(props: ChunksPanelProps): JSX.Element {
  const { datasetId, docId, onActivateChunk, onDocLoaded } = props
  const { t } = useTranslation()
  const panel = useChunksPanelState({ datasetId, docId, onDocLoaded })

  return (
    <Stack spacing={2} sx={{ minWidth: 0 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
        <Typography variant="h6">{t('chunks.panel.title')}</Typography>
        <Typography variant="body2" color="text.secondary">
          {t('chunks.total', { count: panel.total })}
        </Typography>
      </Stack>

      <ChunksToolbar
        expanded={panel.expanded}
        onExpandedChange={panel.setExpanded}
        filter={panel.filter}
        onFilterChange={panel.handleFilterChange}
        keywords={panel.keywords}
        onKeywordsChange={panel.handleKeywordsChange}
        onAdd={panel.openAdd}
      />

      <SelectionBar
        selectedCount={panel.selectedCount}
        pageSize={panel.chunks.length}
        allOnPageSelected={panel.allOnPageSelected}
        onTogglePage={panel.togglePage}
        onEnable={() => {
          panel.setAvailableForSelection(true)
        }}
        onDisable={() => {
          panel.setAvailableForSelection(false)
        }}
        onDelete={panel.openDelete}
      />

      {panel.saveError ? <Alert severity="error">{t('chunks.dialog.saveError')}</Alert> : null}

      {panel.deleteError ? <Alert severity="error">{t('chunks.delete.error')}</Alert> : null}

      {panel.isError ? (
        <QueryError message={t('chunks.error')} onRetry={panel.refetch} />
      ) : panel.isPending ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress aria-label={t('chunks.panel.title')} />
        </Box>
      ) : panel.chunks.length === 0 ? (
        <EmptyState title={panel.filtered ? t('chunks.emptyFiltered') : t('chunks.empty')} />
      ) : (
        <Stack spacing={1}>
          {panel.chunks.map((chunk) => (
            <ChunkCard
              key={chunk.id}
              chunk={chunk}
              selected={panel.selected.has(chunk.id)}
              expanded={panel.expanded}
              active={panel.activeId === chunk.id}
              onToggleSelect={panel.toggleSelect}
              onToggleAvailable={panel.toggleAvailable}
              onActivate={(activated) => {
                panel.activate(activated)
                onActivateChunk(activated)
              }}
              onEdit={panel.openEdit}
            />
          ))}
        </Stack>
      )}

      {panel.pageCount > 1 ? (
        <Pagination
          data-testid="chunks-pagination"
          count={panel.pageCount}
          page={panel.page}
          onChange={(_event, next: number) => {
            panel.setPage(next)
          }}
        />
      ) : null}

      <ChunkDialog
        open={panel.editing !== null}
        chunk={panel.editing === null || panel.editing === 'new' ? null : panel.editing}
        saving={panel.saving}
        onClose={panel.closeDialog}
        onSubmit={panel.submit}
      />

      <ConfirmDialog
        open={panel.deleteOpen}
        title={t('chunks.delete.title')}
        message={t('chunks.delete.message', { count: panel.selectedCount })}
        confirmLabel={t('chunks.delete.confirm')}
        cancelLabel={t('chunks.dialog.cancel')}
        loading={panel.deleting}
        onConfirm={panel.confirmDelete}
        onCancel={panel.closeDelete}
      />
    </Stack>
  )
}
