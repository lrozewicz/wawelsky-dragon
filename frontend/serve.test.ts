// Testy frontend/serve.ts wg briefu T1 (Wymagania 6a–6m) i kontraktu C8.
// Uruchamiane przez `bun test ./serve.test.ts`; NIE są w kolekcji vitest (exclude w vitest.config.ts).
import { describe, test, expect, beforeAll, afterAll } from 'bun:test'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { startServer } from './serve'

const INDEX_HTML = '<!doctype html><title>WD</title>'
const HSTS_VALUE = 'max-age=31536000; includeSubDomains'

type Server = ReturnType<typeof startServer>

let distDir: string
// licznik wywołań upstreamu — test h sprawdza, że 413 po Content-Length nie sięga upstreamu
let upstreamCalls = 0
// znacznik czasu anulowania strumienia po stronie upstreamu — test m
let upstreamCancelAt = 0
// licznik wywołań atrapy MCP — test (d) sprawdza, że /mcpx i /mcp/ nie sięgają tej atrapy
let mcpCalls = 0
// chwila wysłania drugiego eventu SSE przez atrapę MCP — test (b): 0 = jeszcze nie wysłany
let mcpSseSecondAt = 0

const enc = (s: string) => new TextEncoder().encode(s)

// ciało-źródło: N bajtów bez Content-Length (fetch wyśle chunked)
function byteStream(totalBytes: number, chunkSize = 65536): ReadableStream<Uint8Array> {
  let sent = 0
  return new ReadableStream({
    pull(controller) {
      if (sent >= totalBytes) {
        controller.close()
        return
      }
      const size = Math.min(chunkSize, totalBytes - sent)
      controller.enqueue(new Uint8Array(size))
      sent += size
    },
  })
}

function sseResponse(frames: Array<{ delayMs: number; text: string }>): Response {
  let timer: ReturnType<typeof setTimeout> | undefined
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      let i = 0
      const next = () => {
        controller.enqueue(enc(frames[i]!.text))
        i++
        if (i < frames.length) timer = setTimeout(next, frames[i]!.delayMs)
        else controller.close()
      }
      next()
    },
    cancel() {
      if (timer) clearTimeout(timer)
    },
  })
  return new Response(body, { headers: { 'content-type': 'text/event-stream' } })
}

let upstream: Server
let healthUpstream: Server
let mcpUpstream: Server // atrapa serwera MCP (K17): /mcp, /sse, /messages/
let s1: Server // główny: limit 10 MiB, WD_PUBLIC_BASE_URL http (bez HSTS)
let s2: Server // WD_PUBLIC_BASE_URL https → HSTS
let s3: Server // padnięty upstream 127.0.0.1:1, limit 1 MiB
let s4: Server // upstream z /health/live = 200
let s5: Server // env KEYCLOAK_URL/FEATURE_AGENT → /env-config.js

beforeAll(() => {
  distDir = mkdtempSync(join(tmpdir(), 'wd-serve-'))
  mkdirSync(join(distDir, 'assets'))
  writeFileSync(join(distDir, 'index.html'), INDEX_HTML)
  writeFileSync(join(distDir, 'assets', 'app-abc123.js'), '// app')

  upstream = Bun.serve({
    port: 0,
    idleTimeout: 0,
    async fetch(req) {
      upstreamCalls++
      const url = new URL(req.url)
      if (req.method === 'POST' && url.pathname === '/api/v1/upload') {
        let n = 0
        if (req.body) for await (const chunk of req.body) n += chunk.byteLength
        return Response.json({ bytes: n })
      }
      if (url.pathname === '/api/v1/echo') {
        const h: Record<string, string> = {}
        req.headers.forEach((v, k) => {
          h[k] = v
        })
        return Response.json(h)
      }
      if (url.pathname === '/api/v1/sse') {
        return sseResponse([
          { delayMs: 0, text: 'data: 1\n\n' },
          { delayMs: 300, text: 'data: 2\n\n' },
        ])
      }
      if (url.pathname === '/api/v1/sse-slow') {
        return sseResponse([
          { delayMs: 0, text: 'data: 1\n\n' },
          { delayMs: 12_000, text: 'data: 2\n\n' },
        ])
      }
      if (url.pathname === '/api/v1/sse-cancel') {
        let timer: ReturnType<typeof setInterval> | undefined
        let i = 0
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            timer = setInterval(() => controller.enqueue(enc(`data: ${i++}\n\n`)), 100)
          },
          cancel() {
            if (timer) clearInterval(timer)
            upstreamCancelAt = Date.now()
          },
        })
        return new Response(body, { headers: { 'content-type': 'text/event-stream' } })
      }
      if (url.pathname === '/api/v1/cookies') {
        return new Response('ok', {
          headers: new Headers([
            ['set-cookie', 'a=1; Path=/'],
            ['set-cookie', 'b=2; Path=/'],
          ]),
        })
      }
      return Response.json({ code: 404, path: url.pathname + url.search }, { status: 404 })
    },
  })
  const up = `http://localhost:${upstream.port}`

  healthUpstream = Bun.serve({
    port: 0,
    fetch() {
      return new Response('ok')
    },
  })

  // atrapa serwera MCP — zwraca nagłówki żądania i ciało (a), strumień SSE (b), echo ścieżki (e)
  mcpUpstream = Bun.serve({
    port: 0,
    idleTimeout: 0,
    fetch(req) {
      mcpCalls++
      const url = new URL(req.url)
      if (url.pathname === '/mcp') {
        const h: Record<string, string> = {}
        req.headers.forEach((v, k) => {
          h[k] = v
        })
        return Response.json(
          { ok: true, method: req.method, headers: h },
          { headers: { 'mcp-session-id': 'resp-sess' } },
        )
      }
      if (url.pathname === '/sse') {
        let timer: ReturnType<typeof setTimeout> | undefined
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(enc('event: endpoint\ndata: /messages/?session_id=x\n\n'))
            timer = setTimeout(() => {
              mcpSseSecondAt = Date.now()
              controller.enqueue(enc('event: message\ndata: {}\n\n'))
              controller.close()
            }, 300)
          },
          cancel() {
            if (timer) clearTimeout(timer)
          },
        })
        return new Response(body, { headers: { 'content-type': 'text/event-stream' } })
      }
      if (url.pathname === '/messages/') {
        return Response.json({ path: url.pathname + url.search, method: req.method })
      }
      return Response.json({ code: 404, path: url.pathname + url.search }, { status: 404 })
    },
  })
  const mcpUp = `http://localhost:${mcpUpstream.port}`

  s1 = startServer({
    port: 0,
    distDir,
    upstream: up,
    mcpUpstream: mcpUp,
    maxUploadBytes: 10 * 1024 * 1024,
    env: { WD_PUBLIC_BASE_URL: 'http://localhost:8080' },
  })
  s2 = startServer({
    port: 0,
    distDir,
    upstream: up,
    mcpUpstream: mcpUp,
    maxUploadBytes: 10 * 1024 * 1024,
    env: { WD_PUBLIC_BASE_URL: 'https://wd.example.com' },
  })
  s3 = startServer({
    port: 0,
    distDir,
    upstream: 'http://127.0.0.1:1',
    mcpUpstream: 'http://127.0.0.1:1',
    maxUploadBytes: 1024 * 1024,
    env: {},
  })
  s4 = startServer({
    port: 0,
    distDir,
    upstream: `http://localhost:${healthUpstream.port}`,
    mcpUpstream: mcpUp,
    maxUploadBytes: 1024 * 1024,
    env: {},
  })
  s5 = startServer({
    port: 0,
    distDir,
    upstream: up,
    mcpUpstream: mcpUp,
    maxUploadBytes: 1024 * 1024,
    env: { KEYCLOAK_URL: 'http://kc', FEATURE_AGENT: 'true' },
  })
})

afterAll(() => {
  for (const s of [s1, s2, s3, s4, s5, upstream, healthUpstream, mcpUpstream]) s.stop(true)
  rmSync(distDir, { recursive: true, force: true })
})

const base = (s: Server) => `http://localhost:${s.port}`

describe('statyka', () => {
  test('GET / → 200 index.html, no-cache, 4 nagłówki bezpieczeństwa, bez HSTS', async () => {
    const res = await fetch(`${base(s1)}/`)
    expect(res.status).toBe(200)
    expect(await res.text()).toBe(INDEX_HTML)
    expect(res.headers.get('cache-control')).toBe('no-cache')
    expect(res.headers.get('content-security-policy')).toBe(
      "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self' blob:; connect-src 'self'",
    )
    // DEC-055: 'unsafe-inline' tylko w style-src (Emotion/MUI); skrypty nadal wyłącznie 'self'
    // DEC-056: script-src jawny, żeby Chromium nie logował ostrzeżenia o fallbacku z default-src
    const csp = res.headers.get('content-security-policy') ?? ''
    expect(csp.match(/unsafe-inline/g)).toHaveLength(1)
    expect(csp).toContain("default-src 'self'; script-src 'self';")
    expect(csp).not.toContain("script-src 'self' 'unsafe-inline'")
    expect(res.headers.get('x-content-type-options')).toBe('nosniff')
    expect(res.headers.get('referrer-policy')).toBe('strict-origin-when-cross-origin')
    expect(res.headers.get('x-frame-options')).toBe('SAMEORIGIN')
    expect(res.headers.get('strict-transport-security')).toBeNull()
  })

  test('HSTS przy WD_PUBLIC_BASE_URL=https', async () => {
    const res = await fetch(`${base(s2)}/`)
    expect(res.status).toBe(200)
    expect(res.headers.get('strict-transport-security')).toBe(HSTS_VALUE)
  })

  test('assets: immutable; brak pliku pod /assets/ → 404', async () => {
    const ok = await fetch(`${base(s1)}/assets/app-abc123.js`)
    expect(ok.status).toBe(200)
    expect(ok.headers.get('cache-control')).toBe('public, max-age=31536000, immutable')
    const miss = await fetch(`${base(s1)}/assets/brak.js`)
    expect(miss.status).toBe(404)
  })

  test('SPA fallback: GET /datasets/123 → 200 index.html', async () => {
    const res = await fetch(`${base(s1)}/datasets/123`)
    expect(res.status).toBe(200)
    expect(await res.text()).toBe(INDEX_HTML)
  })

  test('path traversal: encodowane ..%2f i %2e%2e nie wychodzą poza distDir', async () => {
    // brief: status ≠ 200 albo treść = index.html (nigdy zawartość pliku spoza distDir)
    const r1 = await fetch(`${base(s1)}/..%2f..%2fetc%2fpasswd`)
    const r2 = await fetch(`${base(s1)}/%2e%2e/%2e%2e/etc/passwd`)
    for (const res of [r1, r2]) {
      const body = await res.text()
      expect(res.status !== 200 || body === INDEX_HTML).toBe(true)
    }
  })

  test('POST /datasets (nie-API) → 405', async () => {
    const res = await fetch(`${base(s1)}/datasets`, { method: 'POST' })
    expect(res.status).toBe(405)
  })
})

describe('proxy', () => {
  test('prefiksy proxy nie przechwycone przez SPA fallback', async () => {
    for (const p of [
      '/api/v1/nope',
      '/v1/x',
      '/user-api/x',
      '/sharepoint-sync-api/x',
      '/health/live',
    ]) {
      const res = await fetch(`${base(s1)}${p}`)
      expect(res.status).toBe(404)
      const json = (await res.json()) as { code: number; path: string }
      expect(json.code).toBe(404)
      expect(json.path).toBe(p)
    }
  })

  test('query string przekazany do upstreamu', async () => {
    const res = await fetch(`${base(s1)}/api/v1/x?a=1&b=2`)
    const json = (await res.json()) as { path: string }
    expect(json.path).toBe('/api/v1/x?a=1&b=2')
  })

  test('prefiks /api (bez końcowego ukośnika) też jest proxy', async () => {
    const res = await fetch(`${base(s1)}/api`)
    expect(res.status).toBe(404)
    const json = (await res.json()) as { path: string }
    expect(json.path).toBe('/api')
  })

  test('nagłówki X-Forwarded-*; hop-by-hop i accept-encoding usunięte', async () => {
    const res = await fetch(`${base(s1)}/api/v1/echo`, {
      headers: { 'proxy-authorization': 'Basic c2VjcmV0', 'accept-encoding': 'gzip' },
    })
    const h = (await res.json()) as Record<string, string>
    expect(h['x-forwarded-for']).toBeTruthy()
    expect(h['x-forwarded-proto']).toBe('http')
    expect(h['x-forwarded-host']).toBe(`localhost:${s1.port}`)
    expect(h['proxy-authorization']).toBeUndefined()
    // wartość wysłana przez klienta nie może dotrzeć do upstreamu (Bun dokleja własną domyślną)
    expect(h['accept-encoding']).not.toBe('gzip')
  })

  test('wiele Set-Cookie z upstreamu przekazane po kolei', async () => {
    const res = await fetch(`${base(s1)}/api/v1/cookies`)
    expect(res.status).toBe(200)
    const cookies = res.headers.getSetCookie()
    expect(cookies).toHaveLength(2)
    expect(cookies).toContain('a=1; Path=/')
    expect(cookies).toContain('b=2; Path=/')
  })
})

describe('SSE', () => {
  test('pierwsza ramka < 250 ms (brak buforowania), nagłówki SSE', async () => {
    const t0 = Date.now()
    const res = await fetch(`${base(s1)}/api/v1/sse`)
    const reader = res.body!.getReader()
    const first = await reader.read()
    expect(Date.now() - t0).toBeLessThan(250)
    expect(new TextDecoder().decode(first.value)).toBe('data: 1\n\n')
    expect(res.headers.get('x-accel-buffering')).toBe('no')
    expect(res.headers.get('cache-control')).toBe('no-cache')
    expect(res.headers.get('content-type')?.startsWith('text/event-stream')).toBe(true)
    // cała treść zawiera obie ramki
    let text = new TextDecoder().decode(first.value)
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      text += new TextDecoder().decode(value)
    }
    expect(text).toContain('data: 1')
    expect(text).toContain('data: 2')
  })

  test('przerwa 12 s między ramkami nie zrywa połączenia (idleTimeout wyłączony)', async () => {
    const res = await fetch(`${base(s1)}/api/v1/sse-slow`)
    const text = await new Response(res.body).text()
    expect(text).toContain('data: 1')
    expect(text).toContain('data: 2')
  }, 30_000)
})

describe('proxy MCP (K17 §1)', () => {
  test('(a) /mcp przekazuje nagłówki żądania, metodę i nagłówki oraz ciało odpowiedzi', async () => {
    const res = await fetch(`${base(s1)}/mcp`, {
      headers: { authorization: 'Bearer tok-1', api_key: 'k-1', 'mcp-session-id': 'sess-1' },
    })
    expect(res.status).toBe(200)
    expect(res.headers.get('mcp-session-id')).toBe('resp-sess') // nagłówki odpowiedzi przez proxy
    const json = (await res.json()) as {
      ok: boolean
      method: string
      headers: Record<string, string>
    }
    expect(json.ok).toBe(true)
    expect(json.method).toBe('GET')
    expect(json.headers['authorization']).toBe('Bearer tok-1')
    expect(json.headers['api_key']).toBe('k-1')
    expect(json.headers['mcp-session-id']).toBe('sess-1')

    // metody nie są przepisywane na GET (streamable HTTP: GET/POST/DELETE)
    const del = await fetch(`${base(s1)}/mcp`, { method: 'DELETE' })
    expect(((await del.json()) as { method: string }).method).toBe('DELETE')
  })

  test('(b) /sse strumieniuje bez buforowania: pierwszy event dociera przed drugim', async () => {
    mcpSseSecondAt = 0
    const res = await fetch(`${base(s1)}/sse`)
    expect(res.headers.get('content-type')?.startsWith('text/event-stream')).toBe(true)
    expect(res.headers.get('x-accel-buffering')).toBe('no')
    expect(res.headers.get('cache-control')).toBe('no-cache')
    const reader = res.body!.getReader()
    const first = await reader.read()
    // atrapa wysyła drugi event po 300 ms — jeśli proxy buforuje, `mcpSseSecondAt` byłby już ustawiony
    expect(mcpSseSecondAt).toBe(0)
    const head = new TextDecoder().decode(first.value)
    expect(head).toContain('event: endpoint')
    expect(head).toContain('/messages/?session_id=x')
    let text = head
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      text += new TextDecoder().decode(value)
    }
    expect(text).toContain('event: endpoint')
    expect(text).toContain('event: message')
  })

  test('(c) upstream MCP nieosiągalny → 503 z treścią z K17 §1 (application/json)', async () => {
    const res = await fetch(`${base(s3)}/mcp`)
    expect(res.status).toBe(503)
    expect(res.headers.get('content-type')?.startsWith('application/json')).toBe(true)
    expect(await res.json()).toEqual({
      error: 'MCP server is not enabled (compose profile "mcp")',
    })
  })

  test('(d) /mcpx i /mcp/ nie trafiają do upstreamu MCP (SPA fallback), /mcp to trasa dokładna', async () => {
    const before = mcpCalls
    for (const p of ['/mcpx', '/mcp/']) {
      const res = await fetch(`${base(s1)}${p}`)
      expect(res.status).toBe(200)
      expect(await res.text()).toBe(INDEX_HTML)
    }
    expect(mcpCalls).toBe(before)
  })

  test('(e) POST /messages/?session_id=x przekazuje metodę i query do upstreamu', async () => {
    const res = await fetch(`${base(s1)}/messages/?session_id=x`, { method: 'POST', body: 'ping' })
    expect(res.status).toBe(200)
    const json = (await res.json()) as { path: string; method: string }
    expect(json.method).toBe('POST')
    expect(json.path).toBe('/messages/?session_id=x')
  })
})

describe('upload i limit', () => {
  test('strumień 5 MiB przy limicie 10 MiB → upstream widzi dokładnie 5 242 880 bajtów', async () => {
    const res = await fetch(`${base(s1)}/api/v1/upload`, {
      method: 'POST',
      body: byteStream(5 * 1024 * 1024),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(200)
    expect(((await res.json()) as { bytes: number }).bytes).toBe(5_242_880)
  })

  test('Content-Length > limit → 413 z JSON kontraktu, upstream nie wołany', async () => {
    const before = upstreamCalls
    // uczciwe body: zgodne z podanym Content-Length (2 MiB), limit serwera s5 to 1 MiB
    const res = await fetch(`${base(s5)}/api/v1/x`, {
      method: 'POST',
      headers: { 'content-length': String(2 * 1024 * 1024) },
      body: byteStream(2 * 1024 * 1024),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ code: 413, message: 'Payload Too Large', data: null })
    expect(upstreamCalls).toBe(before)
  })

  // Regresja E3-H4 p. 5a: przy natywnym zapasie `limit + 1 MiB` żądanie z Content-Length
  // ponad ten zapas Bun ucinał po nagłówku i odsyłał PUSTE 413 (bez koperty C8). Po
  // powiększeniu zapasu nadmiar odbiera handler (`drainBody`), więc odpowiedź ma JSON.
  test('Content-Length > limit + 1 MiB → nadal 413 z JSON kontraktu, nie pusty 413 Buna', async () => {
    const before = upstreamCalls
    const bytes = 3 * 1024 * 1024 // limit s5 to 1 MiB, stary zapas Buna to 2 MiB
    const res = await fetch(`${base(s5)}/api/v1/x`, {
      method: 'POST',
      headers: { 'content-length': String(bytes) },
      body: byteStream(bytes),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ code: 413, message: 'Payload Too Large', data: null })
    expect(upstreamCalls).toBe(before)
  })

  // C5: 413 po samym Content-Length nie może wciągać całego ciała — odczyt ograniczony do
  // `maxUploadBytes + 1 MiB`, reszta strumienia anulowana (klient nie dosyła gigabajtów).
  test('Content-Length ≫ limit → 413, klient wysyła ≤ limit + 2 MiB, reszta anulowana', async () => {
    const before = upstreamCalls
    const limit = 1024 * 1024 // s5
    const budget = limit + 1024 * 1024 // limit odczytu drainBody (C5)
    const total = 16 * 1024 * 1024 // ≫ limit + 1 MiB
    let enqueued = 0
    let sent = 0
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (sent >= total) {
          controller.close()
          return
        }
        const size = Math.min(64 * 1024, total - sent)
        controller.enqueue(new Uint8Array(size))
        sent += size
        enqueued += size
      },
    })
    const res = await fetch(`${base(s5)}/api/v1/x`, {
      method: 'POST',
      headers: { 'content-length': String(total) },
      body,
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ code: 413, message: 'Payload Too Large', data: null })
    expect(upstreamCalls).toBe(before)
    // limit odczytu + 1 MiB zapasu na bufory; 16 MiB ciała nie może przejść w całości (było 16 MiB)
    expect(enqueued).toBeLessThanOrEqual(budget + 1024 * 1024)
  })

  test('strumień bez Content-Length przekraczający limit → 413', async () => {
    const res = await fetch(`${base(s5)}/api/v1/upload`, {
      method: 'POST',
      body: byteStream(3 * 1024 * 1024),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ code: 413, message: 'Payload Too Large', data: null })
  })
})

describe('healthz i env-config', () => {
  test('GET /env-config.js → dokładna treść z env', async () => {
    const res = await fetch(`${base(s5)}/env-config.js`)
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')?.startsWith('application/javascript')).toBe(true)
    expect(await res.text()).toBe(
      'window.__ENV__ = {"KEYCLOAK_URL":"http://kc","KEYCLOAK_REALM":"","KEYCLOAK_CLIENT_ID":"","DOCS_URL":"","FEATURE_AGENT":"true","FEATURE_MEMORY":"","FEATURE_SEARCH":"","FEATURE_FILES":""};\n',
    )
  })

  test('healthz: żywy upstream → 200 ok', async () => {
    const res = await fetch(`${base(s4)}/healthz`)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ status: 'ok' })
  })

  test('padnięty upstream: healthz → 503, proxy → 502 z JSON kontraktu', async () => {
    const hz = await fetch(`${base(s3)}/healthz`)
    expect(hz.status).toBe(503)
    expect(await hz.json()).toEqual({ status: 'upstream_unavailable' })
    const px = await fetch(`${base(s3)}/api/v1/x`)
    expect(px.status).toBe(502)
    expect(await px.json()).toEqual({ code: 502, message: 'Bad Gateway', data: null })
  })
})

describe('abort', () => {
  test('przerwanie połączenia przez klienta → upstream widzi cancel w 2 s', async () => {
    upstreamCancelAt = 0
    const ac = new AbortController()
    const res = await fetch(`${base(s1)}/api/v1/sse-cancel`, { signal: ac.signal })
    const reader = res.body!.getReader()
    await reader.read()
    ac.abort()
    const deadline = Date.now() + 2000
    while (upstreamCancelAt === 0 && Date.now() < deadline) await Bun.sleep(25)
    expect(upstreamCancelAt).toBeGreaterThan(0)
  })
})

// T6 (SP-8): domyślny maxRequestBodySize Bun (128 MiB) odcina upload pustym 413,
// zanim żądanie dotrze do handlera serve.ts. Zapas natywnego limitu jest teraz duży
// (limit + 1 GiB, E3-H4 p. 5a): przy zapasie 1 MiB Bun bywał szybszy od licznika
// handlera, gdy pętla JS się spóźniła, i odsyłał PUSTE 413 bez koperty JSON C8.
// Limit egzekwuje handler (`drainBody` po Content-Length i `countingStream`).
describe('upload > 128 MiB przez Bun.serve (SP-8, T6)', () => {
  // własny upstream z podniesionym limitem Buna (4 GiB, jak w SP-8) — domyślne 128 MiB
  // odcięłoby body w upstreamie, zanim serve.ts zdążyłby cokolwiek udowodnić
  let bigUpstream: Server
  let sBig: Server // serve.ts z maxUploadBytes = 300 MiB (WD_MAX_UPLOAD_MB=300)

  beforeAll(() => {
    bigUpstream = Bun.serve({
      port: 0,
      idleTimeout: 0,
      maxRequestBodySize: 4 * 1024 ** 3,
      async fetch(req) {
        let n = 0
        if (req.body) for await (const chunk of req.body) n += chunk.byteLength
        return Response.json({ bytes: n })
      },
    })
    sBig = startServer({
      port: 0,
      distDir,
      upstream: `http://localhost:${bigUpstream.port}`,
      mcpUpstream: `http://localhost:${bigUpstream.port}`,
      maxUploadBytes: 300 * 1024 * 1024,
      env: {},
    })
  })

  afterAll(() => {
    sBig.stop(true)
    bigUpstream.stop(true)
  })

  // jak uploadBody w SP-8: jeden Uint8Array wielokrotnie, bez Content-Length (fetch wyśle chunked)
  function streamMb(mb: number, chunkBytes = 1024 * 1024): ReadableStream<Uint8Array> {
    const chunk = new Uint8Array(chunkBytes).fill(0x57)
    const chunks = Math.ceil((mb * 1024 * 1024) / chunkBytes)
    let sent = 0
    return new ReadableStream({
      pull(controller) {
        if (sent >= chunks) {
          controller.close()
          return
        }
        controller.enqueue(chunk)
        sent++
      },
    })
  }

  test('strumień 200 MiB przy limicie 300 MiB → 200, upstream widzi dokładnie 209715200 B', async () => {
    const res = await fetch(`${base(sBig)}/api/v1/upload`, {
      method: 'POST',
      body: streamMb(200),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(200)
    expect(((await res.json()) as { bytes: number }).bytes).toBe(209_715_200)
  }, 60_000)

  test('strumień 310 MiB przy limicie 300 MiB → 413 z JSON kontraktu, nie pusty 413 Buna', async () => {
    // wariant z briefu bez nagłówka Content-Length (jawny CL 400 MiB Bun odrzuca po
    // nagłówku pustym 413 przed handlerem — pozostała ścieżka to strumień nadmiaru);
    // kawałki 64 KiB, by nadmiar liczył `countingStream` (limit + 1 GiB zapasu Buna)
    const res = await fetch(`${base(sBig)}/api/v1/upload`, {
      method: 'POST',
      body: streamMb(310, 64 * 1024),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ code: 413, message: 'Payload Too Large', data: null })
  }, 60_000)
})
