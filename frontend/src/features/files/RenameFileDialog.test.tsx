/**
 * Testy `RenameFileDialog` (kontrakt WP E4-5c §7, przykład 3): pole startuje z nazwą pliku,
 * zapis wysyła `move` z `new_name`, a nazwa pusta/niezmieniona blokuje przycisk.
 */

import { useState } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, filesFixtureItems } from '../../test/msw/handlers'
import type { FileItem } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { RenameFileDialog } from './RenameFileDialog'

afterEach(cleanup)

const FILE = filesFixtureItems.find((item) => item.id === 'file-1')!

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

/** Okno da się zamknąć i otworzyć ponownie — potrzebne do sprawdzenia resetu pola. */
function Harness({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<FileItem | null>(FILE)
  return (
    <>
      <button
        type="button"
        data-testid="toggle"
        onClick={() => setFile(file === null ? FILE : null)}
      >
        toggle
      </button>
      <RenameFileDialog file={file} onClose={onClose} />
    </>
  )
}

describe('RenameFileDialog', () => {
  it('startuje z nazwą pliku i zapisuje nową nazwę', async () => {
    const capture = captureMove()
    const onClose = vi.fn()
    await renderWithProviders(<RenameFileDialog file={FILE} onClose={onClose} />)
    const user = userEvent.setup()

    expect(screen.getByTestId('files-rename-name')).toHaveValue('notatki.txt')
    await user.clear(screen.getByTestId('files-rename-name'))
    await user.type(screen.getByTestId('files-rename-name'), 'inna.txt')
    await user.click(screen.getByTestId('files-rename-save'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(capture.bodies).toEqual([{ src_file_ids: ['file-1'], new_name: 'inna.txt' }])
    expect(await screen.findByText('Zmieniono nazwę.')).toBeInTheDocument()
  })

  it('niezmieniona nazwa blokuje przycisk i nie wysyła żądania', async () => {
    const capture = captureMove()
    const onClose = vi.fn()
    await renderWithProviders(<RenameFileDialog file={FILE} onClose={onClose} />)

    expect(screen.getByTestId('files-rename-save')).toBeDisabled()
    expect(capture.bodies).toHaveLength(0)
  })

  it('pusta nazwa po trim blokuje przycisk', async () => {
    const capture = captureMove()
    await renderWithProviders(<RenameFileDialog file={FILE} onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.clear(screen.getByTestId('files-rename-name'))
    await user.type(screen.getByTestId('files-rename-name'), '   ')

    expect(screen.getByTestId('files-rename-save')).toBeDisabled()
    expect(capture.bodies).toHaveLength(0)
  })

  it('błąd koperty pokazuje `Alert` i nie zamyka okna', async () => {
    server.use(
      http.post(apiUrl('/api/v1/files/move'), () =>
        HttpResponse.json({ code: 102, message: 'Name already used', data: false }),
      ),
    )
    const onClose = vi.fn()
    await renderWithProviders(<RenameFileDialog file={FILE} onClose={onClose} />)
    const user = userEvent.setup()

    await user.clear(screen.getByTestId('files-rename-name'))
    await user.type(screen.getByTestId('files-rename-name'), 'zajeta.txt')
    await user.click(screen.getByTestId('files-rename-save'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Name already used')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('po ponownym otwarciu pole znów pokazuje nazwę pliku', async () => {
    await renderWithProviders(<Harness onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.clear(screen.getByTestId('files-rename-name'))
    await user.type(screen.getByTestId('files-rename-name'), 'cokolwiek')
    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(screen.getByTestId('files-rename-name')).toHaveValue('notatki.txt')
  })
})
