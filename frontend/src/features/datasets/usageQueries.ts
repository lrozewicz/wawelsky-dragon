/**
 * Powiązania bazy wiedzy (K20 §4): `GET /api/wd/v1/datasets/{id}/usage` — czaty i wyszukiwarki
 * widoczne dla aktora plus liczniki ukrytych wiązań. Dialog usuwania musi pokazać stan z chwili
 * otwarcia (nie z cache po poprzednim otwarciu), dlatego `staleTime: 0` i `gcTime: 0`.
 * Kopertę WD (`{data}` / `{error:{code,message}}`) rozpakowuje `wdCall` (wzór: `kb-transfer/api.ts`).
 */

import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { components } from '../../api/schema.gen'
import { wdCall } from '../admin/wdClient'

/** Użycie datasetu (`DatasetUsage` z openapi.json): listy, ukryte liczniki, znacznik ucięcia. */
export type DatasetUsage = components['schemas']['DatasetUsage']

/**
 * Zapytanie o powiązania jednej bazy; `null` = dialog zamknięty (nic nie pobieramy).
 * Klucz POZA drzewem `datasets` — unieważnienie `datasetKeys.all` po usunięciu bazy (mutacja
 * DELETE) nie może odświeżyć usage tej właśnie usuniętej bazy (404 i szum w konsoli przeglądarki,
 * e2e SC-V12-04); świeżość zapewniają `staleTime: 0`/`gcTime: 0` — otwarcie dialogu zawsze pobiera.
 */
export function useDatasetUsage(datasetId: string | null) {
  return useQuery({
    queryKey: ['datasetUsage', datasetId],
    queryFn: () =>
      wdCall<DatasetUsage>(
        api.GET('/api/wd/v1/datasets/{dataset_id}/usage', {
          params: { path: { dataset_id: datasetId as string } },
        }),
      ),
    enabled: datasetId !== null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
}
