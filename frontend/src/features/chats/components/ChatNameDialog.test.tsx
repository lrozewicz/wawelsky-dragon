import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, datasetsHandlers, fixtureChatDatasets } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChatNameDialog } from './ChatNameDialog'

afterEach(cleanup)

type DialogProps = Parameters<typeof ChatNameDialog>[0]

async function renderDialog(overrides: Partial<DialogProps> = {}) {
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  await renderWithProviders(
    <ChatNameDialog
      title="Utwórz czat"
      submitLabel="Utwórz"
      onSubmit={onSubmit}
      onClose={onClose}
      {...overrides}
    />,
  )
  return { onSubmit, onClose }
}

/** Opcja listy baz po widocznej nazwie (wzór: ChatSettingsDrawer.test). */
async function optionByText(text: string) {
  const field = screen.getByRole('combobox', { name: 'Bazy wiedzy (opcjonalnie)' })
  await userEvent.setup().click(field)
  return within(await screen.findByRole('listbox')).getByRole('option', { name: new RegExp(text) })
}

describe('ChatNameDialog', () => {
  it('startuje z nazwą początkową, a zapisuje nazwę po trim', async () => {
    const { onSubmit } = await renderDialog({
      title: 'Zmień nazwę',
      submitLabel: 'Zapisz',
      initialName: 'Alfa',
    })
    const user = userEvent.setup()

    const field = screen.getByLabelText(/Nazwa/)
    expect(field).toHaveValue('Alfa')

    await user.clear(field)
    await user.type(field, '  Beta  ')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(onSubmit).toHaveBeenCalledWith('Beta', [])
  })

  it('Enter w polu nazwy zatwierdza formularz', async () => {
    const { onSubmit } = await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa/), 'Nowy{Enter}')

    // Drugi argument to lista baz (`dataset_ids`) — bez wyboru pusta.
    expect(onSubmit).toHaveBeenCalledWith('Nowy', [])
  })

  it('bez nazwy przycisk zapisu pozostaje aktywny (U11)', async () => {
    await renderDialog()

    expect(screen.getByRole('button', { name: 'Utwórz' })).toBeEnabled()
  })

  it('klik z pustą nazwą pokazuje komunikat pod polem i wraca fokusem (U11)', async () => {
    const { onSubmit } = await renderDialog()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Utwórz' }))

    const field = screen.getByLabelText(/Nazwa/)
    expect(field).toHaveFocus()
    expect(screen.getByText('Pole wymagane')).toBeInTheDocument()
    // Etykieta zostaje nad polem (shrink), choć pole jest puste.
    expect(field.closest('.MuiFormControl-root')?.querySelector('.MuiInputLabel-root')).toHaveClass(
      'MuiInputLabel-shrink',
    )
    // Enter przy błędzie nie wysyła formularza.
    await user.type(field, '{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('wpisanie nazwy gasi komunikat od razu (U11)', async () => {
    await renderDialog()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    expect(screen.getByText('Pole wymagane')).toBeInTheDocument()

    await user.type(screen.getByLabelText(/Nazwa/), 'N')

    expect(screen.queryByText('Pole wymagane')).not.toBeInTheDocument()
  })

  it('podwójny klik „Utwórz” wysyła onSubmit raz (U7 — blokada szybsza niż re-render loading)', async () => {
    const { onSubmit } = await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa/), 'Jeden')
    await user.dblClick(screen.getByRole('button', { name: 'Utwórz' }))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith('Jeden', [])
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

describe('ChatNameDialog — bazy wiedzy przy tworzeniu (SC-V13-10)', () => {
  it('tryb tworzenia pokazuje pole baz i teksty pomocnicze', async () => {
    server.use(...datasetsHandlers(fixtureChatDatasets))
    await renderDialog({ showDatasets: true })

    expect(screen.getByRole('combobox', { name: 'Bazy wiedzy (opcjonalnie)' })).toBeInTheDocument()
    expect(screen.getByText('Bez bazy czat odpowiada tylko z wiedzy modelu.')).toBeInTheDocument()
    expect(
      screen.getByText('Bazy możesz zmienić później w ustawieniach czatu.'),
    ).toBeInTheDocument()
  })

  it('baza bez chunków jest wyszarzona z widocznym dopiskiem „brak przetworzonych plików”', async () => {
    server.use(...datasetsHandlers(fixtureChatDatasets))
    await renderDialog({ showDatasets: true })

    const empty = await optionByText('Pusta baza')
    expect(empty).toHaveAttribute('aria-disabled', 'true')
    expect(empty).toHaveTextContent('brak przetworzonych plików')
    // Pełna nazwa w dymku opcji (QA V13-z-2 D4) — także gdy nazwa jest skrócona wielokropkiem.
    expect(empty).toHaveAttribute('title', 'Pusta baza')
  })

  it('wybór bazy trafia do onSubmit jako drugi argument (dataset_ids)', async () => {
    server.use(...datasetsHandlers(fixtureChatDatasets))
    const { onSubmit } = await renderDialog({ showDatasets: true })
    const user = userEvent.setup()

    await user.click(await optionByText('Baza wiedzy'))
    // Chip z nazwą wybranej bazy w polu; wybór ZAMYKA listę (QA MAJOR-1) — przycisk „Utwórz”
    // jest od razu klikalny bez zamykania listy ręcznie.
    expect(document.querySelector('.MuiChip-label')).toHaveTextContent('Baza wiedzy')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText(/Nazwa/), 'Z bazą')
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))

    expect(onSubmit).toHaveBeenCalledWith('Z bazą', ['ds-1'])
  })

  it('bez wyboru bazy onSubmit dostaje pustą listę', async () => {
    server.use(...datasetsHandlers(fixtureChatDatasets))
    const { onSubmit } = await renderDialog({ showDatasets: true })
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa/), 'Bez baz')
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))

    expect(onSubmit).toHaveBeenCalledWith('Bez baz', [])
  })

  it('zmiana nazwy (bez showDatasets) nie ma pola baz', async () => {
    await renderDialog({
      title: 'Zmień nazwę',
      submitLabel: 'Zapisz',
      initialName: 'Alfa',
    })

    expect(
      screen.queryByRole('combobox', { name: 'Bazy wiedzy (opcjonalnie)' }),
    ).not.toBeInTheDocument()
  })

  it('błąd pobierania baz nie blokuje tworzenia czatu (lista pusta)', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({ code: 500, message: 'boom', data: false }, { status: 500 }),
      ),
    )
    const { onSubmit } = await renderDialog({ showDatasets: true })
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa/), 'Bez listy')
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))

    expect(onSubmit).toHaveBeenCalledWith('Bez listy', [])
  })
})
