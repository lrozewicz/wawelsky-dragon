import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { SearchNameDialog } from './SearchNameDialog'

afterEach(cleanup)

type DialogProps = Parameters<typeof SearchNameDialog>[0]

async function renderDialog(overrides: Partial<DialogProps> = {}) {
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  await renderWithProviders(
    <SearchNameDialog
      mode="create"
      busy={false}
      error={null}
      onSubmit={onSubmit}
      onClose={onClose}
      {...overrides}
    />,
  )
  return { onSubmit, onClose }
}

describe('SearchNameDialog', () => {
  it('w trybie tworzenia: tytuł, etykieta, puste pole z fokusem i aktywny zapis (U11)', async () => {
    await renderDialog()

    expect(screen.getByText('Utwórz wyszukiwarkę')).toBeInTheDocument()
    const field = screen.getByLabelText(/Nazwa/)
    expect(field).toHaveValue('')
    expect(field).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Utwórz' })).toBeEnabled()
  })

  it('w trybie zmiany nazwy startuje z nazwą początkową i zapisuje nazwę po trim', async () => {
    const { onSubmit } = await renderDialog({ mode: 'rename', initialName: 'Alfa' })
    const user = userEvent.setup()

    expect(screen.getByText('Zmień nazwę')).toBeInTheDocument()
    const field = screen.getByLabelText(/Nazwa/)
    expect(field).toHaveValue('Alfa')

    await user.clear(field)
    await user.type(field, '  Beta  ')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(onSubmit).toHaveBeenCalledWith('Beta')
  })

  it('Enter w polu nazwy zatwierdza formularz', async () => {
    const { onSubmit } = await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa/), 'Nowa{Enter}')

    expect(onSubmit).toHaveBeenCalledWith('Nowa')
  })

  it('sama spacja nie wystarcza — klik pokazuje komunikat, wraca fokusem i nie wysyła (U11)', async () => {
    const { onSubmit } = await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa/), '   ')
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))

    expect(screen.getByText('Pole wymagane')).toBeInTheDocument()
    expect(screen.getByLabelText(/Nazwa/)).toHaveFocus()
    expect(onSubmit).not.toHaveBeenCalled()

    // Wpisanie wartości gasi komunikat od razu.
    await user.type(screen.getByLabelText(/Nazwa/), 'N')
    expect(screen.queryByText('Pole wymagane')).not.toBeInTheDocument()
  })

  it('podczas mutacji (`busy`) przycisk zapisu jest nieaktywny', async () => {
    await renderDialog({ mode: 'rename', initialName: 'Alfa', busy: true })

    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })

  it('pokazuje błąd mutacji nad polem', async () => {
    await renderDialog({ error: 'nazwa jest zajęta' })

    expect(screen.getByRole('alert')).toHaveTextContent('nazwa jest zajęta')
  })

  it('„Anuluj” woła onClose', async () => {
    const { onSubmit, onClose } = await renderDialog()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
