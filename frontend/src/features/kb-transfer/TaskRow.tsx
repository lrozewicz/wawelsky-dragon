/**
 * Wiersz paska zadań eksportu/importu (08 §7.15 (b), CONTRACT WP E7-2 §2/§7). Stan z
 * `StoredKbTask.last`: „W kolejce” przed pierwszym odpytaniem (świeży wiersz, powrót po F5),
 * w trakcie etap z licznikiem `done/total`, `LinearProgress` i procent; po zakończeniu akcje
 * wg rodzaju (Pobierz / Kopiuj link albo Otwórz), Szczegóły błędu i ✕ (stany końcowe).
 * „Pobierz” to zwykły link z `download` (strumieniowanie przez przeglądarkę); po `expires_at`
 * przycisk nieaktywny z komunikatem o wygasłym linku, a odmowa schowka przy „Kopiuj link” pokazuje
 * komunikat i pole z linkiem (`CopyLinkFallback`). Poniżej progu `sm` kolumna; długa nazwa zawija
 * stan i akcje do drugiej linii (useFlexGap; stan ma basis `auto`, z 0 kurczył się do zera). */

import { useState } from 'react'
import type { ReactElement } from 'react'
import CloseIcon from '@mui/icons-material/Close'
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined'
import FileUploadOutlinedIcon from '@mui/icons-material/FileUploadOutlined'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../i18n'
import useNotifications from '../../hooks/useNotifications/useNotifications'
import { formatDateTime, formatDateTimeSeconds } from '../../lib/format'
import { WdApiError } from '../admin/wdClient'
import { copyToClipboard } from '../settings/api/copyToClipboard'

import { CopyLinkFallback } from './CopyLinkFallback'
import { kbErrorMessageKey } from './errors'
import { formatGrouped, formatPackageBytes } from './format'
import { describeTaskProgress } from './taskStore'
import { taskRowSx } from './taskRowSx'
import { useStopTask } from './queries'
import type { ExportResult, ImportResult, StoredKbTask, WdTask, WdTaskStatus } from './types'

export type TaskRowProps = {
  row: StoredKbTask
  /** Podświetlenie po 409 `export_in_progress` — przewinięcie robi `TaskBar`. */
  highlighted: boolean
  onRemove: (taskId: string) => void
}

/** Komunikat błędu API wg slugi z K19 (nieznany → ogólny) — wzór `ExportDialog`. */
function errorText(error: unknown, t: (key: string) => string): string {
  return t(error instanceof WdApiError ? kbErrorMessageKey(error.code) : 'kbTransfer.error.unknown')
}

/** Wynik eksportu (pole `download_url` występuje tylko w nim). */
function exportResult(task: WdTask | null): ExportResult | null {
  const result = task?.result ?? null
  return result !== null && 'download_url' in result ? result : null
}

/** Wynik importu (pole `dataset_id` występuje tylko w nim). */
function importResult(task: WdTask | null): ImportResult | null {
  const result = task?.result ?? null
  return result !== null && 'dataset_id' in result ? result : null
}
/** Potwierdzenie kopiowania znika po tej zwłoce (brief: Snackbar lub zmiana etykiety). */
const COPIED_RESET_MS = 2000

/** Link po terminie `expires_at` (K19 §3) — próg `<=`, wzór `formatExpiry` w ApiKeysDialog. */
function isLinkExpired(expiresAt: number): boolean {
  return Date.now() >= expiresAt
}

export function TaskRow(props: TaskRowProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const notifications = useNotifications()
  const stopMutation = useStopTask()
  const { row } = props
  const task = row.last
  const status: WdTaskStatus = task?.status ?? 'queued'
  const export_ = status === 'done' ? exportResult(task) : null
  const import_ = status === 'done' ? importResult(task) : null
  // Po `expires_at` przycisk nieaktywny + komunikat `export_expired` (K19 §3).
  const expired = export_ !== null && isLinkExpired(export_.expires_at)

  const [copied, setCopied] = useState(false)
  const [copyFallbackUrl, setCopyFallbackUrl] = useState<string | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)

  const iconColor = status === 'done' ? 'success' : status === 'failed' ? 'error' : 'action'
  const nameKey = row.kind === 'export' ? 'kbTransfer.bar.exportRow' : 'kbTransfer.bar.importRow'
  const nameText = t(nameKey, { name: row.label })

  async function copyLink(): Promise<void> {
    if (export_ === null) return
    setCopyFallbackUrl(null)
    // Link bezwzględny — da się otworzyć bez sesji (SC-E7-2-01 krok 7).
    const url = new URL(export_.download_url, window.location.origin).href
    if (!(await copyToClipboard(url))) {
      setCopyFallbackUrl(url) // schowek odmówił — komunikat i pole z linkiem do ręcznego skopiowania
      return
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), COPIED_RESET_MS)
  }

  function stop(): void {
    stopMutation.mutate(row.task_id, {
      onError: (error) => notifications.show(errorText(error, t), { severity: 'error' }),
    })
  }

  return (
    <Box
      data-testid="kb-task-row"
      data-task-kind={row.kind}
      data-task-id={row.task_id}
      data-task-status={status}
      data-highlighted={props.highlighted || undefined}
      sx={taskRowSx(status, props.highlighted)}
    >
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={{ xs: 0.5, sm: 2 }}
        useFlexGap
        /* Zawijanie tylko w wierszu (sm): w kolumnie (xs) `wrap` rozciąga elementy do szerokości LINII (max-content), nie kontenera — nazwa przestaje się skracać. */
        sx={{ alignItems: { xs: 'stretch', sm: 'center' }, flexWrap: { sm: 'wrap' } }}
      >
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', minWidth: 0 }}>
          {row.kind === 'export' ? (
            <FileDownloadOutlinedIcon fontSize="small" color={iconColor} />
          ) : (
            <FileUploadOutlinedIcon fontSize="small" color={iconColor} />
          )}
          {/* Długa nazwa: wielokropek, pełna nazwa w podpowiedzi (SC-E7-2-01 wariant). */}
          <Tooltip title={row.label}>
            <Typography variant="body2" noWrap sx={{ minWidth: 0 }} aria-label={nameText}>
              {nameText}
            </Typography>
          </Tooltip>
        </Stack>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', flex: '1 1 auto', minWidth: 0, flexWrap: 'wrap' }}
        >
          <StatusContent row={row} status={status} detailsOpen={detailsOpen} />
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', ml: 'auto' }}>
            {status === 'queued' || status === 'running' ? (
              <Button size="small" onClick={stop}>
                {t('kbTransfer.bar.stop')}
              </Button>
            ) : null}
            {export_ !== null ? (
              <>
                {/* Zwykły link z `download` — strumieniowanie przez przeglądarkę (paczka może
                    mieć 2 GB, nie mieści się w pamięci strony); po terminie nieaktywny. */}
                <Button
                  size="small"
                  variant="outlined"
                  component="a"
                  role="button"
                  href={export_.download_url}
                  download={export_.file_name}
                  disabled={expired}
                >
                  {t('kbTransfer.bar.download')}
                </Button>
                <Button size="small" variant="outlined" onClick={() => void copyLink()}>
                  {t(copied ? 'kbTransfer.bar.copied' : 'kbTransfer.bar.copyLink')}
                </Button>
              </>
            ) : null}
            {import_ !== null ? (
              <Button
                size="small"
                onClick={() => void navigate({ href: `/dataset/files/${import_.dataset_id}` })}
              >
                {t('kbTransfer.bar.open')}
              </Button>
            ) : null}
            {status === 'failed' ? (
              <Button
                size="small"
                aria-expanded={detailsOpen}
                onClick={() => setDetailsOpen((open) => !open)}
              >
                {t('kbTransfer.bar.details')}
              </Button>
            ) : null}
            {status === 'done' || status === 'failed' || status === 'cancelled' ? (
              <IconButton
                size="small"
                aria-label={t('kbTransfer.bar.dismiss')}
                onClick={() => props.onRemove(row.task_id)}
              >
                <CloseIcon fontSize="small" />
              </IconButton>
            ) : null}
          </Stack>
        </Stack>
      </Stack>
      {expired ? (
        <Typography variant="caption" color="error" role="alert">
          {t('kbTransfer.error.export_expired')}
        </Typography>
      ) : copyFallbackUrl !== null ? (
        <CopyLinkFallback url={copyFallbackUrl} />
      ) : null}
    </Box>
  )
}

/** Część wiersza zależna od stanu: komunikat, postęp, rozwinięte szczegóły błędu. */
function StatusContent(props: { row: StoredKbTask; status: WdTaskStatus; detailsOpen: boolean }) {
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const task = props.row.last
  const muted = (key: string): ReactElement => (
    <Typography variant="body2" color="text.secondary">
      {t(key)}
    </Typography>
  )

  if (task === null || props.status === 'queued') return muted('kbTransfer.bar.queued')
  if (props.status === 'running') {
    const progress = describeTaskProgress(task)
    const done = formatGrouped(progress.done, language)
    const total = formatGrouped(progress.total, language)
    const counter =
      progress.stageKey === ''
        ? t('kbTransfer.bar.progress', { done, total })
        : t('kbTransfer.bar.stageProgress', { stage: t(progress.stageKey), done, total })
    return (
      <>
        <Typography variant="body2" noWrap sx={{ minWidth: 0 }}>
          {counter}
        </Typography>
        <LinearProgress
          variant="determinate"
          value={progress.percent}
          aria-label={counter}
          sx={{ width: 120, flexShrink: 0 }}
        />
        <Typography variant="body2" sx={{ minWidth: 36, textAlign: 'right' }}>
          {t('kbTransfer.bar.percent', { value: progress.percent })}
        </Typography>
      </>
    )
  }
  if (props.status === 'done') {
    const export_ = exportResult(task)
    const import_ = importResult(task)
    if (export_ !== null) {
      return (
        <Typography variant="body2">
          {t('kbTransfer.bar.doneExport', {
            size: formatPackageBytes(export_.size_bytes, language),
            expiry: formatDateTime(export_.expires_at, language),
            created: formatDateTimeSeconds(task.created_at, language),
          })}
        </Typography>
      )
    }
    if (import_ !== null) {
      return (
        <Typography variant="body2">
          {t('kbTransfer.bar.doneImport', {
            files: t('kbTransfer.export.files', {
              count: import_.documents,
              n: formatGrouped(import_.documents, language),
            }),
            chunks: t('kbTransfer.export.chunks', {
              count: import_.chunks,
              n: formatGrouped(import_.chunks, language),
            }),
          })}
        </Typography>
      )
    }
    return muted('kbTransfer.bar.done')
  }
  if (props.status === 'failed') {
    return (
      <>
        <Typography variant="body2" color="error" noWrap sx={{ minWidth: 0 }}>
          {t('kbTransfer.bar.failed', {
            message: t(kbErrorMessageKey(task.error?.code ?? 'unknown')),
          })}
        </Typography>
        {props.detailsOpen && task.error !== null ? (
          <Typography variant="caption" color="text.secondary" sx={{ flexBasis: '100%' }}>
            {task.error.message}
          </Typography>
        ) : null}
      </>
    )
  }
  return muted('kbTransfer.bar.cancelled')
}
