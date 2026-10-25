// Wspólne stałe i helpery speców SC-V13-01/02/03 (WP V13-1): wyjęte z
// s30-v13-1-mapa-bazy.spec.ts (T1), żeby s30-v13-1-aktualizacja.spec.ts (T9) reużywał
// te same brzmienia asercji i kroki użytkownika. Brzmienia: docs/contracts/K21-v13-mapa-bazy.md
// §2 p. 3, §3 p. 2, §4, §6a i SCENARIOS.md SC-V13-01/02/03. Dokumenty i bazy znajdowane PO NAZWIE.
// Warianty PL linii logu („Spis treści: …”) to tłumaczenie UI z WP V13-2 — akceptujemy obie
// formy kontraktowe, żeby specy przetrwały scalenie V13-2 (serwer pisze po angielsku zawsze).
import { readdirSync } from 'node:fs'
import { basename, join } from 'node:path'

import { expect } from '@playwright/test'
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

export const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
export const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
export const CORPUS = process.env.WD_REAL_CORPUS ?? ''

export const GUS_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
export const AI_ACT_NAME = 'projekt_ustawy_o_systemach_ai_2026.pdf'
export const ACCESS_REPORT_NAME = 'raport_o_stanie_zapewnienia_dostepnosci.pdf'
export const ACCESS_FORM_NAME = 'wniosek_o_zapewnienie_dostepnosci.docx'
export const STRUCTURED_MD_NAME = 'fixture_rag_strukturalny.md'
export const MIX_NAMES = [
  AI_ACT_NAME,
  ACCESS_REPORT_NAME,
  ACCESS_FORM_NAME,
  STRUCTURED_MD_NAME,
] as const

export const GUS_DATASET = 'GUS'
export const MIX_DATASET = 'Mix'
export const OUTLINE_PATTERNS: Record<string, RegExp> = {
  // 678 zakładek rocznika (K21 „Komendy”; 28 działów na poziomie 0).
  [GUS_NAME]: /Outline: 678 entries \(PDF bookmarks\)|Spis treści: 678 pozycji \(zakładki PDF\)/,
  // 15 zakładek projektu ustawy (K21 „Komendy”).
  [AI_ACT_NAME]: /Outline: 15 entries \(PDF bookmarks\)|Spis treści: 15 pozycji \(zakładki PDF\)/,
  // md: 1×h1 + 3×h2 + 2×h3 = 6 nagłówków (zmierzone na konwerterze repo).
  [STRUCTURED_MD_NAME]: /Outline: 6 entries \(headings\)|Spis treści: 6 pozycji \(nagłówki\)/,
  // PDF bez zakładek i DOCX bez stylów nagłówków: kontrakt dopuszcza „headings” i „none”
  // (K21 §2 p. 2b/2c); dziś obie linie oczywiście nie istnieją — to właściwy powód czerwieni.
  [ACCESS_REPORT_NAME]: HEADINGS_OR_NONE(),
  [ACCESS_FORM_NAME]: HEADINGS_OR_NONE(),
}

export function HEADINGS_OR_NONE(): RegExp {
  return /Outline: (?:\d+ entries \(headings\)|none \(no bookmarks or headings\))|Spis treści: (?:\d+ pozycji \(nagłówki\)|brak \(dokument bez zakładek i nagłówków\))/
}

// 28 tytułów DZIAŁ I…XXVIII z zakładek poziomu 0 rocznika (odczytane pypdfium2 z korpusu;
// strip() kontraktu usuwa spację końcową z tytułu DZIAŁU XXIII). SC-V13-01 k2: odpowiedź
// ma zawierać KAŻDY z nich — dziś fake-llm podaje 5 przypadkowych działów, więc test pada.
export const GUS_SECTIONS = [
  'DZIAŁ I GEOGRAFIA',
  'DZIAŁ II STAN I OCHRONA ŚRODOWISKA',
  'DZIAŁ III ORGANIZACJA PAŃSTWA',
  'DZIAŁ IV WYMIAR SPRAWIEDLIWOŚCI',
  'DZIAŁ V ORGANIZACJE SPOŁECZNE I POLITYCZNE. KOŚCIOŁY I INNE ZWIĄZKI WYZNANIOWE',
  'DZIAŁ VI LUDNOŚĆ',
  'DZIAŁ VII RYNEK PRACY',
  'DZIAŁ VIII WYNAGRODZENIA',
  'DZIAŁ IX ŚWIADCZENIA SPOŁECZNE',
  'DZIAŁ X GOSPODARSTWA DOMOWE.MIESZKANIA',
  'DZIAŁ XI EDUKACJA I WYCHOWANIE',
  'DZIAŁ XII OCHRONA ZDROWIA I POMOC SPOŁECZNA',
  'DZIAŁ XIII KULTURA. TURYSTYKA. SPORT',
  'DZIAŁ XIV NAUKA I TECHNIKA. SPOŁECZEŃSTWO INFORMACYJNE. TELEKOMUNIKACJA',
  'DZIAŁ XV CENY',
  'DZIAŁ XVI ROLNICTWO. RYBOŁÓWSTWO',
  'DZIAŁ XVII LEŚNICTWO I ŁOWIECTWO',
  'DZIAŁ XVIII PRZEMYSŁ I BUDOWNICTWO',
  'DZIAŁ XIX TRANSPORT. POCZTA',
  'DZIAŁ XX HANDEL I GASTRONOMIA',
  'DZIAŁ XXI HANDEL ZAGRANICZNY',
  'DZIAŁ XXII FINANSE PRZEDSIĘBIORSTW',
  'DZIAŁ XXIII PIENIĄDZ I BANKI. RYNEK GIEŁDOWY. ZAKŁADY UBEZPIECZEŃ.',
  'DZIAŁ XXIV FINANSE PUBLICZNE',
  'DZIAŁ XXV INWESTYCJE. ŚRODKI TRWAŁE',
  'DZIAŁ XXVI RACHUNKI NARODOWE',
  'DZIAŁ XXVII PODMIOTY GOSPODARKI NARODOWEJ',
  'DZIAŁ XXVIII PRZEGLĄD MIĘDZYNARODOWY',
] as const

// Rozpoznawalne końcówki działów projektu ustawy (SC-V13-02 k2: „przy ustawie — jej działy
// z zakładek”; tytuły zakładek to pełne ścieżki Windows — asercja po jednoznacznych fragmencie
// końcowym, bez znaków LRM ze źródła).
export const AI_ACT_SECTIONS = [
  'pismo przewodnie.pdf',
  '1) projekt ustawy.pdf',
  '2) uzasadnienie.pdf',
  '5a) Tabela zgodności.pdf',
] as const

// Domyślny „Odpowiedzi przy braku wyników” (backend/app/domain/chat/config.py) — po v1.3
// pytanie o bazę nie może nim kończyć się, nawet gdy retrieval nic nie zwróci (K21 §4 p. 3).
export const EMPTY_RESPONSE_MARK = 'No relevant content was found'

// Budżety: pełne parsowanie rocznika (jak real-stop-progress) i cztery pliki Mix
// (ustawa = 1421 stron tekstu). Czaty fake-llm — krótkie.
export const GUS_PARSE_TIMEOUT_MS = 1_200_000
export const MIX_PARSE_TIMEOUT_MS = 900_000
export const ANSWER_TIMEOUT_MS = 60_000

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0` (wzór: real-stop-progress.spec.ts). */
export async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Ścieżka pliku korpusu po nazwie (korpus poza gitem; wzór: real-stop-progress.spec.ts). */
export function corpusFile(name: string): string {
  if (CORPUS === '') throw new Error('WD_REAL_CORPUS nieustawione')
  const paths: string[] = []
  walk(CORPUS, paths)
  const hit = paths.find((path) => basename(path) === name)
  if (hit === undefined) throw new Error(`korpus: brak pliku ${name} pod ${CORPUS}`)
  return hit
}

function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

export async function apiLogin(request: APIRequestContext): Promise<string> {
  const data = await ok<{ access_token: string }>(
    request.post('/api/v1/auth/login', {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    }),
    'POST /api/v1/auth/login',
  )
  return data.access_token
}

/** Identyfikator bazy po NAZWIE (kolejność listy bez znaczenia). */
export async function datasetIdByName(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const listed = await ok<{ id: string; name: string }[]>(
    request.get('/api/v1/datasets', { headers: { authorization: `Bearer ${token}` } }),
    'GET /api/v1/datasets',
  )
  const hit = listed.find((dataset) => dataset.name === name)
  expect(hit, `baza wiedzy ${name} istnieje`).toBeDefined()
  return hit!.id
}

export async function createChatViaApi(
  request: APIRequestContext,
  token: string,
  name: string,
  datasetIds: string[],
): Promise<string> {
  const chat = await ok<{ id: string }>(
    request.post('/api/v1/chats', {
      headers: { authorization: `Bearer ${token}` },
      data: { name, dataset_ids: datasetIds },
    }),
    'POST /api/v1/chats',
  )
  return chat.id
}

export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło”.
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  const nav = page.getByRole('navigation')
  await expect(nav.getByRole('link', { name: 'Bazy wiedzy' })).toBeVisible()
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
}

/** Tworzy dataset domyślnym modelem instancji (pole embeddingu wypełnia się samo). */
export async function createDataset(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Nazwa').fill(name)
  await dialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

/** Upload przez okno wyboru z domyślnym „Parsuj po przesłaniu” (wzorzec real-resilience). */
export async function uploadFiles(page: Page, files: string[]): Promise<void> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(files)
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: 180_000,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
}

export function documentRow(page: Page, name: string): Locator {
  return page.getByRole('row').filter({ hasText: name })
}

/**
 * Pełny log zadania: klik w chip statusu otwiera dialog „Log parsowania” (wzór:
 * real-stop-progress.spec.ts); zwraca treść `<pre>` i zamyka dialog.
 */
export async function readParseLog(page: Page, trigger: Locator, name: string): Promise<string> {
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: `Log parsowania — ${name}` })).toBeVisible()
  try {
    const pre = dialog.locator('pre')
    return (await pre.count()) > 0 ? await pre.innerText() : ''
  } finally {
    await dialog.getByRole('button', { name: 'Zamknij' }).click()
    await expect(dialog).toBeHidden()
  }
}

/** Wpisuje pytanie w polu rozmowy i wysyła je przyciskiem (wzorzec s16c). */
export async function ask(page: Page, question: string): Promise<void> {
  await page.getByPlaceholder('Wpisz pytanie…').fill(question)
  await page.getByRole('button', { name: 'Wyślij' }).click()
}

/** Ostatni dymek asystenta (odpowiedź na świeżo zadane pytanie). */
export function lastAnswer(page: Page): Locator {
  return page.getByTestId('message-assistant').last()
}

/**
 * SC-V13-01 k2/k3: odpowiedź na pytanie o bazę — formuła K21 §6a i WSZYSTKIE 28 działów.
 * Kolejność asercji celowa: najpierw formuła (dziś czerwona po ~5 s z jednoznacznym powodem),
 * potem tytuły działów.
 */
export async function expectKnowledgeBaseMap(
  page: Page,
  sections: readonly string[],
): Promise<void> {
  const answer = lastAnswer(page)
  await expect(answer, 'formuła odpowiedzi o bazie (K21 §6a)').toContainText('Baza zawiera: ', {
    timeout: ANSWER_TIMEOUT_MS,
  })
  for (const section of sections) {
    await expect(answer, `dział „${section}” w odpowiedzi`).toContainText(section)
  }
  await expect(answer, 'pusta odpowiedź nie może się pokazać (K21 §4 p. 3)').not.toContainText(
    EMPTY_RESPONSE_MARK,
  )
}
