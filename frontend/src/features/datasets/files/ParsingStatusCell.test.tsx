/**
 * Komórka statusu parsowania (kontrakt WP E3-3b §T2): każdy stan, kliknięcia przycisków
 * i popover z początkiem, czasem trwania oraz ostatnimi liniami `progress_msg`.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fixtureDocument } from '../../../test/msw/handlers'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ParsingStatusCell } from './ParsingStatusCell'
import type { ParsingStatusDoc } from './ParsingStatusCell'

afterEach(cleanup)

async function renderCell(doc: ParsingStatusDoc) {
  const onParse = vi.fn()
  const onStop = vi.fn()
  const onOpenLog = vi.fn()
  const view = await renderWithProviders(
    <ParsingStatusCell doc={doc} onParse={onParse} onStop={onStop} onOpenLog={onOpenLog} />,
  )
  return { onParse, onStop, onOpenLog, user: userEvent.setup(), ...view }
}

const CELL = 'status-cell-doc-1'
const PARSE = 'status-parse-doc-1'
const STOP = 'status-stop-doc-1'
const LOG = 'status-log-doc-1'

describe('ParsingStatusCell — stany', () => {
  it('idle (UNSTART) pokazuje ▶, który woła onParse', async () => {
    const { onParse, onStop, user } = await renderCell(fixtureDocument({ run: 'UNSTART' }))

    const parse = screen.getByTestId(PARSE)
    expect(parse).toHaveAccessibleName('Parsuj')
    expect(screen.queryByTestId(STOP)).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()

    await user.click(parse)

    expect(onParse).toHaveBeenCalledWith(expect.objectContaining({ id: 'doc-1' }))
    expect(onStop).not.toHaveBeenCalled()
  })

  it('queued (SCHEDULE) pokazuje zegar, tekst „W kolejce” i ⊗ wołający onStop', async () => {
    const { onStop, user } = await renderCell(fixtureDocument({ run: 'SCHEDULE' }))

    expect(screen.getByTestId(LOG)).toHaveTextContent('W kolejce')
    expect(screen.queryByTestId(PARSE)).not.toBeInTheDocument()

    const stop = screen.getByTestId(STOP)
    expect(stop).toHaveAccessibleName('Zatrzymaj parsowanie')
    await user.click(stop)

    expect(onStop).toHaveBeenCalledTimes(1)
  })

  it.each([
    { progress: 0, percent: '0' },
    { progress: 0.45, percent: '45' },
    { progress: 1, percent: '100' },
  ])('running pokazuje pasek $percent% i ⊗', async ({ progress, percent }) => {
    const { onStop, user } = await renderCell(
      fixtureDocument({ run: 'RUNNING', progress, chunk_count: 3 }),
    )

    const bar = screen.getByRole('progressbar', { name: 'Postęp parsowania' })
    expect(bar).toHaveAttribute('aria-valuenow', percent)
    expect(screen.getByTestId(LOG)).toHaveTextContent(`${percent}%`)

    await user.click(screen.getByTestId(STOP))
    expect(onStop).toHaveBeenCalledTimes(1)
  })

  it('UNSTART z postępem w (0,1) liczy się już jako parsowanie', async () => {
    await renderCell(fixtureDocument({ run: 'UNSTART', progress: 0.45 }))

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45')
  })

  it.each([
    { run: 'DONE' as const, label: 'Sukces' },
    { run: 'FAIL' as const, label: 'Błąd' },
    { run: 'CANCEL' as const, label: 'Anulowano' },
  ])('$run pokazuje chip „$label” i ↻ wołający onParse', async ({ run, label }) => {
    const { onParse, user } = await renderCell(fixtureDocument({ run, chunk_count: 12 }))

    expect(screen.getByTestId(LOG)).toHaveTextContent(label)
    expect(screen.queryByTestId(STOP)).not.toBeInTheDocument()

    const reparse = screen.getByTestId(PARSE)
    expect(reparse).toHaveAccessibleName('Parsuj ponownie')
    await user.click(reparse)

    expect(onParse).toHaveBeenCalledTimes(1)
  })
})

describe('ParsingStatusCell — log i popover', () => {
  it('klik w tekst statusu woła onOpenLog, a klik w chip także', async () => {
    const queued = await renderCell(fixtureDocument({ run: 'SCHEDULE' }))
    await queued.user.click(screen.getByTestId(LOG))
    expect(queued.onOpenLog).toHaveBeenCalledTimes(1)

    cleanup()

    const done = await renderCell(fixtureDocument({ run: 'DONE' }))
    await done.user.click(screen.getByTestId(LOG))
    expect(done.onOpenLog).toHaveBeenCalledTimes(1)
  })

  it('hover pokazuje początek, czas trwania i ostatnie 5 niepustych linii logu', async () => {
    const { user } = await renderCell(
      fixtureDocument({
        run: 'RUNNING',
        progress: 0.5,
        process_begin_at: '2025-03-04T10:15:00Z',
        process_duration: 12.6,
        progress_msg: ['l1', '', 'l2', 'l3', 'l4', 'l5', 'l6', 'l7'].join('\n'),
      }),
    )

    await user.hover(screen.getByTestId(CELL))

    expect(await screen.findByText('Początek')).toBeInTheDocument()
    expect(screen.getByText(/2025/)).toBeInTheDocument()
    expect(screen.getByText('Czas trwania')).toBeInTheDocument()
    expect(screen.getByText('13 s')).toBeInTheDocument()
    expect(screen.getByText('Log postępu')).toBeInTheDocument()
    expect(screen.getByText(/l3/).textContent).toBe('l3\nl4\nl5\nl6\nl7')
    expect(screen.queryByText(/l1/)).not.toBeInTheDocument()

    await user.unhover(screen.getByTestId(CELL))
    await waitFor(() => expect(screen.queryByText('Początek')).not.toBeInTheDocument())
  })

  it('brak początku pokazuje „—”, a pusty log — komunikat o braku wpisów', async () => {
    const { user } = await renderCell(fixtureDocument({ run: 'DONE', progress_msg: '' }))

    await user.hover(screen.getByTestId(CELL))

    expect(await screen.findByText('—')).toBeInTheDocument()
    expect(screen.getByText('Brak wpisów')).toBeInTheDocument()
  })

  it('popover nie przechwytuje wskaźnika ani nie ukrywa przycisków komórki', async () => {
    const { onStop, user } = await renderCell(fixtureDocument({ run: 'RUNNING', progress: 0.5 }))

    await user.hover(screen.getByTestId(CELL))

    const popover = await screen.findByRole('tooltip')
    expect(popover).toHaveStyle({ pointerEvents: 'none' })

    const stop = screen.getByTestId(STOP)
    expect(stop.closest('[aria-hidden="true"]')).toBeNull()

    await user.click(stop)
    expect(onStop).toHaveBeenCalledTimes(1)
  })

  it('focus otwiera popover, a Escape go zamyka', async () => {
    const { user } = await renderCell(fixtureDocument({ run: 'DONE' }))

    await user.tab()
    expect(await screen.findByText('Początek')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByText('Początek')).not.toBeInTheDocument())
  })

  it('linie logu w popover przetłumaczone na PL, czas zachowany (T3b)', async () => {
    const { user } = await renderCell(
      fixtureDocument({
        run: 'FAIL',
        progress_msg: [
          '08:00:01 Task has been received.',
          '08:00:02 Auto metadata: 2 fields',
          '08:00:03 [ERROR] File is password-protected (.xlsx)',
        ].join('\n'),
      }),
    )

    await user.hover(screen.getByTestId(CELL))

    const popover = await screen.findByRole('tooltip')
    expect(popover).toHaveTextContent('08:00:01 Zadanie przyjęte.')
    expect(popover).toHaveTextContent('Metadane automatyczne: 2 pola')
    expect(popover).toHaveTextContent('08:00:03 [ERROR] Plik jest chroniony hasłem (.xlsx)')
    expect(popover).not.toHaveTextContent('Auto metadata: 2 fields')
  })
})
