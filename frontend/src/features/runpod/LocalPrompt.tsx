/**
 * Pytanie przy starcie parsowania, gdy parser działa na GPU tego serwera, a model jest wyłączony.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import { useRouteContext } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { DatasetParserNotice } from './DatasetParserNotice'
import { LocalDeployProgress, LocalGpuTable } from './LocalGpuParts'
import { closeRunpodPrompt } from './promptStore'
import type { RunpodPrompt } from './promptStore'

export function LocalPrompt(props: { prompt: RunpodPrompt }): JSX.Element {
  const { prompt } = props
  const { preflight } = prompt
  const { t } = useTranslation()
  const isSuperuser = useRouteContext({
    from: '/_app',
    select: (context) => context.auth?.user?.is_superuser ?? false,
  })
  const model = preflight.model ?? ''
  const title = preflight.title ?? model
  const attachTo = preflight.deployment_id ?? null
  const [step, setStep] = useState<'ask' | 'deploy'>('ask')
  const [gpuId, setGpuId] = useState<string | null>(null)
  const parse = [{ dataset_id: prompt.datasetId, document_ids: prompt.documentIds }]

  return (
    <Dialog open onClose={closeRunpodPrompt} fullWidth maxWidth="md" data-testid="local-prompt">
      <DialogTitle>{t('runpod.local.promptTitle', { model: title })}</DialogTitle>
      <DialogContent>
        {!isSuperuser ? (
          <Alert severity="info">{t('runpod.prompt.askAdmin', { model: title })}</Alert>
        ) : step === 'deploy' ? (
          <LocalDeployProgress
            model={model}
            gpuId={gpuId}
            parse={parse}
            attachTo={attachTo}
            onClose={closeRunpodPrompt}
          />
        ) : (
          <Stack spacing={2}>
            <Alert severity="warning">
              {t(attachTo ? 'runpod.local.promptStarting' : 'runpod.local.promptOff', {
                model: title,
              })}
            </Alert>
            {attachTo ? null : (
              <LocalGpuTable model={model} selectedId={gpuId} onSelect={setGpuId} />
            )}
          </Stack>
        )}
        {step === 'ask' ? <DatasetParserNotice prompt={prompt} /> : null}
      </DialogContent>
      {step === 'ask' ? (
        <DialogActions>
          <Button onClick={closeRunpodPrompt} data-testid="local-prompt-no">
            {isSuperuser ? t('runpod.prompt.no') : t('runpod.common.close')}
          </Button>
          {isSuperuser ? (
            <Button
              variant="contained"
              disabled={attachTo === null && gpuId === null}
              onClick={() => setStep('deploy')}
              data-testid="local-prompt-yes"
            >
              {t('runpod.prompt.yes')}
            </Button>
          ) : null}
        </DialogActions>
      ) : null}
    </Dialog>
  )
}
