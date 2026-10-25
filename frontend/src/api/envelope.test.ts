import { describe, expect, it } from 'vitest'
import { ApiError, unwrap, unwrapEnvelope } from './envelope'

/** Odpowiedź transportowa bez ciała — interesuje nas tylko status/statusText. */
function http(status = 200, statusText = 'OK'): Response {
  return new Response(null, { status, statusText })
}

/** Wyłuskuje rzucony ApiError, żeby test sprawdził jego pola (nie tylko sam fakt rzutu). */
function caught(fn: () => unknown): ApiError {
  try {
    fn()
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('oczekiwano ApiError, a nic nie zostało rzucone')
}

describe('unwrap', () => {
  it('zwraca data gdy koperta ma code 0 (HTTP 200)', () => {
    const body = { code: 0, message: 'success', data: { a: 1 } }

    expect(unwrap({ data: body, response: http() })).toEqual({ a: 1 })
  })

  it('zwraca undefined gdy code 0 i brak data', () => {
    expect(unwrap({ data: { code: 0 }, response: http() })).toBeUndefined()
  })

  it('rzuca ApiError dla code != 0 przy HTTP 200', () => {
    const body = { code: 109, message: 'bad', data: false }

    const error = caught(() => unwrap({ data: body, response: http() }))

    expect(error.code).toBe(109)
    expect(error.message).toBe('bad')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError z pustym message gdy koperta nie ma message', () => {
    const error = caught(() => unwrap({ data: { code: 7 }, response: http(200) }))

    expect(error.code).toBe(7)
    expect(error.message).toBe('')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError z kodu i message błędu transportu (HTTP 500)', () => {
    const error = caught(() =>
      unwrap({ error: { code: 500, message: 'x' }, response: http(500, 'Internal Server Error') }),
    )

    expect(error.code).toBe(500)
    expect(error.message).toBe('x')
    expect(error.httpStatus).toBe(500)
  })

  it('rzuca ApiError ze statusu gdy error.code nie jest liczbą, a message jest tekstem', () => {
    const error = caught(() =>
      unwrap({ error: { code: '500', message: 'x' }, response: http(503, 'Service Unavailable') }),
    )

    expect(error.code).toBe(503)
    expect(error.message).toBe('x')
    expect(error.httpStatus).toBe(503)
  })

  it('rzuca ApiError ze statusText gdy error jest tekstem', () => {
    const error = caught(() => unwrap({ error: 'tekst', response: http(502, 'Bad Gateway') }))

    expect(error.code).toBe(502)
    expect(error.message).toBe('Bad Gateway')
    expect(error.httpStatus).toBe(502)
  })

  it('rzuca ApiError ze statusu gdy błąd transportu nie ma ciała', () => {
    const error = caught(() => unwrap({ response: http(503, 'Service Unavailable') }))

    expect(error.code).toBe(503)
    expect(error.message).toBe('Service Unavailable')
    expect(error.httpStatus).toBe(503)
  })

  it('rzuca ApiError(-1) gdy ciało odpowiedzi nie jest obiektem', () => {
    const error = caught(() => unwrap({ data: 'nie-obiekt', response: http() }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowa odpowiedź serwera')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError(-1) gdy ciałem odpowiedzi jest tablica', () => {
    const error = caught(() => unwrap({ data: [], response: http() }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowa odpowiedź serwera')
    expect(error.httpStatus).toBe(200)
  })

  it('rzuca ApiError(-1) gdy code koperty nie jest liczbą', () => {
    const error = caught(() => unwrap({ data: { code: '0', data: { a: 1 } }, response: http() }))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowa odpowiedź serwera')
    expect(error.httpStatus).toBe(200)
  })

  it('ApiError ma name "ApiError" i jest błędem', () => {
    const error = new ApiError(1, 'x', 200)

    expect(error).toBeInstanceOf(Error)
    expect(error.name).toBe('ApiError')
  })
})

describe('unwrapEnvelope', () => {
  it('zwraca data z koperty code 0 dla podanego statusu', () => {
    expect(unwrapEnvelope({ code: 0, message: 'success', data: 42 }, 201)).toBe(42)
  })

  it('rzuca ApiError dla code != 0 z podanym statusem', () => {
    const error = caught(() => unwrapEnvelope({ code: 5, message: 'e' }, 400))

    expect(error.code).toBe(5)
    expect(error.message).toBe('e')
    expect(error.httpStatus).toBe(400)
  })

  it('rzuca ApiError(-1) dla ciała nie-obiektu z podanym statusem', () => {
    const error = caught(() => unwrapEnvelope('x', 200))

    expect(error.code).toBe(-1)
    expect(error.message).toBe('Nieprawidłowa odpowiedź serwera')
    expect(error.httpStatus).toBe(200)
  })
})
