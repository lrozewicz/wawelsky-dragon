/**
 * Pobieranie pliku z `/files` (kontrakt WP E4-5c §4) — lokalny wrapper, bo `lib/download.ts`
 * obsługuje trasę dokumentów datasetu i nie zmieniamy go. Błąd domenowy przychodzi jako HTTP 200
 * z kopertą JSON (K3 #3); przy `parseAs: 'blob'` taka koperta ląduje w `data`, więc rozpoznajemy
 * ją po `Content-Type` i niezerowym `code` (wzór `lib/download.ts`).
 */

import { api } from '../../api/client'
import { ApiError, unwrap } from '../../api/envelope'
import { filenameFromDisposition, textBlobWithCharset } from '../../lib/download'

/** Trasa pobrania pliku (`files_download`, kontrakt §4). */
const DOWNLOAD_PATH = '/api/v1/files/{file_id}'

/** Zwłoka przed zwolnieniem adresu blobu — przeglądarka musi zdążyć zacząć pobieranie. */
const REVOKE_DELAY_MS = 60_000

/** Typ MIME bez parametrów (np. `text/plain; charset=utf-8` → `text/plain`). */
function mediaType(contentType: string): string {
  return contentType.replace(/;.*/, '').trim().toLowerCase()
}

/** Koperta błędu w ciele odpowiedzi albo `null`, gdy to zwykły plik (wersja lokalna — §4). */
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

/** Pobiera plik i zapisuje go pod nazwą z nagłówka albo `file.name`. */
export async function downloadFile(file: { id: string; name: string }): Promise<void> {
  const result = await api.GET(DOWNLOAD_PATH, {
    params: { path: { file_id: file.id } },
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
    filenameFromDisposition(result.response.headers.get('content-disposition')) ?? file.name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
}
