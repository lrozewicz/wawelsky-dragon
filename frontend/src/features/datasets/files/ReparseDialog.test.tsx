/**
 * Testy `ReparseDialog` (kontrakt WP E3-H2a §K2): okno pokazuje wyłącznie informację, ile chunków
 * zostanie zastąpionych — opcji czyszczenia nie ma, bo backend czyści chunki sam dla dokumentów
 * DONE (DEC-139), a `documents_parse` nie przyjmuje takiego parametru. Potwierdzenie nie przekazuje
 * żadnego argumentu.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { ReparseDialog } from './ReparseDialog'

afterEach(cleanup)

describe('ReparseDialog', () => {
  it('pokazuje liczbę chunków i nie ma opcji czyszczenia', async () => {
    await renderWithProviders(
      <ReparseDialog open chunkCount={5} onConfirm={vi.fn()} onClose={vi.fn()} />,
    )

    expect(
      screen.getByText(
        'Dokument ma już 5 chunków. Ponowne parsowanie usunie istniejące chunki i utworzy je od nowa.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('reparse-clear')).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('potwierdzenie woła `onConfirm` bez argumentu', async () => {
    const onConfirm = vi.fn()
    await renderWithProviders(
      <ReparseDialog open chunkCount={5} onConfirm={onConfirm} onClose={vi.fn()} />,
    )
    const user = userEvent.setup()

    await user.click(screen.getByTestId('reparse-confirm'))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm).toHaveBeenCalledWith()
  })

  it('anulowanie woła `onClose`', async () => {
    const onClose = vi.fn()
    await renderWithProviders(
      <ReparseDialog open chunkCount={5} onConfirm={vi.fn()} onClose={onClose} />,
    )
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
