/**
 * Testy `RenameDocumentDialog` (kontrakt WP E3-3b §T6): pole startuje z bieżącą nazwą (i wraca do
 * niej przy każdym otwarciu), pusta nazwa po `trim` pokazuje `rename.required` i nie zapisuje,
 * Enter zatwierdza formularz, a zapis dostaje nazwę przyciętą.
 */

import { useState } from 'react'
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { RenameDocumentDialog } from './RenameDocumentDialog'

afterEach(cleanup)

/** Okno da się zamykać i otwierać — potrzebne do sprawdzenia resetu pola. */
function Harness({
  onSave,
  name = 'stary.pdf',
}: {
  onSave: (name: string) => void
  name?: string
}) {
  const [open, setOpen] = useState(true)
  return (
    <>
      {/* MUI oznacza treść poza oknem jako `aria-hidden`, więc przełącznik znajdujemy po testid. */}
      <button type="button" data-testid="toggle" onClick={() => setOpen((value) => !value)}>
        toggle
      </button>
      <RenameDocumentDialog
        open={open}
        name={name}
        onSave={onSave}
        onClose={() => setOpen(false)}
      />
    </>
  )
}

function input(): HTMLElement {
  return screen.getByTestId('rename-input')
}

describe('RenameDocumentDialog', () => {
  it('startuje z bieżącą nazwą dokumentu', async () => {
    await renderWithProviders(<Harness onSave={vi.fn()} />)
    expect(input()).toHaveValue('stary.pdf')
    expect(screen.getByRole('dialog')).toHaveTextContent('Zmień nazwę dokumentu')
  })

  it('pusta nazwa po trim pokazuje błąd i nie woła `onSave`', async () => {
    const onSave = vi.fn()
    await renderWithProviders(<Harness onSave={onSave} />)
    const user = userEvent.setup()

    await user.clear(input())
    await user.type(input(), '   ')
    await user.click(screen.getByTestId('rename-save'))

    expect(screen.getByText('Nazwa jest wymagana')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('Enter zapisuje nazwę przyciętą', async () => {
    const onSave = vi.fn()
    await renderWithProviders(<Harness onSave={onSave} />)
    const user = userEvent.setup()

    await user.clear(input())
    await user.type(input(), '  nowa.pdf  ')
    await user.keyboard('{Enter}')

    expect(onSave).toHaveBeenCalledWith('nowa.pdf')
  })

  it('kliknięcie „Zapisz” zapisuje przyciętą nazwę', async () => {
    const onSave = vi.fn()
    await renderWithProviders(<Harness onSave={onSave} />)
    const user = userEvent.setup()

    await user.clear(input())
    await user.type(input(), 'raport.pdf')
    await user.click(screen.getByTestId('rename-save'))

    expect(onSave).toHaveBeenCalledWith('raport.pdf')
  })

  it('po ponownym otwarciu pole znów pokazuje bieżącą nazwę', async () => {
    await renderWithProviders(<Harness onSave={vi.fn()} />)
    const user = userEvent.setup()

    await user.clear(input())
    await user.type(input(), 'cokolwiek')

    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(input()).toHaveValue('stary.pdf')
  })
})
