/**
 * Karta „Ustawienia” testu retrievalu (kontrakt WP E3-H2a §K4): suwaki progu podobieństwa, wagi
 * wektorowej i Top N, zwinięta sekcja „Zaawansowane” z modelem rerank oraz wielokrotnym wyborem
 * języków międzyjęzykowych (`cross_languages`), pole pytania i przycisk Uruchom.
 * Suwaki mają własny `step`, którego nie niesie `ValueSlider` z `../config/fields` (ta warstwa
 * jest poza zakresem T2), więc budujemy je tutaj — wzorem `features/chats/settings/PromptTab.tsx`.
 */

import type { JSX, KeyboardEvent } from 'react'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Autocomplete from '@mui/material/Autocomplete'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Slider from '@mui/material/Slider'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'

import { sliderValueLabel } from '../../../lib/format'
import { MetadataConditionBuilder } from '../../metadata/MetadataConditionBuilder'

import { RETRIEVAL_LANGUAGES } from './schema'
import type { RetrievalSettings } from './schema'

export type SettingsCardProps = {
  settings: RetrievalSettings
  question: string
  running: boolean
  rerankOptions: string[]
  /** Dataset testu — kreator czyta z niego klucze metadanych (`useMetaKeys`). */
  datasetId: string
  onSettingsChange: (next: RetrievalSettings) => void
  onQuestionChange: (q: string) => void
  onRun: () => void
}

type SettingsSliderProps = {
  testId: string
  labelKey: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

/** Liczba miejsc po przecinku kroku: `0.01` → 2, `1` → 0. */
function stepDecimals(step: number): number {
  return Number.isInteger(step) ? 0 : (String(step).split('.')[1] ?? '').length
}

/** Suwak z etykietą niosącą bieżącą wartość; kontener niesie `data-testid`, wejście `aria-label`. */
function SettingsSlider(props: SettingsSliderProps): JSX.Element {
  const { t } = useTranslation()

  return (
    <Stack spacing={1}>
      <Typography variant="body2">{`${t(props.labelKey)}: ${props.value}`}</Typography>
      <Slider
        data-testid={props.testId}
        aria-label={t(props.labelKey)}
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        valueLabelDisplay="auto"
        valueLabelFormat={sliderValueLabel}
        // MUI zaokrągla do kroku tylko przy przeciąganiu; strzałki dodają `step` wprost
        // (0.2 + 0.01 → 0.21000000000000002), więc wyrównujemy wartość także tutaj.
        onChange={(_event, next) => props.onChange(Number(next.toFixed(stepDecimals(props.step))))}
      />
    </Stack>
  )
}

export function SettingsCard(props: SettingsCardProps): JSX.Element {
  const {
    settings,
    question,
    running,
    rerankOptions,
    datasetId,
    onSettingsChange,
    onQuestionChange,
    onRun,
  } = props
  const { t } = useTranslation()

  const canRun = !running && question.trim() !== ''

  /** Ctrl/Cmd+Enter w polu pytania uruchamia test — jak przycisk Uruchom. */
  const handleQuestionKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey) || !canRun) return
    event.preventDefault()
    onRun()
  }

  return (
    <Card data-testid="retrieval-settings-card">
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {t('retrieval.settings.title')}
        </Typography>
        <Stack spacing={2}>
          <SettingsSlider
            testId="retrieval-threshold"
            labelKey="retrieval.settings.threshold"
            value={settings.similarityThreshold}
            min={0}
            max={1}
            step={0.01}
            onChange={(value) => onSettingsChange({ ...settings, similarityThreshold: value })}
          />
          <SettingsSlider
            testId="retrieval-vector-weight"
            labelKey="retrieval.settings.vectorWeight"
            value={settings.vectorWeight}
            min={0}
            max={1}
            step={0.01}
            onChange={(value) => onSettingsChange({ ...settings, vectorWeight: value })}
          />
          <SettingsSlider
            testId="retrieval-top-n"
            labelKey="retrieval.settings.topN"
            value={settings.topN}
            min={1}
            max={100}
            step={1}
            onChange={(value) => onSettingsChange({ ...settings, topN: value })}
          />

          <Accordion disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>{t('retrieval.settings.advanced')}</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2}>
                <Autocomplete
                  options={rerankOptions}
                  // Motyw daje przyciskowi strzałki ramkę i 40 px — wystawał poza pole (36 px): zmniejszony.
                  slotProps={{ popupIndicator: { size: 'small', sx: { width: 28, height: 28 } } }}
                  value={settings.rerankId === '' ? null : settings.rerankId}
                  onChange={(_event, next) =>
                    onSettingsChange({ ...settings, rerankId: next ?? '' })
                  }
                  renderInput={(params) => (
                    <TextField {...params} size="small" label={t('retrieval.settings.rerank')} />
                  )}
                />
                <Autocomplete
                  multiple
                  options={[...RETRIEVAL_LANGUAGES]}
                  // Motyw daje przyciskowi strzałki ramkę i 40 px — wystawał poza pole (36 px): zmniejszony.
                  slotProps={{ popupIndicator: { size: 'small', sx: { width: 28, height: 28 } } }}
                  value={settings.crossLanguages}
                  getOptionLabel={(option) => t(`retrieval.settings.language.${option}`)}
                  onChange={(_event, next) =>
                    onSettingsChange({ ...settings, crossLanguages: next })
                  }
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      size="small"
                      label={t('retrieval.settings.crossLanguage')}
                    />
                  )}
                />
                {/* Filtr metadanych (SC-E6-1b-06): test obsługuje tylko Wyłączony/Ręczny —
                    tryby automatyczne widoczne, ale nieaktywne; warunek idzie w body /retrieval. */}
                {/* disableGutters: marginesy rozwiniętego zagnieżdżonego akordeonu były ucinane
                    przez kontener rodzica (brak dolnej ramki panelu „Zaawansowane”). */}
                <Accordion disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography>{t('metadata.filter.title')}</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <MetadataConditionBuilder
                      value={settings.metaDataFilter}
                      onChange={(metaDataFilter) =>
                        onSettingsChange({ ...settings, metaDataFilter })
                      }
                      datasetIds={[datasetId]}
                      modes={['off', 'manual']}
                      disabledModeHint={t('retrieval.settings.modeChatOnly')}
                    />
                  </AccordionDetails>
                </Accordion>
              </Stack>
            </AccordionDetails>
          </Accordion>

          <TextField
            fullWidth
            multiline
            minRows={3}
            label={t('retrieval.question.label')}
            placeholder={t('retrieval.question.placeholder')}
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            onKeyDown={handleQuestionKeyDown}
            slotProps={{
              // Etykieta zawsze zwinięta — inaczej MUI trzyma ją w polu i zasłania placeholder
              // (D1 QA E3-7). Ten sam wzorzec co `ApiKeysDialog`.
              inputLabel: { shrink: true },
              htmlInput: {
                'data-testid': 'retrieval-question',
                'aria-label': t('retrieval.question.label'),
              },
            }}
          />

          <Button
            variant="contained"
            data-testid="retrieval-run"
            disabled={!canRun}
            onClick={onRun}
          >
            {running ? t('retrieval.running') : t('retrieval.run')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
