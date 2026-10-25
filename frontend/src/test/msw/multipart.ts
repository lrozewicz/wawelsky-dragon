// Parser multipart/form-data na surowych bajtach żądania, dla handlerów MSW.
// `request.formData()` w Node (undici) tworzy własne `File` i pada na asercji wewnętrznej, gdy globalny `File`
// jest podmieniony przez jsdom (Node 24.16: `webidl.is.File(value)`), więc czytamy ciało sami.

export type MultipartFile = { field: string; name: string; type: string; size: number }
export type Multipart = { fields: Record<string, string>; files: MultipartFile[] }

const UTF8 = new TextDecoder('utf-8')

// `TextDecoder('latin1')` to windows-1252 (bajty 0x80–0x9F dają znaki > 255), więc bajty zamieniamy na znaki sami.
function toBytesString(buffer: ArrayBuffer): string {
  let out = ''
  for (const byte of new Uint8Array(buffer)) out += String.fromCharCode(byte)
  return out
}

// Ciało czytamy jako ciąg „1 znak = 1 bajt”: rozmiary plików są wtedy bajtowe, a napisy z nagłówków
// i pól tekstowych odtwarzamy z UTF-8 przez `fromBytes`.
function fromBytes(latin1: string): string {
  return UTF8.decode(Uint8Array.from(latin1, (ch) => ch.charCodeAt(0)))
}

export async function parseMultipart(request: Request): Promise<Multipart> {
  const contentType = request.headers.get('content-type') ?? ''
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType)
  const token = boundary?.[1] ?? boundary?.[2]
  const result: Multipart = { fields: {}, files: [] }
  if (token === undefined) return result
  const body = toBytesString(await request.arrayBuffer())
  for (const part of body.split(`--${token}`)) {
    const headEnd = part.indexOf('\r\n\r\n')
    if (headEnd === -1) continue
    const head = fromBytes(part.slice(0, headEnd))
    const content = part.slice(headEnd + 4).replace(/\r\n$/, '')
    const field = /name="([^"]*)"/i.exec(head)?.[1]
    if (field === undefined) continue
    const filename = /filename="([^"]*)"/i.exec(head)?.[1]
    if (filename === undefined) {
      result.fields[field] = fromBytes(content)
    } else {
      const type = /content-type:\s*([^\r\n]+)/i.exec(head)?.[1] ?? 'application/octet-stream'
      result.files.push({ field, name: filename, type, size: content.length })
    }
  }
  return result
}
