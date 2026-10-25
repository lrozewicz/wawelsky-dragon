import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, chatDetail, chatListItem } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import {
  chatKeys,
  chatQueryOptions,
  chatsListQueryOptions,
  useCreateChat,
  useDeleteChats,
  useUpdateChat,
} from './queries'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

/** Otoczka hooków mutacji — każdy test dostaje własny klient, żeby widzieć własne unieważnienia. */
function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const CHAT_LIST_ITEM = chatListItem({ id: 'chat-1', name: 'Alfa' })

describe('chatsListQueryOptions', () => {
  it('rozpakowuje {chats, total} i nie wysyła filtra bez parametrów', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/v1/chats'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { chats: [CHAT_LIST_ITEM], total: 1 },
        })
      }),
    )

    const items = await createClient().fetchQuery(chatsListQueryOptions())

    expect(items).toEqual([CHAT_LIST_ITEM])
    expect(seen[0]?.searchParams.get('name')).toBeNull()
  })

  it('filtr nazwy trafia do zapytania i do klucza', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/v1/chats'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({ code: 0, message: 'success', data: { chats: [], total: 0 } })
      }),
    )

    expect(chatsListQueryOptions({ name: 'Alfa' }).queryKey).toEqual(
      chatKeys.list({ name: 'Alfa' }),
    )
    await createClient().fetchQuery(chatsListQueryOptions({ name: 'Alfa' }))

    expect(seen[0]?.searchParams.get('name')).toBe('Alfa')
  })

  it('rzuca ApiError przy kopercie code ≠ 0', async () => {
    server.use(
      http.get(apiUrl('/api/v1/chats'), () =>
        HttpResponse.json({ code: 101, message: 'boom', data: false }),
      ),
    )

    await expect(createClient().fetchQuery(chatsListQueryOptions())).rejects.toThrow('boom')
  })
})

describe('chatQueryOptions', () => {
  it('pobiera szczegół czatu po id', async () => {
    const detail = chatDetail({ id: 'chat-7', name: 'Gamma' })
    let path = ''
    server.use(
      http.get(apiUrl('/api/v1/chats/:chatId'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: detail })
      }),
    )

    const chat = await createClient().fetchQuery(chatQueryOptions('chat-7'))

    expect(chat).toEqual(detail)
    expect(path).toBe('/api/v1/chats/chat-7')
    expect(chatQueryOptions('chat-7').queryKey).toEqual(chatKeys.detail('chat-7'))
  })
})

describe('useCreateChat', () => {
  it('wysyła nazwę z domyślnymi tekstami w języku UI i unieważnia chatKeys.all', async () => {
    let body: unknown = null
    server.use(
      http.post(apiUrl('/api/v1/chats'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: chatDetail({ id: 'chat-2', name: 'Nowy' }),
        })
      }),
    )
    const client = createClient()
    client.setQueryData(chatKeys.list(), [CHAT_LIST_ITEM])
    const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(client) })

    let created: unknown
    await act(async () => {
      created = await result.current.mutateAsync({
        name: 'Nowy',
        description: 'Pomocny asystent',
        prologue: 'Cześć! Jestem Twoim asystentem. W czym mogę pomóc?',
        emptyResponse: 'Nie znaleziono pasujących treści w bazie wiedzy.',
      })
    })

    // K4/DEC-306 + K20 §5 p. 3/DEC-358: opis, powitanie i odpowiedź przy braku wyników idą
    // w ciele żądania; pozostałe klucze prompt_config uzupełnia backend wartościami domyślnymi
    // (`apply_prompt_defaults` łączy częściowe `prompt_config` z domyślnym).
    expect(body).toEqual({
      name: 'Nowy',
      description: 'Pomocny asystent',
      prompt_config: {
        prologue: 'Cześć! Jestem Twoim asystentem. W czym mogę pomóc?',
        empty_response: 'Nie znaleziono pasujących treści w bazie wiedzy.',
      },
    })
    expect(created).toMatchObject({ id: 'chat-2', name: 'Nowy' })
    expect(client.getQueryState(chatKeys.list())?.isInvalidated).toBe(true)
  })

  it('z wybranymi bazami wysyła dataset_ids w ciele (SC-V13-10)', async () => {
    let body: unknown = null
    server.use(
      http.post(apiUrl('/api/v1/chats'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: chatDetail({ id: 'chat-3', name: 'Z bazą' }),
        })
      }),
    )
    const client = createClient()
    const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({
        name: 'Z bazą',
        description: 'd',
        prologue: 'p',
        emptyResponse: 'e',
        datasetIds: ['ds-1', 'ds-2'],
      })
    })

    expect(body).toMatchObject({ dataset_ids: ['ds-1', 'ds-2'] })
  })

  it('pusta lista baz nie dodaje klucza dataset_ids (CONTRACT §4: tylko gdy wybrano)', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post(apiUrl('/api/v1/chats'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: chatDetail({ id: 'chat-4', name: 'Bez baz' }),
        })
      }),
    )
    const client = createClient()
    const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({
        name: 'Bez baz',
        description: 'd',
        prologue: 'p',
        emptyResponse: 'e',
        datasetIds: [],
      })
    })

    expect(body).toEqual({
      name: 'Bez baz',
      description: 'd',
      prompt_config: { prologue: 'p', empty_response: 'e' },
    })
  })

  it('błąd koperty zostawia zapytania bez zmian', async () => {
    server.use(
      http.post(apiUrl('/api/v1/chats'), () =>
        HttpResponse.json({ code: 109, message: 'duplikat', data: false }),
      ),
    )
    const client = createClient()
    client.setQueryData(chatKeys.list(), [CHAT_LIST_ITEM])
    const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(client) })

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          name: 'Nowy',
          description: 'd',
          prologue: 'p',
          emptyResponse: 'e',
        }),
      ).rejects.toThrow('duplikat')
    })

    expect(client.getQueryState(chatKeys.list())?.isInvalidated).toBe(false)
  })
})

describe('useUpdateChat', () => {
  it('wysyła PATCH na id czatu i unieważnia chatKeys.all', async () => {
    let body: unknown = null
    let path = ''
    server.use(
      http.patch(apiUrl('/api/v1/chats/:chatId'), async ({ request }) => {
        body = await request.json()
        path = new URL(request.url).pathname
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: chatDetail({ id: 'chat-1', name: 'Beta' }),
        })
      }),
    )
    const client = createClient()
    client.setQueryData(chatKeys.detail('chat-1'), chatDetail({ id: 'chat-1' }))
    const { result } = renderHook(() => useUpdateChat('chat-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ name: 'Beta' })
    })

    expect(path).toBe('/api/v1/chats/chat-1')
    expect(body).toEqual({ name: 'Beta' })
    expect(client.getQueryState(chatKeys.detail('chat-1'))?.isInvalidated).toBe(true)
  })
})

describe('useDeleteChats', () => {
  it('wysyła DELETE {ids} i unieważnia chatKeys.all', async () => {
    let body: unknown = null
    server.use(
      http.delete(apiUrl('/api/v1/chats'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { success_count: 1, errors: null },
        })
      }),
    )
    const client = createClient()
    client.setQueryData(chatKeys.list(), [CHAT_LIST_ITEM])
    const { result } = renderHook(() => useDeleteChats(), { wrapper: wrapperFor(client) })

    let deleted: unknown
    await act(async () => {
      deleted = await result.current.mutateAsync(['chat-1'])
    })

    expect(body).toEqual({ ids: ['chat-1'] })
    expect(deleted).toEqual({ success_count: 1, errors: null })
    expect(client.getQueryState(chatKeys.list())?.isInvalidated).toBe(true)
  })
})
