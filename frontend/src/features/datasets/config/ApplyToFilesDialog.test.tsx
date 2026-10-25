/**
 * Testy `ApplyToFilesDialog` (kontrakt WP E5-H8c §2): treść z liczbą plików, „Tylko nowe pliki”
 * bez żadnego żądania, „Zastosuj i parsuj ponownie” → PATCH dokumentów i JEDNO POST `…/chunks`
 * (postęp i nieaktywne przyciski w trakcie), błąd per plik w `Alert` z otwartym dialogiem,
 * podwójny klik uruchamia jeden przebieg. MSW: własny handler PATCH (plan błędów, opóźnienie),
 * `documentsHandlers` dla listy, własne POST `…/chunks` (brak w atrapach — wzór applyToDocuments).
 */

import { HttpResponse, http } from 'msw'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { DocumentRow } from '../files/queries'

import { ApplyToFilesDialog } from './ApplyToFilesDialog'

afterEach(cleanup)

type Outcome = 'ok' | 'http500' | 'delay'

/** Rejestruje trasy i zwraca zebrane ciała PATCH/POST. */
function setup(
  documents: DocumentRow[],
  opts: { patch?: (documentId: string) => Outcome; chunkMethod?: string } = {},
): { patches: { id: string; body: unknown }[]; posts: unknown[] } {
  const patches: { id: string; body: unknown }[] = []
  const posts: unknown[] = []
  server.use(
    http.patch(
      apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'),
      async ({ request, params }) => {
        const id = String(params.documentId)
        patches.push({ id, body: await request.json() })
        const plan = opts.patch?.(id) ?? 'ok'
        if (plan === 'http500') {
          return HttpResponse.json({ code: 102, message: 'Serwer padł' }, { status: 500 })
        }
        if (plan === 'delay') await new Promise((resolve) => setTimeout(resolve, 50))
        return HttpResponse.json({ code: 0, message: 'success', data: {} })
      },
    ),
    // Lista dla `listAllDocuments` — dialog dostaje dokumenty w propsach, ale GET i tak leci
    // z `useSaveWithApply`; tu tylko dla spójności tras.
    ...documentsHandlers(documents),
    http.post(apiUrl('/api/v1/datasets/:datasetId/chunks'), async ({ request }) => {
      posts.push(await request.json())
      return HttpResponse.json({ code: 0, message: 'success', data: null })
    }),
  )
  return { patches, posts }
}

/** Renderuje dialog z domyślnymi propsami (zmienione pole: Zakres stron). */
function render(props: {
  documents: DocumentRow[]
  chunkMethod?: string
  onClose?: () => void
  parserConfigChanges?: Record<string, unknown>
  language?: 'pl' | 'en'
}): Promise<unknown> {
  return renderWithProviders(
    <ApplyToFilesDialog
      open
      datasetId="ds-1"
      documents={props.documents}
      chunkMethod={props.chunkMethod}
      parserConfigChanges={props.parserConfigChanges ?? { pages: [] }}
      changedLabels={['Zakres stron']}
      onClose={props.onClose ?? vi.fn()}
    />,
    { language: props.language },
  )
}

const docA = (): DocumentRow =>
  fixtureDocument({ id: 'doc-1', name: 'a.pdf', parser_config: { pages: [[2, 3]] } })
const docB = (): DocumentRow =>
  fixtureDocument({ id: 'doc-2', name: 'b.pdf', parser_config: { chunk_token_num: 512 } })

describe('ApplyToFilesDialog', () => {
  it('pokazuje zmienione pola, liczbę plików i parę przycisków', async () => {
    setup([docA()])
    await render({ documents: [docA()] })

    const dialog = screen.getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' })
    expect(within(dialog).getByText('Zmieniono: Zakres stron.')).toBeInTheDocument()
    expect(within(dialog).getByText(/Dataset ma 1 plik/)).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' }),
    ).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Tylko nowe pliki' })).toBeInTheDocument()
  })

  it('„Tylko nowe pliki” zamyka dialog bez PATCH dokumentów i POST', async () => {
    const { patches, posts } = setup([docA()])
    const onClose = vi.fn()
    await render({ documents: [docA()], onClose })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Tylko nowe pliki' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(patches).toEqual([])
    expect(posts).toEqual([])
  })

  it('„Zastosuj…” PATCHuje dokumenty ze scaloną konfiguracją, POST raz, zamyka dialog', async () => {
    const { patches, posts } = setup([docA(), docB()], { chunkMethod: 'qa' })
    const onClose = vi.fn()
    await render({ documents: [docA(), docB()], chunkMethod: 'qa', onClose })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zastosuj i parsuj ponownie (2)' }))

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
    expect(patches).toEqual([
      {
        id: 'doc-1',
        body: { chunk_method: 'qa', parser_config: { pages: [] } },
      },
      {
        id: 'doc-2',
        body: { chunk_method: 'qa', parser_config: { chunk_token_num: 512, pages: [] } },
      },
    ])
    expect(posts).toEqual([{ document_ids: ['doc-1', 'doc-2'] }])
  })

  it('w trakcie zapisu pokazuje postęp i blokuje przyciski', async () => {
    setup([docA(), docB()], { patch: () => 'delay' })
    await render({ documents: [docA(), docB()] })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zastosuj i parsuj ponownie (2)' }))

    expect(await screen.findByText('Zastosowano 0/2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zastosuj i parsuj ponownie (2)' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Tylko nowe pliki' })).toBeDisabled()

    await waitFor(() => {
      expect(screen.queryByText(/Zastosowano/)).toBeNull()
    })
  })

  it('błąd jednego pliku trafia do `Alert`, a dialog zostaje otwarty', async () => {
    const { posts } = setup([docA(), docB()], {
      patch: (id) => (id === 'doc-2' ? 'http500' : 'ok'),
    })
    const onClose = vi.fn()
    await render({ documents: [docA(), docB()], onClose })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zastosuj i parsuj ponownie (2)' }))

    expect(
      await screen.findByText('Nie udało się zastosować do pliku „b.pdf”: Serwer padł'),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    // Udany plik poszedł do POST; drugi nie.
    expect(posts).toEqual([{ document_ids: ['doc-1'] }])
  })

  it('podwójny klik „Zastosuj…” uruchamia jeden przebieg', async () => {
    // Opóźniony PATCH wypina okno drugiego kliknięcia z „w trakcie” — chroni je straż `ref`.
    const { patches, posts } = setup([docA()], { patch: () => 'delay' })
    await render({ documents: [docA()] })
    const user = userEvent.setup()

    const apply = screen.getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' })
    await user.click(apply)
    // W trakcie biegu przycisk jest nieaktywny; wymuszony klik ma zostać zignorowany (straż `ref`).
    fireEvent.click(apply)

    await waitFor(() => {
      expect(posts).toHaveLength(1)
    })
    expect(patches).toHaveLength(1)
  })

  // T10 (QA-UI): treść z liczbą plików odmienia się formami i18next (`apply.body_one/_few/_many/
  // _other`) — PL 1 plik / 2 pliki / 5 plików, EN 1 file / 2 files.
  describe('podpowiedź przy „Tylko nowe pliki” (SC-V12-09 k4)', () => {
    it('zmiana metadanych pokazuje podpowiedź w strefie akcji dialogu', async () => {
      setup([docA()])
      await render({ documents: [docA()], parserConfigChanges: { metadata: [{ key: 'rok' }] } })

      const hint = screen.getByText(
        'Istniejące pliki zachowają dotychczasowe metadane. Aby je dodać, użyj „Zastosuj i parsuj ponownie”.',
      )
      expect(hint.closest('.MuiDialogActions-root')).not.toBeNull()
      expect(
        within(hint.closest('.MuiDialogActions-root') as HTMLElement).getByRole('button', {
          name: 'Tylko nowe pliki',
        }),
      ).toBeInTheDocument()
    })

    it('zmiana bez metadanych (Zakres stron) nie pokazuje podpowiedzi', async () => {
      setup([docA()])
      await render({ documents: [docA()] })

      expect(
        screen.queryByText(
          'Istniejące pliki zachowają dotychczasowe metadane. Aby je dodać, użyj „Zastosuj i parsuj ponownie”.',
        ),
      ).not.toBeInTheDocument()
    })

    it('EN: „Existing files keep…” i „Apply and re-parse”', async () => {
      setup([docA()])
      await render({
        documents: [docA()],
        parserConfigChanges: { enable_metadata: true },
        language: 'en',
      })

      expect(
        screen.getByText(
          'Existing files keep their current metadata. To add it, use "Apply and re-parse".',
        ),
      ).toBeInTheDocument()
    })
  })

  describe('odmiana treści (liczba plików)', () => {
    const docsOf = (count: number): DocumentRow[] =>
      Array.from({ length: count }, (_unused, index) =>
        fixtureDocument({ id: `doc-${index + 1}`, name: `f${index + 1}.pdf` }),
      )

    it.each([
      {
        language: 'pl' as const,
        count: 1,
        text: 'Dataset ma 1 plik sparsowany starą konfiguracją. „Zastosuj i parsuj ponownie” nadpisze ustawienia tego pliku i usunie jego obecne chunki (także edytowane ręcznie).',
      },
      {
        language: 'pl' as const,
        count: 2,
        text: 'Dataset ma 2 pliki sparsowane starą konfiguracją. „Zastosuj i parsuj ponownie” nadpisze ustawienia tych plików i usunie ich obecne chunki (także edytowane ręcznie).',
      },
      {
        language: 'pl' as const,
        count: 5,
        text: 'Dataset ma 5 plików sparsowanych starą konfiguracją. „Zastosuj i parsuj ponownie” nadpisze ustawienia tych plików i usunie ich obecne chunki (także edytowane ręcznie).',
      },
      {
        language: 'en' as const,
        count: 1,
        text: 'The dataset has 1 file parsed with the old configuration. "Apply and re-parse" overwrites this file\'s settings and deletes its current chunks (including manual edits).',
      },
      {
        language: 'en' as const,
        count: 2,
        text: 'The dataset has 2 files parsed with the old configuration. "Apply and re-parse" overwrites these files\' settings and deletes their current chunks (including manual edits).',
      },
    ])('$language, $count plik(ów) — pełna forma treści', async ({ language, count, text }) => {
      setup(docsOf(count))
      await render({ documents: docsOf(count), language })

      expect(screen.getByText(text)).toBeInTheDocument()
    })
  })
})
