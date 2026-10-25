import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureUser } from '../../test/msw/handlers'
import type { FixtureChat, FixtureDataset } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { HomePage } from './HomePage'

afterEach(cleanup)

// N datasetów o kolejnych nazwach/id (kolejność z API nie ma znaczenia — bez sortowania w UI).
function makeDatasets(count: number): FixtureDataset[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `ds-${index + 1}`,
    name: `Baza ${index + 1}`,
    description: null,
    document_count: index,
  }))
}

function makeChats(count: number): FixtureChat[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `chat-${index + 1}`,
    name: `Czat ${index + 1}`,
    description: `Opis ${index + 1}`,
  }))
}

function datasetsHandler(items: FixtureDataset[]) {
  return http.get(apiUrl('/api/v1/datasets'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: items, total_datasets: items.length }),
  )
}

function chatsHandler(items: FixtureChat[]) {
  return http.get(apiUrl('/api/v1/chats'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: { chats: items, total: items.length } }),
  )
}

describe('HomePage', () => {
  it('wita nickname użytkownika w banerze', async () => {
    await renderWithProviders(<HomePage />)

    expect(screen.getByTestId('home-banner')).toHaveTextContent('Witaj w Wawelsky Dragon, User')
  })

  it('w banerze używa e-maila, gdy konto nie ma nickname', async () => {
    await renderWithProviders(<HomePage />, {
      auth: { user: { ...fixtureUser, nickname: '' } },
    })

    expect(screen.getByTestId('home-banner')).toHaveTextContent(fixtureUser.email)
  })

  it('bez datasetów pokazuje kartę tworzenia', async () => {
    await renderWithProviders(<HomePage />)

    const section = screen.getByTestId('home-section-datasets')
    const card = await within(section).findByTestId('resource-card')
    expect(card).toHaveAttribute('href', '/datasets?isCreate=true')
    expect(card).toHaveTextContent('Nie masz jeszcze baz wiedzy')
  })

  it('bez czatów karta tworzenia prowadzi do /chats?isCreate=true', async () => {
    await renderWithProviders(<HomePage />)

    const section = screen.getByTestId('home-section-apps')
    const card = await within(section).findByTestId('resource-card')
    expect(card).toHaveAttribute('href', '/chats?isCreate=true')
    expect(card).toHaveTextContent('Nie masz jeszcze czatów')
  })

  it('pokazuje 4 karty datasetów i kartę „Zobacz wszystkie”', async () => {
    server.use(datasetsHandler(makeDatasets(4)))

    await renderWithProviders(<HomePage />)

    const section = screen.getByTestId('home-section-datasets')
    await within(section).findByText('Baza 4')
    // 4 datasety + karta „Zobacz wszystkie”.
    expect(within(section).getAllByTestId('resource-card')).toHaveLength(5)
    expect(within(section).getByRole('link', { name: /Baza 1/ })).toHaveAttribute(
      'href',
      '/dataset/files/ds-1',
    )
    expect(within(section).getByRole('link', { name: 'Zobacz wszystkie' })).toHaveAttribute(
      'href',
      '/datasets',
    )
  })

  it('mini-karta datasetu nawiguje routerem; Ctrl+klik zostaje przeglądarce', async () => {
    server.use(datasetsHandler(makeDatasets(1)))

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<HomePage />, { routes: ['/dataset/files/$id'] })

    const section = screen.getByTestId('home-section-datasets')
    const card = await within(section).findByRole('link', { name: /Baza 1/ })

    // Ctrl+klik (nowa karta) — `fireEvent.click` zwraca `false` tylko, gdy `preventDefault` padło.
    const notPrevented = fireEvent.click(card, { ctrlKey: true, button: 0 })
    expect(notPrevented).toBe(true)
    expect(router.state.location.pathname).toBe('/')

    await user.click(card)
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/dataset/files/ds-1')
    })
  })

  it('przy błędzie pokazuje Alert, a „Ponów” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 })
        }
        const items = makeDatasets(1)
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: items,
          total_datasets: items.length,
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<HomePage />)

    const section = screen.getByTestId('home-section-datasets')
    expect(await within(section).findByRole('alert')).toHaveTextContent(
      'Nie udało się wczytać danych',
    )

    await user.click(within(section).getByRole('button', { name: 'Ponów' }))

    expect(await within(section).findByText('Baza 1')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('pokazuje ostatnie czaty z linkami do czatu', async () => {
    server.use(chatsHandler(makeChats(2)))

    await renderWithProviders(<HomePage />)

    const section = screen.getByTestId('home-section-apps')
    expect(await within(section).findByRole('link', { name: /Czat 1/ })).toHaveAttribute(
      'href',
      '/chat/chat-1',
    )
    // 2 czaty + karta „Zobacz wszystkie”.
    expect(within(section).getAllByTestId('resource-card')).toHaveLength(3)
    expect(within(section).getByRole('link', { name: 'Zobacz wszystkie' })).toHaveAttribute(
      'href',
      '/chats',
    )
  })

  it('przełączenie na Wyszukiwanie daje pusty stan bez żądania do /searches', async () => {
    let searchCalls = 0
    server.use(
      http.get(apiUrl('/api/v1/searches'), () => {
        searchCalls += 1
        return HttpResponse.json({ code: 0, message: 'success', data: [] })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<HomePage />)

    await user.click(screen.getByRole('button', { name: 'Wyszukiwanie' }))

    expect(await screen.findByText('Wyszukiwanie będzie dostępne wkrótce.')).toBeInTheDocument()
    expect(searchCalls).toBe(0)
  })

  it('nie pokazuje przycisku Agent bez flagi FEATURE_AGENT', async () => {
    await renderWithProviders(<HomePage />)

    expect(screen.queryByRole('button', { name: 'Agent' })).not.toBeInTheDocument()
  })
})
