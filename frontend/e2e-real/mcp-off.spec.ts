// SC-E6-2-05 (K17 §1/§5, brief T8 WP E6-2): stos clean-install BEZ profilu `mcp` — trasy MCP
// proxy `web` odpowiadają 503 application/json z treścią kontraktu (`MCP server is not enabled
// (compose profile "mcp")`), bo usługi `mcp` nie ma, a `web` startuje i działa bez niej:
// `GET /healthz` = 200, `GET /` zwraca SPA. Klient = surowe HTTP (fetch), serwer nie startuje,
// więc nie ma tu żadnego JSON-RPC — liczy się zachowanie proxy. Bieg: WD_CI_SPEC=mcp-off.spec.ts
// (bez WD_CI_PROFILES); patrz tools/dev/mcp-prod-check.sh.
import { expect, test } from '@playwright/test'

const BASE = (process.env.WD_CI_BASE_URL ?? '').replace(/\/+$/, '')

// K17 §1: treść 503, gdy serwer MCP nie działa (profil compose `mcp` wyłączony) — serve.ts.
const MCP_DISABLED_BODY = { error: 'MCP server is not enabled (compose profile "mcp")' }

// POST /mcp z ciałem żądania initialize — jak rzeczywisty klient próbujący rozpocząć sesję.
const INIT_REQUEST = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: {
    protocolVersion: '2025-11-25',
    capabilities: {},
    clientInfo: { name: 'wd-e2e-real-mcp-off', version: '0.0.0' },
  },
})

test.describe.configure({ mode: 'serial' })

test('SC-E6-2-05: web bez profilu mcp → 503 na /mcp i /sse, web zdrowy, SPA działa', async ({
  request,
}) => {
  test.setTimeout(120_000)
  expect(BASE, 'WD_CI_BASE_URL od clean-install.sh').not.toBe('')

  // (a) POST /mcp: 503 application/json z treścią K17 §1 (proxy nie znajduje upstreamu).
  const post = await fetch(`${BASE}/mcp`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      authorization: 'Bearer ragflow-mcp-off-key',
    },
    body: INIT_REQUEST,
  })
  expect(post.status, 'POST /mcp bez usługi mcp → 503').toBe(503)
  expect(
    post.headers.get('content-type') ?? '',
    '503 /mcp: content-type application/json',
  ).toContain('application/json')
  expect(await post.json(), 'treść 503 z K17 §1').toEqual(MCP_DISABLED_BODY)

  // (b) GET /sse: ten sam 503 (strumień nie powstaje).
  const sse = await fetch(`${BASE}/sse`, {
    headers: { accept: 'text/event-stream', authorization: 'Bearer ragflow-mcp-off-key' },
  })
  expect(sse.status, 'GET /sse bez usługi mcp → 503').toBe(503)
  expect(await sse.json(), 'treść 503 SSE z K17 §1').toEqual(MCP_DISABLED_BODY)

  // (c) web zdrowy: healthz 200 (status przez API), strona główna serwuje SPA.
  const health = await request.get('/healthz')
  expect(health.status(), 'GET /healthz (web) → 200').toBe(200)
  expect(await health.json(), 'healthz: status ok').toEqual({ status: 'ok' })

  const home = await request.get('/')
  expect(home.status(), 'GET / → SPA').toBe(200)
  expect(home.headers()['content-type'] ?? '', 'SPA serwowany jako HTML').toContain('text/html')
})
