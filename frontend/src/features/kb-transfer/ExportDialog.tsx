/**
 * Dialog eksportu bazy wiedzy (08 §7.15(a), kontrakt WP E7-2 §2–§4/§7): szacunek
 * „Do paczki trafią: …” (odmiana PL przez plural i18n, rozmiar wg przełącznika), przełącznik
 * „Dołącz wektory” z opisem modelu embeddingów i różnicą rozmiaru, nota o braku kluczy.
 * Szacunek > `max_bytes` → „Eksportuj” nieaktywny + komunikat limitu (WD_EXPORT_MAX_BYTES).
 * Start: sukces → `onStarted(TaskRef)` + zamknięcie (T2/T5 dopisze wpis paska zadań);
 * 409 `export_in_progress` → `onExisting(task_id)` + zamknięcie (T5 przewinie pasek);
 * inne błędy → Alert z `kbErrorMessageKey`. Dialog szer. 560 px, < 600 px pełny ekran.
 */

import { useState } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { useFullScreenDialog } from '../../components/useFullScreenDialog'
import { resolveLanguage } from '../../i18n'
import { WdApiError } from '../admin/wdClient'

import { kbErrorMessageKey } from './errors'
import { formatGrouped, formatPackageBytes } from './format'
import { useExportPreview, useStartExport } from './queries'
import type { TaskRef } from './types'

export type ExportDialogProps = {
  /** Baza wiedzy do eksportu (z listy datasetów — `DatasetsPage` poda `id` i `name`). */
  dataset: { id: string; name: string }
  onClose: () => void
  /** Sukces `POST /export` — T5/T2 dopisze wiersz paska zadań (`useKbTasks().add`). */
  onStarted: (ref: TaskRef) => void
  /** 409 `export_in_progress` — task_id istniejącego eksportu z `details` (T5 przewinie pasek). */
  onExisting: (taskId: string) => void
}

/** Tekst błędu API wg slugi z K19 (nieznany → ogólny). */
function errorText(error: unknown, t: (key: string) => string): string {
  return t(error instanceof WdApiError ? kbErrorMessageKey(error.code) : 'kbTransfer.error.unknown')
}

export function ExportDialog(props: ExportDialogProps) {
  const { t, i18n } = useTranslation()
  const preview = useExportPreview(props.dataset.id, true)
  const startExport = useStartExport()
  const [includeVectors, setIncludeVectors] = useState(true)
  // 08 §7.15(a): < 600 px pełny ekran (breakpoint `sm` = 600).
  const fullScreen = useFullScreenDialog()
  const language = resolveLanguage(i18n.language)

  const data = preview.data
  const estimatedBytes =
    data === undefined
      ? undefined
      : includeVectors
        ? data.estimated_bytes_with_vectors
        : data.estimated_bytes
  const overLimit =
    data !== undefined && estimatedBytes !== undefined && estimatedBytes > data.max_bytes

  function startExportNow(): void {
    startExport.mutate(
      { datasetId: props.dataset.id, includeVectors },
      {
        onSuccess: (ref) => {
          props.onStarted(ref)
          props.onClose()
        },
        onError: (error) => {
          // 409 `export_in_progress` (K19 §3 trasa 2): zamykamy dialog i oddajemy task_id
          // istniejącego eksportu; przewinięcie do wiersza robi pasek zadań (T5).
          if (error instanceof WdApiError && error.code === 'export_in_progress') {
            const taskId = error.details?.task_id
            if (typeof taskId === 'string') {
              props.onExisting(taskId)
              props.onClose()
              return
            }
          }
          // Inne błędy zostają w dialogu jako Alert (stan mutacji).
        },
      },
    )
  }

  return (
    <Dialog
      open
      onClose={props.onClose}
      fullScreen={fullScreen}
      maxWidth={false}
      slotProps={{ paper: { sx: fullScreen ? undefined : { width: 560 } } }}
    >
      <DialogTitle>
        {/* Długa nazwa: widoczny tytuł z wielokropkiem, pełna nazwa w podpowiedzi (SC-E7-2-01).
            `aria-label` z pełnym tytułem — bez niego MUI Tooltip nadpisze nazwę dostępną samą
            nazwą bazy, a algoritmus accname rozdziela elementy w tytule spacjami (CONTRACT §7). */}
        <Tooltip title={props.dataset.name}>
          <Typography
            component="span"
            variant="inherit"
            noWrap
            sx={{ display: 'block' }}
            aria-label={t('kbTransfer.export.title', { name: props.dataset.name })}
          >
            {t('kbTransfer.export.title', { name: props.dataset.name })}
          </Typography>
        </Tooltip>
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {startExport.isError ? (
            <Alert severity="error">{errorText(startExport.error, t)}</Alert>
          ) : null}
          {preview.isError ? (
            <Alert
              severity="error"
              action={
                <Button color="inherit" size="small" onClick={() => void preview.refetch()}>
                  {t('kbTransfer.export.retry')}
                </Button>
              }
            >
              {errorText(preview.error, t)}
            </Alert>
          ) : null}
          {data === undefined ? (
            preview.isError ? null : (
              <Stack spacing={1} data-testid="kb-export-skeleton">
                <Skeleton variant="text" width="60%" />
                <Skeleton variant="rounded" height={48} />
                <Skeleton variant="text" width="80%" />
              </Stack>
            )
          ) : (
            <>
              {overLimit ? (
                <Alert severity="warning">
                  {t('kbTransfer.export.limitExceeded', {
                    max: formatPackageBytes(data.max_bytes, language),
                  })}
                </Alert>
              ) : null}
              {/* Jedna linia tekstu — e2e czyta z niej liczbę plików, chunków i szacunek. */}
              <Typography data-testid="kb-export-summary">
                {t('kbTransfer.export.summary', {
                  files: t('kbTransfer.export.files', {
                    count: data.documents,
                    n: formatGrouped(data.documents, language),
                  }),
                  chunks: t('kbTransfer.export.chunks', {
                    count: data.chunks,
                    n: formatGrouped(data.chunks, language),
                  }),
                  size: formatPackageBytes(
                    includeVectors ? data.estimated_bytes_with_vectors : data.estimated_bytes,
                    language,
                  ),
                })}
              </Typography>
              <Box>
                <FormControlLabel
                  control={
                    <Switch
                      checked={includeVectors}
                      onChange={(event) => setIncludeVectors(event.target.checked)}
                    />
                  }
                  label={t('kbTransfer.export.vectors')}
                />
                <Typography variant="body2" color="text.secondary">
                  {t('kbTransfer.export.vectorInfo', {
                    model: data.embedding.model_name,
                    dimension: String(data.embedding.dimension),
                    size: formatPackageBytes(data.estimated_bytes, language),
                  })}
                </Typography>
              </Box>
              <Typography variant="body2" color="text.secondary">
                {t('kbTransfer.export.noSecrets')}
              </Typography>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={props.onClose}>{t('common.cancel')}</Button>
        <Button
          variant="contained"
          onClick={startExportNow}
          loading={startExport.isPending}
          disabled={data === undefined || overLimit}
        >
          {t('kbTransfer.export.submit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
