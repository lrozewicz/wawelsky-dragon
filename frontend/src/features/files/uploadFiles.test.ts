/**
 * Testy `uploadFiles` (kontrakt WP E4-5c §3): sekwencyjność, pola `file`/`parent_id` w `FormData`,
 * ścieżka, przekazanie postępu i odporność pętli na błąd pojedynczego pliku. `uploadForm` (XHR)
 * jest podmieniony atrapą — w jsdom nie ma prawdziwego wysyłania (wzór `datasets/files`).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UploadOptions } from '../../api/upload'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { uploadFiles } from './uploadFiles'

beforeEach(() => {
  uploadFormMock.mockReset()
})

function file(name: string): File {
  return new File([name], name, { type: 'application/pdf' })
}

const silent = (): void => undefined

describe('uploadFiles', () => {
  it('wysyła po jednym żądaniu na plik z polem file i parent_id', async () => {
    const seen: { path: string; file: string; parentId: FormDataEntryValue | null }[] = []
    uploadFormMock.mockImplementation(async (path: string, form: FormData) => {
      seen.push({ path, file: (form.get('file') as File).name, parentId: form.get('parent_id') })
      return {}
    })

    const count = await uploadFiles('p', [file('a.pdf'), file('b.pdf')], {
      onProgress: silent,
      onResult: silent,
    })

    expect(count).toBe(2)
    expect(uploadFormMock).toHaveBeenCalledTimes(2)
    expect(seen).toEqual([
      { path: '/api/v1/files', file: 'a.pdf', parentId: 'p' },
      { path: '/api/v1/files', file: 'b.pdf', parentId: 'p' },
    ])
  })

  it('pomija parent_id dla root i przekazuje postęp z indeksem pliku', async () => {
    const progress: [number, number, number][] = []
    let parentId: FormDataEntryValue | null = 'x'
    uploadFormMock.mockImplementation(
      async (_path: string, form: FormData, options: UploadOptions) => {
        parentId = form.get('parent_id')
        options.onProgress?.(5, 10)
        options.onProgress?.(10, 10)
        return {}
      },
    )

    await uploadFiles(undefined, [file('a.pdf')], {
      onProgress: (index, loaded, total) => progress.push([index, loaded, total]),
      onResult: silent,
    })

    expect(parentId).toBeNull()
    expect(progress).toEqual([
      [0, 5, 10],
      [0, 10, 10],
    ])
  })

  it('błąd jednego pliku nie przerywa pętli i zwraca liczbę udanych', async () => {
    const results: [number, { ok: boolean; error?: string }][] = []
    uploadFormMock.mockRejectedValueOnce(new Error('Boom')).mockResolvedValueOnce({})

    const count = await uploadFiles('p', [file('a.pdf'), file('b.pdf')], {
      onProgress: silent,
      onResult: (index, result) => results.push([index, result]),
    })

    expect(count).toBe(1)
    expect(uploadFormMock).toHaveBeenCalledTimes(2)
    expect(results).toEqual([
      [0, { ok: false, error: 'Boom' }],
      [1, { ok: true }],
    ])
  })

  it('błąd niebędący Error zamienia na tekst', async () => {
    uploadFormMock.mockRejectedValueOnce('surowe')
    const results: unknown[] = []

    await uploadFiles(undefined, [file('a.pdf')], {
      onProgress: silent,
      onResult: (_index, result) => results.push(result),
    })

    expect(results).toEqual([{ ok: false, error: 'surowe' }])
  })
})
