import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { Citation } from '../../chat-stream/reducer'

import { CitationChip } from './CitationChip'

afterEach(cleanup)

// Endpoint, z którego `DocumentPreview` pobiera plik dokumentu — podgląd cytatu nie może go wołać.
const PREVIEW_URL = apiUrl('/api/v1/documents/:documentId/preview')

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim (domyślnym w `renderWithProviders`). */
const CHIP_LABEL = 'Cytowanie 1'
const SIMILARITY_PREFIX = 'Podobieństwo:'
const DOC_NAME = 'Smok.pdf'
const OPEN_LABEL = 'Otwórz dokument'
const CLOSE_LABEL = 'Zamknij'
const CONTENT = 'Smok wawelski mieszkał pod Wawelem.'

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    chunkId: 'chunk-0',
    docId: 'doc-0',
    docName: DOC_NAME,
    content: CONTENT,
    similarity: 0.8123,
    ...overrides,
  }
}

async function renderChip(overrides: Partial<Citation> = {}) {
  const onOpenDocument = vi.fn()
  await renderWithProviders(
    <CitationChip index={0} citation={citation(overrides)} onOpenDocument={onOpenDocument} />,
  )
  return { onOpenDocument, chip: screen.getByRole('button', { name: CHIP_LABEL }) }
}

describe('CitationChip', () => {
  it('ma etykietę będącą numerem cytowania i dostępną nazwę z i18n', async () => {
    const { chip } = await renderChip()

    expect(chip).toHaveTextContent('1')
    expect(chip).toHaveAccessibleName(CHIP_LABEL)
    expect(chip).toHaveAttribute('aria-haspopup', 'dialog')
  })

  // QA-UI V13-z-2 (MAJOR wizualny): na 390 px długa nazwa dokumentu bez spacji nie mieści się
  // w tytule modalu (scrollWidth 411 > clientWidth 356, `text-overflow: clip`) — tytuł musi
  // zawijać (`overflow-wrap: anywhere`), żeby pełna nazwa była czytelna bez interakcji.
  it('zawija długą nazwę dokumentu w tytule (overflow-wrap: anywhere)', async () => {
    const longName = 'gus_rocznik_statystyczny_rp_2024_dane_miesieczne_wyniki.pdf'
    const { chip } = await renderChip({ docName: longName })
    const user = userEvent.setup()

    await user.click(chip)

    const title = await screen.findByRole('heading', { name: longName })
    expect(title).toHaveStyle({ 'overflow-wrap': 'anywhere' })
  })

  it('po kliknięciu otwiera dialog z nazwą dokumentu, treścią i podobieństwem', async () => {
    const { chip } = await renderChip()
    const user = userEvent.setup()

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(chip)

    const dialog = await screen.findByRole('dialog', { name: DOC_NAME })
    expect(dialog).toHaveTextContent(CONTENT)
    expect(screen.getByText(`${SIMILARITY_PREFIX} 81%`)).toBeInTheDocument()
  })

  it('pokazuje pełną treść ponad 600 znaków, bez przycinania i wielokropka', async () => {
    const { chip } = await renderChip({ content: 'a'.repeat(700) })
    const user = userEvent.setup()

    await user.click(chip)

    const content = await screen.findByTestId('cite-content')
    expect(content).toHaveTextContent('a'.repeat(700))
    expect(content.textContent).not.toContain('…')
  })

  it('Enter na chipie otwiera dialog', async () => {
    const { chip } = await renderChip()
    const user = userEvent.setup()

    chip.focus()
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('dialog', { name: DOC_NAME })).toBeInTheDocument()
  })

  it('hover nic nie otwiera', async () => {
    const { chip } = await renderChip()
    const user = userEvent.setup()

    await user.hover(chip)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Esc zamyka dialog i wraca fokusem na chip', async () => {
    const { chip } = await renderChip()
    const user = userEvent.setup()

    await user.click(chip)
    expect(await screen.findByRole('dialog', { name: DOC_NAME })).toBeInTheDocument()

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(chip).toHaveFocus()
  })

  it('przycisk „Zamknij” zamyka dialog', async () => {
    const { chip } = await renderChip()
    const user = userEvent.setup()

    await user.click(chip)
    await screen.findByRole('dialog', { name: DOC_NAME })

    await user.click(screen.getByRole('button', { name: CLOSE_LABEL }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('przycisk „Otwórz dokument” woła onOpenDocument i zamyka dialog', async () => {
    const { chip, onOpenDocument } = await renderChip()
    const user = userEvent.setup()

    await user.click(chip)
    await user.click(await screen.findByRole('button', { name: OPEN_LABEL }))

    expect(onOpenDocument).toHaveBeenCalledWith('doc-0', DOC_NAME)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('pokazuje numer strony, gdy cytowanie go niesie', async () => {
    const { chip } = await renderChip({ page: 7 })
    const user = userEvent.setup()

    await user.click(chip)

    expect(await screen.findByRole('dialog', { name: DOC_NAME })).toHaveTextContent('Strona 7')
  })

  it('bez numeru strony nie pokazuje wiersza strony', async () => {
    const { chip } = await renderChip({ page: null })
    const user = userEvent.setup()

    await user.click(chip)

    expect(await screen.findByRole('dialog', { name: DOC_NAME })).not.toHaveTextContent(/Strona/)
  })

  it('bez podobieństwa nie pokazuje wiersza podobieństwa', async () => {
    const { chip } = await renderChip({ similarity: null })
    const user = userEvent.setup()

    await user.click(chip)

    expect(await screen.findByRole('dialog', { name: DOC_NAME })).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(`^${SIMILARITY_PREFIX}`))).not.toBeInTheDocument()
  })

  // Strażnik regresji MINOR-a QA E5-H6a/B4 (DEC-269): podgląd cytatu jest lokalny (treść chunku
  // z reducera), a plik dokumentu pobiera dopiero rodzic po „Otwórz dokument” — nigdy sam chip.
  it('podgląd cytatu nie pobiera pliku dokumentu; „Otwórz dokument” tylko woła onOpenDocument', async () => {
    const previewCalls: string[] = []
    server.use(
      http.get(PREVIEW_URL, ({ request }) => {
        previewCalls.push(request.url)
        return HttpResponse.text('%PDF-1.7', { headers: { 'Content-Type': 'application/pdf' } })
      }),
    )
    const { chip, onOpenDocument } = await renderChip()
    const user = userEvent.setup()

    await user.click(chip)
    await screen.findByRole('dialog', { name: DOC_NAME })
    expect(previewCalls).toEqual([])

    await user.click(screen.getByRole('button', { name: OPEN_LABEL }))

    expect(previewCalls).toEqual([])
    expect(onOpenDocument).toHaveBeenCalledWith('doc-0', DOC_NAME)
  })

  it('podobieństwo zaokrągla do pełnych procentów', async () => {
    const { chip } = await renderChip({ similarity: 0.005 })
    const user = userEvent.setup()

    await user.click(chip)

    expect(await screen.findByText(`${SIMILARITY_PREFIX} 1%`)).toBeInTheDocument()
  })
})
