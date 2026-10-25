/**
 * Dialog logu zadania ingestii (kontrakt WP E3-3a §T5): pobiera pojedynczy log
 * (`ingestionLogQueryOptions`) i pokazuje plik, status, czas oraz preformatowany
 * `progress_msg` przetłumaczony wg P1–P29 (K20 §5 p. 4, jak `ProcessLogDialog`).
 * Mieszka tu także `IngestionStatusChip` — tego samego znacznika używa kolumna Status w `LogsTab`,
 * a kontrakt przewiduje w tym katalogu tylko te dwa pliki źródłowe.
 */

import type { JSX, ReactNode } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import type { ChipProps } from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ingestionLogQueryOptions } from '../queries'
import { translateProgressLog } from '../../../lib/serverMessages'

/** Kody `run` z kontraktu §Fakty API → kolory MUI (3 sukces, 4 błąd, 1/5 informacja, 0/2 neutralny). */
const STATUS_COLORS: Record<number, ChipProps['color']> = {
  0: 'default',
  1: 'info',
  2: 'default',
  3: 'success',
  4: 'error',
  5: 'info',
}

/**
 * Znacznik statusu zadania. `operation_status` przychodzi jako string z kodem `run` —
 * mapujemy go przez `Number()`; wartość spoza 0–5 pokazujemy dosłownie.
 */
export function IngestionStatusChip(props: { status: string }): JSX.Element {
  const { t } = useTranslation()
  const code = Number(props.status)
  const color = STATUS_COLORS[code]

  return (
    <Chip
      size="small"
      color={color ?? 'default'}
      label={color === undefined ? props.status : t(`datasets.logs.status.${code}`)}
    />
  )
}

/** Wiersz „etykieta: wartość” w treści dialogu. */
function LogField(props: { label: string; children: ReactNode }): JSX.Element {
  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
      <Typography variant="body2" color="text.secondary">
        {props.label}
      </Typography>
      {props.children}
    </Stack>
  )
}

export type IngestionLogDialogProps = {
  datasetId: string
  logId: string
  onClose: () => void
}

export function IngestionLogDialog(props: IngestionLogDialogProps): JSX.Element {
  const { datasetId, logId, onClose } = props
  const { t } = useTranslation()
  const log = useQuery(ingestionLogQueryOptions(datasetId, logId))

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('datasets.logs.dialog.title')}</DialogTitle>
      <DialogContent>
        {log.isPending ? (
          <Stack sx={{ alignItems: 'center', py: 3 }}>
            <CircularProgress />
          </Stack>
        ) : log.isError ? (
          <Alert severity="error">{t('datasets.logs.dialog.error')}</Alert>
        ) : (
          <Stack spacing={2} sx={{ pt: 1 }}>
            <LogField label={t('datasets.logs.dialog.file')}>
              <Typography variant="body2">{log.data.document_name}</Typography>
            </LogField>
            <LogField label={t('datasets.logs.dialog.status')}>
              <IngestionStatusChip status={log.data.operation_status} />
            </LogField>
            <LogField label={t('datasets.logs.dialog.duration')}>
              <Typography variant="body2">{`${log.data.process_duration.toFixed(1)} s`}</Typography>
            </LogField>
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 2,
                maxHeight: 320,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                bgcolor: 'action.hover',
                borderRadius: 1,
                fontFamily: 'monospace',
                fontSize: 13,
              }}
            >
              {/* Tłumaczenie jak w ProcessLogDialog (T10, QA V12-2-1 D2a): surowy tekst
                  serwera tylko dla wpisów spoza tabeli P. */}
              {translateProgressLog(log.data.progress_msg, t)}
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
