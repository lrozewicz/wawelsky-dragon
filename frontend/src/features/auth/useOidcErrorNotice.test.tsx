import { cleanup, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { useOidcErrorNotice } from './useOidcErrorNotice'

afterEach(cleanup)

// Gospodarz imituje trasę: `error` pochodzi z adresu, tak jak w `routes/login.tsx` i `_app/index.tsx`.
function Host(props: { error?: string }): null {
  useOidcErrorNotice(props.error)
  return null
}

describe('useOidcErrorNotice', () => {
  it('pokazuje powiadomienie i usuwa parametr z adresu', async () => {
    const { router } = await renderWithProviders(<Host error="invalid_state" />, {
      route: '/?error=invalid_state',
    })

    expect(
      await screen.findByText('Sesja logowania wygasła — spróbuj ponownie.'),
    ).toBeInTheDocument()
    await waitFor(() => expect(router.state.location.search).toEqual({}))
  })

  it('nieznany slug pokazuje komunikat ogólny', async () => {
    await renderWithProviders(<Host error="nieznany" />, { route: '/?error=nieznany' })

    expect(
      await screen.findByText('Logowanie przez dostawcę tożsamości nie powiodło się.'),
    ).toBeInTheDocument()
  })

  it('bez parametru nie pokazuje nic i nie rusza adresu', async () => {
    const { router } = await renderWithProviders(<Host />, { route: '/?error=invalid_state' })

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(router.state.location.search).toEqual({ error: 'invalid_state' })
  })
})
