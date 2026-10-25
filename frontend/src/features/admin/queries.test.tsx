import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import { STATUS_REFETCH_MS } from './constants'
import {
  adminKeys,
  apiKeysQueryOptions,
  grantsQueryOptions,
  healthzQueryOptions,
  statsQueryOptions,
  useCreateApiKey,
  useCreateUser,
  useDeleteApiKey,
  useDeleteUser,
  useReplaceGrants,
  useSetPassword,
  useSetUserActive,
  useUpdateUser,
  usersListQueryOptions,
} from './queries'
import type { ApiKey, Stats, SystemHealthz, UsersPage, WdUser } from './queries'

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

const BASE_USER: WdUser = {
  id: 'u1',
  email: 'u1@wd.test',
  nickname: 'Jan',
  auth_source: 'local',
  is_superuser: false,
  is_active: true,
  language: 'pl',
  timezone: null,
  avatar: null,
  last_login_at: null,
  created_at: null,
  updated_at: null,
}
const BASE_KEY: ApiKey = {
  id: 'k1',
  name: 'klucz',
  prefix: 'wdk-abcdef',
  created_at: null,
  last_used_at: null,
  expires_at: null,
}
const STATS: Stats = {
  version: '1.2.3',
  database: { ok: true, elapsed_ms: 3 },
  storage: { ok: true, elapsed_ms: 5 },
  workers: { active: 1, items: [] },
  queue: { queued: 0, running: 0, dead: 0 },
}
const USERS_PAGE: UsersPage = { items: [BASE_USER], total: 1, page: 2, page_size: 25 }

/** Klucz listy z parametrami domyślnymi — mutacje użytkowników mają go unieważniać. */
const LIST_KEY = adminKeys.usersList({ page: 1, pageSize: 25, q: '' })

/** Klient z danymi listy użytkowników. */
function listClient(): QueryClient {
  const client = createClient()
  client.setQueryData(LIST_KEY, [BASE_USER])
  return client
}

describe('zapytania', () => {
  it('usersListQueryOptions wysyła page/page_size i pomija puste q', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/wd/v1/users'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({ data: USERS_PAGE })
      }),
    )

    expect(
      await createClient().fetchQuery(usersListQueryOptions({ page: 2, pageSize: 25, q: '' })),
    ).toEqual(USERS_PAGE)
    expect(seen[0]?.search).toBe('?page=2&page_size=25')

    await createClient().fetchQuery(usersListQueryOptions({ page: 1, pageSize: 25, q: 'jan' }))
    expect(seen[1]?.searchParams.get('q')).toBe('jan')
  })

  it('apiKeysQueryOptions zwraca data.items', async () => {
    let url = ''
    server.use(
      http.get(apiUrl('/api/wd/v1/users/:userId/api-keys'), ({ request }) => {
        url = new URL(request.url).pathname
        return HttpResponse.json({ data: { items: [BASE_KEY] } })
      }),
    )

    expect(await createClient().fetchQuery(apiKeysQueryOptions('u1'))).toEqual([BASE_KEY])
    expect(url).toBe('/api/wd/v1/users/u1/api-keys')
  })

  it('grantsQueryOptions jest wyłączone bez e-maila, inaczej filtruje po email', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/wd/v1/access/assistants'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({ data: { items: [] } })
      }),
    )

    expect(grantsQueryOptions('').enabled).toBe(false)
    expect(grantsQueryOptions('u1@wd.test').enabled).toBe(true)
    await createClient().fetchQuery(grantsQueryOptions('u1@wd.test'))

    expect(seen[0]?.searchParams.get('email')).toBe('u1@wd.test')
  })

  it('statsQueryOptions i healthzQueryOptions odświeżają co STATUS_REFETCH_MS', async () => {
    const health: SystemHealthz = {
      db: 'ok',
      doc_engine: 'ok',
      redis: 'ok',
      status: 'ok',
      storage: 'ok',
    }
    server.use(http.get(apiUrl('/api/wd/v1/stats'), () => HttpResponse.json({ data: STATS })))
    server.use(http.get(apiUrl('/api/v1/system/healthz'), () => HttpResponse.json(health)))

    expect(await createClient().fetchQuery(statsQueryOptions())).toEqual(STATS)
    expect(statsQueryOptions().refetchInterval).toBe(STATUS_REFETCH_MS)
    // healthz to jedyna trasa bez koperty — zwraca surowe ciało.
    expect(await createClient().fetchQuery(healthzQueryOptions())).toEqual(health)
    expect(healthzQueryOptions().refetchInterval).toBe(STATUS_REFETCH_MS)

    server.use(
      http.get(apiUrl('/api/v1/system/healthz'), () =>
        HttpResponse.json({ status: 'fail' }, { status: 500 }),
      ),
    )
    await expect(createClient().fetchQuery(healthzQueryOptions())).rejects.toThrow('healthz')
  })
})

describe('mutacje użytkowników', () => {
  it('useCreateUser wysyła POST, a useUpdateUser PATCH; oba unieważniają adminKeys.users', async () => {
    let createBody: unknown = null
    let patchBody: unknown = null
    let patchPath = ''
    server.use(
      http.post(apiUrl('/api/wd/v1/users'), async ({ request }) => {
        createBody = await request.json()
        return HttpResponse.json({ data: BASE_USER }, { status: 201 })
      }),
      http.patch(apiUrl('/api/wd/v1/users/:userId'), async ({ request }) => {
        patchPath = new URL(request.url).pathname
        patchBody = await request.json()
        return HttpResponse.json({ data: BASE_USER })
      }),
    )
    const client = listClient()
    const create = renderHook(() => useCreateUser(), { wrapper: wrapperFor(client) })
    const update = renderHook(() => useUpdateUser(), { wrapper: wrapperFor(client) })

    const created = await actMutate(() =>
      create.result.current.mutateAsync({ email: 'u2@wd.test', is_superuser: false }),
    )
    await actMutate(() =>
      update.result.current.mutateAsync({ id: 'u1', body: { nickname: 'Nowy' } }),
    )

    expect(createBody).toEqual({ email: 'u2@wd.test', is_superuser: false })
    expect(created).toMatchObject({ id: 'u1' })
    expect(patchPath).toBe('/api/wd/v1/users/u1')
    expect(patchBody).toEqual({ nickname: 'Nowy' })
    expect(client.getQueryState(LIST_KEY)?.isInvalidated).toBe(true)
  })

  it('useSetUserActive wybiera activate/deactivate wg stanu i unieważnia listę', async () => {
    const paths: string[] = []
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/:action'), ({ request }) => {
        paths.push(new URL(request.url).pathname)
        return HttpResponse.json({ data: BASE_USER })
      }),
    )
    const client = listClient()
    const { result } = renderHook(() => useSetUserActive(), { wrapper: wrapperFor(client) })

    await actMutate(() => result.current.mutateAsync({ id: 'u1', active: true }))
    await actMutate(() => result.current.mutateAsync({ id: 'u1', active: false }))

    expect(paths).toEqual(['/api/wd/v1/users/u1/activate', '/api/wd/v1/users/u1/deactivate'])
    expect(client.getQueryState(LIST_KEY)?.isInvalidated).toBe(true)
  })

  it('useSetPassword wysyła POST password, a useDeleteUser DELETE ?mode=cascade', async () => {
    let passwordBody: unknown = null
    let deleteUrl = ''
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/password'), async ({ request }) => {
        passwordBody = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
      http.delete(apiUrl('/api/wd/v1/users/:userId'), ({ request }) => {
        const parsed = new URL(request.url)
        deleteUrl = parsed.pathname + parsed.search
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const client = listClient()
    const password = renderHook(() => useSetPassword(), { wrapper: wrapperFor(client) })
    const deleted = renderHook(() => useDeleteUser(), { wrapper: wrapperFor(client) })

    const out = await actMutate(() =>
      password.result.current.mutateAsync({ id: 'u1', newPassword: 't123' }),
    )
    await actMutate(() => deleted.result.current.mutateAsync({ id: 'u1', mode: 'cascade' }))

    expect(passwordBody).toEqual({ new_password: 't123' })
    expect(out).toBeUndefined()
    expect(deleteUrl).toBe('/api/wd/v1/users/u1?mode=cascade')
    expect(client.getQueryState(LIST_KEY)?.isInvalidated).toBe(true)
  })
})

describe('mutacje kluczy API', () => {
  it('useCreateApiKey oddaje token tylko w mutation.data, useDeleteApiKey unieważnia listę', async () => {
    let createBody: unknown = null
    let deletePath = ''
    const created = { ...BASE_KEY, id: 'k2', token: 'wdk-new-secret' }
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), async ({ request }) => {
        createBody = await request.json()
        return HttpResponse.json({ data: created }, { status: 201 })
      }),
      http.delete(apiUrl('/api/wd/v1/users/:userId/api-keys/:keyId'), ({ request }) => {
        deletePath = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const client = createClient()
    client.setQueryData(adminKeys.apiKeys('u1'), [BASE_KEY])
    const createdHook = renderHook(() => useCreateApiKey('u1'), { wrapper: wrapperFor(client) })
    const deletedHook = renderHook(() => useDeleteApiKey('u1'), { wrapper: wrapperFor(client) })

    await actMutate(() => createdHook.result.current.mutateAsync({ name: 'k' }))
    await actMutate(() => deletedHook.result.current.mutateAsync('k1'))

    expect(createBody).toEqual({ name: 'k' })
    expect(createdHook.result.current.data?.token).toBe('wdk-new-secret')
    expect(JSON.stringify(client.getQueryData(adminKeys.apiKeys('u1')))).not.toContain('secret')
    expect(deletePath).toBe('/api/wd/v1/users/u1/api-keys/k1')
    expect(client.getQueryState(adminKeys.apiKeys('u1'))?.isInvalidated).toBe(true)
  })
})

describe('useReplaceGrants', () => {
  it('wysyła PUT z email i chat_ids oraz unieważnia granty e-maila', async () => {
    let body: unknown = null
    server.use(
      http.put(apiUrl('/api/wd/v1/access/assistants'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ data: { email: 'u1@wd.test', count: 1 } })
      }),
    )
    const client = createClient()
    client.setQueryData(adminKeys.grants('u1@wd.test'), [])
    const { result } = renderHook(() => useReplaceGrants(), { wrapper: wrapperFor(client) })

    await actMutate(() => result.current.mutateAsync({ email: 'u1@wd.test', chatIds: ['c1'] }))

    expect(body).toEqual({ email: 'u1@wd.test', chat_ids: ['c1'] })
    expect(client.getQueryState(adminKeys.grants('u1@wd.test'))?.isInvalidated).toBe(true)
  })
})
