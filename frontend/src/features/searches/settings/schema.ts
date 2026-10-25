/**
 * Pola formularza ustawień wyszukiwarki (kontrakt WP E4-4b §2): wartości formularza z pobranej
 * wyszukiwarki, schemat zod i scalanie pełnego `search_config` przy zapisie.
 *
 * Backend przy `PUT /searches/{id}` ZASTĘPUJE cały `search_config`, więc `buildUpdateBody`
 * wychodzi od kluczy bieżącego obiektu i nadpisuje tylko te, które obsługuje UI — nieznane
 * klucze (`use_kg`, `top_k`, `web_search`, `llm_setting.thinking`, …) przeżywają zapis.
 */

import { z } from 'zod'

import { PRESET_VALUES } from '../../chats/settings/schema'
import { filterFromWire, filterToWire } from '../../metadata/convert'
import type { MetaFilter } from '../../metadata/types'

import type { RawSearchConfig, SearchApp } from '../queries'

export type SummaryPreset = 'precise' | 'balance' | 'improvise'

const SUMMARY_PRESETS: readonly SummaryPreset[] = ['precise', 'balance', 'improvise']

export type SearchSettingsValues = {
  name: string
  description: string
  kbIds: string[]
  similarityThreshold: number
  vectorSimilarityWeight: number
  useRerank: boolean
  rerankId: string
  summary: boolean
  llmId: string
  preset: SummaryPreset
  relatedSearch: boolean
  /** Filtr metadanych (E6-1b): stan kreatora; drut w `buildUpdateBody` przez `filterToWire`. */
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

function presetOf(value: unknown): SummaryPreset {
  return SUMMARY_PRESETS.find((preset) => preset === value) ?? 'precise'
}

/** Komunikaty walidacji to klucze i18n — tłumaczy je formularz. */
export const searchSettingsSchema = z
  .object({
    name: z.string().trim().min(1, 'searches.settings.nameRequired'),
    description: z.string(),
    kbIds: z.array(z.string()).min(1, 'searches.settings.kbIdsRequired'),
    similarityThreshold: z.number().min(0).max(1),
    vectorSimilarityWeight: z.number().min(0).max(1),
    useRerank: z.boolean(),
    rerankId: z.string(),
    summary: z.boolean(),
    llmId: z.string(),
    preset: z.enum(['precise', 'balance', 'improvise']),
    relatedSearch: z.boolean(),
    // Filtr buduje `MetadataConditionBuilder` — zawsze poprawny `MetaFilter` (kontrakt WP E6-1b §2).
    metaDataFilter: z.custom<MetaFilter>(),
  })
  .superRefine((value, ctx) => {
    if (value.summary && value.llmId === '') {
      ctx.addIssue({
        code: 'custom',
        message: 'searches.settings.llmRequired',
        path: ['llmId'],
      })
    }
  })

/** Wartości początkowe formularza z pobranej wyszukiwarki; brakujące pola dostają domyślne. */
export function toFormValues(app: SearchApp): SearchSettingsValues {
  const config = isRecord(app.search_config) ? app.search_config : {}
  const llmSetting = isRecord(config.llm_setting) ? config.llm_setting : {}
  const rerankId = text(config.rerank_id)

  return {
    name: app.name,
    description: text(app.description),
    kbIds: stringList(config.kb_ids),
    similarityThreshold: numberOr(config.similarity_threshold, 0.2),
    vectorSimilarityWeight: numberOr(config.vector_similarity_weight, 0.3),
    // Model rerank jest wybrany wtedy, gdy `rerank_id` jest niepuste.
    useRerank: rerankId !== '',
    rerankId,
    summary: flag(config.summary, false),
    llmId: text(config.chat_id),
    preset: presetOf(llmSetting.parameter),
    relatedSearch: flag(config.related_search, false),
    metaDataFilter: filterFromWire(
      isRecord(config.meta_data_filter) ? config.meta_data_filter : null,
    ),
  }
}

/** Ciało `PUT /searches/{id}`: pełne pola wyszukiwarki plus scalony `search_config`. */
export function buildUpdateBody(
  values: SearchSettingsValues,
  current: SearchApp,
): { name: string; description: string; search_config: RawSearchConfig } {
  const config = isRecord(current.search_config) ? current.search_config : {}
  const llmSetting = isRecord(config.llm_setting) ? config.llm_setting : {}

  return {
    name: values.name,
    description: values.description,
    search_config: {
      ...config,
      kb_ids: values.kbIds,
      similarity_threshold: values.similarityThreshold,
      vector_similarity_weight: values.vectorSimilarityWeight,
      rerank_id: values.useRerank ? values.rerankId : '',
      summary: values.summary,
      chat_id: values.llmId,
      llm_setting: {
        ...llmSetting,
        parameter: values.preset,
        ...PRESET_VALUES[values.preset],
      },
      related_search: values.relatedSearch,
      meta_data_filter: filterToWire(values.metaDataFilter),
    },
  }
}
