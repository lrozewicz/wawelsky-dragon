/**
 * Testy warstwy danych Ustawień (kontrakt WP E3-6c1 §2): maska tokenu i mutacje kluczy API.
 * Wzór: `features/admin/queries.test.tsx`. Odpowiedzi idą przez `apiCall`, więc każdy handler
 * musi zwracać pełną kopertę RAGFlow (`{code, message, data}`).
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import {
  maskToken,
  settingsKeys,
  tokensQueryOptions,
  useCreateToken,
  useDeleteToken,
} from './queries'
import type { ApiToken, CreatedApiToken } from './queries'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

/** Uruchamia mutację w `act` i oddaje jej wynik. */
async function actMutate<T>(run: () => Promise<T>): Promise<T> {
  let out!: T
  await act(async () => {
    out = await run()
  })
  return out
}

const TOKEN: ApiToken = {
  token: 'ragflow-abcdefghijklmnopqrstuvwxyz123456',
  tenant_id: 'tenant-1',
  name: null,
  dialog_id: null,
  source: null,
  beta: 'abcdef',
  create_time: 1_700_000_000,
  create_date: '2026-01-01',
  update_time: 1_700_000_000,
  update_date: '2026-01-01',
}

const CREATED: CreatedApiToken = {
  token: 'ragflow-newsecret0000000000000000000000',
  tenant_id: 'tenant-1',
  name: null,
  beta: 'abcdef',
  create_time: 1_700_000_000,
  create_date: '2026-01-01',
  update_time: null,
  update_date: null,
}

describe('maskToken', () => {
  it('zostawia 12 pierwszych i 4 ostatnie znaki, resztę zasłania', () => {
    expect(maskToken('ragflow-abcdefghijklmnopqrstuvwxyz123456')).toBe('ragflow-abcd…3456')
  })

  it('nie maskuje tokenów, których nie ma czego skracać', () => {
    expect(maskToken('short')).toBe('short')
    expect(maskToken('ragflow-abcdefgh')).toBe('ragflow-abcdefgh')
  })
})

describe('zapytania', () => {
  it('tokensQueryOptions zwraca listę kluczy z koperty', async () => {
    server.use(
      http.get(apiUrl('/api/v1/system/tokens'), () =>
        HttpResponse.json({ code: 0, message: 'success', data: [TOKEN] }),
      ),
    )

    expect(await createClient().fetchQuery(tokensQueryOptions())).toEqual([TOKEN])
  })
})

describe('mutacje kluczy API', () => {
  it('useCreateToken wysyła POST z nazwą i nie zapisuje tokenu w cache', async () => {
    const names: (string | null)[] = []
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), ({ request }) => {
        names.push(new URL(request.url).searchParams.get('name'))
        return HttpResponse.json({ code: 0, message: 'success', data: CREATED })
      }),
    )
    const client = createClient()
    client.setQueryData(settingsKeys.tokens, [TOKEN])
    const { result } = renderHook(() => useCreateToken(), { wrapper: wrapperFor(client) })

    const created = await actMutate(() => result.current.mutateAsync({ name: 'klucz' }))

    expect(names).toEqual(['klucz'])
    expect(created.token).toBe(CREATED.token)
    // Token jawny istnieje tylko w wyniku mutacji — do cache Query nie trafia.
    expect(client.getQueryData(settingsKeys.tokens)).toEqual([TOKEN])
    expect(JSON.stringify(client.getQueryData(settingsKeys.tokens))).not.toContain(CREATED.token)
    expect(client.getQueryState(settingsKeys.tokens)?.isInvalidated).toBe(true)
  })

  it('useDeleteToken kasuje po tokenie ze ścieżki i unieważnia listę', async () => {
    let path = ''
    server.use(
      http.delete(apiUrl('/api/v1/system/tokens/:token'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: true })
      }),
    )
    const client = createClient()
    client.setQueryData(settingsKeys.tokens, [TOKEN])
    const { result } = renderHook(() => useDeleteToken(), { wrapper: wrapperFor(client) })

    await actMutate(() => result.current.mutateAsync(TOKEN.token))

    expect(path).toBe(`/api/v1/system/tokens/${TOKEN.token}`)
    expect(client.getQueryState(settingsKeys.tokens)?.isInvalidated).toBe(true)
  })
})
