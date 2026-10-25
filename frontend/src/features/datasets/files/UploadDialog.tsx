/**
 * Dialog przesyłania plików datasetu (kontrakt WP E3-3b §T3): drag&drop + ukryty
 * `input[type=file]`, lista z paskami postępu (`uploadFiles`), przełącznik „Parsuj po
 * przesłaniu” i `useParseDocuments` na ID przyjętych dokumentów. Błąd pojedynczego pliku
 * nie przerywa pozostałych; po zakończeniu stopka „Przesłano N z M” z „Gotowe” (SC-E5-H9-03).
 * Plik 0 B nie wchodzi do kolejki — ostrzeżenie z nazwą (WP E5-H8d §C3); w mianowniku stopki
 * liczą się odrzucone z całej sesji dialogu (SC-E5-H9-03 krok 3).
 */

import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, JSX, KeyboardEvent } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { DisabledReason, describedBy } from '../../../components/DisabledReason'
import {
  formatNames,
  splitUnreadable,
  unreadableKey,
  type UnreadableSource,
} from '../../../lib/droppedFiles'
import { useParseDocuments } from './mutations'
import { UploadItemRow } from './UploadItemRow'
import { uploadFiles } from './uploadFiles'
import type { UploadItem } from './uploadFiles'
import { patchItem, pendingIndexes, resetForRetry } from './uploadItems'

export type UploadDialogProps = {
  open: boolean
  datasetId: string
  onClose: () => void
  onUploaded?: () => void
}

export function UploadDialog(props: UploadDialogProps): JSX.Element {
  const { open, datasetId, onClose, onUploaded } = props
  const { t } = useTranslation()
  const parseDocuments = useParseDocuments(datasetId)

  const [items, setItems] = useState<UploadItem[]>([])
  const [parseOnUpload, setParseOnUpload] = useState(true)
  const [uploading, setUploading] = useState(false)
  // Koniec przesyłania (SC-E5-H9-03): „Anuluj” → główne „Gotowe”, stopka z podsumowaniem.
  const [finished, setFinished] = useState(false)
  const [transferring, setTransferring] = useState(false) // trwa transfer — blokuje zamknięcie
  const [parseError, setParseError] = useState<string | null>(null)
  // Nazwy plików 0 B z ostatniego dropu (WP E5-H8d §C3); `null` = brak ostrzeżenia.
  const [unreadable, setUnreadable] = useState<{
    source: UnreadableSource
    names: string[]
  } | null>(null)
  // Odrzucone 0 B całej sesji — mianownik podsumowania (SC-E5-H9-03 krok 3).
  const [rejectedCount, setRejectedCount] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const doneRef = useRef<HTMLButtonElement>(null) // fokus na „Gotowe” po zakończeniu (SC-E5-H9-03)

  function addFiles(incoming: File[], source: UnreadableSource): void {
    setFinished(false)
    const { accepted, unreadable: unreadableNames } = splitUnreadable(incoming)
    setUnreadable(unreadableNames.length > 0 ? { source, names: unreadableNames } : null)
    setRejectedCount((count) => count + unreadableNames.length)
    setItems((previous) => {
      const next = [...previous]
      for (const file of accepted) {
        // Duplikat rozpoznajemy po nazwie i rozmiarze (id listy budujemy z tej samej pary).
        if (next.some((item) => item.file.name === file.name && item.file.size === file.size)) {
          continue
        }
        next.push({
          id: `${file.name}:${String(file.size)}`,
          file,
          state: 'pending',
          loaded: 0,
          total: 0,
        })
      }
      return next
    })
  }

  function openFilePicker(): void {
    inputRef.current?.click()
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    if (uploading) return
    addFiles(Array.from(event.dataTransfer.files), 'drop')
  }

  function handleDropzoneKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    openFilePicker()
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>): void {
    addFiles(Array.from(event.target.files ?? []), 'pick')
    // Czyścimy wartość, żeby ten sam plik dał się wybrać ponownie po usunięciu z listy.
    event.target.value = ''
  }

  // Zamknięcie (WP E5-H6a §C1): czyści stan i zamyka; blokada tylko w trakcie transferu plików.
  function handleClose(): void {
    if (transferring) return
    setItems([])
    setParseError(null)
    setUnreadable(null)
    setRejectedCount(0)
    setFinished(false)
    onClose()
  }

  async function start(): Promise<void> {
    const indexes = pendingIndexes(items)
    if (uploading || indexes.length === 0) return
    setUploading(true)
    setTransferring(true)
    setParseError(null)
    setFinished(false)
    setItems((previous) => resetForRetry(previous, indexes)) // błąd → pending, bez starej przyczyny

    const documentIds = await uploadFiles(
      datasetId,
      indexes.map((position) => items[position]!.file),
      {
        onProgress: (batchIndex, loaded, total) => {
          setItems((previous) =>
            patchItem(previous, indexes[batchIndex]!, { state: 'uploading', loaded, total }),
          )
        },
        onResult: (batchIndex, result) => {
          const patch: Partial<UploadItem> = result.ok
            ? { state: 'done', documentId: result.documentId }
            : { state: 'error', error: result.error, errorCode: result.errorCode }
          setItems((previous) => patchItem(previous, indexes[batchIndex]!, patch))
        },
      },
    )

    // Transfer plików zakończony — od tego miejsca „Zamknij” znowu działa, choć parsowanie trwa.
    setTransferring(false)
    setFinished(true)
    doneRef.current?.focus()

    if (parseOnUpload && documentIds.length > 0) {
      try {
        await parseDocuments.mutateAsync({ ids: documentIds })
      } catch {
        setParseError(t('datasets.files.error.generic'))
      }
    }

    setUploading(false)
    onUploaded?.()
  }

  // T15b: po pełnym sukcesie nie ma czego ponawiać — „Prześlij” wyłączone; z błędem w kolejce aktywny.
  const allUploaded = finished && items.every((item) => item.state === 'done')
  // SC-V12-08 k2: po zakończeniu z błędami etykieta mówi, co przycisk zrobi — `start()` wysyła
  // wszystko poza już przesłanym (`pendingIndexes`), więc ponawia wyłącznie nieudane pliki.
  const failedCount = items.filter((item) => item.state === 'error').length
  const retry = finished && failedCount > 0
  const retryHint = retry ? t('datasets.files.upload.retryHint') : null
  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('datasets.files.upload.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {parseError !== null ? <Alert severity="error">{parseError}</Alert> : null}
          <Box
            data-testid="upload-dropzone"
            role="button"
            tabIndex={0}
            aria-disabled={uploading}
            onClick={openFilePicker}
            onKeyDown={handleDropzoneKeyDown}
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
              {t('datasets.files.upload.drop')}
            </Typography>
          </Box>
          {unreadable !== null ? (
            <Alert severity="warning" data-testid="upload-unreadable">
              {t(unreadableKey(unreadable.source), { names: formatNames(unreadable.names) })}
            </Alert>
          ) : null}
          <Stack
            direction="row"
            spacing={2}
            useFlexGap
            sx={{ alignItems: 'center', flexWrap: 'wrap' }}
          >
            <Button
              variant="outlined"
              onClick={openFilePicker}
              disabled={uploading}
              sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}
            >
              {t('datasets.files.upload.choose')}
            </Button>
            <FormControlLabel
              control={
                <Switch
                  data-testid="upload-parse-toggle"
                  checked={parseOnUpload}
                  disabled={uploading}
                  onChange={(event) => setParseOnUpload(event.target.checked)}
                />
              }
              label={t('datasets.files.upload.parse')}
            />
          </Stack>
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            data-testid="upload-input"
            disabled={uploading}
            onChange={handleInputChange}
          />
          {items.map((item, index) => (
            <UploadItemRow key={item.id} item={item} index={index} />
          ))}
        </Stack>
      </DialogContent>
      {/* Spacing MUI (ml 8 na dzieciach po pierwszym) przy wrap NIE znika w nowym wierszu —
          od T5 podpowiedź jest pierwszym dzieckiem i stopka „Przesłano x z y” dostała wcięcie
          8 px względem listy (QA-D5). Odstępy przycisków oddaje columnGap; lewe krawędzie
          stopki, podpowiedzi i listy pozostają wyrównane. */}
      <DialogActions disableSpacing sx={{ px: 3, flexWrap: 'wrap', rowGap: 1, columnGap: 1 }}>
        {/* Podpowiedź ponowienia własnym wierszem nad przyciskami (SC-V12-08 k2). */}
        <DisabledReason id="upload-retry-hint" reason={retryHint} />
        {/* Odrzucony plik (0 B albo błąd API) zostaje w mianowniku (SC-E5-H9-03 krok 3). */}
        {finished ? (
          <Typography
            variant="body1"
            sx={{ mr: 'auto', whiteSpace: 'nowrap', flexBasis: { xs: '100%', sm: 'auto' } }}
            data-testid="upload-summary"
          >
            {t('common.upload.summary', {
              done: items.filter((item) => item.state === 'done').length,
              total: items.length + rejectedCount,
            })}
          </Typography>
        ) : null}
        <Button
          ref={doneRef}
          onClick={handleClose}
          variant={finished ? 'contained' : 'text'}
          data-testid="upload-close"
        >
          {finished ? t('common.done') : t('common.cancel')}
        </Button>
        <Button
          variant={finished ? 'outlined' : 'contained'}
          data-testid="upload-start"
          onClick={start}
          disabled={uploading || items.length === 0 || allUploaded}
          aria-describedby={describedBy('upload-retry-hint', retryHint)}
        >
          {retry
            ? t('datasets.files.upload.retry', { count: failedCount })
            : t('datasets.files.upload.start')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
