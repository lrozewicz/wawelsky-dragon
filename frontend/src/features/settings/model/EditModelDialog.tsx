/**
 * Dialog „Edytuj model” (brief E5-H8c T3, kontrakt WP E5-H8c §1): okno kontekstu oraz — dla
 * wizji/embeddingu — równoległe zapytania (`extra.max_concurrency`, K13 „Poprawka 2026-10-10”).
 * Stan formularza resetowany przy każdym otwarciu z wartości `model` (wzór: `ChunkMethodDialog.tsx`);
 * zapis wysyła PATCH z PEŁNYM `extra` (`buildModelPatch`), więc nie gubi obcych kluczy.
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
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { DisabledReason, describedBy } from '../../../components/DisabledReason'
import { useUpdateInstanceModel } from '../providerQueries'
import type { InstanceModel } from '../providerQueries'
import { DEFAULT_MAX_TOKENS } from './AddModelDialog'
import { ModelTextField } from './ModelTextField'
import {
  buildModelPatch,
  CONCURRENCY_DEFAULTS,
  supportsConcurrency,
  validateConcurrency,
  validateMaxTokens,
} from './modelForm'

/** Wartości formularza edycji — surowe teksty pól; liczby konwertujemy dopiero w ciele PATCH. */
export type EditModelForm = {
  maxTokens: string
  concurrency: string
}

/**
 * Stan początkowy z modelu. Współbieżność równa domyślnej pokazujemy jako puste pole
 * (placeholder „domyślnie N”, SC-E5-H8c-04 krok 1); inna wartość wraca do edycji.
 */
export function formFromModel(model: InstanceModel): EditModelForm {
  const raw = model.extra['max_concurrency']
  const type = model.model_type
  return {
    // T7 (D1): zasiew tworzy modele bez `max_tokens` (NULL) — pole startuje od domyślnej
    // wartości backendu (`chat_pipeline`: `max_tokens or 8192`), nie puste z błędem „Co
    // najmniej 1024”; pusty tekst po zapisie i tak nie przeszedłby walidacji.
    maxTokens: String(model.max_tokens ?? DEFAULT_MAX_TOKENS),
    concurrency:
      supportsConcurrency(type) && typeof raw === 'number' && raw !== CONCURRENCY_DEFAULTS[type]
        ? String(raw)
        : '',
  }
}

/**
 * Etykiety typów — jak w `InstanceModelsGrid.tsx` (`image2text` to backendowe oznaczenie modelu
 * wizji). Kopia lokalna, żeby nie ciągnąć chunku siatki (`@mui/x-data-grid`) do dialogu.
 */
const TYPE_LABEL_KEYS: Record<string, string> = {
  chat: 'settings.models.type.chat',
  embedding: 'settings.models.type.embedding',
  rerank: 'settings.models.type.rerank',
  vision: 'settings.models.type.vision',
  image2text: 'settings.models.type.vision',
}

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export type EditModelDialogProps = {
  instanceId: string
  open: boolean
  /** Edytowany model; `null` przed pierwszym otwarciem (dialog schowany). */
  model: InstanceModel | null
  onClose: () => void
}

export function EditModelDialog(props: EditModelDialogProps): JSX.Element {
  const { instanceId, open, model, onClose } = props
  const { t } = useTranslation()
  const update = useUpdateInstanceModel(instanceId)
  // Start z wartości modelu (dialog może zamontować się od razu otwarty) + reset przy każdym
  // kolejnym otwarciu poniżej.
  const [form, setForm] = useState<EditModelForm>(() =>
    model === null ? { maxTokens: '', concurrency: '' } : formFromModel(model),
  )

  // „Reset przy otwarciu” wzorem Reacta: korekta stanu w renderze przy zmianie wartości propa
  // (efekt ze `setState` odrzuca lint: `react-hooks/set-state-in-effect`) — wzór `ChunkMethodDialog`.
  const [wasOpen, setWasOpen] = useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    if (open && model !== null) setForm(formFromModel(model))
  }

  if (model === null) {
    return <></>
  }

  // Zwężona referencja dla funkcji obsługi (TS nie przenosi zawężenia do deklaracji `function`).
  const current = model
  const showConcurrency = supportsConcurrency(current.model_type)
  const maxTokensError = validateMaxTokens(form.maxTokens)
  const concurrencyError = showConcurrency ? validateConcurrency(form.concurrency) : null
  // Powód nieaktywnego „Zapisz” (SC-V12-08): puste wymagane pole okna kontekstu albo błędna
  // wartość; `null` = formularz gotowy do wysłania — `canSave` jest jego dopełnieniem.
  const reason =
    form.maxTokens.trim() === ''
      ? t('settings.models.reason.fillIn', { field: t('settings.models.maxTokens') })
      : maxTokensError !== null
        ? t('settings.models.reason.fix', { field: t('settings.models.maxTokens') })
        : concurrencyError !== null
          ? t('settings.models.reason.fix', { field: t('settings.models.concurrency') })
          : null
  const canSave = reason === null
  const typeKey = TYPE_LABEL_KEYS[current.model_type]

  /** Zamknięcie czyści stan mutacji, więc ponowne otwarcie startuje bez Alertu po błędzie 500. */
  function close(): void {
    update.reset()
    onClose()
  }

  function submit(): void {
    update.reset()
    update.mutate(
      {
        modelName: current.name,
        body: buildModelPatch(current, {
          maxTokens: form.maxTokens,
          concurrency: form.concurrency,
        }),
      },
      { onSuccess: close },
    )
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
      <DialogTitle>{t('settings.models.editTitle', { name: current.name })}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {update.isError ? (
            <Alert severity="error">
              {errorText(update.error, t('settings.error.title'), t('settings.models.error'))}
            </Alert>
          ) : null}

          <Typography variant="body2" color="text.secondary" data-testid="edit-model-type">
            {t('settings.models.typeFixed', {
              type: typeKey === undefined ? current.model_type : t(typeKey),
            })}
          </Typography>

          <ModelTextField
            id="edit-model-max-tokens"
            type="number"
            label={t('settings.models.maxTokens')}
            value={form.maxTokens}
            error={maxTokensError !== null}
            helperText={
              maxTokensError === null
                ? t('settings.models.maxTokensHelp')
                : t('settings.models.maxTokensError')
            }
            onChange={(event) => setForm((prev) => ({ ...prev, maxTokens: event.target.value }))}
            // T8 (D3): etykieta statyczna nad polem (`ModelTextField`) — pływająca etykieta MUI
            // leżałaby na obramowaniu motywu i pierścieniu fokusa. Bez `InputLabel` MUI nie
            // dotyka już placeholdera (T7 D2), więc podpowiedzi nie trzeba `shrink`ować.
            slotProps={{ htmlInput: { 'data-testid': 'model-max-tokens' } }}
          />

          {showConcurrency ? (
            <ModelTextField
              id="edit-model-concurrency"
              type="number"
              label={t('settings.models.concurrency')}
              value={form.concurrency}
              placeholder={t('settings.models.concurrencyPlaceholder', {
                value: CONCURRENCY_DEFAULTS[current.model_type],
              })}
              error={concurrencyError !== null}
              helperText={
                concurrencyError === null
                  ? t('settings.models.concurrencyHelp')
                  : t('settings.models.concurrencyError')
              }
              onChange={(event) =>
                setForm((prev) => ({ ...prev, concurrency: event.target.value }))
              }
              slotProps={{ htmlInput: { 'data-testid': 'model-concurrency' } }}
            />
          ) : null}
        </Stack>
      </DialogContent>

      <DialogActions sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
        {/* Powód nieaktywności pod przyciskiem, powiązany aria-describedby (SC-V12-08). */}
        <DisabledReason id="edit-model-save-reason" reason={reason} />
        <Button onClick={close}>{t('settings.common.cancel')}</Button>
        <Button
          variant="contained"
          loading={update.isPending}
          disabled={!canSave}
          onClick={submit}
          aria-describedby={describedBy('edit-model-save-reason', reason)}
        >
          {t('settings.common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
