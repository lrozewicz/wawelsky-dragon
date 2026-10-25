/**
 * Magazyn wierszy paska zadań (kontrakt WP E7-2 §6, 08 §7.15b): `localStorage` pod kluczem
 * `wd.kbTasks.v1:<userId>`, odpytywanie `getTask` co 2 s dla zadań niekońcowych (404 → wiersz
 * znika; koniec importu unieważnia listę baz — SC-E7-2-02 krok 4) i sprzątanie wpisów
 * starszych niż 24 h. Identyfikator aktora bierzemy z kontekstu trasy (`AuthState`, wzór
 * `features/home/HomePage.tsx` — magazyn żyje w układzie zalogowanym).
 */

import { useCallback, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useRouteContext } from '@tanstack/react-router'

import { WdApiError } from '../admin/wdClient'

import { datasetKeys } from '../datasets/queries'
import { getTask } from './api'
import type { StoredKbTask, WdTask, WdTaskStatus } from './types'

/** Odstęp odpytania zadań niekońcowych (08 §7.15b: `GET /tasks/{id}` co 2 s). */
export const KB_TASK_POLL_MS = 2000

/** Wiek wiersza, po którym znika z paska (kontrakt §2: wpis usuwany po `added_at` + 24 h;
 * wiersz zakończony — po `finished_at` + 24 h). */
export const KB_TASK_TTL_MS = 24 * 60 * 60 * 1000

/** Statusy końcowe — takich zadań nie ma po co odpytywać (kontrakt §6). */
const FINAL_STATUSES: readonly WdTaskStatus[] = ['done', 'failed', 'cancelled']

export function isFinishedTask(task: WdTask | null): boolean {
  return task !== null && FINAL_STATUSES.includes(task.status)
}

/** Klucz magazynu wierszy dla aktora. */
export function kbTasksStorageKey(userId: string): string {
  return `wd.kbTasks.v1:${userId}`
}

/**
 * Postęp wiersza dla paska: klucz i18n etapu i procent. Etapy dodaje T4 jako `kbTransfer.stage.*`;
 * zadanie bez etapu (kolejka, koniec) dostaje pusty klucz — pasek pokazuje wtedy sam komunikat.
 */
export function describeTaskProgress(task: WdTask): {
  stageKey: string
  done: number
  total: number
  percent: number
} {
  return {
    stageKey: task.stage === null ? '' : `kbTransfer.stage.${task.stage}`,
    done: task.done,
    total: task.total,
    percent: Math.round(task.progress * 100),
  }
}

/**
 * Wiersz nadający się do użycia: potrzebujemy `task_id` (klucz i odpytanie), `added_at` (wiek)
 * i `last` w kształcie, na którym `isFinishedTask` nie padnie. Reszta pól trafia tylko do widoku.
 */
function isStoredKbTask(value: unknown): value is StoredKbTask {
  if (typeof value !== 'object' || value === null) return false
  const row = value as Partial<StoredKbTask>
  return (
    typeof row.task_id === 'string' &&
    typeof row.added_at === 'number' &&
    (row.last === null || typeof row.last === 'object')
  )
}

/**
 * Wczytuje wiersze aktora, pomijając wpisy starsze niż 24 h. Magazyn może pochodzić ze starszej
 * wersji aplikacji, dlatego niepoprawna zawartość jest równoważna z pustym magazynem.
 */
export function readKbTasks(storageKey: string, now: number): StoredKbTask[] {
  const raw = localStorage.getItem(storageKey)
  if (raw === null) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(isStoredKbTask)
      .filter((row) => now - (row.finished_at ?? row.added_at) < KB_TASK_TTL_MS)
  } catch {
    return []
  }
}

export function writeKbTasks(storageKey: string, tasks: readonly StoredKbTask[]): void {
  localStorage.setItem(storageKey, JSON.stringify(tasks))
}

/**
 * Odpytuje podane zadania co `KB_TASK_POLL_MS`. Zależnością efektu jest lista identyfikatorów
 * rozdzielona przecinkiem, nie tablica — inaczej przedział startowałby od nowa przy każdym
 * przerysowaniu paska i słabo obciążony host nigdy nie doczekałby odpytania.
 */
export function useTaskPolling(
  taskIds: readonly string[],
  poll: (taskId: string) => Promise<void>,
): void {
  const ids = taskIds.join(',')
  useEffect(() => {
    if (ids === '') return
    const pending = ids.split(',')
    // Jedno odpytanie na zadanie naraz: wolne `GET` nie może spiętrzać żądań ani cofać stanu
    // wiersza odpowiedzią z przedziału, którego już nie ma.
    const inFlight = new Set<string>()
    const timer = setInterval(() => {
      for (const taskId of pending) {
        if (inFlight.has(taskId)) continue
        inFlight.add(taskId)
        void poll(taskId).finally(() => inFlight.delete(taskId))
      }
    }, KB_TASK_POLL_MS)
    return () => clearInterval(timer)
  }, [ids, poll])
}

export function useKbTasks(): {
  tasks: StoredKbTask[]
  add(entry: Omit<StoredKbTask, 'added_at' | 'last'>): void
  remove(taskId: string): void
  clearFinished(): void
} {
  const userId = useRouteContext({
    strict: false,
    select: (context) => context.auth?.user?.id ?? null,
  })
  const storageKey = userId === null ? null : kbTasksStorageKey(userId)
  // Wczytanie raz, przy montowaniu: wpisy starsze niż 24 h nie wracają po F5 (kontrakt §6).
  const [tasks, setTasks] = useState<StoredKbTask[]>(() =>
    storageKey === null ? [] : readKbTasks(storageKey, Date.now()),
  )

  // Jedyny punkt zapisu — przycięta przy wczytaniu lista zastępuje zawartość magazynu.
  useEffect(() => {
    if (storageKey !== null) writeKbTasks(storageKey, tasks)
  }, [storageKey, tasks])

  const update = useCallback((change: (current: StoredKbTask[]) => StoredKbTask[]): void => {
    setTasks(change)
  }, [])

  const queryClient = useQueryClient()
  const poll = useCallback(
    async (taskId: string): Promise<void> => {
      try {
        const task = await getTask(taskId)
        update((current) =>
          current.map((row) =>
            row.task_id === taskId
              ? {
                  ...row,
                  last: task,
                  // Początek 24 h zakończonego wiersza — ustawiany raz, przy pierwszym stanie końcowym.
                  finished_at: row.finished_at ?? (isFinishedTask(task) ? Date.now() : undefined),
                }
              : row,
          ),
        )
        // Koniec importu: karta nowej bazy ma się pokazać na otwartej liście bez F5
        // (SC-E7-2-02 krok 4). `datasetKeys.all` odświeża też wybór baz w czatach i sekcję
        // Home — wzór mutacji `features/datasets/queries.ts` (wspólne odświeżanie zamierzone).
        if (task.status === 'done' && task.result !== null && 'dataset_id' in task.result) {
          void queryClient.invalidateQueries({ queryKey: datasetKeys.all })
        }
      } catch (error) {
        // Zadanie zniknęło po stronie serwera — wiersz nie ma czego pokazywać.
        if (error instanceof WdApiError && error.httpStatus === 404) {
          update((current) => current.filter((row) => row.task_id !== taskId))
        }
        // Inne błędy odpytania (sieć, 5xx) zostawiają wiersz z ostatnim znanym stanem.
      }
    },
    [update, queryClient],
  )

  const pending = tasks.filter((row) => !isFinishedTask(row.last))
  useTaskPolling(
    pending.map((row) => row.task_id),
    poll,
  )

  const add = useCallback(
    (entry: Omit<StoredKbTask, 'added_at' | 'last'>): void => {
      update((current) => [...current, { ...entry, added_at: Date.now(), last: null }])
    },
    [update],
  )

  const remove = useCallback(
    (taskId: string): void => {
      update((current) => current.filter((row) => row.task_id !== taskId))
    },
    [update],
  )

  const clearFinished = useCallback((): void => {
    update((current) => current.filter((row) => !isFinishedTask(row.last)))
  }, [update])

  return { tasks, add, remove, clearFinished }
}
