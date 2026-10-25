/**
 * Testy `uploadFiles` (kontrakt WP E3-3b §T3): sekwencyjność, pole `file` w `FormData`, ścieżka,
 * przekazanie postępu i odporność pętli na błąd pojedynczego pliku. `uploadForm` (XHR) jest
 * podmieniony atrapą — w jsdom nie ma prawdziwego wysyłania.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UploadOptions } from '../../../api/upload'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { uploadFiles } from './uploadFiles'

beforeEach(() => {
  uploadFormMock.mockReset()
})

function file(name: string): File {
  return new File([name], name, { type: 'application/pdf' })
}

const silent = (): void => undefined

describe('uploadFiles', () => {
  it('wysyła pliki sekwencyjnie, po jednym na żądanie, polem `file`', async () => {
    let active = 0
    let maxActive = 0
    const sent: string[] = []
    uploadFormMock.mockImplementation(async (path: string, form: FormData) => {
      active += 1
      maxActive = Math.max(maxActive, active)
      sent.push(`${path}|${(form.get('file') as File).name}`)
      await new Promise((resolve) => setTimeout(resolve, 0))
      active -= 1
      return [{ id: `doc-${sent.length}` }]
    })

    const ids = await uploadFiles('ds-1', [file('a.pdf'), file('b.pdf'), file('c.pdf')], {
      onProgress: silent,
      onResult: silent,
    })

    expect(ids).toEqual(['doc-1', 'doc-2', 'doc-3'])
    expect(sent).toEqual([
      '/api/v1/datasets/ds-1/documents|a.pdf',
      '/api/v1/datasets/ds-1/documents|b.pdf',
      '/api/v1/datasets/ds-1/documents|c.pdf',
    ])
    expect(uploadFormMock).toHaveBeenCalledTimes(3)
    expect(maxActive).toBe(1)
  })

  it('przekazuje postęp z indeksem pliku', async () => {
    const progress: [number, number, number][] = []
    uploadFormMock.mockImplementation(
      async (_path: string, _form: FormData, options: UploadOptions) => {
        options.onProgress?.(30, 120)
        options.onProgress?.(120, 120)
        return [{ id: 'doc-1' }]
      },
    )

    await uploadFiles('ds-1', [file('a.pdf')], {
      onProgress: (index, loaded, total) => progress.push([index, loaded, total]),
      onResult: silent,
    })

    expect(progress).toEqual([
      [0, 30, 120],
      [0, 120, 120],
    ])
  })

  it('błąd środkowego pliku nie przerywa pętli i nie trafia do zwróconych ID', async () => {
    const results: unknown[] = []
    let call = 0
    uploadFormMock.mockImplementation(async () => {
      call += 1
      if (call === 2) throw new Error('plik za duży')
      return [{ id: `doc-${call}` }]
    })

    const ids = await uploadFiles('ds-1', [file('a.pdf'), file('b.pdf'), file('c.pdf')], {
      onProgress: silent,
      onResult: (index, result) => results.push({ index, result }),
    })

    expect(ids).toEqual(['doc-1', 'doc-3'])
    expect(uploadFormMock).toHaveBeenCalledTimes(3)
    expect(results).toEqual([
      { index: 0, result: { ok: true, documentId: 'doc-1' } },
      { index: 1, result: { ok: false, error: 'plik za duży' } },
      { index: 2, result: { ok: true, documentId: 'doc-3' } },
    ])
  })

  it('błąd niebędący `Error` zamienia na tekst', async () => {
    const results: unknown[] = []
    uploadFormMock.mockImplementation(() => Promise.reject('sieć padła'))

    await uploadFiles('ds-1', [file('a.pdf')], {
      onProgress: silent,
      onResult: (index, result) => results.push({ index, result }),
    })

    expect(results).toEqual([{ index: 0, result: { ok: false, error: 'sieć padła' } }])
  })

  it('ApiError niesie kod koperty (`errorCode`) — tłumaczenie przy wyświetleniu (T3b)', async () => {
    const results: unknown[] = []
    const { ApiError } = await import('../../../api/envelope')
    uploadFormMock.mockImplementation(() =>
      Promise.reject(
        new ApiError(500, 'x.exe: This type of file has not been supported yet!', 200),
      ),
    )

    await uploadFiles('ds-1', [file('x.exe')], {
      onProgress: silent,
      onResult: (index, result) => results.push({ index, result }),
    })

    expect(results).toEqual([
      {
        index: 0,
        result: {
          ok: false,
          error: 'x.exe: This type of file has not been supported yet!',
          errorCode: 500,
        },
      },
    ])
  })
})
