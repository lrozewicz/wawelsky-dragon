/**
 * Domyślna konfiguracja TanStack Query (08 §9.2): świeżość 30 s, jedno ponowienie zapytań
 * (poza błędami 4xx) i brak ponowień mutacji.
 */

import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '../api/envelope'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) =>
          count < 1 &&
          !(error instanceof ApiError && error.httpStatus >= 400 && error.httpStatus < 500),
      },
      mutations: { retry: false },
    },
  })
}

export const queryClient = createQueryClient()
