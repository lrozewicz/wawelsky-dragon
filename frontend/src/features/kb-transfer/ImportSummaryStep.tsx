/**
 * Krok 2 dialogu importu — podsumowanie paczki (08 §7.15(c) makieta dosłownie): linia
 * „Paczka: … · z wektorami", „utworzona … w Wawelsky Dragon …", pole Nazwa (wstępnie z paczki
 * albo `suggested_name`, ostrzeżenie o zajętej nazwie; 409 `name_conflict` → błąd pod polem
 * z `suggested_name` jako klikalny Chip), Select „Model embeddingów" z `target.models`
 * i nota zgodności: „✔ Zgodny z paczką…" albo ostrzeżenie o przeliczeniu chunków z liczbą
 * tokenów (zapis kompaktowy wg makiety — „ok. 1,9 mln").
 */

import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../i18n'
import type { ImportSummary } from './types'

import { formatGrouped } from './format'

/** Liczba tokenów zapisem kompaktowym (makieta: „ok. 1,9 mln tokenów" — nie „1 900 000"). */
function formatCompact(value: number, language: ReturnType<typeof resolveLanguage>): string {
  const locale = language === 'pl' ? 'pl-PL' : 'en-US'
  return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(
    value,
  )
}

/** Data utworzenia paczki w formacie dnia (makieta: „utworzona 12.10.2026"). */
function formatDate(iso: string, language: ReturnType<typeof resolveLanguage>): string {
  const locale = language === 'pl' ? 'pl-PL' : 'en-US'
  return new Intl.DateTimeFormat(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date(iso))
}

export type ImportSummaryStepProps = {
  summary: ImportSummary
  name: string
  onNameChange: (name: string) => void
  model: string
  onModelChange: (model: string) => void
  /** 409 `name_conflict`: `details.suggested_name` (`null` = backend nie podał propozycji). */
  conflict: string | null
}

export function ImportSummaryStep(props: ImportSummaryStepProps) {
  const { t, i18n } = useTranslation()
  const { summary } = props
  const language = resolveLanguage(i18n.language)
  // „✔ Zgodny z paczką" (brief: wybrany = paczka i `compatible`) — inaczej ostrzeżenie
  // o przeliczeniu (paczka bez wektorów albo inny/niezgodny model też wymaga przeliczenia).
  const vectorsReady =
    props.model === summary.embedding.model_name &&
    summary.embedding.included &&
    summary.target.compatible

  const files = t('kbTransfer.export.files', {
    count: summary.documents,
    n: formatGrouped(summary.documents, language),
  })
  const chunks = t('kbTransfer.export.chunks', {
    count: summary.chunks,
    n: formatGrouped(summary.chunks, language),
  })

  return (
    <Stack spacing={2} data-testid="kb-import-summary">
      <Typography data-testid="kb-import-package">
        {t('kbTransfer.import.package', {
          name: summary.name,
          files,
          chunks,
          vectors: t(
            summary.embedding.included
              ? 'kbTransfer.import.withVectors'
              : 'kbTransfer.import.withoutVectors',
          ),
        })}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {/* DEC-346: ukrywamy wyłącznie pustą i starą stałą „0.0.0”; od v1.2 backend zwraca
            realną wersję (1.2.0, K20 §3) i jest ona pokazywana. */}
        {summary.wd_version === '' || summary.wd_version === '0.0.0'
          ? t('kbTransfer.import.createdNoVersion', {
              date: formatDate(summary.created_at, language),
            })
          : t('kbTransfer.import.created', {
              date: formatDate(summary.created_at, language),
              version: summary.wd_version,
            })}
      </Typography>
      <TextField
        label={t('kbTransfer.import.nameLabel')}
        value={props.name}
        onChange={(event) => props.onNameChange(event.target.value)}
        error={props.conflict !== null}
        // 409 `name_conflict` — błąd pod polem Nazwa (e2e SC-E7-2-03 krok 2).
        helperText={props.conflict !== null ? t('kbTransfer.error.name_conflict') : undefined}
      />
      {props.conflict !== null ? (
        <Stack direction="row">
          {/* Propozycja nazwy do jednego kliknięcia (08 §7.15(c)). */}
          <Chip
            label={props.conflict}
            onClick={() => props.onNameChange(props.conflict ?? '')}
            color="primary"
            variant="outlined"
            size="small"
          />
        </Stack>
      ) : summary.name_taken && props.name.trim() === summary.name ? (
        <Alert severity="warning" data-testid="kb-import-name-taken">
          {t('kbTransfer.import.nameTaken', { name: summary.name })}
        </Alert>
      ) : null}
      <TextField
        select
        label={t('kbTransfer.import.modelLabel')}
        value={props.model}
        onChange={(event) => props.onModelChange(event.target.value)}
      >
        {summary.target.models.map((model) => (
          <MenuItem key={model.name} value={model.name}>
            {`${model.name} (${String(model.dimension)})`}
          </MenuItem>
        ))}
      </TextField>
      {vectorsReady ? (
        <Alert severity="success" data-testid="kb-import-compatible">
          {t('kbTransfer.import.compatible')}
        </Alert>
      ) : (
        <Alert severity="warning" data-testid="kb-import-reembed">
          {t('kbTransfer.import.reembed', {
            packageModel: `${summary.embedding.model_name} (${String(summary.embedding.dimension)})`,
            chunks,
            tokens: formatCompact(summary.estimated_reembed_tokens, language),
          })}
        </Alert>
      )}
    </Stack>
  )
}
