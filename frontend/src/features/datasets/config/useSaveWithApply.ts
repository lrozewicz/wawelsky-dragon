/**
 * Przepływ „zapisz i zapytaj o istniejące pliki” (kontrakt WP E5-H8c §2): po udanym PUT datasetu
 * liczy, czy zmieniono któreś z pól dotykających istniejące dokumenty (metoda chunkowania,
 * Parser PDF, zakres stron), pobiera dokumenty (`listAllDocuments`) i — gdy ich jest co najmniej
 * jeden — otwiera `ApplyToFilesDialog`. Zmiana samej nazwy/opisu dialogu nie otwiera.
 * Wydzielone z `ConfigurationTab.tsx` przez limit rozmiaru pliku (wzór: `fields.tsx`).
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { listAllDocuments } from './applyToDocuments'
import type { DocumentRow } from '../files/queries'

/** Dane dialogu „Zastosować zmiany do istniejących plików?” po udanym zapisie datasetu. */
export type ApplyRequest = {
  documents: DocumentRow[]
  /** Nowa metoda — tylko gdy zmieniona (w przeciwnym razie nie trafia do PATCH dokumentów). */
  chunkMethod?: string
  /** Zmienione klucze parser_config (`layout_recognize`, `pages`, `enable_metadata`, `metadata`). */
  parserConfigChanges: Record<string, unknown>
  /** Etykiety zmienionych pól do wiersza „Zmieniono: …” (kolejność jak w formularzu). */
  changedLabels: string[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function useSaveWithApply(datasetId: string): {
  request: ApplyRequest | null
  /**
   * Decyzja po zapisie: ewentualnie pobiera dokumenty i otwiera dialog. Nigdy nie rzuca.
   * `baselineParserConfig` to `parser_config` datasetu PRZED zapisem — łatka PUT niesie
   * parser_config SCALONY w całości (`buildConfigPatch`), więc zmienione klucze poznajemy
   * dopiero po porównaniu wartości z bazą, nie po obecności klucza w łatce.
   */
  open: (patch: Record<string, unknown>, baselineParserConfig: unknown) => Promise<void>
  close: () => void
} {
  const { t } = useTranslation()
  const [request, setRequest] = useState<ApplyRequest | null>(null)

  const open = async (
    patch: Record<string, unknown>,
    baselineParserConfig: unknown,
  ): Promise<void> => {
    const chunkMethod = typeof patch.chunk_method === 'string' ? patch.chunk_method : undefined
    const parser = isRecord(patch.parser_config) ? patch.parser_config : {}
    const base = isRecord(baselineParserConfig) ? baselineParserConfig : {}
    const parserConfigChanges: Record<string, unknown> = {}
    for (const field of ['layout_recognize', 'pages', 'enable_metadata', 'metadata'] as const) {
      if (!(field in parser)) continue
      // `metadata` to lista pól — porównanie referencyjne `!==` myliłoby świeży obiekt z formularza
      // z wartością bazową (kontrakt WP E6-1b §2), więc liczymy różnicę strukturalnie.
      const changed =
        field === 'metadata'
          ? JSON.stringify(parser[field]) !== JSON.stringify(base[field])
          : parser[field] !== base[field]
      if (changed) parserConfigChanges[field] = parser[field]
    }
    if (chunkMethod === undefined && Object.keys(parserConfigChanges).length === 0) return

    let documents: DocumentRow[]
    try {
      documents = await listAllDocuments(datasetId)
    } catch {
      // Zapis datasetu się udał (widoczne „Zapisano”); bez listy dokumentów dialog nie ma
      // o co zapytać — pomijamy go zamiast pokazywać błąd po udanym zapisie.
      return
    }
    if (documents.length === 0) return

    const changedLabels = [
      ...(chunkMethod === undefined ? [] : [t('datasets.config.chunkMethod')]),
      ...('layout_recognize' in parserConfigChanges ? [t('datasets.config.layoutRecognize')] : []),
      ...('pages' in parserConfigChanges ? [t('datasets.config.pages.title')] : []),
      ...('enable_metadata' in parserConfigChanges ? [t('datasets.config.metadata.auto')] : []),
      ...('metadata' in parserConfigChanges ? [t('datasets.config.metadata.fields')] : []),
    ]
    setRequest({ documents, chunkMethod, parserConfigChanges, changedLabels })
  }

  return { request, open, close: (): void => setRequest(null) }
}
