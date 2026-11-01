/**
 * Części wspólne panelu „Ten serwer” i pytania przy parsowaniu: tabela kart i postęp wdrożenia.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Radio from '@mui/material/Radio'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { DeploymentProgress } from './DeploymentProgress'
import {
  isTerminal,
  localGpusQueryOptions,
  useDeployment,
  useLocalDeploy,
  useQueueParse,
} from './api'
import type { ParseTarget } from './api'

function gigabytes(mib: number): string {
  return (mib / 1024).toFixed(1)
}

export function LocalGpuTable(props: {
  model: string
  selectedId: string | null
  onSelect: (id: string | null) => void
}): JSX.Element {
  const { model, selectedId, onSelect } = props
  const { t } = useTranslation()
  const list = useQuery(localGpusQueryOptions(model))
  const data = list.data
  const gpus = data?.gpus ?? []
  const selectedFree = gpus.some((gpu) => gpu.id === selectedId && gpu.free)

  useEffect(() => {
    if (selectedId !== null && data !== undefined && !selectedFree) onSelect(null)
  }, [data, selectedFree, selectedId, onSelect])

  if (list.isError) return <Alert severity="error">{t('runpod.local.unreachable')}</Alert>
  if (data === undefined) return <Typography>{t('runpod.loading')}</Typography>
  if (data.agent === 'not_configured') {
    return (
      <Alert severity="info" data-testid="local-gpu-not-configured">
        {t('runpod.local.notConfigured')}
      </Alert>
    )
  }
  if (data.agent === 'unreachable') {
    return (
      <Alert severity="error" data-testid="local-gpu-unreachable">
        {t('runpod.local.unreachable')}
      </Alert>
    )
  }
  if (gpus.length === 0) return <Alert severity="info">{t('runpod.local.noGpus')}</Alert>

  return (
    <Table size="small" aria-label={t('runpod.local.table')}>
      <TableHead>
        <TableRow>
          <TableCell />
          <TableCell>{t('runpod.local.gpu')}</TableCell>
          <TableCell align="right">{t('runpod.local.total')}</TableCell>
          <TableCell align="right">{t('runpod.local.freeVram')}</TableCell>
          <TableCell align="right">{t('runpod.local.usedVram')}</TableCell>
          <TableCell align="right">{t('runpod.local.load')}</TableCell>
          <TableCell>{t('runpod.local.state')}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {gpus.map((gpu) => (
          <TableRow key={gpu.id} data-testid={`local-gpu-${gpu.index}`}>
            <TableCell padding="checkbox">
              <Radio
                size="small"
                checked={gpu.id === selectedId}
                disabled={!gpu.free}
                onChange={() => onSelect(gpu.id)}
                slotProps={{ input: { 'aria-label': gpu.name } }}
              />
            </TableCell>
            <TableCell>{gpu.name}</TableCell>
            <TableCell align="right">
              {t('runpod.local.memory', { value: gigabytes(gpu.memory_total_mb) })}
            </TableCell>
            <TableCell align="right">
              {t('runpod.local.memory', { value: gigabytes(gpu.memory_free_mb) })}
            </TableCell>
            <TableCell align="right">
              {t('runpod.local.memory', { value: gigabytes(gpu.memory_used_mb) })}
            </TableCell>
            <TableCell align="right">
              {gpu.utilization_pct === null ? '–' : `${gpu.utilization_pct}%`}
            </TableCell>
            <TableCell>
              <Chip
                size="small"
                color={gpu.free ? 'success' : 'warning'}
                data-testid={`local-gpu-state-${gpu.index}`}
                label={
                  gpu.free
                    ? t('runpod.local.stateFree')
                    : t('runpod.local.stateBusy', { min: data.min_vram_gb })
                }
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/** Start wdrożenia (raz po otwarciu) albo dopięcie dokumentów do trwającego i postęp. */
export function LocalDeployProgress(props: {
  model: string
  gpuId: string | null
  parse?: ParseTarget[]
  attachTo?: string | null
  onClose: () => void
}): JSX.Element {
  const { model, gpuId, parse = [], attachTo = null, onClose } = props
  const { t } = useTranslation()
  const deploy = useLocalDeploy()
  const { mutate: queueParse } = useQueueParse()
  const [id, setId] = useState<string | null>(attachTo)
  const started = useRef(false)
  const deployment = useDeployment(id)
  const data = deployment.data

  useEffect(() => {
    if (started.current) return
    started.current = true
    if (attachTo !== null) {
      parse.forEach((target) => queueParse({ id: attachTo, target }))
    } else if (gpuId !== null) {
      deploy.mutate({ model, gpuId, parse }, { onSuccess: (created) => setId(created.id) })
    }
    // Jednorazowo po otwarciu; `started` chroni przed podwójnym wdrożeniem.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Stack spacing={2} data-testid="local-deploy-progress">
      {deploy.error ? (
        <Alert severity="error">{deploy.error.message || t('runpod.local.error')}</Alert>
      ) : data ? (
        <DeploymentProgress deployment={data} />
      ) : (
        <Typography>{t('runpod.loading')}</Typography>
      )}
      <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
        <Button onClick={onClose} data-testid="local-deploy-close">
          {deploy.error || (data && isTerminal(data.status))
            ? t('runpod.common.close')
            : t('runpod.progress.background')}
        </Button>
      </Stack>
    </Stack>
  )
}
