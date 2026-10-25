/**
 * Dialog pełnego logu parsowania (kontrakt WP E3-3b §T2): tytuł z nazwą dokumentu, cały
 * `progress_msg` w bloku `pre-wrap` z przewijaniem i przycisk „Zamknij”. Dokument `null`
 * (nic nie wybrano) nie renderuje zawartości — dialog zostaje pusty, decyduje tylko `open`.
 */

import type { JSX } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { translateProgressLog } from '../../../lib/serverMessages'
import type { DocumentRow } from './queries'

export type ProcessLogDialogProps = {
  open: boolean
  doc: Pick<DocumentRow, 'name' | 'progress_msg' | 'process_begin_at' | 'process_duration'> | null
  onClose: () => void
}

export function ProcessLogDialog(props: ProcessLogDialogProps): JSX.Element {
  const { open, doc, onClose } = props
  const { t } = useTranslation()
  // Wpisy worka tłumaczone przy wyświetleniu (T3b, K20 §5 p. 4) — zmiana języka działa też
  // dla otwartego dialogu; linie nieznane zostają dosłownie.
  const log = doc === null ? '' : translateProgressLog(doc.progress_msg, t)
  const title =
    doc === null ? t('datasets.files.log.title') : `${t('datasets.files.log.title')} — ${doc.name}`

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {doc === null ? null : doc.progress_msg.trim() === '' ? (
          <Typography color="text.secondary">{t('datasets.files.log.empty')}</Typography>
        ) : (
          <Box
            component="pre"
            sx={{
              m: 0,
              maxHeight: 360,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              fontFamily: 'monospace',
              fontSize: 13,
            }}
          >
            {log}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('datasets.files.log.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
