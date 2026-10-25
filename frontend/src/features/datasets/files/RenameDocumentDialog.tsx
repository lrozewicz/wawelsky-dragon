/**
 * Okno zmiany nazwy dokumentu (kontrakt WP E3-3b §T6). Pole startuje z bieżącą nazwą przy każdym
 * otwarciu; nazwa pusta po `trim` nie jest zapisywana — pokazujemy `rename.required`. Formularz
 * w oknie sprawia, że Enter w polu zapisuje (wzór: `features/chats/components/ChatNameDialog.tsx`).
 */

import { useState } from 'react'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

export type RenameDocumentDialogProps = {
  open: boolean
  name: string
  onSave: (name: string) => void
  onClose: () => void
  pending?: boolean
}

export function RenameDocumentDialog(props: RenameDocumentDialogProps) {
  const { open, name, onSave, onClose, pending } = props
  const { t } = useTranslation()
  const [value, setValue] = useState(name)
  const [invalid, setInvalid] = useState(false)

  // „Reset przy otwarciu” wzorem Reacta: korekta stanu w renderze przy zmianie wartości propa
  // (efekt ze `setState` odrzuca lint: `react-hooks/set-state-in-effect`).
  const [wasOpen, setWasOpen] = useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    if (open) {
      setValue(name)
      setInvalid(false)
    }
  }

  const submit = () => {
    const trimmed = value.trim()
    if (trimmed === '') {
      setInvalid(true)
      return
    }
    onSave(trimmed)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xs"
      fullWidth
      slotProps={{
        paper: {
          component: 'form',
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            submit()
          },
        },
      }}
    >
      <DialogTitle>{t('datasets.files.rename.title')}</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          margin="dense"
          label={t('datasets.files.rename.label')}
          value={value}
          error={invalid}
          helperText={invalid ? t('datasets.files.rename.required') : undefined}
          onChange={(event) => {
            setValue(event.target.value)
            setInvalid(false)
          }}
          slotProps={{ htmlInput: { 'data-testid': 'rename-input' } }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button data-testid="rename-save" type="submit" variant="contained" loading={pending}>
          {t('datasets.files.rename.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
