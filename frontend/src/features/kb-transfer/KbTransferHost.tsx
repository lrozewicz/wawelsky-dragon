/**
 * Host paska zadań transferu (uzupełnienie TL do T5): trzyma `useKbTasks()`, renderuje pasek
 * nad zawartością strony i udostępnia kontekst `useKbTransfer()` — dodanie wiersza po starcie
 * z dialogu, podświetlenie wiersza (409 `export_in_progress`) i otwarcie dialogu importu
 * (T6: przycisk „Importuj" w nagłówku strony woła `openImport()`, a host montuje
 * `<ImportDialog/>` na stanie `importOpen`, z `onStarted → addTask`).
 *
 * Dzieci mogą być funkcją `(taskBar) => ReactNode` — strona umieszcza wtedy pasek samodzielnie
 * (DatasetsPage przenosi nagłówek do wnętrza hosta, żeby przycisk „Importuj" widział kontekst),
 * a pozycja paska pod nagłówkiem listy zostaje bez zmian. Zwykłe dzieci — pasek renderuje host.
 */

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { ImportDialog } from './ImportDialog'
import { TaskBar, KB_HIGHLIGHT_MS } from './TaskBar'
import { useKbTasks } from './taskStore'
import type { TaskRef } from './types'

/** Wartość kontekstu hosta paska zadań. */
export interface KbTransferContextValue {
  /** Nowy wiersz po starcie zadania (`TaskRef` z trasy 2/9 K19). */
  addTask(ref: TaskRef, kind: 'export' | 'import', label: string, datasetId: string | null): void
  /** 409 `export_in_progress`: przewinięcie do wiersza i podświetlenie go. */
  highlightTask(taskId: string): void
  /** Czy dialog importu ma być zamontowany (przycisk „Importuj" na liście baz). */
  importOpen: boolean
  /** Otwarcie dialogu importu (przycisk „Importuj" na liście baz). */
  openImport(): void
  /** Zamknięcie dialogu importu (✕/„Anuluj" — host porzuca sesję importu w `ImportDialog`). */
  closeImport(): void
}

const KbTransferContext = createContext<KbTransferContextValue | null>(null)

/** Dostęp do hosta paska zadań — tylko wewnątrz `<KbTransferHost>`. */
export function useKbTransfer(): KbTransferContextValue {
  const value = useContext(KbTransferContext)
  if (value === null) {
    throw new Error('useKbTransfer może być wywołane tylko wewnątrz <KbTransferHost>')
  }
  return value
}

export type KbTransferHostProps = {
  children?: ReactNode | ((taskBar: ReactNode) => ReactNode)
}

export function KbTransferHost(props: KbTransferHostProps) {
  const { tasks, add, remove, clearFinished } = useKbTasks()
  const [highlightedId, setHighlightedId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const highlightTimer = useRef<number | undefined>(undefined)

  const highlightTask = useCallback((taskId: string): void => {
    setHighlightedId(taskId)
    window.clearTimeout(highlightTimer.current)
    highlightTimer.current = window.setTimeout(() => setHighlightedId(null), KB_HIGHLIGHT_MS)
  }, [])

  const addTask = useCallback<KbTransferContextValue['addTask']>(
    (ref, kind, label, datasetId) => {
      add({ task_id: ref.task_id, kind, label, dataset_id: datasetId })
      // Świeży wiersz też podświetlamy: dialog się zamknął, a pasek leży pod nagłówkiem strony.
      highlightTask(ref.task_id)
    },
    [add, highlightTask],
  )

  const openImport = useCallback(() => setImportOpen(true), [])
  const closeImport = useCallback(() => setImportOpen(false), [])

  const value = useMemo<KbTransferContextValue>(
    () => ({ addTask, highlightTask, importOpen, openImport, closeImport }),
    [addTask, highlightTask, importOpen, openImport, closeImport],
  )

  const taskBar = (
    <TaskBar
      tasks={tasks}
      highlightedId={highlightedId}
      onRemove={remove}
      onClearFinished={clearFinished}
    />
  )
  const body =
    typeof props.children === 'function' ? (
      props.children(taskBar)
    ) : (
      <>
        {taskBar}
        {props.children}
      </>
    )

  return (
    <KbTransferContext.Provider value={value}>
      {body}
      {importOpen ? (
        <ImportDialog
          onClose={closeImport}
          onStarted={(ref, label) => addTask(ref, 'import', label, null)}
        />
      ) : null}
    </KbTransferContext.Provider>
  )
}
