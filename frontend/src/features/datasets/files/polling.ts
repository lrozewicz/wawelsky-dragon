/**
 * Odświeżanie listy plików (kontrakt WP E3-3b §T1a). Funkcja czysta — decyduje, czy któryś
 * dokument jest w trakcie przetwarzania (wtedy lista odpytuje backend cyklicznie).
 */

import type { DocumentRow } from './queries'

/** Czy lista wymaga dalszego odpytywania: trwa parsowanie albo postęp jest częściowy. */
export function shouldPoll(docs: Pick<DocumentRow, 'run' | 'progress'>[]): boolean {
  return docs.some(
    (doc) =>
      doc.run === 'RUNNING' || doc.run === 'SCHEDULE' || (doc.progress > 0 && doc.progress < 1),
  )
}
