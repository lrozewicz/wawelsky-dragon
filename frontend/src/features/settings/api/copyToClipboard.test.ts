/**
 * `copyToClipboard` (brief E6-2 T7): trzy warianty — schowek asynchroniczny (secure context),
 * fallback `execCommand` (HTTP) i porażka. Kontrakt: zwraca `true/false`, nigdy nie rzuca.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyToClipboard, selectElementContents } from './copyToClipboard'

// jsdom nie ma `navigator.clipboard` (jak HTTP bez secure context) ani `execCommand` —
// każdy test ustawia jawnie to, co symuluje; wcześniejsze testy z `userEvent` mogą go dodawać.
function setClipboard(clipboard: unknown): void {
  Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true })
}

/** Atrapa `execCommand`, która zapamiętuje stan w chwili kopiowania (jak spy w e2e).
 *  jsdom nie definiuje `execCommand` wcale, więc `vi.spyOn` odpada — podstawiamy jawnie. */
function stubExecCommand(returns: boolean | Error): {
  selected: string
  textarea: HTMLTextAreaElement | null
  /** Rodzic tekstarki W CHWILI kopiowania (textarea jest usuwana przed końcem `await`). */
  host: Element | null
} {
  const state: { selected: string; textarea: HTMLTextAreaElement | null; host: Element | null } = {
    selected: '',
    textarea: null,
    host: null,
  }
  document.execCommand = ((command: string) => {
    if (command !== 'copy') return false
    state.textarea = document.querySelector('textarea')
    // jsdom nie odwzorowuje zaznaczenia kontrolki w `document.getSelection()` — czytamy
    // zaznaczenie tekstarki wprost (przeglądarka eksponuje je także w Selection, co pilnuje e2e).
    const textarea = state.textarea
    if (textarea !== null) {
      state.host = textarea.parentElement
      state.selected = textarea.value.slice(
        textarea.selectionStart ?? 0,
        textarea.selectionEnd ?? 0,
      )
    }
    if (returns instanceof Error) throw returns
    return returns
  }) as typeof document.execCommand
  return state
}

afterEach(() => {
  vi.restoreAllMocks()
  setClipboard(undefined)
  Reflect.deleteProperty(document, 'execCommand')
})

describe('copyToClipboard', () => {
  it('secure context: pisze przez navigator.clipboard i zwraca true', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard({ writeText })

    await expect(copyToClipboard('adres')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('adres')
  })

  it('schowek odrzucił zapis: próbuje fallbacku execCommand', async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error('denied')) })
    const state = stubExecCommand(true)

    await expect(copyToClipboard('adres')).resolves.toBe(true)
    expect(state.selected).toBe('adres')
  })

  it('brak navigator.clipboard (HTTP): fallback zaznacza ukrytą textarea i kopiuje', async () => {
    setClipboard(undefined)
    const state = stubExecCommand(true)

    await expect(copyToClipboard('https://example.test/mcp')).resolves.toBe(true)
    expect(state.selected).toBe('https://example.test/mcp')
    // Przepis z briefu: textarea poza ekranem, `readonly` ustawione przed zaznaczeniem.
    expect(state.textarea?.style.position).toBe('fixed')
    expect(state.textarea?.style.top).toBe('-1000px')
    expect(state.textarea?.getAttribute('readonly')).toBe('')
    // Sprzątnięcie: po próbie nie zostaje żadna textarea w dokumencie.
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })

  it('wywołanie z wnętrza dialogu: textarea doklejona do dialogu, fokus wraca na przycisk', async () => {
    // Defekt MAJOR z QA-UI E6-2-2: focus trap dialogu MUI zabiera fokus elementom poza
    // `[role="dialog"]`, więc textarea przy `document.body` traciła zaznaczenie, zanim
    // zadziałał `execCommand('copy')` — schowek dostawał pusty tekst.
    setClipboard(undefined)
    const state = stubExecCommand(true)
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    const button = document.createElement('button')
    dialog.appendChild(button)
    document.body.appendChild(dialog)
    button.focus()

    await expect(copyToClipboard('token w dialogu')).resolves.toBe(true)
    // `host` zapamiętany w chwili kopiowania — textarea jest już usunięta po `await`.
    expect(state.host).toBe(dialog)
    expect(state.selected).toBe('token w dialogu')
    // Po kopiowaniu fokus wraca na element sprzed tekstarki (klawiatura nie gubi miejsce).
    expect(document.activeElement).toBe(button)
    dialog.remove()
  })

  it('execCommand zwrócił false: zwraca false (porażka, bez rzucania)', async () => {
    setClipboard(undefined)
    stubExecCommand(false)

    await expect(copyToClipboard('adres')).resolves.toBe(false)
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })

  it('execCommand rzuca: zwraca false, nigdy nie rzuca', async () => {
    setClipboard(undefined)
    stubExecCommand(new Error('not implemented'))

    await expect(copyToClipboard('adres')).resolves.toBe(false)
  })

  it('selectElementContents zaznacza treść elementu do ręcznego kopiowania', () => {
    const element = document.createElement('p')
    element.textContent = 'adres do zaznaczenia'
    document.body.appendChild(element)

    selectElementContents(element)

    expect(document.getSelection()?.toString()).toBe('adres do zaznaczenia')
    element.remove()
  })
})
