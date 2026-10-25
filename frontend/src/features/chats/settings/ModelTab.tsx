/**
 * Zakładka „Model” szuflady ustawień czatu (08 §8.2): model czatu i kreatywność (preset),
 * a w zwiniętym akordeonie suwaki `llm_setting` z przełącznikami `*_enabled` — odblokowane
 * dopiero przy presecie „Własne”.
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
import type { ModelOption } from '../modelsQuery'
import { applyPreset, PRESET_PARAMETERS } from './schema'
import type { ChatSettingsUpdate, ChatSettingsValues, LlmSetting, PresetParameter } from './schema'

export type ModelTabProps = {
  values: ChatSettingsValues
  /** Modele czatu do wyboru jako `{id, label}` — `id` trafia do `llm_id`, `label` jest nazwą. */
  modelOptions: ModelOption[]
  onUpdate: ChatSettingsUpdate
}

type ParamField = {
  key: 'temperature' | 'top_p' | 'presence_penalty' | 'frequency_penalty' | 'max_tokens'
  enabledKey:
    | 'temperature_enabled'
    | 'top_p_enabled'
    | 'presence_penalty_enabled'
    | 'frequency_penalty_enabled'
    | 'max_tokens_enabled'
  labelKey: string
  min: number
  max: number
  step: number
}

const PARAM_FIELDS: ParamField[] = [
  {
    key: 'temperature',
    enabledKey: 'temperature_enabled',
    labelKey: 'chat.settings.temperature',
    min: 0,
    max: 1,
    step: 0.05,
  },
  {
    key: 'top_p',
    enabledKey: 'top_p_enabled',
    labelKey: 'chat.settings.topP',
    min: 0,
    max: 1,
    step: 0.05,
  },
  {
    key: 'presence_penalty',
    enabledKey: 'presence_penalty_enabled',
    labelKey: 'chat.settings.presencePenalty',
    min: -2,
    max: 2,
    step: 0.05,
  },
  {
    key: 'frequency_penalty',
    enabledKey: 'frequency_penalty_enabled',
    labelKey: 'chat.settings.frequencyPenalty',
    min: -2,
    max: 2,
    step: 0.05,
  },
  {
    key: 'max_tokens',
    enabledKey: 'max_tokens_enabled',
    labelKey: 'chat.settings.maxTokens',
    min: 1,
    max: 8192,
    step: 1,
  },
]

export function ModelTab(props: ModelTabProps) {
  const { values, modelOptions, onUpdate } = props
  const { t } = useTranslation()
  const setting = values.llm_setting
  const isCustom = setting.parameter === 'custom'

  // Wybrany model z listy opcji; dla wartości spoza listy pokazujemy samo id (zapobiega zniknięciu).
  const selectedModel = modelOptions.find((option) => option.id === values.llm_id) ?? {
    id: values.llm_id,
    label: values.llm_id,
  }

  function patchSetting(patch: Partial<LlmSetting>): void {
    onUpdate({ llm_setting: { ...setting, ...patch } })
  }

  return (
    <Stack spacing={2}>
      <Autocomplete
        options={modelOptions}
        value={selectedModel}
        disableClearable
        getOptionLabel={(option: ModelOption) => option.label}
        onChange={(_event, next) => onUpdate({ llm_id: next.id })}
        renderInput={(params) => <TextField {...params} label={t('chat.settings.model')} />}
      />
      <Autocomplete
        options={[...PRESET_PARAMETERS]}
        value={setting.parameter}
        disableClearable
        getOptionLabel={(option: PresetParameter) => t(`chat.settings.parameter.${option}`)}
        onChange={(_event, next) => onUpdate({ llm_setting: applyPreset(next, setting) })}
        renderInput={(params) => <TextField {...params} label={t('chat.settings.parameter')} />}
      />

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>{t('chat.settings.advanced')}</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            {PARAM_FIELDS.map((field) => (
              <Stack key={field.key} spacing={0.5}>
                <FormControlLabel
                  control={
                    <Switch
                      disabled={!isCustom}
                      checked={setting[field.enabledKey]}
                      aria-label={t(field.labelKey)}
                      onChange={(event) =>
                        patchSetting({ [field.enabledKey]: event.target.checked })
                      }
                    />
                  }
                  label={t(field.labelKey)}
                />
                <Slider
                  disabled={!isCustom}
                  value={setting[field.key]}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  valueLabelDisplay="auto"
                  valueLabelFormat={sliderValueLabel}
                  aria-label={t(field.labelKey)}
                  onChange={(_event, value) => patchSetting({ [field.key]: value })}
                />
              </Stack>
            ))}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Stack>
  )
}
