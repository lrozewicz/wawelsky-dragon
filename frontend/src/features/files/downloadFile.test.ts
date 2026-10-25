/**
 * Pobieranie pliku z `/files` (kontrakt WP E4-5c §4): nazwa z `Content-Disposition`, charset
 * blobu tekstowego, zapis przez `<a download>` i rozpoznanie koperty błędu domenowego.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import { downloadFile } from './downloadFile'

const DOWNLOAD_URL = apiUrl('/api/v1/files/file-1')

describe('downloadFile', () => {
  const anchors: HTMLAnchorElement[] = []
  let savedBlob: Blob | undefined

  beforeEach(() => {
    vi.useFakeTimers()
    anchors.length = 0
    savedBlob = undefined
    vi.spyOn(URL, 'createObjectURL').mockImplementation((object) => {
      savedBlob = object instanceof Blob ? object : undefined
      return 'blob:test'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      anchors.push(this)
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('zapisuje plik pod nazwą z Content-Disposition i zwalnia blob po 60 s', async () => {
    server.use(
      http.get(
        DOWNLOAD_URL,
        () =>
          new HttpResponse('tresc', {
            headers: {
              'Content-Type': 'text/plain',
              'Content-Disposition': 'attachment; filename="b.txt"',
            },
          }),
      ),
    )

    await downloadFile({ id: 'file-1', name: 'a.txt' })

    expect(savedBlob?.type).toBe('text/plain; charset=utf-8')
    expect(anchors).toHaveLength(1)
    expect(anchors.at(-1)?.download).toBe('b.txt')
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()

    vi.advanceTimersByTime(60_000)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
  })

  it('bez nagłówka zapisuje pod file.name, a HTTP 204 daje pusty plik', async () => {
    server.use(http.get(DOWNLOAD_URL, () => new HttpResponse(null, { status: 204 })))

    await downloadFile({ id: 'file-1', name: 'pusty.pdf' })

    expect(savedBlob?.size).toBe(0)
    expect(anchors.at(-1)?.download).toBe('pusty.pdf')
  })

  it('koperta JSON code≠0 z HTTP 200 rzuca ApiError', async () => {
    server.use(
      http.get(DOWNLOAD_URL, () => HttpResponse.json({ code: 102, message: 'nope', data: null })),
    )

    await expect(downloadFile({ id: 'file-1', name: 'a.txt' })).rejects.toMatchObject({
      code: 102,
      message: 'nope',
    })
    expect(anchors).toHaveLength(0)
  })

  it('koperta sukcesu (code 0) jest zapisywana jako plik', async () => {
    server.use(
      http.get(DOWNLOAD_URL, () =>
        HttpResponse.json(
          { code: 0, message: 'success', data: null },
          { headers: { 'Content-Disposition': 'attachment; filename="dane.json"' } },
        ),
      ),
    )

    await downloadFile({ id: 'file-1', name: 'a.json' })

    expect(anchors.at(-1)?.download).toBe('dane.json')
  })

  it('nieparsowalne ciało z typem JSON nie jest brane za kopertę', async () => {
    server.use(
      http.get(
        DOWNLOAD_URL,
        () => new HttpResponse('nie-json', { headers: { 'Content-Type': 'application/json' } }),
      ),
    )

    await downloadFile({ id: 'file-1', name: 'a.json' })

    expect(anchors).toHaveLength(1)
  })

  it('odpowiedź bez powodzenia rzuca ApiError ze statusem', async () => {
    server.use(
      http.get(DOWNLOAD_URL, () =>
        HttpResponse.json({ code: 102, message: 'Nope' }, { status: 401 }),
      ),
    )

    await expect(downloadFile({ id: 'file-1', name: 'a.txt' })).rejects.toMatchObject({
      code: 102,
      httpStatus: 401,
    })
    expect(anchors).toHaveLength(0)
  })
})
