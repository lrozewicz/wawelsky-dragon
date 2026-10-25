/**
 * Pola szuflady ustawień czatu (08 §8.2): schemat zod, presety „Kreatywności” i `buildPatch`.
 *
 * Formularz trzyma PEŁNE obiekty `prompt_config` i `llm_setting` — łącznie z kluczami,
 * których nie ma w UI (np. `parameters`, `tts`, `llm_setting.thinking`), bo backend przy PATCH
 * ZASTĘPUJE cały obiekt. Schemat waliduje więc tylko znane pola, a `buildPatch` wysyła scalony
 * obiekt dopiero, gdy któreś z nich się zmieniło.
 */

import { z } from 'zod'

import { filterFromWire, filterToWire } from '../../metadata/convert'
import { NO_VALUE_OPS } from '../../metadata/types'
import type { MetaFilter } from '../../metadata/types'
import type { Chat } from '../queries'

export const PRESET_PARAMETERS = ['improvise', 'precise', 'balance', 'custom'] as const
export type PresetParameter = (typeof PRESET_PARAMETERS)[number]

/** Wartości presetów `llm_setting.parameter` (08 §8.2): temperature / top_p / presence / frequency. */
export const PRESET_VALUES: Record<
  Exclude<PresetParameter, 'custom'>,
  { temperature: number; top_p: number; presence_penalty: number; frequency_penalty: number }
> = {
  improvise: { temperature: 0.8, top_p: 0.9, presence_penalty: 0.1, frequency_penalty: 0.1 },
  precise: { temperature: 0.2, top_p: 0.75, presence_penalty: 0.5, frequency_penalty: 0.5 },
  balance: { temperature: 0.5, top_p: 0.85, presence_penalty: 0.3, frequency_penalty: 0.2 },
}

/** `max_tokens` wspólny dla wszystkich presetów (08 §8.2). */
export const PRESET_MAX_TOKENS = 4096

/** Języki wyszukiwania międzyjęzykowego (08 §8.2). */
export const CROSS_LANGUAGES = ['pl', 'en', 'de', 'fr', 'es'] as const

export type PromptConfig = {
  prologue: string
  empty_response: string
  quote: boolean
  keyword: boolean
  system: string
  cross_languages: string[]
  refine_multiturn: boolean
} & Record<string, unknown>

export type LlmSetting = {
  parameter: PresetParameter
  temperature: number
  top_p: number
  presence_penalty: number
  frequency_penalty: number
  max_tokens: number
  temperature_enabled: boolean
  top_p_enabled: boolean
  presence_penalty_enabled: boolean
  frequency_penalty_enabled: boolean
  max_tokens_enabled: boolean
} & Record<string, unknown>

/** Wspólny callback zakładek: częściowa zmiana wartości formularza (pola zagnieżdżone w całości). */
export type ChatSettingsUpdate = (patch: Partial<ChatSettingsValues>) => void

export type ChatSettingsValues = {
  name: string
  description: string
  dataset_ids: string[]
  prompt_config: PromptConfig
  similarity_threshold: number
  vector_similarity_weight: number
  top_n: number
  rerank_id: string
  llm_id: string
  llm_setting: LlmSetting
  metaDataFilter: MetaFilter
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function presetOf(value: unknown): PresetParameter {
  return PRESET_PARAMETERS.find((preset) => preset === value) ?? 'precise'
}

/** Wartości początkowe formularza z pobranego czatu; brakujące pola dostają domyślne z 08 §8.2. */
export function chatToFormValues(chat: Chat): ChatSettingsValues {
  const rawPrompt = isRecord(chat.prompt_config) ? chat.prompt_config : {}
  const rawLlm = isRecord(chat.llm_setting) ? chat.llm_setting : {}
  const parameter = presetOf(rawLlm.parameter)
  const preset = parameter === 'custom' ? PRESET_VALUES.precise : PRESET_VALUES[parameter]

  return {
    name: chat.name,
    description: chat.description,
    dataset_ids: [...chat.dataset_ids],
    prompt_config: {
      ...rawPrompt,
      prologue: text(rawPrompt.prologue),
      empty_response: text(rawPrompt.empty_response),
      quote: flag(rawPrompt.quote, true),
      keyword: flag(rawPrompt.keyword, false),
      system: text(rawPrompt.system),
      cross_languages: stringList(rawPrompt.cross_languages),
      refine_multiturn: flag(rawPrompt.refine_multiturn, false),
    },
    similarity_threshold: numberOr(chat.similarity_threshold, 0.2),
    vector_similarity_weight: numberOr(chat.vector_similarity_weight, 0.3),
    top_n: numberOr(chat.top_n, 8),
    rerank_id: chat.rerank_id,
    llm_id: chat.llm_id,
    llm_setting: {
      ...rawLlm,
      parameter,
      temperature: numberOr(rawLlm.temperature, preset.temperature),
      top_p: numberOr(rawLlm.top_p, preset.top_p),
      presence_penalty: numberOr(rawLlm.presence_penalty, preset.presence_penalty),
      frequency_penalty: numberOr(rawLlm.frequency_penalty, preset.frequency_penalty),
      max_tokens: numberOr(rawLlm.max_tokens, PRESET_MAX_TOKENS),
      temperature_enabled: flag(rawLlm.temperature_enabled, false),
      top_p_enabled: flag(rawLlm.top_p_enabled, false),
      presence_penalty_enabled: flag(rawLlm.presence_penalty_enabled, false),
      frequency_penalty_enabled: flag(rawLlm.frequency_penalty_enabled, false),
      max_tokens_enabled: flag(rawLlm.max_tokens_enabled, false),
    },
    metaDataFilter: filterFromWire(chat.meta_data_filter),
  }
}

/**
 * Wybór presetu kreatywności: ustawia wartości i próg „Własne” zachowuje wartości bieżące
 * (suwaki odblokowuje sam formularz). `max_tokens` jest stały dla presetów.
 */
export function applyPreset(parameter: PresetParameter, setting: LlmSetting): LlmSetting {
  if (parameter === 'custom') return { ...setting, parameter }
  return { ...setting, parameter, ...PRESET_VALUES[parameter], max_tokens: PRESET_MAX_TOKENS }
}

function sameStrings(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function deepEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => deepEqual(value, right[index]))
    )
  }
  if (isRecord(left) && isRecord(right)) {
    const keys = Object.keys(left)
    return (
      keys.length === Object.keys(right).length &&
      keys.every((key) => key in right && deepEqual(left[key], right[key]))
    )
  }
  return false
}

/**
 * Łatka PATCH z wyłącznie zmienionych pól (08 §8.2). `prompt_config` i `llm_setting` idą jako
 * pełne, scalone obiekty (z kluczami nieobsługiwanymi przez UI), bo backend zastępuje je w całości.
 */
export function buildPatch(
  initial: ChatSettingsValues,
  current: ChatSettingsValues,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  const name = current.name.trim()

  if (name !== initial.name.trim()) patch.name = name
  if (current.description !== initial.description) patch.description = current.description
  if (!sameStrings(current.dataset_ids, initial.dataset_ids))
    patch.dataset_ids = current.dataset_ids
  if (current.similarity_threshold !== initial.similarity_threshold) {
    patch.similarity_threshold = current.similarity_threshold
  }
  if (current.vector_similarity_weight !== initial.vector_similarity_weight) {
    patch.vector_similarity_weight = current.vector_similarity_weight
  }
  if (current.top_n !== initial.top_n) patch.top_n = current.top_n
  if (current.rerank_id !== initial.rerank_id) patch.rerank_id = current.rerank_id
  if (current.llm_id !== initial.llm_id) patch.llm_id = current.llm_id
  if (!deepEqual(initial.prompt_config, current.prompt_config)) {
    patch.prompt_config = current.prompt_config
  }
  if (!deepEqual(initial.llm_setting, current.llm_setting)) {
    patch.llm_setting = current.llm_setting
  }
  const filterChanged = !deepEqual(initial.metaDataFilter, current.metaDataFilter)
  if (filterChanged) patch.meta_data_filter = filterToWire(current.metaDataFilter)
  return patch
}

const promptConfigSchema = z.object({
  prologue: z.string(),
  empty_response: z.string(),
  quote: z.boolean(),
  keyword: z.boolean(),
  system: z.string(),
  cross_languages: z.array(z.string()),
  refine_multiturn: z.boolean(),
})

const llmSettingSchema = z.object({
  parameter: z.enum(PRESET_PARAMETERS),
  temperature: z.number(),
  top_p: z.number(),
  presence_penalty: z.number(),
  frequency_penalty: z.number(),
  max_tokens: z.number(),
  temperature_enabled: z.boolean(),
  top_p_enabled: z.boolean(),
  presence_penalty_enabled: z.boolean(),
  frequency_penalty_enabled: z.boolean(),
  max_tokens_enabled: z.boolean(),
})

/** Komunikaty walidacji to klucze i18n — tłumaczy je formularz. */
export const chatSettingsSchema = z
  .object({
    name: z.string().trim().min(1, 'chat.settings.nameRequired'),
    description: z.string(),
    dataset_ids: z.array(z.string()),
    prompt_config: promptConfigSchema,
    similarity_threshold: z.number().min(0).max(1),
    vector_similarity_weight: z.number().min(0).max(1),
    top_n: z.number().int().min(1).max(30),
    rerank_id: z.string(),
    llm_id: z.string(),
    llm_setting: llmSettingSchema,
    // Filtr buduje `MetadataConditionBuilder` — zawsze poprawny `MetaFilter` (kontrakt WP E6-1b §2).
    metaDataFilter: z.custom<MetaFilter>(),
  })
  .superRefine((value, ctx) => {
    if (value.dataset_ids.length > 0 && !value.prompt_config.system.includes('{knowledge}')) {
      ctx.addIssue({
        code: 'custom',
        message: 'chat.settings.systemKnowledge',
        path: ['prompt_config', 'system'],
      })
    }
    // Warunek ręczny bez klucza (defekt T6 c): zapis przechodził, a backend padłby dopiero
    // przy pytaniu. Klucz niepusty po trim; komunikat przy polu „Klucz” wiersza warunku
    // (AssistantTab przekazuje go kreatorowi). Tryby spoza `manual` nie wysyłają warunków.
    if (value.metaDataFilter.method === 'manual') {
      value.metaDataFilter.manual.forEach((condition, index) => {
        if (condition.key.trim() === '') {
          ctx.addIssue({
            code: 'custom',
            message: 'chat.settings.filterKeyRequired',
            path: ['metaDataFilter', 'manual', index, 'key'],
          })
        }
        // Pusta wartość (SC-E67-06 k4): `empty`/`not empty` jej nie wymagają, reszta tak.
        const missingValue = Array.isArray(condition.value)
          ? condition.value.length === 0
          : condition.value.trim() === ''
        if (missingValue && !NO_VALUE_OPS.includes(condition.op)) {
          ctx.addIssue({
            code: 'custom',
            message: 'chat.settings.filterValueRequired',
            path: ['metaDataFilter', 'manual', index, 'value'],
          })
        }
      })
    }
  })
