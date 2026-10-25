/**
 * Etykieta bazy czatu spoza pobranej listy (SC-V12-z-D3, QA-UI: UUID zamiast nazwy): użytkownik,
 * któremu udostępniono czat, nie ma dostępu do bazy — chip pokazuje „Baza niedostępna (…xxxxxx)”
 * zamiast surowego id, a pozycja zostaje usuwalna (opcja jest na liście wyboru).
 */
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { chatDetail } from '../../../test/msw/handlers'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { AssistantTab } from './AssistantTab'
import { chatToFormValues } from './schema'

afterEach(cleanup)

describe('AssistantTab — bazy spoza pobranej listy (SC-V12-z-D3)', () => {
  it('niedostępna baza ma czytelną etykietę z ostatnimi 6 znakami id zamiast UUID', async () => {
    const values = chatToFormValues(chatDetail({ dataset_ids: ['0123456789abcdef234567'] }))

    await renderWithProviders(
      <AssistantTab values={values} datasets={[]} nameError={null} onUpdate={vi.fn()} />,
    )

    expect(screen.getByText('Baza niedostępna (…234567)')).toBeInTheDocument()
    expect(screen.queryByText('0123456789abcdef234567')).not.toBeInTheDocument()
  })

  it('pozycja niedostępnej bazy jest widoczna na liście wyboru i usuwalna', async () => {
    const values = chatToFormValues(chatDetail({ dataset_ids: ['0123456789abcdef234567'] }))
    const onUpdate = vi.fn()

    await renderWithProviders(
      <AssistantTab values={values} datasets={[]} nameError={null} onUpdate={onUpdate} />,
    )
    const user = userEvent.setup()

    await user.click(screen.getByLabelText(/Bazy wiedzy/))
    await user.click(await screen.findByRole('option', { name: 'Baza niedostępna (…234567)' }))

    // Usunięcie jedynej pozycji: pusta lista id w zmianie formularza.
    expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ dataset_ids: [] }))
  })
})
