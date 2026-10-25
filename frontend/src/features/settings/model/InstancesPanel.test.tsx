/**
 * Panel instancji dostawcy (brief E3-6c1 T5b pkt 1, 4, 6, 7): nagłówek, lista z wyborem, akcje
 * tylko dla superusera, instancja `default` bez akcji oraz usuwanie z potwierdzeniem i `Alert`
 * przy błędzie 102 (instancja zostaje na liście).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  defaultInstances,
  fixtureUser,
  makeSeedInstance,
  settingsHandlers,
  toProviderInstance,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { RenderWithProvidersOptions } from '../../../test/renderWithProviders'

import { InstancesPanel } from './InstancesPanel'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

/** Seed: instancja `default` (środowiskowa) plus zwykła instancja `litellm-test`. */
const CUSTOM = makeSeedInstance({ id: 'inst-1', name: 'litellm-test' })
const SEED = { instances: [...defaultInstances(), CUSTOM] }

const superuser = { user: { ...fixtureUser, is_superuser: true } }

/** Render w kontekście trasy `/_app` — stąd `useIsSuperuser` czyta flagę. */
async function renderPanel(
  selectedId: string | null = null,
  auth: RenderWithProvidersOptions['auth'] = superuser,
  onSelect = vi.fn(),
) {
  const result = await renderWithProviders(
    <InstancesPanel selectedId={selectedId} onSelect={onSelect} />,
    { route: '/_app', routes: ['/_app'], auth },
  )
  return { ...result, onSelect }
}

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    calls.push(`${request.method} ${new URL(request.url).pathname}`)
  })
  return calls
}

describe('InstancesPanel', () => {
  it('pokazuje nagłówek dostawcy i listę z chipem instancji środowiskowej', async () => {
    server.use(...settingsHandlers(SEED))
    await renderPanel()

    expect(await screen.findByText('Dostawca: OpenAI-compatible / LiteLLM')).toBeInTheDocument()
    expect(screen.getByText('default')).toBeInTheDocument()
    expect(screen.getByText('Środowiskowa')).toBeInTheDocument()
    expect(screen.getByText('litellm-test')).toBeInTheDocument()
  })

  it('zaznacza wybraną instancję i woła `onSelect` po kliknięciu', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers(SEED))
    const { onSelect } = await renderPanel('inst-1')
    await screen.findByText('litellm-test')

    const item = screen.getByTestId('instance-item-inst-1')
    expect(item).toHaveAttribute('aria-current', 'true')
    expect(screen.getByTestId('instance-item-inst-default')).not.toHaveAttribute('aria-current')

    await user.click(screen.getByText('default'))
    expect(onSelect).toHaveBeenCalledWith('inst-default')
  })

  it('superuser widzi Dodaj, a akcje ma tylko instancja niedomyślna', async () => {
    server.use(...settingsHandlers(SEED))
    await renderPanel()

    expect(await screen.findByRole('button', { name: 'Dodaj instancję' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Edytuj instancję litellm-test' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Usuń instancję litellm-test' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Edytuj instancję default' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Usuń instancję default' })).not.toBeInTheDocument()
  })

  it('nie-superuser nie widzi żadnych akcji zapisu', async () => {
    server.use(...settingsHandlers(SEED))
    await renderPanel(null, {})

    expect(await screen.findByText('litellm-test')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dodaj instancję' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Edytuj instancję litellm-test' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Usuń instancję litellm-test' }),
    ).not.toBeInTheDocument()
  })

  it('usuwa instancję po potwierdzeniu', async () => {
    const user = userEvent.setup()
    const calls = recordRequests()
    server.use(...settingsHandlers(SEED))
    await renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Usuń instancję litellm-test' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Usunąć instancję?')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(screen.queryByText('litellm-test')).not.toBeInTheDocument())
    expect(calls).toContain('DELETE /api/v1/providers/litellm/instances')
  })

  it('pokazuje Alert błędu 102, a instancja zostaje na liście', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers(SEED))
    server.use(
      http.delete(apiUrl('/api/v1/providers/litellm/instances'), () =>
        HttpResponse.json({ code: 102, message: "Instance 'litellm-test' is in use" }),
      ),
    )
    await renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Usuń instancję litellm-test' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    expect(
      await screen.findByText("Nie udało się wykonać operacji: Instance 'litellm-test' is in use"),
    ).toBeInTheDocument()
    expect(screen.getByText('litellm-test')).toBeInTheDocument()
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(...settingsHandlers(SEED))
    server.use(
      http.get(apiUrl('/api/v1/providers/litellm/instances'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 102, message: 'instances unavailable' })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: [toProviderInstance(CUSTOM)],
        })
      }),
    )
    const user = userEvent.setup()
    await renderPanel()

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wykonać operacji: instances unavailable',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('litellm-test')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('dodaje instancję z dialogu i pokazuje ją na liście', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers(SEED))
    await renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Dodaj instancję' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: /Nazwa/ }), 'nowa')
    await user.type(within(dialog).getByLabelText(/Base URL/), 'http://nowa.test/v1')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('nowa')).toBeInTheDocument()
  })
})
