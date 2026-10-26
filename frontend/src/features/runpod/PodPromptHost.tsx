/**
 * Okno „Pod {model} jest wyłączony — włączyć?” (start parsowania modelem z RunPod przy braku poda).
 * Mount w powłoce aplikacji. Superuser: wybór GPU (domyślnie poprzednio użyte, a gdy niedostępne —
 * inne o tym samym lub większym VRAM) → wdrożenie → automatyczne parsowanie → automatyczne usunięcie
 * poda. Pozostali użytkownicy dostają informację, by poprosić administratora.
 */

import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import { useRouteContext } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { DeployFlow } from './DeployFlow'
import { GpuPicker } from './GpuPicker'
import type { GpuSelection } from './GpuPicker'
import { gpusQueryOptions } from './api'
import { closeRunpodPrompt, registerRunpodPromptHost, useRunpodPrompt } from './promptStore'

type Step = 'ask' | 'pick' | 'deploy'

/** Wdrożenie już trwa: do `DeployFlow` wystarczy GPU z poprzedniego wpisu (tylko do wyświetlenia). */
function attachSelection(last: { id: string; name: string; vram_gb: number } | null): GpuSelection {
  const gpu = {
    ...(last ?? { id: '', name: '', vram_gb: 0 }),
    price_per_hr: 0,
    availability: 'HIGH',
    data_centers: [],
    fits: true,
  }
  return { gpu, cloud: 'SECURE', region: '', country: '' }
}

function useIsSuperuserSafe(): boolean {
  return useRouteContext({
    from: '/_app',
    select: (context) => context.auth?.user?.is_superuser ?? false,
  })
}

export function PodPromptHost(): JSX.Element | null {
  const prompt = useRunpodPrompt()
  useEffect(() => registerRunpodPromptHost(), [])
  if (prompt === null) return null
  return <PromptDialog key={`${prompt.datasetId}:${prompt.documentIds.join(',')}`} />
}

function PromptDialog(): JSX.Element | null {
  const prompt = useRunpodPrompt()
  const { t } = useTranslation()
  const isSuperuser = useIsSuperuserSafe()
  const [step, setStep] = useState<Step>('ask')
  const [selection, setSelection] = useState<GpuSelection | null>(null)
  const preflight = prompt?.preflight
  const last = preflight?.last_gpu ?? null
  const minVram = Math.max(last?.vram_gb ?? 0, preflight?.min_vram_gb ?? 0)
  const model = preflight?.model ?? ''
  const title = preflight?.title ?? model

  // Domyślny wybór: poprzednie GPU, jeśli wciąż jest dostępne (lista już zawężona do ≥ VRAM).
  const candidates = useQuery({
    ...gpusQueryOptions({ model, cloud: 'SECURE', minVram, onlyAvailable: true }),
    enabled: isSuperuser && step === 'pick' && model !== '',
  })
  const lastStillThere = candidates.data?.gpus.find((gpu) => gpu.id === last?.id)
  const lastGone = candidates.data !== undefined && last !== null && lastStillThere === undefined
  const chosen: GpuSelection | null =
    selection ??
    (lastStillThere ? { gpu: lastStillThere, cloud: 'SECURE', region: '', country: '' } : null)

  if (prompt === null || preflight === undefined) return null
  const target = [{ dataset_id: prompt.datasetId, document_ids: prompt.documentIds }]
  const inProgress = preflight.deployment_id !== null && preflight.deployment_id !== undefined

  return (
    <Dialog open onClose={closeRunpodPrompt} fullWidth maxWidth="md" data-testid="runpod-prompt">
      <DialogTitle>{t('runpod.prompt.title', { model: title })}</DialogTitle>
      <DialogContent>
        {!isSuperuser ? (
          <Alert severity="info">{t('runpod.prompt.askAdmin', { model: title })}</Alert>
        ) : step === 'ask' ? (
          <Alert severity="warning">
            {inProgress
              ? t('runpod.prompt.starting', { model: title })
              : t('runpod.prompt.off', { model: title })}
          </Alert>
        ) : step === 'pick' ? (
          <GpuPicker
            model={model}
            initialMinVram={minVram > 0 ? minVram : undefined}
            initialOnlyAvailable
            selectedId={chosen?.gpu.id ?? null}
            onSelect={setSelection}
            notice={
              lastGone ? (
                <Alert severity="warning" data-testid="runpod-last-gone">
                  {t('runpod.prompt.lastGone', { gpu: last?.name ?? '', vram: last?.vram_gb ?? 0 })}
                </Alert>
              ) : lastStillThere ? (
                <Alert severity="info">
                  {t('runpod.prompt.lastReused', { gpu: lastStillThere.name })}
                </Alert>
              ) : null
            }
          />
        ) : selection || (inProgress && last) ? (
          <DeployFlow
            model={{ name: model, title }}
            selection={selection ?? attachSelection(last)}
            parse={target}
            attachTo={inProgress ? (preflight.deployment_id ?? null) : null}
            onClose={closeRunpodPrompt}
          />
        ) : null}
      </DialogContent>
      {step !== 'deploy' ? (
        <DialogActions>
          <Button onClick={closeRunpodPrompt} data-testid="runpod-prompt-no">
            {isSuperuser ? t('runpod.prompt.no') : t('runpod.common.close')}
          </Button>
          {isSuperuser && step === 'ask' ? (
            <Button
              variant="contained"
              onClick={() => setStep(inProgress ? 'deploy' : 'pick')}
              data-testid="runpod-prompt-yes"
            >
              {t('runpod.prompt.yes')}
            </Button>
          ) : null}
          {isSuperuser && step === 'pick' ? (
            <Button
              variant="contained"
              disabled={chosen === null}
              onClick={() => {
                setSelection(chosen)
                setStep('deploy')
              }}
              data-testid="runpod-prompt-next"
            >
              {t('runpod.prompt.next')}
            </Button>
          ) : null}
        </DialogActions>
      ) : null}
    </Dialog>
  )
}
