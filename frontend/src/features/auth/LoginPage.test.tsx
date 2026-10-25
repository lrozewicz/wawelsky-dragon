import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import { ApiError } from '../../api/envelope'
import { apiUrl, fixtureLoginChannel, fixtureUser } from '../../test/msw/handlers'
import type { FixtureLoginChannel, FixtureSystemConfig } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import type { AuthUser } from './authState'
import { LoginPage } from './LoginPage'

afterEach(cleanup)

type LoginHandler = (email: string, password: string) => Promise<AuthUser>

// Router trasy `/login` poszerzony o `/chat`, żeby nawigacja po sukcesie miała dokąd trafić.
const ROUTES = ['/login', '/chat'] as const

function channelsHandler(data: FixtureLoginChannel[]) {
  return http.get(apiUrl('/api/v1/auth/login/channels'), () =>
    HttpResponse.json({ code: 0, message: 'success', data }),
  )
}

function configHandler(config: FixtureSystemConfig) {
  return http.get(apiUrl('/api/v1/system/config'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: config }),
  )
}

type RenderOptions = {
  login?: Mock<LoginHandler>
  redirectTo?: string
  route?: string
}

async function renderLoginPage(options: RenderOptions = {}) {
  const login = options.login ?? vi.fn<LoginHandler>(async () => fixtureUser)
  const result = await renderWithProviders(
    <LoginPage auth={{ login }} redirectTo={options.redirectTo} />,
    { route: options.route ?? '/login', routes: [...ROUTES] },
  )
  return { ...result, login }
}

describe('LoginPage — formularz logowania', () => {
  it('pusty formularz pokazuje błędy walidacji i nie woła login', async () => {
    const user = userEvent.setup()
    const { login } = await renderLoginPage()

    await user.click(screen.getByTestId('login-submit'))

    expect(await screen.findByText('Podaj poprawny adres e-mail.')).toBeInTheDocument()
    expect(screen.getByText('Podaj hasło.')).toBeInTheDocument()
    expect(login).not.toHaveBeenCalled()
  })

  it('niepoprawny e-mail nie przechodzi walidacji', async () => {
    const user = userEvent.setup()
    const { login } = await renderLoginPage()

    await user.type(screen.getByTestId('login-email'), 'nie-adres')
    await user.type(screen.getByTestId('login-password'), 'sekret')
    await user.click(screen.getByTestId('login-submit'))

    expect(await screen.findByText('Podaj poprawny adres e-mail.')).toBeInTheDocument()
    expect(login).not.toHaveBeenCalled()
  })

  it('błąd API pokazuje Alert login-error z komunikatem backendu', async () => {
    const user = userEvent.setup()
    const login = vi.fn<LoginHandler>(async () => {
      throw new ApiError(109, 'email or password is incorrect', 200)
    })
    await renderLoginPage({ login })

    await user.type(screen.getByTestId('login-email'), 'user@example.com')
    await user.type(screen.getByTestId('login-password'), 'zle-haslo')
    await user.click(screen.getByTestId('login-submit'))

    const alert = await screen.findByTestId('login-error')
    expect(alert).toHaveTextContent('email or password is incorrect')
    expect(login).toHaveBeenCalledWith('user@example.com', 'zle-haslo')
  })

  it('nieprzewidziany błąd pokazuje komunikat i18n', async () => {
    const user = userEvent.setup()
    const login = vi.fn<LoginHandler>(async () => {
      throw new Error('boom')
    })
    await renderLoginPage({ login })

    await user.type(screen.getByTestId('login-email'), 'user@example.com')
    await user.type(screen.getByTestId('login-password'), 'sekret')
    await user.click(screen.getByTestId('login-submit'))

    const alert = await screen.findByTestId('login-error')
    expect(alert).toHaveTextContent('Logowanie nie powiodło się — spróbuj ponownie.')
  })

  it('sukces z ?redirect=/chat nawiguje na /chat', async () => {
    const user = userEvent.setup()
    const { router, login } = await renderLoginPage({ redirectTo: '/chat' })

    await user.type(screen.getByTestId('login-email'), 'user@example.com')
    await user.type(screen.getByTestId('login-password'), 'secret')
    await user.click(screen.getByTestId('login-submit'))

    await waitFor(() => expect(router.state.location.pathname).toBe('/chat'))
    expect(login).toHaveBeenCalledTimes(1)
  })

  it('sukces z ?redirect=//evil nawiguje na stronę główną', async () => {
    const user = userEvent.setup()
    const { router } = await renderLoginPage({ redirectTo: '//evil' })

    await user.type(screen.getByTestId('login-email'), 'user@example.com')
    await user.type(screen.getByTestId('login-password'), 'secret')
    await user.click(screen.getByTestId('login-submit'))

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })

  it('przełącza widoczność hasła', async () => {
    const user = userEvent.setup()
    await renderLoginPage()

    expect(screen.getByTestId('login-password')).toHaveAttribute('type', 'password')

    await user.click(screen.getByRole('button', { name: 'Pokaż hasło' }))

    expect(screen.getByTestId('login-password')).toHaveAttribute('type', 'text')
  })
})

describe('LoginPage — kanały OIDC i rejestracja', () => {
  it('bez kanałów nie ma przycisku ani separatora', async () => {
    await renderLoginPage()

    expect(screen.queryByTestId('login-channel-keycloak')).toBeNull()
    expect(screen.queryByText('lub')).toBeNull()
  })

  it('kanał keycloak prowadzi do backendu z bezpiecznym redirectem', async () => {
    server.use(channelsHandler([fixtureLoginChannel]))

    await renderLoginPage({ redirectTo: '/chat' })

    const link = await screen.findByTestId('login-channel-keycloak')
    expect(link).toHaveAttribute('href', '/api/v1/auth/login/keycloak?redirect=%2Fchat')
    expect(link).toHaveTextContent('Keycloak')
  })

  it('registerEnabled 1 pokazuje przełącznik rejestracji, a 0 go ukrywa', async () => {
    server.use(configHandler({ registerEnabled: 0, disablePasswordLogin: false }))
    await renderLoginPage()
    expect(screen.queryByRole('button', { name: 'Nie masz konta? Zarejestruj się' })).toBeNull()

    cleanup()
    server.use(configHandler({ registerEnabled: 1, disablePasswordLogin: false }))
    await renderLoginPage()
    expect(
      await screen.findByRole('button', { name: 'Nie masz konta? Zarejestruj się' }),
    ).toBeInTheDocument()
  })

  it('udana rejestracja wraca do logowania z komunikatem', async () => {
    const user = userEvent.setup()
    server.use(configHandler({ registerEnabled: 1, disablePasswordLogin: false }))
    await renderLoginPage()

    await user.click(await screen.findByRole('button', { name: 'Nie masz konta? Zarejestruj się' }))
    await user.type(screen.getByTestId('register-email'), 'nowy@example.com')
    await user.type(screen.getByTestId('register-nickname'), 'Nowy')
    await user.type(screen.getByTestId('register-password'), 'sekret')
    await user.click(screen.getByTestId('register-submit'))

    expect(await screen.findByText('Konto utworzone — zaloguj się.')).toBeInTheDocument()
    expect(screen.getByTestId('login-submit')).toBeInTheDocument()
  })

  it('błąd rejestracji pokazuje Alert z komunikatem backendu', async () => {
    const user = userEvent.setup()
    server.use(
      configHandler({ registerEnabled: 1, disablePasswordLogin: false }),
      http.post(apiUrl('/api/v1/users'), () =>
        HttpResponse.json({ code: 101, message: 'email already exists', data: false }),
      ),
    )
    await renderLoginPage()

    await user.click(await screen.findByRole('button', { name: 'Nie masz konta? Zarejestruj się' }))
    await user.type(screen.getByTestId('register-email'), 'nowy@example.com')
    await user.type(screen.getByTestId('register-nickname'), 'Nowy')
    await user.type(screen.getByTestId('register-password'), 'sekret')
    await user.click(screen.getByTestId('register-submit'))

    expect(await screen.findByTestId('register-error')).toHaveTextContent('email already exists')
  })

  it('powrót z formularza rejestracji do logowania', async () => {
    const user = userEvent.setup()
    server.use(configHandler({ registerEnabled: 1, disablePasswordLogin: false }))
    await renderLoginPage()

    await user.click(await screen.findByRole('button', { name: 'Nie masz konta? Zarejestruj się' }))
    await user.click(screen.getByRole('button', { name: 'Masz już konto? Zaloguj się' }))

    expect(screen.getByTestId('login-submit')).toBeInTheDocument()
    expect(screen.queryByTestId('register-submit')).toBeNull()
  })

  it('disablePasswordLogin ukrywa formularz hasła', async () => {
    server.use(configHandler({ registerEnabled: 0, disablePasswordLogin: true }))
    server.use(channelsHandler([fixtureLoginChannel]))

    await renderLoginPage()

    expect(await screen.findByTestId('login-channel-keycloak')).toBeInTheDocument()
    expect(screen.queryByTestId('login-password')).toBeNull()
    expect(screen.queryByTestId('login-submit')).toBeNull()
  })
})
