/**
 * Potwierdzenie zamknięcia szuflady ustawień z niezapisanymi zmianami (kontrakt WP E4-H1
 * §„Klucze i18n”): Escape, backdrop, X i „Anuluj” przy brudnym formularzu pytają o odrzucenie.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import {
  datasetsHandlers,
  fixtureChatDatasets,
  fixtureModel,
  modelsHandlers,
  resetSearchesFixtures,
  searchFixtureApp,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import type { SearchApp } from '../queries'

import { SearchSettingsDrawer } from './SearchSettingsDrawer'

afterEach(cleanup)
beforeEach(resetSearchesFixtures)

// Napisy z `locales/pl/{searches,common}.json` — interfejs PL jest domyślny; dialog
// „Odrzucić zmiany?” to wspólny `DiscardChangesDialog` (SC-V12-07) z kontekstem wyszukiwarki.
const NAME = /Nazwa wyszukiwarki/
const NEW_NAME = 'Nowa nazwa'
const DISCARD_TITLE = 'Odrzucić zmiany?'
const DISCARD_BODY = 'Niezapisane zmiany w ustawieniach wyszukiwarki zostaną utracone.'
const DISCARD_CONFIRM = 'Odrzuć'
const DISCARD_CANCEL = 'Wróć do edycji'
const CLOSE = 'Zamknij ustawienia'

/** Rejestr modeli: model czatu i rerank — comboboxy na potrzeby formularza. */
const MODEL_FIXTURES = [
  fixtureModel({ model_id: 'id-chat-1', name: 'fake-chat' }),
  fixtureModel({ model_id: 'id-rerank', name: 'fake-rerank', model_type: ['rerank'] }),
]

async function renderDrawer(app: SearchApp = searchFixtureApp, onClose: () => void = vi.fn()) {
  server.use(...datasetsHandlers(fixtureChatDatasets), ...modelsHandlers(MODEL_FIXTURES))
  const result = await renderWithProviders(
    <SearchSettingsDrawer app={app} open onClose={onClose} />,
  )
  await screen.findByLabelText(NAME)
  return { ...result, onClose }
}

/** Zmiana nazwy — czyni formularz brudnym (bez zapisu). */
async function editName(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const field = screen.getByLabelText(NAME)
  await user.clear(field)
  await user.type(field, NEW_NAME)
}

/** Dialog odrzucenia widoczny? */
function discardDialog(): HTMLElement | null {
  return screen.queryByText(DISCARD_TITLE)
}

describe('SearchSettingsDrawer — niezapisane zmiany', () => {
  it('Escape przy zmianach pyta o odrzucenie, a „Wróć do edycji” zostawia szufladę otwartą', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    await editName(user)

    await user.keyboard('{Escape}')

    expect(await screen.findByText(DISCARD_TITLE)).toBeInTheDocument()
    expect(screen.getByText(DISCARD_BODY)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: DISCARD_CANCEL }))

    await waitFor(() => expect(discardDialog()).not.toBeInTheDocument())
    expect(screen.getByLabelText(NAME)).toHaveValue(NEW_NAME)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('ponowne zamknięcie i „Odrzuć” woła onClose i zamyka pytanie', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    await editName(user)

    await user.keyboard('{Escape}')
    await screen.findByText(DISCARD_TITLE)
    await user.click(screen.getByRole('button', { name: DISCARD_CONFIRM }))

    expect(onClose).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(discardDialog()).not.toBeInTheDocument())
  })

  it('Escape bez zmian zamyka szufladę od razu', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(discardDialog()).not.toBeInTheDocument()
  })

  it('przycisk X przy zmianach pyta o odrzucenie', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    await editName(user)

    await user.click(screen.getByRole('button', { name: CLOSE }))

    expect(await screen.findByText(DISCARD_TITLE)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('przycisk „Anuluj” przy zmianach pyta o odrzucenie', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    await editName(user)

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(await screen.findByText(DISCARD_TITLE)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('klik w backdrop przy zmianach pyta o odrzucenie', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    await editName(user)
    const backdrop = document.querySelector('.MuiBackdrop-root')
    if (backdrop === null) throw new Error('Brak backdropu szuflady')

    await user.click(backdrop)

    expect(await screen.findByText(DISCARD_TITLE)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('udany zapis zamyka szufladę bez pytania', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    await editName(user)

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Zapisano ustawienia wyszukiwarki.')).toBeInTheDocument()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(discardDialog()).not.toBeInTheDocument()
  })

  it('powrót do wartości z search_config gasi pytanie o odrzucenie', async () => {
    const { onClose } = await renderDrawer()
    const user = userEvent.setup({ delay: null })
    const field = screen.getByLabelText(NAME)
    await editName(user)
    await user.clear(field)
    await user.type(field, searchFixtureApp.name)

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(discardDialog()).not.toBeInTheDocument()
  })
})
