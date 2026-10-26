/**
 * Zakładka „RunPod” w Ustawieniach: klucz API, wybór GPU z filtrami, uruchomienie modelu
 * (Xiaomi-OCR-0) i lista wdrożeń z możliwością ręcznego wyłączenia poda. Zmiany robi tylko
 * superużytkownik (koszty); pozostali widzą stan.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Dialog from '@mui/material/Dialog'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { useIsSuperuser } from '../settings/useIsSuperuser'

import { DeployFlow } from './DeployFlow'
import { GpuPicker } from './GpuPicker'
import type { GpuSelection } from './GpuPicker'
import {
  deploymentsQueryOptions,
  keyQueryOptions,
  modelsQueryOptions,
  useDeleteKey,
  useSaveKey,
  useTerminate,
} from './api'
import type { RunpodDeployment } from './api'

const STATUS_COLOR: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  ready: 'success',
  failed: 'error',
  terminated: 'default',
  terminating: 'default',
}

function KeyCard(props: { isSuperuser: boolean }): JSX.Element {
  const { isSuperuser } = props
  const { t } = useTranslation()
  const status = useQuery(keyQueryOptions())
  const save = useSaveKey()
  const remove = useDeleteKey()
  const [value, setValue] = useState('')
  const error = save.error ?? remove.error

  return (
    <Card data-testid="runpod-key-card">
      <CardContent>
        <Stack spacing={1.5}>
          <Typography variant="h6">{t('runpod.key.title')}</Typography>
          <Typography variant="body2" color="text.secondary">
            {t('runpod.key.description')}
          </Typography>
          {status.data?.configured ? (
            <Alert severity="success" data-testid="runpod-key-ok">
              {t('runpod.key.configured', { hint: status.data.hint ?? '' })}
            </Alert>
          ) : (
            <Alert severity="warning">{t('runpod.key.missing')}</Alert>
          )}
          {error ? <Alert severity="error">{error.message}</Alert> : null}
          {isSuperuser ? (
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                type="password"
                autoComplete="off"
                label={t('runpod.key.label')}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                sx={{ flex: 1, maxWidth: 420 }}
                slotProps={{ htmlInput: { 'data-testid': 'runpod-key-input' } }}
              />
              <Button
                variant="contained"
                disabled={value.trim() === '' || save.isPending}
                onClick={() =>
                  save.mutate(value.trim(), {
                    onSuccess: () => setValue(''),
                  })
                }
                data-testid="runpod-key-save"
              >
                {t('runpod.key.save')}
              </Button>
              {status.data?.configured ? (
                <Button color="error" disabled={remove.isPending} onClick={() => remove.mutate()}>
                  {t('runpod.key.remove')}
                </Button>
              ) : null}
            </Stack>
          ) : (
            <Typography variant="body2">{t('runpod.readOnly')}</Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

function DeploymentsCard(props: { isSuperuser: boolean }): JSX.Element {
  const { isSuperuser } = props
  const { t } = useTranslation()
  const deployments = useQuery(deploymentsQueryOptions())
  const terminate = useTerminate()
  const rows = deployments.data ?? []

  return (
    <Card data-testid="runpod-deployments-card">
      <CardContent>
        <Stack spacing={1.5}>
          <Typography variant="h6">{t('runpod.deployments.title')}</Typography>
          {rows.length === 0 ? (
            <Typography color="text.secondary">{t('runpod.deployments.empty')}</Typography>
          ) : (
            <Table size="small" aria-label={t('runpod.deployments.title')}>
              <TableHead>
                <TableRow>
                  <TableCell>{t('runpod.deployments.model')}</TableCell>
                  <TableCell>{t('runpod.deployments.gpu')}</TableCell>
                  <TableCell>{t('runpod.deployments.status')}</TableCell>
                  <TableCell align="right">{t('runpod.deployments.cost')}</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row: RunpodDeployment) => (
                  <TableRow key={row.id} data-testid={`runpod-deployment-${row.id}`}>
                    <TableCell>{row.title}</TableCell>
                    <TableCell>
                      {t('runpod.deployments.gpuCell', {
                        name: row.gpu.name,
                        vram: row.gpu.vram_gb,
                      })}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={STATUS_COLOR[row.status] ?? 'info'}
                        label={t(`runpod.status.${row.status}`, { defaultValue: row.status })}
                      />
                      {row.error ? (
                        <Typography variant="caption" color="error" sx={{ display: 'block' }}>
                          {row.error}
                        </Typography>
                      ) : null}
                    </TableCell>
                    <TableCell align="right">
                      {t('runpod.units.usd', { value: row.cost_so_far.toFixed(2) })}
                    </TableCell>
                    <TableCell align="right">
                      {row.active && isSuperuser ? (
                        <Button
                          size="small"
                          color="error"
                          disabled={terminate.isPending}
                          onClick={() => terminate.mutate(row.id)}
                          data-testid={`runpod-terminate-${row.id}`}
                        >
                          {t('runpod.deployments.terminate')}
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

function ModelCard(props: { isSuperuser: boolean }): JSX.Element | null {
  const { isSuperuser } = props
  const { t } = useTranslation()
  const key = useQuery(keyQueryOptions())
  const models = useQuery(modelsQueryOptions())
  const [selection, setSelection] = useState<GpuSelection | null>(null)
  const [deploying, setDeploying] = useState(false)
  const hosted = models.data?.[0]
  if (!isSuperuser || !key.data?.configured || hosted === undefined) return null

  return (
    <Card data-testid="runpod-model-card">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6">{hosted.title}</Typography>
          <Typography variant="body2" color="text.secondary">
            {t('runpod.model.description', {
              hf: hosted.hf_model,
              min: hosted.min_vram_gb,
              recommended: hosted.recommended_vram_gb,
              name: hosted.name,
            })}
          </Typography>
          <GpuPicker
            model={hosted.name}
            initialMinVram={hosted.min_vram_gb}
            selectedId={selection?.gpu.id ?? null}
            onSelect={setSelection}
          />
          <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
            <Button
              variant="contained"
              disabled={selection === null}
              onClick={() => setDeploying(true)}
              data-testid="runpod-deploy"
            >
              {t('runpod.model.deploy')}
            </Button>
          </Stack>
        </Stack>
        <Dialog open={deploying} onClose={() => setDeploying(false)} fullWidth maxWidth="sm">
          <DialogTitle>{t('runpod.model.deployTitle', { model: hosted.title })}</DialogTitle>
          <DialogContent>
            {selection ? (
              <DeployFlow
                model={{ name: hosted.name, title: hosted.title }}
                selection={selection}
                onClose={() => setDeploying(false)}
              />
            ) : null}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  )
}

export function RunpodPage(): JSX.Element {
  const isSuperuser = useIsSuperuser()
  return (
    <Stack spacing={2} data-testid="runpod-page">
      <KeyCard isSuperuser={isSuperuser} />
      <ModelCard isSuperuser={isSuperuser} />
      <DeploymentsCard isSuperuser={isSuperuser} />
    </Stack>
  )
}
