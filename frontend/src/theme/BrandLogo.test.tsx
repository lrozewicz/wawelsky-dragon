import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import { initI18n } from '../i18n'
import AppTheme from './AppTheme'
import { BrandLogo } from './BrandLogo'

beforeAll(async () => {
  await initI18n('pl')
})

// Vitest bez `globals` nie rejestruje automatycznego czyszczenia DOM z RTL.
afterEach(cleanup)

describe('BrandLogo', () => {
  it('renderuje się w AppTheme jako obraz o nazwie aplikacji', () => {
    render(
      <AppTheme>
        <BrandLogo />
      </AppTheme>,
    )

    expect(screen.getByRole('img', { name: 'Wawelsky Dragon' })).toBeInTheDocument()
  })

  it('ma domyślny rozmiar 32, a size={48} ustawia width/height na 48; full zachowuje proporcje', () => {
    const { rerender } = render(
      <AppTheme>
        <BrandLogo />
      </AppTheme>,
    )

    const logo = screen.getByRole('img', { name: 'Wawelsky Dragon' })
    expect(logo).toHaveAttribute('width', '32')
    expect(logo).toHaveAttribute('height', '32')

    rerender(
      <AppTheme>
        <BrandLogo size={48} />
      </AppTheme>,
    )

    const bigger = screen.getByRole('img', { name: 'Wawelsky Dragon' })
    expect(bigger).toHaveAttribute('width', '48')
    expect(bigger).toHaveAttribute('height', '48')

    rerender(
      <AppTheme>
        <BrandLogo variant="full" size={240} />
      </AppTheme>,
    )

    const full = screen.getByRole('img', { name: 'Wawelsky Dragon' })
    expect(full).toHaveAttribute('width', '240')
    expect(full).toHaveAttribute('height', '124')
  })
})
