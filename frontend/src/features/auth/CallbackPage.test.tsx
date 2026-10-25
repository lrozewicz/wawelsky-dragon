import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { CallbackPage } from './CallbackPage'

afterEach(cleanup)

describe('CallbackPage', () => {
  it('pokazuje spinner z etykietą i18n', async () => {
    await renderWithProviders(<CallbackPage />)

    expect(screen.getByRole('progressbar', { name: 'Kończenie logowania…' })).toBeInTheDocument()
  })
})
