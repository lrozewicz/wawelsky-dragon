/**
 * Krok 1 dialogu importu (08 §7.15(c), CONTRACT WP E7-2 §7): strefa upuszczania
 * `data-testid="kb-import-dropzone"` (dragenter/dragover/drop — wzór `UploadFilesDialog`)
 * + przycisk „Wybierz plik" z ukrytym `input[type=file] accept=".zip,.wdkb.zip"`.
 * Paczka 0 B nie startuje wysyłki (R-ING-03) — pod strefą zostaje ostrzeżenie; błąd wysyłki
 * (np. odrzucenie sesji przez backend) wraca jako Alert nad strefą.
 */

import { useRef } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type ImportDropzoneProps = {
  onFiles: (file: File) => void
  /** `true` — wybrany/upuszczony plik ma 0 B (R-ING-03): ostrzeżenie pod strefą. */
  emptyFile: boolean
  /** Tekst błędu wysyłki/sesji z poprzedniej próby (`null` = brak). */
  errorText: string | null
}

export function ImportDropzone(props: ImportDropzoneProps) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)

  function openFilePicker(): void {
    inputRef.current?.click()
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>): void {
    // `files` istnieje zawsze po zdarzeniu `change`; pusty wybór niczego nie zmienia.
    const picked = event.target.files?.[0]
    // Czyścimy wartość, żeby ten sam plik dał się wybrać ponownie po niepowodzeniu.
    event.target.value = ''
    if (picked !== undefined) props.onFiles(picked)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    const dropped = event.dataTransfer.files[0]
    if (dropped !== undefined) props.onFiles(dropped)
  }

  return (
    <Stack spacing={2}>
      {props.errorText !== null ? <Alert severity="error">{props.errorText}</Alert> : null}
      <Box
        data-testid="kb-import-dropzone"
        role="button"
        tabIndex={0}
        onClick={openFilePicker}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            openFilePicker()
          }
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        sx={(theme) => ({
          p: 3,
          textAlign: 'center',
          border: '1px dashed',
          borderColor: 'divider',
          borderRadius: 1,
          cursor: 'pointer',
          // Ciemny schemat (QA V12-z-2b MINOR-1): divider (alpha gray-700 0,6) ginie na tle
          // dialogu — ramka w kolorze text.secondary (gray-400, ~7:1 na papierze); jasny bez zmian.
          ...theme.applyStyles('dark', { borderColor: 'text.secondary' }),
        })}
      >
        <Typography variant="body2" color="text.secondary">
          {t('kbTransfer.import.drop')}
        </Typography>
      </Box>
      {props.emptyFile ? (
        <Alert severity="warning" data-testid="kb-import-empty">
          {t('kbTransfer.import.emptyFile')}
        </Alert>
      ) : null}
      <Box>
        <Button variant="outlined" onClick={openFilePicker}>
          {t('kbTransfer.import.pick')}
        </Button>
      </Box>
      <input
        ref={inputRef}
        type="file"
        accept=".zip,.wdkb.zip"
        hidden
        data-testid="kb-import-input"
        onChange={handleInputChange}
      />
    </Stack>
  )
}
