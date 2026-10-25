/**
 * Karta „Serwer MCP" (brief E6-2 T4): treść statyczna — adresy transportów z origin strony,
 * kopiowanie pełnego adresu do schowka oraz przykład konfiguracji klienta z placeholderem
 * klucza (nigdy prawdziwy klucz).
 */
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { McpServerCard } from './McpServerCard'

afterEach(() => {
  cleanup()
})

describe('McpServerCard', () => {
  it('pokazuje kartę z adresami transportów z origin strony', async () => {
    await renderWithProviders(<McpServerCard />)
    const origin = window.location.origin

    expect(screen.getByTestId('mcp-card')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Serwer MCP' })).toBeInTheDocument()
    expect(screen.getByTestId('mcp-url-http')).toHaveTextContent(`${origin}/mcp`)
    expect(screen.getByTestId('mcp-url-sse')).toHaveTextContent(`${origin}/sse`)
    // Notka z odesłaniem do runbooka (SC-E5-H9-08: tekst zamiast martwego linku).
    expect(screen.getByTestId('mcp-runbook-note')).toHaveTextContent(
      'Instrukcja: runbook administratora, §13 Serwer MCP',
    )
  })

  it('kopiowanie wywołuje navigator.clipboard.writeText z pełnym adresem', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<McpServerCard />)
    const origin = window.location.origin

    await user.click(screen.getByTestId('mcp-copy-http'))
    await expect(navigator.clipboard.readText()).resolves.toBe(`${origin}/mcp`)
    expect(screen.getByTestId('mcp-copy-http')).toHaveTextContent('Skopiowano')

    await user.click(screen.getByTestId('mcp-copy-sse'))
    await expect(navigator.clipboard.readText()).resolves.toBe(`${origin}/sse`)
  })

  it('przykład konfiguracji zawiera placeholder i nie zawiera prawdziwego klucza', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<McpServerCard />)

    const example = screen.getByTestId('mcp-example').textContent ?? ''
    expect(example).toContain('"wawelsky-dragon"')
    expect(example).toContain('Bearer <TWÓJ_KLUCZ_API>')
    expect(example, 'przykład nie może zawierać klucza').not.toMatch(/wd_[A-Za-z0-9]{16,}/)
    expect(example).not.toContain('ragflow-')

    await user.click(screen.getByTestId('mcp-copy-example'))
    await expect(navigator.clipboard.readText()).resolves.toBe(example)
  })
})

// Warianty HTTP (brief E6-2 T7): `navigator.clipboard` nie istnieje — ścieżka fallbacku.
// Bez `userEvent` (podstawia własny schowek): `fireEvent` + jawnie zdejmowany schowek
// i podstawiony `document.execCommand` (jsdom go nie definiuje).
describe('McpServerCard bez navigator.clipboard (HTTP)', () => {
  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    Reflect.deleteProperty(document, 'execCommand')
    cleanup()
  })

  it('fallback execCommand: pełny adres przechodzi przez zaznaczenie, znacznik „Skopiowano”', async () => {
    // Wcześniejsze testy (userEvent) dodają schowek — fallback wymaga jego braku.
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    let copiedViaFallback = ''
    document.execCommand = ((command: string) => {
      if (command !== 'copy') return false
      copiedViaFallback = document.querySelector('textarea')?.value ?? ''
      return true
    }) as typeof document.execCommand

    await renderWithProviders(<McpServerCard />)
    fireEvent.click(screen.getByTestId('mcp-copy-http'))

    await waitFor(() => expect(screen.getByTestId('mcp-copy-http')).toHaveTextContent('Skopiowano'))
    expect(copiedViaFallback).toBe(`${window.location.origin}/mcp`)
    expect(screen.queryByTestId('mcp-error-http')).not.toBeInTheDocument()
  })

  it('porażka kopiowania: komunikat błędu, bez „Skopiowano”, tekst zaznaczony', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    const execCommand = vi.fn().mockReturnValue(false)
    document.execCommand = execCommand as typeof document.execCommand

    await renderWithProviders(<McpServerCard />)
    fireEvent.click(screen.getByTestId('mcp-copy-sse'))

    const error = await screen.findByTestId('mcp-error-sse')
    expect(error).toHaveTextContent('Nie udało się skopiować')
    expect(screen.getByTestId('mcp-copy-sse')).toHaveTextContent('Kopiuj')
    expect(screen.getByTestId('mcp-copy-sse')).not.toHaveTextContent('Skopiowano')
    // Porażka zaznacza adres do ręcznej kopii (`selectElementContents`).
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.getSelection()?.toString()).toBe(`${window.location.origin}/sse`)
  })
})
