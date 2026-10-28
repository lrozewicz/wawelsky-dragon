/**
 * Wdrożenie modelu na wskazanym GPU: potwierdzenie ceny → tworzenie poda → postęp do gotowości.
 * Gdy GPU jest niedostępne (409 `gpu_unavailable` albo pod nie dostał maszyny), proponuje inne GPU
 * o tym samym lub większym VRAM i pozwala wybrać jedno z nich. Po gotowości WD samo uruchamia
 * parsowanie (`parse`), a pod jest kasowany po skończonej pracy.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import FormControlLabel from '@mui/material/FormControlLabel'
import Radio from '@mui/material/Radio'
import RadioGroup from '@mui/material/RadioGroup'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { WdApiError } from '../admin/wdClient'

import { DeploymentProgress } from './DeploymentProgress'
import {
  alternativesOf,
  gpusQueryOptions,
  isTerminal,
  useDeploy,
  useDeployment,
  useQueueParse,
} from './api'
import type { ParseTarget, RunpodGpu } from './api'
import type { GpuSelection } from './GpuPicker'

export type DeployFlowProps = {
  model: { name: string; title: string }
  selection: GpuSelection
  parse?: ParseTarget[]
  /** Trwające wdrożenie, do którego tylko dopisujemy parsowanie (zamiast tworzyć nowe). */
  attachTo?: string | null
  /** Zamknięcie okna (po zakończeniu albo rezygnacji). */
  onClose: () => void
}

type Phase =
  | { name: 'confirm' }
  | { name: 'alternatives'; options: RunpodGpu[]; reason: string }
  | { name: 'running'; id: string }

export function DeployFlow(props: DeployFlowProps): JSX.Element {
  const { model, selection, parse = [], attachTo = null, onClose } = props
  const { t } = useTranslation()
  const [gpu, setGpu] = useState<RunpodGpu>(selection.gpu)
  const [phase, setPhase] = useState<Phase>(
    attachTo ? { name: 'running', id: attachTo } : { name: 'confirm' },
  )
  const [picked, setPicked] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const deploy = useDeploy()
  const queueParse = useQueueParse()

  const start = (chosen: RunpodGpu): void => {
    setError(null)
    setGpu(chosen)
    deploy.mutate(
      {
        model: model.name,
        gpuId: chosen.id,
        cloud: selection.cloud,
        region: selection.region,
        country: selection.country,
        parse,
      },
      {
        onSuccess: (created) => setPhase({ name: 'running', id: created.id }),
        onError: (err) => {
          const options = alternativesOf(err)
          if (options.length > 0 || (err instanceof WdApiError && err.code === 'gpu_unavailable')) {
            setPicked(options[0]?.id ?? '')
            setPhase({ name: 'alternatives', options, reason: chosen.name })
            return
          }
          setError(err instanceof Error ? err.message : t('runpod.deploy.error'))
        },
      },
    )
  }

  if (phase.name === 'running') {
    return (
      <RunningStep
        id={phase.id}
        gpu={gpu}
        attachTo={attachTo}
        parse={parse}
        queueParse={queueParse.mutate}
        onChooseOther={(options) => {
          setPicked(options[0]?.id ?? '')
          setPhase({ name: 'alternatives', options, reason: gpu.name })
        }}
        onClose={onClose}
      />
    )
  }

  if (phase.name === 'alternatives') {
    const { options, reason } = phase
    return (
      <Stack spacing={2} data-testid="runpod-alternatives">
        <Alert severity="warning">{t('runpod.alternatives.unavailable', { gpu: reason })}</Alert>
        {options.length === 0 ? (
          <Alert severity="info">{t('runpod.alternatives.none')}</Alert>
        ) : (
          <>
            <Typography>
              {t('runpod.alternatives.intro', { vram: selection.gpu.vram_gb })}
            </Typography>
            <RadioGroup value={picked} onChange={(event) => setPicked(event.target.value)}>
              {options.map((option) => (
                <FormControlLabel
                  key={option.id}
                  value={option.id}
                  control={<Radio />}
                  data-testid={`runpod-alt-${option.id}`}
                  label={t('runpod.alternatives.option', {
                    name: option.name,
                    vram: option.vram_gb,
                    price: option.price_per_hr.toFixed(2),
                  })}
                />
              ))}
            </RadioGroup>
          </>
        )}
        {error ? <Alert severity="error">{error}</Alert> : null}
        <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>{t('runpod.common.cancel')}</Button>
          <Button
            variant="contained"
            disabled={picked === '' || deploy.isPending}
            onClick={() => {
              const chosen = options.find((option) => option.id === picked)
              if (chosen) start(chosen)
            }}
          >
            {t('runpod.alternatives.start')}
          </Button>
        </Stack>
      </Stack>
    )
  }

  return (
    <Stack spacing={2} data-testid="runpod-confirm">
      <Typography>
        {t('runpod.confirm.text', {
          model: model.title,
          gpu: gpu.name,
          vram: gpu.vram_gb,
          price: gpu.price_per_hr.toFixed(2),
        })}
      </Typography>
      <Alert severity="info">
        {t(parse.length > 0 ? 'runpod.confirm.autoDelete' : 'runpod.confirm.manualDelete')}
      </Alert>
      {parse.length > 0 ? <Alert severity="info">{t('runpod.confirm.autoParse')}</Alert> : null}
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
        <Button onClick={onClose}>{t('runpod.common.cancel')}</Button>
        <Button
          variant="contained"
          disabled={deploy.isPending}
          onClick={() => start(gpu)}
          data-testid="runpod-confirm-start"
        >
          {t('runpod.confirm.start')}
        </Button>
      </Stack>
    </Stack>
  )
}

type RunningStepProps = {
  id: string
  gpu: RunpodGpu
  attachTo: string | null
  parse: ParseTarget[]
  queueParse: (input: { id: string; target: ParseTarget }) => void
  onChooseOther: (options: RunpodGpu[]) => void
  onClose: () => void
}

function RunningStep(props: RunningStepProps): JSX.Element {
  const { id, gpu, attachTo, parse, queueParse, onChooseOther, onClose } = props
  const { t } = useTranslation()
  const deployment = useDeployment(id)
  const queued = useRef(false)
  const data = deployment.data
  // Dopięcie parsowania do wdrożenia, które już trwa (pytanie zadane w trakcie startu poda).
  useEffect(() => {
    if (attachTo === null || queued.current || parse.length === 0) return
    queued.current = true
    parse.forEach((target) => queueParse({ id: attachTo, target }))
  }, [attachTo, parse, queueParse])
  const failedForCapacity =
    data?.status === 'failed' && (data.error ?? '').startsWith('gpu_unavailable')
  const alternatives = useQuery({
    ...gpusQueryOptions({
      model: data?.model ?? '',
      cloud: (data?.cloud as 'SECURE' | 'COMMUNITY' | undefined) ?? 'SECURE',
      minVram: gpu.vram_gb,
      onlyAvailable: true,
    }),
    enabled: failedForCapacity,
  })

  return (
    <Stack spacing={2}>
      {data ? (
        <DeploymentProgress deployment={data} />
      ) : (
        <Typography>{t('runpod.loading')}</Typography>
      )}
      {failedForCapacity && alternatives.data ? (
        <Button
          variant="outlined"
          onClick={() => onChooseOther(alternatives.data.gpus.filter((g) => g.id !== gpu.id))}
        >
          {t('runpod.alternatives.pickOther')}
        </Button>
      ) : null}
      <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
        <Button onClick={onClose} data-testid="runpod-flow-close">
          {data && isTerminal(data.status)
            ? t('runpod.common.close')
            : t('runpod.progress.background')}
        </Button>
      </Stack>
    </Stack>
  )
}
