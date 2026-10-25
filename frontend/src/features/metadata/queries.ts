/**
 * Warstwa danych metadanych (kontrakt WP E6-1b §2): konfiguracja pól datasetu, podsumowanie
 * wartości dokumentów i zapis `meta_fields`. Wzorzec: `features/datasets/queries.ts` — jawne
 * `queryOptions` i rozpakowanie koperty przez `apiCall`. Klucze pod prefiksem
 * `['datasets','detail',id,'metadata',…]`, więc `datasetKeys.all` unieważnia też je.
 */

import { queryOptions, useQueries } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'
import { fieldsFromWire, fieldsToWire } from './convert'
import type { MetaFieldDef } from './types'

export const metadataKeys = {
  config: (id: string) => ['datasets', 'detail', id, 'metadata', 'config'] as const,
  summary: (id: string) => ['datasets', 'detail', id, 'metadata', 'summary'] as const,
}

/** Konfiguracja pól datasetu (`GET …/metadata/config`) jako lista formularza. */
export function metadataConfigQueryOptions(datasetId: string) {
  return queryOptions({
    queryKey: metadataKeys.config(datasetId),
    queryFn: async () => {
      const data = await apiCall<components['schemas']['MetadataConfigData']>(
        api.GET('/api/v1/datasets/{dataset_id}/metadata/config', {
          params: { path: { dataset_id: datasetId } },
        }),
      )
      return fieldsFromWire(data.metadata)
    },
  })
}

/** Zapis listy pól (`PUT …/metadata/config`); `enable_metadata` idzie osobnym PUT datasetu (kontrakt §1). */
export async function saveMetadataConfig(datasetId: string, fields: MetaFieldDef[]): Promise<void> {
  await apiCall<components['schemas']['MetadataConfigData']>(
    api.PUT('/api/v1/datasets/{dataset_id}/metadata/config', {
      params: { path: { dataset_id: datasetId } },
      body: { metadata: fieldsToWire(fields) },
    }),
  )
}

/** Podsumowanie kluczy i znanych wartości: `type` + lista wartości (pary z drutu → same wartości). */
export type MetadataSummary = Record<string, { type: string; values: string[] }>

/** `GET …/metadata/summary` → mapa klucz → {typ, znane wartości} (kontrakt §1/§2). */
export function metadataSummaryQueryOptions(datasetId: string) {
  return queryOptions({
    queryKey: metadataKeys.summary(datasetId),
    queryFn: async () => {
      const data = await apiCall<components['schemas']['MetadataSummaryData']>(
        api.GET('/api/v1/datasets/{dataset_id}/metadata/summary', {
          params: { path: { dataset_id: datasetId } },
        }),
      )
      const summary: MetadataSummary = {}
      for (const [key, field] of Object.entries(data.summary)) {
        summary[key] = { type: field.type, values: field.values.map((pair) => String(pair[0])) }
      }
      return summary
    },
  })
}

/** Klucze metadanych scalone z wielu baz: klucz → unikalne wartości w kolejności pierwszego wystąpienia. */
export function useMetaKeys(datasetIds: string[]): {
  keys: Record<string, string[]>
  hasAny: boolean
  isLoading: boolean
} {
  const summaries = useQueries({ queries: datasetIds.map((id) => metadataSummaryQueryOptions(id)) })
  // Wartości enum pól z konfiguracji uzupełniają znane wartości dokumentów (SC-E6-1b-04 krok 5:
  // `ustawa` nie występuje w żadnym dokumencie, ale pole `typ` je dopuszcza — kreator ma je
  // podpowiadać), a pola konfiguracji bez wartości w dokumentach dają klucz z pustą listą.
  const configs = useQueries({ queries: datasetIds.map((id) => metadataConfigQueryOptions(id)) })
  const keys: Record<string, string[]> = {}
  for (const result of summaries) {
    if (!result.data) continue
    for (const [key, field] of Object.entries(result.data)) {
      const values = keys[key] ?? (keys[key] = [])
      for (const value of field.values) {
        if (!values.includes(value)) values.push(value)
      }
    }
  }
  for (const result of configs) {
    if (!result.data) continue
    for (const field of result.data) {
      const values = keys[field.key] ?? (keys[field.key] = [])
      for (const value of field.enum) {
        if (!values.includes(value)) values.push(value)
      }
    }
  }
  return {
    keys,
    hasAny: Object.keys(keys).length > 0,
    isLoading: summaries.some((result) => result.isLoading) || configs.some((r) => r.isLoading),
  }
}

/** Zapis metadanych dokumentu: PATCH `{meta_fields}` (cały słownik — kontrakt §1). */
export async function patchDocumentMeta(
  datasetId: string,
  documentId: string,
  metaFields: Record<string, unknown>,
): Promise<void> {
  await apiCall<components['schemas']['DocumentListed']>(
    api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}', {
      params: { path: { dataset_id: datasetId, document_id: documentId } },
      body: { meta_fields: metaFields } as components['schemas']['UpdateDocumentRequest'],
    }),
  )
}
