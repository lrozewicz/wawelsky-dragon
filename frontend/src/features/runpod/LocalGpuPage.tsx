/**
 * Tab „Ten serwer” w Ustawienia → GPU: karty maszyny z Wawelsky Dragon (VRAM, wolna/zajęta), wybór
 * modelu i uruchomienie przez usługę `gpu-agent`. Zmiany robi tylko superużytkownik; pozostali widzą
 * stan wdrożeń.
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
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { useIsSuperuser } from '../settings/useIsSuperuser'

import { DeploymentsCard } from './DeploymentsCard'
import { LocalDeployProgress, LocalGpuTable } from './LocalGpuParts'
import { localModelsQueryOptions } from './api'

function LocalModelCard(): JSX.Element | null {
  const { t } = useTranslation()
  const models = useQuery(localModelsQueryOptions())
  const [chosenName, setChosenName] = useState<string | null>(null)
  const [gpuId, setGpuId] = useState<string | null>(null)
  const [deploying, setDeploying] = useState(false)
  const items = models.data ?? []
  const hosted = items.find((model) => model.name === chosenName) ?? items[0]
  if (hosted === undefined) return null

  return (
    <Card data-testid="local-model-card" data-model={hosted.name}>
      <CardContent>
        <Stack spacing={2}>
          <TextField
            select
            size="small"
            label={t('runpod.model.select')}
            value={hosted.name}
            onChange={(event) => {
              setChosenName(event.target.value)
              setGpuId(null)
            }}
            sx={{ maxWidth: 420 }}
            slotProps={{ htmlInput: { 'data-testid': 'local-model-select' } }}
          >
            {items.map((model) => (
              <MenuItem key={model.name} value={model.name}>
                {model.title}
              </MenuItem>
            ))}
          </TextField>
          <Typography variant="body2" color="text.secondary">
            {t('runpod.local.description', {
              name: hosted.name,
              hf: hosted.hf_model,
              min: hosted.min_vram_gb,
            })}
          </Typography>
          <LocalGpuTable model={hosted.name} selectedId={gpuId} onSelect={setGpuId} />
          <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
            <Button
              variant="contained"
              disabled={gpuId === null}
              onClick={() => setDeploying(true)}
              data-testid="local-deploy"
            >
              {t('runpod.local.deploy')}
            </Button>
          </Stack>
        </Stack>
        <Dialog open={deploying} onClose={() => setDeploying(false)} fullWidth maxWidth="sm">
          <DialogTitle>{t('runpod.local.deployTitle', { model: hosted.title })}</DialogTitle>
          <DialogContent>
            {deploying ? (
              <LocalDeployProgress
                model={hosted.name}
                gpuId={gpuId}
                onClose={() => setDeploying(false)}
              />
            ) : null}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  )
}

export function LocalGpuPage(): JSX.Element {
  const { t } = useTranslation()
  const isSuperuser = useIsSuperuser()
  return (
    <Stack spacing={2} data-testid="local-gpu-page">
      {isSuperuser ? (
        <LocalModelCard />
      ) : (
        <Alert severity="info">{t('runpod.local.readOnly')}</Alert>
      )}
      <DeploymentsCard isSuperuser={isSuperuser} scope="local" />
    </Stack>
  )
}
