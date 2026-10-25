/**
 * Stan i zapis sekcji „Metadane” zakładki „Konfiguracja” (kontrakt WP E6-1b §1/§4). Pola
 * wczytywane z `GET …/metadata/config` (T2); formularz to edycja użytkownika albo dane
 * zapytania (`edited ?? data` — bez efektu synchronizującego). Zapis idzie w kolejności
 * kontraktu: najpierw `PUT …/metadata/config`, potem PUT datasetu przekazany jako kontynuacja.
 * Wydzielone z `ConfigurationTab.tsx` przez limit rozmiaru pliku (wzór: `useSaveWithApply.ts`).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { validateFieldDefs } from '../../metadata/convert'
import type { MetaFieldDef } from '../../metadata/types'
import {
  metadataConfigQueryOptions,
  metadataKeys,
  saveMetadataConfig,
} from '../../metadata/queries'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function useMetadataConfig(datasetId: string): {
  /** Pola formularza: edycja użytkownika albo (bez zmian) dane `…/metadata/config`; `null` podczas wczytywania. */
  fields: MetaFieldDef[] | null
  /** Podmiana listy pól przez sekcję (dodanie wiersza, edycja, usunięcie). */
  edit: (fields: MetaFieldDef[]) => void
  /** Porzucenie edycji („Anuluj”) — formularz wraca do danych zapytania. */
  discardEdits: () => void
  /** Wynik `validateFieldDefs` po indeksie (pusty przed wczytaniem). */
  issues: Array<'ok' | 'required' | 'duplicate'>
  hasError: boolean
  /** Błąd wczytania konfiguracji — sekcja pokazuje komunikat zamiast edytora (U5). */
  isError: boolean
  savePending: boolean
  /**
   * Zapis wg kontraktu §1: gdy łatka niesie `metadata` (lista pól zmieniona), najpierw
   * `PUT …/metadata/config` i unieważnienie cache konfiguracji, potem PUT datasetu
   * (`saveDataset` — z `parser_config` niosącym nową listę i `enable_metadata`); błąd zapisu
   * pół raportowany przez `onMetaError` i nie uruchamia PUT datasetu.
   */
  saveOrdered: (
    patch: Record<string, unknown>,
    saveDataset: () => void,
    onMetaError: (error: unknown) => void,
  ) => void
} {
  const queryClient = useQueryClient()
  const query = useQuery(metadataConfigQueryOptions(datasetId))
  const [edited, setEdited] = useState<MetaFieldDef[] | null>(null)
  const fields = edited ?? (query.isSuccess ? query.data : null)

  const save = useMutation({
    mutationFn: (fields: MetaFieldDef[]) => saveMetadataConfig(datasetId, fields),
  })

  const saveOrdered = (
    patch: Record<string, unknown>,
    saveDataset: () => void,
    onMetaError: (error: unknown) => void,
  ): void => {
    const parser = isRecord(patch.parser_config) ? patch.parser_config : {}
    if (fields !== null && 'metadata' in parser) {
      save.mutate(fields, {
        onSuccess: () => {
          // Cache konfiguracji po zapisie; klucze metadata/* leżą też pod prefiksem
          // datasetKeys.all, który unieważnia PUT datasetu — tu skracamy odświeżenie.
          void queryClient.invalidateQueries({ queryKey: metadataKeys.config(datasetId) })
          saveDataset()
        },
        onError: onMetaError,
      })
      return
    }
    saveDataset()
  }

  const issues = fields === null ? [] : validateFieldDefs(fields)

  return {
    fields,
    edit: setEdited,
    discardEdits: (): void => setEdited(null),
    issues,
    hasError: issues.some((issue) => issue !== 'ok'),
    isError: query.isError,
    savePending: save.isPending,
    saveOrdered,
  }
}
