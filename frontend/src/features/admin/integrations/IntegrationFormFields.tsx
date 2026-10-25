/**
 * Pola formularza integracji (kontrakt WP E4-3c §1, brief T3 p. 2): dane połączenia, sekret
 * tylko do wpisania, listy wykluczeń i rozszerzeń oraz przełączniki. Komponent jest w pełni
 * sterowany — stan, walidacja i zapis zostają w `IntegrationFormDialog`.
 */

import type { JSX } from 'react'
import Autocomplete from '@mui/material/Autocomplete'
import FormControlLabel from '@mui/material/FormControlLabel'
import MenuItem from '@mui/material/MenuItem'
import type { SelectProps } from '@mui/material/Select'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { datasetsListQueryOptions } from '../../datasets/queries'

import type { IntegrationFormValues } from './schema'

/** Listy wykluczeń są dowolnym tekstem — brak podpowiedzi (`freeSolo`). */
const NO_SUGGESTIONS: readonly string[] = []

export type IntegrationFormFieldsProps = {
  mode: 'create' | 'edit'
  values: IntegrationFormValues
  /** Klucze i18n błędów per pole; `{}` = brak błędów (kontrakt §1). */
  errors: Record<string, string>
  /** Maska zapisanego sekretu („****abcd”) — podpowiedź przy edycji. */
  maskedSecret: string | null
  onChange: (patch: Partial<IntegrationFormValues>) => void
}

/** Liczba z pola tekstowego; puste/nieparsowalne traktujemy jak 0 (walidacja je odrzuci). */
function toNumber(raw: string): number {
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

export function IntegrationFormFields(props: IntegrationFormFieldsProps): JSX.Element {
  const { mode, values, errors, maskedSecret, onChange } = props
  const { t } = useTranslation()
  const datasets = useQuery(datasetsListQueryOptions())
  const datasetOptions = datasets.data ?? []
  // Id z zapisanej integracji może nie być na liście (inny użytkownik, świeży dataset) — wtedy
  // pokazujemy surowe id, żeby select nie był pusty.
  const orphanDataset =
    values.dataset_id !== '' && !datasetOptions.some((row) => row.id === values.dataset_id)

  /** Wspólne propsy pola: znacznik dla testów (kontrakt §1) i komunikat walidacji po `t()`. */
  function fieldProps(key: keyof IntegrationFormValues) {
    const message = errors[key]
    return {
      fullWidth: true,
      error: message !== undefined,
      helperText: message === undefined ? undefined : t(message),
      slotProps: { htmlInput: { 'data-testid': `integration-field-${key}` } },
    }
  }

  return (
    <Stack spacing={2}>
      <TextField
        {...fieldProps('name')}
        required
        autoFocus
        label={t('integrations.form.field.name')}
        value={values.name}
        onChange={(event) => onChange({ name: event.target.value })}
      />

      <TextField
        {...fieldProps('dataset_id')}
        select
        required
        label={t('integrations.form.field.dataset')}
        value={values.dataset_id}
        onChange={(event) => onChange({ dataset_id: event.target.value })}
        // Select ma własny slot — `htmlInput` z `fieldProps` siada na ukrytym inpucie, więc
        // znacznik kładziemy na samym `Select` (typ slotu nie zna `data-*`, stąd zawężenie).
        slotProps={{ select: { 'data-testid': 'integration-field-dataset_id' } as SelectProps }}
      >
        {datasetOptions.map((row) => (
          <MenuItem key={row.id} value={row.id}>
            {row.name}
          </MenuItem>
        ))}
        {orphanDataset ? <MenuItem value={values.dataset_id}>{values.dataset_id}</MenuItem> : null}
      </TextField>

      <TextField
        {...fieldProps('tenant_id')}
        required
        label={t('integrations.form.field.tenant')}
        value={values.tenant_id}
        onChange={(event) => onChange({ tenant_id: event.target.value })}
      />

      <TextField
        {...fieldProps('client_id')}
        required
        label={t('integrations.form.field.client')}
        value={values.client_id}
        onChange={(event) => onChange({ client_id: event.target.value })}
      />

      <TextField
        {...fieldProps('client_secret')}
        required={mode === 'create'}
        type="password"
        autoComplete="new-password"
        label={t('integrations.form.field.secret')}
        value={values.client_secret}
        // Przy edycji pole nigdy nie jest wypełniane — pokazujemy tylko maskę zapisanego sekretu.
        helperText={
          errors.client_secret !== undefined
            ? t(errors.client_secret)
            : maskedSecret === null
              ? undefined
              : t('integrations.form.secretKeep', { masked: maskedSecret })
        }
        onChange={(event) => onChange({ client_secret: event.target.value })}
      />

      <TextField
        {...fieldProps('site_url')}
        required
        label={t('integrations.form.field.siteUrl')}
        value={values.site_url}
        onChange={(event) => onChange({ site_url: event.target.value })}
      />

      <Autocomplete
        multiple
        freeSolo
        options={NO_SUGGESTIONS}
        value={values.excluded_library_names}
        onChange={(_event, next) => onChange({ excluded_library_names: next })}
        renderInput={(params) => (
          <TextField
            {...params}
            label={t('integrations.form.field.excludedLibraries')}
            slotProps={{
              ...params.slotProps,
              htmlInput: {
                ...params.slotProps.htmlInput,
                'data-testid': 'integration-field-excluded_library_names',
              },
            }}
          />
        )}
      />

      <Autocomplete
        multiple
        freeSolo
        options={NO_SUGGESTIONS}
        value={values.ignored_extensions}
        onChange={(_event, next) => onChange({ ignored_extensions: next })}
        renderInput={(params) => (
          <TextField
            {...params}
            label={t('integrations.form.field.ignoredExtensions')}
            slotProps={{
              ...params.slotProps,
              htmlInput: {
                ...params.slotProps.htmlInput,
                'data-testid': 'integration-field-ignored_extensions',
              },
            }}
          />
        )}
      />

      <TextField
        {...fieldProps('max_file_size_mb')}
        type="number"
        label={t('integrations.form.field.maxSizeMb')}
        value={values.max_file_size_mb}
        onChange={(event) => onChange({ max_file_size_mb: toNumber(event.target.value) })}
      />

      <TextField
        {...fieldProps('scan_interval_seconds')}
        type="number"
        label={t('integrations.form.field.interval')}
        value={values.scan_interval_seconds}
        onChange={(event) => onChange({ scan_interval_seconds: toNumber(event.target.value) })}
      />

      <FormControlLabel
        control={
          <Switch
            checked={values.delete_propagation}
            data-testid="integration-field-delete_propagation"
            onChange={(event) => onChange({ delete_propagation: event.target.checked })}
          />
        }
        label={t('integrations.form.field.deletePropagation')}
      />

      <FormControlLabel
        control={
          <Switch
            checked={values.is_active}
            data-testid="integration-field-is_active"
            onChange={(event) => onChange({ is_active: event.target.checked })}
          />
        }
        label={t('integrations.form.field.isActive')}
      />
    </Stack>
  )
}
