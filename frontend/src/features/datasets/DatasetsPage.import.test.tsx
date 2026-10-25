/**
 * Przycisk „Importuj" listy baz (08 §7.15, brief T6): obok „Utwórz bazę wiedzy", otwiera dialog
 * „Importuj bazę wiedzy" przez kontekst hosta (`openImport`); Esc zamyka; po starcie importu
 * dialog znika, a host (`addTask`) dodaje wiersz paska zadań z etykietą nazwy i `dataset_id=null`.
 * Wydzielony plik — `DatasetsPage.test.tsx` stoi na limicie `max-lines` (eslint, DEC-098).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { datasetHandlers, fixtureDatasetDetail } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { DatasetsPage } from './DatasetsPage'

afterEach(cleanup)

beforeEach(() => {
  localStorage.clear()
})

const ROUTES = ['/datasets', '/dataset/files/$id']

/** Fixtur datasetu bez `tenant_id` — rozszerzenie jak w `DatasetsPage.export.test.tsx`. */
function datasetWithTenant(id: string, name: string, tenantId: string) {
  return { ...fixtureDatasetDetail({ id, name }), tenant_id: tenantId }
}

/** Paczka 1-porcjowa — domyślny handler MSW kończy ją podsumowaniem (seed `kbDefaultSummary`). */
function smallPackage(): File {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00])], 'paczka.wdkb.zip', {
    type: 'application/zip',
  })
}

describe('DatasetsPage — przycisk „Importuj" (host KbTransferHost)', () => {
  it('obok „Utwórz bazę wiedzy", otwiera dialog z wyborem pliku i strefą upuszczania', async () => {
    server.use(...datasetHandlers([datasetWithTenant('ds-1', 'Alfa', 'u1')]))
    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await user.click(screen.getByRole('button', { name: 'Importuj' }))

    const dialog = screen.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
    expect(within(dialog).getByRole('button', { name: 'Wybierz plik' })).toBeVisible()
    expect(within(dialog).getByTestId('kb-import-dropzone')).toBeVisible()
  })

  it('Esc zamyka dialog importu', async () => {
    server.use(...datasetHandlers([datasetWithTenant('ds-1', 'Alfa', 'u1')]))
    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')
    await user.click(screen.getByRole('button', { name: 'Importuj' }))
    expect(screen.getByRole('dialog', { name: 'Importuj bazę wiedzy' })).toBeInTheDocument()

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('start importu: dialog znika, wiersz paska zadań z etykietą nazwy (addTask)', async () => {
    server.use(...datasetHandlers([datasetWithTenant('ds-1', 'Alfa', 'u1')]))
    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await user.click(screen.getByRole('button', { name: 'Importuj' }))
    const dialog = screen.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
    await user.upload(within(dialog).getByTestId('kb-import-input'), [smallPackage()])
    await within(dialog).findByTestId('kb-import-summary')
    await user.click(within(dialog).getByRole('button', { name: 'Importuj' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const row = await screen.findByTestId('kb-task-row')
    expect(row).toHaveAttribute('data-task-kind', 'import')
    expect(row).toHaveAttribute('data-task-status', 'queued')
    // Etykieta = nazwa z pola (ziarno MSW: `name_taken` → `suggested_name`).
    expect(row).toHaveTextContent('Import „Rocznik GUS 2024 (import 2026-10-13)”')
    expect(screen.getByRole('button', { name: 'Importuj' })).toBeInTheDocument()
  })
})
