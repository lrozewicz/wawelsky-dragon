// Pomocniki scenariuszy eksportu/importu bazy wiedzy (E7-2, SC-E7-2-01…05; kontrakt K19 §3).
// Dane powstają przez API — wzór: `e2e/helpers.ts` (seedCorpus) i `e2e/helpers/admin.ts`
// (koperta WD: sukces to `{"data": …}` przy 200/201/202, bez pola `code` znanego z koperty
// RAGFlow). Konto B/członka zespołu zakładamy przez API (`POST /api/wd/v1/users`), bo w tych
// scenariuszach jest tylko sztafażem — wzór USUWANIA (kaskadowo) pochodzi z `helpers/admin.ts`.
// Paczki uszkodzone budujemy w teście (E7-1f nie ma jeszcze fixture'ów w repo): poprawny ZIP
// wg K19 §2 z niezgodną sumą wpisu oraz `.txt` przemianowany na `.wdkb.zip`.
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import zlib from 'node:zlib'

import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { expect } from '../fixtures'

const API_URL = process.env.WD_E2E_API_URL ?? ''

export const GUS_PDF_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
export const NCBR_DOCX_NAME = 'wzor_raportu_okresowego_ncbr.docx'
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

/** Budżety stanów końcowych zadań (SCENARIOS/R-KB: eksport i import ≤ 3 min na stosie testowym,
 * z zapasem na wolniejszą maszynę; ponowny embedding 7251 chunków dostaje osobny budżet). */
export const EXPORT_TASK_BUDGET_MS = 360_000
export const IMPORT_TASK_BUDGET_MS = 420_000
export const REEMBED_TASK_BUDGET_MS = 720_000
/** Parsowanie korpusu GUS (745 stron, ~7251 chunków) — pomiar E5-H4a: zasiew nightly 636 s
 * dla 8841 chunków dwóch dużych PDF; tu jeden GUS + mały DOCX, budżet z zapasem ~2×. */
const SEED_PARSE_BUDGET_MS = 1_200_000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export type WdTaskStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

/** Podzbiór `WdTask` (K19 §3) potrzebny scenariuszom; `result` to `ExportResult|ImportResult`. */
export type WdTask = {
  task_id: string
  kind: 'export' | 'import'
  status: WdTaskStatus
  stage: string | null
  done: number
  total: number
  progress: number
  message: string
  error: { code: string; message: string } | null
  result: {
    download_url?: string
    size_bytes?: number
    file_name?: string
    dataset_id?: string
    dataset_name?: string
    documents?: number
    chunks?: number
    reembedded?: boolean
  } | null
}

export type TaskRef = { task_id: string; status: string }

export type DatasetImport = {
  import_id: string
  state: string
  errors: { code: string; message: string }[]
  chunk_size: number
}

/** Paczka eksportu przygotowana przez API: plik na dysku + metadane wyniku zadania. */
export type ExportedPackage = {
  taskId: string
  /** `file_name` z `ExportResult` (np. `rocznik-gus.wdkb.zip`). */
  fileName: string
  /** `size_bytes` z `ExportResult`. */
  sizeBytes: number
  /** Ścieżka pobranej paczki na dysku (dla `setInputFiles`). */
  filePath: string
  /** Względny podpisany link pobrania (`download_url`) — działa bez sesji (K19 §3 trasa 5). */
  downloadPath: string
}

/** Rozwija kopertę WD: żądany status HTTP + `{"data": T}` (wzór: `helpers/admin.ts`). */
export async function wdOk<T>(
  pending: Promise<APIResponse>,
  label: string,
  expectedStatus = 200,
): Promise<T> {
  const response = await pending
  const text = await response.text()
  expect(response.status(), `${label}: HTTP ${response.status()} — ${text}`).toBe(expectedStatus)
  return (JSON.parse(text) as { data: T }).data
}

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0` (wzór: `e2e/helpers.ts`). */
export async function ragOk<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const text = await response.text()
  const body = JSON.parse(text) as { code: number; message: string; data: T }
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

export function authHeaders(token: string): Record<string, string> {
  return { authorization: `Bearer ${token}` }
}

// --- Korpus (dataset poza repo) ---------------------------------------------------------------

/**
 * Ścieżka pliku korpusu: `WD_REAL_CORPUS` (ten sam sens co w `e2e-real`: katalog
 * `dataset/documents/pl`) albo katalog `dataset/documents/pl` obok GŁÓWNEGO checkoutu —
 * `git-common-dir` prowadzi do głównego checkoutu także z worktree (wzór:
 * `tools/dev/mcp-prod-check.sh`). Brak pliku → czytelny wyjątek z oczekiwaną ścieżką.
 */
export function corpusPath(...relative: string[]): string {
  const fromEnv = process.env.WD_REAL_CORPUS
  let base: string
  if (fromEnv !== undefined && fromEnv !== '') {
    base = fromEnv
  } else {
    const commonDir = execFileSync(
      'git',
      ['rev-parse', '--path-format=absolute', '--git-common-dir'],
      {
        cwd: path.dirname(fileURLToPath(import.meta.url)),
      },
    )
      .toString()
      .trim()
    base = path.resolve(path.dirname(commonDir), '..', 'dataset', 'documents', 'pl')
  }
  const resolved = path.resolve(base, ...relative)
  if (!existsSync(resolved)) {
    throw new Error(`Brak pliku korpusu: ${resolved} (WD_REAL_CORPUS=${fromEnv ?? '—'})`)
  }
  return resolved
}

// --- Zadania (K19 §3 trasy 2–4) ---------------------------------------------------------------

/** Odpytuje `GET /tasks/{id}` co 2 s aż do stanu końcowego; po budżecie rzuca z ostatnim stanem. */
export async function waitTask(
  request: APIRequestContext,
  token: string,
  taskId: string,
  budgetMs: number,
): Promise<WdTask> {
  const headers = authHeaders(token)
  const deadline = Date.now() + budgetMs
  for (;;) {
    const task = await wdOk<WdTask>(
      request.get(`${API_URL}/api/wd/v1/tasks/${taskId}`, { headers }),
      `GET /api/wd/v1/tasks/${taskId}`,
    )
    if (task.status === 'done' || task.status === 'failed' || task.status === 'cancelled') {
      return task
    }
    if (Date.now() > deadline) {
      throw new Error(
        `GET /tasks/${taskId}: budżet ${budgetMs} ms minął na stanie „${task.status}” (${task.message})`,
      )
    }
    await sleep(2_000)
  }
}

// --- Zasiew: baza z korpusowym PDF + DOCX ------------------------------------------------------

/** Stany końcowe parsowania dokumentu (`run`; wzór: `seedCorpus` w `e2e/helpers.ts`). */
const TERMINAL_RUNS: readonly string[] = ['DONE', 'FAIL', 'CANCEL']

/**
 * Tworzy bazę wiedzy (domyślny model embeddingu = `fake-embed-1024` z seedu K9), wgrywa rocznik
 * GUS i wzór raportu NCBR przez API, parsuje oba i czeka na `run = DONE` workera (wzór:
 * `seedCorpus` w `e2e/helpers.ts`). Zwraca id bazy. Opcjonalny `relogin` odświeża token co
 * 10 min odpytywania: TTL access tokenu to 15 min (`WD_ACCESS_TOKEN_TTL_MIN`), a budżet zasiewu
 * 20 min — parsowanie GUS potrafi przeżyć ważność tokenu z początku zasiewu (T10).
 */
export async function seedExportDataset(
  request: APIRequestContext,
  token: string,
  name: string,
  relogin?: () => Promise<string>,
): Promise<string> {
  const headers = authHeaders(token)
  const dataset = await ragOk<{ id: string }>(
    request.post(`${API_URL}/api/v1/datasets`, { headers, data: { name } }),
    'POST /api/v1/datasets',
  )
  const corpus = [
    { dir: 'pdf', name: GUS_PDF_NAME, mime: 'application/pdf' },
    { dir: 'docx', name: NCBR_DOCX_NAME, mime: DOCX_MIME },
  ]
  const documentIds: string[] = []
  for (const file of corpus) {
    const uploaded = await ragOk<{ id: string }[]>(
      request.post(`${API_URL}/api/v1/datasets/${dataset.id}/documents`, {
        headers,
        multipart: {
          file: {
            name: file.name,
            mimeType: file.mime,
            buffer: readFileSync(corpusPath(file.dir, file.name)),
          },
        },
      }),
      `POST /datasets/{id}/documents (${file.name})`,
    )
    expect(uploaded, `upload ${file.name}: jeden dokument`).toHaveLength(1)
    documentIds.push(uploaded[0]!.id)
  }

  await ragOk<unknown>(
    request.post(`${API_URL}/api/v1/datasets/${dataset.id}/documents/parse`, {
      headers,
      data: { document_ids: documentIds },
    }),
    'POST /datasets/{id}/documents/parse',
  )

  const deadline = Date.now() + SEED_PARSE_BUDGET_MS
  const runs = new Map<string, string>()
  let currentToken = token
  let tokenIssuedAt = Date.now()
  while (Date.now() < deadline) {
    if (relogin !== undefined && Date.now() - tokenIssuedAt > 600_000) {
      currentToken = await relogin()
      tokenIssuedAt = Date.now()
    }
    const listed = await ragOk<{ docs: { id: string; run: string; chunk_count: number }[] }>(
      request.get(`${API_URL}/api/v1/datasets/${dataset.id}/documents?page=1&page_size=100`, {
        headers: authHeaders(currentToken),
      }),
      'GET /datasets/{id}/documents',
    )
    for (const doc of listed.docs) runs.set(doc.id, doc.run)
    // Stan końcowy = DONE/FAIL/CANCEL; „jakikolwiek run” (np. RUNNING) nie jest końcowy —
    // stary warunek rzucał porażkę już w pierwszej iteracji (T10 bieg 2).
    const settled = documentIds.every((id) => TERMINAL_RUNS.includes(runs.get(id) ?? ''))
    const done = documentIds.every((id) => runs.get(id) === 'DONE')
    if (settled && !done) {
      const states = documentIds.map((id) => `${id}=${runs.get(id)}`).join(', ')
      throw new Error(`parsowanie korpusu zakończone porażką: ${states}`)
    }
    if (done) return dataset.id
    await sleep(3_000)
  }
  throw new Error(`parsowanie korpusu: budżet ${SEED_PARSE_BUDGET_MS} ms minął (${[...runs]})`)
}

// --- Eksport przez API + pobranie paczki --------------------------------------------------------

/**
 * Eksportuje bazę z wektorami (K19 §3 trasa 2), czeka na `done` i pobiera paczkę podpisanym
 * linkiem **bez aktora** (trasa 5 — sam podpis; jednocześnie kontrola kontraktu linku).
 * Plik trafia do katalogu tymczasowego pod nazwą z `file_name`.
 */
export async function exportAndDownloadPackage(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  tag: string,
): Promise<ExportedPackage> {
  const headers = authHeaders(token)
  const ref = await wdOk<TaskRef>(
    request.post(`${API_URL}/api/wd/v1/datasets/${datasetId}/export`, {
      headers,
      data: { include_vectors: true },
    }),
    'POST /datasets/{id}/export',
    202,
  )
  const task = await waitTask(request, token, ref.task_id, EXPORT_TASK_BUDGET_MS)
  expect(
    task.status,
    `eksport API (${task.message}${task.error ? ` — ${task.error.message}` : ''})`,
  ).toBe('done')
  const result = task.result
  expect(result?.download_url, 'download_url w wyniku eksportu').toBeDefined()
  expect(result?.file_name, 'file_name w wyniku eksportu').toBeDefined()
  expect(result?.size_bytes, 'size_bytes w wyniku eksportu').toBeDefined()

  // Pobranie BEZ nagłówka Authorization — link ma działać bez logowania (K19 §3 trasa 5).
  const download = await request.get(`${API_URL}${result!.download_url}`)
  expect(download.status(), 'GET download_url bez aktora').toBe(200)
  const bytes = await download.body()
  expect(bytes.length, 'rozmiar pobranej paczki = size_bytes').toBe(result!.size_bytes)
  const filePath = path.join(tmpdir(), `wd-e2e-${tag}-${process.pid}-${result!.file_name}`)
  writeFileSync(filePath, bytes)
  return {
    taskId: ref.task_id,
    fileName: result!.file_name!,
    sizeBytes: result!.size_bytes!,
    filePath,
    downloadPath: result!.download_url!,
  }
}

// --- Konta i modele (sztafaż scenariuszy) -------------------------------------------------------

/** Zakłada konto przez API (`POST /api/wd/v1/users`, superuser); zwraca id. */
export async function createUserByApi(
  request: APIRequestContext,
  adminToken: string,
  email: string,
  password: string,
  nickname: string,
): Promise<string> {
  const user = await wdOk<{ id: string }>(
    request.post(`${API_URL}/api/wd/v1/users`, {
      headers: authHeaders(adminToken),
      data: { email, password, nickname },
    }),
    'POST /api/wd/v1/users',
    201,
  )
  return user.id
}

/** Logowanie dowolnym kontem przez API (wzór: `apiLogin` w `e2e/helpers.ts`). */
export async function loginToken(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<string> {
  const data = await ragOk<{ access_token: string }>(
    request.post(`${API_URL}/api/v1/auth/login`, {
      data: { email, password },
    }),
    'POST /api/v1/auth/login',
  )
  return data.access_token
}

/** Tworzy bazę wiedzy z jawnym `permission` (`me`|`team`) — SC-E7-2-05. */
export async function createDatasetWithPermission(
  request: APIRequestContext,
  token: string,
  name: string,
  permission: 'me' | 'team',
): Promise<string> {
  const dataset = await ragOk<{ id: string }>(
    request.post(`${API_URL}/api/v1/datasets`, {
      headers: authHeaders(token),
      data: { name, permission },
    }),
    'POST /api/v1/datasets (permission)',
  )
  return dataset.id
}

/** Lista id baz aktora o dokładnie podanej nazwie (RAGFlow `GET /datasets?name=`). */
export async function datasetIdsNamed(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string[]> {
  const response = await request.get(
    `${API_URL}/api/v1/datasets?name=${encodeURIComponent(name)}&page=1&page_size=100`,
    { headers: authHeaders(token) },
  )
  const text = await response.text()
  expect(response.status(), `GET /api/v1/datasets?name: HTTP ${response.status()} — ${text}`).toBe(
    200,
  )
  const body = JSON.parse(text) as {
    code: number
    message: string
    data?: { id: string; name: string }[]
  }
  // Upstream (DAS:449-457, backend/app/services/datasets.py `list`): filtr `name` bez
  // widocznego datasetu — także NIEISTNIEJĄCEGO — to code 102 „lacks permission for
  // dataset '<name>'", a nie pusta lista (zweryfikowane na stosie testowym). Brak bazy
  // o tej nazwie to dla sprzątania/sprawdzeń stan oczekiwany: pusto.
  if (body.code === 102) return []
  expect(body.code, `GET /api/v1/datasets?name: ${body.message}`).toBe(0)
  return (body.data ?? []).filter((row) => row.name === name).map((row) => row.id)
}

/** Usuwa bazy aktora o podanej nazwie — sprzątanie na starcie testu (retry-safe). */
export async function deleteDatasetsNamed(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<void> {
  const ids = await datasetIdsNamed(request, token, name)
  if (ids.length === 0) return
  await ragOk<unknown>(
    request.delete(`${API_URL}/api/v1/datasets`, {
      headers: authHeaders(token),
      data: { ids },
    }),
    'DELETE /api/v1/datasets (nazwa)',
  )
}

/**
 * Rejestruje model embeddingu o innym wymiarze (instancja dostawcy + `wd_dimension`,
 * wzór: `helpers/models.ts`) — SC-E7-2-03 krok 3. Zwraca id instancji (do sprzątania).
 */
export async function registerEmbeddingModel(
  request: APIRequestContext,
  token: string,
  instanceName: string,
  modelName: string,
  dimension: number,
): Promise<string> {
  const headers = authHeaders(token)
  await ragOk<unknown>(
    request.post(`${API_URL}/api/v1/providers/litellm/instances`, {
      headers,
      data: { instance_name: instanceName, base_url: 'http://fake-llm:8090/v1' },
    }),
    'POST /providers/litellm/instances',
  )
  const instances = await ragOk<{ id: string; instance_name: string }[]>(
    request.get(`${API_URL}/api/v1/providers/litellm/instances`, { headers }),
    'GET /providers/litellm/instances',
  )
  const instance = instances.find((entry) => entry.instance_name === instanceName)
  expect(instance, `instancja „${instanceName}” na liście`).toBeDefined()
  await ragOk<unknown>(
    request.post(`${API_URL}/api/v1/providers/litellm/instances/${instance!.id}/models`, {
      headers,
      data: { model_name: modelName, model_type: 'embedding', wd_dimension: dimension },
    }),
    'POST …/instances/{id}/models (embedding)',
  )
  return instance!.id
}

/** Usuwa instancję dostawcy (z jej modelami) — wzór: `deleteInstance` w `helpers/models.ts`. */
export async function deleteProviderInstance(
  request: APIRequestContext,
  token: string,
  instanceId: string,
): Promise<void> {
  await ragOk<unknown>(
    request.delete(`${API_URL}/api/v1/providers/litellm/instances`, {
      headers: authHeaders(token),
      data: { instances: [instanceId] },
    }),
    'DELETE /providers/litellm/instances',
  )
}

// --- Import przez API (stan wyjściowy SC-E7-2-03) ----------------------------------------------

/**
 * Importuje paczkę przez API (K19 §3 trasy 6, 7, 9): sesja + porcje 8 MiB z `Content-Range`
 * + start z podaną nazwą. Zwraca id powstałej bazy — stan „baza już istnieje” dla konfliktu
 * nazw w SC-E7-2-03, niezależny od przebiegu UI w SC-E7-2-02.
 */
export async function importPackageViaApi(
  request: APIRequestContext,
  token: string,
  pkg: ExportedPackage,
  name: string,
): Promise<string> {
  const headers = authHeaders(token)
  const imp = await wdOk<DatasetImport>(
    request.post(`${API_URL}/api/wd/v1/dataset-imports`, {
      headers,
      data: { file_name: pkg.fileName, size_bytes: pkg.sizeBytes },
    }),
    'POST /dataset-imports',
    201,
  )
  const bytes = readFileSync(pkg.filePath)
  const chunkSize = imp.chunk_size > 0 ? imp.chunk_size : 8_388_608
  let last: DatasetImport = imp
  for (let start = 0; start < bytes.length; start += chunkSize) {
    const end = Math.min(start + chunkSize, bytes.length)
    const part = bytes.subarray(start, end)
    last = await wdOk<DatasetImport>(
      request.put(`${API_URL}/api/wd/v1/dataset-imports/${imp.import_id}/content`, {
        headers: { ...headers, 'content-range': `bytes ${start}-${end - 1}/${bytes.length}` },
        data: part,
      }),
      `PUT /dataset-imports/{id}/content (${start})`,
    )
  }
  expect(last.state, `stan sesji po ostatniej porcji (${last.errors.map((e) => e.code)})`).toBe(
    'ready',
  )
  const ref = await wdOk<TaskRef>(
    request.post(`${API_URL}/api/wd/v1/dataset-imports/${imp.import_id}/start`, {
      headers,
      data: { name, embedding_model: null },
    }),
    'POST /dataset-imports/{id}/start',
    202,
  )
  const task = await waitTask(request, token, ref.task_id, IMPORT_TASK_BUDGET_MS)
  expect(
    task.status,
    `import API (${task.message}${task.error ? ` — ${task.error.message}` : ''})`,
  ).toBe('done')
  expect(task.result?.dataset_id, 'dataset_id w wyniku importu').toBeDefined()
  return task.result!.dataset_id!
}

/** Baza o nazwie paczki istnieje u aktora (z UI w SC-E7-2-02 albo tu przez API) — id. */
export async function ensureImportedDataset(
  request: APIRequestContext,
  token: string,
  pkg: ExportedPackage,
  name: string,
): Promise<string> {
  const existing = await datasetIdsNamed(request, token, name)
  if (existing.length > 0) return existing[0]!
  return importPackageViaApi(request, token, pkg, name)
}

/**
 * Usuwa sesję importu (K19 §3 trasa 10) — sprzątanie po przerwanym wysyłaniu. 404 jest tu
 * stanem oczekiwanym (SC-E7-2-04 b/c): sesja zużyta przez `start` albo już porzucona przez
 * dialog po twardym błędzie wysyłki — cel sprzątania (brak sesji) i tak osiągnięty.
 */
export async function deleteImportSession(
  request: APIRequestContext,
  token: string,
  importId: string,
): Promise<void> {
  const response = await request.delete(`${API_URL}/api/wd/v1/dataset-imports/${importId}`, {
    headers: authHeaders(token),
  })
  const text = await response.text()
  expect(
    response.status() === 200 || response.status() === 404,
    `DELETE /dataset-imports/{id}: HTTP ${response.status()} — ${text}`,
  ).toBe(true)
}

// --- Paczki uszkodzone (E7-1f nie ma fixture'ów w repo — budujemy wg K19 §2) --------------------

export type ZipEntry = { name: string; data: Buffer }

/**
 * Minimalny zapis ZIP (metoda STORE) na `node:zlib` — wystarczający dla walidatora K19 §5:
 * nagłówki lokalne, katalog centralny i EOCD; nazwy ASCII, rozmiary 32-bit.
 */
export function zipStore(entries: ZipEntry[]): Buffer {
  const local: Buffer[] = []
  const central: Buffer[] = []
  let offset = 0
  for (const entry of entries) {
    const nameBuf = Buffer.from(entry.name, 'utf8')
    const crc = zlib.crc32(entry.data) >>> 0
    const lh = Buffer.alloc(30)
    lh.writeUInt32LE(0x04034b50, 0)
    lh.writeUInt16LE(20, 4)
    lh.writeUInt32LE(crc, 14)
    lh.writeUInt32LE(entry.data.length, 18)
    lh.writeUInt32LE(entry.data.length, 22)
    lh.writeUInt16LE(nameBuf.length, 26)
    local.push(lh, nameBuf, entry.data)
    const ch = Buffer.alloc(46)
    ch.writeUInt32LE(0x02014b50, 0)
    ch.writeUInt16LE(20, 4)
    ch.writeUInt16LE(20, 6)
    ch.writeUInt32LE(crc, 16)
    ch.writeUInt32LE(entry.data.length, 20)
    ch.writeUInt32LE(entry.data.length, 24)
    ch.writeUInt16LE(nameBuf.length, 28)
    ch.writeUInt32LE(offset, 42)
    central.push(ch, nameBuf)
    offset += 30 + nameBuf.length + entry.data.length
  }
  const centralBuf = Buffer.concat(central)
  const eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(0x06054b50, 0)
  eocd.writeUInt16LE(entries.length, 8)
  eocd.writeUInt16LE(entries.length, 10)
  eocd.writeUInt32LE(centralBuf.length, 12)
  eocd.writeUInt32LE(offset, 16)
  return Buffer.concat([...local, centralBuf, eocd])
}

function sha256Hex(data: Buffer): string {
  return createHash('sha256').update(data).digest('hex')
}

/**
 * Buduje poprawną paczkę `.wdkb.zip` (K19 §2, schemat 1, jeden dokument tekstowy, bez wektorów)
 * z jedną celową wadą: przy `corruptChecksum` wpis `files/<sha>` ma w `entries` INNĄ sumę niż
 * rzeczywiste bajty → walidacja kończy się `checksum_mismatch`. Inaczej paczka jest zgodna.
 * `extraEntries` (SC-V12-02) dopisuje wpisy POZA manifestem — bezpieczna nazwa daje
 * `unexpected_entry`, niebezpieczna (np. `../x`) `unsafe_path`. `manifestOverride`
 * (SC-V12-06 k.4) podmienia manifest przed zapisem — np. usunięcie `embedding.included`
 * daje `manifest_invalid` z komunikatem „Niepoprawny manifest — pole …: Field required”.
 */
export function buildWdkbZip(options: {
  datasetName: string
  corruptChecksum?: boolean
  extraEntries?: ZipEntry[]
  manifestOverride?: (manifest: Record<string, unknown>) => Record<string, unknown>
}): Buffer {
  const content = Buffer.from(
    'Rocznik statystyczny przykład: liczba ludności Polski w 2023 roku wynosiła 37,7 mln.',
    'utf8',
  )
  const fileSha = sha256Hex(content)
  const manifest = {
    format: 'wdkb',
    schema_version: 1,
    wd_version: '0.0.0-e2e',
    created_at: '2026-10-12T21:00:00Z',
    source_instance_id: 'e2e'.padEnd(32, '0'),
    dataset: {
      name: options.datasetName,
      description: null,
      language: 'Polish',
      chunk_method: 'naive',
      parser_config: {},
      similarity_threshold: 0.2,
      vector_similarity_weight: 0.3,
      pagerank: 0,
    },
    embedding: { model_name: 'fake-embed-1024', dimension: 1024, included: false },
    counts: { documents: 1, chunks: 1, vectors: 0 },
    entries: [] as { path: string; sha256: string; size: number }[],
  }
  const documents = {
    ref: 'd1',
    name: 'przyklad.txt',
    type: 'doc',
    suffix: 'txt',
    size: content.length,
    file_sha256: fileSha,
    chunk_method: 'naive',
    parser_config: {},
    meta_fields: {},
    run: 'DONE',
    progress_msg: '',
    token_num: 16,
    chunk_num: 1,
  }
  const chunks = {
    ref: 'c1',
    document_ref: 'd1',
    ordinal: 0,
    chunk_type: 'text',
    content: 'Liczba ludności Polski w 2023 roku wynosiła 37,7 mln.',
    content_llm: '',
    keywords: [],
    questions: [],
    // K19 §2 / ChunkLine (kb_package/format.py): `tags` jest OBIEKTEM (mapą), nie listą —
    // lista wywala walidację paczki 500 przy ostatniej porcji (T10 bieg 2).
    tags: {},
    positions: [],
    page_from: 0,
    page_to: 0,
    image_sha256: null,
    parent_ref: null,
    available: true,
    // K19 §2 / ChunkLine + validate_content (EMBED_SOURCES): dozwolone „content” i „questions”;
    // ingest pisze „content”, gdy chunk nie ma pytań (MINOR z briefu T11: `''` odrzuca walidacja).
    embed_source: 'content',
    token_count: 16,
  }
  const documentsBuf = Buffer.from(`${JSON.stringify(documents)}\n`, 'utf8')
  const chunksBuf = Buffer.from(`${JSON.stringify(chunks)}\n`, 'utf8')
  const filePath = `files/${fileSha}`
  // Sumy wpisów: wszystkie zgodne, POZA files/<sha> przy corruptChecksum (cellowe 64 zera).
  manifest.entries = [
    { path: 'documents.jsonl', sha256: sha256Hex(documentsBuf), size: documentsBuf.length },
    { path: 'chunks.jsonl', sha256: sha256Hex(chunksBuf), size: chunksBuf.length },
    {
      path: filePath,
      sha256: options.corruptChecksum === true ? '0'.repeat(64) : fileSha,
      size: content.length,
    },
  ]
  const manifestValue: Record<string, unknown> =
    options.manifestOverride === undefined ? manifest : options.manifestOverride(manifest)
  const manifestBuf = Buffer.from(`${JSON.stringify(manifestValue, null, 2)}\n`, 'utf8')
  return zipStore([
    { name: 'manifest.json', data: manifestBuf },
    { name: 'documents.jsonl', data: documentsBuf },
    { name: 'chunks.jsonl', data: chunksBuf },
    { name: filePath, data: content },
    ...(options.extraEntries ?? []),
  ])
}

/** Bajty „paczki”, która nie jest archiwum ZIP — `.txt` przemianowany na `.wdkb.zip`. */
export function fakePackageBytes(): Buffer {
  return Buffer.from(
    'To nie jest archiwum ZIP — plik tekstowy przemianowany na .wdkb.zip (SC-E7-2-04 krok 2).',
    'utf8',
  )
}

// --- UI -----------------------------------------------------------------------------------------

/**
 * Upuszcza paczkę na strefę z prawdziwym `DataTransfer` (wzór: `helpers/dnd.ts`), ale bajty
 * NIE idą przez most CDP: paczka GUS ma ~74 MB, więc jest pobierana W STRONIE z podpisanego
 * linku eksportu (działa bez sesji — K19 §3 trasa 5) i z nich powstaje `File`.
 */
export async function dropPackageFromUrl(
  page: Page,
  dropzoneLocator: Locator,
  downloadPath: string,
  fileName: string,
): Promise<void> {
  const dataTransfer = await page.evaluateHandle(
    async (init: { url: string; name: string }) => {
      const response = await fetch(init.url)
      if (!response.ok) throw new Error(`pobieranie paczki w stronie: HTTP ${response.status}`)
      const file = new File([await response.arrayBuffer()], init.name, { type: 'application/zip' })
      const transfer = new DataTransfer()
      transfer.items.add(file)
      return transfer
    },
    { url: downloadPath, name: fileName },
  )
  await dropzoneLocator.dispatchEvent('dragenter', { dataTransfer })
  await dropzoneLocator.dispatchEvent('dragover', { dataTransfer })
  await dropzoneLocator.dispatchEvent('drop', { dataTransfer })
}

/**
 * Init-script pilnujący treści schowka na stosie HTTP (`navigator.clipboard` nie istnieje —
 * wzór: `s21-copy-dialog.spec.ts`): owija `execCommand('copy')` i zapamiętuje ZAZNACZONY tekst,
 * który realnie poszedł do schowka. Prawdziwe `execCommand` wykonuje się dalej.
 */
export function execCommandCopySpy(): Parameters<Page['addInitScript']>[0] {
  return () => {
    const original = document.execCommand.bind(document)
    ;(window as unknown as { __copiedText?: string }).__copiedText = ''
    document.execCommand = ((commandId: string, ...rest: unknown[]) => {
      if (commandId === 'copy') {
        ;(window as unknown as { __copiedText?: string }).__copiedText =
          document.getSelection()?.toString() ?? ''
      }
      return (original as (...args: unknown[]) => boolean)(commandId, ...rest)
    }) as typeof document.execCommand
  }
}

/** Odczyt tekstu zapamiętanego przez `execCommandCopySpy`. */
export async function copiedText(page: Page): Promise<string> {
  return page.evaluate(() => (window as unknown as { __copiedText?: string }).__copiedText ?? '')
}

/** Wstawka dla wyrażeń regularnych z nazw bazy (cudzysłowy „” są bezpieczne, nawiasy nie). */
export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * Czyszczenie wierszy paska zadań w localStorage (kontrakt E7-2 §6: klucz per aktora).
 * Sesja pliku (`storageState`) przenosi między kontekstami testów też localStorage, więc
 * wiersze z poprzednich testów („Gotowe” po eksportach/importach) wchodzą na bar kolejnego
 * testu i wywalają strict mode filtrów wierszy po nazwie bazy. Czyszczone na starcie testów
 * filtrujących wiersze; własne zadanie testu i tak tworzy wiersz od zera (a F5 w teście
 * nadal pokazuje trwałość — klucz żyje w ramach tego samego kontekstu).
 */
export async function clearKbTaskRows(page: Page): Promise<void> {
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('wd.kbTasks.v1:')) localStorage.removeItem(key)
    }
  })
}

/** Rodzina polskich form liczby mnogiej „chunk” (UI odmienia: 1 chunk / 2–4 chunki / 5+ chunków). */
export const CHUNK_WORD_RE = /chunk(i|ów|a)/
