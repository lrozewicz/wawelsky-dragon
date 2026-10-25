/**
 * Okno „Parsuj ponownie” (kontrakt WP E3-H2a §K2): informuje, ile chunków zostanie zastąpionych.
 * Opcji czyszczenia nie ma — backend czyści istniejące chunki sam dla dokumentów DONE (DEC-139),
 * a `documents_parse` nie przyjmuje takiego parametru. Potwierdzenie nie przekazuje argumentu.
 */

import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import { useTranslation } from 'react-i18next'

export type ReparseDialogProps = {
  open: boolean
  chunkCount: number
  onConfirm: () => void
  onClose: () => void
}

export function ReparseDialog(props: ReparseDialogProps) {
  const { open, chunkCount, onConfirm, onClose } = props
  const { t } = useTranslation()

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('datasets.files.reparse.title')}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ pt: 1 }}>
          {t('datasets.files.reparse.body', { n: chunkCount })}
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('datasets.files.reparse.cancel')}</Button>
        {/* Strzałka, a nie `onConfirm` wprost — React dokłada zdarzenie jako argument. */}
        <Button
          data-testid="reparse-confirm"
          variant="contained"
          onClick={() => {
            onConfirm()
          }}
        >
          {t('datasets.files.reparse.confirm')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
