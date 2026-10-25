/**
 * Szuflada ustawień wyszukiwarki (08 §8.3): nazwa, opis, bazy wiedzy, podsumowanie AI (model,
 * pytania pokrewne) i „Zaawansowane”. Zapis to jeden `PUT /searches/{id}` z pełnym
 * `search_config`; sukces zamyka szufladę, błąd API ląduje w `Alert`, a niepoprawny formularz
 * i brak zmian wyłączają „Zapisz” z powodem (SC-V12-08, SC-V13-11). Wartości trzyma szuflada,
 * bo „brudny” (różny od `toFormValues(app)`) musi być znany przy zamknięciu: Escape, backdrop,
 * X i „Anuluj” pytają wtedy „Odrzucić zmiany?” — wspólny `useDiscardGuard` (SC-V12-07).
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Drawer from '@mui/material/Drawer'
import FormControlLabel from '@mui/material/FormControlLabel'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { DisabledReason, describedBy } from '../../../components/DisabledReason'
import { useDiscardGuard } from '../../../components/useDiscardGuard'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { datasetsListQueryOptions } from '../../chats/datasetsQuery'
import { buildModelOptions, modelsListQueryOptions } from '../../chats/modelsQuery'
import type { ModelOption } from '../../chats/modelsQuery'
import { useRerankOptions } from '../../datasets/retrieval/queries'
import { useUpdateSearchConfig } from '../queries'
import type { SearchApp } from '../queries'
import { AdvancedSection } from './AdvancedSection'
import { searchSettingsSchema, toFormValues } from './schema'
import type { SearchSettingsValues } from './schema'

export type SearchSettingsDrawerProps = {
  app: SearchApp
  open: boolean
  onClose: () => void
}

/** Opcja multi-selectu baz wiedzy: `id` trafia do `kb_ids`, `name` jest etykietą. */
type KbOption = { id: string; name: string }

/** Komunikat błędu zapisu: treść z `ApiError`, a przy błędzie transportu — tekst z i18n. */
function mutationError(error: unknown, fallback: string): string | null {
  return error instanceof ApiError && error.message !== '' ? error.message : fallback
}

// Pierwszy błąd walidacji → [klucz „Uzupełnij/Popraw”, etykieta pola] (szablony z datasetów
// i modeli, wzorzec `configSaveReason`).
const REASON_OF_FIELD: Record<string, [reason: string, label: string]> = {
  name: ['settings.models.reason.fillIn', 'searches.settings.name'],
  kbIds: ['datasets.config.reason.fixField', 'searches.settings.kbIds'],
  llmId: ['datasets.config.reason.fixField', 'searches.settings.llm'],
}

/**
 * Zawartość szuflady: montowana tylko przy `open`. Wartości dostaje od szuflady (patrz `dirty`),
 * `onCancel` przechodzi przez pytanie o odrzucenie zmian, a `onSaved` zamyka bez pytania.
 */
function SearchSettingsForm(props: {
  app: SearchApp
  values: SearchSettingsValues
  onChange: (changed: Partial<SearchSettingsValues>) => void
  onCancel: () => void
  onSaved: () => void
}) {
  const { app, values, onChange, onCancel, onSaved } = props
  const { t } = useTranslation()
  const { show } = useNotifications()

  const datasets = useQuery(datasetsListQueryOptions())
  const models = useQuery(modelsListQueryOptions())
  const rerankOptions = useRerankOptions()
  const update = useUpdateSearchConfig(app.id)

  const [error, setError] = useState<string | null>(null)

  const parsed = searchSettingsSchema.safeParse(values)
  const issues = parsed.success ? [] : parsed.error.issues
  const errorAt = (path: string): string | null =>
    issues.find((issue) => issue.path.map(String).join('.') === path)?.message ?? null
  const nameError = errorAt('name')
  const kbError = errorAt('kbIds')
  const llmError = errorAt('llmId')

  // Powód nieaktywnego „Zapisz” (DEC-372): błąd walidacji ma pierwszeństwo — pole z mapowania
  // (REASON_OF_FIELD) → komunikat pola; bez mapowania (dane spoza UI, §C.14c p. 1) → ogólny;
  // formularz poprawny bez zmian → wspólny „Brak zmian do zapisania” (SC-V13-11).
  const dirty = JSON.stringify(values) !== JSON.stringify(toFormValues(app))
  const reasonKeys = parsed.success ? undefined : REASON_OF_FIELD[String(issues[0]?.path[0])]
  const saveReason: string | null = reasonKeys
    ? t(reasonKeys[0], { field: t(reasonKeys[1]) })
    : !parsed.success
      ? t('searches.settings.reason.fixForm')
      : dirty
        ? null
        : t('common.noChangesToSave')

  function save(): void {
    if (!parsed.success) return
    update.mutate(values, {
      onSuccess: () => {
        show(t('searches.settings.saved'), { severity: 'success', autoHideDuration: 4000 })
        onSaved()
      },
      onError: (failure) => setError(mutationError(failure, t('searches.mutationError'))),
    })
  }

  // Bazy spoza pobranej listy (udostępnienie bez grantu, SC-V12-z-D3) zostają widoczne i usuwalne.
  const kbOptions: KbOption[] = (datasets.data ?? []).map(({ id, name }) => ({ id, name }))
  const knownKb = new Set(kbOptions.map((option) => option.id))
  for (const id of values.kbIds) {
    if (knownKb.has(id)) continue
    kbOptions.push({ id, name: t('common.kbUnavailable', { id: id.slice(-6) }) })
  }
  const selectedKbs = kbOptions.filter((option) => values.kbIds.includes(option.id))

  // Modele czatu z rejestru; bieżący model spoza listy dokładamy, żeby wartość nie zniknęła.
  const modelOptions = buildModelOptions(models.data ?? [], values.llmId, '')
  const selectedModel: ModelOption = modelOptions.find((option) => option.id === values.llmId) ?? {
    id: values.llmId,
    label: values.llmId,
  }

  return (
    <>
      {error !== null ? (
        <Alert severity="error" sx={{ mx: 2, mt: 1 }}>
          {error}
        </Alert>
      ) : null}
      <Box sx={{ p: 2, flex: 1, overflowY: 'auto' }}>
        <Stack spacing={2}>
          <TextField
            required
            fullWidth
            label={t('searches.settings.name')}
            value={values.name}
            error={nameError !== null}
            helperText={nameError !== null ? t(nameError) : undefined}
            onChange={(event) => onChange({ name: event.target.value })}
          />
          <TextField
            fullWidth
            multiline
            minRows={2}
            label={t('searches.settings.description')}
            value={values.description}
            onChange={(event) => onChange({ description: event.target.value })}
          />
          <Autocomplete
            multiple
            options={kbOptions}
            value={selectedKbs}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            getOptionLabel={(option) => option.name}
            noOptionsText={t('searches.settings.noDatasets')}
            onChange={(_event, next) => onChange({ kbIds: next.map((option) => option.id) })}
            renderInput={(params) => (
              <TextField
                {...params}
                label={t('searches.settings.kbIds')}
                error={kbError !== null}
                helperText={kbError !== null ? t(kbError) : undefined}
              />
            )}
          />
          <FormControlLabel
            control={
              <Switch
                checked={values.summary}
                onChange={(event) => onChange({ summary: event.target.checked })}
              />
            }
            label={t('searches.settings.summary')}
          />
          {values.summary ? (
            <Autocomplete
              options={modelOptions}
              value={selectedModel}
              isOptionEqualToValue={(option, value) => option.id === value.id}
              getOptionLabel={(option) => option.label}
              onChange={(_event, next) => onChange({ llmId: next?.id ?? '' })}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label={t('searches.settings.llm')}
                  error={llmError !== null}
                  helperText={llmError !== null ? t(llmError) : undefined}
                />
              )}
            />
          ) : null}
          <FormControlLabel
            control={
              <Switch
                checked={values.relatedSearch}
                onChange={(event) => onChange({ relatedSearch: event.target.checked })}
              />
            }
            label={t('searches.settings.related')}
          />

          <AdvancedSection values={values} rerankOptions={rerankOptions} onUpdate={onChange} />
        </Stack>
      </Box>
      <Stack
        direction="row"
        spacing={1}
        sx={{
          p: 2,
          justifyContent: 'flex-end',
          flexWrap: 'wrap',
          rowGap: 0.5,
          borderTop: 1,
          borderColor: 'divider',
        }}
      >
        <DisabledReason id="search-settings-save-reason" reason={saveReason} />
        <Button onClick={onCancel}>{t('searches.cancel')}</Button>
        <Button
          variant="contained"
          // SC-V12-08 (klik ≠ cichy no-op) i SC-V13-11 (brak zmian): obie przyczyny z powodem.
          disabled={!parsed.success || !dirty || update.isPending}
          loading={update.isPending}
          onClick={save}
          aria-describedby={describedBy('search-settings-save-reason', saveReason)}
        >
          {t('searches.settings.save')}
        </Button>
      </Stack>
    </>
  )
}

export function SearchSettingsDrawer(props: SearchSettingsDrawerProps) {
  const { app, open, onClose } = props
  const { t } = useTranslation()

  const [values, setValues] = useState<SearchSettingsValues>(() => toFormValues(app))
  const [lastOpen, setLastOpen] = useState(open)

  // Korekta stanu przy zmianie propsa `open` (wzorzec jak w `SearchBar`): otwarcie startuje od
  // świeżych wartości z `app` (gasić pytanie o odrzucenie umie sam `useDiscardGuard`).
  if (lastOpen !== open) {
    setLastOpen(open)
    setValues(toFormValues(app))
  }

  // „Brudny” = wartości inne niż wynik `toFormValues(app)` (proste dane — porównanie przez JSON).
  const dirty = JSON.stringify(values) !== JSON.stringify(toFormValues(app))

  // Strażnik niezapisanych zmian (SC-V12-07, zastąpił własny `ConfirmDialog` szuflady):
  // Esc/tło/✕/„Anuluj” przy brudnym formularzu pyta „Odrzucić zmiany?”.
  const { requestClose, dialog } = useDiscardGuard({ dirty, onClose, context: 'search', open })

  function patch(changed: Partial<SearchSettingsValues>): void {
    setValues((previous) => ({ ...previous, ...changed }))
  }

  return (
    <>
      <Drawer
        anchor="right"
        open={open}
        onClose={requestClose}
        slotProps={{ paper: { sx: { width: { xs: '100%', sm: 440 } } } }}
      >
        <Stack sx={{ height: '100%' }}>
          <Stack
            direction="row"
            sx={{ p: 2, pb: 1, alignItems: 'center', justifyContent: 'space-between' }}
          >
            <Typography variant="h6">{t('searches.settings.title')}</Typography>
            <IconButton aria-label={t('searches.settings.close')} onClick={requestClose}>
              <CloseIcon />
            </IconButton>
          </Stack>
          {open ? (
            <SearchSettingsForm
              app={app}
              values={values}
              onChange={patch}
              onCancel={requestClose}
              onSaved={onClose}
            />
          ) : null}
        </Stack>
      </Drawer>
      {dialog}
    </>
  )
}
