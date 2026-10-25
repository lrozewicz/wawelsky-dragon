import type { TFunction } from 'i18next'

import {
  CONSTANTS,
  ENVELOPE_RE,
  PATTERNS,
  PROGRESS_CONSTANTS,
  PROGRESS_PATTERNS,
  UNSUPPORTED_SUFFIX,
  type Constant,
  type Pattern,
} from './serverMessages.patterns'

// Tłumaczenie komunikatów serwera RAGFlow w UI (K20 §5 p. 1 i 4; INVENTORY WP V12-2,
// work/wp/V12-2/INVENTORY.md, rozstrzygnięcia DEC-356). Zasada nadrzędna: najpierw kod
// koperty (101/102/500), potem dopasowanie szablonu; pierwszy trafiony wzorzec wygrywa;
// brak dopasowania → tekst serwera pokazywany DOSŁOWNIE (nigdy „Nieznany błąd”).
// Wartości EN w locales/en/serverMsg.json odtwarzają tekst serwera, więc przy języku EN
// tłumaczenie renderuje oryginał 1:1 — bez rozgałęzienia po języku. Jedyny wyjątek:
// nieobsługiwany typ pliku (w. 1 i w. 2 → jeden klucz fileTypeUnsupported, EN
// „Unsupported file type: …”) — sankcjonowany przez DEC-371.

type Params = Record<string, string | number>

interface Match {
  key: string
  params: Params
}

interface Envelope {
  field: string
  msg: string
  value: string
}

function parseEnvelope(line: string): Envelope | null {
  const match = ENVELOPE_RE.exec(line)
  if (match === null) return null
  return { field: match[1] ?? '', msg: match[2] ?? '', value: match[3] ?? '' }
}

function buildParams(match: RegExpExecArray, groups: readonly string[]): Params {
  const params: Params = {}
  groups.forEach((name, index) => {
    params[name] = match[index + 1] ?? ''
  })
  return params
}

// Wiersze 5, 6, 7, 13, 14, 15 INVENTORY (otoczka walidacyjna). Dopasowanie po parze
// (field, msg) jest stabilniejsze niż po pełnym tekście — Value zależy od danych
// użytkownika (reguła 2).
function envelopeMatch(envelope: Envelope, code: number): Match | null {
  const { field, msg, value } = envelope
  if (code === 102 && field === 'chunk_method') {
    const notExist = /^`chunk_method` (.+) doesn't exist$/.exec(msg)
    if (notExist !== null) {
      return {
        key: 'serverMsg.chunkMethodNotExist',
        params: { chunkMethod: notExist[1] ?? '', value },
      }
    }
  }
  if (code === 102 && field === 'meta_fields') {
    // Najpierw wariant „in list” — krótszy prefiks musi wygrywać po nim (reguła tabeli).
    const inList = /^The type is not supported in list: (.+)$/.exec(msg)
    if (inList !== null) {
      return {
        key: 'serverMsg.metaTypeUnsupportedInList',
        params: { v: inList[1] ?? '', value },
      }
    }
    const scalar = /^The type is not supported: (.+)$/.exec(msg)
    if (scalar !== null) {
      return { key: 'serverMsg.metaTypeUnsupported', params: { v: scalar[1] ?? '', value } }
    }
  }
  if (code === 101 && field === 'chunk_method' && msg.startsWith("Input should be '")) {
    return { key: 'serverMsg.chunkMethodInvalid', params: { value } }
  }
  if (
    code === 101 &&
    field === 'embedding_model' &&
    msg === 'embedding model identifier must follow <model_name>@<provider> format'
  ) {
    return { key: 'serverMsg.embeddingModelFormat', params: { value } }
  }
  if (code === 101 && field === 'parser_config') {
    const tooLarge =
      /^Parser config exceeds size limit \(max 65,535 characters\)\. Current size: (\d+)$/.exec(msg)
    if (tooLarge !== null) {
      return {
        key: 'serverMsg.parserConfigTooLarge',
        params: { actual: tooLarge[1] ?? '', value },
      }
    }
  }
  return null
}

function matchConstant(
  code: number | undefined,
  line: string,
  constants: readonly Constant[],
): string | null {
  for (const constant of constants) {
    if (constant.text === line && (constant.code === undefined || constant.code === code)) {
      return constant.key
    }
  }
  return null
}

function matchPatterns(
  code: number | undefined,
  line: string,
  patterns: readonly Pattern[],
): Match | null {
  for (const pattern of patterns) {
    if (pattern.code !== undefined && pattern.code !== code) continue
    const match = pattern.re.exec(line)
    if (match !== null) return { key: pattern.key, params: buildParams(match, pattern.groups) }
  }
  return null
}

// Jedna linia komunikatu koperty; pusta → ''.
function translateServerLine(code: number, line: string, t: TFunction): string {
  if (line === '') return ''
  const envelope = parseEnvelope(line)
  if (envelope !== null) {
    const match = envelopeMatch(envelope, code)
    if (match !== null) return t(match.key, match.params)
  }
  if (code === 500 && line.endsWith(UNSUPPORTED_SUFFIX)) {
    const head = line.slice(0, line.length - UNSUPPORTED_SUFFIX.length)
    const filename = head.endsWith(': ') ? head.slice(0, -2) : head
    return t('serverMsg.fileTypeUnsupported', { filename })
  }
  const constantKey = matchConstant(code, line, CONSTANTS)
  if (constantKey !== null) return t(constantKey)
  const match = matchPatterns(code, line, PATTERNS)
  if (match !== null) return t(match.key, match.params)
  return line
}

// Komunikat z koperty RAGFlow (HTTP 200 + code/message). Wiele plików w jednym
// komunikacie upload (i wiele błędów walidacji) przychodzi jako linie po „\n” —
// każda linia dopasowywana osobno, wynik łączony z powrotem „\n” (reguła 3).
export function translateServerMessage(code: number, message: string, t: TFunction): string {
  if (message === '') return ''
  return message
    .split('\n')
    .map((line) => translateServerLine(code, line, t))
    .join('\n')
}

// Treść wpisu P18 (po prefiksie „[ERROR] ”) mapowana po szablonach P19–P29.
// Zwraca null, gdy treść jest nieznana (reguła „dosłownie” rozstrzyga wołający).
function matchProgressContent(content: string, t: TFunction): string | null {
  if (content === '') return ''
  const constantKey = matchConstant(undefined, content, PROGRESS_CONSTANTS)
  if (constantKey !== null) return t(constantKey)
  // P14 — „0 fields” = brak dopasowań wartości (CONTRACT (c)); N>0 → plural i18next.
  const autoMetadata = /^Auto metadata: (\d+) fields$/.exec(content)
  if (autoMetadata !== null) {
    const count = Number(autoMetadata[1] ?? '0')
    if (count === 0) return t('serverMsg.progressAutoMetadataNone')
    return t('serverMsg.progressAutoMetadataCount', { count })
  }
  // SC-V13-14 (K21 §2 p. 3) — „Outline: N entries (PDF bookmarks|headings)”; wariant
  // „none” jest stałą (PROGRESS_CONSTANTS). Plural i18next jak P14: 1 pozycja / 2–4
  // pozycje / 5+ pozycji; EN odtwarza tekst workera (worker pisze zawsze „entries”).
  const outline = /^Outline: (\d+) entries \((PDF bookmarks|headings)\)$/.exec(content)
  if (outline !== null) {
    const count = Number(outline[1] ?? '0')
    const key =
      outline[2] === 'headings'
        ? 'serverMsg.progressOutlineHeadings'
        : 'serverMsg.progressOutlinePdfBookmarks'
    return t(key, { count })
  }
  const match = matchPatterns(undefined, content, PROGRESS_PATTERNS)
  if (match !== null) return t(match.key, match.params)
  return null
}

function translateProgressContent(content: string, t: TFunction): string {
  return matchProgressContent(content, t) ?? content
}

const TIME_PREFIX_RE = /^(\d{2}:\d{2}:\d{2} )(.*)$/
const ERROR_PREFIX = '[ERROR] '
// Nazwa klasy wyjątku przed treścią (T10, QA V12-2-1 D2b): worker zapisuje
// „[ERROR] <NazwaKlasy>: <treść>” (queue.py fail), np. „[ERROR] CorruptedFile: File is
// corrupted or unreadable (.docx): …” — klasy z parsing/worker/chunking errors.py.
// Grupa 1 = treść po prefiksie klasy.
const ERROR_CLASS_RE = /^[A-Z][A-Za-z0-9]*: (.*)$/

// Jedna linia logu parsowania (progress_msg): opcjonalny prefiks czasu i/lub „[ERROR] ”
// zostaje, treść wg P1–P29; nieznana linia → dosłownie. Po „[ERROR] ” prefiks klasy wyjątku
// jest zdejmowany, gdy treść bez niego jest znana — tłumaczenie bez nazwy klasy; nieznana
// → cała linia dosłownie (z klasą).
export function translateProgressLine(line: string, t: TFunction): string {
  const timeMatch = TIME_PREFIX_RE.exec(line)
  const time = timeMatch?.[1] ?? ''
  let content = timeMatch?.[2] ?? line
  let errorPrefix = ''
  if (content.startsWith(ERROR_PREFIX)) {
    errorPrefix = ERROR_PREFIX
    content = content.slice(ERROR_PREFIX.length)
    if (matchProgressContent(content, t) === null) {
      const withClass = ERROR_CLASS_RE.exec(content)
      const translated = withClass === null ? null : matchProgressContent(withClass[1] ?? '', t)
      if (translated === null) return line
      return time + errorPrefix + translated
    }
  }
  return time + errorPrefix + translateProgressContent(content, t)
}

// Cały tekst logu parsowania: linia po linii, wynik łączony „\n”.
export function translateProgressLog(text: string, t: TFunction): string {
  if (text === '') return ''
  return text
    .split('\n')
    .map((line) => translateProgressLine(line, t))
    .join('\n')
}
