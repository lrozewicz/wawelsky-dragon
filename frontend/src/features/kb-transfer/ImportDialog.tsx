/**
 * Dialog „Importuj bazę wiedzy" (08 §7.15(c), kontrakt WP E7-2 §2/§3/§5/§7/§9): krok 1
 * wybór/upuszczenie `.wdkb.zip` (ImportDropzone), wysyłka porcjami z wznawianiem
 * (`uploadPackage` + AbortController: „Wysłano a/b", „Wznawianie…", „Wznów", „Anuluj"),
 * krok 2 podsumowanie (ImportSummaryStep) i start (`startImport` → `onStarted` dla paska
 * zadań). Porzucenie sesji: „Anuluj" w trakcie wysyłki = abort + `deleteImport` (cancel sesji);
 * twardy błąd wysyłki po założeniu sesji = `deleteImport` (best-effort) i powrót do kroku 1;
 * zamknięcie w kroku 2 = `deleteImport` (nie `cancel()` — MINOR T2: ratunkowe ścieżki sesji
 * mogą skasować kompletną paczkę); `state=invalid` → lista błędów + „Wybierz inny plik".
 */

import { useRef, useState } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { useFullScreenDialog } from '../../components/useFullScreenDialog'
import { resolveLanguage } from '../../i18n'
import { WdApiError } from '../admin/wdClient'

import { ImportDropzone } from './ImportDropzone'
import { ImportSummaryStep } from './ImportSummaryStep'
import { ImportUploadStep } from './ImportUploadStep'
import { kbErrorMessageKey, kbPackageAlertText, kbShowServerDetails } from './errors'
import { useDeleteImport, useStartImport } from './queries'
import { UploadError, uploadPackage } from './uploadSession'
import type { UploadSession, UploadStatus } from './uploadSession'
import type { DatasetImport, ImportSummary, TaskRef } from './types'

export type ImportDialogProps = {
  onClose: () => void
  /** Sukces `POST /start` — host (T6) dopisuje wiersz paska zadań: `addTask(ref, 'import', label, null)`. */
  onStarted: (ref: TaskRef, label: string) => void
}

/** Tekst błędu API wg slugi z K19 (nieznany → ogólny). */
function errorText(error: unknown, t: (key: string) => string): string {
  return t(error instanceof WdApiError ? kbErrorMessageKey(error.code) : 'kbTransfer.error.unknown')
}

type ImportPhase = 'pick' | 'uploading' | 'summary' | 'invalid'

export function ImportDialog(props: ImportDialogProps) {
  const { t, i18n } = useTranslation()
  const startImport = useStartImport()
  const deleteImport = useDeleteImport()
  // EN (K20 §5 p. 2): przyczyna po `code` z locale, komunikat serwera (PL) w zwiniętym bloku.
  const isEnglish = resolveLanguage(i18n.language) === 'en'
  // 08 §7.15(c): dialog pełnoekranowy < 600 px (390 px pełny ekran) — jak ExportDialog.
  const fullScreen = useFullScreenDialog()

  const [phase, setPhase] = useState<ImportPhase>('pick')
  const [received, setReceived] = useState(0)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState<UploadStatus>('uploading')
  const [pauseCode, setPauseCode] = useState<number | undefined>(undefined)
  const [emptyFile, setEmptyFile] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [summary, setSummary] = useState<ImportSummary | null>(null)
  const [packageErrors, setPackageErrors] = useState<DatasetImport['errors']>([])
  const [name, setName] = useState('')
  const [model, setModel] = useState('')
  /** 409 `name_conflict`: propozycja z `details` (`null` = brak konfliktu albo brak propozycji). */
  const [conflict, setConflict] = useState<string | null>(null)
  const sessionRef = useRef<UploadSession | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const importIdRef = useRef<string | null>(null)

  /** Wraca do kroku 1 i czyści stan sesji (po anulowaniu, błędzie, „Wybierz inny plik"). */
  function resetToPick(): void {
    sessionRef.current = null
    abortRef.current = null
    importIdRef.current = null
    setSummary(null)
    setPackageErrors([])
    setConflict(null)
    setPhase('pick')
  }

  /** Porzuca sesję wg fazy: wysyłka → `cancel()` (abort + delete), krok 2/błędy → `deleteImport`. */
  function discardSession(): void {
    if (phase === 'uploading') {
      abortRef.current?.abort()
      void sessionRef.current?.cancel().catch(() => undefined)
      return
    }
    if ((phase === 'summary' || phase === 'invalid') && importIdRef.current !== null) {
      // MINOR T2: po rozstrzygniętej wysyłce nie wołamy `cancel()` — kasujemy sesję wprost.
      deleteImport.mutate(importIdRef.current)
    }
  }

  /** Zamknięcie dialogu (✕/Esc/tło/„Anuluj"): porzuca sesję i zamyka. */
  function handleClose(): void {
    discardSession()
    props.onClose()
  }

  /** „Anuluj" w trakcie wysyłki: abort + `deleteImport`, powrót do kroku 1 (spec: DELETE sesji). */
  function handleCancelUpload(): void {
    abortRef.current?.abort()
    void sessionRef.current?.cancel().catch(() => undefined)
    resetToPick()
  }

  function startUpload(file: File): void {
    // Paczka 0 B (R-ING-03) — ostrzeżenie bez zakładania sesji (backend odrzuciłby 0 B 400).
    if (file.size === 0) {
      setUploadError(null)
      setEmptyFile(true)
      return
    }
    setEmptyFile(false)
    setUploadError(null)
    const controller = new AbortController()
    abortRef.current = controller
    setReceived(0)
    setTotal(file.size)
    setStatus('uploading')
    setPhase('uploading')
    const session = uploadPackage(file, {
      signal: controller.signal,
      onSession: (created) => {
        importIdRef.current = created.import_id
      },
      onProgress: (done, size) => {
        setReceived(done)
        setTotal(size)
      },
      onStatus: (next, code) => {
        setStatus(next)
        // Kod HTTP tylko przy pauzie po 5xx; każdy inny status go czyści.
        setPauseCode(next === 'paused' ? code : undefined)
      },
    })
    sessionRef.current = session
    void session.done
      .then((finished) => {
        if (controller.signal.aborted) return
        if (finished.state === 'invalid') {
          setPackageErrors(finished.errors)
          setPhase('invalid')
          return
        }
        // `state=ready`; brak podsumowania (nie zdarza się wg K19) → szkielet kroku 2.
        setSummary(finished.summary)
        if (finished.summary !== null) {
          const s = finished.summary
          setName(s.name_taken && s.suggested_name !== '' ? s.suggested_name : s.name)
          setModel(s.target.default_model ?? s.embedding.model_name)
        }
        setPhase('summary')
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setUploadError(
          error instanceof UploadError ? t('kbTransfer.import.emptyFile') : errorText(error, t),
        )
        // MINOR T6: twardy błąd wysyłki po założeniu sesji zostawia ją wiszącą do 24 h —
        // porzucamy ją wprost (best-effort: błąd DELETE ignorowany, mutacja nie rzuca).
        const importId = importIdRef.current
        if (importId !== null) deleteImport.mutate(importId)
        resetToPick()
      })
  }

  /** „Importuj" w kroku 2: start zadania; 409 `name_conflict` → błąd pod polem + Chip. */
  function startNow(): void {
    if (importIdRef.current === null) return
    setConflict(null)
    startImport.mutate(
      { importId: importIdRef.current, name: name.trim(), embeddingModel: model },
      {
        onSuccess: (ref) => {
          props.onStarted(ref, name.trim())
          props.onClose()
        },
        onError: (error) => {
          if (error instanceof WdApiError && error.code === 'name_conflict') {
            const suggested = error.details?.suggested_name
            setConflict(typeof suggested === 'string' ? suggested : null)
          }
          // Inne błędy startu zostają w dialogu jako Alert (stan mutacji).
        },
      },
    )
  }

  return (
    <Dialog
      open
      onClose={handleClose}
      fullScreen={fullScreen}
      maxWidth={false}
      slotProps={{ paper: { sx: fullScreen ? undefined : { width: 560 } } }}
    >
      <DialogTitle>{t('kbTransfer.import.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {startImport.isError && conflict === null ? (
            <Alert severity="error">{errorText(startImport.error, t)}</Alert>
          ) : null}
          {phase === 'pick' ? (
            <ImportDropzone onFiles={startUpload} emptyFile={emptyFile} errorText={uploadError} />
          ) : null}
          {phase === 'uploading' ? (
            <ImportUploadStep
              status={status}
              pauseCode={pauseCode}
              received={received}
              total={total}
              onResume={() => sessionRef.current?.resume()}
            />
          ) : null}
          {phase === 'summary' && summary !== null ? (
            <ImportSummaryStep
              summary={summary}
              name={name}
              onNameChange={(next) => {
                setName(next)
                // Edycja po 409 czyści błąd pod polem; ostrzeżenie `name_taken` wraca.
                setConflict(null)
              }}
              model={model}
              onModelChange={setModel}
              conflict={conflict}
            />
          ) : null}
          {phase === 'summary' && summary === null ? (
            <Stack spacing={1} data-testid="kb-import-skeleton">
              <Skeleton variant="text" width="60%" />
              <Skeleton variant="rounded" height={48} />
              <Skeleton variant="rounded" height={48} />
            </Stack>
          ) : null}
          {phase === 'invalid' ? (
            <Stack spacing={1} data-testid="kb-import-invalid">
              {/* Walidacja nieudana (K19, 08 §7.15(c)). EN (K20 §5 p. 2, QA V12-2-1 D1):
                  przyczyna po `code` z locale, polski komunikat serwera w zwiniętym bloku
                  szczegółów; PL bez zmian — komunikat API jako tekst Alertu. */}
              {packageErrors.map((error, index) => (
                <Alert key={index} severity="error">
                  {kbPackageAlertText(error, isEnglish, t)}
                  {kbShowServerDetails(error, isEnglish) ? (
                    <Box component="details" data-testid="kb-import-error-details" sx={{ mt: 0.5 }}>
                      <Box component="summary" sx={{ cursor: 'pointer', width: 'fit-content' }}>
                        {t('kbTransfer.error.details')}
                      </Box>
                      {error.message}
                    </Box>
                  ) : null}
                </Alert>
              ))}
            </Stack>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={phase === 'uploading' ? handleCancelUpload : handleClose}
          disabled={startImport.isPending}
        >
          {t('common.cancel')}
        </Button>
        {phase === 'summary' ? (
          <Button
            variant="contained"
            onClick={startNow}
            loading={startImport.isPending}
            disabled={name.trim() === ''}
          >
            {t('kbTransfer.import.button')}
          </Button>
        ) : null}
        {phase === 'invalid' ? (
          <Button
            variant="contained"
            onClick={() => {
              discardSession()
              resetToPick()
            }}
          >
            {t('kbTransfer.import.chooseAnother')}
          </Button>
        ) : null}
      </DialogActions>
    </Dialog>
  )
}
