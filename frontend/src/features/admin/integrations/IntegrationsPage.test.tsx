/**
 * Strona integracji (kontrakt WP E4-3c §1 i §T2 pkt 1–3, 6): wiersze siatki z chipami statusu,
 * stan pusty, błąd listy 403, otwieranie szczegółów i formularza oraz tabelaryczny `StatusChip`.
 * Stuby dialogów nic nie renderują, więc podsłuchujemy ich propsy (`vi.mock`) — inaczej nie da
 * się zaobserwować, że klik nazwy faktycznie otwiera szczegóły.
 */

import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, integrationsHandlers, makeIntegration } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { stubNarrowViewport } from '../../../test/stubNarrowViewport'

import { IntegrationsPage } from './IntegrationsPage'
import { StatusChip } from './StatusChip'

/** Propsy ostatniego renderu stubów dialogów (kontrakt §T2 pkt 6). */
const dialogProps = vi.hoisted(() => ({
  form: [] as { open: boolean; integration: { id: number } | null }[],
  details: [] as { integrationId: number | null }[],
}))

vi.mock('./IntegrationFormDialog', () => ({
  IntegrationFormDialog: (props: { open: boolean; integration: { id: number } | null }) => {
    dialogProps.form.push(props)
    return null
  },
}))

vi.mock('./IntegrationDetailsDialog', () => ({
  IntegrationDetailsDialog: (props: { integrationId: number | null }) => {
    dialogProps.details.push(props)
    return null
  },
}))

/** Ostatnie propsy formularza/ szczegółów — `undefined` gdy komponent jeszcze nie powstał. */
const lastForm = () => dialogProps.form.at(-1)
const lastDetails = () => dialogProps.details.at(-1)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

beforeEach(() => {
  dialogProps.form.length = 0
  dialogProps.details.length = 0
})

/** Dwie integracje o różnych harmonogramach i stanach ostatniego przebiegu. */
const twoIntegrations = [
  makeIntegration({
    id: 1,
    name: 'Dokumenty zespołu',
    dataset_id: 'ds-1',
    scan_interval_seconds: 300,
    last_sync_status: 'success',
    last_sync_at: '2025-01-01T00:00:00Z',
  }),
  makeIntegration({
    id: 2,
    name: 'Archiwum',
    dataset_id: 'ds-2',
    scan_interval_seconds: 30,
    last_sync_status: null,
    last_sync_at: null,
  }),
]

describe('IntegrationsPage', () => {
  it('pokazuje wiersze, nagłówki i chipy ostatniego przebiegu', async () => {
    server.use(...integrationsHandlers({ integrations: twoIntegrations }))

    await renderWithProviders(<IntegrationsPage />)

    const grid = await screen.findByTestId('integrations-grid')
    for (const header of [
      'Nazwa',
      'Dataset',
      'Harmonogram',
      'Ostatni przebieg',
      'Aktywna',
      'Akcje',
    ]) {
      expect(
        within(grid).getByRole('columnheader', { name: new RegExp(header) }),
      ).toBeInTheDocument()
    }

    expect(within(grid).getByText('Dokumenty zespołu')).toBeInTheDocument()
    expect(within(grid).getByText('Archiwum')).toBeInTheDocument()
    expect(within(grid).getByText('ds-1')).toBeInTheDocument()
    expect(within(grid).getByText('co 5 min')).toBeInTheDocument()
    expect(within(grid).getByText('co 30 s')).toBeInTheDocument()
    expect(within(grid).getByText('Sukces')).toBeInTheDocument()
    expect(within(grid).getByText('Nigdy')).toBeInTheDocument()
    // Wiersz bez ostatniego przebiegu pokazuje kreskę zamiast daty (kontrakt §0).
    expect(within(grid).getByText('—')).toBeInTheDocument()
    // W języku pl wspólny hook `useDataGridLocaleText` ustawia polskie etykiety siatki — stopka
    // paginacji pokazuje „Wierszy na stronę:" (`MuiTablePagination.labelRowsPerPage`) zamiast
    // domyślnego „Rows per page:".
    expect(screen.queryByText('Rows per page:')).not.toBeInTheDocument()
    expect(within(grid).getByText('Wierszy na stronę:')).toBeInTheDocument()
  })

  it('chowa kolumnę Dataset poniżej progu md (mobile 390 px)', async () => {
    stubNarrowViewport()
    server.use(...integrationsHandlers({ integrations: twoIntegrations }))

    await renderWithProviders(<IntegrationsPage />)

    const grid = await screen.findByTestId('integrations-grid')
    expect(within(grid).getByRole('columnheader', { name: /Nazwa/ })).toBeInTheDocument()
    expect(within(grid).queryByRole('columnheader', { name: /Dataset/ })).not.toBeInTheDocument()
  })

  it('otwiera formularz tworzenia przyciskiem „Dodaj integrację”', async () => {
    const user = userEvent.setup()

    await renderWithProviders(<IntegrationsPage />)
    await user.click(await screen.findByTestId('integration-add'))

    expect(lastForm()).toMatchObject({ open: true, integration: null })
  })

  it('klik nazwy otwiera szczegóły wskazanej integracji', async () => {
    server.use(...integrationsHandlers({ integrations: twoIntegrations }))
    const user = userEvent.setup()

    await renderWithProviders(<IntegrationsPage />)
    await user.click(await screen.findByTestId('integration-name-2'))

    expect(lastDetails()?.integrationId).toBe(2)
  })

  it('przycisk edycji otwiera formularz z wierszem integracji', async () => {
    server.use(...integrationsHandlers({ integrations: twoIntegrations }))
    const user = userEvent.setup()

    await renderWithProviders(<IntegrationsPage />)
    await user.click(await screen.findByTestId('integration-edit-1'))

    expect(lastForm()).toMatchObject({ open: true, integration: { id: 1 } })
  })

  it('pokazuje stan pusty, gdy lista jest pusta', async () => {
    await renderWithProviders(<IntegrationsPage />)

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Brak integracji')
    expect(empty).toHaveTextContent('Dodaj pierwszą integrację SharePoint.')
    expect(screen.queryByTestId('integrations-grid')).not.toBeInTheDocument()
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/wd/v1/integrations'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json(
            { error: { code: 'permission_denied', message: 'Brak dostępu' } },
            { status: 403 },
          )
        }
        return HttpResponse.json({
          data: {
            items: twoIntegrations,
            total: twoIntegrations.length,
            page: 1,
            page_size: 100,
          },
        })
      }),
    )
    const user = userEvent.setup()

    await renderWithProviders(<IntegrationsPage />)

    expect(await screen.findByTestId('query-error')).toHaveTextContent('Brak uprawnień.')

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByTestId('integrations-grid')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('na wąskim ekranie akcje są pierwszą kolumną jako menu ⋮', async () => {
    stubNarrowViewport()
    server.use(...integrationsHandlers({ integrations: twoIntegrations }))

    await renderWithProviders(<IntegrationsPage />)

    const grid = await screen.findByTestId('integrations-grid')
    expect(within(grid).getAllByRole('columnheader')[0]).toHaveAttribute('data-field', 'actions')
    expect(within(grid).getAllByTestId('row-actions-menu').length).toBeGreaterThan(0)
    expect(within(grid).queryByTestId('integration-edit-1')).not.toBeInTheDocument()
  })
})

describe('StatusChip', () => {
  const cases: [string | null, string, string][] = [
    [null, 'Nigdy', 'MuiChip-colorDefault'],
    ['running', 'W toku', 'MuiChip-colorInfo'],
    ['queued', 'W kolejce', 'MuiChip-colorInfo'],
    ['success', 'Sukces', 'MuiChip-colorSuccess'],
    ['partial', 'Częściowo', 'MuiChip-colorWarning'],
    ['failed', 'Błąd', 'MuiChip-colorError'],
    ['cancelled', 'Anulowano', 'MuiChip-colorDefault'],
  ]

  it.each(cases)('status %s → etykieta „%s” i kolor %s', async (status, label, chipClass) => {
    await renderWithProviders(<StatusChip status={status} />)

    const text = await screen.findByText(label)
    const chip = text.closest('.MuiChip-root')
    expect(chip).not.toBeNull()
    expect(chip).toHaveClass(chipClass)
  })
})
