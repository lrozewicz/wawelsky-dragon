/**
 * Testy `MoveFilesDialog` (kontrakt WP E4-5c §7, przykłady 4–6): leniwe drzewo, wybór folderu
 * docelowego przez `aria-selected`, wyłączone foldery źródłowe, błąd koperty jako `Alert`,
 * brak folderów oraz węzeł-liść bez strzałki.
 */

import { useState } from 'react'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, filesFixtureItems, filesFixtureRoot } from '../../test/msw/handlers'
import type { FileItem } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { MoveFilesDialog } from './MoveFilesDialog'

afterEach(cleanup)

const FILE = filesFixtureItems.find((item) => item.id === 'file-1')!
const FOLDER = filesFixtureItems.find((item) => item.id === 'folder-1')!

function captureMove(): { bodies: unknown[] } {
  const bodies: unknown[] = []
  server.use(
    http.post(apiUrl('/api/v1/files/move'), async ({ request }) => {
      bodies.push(await request.json())
      return HttpResponse.json({ code: 0, message: '', data: true })
    }),
  )
  return { bodies }
}

/** Podmienia listing roota na podane wiersze (wspólny dla drzewa i `filesListQueryOptions`). */
function rootListing(files: FileItem[]): void {
  server.use(
    http.get(apiUrl('/api/v1/files'), () =>
      HttpResponse.json({
        code: 0,
        message: '',
        data: { files, parent_folder: filesFixtureRoot, total: files.length },
      }),
    ),
  )
}

async function openRoot(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(await screen.findByTestId('folder-expand-__root__'))
}

describe('MoveFilesDialog', () => {
  it('przenosi pliki do wybranego folderu przez `move`', async () => {
    const capture = captureMove()
    const onClose = vi.fn()
    await renderWithProviders(<MoveFilesDialog files={[FILE]} onClose={onClose} />)
    const user = userEvent.setup()

    expect(screen.getByTestId('files-move-confirm')).toBeDisabled()
    await openRoot(user)
    const node = await screen.findByTestId('folder-node-folder-1')
    await user.click(node)

    expect(node).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByTestId('files-move-confirm'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(capture.bodies).toEqual([{ src_file_ids: ['file-1'], dest_file_id: 'folder-1' }])
    expect(await screen.findByText('Przeniesiono.')).toBeInTheDocument()
  })

  it('root jako cel używa `parentFolder.id` z listingu', async () => {
    const capture = captureMove()
    await renderWithProviders(<MoveFilesDialog files={[FILE]} onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.click(screen.getByTestId('folder-node-__root__'))
    await waitFor(() => expect(screen.getByTestId('files-move-confirm')).toBeEnabled())
    await user.click(screen.getByTestId('files-move-confirm'))

    await waitFor(() => expect(capture.bodies).toHaveLength(1))
    expect(capture.bodies[0]).toEqual({ src_file_ids: ['file-1'], dest_file_id: 'root-1' })
  })

  it('folder źródłowy jest wyłączony, nie rozwija się i nie da się go wybrać', async () => {
    await renderWithProviders(<MoveFilesDialog files={[FOLDER]} onClose={() => undefined} />)
    const user = userEvent.setup()

    await openRoot(user)
    const node = await screen.findByTestId('folder-node-folder-1')

    expect(node).toHaveAttribute('aria-disabled', 'true')
    // Źródło nie ma strzałki rozwijania — jego potomków nie da się pokazać ani wybrać.
    expect(screen.queryByTestId('folder-expand-folder-1')).not.toBeInTheDocument()
    // Wyłączony przycisk ma `pointer-events: none`, więc omijamy warstwę wskaźnika `userEvent`.
    fireEvent.click(node)
    expect(node).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByTestId('files-move-confirm')).toBeDisabled()
  })

  it('błąd koperty pokazuje `Alert` i nie zamyka okna', async () => {
    server.use(
      http.post(apiUrl('/api/v1/files/move'), () =>
        HttpResponse.json({
          code: 102,
          message: 'Cannot move folder to its subfolder',
          data: false,
        }),
      ),
    )
    const onClose = vi.fn()
    await renderWithProviders(<MoveFilesDialog files={[FILE]} onClose={onClose} />)
    const user = userEvent.setup()

    await openRoot(user)
    await user.click(await screen.findByTestId('folder-node-folder-1'))
    await user.click(screen.getByTestId('files-move-confirm'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Cannot move folder to its subfolder',
    )
    expect(onClose).not.toHaveBeenCalled()
  })

  it('bez folderów pokazuje komunikat i blokuje przenoszenie', async () => {
    rootListing([])
    await renderWithProviders(<MoveFilesDialog files={[FILE]} onClose={() => undefined} />)

    expect(await screen.findByTestId('files-move-empty')).toHaveTextContent(
      'Brak dostępnych folderów.',
    )
    expect(screen.queryByTestId('folder-node-__root__')).not.toBeInTheDocument()
  })

  it('węzeł-liść bez `has_child_folder` nie ma strzałki rozwijania', async () => {
    rootListing([{ ...FOLDER, id: 'empty-folder', name: 'Pusty', has_child_folder: false }])
    await renderWithProviders(<MoveFilesDialog files={[FILE]} onClose={() => undefined} />)
    const user = userEvent.setup()

    await openRoot(user)
    expect(await screen.findByTestId('folder-node-empty-folder')).toBeInTheDocument()
    expect(screen.queryByTestId('folder-expand-empty-folder')).not.toBeInTheDocument()
  })

  it('po ponownym otwarciu czyści wybór', async () => {
    function Harness() {
      const [files, setFiles] = useState<FileItem[] | null>(null)
      return (
        <>
          <button
            type="button"
            data-testid="toggle"
            onClick={() => setFiles(files === null ? [FILE] : null)}
          >
            toggle
          </button>
          <MoveFilesDialog files={files} onClose={() => setFiles(null)} />
        </>
      )
    }

    await renderWithProviders(<Harness />)
    const user = userEvent.setup()

    await user.click(screen.getByTestId('toggle'))
    await openRoot(user)
    await user.click(await screen.findByTestId('folder-node-folder-1'))
    expect(screen.getByTestId('files-move-confirm')).toBeEnabled()

    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(screen.getByTestId('files-move-confirm')).toBeDisabled()
  })
})
