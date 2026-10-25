/**
 * Pobieranie pliku dokumentu (kontrakt WP E3-3b §T2): nazwa z `Content-Disposition`, charset
 * blobu tekstowego, zapis przez `<a download>` i rozpoznanie koperty błędu domenowego.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/envelope'
import { apiUrl } from '../test/msw/handlers'
import { server } from '../test/msw/server'

import { downloadDocument, filenameFromDisposition, textBlobWithCharset } from './download'

const DOWNLOAD_URL = apiUrl('/api/v1/datasets/ds-1/documents/doc-1')

describe('filenameFromDisposition', () => {
  it('bez nagłówka albo bez `filename` zwraca null', () => {
    expect(filenameFromDisposition(null)).toBeNull()
    expect(filenameFromDisposition('attachment')).toBeNull()
  })

  it('preferuje `filename*` i dekoduje procenty', () => {
    expect(
      filenameFromDisposition(`attachment; filename*=UTF-8''za%C5%BC%C3%B3%C5%82%C4%87.pdf`),
    ).toBe('zażółć.pdf')
    expect(filenameFromDisposition(`attachment; filename*=UTF-8''a%20b.pdf`)).toBe('a b.pdf')
  })

  it('czyta zwykłe `filename` w cudzysłowie', () => {
    expect(filenameFromDisposition('attachment; filename="a.pdf"')).toBe('a.pdf')
  })

  it('niepoprawne kodowanie procentowe zwraca surową nazwę (bez wyjątku)', () => {
    expect(filenameFromDisposition(`attachment; filename*=UTF-8''%E0%A4%A`)).toBe('%E0%A4%A')
  })
})

describe('textBlobWithCharset', () => {
  it('dopisuje charset tekstowi bez kodowania', () => {
    expect(textBlobWithCharset(new Blob(['x'], { type: 'text/plain' })).type).toBe(
      'text/plain; charset=utf-8',
    )
  })

  it('blob z charsetem wraca bez zmian', () => {
    const blob = new Blob(['x'], { type: 'text/plain; charset=utf-8' })
    expect(textBlobWithCharset(blob)).toBe(blob)
  })

  it('typ nietekstowy wraca bez zmian', () => {
    const blob = new Blob(['x'], { type: 'image/png' })
    expect(textBlobWithCharset(blob)).toBe(blob)
  })
})

describe('downloadDocument', () => {
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

  it('zapisuje plik pod nazwą dokumentu i zwalnia adres blobu po 60 s', async () => {
    // Własny handler, nie `documentsHandlers`: tamten składa ciało z `Blob` jsdom, którego
    // `HttpResponse` MSW nie umie przyjąć (brak `stream()`), więc pobranie w teście padałoby 500.
    server.use(
      http.get(
        DOWNLOAD_URL,
        () => new HttpResponse('notatka', { headers: { 'Content-Type': 'text/plain' } }),
      ),
    )

    await downloadDocument('ds-1', { id: 'doc-1', name: 'notatka.txt' })

    expect(savedBlob?.type).toBe('text/plain; charset=utf-8')
    expect(anchors).toHaveLength(1)
    expect(anchors.at(-1)?.download).toBe('notatka.txt')
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()

    vi.advanceTimersByTime(60_000)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
  })

  it('odpowiedź 204 zapisuje pusty plik pod nazwą dokumentu', async () => {
    server.use(http.get(DOWNLOAD_URL, () => new HttpResponse(null, { status: 204 })))

    await downloadDocument('ds-1', { id: 'doc-1', name: 'pusty.pdf' })

    expect(savedBlob?.size).toBe(0)
    expect(anchors.at(-1)?.download).toBe('pusty.pdf')
  })

  it('nazwa z nagłówka Content-Disposition ma pierwszeństwo nad doc.name', async () => {
    server.use(
      http.get(
        DOWNLOAD_URL,
        () =>
          new HttpResponse('x', {
            headers: {
              'Content-Type': 'application/octet-stream',
              'Content-Disposition': `attachment; filename*=UTF-8''za%C5%BC%C3%B3%C5%82%C4%87.pdf`,
            },
          }),
      ),
    )

    await downloadDocument('ds-1', { id: 'doc-1', name: 'plik.pdf' })

    expect(anchors.at(-1)?.download).toBe('zażółć.pdf')
  })

  it('uszkodzone kodowanie w nagłówku zapisuje plik pod surową nazwą', async () => {
    server.use(
      http.get(
        DOWNLOAD_URL,
        () =>
          new HttpResponse('x', {
            headers: {
              'Content-Type': 'application/octet-stream',
              'Content-Disposition': `attachment; filename*=UTF-8''%E0%A4%A`,
            },
          }),
      ),
    )

    await downloadDocument('ds-1', { id: 'doc-1', name: 'plik.pdf' })

    expect(anchors.at(-1)?.download).toBe('%E0%A4%A')
  })

  it('koperta JSON `code≠0` rzuca ApiError', async () => {
    // Domyślne handlery T1a nie znają `doc-1` → HTTP 200 z kopertą `code: 102`.
    await expect(
      downloadDocument('ds-1', { id: 'doc-1', name: 'plik.pdf' }),
    ).rejects.toBeInstanceOf(ApiError)

    await expect(downloadDocument('ds-1', { id: 'doc-1', name: 'plik.pdf' })).rejects.toMatchObject(
      { code: 102 },
    )
    expect(anchors).toHaveLength(0)
  })

  it('koperta bez komunikatu i tak rzuca ApiError', async () => {
    server.use(http.get(DOWNLOAD_URL, () => HttpResponse.json({ code: 102 })))

    await expect(downloadDocument('ds-1', { id: 'doc-1', name: 'plik.pdf' })).rejects.toMatchObject(
      {
        code: 102,
        message: '',
      },
    )
  })

  it('odpowiedź bez powodzenia rzuca ApiError ze statusem', async () => {
    server.use(
      http.get(DOWNLOAD_URL, () =>
        HttpResponse.json({ code: 102, message: 'Nope' }, { status: 401 }),
      ),
    )

    await expect(downloadDocument('ds-1', { id: 'doc-1', name: 'plik.pdf' })).rejects.toMatchObject(
      {
        code: 102,
        httpStatus: 401,
      },
    )
  })

  it('plik JSON, który nie jest kopertą, jest zapisywany', async () => {
    server.use(
      http.get(DOWNLOAD_URL, () =>
        HttpResponse.json(
          { hello: 'world' },
          { headers: { 'Content-Disposition': 'attachment; filename="dane.json"' } },
        ),
      ),
    )

    await downloadDocument('ds-1', { id: 'doc-1', name: 'plik.json' })

    expect(anchors.at(-1)?.download).toBe('dane.json')
  })

  it('koperta sukcesu (`code: 0`) jest zapisywana jako plik', async () => {
    server.use(
      http.get(DOWNLOAD_URL, () =>
        HttpResponse.json(
          { code: 0, message: 'success', data: null },
          { headers: { 'Content-Disposition': 'attachment; filename="dane.json"' } },
        ),
      ),
    )

    await downloadDocument('ds-1', { id: 'doc-1', name: 'plik.json' })

    expect(anchors.at(-1)?.download).toBe('dane.json')
  })

  it('nieparsowalne ciało albo `null` z typem JSON nie jest brane za kopertę', async () => {
    for (const body of ['nie-json', 'null']) {
      server.use(
        http.get(
          DOWNLOAD_URL,
          () => new HttpResponse(body, { headers: { 'Content-Type': 'application/json' } }),
        ),
      )

      await downloadDocument('ds-1', { id: 'doc-1', name: 'plik.json' })
    }

    expect(anchors).toHaveLength(2)
  })
})
