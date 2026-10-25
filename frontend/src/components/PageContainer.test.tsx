import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../test/renderWithProviders'

import PageContainer from './PageContainer'

afterEach(cleanup)

describe('PageContainer', () => {
  it('renderuje tytuł, breadcrumbs, akcje i treść', async () => {
    await renderWithProviders(
      <PageContainer
        title="Tytuł"
        breadcrumbs={[{ title: 'Start', path: '/' }, { title: 'Bieżąca' }]}
        actions={<button>Akcja</button>}
      >
        <p>treść</p>
      </PageContainer>,
      { routes: ['/'] },
    )

    const startLink = screen.getByRole('link', { name: 'Start' })
    expect(startLink).toHaveAttribute('href', '/')
    expect(screen.getByText('Bieżąca')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Bieżąca' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Tytuł' })).toBeInTheDocument()
    expect(screen.getByText('treść')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Akcja' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Ścieżka nawigacji' })).toBeInTheDocument()
  })

  it('renderuje się bez breadcrumbs, tytułu i akcji', async () => {
    await renderWithProviders(
      <PageContainer>
        <p>treść</p>
      </PageContainer>,
    )

    expect(screen.getByText('treść')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Ścieżka nawigacji' })).toBeInTheDocument()
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  })
})
