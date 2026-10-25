/**
 * Wysyłka paczki importu porcjami `PUT` z wznawianiem (kontrakt WP E7-2 §5, 08 §7.15c).
 * Sesję zakłada `createImport`, porcje idą po `chunk_size` z jego odpowiedzi; po błędzie sieci
 * ponawiamy 3 razy (1 s/2 s/4 s), potem stan `paused` i czekanie na `resume()`. Każda próba
 * startuje od `received_bytes` serwera (`getImport`), więc żadna porcja nie leci dwa razy.
 * Odpowiedź 5xx (serwer chwilowo niedostępny) nie jest ponawiana automatycznie: `paused`
 * z kodem HTTP i czekanie na `resume()` (kontrakt WP E67-z1a §C1). `cancel()` przerywa `fetch`
 * i porzuca sesję importu — chyba że `done` rozstrzygnęło się sukcesem.
 */

import { WdApiError } from '../admin/wdClient'

import { createImport, deleteImport, getImport, uploadChunk } from './api'
import type { DatasetImport } from './types'

/** Stan wysyłki dla UI: `resuming` w trakcie ponawiania, `paused` po 3 nieudanych próbach. */
export type UploadStatus = 'uploading' | 'resuming' | 'paused'

/** Przerwy między próbami po błędzie sieci (kontrakt §5: 1 s/2 s/4 s, potem `paused`). */
export const UPLOAD_BACKOFF_MS: readonly number[] = [1000, 2000, 4000]

/** Uchwyt sesji wysyłki (kontrakt §5): `cancel()` przerywa `fetch` i porzuca sesję importu. */
export interface UploadHandle {
  cancel(): Promise<void>
}

/** Sterowanie wysyłką: `done` = ostatnia odpowiedź `PUT`, `resume()` wznawia po `paused`. */
export interface UploadSession extends UploadHandle {
  done: Promise<DatasetImport>
  resume(): void
}

export interface UploadCallbacks {
  /** Po `createImport` — dialog pokazuje z tego rozmiar porcji i identyfikator sesji. */
  onSession(imp: DatasetImport): void
  /** Po każdej porcji przyjętej przez serwer. */
  onProgress(received: number, total: number): void
  /** `pauseHttpStatus` tylko dla `paused` po odpowiedzi 5xx (kontrakt WP E67-z1a §C1). */
  onStatus(status: UploadStatus, pauseHttpStatus?: number): void
  signal: AbortSignal
}

/** Błąd wykryty przez przeglądarkę przed żądaniami — `code` to slug komunikatu UI. */
export class UploadError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'UploadError'
  }
}

function abortError(): DOMException {
  return new DOMException('Wysyłka przerwana.', 'AbortError')
}

/** Odpowiedź serwera 5xx — wstrzymujemy wysyłkę zamiast ponawiać (kontrakt WP E67-z1a §C1). */
function isServerError(error: unknown): error is WdApiError {
  return error instanceof WdApiError && error.httpStatus >= 500
}

export function uploadPackage(file: File, cb: UploadCallbacks): UploadSession {
  // Własny kontroler: `cancel()` i sygnał wołającego przerywają to samo żądanie `fetch`.
  const controller = new AbortController()
  if (cb.signal.aborted) controller.abort()
  else cb.signal.addEventListener('abort', () => controller.abort(), { once: true })

  /** Wybudzenie pętli czekającej na `resume()`; `null`, gdy wysyłka nie jest wstrzymana. */
  let wake: (() => void) | null = null
  let session: DatasetImport | null = null
  /** Wszystkie bajty paczki odebrane — `cancel()` nie ma już czego porzucać. */
  let completed = false
  /** `done` rozstrzygnięte sukcesem — `cancel()` po nim nie kasuje sesji importu (§C1). */
  let settled = false
  /** Nieudane próby od ostatniej przyjętej porcji — 3 przerwy, potem `paused`. */
  let failures = 0

  /** Sen przerywany przerwaniem wysyłki — odrzuca wtedy `AbortError`. */
  function sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        controller.signal.removeEventListener('abort', onAbort)
        resolve()
      }, ms)
      const onAbort = (): void => {
        clearTimeout(timer)
        reject(abortError())
      }
      controller.signal.addEventListener('abort', onAbort, { once: true })
    })
  }

  /** Czeka na `resume()`; przerwanie wysyłki kończy oczekiwanie `AbortError`. */
  function waitForResume(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const onAbort = (): void => reject(abortError())
      wake = () => {
        controller.signal.removeEventListener('abort', onAbort)
        resolve()
      }
      controller.signal.addEventListener('abort', onAbort, { once: true })
    })
  }

  function throwIfAborted(): void {
    if (controller.signal.aborted) throw abortError()
  }

  /**
   * Próba po błędzie sieci (kontrakt §5): przerwa 1 s/2 s/4 s i świeży stan serwera. Gdy i
   * odpytanie padnie (sieć wciąż leży), liczy się to jak kolejna próba; po wyczerpaniu prób
   * wysyłka wchodzi w `paused` i czeka na `resume()`.
   */
  async function resync(importId: string): Promise<DatasetImport> {
    for (;;) {
      failures += 1
      if (failures > UPLOAD_BACKOFF_MS.length) {
        failures = 0
        // `wake` musi istnieć, zanim UI zobaczy `paused` — `resume()` z tego samego zdarzenia
        // (np. automatyczne wznowienie) nie może przepaść.
        const waiting = waitForResume()
        cb.onStatus('paused')
        await waiting
      } else {
        cb.onStatus('resuming')
        await sleep(UPLOAD_BACKOFF_MS[failures - 1]!)
      }
      try {
        const state = await getImport(importId)
        // Sieć wróciła — wracamy do zwykłego stanu wysyłki.
        cb.onStatus('uploading')
        return state
      } catch (error) {
        if (controller.signal.aborted) throw abortError()
        if (!(error instanceof TypeError)) throw error
      }
    }
  }

  /**
   * Reakcja na 5xx (kontrakt §C1, K19 trasa 7): `paused` z kodem HTTP i czekanie na `resume()`
   * użytkownika — serwer chwilowo niedostępny nie jest ponawiany automatycznie. Po wznowieniu
   * offset bierzemy z `getImport`; kolejne 5xx odpytania wstrzymują wysyłkę ponownie, z nowym
   * kodem. Błąd sieci odpytania wraca do dotychczasowego backoffu (`resync`).
   */
  async function waitForServer(importId: string, httpStatus: number): Promise<DatasetImport> {
    for (;;) {
      // `waitForResume` musi istnieć, zanim UI zobaczy `paused` — `resume()` z tego samego
      // zdarzenia (np. kliknięcie „Wznów” natychmiast po komunikacie) nie może przepaść.
      const waiting = waitForResume()
      cb.onStatus('paused', httpStatus)
      await waiting
      try {
        const state = await getImport(importId)
        failures = 0
        cb.onStatus('uploading')
        return state
      } catch (error) {
        if (controller.signal.aborted) throw abortError()
        if (isServerError(error)) {
          httpStatus = error.httpStatus
          continue
        }
        if (error instanceof TypeError) {
          failures = 0
          return resync(importId)
        }
        throw error
      }
    }
  }

  /**
   * Stan serwera do wznowienia: pierwsza próba od razu, błąd sieci → backoff z `resync`
   * (kontrakt §5) — dotąd w ścieżce ratunkowej `offset_mismatch` odpytanie stało poza
   * ponawianiem i jego niepowodzenie kończyło całą wysyłkę. 5xx odpytania to pauza z kodem (§C1).
   */
  async function stateWithBackoff(importId: string): Promise<DatasetImport> {
    try {
      return await getImport(importId)
    } catch (error) {
      if (controller.signal.aborted) throw abortError()
      if (isServerError(error)) return waitForServer(importId, error.httpStatus)
      if (!(error instanceof TypeError)) throw error
      return resync(importId)
    }
  }

  async function send(): Promise<DatasetImport> {
    // Pusta paczka nie ma czego wysyłać (R-ING-03) — odrzucamy PRZED założeniem sesji.
    if (file.size === 0) {
      throw new UploadError('empty_file', 'Paczka jest pusta (0 B) — wybierz inny plik.')
    }
    throwIfAborted()

    const created = await createImport(file.name, file.size)
    session = created
    cb.onSession(created)
    cb.onStatus('uploading')

    const total = file.size
    let received = created.received_bytes
    let last = created

    /** Komplet odebrany bez odpowiedzi `PUT` — wynik i postęp bierzemy z serwera (kontrakt §5). */
    function accept(state: DatasetImport): DatasetImport {
      cb.onProgress(state.received_bytes, total)
      return state
    }

    while (received < total) {
      throwIfAborted()
      const bytes = file.slice(received, Math.min(received + created.chunk_size, total))
      try {
        const next = await uploadChunk(created.import_id, received, total, bytes, controller.signal)
        last = next
        received = next.received_bytes
        failures = 0
        // Przed `onProgress`: „Anuluj” w tej samej porcji nie może skasować kompletnej paczki.
        completed = received >= total
        cb.onProgress(received, total)
      } catch (error) {
        if (controller.signal.aborted) throw abortError()
        // 5xx na porcji (§C1): pauza z kodem bez ponowień, wznowienie od offsetu serwera.
        if (isServerError(error)) {
          const state = await waitForServer(created.import_id, error.httpStatus)
          received = state.received_bytes
          if (received >= total) {
            completed = true
            last = accept(state)
          }
          continue
        }
        // 409 `offset_mismatch` niesie liczbę bajtów, które dotarły — wznawiamy dokładnie od niej.
        if (error instanceof WdApiError && error.code === 'offset_mismatch') {
          const at = error.details?.received_bytes
          if (typeof at !== 'number') throw error
          received = at
          // Serwer ma komplet — `done` musi oddać stan terminalny (§5), a nie obiekt z sesji.
          // `completed` przed `accept`: „Anuluj”/`cancel()` po `done` nie kasuje sesji, której
          // bajty już dotarły.
          if (received >= total) {
            completed = true
            last = accept(await stateWithBackoff(created.import_id))
          }
          continue
        }
        // Inny błąd WD (np. `import_not_ready`) i błędy nie-sieciowe kończą wysyłkę.
        if (error instanceof WdApiError || !(error instanceof TypeError)) throw error
        // Każda próba zaczyna od stanu serwera (kontrakt §5).
        const state = await resync(created.import_id)
        received = state.received_bytes
        // Odpowiedź ostatniej porcji mogła przepaść, choć bajty dotarły — inaczej `done`
        // oddaje nieaktualny obiekt z `createImport` zamiast stanu `ready`|`invalid`.
        if (received >= total) {
          completed = true
          last = accept(state)
        }
      }
    }
    return last
  }

  const done = send().then((state) => {
    settled = true
    return state
  })

  return {
    done,
    resume(): void {
      const woken = wake
      wake = null
      woken?.()
    },
    async cancel(): Promise<void> {
      controller.abort()
      // Sukces rozstrzygnięty (§C1) albo komplet bajtów na serwerze — sesji nie ma po co kasować.
      if (!settled && !completed && session !== null) await deleteImport(session.import_id)
    },
  }
}
