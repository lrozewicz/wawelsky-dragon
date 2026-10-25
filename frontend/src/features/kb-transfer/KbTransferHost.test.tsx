/**
 * Host paska zadań (uzupełnienie TL do T5): wiersze wracają z `localStorage` przy pierwszym
 * renderze (SC-E7-2-01 krok 8), kontekst `addTask` dodaje wiersz i podświetla go, ✕ usuwa
 * wiersz z magazynu, `highlightTask` podświetla istniejący wiersz (409 `export_in_progress`),
 * a podświetlenie wygasa po `KB_HIGHLIGHT_MS`; `openImport` włącza `importOpen` (T6).
 */

import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useQuery } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { datasetsListQueryOptions } from '../datasets/queries'
import { initI18n } from '../../i18n'
import { apiUrl, fixtureUser } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'
import { HttpResponse, http } from 'msw'

import { KbTransferHost, useKbTransfer } from './KbTransferHost'
import { kbTasksStorageKey } from './taskStore'
import type { StoredKbTask } from './types'

const KEY = kbTasksStorageKey(fixtureUser.id)
const TASKS_ROUTE = apiUrl('/api/wd/v1/tasks/:taskId')

/** Komponent-probe: odwołania do kontekstu hosta, jak użyje ich `DatasetsPage`. */
function Probe() {
  const { addTask, highlightTask, importOpen, openImport } = useKbTransfer()
  return (
    <>
      <button
        onClick={() =>
          addTask({ task_id: 'task-new', status: 'queued' }, 'export', 'Nowa baza', 'd2')
        }
      >
        add
      </button>
      <button onClick={() => highlightTask('task-1')}>highlight</button>
      <button onClick={openImport}>openImport</button>
      <span data-testid="import-open">{String(importOpen)}</span>
    </>
  )
}

function storedRow(overrides: Partial<StoredKbTask> = {}): StoredKbTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    label: 'Rocznik GUS 2024',
    dataset_id: 'd1',
    added_at: Date.now(),
    last: {
      task_id: 'task-1',
      kind: 'export',
      dataset_id: 'd1',
      status: 'done',
      stage: null,
      done: 1,
      total: 1,
      progress: 1,
      message: 'Gotowe',
      error: null,
      created_at: Date.now(),
      finished_at: Date.now(),
      result: {
        download_url: '/api/wd/v1/exports/task-1/download?sig=task-1',
        expires_at: 4_102_444_800_000,
        size_bytes: 77_594_624,
        file_name: 'rocznik-gus.wdkb.zip',
      },
    },
    ...overrides,
  }
}

function stored(): StoredKbTask[] {
  return JSON.parse(localStorage.getItem(KEY) ?? '[]') as StoredKbTask[]
}

beforeEach(() => {
  localStorage.clear()
  // jsdom nie ma `scrollIntoView` — atrapa bez efektu (przewinięcie i tak jest nieistotne w jsdom).
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    writable: true,
    value: vi.fn(),
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
})

describe('KbTransferHost', () => {
  it('wiersze wracają z localStorage przy pierwszym renderze (krok 8: F5)', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow()]))

    await renderWithProviders(
      <KbTransferHost>
        <Probe />
      </KbTransferHost>,
    )

    const row = screen.getByTestId('kb-task-row')
    expect(row).toHaveAttribute('data-task-kind', 'export')
    expect(row).toHaveAttribute('data-task-status', 'done')
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('addTask dodaje wiersz z etykietą i podświetla go, po 3 s wygasza', async () => {
    await initI18n('pl')
    vi.useFakeTimers()
    // Odpytanie świeżego wiersza po 2 s — zadanie w makiecie pozostaje w kolejce (wiersz trwa).
    server.use(
      http.get(TASKS_ROUTE, () =>
        HttpResponse.json({
          data: {
            task_id: 'task-new',
            kind: 'export',
            dataset_id: 'd2',
            status: 'queued',
            stage: null,
            done: 0,
            total: 7251,
            progress: 0,
            message: 'W kolejce',
            error: null,
            created_at: Date.now(),
            finished_at: null,
            result: null,
          },
        }),
      ),
    )
    await renderWithProviders(
      <KbTransferHost>
        <Probe />
      </KbTransferHost>,
    )
    expect(screen.queryByTestId('kb-task-bar')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'add' }))
    // Scheduler Reacta pod fałszywym zegarem — przepchnięcie zaplanowanej pracy (wzór taskStore).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    const row = screen.getByTestId('kb-task-row')
    expect(row).toHaveTextContent('Eksport „Nowa baza”')
    expect(row).toHaveAttribute('data-task-status', 'queued')
    expect(row).toHaveAttribute('data-highlighted')
    expect(stored()[0]).toMatchObject({ task_id: 'task-new', label: 'Nowa baza' })

    await act(async () => {
      vi.advanceTimersByTime(3_000)
    })
    expect(screen.getByTestId('kb-task-row')).not.toHaveAttribute('data-highlighted')
  })

  it('highlightTask podświetla istniejący wiersz (409 export_in_progress)', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow()]))
    await initI18n('pl')
    vi.useFakeTimers()
    await renderWithProviders(
      <KbTransferHost>
        <Probe />
      </KbTransferHost>,
    )
    expect(screen.getByTestId('kb-task-row')).not.toHaveAttribute('data-highlighted')

    fireEvent.click(screen.getByRole('button', { name: 'highlight' }))

    expect(screen.getByTestId('kb-task-row')).toHaveAttribute('data-highlighted')
  })

  it('openImport włącza importOpen (miejsce na dialog importu T6)', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <KbTransferHost>
        <Probe />
      </KbTransferHost>,
    )
    expect(screen.getByTestId('import-open')).toHaveTextContent('false')

    await user.click(screen.getByRole('button', { name: 'openImport' }))

    expect(screen.getByTestId('import-open')).toHaveTextContent('true')
  })

  it('✕ usuwa wiersz z paska i magazynu', async () => {
    localStorage.setItem(KEY, JSON.stringify([storedRow()]))
    const user = userEvent.setup()
    await renderWithProviders(
      <KbTransferHost>
        <Probe />
      </KbTransferHost>,
    )

    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    expect(screen.queryByTestId('kb-task-bar')).not.toBeInTheDocument()
    expect(stored()).toEqual([])
  })

  it('404 przy odpytaniu świeżego wiersza usuwa go (wzór taskStore §6)', async () => {
    await initI18n('pl')
    vi.useFakeTimers()
    localStorage.setItem(KEY, JSON.stringify([storedRow({ last: null })]))
    server.use(
      http.get(TASKS_ROUTE, () =>
        HttpResponse.json(
          { error: { code: 'not_found', message: 'Nie znaleziono zadania.' } },
          { status: 404 },
        ),
      ),
    )
    await renderWithProviders(
      <KbTransferHost>
        <Probe />
      </KbTransferHost>,
    )
    expect(screen.getByTestId('kb-task-row')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000)
    })

    expect(screen.queryByTestId('kb-task-bar')).not.toBeInTheDocument()
  })

  it('koniec importu odświeża listę baz — karta pojawia się bez F5 (SC-E7-2-02 krok 4)', async () => {
    await initI18n('pl')
    vi.useFakeTimers()
    localStorage.setItem(
      KEY,
      JSON.stringify([storedRow({ kind: 'import', label: 'Nowa baza', last: null })]),
    )
    server.use(
      http.get(TASKS_ROUTE, () =>
        HttpResponse.json({
          data: {
            task_id: 'task-1',
            kind: 'import',
            dataset_id: 'ds-new',
            status: 'done',
            stage: null,
            done: 2,
            total: 2,
            progress: 1,
            message: 'Gotowe — 2 pliki, 3 chunki',
            error: null,
            created_at: Date.now(),
            finished_at: Date.now(),
            result: {
              dataset_id: 'ds-new',
              dataset_name: 'Nowa baza',
              documents: 2,
              chunks: 3,
              reembedded: false,
            },
          },
        }),
      ),
    )
    let listCalls = 0
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () => {
        listCalls += 1
        return HttpResponse.json({ code: 0, message: 'success', data: [], total_datasets: 0 })
      }),
    )
    // Probe montuje listę baz wewnątrz hosta — jak `DatasetsPage` (pasek pod nagłówkiem listy).
    function ListProbe() {
      useQuery(datasetsListQueryOptions())
      return <span data-testid="list-probe" />
    }
    await renderWithProviders(
      <KbTransferHost>
        <ListProbe />
      </KbTransferHost>,
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(listCalls).toBe(1)

    // Odpytanie zadania po 2 s: import „done” unieważnia listę → ponowne pobranie.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(listCalls).toBe(2)
  })
})
