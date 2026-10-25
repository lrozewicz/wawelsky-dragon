import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { formatBytes, formatDate } from '../../../lib/format'
import {
  apiUrl,
  datasetHandlers,
  documentsHandlers,
  fixtureDatasetDetail,
} from '../../../test/msw/handlers'
import type { FixtureDatasetDetail } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { DatasetFilesTab } from '../files/DatasetFilesTab'

import { DatasetLayout } from './DatasetLayout'
import type { DatasetTabKey } from './DatasetLayout'

// Atrapa `uploadForm`: jsdomowy `FormData` z blobem nie przechodzi przez przechwytywacz MSW
// (błąd `_buffer`, `docs/modules/frontend-files.md`), a ten test bada odświeżenie nagłówka,
// nie samą wysyłkę — realny XHR pokrywa `src/api/upload.test.ts`.
const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../../api/upload', () => ({ uploadForm: uploadFormMock }))

afterEach(cleanup)
afterEach(() => vi.unstubAllGlobals())
afterEach(() => {
  uploadFormMock.mockReset()
})

/** Trasy rejestrowane w routerze testowym: cztery zakładki i lista baz wiedzy (cel powrotu). */
const ROUTES = [
  '/datasets',
  '/dataset/files/$id',
  '/dataset/retrieval/$id',
  '/dataset/logs/$id',
  '/dataset/configuration/$id',
]

const CREATE_TIME = 1735689600000

const DATASET = fixtureDatasetDetail({
  id: 'ds-1',
  name: 'Baza testowa',
  document_count: 3,
  size: 4096,
  create_time: CREATE_TIME,
})

type RenderOptions = {
  datasetId?: string
  activeTab?: DatasetTabKey
  datasets?: FixtureDatasetDetail[]
}

async function renderLayout(options: RenderOptions = {}) {
  const { datasetId = 'ds-1', activeTab = 'files', datasets = [DATASET] } = options
  server.use(...datasetHandlers(datasets))

  return renderWithProviders(
    <DatasetLayout datasetId={datasetId} activeTab={activeTab}>
      <div>treść zakładki</div>
    </DatasetLayout>,
    { route: `/dataset/${activeTab}/${datasetId}`, routes: ROUTES },
  )
}

describe('DatasetLayout', () => {
  it('pokazuje nagłówek datasetu: inicjały, nazwę, liczbę plików z rozmiarem i datę utworzenia', async () => {
    await renderLayout()

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Baza testowa' }),
    ).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    expect(
      screen.getByText(`3 pliki · ${formatBytes(DATASET.size ?? 0, 'pl')}`),
    ).toBeInTheDocument()
    expect(screen.getByText(`Utworzono ${formatDate(CREATE_TIME, 'pl')}`)).toBeInTheDocument()
  })

  // Kontrakt WP E3-3b §T4 (c): liczba plików odmieniana przez plural i18next.
  it.each([
    [1, '1 plik'],
    [2, '2 pliki'],
    [5, '5 plików'],
    [22, '22 pliki'],
  ] as [number, string][])('odmienia liczbę plików: %i → „%s”', async (count, expected) => {
    await renderLayout({ datasets: [{ ...DATASET, document_count: count }] })

    expect(
      await screen.findByText(`${expected} · ${formatBytes(DATASET.size ?? 0, 'pl')}`),
    ).toBeInTheDocument()
  })

  it('renderuje treść przekazaną jako dzieci', async () => {
    await renderLayout()

    expect(await screen.findByText('treść zakładki')).toBeInTheDocument()
  })

  it('renderuje cztery zakładki-linki w kolejności z kontraktu i zaznacza aktywną', async () => {
    await renderLayout({ activeTab: 'logs' })
    await screen.findByRole('heading', { level: 1 })

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Pliki',
      'Test retrievalu',
      'Logi',
      'Konfiguracja',
    ])
    expect(screen.getByRole('tablist')).toHaveAttribute('aria-label', 'Zakładki bazy wiedzy')
    expect(tabs[0]).toHaveAttribute('href', '/dataset/files/ds-1')
    expect(tabs[1]).toHaveAttribute('href', '/dataset/retrieval/ds-1')
    expect(tabs[2]).toHaveAttribute('href', '/dataset/logs/ds-1')
    expect(tabs[3]).toHaveAttribute('href', '/dataset/configuration/ds-1')
    expect(tabs[2]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[0]).toHaveAttribute('aria-selected', 'false')
  })

  // Liczba pochodzi z plural i18next (placeholdery `{{count}}` bez formatowania `Intl`),
  // więc dla 1500 obowiązuje forma „many” — bez separatora grupowania.
  it('dla dużych liczb używa formy „many”', async () => {
    await renderLayout({ datasets: [{ ...DATASET, document_count: 1500 }] })

    expect(
      await screen.findByText(`1500 plików · ${formatBytes(DATASET.size ?? 0, 'pl')}`),
    ).toBeInTheDocument()
  })

  it('brak rozmiaru liczy jako zero bajtów', async () => {
    await renderLayout({ datasets: [{ ...DATASET, size: null }] })

    expect(await screen.findByText('3 pliki · 0 B')).toBeInTheDocument()
  })

  it('nieistniejący dataset pokazuje Alert i link powrotu do listy baz wiedzy', async () => {
    await renderLayout({ datasetId: 'brak', datasets: [] })

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać bazy wiedzy.')
    expect(screen.getByRole('link', { name: 'Wróć do baz wiedzy' })).toHaveAttribute(
      'href',
      '/datasets',
    )
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  })

  // Kontrakt WP E5-H6a §C1 + U3: nagłówek czyta szczegół zbioru (`datasetQueryOptions`), więc po
  // uploadzie z zakładki „Pliki” trzeba unieważnić TO zapytanie — bez tego licznik zostaje stary.
  it('po uploadzie w zakładce Pliki odświeża licznik plików w nagłówku', async () => {
    let uploaded = 0
    uploadFormMock.mockImplementation(async () => {
      uploaded += 1
      return [{ id: 'doc-1' }]
    })
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: { ...DATASET, document_count: 3 + uploaded },
        }),
      ),
      ...documentsHandlers(),
    )

    await renderWithProviders(
      <DatasetLayout datasetId="ds-1" activeTab="files">
        <DatasetFilesTab datasetId="ds-1" />
      </DatasetLayout>,
      { route: '/dataset/files/ds-1', routes: [...ROUTES, '/chunk/parsed/chunks'] },
    )
    const size = formatBytes(DATASET.size ?? 0, 'pl')
    expect(await screen.findByText(`3 pliki · ${size}`)).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByTestId('files-add'))
    const dialog = screen.getByRole('dialog')
    await user.upload(within(dialog).getByTestId('upload-input'), [
      new File(['a.pdf'], 'a.pdf', { type: 'application/pdf' }),
    ])
    await user.click(within(dialog).getByTestId('upload-start'))
    // Dowód, że upload doszedł do końca (a więc `onUploaded` zadziałał) — dopiero potem licznik.
    expect(await within(dialog).findByText('Przesłano')).toBeInTheDocument()

    expect(await screen.findByText(`4 pliki · ${size}`)).toBeInTheDocument()
  })

  it('poniżej progu md zakładki przewijają się poziomo', async () => {
    stubMatchMedia(true)

    await renderLayout()
    await screen.findByRole('heading', { level: 1 })

    expect(document.querySelector('.MuiTabs-scrollableX')).not.toBeNull()
  })

  it('od progu md zakładki mieszczą się w całości', async () => {
    await renderLayout()
    await screen.findByRole('heading', { level: 1 })

    expect(document.querySelector('.MuiTabs-scrollableX')).toBeNull()
  })
})

/** jsdom nie zna `matchMedia` — atrapa zwraca `true` na każde zapytanie (wąskie okno). */
function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })),
  )
}
