/**
 * Menu akcji wiersza (kontrakt WP E3-6c2 §T3 pkt 5): pozycje zależne od konta (lokalne/SSO,
 * administrator/zwykły użytkownik), wywołanie `onAction(kind)` z zamknięciem menu oraz blokada
 * roli i usuwania na własnym koncie.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { makeWdUser } from '../../../test/msw/handlers'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { WdUser } from '../queries'

import { UserActionsMenu } from './UserActionsMenu'
import type { UserActionKind } from './UserActionsMenu'

afterEach(cleanup)

const LOCAL = makeWdUser({ id: 'u-jan', email: 'jan@wd.test' })
const OIDC = makeWdUser({ id: 'u-oidc', email: 'oidc@wd.test', auth_source: 'oidc' })

/** Renderuje menu i otwiera je przyciskiem akcji. */
async function openMenu(
  user: WdUser,
  selfId: string | null,
  onAction: (kind: UserActionKind) => void = () => undefined,
): Promise<ReturnType<typeof userEvent.setup>> {
  const actor = userEvent.setup()
  await renderWithProviders(<UserActionsMenu user={user} selfId={selfId} onAction={onAction} />)
  await actor.click(screen.getByTestId(`admin-user-actions-${user.id}`))
  return actor
}

describe('UserActionsMenu', () => {
  it('przycisk ma etykietę dostępności i testid z identyfikatorem konta', async () => {
    await renderWithProviders(<UserActionsMenu user={LOCAL} selfId={null} onAction={vi.fn()} />)

    expect(screen.getByTestId('admin-user-actions-u-jan')).toHaveAccessibleName('Akcje użytkownika')
  })

  it('wybór pozycji woła onAction(kind) i zamyka menu', async () => {
    const onAction = vi.fn()
    const actor = await openMenu(LOCAL, null, onAction)

    await actor.click(await screen.findByRole('menuitem', { name: 'Szczegóły' }))

    expect(onAction).toHaveBeenCalledWith('details')
    await waitFor(() =>
      expect(screen.queryByRole('menuitem', { name: 'Szczegóły' })).not.toBeInTheDocument(),
    )
  })

  it('pokazuje „Zmień hasło” tylko dla kont lokalnych', async () => {
    await openMenu(LOCAL, null)
    expect(await screen.findByRole('menuitem', { name: 'Zmień hasło' })).toBeInTheDocument()
  })

  it('ukrywa „Zmień hasło” dla kont SSO', async () => {
    await openMenu(OIDC, null)

    expect(await screen.findByRole('menuitem', { name: 'Klucze API' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Zmień hasło' })).not.toBeInTheDocument()
  })

  it('administratorowi proponuje odebranie roli, zwykłemu kontu nadanie', async () => {
    await openMenu(makeWdUser({ id: 'u-admin', is_superuser: true }), null)

    expect(
      await screen.findByRole('menuitem', { name: 'Odbierz administratora' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Nadaj administratora' })).not.toBeInTheDocument()
  })

  it('blokuje rolę i usuwanie na własnym koncie', async () => {
    await openMenu(LOCAL, LOCAL.id)

    // MUI nadaje pozycji listy `aria-disabled` (to `<li>`, nie `<button>`).
    expect(await screen.findByRole('menuitem', { name: 'Nadaj administratora' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(screen.getByRole('menuitem', { name: 'Usuń' })).toHaveAttribute('aria-disabled', 'true')
  })
})
