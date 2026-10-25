/**
 * Sekwencyjny upload plików do `/files` (kontrakt WP E4-5c §3). Każdy plik idzie osobnym
 * `uploadForm` (XHR z postępem), bo jeden błąd nie może przewrócić pozostałych — wyjątek
 * zamieniamy na `onResult(ok: false)` i przechodzimy do kolejnego pliku. Po zakończeniu pętli
 * unieważnienie `fileKeys.all` robi komponent przez `useQueryClient` (hooka nie ma).
 */

import { ApiError } from '../../api/envelope'
import { uploadForm } from '../../api/upload'

/** Stan pojedynczego pliku w kolejce uploadu (utrzymuje komponent dialogu). */
export type FileUploadItem = {
  id: string
  file: File
  state: 'pending' | 'uploading' | 'done' | 'error'
  loaded: number
  total: number
  error?: string
  /** Kod koperty RAGFlow z `ApiError` — tłumaczenie komunikatu przy wyświetleniu (T5b). */
  errorCode?: number
}

type UploadHandlers = {
  /** Postęp wysyłania pliku o danym indeksie (`loaded`/`total` z `xhr.upload.onprogress`). */
  onProgress: (index: number, loaded: number, total: number) => void
  /** Wynik pojedynczego pliku — błąd nie przerywa pętli. */
  onResult: (
    index: number,
    result: { ok: true } | { ok: false; error: string; errorCode?: number },
  ) => void
}

/** Zwraca liczbę plików wysłanych poprawnie. */
export async function uploadFiles(
  parentId: string | undefined,
  files: File[],
  handlers: UploadHandlers,
): Promise<number> {
  let succeeded = 0

  for (const [index, file] of files.entries()) {
    const form = new FormData()
    form.append('file', file)
    if (parentId !== undefined) form.append('parent_id', parentId)

    try {
      await uploadForm<unknown>('/api/v1/files', form, {
        onProgress: (loaded, total) => handlers.onProgress(index, loaded, total),
      })
      succeeded += 1
      handlers.onResult(index, { ok: true })
    } catch (error) {
      handlers.onResult(index, {
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        // Kod koperty (101/102/500) potrzebny do tłumaczenia przy wyświetleniu (T5b);
        // błędy bez koperty nie mają go i wyświetlają się bez zmian.
        ...(error instanceof ApiError ? { errorCode: error.code } : {}),
      })
    }
  }

  return succeeded
}
