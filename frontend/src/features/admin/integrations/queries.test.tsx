/**
 * Warstwa danych integracji (kontrakt WP E4-3c §1): kształt zapytań, kursory przebiegów
 * i zdarzeń, odpytywanie statusu oraz unieważnianie cache po mutacjach. Stan MSW pochodzi
 * z prawdziwych handlerów `integrationsHandlers(seed)` (kontrakt §3).
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  integrationsHandlers,
  makeEvent,
  makeIntegration,
  makeRun,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import {
  INTEGRATIONS_PAGE_SIZE,
  integrationDrivesQueryOptions,
  integrationKeys,
  integrationQueryOptions,
  integrationRunsQueryOptions,
  integrationStatusQueryOptions,
  integrationsListQueryOptions,
  runEventsQueryOptions,
  useCancelIntegration,
  useCreateIntegration,
  useDeleteIntegration,
  useSyncIntegration,
  useTestConnection,
  useTestSavedConnection,
  useUpdateIntegration,
} from './queries'
import { DEFAULT_FORM_VALUES, toCreateBody, toTestBody } from './schema'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

async function actMutate<T>(run: () => Promise<T>): Promise<T> {
  let out!: T
  await act(async () => {
    out = await run()
  })
  return out
}

/** Ciało zapisu bierzemy z `toCreateBody`, żeby testy nie dublowały mapowania formularza. */
const CREATE_BODY = toCreateBody({
  ...DEFAULT_FORM_VALUES,
  name: 'Zespołowa',
  dataset_id: 'ds-9',
  tenant_id: 'tenant-test',
  client_id: 'client-9',
  client_secret: 'sekret-9',
  site_url: 'https://example.invalid/sites/nowa',
})

describe('zapytania', () => {
  it('lista zwraca items malejąco po id', async () => {
    server.use(
      ...integrationsHandlers({
        integrations: [makeIntegration({ id: 1 }), makeIntegration({ id: 2, dataset_id: 'ds-2' })],
      }),
    )

    const rows = await createClient().fetchQuery(integrationsListQueryOptions())

    expect(rows.map((row) => row.id)).toEqual([2, 1])
  })

  it('lista pyta o pierwszą stronę w rozmiarze INTEGRATIONS_PAGE_SIZE', async () => {
    let search = ''
    server.use(
      http.get(apiUrl('/api/wd/v1/integrations'), ({ request }) => {
        search = new URL(request.url).search
        return HttpResponse.json({
          data: { items: [], total: 0, page: 1, page_size: INTEGRATIONS_PAGE_SIZE },
        })
      }),
    )

    expect(await createClient().fetchQuery(integrationsListQueryOptions())).toEqual([])
    expect(search).toBe(`?page=1&page_size=${INTEGRATIONS_PAGE_SIZE}`)
  })

  it('szczegóły integracji i biblioteki: brak id wyłącza zapytanie, nieznany id rzuca', async () => {
    server.use(...integrationsHandlers({ integrations: [makeIntegration({ id: 2 })] }))
    const client = createClient()

    expect(integrationDrivesQueryOptions(0).enabled).toBe(false)
    expect(integrationDrivesQueryOptions(2).enabled).toBe(true)

    await expect(client.fetchQuery(integrationQueryOptions(99))).rejects.toThrow(
      'Nie ma takiej integracji',
    )
    expect((await client.fetchQuery(integrationQueryOptions(2))).id).toBe(2)
    expect(await client.fetchQuery(integrationDrivesQueryOptions(2))).toEqual([])
  })

  it('runs zwraca kursor malejąco, a events rosnąco z filtrem poziomu', async () => {
    server.use(
      ...integrationsHandlers({
        integrations: [makeIntegration({ id: 1 })],
        runs: { 1: [makeRun({ id: 10 }), makeRun({ id: 11 }), makeRun({ id: 12 })] },
        events: {
          12: [
            makeEvent({ id: 1, run_id: 12 }),
            makeEvent({ id: 2, run_id: 12, level: 'warning' }),
            makeEvent({ id: 3, run_id: 12, level: 'error' }),
          ],
        },
      }),
    )
    const client = createClient()

    const runs = await client.fetchQuery(integrationRunsQueryOptions(1))
    expect(runs.items.map((run) => run.id)).toEqual([12, 11, 10])
    expect(runs.next_after_id).toBeNull()

    const errors = await client.fetchQuery(runEventsQueryOptions(12, 'error'))
    expect(errors.items.map((event) => event.id)).toEqual([3])

    const all = await client.fetchQuery(runEventsQueryOptions(12, ''))
    expect(all.items.map((event) => event.id)).toEqual([1, 2, 3])
  })
})

describe('mutacje', () => {
  it('create nadaje id od max+1 i unieważnia prefiks integracji', async () => {
    server.use(...integrationsHandlers({ integrations: [makeIntegration({ id: 3 })] }))
    const client = createClient()
    client.setQueryData(integrationKeys.list, [makeIntegration({ id: 3 })])
    const { result } = renderHook(() => useCreateIntegration(), { wrapper: wrapperFor(client) })

    const created = await actMutate(() => result.current.mutateAsync({ ...CREATE_BODY }))

    expect(created.id).toBe(4)
    expect(client.getQueryState(integrationKeys.list)?.isInvalidated).toBe(true)
  })

  it('create na zajętym datasecie kończy się konfliktem', async () => {
    server.use(
      ...integrationsHandlers({ integrations: [makeIntegration({ id: 1, dataset_id: 'ds-1' })] }),
    )
    const { result } = renderHook(() => useCreateIntegration(), {
      wrapper: wrapperFor(createClient()),
    })

    await expect(
      actMutate(() => result.current.mutateAsync({ ...CREATE_BODY, dataset_id: 'ds-1' })),
    ).rejects.toThrow('Ten dataset ma już integrację')
  })

  it('update zmienia pola, a delete nie zwraca ciała — oba unieważniają prefiks', async () => {
    server.use(...integrationsHandlers({ integrations: [makeIntegration({ id: 2 })] }))
    const client = createClient()
    client.setQueryData(integrationKeys.list, [])
    const update = renderHook(() => useUpdateIntegration(2), { wrapper: wrapperFor(client) })
    const remove = renderHook(() => useDeleteIntegration(), { wrapper: wrapperFor(client) })

    expect(
      await actMutate(() => update.result.current.mutateAsync({ name: 'Nowa nazwa' })),
    ).toMatchObject({ name: 'Nowa nazwa' })
    expect(await actMutate(() => remove.result.current.mutateAsync(2))).toBeUndefined()
    expect(client.getQueryState(integrationKeys.list)?.isInvalidated).toBe(true)
  })

  it('delete czyści zapytania usuniętego zasobu i unieważnia tylko listę', async () => {
    server.use(
      ...integrationsHandlers({
        integrations: [makeIntegration({ id: 7 }), makeIntegration({ id: 2, dataset_id: 'ds-2' })],
      }),
    )
    const client = createClient()
    // Cache obu integracji: rodzina detalu (szczegóły, status, biblioteki, przebiegi) i zdarzenia
    // przebiegu — usunięcie siódemki nie może ruszyć dwójki.
    for (const id of [7, 2]) {
      client.setQueryData(integrationKeys.detail(id), makeIntegration({ id }))
      client.setQueryData(integrationKeys.status(id), { id, is_running: false })
      client.setQueryData(integrationKeys.drives(id), [])
      client.setQueryData(integrationKeys.runs(id), {
        items: [makeRun({ id: id * 10 })],
        next_after_id: null,
      })
      client.setQueryData(integrationKeys.events(id * 10, 'info'), {
        items: [makeEvent({ id: id * 10, run_id: id * 10, integration_id: id })],
        next_after_id: null,
      })
    }
    client.setQueryData(integrationKeys.list, [])
    const remove = renderHook(() => useDeleteIntegration(), { wrapper: wrapperFor(client) })

    expect(await actMutate(() => remove.result.current.mutateAsync(7))).toBeUndefined()

    // Zapytania usuniętej integracji znikają z cache...
    expect(client.getQueryState(integrationKeys.detail(7))).toBeUndefined()
    expect(client.getQueryState(integrationKeys.status(7))).toBeUndefined()
    expect(client.getQueryState(integrationKeys.drives(7))).toBeUndefined()
    expect(client.getQueryState(integrationKeys.runs(7))).toBeUndefined()
    expect(client.getQueryState(integrationKeys.events(70, 'info'))).toBeUndefined()
    // ...a drugiej integracji zostają nietknięte...
    expect(client.getQueryState(integrationKeys.detail(2))).toBeDefined()
    expect(client.getQueryState(integrationKeys.status(2))).toBeDefined()
    expect(client.getQueryState(integrationKeys.runs(2))).toBeDefined()
    expect(client.getQueryState(integrationKeys.events(20, 'info'))).toBeDefined()
    // ...a lista jest unieważniona, żeby odświeżyła się bez tras usuniętego zasobu.
    expect(client.getQueryState(integrationKeys.list)?.isInvalidated).toBe(true)
  })

  it('test połączenia zwraca graph_auth failed tylko dla tenanta „bad”', async () => {
    server.use(...integrationsHandlers())
    const { result } = renderHook(() => useTestConnection(), {
      wrapper: wrapperFor(createClient()),
    })
    const body = toTestBody({ ...DEFAULT_FORM_VALUES, tenant_id: 'bad' })

    const bad = await actMutate(() => result.current.mutateAsync(body))
    const good = await actMutate(() =>
      result.current.mutateAsync({ ...body, tenant_id: 'tenant-test' }),
    )

    expect(bad).toMatchObject({ graph_auth: 'failed', site_resolution: 'skipped' })
    expect(bad.graph_auth_error).toBe('Invalid tenant')
    expect(good).toMatchObject({ graph_auth: 'ok', dataset_exists: 'ok' })
  })

  it('test zapisanej integracji nie wymaga ciała', async () => {
    server.use(
      ...integrationsHandlers({ integrations: [makeIntegration({ id: 2, tenant_id: 'bad' })] }),
    )
    const { result } = renderHook(() => useTestSavedConnection(2), {
      wrapper: wrapperFor(createClient()),
    })

    expect(await actMutate(() => result.current.mutateAsync({}))).toMatchObject({
      graph_auth: 'failed',
    })
  })

  it('sync ustawia is_running i unieważnia status oraz przebiegi', async () => {
    server.use(...integrationsHandlers({ integrations: [makeIntegration({ id: 7 })] }))
    const client = createClient()
    client.setQueryData(integrationKeys.status(7), { id: 7, is_running: false })
    client.setQueryData(integrationKeys.list, [])
    const { result } = renderHook(() => useSyncIntegration(7), { wrapper: wrapperFor(client) })

    expect(await actMutate(() => result.current.mutateAsync({ full: false }))).toEqual({
      queued: true,
    })
    // Unieważnienie czytamy przed odświeżeniem — udane `fetchQuery` zeruje ten znacznik.
    expect(client.getQueryState(integrationKeys.status(7))?.isInvalidated).toBe(true)
    expect(client.getQueryState(integrationKeys.list)?.isInvalidated).toBe(true)
    expect((await client.fetchQuery(integrationStatusQueryOptions(7))).is_running).toBe(true)
  })

  it('cancel gasi is_running i unieważnia przebiegi', async () => {
    server.use(
      ...integrationsHandlers({ integrations: [makeIntegration({ id: 7, is_running: true })] }),
    )
    const client = createClient()
    client.setQueryData(integrationKeys.runs(7), { items: [], next_after_id: null })
    const { result } = renderHook(() => useCancelIntegration(7), { wrapper: wrapperFor(client) })

    expect(await actMutate(() => result.current.mutateAsync())).toEqual({ cancelled: true })
    expect((await client.fetchQuery(integrationStatusQueryOptions(7))).is_running).toBe(false)
    expect(client.getQueryState(integrationKeys.runs(7))?.isInvalidated).toBe(true)
  })
})
