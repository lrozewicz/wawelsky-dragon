import { cleanup, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureLoginChannel } from '../../test/msw/handlers'
import type { FixtureSystemConfig } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { useLoginChannels, useSystemConfig } from './queries'

afterEach(cleanup)

function ChannelsProbe() {
  return (
    <span data-testid="channels">
      {useLoginChannels()
        .map((channel) => channel.channel)
        .join(',')}
    </span>
  )
}

function ConfigProbe() {
  const config = useSystemConfig()
  if (config === undefined) return <span>brak</span>
  return <span>{`${config.registerEnabled}/${config.disablePasswordLogin}`}</span>
}

function channelsHandler(data: unknown) {
  return http.get(apiUrl('/api/v1/auth/login/channels'), () =>
    HttpResponse.json({ code: 0, message: 'success', data }),
  )
}

function configHandler(config: FixtureSystemConfig) {
  return http.get(apiUrl('/api/v1/system/config'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: config }),
  )
}

describe('useLoginChannels', () => {
  it('zwraca kanały wystawione przez instancję', async () => {
    server.use(channelsHandler([fixtureLoginChannel]))

    const { queryClient } = await renderWithProviders(<ChannelsProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['auth', 'login-channels'])?.status).toBe('success')
    })
    expect(screen.getByTestId('channels')).toHaveTextContent('keycloak')
  })

  it('brak kanałów daje pustą listę', async () => {
    const { queryClient } = await renderWithProviders(<ChannelsProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['auth', 'login-channels'])?.status).toBe('success')
    })
    expect(screen.getByTestId('channels').textContent).toBe('')
  })

  it('błąd żądania daje pustą listę', async () => {
    server.use(
      http.get(apiUrl('/api/v1/auth/login/channels'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
    )

    const { queryClient } = await renderWithProviders(<ChannelsProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['auth', 'login-channels'])?.status).toBe('error')
    })
    expect(screen.getByTestId('channels').textContent).toBe('')
  })
})

describe('useSystemConfig', () => {
  it('zwraca flagi instancji', async () => {
    const { queryClient } = await renderWithProviders(<ConfigProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['system', 'config'])?.status).toBe('success')
    })
    expect(screen.getByText('0/false')).toBeInTheDocument()
  })

  it('błąd żądania zostawia flagi nieznane', async () => {
    server.use(
      http.get(apiUrl('/api/v1/system/config'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
    )

    const { queryClient } = await renderWithProviders(<ConfigProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['system', 'config'])?.status).toBe('error')
    })
    expect(screen.getByText('brak')).toBeInTheDocument()
  })

  it('odczytuje registerEnabled 1 i wyłączone logowanie hasłem', async () => {
    server.use(configHandler({ registerEnabled: 1, disablePasswordLogin: true }))

    await renderWithProviders(<ConfigProbe />)

    expect(await screen.findByText('1/true')).toBeInTheDocument()
  })
})
