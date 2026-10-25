/**
 * Stałe panelu administracyjnego (kontrakt WP E3-6c2 §2).
 */

/** Sufiks `created_by` grantów nadanych automatycznie przez klienta hub-compat (DEC-312). */
export const AUTO_PROVISIONED_SUFFIX = '-auto-provisioning'

/** Grant nadany automatycznie (provisioning klienta hub-compat) — takich grantów nie odbiera się w UI. */
export function isAutoProvisioned(createdBy: string | null | undefined): boolean {
  return createdBy?.endsWith(AUTO_PROVISIONED_SUFFIX) ?? false
}

/** Domyślny rozmiar strony listy użytkowników (`GET /api/wd/v1/users`). */
export const USERS_PAGE_SIZE = 25

/**
 * Opcje rozmiaru strony listy użytkowników. Ponad jedna opcja, bo `TablePagination` pokazuje
 * select i etykietę „Wierszy na stronę” dopiero przy >1 opcjach (SC-E5-H9-05 krok 4).
 */
export const USERS_PAGE_SIZE_OPTIONS = [10, 25, 50]

/** Odstęp odświeżania statusu systemu (`/stats`, `/healthz`) — 10 s. */
export const STATUS_REFETCH_MS = 10_000
