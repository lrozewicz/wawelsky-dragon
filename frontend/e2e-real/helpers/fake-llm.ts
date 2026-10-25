// Endpointy administracyjne fake-llm `/v1/fake/*` (C6: stats, stats/reset, ocr-delay) dla specu
// realnego. Na stosie clean-install fake-llm NIE ma publikowanego portu — zapytania idą przez
// `docker exec <fake-llm> python -c …` (wzór: healthcheck obrazu i tools/dev/real/kill.sh).
// Gdy ustawione WD_LLM_BASE_URL (stos testowy, bieg skrócony E2E_REAL_QUICK=1) — zwykłe HTTP.
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

import { serviceContainerId } from './worker'

const run = promisify(execFile)

/** Adres fake-llm z hosta (bez końcówki `/v1`); pusty = ścieżka przez `docker exec`. */
const HOST_BASE = (process.env.WD_LLM_BASE_URL ?? '').replace(/\/v1\/?$/, '')

/**
 * Zapytanie HTTP wykonywane W KONTENERZE fake-llm (port 8090 jest tam lokalny). Treść żądania
 * przychodzi jako argv (JSON), kod nie ma interpolacji — bez wstrzykiwania. Metoda GET/POST.
 */
const PY_PROBE = [
  'import json, sys, urllib.request',
  'method, path = sys.argv[1], sys.argv[2]',
  'body = None if len(sys.argv) < 4 else json.dumps(json.loads(sys.argv[3])).encode()',
  'req = urllib.request.Request("http://127.0.0.1:8090" + path, data=body, method=method,',
  '    headers={"Content-Type": "application/json"})',
  'sys.stdout.write(urllib.request.urlopen(req, timeout=15).read().decode())',
].join('\n')

/** Licznik kontenera fake-llm w pamięci — rozwiązanie raz, potem bez ponownego `compose ps`. */
let cachedCid: string | null = null

function dockerProject(): string {
  const project = process.env.WD_CI_PROJECT ?? process.env.COMPOSE_PROJECT_NAME ?? ''
  if (project === '') {
    throw new Error(
      'brak WD_CI_PROJECT/COMPOSE_PROJECT_NAME — nie wiadomo, w którym projekcie jest fake-llm',
    )
  }
  return project
}

async function fakeLlmCid(): Promise<string> {
  if (cachedCid !== null) return cachedCid
  const project = dockerProject()
  const cid = serviceContainerId(project, 'fake-llm')
  if (cid === null) throw new Error(`brak działającego kontenera fake-llm w projekcie ${project}`)
  cachedCid = cid
  return cid
}

/** Surowe wywołanie `/v1/fake/*`; zwraca sparsowany JSON odpowiedzi (fake-llm nie używa koperty). */
export async function fakeRequest<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<T> {
  if (HOST_BASE !== '') {
    const response = await fetch(`${HOST_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!response.ok) throw new Error(`${method} ${path}: HTTP ${response.status}`)
    return (await response.json()) as T
  }
  const cid = await fakeLlmCid()
  const args =
    body === undefined
      ? ['-c', PY_PROBE, method, path]
      : ['-c', PY_PROBE, method, path, JSON.stringify(body)]
  const { stdout } = await run('docker', ['exec', cid, 'python', ...args], { timeout: 30_000 })
  return JSON.parse(stdout) as T
}

/** Kształt `GET /v1/fake/stats` (C6, C7): liczniki żądań, embeddingi, maks. współbieżność
 * per model i liczba wstrzykniętych błędów 5xx per trasa. */
export type FakeStats = {
  chat_completions: Record<string, number>
  embeddings: { requests: number; rejected_429: number }
  max_concurrent: Record<string, number>
  upstream_errors: Record<UpstreamRoute, number>
}

/** Licznik żądań danego modelu (0, gdy model jeszcze nie odpowiadał). */
export function ocrCount(stats: FakeStats, model: string): number {
  return stats.chat_completions[model] ?? 0
}

export function fakeStats(): Promise<FakeStats> {
  return fakeRequest<FakeStats>('GET', '/v1/fake/stats')
}

/** Maks. liczba jednocześnie obsługiwanych żądań modelu od ostatniego resetu (C6); 0 = brak. */
export async function maxConcurrent(model: string): Promise<number> {
  const stats = await fakeStats()
  return stats.max_concurrent[model] ?? 0
}

/** Ustawia opóźnienie `fake-ocr` na żądanie w ms (C6: `POST /v1/fake/ocr-delay`). */
export function setOcrDelay(ms: number): Promise<{ ms: number }> {
  return fakeRequest<{ ms: number }>('POST', '/v1/fake/ocr-delay', { ms })
}

/** Ustawia opóźnienie `POST /v1/embeddings` na żądanie w ms (C6: `POST /v1/fake/embed-delay`). */
export function setEmbedDelay(ms: number): Promise<{ ms: number }> {
  return fakeRequest<{ ms: number }>('POST', '/v1/fake/embed-delay', { ms })
}

/** Trasa wstrzykiwania 5xx (C7): `embeddings` albo `chat` (wizja/OCR). */
export type UpstreamRoute = 'embeddings' | 'chat'

/** Stan wstrzykiwania 5xx jednej trasy (`GET/POST /v1/fake/upstream-error`, C7). */
export type UpstreamErrorRouteState = {
  every: number
  status: number
  times_left: number | null
}

/** Argumenty `POST /v1/fake/upstream-error` (C7): co ile żądań, kod 5xx, opcjonalny limit. */
export type UpstreamErrorInit = {
  route: UpstreamRoute
  every: number
  status: 500 | 502 | 503 | 504
  /** Ile wstrzyknięć wykonać (None = bez limitu); pominięcie = bez limitu. */
  times?: number
}

/** Włącza wstrzykiwanie 5xx dla trasy (C7: `POST /v1/fake/upstream-error`); `every: 0` wyłącza. */
export function setUpstreamError(
  init: UpstreamErrorInit,
): Promise<Record<UpstreamRoute, UpstreamErrorRouteState>> {
  return fakeRequest<Record<UpstreamRoute, UpstreamErrorRouteState>>(
    'POST',
    '/v1/fake/upstream-error',
    { route: init.route, every: init.every, status: init.status, times: init.times ?? null },
  )
}

/** Stan wstrzykiwania 5xx obu tras (C7: `GET /v1/fake/upstream-error`). */
export function getUpstreamError(): Promise<Record<UpstreamRoute, UpstreamErrorRouteState>> {
  return fakeRequest<Record<UpstreamRoute, UpstreamErrorRouteState>>(
    'GET',
    '/v1/fake/upstream-error',
  )
}

/** Włącza wstrzykiwanie 429 dla embeddingów (C6: `POST /v1/fake/embed-429`); `every: 0` wyłącza. */
export function setEmbed429(
  every: number,
  retryAfterS: number | null,
): Promise<{ every: number; retry_after_s: number | null }> {
  return fakeRequest<{ every: number; retry_after_s: number | null }>(
    'POST',
    '/v1/fake/embed-429',
    { every, retry_after_s: retryAfterS },
  )
}

/** Zeruje liczniki żądań (C6: `POST /v1/fake/stats/reset`); opóźnienia nie rusza. */
export function resetFakeStats(): Promise<unknown> {
  return fakeRequest<unknown>('POST', '/v1/fake/stats/reset')
}
