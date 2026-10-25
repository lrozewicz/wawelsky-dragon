/**
 * Ścieżka nawigacji (kontrakt WP E4-5c §3, §7): root jako sam tekst, a dla folderu
 * „Pliki” (klikalne) → przodkowie → bieżący bez linku (`aria-current="page"`).
 * Dane przodków pochodzą z ziarna MSW (`folder-1` „Projekty”); głębszy łańcuch podstawiamy
 * własnym handlerem, żeby sprawdzić pośredniego przodka jako link.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { FilesBreadcrumbs } from './FilesBreadcrumbs'
import type { FileParent } from './queries'

afterEach(cleanup)

/** Folder-kontekst (schemat `FileParent`) na potrzeby łańcucha przodków. */
function parent(id: string, name: string): FileParent {
  return {
    id,
    name,
    parent_id: id,
    tenant_id: 'tenant-1',
    created_by: 'user-1',
    type: 'folder',
    size: 0,
    location: '',
    source_type: '',
    create_time: 1,
    create_date: '2025-01-01 00:00:00',
    update_time: 1,
    update_date: '2025-01-01 00:00:00',
  }
}

describe('FilesBreadcrumbs', () => {
  it('bez folderu pokazuje sam tekst „Pliki”', async () => {
    await renderWithProviders(<FilesBreadcrumbs folderId={undefined} onNavigate={vi.fn()} />)

    expect(screen.getByTestId('files-breadcrumbs')).toHaveTextContent('Pliki')
    expect(screen.queryByRole('button', { name: 'Pliki' })).not.toBeInTheDocument()
  })

  it('dla folderu pokazuje root-link i bieżący folder bez linku', async () => {
    const onNavigate = vi.fn()
    const user = userEvent.setup()

    await renderWithProviders(<FilesBreadcrumbs folderId="folder-1" onNavigate={onNavigate} />)

    await screen.findByText('Projekty')
    await user.click(screen.getByRole('button', { name: 'Pliki' }))
    expect(onNavigate).toHaveBeenCalledWith(undefined)

    // Bieżący folder jest tekstem z `aria-current`, nie linkiem.
    expect(screen.getByText('Projekty')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('Projekty').closest('button')).toBeNull()
  })

  it('pośredni przodek jest linkiem prowadzącym do swojego folderu', async () => {
    server.use(
      http.get(apiUrl('/api/v1/files/:fileId/ancestors'), () =>
        HttpResponse.json({
          code: 0,
          message: '',
          data: {
            // Kolejność API: [bieżący, …, root].
            parent_folders: [
              parent('deep', 'Kadry'),
              parent('mid', 'Projekty'),
              parent('root-1', 'Pliki'),
            ],
          },
        }),
      ),
    )
    const onNavigate = vi.fn()
    const user = userEvent.setup()

    await renderWithProviders(<FilesBreadcrumbs folderId="deep" onNavigate={onNavigate} />)

    await user.click(await screen.findByRole('button', { name: 'Projekty' }))
    expect(onNavigate).toHaveBeenCalledWith('mid')

    expect(screen.getByText('Kadry')).toHaveAttribute('aria-current', 'page')
  })
})
