/**
 * Tab „Ten serwer”: stan agenta, karty wolne i zajęte, wdrożenie na wybranej karcie, rozdział
 * wdrożeń między dostawców.
 */

import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { fixtureUser, makeDeployment } from '../../test/msw/handlers'
import { apiUrl } from '../../test/msw/handlers/common'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { LocalGpuPage } from './LocalGpuPage'

afterEach(cleanup)

const superuser = { user: { ...fixtureUser, is_superuser: true } }
const regular = { user: { ...fixtureUser, is_superuser: false } }
const LOCAL_MODEL = {
  name: 'xiaomi-ocr-0-localhost',
  title: 'Xiaomi-OCR-0',
  hf_model: 'SeerRay-Lab/Xiaomi-OCR-0',
  min_vram_gb: 8,
  recommended_vram_gb: 8,
}

function gpu(index: number, free: boolean) {
  return {
    id: `GPU-${index}`,
    index,
    name: `RTX ${index}`,
    vram_gb: 16,
    memory_total_mb: 16376,
    memory_free_mb: free ? 14336 : 2048,
    memory_used_mb: free ? 2040 : 14328,
    utilization_pct: free ? 1 : 97,
    free,
  }
}

function localHandlers(list: Record<string, unknown>, deployments: unknown[] = []) {
  const posts: unknown[] = []
  const envelope = (data: unknown, status = 200) => HttpResponse.json({ data }, { status })
  return {
    posts,
    handlers: [
      http.get(apiUrl('/api/wd/v1/gpu/local/models'), () => envelope({ items: [LOCAL_MODEL] })),
      http.get(apiUrl('/api/wd/v1/gpu/local/gpus'), () =>
        envelope({ model: LOCAL_MODEL.name, min_vram_gb: 8, gpus: [], ...list }),
      ),
      http.post(apiUrl('/api/wd/v1/gpu/local/deployments'), async ({ request }) => {
        posts.push(await request.json())
        return envelope(
          makeDeployment({ id: 'dep-local', cloud: 'LOCAL', status: 'starting', active: true }),
          201,
        )
      }),
      http.get(apiUrl('/api/wd/v1/runpod/deployments'), () => envelope({ items: deployments })),
    ],
  }
}

async function renderPage(auth = superuser) {
  return renderWithProviders(<LocalGpuPage />, { route: '/_app', routes: ['/_app'], auth })
}

describe('LocalGpuPage', () => {
  it('bez agenta wyjaśnia, co włączyć, i nie pozwala uruchomić', async () => {
    server.use(...localHandlers({ agent: 'not_configured' }).handlers)
    await renderPage()

    expect(await screen.findByTestId('local-gpu-not-configured')).toBeInTheDocument()
    expect(screen.getByTestId('local-deploy')).toBeDisabled()
  })

  it('zgłasza niedziałającego agenta', async () => {
    server.use(...localHandlers({ agent: 'unreachable' }).handlers)
    await renderPage()

    expect(await screen.findByTestId('local-gpu-unreachable')).toBeInTheDocument()
  })

  it('pokazuje karty wolne i zajęte; zajętej nie da się wybrać, wolną da się uruchomić', async () => {
    const { handlers, posts } = localHandlers({ agent: 'ok', gpus: [gpu(0, true), gpu(1, false)] })
    server.use(...handlers)
    await renderPage()
    const user = userEvent.setup()

    const freeRow = await screen.findByTestId('local-gpu-0')
    const busyRow = screen.getByTestId('local-gpu-1')
    expect(screen.getByTestId('local-gpu-state-0')).toHaveTextContent('wolna')
    expect(screen.getByTestId('local-gpu-state-1')).toHaveTextContent('zajęta')
    expect(within(busyRow).getByRole('radio')).toBeDisabled()
    expect(within(freeRow).getByText('14.0 GB')).toBeInTheDocument()
    expect(screen.getByTestId('local-deploy')).toBeDisabled()

    await user.click(within(freeRow).getByRole('radio'))
    await user.click(screen.getByTestId('local-deploy'))

    expect(await screen.findByTestId('local-deploy-progress')).toBeInTheDocument()
    expect(posts).toEqual([{ model: LOCAL_MODEL.name, gpu_id: 'GPU-0', parse: [] }])
  })

  it('zwykły użytkownik nie widzi kart ani przycisku', async () => {
    server.use(...localHandlers({ agent: 'ok', gpus: [gpu(0, true)] }).handlers)
    await renderPage(regular)

    expect(await screen.findByTestId('local-gpu-page')).toBeInTheDocument()
    expect(screen.queryByTestId('local-model-card')).not.toBeInTheDocument()
  })

  it('w sekcji Wdrożenia pokazuje tylko wdrożenia tego serwera, bez kosztu', async () => {
    const local = makeDeployment({ id: 'dep-local', cloud: 'LOCAL', status: 'ready', active: true })
    const cloud = makeDeployment({ id: 'dep-cloud', cloud: 'SECURE' })
    server.use(...localHandlers({ agent: 'ok', gpus: [] }, [local, cloud]).handlers)
    await renderPage()

    expect(await screen.findByTestId('runpod-deployment-dep-local')).toBeInTheDocument()
    expect(screen.queryByTestId('runpod-deployment-dep-cloud')).not.toBeInTheDocument()
    expect(screen.queryByText('Koszt')).not.toBeInTheDocument()
  })
})
