/**
 * Postęp wdrożenia modelu na RunPod: etap (GPU → obraz → model → gotowe), koszt i błąd.
 * Dane z `useDeployment` (odpytywanie co kilka sekund, dopóki pod nie osiągnie stanu końcowego).
 */

import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { RunpodDeployment } from './api'

/** Procent paska dla stanu poda (stany końcowe dają 100 albo 0). */
const PROGRESS: Record<string, number> = {
  requested: 5,
  provisioning: 15,
  starting: 45,
  loading: 75,
  ready: 100,
  terminating: 100,
  terminated: 100,
}

export function deploymentPercent(status: string): number {
  return PROGRESS[status] ?? 0
}

export type DeploymentProgressProps = {
  deployment: RunpodDeployment
}

export function DeploymentProgress(props: DeploymentProgressProps): JSX.Element {
  const { deployment } = props
  const { t } = useTranslation()
  const failed = deployment.status === 'failed'
  const known = deployment.status in PROGRESS || failed

  return (
    <Stack spacing={1.5} data-testid="runpod-progress">
      <Typography variant="subtitle1">
        {t('runpod.progress.title', {
          model: deployment.title,
          gpu: deployment.gpu.name,
        })}
      </Typography>
      <LinearProgress
        variant="determinate"
        value={failed ? 0 : deploymentPercent(deployment.status)}
        color={failed ? 'error' : deployment.status === 'ready' ? 'success' : 'primary'}
        aria-label={t('runpod.progress.label')}
      />
      <Typography data-testid="runpod-progress-status">
        {known ? t(`runpod.status.${deployment.status}`) : deployment.status}
      </Typography>
      {deployment.status === 'ready' && deployment.pending_documents > 0 ? (
        <Alert severity="info">{t('runpod.progress.parseStarted')}</Alert>
      ) : null}
      {failed && deployment.error ? <Alert severity="error">{deployment.error}</Alert> : null}
      <Typography variant="body2" color="text.secondary">
        {t('runpod.progress.cost', {
          price: deployment.price_per_hr.toFixed(2),
          cost: deployment.cost_so_far.toFixed(3),
        })}
      </Typography>
    </Stack>
  )
}
