/**
 * Pobieranie pliku dokumentu (kontrakt WP E3-3b §T2): `GET …/documents/{id}` klientem API
 * (`parseAs: 'blob'` — DEC-080), nazwa z `Content-Disposition`, zapis przez `<a download>`.
 *
 * Błąd domenowy przychodzi jako HTTP 200 z kopertą JSON (K3 #3, `app/api/errors.py`) — przy
 * `parseAs: 'blob'` taka koperta ląduje w `data`, nie w `error`, więc rozpoznajemy ją po
 * `Content-Type` i niezerowym `code` (wzór `features/chats/preview/DocumentPreview.tsx`).
 */

import { api } from '../api/client'
import { ApiError, unwrap } from '../api/envelope'

/** Trasa pobrania pliku (`documents_download`, kontrakt §Fakty API). */
const DOWNLOAD_PATH = '/api/v1/datasets/{dataset_id}/documents/{document_id}'

/** Zwłoka przed zwolnieniem adresu blobu — przeglądarka musi zdążyć zacząć pobieranie. */
const REVOKE_DELAY_MS = 60_000

/** Typ MIME bez parametrów (np. `text/plain; charset=utf-8` → `text/plain`). */
function mediaType(contentType: string): string {
  return contentType.replace(/;.*/, '').trim().toLowerCase()
}

/**
 * Koperta błędu domenowego w ciele odpowiedzi albo `null`, gdy to zwykły plik. `JSON.parse`
 * może paść na treści dowolnego dokumentu `.json` — wtedy zwracamy `null`, bo to plik do zapisania.
 */
function jsonEnvelopeError(body: string, httpStatus: number): ApiError | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(body)
  } catch {
    return null
  }
  if (parsed === null || typeof parsed !== 'object') return null
  const { code, message } = parsed as { code?: unknown; message?: unknown }
  if (typeof code !== 'number' || code === 0) return null
  return new ApiError(code, typeof message === 'string' ? message : '', httpStatus)
}

/**
 * Nazwa pliku z `Content-Disposition`: najpierw `filename*=UTF-8''…` (RFC 5987, zakodowana
 * procentowo), potem zwykłe `filename="…"`; brak obu → `null`.
 * Uszkodzone kodowanie procentowe (np. `%E0%A4%A`) rzuca `URIError` — wtedy zwracamy surową
 * nazwę z nagłówka, by pobranie pliku nie padło.
 */
export function filenameFromDisposition(header: string | null): string | null {
  if (header === null) return null

  const extended = header.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (extended !== undefined) {
    const raw = extended.trim()
    try {
      return decodeURIComponent(raw)
    } catch {
      return raw
    }
  }

  const plain = header.match(/filename="?([^";]+)"?/i)?.[1]
  return plain === undefined ? null : plain.trim()
}

/**
 * Blob tekstowy bez `charset` dostaje `; charset=utf-8` (backend oddaje `text/plain` bez kodowania,
 * a przeglądarka wzięłaby wtedy domyślne). Blob z charsetem oraz typy nietekstowe wracają bez zmian.
 */
export function textBlobWithCharset(blob: Blob): Blob {
  if (!blob.type.startsWith('text/') || /charset=/i.test(blob.type)) return blob
  return new Blob([blob], { type: `${blob.type}; charset=utf-8` })
}

/** Pobiera plik dokumentu i zapisuje go w przeglądarce pod nazwą z nagłówka albo `doc.name`. */
export async function downloadDocument(
  datasetId: string,
  doc: { id: string; name: string },
): Promise<void> {
  const result = await api.GET(DOWNLOAD_PATH, {
    params: { path: { dataset_id: datasetId, document_id: doc.id } },
    parseAs: 'blob',
  })
  // Błąd transportu/HTTP (401, 5xx): `unwrap` rzuca `ApiError` z koperty błędu albo ze statusu.
  const blob = result.response.ok ? (result.data ?? new Blob()) : unwrap<Blob>(result)

  if (mediaType(blob.type) === 'application/json') {
    const failure = jsonEnvelopeError(await blob.text(), result.response.status)
    if (failure !== null) throw failure
  }

  const url = URL.createObjectURL(textBlobWithCharset(blob))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download =
    filenameFromDisposition(result.response.headers.get('content-disposition')) ?? doc.name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
}
