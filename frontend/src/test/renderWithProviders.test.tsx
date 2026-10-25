import { cleanup, screen } from '@testing-library/react'
import { QueryClient } from '@tanstack/react-query'
import { useRouterState } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fixtureUser } from './msw/handlers'
import { renderWithProviders } from './renderWithProviders'

afterEach(cleanup)

function RouteProbe() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const { t } = useTranslation()

  return (
    <span>
      {pathname}|{t('nav.home')}
    </span>
  )
}

describe('renderWithProviders', () => {
  it('z `route` i `routes` renderuje komponent na podanej ścieżce', async () => {
    await renderWithProviders(<RouteProbe />, { route: '/abc', routes: ['/abc'] })

    expect(screen.getByText('/abc|Start')).toBeInTheDocument()
  })

  it('z `language: en` używa angielskich tłumaczeń', async () => {
    await renderWithProviders(<RouteProbe />, { language: 'en' })

    expect(screen.getByText('/|Home')).toBeInTheDocument()
  })

  it('zwraca router testowy', async () => {
    const { router } = await renderWithProviders(<RouteProbe />, {
      route: '/abc',
      routes: ['/abc'],
    })

    expect(router.state.location.pathname).toBe('/abc')
  })

  it('dokłada kontekst sesji i klienta zapytań do routera testowego', async () => {
    const { queryClient, router } = await renderWithProviders(<RouteProbe />)

    expect(router.options.context.auth.user).toEqual(fixtureUser)
    expect(await router.options.context.auth.ensureSession()).toEqual(fixtureUser)
    expect(router.options.context.queryClient).toBe(queryClient)
  })

  it('domyślny klient testowy nie ponawia zapytań i nie wyrzuca ich z cache', async () => {
    const { queryClient } = await renderWithProviders(<RouteProbe />)

    expect(queryClient.getDefaultOptions().queries?.retry).toBe(false)
    expect(queryClient.getDefaultOptions().queries?.gcTime).toBe(Infinity)
  })

  it('`auth` nadpisuje atrapę sesji', async () => {
    const ensureSession = vi.fn(async () => null)
    const { router } = await renderWithProviders(<RouteProbe />, {
      auth: { user: null, ensureSession },
    })

    expect(router.options.context.auth.user).toBeNull()
    expect(router.options.context.auth.ensureSession).toBe(ensureSession)
  })

  it('przyjmuje własny klient zapytań', async () => {
    const custom = new QueryClient()
    const { queryClient } = await renderWithProviders(<RouteProbe />, { queryClient: custom })

    expect(queryClient).toBe(custom)
  })
})
