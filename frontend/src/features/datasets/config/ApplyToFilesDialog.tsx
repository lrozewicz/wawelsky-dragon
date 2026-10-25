/**
 * Dialog „Zastosować zmiany do istniejących plików?” (kontrakt WP E5-H8c §2, makieta 08 §8.1a).
 * Zapis datasetu (PUT) odbywa się wcześniej; tu użytkownik decyduje, czy zmienione pola
 * (metoda chunkowania / Parser PDF / zakres stron) nadpisać także w istniejących dokumentach.
 * Przy zmienionych metadanych obok „Tylko nowe pliki” stoi podpowiedź, że istniejące pliki
 * zachowają dotychczasowe metadane (SC-V12-09 k4).
 */

import { useRef, useState } from 'react'
import type { JSX } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { errorText } from '../../../lib/errorText'
import { translateServerMessage } from '../../../lib/serverMessages'
import type { DocumentRow } from '../files/queries'
import { documentKeys } from '../files/queries'
import { datasetKeys } from '../queries'
import { applyConfigToDocuments } from './applyToDocuments'
import type { ApplyFailure, ApplyProgress } from './applyToDocuments'

export type ApplyToFilesDialogProps = {
  open: boolean
  datasetId: string
  /** Dokumenty pobrane po zapisie (`listAllDocuments`) — decydują o N w przycisku i treści. */
  documents: DocumentRow[]
  /** Nowa metoda chunkowania — tylko gdy zmieniona, inaczej nie trafia do PATCH dokumentów. */
  chunkMethod?: string
  /** Zmienione klucze parser_config scalane z konfiguracją każdego dokumentu. */
  parserConfigChanges: Record<string, unknown>
  /** Etykiety zmienionych pól do wiersza „Zmieniono: …”. */
  changedLabels: string[]
  onClose: () => void
}

/**
 * „Zastosuj i parsuj ponownie” idzie przez `applyConfigToDocuments` (T5): PATCH każdego dokumentu
 * po kolei i JEDNO POST `…/chunks`; w trakcie „Zastosowano d/N” (przyciski nieaktywne), błąd
 * per plik w `Alert`, a dialog z błędami zostaje otwarty. Podwójny klik uruchamia jeden przebieg.
 */
export function ApplyToFilesDialog(props: ApplyToFilesDialogProps): JSX.Element {
  const { open, datasetId, documents, chunkMethod, parserConfigChanges, changedLabels, onClose } =
    props
  const { t } = useTranslation()
  const client = useQueryClient()
  const { show } = useNotifications()

  const [pending, setPending] = useState(false)
  const [progress, setProgress] = useState<ApplyProgress | null>(null)
  const [failures, setFailures] = useState<ApplyFailure[]>([])
  const [applyError, setApplyError] = useState<string | null>(null)

  // Podpowiedź przy „Tylko nowe pliki” (SC-V12-09 k4): tylko gdy zmieniono metadane
  // i dialog w ogóle ma istniejące pliki — inaczej wybór niczego dla metadanych nie zmienia.
  const metadataChanged =
    'enable_metadata' in parserConfigChanges || 'metadata' in parserConfigChanges

  // Straż podwójnego kliku: stan `pending` nie zdąży się odświeżyć między dwoma kliknięciami.
  const running = useRef(false)

  // Zamknięcie czyści stany błędów i postępu — ponowne otwarcie zaczyna od czystego dialogu.
  const close = (): void => {
    running.current = false
    setPending(false)
    setProgress(null)
    setFailures([])
    setApplyError(null)
    onClose()
  }

  const finish = (): void => {
    running.current = false
    setPending(false)
  }

  const apply = (): void => {
    if (running.current) return
    running.current = true
    setPending(true)
    setFailures([])
    setApplyError(null)
    setProgress({ done: 0, total: documents.length })
    void applyConfigToDocuments({
      datasetId,
      documents,
      chunkMethod,
      parserConfigChanges,
      onProgress: setProgress,
    })
      .then((result) => {
        void client.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
        void client.invalidateQueries({ queryKey: datasetKeys.detail(datasetId) })
        if (result.failures.length === 0) {
          show(t('datasets.config.saved'), { severity: 'success' })
          close()
        } else {
          // Reszta plików została przetworzona (POST szedł bez nieudanych) — dialog zostaje.
          setFailures(result.failures)
        }
      })
      .catch((error: unknown) => {
        // Błąd POST `…/chunks` (PATCH-e już poszły) albo transportu — komunikat i dialog zostaje.
        setApplyError(
          error instanceof ApiError && error.message !== ''
            ? errorText(error, t)
            : t('datasets.files.error.generic'),
        )
      })
      .finally(finish)
  }

  return (
    <Dialog
      open={open}
      // W trakcie zapisu nic nie zamyka dialogu — „Zastosuj…” musi się dokończyć (§2: nieaktywne).
      onClose={() => {
        if (!pending) close()
      }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>{t('datasets.config.apply.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5}>
          {changedLabels.length > 0 ? (
            <DialogContentText>
              {t('datasets.config.apply.changed', { fields: changedLabels.join(', ') })}
            </DialogContentText>
          ) : null}
          <DialogContentText>
            {t('datasets.config.apply.body', { count: documents.length })}
          </DialogContentText>
          {'enable_metadata' in parserConfigChanges || 'metadata' in parserConfigChanges ? (
            <DialogContentText>{t('datasets.config.apply.hint')}</DialogContentText>
          ) : null}
          {applyError !== null ? <Alert severity="error">{applyError}</Alert> : null}
          {failures.map((failure) => (
            <Alert key={failure.documentId} severity="error">
              {t('datasets.config.apply.fileError', {
                name: failure.name,
                // Komunikat serwera tłumaczony przy wyświetleniu (T3b); bez koperty — bez zmian.
                message:
                  failure.code === undefined
                    ? failure.message
                    : translateServerMessage(failure.code, failure.message, t),
              })}
            </Alert>
          ))}
          {pending && progress !== null ? (
            <Typography>
              {t('datasets.config.apply.progress', {
                done: progress.done,
                total: progress.total,
              })}
            </Typography>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ flexWrap: 'wrap' }}>
        {metadataChanged && documents.length > 0 ? (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mr: 'auto', maxWidth: '100%', pt: 0.5 }}
          >
            {t('datasets.config.apply.newOnlyHint')}
          </Typography>
        ) : null}
        <Button disabled={pending} onClick={close}>
          {t('datasets.config.apply.newOnly')}
        </Button>
        <Button variant="contained" disabled={pending} loading={pending} onClick={apply}>
          {t('datasets.config.apply.reparse', { count: documents.length })}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
