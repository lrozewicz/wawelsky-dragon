import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../test/renderWithProviders'

import { ConfirmDialog } from './ConfirmDialog'

afterEach(cleanup)

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  return renderWithProviders(
    <ConfirmDialog
      open
      title="Usuń czat"
      message="Czy usunąć czat „Alfa”?"
      confirmLabel="Usuń"
      cancelLabel="Anuluj"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  ).then(() => ({ onConfirm, onCancel }))
}

describe('ConfirmDialog', () => {
  it('pokazuje tytuł i komunikat, a potwierdzenie woła onConfirm', async () => {
    const { onConfirm, onCancel } = await renderDialog()
    const user = userEvent.setup()

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Usuń czat')
    expect(dialog).toHaveTextContent('Czy usunąć czat „Alfa”?')

    await user.click(screen.getByRole('button', { name: 'Usuń' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('anulowanie woła onCancel', async () => {
    const { onConfirm, onCancel } = await renderDialog()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('zamknięte okno nie renderuje treści', async () => {
    await renderDialog({ open: false })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('w trakcie zapisu przycisk potwierdzenia jest nieaktywny', async () => {
    await renderDialog({ loading: true })

    expect(screen.getByRole('button', { name: /Usuń/ })).toBeDisabled()
  })

  it('renderuje `children` pod komunikatem', async () => {
    await renderDialog({ children: <span data-testid="extra">dodatkowa opcja</span> })

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Czy usunąć czat „Alfa”?')).toBeInTheDocument()
    expect(within(dialog).getByTestId('extra')).toHaveTextContent('dodatkowa opcja')
  })
})
