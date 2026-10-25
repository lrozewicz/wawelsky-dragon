/**
 * Strona `/files` (kontrakt WP E4-5c §2, §7): wiersze ziarna, wejście do folderu przez
 * `?folder=`, wyszukiwanie z debounce, pusty stan (także brak wyników), błąd listy i menu „Dodaj”.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { apiUrl, filesFixtureRoot, resetFilesFixtures } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { FilesPage } from './FilesPage'

afterEach(cleanup)

beforeEach(() => {
  resetFilesFixtures()
})

/** Trasy rejestrowane w routerze testowym: strona listy i cel chipu datasetu. */
const ROUTES = ['/files', '/dataset/files/$id']

function renderPage(route = '/files') {
  return renderWithProviders(<FilesPage />, { route, routes: ROUTES })
}

function emptyFilesHandler(): void {
  server.use(
    http.get(apiUrl('/api/v1/files'), () =>
      HttpResponse.json({
        code: 0,
        message: '',
        data: { files: [], total: 0, parent_folder: filesFixtureRoot },
      }),
    ),
  )
}

describe('FilesPage', () => {
  it('pokazuje wiersze ziarna i chip datasetu w raport.pdf', async () => {
    await renderPage()

    expect(await screen.findByText('notatki.txt')).toBeInTheDocument()
    expect(screen.getByText('raport.pdf')).toBeInTheDocument()

    const row = screen.getByText('raport.pdf').closest('[role="row"]') as HTMLElement
    expect(within(row).getByTestId('files-kb-chip')).toHaveTextContent('Baza wiedzy')
  })

  it('klik folderu nawiguje z ?folder= i pokazuje jego zawartość oraz breadcrumbs', async () => {
    const user = userEvent.setup()
    const { router } = await renderPage()

    await user.click(await screen.findByRole('button', { name: 'Projekty' }))

    await screen.findByText('umowa.docx')
    expect(router.state.location.search).toEqual({ folder: 'folder-1' })
    expect(screen.queryByText('notatki.txt')).not.toBeInTheDocument()

    const trail = screen.getByTestId('files-breadcrumbs')
    expect(within(trail).getByText('Pliki')).toBeInTheDocument()
    expect(within(trail).getByText('Projekty')).toBeInTheDocument()
  })

  it('wpisanie frazy po debounce zawęża siatkę', async () => {
    const user = userEvent.setup()
    await renderPage()

    const input = within(screen.getByTestId('files-search')).getByRole('textbox')
    await user.type(input, 'rap')

    await screen.findByText('raport.pdf')
    await waitFor(() => {
      expect(screen.queryByText('notatki.txt')).not.toBeInTheDocument()
    })
  })

  it('brak wyników wyszukiwania pokazuje dedykowany pusty stan', async () => {
    const user = userEvent.setup()
    await renderPage()

    const input = within(screen.getByTestId('files-search')).getByRole('textbox')
    await user.type(input, 'zzz')

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Brak wyników wyszukiwania.')
  })

  it('pusta lista pokazuje pusty stan z akcją tworzenia opisu', async () => {
    emptyFilesHandler()

    await renderPage()

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Brak plików')
  })

  it('błąd listy pokazuje Alert z komunikatem', async () => {
    server.use(http.get(apiUrl('/api/v1/files'), () => new HttpResponse(null, { status: 500 })))

    await renderPage()

    expect(await screen.findByText('Nie udało się wczytać plików.')).toBeInTheDocument()
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    // Trzy zapytania `/api/v1/files` startują z ekranem (lista + leniwe drzewo „Przenieś”),
    // więc błąd trzymamy flagą do chwili ponowienia, a nie licznikiem żądań.
    let failing = true
    server.use(
      http.get(apiUrl('/api/v1/files'), () => {
        if (failing) return new HttpResponse(null, { status: 500 })
        return HttpResponse.json({
          code: 0,
          message: '',
          data: { files: [], total: 0, parent_folder: filesFixtureRoot },
        })
      }),
    )

    const user = userEvent.setup()
    await renderPage()

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać plików.',
    )

    failing = false
    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
  })

  it('przycisk Dodaj otwiera menu z pozycjami Prześlij i Nowy folder', async () => {
    const user = userEvent.setup()
    await renderPage()

    await user.click(screen.getByTestId('files-add'))

    const upload = await screen.findByTestId('files-add-upload')
    expect(upload).toBeInTheDocument()
    expect(screen.getByTestId('files-add-folder')).toBeInTheDocument()

    // Pozycje menu zapisują żądanie dialogu (T4 je zrealizuje) i zamykają menu.
    await user.click(screen.getByTestId('files-add-folder'))
    expect(screen.queryByTestId('files-add-upload')).not.toBeInTheDocument()
  })

  it('klik „Pliki” w breadcrumbs wraca na root i czyści ?folder=', async () => {
    const user = userEvent.setup()
    const { router } = await renderPage('/files?folder=folder-1')

    await screen.findByText('umowa.docx')
    await user.click(
      within(screen.getByTestId('files-breadcrumbs')).getByRole('button', { name: 'Pliki' }),
    )

    await screen.findByText('notatki.txt')
    expect(router.state.location.search).toEqual({})
  })
})
