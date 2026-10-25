// WP V13-1 T1 — SC-V13-01 k1–k4 (rocznik GUS) i SC-V13-02 k1–k4 (baza „Mix”) w przeglądarce
// na stosie produkcyjnym z nakładką fake-llm (tools/dev/clean-install.sh, WD_CI_SPEC=ten plik).
// Uruchomienie jak krok verify-real:
//   WD_CI_SPEC=s30-v13-1-mapa-bazy.spec.ts tools/dev/clean-install.sh
// Helpery i stałe asercji: helpers/s30-gus.ts (współdzielone z s30-v13-1-aktualizacja.spec.ts,
// T9). Testy są CZERWONE PRZED implementacją (K21): dziś log parsowania nie ma linii
// „Outline: …”, czat nie dostaje mapy bazy (fake-llm odpowiada blokiem wiedzy „Na podstawie
// źródeł…”), a po T2–T7 mają być zielone.
import { expect, test } from '@playwright/test'

import { expectNoLayoutDefects } from '../e2e/helpers/layout'

import {
  ANSWER_TIMEOUT_MS,
  AI_ACT_NAME,
  AI_ACT_SECTIONS,
  ACCESS_FORM_NAME,
  ACCESS_REPORT_NAME,
  ask,
  apiLogin,
  corpusFile,
  createChatViaApi,
  createDataset,
  datasetIdByName,
  documentRow,
  expectKnowledgeBaseMap,
  GUS_DATASET,
  GUS_NAME,
  GUS_PARSE_TIMEOUT_MS,
  GUS_SECTIONS,
  lastAnswer,
  loginAsAdmin,
  MIX_DATASET,
  MIX_NAMES,
  MIX_PARSE_TIMEOUT_MS,
  OUTLINE_PATTERNS,
  readParseLog,
  STRUCTURED_MD_NAME,
  uploadFiles,
} from './helpers/s30-gus'

// Bez trybu serial: test 2 korzysta z bazy „GUS” utworzonej w teście 1 (k4 — czat z dwiema
// bazami), ale tworzy ją PRZED pierwszą asercją testu 1, więc po porażce testu 1 (czerwień
// na braku funkcji) test 2 biegnie dalej i pokazuje własny powód czerwieni.
test('SC-V13-01 (real): mapa bazy na roczniku GUS — log, pełna mapa 28 działów, zwykłe pytanie', async ({
  page,
  request,
}) => {
  test.setTimeout(GUS_PARSE_TIMEOUT_MS + 900_000)
  const token = await apiLogin(request)

  await loginAsAdmin(page)
  await createDataset(page, GUS_DATASET)
  await uploadFiles(page, [corpusFile(GUS_NAME)])
  const row = documentRow(page, GUS_NAME)
  await expect(
    row.getByRole('button', { name: 'Sukces' }),
    `parsowanie rocznika dochodzi do „Sukces”`,
  ).toBeVisible({ timeout: GUS_PARSE_TIMEOUT_MS })

  // k1: „Log parsowania” pliku — linia spisu treści z zakładek PDF (K21 §2 p. 3).
  const log = await readParseLog(page, row.getByRole('button', { name: 'Sukces' }), GUS_NAME)
  expect(log, `linia „Outline: …” w logu rocznika`).toMatch(OUTLINE_PATTERNS[GUS_NAME]!)
  await expectNoLayoutDefects(page, 'lista plików bazy GUS po parsowaniu (widok dialogu zamknięty)')

  // Czat „Czat GUS” z bazą GUS (ustawienia przez API, kroki użytkownika w przeglądarce).
  const gusDatasetId = await datasetIdByName(request, token, GUS_DATASET)
  const chatId = await createChatViaApi(request, token, 'Czat GUS', [gusDatasetId])
  await page.goto(`/chat/${chatId}`)

  // k2: pytanie o bazę → fake-llm wymienia plik i wszystkie 28 działów (SCENARIOS SC-01 k2).
  await ask(page, 'Co zawiera twoja baza wiedzy? Na jakie tematy możesz udzielić informacji?')
  await expectKnowledgeBaseMap(page, GUS_SECTIONS)
  await expectNoLayoutDefects(page, 'czat GUS — odpowiedź z pełną mapą')

  // k3: inna formuła pytania o bazę rozpoznana tak samo (SCENARIOS SC-01 k3).
  await ask(page, 'Jakie działy ma rocznik?')
  await expectKnowledgeBaseMap(page, GUS_SECTIONS)

  // k4: zwykłe pytanie — bez regresji: odpowiedź ze źródeł, cytowanie klikalne, podgląd działa.
  await ask(page, 'Ile wynosiła ludność Polski w 2023 r.?')
  const answer = lastAnswer(page)
  await expect(answer, 'odpowiedź ze źródeł (format sprzed v1.3)').toContainText(
    'Na podstawie źródeł: ',
    { timeout: ANSWER_TIMEOUT_MS },
  )
  // Znacznik `[ID:n]` front zamienia na chip cytowania (DEC-243) — surowy tekst nie występuje
  // w DOM, więc asercją jest klikalny chip (wzorzec real-corpus, s07-chat-citations).
  // Po zakończeniu strumienia front unieważnia zapytanie sesji (useChatStream → refetch
  // GET …/sessions/<id>, ~65 ms po odpowiedzi; trace 2026-10-18) i podmienia wiadomość „live”
  // na serwerową — remount wiadomości resetuje lokalny stan modala cytowania (CitationChip
  // trzyma `open` w useState), więc klik tuż po odpowiedzi bywa w odczepiony element. Sieć
  // cichnie dopiero po tym refetchu — networkidle czeka na koniec przemontowania.
  await page.waitForLoadState('networkidle')
  const chip = answer.getByRole('button', { name: /^Cytowanie \d+$/ }).first()
  await expect(chip, 'chip cytowania').toBeVisible()
  await chip.click({ timeout: 10_000 })
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog, 'modal cytowania otwarty').toBeVisible()
  await expect(citeDialog, 'modal wskazuje rocznik').toContainText(GUS_NAME)
  await expectNoLayoutDefects(page, 'modal cytowania (pytanie zwykłe)')
  await citeDialog.getByRole('button', { name: 'Otwórz dokument' }).click({ timeout: 10_000 })
  await expect(citeDialog).toBeHidden()
  const preview = page.getByRole('dialog')
  await expect(preview, 'szuflada podglądu dokumentu otwarta').toBeVisible()
  await expect(preview, 'podgląd wskazuje rocznik').toContainText(GUS_NAME)
  // Szuflada wjeżdża animacją Slide (MUI kończy wejście z `transform: none`) — pomiar wad
  // układu dopiero po jej zakończeniu, inaczej off-screen łapie klatkę przejściową
  // (analogia do czekania na Fade w s07-chat-citations).
  await expect(preview).toHaveCSS('transform', 'none')
  await expectNoLayoutDefects(page, 'podgląd fragmentu rocznika')
  await page.keyboard.press('Escape')
  await expect(preview).toBeHidden()
})

test('SC-V13-02 (real): baza Mix — logi plików, wyłączenie DOCX, czat z dwiema bazami', async ({
  page,
  request,
}) => {
  test.setTimeout(MIX_PARSE_TIMEOUT_MS + 600_000)
  const token = await apiLogin(request)

  await loginAsAdmin(page)
  await createDataset(page, MIX_DATASET)
  await uploadFiles(
    page,
    MIX_NAMES.map((name) => corpusFile(name)),
  )
  for (const name of MIX_NAMES) {
    await expect(
      documentRow(page, name).getByRole('button', { name: 'Sukces' }),
      `parsowanie ${name} dochodzi do „Sukces”`,
    ).toBeVisible({ timeout: MIX_PARSE_TIMEOUT_MS })
  }

  // k1: log każdego pliku — linia „Outline: …” zgodna z plikiem (K21 §2 p. 3).
  for (const name of MIX_NAMES) {
    const log = await readParseLog(
      page,
      documentRow(page, name).getByRole('button', { name: 'Sukces' }),
      name,
    )
    expect(log, `linia „Outline: …” w logu ${name}`).toMatch(OUTLINE_PATTERNS[name]!)
  }

  // Czat z bazą Mix: „Jakie dokumenty masz w bazie?” — wszystkie 4 pliki i działy ustawy (k2).
  const mixDatasetId = await datasetIdByName(request, token, MIX_DATASET)
  const mixChatId = await createChatViaApi(request, token, 'Czat Mix', [mixDatasetId])
  await page.goto(`/chat/${mixChatId}`)
  await ask(page, 'Jakie dokumenty masz w bazie?')
  const mixAnswer = lastAnswer(page)
  await expect(mixAnswer, 'formuła odpowiedzi o bazie (K21 §6a)').toContainText('Baza zawiera: ', {
    timeout: ANSWER_TIMEOUT_MS,
  })
  for (const name of MIX_NAMES) {
    await expect(mixAnswer, `nazwa pliku ${name} w odpowiedzi`).toContainText(name)
  }
  for (const section of AI_ACT_SECTIONS) {
    await expect(mixAnswer, `dział ustawy „${section}” w odpowiedzi`).toContainText(section)
  }

  // k3: przełącznik „Włączony” wyłącza DOCX → ponowne pytanie bez niego, pozostałe 3 zostają.
  await page.goto(`/dataset/files/${mixDatasetId}`)
  const docxRow = documentRow(page, ACCESS_FORM_NAME)
  const enabledSwitch = docxRow.getByRole('switch', { name: 'Włączony' })
  await expect(enabledSwitch, 'DOCX włączony przed zmianą').toBeChecked()
  await enabledSwitch.click()
  await expect(enabledSwitch, 'DOCX wyłączony przełącznikiem').not.toBeChecked()
  await page.goto(`/chat/${mixChatId}`)
  await ask(page, 'Jakie dokumenty masz w bazie?')
  const afterDisable = lastAnswer(page)
  await expect(afterDisable, 'formuła odpowiedzi po wyłączeniu (K21 §6a)').toContainText(
    'Baza zawiera: ',
    { timeout: ANSWER_TIMEOUT_MS },
  )
  await expect(afterDisable, 'wyłączony DOCX nie występuje').not.toContainText(ACCESS_FORM_NAME)
  for (const name of [AI_ACT_NAME, ACCESS_REPORT_NAME, STRUCTURED_MD_NAME]) {
    await expect(afterDisable, `pozostały plik ${name} w odpowiedzi`).toContainText(name)
  }

  // Włączenie DOCX z powrotem — czat z dwiema bazami (k4) ma widzieć pełny katalog 5 dokumentów.
  await page.goto(`/dataset/files/${mixDatasetId}`)
  await enabledSwitch.click()
  await expect(enabledSwitch, 'DOCX włączony z powrotem').toBeChecked()

  // k4: czat z DWIEMA bazami (GUS + Mix) — 5 dokumentów. Sufiks „[<nazwa bazy>]” (K21 §3 p. 2)
  // trafia do promptu; fake-llm wymienia tytuły bez sufiksu, więc browserowa asercja sufiksów
  // nie dotyczy odpowiedzi (format z sufiksem pokrywa test integracyjny T5 w prompcie).
  const gusDatasetId = await datasetIdByName(request, token, GUS_DATASET)
  const bothChatId = await createChatViaApi(request, token, 'Czat GUS i Mix', [
    gusDatasetId,
    mixDatasetId,
  ])
  await page.goto(`/chat/${bothChatId}`)
  await ask(page, 'What documents do you have?')
  const bothAnswer = lastAnswer(page)
  await expect(bothAnswer, 'formuła odpowiedzi o bazie (K21 §6a)').toContainText('Baza zawiera: ', {
    timeout: ANSWER_TIMEOUT_MS,
  })
  for (const name of [GUS_NAME, ...MIX_NAMES]) {
    await expect(bothAnswer, `dokument ${name} w odpowiedzi z dwóch baz`).toContainText(name)
  }
  await expectNoLayoutDefects(page, 'czat z dwiema bazami — katalog 5 dokumentów')
})
