/**
 * Testy komponentu powodu nieaktywnego przycisku (SC-V12-08, brief T5 pkt 2): tekst pod
 * wskazanym id, brak renderu bez powodu i zgodność `describedBy` z obecnością atrybutu.
 */

import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../test/renderWithProviders'
import { DisabledReason, describedBy } from './DisabledReason'

afterEach(cleanup)

describe('DisabledReason', () => {
  it('renderuje tekst powodu pod stałym id', async () => {
    await renderWithProviders(<DisabledReason id="save-reason" reason="Uzupełnij: Nazwa modelu" />)
    const hint = screen.getByText('Uzupełnij: Nazwa modelu')
    expect(hint.id).toBe('save-reason')
  })

  it('nie renderuje niczego bez powodu', async () => {
    await renderWithProviders(<DisabledReason id="save-reason" reason={null} />)
    expect(screen.queryByText('Uzupełnij: Nazwa modelu')).not.toBeInTheDocument()
    expect(document.getElementById('save-reason')).toBeNull()
  })

  it('describedBy zwraca id tylko wtedy, gdy powód istnieje', () => {
    expect(describedBy('save-reason', 'Brak zmian do zapisania')).toBe('save-reason')
    expect(describedBy('save-reason', null)).toBeUndefined()
  })
})
