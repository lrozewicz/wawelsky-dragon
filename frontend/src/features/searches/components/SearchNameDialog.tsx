/**
 * Okno nazwy wyszukiwarki (kontrakt WP E4-4b §4): jedno dla tworzenia (`POST /searches`)
 * i zmiany nazwy (`PUT`). Tytuł i etykieta zapisu wynikają z `mode`; pole nazwy startuje
 * z `initialName`. Walidacja U11 (kontrakt K2): przycisk zapisu pozostaje aktywny, a klik przy
 * pustej nazwie (po trim) pokazuje `common.required` pod polem i wraca fokusem do pola; etykieta
 * zostaje nad polem. Zmiana treści gasi komunikat; `busy` wyłącza przycisk (`loading`).
 * Błąd mutacji wraca tu jako `error` (Alert nad polem).
 * Wołający renderuje komponent tylko wtedy, gdy okno ma być widoczne.
 */

import * as React from 'react'
import { useRef, useState } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

export type SearchNameDialogProps = {
  mode: 'create' | 'rename'
  /** Wartość początkowa pola; przy tworzeniu pusta. */
  initialName?: string
  /** Trwa mutacja — przycisk zapisu pokazuje `loading` (i jest nieaktywny). */
  busy: boolean
  /** Komunikat błędu mutacji (np. z `ApiError`) — `null` ukrywa Alert. */
  error: string | null
  onSubmit: (name: string) => void
  onClose: () => void
}

export function SearchNameDialog(props: SearchNameDialogProps) {
  const { mode, initialName = '', busy, error, onSubmit, onClose } = props
  const { t } = useTranslation()
  const [name, setName] = useState(initialName)
  // Walidacja U11: komunikat o pustym polu dopiero po próbie wysłania.
  const [invalid, setInvalid] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const trimmed = name.trim()
  const isValid = trimmed !== ''
  const showError = invalid && !isValid
  const title = mode === 'create' ? t('searches.create') : t('searches.rename')
  const submitLabel = mode === 'create' ? t('searches.createSubmit') : t('searches.renameSubmit')

  return (
    <Dialog
      open
      onClose={onClose}
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
            if (isValid) {
              onSubmit(trimmed)
              return
            }
            setInvalid(true)
            inputRef.current?.focus()
          },
        } as React.ComponentPropsWithRef<'form'>,
      }}
    >
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error !== null ? <Alert severity="error">{error}</Alert> : null}
          <TextField
            autoFocus
            required
            fullWidth
            margin="dense"
            label={t('searches.name')}
            value={name}
            inputRef={inputRef}
            error={showError}
            helperText={showError ? t('common.required') : undefined}
            slotProps={{ inputLabel: { shrink: showError ? true : undefined } }}
            onChange={(event) => {
              setName(event.target.value)
              setInvalid(false)
            }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('searches.cancel')}</Button>
        <Button type="submit" variant="contained" loading={busy}>
          {submitLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
