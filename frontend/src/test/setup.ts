import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './msw/server'

// Flaki pod obciążeniem CI/hosta (load ~20–30): domyślne 1 s `findBy*` bywa za krótkie na
// pierwszy render leniwego `MessageList` i ciężkich widoków. Semantyka testów bez zmian.
configure({ asyncUtilTimeout: 5000 })

// 08 §11.1 — MSW przechwytuje żądania w testach; nieobsłużone żądanie to błąd testu.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

// jsdom nie implementuje `ResizeObserver` (używa go np. `MessageList`); obserwacje i tak są
// bezprzedmiotowe bez silnika układu — wystarczy no-op z natychmiastowym rozłączeniem.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
