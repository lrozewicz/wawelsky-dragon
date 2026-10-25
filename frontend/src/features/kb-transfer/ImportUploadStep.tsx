/**
 * Widok kroku wysyłki w dialogu importu: pasek postępu, „Wysłano a/b", „Wznawianie…" oraz stan
 * `paused` — po 5xx (`pauseCode`) komunikat „Serwer chwilowo niedostępny (503). Wysyłka
 * wstrzymana." i „Wznów wysyłkę", po błędzie sieci (bez kodu) „Wznów" jak dotąd (CONTRACT E67-z1a §C1/§C2).
 */

import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../i18n'

import { formatPackageBytes } from './format'
import type { UploadStatus } from './uploadSession'

export type ImportUploadStepProps = {
  status: UploadStatus
  /** Kod HTTP 5xx, który wstrzymał wysyłkę (`undefined` = błąd sieci albo brak pauzy). */
  pauseCode: number | undefined
  received: number
  total: number
  onResume: () => void
}

export function ImportUploadStep(props: ImportUploadStepProps) {
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const percent = props.total > 0 ? Math.round((props.received / props.total) * 100) : 0
  const serverPause = props.status === 'paused' && props.pauseCode !== undefined

  return (
    <Stack spacing={1} data-testid="kb-import-upload">
      <LinearProgress variant="determinate" value={percent} />
      {props.status === 'resuming' ? (
        <Typography variant="body2" color="text.secondary">
          {t('kbTransfer.import.resuming')}
        </Typography>
      ) : (
        <Typography variant="body2" color="text.secondary">
          {t('kbTransfer.import.uploaded', {
            received: formatPackageBytes(props.received, language),
            total: formatPackageBytes(props.total, language),
          })}
        </Typography>
      )}
      {serverPause ? (
        <Alert severity="warning">
          {t('kbTransfer.import.pausedServer', { code: props.pauseCode })}
        </Alert>
      ) : null}
      {props.status === 'paused' ? (
        <Box>
          <Button variant="outlined" onClick={props.onResume}>
            {serverPause ? t('kbTransfer.import.resumeUpload') : t('kbTransfer.import.resume')}
          </Button>
        </Box>
      ) : null}
    </Stack>
  )
}
