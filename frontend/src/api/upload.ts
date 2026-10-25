/**
 * Upload plików przez XHR (08 §5): `fetch` nie raportuje postępu wysyłania, dlatego
 * `uploadForm` używa `XMLHttpRequest` i tej samej logiki sesji co middleware klienta:
 * 401 → jedno wspólne odświeżenie → jedno powtórzenie.
 */

import { getAccessToken } from '../features/auth/tokenStore'
import { notifySessionExpired, refreshSession } from './client'
import { ApiError, unwrapEnvelope } from './envelope'

export type UploadOptions = {
  onProgress?: (loaded: number, total: number) => void
  signal?: AbortSignal
}

type XhrResult = { status: number; text: string }

function sendRequest(path: string, form: FormData, options: UploadOptions): Promise<XhrResult> {
  return new Promise<XhrResult>((resolve, reject) => {
    const { signal } = options
    if (signal?.aborted) {
      reject(new ApiError(-1, 'aborted', 0))
      return
    }

    const xhr = new XMLHttpRequest()
    xhr.open('POST', window.location.origin + path)
    xhr.withCredentials = true

    const token = getAccessToken()
    if (token !== null) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (event) => {
      options.onProgress?.(event.loaded, event.total)
    }
    xhr.onload = () => resolve({ status: xhr.status, text: xhr.responseText })
    xhr.onerror = () => reject(new ApiError(-1, 'Błąd sieci', 0))
    xhr.onabort = () => reject(new ApiError(-1, 'aborted', 0))
    signal?.addEventListener('abort', () => xhr.abort())

    xhr.send(form)
  })
}

export async function uploadForm<T>(
  path: string,
  form: FormData,
  options: UploadOptions = {},
): Promise<T> {
  const first = await sendRequest(path, form, options)
  if (first.status !== 401) {
    return unwrapEnvelope<T>(JSON.parse(first.text), first.status)
  }

  const token = await refreshSession()
  if (token === null) {
    notifySessionExpired()
    throw new ApiError(401, 'Sesja wygasła', 401)
  }

  const second = await sendRequest(path, form, options)
  if (second.status === 401) {
    notifySessionExpired()
    throw new ApiError(401, 'Sesja wygasła', 401)
  }
  return unwrapEnvelope<T>(JSON.parse(second.text), second.status)
}
