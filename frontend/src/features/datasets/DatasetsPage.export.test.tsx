/**
 * Pozycja ⋮ „Eksportuj” (CONTRACT WP E7-2 §8 / SC-E7-2-05): widoczna tylko dla właściciela bazy
 * (`tenant_id == me.id`) i superusera; pozostałe pozycje menu bez zmian. Wydzielony do osobnego
 * pliku, bo `DatasetsPage.test.tsx` siedzi na limicie `max-lines` (300).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  fixtureDatasetDetail,
  fixtureUser,
  KB_DATASET_ID,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { kbTasksStorageKey } from '../kb-transfer/taskStore'
import type { StoredKbTask } from '../kb-transfer/types'

import { DatasetsPage } from './DatasetsPage'

afterEach(cleanup)

beforeEach(() => {
  localStorage.clear()
})

const ROUTES = ['/datasets', '/dataset/files/$id']

/** Fixtur datasetu nie ma `tenant_id` (schema go wymaga) — rozszerzamy bez zmiany pliku fixtures. */
function datasetWithTenant(id: string, name: string, tenantId: string) {
  return { ...fixtureDatasetDetail({ id, name }), tenant_id: tenantId }
}

async function openCardMenu(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole('button', { name: `Menu bazy wiedzy ${name}` }))
}

describe('DatasetsPage — pozycja ⋮ „Eksportuj” (widoczność wg właściciela)', () => {
  it('właściciel widzi pozycję i po kliknięciu otwiera dialog eksportu', async () => {
    server.use(...datasetHandlers([datasetWithTenant('ds-1', 'Alfa', 'u1')]))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Eksportuj' }))

    // Dialog eksportu nad listą (podgląd `ds-1` padnie 404 — widoczność dialogu wystarczy).
    expect(await screen.findByRole('dialog', { name: 'Eksportuj „Alfa”' })).toBeInTheDocument()
  })

  it('członek zespołu przy cudzej bazie nie widzi pozycji (SC-E7-2-05 krok 1)', async () => {
    server.use(...datasetHandlers([datasetWithTenant('ds-1', 'Alfa', 'u2')]))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    expect(await screen.findByRole('menuitem', { name: 'Zmień nazwę' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Eksportuj' })).not.toBeInTheDocument()
  })

  it('superuser widzi pozycję przy cudzej bazie (SC-E7-2-05 krok 2)', async () => {
    server.use(...datasetHandlers([datasetWithTenant('ds-1', 'Alfa', 'u2')]))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, {
      routes: ROUTES,
      auth: { user: { ...fixtureUser, is_superuser: true } },
    })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    expect(await screen.findByRole('menuitem', { name: 'Eksportuj' })).toBeInTheDocument()
  })
})

describe('DatasetsPage — pasek zadań eksportu (host KbTransferHost)', () => {
  it('start eksportu dodaje wiersz do paska pod nagłówkiem (host: addTask)', async () => {
    server.use(...datasetHandlers([datasetWithTenant(KB_DATASET_ID, 'Alfa', 'u1')]))
    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Eksportuj' }))
    const dialog = await screen.findByRole('dialog', { name: 'Eksportuj „Alfa”' })
    await waitFor(() => {
      expect(within(dialog).getByTestId('kb-export-summary')).toBeInTheDocument()
    })
    await user.click(within(dialog).getByRole('button', { name: 'Eksportuj' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    const row = await screen.findByTestId('kb-task-row')
    expect(row).toHaveAttribute('data-task-kind', 'export')
    expect(row).toHaveAttribute('data-task-status', 'queued')
    expect(row).toHaveTextContent('Eksport „Alfa”')
  })

  it('409 `export_in_progress` podświetla istniejący wiersz (onExisting → highlightTask)', async () => {
    // Wiersz istniejącego zadania w magazynie (stan końcowy — bez odpytania) i 409 na starcie.
    const row: StoredKbTask = {
      task_id: 'task-409',
      kind: 'export',
      label: 'Alfa',
      dataset_id: KB_DATASET_ID,
      added_at: Date.now(),
      last: {
        task_id: 'task-409',
        kind: 'export',
        dataset_id: KB_DATASET_ID,
        status: 'done',
        stage: null,
        done: 1,
        total: 1,
        progress: 1,
        message: 'Gotowe',
        error: null,
        created_at: Date.now(),
        finished_at: Date.now(),
        result: null,
      },
    }
    localStorage.setItem(kbTasksStorageKey(fixtureUser.id), JSON.stringify([row]))
    server.use(
      http.post(apiUrl('/api/wd/v1/datasets/d1/export'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'export_in_progress',
              message: 'Eksport tej bazy wiedzy już trwa.',
              details: { task_id: 'task-409' },
            },
          },
          { status: 409 },
        ),
      ),
    )
    server.use(...datasetHandlers([datasetWithTenant(KB_DATASET_ID, 'Alfa', 'u1')]))
    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Eksportuj' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Eksportuj' }))

    await waitFor(() =>
      expect(screen.getByTestId('kb-task-row')).toHaveAttribute('data-highlighted'),
    )
    expect(screen.getByTestId('kb-task-row')).toHaveAttribute('data-task-id', 'task-409')
  })
})
