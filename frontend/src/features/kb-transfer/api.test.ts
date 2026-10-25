import { HttpResponse, http } from 'msw'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { apiUrl, kbDefaultPreview, makeAccessToken, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { i18n, initI18n } from '../../i18n'
import { clearAccessToken, getAccessToken, setAccessToken } from '../auth/tokenStore'

import { getTask, previewExport, startExport, stopTask } from './api'
import type { WdTaskStage } from './types'

const nowSeconds = () => Math.floor(Date.now() / 1000)
const oldToken = () => makeAccessToken(nowSeconds() + 900)
const newToken = () => makeAccessToken(nowSeconds() + 1800)
const unauthorized = () => new HttpResponse(null, { status: 401 })
const refreshSuccess = (token: string) =>
  HttpResponse.json({ code: 0, message: 'success', data: { access_token: token, expires_in: 900 } })

beforeAll(async () => {
  await initI18n('pl')
})

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
  clearAccessToken()
})

describe('previewExport', () => {
  it('zwraca podgląd zawartości paczki (trasa 1)', async () => {
    const preview = await previewExport('d1')

    expect(preview.documents).toBe(3)
    expect(preview.chunks).toBe(7251)
    expect(preview.estimated_bytes).toBeGreaterThan(0)
    expect(preview.estimated_bytes_with_vectors).toBeGreaterThan(preview.estimated_bytes)
    expect(preview.embedding).toEqual({ model_name: 'text-embedding-3-small', dimension: 1536 })
  })

  it('nieznany dataset daje WdApiError `not_found` (404)', async () => {
    await expect(previewExport('obcy')).rejects.toMatchObject({
      code: 'not_found',
      httpStatus: 404,
    })
  })
})

describe('startExport', () => {
  it('drugie wywołanie na ten sam dataset daje 409 export_in_progress z details.task_id', async () => {
    const first = await startExport('d1', true)
    expect(first.status).toBe('queued')

    await expect(startExport('d1', false)).rejects.toMatchObject({
      code: 'export_in_progress',
      httpStatus: 409,
      details: { task_id: first.task_id },
    })
  })

  it('po zakończeniu eksportu kolejny start przechodzi', async () => {
    const first = await startExport('d1', true)
    await getTask(first.task_id)
    await stopTask(first.task_id)

    await expect(startExport('d1', true)).resolves.toMatchObject({ status: 'queued' })
  })
})

describe('getTask / stopTask', () => {
  it('odpytywanie rozwija zadanie przez etapy do `done` z linkiem pobrania', async () => {
    const { task_id } = await startExport('d1', true)
    const stages: WdTaskStage[] = []
    let task = await getTask(task_id)
    for (let i = 0; i < 10 && task.status !== 'done'; i += 1) {
      stages.push(task.stage as WdTaskStage)
      task = await getTask(task_id)
    }

    expect(stages).toEqual(['files', 'chunks', 'vectors', 'finalize'])
    expect(task).toMatchObject({ status: 'done', progress: 1, finished_at: expect.any(Number) })
    expect(task.result).toMatchObject({ file_name: 'rocznik-gus-2024.wdkb.zip' })
  })

  it('stopTask zatrzymuje zadanie, powtórzony zwraca stopped=false', async () => {
    const { task_id } = await startExport('d1', true)

    await expect(stopTask(task_id)).resolves.toEqual({ stopped: true })
    await expect(stopTask(task_id)).resolves.toEqual({ stopped: false })
    await expect(getTask(task_id)).resolves.toMatchObject({ status: 'cancelled' })
  })

  it('nieznane zadanie daje `not_found`', async () => {
    await expect(getTask('brak')).rejects.toMatchObject({ code: 'not_found', httpStatus: 404 })
  })
})

describe('sesja użytkownika', () => {
  it('dołącza Bearer z tokenem i Accept-Language', async () => {
    let authorization: string | null = null
    let acceptLanguage: string | null = null
    setAccessToken(oldToken())
    server.use(
      http.get(apiUrl('/api/wd/v1/datasets/:datasetId/export/preview'), ({ request }) => {
        authorization = request.headers.get('Authorization')
        acceptLanguage = request.headers.get('Accept-Language')
        return HttpResponse.json({ data: kbDefaultPreview() })
      }),
    )

    const preview = await previewExport('d1')

    expect(preview.dataset_id).toBe('d1')
    expect(authorization).toBe(`Bearer ${getAccessToken()}`)
    expect(acceptLanguage).toBe('pl')
    expect(acceptLanguage).toBe(i18n.language)
  })

  it('401 odświeża sesję i powtarza żądanie z tym samym ciałem', async () => {
    const stale = oldToken()
    const fresh = newToken()
    const bodies: string[] = []
    const authorizations: (string | null)[] = []
    setAccessToken(stale)
    server.use(
      http.post(apiUrl('/api/wd/v1/datasets/d1/export'), async ({ request }) => {
        bodies.push(await request.text())
        authorizations.push(request.headers.get('Authorization'))
        return bodies.length === 1
          ? unauthorized()
          : HttpResponse.json({ data: { task_id: 'task-9', status: 'queued' } }, { status: 202 })
      }),
      http.post(apiUrl('/api/v1/auth/refresh'), () => refreshSuccess(fresh)),
    )

    await expect(startExport('d1', true)).resolves.toEqual({ task_id: 'task-9', status: 'queued' })

    expect(authorizations).toEqual([`Bearer ${stale}`, `Bearer ${fresh}`])
    expect(bodies.map((body) => JSON.parse(body))).toEqual([
      { include_vectors: true },
      { include_vectors: true },
    ])
    expect(getAccessToken()).toBe(fresh)
  })
})

describe('koperta WD', () => {
  it('przekazuje do WdApiError kod, komunikat i status błędu', async () => {
    server.use(
      http.get(apiUrl('/api/wd/v1/datasets/d1/export/preview'), () =>
        HttpResponse.json(
          { error: { code: 'forbidden', message: 'Brak uprawnień.' } },
          { status: 403 },
        ),
      ),
    )

    await expect(previewExport('d1')).rejects.toMatchObject({
      name: 'WdApiError',
      code: 'forbidden',
      message: 'Brak uprawnień.',
      httpStatus: 403,
    })
  })
})
