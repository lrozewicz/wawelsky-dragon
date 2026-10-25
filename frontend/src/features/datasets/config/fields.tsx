/**
 * Prezentacyjne części zakładki „Konfiguracja” datasetu (08 §8.1, kontrakt WP E3-3a §T4),
 * wydzielone z `ConfigurationTab.tsx` przez limit rozmiaru pliku: suwak z etykietą wartości,
 * sekcja „Zaawansowane” w zwiniętym akordeonie i karta „O tej metodzie chunkowania”.
 *
 * Sekcja „Zaawansowane” musi znikać z DOM po zwinięciu (`unmountOnExit`), bo e2e S6-06
 * asertuje, że pola ADV są niewidoczne, dopóki akordeon nie zostanie rozwinięty.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Autocomplete from '@mui/material/Autocomplete'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import FormControl from '@mui/material/FormControl'
import FormControlLabel from '@mui/material/FormControlLabel'
import FormLabel from '@mui/material/FormLabel'
import IconButton from '@mui/material/IconButton'
import MenuItem from '@mui/material/MenuItem'
import Radio from '@mui/material/Radio'
import RadioGroup from '@mui/material/RadioGroup'
import Slider from '@mui/material/Slider'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import DeleteIcon from '@mui/icons-material/Delete'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'

import { sliderValueLabel } from '../../../lib/format'
import type { ChunkMethod } from '../queries'

import type { ConfigValues, PageRange } from './schema'

/** Języki datasetu — wartości, jakich używa backend (`English`, `Polish`), i ich etykiety. */
const LANGUAGE_OPTIONS = [
  { value: 'English', labelKey: 'datasets.config.languageOption.en' },
  { value: 'Polish', labelKey: 'datasets.config.languageOption.pl' },
] as const

/** Pola suwakowe formularza z zakresami z 08 §8.1; pierwsze stoi poza akordeonem. */
export const CHUNK_TOKEN_SLIDER = {
  name: 'chunk_token_num',
  labelKey: 'datasets.config.chunkTokenNum',
  min: 64,
  max: 2048,
} as const

/** Suwaki sekcji „Zaawansowane”. */
export const ADVANCED_SLIDERS = [
  { name: 'overlapped_percent', labelKey: 'datasets.config.overlappedPercent', min: 0, max: 30 },
  { name: 'auto_keywords', labelKey: 'datasets.config.autoKeywords', min: 0, max: 30 },
  { name: 'auto_questions', labelKey: 'datasets.config.autoQuestions', min: 0, max: 10 },
] as const

export type SliderField = {
  name: string
  labelKey: string
  min: number
  max: number
}

type ValueSliderProps = {
  field: SliderField
  value: number
  onChange: (value: number) => void
}

/** Suwak z etykietą niosącą bieżącą wartość (08 §8.1: „slider z etykietami wartości”). */
export function ValueSlider(props: ValueSliderProps): JSX.Element {
  const { t } = useTranslation()
  const label = `${t(props.field.labelKey)}: ${props.value}`

  return (
    <Stack spacing={1}>
      <Typography variant="body2">{label}</Typography>
      <Slider
        aria-label={t(props.field.labelKey)}
        min={props.field.min}
        max={props.field.max}
        value={props.value}
        valueLabelDisplay="auto"
        valueLabelFormat={sliderValueLabel}
        onChange={(_event, next) => props.onChange(next)}
      />
    </Stack>
  )
}

type AdvancedFieldsProps = {
  values: ConfigValues
  /** Modele czatu do wyboru `parser_config.llm_id` (nazwy). */
  llmOptions: string[]
  onChange: (changed: Partial<ConfigValues>) => void
}

/** Sekcja „Zaawansowane” formularza (08 §8.1, wiersze ADV). */
export function AdvancedFields(props: AdvancedFieldsProps): JSX.Element {
  const { t } = useTranslation()
  const { values, llmOptions, onChange } = props

  return (
    <Accordion disableGutters slotProps={{ transition: { unmountOnExit: true } }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography>{t('datasets.config.advanced')}</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <TextField
            select
            fullWidth
            label={t('datasets.config.language')}
            value={values.language}
            onChange={(event) => onChange({ language: event.target.value })}
          >
            {LANGUAGE_OPTIONS.map((language) => (
              <MenuItem key={language.value} value={language.value}>
                {t(language.labelKey)}
              </MenuItem>
            ))}
          </TextField>

          <FormControl>
            <FormLabel>{t('datasets.config.permission')}</FormLabel>
            <RadioGroup
              row
              value={values.permission}
              onChange={(event) =>
                onChange({ permission: event.target.value === 'team' ? 'team' : 'me' })
              }
            >
              <FormControlLabel
                value="me"
                control={<Radio />}
                label={t('datasets.config.permission.me')}
              />
              <FormControlLabel
                value="team"
                control={<Radio />}
                label={t('datasets.config.permission.team')}
              />
            </RadioGroup>
          </FormControl>

          {ADVANCED_SLIDERS.map((field) => (
            <ValueSlider
              key={field.name}
              field={field}
              value={values[field.name]}
              onChange={(value) => onChange({ [field.name]: value })}
            />
          ))}

          <FormControlLabel
            control={
              <Switch
                checked={values.html4excel}
                onChange={(event) => onChange({ html4excel: event.target.checked })}
              />
            }
            label={t('datasets.config.html4excel')}
          />

          <Autocomplete
            options={llmOptions}
            value={values.llm_id === '' ? null : values.llm_id}
            onChange={(_event, next) => onChange({ llm_id: next ?? '' })}
            // Strzałka z motywu (IconButton 36 px z ramką) wystawała poza obrys pola 40 px (T8).
            sx={{ '& .MuiAutocomplete-popupIndicator': { width: 28, height: 28, border: 0 } }}
            renderInput={(params) => <TextField {...params} label={t('datasets.config.llmId')} />}
          />
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

type PagesEditorProps = {
  /** Zakresy stron `parser_config.pages` (`[od, do]`, 1-based, włącznie); `[]` = wszystkie. */
  pages: PageRange[]
  /** Komunikat walidacji zakresów (już przetłumaczony) albo `null`. */
  error: string | null
  /** Podpowiedź pod tytułem; błąd walidacji ją zastępuje (kontrakt WP E5-H8c §2). */
  hint?: string
  onChange: (pages: PageRange[]) => void
}

/** Liczba z pola tekstowego; puste pole daje `null` (wiersz niewypełniony — SC-E5-H9-05). */
function pageNumber(raw: string): number | null {
  return raw === '' ? null : Number(raw)
}

/** Edytor zakresów stron (kontrakt E5-H3 §#9): wiersze „Od"–„Do" + „Dodaj zakres". */
export function PagesEditor(props: PagesEditorProps): JSX.Element {
  const { t } = useTranslation()
  const { pages } = props
  // Indeks nowo dodanego wiersza: `autoFocus` działa tylko przy montażu, więc wystarczy
  // ustawić go raz — fokus trafia w pole „Od” nowego wiersza (SC-E5-H9-05 krok 2).
  const [focusIndex, setFocusIndex] = useState<number | null>(null)

  function setPage(index: number, position: 0 | 1, raw: string): void {
    const next: PageRange[] = pages.map((page, current): PageRange => {
      if (current !== index) return page
      return position === 0 ? [pageNumber(raw), page[1]] : [page[0], pageNumber(raw)]
    })
    props.onChange(next)
  }

  return (
    <Stack spacing={1}>
      <Typography variant="body2">{t('datasets.config.pages.title')}</Typography>
      {/* Błąd walidacji wypiera podpowiedź (kontrakt E5-H8c §2: „błąd, nie podpowiedź”). */}
      {props.error === null && props.hint !== undefined ? (
        <Typography variant="body2" color="text.secondary">
          {props.hint}
        </Typography>
      ) : null}
      {pages.map((page, index) => (
        <Stack key={index} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <TextField
            type="number"
            size="small"
            label={t('datasets.config.pages.from')}
            value={page[0] ?? ''}
            autoFocus={index === focusIndex}
            slotProps={{
              htmlInput: {
                'data-testid': `pages-from-${index}`,
                'aria-label': t('datasets.config.pages.from'),
              },
            }}
            onChange={(event) => setPage(index, 0, event.target.value)}
          />
          <TextField
            type="number"
            size="small"
            label={t('datasets.config.pages.to')}
            value={page[1] ?? ''}
            slotProps={{
              htmlInput: {
                'data-testid': `pages-to-${index}`,
                'aria-label': t('datasets.config.pages.to'),
              },
            }}
            onChange={(event) => setPage(index, 1, event.target.value)}
          />
          <IconButton
            aria-label={t('datasets.config.pages.remove')}
            data-testid={`pages-remove-${index}`}
            onClick={() => props.onChange(pages.filter((_, current) => current !== index))}
          >
            <DeleteIcon />
          </IconButton>
        </Stack>
      ))}
      <Button
        variant="outlined"
        data-testid="pages-add"
        onClick={() => {
          // Pusty wiersz „Od”–„Do” (nie ukryte „1-1”); fokus w polu „Od” nowego wiersza.
          setFocusIndex(pages.length)
          props.onChange([...pages, [null, null]])
        }}
        sx={{ alignSelf: 'flex-start' }}
      >
        {t('datasets.config.pages.add')}
      </Button>
      {props.error === null ? null : (
        <Typography color="error" variant="body2">
          {props.error}
        </Typography>
      )}
    </Stack>
  )
}

/** Karta „O tej metodzie chunkowania” — nazwa i opis wybranej metody (bez obrazka, §T4). */
export function MethodCard(props: { chunkMethod: ChunkMethod }): JSX.Element {
  const { t } = useTranslation()

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {t('datasets.config.aboutMethod')}
        </Typography>
        <Typography variant="subtitle1">{t(`datasets.method.${props.chunkMethod}`)}</Typography>
        <Typography variant="body2" color="text.secondary">
          {t(`datasets.method.${props.chunkMethod}.desc`)}
        </Typography>
      </CardContent>
    </Card>
  )
}
