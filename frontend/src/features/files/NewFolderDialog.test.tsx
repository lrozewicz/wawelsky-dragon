/**
 * Testy `NewFolderDialog` (kontrakt WP E4-5c §7, przykład 1–2): JSON folderu z `parent_id`,
 * sukces przez `onClose` i toast, puste pole bez żądania, błąd koperty jako `Alert`.
 */

import { useState } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { NewFolderDialog } from './NewFolderDialog'

afterEach(cleanup)

const CREATED = {
  id: 'folder-new',
  tenant_id: 'tenant-1',
  created_by: 'user-1',
  parent_id: 'root-1',
  name: 'Faktury',
  type: 'folder',
  size: 0,
  location: '',
  source_type: 'local',
}

function captureCreate(response = CREATED): { bodies: unknown[]; posts: number } {
  const bodies: unknown[] = []
  server.use(
    http.post(apiUrl('/api/v1/files'), async ({ request }) => {
      bodies.push(await request.json())
      return HttpResponse.json({ code: 0, message: '', data: response })
    }),
  )
  return {
    bodies,
    get posts() {
      return bodies.length
    },
  }
}

/** Okno da się zamykać i otwierać — potrzebne do sprawdzenia resetu pola i komunikatu. */
function Harness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button type="button" data-testid="toggle" onClick={() => setOpen((value) => !value)}>
        toggle
      </button>
      <NewFolderDialog open={open} parentId="root-1" onClose={() => setOpen(false)} />
    </>
  )
}

describe('NewFolderDialog', () => {
  it('tworzy folder z `parent_id` i po sukcesie woła `onClose` i toast', async () => {
    const captured = captureCreate()
    const onClose = vi.fn()
    await renderWithProviders(<NewFolderDialog open parentId="root-1" onClose={onClose} />)
    const user = userEvent.setup()

    await user.type(screen.getByTestId('files-folder-name'), 'Faktury')
    await user.click(screen.getByTestId('files-folder-create'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(captured.bodies).toEqual([{ name: 'Faktury', type: 'folder', parent_id: 'root-1' }])
    expect(await screen.findByText('Utworzono folder.')).toBeInTheDocument()
  })

  it('pomija `parent_id` przy tworzeniu w roocie', async () => {
    const captured = captureCreate()
    await renderWithProviders(
      <NewFolderDialog open parentId={undefined} onClose={() => undefined} />,
    )
    const user = userEvent.setup()

    await user.type(screen.getByTestId('files-folder-name'), 'Bez rodzica')
    await user.click(screen.getByTestId('files-folder-create'))

    await waitFor(() => expect(captured.bodies).toHaveLength(1))
    expect(captured.bodies[0]).toEqual({ name: 'Bez rodzica', type: 'folder' })
  })

  it('puste pole po trim nie wysyła żądania i pokazuje komunikat', async () => {
    const captured = captureCreate()
    await renderWithProviders(<NewFolderDialog open parentId="root-1" onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.type(screen.getByTestId('files-folder-name'), '   ')
    await user.click(screen.getByTestId('files-folder-create'))

    expect(screen.getByText('Podaj nazwę folderu.')).toBeInTheDocument()
    expect(captured.posts).toBe(0)
  })

  it('klik z pustym polem wraca fokusem do pola, etykieta zostaje nad nim (U11)', async () => {
    await renderWithProviders(<NewFolderDialog open parentId="root-1" onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.click(screen.getByTestId('files-folder-create'))

    const field = screen.getByTestId('files-folder-name')
    expect(field).toHaveFocus()
    expect(screen.getByText('Podaj nazwę folderu.')).toBeInTheDocument()
    expect(field.closest('.MuiFormControl-root')?.querySelector('.MuiInputLabel-root')).toHaveClass(
      'MuiInputLabel-shrink',
    )
  })

  it('błąd koperty pokazuje `Alert` i nie zamyka okna', async () => {
    server.use(
      http.post(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({ code: 102, message: 'Folder already exists', data: false }),
      ),
    )
    const onClose = vi.fn()
    await renderWithProviders(<NewFolderDialog open parentId="root-1" onClose={onClose} />)
    const user = userEvent.setup()

    await user.type(screen.getByTestId('files-folder-name'), 'Faktury')
    await user.click(screen.getByTestId('files-folder-create'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Folder already exists')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('po ponownym otwarciu czyści pole i komunikat', async () => {
    await renderWithProviders(<Harness />)
    const user = userEvent.setup()

    await user.type(screen.getByTestId('files-folder-name'), '   ')
    await user.click(screen.getByTestId('files-folder-create'))
    expect(screen.getByText('Podaj nazwę folderu.')).toBeInTheDocument()

    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(screen.getByTestId('files-folder-name')).toHaveValue('')
    expect(screen.queryByText('Podaj nazwę folderu.')).not.toBeInTheDocument()
  })
})
