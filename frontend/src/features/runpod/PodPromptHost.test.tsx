/**
 * Pytanie „Pod jest wyłączony — włączyć?” przy starcie parsowania: preflight → okno → wybór GPU
 * (poprzednie albo zamienniki o ≥ VRAM) → wdrożenie z dokumentami do sparsowania. Sprawdza też,
 * że bez wyłączonego poda parsowanie idzie bez pytania i że zwykły użytkownik nie może włączać GPU.
 */

import { cleanup, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { useParseDocuments } from '../datasets/files/mutations'
import { apiUrl, fixtureUser, makeRunpodState, runpodHandlers } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { PodPromptHost } from './PodPromptHost'
import { closeRunpodPrompt, hasRunpodPromptHost } from './promptStore'

afterEach(() => {
  cleanup()
  closeRunpodPrompt()
})

const superuser = { user: { ...fixtureUser, is_superuser: true } }
const regular = { user: { ...fixtureUser, is_superuser: false } }

const OFF = {
  needs_pod: true,
  model: 'xiaomi-ocr-0-runpod',
  title: 'Xiaomi-OCR-0 (RunPod)',
  state: 'off',
  deployment_id: null,
  last_gpu: { id: 'A40', name: 'A40', vram_gb: 48 },
  min_vram_gb: 16,
}

function parseHandler(calls: string[]) {
  return http.post(apiUrl('/api/v1/datasets/:id/documents/parse'), async ({ request }) => {
    calls.push(JSON.stringify(await request.json()))
    return HttpResponse.json({ code: 0, message: 'success', data: { success_count: 1 } })
  })
}

/** Hook parsowania w drzewie z hostem pytania (host rejestruje się przy montażu). */
async function setup(auth = superuser) {
  let parse: ReturnType<typeof useParseDocuments> | undefined
  function Probe(): ReactNode {
    parse = useParseDocuments('ds-1')
    return null
  }
  const result = await renderWithProviders(
    <>
      <Probe />
      <PodPromptHost />
    </>,
    { route: '/_app', routes: ['/_app'], auth },
  )
  return { ...result, parse: () => parse as NonNullable<typeof parse> }
}

describe('start parsowania a pod RunPod', () => {
  it('pod wyłączony → pytanie zamiast parsowania; „Nie” zamyka okno', async () => {
    const calls: string[] = []
    server.use(...runpodHandlers(makeRunpodState({ preflight: OFF })), parseHandler(calls))
    const user = userEvent.setup()
    const { parse } = await setup()

    await parse().mutateAsync({ ids: ['d1'] })
    const dialog = await screen.findByTestId('runpod-prompt')
    expect(dialog).toHaveTextContent('Pod Xiaomi-OCR-0 (RunPod) jest wyłączony')
    expect(calls).toEqual([]) // parsowanie nie poszło
    await user.click(screen.getByTestId('runpod-prompt-no'))
    await waitFor(() => expect(screen.queryByTestId('runpod-prompt')).not.toBeInTheDocument())
  })

  it('„Tak” → poprzednie GPU jest zaznaczone → wdrożenie niesie dokumenty do sparsowania', async () => {
    const state = makeRunpodState({ preflight: OFF })
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    const { parse } = await setup()

    await parse().mutateAsync({ ids: ['d1', 'd2'] })
    await user.click(await screen.findByTestId('runpod-prompt-yes'))
    expect(await screen.findByText(/Użyję poprzednio wybranego GPU: A40/)).toBeInTheDocument()
    // Zapytanie o GPU było zawężone do VRAM poprzedniego GPU i do dostępnych.
    const query = state.requests.find((r) => r.path.endsWith('/gpus'))?.query ?? ''
    expect(query).toContain('min_vram=48')
    expect(query).toContain('only_available=true')
    await user.click(screen.getByTestId('runpod-prompt-next'))
    await user.click(await screen.findByTestId('runpod-confirm-start'))

    expect(await screen.findByTestId('runpod-progress')).toBeInTheDocument()
    const post = state.requests.find((r) => r.method === 'POST' && r.path.endsWith('/deployments'))
    expect(post?.body).toMatchObject({
      gpu_id: 'A40',
      parse: [{ dataset_id: 'ds-1', document_ids: ['d1', 'd2'] }],
    })
  })

  it('poprzednie GPU niedostępne → ostrzeżenie i inne GPU z tym samym lub większym VRAM', async () => {
    const state = makeRunpodState({
      preflight: { ...OFF, last_gpu: { id: 'L4', name: 'L4', vram_gb: 24 } },
    })
    state.gpus = state.gpus.map((g) => (g.id === 'L4' ? { ...g, availability: 'NONE' } : g))
    server.use(...runpodHandlers(state))
    const user = userEvent.setup()
    const { parse } = await setup()

    await parse().mutateAsync({ ids: ['d1'] })
    await user.click(await screen.findByTestId('runpod-prompt-yes'))
    expect(await screen.findByTestId('runpod-last-gone')).toHaveTextContent('L4, 24 GB')
    const list = screen.getByTestId('runpod-gpu-picker')
    expect(within(list).getByTestId('runpod-gpu-A40')).toBeInTheDocument() // 48 GB ≥ 24 GB
    expect(within(list).queryByTestId('runpod-gpu-3060')).not.toBeInTheDocument() // 12 GB
    expect(screen.getByTestId('runpod-prompt-next')).toBeDisabled() // trzeba wybrać
  })

  it('pod gotowy albo model nie z RunPod → parsowanie idzie od razu, bez pytania', async () => {
    const calls: string[] = []
    server.use(
      ...runpodHandlers(makeRunpodState({ preflight: { needs_pod: false } })),
      parseHandler(calls),
    )
    const { parse } = await setup()

    await parse().mutateAsync({ ids: ['d1'] })
    expect(calls).toEqual([JSON.stringify({ document_ids: ['d1'] })])
    expect(screen.queryByTestId('runpod-prompt')).not.toBeInTheDocument()
  })

  it('błąd preflightu nie blokuje parsowania (straż jest po stronie workera)', async () => {
    const calls: string[] = []
    server.use(
      http.post(apiUrl('/api/wd/v1/runpod/preflight'), () => HttpResponse.error()),
      parseHandler(calls),
    )
    const { parse } = await setup()

    await parse().mutateAsync({ ids: ['d1'] })
    expect(calls).toHaveLength(1)
  })

  it('zwykły użytkownik dostaje prośbę do administratora i nie może włączać GPU', async () => {
    server.use(...runpodHandlers(makeRunpodState({ preflight: OFF })))
    const { parse } = await setup(regular)

    await parse().mutateAsync({ ids: ['d1'] })
    const dialog = await screen.findByTestId('runpod-prompt')
    expect(dialog).toHaveTextContent('Poproś administratora')
    expect(screen.queryByTestId('runpod-prompt-yes')).not.toBeInTheDocument()
  })

  it('bez hosta pytania (np. inne drzewo) parsowanie nie woła preflightu', async () => {
    const calls: string[] = []
    const state = makeRunpodState({ preflight: OFF })
    server.use(...runpodHandlers(state), parseHandler(calls))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    expect(hasRunpodPromptHost()).toBe(false)
    const { result } = renderHook(() => useParseDocuments('ds-1'), { wrapper })

    await result.current.mutateAsync({ ids: ['d1'] })
    expect(calls).toHaveLength(1)
    expect(state.requests.some((r) => r.path.endsWith('/preflight'))).toBe(false)
  })
})
