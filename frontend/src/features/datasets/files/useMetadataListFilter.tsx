/**
 * Stan i akcje filtra metadanych listy dokumentów (WP E6-1b T5b). Stan roboczy kreatora (logika
 * i warunki) żyje w hooku, więc przetrwa zamknięcie popovera; „Zastosuj” pisze go do zapytania
 * listy (`metadata_condition`) i wraca na stronę 1, a „Wyczyść”/chip × (i „Wyczyść filtr” na
 * pustym wyniku, przez `clearFilter`) usuwają filtr i czyszczą stan roboczy. Chip „Metadane:
 * n warunków” opisuje ZASTOSOWANY parametr — liczność czytana z `JSON.parse`, który nie może
 * paść, bo parametr pisze wyłącznie `conditionsToDocumentsParam` (własny kształt drutu).
 */
import { useState } from 'react'
import type { JSX } from 'react'

import { conditionsToDocumentsParam } from '../../metadata/convert'
import type { MetaCondition } from '../../metadata/types'
import { MetadataFilterBar } from './MetadataFilterBar'
import type { DocumentsQuery } from './queries'

export function useMetadataListFilter(
  datasetId: string,
  query: DocumentsQuery,
  applyQuery: (next: DocumentsQuery) => void,
): { filterBar: JSX.Element; clearFilter: () => void } {
  const [logic, setLogic] = useState<'and' | 'or'>('and')
  const [conditions, setConditions] = useState<MetaCondition[]>([])
  const activeCount =
    query.metadataCondition === ''
      ? 0
      : (JSON.parse(query.metadataCondition).conditions as unknown[]).length

  function clearFilter(): void {
    setLogic('and')
    setConditions([])
    applyQuery({ ...query, metadataCondition: '', page: 1 })
  }

  const filterBar = (
    <MetadataFilterBar
      datasetId={datasetId}
      logic={logic}
      conditions={conditions}
      activeCount={activeCount}
      onChange={(nextLogic, nextConditions) => {
        setLogic(nextLogic)
        setConditions(nextConditions)
      }}
      onApply={() =>
        applyQuery({
          ...query,
          metadataCondition: conditionsToDocumentsParam(logic, conditions) ?? '',
          page: 1,
        })
      }
      onClear={clearFilter}
    />
  )

  return { filterBar, clearFilter }
}
