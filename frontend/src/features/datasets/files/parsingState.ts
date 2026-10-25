/**
 * Stan parsowania dokumentu (kontrakt WP E3-3b §T1a). Mapowanie kodu `run` na etykietę UI oraz
 * pochodne: procent postępu, blokada usuwania, obecność chunków. Funkcje czyste.
 */

import type { DocumentRow } from './queries'

export type ParsingState = 'idle' | 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

/**
 * `UNSTART` jest domyślnym stanem spoczynku, ale dokument z postępem w (0,1) już się parsuje
 * (backend przy starcie zostawia `run='UNSTART'`, zanim ustawi `RUNNING`) — stąd wyjątek niżej.
 */
export function parsingState(
  doc: Pick<DocumentRow, 'run' | 'progress' | 'chunk_count'>,
): ParsingState {
  switch (doc.run) {
    case 'SCHEDULE':
      return 'queued'
    case 'RUNNING':
      return 'running'
    case 'DONE':
      return 'done'
    case 'FAIL':
      return 'failed'
    case 'CANCEL':
      return 'cancelled'
    default:
      return doc.progress > 0 && doc.progress < 1 ? 'running' : 'idle'
  }
}

/** Postęp dokumentu w procentach: `progress` (0..1) obcięty do zakresu i zaokrąglony. */
export function progressPercent(progress: number): number {
  return Math.round(Math.min(1, Math.max(0, progress)) * 100)
}

/** Usuwanie w trakcie parsowania jest zablokowane (przyciski „Usuń” w wierszu i zbiorczo). */
export function canDelete(doc: Pick<DocumentRow, 'run' | 'progress' | 'chunk_count'>): boolean {
  const state = parsingState(doc)
  return state !== 'running' && state !== 'queued'
}

/** Czy dokument ma już chunki — decyduje o dialogu „Parsuj ponownie” zamiast bezpośredniego parsowania. */
export function hasChunks(doc: Pick<DocumentRow, 'chunk_count'>): boolean {
  return doc.chunk_count > 0
}
