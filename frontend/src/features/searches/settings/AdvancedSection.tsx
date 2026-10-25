/**
 * Sekcja „Zaawansowane” szuflady ustawień wyszukiwarki (08 §8.3): próg podobieństwa, waga
 * podobieństwa wektorowego, rerank (przełącznik + model z rejestru) i preset kreatywności.
 * Preset jest aktywny tylko przy włączonym podsumowaniu AI — bez niego nie ma czego ustawiać.
 */

import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Autocomplete from '@mui/material/Autocomplete'
import FormControlLabel from '@mui/material/FormControlLabel'
import Slider from '@mui/material/Slider'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'

import { sliderValueLabel } from '../../../lib/format'
import { MetadataConditionBuilder } from '../../metadata/MetadataConditionBuilder'
import type { SearchSettingsValues, SummaryPreset } from './schema'

export type AdvancedSectionProps = {
  values: SearchSettingsValues
  /** Nazwy modeli rerank z rejestru; bieżąca wartość spoza listy też się pokaże. */
  rerankOptions: string[]
  onUpdate: (patch: Partial<SearchSettingsValues>) => void
}

const PRESETS: readonly SummaryPreset[] = ['precise', 'balance', 'improvise']

export function AdvancedSection(props: AdvancedSectionProps) {
  const { values, rerankOptions, onUpdate } = props
  const { t } = useTranslation()
  const rerankChoices = [...new Set([values.rerankId, ...rerankOptions])].filter((id) => id !== '')

  return (
    <Accordion>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography>{t('searches.settings.advanced')}</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <Stack spacing={0.5}>
            <Typography variant="body2">{t('searches.settings.similarity')}</Typography>
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={values.similarityThreshold}
              valueLabelDisplay="auto"
              valueLabelFormat={sliderValueLabel}
              aria-label={t('searches.settings.similarity')}
              onChange={(_event, value) => onUpdate({ similarityThreshold: value })}
            />
          </Stack>
          <Stack spacing={0.5}>
            <Typography variant="body2">{t('searches.settings.vectorWeight')}</Typography>
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={values.vectorSimilarityWeight}
              valueLabelDisplay="auto"
              valueLabelFormat={sliderValueLabel}
              aria-label={t('searches.settings.vectorWeight')}
              onChange={(_event, value) => onUpdate({ vectorSimilarityWeight: value })}
            />
          </Stack>
          <FormControlLabel
            control={
              <Switch
                checked={values.useRerank}
                onChange={(event) => onUpdate({ useRerank: event.target.checked })}
              />
            }
            label={t('searches.settings.useRerank')}
          />
          <Autocomplete
            disabled={!values.useRerank}
            options={rerankChoices}
            value={values.rerankId === '' ? null : values.rerankId}
            onChange={(_event, next) => onUpdate({ rerankId: next ?? '' })}
            renderInput={(params) => (
              <TextField {...params} label={t('searches.settings.rerankModel')} />
            )}
          />
          {values.summary ? (
            <Autocomplete
              options={[...PRESETS]}
              value={values.preset}
              disableClearable
              getOptionLabel={(option) => t(`searches.settings.preset.${option}`)}
              onChange={(_event, next) => onUpdate({ preset: next })}
              renderInput={(params) => (
                <TextField {...params} label={t('searches.settings.preset')} />
              )}
            />
          ) : null}
          {/* Filtr metadanych (E6-1b): zapis idzie z resztą search_config; klucze z wybranych
              baz wyszukiwarki, link do konfiguracji pierwszej z nich (SC-E6-1b-07). */}
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>{t('metadata.filter.title')}</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <MetadataConditionBuilder
                value={values.metaDataFilter}
                onChange={(metaDataFilter) => onUpdate({ metaDataFilter })}
                datasetIds={values.kbIds}
                modes={['off', 'manual', 'auto', 'semi_auto']}
                datasetConfigLinkId={values.kbIds[0]}
              />
            </AccordionDetails>
          </Accordion>
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
