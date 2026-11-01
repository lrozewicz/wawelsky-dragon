import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { UserLanguageDialog } from './UserLanguageDialog'

afterEach(cleanup)

describe('UserLanguageDialog', () => {
  it('konto bez wyboru pokazuje „Nie ustawiono”, a zapis wysyła wybrany język', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch(apiUrl('/api/wd/v1/users/u-1'), async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ data: makeWdUser({ language: 'en' }) })
      }),
    )
    const onClose = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(
      <UserLanguageDialog open user={makeWdUser({ language: '' })} onClose={onClose} />,
    )

    const field = screen.getByRole('combobox', { name: 'Język' })
    expect(field).toHaveTextContent('Nie ustawiono')
    await user.click(field)
    await user.click(await screen.findByRole('option', { name: 'English' }))
    await user.click(screen.getByTestId('admin-user-language-save'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(bodies).toEqual([{ language: 'en' }])
  })

  it('starszą wartość „Polish” pokazuje jako Polski', async () => {
    await renderWithProviders(
      <UserLanguageDialog open user={makeWdUser({ language: 'Polish' })} onClose={vi.fn()} />,
    )

    expect(screen.getByRole('combobox', { name: 'Język' })).toHaveTextContent('Polski')
  })
})
