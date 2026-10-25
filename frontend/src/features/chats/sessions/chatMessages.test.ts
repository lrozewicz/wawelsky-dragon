import { describe, expect, it } from 'vitest'

import type { components } from '../../../api/schema.gen'
import { initialStreamState, type StreamState } from '../../chat-stream/reducer'

import { historyToMessages, liveToMessages } from './chatMessages'
import type { Session } from './sessionQueries'

type ReferenceChunk = components['schemas']['ReferenceChunk']
type CompletionReference = components['schemas']['CompletionReference']

// Kształt wiadomości i `reference` jak w złocie
// backend/tests/contract/golden/v0.27.2/chats___sessions___/chat_extras--10.json
// (placeholdery `<ID:…>` zastąpione zwykłymi identyfikatorami).
function chunk(overrides: Partial<ReferenceChunk> = {}): ReferenceChunk {
  return {
    id: 'c1',
    content: 'tekst',
    document_id: 'd1',
    document_name: 'f.txt',
    dataset_id: 'ds-1',
    image_id: '',
    positions: [],
    url: null,
    similarity: 0.5,
    vector_similarity: 0.5,
    term_similarity: 0.5,
    row_id: null,
    doc_type: '',
    document_metadata: null,
    ...overrides,
  }
}

function reference(overrides: Partial<CompletionReference> = {}): CompletionReference {
  return { chunks: [], ...overrides }
}

function sessionFixture(overrides: Partial<Session> = {}): Session {
  return {
    chat_id: 'chat-1',
    create_date: '2025-01-01 00:00:00',
    create_time: 1735689600000,
    id: 'session-1',
    name: 'wd_rec_chat_extras_session',
    update_date: '2025-01-01 00:00:00',
    update_time: 1735689600000,
    user_id: 'u1',
    messages: [
      { role: 'assistant', content: "Hi! I'm your assistant. What can I do for you?" },
      { role: 'user', content: 'smokwawelski', id: 'u1' },
      {
        role: 'assistant',
        content: '<think>x</think>Odp [ID:0]',
        id: 'a1',
        created_at: 1735689600,
      },
    ],
    reference: [
      reference({
        chunks: [chunk()],
        doc_aggs: [{ doc_id: 'd1', doc_name: 'f.txt', count: 1 }],
        total: 1,
      }),
    ],
    ...overrides,
  }
}

describe('historyToMessages', () => {
  it('mapuje prologue, user i assistant z cytowaniami z reference[0]', () => {
    const messages = historyToMessages(sessionFixture())

    expect(messages).toHaveLength(3)
    expect(messages[0]).toMatchObject({
      key: 'greeting',
      id: null,
      role: 'assistant',
      content: "Hi! I'm your assistant. What can I do for you?",
      thinking: '',
      citations: [],
      docAggs: [],
      status: 'done',
    })
    expect(messages[1]).toMatchObject({
      key: 'u1',
      id: 'u1',
      role: 'user',
      content: 'smokwawelski',
      thinking: '',
      citations: [],
    })
    expect(messages[2]).toEqual({
      key: 'a1',
      id: 'a1',
      role: 'assistant',
      content: 'Odp [ID:0]',
      thinking: 'x',
      citations: [
        { chunkId: 'c1', docId: 'd1', docName: 'f.txt', content: 'tekst', similarity: 0.5 },
      ],
      docAggs: [{ docId: 'd1', docName: 'f.txt', count: 1 }],
      thumbup: null,
      status: 'done',
      error: null,
    })
  })

  it('assistant bez wpisu w reference dostaje puste cytowania', () => {
    const session = sessionFixture({
      messages: [
        { role: 'assistant', content: 'prologue' },
        { role: 'assistant', content: 'bez źródeł', id: 'a1' },
      ],
      reference: [],
    })

    expect(historyToMessages(session)[1]).toMatchObject({ citations: [], docAggs: [] })
  })

  it('kolejne odpowiedzi assistant biorą reference[k] bez prologue', () => {
    const session = sessionFixture({
      messages: [
        { role: 'assistant', content: 'prologue' },
        { role: 'user', content: 'pyt 1', id: 'u1' },
        { role: 'assistant', content: 'odp 1', id: 'a1' },
        { role: 'user', content: 'pyt 2', id: 'u2' },
        { role: 'assistant', content: 'odp 2', id: 'a2' },
      ],
      reference: [
        reference({ chunks: [chunk({ id: 'c1', content: 'a' })] }),
        reference({ chunks: [chunk({ id: 'c2', content: 'b' })] }),
      ],
    })

    const messages = historyToMessages(session)

    expect(messages[2]?.citations.map((citation) => citation.chunkId)).toEqual(['c1'])
    expect(messages[4]?.citations.map((citation) => citation.chunkId)).toEqual(['c2'])
  })

  it('para user/assistant o wspólnym `id` dostaje unikalne klucze', () => {
    // API sesji eksponuje JEDNO `id` dla pary user+assistant (K4 §3.3), więc sam `id` nie jest
    // unikalnym kluczem Reacta — klucze muszą się różnić mimo wspólnego `id`.
    const session = sessionFixture({
      messages: [
        { role: 'assistant', content: 'prologue' },
        { role: 'user', content: 'pyt', id: 'shared' },
        { role: 'assistant', content: 'odp', id: 'shared' },
      ],
      reference: [reference()],
    })

    const keys = historyToMessages(session).map((message) => message.key)

    expect(new Set(keys).size).toBe(keys.length)
  })

  it('przepuszcza thumbup i pomija puste doc_aggs', () => {
    const session = sessionFixture({
      messages: [
        { role: 'assistant', content: 'prologue' },
        { role: 'assistant', content: 'odp', id: 'a1', thumbup: true, feedback: 'ok' },
      ],
      reference: [reference({ doc_aggs: null })],
    })

    expect(historyToMessages(session)[1]).toMatchObject({ thumbup: true, docAggs: [] })
  })
})

describe('liveToMessages', () => {
  it('buduje parę live ze stanu reduktora; klucze wg id pary (jak w historii)', () => {
    const state: StreamState = {
      ...initialStreamState,
      status: 'streaming',
      answer: 'a',
      thinking: 't',
      messageId: 'm',
    }

    const messages = liveToMessages('pyt', state, 'streaming')

    expect(
      messages.map(({ key, id, role, content, thinking, status }) => ({
        key,
        id,
        role,
        content,
        thinking,
        status,
      })),
    ).toEqual([
      { key: 'user-m', id: null, role: 'user', content: 'pyt', thinking: '', status: 'done' },
      {
        key: 'assistant-m',
        id: 'm',
        role: 'assistant',
        content: 'a',
        thinking: 't',
        status: 'streaming',
      },
    ])
  })

  it('bez id pary (przed pierwszą ramką) klucze zostają live-*', () => {
    const messages = liveToMessages('pyt', initialStreamState, 'streaming')

    expect(messages.map((message) => message.key)).toEqual(['live-user', 'live-assistant'])
  })

  it('klucze pary live zgadzają się z kluczami tej pary w historii (SC-V13-z-01)', () => {
    // Refetch sesji po `done` zamienia parę live na parę z historii; przy różnych kluczach React
    // remontuje komponenty wiadomości i otwarty modal cytowania zamyka się zaraz po kliknięciu.
    // Para w sesji dzieli jedno `id` (K4 §3.3), więc historia daje klucze `user-<id>`/`assistant-<id>`
    // (id powtórzone → prefiks roli w `historyToMessages`).
    const session = sessionFixture({
      messages: [
        { role: 'assistant', content: 'prologue' },
        { role: 'user', content: 'pyt', id: 'm1' },
        { role: 'assistant', content: 'odp', id: 'm1' },
      ],
      reference: [reference()],
    })
    const state: StreamState = {
      ...initialStreamState,
      status: 'done',
      answer: 'odp',
      messageId: 'm1',
    }

    const liveKeys = liveToMessages('pyt', state, 'done').map((message) => message.key)
    const historyKeys = historyToMessages(session).map((message) => message.key)

    expect(liveKeys).toEqual(['user-m1', 'assistant-m1'])
    expect(liveKeys).toEqual(historyKeys.slice(-2))
  })

  it('przenosi cytowania, agregaty i błąd ze stanu', () => {
    const state: StreamState = {
      ...initialStreamState,
      status: 'error',
      answer: 'a',
      citations: [
        { chunkId: 'c1', docId: 'd1', docName: 'f.txt', content: 'tekst', similarity: 0.5 },
      ],
      docAggs: [{ docId: 'd1', docName: 'f.txt', count: 1 }],
      messageId: 'm',
      error: 'boom',
    }

    expect(liveToMessages('pyt', state, 'error')[1]).toMatchObject({
      citations: state.citations,
      docAggs: state.docAggs,
      error: 'boom',
      status: 'error',
    })
  })

  it('po końcu bez błędu nie niesie komunikatu błędu', () => {
    const state: StreamState = { ...initialStreamState, answer: 'a', messageId: 'm' }

    expect(liveToMessages('pyt', state, 'done')[1]).toMatchObject({ error: null, status: 'done' })
  })
})
