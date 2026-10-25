/**
 * Dialog dodawania/edycji instancji dostawcy (brief E3-6c1 T5b pkt 2): nazwa, base URL i klucz
 * API z walidacją zod oraz przycisk „Weryfikuj” wołający sondę połączenia. W trybie edycji dane
 * bierzemy z `instanceDetailQueryOptions(id)`; pole klucza zostaje puste („bez zmian”), a przy
 * weryfikacji z pustym kluczem wysyłamy `instance_id`, żeby backend użył zapisanego klucza.
 */

import * as React from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useForm } from '@tanstack/react-form'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import type { components } from '../../../api/schema.gen'
import { MASKED_API_KEY } from '../constants'
import {
  instanceDetailQueryOptions,
  useCreateInstance,
  useUpdateInstance,
  useVerifyConnection,
} from '../providerQueries'
import type { ProviderInstance, ProviderInstanceDetail } from '../providerQueries'

import {
  buildInstanceCreate,
  buildInstanceUpdate,
  instanceFormSchema,
  normalizeBaseUrl,
} from './instanceForm'

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

/** Klucz i18n pierwszego błędu pola; zod przez Standard Schema zwraca `{message}`. */
function errorKey(errors: readonly unknown[]): string | undefined {
  const issue = errors.find(
    (entry): entry is { message: string } =>
      typeof entry === 'object' &&
      entry !== null &&
      'message' in entry &&
      typeof entry.message === 'string',
  )
  return issue?.message
}

export type InstanceDialogProps = {
  /** Instancja do edycji; brak = tryb dodawania. */
  instance?: ProviderInstance
  onClose: () => void
}

/** Ładuje dane edycji, zanim zbudujemy formularz (pola startują z wartości instancji). */
export function InstanceDialog(props: InstanceDialogProps): React.JSX.Element {
  const { instance, onClose } = props
  const { t } = useTranslation()
  const isEdit = instance !== undefined
  const detail = useQuery({
    ...instanceDetailQueryOptions(instance?.id ?? ''),
    enabled: isEdit,
  })

  if (isEdit && detail.isPending) {
    return (
      <Dialog open onClose={onClose} fullWidth maxWidth="sm">
        <DialogContent>
          <Skeleton variant="rounded" height={160} data-testid="instance-dialog-loading" />
        </DialogContent>
      </Dialog>
    )
  }

  if (isEdit && (detail.isError || detail.data === undefined)) {
    return (
      <Dialog open onClose={onClose} fullWidth maxWidth="sm">
        <DialogContent>
          <Alert severity="error">
            {errorText(detail.error, t('settings.error.title'), t('settings.instances.error'))}
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>{t('settings.common.close')}</Button>
        </DialogActions>
      </Dialog>
    )
  }

  return <InstanceFormDialog instance={instance} detail={detail.data} onClose={onClose} />
}

type InstanceFormDialogProps = {
  instance?: ProviderInstance
  detail?: ProviderInstanceDetail
  onClose: () => void
}

function InstanceFormDialog(props: InstanceFormDialogProps): React.JSX.Element {
  const { instance, detail, onClose } = props
  const { t } = useTranslation()
  const isEdit = instance !== undefined
  const create = useCreateInstance()
  const update = useUpdateInstance()
  const verify = useVerifyConnection()
  const [verified, setVerified] = React.useState(false)

  const saveError = isEdit ? update.error : create.error
  const saveFailed = isEdit ? update.isError : create.isError
  const savePending = isEdit ? update.isPending : create.isPending

  const form = useForm({
    defaultValues: {
      name: detail?.instance_name ?? '',
      baseUrl: detail?.base_url ?? '',
      apiKey: '',
    },
    validators: { onSubmit: instanceFormSchema },
    onSubmit: ({ value }) => {
      if (instance !== undefined && detail !== undefined) {
        update.mutate(
          { id: instance.id, body: buildInstanceUpdate(value, detail) },
          {
            onSuccess: onClose,
          },
        )
        return
      }
      create.mutate(buildInstanceCreate(value), { onSuccess: onClose })
    },
  })

  /** Sonda połączenia: przy edycji z pustym kluczem podajemy `instance_id` zamiast klucza. */
  function verifyConnection(): void {
    setVerified(false)
    const { baseUrl, apiKey } = form.state.values
    const key = apiKey.trim()
    const body: components['schemas']['ProviderConnectionRequest'] = {
      base_url: normalizeBaseUrl(baseUrl),
      api_key: key === '' ? null : key,
      instance_id: key === '' && instance !== undefined ? instance.id : null,
    }
    verify.mutate(body, { onSuccess: () => setVerified(true) })
  }

  return (
    <Dialog
      open
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      slotProps={{
        paper: {
          component: 'form',
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            void form.handleSubmit()
          },
        },
      }}
    >
      <DialogTitle>
        {isEdit ? t('settings.instances.editTitle') : t('settings.instances.addTitle')}
      </DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {saveFailed ? (
            <Alert severity="error">
              {errorText(saveError, t('settings.error.title'), t('settings.instances.error'))}
            </Alert>
          ) : null}
          {verify.isError ? (
            <Alert severity="error">
              {errorText(verify.error, t('settings.error.title'), t('settings.instances.error'))}
            </Alert>
          ) : null}
          {verified ? <Alert severity="success">{t('settings.instances.verifyOk')}</Alert> : null}

          <form.Field name="name">
            {(field) => {
              const key = errorKey(field.state.meta.errors)
              return (
                <TextField
                  autoFocus
                  required
                  fullWidth
                  margin="dense"
                  label={t('settings.instances.name')}
                  value={field.state.value}
                  error={key !== undefined}
                  helperText={key === undefined ? undefined : t(key)}
                  onChange={(event) => field.handleChange(event.target.value)}
                  slotProps={{ htmlInput: { 'data-testid': 'instance-name-input' } }}
                />
              )
            }}
          </form.Field>

          <form.Field name="baseUrl">
            {(field) => {
              const key = errorKey(field.state.meta.errors)
              return (
                <TextField
                  required
                  fullWidth
                  margin="dense"
                  label={t('settings.instances.baseUrl')}
                  value={field.state.value}
                  error={key !== undefined}
                  helperText={key === undefined ? undefined : t(key)}
                  onChange={(event) => field.handleChange(event.target.value)}
                  slotProps={{ htmlInput: { 'data-testid': 'instance-base-url-input' } }}
                />
              )
            }}
          </form.Field>

          <form.Field name="apiKey">
            {(field) => (
              <TextField
                fullWidth
                margin="dense"
                type="password"
                label={t('settings.instances.apiKey')}
                placeholder={
                  detail?.api_key === MASKED_API_KEY
                    ? t('settings.instances.apiKeyUnchanged')
                    : undefined
                }
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
                slotProps={{ htmlInput: { 'data-testid': 'instance-api-key-input' } }}
              />
            )}
          </form.Field>
        </Stack>
      </DialogContent>

      <DialogActions sx={{ justifyContent: 'space-between' }}>
        <Button type="button" loading={verify.isPending} onClick={verifyConnection}>
          {t('settings.instances.verify')}
        </Button>
        <Stack direction="row" spacing={1}>
          <Button onClick={onClose}>{t('settings.common.cancel')}</Button>
          <Button type="submit" variant="contained" loading={savePending}>
            {t('settings.common.save')}
          </Button>
        </Stack>
      </DialogActions>
    </Dialog>
  )
}
