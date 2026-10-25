/**
 * Status integracji i odpytywanie (kontrakt WP E4-3c §1): interwał pollingu zależy od stanu
 * przebiegu, a `isActiveRunStatus` rozpoznaje przebieg aktywny po `is_running` albo statusie
 * ostatniego przebiegu. Wydzielone z `queries.test.tsx`, żeby oba pliki mieściły się w limicie
 * 300 linii.
 */

import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { integrationsHandlers, makeIntegration } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { INTEGRATION_POLL_MS, integrationStatusQueryOptions, isActiveRunStatus } from './queries'
import type { IntegrationStatus } from './queries'

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

/** Woła `refetchInterval` opcji statusu z podanymi danymi (typ opcji to unia z liczbą). */
function pollInterval(data: IntegrationStatus | undefined): number | false | undefined {
  const fn = integrationStatusQueryOptions(1).refetchInterval
  if (typeof fn !== 'function') return fn
  return fn({ state: { data } } as never)
}

describe('status i odpytywanie', () => {
  it('odpytuje tylko przy aktywnym przebiegu', async () => {
    server.use(...integrationsHandlers({ integrations: [makeIntegration({ id: 1 })] }))
    const idle = await createClient().fetchQuery(integrationStatusQueryOptions(1))

    expect(pollInterval(idle)).toBe(false)
    expect(pollInterval(undefined)).toBe(false)
    expect(pollInterval({ ...idle, is_running: true })).toBe(INTEGRATION_POLL_MS)
    expect(
      pollInterval({
        ...idle,
        latest_run: {
          id: 5,
          started_at: null,
          finished_at: null,
          status: 'queued',
          added: 0,
          updated: 0,
          deleted: 0,
          failed: 0,
        },
      }),
    ).toBe(INTEGRATION_POLL_MS)
  })

  it.each<[boolean, string | null, boolean]>([
    [true, null, true],
    [false, 'running', true],
    [false, 'queued', true],
    [false, 'success', false],
    [false, 'failed', false],
    [false, null, false],
  ])('isActiveRunStatus(is_running=%s, status=%s) to %s', (isRunning, status, expected) => {
    expect(
      isActiveRunStatus({
        is_running: isRunning,
        latest_run: status === null ? null : { status },
      }),
    ).toBe(expected)
  })
})
