/**
 * Dialog importu — pauza po 5xx (CONTRACT WP E67-z1a §C1/§C2, SC-E67-03): 503 na porcji daje
 * „Serwer chwilowo niedostępny (503). Wysyłka wstrzymana." i „Wznów wysyłkę", klik kończy
 * wysyłkę podsumowaniem, zamknięcie dialogu przy pauzie kasuje sesję (`DELETE`).
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, kbDefaultSummary, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ImportDialog } from './ImportDialog'
import type { DatasetImport } from './types'

const CONTENT_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/content')
const SESSION_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
  cleanup()
})

function smallPackage(): File {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00])], 'paczka.wdkb.zip', {
    type: 'application/zip',
  })
}

function sessionBody(overrides: Partial<DatasetImport>): DatasetImport {
  return {
    import_id: 'import-test',
    file_name: 'paczka.wdkb.zip',
    size_bytes: 6,
    received_bytes: 0,
    chunk_size: 4_096,
    state: 'uploading',
    errors: [],
    summary: null,
    task_id: null,
    expires_at: Date.now() + 3_600_000,
    ...overrides,
  }
}

/** `PUT` porcji: pierwszy raz 503 (koperta API), potem sukces z podsumowaniem; `GET`/`DELETE` sesji. */
function useFlakyServer(): { deleted: () => boolean } {
  let failed = false
  let deleted = false
  server.use(
    http.put(CONTENT_ROUTE, () => {
      if (!failed) {
        failed = true
        return HttpResponse.json({ error: { code: 'unavailable', message: 'x' } }, { status: 503 })
      }
      return HttpResponse.json({
        data: sessionBody({ received_bytes: 6, state: 'ready', summary: kbDefaultSummary() }),
      })
    }),
    http.get(SESSION_ROUTE, () => HttpResponse.json({ data: sessionBody({}) })),
    http.delete(SESSION_ROUTE, () => {
      deleted = true
      return HttpResponse.json({ data: { deleted: true } })
    }),
  )
  return { deleted: () => deleted }
}

describe('ImportDialog — pauza po 5xx', () => {
  it('503 na porcji: komunikat z kodem i „Wznów wysyłkę"; klik kończy podsumowaniem', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<ImportDialog onClose={vi.fn()} onStarted={vi.fn()} />)
    useFlakyServer()

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])

    expect(
      await screen.findByText('Serwer chwilowo niedostępny (503). Wysyłka wstrzymana.'),
    ).toBeInTheDocument()
    // Pauza to ostrzeżenie (amber), nie błąd.
    expect(screen.getByRole('alert')).toHaveClass('MuiAlert-colorWarning')
    expect(screen.queryByText('Nieznany błąd operacji.')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Wznów wysyłkę' }))

    expect(await screen.findByTestId('kb-import-summary')).toBeInTheDocument()
  })

  it('zamknięcie dialogu przy wstrzymanej wysyłce wywołuje DELETE sesji', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<ImportDialog onClose={vi.fn()} onStarted={vi.fn()} />)
    const flaky = useFlakyServer()

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
    await screen.findByRole('button', { name: 'Wznów wysyłkę' })
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    await vi.waitFor(() => expect(flaky.deleted()).toBe(true))
  })
})
