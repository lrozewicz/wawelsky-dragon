// WP V13-1 T1 — SC-V13-02 k1–k3 i SC-V13-04 k1–k2 przez API na stosie testowym (fake-llm).
// Testy są CZERWONE PRZED implementacją (K21): dziś brak spisu treści w logu ingestii, brak
// mapy bazy w prompcie czatu (fake-llm odpowiada blokiem wiedzy „Na podstawie źródeł…”) i
// brak walidacji długości nazwy klucza API. Po T2–T7 mają być zielone — asercje trzymają
// dosłowne brzmienia z kontraktu docs/contracts/K21-v13-mapa-bazy.md (§2 p. 3, §4, §5, §6a).
// Fixtures: e2e/fixtures/v13-1/ (PDF z 3 zakładkami poziomu 0, PDF bez zakładek, md z 4
// nagłówkami; generator: make-fixtures.py w tym katalogu). Dokumenty znajdowane po nazwie,
// kolejność uploadu nie gra roli (wymaganie briefu T1 p. 3).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { APIRequestContext, APIResponse } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, POLL_TIMEOUT_MS } from './helpers'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const FIXTURES_DIR = fileURLToPath(new URL('./fixtures/v13-1', import.meta.url))

const DATASET_NAME = 'V13-1 Mix (mapa bazy)'
const CHAT_NAME = 'V13-1 czat mix'

/** Nazwy plików fixtures — unikalne prefiksy, żeby asercje odpowiedzi były jednoznaczne. */
const DOC_BOOKMARKS = 'v13-zakladki.pdf'
const DOC_PLAIN = 'v13-bez-zakladek.pdf'
const DOC_MD = 'v13-naglowki.md'
const DOC_NAMES = [DOC_BOOKMARKS, DOC_PLAIN, DOC_MD] as const

/** Tytuły 3 zakładek poziomu 0 w v13-zakladki.pdf (make-fixtures.py — DOSŁOWNIE te same). */
const BOOKMARK_TITLES = [
  'Smok Wawelski — rozdział wstępny',
  'Zamek na wzgórzu — rozdział drugi',
  'Przegląd korpusu — rozdział końcowy',
] as const

/** Liczba nagłówków w v13-naglowki.md (h1 + 2×h2 + h3 — patrz make-fixtures.py). */
const MD_HEADING_COUNT = 4

const LONG_NAME = 'a'.repeat(129)
const OK_NAME = 'a'.repeat(128)

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0` (wzór: helpers.ts). */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

type DocRow = {
  id: string
  name: string
  run: string
  status: string
  progress_msg: string
}

/** Wiersz dokumentu z listy bazy (szukany PO NAZWIE — kolejność uploadu bez znaczenia). */
async function docRowByName(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  name: string,
): Promise<DocRow> {
  const listed = await ok<{ docs: DocRow[] }>(
    request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/v1/datasets/{id}/documents',
  )
  const row = listed.docs.find((doc) => doc.name === name)
  expect(row, `dokument ${name} na liście bazy`).toBeDefined()
  return row!
}

/** Wgrywa jeden plik z katalogu fixtures i zwraca identyfikator dokumentu. */
async function uploadFixture(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  name: string,
  mimeType: string,
): Promise<string> {
  const uploaded = await ok<{ id: string }[]>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${token}` },
      multipart: {
        file: {
          name,
          mimeType,
          buffer: readFileSync(`${FIXTURES_DIR}/${name}`),
        },
      },
    }),
    `POST /datasets/{id}/documents (${name})`,
  )
  expect(uploaded, `upload ${name}: dokładnie jeden dokument`).toHaveLength(1)
  return uploaded[0]!.id
}

/** Pyta czat przez API (stream=false → JSON; K4 §1.7) i zwraca treść odpowiedzi. */
async function ask(
  request: APIRequestContext,
  token: string,
  chatId: string,
  question: string,
): Promise<string> {
  const data = await ok<{ answer: string }>(
    request.post(`${API_URL}/api/v1/chats/${chatId}/completions`, {
      headers: { authorization: `Bearer ${token}` },
      data: { question, stream: false },
    }),
    `POST /chats/{id}/completions (${question})`,
  )
  return data.answer
}

const state: { token: string; datasetId: string; chatId: string } = {
  token: '',
  datasetId: '',
  chatId: '',
}

// Testy współdzielą tylko stan z beforeAll (baza, dokumenty, czat) — między sobą są
// niezależne, więc domyślny tryb pokaże w czerwonym biegu powód niepowodzenia KAŻDEGO z nich.
test.beforeAll(async ({ request }) => {
  test.setTimeout(300_000)
  state.token = await apiLogin(request)
  state.datasetId = await (async () => {
    const dataset = await ok<{ id: string }>(
      request.post(`${API_URL}/api/v1/datasets`, {
        headers: { authorization: `Bearer ${state.token}` },
        data: { name: DATASET_NAME },
      }),
      'POST /api/v1/datasets',
    )
    return dataset.id
  })()

  const uploaded: [string, string][] = [
    [
      DOC_BOOKMARKS,
      await uploadFixture(request, state.token, state.datasetId, DOC_BOOKMARKS, 'application/pdf'),
    ],
    [
      DOC_PLAIN,
      await uploadFixture(request, state.token, state.datasetId, DOC_PLAIN, 'application/pdf'),
    ],
    [DOC_MD, await uploadFixture(request, state.token, state.datasetId, DOC_MD, 'text/markdown')],
  ]
  await ok<unknown>(
    request.post(`${API_URL}/api/v1/datasets/${state.datasetId}/documents/parse`, {
      headers: { authorization: `Bearer ${state.token}` },
      data: { document_ids: uploaded.map(([, documentId]) => documentId) },
    }),
    'POST /datasets/{id}/documents/parse',
  )

  // Wszystkie trzy dochodzą do DONE (limit jak seedCorpus, odmierzany od teraz).
  const deadline = Date.now() + POLL_TIMEOUT_MS
  for (;;) {
    const runs = await Promise.all(
      uploaded.map(([name]) => docRowByName(request, state.token, state.datasetId, name)),
    )
    if (runs.every((row) => ['DONE', 'FAIL', 'CANCEL'].includes(row.run))) {
      for (const row of runs) {
        expect(row.run, `parsowanie ${row.name}`).toBe('DONE')
      }
      break
    }
    expect(Date.now() < deadline, 'limit oczekiwania na parsowanie fixtures').toBe(true)
    await new Promise((resolve) => setTimeout(resolve, 1_000))
  }

  state.chatId = await createChat(request, state.token, {
    name: CHAT_NAME,
    datasetIds: [state.datasetId],
  })
})

test.afterAll(async ({ request }) => {
  // Sprzątanie mimo porażki: klucze z SC-04 (po NAZWIE — czerwony bieg przed T7 tworzy klucz
  // 129-znakowy, którego test nie zdąży zapisać), czat i baza. Reset K9 czyści bazę raz na bieg,
  // więc zostawienie wierszy zaburzyłoby inne scenariusze (konwencja s09/s16c).
  const headers = { authorization: `Bearer ${state.token}` }
  const listed = await ok<{ token: string; name: string | null }[]>(
    request.get(`${API_URL}/api/v1/system/tokens`, { headers }),
    'GET /api/v1/system/tokens (sprzątanie)',
  )
  for (const view of listed) {
    if (view.name === LONG_NAME || view.name === OK_NAME) {
      await request.delete(`${API_URL}/api/v1/system/tokens/${encodeURIComponent(view.token)}`, {
        headers,
      })
    }
  }
  if (state.chatId !== '') {
    await request.delete(`${API_URL}/api/v1/chats`, {
      headers,
      data: { ids: [state.chatId] },
    })
  }
  if (state.datasetId !== '') {
    await request.delete(`${API_URL}/api/v1/datasets`, {
      headers,
      data: { ids: [state.datasetId] },
    })
  }
})

test('SC-V13-02 k1 (e2e API): log parsowania każdego pliku ma linię „Outline: …”', async ({
  request,
}) => {
  test.setTimeout(120_000)
  const expected: Record<string, { pattern: RegExp; why: string }> = {
    // Zakładki poziomu 0 w fixture → dokładnie 3 pozycje, źródło „PDF bookmarks” (K21 §2 p. 3).
    // Wpisy progress_msg mają prefiks znacznika czasu — bez kotwic ^…$.
    [DOC_BOOKMARKS]: {
      pattern: /Outline: 3 entries \(PDF bookmarks\)/,
      why: 'PDF z 3 zakładkami poziomu 0',
    },
    // md z 4 nagłówkami (h1 + 2×h2 + h3) → 4 pozycje, źródło „headings”.
    [DOC_MD]: {
      pattern: new RegExp(`Outline: ${MD_HEADING_COUNT} entries \\(headings\\)`),
      why: 'md z 4 nagłówkami',
    },
    // PDF bez zakładek: kontrakt dopuszcza obie ścieżki — nagłówki z bloków (gdy parser
    // rozpozna układ) albo „none” (K21 §2 p. 2b/2c i „Komendy”: raport korpusu → headings/none).
    [DOC_PLAIN]: {
      pattern: /Outline: (?:\d+ entries \(headings\)|none \(no bookmarks or headings\))/,
      why: 'PDF bez zakładek — headings albo none',
    },
  }
  for (const name of DOC_NAMES) {
    const row = await docRowByName(request, state.token, state.datasetId, name)
    expect(row.progress_msg, `${name} (${expected[name]!.why}) — wpis w progress_msg`).toMatch(
      expected[name]!.pattern,
    )
  }
})

test('SC-V13-02 k2 (e2e API): „Jakie dokumenty masz w bazie?” wymienia wszystkie pliki i działy', async ({
  request,
}) => {
  test.setTimeout(120_000)
  const answer = await ask(request, state.token, state.chatId, 'Jakie dokumenty masz w bazie?')

  // K21 §6a: fake-llm widzi w promptcie sekcję „pełna mapa” (T5) i odpowiada formułą
  // „Baza zawiera: … . Działy: …” — dziś dostaje tylko bloki wiedzy, więc odpowiedź to
  // „Na podstawie źródeł: … [ID:n]” i asercje poniżej padają na braku formuły (właściwy powód).
  expect(answer, 'formuła odpowiedzi o bazie (K21 §6a)').toContain('Baza zawiera: ')
  expect(answer, 'koniec wyliczenia plików, początek działów').toContain('. Działy: ')
  for (const name of DOC_NAMES) {
    expect(answer, `nazwa pliku ${name} w odpowiedzi`).toContain(name)
  }
  for (const title of BOOKMARK_TITLES) {
    expect(answer, `tytuł zakładki „${title}” wśród działów`).toContain(title)
  }
  // Sufiks stron ląduje tylko w prompcie — odpowiedź fake-llm ma go ściąć (K21 §6a).
  expect(answer, 'brak sufiksu „(s. N)” w odpowiedzi fake-llm').not.toMatch(/\(s\. \d+\)/)
})

test('SC-V13-02 k3 (e2e API): po wyłączeniu dokumentu znika z odpowiedzi, pozostałe zostają', async ({
  request,
}) => {
  test.setTimeout(120_000)
  // Wyłączenie przez API (na stosie prod. ten sam krok biega przełącznikiem „Włączony”).
  const row = await docRowByName(request, state.token, state.datasetId, DOC_MD)
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${state.datasetId}/documents/${row.id}`, {
      headers: { authorization: `Bearer ${state.token}` },
      data: { enabled: 0 },
    }),
    `PUT /datasets/{id}/documents/{id} (enabled=0, ${DOC_MD})`,
  )
  const after = await docRowByName(request, state.token, state.datasetId, DOC_MD)
  expect(after.status, `${DOC_MD} wyłączony`).toBe('0')

  const answer = await ask(request, state.token, state.chatId, 'Jakie dokumenty masz w bazie?')
  expect(answer, 'formuła odpowiedzi po wyłączeniu (K21 §6a)').toContain('Baza zawiera: ')
  expect(answer, `wyłączony ${DOC_MD} nie występuje`).not.toContain(DOC_MD)
  for (const name of [DOC_BOOKMARKS, DOC_PLAIN]) {
    expect(answer, `pozostały plik ${name} w odpowiedzi`).toContain(name)
  }
})

test('SC-V13-04 k1 (e2e API): nazwa klucza 129 znaków → 101, „Token name must be at most 128 characters.”', async ({
  request,
}) => {
  test.setTimeout(60_000)
  const headers = { authorization: `Bearer ${state.token}` }
  const before = await ok<{ token: string }[]>(
    request.get(`${API_URL}/api/v1/system/tokens`, { headers }),
    'GET /api/v1/system/tokens (przed)',
  )

  const response = await request.post(`${API_URL}/api/v1/system/tokens?name=${LONG_NAME}`, {
    headers,
  })
  // K21 §5 p. 1: ValidationFailed → jak inne w przestrzeni ragflow: HTTP 200 z code 101
  // (DEC-367); komunikat dosłowny; klucz nie powstaje.
  expect(response.status(), 'HTTP walidacji nazwy klucza').toBe(200)
  const body = (await response.json()) as Envelope<null>
  expect(body.code, 'kod koperty walidacji').toBe(101)
  expect(body.message, 'komunikat walidacji (dosłownie)').toBe(
    'Token name must be at most 128 characters.',
  )

  const after = await ok<{ token: string }[]>(
    request.get(`${API_URL}/api/v1/system/tokens`, { headers }),
    'GET /api/v1/system/tokens (po)',
  )
  expect(
    after.map((view) => view.token),
    'lista kluczy bez zmian — klucz nie powstał',
  ).toEqual(before.map((view) => view.token))
})

test('SC-V13-04 k2 (e2e API): nazwa 128 znaków → klucz powstały z pełną nazwą', async ({
  request,
}) => {
  test.setTimeout(60_000)
  const created = await ok<{ token: string; name: string | null }>(
    request.post(`${API_URL}/api/v1/system/tokens?name=${OK_NAME}`, {
      headers: { authorization: `Bearer ${state.token}` },
    }),
    'POST /api/v1/system/tokens?name=<128 × a>',
  )
  expect(created.name, 'nazwa odbita w odpowiedzi').toBe(OK_NAME)
  expect(created.token, 'token zaczyna się od prefiksu ragflow-').toMatch(/^ragflow-/)
})
