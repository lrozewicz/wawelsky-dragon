/**
 * Strona RunPod w Ustawieniach: klucz API, filtry GPU (VRAM/region/kraj), wdrożenie z
 * potwierdzeniem ceny, zamienniki przy niedostępnym GPU, lista wdrożeń i ręczne wyłączenie.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import {
  fixtureUser,
  makeDeployment,
  makeRunpodState,
  runpodHandlers,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { RunpodPage } from './RunpodPage'

afterEach(cleanup)

const superuser = { user: { ...fixtureUser, is_superuser: true } }
const regular = { user: { ...fixtureUser, is_superuser: false } }

async function renderPage(auth = superuser) {
  return renderWithProviders(<RunpodPage />, { route: '/_app', routes: ['/_app'], auth })
}

describe('RunpodPage', () => {
  it('bez klucza pokazuje ostrzeżenie i formularz, a po zapisie klucza kartę z modelem', async () => {
    const state = makeRunpodState({ keyConfigured: false })
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    await renderPage()

    expect(await screen.findByText(/Brak klucza/)).toBeInTheDocument()
    expect(screen.queryByTestId('runpod-model-card')).not.toBeInTheDocument()
    await user.type(screen.getByTestId('runpod-key-input'), 'rpa_secret')
    await user.click(screen.getByTestId('runpod-key-save'))

    expect(await screen.findByTestId('runpod-key-ok')).toHaveTextContent('…abcd')
    expect(await screen.findByTestId('runpod-model-card')).toBeInTheDocument()
    const put = state.requests.find((r) => r.method === 'PUT')
    expect(put?.body).toEqual({ api_key: 'rpa_secret' })
  })

  it('zwykły użytkownik widzi stan, ale nie może zmieniać klucza ani uruchamiać GPU', async () => {
    server.use(...runpodHandlers(makeRunpodState()))
    await renderPage(regular)

    expect(await screen.findByTestId('runpod-key-ok')).toBeInTheDocument()
    expect(screen.queryByTestId('runpod-key-input')).not.toBeInTheDocument()
    expect(screen.queryByTestId('runpod-model-card')).not.toBeInTheDocument()
  })

  it('lista GPU jest od najtańszych, a filtr VRAM i „tylko dostępne” zawęża zapytanie', async () => {
    const state = makeRunpodState()
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    await renderPage()

    expect(await screen.findByTestId('runpod-gpu-L4')).toBeInTheDocument()
    // Domyślnie min. VRAM = wymaganie modelu (16 GB): RTX 3060 (12 GB) nie ma na liście.
    expect(screen.queryByTestId('runpod-gpu-3060')).not.toBeInTheDocument()
    // Niedostępne GPU widać, ale nie da się go wybrać.
    expect(within(screen.getByTestId('runpod-gpu-A4000')).getByRole('radio')).toBeDisabled()

    await user.click(screen.getByTestId('runpod-filter-available'))
    await waitFor(() => expect(screen.queryByTestId('runpod-gpu-A4000')).not.toBeInTheDocument())
    await user.clear(screen.getByTestId('runpod-filter-min-vram'))
    await user.type(screen.getByTestId('runpod-filter-min-vram'), '40')
    await waitFor(() => expect(screen.queryByTestId('runpod-gpu-L4')).not.toBeInTheDocument())
    expect(screen.getByTestId('runpod-gpu-A40')).toBeInTheDocument()
    const last = state.requests.filter((r) => r.path.endsWith('/gpus')).at(-1)
    expect(last?.query).toContain('min_vram=40')
    expect(last?.query).toContain('only_available=true')
  })

  it('wybór GPU → potwierdzenie z ceną → wdrożenie i postęp', async () => {
    const state = makeRunpodState()
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    await renderPage()

    await user.click(within(await screen.findByTestId('runpod-gpu-A40')).getByRole('radio'))
    await user.click(screen.getByTestId('runpod-deploy'))
    const confirm = await screen.findByTestId('runpod-confirm')
    expect(confirm).toHaveTextContent('A40')
    expect(confirm).toHaveTextContent('0.59 USD/h')
    await user.click(screen.getByTestId('runpod-confirm-start'))

    expect(await screen.findByTestId('runpod-progress')).toHaveTextContent(
      'Xiaomi-OCR-0 (RunPod) na A40',
    )
    expect(screen.getByTestId('runpod-progress-status')).toHaveTextContent('Przydzielanie GPU')
    const post = state.requests.find((r) => r.method === 'POST')
    expect(post?.body).toMatchObject({ gpu_id: 'A40', cloud: 'SECURE', parse: [] })
  })

  it('niedostępne GPU → propozycje z tym samym lub większym VRAM i start na wybranym', async () => {
    const state = makeRunpodState({ unavailable: ['L4'] })
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    await renderPage()

    await user.click(within(await screen.findByTestId('runpod-gpu-L4')).getByRole('radio'))
    await user.click(screen.getByTestId('runpod-deploy'))
    await user.click(await screen.findByTestId('runpod-confirm-start'))

    const alternatives = await screen.findByTestId('runpod-alternatives')
    expect(alternatives).toHaveTextContent('L4 nie jest teraz dostępne')
    // Zamiennik ma ≥ 24 GB: A40 (48 GB); RTX 3060 (12 GB) i niedostępny A4000 odpadają.
    expect(within(alternatives).getByTestId('runpod-alt-A40')).toBeInTheDocument()
    expect(within(alternatives).queryByTestId('runpod-alt-3060')).not.toBeInTheDocument()
    await user.click(within(alternatives).getByRole('button', { name: 'Uruchom na wybranym' }))

    expect(await screen.findByTestId('runpod-progress')).toHaveTextContent('na A40')
    const posts = state.requests.filter((r) => r.method === 'POST')
    expect(posts.map((p) => (p.body as { gpu_id: string }).gpu_id)).toEqual(['L4', 'A40'])
  })

  it('lista wdrożeń pokazuje stan i pozwala wyłączyć działającego poda', async () => {
    const state = makeRunpodState({
      deployments: [
        makeDeployment({ id: 'dep-run', status: 'ready', cost_so_far: 0.12 }),
        makeDeployment({ id: 'dep-old', status: 'terminated', active: false, cost_so_far: 0.4 }),
      ],
    })
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    await renderPage()

    const running = await screen.findByTestId('runpod-deployment-dep-run')
    expect(running).toHaveTextContent('Gotowe')
    expect(running).toHaveTextContent('$0.12')
    expect(screen.queryByTestId('runpod-terminate-dep-old')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('runpod-terminate-dep-run'))
    await waitFor(() =>
      expect(state.requests.some((r) => r.method === 'DELETE' && r.path.endsWith('/dep-run'))).toBe(
        true,
      ),
    )
  })

  it('wiersz ma datę i opis wygasania, a „Wyczyść historię” usuwa tylko zakończone', async () => {
    const state = makeRunpodState({
      deployments: [
        makeDeployment({
          id: 'dep-panel',
          status: 'ready',
          origin: 'panel',
          idle_shutdown_s: null,
          created_at: Date.UTC(2026, 9, 27, 10, 5),
        }),
        makeDeployment({ id: 'dep-parse', status: 'ready', origin: 'parse' }),
        makeDeployment({ id: 'dep-old', status: 'terminated', active: false }),
        makeDeployment({ id: 'dep-bad', status: 'failed', active: false }),
      ],
    })
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    await renderPage()

    expect(await screen.findByTestId('runpod-date-dep-panel')).toHaveTextContent('2026')
    expect(screen.getByTestId('runpod-lifetime-dep-panel')).toHaveTextContent(
      'do ręcznego wyłączenia',
    )
    expect(screen.getByTestId('runpod-lifetime-dep-parse')).toHaveTextContent('po 5 min')
    expect(screen.queryByTestId('runpod-lifetime-dep-old')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('runpod-clear-history'))
    await waitFor(() => expect(screen.queryByTestId('runpod-deployment-dep-old')).toBeNull())
    expect(screen.queryByTestId('runpod-deployment-dep-bad')).toBeNull()
    expect(screen.getByTestId('runpod-deployment-dep-panel')).toBeInTheDocument()
    expect(screen.getByTestId('runpod-deployment-dep-parse')).toBeInTheDocument()
    expect(screen.getByTestId('runpod-clear-history')).toBeDisabled()
  })

  it('zwykły użytkownik nie widzi przycisku czyszczenia historii', async () => {
    server.use(...runpodHandlers(makeRunpodState()))
    await renderPage(regular)
    await screen.findByTestId('runpod-key-ok')
    expect(screen.queryByTestId('runpod-clear-history')).not.toBeInTheDocument()
  })
})
