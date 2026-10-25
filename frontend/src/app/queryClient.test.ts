import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/envelope'
import { createQueryClient } from './queryClient'

type RetryFn = (count: number, error: unknown) => boolean

describe('createQueryClient', () => {
  const client = createQueryClient()

  it('ustawia staleTime na 30 s', () => {
    expect(client.getDefaultOptions().queries?.staleTime).toBe(30_000)
  })

  it('ponawia raz błędy inne niż 4xx', () => {
    const retry = client.getDefaultOptions().queries?.retry as unknown as RetryFn

    expect(retry(0, new Error('x'))).toBe(true)
    expect(retry(1, new Error('x'))).toBe(false)
    expect(retry(0, new ApiError(1, 'm', 404))).toBe(false)
    expect(retry(0, new ApiError(1, 'm', 500))).toBe(true)
  })

  it('nie ponawia mutacji', () => {
    expect(client.getDefaultOptions().mutations?.retry).toBe(false)
  })
})
