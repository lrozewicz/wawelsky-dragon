import { describe, expect, it } from 'vitest'

import type { SseFrame } from '../../lib/sse'

import { initialStreamState, normalizeChunks, reduce } from './reducer'

// Ramki w kształcie złota `backend/tests/contract/golden/v0.27.2/chats___completions/completion--09.sse`
// (placeholdery `<ID:…>` z golden zamienione na zwykłe identyfikatory).
const FRAME_SEARCH: SseFrame = {
  code: 0,
  message: '',
  data: {
    answer: 'Sorry! No relevant content was found in the knowledge base!',
    reference: { chunks: [] },
    final: false,
    id: 'id-3',
    session_id: 'session-1',
  },
}

// Profil v0.27 przy 0 trafień: DWIe ramki z TYM SAMYM tekstem (delta i finalna); patrz §1.4.
const FRAME_ANSWER: SseFrame = {
  code: 0,
  message: '',
  data: {
    answer: 'Sorry! No relevant content was found in the knowledge base!',
    reference: { total: 0, chunks: [], doc_aggs: [] },
    final: true,
    id: 'id-3',
    session_id: 'session-1',
  },
}

const FRAME_DONE: SseFrame = { code: 0, message: '', data: true }

const CHUNK_A = {
  id: 'chunk-a',
  document_id: 'doc-1',
  document_name: 'Umowa.pdf',
  content: 'Treść A',
  similarity: 0.87,
}

const CHUNK_B = {
  id: 'chunk-b',
  document_id: 'doc-2',
  document_name: 'Regulamin.pdf',
  content: 'Treść B',
  similarity: 0.42,
}

const FRAME_CITATIONS: SseFrame = {
  code: 0,
  message: '',
  data: {
    reference: {
      total: 2,
      chunks: [CHUNK_A, CHUNK_B],
      doc_aggs: [
        { doc_id: 'doc-1', doc_name: 'Umowa.pdf', count: 1 },
        { doc_id: 'doc-2', doc_name: 'Regulamin.pdf', count: 1 },
      ],
    },
  },
}

// Głęboko zamraża stan (brief wymaga `Object.freeze`), żeby mutacja w `reduce` rzuciła wyjątkiem.
function freeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const nested of Object.values(value)) freeze(nested)
    Object.freeze(value)
  }
  return value
}

describe('reduce', () => {
  it('ustawia done na ramce data:true', () => {
    const streaming = reduce(initialStreamState, FRAME_ANSWER)
    expect(reduce(streaming, FRAME_DONE).status).toBe('done')
  })
  it('ustawia error z message ramki bez data', () => {
    // Ramka błędu bez `data` (kształt z briefu: `code:500, message:'boom'`).
    const frame = { code: 500, message: 'boom' } as unknown as SseFrame
    const next = reduce(initialStreamState, frame)
    expect(next.status).toBe('error')
    expect(next.error).toBe('boom')
  })
  it('bierze error z data.answer, gdy brak message', () => {
    const next = reduce(initialStreamState, {
      code: 500,
      message: '',
      data: { answer: '**ERROR**: x' },
    })
    expect(next.status).toBe('error')
    expect(next.error).toBe('**ERROR**: x')
  })
  it('używa "error", gdy brak message i answer', () => {
    const next = reduce(initialStreamState, { code: 500, message: '', data: null })
    expect(next.status).toBe('error')
    expect(next.error).toBe('error')
  })
  it('skleja delty answer i ustawia streaming', () => {
    const first = reduce(initialStreamState, { code: 0, message: '', data: { answer: 'Ab' } })
    const second = reduce(first, { code: 0, message: '', data: { answer: 'c' } })
    expect(second.answer).toBe('Abc')
    expect(second.status).toBe('streaming')
  })
  it('zapisuje session_id i id, a puste pomija', () => {
    const next = reduce(initialStreamState, FRAME_SEARCH)
    expect(next.sessionId).toBe('session-1')
    expect(next.messageId).toBe('id-3')
    const empty = reduce(initialStreamState, {
      code: 0,
      message: '',
      data: { session_id: '', id: '' },
    })
    expect(empty.sessionId).toBeNull()
    expect(empty.messageId).toBeNull()
  })
  it('przełącza w tryb think i kieruje delty do thinking', () => {
    const started = reduce(initialStreamState, {
      code: 0,
      message: '',
      data: { start_to_think: true, answer: '' },
    })
    expect(started.mode).toBe('think')
    const next = reduce(started, { code: 0, message: '', data: { answer: 'myśl' } })
    expect(next.thinking).toBe('myśl')
    expect(next.answer).toBe('')
  })
  it('przełącza z powrotem w tryb answer na end_to_think', () => {
    const thinking = reduce(initialStreamState, {
      code: 0,
      message: '',
      data: { start_to_think: true },
    })
    const next = reduce(thinking, {
      code: 0,
      message: '',
      data: { end_to_think: true, answer: 'ok' },
    })
    expect(next.mode).toBe('answer')
    expect(next.answer).toBe('ok')
  })
  it('pusta ramka (data null) ustawia streaming bez zmiany treści', () => {
    const next = reduce(initialStreamState, { code: 0, message: '', data: null })
    expect(next.status).toBe('streaming')
    expect(next.answer).toBe('')
  })
  it('normalizuje tablicę chunków i doc_aggs', () => {
    const next = reduce(initialStreamState, FRAME_CITATIONS)
    expect(next.citations).toEqual([
      {
        chunkId: 'chunk-a',
        docId: 'doc-1',
        docName: 'Umowa.pdf',
        content: 'Treść A',
        similarity: 0.87,
      },
      {
        chunkId: 'chunk-b',
        docId: 'doc-2',
        docName: 'Regulamin.pdf',
        content: 'Treść B',
        similarity: 0.42,
      },
    ])
    expect(next.docAggs).toEqual([
      { docId: 'doc-1', docName: 'Umowa.pdf', count: 1 },
      { docId: 'doc-2', docName: 'Regulamin.pdf', count: 1 },
    ])
  })
  it('normalizuje doc_aggs, pomija nie-obiekty i uzupełnia brakujące pola', () => {
    const next = reduce(initialStreamState, {
      code: 0,
      message: '',
      data: {
        reference: {
          chunks: [CHUNK_A],
          doc_aggs: [null, 'nie-obiekt', { doc_id: 'doc-1' }, { doc_name: 'Bez id.pdf', count: 2 }],
        },
      },
    })
    expect(next.docAggs).toEqual([
      { docId: 'doc-1', docName: '', count: 0 },
      { docId: '', docName: 'Bez id.pdf', count: 2 },
    ])
  })
  it('przyjmuje chunki jako obiekt i zachowuje kolejność Object.values', () => {
    const next = reduce(initialStreamState, {
      code: 0,
      message: '',
      data: { reference: { chunks: { a: CHUNK_A, b: CHUNK_B } } },
    })
    expect(next.citations.map((citation) => citation.chunkId)).toEqual(['chunk-a', 'chunk-b'])
    expect(next.docAggs).toEqual([])
  })
  it('puste chunki nie kasują poprzednich cytowań', () => {
    const withCitations = reduce(initialStreamState, FRAME_CITATIONS)
    const emptyArray = reduce(withCitations, {
      code: 0,
      message: '',
      data: { reference: { chunks: [] } },
    })
    expect(emptyArray.citations).toHaveLength(2)
    const emptyObject = reduce(withCitations, {
      code: 0,
      message: '',
      data: { reference: { chunks: {} } },
    })
    expect(emptyObject.citations).toHaveLength(2)
    const noChunks = reduce(withCitations, {
      code: 0,
      message: '',
      data: { reference: { total: 5 } },
    })
    expect(noChunks.citations).toHaveLength(2)
  })
  it('niepusta tablica chunków zastępuje poprzednie cytowania', () => {
    const withCitations = reduce(initialStreamState, FRAME_CITATIONS)
    const next = reduce(withCitations, {
      code: 0,
      message: '',
      data: { reference: { chunks: [CHUNK_A] } },
    })
    expect(next.citations).toHaveLength(1)
    expect(next.citations[0]?.chunkId).toBe('chunk-a')
  })
  it('ignoruje kolejne ramki po done', () => {
    const done = reduce(initialStreamState, FRAME_DONE)
    const next = reduce(done, { code: 0, message: '', data: { answer: 'x' } })
    expect(next).toBe(done)
  })
  it('ignoruje kolejne ramki po error', () => {
    const errored = reduce(initialStreamState, { code: 500, message: 'boom', data: null })
    const next = reduce(errored, { code: 0, message: '', data: { answer: 'x' } })
    expect(next).toBe(errored)
  })
  it('przechodzi sekwencję złota completion--09 do done', () => {
    let state = reduce(initialStreamState, FRAME_SEARCH)
    state = reduce(state, FRAME_ANSWER)
    state = reduce(state, FRAME_DONE)
    expect(state.status).toBe('done')
    // Finalna ramka empty_response niesie ten sam tekst co delta — tekst NIE dubluje się.
    expect(state.answer).toBe('Sorry! No relevant content was found in the knowledge base!')
    expect(state.sessionId).toBe('session-1')
  })
  it('finalna ramka z niepustym answer zastępuje tekst (empty_response v0.27)', () => {
    // Kształt [{answer:'E',final:false},{answer:'E',final:true}] → 'E' (bez poprawki 'EE').
    let state = reduce(initialStreamState, { code: 0, message: '', data: { answer: 'E' } })
    state = reduce(state, { code: 0, message: '', data: { answer: 'E', final: true } })
    expect(state.answer).toBe('E')
  })
  it('finalna ramka zwykłej ścieżki (answer="") nie zmienia tekstu', () => {
    const text = reduce(initialStreamState, { code: 0, message: '', data: { answer: 'Ab' } })
    const next = reduce(text, { code: 0, message: '', data: { answer: '', final: true } })
    expect(next.answer).toBe('Ab')
  })
  it('nie mutuje wejściowego stanu', () => {
    const state = freeze(reduce(initialStreamState, FRAME_CITATIONS))
    const next = reduce(state, { code: 0, message: '', data: { answer: 'delta' } })
    expect(next).not.toBe(state)
    expect(next.answer).toBe('delta')
    expect(next.citations).toEqual(state.citations)
  })
})

describe('normalizeChunks', () => {
  it('czyta alternatywne nazwy pól', () => {
    expect(
      normalizeChunks([
        { chunk_id: 'c1', doc_id: 'd1', docnm_kwd: 'Plik.pdf', content_with_weight: 'treść' },
      ]),
    ).toEqual([
      { chunkId: 'c1', docId: 'd1', docName: 'Plik.pdf', content: 'treść', similarity: null },
    ])
  })
  it('ustawia similarity null dla nie-liczby i pomija elementy nie-obiektowe', () => {
    const chunks = normalizeChunks([
      null,
      'nie-obiekt',
      { id: 'c1', document_id: 'd1', document_name: 'P.pdf', content: 'x', similarity: '0.5' },
      {},
    ])
    expect(chunks).toEqual([
      { chunkId: 'c1', docId: 'd1', docName: 'P.pdf', content: 'x', similarity: null },
      { chunkId: '', docId: '', docName: '', content: '', similarity: null },
    ])
  })
  it('wyprowadza stronę z positions, a bez pozycji pomija pole', () => {
    const chunks = normalizeChunks([
      { id: 'c1', positions: [[3, 0, 5, 0, 5]] },
      { id: 'c2', positions: [] },
      { id: 'c3', positions: [[0, 0, 0, 0, 0]] },
    ])
    expect(chunks[0]?.page).toBe(3)
    expect(chunks[1]).not.toHaveProperty('page')
    expect(chunks[2]).not.toHaveProperty('page')
  })
})
