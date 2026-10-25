/**
 * Zakładka „Konfiguracja” szczegółów datasetu (08 §7.4, §8.1; kontrakt WP E3-3a §T4):
 * formularz ustawień bazy (max 768 px) i karta „O tej metodzie chunkowania” (`fields.tsx`).
 * Zapis to jeden PUT z wyłącznie zmienionymi polami (`buildConfigPatch`); pola dotykające
 * istniejące dokumenty mają podpowiedź „Dotyczy nowych plików”, a gdy po zapisie któraś się
 * zmieniła i dataset ma dokumenty, `useSaveWithApply` otwiera `ApplyToFilesDialog` (E5-H8c §2).
 * Model embeddingu zablokowany przy istniejących chunkach; po sukcesie bazą formularza staje
 * się dataset z odpowiedzi PUT. Sekcja „Metadane” zapisuje się wg kolejności kontraktu
 * WP E6-1b §1 (`useMetadataConfig`). Walidacja U11: „Zapisz” wyłącza brak zmian; błędy pól
 * tekstowych ujawniają się po opuszczeniu pola albo próbie wysłania, a klik przy błędzie
 * wraca fokusem do pierwszego błędnego pola. Błędy wczytanych danych widać od razu.
 */

import { useMemo, useRef, useState } from 'react'
import type { JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Grid from '@mui/material/Grid'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import { useTranslation } from 'react-i18next'

import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { modelsListQueryOptions } from '../../chats/modelsQuery'
import { CHUNK_METHODS, useUpdateDataset } from '../queries'
import type { ChunkMethod, Dataset } from '../queries'
import { ApplyToFilesDialog } from './ApplyToFilesDialog'
import { AdvancedFields, CHUNK_TOKEN_SLIDER, MethodCard, PagesEditor, ValueSlider } from './fields'
import { configSaveReason, escapedDelimiter, modelNames, mutationMessage } from './helpers'
import { MetadataSection } from './MetadataSection'
import { SaveFooter } from './SaveFooter'
import {
  LAYOUT_OPTIONS,
  LAYOUT_VALUES,
  buildConfigPatch,
  configSchema,
  datasetToValues,
  visionModelNames,
  type ConfigValues,
} from './schema'
import { useMetadataConfig } from './useMetadataConfig'
import { useSaveWithApply } from './useSaveWithApply'

export type ConfigurationTabProps = {
  dataset: Dataset
}

export function ConfigurationTab(props: ConfigurationTabProps): JSX.Element {
  const { dataset } = props
  const { t } = useTranslation()
  const models = useQuery(modelsListQueryOptions())
  const update = useUpdateDataset(dataset.id)
  const applyFlow = useSaveWithApply(dataset.id)
  const meta = useMetadataConfig(dataset.id)
  const notifications = useNotifications()

  // `baseline` to baza porównania łatki: po udanym PUT-em jest nią dataset z odpowiedzi.
  const [baseline, setBaseline] = useState<Dataset>(dataset)
  const [values, setValues] = useState<ConfigValues>(() => datasetToValues(dataset))
  const [error, setError] = useState<string | null>(null)
  // Błąd zapisu pól metadanych — osobno od błędu PUT datasetu: komunikat przy sekcji pól (T4).
  const [metaError, setMetaError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const descriptionRef = useRef<HTMLInputElement>(null)
  const layoutRef = useRef<HTMLInputElement>(null)
  const initial = useMemo(() => datasetToValues(baseline), [baseline])
  const visionNames = visionModelNames(models.data ?? [])
  const parsed = configSchema.safeParse(values)
  // Walidacja parsera zależy od listy modeli (ładowanej osobno), więc dołączamy ją obok zod.
  const layoutUnknown = ![...LAYOUT_VALUES, ...visionNames].includes(values.layout_recognize)
  const issues: { path: PropertyKey[]; message: string }[] = parsed.success
    ? []
    : parsed.error.issues.map((issue) => ({ path: issue.path, message: issue.message }))
  if (layoutUnknown) {
    issues.push({ path: ['layout_recognize'], message: 'datasets.config.layout.unknownError' })
  }
  const errorAt = (path: string): string | null => {
    const issue = issues.find((item) => item.path.map(String).join('.') === path)
    return issue === undefined ? null : t(issue.message)
  }
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(new Set())
  const reveal = (path: string): void => setRevealed((previous) => new Set(previous).add(path))
  const shownErrorAt = (path: string): string | null => (revealed.has(path) ? errorAt(path) : null)
  const fieldRefs = { name: nameRef, description: descriptionRef, layout_recognize: layoutRef }
  const patch = buildConfigPatch(baseline, values, meta.fields ?? undefined)
  const embeddingLocked = baseline.chunk_count > 0
  const saveReason = configSaveReason(t, Object.keys(patch).length === 0, meta.hasError)

  const change = (changed: Partial<ConfigValues>): void => {
    setValues((previous) => ({ ...previous, ...changed }))
  }
  function submit(): void {
    setError(null)
    setMetaError(null)
    const paths = issues.map((issue) => issue.path.map(String).join('.'))
    setRevealed(new Set(paths))
    if (issues.length > 0) {
      fieldRefs[paths[0] as keyof typeof fieldRefs]?.current?.focus()
      return
    }
    // `baseline` jeszcze PRZED podmianą na odpowiedź PUT; pytanie o pliki po sukcesie (§2).
    const baselineParserConfig = baseline.parser_config
    const saveDataset = (): void =>
      update.mutate(patch, {
        onSuccess: (updated) => {
          setBaseline(updated)
          setValues(datasetToValues(updated))
          // Toast zamiast alertu na górze długiego formularza — „Zapisz” jest na dole (QA D3).
          notifications.show(t('datasets.config.saved'), { severity: 'success' })
          void applyFlow.open(patch, baselineParserConfig)
        },
        onError: (failure) => setError(mutationMessage(failure, t('datasets.config.saveError'), t)),
      })
    // Kolejność wg kontraktu WP E6-1b §1 — `useMetadataConfig.saveOrdered`; błąd pól przy sekcji (T4).
    meta.saveOrdered(patch, saveDataset, (failure) =>
      setMetaError(mutationMessage(failure, t('datasets.config.metadata.saveError'), t)),
    )
  }
  function cancel(): void {
    setValues(initial)
    // Pola metadanych wracają do danych zapytania (stan zapisany — to samo źródło co GET).
    meta.discardEdits()
    setError(null)
    setMetaError(null)
    setRevealed(new Set())
  }

  const embeddingField = (
    <Autocomplete
      options={modelNames(models.data ?? [], 'embedding', values.embedding_model)}
      value={values.embedding_model === '' ? null : values.embedding_model}
      disabled={embeddingLocked}
      onChange={(_event, next) => change({ embedding_model: next ?? '' })}
      renderInput={(params) => <TextField {...params} label={t('datasets.config.embedding')} />}
    />
  )

  return (
    <Grid container spacing={3} sx={{ alignItems: 'flex-start', pb: 3 }}>
      <Grid size={{ xs: 12, md: 7 }}>
        <Card sx={{ maxWidth: 768 }}>
          <CardContent component={Stack} spacing={2}>
            {error !== null ? <Alert severity="error">{error}</Alert> : null}

            <TextField
              required
              fullWidth
              label={t('datasets.config.name')}
              value={values.name}
              inputRef={nameRef}
              error={shownErrorAt('name') !== null}
              helperText={shownErrorAt('name') ?? undefined}
              slotProps={{
                inputLabel: { shrink: shownErrorAt('name') !== null ? true : undefined },
              }}
              onChange={(event) => change({ name: event.target.value })}
              onBlur={() => reveal('name')}
            />
            <TextField
              fullWidth
              multiline
              minRows={2}
              label={t('datasets.config.description')}
              value={values.description}
              inputRef={descriptionRef}
              error={shownErrorAt('description') !== null}
              helperText={shownErrorAt('description') ?? undefined}
              slotProps={{
                inputLabel: { shrink: shownErrorAt('description') !== null ? true : undefined },
              }}
              onChange={(event) => change({ description: event.target.value })}
              onBlur={() => reveal('description')}
            />
            {embeddingLocked ? (
              <Tooltip title={t('datasets.config.embeddingLocked')}>
                <span>{embeddingField}</span>
              </Tooltip>
            ) : (
              embeddingField
            )}

            <TextField
              select
              required
              fullWidth
              label={t('datasets.config.chunkMethod')}
              value={values.chunk_method}
              helperText={errorAt('chunk_method') ?? t('datasets.config.appliesToNew')}
              // MUI 9 renderuje etykietę selectu jako `div`; test kolejności s25 czyta `label`.
              slotProps={{ inputLabel: { component: 'label' } }}
              onChange={(event) => change({ chunk_method: event.target.value as ChunkMethod })}
            >
              {CHUNK_METHODS.map((method) => (
                <MenuItem key={method} value={method}>
                  {t(`datasets.method.${method}`)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              fullWidth
              data-testid="pdf-parser-select"
              label={t('datasets.config.layoutRecognize')}
              value={values.layout_recognize}
              inputRef={layoutRef}
              error={errorAt('layout_recognize') !== null}
              helperText={errorAt('layout_recognize') ?? t('datasets.config.appliesToNew')}
              onChange={(event) => change({ layout_recognize: event.target.value })}
            >
              {LAYOUT_OPTIONS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </MenuItem>
              ))}
              {visionNames.map((name) => (
                <MenuItem key={name} value={name}>
                  {name}
                </MenuItem>
              ))}
              {layoutUnknown ? (
                <MenuItem value={values.layout_recognize} disabled>
                  {t('datasets.config.layout.unknown')}
                </MenuItem>
              ) : null}
            </TextField>

            <PagesEditor
              pages={values.pages}
              error={errorAt('pages')}
              hint={t('datasets.config.appliesToNew')}
              onChange={(pages) => change({ pages })}
            />

            <ValueSlider
              field={CHUNK_TOKEN_SLIDER}
              value={values.chunk_token_num}
              onChange={(value) => change({ chunk_token_num: value })}
            />

            <TextField
              fullWidth
              label={t('datasets.config.delimiter')}
              value={values.delimiter}
              helperText={t('datasets.config.delimiterPreview', {
                value: escapedDelimiter(values.delimiter),
              })}
              onChange={(event) => change({ delimiter: event.target.value })}
            />

            {meta.isError ? (
              <Alert severity="error">{t('datasets.config.metadata.loadError')}</Alert>
            ) : meta.fields === null ? null : (
              <MetadataSection
                fields={meta.fields}
                errors={meta.issues}
                autoEnabled={values.enable_metadata}
                onAutoChange={(enabled) => change({ enable_metadata: enabled })}
                onFieldsChange={meta.edit}
                saveError={metaError}
              />
            )}

            <AdvancedFields
              values={values}
              llmOptions={modelNames(models.data ?? [], 'chat', values.llm_id)}
              onChange={change}
            />

            <SaveFooter
              onCancel={cancel}
              onSubmit={submit}
              disabled={Object.keys(patch).length === 0 || meta.hasError}
              reason={saveReason}
              loading={update.isPending || meta.savePending}
            />
          </CardContent>
        </Card>
      </Grid>

      <Grid size={{ xs: 12, md: 5 }}>
        <MethodCard chunkMethod={values.chunk_method} />
      </Grid>

      <ApplyToFilesDialog
        open={applyFlow.request !== null}
        datasetId={dataset.id}
        documents={applyFlow.request?.documents ?? []}
        chunkMethod={applyFlow.request?.chunkMethod}
        parserConfigChanges={applyFlow.request?.parserConfigChanges ?? {}}
        changedLabels={applyFlow.request?.changedLabels ?? []}
        onClose={applyFlow.close}
      />
    </Grid>
  )
}
