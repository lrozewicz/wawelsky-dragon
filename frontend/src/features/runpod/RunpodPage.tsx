/**
 * Zakładka „RunPod” w Ustawieniach: klucz API, wybór GPU z filtrami, uruchomienie modelu
 * (karta per model hostowany) i lista wdrożeń z możliwością ręcznego wyłączenia poda. Zmiany robi tylko
 * superużytkownik (koszty); pozostali widzą stan.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Dialog from '@mui/material/Dialog'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { useIsSuperuser } from '../settings/useIsSuperuser'

import { DeployFlow } from './DeployFlow'
import { DeploymentsCard } from './DeploymentsCard'
import { GpuPicker } from './GpuPicker'
import type { GpuSelection } from './GpuPicker'
import { keyQueryOptions, modelsQueryOptions, useDeleteKey, useSaveKey } from './api'
import type { HostedModel } from './api'

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

function ModelCard(props: { hosted: HostedModel }): JSX.Element {
  const { hosted } = props
  const { t } = useTranslation()
  const [selection, setSelection] = useState<GpuSelection | null>(null)
  const [deploying, setDeploying] = useState(false)

  return (
    <Card data-testid="runpod-model-card" data-model={hosted.name}>
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

/** Po jednej karcie na każdy model hostowany przez WD (lista pochodzi z backendu). */
function ModelCards(props: { isSuperuser: boolean }): JSX.Element | null {
  const key = useQuery(keyQueryOptions())
  const models = useQuery(modelsQueryOptions())
  if (!props.isSuperuser || !key.data?.configured) return null
  return (
    <>
      {(models.data ?? []).map((hosted: HostedModel) => (
        <ModelCard key={hosted.name} hosted={hosted} />
      ))}
    </>
  )
}

export function RunpodPage(): JSX.Element {
  const isSuperuser = useIsSuperuser()
  return (
    <Stack spacing={2} data-testid="runpod-page">
      <KeyCard isSuperuser={isSuperuser} />
      <ModelCards isSuperuser={isSuperuser} />
      <DeploymentsCard isSuperuser={isSuperuser} />
    </Stack>
  )
}
