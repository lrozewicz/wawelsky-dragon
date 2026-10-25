// WP V13-1 T9 — SC-V13-03 k2–k3 (work/wp/V13/SCENARIOS.md): po „aktualizacji” do v1.3 mapa
// bazy działa BEZ ponownego parsowania — w przeglądarce na stosie produkcyjnym z nakładką
// fake-llm (tools/dev/clean-install.sh, WD_CI_SPEC=ten plik).
//
// Symulacja instalacji sprzed v1.3 (sposób wg docs/decisions/DEC-368): wiersze
// `document_profiles` usuwamy SQL-em przez `docker exec` do kontenera mariadb stosu (żadna
// trasa API/UI nie usuwa profilu — instalacja sprzed v1.3 nie zna tej tabeli wcale), a potem
// restartujemy kontener workera helperem helpers/worker.ts (jak real-resilience). Worker przy
// starcie kolejkuje `build_outline` dla dokumentów bez profilu (K21 §2 p. 4) — użytkownik
// nie klika „Parsuj ponownie”.
//
// Przebieg: wgranie i parsowanie rocznika GUS (stan „przed aktualizacją”) → baseline
// (chunk_count, log) → DELETE profili + twarde potwierdzenie w SQL → pytanie o bazę PRZED
// restartem nie psuje się (asercja negatywna z briefu) → restart workera → w ≤ 120 s pełna
// mapa 28 działów (k2) → log ma dopisaną linię „Outline: 678 entries (PDF bookmarks)”,
// status pliku nadal „Sukces”, chunk_count bez zmian (k3). Brzmienia asercji: kontrakt
// K21 §2 p. 3, §4, §6a; helpery wspólne: helpers/s30-gus.ts.
//
// Zrzuty diagnostyczne: gdy ustawione WD_CI_SHOTS_DIR, spec zapisuje tam desktop.png/mobile.png
// (do oceny wizualnej); bez zmiennej zapis jest pomijany (bieg wyroczni bez zrzutów działa).
import { execFile } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { promisify } from 'node:util'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

import { expectNoLayoutDefects } from '../e2e/helpers/layout'

import { restartContainer, serviceContainerId } from './helpers/worker'
import {
  ANSWER_TIMEOUT_MS,
  apiLogin,
  ask,
  corpusFile,
  createChatViaApi,
  createDataset,
  datasetIdByName,
  documentRow,
  GUS_DATASET,
  GUS_NAME,
  GUS_PARSE_TIMEOUT_MS,
  GUS_SECTIONS,
  lastAnswer,
  loginAsAdmin,
  ok,
  readParseLog,
  uploadFiles,
} from './helpers/s30-gus'

const run = promisify(execFile)

// Pytanie o bazę SC-V13-03 k2 — to samo brzmienie co SC-V13-01 k2 (i zestaw testowy K21 §4 p. 1).
const KB_QUESTION = 'Co zawiera twoja baza wiedzy? Na jakie tematy możesz udzielić informacji?'

// Linia logu po wyznaczeniu spisu (K21 §2 p. 3); wariant PL to tłumaczenie UI z WP V13-2.
// Wersja z flagą global służy wyłącznie do zliczania wystąpień (matchAll); do zwykłego
// dopasowania osobna — regex z flagą `g` przenosi `lastIndex` między testami.
const OUTLINE_LINE =
  /Outline: 678 entries \(PDF bookmarks\)|Spis treści: 678 pozycji \(zakładki PDF\)/
const OUTLINE_LINE_GLOBAL = new RegExp(OUTLINE_LINE.source, 'g')

// Budżet scenariusza k2: od restartu workera do odpowiedzi z pełną mapą ≤ 2 min (SCENARIOS).
const MAP_BUDGET_MS = 120_000

const SHOTS_DIR = process.env.WD_CI_SHOTS_DIR ?? ''

/**
 * Jedno polecenie SQL w kontenerze mariadb stosu (DEC-368). Login/hasło/baza rozwijane
 * ZMIENNYMI KONTENERA (`$MARIADB_*` w `sh -c`) — sekret nie opuszcza kontenera i nie trafia
 * do argv procesu na hoście; sama treść polecenia wchodzi osobnym argumentem (`$1`).
 */
async function mariadbSql(project: string, sql: string): Promise<string> {
  const cid = serviceContainerId(project, 'mariadb')
  if (cid === null) throw new Error(`brak działającego kontenera mariadb w projekcie ${project}`)
  const { stdout } = await run(
    'docker',
    [
      'exec',
      cid,
      'sh',
      '-c',
      'exec mariadb -N -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" -e "$1"',
      'sh',
      sql,
    ],
    { timeout: 60_000 },
  )
  return stdout
}

async function profileCount(project: string): Promise<number> {
  const out = await mariadbSql(project, 'SELECT COUNT(*) FROM document_profiles')
  const n = Number.parseInt(out.trim(), 10)
  expect(
    Number.isFinite(n),
    `liczba profili odczytana z SQL (stdout: ${JSON.stringify(out)})`,
  ).toBe(true)
  return n
}

/** chunk_count dokumentu po NAZWIE z API listy dokumentów (ta sama wartość co kolumna „Chunki”). */
async function chunkCountByName(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  name: string,
): Promise<number> {
  const data = await ok<{ docs: { name: string; chunk_count: number }[] }>(
    request.get(`/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/v1/datasets/{id}/documents',
  )
  const doc = data.docs.find((candidate) => candidate.name === name)
  expect(doc, `dokument ${name} na liście bazy GUS`).toBeDefined()
  return doc!.chunk_count
}

function countOutlineLines(log: string): number {
  return [...log.matchAll(OUTLINE_LINE_GLOBAL)].length
}

/** Zrzut ekranu do katalogu z WD_CI_SHOTS_DIR (gdy nieustawione — bez zapisu). */
async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS_DIR === '') return
  await page.screenshot({ path: join(SHOTS_DIR, name) })
}

test('SC-V13-03 (real): mapa po aktualizacji — usunięte profile + restart workera, bez ponownego parsowania', async ({
  page,
  request,
}) => {
  test.setTimeout(GUS_PARSE_TIMEOUT_MS + 900_000)
  const project = process.env.WD_CI_PROJECT ?? ''
  expect(project, 'WD_CI_PROJECT ustawiane przez tools/dev/clean-install.sh').not.toBe('')
  if (SHOTS_DIR !== '') await mkdir(SHOTS_DIR, { recursive: true })
  const token = await apiLogin(request)

  // Stan „przed aktualizacją”: instalacja z już sparsowanym rocznikiem (persona SC-V13-03).
  await loginAsAdmin(page)
  await createDataset(page, GUS_DATASET)
  await uploadFiles(page, [corpusFile(GUS_NAME)])
  const row = documentRow(page, GUS_NAME)
  await expect(
    row.getByRole('button', { name: 'Sukces' }),
    `parsowanie rocznika dochodzi do „Sukces”`,
  ).toBeVisible({ timeout: GUS_PARSE_TIMEOUT_MS })

  // Baseline (odczyt PRZED usunięciem profilu): liczba chunków i linie spisu w logu parsowania.
  const gusDatasetId = await datasetIdByName(request, token, GUS_DATASET)
  const chunksBefore = await chunkCountByName(request, token, gusDatasetId, GUS_NAME)
  const logBefore = await readParseLog(page, row.getByRole('button', { name: 'Sukces' }), GUS_NAME)
  const linesBefore = countOutlineLines(logBefore)
  expect(
    linesBefore,
    'parsowanie zostawiło linię spisu w logu (K21 §2 p. 1)',
  ).toBeGreaterThanOrEqual(1)
  console.info(`[SC-V13-03] baseline: chunk_count=${chunksBefore}, linii Outline=${linesBefore}`)

  // Symulacja aktualizacji (DEC-368): profile znikają jak w instalacji sprzed v1.3.
  expect(
    await profileCount(project),
    'profil rocznika istnieje przed usunięciem',
  ).toBeGreaterThanOrEqual(1)
  await mariadbSql(project, 'DELETE FROM document_profiles')
  expect(await profileCount(project), 'profile usunięte — stan instalacji sprzed v1.3').toBe(0)

  // Czat GUS (ustawienia przez API, pytanie użytkownika w przeglądarce).
  const chatId = await createChatViaApi(request, token, 'Czat GUS', [gusDatasetId])
  await page.goto(`/chat/${chatId}`)

  // Asercja negatywna (brief p. 3): PRZED restartem, bez profili, pytanie o bazę NIE psuje się —
  // odpowiedź przychodzi, dokument jest wymieniony. Uwaga na bieg: okresowy przegląd workera
  // (WD_OUTLINE_SWEEP_S=600) mógłby w tym oknie odtworzyć profil — okno jest ułamkiem interwału.
  await ask(page, KB_QUESTION)
  const beforeRestart = lastAnswer(page)
  await expect(beforeRestart, 'pytanie o bazę bez profili dostaje odpowiedź').toContainText(
    'Baza zawiera: ',
    { timeout: ANSWER_TIMEOUT_MS },
  )
  await expect(beforeRestart, 'dokument nadal wymieniony w mapie').toContainText(GUS_NAME)
  await expect(beforeRestart, 'bez profilu mapa nie ma działów').not.toContainText('DZIAŁ I ')

  // Restart workera → sweep przy starcie kolejkuje build_outline (K21 §2 p. 4).
  const workerCid = serviceContainerId(project, 'worker')
  expect(workerCid, 'kontener workera działa').not.toBeNull()
  await restartContainer(workerCid!)

  // k2: w ≤ 2 min pytanie o bazę zwraca pełną mapę 28 działów (bez „Parsuj ponownie”).
  // Polling: profil może się budować jeszcze kilka sekund po restarcie — pytamy ponownie,
  // aż odpowiedź zawiera wszystkie działy (każda próba to świeże zapytanie użytkownika).
  await expect(async () => {
    await ask(page, KB_QUESTION)
    const answer = lastAnswer(page)
    await expect(answer, 'formuła odpowiedzi o bazie (K21 §6a)').toContainText('Baza zawiera: ', {
      timeout: 15_000,
    })
    const text = await answer.innerText()
    for (const section of GUS_SECTIONS) {
      expect(text, `dział „${section}” w mapie po aktualizacji`).toContain(section)
    }
  }).toPass({ timeout: MAP_BUDGET_MS })
  await expect(
    lastAnswer(page),
    'pusta odpowiedź nie może się pokazać (K21 §4 p. 3)',
  ).not.toContainText('No relevant content was found')
  await expectNoLayoutDefects(page, 'czat GUS — pełna mapa po aktualizacji bez reparsowania')

  // Zrzuty do oceny wizualnej: desktop 1280×800 i mobile 390×844 (widok mapy w historii czatu).
  // Po każdej zmianie viewportu dociągamy odpowiedź do widoku (scroll przelicza się na nowo).
  await lastAnswer(page).scrollIntoViewIfNeeded()
  await page.setViewportSize({ width: 1280, height: 800 })
  await lastAnswer(page).scrollIntoViewIfNeeded()
  await shot(page, 'desktop.png')
  await page.setViewportSize({ width: 390, height: 844 })
  await lastAnswer(page).scrollIntoViewIfNeeded()
  await shot(page, 'mobile.png')
  await page.setViewportSize({ width: 1280, height: 720 })

  // k3: status pliku nadal „Gotowe” (chip „Sukces”), chunk_count bez zmian — bez ponownego
  // parsowania; log parsowania ma DOPISANĄ linię spisu (wzrost liczby wystąpień).
  await page.goto(`/dataset/files/${gusDatasetId}`)
  await expect(
    row.getByRole('button', { name: 'Sukces' }),
    'status rocznika nadal „Sukces” po odtworzeniu profilu',
  ).toBeVisible({ timeout: 60_000 })
  const chunksAfter = await chunkCountByName(request, token, gusDatasetId, GUS_NAME)
  expect(chunksAfter, 'liczba chunków bez zmian (bez ponownego parsowania)').toBe(chunksBefore)
  console.info(`[SC-V13-03] po restarcie: chunk_count=${chunksAfter}`)

  const logAfter = await readParseLog(page, row.getByRole('button', { name: 'Sukces' }), GUS_NAME)
  const linesAfter = countOutlineLines(logAfter)
  expect(logAfter, 'linia „Outline: 678 entries (PDF bookmarks)” w logu').toMatch(OUTLINE_LINE)
  expect(
    linesAfter,
    `linia spisu dopisana przez build_outline (przed: ${linesBefore})`,
  ).toBeGreaterThanOrEqual(linesBefore + 1)
  console.info(`[SC-V13-03] log: linii Outline przed=${linesBefore}, po=${linesAfter}`)
  await shot(page, 'log-parsowania.png')
})
