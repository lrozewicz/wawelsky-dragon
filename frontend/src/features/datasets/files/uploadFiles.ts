/**
 * Sekwencyjny upload plików datasetu (kontrakt WP E3-3b §T3). Każdy plik idzie osobnym
 * `uploadForm` (XHR z postępem), bo jeden błąd nie może przewrócić pozostałych — wyjątek
 * zamieniamy na `onResult(ok: false)` i przechodzimy do kolejnego pliku. `uploadForm` zwraca
 * tablicę (multipart przyjmuje wiele plików), a my wysyłamy po jednym, więc bierzemy `[0].id`.
 */

import { ApiError } from '../../../api/envelope'
import { uploadForm } from '../../../api/upload'

export type UploadItem = {
  id: string
  file: File
  state: 'pending' | 'uploading' | 'done' | 'error'
  loaded: number
  total: number
  error?: string
  /** Kod koperty RAGFlow z `ApiError` — tłumaczenie komunikatu przy wyświetleniu (T3b). */
  errorCode?: number
  documentId?: string
}

type UploadHandlers = {
  /** Postęp wysyłania pliku o danym indeksie (`loaded`/`total` z `xhr.upload.onprogress`). */
  onProgress: (index: number, loaded: number, total: number) => void
  /** Wynik pojedynczego pliku — błąd nie przerywa pętli. */
  onResult: (
    index: number,
    result: { ok: true; documentId: string } | { ok: false; error: string; errorCode?: number },
  ) => void
}

export async function uploadFiles(
  datasetId: string,
  files: File[],
  handlers: UploadHandlers,
): Promise<string[]> {
  const documentIds: string[] = []

  for (const [index, file] of files.entries()) {
    const form = new FormData()
    form.append('file', file)

    try {
      const result = await uploadForm<{ id: string }[]>(
        `/api/v1/datasets/${datasetId}/documents`,
        form,
        { onProgress: (loaded, total) => handlers.onProgress(index, loaded, total) },
      )
      // Wysyłamy jeden plik, więc odpowiedź ma jeden element; pusta tablica to `TypeError`
      // łapany niżej razem z każdym innym wyjątkiem `uploadForm` (plik ląduje jako błąd).
      const documentId = result[0]!.id
      documentIds.push(documentId)
      handlers.onResult(index, { ok: true, documentId })
    } catch (error) {
      handlers.onResult(index, {
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        // Kod koperty (101/102/500) potrzebny do tłumaczenia przy wyświetleniu (T3b);
        // błędy bez koperty nie mają go i wyświetlają się bez zmian.
        ...(error instanceof ApiError ? { errorCode: error.code } : {}),
      })
    }
  }

  return documentIds
}
