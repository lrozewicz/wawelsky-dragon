/**
 * Dialog importu z bramki (brief E3-6c1 T6 pkt 4): odczyt `?supported=true`, wielokrotny wybór
 * z „Zaznacz wszystko”, wybór typu, kolejne `POST …/models` z pominięciem istniejących nazw,
 * podsumowanie i `Alert` przy błędzie pobrania listy.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, makeSeedInstance, settingsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ImportModelsDialog } from './ImportModelsDialog'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

const MODELS_URL = apiUrl('/api/v1/providers/litellm/instances/inst-1/models')

/** Bramka zwraca trzy modele; `old` jest już w instancji (istniejące nazwy z propsa). */
const SEED = {
  instances: [makeSeedInstance({ id: 'inst-1', name: 'litellm-test' })],
  supported: {
    'inst-1': [
      { name: 'a', rank: 1 },
      { name: 'b', rank: 2 },
      { name: 'old', rank: 3 },
    ],
  },
}

/** Przechwytuje ciała `POST …/models` i zwraca sukces. */
function capturePost(bodies: unknown[]) {
  return http.post(MODELS_URL, async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ code: 0, message: 'success' })
  })
}

async function renderDialog(onClose = vi.fn()) {
  const result = await renderWithProviders(
    <ImportModelsDialog instanceId="inst-1" existingNames={['old']} open onClose={onClose} />,
  )
  return { ...result, onClose }
}

/** Zaznacza checkbox modelu po nazwie. */
async function check(name: string): Promise<void> {
  await userEvent.setup().click(await screen.findByRole('checkbox', { name }))
}

describe('ImportModelsDialog', () => {
  it('otwarcie pobiera listę bramki z `supported=true` i pokazuje checkboxy', async () => {
    const calls: string[] = []
    server.use(...settingsHandlers(SEED))
    server.events.on('request:start', ({ request }) => calls.push(request.url))
    await renderDialog()

    expect(await screen.findByRole('checkbox', { name: 'a' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'b' })).toBeInTheDocument()
    // `old` jest już w instancji — checkbox nieklikalny.
    expect(screen.getByRole('checkbox', { name: 'old' })).toBeDisabled()
    expect(calls.some((url) => url.includes('/models?supported=true'))).toBe(true)
  })

  it('importuje zaznaczone modele jako kolejne POST-y z domyślnym typem chat', async () => {
    const bodies: unknown[] = []
    server.use(...settingsHandlers(SEED))
    server.use(capturePost(bodies))
    await renderDialog()

    await check('a')
    await check('b')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Importuj' }))

    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies).toEqual([
      { model_name: 'a', model_type: 'chat', max_tokens: 8192 },
      { model_name: 'b', model_type: 'chat', max_tokens: 8192 },
    ])
    expect(await screen.findByText('Dodano modeli: 2')).toBeInTheDocument()
  })

  it('„Zaznacz wszystko” pomija nazwy już obecne w instancji', async () => {
    const bodies: unknown[] = []
    server.use(...settingsHandlers(SEED))
    server.use(capturePost(bodies))
    const user = userEvent.setup()
    await renderDialog()

    await user.click(await screen.findByRole('checkbox', { name: 'Zaznacz wszystko' }))
    await user.click(screen.getByRole('button', { name: 'Importuj' }))

    await waitFor(() => expect(bodies).toHaveLength(2))
    expect((bodies as { model_name: string }[]).map((body) => body.model_name)).toEqual(['a', 'b'])
  })

  it('pokazuje błędy importu w `Alert` obok podsumowania', async () => {
    server.use(...settingsHandlers(SEED))
    server.use(
      http.post(MODELS_URL, async ({ request }) => {
        const body = (await request.json()) as { model_name: string }
        return body.model_name === 'b'
          ? HttpResponse.json({ code: 102, message: "Model 'b' already exists" })
          : HttpResponse.json({ code: 0, message: 'success' })
      }),
    )
    await renderDialog()

    await check('a')
    await check('b')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Importuj' }))

    expect(await screen.findByText('Dodano modeli: 1')).toBeInTheDocument()
    expect(screen.getByText("Model 'b' already exists")).toBeInTheDocument()
  })

  it('pokazuje `Alert` z komunikatem API, gdy pobranie listy się nie powiedzie', async () => {
    server.use(...settingsHandlers(SEED))
    server.use(
      http.get(MODELS_URL, () =>
        HttpResponse.json({ code: 102, message: 'Connection failed: HTTP 401' }),
      ),
    )
    await renderDialog()

    expect(
      await screen.findByText('Nie udało się wykonać operacji: Connection failed: HTTP 401'),
    ).toBeInTheDocument()
  })
})
