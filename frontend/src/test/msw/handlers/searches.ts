import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type { SearchApp, SearchListItem } from '../../../features/searches/queries'

import { apiUrl } from './common'

/** Znacznik czasu wyszukiwarek w fixture'ach (ms epoki — jak `CHAT_TIMESTAMP`). */
export const SEARCH_TIMESTAMP = 1735689600000

/** Data tekstowa zwracana przez `searches_update` (kolumna `create_date`/`update_date`). */
const SEARCH_DATE = '2025-01-01 00:00:00'

export type FixtureSearchApp = SearchApp

/**
 * Domyślna wyszukiwarka magazynu (kontrakt WP E4-4b §6): `search_config` niesie klucz `use_kg`
 * nieobsługiwany przez UI — testy pilnują, że zapis go nie gubi.
 */
export const searchFixtureApp: SearchApp = {
  id: 'search-1',
  name: 'Wyszukiwarka testowa',
  description: 'Wyszukiwarka demonstracyjna',
  avatar: null,
  created_by: 'user-1',
  tenant_id: 'tenant-1',
  update_time: SEARCH_TIMESTAMP,
  search_config: {
    kb_ids: ['ds-1'],
    summary: true,
    chat_id: 'fake-chat',
    related_search: true,
    similarity_threshold: 0.2,
    vector_similarity_weight: 0.3,
    use_kg: false,
    llm_setting: { parameter: 'precise', temperature: 0.2 },
  },
}

/** Wiersz listy bez `search_config` (operacja `searches_list`). */
function toListItem(app: SearchApp): SearchListItem {
  return {
    id: app.id,
    name: app.name,
    description: app.description,
    avatar: app.avatar,
    created_by: app.created_by,
    tenant_id: app.tenant_id,
    create_time: app.update_time,
    update_time: app.update_time,
    nickname: 'recorder',
    status: '1',
    tenant_avatar: null,
  }
}

function cloneApp(app: SearchApp): SearchApp {
  return { ...app, search_config: { ...app.search_config } }
}

// Stan w pamięci modułu: `searchesHandlers()` wołane wielokrotnie (domyślne `handlers` i
// `server.use(...)`) dzieli ten sam magazyn, a `resetSearchesFixtures()` wraca do ziarna.
let store: SearchApp[] = [cloneApp(searchFixtureApp)]
let nextId = 2

/** Przywraca magazyn do stanu początkowego (jedna wyszukiwarka — `searchFixtureApp`). */
export function resetSearchesFixtures(): void {
  store = [cloneApp(searchFixtureApp)]
  nextId = 2
}

const SSE_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8' }

/** Ramka SSE w kopercie RAGFlow — kodowanie `data:{json}\n\n` bez spacji. */
function frame(data: unknown): string {
  return `data:${JSON.stringify({ code: 0, message: '', data })}\n\n`
}

// Jedno trafienie podsumowania: `[ID:0]` z delty wskazuje na nie indeksem.
const SUMMARY_CHUNK = {
  id: 'chunk-1',
  content: 'Legenda o smoku wawelskim należy do najstarszych opowieści Krakowa.',
  document_id: 'doc-1',
  document_name: 'ragflow_intro.txt',
  dataset_id: 'ds-1',
  image_id: '',
  positions: [[1, 0, 0, 0, 0]],
  url: null,
  similarity: 0.85,
  vector_similarity: 0.9,
  term_similarity: 0.7,
  row_id: null,
  doc_type: '',
  document_metadata: null,
}

function summaryStream(): string {
  return [
    frame({ answer: 'Odpowiedź na podstawie źródeł [ID:0]', reference: {}, final: false }),
    frame({
      answer: '',
      reference: {
        total: 1,
        chunks: [SUMMARY_CHUNK],
        doc_aggs: [{ doc_name: 'ragflow_intro.txt', doc_id: 'doc-1', count: 1 }],
      },
      final: true,
    }),
    frame(true),
  ].join('')
}

/**
 * Handlery wyszukiwarek (kontrakt WP E4-4b §6): CRUD `searches`, SSE podsumowania i rekomendacje
 * pytań. `POST /api/v1/retrieval` obsługuje `retrievalHandlers` — tutaj go nie dublujemy.
 */
export function searchesHandlers(): HttpHandler[] {
  return [
    http.get(apiUrl('/api/v1/searches'), () =>
      HttpResponse.json({
        code: 0,
        message: '',
        data: { search_apps: store.map(toListItem), total: store.length },
      }),
    ),

    http.post(apiUrl('/api/v1/searches'), async ({ request }) => {
      const body = (await request.json()) as { name?: string }
      const created: SearchApp = {
        ...cloneApp(searchFixtureApp),
        id: `search-${nextId}`,
        name: body.name ?? '',
        search_config: {},
      }
      nextId += 1
      store = [...store, created]
      return HttpResponse.json({ code: 0, message: '', data: { search_id: created.id } })
    }),

    http.get(apiUrl('/api/v1/searches/:searchId'), ({ params }) => {
      const app = store.find((item) => item.id === params.searchId)
      if (app === undefined) {
        return HttpResponse.json({ code: 103, message: 'Search not found', data: false })
      }
      return HttpResponse.json({ code: 0, message: '', data: app })
    }),

    http.put(apiUrl('/api/v1/searches/:searchId'), async ({ request, params }) => {
      const body = (await request.json()) as {
        name?: string
        description?: string
        search_config?: Record<string, unknown>
      }
      // Jak backend (`searches_update`, złoto searches--15): brak `name`/`search_config` → 101.
      if (body.name === undefined || body.search_config === undefined) {
        return HttpResponse.json({
          code: 101,
          message: 'required argument are missing: search_config; ',
          data: false,
        })
      }
      const existing = store.find((item) => item.id === params.searchId)
      if (existing === undefined) {
        return HttpResponse.json({ code: 109, message: 'Search not found', data: false })
      }
      const updated: SearchApp = {
        ...existing,
        name: body.name ?? existing.name,
        description: body.description ?? existing.description,
        search_config: body.search_config ?? existing.search_config,
      }
      store = store.map((item) => (item.id === updated.id ? updated : item))
      // `searches_update` zwraca pełny wiersz z datami (`SearchUpdateResult`), nie sam `SearchApp`.
      return HttpResponse.json({
        code: 0,
        message: '',
        data: {
          ...toListItem(updated),
          create_date: SEARCH_DATE,
          update_date: SEARCH_DATE,
          search_config: updated.search_config,
        },
      })
    }),

    http.delete(apiUrl('/api/v1/searches/:searchId'), ({ params }) => {
      store = store.filter((item) => item.id !== params.searchId)
      return HttpResponse.json({ code: 0, message: '', data: true })
    }),

    http.post(
      apiUrl('/api/v1/searches/:searchId/completions'),
      () => new HttpResponse(summaryStream(), { headers: SSE_HEADERS }),
    ),

    http.post(apiUrl('/api/v1/chat/recommendation'), () =>
      HttpResponse.json({
        code: 0,
        message: '',
        data: ['Powiązane pytanie 1', 'Powiązane pytanie 2'],
      }),
    ),
  ]
}
