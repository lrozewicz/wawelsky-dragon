/**
 * Dialog „Dodaj model” do instancji (brief E3-6c1 T6 pkt 3 + E5-H8c T3): nazwa i typ wymagane,
 * okno kontekstu z domyślnym 8192, pole współbieżności dla wizji/embeddingu (`extra.max_concurrency`)
 * i pole wymiaru widoczne WYŁĄCZNIE dla typu `embedding`. Błąd 101/102 pokazujemy w `Alert`
 * (kontrakt §0); błędy walidacji pól blokują „Zapisz” (kontrakt WP E5-H8c §1).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import type { components } from '../../../api/schema.gen'
import { DisabledReason, describedBy } from '../../../components/DisabledReason'
import { MODEL_TYPES } from '../constants'
import type { ModelType } from '../constants'
import { useAddInstanceModel } from '../providerQueries'
import { ModelTextField } from './ModelTextField'
import {
  CONCURRENCY_DEFAULTS,
  supportsConcurrency,
  validateConcurrency,
  validateMaxTokens,
} from './modelForm'

/** Domyślna liczba tokenów nowego modelu (brief T6 pkt 3). */
export const DEFAULT_MAX_TOKENS = 8192

/** Wartości formularza dodawania modelu. */
export type AddModelForm = {
  name: string
  type: ModelType
  maxTokens: number
  /** Równoległe zapytania jako surowy tekst pola — puste = domyślne dostawcy (brak klucza). */
  concurrency: string
  /** Wymiar jako surowy tekst pola — liczby konwertujemy dopiero w ciele żądania. */
  dimension: string
}

/** Stan początkowy formularza; `close` i `submit` wracają do niego po sukcesie. */
function emptyForm(): AddModelForm {
  return { name: '', type: 'chat', maxTokens: DEFAULT_MAX_TOKENS, concurrency: '', dimension: '' }
}

/**
 * Ciało `POST …/models`: `extra.max_concurrency` tylko dla wizji/embeddingu z niepustym polem
 * (kontrakt WP E5-H8c §1), `wd_dimension` tylko dla embeddingu.
 * `max_tokens`/`extra`/`wd_dimension` są w schemacie opcjonalne (po E2-H2) — rzutowanie zbędne
 * (wzór: `buildInstanceCreate` w `instanceForm.ts`).
 */
export function buildAddModelBody(
  form: AddModelForm,
): components['schemas']['InstanceModelAddRequest'] {
  const base = { model_name: form.name.trim(), model_type: form.type, max_tokens: form.maxTokens }
  const concurrency = form.concurrency.trim()
  const withConcurrency =
    supportsConcurrency(form.type) && concurrency !== ''
      ? { ...base, extra: { max_concurrency: Number(concurrency) } }
      : base
  if (form.type !== 'embedding') {
    return withConcurrency
  }
  const dimension = form.dimension.trim()
  return { ...withConcurrency, wd_dimension: dimension === '' ? null : Number(dimension) }
}

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export type AddModelDialogProps = {
  instanceId: string
  open: boolean
  onClose: () => void
}

export function AddModelDialog(props: AddModelDialogProps): JSX.Element {
  const { instanceId, open, onClose } = props
  const { t } = useTranslation()
  const add = useAddInstanceModel(instanceId)
  const [form, setForm] = useState<AddModelForm>(emptyForm)
  const maxTokensError = validateMaxTokens(String(form.maxTokens))
  const showConcurrency = supportsConcurrency(form.type)
  const concurrencyError = showConcurrency ? validateConcurrency(form.concurrency) : null
  // Powód nieaktywnego „Zapisz” (SC-V12-08): pierwszy niespełniony warunek zapisu; `null`
  // oznacza formularz gotowy do wysłania — `canSave` jest jego dopełnieniem.
  const reason =
    form.name.trim() === ''
      ? t('settings.models.reason.fillIn', { field: t('settings.models.name') })
      : maxTokensError !== null
        ? t('settings.models.reason.fix', { field: t('settings.models.maxTokens') })
        : concurrencyError !== null
          ? t('settings.models.reason.fix', { field: t('settings.models.concurrency') })
          : null
  const canSave = reason === null

  function change<K extends keyof AddModelForm>(field: K, value: AddModelForm[K]): void {
    setForm((current) => ({ ...current, [field]: value }))
  }

  /** Zamknięcie czyści formularz i stan mutacji, więc ponowne otwarcie startuje od zera. */
  function close(): void {
    setForm(emptyForm())
    add.reset()
    onClose()
  }

  function submit(): void {
    add.reset()
    add.mutate(buildAddModelBody(form), { onSuccess: close })
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
      <DialogTitle>{t('settings.models.addTitle')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {add.isError ? (
            <Alert severity="error">
              {errorText(add.error, t('settings.error.title'), t('settings.models.error'))}
            </Alert>
          ) : null}

          {/* T8 (D5): bez `autoFocus` — fokus motywu jest czerwony (primary) i dialog od
              otwarcia wyglądał jak błąd walidacji; fokus zostaje na dialogu, pierwszy Tab
              przechodzi na pole nazwy. Etykieta statyczna nad polem jak w pozostałych polach. */}
          <ModelTextField
            id="add-model-name"
            required
            label={t('settings.models.name')}
            value={form.name}
            onChange={(event) => change('name', event.target.value)}
          />

          <ModelTextField
            select
            id="add-model-type"
            label={t('settings.models.type')}
            value={form.type}
            onChange={(event) => change('type', event.target.value as ModelType)}
            data-testid="add-model-type"
          >
            {MODEL_TYPES.map((type) => (
              <MenuItem key={type} value={type}>
                {t(`settings.models.type.${type}`)}
              </MenuItem>
            ))}
          </ModelTextField>

          <ModelTextField
            id="add-model-max-tokens"
            type="number"
            label={t('settings.models.maxTokens')}
            value={form.maxTokens}
            error={maxTokensError !== null}
            helperText={
              maxTokensError === null
                ? t('settings.models.maxTokensHelp')
                : t('settings.models.maxTokensError')
            }
            onChange={(event) => change('maxTokens', Number(event.target.value))}
            data-testid="add-model-max-tokens"
          />

          {showConcurrency ? (
            <ModelTextField
              id="add-model-concurrency"
              type="number"
              label={t('settings.models.concurrency')}
              value={form.concurrency}
              placeholder={t('settings.models.concurrencyPlaceholder', {
                value: CONCURRENCY_DEFAULTS[form.type],
              })}
              error={concurrencyError !== null}
              helperText={
                concurrencyError === null
                  ? t('settings.models.concurrencyHelp')
                  : t('settings.models.concurrencyError')
              }
              onChange={(event) => change('concurrency', event.target.value)}
              data-testid="model-concurrency"
            />
          ) : null}

          {form.type === 'embedding' ? (
            <ModelTextField
              id="add-model-dimension"
              type="number"
              label={t('settings.models.dimension')}
              value={form.dimension}
              onChange={(event) => change('dimension', event.target.value)}
              data-testid="add-model-dimension"
            />
          ) : null}
        </Stack>
      </DialogContent>

      <DialogActions sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
        {/* Powód nieaktywności pod przyciskiem, powiązany aria-describedby (SC-V12-08). */}
        <DisabledReason id="add-model-save-reason" reason={reason} />
        <Button onClick={close}>{t('settings.common.cancel')}</Button>
        <Button
          variant="contained"
          loading={add.isPending}
          disabled={!canSave}
          onClick={submit}
          aria-describedby={describedBy('add-model-save-reason', reason)}
        >
          {t('settings.common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
