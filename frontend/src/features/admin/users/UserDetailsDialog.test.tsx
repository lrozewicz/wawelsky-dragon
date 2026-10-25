/**
 * Dialog szczegółów użytkownika (kontrakt WP E3-6c2 §T4 pkt 3): wszystkie pola konta, kreska dla
 * pustej strefy czasowej, „Nigdy” bez ostatniego logowania i daty w formacie języka interfejsu.
 */

import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { makeWdUser } from '../../../test/msw/handlers'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { UserDetailsDialog } from './UserDetailsDialog'

afterEach(cleanup)

describe('UserDetailsDialog', () => {
  it('pokazuje pola konta, kreskę i „Nigdy” dla pustych wartości', async () => {
    const user = makeWdUser({
      id: 'u-jan',
      email: 'jan@wd.test',
      nickname: 'Jan',
      timezone: null,
      last_login_at: null,
    })
    await renderWithProviders(<UserDetailsDialog open user={user} onClose={vi.fn()} />)

    expect(screen.getByText('jan@wd.test')).toBeInTheDocument()
    expect(screen.getByText('Jan')).toBeInTheDocument()
    expect(screen.getByText('Użytkownik')).toBeInTheDocument()
    expect(screen.getByText('Lokalne')).toBeInTheDocument()
    expect(screen.getByText('u-jan')).toBeInTheDocument()
    expect(screen.getByText('Nigdy')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('formatuje daty w języku interfejsu', async () => {
    const user = makeWdUser({ last_login_at: '2025-06-01T10:30:00Z' })
    await renderWithProviders(<UserDetailsDialog open user={user} onClose={vi.fn()} />)

    const expected = new Date('2025-06-01T10:30:00Z').toLocaleString('pl')
    expect(screen.getByText(expected)).toBeInTheDocument()
    expect(screen.queryByText('Nigdy')).not.toBeInTheDocument()
  })
})
