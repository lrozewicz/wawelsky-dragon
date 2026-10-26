/**
 * Pytanie „Pod jest wyłączony — włączyć?” otwierane z dowolnego miejsca (start parsowania w
 * tabeli plików, przesyłanie plików). Mały magazyn poza Reactem: `useParseDocuments` woła
 * `openRunpodPrompt`, a `RunpodPromptHost` (w powłoce aplikacji) subskrybuje i pokazuje okno.
 */

import { useSyncExternalStore } from 'react'

import type { RunpodPreflight } from './api'

export type RunpodPrompt = {
  datasetId: string
  documentIds: string[]
  preflight: RunpodPreflight
}

let current: RunpodPrompt | null = null
let hostMounted = 0
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

/** Czy jest host, który pokaże okno; bez niego parsowanie idzie dalej bez pytania. */
export function hasRunpodPromptHost(): boolean {
  return hostMounted > 0
}

export function registerRunpodPromptHost(): () => void {
  hostMounted += 1
  return () => {
    hostMounted -= 1
  }
}

export function openRunpodPrompt(prompt: RunpodPrompt): void {
  current = prompt
  emit()
}

export function closeRunpodPrompt(): void {
  current = null
  emit()
}

export function useRunpodPrompt(): RunpodPrompt | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => current,
  )
}
