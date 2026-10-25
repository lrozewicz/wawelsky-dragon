/**
 * `useKbTasks().clearFinished` (kontrakt WP E67-z1a §C3): usuwa wiersze zakończone z paska
 * i z magazynu, trwające zostają; `finished_at` ustawia się przy pierwszym stanie końcowym.
 */

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureUser } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { kbTasksStorageKey, useKbTasks } from './taskStore'
import type { StoredKbTask, WdTask } from './types'

const KEY = kbTasksStorageKey(fixtureUser.id)

function wdTask(status: WdTask['status']): WdTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    dataset_id: 'd1',
    status,
    stage: null,
    done: 1,
    total: 1,
    progress: 1,
    message: '',
    error: null,
    created_at: Date.now(),
    finished_at: null,
    result: null,
  }
}

function storedRow(taskId: string, status: WdTask['status']): StoredKbTask {
  return {
    task_id: taskId,
    kind: 'export',
    label: 'Baza',
    dataset_id: 'd1',
    added_at: Date.now(),
    last: { ...wdTask(status), task_id: taskId },
  }
}

function Probe() {
  const { tasks, clearFinished } = useKbTasks()
  return (
    <div>
      <span data-testid="rows">{tasks.map((row) => row.task_id).join(',')}</span>
      <button onClick={clearFinished}>clear</button>
    </div>
  )
}

function stored(): StoredKbTask[] {
  return JSON.parse(localStorage.getItem(KEY) ?? '[]') as StoredKbTask[]
}

beforeEach(() => {
  localStorage.clear()
  server.use(
    http.get(apiUrl('/api/wd/v1/tasks/:taskId'), () =>
      HttpResponse.json({ data: wdTask('running') }),
    ),
  )
})

afterEach(cleanup)

describe('useKbTasks — clearFinished', () => {
  it('usuwa zakończone (gotowe, błąd, anulowane) z paska i magazynu, trwające zostają', async () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([
        storedRow('t-done', 'done'),
        storedRow('t-failed', 'failed'),
        storedRow('t-cancelled', 'cancelled'),
        storedRow('t-run', 'running'),
      ]),
    )
    await renderWithProviders(<Probe />)

    fireEvent.click(screen.getByRole('button', { name: 'clear' }))

    expect(screen.getByTestId('rows').textContent).toBe('t-run')
    await waitFor(() => expect(stored().map((row) => row.task_id)).toEqual(['t-run']))
  })

  it('pierwsze odpytanie ze statusem końcowym ustawia finished_at', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow('task-1', 'running')]))
    server.use(
      http.get(apiUrl('/api/wd/v1/tasks/:taskId'), () =>
        HttpResponse.json({ data: wdTask('done') }),
      ),
    )
    const before = Date.now()
    await renderWithProviders(<Probe />)

    await waitFor(() => expect(stored()[0]?.finished_at).toBeGreaterThanOrEqual(before), {
      timeout: 4000,
    })
  })
})
