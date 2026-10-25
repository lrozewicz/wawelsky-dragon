/**
 * Pasek zadań (CONTRACT WP E7-2 §7): pusty pasek nie renderuje nic (U5), wiersze mapowane
 * z magazynu z atrybutami rodzaju i stanu, ✕ usuwa właściwy wiersz, podświetlenie przewija
 * pasek do wiersza (`scrollIntoView`).
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { TaskBar } from './TaskBar'
import type { StoredKbTask, WdTask } from './types'

const onRemove = vi.fn()
const onClear = vi.fn()

function doneRow(taskId: string, kind: 'export' | 'import'): StoredKbTask {
  const result: WdTask['result'] =
    kind === 'export'
      ? {
          download_url: `/api/wd/v1/exports/${taskId}/download?sig=${taskId}`,
          expires_at: 4_102_444_800_000,
          size_bytes: 77_594_624,
          file_name: `${taskId}.wdkb.zip`,
        }
      : {
          dataset_id: 'ds-9',
          dataset_name: 'Rocznik GUS 2024',
          documents: 2,
          chunks: 7251,
          reembedded: false,
        }
  return {
    task_id: taskId,
    kind,
    label: 'Rocznik GUS 2024',
    dataset_id: 'd1',
    added_at: Date.now(),
    last: {
      task_id: taskId,
      kind,
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
      result,
    },
  }
}

function queuedRow(taskId: string): StoredKbTask {
  return {
    task_id: taskId,
    kind: 'import',
    label: 'Kopia',
    dataset_id: null,
    added_at: Date.now(),
    last: null,
  }
}

afterEach(() => {
  cleanup()
  onRemove.mockClear()
  onClear.mockClear()
  vi.restoreAllMocks()
  Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
})

/** jsdom nie ma `scrollIntoView` — wstawiamy atrapę, by sprawdzić przewinięcie do wiersza. */
function stubScrollIntoView(): ReturnType<typeof vi.fn> {
  const stub = vi.fn()
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    writable: true,
    value: stub,
  })
  return stub
}

describe('TaskBar', () => {
  it('pusty pasek nie renderuje nic (U5: niewidoczny)', async () => {
    await renderWithProviders(
      <TaskBar tasks={[]} highlightedId={null} onRemove={onRemove} onClearFinished={onClear} />,
    )

    expect(screen.queryByTestId('kb-task-bar')).not.toBeInTheDocument()
  })

  it('renderuje wiersze z atrybutami rodzaju i stanu (CONTRACT §7)', async () => {
    await renderWithProviders(
      <TaskBar
        tasks={[doneRow('task-1', 'export'), queuedRow('task-2')]}
        highlightedId={null}
        onRemove={onRemove}
        onClearFinished={onClear}
      />,
    )

    const rows = screen.getAllByTestId('kb-task-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveAttribute('data-task-kind', 'export')
    expect(rows[0]).toHaveAttribute('data-task-status', 'done')
    expect(rows[1]).toHaveAttribute('data-task-kind', 'import')
    expect(rows[1]).toHaveAttribute('data-task-status', 'queued')
  })

  it('✕ w wierszu usuwa właściwy wiersz (tylko stany końcowe)', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <TaskBar
        tasks={[doneRow('task-1', 'export'), queuedRow('task-2')]}
        highlightedId={null}
        onRemove={onRemove}
        onClearFinished={onClear}
      />,
    )

    // queued nie ma ✕; jedyny przycisk należy do gotowego eksportu.
    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    expect(onRemove).toHaveBeenCalledTimes(1)
    expect(onRemove).toHaveBeenCalledWith('task-1')
  })

  it('„Wyczyść zakończone” widoczne tylko przy zakończonym wierszu i woła onClearFinished', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <TaskBar
        tasks={[queuedRow('task-2')]}
        highlightedId={null}
        onRemove={onRemove}
        onClearFinished={onClear}
      />,
    )
    expect(screen.queryByTestId('kb-clear-finished')).not.toBeInTheDocument()
    cleanup()

    await renderWithProviders(
      <TaskBar
        tasks={[doneRow('task-1', 'export'), queuedRow('task-2')]}
        highlightedId={null}
        onRemove={onRemove}
        onClearFinished={onClear}
      />,
    )
    await user.click(screen.getByTestId('kb-clear-finished'))

    expect(screen.getByTestId('kb-clear-finished')).toHaveTextContent('Wyczyść zakończone')
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('podświetlenie przewija pasek do wiersza o tym identyfikatorze', async () => {
    const scrollIntoView = stubScrollIntoView()
    await renderWithProviders(
      <TaskBar
        tasks={[doneRow('task-1', 'export'), doneRow('task-2', 'import')]}
        highlightedId="task-2"
        onRemove={onRemove}
        onClearFinished={onClear}
      />,
    )

    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    expect(scrollIntoView.mock.contexts[0]).toHaveAttribute('data-task-id', 'task-2')
    expect(screen.getAllByTestId('kb-task-row')[1]).toHaveAttribute('data-highlighted')
  })
})
