/**
 * Testy auto-zamknięcia, limitu 3 widocznych i duplikatów powiadomień (kontrakt WP E3-7 §C3).
 * Fałszywy zegar: `show`/`close` wołamy wprost przez przechwycone API (bez `userEvent`, które
 * pod fałszywym zegarem wymaga `advanceTimers`), a czas posuwamy `advanceTimersByTimeAsync`.
 */
import * as React from 'react'
import { act, cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { initI18n } from '../../i18n'
import { renderWithProviders } from '../../test/renderWithProviders'

import useNotifications from './useNotifications'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

type NotificationsApi = ReturnType<typeof useNotifications>

let api: NotificationsApi | null = null

/** Zapisuje API w module testu — mutacja globalnej zmiennej poza renderem (efektem) jest dozwolona. */
function captureApi(next: NotificationsApi): void {
  api = next
}

/** Komponent przechwytujący API, by wołać `show`/`close` bez interakcji z DOM. */
function Capture(): null {
  const notifications = useNotifications()
  React.useEffect(() => {
    captureApi(notifications)
  }, [notifications])
  return null
}

/** Tłumaczenia ładujemy przed fałszywym zegarem — inaczej dynamiczny `import()` czeka na timer. */
async function setup(): Promise<void> {
  await initI18n('pl')
  vi.useFakeTimers()
  await renderWithProviders(<Capture />)
}

function requireApi(): NotificationsApi {
  if (api === null) {
    throw new Error('API powiadomień nie zostało przechwycone')
  }
  return api
}

function show(message: string, options?: Parameters<NotificationsApi['show']>[1]): string {
  let key = ''
  act(() => {
    key = requireApi().show(message, options)
  })
  return key
}

function close(key: string): void {
  act(() => {
    requireApi().close(key)
  })
}

async function tick(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('useNotifications — auto-zamknięcie', () => {
  it('sukces znika domyślnie po 5000 ms', async () => {
    await setup()
    show('ok', { severity: 'success' })
    expect(screen.getByText('ok')).toBeInTheDocument()

    await tick(4999)
    expect(screen.getByText('ok')).toBeInTheDocument()

    await tick(1)
    expect(screen.queryByText('ok')).not.toBeInTheDocument()
  })

  it('ostrzeżenie znika domyślnie po 8000 ms', async () => {
    await setup()
    show('uwaga', { severity: 'warning' })

    await tick(7999)
    expect(screen.getByText('uwaga')).toBeInTheDocument()

    await tick(1)
    expect(screen.queryByText('uwaga')).not.toBeInTheDocument()
  })

  it('błąd nie znika — nadal widoczny po 60000 ms', async () => {
    await setup()
    show('blad', { severity: 'error' })

    await tick(60000)
    expect(screen.getByText('blad')).toBeInTheDocument()
  })

  it('jawny autoHideDuration ma pierwszeństwo nad domyślnym', async () => {
    await setup()
    show('szybko', { severity: 'success', autoHideDuration: 100 })

    await tick(100)
    expect(screen.queryByText('szybko')).not.toBeInTheDocument()
  })
})

describe('useNotifications — limit 3', () => {
  it('czwarte powiadomienie usuwa najstarsze; w kolejce zostają trzy', async () => {
    await setup()
    show('a')
    const kb = show('b')
    const kc = show('c')
    const kd = show('d')

    // Kolejka pokazywana po kolei — widoczne jest pierwsze z niej; 'a' wypadło przy dodaniu 'd'.
    expect(screen.queryByText('a')).not.toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()

    close(kb)
    expect(screen.getByText('c')).toBeInTheDocument()

    close(kc)
    expect(screen.getByText('d')).toBeInTheDocument()

    close(kd)
    expect(screen.queryByText('d')).not.toBeInTheDocument()
    expect(screen.queryByText('a')).not.toBeInTheDocument()
  })
})

describe('useNotifications — duplikaty', () => {
  it('ten sam tekst i severity po raz drugi zwraca klucz istniejącego i nic nie dodaje', async () => {
    await setup()
    const first = show('dup', { severity: 'info', key: 'one' })
    const second = show('dup', { severity: 'info', key: 'two' })
    expect(second).toBe(first)

    close(first)
    // Gdyby drugie trafiło do kolejki, po zamknięciu pierwszego zostałoby widoczne.
    expect(screen.queryByText('dup')).not.toBeInTheDocument()
  })

  it('ten sam tekst, inny severity, dodaje powiadomienie', async () => {
    await setup()
    const first = show('dup', { severity: 'info', key: 'one' })
    const second = show('dup', { severity: 'warning', key: 'two' })
    expect(second).not.toBe(first)
  })
})
