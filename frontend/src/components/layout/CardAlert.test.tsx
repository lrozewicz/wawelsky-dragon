import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { CardAlert } from './CardAlert'

const ROUTES = ['/user-setting/model']

afterEach(cleanup)

describe('CardAlert', () => {
  it('nic nie renderuje, gdy show jest fałszywe', async () => {
    await renderWithProviders(<CardAlert show={false} />, { routes: ROUTES })
    expect(screen.queryByText('Skonfiguruj modele')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('pokazuje treść i link do ustawień modeli, gdy show jest prawdziwe', async () => {
    await renderWithProviders(<CardAlert show />, { routes: ROUTES })

    expect(screen.getByText('Skonfiguruj modele')).toBeInTheDocument()
    expect(screen.getByText('Brak domyślnego modelu LLM lub embeddingu.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Przejdź do ustawień' })).toHaveAttribute(
      'href',
      '/user-setting/model',
    )
  })
})
