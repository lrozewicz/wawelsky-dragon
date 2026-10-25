/**
 * Testy spięcia akcji wiersza i zbiorczych w `FilesPage` (kontrakt WP E4-5c §7, przykłady 1–8):
 * zmiana nazwy, nowy folder, przesłanie, przeniesienie, połączenie z datasetem, pobranie, podgląd
 * oraz blokada „Połącz” dla samych folderów i brak paska bez zaznaczenia. `downloadFile` jest
 * zamockowany (sprawdzamy podpięcie, nie zapis pliku), a `DocumentPreviewDrawer` podstawiony stubem,
 * bo podgląd ciągnie dodatkowe handlery.
 */

import type { ReactNode } from 'react'
import { act, cleanup, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import NotificationsProvider from '../../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../../i18n'
import {
  datasetHandlers,
  filesFixtureItems,
  fixtureDatasetDetail,
  resetFilesFixtures,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { downloadFile } from './downloadFile'
import { FilesPage } from './FilesPage'
import { useFilesActions } from './useFilesActions'

vi.mock('./downloadFile', () => ({ downloadFile: vi.fn(async () => undefined) }))

vi.mock('../chats/preview/DocumentPreviewDrawer', () => ({
  DocumentPreviewDrawer: (props: { documentId: string | null; documentName?: string }) =>
    props.documentId === null ? null : (
      <div role="dialog" aria-label={props.documentName}>
        {props.documentId}
      </div>
    ),
}))

afterEach(() => {
  cleanup()
  vi.mocked(downloadFile).mockClear()
})

beforeEach(() => {
  resetFilesFixtures()
})

/** Trasy rejestrowane w routerze testowym: strona listy i cel chipu datasetu. */
const ROUTES = ['/files', '/dataset/files/$id']

function renderPage(route = '/files') {
  return renderWithProviders(<FilesPage />, { route, routes: ROUTES })
}

function grid(): HTMLElement {
  return screen.getByTestId('files-grid')
}

function rowOf(name: string): HTMLElement {
  return within(grid()).getByText(name).closest('[role="row"]') as HTMLElement
}

function seedDatasets(): void {
  server.use(...datasetHandlers([fixtureDatasetDetail({ id: 'ds-1', name: 'Baza wiedzy' })]))
}

describe('FilesPage — akcje wiersza', () => {
  it('zmiana nazwy z wiersza odświeża siatkę', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('notatki.txt')).getByRole('button', { name: 'Zmień nazwę' }))
    const input = await screen.findByTestId('files-rename-name')
    await user.clear(input)
    await user.type(input, 'inna.txt')
    await user.click(screen.getByTestId('files-rename-save'))

    await waitFor(() => {
      expect(within(grid()).getByText('inna.txt')).toBeInTheDocument()
      expect(within(grid()).queryByText('notatki.txt')).not.toBeInTheDocument()
    })
  })

  it('menu Dodaj → Nowy folder tworzy folder w siatce', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(screen.getByTestId('files-add'))
    await user.click(await screen.findByTestId('files-add-folder'))
    await user.type(await screen.findByTestId('files-folder-name'), 'Faktury')
    await user.click(screen.getByTestId('files-folder-create'))

    expect(await within(grid()).findByText('Faktury')).toBeInTheDocument()
  })

  it('menu Dodaj → Prześlij pokazuje wejście pliku', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(screen.getByTestId('files-add'))
    await user.click(await screen.findByTestId('files-add-upload'))

    expect(await screen.findByTestId('files-upload-input')).toBeInTheDocument()
  })

  it('przeniesienie z wiersza do folderu Projekty', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('notatki.txt')).getByRole('button', { name: 'Przenieś' }))
    await user.click(await screen.findByTestId('folder-expand-__root__'))
    await user.click(await screen.findByTestId('folder-node-folder-1'))
    await user.click(screen.getByTestId('files-move-confirm'))

    await waitFor(() => expect(within(grid()).queryByText('notatki.txt')).not.toBeInTheDocument())

    await user.click(await within(grid()).findByRole('button', { name: 'Projekty' }))
    expect(await within(grid()).findByText('notatki.txt')).toBeInTheDocument()
    expect(within(grid()).getByText('umowa.docx')).toBeInTheDocument()
  })

  it('połączenie z datasetem pokazuje chip w wierszu', async () => {
    seedDatasets()
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(
      within(rowOf('notatki.txt')).getByRole('button', { name: 'Połącz z datasetem' }),
    )
    await user.click(await screen.findByTestId('files-link-dataset-ds-1'))
    await user.click(screen.getByTestId('files-link-confirm'))

    await waitFor(() => {
      const row = rowOf('notatki.txt')
      expect(within(row).getByTestId('files-kb-chip')).toHaveTextContent('Baza wiedzy')
    })
  })

  it('pobranie wiersza woła downloadFile z plikiem', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('notatki.txt')).getByRole('button', { name: 'Pobierz' }))

    await waitFor(() =>
      expect(downloadFile).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'file-1', name: 'notatki.txt' }),
      ),
    )
  })

  it('błąd pobrania melduje powiadomienie', async () => {
    vi.mocked(downloadFile).mockRejectedValueOnce(new Error('boom'))
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('notatki.txt')).getByRole('button', { name: 'Pobierz' }))

    expect(await screen.findByText('Operacja nie powiodła się.')).toBeInTheDocument()
  })

  it('podgląd raport.pdf otwiera szufladę dokumentu doc-1', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('raport.pdf')

    await user.click(within(rowOf('raport.pdf')).getByRole('button', { name: 'Podgląd' }))

    const drawer = await screen.findByRole('dialog', { name: 'raport.pdf' })
    // Żądanie podglądu wskazuje dokument datasetu z `kbs_info` (przykład briefu: doc-1).
    expect(drawer).toHaveTextContent('doc-1')
  })
})

describe('FilesPage — akcje zbiorcze', () => {
  it('bez zaznaczenia pasek zbiorczy jest nieobecny', async () => {
    await renderPage()
    await screen.findByText('notatki.txt')

    expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument()
  })

  it('zaznaczenie samego folderu blokuje Połącz', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('Projekty')

    await user.click(within(rowOf('Projekty')).getByRole('checkbox'))

    const bar = await screen.findByTestId('files-bulk-bar')
    expect(within(bar).getByTestId('files-bulk-link')).toBeDisabled()
  })

  it('zbiorcze Połącz pomija foldery i łączy tylko pliki', async () => {
    seedDatasets()
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('Projekty')).getByRole('checkbox'))
    await user.click(within(rowOf('notatki.txt')).getByRole('checkbox'))
    await user.click(screen.getByTestId('files-bulk-link'))
    await user.click(await screen.findByTestId('files-link-dataset-ds-1'))
    await user.click(screen.getByTestId('files-link-confirm'))

    await waitFor(() => {
      const row = rowOf('notatki.txt')
      expect(within(row).getByTestId('files-kb-chip')).toHaveTextContent('Baza wiedzy')
    })
    expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument()
  })

  it('zbiorcze Przenieś przenosi zaznaczone pliki do folderu', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('notatki.txt')).getByRole('checkbox'))
    await user.click(screen.getByTestId('files-bulk-move'))
    await user.click(await screen.findByTestId('folder-expand-__root__'))
    await user.click(await screen.findByTestId('folder-node-folder-1'))
    await user.click(screen.getByTestId('files-move-confirm'))

    await waitFor(() => expect(within(grid()).queryByText('notatki.txt')).not.toBeInTheDocument())
    expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument()
  })

  it('przycisk czyszczenia zaznaczenia ukrywa pasek', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByText('notatki.txt')

    await user.click(within(rowOf('notatki.txt')).getByRole('checkbox'))
    const bar = await screen.findByTestId('files-bulk-bar')
    await user.click(within(bar).getByRole('button', { name: 'Anuluj' }))

    await waitFor(() => expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument())
  })
})

/** Opakowanie hooka: kontekst powiadomień i klient zapytań (i18n inicjujemy w teście). */
const hookQueryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

function hookWrapper({ children }: { children: ReactNode }) {
  return (
    <NotificationsProvider>
      <QueryClientProvider client={hookQueryClient}>{children}</QueryClientProvider>
    </NotificationsProvider>
  )
}

describe('useFilesActions — stany brzegowe', () => {
  it('puste zaznaczenie nie otwiera dialogów ani nie czyści', async () => {
    await initI18n('pl')
    const clear = vi.fn()
    const { result } = renderHook(
      () => useFilesActions({ rows: [], selectedIds: [], onClearSelection: clear }),
      { wrapper: hookWrapper },
    )

    act(() => {
      result.current.linkSelected()
      result.current.moveSelected()
      result.current.deleteSelected()
      result.current.confirmDelete()
    })

    expect(result.current.linkTargets).toBeNull()
    expect(result.current.moveTargets).toBeNull()
    expect(result.current.deleteTargets).toBeNull()
    expect(clear).not.toHaveBeenCalled()
  })

  it('podgląd pliku bez kbs_info nic nie otwiera', async () => {
    await initI18n('pl')
    const plain = filesFixtureItems.find((item) => item.id === 'file-1')!
    const { result } = renderHook(
      () =>
        useFilesActions({
          rows: [plain],
          selectedIds: [plain.id],
          onClearSelection: () => undefined,
        }),
      { wrapper: hookWrapper },
    )

    act(() => result.current.onAction('preview', plain))

    expect(result.current.previewDoc).toBeNull()
  })
})
