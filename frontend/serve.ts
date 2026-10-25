// Serwer statyczny SPA + reverse proxy do API (Bun, bez zależności npm — tylko API Bun/Web).
// Kontrakt: work/wp/E0-3/CONTRACT.md C8; dokumentacja: docs/architecture/11-infrastruktura.md §2.2.
import { join, resolve, sep } from 'node:path'

export type ServeOptions = {
  port: number
  distDir: string
  upstream: string
  mcpUpstream: string
  maxUploadBytes: number
  env: Record<string, string | undefined>
}

export const PROXY_PREFIXES: readonly string[] = [
  '/api/',
  '/v1/',
  '/user-api/',
  '/sharepoint-sync-api/',
  '/health/',
]

// K17 §1: proxy serwera MCP (usługa `mcp`, profil compose `mcp`) — trasy dokładne `/mcp`
// i `/sse` oraz prefiks `/messages/`; `/mcp/` i `/mcpx` nie pasują (muszą iść do SPA).
export const PROXY_MCP_PREFIXES: readonly string[] = ['/mcp', '/sse', '/messages/']

// DEC-055: 'unsafe-inline' tylko dla styli (Emotion/MUI); skrypty pozostają przy 'self'.
// DEC-056: `script-src 'self'` jawne (nie przez fallback `default-src`) — Chromium loguje
// ostrzeżenie o fallbacku przy modulepreload Vite, a harness e2e wymaga zera błędów konsoli.
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self' blob:; connect-src 'self'"
const HSTS = 'max-age=31536000; includeSubDomains'

// nagłówki hop-by-hop (RFC 9110 §7.6.1) — usuwane w obie strony proxy
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

// marker błędu limitu uploadu — rozpoznawany przez instanceof, nigdy po treści komunikatu
class UploadLimitError extends Error {
  constructor() {
    super('upload limit exceeded')
  }
}

function errorResponse(status: 413 | 502, message: string): Response {
  return Response.json({ code: status, message, data: null }, { status })
}

// kopiuje nagłówki pomijając hop-by-hop + te wymienione w wartości Connection
function copyHeaders(headers: Headers, dropRequestOnly: boolean): Headers {
  const drop = new Set(HOP_BY_HOP)
  const connection = headers.get('connection')
  if (connection) {
    for (const token of connection.split(',')) {
      const name = token.trim().toLowerCase()
      if (name) drop.add(name)
    }
  }
  const out = new Headers()
  headers.forEach((value, name) => {
    const n = name.toLowerCase()
    if (drop.has(n)) return
    if (dropRequestOnly && (n === 'host' || n === 'accept-encoding')) return
    if (!dropRequestOnly && n === 'set-cookie') return // niżej przez getSetCookie(), żeby nie skolapsować
    out.set(name, value)
  })
  if (!dropRequestOnly) {
    // wiele Set-Cookie (np. wd_refresh + czyszczenie wd_oidc) — każde osobno przez append
    for (const cookie of headers.getSetCookie()) out.append('set-cookie', cookie)
  }
  return out
}

export function optionsFromEnv(env: Record<string, string | undefined>): ServeOptions {
  return {
    port: Number(env.PORT ?? 8080),
    distDir: env.WD_WEB_DIST ?? join(import.meta.dir, 'dist'),
    upstream: (env.WD_API_UPSTREAM ?? 'http://api:8000').replace(/\/+$/, ''),
    mcpUpstream: (env.WD_MCP_UPSTREAM ?? 'http://mcp:9382').replace(/\/+$/, ''),
    maxUploadBytes: Number(env.WD_MAX_UPLOAD_MB ?? 1024) * 1024 * 1024,
    env,
  }
}

function isProxyPath(pathname: string): boolean {
  for (const prefix of PROXY_PREFIXES) {
    if (pathname.startsWith(prefix)) return true
    if (pathname === prefix.slice(0, -1)) return true
  }
  return false
}

// K17 §1: tylko dokładne `/mcp` (z query) i `/sse` oraz prefiks `/messages/`; `/mcp/` i `/mcpx`
// NIE są trasami MCP (trafiają do SPA, nie do upstreamu MCP). Wpis z końcowym `/` = prefiks.
function isMcpPath(pathname: string): boolean {
  return PROXY_MCP_PREFIXES.some((p) => (p.endsWith('/') ? pathname.startsWith(p) : pathname === p))
}

async function healthz(opts: ServeOptions): Promise<Response> {
  try {
    const res = await fetch(opts.upstream + '/health/live', { signal: AbortSignal.timeout(3000) })
    if (res.status === 200) return Response.json({ status: 'ok' })
  } catch {
    // upstream niedostępny lub timeout 3 s → 503 poniżej
  }
  return Response.json({ status: 'upstream_unavailable' }, { status: 503 })
}

// runtime config dla SPA — klucze dokładnie w kolejności z C8 pkt 2
function envConfig(opts: ServeOptions): Response {
  const env = opts.env
  const config = {
    KEYCLOAK_URL: env.KEYCLOAK_URL ?? '',
    KEYCLOAK_REALM: env.KEYCLOAK_REALM ?? '',
    KEYCLOAK_CLIENT_ID: env.KEYCLOAK_CLIENT_ID ?? '',
    DOCS_URL: env.DOCS_URL ?? '',
    FEATURE_AGENT: env.FEATURE_AGENT ?? '',
    FEATURE_MEMORY: env.FEATURE_MEMORY ?? '',
    FEATURE_SEARCH: env.FEATURE_SEARCH ?? '',
    FEATURE_FILES: env.FEATURE_FILES ?? '',
  }
  return new Response(`window.__ENV__ = ${JSON.stringify(config)};\n`, {
    status: 200,
    headers: {
      'content-type': 'application/javascript; charset=utf-8',
      'cache-control': 'no-cache',
    },
  })
}

// TransformStream zliczający bajty; po przekroczeniu limitu errowuje markerem → fetch odrzuca
function countingStream(maxBytes: number): TransformStream<Uint8Array, Uint8Array> {
  let total = 0
  return new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      total += chunk.byteLength
      if (total > maxBytes) {
        controller.error(new UploadLimitError())
        return
      }
      controller.enqueue(chunk)
    },
  })
}

// wyciąga co najwyżej `limit` bajtów body i anuluje resztę strumienia (bez upstreamu) —
// klient dosyłający ciało dostaje pełną odpowiedź 413 (nie RST po zerwaniu połączenia),
// a serwer nie wciąga całego gigabajtowego ciała (C5, DEC-258)
async function drainBody(req: Request, limit: number): Promise<void> {
  if (!req.body) return
  const reader = req.body.getReader()
  let read = 0
  while (read < limit) {
    const { done, value } = await reader.read()
    if (done) break
    read += value.byteLength
  }
  await reader.cancel()
}

function proxyRequestHeaders(req: Request, server: Bun.Server): Headers {
  const out = copyHeaders(req.headers, true)
  const ip = server.requestIP(req)?.address ?? ''
  const forwardedFor = req.headers.get('x-forwarded-for')
  out.set('x-forwarded-for', forwardedFor ? `${forwardedFor}, ${ip}` : ip)
  out.set('x-forwarded-proto', req.headers.get('x-forwarded-proto') ?? 'http')
  const host = req.headers.get('host')
  if (host) out.set('x-forwarded-host', host)
  return out
}

async function proxy(
  req: Request,
  server: Bun.Server,
  url: URL,
  opts: ServeOptions,
): Promise<Response> {
  const target = opts.upstream + url.pathname + url.search
  let body: BodyInit | undefined
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    const contentLength = req.headers.get('content-length')
    if (contentLength !== null && Number(contentLength) > opts.maxUploadBytes) {
      // 413 bez kontaktu z upstreamem; ograniczony odczyt (C5), by klient dostał pełną odpowiedź
      await drainBody(req, opts.maxUploadBytes + 1024 * 1024)
      return errorResponse(413, 'Payload Too Large')
    }
    if (req.body) body = req.body.pipeThrough(countingStream(opts.maxUploadBytes))
  }
  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers: proxyRequestHeaders(req, server),
      body,
      redirect: 'manual',
      signal: AbortSignal.any([req.signal, AbortSignal.timeout(3_600_000)]),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
  } catch (err) {
    if (err instanceof UploadLimitError) return errorResponse(413, 'Payload Too Large')
    if (req.signal.aborted) return new Response(null, { status: 499 }) // klient zniknął — odpowiedź nie dotrze
    return errorResponse(502, 'Bad Gateway')
  }
  const headers = copyHeaders(upstream.headers, false)
  if ((headers.get('content-type') ?? '').startsWith('text/event-stream')) {
    headers.set('x-accel-buffering', 'no')
    headers.set('cache-control', 'no-cache')
  }
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  })
}

// K17 §1: treść 503, gdy serwer MCP nie działa (profil compose `mcp` wyłączony).
const MCP_DISABLED_BODY = { error: 'MCP server is not enabled (compose profile "mcp")' }

// Proxy serwera MCP (K17 §1): wszystkie nagłówki żądania/odpowiedzi poza hop-by-hop, ciało jako
// strumień (bez buforowania), bez wymuszania kompresji; SSE bez limitu czasu bezczynności.
async function proxyMcp(
  req: Request,
  server: Bun.Server,
  url: URL,
  opts: ServeOptions,
): Promise<Response> {
  // /sse to długi strumień zdarzeń — wyłącz idle-timeout (idleTimeout Buna ma sufit 255 s)
  if (url.pathname === '/sse') server.timeout(req, 0)
  const target = opts.mcpUpstream + url.pathname + url.search
  const body = req.method === 'GET' || req.method === 'HEAD' ? undefined : (req.body ?? undefined)
  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers: proxyRequestHeaders(req, server),
      body,
      redirect: 'manual',
      signal: AbortSignal.any([req.signal, AbortSignal.timeout(3_600_000)]),
      duplex: 'half',
    } as RequestInit & { duplex: 'half' })
  } catch {
    if (req.signal.aborted) return new Response(null, { status: 499 }) // klient zniknął — odpowiedź nie dotrze
    return Response.json(MCP_DISABLED_BODY, { status: 503 })
  }
  const headers = copyHeaders(upstream.headers, false)
  if ((headers.get('content-type') ?? '').startsWith('text/event-stream')) {
    headers.set('x-accel-buffering', 'no')
    headers.set('cache-control', 'no-cache')
  }
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  })
}

async function staticFile(req: Request, url: URL, opts: ServeOptions): Promise<Response> {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    return new Response('Method Not Allowed', { status: 405, headers: { allow: 'GET, HEAD' } })
  }
  let decoded: string
  try {
    decoded = decodeURIComponent(url.pathname)
  } catch {
    return new Response('Bad Request', { status: 400 })
  }
  const root = resolve(opts.distDir)
  const filePath = resolve(root, '.' + decoded)
  // ochrona przed path traversal: ścieżka musi zostać wewnątrz distDir
  if (filePath !== root && !filePath.startsWith(root + sep)) {
    return new Response(null, { status: 404 })
  }
  let file: string
  if (filePath === root) {
    file = join(root, 'index.html') // /
  } else if (await Bun.file(filePath).exists()) {
    file = filePath
  } else if (decoded.startsWith('/assets/')) {
    return new Response(null, { status: 404 }) // brak assetu nigdy nie jest fallbackiem SPA
  } else {
    file = join(root, 'index.html') // SPA fallback
  }
  const servesIndex = file === join(root, 'index.html')
  const headers: Record<string, string> = {
    'cache-control':
      decoded.startsWith('/assets/') && !servesIndex
        ? 'public, max-age=31536000, immutable'
        : 'no-cache',
  }
  if (servesIndex) {
    headers['content-security-policy'] = CSP
    headers['x-content-type-options'] = 'nosniff'
    headers['referrer-policy'] = 'strict-origin-when-cross-origin'
    headers['x-frame-options'] = 'SAMEORIGIN'
    if (opts.env.WD_PUBLIC_BASE_URL?.startsWith('https://'))
      headers['strict-transport-security'] = HSTS
  }
  return new Response(Bun.file(file), { headers })
}

async function handle(req: Request, server: Bun.Server, opts: ServeOptions): Promise<Response> {
  const url = new URL(req.url)
  if (url.pathname === '/healthz') return healthz(opts)
  if (url.pathname === '/env-config.js') return envConfig(opts)
  if (isMcpPath(url.pathname)) return proxyMcp(req, server, url, opts)
  if (isProxyPath(url.pathname)) return proxy(req, server, url, opts)
  return staticFile(req, url, opts)
}

export function startServer(opts: ServeOptions): ReturnType<typeof Bun.serve> {
  return Bun.serve({
    port: opts.port,
    // idleTimeout: 0 wyłącza limit bezczynności (docs Bun) — długie strumienie SSE nie są zrywane
    idleTimeout: 0,
    // SP-8: domyślny limit ciała Bun (128 MiB) odcina upload pustym 413, zanim żądanie
    // dotrze do handlera. Zapas musi być duży (nie 1 MiB): przy wąskim zapasie licznik
    // handlera wyprzedzał natywną warstwę tylko dopóki pętla JS się nie spóźniła — a wtedy
    // Bun ucinał żądanie i odsyłał PUSTE 413 bez koperty JSON C8 (flak E3-H4 p. 5a,
    // reprodukcja 2/100). Limit egzekwuje handler (Content-Length w `drainBody` i licznik
    // `countingStream`); natywny limit zostaje wyłącznie bezpiecznikiem, więc zapas nie
    // kosztuje pamięci — Bun dławi strumień (SP-8: upload 1 GiB → wzrost RSS 41–62 MB).
    maxRequestBodySize: opts.maxUploadBytes + 1024 * 1024 * 1024,
    fetch: (req, server) => handle(req, server, opts),
  })
}

if (import.meta.main) startServer(optionsFromEnv(process.env))
