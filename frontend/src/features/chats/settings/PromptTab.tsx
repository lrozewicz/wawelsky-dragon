/**
 * Zakładka „Silnik promptu” szuflady ustawień czatu (08 §8.2): prompt systemowy (z walidacją
 * `{knowledge}`), a w zwiniętym akordeonie próg podobieństwa, waga wektorowa, Top N,
 * model rerank, języki międzyjęzykowe i optymalizacja wieloturowa.
 */

import type { Ref } from 'react'
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
import { CROSS_LANGUAGES } from './schema'
import type { ChatSettingsUpdate, ChatSettingsValues } from './schema'

export type PromptTabProps = {
  values: ChatSettingsValues
  /** Id modeli rerank do wyboru (czyszczalny). */
  rerankOptions: string[]
  /** Klucz i18n błędu promptu systemowego (albo `null`, gdy poprawny). */
  systemError: string | null
  /** Ref pola promptu systemowego — fokus przy próbie zapisu z błędem (U11). */
  systemInputRef?: Ref<HTMLInputElement>
  onUpdate: ChatSettingsUpdate
}

type SliderFieldProps = {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

function SliderField(props: SliderFieldProps) {
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2" color="text.secondary">
        {`${props.label}: ${props.value}`}
      </Typography>
      <Slider
        value={props.value}
        min={props.min}
        max={props.max}
        step={props.step}
        valueLabelDisplay="auto"
        valueLabelFormat={sliderValueLabel}
        aria-label={props.label}
        onChange={(_event, value) => props.onChange(value)}
      />
    </Stack>
  )
}

export function PromptTab(props: PromptTabProps) {
  const { values, rerankOptions, systemError, onUpdate } = props
  const { t } = useTranslation()

  return (
    <Stack spacing={2}>
      <TextField
        required
        fullWidth
        multiline
        minRows={8}
        label={t('chat.settings.system')}
        value={values.prompt_config.system}
        inputRef={props.systemInputRef}
        error={systemError !== null}
        helperText={systemError !== null ? t(systemError) : undefined}
        onChange={(event) =>
          onUpdate({ prompt_config: { ...values.prompt_config, system: event.target.value } })
        }
      />

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>{t('chat.settings.advanced')}</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <SliderField
              label={t('chat.settings.similarityThreshold')}
              value={values.similarity_threshold}
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => onUpdate({ similarity_threshold: value })}
            />
            <SliderField
              label={t('chat.settings.vectorWeight')}
              value={values.vector_similarity_weight}
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => onUpdate({ vector_similarity_weight: value })}
            />
            <SliderField
              label={t('chat.settings.topN')}
              value={values.top_n}
              min={1}
              max={30}
              step={1}
              onChange={(value) => onUpdate({ top_n: value })}
            />
            <Autocomplete
              options={rerankOptions}
              value={values.rerank_id === '' ? null : values.rerank_id}
              onChange={(_event, next) => onUpdate({ rerank_id: next ?? '' })}
              renderInput={(params) => (
                <TextField {...params} label={t('chat.settings.rerankId')} />
              )}
            />
            <Autocomplete
              multiple
              options={[...CROSS_LANGUAGES]}
              value={values.prompt_config.cross_languages}
              getOptionLabel={(option) => t(`chat.settings.language.${option}`)}
              onChange={(_event, next) =>
                onUpdate({
                  prompt_config: { ...values.prompt_config, cross_languages: next },
                })
              }
              renderInput={(params) => (
                <TextField {...params} label={t('chat.settings.crossLanguages')} />
              )}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={values.prompt_config.refine_multiturn}
                  onChange={(event) =>
                    onUpdate({
                      prompt_config: {
                        ...values.prompt_config,
                        refine_multiturn: event.target.checked,
                      },
                    })
                  }
                />
              }
              label={t('chat.settings.refineMultiturn')}
            />
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Stack>
  )
}
