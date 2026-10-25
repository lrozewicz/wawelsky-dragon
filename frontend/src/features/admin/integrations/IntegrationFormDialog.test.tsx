/**
 * Dialog formularza integracji w trybie tworzenia (kontrakt WP E4-3c §1, brief T3 p. 7):
 * pełne ciało żądania, komunikaty walidacji bez wysyłki, wynik testu połączenia (padające
 * uwierzytelnienie i udana witryna z bibliotekami), konflikt datasetu, blokada zapisu
 * w trakcie mutacji oraz brak zapisu z Entera.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  fixtureDatasetDetail,
  integrationsHandlers,
  makeIntegration,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { stubNarrowViewport } from '../../../test/stubNarrowViewport'

import { IntegrationFormDialog } from './IntegrationFormDialog'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const DATASET_ID = 'ds-7'
const DATASET_NAME = 'Baza wiedzy'
const SITE_URL = 'https://example.invalid/sites/nowa'

type User = ReturnType<typeof userEvent.setup>

/** Dialog z rodzicem trzymającym `open` — pozwala sprawdzić zamknięcie po sukcesie. */
function FormHarness(): JSX.Element {
  const [open, setOpen] = useState(true)
  return <IntegrationFormDialog open={open} integration={null} onClose={() => setOpen(false)} />
}

/** Scenariusz tworzenia: lista datasetów z MSW + świeży dialog. */
async function renderCreateForm(): Promise<User> {
  server.use(...datasetHandlers([fixtureDatasetDetail({ id: DATASET_ID, name: DATASET_NAME })]))
  const user = userEvent.setup()
  await renderWithProviders(<FormHarness />)
  return user
}

/** Wstawia całą wartość pola jednym zdarzeniem — klepanie znak po znaku mnoży rendery formularza. */
function setText(testId: string, value: string): void {
  fireEvent.change(screen.getByTestId(testId), { target: { value } })
}

/** Wypełnia pola wymagane; dataset wybieramy z listy, żeby przejść walidację. */
async function fillRequiredFields(user: User, tenantId = 'tenant-test'): Promise<void> {
  setText('integration-field-name', 'Zespołowa')
  setText('integration-field-tenant_id', tenantId)
  setText('integration-field-client_id', 'client-9')
  setText('integration-field-client_secret', 'sekret-9')
  setText('integration-field-site_url', SITE_URL)
  // Menu otwiera dopiero wewnętrzny `combobox` selectu (`data-testid` siedzi na jego kontenerze).
  await user.click(screen.getByRole('combobox', { name: /Dataset docelowy/ }))
  await user.click(await screen.findByRole('option', { name: DATASET_NAME }))
}

/** Handler POST-a zapisujący ciała żądań — pozwala udowodnić i treść, i brak wysyłki. */
function recordCreates(bodies: unknown[]): ReturnType<typeof http.post> {
  return http.post(apiUrl('/api/wd/v1/integrations'), async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ data: makeIntegration({ id: 9 }) }, { status: 201 })
  })
}

describe('IntegrationFormDialog — tworzenie', () => {
  it('wysyła pełne ciało i zamyka dialog po sukcesie', async () => {
    const bodies: unknown[] = []
    server.use(recordCreates(bodies))
    const user = await renderCreateForm()

    await fillRequiredFields(user)
    // Wybrany dataset widać w polu — select pokazuje nazwę, a nie surowe id.
    expect(screen.getByTestId('integration-field-dataset_id')).toHaveTextContent(DATASET_NAME)
    await user.click(screen.getByTestId('integration-save'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      type: 'sharepoint',
      name: 'Zespołowa',
      dataset_id: DATASET_ID,
      tenant_id: 'tenant-test',
      client_id: 'client-9',
      client_secret: 'sekret-9',
      site_url: SITE_URL,
      excluded_library_names: [],
      ignored_extensions: [],
      max_file_size_bytes: 209715200,
      scan_interval_seconds: 300,
      delete_propagation: true,
      is_active: true,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('przy pustych polach pokazuje komunikaty i nic nie wysyła', async () => {
    const bodies: unknown[] = []
    server.use(recordCreates(bodies))
    const user = await renderCreateForm()

    await user.click(screen.getByTestId('integration-save'))

    // name, dataset, tenant, client, secret i site_url — sekret jest wymagany tylko przy tworzeniu.
    // `waitFor`, bo `findAllBy*` wraca już przy pierwszym komunikacie i nie czeka na resztę.
    await waitFor(() => expect(screen.getAllByText('Pole wymagane')).toHaveLength(6))
    expect(bodies).toEqual([])
  })

  it('Enter w polu nie zapisuje integracji', async () => {
    const bodies: unknown[] = []
    server.use(recordCreates(bodies))
    const user = await renderCreateForm()

    const name = screen.getByTestId('integration-field-name')
    setText('integration-field-name', 'Zespołowa')
    await user.type(name, '{Enter}')

    expect(bodies).toEqual([])
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('test połączenia z błędnym tenantem pokazuje wynik failed i szczegół', async () => {
    const user = await renderCreateForm()

    await fillRequiredFields(user, 'bad')
    await user.click(screen.getByTestId('integration-test'))

    const result = await screen.findByTestId('integration-test-result')
    const auth = within(result).getByTestId('integration-test-graph_auth')
    expect(auth).toHaveTextContent('Uwierzytelnienie Graph')
    expect(auth).toHaveTextContent('Błąd')
    expect(within(result).getByText('Invalid tenant')).toBeInTheDocument()
    expect(within(result).getByTestId('integration-test-site_resolution')).toHaveTextContent(
      'Pominięto',
    )
  })

  it('błąd HTTP testu pokazuje Alert z komunikatem błędu', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/integrations/test'), () =>
        HttpResponse.json(
          { error: { code: 'upstream_error', message: 'brak Graph' } },
          { status: 502 },
        ),
      ),
    )
    const user = await renderCreateForm()

    await fillRequiredFields(user)
    await user.click(screen.getByTestId('integration-test'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Błąd usługi zewnętrznej')
    expect(screen.queryByTestId('integration-test-result')).not.toBeInTheDocument()
  })

  it('udany test pokazuje witrynę i biblioteki z licznikami', async () => {
    const user = await renderCreateForm()

    await fillRequiredFields(user)
    await user.click(screen.getByTestId('integration-test'))

    const result = await screen.findByTestId('integration-test-result')
    expect(result).toHaveTextContent('Witryna: Witryna testowa')
    expect(result).toHaveTextContent('Biblioteki: Dokumenty')
    expect(result).toHaveTextContent('widoczne: 1')
    expect(within(result).getByTestId('integration-test-dataset_exists')).toHaveTextContent('OK')
    // Pełny sekret nigdy nie ląduje w DOM-ie — pole trzyma tylko to, co wpisał użytkownik.
    expect(result.textContent).not.toContain('sekret-9')
  })

  it('konflikt datasetu pokazuje komunikat i zostawia dialog otwarty', async () => {
    server.use(
      ...integrationsHandlers({
        integrations: [makeIntegration({ id: 1, dataset_id: DATASET_ID })],
      }),
    )
    const user = await renderCreateForm()

    await fillRequiredFields(user)
    await user.click(screen.getByTestId('integration-save'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Ten dataset ma już integrację')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('blokuje zapis w trakcie mutacji', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/integrations'), async () => {
        await delay(50)
        return HttpResponse.json({ data: makeIntegration({ id: 9 }) }, { status: 201 })
      }),
    )
    const user = await renderCreateForm()

    await fillRequiredFields(user)
    await user.click(screen.getByTestId('integration-save'))

    expect(screen.getByTestId('integration-save')).toBeDisabled()
  })

  it('ma tytuł trybu tworzenia i etykiety pól, fokus na pierwszym polu', async () => {
    await renderCreateForm()

    expect(screen.getByRole('dialog')).toHaveAccessibleName('Nowa integracja')
    expect(screen.getByRole('combobox', { name: /Dataset docelowy/ })).toBeInTheDocument()
    const secret = screen.getByTestId('integration-field-client_secret')
    expect(secret).toHaveAttribute('type', 'password')
    expect(secret).toHaveAttribute('autocomplete', 'new-password')
    await waitFor(() => expect(screen.getByTestId('integration-field-name')).toHaveFocus())
  })

  it('przy 400 z API pokazuje komunikat serwera zamiast ogólnego o walidacji', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/integrations'), () =>
        HttpResponse.json(
          { error: { code: 'validation_failed', message: 'Run test-connection first' } },
          { status: 400 },
        ),
      ),
    )
    const user = await renderCreateForm()

    await fillRequiredFields(user)
    await user.click(screen.getByTestId('integration-save'))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Run test-connection first')
    // Ogólny slug `validation_failed` nie zasłania konkretnego powodu z API.
    expect(alert).not.toHaveTextContent('Dane są niepoprawne')
  })

  it('poniżej `sm` dialog jest pełnoekranowy', async () => {
    stubNarrowViewport()
    await renderCreateForm()

    expect(screen.getByRole('dialog')).toHaveClass('MuiDialog-paperFullScreen')
  })
})
