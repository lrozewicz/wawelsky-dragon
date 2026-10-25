/**
 * Testy `RowActions` (kontrakt WP E3-3b §T6): trzy przyciski wołają swoje callbacki, a usuwanie
 * jest nieaktywne dokładnie wtedy, gdy `canDelete` na to nie pozwala (parsowanie w kolejce lub
 * w toku). Dla nieaktywnego usuwania podpowiedź mówi, dlaczego akcja jest zablokowana.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { RowActions } from './RowActions'
import type { DocumentRow } from './queries'

afterEach(cleanup)

type ActionDoc = Pick<DocumentRow, 'id' | 'name' | 'run' | 'progress' | 'chunk_count'>

function doc(overrides: Partial<ActionDoc> = {}): ActionDoc {
  return { id: 'doc-1', name: 'plik.pdf', run: 'DONE', progress: 1, chunk_count: 3, ...overrides }
}

function renderActions(
  document: ActionDoc,
  callbacks?: {
    onRename: () => void
    onDownload: () => void
    onDelete: () => void
    onMetadata: () => void
  },
) {
  const handlers = callbacks ?? {
    onRename: vi.fn(),
    onDownload: vi.fn(),
    onDelete: vi.fn(),
    onMetadata: vi.fn(),
  }
  return renderWithProviders(
    <RowActions
      doc={document}
      onRename={handlers.onRename}
      onDownload={handlers.onDownload}
      onDelete={handlers.onDelete}
      onMetadata={handlers.onMetadata}
    />,
  )
}

describe('RowActions', () => {
  it('renderuje trzy ikony z etykietami i woła trzy callbacki', async () => {
    const onRename = vi.fn()
    const onDownload = vi.fn()
    const onDelete = vi.fn()
    await renderActions(doc(), { onRename, onDownload, onDelete, onMetadata: vi.fn() })
    const user = userEvent.setup()

    expect(screen.getByRole('button', { name: 'Zmień nazwę' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pobierz' })).toBeInTheDocument()

    await user.click(screen.getByTestId('row-rename-doc-1'))
    await user.click(screen.getByTestId('row-download-doc-1'))
    await user.click(screen.getByTestId('row-delete-doc-1'))

    expect(onRename).toHaveBeenCalledTimes(1)
    expect(onDownload).toHaveBeenCalledTimes(1)
    expect(onDelete).toHaveBeenCalledTimes(1)
  })

  const blocked: { run: ActionDoc['run']; progress: number }[] = [
    { run: 'RUNNING', progress: 0.4 },
    { run: 'SCHEDULE', progress: 0 },
  ]

  it.each(blocked)(
    'blokuje usuwanie przy run=$run i pokazuje powód w podpowiedzi',
    async ({ run, progress }) => {
      await renderActions(doc({ run, progress }))
      const user = userEvent.setup()

      const button = screen.getByTestId('row-delete-doc-1')
      expect(button).toBeDisabled()

      await user.hover(button.parentElement as HTMLElement)
      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        'Nie można usunąć w trakcie parsowania',
      )
    },
  )

  it('pozwala usunąć dokument, gdy parsowanie się zakończyło', async () => {
    const onDelete = vi.fn()
    await renderActions(doc({ run: 'DONE' }), {
      onRename: vi.fn(),
      onDownload: vi.fn(),
      onDelete,
      onMetadata: vi.fn(),
    })
    const user = userEvent.setup()

    const button = screen.getByTestId('row-delete-doc-1')
    expect(button).toBeEnabled()
    await user.click(button)
    expect(onDelete).toHaveBeenCalledTimes(1)
  })

  it('⋮ otwiera menu z pozycją „Metadane”, która woła `onMetadata` (WP E6-1b T5a)', async () => {
    const onMetadata = vi.fn()
    await renderActions(doc(), {
      onRename: vi.fn(),
      onDownload: vi.fn(),
      onDelete: vi.fn(),
      onMetadata,
    })
    const user = userEvent.setup()

    await user.click(screen.getByTestId('row-actions-menu'))
    const item = await screen.findByRole('menuitem', { name: 'Metadane' })
    await user.click(item)
    expect(onMetadata).toHaveBeenCalledTimes(1)
  })
})
