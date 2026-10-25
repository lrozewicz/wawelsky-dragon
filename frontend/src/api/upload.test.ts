import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearAccessToken, getAccessToken, setAccessToken } from '../features/auth/tokenStore'
import { apiUrl } from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { setSessionExpiredHandler } from './client'
import { ApiError } from './envelope'
import { uploadForm } from './upload'

type ProgressEventLike = { loaded: number; total: number }

// Atrapa XHR: `send` nic nie wysyła, odpowiedź wstrzykuje test przez `onload`/`onerror`/`onabort`.
class FakeXhr {
  static instances: FakeXhr[] = []

  method = ''
  url = ''
  withCredentials = false
  requestHeaders: Record<string, string> = {}
  status = 0
  responseText = ''
  body: FormData | null = null
  aborted = false

  upload: { onprogress: ((event: ProgressEventLike) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    FakeXhr.instances.push(this)
  }

  open(method: string, url: string): void {
    this.method = method
    this.url = url
  }

  setRequestHeader(name: string, value: string): void {
    this.requestHeaders[name] = value
  }

  send(body: FormData): void {
    this.body = body
  }

  abort(): void {
    this.aborted = true
    this.onabort?.()
  }
}

function makeForm(): FormData {
  const form = new FormData()
  form.append('file', new Blob(['x']), 'a.txt')
  return form
}

function respondOk(xhr: FakeXhr, data: unknown): void {
  xhr.status = 200
  xhr.responseText = JSON.stringify({ code: 0, message: 'success', data })
  xhr.onload?.()
}

function respondUnauthorized(xhr: FakeXhr): void {
  xhr.status = 401
  xhr.responseText = JSON.stringify({ code: 401, message: 'unauthorized', data: false })
  xhr.onload?.()
}

beforeEach(() => {
  FakeXhr.instances = []
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
})

afterEach(() => {
  vi.unstubAllGlobals()
  clearAccessToken()
  setSessionExpiredHandler(null)
})

describe('uploadForm — wysyłka', () => {
  it('POST na origin + path, z ciasteczkami, raportuje postęp i zwraca data', async () => {
    const onProgress = vi.fn()
    const promise = uploadForm<{ id: string }>('/api/v1/files', makeForm(), { onProgress })
    const xhr = FakeXhr.instances[0]!

    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe(window.location.origin + '/api/v1/files')
    expect(xhr.withCredentials).toBe(true)

    xhr.upload.onprogress?.({ loaded: 5, total: 10 })
    expect(onProgress).toHaveBeenCalledWith(5, 10)

    respondOk(xhr, { id: 'f1' })
    await expect(promise).resolves.toEqual({ id: 'f1' })
  })

  it('dołącza Bearer, gdy token jest ustawiony', async () => {
    setAccessToken('token-abc')

    const promise = uploadForm('/api/v1/files', makeForm())
    const xhr = FakeXhr.instances[0]!
    expect(xhr.requestHeaders['Authorization']).toBe('Bearer token-abc')

    respondOk(xhr, {})
    await expect(promise).resolves.toEqual({})
  })

  it('koperta code ≠ 0 odrzuca ApiError', async () => {
    const promise = uploadForm('/api/v1/files', makeForm())
    const xhr = FakeXhr.instances[0]!

    xhr.status = 200
    xhr.responseText = JSON.stringify({ code: 109, message: 'zły plik', data: false })
    xhr.onload?.()

    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toMatchObject({ code: 109, message: 'zły plik', httpStatus: 200 })
  })

  it('błąd sieci odrzuca ApiError(-1)', async () => {
    const promise = uploadForm('/api/v1/files', makeForm())
    FakeXhr.instances[0]!.onerror?.()

    await expect(promise).rejects.toMatchObject({ code: -1, httpStatus: 0 })
  })
})

describe('uploadForm — sesja', () => {
  it('401 → odświeżenie → powtórzenie z nowym tokenem → sukces', async () => {
    const promise = uploadForm<{ id: string }>('/api/v1/files', makeForm())
    respondUnauthorized(FakeXhr.instances[0]!)

    await vi.waitFor(() => expect(FakeXhr.instances).toHaveLength(2))
    const retried = FakeXhr.instances[1]!
    const token = getAccessToken()
    expect(token).not.toBeNull()
    expect(retried.requestHeaders['Authorization']).toBe(`Bearer ${token}`)

    respondOk(retried, { id: 'f2' })
    await expect(promise).resolves.toEqual({ id: 'f2' })
  })

  it('odświeżenie nieudane → sessionExpired i ApiError 401, bez powtórzenia', async () => {
    const handler = vi.fn()
    setSessionExpiredHandler(handler)
    server.use(
      http.post(apiUrl('/api/v1/auth/refresh'), () => new HttpResponse(null, { status: 401 })),
    )

    const promise = uploadForm('/api/v1/files', makeForm())
    respondUnauthorized(FakeXhr.instances[0]!)

    await expect(promise).rejects.toMatchObject({ httpStatus: 401, message: 'Sesja wygasła' })
    expect(handler).toHaveBeenCalledTimes(1)
    expect(FakeXhr.instances).toHaveLength(1)
  })

  it('drugi 401 po udanym odświeżeniu → sessionExpired i ApiError 401', async () => {
    const handler = vi.fn()
    setSessionExpiredHandler(handler)

    const promise = uploadForm('/api/v1/files', makeForm())
    respondUnauthorized(FakeXhr.instances[0]!)

    await vi.waitFor(() => expect(FakeXhr.instances).toHaveLength(2))
    respondUnauthorized(FakeXhr.instances[1]!)

    await expect(promise).rejects.toMatchObject({ httpStatus: 401, message: 'Sesja wygasła' })
    expect(handler).toHaveBeenCalledTimes(1)
  })
})

describe('uploadForm — abort', () => {
  it('przerwanie sygnału przerywa XHR i odrzuca ApiError(-1, aborted)', async () => {
    const controller = new AbortController()
    const promise = uploadForm('/api/v1/files', makeForm(), { signal: controller.signal })

    controller.abort()

    expect(FakeXhr.instances[0]!.aborted).toBe(true)
    await expect(promise).rejects.toMatchObject({ code: -1, message: 'aborted', httpStatus: 0 })
  })

  it('sygnał przerwany przed startem odrzuca bez wysyłki', async () => {
    const controller = new AbortController()
    controller.abort()

    const promise = uploadForm('/api/v1/files', makeForm(), { signal: controller.signal })

    expect(FakeXhr.instances).toHaveLength(0)
    await expect(promise).rejects.toMatchObject({ code: -1, message: 'aborted', httpStatus: 0 })
  })
})
