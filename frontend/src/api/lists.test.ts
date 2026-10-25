import { describe, expect, it } from 'vitest'
import { ApiError } from './envelope'
import { unwrapList } from './lists'

const a = { id: 'a' }
const b = { id: 'b' }
const c = { id: 'c' }
const x = { id: 'x' }
const s = { id: 's' }

/** Wyłuskuje rzucony ApiError, żeby test sprawdził jego pola. */
function caught(fn: () => unknown): ApiError {
  try {
    fn()
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('oczekiwano ApiError, a nic nie zostało rzucone')
}

describe('unwrapList — datasets', () => {
  it('czyta top-level total_datasets', () => {
    expect(unwrapList('datasets', { code: 0, data: [a, b], total_datasets: 7 })).toEqual({
      items: [a, b],
      total: 7,
    })
  })

  it('bez total_datasets liczy długość tablicy', () => {
    expect(unwrapList('datasets', { code: 0, data: [a, b] })).toEqual({
      items: [a, b],
      total: 2,
    })
  })

  it('rzuca ApiError(-1) gdy data nie jest tablicą', () => {
    const error = caught(() => unwrapList('datasets', { code: 0, data: 'zły' }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: datasets')
    expect(error.httpStatus).toBe(200)
  })

  it('używa podanego httpStatus w błędzie kształtu', () => {
    const error = caught(() => unwrapList('datasets', { code: 0, data: 'zły' }, 502))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: datasets')
    expect(error.httpStatus).toBe(502)
  })
})

describe('unwrapList — documents', () => {
  it('czyta data.docs i data.total', () => {
    expect(unwrapList('documents', { code: 0, data: { docs: [a], total: 5 } })).toEqual({
      items: [a],
      total: 5,
    })
  })

  it('bez total liczy długość docs', () => {
    expect(unwrapList('documents', { code: 0, data: { docs: [a, b] } })).toEqual({
      items: [a, b],
      total: 2,
    })
  })

  it('rzuca ApiError(-1) gdy data nie jest obiektem', () => {
    const error = caught(() => unwrapList('documents', { code: 0, data: 'zły' }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: documents')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError(-1) gdy docs nie jest tablicą', () => {
    const error = caught(() => unwrapList('documents', { code: 0, data: { docs: {}, total: 1 } }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: documents')
    expect(error.httpStatus).toBe(200)
  })
})

describe('unwrapList — chunks', () => {
  it('zwraca items, total i doc', () => {
    expect(
      unwrapList('chunks', { code: 0, data: { chunks: [c], doc: { id: 'd' }, total: 9 } }),
    ).toEqual({ items: [c], total: 9, doc: { id: 'd' } })
  })

  it('rzuca ApiError(-1) gdy chunks nie jest tablicą', () => {
    const error = caught(() => unwrapList('chunks', { code: 0, data: { chunks: 'zły' } }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: chunks')
    expect(error.httpStatus).toBe(200)
  })
})

describe('unwrapList — chats', () => {
  it('czyta data.chats i data.total (profil 0.27)', () => {
    expect(unwrapList('chats', { code: 0, data: { chats: [x], total: 3 } })).toEqual({
      items: [x],
      total: 3,
    })
  })

  it('przyjmuje data:[…] (profil 0.24) i liczy długość', () => {
    expect(unwrapList('chats', { code: 0, data: [x, x] })).toEqual({ items: [x, x], total: 2 })
  })

  it('rzuca ApiError(-1) dla złego kształtu', () => {
    const error = caught(() => unwrapList('chats', { code: 0, data: 'zły' }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: chats')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError(-1) gdy obiekt nie ma tablicy chats', () => {
    const error = caught(() => unwrapList('chats', { code: 0, data: { total: 3 } }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: chats')
    expect(error.httpStatus).toBe(200)
  })
})

describe('unwrapList — sessions', () => {
  it('czyta data:[…] i liczy długość', () => {
    expect(unwrapList('sessions', { code: 0, data: [s] })).toEqual({ items: [s], total: 1 })
  })

  it('rzuca ApiError(-1) gdy data nie jest tablicą', () => {
    const error = caught(() => unwrapList('sessions', { code: 0, data: { sessions: [s] } }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: sessions')
    expect(error.httpStatus).toBe(200)
  })
})

describe('unwrapList — koperta', () => {
  it('rzuca ApiError z code koperty przy code != 0', () => {
    const error = caught(() => unwrapList('documents', { code: 102, message: 'no', data: null }))

    expect(error.code).toBe(102)
    expect(error.message).toBe('no')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError z pustym message gdy koperta go nie ma', () => {
    const error = caught(() => unwrapList('chats', { code: 110, data: null }))

    expect(error.code).toBe(110)
    expect(error.message).toBe('')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError(-1) gdy ciało nie jest obiektem', () => {
    const error = caught(() => unwrapList('datasets', 'nie-obiekt'))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: datasets')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError(-1) gdy code koperty nie jest liczbą', () => {
    const error = caught(() => unwrapList('datasets', { code: '0', data: [] }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowy kształt listy: datasets')
    expect(error.httpStatus).toBe(200)
  })
})
