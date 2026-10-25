/**
 * Dialog „Nowy folder” (kontrakt WP E4-5c §7): pole `files.folder.name` (wymagane po `trim` —
 * puste pokazuje `files.folder.required`), przycisk `files.folder.create`. Walidacja U11
 * (kontrakt K2): przycisk pozostaje aktywny, klik przy pustym polu pokazuje komunikat i wraca
 * fokusem do pola, etykieta zostaje nad polem. Sukces → powiadomienie `files.toast.created`
 * i `onClose`. Błąd koperty (`useCreateFolder`) → `Alert` z `error.message`, okno zostaje otwarte.
 * Stan czyścimy przy każdym otwarciu (wzór: `RenameDocumentDialog`).
 */

import { useRef, useState } from 'react'
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
import { useCreateFolder } from './mutations'

export type NewFolderDialogProps = {
  open: boolean
  parentId: string | undefined
  onClose: () => void
}

export function NewFolderDialog(props: NewFolderDialogProps) {
  const { open, parentId, onClose } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const create = useCreateFolder()

  const [value, setValue] = useState('')
  const [invalid, setInvalid] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // „Reset przy otwarciu” bez efektu (wzór `RenameDocumentDialog`): korekta stanu w renderze.
  const [wasOpen, setWasOpen] = useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    if (open) {
      setValue('')
      setInvalid(false)
    }
  }

  const close = () => {
    create.reset()
    onClose()
  }

  const trimmed = value.trim()
  const showError = invalid && trimmed === ''

  const submit = () => {
    if (trimmed === '') {
      setInvalid(true)
      inputRef.current?.focus()
      return
    }
    create.mutate(
      { name: trimmed, parentId },
      {
        onSuccess: () => {
          show(t('files.toast.created'), { severity: 'success' })
          close()
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      maxWidth="xs"
      fullWidth
      slotProps={{
        paper: {
          component: 'form',
          // Natywna walidacja przeglądarki blokowałaby `submit` przy pustym polu `required`
          // (wzór: `ChunkDialog`).
          noValidate: true,
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            submit()
          },
        } as React.ComponentPropsWithRef<'form'>,
      }}
    >
      <DialogTitle>{t('files.folder.title')}</DialogTitle>
      <DialogContent>
        {create.error !== null ? (
          <Alert severity="error">{errorText(create.error, t)}</Alert>
        ) : null}
        <TextField
          autoFocus
          fullWidth
          margin="dense"
          label={t('files.folder.name')}
          value={value}
          inputRef={inputRef}
          error={showError}
          helperText={showError ? t('files.folder.required') : undefined}
          slotProps={{
            htmlInput: { 'data-testid': 'files-folder-name' },
            inputLabel: { shrink: showError ? true : undefined },
          }}
          onChange={(event) => {
            setValue(event.target.value)
            setInvalid(false)
          }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('common.cancel')}</Button>
        <Button
          data-testid="files-folder-create"
          type="submit"
          variant="contained"
          loading={create.isPending}
        >
          {t('files.folder.create')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
