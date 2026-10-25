import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../test/renderWithProviders'

import { QueryError } from './QueryError'

afterEach(cleanup)

describe('QueryError', () => {
  it('pokazuje komunikat i przycisk „Spróbuj ponownie” z `data-testid="query-error"`', async () => {
    await renderWithProviders(
      <QueryError message="Nie udało się wczytać czatów." onRetry={vi.fn()} />,
    )

    const alert = screen.getByTestId('query-error')
    expect(alert).toHaveTextContent('Nie udało się wczytać czatów.')
    expect(screen.getByRole('button', { name: 'Spróbuj ponownie' })).toBeInTheDocument()
  })

  it('kliknięcie przycisku woła `onRetry`', async () => {
    const onRetry = vi.fn()
    await renderWithProviders(<QueryError message="Błąd" onRetry={onRetry} />)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
