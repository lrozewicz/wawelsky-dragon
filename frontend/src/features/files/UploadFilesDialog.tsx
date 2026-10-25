/**
 * Dialog „Prześlij pliki” (kontrakt WP E4-5c §7, WP E5-H6a §C1): ukryty `input[type=file]` + strefa
 * upuszczania startują `uploadFiles(parentId, files, …)` od razu po wyborze. Lista pozycji
 * z `LinearProgress` pokazuje stany `done`/`error` (komunikat błędu z koperty API w elemencie
 * `role="alert"`). Po zakończeniu pętli unieważniamy `fileKeys.all`. Okno nie zamyka się samo —
 * zamyka je przycisk „Anuluj”/„Gotowe” (testid `files-upload-close`), który (jak Esc i klik w tło)
 * czyści kolejkę i woła
 * `onClose`; w trakcie wysyłki zamknięcie nic nie robi. Po zakończeniu (SC-E5-H9-03) stopka
 * pokazuje „Przesłano N z M”, a przycisk staje się głównym „Gotowe” z fokusem. Plik 0 B
 * (np. Chrome z Flatpaka bez dostępu do katalogu) nie startuje wysyłki — pod strefą zostaje
 * ostrzeżenie z jego nazwą (kontrakt WP E5-H8d §C3); wybór czytelnych plików je gasi.
 */

import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import {
  formatNames,
  splitUnreadable,
  unreadableKey,
  type UnreadableSource,
} from '../../lib/droppedFiles'
import { translateServerMessage } from '../../lib/serverMessages'
import { doneMarkerColorSx } from '../../theme/parsingStatus'
import { fileKeys } from './queries'
import { uploadFiles } from './uploadFiles'
import type { FileUploadItem } from './uploadFiles'

/** Procent postępu 0–100; plik bez zdarzeń postępu (`total === 0`) stoi na 0. */
function progressPercent(loaded: number, total: number): number {
  return total > 0 ? Math.round((loaded / total) * 100) : 0
}

/** Podmienia pola jednej pozycji po indeksie (kolejność `uploadFiles` = kolejność listy). */
function patchItem(
  items: FileUploadItem[],
  index: number,
  patch: Partial<FileUploadItem>,
): FileUploadItem[] {
  return items.map((item, position) => (position === index ? { ...item, ...patch } : item))
}

export type UploadFilesDialogProps = {
  open: boolean
  parentId: string | undefined
  onClose: () => void
}

export function UploadFilesDialog(props: UploadFilesDialogProps) {
  const { open, parentId, onClose } = props
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [items, setItems] = useState<FileUploadItem[]>([])
  const [uploading, setUploading] = useState(false)
  // Koniec przesyłania (SC-E5-H9-03): stopka „Przesłano N z M”, przycisk staje się „Gotowe”.
  const [finished, setFinished] = useState(false)
  // Nazwy plików 0 B z ostatniego dropu/wyboru (kontrakt WP E5-H8d §C3) — `null` znaczy: brak ostrzeżenia.
  const [unreadable, setUnreadable] = useState<{
    source: UnreadableSource
    names: string[]
  } | null>(null)
  // Odrzucone 0 B w CAŁEJ sesji okna — mianownik podsumowania (SC-E5-H9-03 krok 3), bo
  // ostrzeżenie dotyczy tylko ostatniego dropu i gaśnie po dobrym wyborze.
  const [rejectedCount, setRejectedCount] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  // „Gotowe” (po zakończeniu przesyłania) dostaje na siebie fokus (SC-E5-H9-03).
  const doneRef = useRef<HTMLButtonElement>(null)

  /** Filtr nieczytelnych plików (E5-H8d §C3): 0 B zostaje jako ostrzeżenie, reszta startuje wysyłkę. */
  function accept(incoming: File[], source: UnreadableSource): void {
    const { accepted, unreadable: unreadableNames } = splitUnreadable(incoming)
    setUnreadable(unreadableNames.length > 0 ? { source, names: unreadableNames } : null)
    setRejectedCount((count) => count + unreadableNames.length)
    if (accepted.length > 0) void start(accepted)
  }

  async function start(incoming: File[]): Promise<void> {
    if (incoming.length === 0) return
    setFinished(false)
    setItems(
      incoming.map((file, index) => ({
        id: `${file.name}:${String(file.size)}:${String(index)}`,
        file,
        state: 'pending',
        loaded: 0,
        total: 0,
      })),
    )
    setUploading(true)

    await uploadFiles(parentId, incoming, {
      onProgress: (index, loaded, total) => {
        setItems((previous) => patchItem(previous, index, { state: 'uploading', loaded, total }))
      },
      onResult: (index, result) => {
        setItems((previous) =>
          patchItem(
            previous,
            index,
            result.ok
              ? { state: 'done' }
              : { state: 'error', error: result.error, errorCode: result.errorCode },
          ),
        )
      },
    })

    setUploading(false)
    setFinished(true)
    doneRef.current?.focus()
    await queryClient.invalidateQueries({ queryKey: fileKeys.all })
  }

  function openFilePicker(): void {
    inputRef.current?.click()
  }

  /** Zamknięcie okna (kontrakt C1): w trakcie wysyłki nic nie robi; inaczej czyści kolejkę, ostrzeżenie i woła `onClose`. */
  function close(): void {
    if (uploading) return
    setItems([])
    setUnreadable(null)
    setRejectedCount(0)
    setFinished(false)
    onClose()
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>): void {
    // `files` istnieje zawsze po zdarzeniu `change`; pusty wybór niczego nie zmienia.
    const picked = Array.from(event.target.files as FileList)
    // Czyścimy wartość, żeby ten sam plik dał się wybrać ponownie po zamknięciu okna.
    event.target.value = ''
    accept(picked, 'pick')
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    if (uploading) return
    accept(Array.from(event.dataTransfer.files), 'drop')
  }

  return (
    <Dialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle>{t('files.upload.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Box
            data-testid="files-upload-dropzone"
            role="button"
            tabIndex={0}
            aria-disabled={uploading}
            onClick={openFilePicker}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                openFilePicker()
              }
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleDrop}
            sx={{
              p: 3,
              textAlign: 'center',
              border: '1px dashed',
              borderColor: 'divider',
              borderRadius: 1,
              cursor: uploading ? 'default' : 'pointer',
            }}
          >
            <Typography variant="body2" color="text.secondary">
              {t('files.upload.drop')}
            </Typography>
          </Box>
          {unreadable !== null ? (
            <Alert severity="warning" data-testid="upload-unreadable">
              {t(unreadableKey(unreadable.source), { names: formatNames(unreadable.names) })}
            </Alert>
          ) : null}
          <Box>
            <Button variant="outlined" disabled={uploading} onClick={openFilePicker}>
              {t('files.upload.pick')}
            </Button>
          </Box>
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            data-testid="files-upload-input"
            disabled={uploading}
            onChange={handleInputChange}
          />
          {items.map((item, index) => (
            <Stack key={item.id} spacing={0.5} data-testid={`files-upload-item-${String(index)}`}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <Typography variant="body2" noWrap sx={{ minWidth: 0, flex: 1 }}>
                  {item.file.name}
                </Typography>
                {item.state === 'done' ? (
                  <Typography variant="caption" sx={doneMarkerColorSx}>
                    {t('files.upload.done')}
                  </Typography>
                ) : null}
                {item.state === 'error' ? (
                  <Typography variant="caption" color="error">
                    {t('files.upload.error')}
                  </Typography>
                ) : null}
              </Stack>
              <LinearProgress
                variant="determinate"
                value={progressPercent(item.loaded, item.total)}
                aria-valuenow={progressPercent(item.loaded, item.total)}
              />
              {item.state === 'error' && item.error !== undefined ? (
                <Typography variant="caption" color="error" role="alert">
                  {/* Komunikat serwera tłumaczony przy wyświetleniu (T5b); bez koperty — bez zmian. */}
                  {item.errorCode === undefined
                    ? item.error
                    : translateServerMessage(item.errorCode, item.error, t)}
                </Typography>
              ) : null}
            </Stack>
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        {/* Koniec przesyłania (SC-E5-H9-03): „Przesłano N z M”; odrzucony plik (0 B albo błąd
            API) zostaje w mianowniku. */}
        {finished ? (
          <Typography variant="body1" sx={{ mr: 'auto' }} data-testid="files-upload-summary">
            {t('common.upload.summary', {
              done: items.filter((item) => item.state === 'done').length,
              total: items.length + rejectedCount,
            })}
          </Typography>
        ) : null}
        {/* „Gotowe” główne po zakończeniu; w trakcie wysyłki klik nic nie robi (kontrakt C1). */}
        <Button
          ref={doneRef}
          data-testid="files-upload-close"
          onClick={close}
          variant={finished ? 'contained' : 'text'}
        >
          {finished ? t('common.done') : t('common.cancel')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
