/**
 * Testy usuwania z listy Plików (kontrakt WP E4-5c §7, przykłady 9–10): potwierdzenie zbiorcze
 * znika z siatki i melduje sukces; częściowa porażka (koperta 102) daje toast ostrzegawczy z liczbą
 * nieudanych i treścią błędów. Po zamknięciu dialogu zaznaczenie jest czyszczone.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { apiUrl, resetFilesFixtures } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { FilesPage } from './FilesPage'

afterEach(cleanup)

beforeEach(() => {
  resetFilesFixtures()
})

const ROUTES = ['/files', '/dataset/files/$id']

function renderPage() {
  return renderWithProviders(<FilesPage />, { route: '/files', routes: ROUTES })
}

function grid(): HTMLElement {
  return screen.getByTestId('files-grid')
}

async function selectRow(user: ReturnType<typeof userEvent.setup>, name: string): Promise<void> {
  const row = within(grid()).getByText(name).closest('[role="row"]') as HTMLElement
  await user.click(within(row).getByRole('checkbox'))
}

async function confirmDelete(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const dialog = await screen.findByRole('dialog')
  await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))
}

describe('FilesPage — usuwanie', () => {
  it('zbiorcze usunięcie dwóch plików usuwa je i melduje sukces', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await selectRow(user, 'notatki.txt')
    await selectRow(user, 'raport.pdf')
    await user.click(screen.getByTestId('files-bulk-delete'))
    await confirmDelete(user)

    await waitFor(() => {
      expect(within(grid()).queryByText('notatki.txt')).not.toBeInTheDocument()
      expect(within(grid()).queryByText('raport.pdf')).not.toBeInTheDocument()
    })
    expect(await screen.findByText('Usunięto pliki.')).toBeInTheDocument()
    expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument()
  })

  it('częściowa porażka (102) pokazuje liczbę i treść błędów', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({
          code: 102,
          message: 'Deleted files failed with 1 errors',
          data: {
            success_count: 0,
            errors: ['File or Folder not found: file-1'],
          },
        }),
      ),
    )

    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await selectRow(user, 'notatki.txt')
    await user.click(screen.getByTestId('files-bulk-delete'))
    await confirmDelete(user)

    const toast = await screen.findByText(/nie udało się: 1/)
    expect(toast).toHaveTextContent('File or Folder not found: file-1')
  })

  it('błąd usuwania pokazuje komunikat koperty', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({ code: 500, message: 'Nie wolno usuwać.' }),
      ),
    )

    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await selectRow(user, 'notatki.txt')
    await user.click(screen.getByTestId('files-bulk-delete'))
    await confirmDelete(user)

    expect(await screen.findByText('Nie wolno usuwać.')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument())
  })

  it('błąd usuwania bez komunikatu pokazuje komunikat ogólny', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () => HttpResponse.json({ code: 500, message: '' })),
    )

    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await selectRow(user, 'notatki.txt')
    await user.click(screen.getByTestId('files-bulk-delete'))
    await confirmDelete(user)

    expect(await screen.findByText('Operacja nie powiodła się.')).toBeInTheDocument()
  })

  it('anulowanie potwierdzenia zamyka dialog i nic nie usuwa', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await selectRow(user, 'notatki.txt')
    await user.click(screen.getByTestId('files-bulk-delete'))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Anuluj' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(within(grid()).getByText('notatki.txt')).toBeInTheDocument()
  })
})
