import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import {
  translateProgressLine,
  translateProgressLog,
  translateServerMessage,
} from './serverMessages'

// Pliki ładowane globem (jak w i18n/locales.test.ts) — bez resolveJsonModule.
type Locale = Record<string, string>

const bundles = import.meta.glob<Locale>('../locales/*/serverMsg.json', {
  eager: true,
  import: 'default',
})

const plMessages: Locale = bundles['../locales/pl/serverMsg.json'] ?? {}
const enMessages: Locale = bundles['../locales/en/serverMsg.json'] ?? {}

async function createT(language: 'pl' | 'en'): Promise<TFunction> {
  const instance = i18next.createInstance()
  await instance.init({
    lng: language,
    fallbackLng: 'pl',
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    resources: { [language]: { translation: language === 'pl' ? plMessages : enMessages } },
  })
  return instance.t
}

let tPl: TFunction
let tEn: TFunction

beforeAll(async () => {
  tPl = await createT('pl')
  tEn = await createT('en')
})

// Wiersze 1–26 i 28 INVENTORY (w. 27 = chat.defaultEmptyResponse w chat.json, CONTRACT (c)/DEC-356).
// EN domyślnie = tekst serwera dosłownie (niezmiennik z DEC-356: tłumaczenie przy języku EN
// renderuje oryginał 1:1); odchylenia tylko tam, gdzie brief/CONTRACT (c) je sankcjonują —
// wyjątkiem jest nieobsługiwany typ pliku (w. 1 i w. 2: jeden klucz dla obu ścieżek, EN
// „Unsupported file type: …”, sankcjonowane przez DEC-371).
interface ServerCase {
  code: number
  input: string
  pl: string
  en?: string
}

const SERVER_CASES: ServerCase[] = [
  // w. 1 — upload, jeden plik (przykład z briefu); EN ≠ tekst serwera (DEC-371)
  {
    code: 500,
    input: 'a.exe: This type of file has not been supported yet!',
    pl: 'Nieobsługiwany typ pliku: a.exe',
    en: 'Unsupported file type: a.exe',
  },
  // w. 1 — upload wielu plików: linie łączone „\n”, każda mapowana osobno
  {
    code: 500,
    input:
      'a.exe: This type of file has not been supported yet!\nb.exe: This type of file has not been supported yet!',
    pl: 'Nieobsługiwany typ pliku: a.exe\nNieobsługiwany typ pliku: b.exe',
    en: 'Unsupported file type: a.exe\nUnsupported file type: b.exe',
  },
  // w. 2 — ścieżka kliencka: inny tekst serwera, ten sam klucz co w. 1 (jedno źródło tekstu,
  // DEC-371); EN ≠ tekst serwera
  {
    code: 101,
    input: 'file type not supported: archiwum.tar.gz',
    pl: 'Nieobsługiwany typ pliku: archiwum.tar.gz',
    en: 'Unsupported file type: archiwum.tar.gz',
  },
  // w. 2 na ścieżce linku (/files → „Dodaj do bazy”, T5b): trasa link-to-datasets łapie
  // ValidationFailed z file_suffix i zwraca data_error — ten sam tekst z kodem 102
  {
    code: 102,
    input: 'file type not supported: setup.exe',
    pl: 'Nieobsługiwany typ pliku: setup.exe',
    en: 'Unsupported file type: setup.exe',
  },
  // SC-V13-04 k3 — za długa nazwa klucza API (EN = tekst serwera dosłownie)
  {
    code: 101,
    input: 'Token name must be at most 128 characters.',
    pl: 'Nazwa klucza może mieć najwyżej 128 znaków.',
  },
  // w. 3
  {
    code: 102,
    input: "Can't find the dataset with ID 0123456789abcdef0123456789abcdef!",
    pl: 'Nie można znaleźć zbioru o identyfikatorze 0123456789abcdef0123456789abcdef!',
  },
  // w. 4
  { code: 101, input: 'No file part!', pl: 'Brak pliku w żądaniu!' },
  { code: 101, input: 'No file selected!', pl: 'Nie wybrano pliku!' },
  // w. 5 — otoczka walidacyjna, Value ≠ Message (DEC-356: PL dostaje {{value}})
  {
    code: 102,
    input: "Field: <chunk_method> - Message: <`chunk_method` qa doesn't exist> - Value: <qa>",
    pl: 'Metoda chunkowania qa nie istnieje (wartość: qa)',
  },
  // w. 6
  {
    code: 102,
    input:
      "Field: <meta_fields> - Message: <The type is not supported: True> - Value: <{'akceptuj': True}>",
    pl: "Nieobsługiwany typ wartości metadanych: True (wartość: {'akceptuj': True})",
  },
  // w. 7
  {
    code: 102,
    input:
      "Field: <meta_fields> - Message: <The type is not supported in list: {'x': 1}> - Value: <{'tagi': [{'x': 1}]}>",
    pl: "Nieobsługiwany typ w liście metadanych: {'x': 1} (wartość: {'tagi': [{'x': 1}]})",
  },
  // w. 8
  {
    code: 101,
    input: "The extension of file can't be changed",
    pl: 'Nie można zmienić rozszerzenia pliku',
  },
  // w. 9
  {
    code: 102,
    input: 'Duplicated document name in the same dataset.',
    pl: 'Nazwa dokumentu już istnieje w tym zbiorze.',
  },
  // w. 10
  {
    code: 102,
    input: "can't change `token_count`",
    pl: 'Nie można zmienić pola token_count',
  },
  // w. 11 — wariant 0.27.2 (bez kropki)
  {
    code: 102,
    input: "the dataset doesn't own the document",
    pl: 'Ten zbiór nie zawiera tego dokumentu',
  },
  // w. 11 — wariant 0.24 z kropką pomijany (reguła 7 INVENTORY) → dosłownie
  {
    code: 102,
    input: "The dataset doesn't own the document.",
    pl: "The dataset doesn't own the document.",
  },
  // w. 12
  {
    code: 101,
    input: '`chunk_method` tag is not supported by Wawelsky Dragon',
    pl: 'Metoda chunkowania tag nie jest obsługiwana przez Wawelsky Dragon',
  },
  // w. 13
  {
    code: 101,
    input:
      "Field: <chunk_method> - Message: <Input should be 'naive', 'book', 'email', 'laws', 'manual', 'one', 'paper', 'picture', 'presentation', 'qa', 'table', 'tag' or 'resume'> - Value: <tag>",
    pl: 'Nieznana metoda chunkowania: tag. Dozwolone: naive, book, email, laws, manual, one, paper, picture, presentation, qa, table, tag, resume',
  },
  // w. 14
  {
    code: 101,
    input:
      'Field: <embedding_model> - Message: <embedding model identifier must follow <model_name>@<provider> format> - Value: <bogus>',
    pl: 'Identyfikator modelu embeddingu musi mieć format <model_name>@<provider> (wartość: bogus)',
  },
  // w. 15
  {
    code: 101,
    input:
      "Field: <parser_config> - Message: <Parser config exceeds size limit (max 65,535 characters). Current size: 70000> - Value: <{'chunk_token_num': 512, ...}>",
    pl: "Konfiguracja parsera przekracza limit 65 535 znaków (aktualnie: 70000, wartość: {'chunk_token_num': 512, ...}).",
  },
  // w. 16
  {
    code: 102,
    input: "Dataset name 'Nowy zbiór' already exists",
    pl: 'Zbiór o nazwie „Nowy zbiór” już istnieje',
  },
  // w. 17
  {
    code: 102,
    input: 'no properties were modified',
    pl: 'Nie zmieniono żadnych właściwości',
  },
  // w. 18 — czat: bez kropki (reguła 5: ≠ w. 3 i ≠ w. 28)
  {
    code: 102,
    input: "You don't own the dataset 0123456789abcdef0123456789abcdef",
    pl: 'Brak dostępu do zbioru 0123456789abcdef0123456789abcdef',
  },
  // w. 19
  {
    code: 102,
    input: "The dataset 0123456789abcdef0123456789abcdef doesn't own parsed file",
    pl: 'Zbiór 0123456789abcdef0123456789abcdef nie ma sparsowanych plików',
  },
  // w. 20
  {
    code: 102,
    input: "Datasets use different embedding models: ['bge-small@openai', 'e5@local']",
    pl: "Wybrane zbiory używają różnych modeli embeddingu: ['bge-small@openai', 'e5@local']",
  },
  // w. 21
  {
    code: 102,
    input: "`llm_id` m-123 doesn't exist",
    pl: 'Model m-123 (llm_id) nie istnieje',
  },
  {
    code: 102,
    input: "`rerank_id` r-9 doesn't exist",
    pl: 'Model r-9 (rerank_id) nie istnieje',
  },
  // w. 22
  {
    code: 102,
    input: 'duplicated chat name in creating chat',
    pl: 'Czat o tej nazwie już istnieje',
  },
  // w. 23
  {
    code: 102,
    input: 'duplicated chat name',
    pl: 'Czat o tej nazwie już istnieje',
  },
  // w. 24 — dwa z czterech szablonów mapowane (DEC-356: tylko gdy EN = tekst serwera)
  { code: 102, input: '`name` is required', pl: 'Nazwa czatu jest wymagana' },
  { code: 102, input: 'chat name must be a string', pl: 'Nieprawidłowa nazwa czatu' },
  // w. 24 — pozostałe dwa szablony → dosłownie (DEC-356)
  { code: 102, input: '`name` cannot be empty', pl: '`name` cannot be empty' },
  {
    code: 102,
    input: 'chat name length is 300 which is larger than 255',
    pl: 'chat name length is 300 which is larger than 255',
  },
  // w. 25 — EN = oryginał przez {{message}} (DEC-356)
  {
    code: 102,
    input: '`dataset_ids` should be a list.',
    pl: 'Nieprawidłowy typ pola żądania czatu (`dataset_ids` should be a list.)',
  },
  {
    code: 102,
    input: '`llm_setting` should be an object.',
    pl: 'Nieprawidłowy typ pola żądania czatu (`llm_setting` should be an object.)',
  },
  {
    code: 102,
    input: '`prompt_config` should be an object.',
    pl: 'Nieprawidłowy typ pola żądania czatu (`prompt_config` should be an object.)',
  },
  {
    code: 102,
    input: '`llm_id` must be a string',
    pl: 'Nieprawidłowy typ pola żądania czatu (`llm_id` must be a string)',
  },
  // w. 26
  {
    code: 102,
    input: '`parameters` contains duplicate key: top_k',
    pl: 'Parametr top_k powtarza się w konfiguracji promptu',
  },
  // w. 28 — profil odmowy datasets_update (reguła 5: ≠ w. 3 i ≠ w. 18)
  {
    code: 102,
    input: "User 'admin' lacks permission for dataset 'fedcba9876543210fedcba9876543210'",
    pl: 'Brak dostępu do zbioru fedcba9876543210fedcba9876543210 (użytkownik admin)',
  },
  // Nieznane komunikaty → dosłownie (nigdy „Nieznany błąd”; przykład z briefu)
  { code: 101, input: 'bogus', pl: 'bogus' },
  {
    code: 500,
    input: 'Planetary alignment interfered with the request',
    pl: 'Planetary alignment interfered with the request',
  },
  // Pusty komunikat → ''
  { code: 500, input: '', pl: '' },
  // w. 27 — treść odpowiedzi czatu, nie koperta: poza serverMsg (CONTRACT (c)) → dosłownie
  {
    code: 200,
    input: 'Sorry! No relevant content was found in the knowledge base!',
    pl: 'Sorry! No relevant content was found in the knowledge base!',
  },
]

interface ProgressCase {
  input: string
  pl: string
  en?: string
}

// P1–P29 (bez P18 — jego treść mapowana po szablonach P19–P29); EN = oryginał workera,
// odchylenia tylko dla plurala „Auto metadata” (brief, CONTRACT (c)).
const PROGRESS_CASES: ProgressCase[] = [
  { input: 'Task has been received.', pl: 'Zadanie przyjęte.' }, // P1
  { input: 'Reused previous chunks.', pl: 'Użyto ponownie poprzednich fragmentów.' }, // P2
  {
    input: 'OCR concurrency: 4 (qwen2-vl-7b)',
    pl: 'Współbieżność OCR: 4 (qwen2-vl-7b)',
  }, // P3
  { input: 'Converting pages 3/10', pl: 'Konwertowanie stron 3/10' }, // P4
  {
    input: 'Converted 7 pages (text layer)',
    pl: 'Skonwertowano 7 stron (warstwa tekstowa)',
  }, // P5
  {
    input: 'Converted 7 pages (3 to recognize)',
    pl: 'Skonwertowano 7 stron (3 to recognize)',
  }, // P6
  { input: 'OCR pages 2/8 (qwen2-vl-7b)', pl: 'OCR stron 2/8 (qwen2-vl-7b)' }, // P7
  {
    input: 'OCR finished: 8 pages (qwen2-vl-7b)',
    pl: 'OCR zakończone: 8 stron (qwen2-vl-7b)',
  }, // P8
  {
    input: '[WARNING] PDF uses embedded fonts',
    pl: '[OSTRZEŻENIE] PDF uses embedded fonts',
  }, // P9
  { input: 'Generate 12 chunks', pl: 'Generowanie 12 fragmentów' }, // P10
  {
    input: 'Keywords generation for 12 chunks',
    pl: 'Generowanie słów kluczowych dla 12 fragmentów',
  }, // P11
  {
    input: 'Question generation for 12 chunks',
    pl: 'Generowanie pytań dla 12 fragmentów',
  }, // P12
  { input: 'Embedding chunks (4/12)', pl: 'Osadzanie fragmentów (4/12)' }, // P13
  {
    input: 'Auto metadata: 0 fields',
    pl: 'Metadane automatyczne: nie znaleziono wartości',
    en: 'Auto metadata: no values found',
  }, // P14 (0)
  {
    input: 'Auto metadata: 1 fields',
    pl: 'Metadane automatyczne: 1 pole',
    en: 'Auto metadata: 1 field',
  }, // P14 (1, plural i18next)
  { input: 'Auto metadata: 2 fields', pl: 'Metadane automatyczne: 2 pola' }, // P14 (2, _few)
  { input: 'Auto metadata: 5 fields', pl: 'Metadane automatyczne: 5 pól' }, // P14 (5, _many)
  {
    input: 'Auto metadata failed: connection reset',
    pl: 'Automatyczne metadane nie powiodły się: connection reset',
  }, // P15
  {
    input: 'Indexing done (3.42s). Done.',
    pl: 'Indeksowanie zakończone (3.42 s). Gotowe.',
  }, // P16
  { input: 'Task has been cancelled.', pl: 'Zadanie anulowane.' }, // P17
  {
    input: 'No text could be extracted: scanned pages without text layer',
    pl: 'Nie udało się wyodrębnić tekstu: scanned pages without text layer',
  }, // P19
  {
    input: 'File is password-protected (.pdf)',
    pl: 'Plik jest chroniony hasłem (.pdf)',
  }, // P20
  {
    input: 'File is corrupted or unreadable (.docx): archive error',
    pl: 'Plik jest uszkodzony lub nieczytelny (.docx): archive error',
  }, // P21
  {
    input: 'Unsupported file format: cad',
    pl: 'Nieobsługiwany format pliku: cad',
  }, // P22
  {
    input: 'Limit exceeded: pages 1200 > 1000',
    pl: 'Przekroczono limit: pages 1200 > 1000',
  }, // P23
  {
    input: 'Parsing timed out after 90 s',
    pl: 'Parsowanie przekroczyło limit czasu (90 s)',
  }, // P24
  {
    input: "Required program 'pdftoppm' is not installed; use the worker-ocr image",
    pl: 'Wymagany program „pdftoppm” nie jest zainstalowany; użyj obrazu worker-ocr',
  }, // P25
  {
    input:
      'Conversion process terminated abruptly (out of memory? document too large for worker memory limit WD_WORKER_MEM_LIMIT)',
    pl: 'Proces konwersji zakończył się awaryjnie (brak pamięci? dokument za duży dla limitu pamięci workera WD_WORKER_MEM_LIMIT)',
  }, // P26
  { input: "document too large for 'one'", pl: 'Dokument za duży dla metody „one”' }, // P27
  {
    input: 'chunk_method qa is not supported by this server',
    pl: 'Metoda chunkowania qa nie jest obsługiwana przez ten serwer',
  }, // P28 (treść po „[ERROR] ”)
  {
    input: 'cannot change file type: pdf -> docx',
    pl: 'Nie można zmienić typu pliku: pdf -> docx',
  }, // P29
  // SC-V13-14 (K21 §2 p. 3) — „Outline: …” (spis treści); EN = tekst workera dosłownie
  {
    input: 'Outline: 678 entries (PDF bookmarks)',
    pl: 'Spis treści: 678 pozycji (zakładki PDF)',
  },
  {
    input: 'Outline: 12 entries (headings)',
    pl: 'Spis treści: 12 pozycji (nagłówki)',
  },
  {
    input: 'Outline: none (no bookmarks or headings)',
    pl: 'Spis treści: brak (dokument bez zakładek i nagłówków)',
  },
  // plural i18next (jak P14): 1 → „pozycja”, 2–4 → „pozycje”
  {
    input: 'Outline: 1 entries (headings)',
    pl: 'Spis treści: 1 pozycja (nagłówki)',
    en: 'Outline: 1 entries (headings)',
  },
  {
    input: 'Outline: 3 entries (PDF bookmarks)',
    pl: 'Spis treści: 3 pozycje (zakładki PDF)',
  },
  // Linia może być jedną z wielu w wielowierszowym progress_msg — prefiks czasu zostaje
  {
    input: '12:03:04 Outline: 678 entries (PDF bookmarks)',
    pl: '12:03:04 Spis treści: 678 pozycji (zakładki PDF)',
    en: '12:03:04 Outline: 678 entries (PDF bookmarks)',
  },
  // Nieznana treść → dosłownie
  { input: 'Something novel happened', pl: 'Something novel happened' },
  // Prefiks czasu zostaje (przykład z briefu)
  {
    input: '12:03:04 Auto metadata: 0 fields',
    pl: '12:03:04 Metadane automatyczne: nie znaleziono wartości',
    en: '12:03:04 Auto metadata: no values found',
  },
  // Prefiksy czasu i [ERROR] zostają, treść tłumaczona
  {
    input: '12:03:04 [ERROR] File is password-protected (.pdf)',
    pl: '12:03:04 [ERROR] Plik jest chroniony hasłem (.pdf)',
  },
  // [ERROR] bez prefiksu czasu
  {
    input: '[ERROR] chunk_method qa is not supported by this server',
    pl: '[ERROR] Metoda chunkowania qa nie jest obsługiwana przez ten serwer',
  },
  // Nieznana treść z prefiksami → dosłownie z prefiksami
  {
    input: '09:00:00 [ERROR] Something novel happened',
    pl: '09:00:00 [ERROR] Something novel happened',
  },
]

describe('translateServerMessage — wiersze 1–28 INVENTORY', () => {
  for (const { code, input, pl, en = input } of SERVER_CASES) {
    const label = `[${code}] ${input.length > 72 ? `${input.slice(0, 72)}…` : input}`
    it(label, () => {
      expect(translateServerMessage(code, input, tPl)).toBe(pl)
      // Niezmiennik DEC-356: przy języku EN komunikat wraca 1:1 (sankcjonowane wyjątki mają
      // własne „en”).
      expect(translateServerMessage(code, input, tEn)).toBe(en)
    })
  }
})

describe('translateProgressLine — wpisy P1–P29 INVENTORY', () => {
  for (const { input, pl, en = input } of PROGRESS_CASES) {
    it(input.length > 72 ? `${input.slice(0, 72)}…` : input, () => {
      expect(translateProgressLine(input, tPl)).toBe(pl)
      expect(translateProgressLine(input, tEn)).toBe(en)
    })
  }
})

// Regexy z speców e2e-real czytających log z DIALOGU UI (T9: real-stop-progress,
// real-concurrency, real-ingest-retry). Dialog tłumaczy wpisy worka (T3b), więc asercje
// speców trzymają brzmienia PL z locales/pl/serverMsg.json — ten test strzeże ich zgodności:
// zmiana tłumaczenia bez aktualizacji speców (albo odwrotnie) robi tu czerwień.
const SPEC_LOG_REGEX_CASES: { line: string; regex: RegExp }[] = [
  // P1 — „Zadanie przyjęte.” (concurrency/retry: granica renderu; stop-progress: próg 2%)
  { line: '12:03:04 Task has been received.', regex: /Zadanie przyjęte\./ },
  // P3 — „Współbieżność OCR: N” (concurrency SC-01/SC-03)
  { line: '12:03:04 OCR concurrency: 8 (fake-ocr)', regex: /Współbieżność OCR: 8/ },
  // P4 — „Konwertowanie stron d/745” (stop-progress: ≥ 5 wpisów, Stop w fazie konwersji)
  { line: '12:03:04 Converting pages 3/745', regex: /Konwertowanie stron \d+\/745/ },
  // P6 — „Skonwertowano N stron …” (stop-progress: koniec konwersji; concurrency: faza OCR)
  { line: '12:03:04 Converted 745 pages (0 to recognize)', regex: /Skonwertowano 745 stron/ },
  // P5 — wariant z warstwą tekstową, ten sam regex speców
  { line: '12:03:04 Converted 7 pages (text layer)', regex: /Skonwertowano 7 stron/ },
  // P7 — „OCR stron n/N” (stop-progress SC-06: tani koniec pętli pomiarowej)
  { line: '12:03:04 OCR pages 2/8 (fake-ocr)', regex: /OCR stron \d+\/\d+/ },
  // P8 — „OCR zakończone” (concurrency: koniec fazy OCR)
  { line: '12:03:04 OCR finished: 8 pages (fake-ocr)', regex: / OCR zakończone/ },
  // P10 — „Generowanie N fragmentów” (retry: licznik chunków, granica embeddingu)
  { line: '12:03:04 Generate 12 chunks', regex: /Generowanie (\d+) fragmentów/ },
  // P13 — „Osadzanie fragmentów (d/N)” (concurrency: koniec embeddingu)
  { line: '12:03:04 Embedding chunks (4/12)', regex: / Osadzanie fragmentów \(\d+\/\d+\)/ },
  // P16 — „Indeksowanie zakończone” (concurrency/retry: koniec zadania)
  { line: '12:03:04 Indexing done (3.42s). Done.', regex: / Indeksowanie zakończone/ },
  // P17 — „Zadanie anulowane.” (stop-progress SC-01: dokładnie jeden i ostatni wpis logu)
  { line: '12:03:04 Task has been cancelled.', regex: /Zadanie anulowane\./ },
]

describe('regexy logu parsowania z e2e-real vs tłumaczenie PL', () => {
  for (const { line, regex } of SPEC_LOG_REGEX_CASES) {
    it(`${regex} ← ${line}`, () => {
      expect(regex.test(translateProgressLine(line, tPl)), `${regex} vs „${line}”`).toBe(true)
    })
  }

  // Wpisy poza tabelą P1–P29 (ponowienia rate_limit.py, bilans cache OCR) zostają dosłownie —
  // asercje real-ingest-retry trzymają ich angielskie brzmienie.
  it('wpisy spoza P1–P29 bez tłumaczenia (asercje EN w real-ingest-retry)', () => {
    const raw = '12:03:04 Embedding provider error 502 — retry 1/2 in 12s'
    expect(translateProgressLine(raw, tPl)).toBe(raw)
  })
})

// T10 (QA V12-2-1 D2b): worker pisze „[ERROR] <NazwaKlasy>: <treść>” (queue.py fail), np.
// „[ERROR] CorruptedFile: File is corrupted or unreadable (.docx): …” — prefiks klasy wyjątku
// (parsing/worker/chunking errors.py) blokował dopasowanie P19–P28. Znana treść → tłumaczenie
// BEZ nazwy klasy; nieznana → linia dosłownie (z klasą).
interface ErrorClassCase {
  input: string
  pl: string
  en: string
}

const ERROR_CLASS_CASES: ErrorClassCase[] = [
  // P19 — EmptyDocument
  {
    input: '07:00:01 [ERROR] EmptyDocument: No text could be extracted: scanned pages',
    pl: '07:00:01 [ERROR] Nie udało się wyodrębnić tekstu: scanned pages',
    en: '07:00:01 [ERROR] No text could be extracted: scanned pages',
  },
  // P20 — EncryptedFile
  {
    input: '[ERROR] EncryptedFile: File is password-protected (.pdf)',
    pl: '[ERROR] Plik jest chroniony hasłem (.pdf)',
    en: '[ERROR] File is password-protected (.pdf)',
  },
  // P21 — CorruptedFile (przykład z QA: PL bez „CorruptedFile”, reason dosłownie)
  {
    input:
      '08:00:04 [ERROR] CorruptedFile: File is corrupted or unreadable (.docx): file content does not match its extension',
    pl: '08:00:04 [ERROR] Plik jest uszkodzony lub nieczytelny (.docx): file content does not match its extension',
    en: '08:00:04 [ERROR] File is corrupted or unreadable (.docx): file content does not match its extension',
  },
  // P22 — UnsupportedFormat
  {
    input: '[ERROR] UnsupportedFormat: Unsupported file format: cad',
    pl: '[ERROR] Nieobsługiwany format pliku: cad',
    en: '[ERROR] Unsupported file format: cad',
  },
  // P23 — LimitExceeded
  {
    input: '[ERROR] LimitExceeded: Limit exceeded: pages 1200 > 1000',
    pl: '[ERROR] Przekroczono limit: pages 1200 > 1000',
    en: '[ERROR] Limit exceeded: pages 1200 > 1000',
  },
  // P24 — ParseTimeout
  {
    input: '[ERROR] ParseTimeout: Parsing timed out after 90 s',
    pl: '[ERROR] Parsowanie przekroczyło limit czasu (90 s)',
    en: '[ERROR] Parsing timed out after 90 s',
  },
  // P25 — BinaryMissing
  {
    input:
      "[ERROR] BinaryMissing: Required program 'pdftoppm' is not installed; use the worker-ocr image",
    pl: '[ERROR] Wymagany program „pdftoppm” nie jest zainstalowany; użyj obrazu worker-ocr',
    en: "[ERROR] Required program 'pdftoppm' is not installed; use the worker-ocr image",
  },
  // P26 — TransientError (POOL_BROKEN_MESSAGE z worker/errors.py)
  {
    input:
      '[ERROR] TransientError: Conversion process terminated abruptly (out of memory? document too large for worker memory limit WD_WORKER_MEM_LIMIT)',
    pl: '[ERROR] Proces konwersji zakończył się awaryjnie (brak pamięci? dokument za duży dla limitu pamięci workera WD_WORKER_MEM_LIMIT)',
    en: '[ERROR] Conversion process terminated abruptly (out of memory? document too large for worker memory limit WD_WORKER_MEM_LIMIT)',
  },
  // P27 — DocumentTooLarge
  {
    input: "[ERROR] DocumentTooLarge: document too large for 'one'",
    pl: '[ERROR] Dokument za duży dla metody „one”',
    en: "[ERROR] document too large for 'one'",
  },
  // P28 — UnsupportedChunkMethod
  {
    input: '[ERROR] UnsupportedChunkMethod: chunk_method qa is not supported by this server',
    pl: '[ERROR] Metoda chunkowania qa nie jest obsługiwana przez ten serwer',
    en: '[ERROR] chunk_method qa is not supported by this server',
  },
  // Nieznana treść z klasą → linia dosłownie, klasa zostaje
  {
    input: '09:00:00 [ERROR] SomethingNovel: entirely unknown trouble',
    pl: '09:00:00 [ERROR] SomethingNovel: entirely unknown trouble',
    en: '09:00:00 [ERROR] SomethingNovel: entirely unknown trouble',
  },
]

describe('translateProgressLine — prefiks klasy wyjątku po [ERROR] (T10)', () => {
  for (const { input, pl, en } of ERROR_CLASS_CASES) {
    it(input.length > 72 ? `${input.slice(0, 72)}…` : input, () => {
      expect(translateProgressLine(input, tPl)).toBe(pl)
      expect(translateProgressLine(input, tEn)).toBe(en)
    })
  }
})

describe('translateProgressLog', () => {
  it('mapuje każdą linię osobno i łączy wynik „\\n”', () => {
    const text = [
      '12:03:04 Auto metadata: 0 fields',
      '12:03:05 [ERROR] File is password-protected (.pdf)',
      '12:03:06 Outline: 678 entries (PDF bookmarks)',
      'Something novel happened',
    ].join('\n')
    expect(translateProgressLog(text, tPl)).toBe(
      [
        '12:03:04 Metadane automatyczne: nie znaleziono wartości',
        '12:03:05 [ERROR] Plik jest chroniony hasłem (.pdf)',
        '12:03:06 Spis treści: 678 pozycji (zakładki PDF)',
        'Something novel happened',
      ].join('\n'),
    )
  })

  it('pusty tekst → pusty tekst', () => {
    expect(translateProgressLog('', tPl)).toBe('')
  })
})

describe('serverMsg.json — spójność', () => {
  it('pl i en mają identyczny zbiór kluczy', () => {
    expect(Object.keys(plMessages).sort()).toEqual(Object.keys(enMessages).sort())
  })

  it('wszystkie klucze mają prefiks „serverMsg.”', () => {
    for (const key of Object.keys(plMessages)) {
      expect(key.startsWith('serverMsg.'), key).toBe(true)
    }
  })
})
