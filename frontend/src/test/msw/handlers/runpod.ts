/**
 * Atrapa tras RunPod (`/api/wd/v1/runpod/*`) dla testów: stan w obiekcie przekazanym testowi.
 * Testy podmieniają handlery przez `server.use(...runpodHandlers(state))`; domyślny zestaw nie
 * zawiera tych tras, bo parsowanie bez hosta pytania w ogóle nie woła preflightu.
 */

import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { apiUrl } from './common'

export type FakeGpu = {
  id: string
  name: string
  vram_gb: number
  price_per_hr: number
  availability: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
}

export type FakeDeployment = {
  id: string
  model: string
  title: string
  status: string
  active: boolean
  gpu: { id: string; name: string; vram_gb: number }
  cloud: string
  data_center_id: string | null
  price_per_hr: number
  cost_so_far: number
  error: string | null
  pending_documents: number
  created_at: number
  ready_at: number | null
  ended_at: number | null
  origin: 'panel' | 'parse'
  idle_shutdown_s: number | null
}

export type RunpodState = {
  keyConfigured: boolean
  gpus: FakeGpu[]
  deployments: FakeDeployment[]
  preflight: Record<string, unknown>
  /** Odpowiedź 409 `gpu_unavailable` dla tych GPU (id) przy POST /deployments. */
  unavailable: string[]
  requests: { method: string; path: string; query: string; body: unknown }[]
}

export const MODEL = {
  name: 'xiaomi-ocr-0-runpod',
  title: 'Xiaomi-OCR-0 (RunPod)',
  hf_model: 'SeerRay-Lab/Xiaomi-OCR-0',
  min_vram_gb: 16,
  recommended_vram_gb: 24,
}

export function makeRunpodState(overrides: Partial<RunpodState> = {}): RunpodState {
  return {
    keyConfigured: true,
    gpus: [
      { id: 'L4', name: 'L4', vram_gb: 24, price_per_hr: 0.39, availability: 'LOW' },
      { id: 'A40', name: 'A40', vram_gb: 48, price_per_hr: 0.59, availability: 'MEDIUM' },
      { id: 'A4000', name: 'RTX A4000', vram_gb: 16, price_per_hr: 0.25, availability: 'NONE' },
      { id: '3060', name: 'RTX 3060', vram_gb: 12, price_per_hr: 0.2, availability: 'HIGH' },
    ],
    deployments: [],
    preflight: { needs_pod: false },
    unavailable: [],
    requests: [],
    ...overrides,
  }
}

export function makeDeployment(overrides: Partial<FakeDeployment> = {}): FakeDeployment {
  return {
    id: 'dep-1',
    model: MODEL.name,
    title: MODEL.title,
    status: 'provisioning',
    active: true,
    gpu: { id: 'A40', name: 'A40', vram_gb: 48 },
    cloud: 'SECURE',
    data_center_id: null,
    price_per_hr: 0.59,
    cost_so_far: 0,
    error: null,
    pending_documents: 0,
    created_at: 0,
    ready_at: null,
    ended_at: null,
    origin: 'parse',
    idle_shutdown_s: 300,
    ...overrides,
  }
}

function envelope<T>(data: T, status = 200): Response {
  return HttpResponse.json({ data }, { status })
}

function toView(gpu: FakeGpu, minVram: number) {
  return { ...gpu, data_centers: [], fits: gpu.vram_gb >= minVram }
}

export function runpodHandlers(state: RunpodState): HttpHandler[] {
  const record = async (request: Request): Promise<void> => {
    const url = new URL(request.url)
    let body: unknown = null
    if (request.method !== 'GET' && request.method !== 'DELETE') {
      body = await request
        .clone()
        .json()
        .catch(() => null)
    }
    state.requests.push({ method: request.method, path: url.pathname, query: url.search, body })
  }
  return [
    http.get(apiUrl('/api/wd/v1/runpod/key'), async ({ request }) => {
      await record(request)
      return envelope({
        configured: state.keyConfigured,
        hint: state.keyConfigured ? '…abcd' : null,
      })
    }),
    http.put(apiUrl('/api/wd/v1/runpod/key'), async ({ request }) => {
      await record(request)
      state.keyConfigured = true
      return envelope({ configured: true, hint: '…abcd' })
    }),
    http.delete(apiUrl('/api/wd/v1/runpod/key'), async ({ request }) => {
      await record(request)
      state.keyConfigured = false
      return new HttpResponse(null, { status: 204 })
    }),
    http.get(apiUrl('/api/wd/v1/runpod/models'), () => envelope({ items: [MODEL] })),
    http.get(apiUrl('/api/wd/v1/runpod/gpus'), async ({ request }) => {
      await record(request)
      const q = new URL(request.url).searchParams
      const min = Number(q.get('min_vram') ?? 0)
      const max = Number(q.get('max_vram') ?? 1e9)
      const onlyAvailable = q.get('only_available') === 'true'
      const gpus = state.gpus
        .filter((g) => g.vram_gb >= min && g.vram_gb <= max)
        .filter((g) => !onlyAvailable || g.availability !== 'NONE')
        .sort((a, b) => a.price_per_hr - b.price_per_hr)
        .map((g) => toView(g, MODEL.min_vram_gb))
      return envelope({
        model: MODEL.name,
        min_vram_gb: MODEL.min_vram_gb,
        gpus,
        regions: ['EUROPE', 'NORTH_AMERICA'],
        countries: ['CZ', 'RO', 'US'],
      })
    }),
    http.post(apiUrl('/api/wd/v1/runpod/preflight'), async ({ request }) => {
      await record(request)
      return envelope(state.preflight)
    }),
    http.get(apiUrl('/api/wd/v1/runpod/deployments'), () => envelope({ items: state.deployments })),
    http.get(apiUrl('/api/wd/v1/runpod/deployments/:id'), ({ params }) => {
      const found = state.deployments.find((d) => d.id === params.id)
      return found
        ? envelope(found)
        : HttpResponse.json({ error: { code: 'not_found', message: 'nope' } }, { status: 404 })
    }),
    http.post(apiUrl('/api/wd/v1/runpod/deployments'), async ({ request }) => {
      await record(request)
      const body = (await request.clone().json()) as { gpu_id: string }
      if (state.unavailable.includes(body.gpu_id)) {
        const chosen = state.gpus.find((g) => g.id === body.gpu_id)
        const alternatives = state.gpus
          .filter((g) => g.availability !== 'NONE' && g.id !== body.gpu_id)
          .filter((g) => g.vram_gb >= (chosen?.vram_gb ?? 0) && !state.unavailable.includes(g.id))
          .map((g) => toView(g, MODEL.min_vram_gb))
        return HttpResponse.json(
          { error: { code: 'gpu_unavailable', message: 'gone', details: { alternatives } } },
          { status: 409 },
        )
      }
      const gpu = state.gpus.find((g) => g.id === body.gpu_id)
      const created = makeDeployment({
        id: `dep-${state.deployments.length + 1}`,
        gpu: { id: gpu?.id ?? body.gpu_id, name: gpu?.name ?? '?', vram_gb: gpu?.vram_gb ?? 0 },
        price_per_hr: gpu?.price_per_hr ?? 0,
      })
      state.deployments.unshift(created)
      return envelope(created, 201)
    }),
    http.post(apiUrl('/api/wd/v1/runpod/deployments/:id/parse'), async ({ request, params }) => {
      await record(request)
      const found = state.deployments.find((d) => d.id === params.id)
      return found
        ? envelope(found)
        : HttpResponse.json({ error: { code: 'not_found', message: 'x' } }, { status: 404 })
    }),
    http.delete(apiUrl('/api/wd/v1/runpod/deployments'), async ({ request }) => {
      await record(request)
      const before = state.deployments.length
      state.deployments = state.deployments.filter((d) => d.active)
      return envelope({ deleted: before - state.deployments.length })
    }),
    http.delete(apiUrl('/api/wd/v1/runpod/deployments/:id'), async ({ request, params }) => {
      await record(request)
      const found = state.deployments.find((d) => d.id === params.id)
      if (found) Object.assign(found, { status: 'terminated', active: false })
      return found
        ? envelope(found)
        : HttpResponse.json({ error: { code: 'not_found', message: 'x' } }, { status: 404 })
    }),
  ]
}
