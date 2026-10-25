import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import {
  sessionKeys,
  sessionQueryOptions,
  sessionsListQueryOptions,
  useDeleteSessions,
  useMessageFeedback,
  useRenameSession,
} from './sessionQueries'
import type { Session } from './sessionQueries'

afterEach(cleanup)

function sessionFixture(overrides: Partial<Session> = {}): Session {
  return {
    chat_id: 'chat-1',
    create_date: '2025-01-01 00:00:00',
    create_time: 1735689600000,
    id: 'session-1',
    name: 'Sesja A',
    update_date: '2025-01-01 00:00:00',
    update_time: 1735689600000,
    user_id: 'u1',
    messages: [{ role: 'assistant', content: 'prologue' }],
    reference: [],
    ...overrides,
  }
}

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

// Sonda RTL: lista sesji renderowana w prawdziwym drzewie (MSW + QueryClient z `renderWithProviders`).
function SessionsProbe({ chatId }: { chatId: string }) {
  const sessions = useQuery(sessionsListQueryOptions(chatId))
  return <span>{sessions.data?.map((session) => session.name).join(',')}</span>
}

describe('sessionKeys', () => {
  it('buduje klucze listy i szczegółu pod czatem', () => {
    expect(sessionKeys.all('chat-1')).toEqual(['chats', 'sessions', 'chat-1'])
    expect(sessionKeys.list('chat-1')).toEqual(['chats', 'sessions', 'chat-1', 'list'])
    expect(sessionKeys.detail('chat-1', 'session-1')).toEqual([
      'chats',
      'sessions',
      'chat-1',
      'detail',
      'session-1',
    ])
    expect(sessionsListQueryOptions('chat-1').queryKey).toEqual(sessionKeys.list('chat-1'))
    expect(sessionQueryOptions('chat-1', 'session-1').queryKey).toEqual(
      sessionKeys.detail('chat-1', 'session-1'),
    )
  })
})

describe('sessionsListQueryOptions', () => {
  it('pobiera listę z page_size=1000, orderby=update_time i desc=true', async () => {
    const session = sessionFixture()
    let seen: URL | null = null
    server.use(
      http.get(apiUrl('/api/v1/chats/:chatId/sessions'), ({ request }) => {
        seen = new URL(request.url)
        return HttpResponse.json({ code: 0, message: 'success', data: [session] })
      }),
    )

    const items = await createClient().fetchQuery(sessionsListQueryOptions('chat-1'))

    expect(items).toEqual([session])
    expect(seen!.pathname).toBe('/api/v1/chats/chat-1/sessions')
    expect(seen!.searchParams.get('page_size')).toBe('1000')
    expect(seen!.searchParams.get('orderby')).toBe('update_time')
    expect(seen!.searchParams.get('desc')).toBe('true')
  })

  it('renderuje listę sesji przez RTL', async () => {
    server.use(
      http.get(apiUrl('/api/v1/chats/:chatId/sessions'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: [
            sessionFixture({ id: 's-1', name: 'Alfa' }),
            sessionFixture({ id: 's-2', name: 'Beta' }),
          ],
        }),
      ),
    )

    const { findByText } = await renderWithProviders(<SessionsProbe chatId="chat-1" />)

    expect(await findByText('Alfa,Beta')).toBeInTheDocument()
  })

  it('rzuca ApiError przy kopercie code ≠ 0', async () => {
    server.use(
      http.get(apiUrl('/api/v1/chats/:chatId/sessions'), () =>
        HttpResponse.json({ code: 102, message: 'brak sesji', data: null }),
      ),
    )

    await expect(createClient().fetchQuery(sessionsListQueryOptions('chat-1'))).rejects.toThrow(
      'brak sesji',
    )
  })
})

describe('sessionQueryOptions', () => {
  it('pobiera szczegół sesji po id', async () => {
    const detail = sessionFixture({ id: 'session-7', name: 'Gamma' })
    let path = ''
    server.use(
      http.get(apiUrl('/api/v1/chats/:chatId/sessions/:sessionId'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: detail })
      }),
    )

    const session = await createClient().fetchQuery(sessionQueryOptions('chat-1', 'session-7'))

    expect(session).toEqual(detail)
    expect(path).toBe('/api/v1/chats/chat-1/sessions/session-7')
  })
})

describe('useRenameSession', () => {
  it('wysyła PATCH i unieważnia sessionKeys.all(chatId)', async () => {
    let body: unknown = null
    let path = ''
    server.use(
      http.patch(apiUrl('/api/v1/chats/:chatId/sessions/:sessionId'), async ({ request }) => {
        body = await request.json()
        path = new URL(request.url).pathname
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: sessionFixture({ name: 'Nowa' }),
        })
      }),
    )
    const client = createClient()
    client.setQueryData(sessionKeys.list('chat-1'), [sessionFixture()])
    const { result } = renderHook(() => useRenameSession('chat-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ sessionId: 'session-1', name: 'Nowa' })
    })

    expect(path).toBe('/api/v1/chats/chat-1/sessions/session-1')
    expect(body).toEqual({ name: 'Nowa' })
    expect(client.getQueryState(sessionKeys.list('chat-1'))?.isInvalidated).toBe(true)
  })
})

describe('useDeleteSessions', () => {
  it('wysyła DELETE {ids} i unieważnia sessionKeys.all(chatId)', async () => {
    let body: unknown = null
    server.use(
      http.delete(apiUrl('/api/v1/chats/:chatId/sessions'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { success_count: 1, errors: null },
        })
      }),
    )
    const client = createClient()
    client.setQueryData(sessionKeys.list('chat-1'), [sessionFixture()])
    const { result } = renderHook(() => useDeleteSessions('chat-1'), {
      wrapper: wrapperFor(client),
    })

    let deleted: unknown
    await act(async () => {
      deleted = await result.current.mutateAsync(['session-1'])
    })

    expect(body).toEqual({ ids: ['session-1'] })
    expect(deleted).toEqual({ success_count: 1, errors: null })
    expect(client.getQueryState(sessionKeys.list('chat-1'))?.isInvalidated).toBe(true)
  })
})

describe('useMessageFeedback', () => {
  it('wysyła PUT na wiadomość i unieważnia sessionKeys.detail', async () => {
    let body: unknown = null
    let path = ''
    server.use(
      http.put(
        apiUrl('/api/v1/chats/:chatId/sessions/:sessionId/messages/:messageId/feedback'),
        async ({ request }) => {
          body = await request.json()
          path = new URL(request.url).pathname
          return HttpResponse.json({ code: 0, message: 'success', data: sessionFixture() })
        },
      ),
    )
    const client = createClient()
    client.setQueryData(sessionKeys.detail('chat-1', 'session-1'), sessionFixture())
    const { result } = renderHook(() => useMessageFeedback('chat-1', 'session-1'), {
      wrapper: wrapperFor(client),
    })

    await act(async () => {
      await result.current.mutateAsync({ messageId: 'msg-1', thumbup: false, feedback: 'nie tak' })
    })

    expect(path).toBe('/api/v1/chats/chat-1/sessions/session-1/messages/msg-1/feedback')
    expect(body).toEqual({ thumbup: false, feedback: 'nie tak' })
    expect(client.getQueryState(sessionKeys.detail('chat-1', 'session-1'))?.isInvalidated).toBe(
      true,
    )
  })
})
