/**
 * Szkielet ładowania siatki kluczy (QA V12-z-2b MINOR-2): wiersze (`Skeleton`) zamiast gołego
 * szarego prostokąta, z identyfikatorem `keys-grid-skeleton` dla e2e.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { GridSkeleton } from './GridSkeleton'

afterEach(cleanup)

describe('GridSkeleton', () => {
  it('pokazuje nagłówek i wiersze szkieletu — nie jeden prostokąt', () => {
    render(<GridSkeleton />)

    const skeleton = screen.getByTestId('keys-grid-skeleton')
    expect(skeleton).toBeInTheDocument()
    // Nagłówek + 6 wierszy danych — szkielet ma przypominać siatkę (MINOR-2 z QA V12-z-2b).
    expect(skeleton.querySelectorAll('.MuiSkeleton-root').length).toBeGreaterThan(2)
    expect(skeleton).toHaveAttribute('aria-busy', 'true')
  })
})
