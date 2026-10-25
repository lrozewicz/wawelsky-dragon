import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DocumentPreviewDrawer } from './DocumentPreviewDrawer'

afterEach(cleanup)

const PREVIEW_URL = apiUrl('/api/v1/documents/:documentId/preview')

// jsdom nie implementuje `URL.createObjectURL` — patrz `DocumentPreview.test.tsx`.
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

// Podgląd tekstowy: najprostsza treść do sprawdzenia, że szuflada faktycznie pokazuje dokument.
function textPreviewHandler(): ReturnType<typeof http.get> {
  return http.get(
    PREVIEW_URL,
    () =>
      new HttpResponse('Treść dokumentu', {
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      }),
  )
}

describe('DocumentPreviewDrawer', () => {
  it('jest zamknięta, gdy documentId jest null — bez żądania i bez nagłówka', async () => {
    // Brak handlera podglądu: `onUnhandledRequest: 'error'` w `src/test/setup.ts` wywali test,
    // gdyby komponent jednak pobierał dokument.
    await renderWithProviders(
      <DocumentPreviewDrawer documentId={null} documentName="Notatka.txt" onClose={vi.fn()} />,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('Podgląd dokumentu')).not.toBeInTheDocument()
  })

  it('pokazuje nagłówek z nazwą dokumentu i treść podglądu', async () => {
    server.use(textPreviewHandler())

    await renderWithProviders(
      <DocumentPreviewDrawer documentId="doc-1" documentName="Notatka.txt" onClose={vi.fn()} />,
    )

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Notatka.txt')).toBeInTheDocument()
    expect(await within(dialog).findByText('Treść dokumentu')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Zamknij podgląd' })).toBeInTheDocument()
  })

  it('bez nazwy dokumentu nagłówkiem jest tekst ogólny', async () => {
    server.use(textPreviewHandler())

    await renderWithProviders(<DocumentPreviewDrawer documentId="doc-1" onClose={vi.fn()} />)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Podgląd dokumentu')).toBeInTheDocument()
  })

  it('przycisk zamknięcia woła onClose', async () => {
    server.use(textPreviewHandler())
    const onClose = vi.fn()
    const user = userEvent.setup()

    await renderWithProviders(
      <DocumentPreviewDrawer documentId="doc-1" documentName="Notatka.txt" onClose={onClose} />,
    )

    await user.click(await screen.findByRole('button', { name: 'Zamknij podgląd' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('zamyka się klawiszem Esc', async () => {
    server.use(textPreviewHandler())
    const onClose = vi.fn()
    const user = userEvent.setup()

    await renderWithProviders(
      <DocumentPreviewDrawer documentId="doc-1" documentName="Notatka.txt" onClose={onClose} />,
    )

    await screen.findByRole('dialog')
    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('zamyka się kliknięciem w tło (backdrop)', async () => {
    server.use(textPreviewHandler())
    const onClose = vi.fn()
    const user = userEvent.setup()

    await renderWithProviders(
      <DocumentPreviewDrawer documentId="doc-1" documentName="Notatka.txt" onClose={onClose} />,
    )

    await screen.findByRole('dialog')
    const backdrop = document.querySelector('.MuiModal-backdrop')
    expect(backdrop).not.toBeNull()
    await user.click(backdrop as Element)

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
