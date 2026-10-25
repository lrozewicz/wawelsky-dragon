/**
 * Siatka plików (kontrakt WP E4-5c §4): kolumny (Nazwa z ikoną i linkiem folderu, Data, Rozmiar,
 * Datasety jako chip-link, Akcje), paginacja serwerowa i zaznaczanie przekazywane rodzicowi.
 */

import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Language } from '../../i18n'
import { renderWithProviders } from '../../test/renderWithProviders'

import { FilesGrid } from './FilesGrid'
import type { FileAction } from './FileRowActions'
import type { FileItem } from './queries'

afterEach(cleanup)

/** Trasy potrzebne, by chip datasetu (link-routera) miał dokąd prowadzić. */
const ROUTES = ['/dataset/files/$id']

function item(overrides: Partial<FileItem> & { id: string; name: string }): FileItem {
  const { id, name, ...rest } = overrides
  return {
    id,
    name,
    parent_id: 'root-1',
    tenant_id: 'tenant-1',
    created_by: 'user-1',
    type: 'doc',
    size: 0,
    location: name,
    source_type: '',
    create_time: 1,
    create_date: '2025-01-01 00:00:00',
    update_time: 1,
    update_date: '2025-01-01 00:00:00',
    kbs_info: [],
    has_child_folder: null,
    ...rest,
  }
}

function folder(id: string, name: string): FileItem {
  return item({ id, name, type: 'folder', location: '' })
}

type RenderGridOptions = {
  rows?: FileItem[]
  total?: number
  onOpenFolder?: (id: string) => void
  onAction?: (action: FileAction, file: FileItem) => void
  onPageChange?: (page: number, pageSize: number) => void
  onSelectedChange?: (ids: string[]) => void
  language?: Language
}

function renderGrid(options: RenderGridOptions = {}) {
  return renderWithProviders(
    <FilesGrid
      rows={
        options.rows ?? [
          folder('folder-1', 'Projekty'),
          item({ id: 'file-1', name: 'notatki.txt', size: 1234 }),
        ]
      }
      total={options.total ?? 2}
      loading={false}
      page={1}
      pageSize={15}
      selectedIds={[]}
      onSelectedChange={options.onSelectedChange ?? vi.fn()}
      onPageChange={options.onPageChange ?? vi.fn()}
      onOpenFolder={options.onOpenFolder ?? vi.fn()}
      onAction={options.onAction ?? vi.fn()}
    />,
    { routes: ROUTES, language: options.language },
  )
}

describe('FilesGrid', () => {
  it('w języku angielskim pokazuje angielskie nagłówki kolumn', async () => {
    await renderGrid({ language: 'en' })

    expect(await screen.findByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Size')).toBeInTheDocument()
  })

  it('renderuje wiersze: folder jako link, plik jako tekst, rozmiar sformatowany', async () => {
    const onOpenFolder = vi.fn()
    const user = userEvent.setup()

    await renderGrid({ onOpenFolder })

    expect(screen.getByTestId('files-grid')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Projekty' }))
    expect(onOpenFolder).toHaveBeenCalledWith('folder-1')

    // Plik nie jest linkiem, a folder nie ma rozmiaru (myślnik).
    expect(screen.getByText('notatki.txt').closest('button')).toBeNull()
    expect(screen.getByText('1,2 KB')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('wiersz raport.pdf pokazuje chip datasetu z nazwą i linkiem szczegółów', async () => {
    await renderGrid({
      rows: [
        item({
          id: 'file-2',
          name: 'raport.pdf',
          kbs_info: [{ kb_id: 'ds-1', kb_name: 'Baza wiedzy', document_id: 'doc-1' }],
        }),
      ],
      total: 1,
    })

    const chip = await screen.findByTestId('files-kb-chip')
    expect(chip).toHaveTextContent('Baza wiedzy')
    expect(chip).toHaveAttribute('href', '/dataset/files/ds-1')
  })

  it('klik akcji wiersza woła onAction z akcją i plikiem', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()

    await renderGrid({ onAction })

    const row = (await screen.findByText('notatki.txt')).closest('[role="row"]') as HTMLElement
    await user.click(within(row).getByRole('button', { name: 'Zmień nazwę' }))
    expect(onAction).toHaveBeenCalledWith('rename', expect.objectContaining({ id: 'file-1' }))
  })

  it('plik bez kbs_info: pełny zestaw akcji, Podgląd zablokowany, każdy klik zgłoszony', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()

    await renderGrid({ rows: [item({ id: 'file-1', name: 'notatki.txt' })], total: 1, onAction })

    const row = (await screen.findByText('notatki.txt')).closest('[role="row"]') as HTMLElement
    expect(within(row).getByRole('button', { name: 'Podgląd' })).toBeDisabled()

    for (const label of ['Połącz z datasetem', 'Przenieś', 'Zmień nazwę', 'Pobierz', 'Usuń']) {
      await user.click(within(row).getByRole('button', { name: label }))
    }
    expect(onAction).toHaveBeenCalledTimes(5)
    expect(onAction).toHaveBeenCalledWith('link', expect.objectContaining({ id: 'file-1' }))
  })

  it('plik z kbs_info: Podgląd aktywny i zgłasza akcję preview', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()

    await renderGrid({
      rows: [
        item({
          id: 'file-2',
          name: 'raport.pdf',
          kbs_info: [{ kb_id: 'ds-1', kb_name: 'Baza wiedzy', document_id: 'doc-1' }],
        }),
      ],
      total: 1,
      onAction,
    })

    const row = (await screen.findByText('raport.pdf')).closest('[role="row"]') as HTMLElement
    await user.click(within(row).getByRole('button', { name: 'Podgląd' }))
    expect(onAction).toHaveBeenCalledWith('preview', expect.objectContaining({ id: 'file-2' }))
  })

  it('folder nie ma Połącz, Pobierz ani Podgląd', async () => {
    await renderGrid({ rows: [folder('folder-1', 'Projekty')], total: 1 })

    const row = (await screen.findByText('Projekty')).closest('[role="row"]') as HTMLElement
    expect(within(row).queryByRole('button', { name: 'Połącz z datasetem' })).toBeNull()
    expect(within(row).queryByRole('button', { name: 'Pobierz' })).toBeNull()
    expect(within(row).queryByRole('button', { name: 'Podgląd' })).toBeNull()
    expect(within(row).getByRole('button', { name: 'Przenieś' })).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Zmień nazwę' })).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Usuń' })).toBeInTheDocument()
  })

  it('przejście na następną stronę zgłasza page+1 i pageSize', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()

    await renderGrid({
      rows: [item({ id: 'file-1', name: 'a.txt' })],
      total: 30,
      onPageChange,
    })

    await user.click(await screen.findByRole('button', { name: 'Przejdź do następnej strony' }))
    expect(onPageChange).toHaveBeenCalledWith(2, 15)
  })

  it('zaznaczenie wiersza przekazuje identyfikatory do rodzica', async () => {
    const onSelectedChange = vi.fn()
    const user = userEvent.setup()

    await renderGrid({ onSelectedChange })

    const row = (await screen.findByText('Projekty')).closest('[role="row"]') as HTMLElement
    await user.click(within(row).getByRole('checkbox'))
    expect(onSelectedChange).toHaveBeenCalledWith(['folder-1'])
  })
})
