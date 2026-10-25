import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { NavbarBreadcrumbs } from './NavbarBreadcrumbs'

afterEach(cleanup)

describe('NavbarBreadcrumbs', () => {
  it('na stronie głównej pokazuje nazwę aplikacji i Start', async () => {
    await renderWithProviders(<NavbarBreadcrumbs pathname="/" />, { route: '/' })

    expect(screen.getByText('Wawelsky Dragon')).toBeInTheDocument()
    expect(screen.getByText('Start')).toBeInTheDocument()
  })

  it('dla nieznanej trasy pokazuje tylko nazwę aplikacji', async () => {
    await renderWithProviders(<NavbarBreadcrumbs pathname="/nieznana" />, { route: '/' })

    expect(screen.getByText('Wawelsky Dragon')).toBeInTheDocument()
    expect(screen.queryByText('Start')).not.toBeInTheDocument()
    expect(screen.queryByText('Bazy wiedzy')).not.toBeInTheDocument()
  })
})
