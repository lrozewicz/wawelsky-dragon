/**
 * Dialog „Zmień nazwę” (kontrakt WP E4-5c §7): pole startuje z `file.name` przy każdym pliku,
 * przycisk `files.rename.save` nieaktywny, gdy nazwa jest pusta lub niezmieniona. Sukces →
 * toast `files.toast.renamed` i `onClose`; błąd koperty → `Alert` z `error.message`.
 */

import { useState } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import useNotifications from '../../hooks/useNotifications/useNotifications'
import { errorText } from '../../lib/errorText'
import { useRenameFile } from './mutations'
import type { FileItem } from './queries'

export type RenameFileDialogProps = {
  file: FileItem | null
  onClose: () => void
}

export function RenameFileDialog(props: RenameFileDialogProps) {
  const { file, onClose } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const rename = useRenameFile()

  const [value, setValue] = useState(file?.name ?? '')

  // Nowy plik (albo zamknięcie) → pole wraca do jego nazwy; korekta stanu w renderze.
  const [openedFile, setOpenedFile] = useState(file)
  if (openedFile !== file) {
    setOpenedFile(file)
    setValue(file?.name ?? '')
  }

  const trimmed = value.trim()
  const canSave = file !== null && trimmed !== '' && trimmed !== file.name

  const close = () => {
    rename.reset()
    onClose()
  }

  const submit = () => {
    if (file === null || !canSave) return
    rename.mutate(
      { id: file.id, newName: trimmed },
      {
        onSuccess: () => {
          show(t('files.toast.renamed'), { severity: 'success' })
          close()
        },
      },
    )
  }

  return (
    <Dialog
      open={file !== null}
      onClose={close}
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
      <DialogTitle>{t('files.rename.title')}</DialogTitle>
      <DialogContent>
        {rename.error !== null ? (
          <Alert severity="error">{errorText(rename.error, t)}</Alert>
        ) : null}
        <TextField
          autoFocus
          fullWidth
          margin="dense"
          label={t('files.rename.name')}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          slotProps={{ htmlInput: { 'data-testid': 'files-rename-name' } }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('common.cancel')}</Button>
        <Button
          data-testid="files-rename-save"
          type="submit"
          variant="contained"
          disabled={!canSave}
          loading={rename.isPending}
        >
          {t('files.rename.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
