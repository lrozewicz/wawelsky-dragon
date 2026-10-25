// Scenariusz T3 (brief WP E5-H6a + ADDENDUM TL): przy 0 trafień i niepustym „Odpowiedzi przy
// braku wyników" dymek asystenta pokazuje ten tekst — desktop i 390×844.
//
// Kształt zdarzeń SSE (backend/app/api/ragflow/sse.py, `native_frames`, profil ragflow_0_27,
// K4 §1.4): przy 0 trafień backend wysyła DWIE ramki z tym samym `answer`=`E` — delta
// `{"answer":E,"final":false}` i finalna `{"answer":E,"final":true}`. Backend utrwala tekst `E`
// w wiadomości asystenta sesji (K4 §3.4; C1 WP E5-H6e), więc po F5 dymek odtwarza się z historii.
//
// `empty_response` i próg podobieństwa ustawiamy przez API (ADDENDUM TL p. 3: seed e2e tego nie
// umożliwia); pytanie zadajemy w prawdziwym UI. Baza ma sparsowany dokument (`chunk_count > 0` —
// `POST /chats` odrzuca puste bazy, `chat_validation.py`), ale treść niezwiązaną z pytaniem,
// a `similarity_threshold = 0.9` gwarantuje 0 trafień (nawet przy pełnym pokryciu tokenów
// similarity ≤ 0.7).
import { expect, test } from './fixtures'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

import { apiLogin, loginViaUi, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const EMPTY_TEXT = 'Brak informacji w bazie'
const DATASET_NAME = 'E2E T3 baza bez trafien'
const DOCUMENT_NAME = 'e2e-t3-prognoza.txt'
/** Treść niezwiązana z pytaniem — retrieval nie ma czego trafić. */
const DOCUMENT_BODY =
  'Prognoza pogody na najbliższy tydzień przewiduje opady deszczu i silny wiatr w całym kraju. ' +
  'Meteorolodzy ostrzegają przed burzami i zalecają pozostanie w domach.'
const QUESTION = 'Ile waży dorodny arbuz z ogrodu babci?'
const VIEWPORT_WIDE = { width: 1280, height: 800 }
const VIEWPORT_NARROW = { width: 390, height: 844 }

type Envelope<T> = { code: number; message: string; data: T }

async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Czat z niepustym `empty_response` i progiem 0.9 (0 trafień); bez refine wieloturowego. */
async function createEmptyResponseChat(
  request: APIRequestContext,
  token: string,
  corpus: SeededCorpus,
): Promise<string> {
  const chat = await ok<{ id: string }>(
    request.post(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: {
        name: 'E2E T3 empty_response',
        dataset_ids: [corpus.datasetId],
        similarity_threshold: 0.9,
        prompt_config: { empty_response: EMPTY_TEXT, refine_multiturn: false },
      },
    }),
    'POST /api/v1/chats',
  )
  return chat.id
}

/** Wpisuje pytanie w polu rozmowy i wysyła je przyciskiem. */
async function ask(page: Page, question: string): Promise<void> {
  await page.getByPlaceholder('Wpisz pytanie…').fill(question)
  await page.getByRole('button', { name: 'Wyślij' }).click()
}

test('S16c: 0 trafień → dymek asystenta pokazuje „Odpowiedzi przy braku wyników”', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)
  const token = await apiLogin(request)
  const corpus = await seedCorpus(request, token, {
    datasetName: DATASET_NAME,
    documentName: DOCUMENT_NAME,
    documentBody: DOCUMENT_BODY,
  })
  const chatId = await createEmptyResponseChat(request, token, corpus)

  try {
    await loginViaUi(page)
    await page.goto(`/chat/${chatId}`)

    // 1. Desktop: pytanie w prawdziwym UI, odpowiedź z `empty_response` w dymku asystenta.
    await page.setViewportSize(VIEWPORT_WIDE)
    await ask(page, QUESTION)
    await expect(page.getByTestId('message-assistant').last()).toContainText(EMPTY_TEXT, {
      timeout: 30_000,
    })

    // 1b. F5: tekst utrwalony w sesji — po przeładowaniu dymek nadal go pokazuje (C1 WP E5-H6e).
    await page.reload()
    await expect(page.getByTestId('message-assistant').last()).toContainText(EMPTY_TEXT, {
      timeout: 30_000,
    })

    // 2. 390×844: ten sam tekst w wąskim układzie, bez przeładowania strony (ADDENDUM TL p. 3).
    await page.setViewportSize(VIEWPORT_NARROW)
    await ask(page, QUESTION)
    await expect(page.getByTestId('message-assistant').last()).toContainText(EMPTY_TEXT, {
      timeout: 30_000,
    })

    // 2b. F5 w wąskim układzie: ten sam dymek nadal widoczny po przeładowaniu.
    await page.reload()
    await expect(page.getByTestId('message-assistant').last()).toContainText(EMPTY_TEXT, {
      timeout: 30_000,
    })
  } finally {
    // Sprzątanie: czat i baza wiedzy po scenariuszu.
    const headers = { authorization: `Bearer ${token}` }
    await request.delete(`${API_URL}/api/v1/chats`, { headers, data: { ids: [chatId] } })
    await request.delete(`${API_URL}/api/v1/datasets`, {
      headers,
      data: { ids: [corpus.datasetId] },
    })
  }
})
