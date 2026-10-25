/**
 * Dialog pełnego logu parsowania (kontrakt WP E3-3b §T2): tytuł z nazwą dokumentu, cały
 * `progress_msg` w bloku `pre-wrap`, przycisk „Zamknij”, pusty środek przy `doc === null`.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fixtureDocument } from '../../../test/msw/handlers'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ProcessLogDialog } from './ProcessLogDialog'

afterEach(cleanup)

const DOC = fixtureDocument({
  name: 'umowa.pdf',
  progress_msg: 'start\nstrona 3',
  process_duration: 4,
})

describe('ProcessLogDialog', () => {
  it('pokazuje tytuł z nazwą dokumentu i cały log', async () => {
    await renderWithProviders(<ProcessLogDialog open doc={DOC} onClose={() => {}} />)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Log parsowania')
    expect(dialog).toHaveTextContent('umowa.pdf')

    const log = screen.getByText(/start/)
    expect(log.tagName).toBe('PRE')
    expect(log.textContent).toBe('start\nstrona 3')
  })

  it('Zamknij woła onClose', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<ProcessLogDialog open doc={DOC} onClose={onClose} />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Zamknij' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('bez dokumentu renderuje sam dialog bez zawartości', async () => {
    await renderWithProviders(<ProcessLogDialog open doc={null} onClose={() => {}} />)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Log parsowania')
    expect(dialog.querySelector('pre')).toBeNull()
  })

  it('pusty log (np. plik zaimportowany) pokazuje „Brak logu” zamiast pustego okna', async () => {
    await renderWithProviders(
      <ProcessLogDialog open doc={{ ...DOC, progress_msg: '' }} onClose={() => {}} />,
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Brak logu')
    expect(dialog.querySelector('pre')).toBeNull()
  })

  it('zamknięty nie renderuje niczego', async () => {
    await renderWithProviders(<ProcessLogDialog open={false} doc={DOC} onClose={() => {}} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('wpisy workera tłumaczone na PL z zachowaniem czasu i prefiksu [ERROR] (T3b)', async () => {
    await renderWithProviders(
      <ProcessLogDialog
        open
        doc={{
          ...DOC,
          progress_msg: [
            '08:00:01 Task has been received.',
            '08:00:02 Auto metadata: 0 fields',
            '08:00:03 Auto metadata: 2 fields',
            '08:00:04 [ERROR] File is corrupted or unreadable (.xlsx): broken zip',
            'całkiem nieznany wpis',
          ].join('\n'),
        }}
        onClose={() => {}}
      />,
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('08:00:01 Zadanie przyjęte.')
    expect(dialog).toHaveTextContent('Metadane automatyczne: nie znaleziono wartości')
    expect(dialog).toHaveTextContent('Metadane automatyczne: 2 pola')
    expect(dialog).toHaveTextContent(
      '08:00:04 [ERROR] Plik jest uszkodzony lub nieczytelny (.xlsx): broken zip',
    )
    // Nieznana linia — dosłownie; surowe wpisy znikają.
    expect(dialog).toHaveTextContent('całkiem nieznany wpis')
    expect(dialog).not.toHaveTextContent('Auto metadata: 2 fields')
    expect(dialog).not.toHaveTextContent('Task has been received.')
  })
})
