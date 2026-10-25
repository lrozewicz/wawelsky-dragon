import { describe, expect, it } from 'vitest'

import { parseMultipart } from './multipart'

function request(body: string): Request {
  return new Request('http://localhost/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'multipart/form-data; boundary=XX' },
    body,
  })
}

describe('parseMultipart', () => {
  it('czyta pola tekstowe i pliki (rozmiar w bajtach, nazwa UTF-8)', async () => {
    const parsed = await parseMultipart(
      request(
        '--XX\r\nContent-Disposition: form-data; name="parent_id"\r\n\r\nroot-1\r\n' +
          '--XX\r\nContent-Disposition: form-data; name="file"; filename="zażółć.txt"\r\n' +
          'Content-Type: text/plain\r\n\r\ntresc\r\n--XX--\r\n',
      ),
    )

    expect(parsed.fields).toEqual({ parent_id: 'root-1' })
    expect(parsed.files).toEqual([
      { field: 'file', name: 'zażółć.txt', type: 'text/plain', size: 5 },
    ])
  })

  it('bez boundary zwraca pusty wynik', async () => {
    const parsed = await parseMultipart(
      new Request('http://localhost/x', { method: 'POST', body: 'a' }),
    )

    expect(parsed).toEqual({ fields: {}, files: [] })
  })
})
