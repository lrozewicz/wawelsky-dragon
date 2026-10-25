import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { apiUrl } from './common'

// Pełny wiersz listy czatów (ChatListItem z backend/openapi.json) — wartości jak w złocie
// backend/tests/contract/golden/v0.27.2/chats/chat_session--02.json.
export type FixtureChatListItem = {
  create_time: number
  dataset_ids: string[]
  description: string
  do_refer: string
  icon: string
  id: string
  kb_names: string[]
  language: string
  llm_id: string
  llm_setting: Record<string, unknown>
  name: string
  nickname: string
  prompt_config: Record<string, unknown>
  prompt_type: string
  rerank_candidates_count: number
  rerank_id: string
  similarity_threshold: number
  status: string
  tenant_avatar: string | null
  tenant_id: string
  top_k: number
  top_n: number
  update_time: number
  vector_similarity_weight: number
}

// Szczegół czatu (Chat z backend/openapi.json) — wiersz listy plus pola ze złota chat_session--01.json.
export type FixtureChatDetail = FixtureChatListItem & {
  create_date: string
  update_date: string
  meta_data_filter: Record<string, unknown>
  tenant_llm_id: string | null
  tenant_rerank_id: string | null
}

/** Znacznik czasu czatów (ms epoki — `present/common.ts:ts`). */
export const CHAT_TIMESTAMP = 1735689600000

const chatListItemDefaults: FixtureChatListItem = {
  create_time: CHAT_TIMESTAMP,
  dataset_ids: [],
  description: 'A helpful Assistant',
  do_refer: '1',
  icon: '',
  id: 'chat-1',
  kb_names: [],
  language: 'English',
  llm_id: 'fake-llm',
  llm_setting: {},
  name: 'wd_rec_chat',
  nickname: 'recorder',
  prompt_config: {
    empty_response: 'Sorry! No relevant content was found in the knowledge base!',
    parameters: [
      { key: 'knowledge', optional: false },
      { key: 'date', optional: true },
    ],
    prologue: "Hi! I'm your assistant. What can I do for you?",
    quote: true,
    refine_multiturn: true,
    system: '',
    tts: false,
  },
  prompt_type: 'simple',
  rerank_candidates_count: 64,
  rerank_id: '',
  similarity_threshold: 0.1,
  status: '1',
  tenant_avatar: null,
  tenant_id: 'tenant-1',
  top_k: 1024,
  top_n: 6,
  update_time: CHAT_TIMESTAMP,
  vector_similarity_weight: 0.3,
}

export function chatListItem(overrides: Partial<FixtureChatListItem> = {}): FixtureChatListItem {
  return { ...chatListItemDefaults, ...overrides }
}

export function chatDetail(overrides: Partial<FixtureChatDetail> = {}): FixtureChatDetail {
  return {
    ...chatListItemDefaults,
    create_date: '2025-01-01 00:00:00',
    update_date: '2025-01-01 00:00:00',
    meta_data_filter: {},
    tenant_llm_id: 'fake-llm',
    tenant_rerank_id: null,
    ...overrides,
  }
}

/**
 * Handlery czatów z pamięcią stanu: `POST` dopisuje, `PATCH` scala pola, `DELETE {ids}` usuwa —
 * testy dostają spójną listę bez własnych stubów. Każde wywołanie `chatsHandlers(...)` daje świeży
 * stan, a `server.resetHandlers()` w `src/test/setup.ts` wraca do stanu początkowego między testami.
 */
export function chatsHandlers(initialChats: FixtureChatListItem[] = []): HttpHandler[] {
  let store = initialChats.map((chat) => ({ ...chat }))
  let nextId = store.length + 1

  return [
    http.get(apiUrl('/api/v1/chats'), () =>
      HttpResponse.json({
        code: 0,
        message: 'success',
        data: { chats: store, total: store.length },
      }),
    ),

    http.get(apiUrl('/api/v1/chats/:chatId'), ({ params }) => {
      const chat = store.find((item) => item.id === params.chatId)
      if (chat === undefined) {
        return HttpResponse.json({ code: 102, message: 'Chat not found', data: null })
      }
      return HttpResponse.json({ code: 0, message: 'success', data: chatDetail(chat) })
    }),

    http.post(apiUrl('/api/v1/chats'), async ({ request }) => {
      const body = (await request.json()) as {
        name?: string
        prompt_config?: Record<string, unknown>
      }
      // Backend (POST) łączy częściowe `prompt_config` z domyślnym (`apply_prompt_defaults`,
      // DEC-358) — handler robi to samo, żeby szczegół utworzonego czatu odzwierciedlał ciało
      // żądania (K20 §5 p. 3: UI wysyła `{prologue, empty_response}` w języku UI).
      const created = chatDetail({
        id: `chat-${nextId}`,
        name: body.name ?? '',
        prompt_config: { ...chatListItemDefaults.prompt_config, ...(body.prompt_config ?? {}) },
      })
      nextId += 1
      store = [...store, created]
      return HttpResponse.json({ code: 0, message: 'success', data: created })
    }),

    http.patch(apiUrl('/api/v1/chats/:chatId'), async ({ request, params }) => {
      const body = (await request.json()) as Partial<FixtureChatListItem>
      const existing = store.find((item) => item.id === params.chatId)
      if (existing === undefined) {
        return HttpResponse.json({ code: 102, message: 'Chat not found', data: null })
      }
      const updated = { ...existing, ...body }
      store = store.map((item) => (item.id === updated.id ? updated : item))
      return HttpResponse.json({ code: 0, message: 'success', data: chatDetail(updated) })
    }),

    http.delete(apiUrl('/api/v1/chats'), async ({ request }) => {
      const body = (await request.json()) as { ids?: string[] }
      const ids = body.ids ?? []
      store = store.filter((item) => !ids.includes(item.id))
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: { success_count: ids.length, errors: null },
      })
    }),
  ]
}
