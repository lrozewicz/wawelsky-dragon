// Wzorce i stałe komunikatów serwera (INVENTORY WP V12-2, work/wp/V12-2/INVENTORY.md;
// rozstrzygnięcia DEC-356) — wydzielone z serverMessages.ts ze względu na limit 300 linii.
// Kolejność wpisów = kolejność sprawdzania: pierwsze trafienie wygrywa.

// Otoczka walidacyjna upstream: `Field: <{field}> - Message: <{msg}> - Value: <{value}>`
// (backend/app/api/ragflow/messages.py, format_validation_error w normalize/common.py;
// value = str(input) przycięty do 125 znaków + „...”).
export const ENVELOPE_RE = /^Field: <([^>]*)> - Message: <(.*)> - Value: <(.*)>$/

// w. 1 — upload wielu plików: `{filename}: {MSG}` łączone „\n” (reguła 3 INVENTORY).
export const UNSUPPORTED_SUFFIX = 'This type of file has not been supported yet!'

export interface Pattern {
  // Kod koperty (101 = ARGUMENT_ERROR, 102 = DATA_ERROR, 500 = SERVER_ERROR);
  // wpisy logu parsowania (progress_msg) nie niosą kodu — bez filtru.
  code?: number
  // Bez flagi „g” — exec jest stateful dla wzorców globalnych.
  re: RegExp
  key: string
  // Nazwy parametrów dla grup 1..n; grupa zagnieżdżona nie dostaje nazwy.
  groups: readonly string[]
}

export interface Constant {
  code?: number
  text: string
  key: string
}

// Wiersze z danymi użytkownika wyłapywane wzorcem z kotwicami (reguły 3–5 INVENTORY).
export const PATTERNS: readonly Pattern[] = [
  // w. 2 — file_suffix (ingest.py). Inny tekst serwera niż w. 1, ten sam klucz — jedno
  // źródło tekstu PL/EN dla obu ścieżek (DEC-371). Trasa /files/link-to-datasets łapie
  // ValidationFailed z file_suffix i zwraca data_error (102) — stąd druga wpis z kodem 102
  // (empiria T5b); 101 zostaje dla ścieżek, gdzie wyjątek wychodzi bez owinięcia trasy.
  {
    code: 101,
    re: /^file type not supported: (.+)$/,
    key: 'serverMsg.fileTypeUnsupported',
    groups: ['filename'],
  },
  {
    code: 102,
    re: /^file type not supported: (.+)$/,
    key: 'serverMsg.fileTypeUnsupported',
    groups: ['filename'],
  },
  // w. 3 — upload do zbioru, który nie istnieje
  {
    code: 102,
    re: /^Can't find the dataset with ID (.+)!$/,
    key: 'serverMsg.datasetNotFound',
    groups: ['datasetId'],
  },
  // w. 28 — profil odmowy datasets_update (brak zbioru i cudzy zbiór mają ten sam komunikat)
  {
    code: 102,
    re: /^User '(.+)' lacks permission for dataset '(.+)'$/,
    key: 'serverMsg.datasetLacksPermission',
    groups: ['userId', 'datasetId'],
  },
  // w. 10 — pola niezmiennych dokumentu
  { code: 102, re: /^can't change `(.+)`$/, key: 'serverMsg.fieldImmutable', groups: ['field'] },
  // w. 12 — odrzucone metody chunkowania datasetu
  {
    code: 101,
    re: /^`chunk_method` (.+) is not supported by Wawelsky Dragon$/,
    key: 'serverMsg.chunkMethodUnsupported',
    groups: ['chunkMethod'],
  },
  // w. 16 — duplikat nazwy zbioru (nazwa jest danymi, stąd wzorzec zamiast ===)
  {
    code: 102,
    re: /^Dataset name '(.*)' already exists$/,
    key: 'serverMsg.datasetNameExists',
    groups: ['name'],
  },
  // w. 18 — czat: zbiór nie należy do użytkownika (bez kropki; reguła 5)
  {
    code: 102,
    re: /^You don't own the dataset ([0-9a-f]{32})$/,
    key: 'serverMsg.chatDatasetNoAccess',
    groups: ['datasetId'],
  },
  // w. 19 — czat: zbiór bez sparsowanych plików
  {
    code: 102,
    re: /^The dataset ([0-9a-f]{32}) doesn't own parsed file$/,
    key: 'serverMsg.chatDatasetNotParsed',
    groups: ['datasetId'],
  },
  // w. 20 — czat: różne modele embeddingu
  {
    code: 102,
    re: /^Datasets use different embedding models: (.+)$/,
    key: 'serverMsg.chatDatasetsMixedEmbeddings',
    groups: ['list'],
  },
  // w. 21 — czat: model nie istnieje (PL zachowuje nazwę pola technicznego; reguła 6)
  {
    code: 102,
    re: /^`(llm_id|rerank_id)` (.+) doesn't exist$/,
    key: 'serverMsg.chatModelNotExist',
    groups: ['field', 'value'],
  },
  // w. 26 — duplikat klucza parameters promptu
  {
    code: 102,
    re: /^`parameters` contains duplicate key: (.+)$/,
    key: 'serverMsg.chatParameterDuplicate',
    groups: ['key'],
  },
  // w. 25 — złe typy pól żądania czatu; EN renderuje oryginał przez {{message}} (DEC-356)
  {
    code: 102,
    re: /^(`(?:dataset_ids|llm_setting|prompt_config)` should be (?:a list|an object)\.)$/,
    key: 'serverMsg.chatFieldInvalid',
    groups: ['message'],
  },
  {
    code: 102,
    re: /^(`(?:llm_id|rerank_id)` must be a string)$/,
    key: 'serverMsg.chatFieldInvalid',
    groups: ['message'],
  },
]

// Wiersze krótkie, stałe — pełne porównanie po kodzie (reguła 4 INVENTORY).
export const CONSTANTS: readonly Constant[] = [
  { code: 101, text: 'No file part!', key: 'serverMsg.noFilePart' }, // w. 4
  { code: 101, text: 'No file selected!', key: 'serverMsg.noFileSelected' }, // w. 4
  {
    code: 101,
    text: "The extension of file can't be changed",
    key: 'serverMsg.extensionImmutable',
  }, // w. 8
  {
    code: 102,
    text: 'Duplicated document name in the same dataset.',
    key: 'serverMsg.duplicatedDocumentName',
  }, // w. 9
  // w. 11 — wariant 0.27.2 (bez kropki); wariant 0.24 z kropką pomijamy (reguła 7)
  { code: 102, text: "the dataset doesn't own the document", key: 'serverMsg.documentNotOwned' },
  { code: 102, text: 'no properties were modified', key: 'serverMsg.noPropertiesModified' }, // w. 17
  {
    code: 102,
    text: 'duplicated chat name in creating chat',
    key: 'serverMsg.chatNameDuplicateCreate',
  }, // w. 22
  { code: 102, text: 'duplicated chat name', key: 'serverMsg.chatNameDuplicate' }, // w. 23
  { code: 102, text: '`name` is required', key: 'serverMsg.chatNameRequired' }, // w. 24
  { code: 102, text: 'chat name must be a string', key: 'serverMsg.chatNameInvalid' }, // w. 24
  // SC-V13-04 k3 — za długa nazwa klucza API (system/tokens, code 101)
  {
    code: 101,
    text: 'Token name must be at most 128 characters.',
    key: 'serverMsg.tokenNameTooLong',
  },
]

// Wpisy progress_msg (K20 §5 p. 4; INVENTORY P1–P29). Linia ma opcjonalny prefiks
// czasu „HH:MM:SS ” i/lub „[ERROR] ” — zostają bez zmian, tłumaczona jest treść.
// „[WARNING]” jest częścią samego szablonu P9 (tłumaczone na „[OSTRZEŻENIE]”).
export const PROGRESS_PATTERNS: readonly Pattern[] = [
  // P3
  {
    re: /^OCR concurrency: (.+) \((.*)\)$/,
    key: 'serverMsg.progressOcrConcurrency',
    groups: ['n', 'model'],
  },
  // P4
  {
    re: /^Converting pages (\d+)\/(\d+)$/,
    key: 'serverMsg.progressConvertingPages',
    groups: ['done', 'total'],
  },
  // P5 — specjalny wariant P6 z końcówką „(text layer)”; musi być sprawdzony pierwszy
  {
    re: /^Converted (\d+) pages \(text layer\)$/,
    key: 'serverMsg.progressConvertedTextLayer',
    groups: ['n'],
  },
  // P6
  {
    re: /^Converted (\d+) pages (.+)$/,
    key: 'serverMsg.progressConvertedPages',
    groups: ['n', 'tail'],
  },
  // P7
  {
    re: /^OCR pages (\d+)\/(\d+) \((.*)\)$/,
    key: 'serverMsg.progressOcrPages',
    groups: ['done', 'total', 'name'],
  },
  // P8
  {
    re: /^OCR finished: (\d+) pages \((.*)\)$/,
    key: 'serverMsg.progressOcrFinished',
    groups: ['total', 'name'],
  },
  // P9
  { re: /^\[WARNING\] (.+)$/, key: 'serverMsg.progressWarning', groups: ['warning'] },
  // P10
  { re: /^Generate (\d+) chunks$/, key: 'serverMsg.progressGenerateChunks', groups: ['n'] },
  // P11
  {
    re: /^Keywords generation for (\d+) chunks$/,
    key: 'serverMsg.progressKeywords',
    groups: ['n'],
  },
  // P12
  {
    re: /^Question generation for (\d+) chunks$/,
    key: 'serverMsg.progressQuestions',
    groups: ['n'],
  },
  // P13
  {
    re: /^Embedding chunks \((\d+)\/(\d+)\)$/,
    key: 'serverMsg.progressEmbedding',
    groups: ['done', 'total'],
  },
  // P15
  {
    re: /^Auto metadata failed: (.+)$/,
    key: 'serverMsg.progressAutoMetadataFailed',
    groups: ['exc'],
  },
  // P16 (f-string „{elapsed:.2f}”)
  {
    re: /^Indexing done \((.+)s\)\. Done\.$/,
    key: 'serverMsg.progressIndexingDone',
    groups: ['elapsed'],
  },
  // P19
  {
    re: /^No text could be extracted: (.+)$/,
    key: 'serverMsg.progressEmptyDocument',
    groups: ['diagnosis'],
  },
  // P20 — szablon „(.{fmt})”: nawias przed kropką rozszerzenia
  {
    re: /^File is password-protected \(\.(.+)\)$/,
    key: 'serverMsg.progressEncryptedFile',
    groups: ['fmt'],
  },
  // P21 — fmt leniwy, reszta (powód) może zawierać dwukropek
  {
    re: /^File is corrupted or unreadable \(\.(.+?)\): (.+)$/,
    key: 'serverMsg.progressCorruptedFile',
    groups: ['fmt', 'reason'],
  },
  // P22
  {
    re: /^Unsupported file format: (.+)$/,
    key: 'serverMsg.progressUnsupportedFormat',
    groups: ['what'],
  },
  // P23
  {
    re: /^Limit exceeded: (.+?) (\S+) > (.+)$/,
    key: 'serverMsg.progressLimitExceeded',
    groups: ['what', 'value', 'limit'],
  },
  // P24
  {
    re: /^Parsing timed out after (.+) s$/,
    key: 'serverMsg.progressTimeout',
    groups: ['seconds'],
  },
  // P25
  {
    re: /^Required program '(.+)' is not installed; use the worker-ocr image$/,
    key: 'serverMsg.progressBinaryMissing',
    groups: ['binary'],
  },
  // P28
  {
    re: /^chunk_method (.+) is not supported by this server$/,
    key: 'serverMsg.progressChunkMethodUnsupported',
    groups: ['chunkMethod'],
  },
  // P29 (rename z łączników)
  {
    re: /^cannot change file type: (.+) -> (.+)$/,
    key: 'serverMsg.progressFileTypeImmutable',
    groups: ['old', 'new'],
  },
]

// P1, P2, P17, P26, P27 — teksty w pełni stałe.
export const PROGRESS_CONSTANTS: readonly Constant[] = [
  { text: 'Task has been received.', key: 'serverMsg.progressTaskReceived' }, // P1
  { text: 'Reused previous chunks.', key: 'serverMsg.progressReusedChunks' }, // P2
  { text: 'Task has been cancelled.', key: 'serverMsg.progressCancelled' }, // P17
  {
    text: 'Conversion process terminated abruptly (out of memory? document too large for worker memory limit WD_WORKER_MEM_LIMIT)',
    key: 'serverMsg.progressPoolBroken',
  }, // P26
  { text: "document too large for 'one'", key: 'serverMsg.progressTooLargeForOne' }, // P27
  // SC-V13-14 (K21 §2 p. 3) — spis treści bez pozycji; warianty z liczbą obsługuje
  // matchProgressContent (plural i18next, jak P14)
  { text: 'Outline: none (no bookmarks or headings)', key: 'serverMsg.progressOutlineNone' },
]
