import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DocumentPreview } from './DocumentPreview'

afterEach(cleanup)

const PREVIEW_URL = apiUrl('/api/v1/documents/:documentId/preview')

// jsdom nie implementuje `URL.createObjectURL` (brak w `node_modules/jsdom/lib`) — podstawiamy
// deterministyczny adres, żeby sprawdzić, że komponent tworzy i zwalnia object URL.
const OBJECT_URL = 'blob:preview'

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => OBJECT_URL)
  URL.revokeObjectURL = vi.fn()
})

function previewHandler(contentType: string, body: string): HttpHandler {
  return http.get(
    PREVIEW_URL,
    () => new HttpResponse(body, { headers: { 'Content-Type': contentType } }),
  )
}

describe('DocumentPreview', () => {
  it('pokazuje wskaźnik ładowania, dopóki blob nie dotrze', async () => {
    let release = (): void => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.get(PREVIEW_URL, async () => {
        await gate
        return new HttpResponse('Zażółć', {
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        })
      }),
    )

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Notatka.txt" />)

    expect(screen.getByRole('progressbar', { name: 'Wczytywanie podglądu' })).toBeInTheDocument()

    release()
    expect(await screen.findByText('Zażółć')).toBeInTheDocument()
  })

  it('text/plain renderuje <pre> z polskimi znakami (UTF-8)', async () => {
    server.use(previewHandler('text/plain; charset=utf-8', 'Zażółć gęślą jaźń'))

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Notatka.txt" />)

    const pre = await screen.findByText('Zażółć gęślą jaźń')
    expect(pre.tagName).toBe('PRE')
  })

  it('text/html renderuje iframe z sandbox i srcDoc, bez object URL', async () => {
    server.use(previewHandler('text/html; charset=utf-8', '<h1>Witaj</h1>'))

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Strona.html" />)

    const frame = await screen.findByTitle('Strona.html')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame).toHaveAttribute('sandbox', '')
    expect(frame).toHaveAttribute('srcdoc', '<h1>Witaj</h1>')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('image/png renderuje <img> z object URL', async () => {
    server.use(previewHandler('image/png', 'pixels'))

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Obrazek.png" />)

    const image = await screen.findByRole('img', { name: 'Obrazek.png' })
    expect(image).toHaveAttribute('src', OBJECT_URL)
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('application/pdf renderuje iframe z object URL', async () => {
    server.use(previewHandler('application/pdf', '%PDF-1.7'))

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Dokument.pdf" />)

    const frame = await screen.findByTitle('Dokument.pdf')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame).toHaveAttribute('src', OBJECT_URL)
    expect(frame).not.toHaveAttribute('srcdoc')
  })

  it('PDF z page=N dokłada fragment #page=N do object URL', async () => {
    server.use(previewHandler('application/pdf', '%PDF-1.7'))

    await renderWithProviders(
      <DocumentPreview documentId="doc-1" documentName="Dokument.pdf" page={3} />,
    )

    const frame = await screen.findByTitle('Dokument.pdf')
    expect(frame).toHaveAttribute('src', `${OBJECT_URL}#page=3`)
  })

  it.each([undefined, 0, 1.5])('PDF z page=%s nie dokłada fragmentu', async (page) => {
    server.use(previewHandler('application/pdf', '%PDF-1.7'))

    await renderWithProviders(
      <DocumentPreview documentId="doc-1" documentName="Dokument.pdf" page={page} />,
    )

    const frame = await screen.findByTitle('Dokument.pdf')
    expect(frame).toHaveAttribute('src', OBJECT_URL)
    expect(frame.getAttribute('src')).not.toContain('#')
  })

  it('zmiana page zmienia src, ale nie pobiera blobu ani nie tworzy drugiego object URL', async () => {
    const counter = { calls: 0 }
    server.use(
      http.get(PREVIEW_URL, () => {
        counter.calls += 1
        return new HttpResponse('%PDF-1.7', { headers: { 'Content-Type': 'application/pdf' } })
      }),
    )

    // Podmiana `page` przez stan, bo `renderWithProviders` montuje UI w komponencie trasy —
    // `rerender` z RTL nie dotarłby do drzewa routera.
    function Switcher(): JSX.Element {
      const [page, setPage] = useState(1)
      return (
        <>
          <DocumentPreview documentId="doc-1" documentName="Dokument.pdf" page={page} />
          <button
            type="button"
            onClick={() => {
              setPage(4)
            }}
          >
            Strona 4
          </button>
        </>
      )
    }

    const user = userEvent.setup()
    await renderWithProviders(<Switcher />)

    expect(await screen.findByTitle('Dokument.pdf')).toHaveAttribute('src', `${OBJECT_URL}#page=1`)

    await user.click(screen.getByRole('button', { name: 'Strona 4' }))

    expect(await screen.findByTitle('Dokument.pdf')).toHaveAttribute('src', `${OBJECT_URL}#page=4`)
    expect(counter.calls).toBe(1)
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('nieznany typ daje komunikat „niedostępny” i link „Pobierz” z object URL', async () => {
    server.use(previewHandler('application/zip', 'PK'))

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Archiwum.zip" />)

    // SC-V12-09 k3: komunikat zgodny ze scenariuszem (DEC-357), link zachowuje nazwę pliku.
    expect(await screen.findByText('Podgląd niedostępny dla tego typu pliku.')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Pobierz' })
    expect(link).toHaveAttribute('href', OBJECT_URL)
    expect(link).toHaveAttribute('download', 'Archiwum.zip')
  })

  it('pusty blob (0 B) daje komunikat „niedostępny” bez ramki ani „Pobierz” (DEC-357)', async () => {
    server.use(previewHandler('application/pdf', ''))

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Pusty.pdf" />)

    expect(await screen.findByText('Podgląd niedostępny dla tego typu pliku.')).toBeInTheDocument()
    expect(screen.queryByTitle('Pusty.pdf')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Pobierz' })).not.toBeInTheDocument()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('404 pokazuje Alert z komunikatem błędu', async () => {
    server.use(
      http.get(PREVIEW_URL, () =>
        HttpResponse.json(
          { code: 102, message: 'Dokument nie istnieje' },
          { status: 404, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Brak.txt" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Dokument nie istnieje')
  })

  it('kopertę błędu w HTTP 200 (application/json) pokazuje jako Alert, nie jako plik', async () => {
    // Tak backend ragflow oddaje błędy domenowe (K3 #3): 200 + `{code, message}`.
    server.use(
      http.get(PREVIEW_URL, () =>
        HttpResponse.json(
          { code: 102, message: 'Dokument nie istnieje' },
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Brak.txt" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Dokument nie istnieje')
    expect(screen.queryByRole('link', { name: 'Pobierz' })).not.toBeInTheDocument()
  })

  it.each(['{"code":0,"items":[1,2]}', 'nie-json'])(
    'treść application/json „%s” traktuje jak plik do pobrania, nie błąd',
    async (body) => {
      server.use(previewHandler('application/json', body))

      await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="dane.json" />)

      expect(await screen.findByRole('link', { name: 'Pobierz' })).toBeInTheDocument()
    },
  )

  it('„Spróbuj ponownie” powtarza żądanie i pokazuje treść', async () => {
    let calls = 0
    server.use(
      http.get(PREVIEW_URL, () => {
        calls += 1
        if (calls === 1) {
          return new HttpResponse('boom', {
            status: 500,
            headers: { 'Content-Type': 'text/plain' },
          })
        }
        return new HttpResponse('Zażółć', {
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DocumentPreview documentId="doc-1" documentName="Notatka.txt" />)

    const alert = await screen.findByRole('alert')
    await user.click(within(alert).getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('Zażółć')).toBeInTheDocument()
  })

  it('zwalnia object URL przy odmontowaniu', async () => {
    server.use(previewHandler('image/png', 'pixels'))

    const { unmount } = await renderWithProviders(
      <DocumentPreview documentId="doc-1" documentName="Obrazek.png" />,
    )
    await screen.findByRole('img', { name: 'Obrazek.png' })

    unmount()

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL)
  })
})
