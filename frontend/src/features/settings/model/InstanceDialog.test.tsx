/**
 * Dialog instancji (brief E3-6c1 T5b pkt 2, 3, 5): walidacja pól, zapis (POST/PUT), weryfikacja
 * połączenia i brak klucza w ciele PUT, gdy pole puste (test kontraktowy — maska nie jedzie).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, makeSeedInstance, settingsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { InstanceDialog } from './InstanceDialog'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

/** Instancja z seedu: klucz ustawiony, więc odczyt zwraca maskę `********` (K13 §0 p. 5). */
const SEEDED = makeSeedInstance({
  id: 'inst-1',
  name: 'litellm-test',
  base_url: 'http://gateway.test/v1',
  api_key: 'sekret',
})

const instance = {
  id: 'inst-1',
  instance_name: 'litellm-test',
  provider_id: 'litellm',
  region: 'default',
  status: 'active',
}

/** Rejestruje ciało żądania POST/PUT pod wskazaną ścieżką i zwraca sukces. */
function captureBody(path: string, method: 'post' | 'put'): { read: () => unknown } {
  let body: unknown
  server.use(
    http[method](apiUrl(path), async ({ request }) => {
      body = await request.json()
      return HttpResponse.json({ code: 0, message: 'success' })
    }),
  )
  return { read: () => body }
}

describe('InstanceDialog', () => {
  it('waliduje format base URL i blokuje zapis', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(...settingsHandlers({ instances: [SEEDED] }))
    const post = captureBody('/api/v1/providers/litellm/instances', 'post')

    await renderWithProviders(<InstanceDialog onClose={onClose} />)
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Nowa instancja')).toBeInTheDocument()

    await user.type(within(dialog).getByRole('textbox', { name: /Nazwa/ }), 'nowa')
    await user.type(within(dialog).getByLabelText(/Base URL/), 'ftp://nowa.test')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    expect(
      await within(dialog).findByText('Adres musi zaczynać się od http:// lub https://'),
    ).toBeInTheDocument()
    expect(post.read()).toBeUndefined()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('tworzy instancję ciałem POST z kluczem i zamyka dialog', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(...settingsHandlers({ instances: [SEEDED] }))
    const post = captureBody('/api/v1/providers/litellm/instances', 'post')

    await renderWithProviders(<InstanceDialog onClose={onClose} />)
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: /Nazwa/ }), 'nowa')
    await user.type(within(dialog).getByLabelText(/Base URL/), 'http://nowa.test/v1/')
    await user.type(within(dialog).getByLabelText('Klucz API'), 'tajny')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    await waitFor(() =>
      expect(post.read()).toEqual({
        instance_name: 'nowa',
        base_url: 'http://nowa.test/v1',
        api_key: 'tajny',
      }),
    )
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('przy edycji z pustym kluczem nie wysyła `api_key` w ciele PUT', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(...settingsHandlers({ instances: [SEEDED] }))
    const put = captureBody('/api/v1/providers/litellm/instances/inst-1', 'put')

    await renderWithProviders(<InstanceDialog instance={instance} onClose={onClose} />)
    const name = await screen.findByRole('textbox', { name: /Nazwa/ })
    // Maska z odczytu: pole klucza zostaje puste z podpowiedzią „Bez zmian”.
    expect(screen.getByLabelText('Klucz API')).toHaveAttribute('placeholder', 'Bez zmian')

    await user.clear(name)
    await user.type(name, 'x')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    const body = put.read() as Record<string, unknown>
    expect(body).toEqual({ instance_name: 'x', base_url: 'http://gateway.test/v1' })
    expect('api_key' in body).toBe(false)
  })

  it('przy edycji wpisany klucz trafia do ciała PUT', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(...settingsHandlers({ instances: [SEEDED] }))
    const put = captureBody('/api/v1/providers/litellm/instances/inst-1', 'put')

    await renderWithProviders(<InstanceDialog instance={instance} onClose={onClose} />)
    await screen.findByRole('textbox', { name: /Nazwa/ })
    await user.type(screen.getByLabelText('Klucz API'), 'nowy')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() =>
      expect(put.read()).toEqual({
        instance_name: 'litellm-test',
        base_url: 'http://gateway.test/v1',
        api_key: 'nowy',
      }),
    )
  })

  it('pokazuje sukces weryfikacji połączenia', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ instances: [SEEDED] }))

    await renderWithProviders(<InstanceDialog instance={instance} onClose={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Weryfikuj' }))

    expect(await screen.findByText('Połączenie działa')).toBeInTheDocument()
  })

  it('pokazuje komunikat błędu z API, gdy weryfikacja się nie powiedzie', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ instances: [SEEDED], connection: 'fail' }))

    await renderWithProviders(<InstanceDialog instance={instance} onClose={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Weryfikuj' }))

    expect(
      await screen.findByText('Nie udało się wykonać operacji: Connection failed: HTTP 401'),
    ).toBeInTheDocument()
  })

  it('przy edycji z pustym kluczem weryfikuje przez `instance_id`', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ instances: [SEEDED] }))
    const connection = captureBody('/api/v1/providers/litellm/connection', 'post')

    await renderWithProviders(<InstanceDialog instance={instance} onClose={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Weryfikuj' }))

    await waitFor(() =>
      expect(connection.read()).toEqual({
        base_url: 'http://gateway.test/v1',
        api_key: null,
        instance_id: 'inst-1',
      }),
    )
  })
})
