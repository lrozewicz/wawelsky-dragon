/**
 * Sekcja „Metadane” zakładki „Konfiguracja” datasetu (kontrakt WP E6-1b §4, spec 08 §7.14 a):
 * przełącznik „Auto-metadane” (nieaktywny przy pustej liście pól, podpowiedź „Dodaj co najmniej
 * jedno pole”), ⓘ z podpowiedzią o działaniu przy następnym parsowaniu oraz edytor listy pól
 * (klucz / opis / dozwolone wartości jako chipy). Prezentacyjny: stan niosą propsy, a zapis
 * koordynuje `ConfigurationTab` (kolejność PUT wg kontraktu §1); walidacja kluczy (`required`,
 * `duplicate`) przychodzi z `validateFieldDefs` przez `errors`, chipy to wspólny `ChipListInput`.
 */
import { useState } from 'react'
import type { JSX } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import FormControlLabel from '@mui/material/FormControlLabel'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'
import DeleteIcon from '@mui/icons-material/Delete'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useTranslation } from 'react-i18next'

import { ChipListInput } from '../../metadata/ChipListInput'
import type { MetaFieldDef } from '../../metadata/types'

export type MetadataFieldError = 'ok' | 'required' | 'duplicate'

export type MetadataSectionProps = {
  /** Pola formularza (kolejność istotna — numer wiersza trafia do `aria-label` grupy). */
  fields: MetaFieldDef[]
  /** Wynik `validateFieldDefs` po indeksie — komunikat przy polu „Klucz”. */
  errors: ReadonlyArray<MetadataFieldError>
  /** Stan przełącznika `parser_config.enable_metadata`. */
  autoEnabled: boolean
  onAutoChange: (enabled: boolean) => void
  /** Podmiana całej listy pól (dodanie wiersza, edycja, usunięcie). */
  onFieldsChange: (fields: MetaFieldDef[]) => void
  /**
   * Błąd zapisu pól metadanych (T4, 08 §7.14 U5) — komunikat przy polu ostatniego wiersza
   * zamiast alertu karty; wpisane wartości zostają. `null` = brak błędu.
   */
  saveError?: string | null
}

/**
 * Kolumny wiersza (i nagłówka): `minmax(0, …)` pozwala zwężać kolumny przy długich danych
 * (klucz 64 znaki, 12 chipów) zamiast wypychać kartę; < 900 px wiersz składany pod siebie.
 */
const ROW_COLUMNS = {
  display: 'grid',
  gap: 2,
  alignItems: 'start',
  gridTemplateColumns: {
    xs: '1fr',
    md: 'minmax(170px, 1.3fr) minmax(0, 1.4fr) minmax(0, 1.5fr) 40px',
  },
} as const

/** Nagłówek kolumn listy pól — wolno schować na wąskim ekranie (wiersze są wtedy w kolumnie). */
function RowHeaders(): JSX.Element {
  const { t } = useTranslation()
  return (
    <Box sx={{ ...ROW_COLUMNS, display: { xs: 'none', md: 'grid' } }}>
      <Typography variant="body2" color="text.secondary">
        {t('datasets.config.metadata.key')}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {t('datasets.config.metadata.description')}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {t('datasets.config.metadata.allowedValues')}
      </Typography>
      {/* Pusta komórka pod kosz — kolumna 40 px jak w wierszu, żeby nagłówki równały się z polami. */}
      <Box />
    </Box>
  )
}

/** Wiersz jednego pola; `autoFocus` stawia fokus w „Klucz” po dodaniu wiersza (kontrakt §4). */
function MetadataFieldRow(props: {
  field: MetaFieldDef
  index: number
  error: MetadataFieldError
  /** Błąd zapisu pól przypięty do tego wiersza (08 §7.14 U5) — pokazany przy polu „Klucz”. */
  saveError: string | null
  autoFocus: boolean
  onChange: (field: MetaFieldDef) => void
  onRemove: () => void
}): JSX.Element {
  const { field, index, error, saveError, autoFocus, onChange, onRemove } = props
  const { t } = useTranslation()
  // ≥ md nagłówek kolumn jest etykietą pól — pływająca etykieta MUI byłaby jej duplikatem i ucinała
  // się w wąskiej kolumnie (T8); < md nagłówek jest schowany, więc etykiety zostają.
  const theme = useTheme()
  const headerVisible = useMediaQuery(theme.breakpoints.up('md'))
  // „Klucz jest wymagany” dopiero po opuszczeniu pola — świeżo dodany pusty wiersz nie świeci błędem.
  const [keyTouched, setKeyTouched] = useState(false)
  const showRequired = error === 'required' && keyTouched
  return (
    <Box
      role="group"
      aria-label={t('datasets.config.metadata.field', { index: index + 1 })}
      sx={ROW_COLUMNS}
    >
      <TextField
        size="small"
        label={headerVisible ? undefined : t('datasets.config.metadata.key')}
        value={field.key}
        autoFocus={autoFocus}
        error={showRequired || error === 'duplicate' || saveError !== null}
        helperText={
          showRequired
            ? t('datasets.config.metadata.keyRequired')
            : error === 'duplicate'
              ? t('datasets.config.metadata.keyDuplicate')
              : (saveError ?? undefined)
        }
        // `title` na samym `input` (to on ma wielokropek) — pełny klucz widoczny przy hoverze.
        slotProps={{
          htmlInput: {
            'aria-label': t('datasets.config.metadata.key'),
            title: field.key,
            onBlur: () => setKeyTouched(true),
          },
        }}
        // Długi klucz (do 64 znaków) kończy się wielokropkiem, pełny tekst w `title`.
        sx={{ '& input': { textOverflow: 'ellipsis' } }}
        onChange={(event) => onChange({ ...field, key: event.target.value })}
      />
      {/* Opis dla modelu: wielowierszowy, ale ograniczony (maxRows), by nie rozpychał karty (U2). */}
      <TextField
        size="small"
        multiline
        maxRows={3}
        label={headerVisible ? undefined : t('datasets.config.metadata.description')}
        value={field.description}
        slotProps={{ htmlInput: { 'aria-label': t('datasets.config.metadata.descriptionAria') } }}
        onChange={(event) => onChange({ ...field, description: event.target.value })}
      />
      <ChipListInput
        value={field.enum}
        inputLabel={t('datasets.config.metadata.valueAria')}
        label={headerVisible ? undefined : t('datasets.config.metadata.allowedValues')}
        placeholder={headerVisible ? t('datasets.config.metadata.valuesPlaceholder') : undefined}
        removeLabel={(value) => t('datasets.config.metadata.removeValue', { value })}
        onChange={(next) => onChange({ ...field, enum: next })}
      />
      <IconButton
        size="small"
        aria-label={t('datasets.config.metadata.removeField')}
        onClick={onRemove}
      >
        <DeleteIcon fontSize="small" />
      </IconButton>
    </Box>
  )
}

export function MetadataSection(props: MetadataSectionProps): JSX.Element {
  const { fields, errors, autoEnabled, onAutoChange, onFieldsChange, saveError = null } = props
  const { t } = useTranslation()
  // Indeks wiersza, który dostać ma fokus: ustawiany przy „+ Pole”, czytany przez `autoFocus`
  // nowo montowanego wiersza (wzór: `PagesEditor` w `fields.tsx`).
  const [focusIndex, setFocusIndex] = useState<number | null>(null)

  const addField = (): void => {
    setFocusIndex(fields.length)
    onFieldsChange([...fields, { key: '', description: '', enum: [] }])
  }
  const changeField = (index: number, next: MetaFieldDef): void =>
    onFieldsChange(fields.map((field, current) => (current === index ? next : field)))
  const removeField = (index: number): void => {
    onFieldsChange(fields.filter((_, current) => current !== index))
    // Usunięcie ostatniego pola przy włączonych auto-metadanych zostawiałoby stan defektowy
    // `enable_metadata=true` z pustą listą (T4) — przełącznik wraca do wyłączenia.
    if (fields.length === 1 && autoEnabled) onAutoChange(false)
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography component="h3" variant="h6">
          {t('datasets.config.metadata.title')}
        </Typography>
        <Tooltip title={t('datasets.config.metadata.info')}>
          <IconButton size="small" aria-label={t('datasets.config.metadata.infoLabel')}>
            <InfoOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
      <div>
        <FormControlLabel
          control={
            <Switch
              checked={autoEnabled}
              disabled={fields.length === 0}
              onChange={(event) => onAutoChange(event.target.checked)}
            />
          }
          label={t('datasets.config.metadata.auto')}
        />
        {fields.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('datasets.config.metadata.emptyHint')}
          </Typography>
        ) : null}
        {/* Przy pustej liście nie ma wiersza, przy którym leżałby błąd zapisu (usunięcie wszystkich pól). */}
        {fields.length === 0 && saveError !== null ? (
          <Typography variant="body2" color="error">
            {saveError}
          </Typography>
        ) : null}
      </div>
      <Stack spacing={1}>
        <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
          <Button variant="outlined" onClick={addField}>
            {t('datasets.config.metadata.addField')}
          </Button>
        </Stack>
        {fields.length > 0 ? (
          <>
            <RowHeaders />
            {fields.map((field, index) => (
              <MetadataFieldRow
                key={index}
                field={field}
                index={index}
                error={errors[index] ?? 'ok'}
                // Błąd zapisu nie wskazuje pola — trafia do ostatniego wiersza (świeżo dodanego).
                saveError={index === fields.length - 1 ? saveError : null}
                autoFocus={index === focusIndex}
                onChange={(next) => changeField(index, next)}
                onRemove={() => removeField(index)}
              />
            ))}
          </>
        ) : null}
      </Stack>
    </Stack>
  )
}
