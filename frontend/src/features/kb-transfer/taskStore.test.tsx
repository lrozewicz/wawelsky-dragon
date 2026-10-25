/**
 * Hook magazynu wierszy paska zadań (kontrakt WP E7-2 §6): wczytanie z `localStorage` z cięciem
 * wpisów starszych niż 24 h, `add`/`remove`, odpytanie `getTask` co 2 s i 404 usuwający wiersz.
 * Czyste funkcje: `taskStore.test.ts`.
 */

import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { initI18n } from '../../i18n'
import { apiUrl, fixtureUser } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { kbTasksStorageKey, useKbTasks } from './taskStore'
import type { StoredKbTask, WdTask } from './types'

const KEY = kbTasksStorageKey(fixtureUser.id)
const TASKS_ROUTE = apiUrl('/api/wd/v1/tasks/:taskId')

function wdTask(overrides: Partial<WdTask> = {}): WdTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    dataset_id: 'd1',
    status: 'running',
    stage: 'chunks',
    done: 3000,
    total: 7251,
    progress: 0.41,
    message: 'Chunki 3000/7251',
    error: null,
    created_at: Date.now(),
    finished_at: null,
    result: null,
    ...overrides,
  }
}

function storedRow(overrides: Partial<StoredKbTask> = {}): StoredKbTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    label: 'Rocznik GUS 2024',
    dataset_id: 'd1',
    added_at: Date.now(),
    last: wdTask({ status: 'done' }),
    ...overrides,
  }
}

/** Pasek zadań w miniaturze: wiersze jako `id:status` plus przyciski `add` i `remove`. */
function TaskBarProbe(): JSX.Element {
  const { tasks, add, remove } = useKbTasks()
  return (
    <div>
      <span data-testid="rows">
        {tasks.map((row) => `${row.task_id}:${row.last?.status ?? 'none'}`).join(',')}
      </span>
      <button
        onClick={() =>
          add({ task_id: 'task-new', kind: 'import', label: 'Kopia', dataset_id: null })
        }
      >
        add
      </button>
      <button onClick={() => remove('task-new')}>remove</button>
    </div>
  )
}

function rows(): string | null {
  return screen.getByTestId('rows').textContent
}

function stored(key = KEY): StoredKbTask[] {
  return JSON.parse(localStorage.getItem(key) ?? '[]') as StoredKbTask[]
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  server.events.removeAllListeners()
})

describe('useKbTasks — magazyn', () => {
  it('wpis starszy niż 24 h ginie przy montowaniu, świeży zostaje', async () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([
        storedRow({ task_id: 'task-stale', added_at: Date.now() - 25 * 60 * 60 * 1000 }),
        storedRow({ task_id: 'task-fresh', added_at: Date.now() - 1000 }),
      ]),
    )

    await renderWithProviders(<TaskBarProbe />)

    expect(rows()).toBe('task-fresh:done')
    expect(localStorage.getItem(KEY)).not.toContain('task-stale')
  })

  it('add i remove zmieniają pasek i zapis magazynu', async () => {
    await renderWithProviders(<TaskBarProbe />)
    expect(rows()).toBe('')

    fireEvent.click(screen.getByRole('button', { name: 'add' }))

    expect(rows()).toBe('task-new:none')
    expect(stored()).toHaveLength(1)
    expect(stored()[0]).toMatchObject({ task_id: 'task-new', label: 'Kopia', last: null })
    expect(stored()[0]?.added_at).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: 'remove' }))

    expect(rows()).toBe('')
    expect(stored()).toEqual([])
  })

  it('wiersze innego aktora nie trafiają do paska', async () => {
    localStorage.setItem(
      kbTasksStorageKey('u9'),
      JSON.stringify([storedRow({ task_id: 'task-9' })]),
    )
    localStorage.setItem(KEY, JSON.stringify([storedRow({ task_id: 'task-1' })]))

    await renderWithProviders(<TaskBarProbe />, { auth: { user: { ...fixtureUser, id: 'u9' } } })

    expect(rows()).toBe('task-9:done')
  })

  it('bez zalogowanego aktora pasek działa, ale nic nie zapisuje', async () => {
    await renderWithProviders(<TaskBarProbe />, { auth: { user: null } })

    fireEvent.click(screen.getByRole('button', { name: 'add' }))

    expect(rows()).toBe('task-new:none')
    expect(localStorage.getItem(KEY)).toBeNull()
  })
})

describe('useKbTasks — odpytywanie', () => {
  it('odpytuje zadanie w toku co 2000 ms (kontrakt §6) i przestaje po done', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow({ task_id: 'task-1', last: null })]))
    let polls = 0
    server.use(
      http.get(TASKS_ROUTE, ({ params }) => {
        polls += 1
        const running = polls < 3
        return HttpResponse.json({
          data: wdTask({
            task_id: String(params.taskId),
            status: running ? 'running' : 'done',
            progress: running ? 0.5 : 1,
            finished_at: running ? null : Date.now(),
          }),
        })
      }),
    )
    // Pakiet tłumaczeń ładujemy przed fałszywym zegarem (wzór `DatasetFilesTab.polling.test.tsx`).
    await initI18n('pl')
    vi.useFakeTimers()

    await renderWithProviders(<TaskBarProbe />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(polls).toBe(0)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(polls).toBe(1)
    expect(rows()).toBe('task-1:running')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(polls).toBe(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(rows()).toBe('task-1:done')
    expect(stored()[0]?.last?.status).toBe('done')

    // Zadanie końcowe wypada z odpytywania.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(polls).toBe(3)
  })

  it('404 przy odpytaniu usuwa wiersz z paska i magazynu', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow({ task_id: 'task-gone', last: null })]))
    await initI18n('pl')
    vi.useFakeTimers()

    await renderWithProviders(<TaskBarProbe />)
    expect(rows()).toBe('task-gone:none')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(rows()).toBe('')
    expect(stored()).toEqual([])
  })

  it('błąd serwera przy odpytaniu zostawia wiersz z ostatnim znanym stanem', async () => {
    const last = wdTask({ status: 'running', progress: 0.41 })
    localStorage.setItem(KEY, JSON.stringify([storedRow({ task_id: 'task-1', last })]))
    server.use(
      http.get(TASKS_ROUTE, () =>
        HttpResponse.json({ error: { code: 'busy', message: 'Kolejka zajęta.' } }, { status: 503 }),
      ),
    )
    await initI18n('pl')
    vi.useFakeTimers()

    await renderWithProviders(<TaskBarProbe />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })

    expect(rows()).toBe('task-1:running')
    expect(stored()[0]?.last?.progress).toBe(0.41)
  })

  it('wolne odpytanie nie spiętrza żądań', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow({ task_id: 'task-1', last: null })]))
    let gets = 0
    let release: ((response: Response) => void) | null = null
    server.use(
      http.get(
        TASKS_ROUTE,
        () =>
          new Promise<Response>((resolve) => {
            gets += 1
            release = resolve
          }),
      ),
    )
    await initI18n('pl')
    vi.useFakeTimers()

    await renderWithProviders(<TaskBarProbe />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(gets).toBe(1)

    // Trzy przedziały, a pierwsze odpytanie wciąż wisi — bez spiętrzania żądań.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(gets).toBe(1)

    await act(async () => {
      release?.(HttpResponse.json({ data: wdTask({ status: 'done' }) }))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(rows()).toBe('task-1:done')
  })

  it('zadanie zakończone nie jest odpytywane', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow({ task_id: 'task-1' })]))
    let polls = 0
    server.use(
      http.get(TASKS_ROUTE, () => {
        polls += 1
        return HttpResponse.json({ data: wdTask({ status: 'done' }) })
      }),
    )
    await initI18n('pl')
    vi.useFakeTimers()

    await renderWithProviders(<TaskBarProbe />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })

    expect(polls).toBe(0)
    expect(rows()).toBe('task-1:done')
  })
})
