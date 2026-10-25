/**
 * Dialog formularza integracji w trybie edycji (kontrakt WP E4-3c §1, brief T3 p. 7): pola
 * wypełnione z zapisanej integracji, maska sekretu bez pełnej wartości, PATCH z sekretem i bez
 * niego, test połączenia zapisanej integracji oraz brak sekretu po zamknięciu i ponownym otwarciu.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  fixtureDatasetDetail,
  makeIntegration,
} from '../../../test/msw/handlers'
import type { Integration } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { IntegrationFormDialog } from './IntegrationFormDialog'

afterEach(cleanup)

const MASKED = '****abcd'
const EDITABLE = makeIntegration({
  id: 2,
  name: 'Dokumenty zespołu',
  dataset_id: 'ds-1',
  client_secret_masked: MASKED,
})

type User = ReturnType<typeof userEvent.setup>
type RecordedCall = { id: number; body: Record<string, unknown> }

/** Dialog z rodzicem trzymającym `open` — pozwala zamknąć i otworzyć formularz ponownie. */
function EditHarness(props: { integration: Integration }): JSX.Element {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button type="button" data-testid="reopen" onClick={() => setOpen(true)}>
        otwórz
      </button>
      <IntegrationFormDialog
        open={open}
        integration={props.integration}
        onClose={() => setOpen(false)}
      />
    </>
  )
}

/** Scenariusz edycji: lista datasetów z MSW + świeży dialog dla zapisanej integracji. */
async function renderEditForm(): Promise<User> {
  server.use(...datasetHandlers([fixtureDatasetDetail({ id: 'ds-1', name: 'Baza wiedzy' })]))
  const user = userEvent.setup()
  await renderWithProviders(<EditHarness integration={EDITABLE} />)
  return user
}

/** Handler PATCH-a zapisujący ciała żądań (id z adresu + ciało). */
function recordPatches(calls: RecordedCall[]): ReturnType<typeof http.patch> {
  return http.patch(apiUrl('/api/wd/v1/integrations/:id'), async ({ params, request }) => {
    calls.push({
      id: Number(String(params.id)),
      body: (await request.json()) as Record<string, unknown>,
    })
    return HttpResponse.json({ data: makeIntegration({ id: 2 }) })
  })
}

/** Handler testu zapisanej integracji — zwraca padające uwierzytelnienie (stos bez Graph). */
function recordSavedTests(calls: RecordedCall[]): ReturnType<typeof http.post> {
  return http.post(apiUrl('/api/wd/v1/integrations/:id/test'), async ({ params, request }) => {
    calls.push({
      id: Number(String(params.id)),
      body: (await request.json()) as Record<string, unknown>,
    })
    return HttpResponse.json({
      data: {
        graph_auth: 'failed',
        graph_auth_error: 'Invalid tenant',
        site_resolution: 'skipped',
        dataset_exists: 'skipped',
      },
    })
  })
}

describe('IntegrationFormDialog — edycja', () => {
  it('wypełnia pola z integracji, a sekret zostawia pusty z maską w podpowiedzi', async () => {
    await renderEditForm()

    expect(screen.getByRole('dialog')).toHaveAccessibleName('Edycja integracji')
    expect(screen.getByTestId('integration-field-name')).toHaveValue('Dokumenty zespołu')
    expect(screen.getByTestId('integration-field-tenant_id')).toHaveValue('tenant-test')

    const secret = screen.getByTestId('integration-field-client_secret')
    expect(secret).toHaveValue('')
    expect(secret).toHaveAttribute('autocomplete', 'new-password')
    // Widać wyłącznie maskę z API — pełna wartość sekretu nigdy nie trafia do formularza.
    expect(
      screen.getByText(`Zapisany sekret: ${MASKED} — puste pole oznacza bez zmiany`),
    ).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('sekret-test')
  })

  it('dataset pokazuje nazwę z listy i zostaje aktywny (API pozwala go zmienić)', async () => {
    const user = await renderEditForm()

    const field = screen.getByTestId('integration-field-dataset_id')
    // Lista datasetów dochodzi asynchronicznie — do tego czasu pole pokazuje surowe id.
    await waitFor(() => expect(field).toHaveTextContent('Baza wiedzy'))

    await user.click(within(field).getByRole('combobox'))
    expect(await screen.findByRole('option', { name: 'Baza wiedzy' })).toBeInTheDocument()
  })

  it('przy pustym sekrecie wysyła PATCH bez `client_secret` i zamyka dialog', async () => {
    const calls: RecordedCall[] = []
    server.use(recordPatches(calls))
    const user = await renderEditForm()

    fireEvent.change(screen.getByTestId('integration-field-name'), {
      target: { value: 'Nowa nazwa' },
    })
    await user.click(screen.getByTestId('integration-save'))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.id).toBe(2)
    expect(calls[0]?.body).toMatchObject({ name: 'Nowa nazwa', dataset_id: 'ds-1' })
    expect(calls[0]?.body).not.toHaveProperty('client_secret')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('z wpisanym sekretem wysyła go w PATCH-u', async () => {
    const calls: RecordedCall[] = []
    server.use(recordPatches(calls))
    const user = await renderEditForm()

    await user.type(screen.getByTestId('integration-field-client_secret'), 'nowy-sekret')
    await user.click(screen.getByTestId('integration-save'))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.body).toMatchObject({ client_secret: 'nowy-sekret' })
  })

  it('po zamknięciu i ponownym otwarciu pole sekretu jest puste', async () => {
    const user = await renderEditForm()
    const secret = screen.getByTestId('integration-field-client_secret')

    await user.type(secret, 'nowy-sekret')
    expect(secret).toHaveValue('nowy-sekret')

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    await user.click(screen.getByTestId('reopen'))

    expect(await screen.findByTestId('integration-field-client_secret')).toHaveValue('')
  })

  it('test połączenia woła trasę zapisanej integracji i pokazuje wynik', async () => {
    const calls: RecordedCall[] = []
    server.use(recordSavedTests(calls))
    const user = await renderEditForm()

    await user.click(screen.getByTestId('integration-test'))

    const result = await screen.findByTestId('integration-test-result')
    expect(within(result).getByTestId('integration-test-graph_auth')).toHaveTextContent('Błąd')
    expect(calls).toHaveLength(1)
    expect(calls[0]?.id).toBe(2)
    expect(calls[0]?.body).toMatchObject({ tenant_id: 'tenant-test', dataset_id: 'ds-1' })
    expect(calls[0]?.body).not.toHaveProperty('client_secret')
  })
})
